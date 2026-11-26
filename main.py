import asyncio
import glob
import math
import os
import re
import subprocess
import tempfile
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from html import escape
from io import BytesIO
from urllib.parse import quote
from urllib.request import Request, urlopen

import asyncpg
import cairosvg
import ddddocr
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
from PIL import Image, ImageEnhance
from playwright.async_api import async_playwright
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, PhoneNumberInvalidError, SessionPasswordNeededError
from telethon.sessions import StringSession

# =====================================================================
# CẤU HÌNH
# =====================================================================
API_ID = int(os.getenv("API_ID", "30309186"))
API_HASH = os.getenv("API_HASH", "307273bc278e53017b5fdcd407c1d941")
PHONE_NUMBER = os.getenv("PHONE_NUMBER", "+84335442999")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise RuntimeError("Thiếu biến môi trường BOT_TOKEN trên Railway!")

ADMIN_ID = int(os.getenv("ADMIN_ID", "9220244280"))
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Phân loại nhóm quét
TEXT_TARGET_GROUPS = ["official78wins", "thongbaocvx"]
VIDEO_TARGET_GROUPS = ["FreeCode_78win"]
ALL_TARGET_GROUPS = TEXT_TARGET_GROUPS + VIDEO_TARGET_GROUPS

TARGET_URL = "https://code78k.online/"
CODE_PRICE = 10000
MAX_BATCH = 30
ORDER_TIMEOUT_HOURS = 72
PAGE_SIZE = 8
WARM_TAB_COUNT = int(os.getenv("WARM_TAB_COUNT", "24"))  # tổng số tab mở sẵn (RAM yếu thì giảm xuống)
REPLICAS_PER_CODE = int(os.getenv("REPLICAS_PER_CODE", "4"))  # số tab cùng nhập 1 code cho 1 tài khoản (dự phòng sai captcha)
SPARE_TAB_COUNT = int(os.getenv("SPARE_TAB_COUNT", "0"))  # tab dự phòng luôn mở sẵn, đặt 0 nếu thiếu RAM

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
login_phone_code_hash: str | None = None
background_tasks: list[asyncio.Task] = []
paid_notify_at: dict[int, float] = {}

# Pool tab trình duyệt mở sẵn tới trang nhập code
_playwright_ctx = None
_shared_browser = None
_tab_queue: asyncio.Queue | None = None
_pool_lock = asyncio.Lock()
_in_use = 0  # số tab của pool đang được mượn
_tab_refreshed: dict = {}  # tab -> thời điểm nạp lại trang gần nhất
_tab_sem: asyncio.Semaphore | None = None  # giới hạn số tab chạy đồng thời trên toàn bot
_inflight_codes: set[str] = set()          # code đang có tab nhập, tránh 2 tab nhập trùng 1 code
_dead_codes: dict[str, float] = {}  # code web báo sai/hết hạn -> thời điểm, bỏ qua cho mọi tài khoản
_fire_tasks: set = set()
TAB_MAX_AGE = 240  # tab đứng yên quá số giây này sẽ được nạp lại để luôn "tươi"
DEAD_CODE_TTL = 120
DEAD_CODE_RX = re.compile(r"mã code không đúng|code .*hết (lượt|hạn)|code .*đã (được )?sử dụng", re.I)


def _get_tab_sem() -> asyncio.Semaphore:
    global _tab_sem
    if _tab_sem is None:
        _tab_sem = asyncio.Semaphore(max(1, WARM_TAB_COUNT))
    return _tab_sem


def fire(coro):
    """Chạy nền (không chặn luồng nhập code), giữ tham chiếu để task không bị dọn mất."""
    t = asyncio.create_task(coro)
    _fire_tasks.add(t)
    t.add_done_callback(_fire_tasks.discard)
    return t


def mark_dead(code: str):
    _dead_codes[code] = time.time()


def is_dead(code: str) -> bool:
    ts = _dead_codes.get(code)
    if ts is None:
        return False
    if time.time() - ts > DEAD_CODE_TTL:
        _dead_codes.pop(code, None)
        return False
    return True


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
EXIT_WORDS = {"thoát", "thoat", "hủy", "huy", "cancel", "exit", "quit", "đóng", "dong"}

main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [kb_btn(BTN_CODE, "fire"), kb_btn(BTN_ACCOUNT, "user")],
        [kb_btn(BTN_DEPOSIT, "money"), kb_btn(BTN_HISTORY, "receipt")],
        [kb_btn(BTN_ORDERS, "gift"), kb_btn(BTN_SUPPORT, "shield")],
    ],
    resize_keyboard=True,
)

SEP = "━━━━━━━━━━━━━━━━━━"


def clean_text(raw: str | None) -> str:
    """Xoá ký tự điều khiển, khoảng trắng thừa và chuẩn hoá dấu câu."""
    if not raw:
        return ""
    s = re.sub(r"[\x00-\x1f\x7f\u200b-\u200f\ufeff]", " ", raw)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s+([.,!?;:])", r"\1", s)
    return s


def is_exit_text(raw: str | None) -> bool:
    return clean_text(raw).lower() in EXIT_WORDS


def is_menu_or_command_text(raw: str | None) -> bool:
    s = clean_text(raw)
    return s in MENU_TEXTS or s.startswith("/")


def now_str() -> str:
    return datetime.now(VN_TZ).strftime("%H:%M:%S %d/%m/%Y")


def fmt_dt(dt: datetime) -> str:
    return dt.astimezone(VN_TZ).strftime("%H:%M %d/%m/%Y")


async def _cleanup_temp_login():
    global temp_login_client, login_phone_code_hash
    login_phone_code_hash = None
    if temp_login_client:
        try:
            if temp_login_client.is_connected():
                await temp_login_client.disconnect()
        except Exception:
            pass
        temp_login_client = None


async def exit_state_to_home(message: types.Message, state: FSMContext, reason: str = "Đã thoát thao tác."):
    await state.clear()
    await _cleanup_temp_login()
    bal = await get_user_balance(message.from_user.id)
    await message.answer(f"{e('ok')} {escape(reason)}\n\n" + home_text(bal), reply_markup=main_kb)


@dp.callback_query(F.data == "state:exit")
async def cb_exit_state(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await _cleanup_temp_login()
    bal = await get_user_balance(call.from_user.id)
    await call.message.answer(f"{e('ok')} Đã thoát thao tác hiện tại.\n\n" + home_text(bal), reply_markup=main_kb)
    await call.answer("Đã thoát")


# =====================================================================
# QUẢN LÝ POOL TAB TRÌNH DUYỆT MỞ SẴN TRANG NHẬP CODE
# =====================================================================
async def _prepare_page_on_target(page, timeout: int = 15000):
    if page.url.rstrip("/") != TARGET_URL.rstrip("/"):
        await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=timeout)
    else:
        await page.reload(wait_until="domcontentloaded", timeout=timeout)
    _tab_refreshed[page] = time.time()


async def _create_warm_page(browser, timeout: int = 15000):
    page = await browser.new_page()
    await _prepare_page_on_target(page, timeout=timeout)
    return page


