import asyncio
import os
import re
from datetime import datetime, timedelta, timezone
from html import escape
from io import BytesIO

import asyncpg
import ddddocr
from PIL import Image, ImageEnhance
from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
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

BOT_TOKEN = os.getenv("BOT_TOKEN", "9044293543:AAEFP_xv45GUuR76f382cekrDOaCjdE2zLw")
ADMIN_ID = int(os.getenv("ADMIN_ID", "9220244280"))
DATABASE_URL = os.getenv("DATABASE_URL", "")

TARGET_GROUPS = ["official78wins", "FreeCode_78win"]
TARGET_URL = "https://code78k.online/"
CODE_PRICE = 10000
MAX_BATCH = 30  # số tài khoản tối đa đăng ký trong 1 lần

VN_TZ = timezone(timedelta(hours=7))

# Danh sách game cho slot nhập code (hiện chỉ có 78WIN)
GAMES = {
    "78win": {"name": "78WIN", "price": CODE_PRICE},
}

# =====================================================================
# EMOJI PREMIUM
# =====================================================================
EMOJI = {
    "ok": "5206607081334906820",       # ✔️
    "fast": "5456140674028019486",     # ⚡️
    "money": "5231449120635370684",    # 💸
    "money2": "5231005931550030290",   # 💸
    "no": "5210952531676504517",       # ❌
    "fire": "5424972470023104089",     # 🔥
    "reload": "5375338737028841420",   # 🔄
    "top": "5341498088408234504",      # 💯
    "new": "5382357040008021292",      # 🆕
    "soon": "5440621591387980068",     # 🔜
    "pc": "5282843764451195532",       # 🖥
    "link": "5271604874419647061",     # 🔗
    "shield": "5251203410396458957",   # 🛡
    "plus": "5397916757333654639",     # ➕
    "lock": "5296369303661067030",     # 🔒
    "down": "5406745015365943482",     # ⬇️
    "mail": "5253742260054409879",     # ✉️
}
FALLBACK = {
    "ok": "✔️", "fast": "⚡️", "money": "💸", "money2": "💸", "no": "❌",
    "fire": "🔥", "reload": "🔄", "top": "💯", "new": "🆕", "soon": "🔜",
    "pc": "🖥", "link": "🔗", "shield": "🛡", "plus": "➕", "lock": "🔒",
    "down": "⬇️", "mail": "✉️",
}


def e(name: str) -> str:
    """Emoji premium dạng HTML (tự hiện emoji thường nếu không hỗ trợ)."""
    return f'<tg-emoji emoji-id="{EMOJI[name]}">{FALLBACK[name]}</tg-emoji>'


def kb_btn(text: str, icon: str) -> KeyboardButton:
    return KeyboardButton(text=text, icon_custom_emoji_id=EMOJI[icon])


def inline_btn(text: str, icon: str, callback_data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=callback_data, icon_custom_emoji_id=EMOJI[icon])


# =====================================================================
# KHỞI TẠO
# =====================================================================
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
ocr = ddddocr.DdddOcr(show_ad=False)
db_pool: asyncpg.Pool | None = None
userbot: TelegramClient | None = None
temp_login_client: TelegramClient | None = None


class BotStates(StatesGroup):
    waiting_for_username = State()
    waiting_for_otp = State()
    waiting_for_2fa = State()


BTN_CODE = "Nhập Code"
BTN_ACCOUNT = "Tài Khoản"
BTN_DEPOSIT = "Nạp Tiền"
MENU_TEXTS = (BTN_CODE, BTN_ACCOUNT, BTN_DEPOSIT)

main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [kb_btn(BTN_CODE, "fire"), kb_btn(BTN_ACCOUNT, "shield")],
        [kb_btn(BTN_DEPOSIT, "money")],
    ],
    resize_keyboard=True,
)


