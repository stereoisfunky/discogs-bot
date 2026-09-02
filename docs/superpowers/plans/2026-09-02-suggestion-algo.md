# Suggestion Algorithm Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the daily vinyl suggestions less narrow, more surprising, and less expensive by adding a deeper taste profile, a rotating exploration mode, multi-candidate ranking, and price-aware pressing selection.

**Architecture:** `discogs.py` gains a richer pure taste-profile builder (long-tail sample + decade×genre cross-tab), an anchor picker, a pressing list from search, and a combined release-info fetch (have/want/price/stock). `recommender.py` picks a daily mode by weighted random, asks Claude for 5 candidates, scores them with pure functions (novelty + mode fit + discoverability + price band), then selects a pressing per Claude's per-record `pressing_note`. `database.py` stores `mode`/`style`/`year` and returns rated-attribute aggregates. `bot.py` shows a price/availability line instead of the rarity headline.

**Tech Stack:** Python 3.13, `anthropic` 0.86 SDK (`claude-opus-5`, adaptive thinking, `output_config.effort`), `requests` against the Discogs REST API, `sqlite3`, `pytest` (new, dev-only).

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `requirements-dev.txt` | Dev/test dependencies | Create |
| `pytest.ini` | Pytest config (testpaths, quiet) | Create |
| `tests/conftest.py` | Shared fixtures: temp DB, sample collection | Create |
| `tests/test_profile.py` | `build_taste_profile`, `pick_anchors` | Create |
| `tests/test_discogs.py` | `search_release` list shape, `get_release_info` | Create |
| `tests/test_scoring.py` | `pick_mode`, `score_candidate`, `choose_pressing` | Create |
| `tests/test_database.py` | new columns, `get_recent_styles`, `get_rated_attributes` | Create |
| `tests/test_bot_format.py` | `format_suggestion` price line | Create |
| `config.py` | Tunable knobs | Modify: add 6 constants |
| `database.py` | History + ratings + new columns + aggregates | Modify |
| `discogs.py` | Discogs API + pure profile/anchor helpers | Modify |
| `recommender.py` | Mode, candidate prompt, scoring, pressing pick, orchestration | Modify (large) |
| `bot.py` | Telegram message + record calls | Modify |
| `HOW_IT_WORKS.md` | Algorithm docs | Modify |

Every unit under test (`build_taste_profile`, `pick_anchors`, `pick_mode`, `score_candidate`, `choose_pressing`, `format_suggestion`, `get_rated_attributes`) is a **pure function** or a function with an **injected fetch callable** — no network in tests.

---

## Task 1: Test infrastructure

**Files:**
- Create: `requirements-dev.txt`
- Create: `pytest.ini`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create `requirements-dev.txt`**

```
-r requirements.txt
pytest==8.3.3
```

- [ ] **Step 2: Install it**

Run: `source venv/bin/activate && pip install -r requirements-dev.txt`
Expected: `Successfully installed pytest-8.3.3 ...` (plus `iniconfig`, `pluggy`).

- [ ] **Step 3: Create `pytest.ini`**

```ini
[pytest]
testpaths = tests
addopts = -q
```

- [ ] **Step 4: Create `tests/conftest.py`**

```python
"""Shared test fixtures. No network calls anywhere in the suite."""
import sqlite3
import pytest

import database


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Point database.py at a fresh empty SQLite file and init the schema."""
    db_file = tmp_path / "test_suggestions.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_file))
    database.init_db()
    return str(db_file)


@pytest.fixture
def sample_collection():
    """A small collection with a clear head/long-tail split.

    Techno + Ambient dominate; the rest are 1-2 copies each (the long tail).
    """
    def rec(rid, artist, title, year, genres, styles):
        return {
            "id": str(rid), "title": title, "artists": [artist],
            "genres": genres, "styles": styles, "labels": ["Some Label"],
            "year": year,
        }
    items = []
    for i in range(20):
        items.append(rec(100 + i, f"Techno Artist {i}", f"Techno LP {i}", 1994 + (i % 5),
                         ["Electronic"], ["Techno"]))
    for i in range(15):
        items.append(rec(200 + i, f"Ambient Artist {i}", f"Ambient LP {i}", 1980 + (i % 10),
                         ["Electronic"], ["Ambient"]))
    # long tail: one record each
    items.append(rec(300, "The Congos", "Heart Of The Congos", 1977, ["Reggae"], ["Roots Reggae"]))
    items.append(rec(301, "Alice Coltrane", "Journey In Satchidananda", 1971, ["Jazz"], ["Spiritual Jazz"]))
    items.append(rec(302, "Aksak Maboul", "Onze Danses", 1977, ["Rock"], ["Avantgarde"]))
    items.append(rec(303, "Pauline Oliveros", "Deep Listening", 1989, ["Classical"], ["Modern"]))
    return items


@pytest.fixture
def sample_wantlist():
    return [{
        "id": "900", "title": "Wanted LP", "artists": ["Wanted Artist"],
        "genres": ["Electronic"], "styles": ["Deep House"], "labels": ["X"], "year": 2001,
    }]
```

- [ ] **Step 5: Run the empty suite**

Run: `source venv/bin/activate && python -m pytest`
Expected: `no tests ran` (exit code 5) — confirms pytest discovers `tests/` and imports `database` cleanly.

- [ ] **Step 6: Commit**

```bash
git add requirements-dev.txt pytest.ini tests/conftest.py
git commit -m "test: add pytest infrastructure and shared fixtures"
```

---

## Task 2: Config knobs

**Files:**
- Modify: `config.py` (append after line 20, before `def validate()`)

- [ ] **Step 1: Add constants to `config.py`**

Insert after `CACHE_TTL_HOURS = 168  # 1 week`:

```python

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
```

- [ ] **Step 2: Verify it imports**

Run: `source venv/bin/activate && python -c "import config; print(config.MODE_WEIGHTS, config.ABSURD_PRICE, config.SCORE_WEIGHTS)"`
Expected: `{'core': 0.5, 'adjacent': 0.3, 'wildcard': 0.2} 80.0 {'novelty': 1.0, 'mode_fit': 0.6, 'discoverable': 0.3, 'price_band': 0.3}`

- [ ] **Step 3: Commit**

```bash
git add config.py
git commit -m "feat: add suggestion-algorithm tuning constants"
```

---

## Task 3: Database — new columns, recent styles, rated attributes

**Files:**
- Modify: `database.py`
- Test: `tests/test_database.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_database.py`:

