"""様式の欄の対応表（forms）を evaluate の結果に組み込む部分（SCOPE §3、HANDOFF D19 T5-2、forms/README.md §5 の申し送り）。

- form_concepts(年分)：その年分の欄・帳票を使う条件・申告の型・行の割当てが読む概念 ID。evaluate は問いが欄の値を求めたとき、
  これらの概念のうち「出力」を持たない途中の概念も、その年分の単位の値として結果に出す（form_specs。トレースを止める出力の
  集まりは変えないので、ほかの値は変わらない）。
- forms_for(値, 申告者, 年分の一覧, 提出日)：申告者 × 年分ごとに forms.fill_forms を呼ぶ。予測は fill_forms が止める（build_filing と同じ：
  申告者・年分の申告の範囲の値か欄が使う値に予測があれば全部を出さない）。施行日前の提出は build_filing と同じ判定
  （result.enforcement_after：申告者・年分の申告の範囲の値が依存した規定の施行日が提出日より後）で止める。
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable
from .concepts import ConceptDictionary
from .forms import FormsRefusal, FormsResult, RefusalCategory, fill_forms, load_year
from .forms import fill as _fill
from .forms import rows as _rows
from .registry import OutputSpec, Registry, memo
from .result import ResultValue, TimeKey, enforcement_after


def form_concepts(tax_year: int) -> frozenset[str]:
    """その年分の対応表が読む概念 ID（欄・帳票を使う条件・申告の型・行の割当て）。対応表がない・未公表の年分は空。"""
    tables = load_year(tax_year)
    if tables is None:
        return frozenset()
    out: set[str] = set()
    for table in tables.forms:
        for p in table.use_when:
            out.update(p.concepts())
        for spec in table.fields:
            out.update(spec.mapping.concepts())
    out.update(_fill._LOSS)
    out.update(_fill._SEPARATE)
    for pair in _fill._CARRIED:
        out.update(pair)
    out.update(v for k, v in vars(_rows).items() if k.startswith("C_") and isinstance(v, str))
    return frozenset(c for c in out if c)


def form_specs(reg: Registry, tax_year: int, outputs: Iterable[OutputSpec]) -> tuple[OutputSpec, ...]:
    """欄が読む概念のうち、結果の出力でない実装済みの人の概念を、結果に出す値として足す（依存の順。申告の範囲には入れない）。"""
    cache = memo(reg, "form_specs")
    have = frozenset(o.variable for o in outputs)
    key = (tax_year, have)
    if key in cache:
        return cache[key]
    d: ConceptDictionary = reg.dictionary
    wanted = form_concepts(tax_year)
    out: list[OutputSpec] = []
    for c in d.topological_order():
        if c.id not in wanted or not c.implemented or not c.variables:
            continue
        var = c.variables[0]
        if var in have or var not in reg.variable_module or c.entity != "人物" or c.institution != "所得税":
            continue  # 所得税の年分の値だけ（住民税などの年度の値は、その年度を問われた単位で計算する）
        out.append(OutputSpec(var, c.id, c.value_type, False, False, d.depends_on_all_income(c.id)))
    cache[key] = tuple(out)
    return cache[key]


def forms_for(
    values: Iterable[ResultValue],
    persons: Iterable[str],
    tax_years: Iterable[int],
    filing_date: _dt.date | None,
) -> tuple[FormsResult | FormsRefusal, ...]:
    """申告者 × 年分ごとの欄の値（年分の順、その中で申告者の順）。"""
    items = tuple(values)
    out: list[FormsResult | FormsRefusal] = []
    for year in tax_years:
        time = TimeKey("tax_year", year)
        for person in persons:
            mine = [v for v in items if v.person == person and v.time == time]
            if not mine:
                continue  # その年分に値がない人（生存していないなど）
            late, blocking = enforcement_after(mine, items, filing_date)
            if late:
                out.append(
                    FormsRefusal(
                        person,
                        year,
                        RefusalCategory.BEFORE_ENFORCEMENT,
                        "提出日が、使った規定の施行日（" + "・".join(late) + "）より前。施行前に出す申告書の値は出さない（result.build_filing と同じ）",
                        blocking_value_ids=blocking,
                    )
                )
                continue
            out.append(fill_forms(items, person, year))
    return tuple(out)


__all__ = ["form_concepts", "form_specs", "forms_for"]
