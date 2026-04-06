import asyncio
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.tl.types import Channel, Chat
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError
)

# ── CONFIG ──
BOT_TOKEN        = "8783380951:AAEMqv7e_V9-m4yKxUdMf3Fr40coBGUEP0Q"
API_ID    = 37827563
API_HASH  = "abca86f59db00e94244dd14df8259ff0"
DELAY     = 10

state = {}

def make_client():
    # ALWAYS fresh client (critical fix)
    return TelegramClient(StringSession(), API_ID, API_HASH)

# ── GET GROUPS ──
async def get_groups(client):
    groups = []
    async for dialog in client.iter_dialogs():
        e = dialog.entity
        if isinstance(e, Chat):
            groups.append(dialog)
        elif isinstance(e, Channel) and e.megagroup:
            groups.append(dialog)
    return groups

# ── BROADCAST ──
async def do_broadcast(bot, uid, session_string, message):
    await bot.send_message(uid, "📡 Starting broadcast...")
    client = TelegramClient(StringSession(session_string), API_ID, API_HASH)

    await client.connect()
    groups = await get_groups(client)

    for i, g in enumerate(groups, 1):
        try:
            await client.send_message(g.entity, message)
            await bot.send_message(uid, f"[{i}] ✅ {g.name}")
        except Exception as e:
            await bot.send_message(uid, f"[{i}] ❌ {g.name}: {e}")
        await asyncio.sleep(DELAY)

    await client.disconnect()
    await bot.send_message(uid, "🎉 Broadcast complete!")

# ── MAIN ──
async def main():
    bot = TelegramClient("bot_session", API_ID, API_HASH)
    await bot.start(bot_token=BOT_TOKEN)

    print("✅ Bot running...")

    # ── START ──
    @bot.on(events.NewMessage(pattern="/start"))
    async def start(event):
        uid = event.sender_id
        state.pop(uid, None)

        await event.respond(
            "👋 Send your phone number\n"
            "Example: +919876543210"
        )

    # ── RESEND OTP ──
    @bot.on(events.CallbackQuery(data=b"resend"))
    async def resend(event):
        uid = event.sender_id

        if uid not in state:
            await event.respond("❌ Start again with /start")
            return

        phone = state[uid]["phone"]

        # 🔥 FULL RESET (IMPORTANT)
        try:
            await state[uid]["client"].disconnect()
        except:
            pass

        client = make_client()
        await client.connect()

        result = await client.send_code_request(phone)

        state[uid]["client"] = client
        state[uid]["hash"]   = result.phone_code_hash

        await event.respond(
            "✅ New OTP sent (use immediately!)",
            buttons=[[Button.inline("🔄 Resend OTP", b"resend")]]
        )

    # ── HANDLER ──
    @bot.on(events.NewMessage())
    async def handler(event):
        uid  = event.sender_id
        text = (event.text or "").strip()

        if text.startswith("/"):
            return

        # ── PHONE ──
        if text.startswith("+") and uid not in state:
            client = make_client()
            await client.connect()

            result = await client.send_code_request(text)

            state[uid] = {
                "step":  "otp",
                "phone": text,
                "hash":  result.phone_code_hash,
                "client": client
            }

            await event.respond(
                "✅ OTP sent\nEnter it FAST:",
                buttons=[[Button.inline("🔄 Resend OTP", b"resend")]]
            )
            return

        if uid not in state:
            await event.respond("Send /start first")
            return

        s = state[uid]

        # ── OTP ──
        if s["step"] == "otp":
            client = s["client"]

            try:
                code = "".join(filter(str.isdigit, text))

                await client.sign_in(
                    phone=s["phone"],
                    code=code,
                    phone_code_hash=s["hash"]
                )

                me = await client.get_me()
                session_string = client.session.save()

                await client.disconnect()

                s["session"] = session_string
                s["step"] = "msg"

                await event.respond(
                    f"✅ Logged in as {me.first_name}\n\nSend message to broadcast"
                )

            # 🔥 AUTO FIX ON EXPIRE
            except PhoneCodeExpiredError:
                await event.respond("⌛ Expired → sending new OTP...")

                try:
                    await client.disconnect()
                except:
                    pass

                new_client = make_client()
                await new_client.connect()

                result = await new_client.send_code_request(s["phone"])

                s["client"] = new_client
                s["hash"]   = result.phone_code_hash

                await event.respond(
                    "✅ New OTP sent. Enter NOW:",
                    buttons=[[Button.inline("🔄 Resend OTP", b"resend")]]
                )

            except PhoneCodeInvalidError:
                await event.respond("❌ Wrong OTP. Try again.")

            except SessionPasswordNeededError:
                s["step"] = "2fa"
                await event.respond("🔒 Enter 2FA password")

            except Exception as e:
                await event.respond(f"❌ Error: {e}")
                state.pop(uid, None)

        # ── 2FA ──
        elif s["step"] == "2fa":
            client = s["client"]

            try:
                await client.sign_in(password=text)

                me = await client.get_me()
                session_string = client.session.save()

                await client.disconnect()

                s["session"] = session_string
                s["step"] = "msg"

                await event.respond(
                    f"✅ Logged in as {me.first_name}\n\nSend message"
                )

            except Exception as e:
                await event.respond(f"❌ {e}")
                state.pop(uid, None)

        # ── MESSAGE ──
        elif s["step"] == "msg":
            asyncio.create_task(
                do_broadcast(bot, uid, s["session"], text)
            )
            s["step"] = "idle"

    await bot.run_until_disconnected()

asyncio.run(main())
