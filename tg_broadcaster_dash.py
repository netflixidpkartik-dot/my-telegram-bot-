"""
Telegram Group Broadcaster — Dashboard Edition
- Inline button dashboard
- Add accounts with phone + OTP only
- Messages sent from each account's Saved Messages
- Start/Stop all accounts at once
- Analytics, Delete Accounts

Usage:
    python tg_broadcaster_dash.py

Requirements:
    pip install telethon
"""

import asyncio
import json
import os
from datetime import datetime
from telethon import TelegramClient, events, Button
from telethon.tl.types import Channel, Chat
from telethon.errors import SessionPasswordNeededError, AuthRestartError

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────

BOT_TOKEN        = "8238694441:AAHT0lckdea6RRWATGtrMsucLZbq0E22G0A"
SHARED_API_ID    = 2040
SHARED_API_HASH  = "b18441a1ff607e10a989891a5462e627"
REST_HOURS       = 6
REST_DURATION    = 1
DEFAULT_INTERVAL = 30
CONFIG_FILE      = "dash_config.json"
LOGS_DIR         = "logs"
os.makedirs(LOGS_DIR, exist_ok=True)

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {
        "owner_id": 0,
        "accounts": {},
        "interval": DEFAULT_INTERVAL,
        "broadcasting": False,
        "analytics": {"total_sent": 0, "total_failed": 0, "rounds": 0}
    }

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

def log(label, msg):
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    path = os.path.join(LOGS_DIR, f"{label}.log")
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")

# ─────────────────────────────────────────────
#  STATE
# ─────────────────────────────────────────────

state          = {}
broadcast_task = None

# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────

async def get_groups(client):
    groups = []
    async for dialog in client.iter_dialogs():
        e = dialog.entity
        if isinstance(e, Chat):
            groups.append(dialog)
        elif isinstance(e, Channel) and e.megagroup:
            groups.append(dialog)
    return groups

async def get_saved_message(client):
    msgs = await client.get_messages("me", limit=1)
    return msgs[0] if msgs else None

def dashboard_buttons():
    return [
        [Button.inline("➕ Add Accounts",   b"add_acc"),    Button.inline("👥 My Accounts",  b"my_acc")],
        [Button.inline("⏱ Set Interval",    b"set_interval")],
        [Button.inline("▶️ Start Ads",       b"start_ads"),  Button.inline("⏹ Stop Ads",     b"stop_ads")],
        [Button.inline("🗑 Delete Accounts", b"del_acc")],
    ]

async def send_dashboard(bot, chat_id, msg_to_edit=None):
    cfg       = load_config()
    acc_count = len(cfg["accounts"])
    status    = "🚀 Running" if cfg.get("broadcasting") else "⏸ Stopped"
    text = (
        f"🎛 **Ads DASHBOARD**\n\n"
        f"• Hosted Accounts: **{acc_count}**\n"
        f"• Cycle Interval: **{cfg['interval']}s**\n"
        f"• Advertising Status: **{status}**\n\n"
        f"Choose an action below to continue"
    )
    buttons = dashboard_buttons()
    try:
        if msg_to_edit:
            await msg_to_edit.edit(text, buttons=buttons)
            return
    except Exception:
        pass
    await bot.send_message(chat_id, text, buttons=buttons)

# ─────────────────────────────────────────────
#  BROADCAST LOOP
# ─────────────────────────────────────────────

async def broadcast_account(label, acc, interval, bot, owner_id):
    """Broadcast from a single account to all its groups."""
    try:
        client = TelegramClient(acc["session"], SHARED_API_ID, SHARED_API_HASH)
        await client.connect()
        msg = await get_saved_message(client)
        if not msg:
            log(label, "No message in Saved Messages.")
            await client.disconnect()
            return

        groups  = await get_groups(client)
        success = 0
        failed  = 0

        for dialog in groups:
            try:
                if msg.text:
                    await client.send_message(dialog.entity, msg.text)
                elif msg.media:
                    await client.send_file(dialog.entity, msg.media, caption=msg.text or "")
                success += 1
            except Exception as e:
                failed += 1
                log(label, f"Failed → {dialog.name}: {e}")
            await asyncio.sleep(interval)

        cfg2 = load_config()
        cfg2["analytics"]["total_sent"]   += success
        cfg2["analytics"]["total_failed"] += failed
        cfg2["analytics"]["rounds"]       += 1
        save_config(cfg2)
        log(label, f"Round done — ✅ {success} sent ❌ {failed} failed")
        await client.disconnect()

    except Exception as e:
        log(label, f"Error: {e}")

