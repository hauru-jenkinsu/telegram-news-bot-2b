import os
import csv
import json
import asyncio
import logging
import html
from pathlib import Path
from datetime import datetime, timezone

import httpx
from telegram import Bot
from telegram.request import HTTPXRequest
from telegram.error import RetryAfter, TimedOut, NetworkError, TelegramError

ROOT = Path(__file__).resolve().parent
QUEUE = ROOT / "archive_queue.csv"
STATE = ROOT / "archive_progress.json"
TOKEN = os.environ["TOKEN"]
CHANNELS = [x.strip() for x in os.environ["CHANNELS"].split(",") if x.strip()]
DELAY_PER_CHANNEL = 3.2
POOL_SIZE = 20
POOL_TIMEOUT = 30.0
POOL_TIMEOUT_RETRIES = 10

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


class AmbiguousDelivery(RuntimeError):
    """Telegram may have accepted the message, but no response was received."""


def load_state():
    if not STATE.exists():
        return {"done": set(), "uncertain": {}}
    raw = json.loads(STATE.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return {"done": set(raw), "uncertain": {}}
    if not isinstance(raw, dict) or not isinstance(raw.get("done", []), list):
        raise RuntimeError("archive_progress.json has an unknown format; refusing to start")
    uncertain = raw.get("uncertain", {})
    if not isinstance(uncertain, dict):
        raise RuntimeError("The uncertain section in archive_progress.json is invalid")
    return {"done": set(raw.get("done", [])), "uncertain": uncertain}


def save_state(state):
    payload = {"done": sorted(state["done"]), "uncertain": state["uncertain"]}
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE)


def load_queue():
    with QUEUE.open(encoding="utf-8-sig", newline="") as f:
        items = list(csv.DictReader(f))
    required = {"sort_date_internal", "title", "url"}
    if not items or not required.issubset(items[0]):
        raise RuntimeError("archive_queue.csv is empty or has unexpected columns")
    return sorted(items, key=lambda x: (x["sort_date_internal"], x["url"]))


def is_pool_timeout(error):
    """httpx PoolTimeout means no HTTP request was sent to Telegram."""
    current = error
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if type(current).__name__ == "PoolTimeout":
            return True
        current = current.__cause__ or current.__context__
    return "Pool timeout: All connections in the connection pool are occupied" in str(error)


async def send_one(bot, channel, item, state, lock, stop_event):
    key = channel + "|" + item["url"]
    if key in state["done"]:
        return

    message = f"📰 <b>{html.escape(item['title'])}</b>\n🔗 {html.escape(item['url'])}"
    pool_retries = 0

    while not stop_event.is_set():
        try:
            await bot.send_message(
                chat_id=channel,
                text=message,
                parse_mode="HTML",
                disable_web_page_preview=False,
            )
            async with lock:
                state["done"].add(key)
                state["uncertain"].pop(key, None)
                save_state(state)
            logging.info("SENT channel=%s url=%s", channel, item["url"])
            return
        except RetryAfter as e:
            wait = float(getattr(e, "retry_after", 5)) + 1
            logging.warning("Telegram 429 for %s; sleeping %.1fs", channel, wait)
            await asyncio.sleep(wait)
        except TimedOut as e:
            if is_pool_timeout(e):
                pool_retries += 1
                if pool_retries > POOL_TIMEOUT_RETRIES:
                    stop_event.set()
                    logging.exception("HTTP pool remained unavailable; request was not sent. Stopping safely.")
                    raise RuntimeError("HTTP connection pool unavailable after repeated safe retries") from e
                wait = min(2 + pool_retries, 10)
                logging.warning(
                    "HTTP PoolTimeout for %s: request was NOT sent; safe retry %d/%d in %ds",
                    channel, pool_retries, POOL_TIMEOUT_RETRIES, wait,
                )
                await asyncio.sleep(wait)
                continue

            async with lock:
                state["uncertain"][key] = {
                    "channel": channel,
                    "title": item["title"],
                    "url": item["url"],
                    "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
                    "error": f"{type(e).__name__}: {e}",
                }
                save_state(state)
            stop_event.set()
            logging.exception("DELIVERY UNCERTAIN channel=%s url=%s; automatic retry disabled", channel, item["url"])
            raise AmbiguousDelivery(f"Delivery outcome is uncertain for {channel} / {item['url']}") from e
        except NetworkError as e:
            async with lock:
                state["uncertain"][key] = {
                    "channel": channel,
                    "title": item["title"],
                    "url": item["url"],
                    "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
                    "error": f"{type(e).__name__}: {e}",
                }
                save_state(state)
            stop_event.set()
            logging.exception("DELIVERY UNCERTAIN channel=%s url=%s; automatic retry disabled", channel, item["url"])
            raise AmbiguousDelivery(f"Delivery outcome is uncertain for {channel} / {item['url']}") from e
        except TelegramError:
            stop_event.set()
            logging.exception("Telegram API error channel=%s url=%s", channel, item["url"])
            raise


async def channel_worker(bot, channel, items, state, lock, stop_event):
    sent = 0
    try:
        for item in items:
            if stop_event.is_set():
                break
            key = channel + "|" + item["url"]
            if key in state["done"]:
                continue
            await send_one(bot, channel, item, state, lock, stop_event)
            sent += 1
            if not stop_event.is_set():
                await asyncio.sleep(DELAY_PER_CHANNEL)
        logging.info("CHANNEL STOPPED/COMPLETE channel=%s newly_sent=%d", channel, sent)
    except Exception:
        stop_event.set()
        raise


async def main():
    if not CHANNELS:
        raise RuntimeError("CHANNELS secret is empty")
    items = load_queue()
    state = load_state()
    if state["uncertain"]:
        examples = list(state["uncertain"].values())[:5]
        logging.error("There are %d uncertain deliveries. Resolve them in archive_progress.json before restarting. Examples: %s", len(state["uncertain"]), examples)
        raise RuntimeError("Uncertain deliveries require manual reconciliation; no posts sent")

    total_targets = len(items) * len(CHANNELS)
    logging.info("Queue=%d channels=%d already_done=%d total_targets=%d", len(items), len(CHANNELS), len(state["done"]), total_targets)
    lock = asyncio.Lock()
    stop_event = asyncio.Event()

    request = HTTPXRequest(
        connection_pool_size=POOL_SIZE,
        pool_timeout=POOL_TIMEOUT,
        connect_timeout=20.0,
        read_timeout=40.0,
        write_timeout=30.0,
    )
    async with Bot(TOKEN, request=request) as bot:
        results = await asyncio.gather(
            *(channel_worker(bot, ch, items, state, lock, stop_event) for ch in CHANNELS),
            return_exceptions=True,
        )

    errors = [result for result in results if isinstance(result, BaseException)]
    if errors:
        for error in errors:
            logging.error("Worker stopped: %r", error)
        raise RuntimeError(f"Publication stopped after an error. Completed targets: {len(state['done'])}/{total_targets}")
    logging.info("ARCHIVE RUN COMPLETE; sent targets=%d/%d", len(state["done"]), total_targets)


if __name__ == "__main__":
    asyncio.run(main())
