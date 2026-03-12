import asyncio
import json
import os
import random

from telethon import TelegramClient, events, Button
from telethon.errors import FloodWaitError, SessionPasswordNeededError
from telethon.tl.functions.channels import CreateChannelRequest

BOT_TOKEN = "8665346412:AAF-QqT8nUot2xeoomXPzGjKt1lGFZni3f8"
API_ID = 34564865
API_HASH = "07b94d63a077ddd7a222d64d8362c7b0"

CONFIG = "accounts.json"
REPLIED_FILE = "replied_users.json"

DEFAULT_INTERVAL = 90
CYCLE_DELAY = 60

state = {}
clients = {}
broadcast_task = None


def load_cfg():
    if os.path.exists(CONFIG):
        with open(CONFIG) as f:
            return json.load(f)
    return {"owner": 0, "accounts": {}, "interval": DEFAULT_INTERVAL, "auto_dm": ""}


def save_cfg(c):
    with open(CONFIG, "w") as f:
        json.dump(c, f, indent=2)


def load_replied():
    if os.path.exists(REPLIED_FILE):
        with open(REPLIED_FILE) as f:
            return json.load(f)
    return {}


def save_replied(data):
    with open(REPLIED_FILE, "w") as f:
        json.dump(data, f, indent=2)


async def create_logs_channel(client, label):
    result = await client(
        CreateChannelRequest(
            title=f"{label} Logs",
            about="Account logs",
            megagroup=False
        )
    )
    return result.chats[0].id


async def start_account(label, acc):

    client = TelegramClient(acc["session"], API_ID, API_HASH)
    await client.start()

    clients[label] = client

    cfg = load_cfg()
    auto_msg = cfg["auto_dm"]

    replied = load_replied()

    if label not in replied:
        replied[label] = []

    @client.on(events.NewMessage(incoming=True))
    async def dm_handler(event):

        if not auto_msg:
            return

        if not event.is_private or event.out:
            return

        uid = event.sender_id

        if uid in replied[label]:
            return

        try:
            await event.reply(auto_msg)
            replied[label].append(uid)
            save_replied(replied)
        except:
            pass


async def broadcast_cycle():

    cfg = load_cfg()
    interval = cfg["interval"]

    for label, acc in cfg["accounts"].items():

        if label not in clients:
            continue

        client = clients[label]

        msg = await client.get_messages("me", limit=1)

        if not msg:
            continue

        message = msg[0]

        success = 0
        failed = 0

        async for dialog in client.iter_dialogs():

            if not dialog.is_group:
                continue

            try:

                if message.text:
                    await client.send_message(dialog.id, message.text)

                elif message.media:
                    await client.send_file(
                        dialog.id,
                        message.media,
                        caption=message.text
                    )

                success += 1

                await client.send_message(
                    acc["log_channel"],
                    f"Sent → {dialog.name}"
                )

                await asyncio.sleep(random.randint(interval, interval + 30))

            except FloodWaitError as e:

                await client.send_message(
                    acc["log_channel"],
                    f"Flood wait {e.seconds}s"
                )

                await asyncio.sleep(e.seconds)

            except:

                failed += 1

                await client.send_message(
                    acc["log_channel"],
                    f"Failed → {dialog.name}"
                )

        await client.send_message(
            acc["log_channel"],
            f"Cycle done\nSuccess: {success}\nFailed: {failed}"
        )


async def broadcast_loop():

    while True:
        await broadcast_cycle()
        await asyncio.sleep(CYCLE_DELAY)


async def run_bot():

    global broadcast_task

    bot = TelegramClient("bot_session", API_ID, API_HASH)
    await bot.start(bot_token=BOT_TOKEN)

    cfg = load_cfg()

    for label, acc in cfg["accounts"].items():
        asyncio.create_task(start_account(label, acc))

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
                [Button.inline("Remove Account", b"del")],
                [Button.inline("Start Ads", b"start"),
                 Button.inline("Stop Ads", b"stop")],
                [Button.inline("Set Interval", b"interval")],
                [Button.inline("Set Auto DM", b"autodm")]
            ],
        )

    @bot.on(events.CallbackQuery)
    async def callback(event):

        global broadcast_task

        cfg = load_cfg()
        uid = event.sender_id
        data = event.data.decode()

        if uid != cfg["owner"]:
            return

        if data == "add":
            state[uid] = {"step": "phone"}
            await event.respond("Send phone number with country code")

        elif data == "interval":
            state[uid] = {"step": "interval"}
            await event.respond("Send interval seconds")

        elif data == "autodm":
            state[uid] = {"step": "autodm"}
            await event.respond("Send auto DM message")

        elif data == "start":

            if broadcast_task and not broadcast_task.done():
                return

            broadcast_task = asyncio.create_task(broadcast_loop())

            await event.respond("Ads Started")

        elif data == "stop":

            if broadcast_task:
                broadcast_task.cancel()

            await event.respond("Ads Stopped")

        elif data == "del":

            buttons = []

            for label, acc in cfg["accounts"].items():
                buttons.append(
                    [Button.inline(acc["name"], f"del_{label}".encode())]
                )

            await event.respond("Select account to remove", buttons=buttons)

        elif data.startswith("del_"):

            label = data.replace("del_", "")

            if label in cfg["accounts"]:

                del cfg["accounts"][label]
                save_cfg(cfg)

                await event.respond("Account removed")

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

            await event.respond("Interval updated")

        elif step == "autodm":

            cfg["auto_dm"] = event.text
            save_cfg(cfg)
            del state[uid]

            await event.respond("Auto DM updated")

        elif step == "phone":

            phone = event.text.strip()
            label = f"acc{len(cfg['accounts'])+1}"

            client = TelegramClient(f"session_{label}", API_ID, API_HASH)
            await client.connect()

            result = await client.send_code_request(phone)

            state[uid] = {
                "step": "otp",
                "client": client,
                "phone": phone,
                "hash": result.phone_code_hash,
                "label": label
            }

            await event.respond("Send OTP")

        elif step == "otp":

            s = state[uid]
            client = s["client"]

            try:

                await client.sign_in(
                    phone=s["phone"],
                    code=event.text,
                    phone_code_hash=s["hash"]
                )

                me = await client.get_me()

                log_channel = await create_logs_channel(client, s["label"])

                await client.disconnect()

                cfg["accounts"][s["label"]] = {
                    "session": f"session_{s['label']}",
                    "name": me.first_name,
                    "log_channel": log_channel
                }

                save_cfg(cfg)
                del state[uid]

                asyncio.create_task(
                    start_account(
                        s["label"],
                        cfg["accounts"][s["label"]]
                    )
                )

                await event.respond("Account added + logs channel created")

            except SessionPasswordNeededError:

                state[uid]["step"] = "2fa"
                await event.respond("Send 2FA password")

        elif step == "2fa":

            s = state[uid]
            client = s["client"]

            await client.sign_in(password=event.text)

            me = await client.get_me()

            log_channel = await create_logs_channel(client, s["label"])

            await client.disconnect()

            cfg["accounts"][s["label"]] = {
                "session": f"session_{s['label']}",
                "name": me.first_name,
                "log_channel": log_channel
            }

            save_cfg(cfg)
            del state[uid]

            asyncio.create_task(
                start_account(
                    s["label"],
                    cfg["accounts"][s["label"]]
                )
            )

            await event.respond("Account added + logs channel created")

    await bot.run_until_disconnected()


asyncio.run(run_bot())
