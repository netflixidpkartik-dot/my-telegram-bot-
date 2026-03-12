import asyncio
import json
import os
import random

from telethon import TelegramClient, events, Button
from telethon.errors import FloodWaitError, SessionPasswordNeededError

# ===== ENV VARIABLES =====

BOT_TOKEN = os.getenv("8665346412:AAF-QqT8nUot2xeoomXPzGjKt1lGFZni3f8")
API_ID = os.getenv("34564865")
API_HASH = os.getenv("07b94d63a077ddd7a222d64d8362c7b0")

if not BOT_TOKEN or not API_ID or not API_HASH:
    raise Exception("BOT_TOKEN / API_ID / API_HASH missing in environment variables")

API_ID = int(API_ID)

# =========================

CONFIG = "accounts.json"
DEFAULT_INTERVAL = 120

state = {}
broadcast_task = None


def load_cfg():
    if os.path.exists(CONFIG):
        with open(CONFIG) as f:
            return json.load(f)

    return {"owner": 0, "accounts": {}, "interval": DEFAULT_INTERVAL}


def save_cfg(c):
    with open(CONFIG, "w") as f:
        json.dump(c, f, indent=2)


async def get_groups(client):
    groups = []

    async for dialog in client.iter_dialogs():
        if dialog.is_group:
            groups.append(dialog)

    return groups


async def broadcast_account(label, acc, interval):

    client = TelegramClient(acc["session"], API_ID, API_HASH)
    await client.connect()

    msg = await client.get_messages("me", limit=1)

    if not msg:
        await client.disconnect()
        return

    message = msg[0]
    groups = await get_groups(client)

    for g in groups:

        try:

            if message.text:
                await client.send_message(g.id, message.text)

            elif message.media:
                await client.send_file(g.id, message.media, caption=message.text)

            delay = random.randint(interval, interval + 60)

            await asyncio.sleep(delay)

        except FloodWaitError as e:

            print("Flood wait:", e.seconds)
            await asyncio.sleep(e.seconds)

        except Exception as err:

            print("Send failed:", err)

    await client.disconnect()


async def broadcast_loop():

    while True:

        cfg = load_cfg()

        interval = cfg["interval"]
        accounts = cfg["accounts"]

        for label, acc in accounts.items():

            print("Running account:", label)

            await broadcast_account(label, acc, interval)

        await asyncio.sleep(300)


async def run_bot():

    global broadcast_task

    bot = TelegramClient("bot_session", API_ID, API_HASH)

    await bot.start(bot_token=BOT_TOKEN)

    print("BOT STARTED")

    @bot.on(events.NewMessage(pattern="/start"))
    async def start(event):

        cfg = load_cfg()

        if cfg["owner"] == 0:
            cfg["owner"] = event.sender_id
            save_cfg(cfg)

        if event.sender_id != cfg["owner"]:
            return

        await event.respond(
            "Ads Dashboard",
            buttons=[
                [Button.inline("Add Account", b"add")],
                [Button.inline("My Accounts", b"accs")],
                [Button.inline("Start Ads", b"start"),
                 Button.inline("Stop Ads", b"stop")],
                [Button.inline("Set Interval", b"interval")],
            ],
        )

    @bot.on(events.CallbackQuery)
    async def callback(event):

        global broadcast_task

        cfg = load_cfg()

        uid = event.sender_id

        if uid != cfg["owner"]:
            return

        data = event.data.decode()

        if data == "add":

            state[uid] = {"step": "phone"}

            await event.respond("Send phone number with country code")

        elif data == "accs":

            txt = "Accounts\n\n"

            for l, a in cfg["accounts"].items():
                txt += a["name"] + "\n"

            await event.respond(txt)

        elif data == "interval":

            state[uid] = {"step": "interval"}

            await event.respond("Send interval seconds")

        elif data == "start":

            if broadcast_task and not broadcast_task.done():
                return

            broadcast_task = asyncio.create_task(broadcast_loop())

            await event.respond("Ads Started")

        elif data == "stop":

            if broadcast_task:
                broadcast_task.cancel()

            await event.respond("Ads Stopped")

    @bot.on(events.NewMessage)
    async def handler(event):

        uid = event.sender_id

        cfg = load_cfg()

        if uid not in state:
            return

        step = state[uid]["step"]

        if step == "interval":

            cfg["interval"] = int(event.text)

            save_cfg(cfg)

            del state[uid]

            await event.respond("Interval Updated")

        elif step == "phone":

            phone = event.text.strip()

            label = f"acc{len(cfg['accounts']) + 1}"

            client = TelegramClient(f"session_{label}", API_ID, API_HASH)

            await client.connect()

            result = await client.send_code_request(phone)

            state[uid] = {
                "step": "otp",
                "client": client,
                "phone": phone,
                "hash": result.phone_code_hash,
                "label": label,
            }

            await event.respond("Send OTP")

        elif step == "otp":

            s = state[uid]

            client = s["client"]

            try:

                await client.sign_in(
                    phone=s["phone"],
                    code=event.text,
                    phone_code_hash=s["hash"],
                )

                me = await client.get_me()

                await client.disconnect()

                cfg["accounts"][s["label"]] = {
                    "session": f"session_{s['label']}",
                    "name": me.first_name,
                }

                save_cfg(cfg)

                del state[uid]

                await event.respond("Account Added")

            except SessionPasswordNeededError:

                state[uid]["step"] = "2fa"

                await event.respond("Send 2FA Password")

        elif step == "2fa":

            s = state[uid]

            client = s["client"]

            await client.sign_in(password=event.text)

            me = await client.get_me()

            await client.disconnect()

            cfg["accounts"][s["label"]] = {
                "session": f"session_{s['label']}",
                "name": me.first_name,
            }

            save_cfg(cfg)

            del state[uid]

            await event.respond("Account Added")

    await bot.run_until_disconnected()


asyncio.run(run_bot())
