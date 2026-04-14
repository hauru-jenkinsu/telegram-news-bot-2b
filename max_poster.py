import asyncio
from playwright.sync_api import sync_playwright

MAX_CHAT_URL = "https://web.max.ru/-72983374297821"

def _send(text):
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )

        context = browser.new_context(storage_state="auth.json")
        page = context.new_page()

        page.goto(MAX_CHAT_URL)

        # ждём загрузку MAX
        page.wait_for_timeout(8000)

        # вставка текста
        page.evaluate(f"""
            (() => {{
                const input = document.querySelector('[contenteditable="true"]');
                if (!input) return;

                input.innerText = `{text}`;
                input.dispatchEvent(new Event('input', {{ bubbles: true }}));
            }})()
        """)

        # отправка
        page.keyboard.press("Enter")

        page.wait_for_timeout(2000)

        browser.close()

async def send_to_max(text):
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _send, text)
