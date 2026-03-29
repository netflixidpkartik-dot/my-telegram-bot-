import asyncio
import json
import os
import random

from telethon import TelegramClient, events, Button
from telethon.errors import (
    FloodWaitError,
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    PasswordHashInvalidError
)
from telethon.tl.functions.channels import CreateChannelRequest


# =========================
# CONFIG
# =========================
BOT_TOKEN = os.getenv("8612619704:AAHJlA-FTkHwJQ8NY1eCJbEahN0iqAXinfA")
API_ID = int(os.getenv("39079240"))
API_HASH = os.getenv("4965548c91f559cd2ce88d00fcc54db1")

CONFIG = "accounts.json"

DEFAULT_INTERVAL = 90
CYCLE_DELAY = 60

state = {}
account_tasks = {}
cfg_lock = asyncio.Lock()


# =========================
# CONFIG HELPERS
# =========================
def load_cfg():
    if os.path.exists(CONFIG):
        with open(CONFIG, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"owner": 0, "accounts": {}, "interval": DEFAULT_INTERVAL}


async def save_cfg(data):
    async with cfg_lock:
        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)


# =========================
# UI HELPERS
# =========================
def dashboard_buttons():
    return [
        [Button.inline("Add Account", b"add")],
        [Button.inline("Accounts", b"accs")],
        [Button.inline("Remove Account", b"del")],
        [Button.inline("Start Ads", b"start"), Button.inline("Stop Ads", b"stop")],
        [Button.inline("Set Interval", b"interval")]
    ]


async def send_dashboard(event, text="Ads Dashboard"):
    await event.respond(text, buttons=dashboard_buttons())


# =========================
# ACCOUNT HELPERS
# =========================
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
        interval = cfg.get("interval", DEFAULT_INTERVAL)

        try:
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
                    if message.media:
                        await client.send_file(
                            dialog.id,
                            message.media,
                            caption=message.text or ""
                        )
                    else:
                        await client.send_message(dialog.id, message.text or "")

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

                except Exception as ex:
                    failed += 1
                    await client.send_message(
                        acc["log_channel"],
                        f"Failed → {dialog.name}\nReason: {str(ex)}"
                    )

            await client.send_message(
                acc["log_channel"],
                f"Cycle done\nSuccess: {success}\nFailed: {failed}"
            )

            await asyncio.sleep(CYCLE_DELAY)

        except asyncio.CancelledError:
            print(f"Stopped task for {label}")
            break
        except Exception as ex:
            print(f"Loop error [{label}]: {ex}")
            await asyncio.sleep(10)

    await client.disconnect()


async def start_accounts():
    cfg = load_cfg()

    for label, acc in cfg["accounts"].items():
        if label not in account_tasks:
            task = asyncio.create_task(broadcast_account_loop(label, acc))
            account_tasks[label] = task


async def stop_accounts():
    for label, task in list(account_tasks.items()):
        task.cancel()
    account_tasks.clear()


async def stop_single_account(label):
    if label in account_tasks:
        account_tasks[label].cancel()
        del account_tasks[label]


