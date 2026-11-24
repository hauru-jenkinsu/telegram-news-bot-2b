import os
import csv
import json
import asyncio
import logging
import html
from pathlib import Path
from datetime import datetime, timezone

from telegram import Bot
from telegram.error import RetryAfter, TimedOut, NetworkError, TelegramError

ROOT = Path(__file__).resolve().parent
QUEUE = ROOT / "archive_queue.csv"
STATE = ROOT / "archive_progress.json"
TOKEN = os.environ["TOKEN"]
CHANNELS = [x.strip() for x in os.environ["CHANNELS"].split(",") if x.strip()]
DELAY_PER_CHANNEL = 3.2

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


class AmbiguousDelivery(RuntimeError):
    """The request may have reached Telegram, but its response was not received."""


def load_state():
    """Load progress. Supports the old list-only format for backward compatibility."""
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
    payload = {
        "done": sorted(state["done"]),
        "uncertain": state["uncertain"],
    }
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


async def send_one(bot, channel, item, state, lock, stop_event):
    key = channel + "|" + item["url"]
    if key in state["done"]:
        return

    message = (
        f"📰 <b>{html.escape(item['title'])}</b>\n"
        f"🔗 {html.escape(item['url'])}"
    )

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
            # Telegram explicitly rejected this attempt due to flood control;
            # waiting and retrying is safe.
            wait = float(getattr(e, "retry_after", 5)) + 1
            logging.warning("429 for %s; sleeping %.1fs", channel, wait)
            await asyncio.sleep(wait)
        except (TimedOut, NetworkError) as e:
            # The message may already have been accepted by Telegram. Do NOT
            # retry automatically: doing so could publish a duplicate.
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
            logging.exception(
                "DELIVERY UNCERTAIN channel=%s url=%s; automatic retry disabled",
                channel,
                item["url"],
            )
            raise AmbiguousDelivery(
                f"Delivery outcome is uncertain for {channel} / {item['url']}"
            ) from e
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
        logging.error(
            "There are %d uncertain deliveries. Resolve them in archive_progress.json "
            "before restarting. Examples: %s",
            len(state["uncertain"]),
            examples,
        )
        raise RuntimeError("Uncertain deliveries require manual reconciliation; no posts sent")

    total_targets = len(items) * len(CHANNELS)
    logging.info(
        "Queue=%d channels=%d already_done=%d total_targets=%d",
        len(items), len(CHANNELS), len(state["done"]), total_targets,
    )

    lock = asyncio.Lock()
    stop_event = asyncio.Event()
    async with Bot(TOKEN) as bot:
        results = await asyncio.gather(
            *(channel_worker(bot, ch, items, state, lock, stop_event) for ch in CHANNELS),
            return_exceptions=True,
        )

    errors = [result for result in results if isinstance(result, BaseException)]
    if errors:
        for error in errors:
            logging.error("Worker stopped: %r", error)
        raise RuntimeError(
            f"Publication stopped after an error. Completed targets: {len(state['done'])}/{total_targets}"
        )

    logging.info(
        "ARCHIVE RUN COMPLETE; sent targets=%d/%d",
        len(state["done"]),
        total_targets,
    )


if __name__ == "__main__":
    asyncio.run(main())
