"""
Telegram bot with daily vinyl suggestion scheduler.

Commands:
  /start   – welcome message
  /suggest – request a suggestion right now
  /history – show last 10 suggestions
"""
import asyncio
import datetime
import logging
from logging.handlers import RotatingFileHandler

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.constants import ParseMode

import config
import database
import recommender

_handler = RotatingFileHandler(
    config.LOG_PATH,
    maxBytes=500_000,
    backupCount=2,
    encoding="utf-8",
)
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    level=logging.INFO,
    handlers=[_handler, logging.StreamHandler()],
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Message formatting
# ---------------------------------------------------------------------------

def format_suggestion(s: dict) -> str:
    year_str = f" ({s['year']})" if s.get("year") else ""
    fmt_emoji = "📼" if s.get("format", "").lower() == "cassette" else "🎵"
    have = s.get("have", 0)
    want = s.get("want", 0)
    rarity_bar = s.get("rarity_bar", "💎")
    rarity_label = s.get("rarity_label", "")

    return (
        f"{fmt_emoji} *{s['artist']}* – _{s['title']}{year_str}_\n\n"
        f"{s['why']}\n\n"
        f"*Rarity:* {rarity_bar} {rarity_label}\n"
        f"_{have} collectors own it · {want} want it_\n\n"
        f"🔗 [View on Discogs]({s['discogs_url']})"
    )


def rating_keyboard(discogs_id: str) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(f"{i}★", callback_data=f"rate:{discogs_id}:{i}")
        for i in range(1, 6)
    ]
    return InlineKeyboardMarkup([buttons])


def rated_keyboard(rating: int) -> InlineKeyboardMarkup:
    stars = "★" * rating + "☆" * (5 - rating)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"You rated: {stars}", callback_data="noop")]
    ])


# ---------------------------------------------------------------------------
# Bot command handlers
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hi\\! I'm your personal vinyl curator\\.\n\n"
        "Every day I'll suggest a vinyl or cassette record based on your Discogs taste\\.\n\n"
        "Commands:\n"
        "  /suggest – get a suggestion right now\n"
        "  /history – see the last 10 suggestions",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


async def cmd_suggest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔍 Analysing your taste… hang tight!")
    suggestion = await asyncio.to_thread(recommender.get_suggestion)
    if suggestion is None:
        await msg.edit_text("😕 Couldn't find a good suggestion right now. Try again later.")
        return
    database.record_suggestion(
        suggestion["discogs_id"],
        suggestion["artist"],
        suggestion["title"],
        suggestion.get("format", ""),
        suggestion.get("genre", ""),
    )
    await msg.edit_text(
        format_suggestion(suggestion),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=rating_keyboard(suggestion["discogs_id"]),
    )


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    history = database.get_history(limit=10)
    if not history:
        await update.message.reply_text("No suggestions sent yet.")
        return
    lines = ["*Recent suggestions:*\n"]
    for i, h in enumerate(history, 1):
        date = h["sent_at"][:10]
        rating_str = f" {'★' * h['rating']}" if h.get("rating") else ""
        fmt_str = f" [{h['format']}]" if h.get("format") else ""
        lines.append(f"{i}. *{h['artist']}* – _{h['title']}_{fmt_str}{rating_str} ({date})")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ---------------------------------------------------------------------------
# Rating callback handler
# ---------------------------------------------------------------------------

async def handle_rating(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "noop":
        return

    _, discogs_id, rating_str = query.data.split(":")
    rating = int(rating_str)

    database.update_rating(discogs_id, rating)
    await query.edit_message_reply_markup(reply_markup=rated_keyboard(rating))
    log.info(f"User rated {discogs_id} → {rating}★")


# ---------------------------------------------------------------------------
# Daily scheduled job (uses built-in JobQueue)
# ---------------------------------------------------------------------------

async def catchup_check(context: ContextTypes.DEFAULT_TYPE):
    """Runs every 15 min. If the scheduled time has passed and no suggestion was
    sent today (e.g. Mac was asleep), send it now."""
    now = datetime.datetime.now(datetime.timezone.utc)
    scheduled = now.replace(hour=config.DAILY_HOUR, minute=config.DAILY_MINUTE, second=0, microsecond=0)
    if now >= scheduled and not database.suggestion_sent_today():
        log.info("Catch-up check: missed today's suggestion — sending now…")
        await daily_suggestion(context)


async def daily_suggestion(context: ContextTypes.DEFAULT_TYPE):
    log.info("Running daily suggestion job…")
    suggestion = await asyncio.to_thread(recommender.get_suggestion)
    if suggestion is None:
        log.warning("No suggestion generated today.")
        await context.bot.send_message(
            chat_id=config.TELEGRAM_CHAT_ID,
            text="😕 Couldn't find a vinyl suggestion for today. Try /suggest manually.",
        )
        return
    database.record_suggestion(
        suggestion["discogs_id"],
        suggestion["artist"],
        suggestion["title"],
        suggestion.get("format", ""),
        suggestion.get("genre", ""),
    )
    await context.bot.send_message(
        chat_id=config.TELEGRAM_CHAT_ID,
        text=format_suggestion(suggestion),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=rating_keyboard(suggestion["discogs_id"]),
    )
    log.info(f"Sent daily suggestion: {suggestion['artist']} – {suggestion['title']}")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    config.validate()
    database.init_db()

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("suggest", cmd_suggest))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CallbackQueryHandler(handle_rating))

    # Use the built-in JobQueue — fully integrated with the bot's async event loop
    send_time = datetime.time(
        hour=config.DAILY_HOUR,
        minute=config.DAILY_MINUTE,
        tzinfo=datetime.timezone.utc,
    )
    app.job_queue.run_daily(daily_suggestion, time=send_time)
    log.info(f"Daily suggestion scheduled at {config.DAILY_HOUR:02d}:{config.DAILY_MINUTE:02d} UTC")

    # Watchdog: every 15 min, catch missed suggestions (e.g. Mac was asleep at scheduled time)
    app.job_queue.run_repeating(catchup_check, interval=900, first=60)
    log.info("Catch-up watchdog scheduled every 15 minutes")

    # Catch-up: if the Mac was asleep at scheduled time, send on startup
    async def post_init(application: Application):
        if not database.suggestion_sent_today():
            log.info("No suggestion sent today yet — sending catch-up suggestion…")
            await daily_suggestion(type("ctx", (), {"bot": application.bot})())

    app.post_init = post_init

    log.info("Bot starting…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