def game_select_kb() -> InlineKeyboardMarkup:
    rows = [
        [inline_btn(f"{g['name']}  •  {g['price']:,}đ", "top", f"game:{key}")]
        for key, g in GAMES.items()
    ]
    rows.append([inline_btn("Hủy", "no", "game:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def now_str() -> str:
    return datetime.now(VN_TZ).strftime("%H:%M:%S %d/%m/%Y")


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
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS hunt_accounts (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                game_username TEXT NOT NULL,
                status TEXT DEFAULT 'active'
            )
        """)
        await conn.execute("ALTER TABLE hunt_accounts ADD COLUMN IF NOT EXISTS game TEXT DEFAULT '78win'")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        # Chặn trùng ở tầng DB: 1 tài khoản game chỉ được có 1 đơn đang chờ
        try:
            await conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_active_game_account
                ON hunt_accounts (game, lower(game_username))
                WHERE status = 'active'
            """)
        except Exception as ex:
            print(f"Không tạo được unique index (dữ liệu cũ có thể bị trùng): {ex}")


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


async def get_user_balance(user_id: int) -> int:
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO users (user_id, balance) VALUES ($1, 0) ON CONFLICT (user_id) DO NOTHING",
            user_id,
        )
        row = await conn.fetchrow("SELECT balance FROM users WHERE user_id = $1", user_id)
        return int(row["balance"]) if row else 0


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
# NGƯỜI DÙNG
# =====================================================================
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    bal = await get_user_balance(message.from_user.id)
    await message.answer(
        f"{e('fire')} <b>HỆ THỐNG NHẬP CODE TỰ ĐỘNG</b> {e('fast')}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{e('money')} Số dư: <b>{bal:,}đ</b>\n"
        f"{e('top')} Giá đăng ký: <b>{CODE_PRICE:,}đ / tài khoản</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{e('down')} Chọn chức năng ở menu bên dưới",
        reply_markup=main_kb,
    )


# ---- Tài Khoản -------------------------------------------------------
@dp.message(F.text == BTN_ACCOUNT)
async def menu_account(message: types.Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    bal = await get_user_balance(uid)
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT game_username, status, game FROM hunt_accounts "
            "WHERE user_id = $1 ORDER BY id DESC LIMIT 30",
            uid,
        )

    lines = [
        f"{e('shield')} <b>THÔNG TIN TÀI KHOẢN</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"{e('link')} ID của bạn: <code>{uid}</code>",
        f"{e('money')} Số dư: <b>{bal:,}đ</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"{e('pc')} <b>Danh sách tài khoản (30 gần nhất):</b>",
    ]
    if not rows:
        lines.append(f"{e('no')} Chưa có tài khoản nào đang chờ nhập code.")
    else:
        for idx, r in enumerate(rows, 1):
            game_name = GAMES.get(r["game"] or "78win", {}).get("name", "78WIN")
            if r["status"] == "active":
                status = f"{e('reload')} Đang chờ nhập code"
            elif r["status"] == "cancelled":
                status = f"{e('no')} Đã bị Admin hủy"
            else:
                status = f"{e('ok')} Đã nhập code thành công"
            lines.append(f"{idx}. <code>{escape(r['game_username'])}</code> • {game_name} • {status}")
    await message.answer("\n".join(lines))


# ---- Nạp Tiền --------------------------------------------------------
@dp.message(F.text == BTN_DEPOSIT)
async def menu_deposit(message: types.Message, state: FSMContext):
    await state.clear()
    bal = await get_user_balance(message.from_user.id)
    await message.answer(
        f"{e('money2')} <b>NẠP TIỀN</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{e('link')} ID của bạn: <code>{message.from_user.id}</code>\n"
        f"{e('money')} Số dư hiện tại: <b>{bal:,}đ</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{e('plus')} Gửi ID trên cho Admin để được nạp tiền."
    )


# ---- Nhập Code -------------------------------------------------------
@dp.message(F.text == BTN_CODE)
async def menu_code(message: types.Message, state: FSMContext):
    await state.clear()
    bal = await get_user_balance(message.from_user.id)
    await message.answer(
        f"{e('fire')} <b>NHẬP CODE</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{e('money')} Số dư: <b>{bal:,}đ</b>\n"
        f"{e('down')} Chọn game cần mua slot nhập code:",
        reply_markup=game_select_kb(),
    )


@dp.callback_query(F.data.startswith("game:"))
async def choose_game(call: types.CallbackQuery, state: FSMContext):
    key = call.data.split(":", 1)[1]
    if key == "cancel":
        await state.clear()
        await call.message.edit_text(f"{e('no')} Đã hủy thao tác.")
        await call.answer()
        return

    game = GAMES.get(key)
    if not game:
        await call.answer("Game không tồn tại!", show_alert=True)
        return

    bal = await get_user_balance(call.from_user.id)
    if bal < game["price"]:
        await call.message.edit_text(
            f"{e('no')} <b>Số dư không đủ!</b>\n"
            f"{e('money')} Cần tối thiểu: <b>{game['price']:,}đ</b>\n"
            f"{e('money2')} Số dư hiện tại: <b>{bal:,}đ</b>\n"
            f"{e('plus')} Bấm <b>{BTN_DEPOSIT}</b> để nạp thêm."
        )
        await call.answer()
        return

    await state.update_data(game=key)
    await state.set_state(BotStates.waiting_for_username)
    await call.message.edit_text(
        f"{e('top')} Game: <b>{game['name']}</b>\n"
        f"{e('money')} Giá: <b>{game['price']:,}đ / tài khoản</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{e('mail')} Nhập <b>tên tài khoản</b> cần nhập code.\n"
        f"{e('plus')} Muốn đăng ký nhiều tài khoản, mỗi tài khoản <b>một dòng</b>, ví dụ:\n"
        f"<code>bolatienphong\nnoapq1983</code>"
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
async def buy_code_finish(message: types.Message, state: FSMContext):
    raw = message.text or ""
    if raw.strip() in MENU_TEXTS or raw.strip().startswith("/"):
        await message.answer(f"{e('no')} Tên tài khoản không hợp lệ, nhập lại:")
        return

    names = parse_usernames(raw)
    if not names:
        await message.answer(f"{e('no')} Tên tài khoản không được để trống, nhập lại:")
        return
    if len(names) > MAX_BATCH:
        await message.answer(f"{e('no')} Mỗi lần chỉ đăng ký tối đa <b>{MAX_BATCH}</b> tài khoản, nhập lại:")
        return
    if any(len(n) > 50 for n in names):
        await message.answer(f"{e('no')} Có tên tài khoản quá dài (tối đa 50 ký tự), nhập lại:")
        return

    data = await state.get_data()
    game_key = data.get("game", "78win")
    game = GAMES.get(game_key, GAMES["78win"])
    price = game["price"]
    user_id = message.from_user.id

    result = "ok"
    valid: list[str] = []
    rejected: list[str] = []
    bal = 0
    total = 0

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            # Khóa toàn cục ngắn để tránh 2 người đăng ký trùng 1 tài khoản cùng lúc
            await conn.execute("SELECT pg_advisory_xact_lock(78001)")
            row = await conn.fetchrow("SELECT balance FROM users WHERE user_id = $1 FOR UPDATE", user_id)
            bal = int(row["balance"]) if row else 0

            busy_rows = await conn.fetch(
                "SELECT lower(game_username) AS u FROM hunt_accounts "
                "WHERE game = $1 AND status = 'active' AND lower(game_username) = ANY($2::text[])",
                game_key,
                [n.lower() for n in names],
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

    rejected_text = ""
    if rejected:
        rejected_text = (
            f"\n━━━━━━━━━━━━━━━━━━\n"
            f"{e('no')} <b>Không đăng ký được ({len(rejected)})</b> - đang chờ nhập code, "
            f"chỉ đăng ký lại được khi đơn thành công hoặc bị Admin hủy:\n"
            + "\n".join(f"• <code>{escape(n)}</code>" for n in rejected)
        )

    if result == "all_busy":
        await state.clear()
        await message.answer(
            f"{e('no')} <b>Không thể đăng ký!</b>{rejected_text}",
            reply_markup=main_kb,
        )
        return

    if result == "no_balance":
        await state.clear()
        await message.answer(
            f"{e('no')} <b>Số dư không đủ!</b>\n"
            f"{e('pc')} Số tài khoản hợp lệ: <b>{len(valid)}</b>\n"
            f"{e('money')} Cần: <b>{total:,}đ</b>\n"
            f"{e('money2')} Số dư hiện tại: <b>{bal:,}đ</b>\n"
            f"{e('plus')} Bấm <b>{BTN_DEPOSIT}</b> để nạp thêm."
            f"{rejected_text}",
            reply_markup=main_kb,
        )
        return

    await message.answer(
        f"{e('ok')} <b>MUA SLOT THÀNH CÔNG!</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{e('top')} Game: <b>{game['name']}</b>\n"
        f"{e('reload')} Trạng thái: <b>Đang chờ nhập code</b>\n"
        f"{e('pc')} <b>Tài khoản ({len(valid)}):</b>\n"
        + "\n".join(f"• <code>{escape(n)}</code>" for n in valid)
        + f"\n━━━━━━━━━━━━━━━━━━\n"
        f"{e('money')} Đã trừ: <b>{total:,}đ</b>\n"
        f"{e('money2')} Số dư còn lại: <b>{bal - total:,}đ</b>"
        f"{rejected_text}",
        reply_markup=main_kb,
    )
    await state.clear()


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
            await conn.execute("UPDATE users SET balance = balance + $1 WHERE user_id = $2", amount, target_id)
        await message.answer(f"{e('ok')} Đã nạp <b>{amount:,}đ</b> cho <code>{target_id}</code>.")
        await bot.send_message(target_id, f"{e('money')} Bạn được cộng <b>{amount:,}đ</b> vào tài khoản!")
    except Exception:
        await message.answer(f"{e('no')} Cú pháp: <code>/nap &lt;user_id&gt; &lt;so_tien&gt;</code>")


@dp.message(Command("tru"))
async def admin_sub_money(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        _, target_id, amount = message.text.split()
        target_id, amount = int(target_id), int(amount)
        await get_user_balance(target_id)
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET balance = GREATEST(0, balance - $1) WHERE user_id = $2",
                amount,
                target_id,
            )
        await message.answer(f"{e('ok')} Đã trừ <b>{amount:,}đ</b> của <code>{target_id}</code>.")
    except Exception:
        await message.answer(f"{e('no')} Cú pháp: <code>/tru &lt;user_id&gt; &lt;so_tien&gt;</code>")


@dp.message(Command("huy"))
async def admin_cancel_order(message: types.Message):
    """Admin hủy đơn đang chờ nhập code của 1 tài khoản game: /huy <ten_tai_khoan>"""
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
        f"Cần hoàn tiền thì dùng <code>/nap &lt;user_id&gt; &lt;so_tien&gt;</code>."
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
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{e('pc')} Bộ quét nhóm: {scanner_status}\n"
        f"{e('shield')} Người dùng: <b>{total_users}</b>\n"
        f"{e('reload')} Tài khoản chờ nhập code: <b>{active_accs}</b>"
    )


# =====================================================================
# LỌC CODE & TỰ ĐỘNG NHẬP WEB + GIẢI CAPTCHA
# =====================================================================
def extract_clean_codes(raw_text: str) -> list[str]:
    clean_codes = []
    for w in raw_text.split():
        if w.startswith(("http", "#", "@")):
            continue
        if re.search(r"[^a-zA-Z0-9]", w) and re.search(r"[a-zA-Z0-9]", w):
            cleaned = re.sub(r"[^a-zA-Z0-9]", "", w)
            if 5 <= len(cleaned) <= 12:
                clean_codes.append(cleaned)
    return list(dict.fromkeys(clean_codes))


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
    """Lấy thông báo web trả về (để ghi chú gửi admin)."""
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
    """Trả về (trạng_thái, ghi_chú). Trạng thái: SUCCESS | FAIL."""
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
    """Gửi admin kết quả MỖI LẦN nhập code (thành công hay thất bại)."""
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


# =====================================================================
# QUÉT NHÓM LIÊN TỤC
# =====================================================================
async def start_scanner(session_str: str):
    global userbot
    if userbot and userbot.is_connected():
        await userbot.disconnect()

    userbot = TelegramClient(StringSession(session_str), API_ID, API_HASH)

    @userbot.on(events.NewMessage(chats=TARGET_GROUPS))
    async def scanner_handler(event):
        codes = extract_clean_codes(event.raw_text)
        if not codes:
            return

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
    saved_session = await get_saved_session()
    if saved_session:
        asyncio.create_task(start_scanner(saved_session))
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
