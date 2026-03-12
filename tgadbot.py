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

CCONFIG = "accounts.json"

DEFAULT_INTERVAL = 90
CYCLE_DELAY = 60

state = {}
account_tasks = {}


def load_cfg():
    if os.path.exists(CONFIG):
        with open(CONFIG) as f:
            return json.load(f)

    return {"owner": 0, "accounts": {}, "interval": DEFAULT_INTERVAL}


def save_cfg(data):
    with open(CONFIG, "w") as f:
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


async def broadcast_account_loop(label, acc):

    client = TelegramClient(acc["session"], API_ID, API_HASH)

    await client.start()

    print("Account started:", label)

    while True:

        cfg = load_cfg()

        interval = cfg["interval"]

        msg = await client.get_messages("me", limit=1)

        if not msg:

            await asyncio.sleep(CYCLE_DELAY)

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

                await asyncio.sleep(
                    random.randint(interval, interval + 30)
                )

            except FloodWaitError as e:

                await client.send_message(
                    acc["log_channel"],
                    f"Flood wait {e.seconds}s"
                )

                await asyncio.sleep(e.seconds)

            except Exception:

                failed += 1

                await client.send_message(
                    acc["log_channel"],
                    f"Failed → {dialog.name}"
                )

        await client.send_message(
            acc["log_channel"],
            f"Cycle done\nSuccess: {success}\nFailed: {failed}"
        )

        await asyncio.sleep(CYCLE_DELAY)


async def start_accounts():

    cfg = load_cfg()

    for label, acc in cfg["accounts"].items():

        if label not in account_tasks:

            task = asyncio.create_task(
                broadcast_account_loop(label, acc)
            )

            account_tasks[label] = task


async def stop_accounts():

    for task in account_tasks.values():
        task.cancel()

    account_tasks.clear()


async def run_bot():

    bot = TelegramClient("bot_session", API_ID, API_HASH)

    await bot.start(bot_token=BOT_TOKEN)

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
                [Button.inline("Accounts", b"accs")],
                [Button.inline("Remove Account", b"del")],
                [Button.inline("Start Ads", b"start"),
                 Button.inline("Stop Ads", b"stop")],
                [Button.inline("Set Interval", b"interval")]
            ],
        )


    @bot.on(events.CallbackQuery)
    async def callback(event):

        cfg = load_cfg()

        uid = event.sender_id

        if uid != cfg["owner"]:
            return

        data = event.data.decode()

        if data == "start":

            await start_accounts()

            await event.respond("Ads Started")


        elif data == "stop":

            await stop_accounts()

            await event.respond("Ads Stopped")


        elif data == "interval":

            state[uid] = {"step": "interval"}

            await event.respond("Send group interval seconds")


        elif data == "accs":

            txt = "Accounts\n\n"

            for l, a in cfg["accounts"].items():
                txt += a["name"] + "\n"

            await event.respond(txt)


        elif data == "add":

            state[uid] = {"step": "phone"}

            await event.respond(
                "Send phone with country code\nExample: +919876543210"
            )


        elif data == "del":

            buttons = []

            for label, acc in cfg["accounts"].items():

                buttons.append(
                    [Button.inline(acc["name"], f"del_{label}".encode())]
                )

            await event.respond("Select account", buttons=buttons)


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

            await event.respond("Interval Updated")


        elif step == "phone":

            phone = event.text.strip()

            if not phone.startswith("+"):

                await event.respond(
                    "Invalid format\nExample: +919876543210"
                )

                return

            label = f"acc{len(cfg['accounts']) + 1}"

            client = TelegramClient(
                f"session_{label}",
                API_ID,
                API_HASH
            )

            await client.connect()

            try:

                result = await client.send_code_request(phone)

            except FloodWaitError as e:

                await event.respond(
                    f"Too many OTP requests\nWait {e.seconds//60} minutes"
                )

                return

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

                log_channel = await create_logs_channel(
                    client,
                    s["label"]
                )

                await client.disconnect()

                cfg["accounts"][s["label"]] = {
                    "session": f"session_{s['label']}",
                    "name": me.first_name,
                    "log_channel": log_channel
                }

                save_cfg(cfg)

                del state[uid]

                await event.respond("Account Added")


            except SessionPasswordNeededError:

                state[uid]["step"] = "2fa"

                await event.respond("Send 2FA password")


        elif step == "2fa":

            s = state[uid]

            client = s["client"]

            await client.sign_in(password=event.text)

            me = await client.get_me()

            log_channel = await create_logs_channel(
                client,
                s["label"]
            )

            await client.disconnect()

            cfg["accounts"][s["label"]] = {
                "session": f"session_{s['label']}",
                "name": me.first_name,
                "log_channel": log_channel
            }

            save_cfg(cfg)

            del state[uid]

            await event.respond("Account Added")


    await bot.run_until_disconnected()


asyncio.run(run_bot())
