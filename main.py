import asyncio
import os
import re
from io import BytesIO
from PIL import Image, ImageEnhance
import asyncpg
import ddddocr
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from playwright.async_api import async_playwright

# --- CẤU HÌNH TRỰC TIẾP (CHỈ CẦN ĐIỀN HOẶC ĐỂ TRONG ENV RAILWAY) ---
API_ID = int(os.getenv("API_ID", "30309186"))
API_HASH = os.getenv("API_HASH", "307273bc278e53017b5fdcd407c1d941")
PHONE_NUMBER = os.getenv("PHONE_NUMBER", "+84335442999")
SESSION_STRING = os.getenv("SESSION_STRING", "")

BOT_TOKEN = os.getenv("BOT_TOKEN", "9044293543:AAEFP_xv45GUuR76f382cekrDOaCjdE2zLw")
ADMIN_ID = int(os.getenv("ADMIN_ID", "9220244280"))

# Railway tự cấp DATABASE_URL khi bạn thêm plugin PostgreSQL
DATABASE_URL = os.getenv("DATABASE_URL", "")

TARGET_GROUPS = ["official78wins", "FreeCode_78win"]
TARGET_URL = "https://code78k.online/"
CODE_PRICE = 10000

# --- KHỞI TẠO BOT, USERBOT & OCR ---
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
userbot = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
ocr = ddddocr.DdddOcr(show_ad=False)
db_pool: asyncpg.Pool | None = None


class BuyCodeState(StatesGroup):
    waiting_for_username = State()


main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🎁 Nhập code"), KeyboardButton(text="💰 Số dư & Nạp tiền")],
        [KeyboardButton(text="📋 Danh sách tài khoản đang săn")],
    ],
    resize_keyboard=True,
)


async def init_db():
    global db_pool
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


async def get_user_balance(user_id: int) -> int:
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO users (user_id, balance) VALUES ($1, 0) ON CONFLICT (user_id) DO NOTHING",
            user_id,
        )
        row = await conn.fetchrow("SELECT balance FROM users WHERE user_id = $1", user_id)
        return int(row["balance"]) if row else 0


# --- LỆNH NGƯỜI DÙNG ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    bal = await get_user_balance(message.from_user.id)
    await message.answer(
        f"👋 Hệ thống tự động săn Code 78WIN\n"
        f"💵 Số dư: **{bal:,}đ**\n"
        f"🏷 Giá đăng ký: **{CODE_PRICE:,}đ / tài khoản**",
        reply_markup=main_kb,
        parse_mode="Markdown",
    )


@dp.message(F.text == "💰 Số dư & Nạp tiền")
async def check_balance(message: types.Message):
    bal = await get_user_balance(message.from_user.id)
    await message.answer(
        f"🆔 ID của bạn: `{message.from_user.id}`\n"
        f"💵 Số dư: **{bal:,}đ**\n"
        f"👉 Gửi ID trên cho Admin để nạp tiền.",
        parse_mode="Markdown",
    )


@dp.message(F.text == "🎁 Nhập code")
async def buy_code_start(message: types.Message, state: FSMContext):
    bal = await get_user_balance(message.from_user.id)
    if bal < CODE_PRICE:
        await message.answer(f"❌ Số dư không đủ! Cần tối thiểu {CODE_PRICE:,}đ.")
        return
    await message.answer("✍️ Nhập **tên tài khoản đăng ký** cần săn code:")
    await state.set_state(BuyCodeState.waiting_for_username)


@dp.message(BuyCodeState.waiting_for_username)
async def buy_code_finish(message: types.Message, state: FSMContext):
    game_user = message.text.strip()
    user_id = message.from_user.id

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("SELECT balance FROM users WHERE user_id = $1 FOR UPDATE", user_id)
            bal = int(row["balance"]) if row else 0
            if bal < CODE_PRICE:
                await message.answer("❌ Số dư không đủ!")
                await state.clear()
                return
            await conn.execute("UPDATE users SET balance = balance - $1 WHERE user_id = $2", CODE_PRICE, user_id)
            await conn.execute(
                "INSERT INTO hunt_accounts (user_id, game_username, status) VALUES ($1, $2, 'active')",
                user_id,
                game_user,
            )

    await message.answer(
        f"✅ Đã lưu tài khoản `{game_user}` vào hệ thống chờ săn code!\n"
        f"💸 Đã trừ: {CODE_PRICE:,}đ",
        parse_mode="Markdown",
    )
    await state.clear()


