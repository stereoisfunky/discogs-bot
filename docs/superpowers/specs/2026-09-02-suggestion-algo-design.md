# Suggestion Algorithm Redesign — Design

**Date:** 2026-09-02
**Status:** Approved (brainstorm), pending implementation plan

## Problem

Stefano's feedback on the daily vinyl suggestions:

1. **Narrow** — picks circle the same genres, artists, and eras.
2. **Never surprising** — safe canonical classics he already knows.
3. **Always expensive** — picks skew toward costly first pressings and collector rarities.

Root causes in the current code:

- `discogs.build_taste_profile` only emits the head of the distribution (top 10 genres, top 15 styles, top 20 artists as % of a 1,214-record collection). The long tail — where discovery lives — never reaches Claude.
- All constraints are negative (avoid last 5 genres, avoid last 10 artists, avoid all owned). Nothing actively pushes toward unexplored territory.
- One blind Claude call picks a single record; "matches a profile" resolves to canonical picks.
- `discogs.search_release` always returns the **oldest pressing by year**, which is the expensive first press instead of a cheap reissue of the same music.
- Rarity (💎 "Extremely Rare") is displayed as a positive, implicitly rewarding expensive picks. It never influences selection, only display.
- The prompt appends all ~1,267 owned titles as an exclusion list (~15–20k tokens per call), diluting the taste signal. This is redundant: `recommender.get_suggestion` already rejects owned records by Discogs ID and by normalized `(artist, title)`.
- Rating feedback (10 of 63 rated) is passed as bare title lists with no musical reasoning.

## Decisions (from brainstorm)

| Question | Decision |
|---|---|
| Price target | No hard ceiling; avoid the absurd (roughly €80+ collector rarities). Always show price. |
| Adventurousness | Balanced rotation, ~50/50 core vs. exploration, true wildcard ~2×/week. |
| Pressing choice | Claude decides per record whether the original matters or any pressing is fine. |
| Model | Bump `claude-opus-4-6` → `claude-opus-5`, adaptive thinking, `effort: medium`. |

## Design

### 1. Deeper taste profile

`discogs.build_taste_profile` / `format_profile_for_prompt` changes:

- **Rotating long-tail sample:** in addition to the top lists, sample ~10 styles and ~10 artists from *below* the top 20 (items with a collection count roughly in the 2–6 range). Selection is seeded by a per-run random seed so the sample rotates daily.
- **Decade × genre cross-tab:** for the top ~5 genres, break each down by decade (e.g. `Reggae: 70s 62%, 80s 21%, 10s 12%`). Emitted as compact lines.
- **Trim head lists** to top 8 genres / top 12 styles to keep the prompt focused.

Profile builder stays a pure function over `(collection, wantlist)` plus an optional `seed`. No network calls.

### 2. Daily mode

`recommender` picks a mode per run by weighted random (weights in `config.py`):

| Mode | Default weight | Instruction to Claude |
|---|---|---|
| `core` | 0.50 | A release squarely within the collector's established taste that they are likely missing. |
| `adjacent` | 0.30 | A scene or style that borders the collection but is not represented in it — one step outside. |
| `wildcard` | 0.20 | A deliberate left turn: a genre the collector owns less than ~1% of, or a lateral connection (a producer, label-mate, or contemporary of a record they own). |

The chosen mode string is passed into the prompt and stored in a new `suggestions.mode` column for auditing the mix over time.

### 3. Anchors

Each run, `recommender` asks `discogs` for 2–3 randomly chosen collection records, weighted toward the long tail (lower-frequency artists/styles), using the same per-run seed. These are passed to Claude as: "Find something in dialogue with these specific records the collector owns: …". Rotates the entry point daily.

### 4. Candidate generation + ranking

**Claude call** returns a JSON array of **5 candidates**, each:

```json
{
  "artist": "...",
  "title": "...",
  "year": 1977,
  "format": "Vinyl",
  "genre": "Reggae",
  "style": "Roots Reggae",
  "pressing_note": "original" | "any",
  "est_price_band": "budget" | "mid" | "collector",
  "reason": "one concise factual sentence"
}
```

`pressing_note` — Claude's judgement on whether the original pressing matters or any vinyl/cassette pressing is acceptable.
`est_price_band` — Claude's rough guess, used only as a scoring tiebreaker (the `price_band` term in step 3), never as ground truth. Real price comes from Discogs in step 4.

**Bot-side pipeline** (`recommender.get_suggestion`):

1. **Hard filters** — drop any candidate that is owned (by ID or normalized `(artist, title)`), fails the artist cooldown (last 10), or was already sent.
2. **Resolve** each surviving candidate via `discogs.search_release`, which now returns *all* matching Vinyl/Cassette pressings (id, year) rather than just the oldest.
3. **Score** each candidate:
   - `novelty` — distance of its genre/style from the last ~10 picks' genres/styles (higher = more novel).
   - `mode_fit` — bonus if the candidate plausibly matches the day's mode (heuristic: for `wildcard`, genre not in the collection's top genres; for `adjacent`, style not in top styles but genre is; for `core`, both in top).
   - `discoverable` — small bonus when the release's community `have` count is roughly 200–3,000 (findable but not ubiquitous).
   - `price_band` — small penalty for `collector`.
   Weights in `config.py`.
4. **Pick the top candidate.** Fetch its release detail(s) for `lowest_price` and `num_for_sale` via a new `discogs.get_release_price(release_id)` (reusing the release GET already done for community stats where possible):
   - `pressing_note == "original"` → choose the oldest pressing whose `lowest_price` is not absurd (≤ `ABSURD_PRICE_EUR`, default 80). If the oldest is absurd, fall back to the cheapest available Vinyl/Cassette pressing and mark `reissue_fallback` so the message can note it.
   - `pressing_note == "any"` → choose the pressing with the best price × availability (lowest `lowest_price` among those with `num_for_sale > 0`).
