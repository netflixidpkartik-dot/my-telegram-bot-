import asyncio

from tgadbot import run_bot
from cc import run_cc


async def run_safe(name, fn):
    """Ek bot crash ho toh 30 sec baad restart karo, dusre pe asar nahi."""
    while True:
        try:
            print(f"[{name}] Starting...")
            await fn()
        except Exception as e:
            print(f"[{name}] Crashed: {e}")
            print(f"[{name}] 30 sec mein restart hoga...")
            await asyncio.sleep(30)


async def main():
    print("Dono bots start ho rahe hain...")
    await asyncio.gather(
        run_safe("tgadbot", run_bot),
        run_safe("cc",      run_cc),
    )


if __name__ == "__main__":
    asyncio.run(main())