async def init_browser_pool(tab_count: int = WARM_TAB_COUNT):
    global _playwright_ctx, _shared_browser, _tab_queue, _in_use
    async with _pool_lock:
        if _tab_queue is None:
            _tab_queue = asyncio.Queue()
        if _playwright_ctx is None:
            _playwright_ctx = await async_playwright().start()
        if _shared_browser is None or not _shared_browser.is_connected():
            _shared_browser = await _playwright_ctx.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--disable-extensions",
                      "--disable-background-networking", "--mute-audio"],
            )
            _in_use = 0
            _tab_refreshed.clear()
            while not _tab_queue.empty():
                try:
                    _tab_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
        target_total = max(1, tab_count) + max(0, SPARE_TAB_COUNT)
        current_total = _tab_queue.qsize() + _in_use
        need = max(0, target_total - current_total)

        async def _make_tab():
            try:
                pg = await _create_warm_page(_shared_browser, timeout=15000)
                await _tab_queue.put(pg)
            except Exception as ex:
                print(f"Không mở sẵn được tab trình duyệt: {ex}")

        for i in range(0, need, 10):  # mở song song từng đợt 10 tab cho nhanh
            await asyncio.gather(*(_make_tab() for _ in range(min(10, need - i))))


async def borrow_warm_page():
    """Lấy một tab đã mở sẵn trang nhập code từ pool; nếu đang bận hết thì chờ tab rảnh (tối đa 8s)."""
    global _in_use
    try:
        if _tab_queue is None or _shared_browser is None or not _shared_browser.is_connected():
            await init_browser_pool(WARM_TAB_COUNT)
        while True:
            try:
                page = _tab_queue.get_nowait()
            except asyncio.QueueEmpty:
                try:
                    page = await asyncio.wait_for(_tab_queue.get(), timeout=8)
                except asyncio.TimeoutError:
                    break
            if page and not page.is_closed():
                _in_use += 1
                return page, True
    except Exception:
        pass
    if _shared_browser and _shared_browser.is_connected():
        page = await _create_warm_page(_shared_browser, timeout=15000)
        return page, False
    return None, False


async def return_warm_page(page, from_pool: bool):
    """Nạp lại trang nhập code sẵn cho lượt tiếp theo và trả tab về pool."""
    global _in_use
    if from_pool:
        _in_use = max(0, _in_use - 1)
    if not page or page.is_closed():
        return
    if not from_pool or _tab_queue is None:
        try:
            await page.close()
        except Exception:
            pass
        return
    try:
        await _prepare_page_on_target(page, timeout=12000)
        await _tab_queue.put(page)
    except Exception:
        try:
            await page.close()
        except Exception:
            pass
        if _shared_browser and _shared_browser.is_connected():
            try:
                fresh = await _create_warm_page(_shared_browser, timeout=12000)
                await _tab_queue.put(fresh)
            except Exception:
                pass


async def _reload_and_return(page):
    try:
        await _prepare_page_on_target(page, timeout=12000)
        await _tab_queue.put(page)
    except Exception:
        _tab_refreshed.pop(page, None)
        try:
            await page.close()
        except Exception:
            pass


async def _keepalive_tabs():
    """Tab khoẻ trả lại pool ngay; mỗi vòng chỉ nạp lại tối đa 8 tab cũ để pool không bị cạn."""
    if _tab_queue is None:
        return
    pages = []
    for _ in range(_tab_queue.qsize()):
        try:
            pages.append(_tab_queue.get_nowait())
        except asyncio.QueueEmpty:
            break
    to_reload = []
    for page in pages:
        if page.is_closed():
            _tab_refreshed.pop(page, None)
            continue
        stale = time.time() - _tab_refreshed.get(page, 0) > TAB_MAX_AGE
        if stale and len(to_reload) < 8:
            to_reload.append(page)
        else:
            await _tab_queue.put(page)
    if to_reload:
        await asyncio.gather(*(_reload_and_return(p) for p in to_reload))


async def warm_pool_loop():
    """Giữ pool tab trình duyệt bật sẵn 24/24: tự mở bù tab thiếu, tự làm mới tab cũ/chết."""
    while True:
        try:
            await init_browser_pool(WARM_TAB_COUNT)
            await _keepalive_tabs()
            await init_browser_pool(WARM_TAB_COUNT)
        except Exception as ex:
            print(f"Lỗi duy trì pool tab: {ex}")
        await asyncio.sleep(30)


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
        user_id, amount, tx_type, clean_text(note),
    )


# =====================================================================
# ADMIN: ĐĂNG NHẬP USERBOT (HỖ TRỢ GỬI LẠI / SMS OTP + NÚT THOÁT)
# =====================================================================
async def _request_login_code(message: types.Message, state: FSMContext, force_sms: bool = False):
    global temp_login_client, login_phone_code_hash
    try:
        if temp_login_client and temp_login_client.is_connected():
            await temp_login_client.disconnect()
        temp_login_client = TelegramClient(StringSession(), API_ID, API_HASH)
        await temp_login_client.connect()

        if force_sms and login_phone_code_hash:
            sent = await temp_login_client.send_code_request(PHONE_NUMBER, force_sms=True)
        else:
            sent = await temp_login_client.send_code_request(PHONE_NUMBER)

        login_phone_code_hash = getattr(sent, "phone_code_hash", None)
        delivery_type = type(getattr(sent, "type", None)).__name__ if getattr(sent, "type", None) else "app/sms"

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [inline_btn("Gửi lại qua SMS", "reload", "login:sms"), inline_btn("Gửi lại mã mới", "mail", "login:resend")],
            [inline_btn("Thoát", "no", "state:exit")],
        ])
        await message.answer(
            f"{e('mail')} Đã yêu cầu gửi mã OTP ({escape(delivery_type)}) tới SĐT <code>{escape(PHONE_NUMBER)}</code>.\n"
            f"{e('lock')} Hãy nhập mã OTP vào đây (có thể thêm chữ <code>a</code> phía trước, ví dụ: <code>a12345</code>).\n"
            f"{e('bulb')} Muốn huỷ và dùng chức năng khác, bấm <b>Thoát</b> hoặc gõ <code>thoát</code>.",
            reply_markup=kb,
        )
        await state.set_state(BotStates.waiting_for_otp)
    except FloodWaitError as fw:
        await state.clear()
        await message.answer(
            f"{e('warn')} Telegram đang giới hạn gửi mã (FloodWait): vui lòng đợi <b>{fw.seconds} giây</b> rồi thử lại <code>/login</code>."
        )
    except PhoneNumberInvalidError:
        await state.clear()
        await message.answer(
            f"{e('no')} Số điện thoại <code>{escape(PHONE_NUMBER)}</code> không hợp lệ trên Telegram. Kiểm tra biến <code>PHONE_NUMBER</code>."
        )
    except Exception as ex:
        await state.clear()
        await message.answer(f"{e('no')} Lỗi gửi OTP: <code>{escape(clean_text(str(ex)))}</code>")


@dp.message(Command("login"))
async def admin_login_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await _request_login_code(message, state, force_sms=False)


