# How It Works

A detailed explanation of the suggestion algorithm, filtering logic, rating system, caching, and cost.

---

## Overview

Every day (or on demand with `/suggest`), the bot goes through this pipeline:

```
Discogs collection + wantlist
        ↓
   Taste profile  (+ daily mode + anchor records)
        ↓
   Claude AI prompt  →  5 candidate records
        ↓
   Hard filters  (owned / artist cooldown / already sent)
        ↓
   Resolve on Discogs + score each survivor
        ↓
   Pick top candidate  →  choose a pressing
        ↓
   Price & availability lookup
        ↓
 Telegram message + rating buttons
```

Each run picks a fresh random `seed`. The seed drives the daily mode, the rotating
long-tail sample in the taste profile, and the anchor selection — so two runs on the
same collection explore different corners.

---

## 1. Taste profile

The bot fetches your full Discogs collection and wantlist, then counts occurrences across:

- **Genres** (e.g. Electronic, Jazz, Rock)
- **Styles** (e.g. Ambient, Dub Techno, Modal)
- **Artists**
- **Labels**
- **Decades** (derived from release year)

Head counts are converted to **percentages of your total collection** so Claude
understands the real proportional balance. The prompt carries the top 8 genres and
top 12 styles:

```
Genre breakdown (percentage of total collection):
  Electronic: 42.3%  (512 records)
  Reggae:     12.1%  (146 records)
  Jazz:        7.4%  (89 records)
  ...

Style breakdown:
  Dub Techno:    18.2%  (220 records)
  Roots Reggae:  10.4%  (126 records)
  ...
```

Two extra views are derived from the same data:

- **Decade × genre cross-tab** — for the top 5 genres, how the records spread across
  decades. Surfaces that e.g. your reggae is mostly 70s but your electronic is mostly 2010s.

  ```
  Top genres by decade:
    Reggae: 1970s 9, 1980s 8, 2010s 18
    Electronic: 1990s 44, 2000s 120, 2010s 210
  ```

- **Rotating long-tail sample** — ~10 styles and ~10 artists drawn from *below* the
  top ranks, owned in small numbers. Reshuffled every run by the seed, so the
  "discovery territory" the model sees changes daily.

  ```
  Less-explored corners of the collection (styles owned in small numbers …):
    Free Jazz, Musique Concrète, Highlife, No Wave, Cumbia, ...
  Less-explored artists (owned in small numbers):
    Alice Coltrane, Midori Takada, William Onyeabor, ...
  ```

---

## 2. Claude AI suggestion

### Daily mode

Before prompting, the bot picks one **mode** for the run by weighted random
(`config.MODE_WEIGHTS`):

| Mode | Weight | Meaning |
|---|---|---|
| `core` | 0.50 | Squarely within your established taste — something strong you've likely missed |
| `adjacent` | 0.30 | A scene or style that borders your collection but isn't in it — one step outside |
| `wildcard` | 0.20 | A deliberate left turn — a genre you own very little of, or a lateral link (producer, label-mate, contemporary of something you own) |

The mode is sent to Claude and stored in `suggestions.db` (`mode` column).

### Anchors

The bot picks **2–3 records from your collection** (`config.ANCHOR_COUNT`), weighted
toward rarer artists and styles, and passes them to Claude as anchors — "propose
things in dialogue with these, not more copies of them".

### The request

The taste profile, mode, anchors, recently-sent list, artist-cooldown list, and
rating feedback go to **Claude (`claude-opus-5`, adaptive thinking, effort medium)**.
It's asked for a **JSON array of 5 distinct candidates**:

```json
[
  {
    "artist": "The Congos",
    "title": "Heart of the Congos",
    "year": 1977,
    "format": "Vinyl",
    "genre": "Reggae",
    "style": "Roots Reggae",
    "pressing_note": "original",
    "est_price_band": "mid",
    "reason": "Produced by Lee Perry at the Black Ark; three-part harmony vocal group."
  }
]
```

| Field | Notes |
|---|---|
| `genre` | one broad genre |
| `style` | one specific sub-genre |
| `pressing_note` | `"original"` if only an early pressing is worth pointing to, `"any"` if a reissue serves the music fine — Claude's call |
| `est_price_band` | `"budget"` / `"mid"` / `"collector"` — Claude's rough guess of the cheapest copy |
| `reason` | one factual sentence about the record itself — label, producer, a notable fact — never "why it fits you" |

---

## 3. Filters & checks

Every candidate runs through hard filters. Failing candidates are dropped silently;
the remaining ones are resolved and scored.

