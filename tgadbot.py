"""
Telegram Group Broadcaster — Railway Safe Edition
- String sessions saved in Telegram Saved Messages (survives Railway restart!)
- Inline button dashboard
- Add accounts with phone + OTP only
- Parallel broadcasting
- 6hr on / 1hr rest cycle
- FIX: OTP resend on expiry
- FIX: Per-account group selection

Requirements:
    pip install telethon
"""

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

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────

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
        except Exception:
            pass
    _config = default_config()
    return _config

def save_config(cfg):
    global _config
    _config = cfg
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass

async def backup_config_to_telegram(bot, cfg):
    try:
        owner_id = cfg.get("owner_id", 0)
        if not owner_id:
            return
        backup   = json.dumps(cfg)
        msg_text = f"{CONFIG_BACKUP_TAG}\n{backup}"
        async for msg in bot.iter_messages("me", search=CONFIG_BACKUP_TAG):
            await msg.delete()
            break
        await bot.send_message("me", msg_text)
    except Exception:
        pass

async def restore_config_from_telegram(bot):
    try:
        async for msg in bot.iter_messages("me", search=CONFIG_BACKUP_TAG):
            text = msg.text or ""
            if CONFIG_BACKUP_TAG in text:
                json_part = text.replace(CONFIG_BACKUP_TAG, "").strip()
                cfg = json.loads(json_part)
                save_config(cfg)
                print("✅ Config restored from Telegram backup!")
                return cfg
    except Exception as e:
        print(f"⚠️ Could not restore backup: {e}")
    return None

def log(label, msg):
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    path = os.path.join(LOGS_DIR, f"{label}.log")
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass

# ─────────────────────────────────────────────
#  STATE
# ─────────────────────────────────────────────

state          = {}
broadcast_task = None

# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────

def make_client(session_string=None):
    session = StringSession(session_string) if session_string else StringSession()
    return TelegramClient(session, SHARED_API_ID, SHARED_API_HASH)

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
        [Button.inline("➕ Add Accounts",    b"add_acc"),     Button.inline("👥 My Accounts",   b"my_acc")],
        [Button.inline("📋 Select Groups",   b"select_grp"),  Button.inline("⏱ Set Interval",   b"set_interval")],
        [Button.inline("▶️ Start Ads",        b"start_ads"),   Button.inline("⏹ Stop Ads",      b"stop_ads")],
        [Button.inline("🗑 Delete Accounts",  b"del_acc")],
    ]

