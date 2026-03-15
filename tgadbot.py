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

# ─────────────────────────────────────────
#  Config
# ─────────────────────────────────────────

BOT_TOKEN = "8639594670:AAESsjZn3OgDzVkde6juVD8OOwk2RhdJ3us"
API_ID    = 30298985
API_HASH  = "0e632624d1551bc099a2ed8563962717"

CONFIG           = "accounts.json"
DEFAULT_INTERVAL = 90
CYCLE_DELAY      = 60

# ─────────────────────────────────────────
#  In-memory state
# ─────────────────────────────────────────

state         = {}   # uid → step data
account_tasks = {}   # label → asyncio.Task
clients       = {}   # session_path → TelegramClient  (global pool)

# ─────────────────────────────────────────
#  Config helpers
# ─────────────────────────────────────────

def load_cfg() -> dict:
    if os.path.exists(CONFIG):
        with open(CONFIG) as f:
            return json.load(f)
    return {"owner": 0, "interval": DEFAULT_INTERVAL, "users": {}, "accounts": {}}


def save_cfg(data: dict):
    with open(CONFIG, "w") as f:
        json.dump(data, f, indent=2)


def is_authorised(uid: int) -> bool:
    cfg = load_cfg()
    return uid == cfg["owner"] or str(uid) in cfg.get("users", {})


def is_owner(uid: int) -> bool:
    return uid == load_cfg()["owner"]


def can_add_account(uid: int) -> bool:
    cfg = load_cfg()
    if uid == cfg["owner"]:
        return True
    u = cfg["users"].get(str(uid))
    if not u:
        return False
    used = sum(1 for a in cfg["accounts"].values() if a.get("owner") == uid)
    return used < u["limit"]


# ─────────────────────────────────────────
#  Global client manager  ← KEY FIX
#  One TelegramClient per session file.
#  Both broadcast and groups-fetch share
#  the same instance → no SQLite lock.
# ─────────────────────────────────────────

async def get_client(session: str) -> TelegramClient:
    """Return existing client or create + authenticate a new one."""
    if session in clients:
        c = clients[session]
        if c.is_connected():
            return c
        await c.connect()
        return c

    c = TelegramClient(session, API_ID, API_HASH)
    await c.start()
    clients[session] = c
    return c


async def release_client(session: str):
    """Disconnect and remove a client from the pool."""
    c = clients.pop(session, None)
    if c:
        try:
            await c.disconnect()
        except Exception:
            pass


# ─────────────────────────────────────────
#  Log channel
# ─────────────────────────────────────────

async def create_logs_channel(client: TelegramClient, name: str) -> int:
    result = await client(
        CreateChannelRequest(
            title=f"{name} Logs",
            about="Account activity logs",
            megagroup=False,
        )
    )
    return result.chats[0].id


async def send_log(client: TelegramClient, log_channel, text: str):
    if not log_channel:
        return
    try:
        await client.send_message(log_channel, text)
    except Exception:
        pass


# ─────────────────────────────────────────
#  Broadcast engine
# ─────────────────────────────────────────

async def broadcast_loop(label: str):
    """
    Runs forever for one account.
    Uses the global client pool — no duplicate sessions — no DB lock.
    Pre-loads dialogs before sending — stable loop.
    """
    cfg = load_cfg()
    acc = cfg["accounts"].get(label)
    if not acc:
        return

    session     = acc["session"]
    log_channel = acc.get("logs")

    try:
        client = await get_client(session)
    except Exception as e:
        print(f"[{label}] Could not start client: {e}")
        return

    while True:
        cfg      = load_cfg()
        interval = cfg.get("interval", DEFAULT_INTERVAL)
        acc      = cfg["accounts"].get(label)
        if not acc:
            break

        # --- fetch saved message ---
        try:
            msgs = await client.get_messages("me", limit=1)
        except Exception as e:
            await send_log(client, log_channel, f"warning get_messages error: {e}")
            await asyncio.sleep(10)
            continue

        if not msgs:
            await asyncio.sleep(CYCLE_DELAY)
            continue

        message = msgs[0]

        # --- preload dialogs ---
        try:
            dialogs = [d async for d in client.iter_dialogs() if d.is_group]
        except Exception as e:
            await send_log(client, log_channel, f"warning iter_dialogs error: {e}")
            await asyncio.sleep(CYCLE_DELAY)
            continue

        # --- send to each group ---
        for dialog in dialogs:
            try:
                if message.media:
                    await client.send_file(
                        dialog.id, message.media, caption=message.text or ""
                    )
                elif message.text:
                    await client.send_message(dialog.id, message.text)

                await send_log(client, log_channel, f"Sent to {dialog.name}")
                await asyncio.sleep(random.randint(interval, interval + 30))

            except FloodWaitError as e:
                await send_log(client, log_channel, f"FloodWait {e.seconds}s")
                await asyncio.sleep(e.seconds)

            except asyncio.CancelledError:
                return

            except Exception as e:
                await send_log(client, log_channel, f"Error {dialog.name}: {e}")

        await asyncio.sleep(CYCLE_DELAY)


