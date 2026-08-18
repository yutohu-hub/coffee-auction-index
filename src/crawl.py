"""全オークション源を横断して巡回し、正規化済み Lot を集める司令塔。"""
from __future__ import annotations
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "sources"))
from model import Lot  # noqa: E402
import coe  # noqa: E402
import bop  # noqa: E402
import mcultivo  # noqa: E402

UA = "AuctionTrackerBot/1.0 (personal hobby project; contact via repo)"


async def crawl_all(config: dict, skip_keys: set) -> tuple[list[Lot], list[str]]:
    settings = config.get("settings", {})
    sources = config.get("sources", {})
    timeout = httpx.Timeout(float(settings.get("timeout_sec", 25)))
    lots: list[Lot] = []
    failed: list[str] = []

    # キュレーション（seed）は常に取り込む
    seed_lots = bop.load_seed_lots()
    lots.extend(seed_lots)
    print(f"  ✓ seed — {len(seed_lots)}ロット")

    async with httpx.AsyncClient(headers={"User-Agent": UA}, timeout=timeout,
                                 follow_redirects=True) as client:
        coe_cfg = sources.get("coe", {})
        if coe_cfg.get("enabled", True):
            try:
                coe_lots, coe_failed = await coe.fetch(client, coe_cfg, skip_keys)
                lots.extend(coe_lots)
                failed.extend(coe_failed)
                print(f"  ✓ COE 合計 — {len(coe_lots)}ロット")
            except Exception as e:  # 1源の失敗で全体を止めない
                failed.append(f"COE:{type(e).__name__}")
                print(f"  ✗ COE — {e}")

        mc_cfg = sources.get("mcultivo", {})
        if mc_cfg.get("enabled", True):
            try:
                mc_lots, mc_failed = await mcultivo.fetch(client, mc_cfg)
                lots.extend(mc_lots)
                failed.extend(mc_failed)
                print(f"  ✓ mCultivo 合計 — {len(mc_lots)}ロット")
            except Exception as e:
                failed.append(f"mCultivo:{type(e).__name__}")
                print(f"  ✗ mCultivo — {e}")

    return lots, failed
