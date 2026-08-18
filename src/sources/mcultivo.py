"""mCultivo（CultivoCommerce / Framer製）で公開される結果ページのスクレイパー。

Dubai Coffee Auction・Colombia Land of Diversity など複数のプライベート/特殊
オークションが同一基盤でホストされており、結果はサーバー側レンダリング
（httpxで取得可能）。データは `data-framer-name="Row #N"` のネストdivに入る。

config の sources.mcultivo.auctions に「結果ページURL・名称・年・国・bid単位」を
1件ずつ列挙する。列はヘッダ名から動的にマッピングし、bid単価は USD/lb に正規化。
"""
from __future__ import annotations
import asyncio
import hashlib
import random
import re
import sys
from html import unescape
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model import (  # noqa: E402
    Lot, KG_PER_LB, parse_number, parse_score, guess_variety, guess_process, guess_country,
)

_ROW = re.compile(r'data-framer-name="Row #\d+"')
_PTEXT = re.compile(r'<p class="framer-text[^"]*"[^>]*>(.*?)</p>', re.S)
_TAG = re.compile(r"<[^>]+>")

COLMAP = {
    "farm": ["producer", "farm", "estate"],
    "lot": ["lot", "coffee", "name", "variety"],
    "score": ["score", "cupping", "points"],
    "bid": ["final bid", "winning bid", "high bid", "bid", "price", "usd"],
    "buyer": ["highest bidder", "bidder", "buyer", "winner", "winning"],
    "rank": ["rank", "place", "position", "#"],
    "country": ["country", "origin"],
}


def _texts(html: str) -> list:
    return [unescape(_TAG.sub("", x)).strip() for x in _PTEXT.findall(html)]


def _map_columns(header: list) -> dict:
    idx: dict = {}
    low = [h.lower() for h in header]
    for field, needles in COLMAP.items():
        for i, h in enumerate(low):
            if i in idx.values():
                continue
            if any(n in h for n in needles):
                idx[field] = i
                break
    return idx


def parse_results(html: str, a: dict) -> list:
    starts = [m.start() for m in _ROW.finditer(html)]
    if not starts:
        return []
    bounds = starts + [len(html)]
    rows = [_texts(html[bounds[i]:bounds[i + 1]]) for i in range(len(starts))]
    ncols = max((len(r) for r in rows), default=0)
    if ncols == 0:
        return []
    rows = [r[:ncols] for r in rows]                 # 末尾行に混ざるフッタ文言を切る
    header = _texts(html[:starts[0]])[-ncols:]
    cols = _map_columns(header)
    if "farm" not in cols and "bid" not in cols:
        return []

    bid_hdr = header[cols["bid"]].lower() if "bid" in cols else ""
    per_lb = "lb" in bid_hdr and "kg" not in bid_hdr   # 既定は USD/Kg

    def cell(r, f):
        return r[cols[f]].strip() if f in cols and cols[f] < len(r) else ""

    lots = []
    for r in rows:
        farm = cell(r, "farm")
        lot = cell(r, "lot")
        if not farm and not lot:
            continue
        if farm.lower() in ("producer/farm", "producer", "farm"):
            continue
        bid = parse_number(cell(r, "bid"))
        price_lb = bid if per_lb else (round(bid * KG_PER_LB, 2) if bid else None)
        blob = f"{farm} {lot}"
        country = a.get("country") or guess_country(blob)
        buyer = cell(r, "buyer")
        # 同一農園・同一ロット名で複数落札（例: Finca Sophia が2本）があるため、
        # 落札者と価格まで含めてキーを一意化する。
        raw = f"mCultivo|{a['name']}|{a['year']}|{farm}|{lot}|{buyer}|{bid}"
        key = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
        lots.append(Lot(
            key=key, source="mCultivo", auction=a["name"],
            country=country, year=int(a["year"]),
            category=lot or a["name"], rank=cell(r, "rank"),
            farm=farm, variety=guess_variety(blob), process=guess_process(blob),
            score=parse_score(cell(r, "score")),
            price_lb=price_lb, buyer=buyer,
            url=a["url"], note=lot if lot and lot != (a.get("country") or "") else "",
        ).finalize())
    return lots


async def _get(client, url, retries=3):
    for attempt in range(retries):
        try:
            resp = await client.get(url)
        except httpx.HTTPError:
            resp = None
        else:
            if resp.status_code in (200, 404):
                return resp
        if attempt < retries - 1:
            await asyncio.sleep(1.2 * (2 ** attempt) + random.uniform(0, 0.4))
    return resp


async def fetch(client, cfg, skip_keys=None) -> tuple:
    auctions = cfg.get("auctions", [])
    sem = asyncio.Semaphore(int(cfg.get("concurrency", 4)))
    lots, failed = [], []

    async def one(a):
        async with sem:
            resp = await _get(client, a["url"])
            if resp is None or resp.status_code != 200:
                failed.append(f"mCultivo:{a['name']}")
                return
            got = parse_results(resp.text, a)
            if got:
                lots.extend(got)
                print(f"  ✓ mCultivo {a['name']} {a['year']} — {len(got)}ロット")
            else:
                failed.append(f"mCultivo:{a['name']}(0)")
                print(f"  ✗ mCultivo {a['name']} — 0ロット（構造変更の可能性）")

    await asyncio.gather(*(one(a) for a in auctions))
    return lots, failed