async def send_dashboard(bot, chat_id, msg_to_edit=None):
    cfg       = load_config()
    acc_count = len(cfg["accounts"])
    status    = "🚀 Running" if cfg.get("broadcasting") else "⏸ Stopped"

    # Count total selected groups across all accounts
    total_grps = sum(
        len(acc.get("selected_groups", []))
        for acc in cfg["accounts"].values()
    )
    grp_note = f"• Selected Groups: **{total_grps}** (across all accounts)\n" if total_grps else ""

    text = (
        f"🎛 **Ads DASHBOARD**\n\n"
        f"• Hosted Accounts: **{acc_count}**\n"
        f"{grp_note}"
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
#  BROADCAST
# ─────────────────────────────────────────────

async def broadcast_account(label, acc, interval, bot, owner_id):
    try:
        client = make_client(acc["session_string"])
        await client.connect()
        msg = await get_saved_message(client)
        if not msg:
            log(label, "No message in Saved Messages.")
            await client.disconnect()
            return

        # ── Use selected groups if set, otherwise fall back to ALL groups ──
        selected_ids = acc.get("selected_groups", [])
        if selected_ids:
            all_groups = await get_groups(client)
            groups = [d for d in all_groups if d.entity.id in selected_ids]
            if not groups:
                log(label, "⚠️ No matching selected groups found — skipping.")
                await client.disconnect()
                return
        else:
            groups = await get_groups(client)

        success = 0
        failed  = 0
        for dialog in groups:
            try:
                if msg.media:
                    await client.send_file(dialog.entity, msg.media, caption=msg.text or "")
                else:
                    await client.send_message(dialog.entity, msg.text)
                success += 1
            except Exception as e:
                failed += 1
                log(label, f"Failed → {dialog.name}: {e}")
            await asyncio.sleep(interval)

        log(label, f"Round done — ✅ {success} sent  ❌ {failed} failed")
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
                    await asyncio.gather(*[
                        broadcast_account(label, acc, interval, bot, owner_id)
                        for label, acc in accounts.items()
                    ])
                await asyncio.sleep(5)
            cfg = load_config()
            cfg["broadcasting"] = False
            save_config(cfg)
            await bot.send_message(owner_id, f"😴 Rest period ({REST_DURATION}hr). Resumes automatically.")
            await asyncio.sleep(rest_seconds)
            await bot.send_message(owner_id, "🟢 Rest over! Resuming...")
    except asyncio.CancelledError:
        cfg = load_config()
        cfg["broadcasting"] = False
        save_config(cfg)
        await bot.send_message(owner_id, "⏹ Broadcasting stopped.")

# ─────────────────────────────────────────────
#  HELPER: Send OTP request (reusable for resend)
# ─────────────────────────────────────────────

async def request_otp(client, phone):
    """Connect client and send OTP. Returns phone_code_hash."""
    await client.connect()
    try:
        result = await client.send_code_request(phone)
    except AuthRestartError:
        await client.disconnect()
        await client.connect()
        result = await client.send_code_request(phone)
    return result.phone_code_hash

# ─────────────────────────────────────────────
#  BOT
# ─────────────────────────────────────────────

async def run_bot():
    global broadcast_task

    bot = TelegramClient("dash_bot_session", SHARED_API_ID, SHARED_API_HASH)
    await bot.start(bot_token=BOT_TOKEN)
    me  = await bot.get_me()
    print(f"✅ Bot running: @{me.username}")

    cfg = load_config()
    if not cfg["accounts"]:
        restored = await restore_config_from_telegram(bot)
        if restored:
            print(f"✅ Restored {len(restored['accounts'])} accounts from backup!")

    @bot.on(events.NewMessage(pattern="/start"))
    async def cmd_start(event):
        cfg = load_config()
        uid = event.sender_id
        if cfg["owner_id"] == 0:
            cfg["owner_id"] = uid
            save_config(cfg)
            await backup_config_to_telegram(bot, cfg)
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

        if data == "dashboard":
            await send_dashboard(bot, uid, msg_to_edit=msg)

        # ── My Accounts ──────────────────────────────────────────────────────
        elif data == "my_acc":
            cfg = load_config()
            if not cfg["accounts"]:
                await bot.send_message(uid, "❌ No accounts added yet.")
                return
            lines = ["👥 **Hosted Accounts:**\n"]
            for i, (label, acc) in enumerate(cfg["accounts"].items(), 1):
                grp_count = len(acc.get("selected_groups", []))
                grp_note  = f" | {grp_count} groups selected" if grp_count else " | all groups"
                lines.append(f"{i}. `{label}` — {acc['name']}{grp_note}")
            await bot.send_message(uid, "\n".join(lines),
                buttons=[[Button.inline("⬅️ Back to Dashboard", b"dashboard")]])

        # ── Add Account ──────────────────────────────────────────────────────
        elif data == "add_acc":
            state[uid] = {"step": "wait_phone", "data": {}}
            await bot.send_message(uid,
                "➕ **Add New Account**\n\n"
                "Send your **phone number** with country code:\n_(e.g. `+12025551234`)_")

        # ── Set Interval ─────────────────────────────────────────────────────
        elif data == "set_interval":
            cfg = load_config()
            state[uid] = {"step": "wait_interval", "data": {}}
            await bot.send_message(uid,
                f"⏱ **Set Time Interval**\n\nCurrent: **{cfg['interval']}s**\n\n"
                "Send new interval in seconds _(minimum 10)_:")

        # ── Select Groups (pick which account first) ──────────────────────────
        elif data == "select_grp":
            cfg = load_config()
            if not cfg["accounts"]:
                await bot.send_message(uid, "❌ No accounts added yet.")
                return
            buttons = []
            for label, acc in cfg["accounts"].items():
                buttons.append([Button.inline(
                    f"👤 {acc['name']}", f"grp_pick_{label}".encode()
                )])
            buttons.append([Button.inline("⬅️ Back", b"dashboard")])
            await bot.send_message(uid,
                "📋 **Select Groups**\n\nChoose an account to configure its target groups:",
                buttons=buttons)

        # ── Load groups for a specific account ───────────────────────────────
        elif data.startswith("grp_pick_"):
            label = data.replace("grp_pick_", "")
            cfg   = load_config()
            acc   = cfg["accounts"].get(label)
            if not acc:
                await bot.send_message(uid, "❌ Account not found.")
                return

            await bot.send_message(uid, f"⏳ Loading groups for **{acc['name']}**...")
            try:
                client = make_client(acc["session_string"])
                await client.connect()
                groups = await get_groups(client)
                await client.disconnect()
            except Exception as e:
                await bot.send_message(uid, f"❌ Could not load groups: {e}")
                return

            if not groups:
                await bot.send_message(uid, "❌ No groups found for this account.")
                return

            # Store groups in state for pagination/selection
            selected_ids = set(acc.get("selected_groups", []))
            state[uid] = {
                "step": "selecting_groups",
                "data": {
                    "label":    label,
                    "groups":   [(d.entity.id, d.name) for d in groups],
                    "selected": selected_ids,
                    "page":     0,
                }
            }
            await send_group_picker(bot, uid)

        # ── Group picker toggle / pagination ──────────────────────────────────
        elif data.startswith("gtoggle_"):
            if uid not in state or state[uid]["step"] != "selecting_groups":
                return
            gid = int(data.replace("gtoggle_", ""))
            sel = state[uid]["data"]["selected"]
            if gid in sel:
                sel.discard(gid)
            else:
                sel.add(gid)
            await send_group_picker(bot, uid, msg_to_edit=msg)

        elif data == "grp_prev":
            if uid in state and state[uid]["step"] == "selecting_groups":
                state[uid]["data"]["page"] = max(0, state[uid]["data"]["page"] - 1)
                await send_group_picker(bot, uid, msg_to_edit=msg)

        elif data == "grp_next":
            if uid in state and state[uid]["step"] == "selecting_groups":
                s      = state[uid]["data"]
                pages  = (len(s["groups"]) + 9) // 10
                s["page"] = min(pages - 1, s["page"] + 1)
                await send_group_picker(bot, uid, msg_to_edit=msg)

        elif data == "grp_save":
            if uid not in state or state[uid]["step"] != "selecting_groups":
                return
            s     = state[uid]["data"]
            label = s["label"]
            cfg   = load_config()
            cfg["accounts"][label]["selected_groups"] = list(s["selected"])
            save_config(cfg)
            await backup_config_to_telegram(bot, cfg)
            del state[uid]
            count = len(s["selected"])
            await bot.send_message(uid,
                f"✅ Saved! **{count}** group(s) selected for `{label}`.\n"
                f"_(0 means broadcast to ALL groups)_")
            await send_dashboard(bot, uid)

        elif data == "grp_clear":
            if uid not in state or state[uid]["step"] != "selecting_groups":
                return
            state[uid]["data"]["selected"] = set()
            await send_group_picker(bot, uid, msg_to_edit=msg)

        # ── Start / Stop Ads ─────────────────────────────────────────────────
        elif data == "start_ads":
            cfg = load_config()
            if not cfg["accounts"]:
                await bot.send_message(uid, "❌ No accounts added!")
                return
            if broadcast_task and not broadcast_task.done():
                await bot.send_message(uid, "⚠️ Already running!")
                return
            broadcast_task = asyncio.create_task(broadcast_loop(bot, uid))
            cfg["broadcasting"] = True
            save_config(cfg)
            await send_dashboard(bot, uid, msg_to_edit=msg)

        elif data == "stop_ads":
            if broadcast_task and not broadcast_task.done():
                broadcast_task.cancel()
            cfg = load_config()
            cfg["broadcasting"] = False
            save_config(cfg)
            await send_dashboard(bot, uid, msg_to_edit=msg)

        # ── Delete Account ───────────────────────────────────────────────────
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
                del cfg["accounts"][label]
                save_config(cfg)
                await backup_config_to_telegram(bot, cfg)
                await bot.send_message(uid, f"✅ **{name}** deleted.")
            await send_dashboard(bot, uid)

        # ── Resend OTP ───────────────────────────────────────────────────────
        elif data == "resend_otp":
            if uid not in state or state[uid]["step"] != "wait_otp":
                await bot.send_message(uid, "❌ No pending OTP session.")
                return
            s = state[uid]
            phone  = s["data"]["phone"]
            old_cl = s["data"].get("client")
            if old_cl:
                try:
                    await old_cl.disconnect()
                except Exception:
                    pass
            await bot.send_message(uid, "🔄 Resending OTP...")
            try:
                client     = make_client()
                phone_hash = await request_otp(client, phone)
                s["data"]["client"]     = client
                s["data"]["phone_hash"] = phone_hash
                await bot.send_message(uid,
                    "✅ New OTP sent! Enter it below:\n\n"
                    "_(OTP expires in ~2 mins — enter quickly)_",
                    buttons=[[Button.inline("🔄 Resend OTP again", b"resend_otp")]])
            except Exception as e:
                await bot.send_message(uid, f"❌ Resend failed: {e}")
                del state[uid]

    # ── Group picker renderer ─────────────────────────────────────────────────
    async def send_group_picker(bot, uid, msg_to_edit=None):
        s        = state[uid]["data"]
        groups   = s["groups"]
        selected = s["selected"]
        page     = s["page"]
        per_page = 10
        start    = page * per_page
        chunk    = groups[start: start + per_page]
        pages    = (len(groups) + per_page - 1) // per_page

        text = (
            f"📋 **Select Target Groups** (page {page+1}/{pages})\n"
            f"✅ = will receive ads  |  Tap to toggle\n"
            f"Selected: **{len(selected)}/{len(groups)}**\n\n"
            f"_(Save with 0 selected = post to ALL groups)_"
        )
        buttons = []
        for gid, name in chunk:
            tick  = "✅" if gid in selected else "☐"
            short = name[:28] + "…" if len(name) > 30 else name
            buttons.append([Button.inline(f"{tick} {short}", f"gtoggle_{gid}".encode())])

        nav = []
        if page > 0:
            nav.append(Button.inline("◀️ Prev", b"grp_prev"))
        if page < pages - 1:
            nav.append(Button.inline("Next ▶️", b"grp_next"))
        if nav:
            buttons.append(nav)

        buttons.append([
            Button.inline("🗑 Clear All", b"grp_clear"),
            Button.inline("💾 Save",      b"grp_save"),
        ])
        buttons.append([Button.inline("⬅️ Back to Dashboard", b"dashboard")])

        try:
            if msg_to_edit:
                await msg_to_edit.edit(text, buttons=buttons)
                return
        except Exception:
            pass
        await bot.send_message(uid, text, buttons=buttons)

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

        # ── Set Interval ─────────────────────────────────────────────────────
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

        # ── Phone Number ──────────────────────────────────────────────────────
        elif step == "wait_phone":
            if not text.startswith("+"):
                await event.respond("❌ Include country code e.g. `+12025551234`")
                return
            await event.respond("📱 Sending OTP to your Telegram app...")
            try:
                cfg   = load_config()
                label = f"acc{len(cfg['accounts']) + 1}"
                client     = make_client()
                phone_hash = await request_otp(client, text)
                s["data"]["phone"]      = text
                s["data"]["phone_hash"] = phone_hash
                s["data"]["client"]     = client
                s["data"]["label"]      = label
                s["step"] = "wait_otp"
                await event.respond(
                    "✅ OTP sent! Enter the code from your Telegram app:\n\n"
                    "_(OTP expires in ~2 mins — enter quickly)_",
                    buttons=[[Button.inline("🔄 Resend OTP", b"resend_otp")]])
            except Exception as e:
                await event.respond(f"❌ Error: {e}\n\nPress ➕ Add Accounts to try again.")
                del state[uid]

        # ── OTP ───────────────────────────────────────────────────────────────
        elif step == "wait_otp":
            client = s["data"]["client"]
            try:
                clean_otp = "".join(filter(str.isdigit, text))
                await client.sign_in(
                    phone=s["data"]["phone"],
                    code=clean_otp,
                    phone_code_hash=s["data"]["phone_hash"]
                )
                me             = await client.get_me()
                session_string = client.session.save()
                await client.disconnect()
                label = s["data"]["label"]
                cfg   = load_config()
                cfg["accounts"][label] = {
                    "session_string": session_string,
                    "name":           f"{me.first_name} (@{me.username})",
                    "phone":          s["data"]["phone"],
                    "selected_groups": [],   # empty = all groups
                }
                save_config(cfg)
                await backup_config_to_telegram(bot, cfg)
                del state[uid]
                log(label, f"Account added: {me.first_name} (@{me.username})")
                await event.respond(
                    f"✅ **{me.first_name}** (@{me.username}) added!\n"
                    f"🔒 Session backed up to Telegram.\n\n"
                    f"💡 Use **📋 Select Groups** in dashboard to choose which groups to post to.")
                await send_dashboard(bot, uid)

            # ── OTP expired → prompt resend ────────────────────────────────
            except PhoneCodeExpiredError:
                await event.respond(
                    "⌛ OTP has **expired**! Tap below to get a fresh code:",
                    buttons=[[Button.inline("🔄 Resend OTP", b"resend_otp")]])

            # ── Wrong OTP ──────────────────────────────────────────────────
            except PhoneCodeInvalidError:
                await event.respond(
                    "❌ Wrong OTP code. Try again, or resend:",
                    buttons=[[Button.inline("🔄 Resend OTP", b"resend_otp")]])

            except SessionPasswordNeededError:
                s["step"] = "wait_2fa"
                await event.respond("🔒 2FA enabled. Enter your Telegram password:")

            except Exception as e:
                await event.respond(f"❌ Error: {e}\n\nPress ➕ Add Accounts to try again.")
                try:
                    await client.disconnect()
                except Exception:
                    pass
                del state[uid]

        # ── 2FA Password ──────────────────────────────────────────────────────
        elif step == "wait_2fa":
            client = s["data"]["client"]
            try:
                await client.sign_in(password=text)
                me             = await client.get_me()
                session_string = client.session.save()
                await client.disconnect()
                label = s["data"]["label"]
                cfg   = load_config()
                cfg["accounts"][label] = {
                    "session_string": session_string,
                    "name":           f"{me.first_name} (@{me.username})",
                    "phone":          s["data"]["phone"],
                    "selected_groups": [],
                }
                save_config(cfg)
                await backup_config_to_telegram(bot, cfg)
                del state[uid]
                log(label, f"Account added (2FA): {me.first_name} (@{me.username})")
                await event.respond(
                    f"✅ **{me.first_name}** (@{me.username}) added!\n"
                    f"🔒 Session backed up to Telegram.\n\n"
                    f"💡 Use **📋 Select Groups** to choose target groups.")
                await send_dashboard(bot, uid)
            except Exception as e:
                await event.respond(f"❌ Wrong password: {e}\n\nPress ➕ Add Accounts to try again.")
                try:
                    await client.disconnect()
                except Exception:
                    pass
                del state[uid]

    await bot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(run_bot())
