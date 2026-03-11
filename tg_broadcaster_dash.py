#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════╗
║         4xCardsShop — Telegram Bot               ║
║  Exact replica of 4xCardsShop website            ║
║                                                  ║
║  Install:  pip install python-telegram-bot       ║
║  Run:      python 4xcards_bot.py                 ║
╚══════════════════════════════════════════════════╝
"""

import sqlite3
import random
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ══════════════════════════════════════════════════════
#  ⚙️  CONFIG — apna token aur wallet addresses yahan daalein
# ══════════════════════════════════════════════════════

BOT_TOKEN = "8624189770:AAGvFomH-7Lvc-HCQCfSQ5U8Dsuy4fCTtUg"        # @BotFather se milta hai

# Crypto wallet addresses — apne daalein
WALLETS = {
    "usdt_bep20": ("💵 USDT BEP-20 (BSC)",   "YOUR_BSC_USDT_WALLET_ADDRESS"),
    "usdt_trc20": ("🟢 USDT TRC-20 (TRON)",  "YOUR_TRC20_USDT_WALLET_ADDRESS"),
    "trx":        ("🔴 TRON (TRX)",           "YOUR_TRX_WALLET_ADDRESS"),
    "btc":        ("₿  Bitcoin (BTC)",        "YOUR_BTC_WALLET_ADDRESS"),
    "ltc":        ("🥈 Litecoin (LTC)",       "YOUR_LTC_WALLET_ADDRESS"),
    "ton":        ("💎 TON",                  "YOUR_TON_WALLET_ADDRESS"),
}

ADMIN_IDS = []   # Optional: apna Telegram user ID daalein admin features ke liye, e.g. [123456789]

# ══════════════════════════════════════════════════════
#  🃏  CARD DATA (same as website)
# ══════════════════════════════════════════════════════

BRANDS = [
    {"brand": "VISA",       "logo": "V",  "variants": ["CLASSIC","GOLD","PLATINUM","INFINITE","SIGNATURE"]},
    {"brand": "MASTERCARD", "logo": "M",  "variants": ["STANDARD","GOLD","WORLD","BLACK","TITANIUM"]},
    {"brand": "AMEX",       "logo": "A",  "variants": ["GREEN","GOLD","PLATINUM","CENTURION","BLUE CASH"]},
    {"brand": "DISCOVER",   "logo": "D",  "variants": ["IT","CASHBACK PLUS","STUDENT","SECURED","MILES"]},
    {"brand": "UNIONPAY",   "logo": "U",  "variants": ["CLASSIC","DIAMOND","PLATINUM","WORLD"]},
    {"brand": "JCB",        "logo": "J",  "variants": ["CLASSIC","GOLD","PLATINUM","ULTRA"]},
    {"brand": "MAESTRO",    "logo": "MA", "variants": ["STANDARD","GOLD"]},
]

PRICE_TIERS = [
    10,12,14,16,18,20,22,25,28,30,33,35,38,40,45,
    48,50,55,60,65,70,75,80,85,90,100,110,120,130,
    150,170,200,250,300,350,400,500,600,700,800,900,1000,1100
]

def _gen_cards():
    cards = []
    cid = 1
    for b in BRANDS:
        for v in b["variants"]:
            price = random.choice(PRICE_TIERS)
            mult  = random.randint(5, 7)
            cards.append({
                "id":      cid,
                "brand":   b["brand"],
                "variant": v,
                "type":    f"{b['brand']} {v}",
                "logo":    b["logo"],
                "num":     str(random.randint(1000, 9999)),
                "limit":   f"${price * mult:,}",
                "valid":   f"{str(random.randint(1,12)).zfill(2)}/{random.randint(2028,2032)}",
                "price":   price,
            })
            cid += 1
    # pad to 35+
    while len(cards) < 35:
        b     = random.choice(BRANDS)
        v     = random.choice(b["variants"])
        price = random.choice(PRICE_TIERS)
        mult  = random.randint(5, 7)
        cards.append({
            "id":      cid,
            "brand":   b["brand"],
            "variant": v,
            "type":    f"{b['brand']} {v}",
            "logo":    b["logo"],
            "num":     str(random.randint(1000, 9999)),
            "limit":   f"${price * mult:,}",
            "valid":   f"{str(random.randint(1,12)).zfill(2)}/{random.randint(2028,2032)}",
            "price":   price,
        })
        cid += 1
    random.shuffle(cards)
    return cards

ALL_CARDS = _gen_cards()

# ══════════════════════════════════════════════════════
#  🗄️  DATABASE (SQLite)
# ══════════════════════════════════════════════════════

DB_FILE = "4xcards.db"

def init_db():
    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            tg_id      INTEGER PRIMARY KEY,
            name       TEXT,
            username   TEXT,
            created_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS carts (
            tg_id   INTEGER,
            card_id INTEGER,
            PRIMARY KEY (tg_id, card_id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id      INTEGER,
            order_ref  TEXT,
            card_id    INTEGER,
            card_type  TEXT,
            card_num   TEXT,
            card_limit TEXT,
            card_valid TEXT,
            price      REAL,
            network    TEXT,
            status     TEXT DEFAULT 'pending',
            created_at TEXT
        )
    """)
    con.commit()
    con.close()

