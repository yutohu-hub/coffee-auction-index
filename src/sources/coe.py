"""Cup of Excellence（COE）のオークション結果スクレイパー。

allianceforcoffeeexcellence.org / cupofexcellence.org の結果インデックスから
「国-年」ページを発見し、各ページの HTML テーブルを Lot に正規化する。
結果は公表後は基本不変なので、既取得の過去年はスキップして負荷を抑える。
"""
from __future__ import annotations
import asyncio
import random
import re
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model import Lot, parse_money, parse_score, primary_variety  # noqa: E402
from htmltable import extract_tables  # noqa: E402

AUCTION = "Cup of Excellence"
INDEX_URLS = [
    "https://allianceforcoffeeexcellence.org/competition-auction-results/",
    "https://cupofexcellence.org/competition-auction-results/",
]
BASES = ["allianceforcoffeeexcellence.org", "cupofexcellence.org"]

# COE 開催国（スラッグ先頭一致で国名を切り出す。長い名前を先に）
COUNTRIES = [
    "costa-rica", "el-salvador", "brazil", "bolivia", "burundi", "colombia",
    "ecuador", "ethiopia", "guatemala", "honduras", "indonesia", "mexico",
    "nicaragua", "rwanda", "peru", "panama", "tanzania", "uganda", "kenya",
]

_LINK = re.compile(r'href=["\']([^"\']+?/([a-z][a-z0-9-]*?)-((?:19|20)\d{2})/)["\']', re.I)

# ACE が同じ表形式でホストする「国以外」の特別オークション。
# 国スラッグではないので通常のディスカバリでは拾わず、年ごとに直接叩く。
SPECIAL = [
    {"slug": "best-of-yemen", "auction": "Best of Yemen", "country": "Yemen", "source": "BoY"},
]
SPECIAL_BASE = "https://allianceforcoffeeexcellence.org/{slug}-{year}/"

# ヘッダ列 → フィールド の対応（部分一致）
COLMAP = [
    ("rank", ["rank", "place", "no."]),
    ("farm", ["farm", "producer", "coffee name", "coffee", "lot name"]),
    ("farmer", ["farmer", "grower"]),
    ("score", ["score", "cupping"]),
    ("process", ["process", "processing"]),
    ("variety", ["variety", "varietal", "cultivar"]),
    ("region", ["region", "area", "department"]),
    ("weight", ["weight", "lbs", "pounds", "quantity", "qty"]),
    ("bid", ["high bid", "winning bid", "bid", "price/lb", "$/lb", "price per", "price"]),
    ("total", ["total value", "total", "value", "amount"]),
    ("buyer", ["business name", "buyer", "importer", "winning bidder", "company", "winner"]),
]


async def _get(client: httpx.AsyncClient, url: str, retries: int = 3):
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


def _country_of(slug: str) -> tuple[str, str]:
    """スラッグから (国名, 地域/種別) を切り出す。"""
    for c in COUNTRIES:
        if slug == c or slug.startswith(c + "-"):
            region = slug[len(c):].strip("-").replace("-", " ").title()
            return c.replace("-", " ").title(), region
    return slug.replace("-", " ").title(), ""


async def _discover(client: httpx.AsyncClient, min_year: int) -> dict:
    """インデックスから {(slug, year): url} を集める。"""
    found: dict = {}
    for idx in INDEX_URLS:
        resp = await _get(client, idx)
        if resp is None or resp.status_code != 200:
            continue
        for m in _LINK.finditer(resp.text):
            url, slug, year = m.group(1), m.group(2).lower(), int(m.group(3))
            if year < min_year:
                continue
            if not any(slug == c or slug.startswith(c + "-") for c in COUNTRIES):
                continue
            found.setdefault((slug, year), url)
    return found


def _match_columns(header: list[str]) -> dict:
    idx: dict = {}
    lowered = [h.lower() for h in header]
    for field, needles in COLMAP:
        for i, h in enumerate(lowered):
            if i in idx.values():
                continue
            if any(n in h for n in needles):
                idx[field] = i
                break
    return idx


def _looks_like_header(cells: list[str]) -> bool:
    joined = " ".join(cells).lower()
    return ("rank" in joined or "farm" in joined or "producer" in joined) and \
           ("score" in joined or "bid" in joined or "price" in joined)


def _clean_category(heading: str, region: str) -> str:
    cat = heading or region
    cat = re.sub(r"\s*(auction\s+)?results?\s*$", "", cat, flags=re.I).strip()
    return cat


_SUMMARY = re.compile(r"\b(total|totals|average|averages|avg|mean|sum|subtotal)\b", re.I)


def _iter_rows(rows: list, cols: dict):
    """ヘッダ以降のデータ行を返す。合計/平均などの集計行・空行は除外。"""
    maxidx = max(cols.values(), default=0)
    for r in rows[1:]:
        if len(r) <= maxidx:
            continue
        rank = r[cols["rank"]] if "rank" in cols and cols["rank"] < len(r) else ""
        farm = r[cols["farm"]] if "farm" in cols and cols["farm"] < len(r) else ""
        joined = " ".join(r[:3])
        if (not farm and not rank) or rank.lower() == "rank" or farm.lower() in ("farm", "producer"):
            continue
        if _SUMMARY.search(rank) or _SUMMARY.search(farm) or _SUMMARY.search(joined[:20]):
            continue
        if not farm:  # COE のロット行には必ず農園名がある
            continue
        yield r


