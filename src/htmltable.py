"""標準ライブラリ html.parser だけで HTML の <table> を抽出する軽量パーサ。

外部依存（BeautifulSoup 等）を足さずに、WordPress 由来の結果ページを読むための道具。
各テーブルを rows（list[list[str]]）として取り出し、
直前に現れた見出し（h1〜h4）をそのテーブルの「文脈ラベル」として添える。
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from html import unescape


@dataclass
class Table:
    heading: str            # 直前の見出しテキスト（カテゴリ名になりがち）
    rows: list = field(default_factory=list)  # list[list[str]]


class _TableExtractor(HTMLParser):
    HEADINGS = {"h1", "h2", "h3", "h4"}
    CELLS = {"td", "th"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[Table] = []
        self._last_heading = ""
        self._depth = 0            # table のネスト深さ
        self._in_heading = False
        self._heading_buf: list[str] = []
        self._cur: Table | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag in self.HEADINGS and self._depth == 0:
            self._in_heading = True
            self._heading_buf = []
        elif tag == "table":
            self._depth += 1
            if self._depth == 1:
                self._cur = Table(heading=self._last_heading.strip())
        elif self._cur is not None:
            if tag == "tr":
                self._row = []
            elif tag in self.CELLS:
                self._cell = []

    def handle_endtag(self, tag):
        if tag in self.HEADINGS and self._in_heading:
            self._in_heading = False
            self._last_heading = _clean(" ".join(self._heading_buf))
        elif tag == "table":
            if self._depth == 1 and self._cur is not None:
                if self._cur.rows:
                    self.tables.append(self._cur)
                self._cur = None
            self._depth = max(0, self._depth - 1)
        elif self._cur is not None:
            if tag == "tr" and self._row is not None:
                if any(c.strip() for c in self._row):
                    self._cur.rows.append(self._row)
                self._row = None
            elif tag in self.CELLS and self._cell is not None:
                if self._row is not None:
                    self._row.append(_clean(" ".join(self._cell)))
                self._cell = None

    def handle_data(self, data):
        if self._in_heading:
            self._heading_buf.append(data)
        elif self._cell is not None:
            self._cell.append(data)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", unescape(text)).strip()


def extract_tables(html: str) -> list[Table]:
    p = _TableExtractor()
    try:
        p.feed(html)
    except Exception:
        pass
    return p.tables
