import asyncio
import os
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.tl.types import Channel, Chat
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError
)

# ── CONFIG ──
BOT_TOKEN     = "8783380951:AAEMqv7e_V9-m4yKxUdMf3Fr40coBGUEP0Q"
API_ID        = 37827563
API_HASH      = "abca86f59db00e94244dd14df8259ff0"
DELAY         = 10   # seconds between each group message

state = {}  # stores per-user login state

def make_client(session=None):
    return TelegramClient(
        StringSession(session) if session else StringSession(),
        API_ID, API_HASH
    )

async def get_groups(client):
    groups = []
    async for dialog in client.iter_dialogs():
        e = dialog.entity
        if isinstance(e, Chat):
            groups.append(dialog)
        elif isinstance(e, Channel) and e.megagroup:
            groups.append(dialog)
    return groups

async def do_broadcast(bot, uid, session_string, message):
    await bot.send_message(uid, "📡 Starting broadcast...")
    try:
        client = make_client(session_string)
        await client.connect()
        groups  = await get_groups(client)
        success = 0
        failed  = 0
        for i, dialog in enumerate(groups, 1):
            try:
                await client.send_message(dialog.entity, message)
                success += 1
                await bot.send_message(uid, f"[{i}/{len(groups)}] ✅ {dialog.name}")
            except Exception as e:
                failed += 1
                await bot.send_message(uid, f"[{i}/{len(groups)}] ❌ {dialog.name}: {e}")
            await asyncio.sleep(DELAY)
        await client.disconnect()
        await bot.send_message(uid, f"\n🎉 Done! ✅ {success} sent  ❌ {failed} failed")
    except Exception as e:
        await bot.send_message(uid, f"❌ Broadcast error: {e}")

async def main():
    bot = TelegramClient("bot_session", API_ID, API_HASH)
    await bot.start(bot_token=BOT_TOKEN)
    print("✅ Bot running...")

    # ── /start ──
    @bot.on(events.NewMessage(pattern="/start"))
    async def start(event):
        uid = event.sender_id
        state.pop(uid, None)
        await event.respond(
            "👋 *Welcome to Group Broadcaster!*\n\n"
            "Step 1: Send your phone number\n"
            "_(e.g. `+919876543210`)_"
        )

    # ── Resend OTP button ──
    @bot.on(events.CallbackQuery(data=b"resend"))
    async def resend(event):
        await event.answer()
        uid = event.sender_id
        if uid not in state or state[uid]["step"] != "otp":
            await event.respond("❌ No active session. Send /start to begin.")
            return

        s     = state[uid]
        phone = s["phone"]

        try:
            old = s.get("client")
            if old:
                await old.disconnect()
        except Exception:
            pass

        await event.respond("🔄 Resending OTP...")
        try:
            client = make_client()
            await client.connect()
            result = await client.send_code_request(phone)
            s["client"]     = client
            s["phone_hash"] = result.phone_code_hash
            await event.respond(
                "✅ New OTP sent! Enter it below:",
                buttons=[[Button.inline("🔄 Resend OTP", b"resend")]]
            )
        except Exception as e:
            await event.respond(f"❌ Resend failed: {e}\n\nSend /start to try again.")
            state.pop(uid, None)

    # ── Main message handler ──
    @bot.on(events.NewMessage())
    async def handler(event):
        uid  = event.sender_id
        text = (event.text or "").strip()

        if text.startswith("/"):
            return

        # ── Phone number (first step) ──
        if text.startswith("+") and (uid not in state or state[uid]["step"] == "idle"):
            await event.respond("📱 Sending OTP to your Telegram app...")
            try:
                client = make_client()
                await client.connect()
                result = await client.send_code_request(text)
                state[uid] = {
                    "step":       "otp",
                    "phone":      text,
                    "phone_hash": result.phone_code_hash,
                    "client":     client,
                    "session":    None,
                }
                await event.respond(
                    "✅ OTP sent!\n\nEnter the code from your Telegram app:",
                    buttons=[[Button.inline("🔄 Resend OTP", b"resend")]]
                )
            except Exception as e:
                await event.respond(f"❌ Error sending OTP: {e}")
            return

        if uid not in state:
            await event.respond("Send /start to begin.")
            return

        s = state[uid]

        # ── OTP step ──
        if s["step"] == "otp":
            client = s["client"]
            phone  = s["phone"]
            try:
                code = "".join(filter(str.isdigit, text))
                await client.sign_in(
                    phone=phone,
                    code=code,
                    phone_code_hash=s["phone_hash"]
                )
                me             = await client.get_me()
                session_string = client.session.save()
                await client.disconnect()

                s["session"] = session_string
                s["step"]    = "message"
                await event.respond(
                    f"✅ Logged in as *{me.first_name}*!\n\n"
                    f"Now send me the *message* you want to broadcast to all groups:"
                )

            except PhoneCodeExpiredError:
                await event.respond("⌛ OTP expired! Sending a new one...")
                try:
                    await client.disconnect()
                except Exception:
                    pass
                try:
                    new_client = make_client()
                    await new_client.connect()
                    result          = await new_client.send_code_request(phone)
                    s["client"]     = new_client
                    s["phone_hash"] = result.phone_code_hash
                    await event.respond(
                        "✅ New OTP sent! Enter it:",
                        buttons=[[Button.inline("🔄 Resend OTP", b"resend")]]
                    )
                except Exception as e:
                    await event.respond(f"❌ Could not resend: {e}\n\nSend /start to try again.")
                    state.pop(uid, None)

            except PhoneCodeInvalidError:
                await event.respond(
                    "❌ Wrong OTP. Try again:",
                    buttons=[[Button.inline("🔄 Resend OTP", b"resend")]]
                )

            except SessionPasswordNeededError:
                s["step"] = "2fa"
                await event.respond("🔒 2FA enabled. Enter your Telegram password:")

            except Exception as e:
                await event.respond(f"❌ Error: {e}\n\nSend /start to try again.")
                try:
                    await client.disconnect()
                except Exception:
                    pass
                state.pop(uid, None)

        # ── 2FA step ──
        elif s["step"] == "2fa":
            client = s["client"]
            try:
                await client.sign_in(password=text)
                me             = await client.get_me()
                session_string = client.session.save()
                await client.disconnect()

                s["session"] = session_string
                s["step"]    = "message"
                await event.respond(
                    f"✅ Logged in as *{me.first_name}*!\n\n"
                    f"Now send me the *message* you want to broadcast to all groups:"
                )
            except Exception as e:
                await event.respond(f"❌ Wrong password: {e}\n\nSend /start to try again.")
                try:
                    await client.disconnect()
                except Exception:
                    pass
                state.pop(uid, None)

        # ── Message step → broadcast ──
        elif s["step"] == "message":
            message        = text
            session_string = s["session"]
            s["step"]      = "idle"
            asyncio.create_task(do_broadcast(bot, uid, session_string, message))

    await bot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
