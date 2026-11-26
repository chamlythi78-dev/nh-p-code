import asyncio
import glob
import math
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from html import escape
from io import BytesIO
from urllib.parse import quote
from urllib.request import Request, urlopen

import asyncpg
import ddddocr
from PIL import Image, ImageEnhance
import cairosvg
from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from playwright.async_api import async_playwright
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession

# =====================================================================
# CẤU HÌNH
# =====================================================================
API_ID = int(os.getenv("API_ID", "30309186"))
API_HASH = os.getenv("API_HASH", "307273bc278e53017b5fdcd407c1d941")
PHONE_NUMBER = os.getenv("PHONE_NUMBER", "+84335442999")

# Lấy BOT_TOKEN từ biến môi trường trên Railway
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise RuntimeError("Thiếu biến môi trường BOT_TOKEN trên Railway!")

ADMIN_ID = int(os.getenv("ADMIN_ID", "9220244280"))
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Phân loại nhóm quét
TEXT_TARGET_GROUPS = ["official78wins"]
VIDEO_TARGET_GROUPS = ["FreeCode_78win"]
ALL_TARGET_GROUPS = TEXT_TARGET_GROUPS + VIDEO_TARGET_GROUPS

TARGET_URL = "https://code78k.online/"
CODE_PRICE = 10000
MAX_BATCH = 30
ORDER_TIMEOUT_HOURS = 72
PAGE_SIZE = 8

# Hỗ trợ
SUPPORT_GROUP = "khututricvx"
SUPPORT_ADMIN = "dgfrutil"

# Nạp tiền
BANK_NAME = "KIENLONGBANK"
BANK_CODE = "KLB"
BANK_ACCOUNT_NAME = "BAN TIEN PHONG"
BANK_ACCOUNT_NO = "6530052011"
DEPOSIT_PREFIX = "nap tien code tu dong"
MIN_DEPOSIT = 10000
MAX_DEPOSIT = 50_000_000
QUICK_AMOUNTS = [10000, 20000, 50000, 100000, 500000, 1000000]

VN_TZ = timezone(timedelta(hours=7))

GAMES = {
    "78win": {"name": "78WIN", "price": CODE_PRICE},
}

# =====================================================================
# EMOJI PREMIUM
# =====================================================================
EMOJI_TABLE = {
    "ok": ("5206607081334906820", "✔️"),
    "no": ("5210952531676504517", "❌"),
    "fast": ("5456140674028019486", "⚡️"),
    "fire": ("5424972470023104089", "🔥"),
    "money": ("5231449120635370684", "💸"),
    "money2": ("5231005931550030290", "💸"),
    "cash": ("5409048419211682843", "💵"),
    "reload": ("5375338737028841420", "🔄"),
    "shield": ("5251203410396458957", "🛡"),
    "plus": ("5397916757333654639", "➕"),
    "down": ("5406745015365943482", "⬇️"),
    "new": ("5382357040008021292", "🆕"),
    "gem": ("5427168083074628963", "💎"),
    "game": ("5361741454685256344", "🎮"),
    "hourglass": ("5386367538735104399", "⌛"),
    "bulb": ("5422439311196834318", "💡"),
    "gold": ("5440539497383087970", "🥇"),
    "gift": ("5442939099906325301", "🎁"),
    "bell": ("5440833702642857683", "🔔"),
    "link": ("5440410042773824003", "🔗"),
    "bank": ("5238132025323444613", "🏦"),
    "card": ("5472250091332993630", "💳"),
    "wallet": ("5215420556089776398", "👛"),
    "receipt": ("5204242830687494041", "🧾"),
    "rocket": ("5188481279963715781", "🚀"),
    "trophy": ("5188344996356448758", "🏆"),
    "phone": ("5213179235996294999", "📞"),
    "mega": ("5298609030321691620", "📣"),
    "warn": ("5447644880824181073", "⚠️"),
    "pin": ("5397782960512444700", "📌"),
    "chart": ("5244837092042750681", "📈"),
    "coin": ("5382164415019768638", "🪙"),
    "bag": ("5417924076503062111", "💰"),
    "inbox": ("5443127283898405358", "📥"),
    "globe": ("5447410659077661506", "🌐"),
    "user": ("6066579956287148786", "👨‍💻"),
    "up": ("5415655814079723871", "🔝"),
    "top": ("5341498088408234504", "💯"),
    "soon": ("5440621591387980068", "🔜"),
    "pc": ("5282843764451195532", "🖥"),
    "lock": ("5296369303661067030", "🔒"),
    "mail": ("5253742260054409879", "✉️"),
}
EMOJI = {k: v[0] for k, v in EMOJI_TABLE.items()}
FALLBACK = {k: v[1] for k, v in EMOJI_TABLE.items()}


def e(name: str) -> str:
    return f'<tg-emoji emoji-id="{EMOJI[name]}">{FALLBACK[name]}</tg-emoji>'


def kb_btn(text: str, icon: str) -> KeyboardButton:
    return KeyboardButton(text=text, icon_custom_emoji_id=EMOJI[icon])


def inline_btn(text: str, icon: str, callback_data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=callback_data, icon_custom_emoji_id=EMOJI[icon])


def url_btn(text: str, icon: str, url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, url=url, icon_custom_emoji_id=EMOJI[icon])


# =====================================================================
# KHỞI TẠO
# =====================================================================
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
ocr = ddddocr.DdddOcr(show_ad=False)
db_pool: asyncpg.Pool | None = None
userbot: TelegramClient | None = None
temp_login_client: TelegramClient | None = None
background_tasks: list[asyncio.Task] = []
paid_notify_at: dict[int, float] = {}


class BotStates(StatesGroup):
    waiting_for_username = State()
    confirm_order = State()
    waiting_for_amount = State()
    waiting_for_otp = State()
    waiting_for_2fa = State()


BTN_CODE = "Nhập Code"
BTN_ACCOUNT = "Tài Khoản"
BTN_DEPOSIT = "Nạp Tiền"
BTN_HISTORY = "Lịch Sử"
BTN_ORDERS = "Đơn Hàng"
BTN_SUPPORT = "Nhóm Hỗ Trợ"
MENU_TEXTS = (BTN_CODE, BTN_ACCOUNT, BTN_DEPOSIT, BTN_HISTORY, BTN_ORDERS, BTN_SUPPORT)

main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [kb_btn(BTN_CODE, "fire"), kb_btn(BTN_ACCOUNT, "user")],
        [kb_btn(BTN_DEPOSIT, "money"), kb_btn(BTN_HISTORY, "receipt")],
        [kb_btn(BTN_ORDERS, "gift"), kb_btn(BTN_SUPPORT, "shield")],
    ],
    resize_keyboard=True,
)

SEP = "━━━━━━━━━━━━━━━━━━"


def now_str() -> str:
    return datetime.now(VN_TZ).strftime("%H:%M:%S %d/%m/%Y")


def fmt_dt(dt: datetime) -> str:
    return dt.astimezone(VN_TZ).strftime("%H:%M %d/%m/%Y")


# =====================================================================
# DATABASE
# =====================================================================
async def init_db():
    global db_pool
    if not DATABASE_URL:
        raise RuntimeError("Thiếu DATABASE_URL trên Railway!")
    db_pool = await asyncpg.create_pool(dsn=DATABASE_URL, min_size=1, max_size=5)
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                balance BIGINT DEFAULT 0
            )
        """)
        await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS total_deposit BIGINT DEFAULT 0")
        await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS joined_at TIMESTAMPTZ DEFAULT now()")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS hunt_accounts (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                game_username TEXT NOT NULL,
                status TEXT DEFAULT 'active'
            )
        """)
        await conn.execute("ALTER TABLE hunt_accounts ADD COLUMN IF NOT EXISTS game TEXT DEFAULT '78win'")
        await conn.execute("ALTER TABLE hunt_accounts ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT now()")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                amount BIGINT NOT NULL,
                type TEXT NOT NULL,
                note TEXT DEFAULT '',
                created_at TIMESTAMPTZ DEFAULT now()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_tx_user ON transactions (user_id, id DESC)")
        try:
            await conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_active_game_account
                ON hunt_accounts (game, lower(game_username))
                WHERE status = 'active'
            """)
        except Exception as ex:
            print(f"Không tạo được unique index: {ex}")


async def get_saved_session() -> str:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT value FROM settings WHERE key = 'telethon_session'")
        return row["value"].strip() if row else ""


async def save_session(session_str: str):
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO settings (key, value) VALUES ('telethon_session', $1)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """, session_str)


