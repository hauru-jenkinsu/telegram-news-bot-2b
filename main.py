import os
import time
import json
import logging
import re
import feedparser
import asyncio
import random
import websocket

from telegram import Bot
from telegram.constants import ParseMode
from dotenv import load_dotenv

# ------------------ ЛОГИ ------------------

log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'parser.log')
logging.basicConfig(
    filename=log_file,
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logging.getLogger().addHandler(logging.StreamHandler())

# ------------------ ENV ------------------

load_dotenv()

TOKEN = os.getenv("TOKEN")
CHANNELS = os.getenv("CHANNELS", "").split(",")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

# 👉 MAX
MAX_CHAT_ID = -72955706374877
MAX_USER_ID = 253598941

# ------------------ FILES ------------------

PROCESSED_LINKS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'processed_links.json')
REJECTED_NEWS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'rejected_news.json')

# ------------------ RSS ------------------

RSS_FEEDS = [
    {"name": "lenta.ru", "url": "https://lenta.ru/rss/news/", "fallback": "https://lenta.ru/rss/"},
    {"name": "vpk.name", "url": "https://vpk.name/rss/", "fallback": None},
    {"name": "ria.ru", "url": "https://ria.ru/export/rss2/index.xml", "fallback": "https://ria.ru/export/rss2/army/index.xml"},
    {"name": "rg.ru", "url": "https://rg.ru/xml/index.xml", "fallback": None},
    {"name": "tass.ru", "url": "https://tass.ru/rss/v2.xml?sections=MjQ%3D", "fallback": None}
]

KEYWORDS = [
    "сво", "вс рф", "российские войска", "российские учения", "российская армия",
    "российское вооружение", "российская техника", "спецоперация", "военный",
    "армия", "учения", "войска", "техника", "одкб", "вооружение",
    "танк", "флот", "ракета", "оборона", "минобороны", "белоусов",
    "вооружённые силы", "конфликт", "наёмник", "всу"
]

bot = Bot(token=TOKEN)

# ------------------ MAX ------------------

def generate_cid():
    return -int(time.time() * 1000)

def send_to_max(text):
    try:
        logging.info("MAX: попытка отправки")

        ws = websocket.create_connection("wss://ws-api.oneme.ru/websocket")

        message = {
            "ver": 11,
            "cmd": 2,
            "seq": random.randint(1000, 9999),
            "opcode": 49,
            "payload": {
                "messages": [
                    {
                        "sender": MAX_USER_ID,
                        "text": text,
                        "type": "CHANNEL",
                        "cid": MAX_CHAT_ID,
                        "id": str(int(time.time() * 1000)),
                        "time": int(time.time() * 1000),
                        "attaches": []
                    }
                ]
            }
        }

        ws.send(json.dumps(message))
        ws.close()

        logging.info("MAX: отправлено")

    except Exception as e:
        logging.error(f"MAX ошибка: {e}")

# ------------------ UTILS ------------------

def load_processed_links():
    try:
        with open(PROCESSED_LINKS_FILE, "r", encoding='utf-8') as f:
            return set(json.load(f))
    except:
        return set()

def save_processed_links(links):
    with open(PROCESSED_LINKS_FILE, "w", encoding='utf-8') as f:
        json.dump(list(links), f, ensure_ascii=False)

def matches_keywords(text):
    text = text.lower()
    return any(re.search(r'\b' + re.escape(k) + r'\b', text) for k in KEYWORDS)

def parse_feed(feed):
    parsed = feedparser.parse(feed["url"])
    if not parsed.entries and feed.get("fallback"):
        parsed = feedparser.parse(feed["fallback"])
    return parsed.entries[:5]

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

            # 🔥 MAX СРАЗУ ПОСЛЕ TG
            send_to_max(f"{title}\n{link}")

            await asyncio.sleep(1)

        except Exception as e:
            logging.error(f"Ошибка TG: {e}")

    return True

# ------------------ MAIN ------------------

async def main():
    logging.info("СТАРТ СКРИПТА")

    processed_links = load_processed_links()

    for feed in RSS_FEEDS:
        entries = parse_feed(feed)

        for entry in entries:
            title = entry.get("title", "")
            link = entry.get("link", "")
            desc = entry.get("summary", "")

            if not title or not link:
                continue

            if link in processed_links:
                continue

            if matches_keywords(title) or matches_keywords(desc):
                await publish_news(title, link)
                processed_links.add(link)

    save_processed_links(processed_links)

    logging.info("ФИНИШ")

if __name__ == "__main__":
    asyncio.run(main())
