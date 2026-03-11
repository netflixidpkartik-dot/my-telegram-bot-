"""
Personal Storage Bot
Requirements: pip install telethon
"""

import asyncio
import json
import os
from datetime import datetime
from telethon import TelegramClient, events, Button

BOT_TOKEN   = "8794955820:AAG4ElkeHggu_9sthbZJQRR95Fthpdz4Tgc"
API_ID      = 2040
API_HASH    = "b18441a1ff607e10a989891a5462e627"
CONFIG_FILE = "storage_config.json"
MEDIA_DIR   = "saved_media"
os.makedirs(MEDIA_DIR, exist_ok=True)

CATEGORIES = {
    "bookmarks":   "🔖 Bookmarks",
    "links":       "🔗 Links",
    "proofs":      "📸 Proofs",
    "deal_proofs": "🤝 Deal Proofs",
    "services":    "🛠 Services",
    "shortcuts":   "⚡ Shortcuts",
    "methods":     "📋 Methods",
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {"owner_id": 0, "items": {k: [] for k in CATEGORIES}}

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

state = {}

def main_menu():
    return [
        [Button.inline("🔖 Bookmarks",   b"cat_bookmarks"),  Button.inline("🔗 Links",       b"cat_links")],
        [Button.inline("📸 Proofs",       b"cat_proofs"),     Button.inline("🤝 Deal Proofs", b"cat_deal_proofs")],
        [Button.inline("🛠 Services",     b"cat_services"),   Button.inline("⚡ Shortcuts",   b"cat_shortcuts")],
        [Button.inline("📋 Methods",      b"cat_methods")],
    ]

def add_see_buttons(cat):
    return [
        [Button.inline("➕ Add",  f"add_{cat}".encode()),  Button.inline("👁 See All", f"see_{cat}".encode())],
        [Button.inline("🗑 Delete Item", f"del_menu_{cat}".encode())],
        [Button.inline("⬅️ Back", b"home")],
    ]

async def run():
    bot = TelegramClient("storage_bot", API_ID, API_HASH)
    await bot.start(bot_token=BOT_TOKEN)
    print("✅ Storage Bot running!")

    async def send_home(uid, msg_to_edit=None):
        text = "📦 **Personal Storage**\n\nChoose a category:"
        try:
            if msg_to_edit:
                await msg_to_edit.edit(text, buttons=main_menu())
                return
        except Exception:
            pass
        await bot.send_message(uid, text, buttons=main_menu())

    # ── /start ──
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
        await send_home(uid)

    # ── CALLBACKS ──
    @bot.on(events.CallbackQuery())
    async def cb(event):
        uid  = event.sender_id
        data = event.data.decode()
        await event.answer()

        cfg = load_config()
        if uid != cfg["owner_id"]:
            return

        msg = await event.get_message()

        # Home
        if data == "home":
            await send_home(uid, msg_to_edit=msg)

        # Category selected — show Add/See
        elif data.startswith("cat_"):
            cat  = data.replace("cat_", "")
            name = CATEGORIES.get(cat, cat)
            cfg  = load_config()
            count = len(cfg["items"].get(cat, []))
            text = f"{name}\n\n📦 **{count} items** saved\n\nWhat do you want to do?"
            try:
                await msg.edit(text, buttons=add_see_buttons(cat))
            except Exception:
                await bot.send_message(uid, text, buttons=add_see_buttons(cat))

        # ADD
        elif data.startswith("add_"):
            cat = data.replace("add_", "")
            state[uid] = {"step": "wait_item", "cat": cat}
            await bot.send_message(
                uid,
                f"➕ **Adding to {CATEGORIES[cat]}**\n\n"
                "Send me anything — text, link, photo, file, or forward a message.\n"
                "You can send **multiple items one by one**.\n\n"
                "Send /done when finished."
            )

        # SEE ALL — send everything at once
        elif data.startswith("see_"):
            cat   = data.replace("see_", "")
            cfg   = load_config()
            items = cfg["items"].get(cat, [])

            if not items:
                await bot.send_message(uid, f"📭 Nothing in {CATEGORIES[cat]} yet.", buttons=[[Button.inline("⬅️ Back", f"cat_{cat}".encode())]])
                return

            await bot.send_message(uid, f"📂 **{CATEGORIES[cat]}** — sending {len(items)} items...")

            for i, item in enumerate(items, 1):
                try:
                    if item["type"] == "text":
                        await bot.send_message(uid, f"📝 **#{i}**\n\n{item['content']}")

                    elif item["type"] == "link":
                        await bot.send_message(uid, f"🔗 **#{i}**\n\n{item['content']}")

                    elif item["type"] == "photo":
                        path = item.get("path")
                        if path and os.path.exists(path):
                            cap = item.get("caption", "")
                            await bot.send_file(uid, path, caption=f"🖼 #{i}" + (f"\n{cap}" if cap else ""))
                        else:
                            await bot.send_message(uid, f"🖼 #{i} — Photo file missing")

                    elif item["type"] == "file":
                        path = item.get("path")
                        if path and os.path.exists(path):
                            cap = item.get("caption", "")
                            await bot.send_file(uid, path, caption=f"📎 #{i} {item.get('filename','')}" + (f"\n{cap}" if cap else ""))
                        else:
                            await bot.send_message(uid, f"📎 #{i} — File missing: {item.get('filename','')}")

                    elif item["type"] == "forward":
                        await bot.send_message(uid, f"🔁 **#{i} Forwarded**\n\n{item.get('caption','(no text)')}")

                    await asyncio.sleep(0.3)

                except Exception as e:
                    await bot.send_message(uid, f"❌ Item #{i} error: {e}")

            await bot.send_message(
                uid,
                f"✅ All {len(items)} items sent!",
                buttons=[[Button.inline("⬅️ Back", f"cat_{cat}".encode())]]
            )

        # DELETE MENU
        elif data.startswith("del_menu_"):
            cat   = data.replace("del_menu_", "")
            items = cfg["items"].get(cat, [])
            if not items:
                await bot.send_message(uid, "❌ Nothing to delete.")
                return
            buttons = []
            for i, item in enumerate(items):
                if item["type"] == "text":
                    label = item["content"][:35]
                elif item["type"] == "link":
                    label = item["content"][:35]
                elif item["type"] == "photo":
                    label = f"🖼 Photo {i+1}"
                elif item["type"] == "file":
                    label = f"📎 {item.get('filename', f'File {i+1}')[:35]}"
                else:
                    label = f"Item {i+1}"
                buttons.append([Button.inline(f"🗑 {label}", f"delitem_{cat}_{i}".encode())])
            buttons.append([Button.inline("⬅️ Back", f"cat_{cat}".encode())])
            await bot.send_message(uid, "🗑 **Select item to delete:**", buttons=buttons)

        elif data.startswith("delitem_"):
            _, cat, idx = data.split("_", 2)
            try:
                idx = int(idx)
                cfg["items"][cat].pop(idx)
                save_config(cfg)
                await bot.send_message(uid, "✅ Deleted!", buttons=[[Button.inline("⬅️ Back", f"cat_{cat}".encode())]])
            except Exception as e:
                await bot.send_message(uid, f"❌ Error: {e}")

    # ── TEXT & MEDIA HANDLER ──
    @bot.on(events.NewMessage())
    async def msg_handler(event):
        cfg = load_config()
        uid = event.sender_id

        if uid != cfg["owner_id"]:
            return

        text = (event.text or "").strip()

        # /done — finish adding
        if text == "/done":
            if uid in state:
                cat = state[uid].get("cat")
                del state[uid]
                cfg   = load_config()
                count = len(cfg["items"].get(cat, []))
                await event.respond(
                    f"✅ Done! **{CATEGORIES.get(cat, cat)}** now has **{count} items**.",
                    buttons=[[Button.inline("⬅️ Back to Menu", b"home")]]
                )
            return

        if text.startswith("/"):
            return

        if uid not in state or state[uid].get("step") != "wait_item":
            return

        cat = state[uid]["cat"]
        cfg = load_config()
        items = cfg["items"].setdefault(cat, [])
        ts    = datetime.now().strftime("%Y-%m-%d %H:%M")

        # Photo
        if event.photo:
            path = os.path.join(MEDIA_DIR, f"{uid}_{cat}_{len(items)}.jpg")
            await event.download_media(path)
            items.append({"type": "photo", "path": path, "caption": event.text or "", "date": ts})
            save_config(cfg)
            await event.respond("✅ Photo saved! Send more or /done")

        # File
        elif event.document:
            filename = event.file.name or f"file_{len(items)}"
            path = os.path.join(MEDIA_DIR, f"{uid}_{cat}_{len(items)}_{filename}")
            await event.download_media(path)
            items.append({"type": "file", "path": path, "filename": filename, "caption": event.text or "", "date": ts})
            save_config(cfg)
            await event.respond(f"✅ File **{filename}** saved! Send more or /done")

        # Forwarded
        elif event.forward:
            items.append({"type": "forward", "caption": event.text or "Forwarded message", "date": ts})
            save_config(cfg)
            await event.respond("✅ Forwarded message saved! Send more or /done")

        # Link
        elif text and ("http://" in text or "https://" in text or "t.me/" in text):
            items.append({"type": "link", "content": text, "date": ts})
            save_config(cfg)
            await event.respond("✅ Link saved! Send more or /done")

        # Text
        elif text:
            items.append({"type": "text", "content": text, "date": ts})
            save_config(cfg)
            await event.respond("✅ Note saved! Send more or /done")

        else:
            await event.respond("❌ Can't save this type. Try again or /done")

    await bot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(run())
