"""Best of Panama など、独自オークション基盤で構造がまちまちな源の取り込み口。

現状は data/seed.json のキュレーション済みデータ（報道・公式発表ベース）を Lot 化する。
将来ここに実スクレイパーを追加できるよう、他の源と同じ fetch() 形にしてある。
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model import Lot  # noqa: E402

SEED_PATH = Path(__file__).resolve().parents[2] / "data" / "seed.json"


def load_seed_lots() -> list[Lot]:
    if not SEED_PATH.exists():
        return []
    data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    lots: list[Lot] = []
    for d in data.get("lots", []):
        lots.append(Lot(
            key="", source=d.get("source", "seed"),
            auction=d["auction"], country=d["country"], year=int(d["year"]),
            category=d.get("category", ""), rank=str(d.get("rank", "")),
            farm=d.get("farm", ""), variety=d.get("variety", ""),
            process=d.get("process", ""),
            score=d.get("score"), weight_lb=d.get("weight_lb"),
            price_lb=d.get("price_lb"), total_value=d.get("total_value"),
            buyer=d.get("buyer", ""), auction_date=d.get("auction_date", ""),
            url=d.get("url", ""), note=d.get("note", ""),
        ).finalize())
    return lots
