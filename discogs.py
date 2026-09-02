"""
Discogs API helpers using the REST API directly.
"""
import json
import os
import random
import re
import time
from collections import Counter
from datetime import datetime, timezone
import requests
from config import DISCOGS_TOKEN, DISCOGS_USERNAME, CACHE_PATH, CACHE_TTL_HOURS

BASE_URL = "https://api.discogs.com"
HEADERS = {
    "Authorization": f"Discogs token={DISCOGS_TOKEN}",
    "User-Agent": "discogs-vinyl-bot/1.0",
}

ALLOWED_FORMATS = {"Vinyl", "Cassette"}


def normalize(s: str) -> str:
    """Normalize a string for loose matching across represses/reissues."""
    s = s.lower().strip()
    s = re.sub(r'\(.*?\)', '', s)       # remove parenthetical suffixes e.g. (Remastered)
    s = re.sub(r'[^a-z0-9\s]', '', s)  # strip punctuation
    s = re.sub(r'\s+', ' ', s).strip()
    s = re.sub(r'^the\s+', '', s)       # ignore leading "The"
    return s


def _get(url, params=None) -> dict:
    resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
    resp.raise_for_status()
    time.sleep(0.5)  # stay under 60 req/min
    return resp.json()


def _fetch_all_pages(url: str, data_key: str, extra_params: dict = None) -> list:
    items = []
    page = 1
    while True:
        params = {"page": page, "per_page": 100}
        if extra_params:
            params.update(extra_params)
        data = _get(url, params=params)
        items.extend(data.get(data_key, []))
        pagination = data.get("pagination", {})
        if page >= pagination.get("pages", 1):
            break
        page += 1
    return items


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _cache_is_fresh() -> bool:
    if not os.path.exists(CACHE_PATH):
        return False
    try:
        with open(CACHE_PATH) as f:
            data = json.load(f)
        cached_at = datetime.fromisoformat(data["cached_at"])
        age_hours = (datetime.now(timezone.utc) - cached_at).total_seconds() / 3600
        return age_hours < CACHE_TTL_HOURS
    except Exception:
        return False


def _load_cache() -> tuple[list, list]:
    with open(CACHE_PATH) as f:
        data = json.load(f)
    return data["collection"], data["wantlist"]


def _save_cache(collection: list, wantlist: list):
    with open(CACHE_PATH, "w") as f:
        json.dump({
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "collection": collection,
            "wantlist": wantlist,
        }, f)


# ---------------------------------------------------------------------------
# Collection / wantlist fetching
# ---------------------------------------------------------------------------

def fetch_collection() -> list[dict]:
    url = f"{BASE_URL}/users/{DISCOGS_USERNAME}/collection/folders/0/releases"
    items = _fetch_all_pages(url, "releases")
    return [_parse_basic(item) for item in items]


def fetch_wantlist() -> list[dict]:
    url = f"{BASE_URL}/users/{DISCOGS_USERNAME}/wants"
    items = _fetch_all_pages(url, "wants")
    return [_parse_basic(item) for item in items]


def fetch_collection_and_wantlist() -> tuple[list[dict], list[dict]]:
    """
    Return (collection, wantlist), using a local cache refreshed every 24 hours.
    This avoids hitting the Discogs API on every suggestion request.
    """
    if _cache_is_fresh():
        print("  Using cached Discogs data.")
        return _load_cache()

    print("  Cache stale or missing — fetching from Discogs…")
    collection = fetch_collection()
    wantlist = fetch_wantlist()
    _save_cache(collection, wantlist)
    print(f"  Cached {len(collection)} collection + {len(wantlist)} wantlist items.")
    return collection, wantlist


def _parse_basic(item: dict) -> dict:
    info = item.get("basic_information", {})
    return {
        "id": str(item.get("id", info.get("id", ""))),
        "title": info.get("title", ""),
        "artists": [a.get("name", "") for a in info.get("artists", [])],
        "genres": info.get("genres", []),
        "styles": info.get("styles", []),
        "labels": [l.get("name", "") for l in info.get("labels", [])],
        "year": info.get("year"),
    }


