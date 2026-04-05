import asyncio
import json
import os
from datetime import datetime
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.tl.types import Channel, Chat
from telethon.errors import (
    SessionPasswordNeededError, AuthRestartError,
    PhoneCodeExpiredError, PhoneCodeInvalidError
)

# ───────────────── CONFIG ─────────────────

BOT_TOKEN        = "8783380951:AAEMqv7e_V9-m4yKxUdMf3Fr40coBGUEP0Q"
SHARED_API_ID    = 37827563
SHARED_API_HASH  = "abca86f59db00e94244dd14df8259ff0"
REST_HOURS       = 6
REST_DURATION    = 1
DEFAULT_INTERVAL = 30
CONFIG_FILE      = "dash_config.json"
LOGS_DIR         = "logs"
CONFIG_BACKUP_TAG = "#BROADCASTER_CONFIG_BACKUP"

os.makedirs(LOGS_DIR, exist_ok=True)

_config = None

def default_config():
    return {
        "owner_id": 0,
        "accounts": {},
        "interval": DEFAULT_INTERVAL,
        "broadcasting": False,
    }

def load_config():
    global _config
    if _config is not None:
        return _config
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                _config = json.load(f)
            return _config
        except:
            pass
    _config = default_config()
    return _config

def save_config(cfg):
    global _config
    _config = cfg
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

# ───────────────── HELPERS ─────────────────

def make_client(session_string=None):
    session = StringSession(session_string) if session_string else StringSession()
    return TelegramClient(session, SHARED_API_ID, SHARED_API_HASH)

async def request_otp(client, phone):
    await client.connect()
    try:
        result = await client.send_code_request(phone)
    except AuthRestartError:
        await client.disconnect()
        await client.connect()
        result = await client.send_code_request(phone)
    return result.phone_code_hash

# ───────────────── BOT ─────────────────

state = {}

async def run_bot():
    bot = TelegramClient("bot_session", SHARED_API_ID, SHARED_API_HASH)
    await bot.start(bot_token=BOT_TOKEN)

    @bot.on(events.NewMessage(pattern="/start"))
    async def start(event):
        cfg = load_config()
        uid = event.sender_id

        if cfg["owner_id"] == 0:
            cfg["owner_id"] = uid
            save_config(cfg)
        elif uid != cfg["owner_id"]:
            await event.respond("❌ Unauthorized")
            return

        await event.respond("✅ Bot Ready\n\nUse buttons below.",
            buttons=[[Button.inline("➕ Add Account", b"add")]])

    # ───────── ADD ACCOUNT ─────────
    @bot.on(events.CallbackQuery(data=b"add"))
    async def add_acc(event):
        uid = event.sender_id
        state[uid] = {"step": "phone", "data": {}}
        await event.respond("📱 Send phone number with country code")

    @bot.on(events.NewMessage())
    async def handler(event):
        uid = event.sender_id
        if uid not in state:
            return

        s = state[uid]
        step = s["step"]
        text = (event.text or "").strip()

        # ───────── PHONE ─────────
        if step == "phone":
            if not text.startswith("+"):
                await event.respond("❌ Use country code")
                return

            client = make_client()
            phone_hash = await request_otp(client, text)

            s["data"] = {
                "phone": text,
                "client": client,
                "phone_hash": phone_hash,
            }
            s["step"] = "otp"

            await event.respond(
                "✅ OTP sent\nEnter code:",
                buttons=[[Button.inline("🔄 Resend OTP", b"resend")]]
            )

        # ───────── OTP FIXED ─────────
        elif step == "otp":
            client = s["data"]["client"]
            phone  = s["data"]["phone"]

            try:
                code = "".join(filter(str.isdigit, text))

                await client.sign_in(
                    phone=phone,
                    code=code,
                    phone_code_hash=s["data"]["phone_hash"]
                )

                me = await client.get_me()
                session_string = client.session.save()
                await client.disconnect()

                cfg = load_config()
                label = f"acc{len(cfg['accounts'])+1}"

                cfg["accounts"][label] = {
                    "session_string": session_string,
                    "name": me.first_name
                }

                save_config(cfg)
                del state[uid]

                await event.respond(f"✅ Added: {me.first_name}")

            # 🔥 AUTO RESEND FIX
            except PhoneCodeExpiredError:
                await event.respond("⌛ OTP expired, sending new...")

                try:
                    await client.disconnect()
                except:
                    pass

                new_client = make_client()
                phone_hash = await request_otp(new_client, phone)

                s["data"]["client"] = new_client
                s["data"]["phone_hash"] = phone_hash

                await event.respond(
                    "✅ New OTP sent\nEnter it:",
                    buttons=[[Button.inline("🔄 Resend OTP", b"resend")]]
                )

            except PhoneCodeInvalidError:
                await event.respond("❌ Wrong OTP")

            except SessionPasswordNeededError:
                s["step"] = "2fa"
                await event.respond("🔒 Enter 2FA password")

        # ───────── 2FA ─────────
        elif step == "2fa":
            client = s["data"]["client"]

            try:
                await client.sign_in(password=text)
                me = await client.get_me()
                session_string = client.session.save()
                await client.disconnect()

                cfg = load_config()
                label = f"acc{len(cfg['accounts'])+1}"

                cfg["accounts"][label] = {
                    "session_string": session_string,
                    "name": me.first_name
                }

                save_config(cfg)
                del state[uid]

                await event.respond(f"✅ Added: {me.first_name}")

            except Exception as e:
                await event.respond(f"❌ {e}")
                del state[uid]

    # ───────── RESEND OTP FIX ─────────
    @bot.on(events.CallbackQuery(data=b"resend"))
    async def resend(event):
        uid = event.sender_id

        if uid not in state or state[uid]["step"] != "otp":
            await event.respond("❌ No active session")
            return

        s = state[uid]
        phone = s["data"]["phone"]

        try:
            old = s["data"]["client"]
            await old.disconnect()
        except:
            pass

        new_client = make_client()
        phone_hash = await request_otp(new_client, phone)

        s["data"]["client"] = new_client
        s["data"]["phone_hash"] = phone_hash

        await event.respond("✅ New OTP sent")

    print("✅ Bot Running...")
    await bot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(run_bot())
