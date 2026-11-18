"""規則モジュール other_deductions：年齢23歳未満の扶養親族を有するか（租税特別措置法第41条の15の5）を決める段階（D23 K1）。

- 第1項：「年齢二十三歳未満の扶養親族」（所得税法第2条第1項第34号の扶養親族）を有する居住者の、令和8年分・令和9年分の生命保険料控除の読替え。
- 第2項：判定はその年の12月31日（居住者の年の中途の死亡・出国のときはその時）の現況。判定に係る者がその当時既に死亡しているときは、その死亡の時の現況。
  判定の日は、その人の死亡日があればその日と12月31日の早い方（出国の時は扱わない）。
- 扶養親族の要件：親族（kinship.py）、生計を一にする（判断.生計を一にする の年分の1か所 "<支払者>:<親族>"）、合計所得金額の要件
  （personal_deductions の 所得税_扶養親族の合計所得金額要件）、青色事業専従者等でないこと（payroll_paid の family_employee_salary だけを見る）。
  扶養所属のグループを使わない（夫婦の両方が同じ子について有しうる：docs/public-sources/20261109_round2_hoken-kifu-nta-soumu.md §1.6）。
- 親族と導けない若い家族がいて、ほかに有する扶養親族が見つからない支払者は対象外（黙って false にしない：README §4）。
"""

from __future__ import annotations

import datetime as _dt

from ...registry import DecisionSlot, StageContext, StageOutput, StageSpec, StageValue, YearContext
from ...result import OutOfScopeCategory, OutOfScopeReason, State
from .basis import LIFE_SPECIAL_RULE
from .facts import _pair, J_LIFE, J_SEIKEI, heads_for, on_year, year_end
from .insurance import NEW_CONTRACT_FROM
from .kinship import kinship, relation_index

V_HAS = "所得税_年齢23歳未満の扶養親族を有するか"
V_INCOME_OK = "所得税_扶養親族の合計所得金額要件"
STAGE_NAME = "生命保険料控除の特例の扶養親族"

R_KIN = "年齢23歳未満の家族を支払者の親族と記録から導けない（関係の書き忘れと区別できない）ので、措法第41条の15の5 の扶養親族を有するかを決めない"


def special_year(ctx: YearContext) -> bool:
    """その年分に措法第41条の15の5 を当てうるか（パラメータ 適用）。パラメータの窓口がない（evaluate の外の）ときは当てない。"""
    try:
        return bool(ctx.parameters.所得税.生命保険料控除.措法第41条の15の5.適用)
    except ValueError:
        return False


def payers(ctx: YearContext) -> list[str]:
    """特例を当てうる人：その年中に平成24年1月1日以後の契約の生命保険料（一般の区分になりうるもの）を支払った人。"""
    contracts = {r["id"]: r for r in ctx.records("insurance_contract")}
    out = set()
    for r in ctx.records("insurance_payment"):
        if on_year(r) != ctx.year or r["attributes"].get("flow") != "premium":
            continue
        c = contracts.get(r["attributes"]["contract_id"])
        if c is None or (c["attributes"]["product_type"] != "life" and not heads_for(ctx, J_LIFE, "contract_id", c["id"])):
            continue  # 判断.生命保険の区分で一般の区分になりうる契約は含める
        if _dt.date.fromisoformat(c["attributes"]["concluded_on"]) >= NEW_CONTRACT_FROM:
            out.add(r["roles"]["payer"])
    return sorted(out & set(ctx.persons))


def judgment_day(ctx: YearContext, a: str, b: str) -> _dt.date:
    """第2項の判定の日：12月31日。支払者 a が年の中途で死亡すればその時、b がその前に死亡していれば b の死亡の時。"""
    day = year_end(ctx)
    for pid in (a, b):
        death = ctx.death_on(pid)
        if death is not None and death < day:
            day = death
    return day


