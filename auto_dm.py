import asyncio
import json
from telethon import TelegramClient, events

API_ID = 34564865
API_HASH = "07b94d63a077ddd7a222d64d8362c7b0"
BOT_TOKEN = "8689956318:AAH_B5bKWXQrBd-k462kL4qXYOBmRhfkZF8"

ACCOUNTS_FILE = "accounts.json"
CONFIG_FILE = "config.json"

clients = {}
replied = {}
state = {}


def load_accounts():
    with open(ACCOUNTS_FILE) as f:
        return json.load(f)["accounts"]


def load_cfg():
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except:
        return {"auto_dm": ""}


def save_cfg(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)


async def start_account(label, session):

    client = TelegramClient(session, API_ID, API_HASH)
    await client.start()

    clients[label] = client
    replied[label] = set()

    print("DM listener running:", label)

    @client.on(events.NewMessage(incoming=True))
    async def handler(event):

        cfg = load_cfg()
        auto_msg = cfg["auto_dm"]

        if not auto_msg:
            return

        if not event.is_private or event.out:
            return

        uid = event.sender_id

        if uid in replied[label]:
            return

        try:
            await event.reply(auto_msg)
            replied[label].add(uid)
        except:
            pass


async def start_accounts():

    accounts = load_accounts()

    for label, acc in accounts.items():

        if label not in clients:

            asyncio.create_task(
                start_account(label, acc["session"])
            )


async def run_bot():

    bot = TelegramClient("dm_control", API_ID, API_HASH)

    await bot.start(bot_token=BOT_TOKEN)

    await start_accounts()

    print("Control bot running")

    @bot.on(events.NewMessage(pattern="/start"))
    async def start(event):

        txt = """
DM Control Panel

/setdm  → set auto DM message
/accounts → show connected accounts
"""

        await event.respond(txt)

    @bot.on(events.NewMessage(pattern="/setdm"))
    async def setdm(event):

        state[event.sender_id] = "setdm"

        await event.respond("Send new auto DM message")

    @bot.on(events.NewMessage)
    async def handler(event):

        uid = event.sender_id

        if uid not in state:
            return

        if state[uid] == "setdm":

            cfg = load_cfg()

            cfg["auto_dm"] = event.text

            save_cfg(cfg)

            del state[uid]

            await event.respond("Auto DM updated")

    @bot.on(events.NewMessage(pattern="/accounts"))
    async def accs(event):

        txt = "Connected Accounts\n\n"

        for label in clients:
            txt += f"• {label}\n"

        await event.respond(txt)

    await bot.run_until_disconnected()


asyncio.run(run_bot())
