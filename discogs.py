"""
Discogs API helpers using the REST API directly.
"""
import re
import time
import requests
from config import DISCOGS_TOKEN, DISCOGS_USERNAME

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

def build_taste_profile(collection: list[dict], wantlist: list[dict]) -> dict:
    from collections import Counter

    all_items = collection + wantlist
    genres: Counter = Counter()
    styles: Counter = Counter()
    artists: Counter = Counter()
    labels: Counter = Counter()
    decades: Counter = Counter()

    for item in all_items:
        genres.update(item.get("genres") or [])
        styles.update(item.get("styles") or [])
        artists.update(item.get("artists") or [])
        labels.update(item.get("labels") or [])
        year = item.get("year")
        if year:
            try:
                decade = (int(year) // 10) * 10
                decades[f"{decade}s"] += 1
            except (ValueError, TypeError):
                pass

    return {
        "top_genres": genres.most_common(10),
        "top_styles": styles.most_common(15),
        "top_artists": artists.most_common(20),
        "top_labels": labels.most_common(10),
        "top_decades": sorted(decades.items()),
        "total_collection": len(collection),
        "total_wantlist": len(wantlist),
    }


def format_profile_for_prompt(profile: dict) -> str:
    lines = [
        f"Collection size: {profile['total_collection']} records",
        f"Wantlist size:   {profile['total_wantlist']} records",
        "",
        "Top genres:    " + ", ".join(f"{g} ({n})" for g, n in profile["top_genres"]),
        "Top styles:    " + ", ".join(f"{s} ({n})" for s, n in profile["top_styles"]),
        "Top decades:   " + ", ".join(f"{d} ({n})" for d, n in profile["top_decades"]),
        "Fav artists:   " + ", ".join(a for a, _ in profile["top_artists"][:12]),
        "Fav labels:    " + ", ".join(l for l, _ in profile["top_labels"][:8]),
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Release search (vinyl & cassette only)
# ---------------------------------------------------------------------------

def search_release(artist: str, title: str) -> dict | None:
    """
    Search Discogs for a specific release, accepting only Vinyl or Cassette.
    Collects all matching pressings and returns the oldest one.
    """
    candidates = []
    for fmt in ("Vinyl", "Cassette"):
        params = {
            "artist": artist,
            "release_title": title,
            "format": fmt,
            "type": "release",
            "per_page": 10,
        }
        data = _get(f"{BASE_URL}/database/search", params=params)
        for r in data.get("results", []):
            release_id = str(r.get("id", ""))
            if release_id:
                candidates.append({
                    "id": release_id,
                    "title": r.get("title", ""),
                    "url": f"https://www.discogs.com/release/{release_id}",
                    "year": r.get("year"),
                    "format": fmt,
                })

    if not candidates:
        return None

    # Prefer the oldest pressing; entries without a year go last
    candidates.sort(key=lambda r: (r["year"] is None, int(r["year"]) if r["year"] else 9999))
    return candidates[0]


# ---------------------------------------------------------------------------
# Community stats for rarity
# ---------------------------------------------------------------------------

def get_community_stats(release_id: str) -> dict:
    """Fetch have/want counts for a release."""
    try:
        data = _get(f"{BASE_URL}/releases/{release_id}")
        community = data.get("community", {})
        return {
            "have": community.get("have", 0),
            "want": community.get("want", 0),
        }
    except Exception:
        return {"have": 0, "want": 0}


def calculate_rarity(have: int, want: int) -> tuple[str, str]:
    """
    Returns (emoji_bar, label) based on how many collectors own the release.
    Lower `have` count = rarer.
    """
    if have == 0:
        return "💎💎💎💎💎", "Extremely Rare"
    elif have < 50:
        return "💎💎💎💎", "Very Rare"
    elif have < 300:
        return "💎💎💎", "Rare"
    elif have < 1500:
        return "💎💎", "Uncommon"
    else:
        return "💎", "Common"


def get_owned_ids(collection: list[dict], wantlist: list[dict]) -> set[str]:
    return {item["id"] for item in collection + wantlist}


def get_owned_titles(collection: list[dict], wantlist: list[dict]) -> set[tuple[str, str]]:
    """
    Return a set of normalized (artist, title) pairs for every owned release,
    so any repress or reissue of the same album can be detected and excluded.
    """
    owned = set()
    for item in collection + wantlist:
        artists = item.get("artists", [])
        title = item.get("title", "")
        if artists and title:
            owned.add((normalize(artists[0]), normalize(title)))
    return owned
