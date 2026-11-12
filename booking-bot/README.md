# Booking bot for a barbershop (demo)

Telegram bot for online booking, English / Vietnamese. Python 3.11+, aiogram 3, SQLite.

**Client:** language → service → barber (or "any available") → day (7 days ahead) → free time → phone → confirm.
"My bookings" with cancel, price list, reminder 2 hours before a confirmed visit.

**Owner:** every booking arrives as a card with ✅ Confirm / ❌ Decline; the client gets the answer automatically.
`/today` — today's schedule. Busy slots disappear for other clients; "any available" picks a free barber.

## Run

```
python -m venv venv
venv\Scripts\pip install -r requirements.txt
copy .env.example .env      # put BOT_TOKEN from @BotFather
venv\Scripts\python bot.py  # send /id to the bot, put the number into ADMIN_IDS, restart
```

Services, barbers and hours are at the top of `bot.py` (`SERVICES`, `BARBERS`, `HOURS`).

Made by [invisiblekidn](https://kwork.com/user/invisiblekidn).