def _parse_page(html: str, country: str, region: str, year: int, url: str,
                auction: str = AUCTION, source: str = "COE") -> list[Lot]:
    tables = extract_tables(html)
    # 競技表（品種/精製/地域つき）を (category, rank, farm) で索引化して後で価格表に合流
    meta: dict = {}
    auction_lots: list[Lot] = []
    comp_lots: list[Lot] = []

    for tbl in tables:
        rows = tbl.rows
        if len(rows) < 2:
            continue
        hi = 0 if _looks_like_header(rows[0]) else \
            next((i for i, r in enumerate(rows[:3]) if _looks_like_header(r)), -1)
        if hi < 0:
            continue
        # 手数料内訳（Organizing Country Commissions）は正規表と重複するので除外
        head_blob = (tbl.heading + " " + " ".join(rows[hi])).lower()
        if "commission" in head_blob or "comission" in head_blob:
            continue
        cols = _match_columns(rows[hi])
        if "rank" not in cols and "farm" not in cols:
            continue
        category = _clean_category(tbl.heading, region)
        is_auction = "bid" in cols or "total" in cols or "buyer" in cols
        body = rows[hi:]  # cols は body[0]=ヘッダ基準

        def cell(r, f):
            return r[cols[f]].strip() if f in cols and cols[f] < len(r) else ""

        for r in _iter_rows(body, cols):
            rank, farm = cell(r, "rank"), cell(r, "farm")
            mkey = (category.lower(), rank.lower(), farm.lower())
            variety_raw = cell(r, "variety")
            if is_auction:
                lot = Lot(
                    key="", source=source, auction=auction,
                    country=country, year=year, category=category,
                    rank=rank, farm=farm,
                    score=parse_score(cell(r, "score")),
                    weight_lb=parse_money(cell(r, "weight")),
                    price_lb=parse_money(cell(r, "bid")),
                    total_value=parse_money(cell(r, "total")),
                    buyer=cell(r, "buyer"), url=url,
                )
                auction_lots.append((mkey, lot))
            else:
                m = {
                    "variety": primary_variety(variety_raw),
                    "variety_raw": variety_raw,
                    "process": cell(r, "process"),
                    "region": cell(r, "region"),
                    "farmer": cell(r, "farmer"),
                    "score": parse_score(cell(r, "score")),
                }
                meta[mkey] = m
                lot = Lot(
                    key="", source=source, auction=auction,
                    country=country, year=year, category=category,
                    rank=rank, farm=farm,
                    variety=m["variety"], process=m["process"],
                    score=m["score"], url=url,
                    note=variety_raw if variety_raw and m["variety"] != variety_raw else "",
                )
                comp_lots.append((mkey, lot))

    lots: list[Lot] = []
    if auction_lots:
        for mkey, lot in auction_lots:
            m = meta.get(mkey)
            if m:
                lot.variety = lot.variety or m["variety"]
                lot.process = lot.process or m["process"]
                if not lot.note and m.get("variety_raw") and m["variety"] != m["variety_raw"]:
                    lot.note = m["variety_raw"]
                if lot.score is None:
                    lot.score = m["score"]
                if m.get("region"):
                    lot.note = (lot.note + " · " if lot.note else "") + m["region"]
            lot.finalize()
            if lot.price_lb is None and lot.score is None:
                continue
            lots.append(lot)
    else:
        # 価格表が無いページは競技結果のみ（スコアで記録・ランキングに使える）
        for mkey, lot in comp_lots:
            lot.finalize()
            if lot.score is not None:
                lots.append(lot)
    return lots


async def fetch(client: httpx.AsyncClient, cfg: dict, skip_keys: set) -> tuple[list[Lot], list[str]]:
    min_year = int(cfg.get("min_year", 2018))
    max_pages = int(cfg.get("max_pages", 60))
    sem = asyncio.Semaphore(int(cfg.get("concurrency", 5)))
    pages = await _discover(client, min_year)
    if not pages:
        return [], ["COE:index"]

    # 既取得の過去年はスキップ（今年ぶんは再取得＝追い落札の反映）
    import datetime
    this_year = datetime.datetime.utcnow().year
    targets = [(k, u) for k, u in pages.items()
               if f"{k[0]}-{k[1]}" not in skip_keys or k[1] >= this_year]
    # 新しい年から優先取得（1回の巡回上限で全国の直近年をまず押さえる）
    targets.sort(key=lambda t: (-t[0][1], t[0][0]))
    targets = targets[:max_pages]

    lots: list[Lot] = []
    failed: list[str] = []

    async def one(slug: str, year: int, url: str):
        async with sem:
            resp = await _get(client, url)
            if resp is None or resp.status_code != 200:
                failed.append(f"COE:{slug}-{year}")
                return
            country, region = _country_of(slug)
            got = _parse_page(resp.text, country, region, year, url)
            if got:
                lots.extend(got)
            print(f"  ✓ COE {country} {year} — {len(got)}ロット")

    async def one_special(sp: dict, year: int):
        skey = f"{sp['slug']}-{year}"
        if skey in skip_keys and year < this_year:
            return
        url = SPECIAL_BASE.format(slug=sp["slug"], year=year)
        async with sem:
            resp = await _get(client, url)
            if resp is None or resp.status_code != 200:
                return  # 未開催年は404 → 静かにスキップ
            got = _parse_page(resp.text, sp["country"], "", year, url,
                              auction=sp["auction"], source=sp["source"])
            if got:
                lots.extend(got)
                print(f"  ✓ {sp['auction']} {year} — {len(got)}ロット")

    special_tasks = [one_special(sp, y)
                     for sp in SPECIAL
                     for y in range(max(min_year, 2020), this_year + 1)]
    await asyncio.gather(*[one(k[0], k[1], u) for k, u in targets], *special_tasks)
    return lots, failed