```python
import database


def test_record_suggestion_stores_mode_style_year(temp_db):
    database.record_suggestion("111", "The Congos", "Heart Of The Congos",
                               fmt="Vinyl", genre="Reggae", style="Roots Reggae",
                               year=1977, mode="wildcard")
    hist = database.get_history(limit=1)
    assert hist[0]["artist"] == "The Congos"
    rows = database._connect().execute(
        "SELECT mode, style, year FROM suggestions WHERE discogs_id='111'"
    ).fetchone()
    assert rows == ("wildcard", "Roots Reggae", 1977)


def test_get_recent_styles(temp_db):
    database.record_suggestion("1", "A", "a", style="Dub Techno")
    database.record_suggestion("2", "B", "b", style="Ambient")
    database.record_suggestion("3", "C", "c", style="")
    assert database.get_recent_styles(limit=5) == ["Ambient", "Dub Techno"]


def test_get_recent_genres_default_limit_is_10(temp_db):
    for i in range(12):
        database.record_suggestion(str(i), "A", "a", genre=f"G{i}")
    assert len(database.get_recent_genres()) == 10


def test_get_rated_attributes_buckets_by_rating(temp_db):
    database.record_suggestion("1", "A", "a", genre="Reggae", style="Roots Reggae", year=1977)
    database.record_suggestion("2", "B", "b", genre="Jazz", style="Jazz-Funk", year=1981)
    database.update_rating("1", 5)
    database.update_rating("2", 1)
    attrs = database.get_rated_attributes()
    assert "Reggae" in attrs["liked"]["genres"]
    assert "70s" in attrs["liked"]["decades"]
    assert "Jazz-Funk" in attrs["disliked"]["styles"]
    assert "80s" in attrs["disliked"]["decades"]
```

- [ ] **Step 2: Run it, verify failure**

Run: `source venv/bin/activate && python -m pytest tests/test_database.py -v`
Expected: FAIL — `record_suggestion() got an unexpected keyword argument 'style'` / `AttributeError: module 'database' has no attribute 'get_recent_styles'`.

- [ ] **Step 3: Update `database.py`**

In `init_db()`, extend the migration loop (currently `for col, definition in [("format", "TEXT"), ("rating", "INTEGER"), ("genre", "TEXT")]:`) to:

```python
        for col, definition in [
            ("format", "TEXT"), ("rating", "INTEGER"), ("genre", "TEXT"),
            ("style", "TEXT"), ("year", "INTEGER"), ("mode", "TEXT"),
        ]:
```

Replace `record_suggestion`:

```python
def record_suggestion(discogs_id: str, artist: str, title: str, fmt: str = "",
                      genre: str = "", style: str = "", year: int | None = None,
                      mode: str = ""):
    with _connect() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO suggestions
               (discogs_id, artist, title, format, genre, style, year, mode, sent_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (discogs_id, artist, title, fmt, genre, style, year, mode,
             datetime.utcnow().isoformat()),
        )
        conn.commit()
```

Change `get_recent_genres` default from `limit: int = 5` to `limit: int = 10`.

Add after `get_recent_artists`:

```python
def get_recent_styles(limit: int = 10) -> list[str]:
    """Return styles from the last N suggestions (for novelty scoring)."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT style FROM suggestions WHERE style IS NOT NULL AND style != '' "
            "ORDER BY sent_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [r[0] for r in rows]


def _decade(year) -> str | None:
    try:
        return f"{(int(year) // 10) * 10 % 100:02d}s" if year else None
    except (ValueError, TypeError):
        return None


def get_rated_attributes() -> dict:
    """Aggregate genre/style/decade of liked (4-5) vs disliked (1-2) picks."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT genre, style, year, rating FROM suggestions WHERE rating IS NOT NULL"
        ).fetchall()
    out = {
        "liked": {"genres": [], "styles": [], "decades": []},
        "disliked": {"genres": [], "styles": [], "decades": []},
    }
    for genre, style, year, rating in rows:
        bucket = "liked" if rating >= 4 else "disliked" if rating <= 2 else None
        if not bucket:
            continue
        if genre and genre not in out[bucket]["genres"]:
            out[bucket]["genres"].append(genre)
        if style and style not in out[bucket]["styles"]:
            out[bucket]["styles"].append(style)
        dec = _decade(year)
        if dec and dec not in out[bucket]["decades"]:
            out[bucket]["decades"].append(dec)
    return out
```

- [ ] **Step 4: Run the tests, verify pass**

Run: `source venv/bin/activate && python -m pytest tests/test_database.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add database.py tests/test_database.py
git commit -m "feat: store mode/style/year and expose rated-attribute aggregates"
```

---

## Task 4: Deeper taste profile

**Files:**
- Modify: `discogs.py` (`build_taste_profile`, `format_profile_for_prompt`)
- Test: `tests/test_profile.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_profile.py`:

```python
import discogs


def test_profile_has_long_tail_sample_excluding_head(sample_collection, sample_wantlist):
    p = discogs.build_taste_profile(sample_collection, sample_wantlist, seed=1)
    head_styles = {s for s, _ in p["top_styles"][:12]}
    assert p["long_tail_styles"], "expected a non-empty long-tail sample"
    assert all(s not in head_styles for s in p["long_tail_styles"])
    # Roots Reggae / Spiritual Jazz etc. are 1-copy styles -> long tail
    assert "Roots Reggae" in p["long_tail_styles"] or "Spiritual Jazz" in p["long_tail_styles"]


def test_long_tail_sample_rotates_with_seed(sample_collection, sample_wantlist):
    a = discogs.build_taste_profile(sample_collection, sample_wantlist, seed=1)["long_tail_styles"]
    b = discogs.build_taste_profile(sample_collection, sample_wantlist, seed=1)["long_tail_styles"]
    c = discogs.build_taste_profile(sample_collection, sample_wantlist, seed=999)["long_tail_styles"]
    assert a == b, "same seed must be deterministic"
    assert a != c or len(a) <= 1, "different seed should usually reshuffle"


def test_genre_decades_crosstab(sample_collection, sample_wantlist):
    p = discogs.build_taste_profile(sample_collection, sample_wantlist, seed=1)
    assert "Electronic" in p["genre_decades"]
    total = sum(n for _, n in p["genre_decades"]["Electronic"])
    assert total == 35  # 20 techno + 15 ambient


def test_format_profile_mentions_long_tail_and_crosstab(sample_collection, sample_wantlist):
    p = discogs.build_taste_profile(sample_collection, sample_wantlist, seed=1)
    text = discogs.format_profile_for_prompt(p)
    assert "Less-explored corners" in text
    assert "by decade" in text
```

- [ ] **Step 2: Run it, verify failure**

Run: `source venv/bin/activate && python -m pytest tests/test_profile.py -v`
Expected: FAIL — `KeyError: 'long_tail_styles'`.

- [ ] **Step 3: Update `build_taste_profile` in `discogs.py`**

Replace the function body's `return` block and add logic. Full replacement:

```python
def build_taste_profile(collection: list[dict], wantlist: list[dict], seed=None) -> dict:
    import random
    from collections import Counter

    all_items = collection + wantlist
    genres: Counter = Counter()
    styles: Counter = Counter()
    artists: Counter = Counter()
    labels: Counter = Counter()
    decades: Counter = Counter()
    # genre -> Counter(decade -> count)
    genre_decade: dict[str, Counter] = {}

    for item in all_items:
        item_genres = item.get("genres") or []
        item_styles = item.get("styles") or []
        genres.update(item_genres)
        styles.update(item_styles)
        artists.update(item.get("artists") or [])
        labels.update(item.get("labels") or [])
        year = item.get("year")
        decade_label = None
        if year:
            try:
                decade_label = f"{(int(year) // 10) * 10}s"
                decades[decade_label] += 1
            except (ValueError, TypeError):
                decade_label = None
        if decade_label:
            for g in item_genres:
                genre_decade.setdefault(g, Counter())[decade_label] += 1

    top_genres = genres.most_common(10)
    top_styles = styles.most_common(15)

    # Long-tail sample: styles/artists below the head, with low counts, reshuffled per seed.
    rng = random.Random(seed)
    head_style_names = {s for s, _ in styles.most_common(20)}
    head_artist_names = {a for a, _ in artists.most_common(20)}
    tail_styles = [s for s, n in styles.items() if s not in head_style_names and 1 <= n <= 6]
    tail_artists = [a for a, n in artists.items() if a not in head_artist_names and 1 <= n <= 6]
    rng.shuffle(tail_styles)
    rng.shuffle(tail_artists)

    genre_decades = {
        g: sorted(genre_decade.get(g, {}).items())
        for g, _ in top_genres[:5]
    }

    return {
        "top_genres": top_genres,
        "top_styles": top_styles,
        "top_artists": artists.most_common(20),
        "top_labels": labels.most_common(10),
        "top_decades": sorted(decades.items()),
        "genre_decades": genre_decades,
        "long_tail_styles": tail_styles[:10],
        "long_tail_artists": tail_artists[:10],
        "total_collection": len(collection),
        "total_wantlist": len(wantlist),
    }
```