5. If the chosen record's best price is still absurd → discard the candidate, move to the next.
6. If no candidate survives the whole pipeline → one more Claude round with feedback (which candidates were rejected and why), max **2 rounds total**.

Discogs call budget per run: ~5 searches + up to ~3 release GETs — comparable to today's up-to-5 retry loop.

### 5. Message format — price replaces rarity headline

`bot.format_suggestion`:

```
🎵 The Congos – Heart Of The Congos (1977)
Roots reggae on Black Ark, produced by Lee Perry.

From €18 · 42 for sale · 3,100 own / 1,800 want
🔗 View on Discogs
```

- Price line: `From €{lowest_price} · {num_for_sale} for sale · {have} own / {want} want`.
- If `reissue_fallback`: append a short note, e.g. `(original pressing runs ~€210; this points to the {year} reissue)`.
- `discogs.calculate_rarity` stays in the module (still used nowhere critical) but is no longer the headline. Can be dropped entirely if nothing references it after the change.
- Currency: Discogs `lowest_price` is returned in the currency tied to the API token's account. Display with a `€` prefix; if the account currency turns out not to be EUR, make the symbol a `config.PRICE_CURRENCY` string. Confirm during implementation with one live call.

### 6. Attribute-level rating feedback

- `database`: add `style` and `year` columns to `suggestions`; populate them on `record_suggestion`.
- New `database.get_rated_attributes()` → aggregates the genre/style/decade of 4–5★ picks vs 1–2★ picks.
- `recommender` prompt includes: "The collector responded well to: {roots reggae, dub, late-70s, …}. Responded poorly to: {jazz-funk, early-80s, …}." alongside (not replacing) the existing liked/disliked title lists.
- Soft nudge only — 10 ratings is a thin signal.

### 7. Drop the owned-titles dump

Remove `owned_exclusion` (the ~1,267-line owned-titles block) from `recommender._ask_claude`'s prompt. Keep:
- the recent already-suggested list (last ~30),
- the recent-artists list (last 10).

The hard filters in `get_suggestion` remain the enforcement mechanism for "don't suggest what he owns".

### 8. Model bump

`recommender._ask_claude`:
- `model="claude-opus-5"`
- `thinking={"type": "adaptive"}`
- `output_config={"effort": "medium"}`
- Remove `max_tokens` lowball if present; set to a comfortable value for a 5-candidate JSON array (~1500).

## Components and boundaries

| Unit | Responsibility | Interface | Depends on |
|---|---|---|---|
| `discogs.build_taste_profile(collection, wantlist, seed=None)` | Aggregate taste incl. long-tail sample + cross-tab | dict | stdlib only |
| `discogs.pick_anchors(collection, n, seed)` | Choose long-tail-weighted sample records | list[dict] | stdlib only |
| `discogs.search_release(artist, title)` | All matching Vinyl/Cassette pressings | list[dict] (id, year, format, url) | Discogs API |
| `discogs.get_release_price(release_id)` | `lowest_price`, `num_for_sale` | dict | Discogs API |
| `discogs.get_community_stats(release_id)` | `have`, `want` | dict | Discogs API |
| `recommender.pick_mode(weights, rng)` | Choose the day's mode | str | stdlib |
| `recommender.score_candidate(cand, release_stats, recent, mode, weights)` | Numeric score | float | pure |
| `recommender.choose_pressing(pressings, pressing_note, prices, absurd_eur)` | Final pressing + reissue_fallback flag | dict | pure |
| `recommender.get_suggestion()` | Orchestrate the pipeline | dict \| None | all of the above, database |
| `database` | history, ratings, mode/style/year columns, `get_rated_attributes()` | functions | sqlite |
| `bot.format_suggestion(s)` | Telegram text | str | pure |

Scoring, pressing choice, mode pick, and the profile builder are all pure functions — unit-testable without network.

## Config additions (`config.py`)

```python
MODE_WEIGHTS = {"core": 0.50, "adjacent": 0.30, "wildcard": 0.20}
ABSURD_PRICE_EUR = 80
ANCHOR_COUNT = 3
DISCOVERABLE_HAVE_RANGE = (200, 3000)
SCORE_WEIGHTS = {"novelty": 1.0, "mode_fit": 0.6, "discoverable": 0.3, "price_band": 0.3}
PRICE_CURRENCY = "€"
```

## Testing

Unit tests (mocked Discogs + Claude, no live calls):

- `score_candidate` — novelty distance ordering, discoverable-range bonus edges, price-band penalty.
- `choose_pressing` — `original` picks oldest non-absurd; `original` with absurd OG → reissue fallback flag set; `any` picks cheapest in-stock.
- `pick_mode` — distribution over many draws roughly matches weights (seeded RNG).
- `build_taste_profile` — long-tail sample excludes the top 20; rotates with seed; cross-tab sums per genre.
- `pick_anchors` — returns N, weighted to lower-frequency items, deterministic under a seed.
- `format_suggestion` — price line rendering, reissue-fallback note.
- `get_rated_attributes` — correct like/dislike attribute buckets.

One manual end-to-end `/suggest` run against live APIs before merge, checked for: price line correct, currency correct, mode logged, sensible pick.

## Out of scope

- Full embedding/cluster taste model (approach C) — deferred.
- Extra Telegram feedback buttons ("too safe" / "too pricey") — deferred; revisit if attribute feedback proves too thin.
- Marketplace price history / median price — `lowest_price` is enough.

## Files touched

- `discogs.py`
- `recommender.py`
- `database.py`
- `bot.py`
- `config.py`
- `HOW_IT_WORKS.md`
- `tests/` (new)
