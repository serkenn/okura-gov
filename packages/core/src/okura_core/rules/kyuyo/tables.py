"""大きな表のデータ（rules/kyuyo/data/ の CSV。規則モジュール kyuyo）を、出典つきで読む。

- 表は実測の出力（scripts/results/…）を写したもの。写した元と SHA-256 は data/SOURCES.json にある。
- 読むたびに SHA-256 を確かめ、合わなければ例外（黙って別の表を使わない）。
- 読んだ表は変更できない値（タプル・frozen dataclass）。同じ表 ID には同じ値を返すので、読み込みを
  functools.cache で覚える（パッケージのファイルで決まる不変の値の覚え書きで、可変の状態ではない）。
"""

from __future__ import annotations

import bisect
import csv
import functools
import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...basis import SourceKind

DATA_DIR = Path(__file__).resolve().parent / "data"
SOURCES_FILE = DATA_DIR / "SOURCES.json"

_KINDS = ("fixed", "minus", "rate_minus", "point")


class DataFileError(Exception):
    """表のデータが記録と合わない・壊れている。"""


def sources() -> dict[str, Any]:
    """data/SOURCES.json（呼ぶたびに読み直した新しい dict）。"""
    return json.loads(SOURCES_FILE.read_text(encoding="utf-8"))


def _file_info(file_name: str) -> dict[str, Any]:
    info = sources()["files"].get(file_name)
    if info is None:
        raise DataFileError(f"SOURCES.json に記録がない: {file_name}")
    return info


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class Beppyo5Row:
    """別表第五の1区分。lower 以上 upper 未満（point は lower の1点）。

    kind：fixed（金額）、minus（給与等の金額 − c）、rate_minus（給与等の金額 × rate_pct% − c）、point（1点の金額）。
    """

    lower: int
    upper: int | None
    kind: str
    value: int | None
    c: int | None
    rate_pct: int | None
    source_text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "lower_incl": self.lower,
            "upper_excl": self.upper,
            "kind": self.kind,
            "value": self.value,
            "formula_c": self.c,
            "formula_rate_pct": self.rate_pct,
            "source_text": self.source_text,
        }


@dataclass(frozen=True)
class Beppyo5Table:
    table_id: str
    file_name: str
    sha256: str
    title: str
    law: str
    law_revision_id: str
    asof: str
    source_kind: SourceKind
    references: tuple[str, ...]
    rows: tuple[Beppyo5Row, ...]
    lowers: tuple[int, ...]

    def row_for(self, x: int) -> Beppyo5Row:
        """給与等の金額 x を含む区分。区分の外なら例外。"""
        if type(x) is not int or x < 0:
            raise ValueError("給与等の金額は0以上の整数の円")
        i = bisect.bisect_right(self.lowers, x) - 1
        if i < 0:
            raise ValueError(f"別表第五の区分の外: {x}")
        row = self.rows[i]
        if row.kind == "point":
            if x != row.lower:
                raise ValueError(f"別表第五の区分の外: {x}")
        elif row.upper is None or not (row.lower <= x < row.upper):
            raise ValueError(f"別表第五の区分の外: {x}")
        return row


def _int_or_none(s: str) -> int | None:
    s = s.strip()
    if s == "":
        return None
    if not s.isdigit():
        raise DataFileError(f"整数でない値: {s!r}")
    return int(s)


def _parse_beppyo5(text: str, file_name: str) -> tuple[Beppyo5Row, ...]:
    reader = csv.DictReader(io.StringIO(text, newline=""))
    expected = [
        "lower_incl",
        "upper_excl",
        "kind",
        "value",
        "formula_c",
        "formula_rate_pct",
        "struct",
        "group",
        "row",
        "source_text",
    ]
    if reader.fieldnames != expected:
        raise DataFileError(f"{file_name}: 列が違う: {reader.fieldnames}")
    rows: list[Beppyo5Row] = []
    for rec in reader:
        kind = rec["kind"]
        if kind not in _KINDS:
            raise DataFileError(f"{file_name}: 知らない区分の種類: {kind}")
        lower = _int_or_none(rec["lower_incl"])
        if lower is None:
            raise DataFileError(f"{file_name}: 下限がない")
        row = Beppyo5Row(
            lower=lower,
            upper=_int_or_none(rec["upper_excl"]),
            kind=kind,
            value=_int_or_none(rec["value"]),
            c=_int_or_none(rec["formula_c"]),
            rate_pct=_int_or_none(rec["formula_rate_pct"]),
            source_text=rec["source_text"],
        )
        if kind in ("fixed", "point") and row.value is None:
            raise DataFileError(f"{file_name}: 金額の区分に金額がない（{lower}）")
        if kind in ("minus", "rate_minus") and row.c is None:
            raise DataFileError(f"{file_name}: 式の区分に定数がない（{lower}）")
        if kind == "rate_minus" and row.rate_pct is None:
            raise DataFileError(f"{file_name}: 率の区分に率がない（{lower}）")
        if kind != "point" and (row.upper is None or row.upper <= row.lower):
            raise DataFileError(f"{file_name}: 区分の上限がおかしい（{lower}）")
        rows.append(row)
    if not rows or rows[0].lower != 0:
        raise DataFileError(f"{file_name}: 0円から始まらない")
    for prev, cur in zip(rows, rows[1:]):
        if prev.kind == "point":
            raise DataFileError(f"{file_name}: 1点の区分の後に区分がある")
        if prev.upper != cur.lower:
            raise DataFileError(f"{file_name}: 区分に隙間・重なりがある（{prev.upper} と {cur.lower}）")
    return tuple(rows)


@functools.cache
def load_beppyo5(table_id: str) -> Beppyo5Table:
    """表 ID（例 "beppyo5_2025-12-31"）の別表第五を読む。SHA-256 が記録と違えば DataFileError。"""
    file_name = f"{table_id}.csv"
    info = _file_info(file_name)
    if info.get("table_id") != table_id:
        raise DataFileError(f"SOURCES.json の表 ID が違う: {file_name}")
    path = DATA_DIR / file_name
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != info["sha256"]:
        raise DataFileError(f"{file_name} の SHA-256 が記録と違う（{digest}）")
    rows = _parse_beppyo5(raw.decode("utf-8"), file_name)
    return Beppyo5Table(
        table_id=table_id,
        file_name=file_name,
        sha256=digest,
        title=info["title"],
        law=info["law"],
        law_revision_id=info["law_revision_id"],
        asof=info["asof"],
        source_kind=SourceKind.from_label(info["source_kind"]),
        references=tuple(info["references"]),
        rows=rows,
        lowers=tuple(r.lower for r in rows),
    )


def data_file_hashes() -> dict[str, str]:
    """結果の版に書く：data/ の表のファイル名 → SHA-256（記録の値ではなく、いまのファイルの値）。"""
    out: dict[str, str] = {}
    for name in sorted(sources()["files"]):
        out[f"rules/kyuyo/data/{name}"] = file_sha256(DATA_DIR / name)
    return out
