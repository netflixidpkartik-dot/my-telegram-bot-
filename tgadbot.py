import asyncio
import json
import os
import random
import re
from dotenv import load_dotenv

from telethon import TelegramClient, events, Button
from telethon.errors import (
    FloodWaitError,
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    PasswordHashInvalidError,
)
from telethon.tl.functions.channels import CreateChannelRequest

# =========================
# LOAD ENV
# =========================
load_dotenv()
BOT_TOKEN = "8612619704:AAHJlA-FTkHwJQ8NY1eCJbEahN0iqAXinfA" 
API_ID = 39079240
API_HASH = "4965548c91f559cd2ce88d00fcc54db1"

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN missing")
if not API_ID_RAW:
    raise ValueError("API_ID missing")
if not API_HASH:
    raise ValueError("API_HASH missing")
if not OWNER_ID_RAW:
    raise ValueError("OWNER_ID missing")

API_ID = int(API_ID_RAW)
OWNER_ID = int(OWNER_ID_RAW)

# =========================
# FILES / GLOBALS
# =========================
CONFIG = "accounts.json"
DEFAULT_INTERVAL = 90
CYCLE_DELAY = 60

state = {}          # user state
account_tasks = {}  # running tasks
cfg_lock = asyncio.Lock()


# =========================
# CONFIG HELPERS
# =========================
def load_cfg():
    if os.path.exists(CONFIG):
        try:
            with open(CONFIG, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {"accounts": {}, "interval": DEFAULT_INTERVAL}
    return {"accounts": {}, "interval": DEFAULT_INTERVAL}


async def save_cfg(data):
    async with cfg_lock:
        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)


# =========================
# UI
# =========================
def dashboard_buttons():
    return [
        [Button.inline("➕ Add Account", b"add")],
        [Button.inline("📂 Accounts", b"accs"), Button.inline("❌ Remove", b"del")],
        [Button.inline("▶ Start Ads", b"start"), Button.inline("⏹ Stop Ads", b"stop")],
        [Button.inline("⏱ Set Interval", b"interval")],
        [Button.inline("♻ Refresh", b"refresh")]
    ]


async def send_dashboard(event, text="Ads Dashboard Ready"):
    await event.respond(text, buttons=dashboard_buttons())


def is_owner(uid: int):
    return uid == OWNER_ID


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


def sanitize_phone(phone: str):
    phone = phone.strip().replace(" ", "")
    return phone


def sanitize_otp(otp: str):
    return "".join(ch for ch in otp if ch.isdigit())


def make_label(cfg):
    return f"acc{len(cfg['accounts']) + 1}"


# =========================
# BROADCAST LOOP
# =========================
async def broadcast_account_loop(label, acc):
    client = TelegramClient(acc["session"], API_ID, API_HASH)

    try:
        await client.start()
        print(f"[+] Started broadcast for {label}")

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
                break
            except Exception as ex:
                print(f"[Loop Error {label}] {ex}")
                await asyncio.sleep(10)

    finally:
        await client.disconnect()
        print(f"[-] Stopped broadcast for {label}")


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
# LOGIN FLOW HELPERS
# =========================
async def begin_login(uid, phone):
    """
    SINGLE source of truth for OTP request.
    This is the main fix.
    """
    cfg = load_cfg()
    label = make_label(cfg)

    # block duplicate pending login
    if uid in state and state[uid].get("step") in ["otp", "2fa", "phone"]:
        return False, "A login flow is already active. Finish it first."

    client = TelegramClient(f"session_{label}", API_ID, API_HASH)

    try:
        await client.connect()

        # IMPORTANT:
        # send code ONLY ONCE
        result = await client.send_code_request(phone)

        await client.disconnect()

        state[uid] = {
            "step": "otp",
            "phone": phone,
            "hash": result.phone_code_hash,
            "label": label,
            "otp_sent": True,
        }

        return True, f"OTP sent to {phone}\n\nNow send OTP digits only."

    except FloodWaitError as e:
        try:
            await client.disconnect()
        except:
            pass
        return False, f"Too many OTP requests.\nWait {e.seconds} seconds."

    except Exception as ex:
        try:
            await client.disconnect()
        except:
            pass
        return False, f"Failed to send OTP:\n{str(ex)}"


async def complete_login_with_otp(uid, otp):
    if uid not in state:
        return False, "No active OTP session found."

    s = state[uid]

    if s.get("step") != "otp":
        return False, "You're not in OTP step."

    otp = sanitize_otp(otp)

    if len(otp) < 5:
        return False, "OTP incomplete. Send full OTP digits only."

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

        cfg = load_cfg()
        cfg["accounts"][s["label"]] = {
            "session": f"session_{s['label']}",
            "name": me.first_name or "NoName",
            "log_channel": log_channel,
            "phone": s["phone"]
        }
        await save_cfg(cfg)

        await client.disconnect()
        del state[uid]

        return True, f"Account added successfully: {me.first_name or 'NoName'}"

    except SessionPasswordNeededError:
        try:
            await client.disconnect()
        except:
            pass

        state[uid]["step"] = "2fa"
        return False, "2FA enabled. Send your password."

    except PhoneCodeInvalidError:
        try:
            await client.disconnect()
        except:
            pass
        return False, "Invalid OTP. Use latest OTP only."

    except PhoneCodeExpiredError:
        try:
            await client.disconnect()
        except:
            pass

        # delete broken flow so user can restart cleanly
        del state[uid]
        return False, "OTP expired. Start again from Add Account."

    except Exception as ex:
        try:
            await client.disconnect()
        except:
            pass
        return False, f"Login failed:\n{str(ex)}"


