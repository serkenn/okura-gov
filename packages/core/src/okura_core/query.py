"""問い（SCOPE §8、D19、D22 S4）の形と検査。

問いの JSON（キーは全部必須。filing_date・kokunen_fiscal_years だけ任意）：

    {
      "income_tax_years": [2025, 2026],            所得税の年分（西暦）
      "filing_date": {"on": "2027-03-10", "planned": true},   提出日（planned=true なら予定日）
      "resident_tax_fiscal_years": [],             住民税の年度（西暦）
      "kokuho_fiscal_years": [],                   国民健康保険料（税）の年度（西暦）
      "kokunen_fiscal_years": [],                  国民年金（保険料・免除等）の年度（西暦。任意のキー。2026-11-11 に足した）
      "dependent_judgment_dates": [],              被扶養者の判定日（YYYY-MM-DD）
      "forms": {"persons": ["p-1"]},               様式の欄の値（任意のキー。2026-11-12）：所得税の年分 × 申告者ごとに作る。
                                                   persons が null なら、その年分に生存している全員。キーがない・null なら作らない
      "workers": 4,                                 候補の組を計算するプロセスの数（任意のキー。2026-11-12）：null・キーなしは CPU の数、1 は直列。
                                                   実行の指定で結果を変えない（結果の query・入力の SHA-256 に入れない）
      "scenarios": [                               複数シナリオ（判断・選択の差分。D12 の形）
        {"id": "s1", "label": "…", "judgments": [ …中間表現の判断… ], "choices": [ …選択… ]}
      ]
    }

- 形の誤り（知らないキー、年が整数でない、重複、日付の形）は問題として返す（例外を送出しない）。
- 対象の年分・年度の外（例：令和6年分）は形の誤りではない。evaluate が「対象外（年分外）」として返す。
- 年度 F の住民税・国保・国年は、所得の年分 F−1 の situation で計算する（timepoints.py）。判定日は健保・共済の被扶養者と第3号被保険者に使う。
- シナリオは常に差分なしの "base" を先頭に足して評価する（design-output §4.1）。"base" は予約語。
- シナリオで変えられるのは判断・選択の追記だけ（design-output UO13 は未決。事実は変えない）。
"""

from __future__ import annotations

import copy
import datetime as _dt
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .result import Problem

BASE_SCENARIO_ID = "base"

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}", re.ASCII)
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", re.ASCII)

#: 年の形として受け付ける範囲（対象の年分かどうかは evaluate が決める）。
YEAR_MIN = 2000
YEAR_MAX = 2100
MAX_SCENARIOS = 32
MAX_LIST = 64

_REQUIRED = (
    "income_tax_years",
    "resident_tax_fiscal_years",
    "kokuho_fiscal_years",
    "dependent_judgment_dates",
    "scenarios",
)
_OPTIONAL = ("filing_date", "kokunen_fiscal_years", "forms", "workers")
#: workers の上限（形の検査。並列の数は結果を変えない）
MAX_WORKERS = 256


@dataclass(frozen=True)
class FilingDate:
    on: _dt.date
    planned: bool

    def to_dict(self) -> dict[str, Any]:
        return {"on": self.on.isoformat(), "planned": self.planned}


@dataclass(frozen=True)
class FormsRequest:
    """様式の欄の値の求め（申告者。None ならその年分に生存している全員）。"""

    persons: tuple[str, ...] | None

    def to_dict(self) -> dict[str, Any]:
        return {"persons": None if self.persons is None else list(self.persons)}


