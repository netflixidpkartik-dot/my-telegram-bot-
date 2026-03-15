#!/usr/bin/env python3
import asyncio
import sqlite3
import random
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes,
)
from telegram.error import BadRequest

BOT_TOKEN = "8624189770:AAGvFomH-7Lvc-HCQCfSQ5U8Dsuy4fCTtUg"

WALLETS = {
    "usdt_bep20": ("💵 USDT BEP-20 (BSC)",      "0xcF0ABcDF3afccBE577d4D930e01af5c7F50f5aB7"),
    "usdt_eth":   ("🔷 USDT Ethereum (ERC-20)", "0xcF0ABcDF3afccBE577d4D930e01af5c7F50f5aB7"),
    "btc":        ("₿ Bitcoin (BTC)",           "bc1q0gtel9l8sczkrlv3ywdqkk9adln8f84zw0wczr"),
    "ltc":        ("🥈 Litecoin (LTC)",         "ltc1qj3f4rdevg738hrnf0xpdvlkc9k98u3ahkfykrj"),
    "ton":        ("💎 TON",                    "UQCAoTZkL0N_gxjDnV1-PC1rgqdPgfGDhtJs-YU2yHbkeZy-"),
    "usdt_sol":   ("🟣 USDT SPL (Solana)",      "CLiBT9JuTJCjpBkf4HXZMCimkzxJKX8PJxJtxHTd6iFe"),
    "bnb":        ("🟡 BNB Coin (BSC)",         "0xcF0ABcDF3afccBE577d4D930e01af5c7F50f5aB7"),
}

ADMIN_IDS = []

COUNTRIES = [
    ("🇺🇸", "United States"), ("🇬🇧", "United Kingdom"), ("🇨🇦", "Canada"),
    ("🇦🇺", "Australia"),     ("🇩🇪", "Germany"),        ("🇫🇷", "France"),
    ("🇳🇱", "Netherlands"),   ("🇸🇬", "Singapore"),      ("🇯🇵", "Japan"),
    ("🇦🇪", "UAE"),           ("🇨🇭", "Switzerland"),    ("🇸🇪", "Sweden"),
]

_fixed_cards = [
    {"brand": "VISA",       "variant": "CLASSIC",   "price": 25},
    {"brand": "VISA",       "variant": "GOLD",      "price": 50},
    {"brand": "VISA",       "variant": "PLATINUM",  "price": 100},
    {"brand": "VISA",       "variant": "INFINITE",  "price": 500},
    {"brand": "MASTERCARD", "variant": "STANDARD",  "price": 25},
    {"brand": "MASTERCARD", "variant": "GOLD",      "price": 50},
    {"brand": "MASTERCARD", "variant": "WORLD",     "price": 150},
    {"brand": "MASTERCARD", "variant": "BLACK",     "price": 200},
    {"brand": "MASTERCARD", "variant": "TITANIUM",  "price": 400},
    {"brand": "AMEX",       "variant": "GREEN",     "price": 40},
    {"brand": "AMEX",       "variant": "GOLD",      "price": 90},
    {"brand": "AMEX",       "variant": "PLATINUM",  "price": 300},
]

ALL_CARDS = []
for _i, _c in enumerate(_fixed_cards):
    _flag, _country = COUNTRIES[_i]
    _mult = random.randint(5, 7)
    ALL_CARDS.append({
        "id":      _i + 1,
        "brand":   _c["brand"],
        "variant": _c["variant"],
        "type":    f"{_c['brand']} {_c['variant']}",
        "num":     str(random.randint(1000, 9999)),
        "limit":   f"${_c['price'] * _mult:,}",
        "valid":   f"{str(random.randint(1,12)).zfill(2)}/{random.randint(2028,2032)}",
        "price":   _c["price"],
        "flag":    _flag,
        "country": _country,
    })

DB_FILE = "4xcards.db"

def init_db():
    con = sqlite3.connect(DB_FILE)
    con.execute("""CREATE TABLE IF NOT EXISTS users (
        tg_id INTEGER PRIMARY KEY, name TEXT, username TEXT, created_at TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS carts (
        tg_id INTEGER, card_id INTEGER, PRIMARY KEY (tg_id, card_id))""")
    con.execute("""CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tg_id INTEGER, order_ref TEXT, card_id INTEGER,
        card_type TEXT, card_num TEXT, card_limit TEXT, card_valid TEXT,
        price REAL, network TEXT, status TEXT DEFAULT 'pending', created_at TEXT)""")
    con.commit()
    con.close()

