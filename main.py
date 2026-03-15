import asyncio

from tgadbot import run_bot      # Telethon adbot
from cc import run_cc            # 4xCardsShop bot


async def main():
    print("Dono bots start ho rahe hain...")
    await asyncio.gather(
        run_bot(),   # tgadbot.py
        run_cc(),    # cc.py
    )


if __name__ == "__main__":
    asyncio.run(main())