def _db():
    return sqlite3.connect(DB_FILE)

def ensure_user(tg_id: int, name: str, username: str = ""):
    con = _db()
    con.execute(
        "INSERT OR IGNORE INTO users (tg_id, name, username, created_at) VALUES (?,?,?,?)",
        (tg_id, name, username or "", datetime.now().isoformat())
    )
    con.commit()
    con.close()

def get_cart(tg_id: int):
    con = _db()
    rows = con.execute("SELECT card_id FROM carts WHERE tg_id=?", (tg_id,)).fetchall()
    con.close()
    ids = {r[0] for r in rows}
    return [c for c in ALL_CARDS if c["id"] in ids]

def add_to_cart(tg_id: int, card_id: int):
    con = _db()
    con.execute("INSERT OR IGNORE INTO carts (tg_id, card_id) VALUES (?,?)", (tg_id, card_id))
    con.commit()
    con.close()

def remove_from_cart(tg_id: int, card_id: int):
    con = _db()
    con.execute("DELETE FROM carts WHERE tg_id=? AND card_id=?", (tg_id, card_id))
    con.commit()
    con.close()

def clear_cart(tg_id: int):
    con = _db()
    con.execute("DELETE FROM carts WHERE tg_id=?", (tg_id,))
    con.commit()
    con.close()

def save_orders(tg_id: int, cart_items: list, network_name: str, order_ref: str):
    con = _db()
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    for c in cart_items:
        con.execute("""
            INSERT INTO orders
                (tg_id, order_ref, card_id, card_type, card_num, card_limit, card_valid, price, network, status, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,'pending',?)
        """, (tg_id, order_ref, c["id"], c["type"], c["num"], c["limit"], c["valid"], c["price"], network_name, now))
    con.commit()
    con.close()

def get_orders(tg_id: int):
    con = _db()
    rows = con.execute(
        "SELECT order_ref, card_type, card_num, card_limit, card_valid, price, network, status, created_at "
        "FROM orders WHERE tg_id=? ORDER BY id DESC",
        (tg_id,)
    ).fetchall()
    con.close()
    return rows

def get_all_orders_admin():
    """Admin: fetch all orders with user info"""
    con = _db()
    rows = con.execute("""
        SELECT o.order_ref, o.card_type, o.price, o.network, o.status, o.created_at, u.name, u.username
        FROM orders o
        LEFT JOIN users u ON o.tg_id = u.tg_id
        ORDER BY o.id DESC LIMIT 50
    """).fetchall()
    con.close()
    return rows

def get_stats():
    con = _db()
    users  = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    orders = con.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    revenue= con.execute("SELECT COALESCE(SUM(price),0) FROM orders WHERE status='pending'").fetchone()[0]
    con.close()
    return users, orders, revenue

# ══════════════════════════════════════════════════════
#  🎨  KEYBOARDS
# ══════════════════════════════════════════════════════

def kb_main_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🃏  Browse Cards",  callback_data="browse_all"),
            InlineKeyboardButton("🛒  My Cart",       callback_data="cart"),
        ],
        [
            InlineKeyboardButton("📦  My Orders",     callback_data="orders"),
            InlineKeyboardButton("ℹ️  About",          callback_data="about"),
        ],
    ])

