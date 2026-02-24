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
  "why": "Two or three sentences explaining why this fits their taste."
}

The "format" field must be either "Vinyl" or "Cassette".

Rules:
- Suggest a real, existing album available on Discogs as vinyl or cassette.
- Vary your suggestions: don't always pick the most obvious classics.
- Consider deep cuts, cult favourites, limited pressings, and international releases.
- The suggestion must NOT be one of the records already in their collection or wantlist.
- Take user ratings into account: push towards what they loved, away from what they disliked.
"""


def _ask_claude(taste_summary: str, already_suggested: list[str], rated: dict) -> dict:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    exclusion = ""
    if already_suggested:
        exclusion = "\n\nDo NOT suggest any of these already-sent records:\n" + "\n".join(
            f"- {s}" for s in already_suggested[-30:]
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
        f"{rating_context}{exclusion}\n\n"
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
    print("Fetching Discogs collection…")
    collection = discogs.fetch_collection()
    print(f"  {len(collection)} records in collection")

    print("Fetching Discogs wantlist…")
    wantlist = discogs.fetch_wantlist()
    print(f"  {len(wantlist)} records in wantlist")

    profile = discogs.build_taste_profile(collection, wantlist)
    taste_summary = discogs.format_profile_for_prompt(profile)
    owned_ids = discogs.get_owned_ids(collection, wantlist)

    history = database.get_history(limit=50)
    already_suggested = [f"{h['artist']} – {h['title']}" for h in history]
    rated = database.get_rated_history()

    for attempt in range(1, max_attempts + 1):
        print(f"Asking Claude for suggestion (attempt {attempt}/{max_attempts})…")
        try:
            suggestion = _ask_claude(taste_summary, already_suggested, rated)
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            print(f"  Claude response parse error: {e}")
            continue

        artist = suggestion.get("artist", "")
        title = suggestion.get("title", "")
        why = suggestion.get("why", "")
        year = suggestion.get("year")
        fmt = suggestion.get("format", "Vinyl")

        print(f"  Claude suggests: {artist} – {title} ({year}) [{fmt}]")

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
