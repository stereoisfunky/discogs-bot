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


def _ask_claude(taste_summary: str, already_suggested: list[str], rated: dict, recent_artists: list[str], recent_genres: list[str]) -> dict:
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

    rating_context = ""
    if rated["liked"]:
        rating_context += "\n\nThe user LOVED these suggestions (rated 4-5★) — lean into this taste:\n"
        rating_context += "\n".join(f"- {s}" for s in rated["liked"])
    if rated["disliked"]:
        rating_context += "\n\nThe user DISLIKED these suggestions (rated 1-2★) — avoid this direction:\n"
        rating_context += "\n".join(f"- {s}" for s in rated["disliked"])

    user_message = (
        f"Here is the collector's taste profile:\n\n{taste_summary}"
        f"{rating_context}{exclusion}{artist_exclusion}{genre_context}\n\n"
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
            suggestion = _ask_claude(taste_summary, already_suggested, rated, recent_artists, recent_genres)
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
