import os
import time
import json
import logging
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

# MAX
MAX_CHAT_ID = -72955706374877
MAX_USER_ID = 253598941

bot = Bot(token=TOKEN)

# ------------------ FILES ------------------

PROCESSED_LINKS_FILE = "processed_links.json"

# ------------------ RSS ------------------

RSS_FEEDS = [
    {"url": "https://lenta.ru/rss/news/"},
]

# ------------------ MAX ------------------

def generate_cid():
    return -int(time.time() * 1000)

def send_to_max(text):
    try:
        logging.info("MAX: попытка отправки")

        ws = websocket.create_connection("wss://ws-api.oneme.ru/websocket")

        # INIT
        ws.send(json.dumps({
            "ver": 11,
            "cmd": 1,
            "seq": 1,
            "opcode": 1,
            "payload": {"interactive": True}
        }))
        time.sleep(0.3)

        # SESSION
        ws.send(json.dumps({
            "ver": 11,
            "cmd": 1,
            "seq": 2,
            "opcode": 19,
            "payload": {}
        }))
        time.sleep(0.3)

        # OPEN CHAT
        ws.send(json.dumps({
            "ver": 11,
            "cmd": 1,
            "seq": 3,
            "opcode": 65,
            "payload": {"chatId": MAX_CHAT_ID}
        }))
        time.sleep(0.3)

        # SEND
        ws.send(json.dumps({
            "ver": 11,
            "cmd": 0,
            "seq": 4,
            "opcode": 64,
            "payload": {
                "chatId": MAX_CHAT_ID,
                "message": {
                    "text": text,
                    "cid": generate_cid(),
                    "elements": [],
                    "attaches": []
                },
                "notify": True
            }
        }))

        time.sleep(0.5)
        ws.close()

        logging.info("MAX: отправлено")

    except Exception as e:
        logging.error(f"MAX ошибка: {e}")

# ------------------ UTILS ------------------

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

            # MAX сразу после TG
            send_to_max(f"{title}\n{link}")

            await asyncio.sleep(1)

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

            await publish_news(title, link)
            processed_links.add(link)

    save_processed_links(processed_links)

    logging.info("ФИНИШ")

if __name__ == "__main__":
    asyncio.run(main())
