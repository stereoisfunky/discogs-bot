# Discogs Vinyl Bot

A Telegram bot that suggests one vinyl or cassette record per day, powered by your Discogs collection and Claude AI.

Analyses your taste profile (genres, styles, artists, labels, decades) from your Discogs collection and wantlist, asks Claude for a personalised pick, shows real rarity data from the Discogs community, and learns from your ratings over time.

---

## Prerequisites

Before starting, make sure you have:

- A **Mac** running macOS (these instructions are Mac-specific)
- **Python 3.10 or later** — check by running `python3 --version` in Terminal. If not installed, download it from [python.org](https://www.python.org/downloads/)
- A **Discogs account** with some records in your collection or wantlist — [discogs.com](https://www.discogs.com)
- A **Telegram account** — [telegram.org](https://telegram.org)
- An **Anthropic account** with credits — [console.anthropic.com](https://console.anthropic.com)

---

## Step 1 — Get your API keys

You need four credentials. Get them in this order:

### Discogs token & username

1. Log in to [discogs.com](https://www.discogs.com)
2. Go to **Settings → Developers** (or visit [discogs.com/settings/developers](https://www.discogs.com/settings/developers))
3. Click **Generate new token**
4. Copy the token — this is your `DISCOGS_TOKEN`
5. Your `DISCOGS_USERNAME` is visible in your profile URL: `discogs.com/user/YOUR_USERNAME`

### Telegram bot token

1. Open Telegram and search for **@BotFather**
2. Send `/newbot`
3. Choose a name for your bot (e.g. "My Vinyl Bot")
4. Choose a username ending in `bot` (e.g. "myvinylbot")
5. BotFather will reply with a token like `1234567890:AAFabc...` — this is your `TELEGRAM_BOT_TOKEN`

### Telegram chat ID

This is your personal Telegram user ID — it tells the bot where to send messages.

1. Start a chat with your new bot (search for it in Telegram and press Start)
2. Open this URL in your browser (replace `YOUR_TOKEN` with the token from above):
   ```
   https://api.telegram.org/botYOUR_TOKEN/getUpdates
   ```
3. You'll see a JSON response. Look for `"chat":{"id":XXXXXXXXX}` — that number is your `TELEGRAM_CHAT_ID`

> If the response is empty, send any message to your bot first, then refresh the URL.

### Anthropic API key

1. Go to [console.anthropic.com](https://console.anthropic.com)
2. Sign up or log in
3. Go to **Settings → API Keys → Create Key**
4. Copy the key (starts with `sk-ant-...`) — this is your `ANTHROPIC_API_KEY`
5. Go to **Plans & Billing** and add a payment method with some credits (a few dollars is plenty — each suggestion costs fractions of a cent)

---

## Step 2 — Download and set up the project

Open **Terminal** (press `Cmd + Space`, type "Terminal", press Enter).

```bash
# Clone the project
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
# Create your personal config file from the template
cp .env.example .env
```

Now open `.env` in any text editor and fill in your values:

```
DISCOGS_TOKEN=your_discogs_token_here
DISCOGS_USERNAME=your_discogs_username
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_telegram_chat_id
ANTHROPIC_API_KEY=your_anthropic_api_key
DAILY_HOUR=9
DAILY_MINUTE=0
```

`DAILY_HOUR` and `DAILY_MINUTE` set when the daily suggestion is sent (24h format, your local time). Default is 9:00 AM.

---

## Step 4 — Run the bot

```bash
python3 bot.py
```

The bot is now running. Open Telegram, find your bot, and send `/suggest` to get your first recommendation.

To stop it, press `Ctrl + C` in the terminal.

---

## Step 5 — Keep it running in the background (recommended)

So the bot runs automatically without keeping a terminal open, install it as a macOS background service.

**One-time setup:**

```bash
# Copy the service file to the right place
cp com.stefano.vinylbot.plist ~/Library/LaunchAgents/

# Start the service
launchctl load ~/Library/LaunchAgents/com.stefano.vinylbot.plist
```

The bot will now start automatically every time you log in and restart itself if it crashes.

**Managing the service:**

```bash
# Stop
launchctl unload ~/Library/LaunchAgents/com.stefano.vinylbot.plist

# Start
launchctl load ~/Library/LaunchAgents/com.stefano.vinylbot.plist

# Restart
launchctl unload ~/Library/LaunchAgents/com.stefano.vinylbot.plist && launchctl load ~/Library/LaunchAgents/com.stefano.vinylbot.plist

# Check if it's running (a PID number means yes)
launchctl list | grep -i vinyl

# View logs
tail -f /Users/YOUR_USERNAME/Desktop/discogs-bot/bot.log
```

You can also toggle it from **System Settings → General → Login Items & Extensions → "Vinyl Bot"**.

> **Note:** Before running the service setup, open `com.stefano.vinylbot.plist` and replace `/Users/stefano/` with your own home directory path (e.g. `/Users/yourname/`).

---

## Telegram commands

| Command | What it does |
|---|---|
| `/start` | Welcome message |
| `/suggest` | Get a suggestion right now |
| `/history` | Show your last 10 suggestions with ratings |

---

## How a suggestion is generated

1. **Fetch** your full Discogs collection and wantlist
2. **Build a taste profile** — counts top genres, styles, artists, labels, and decades
3. **Ask Claude** to suggest one vinyl or cassette record that fits your profile, excluding anything already in your collection, wantlist, or previously sent
4. **Search Discogs** for the release, filtering to Vinyl or Cassette formats only
5. **Fetch rarity stats** — pulls `have` and `want` counts from Discogs community data
6. **Send** the suggestion to Telegram with a Discogs link, rarity score, and rating buttons

---

## Rating system & learning loop

After each suggestion you'll see five buttons: **1★ through 5★**.

- Tap a button to rate the pick
- Ratings are saved locally in `suggestions.db`
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
| 💎💎💎 | Rare | 300 – 1,499 |
| 💎💎 | Uncommon | 1,500 – 4,999 |
| 💎 | Common | 5,000+ |

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
├── requirements.txt          # Python dependencies
├── com.stefano.vinylbot.plist  # macOS background service config
├── .env              # Your API keys — never share or commit this file
├── .env.example      # Template showing which keys are needed
└── suggestions.db    # Auto-created on first run; stores history and ratings
```

---

## Troubleshooting

**Bot doesn't respond in Telegram**
- Check the bot is running: `launchctl list | grep -i vinyl`
- Check logs: `tail -f ~/Desktop/discogs-bot/bot.log`

**"Credit balance too low" error**
- Add credits at [console.anthropic.com](https://console.anthropic.com) → Plans & Billing

**Suggestion takes a long time**
- Normal on first run — it's downloading your entire Discogs collection. Subsequent calls are faster as the collection size stays the same.

**No results found on Discogs**
- Claude occasionally suggests albums that exist only on CD. The bot will automatically retry up to 5 times with a different suggestion.
