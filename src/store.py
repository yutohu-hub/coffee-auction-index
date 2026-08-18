"""落札ロットを SQLite に蓄積し、前回との差分イベントを検出する。

イベント種別:
  new_lot       … 新しく公表されたロット（初回投入時は抑制）
  record_price  … 全期間の最高ポンド単価を更新したロット
"""
from __future__ import annotations
import sqlite3
import time

FIELDS = [
    "key", "source", "auction", "country", "year", "category", "rank",
    "farm", "variety", "process", "score", "weight_lb", "price_lb",
    "total_value", "buyer", "auction_date", "url", "note",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS lots (
  key TEXT PRIMARY KEY,
  source TEXT, auction TEXT, country TEXT, year INTEGER, category TEXT, rank TEXT,
  farm TEXT, variety TEXT, process TEXT,
  score REAL, weight_lb REAL, price_lb REAL, total_value REAL,
  buyer TEXT, auction_date TEXT, url TEXT, note TEXT,
  first_seen REAL, last_seen REAL
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  key TEXT, type TEXT, ts REAL, detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts DESC);
CREATE INDEX IF NOT EXISTS idx_lots_price ON lots(price_lb DESC);
"""


def open_db(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def scraped_country_years(con: sqlite3.Connection, source: str = "COE") -> set:
    """COE で既取得済みの 'country-year'（kebab）集合。再取得スキップ用。"""
    out = set()
    for r in con.execute("SELECT DISTINCT country, year FROM lots WHERE source=?", (source,)):
        kebab = r["country"].strip().lower().replace(" ", "-")
        out.add(f"{kebab}-{r['year']}")
    return out


def apply_snapshot(con: sqlite3.Connection, lots: list[dict]) -> dict:
    now = time.time()
    first_run = con.execute("SELECT COUNT(*) AS n FROM lots").fetchone()["n"] == 0
    prev_max = con.execute("SELECT MAX(price_lb) AS m FROM lots").fetchone()["m"] or 0.0
    stats = {"new": 0, "record": 0, "total": len(lots)}
    running_max = prev_max

    for p in lots:
        row = con.execute("SELECT key, price_lb FROM lots WHERE key=?", (p["key"],)).fetchone()
        vals = [p.get(f) for f in FIELDS]
        if row is None:
            con.execute(
                f"INSERT INTO lots ({','.join(FIELDS)}, first_seen, last_seen) "
                f"VALUES ({','.join(['?'] * len(FIELDS))}, ?, ?)",
                vals + [now, now])
            price = p.get("price_lb") or 0
            if not first_run:
                con.execute("INSERT INTO events (key,type,ts,detail) VALUES (?,?,?,?)",
                            (p["key"], "new_lot", now, f"{p['auction']} {p['country']} {p['year']}"))
                stats["new"] += 1
                if price > running_max and price > 0:
                    con.execute("INSERT INTO events (key,type,ts,detail) VALUES (?,?,?,?)",
                                (p["key"], "record_price", now, f"${price:,.0f}/lb"))
                    stats["record"] += 1
            running_max = max(running_max, price)
        else:
            con.execute(
                f"UPDATE lots SET {','.join(f'{f}=?' for f in FIELDS)}, last_seen=? WHERE key=?",
                vals + [now, p["key"]])

    con.commit()
    return stats


def export_for_site(con: sqlite3.Connection, event_days: int = 30) -> dict:
    cutoff = time.time() - event_days * 86400
    lots = [dict(r) for r in con.execute(
        "SELECT * FROM lots ORDER BY (price_lb IS NULL), price_lb DESC").fetchall()]
    events = [dict(r) for r in con.execute(
        "SELECT e.*, l.auction, l.country, l.year, l.farm, l.variety, l.process, "
        "l.category, l.price_lb, l.score, l.url "
        "FROM events e JOIN lots l ON l.key = e.key "
        "WHERE e.ts > ? ORDER BY e.ts DESC LIMIT 200", (cutoff,)).fetchall()]
    return {"lots": lots, "events": events}
