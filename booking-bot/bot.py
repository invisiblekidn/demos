"""Northside Barber Club — demo booking bot (EN / VI).

Flow: language -> service -> barber -> day -> time -> contact -> confirm.
Owner (ADMIN_IDS) gets every booking with Confirm / Decline buttons,
the client gets the answer and a reminder 2 hours before the visit.
Booked slots disappear for other clients.
"""
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

import aiosqlite
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
                           KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove)
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x}
DB_PATH = os.getenv("DB_PATH", "bookings.db")
TZ = timezone(timedelta(hours=7))  # Vietnam
SITE_URL = os.getenv("SITE_URL", "")

SERVICES = [  # (en, vi, price VND thousand, minutes)
    ("Haircut", "Cắt tóc", 150, 40),
    ("Haircut + beard", "Cắt tóc + tỉa râu", 250, 60),
    ("Beard trim", "Tỉa râu", 100, 30),
    ("Hot towel shave", "Cạo mặt khăn nóng", 120, 30),
    ("Kids haircut", "Cắt tóc trẻ em", 100, 30),
]
BARBERS = ["Minh", "Alex", "Tuấn"]
HOURS = [f"{h}:00" for h in range(10, 20)]

TXT = {
    "en": {
        "hello": "💈 <b>Northside Barber Club</b> (demo)\nBook a haircut in a few taps — pick a service, barber and time.",
        "menu_book": "✂️ Book a visit", "menu_my": "📅 My bookings", "menu_prices": "💵 Prices", "menu_lang": "🌐 Language",
        "choose_service": "Choose a service:", "choose_barber": "Choose a barber:", "any": "Any available",
        "choose_day": "Choose a day:", "choose_time": "Free time on {day}:", "no_time": "No free time this day — pick another one.",
        "today": "Today", "tomorrow": "Tomorrow",
        "ask_contact": "Almost done! Send your phone number with the button below or type it.",
        "share": "📱 Share my number",
        "summary": "<b>Check your booking</b>\n\n✂️ {svc}\n💈 {barber}\n📅 {when}\n💵 {price}\n📱 {phone}",
        "confirm": "✅ Confirm", "cancel": "✖️ Cancel", "back": "← Back",
        "sent": "🙌 Booking sent! The barbershop will confirm it shortly.",
        "approved": "✅ Your booking is confirmed: {when}, {svc}. See you!",
        "declined": "😔 Sorry, the barbershop can't take this time. Please choose another one.",
        "reminder": "⏰ Reminder: {svc} today at {time}. Address: Demo street 12, Nha Trang.",
        "my_none": "You have no upcoming bookings.", "my_title": "<b>Your bookings</b>",
        "cancelled": "Booking cancelled.", "taken": "This time was just taken — please choose another.",
        "prices": "<b>Prices</b>\n\n{list}", "status": {"new": "⏳ waiting", "ok": "✅ confirmed"},
        "lang_set": "Language: English 🇬🇧", "site": "🌐 Website",
        "days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    },
    "vi": {
        "hello": "💈 <b>Northside Barber Club</b> (demo)\nĐặt lịch cắt tóc chỉ vài chạm — chọn dịch vụ, thợ và giờ.",
        "menu_book": "✂️ Đặt lịch", "menu_my": "📅 Lịch của tôi", "menu_prices": "💵 Bảng giá", "menu_lang": "🌐 Ngôn ngữ",
        "choose_service": "Chọn dịch vụ:", "choose_barber": "Chọn thợ:", "any": "Bất kỳ thợ nào",
        "choose_day": "Chọn ngày:", "choose_time": "Giờ trống ngày {day}:", "no_time": "Ngày này đã kín — vui lòng chọn ngày khác.",
        "today": "Hôm nay", "tomorrow": "Ngày mai",
        "ask_contact": "Sắp xong! Gửi số điện thoại bằng nút bên dưới hoặc nhập số.",
        "share": "📱 Gửi số của tôi",
        "summary": "<b>Kiểm tra lịch hẹn</b>\n\n✂️ {svc}\n💈 {barber}\n📅 {when}\n💵 {price}\n📱 {phone}",
        "confirm": "✅ Xác nhận", "cancel": "✖️ Huỷ", "back": "← Quay lại",
        "sent": "🙌 Đã gửi lịch hẹn! Tiệm sẽ xác nhận ngay.",
        "approved": "✅ Lịch hẹn đã được xác nhận: {when}, {svc}. Hẹn gặp bạn!",
        "declined": "😔 Xin lỗi, tiệm không nhận được giờ này. Vui lòng chọn giờ khác.",
        "reminder": "⏰ Nhắc lịch: {svc} hôm nay lúc {time}. Địa chỉ: 12 Đường Demo, Nha Trang.",
        "my_none": "Bạn chưa có lịch hẹn nào.", "my_title": "<b>Lịch hẹn của bạn</b>",
        "cancelled": "Đã huỷ lịch hẹn.", "taken": "Giờ này vừa có người đặt — vui lòng chọn giờ khác.",
        "prices": "<b>Bảng giá</b>\n\n{list}", "status": {"new": "⏳ chờ xác nhận", "ok": "✅ đã xác nhận"},
        "lang_set": "Ngôn ngữ: Tiếng Việt 🇻🇳", "site": "🌐 Website",
        "days": ["T2", "T3", "T4", "T5", "T6", "T7", "CN"],
    },
}

router = Router()
bot: Bot


class Book(StatesGroup):
    contact = State()


# ---------- storage ----------
async def db_init():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, lang TEXT DEFAULT 'en', name TEXT);
        CREATE TABLE IF NOT EXISTS bookings(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, service INTEGER, barber INTEGER,
            day TEXT, time TEXT, phone TEXT, status TEXT DEFAULT 'new', reminded INTEGER DEFAULT 0,
            created TEXT DEFAULT CURRENT_TIMESTAMP);
        """)
        await db.commit()


async def get_lang(uid: int) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        row = await (await db.execute("SELECT lang FROM users WHERE id=?", (uid,))).fetchone()
    return row[0] if row else "en"


async def set_lang(uid: int, lang: str, name: str = ""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO users(id,lang,name) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET lang=excluded.lang",
                         (uid, lang, name))
        await db.commit()


async def taken_times(day: str, barber: int) -> set[str]:
    """Times that are busy for this barber (barber 0 = any: busy only if all barbers are busy)."""
    async with aiosqlite.connect(DB_PATH) as db:
        rows = await (await db.execute(
            "SELECT time, barber FROM bookings WHERE day=? AND status IN ('new','ok')", (day,))).fetchall()
    if barber:
        return {t for t, b in rows if b == barber}
    count: dict[str, int] = {}
    for t, _ in rows:
        count[t] = count.get(t, 0) + 1
    return {t for t, c in count.items() if c >= len(BARBERS)}


async def free_barber(day: str, time: str) -> int | None:
    async with aiosqlite.connect(DB_PATH) as db:
        rows = await (await db.execute(
            "SELECT barber FROM bookings WHERE day=? AND time=? AND status IN ('new','ok')", (day, time))).fetchall()
    busy = {r[0] for r in rows}
    for i in range(1, len(BARBERS) + 1):
        if i not in busy:
            return i
    return None


# ---------- helpers ----------
def price(k: int) -> str:
    return f"{k:,}.000₫".replace(",", ".")


def svc_name(i: int, lang: str) -> str:
    return SERVICES[i][0 if lang == "en" else 1]


def day_label(d: datetime, lang: str) -> str:
    t = TXT[lang]
    today = datetime.now(TZ).date()
    if d.date() == today:
        return f"{t['today']} {d:%d.%m}"
    if d.date() == today + timedelta(days=1):
        return f"{t['tomorrow']} {d:%d.%m}"
    return f"{t['days'][d.weekday()]} {d:%d.%m}"


def when_text(day: str, time: str, lang: str) -> str:
    return f"{day_label(datetime.strptime(day, '%Y-%m-%d').replace(tzinfo=TZ), lang)}, {time}"


def main_kb(lang: str) -> ReplyKeyboardMarkup:
    t = TXT[lang]
    return ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
        [KeyboardButton(text=t["menu_book"])],
        [KeyboardButton(text=t["menu_my"]), KeyboardButton(text=t["menu_prices"])],
        [KeyboardButton(text=t["menu_lang"])],
    ])


def ikb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=a, callback_data=b) for a, b in r] for r in rows])


def lang_kb() -> InlineKeyboardMarkup:
    return ikb([[("🇬🇧 English", "lang:en"), ("🇻🇳 Tiếng Việt", "lang:vi")]])


def services_kb(lang: str) -> InlineKeyboardMarkup:
    return ikb([[(f"{svc_name(i, lang)} · {price(s[2])}", f"svc:{i}")] for i, s in enumerate(SERVICES)])


def barbers_kb(lang: str, svc: int) -> InlineKeyboardMarkup:
    rows = [[(TXT[lang]["any"], f"bar:{svc}:0")]] + [[(f"💈 {b}", f"bar:{svc}:{i + 1}")] for i, b in enumerate(BARBERS)]
    rows.append([(TXT[lang]["back"], "book")])
    return ikb(rows)


def days_kb(lang: str, svc: int, bar: int) -> InlineKeyboardMarkup:
    now = datetime.now(TZ)
    btns = [(day_label(now + timedelta(days=i), lang), f"day:{svc}:{bar}:{(now + timedelta(days=i)):%Y-%m-%d}") for i in range(7)]
    rows = [btns[i:i + 2] for i in range(0, 7, 2)]
    rows.append([(TXT[lang]["back"], f"svc:{svc}")])
    return ikb(rows)


async def times_kb(lang: str, svc: int, bar: int, day: str) -> InlineKeyboardMarkup | None:
    busy = await taken_times(day, bar)
    now = datetime.now(TZ)
    free = []
    for t in HOURS:
        slot = datetime.strptime(f"{day} {t}", "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
        if t not in busy and slot > now + timedelta(minutes=30):
            free.append((t, f"time:{svc}:{bar}:{day}:{t.replace(':', '-')}"))
    if not free:
        return None
    rows = [free[i:i + 4] for i in range(0, len(free), 4)]
    rows.append([(TXT[lang]["back"], f"bar:{svc}:{bar}")])
    return ikb(rows)


# ---------- client ----------
@router.message(CommandStart())
async def start(m: Message, state: FSMContext):
    await state.clear()
    async with aiosqlite.connect(DB_PATH) as db:
        known = await (await db.execute("SELECT 1 FROM users WHERE id=?", (m.from_user.id,))).fetchone()
    if not known:
        await m.answer("Choose your language / Chọn ngôn ngữ:", reply_markup=lang_kb())
        return
    lang = await get_lang(m.from_user.id)
    await m.answer(TXT[lang]["hello"], reply_markup=main_kb(lang))


@router.message(Command("id"))
async def my_id(m: Message):
    await m.answer(f"Your ID: <code>{m.from_user.id}</code>")


@router.callback_query(F.data.startswith("lang:"))
async def choose_lang(c: CallbackQuery):
    lang = c.data.split(":")[1]
    await set_lang(c.from_user.id, lang, c.from_user.full_name)
    await c.message.edit_text(TXT[lang]["lang_set"])
    await c.message.answer(TXT[lang]["hello"], reply_markup=main_kb(lang))
    await c.answer()


@router.message(F.text.in_({TXT["en"]["menu_lang"], TXT["vi"]["menu_lang"]}))
async def menu_lang(m: Message):
    await m.answer("Choose your language / Chọn ngôn ngữ:", reply_markup=lang_kb())


@router.message(F.text.in_({TXT["en"]["menu_prices"], TXT["vi"]["menu_prices"]}))
async def menu_prices(m: Message):
    lang = await get_lang(m.from_user.id)
    lst = "\n".join(f"✂️ {svc_name(i, lang)} — <b>{price(s[2])}</b> · {s[3]} min" for i, s in enumerate(SERVICES))
    kb = ikb([[(TXT[lang]["menu_book"], "book")]])
    await m.answer(TXT[lang]["prices"].format(list=lst), reply_markup=kb)


@router.message(F.text.in_({TXT["en"]["menu_book"], TXT["vi"]["menu_book"]}))
async def menu_book(m: Message, state: FSMContext):
    await state.clear()
    lang = await get_lang(m.from_user.id)
    await m.answer(TXT[lang]["choose_service"], reply_markup=services_kb(lang))


@router.callback_query(F.data == "book")
async def cb_book(c: CallbackQuery):
    lang = await get_lang(c.from_user.id)
    await c.message.edit_text(TXT[lang]["choose_service"], reply_markup=services_kb(lang))
    await c.answer()


@router.callback_query(F.data.startswith("svc:"))
async def cb_service(c: CallbackQuery):
    lang = await get_lang(c.from_user.id)
    svc = int(c.data.split(":")[1])
    await c.message.edit_text(f"✂️ <b>{svc_name(svc, lang)}</b>\n\n{TXT[lang]['choose_barber']}", reply_markup=barbers_kb(lang, svc))
    await c.answer()


@router.callback_query(F.data.startswith("bar:"))
async def cb_barber(c: CallbackQuery):
    lang = await get_lang(c.from_user.id)
    _, svc, bar = c.data.split(":")
    svc, bar = int(svc), int(bar)
    who = BARBERS[bar - 1] if bar else TXT[lang]["any"]
    await c.message.edit_text(f"✂️ <b>{svc_name(svc, lang)}</b> · 💈 {who}\n\n{TXT[lang]['choose_day']}", reply_markup=days_kb(lang, svc, bar))
    await c.answer()


@router.callback_query(F.data.startswith("day:"))
async def cb_day(c: CallbackQuery):
    lang = await get_lang(c.from_user.id)
    _, svc, bar, day = c.data.split(":")
    svc, bar = int(svc), int(bar)
    kb = await times_kb(lang, svc, bar, day)
    if kb is None:
        await c.answer(TXT[lang]["no_time"], show_alert=True)
        return
    label = day_label(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=TZ), lang)
    await c.message.edit_text(TXT[lang]["choose_time"].format(day=label), reply_markup=kb)
    await c.answer()


@router.callback_query(F.data.startswith("time:"))
async def cb_time(c: CallbackQuery, state: FSMContext):
    lang = await get_lang(c.from_user.id)
    _, svc, bar, day, t = c.data.split(":")
    await state.set_state(Book.contact)
    await state.update_data(svc=int(svc), bar=int(bar), day=day, time=t.replace("-", ":"))
    await c.message.edit_reply_markup(reply_markup=None)
    kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True,
                             keyboard=[[KeyboardButton(text=TXT[lang]["share"], request_contact=True)]])
    await c.message.answer(TXT[lang]["ask_contact"], reply_markup=kb)
    await c.answer()


@router.message(Book.contact)
async def got_contact(m: Message, state: FSMContext):
    lang = await get_lang(m.from_user.id)
    phone = m.contact.phone_number if m.contact else (m.text or "").strip()
    if len(phone) < 5:
        await m.answer(TXT[lang]["ask_contact"])
        return
    await state.update_data(phone=phone)
    d = await state.get_data()
    who = BARBERS[d["bar"] - 1] if d["bar"] else TXT[lang]["any"]
    text = TXT[lang]["summary"].format(svc=svc_name(d["svc"], lang), barber=who, when=when_text(d["day"], d["time"], lang),
                                       price=price(SERVICES[d["svc"]][2]), phone=phone)
    await m.answer("👌", reply_markup=main_kb(lang))
    await m.answer(text, reply_markup=ikb([[(TXT[lang]["confirm"], "confirm"), (TXT[lang]["cancel"], "abort")]]))


@router.callback_query(F.data == "abort")
async def cb_abort(c: CallbackQuery, state: FSMContext):
    lang = await get_lang(c.from_user.id)
    await state.clear()
    await c.message.edit_text(TXT[lang]["cancelled"])
    await c.answer()


@router.callback_query(F.data == "confirm")
async def cb_confirm(c: CallbackQuery, state: FSMContext):
    lang = await get_lang(c.from_user.id)
    d = await state.get_data()
    if not d:
        await c.answer()
        return
    bar = d["bar"]
    if bar == 0:
        bar = await free_barber(d["day"], d["time"])
    elif d["time"] in await taken_times(d["day"], bar):
        bar = None
    if not bar:
        await state.clear()
        await c.message.edit_text(TXT[lang]["taken"], reply_markup=services_kb(lang))
        await c.answer()
        return
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("INSERT INTO bookings(user_id,service,barber,day,time,phone) VALUES(?,?,?,?,?,?)",
                               (c.from_user.id, d["svc"], bar, d["day"], d["time"], d["phone"]))
        await db.commit()
        bid = cur.lastrowid
    await state.clear()
    await c.message.edit_text(TXT[lang]["sent"])
    await c.answer()
    card = (f"🆕 <b>Booking #{bid}</b>\n\n✂️ {SERVICES[d['svc']][0]} · {price(SERVICES[d['svc']][2])}\n💈 {BARBERS[bar - 1]}\n"
            f"📅 {when_text(d['day'], d['time'], 'en')}\n👤 {c.from_user.full_name}"
            f"{' @' + c.from_user.username if c.from_user.username else ''}\n📱 {d['phone']}")
    kb = ikb([[("✅ Confirm", f"adm:ok:{bid}"), ("❌ Decline", f"adm:no:{bid}")]])
    for admin in ADMIN_IDS:
        try:
            await bot.send_message(admin, card, reply_markup=kb)
        except Exception as e:  # admin hasn't started the bot yet
            logging.warning("cannot notify admin %s: %s", admin, e)


@router.message(F.text.in_({TXT["en"]["menu_my"], TXT["vi"]["menu_my"]}))
async def menu_my(m: Message):
    lang = await get_lang(m.from_user.id)
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        rows = await (await db.execute(
            "SELECT id,service,barber,day,time,status FROM bookings WHERE user_id=? AND day>=? AND status IN ('new','ok') ORDER BY day,time",
            (m.from_user.id, today))).fetchall()
    if not rows:
        await m.answer(TXT[lang]["my_none"])
        return
    for bid, svc, bar, day, t, status in rows:
        await m.answer(f"📅 <b>{when_text(day, t, lang)}</b>\n✂️ {svc_name(svc, lang)} · 💈 {BARBERS[bar - 1]}\n{TXT[lang]['status'][status]}",
                       reply_markup=ikb([[(TXT[lang]["cancel"], f"my:cancel:{bid}")]]))


@router.callback_query(F.data.startswith("my:cancel:"))
async def my_cancel(c: CallbackQuery):
    lang = await get_lang(c.from_user.id)
    bid = int(c.data.split(":")[2])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE bookings SET status='cancelled' WHERE id=? AND user_id=?", (bid, c.from_user.id))
        await db.commit()
    await c.message.edit_text(TXT[lang]["cancelled"])
    await c.answer()
    for admin in ADMIN_IDS:
        try:
            await bot.send_message(admin, f"✖️ Booking #{bid} was cancelled by the client.")
        except Exception:
            pass


# ---------- owner ----------
@router.callback_query(F.data.startswith("adm:"))
async def admin_action(c: CallbackQuery):
    if c.from_user.id not in ADMIN_IDS:
        await c.answer()
        return
    _, act, bid = c.data.split(":")
    async with aiosqlite.connect(DB_PATH) as db:
        row = await (await db.execute("SELECT user_id,service,day,time FROM bookings WHERE id=?", (int(bid),))).fetchone()
        await db.execute("UPDATE bookings SET status=? WHERE id=?", ("ok" if act == "ok" else "declined", int(bid)))
        await db.commit()
    if not row:
        await c.answer()
        return
    uid, svc, day, t = row
    lang = await get_lang(uid)
    msg = (TXT[lang]["approved"].format(when=when_text(day, t, lang), svc=svc_name(svc, lang)) if act == "ok"
           else TXT[lang]["declined"])
    await bot.send_message(uid, msg, reply_markup=None if act == "ok" else services_kb(lang))
    await c.message.edit_text(c.message.html_text + ("\n\n✅ <b>Confirmed</b>" if act == "ok" else "\n\n❌ <b>Declined</b>"))
    await c.answer()


@router.message(Command("today"))
async def admin_today(m: Message):
    if m.from_user.id not in ADMIN_IDS:
        return
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        rows = await (await db.execute(
            "SELECT time,barber,service,phone,status FROM bookings WHERE day=? AND status IN ('new','ok') ORDER BY time",
            (today,))).fetchall()
    if not rows:
        await m.answer("No bookings today.")
        return
    lines = [f"{t} · 💈 {BARBERS[b - 1]} · {SERVICES[s][0]} · {p} {'✅' if st == 'ok' else '⏳'}" for t, b, s, p, st in rows]
    await m.answer("<b>Today</b>\n\n" + "\n".join(lines))


# ---------- reminders ----------
async def reminder_loop():
    while True:
        try:
            now = datetime.now(TZ)
            async with aiosqlite.connect(DB_PATH) as db:
                rows = await (await db.execute(
                    "SELECT id,user_id,service,day,time FROM bookings WHERE status='ok' AND reminded=0")).fetchall()
                for bid, uid, svc, day, t in rows:
                    slot = datetime.strptime(f"{day} {t}", "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
                    if now <= slot <= now + timedelta(hours=2):
                        lang = await get_lang(uid)
                        await bot.send_message(uid, TXT[lang]["reminder"].format(svc=svc_name(svc, lang), time=t))
                        await db.execute("UPDATE bookings SET reminded=1 WHERE id=?", (bid,))
                await db.commit()
        except Exception as e:
            logging.warning("reminder loop: %s", e)
        await asyncio.sleep(60)


async def main():
    global bot
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN is empty — put it into .env (see .env.example)")
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await db_init()
    dp = Dispatcher()
    dp.include_router(router)
    asyncio.create_task(reminder_loop())
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