async def get_user_info(user_id: int):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO users (user_id, balance) VALUES ($1, 0) ON CONFLICT (user_id) DO NOTHING",
            user_id,
        )
        return await conn.fetchrow(
            "SELECT balance, COALESCE(total_deposit, 0) AS total_deposit, joined_at FROM users WHERE user_id = $1",
            user_id,
        )


async def get_user_balance(user_id: int) -> int:
    info = await get_user_info(user_id)
    return int(info["balance"]) if info else 0


async def add_tx(conn, user_id: int, amount: int, tx_type: str, note: str = ""):
    await conn.execute(
        "INSERT INTO transactions (user_id, amount, type, note) VALUES ($1, $2, $3, $4)",
        user_id, amount, tx_type, note,
    )


# =====================================================================
# ADMIN: ĐĂNG NHẬP USERBOT
# =====================================================================
@dp.message(Command("login"))
async def admin_login_start(message: types.Message, state: FSMContext):
    global temp_login_client
    if message.from_user.id != ADMIN_ID:
        return
    try:
        if temp_login_client:
            await temp_login_client.disconnect()
        temp_login_client = TelegramClient(StringSession(), API_ID, API_HASH)
        await temp_login_client.connect()
        await temp_login_client.send_code_request(PHONE_NUMBER)
        await message.answer(
            f"{e('mail')} Đã gửi mã OTP về SĐT <code>{escape(PHONE_NUMBER)}</code>.\n"
            f"{e('lock')} Hãy nhập mã OTP vào đây (thêm chữ <code>a</code> phía trước nếu sợ Telegram chặn, "
            f"ví dụ: <code>a12345</code>):"
        )
        await state.set_state(BotStates.waiting_for_otp)
    except Exception as ex:
        await message.answer(f"{e('no')} Lỗi gửi OTP: <code>{escape(str(ex))}</code>")


@dp.message(BotStates.waiting_for_otp)
async def admin_login_otp(message: types.Message, state: FSMContext):
    global temp_login_client
    if message.from_user.id != ADMIN_ID:
        return
    otp = re.sub(r"\D", "", message.text or "")
    if not otp:
        await message.answer(f"{e('no')} Mã OTP không hợp lệ, nhập lại:")
        return
    try:
        await temp_login_client.sign_in(PHONE_NUMBER, otp)
        session_str = temp_login_client.session.save()
        await save_session(session_str)
        await state.clear()
        await message.answer(
            f"{e('ok')} Đăng nhập nick quét thành công và đã lưu vào PostgreSQL!\n"
            f"{e('reload')} Đang khởi động bộ quét..."
        )
        asyncio.create_task(start_scanner(session_str))
    except SessionPasswordNeededError:
        await message.answer(f"{e('lock')} Nick có bật mật khẩu 2 bước (2FA). Vui lòng nhập mật khẩu:")
        await state.set_state(BotStates.waiting_for_2fa)
    except Exception as ex:
        await message.answer(
            f"{e('no')} Lỗi xác nhận OTP: <code>{escape(str(ex))}</code>\nGõ <code>/login</code> để thử lại."
        )
        await state.clear()


@dp.message(BotStates.waiting_for_2fa)
async def admin_login_2fa(message: types.Message, state: FSMContext):
    global temp_login_client
    if message.from_user.id != ADMIN_ID:
        return
    try:
        await temp_login_client.sign_in(password=(message.text or "").strip())
        session_str = temp_login_client.session.save()
        await save_session(session_str)
        await state.clear()
        await message.answer(f"{e('ok')} Đăng nhập 2FA thành công!\n{e('reload')} Đang khởi động bộ quét...")
        asyncio.create_task(start_scanner(session_str))
    except Exception as ex:
        await message.answer(
            f"{e('no')} Sai mật khẩu 2FA: <code>{escape(str(ex))}</code>\nGõ <code>/login</code> để thử lại."
        )
        await state.clear()


# =====================================================================
# TIỆN ÍCH GIAO DIỆN
# =====================================================================
async def edit_or_send(call: types.CallbackQuery, text: str, kb: InlineKeyboardMarkup | None = None):
    try:
        await call.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest:
        await call.message.answer(text, reply_markup=kb)


def home_text(bal: int) -> str:
    return (
        f"{e('fire')} <b>HỆ THỐNG NHẬP CODE TỰ ĐỘNG</b> {e('fast')}\n"
        f"{SEP}\n"
        f"{e('wallet')} Số dư: <b>{bal:,}đ</b>\n"
        f"{e('top')} Giá đăng ký: <b>{CODE_PRICE:,}đ / tài khoản</b>\n"
        f"{SEP}\n"
        f"{e('down')} Chọn chức năng ở menu bên dưới"
    )