def kb_brand_filter():
    brands = ["ALL","VISA","MASTERCARD","AMEX","DISCOVER","UNIONPAY","JCB","MAESTRO"]
    rows, row = [], []
    for i, b in enumerate(brands):
        row.append(InlineKeyboardButton(b, callback_data=f"filter_{b.lower()}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")])
    return InlineKeyboardMarkup(rows)

def kb_cards(cards: list, page: int = 0, brand: str = "all", per_page: int = 8):
    start    = page * per_page
    end      = min(start + per_page, len(cards))
    slice_   = cards[start:end]

    rows = []
    for c in slice_:
        rows.append([InlineKeyboardButton(
            f"💳  {c['type']}  —  ${c['price']:.2f} USDT",
            callback_data=f"card_{c['id']}"
        )])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"page_{brand}_{page-1}"))
    if end < len(cards):
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"page_{brand}_{page+1}"))
    if nav:
        rows.append(nav)

    rows.append([
        InlineKeyboardButton("🔍 Filter Brand", callback_data="brand_filter"),
        InlineKeyboardButton("🏠 Menu",         callback_data="main_menu"),
    ])
    return InlineKeyboardMarkup(rows)

def kb_card_detail(card_id: int, in_cart: bool):
    cart_label = "✅  Already in Cart" if in_cart else "🛒  Add to Cart"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(cart_label,       callback_data=f"addcart_{card_id}"),
            InlineKeyboardButton("⚡  Buy Now",    callback_data=f"buynow_{card_id}"),
        ],
        [
            InlineKeyboardButton("⬅️ Back to Cards", callback_data="browse_all"),
            InlineKeyboardButton("🏠 Menu",           callback_data="main_menu"),
        ],
    ])

def kb_cart(cart_items: list):
    rows = []
    for c in cart_items:
        rows.append([InlineKeyboardButton(
            f"❌  Remove  {c['type']}  (${c['price']:.2f})",
            callback_data=f"rmcart_{c['id']}"
        )])
    rows.append([InlineKeyboardButton("🔐  Proceed to Checkout", callback_data="checkout")])
    rows.append([
        InlineKeyboardButton("🃏 Browse More", callback_data="browse_all"),
        InlineKeyboardButton("🏠 Menu",        callback_data="main_menu"),
    ])
    return InlineKeyboardMarkup(rows)

def kb_empty_cart():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🃏  Browse Cards", callback_data="browse_all")],
        [InlineKeyboardButton("🏠  Main Menu",    callback_data="main_menu")],
    ])

def kb_crypto():
    rows = []
    for key, (name, _) in WALLETS.items():
        rows.append([InlineKeyboardButton(name, callback_data=f"pay_{key}")])
    rows.append([InlineKeyboardButton("❌  Cancel / Back to Cart", callback_data="cart")])
    return InlineKeyboardMarkup(rows)

def kb_payment_confirm(network_key: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅  I Have Sent the Payment", callback_data=f"confirm_{network_key}")],
        [InlineKeyboardButton("⬅️  Change Network",          callback_data="checkout")],
    ])

def kb_post_order():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦  My Orders",       callback_data="orders")],
        [InlineKeyboardButton("🃏  Continue Shopping", callback_data="browse_all")],
    ])

def kb_orders():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠  Main Menu", callback_data="main_menu")]
    ])

def kb_back_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠  Main Menu", callback_data="main_menu")]
    ])

# ══════════════════════════════════════════════════════
#  📝  MESSAGE TEXTS
# ══════════════════════════════════════════════════════

def txt_welcome(name: str) -> str:
    return (
        f"🏦 *Welcome to 4xCardsShop, {name}\\!*\n\n"
        "🌟 _Institutional Grade Virtual Cards_\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "💳 VISA • Mastercard • AMEX • Discover\n"
        "₿  Crypto payments • ⚡ Instant delivery\n"
        "🌍 180\\+ countries • 🔒 256\\-bit SSL\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "What would you like to do?"
    )

