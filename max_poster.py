import asyncio
import logging
from playwright.sync_api import sync_playwright

MAX_CHAT_URL = "https://web.max.ru/-72983374297821"

logging.basicConfig(level=logging.INFO)

def _send_to_max_sync(text):
    try:
        logging.info("MAX: запуск браузера")

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )

            context = browser.new_context(storage_state="auth.json")
            page = context.new_page()

            page.goto(MAX_CHAT_URL)

            logging.info(f"MAX URL: {page.url}")

            # ждём поле ввода (долго, потому что MAX тормозной)
            page.wait_for_selector("div[contenteditable='true']", timeout=30000)

            logging.info("MAX: вводим текст")

            input_box = page.locator("div[contenteditable='true']").first

            input_box.click()
            input_box.fill(text)

            page.keyboard.press("Enter")

            page.wait_for_timeout(2000)

            logging.info("MAX: отправлено")

            browser.close()

    except Exception as e:
        logging.error(f"MAX ошибка: {e}")

async def send_to_max(text):
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _send_to_max_sync, text)