def page_kb(prefix: str, page: int, pages: int) -> InlineKeyboardMarkup:
    nav = []
    if page > 0:
        nav.append(inline_btn("Trước", "reload", f"{prefix}:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="noop"))
    if page < pages - 1:
        nav.append(inline_btn("Sau", "down", f"{prefix}:{page + 1}"))
    rows = [nav] if pages > 1 else []
    rows.append([inline_btn("Nạp Tiền", "money", "dep:menu"), inline_btn("Menu Chính", "up", "home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.callback_query(F.data == "noop")
async def cb_noop(call: types.CallbackQuery):
    await call.answer()


@dp.callback_query(F.data == "home")
async def cb_home(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    bal = await get_user_balance(call.from_user.id)
    await call.message.answer(home_text(bal), reply_markup=main_kb)
    await call.answer()


# =====================================================================
# NGƯỜI DÙNG
# =====================================================================
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    bal = await get_user_balance(message.from_user.id)
    await message.answer(home_text(bal), reply_markup=main_kb)


async def build_account(user: types.User):
    info = await get_user_info(user.id)
    name = escape(user.full_name or "—")
    uname = f"@{escape(user.username)}" if user.username else "Chưa đặt"
    joined = info["joined_at"].astimezone(VN_TZ).strftime("%Y-%m-%d %H:%M:%S") if info["joined_at"] else "—"
    text = (
        f"{e('user')} <b>THÔNG TIN TÀI KHOẢN &amp; VÍ TIỀN</b>\n"
        f"\n"
        f"{e('link')} <b>Telegram ID:</b> <code>{user.id}</code>\n"
        f"{e('gold')} <b>Tên tài khoản:</b> {name}\n"
        f"{e('pin')} <b>Username:</b> {uname}\n"
        f"\n"
        f"{e('wallet')} <b>Số dư khả dụng:</b> <code>{int(info['balance']):,} VNĐ</code>\n"
        f"{e('cash')} <b>Tổng tiền đã nạp:</b> <code>{int(info['total_deposit']):,} VNĐ</code>\n"
        f"{e('hourglass')} <b>Ngày tham gia:</b> {joined}\n"
        f"\n"
        f"{e('bulb')} <i>Bấm 'Nạp Tiền' bên dưới để nạp thêm số dư nhanh chóng!</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [inline_btn("Nạp Tiền", "money", "dep:menu"), inline_btn("Lịch Sử GD", "receipt", "hist:0")],
        [inline_btn("Menu Chính", "up", "home")],
    ])
    return text, kb


@dp.message(F.text == BTN_ACCOUNT)
async def menu_account(message: types.Message, state: FSMContext):
    await state.clear()
    text, kb = await build_account(message.from_user)
    await message.answer(text, reply_markup=kb)


def amount_label(amount: int) -> str:
    if amount >= 1_000_000 and amount % 1_000_000 == 0:
        return f"{amount // 1_000_000}M"
    return f"{amount // 1000}K"


def deposit_menu_content(bal: int):
    text = (
        f"{e('money2')} <b>NẠP TIỀN VÀO VÍ</b>\n"
        f"{SEP}\n"
        f"{e('wallet')} Số dư hiện tại: <b>{bal:,}đ</b>\n"
        f"{SEP}\n"
        f"{e('fast')} Chọn nhanh số tiền bên dưới hoặc bấm <b>Nhập số tiền khác</b>.\n"
        f"{e('card')} Bot sẽ tạo <b>mã QR</b> có sẵn số tiền &amp; nội dung chuyển khoản.\n"
        f"{e('warn')} Tối thiểu <b>{MIN_DEPOSIT:,}đ</b>."
    )
    rows, row = [], []
    for amt in QUICK_AMOUNTS:
        row.append(inline_btn(amount_label(amt), "money", f"dep:{amt}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([inline_btn("Nhập số tiền khác", "plus", "dep:custom")])
    rows.append([inline_btn("Menu Chính", "up", "home")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


@dp.message(F.text == BTN_DEPOSIT)
async def menu_deposit(message: types.Message, state: FSMContext):
    await state.clear()
    bal = await get_user_balance(message.from_user.id)
    text, kb = deposit_menu_content(bal)
    await message.answer(text, reply_markup=kb)


def parse_amount(raw: str) -> int | None:
    s = (raw or "").strip().lower().replace(" ", "").replace("đ", "").replace("vnd", "")
    m = re.fullmatch(r"(\d+(?:[.,]\d+)?)(k|m|tr|nghin|ngan)?", s)
    if not m:
        return None
    num, suffix = m.group(1), m.group(2)
    if suffix:
        mult = 1000 if suffix in ("k", "nghin", "ngan") else 1_000_000
        return int(round(float(num.replace(",", ".")) * mult))
    digits = re.sub(r"[.,]", "", num)
    return int(digits) if digits.isdigit() else None


def vietqr_url(amount: int, content: str) -> str:
    return (
        f"https://img.vietqr.io/image/{BANK_CODE}-{BANK_ACCOUNT_NO}-compact2.png"
        f"?amount={amount}&addInfo={quote(content)}&accountName={quote(BANK_ACCOUNT_NAME)}"
    )


def _download_vietqr_image(url: str) -> bytes:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; DepositQRBot/1.0)",
            "Accept": "image/png,image/jpeg,image/*,*/*;q=0.8",
        },
    )
    with urlopen(request, timeout=25) as response:
        raw_data = response.read(5 * 1024 * 1024 + 1)
        content_type = response.headers.get("Content-Type", "").lower()

    if not raw_data:
        raise ValueError("VietQR trả về dữ liệu rỗng")
    if len(raw_data) > 5 * 1024 * 1024:
        raise ValueError("Ảnh QR tải về vượt quá giới hạn 5 MB")

    image_bytes = raw_data
    looks_like_svg = (
        "image/svg" in content_type
        or raw_data.lstrip().startswith(b"<svg")
        or (raw_data.lstrip().startswith(b"<?xml") and b"<svg" in raw_data[:2048])
    )
    if looks_like_svg:
        try:
            image_bytes = cairosvg.svg2png(
                bytestring=raw_data,
                output_width=1080,
                output_height=1280,
            )
        except Exception as exc:
            raise ValueError(f"Không chuyển đổi được SVG VietQR sang PNG: {exc}") from exc

    try:
        with Image.open(BytesIO(image_bytes)) as source:
            source.load()
            image = source.convert("RGB")
    except Exception as exc:
        preview = raw_data[:120].decode("utf-8", errors="replace")
        raise ValueError(
            f"VietQR không trả về ảnh hợp lệ "
            f"(Content-Type: {content_type}; dữ liệu đầu: {preview})"
        ) from exc

    image.thumbnail((2000, 2000), Image.Resampling.LANCZOS)
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    png_data = output.getvalue()

    if not png_data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Không thể chuẩn hóa ảnh QR thành PNG")
    if len(png_data) > 10 * 1024 * 1024:
        raise ValueError("Ảnh QR sau chuẩn hóa vượt quá giới hạn Telegram")
    return png_data


async def send_deposit_qr(target: types.Message, uid: int, amount: int):
    content = f"{DEPOSIT_PREFIX} {uid}"
    caption = (
        f"{e('card')} <b>THÔNG TIN NẠP TIỀN</b>\n"
        f"{SEP}\n"
        f"{e('bank')} Ngân hàng: <b>{BANK_NAME}</b>\n"
        f"{e('user')} Chủ tài khoản: <b>{BANK_ACCOUNT_NAME}</b>\n"
        f"{e('link')} Số tài khoản: <code>{BANK_ACCOUNT_NO}</code>\n"
        f"{e('money')} Số tiền: <b>{amount:,}đ</b>\n"
        f"{e('pin')} Nội dung: <code>{escape(content)}</code>\n"
        f"{SEP}\n"
        f"{e('fast')} Quét mã QR để tự điền sẵn <b>số tiền &amp; nội dung</b>.\n"
        f"{e('warn')} Giữ <b>đúng nội dung chuyển khoản</b> để được cộng tiền.\n"
        f"{e('hourglass')} Chuyển xong bấm <b>Đã chuyển khoản</b> để báo Admin cộng tiền."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [inline_btn("Đã chuyển khoản", "ok", f"dep:paid:{amount}")],
        [inline_btn("Đổi số tiền", "reload", "dep:menu"), inline_btn("Menu Chính", "up", "home")],
    ])
    try:
        qr_data = await asyncio.to_thread(_download_vietqr_image, vietqr_url(amount, content))
        qr_file = types.BufferedInputFile(qr_data, filename=f"vietqr_{uid}_{amount}.png")
        await target.answer_photo(photo=qr_file, caption=caption, reply_markup=kb)
    except Exception as ex:
        print(f"Không tải/gửi được ảnh QR: {type(ex).__name__}: {ex}")
        await target.answer(
            caption + f"\n{e('no')} <i>Không tải được ảnh QR, vui lòng chuyển khoản thủ công theo thông tin trên.</i>",
            reply_markup=kb,
        )


@dp.callback_query(F.data.startswith("dep:"))
async def cb_deposit(call: types.CallbackQuery, state: FSMContext):
    parts = call.data.split(":")
    action = parts[1]
    uid = call.from_user.id

    if action == "menu":
        await state.clear()
        bal = await get_user_balance(uid)
        text, kb = deposit_menu_content(bal)
        await edit_or_send(call, text, kb)
        await call.answer()
        return

    if action == "custom":
        await state.set_state(BotStates.waiting_for_amount)
        await edit_or_send(
            call,
            f"{e('plus')} <b>NHẬP SỐ TIỀN NẠP</b>\n"
            f"{SEP}\n"
            f"{e('money')} Tối thiểu <b>{MIN_DEPOSIT:,}đ</b>, tối đa <b>{MAX_DEPOSIT:,}đ</b>.\n"
            f"{e('mail')} Gửi số tiền muốn nạp, ví dụ: <code>75000</code> hoặc <code>75k</code>",
            InlineKeyboardMarkup(inline_keyboard=[[inline_btn("Quay lại", "reload", "dep:menu")]]),
        )
        await call.answer()
        return

    if action == "paid":
        try:
            amount = int(parts[2])
        except (IndexError, ValueError):
            await call.answer()
            return
        last = paid_notify_at.get(uid, 0)
        if time.time() - last < 60:
            await call.answer("Đã gửi yêu cầu rồi, vui lòng chờ Admin xử lý.", show_alert=True)
            return
        paid_notify_at[uid] = time.time()
        u = call.from_user
        uname = f"@{escape(u.username)}" if u.username else "không có"
        try:
            await bot.send_message(
                ADMIN_ID,
                f"{e('bell')} <b>YÊU CẦU XÁC NHẬN NẠP TIỀN</b>\n"
                f"{SEP}\n"
                f"{e('user')} Khách: {escape(u.full_name or '')} ({uname})\n"
                f"{e('link')} ID: <code>{u.id}</code>\n"
                f"{e('money')} Số tiền: <b>{amount:,}đ</b>\n"
                f"{e('pin')} Nội dung: <code>{escape(DEPOSIT_PREFIX)} {u.id}</code>\n"
                f"{e('soon')} Thời gian: {now_str()}\n"
                f"{SEP}\n"
                f"Sau khi kiểm tra tiền về: <code>/nap {u.id} {amount}</code>",
            )
        except Exception as ex:
            print(f"Không báo được admin: {ex}")
        await call.answer("Đã gửi yêu cầu cho Admin, tiền sẽ được cộng sau khi kiểm tra.", show_alert=True)
        return

    try:
        amount = int(action)
    except ValueError:
        await call.answer()
        return
    if not MIN_DEPOSIT <= amount <= MAX_DEPOSIT:
        await call.answer("Số tiền không hợp lệ!", show_alert=True)
        return
    await state.clear()
    await send_deposit_qr(call.message, uid, amount)
    await call.answer()


@dp.message(BotStates.waiting_for_amount)
async def deposit_custom_amount(message: types.Message, state: FSMContext):
    raw = message.text or ""
    if raw.strip().startswith("/"):
        await message.answer(f"{e('no')} Số tiền không hợp lệ, nhập lại (ví dụ <code>75000</code>):")
        return
    amount = parse_amount(raw)
    if amount is None:
        await message.answer(f"{e('no')} Số tiền không hợp lệ, nhập lại (ví dụ <code>75000</code> hoặc <code>75k</code>):")
        return
    if amount < MIN_DEPOSIT:
        await message.answer(f"{e('no')} Nạp tối thiểu <b>{MIN_DEPOSIT:,}đ</b>, nhập lại:")
        return
    if amount > MAX_DEPOSIT:
        await message.answer(f"{e('no')} Nạp tối đa <b>{MAX_DEPOSIT:,}đ</b> mỗi lần, nhập lại:")
        return
    await state.clear()
    await send_deposit_qr(message, message.from_user.id, amount)


TX_LABELS = {
    "deposit": "Nạp tiền",
    "purchase": "Mua slot nhập code",
    "refund": "Hoàn tiền",
    "admin_sub": "Admin trừ tiền",
}


async def build_history(uid: int, page: int):
    async with db_pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM transactions WHERE user_id = $1", uid)
        pages = max(1, math.ceil(total / PAGE_SIZE))
        page = max(0, min(page, pages - 1))
        rows = await conn.fetch(
            "SELECT amount, type, note, created_at FROM transactions WHERE user_id = $1 "
            "ORDER BY id DESC LIMIT $2 OFFSET $3",
            uid, PAGE_SIZE, page * PAGE_SIZE,
        )
    lines = [
        f"{e('receipt')} <b>LỊCH SỬ GIAO DỊCH</b>",
        f"{SEP}",
    ]
    if not rows:
        lines.append(f"{e('no')} Bạn chưa có giao dịch nào.")
    else:
        lines.append(f"{e('chart')} Tổng cộng <b>{total}</b> giao dịch")
        lines.append("")
        for r in rows:
            amt = int(r["amount"])
            icon = e("plus") if amt >= 0 else e("down")
            sign = "+" if amt >= 0 else "-"
            label = TX_LABELS.get(r["type"], r["type"])
            note = f" · {escape(r['note'])}" if r["note"] else ""
            lines.append(f"{icon} <b>{sign}{abs(amt):,}đ</b> · {label}")
            lines.append(f"┗ {fmt_dt(r['created_at'])}{note}")
    return "\n".join(lines), page_kb("hist", page, pages)


@dp.message(F.text == BTN_HISTORY)
async def menu_history(message: types.Message, state: FSMContext):
    await state.clear()
    text, kb = await build_history(message.from_user.id, 0)
    await message.answer(text, reply_markup=kb)


@dp.callback_query(F.data.startswith("hist:"))
async def cb_history(call: types.CallbackQuery):
    page = int(call.data.split(":")[1])
    text, kb = await build_history(call.from_user.id, page)
    await edit_or_send(call, text, kb)
    await call.answer()


async def build_orders(uid: int, page: int):
    async with db_pool.acquire() as conn:
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM hunt_accounts WHERE user_id = $1 AND status = 'active'", uid
        )
        pages = max(1, math.ceil(total / PAGE_SIZE))
        page = max(0, min(page, pages - 1))
        rows = await conn.fetch(
            "SELECT game_username, game, created_at FROM hunt_accounts "
            "WHERE user_id = $1 AND status = 'active' ORDER BY id DESC LIMIT $2 OFFSET $3",
            uid, PAGE_SIZE, page * PAGE_SIZE,
        )
    lines = [
        f"{e('gift')} <b>ĐƠN HÀNG ĐANG CHỜ NHẬP CODE</b>",
        f"{SEP}",
    ]
    if not rows:
        lines.append(f"{e('no')} Bạn chưa có đơn hàng nào đang chờ nhập code.")
        lines.append(f"{e('fire')} Bấm <b>{BTN_CODE}</b> để mua slot nhập code.")
    else:
        lines.append(f"{e('reload')} Đang chờ: <b>{total}</b> đơn")
        lines.append("")
        now = datetime.now(timezone.utc)
        for idx, r in enumerate(rows, page * PAGE_SIZE + 1):
            game_name = GAMES.get(r["game"] or "78win", {}).get("name", "78WIN")
            created = r["created_at"] or now
            remain = created + timedelta(hours=ORDER_TIMEOUT_HOURS) - now
            mins = max(0, int(remain.total_seconds() // 60))
            lines.append(f"{e('reload')} <b>{idx}.</b> <code>{escape(r['game_username'])}</code>")
            lines.append(f"┗ {game_name} · đặt lúc {fmt_dt(created)} · còn {mins // 60}h{mins % 60:02d}p")
        lines.append("")
        lines.append(
            f"{e('hourglass')} <i>Quá {ORDER_TIMEOUT_HOURS}h chưa nhập code thành công sẽ tự huỷ &amp; hoàn tiền.</i>"
        )
    return "\n".join(lines), page_kb("ord", page, pages)


@dp.message(F.text == BTN_ORDERS)
async def menu_orders(message: types.Message, state: FSMContext):
    await state.clear()
    text, kb = await build_orders(message.from_user.id, 0)
    await message.answer(text, reply_markup=kb)


@dp.callback_query(F.data.startswith("ord:"))
async def cb_orders(call: types.CallbackQuery):
    page = int(call.data.split(":")[1])
    text, kb = await build_orders(call.from_user.id, page)
    await edit_or_send(call, text, kb)
    await call.answer()


@dp.message(F.text == BTN_SUPPORT)
async def menu_support(message: types.Message, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [url_btn("Nhóm Hỗ Trợ", "mega", f"https://t.me/{SUPPORT_GROUP}")],
        [url_btn("Admin Hỗ Trợ", "shield", f"https://t.me/{SUPPORT_ADMIN}")],
    ])
    await message.answer(
        f"{e('shield')} <b>HỖ TRỢ KHÁCH HÀNG</b>\n"
        f"{SEP}\n"
        f"{e('mega')} Nhóm hỗ trợ: @{SUPPORT_GROUP}\n"
        f"{e('user')} Admin hỗ trợ: @{SUPPORT_ADMIN}\n"
        f"{SEP}\n"
        f"{e('bulb')} Cần giúp đỡ về nạp tiền, đơn hàng hoặc nhập code, hãy liên hệ ngay!",
        reply_markup=kb,
    )


def game_list_content(bal: int):
    text = (
        f"{e('fire')} <b>NHẬP CODE</b>\n"
        f"{SEP}\n"
        f"{e('wallet')} Số dư: <b>{bal:,}đ</b>\n"
        f"{e('down')} Chọn game cần mua slot nhập code:"
    )
    rows = [
        [inline_btn(f"{g['name']}  •  {g['price']:,}đ", "game", f"game:{key}")]
        for key, g in GAMES.items()
    ]
    rows.append([inline_btn("Đóng", "no", "game:cancel")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


@dp.message(F.text == BTN_CODE)
async def menu_code(message: types.Message, state: FSMContext):
    await state.clear()
    bal = await get_user_balance(message.from_user.id)
    text, kb = game_list_content(bal)
    await message.answer(text, reply_markup=kb)


@dp.callback_query(F.data.startswith("game:"))
async def choose_game(call: types.CallbackQuery, state: FSMContext):
    key = call.data.split(":", 1)[1]
    if key == "cancel":
        await state.clear()
        await edit_or_send(call, f"{e('no')} Đã đóng.")
        await call.answer()
        return
    if key == "back":
        await state.clear()
        bal = await get_user_balance(call.from_user.id)
        text, kb = game_list_content(bal)
        await edit_or_send(call, text, kb)
        await call.answer()
        return

    game = GAMES.get(key)
    if not game:
        await call.answer("Game không tồn tại!", show_alert=True)
        return

    text = (
        f"{e('gem')} <b>Mệnh giá code: Random</b>\n"
        f"{e('game')} Game: <b>{game['name']}</b>\n"
        f"{e('money')} Giá bán: <b>{game['price']:,}đ</b> / tài khoản\n"
        f"{SEP}\n"
        f"{e('receipt')} <b>HƯỚNG DẪN MUA HÀNG:</b>\n"
        f"• Mua được nhiều nick cùng lúc.\n"
        f"• Mỗi nick nhập 1 dòng, gửi cho bot chỉ gửi tên nick.\n"
        f"{SEP}\n"
        f"{e('hourglass')} Đơn hàng sẽ được nhập code từ <b>1–{ORDER_TIMEOUT_HOURS}h</b>. "
        f"Quá <b>{ORDER_TIMEOUT_HOURS}h</b> nếu đơn hàng chưa được nhập code thành công sẽ "
        f"<b>tự động huỷ đơn và hoàn tiền</b>."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [inline_btn("Mua Ngay", "fire", f"buy:{key}")],
        [inline_btn("Quay lại", "reload", "game:back")],
    ])
    await edit_or_send(call, text, kb)
    await call.answer()


@dp.callback_query(F.data.startswith("buy:"))
async def buy_start(call: types.CallbackQuery, state: FSMContext):
    key = call.data.split(":", 1)[1]
    game = GAMES.get(key)
    if not game:
        await call.answer("Game không tồn tại!", show_alert=True)
        return

    bal = await get_user_balance(call.from_user.id)
    if bal < game["price"]:
        kb = InlineKeyboardMarkup(inline_keyboard=[[inline_btn("Nạp Tiền", "money", "dep:menu")]])
        await edit_or_send(
            call,
            f"{e('no')} <b>Số dư không đủ!</b>\n"
            f"{e('money')} Cần tối thiểu: <b>{game['price']:,}đ</b>\n"
            f"{e('wallet')} Số dư hiện tại: <b>{bal:,}đ</b>\n"
            f"{e('plus')} Bấm <b>Nạp Tiền</b> để nạp thêm.",
            kb,
        )
        await call.answer()
        return

    await state.clear()
    await state.update_data(game=key)
    await state.set_state(BotStates.waiting_for_username)
    await edit_or_send(
        call,
        f"{e('game')} Game: <b>{game['name']}</b>  •  {e('money')} <b>{game['price']:,}đ / tài khoản</b>\n"
        f"{SEP}\n"
        f"{e('mail')} Gửi <b>tên tài khoản</b> cần nhập code.\n"
        f"{e('plus')} Muốn mua nhiều nick, mỗi nick <b>một dòng</b> (tối đa {MAX_BATCH}), ví dụ:\n"
        f"<code>bolatienphong\nnoapq1983</code>",
    )
    await call.answer()


def parse_usernames(raw: str) -> list[str]:
    seen, names = set(), []
    for line in raw.splitlines():
        name = line.strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


@dp.message(BotStates.waiting_for_username)
async def buy_code_preview(message: types.Message, state: FSMContext):
    raw = message.text or ""
    if raw.strip() in MENU_TEXTS or raw.strip().startswith("/"):
        await message.answer(f"{e('no')} Tên tài khoản không hợp lệ, nhập lại:")
        return

    names = parse_usernames(raw)
    if not names:
        await message.answer(f"{e('no')} Tên tài khoản không được để trống, nhập lại:")
        return
    if len(names) > MAX_BATCH:
        await message.answer(f"{e('no')} Mỗi lần chỉ mua tối đa <b>{MAX_BATCH}</b> tài khoản, nhập lại:")
        return
    if any(len(n) > 50 for n in names):
        await message.answer(f"{e('no')} Có tên tài khoản quá dài (tối đa 50 ký tự), nhập lại:")
        return

    data = await state.get_data()
    game_key = data.get("game", "78win")
    game = GAMES.get(game_key, GAMES["78win"])
    price = game["price"]
    uid = message.from_user.id

    async with db_pool.acquire() as conn:
        busy_rows = await conn.fetch(
            "SELECT lower(game_username) AS u FROM hunt_accounts "
            "WHERE game = $1 AND status = 'active' AND lower(game_username) = ANY($2::text[])",
            game_key, [n.lower() for n in names],
        )
    busy = {r["u"] for r in busy_rows}
    rejected = [n for n in names if n.lower() in busy]
    valid = [n for n in names if n.lower() not in busy]
    bal = await get_user_balance(uid)

    rejected_text = ""
    if rejected:
        rejected_list = "\n".join(f"• <code>{escape(n)}</code>" for n in rejected)
        rejected_text = (
            f"\n{SEP}\n"
            f"{e('no')} <b>Bỏ qua ({len(rejected)})</b> - đang chờ nhập code:\n{rejected_list}"
        )

    if not valid:
        await state.clear()
        await message.answer(f"{e('no')} <b>Không thể đăng ký!</b>{rejected_text}")
        return

    total = price * len(valid)
    if bal < total:
        await state.clear()
        kb = InlineKeyboardMarkup(inline_keyboard=[[inline_btn("Nạp Tiền", "money", "dep:menu")]])
        await message.answer(
            f"{e('no')} <b>Số dư không đủ!</b>\n"
            f"{e('pc')} Số tài khoản hợp lệ: <b>{len(valid)}</b>\n"
            f"{e('money')} Cần: <b>{total:,}đ</b>\n"
            f"{e('wallet')} Số dư hiện tại: <b>{bal:,}đ</b>\n"
            f"{e('plus')} Bấm <b>Nạp Tiền</b> để nạp thêm."
            f"{rejected_text}",
            reply_markup=kb,
        )
        return

    await state.update_data(names=valid, game=game_key)
    await state.set_state(BotStates.confirm_order)
    valid_list = "\n".join(f"• <code>{escape(n)}</code>" for n in valid)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [inline_btn("Xác Nhận Mua", "ok", "order:confirm"), inline_btn("Hủy", "no", "order:cancel")],
    ])
    await message.answer(
        f"{e('receipt')} <b>THÔNG TIN ĐƠN HÀNG</b>\n"
        f"{SEP}\n"
        f"{e('game')} Game: <b>{game['name']}</b>\n"
        f"{e('gem')} Mệnh giá code: <b>Random</b>\n"
        f"{e('pc')} <b>Tài khoản ({len(valid)}):</b>\n{valid_list}\n"
        f"{SEP}\n"
        f"{e('money')} Đơn giá: <b>{price:,}đ</b> × {len(valid)}\n"
        f"{e('cash')} Tổng thanh toán: <b>{total:,}đ</b>\n"
        f"{e('wallet')} Số dư hiện tại: <b>{bal:,}đ</b>\n"
        f"{e('bag')} Số dư sau khi mua: <b>{bal - total:,}đ</b>\n"
        f"{SEP}\n"
        f"{e('hourglass')} Nhập code trong <b>1–{ORDER_TIMEOUT_HOURS}h</b>, quá hạn tự huỷ &amp; hoàn tiền."
        f"{rejected_text}\n\n"
        f"{e('down')} Bấm <b>Xác Nhận Mua</b> để thanh toán.",
        reply_markup=kb,
    )


async def process_purchase(user_id: int, game_key: str, names: list[str]) -> dict:
    game = GAMES.get(game_key, GAMES["78win"])
    price = game["price"]
    result = "ok"
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(78001)")
            row = await conn.fetchrow("SELECT balance FROM users WHERE user_id = $1 FOR UPDATE", user_id)
            bal = int(row["balance"]) if row else 0

            busy_rows = await conn.fetch(
                "SELECT lower(game_username) AS u FROM hunt_accounts "
                "WHERE game = $1 AND status = 'active' AND lower(game_username) = ANY($2::text[])",
                game_key, [n.lower() for n in names],
            )
            busy = {r["u"] for r in busy_rows}
            rejected = [n for n in names if n.lower() in busy]
            valid = [n for n in names if n.lower() not in busy]
            total = price * len(valid)

            if not valid:
                result = "all_busy"
            elif bal < total:
                result = "no_balance"
            else:
                await conn.execute("UPDATE users SET balance = balance - $1 WHERE user_id = $2", total, user_id)
                await conn.executemany(
                    "INSERT INTO hunt_accounts (user_id, game_username, status, game) VALUES ($1, $2, 'active', $3)",
                    [(user_id, n, game_key) for n in valid],
                )
                note = f"{game['name']} x{len(valid)}: " + ", ".join(valid)
                await add_tx(conn, user_id, -total, "purchase", note[:200])
    return {"result": result, "valid": valid, "rejected": rejected, "bal": bal, "total": total, "game": game}


@dp.callback_query(F.data == "order:cancel")
async def order_cancel(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await edit_or_send(call, f"{e('no')} Đã hủy đơn hàng.")
    await call.answer()


@dp.callback_query(F.data == "order:confirm")
async def order_confirm(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    names = data.get("names")
    game_key = data.get("game", "78win")
    await state.clear()
    if not names:
        await edit_or_send(call, f"{e('no')} Phiên mua hàng đã hết hạn, vui lòng bấm <b>{BTN_CODE}</b> để mua lại.")
        await call.answer()
        return

    r = await process_purchase(call.from_user.id, game_key, names)
    rejected_text = ""
    if r["rejected"]:
        rejected_list = "\n".join(f"• <code>{escape(n)}</code>" for n in r["rejected"])
        rejected_text = f"\n{SEP}\n{e('no')} <b>Không đăng ký được ({len(r['rejected'])})</b> - đang chờ nhập code:\n{rejected_list}"

    if r["result"] == "all_busy":
        await edit_or_send(call, f"{e('no')} <b>Không thể đăng ký!</b>{rejected_text}")
    elif r["result"] == "no_balance":
        kb = InlineKeyboardMarkup(inline_keyboard=[[inline_btn("Nạp Tiền", "money", "dep:menu")]])
        await edit_or_send(
            call,
            f"{e('no')} <b>Số dư không đủ!</b>\n"
            f"{e('money')} Cần: <b>{r['total']:,}đ</b>\n"
            f"{e('wallet')} Số dư hiện tại: <b>{r['bal']:,}đ</b>"
            f"{rejected_text}",
            kb,
        )
    else:
        valid_list = "\n".join(f"• <code>{escape(n)}</code>" for n in r["valid"])
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [inline_btn("Xem Đơn Hàng", "gift", "ord:0"), inline_btn("Menu Chính", "up", "home")],
        ])
        await edit_or_send(
            call,
            f"{e('ok')} <b>MUA SLOT THÀNH CÔNG!</b>\n"
            f"{SEP}\n"
            f"{e('game')} Game: <b>{r['game']['name']}</b>\n"
            f"{e('reload')} Trạng thái: <b>Đang chờ nhập code</b>\n"
            f"{e('pc')} <b>Tài khoản ({len(r['valid'])}):</b>\n{valid_list}\n"
            f"{SEP}\n"
            f"{e('money')} Đã trừ: <b>{r['total']:,}đ</b>\n"
            f"{e('wallet')} Số dư còn lại: <b>{r['bal'] - r['total']:,}đ</b>"
            f"{rejected_text}",
            kb,
        )
    await call.answer()


# =====================================================================
# TỰ ĐỘNG HUỶ ĐƠN QUÁ HẠN + HOÀN TIỀN
# =====================================================================
async def expire_old_orders():
    refunds: dict[int, list[tuple[str, int]]] = {}
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            rows = await conn.fetch(
                "UPDATE hunt_accounts SET status = 'expired' "
                "WHERE status = 'active' AND created_at < now() - ($1 * interval '1 hour') "
                "RETURNING user_id, game_username, game",
                ORDER_TIMEOUT_HOURS,
            )
            for r in rows:
                price = GAMES.get(r["game"] or "78win", GAMES["78win"])["price"]
                await get_user_balance_tx(conn, r["user_id"])
                await conn.execute("UPDATE users SET balance = balance + $1 WHERE user_id = $2", price, r["user_id"])
                await add_tx(conn, r["user_id"], price, "refund", f"Quá {ORDER_TIMEOUT_HOURS}h: {r['game_username']}"[:200])
                refunds.setdefault(r["user_id"], []).append((r["game_username"], price))

    for uid, items in refunds.items():
        total = sum(p for _, p in items)
        names = "\n".join(f"• <code>{escape(n)}</code>" for n, _ in items)
        try:
            await bot.send_message(
                uid,
                f"{e('hourglass')} <b>ĐƠN HÀNG QUÁ {ORDER_TIMEOUT_HOURS}H - TỰ ĐỘNG HUỶ</b>\n"
                f"{SEP}\n"
                f"{e('pc')} Tài khoản chưa nhập code thành công:\n{names}\n"
                f"{SEP}\n"
                f"{e('money')} Đã hoàn: <b>{total:,}đ</b> vào ví của bạn.",
            )
        except Exception:
            pass


async def get_user_balance_tx(conn, user_id: int):
    await conn.execute(
        "INSERT INTO users (user_id, balance) VALUES ($1, 0) ON CONFLICT (user_id) DO NOTHING", user_id
    )


async def expire_orders_loop():
    while True:
        try:
            await expire_old_orders()
        except Exception as ex:
            print(f"Lỗi quét đơn quá hạn: {ex}")
        await asyncio.sleep(600)


# =====================================================================
# ADMIN
# =====================================================================
@dp.message(Command("nap"))
async def admin_add_money(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        _, target_id, amount = message.text.split()
        target_id, amount = int(target_id), int(amount)
        await get_user_balance(target_id)
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE users SET balance = balance + $1, total_deposit = COALESCE(total_deposit, 0) + $1 "
                    "WHERE user_id = $2",
                    amount, target_id,
                )
                await add_tx(conn, target_id, amount, "deposit", "Nạp tiền vào ví")
        await message.answer(f"{e('ok')} Đã nạp <b>{amount:,}đ</b> cho <code>{target_id}</code>.")
        await bot.send_message(
            target_id,
            f"{e('money')} <b>NẠP TIỀN THÀNH CÔNG</b>\n"
            f"{SEP}\n"
            f"{e('cash')} Bạn được cộng <b>{amount:,}đ</b> vào ví!",
        )
    except Exception:
        await message.answer(f"{e('no')} Cú pháp: <code>/nap &lt;user_id&gt; &lt;so_tien&gt;</code>")


@dp.message(Command("hoan"))
async def admin_refund_money(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        _, target_id, amount = message.text.split()
        target_id, amount = int(target_id), int(amount)
        await get_user_balance(target_id)
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("UPDATE users SET balance = balance + $1 WHERE user_id = $2", amount, target_id)
                await add_tx(conn, target_id, amount, "refund", "Admin hoàn tiền")
        await message.answer(f"{e('ok')} Đã hoàn <b>{amount:,}đ</b> cho <code>{target_id}</code>.")
        await bot.send_message(target_id, f"{e('money')} Bạn được hoàn <b>{amount:,}đ</b> vào ví!")
    except Exception:
        await message.answer(f"{e('no')} Cú pháp: <code>/hoan &lt;user_id&gt; &lt;so_tien&gt;</code>")


@dp.message(Command("tru"))
async def admin_sub_money(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        _, target_id, amount = message.text.split()
        target_id, amount = int(target_id), int(amount)
        await get_user_balance(target_id)
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                old = await conn.fetchval("SELECT balance FROM users WHERE user_id = $1 FOR UPDATE", target_id)
                taken = min(int(old or 0), amount)
                await conn.execute("UPDATE users SET balance = balance - $1 WHERE user_id = $2", taken, target_id)
                if taken:
                    await add_tx(conn, target_id, -taken, "admin_sub", "Admin trừ tiền")
        await message.answer(f"{e('ok')} Đã trừ <b>{taken:,}đ</b> của <code>{target_id}</code>.")
    except Exception:
        await message.answer(f"{e('no')} Cú pháp: <code>/tru &lt;user_id&gt; &lt;so_tien&gt;</code>")


@dp.message(Command("huy"))
async def admin_cancel_order(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer(f"{e('no')} Cú pháp: <code>/huy &lt;ten_tai_khoan&gt;</code>")
        return
    name = parts[1].strip()
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "UPDATE hunt_accounts SET status = 'cancelled' "
            "WHERE lower(game_username) = lower($1) AND status = 'active' "
            "RETURNING user_id, game_username",
            name,
        )
    if not rows:
        await message.answer(f"{e('no')} Không có đơn nào đang chờ nhập code của <code>{escape(name)}</code>.")
        return
    await message.answer(
        f"{e('ok')} Đã hủy đơn <code>{escape(name)}</code>. "
        f"Cần hoàn tiền thì dùng <code>/hoan &lt;user_id&gt; &lt;so_tien&gt;</code>."
    )
    for r in rows:
        try:
            await bot.send_message(
                r["user_id"],
                f"{e('no')} Đơn nhập code của tài khoản <code>{escape(r['game_username'])}</code> "
                f"đã bị Admin hủy.",
            )
        except Exception:
            pass


@dp.message(Command("thongke"))
async def admin_stats(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    async with db_pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
        active_accs = await conn.fetchval("SELECT COUNT(*) FROM hunt_accounts WHERE status = 'active'")
    scanner_status = (
        f"{e('ok')} Đang chạy" if (userbot and userbot.is_connected()) else f"{e('no')} Chưa đăng nhập (/login)"
    )
    await message.answer(
        f"{e('top')} <b>THỐNG KÊ</b>\n"
        f"{SEP}\n"
        f"{e('pc')} Bộ quét nhóm: {scanner_status}\n"
        f"{e('shield')} Người dùng: <b>{total_users}</b>\n"
        f"{e('reload')} Tài khoản chờ nhập code: <b>{active_accs}</b>"
    )


# =====================================================================
# LỌC CODE 6 KÝ TỰ (TIN NHẮN & VIDEO)
# =====================================================================
def extract_clean_codes(raw_text: str) -> list[str]:
    """
    Lọc các chuỗi code có ký tự rác xen kẽ (ví dụ NrTs.WA@, hfAh!RE#, uJRJ.RC@),
    xóa hết ký tự đặc biệt / gạch ngang / gạch chéo, chỉ giữ lại chữ hoa, chữ thường và số
    có độ dài đúng 6 ký tự.
    """
    clean_codes = []
    for w in (raw_text or "").split():
        if w.startswith(("http", "#", "@")):
            continue
        # Chỉ nhận các cụm có chứa ký tự đặc biệt xen kẽ chữ/số (tránh nhận nhầm chữ bình thường như 'TẶNG', 'MỖI')
        if re.search(r"[^a-zA-Z0-9]", w) and re.search(r"[a-zA-Z0-9]", w):
            cleaned = re.sub(r"[^a-zA-Z0-9]", "", w)
            if len(cleaned) == 6:
                clean_codes.append(cleaned)
    return list(dict.fromkeys(clean_codes))


def _ocr_video_frame_sync(img_path: str) -> str:
    """Cắt vùng bên trái video (nơi hiển thị dãy code) và tăng tương phản để OCR đọc chuẩn."""
    with Image.open(img_path) as im:
        im = im.convert("L")
        w, h = im.size
        # Cắt 45% bên trái màn hình video, bỏ 15% mép trên và 18% mép dưới (banner chữ vàng)
        crop_box = (0, int(h * 0.15), int(w * 0.45), int(h * 0.82))
        cropped = im.crop(crop_box)
        cw, ch = cropped.size
        cropped = cropped.resize((cw * 2, ch * 2), Image.Resampling.LANCZOS)
        cropped = ImageEnhance.Contrast(cropped).enhance(2.2)

        # Cắt ngang làm 5 dải để ddddocr đọc từng dòng code chính xác hơn
        lines_text = []
        step = ch * 2 // 5
        for i in range(5):
            strip = cropped.crop((0, i * step, cw * 2, (i + 1) * step))
            buf = BytesIO()
            strip.save(buf, format="PNG")
            txt = ocr.classification(buf.getvalue())
            if txt:
                lines_text.append(txt)
        return " ".join(lines_text)


def _extract_codes_from_video_file(video_path: str, temp_dir: str) -> list[str]:
    """Dùng ffmpeg trích xuất khung hình mỗi 1 giây và quét code 6 ký tự."""
    frame_pattern = os.path.join(temp_dir, "frame_%03d.png")
    subprocess.run(
        ["ffmpeg", "-i", video_path, "-vf", "fps=1", "-vframes", "25", frame_pattern],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    found_codes = []
    for frame_file in sorted(glob.glob(os.path.join(temp_dir, "frame_*.png"))):
        raw_ocr = _ocr_video_frame_sync(frame_file)
        for c in extract_clean_codes(raw_ocr):
            if c not in found_codes:
                found_codes.append(c)
    return found_codes


async def extract_codes_from_video_message(message) -> list[str]:
    """Tải video từ Telegram về thư mục tạm, tách khung hình và lọc code 6 ký tự."""
    with tempfile.TemporaryDirectory() as tmpdir:
        video_path = os.path.join(tmpdir, "code_video.mp4")
        await message.download_media(file=video_path)
        if not os.path.exists(video_path):
            return []
        return await asyncio.to_thread(_extract_codes_from_video_file, video_path, tmpdir)


def _ocr_sync(img_bytes: bytes) -> str:
    img = Image.open(BytesIO(img_bytes)).convert("L")
    w, h = img.size
    img = img.resize((w * 3, h * 3), Image.Resampling.LANCZOS)
    img = ImageEnhance.Contrast(img).enhance(1.8)
    buf = BytesIO()
    img.save(buf, format="PNG")
    text = ocr.classification(buf.getvalue())
    return re.sub(r"[^a-zA-Z0-9]", "", text)


async def doc_captcha(img_bytes: bytes) -> str:
    return await asyncio.to_thread(_ocr_sync, img_bytes)


async def refresh_captcha_image(page, captcha_img, captcha_input):
    refresh_btn = page.locator('button:has-text("Làm mới ảnh")')
    if await refresh_btn.count() > 0:
        await refresh_btn.first.click()
    else:
        await captcha_img.click()
    await page.wait_for_timeout(1000)
    if not await captcha_input.is_visible():
        await page.click('button:has-text("KIỂM TRA")')
        await captcha_input.wait_for(state="visible", timeout=8000)


async def get_page_notice(page) -> str:
    try:
        for sel in ('[role="alert"]', ".swal2-html-container", ".toast", ".alert", ".notification"):
            loc = page.locator(sel)
            if await loc.count() > 0:
                txt = re.sub(r"\s+", " ", (await loc.first.inner_text()).strip())
                if txt:
                    return txt[:200]
        body = re.sub(r"\s+", " ", await page.inner_text("body")).strip()
        return body[-200:]
    except Exception:
        return ""


async def thu_mot_code(page, code: str, game_username: str, max_captcha_retry: int = 4) -> tuple[str, str]:
    await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=20000)
    await page.fill('input[placeholder*="Nhập code"]', code)
    await page.fill('input[placeholder*="Nhập tài khoản"]', game_username)
    await page.click('button:has-text("KIỂM TRA")')

    captcha_input = page.locator('input[placeholder*="Nhập mã captcha"]')
    await captcha_input.wait_for(state="visible", timeout=8000)

    captcha_img = page.locator('img[src*="captcha"], canvas').first
    if await captcha_img.count() == 0:
        captcha_img = page.locator("img").nth(1)

    for _ in range(max_captcha_retry):
        img_bytes = await captcha_img.screenshot()
        captcha_text = await doc_captcha(img_bytes)

        if not captcha_text:
            await refresh_captcha_image(page, captcha_img, captcha_input)
            continue

        await captcha_input.fill(captcha_text)
        await page.click('button:has-text("Xác thực")')
        await page.wait_for_timeout(1500)

        body_text = (await page.inner_text("body")).lower()
        if "thành công" in body_text or "nhận được" in body_text or "cộng" in body_text:
            notice = await get_page_notice(page)
            return "SUCCESS", f"Web báo nhập code thành công. Phản hồi: {notice}" if notice else "Web báo nhập code thành công"

        if "captcha" in body_text or "mã xác thực" in body_text or "không đúng" in body_text:
            await refresh_captcha_image(page, captcha_img, captcha_input)
            continue

        notice = await get_page_notice(page)
        return "FAIL", f"Code không hợp lệ / hết lượt / đã được dùng. Phản hồi web: {notice}"

    return "FAIL", f"Giải captcha sai sau {max_captcha_retry} lần thử"


async def report_attempt_to_admin(code: str, game_username: str, owner_id: int, ok: bool, note: str):
    head = (
        f"{e('ok')} <b>NHẬP CODE THÀNH CÔNG</b>" if ok else f"{e('no')} <b>NHẬP CODE THẤT BẠI</b>"
    )
    text = (
        f"{head}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{e('pc')} Tài khoản: <code>{escape(game_username)}</code>\n"
        f"{e('new')} Mã code nhập: <code>{escape(code)}</code>\n"
        f"{e('shield')} Chủ đơn: <code>{owner_id}</code>\n"
        f"{e('mail')} Ghi chú: {escape(note)}\n"
        f"{e('soon')} Thời gian: {now_str()}"
    )
    try:
        await bot.send_message(ADMIN_ID, text)
    except Exception as ex:
        print(f"Không gửi được báo cáo cho admin: {ex}")


async def chay_nhap_code_cho_tai_khoan(codes: list[str], game_username: str, owner_id: int) -> str | None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            for code in codes:
                try:
                    status, note = await thu_mot_code(page, code, game_username)
                except Exception as ex:
                    status, note = "FAIL", f"Lỗi khi nhập: {ex}"

                ok = status == "SUCCESS"
                await report_attempt_to_admin(code, game_username, owner_id, ok, note)
                if ok:
                    return code
            return None
        finally:
            await browser.close()


async def dispatch_codes_to_accounts(codes: list[str], source_label: str):
    """Gửi bộ code vừa quét được (từ tin nhắn hoặc video) vào tất cả tài khoản đang chờ."""
    if not codes:
        return

    try:
        code_list_str = ", ".join(f"<code>{escape(c)}</code>" for c in codes)
        await bot.send_message(
            ADMIN_ID,
            f"{e('fast')} <b>QUÉT ĐƯỢC CODE MỚI ({escape(source_label)})</b>\n"
            f"{SEP}\n"
            f"{e('new')} Danh sách ({len(codes)} mã): {code_list_str}",
        )
    except Exception:
        pass

    async with db_pool.acquire() as conn:
        accounts = await conn.fetch(
            "SELECT id, user_id, game_username FROM hunt_accounts WHERE status = 'active'"
        )

    for acc in accounts:
        record_id = acc["id"]
        owner_id = acc["user_id"]
        game_user = acc["game_username"]

        try:
            won_code = await chay_nhap_code_cho_tai_khoan(codes, game_user, owner_id)
            if won_code:
                async with db_pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE hunt_accounts SET status = 'done' WHERE id = $1 AND status = 'active'",
                        record_id,
                    )
                msg = (
                    f"{e('fire')} <b>NHẬP CODE THÀNH CÔNG!</b> {e('top')}\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"{e('pc')} Tài khoản: <code>{escape(game_user)}</code>\n"
                    f"{e('new')} Mã code: <code>{escape(won_code)}</code>"
                )
                if owner_id != ADMIN_ID:
                    await bot.send_message(owner_id, msg)
            else:
                await bot.send_message(
                    owner_id,
                    f"{e('soon')} Đợt code hiện tại chưa khớp cho <code>{escape(game_user)}</code>.\n"
                    f"{e('reload')} Hệ thống tiếp tục giữ tài khoản ở trạng thái "
                    f"<b>đang chờ nhập code</b> cho đợt code tiếp theo.",
                )
        except Exception as ex:
            print(f"Lỗi nhập code cho {game_user}: {ex}")
            try:
                await bot.send_message(
                    ADMIN_ID,
                    f"{e('no')} <b>LỖI HỆ THỐNG</b> khi nhập code cho <code>{escape(game_user)}</code>:\n"
                    f"<code>{escape(str(ex))}</code>",
                )
            except Exception:
                pass


# =====================================================================
# QUÉT NHÓM LIÊN TỤC (TIN NHẮN + VIDEO)
# =====================================================================
async def start_scanner(session_str: str):
    global userbot
    if userbot and userbot.is_connected():
        await userbot.disconnect()

    userbot = TelegramClient(StringSession(session_str), API_ID, API_HASH)

    # 1. Nhóm FreeCode_78win -> Chỉ quét video gửi lên
    @userbot.on(events.NewMessage(chats=VIDEO_TARGET_GROUPS))
    async def video_scanner_handler(event):
        if not event.message or not event.message.video:
            return
        try:
            codes = await extract_codes_from_video_message(event.message)
            if codes:
                await dispatch_codes_to_accounts(codes, "Video FreeCode_78win")
        except Exception as ex:
            print(f"Lỗi quét video FreeCode_78win: {ex}")

    # 2. Nhóm official78wins -> Chỉ quét tin nhắn văn bản
    @userbot.on(events.NewMessage(chats=TEXT_TARGET_GROUPS))
    async def text_scanner_handler(event):
        if not event.raw_text:
            return
        codes = extract_clean_codes(event.raw_text)
        if codes:
            await dispatch_codes_to_accounts(codes, "Tin nhắn official78wins")

    await userbot.connect()
    if await userbot.is_user_authorized():
        await bot.send_message(ADMIN_ID, f"{e('ok')} Bộ quét nhóm Telegram đã hoạt động! {e('fast')}")
        await userbot.run_until_disconnected()
    else:
        await bot.send_message(
            ADMIN_ID,
            f"{e('lock')} Phiên đăng nhập hết hạn. Gõ <code>/login</code> để đăng nhập lại.",
        )


async def main():
    await init_db()
    background_tasks.append(asyncio.create_task(expire_orders_loop()))
    saved_session = await get_saved_session()
    if saved_session:
        background_tasks.append(asyncio.create_task(start_scanner(saved_session)))
    else:
        try:
            await bot.send_message(
                ADMIN_ID,
                f"{e('lock')} Chưa đăng nhập nick quét nhóm. Gõ <code>/login</code> để lấy OTP đăng nhập.",
            )
        except Exception:
            pass
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