def txt_card(c: dict) -> str:
    return (
        f"💳 *{c['type']}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔢 Card No\\: `•••• {c['num']}`\n"
        f"💰 Price\\:  *${c['price']:.2f} USDT*\n"
        f"📊 Limit\\:  `{c['limit']}`\n"
        f"📅 Valid\\:  `{c['valid']}`\n"
        f"✅ Status\\: IN STOCK\n"
        f"🏷️ Brand\\:  {c['brand']}"
    )

def txt_cart(cart_items: list) -> str:
    lines = "\n".join(
        f"• {c['type']} ••••{c['num']} — *${c['price']:.2f}*"
        for c in cart_items
    )
    total = sum(c["price"] for c in cart_items)
    return (
        f"🛒 *Your Cart*\n\n"
        f"{lines}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Total\\: *${total:.2f} USDT*"
    )

def txt_checkout(cart_items: list) -> str:
    total = sum(c["price"] for c in cart_items)
    return (
        f"🔐 *Select Payment Network*\n\n"
        f"💰 Amount Due\\: *${total:.2f} USDT*\n\n"
        "Choose your cryptocurrency network:"
    )

def txt_payment(name: str, addr: str, total: float) -> str:
    safe_addr = addr.replace("-", "\\-").replace(".", "\\.").replace("_", "\\_")
    return (
        f"💳 *Payment Details*\n\n"
        f"Network\\: *{name}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Amount Due\\: `${total:.2f} USDT`\n\n"
        f"📬 *Send Exact Amount To\\:*\n"
        f"`{safe_addr}`\n\n"
        f"⚠️ _Send exact amount shown\\. Include network fees separately\\._\n"
        f"_Do not send from exchange wallets directly\\._"
    )

def txt_success(order_ref: str) -> str:
    safe_ref = order_ref.replace("#", "\\#")
    return (
        f"🎉 *Thank You for Your Purchase\\!*\n\n"
        f"Your payment has been received and is awaiting verification\\.\n\n"
        f"📋 Order Reference\\: `{safe_ref}`\n\n"
        f"⏳ _Payment verification takes 10–30 minutes\\._\n"
        f"_Your card will appear in My Orders once confirmed\\._\n\n"
        f"💛 Thanks for shopping with *4xCardsShop*\\!"
    )

def txt_orders(orders: list) -> str:
    if not orders:
        return (
            "📦 *My Orders*\n\n"
            "You haven't placed any orders yet\\.\n\n"
            "_Browse cards and make your first purchase\\!_"
        )
    lines = []
    for o in orders[:15]:
        ref, ctype, cnum, climit, cvalid, price, network, status, created = o
        safe_ref = ref.replace("#", "\\#")
        status_icon = "⏳" if status == "pending" else "✅"
        st_up = status.upper()
        lines.append(
            f"{status_icon} `{safe_ref}`\n"
            f"   💳 {ctype} ••••{cnum}\n"
            f"   💰 ${price:.2f} \\| 📅 {created[:10]} \\| {st_up}"
        )
    return "📦 *My Orders*\n\n" + "\n\n".join(lines)

# ══════════════════════════════════════════════════════
#  🤖  HANDLERS
# ══════════════════════════════════════════════════════

logging.basicConfig(
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id, user.first_name, user.username or "")
    await update.message.reply_text(
        txt_welcome(user.first_name),
        parse_mode="MarkdownV2",
        reply_markup=kb_main_menu()
    )


async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id, user.first_name, user.username or "")
    await update.message.reply_text(
        "🏠 *Main Menu*\n\nWhat would you like to do?",
        parse_mode="MarkdownV2",
        reply_markup=kb_main_menu()
    )