- [ ] **Step 4: Update `format_profile_for_prompt` in `discogs.py`**

Replace the function:

```python
def format_profile_for_prompt(profile: dict) -> str:
    total = profile["total_collection"] + profile["total_wantlist"]

    def pct(n):
        return f"{n / total * 100:.1f}%" if total > 0 else "?"

    lines = [
        f"Collection: {profile['total_collection']} records | Wantlist: {profile['total_wantlist']} records",
        "",
        "Genre breakdown (percentage of total collection):",
    ]
    for g, n in profile["top_genres"][:8]:
        lines.append(f"  {g}: {pct(n)}  ({n} records)")

    lines += ["", "Style breakdown:"]
    for s, n in profile["top_styles"][:12]:
        lines.append(f"  {s}: {pct(n)}  ({n} records)")

    lines += ["", "Top genres by decade:"]
    for g, buckets in profile["genre_decades"].items():
        if buckets:
            inner = ", ".join(f"{d} {n}" for d, n in buckets)
            lines.append(f"  {g}: {inner}")

    lines += [
        "",
        "Less-explored corners of the collection (styles owned in small numbers — good discovery territory):",
        "  " + ", ".join(profile["long_tail_styles"]) if profile["long_tail_styles"] else "  (none)",
        "Less-explored artists (owned in small numbers):",
        "  " + ", ".join(profile["long_tail_artists"]) if profile["long_tail_artists"] else "  (none)",
        "",
        "Decades:  " + ", ".join(f"{d} ({n})" for d, n in profile["top_decades"]),
        "Artists:  " + ", ".join(a for a, _ in profile["top_artists"][:12]),
        "Labels:   " + ", ".join(l for l, _ in profile["top_labels"][:8]),
    ]
    return "\n".join(lines)
```

- [ ] **Step 5: Run the tests, verify pass**

Run: `source venv/bin/activate && python -m pytest tests/test_profile.py -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add discogs.py tests/test_profile.py
git commit -m "feat: taste profile gains long-tail sample and decade x genre cross-tab"
```

---

## Task 5: Anchor picker

**Files:**
- Modify: `discogs.py` (add `pick_anchors`)
- Test: `tests/test_profile.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_profile.py`:

```python
def test_pick_anchors_deterministic_and_favours_long_tail(sample_collection):
    a = discogs.pick_anchors(sample_collection, n=3, seed=7)
    b = discogs.pick_anchors(sample_collection, n=3, seed=7)
    assert a == b
    assert len(a) == 3
    for rec in a:
        assert "title" in rec and "artists" in rec


def test_pick_anchors_handles_small_collection():
    tiny = [{"id": "1", "title": "Only One", "artists": ["Solo"], "genres": [], "styles": [], "year": 2000}]
    assert len(discogs.pick_anchors(tiny, n=3, seed=1)) == 1
```

- [ ] **Step 2: Run it, verify failure**

Run: `source venv/bin/activate && python -m pytest tests/test_profile.py -k anchors -v`
Expected: FAIL — `AttributeError: module 'discogs' has no attribute 'pick_anchors'`.

- [ ] **Step 3: Add `pick_anchors` to `discogs.py`**

Add after `build_taste_profile`:

```python
def pick_anchors(collection: list[dict], n: int = 3, seed=None) -> list[dict]:
    """Pick N records from the collection, weighted toward the long tail.

    Records by rarer artists/styles (within this collection) are more likely to be
    chosen, so the daily 'starting point' rotates away from the obvious favourites.
    """
    import random
    from collections import Counter

    if not collection:
        return []
    rng = random.Random(seed)

    artist_counts: Counter = Counter()
    style_counts: Counter = Counter()
    for item in collection:
        artist_counts.update(item.get("artists") or [])
        style_counts.update(item.get("styles") or [])

    def weight(item):
        a = min((artist_counts[x] for x in item.get("artists") or []), default=1)
        s = min((style_counts[x] for x in item.get("styles") or []), default=1)
        # rarer -> higher weight
        return 1.0 / (a + s)

    weights = [weight(it) for it in collection]
    k = min(n, len(collection))
    # weighted sample without replacement
    chosen = []
    pool = list(range(len(collection)))
    pool_w = list(weights)
    for _ in range(k):
        idx = rng.choices(pool, weights=pool_w, k=1)[0]
        pos = pool.index(idx)
        pool.pop(pos)
        pool_w.pop(pos)
        chosen.append(collection[idx])
    return chosen
```

- [ ] **Step 4: Run the tests, verify pass**

Run: `source venv/bin/activate && python -m pytest tests/test_profile.py -k anchors -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add discogs.py tests/test_profile.py
git commit -m "feat: add long-tail-weighted anchor picker"
```

---

## Task 6: `search_release` returns all pressings; `get_release_info` combines have/want/price/stock

**Files:**
- Modify: `discogs.py` (`search_release`, replace `get_community_stats` with `get_release_info`)
- Test: `tests/test_discogs.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_discogs.py`:

```python
import discogs


def test_search_release_returns_sorted_pressing_list(monkeypatch):
    fake = {
        "results": [
            {"id": 3, "title": "The Congos - Heart Of The Congos", "year": "2017",
             "formats": [{"name": "Vinyl"}]},
            {"id": 1, "title": "The Congos - Heart Of The Congos", "year": "1977",
             "formats": [{"name": "Vinyl"}]},
            {"id": 2, "title": "The Congos - Heart Of The Congos", "year": "1996",
             "formats": [{"name": "CD"}]},  # dropped: not vinyl/cassette
            {"id": 9, "title": "Someone Else - Other Record", "year": "1980",
             "formats": [{"name": "Vinyl"}]},  # dropped: artist mismatch
        ]
    }
    monkeypatch.setattr(discogs, "_get", lambda url, params=None: fake)
    out = discogs.search_release("The Congos", "Heart Of The Congos")
    assert [r["id"] for r in out] == ["1", "3"]
    assert out[0]["year"] == "1977"
    assert out[0]["format"] == "Vinyl"
    assert out[0]["url"] == "https://www.discogs.com/release/1"


def test_search_release_no_match_returns_empty_list(monkeypatch):
    monkeypatch.setattr(discogs, "_get", lambda url, params=None: {"results": []})
    assert discogs.search_release("Nobody", "Nothing") == []


def test_get_release_info_extracts_fields(monkeypatch):
    fake = {
        "community": {"have": 3100, "want": 1800},
        "lowest_price": 17.5, "num_for_sale": 42,
    }
    monkeypatch.setattr(discogs, "_get", lambda url, params=None: fake)
    info = discogs.get_release_info("123")
    assert info == {"have": 3100, "want": 1800, "lowest_price": 17.5, "num_for_sale": 42}


def test_get_release_info_handles_missing_price(monkeypatch):
    monkeypatch.setattr(discogs, "_get", lambda url, params=None: {"community": {}})
    info = discogs.get_release_info("123")
    assert info == {"have": 0, "want": 0, "lowest_price": None, "num_for_sale": 0}


def test_get_release_info_swallows_errors(monkeypatch):
    def boom(url, params=None):
        raise RuntimeError("network")
    monkeypatch.setattr(discogs, "_get", boom)
    assert discogs.get_release_info("123") == {
        "have": 0, "want": 0, "lowest_price": None, "num_for_sale": 0}
```

