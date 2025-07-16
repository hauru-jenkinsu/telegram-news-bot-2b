import feedparser
import telegram
import time
import json
import logging
import os
import re
import schedule
import asyncio
from urllib.parse import urljoin

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
REJECTED_NEWS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'rejected_news.json')
TEST_MODE = False  # Установите True для тестирования

# Инициализация бота
try:
    bot = telegram.Bot(token=TOKEN)
    logging.info("Бот успешно инициализирован")
except Exception as e:
    logging.error(f"Ошибка инициализации бота: {e}")
    exit(1)

# Загрузка обработанных ссылок
def load_processed_links():
    try:
        with open(PROCESSED_LINKS_FILE, "r", encoding='utf-8') as f:
            return set(json.load(f))
    except FileNotFoundError:
        logging.info(f"Файл {PROCESSED_LINKS_FILE} не найден, создается новый")
        return set()

# Сохранение обработанных ссылок
def save_processed_links(links):
    try:
        with open(PROCESSED_LINKS_FILE, "w", encoding='utf-8') as f:
            json.dump(list(links), f, ensure_ascii=False)
        logging.info(f"Сохранено {len(links)} ссылок в {PROCESSED_LINKS_FILE}")
    except Exception as e:
        logging.error(f"Ошибка сохранения ссылок: {e}")

# Сохранение отклоненных новостей
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

# Парсинг RSS
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
            else:
                logging.debug(f"Пропущена запись в {feed['url']}: title={title}, link={link}")
        logging.info(f"Спарсено {feed['name']} ({feed['url']}): найдено {len(news)} новостей")
        return news
    except Exception as e:
        logging.error(f"Ошибка парсинга RSS {feed['name']} ({feed['url']}): {e}")
        await bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"Ошибка парсинга RSS {feed['name']}: {e}")
        return []

# Публикация новости
async def publish_news(title, link):
    message = f"📰 {title}\n🔗 {link}"
    if TEST_MODE:
        logging.info(f"[ТЕСТ] Новость готова к отправке: {message}")
        print(f"[ТЕСТ] {message}")
        return True
    success = True
    for channel in CHANNELS:
        try:
            await bot.send_message(chat_id=channel, text=message)
            logging.info(f"Новость '{title}' отправлена в {channel}")
            time.sleep(0.5)
        except telegram.error.RetryAfter as e:
            logging.warning(f"Лимит Telegram, задержка {e.retry_after} сек")
            time.sleep(e.retry_after)
            await bot.send_message(chat_id=channel, text=message)
        except Exception as e:
            logging.error(f"Ошибка отправки в {channel}: {e}")
            await bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"Ошибка отправки в {channel}: {e}")
            success = False
    return success

# Проверка ключевых слов
def matches_keywords(text):
    text = text.lower()
    for keyword in KEYWORDS:
        if re.search(r'\b' + re.escape(keyword.lower()) + r'\b', text):
            logging.debug(f"Совпадение: '{keyword}' в '{text}'")
            return True
    return False

# Основная функция
async def main():
    logging.info(f"Запуск скрипта в {time.strftime('%Y-%m-%d %H:%M:%S')}")
    processed_links = load_processed_links()
    for feed in RSS_FEEDS:
        news = await parse_rss(feed)
        for item in news:
            title = item["title"]
            desc = item["desc"]
            link = item["link"]
            if link in processed_links:
                save_rejected_news(title, link, "дубликат")
                logging.debug(f"Новость отклонена (дубликат): {title}")
                continue
            if matches_keywords(title) or matches_keywords(desc):
                if await publish_news(title, link):
                    processed_links.add(link)
                else:
                    save_rejected_news(title, link, "ошибка отправки")
            else:
                save_rejected_news(title, link, "не соответствует ключевым словам")
                logging.debug(f"Новость отклонена (нет ключевых слов): {title}")
        save_processed_links(processed_links)
    logging.info("Парсинг завершен")

# Планировщик
def run_scheduler():
    schedule.every(1).hours.do(lambda: asyncio.run(main()))
    logging.info("Планировщик запущен: парсинг каждый час")
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())  # Запуск один раз для теста
    #run_scheduler()  # Запуск по расписанию
