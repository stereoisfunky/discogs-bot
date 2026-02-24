# Setup Guide

Full step-by-step guide to get the bot running from scratch.

---

## Prerequisites

- **macOS** (these instructions are Mac-specific)
- **Python 3.10+** — check with `python3 --version`. Download from [python.org](https://www.python.org/downloads/) if needed.
- A **Discogs account** with records in your collection or wantlist — [discogs.com](https://www.discogs.com)
- A **Telegram account** — [telegram.org](https://telegram.org)
- An **Anthropic account** — [console.anthropic.com](https://console.anthropic.com)

---

## Step 1 — Get your API keys

### Discogs token

1. Log in to [discogs.com](https://www.discogs.com)
2. Go to **Settings → Developers** → [discogs.com/settings/developers](https://www.discogs.com/settings/developers)
3. Click **Generate new token**
4. Copy the token → this is your `DISCOGS_TOKEN`

### Discogs username

Your username is in your profile URL:
`discogs.com/user/YOUR_USERNAME` → this is your `DISCOGS_USERNAME`

---

### Telegram bot token

1. Open Telegram and search for **@BotFather**
2. Send `/newbot`
3. Choose a display name (e.g. "My Vinyl Bot")
4. Choose a username ending in `bot` (e.g. `myvinylbot`)
5. BotFather replies with a token like `1234567890:AAFabc...` → this is your `TELEGRAM_BOT_TOKEN`

### Telegram chat ID

This is your personal Telegram user ID — it tells the bot where to send messages.

1. Search for your new bot in Telegram and press **Start**
2. Open this URL in a browser (replace `YOUR_TOKEN`):
   ```
   https://api.telegram.org/botYOUR_TOKEN/getUpdates
   ```
3. Look for `"chat":{"id": XXXXXXXXX}` — that number is your `TELEGRAM_CHAT_ID`

> If the response is empty, send any message to your bot first, then refresh the URL.

---

### Anthropic API key

1. Go to [console.anthropic.com](https://console.anthropic.com) and sign in
2. Go to **Settings → API Keys → Create Key**
3. Copy the key (starts with `sk-ant-...`) → this is your `ANTHROPIC_API_KEY`
4. Go to **Plans & Billing** and add a payment method with some credits

> A few dollars is more than enough. Each suggestion costs fractions of a cent. See [HOW_IT_WORKS.md](HOW_IT_WORKS.md) for a cost breakdown.

---

## Step 2 — Install the project

Open **Terminal** (`Cmd + Space` → type "Terminal" → Enter):

```bash
# Clone the repo
git clone https://github.com/stereoisfunky/discogs-bot.git
cd discogs-bot

# Create a Python virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

---

## Step 3 — Configure your keys

```bash
cp .env.example .env
```

Open `.env` in any text editor and fill in your values:

```
DISCOGS_TOKEN=your_discogs_token
DISCOGS_USERNAME=your_discogs_username

TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_telegram_chat_id

ANTHROPIC_API_KEY=your_anthropic_api_key

DAILY_HOUR=9
DAILY_MINUTE=0
```

`DAILY_HOUR` and `DAILY_MINUTE` set when the daily suggestion is sent (24h format, your local time).

---

## Step 4 — Run the bot

```bash
python3 bot.py
```

Open Telegram, find your bot, and send `/suggest` to get your first recommendation.

Press `Ctrl + C` to stop.

---

## Step 5 — Run automatically in the background (recommended)

So the bot starts on login and runs without a terminal:

```bash
# Open the plist file and replace /Users/stefano/ with your own home path first
# e.g. /Users/yourname/

cp com.stefano.vinylbot.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.stefano.vinylbot.plist
```

The bot now starts automatically on every login and restarts itself if it crashes.

Check it's running:
```bash
launchctl list | grep -i vinyl
# A row with a PID number = running
```

View logs:
```bash
tail -f ~/Desktop/discogs-bot/bot.log
```

---

## Troubleshooting

**Bot doesn't respond in Telegram**
- Check it's running: `launchctl list | grep -i vinyl`
- Check logs: `tail -f ~/Desktop/discogs-bot/bot.log`

**"Credit balance too low" error**
- Add credits at [console.anthropic.com](https://console.anthropic.com) → Plans & Billing

**Suggestion takes a long time the first time**
- Normal — the bot downloads your entire Discogs collection on first run and caches it. Subsequent calls are instant.

**"Couldn't find a good suggestion" message**
- The bot retries up to 5 times automatically. If it still fails, try `/suggest` again.