- [ ] **Step 2: Run it, verify failure**

Run: `source venv/bin/activate && python -m pytest tests/test_discogs.py -v`
Expected: FAIL — `search_release` returns a dict not a list; `get_release_info` missing.

- [ ] **Step 3: Rewrite `search_release` in `discogs.py`**

Replace the function (keep `_artist_matches` unchanged):

```python
def search_release(artist: str, title: str) -> list[dict]:
    """
    Search Discogs for a release, accepting only Vinyl or Cassette.
    Returns every matching pressing sorted oldest-first (undated last);
    empty list if nothing matches.
    """
    params = {"q": f"{artist} {title}", "type": "release", "per_page": 25}
    data = _get(f"{BASE_URL}/database/search", params=params)

    candidates = []
    for r in data.get("results", []):
        release_id = str(r.get("id", ""))
        if not release_id:
            continue
        result_title = r.get("title", "")
        if not _artist_matches(artist, result_title):
            continue

        formats = r.get("formats") or []
        if not formats:
            continue
        format_names = (
            {f.get("name", "") for f in formats}
            if isinstance(formats[0], dict) else set(formats)
        )
        matched_fmt = "Vinyl" if "Vinyl" in format_names else (
            "Cassette" if "Cassette" in format_names else None)
        if not matched_fmt:
            continue

        candidates.append({
            "id": release_id,
            "title": result_title,
            "url": f"https://www.discogs.com/release/{release_id}",
            "year": r.get("year"),
            "format": matched_fmt,
        })

    candidates.sort(key=lambda r: (r["year"] is None, int(r["year"]) if r["year"] else 9999))
    return candidates
```

- [ ] **Step 4: Replace `get_community_stats` with `get_release_info` in `discogs.py`**

```python
def get_release_info(release_id: str) -> dict:
    """Fetch have/want, cheapest listing price, and stock for one release."""
    from config import PRICE_CURRENCY_CODE
    try:
        data = _get(f"{BASE_URL}/releases/{release_id}",
                    params={"curr_abbr": PRICE_CURRENCY_CODE})
        community = data.get("community", {}) or {}
        return {
            "have": community.get("have", 0) or 0,
            "want": community.get("want", 0) or 0,
            "lowest_price": data.get("lowest_price"),
            "num_for_sale": data.get("num_for_sale", 0) or 0,
        }
    except Exception:
        return {"have": 0, "want": 0, "lowest_price": None, "num_for_sale": 0}
```

