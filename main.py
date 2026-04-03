import os
import json
import logging
import feedparser
import asyncio

from telegram import Bot
from telegram.constants import ParseMode
from dotenv import load_dotenv

from playwright.sync_api import sync_playwright

# ------------------ ЛОГИ ------------------

logging.basicConfig(level=logging.INFO)

# ------------------ ENV ------------------

load_dotenv()

TOKEN = os.getenv("TOKEN")
CHANNELS = os.getenv("CHANNELS", "").split(",")

bot = Bot(token=TOKEN)

PROCESSED_LINKS_FILE = "processed_links.json"

# ------------------ MAX ------------------

def _send_to_max_sync(text):
    try:
        logging.info("MAX: старт")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(storage_state="auth.json")
            page = context.new_page()

            # 👉 СРАЗУ В ЧАТ
            page.goto("https://web.max.ru/-72955706374877")

            # короткое ожидание
            page.wait_for_timeout(7000)

            # поле ввода
            input_box = page.locator("div[contenteditable='true']").first

            input_box.click(timeout=5000)
            input_box.fill(text)

            page.keyboard.press("Enter")

            logging.info("MAX: отправлено")

            browser.close()

    except Exception as e:
        logging.error(f"MAX ошибка: {e}")


async def send_to_max(text):
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _send_to_max_sync, text)

# ------------------ FILES ------------------

def load_processed_links():
    try:
        with open(PROCESSED_LINKS_FILE, "r") as f:
            return set(json.load(f))
    except:
        return set()

def save_processed_links(links):
    with open(PROCESSED_LINKS_FILE, "w") as f:
        json.dump(list(links), f)

# ------------------ POST ------------------

async def publish_news(title, link):
    message = f"{title}\n{link}"

    for channel in CHANNELS:
        if not channel.strip():
            continue

        try:
            await bot.send_message(
                chat_id=channel.strip(),
                text=message,
                parse_mode=ParseMode.HTML
            )

            logging.info("TG: отправлено")

            # 👉 MAX
            await send_to_max(message)

            await asyncio.sleep(1)

        except Exception as e:
            logging.error(f"Ошибка TG: {e}")

# ------------------ MAIN ------------------

async def main():
    logging.info("СТАРТ")

    processed_links = load_processed_links()

    parsed = feedparser.parse("https://lenta.ru/rss/news/")

    sent = 0

    for entry in parsed.entries:
        if sent >= 2:  # 👉 ограничили, чтобы не висело
            break

        title = entry.get("title", "")
        link = entry.get("link", "")

        if not title or not link:
            continue

        if link in processed_links:
            continue

        await publish_news(title, link)
        processed_links.add(link)
        sent += 1

    save_processed_links(processed_links)

    logging.info("ФИНИШ")

if __name__ == "__main__":
    asyncio.run(main())
