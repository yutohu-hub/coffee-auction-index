"""DB由来のデータから docs/ に静的サイト（単一HTML）を生成する。"""
from __future__ import annotations
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
TEMPLATE = Path(__file__).resolve().parent / "template.html"

KG_PER_LB = 0.45359237


def _sorted_unique(values):
    return sorted({v for v in values if v})


def _facet(values, min_count=1):
    """ドロップダウン用。出現回数の少ない自由記述の外れ値を除いて整理する。"""
    from collections import Counter
    c = Counter(v for v in values if v)
    return sorted([v for v, n in c.items() if n >= min_count])


def _record_by(lots, field):
    cand = [l for l in lots if l.get(field) is not None]
    return max(cand, key=lambda l: l[field]) if cand else None


def build(data: dict, failed: list) -> None:
    lots = data["lots"]
    events = data["events"]
    priced = [l for l in lots if l.get("price_lb")]

    years = _sorted_unique(l["year"] for l in lots)
    stats = {
        "lots": len(lots),
        "priced": len(priced),
        "countries": len(_sorted_unique(l["country"] for l in lots)),
        "auctions": len(_sorted_unique(l["auction"] for l in lots)),
        "years": years,
        "current_year": years[-1] if years else None,
        "top_price": max((l["price_lb"] for l in priced), default=0),
        "top_score": max((l["score"] for l in lots if l.get("score")), default=0),
        "total_value": round(sum(l["total_value"] or 0 for l in lots)),
    }
    records = {
        "price": _record_by(lots, "price_lb"),
        "score": _record_by(lots, "score"),
        "total": _record_by(lots, "total_value"),
    }
    facets = {
        "auctions": _sorted_unique(l["auction"] for l in lots),
        "countries": _sorted_unique(l["country"] for l in lots),
        "years": [str(y) for y in stats["years"]],
        "varieties": _facet((l["variety"] for l in lots), min_count=4),
        "processes": _facet((l["process"] for l in lots), min_count=5),
    }

    payload = {
        "updated": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "today": time.strftime("%Y-%m-%d", time.gmtime()),
        "stats": stats,
        "records": records,
        "facets": facets,
        "lots": lots,
        "events": events,
        "failed": failed,
        "fx": data.get("fx", {"jpy": 150.0, "asof": "", "live": False}),
        "schedule": data.get("schedule", []),
    }

    html = TEMPLATE.read_text(encoding="utf-8")
    html = html.replace("/*__DATA__*/null", json.dumps(payload, ensure_ascii=False))
    DOCS.mkdir(exist_ok=True)
    (DOCS / "index.html").write_text(html, encoding="utf-8")
    (DOCS / ".nojekyll").write_text("", encoding="utf-8")
    # 静的な付随ページ（購買ガイド・落札履歴）をそのまま配置
    for name in ("guide.html", "history.html"):
        src = TEMPLATE.parent / name
        if src.exists():
            (DOCS / name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    # ローカルプレビューのミラー（このマシンのプレビューは /Users 配下を読めず /tmp のみ
    # 読めるため）。ディレクトリが存在する時だけ更新。CI では存在しないので何もしない。
    from pathlib import Path as _P
    mirror = _P("/tmp/auction-site-docs")
    if mirror.is_dir():
        for name in ("index.html", "guide.html", "history.html", "data.json"):
            try:
                (mirror / name).write_bytes((DOCS / name).read_bytes())
            except OSError:
                pass
    (DOCS / "data.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"サイト生成: {len(lots)}ロット → {DOCS/'index.html'}")