async def complete_login_with_2fa(uid, password):
    if uid not in state:
        return False, "No active 2FA session found."

    s = state[uid]

    if s.get("step") != "2fa":
        return False, "You're not in 2FA step."

    client = TelegramClient(f"session_{s['label']}", API_ID, API_HASH)

    try:
        await client.connect()
        await client.sign_in(password=password.strip())

        me = await client.get_me()
        log_channel = await create_logs_channel(client, s["label"])

        cfg = load_cfg()
        cfg["accounts"][s["label"]] = {
            "session": f"session_{s['label']}",
            "name": me.first_name or "NoName",
            "log_channel": log_channel,
            "phone": s["phone"]
        }
        await save_cfg(cfg)

        await client.disconnect()
        del state[uid]

        return True, f"Account added successfully: {me.first_name or 'NoName'}"

    except PasswordHashInvalidError:
        try:
            await client.disconnect()
        except:
            pass
        return False, "Wrong 2FA password. Try again."

    except Exception as ex:
        try:
            await client.disconnect()
        except:
            pass
        return False, f"2FA login failed:\n{str(ex)}"


# =========================
# MAIN BOT
# =========================
async def run_bot():
    bot = TelegramClient("bot_session", API_ID, API_HASH)
    await bot.start(bot_token=BOT_TOKEN)

    print("[+] Bot started")

    @bot.on(events.NewMessage(pattern="/start"))
    async def start_cmd(event):
        if not is_owner(event.sender_id):
            return
        await send_dashboard(event)

    @bot.on(events.CallbackQuery)
    async def callback(event):
        uid = event.sender_id

        if not is_owner(uid):
            await event.answer("Unauthorized", alert=True)
            return

        data = event.data.decode()

        # IMPORTANT:
        # acknowledge callback immediately
        await event.answer()

        cfg = load_cfg()

        if data == "refresh":
            await send_dashboard(event, "Dashboard refreshed.")

        elif data == "start":
            await start_accounts()
            await send_dashboard(event, "Ads started.")

        elif data == "stop":
            await stop_accounts()
            await send_dashboard(event, "Ads stopped.")

        elif data == "interval":
            state[uid] = {"step": "interval"}
            await event.respond("Send interval in seconds.\nExample: 90")

        elif data == "accs":
            if not cfg["accounts"]:
                await event.respond("No accounts added yet.")
                return

            txt = "Accounts:\n\n"
            for label, acc in cfg["accounts"].items():
                txt += f"{label} → {acc['name']} ({acc.get('phone', 'NoPhone')})\n"

            await event.respond(txt)

        elif data == "add":
            # clear any broken old state first
            if uid in state:
                del state[uid]

            state[uid] = {"step": "phone"}
            await event.respond("Send phone number with country code.\nExample: +919876543210")

        elif data == "del":
            if not cfg["accounts"]:
                await event.respond("No accounts to remove.")
                return

            buttons = []
            for label, acc in cfg["accounts"].items():
                buttons.append([Button.inline(f"{acc['name']} ({label})", f"del_{label}".encode())])

            await event.respond("Select account to remove:", buttons=buttons)

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

        if not is_owner(uid):
            return

        # ignore commands
        if event.raw_text.startswith("/"):
            return

        if uid not in state:
            return

        step = state[uid].get("step")
        text = event.raw_text.strip()

        # INTERVAL STEP
        if step == "interval":
            try:
                val = int(text)
                if val < 10:
                    await event.respond("Too low. Keep interval at least 10 seconds.")
                    return

                cfg = load_cfg()
                cfg["interval"] = val
                await save_cfg(cfg)

                del state[uid]
                await event.respond(f"Interval updated to {val} seconds.")
                await send_dashboard(event)

            except:
                await event.respond("Send a valid number.\nExample: 90")

        # PHONE STEP
        elif step == "phone":
            phone = sanitize_phone(text)

            if not re.fullmatch(r"\+\d{8,15}", phone):
                await event.respond("Invalid phone format.\nExample: +919876543210")
                return

            ok, msg = await begin_login(uid, phone)
            await event.respond(msg)

            # if failed, reset phone state
            if not ok:
                if uid in state and state[uid].get("step") == "phone":
                    del state[uid]

        # OTP STEP
        elif step == "otp":
            ok, msg = await complete_login_with_otp(uid, text)
            await event.respond(msg)

            if ok:
                await send_dashboard(event)

        # 2FA STEP
        elif step == "2fa":
            ok, msg = await complete_login_with_2fa(uid, text)
            await event.respond(msg)

            if ok:
                await send_dashboard(event)

    await bot.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(run_bot())