async def broadcast_loop(bot, owner_id):
    active_seconds = REST_HOURS * 3600
    rest_seconds   = REST_DURATION * 3600
    await bot.send_message(owner_id, "▶️ Broadcasting started for all accounts.")

    try:
        while True:
            phase_start = asyncio.get_event_loop().time()
            cfg = load_config()
            cfg["broadcasting"] = True
            save_config(cfg)

            while asyncio.get_event_loop().time() - phase_start < active_seconds:
                cfg      = load_config()
                interval = cfg["interval"]
                accounts = cfg["accounts"]

                if accounts:
                    # Run all accounts in parallel simultaneously
                    await asyncio.gather(*[
                        broadcast_account(label, acc, interval, bot, owner_id)
                        for label, acc in accounts.items()
                    ])

                await asyncio.sleep(5)

            cfg = load_config()
            cfg["broadcasting"] = False
            save_config(cfg)
            await bot.send_message(owner_id, f"😴 Rest period started ({REST_DURATION}hr). Will resume automatically.")
            await asyncio.sleep(rest_seconds)
            await bot.send_message(owner_id, "🟢 Rest over! Resuming broadcasting...")

    except asyncio.CancelledError:
        cfg = load_config()
        cfg["broadcasting"] = False
        save_config(cfg)
        await bot.send_message(owner_id, "⏹ Broadcasting stopped.")

# ─────────────────────────────────────────────
#  BOT
# ─────────────────────────────────────────────