def _db():
    return sqlite3.connect(DB_FILE)

def ensure_user(tg_id, name, username=""):
    con = _db()
    con.execute("INSERT OR IGNORE INTO users VALUES (?,?,?,?)",
                (tg_id, name, username, datetime.now().isoformat()))
    con.commit(); con.close()

def get_cart(tg_id):
    con = _db()
    rows = con.execute("SELECT card_id FROM carts WHERE tg_id=?", (tg_id,)).fetchall()
    con.close()
    ids = {r[0] for r in rows}
    return [c for c in ALL_CARDS if c["id"] in ids]

def add_to_cart(tg_id, card_id):
    con = _db()
    con.execute("INSERT OR IGNORE INTO carts VALUES (?,?)", (tg_id, card_id))
    con.commit(); con.close()

def remove_from_cart(tg_id, card_id):
    con = _db()
    con.execute("DELETE FROM carts WHERE tg_id=? AND card_id=?", (tg_id, card_id))
    con.commit(); con.close()

def clear_cart(tg_id):
    con = _db()
    con.execute("DELETE FROM carts WHERE tg_id=?", (tg_id,))
    con.commit(); con.close()

def save_orders(tg_id, cart_items, network_name, order_ref):
    con = _db()
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    for c in cart_items:
        con.execute("""INSERT INTO orders
            (tg_id,order_ref,card_id,card_type,card_num,card_limit,card_valid,price,network,status,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,'pending',?)""",
            (tg_id, order_ref, c["id"], c["type"], c["num"],
             c["limit"], c["valid"], c["price"], network_name, now))
    con.commit(); con.close()

def get_orders(tg_id):
    con = _db()
    rows = con.execute(
        "SELECT order_ref,card_type,card_num,card_limit,card_valid,price,network,status,created_at "
        "FROM orders WHERE tg_id=? ORDER BY id DESC", (tg_id,)).fetchall()
    con.close()
    return rows

def get_stats():
    con = _db()
    u = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    o = con.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    r = con.execute("SELECT COALESCE(SUM(price),0) FROM orders").fetchone()[0]
    con.close()
    return u, o, r

def get_all_orders_admin():
    con = _db()
    rows = con.execute("""
        SELECT o.order_ref,o.card_type,o.price,o.network,o.status,o.created_at,u.name,u.username
        FROM orders o LEFT JOIN users u ON o.tg_id=u.tg_id
        ORDER BY o.id DESC LIMIT 50""").fetchall()
    con.close()
    return rows

# ── Keyboards ─────────────────────────────────────────

def kb_main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🃏 Browse Cards", callback_data="browse_all"),
         InlineKeyboardButton("🛒 My Cart",      callback_data="cart")],
        [InlineKeyboardButton("📦 My Orders",    callback_data="orders"),
         InlineKeyboardButton("ℹ️ About",         callback_data="about")],
    ])

def kb_brand_filter():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 ALL",        callback_data="filter_all"),
         InlineKeyboardButton("💳 VISA",       callback_data="filter_visa"),
         InlineKeyboardButton("🔴 MASTERCARD", callback_data="filter_mastercard")],
        [InlineKeyboardButton("💚 AMEX",       callback_data="filter_amex")],
        [InlineKeyboardButton("🏠 Main Menu",  callback_data="main_menu")],
    ])

def kb_cards(cards, brand="all"):
    rows = []
    for c in cards:
        rows.append([InlineKeyboardButton(
            f"{c['flag']} {c['type']}  —  ${c['price']:.2f} USDT",
            callback_data=f"card_{c['id']}")])
    rows.append([InlineKeyboardButton("🔍 Filter Brand", callback_data="brand_filter"),
                 InlineKeyboardButton("🏠 Menu",          callback_data="main_menu")])
    return InlineKeyboardMarkup(rows)

def kb_card_detail(card_id, in_cart):
    label = "✅ Already in Cart" if in_cart else "🛒 Add to Cart"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(label,              callback_data=f"addcart_{card_id}"),
         InlineKeyboardButton("⚡ Buy Now",       callback_data=f"buynow_{card_id}")],
        [InlineKeyboardButton("⬅️ Back to Cards", callback_data="browse_all"),
         InlineKeyboardButton("🏠 Menu",          callback_data="main_menu")],
    ])