async def cmd_cart(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user  = update.effective_user
    cart_ = get_cart(user.id)
    if not cart_:
        await update.message.reply_text(
            "🛒 *Your Cart is Empty*\n\nBrowse cards and add them here\\!",
            parse_mode="MarkdownV2",
            reply_markup=kb_empty_cart()
        )
    else:
        await update.message.reply_text(
            txt_cart(cart_),
            parse_mode="MarkdownV2",
            reply_markup=kb_cart(cart_)
        )


async def cmd_orders(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user   = update.effective_user
    orders = get_orders(user.id)
    await update.message.reply_text(
        txt_orders(orders),
        parse_mode="MarkdownV2",
        reply_markup=kb_orders()
    )


async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin panel — only for ADMIN_IDS"""
    user = update.effective_user
    if ADMIN_IDS and user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Unauthorised.")
        return
    users_c, orders_c, revenue = get_stats()
    recent = get_all_orders_admin()
    lines = [
        f"📊 *Admin Panel*\n",
        f"👥 Total Users\\: {users_c}",
        f"🧾 Total Orders\\: {orders_c}",
        f"💰 Pending Revenue\\: ${revenue:.2f} USDT\n",
        "📋 *Recent 10 Orders\\:*",
    ]
    for o in recent[:10]:
        ref, ctype, price, network, status, created, name, uname = o
        safe_ref = ref.replace("#", "\\#")
        s_upper = status.upper()
        lines.append(f"• `{safe_ref}` {ctype} \\— ${price:.2f} \\| {name} @{uname} \\| {s_upper}")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="MarkdownV2"
    )


async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    data = q.data
    user = update.effective_user
    ensure_user(user.id, user.first_name, user.username or "")
    await q.answer()

    # ─ Main Menu ─
    if data == "main_menu":
        await q.edit_message_text(
            "🏠 *Main Menu*\n\nWhat would you like to do?",
            parse_mode="MarkdownV2",
            reply_markup=kb_main_menu()
        )

    # ─ About ─
    elif data == "about":
        txt = (
            "ℹ️ *About 4xCardsShop*\n\n"
            "💳 Premium virtual card marketplace\n"
            "👥 50,000\\+ satisfied cardholders\n"
            "🔒 256\\-bit SSL Encrypted\n"
            "⚡ Instant delivery\n"
            "₿  6 Crypto payment networks\n"
            "🌍 180\\+ countries served\n"
            "📊 99\\.98% uptime SLA\n\n"
            "📞 Support\\: @4xCardSupport\n"
            "📢 Channel\\: @4xCardsShopOfficial\n\n"
            "_© 2025 4xCardsShop_"
        )
        await q.edit_message_text(txt, parse_mode="MarkdownV2", reply_markup=kb_back_main())

    # ─ Browse / Filters / Pagination ─
    elif data in ("browse_all",) or data.startswith("filter_") or data.startswith("page_"):
        if data == "browse_all":
            brand, page = "all", 0
        elif data.startswith("filter_"):
            brand, page = data[7:], 0
        else:  # page_<brand>_<n>
            _, brand, pg = data.split("_", 2)
            page = int(pg)

        filtered = ALL_CARDS if brand == "all" else [c for c in ALL_CARDS if c["brand"].lower() == brand]
        label    = "All Cards" if brand == "all" else brand.upper()
        txt = (
            f"🃏 *Card Catalog — {label}*\n"
            f"_{len(filtered)} cards available_\n\n"
            "Tap a card to view details:"
        )
        await q.edit_message_text(
            txt, parse_mode="MarkdownV2",
            reply_markup=kb_cards(filtered, page, brand)
        )

    # ─ Brand Filter ─
    elif data == "brand_filter":
        await q.edit_message_text(
            "🔍 *Filter by Brand*\n\nChoose a card network:",
            parse_mode="MarkdownV2",
            reply_markup=kb_brand_filter()
        )

    # ─ Card Detail ─
    elif data.startswith("card_"):
        card_id = int(data[5:])
        card    = next((c for c in ALL_CARDS if c["id"] == card_id), None)
        if not card:
            await q.answer("Card not found.", show_alert=True)
            return
        in_cart = any(c["id"] == card_id for c in get_cart(user.id))
        await q.edit_message_text(
            txt_card(card),
            parse_mode="MarkdownV2",
            reply_markup=kb_card_detail(card_id, in_cart)
        )

    # ─ Add to Cart ─
    elif data.startswith("addcart_"):
        card_id    = int(data[8:])
        cart_items = get_cart(user.id)
        if any(c["id"] == card_id for c in cart_items):
            await q.answer("✅ Already in your cart!", show_alert=True)
        else:
            add_to_cart(user.id, card_id)
            await q.answer("🛒 Added to cart!", show_alert=True)
            await q.edit_message_reply_markup(reply_markup=kb_card_detail(card_id, True))

    # ─ Buy Now ─
    elif data.startswith("buynow_"):
        card_id    = int(data[7:])
        cart_items = get_cart(user.id)
        if not any(c["id"] == card_id for c in cart_items):
            add_to_cart(user.id, card_id)
        await _show_checkout(q, user.id)

    # ─ Cart View ─
    elif data == "cart":
        cart_items = get_cart(user.id)
        if not cart_items:
            await q.edit_message_text(
                "🛒 *Your Cart is Empty*\n\nBrowse cards and add them here\\!",
                parse_mode="MarkdownV2",
                reply_markup=kb_empty_cart()
            )
        else:
            await q.edit_message_text(
                txt_cart(cart_items),
                parse_mode="MarkdownV2",
                reply_markup=kb_cart(cart_items)
            )

    # ─ Remove from Cart ─
    elif data.startswith("rmcart_"):
        card_id = int(data[7:])
        remove_from_cart(user.id, card_id)
        await q.answer("Removed from cart.", show_alert=False)
        cart_items = get_cart(user.id)
        if not cart_items:
            await q.edit_message_text(
                "🛒 *Your Cart is Empty*",
                parse_mode="MarkdownV2",
                reply_markup=kb_empty_cart()
            )
        else:
            await q.edit_message_text(
                txt_cart(cart_items),
                parse_mode="MarkdownV2",
                reply_markup=kb_cart(cart_items)
            )

    # ─ Checkout (crypto select) ─
    elif data == "checkout":
        await _show_checkout(q, user.id)

    # ─ Select Crypto Network ─
    elif data.startswith("pay_"):
        network_key = data[4:]
        if network_key not in WALLETS:
            await q.answer("Invalid network.", show_alert=True)
            return
        name, addr = WALLETS[network_key]
        cart_items  = get_cart(user.id)
        if not cart_items:
            await q.answer("Cart is empty!", show_alert=True)
            return
        total = sum(c["price"] for c in cart_items)
        await q.edit_message_text(
            txt_payment(name, addr, total),
            parse_mode="MarkdownV2",
            reply_markup=kb_payment_confirm(network_key)
        )

    # ─ Confirm Payment ─
    elif data.startswith("confirm_"):
        network_key = data[8:]
        cart_items  = get_cart(user.id)
        if not cart_items:
            await q.answer("Cart is empty!", show_alert=True)
            return
        name, _ = WALLETS.get(network_key, ("Unknown", ""))
        order_ref = f"#4X{random.randint(10000, 99999)}"
        save_orders(user.id, cart_items, name, order_ref)
        clear_cart(user.id)
        await q.edit_message_text(
            txt_success(order_ref),
            parse_mode="MarkdownV2",
            reply_markup=kb_post_order()
        )

    # ─ My Orders ─
    elif data == "orders":
        orders = get_orders(user.id)
        await q.edit_message_text(
            txt_orders(orders),
            parse_mode="MarkdownV2",
            reply_markup=kb_orders()
        )


async def _show_checkout(q, user_id: int):
    cart_items = get_cart(user_id)
    if not cart_items:
        await q.edit_message_text(
            "🛒 *Your Cart is Empty\\!*\n\nAdd some cards first\\.",
            parse_mode="MarkdownV2",
            reply_markup=kb_empty_cart()
        )
        return
    await q.edit_message_text(
        txt_checkout(cart_items),
        parse_mode="MarkdownV2",
        reply_markup=kb_crypto()
    )


# ══════════════════════════════════════════════════════
#  🚀  MAIN
# ══════════════════════════════════════════════════════

def main():
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌  ERROR: BOT_TOKEN set nahi hai!")
        print("   Step 1: @BotFather pe jaao")
        print("   Step 2: /newbot karo")
        print("   Step 3: Token copy karo")
        print("   Step 4: BOT_TOKEN variable mein paste karo")
        return

    init_db()
    logger.info("Database initialized ✓")

    app = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("menu",   cmd_menu))
    app.add_handler(CommandHandler("cart",   cmd_cart))
    app.add_handler(CommandHandler("orders", cmd_orders))
    app.add_handler(CommandHandler("admin",  cmd_admin))

    # Callbacks
    app.add_handler(CallbackQueryHandler(on_callback))

    logger.info("4xCardsShop Bot started ✓")
    print("✅  Bot chal raha hai... (Ctrl+C se band karo)")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