| Check | How |
|---|---|
| Already owned (exact) | Matches by Discogs release ID (collection + wantlist) |
| Already owned (repress/reissue) | Normalises artist + title — strips parentheticals like *(Remastered)*, ignores leading *"The"*, strips punctuation — then compares |
| Already sent | Checks `suggestions.db` for the release ID and the `artist – title` string |
| Artist cooldown | An artist used in any of the last 10 picks is rejected |
| **Candidate scoring** | Survivors are resolved on Discogs and scored; the top score wins (`config.SCORE_WEIGHTS`) |

**Scoring** (`recommender.score_candidate`) combines:

- **novelty** — genre/style distance from the last ~10 picks (supersedes the old
  fixed "last 5 genres" rotation)
- **mode fit** — does the candidate's genre/style match the day's mode? (heuristic:
  `core` wants both in your top lists, `adjacent` wants the genre in but the style out,
  `wildcard` wants the genre out)
- **discoverable** — small bonus when community `have` is inside
  `config.DISCOVERABLE_HAVE_RANGE` (default 200–3000: findable but not ubiquitous)
- **price band** — small penalty when `est_price_band` is `"collector"`

If no candidate survives filtering + pressing selection, the bot asks Claude for
5 more with feedback — **maximum 2 rounds**.

---

## 4. Pressing selection

`discogs.search_release` returns **all** Vinyl / Cassette pressings of the winning
record, oldest first. `recommender.choose_pressing` then decides which one to point at,
fetching price and stock per pressing:

| `pressing_note` | Logic |
|---|---|
| `"original"` | The oldest pressing, **if** its lowest price isn't "absurd" (> `config.ABSURD_PRICE`, default €80) and it's in stock. If the original is absurd, fall back to the cheapest affordable reissue and the message notes the original's price. |
| `"any"` | The cheapest pressing that's actually in stock. |

If even the cheapest option is absurd or nothing is for sale, the candidate is
discarded and the bot tries the next-highest-scored one.

---

## 5. Price & availability

For the chosen pressing the bot fetches real Discogs data (`discogs.get_release_info`):

- **have / want** — from `/releases/{id}` community stats
- **lowest price** and **number for sale** — from `/marketplace/stats/{id}`, in
  `config.PRICE_CURRENCY_CODE` (default EUR)

The Telegram message shows a line like:

```
From €29.80 · 23 for sale · 2498 own / 1106 want
```

If the pick is a reissue fallback, a note is appended:
`(original pressing runs ~€120.00; this points to the 2017 reissue)`.

---

## 6. Rating system & learning loop

After each suggestion you'll see five buttons: **1★ through 5★**.

- Ratings are stored in `suggestions.db`.
- On later runs, Claude's prompt includes:
  - The **titles** you rated 4–5★ (lean in) and 1–2★ (steer away).
  - An **attribute-level aggregate** (`database.get_rated_attributes`): the genres,
    styles and decades common to your high ratings vs your low ratings, phrased as
    *"responded well to: roots reggae, dub, 70s / poorly to: jazz-funk, 80s"*.
- Still a soft nudge — with few ratings so far it only lightly biases the model.

---

## 7. Caching

Fetching a large Discogs collection on every request would be slow and expensive.
Instead, the bot caches the collection and wantlist locally in `discogs_cache.json`.

- **Cache duration:** 1 week (`CACHE_TTL_HOURS`)
- **First request of the week:** fetches from Discogs and saves the cache
- **All other requests:** loads instantly from the local file
- To force a refresh, delete `discogs_cache.json` and run `/suggest`

Per-release lookups (search, community stats, marketplace stats) are hit live each
run, since only a handful of candidates and pressings are checked.

---

## Tuning

The knobs in `config.py`:

| Setting | Default | Effect |
|---|---|---|
| `MODE_WEIGHTS` | `core 0.50 / adjacent 0.30 / wildcard 0.20` | Probability of each daily exploration mode |
| `ANCHOR_COUNT` | `3` | How many collection records are passed to Claude as anchors |
| `SCORE_WEIGHTS` | `novelty 1.0 / mode_fit 0.6 / discoverable 0.3 / price_band 0.3` | Relative weight of each scoring component |
| `DISCOVERABLE_HAVE_RANGE` | `(200, 3000)` | Community `have` count that earns the discoverability bonus |
| `ABSURD_PRICE` | `80.0` | Cheapest listing above this (account currency) is skipped / triggers a reissue fallback |
| `PRICE_CURRENCY_CODE` / `PRICE_CURRENCY_SYMBOL` | `EUR` / `€` | Currency requested from Discogs and shown in the message |

---

## Cost estimate

| Item | Cost |
|---|---|
| Discogs API | Free |
| Claude (`claude-opus-5`, one call per run — returns 5 candidates) | a few cents |
| **Per month (~30 runs)** | **roughly $1–3** |

A run occasionally makes a second Claude call (when the first 5 candidates are all
rejected), which roughly doubles that run's cost. The weekly cache means the Discogs
collection endpoint is called at most once per week regardless of how many times you
use `/suggest`.
