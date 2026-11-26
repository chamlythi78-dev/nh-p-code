import asyncio
import os
import re
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
# CẤU HÌNH  (khai báo trong Variables của Railway, KHÔNG ghi thẳng vào code)
# =====================================================================
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
PHONE_NUMBER = os.environ["PHONE_NUMBER"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ["ADMIN_ID"])
DATABASE_URL = os.getenv("DATABASE_URL", "")

TARGET_GROUPS = ["official78wins", "FreeCode_78win"]
TARGET_URL = "https://code78k.online/"
CODE_PRICE = 10000

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


# Nút menu chính (text thuần để bắt sự kiện, emoji premium hiển thị qua icon)
BTN_CODE = "Nhập Code"
BTN_ACCOUNT = "Tài Khoản"
BTN_DEPOSIT = "Nạp Tiền"

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
        # Cột game để mở rộng nhiều loại nhập code sau này (dữ liệu cũ mặc định 78win)
        await conn.execute("ALTER TABLE hunt_accounts ADD COLUMN IF NOT EXISTS game TEXT DEFAULT '78win'")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)


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
            "SELECT game_username, status, game FROM hunt_accounts WHERE user_id = $1 ORDER BY id DESC",
            uid,
        )

    lines = [
        f"{e('shield')} <b>THÔNG TIN TÀI KHOẢN</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"{e('link')} ID của bạn: <code>{uid}</code>",
        f"{e('money')} Số dư: <b>{bal:,}đ</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"{e('pc')} <b>Danh sách tài khoản:</b>",
    ]
    if not rows:
        lines.append(f"{e('no')} Chưa có tài khoản nào đang chờ nhập code.")
    else:
        for idx, r in enumerate(rows, 1):
            game_name = GAMES.get(r["game"] or "78win", {}).get("name", "78WIN")
            if r["status"] == "active":
                status = f"{e('reload')} Đang chờ nhập code"
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
        f"{e('mail')} Nhập <b>tên tài khoản đăng ký</b> cần nhập code:"
    )
    await call.answer()


@dp.message(BotStates.waiting_for_username)
async def buy_code_finish(message: types.Message, state: FSMContext):
    game_user = (message.text or "").strip()
    if not game_user or game_user in (BTN_CODE, BTN_ACCOUNT, BTN_DEPOSIT) or game_user.startswith("/"):
        await message.answer(f"{e('no')} Tên tài khoản không hợp lệ, nhập lại:")
        return

    data = await state.get_data()
    game_key = data.get("game", "78win")
    game = GAMES.get(game_key, GAMES["78win"])
    price = game["price"]
    user_id = message.from_user.id

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("SELECT balance FROM users WHERE user_id = $1 FOR UPDATE", user_id)
            bal = int(row["balance"]) if row else 0
            if bal < price:
                await message.answer(f"{e('no')} Số dư không đủ!")
                await state.clear()
                return
            await conn.execute("UPDATE users SET balance = balance - $1 WHERE user_id = $2", price, user_id)
            await conn.execute(
                "INSERT INTO hunt_accounts (user_id, game_username, status, game) VALUES ($1, $2, 'active', $3)",
                user_id,
                game_user,
                game_key,
            )
            new_bal = bal - price

    await message.answer(
        f"{e('ok')} <b>MUA SLOT THÀNH CÔNG!</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{e('top')} Game: <b>{game['name']}</b>\n"
        f"{e('pc')} Tài khoản: <code>{escape(game_user)}</code>\n"
        f"{e('reload')} Trạng thái: <b>Đang chờ nhập code</b>\n"
        f"{e('money')} Đã trừ: <b>{price:,}đ</b>\n"
        f"{e('money2')} Số dư còn lại: <b>{new_bal:,}đ</b>",
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


async def thu_mot_code(page, code: str, game_username: str, max_captcha_retry: int = 4) -> str:
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
            return "SUCCESS"

        if "captcha" in body_text or "mã xác thực" in body_text or "không đúng" in body_text:
            await refresh_captcha_image(page, captcha_img, captcha_input)
            continue

        return "NEXT_CODE"

    return "NEXT_CODE"


async def chay_nhap_code_cho_tai_khoan(codes: list[str], game_username: str) -> str | None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            for code in codes:
                if await thu_mot_code(page, code, game_username) == "SUCCESS":
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
                won_code = await chay_nhap_code_cho_tai_khoan(codes, game_user)
                if won_code:
                    async with db_pool.acquire() as conn:
                        await conn.execute("UPDATE hunt_accounts SET status = 'done' WHERE id = $1", record_id)
                    msg = (
                        f"{e('fire')} <b>NHẬP CODE THÀNH CÔNG!</b> {e('top')}\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"{e('pc')} Tài khoản: <code>{escape(game_user)}</code>\n"
                        f"{e('new')} Mã code: <code>{escape(won_code)}</code>"
                    )
                    await bot.send_message(ADMIN_ID, msg)
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
