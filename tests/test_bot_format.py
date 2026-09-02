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