def age_at_end_of(birth: _dt.date, day: _dt.date) -> int:
    """判定の日の終了時までに達した年齢（年齢計算ニ関スル法律・民法第143条）。翌日の暦の上の満年齢と同じ（personal_deductions の年齢と同じ考え方）。"""
    nxt = day + _dt.timedelta(days=1)
    return nxt.year - birth.year - (1 if (nxt.month, nxt.day) < (birth.month, birth.day) else 0)


def candidates(ctx: YearContext, a: str) -> list[str]:
    """支払者 a の特例の対象になりうる人（判定の日に年齢の上限未満の家族で a 以外の人）。special_year が真のときだけ呼ぶ。"""
    limit = int(ctx.parameters.所得税.生命保険料控除.措法第41条の15の5.扶養親族の年齢の上限)
    return [b for b in ctx.persons if b != a and age_at_end_of(ctx.birth_on(b), judgment_day(ctx, a, b)) < limit]


def seikei_slots(ctx: YearContext) -> list[DecisionSlot]:
    """親族と導ける候補の、年分の 判断.生計を一にする の1か所（personal_deductions と同じ key："<person>:<other_person>"）。"""
    if not special_year(ctx):
        return []
    idx = relation_index(ctx.ir)
    out: list[DecisionSlot] = []
    for a in payers(ctx):
        for b in candidates(ctx, a):
            if kinship(idx, a, b, judgment_day(ctx, a, b)).relative is not True:
                continue
            out.append(
                DecisionSlot(
                    key=f"{a}:{b}",
                    target={"person": a, "other_person": b, "tax_year": ctx.year, "purpose": "年齢23歳未満の扶養親族（租税特別措置法第41条の15の5）"},
                    matches=lambda r, a=a, b=b: _pair(r, a, b),
                    persons=(a, b),
                )
            )
    return out


def _family_employee(ctx: YearContext, a: str, b: str) -> bool:
    return any(
        r["roles"].get("employer") == a
        and r["roles"].get("recipient") == b
        and r["attributes"]["pay_type"] == "family_employee_salary"
        and on_year(r) == ctx.year
        for r in ctx.records("payroll_paid")
    )


def run(ctx: StageContext) -> StageOutput:
    out = StageOutput()
    relevant = set(payers(ctx)) if special_year(ctx) else set()
    idx = relation_index(ctx.ir)
    for a in ctx.persons:
        if a not in relevant:
            out.set(V_HAS, a, False, uses=())
            continue
        has = False
        ids: list[str] = []
        states: set[State] = set()
        uses: list[StageValue] = []
        unknown: list[str] = []
        for b in candidates(ctx, a):
            k = kinship(idx, a, b, judgment_day(ctx, a, b))
            if k.relative is not True:
                unknown.append(b)
                continue
            ids += list(k.record_ids)
            states |= set(k.states)
            dec = ctx.decision(J_SEIKEI, f"{a}:{b}")
            ids += list(dec.record_ids)
            states |= set(dec.states)
            if not dec.value or _family_employee(ctx, a, b):
                continue
            v = ctx.value(V_INCOME_OK, b)
            uses.append(v)
            if bool(v.value):
                has = True
        if not has and unknown:
            out.exclude(a, OutOfScopeReason(OutOfScopeCategory.NOT_IMPLEMENTED, R_KIN), V_HAS)
        out.set(V_HAS, a, has, ids, states, uses=uses)
    return out


STAGE = StageSpec(
    name=STAGE_NAME,
    title="年齢23歳未満の扶養親族を有するか（租税特別措置法第41条の15の5：扶養親族の合計所得金額の要件を前の段から読む）",
    reads=(V_INCOME_OK,),
    writes=(V_HAS,),
    run=run,
    basis=(LIFE_SPECIAL_RULE,),
)

__all__ = ["STAGE", "STAGE_NAME", "age_at_end_of", "seikei_slots", "special_year"]