# ---------------------------------------------------------------------------
# Taste profile builder
# ---------------------------------------------------------------------------

def build_taste_profile(collection: list[dict], wantlist: list[dict], seed=None) -> dict:
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
    # "Recurring" styles = owned in real numbers; the rest is discovery territory.
    top_styles = [(s, n) for s, n in styles.most_common(15) if n >= 2] or styles.most_common(15)

    # Long-tail sample: styles/artists below the head, with low counts, reshuffled per seed.
    rng = random.Random(seed)
    head_style_names = {s for s, _ in top_styles}
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


def pick_anchors(collection: list[dict], n: int = 3, seed=None) -> list[dict]:
    """Pick N records from the collection, weighted toward the long tail.

    Records by rarer artists/styles (within this collection) are more likely to be
    chosen, so the daily 'starting point' rotates away from the obvious favourites.
    """
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


# ---------------------------------------------------------------------------
# Release search (vinyl & cassette only)
# ---------------------------------------------------------------------------

def _artist_matches(suggested_artist: str, result_title: str) -> bool:
    """
    Discogs search results return title as "Artist - Album".
    Check that the suggested artist appears in the result's artist portion.
    """
    norm_suggested = normalize(suggested_artist)
    # result_title is "Artist Name - Album Title"
    result_artist = result_title.split(" - ")[0] if " - " in result_title else result_title
    norm_result = normalize(result_artist)
    # Accept if either contains the other (handles "Maurizio" matching "Maurizio")
    return norm_suggested in norm_result or norm_result in norm_suggested


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


# ---------------------------------------------------------------------------
# Community stats for rarity
# ---------------------------------------------------------------------------

def get_release_info(release_id: str) -> dict:
    """Fetch have/want, cheapest listing price, and stock for one release.

    have/want come from GET /releases/{id} .community.
    lowest_price / num_for_sale come from GET /marketplace/stats/{id}, whose
    lowest_price field is a nested {"value", "currency"} object (or null) and is
    far more reliable than the release endpoint's own lowest_price.
    """
    from config import PRICE_CURRENCY_CODE
    try:
        release = _get(f"{BASE_URL}/releases/{release_id}")
        community = release.get("community", {}) or {}

        stats = _get(f"{BASE_URL}/marketplace/stats/{release_id}",
                     params={"curr_abbr": PRICE_CURRENCY_CODE})
        price_obj = stats.get("lowest_price") or {}
        lowest_price = price_obj.get("value") if isinstance(price_obj, dict) else None

        return {
            "have": community.get("have", 0) or 0,
            "want": community.get("want", 0) or 0,
            "lowest_price": lowest_price,
            "num_for_sale": int(stats.get("num_for_sale", 0) or 0),
        }
    except Exception:
        return {"have": 0, "want": 0, "lowest_price": None, "num_for_sale": 0}


def get_owned_ids(collection: list[dict], wantlist: list[dict]) -> set[str]:
    return {item["id"] for item in collection + wantlist}


def get_owned_titles(collection: list[dict], wantlist: list[dict]) -> set[tuple[str, str]]:
    """
    Return a set of normalized (artist, title) pairs for every owned release,
    so any repress or reissue of the same album can be detected and excluded.

    For multi-artist releases (e.g. Discogs stores ["Cluster", "Eno"] separately),
    we store both the first artist alone AND all artists joined, so that a Claude
    suggestion like "Cluster & Eno" still matches correctly.
    """
    owned = set()
    for item in collection + wantlist:
        artists = item.get("artists", [])
        title = item.get("title", "")
        if not artists or not title:
            continue
        norm_title = normalize(title)
        # First artist alone
        owned.add((normalize(artists[0]), norm_title))
        # All artists joined — catches "Cluster & Eno" style suggestions
        if len(artists) > 1:
            owned.add((normalize(" ".join(artists)), norm_title))
    return owned