async def start_all_accounts():
    cfg = load_cfg()
    for label in cfg["accounts"]:
        if label not in account_tasks:
            t = asyncio.create_task(broadcast_loop(label))
            account_tasks[label] = t


async def stop_all_accounts():
    for t in account_tasks.values():
        t.cancel()
    account_tasks.clear()


def start_one(label: str):
    if label not in account_tasks:
        t = asyncio.create_task(broadcast_loop(label))
        account_tasks[label] = t


def stop_one(label: str):
    t = account_tasks.pop(label, None)
    if t:
        t.cancel()


# ─────────────────────────────────────────
#  Panel builders
# ─────────────────────────────────────────

async def send_owner_panel(target, cfg: dict):
    total   = len(cfg["accounts"])
    running = len(account_tasks)
    subs    = len(cfg.get("users", {}))
    text = (
        "👑 **OWNER PANEL**\n\n"
        f"📱 Accounts   : `{total}`\n"
        f"🟢 Running    : `{running}`\n"
        f"👥 Subscribers: `{subs}`\n"
        f"⏱ Interval   : `{cfg['interval']} sec`"
    )
    buttons = [
        [Button.inline("📂 Accounts",          b"accs"),
         Button.inline("➕ Add Account",       b"add")],
        [Button.inline("👥 Subscribers",       b"subs"),
         Button.inline("➕ Add Sub",           b"add_sub")],
        [Button.inline("❌ Remove Account",    b"del"),
         Button.inline("🗑 Remove Sub",        b"del_sub")],
        [Button.inline("🚀 Start Ads",         b"start"),
         Button.inline("⛔ Stop Ads",          b"stop")],
        [Button.inline("⏱ Interval",           b"interval")],
        [Button.inline("📡 Subscriber Groups", b"subgroups")],
    ]
    await target.respond(text, buttons=buttons)


async def send_sub_panel(target, uid: int, cfg: dict):
    u_data     = cfg["users"][str(uid)]
    limit      = u_data["limit"]
    name       = u_data.get("username", "User")
    my_accs    = [l for l, a in cfg["accounts"].items() if a.get("owner") == uid]
    used       = len(my_accs)
    running    = sum(1 for l in my_accs if l in account_tasks)
    stopped    = used - running
    slots_left = limit - used
    bar        = "🟢" * running + "🔴" * stopped + "⚫" * slots_left

    text = (
        "🚀 **Dustin Adbot Dashboard**\n\n"
        f"📱 Accounts Used : `{used}/{limit}`\n"
        f"🟢 Running       : `{running}`\n"
        f"🔴 Stopped       : `{stopped}`\n"
        f"⏱ Interval      : `{cfg['interval']} sec`\n\n"
        f"{bar}"
    )
    buttons = [
        [Button.inline("➕ Add Account",     b"add"),
         Button.inline("📂 My Accounts",    b"accs")],
        [Button.inline("🗑️ Remove Account", b"del")],
        [Button.inline("🚀 Start Ads",       b"start"),
         Button.inline("⛔ Stop Ads",        b"stop")],
        [Button.inline("⏱️ Set Interval",    b"interval")],
    ]
    await target.respond(text, buttons=buttons)


# ─────────────────────────────────────────
#  Bot
# ─────────────────────────────────────────

