"""オークション落札ロットの正規化モデルと補助関数。

各オークション源（COE / BOP / …）は、この Lot 形式に落とし込んで返す。
価格はすべて USD/lb（ポンド単価）に正規化しておくと横断比較ができる。
"""
from __future__ import annotations
import hashlib
import re
from dataclasses import dataclass, asdict, field

KG_PER_LB = 0.45359237

VARIETIES = [
    "Geisha", "Gesha", "Sudan Rume", "Sidra", "Bourbon", "Caturra", "Catuai",
    "Pacamara", "Typica", "SL28", "SL34", "Wush Wush", "Laurina", "Maragogipe",
    "Java", "Mokka", "Pink Bourbon", "Ethiosar", "Chiroso", "Tabi", "Eugenioides",
    "Yemenia", "Udaini", "Jaadi", "Dawairi",
]
PROCESS_WORDS = [
    ("anaerobic", "Anaerobic"),
    ("carbonic", "Carbonic"),
    ("thermal", "Thermal Shock"),
    ("lactic", "Lactic"),
    ("honey", "Honey"),
    ("pulped natural", "Honey"),
    ("natural", "Natural"),
    ("dry", "Natural"),
    ("washed", "Washed"),
    ("wet", "Washed"),
]


@dataclass
class Lot:
    key: str            # 安定した一意キー（source|auction|country|year|rank|farm のhash）
    source: str         # データ源: "COE", "BOP", "seed" など
    auction: str        # 表示名: "Cup of Excellence", "Best of Panama"
    country: str        # 生産国
    year: int
    category: str = ""  # 例: "Exotic Washed", "Geisha Washed"
    rank: str = ""      # "1A", "1B", "2" など（文字列で保持）
    farm: str = ""      # 農園 / 生産者
    variety: str = ""   # 品種（Geisha など）
    process: str = ""   # 精製（Washed / Natural / Honey …）
    score: float | None = None       # カッピングスコア
    weight_lb: float | None = None    # ロット重量（lb）
    price_lb: float | None = None     # 落札ポンド単価（USD/lb）
    total_value: float | None = None  # 落札総額（USD）
    buyer: str = ""     # 落札者 / Business Name
    auction_date: str = ""            # ISO日付（分かれば）
    url: str = ""       # 出典ページ
    note: str = ""

    def finalize(self) -> "Lot":
        """派生値の補完・値域チェック・キー生成。"""
        # 値域チェック（列ずれや合計行の混入で生じる異常値を無効化）
        if self.score is not None and not (55.0 <= self.score <= 100.0):
            self.score = None
        if self.price_lb is not None and not (0 < self.price_lb <= 60000):
            self.price_lb = None
        if self.weight_lb is not None and self.weight_lb <= 0:
            self.weight_lb = None
        blob = " ".join([self.farm, self.category, self.note, self.variety, self.process])
        if not self.variety:
            self.variety = guess_variety(blob)
        if not self.process:
            self.process = guess_process(blob + " " + self.category)
        # 単価↔総額↔重量 の相互補完
        if self.price_lb is None and self.total_value and self.weight_lb:
            self.price_lb = round(self.total_value / self.weight_lb, 2)
        if self.total_value is None and self.price_lb and self.weight_lb:
            self.total_value = round(self.price_lb * self.weight_lb, 2)
        if not self.key:
            raw = f"{self.source}|{self.auction}|{self.country}|{self.year}|{self.category}|{self.rank}|{self.farm}"
            self.key = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
        return self


def guess_variety(text: str) -> str:
    low = text.lower()
    for v in VARIETIES:
        if v.lower() in low:
            return "Geisha" if v.lower() == "gesha" else v
    return ""


def guess_process(text: str) -> str:
    low = text.lower()
    for needle, label in PROCESS_WORDS:
        if needle in low:
            return label
    return ""


# 原産国推定（多国籍オークションで、農園・ロット名から拾えるものだけ拾う）
ORIGIN_WORDS = [
    "Ethiopia", "Kenya", "Colombia", "Panama", "Peru", "Brazil", "Bolivia",
    "Rwanda", "Burundi", "Guatemala", "Costa Rica", "El Salvador", "Honduras",
    "Ecuador", "Mexico", "Nicaragua", "Yemen", "India", "Indonesia", "Uganda",
    "Tanzania", "Hawaii", "China", "Taiwan", "Thailand", "Myanmar",
]
# 著名農園 → 原産国（報道・公式で確認できるもの）
FARM_ORIGIN = {
    "gesha village": "Ethiopia", "finca sophia": "Panama", "hacienda la esmeralda": "Panama",
    "finca deborah": "Panama", "kona": "USA (Hawaii)", "la llama": "Bolivia",
    "los rodriguez": "Bolivia", "daterra": "Brazil", "el injerto": "Guatemala",
    "inmaculada": "Colombia", "granja la esperanza": "Colombia", "las nubes": "Panama",
    "ninety plus": "Ethiopia", "alkhanshali": "Yemen", "al-khanshali": "Yemen",
    "mokhtar": "Yemen",
}


def guess_country(text: str) -> str:
    low = (text or "").lower()
    for key, country in FARM_ORIGIN.items():
        if key in low:
            return country
    for w in ORIGIN_WORDS:
        if w.lower() in low:
            return w
    return ""


def price_per_kg(price_lb: float | None) -> float | None:
    return round(price_lb / KG_PER_LB, 2) if price_lb else None


_NUM = re.compile(r"-?\d[\d.,]*\d|\d")


def parse_number(text: str) -> float | None:
    """通貨記号や単位を含む文字列から数値を取り出す。

    US式（143.10 / 41,727.96）と欧州式（143,10 / 41.727,96）が
    同じページに混在するため、区切り文字の位置から小数点を判定する。
    """
    if text is None:
        return None
    m = _NUM.search(str(text).replace("\xa0", " "))
    if not m:
        return None
    s = m.group(0)
    has_dot, has_comma = "." in s, "," in s
    if has_dot and has_comma:
        # 最後に出る区切りが小数点
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif has_comma:
        frac = s.split(",")[-1]
        # 末尾1〜2桁のカンマは小数点、それ以外（3桁など複数）は桁区切り
        s = s.replace(",", ".") if (s.count(",") == 1 and len(frac) in (1, 2)) else s.replace(",", "")
    elif has_dot:
        frac = s.split(".")[-1]
        # ドット複数、または末尾ちょうど3桁は桁区切り（欧州式 41.727）
        if s.count(".") > 1 or (s.count(".") == 1 and len(frac) == 3):
            s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


# 後方互換のエイリアス（金額・重量など一般の数値に使う）
parse_money = parse_number


def parse_score(text: str) -> float | None:
    """カッピングスコアを読む（60〜100の帯に収める）。"""
    v = parse_number(text)
    if v is None:
        return None
    while v and v > 100:  # 桁ずれ（9115 等）の保険
        v = v / 10
    return round(v, 2)


def primary_variety(text: str) -> str:
    """複数品種表記から代表品種を1つ選ぶ。Geisha を優先。"""
    if not text:
        return ""
    g = guess_variety(text)
    if g:
        return g
    first = re.split(r"[,/;、]| y ", text, flags=re.I)[0].strip()
    return first.title()[:24]


def lots_to_dicts(lots: list[Lot]) -> list[dict]:
    return [asdict(x) for x in lots]