@dp.callback_query(F.data.startswith("login:"))
async def cb_login_retry(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        await call.answer()
        return
    action = call.data.split(":", 1)[1]
    await call.answer("Đang gửi lại yêu cầu mã...")
    await _request_login_code(call.message, state, force_sms=(action == "sms"))


@dp.message(BotStates.waiting_for_otp)
async def admin_login_otp(message: types.Message, state: FSMContext):
    global temp_login_client, login_phone_code_hash
    if message.from_user.id != ADMIN_ID:
        return
    raw_text = (message.text or "").strip()
    if is_exit_text(raw_text):
        await exit_state_to_home(message, state, "Đã thoát đăng nhập OTP.")
        return
    if raw_text.startswith("/login"):
        await _request_login_code(message, state, force_sms=False)
        return
    if is_menu_or_command_text(raw_text):
        await state.clear()
        await _cleanup_temp_login()
        await dp.feed_update(bot, types.Update(update_id=message.message_id, message=message))
        return

    otp = re.sub(r"\D", "", raw_text)
    if not otp:
        kb = InlineKeyboardMarkup(inline_keyboard=[[inline_btn("Thoát", "no", "state:exit")]])
        await message.answer(
            f"{e('no')} Mã OTP không hợp lệ, nhập lại (ví dụ <code>12345</code> hoặc <code>a12345</code>) hoặc bấm <b>Thoát</b>:",
            reply_markup=kb,
        )
        return
    try:
        if not temp_login_client or not temp_login_client.is_connected():
            await _request_login_code(message, state, force_sms=False)
            return

        await temp_login_client.sign_in(
            phone=PHONE_NUMBER,
            code=otp,
            phone_code_hash=login_phone_code_hash,
        )
        session_str = temp_login_client.session.save()
        await save_session(session_str)
        await state.clear()
        await _cleanup_temp_login()
        await message.answer(
            f"{e('ok')} Đăng nhập nick quét thành công và đã lưu vào PostgreSQL!\n"
            f"{e('reload')} Đang khởi động bộ quét..."
        )
        asyncio.create_task(start_scanner(session_str))
    except SessionPasswordNeededError:
        kb = InlineKeyboardMarkup(inline_keyboard=[[inline_btn("Thoát", "no", "state:exit")]])
        await message.answer(
            f"{e('lock')} Nick có bật mật khẩu 2 bước (2FA). Vui lòng nhập mật khẩu hoặc bấm <b>Thoát</b>:",
            reply_markup=kb,
        )
        await state.set_state(BotStates.waiting_for_2fa)
    except Exception as ex:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [inline_btn("Gửi lại qua SMS", "reload", "login:sms"), inline_btn("Gửi lại mã mới", "mail", "login:resend")],
            [inline_btn("Thoát", "no", "state:exit")],
        ])
        await message.answer(
            f"{e('no')} Lỗi xác nhận OTP: <code>{escape(clean_text(str(ex)))}</code>\n"
            f"Bạn có thể nhập lại mã OTP, bấm gửi lại hoặc bấm <b>Thoát</b>.",
            reply_markup=kb,
        )


@dp.message(BotStates.waiting_for_2fa)
async def admin_login_2fa(message: types.Message, state: FSMContext):
    global temp_login_client
    if message.from_user.id != ADMIN_ID:
        return
    raw_text = (message.text or "").strip()
    if is_exit_text(raw_text):
        await exit_state_to_home(message, state, "Đã thoát nhập mật khẩu 2FA.")
        return
    if is_menu_or_command_text(raw_text):
        await state.clear()
        await _cleanup_temp_login()
        await dp.feed_update(bot, types.Update(update_id=message.message_id, message=message))
        return

    try:
        await temp_login_client.sign_in(password=raw_text)
        session_str = temp_login_client.session.save()
        await save_session(session_str)
        await state.clear()
        await _cleanup_temp_login()
        await message.answer(f"{e('ok')} Đăng nhập 2FA thành công!\n{e('reload')} Đang khởi động bộ quét...")
        asyncio.create_task(start_scanner(session_str))
    except Exception as ex:
        await state.clear()
        await _cleanup_temp_login()
        await message.answer(
            f"{e('no')} Sai mật khẩu 2FA: <code>{escape(clean_text(str(ex)))}</code>\nGõ <code>/login</code> để thử lại."
        )


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
    await _cleanup_temp_login()
    bal = await get_user_balance(call.from_user.id)
    await call.message.answer(home_text(bal), reply_markup=main_kb)
    await call.answer()


# =====================================================================
# NGƯỜI DÙNG
# =====================================================================
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await _cleanup_temp_login()
    bal = await get_user_balance(message.from_user.id)
    await message.answer(home_text(bal), reply_markup=main_kb)


async def build_account(user: types.User):
    info = await get_user_info(user.id)
    name = escape(clean_text(user.full_name) or "—")
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
    await _cleanup_temp_login()
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
    await _cleanup_temp_login()
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
            InlineKeyboardMarkup(inline_keyboard=[
                [inline_btn("Quay lại", "reload", "dep:menu"), inline_btn("Thoát", "no", "state:exit")]
            ]),
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
                f"{e('user')} Khách: {escape(clean_text(u.full_name))} ({uname})\n"
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
    if is_exit_text(raw):
        await exit_state_to_home(message, state, "Đã thoát nhập số tiền.")
        return
    if is_menu_or_command_text(raw):
        await state.clear()
        await dp.feed_update(bot, types.Update(update_id=message.message_id, message=message))
        return
    amount = parse_amount(raw)
    if amount is None:
        await message.answer(
            f"{e('no')} Số tiền không hợp lệ, nhập lại (ví dụ <code>75000</code> hoặc <code>75k</code>) hoặc gõ <code>thoát</code>:"
        )
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
            cleaned_note = clean_text(r["note"])
            note = f" · {escape(cleaned_note)}" if cleaned_note else ""
            lines.append(f"{icon} <b>{sign}{abs(amt):,}đ</b> · {label}")
            lines.append(f"┗ {fmt_dt(r['created_at'])}{note}")
    return "\n".join(lines), page_kb("hist", page, pages)


@dp.message(F.text == BTN_HISTORY)
async def menu_history(message: types.Message, state: FSMContext):
    await state.clear()
    await _cleanup_temp_login()
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
            acc_name = clean_text(r["game_username"])
            lines.append(f"{e('reload')} <b>{idx}.</b> <code>{escape(acc_name)}</code>")
            lines.append(f"┗ {game_name} · đặt lúc {fmt_dt(created)} · còn {mins // 60}h{mins % 60:02d}p")
        lines.append("")
        lines.append(
            f"{e('hourglass')} <i>Quá {ORDER_TIMEOUT_HOURS}h chưa nhập code thành công sẽ tự huỷ &amp; hoàn tiền.</i>"
        )
    return "\n".join(lines), page_kb("ord", page, pages)


@dp.message(F.text == BTN_ORDERS)
async def menu_orders(message: types.Message, state: FSMContext):
    await state.clear()
    await _cleanup_temp_login()
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
    await _cleanup_temp_login()
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
    await _cleanup_temp_login()
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
        InlineKeyboardMarkup(inline_keyboard=[[inline_btn("Thoát", "no", "state:exit")]]),
    )
    await call.answer()


