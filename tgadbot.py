import asyncio
import json
import os
import random

from telethon import TelegramClient, events, Button
from telethon.errors import (
    FloodWaitError,
    SessionPasswordNeededError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
)
from telethon.tl.functions.channels import CreateChannelRequest
from telethon.tl.functions.messages import ExportChatInviteRequest

# ══════════════════════════════════════════════
#  CREDENTIALS
# ══════════════════════════════════════════════

BOT_TOKEN = "8639594670:AAESsjZn3OgDzVkde6juVD8OOwk2RhdJ3us"
API_ID    = 30298985
API_HASH  = "0e632624d1551bc099a2ed8563962717"

OWNER_ID  = 0   # 👈 APNI TELEGRAM ID YAHAN DAALO — e.g. 123456789

# ══════════════════════════════════════════════
#  CONSTANTS
# ══════════════════════════════════════════════

CONFIG           = "accounts.json"
DEFAULT_INTERVAL = 90
CYCLE_DELAY      = 60

# ══════════════════════════════════════════════
#  GLOBAL STATE
# ══════════════════════════════════════════════

user_state    = {}   # uid  → {"step": ..., ...}
account_tasks = {}   # label → asyncio.Task
client_pool   = {}   # session_path → TelegramClient

# ══════════════════════════════════════════════
#  CONFIG HELPERS
# ══════════════════════════════════════════════

def load_cfg() -> dict:
    if os.path.exists(CONFIG):
        with open(CONFIG) as f:
            return json.load(f)
    return {
        "owner":    0,
        "interval": DEFAULT_INTERVAL,
        "users":    {},
        "accounts": {}
    }


def save_cfg(data: dict):
    with open(CONFIG, "w") as f:
        json.dump(data, f, indent=2)


def is_auth(uid: int) -> bool:
    cfg = load_cfg()
    return uid == cfg["owner"] or str(uid) in cfg["users"]


def is_owner(uid: int) -> bool:
    return uid == load_cfg()["owner"]


def account_limit_ok(uid: int) -> bool:
    cfg = load_cfg()
    if uid == cfg["owner"]:
        return True
    u = cfg["users"].get(str(uid))
    if not u:
        return False
    used = sum(1 for a in cfg["accounts"].values() if a.get("owner") == uid)
    return used < u["limit"]

# ══════════════════════════════════════════════
#  CLIENT POOL
#  ONE client per session → no SQLite lock
# ══════════════════════════════════════════════

async def get_client(session: str) -> TelegramClient:
    if session in client_pool:
        c = client_pool[session]
        if not c.is_connected():
            await c.connect()
        return c
    c = TelegramClient(session, API_ID, API_HASH)
    await c.start()
    client_pool[session] = c
    return c


async def drop_client(session: str):
    c = client_pool.pop(session, None)
    if c:
        try:
            await c.disconnect()
        except Exception:
            pass

# ══════════════════════════════════════════════
#  BROADCAST ENGINE
# ══════════════════════════════════════════════

async def broadcast_loop(label: str):
    cfg = load_cfg()
    acc = cfg["accounts"].get(label)
    if not acc:
        return

    try:
        client = await get_client(acc["session"])
    except Exception as e:
        print(f"[{label}] start failed: {e}")
        return

    log_ch = acc.get("logs")

    async def log(txt):
        if not log_ch:
            return
        try:
            await client.send_message(log_ch, txt)
        except Exception:
            pass

    while True:
        try:
            cfg      = load_cfg()
            interval = cfg.get("interval", DEFAULT_INTERVAL)
            acc      = cfg["accounts"].get(label)
            if not acc:
                break

            # 1. Get saved message
            msgs = await client.get_messages("me", limit=1)
            if not msgs:
                await asyncio.sleep(CYCLE_DELAY)
                continue

            msg = msgs[0]

            # 2. Preload all groups
            dialogs = []
            async for d in client.iter_dialogs():
                if d.is_group:
                    dialogs.append(d)

            # 3. Send to each group
            for d in dialogs:
                try:
                    if msg.media:
                        await client.send_file(d.id, msg.media, caption=msg.text or "")
                    elif msg.text:
                        await client.send_message(d.id, msg.text)
                    await log(f"Sent → {d.name}")
                    await asyncio.sleep(random.randint(interval, interval + 30))

                except FloodWaitError as e:
                    await log(f"FloodWait {e.seconds}s — waiting")
                    await asyncio.sleep(e.seconds)

                except asyncio.CancelledError:
                    return

                except Exception as e:
                    await log(f"Error [{d.name}]: {e}")

            await asyncio.sleep(CYCLE_DELAY)

        except asyncio.CancelledError:
            return

        except Exception as e:
            print(f"[{label}] loop error: {e}")
            await asyncio.sleep(15)