def kb_cart(cart_items):
    rows = []
    for c in cart_items:
        rows.append([InlineKeyboardButton(
            f"❌ Remove  {c['type']}  (${c['price']:.2f})",
            callback_data=f"rmcart_{c['id']}")])
    rows.append([InlineKeyboardButton("🔐 Proceed to Checkout", callback_data="checkout")])
    rows.append([InlineKeyboardButton("🃏 Browse More", callback_data="browse_all"),
                 InlineKeyboardButton("🏠 Menu",        callback_data="main_menu")])
    return InlineKeyboardMarkup(rows)

def kb_empty_cart():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🃏 Browse Cards", callback_data="browse_all")],
        [InlineKeyboardButton("🏠 Main Menu",    callback_data="main_menu")],
    ])

def kb_crypto():
    rows = [[InlineKeyboardButton(name, callback_data=f"pay_{key}")]
            for key, (name, _) in WALLETS.items()]
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data="cart")])
    return InlineKeyboardMarkup(rows)

def kb_payment_confirm(network_key):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ I Have Sent the Payment", callback_data=f"confirm_{network_key}")],
        [InlineKeyboardButton("⬅️ Change Network",          callback_data="checkout")],
    ])

def kb_post_order():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 My Orders",        callback_data="orders")],
        [InlineKeyboardButton("🃏 Continue Shopping", callback_data="browse_all")],
    ])

def kb_back_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
    ])

# ── Text builders ──────────────────────────────────────

HTML = "HTML"

def txt_welcome(name):
    return (
        f"🏦 <b>Welcome to 4xCardsShop, {name}!</b>\n\n"
        "🌟 <i>Institutional Grade Virtual Cards</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "💳 VISA  •  Mastercard  •  AMEX\n"
        "₿  Crypto payments  •  ⚡ Instant delivery\n"
        "🌍 180+ countries  •  🔒 256-bit SSL\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "What would you like to do?"
    )

def txt_card(c):
    return (
        f"💳 <b>{c['type']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔢 Card No:  <code>•••• {c['num']}</code>\n"
        f"💰 Price:    <b>${c['price']:.2f} USDT</b>\n"
        f"📊 Limit:    <code>{c['limit']}</code>\n"
        f"📅 Valid:    <code>{c['valid']}</code>\n"
        f"🌍 Country:  {c['flag']} {c['country']}\n"
        f"✅ Status:   IN STOCK\n"
        f"🏷️ Brand:    {c['brand']}"
    )

def txt_cart(cart_items):
    lines = "\n".join(
        f"• {c['flag']} {c['type']} ••••{c['num']} — <b>${c['price']:.2f}</b>"
        for c in cart_items
    )
    total = sum(c["price"] for c in cart_items)
    return (
        f"🛒 <b>Your Cart</b>\n\n"
        f"{lines}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Total: <b>${total:.2f} USDT</b>"
    )

def txt_checkout(cart_items):
    total = sum(c["price"] for c in cart_items)
    return (
        f"🔐 <b>Select Payment Network</b>\n\n"
        f"💰 Amount Due: <b>${total:.2f} USDT</b>\n\n"
        "Choose your cryptocurrency network:"
    )

def txt_payment(name, addr, total):
    return (
        f"💳 <b>Payment Details</b>\n\n"
        f"Network: <b>{name}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Amount Due: <code>${total:.2f} USDT</code>\n\n"
        f"📬 <b>Send Exact Amount To:</b>\n"
        f"<code>{addr}</code>\n\n"
        f"⚠️ <i>Send exact amount shown. Include network fees separately.\n"
        f"Do not send from exchange wallets directly.</i>"
    )

def txt_success(order_ref):
    return (
        f"🎉 <b>Thank You for Your Purchase!</b>\n\n"
        f"Your payment has been received and is awaiting verification.\n\n"
        f"📋 Order Reference: <code>{order_ref}</code>\n\n"
        f"⏳ <i>Payment verification takes 10-30 minutes.\n"
        f"Your card will appear in My Orders once confirmed.</i>\n\n"
        f"💛 Thanks for shopping with <b>4xCardsShop</b>!"
    )

