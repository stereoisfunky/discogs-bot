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

This produces a ranked summary like:

```
Top genres:   Electronic (312), Jazz (88), Funk / Soul (41)
Top styles:   Ambient (140), Dub Techno (95), Experimental (60)
Top decades:  1990s (280), 2000s (310), 1970s (90)
Fav artists:  Basic Channel, Gas, Jan Jelinek, Burial...
Fav labels:   Chain Reaction, Kompakt, Warp...
```

---

## 2. Claude AI suggestion

The taste profile is sent to **Claude (claude-opus-4-6)** with a prompt that instructs it to:

- Suggest one real vinyl or cassette release (no CDs, no digital)
- Match the user's taste profile
- Avoid anything already in the collection, wantlist, or previously suggested
- Avoid artists suggested in the last 10 picks (artist cooldown)
- Factor in user ratings: lean toward liked records (4–5★), steer away from disliked ones (1–2★)

Claude responds with a structured JSON:
```json
{
  "artist": "Cluster",
  "title": "Zuckerzeit",
  "year": 1974,
  "format": "Vinyl",
  "why": "A landmark of kosmische musik that bridges your love of ambient electronics and experimental minimalism."
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