Delete the old `get_community_stats` function. `calculate_rarity` stays (used by Task 8's message as a secondary label — keep it).

- [ ] **Step 5: Run the tests, verify pass**

Run: `source venv/bin/activate && python -m pytest tests/test_discogs.py -v`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add discogs.py tests/test_discogs.py
git commit -m "feat: search_release returns pressing list; add get_release_info"
```

---

## Task 7: Scoring — `pick_mode`, `score_candidate`, `choose_pressing`

**Files:**
- Modify: `recommender.py` (add three pure functions near the top, after imports)
- Test: `tests/test_scoring.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_scoring.py`:

```python
import random
import recommender


def test_pick_mode_distribution():
    rng = random.Random(42)
    weights = {"core": 0.5, "adjacent": 0.3, "wildcard": 0.2}
    counts = {"core": 0, "adjacent": 0, "wildcard": 0}
    for _ in range(4000):
        counts[recommender.pick_mode(weights, rng)] += 1
    assert 0.44 < counts["core"] / 4000 < 0.56
    assert 0.24 < counts["adjacent"] / 4000 < 0.36
    assert 0.14 < counts["wildcard"] / 4000 < 0.26


PROFILE = {
    "top_genres": [("Electronic", 100), ("Reggae", 10)],
    "top_styles": [("Techno", 80), ("Ambient", 50)],
}
WEIGHTS = {"novelty": 1.0, "mode_fit": 0.6, "discoverable": 0.3, "price_band": 0.3}


def _cand(genre, style, band="mid"):
    return {"genre": genre, "style": style, "est_price_band": band}


def test_score_rewards_novelty():
    info = {"have": 1000}
    fresh = recommender.score_candidate(_cand("Jazz", "Spiritual Jazz"), info,
                                        recent_genres=["Electronic"], recent_styles=["Techno"],
                                        profile=PROFILE, mode="wildcard", weights=WEIGHTS,
                                        discoverable_range=(200, 3000))
    stale = recommender.score_candidate(_cand("Electronic", "Techno"), info,
                                        recent_genres=["Electronic"], recent_styles=["Techno"],
                                        profile=PROFILE, mode="wildcard", weights=WEIGHTS,
                                        discoverable_range=(200, 3000))
    assert fresh > stale


def test_score_mode_fit_core_vs_wildcard():
    info = {"have": 1000}
    kw = dict(recent_genres=[], recent_styles=[], profile=PROFILE, weights=WEIGHTS,
              discoverable_range=(200, 3000))
    core_hit = recommender.score_candidate(_cand("Electronic", "Techno"), info, mode="core", **kw)
    core_miss = recommender.score_candidate(_cand("Reggae", "Dub"), info, mode="core", **kw)
    assert core_hit > core_miss
    wild_hit = recommender.score_candidate(_cand("Jazz", "Free Jazz"), info, mode="wildcard", **kw)
    wild_miss = recommender.score_candidate(_cand("Electronic", "House"), info, mode="wildcard", **kw)
    assert wild_hit > wild_miss


def test_score_discoverable_bonus_and_price_penalty():
    kw = dict(recent_genres=[], recent_styles=[], profile=PROFILE, mode="core", weights=WEIGHTS,
              discoverable_range=(200, 3000))
    in_range = recommender.score_candidate(_cand("Electronic", "Techno"), {"have": 1000}, **kw)
    ubiquitous = recommender.score_candidate(_cand("Electronic", "Techno"), {"have": 50000}, **kw)
    assert in_range > ubiquitous
    collector = recommender.score_candidate(_cand("Electronic", "Techno", "collector"),
                                            {"have": 1000}, **kw)
    assert in_range > collector


# ---- choose_pressing ----

def _mk(pid, year):
    return {"id": pid, "year": str(year), "format": "Vinyl",
            "url": f"https://www.discogs.com/release/{pid}"}


def test_choose_pressing_original_cheap_takes_oldest():
    pressings = [_mk("og", 1977), _mk("re", 2017)]
    info = {"og": {"lowest_price": 22.0, "num_for_sale": 5, "have": 3000, "want": 900}}
    res = recommender.choose_pressing(pressings, "original", info.__getitem__, absurd_price=80.0)
    assert res["id"] == "og"
    assert res["reissue_fallback"] is False


def test_choose_pressing_original_absurd_falls_back_to_reissue():
    pressings = [_mk("og", 1977), _mk("re1", 2001), _mk("re2", 2017)]
    info = {
        "og": {"lowest_price": 220.0, "num_for_sale": 2, "have": 3000, "want": 4000},
        "re1": {"lowest_price": 15.0, "num_for_sale": 10, "have": 800, "want": 100},
        "re2": {"lowest_price": 40.0, "num_for_sale": 20, "have": 500, "want": 50},
    }
    res = recommender.choose_pressing(pressings, "original", info.__getitem__, absurd_price=80.0)
    assert res["id"] == "re1"
    assert res["reissue_fallback"] is True
    assert res["original_price"] == 220.0


def test_choose_pressing_any_picks_cheapest_in_stock():
    pressings = [_mk("a", 1990), _mk("b", 2005), _mk("c", 2020)]
    info = {
        "a": {"lowest_price": 30.0, "num_for_sale": 4, "have": 1, "want": 1},
        "b": {"lowest_price": 9.0, "num_for_sale": 0, "have": 1, "want": 1},   # no stock
        "c": {"lowest_price": 12.0, "num_for_sale": 8, "have": 1, "want": 1},
    }
    res = recommender.choose_pressing(pressings, "any", info.__getitem__, absurd_price=80.0)
    assert res["id"] == "c"


def test_choose_pressing_returns_none_when_all_absurd():
    pressings = [_mk("a", 1990)]
    info = {"a": {"lowest_price": 500.0, "num_for_sale": 1, "have": 1, "want": 1}}
    assert recommender.choose_pressing(pressings, "any", info.__getitem__, absurd_price=80.0) is None


def test_choose_pressing_empty_list_returns_none():
    assert recommender.choose_pressing([], "any", lambda x: {}, absurd_price=80.0) is None
```

- [ ] **Step 2: Run it, verify failure**

Run: `source venv/bin/activate && python -m pytest tests/test_scoring.py -v`
Expected: FAIL — `AttributeError: module 'recommender' has no attribute 'pick_mode'`.

- [ ] **Step 3: Add the three functions to `recommender.py`**

Insert after the imports (`import discogs` / `import database`) and before `SYSTEM_PROMPT`:

```python
import random as _random


def pick_mode(weights: dict, rng: _random.Random) -> str:
    modes = list(weights.keys())
    return rng.choices(modes, weights=[weights[m] for m in modes], k=1)[0]


def score_candidate(candidate: dict, info: dict, recent_genres: list[str],
                    recent_styles: list[str], profile: dict, mode: str,
                    weights: dict, discoverable_range=(200, 3000)) -> float:
    genre = candidate.get("genre", "")
    style = candidate.get("style", "")

    novelty = 0.0
    if genre and genre not in recent_genres:
        novelty += 0.5
    if style and style not in recent_styles:
        novelty += 0.5

    top_genres = {g for g, _ in profile.get("top_genres", [])}
    top_styles = {s for s, _ in profile.get("top_styles", [])}
    g_in, s_in = genre in top_genres, style in top_styles
    if mode == "core":
        fit = 1.0 if (g_in and s_in) else 0.0
    elif mode == "adjacent":
        fit = 1.0 if (g_in and not s_in) else 0.0
    else:  # wildcard
        fit = 1.0 if not g_in else 0.0

    have = info.get("have") or 0
    lo, hi = discoverable_range
    disc = 1.0 if lo <= have <= hi else 0.0

    price_pen = 1.0 if candidate.get("est_price_band") == "collector" else 0.0

    return (weights["novelty"] * novelty
            + weights["mode_fit"] * fit
            + weights["discoverable"] * disc
            - weights["price_band"] * price_pen)


def _pressing_result(pressing: dict, info: dict, reissue_fallback: bool,
                     original_price) -> dict:
    return {
        "id": pressing["id"],
        "year": pressing.get("year"),
        "url": pressing["url"],
        "format": pressing.get("format", "Vinyl"),
        "lowest_price": info.get("lowest_price"),
        "num_for_sale": info.get("num_for_sale", 0),
        "have": info.get("have", 0),
        "want": info.get("want", 0),
        "reissue_fallback": reissue_fallback,
        "original_price": original_price,
    }


def choose_pressing(pressings: list[dict], pressing_note: str, fetch_info,
                    absurd_price: float) -> dict | None:
    """Pick the pressing to point at. `fetch_info` maps release_id -> info dict
    (have/want/lowest_price/num_for_sale). Returns None if nothing affordable."""
    if not pressings:
        return None

    cache: dict = {}

    def info_for(p):
        if p["id"] not in cache:
            cache[p["id"]] = fetch_info(p["id"])
        return cache[p["id"]]

    def affordable(info):
        pr = info.get("lowest_price")
        return pr is not None and pr <= absurd_price and (info.get("num_for_sale", 0) or 0) > 0

    if pressing_note == "original":
        oldest = pressings[0]
        oi = info_for(oldest)
        if affordable(oi):
            return _pressing_result(oldest, oi, False, None)
        original_price = oi.get("lowest_price")
        best, best_info = None, None
        for p in pressings[1:4]:
            pi = info_for(p)
            if not affordable(pi):
                continue
            if best is None or pi["lowest_price"] < best_info["lowest_price"]:
                best, best_info = p, pi
        if best is not None:
            return _pressing_result(best, best_info, True, original_price)
        return None

    # "any"
    best, best_info = None, None
    for p in pressings[:4]:
        pi = info_for(p)
        if not affordable(pi):
            continue
        if best is None or pi["lowest_price"] < best_info["lowest_price"]:
            best, best_info = p, pi
    if best is not None:
        return _pressing_result(best, best_info, False, None)
    return None
```

- [ ] **Step 4: Run the tests, verify pass**

Run: `source venv/bin/activate && python -m pytest tests/test_scoring.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add recommender.py tests/test_scoring.py
git commit -m "feat: add pure mode-pick, candidate scoring, pressing selection"
```

---

## Task 8: Message format — price/availability line

**Files:**
- Modify: `bot.py` (`format_suggestion`)
- Test: `tests/test_bot_format.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_bot_format.py`:

```python
import bot


BASE = {
    "artist": "The Congos", "title": "Heart Of The Congos", "year": 1977,
    "format": "Vinyl", "genre": "Reggae", "why": "Roots reggae on Black Ark.",
    "discogs_url": "https://www.discogs.com/release/1",
    "have": 3100, "want": 1800, "lowest_price": 18.0, "num_for_sale": 42,
    "reissue_fallback": False, "original_price": None,
}


def test_format_shows_price_line():
    text = bot.format_suggestion(BASE)
    assert "From €18" in text
    assert "42 for sale" in text
    assert "3100 own / 1800 want" in text
    assert "Extremely Rare" not in text


def test_format_reissue_fallback_note():
    s = dict(BASE, reissue_fallback=True, original_price=210.0, year=2017)
    text = bot.format_suggestion(s)
    assert "original pressing" in text.lower()
    assert "210" in text


def test_format_handles_missing_price():
    s = dict(BASE, lowest_price=None, num_for_sale=0)
    text = bot.format_suggestion(s)
    assert "price unavailable" in text.lower()
```

- [ ] **Step 2: Run it, verify failure**

Run: `source venv/bin/activate && python -m pytest tests/test_bot_format.py -v`
Expected: FAIL — assertion errors (still shows the old rarity block).

- [ ] **Step 3: Rewrite `format_suggestion` in `bot.py`**

```python
def format_suggestion(s: dict) -> str:
    year_str = f" ({s['year']})" if s.get("year") else ""
    fmt_emoji = "\U0001F4FC" if s.get("format", "").lower() == "cassette" else "\U0001F3B5"

    price = s.get("lowest_price")
    num = s.get("num_for_sale", 0) or 0
    have = s.get("have", 0) or 0
    want = s.get("want", 0) or 0

    if price is not None:
        sym = config.PRICE_CURRENCY_SYMBOL
        price_str = f"From {sym}{price:g} · {num} for sale · {have} own / {want} want"
    else:
        price_str = f"Price unavailable · {have} own / {want} want"

    fallback_note = ""
    if s.get("reissue_fallback") and s.get("original_price"):
        sym = config.PRICE_CURRENCY_SYMBOL
        fallback_note = (
            f"\n_(original pressing runs ~{sym}{s['original_price']:g}; "
            f"this points to the {s.get('year', 'reissue')} reissue)_"
        )

    return (
        f"{fmt_emoji} *{s['artist']}* – _{s['title']}{year_str}_\n\n"
        f"{s['why']}\n\n"
        f"{price_str}{fallback_note}\n\n"
        f"\U0001F517 [View on Discogs]({s['discogs_url']})"
    )
```

Confirm `import config` is present at the top of `bot.py` (it is — line 18).

- [ ] **Step 4: Run the tests, verify pass**

Run: `source venv/bin/activate && python -m pytest tests/test_bot_format.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add bot.py tests/test_bot_format.py
git commit -m "feat: message shows price/availability instead of rarity headline"
```

---

## Task 9: Rewrite the Claude prompt for 5 candidates + modes

**Files:**
- Modify: `recommender.py` (`SYSTEM_PROMPT`, `_ask_claude`)

- [ ] **Step 1: Replace `SYSTEM_PROMPT` in `recommender.py`**

```python
SYSTEM_PROMPT = """You are a record-collecting guide with deep, wide knowledge of physical music.
Given a collector's Discogs taste profile and a target "mode" for today, you propose FIVE
distinct candidate records they could buy on vinyl or cassette.

FORMAT RULE: vinyl or cassette only. No CD, no digital, no DVD.

Respond with a single valid JSON array of exactly 5 objects — no markdown, no prose:
[
  {
    "artist": "Artist Name",
    "title": "Album Title",
    "year": 1977,
    "format": "Vinyl",
    "genre": "Reggae",
    "style": "Roots Reggae",
    "pressing_note": "original",
    "est_price_band": "mid",
    "reason": "One concise factual sentence: label, producer, or a notable fact."
  },
  ... 4 more ...
]

Field rules:
- "format": "Vinyl" or "Cassette".
- "genre": one broad genre (e.g. "Electronic", "Jazz", "Reggae").
- "style": one specific style/sub-genre (e.g. "Dub Techno", "Spiritual Jazz").
- "pressing_note": "original" if only an early pressing is worth pointing to,
  "any" if a later reissue serves the music just as well.
- "est_price_band": your rough guess of the cheapest copy — "budget" (<~15),
  "mid" (~15-50), or "collector" (rare/expensive). Be honest; do not label
  known expensive records as "mid".
- "reason": the record itself, not why it fits the collector. No references to their collection.

Hard rules:
- Real releases that exist on Discogs as vinyl or cassette.
- None of the five may be in the collector's collection or wantlist, or in the
  recently-suggested list provided.
- The five must be genuinely different from each other (different artists).
- Prefer records that are actually findable — avoid ultra-rare collector items
  unless the mode explicitly calls for a deep cut.

MODE — today's target:
- "core": squarely within the collector's established taste; something strong they have likely missed.
- "adjacent": a scene or style that borders their collection but is NOT in it — one step outside.
- "wildcard": a deliberate left turn — a genre they own very little of, or a lateral
  connection (a producer, label-mate, or contemporary of a record they own).
"""
```

- [ ] **Step 2: Rewrite `_ask_claude` in `recommender.py`**

```python
def _ask_claude(taste_summary: str, mode: str, anchors: list[str],
                already_suggested: list[str], recent_artists: list[str],
                rated_attrs: dict, feedback: str = "") -> list[dict]:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    anchor_block = ""
    if anchors:
        anchor_block = ("\n\nAnchor records the collector owns — propose things in dialogue "
                        "with these (not more copies of them):\n" + "\n".join(f"- {a}" for a in anchors))

    exclusion = ""
    if already_suggested:
        exclusion = ("\n\nDo NOT propose any of these already-sent records:\n"
                     + "\n".join(f"- {s}" for s in already_suggested[-30:]))

    artist_exclusion = ""
    if recent_artists:
        artist_exclusion = ("\n\nAvoid these artists — suggested recently:\n"
                            + "\n".join(f"- {a}" for a in recent_artists))

    taste_feedback = ""
    liked = rated_attrs.get("liked", {})
    disliked = rated_attrs.get("disliked", {})
    liked_bits = liked.get("genres", []) + liked.get("styles", []) + liked.get("decades", [])
    disliked_bits = disliked.get("genres", []) + disliked.get("styles", []) + disliked.get("decades", [])
    if liked_bits:
        taste_feedback += "\n\nThe collector responded well to: " + ", ".join(liked_bits) + "."
    if disliked_bits:
        taste_feedback += "\nResponded poorly to: " + ", ".join(disliked_bits) + "."

    user_message = (
        f"Collector's taste profile:\n\n{taste_summary}"
        f"{taste_feedback}{anchor_block}{exclusion}{artist_exclusion}"
        f"\n\nToday's mode: {mode.upper()}."
        f"{feedback}"
        "\n\nPropose 5 candidates. Respond only with the JSON array."
    )

    message = client.messages.create(
        model="claude-opus-5",
        max_tokens=1500,
        thinking={"type": "adaptive"},
        output_config={"effort": "medium"},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = "".join(b.text for b in message.content if b.type == "text").strip()
    raw = re.sub(r"^```[a-z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    parsed = json.loads(raw)
    if not isinstance(parsed, list):
        raise ValueError("expected a JSON array of candidates")
    return parsed
```

- [ ] **Step 3: Verify the module imports**

Run: `source venv/bin/activate && python -c "import recommender; print(recommender.SYSTEM_PROMPT[:40])"`
Expected: `You are a record-collecting guide with de`

- [ ] **Step 4: Run the whole suite (nothing should regress)**

Run: `source venv/bin/activate && python -m pytest`
Expected: all tests from Tasks 3–8 pass (28 passed).

- [ ] **Step 5: Commit**

```bash
git add recommender.py
git commit -m "feat: prompt Claude for 5 mode-targeted candidates on opus-5"
```

---

## Task 10: Rewrite `get_suggestion` orchestration

**Files:**
- Modify: `recommender.py` (`get_suggestion`)
- Test: `tests/test_scoring.py` (append an integration-style test with everything mocked)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_scoring.py`:

```python
import discogs as _discogs
import database as _database


def test_get_suggestion_end_to_end(monkeypatch, temp_db, sample_collection, sample_wantlist):
    monkeypatch.setattr(_discogs, "fetch_collection_and_wantlist",
                        lambda: (sample_collection, sample_wantlist))

    candidates = [
        {"artist": "Sun Ra", "title": "Lanquidity", "year": 1978, "format": "Vinyl",
         "genre": "Jazz", "style": "Free Jazz", "pressing_note": "any",
         "est_price_band": "mid", "reason": "Cosmic jazz on Philly Jazz."},
        {"artist": "Pole", "title": "1", "year": 1998, "format": "Vinyl",
         "genre": "Electronic", "style": "Dub Techno", "pressing_note": "any",
         "est_price_band": "mid", "reason": "Glitch dub on Kiff SM."},
    ]
    monkeypatch.setattr(recommender, "_ask_claude",
                        lambda *a, **k: candidates)

    monkeypatch.setattr(_discogs, "search_release",
                        lambda artist, title: [
                            {"id": f"{artist}-og", "year": "1978", "format": "Vinyl",
                             "url": "u1"},
                            {"id": f"{artist}-re", "year": "2010", "format": "Vinyl",
                             "url": "u2"},
                        ])

    def fake_info(rid):
        return {"have": 1200, "want": 300, "lowest_price": 20.0, "num_for_sale": 5}
    monkeypatch.setattr(_discogs, "get_release_info", fake_info)

    monkeypatch.setattr(recommender._random, "Random", lambda *a, **k: __import__("random").Random(0))

    out = recommender.get_suggestion()
    assert out is not None
    assert out["artist"] in ("Sun Ra", "Pole")
    assert out["lowest_price"] == 20.0
    assert "mode" in out
    assert out["discogs_url"] in ("u1", "u2")
```

- [ ] **Step 2: Run it, verify failure**

Run: `source venv/bin/activate && python -m pytest tests/test_scoring.py::test_get_suggestion_end_to_end -v`
Expected: FAIL — old `get_suggestion` calls `_ask_claude` with the old signature / `get_community_stats`.

- [ ] **Step 3: Rewrite `get_suggestion` in `recommender.py`**

```python
def get_suggestion(max_rounds: int = 2) -> dict | None:
    """Build a profile, ask Claude for candidates, score, resolve, pick a pressing."""
    import config

    print("Loading Discogs collection and wantlist…")
    collection, wantlist = discogs.fetch_collection_and_wantlist()
    print(f"  {len(collection)} collection + {len(wantlist)} wantlist items")

    seed = _random.randrange(1_000_000)
    rng = _random.Random(seed)
    mode = pick_mode(config.MODE_WEIGHTS, rng)
    print(f"  Mode: {mode} (seed {seed})")

    profile = discogs.build_taste_profile(collection, wantlist, seed=seed)
    taste_summary = discogs.format_profile_for_prompt(profile)
    owned_ids = discogs.get_owned_ids(collection, wantlist)
    owned_titles = discogs.get_owned_titles(collection, wantlist)

    anchors = [
        f"{' & '.join(r.get('artists', []))} – {r.get('title', '')}"
        for r in discogs.pick_anchors(collection, config.ANCHOR_COUNT, seed=seed)
    ]

    history = database.get_history(limit=50)
    already_suggested = [f"{h['artist']} – {h['title']}" for h in history]
    recent_artists = database.get_recent_artists(limit=10)
    recent_genres = database.get_recent_genres(limit=10)
    recent_styles = database.get_recent_styles(limit=10)
    rated_attrs = database.get_rated_attributes()

    rejected_feedback = ""

    for rnd in range(1, max_rounds + 1):
        print(f"Asking Claude for candidates (round {rnd}/{max_rounds})…")
        try:
            candidates = _ask_claude(taste_summary, mode, anchors, already_suggested,
                                     recent_artists, rated_attrs, feedback=rejected_feedback)
        except (json.JSONDecodeError, KeyError, IndexError, ValueError, TypeError) as e:
            print(f"  Claude response parse error: {e}")
            continue

        # Hard filters
        viable = []
        for c in candidates:
            artist = c.get("artist", "")
            title = c.get("title", "")
            if not artist or not title:
                continue
            if artist in recent_artists:
                continue
            if (discogs.normalize(artist), discogs.normalize(title)) in owned_titles:
                continue
            if f"{artist} – {title}" in already_suggested:
                continue
            viable.append(c)

        # Resolve + score
        scored = []
        for c in viable:
            pressings = discogs.search_release(c["artist"], c["title"])
            if not pressings:
                continue
            if pressings[0]["id"] in owned_ids or database.already_sent(pressings[0]["id"]):
                continue
            head_info = discogs.get_release_info(pressings[0]["id"])
            score = score_candidate(c, head_info, recent_genres, recent_styles,
                                    profile, mode, config.SCORE_WEIGHTS,
                                    discoverable_range=tuple(config.DISCOVERABLE_HAVE_RANGE))
            scored.append((score, c, pressings, head_info))

        scored.sort(key=lambda t: t[0], reverse=True)

        for score, c, pressings, head_info in scored:
            def fetch_info(rid, _head=(pressings[0]["id"], head_info)):
                return _head[1] if rid == _head[0] else discogs.get_release_info(rid)

            chosen = choose_pressing(pressings, c.get("pressing_note", "any"),
                                     fetch_info, config.ABSURD_PRICE)
            if chosen is None:
                continue
            if chosen["id"] in owned_ids or database.already_sent(chosen["id"]):
                continue

            print(f"  Pick: {c['artist']} – {c['title']} "
                  f"[{chosen['format']}] {config.PRICE_CURRENCY_SYMBOL}{chosen['lowest_price']}")
            return {
                "artist": c["artist"],
                "title": c["title"],
                "year": chosen.get("year") or c.get("year"),
                "format": chosen.get("format", c.get("format", "Vinyl")),
                "genre": c.get("genre", ""),
                "style": c.get("style", ""),
                "mode": mode,
                "why": c.get("reason", ""),
                "discogs_url": chosen["url"],
                "discogs_id": chosen["id"],
                "have": chosen["have"],
                "want": chosen["want"],
                "lowest_price": chosen["lowest_price"],
                "num_for_sale": chosen["num_for_sale"],
                "reissue_fallback": chosen["reissue_fallback"],
                "original_price": chosen["original_price"],
            }

        rejected_feedback = ("\n\nThe previous candidates were all rejected (owned, "
                             "already suggested, unavailable, or too expensive). "
                             "Propose 5 completely different ones.")

    print("Could not find a valid suggestion after all rounds.")
    return None
```

- [ ] **Step 4: Run the test, verify pass**

Run: `source venv/bin/activate && python -m pytest tests/test_scoring.py::test_get_suggestion_end_to_end -v`
Expected: PASS.

- [ ] **Step 5: Run the whole suite**

Run: `source venv/bin/activate && python -m pytest`
Expected: 29 passed.

- [ ] **Step 6: Commit**

```bash
git add recommender.py tests/test_scoring.py
git commit -m "feat: candidate-ranking orchestration with price-aware pressing pick"
```

---

## Task 11: Wire mode/style/year into `bot.py` record calls

**Files:**
- Modify: `bot.py` (`cmd_suggest` ~line 93, `daily_suggestion` ~line 164)

- [ ] **Step 1: Update both `database.record_suggestion(...)` calls in `bot.py`**

Both call sites currently pass `(discogs_id, artist, title, format, genre)`. Change both to:

```python
    database.record_suggestion(
        suggestion["discogs_id"],
        suggestion["artist"],
        suggestion["title"],
        suggestion.get("format", ""),
        suggestion.get("genre", ""),
        suggestion.get("style", ""),
        suggestion.get("year"),
        suggestion.get("mode", ""),
    )
```

- [ ] **Step 2: Check for other `get_community_stats` / old `search_release` callers**

Run: `grep -rn "get_community_stats\|calculate_rarity\|rarity_bar\|rarity_label" *.py`
Expected: only `discogs.py` (definition of `calculate_rarity`, now unused). If `bot.py` or `recommender.py` still reference `rarity_bar`/`rarity_label`/`get_community_stats`, remove those references — they were replaced in Tasks 6–8 and 10.

- [ ] **Step 3: Delete now-dead `calculate_rarity`**

If Step 2 confirms nothing references it, delete `calculate_rarity` from `discogs.py` and its row in `HOW_IT_WORKS.md` (handled in Task 12).

- [ ] **Step 4: Run the suite**

Run: `source venv/bin/activate && python -m pytest`
Expected: 29 passed.

- [ ] **Step 5: Commit**

```bash
git add bot.py discogs.py
git commit -m "chore: pass mode/style/year to record_suggestion; drop dead rarity code"
```

---

## Task 12: Update `HOW_IT_WORKS.md`

**Files:**
- Modify: `HOW_IT_WORKS.md`

- [ ] **Step 1: Rewrite sections 2–5 and 6**

Replace section **2. Claude AI suggestion** with a description of: daily mode (core/adjacent/wildcard weighted 50/30/20), anchors, and the 5-candidate request. Replace the JSON example with the new candidate shape (`style`, `pressing_note`, `est_price_band`, `reason`).

Replace section **3. Filters & checks** table — keep the owned/artist-cooldown/already-sent rows, add a **Candidate scoring** row (novelty + mode fit + discoverability + price band), and remove the "genre rotation via last-5" row (superseded by novelty scoring).

Replace section **4. Discogs search — oldest pressing** with **4. Pressing selection**: `search_release` returns all Vinyl/Cassette pressings; `choose_pressing` picks per Claude's `pressing_note` — original (oldest non-absurd, else reissue fallback) or any (cheapest in stock); records over `ABSURD_PRICE` are skipped.

Replace section **5. Rarity score** with **5. Price & availability**: the message shows `lowest_price`, `num_for_sale`, and `have`/`want` from the Discogs release; no rarity tiers.

Update section **6. Rating system**: ratings now also feed genre/style/decade aggregates ("responded well to … / poorly to …") into the prompt.

Add a short **Tuning** section listing the `config.py` constants: `MODE_WEIGHTS`, `ABSURD_PRICE`, `ANCHOR_COUNT`, `DISCOVERABLE_HAVE_RANGE`, `SCORE_WEIGHTS`, `PRICE_CURRENCY_CODE`/`PRICE_CURRENCY_SYMBOL`.

- [ ] **Step 2: Commit**

```bash
git add HOW_IT_WORKS.md
git commit -m "docs: update HOW_IT_WORKS for modes, candidates, price selection"
```

---

## Task 13: Live smoke test

**Files:** none (manual verification)

- [ ] **Step 1: Full suite green**

Run: `source venv/bin/activate && python -m pytest -v`
Expected: 29 passed.

- [ ] **Step 2: One live suggestion, no Telegram send**

Run:
```bash
source venv/bin/activate && python -c "
import recommender, json
s = recommender.get_suggestion()
print(json.dumps(s, indent=2, default=str))
"
```
Expected: a dict with `artist`, `title`, `mode`, `lowest_price` (a number in the account currency), `num_for_sale`, `discogs_url`. Console shows the chosen `Mode:` and `Pick:` lines.

- [ ] **Step 3: Verify currency**

Open the printed `discogs_url` in a browser and compare the lowest listed price to `lowest_price`. If the number matches the site's non-EUR figure, set `PRICE_CURRENCY_CODE` / `PRICE_CURRENCY_SYMBOL` in `config.py` accordingly and re-run Step 2.

- [ ] **Step 4: Render check**

Run:
```bash
source venv/bin/activate && python -c "
import recommender, bot
s = recommender.get_suggestion()
print(bot.format_suggestion(s))
"
```
Expected: a clean Telegram-style message with the `From <sym><price> · N for sale · X own / Y want` line and no `💎` / "Rare" text.

- [ ] **Step 5: Commit any config currency fix**

```bash
git add config.py
git commit -m "chore: set price currency to match Discogs account"
```
(Skip if no change was needed.)

- [ ] **Step 6: Restart the service**

Run: `launchctl unload ~/Library/LaunchAgents/com.stefano.vinylbot.plist && launchctl load ~/Library/LaunchAgents/com.stefano.vinylbot.plist`
Then send `/suggest` in Telegram and confirm the message and rating buttons work end to end.

---

## Self-Review Notes

**Spec coverage:**
- §1 deeper profile → Task 4. §2 daily mode → Tasks 2, 7 (`pick_mode`), 10 (wiring), 3 (DB column). §3 anchors → Task 5, 10. §4 candidates + ranking → Tasks 7 (`score_candidate`, `choose_pressing`), 9 (prompt), 10 (orchestration). §5 price message → Tasks 6, 8. §6 attribute feedback → Tasks 3 (`get_rated_attributes`), 9 (prompt). §7 drop owned-titles dump → Task 9 (`_ask_claude` no longer builds `owned_exclusion`). §8 model bump → Task 9.
- Config knobs (spec "Config additions") → Task 2. Testing section → every task is TDD; Task 13 is the live smoke test.

**Type consistency:** `get_release_info` returns `{have, want, lowest_price, num_for_sale}` everywhere (Tasks 6, 7, 10). `choose_pressing` result keys (`id, year, url, format, lowest_price, num_for_sale, have, want, reissue_fallback, original_price`) consumed unchanged by `get_suggestion` (Task 10) and `format_suggestion` (Task 8). `record_suggestion` signature `(discogs_id, artist, title, fmt, genre, style, year, mode)` matches the call sites in Task 11 and the test in Task 3. `_ask_claude(taste_summary, mode, anchors, already_suggested, recent_artists, rated_attrs, feedback="")` matches the call in Task 10.

**Deviations from spec:** spec named `get_release_price` + kept `get_community_stats`; plan merges both into `get_release_info` (one release GET already returns all four fields — DRY, fewer calls). Spec's `pick_mode(weights, rng)` — kept. No functional gap.
