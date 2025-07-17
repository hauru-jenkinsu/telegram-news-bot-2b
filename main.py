import feedparser
import telegram
import time
import json
import logging
import os
import re
import schedule
import asyncio
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

# Настройка логирования
log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'parser.log')
logging.basicConfig(
    filename=log_file,
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logging.getLogger().addHandler(logging.StreamHandler())

# Конфигурация
TOKEN = os.getenv("TOKEN")
CHANNELS = os.getenv("CHANNELS", "").split(",")
logging.info(f"Переменная CHANNELS: {CHANNELS}")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

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

PROCESSED_LINKS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'processed_links.json')
PROCESSED_TITLES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'processed_titles.json')
REJECTED_NEWS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'rejected_news.json')
TEST_MODE = False  # True — для отладки без публикации

# Инициализация бота
try:
    bot = telegram.Bot(token=TOKEN)
    logging.info("Бот успешно инициализирован")
except Exception as e:
    logging.error(f"Ошибка инициализации бота: {e}")
    exit(1)

# Загрузка и сохранение
def load_processed_links():
    try:
        with open(PROCESSED_LINKS_FILE, "r", encoding='utf-8') as f:
            return set(json.load(f))
    except FileNotFoundError:
        logging.info(f"Файл {PROCESSED_LINKS_FILE} не найден, создается новый")
        return set()

def save_processed_links(links):
    try:
        with open(PROCESSED_LINKS_FILE, "w", encoding='utf-8') as f:
            json.dump(list(links), f, ensure_ascii=False)
        logging.info(f"Сохранено {len(links)} ссылок в {PROCESSED_LINKS_FILE}")
    except Exception as e:
        logging.error(f"Ошибка сохранения ссылок: {e}")

def load_processed_titles():
    try:
        with open(PROCESSED_TITLES_FILE, "r", encoding='utf-8') as f:
            return set(json.load(f))
    except FileNotFoundError:
        logging.info(f"Файл {PROCESSED_TITLES_FILE} не найден, создается новый")
        return set()

def save_processed_titles(titles):
    try:
        with open(PROCESSED_TITLES_FILE, "w", encoding='utf-8') as f:
            json.dump(list(titles), f, ensure_ascii=False)
        logging.info(f"Сохранено {len(titles)} заголовков в {PROCESSED_TITLES_FILE}")
    except Exception as e:
        logging.error(f"Ошибка сохранения заголовков: {e}")

def save_rejected_news(title, link, reason):
    try:
        rejected = []
        if os.path.exists(REJECTED_NEWS_FILE):
            with open(REJECTED_NEWS_FILE, "r", encoding='utf-8') as f:
                rejected = json.load(f)
        rejected.append({"title": title, "link": link, "reason": reason, "time": time.strftime("%Y-%m-%d %H:%M:%S")})
        with open(REJECTED_NEWS_FILE, "w", encoding='utf-8') as f:
            json.dump(rejected, f, ensure_ascii=False, indent=2)
        logging.debug(f"Отклоненная новость сохранена: {title}")
    except Exception as e:
        logging.error(f"Ошибка сохранения отклоненной новости: {e}")

def normalize_url(url):
    try:
        parsed = urlparse(url)
        clean_query = {k: v for k, v in parse_qs(parsed.query).items() if not k.startswith('utm_')}
        new_query = urlencode(clean_query, doseq=True)
        cleaned = parsed._replace(query=new_query, fragment='')
        return urlunparse(cleaned)
    except Exception as e:
        logging.warning(f"Не удалось нормализовать ссылку: {url} — {e}")
        return url

async def parse_rss(feed):
    try:
        feed_data = feedparser.parse(feed["url"])
        if not feed_data.entries and feed["fallback"]:
            logging.warning(f"Пустая RSS-лента: {feed['url']}, пробуем запасной URL: {feed['fallback']}")
            feed_data = feedparser.parse(feed["fallback"])
        if not feed_data.entries:
            logging.warning(f"Пустая RSS-лента: {feed['name']} ({feed['url']})")
            await bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"Пустая RSS-лента: {feed['name']} ({feed['url']})")
            return []
        news = []
        for entry in feed_data.entries[:5]:
            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()
            desc = entry.get("summary", entry.get("description", "")).strip()
            if title and link:
                news.append({"title": title, "link": link, "desc": desc})
        logging.info(f"Спарсено {feed['name']}: {len(news)} новостей")
        return news
    except Exception as e:
        logging.error(f"Ошибка парсинга {feed['name']}: {e}")
        await bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"Ошибка парсинга RSS {feed['name']}: {e}")
        return []

async def publish_news(title, link):
    message = f"📰 {title}\n🔗 {link}"
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
            await bot.send_message(chat_id=channel.strip(), text=message)
            await asyncio.sleep(2)
        except Exception as e:
            logging.error(f"Ошибка отправки в {channel}: {e}")
            success = False
            if ADMIN_CHAT_ID:
                try:
                    await bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"Ошибка отправки в {channel}: {e}")
                except Exception as e_admin:
                    logging.error(f"Ошибка при оповещении админа: {e_admin}")
    return success

def matches_keywords(text):
    text = text.lower()
    for keyword in KEYWORDS:
        if re.search(r'\b' + re.escape(keyword.lower()) + r'\b', text):
            return True
    return False

async def main():
    logging.info(f"Запуск: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    processed_links = load_processed_links()
    processed_titles = load_processed_titles()

    for feed in RSS_FEEDS:
        news = await parse_rss(feed)
        for item in news:
            title = item["title"]
            desc = item["desc"]
            link = item["link"]
            normalized_link = normalize_url(link)

            if normalized_link in processed_links or title in processed_titles:
                save_rejected_news(title, link, "дубликат")
                continue

            if matches_keywords(title) or matches_keywords(desc):
                if await publish_news(title, link):
                    processed_links.add(normalized_link)
                    processed_titles.add(title)
                else:
                    save_rejected_news(title, link, "ошибка отправки")
            else:
                save_rejected_news(title, link, "не соответствует ключевым словам")

    save_processed_links(processed_links)
    save_processed_titles(processed_titles)
    logging.info("Парсинг завершен")

# Для отладки:
if __name__ == "__main__":
    asyncio.run(main())
