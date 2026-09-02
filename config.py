import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

DISCOGS_TOKEN = os.getenv("DISCOGS_TOKEN")
DISCOGS_USERNAME = os.getenv("DISCOGS_USERNAME")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

DAILY_HOUR = int(os.getenv("DAILY_HOUR", 9))
DAILY_MINUTE = int(os.getenv("DAILY_MINUTE", 0))

DB_PATH = os.path.join(os.path.dirname(__file__), "suggestions.db")
CACHE_PATH = os.path.join(os.path.dirname(__file__), "discogs_cache.json")
LOG_PATH = os.path.join(os.path.dirname(__file__), "bot.log")
CACHE_TTL_HOURS = 168  # 1 week

# ---------------------------------------------------------------------------
# Suggestion algorithm tuning
# ---------------------------------------------------------------------------

# Weighted-random pick of the daily exploration mode.
MODE_WEIGHTS = {"core": 0.50, "adjacent": 0.30, "wildcard": 0.20}

# A record whose cheapest listing exceeds this (account currency) is "absurd"
# and gets skipped / triggers a reissue fallback.
ABSURD_PRICE = 80.0

# Currency passed to Discogs and shown in the message.
PRICE_CURRENCY_CODE = "EUR"
PRICE_CURRENCY_SYMBOL = "€"

# How many collection records to pass to Claude as "anchors" each run.
ANCHOR_COUNT = 3

# Community "have" count considered discoverable-but-not-ubiquitous.
DISCOVERABLE_HAVE_RANGE = (200, 3000)

# Candidate scoring weights.
SCORE_WEIGHTS = {"novelty": 1.0, "mode_fit": 0.6, "discoverable": 0.3, "price_band": 0.3}

def validate():
    required = {
        "DISCOGS_TOKEN": DISCOGS_TOKEN,
        "DISCOGS_USERNAME": DISCOGS_USERNAME,
        "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
        "TELEGRAM_CHAT_ID": TELEGRAM_CHAT_ID,
        "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise EnvironmentError(f"Missing required env vars: {', '.join(missing)}")