def task_start(label: str):
    if label not in account_tasks:
        account_tasks[label] = asyncio.create_task(broadcast_loop(label))


def task_stop(label: str):
    t = account_tasks.pop(label, None)
    if t:
        t.cancel()

# ══════════════════════════════════════════════
#  PANEL HELPERS
# ══════════════════════════════════════════════

async def owner_panel(event, cfg: dict):
    total   = len(cfg["accounts"])
    running = sum(1 for l in cfg["accounts"] if l in account_tasks)
    subs    = len(cfg["users"])
    await event.respond(
        f"👑 **OWNER PANEL**\n\n"
        f"📱 Accounts    : `{total}`\n"
        f"🟢 Running     : `{running}`\n"
        f"👥 Subscribers : `{subs}`\n"
        f"⏱ Interval    : `{cfg['interval']} sec`",
        buttons=[
            [Button.inline("📂 Accounts",          b"accs"),
             Button.inline("➕ Add Account",        b"add")],
            [Button.inline("👥 Subscribers",        b"subs"),
             Button.inline("➕ Add Sub",            b"add_sub")],
            [Button.inline("❌ Remove Account",     b"del"),
             Button.inline("🗑 Remove Sub",         b"del_sub")],
            [Button.inline("🚀 Start Ads",          b"start"),
             Button.inline("⛔ Stop Ads",           b"stop")],
            [Button.inline("⏱ Interval",            b"interval")],
            [Button.inline("📡 Subscriber Groups",  b"subgroups")],
        ]
    )


async def sub_panel(event, uid: int, cfg: dict):
    u       = cfg["users"][str(uid)]
    limit   = u["limit"]
    my      = [l for l, a in cfg["accounts"].items() if a.get("owner") == uid]
    used    = len(my)
    running = sum(1 for l in my if l in account_tasks)
    stopped = used - running
    left    = limit - used
    bar     = "🟢" * running + "🔴" * stopped + "⚫" * left
    await event.respond(
        f"🚀 **Dustin Adbot**\n\n"
        f"📱 Accounts : `{used}/{limit}`\n"
        f"🟢 Running  : `{running}`\n"
        f"🔴 Stopped  : `{stopped}`\n"
        f"⏱ Interval : `{cfg['interval']} sec`\n\n"
        f"{bar}",
        buttons=[
            [Button.inline("➕ Add Account",     b"add"),
             Button.inline("📂 My Accounts",     b"accs")],
            [Button.inline("🗑️ Remove Account",  b"del")],
            [Button.inline("🚀 Start Ads",        b"start"),
             Button.inline("⛔ Stop Ads",         b"stop")],
            [Button.inline("⏱️ Set Interval",     b"interval")],
        ]
    )

# ══════════════════════════════════════════════
#  BOT
# ══════════════════════════════════════════════

