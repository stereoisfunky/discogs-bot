# Discogs Vinyl Bot

A Telegram bot that suggests one vinyl or cassette record per day based on your Discogs collection and wantlist taste, powered by Claude AI.

---

## How to run

```bash
# 1. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Fill in your credentials
cp .env.example .env
# edit .env with your tokens

# 4. Start the bot
python bot.py
```

The bot runs in the foreground. Keep the terminal open, or run it as a background service (see below).

---

## Running as a background service (recommended)

The bot is installed as a macOS login item called **"Vinyl Bot"**. It starts automatically when you log in and restarts itself if it crashes — no terminal needed.

To manage it without opening a terminal, use **Script Editor** (or any app that can run AppleScript/shell):

**Start**
```bash
launchctl load ~/Library/LaunchAgents/com.stefano.vinylbot.plist
```

**Stop**
```bash
launchctl unload ~/Library/LaunchAgents/com.stefano.vinylbot.plist
```

**Restart**
```bash
launchctl unload ~/Library/LaunchAgents/com.stefano.vinylbot.plist && launchctl load ~/Library/LaunchAgents/com.stefano.vinylbot.plist
```

**Check if it's running**
```bash
launchctl list | grep -i vinyl
```
A row with a PID number means it's running. An empty result means it's stopped.

**View logs**
```bash
tail -f /Users/stefano/Desktop/discogs-bot/bot.log
```

You can also enable/disable it permanently from:
**System Settings → General → Login Items & Extensions → "Vinyl Bot"**

---

## Telegram commands

| Command | What it does |
|---|---|
| `/start` | Welcome message |
| `/suggest` | Get a suggestion right now |
| `/history` | Show your last 10 suggestions with ratings |

---

## How a suggestion is generated

1. **Fetch** your full Discogs collection and wantlist via the Discogs REST API
2. **Build a taste profile** — counts top genres, styles, artists, labels, and decades
3. **Ask Claude** (claude-opus-4-6) to suggest one vinyl or cassette record that fits your profile, excluding anything already in your collection, wantlist, or previously sent
4. **Search Discogs** for the suggested release, filtering to Vinyl or Cassette formats only
5. **Fetch rarity stats** — pulls `have` and `want` counts from the Discogs community data
6. **Send** the suggestion to Telegram with a Discogs link, rarity score, and rating buttons

---

## Rating system & learning loop

After each suggestion you'll see five buttons: **1★ through 5★**.

- Tap a button to rate the pick
- Ratings are saved in the local SQLite database (`suggestions.db`)
- On the next suggestion, Claude receives your rating history:
  - Records you rated **4–5★** → Claude leans further in that direction
  - Records you rated **1–2★** → Claude steers away from that style
- The more you rate, the better the suggestions get

---

## Rarity scale

Rarity is calculated from the number of Discogs collectors who own the release:

| Score | Label | Collectors who own it |
|---|---|---|
| 💎💎💎💎💎 | Extremely Rare | fewer than 50 |
| 💎💎💎💎 | Very Rare | 50 – 299 |
| 💎💎💎 | Rare | 300 – 1499 |
| 💎💎 | Uncommon | 1500 – 4999 |
| 💎 | Common | 5000+ |

---

## File structure

```
discogs-bot/
│
├── bot.py            # Telegram bot: commands, rating callbacks, daily scheduler
├── recommender.py    # Claude AI: builds prompt, parses suggestion, fetches rarity
├── discogs.py        # Discogs REST API: collection, wantlist, search, community stats
├── database.py       # SQLite: stores sent suggestions and user ratings
├── config.py         # Loads and validates environment variables from .env
│
├── requirements.txt  # Python dependencies
├── .env              # Your API keys (never commit this)
├── .env.example      # Template for .env
└── suggestions.db    # Auto-created on first run; stores history and ratings
```

---

## Environment variables

| Variable | Description |
|---|---|
| `DISCOGS_TOKEN` | Personal access token from discogs.com/settings/developers |
| `DISCOGS_USERNAME` | Your Discogs username |
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Your Telegram user ID (find via getUpdates) |
| `ANTHROPIC_API_KEY` | API key from console.anthropic.com |
| `DAILY_HOUR` | Hour to send the daily suggestion (24h, default: 9) |
| `DAILY_MINUTE` | Minute to send the daily suggestion (default: 0) |
