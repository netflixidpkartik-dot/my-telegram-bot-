import asyncio
import json
import os
import random

from telethon import TelegramClient, events, Button
from telethon.errors import FloodWaitError, SessionPasswordNeededError, PhoneCodeExpiredError, PhoneCodeInvalidError
from telethon.tl.functions.channels import CreateChannelRequest

BOT_TOKEN = "8639594670:AAESsjZn3OgDzVkde6juVD8OOwk2RhdJ3us"
API_ID = 30298985
API_HASH = "0e632624d1551bc099a2ed8563962717"

CONFIG = "accounts.json"

DEFAULT_INTERVAL = 90
CYCLE_DELAY = 60

state = {}
account_tasks = {}


# ─────────────────────────────────────────
#  Config helpers
# ─────────────────────────────────────────

def load_cfg():
    if os.path.exists(CONFIG):
        with open(CONFIG) as f:
            return json.load(f)
    return {
        "owner": 0,
        "accounts": {},
        "interval": DEFAULT_INTERVAL,
        "users": {}
    }


def save_cfg(data):
    with open(CONFIG, "w") as f:
        json.dump(data, f, indent=2)


def is_authorised(uid):
    cfg = load_cfg()
    return uid == cfg["owner"] or str(uid) in cfg.get("users", {})


def can_add_account(uid):
    cfg = load_cfg()
    if uid == cfg["owner"]:
        return True
    if str(uid) not in cfg["users"]:
        return False
    limit = cfg["users"][str(uid)]["limit"]
    user_accounts = [a for a in cfg["accounts"].values() if a.get("owner") == uid]
    return len(user_accounts) < limit


# ─────────────────────────────────────────
#  Log channel
# ─────────────────────────────────────────

async def create_logs_channel(client, name):
    result = await client(
        CreateChannelRequest(
            title=f"{name} Logs",
            about="Account activity logs",
            megagroup=False
        )
    )
    return result.chats[0].id


async def send_log(client, log_channel, text):
    if not log_channel:
        return
    try:
        await client.send_message(log_channel, text)
    except Exception:
        pass


# ─────────────────────────────────────────
#  Broadcast loop
# ─────────────────────────────────────────

async def broadcast_account_loop(label, acc):
    client = TelegramClient(acc["session"], API_ID, API_HASH)
    await client.start()
    log_channel = acc.get("logs")

    while True:
        cfg = load_cfg()
        interval = cfg["interval"]

        try:
            msg = await client.get_messages("me", limit=1)
        except Exception:
            await asyncio.sleep(10)
            continue

        if not msg:
            await asyncio.sleep(CYCLE_DELAY)
            continue

        message = msg[0]

        async for dialog in client.iter_dialogs():
            if not dialog.is_group:
                continue
            try:
                if message.text:
                    await client.send_message(dialog.id, message.text)
                elif message.media:
                    await client.send_file(dialog.id, message.media, caption=message.text)

                await send_log(client, log_channel, f"Sent message → {dialog.name}")
                await asyncio.sleep(random.randint(interval, interval + 30))

            except FloodWaitError as e:
                await send_log(client, log_channel, f"FloodWait {e.seconds}s")
                await asyncio.sleep(e.seconds)

            except Exception as e:
                await send_log(client, log_channel, f"Error: {str(e)}")

        await asyncio.sleep(CYCLE_DELAY)


async def start_accounts():
    cfg = load_cfg()
    for label, acc in cfg["accounts"].items():
        if label not in account_tasks:
            task = asyncio.create_task(broadcast_account_loop(label, acc))
            account_tasks[label] = task


async def stop_accounts():
    for task in account_tasks.values():
        task.cancel()
    account_tasks.clear()


# ─────────────────────────────────────────
#  Bot
# ─────────────────────────────────────────