async def run_bot():
    global broadcast_task

    bot = TelegramClient("dash_bot_session", SHARED_API_ID, SHARED_API_HASH)
    await bot.start(bot_token=BOT_TOKEN)
    me  = await bot.get_me()
    print(f"✅ Bot running: @{me.username}")
    print(f"   Send /start to your bot on Telegram.")
    print(f"   Press Ctrl+C to stop.\n")

    @bot.on(events.NewMessage(pattern="/start"))
    async def cmd_start(event):
        cfg = load_config()
        uid = event.sender_id
        if cfg["owner_id"] == 0:
            cfg["owner_id"] = uid
            save_config(cfg)
        elif uid != cfg["owner_id"]:
            await event.respond("❌ Unauthorized.")
            return
        await send_dashboard(bot, uid)

    @bot.on(events.CallbackQuery())
    async def callback_handler(event):
        global broadcast_task
        uid  = event.sender_id
        data = event.data.decode()
        await event.answer()

        cfg = load_config()
        if uid != cfg["owner_id"]:
            return

        msg = await event.get_message()

        # ── Dashboard ──
        if data == "dashboard":
            await send_dashboard(bot, uid, msg_to_edit=msg)

        # ── My Accounts ──
        elif data == "my_acc":
            cfg = load_config()
            if not cfg["accounts"]:
                await bot.send_message(uid, "❌ No accounts added yet.\n\nPress ➕ Add Accounts to add one.")
                return
            lines = ["👥 **Hosted Accounts:**\n"]
            for i, (label, acc) in enumerate(cfg["accounts"].items(), 1):
                lines.append(f"{i}. `{label}` — {acc['name']}")
            await bot.send_message(
                uid,
                "\n".join(lines),
                buttons=[[Button.inline("⬅️ Back to Dashboard", b"dashboard")]]
            )

        # ── Add Account ──
        elif data == "add_acc":
            state[uid] = {"step": "wait_phone", "data": {}}
            await bot.send_message(
                uid,
                "➕ **Add New Account**\n\n"
                "Send your **phone number** with country code:\n"
                "_(e.g. `+12025551234`)_"
            )

        # ── Set Interval ──
        elif data == "set_interval":
            cfg = load_config()
            state[uid] = {"step": "wait_interval", "data": {}}
            await bot.send_message(
                uid,
                f"⏱ **Set Time Interval**\n\n"
                f"Current: **{cfg['interval']}s**\n\n"
                "Send new interval in seconds _(minimum 10)_:"
            )

        # ── Start Ads ──
        elif data == "start_ads":
            cfg = load_config()
            if not cfg["accounts"]:
                await bot.send_message(uid, "❌ No accounts added! Use ➕ Add Accounts first.")
                return
            if broadcast_task and not broadcast_task.done():
                await bot.send_message(uid, "⚠️ Already running!")
                return
            broadcast_task = asyncio.create_task(broadcast_loop(bot, uid))
            cfg["broadcasting"] = True
            save_config(cfg)
            await send_dashboard(bot, uid, msg_to_edit=msg)

        # ── Stop Ads ──
        elif data == "stop_ads":
            if broadcast_task and not broadcast_task.done():
                broadcast_task.cancel()
            cfg = load_config()
            cfg["broadcasting"] = False
            save_config(cfg)
            await send_dashboard(bot, uid, msg_to_edit=msg)

        # ── Delete Accounts ──
        elif data == "del_acc":
            cfg = load_config()
            if not cfg["accounts"]:
                await bot.send_message(uid, "❌ No accounts to delete.")
                return
            buttons = []
            for label, acc in cfg["accounts"].items():
                buttons.append([Button.inline(f"🗑 {acc['name']}", f"confirm_del_{label}".encode())])
            buttons.append([Button.inline("⬅️ Back to Dashboard", b"dashboard")])
            await bot.send_message(uid, "🗑 **Select account to delete:**", buttons=buttons)

        elif data.startswith("confirm_del_"):
            label = data.replace("confirm_del_", "")
            cfg   = load_config()
            if label in cfg["accounts"]:
                name = cfg["accounts"][label]["name"]
                sf   = f"session_{label}.session"
                if os.path.exists(sf):
                    os.remove(sf)
                del cfg["accounts"][label]
                save_config(cfg)
                await bot.send_message(uid, f"✅ **{name}** deleted.")
            await send_dashboard(bot, uid)

    # ── TEXT HANDLER ──
    @bot.on(events.NewMessage())
    async def text_handler(event):
        cfg = load_config()
        uid = event.sender_id

        if event.text and event.text.startswith("/"):
            return
        if uid != cfg["owner_id"]:
            return
        if uid not in state:
            return

        s    = state[uid]
        step = s["step"]
        text = (event.text or "").strip()

        if step == "wait_interval":
            clean = "".join(filter(str.isdigit, text))
            if not clean or int(clean) < 10:
                await event.respond("❌ Minimum 10 seconds. Try again:")
                return
            cfg["interval"] = int(clean)
            save_config(cfg)
            del state[uid]
            await event.respond(f"✅ Interval set to **{clean}s**!")
            await send_dashboard(bot, uid)

        elif step == "wait_phone":
            if not text.startswith("+"):
                await event.respond("❌ Include country code e.g. `+12025551234`")
                return
            await event.respond("📱 Sending OTP to your Telegram app...")
            try:
                cfg   = load_config()
                label = f"acc{len(cfg['accounts']) + 1}"
                client = TelegramClient(f"session_{label}", SHARED_API_ID, SHARED_API_HASH)
                await client.connect()
                try:
                    result = await client.send_code_request(text)
                except AuthRestartError:
                    await client.disconnect()
                    client = TelegramClient(f"session_{label}", SHARED_API_ID, SHARED_API_HASH)
                    await client.connect()
                    result = await client.send_code_request(text)
                s["data"]["phone"]      = text
                s["data"]["phone_hash"] = result.phone_code_hash
                s["data"]["client"]     = client
                s["data"]["label"]      = label
                s["step"] = "wait_otp"
                await event.respond("✅ OTP sent!\n\nEnter the **OTP code** from your Telegram app:")
            except Exception as e:
                await event.respond(f"❌ Error: {e}\n\nPress ➕ Add Accounts to try again.")
                del state[uid]

        elif step == "wait_otp":
            client = s["data"]["client"]
            try:
                clean_otp = "".join(filter(str.isdigit, text))
                await client.sign_in(
                    phone=s["data"]["phone"],
                    code=clean_otp,
                    phone_code_hash=s["data"]["phone_hash"]
                )
                me    = await client.get_me()
                await client.disconnect()
                label = s["data"]["label"]
                cfg   = load_config()
                cfg["accounts"][label] = {
                    "session": f"session_{label}",
                    "name":    f"{me.first_name} (@{me.username})",
                    "phone":   s["data"]["phone"],
                }
                save_config(cfg)
                del state[uid]
                log(label, f"Account added: {me.first_name} (@{me.username})")
                await event.respond(f"✅ **{me.first_name}** (@{me.username}) added successfully!")
                await send_dashboard(bot, uid)

            except SessionPasswordNeededError:
                s["step"] = "wait_2fa"
                await event.respond("🔒 2FA enabled. Enter your Telegram password:")

            except Exception as e:
                await event.respond(f"❌ Wrong OTP: {e}\n\nPress ➕ Add Accounts to try again.")
                await client.disconnect()
                del state[uid]

        elif step == "wait_2fa":
            client = s["data"]["client"]
            try:
                await client.sign_in(password=text)
                me    = await client.get_me()
                await client.disconnect()
                label = s["data"]["label"]
                cfg   = load_config()
                cfg["accounts"][label] = {
                    "session": f"session_{label}",
                    "name":    f"{me.first_name} (@{me.username})",
                    "phone":   s["data"]["phone"],
                }
                save_config(cfg)
                del state[uid]
                log(label, f"Account added (2FA): {me.first_name} (@{me.username})")
                await event.respond(f"✅ **{me.first_name}** (@{me.username}) added successfully!")
                await send_dashboard(bot, uid)
            except Exception as e:
                await event.respond(f"❌ Wrong password: {e}\n\nPress ➕ Add Accounts to try again.")
                await client.disconnect()
                del state[uid]

    await bot.run_until_disconnected()

# ─────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    asyncio.run(run_bot())