@dp.message(F.text == "📋 Danh sách tài khoản đang săn")
async def list_accounts(message: types.Message):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT game_username, status FROM hunt_accounts WHERE user_id = $1 ORDER BY id DESC",
            message.from_user.id,
        )
    if not rows:
        await message.answer("📭 Chưa có tài khoản nào đang chờ.")
        return
    lines = ["📋 **Danh sách tài khoản:**"]
    for idx, r in enumerate(rows, 1):
        icon = "🟢 Đang chờ săn" if r["status"] == "active" else "✅ Đã trúng code"
        lines.append(f"{idx}. `{r['game_username']}` - {icon}")
    await message.answer("\n".join(lines), parse_mode="Markdown")


# --- LỆNH ADMIN ---
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
        await message.answer(f"✅ Đã nạp **{amount:,}đ** cho `{target_id}`.", parse_mode="Markdown")
        await bot.send_message(target_id, f"💰 Bạn được cộng **{amount:,}đ** vào tài khoản!", parse_mode="Markdown")
    except Exception:
        await message.answer("⚠️ Cú pháp: `/nap <user_id> <so_tien>`", parse_mode="Markdown")


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
        await message.answer(f"✅ Đã trừ **{amount:,}đ** của `{target_id}`.", parse_mode="Markdown")
    except Exception:
        await message.answer("⚠️ Cú pháp: `/tru <user_id> <so_tien>`", parse_mode="Markdown")


@dp.message(Command("thongke"))
async def admin_stats(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    async with db_pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
        active_accs = await conn.fetchval("SELECT COUNT(*) FROM hunt_accounts WHERE status = 'active'")
    await message.answer(
        f"📊 **THỐNG KÊ**\n👥 Người dùng: {total_users}\n🎯 Tài khoản chờ săn: {active_accs}",
        parse_mode="Markdown",
    )


# --- LỌC CODE & TỰ ĐỘNG NHẬP WEB + GIẢI CAPTCHA ---
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


def doc_captcha(img_bytes: bytes) -> str:
    img = Image.open(BytesIO(img_bytes)).convert("L")
    w, h = img.size
    img = img.resize((w * 3, h * 3), Image.Resampling.LANCZOS)
    img = ImageEnhance.Contrast(img).enhance(1.8)
    buf = BytesIO()
    img.save(buf, format="PNG")
    text = ocr.classification(buf.getvalue())
    return re.sub(r"[^a-zA-Z0-9]", "", text)


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
        captcha_text = doc_captcha(img_bytes)

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


async def chay_san_code_cho_tai_khoan(codes: list[str], game_username: str) -> str | None:
    executable = "/run/current-system/sw/bin/chromium" if os.path.exists("/run/current-system/sw/bin/chromium") else None
    async with async_playwright() as p:
        launch_args = {"headless": True}
        if executable:
            launch_args["executable_path"] = executable
        browser = await p.chromium.launch(**launch_args)
        page = await browser.new_page()
        try:
            for code in codes:
                if await thu_mot_code(page, code, game_username) == "SUCCESS":
                    return code
            return None
        finally:
            await browser.close()


# --- QUÉT NHÓM LIÊN TỤC ---
@userbot.on(events.NewMessage(chats=TARGET_GROUPS))
async def scanner_handler(event):
    codes = extract_clean_codes(event.raw_text)
    if not codes:
        return

    async with db_pool.acquire() as conn:
        accounts = await conn.fetch("SELECT id, user_id, game_username FROM hunt_accounts WHERE status = 'active'")

    for acc in accounts:
        record_id = acc["id"]
        owner_id = acc["user_id"]
        game_user = acc["game_username"]

        won_code = await chay_san_code_cho_tai_khoan(codes, game_user)
        if won_code:
            async with db_pool.acquire() as conn:
                await conn.execute("UPDATE hunt_accounts SET status = 'done' WHERE id = $1", record_id)
            msg = f"🎉 **TRÚNG CODE!**\n👤 Tài khoản: `{game_user}`\n🎫 Mã code: `{won_code}`"
            await bot.send_message(ADMIN_ID, msg, parse_mode="Markdown")
            await bot.send_message(owner_id, msg, parse_mode="Markdown")
        else:
            await bot.send_message(
                owner_id,
                f"⏳ Đợt code hiện tại chưa khớp cho `{game_user}`. Hệ thống giữ tài khoản để chờ đợt code tiếp theo.",
                parse_mode="Markdown",
            )


async def main():
    await init_db()
    await userbot.start(phone=PHONE_NUMBER)
    await asyncio.gather(
        userbot.run_until_disconnected(),
        dp.start_polling(bot),
    )


if __name__ == "__main__":
    asyncio.run(main())