def txt_orders(orders):
    if not orders:
        return (
            "📦 <b>My Orders</b>\n\n"
            "You haven't placed any orders yet.\n\n"
            "<i>Browse cards and make your first purchase!</i>"
        )
    lines = []
    for o in orders[:15]:
        ref, ctype, cnum, climit, cvalid, price, network, status, created = o
        icon  = "⏳" if status == "pending" else "✅"
        st_up = status.upper()
        lines.append(
            f"{icon} <code>{ref}</code>\n"
            f"   💳 {ctype} ••••{cnum}\n"
            f"   💰 ${price:.2f} | 📅 {created[:10]} | {st_up}"
        )
    return "📦 <b>My Orders</b>\n\n" + "\n\n".join(lines)

# ── Logging ───────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# ── Safe answer helper ────────────────────────────────

async def safe_answer(q, text="", alert=False):
    """answer() ko try-except mein wrap karo — stale query crash nahi karegi."""
    try:
        await q.answer(text, show_alert=alert)
    except BadRequest:
        pass  # Query expired — ignore karo

# ── Handlers ──────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id, user.first_name, user.username or "")
    await update.message.reply_text(
        txt_welcome(user.first_name), parse_mode=HTML, reply_markup=kb_main_menu())

async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id, user.first_name, user.username or "")
    await update.message.reply_text(
        "🏠 <b>Main Menu</b>\n\nWhat would you like to do?",
        parse_mode=HTML, reply_markup=kb_main_menu())

