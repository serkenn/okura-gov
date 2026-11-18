"""住民税への窓口（2026-11-12。rules/juminzei/README.md JM-03）：翌年の1月1日（住民税の賦課期日）の障害者・婚姻の現況。

地方税法第295条第1項第2号の非課税の判定の時点を賦課期日とする市町村（注入データ 住民税.135万円の非課税の判定の時点）では、
障害者・寡婦・ひとり親を賦課期日の現況で判定する。このモジュールの判定は所得税の判定の時（その年の12月31日）だけなので、
同じ材料（disability_basis・判断.障害の程度・marriage・legal_sex・住民票の事実婚の記載）を翌年の1月1日に取り出して、入力変数に書く。

- `所得税_翌年1月1日に障害者に当たるか`：所得税法施行令第10条第1項の区分（classify.所得税_障害者に当たるか と同じ材料の論理和。
  市町村長等の認定は年齢の下限）を翌年の1月1日の記録で。判断.障害の程度 の側面は、その日を覆う判断がそろっていればその値、
  材料があるのに判断がなければ分かれ目（決める手段：判断）。
- `所得税_翌年1月1日に婚姻の状況が判定の時と違うか`：婚姻・配偶者の生死不明・夫との離婚又は死別・事実婚の記載のどれかが、
  判定の時と翌年の1月1日で違うか（寡婦・ひとり親の本人の要件が変わりうる）。
- `所得税_翌年1月1日に婚姻又は事実婚をしているか`：翌年の1月1日に婚姻が続いている（配偶者の生死不明を除く）か、住民票に事実婚の記載がある
  （寡婦・ひとり親の本人の要件を欠く：所法2①三十・三十一）。

法令の判定の式（障害者の区分の論理和）は classify.py と同じ材料・同じ向きで、パラメータも同じもの（所得税.障害者.市町村長等の認定の年齢の下限）を使う。
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from ...registry import ModuleInputs, YearContext
from ...result import Means, Split, State
from .ir_facts import (
    IrIndex,
    certificate_grade,
    cohabitation,
    covers,
    disability_bases,
    ended_marriages,
    missing_spouses,
    other_party,
)

V_JAN1_DISABLED = "所得税_翌年1月1日に障害者に当たるか"
V_JAN1_MARITAL_CHANGED = "所得税_翌年1月1日に婚姻の状況が判定の時と違うか"
V_JAN1_MARRIED = "所得税_翌年1月1日に婚姻又は事実婚をしているか"
VARIABLES_WRITTEN = (V_JAN1_DISABLED, V_JAN1_MARITAL_CHANGED, V_JAN1_MARRIED)

#: 判断.障害の程度 の側面のうち、障害者の区分に効くもの（inputs.ASPECT_TRIGGERS と同じ。材料の記録の根拠 → None は材料のない側面）
_ASPECTS = {
    "lacks_capacity": None,
    "severe_intellectual_disability": "intellectual_disability_assessment",
    "bedridden_requiring_complex_care": None,
    "evidently_disabled_pending_application": "application",
}
_BOOL_BASES = ("intellectual_disability_assessment", "war_injury_certificate", "atomic_bomb_survivor_certification")


def _marks(records: Any) -> frozenset[State]:
    return frozenset(State.from_mark(r["mark"]) for r in records if "mark" in r)


def _age_on(birth: _dt.date | None, day: _dt.date) -> int:
    if birth is None:
        return 0
    return day.year - birth.year - ((day.month, day.day) < (birth.month, birth.day))


def _marital(idx: IrIndex, pid: str, t: _dt.date) -> tuple[tuple[Any, ...], list[str]]:
    """婚姻の状況の比べる値（婚姻が続く・配偶者の生死不明・離婚・死別・事実婚の記載）と、使った記録の ID。"""
    active = [
        r for r in idx.of("marriage", pid)
        if covers(r.get("when"), t) and (idx.death(other_party(r, pid)) is None or idx.death(other_party(r, pid)) >= t)
    ]
    missing = [m for m in missing_spouses(idx, pid, t) if m.applies is not False]
    ended = [e for e in ended_marriages(idx, pid, t) if e.husband is not False]
    coh = cohabitation(idx, pid, t)
    key = (bool(active), bool(missing), any(e.divorced for e in ended), any(not e.divorced for e in ended), coh.found)
    ids = [r["id"] for r in active] + [m.record["id"] for m in missing] + [e.record["id"] for e in ended] + list(coh.ids)
    return key, ids


def write(ctx: YearContext, out: ModuleInputs, aspect_judgments: Any) -> None:
    """全員の3つの入力を書く。aspect_judgments(人, 側面, 日) は判断.障害の程度 のその日を覆う判断の一覧（inputs._Source.aspect_judgments）。"""
    idx = IrIndex(ctx.ir)
    dec31, jan1 = _dt.date(ctx.year, 12, 31), _dt.date(ctx.year + 1, 1, 1)
    age_floor = int(ctx.parameters.所得税.障害者.市町村長等の認定の年齢の下限)
    for pid in ctx.persons:
        death = idx.death(pid)
        if death is not None and death < jan1:  # 賦課期日に生存していない人は賦課期日の現況がない（判定の時の値を使う）
            out.set(V_JAN1_DISABLED, pid, False)
            out.set(V_JAN1_MARITAL_CHANGED, pid, False)
            out.set(V_JAN1_MARRIED, pid, False)
            continue
        bases = disability_bases(idx, pid, jan1)
        ids = [r["id"] for r in bases]
        hit = False
        for basis in ("physical_disability_certificate", "mental_disability_certificate"):
            grade, _ = certificate_grade(bases, basis)
            hit |= grade > 0
        hit |= any(r["attributes"]["basis"] in _BOOL_BASES for r in bases)
        hit |= any(r["attributes"]["basis"] == "municipal_certification" for r in bases) and _age_on(ctx.birth_on(pid), jan1) >= age_floor
        miss: list[Split] = []
        states = set(_marks(bases))
        for aspect, trigger in _ASPECTS.items():
            js = list(aspect_judgments(pid, aspect, jan1))
            values = {bool(j["value"]["applies"]) for j in js}
            if len(values) == 1:
                ids += [j["id"] for j in js]
                states |= _marks(js)
                hit |= values.pop()
            elif js or (trigger is not None and any(r["attributes"]["basis"] == trigger for r in bases)):
                miss.append(
                    Split(
                        id=f"判断:翌年1月1日の障害の程度:{pid}:{aspect}:{ctx.year}",
                        means=Means.JUDGMENT,
                        target={"person": pid, "on": jan1.isoformat(), "aspect": aspect, "入力": "翌年の1月1日を覆う 判断.障害の程度"},
                        candidates=("true", "false"),
                        splits_conclusion=True,
                    )
                )
        out.set(V_JAN1_DISABLED, pid, hit, ids, states, missing=miss)
        before, ids_b = _marital(idx, pid, dec31 if death is None or death > dec31 else death)
        after, ids_a = _marital(idx, pid, jan1)
        out.set(V_JAN1_MARITAL_CHANGED, pid, before != after, ids_b + ids_a)
        out.set(V_JAN1_MARRIED, pid, after[0] and not after[1] or after[4], ids_a)


__all__ = ["VARIABLES_WRITTEN", "V_JAN1_DISABLED", "V_JAN1_MARITAL_CHANGED", "V_JAN1_MARRIED", "write"]
