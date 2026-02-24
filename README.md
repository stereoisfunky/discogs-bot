# Discogs Vinyl Bot

A Telegram bot that suggests one vinyl or cassette record per day, powered by your Discogs collection and Claude AI.

It analyses your taste from your Discogs collection and wantlist, asks Claude for a personalised pick, checks rarity from real Discogs community data, and learns from your ratings over time.

---

## Quick start

```bash
git clone https://github.com/stereoisfunky/discogs-bot.git
cd discogs-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# fill in your keys — see SETUP.md
python3 bot.py
```

Full installation guide with step-by-step API key setup → **[SETUP.md](SETUP.md)**

---

## Telegram commands

| Command | What it does |
|---|---|
| `/start` | Welcome message |
| `/suggest` | Get a suggestion right now |
| `/history` | Show your last 10 suggestions with ratings |

---

## Running as a background service

Install as a macOS login item so the bot runs automatically without keeping a terminal open:

```bash
cp com.stefano.vinylbot.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.stefano.vinylbot.plist
```

> Before running, open `com.stefano.vinylbot.plist` and replace `/Users/stefano/` with your own home path.

| Action | Command |
|---|---|
| Stop | `launchctl unload ~/Library/LaunchAgents/com.stefano.vinylbot.plist` |
| Start | `launchctl load ~/Library/LaunchAgents/com.stefano.vinylbot.plist` |
| Restart | unload + load |
| Check status | `launchctl list \| grep -i vinyl` |
| View logs | `tail -f ~/Desktop/discogs-bot/bot.log` |

You can also toggle it from **System Settings → General → Login Items → "Vinyl Bot"**.

---

## File structure

```
discogs-bot/
│
├── bot.py            # Telegram bot: commands, rating callbacks, daily scheduler
├── recommender.py    # Claude AI: builds prompt, parses suggestion
├── discogs.py        # Discogs REST API: collection, wantlist, search, cache
├── database.py       # SQLite: suggestion history, user ratings
├── config.py         # Loads environment variables from .env
│
├── SETUP.md                    # Step-by-step installation guide
├── HOW_IT_WORKS.md             # How the algorithm works in detail
├── requirements.txt            # Python dependencies
├── com.stefano.vinylbot.plist  # macOS background service config
├── .env                        # Your API keys (never commit this)
├── .env.example                # Template for .env
├── suggestions.db              # Auto-created; stores history and ratings
└── discogs_cache.json          # Auto-created; weekly Discogs cache
```

---

## Docs

- [SETUP.md](SETUP.md) — prerequisites, API keys, installation
- [HOW_IT_WORKS.md](HOW_IT_WORKS.md) — suggestion algorithm, rating loop, caching, rarity
