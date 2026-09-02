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
