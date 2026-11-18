"""規則モジュール personal_deductions の計算の後の対象外の検出（RuleModule.checks）。

材料が中間表現にないために、式の値（途中の変数・出力）を信じられない人を対象外にする（依存する値へ伝わる）：
- 特別障害者に当たるか：程度の記載のない根拠（級のない手帳・項症のない戦傷病者手帳・程度のない市町村長等の認定・程度のない申請）。
  ほかの根拠で既に特別障害者に当たる人は、程度が分からなくても結論が変わらないので止めない。理由に入力すれば決まる欄を書く。
- 学生に当たるか：専修学校・各種学校・認定職業訓練の在学で、設置者・課程の証明の欄がない（入力すれば決まる）。
- 年の中途で死亡した人の、親族に関する控除：親族の合計所得金額は死亡の時の現況で見積もる（所基通85−1(2)）。
  見積り.親族の合計所得金額 のない親族がいるとき（入力すれば決まる）。
- 年の途中に非居住者の期間がある居住者自身の所得控除：非居住者の期間の計算（所法102・165）は範囲外（D20）。
- 寡婦に当たるか：相手が「夫」かは相手の法令上の性別（legal_sex）で決める（inputs.py）。性別の記録がない婚姻で寡婦に当たると判定された人だけ、
  判定の値を出さない（性別は要件を狭める向きにだけ効くので、当たらないと判定された人は性別によらず当たらない）。
- 寡婦・ひとり親に当たるか：判定の時の住民票の記録（事実婚の続柄の記載）を確かめられない人のうち、当たると判定された人だけ値を出さない
  （記載は要件を狭める向きにだけ効く。婚姻をしている人などは記載によらず当たらないので止めない：2026-11-11 の過剰な対象外を直した）。
- 非居住者（国外居住親族）の所得控除：非居住者本人の申告は範囲外（D20）。所得の記録のない非居住者は居住者の扶養親族等の判定にだけ使うので
  （inputs.py）、その人自身の所得控除の額を対象外にする（所得控除の合計・税額へ伝わる）。判定の変数（扶養親族に当たるか・1人分の額）は止めない
  （止めると扶養所属のグループを通して申告者の控除へ伝わる）。
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable

from ...registry import CheckContext, Exclusion, heads
from .allocation import J_SEIKEI, K_EST, kin_for, person_departures
from ...result import OutOfScopeCategory, OutOfScopeReason
from .ir_facts import (
    IrIndex,
    application_special,
    course_student,
    covers,
    foreign_period_ids,
    cohabitation,
    disability_bases,
    ended_marriages,
    enrollments,
    cut_date,
    judgment_date,
    kin_record_ids,
    missing_spouses,
    war_special,
)

UNKNOWN_SPECIAL_REASON = (
    "特別障害者に当たるか（所得税法施行令第10条第2項、所得税基本通達2−38）を決める程度の記載がない根拠がある。次を入力すれば決まる"
)
NON_ARTICLE1_REASON = (
    "専修学校・各種学校・認定職業訓練の在学で、政令で定める課程を履修する者か（所得税法第2条第1項第32号ロ・ハ、所得税法施行令第11条の3）を決める欄がない。"
    "次を入力すれば決まる"
)
FILER_DIED_REASON = (
    "年の中途で死亡した人の親族に関する控除は、親族の合計所得金額を死亡の時の現況で見積もる（所得税基本通達85−1(2)）。"
    "次の親族について 見積り.親族の合計所得金額（person=親族、taxpayer=死亡した人）を入力すれば決まる"
)

WIDOW_GENDER_REASON = (
    "離婚・死別の後に婚姻をしていない人で、寡婦の他の要件を満たす。相手の法令上の性別（legal_sex）の記録がなく、"
    "相手が「夫」か（所得税法第2条第1項第30号）を決められない。相手の legal_sex を入力すれば決まる"
)
NO_RESIDENT_RECORD_REASON = (
    "寡婦・ひとり親の他の要件を満たすが、判定の時の住民票の記録がなく（又は続柄の記載がなく）、事実婚の要件（所規1の3・1の4）を確かめられない。"
    "住民票の記録（resident_record の続柄）を入力すれば決まる"
)

#: 年の中途で死亡した人について対象外にする控除の額。判定の変数でなく額（人をまたがない変数）を止める：同一生計配偶者などの判定の変数を止めると、
#: 法律婚のグループの相手の控除へ人をまたいで伝わる（生存している配偶者の控除は死亡した人の所得で決まり、見積りは要らない）。
FILER_DIED_VARIABLES = (
    "所得税_配偶者控除の額",
    "所得税_配偶者特別控除の額",
    "所得税_扶養控除の額",
    "所得税_特定親族特別控除の額",
    "所得税_障害者控除の額",
    "所得税_寡婦控除の額",
    "所得税_ひとり親控除の額",
)


NON_RESIDENT_OWN_REASON = (
    "非居住者（判断.住所の所在が国外）。非居住者本人の申告（所得税法第165条）は範囲外（HANDOFF D20）。"
    "居住者の扶養親族等に当たるかの判定にだけ使う（国外居住親族：所得税法第2条第1項第34号の2ロ）"
)
NON_RESIDENT_PERIOD_OWN_REASON = (
    "この年分の判定の時は居住者だが、年の途中に非居住者の期間がある（入国の年など）。非居住者の期間の所得と税額の計算（所得税法第102条・第165条）は"
    "非居住者本人の申告として範囲外（HANDOFF D20）。居住者の扶養親族等に当たるかの判定には使う（合計所得金額は読みの分かれ目：allocation.py）"
)
#: 非居住者について対象外にする、その人自身の所得控除の額（所得控除の合計と税額へ伝わる）。判定の変数・申告者に集める1人分の額は含めない。
NON_RESIDENT_OWN_VARIABLES = FILER_DIED_VARIABLES + (
    "所得税_勤労学生控除の額",
    "所得税_基礎控除の額",
    "所得税_雑損控除の額",
    "所得税_医療費控除の額",
    "所得税_セルフメディケーション税制による医療費控除の額",
    "所得税_社会保険料控除の額",
    "所得税_小規模企業共済等掛金控除の額",
    "所得税_生命保険料控除の額",
    "所得税_地震保険料控除の額",
    "所得税_寄附金控除の額",
)


def _not_implemented(reason: str, ids: Iterable[str]) -> OutOfScopeReason:
    return OutOfScopeReason(OutOfScopeCategory.NOT_IMPLEMENTED, reason, tuple(sorted(set(ids))))


def _unknown_special(bases: list, age: int, municipal_min_age: int, pending: bool) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """程度の記載がなく、特別障害者に当たるかを決められない根拠の記録の ID と、入力すれば決まる欄。

    市町村長等の認定は年齢の下限（所令10①七）未満なら当たらないので数えない。申請（所基通2−38）は申請中で障害が明らかと判断された人だけ数える。
    """
    ids: list[str] = []
    needs: set[str] = set()
    for r in bases:
        a = r["attributes"]
        b = a["basis"]
        if b in ("physical_disability_certificate", "mental_disability_certificate") and "grade" not in a:
            ids.append(r["id"])
            needs.add("grade（手帳の級・等級）")
        elif b == "war_injury_certificate" and war_special(r) is None:
            ids.append(r["id"])
            needs.add("war_injury_class（戦傷病者手帳の項症・款症）")
        elif b == "municipal_certification" and age >= municipal_min_age and "certified_severity" not in a:
            ids.append(r["id"])
            needs.add("certified_severity（市町村長等の認定の程度）")
        elif b == "application" and pending and application_special(r, 2) is None:
            ids.append(r["id"])
            needs.add("申請の grade（身体障害者手帳の級）又は war_injury_class")
    return tuple(ids), tuple(sorted(needs))


def _widow_sex_unknown_ids(idx: IrIndex, pid: str, t) -> tuple[str, ...]:
    """寡婦に当たると判定された人で、「夫」と決まらない婚姻の記録の ID（決まれば空）。

    死別（第30号ロ）の婚姻で相手が male と決まっていれば、ロ の要件（(2)(3) は寡婦に当たる判定で満たしている）で寡婦に当たる。
    それ以外で、相手の性別の記録がない婚姻があれば、その婚姻だけで要件を満たしたかもしれないので決められない（安全側）。
    """
    ended = [e for e in ended_marriages(idx, pid, t) if e.husband is not False]
    missing = [m for m in missing_spouses(idx, pid, t) if m.applies is True and m.husband is not False]
    if any(e.husband is True and not e.divorced for e in ended) or any(m.husband is True for m in missing):
        return ()
    if all(e.husband is True for e in ended) and not missing:
        return ()
    return tuple(e.record["id"] for e in ended if e.husband is None) + tuple(m.record["id"] for m in missing if m.husband is None)


def _missing_estimates(idx: IrIndex, ctx: CheckContext, c: str, t: _dt.date) -> tuple[str, ...]:
    """年の中途で死亡・出国した c の親族（里子などを含む）で、生計を一にしないと判断されておらず、見積り.親族の合計所得金額 がない人。t は判定の時。"""
    estimated = {
        j["subject"]["person"]
        for j in heads(ctx.ir["judgments"])
        if j["kind"] == K_EST and j["subject"]["taxpayer"] == c and (j.get("when") or {}).get("tax_year", ctx.year) == ctx.year
    }
    out: list[str] = []
    for d in ctx.persons:
        if d == c or d in estimated:
            continue
        if kin_for(idx, c, d, t).relative is False and kin_for(idx, d, c, t).relative is False:
            continue
        lives = [
            j["value"]
            for j in heads(ctx.ir["judgments"])
            if j["kind"] == J_SEIKEI and {j["subject"]["person"], j["subject"]["other_person"]} == {c, d} and covers(j.get("when"), t)
        ]
        if lives and all(v is False for v in lives):
            continue
        out.append(d)
    return tuple(out)


def check_personal(ctx: CheckContext) -> Iterable[Exclusion]:
    out: list[Exclusion] = []
    special = ctx.calc("所得税_特別障害者に当たるか")
    pending = ctx.calc("所得税_手帳の申請中で障害が明らかか")
    student = ctx.calc("所得税_学校教育法第1条の学校の学生等か")
    widow = ctx.calc("所得税_寡婦に当たるか")
    single = ctx.calc("所得税_ひとり親に当たるか")
    wages = ctx.calc("所得税_給与等の収入金額")
    adj_base = int(ctx.parameters.所得税.所得金額調整控除.第1項の給与等の収入金額の基準)
    age = ctx.calc("所得税_年齢")
    municipal_min_age = int(ctx.parameters.所得税.障害者.市町村長等の認定の年齢の下限)
    resident = ctx.calc("所得税_居住者か")
    idx = IrIndex(ctx.ir)
    departures = person_departures(ctx)
    for i, pid in enumerate(ctx.persons):
        death = idx.death(pid)
        t = judgment_date(ctx.year, cut_date(death, departures[pid]))  # 死亡・出国の時（所法85①③。PD-05）
        if not resident[i]:
            reason = OutOfScopeReason(OutOfScopeCategory.OUT_OF_RANGE, NON_RESIDENT_OWN_REASON, tuple(r["id"] for r in idx.of("abroad_stay", pid)))
            out += [Exclusion(pid, reason, v) for v in NON_RESIDENT_OWN_VARIABLES]
        elif foreign := foreign_period_ids(ctx.ir, pid, ctx.year, t):
            reason = OutOfScopeReason(OutOfScopeCategory.OUT_OF_RANGE, NON_RESIDENT_PERIOD_OWN_REASON, foreign)
            out += [Exclusion(pid, reason, v) for v in NON_RESIDENT_OWN_VARIABLES]
        if not special[i]:
            ids, needs = _unknown_special(disability_bases(idx, pid, t), int(age[i]), municipal_min_age, bool(pending[i]))
            if ids:
                out.append(Exclusion(pid, _not_implemented(UNKNOWN_SPECIAL_REASON + "：" + "・".join(needs), ids), "所得税_特別障害者に当たるか"))
        if not student[i]:
            unknown = [(r["id"], n) for r in enrollments(idx, pid, t) if (c := course_student(r))[0] is None and (n := c[1])]
            if unknown:
                reason = NON_ARTICLE1_REASON + "：" + "・".join(sorted({n for _, n in unknown}))
                out.append(Exclusion(pid, _not_implemented(reason, [i for i, _ in unknown]), "所得税_学生に当たるか"))
        in_year = (death is not None and death.year == ctx.year) or departures[pid] is not None  # 所基通85−1(2)：死亡・出国
        missing_est = _missing_estimates(idx, ctx, pid, t) if in_year else ()
        if missing_est:
            reason = _not_implemented(FILER_DIED_REASON + "：" + "・".join(missing_est), kin_record_ids(idx, pid))
            out += [Exclusion(pid, reason, v) for v in FILER_DIED_VARIABLES]
            if int(wages[i]) > adj_base:  # 第1項は親族の所得の見積りに依存する（合計所得金額へ伝わる）
                out.append(Exclusion(pid, reason, "所得税_所得金額調整控除の対象の親族等を有するか"))
        if widow[i]:
            ids = _widow_sex_unknown_ids(idx, pid, t)
            if ids:
                out.append(Exclusion(pid, _not_implemented(WIDOW_GENDER_REASON, ids), "所得税_寡婦に当たるか"))
        if resident[i] and (widow[i] or single[i]):
            c = cohabitation(idx, pid, t)
            if c.unknown:  # 記載があれば寡婦・ひとり親のどちらにも当たらない（第30号(3)・第31号ハ）。記載のない人だけが当たる
                reason = _not_implemented(NO_RESIDENT_RECORD_REASON, c.ids)
                # ひとり親に当たる人は、記載があってもなくても寡婦に当たらない（寡婦は「ひとり親に該当しないもの」）ので、当たると判定した方だけを止める
                out.append(Exclusion(pid, reason, "所得税_ひとり親に当たるか" if single[i] else "所得税_寡婦に当たるか"))
    return out
