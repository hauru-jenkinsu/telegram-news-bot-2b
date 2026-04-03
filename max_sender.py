import asyncio
import json
import random
import time
import websockets

WS_URL = "wss://ws-api.oneme.ru/websocket"

CHAT_ID = -72983374297821
USER_ID = 253598941  # твой id

async def send_to_max_ws(text):
    async with websockets.connect(WS_URL) as ws:

        # 👉 генерируем cid
        cid = -int(time.time() * 1000)

        payload = {
            "ver": 11,
            "cmd": 0,
            "seq": random.randint(1, 1000),
            "opcode": 64,
            "payload": {
                "chatId": CHAT_ID,
                "message": {
                    "text": text,
                    "cid": cid,
                    "elements": [],
                    "attaches": []
                },
                "notify": True
            }
        }

        await ws.send(json.dumps(payload))

        print("MAX WS: отправлено")
