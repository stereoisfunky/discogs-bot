# How It Works

A detailed explanation of the suggestion algorithm, filtering logic, rating system, caching, and cost.

---

## Overview

Every day (or on demand with `/suggest`), the bot goes through this pipeline:

```
Discogs collection + wantlist
        ↓
   Taste profile
        ↓
   Claude AI prompt
        ↓
  Discogs search
        ↓
  Filters & checks
        ↓
  Rarity lookup
        ↓
 Telegram message + rating buttons
```

---

## 1. Taste profile

The bot fetches your full Discogs collection and wantlist, then counts occurrences across:

- **Genres** (e.g. Electronic, Jazz, Rock)
- **Styles** (e.g. Ambient, Dub Techno, Modal)
- **Artists**
- **Labels**
- **Decades** (derived from release year)

Counts are converted to **percentages of your total collection** so Claude understands the real proportional balance — not just raw numbers that would over-emphasise the largest genre:

```
Genre breakdown (percentage of total collection):
  Electronic: 42.3%  (512 records)
  Reggae:     12.1%  (146 records)
  Jazz:        7.4%  (89 records)
  Rock:        6.8%  (82 records)
  ...

Style breakdown:
  Dub Techno:    18.2%  (220 records)
  Roots Reggae:  10.4%  (126 records)
  Ambient:        9.7%  (117 records)
  ...
```

---

## 2. Claude AI suggestion

The taste profile is sent to **Claude (claude-opus-4-6)** with a prompt that instructs it to:

- Suggest one real vinyl or cassette release (no CDs, no digital)
- **Rotate across genres proportionally** — if Reggae is 12% of your collection, roughly 1 in 8 suggestions should be Reggae, not just Electronic every time
- Avoid anything already in the collection, wantlist, or previously suggested
- Avoid artists suggested in the last 10 picks (artist cooldown)
- Avoid genres suggested in the last 5 picks (genre rotation)
- Factor in user ratings: lean toward liked records (4–5★), steer away from disliked ones (1–2★)

Claude responds with a structured JSON that includes the broad genre:
```json
{
  "artist": "The Congos",
  "title": "Heart of the Congos",
  "year": 1977,
  "format": "Vinyl",
  "genre": "Reggae",
  "why": "A roots reggae cornerstone that matches your taste for dub and spiritual sounds."
}
```

---

## 3. Filters & checks

Before accepting a suggestion, the bot runs several checks:

| Check | How |
|---|---|
| Already owned (exact) | Matches by Discogs release ID |
| Already owned (repress/reissue) | Normalises artist + title, strips parentheticals like *(Remastered)*, ignores leading *"The"*, strips punctuation — then compares |
| Already suggested | Checks `suggestions.db` for the release ID |
| Artist cooldown | The same artist cannot appear in two of the last 10 suggestions |
| Genre rotation | If the last 5 suggestions were all in the same genre, Claude is told to pick a different one |

If any check fails, the bot tells Claude and retries (up to 5 attempts).

---

## 4. Discogs search — oldest pressing

Once Claude picks an artist and title, the bot searches Discogs with a free-text query and filters results to Vinyl or Cassette only. From all matching pressings, it picks the **oldest one by year** — so you always get pointed to the original release, not a recent repress.

---

## 5. Rarity score

The bot fetches real community stats from Discogs for the chosen release:

- **have** — how many collectors own it
- **want** — how many collectors want it

Rarity is calculated from the `have` count:

| Score | Label | Collectors who own it |
|---|---|---|
| 💎💎💎💎💎 | Extremely Rare | fewer than 50 |
| 💎💎💎💎 | Very Rare | 50 – 299 |
| 💎💎💎 | Rare | 300 – 1,499 |
| 💎💎 | Uncommon | 1,500 – 4,999 |
| 💎 | Common | 5,000+ |

---

## 6. Rating system & learning loop

After each suggestion you'll see five buttons: **1★ through 5★**.

- Ratings are stored in `suggestions.db`
- On the next suggestion, Claude's prompt includes:
  - Records rated **4–5★** → *"lean into this taste"*
  - Records rated **1–2★** → *"avoid this direction"*
- The more you rate, the more personalised the suggestions become

---

## 7. Caching

Fetching a large Discogs collection on every request would be slow and expensive. Instead, the bot caches the collection and wantlist locally in `discogs_cache.json`.

- **Cache duration:** 1 week
- **First request of the week:** fetches from Discogs and saves the cache
- **All other requests:** loads instantly from the local file
- If you add a lot of records and want to force a refresh, delete `discogs_cache.json` and run `/suggest`

---

## Cost estimate

| Item | Cost |
|---|---|
| Discogs API | Free |
| Claude (per suggestion) | ~$0.03–0.05 |
| **Per month (30 suggestions)** | **~$1–2** |

The weekly cache means the Discogs API is called at most once per week regardless of how many times you use `/suggest`.