async def run_bot():
    bot = TelegramClient("control_panel_bot", API_ID, API_HASH)
    await bot.start(bot_token=BOT_TOKEN)

    # ════════════════════════════════════════
    #  /start
    # ════════════════════════════════════════
    @bot.on(events.NewMessage(pattern="/start"))
    async def cmd_start(event):
        cfg = load_cfg()
        uid = event.sender_id

        if cfg["owner"] == 0:
            cfg["owner"] = uid
            save_cfg(cfg)

        cfg = load_cfg()

        if not is_authorised(uid):
            await event.respond(
                "🚫 **Access Denied**\n\n"
                "You are not authorised to use this bot.\n\n"
                "Contact the owner to purchase a subscription."
            )
            return

        if is_owner(uid):
            await send_owner_panel(event, cfg)
        else:
            await send_sub_panel(event, uid, cfg)

    # ════════════════════════════════════════
    #  Callbacks
    # ════════════════════════════════════════
    @bot.on(events.CallbackQuery)
    async def on_callback(event):
        cfg  = load_cfg()
        uid  = event.sender_id
        data = event.data.decode()

        if not is_authorised(uid):
            await event.answer("Access denied", alert=True)
            return

        owner = is_owner(uid)

        # ── Start / Stop ─────────────────────
        if data == "start":
            if owner:
                await start_all_accounts()
                await event.answer("All ads started")
            else:
                for label, acc in cfg["accounts"].items():
                    if acc.get("owner") == uid:
                        start_one(label)
                await event.answer("Your ads started")

        elif data == "stop":
            if owner:
                await stop_all_accounts()
                await event.answer("All ads stopped")
            else:
                for label, acc in cfg["accounts"].items():
                    if acc.get("owner") == uid:
                        stop_one(label)
                await event.answer("Your ads stopped")

        # ── Interval ─────────────────────────
        elif data == "interval":
            state[uid] = {"step": "interval"}
            await event.respond("Enter new interval in seconds (e.g. `90`):")

        # ── Accounts list ─────────────────────
        elif data == "accs":
            txt   = "📂 **Connected Accounts**\n\n"
            found = False
            for label, acc in cfg["accounts"].items():
                if owner or acc.get("owner") == uid:
                    icon     = "🟢" if label in account_tasks else "🔴"
                    owner_id = acc.get("owner", "?")
                    extra    = f" _(sub: `{owner_id}`)_" if owner and owner_id != uid else ""
                    txt     += f"{icon} **{acc['name']}**{extra}\n"
                    found    = True
            if not found:
                txt += "_No accounts connected._"
            await event.respond(txt)

        # ── Add account ───────────────────────
        elif data == "add":
            if not can_add_account(uid):
                await event.respond("Account limit reached. Contact owner.")
                return
            state[uid] = {"step": "phone"}
            await event.respond("Send phone number:\nExample: `+919876543210`")

        # ── Remove account ────────────────────
        elif data == "del":
            buttons = [
                [Button.inline(f"Remove {acc['name']}", f"delacc_{label}".encode())]
                for label, acc in cfg["accounts"].items()
                if owner or acc.get("owner") == uid
            ]
            if not buttons:
                await event.respond("No accounts found.")
                return
            await event.respond("Select account to remove:", buttons=buttons)

        elif data.startswith("delacc_"):
            label    = data[len("delacc_"):]
            acc      = cfg["accounts"].get(label, {})
            acc_name = acc.get("name", label)
            if not owner and acc.get("owner") != uid:
                await event.answer("Not your account", alert=True)
                return
            cfg["accounts"].pop(label, None)
            save_cfg(cfg)
            stop_one(label)
            await release_client(acc.get("session", ""))
            await event.respond(f"Account **{acc_name}** removed.")

        # ── Subscribers list ──────────────────
        elif data == "subs":
            if not owner:
                await event.answer("Owner only", alert=True)
                return
            users = cfg.get("users", {})
            if not users:
                await event.respond("No subscribers yet.")
                return
            txt = "👥 **Subscribers**\n\n"
            for u_id, u in users.items():
                used  = sum(1 for a in cfg["accounts"].values() if a.get("owner") == int(u_id))
                uname = f"@{u['username']}" if u.get("username") else f"`{u_id}`"
                txt  += f"• {uname} — limit `{u['limit']}` | used `{used}`\n"
            await event.respond(txt)

        # ── Add subscriber ────────────────────
        elif data == "add_sub":
            if not owner:
                await event.answer("Owner only", alert=True)
                return
            state[uid] = {"step": "add_sub"}
            await event.respond(
                "➕ **Add Subscriber**\n\n"
                "Format: `@username LIMIT`\n"
                "Example: `@rahul123 5`"
            )

        # ── Remove subscriber ─────────────────
        elif data == "del_sub":
            if not owner:
                await event.answer("Owner only", alert=True)
                return
            users = cfg.get("users", {})
            if not users:
                await event.respond("No subscribers found.")
                return
            buttons = []
            for u_id, u in users.items():
                uname  = f"@{u['username']}" if u.get("username") else f"ID:{u_id}"
                u_accs = sum(1 for a in cfg["accounts"].values() if a.get("owner") == int(u_id))
                buttons.append([
                    Button.inline(
                        f"{uname}  [{u_accs} accounts]",
                        f"delsub_{u_id}".encode()
                    )
                ])
            await event.respond("Select subscriber to remove:", buttons=buttons)

        elif data.startswith("delsub_"):
            if not owner:
                await event.answer("Owner only", alert=True)
                return
            target = data[len("delsub_"):]
            u      = cfg["users"].get(target, {})
            uname  = f"@{u.get('username','')}" if u.get("username") else f"`{target}`"
            cfg["users"].pop(target, None)
            save_cfg(cfg)
            await event.respond(f"Subscriber {uname} removed.")

        # ── Subscriber Groups — Step 1: pick subscriber ──
        elif data == "subgroups":
            if not owner:
                await event.answer("Owner only", alert=True)
                return
            users = cfg.get("users", {})
            if not users:
                await event.respond("No subscribers yet.")
                return
            buttons = []
            for u_id, u in users.items():
                uname = f"@{u['username']}" if u.get("username") else f"ID:{u_id}"
                buttons.append([Button.inline(f"👤 {uname}", f"sg_sub_{u_id}".encode())])
            await event.respond("📡 **Subscriber Groups**\n\nSelect subscriber:", buttons=buttons)

        # ── Step 2: pick account ──────────────
        elif data.startswith("sg_sub_"):
            if not owner:
                await event.answer("Owner only", alert=True)
                return
            target_id = data[len("sg_sub_"):]
            sub_accs  = {
                l: a for l, a in cfg["accounts"].items()
                if str(a.get("owner")) == target_id
            }
            if not sub_accs:
                await event.respond(
                    "No accounts linked to this subscriber.",
                    buttons=[[Button.inline("Back", b"subgroups")]]
                )
                return
            u     = cfg["users"].get(target_id, {})
            uname = f"@{u['username']}" if u.get("username") else f"ID:{target_id}"
            buttons = [
                [Button.inline(
                    ("🟢 " if l in account_tasks else "🔴 ") + a["name"],
                    f"sg_acc_{l}".encode()
                )]
                for l, a in sub_accs.items()
            ]
            buttons.append([Button.inline("Back", b"subgroups")])
            await event.respond(f"📱 **{uname}** — select account:", buttons=buttons)

        # ── Step 3: show groups ───────────────
        elif data.startswith("sg_acc_"):
            if not owner:
                await event.answer("Owner only", alert=True)
                return

            label = data[len("sg_acc_"):]
            acc   = cfg["accounts"].get(label)
            if not acc:
                await event.respond("Account not found.")
                return

            owner_id = str(acc.get("owner", ""))
            u        = cfg["users"].get(owner_id, {})
            uname    = f"@{u['username']}" if u.get("username") else f"ID:{owner_id}"
            back_cb  = f"sg_sub_{owner_id}".encode()

            await event.answer("Fetching groups...")

            try:
                # Uses global pool — same client as broadcast — no DB lock
                sub_client = await get_client(acc["session"])

                if not await sub_client.is_user_authorized():
                    await event.respond(
                        "Session expired. Ask subscriber to re-add account.",
                        buttons=[[Button.inline("Back", back_cb)]]
                    )
                    return

                groups = []
                async for dialog in sub_client.iter_dialogs():
                    if not dialog.is_group:
                        continue
                    entity   = dialog.entity
                    username = getattr(entity, "username", None)
                    if username:
                        link = f"https://t.me/{username}"
                    else:
                        try:
                            inv  = await sub_client(ExportChatInviteRequest(entity))
                            link = inv.link
                        except Exception:
                            link = None
                    link_line = link or "_unavailable_"
                    groups.append(f"• **{dialog.name}**\n  {link_line}")

            except Exception as e:
                await event.respond(
                    f"Error fetching groups: `{e}`",
                    buttons=[[Button.inline("Back", back_cb)]]
                )
                return

            status = "🟢 Running" if label in account_tasks else "🔴 Stopped"
            header = (
                f"📡 **{acc['name']}** ({uname}) — {status}\n"
                f"Total Groups: `{len(groups)}`\n\n"
            )

            if not groups:
                await event.respond(
                    header + "_No groups found._",
                    buttons=[[Button.inline("Back", back_cb)]]
                )
                return

            chunks = [groups[i:i + 20] for i in range(0, len(groups), 20)]
            for i, chunk in enumerate(chunks):
                h    = header if i == 0 else f"Page {i+1}/{len(chunks)}\n\n"
                txt  = h + "\n\n".join(chunk)
                btns = [[Button.inline("Back", back_cb)]] if i == len(chunks) - 1 else None
                await event.respond(txt, buttons=btns)

    # ════════════════════════════════════════
    #  Message handler (state machine)
    # ════════════════════════════════════════
    @bot.on(events.NewMessage)
    async def on_message(event):
        uid = event.sender_id
        if uid not in state:
            return

        step = state[uid]["step"]
        cfg  = load_cfg()

        # ── Interval ─────────────────────────
        if step == "interval":
            try:
                val = int(event.raw_text.strip())
                cfg["interval"] = val
                save_cfg(cfg)
                state.pop(uid)
                await event.respond(f"Interval set to `{val} sec`")
            except ValueError:
                await event.respond("Enter a valid number.")

        # ── Add subscriber ────────────────────
        elif step == "add_sub":
            parts = event.raw_text.strip().split()
            if len(parts) != 2 or not parts[1].isdigit():
                await event.respond("Format: `@username LIMIT`\nExample: `@rahul123 5`")
                return

            username = parts[0].lstrip("@")
            limit    = int(parts[1])

            try:
                user = await bot.get_entity(username)
            except Exception:
                await event.respond(
                    f"`@{username}` not found. Make sure they have started the bot."
                )
                return

            target_id = str(user.id)
            if target_id in cfg["users"]:
                await event.respond(f"`@{username}` is already a subscriber.")
                state.pop(uid)
                return

            cfg["users"][target_id] = {"username": username, "limit": limit}
            save_cfg(cfg)
            state.pop(uid)
            await event.respond(
                f"Subscriber added!\n\n"
                f"@{username} | ID: `{target_id}` | Limit: `{limit}`"
            )

        # ── Phone ─────────────────────────────
        elif step == "phone":
            phone = event.raw_text.strip()
            if not phone.startswith("+"):
                await event.respond("Format: `+919876543210`")
                return

            label  = f"acc_{uid}_{len(cfg['accounts']) + 1}"
            client = TelegramClient(f"session_{label}", API_ID, API_HASH)
            await client.connect()
            result = await client.send_code_request(phone)

            state[uid] = {
                "step":   "otp",
                "client": client,
                "phone":  phone,
                "hash":   result.phone_code_hash,
                "label":  label,
            }
            await event.respond("Enter the OTP:")

        # ── OTP ───────────────────────────────
        elif step == "otp":
            client = state[uid]["client"]
            try:
                await client.sign_in(
                    state[uid]["phone"],
                    event.raw_text.strip(),
                    phone_code_hash=state[uid]["hash"],
                )
            except PhoneCodeExpiredError:
                state.pop(uid)
                await event.respond("OTP expired. Please add the account again.")
                return
            except PhoneCodeInvalidError:
                await event.respond("Invalid OTP. Try again.")
                return
            except SessionPasswordNeededError:
                state[uid]["step"] = "password"
                await event.respond("Enter your 2FA password:")
                return

            await _finish_add(event, uid, client, cfg)

        # ── 2FA Password ──────────────────────
        elif step == "password":
            client = state[uid]["client"]
            try:
                await client.sign_in(password=event.raw_text.strip())
            except Exception as e:
                await event.respond(f"2FA failed: `{e}`")
                return
            await _finish_add(event, uid, client, cfg)

    # ─────────────────────────────────────────
    #  Helper: finish account add
    # ─────────────────────────────────────────
    async def _finish_add(event, uid: int, client: TelegramClient, cfg: dict):
        label        = state[uid]["label"]
        me           = await client.get_me()
        logs         = await create_logs_channel(client, me.first_name)
        session_path = f"session_{label}"

        # Register in global pool so broadcast uses the same instance
        clients[session_path] = client

        cfg["accounts"][label] = {
            "session": session_path,
            "name":    me.first_name,
            "owner":   uid,
            "logs":    logs,
        }
        save_cfg(cfg)
        state.pop(uid)
        await event.respond(f"Account **{me.first_name}** added successfully!")

    await bot.run_until_disconnected()


asyncio.run(run_bot())
