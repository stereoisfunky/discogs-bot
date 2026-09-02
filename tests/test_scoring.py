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

    _RealRandom = random.Random
    monkeypatch.setattr(recommender._random, "Random", lambda *a, **k: _RealRandom(0))

    out = recommender.get_suggestion()
    assert out is not None
    assert out["artist"] in ("Sun Ra", "Pole")
    assert out["lowest_price"] == 20.0
    assert "mode" in out
    assert out["discogs_url"] in ("u1", "u2")
