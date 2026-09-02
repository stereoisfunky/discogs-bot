"""
Uses Claude to generate a vinyl/cassette suggestion based on the user's taste profile,
then resolves it to a real Discogs release with community rarity stats.
"""
import json
import re
import anthropic

from config import ANTHROPIC_API_KEY
import discogs
import database


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


SYSTEM_PROMPT = """You are a passionate vinyl record expert and music curator.
Your job is to suggest one specific physical music release that a collector would love,
based on their Discogs taste profile.

IMPORTANT FORMAT RULE: You may ONLY suggest releases available on VINYL or CASSETTE.
No CDs, no digital releases, no WAV/FLAC releases, no DVDs. Vinyl or cassette only.

You must respond with a single valid JSON object — no markdown, no extra text —
with exactly these fields:
{
  "artist": "Artist Name",
  "title": "Album Title",
  "year": 1973,
  "format": "Vinyl",
  "genre": "Reggae",
  "info": "Label: Trojan Records. One concise sentence of factual context about the release."
}

The "format" field must be either "Vinyl" or "Cassette".
The "genre" field must be one broad genre from the user's profile (e.g. "Electronic", "Reggae", "Jazz").
The "info" field must be SHORT and FACTUAL — label, key collaborators, or one notable fact about the release.
Do NOT explain why it fits the collector's taste. No references to their collection. Just the record itself.

Rules:
- Suggest a real, existing album available on Discogs as vinyl or cassette.
- GENRE DIVERSITY: The user's collection spans many genres. You MUST rotate across them.
  Look at the percentage breakdown — if Electronic is 40% it should get ~40% of suggestions,
  not 100%. Actively explore the user's other genres (Reggae, Jazz, Ambient, Rock, etc.).
- Do NOT always default to the numerically largest genre.
- Vary your suggestions: don't always pick the most obvious classics.
- Consider deep cuts, cult favourites, limited pressings, and international releases.
- The suggestion must NOT be one of the records already in their collection or wantlist.
- Take user ratings into account: push towards what they loved, away from what they disliked.
"""


def _ask_claude(taste_summary: str, already_suggested: list[str], rated: dict, recent_artists: list[str], recent_genres: list[str], owned_titles: set[tuple[str, str]] | None = None) -> dict:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    exclusion = ""
    if already_suggested:
        exclusion = "\n\nDo NOT suggest any of these already-sent records:\n" + "\n".join(
            f"- {s}" for s in already_suggested[-30:]
        )

    artist_exclusion = ""
    if recent_artists:
        artist_exclusion = "\n\nDo NOT suggest any of these artists — they were suggested recently:\n" + "\n".join(
            f"- {a}" for a in recent_artists
        )

    genre_context = ""
    if recent_genres:
        genre_context = (
            f"\n\nThe last {len(recent_genres)} suggestions were in these genres: "
            + ", ".join(recent_genres)
            + ".\nPlease suggest something from a DIFFERENT genre this time to ensure variety."
        )

    owned_exclusion = ""
    if owned_titles:
        owned_lines = sorted(f"- {artist} – {title}" for artist, title in owned_titles)
        owned_exclusion = "\n\nThe user already owns or has wishlisted ALL of these records — do NOT suggest any of them:\n" + "\n".join(owned_lines)

    rating_context = ""
    if rated["liked"]:
        rating_context += "\n\nThe user LOVED these suggestions (rated 4-5★) — lean into this taste:\n"
        rating_context += "\n".join(f"- {s}" for s in rated["liked"])
    if rated["disliked"]:
        rating_context += "\n\nThe user DISLIKED these suggestions (rated 1-2★) — avoid this direction:\n"
        rating_context += "\n".join(f"- {s}" for s in rated["disliked"])

    user_message = (
        f"Here is the collector's taste profile:\n\n{taste_summary}"
        f"{rating_context}{owned_exclusion}{exclusion}{artist_exclusion}{genre_context}\n\n"
        "Please suggest one vinyl or cassette record they would love. Respond only with the JSON."
    )

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=512,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = message.content[0].text.strip()
    raw = re.sub(r"^```[a-z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    return json.loads(raw)


def get_suggestion(max_attempts: int = 5) -> dict | None:
    """
    Build a taste profile, ask Claude for a vinyl/cassette suggestion,
    find it on Discogs, fetch rarity stats.
    Returns a dict or None if all attempts fail.
    """
    print("Loading Discogs collection and wantlist…")
    collection, wantlist = discogs.fetch_collection_and_wantlist()
    print(f"  {len(collection)} collection + {len(wantlist)} wantlist items")

    profile = discogs.build_taste_profile(collection, wantlist)
    taste_summary = discogs.format_profile_for_prompt(profile)
    owned_ids = discogs.get_owned_ids(collection, wantlist)
    owned_titles = discogs.get_owned_titles(collection, wantlist)

    history = database.get_history(limit=50)
    already_suggested = [f"{h['artist']} – {h['title']}" for h in history]
    rated = database.get_rated_history()
    recent_artists = database.get_recent_artists(limit=10)
    recent_genres = database.get_recent_genres(limit=5)

    for attempt in range(1, max_attempts + 1):
        print(f"Asking Claude for suggestion (attempt {attempt}/{max_attempts})…")
        try:
            suggestion = _ask_claude(taste_summary, already_suggested, rated, recent_artists, recent_genres, owned_titles)
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            print(f"  Claude response parse error: {e}")
            continue

        artist = suggestion.get("artist", "")
        title = suggestion.get("title", "")
        why = suggestion.get("info", "")
        year = suggestion.get("year")
        fmt = suggestion.get("format", "Vinyl")
        genre = suggestion.get("genre", "")

        print(f"  Claude suggests: {artist} – {title} ({year}) [{fmt}]")

        if artist in recent_artists:
            print(f"  Artist '{artist}' was suggested recently, retrying…")
            already_suggested.append(f"{artist} – {title}")
            continue

        # Reject if any version of this album is already owned
        if (discogs.normalize(artist), discogs.normalize(title)) in owned_titles:
            print(f"  User already owns a version of '{artist} – {title}', retrying…")
            already_suggested.append(f"{artist} – {title}")
            continue

        result = discogs.search_release(artist, title)
        if result is None:
            print("  Not found on Discogs as vinyl/cassette, retrying…")
            already_suggested.append(f"{artist} – {title}")
            continue

        if database.already_sent(result["id"]):
            print("  Already sent this one, retrying…")
            already_suggested.append(f"{artist} – {title}")
            continue

        if result["id"] in owned_ids:
            print("  Already in collection/wantlist, retrying…")
            already_suggested.append(f"{artist} – {title}")
            continue

        # Fetch rarity
        print(f"  Fetching community stats for release {result['id']}…")
        stats = discogs.get_community_stats(result["id"])
        rarity_bar, rarity_label = discogs.calculate_rarity(stats["have"], stats["want"])

        return {
            "artist": artist,
            "title": title,
            "year": year,
            "format": result.get("format", fmt),
            "genre": genre,
            "why": why,
            "discogs_url": result["url"],
            "discogs_id": result["id"],
            "have": stats["have"],
            "want": stats["want"],
            "rarity_bar": rarity_bar,
            "rarity_label": rarity_label,
        }

    print("Could not find a valid suggestion after all attempts.")
    return None
