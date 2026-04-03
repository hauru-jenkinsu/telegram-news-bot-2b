import asyncio
import logging
from playwright.sync_api import sync_playwright

# 👉 ВСТАВЬ СЮДА СВОЮ ССЫЛКУ
MAX_CHAT_URL = "https://web.max.ru/-72983374297821"

logging.basicConfig(level=logging.INFO)

# ------------------ SYNC ЧАСТЬ ------------------

def _send_to_max_sync(text):
    try:
        logging.info("MAX: запуск браузера")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(storage_state="auth.json")
            page = context.new_page()

            # открываем группу
            page.goto(MAX_CHAT_URL)

            # ждём загрузку
            page.wait_for_timeout(7000)

            logging.info("MAX: ищем поле ввода")

            # универсальный селектор для чата
            input_box = page.locator("div[contenteditable='true']").first

            input_box.click(timeout=5000)
            input_box.fill(text)

            page.keyboard.press("Enter")

            logging.info("MAX: сообщение отправлено")

            browser.close()

    except Exception as e:
        logging.error(f"MAX ошибка: {e}")

# ------------------ ASYNC ОБЁРТКА ------------------

async def send_to_max(text):
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _send_to_max_sync, text)