async def cmd_cart(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user  = update.effective_user
    cart_ = get_cart(user.id)
    if not cart_:
        await update.message.reply_text(
            "🛒 <b>Your Cart is Empty</b>\n\nBrowse cards and add them here!",
            parse_mode=HTML, reply_markup=kb_empty_cart())
    else:
        await update.message.reply_text(
            txt_cart(cart_), parse_mode=HTML, reply_markup=kb_cart(cart_))

async def cmd_orders(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    orders = get_orders(update.effective_user.id)
    await update.message.reply_text(
        txt_orders(orders), parse_mode=HTML, reply_markup=kb_back_main())

async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if ADMIN_IDS and user.id not in ADMIN_IDS:
        await update.message.reply_text("Unauthorised.")
        return
    u_cnt, o_cnt, rev = get_stats()
    recent = get_all_orders_admin()
    lines = [
        "<b>Admin Panel</b>\n",
        f"👥 Users: {u_cnt}",
        f"🧾 Orders: {o_cnt}",
        f"💰 Revenue: ${rev:.2f} USDT\n",
        "<b>Recent 10 Orders:</b>",
    ]
    for o in recent[:10]:
        ref, ctype, price, network, status, created, name, uname = o
        lines.append(f"• <code>{ref}</code> {ctype} — ${price:.2f} | {name} | {status}")
    await update.message.reply_text("\n".join(lines), parse_mode=HTML)


async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    data = q.data
    user = update.effective_user
    ensure_user(user.id, user.first_name, user.username or "")

    # ✅ KEY FIX: stale query crash nahi karegi
    await safe_answer(q)

    if data == "main_menu":
        await q.edit_message_text(
            "🏠 <b>Main Menu</b>\n\nWhat would you like to do?",
            parse_mode=HTML, reply_markup=kb_main_menu())

    elif data == "about":
        await q.edit_message_text(
            "ℹ️ <b>About 4xCardsShop</b>\n\n"
            "💳 Premium virtual card marketplace\n"
            "👥 50,000+ satisfied cardholders\n"
            "🔒 256-bit SSL Encrypted\n"
            "⚡ Instant delivery\n"
            "₿  6 Crypto payment networks\n"
            "🌍 180+ countries served\n"
            "📊 99.98% uptime SLA\n\n"
            "📞 Support: @4xCardSupport\n\n"
            "<i>© 2025 4xCardsShop</i>",
            parse_mode=HTML, reply_markup=kb_back_main())

    elif data == "browse_all" or data.startswith("filter_"):
        brand    = "all" if data == "browse_all" else data[7:]
        filtered = ALL_CARDS if brand == "all" else [c for c in ALL_CARDS if c["brand"].lower() == brand]
        label    = "All Cards" if brand == "all" else brand.upper()
        await q.edit_message_text(
            f"🃏 <b>Card Catalog — {label}</b>\n"
            f"<i>{len(filtered)} cards available</i>\n\n"
            "Tap a card to view details:",
            parse_mode=HTML, reply_markup=kb_cards(filtered, brand=brand))

    elif data == "brand_filter":
        await q.edit_message_text(
            "🔍 <b>Filter by Brand</b>\n\nChoose a card network:",
            parse_mode=HTML, reply_markup=kb_brand_filter())

    elif data.startswith("card_"):
        card_id = int(data[5:])
        card    = next((c for c in ALL_CARDS if c["id"] == card_id), None)
        if not card:
            await safe_answer(q, "Card not found.", alert=True)
            return
        in_cart = any(c["id"] == card_id for c in get_cart(user.id))
        await q.edit_message_text(
            txt_card(card), parse_mode=HTML,
            reply_markup=kb_card_detail(card_id, in_cart))

    elif data.startswith("addcart_"):
        card_id = int(data[8:])
        if any(c["id"] == card_id for c in get_cart(user.id)):
            await safe_answer(q, "Already in your cart!", alert=True)
        else:
            add_to_cart(user.id, card_id)
            await safe_answer(q, "Added to cart!", alert=True)
            await q.edit_message_reply_markup(reply_markup=kb_card_detail(card_id, True))

    elif data.startswith("buynow_"):
        card_id = int(data[7:])
        if not any(c["id"] == card_id for c in get_cart(user.id)):
            add_to_cart(user.id, card_id)
        await _show_checkout(q, user.id)

    elif data == "cart":
        cart_items = get_cart(user.id)
        if not cart_items:
            await q.edit_message_text(
                "🛒 <b>Your Cart is Empty</b>\n\nBrowse cards and add them here!",
                parse_mode=HTML, reply_markup=kb_empty_cart())
        else:
            await q.edit_message_text(
                txt_cart(cart_items), parse_mode=HTML, reply_markup=kb_cart(cart_items))

    elif data.startswith("rmcart_"):
        card_id = int(data[7:])
        remove_from_cart(user.id, card_id)
        cart_items = get_cart(user.id)
        if not cart_items:
            await q.edit_message_text(
                "🛒 <b>Your Cart is Empty</b>",
                parse_mode=HTML, reply_markup=kb_empty_cart())
        else:
            await q.edit_message_text(
                txt_cart(cart_items), parse_mode=HTML, reply_markup=kb_cart(cart_items))

    elif data == "checkout":
        await _show_checkout(q, user.id)

    elif data.startswith("pay_"):
        network_key = data[4:]
        if network_key not in WALLETS:
            await safe_answer(q, "Invalid network.", alert=True)
            return
        name, addr = WALLETS[network_key]
        cart_items  = get_cart(user.id)
        if not cart_items:
            await safe_answer(q, "Cart is empty!", alert=True)
            return
        total = sum(c["price"] for c in cart_items)
        await q.edit_message_text(
            txt_payment(name, addr, total), parse_mode=HTML,
            reply_markup=kb_payment_confirm(network_key))

    elif data.startswith("confirm_"):
        network_key = data[8:]
        cart_items  = get_cart(user.id)
        if not cart_items:
            await safe_answer(q, "Cart is empty!", alert=True)
            return
        name, _   = WALLETS.get(network_key, ("Unknown", ""))
        order_ref = f"#4X{random.randint(10000, 99999)}"
        save_orders(user.id, cart_items, name, order_ref)
        clear_cart(user.id)
        await q.edit_message_text(
            txt_success(order_ref), parse_mode=HTML, reply_markup=kb_post_order())

    elif data == "orders":
        orders = get_orders(user.id)
        await q.edit_message_text(
            txt_orders(orders), parse_mode=HTML, reply_markup=kb_back_main())


async def _show_checkout(q, user_id):
    cart_items = get_cart(user_id)
    if not cart_items:
        await q.edit_message_text(
            "🛒 <b>Your Cart is Empty!</b>\n\nAdd some cards first.",
            parse_mode=HTML, reply_markup=kb_empty_cart())
        return
    await q.edit_message_text(
        txt_checkout(cart_items), parse_mode=HTML, reply_markup=kb_crypto())

# ── Main ──────────────────────────────────────────────

async def run_cc():
    init_db()
    logger.info("4xCardsShop: Database initialized")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("menu",   cmd_menu))
    app.add_handler(CommandHandler("cart",   cmd_cart))
    app.add_handler(CommandHandler("orders", cmd_orders))
    app.add_handler(CommandHandler("admin",  cmd_admin))
    app.add_handler(CallbackQueryHandler(on_callback))
    await app.initialize()
    await app.start()
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    print("cc.py (4xCardsShop) chal raha hai...")
    try:
        await asyncio.Event().wait()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

if __name__ == "__main__":
    asyncio.run(run_cc())