@dataclass(frozen=True)
class Scenario:
    id: str
    label: str | None
    judgments: tuple[Mapping[str, Any], ...]
    choices: tuple[Mapping[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "judgments": [dict(j) for j in self.judgments],
            "choices": [dict(c) for c in self.choices],
        }


@dataclass(frozen=True)
class Query:
    income_tax_years: tuple[int, ...]
    filing_date: FilingDate | None
    resident_tax_fiscal_years: tuple[int, ...]
    kokuho_fiscal_years: tuple[int, ...]
    dependent_judgment_dates: tuple[_dt.date, ...]
    scenarios: tuple[Scenario, ...]
    kokunen_fiscal_years: tuple[int, ...] = ()
    forms: FormsRequest | None = None
    #: 候補の組を計算するプロセスの数（None は CPU の数、1 は直列。parallel.py）。実行の指定なので to_dict に出さない（結果を変えない）
    workers: int | None = None

    def all_scenarios(self) -> tuple[Scenario, ...]:
        """先頭に差分なしの base を足したシナリオの並び。"""
        return (Scenario(BASE_SCENARIO_ID, "差分なし", (), ()),) + self.scenarios

    def to_dict(self) -> dict[str, Any]:
        return {
            "income_tax_years": list(self.income_tax_years),
            "filing_date": None if self.filing_date is None else self.filing_date.to_dict(),
            "resident_tax_fiscal_years": list(self.resident_tax_fiscal_years),
            "kokuho_fiscal_years": list(self.kokuho_fiscal_years),
            "kokunen_fiscal_years": list(self.kokunen_fiscal_years),
            "dependent_judgment_dates": [d.isoformat() for d in self.dependent_judgment_dates],
            "scenarios": [s.to_dict() for s in self.scenarios],
            "forms": None if self.forms is None else self.forms.to_dict(),
        }


def _forms_request(v: Any, path: str, problems: list[Problem]) -> FormsRequest | None:
    if v is None:
        return None
    if not isinstance(v, dict):
        problems.append(Problem(path, "type", f"forms は null かオブジェクト {{persons}}（{_type_name(v)} が来た）"))
        return None
    ps = _object_keys(v, path, ("persons",), ())
    problems.extend(ps)
    if ps:
        return None
    persons = v["persons"]
    if persons is None:
        return FormsRequest(None)
    if not isinstance(persons, list) or len(persons) > MAX_LIST:
        problems.append(Problem(f"{path}.persons", "type", f"persons は null か人の ID の配列（{MAX_LIST} 個まで）"))
        return None
    out: list[str] = []
    for i, pid in enumerate(persons):
        if not isinstance(pid, str) or not pid:
            problems.append(Problem(f"{path}.persons[{i}]", "type", "人の ID は空でない文字列"))
        elif pid in out:
            problems.append(Problem(f"{path}.persons[{i}]", "duplicate", f"人 {pid} が重複している"))
        else:
            out.append(pid)
    return FormsRequest(tuple(out))


def _type_name(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "真偽値"
    if isinstance(v, int):
        return "整数"
    if isinstance(v, float):
        return "小数"
    if isinstance(v, str):
        return "文字列"
    if isinstance(v, list):
        return "配列"
    if isinstance(v, dict):
        return "オブジェクト"
    return type(v).__name__


def parse_date(v: Any, path: str, problems: list[Problem]) -> _dt.date | None:
    if not isinstance(v, str) or not _DATE.fullmatch(v):
        problems.append(Problem(path, "format", f"日付は YYYY-MM-DD の文字列（{_type_name(v)} が来た）"))
        return None
    try:
        return _dt.date.fromisoformat(v)
    except ValueError:
        problems.append(Problem(path, "format", f"実在しない日付: {v}"))
        return None


def _years(v: Any, path: str, problems: list[Problem]) -> tuple[int, ...]:
    if not isinstance(v, list):
        problems.append(Problem(path, "type", f"年の配列が必要（{_type_name(v)} が来た）"))
        return ()
    if len(v) > MAX_LIST:
        problems.append(Problem(path, "max_items", f"多すぎる（{MAX_LIST} 個まで）"))
        return ()
    out: list[int] = []
    for i, y in enumerate(v):
        p = f"{path}[{i}]"
        if type(y) is not int:
            problems.append(Problem(p, "type", f"年は整数（{_type_name(y)} が来た）"))
            continue
        if not YEAR_MIN <= y <= YEAR_MAX:
            problems.append(Problem(p, "range", f"年は {YEAR_MIN}〜{YEAR_MAX}"))
            continue
        if y in out:
            problems.append(Problem(p, "duplicate", f"年 {y} が重複している"))
            continue
        out.append(y)
    return tuple(sorted(out))


def _object_keys(obj: Mapping[str, Any], path: str, required: tuple[str, ...], optional: tuple[str, ...]) -> list[Problem]:
    problems: list[Problem] = []
    for k in required:
        if k not in obj:
            problems.append(Problem(f"{path}.{k}", "required", f"{k} がない（空でも書く）"))
    for k in obj:
        if k not in required and k not in optional:
            problems.append(Problem(f"{path}.{k}", "additional_property", f"知らないキー: {k}"))
    return problems


def _scenario(v: Any, path: str, problems: list[Problem]) -> Scenario | None:
    if not isinstance(v, dict):
        problems.append(Problem(path, "type", f"シナリオはオブジェクト（{_type_name(v)} が来た）"))
        return None
    ps = _object_keys(v, path, ("id", "judgments", "choices"), ("label",))
    problems.extend(ps)
    if ps:
        return None
    sid = v["id"]
    ok = True
    if not isinstance(sid, str) or not _ID.fullmatch(sid):
        problems.append(Problem(f"{path}.id", "pattern", "シナリオの ID は英数字で始まる64文字までの ASCII"))
        ok = False
    elif sid == BASE_SCENARIO_ID:
        problems.append(Problem(f"{path}.id", "reserved", f"{BASE_SCENARIO_ID} は差分なしのシナリオの予約語"))
        ok = False
    label = v.get("label")
    if label is not None and (not isinstance(label, str) or not label or len(label) > 200):
        problems.append(Problem(f"{path}.label", "type", "label は1〜200文字の文字列"))
        ok = False
    lists: dict[str, tuple[Mapping[str, Any], ...]] = {}
    for key in ("judgments", "choices"):
        items = v[key]
        if not isinstance(items, list) or not all(isinstance(x, dict) for x in items):
            problems.append(Problem(f"{path}.{key}", "type", "オブジェクトの配列が必要（中身は中間表現と同じ形）"))
            ok = False
            continue
        # 呼び出し側の dict を結果（Query.to_dict → EvaluationResult.query）と共有しない（入力と結果の別名を作らない）
        lists[key] = tuple(copy.deepcopy(items))
    if not ok:
        return None
    return Scenario(sid, label, lists["judgments"], lists["choices"])


def parse_query(raw: Any, *, path: str = "$") -> tuple[Query | None, list[Problem]]:
    """問いを検査して Query にする。例外を送出しない。問題があれば (None, 問題の一覧)。"""
    problems: list[Problem] = []
    if not isinstance(raw, dict):
        return None, [Problem(path, "type", f"問いはオブジェクト（{_type_name(raw)} が来た）")]
    problems.extend(_object_keys(raw, path, _REQUIRED, _OPTIONAL))
    if problems:
        return None, problems

    income_tax_years = _years(raw["income_tax_years"], f"{path}.income_tax_years", problems)
    resident = _years(raw["resident_tax_fiscal_years"], f"{path}.resident_tax_fiscal_years", problems)
    kokuho = _years(raw["kokuho_fiscal_years"], f"{path}.kokuho_fiscal_years", problems)
    kokunen = _years(raw.get("kokunen_fiscal_years", []), f"{path}.kokunen_fiscal_years", problems)

    dates_raw = raw["dependent_judgment_dates"]
    dates: list[_dt.date] = []
    if not isinstance(dates_raw, list):
        problems.append(Problem(f"{path}.dependent_judgment_dates", "type", "日付の配列が必要"))
    elif len(dates_raw) > MAX_LIST:
        problems.append(Problem(f"{path}.dependent_judgment_dates", "max_items", f"多すぎる（{MAX_LIST} 個まで）"))
    else:
        for i, d in enumerate(dates_raw):
            parsed = parse_date(d, f"{path}.dependent_judgment_dates[{i}]", problems)
            if parsed is None:
                continue
            if parsed in dates:
                problems.append(Problem(f"{path}.dependent_judgment_dates[{i}]", "duplicate", f"判定日 {d} が重複している"))
                continue
            dates.append(parsed)

    filing: FilingDate | None = None
    if "filing_date" in raw:
        fd = raw["filing_date"]
        fp = f"{path}.filing_date"
        if not isinstance(fd, dict):
            problems.append(Problem(fp, "type", f"提出日はオブジェクト {{on, planned}}（{_type_name(fd)} が来た）"))
        else:
            ps = _object_keys(fd, fp, ("on", "planned"), ())
            problems.extend(ps)
            if not ps:
                on = parse_date(fd["on"], f"{fp}.on", problems)
                if type(fd["planned"]) is not bool:
                    problems.append(Problem(f"{fp}.planned", "type", "planned は真偽値（予定日なら true）"))
                elif on is not None:
                    filing = FilingDate(on, fd["planned"])

    forms = _forms_request(raw.get("forms"), f"{path}.forms", problems)

    workers = raw.get("workers")
    if workers is not None and (type(workers) is not int or not 1 <= workers <= MAX_WORKERS):
        problems.append(Problem(f"{path}.workers", "type", f"workers は null か 1〜{MAX_WORKERS} の整数（プロセスの数。1 は直列）"))
        workers = None

    scenarios: list[Scenario] = []
    sc_raw = raw["scenarios"]
    if not isinstance(sc_raw, list):
        problems.append(Problem(f"{path}.scenarios", "type", "シナリオの配列が必要"))
    elif len(sc_raw) > MAX_SCENARIOS:
        problems.append(Problem(f"{path}.scenarios", "max_items", f"シナリオは {MAX_SCENARIOS} 個まで"))
    else:
        seen: set[str] = set()
        for i, s in enumerate(sc_raw):
            sc = _scenario(s, f"{path}.scenarios[{i}]", problems)
            if sc is None:
                continue
            if sc.id in seen:
                problems.append(Problem(f"{path}.scenarios[{i}].id", "duplicate", f"シナリオの ID {sc.id} が重複している"))
                continue
            seen.add(sc.id)
            scenarios.append(sc)

    if problems:
        return None, problems
    return (
        Query(
            income_tax_years=income_tax_years,
            filing_date=filing,
            resident_tax_fiscal_years=resident,
            kokuho_fiscal_years=kokuho,
            dependent_judgment_dates=tuple(sorted(dates)),
            scenarios=tuple(scenarios),
            kokunen_fiscal_years=kokunen,
            forms=forms,
            workers=workers,
        ),
        [],
    )
