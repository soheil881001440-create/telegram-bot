
# ===== WALLET HELPERS =====
def get_wallet(uid):
    db=load_db()
    return db.get("wallets",{}).get(str(uid),0)

def add_wallet(uid,amount):
    db=load_db()
    db.setdefault("wallets",{})
    db.setdefault("transactions",[])
    db["wallets"][str(uid)]=db["wallets"].get(str(uid),0)+amount
    db["transactions"].append({"user":str(uid),"amount":amount,"type":"deposit"})
    save_db(db)

def deduct_wallet(uid,amount):
    db=load_db()
    db.setdefault("wallets",{})
    bal=db["wallets"].get(str(uid),0)
    if bal<amount:
        return False
    db["wallets"][str(uid)]=bal-amount
    db.setdefault("transactions",[])
    db["transactions"].append({"user":str(uid),"amount":amount,"type":"purchase"})
    save_db(db)
    return True

"""
ربات تلگرام فروش کانفیگ
نیازمندی‌ها: pip install python-telegram-bot==20.7
"""

import logging
import json
import os
import functools
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

# ─── تنظیمات ───────────────────────────────────────────────
BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_IDS = [8224023773]

# ─── اطلاعات پرداخت ─────────────────────────────────────────
CARD_NUMBER = os.environ.get("CARD_NUMBER", "")
CARD_OWNER = os.environ.get("CARD_OWNER", "")

# ─── لاگ ───────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── Keep-Alive Server ─────────────────────────────────────
class _PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass

def start_keep_alive():
    port = int(os.environ.get("BOT_PORT", 8000))
    server = HTTPServer(("0.0.0.0", port), _PingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info(f"Keep-alive server running on port {port}")

# ─── دیتابیس ساده ──────────────────────────────────────────
DB_FILE = "database.json"

def load_db():
    if not os.path.exists(DB_FILE):
        return {"products": {}, "orders": {}, "users": {}, "wallets": {}, "transactions": [], "carts": {}}
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_db(db):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def init_db():
    db = load_db()
    if not db["products"]:
        db["products"] = {
            "1": {
                "name": "کانفیگ V2Ray - یک ماهه",
                "price": 50000,
                "description": "سرعت بالا، پینگ پایین\n✅ ۳۰ روز\n✅ حجم نامحدود\n✅ پشتیبانی ۲۴/۷",
                "file": "configs/v2ray_1month.txt",
                "active": True
            },
            "2": {
                "name": "کانفیگ V2Ray - سه ماهه",
                "price": 120000,
                "description": "بهترین قیمت!\n✅ ۹۰ روز\n✅ حجم نامحدود\n✅ پشتیبانی ۲۴/۷",
                "file": "configs/v2ray_3month.txt",
                "active": True
            },
            "3": {
                "name": "کانفیگ Hysteria2 - یک ماهه",
                "price": 60000,
                "description": "پروتکل جدید و قوی\n✅ ۳۰ روز\n✅ سرعت فوق‌العاده\n✅ مناسب گیمرها",
                "file": "configs/hysteria2_1month.txt",
                "active": True
            },
        }
        save_db(db)


def get_cart(uid):
    db = load_db()
    return db.setdefault("carts", {}).get(str(uid), [])

def save_cart(uid, cart):
    db = load_db()
    db.setdefault("carts", {})
    db["carts"][str(uid)] = cart
    save_db(db)

def clear_user_cart(uid):
    db = load_db()
    db.setdefault("carts", {})
    db["carts"].pop(str(uid), None)
    save_db(db)


# ─── State ها ──────────────────────────────────────────────
WAITING_RECEIPT = 1
EDIT_NAME, EDIT_PRICE, EDIT_DESC = 2, 3, 4
ADD_NAME, ADD_PRICE, ADD_DESC = 5, 6, 7
WAITING_CARD = 8
WAITING_CONFIG = 9

# ─── سبد خرید موقت ─────────────────────────────────────────
carts = {}  # deprecated, using database carts
pending_configs = {}  # ادمین‌هایی که منتظر ارسال کانفیگ هستن

# ══════════════════════════════════════════════════════════
#  ادمین چک
# ══════════════════════════════════════════════════════════

def admin_check(func):
    @functools.wraps(func)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        if uid not in ADMIN_IDS:
            if update.callback_query:
                await update.callback_query.answer("⛔ دسترسی ندارید!", show_alert=True)
            return ConversationHandler.END
        return await func(update, ctx)
    return wrapper

# ══════════════════════════════════════════════════════════
#  هندلرهای کاربر
# ══════════════════════════════════════════════════════════

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db = load_db()
    uid = str(user.id)
    if uid not in db["users"]:
        db["users"][uid] = {
            "name": user.full_name,
            "username": user.username,
            "joined": str(datetime.now())
        }
        save_db(db)

    kb = [
        [InlineKeyboardButton("🛍 مشاهده محصولات", callback_data="show_products")],
        [InlineKeyboardButton("🛒 سبد خرید من", callback_data="my_cart")],
        [InlineKeyboardButton("📦 سفارش‌های من", callback_data="my_orders")],
        [InlineKeyboardButton("💰 کیف پول من", callback_data="wallet_menu")],
        [InlineKeyboardButton("📞 پشتیبانی", callback_data="support")],
    ]
    if user.id in ADMIN_IDS:
        kb.append([InlineKeyboardButton("⚙️ پنل ادمین", callback_data="admin_panel")])

    await update.message.reply_text(
        f"سلام {user.first_name} عزیز! 👋\n\n"
        "به ربات فروش کانفیگ خوش اومدی.\n"
        "از منوی زیر انتخاب کن:",
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def main_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    kb = [
        [InlineKeyboardButton("🛍 مشاهده محصولات", callback_data="show_products")],
        [InlineKeyboardButton("🛒 سبد خرید من", callback_data="my_cart")],
        [InlineKeyboardButton("📦 سفارش‌های من", callback_data="my_orders")],
        [InlineKeyboardButton("💰 کیف پول من", callback_data="wallet_menu")],
        [InlineKeyboardButton("📞 پشتیبانی", callback_data="support")],
    ]
    if user.id in ADMIN_IDS:
        kb.append([InlineKeyboardButton("⚙️ پنل ادمین", callback_data="admin_panel")])
    await query.edit_message_text("منوی اصلی 👇", reply_markup=InlineKeyboardMarkup(kb))


async def show_products(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    db = load_db()
    products = {pid: p for pid, p in db["products"].items() if p.get("active")}

    if not products:
        await query.edit_message_text("❌ محصولی موجود نیست.")
        return

    kb = []
    for pid, p in products.items():
        price_str = f"{p['price']:,}".replace(",", "،")
        kb.append([InlineKeyboardButton(
            f"{p['name']} — {price_str} تومان",
            callback_data=f"product_{pid}"
        )])
    kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")])

    await query.edit_message_text(
        "📦 محصولات موجود:\n\nیکی رو انتخاب کن 👇",
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def show_product_detail(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pid = query.data.split("_")[1]
    db = load_db()
    p = db["products"].get(pid)
    if not p:
        await query.edit_message_text("❌ محصول پیدا نشد.")
        return

    price_str = f"{p['price']:,}".replace(",", "،")
    kb = [
        [InlineKeyboardButton("🛒 افزودن به سبد خرید", callback_data=f"addcart_{pid}")],
        [InlineKeyboardButton("🔙 بازگشت به محصولات", callback_data="show_products")],
    ]
    await query.edit_message_text(
        f"📦 *{p['name']}*\n\n"
        f"{p['description']}\n\n"
        f"💰 قیمت: *{price_str} تومان*",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )


async def add_to_cart(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pid = query.data.split("_")[1]
    db = load_db()
    p = db["products"].get(pid)
    if not p:
        await query.answer("❌ محصول پیدا نشد!", show_alert=True)
        return

    uid = query.from_user.id
    cart = get_cart(uid)
    cart.append({
        "product_id": pid,
        "product_name": p["name"],
        "price": p["price"]
    })
    save_cart(uid, cart)

    await query.edit_message_text(
        f"✅ {p['name']} به سبد خرید اضافه شد.
تعداد اقلام: {len(cart)}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 ادامه و پرداخت", callback_data="checkout")],
            [InlineKeyboardButton("🛒 مشاهده سبد", callback_data="my_cart")]
        ])
    )

async def my_cart(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    cart = get_cart(uid)

    if not cart:
        kb = [[InlineKeyboardButton("🛍 مشاهده محصولات", callback_data="show_products")]]
        await query.edit_message_text(
            "🛒 سبد خریدت خالیه!\nبرو یه چیزی انتخاب کن 😊",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return

    price_str = f"{cart['price']:,}".replace(",", "،")
    kb = [
        [InlineKeyboardButton("💳 پرداخت", callback_data="checkout")],
        [InlineKeyboardButton("🗑 خالی کردن سبد", callback_data="clear_cart")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")],
    ]
    await query.edit_message_text(
        f"🛒 *سبد خرید شما:*\n\n"
        f"📦 {cart['product_name']}\n"
        f"💰 {price_str} تومان\n\n"
        "برای پرداخت دکمه زیر رو بزن 👇",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )


async def clear_cart(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    clear_user_cart(uid)
    kb = [[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]
    await query.edit_message_text("✅ سبد خریدت خالی شد.", reply_markup=InlineKeyboardMarkup(kb))


async def checkout(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    cart = get_cart(uid)
    if not cart:
        await query.edit_message_text("❌ سبد خریدت خالیه!")
        return ConversationHandler.END

    price_str = f"{cart['price']:,}".replace(",", "،")

    await query.edit_message_text(
        f"✅ درخواست پرداخت ثبت شد!\n\n"
        f"📦 {cart['product_name']}\n"
        f"💰 مبلغ: *{price_str} تومان*\n\n"
        "⏳ اطلاعات کارت به زودی برات ارسال میشه.\n"
        "بعد از دریافت، پرداخت کن و عکس رسید رو اینجا بفرست 🙏",
        parse_mode="Markdown"
    )

    user = query.from_user
    for admin_id in ADMIN_IDS:
        try:
            kb = [[InlineKeyboardButton(
                "💳 ارسال شماره کارت به کاربر",
                callback_data=f"sendcard_{uid}"
            )]]
            await ctx.bot.send_message(
                chat_id=admin_id,
                text=(
                    f"🔔 *درخواست پرداخت جدید!*\n\n"
                    f"👤 کاربر: {user.full_name} (@{user.username})\n"
                    f"🆔 آی‌دی: `{uid}`\n"
                    f"📦 محصول: {cart['product_name']}\n"
                    f"💰 مبلغ: {price_str} تومان\n\n"
                    "برای ارسال شماره کارت به کاربر، دکمه زیر رو بزن 👇"
                ),
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"خطا در اطلاع به ادمین: {e}")

    return WAITING_RECEIPT


async def receive_receipt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cart = get_cart(uid)
    if not cart:
        await update.message.reply_text("❌ سبد خریدت خالیه. دوباره از /start شروع کن.")
        return ConversationHandler.END

    db = load_db()
    order_id = str(len(db["orders"]) + 1)
    db["orders"][order_id] = {
        "user_id": str(uid),
        "product_id": cart["product_id"],
        "product_name": cart["product_name"],
        "price": cart["price"],
        "status": "pending",
        "date": str(datetime.now()),
    }
    save_db(db)
    clear_user_cart(uid)

    await update.message.reply_text(
        f"✅ رسیدت دریافت شد!\n\n"
        f"🔢 شماره سفارش: `{order_id}`\n"
        "⏳ بعد از تأیید پرداخت، کانفیگت ارسال میشه.\n"
        "معمولاً کمتر از ۳۰ دقیقه 🙏",
        parse_mode="Markdown"
    )

    for admin_id in ADMIN_IDS:
        try:
            kb = [[
                InlineKeyboardButton("✅ تأیید", callback_data=f"confirm_{order_id}"),
                InlineKeyboardButton("❌ رد", callback_data=f"reject_{order_id}"),
            ]]
            user = update.effective_user
            price_str = f"{cart['price']:,}".replace(",", "،")
            msg = (
                f"🔔 *رسید پرداخت دریافت شد!*\n\n"
                f"👤 {user.full_name} (@{user.username})\n"
                f"🆔 `{uid}`\n"
                f"📦 {cart['product_name']}\n"
                f"💰 {price_str} تومان\n"
                f"🔢 سفارش #{order_id}"
            )
            if update.message.photo:
                await ctx.bot.send_photo(
                    chat_id=admin_id,
                    photo=update.message.photo[-1].file_id,
                    caption=msg,
                    reply_markup=InlineKeyboardMarkup(kb),
                    parse_mode="Markdown"
                )
            else:
                await ctx.bot.send_message(
                    chat_id=admin_id,
                    text=msg,
                    reply_markup=InlineKeyboardMarkup(kb),
                    parse_mode="Markdown"
                )
        except Exception as e:
            logger.error(f"خطا در ارسال به ادمین: {e}")

    return ConversationHandler.END


async def my_orders(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = str(query.from_user.id)
    db = load_db()
    user_orders = {oid: o for oid, o in db["orders"].items() if o["user_id"] == uid}

    if not user_orders:
        kb = [[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]
        await query.edit_message_text("📦 هنوز سفارشی نداری.", reply_markup=InlineKeyboardMarkup(kb))
        return

    status_map = {"pending": "⏳ در انتظار تأیید", "confirmed": "✅ تأیید شده", "rejected": "❌ رد شده"}
    text = "📦 *سفارش‌های شما:*\n\n"
    for oid, o in list(user_orders.items())[-5:]:
        st = status_map.get(o["status"], o["status"])
        price_str = f"{o['price']:,}".replace(",", "،")
        text += f"🔢 #{oid} | {o['product_name']}\n💰 {price_str} تومان | {st}\n\n"

    kb = [[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")


async def support(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kb = [[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]
    await query.edit_message_text(
        "📞 *پشتیبانی:*\n\n"
        "برای ارتباط با پشتیبانی:\n"
        "👤 @Soheil88100\n\n"
        "ساعات پاسخگویی: ۹ صبح تا ۱۲ شب",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )

# ══════════════════════════════════════════════════════════
#  پنل ادمین
# ══════════════════════════════════════════════════════════

@admin_check
async def send_card_to_user(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    target_uid = int(query.data.split("_")[1])
    ctx.user_data["sendcard_target"] = target_uid
    await query.edit_message_text(
        "💳 شماره کارت رو بنویس تا برای مشتری بفرستم:\n\n"
        "(مثال: 6037-XXXX-XXXX-XXXX به نام علی احمدی)"
    )
    return WAITING_CARD

async def send_card_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    target_uid = ctx.user_data.get("sendcard_target")
    card_text = update.message.text
    if not target_uid:
        await update.message.reply_text("❌ خطا، دوباره امتحان کن.")
        return ConversationHandler.END

    cart = carts.get(target_uid)
    price_str = f"{cart['price']:,}".replace(",", "،") if cart else "نامشخص"

    try:
        await ctx.bot.send_message(
            chat_id=target_uid,
            text=(
                f"💳 *اطلاعات پرداخت:*\n\n"
                f"💰 مبلغ: *{price_str} تومان*\n\n"
                f"🏦 شماره کارت:\n`{card_text}`\n\n"
                "روی شماره کارت بزن تا کپی بشه 👆\n\n"
                "بعد از واریز، لطفاً *عکس رسید* یا *شماره پیگیری* رو اینجا بفرست 👇"
            ),
            parse_mode="Markdown"
        )
        await update.message.reply_text("✅ شماره کارت برای مشتری ارسال شد.")
    except Exception as e:
        await update.message.reply_text(f"❌ خطا در ارسال: {e}")

    return ConversationHandler.END


@admin_check
async def admin_panel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    db = load_db()
    pending = sum(1 for o in db["orders"].values() if o["status"] == "pending")

    kb = [
        [InlineKeyboardButton(f"📋 سفارش‌های در انتظار ({pending})", callback_data="admin_orders")],
        [InlineKeyboardButton("📦 مدیریت محصولات", callback_data="admin_products")],
        [InlineKeyboardButton("👥 لیست کاربران", callback_data="admin_users")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")],
    ]
    await query.edit_message_text(
        "⚙️ *پنل مدیریت ادمین*",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )


@admin_check
async def admin_orders(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    db = load_db()
    pending_orders = {oid: o for oid, o in db["orders"].items() if o["status"] == "pending"}

    if not pending_orders:
        kb = [[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]]
        await query.edit_message_text("✅ هیچ سفارش در انتظاری وجود ندارد.", reply_markup=InlineKeyboardMarkup(kb))
        return

    kb = []
    for oid, o in pending_orders.items():
        kb.append([InlineKeyboardButton(f"#{oid} - {o['product_name']}", callback_data=f"admin_order_{oid}")])
    kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")])
    await query.edit_message_text(
        f"📋 *سفارش‌های در انتظار ({len(pending_orders)} عدد):*",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )


@admin_check
async def admin_order_detail(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    oid = query.data.split("_")[2]
    db = load_db()
    o = db["orders"].get(oid)
    if not o:
        await query.edit_message_text("❌ سفارش پیدا نشد.")
        return

    price_str = f"{o['price']:,}".replace(",", "،")
    kb = [
        [
            InlineKeyboardButton("✅ تأیید و ارسال کانفیگ", callback_data=f"confirm_{oid}"),
            InlineKeyboardButton("❌ رد سفارش", callback_data=f"reject_{oid}"),
        ],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_orders")],
    ]
    await query.edit_message_text(
        f"📋 *سفارش #{oid}*\n\n"
        f"👤 کاربر: {o['user_id']}\n"
        f"📦 محصول: {o['product_name']}\n"
        f"💰 مبلغ: {price_str} تومان\n"
        f"📅 تاریخ: {o['date'][:16]}\n"
        f"🔄 وضعیت: {o['status']}",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )


@admin_check
async def confirm_order(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    oid = query.data.split("_")[1]
    db = load_db()
    o = db["orders"].get(oid)
    if not o or o["status"] != "pending":
        await query.answer("❌ سفارش قابل تأیید نیست!", show_alert=True)
        return

    o["status"] = "confirmed"
    save_db(db)

    pending_configs[query.from_user.id] = {
        "order_id": oid,
        "user_id": int(o["user_id"]),
        "product_name": o["product_name"]
    }

    await query.edit_message_text(
        f"✅ سفارش #{oid} تأیید شد.\n\n"
        f"📦 {o['product_name']}\n"
        f"👤 کاربر: {o['user_id']}\n\n"
        "حالا کانفیگ رو اینجا بفرست 👇\n"
        "(متن، فایل txt، یا هر فرمتی)"
    )

async def send_config_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id
    if admin_id not in ADMIN_IDS:
        return
    if admin_id not in pending_configs:
        return

    info = pending_configs.pop(admin_id)
    user_id = info["user_id"]
    oid = info["order_id"]
    product_name = info["product_name"]

    try:
        if update.message.document:
            await ctx.bot.send_document(
                chat_id=user_id,
                document=update.message.document.file_id,
                caption=f"✅ کانفیگ شما آماده‌ست!\n📦 {product_name}\n\nممنون از خریدت 🙏"
            )
        elif update.message.photo:
            await ctx.bot.send_photo(
                chat_id=user_id,
                photo=update.message.photo[-1].file_id,
                caption=f"✅ کانفیگ شما آماده‌ست!\n📦 {product_name}\n\nممنون از خریدت 🙏"
            )
        else:
            await ctx.bot.send_message(
                chat_id=user_id,
                text=f"✅ کانفیگ شما آماده‌ست!\n📦 {product_name}\n\n`{update.message.text}`\n\nروی متن بالا بزن تا کپی بشه 👆\nممنون از خریدت 🙏",
                parse_mode="Markdown"
            )
        await update.message.reply_text(f"✅ کانفیگ سفارش #{oid} برای مشتری ارسال شد.")
    except Exception as e:
        await update.message.reply_text(f"❌ خطا در ارسال: {e}")


@admin_check
async def reject_order(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    oid = query.data.split("_")[1]
    db = load_db()
    o = db["orders"].get(oid)
    if not o:
        await query.answer("❌ سفارش پیدا نشد!", show_alert=True)
        return

    o["status"] = "rejected"
    save_db(db)

    user_id = int(o["user_id"])
    try:
        await ctx.bot.send_message(
            chat_id=user_id,
            text=f"❌ متأسفانه سفارش #{oid} رد شد.\nاگر مشکلی دارید با پشتیبانی در ارتباط باشید."
        )
    except Exception as e:
        logger.error(e)

    await query.edit_message_text(f"❌ سفارش #{oid} رد شد.")


@admin_check
async def admin_products(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    db = load_db()
    kb = []
    for pid, p in db["products"].items():
        status = "✅" if p.get("active") else "❌"
        kb.append([InlineKeyboardButton(f"{status} {p['name']}", callback_data=f"admin_product_{pid}")])
    kb.append([InlineKeyboardButton("➕ افزودن محصول جدید", callback_data="add_product")])
    kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")])
    await query.edit_message_text(
        "📦 *مدیریت محصولات:*",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )


@admin_check
async def admin_product_detail(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pid = query.data.split("_")[2]
    db = load_db()
    p = db["products"].get(pid)
    if not p:
        await query.edit_message_text("❌ محصول پیدا نشد.")
        return

    price_str = f"{p['price']:,}".replace(",", "،")
    status = "✅ فعال" if p.get("active") else "❌ غیرفعال"
    toggle_label = "❌ غیرفعال کردن" if p.get("active") else "✅ فعال کردن"

    kb = [
        [InlineKeyboardButton("✏️ ویرایش نام", callback_data=f"edit_name_{pid}"),
         InlineKeyboardButton("💰 ویرایش قیمت", callback_data=f"edit_price_{pid}")],
        [InlineKeyboardButton("📝 ویرایش توضیحات", callback_data=f"edit_desc_{pid}")],
        [InlineKeyboardButton(toggle_label, callback_data=f"admin_toggle_{pid}")],
        [InlineKeyboardButton("🗑 حذف", callback_data=f"admin_delete_{pid}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_products")],
    ]
    await query.edit_message_text(
        f"📦 {p['name']}\n"
        f"💰 {price_str} تومان\n"
        f"🔄 وضعیت: {status}",
        reply_markup=InlineKeyboardMarkup(kb),
    )


@admin_check
async def edit_name_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pid = query.data.split("_")[2]
    ctx.user_data["edit_pid"] = pid
    await query.edit_message_text(f"✏️ نام جدید محصول رو بنویس:")
    return EDIT_NAME

async def edit_name_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pid = ctx.user_data.get("edit_pid")
    db = load_db()
    if pid and pid in db["products"]:
        db["products"][pid]["name"] = update.message.text
        save_db(db)
    await update.message.reply_text("✅ نام محصول تغییر کرد!")
    return ConversationHandler.END

@admin_check
async def edit_price_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pid = query.data.split("_")[2]
    ctx.user_data["edit_pid"] = pid
    await query.edit_message_text("💰 قیمت جدید رو بنویس (فقط عدد، تومان):")
    return EDIT_PRICE

async def edit_price_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pid = ctx.user_data.get("edit_pid")
    try:
        price = int(update.message.text.replace(",", "").replace("،", ""))
        db = load_db()
        if pid and pid in db["products"]:
            db["products"][pid]["price"] = price
            save_db(db)
        await update.message.reply_text("✅ قیمت محصول تغییر کرد!")
    except Exception:
        await update.message.reply_text("❌ فقط عدد وارد کن!")
    return ConversationHandler.END

@admin_check
async def edit_desc_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pid = query.data.split("_")[2]
    ctx.user_data["edit_pid"] = pid
    await query.edit_message_text("📝 توضیحات جدید رو بنویس:")
    return EDIT_DESC

async def edit_desc_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pid = ctx.user_data.get("edit_pid")
    db = load_db()
    if pid and pid in db["products"]:
        db["products"][pid]["description"] = update.message.text
        save_db(db)
    await update.message.reply_text("✅ توضیحات محصول تغییر کرد!")
    return ConversationHandler.END

@admin_check
async def add_product_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data.clear()
    await query.edit_message_text("➕ نام محصول جدید رو بنویس:\n\n(برای لغو /start بزن)")
    return ADD_NAME

async def add_product_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["new_name"] = update.message.text
    await update.message.reply_text("💰 قیمت رو بنویس (فقط عدد، تومان):")
    return ADD_PRICE

async def add_product_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        price = int(update.message.text.replace(",", "").replace("،", ""))
        ctx.user_data["new_price"] = price
        await update.message.reply_text("📝 توضیحات محصول رو بنویس:")
        return ADD_DESC
    except Exception:
        await update.message.reply_text("❌ فقط عدد وارد کن!")
        return ADD_PRICE

async def add_product_desc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db = load_db()
    new_id = str(max([int(k) for k in db["products"].keys()], default=0) + 1)
    db["products"][new_id] = {
        "name": ctx.user_data["new_name"],
        "price": ctx.user_data["new_price"],
        "description": update.message.text,
        "file": f"configs/product_{new_id}.txt",
        "active": True
    }
    save_db(db)
    await update.message.reply_text(
        f"✅ محصول جدید اضافه شد!\n\n📦 {ctx.user_data['new_name']}\n💰 {ctx.user_data['new_price']:,} تومان"
    )
    return ConversationHandler.END


@admin_check
async def admin_toggle_product(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    pid = query.data.split("_")[2]
    db = load_db()
    if pid in db["products"]:
        db["products"][pid]["active"] = not db["products"][pid].get("active", True)
        save_db(db)
        status = "✅ فعال" if db["products"][pid]["active"] else "❌ غیرفعال"
        await query.answer(f"محصول {status} شد!", show_alert=True)
    await admin_products(update, ctx)


@admin_check
async def admin_delete_product(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    pid = query.data.split("_")[2]
    db = load_db()
    if pid in db["products"]:
        del db["products"][pid]
        save_db(db)
        await query.answer("🗑 محصول حذف شد!", show_alert=True)
    await admin_products(update, ctx)


@admin_check
async def admin_users(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    db = load_db()
    users = db.get("users", {})
    text = f"👥 *تعداد کاربران: {len(users)}*\n\n"
    for uid, u in list(users.items())[-10:]:
        text += f"👤 {u['name']} | @{u.get('username', '-')} | `{uid}`\n"
    kb = [[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")


# ══════════════════════════════════════════════════════════
#  اجرای ربات
# ══════════════════════════════════════════════════════════

def main():
    start_keep_alive()
    init_db()
    os.makedirs("configs", exist_ok=True)

    app = Application.builder().token(BOT_TOKEN).build()

    send_card_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(send_card_to_user, pattern=r"^sendcard_\d+$")],
        states={WAITING_CARD: [MessageHandler(filters.TEXT & ~filters.COMMAND, send_card_done)]},
        fallbacks=[CommandHandler("start", start)],
        per_message=False,
        allow_reentry=True,
    )

    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(checkout, pattern="^checkout$")],
        states={
            WAITING_RECEIPT: [
                MessageHandler(filters.PHOTO | filters.Document.ALL | filters.TEXT & ~filters.COMMAND, receive_receipt)
            ],
        },
        fallbacks=[CommandHandler("start", start)],
        per_message=False,
        allow_reentry=True,
    )

    edit_name_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_name_start, pattern=r"^edit_name_\d+$")],
        states={EDIT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_name_done)]},
        fallbacks=[CommandHandler("start", start)],
        per_message=False,
        allow_reentry=True,
    )

    edit_price_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_price_start, pattern=r"^edit_price_\d+$")],
        states={EDIT_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_price_done)]},
        fallbacks=[CommandHandler("start", start)],
        per_message=False,
        allow_reentry=True,
    )

    edit_desc_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_desc_start, pattern=r"^edit_desc_\d+$")],
        states={EDIT_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_desc_done)]},
        fallbacks=[CommandHandler("start", start)],
        per_message=False,
        allow_reentry=True,
    )

    add_product_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_product_start, pattern="^add_product$")],
        states={
            ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_name)],
            ADD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_price)],
            ADD_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_desc)],
        },
        fallbacks=[CommandHandler("start", start)],
        per_message=False,
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(send_card_conv)
    app.add_handler(conv)
    app.add_handler(edit_name_conv)
    app.add_handler(edit_price_conv)
    app.add_handler(edit_desc_conv)
    app.add_handler(add_product_conv)

    # کاربر
    app.add_handler(CallbackQueryHandler(show_products, pattern="^show_products$"))
    app.add_handler(CallbackQueryHandler(show_product_detail, pattern=r"^product_\d+$"))
    app.add_handler(CallbackQueryHandler(add_to_cart, pattern=r"^addcart_\d+$"))
    app.add_handler(CallbackQueryHandler(my_cart, pattern="^my_cart$"))
    app.add_handler(CallbackQueryHandler(clear_cart, pattern="^clear_cart$"))
    app.add_handler(CallbackQueryHandler(my_orders, pattern="^my_orders$"))
    app.add_handler(CallbackQueryHandler(support, pattern="^support$"))
    app.add_handler(CallbackQueryHandler(main_menu, pattern="^main_menu$"))

    # ادمین
    app.add_handler(CallbackQueryHandler(confirm_order, pattern=r"^confirm_\d+$"))
    app.add_handler(CallbackQueryHandler(reject_order, pattern=r"^reject_\d+$"))
    app.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin_panel$"))
    app.add_handler(CallbackQueryHandler(admin_orders, pattern="^admin_orders$"))
    app.add_handler(CallbackQueryHandler(admin_order_detail, pattern=r"^admin_order_\d+$"))
    app.add_handler(CallbackQueryHandler(admin_products, pattern="^admin_products$"))
    app.add_handler(CallbackQueryHandler(admin_product_detail, pattern=r"^admin_product_\d+$"))
    app.add_handler(CallbackQueryHandler(admin_toggle_product, pattern=r"^admin_toggle_\d+$"))
    app.add_handler(CallbackQueryHandler(admin_delete_product, pattern=r"^admin_delete_\d+$"))
    app.add_handler(CallbackQueryHandler(admin_users, pattern="^admin_users$"))

    # دریافت کانفیگ از ادمین
    app.add_handler(MessageHandler(
        filters.User(ADMIN_IDS) & (filters.TEXT & ~filters.COMMAND | filters.PHOTO | filters.Document.ALL),
        send_config_done
    ))

    print("✅ ربات در حال اجراست...")
    app.run_polling()


if __name__ == "__main__":
    main()
