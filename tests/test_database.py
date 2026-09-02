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