def parse_usernames(raw: str) -> list[str]:
    seen, names = set(), []
    for line in (raw or "").splitlines():
        name = clean_text(line)
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
    if is_exit_text(raw):
        await exit_state_to_home(message, state, "Đã thoát nhập tên tài khoản.")
        return
    if is_menu_or_command_text(raw):
        await state.clear()
        await dp.feed_update(bot, types.Update(update_id=message.message_id, message=message))
        return

    names = parse_usernames(raw)
    if not names:
        await message.answer(f"{e('no')} Tên tài khoản không được để trống, nhập lại hoặc gõ <code>thoát</code>:")
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
        names = "\n".join(f"• <code>{escape(clean_text(n))}</code>" for n, _ in items)
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
@dp.message(Command("thoat", "huythao", "cancel"))
async def admin_exit_cmd(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await exit_state_to_home(message, state, "Đã thoát trạng thái đang chờ.")


@dp.message(Command("checkweb"))
async def admin_check_web(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.clear()
    await _cleanup_temp_login()
    status_msg = await message.answer(f"{e('reload')} Đang kiểm tra truy cập <code>{escape(TARGET_URL)}</code>...")
    t0 = time.perf_counter()
    page = None
    from_pool = False
    try:
        page, from_pool = await borrow_warm_page()
        if page is None:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                try:
                    pg = await browser.new_page()
                    await pg.goto(TARGET_URL, wait_until="domcontentloaded", timeout=20000)
                    elapsed_ms = int((time.perf_counter() - t0) * 1000)
                    has_code = await pg.locator('input[placeholder*="Nhập code"]').count() > 0
                    has_user = await pg.locator('input[placeholder*="Nhập tài khoản"]').count() > 0
                    has_btn = await _has_text_button(pg, r"kiểm tra")
                    await status_msg.edit_text(
                        f"{e('ok')} <b>TRUY CẬP WEB THÀNH CÔNG</b> ({elapsed_ms} ms)\n"
                        f"{SEP}\n"
                        f"{e('globe')} URL: <code>{escape(pg.url)}</code>\n"
                        f"{e('pin')} Ô nhập code: <b>{'Có' if has_code else 'Không thấy'}</b>\n"
                        f"{e('user')} Ô tài khoản: <b>{'Có' if has_user else 'Không thấy'}</b>\n"
                        f"{e('fast')} Nút kiểm tra: <b>{'Có' if has_btn else 'Không thấy'}</b>\n"
                        f"{e('pc')} Pool tab sẵn: <b>0/{WARM_TAB_COUNT}</b>"
                    )
                finally:
                    await browser.close()
            return

        await _prepare_page_on_target(page, timeout=20000)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        has_code = await page.locator('input[placeholder*="Nhập code"]').count() > 0
        has_user = await page.locator('input[placeholder*="Nhập tài khoản"]').count() > 0
        has_btn = await _has_text_button(page, r"kiểm tra")
        ready_tabs = _tab_queue.qsize() if _tab_queue else 0

        await status_msg.edit_text(
            f"{e('ok')} <b>TRUY CẬP WEB THÀNH CÔNG</b> ({elapsed_ms} ms)\n"
            f"{SEP}\n"
            f"{e('globe')} URL: <code>{escape(page.url)}</code>\n"
            f"{e('pin')} Ô nhập code: <b>{'Có' if has_code else 'Không thấy'}</b>\n"
            f"{e('user')} Ô tài khoản: <b>{'Có' if has_user else 'Không thấy'}</b>\n"
            f"{e('fast')} Nút kiểm tra: <b>{'Có' if has_btn else 'Không thấy'}</b>\n"
            f"{e('pc')} Pool tab sẵn: <b>{ready_tabs + (1 if from_pool else 0)}/{WARM_TAB_COUNT}</b>"
        )
    except Exception as ex:
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        await status_msg.edit_text(
            f"{e('no')} <b>LỖI TRUY CẬP WEB</b> ({elapsed_ms} ms)\n"
            f"{SEP}\n"
            f"{e('globe')} URL: <code>{escape(TARGET_URL)}</code>\n"
            f"{e('mail')} Chi tiết: <code>{escape(clean_text(str(ex))[:250])}</code>"
        )
    finally:
        await return_warm_page(page, from_pool)


@dp.message(Command("nap"))
async def admin_add_money(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.clear()
    await _cleanup_temp_login()
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
async def admin_refund_money(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.clear()
    await _cleanup_temp_login()
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
async def admin_sub_money(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.clear()
    await _cleanup_temp_login()
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
async def admin_cancel_order(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.clear()
    await _cleanup_temp_login()
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer(f"{e('no')} Cú pháp: <code>/huy &lt;ten_tai_khoan&gt;</code>")
        return
    name = clean_text(parts[1])
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
                f"{e('no')} Đơn nhập code của tài khoản <code>{escape(clean_text(r['game_username']))}</code> "
                f"đã bị Admin hủy.",
            )
        except Exception:
            pass


@dp.message(Command("thongke"))
async def admin_stats(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.clear()
    await _cleanup_temp_login()
    async with db_pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
        active_accs = await conn.fetchval("SELECT COUNT(*) FROM hunt_accounts WHERE status = 'active'")
    scanner_status = (
        f"{e('ok')} Đang chạy" if (userbot and userbot.is_connected()) else f"{e('no')} Chưa đăng nhập (/login)"
    )
    ready_tabs = _tab_queue.qsize() if _tab_queue else 0
    await message.answer(
        f"{e('top')} <b>THỐNG KÊ</b>\n"
        f"{SEP}\n"
        f"{e('pc')} Bộ quét nhóm: {scanner_status}\n"
        f"{e('globe')} Tab sẵn trên web: <b>{ready_tabs}/{WARM_TAB_COUNT}</b>\n"
        f"{e('shield')} Người dùng: <b>{total_users}</b>\n"
        f"{e('reload')} Tài khoản chờ nhập code: <b>{active_accs}</b>"
    )


# =====================================================================
# LỌC CODE 6 KÝ TỰ (TIN NHẮN & VIDEO)
# =====================================================================
def extract_clean_codes(raw_text: str) -> list[str]:
    """
    Lọc các chuỗi code có ký tự rác xen kẽ (ví dụ NrTs.WA@, hfAh!RE#, uJRJ.RC@),
    xoá hết ký tự đặc biệt / gạch ngang / gạch chéo, chỉ giữ lại chữ hoa, chữ thường và số
    có độ dài đúng 6 ký tự.
    """
    clean_codes = []
    for w in clean_text(raw_text).split():
        if w.startswith(("http", "#", "@")):
            continue
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
        crop_box = (0, int(h * 0.15), int(w * 0.45), int(h * 0.82))
        cropped = im.crop(crop_box)
        cw, ch = cropped.size
        cropped = cropped.resize((cw * 2, ch * 2), Image.Resampling.LANCZOS)
        cropped = ImageEnhance.Contrast(cropped).enhance(2.2)

        lines_text = []
        step = ch * 2 // 5
        for i in range(5):
            strip = cropped.crop((0, i * step, cw * 2, (i + 1) * step))
            buf = BytesIO()
            strip.save(buf, format="PNG")
            txt = clean_text(ocr.classification(buf.getvalue()))
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


CAPTCHA_FORCE_UPPER = True  # captcha của web là chữ HOA + số; đổi thành False nếu web phân biệt hoa/thường
CAPTCHA_MIN_LEN = 4
CAPTCHA_MAX_LEN = 6


CAPTCHA_CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
ocr_captcha = ddddocr.DdddOcr(show_ad=False)  # bộ OCR riêng cho captcha (bộ `ocr` ở trên dành cho video, phân biệt hoa/thường)
if os.getenv("CAPTCHA_RESTRICT", "1") == "1":
    try:
        ocr_captcha.set_ranges(CAPTCHA_CHARSET)  # chỉ cho phép nhận ra chữ HOA + số -> hết nhầm hoa/thường
    except Exception as _ex:
        print(f"Không giới hạn được bảng ký tự captcha: {_ex}")
_ocr_pool = ThreadPoolExecutor(max_workers=max(4, (os.cpu_count() or 2) * 2))


def _ocr_variants(img_bytes: bytes) -> list[bytes]:
    """Vài bản xử lý ảnh khác nhau của cùng một captcha để OCR bỏ phiếu cho chính xác hơn."""
    variants = [img_bytes]
    base = Image.open(BytesIO(img_bytes)).convert("L")
    w, h = base.size
    v1 = ImageEnhance.Contrast(base.resize((w * 3, h * 3), Image.Resampling.LANCZOS)).enhance(1.8)
    v3 = ImageEnhance.Contrast(base.resize((w * 2, h * 2), Image.Resampling.LANCZOS)).enhance(2.5)
    for im in (v1, v3):
        buf = BytesIO()
        im.save(buf, format="PNG")
        variants.append(buf.getvalue())
    return variants


def _ocr_sync(img_bytes: bytes) -> str:
    votes = []
    for data in _ocr_variants(img_bytes):
        try:
            text = re.sub(r"[^a-zA-Z0-9]", "", ocr_captcha.classification(data))
        except Exception:
            continue
        text = text.upper()  # captcha luôn là CHỮ HOA + số
        if CAPTCHA_MIN_LEN <= len(text) <= CAPTCHA_MAX_LEN:
            votes.append(text)
    if not votes:
        return ""  # đọc không ra -> bấm Làm mới ảnh lấy captcha khác, không nộp bừa
    return Counter(votes).most_common(1)[0][0]


async def doc_captcha(img_bytes: bytes) -> str:
    return await asyncio.get_running_loop().run_in_executor(_ocr_pool, _ocr_sync, img_bytes)


# =====================================================================
# THAO TÁC TRÊN TRANG WEB NHẬP CODE
# =====================================================================
async def click_text_button(page, pattern: str, below=None) -> bool:
    """Bấm phần tử có chữ/alt/title khớp pattern; nếu có `below` thì chỉ nhận phần tử nằm dưới ô đó."""
    rx = re.compile(pattern, re.I)
    min_y = 0
    if below is not None:
        box = await below.bounding_box()
        if box:
            min_y = box["y"] + box["height"] - 5

    finders = [
        page.get_by_role("button", name=rx),
        page.get_by_text(rx),
        page.get_by_alt_text(rx),
        page.get_by_title(rx),
    ]
    for loc in finders:
        try:
            total = await loc.count()
        except Exception:
            continue
        for i in range(total):
            el = loc.nth(i)
            try:
                if not await el.is_visible():
                    continue
                await el.scroll_into_view_if_needed(timeout=2000)
                box = await el.bounding_box()
                if not box or box["y"] < min_y:
                    continue
                await page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                return True
            except Exception:
                continue
    return False


async def _has_text_button(page, pattern: str) -> bool:
    """Kiểm tra có phần tử (nút/ảnh/chữ) khớp pattern trên trang hay không (dùng cho /checkweb)."""
    rx = re.compile(pattern, re.I)
    for loc in (
        page.get_by_role("button", name=rx),
        page.get_by_text(rx),
        page.get_by_alt_text(rx),
        page.get_by_title(rx),
    ):
        try:
            if await loc.count() > 0:
                return True
        except Exception:
            continue
    return False


async def _find_captcha_element(page, captcha_input):
    """Tìm đúng ảnh captcha: ảnh nằm ngay phía trên ô 'Nhập mã captcha' trong khung Mã xác thực."""
    try:
        ibox = await captcha_input.first.bounding_box()
        if not ibox:
            return None
        cont = captcha_input.first.locator("xpath=ancestor::*[.//img or .//canvas][1]")
        if await cont.count() == 0:
            return None
        imgs = cont.first.locator("img, canvas")
        best, best_gap = None, None
        for i in range(await imgs.count()):
            el = imgs.nth(i)
            if not await el.is_visible():
                continue
            box = await el.bounding_box()
            if not box or box["width"] < 60 or box["height"] < 20:
                continue
            gap = ibox["y"] - (box["y"] + box["height"])
            if gap < -5 or gap > 200:
                continue
            if best_gap is None or gap < best_gap:
                best, best_gap = el, gap
        return best
    except Exception:
        return None


async def _captcha_image_bytes(page, captcha_input) -> bytes:
    el = await _find_captcha_element(page, captcha_input)
    if el is not None:
        return await el.screenshot()
    # Dự phòng: chụp vùng ngay phía trên ô nhập captcha (ảnh captcha nằm ở đó)
    ibox = await captcha_input.first.bounding_box()
    width = ibox["width"]
    height = width * 0.35
    y = max(0, ibox["y"] - width * 0.04 - height)
    return await page.screenshot(clip={"x": ibox["x"], "y": y, "width": width, "height": height})


async def refresh_captcha_image(page, captcha_input) -> bool:
    """Bấm 'Làm mới ảnh' để lấy captcha mới, chờ tới khi ảnh đổi và xoá ô đã nhập."""
    try:
        old = await _captcha_image_bytes(page, captcha_input)
    except Exception:
        old = b""
    clicked = await click_text_button(page, r"làm mới", below=captcha_input.first)
    if not clicked:
        el = await _find_captcha_element(page, captcha_input)  # web ghi chú: bấm vào ảnh cũng tải lại
        if el is not None:
            try:
                await el.click(timeout=3000)
                clicked = True
            except Exception:
                pass
    try:
        await captcha_input.first.fill("")
    except Exception:
        pass
    for _ in range(20):
        await page.wait_for_timeout(100)
        try:
            new = await _captcha_image_bytes(page, captcha_input)
        except Exception:
            continue
        if new and new != old:
            return True
    return clicked


def _format_notice_lines(raw_text: str) -> str:
    """Làm sạch nội dung thông báo trên web và xoá dòng nút bấm thừa."""
    ignore_lines = {"đóng", "chăm sóc khách hàng 24/7", "xác thực", "kiểm tra", "làm mới ảnh", "hủy"}
    cleaned_lines = []
    seen = set()
    for line in (raw_text or "").splitlines():
        item = clean_text(line)
        if not item:
            continue
        if item.lower() in ignore_lines:
            continue
        if item.lower() not in seen:
            seen.add(item.lower())
            cleaned_lines.append(item)
    return " | ".join(cleaned_lines)[:350]


RESULT_KEYWORDS = (
    "thành công", "thất bại", "không đúng", "không tồn tại", "không hợp lệ",
    "đã sử dụng", "đã được", "hết lượt", "hết hạn",
)
POPUP_SELECTORS = (
    ".swal2-popup", '[role="dialog"]', '[role="alert"]', ".modal-content", ".toast", ".alert", ".notification",
)


async def _popup_text(page) -> str:
    """Đọc nội dung popup đang hiện (khung kết quả kiểu 'Nhận Code Thất Bại!...')."""
    for sel in POPUP_SELECTORS:
        try:
            loc = page.locator(sel)
            count = await loc.count()
            for idx in range(count - 1, -1, -1):
                item = loc.nth(idx)
                if await item.is_visible():
                    txt = _format_notice_lines(await item.inner_text())
                    if txt:
                        return txt
        except Exception:
            continue
    # Popup tự viết của web (không có class chuẩn): tìm theo nút "Đóng" rồi lấy cả khung chứa nó
    try:
        close_btn = page.get_by_text(re.compile(r"^\s*đóng\s*$", re.I))
        total = await close_btn.count()
        for i in range(total - 1, -1, -1):
            el = close_btn.nth(i)
            if not await el.is_visible():
                continue
            box = el.locator("xpath=ancestor::*[contains(normalize-space(.), 'Chăm sóc khách hàng')][1]")
            if await box.count() == 0:
                box = el.locator("xpath=../..")
            txt = _format_notice_lines(await box.first.inner_text())
            if txt:
                return txt
    except Exception:
        pass
    return ""


async def get_page_notice(page) -> str:
    """Lấy đúng nội dung ghi chú/thông báo hiển thị trên web sau khi nhập code."""
    try:
        txt = await _popup_text(page)
        if txt:
            return txt
        body = _format_notice_lines(await page.inner_text("body"))
        return body[-250:]
    except Exception:
        return ""


async def _captcha_modal_visible(captcha_input) -> bool:
    try:
        return await captcha_input.first.is_visible()
    except Exception:
        return False


async def _wait_after_verify(page, captcha_input, timeout_ms: int = 3500) -> tuple[str, str]:
    """
    Sau khi bấm Xác thực:
      - ("result", text): web hiện popup kết quả (thành công / thất bại + lý do)
      - ("captcha_wrong", ""): khung Mã xác thực vẫn còn -> nhập sai, bắt nhập lại
    """
    deadline = time.perf_counter() + timeout_ms / 1000
    hidden_since = None
    while time.perf_counter() < deadline:
        txt = await _popup_text(page)
        low = txt.lower()
        if txt and any(k in low for k in RESULT_KEYWORDS):
            return "result", txt
        if await _captcha_modal_visible(captcha_input):
            hidden_since = None
        else:
            if hidden_since is None:
                hidden_since = time.perf_counter()
            elif time.perf_counter() - hidden_since > 1.5:
                return "result", txt or await get_page_notice(page)
        await page.wait_for_timeout(100)
    if await _captcha_modal_visible(captcha_input):
        return "captcha_wrong", ""
    return "result", await get_page_notice(page)


CAPTCHA_ERR_RX = re.compile(r"không tải được captcha|tải captcha|làm mới hoặc thử lại", re.I)
MAX_ATTEMPTS_PER_CODE = 8  # chưa vượt qua bước captcha thì nhập lại code đó tối đa số lần này


def _is_captcha_notice(low: str) -> bool:
    return bool(CAPTCHA_ERR_RX.search(low)) or "captcha" in low or "mã xác thực" in low or "nhập đúng mã trong ảnh" in low


def _is_code_verdict(text: str) -> bool:
    """True khi web đã trả lời về CODE (sai/hết hạn/thành công...), không phải thông báo của khung captcha."""
    low = (text or "").lower()
    return bool(low) and not _is_captcha_notice(low) and any(k in low for k in RESULT_KEYWORDS)


async def _captcha_loaded(page, captcha_input) -> bool:
    """Ảnh captcha đã tải xong chưa (ảnh lỗi/đang tải thì naturalWidth = 0)."""
    el = await _find_captcha_element(page, captcha_input)
    if el is None:
        return True  # không xác định được phần tử -> để bước chụp dự phòng xử lý
    try:
        return bool(await el.evaluate("e => e.tagName !== 'IMG' || (e.complete && e.naturalWidth > 0)"))
    except Exception:
        return True


async def _refresh_until_loaded(page, captcha_input):
    """Bấm Làm mới ảnh rồi chờ ảnh captcha mới tải xong."""
    await refresh_captcha_image(page, captcha_input)
    for _ in range(10):
        if await _captcha_loaded(page, captcha_input):
            return
        await page.wait_for_timeout(300)


async def thu_mot_code(page, code: str, game_username: str, max_captcha_retry: int = 8, stop_check=None) -> tuple[str, str]:
    """
    Trả về:
      SUCCESS - web báo nhập code thành công
      FAIL    - web đã trả lời về CODE (sai / hết hạn / đã dùng...) -> không cần nhập lại
      RETRY   - chưa vượt qua được bước captcha (hoặc web chưa trả lời về code) -> nhập lại code này
    """
    clean_code = clean_text(code)
    clean_user = clean_text(game_username)

    code_input = page.locator('input[placeholder*="Nhập code"]')
    user_input = page.locator('input[placeholder*="Nhập tài khoản"]')
    captcha_input = page.locator('input[placeholder*="Nhập mã captcha"]')

    if page.url.rstrip("/") != TARGET_URL.rstrip("/") or await code_input.count() == 0:
        await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=15000)
    await code_input.first.wait_for(state="visible", timeout=8000)

    # Đóng popup cũ nếu còn
    try:
        old_close = page.get_by_text(re.compile(r"^\s*đóng\s*$", re.I))
        if await old_close.count() > 0 and await old_close.first.is_visible():
            await old_close.first.click(timeout=2000)
    except Exception:
        pass

    # BƯỚC 1: điền code + tài khoản
    await code_input.first.fill(clean_code)
    await user_input.first.fill(clean_user)

    # BƯỚC 2: bấm KIỂM TRA (nút nằm dưới ô tài khoản)
    if not await click_text_button(page, r"kiểm tra", below=user_input.first):
        return "RETRY", "Không tìm thấy nút Kiểm tra trên web"

    # BƯỚC 3: chờ khung "Mã xác thực" (ô captcha) hiện ra
    try:
        await captcha_input.first.wait_for(state="visible", timeout=8000)
    except Exception:
        popup = await _popup_text(page)
        if _is_code_verdict(popup):
            return "FAIL", popup
        return "RETRY", popup or "Bấm Kiểm tra nhưng web không hiện khung mã xác thực"

    # BƯỚC 4: đọc captcha -> nhập -> Xác thực.
    # Captcha lỗi / không tải được / nhập sai -> bấm "Làm mới ảnh" lấy captcha mới rồi làm lại.
    last_notice = ""
    for _ in range(max_captcha_retry):
        if stop_check and stop_check():
            return "SKIP", "Tài khoản đã nhập thành công bằng code khác"
        if not await _captcha_modal_visible(captcha_input):
            popup = await _popup_text(page)
            if _is_code_verdict(popup):
                return "FAIL", popup
            return "RETRY", popup or last_notice or "Khung mã xác thực đã đóng khi chưa có kết quả"

        # Web báo "Không tải được captcha" hoặc ảnh chưa tải -> làm mới ảnh
        popup = await _popup_text(page)
        if CAPTCHA_ERR_RX.search(popup or "") or not await _captcha_loaded(page, captcha_input):
            last_notice = popup or "Không tải được captcha"
            await _refresh_until_loaded(page, captcha_input)
            continue

        try:
            img_bytes = await _captcha_image_bytes(page, captcha_input)
            captcha_text = await doc_captcha(img_bytes)
        except Exception:
            captcha_text = ""
        if not captcha_text:
            await _refresh_until_loaded(page, captcha_input)
            continue

        await captcha_input.first.fill(captcha_text.upper())
        if not await click_text_button(page, r"xác thực", below=captcha_input.first):
            await _refresh_until_loaded(page, captcha_input)
            continue

        outcome, notice = await _wait_after_verify(page, captcha_input)
        low = notice.lower()
        if outcome == "result":
            if "thành công" in low and "thất bại" not in low and not _is_captcha_notice(low):
                return "SUCCESS", notice
            if _is_code_verdict(notice):
                # Web đã trả lời về CODE (vd: Nhận Code Thất Bại! Mã CODE không đúng...) -> báo nguyên văn
                return "FAIL", notice

        # Còn lại: captcha sai / lỗi captcha / chưa có kết quả -> làm mới ảnh, nhập lại
        last_notice = notice
        await _refresh_until_loaded(page, captcha_input)

    return "RETRY", f"Chưa vượt qua được bước captcha sau {max_captcha_retry} lần ({last_notice or 'web không phản hồi'})"


async def report_attempt_to_admin(code: str, game_username: str, owner_id: int, ok: bool, note: str):
    head = (
        f"{e('ok')} <b>NHẬP CODE THÀNH CÔNG</b>" if ok else f"{e('no')} <b>NHẬP CODE THẤT BẠI</b>"
    )
    final_note = clean_text(note) or "Không có ghi chú"
    text = (
        f"{head}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{e('pc')} Tài khoản: <code>{escape(clean_text(game_username))}</code>\n"
        f"{e('new')} Mã code nhập: <code>{escape(clean_text(code))}</code>\n"
        f"{e('shield')} Chủ đơn: <code>{owner_id}</code>\n"
        f"{e('mail')} Ghi chú: {escape(final_note)}\n"
        f"{e('soon')} Thời gian: {now_str()}"
    )
    try:
        await bot.send_message(ADMIN_ID, text)
    except Exception as ex:
        print(f"Không gửi được báo cáo cho admin: {ex}")


async def _attempt_code(code: str, game_username: str, owner_id: int, stop_check=None) -> tuple[str, str]:
    """
    Một lần thử = một tab riêng. Thử xong là nạp lại tab ở nền để trống chỗ cho lượt sau.
    Trả về (SUCCESS | FAIL | ERROR, ghi chú). ERROR = tab bị lỗi thao tác (không phải web trả lời).
    """
    async def _run(page) -> tuple[str, str]:
        try:
            return await thu_mot_code(page, code, game_username, stop_check=stop_check)
        except Exception as ex:
            print(f"Lỗi tab khi nhập {code} cho {game_username}: {ex}")  # chi tiết kỹ thuật chỉ ghi log
            try:
                notice = await _popup_text(page)
            except Exception:
                notice = ""
            if notice and _is_code_verdict(notice):
                return "FAIL", notice
            return "ERROR", "Tab nhập code bị lỗi thao tác, đã chuyển sang tab khác"

    page, from_pool = await borrow_warm_page()
    if page is None:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                return await _run(await browser.new_page())
            finally:
                await browser.close()
    try:
        return await _run(page)
    finally:
        fire(return_warm_page(page, from_pool))  # nạp lại tab ở nền cho đợt sau


# =====================================================================
# CHIA CODE CHO TÀI KHOẢN VÀ NHẬP SONG SONG NHIỀU TAB
# =====================================================================
async def _account_still_active(record_id: int) -> bool:
    async with db_pool.acquire() as conn:
        st = await conn.fetchval("SELECT status FROM hunt_accounts WHERE id = $1", record_id)
    return st == "active"


async def _mark_account_done(acc, code: str):
    record_id = acc["id"]
    owner_id = acc["user_id"]
    game_user = clean_text(acc["game_username"])
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE hunt_accounts SET status = 'done' WHERE id = $1 AND status = 'active'", record_id
        )
    if owner_id != ADMIN_ID:
        fire(bot.send_message(
            owner_id,
            f"{e('fire')} <b>NHẬP CODE THÀNH CÔNG!</b> {e('top')}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{e('pc')} Tài khoản: <code>{escape(game_user)}</code>\n"
            f"{e('new')} Mã code: <code>{escape(code)}</code>\n"
            f"{SEP}\n"
            f"{e('ok')} Đơn hàng đã <b>hoàn tất</b> và được xoá khỏi danh sách chờ.\n"
            f"{e('bulb')} <i>Muốn nhập code lại cho tài khoản này, vui lòng mua lại.</i>",
        ))


async def _run_accounts(accounts, codes: list[str]):
    """
    Chia code cho tài khoản, mỗi cặp (tài khoản, code) được nhiều tab CHẠY ĐUA cùng lúc:
      - Ví dụ 60 tab, 6 code -> 6 cặp, mỗi cặp 10 tab. Tab nào sai captcha thì tab khác vẫn đang chạy.
      - Tab đầu tiên thành công -> các tab còn lại của cặp đó dừng ngay.
      - Mỗi code chỉ giao cho tài khoản đang được giao ít nhất (2 tài khoản / 6 code = mỗi nick 3 code).
      - Tài khoản thành công -> chuyển 'done' (rời danh sách chờ), code còn lại dồn sang nick chưa xong.
      - Code web báo sai/hết hạn/đã dùng -> bỏ; lỗi riêng của tài khoản -> thử sang tài khoản khác.
    """
    accs = {a["id"]: a for a in accounts}
    done: set[int] = set()
    dead: set[str] = set()
    tried: set[tuple[int, str]] = set()
    assigned: dict[int, int] = {aid: 0 for aid in accs}
    active = [0]
    stats = {"SUCCESS": 0, "FAIL": 0, "RETRY": 0}

    max_jobs = max(1, min(len(codes), WARM_TAB_COUNT))
    replicas = max(1, min(REPLICAS_PER_CODE, WARM_TAB_COUNT // max_jobs))

    def pick():
        for code in codes:
            if code in dead or code in _inflight_codes or is_dead(code):
                continue
            cands = [aid for aid in accs if aid not in done and (aid, code) not in tried]
            if not cands:
                continue
            aid = min(cands, key=lambda a: (assigned[a], a))
            _inflight_codes.add(code)
            tried.add((aid, code))
            assigned[aid] += 1
            return aid, code
        return None

    async def run_job(aid: int, code: str):
        acc = accs[aid]
        game_user = clean_text(acc["game_username"])
        owner_id = acc["user_id"]
        if aid in done or not await _account_still_active(aid):
            done.add(aid)
            return

        state = {"final": None, "last_note": ""}

        def stop() -> bool:
            return aid in done or state["final"] is not None

        async def replica():
            for _ in range(MAX_ATTEMPTS_PER_CODE):
                if stop():
                    return
                async with _get_tab_sem():
                    status, note = await _attempt_code(code, game_user, owner_id, stop_check=stop)
                if status == "SUCCESS":
                    state["final"] = ("SUCCESS", note)  # thành công luôn được ưu tiên
                    return
                if status == "FAIL":
                    if state["final"] is None:
                        state["final"] = ("FAIL", note)
                    return
                if status == "SKIP":
                    return
                state["last_note"] = note  # RETRY/ERROR: sai captcha... -> lượt sau thử lại trên tab mới
                await asyncio.sleep(0.1)

        await asyncio.gather(*(replica() for _ in range(replicas)), return_exceptions=True)

        final = state["final"]
        if final is None:
            if aid in done:
                return
            status = "RETRY"
            note = (clean_text(state["last_note"]) or "Chưa vượt qua được bước captcha") + \
                f" | {replicas} tab x {MAX_ATTEMPTS_PER_CODE} lần"
        else:
            status, note = final

        ok = status == "SUCCESS"
        stats[status if status in ("SUCCESS", "FAIL") else "RETRY"] += 1
        if ok:
            done.add(aid)
            dead.add(code)
            await _mark_account_done(acc, code)
        elif DEAD_CODE_RX.search(note or ""):
            mark_dead(code)
            dead.add(code)
        fire(report_attempt_to_admin(code, game_user, owner_id, ok, note))

    async def job_worker():
        while True:
            job = pick()  # không có await bên trong nên không bị tranh chấp
            if job is None:
                if active[0] == 0:
                    return
                await asyncio.sleep(0.1)
                continue
            aid, code = job
            active[0] += 1
            try:
                await run_job(aid, code)
            except Exception as ex:
                name = clean_text(accs[aid]["game_username"])
                print(f"Lỗi nhập code {code} cho {name}: {type(ex).__name__}: {ex}")
                fire(bot.send_message(
                    ADMIN_ID,
                    f"{e('no')} <b>LỖI HỆ THỐNG</b> khi nhập code cho <code>{escape(name)}</code>:\n"
                    f"<code>{escape(clean_text(f'{type(ex).__name__}: {ex}')[:250])}</code>",
                ))
            finally:
                _inflight_codes.discard(code)
                active[0] -= 1

    await asyncio.gather(*(job_worker() for _ in range(max_jobs)), return_exceptions=True)

    fire(bot.send_message(
        ADMIN_ID,
        f"{e('chart')} <b>TỔNG KẾT ĐỢT CODE</b>\n"
        f"{SEP}\n"
        f"{e('ok')} Tài khoản thành công: <b>{len(done)}/{len(accs)}</b>\n"
        f"{e('no')} Code web báo sai/hết hạn: <b>{stats['FAIL']}</b>\n"
        f"{e('reload')} Code chưa qua captcha: <b>{stats['RETRY']}</b>\n"
        f"{e('pc')} Chạy đua: <b>{replicas}</b> tab / code",
    ))
    for aid, acc in accs.items():
        if aid in done:
            continue
        fire(bot.send_message(
            acc["user_id"],
            f"{e('soon')} Đợt code hiện tại chưa khớp cho <code>{escape(clean_text(acc['game_username']))}</code>.\n"
            f"{e('reload')} Hệ thống tiếp tục giữ tài khoản ở trạng thái "
            f"<b>đang chờ nhập code</b> cho đợt code tiếp theo.",
        ))
    fire(init_browser_pool(WARM_TAB_COUNT))  # đảm bảo luôn đủ tab trống cho đợt sau


async def dispatch_codes_to_accounts(codes: list[str], source_label: str):
    """Quét được code là nhập NGAY cho mọi tài khoản đang chờ, chạy song song nhiều tab."""
    cleaned_codes = [clean_text(c) for c in codes if clean_text(c)]
    cleaned_codes = list(dict.fromkeys(cleaned_codes))
    if not cleaned_codes:
        return

    for c in cleaned_codes:
        _dead_codes.pop(c, None)  # code được đăng lại -> thử lại từ đầu

    async with db_pool.acquire() as conn:
        accounts = await conn.fetch(
            "SELECT id, user_id, game_username FROM hunt_accounts WHERE status = 'active' ORDER BY id"
        )

    code_list_str = ", ".join(f"<code>{escape(c)}</code>" for c in cleaned_codes)
    fire(bot.send_message(
        ADMIN_ID,
        f"{e('fast')} <b>QUÉT ĐƯỢC CODE MỚI ({escape(clean_text(source_label))})</b>\n"
        f"{SEP}\n"
        f"{e('new')} Danh sách ({len(cleaned_codes)} mã): {code_list_str}\n"
        f"{e('pc')} Tài khoản đang chờ nhập code: <b>{len(accounts)}</b>",
    ))
    if not accounts:
        return
    await _run_accounts(accounts, cleaned_codes)


# =====================================================================
# QUÉT NHÓM LIÊN TỤC (TIN NHẮN + VIDEO)
# =====================================================================
async def start_scanner(session_str: str):
    global userbot
    if userbot and userbot.is_connected():
        await userbot.disconnect()

    userbot = TelegramClient(StringSession(session_str), API_ID, API_HASH)

    # 1. Nhóm video (FreeCode_78win) -> Chỉ quét video gửi lên
    @userbot.on(events.NewMessage(chats=VIDEO_TARGET_GROUPS))
    async def video_scanner_handler(event):
        if not event.message or not event.message.video:
            return
        try:
            chat = await event.get_chat()
            group_name = getattr(chat, "username", None) or "video_group"
            codes = await extract_codes_from_video_message(event.message)
            if codes:
                fire(dispatch_codes_to_accounts(codes, f"Video {group_name}"))
        except Exception as ex:
            print(f"Lỗi quét video: {ex}")

    # 2. Nhóm tin nhắn văn bản (official78wins, thongbaocvx) -> Quét tin nhắn code
    @userbot.on(events.NewMessage(chats=TEXT_TARGET_GROUPS))
    async def text_scanner_handler(event):
        if not event.raw_text:
            return
        try:
            chat = await event.get_chat()
            group_name = getattr(chat, "username", None) or "text_group"
            codes = extract_clean_codes(event.raw_text)
            if codes:
                fire(dispatch_codes_to_accounts(codes, f"Tin nhắn {group_name}"))
        except Exception as ex:
            print(f"Lỗi quét tin nhắn: {ex}")

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
    background_tasks.append(asyncio.create_task(warm_pool_loop()))
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
