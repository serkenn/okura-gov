"""問いの時点（SCOPE §8、D19・D22 S4）：所得税の年分・住民税・国保・国年の年度・被扶養者と第3号の判定日を、
評価の単位（OpenFisca の situation を作る「所得の年分」と判定日）に写す窓口。

考え方（packages/core/README.md §5.2）：
  - 判定コアの situation は暦年（所得の年分）ごとに作る。住民税・国保・国年の **年度 F** の値は、所得の年分 **F−1** の situation の中で計算する
    （年度＝所得の年分＋1。住民税は前年の所得：地方税法第313条第1項。国保の所得割の基礎も前年の所得。国年の免除等の所得も前年〔月分によって前々年〕）。
    そのため、年度の値の式は所得税の値（前年分の合計所得金額など）を **同じ期間** で引ける（同じ evaluate の中で前年分を評価する）。
    概念辞書には「制度をまたぐ依存」として書き、「年をまたぐ依存」にはしない。
  - 判定日 D の値（健保・共済の被扶養者、国年の第3号被保険者）は、D の属する暦年の situation を D ごとに作って計算する
    （同じ年の2つの判定日は別の situation。年の変数に判定日ごとの値を入れるため）。
  - 規則モジュールは YearContext.windows（その situation で答える問いの時点）から、年度・賦課期日・前年の12月31日・判定日などの
    名前つきの日付を引く（Window.dates）。窓口のない制度のモジュールも入力変数を全員分書く（値は使われない）。

日付の根拠：
  - 住民税の賦課期日 1月1日（地方税法第318条）、扶養・控除の判定の時点 前年の12月31日（同第314条の2第8項）：
    docs/public-sources/20261109_impl-prep_juminzei-hikazei-fuyo-shinkoku.md §3.1・§5、docs/public-sources/20261109_round2_kyosai-separate-address.md §4.1。
  - 国保の賦課期日：料は当該年度の初日（国保法第76条の2）、税は4月1日（地方税法第705条第2項）：
    docs/public-sources/20261109_round2_kokuho-premium-structure.md §1.1・§1.2。
  - 国年の免除・納付猶予は7月〜翌年6月の月分を前年の所得で（1〜6月分は前々年）、学生納付特例は4月〜翌年3月の月分を前年の所得で
    （1〜3月分は前々年）見る（国民年金法施行規則第77条の2ほか）：docs/public-sources/20261109_round2_kokuho-premium-structure.md §12.3。
    年度 F の国年の値は「所得の年分 F−1 で判定する期間」（免除等は F年7月〜F+1年6月、学生納付特例は F年4月〜F+1年3月）の値とする。
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from .result import OutOfScopeCategory, OutOfScopeItem, TimeKey

#: この版で計算する所得税の年分（SCOPE §5：令和7年分・令和8年分）。
SUPPORTED_INCOME_TAX_YEARS: tuple[int, ...] = (2025, 2026)
#: 住民税・国保・国年の年度（SCOPE §5：令和8年度分・令和9年度分）。年度 F は所得の年分 F−1 で計算する。
SUPPORTED_FISCAL_YEARS: tuple[int, ...] = (2026, 2027)
#: 判定日の範囲（両端を含む）。所得税の年分と年度の暦年を覆う仮の範囲（SCOPE に明記がない。README §9 の未決）。
SUPPORTED_JUDGMENT_DATES: tuple[_dt.date, _dt.date] = (_dt.date(2025, 1, 1), _dt.date(2027, 12, 31))

#: 年度の問いのキー → 制度。
FISCAL_QUERY_KEYS: Mapping[str, str] = MappingProxyType(
    {"resident_tax_fiscal_years": "住民税", "kokuho_fiscal_years": "国保", "kokunen_fiscal_years": "国年"}
)
#: 判定日の問いで答える制度（被扶養者は健保、第3号被保険者は国年）。
JUDGMENT_DATE_INSTITUTIONS: tuple[str, ...] = ("健保", "国年")

_NAMES = {"住民税": "住民税", "国保": "国民健康保険料（税）", "国年": "国民年金（保険料・免除等）", "健保": "健康保険・共済組合の被扶養者", "所得税": "所得税"}


@dataclass(frozen=True)
class Window:
    """問いの時点1つ：制度・問い（年分・年度・判定日）・結果の時点・situation の年（所得の年分）・名前つきの日付。"""

    institution: str
    question: str
    time: TimeKey
    income_year: int
    dates: Mapping[str, _dt.date] = field(default_factory=dict)

    def date(self, name: str) -> _dt.date:
        try:
            return self.dates[name]
        except KeyError:
            raise KeyError(f"問いの時点 {self.institution}・{self.time.to_dict()} に日付 {name} がない（{sorted(self.dates)}）") from None

    @property
    def judgment_on(self) -> _dt.date | None:
        return self.dates.get("判定日")

    def to_dict(self) -> dict[str, Any]:
        return {
            "institution": self.institution,
            "question": self.question,
            "time": self.time.to_dict(),
            "income_year": self.income_year,
            "dates": {k: v.isoformat() for k, v in sorted(self.dates.items())},
        }


def _d(y: int, m: int, d: int) -> _dt.date:
    return _dt.date(y, m, d)


def income_tax_window(year: int) -> Window:
    return Window("所得税", "年分", TimeKey("tax_year", year), year, MappingProxyType({"年分の初日": _d(year, 1, 1), "年分の末日": _d(year, 12, 31)}))


def resident_tax_window(fiscal_year: int) -> Window:
    f = fiscal_year
    return Window(
        "住民税",
        "年度",
        TimeKey("fiscal_year", f),
        f - 1,
        MappingProxyType(
            {
                "賦課期日": _d(f, 1, 1),
                "前年の12月31日": _d(f - 1, 12, 31),
                "年度の初日": _d(f, 4, 1),
                "年度の末日": _d(f + 1, 3, 31),
            }
        ),
    )


def kokuho_window(fiscal_year: int) -> Window:
    f = fiscal_year
    return Window(
        "国保",
        "年度",
        TimeKey("fiscal_year", f),
        f - 1,
        MappingProxyType({"賦課期日": _d(f, 4, 1), "年度の初日": _d(f, 4, 1), "年度の末日": _d(f + 1, 3, 31)}),
    )


def kokunen_window(fiscal_year: int) -> Window:
    f = fiscal_year
    return Window(
        "国年",
        "年度",
        TimeKey("fiscal_year", f),
        f - 1,
        MappingProxyType(
            {
                "年度の初日": _d(f, 4, 1),
                "年度の末日": _d(f + 1, 3, 31),
                "免除等の期間の初日": _d(f, 7, 1),
                "免除等の期間の末日": _d(f + 1, 6, 30),
                "学生納付特例の期間の初日": _d(f, 4, 1),
                "学生納付特例の期間の末日": _d(f + 1, 3, 31),
            }
        ),
    )


_FISCAL_WINDOWS = {"住民税": resident_tax_window, "国保": kokuho_window, "国年": kokunen_window}


def fiscal_window(institution: str, fiscal_year: int) -> Window:
    return _FISCAL_WINDOWS[institution](fiscal_year)


def judgment_window(institution: str, on: _dt.date) -> Window:
    return Window(institution, "判定日", TimeKey("on", on.isoformat()), on.year, MappingProxyType({"判定日": on}))


@dataclass(frozen=True)
class Unit:
    """評価の単位：所得の年分 income_year の situation 1つ（判定日の単位は on つき）と、そこで答える問いの時点。"""

    income_year: int
    on: _dt.date | None
    windows: tuple[Window, ...]

    @property
    def key(self) -> tuple[int, str]:
        return (self.income_year, "" if self.on is None else self.on.isoformat())

    def window_for(self, institution: str, question: str) -> Window | None:
        for w in self.windows:
            if w.institution == institution and w.question == question:
                return w
        return None

    def time_of(self, institution: str, question: str) -> TimeKey:
        """この単位で計算した概念（制度・問い）の値の時点。答える窓口がなければ問いから導く（依存先として出す値）。"""
        w = self.window_for(institution, question)
        if w is not None:
            return w.time
        if question == "年度":
            return TimeKey("fiscal_year", self.income_year + 1)
        if question == "判定日" and self.on is not None:
            return TimeKey("on", self.on.isoformat())
        return TimeKey("tax_year", self.income_year)

    def tag(self, time: TimeKey) -> str:
        """値の ID の時点の部分。所得税の年分は従来どおり "2026"。年度は "FY2027"、判定日は "2026-03-01"。
        判定日の単位で計算した、判定日でない値は "2026-03-01@2026" のように単位の判定日を前に付ける（ID を一意にする）。"""
        base = {"tax_year": lambda v: str(v), "fiscal_year": lambda v: f"FY{v}", "on": lambda v: str(v)}[time.kind](time.value)
        if self.on is not None and time.kind != "on":
            return f"{self.on.isoformat()}@{base}"
        return base


def plan_units(
    income_tax_years: Iterable[int],
    fiscal_years: Mapping[str, Iterable[int]],
    judgment_dates: Iterable[_dt.date],
    available: frozenset[tuple[str, str]],
) -> tuple[tuple[Unit, ...], tuple[OutOfScopeItem, ...]]:
    """問いを評価の単位に分ける（純粋関数）。

    - income_tax_years：所得税の年分。fiscal_years：問いのキー（FISCAL_QUERY_KEYS）→ 年度。judgment_dates：判定日。
    - available：登録した規則モジュールが結果に出す概念の（制度, 問い）の組。ない制度の問いは「対象外（未対応）」。
    - 単位は (所得の年分, 判定日) ごとに1つ。年度 F の窓口は所得の年分 F−1 の単位に入る（所得税の年分 F−1 と同じ situation）。
    """
    units: dict[tuple[int, str], list[Window]] = {}
    ons: dict[tuple[int, str], _dt.date | None] = {}
    items: list[OutOfScopeItem] = []

    def add(w: Window, on: _dt.date | None) -> None:
        k = (w.income_year, "" if on is None else on.isoformat())
        units.setdefault(k, []).append(w)
        ons[k] = on

    for y in income_tax_years:
        if y not in SUPPORTED_INCOME_TAX_YEARS:
            items.append(
                OutOfScopeItem(
                    {"query": "income_tax_years", "value": y},
                    (),
                    OutOfScopeCategory.OUT_OF_YEARS,
                    "この版が計算する所得税の年分は令和7年分（2025）・令和8年分（2026）だけ（SCOPE §5）",
                )
            )
            continue
        add(income_tax_window(y), None)
    for key, years in fiscal_years.items():
        inst = FISCAL_QUERY_KEYS[key]
        for f in years:
            if f not in SUPPORTED_FISCAL_YEARS:
                items.append(
                    OutOfScopeItem(
                        {"query": key, "value": f},
                        (),
                        OutOfScopeCategory.OUT_OF_YEARS,
                        f"この版が計算する{_NAMES[inst]}の年度は令和8年度（2026）・令和9年度（2027）だけ（SCOPE §5）",
                    )
                )
                continue
            if (inst, "年度") not in available:
                items.append(
                    OutOfScopeItem(
                        {"query": key, "value": f}, (), OutOfScopeCategory.NOT_IMPLEMENTED, f"{_NAMES[inst]}の判定・計算はこの版では未実装"
                    )
                )
                continue
            add(fiscal_window(inst, f), None)
    lo, hi = SUPPORTED_JUDGMENT_DATES
    for d in judgment_dates:
        if not lo <= d <= hi:
            items.append(
                OutOfScopeItem(
                    {"query": "dependent_judgment_dates", "value": d.isoformat()},
                    (),
                    OutOfScopeCategory.OUT_OF_YEARS,
                    f"この版が判定する判定日は {lo.isoformat()} から {hi.isoformat()} まで",
                )
            )
            continue
        insts = [i for i in JUDGMENT_DATE_INSTITUTIONS if (i, "判定日") in available]
        missing = [i for i in JUDGMENT_DATE_INSTITUTIONS if (i, "判定日") not in available]
        if missing:
            items.append(
                OutOfScopeItem(
                    {"query": "dependent_judgment_dates", "value": d.isoformat(), "institutions": missing},
                    (),
                    OutOfScopeCategory.NOT_IMPLEMENTED,
                    "健康保険・共済組合の被扶養者、第3号被保険者の判定のうち " + "・".join(_NAMES[i] if i != "国年" else "第3号被保険者" for i in missing) + " はこの版では未実装",
                )
            )
        for inst in insts:
            add(judgment_window(inst, d), d)
    out = tuple(Unit(k[0], ons[k], tuple(units[k])) for k in sorted(units))
    return out, tuple(items)


__all__ = [
    "FISCAL_QUERY_KEYS",
    "JUDGMENT_DATE_INSTITUTIONS",
    "SUPPORTED_FISCAL_YEARS",
    "SUPPORTED_INCOME_TAX_YEARS",
    "SUPPORTED_JUDGMENT_DATES",
    "Unit",
    "Window",
    "fiscal_window",
    "income_tax_window",
    "judgment_window",
    "kokuho_window",
    "kokunen_window",
    "plan_units",
    "resident_tax_window",
]
