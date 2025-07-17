import os
import time
import json
import logging
import re
import feedparser
import schedule
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError
from dotenv import load_dotenv
from urllib.parse import urljoin

# Настройка логирования
log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'parser.log')
logging.basicConfig(
    filename=log_file,
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logging.getLogger().addHandler(logging.StreamHandler())

# Загрузка переменных окружения
load_dotenv()

# Конфигурация
TOKEN = os.getenv("TOKEN")
CHANNELS = os.getenv("CHANNELS", "").split(",")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

PROCESSED_LINKS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'processed_links.json')
REJECTED_NEWS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'rejected_news.json')

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


def load_processed_links():
    try:
        with open(PROCESSED_LINKS_FILE, "r", encoding='utf-8') as f:
            return set(json.load(f))
    except FileNotFoundError:
        logging.info("Файл processed_links.json не найден. Создается новый.")
        return set()


def save_processed_links(links):
    try:
        with open(PROCESSED_LINKS_FILE, "w", encoding='utf-8') as f:
            json.dump(list(links), f, ensure_ascii=False)
        logging.info(f"Сохранено {len(links)} ссылок")
    except Exception as e:
        logging.error(f"Ошибка при сохранении processed_links: {e}")


def save_rejected_news(title, link, reason):
    try:
        rejected = []
        if os.path.exists(REJECTED_NEWS_FILE):
            with open(REJECTED_NEWS_FILE, "r", encoding='utf-8') as f:
                rejected = json.load(f)
        rejected.append({
            "title": title,
            "link": link,
            "reason": reason,
            "time": time.strftime("%Y-%m-%d %H:%M:%S")
        })
        with open(REJECTED_NEWS_FILE, "w", encoding='utf-8') as f:
            json.dump(rejected, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Ошибка сохранения отклоненной новости: {e}")


def matches_keywords(text):
    text = text.lower()
    for keyword in KEYWORDS:
        if re.search(r'\b' + re.escape(keyword.lower()) + r'\b', text):
            return True
    return False


def parse_feed(feed):
    try:
        parsed = feedparser.parse(feed["url"])
        if not parsed.entries and feed.get("fallback"):
            parsed = feedparser.parse(feed["fallback"])
        return parsed.entries[:5]
    except Exception as e:
        logging.error(f"Ошибка парсинга {feed['name']}: {e}")
        return []


async def publish_news(title, link):
    message = f"📰 <b>{title}</b>\n🔗 {link}"
    if TEST_MODE:
        logging.info(f"[ТЕСТ] Новость готова к отправке: {message}")
        print(f"[ТЕСТ] {message}")
        return True

    success = True

    for channel in CHANNELS:
        if not channel.strip():
            logging.warning("Пропущен пустой chat_id в списке CHANNELS")
            continue
        try:
            await bot.send_message(chat_id=channel.strip(), text=message, parse_mode=telegram.constants.ParseMode.HTML)
            await asyncio.sleep(2)
        except Exception as e:
            logging.error(f"Ошибка отправки в {channel}: {e}")
            success = False
            try:
                if ADMIN_CHAT_ID:
                    await bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"Ошибка отправки в {channel}: {e}")
            except Exception as e_admin:
                logging.error(f"Ошибка при уведомлении администратора: {e_admin}")
    return success

def main():
    logging.info(f"Запуск скрипта: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    processed_links = load_processed_links()

    for feed in RSS_FEEDS:
        entries = parse_feed(feed)
        for entry in entries:
            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()
            desc = entry.get("summary", entry.get("description", "")).strip()

            if not title or not link:
                continue

            if link in processed_links:
                save_rejected_news(title, link, "дубликат")
                continue

            if matches_keywords(title) or matches_keywords(desc):
                if publish_news(title, link):
                    processed_links.add(link)
                else:
                    save_rejected_news(title, link, "ошибка отправки")
            else:
                save_rejected_news(title, link, "не соответствует ключевым словам")

    save_processed_links(processed_links)
    logging.info("Завершение работы скрипта")


# Запуск по расписанию
def run_scheduler():
    schedule.every(1).hours.do(main)
    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()  # можно заменить на run_scheduler() для фоновой работы
