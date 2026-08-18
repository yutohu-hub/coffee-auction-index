"""為替レート（USD→JPY）の取得。取得失敗時はフォールバック値を返す。"""
from __future__ import annotations

import httpx

# ECBデータの無料API（キー不要）。301で .dev に移るため最新ホストを直接指定。
FX_URL = "https://api.frankfurter.dev/v1/latest?from=USD&to=JPY"
FALLBACK_JPY = 150.0


def fetch_usd_jpy() -> dict:
    """{'jpy': float, 'asof': 'YYYY-MM-DD', 'live': bool} を返す。"""
    try:
        r = httpx.get(FX_URL, timeout=15, follow_redirects=True)
        r.raise_for_status()
        data = r.json()
        rate = float(data["rates"]["JPY"])
        return {"jpy": round(rate, 2), "asof": data.get("date", ""), "live": True}
    except Exception as e:
        print(f"  ! 為替取得に失敗、フォールバック {FALLBACK_JPY} を使用（{type(e).__name__}）")
        return {"jpy": FALLBACK_JPY, "asof": "", "live": False}
