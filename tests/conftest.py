"""Shared test fixtures. No network calls anywhere in the suite."""
import sqlite3
import pytest

import database


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Point database.py at a fresh empty SQLite file and init the schema."""
    db_file = tmp_path / "test_suggestions.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_file))
    database.init_db()
    return str(db_file)


@pytest.fixture
def sample_collection():
    """A small collection with a clear head/long-tail split.

    Techno + Ambient dominate; the rest are 1-2 copies each (the long tail).
    """
    def rec(rid, artist, title, year, genres, styles):
        return {
            "id": str(rid), "title": title, "artists": [artist],
            "genres": genres, "styles": styles, "labels": ["Some Label"],
            "year": year,
        }
    items = []
    for i in range(20):
        items.append(rec(100 + i, f"Techno Artist {i}", f"Techno LP {i}", 1994 + (i % 5),
                         ["Electronic"], ["Techno"]))
    for i in range(15):
        items.append(rec(200 + i, f"Ambient Artist {i}", f"Ambient LP {i}", 1980 + (i % 10),
                         ["Electronic"], ["Ambient"]))
    # long tail: one record each
    items.append(rec(300, "The Congos", "Heart Of The Congos", 1977, ["Reggae"], ["Roots Reggae"]))
    items.append(rec(301, "Alice Coltrane", "Journey In Satchidananda", 1971, ["Jazz"], ["Spiritual Jazz"]))
    items.append(rec(302, "Aksak Maboul", "Onze Danses", 1977, ["Rock"], ["Avantgarde"]))
    items.append(rec(303, "Pauline Oliveros", "Deep Listening", 1989, ["Classical"], ["Modern"]))
    return items


@pytest.fixture
def sample_wantlist():
    return [{
        "id": "900", "title": "Wanted LP", "artists": ["Wanted Artist"],
        "genres": ["Electronic"], "styles": ["Deep House"], "labels": ["X"], "year": 2001,
    }]
