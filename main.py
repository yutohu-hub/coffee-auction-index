"""COFFEE AUCTION INDEX — 実行入口。

  巡回 → 差分検知 → サイト生成。

  python main.py            # 本番巡回（COE公式ページを自動巡回 + seed取り込み）
  python main.py --seed-only  # ネット不要。seedデータだけでサイトを組む動作テスト
"""
from __future__ import annotations
import asyncio
import datetime
import sys
import time
from pathlib import Path

import json

import yaml

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))
from crawl import crawl_all  # noqa: E402
from store import open_db, apply_snapshot, export_for_site, scraped_country_years  # noqa: E402
from build_site import build  # noqa: E402
from model import lots_to_dicts  # noqa: E402
from fx import fetch_usd_jpy  # noqa: E402
import bop  # noqa: E402  (src/sources on path via crawl import)


def load_schedule() -> list:
    path = ROOT / "data" / "schedule.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("events", [])


# 生豆サンプルセット制があり、注文期限の概念が当てはまる競技系オークションのタイプ
SAMPLE_TYPES = {"COE", "BOP", "BoY", "CLoD", "CGLE"}


def add_sample_deadlines(events: list, lead_days: int) -> list:
    """今後のオークションごとに、生豆サンプル注文期限（目安）をカレンダーに追加する。

    実際の締切は各オークションが登録者向けに個別通知し公表されないため、
    オークション日から lead_days 日前を「目安」として算出する。
    schedule.json のイベントに sample_deadline を明記すればそちらを優先。
    単一生産者/イベント型オークション（サンプルセットが無い）には付けない。
    """
    today = datetime.datetime.utcnow().date()
    out = list(events)
    for e in events:
        if not e.get("date"):
            continue
        if e.get("type") not in SAMPLE_TYPES:
            continue
        try:
            ad = datetime.date.fromisoformat(e["date"])
        except ValueError:
            continue
        if ad < today:  # 過去オークションのサンプル期限は載せない
            continue
        explicit = e.get("sample_deadline")
        dl = datetime.date.fromisoformat(explicit) if explicit else ad - datetime.timedelta(days=lead_days)
        out.append({
            "date": dl.isoformat(),
            "auction": e["auction"], "type": e.get("type", ""),
            "country": e["country"], "year": e["year"], "kind": "sample",
            "note": (f"{e['country']} {e['auction']} の生豆サンプル注文期限"
                     + ("（公表値）" if explicit else f"（目安・オークション{lead_days}日前）")),
            "url": e.get("url", ""),
        })
    return out


def main() -> None:
    t0 = time.time()
    config = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))

    (ROOT / "data").mkdir(exist_ok=True)
    con = open_db(str(ROOT / "data" / "state.db"))

    if "--seed-only" in sys.argv:
        print("[seed-only] ネットに出ずキュレーションデータのみで生成")
        lots = bop.load_seed_lots()
        failed: list = []
        fx = {"jpy": 150.0, "asof": "", "live": False}
    else:
        skip = scraped_country_years(con, "COE")
        print(f"巡回開始（既取得 {len(skip)} 国×年はスキップ対象）")
        lots, failed = asyncio.run(crawl_all(config, skip))
        fx = fetch_usd_jpy()
        print(f"為替: 1 USD = {fx['jpy']} JPY（{fx['asof'] or 'fallback'}）")

    lot_dicts = lots_to_dicts(lots)
    print(f"取得: {len(lot_dicts)}ロット（失敗 {len(failed)}）")

    stats = apply_snapshot(con, lot_dicts)
    print(f"イベント: 新着{stats['new']} / 新記録{stats['record']}")

    site_data = export_for_site(con, int(config.get("settings", {}).get("event_days", 30)))
    site_data["fx"] = fx
    lead = int(config.get("settings", {}).get("sample_lead_days", 21))
    site_data["schedule"] = add_sample_deadlines(load_schedule(), lead)
    build(site_data, failed)

    print(f"完了（{round(time.time()-t0,1)}秒）")


if __name__ == "__main__":
    main()
