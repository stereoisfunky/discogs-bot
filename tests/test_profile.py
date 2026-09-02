import discogs


def test_profile_has_long_tail_sample_excluding_head(sample_collection, sample_wantlist):
    p = discogs.build_taste_profile(sample_collection, sample_wantlist, seed=1)
    head_styles = {s for s, _ in p["top_styles"][:12]}
    assert p["long_tail_styles"], "expected a non-empty long-tail sample"
    assert all(s not in head_styles for s in p["long_tail_styles"])
    # Roots Reggae / Spiritual Jazz etc. are 1-copy styles -> long tail
    assert "Roots Reggae" in p["long_tail_styles"] or "Spiritual Jazz" in p["long_tail_styles"]


def test_long_tail_sample_rotates_with_seed(sample_collection, sample_wantlist):
    a = discogs.build_taste_profile(sample_collection, sample_wantlist, seed=1)["long_tail_styles"]
    b = discogs.build_taste_profile(sample_collection, sample_wantlist, seed=1)["long_tail_styles"]
    c = discogs.build_taste_profile(sample_collection, sample_wantlist, seed=999)["long_tail_styles"]
    assert a == b, "same seed must be deterministic"
    assert a != c or len(a) <= 1, "different seed should usually reshuffle"


def test_genre_decades_crosstab(sample_collection, sample_wantlist):
    p = discogs.build_taste_profile(sample_collection, sample_wantlist, seed=1)
    assert "Electronic" in p["genre_decades"]
    total = sum(n for _, n in p["genre_decades"]["Electronic"])
    assert total == 36  # 35 owned + 1 wantlist (Electronic)


def test_format_profile_mentions_long_tail_and_crosstab(sample_collection, sample_wantlist):
    p = discogs.build_taste_profile(sample_collection, sample_wantlist, seed=1)
    text = discogs.format_profile_for_prompt(p)
    assert "Less-explored corners" in text
    assert "by decade" in text