async def run_bot():
    bot = TelegramClient("bot_session", API_ID, API_HASH)
    await bot.start(bot_token=BOT_TOKEN)

    # ─────────────────────────────────────────
    #  /start
    # ─────────────────────────────────────────
    @bot.on(events.NewMessage(pattern="/start"))
    async def cmd_start(event):
        cfg = load_cfg()
        uid = event.sender_id

        # OWNER_ID hardcoded hone par use karo, warna first-run wala logic
        if OWNER_ID != 0:
            if cfg["owner"] != OWNER_ID:
                cfg["owner"] = OWNER_ID
                save_cfg(cfg)
                cfg = load_cfg()
        else:
            if cfg["owner"] == 0:
                cfg["owner"] = uid
                save_cfg(cfg)
                cfg = load_cfg()

        if not is_auth(uid):
            await event.respond(
                "╔══════════════════════╗\n"
                "      🚫 ACCESS DENIED 🚫\n"
                "╚══════════════════════╝\n\n"
                "😔 **You are not authorised to use this bot.**\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "🚀 **What is DUSTIN ADBOT?**\n\n"
                "   🤖 Auto-broadcast messages to all your Telegram groups\n"
                "   📱 Connect multiple Telegram accounts\n"
                "   ⚡ Smart interval-based sending (no spam ban)\n"
                "   🔁 Runs 24/7 in the background automatically\n"
                "   📊 Live logs for every account activity\n"
                "   🛡️ Flood-wait protection built-in\n"
                "   🖼️ Supports text & media messages\n"
                "   ⚙️ Full control via Telegram bot panel\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "📋 **To get access:**\n\n"
                "   🔹 Contact the Owner\n"
                "   🔹 Purchase a Subscription\n"
                "   🔹 Come back & type /start\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "💎 **DUSTIN ADBOT** — Premium Only\n\n"
                "🙏 Thank You for visiting!\n"
                "⭐ See you after purchasing your subscription."
            )
            return

        if is_owner(uid):
            await owner_panel(event, cfg)
        else:
            await sub_panel(event, uid, cfg)

    # ─────────────────────────────────────────
    #  Callbacks
    # ─────────────────────────────────────────
    @bot.on(events.CallbackQuery)
    async def on_cb(event):
        uid  = event.sender_id
        data = event.data.decode()

        if not is_auth(uid):
            await event.answer("Access denied.", alert=True)
            return

        cfg   = load_cfg()
        owner = is_owner(uid)

        # ── Start Ads ────────────────────────
        if data == "start":
            if owner:
                for label in cfg["accounts"]:
                    task_start(label)
                await event.answer("All ads started.")
            else:
                for label, acc in cfg["accounts"].items():
                    if acc.get("owner") == uid:
                        task_start(label)
                await event.answer("Your ads started.")

        # ── Stop Ads ─────────────────────────
        elif data == "stop":
            if owner:
                for label in list(account_tasks.keys()):
                    task_stop(label)
                await event.answer("All ads stopped.")
            else:
                for label, acc in cfg["accounts"].items():
                    if acc.get("owner") == uid:
                        task_stop(label)
                await event.answer("Your ads stopped.")

        # ── Set Interval ─────────────────────
        elif data == "interval":
            user_state[uid] = {"step": "interval"}
            await event.respond("⏱ Send new interval in seconds:\nExample: `90`")

        # ── View Accounts ─────────────────────
        elif data == "accs":
            lines = []
            for label, acc in cfg["accounts"].items():
                if owner or acc.get("owner") == uid:
                    icon = "🟢" if label in account_tasks else "🔴"
                    lines.append(f"{icon} **{acc['name']}**")
            txt = "📂 **Accounts**\n\n" + ("\n".join(lines) if lines else "_None._")
            await event.respond(txt)

        # ── Add Account ──────────────────────
        elif data == "add":
            if not account_limit_ok(uid):
                await event.respond("⚠️ Account limit reached. Contact owner.")
                return
            user_state[uid] = {"step": "phone"}
            await event.respond("📱 Send phone number:\nExample: `+919876543210`")

        # ── Remove Account — list ─────────────
        elif data == "del":
            buttons = []
            for label, acc in cfg["accounts"].items():
                if owner or acc.get("owner") == uid:
                    buttons.append([
                        Button.inline(f"🗑 {acc['name']}", f"del_{label}".encode())
                    ])
            if not buttons:
                await event.respond("No accounts found.")
                return
            await event.respond("Select account to remove:", buttons=buttons)

        # ── Remove Account — confirm ──────────
        elif data.startswith("del_") and not data.startswith("del_sub"):
            label = data[4:]
            acc   = cfg["accounts"].get(label)
            if not acc:
                await event.respond("Account not found.")
                return
            if not owner and acc.get("owner") != uid:
                await event.answer("Not your account.", alert=True)
                return
            name = acc["name"]
            cfg["accounts"].pop(label)
            save_cfg(cfg)
            task_stop(label)
            await drop_client(acc.get("session", ""))
            await event.respond(f"✅ **{name}** removed.")

        # ── Subscribers List ──────────────────
        elif data == "subs":
            if not owner:
                await event.answer("Owner only.", alert=True)
                return
            users = cfg["users"]
            if not users:
                await event.respond("No subscribers yet.")
                return
            lines = []
            for u_id, u in users.items():
                used  = sum(1 for a in cfg["accounts"].values() if a.get("owner") == int(u_id))
                uname = f"@{u['username']}" if u.get("username") else f"`{u_id}`"
                lines.append(f"• {uname} — limit `{u['limit']}` | used `{used}`")
            await event.respond("👥 **Subscribers**\n\n" + "\n".join(lines))

        # ── Add Subscriber ────────────────────
        elif data == "add_sub":
            if not owner:
                await event.answer("Owner only.", alert=True)
                return
            user_state[uid] = {"step": "add_sub"}
            await event.respond(
                "➕ **Add Subscriber**\n\n"
                "Format: `@username LIMIT`\n"
                "Example: `@rahul123 5`"
            )

        # ── Remove Subscriber — list ──────────
        elif data == "del_sub":
            if not owner:
                await event.answer("Owner only.", alert=True)
                return
            users = cfg["users"]
            if not users:
                await event.respond("No subscribers found.")
                return
            buttons = []
            for u_id, u in users.items():
                uname  = f"@{u['username']}" if u.get("username") else f"ID:{u_id}"
                u_accs = sum(1 for a in cfg["accounts"].values() if a.get("owner") == int(u_id))
                buttons.append([
                    Button.inline(
                        f"🗑 {uname}  [{u_accs} acc]",
                        f"delsub_{u_id}".encode()
                    )
                ])
            await event.respond("Select subscriber to remove:", buttons=buttons)

        # ── Remove Subscriber — confirm ───────
        elif data.startswith("delsub_"):
            if not owner:
                await event.answer("Owner only.", alert=True)
                return
            t_id  = data[len("delsub_"):]
            u     = cfg["users"].pop(t_id, {})
            save_cfg(cfg)
            uname = f"@{u.get('username', t_id)}"
            await event.respond(f"✅ Subscriber {uname} removed.")

        # ── Subscriber Groups — Step 1 ────────
        elif data == "subgroups":
            if not owner:
                await event.answer("Owner only.", alert=True)
                return
            users = cfg["users"]
            if not users:
                await event.respond("No subscribers found.")
                return
            buttons = []
            for u_id, u in users.items():
                uname = f"@{u['username']}" if u.get("username") else f"ID:{u_id}"
                buttons.append([Button.inline(f"👤 {uname}", f"sg1_{u_id}".encode())])
            await event.respond("📡 **Subscriber Groups**\n\nSelect subscriber:", buttons=buttons)

        # ── Subscriber Groups — Step 2 ────────
        elif data.startswith("sg1_"):
            if not owner:
                await event.answer("Owner only.", alert=True)
                return
            t_id     = data[4:]
            sub_accs = {l: a for l, a in cfg["accounts"].items()
                        if str(a.get("owner")) == t_id}
            if not sub_accs:
                await event.respond(
                    "No accounts linked to this subscriber.",
                    buttons=[[Button.inline("« Back", b"subgroups")]]
                )
                return
            u     = cfg["users"].get(t_id, {})
            uname = f"@{u['username']}" if u.get("username") else f"ID:{t_id}"
            buttons = [
                [Button.inline(
                    ("🟢 " if l in account_tasks else "🔴 ") + a["name"],
                    f"sg2_{l}".encode()
                )]
                for l, a in sub_accs.items()
            ]
            buttons.append([Button.inline("« Back", b"subgroups")])
            await event.respond(f"📱 **{uname}** — select account:", buttons=buttons)

        # ── Subscriber Groups — Step 3 ────────
        elif data.startswith("sg2_"):
            if not owner:
                await event.answer("Owner only.", alert=True)
                return

            label = data[4:]
            acc   = cfg["accounts"].get(label)
            if not acc:
                await event.respond("Account not found.")
                return

            t_id    = str(acc.get("owner", ""))
            back_cb = f"sg1_{t_id}".encode()

            await event.answer("Fetching groups...")

            try:
                sub_client = await get_client(acc["session"])

                if not await sub_client.is_user_authorized():
                    await event.respond(
                        "⚠️ Session expired. Account needs to be re-added.",
                        buttons=[[Button.inline("« Back", back_cb)]]
                    )
                    return

                groups = []
                async for dialog in sub_client.iter_dialogs():
                    if not dialog.is_group:
                        continue
                    entity = dialog.entity
                    uname  = getattr(entity, "username", None)
                    if uname:
                        link = f"https://t.me/{uname}"
                    else:
                        try:
                            inv  = await sub_client(ExportChatInviteRequest(entity))
                            link = inv.link
                        except Exception:
                            link = "_unavailable_"
                    groups.append(f"• **{dialog.name}**\n  {link}")

            except Exception as e:
                await event.respond(
                    f"❌ Error: `{e}`",
                    buttons=[[Button.inline("« Back", back_cb)]]
                )
                return

            status = "🟢 Running" if label in account_tasks else "🔴 Stopped"
            header = (
                f"📡 **{acc['name']}** — {status}\n"
                f"Total Groups: `{len(groups)}`\n\n"
            )

            if not groups:
                await event.respond(
                    header + "_No groups found._",
                    buttons=[[Button.inline("« Back", back_cb)]]
                )
                return

            chunks = [groups[i:i + 20] for i in range(0, len(groups), 20)]
            for i, chunk in enumerate(chunks):
                head = header if i == 0 else f"Page {i+1}/{len(chunks)}\n\n"
                btns = [[Button.inline("« Back", back_cb)]] if i == len(chunks) - 1 else None
                await event.respond(head + "\n\n".join(chunk), buttons=btns)

    # ─────────────────────────────────────────
    #  Message handler (state machine)
    # ─────────────────────────────────────────
    @bot.on(events.NewMessage)
    async def on_msg(event):
        uid = event.sender_id
        if uid not in user_state:
            return

        step = user_state[uid]["step"]
        cfg  = load_cfg()
        text = event.raw_text.strip()

        # ── Interval ─────────────────────────
        if step == "interval":
            if not text.isdigit():
                await event.respond("⚠️ Enter a valid number.")
                return
            cfg["interval"] = int(text)
            save_cfg(cfg)
            user_state.pop(uid)
            await event.respond(f"✅ Interval set to `{text} sec`")

        # ── Add Subscriber ────────────────────
        elif step == "add_sub":
            parts = text.split()
            if len(parts) != 2 or not parts[1].isdigit():
                await event.respond("Format: `@username LIMIT`\nExample: `@rahul123 5`")
                return
            username = parts[0].lstrip("@")
            limit    = int(parts[1])
            try:
                user = await bot.get_entity(username)
            except Exception:
                await event.respond(
                    f"❌ `@{username}` not found.\n"
                    "Make sure the username is correct and they have started the bot."
                )
                return
            t_id = str(user.id)
            if t_id in cfg["users"]:
                await event.respond(f"⚠️ `@{username}` is already a subscriber.")
                user_state.pop(uid)
                return
            cfg["users"][t_id] = {"username": username, "limit": limit}
            save_cfg(cfg)
            user_state.pop(uid)
            await event.respond(
                f"✅ Subscriber added!\n\n"
                f"👤 @{username}\n"
                f"🆔 `{t_id}`\n"
                f"📊 Limit: `{limit}` accounts"
            )

        # ── Phone ─────────────────────────────
        elif step == "phone":
            if not text.startswith("+"):
                await event.respond("⚠️ Format: `+919876543210`")
                return
            label  = f"acc_{uid}_{len(cfg['accounts']) + 1}"
            client = TelegramClient(f"session_{label}", API_ID, API_HASH)
            try:
                await client.connect()
                result = await client.send_code_request(text)
            except Exception as e:
                await event.respond(f"❌ Error: `{e}`")
                return
            user_state[uid] = {
                "step":   "otp",
                "client": client,
                "phone":  text,
                "hash":   result.phone_code_hash,
                "label":  label,
            }
            await event.respond("✉️ Enter the OTP:")

        # ── OTP ───────────────────────────────
        elif step == "otp":
            client = user_state[uid]["client"]
            try:
                await client.sign_in(
                    user_state[uid]["phone"],
                    text,
                    phone_code_hash=user_state[uid]["hash"],
                )
            except PhoneCodeExpiredError:
                user_state.pop(uid)
                await event.respond("❌ OTP expired. Please add the account again.")
                return
            except PhoneCodeInvalidError:
                await event.respond("❌ Wrong OTP. Try again.")
                return
            except SessionPasswordNeededError:
                user_state[uid]["step"] = "2fa"
                await event.respond("🔐 Enter 2FA password:")
                return
            except Exception as e:
                await event.respond(f"❌ Error: `{e}`")
                return
            await finish_add(event, uid, client, cfg)

        # ── 2FA ───────────────────────────────
        elif step == "2fa":
            client = user_state[uid]["client"]
            try:
                await client.sign_in(password=text)
            except Exception as e:
                await event.respond(f"❌ 2FA failed: `{e}`")
                return
            await finish_add(event, uid, client, cfg)

    # ─────────────────────────────────────────
    #  Finish account add
    # ─────────────────────────────────────────
    async def finish_add(event, uid: int, client: TelegramClient, cfg: dict):
        label = user_state[uid]["label"]
        try:
            me   = await client.get_me()
            logs = await client(
                CreateChannelRequest(
                    title=f"{me.first_name} Logs",
                    about="Activity logs",
                    megagroup=False,
                )
            )
            log_ch = logs.chats[0].id
        except Exception:
            log_ch = None

        session_path = f"session_{label}"
        client_pool[session_path] = client   # register in pool

        cfg["accounts"][label] = {
            "session": session_path,
            "name":    me.first_name,
            "owner":   uid,
            "logs":    log_ch,
        }
        save_cfg(cfg)
        user_state.pop(uid)
        await event.respond(f"✅ Account **{me.first_name}** added!")

    await bot.run_until_disconnected()


asyncio.run(run_bot())
