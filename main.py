import os
import time
import json
import logging
import re
import feedparser
import asyncio

from telegram import Bot
from telegram.constants import ParseMode
from dotenv import load_dotenv

from playwright.sync_api import sync_playwright

# ------------------ ЛОГИ ------------------

log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'parser.log')
logging.basicConfig(
    filename=log_file,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logging.getLogger().addHandler(logging.StreamHandler())

# ------------------ ENV ------------------

load_dotenv()

TOKEN = os.getenv("TOKEN")
CHANNELS = os.getenv("CHANNELS", "").split(",")

bot = Bot(token=TOKEN)

# ------------------ ФАЙЛЫ ------------------

PROCESSED_LINKS_FILE = "processed_links.json"

# ------------------ RSS ------------------

RSS_FEEDS = [
    {"url": "https://lenta.ru/rss/news/"},
]

# ------------------ MAX ------------------

def _send_to_max_sync(text):
    try:
        logging.info("MAX: открываем браузер")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(storage_state="auth.json")
            page = context.new_page()

            # открываем MAX
            page.goto("https://web.max.ru")

            # ждём загрузку
            page.wait_for_timeout(8000)

            logging.info("MAX: ищем канал")

            # 👉 КЛИК ПО КАНАЛУ
            page.locator("text=Информанто").first.click()

            page.wait_for_timeout(5000)

            logging.info("MAX: ищем поле ввода")

            # 👉 правильное поле ввода
            input_box = page.locator("div[contenteditable='true']").first

            input_box.click()
            input_box.fill(text)

            page.keyboard.press("Enter")

            logging.info("MAX: сообщение отправлено")

            browser.close()

    except Exception as e:
        logging.error(f"MAX ошибка: {e}")


async def send_to_max(text):
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _send_to_max_sync, text)

# ------------------ УТИЛЫ ------------------

def load_processed_links():
    try:
        with open(PROCESSED_LINKS_FILE, "r") as f:
            return set(json.load(f))
    except:
        return set()

def save_processed_links(links):
    with open(PROCESSED_LINKS_FILE, "w") as f:
        json.dump(list(links), f)

# ------------------ ФИЛЬТР ------------------

KEYWORDS = ["сво", "армия", "войска", "танк", "ракета"]

def matches_keywords(text):
    text = text.lower()
    return any(word in text for word in KEYWORDS)

# ------------------ POST ------------------

async def publish_news(title, link):
    message = f"📰 <b>{title}</b>\n🔗 {link}"

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
            await send_to_max(f"{title}\n{link}")

            await asyncio.sleep(2)

        except Exception as e:
            logging.error(f"Ошибка TG: {e}")

# ------------------ MAIN ------------------

async def main():
    logging.info("СТАРТ")

    processed_links = load_processed_links()

    for feed in RSS_FEEDS:
        parsed = feedparser.parse(feed["url"])

        for entry in parsed.entries[:5]:
            title = entry.get("title", "")
            link = entry.get("link", "")

            if not title or not link:
                continue

            if link in processed_links:
                continue

            if matches_keywords(title):
                await publish_news(title, link)
                processed_links.add(link)

    save_processed_links(processed_links)

    logging.info("ФИНИШ")

if __name__ == "__main__":
    asyncio.run(main())
