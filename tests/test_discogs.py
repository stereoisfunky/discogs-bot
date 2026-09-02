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


def _fake_get_factory(release_data=None, stats_data=None, error=False):
    def fake_get(url, params=None):
        if error:
            raise RuntimeError("network")
        if "/marketplace/stats/" in url:
            return stats_data if stats_data is not None else {}
        return release_data if release_data is not None else {}
    return fake_get


def test_get_release_info_extracts_fields(monkeypatch):
    monkeypatch.setattr(discogs, "_get", _fake_get_factory(
        release_data={"community": {"have": 3100, "want": 1800}},
        stats_data={"num_for_sale": 42, "lowest_price": {"value": 17.5, "currency": "EUR"}},
    ))
    info = discogs.get_release_info("123")
    assert info == {"have": 3100, "want": 1800, "lowest_price": 17.5, "num_for_sale": 42}


def test_get_release_info_handles_missing_price(monkeypatch):
    monkeypatch.setattr(discogs, "_get", _fake_get_factory(
        release_data={"community": {}},
        stats_data={"num_for_sale": 0, "lowest_price": None},
    ))
    info = discogs.get_release_info("123")
    assert info == {"have": 0, "want": 0, "lowest_price": None, "num_for_sale": 0}


def test_get_release_info_swallows_errors(monkeypatch):
    monkeypatch.setattr(discogs, "_get", _fake_get_factory(error=True))
    assert discogs.get_release_info("123") == {
        "have": 0, "want": 0, "lowest_price": None, "num_for_sale": 0}
