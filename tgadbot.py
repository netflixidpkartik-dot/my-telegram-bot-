"""
Simple Telegram Group Broadcaster
- Auto login (handles OTP + 2FA automatically via terminal)
- Sends your message to all groups
- No bot needed — just run and go
"""

import asyncio
from telethon import TelegramClient
from telethon.tl.types import Channel, Chat

# ── YOUR CREDENTIALS (from my.telegram.org) ──
API_ID   = 37827563
API_HASH = "abca86f59db00e94244dd14df8259ff0"
PHONE    = "+91XXXXXXXXXX"   # your phone number

# ── YOUR MESSAGE ──
MESSAGE  = "Hello! This is my message."

# ── SETTINGS ──
DELAY_BETWEEN_GROUPS = 10   # seconds between each send (avoid flood ban)
SESSION_FILE         = "my_session"  # saved after first login, reused next time


async def get_groups(client):
    groups = []
    async for dialog in client.iter_dialogs():
        e = dialog.entity
        if isinstance(e, Chat):
            groups.append(dialog)
        elif isinstance(e, Channel) and e.megagroup:
            groups.append(dialog)
    return groups


async def main():
    # Telethon auto-prompts for OTP and 2FA in terminal — nothing to handle manually
    client = TelegramClient(SESSION_FILE, API_ID, API_HASH)
    await client.start(phone=PHONE)

    me = await client.get_me()
    print(f"\n✅ Logged in as: {me.first_name} (@{me.username})\n")

    groups = await get_groups(client)
    print(f"📋 Found {len(groups)} groups\n")

    for i, dialog in enumerate(groups, 1):
        try:
            await client.send_message(dialog.entity, MESSAGE)
            print(f"[{i}/{len(groups)}] ✅ Sent → {dialog.name}")
        except Exception as e:
            print(f"[{i}/{len(groups)}] ❌ Failed → {dialog.name}: {e}")
        await asyncio.sleep(DELAY_BETWEEN_GROUPS)

    print("\n🎉 Done!")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
