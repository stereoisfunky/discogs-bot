import sqlite3
from datetime import datetime
from config import DB_PATH


def _connect():
    return sqlite3.connect(DB_PATH)


def init_db():
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS suggestions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                discogs_id  TEXT NOT NULL,
                artist      TEXT,
                title       TEXT,
                format      TEXT,
                rating      INTEGER,
                sent_at     TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_discogs_id
            ON suggestions (discogs_id)
        """)
        # Migrate: add columns if upgrading from older schema
        for col, definition in [("format", "TEXT"), ("rating", "INTEGER"), ("genre", "TEXT")]:
            try:
                conn.execute(f"ALTER TABLE suggestions ADD COLUMN {col} {definition}")
            except Exception:
                pass
        conn.commit()


def already_sent(discogs_id: str) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM suggestions WHERE discogs_id = ?", (discogs_id,)
        ).fetchone()
    return row is not None


def record_suggestion(discogs_id: str, artist: str, title: str, fmt: str = "", genre: str = ""):
    with _connect() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO suggestions
               (discogs_id, artist, title, format, genre, sent_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (discogs_id, artist, title, fmt, genre, datetime.utcnow().isoformat()),
        )
        conn.commit()


def update_rating(discogs_id: str, rating: int):
    with _connect() as conn:
        conn.execute(
            "UPDATE suggestions SET rating = ? WHERE discogs_id = ?",
            (rating, discogs_id),
        )
        conn.commit()


def get_history(limit: int = 20) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """SELECT artist, title, discogs_id, format, rating, sent_at
               FROM suggestions ORDER BY sent_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [
        {"artist": r[0], "title": r[1], "discogs_id": r[2],
         "format": r[3], "rating": r[4], "sent_at": r[5]}
        for r in rows
    ]


def suggestion_sent_today() -> bool:
    """Return True if a suggestion was already recorded today (UTC date)."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM suggestions WHERE sent_at LIKE ? LIMIT 1",
            (f"{today}%",),
        ).fetchone()
    return row is not None


def get_recent_genres(limit: int = 5) -> list[str]:
    """Return genres from the last N suggestions (for rotation)."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT genre FROM suggestions WHERE genre IS NOT NULL AND genre != '' ORDER BY sent_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [r[0] for r in rows]


def get_recent_artists(limit: int = 10) -> list[str]:
    """Return artists from the last N suggestions (for deduplication)."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT artist FROM suggestions ORDER BY sent_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [r[0] for r in rows if r[0]]


def get_rated_history() -> dict[str, list[str]]:
    """Return liked (4-5★) and disliked (1-2★) suggestions for Claude context."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT artist, title, rating FROM suggestions WHERE rating IS NOT NULL"
        ).fetchall()
    liked, disliked = [], []
    for artist, title, rating in rows:
        entry = f"{artist} – {title}"
        if rating >= 4:
            liked.append(entry)
        elif rating <= 2:
            disliked.append(entry)
    return {"liked": liked, "disliked": disliked}