# =========================
# MAIN BOT
# =========================
async def run_bot():
    bot = TelegramClient("bot_session", API_ID, API_HASH)
    await bot.start(bot_token=BOT_TOKEN)

    @bot.on(events.NewMessage(pattern="/start"))
    async def start(event):
        cfg = load_cfg()

        if cfg["owner"] == 0:
            cfg["owner"] = event.sender_id
            await save_cfg(cfg)

        if event.sender_id != cfg["owner"]:
            return

        await send_dashboard(event)

    @bot.on(events.CallbackQuery)
    async def callback(event):
        cfg = load_cfg()
        uid = event.sender_id

        if uid != cfg["owner"]:
            await event.answer("Unauthorized", alert=True)
            return

        data = event.data.decode()
        await event.answer()

        if data == "start":
            await start_accounts()
            await send_dashboard(event, "Ads Started")

        elif data == "stop":
            await stop_accounts()
            await send_dashboard(event, "Ads Stopped")

        elif data == "interval":
            state[uid] = {"step": "interval"}
            await event.respond("Send interval in seconds (example: 90)")

        elif data == "accs":
            if not cfg["accounts"]:
                await event.respond("No accounts added yet.")
                return

            txt = "Accounts:\n\n"
            for label, acc in cfg["accounts"].items():
                txt += f"- {acc['name']} ({label})\n"

            await event.respond(txt)

        elif data == "add":
            state[uid] = {"step": "phone"}
            await event.respond("Send phone with country code\nExample: +919876543210")

        elif data == "del":
            if not cfg["accounts"]:
                await event.respond("No accounts to remove.")
                return

            buttons = []
            for label, acc in cfg["accounts"].items():
                buttons.append([Button.inline(acc["name"], f"del_{label}".encode())])

            await event.respond("Select account", buttons=buttons)

        elif data.startswith("del_"):
            label = data.replace("del_", "")

            if label in cfg["accounts"]:
                await stop_single_account(label)
                del cfg["accounts"][label]
                await save_cfg(cfg)
                await event.respond(f"{label} removed successfully.")

    @bot.on(events.NewMessage)
    async def handler(event):
        uid = event.sender_id
        cfg = load_cfg()

        if uid != cfg["owner"]:
            return

        if uid not in state:
            return

        # prevent commands from interfering
        if event.text and event.text.startswith("/"):
            return

        step = state[uid]["step"]

        if step == "interval":
            try:
                value = int(event.text.strip())
                if value < 10:
                    await event.respond("Interval too low. Keep it at least 10 seconds.")
                    return

                cfg["interval"] = value
                await save_cfg(cfg)
                del state[uid]
                await event.respond("Interval updated.")
                await send_dashboard(event)

            except ValueError:
                await event.respond("Send a valid number. Example: 90")

        elif step == "phone":
            phone = event.text.strip()

            if not phone.startswith("+") or not phone[1:].isdigit():
                await event.respond("Invalid format.\nExample: +919876543210")
                return

            label = f"acc{len(cfg['accounts']) + 1}"
            client = TelegramClient(f"session_{label}", API_ID, API_HASH)

            try:
                await client.connect()
                result = await client.send_code_request(phone)

                state[uid] = {
                    "step": "otp",
                    "phone": phone,
                    "hash": result.phone_code_hash,
                    "label": label
                }

                await client.disconnect()
                await event.respond("Send OTP exactly as received.")

            except FloodWaitError as e:
                await event.respond(f"Too many OTP requests.\nWait {e.seconds // 60} minutes.")
            except Exception as ex:
                await event.respond(f"Failed to send OTP:\n{str(ex)}")

        elif step == "otp":
            s = state[uid]
            otp = "".join(ch for ch in event.text if ch.isdigit())

            if len(otp) < 5:
                await event.respond("OTP incomplete. Send full OTP digits only.")
                return

            client = TelegramClient(f"session_{s['label']}", API_ID, API_HASH)

            try:
                await client.connect()

                await client.sign_in(
                    phone=s["phone"],
                    code=otp,
                    phone_code_hash=s["hash"]
                )

                me = await client.get_me()
                log_channel = await create_logs_channel(client, s["label"])

                cfg["accounts"][s["label"]] = {
                    "session": f"session_{s['label']}",
                    "name": me.first_name or "NoName",
                    "log_channel": log_channel
                }

                await save_cfg(cfg)
                del state[uid]

                await client.disconnect()
                await event.respond("Account added successfully.")
                await send_dashboard(event)

            except SessionPasswordNeededError:
                await client.disconnect()
                state[uid]["step"] = "2fa"
                await event.respond("2FA enabled. Send your password.")

            except PhoneCodeInvalidError:
                await client.disconnect()
                await event.respond("Invalid OTP. Send correct code.")

            except PhoneCodeExpiredError:
                await client.disconnect()
                del state[uid]
                await event.respond("OTP expired. Start again.")

            except Exception as ex:
                await client.disconnect()
                await event.respond(f"Login failed:\n{str(ex)}")

        elif step == "2fa":
            s = state[uid]
            client = TelegramClient(f"session_{s['label']}", API_ID, API_HASH)

            try:
                await client.connect()
                await client.sign_in(password=event.text.strip())

                me = await client.get_me()
                log_channel = await create_logs_channel(client, s["label"])

                cfg["accounts"][s["label"]] = {
                    "session": f"session_{s['label']}",
                    "name": me.first_name or "NoName",
                    "log_channel": log_channel
                }

                await save_cfg(cfg)
                del state[uid]

                await client.disconnect()
                await event.respond("Account added successfully.")
                await send_dashboard(event)

            except PasswordHashInvalidError:
                await client.disconnect()
                await event.respond("Wrong 2FA password. Try again.")

            except Exception as ex:
                await client.disconnect()
                await event.respond(f"2FA login failed:\n{str(ex)}")

    print("Bot running...")
    await bot.run_until_disconnected()


asyncio.run(run_bot())