async def run_bot():
    bot = TelegramClient("control_panel_bot", API_ID, API_HASH)
    await bot.start(bot_token=BOT_TOKEN)

    # ── /start ──────────────────────────────
    @bot.on(events.NewMessage(pattern="/start"))
    async def start(event):
        cfg = load_cfg()

        if cfg["owner"] == 0:
            cfg["owner"] = event.sender_id
            save_cfg(cfg)

        uid = event.sender_id

        if uid != cfg["owner"] and str(uid) not in cfg.get("users", {}):
            await event.respond(
                "╔══════════════════════╗\n"
                "         🚫 ACCESS DENIED 🚫\n"
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

        # ── Non-owner (subscriber) panel ────
        if uid != cfg["owner"]:
            plan          = cfg["users"][str(uid)]["limit"]
            user_name     = cfg["users"][str(uid)].get("name", "User")
            user_accounts = [a for a in cfg["accounts"].values() if a.get("owner") == uid]
            accounts      = len(user_accounts)
            running_accs  = sum(1 for l, a in cfg["accounts"].items()
                                if a.get("owner") == uid and l in account_tasks)
            slots_left    = plan - accounts
            status_bar    = "🟢" * running_accs + "🔴" * (accounts - running_accs) + "⚫" * slots_left

            msg = (
                f"╔══════════════════════╗\n"
                f"     🚀  DUSTIN ADBOT  🚀\n"
                f"╚══════════════════════╝\n\n"
                f"👋 Welcome back, **{user_name}**!\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📊 **Your Dashboard**\n\n"
                f"   📱 Accounts Slot  :  `{accounts} / {plan}`\n"
                f"   🟢 Running        :  `{running_accs}`\n"
                f"   🔴 Stopped        :  `{accounts - running_accs}`\n"
                f"   ⚫ Slots Left     :  `{slots_left}`\n"
                f"   ⏱️ Send Interval  :  `{cfg['interval']} sec`\n\n"
                f"   {status_bar}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"⚡ **Bot Features**\n\n"
                f"   🤖  Auto-broadcast to ALL your groups\n"
                f"   📱  Multiple Telegram accounts support\n"
                f"   🔁  Runs 24/7 without interruption\n"
                f"   🛡️  Flood-wait protection built-in\n"
                f"   🖼️  Text & media messages supported\n"
                f"   📊  Live activity logs per account\n"
                f"   ⚙️  Custom interval between messages\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"💡 **Quick Guide**\n\n"
                f"   1️⃣  Add your account  →  ➕ Add Account\n"
                f"   2️⃣  Start broadcasting  →  🚀 Start Ads\n"
                f"   3️⃣  Monitor activity  →  📂 My Accounts\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💎 **DUSTIN ADBOT** — Premium Subscription"
            )

            await event.respond(
                msg,
                buttons=[
                    [Button.inline("➕ Add Account", b"add"),
                     Button.inline("📂 My Accounts", b"accs")],
                    [Button.inline("🗑️ Remove Account", b"del")],
                    [Button.inline("🚀 Start Ads", b"start"),
                     Button.inline("⛔ Stop Ads",  b"stop")],
                    [Button.inline("⏱️ Set Interval", b"interval")]
                ]
            )
            return

        # ── Owner panel ──────────────────────
        running = len(account_tasks)
        total   = len(cfg["accounts"])
        subs    = len(cfg.get("users", {}))

        msg = (
            f"👑 **Owner Control Panel**\n\n"
            f"📊 Accounts: `{total}` | Running: `{running}`\n"
            f"👥 Subscribers: `{subs}`\n"
            f"⏱ Interval: `{cfg['interval']} sec`"
        )

        await event.respond(
            msg,
            buttons=[
                [Button.inline("📂 Accounts", b"accs"),
                 Button.inline("➕ Add Account", b"add")],
                [Button.inline("👥 Subscribers", b"subs"),
                 Button.inline("➕ Add Sub", b"add_sub")],
                [Button.inline("❌ Remove Account", b"del"),
                 Button.inline("🗑 Remove Sub", b"del_sub")],
                [Button.inline("🚀 Start Ads", b"start"),
                 Button.inline("⛔ Stop Ads", b"stop")],
                [Button.inline("⏱ Interval", b"interval")],
                [Button.inline("📡 Subscriber Groups", b"subgroups")]
            ]
        )

    # ── Callbacks ───────────────────────────
    @bot.on(events.CallbackQuery)
    async def callback(event):
        cfg = load_cfg()
        uid = event.sender_id
        data = event.data.decode()

        if not is_authorised(uid):
            await event.answer("Access denied", alert=True)
            return

        # ── Start / Stop ─────────────────────
        if data == "start":
            await start_accounts()
            await event.answer("✅ Ads started")

        elif data == "stop":
            await stop_accounts()
            await event.answer("⛔ Ads stopped")

        # ── Interval ─────────────────────────
        elif data == "interval":
            state[uid] = {"step": "interval"}
            await event.respond("⏱ Send new interval in seconds (e.g. `90`)")

        # ── All accounts list ─────────────────
        elif data == "accs":
            txt = "📂 **Connected Accounts**\n\n"
            found = False

            for label, acc in cfg["accounts"].items():
                if uid == cfg["owner"] or acc.get("owner") == uid:
                    running = "🟢" if label in account_tasks else "🔴"
                    owner_id = acc.get("owner", "?")
                    owner_note = " _(you)_" if owner_id == uid else f" _(sub: `{owner_id}`)_"
                    txt += f"{running} **{acc['name']}**{owner_note if uid == cfg['owner'] else ''}\n"
                    found = True

            if not found:
                txt += "_No accounts connected._"

            await event.respond(txt)

        # ── Add account ───────────────────────
        elif data == "add":
            if not can_add_account(uid):
                await event.respond("⚠️ Account limit reached.")
                return
            state[uid] = {"step": "phone"}
            await event.respond("📱 Send phone number\nExample: `+919876543210`")

        # ── Remove account ────────────────────
        elif data == "del":
            buttons = []
            for label, acc in cfg["accounts"].items():
                if acc.get("owner") == uid or uid == cfg["owner"]:
                    buttons.append(
                        [Button.inline(f"🗑 {acc['name']}", f"delacc_{label}".encode())]
                    )
            if not buttons:
                await event.respond("No accounts found.")
                return
            await event.respond("Select account to remove:", buttons=buttons)

        elif data.startswith("delacc_"):
            label = data.replace("delacc_", "")
            acc_name = cfg["accounts"].get(label, {}).get("name", label)
            if label in cfg["accounts"]:
                del cfg["accounts"][label]
                save_cfg(cfg)
                if label in account_tasks:
                    account_tasks[label].cancel()
                    del account_tasks[label]
            await event.respond(f"✅ Account **{acc_name}** removed.")

        # ══════════════════════════════════════
        #  OWNER-ONLY FEATURES
        # ══════════════════════════════════════

        # ── List subscribers ──────────────────
        elif data == "subs":
            if uid != cfg["owner"]:
                await event.answer("Owner only", alert=True)
                return

            users = cfg.get("users", {})
            if not users:
                await event.respond("👥 No subscribers yet.")
                return

            txt = "👥 **Subscribers List**\n\n"
            for u_id, u_data in users.items():
                u_accounts = [a for a in cfg["accounts"].values() if a.get("owner") == int(u_id)]
                uname = f"@{u_data['username']}" if u_data.get("username") else f"ID: `{u_id}`"
                txt += (
                    f"🔹 {uname}\n"
                    f"   Name: **{u_data.get('name', 'Unknown')}**\n"
                    f"   ID: `{u_id}`\n"
                    f"   Limit: `{u_data['limit']}` | Used: `{len(u_accounts)}`\n\n"
                )
            await event.respond(txt)

        # ── Add subscriber ────────────────────
        elif data == "add_sub":
            if uid != cfg["owner"]:
                await event.answer("Owner only", alert=True)
                return
            state[uid] = {"step": "add_sub_username"}
            await event.respond(
                "➕ **Add Subscriber**\n\n"
                "Username aur limit bhejo:\n"
                "Format: `@username LIMIT`\n"
                "Example: `@rahul123 5`"
            )

        # ── Remove subscriber ─────────────────
        elif data == "del_sub":
            if uid != cfg["owner"]:
                await event.answer("Owner only", alert=True)
                return

            users = cfg.get("users", {})
            if not users:
                await event.respond("❌ Koi subscriber nahi hai.")
                return

            buttons = []
            for u_id, u_data in users.items():
                name    = u_data.get("name", "Unknown")
                uname   = f"@{u_data['username']}" if u_data.get("username") else f"ID:{u_id}"
                u_accs  = len([a for a in cfg["accounts"].values() if a.get("owner") == int(u_id)])
                buttons.append([
                    Button.inline(
                        f"👤 {name}  {uname}  [{u_accs} acc]",
                        f"delsub_confirm_{u_id}".encode()
                    )
                ])

            await event.respond("🗑 **Subscriber hatao** — kisko remove karna hai?", buttons=buttons)

        elif data.startswith("delsub_confirm_"):
            if uid != cfg["owner"]:
                await event.answer("Owner only", alert=True)
                return

            target_id = data.replace("delsub_confirm_", "")
            u_data    = cfg["users"].get(target_id, {})
            name      = u_data.get("name", "Unknown")
            uname     = f"@{u_data['username']}" if u_data.get("username") else f"ID:{target_id}"
            u_accs    = len([a for a in cfg["accounts"].values() if a.get("owner") == int(target_id)])

            await event.respond(
                f"⚠️ **Confirm karo**\n\n"
                f"👤 {name}  ({uname})\n"
                f"🆔 ID: `{target_id}`\n"
                f"📱 Linked accounts: `{u_accs}`\n\n"
                f"Isko remove karna hai?",
                buttons=[
                    [Button.inline("✅ Haan, hatao", f"delsub_yes_{target_id}".encode()),
                     Button.inline("❌ Cancel",      b"del_sub")]
                ]
            )

        elif data.startswith("delsub_yes_"):
            if uid != cfg["owner"]:
                await event.answer("Owner only", alert=True)
                return

            target_id = data.replace("delsub_yes_", "")
            u_data    = cfg["users"].get(target_id, {})
            name      = u_data.get("name", target_id)
            uname     = f"@{u_data.get('username', '')}" if u_data.get("username") else f"`{target_id}`"

            if target_id in cfg["users"]:
                del cfg["users"][target_id]
                save_cfg(cfg)

            await event.respond(f"✅ Subscriber **{name}** ({uname}) remove ho gaya.")

        # ── Subscriber groups viewer ──────────
        elif data == "subgroups":
            if uid != cfg["owner"]:
                await event.answer("Owner only", alert=True)
                return

            users = cfg.get("users", {})
            if not users:
                await event.respond("❌ Koi subscriber nahi hai.")
                return

            buttons = []
            for u_id, u_data in users.items():
                name  = u_data.get("name", "Unknown")
                uname = f"@{u_data['username']}" if u_data.get("username") else f"ID:{u_id}"
                buttons.append([
                    Button.inline(
                        f"👤 {name}  {uname}",
                        f"subgroups_{u_id}".encode()
                    )
                ])

            await event.respond("📡 **Subscriber Groups**\n\nKis subscriber ke accounts dekhne hain?", buttons=buttons)

        # Subscriber tap → show their linked accounts
        elif data.startswith("subgroups_") and not data.startswith("subgacc_"):
            if uid != cfg["owner"]:
                await event.answer("Owner only", alert=True)
                return

            target_id  = data.replace("subgroups_", "")
            u_data     = cfg["users"].get(target_id, {})
            name       = u_data.get("name", "Unknown")
            uname      = f"@{u_data['username']}" if u_data.get("username") else f"ID:{target_id}"

            sub_accounts = {
                label: acc for label, acc in cfg["accounts"].items()
                if str(acc.get("owner")) == target_id
            }

            if not sub_accounts:
                await event.respond(
                    f"📭 **{name}** ({uname}) ka koi account linked nahi hai.",
                    buttons=[[Button.inline("« Wapas", b"subgroups")]]
                )
                return

            buttons = []
            for label, acc in sub_accounts.items():
                running = "🟢" if label in account_tasks else "🔴"
                buttons.append([
                    Button.inline(
                        f"{running} {acc['name']}",
                        f"subgacc_{label}".encode()
                    )
                ])
            buttons.append([Button.inline("« Wapas", b"subgroups")])

            await event.respond(
                f"📱 **{name}** ({uname}) ke accounts:\n\nKis account ke groups dekhne hain?",
                buttons=buttons
            )

        # Account tap → show its groups
        elif data.startswith("subgacc_"):
            if uid != cfg["owner"]:
                await event.answer("Owner only", alert=True)
                return

            label = data.replace("subgacc_", "")
            acc   = cfg["accounts"].get(label)

            if not acc:
                await event.respond("⚠️ Account nahi mila.")
                return

            owner_id = str(acc.get("owner", ""))
            u_data   = cfg["users"].get(owner_id, {})
            uname    = f"@{u_data['username']}" if u_data.get("username") else f"ID:{owner_id}"
            back_cb  = f"subgroups_{owner_id}".encode()

            await event.answer("Groups fetch ho raha hai…")

            try:
                from telethon.tl.functions.messages import ExportChatInviteRequest

                sub_client = TelegramClient(acc["session"], API_ID, API_HASH)
                await sub_client.connect()
                groups = []

                async for dialog in sub_client.iter_dialogs():
                    if not dialog.is_group:
                        continue

                    name   = dialog.name or "Unknown"
                    entity = dialog.entity

                    # Public username link
                    username = getattr(entity, "username", None)
                    if username:
                        link = f"https://t.me/{username}"
                    else:
                        try:
                            inv  = await sub_client(ExportChatInviteRequest(entity))
                            link = inv.link
                        except Exception:
                            link = None

                    link_line = link if link else "_link unavailable_"
                    groups.append(f"• **{name}**\n  🔗 {link_line}")

                await sub_client.disconnect()

            except Exception as e:
                await event.respond(
                    f"❌ Groups fetch nahi ho sake: `{e}`",
                    buttons=[[Button.inline("« Wapas", back_cb)]]
                )
                return

            running = "🟢 Running" if label in account_tasks else "🔴 Stopped"
            header  = (
                f"📡 **{acc['name']}** ({uname}) — {running}\n"
                f"📊 Total Groups: **{len(groups)}**\n\n"
            )

            if not groups:
                await event.respond(
                    header + "_Koi group nahi mila._",
                    buttons=[[Button.inline("« Wapas", back_cb)]]
                )
                return

            # Split into chunks of 20 groups per message (Telegram 4096 char limit)
            chunk_size = 20
            chunks = [groups[i:i+chunk_size] for i in range(0, len(groups), chunk_size)]

            for i, chunk in enumerate(chunks):
                part_header = header if i == 0 else f"📄 **Page {i+1}/{len(chunks)}**\n\n"
                txt = part_header + "\n\n".join(chunk)
                is_last = (i == len(chunks) - 1)
                btns = [[Button.inline("« Wapas", back_cb)]] if is_last else None
                await event.respond(txt, buttons=btns)

    # ── Message handler (state machine) ─────
    @bot.on(events.NewMessage)
    async def handler(event):
        uid = event.sender_id

        if uid not in state:
            return

        step = state[uid]["step"]
        cfg = load_cfg()

        # ── Interval ─────────────────────────
        if step == "interval":
            try:
                cfg["interval"] = int(event.raw_text.strip())
                save_cfg(cfg)
                del state[uid]
                await event.respond(f"✅ Interval updated to `{cfg['interval']} sec`")
            except ValueError:
                await event.respond("⚠️ Send a valid number.")

        # ── Add subscriber: @username + limit ──
        elif step == "add_sub_username":
            parts = event.raw_text.strip().split()
            if len(parts) != 2 or not parts[1].isdigit():
                await event.respond(
                    "⚠️ Format galat hai.\nBhejo: `@username LIMIT`\nExample: `@rahul123 5`"
                )
                return

            username = parts[0].lstrip("@")
            limit = int(parts[1])

            try:
                user = await bot.get_entity(username)
            except Exception:
                await event.respond(
                    f"❌ `@{username}` nahi mila. Check karo username sahi hai aur usne bot ko start kiya ho."
                )
                return

            target_id = str(user.id)
            name = user.first_name or username
            if getattr(user, "last_name", None):
                name += f" {user.last_name}"

            if target_id in cfg["users"]:
                await event.respond(f"⚠️ `@{username}` pehle se subscriber hai.")
                del state[uid]
                return

            cfg["users"][target_id] = {"name": name, "username": username, "limit": limit}
            save_cfg(cfg)
            del state[uid]

            await event.respond(
                f"✅ **Subscriber add ho gaya!**\n\n"
                f"👤 Name: **{name}**\n"
                f"🔗 Username: `@{username}`\n"
                f"🆔 ID: `{target_id}`\n"
                f"📊 Limit: `{limit}` accounts"
            )

        # ── Phone ─────────────────────────────
        elif step == "phone":
            phone = (event.raw_text or "").strip()
            if not phone or not phone.startswith("+"):
                await event.respond("⚠️ Send phone like `+919876543210`")
                return

            label = f"acc_{uid}_{len(cfg['accounts'])+1}"
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
            await event.respond("✉️ OTP code bhejo:")

        # ── OTP ───────────────────────────────
        elif step == "otp":
            client = state[uid]["client"]

            try:
                await client.sign_in(
                    state[uid]["phone"],
                    event.raw_text.strip(),
                    phone_code_hash=state[uid]["hash"]
                )

            except PhoneCodeExpiredError:
                del state[uid]
                await event.respond("❌ OTP expired. Please add the account again.")
                return

            except PhoneCodeInvalidError:
                await event.respond("❌ Invalid OTP. Send the correct code.")
                return

            except SessionPasswordNeededError:
                state[uid]["step"] = "password"
                await event.respond("🔐 Send your 2FA password:")
                return

            me = await client.get_me()
            logs = await create_logs_channel(client, me.first_name)

            cfg["accounts"][state[uid]["label"]] = {
                "session": f"session_{state[uid]['label']}",
                "name": me.first_name,
                "owner": uid,
                "logs": logs
            }

            save_cfg(cfg)
            await client.disconnect()
            del state[uid]

            await event.respond(f"✅ Account **{me.first_name}** added successfully!")

        # ── 2FA Password ──────────────────────
        elif step == "password":
            client = state[uid]["client"]
            await client.sign_in(password=event.raw_text.strip())
            me = await client.get_me()
            logs = await create_logs_channel(client, me.first_name)

            cfg["accounts"][state[uid]["label"]] = {
                "session": f"session_{state[uid]['label']}",
                "name": me.first_name,
                "owner": uid,
                "logs": logs
            }
            save_cfg(cfg)
            await client.disconnect()
            del state[uid]
            await event.respond(f"✅ Account **{me.first_name}** added successfully!")

    await bot.run_until_disconnected()


asyncio.run(run_bot())
