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
            page.wait_for_timeout(8000)

            logging.info("MAX: пробуем отправку через JS")

            # 🔥 ВАЖНО: отправка через JS (без UI)
            page.evaluate(f"""
                (() => {{
                    const event = new KeyboardEvent('keydown', {{
                        bubbles: true,
                        cancelable: true,
                        keyCode: 13
                    }});

                    const textarea = document.querySelector('[contenteditable="true"]');
                    if (!textarea) {{
                        console.log("NO INPUT FOUND");
                        return;
                    }}

                    textarea.innerText = `{text}`;
                    textarea.dispatchEvent(event);
                }})()
            """)

            page.wait_for_timeout(3000)

            logging.info("MAX: отправка выполнена")

            browser.close()

    except Exception as e:
        logging.error(f"MAX ошибка: {e}")

async def send_to_max(text):
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _send_to_max_sync, text)
