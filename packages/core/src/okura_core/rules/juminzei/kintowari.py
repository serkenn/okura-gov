"""段階評価の段「住民税の均等割」（D23 K1、SCOPE §6-3）：均等割の軽減（第311条）と家屋敷課税の均等割（第294条第1項第2号）。

どちらも人をまたぐ値（扶養の判定・配偶者が住所地で課税されるか）と注入データで決まるので、全員の値をまず計算し、その値から段が入力を書く。

- 第311条（市町村民税だけ。docs/public-sources/20261109_round2_juminzei-tax-law-text.md §13）：市町村は、
  第1号 納税義務者自身が、均等割を納付する義務がある同一生計配偶者又は扶養親族（16歳未満の者と控除対象扶養親族に限る）である場合、
  第2号 第1号に当たる者を2人以上有する場合に、条例で定めるところにより均等割の額を軽減できる。軽減の有無と額は注入データ 住民税.均等割の軽減
  （住所の市町村、賦課期日。候補を持たない）。第1号・第2号に当たる人だけが注入データを読み、未注入ならその人の均等割の額が未確定になる。
- 家屋敷課税（docs/hypotheses/20261109_round3_juminzei-extra-model.md H1・H2）：住所のない市町村ごとに、その市町村・道府県の均等割の税率と
  均等割の非課税の基準（第295条第1項・第3項。施行地に住所を有する者に限る）で課すかを決め、市町村ごとに足す（第24条第7項：道府県民税の均等割も
  市町村ごと）。確定金額は市町村民税・道府県民税ごとに百円未満を切り捨てる（第20条の4の2第3項）。
  単身赴任者の家族の住宅の運用の型 B（注入データ 住民税.家屋敷課税の運用。候補：型 A・型 B）では、その市町村に住所を有する配偶者が住所地として
  課税されている（住所地の均等割を課される）なら課さない。
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from ...registry import StageContext, StageOutput, StageValue, injection_key
from ...result import Means, Split
from . import calc
from .inputs import (
    P_KEIGEN,
    P_KINTO,
    P_UNYO,
    UNYO_B,
    exemption_amounts,
    domicile_on,
    issuer_code,
    spouse_at_home,
    yashiki_hits,
)

STAGE = "住民税の均等割"

R_LEVY = "住民税_住所地の均等割を課すか"
R_COUNTED = "住民税_非課税の判定で数える扶養親族か"
R_CLAIMANT = "住民税_扶養親族等の納税義務者"  # 住民税の割当て（段 住民税の扶養の割当て。2026-11-12：以前は所得税の割当て）
R_SPOUSE = "住民税_同一生計配偶者に当たるか"
R_RATE = "住民税_市町村民税の均等割の税率"
R_TOTAL = "住民税_合計所得金額"
R_COUNT = "住民税_同一生計配偶者及び扶養親族の数"
R_295 = "住民税_第295条第1項の非課税に当たるか"
READS = (R_LEVY, R_COUNTED, R_CLAIMANT, R_SPOUSE, R_RATE, R_TOTAL, R_COUNT, R_295)

W_RATE = "住民税_軽減後の市町村民税の均等割の税率"
W_YASHIKI = "住民税_家屋敷課税の均等割の額"
WRITES = (W_RATE, W_YASHIKI)


def _split(sid: str, means: Means, target: dict[str, Any]) -> Split:
    return Split(id=sid, means=means, target=target, candidates=(), splits_conclusion=True)


def first_and_second(ctx: StageContext, on: _dt.date) -> tuple[dict[str, bool], dict[str, bool], dict[str, list[StageValue]]]:
    """人 → 第311条第1号に当たるか・第2号に当たるか、と判定に使った値（人ごとの uses）。"""
    persons = list(ctx.persons)
    alive = set(persons)
    levy = {p: ctx.value(R_LEVY, p) for p in persons}
    counted = {p: ctx.value(R_COUNTED, p) for p in persons}
    claimant = {p: ctx.value(R_CLAIMANT, p) for p in persons}
    spouse_flag = {p: ctx.value(R_SPOUSE, p) for p in persons}
    spouses = {p: sorted(s.other for s in ctx.relations.spouses(p, on) if s.other in alive) for p in persons}
    uses: dict[str, list[StageValue]] = {p: [] for p in persons}
    first: dict[str, bool] = {}
    for x in persons:
        # x が、生計を一にする配偶者 y の同一生計配偶者である（y から見た配偶者が同一生計配偶者：所得税.同一生計配偶者に当たるか）
        as_spouse = [y for y in spouses[x] if bool(spouse_flag[y].value)]
        first[x] = bool(levy[x].value) and (bool(counted[x].value) or bool(as_spouse))
        uses[x] += [levy[x], counted[x], *(spouse_flag[y] for y in as_spouse)]
    second: dict[str, bool] = {}
    for x in persons:
        mine = {z for z in persons if z != x and claimant[z].value == x and first[z]}
        if bool(spouse_flag[x].value):
            mine |= {y for y in spouses[x] if first[y]}
        second[x] = len(mine) >= 2
        uses[x] += [spouse_flag[x], *(claimant[z] for z in persons if claimant[z].value == x)]
        for z in mine:
            uses[x] += [levy[z], counted[z]]
    return first, second, uses


def _reduction(ctx: StageContext, out: StageOutput, jan1: _dt.date) -> None:
    first, second, uses = first_and_second(ctx, jan1)
    for x in ctx.persons:
        rate = ctx.value(R_RATE, x)
        used = [*uses[x], rate]
        if not (first[x] or second[x]):
            out.set(W_RATE, x, int(rate.value), uses=used)
            continue
        home = domicile_on(ctx, x, jan1, ctx.window("住民税", "年度").time.value).code  # type: ignore[union-attr]
        d = ctx.injection(P_KEIGEN, injection_key("municipality", home, jan1))
        amount, lacking = calc.reduced_per_capita(int(rate.value), first[x], second[x], d.value)
        miss = list(d.missing)
        if lacking is not None:
            miss.append(
                _split(
                    f"注入:住民税.均等割の軽減:{home}:{x}",
                    Means.INJECTION,
                    {"注入点": P_KEIGEN, "団体": {"kind": "municipality", "code": home}, "person": x, "欄": lacking},
                )
            )
        out.set(W_RATE, x, amount, d.record_ids, d.states, uses=used, basis=d.basis, missing=miss)


def _yashiki(ctx: StageContext, out: StageOutput, jan1: _dt.date, dec31: _dt.date, fiscal: int) -> None:
    p = ctx.parameters.住民税
    unit = int(p.税率.端数.確定金額の単位)
    for x in ctx.persons:
        home = domicile_on(ctx, x, jan1, fiscal).code
        h = yashiki_hits(ctx, x, home, jan1, fiscal)
        if not h.by_municipality:
            out.set(W_YASHIKI, x, 0, h.record_ids, h.states, uses=[])
            continue
        total_v = ctx.value(R_TOTAL, x)
        count_v = ctx.value(R_COUNT, x)
        exempt_v = ctx.value(R_295, x)
        used: list[StageValue] = [total_v, count_v, exempt_v]
        ids, states, basis, miss = list(h.record_ids), set(h.states), [], []
        amount = 0
        fixed = int(p.非課税.均等割.定額)
        for c in h.by_municipality:
            rates = [ctx.injection(P_KINTO, injection_key(kind, issuer_code(kind, c), jan1)) for kind in ("municipality", "prefecture")]
            base, add, e_ids, e_states, e_basis = exemption_amounts(ctx, c, jan1, dec31, p)
            for d in rates:
                ids += d.record_ids
                states |= set(d.states)
                basis += list(d.basis)
                miss += list(d.missing)
            ids += e_ids
            states |= set(e_states)
            basis += list(e_basis)
            if home:
                line = calc.exemption_line(int(count_v.value), base, fixed, add)
                if bool(exempt_v.value) or int(total_v.value) <= line:
                    continue  # 第295条第1項・第3項（施行地に住所を有する者に限る）
            spouses = spouse_at_home(ctx, x, c, jan1, fiscal)
            if spouses:
                t = ctx.injection(P_UNYO, injection_key("municipality", c, jan1))
                ids += t.record_ids
                states |= set(t.states)
                basis += list(t.basis)
                levied = [ctx.value(R_LEVY, s) for s in spouses]
                used += levied
                if t.value is not None and t.value.get("単身赴任者の家族の住宅") == UNYO_B and any(bool(v.value) for v in levied):
                    continue  # 型 B：その市町村に住む配偶者が住所地として課税されている
            amount += sum(calc.floor_unit(0 if d.value is None else int(d.value["税率"]), unit) for d in rates)
        out.set(W_YASHIKI, x, amount, ids, states, uses=used, basis=basis, missing=miss)


def run(ctx: StageContext) -> StageOutput:
    out = StageOutput()
    w = ctx.window("住民税", "年度")
    if w is None:
        for x in ctx.persons:
            out.set(W_RATE, x, 0, uses=[])
            out.set(W_YASHIKI, x, 0, uses=[])
        return out
    jan1, dec31 = w.date("賦課期日"), w.date("前年の12月31日")
    _reduction(ctx, out, jan1)
    _yashiki(ctx, out, jan1, dec31, w.time.value)
    return out


__all__ = ["READS", "STAGE", "WRITES", "first_and_second", "run"]
