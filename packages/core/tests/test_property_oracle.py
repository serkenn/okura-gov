"""性質のテスト（D15 ④）：実装を読まずに docs の一次情報だけから組んだ検算（オラクル）と evaluate を、ランダムな架空の家庭で比べる。

反証役のレビュー（2026-11-11）で足した。目的は「黙って間違った値を出す」誤りを見つけること。evaluate が値を断定したとき、
オラクルの値と違えば失敗にする（未確定・対象外は値を出していないので比べない。件数だけを数える）。

オラクルの根拠（どれも docs の原文の節。実装のパラメータ・コードは読まない）：
  [K28]  所得税法第28条第3項（令和7年分・令和8年分の版）：scripts/results/IMPL2_kyuyo-jiki_egov/ho_2025-12-31.txt・ho_2026-12-31.txt の Num=28
         （docs/measurements/20261111_impl-research_kyuyo-jiki-fetch-and-checks.md の取得の記録）
  [B5]   別表第五の構造（区分の下限で第28条第3項を評価、4,000円刻み・「◯円未満は0」・660万円以上は1円未満切捨て）：
         docs/measurements/20261109_impl-prep_kyuyo-beppyo5.md §3・§3.1、docs/public-sources/20261109_impl-prep_kyuyo-sources.md §1.2
  [S294] 措法第29条の4第2項（令和8年分）：docs/public-sources/20261109_impl-prep_kyuyo-sources.md §2.1
  [ADJ]  所得金額調整控除の第1項（措法41の3の11①、1円未満切上げは TA1411）：docs/public-sources/20261109_round2_gaps-sources.md §3.1 と 128行目の TA の引用
  [IT2]  扶養親族・同一生計配偶者・勤労学生の所得要件、基礎控除の加算（措法41の16の2）、扶養控除：docs/public-sources/20261109_R1-laws_income-tax.md §2
  [IT3]  特定親族特別控除（所法84の2）：docs/public-sources/20261109_R1-laws_income-tax.md §3
  [B86]  基礎控除の2,350万円超の段階（所法86①）：docs/public-sources/20261109_round2_gaps-sources.md §4.1
  [SP]   配偶者控除・配偶者特別控除（所法83・83の2）：docs/public-sources/20261109_round2_spouse-laws-and-sources.md §1.1〜§1.3
  [EA]   老人扶養親族・同居老親等（所法84①・措法41の16①）：docs/public-sources/20261109_round2_elderly-abroad-laws.md §1.1・§1.2・§2.1
  [AGE]  年齢（12月31日の終了時。1月1日生まれは1つ多い）：docs/public-sources/20261109_impl-prep_misc-age-kinship-attribution.md §1.3
  [ATR]  扶養の所属（所令218・219②：記載がなければ配偶者、次に所得の合計額が最も大きい人）：同 §3.2
  [ZG]   税率・課税総所得金額の千円未満切捨て・復興特別所得税 2.1%・申告納税額の百円未満切捨て・還付：
         docs/public-sources/20261109_impl-prep_zeigaku-tax-calc.md §1.2・§2・§3.1・§3.3・§10
  [NK]   公的年金等控除額（所法35④、65歳以上の最低額 措法41の15の3①④）：docs/public-sources/20261109_round2b_nenkin-laws-and-guidance.md §2.1・§2.2
  [SI]   社会保険料控除（所法74①）：docs/public-sources/20261109_impl-prep_zeigaku-tax-calc.md §7.1
  [ZG6]  勤労学生（所法2①三十二イ、令和7年分85万円・令和8年分89万円、控除額27万円）：同 §6.1、[IT2]
  [HO]   ひとり親（所法2①三十一、子の総所得金額等 令和7年分58万円・令和8年分62万円、本人の合計所得金額500万円、控除額35万円）：
         docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md §1.2・§1.4
  [FK]   令和8年分の復興特別所得税額の1円未満：令和7年分と同じく切捨て（tax の担当の読み。令和8年分の手引きは未公表で、根拠の弱い値。
         ここで比べるのは「2.1% を掛けて1円未満を切り捨てた額」。切捨て以外の読みに変われば、このテストも直す）

テストのデータはどれも架空の家庭（個人の情報を使わない）。乱数の種は固定（決定的）。
"""

from __future__ import annotations

import datetime as _dt
import random
import unittest
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

from okura_core import evaluate
from okura_core.money import YenRange
from okura_core.result import EvaluationResult, State, TimeKey, YenAmount

from .support import make_ir, make_query, system

# ---------------------------------------------------------------------------
# オラクル（docs の一次情報だけから）
# ---------------------------------------------------------------------------

MAN = 10_000


def _floor(x: Fraction) -> int:
    return x.numerator // x.denominator


def _ceil(x: Fraction) -> int:
    return -((-x.numerator) // x.denominator)


def kyuyo_kojo(year: int, s: int) -> Fraction:
    """所得税法第28条第3項の給与所得控除額（[K28]。令和8年分は措法29の4①の74万円を別に扱う）。"""
    if year == 2025:
        if s <= 190 * MAN:
            return Fraction(65 * MAN)
        if s <= 360 * MAN:
            return 65 * MAN + Fraction(s - 190 * MAN) * Fraction(30, 100)
    else:
        if s <= 360 * MAN:
            return max(Fraction(69 * MAN), 8 * MAN + Fraction(s) * Fraction(30, 100))
    if s <= 660 * MAN:
        return 116 * MAN + Fraction(s - 360 * MAN) * Fraction(20, 100)
    if s <= 850 * MAN:
        return 176 * MAN + Fraction(s - 660 * MAN) * Fraction(10, 100)
    return Fraction(195 * MAN)


def kyuyo_shotoku(year: int, s: int) -> int:
    """給与所得の金額（[K28]・[B5]・[S294]）。"""
    if year == 2026 and 691_000 <= s < 2_200_000:
        # [S294] 措法29の4②（令和8年分）
        if s < 741_000:
            return 0
        if s < 2_191_000:
            return s - 740_000
        if s < 2_193_000:
            return 1_451_000
        if s < 2_196_000:
            return 1_453_000
        return 1_456_000
    if s >= 660 * MAN:
        # [B5] 備考：660万円以上は1円未満切捨て（式の区分。第28条第3項そのもの）
        return _floor(Fraction(s) - kyuyo_kojo(year, s))
    # 別表第五（[B5]）：「◯円未満は0」→ 式の区分（収入−控除の最低額）→ 4,000円刻み（区分の下限で第28条第3項を評価）
    zero_below, flat_until, flat_kojo, step_from = (
        (651_000, 1_900_000, 650_000, 1_900_000) if year == 2025 else (691_000, 2_026_000, 690_000, 2_028_000)
    )
    if s < zero_below:
        return 0
    if s < flat_until:
        return s - flat_kojo
    if year == 2026 and s < step_from:
        lower = 2_026_000  # [B5] 令和8年分の [2,026,000, 2,028,000) は 2,000円の区分
    else:
        lower = step_from + (s - step_from) // 4_000 * 4_000
    return _floor(Fraction(lower) - kyuyo_kojo(year, lower))


def fuyo_limit(year: int) -> int:
    return 58 * MAN if year == 2025 else 62 * MAN  # [IT2]


def kiso(year: int, total: int) -> int:
    """基礎控除の額（[IT2]・[B86]）。"""
    first = 58 * MAN if year == 2025 else 62 * MAN
    if total > 2_500 * MAN:
        return 0
    if total > 2_450 * MAN:
        return 16 * MAN
    if total > 2_400 * MAN:
        return 32 * MAN
    if total > 2_350 * MAN:
        return 48 * MAN
    if total > 655 * MAN:
        return first
    if year == 2025:
        add = 37 * MAN if total <= 132 * MAN else 30 * MAN if total <= 336 * MAN else 10 * MAN if total <= 489 * MAN else 5 * MAN
    else:
        add = 42 * MAN if total <= 489 * MAN else 5 * MAN
    return first + add


def _largest_form(e: int, step: int, minus: int) -> int:
    """「step の整数倍 − minus」の形の金額で e 以下のもののうち最も多いもの（e がその形ならそのまま）。"""
    return (e + minus) // step * step - minus


def haigusha(total_self: int, total_spouse: int, old: bool, year: int) -> tuple[int, int]:
    """(配偶者控除の額, 配偶者特別控除の額)（[SP]）。生計を一にし、青色事業専従者等でない配偶者。"""
    if total_self > 1_000 * MAN:
        return 0, 0
    if total_spouse <= fuyo_limit(year):
        if total_self <= 900 * MAN:
            return (48 if old else 38) * MAN, 0
        if total_self <= 950 * MAN:
            return (32 if old else 26) * MAN, 0
        return (16 if old else 13) * MAN, 0
    if total_spouse > 133 * MAN:
        return 0, 0
    if total_spouse <= 95 * MAN:
        base = 38 * MAN
    elif total_spouse <= 130 * MAN:
        base = 38 * MAN - _largest_form(total_spouse - 930_001, 50_000, 30_000)
    else:
        base = 3 * MAN
    if total_self <= 900 * MAN:
        return 0, base
    frac = Fraction(2, 3) if total_self <= 950 * MAN else Fraction(1, 3)
    return 0, _ceil(base * frac / MAN) * MAN


def tokutei_shinzoku(total: int) -> int:
    """特定親族特別控除の額（[IT3]）。合計所得金額が扶養親族の上限を超え123万円以下の19歳以上23歳未満の親族。"""
    if total <= 85 * MAN:
        return 63 * MAN
    if total <= 115 * MAN:
        return 63 * MAN - _largest_form(2 * (total - 840_001), 100_000, 80_000)
    if total <= 120 * MAN:
        return 6 * MAN
    return 3 * MAN


def zeigaku(taxable: int) -> int:
    """課税総所得金額に対する税額（[ZG] 所法89①の超過累進）。"""
    brackets = [(195 * MAN, 5), (330 * MAN, 10), (695 * MAN, 20), (900 * MAN, 23), (1_800 * MAN, 33), (4_000 * MAN, 40), (None, 45)]
    tax = Fraction(0)
    lower = 0
    for upper, rate in brackets:
        if taxable <= lower:
            break
        part = (taxable if upper is None else min(taxable, upper)) - lower
        tax += Fraction(part * rate, 100)
        if upper is None:
            break
        lower = upper
    return _floor(tax)


def age_at_end(birth: _dt.date, year: int) -> int:
    """12月31日の終了時の年齢（[AGE]）。"""
    return year - birth.year + (1 if (birth.month, birth.day) == (1, 1) else 0)


def nenkin_zatsu(gross: int, age: int, other_total: int) -> int:
    """公的年金等に係る雑所得の金額（[NK] 所法35④、措法41の15の3①④。収入は100円の倍数なので1円未満は出ない）。"""
    r = max(0, gross - 50 * MAN)
    if r <= 360 * MAN:
        lo = Fraction(r * 25, 100)
    elif r <= 720 * MAN:
        lo = 90 * MAN + Fraction((r - 360 * MAN) * 15, 100)
    elif r <= 950 * MAN:
        lo = 144 * MAN + Fraction((r - 720 * MAN) * 5, 100)
    else:
        lo = Fraction(1_555_000)
    if other_total <= 1_000 * MAN:
        base, minimum = 40 * MAN, (110 if age >= 65 else 60) * MAN
    elif other_total <= 2_000 * MAN:
        base, minimum = 30 * MAN, (100 if age >= 65 else 50) * MAN
    else:
        base, minimum = 20 * MAN, (90 if age >= 65 else 40) * MAN
    assert lo.denominator == 1
    return max(0, gross - max(minimum, base + int(lo)))


# ---------------------------------------------------------------------------
# 架空の家庭
# ---------------------------------------------------------------------------


@dataclass
class Member:
    pid: str
    birth: _dt.date
    salary: int
    withholding: int
    role: str  # claimant・spouse・child・grandparent
    pension: int = 0  # 公的年金等（老齢の国民年金）の収入金額。100円の倍数（率を掛けて1円未満が出ないように）
    student: bool = False  # 学校教育法第1条の学校の学生等（enrollment）
    # 社会保険料の支払：(負担すべき人, 金額)。支払った人はこの人
    social: list[tuple[str, int]] = field(default_factory=list)


@dataclass
class Family:
    year: int
    members: list[Member]
    # 生計を一にする：人の組（順序なし）→ 真偽。全部の組を書く
    seikei: dict[frozenset[str], bool] = field(default_factory=dict)
    # 同居を常況：全部の組を書く
    doukyo: dict[frozenset[str], bool] = field(default_factory=dict)

    def m(self, pid: str) -> Member:
        return next(x for x in self.members if x.pid == pid)

    def spouse_of(self, pid: str) -> str | None:
        if pid == "p-a" and any(x.pid == "p-b" for x in self.members):
            return "p-b"
        if pid == "p-b":
            return "p-a"
        return None

    def lineal_ascendants(self, pid: str) -> set[str]:
        """直系尊属（この家庭の構成：子 → 申告者・配偶者・祖父母、申告者 → 祖父母）。"""
        out: set[str] = set()
        role = self.m(pid).role
        ids = {x.pid for x in self.members}
        if role == "child":
            out |= {p for p in ("p-a", "p-b", "p-g") if p in ids}
        elif role == "claimant":
            out |= {p for p in ("p-g",) if p in ids}
        return out


def _rand_salary(rng: random.Random, lo: int, hi: int, points: tuple[int, ...] = ()) -> int:
    """境目の近くを多めに引く（1,000円単位と1円単位を混ぜる）。"""
    if points and rng.random() < 0.5:
        p = rng.choice(points)
        return max(0, p + rng.randint(-6_000, 6_000))
    v = rng.randint(lo, hi)
    return v if rng.random() < 0.3 else v // 1_000 * 1_000


def random_family(rng: random.Random, year: int, *, cap: bool = True) -> Family:
    lim_points = (
        (1_230_000, 1_500_000, 1_550_000, 1_880_000, 1_900_000, 650_000, 651_000)
        if year == 2025
        else (1_360_000, 1_590_000, 1_640_000, 1_970_000, 2_190_000, 2_200_000, 741_000, 691_000)
    )
    members: list[Member] = []
    a_birth = _dt.date(rng.randint(1950, 1990), rng.randint(1, 12), 1 if rng.random() < 0.15 else rng.randint(1, 28))
    a_points = (6_600_000, 8_500_000, 10_000_000, 10_950_000, 11_450_000, 11_950_000, 25_300_000, 25_800_000, 26_300_000, 26_800_000)
    members.append(Member("p-a", a_birth, _rand_salary(rng, 2_300_000, 15_000_000, a_points), rng.choice((0, 0, rng.randint(1, 900_000))), "claimant"))
    if rng.random() < 0.8:
        b_birth = _dt.date(rng.randint(1950, 1995), rng.randint(1, 12), rng.randint(1, 28))
        r = rng.random()
        if r < 0.25:
            sb = 0
        elif r < 0.85:
            sb = _rand_salary(rng, 0, 2_600_000, (*lim_points, 1_600_000, 2_010_000, 2_060_000, 2_160_000))
        else:
            sb = _rand_salary(rng, 2_600_000, 12_000_000)
        members.append(Member("p-b", b_birth, sb, rng.choice((0, rng.randint(1, 50_000))), "spouse"))
    for i in range(rng.randint(0, 3)):
        age = rng.randint(0, 27)
        c_birth = _dt.date(year - age, rng.randint(1, 12), 1 if rng.random() < 0.2 else rng.randint(1, 28))
        sc = 0 if rng.random() < 0.35 or age < 15 else _rand_salary(rng, 100_000, 2_500_000, lim_points)
        members.append(Member(f"p-c{i}", c_birth, sc, 0, "child"))
    if rng.random() < 0.4:
        g_birth = _dt.date(rng.randint(1930, 1962), rng.randint(1, 12), 1 if rng.random() < 0.2 else rng.randint(1, 28))
        sg = 0 if rng.random() < 0.6 else _rand_salary(rng, 100_000, 3_000_000, lim_points)
        pension = 0 if rng.random() < 0.4 else rng.choice((rng.randint(5_000, 40_000), rng.randint(16_000, 18_500), rng.randint(9_000, 12_000))) * 100
        members.append(Member("p-g", g_birth, sg, 0, "grandparent", pension=pension))
    for x in members:
        if x.role == "child" and 6 <= year - x.birth.year <= 24 and rng.random() < 0.6:
            x.student = True
        if x.role in ("claimant", "spouse") and rng.random() < 0.6:
            x.social.append((x.pid, rng.randint(1, 1_500_000)))
    adults = [x.pid for x in members if x.role == "child" and year - x.birth.year >= 21]
    if adults and rng.random() < 0.6:
        members[0].social.append((rng.choice(adults), rng.randint(100_000, 210_000)))  # 親が子の国民年金保険料を払う
    away = {x.pid for x in members if x.role == "child" and rng.random() < 0.15}  # 生計が別の子
    while True:
        fam = Family(year, list(members))
        ids = [x.pid for x in members]
        for i, p in enumerate(ids):
            for q in ids[i + 1 :]:
                roles = {fam.m(p).role, fam.m(q).role}
                # 傍系（兄弟姉妹）・姻族（配偶者と祖父母）の組は、生計を一にするを真にすることを少なくする（下の分かれ目の数を抑えるため）
                collateral = roles == {"child"} or roles == {"spouse", "grandparent"}
                fam.seikei[frozenset((p, q))] = not ({p, q} & away) and (not collateral or rng.random() < 0.25)
                fam.doukyo[frozenset((p, q))] = rng.random() < 0.6 and not ({p, q} & away)
        if not cap or attribution_combinations(fam) <= 64:
            for x in members:  # 外した人の社会保険料の支払は落とす
                x.social = [(liable, a) for liable, a in x.social if liable in ids]
            return fam
        members.pop()  # 最後の人（祖父母か末の子）を外して作り直す


def attribution_combinations(fam: Family) -> int:
    """選択.扶養の所属 の未入力の1か所の候補の直積の大きさ（扶養親族等の申告者になりうる人が2人以上の人ごと。所得を見る前に置かれる）。

    evaluate の候補の上限（64）を超える家庭は、どの値も未確定になって比べられないので作らない（上限を超えたときの扱いは test_candidates）。
    """
    n = 1
    for d in fam.members:
        cands = [x.pid for x in fam.members if x.pid not in (d.pid, fam.spouse_of(d.pid)) and fam.seikei[frozenset((x.pid, d.pid))]]
        if len(cands) >= 2:
            n *= len(cands)
    return n


def family_ir(fam: Family) -> dict[str, Any]:
    y = fam.year
    persons = [{"id": x.pid, "birth_on": x.birth.isoformat()} for x in fam.members]
    facts = [
        {
            "id": f"s-{x.pid}", "kind": "salary_payment", "roles": {"recipient": x.pid}, "when": {"on": f"{y}-12-20"},
            "amounts": {"gross": x.salary, "withholding_tax": x.withholding},
            "attributes": {"counterparty": "架空の会社", "due_on": f"{y}-12-20"},
        }
        for x in fam.members
        if x.salary > 0
    ]  # fmt: skip
    for x in fam.members:
        if x.pension:
            facts.append({"id": f"pen-{x.pid}", "kind": "pension_payment", "roles": {"recipient": x.pid}, "when": {"on": f"{y}-12-15"},
                          "amounts": {"gross": x.pension, "withholding_tax": 0},
                          "attributes": {"scheme": "national_pension", "benefit_reason": "old_age"}})  # fmt: skip
        if x.student:
            facts.append({"id": f"enr-{x.pid}", "kind": "enrollment", "roles": {"person": x.pid}, "when": {"from_on": f"{y - 1}-04-01"},
                          "attributes": {"school_type": "school_act_article1"}})  # fmt: skip
        for i, (liable, amount) in enumerate(x.social):
            kind = "health_insurance" if liable == x.pid else "national_pension"
            facts.append({"id": f"si-{x.pid}-{i}", "kind": "social_insurance_payment", "roles": {"payer": x.pid, "liable_person": liable},
                          "when": {"on": f"{y}-10-31"}, "amounts": {"amount": amount}, "attributes": {"premium_type": kind}})  # fmt: skip
    ids = {x.pid for x in fam.members}
    relations: list[dict[str, Any]] = []
    if "p-b" in ids:
        relations.append({"id": "m-ab", "kind": "marriage", "roles": {"spouse_a": "p-a", "spouse_b": "p-b"}, "when": {"from_on": "2000-01-01"}})
    for x in fam.members:
        if x.role == "child":
            for p in ("p-a", "p-b"):
                if p in ids:
                    relations.append({"id": f"pa-{p}-{x.pid}", "kind": "parentage", "roles": {"parent": p, "child": x.pid},
                                      "when": {"on": x.birth.isoformat()}, "attributes": {"basis": "birth_in_marriage"}})  # fmt: skip
    if "p-g" in ids:
        relations.append({"id": "pa-g-a", "kind": "parentage", "roles": {"parent": "p-g", "child": "p-a"},
                          "when": {"on": fam.m("p-a").birth.isoformat()}, "attributes": {"basis": "birth_in_marriage"}})  # fmt: skip
    rel_word = {"claimant": "householder", "spouse": "spouse", "child": "child", "grandparent": "parent"}
    residences = [
        {"id": f"rr-{x.pid}", "kind": "resident_record", "roles": {"person": x.pid}, "when": {"from_on": f"{y - 1}-01-01"},
         "attributes": {"municipality_code": "131016", "household_id": "h-1", "householder": x.role == "claimant",
                        "relation_to_householder": rel_word[x.role]}}
        for x in fam.members
    ]  # fmt: skip
    judgments: list[dict[str, Any]] = []
    for kind, table, tag in (("判断.生計を一にする", fam.seikei, "sk"), ("判断.同居を常況", fam.doukyo, "dk")):
        for pair, val in sorted(table.items(), key=lambda kv: sorted(kv[0])):
            p, q = sorted(pair)
            judgments.append({"id": f"{tag}-{p}-{q}", "kind": kind, "judged_by": {"person": "p-a"}, "judged_at": f"{y}-12-31T10:00:00+09:00",
                              "subject": {"person": p, "other_person": q}, "when": {"from_on": f"{y}-01-01", "to_on": f"{y}-12-31"},
                              "value": val})  # fmt: skip
    return make_ir(persons, facts, relations=relations, residences=residences, judgments=judgments)


@dataclass
class Expected:
    values: dict[tuple[str, str], int]  # (概念, 人) → 円
    skipped: str | None = None  # オラクルが決めない理由（所属の同額など）


def oracle(fam: Family) -> Expected:
    y = fam.year
    lim = fuyo_limit(y)
    kyu = {x.pid: kyuyo_shotoku(y, x.salary) for x in fam.members}
    # 公的年金等に係る雑所得（[NK]）：公的年金等に係る雑所得以外の合計所得金額は給与所得（第2項の調整控除を適用しない：所基通35−8）
    nenkin = {x.pid: nenkin_zatsu(x.pension, age_at_end(x.birth, y), kyu[x.pid]) if x.pension else 0 for x in fam.members}
    # 所得金額調整控除の第2項（[ADJ]）：給与所得控除後の給与等の金額と公的年金等に係る雑所得の金額の双方があるとき
    adj2 = {
        p: max(0, min(kyu[p], 100_000) + min(nenkin[p], 100_000) - 100_000) if (kyu[p] > 0 and nenkin[p] > 0) else 0 for p in kyu
    }
    age = {x.pid: age_at_end(x.birth, y) for x in fam.members}

    def seikei(p: str, q: str) -> bool:
        return fam.seikei[frozenset((p, q))]

    # 所得金額調整控除の第1項（[ADJ]）：850万円超で、年齢23歳未満の扶養親族（親族・生計一・判定用の合計所得金額が上限以下）を有する
    pre_total = {p: kyu[p] - adj2[p] + nenkin[p] for p in kyu}  # 第1項の控除の前の合計所得金額
    adj: dict[str, int] = {}
    for x in fam.members:
        has = any(
            d.pid != x.pid and d.pid != fam.spouse_of(x.pid) and seikei(x.pid, d.pid) and age[d.pid] < 23 and pre_total[d.pid] <= lim
            for d in fam.members
        )
        adj[x.pid] = _ceil(Fraction(min(x.salary, 1_000 * MAN) - 850 * MAN, 10)) if (x.salary > 850 * MAN and has) else 0
    adj = {p: adj[p] + adj2[p] for p in adj}
    total = {p: kyu[p] - adj[p] + nenkin[p] for p in kyu}

    # 扶養の所属（[ATR]）：記載がないので、配偶者（所令218）→ 所得の合計額が最も大きい人（所令219②二）。同額なら決めない
    claim: dict[str, str] = {}
    for d in fam.members:
        if d.role == "claimant":
            continue
        is_dep = total[d.pid] <= lim
        is_tok = 19 <= age[d.pid] < 23 and lim < total[d.pid] <= 123 * MAN
        if not (is_dep or is_tok):
            continue
        sp = fam.spouse_of(d.pid)
        if sp is not None and seikei(sp, d.pid) and is_dep:
            claim[d.pid] = sp  # 同一生計配偶者（所令218：記載がなければ配偶者）
            continue
        cands = [x.pid for x in fam.members if x.pid not in (d.pid, sp) and seikei(x.pid, d.pid)]
        if not cands:
            continue
        top = max(total[c] for c in cands)
        best = [c for c in cands if total[c] == top]
        if len(best) > 1:
            return Expected({}, skipped=f"{d.pid} の所属が所得の合計額の同額で決まらない")
        claim[d.pid] = best[0]

    vals: dict[tuple[str, str], int] = {}
    for x in fam.members:
        p = x.pid
        sp = fam.spouse_of(p)
        hk = htk = fuyo = toku = 0
        if sp is not None and claim.get(sp) == p:
            hk, htk = haigusha(total[p], total[sp], age[sp] >= 70, y)
        if sp is not None and sp not in claim and seikei(p, sp) and lim < total[sp] <= 133 * MAN:
            hk, htk = haigusha(total[p], total[sp], age[sp] >= 70, y)
        for d, c in claim.items():
            if c != p or d == sp:
                continue
            if total[d] <= lim:
                if age[d] < 16:
                    continue
                if 19 <= age[d] < 23:
                    fuyo += 63 * MAN
                elif age[d] >= 70:
                    asc = d in fam.lineal_ascendants(p) or (sp is not None and d in fam.lineal_ascendants(sp))
                    together = fam.doukyo[frozenset((d, p))] or (sp is not None and fam.doukyo[frozenset((d, sp))])
                    fuyo += 58 * MAN if (asc and together) else 48 * MAN
                else:
                    fuyo += 38 * MAN
            else:
                toku += tokutei_shinzoku(total[d])
        kiso_p = kiso(y, total[p])
        # 社会保険料控除（[SI]）：自己又は生計を一にする配偶者その他の親族の負担すべき社会保険料を支払った額
        shakai = sum(a for liable, a in x.social if liable == p or seikei(p, liable))
        # 勤労学生控除（[ZG6]）：学校教育法第1条の学生で給与所得等（給与）を有し、合計所得金額が上限以下（給与のほかの所得はない）
        kinro = 27 * MAN if (x.student and x.salary > 0 and not x.pension and total[p] <= (85 if y == 2025 else 89) * MAN) else 0
        # ひとり親控除（[HO]）：現に婚姻をしていない者（婚姻の記録がない申告者）で、生計を一にする子（総所得金額等が上限以下、他の者の
        # 同一生計配偶者・扶養親族とされている者を除く）を有し、合計所得金額が500万円以下。事実婚の続柄の記載はない（住民票の記録で確かめる）
        child_ok = x.role == "claimant" and any(
            c.role == "child" and seikei(p, c.pid) and total[c.pid] <= lim and claim.get(c.pid, p) == p
            for c in fam.members
        )
        hitori = 35 * MAN if (sp is None and child_ok and total[p] <= 500 * MAN) else 0
        kojo = kiso_p + hk + htk + fuyo + toku + shakai + kinro + hitori
        taxable = max(0, total[p] - kojo) // 1_000 * 1_000
        tax = zeigaku(taxable)
        fukko = _floor(Fraction(tax * 21, 1_000))
        both = tax + fukko
        diff = both - (x.withholding if x.salary > 0 else 0)  # 給与の支払の記録は給与があるときだけ作る
        vals.update(
            {
                ("所得税.給与所得の金額", p): kyu[p],
                ("所得税.所得金額調整控除", p): adj[p],
                ("所得税.社会保険料控除の額", p): shakai,
                ("所得税.勤労学生控除の額", p): kinro,
                ("所得税.ひとり親控除の額", p): hitori,
                ("所得税.合計所得金額", p): total[p],
                ("所得税.基礎控除の額", p): kiso_p,
                ("所得税.配偶者控除の額", p): hk,
                ("所得税.配偶者特別控除の額", p): htk,
                ("所得税.扶養控除の額", p): fuyo,
                ("所得税.特定親族特別控除の額", p): toku,
                ("所得税.所得控除の合計", p): kojo,
                ("所得税.課税総所得金額", p): taxable,
                ("所得税.課税総所得金額に対する税額", p): tax,
                ("所得税.基準所得税額", p): tax,
                ("所得税.復興特別所得税額", p): fukko,
                ("所得税.所得税及び復興特別所得税の額", p): both,
                ("所得税.還付される税額", p): max(0, -diff),
            }
        )
        if diff >= 0:
            vals[("所得税.申告納税額", p)] = diff // 100 * 100
    return Expected(vals)


# ---------------------------------------------------------------------------
# 比べる
# ---------------------------------------------------------------------------


@dataclass
class Comparison:
    compared: int = 0
    withheld: int = 0  # 未確定・対象外で値を出さなかった
    ranges: int = 0  # 幅（端数の候補）
    mismatches: list[str] = field(default_factory=list)
    withheld_examples: list[str] = field(default_factory=list)


def compare(fam: Family, exp: Expected, out: Comparison) -> None:
    res = evaluate(family_ir(fam), make_query((fam.year,)), system=system())
    assert isinstance(res, EvaluationResult), getattr(res, "errors", res)
    sc = res.scenario("base")
    t = TimeKey("tax_year", fam.year)
    for (concept, pid), want in sorted(exp.values.items()):
        v = sc.value(concept, pid, t)
        if State.OUT_OF_SCOPE in v.states or State.UNDETERMINED in v.states:
            out.withheld += 1
            if len(out.withheld_examples) < 5:
                why = v.out_of_scope.reason if v.out_of_scope else str([s.target for s in v.undetermined.splits][:2]) if v.undetermined else ""
                out.withheld_examples.append(f"{fam.year} {pid} {concept}: {why[:200]}")
            continue
        got = v.value
        if isinstance(got, YenRange):
            out.ranges += 1
            if not (got.min <= want <= got.max):
                out.mismatches.append(f"{fam.year} {pid} {concept}: 幅 {got} にオラクル {want} が入らない（{_describe(fam)}）")
            continue
        out.compared += 1
        if got != YenAmount(want):
            out.mismatches.append(f"{fam.year} {pid} {concept}: evaluate {got} ≠ オラクル {want}（{_describe(fam)}）")


def _describe(fam: Family) -> str:
    ms = ", ".join(f"{x.pid}:{x.birth.isoformat()}:{x.salary}:{x.pension}:{'学' if x.student else ''}:{x.social}" for x in fam.members)
    apart = sorted("-".join(sorted(pair)) for pair, v in fam.seikei.items() if not v)
    return f"{ms} 生計が別の組={apart}"


def run_sweep(seed: int, n: int, *, cap: bool = True) -> tuple[Comparison, int]:
    rng = random.Random(seed)
    out = Comparison()
    skipped = 0
    for i in range(n):
        year = 2025 if i % 2 == 0 else 2026
        fam = random_family(rng, year, cap=cap)
        exp = oracle(fam)
        if exp.skipped:
            skipped += 1
            continue
        compare(fam, exp, out)
    return out, skipped


class TestOracleUnits(unittest.TestCase):
    """オラクル自身を docs に書かれた点で確かめる（オラクルの誤りで evaluate を疑わないため）。"""

    def test_kyuyo_points_from_docs(self) -> None:
        # [B5] §3.1 の例：令和7年分 [1,904,000, 1,908,000) → 1,252,800
        self.assertEqual(kyuyo_shotoku(2025, 1_905_000), 1_252_800)
        # [ZE]（docs/inferences/20261109_impl-prep_zeigaku-examples.md）Z1：令和8年分 140万円 → 66万円、令和7年分 → 75万円
        self.assertEqual(kyuyo_shotoku(2026, 1_400_000), 660_000)
        self.assertEqual(kyuyo_shotoku(2025, 1_400_000), 750_000)
        # [B5] 20,000,000円 → 18,050,000円
        self.assertEqual(kyuyo_shotoku(2025, 20_000_000), 18_050_000)
        self.assertEqual(kyuyo_shotoku(2026, 2_192_000), 1_451_000)  # [S294] 第3号
        self.assertEqual(kyuyo_shotoku(2026, 690_999), 0)

    def test_spouse_special_table(self) -> None:
        # [SP] §1.3 の表（令和8年分）
        rows = [(950_000, 38), (950_001, 36), (1_000_000, 36), (1_000_001, 31), (1_300_000, 6), (1_300_001, 3), (1_330_000, 3)]
        for t, man in rows:
            self.assertEqual(haigusha(5_000_000, t, False, 2026)[1], man * MAN, t)
        self.assertEqual(haigusha(9_200_000, 1_000_001, False, 2026)[1], 21 * MAN)  # 31万の2/3 → 1万円未満切上げ
        self.assertEqual(haigusha(9_600_000, 1_330_000, False, 2026)[1], 1 * MAN)

    def test_tokutei_table(self) -> None:
        # [IT3]・docs/public-sources/20261109_impl-prep_kyuyo-sources.md §4.2 の表
        rows = [(850_000, 63), (850_001, 61), (900_000, 61), (900_001, 51), (1_100_001, 11), (1_150_000, 11), (1_150_001, 6), (1_200_001, 3)]
        for t, man in rows:
            self.assertEqual(tokutei_shinzoku(t), man * MAN, t)

    def test_tax_table(self) -> None:
        # [ZG] TA2260 の速算表（控除額）と超過累進が一致する
        for taxable, rate, minus in [(1_949_000, 5, 0), (3_299_000, 10, 97_500), (6_949_000, 20, 427_500), (8_999_000, 23, 636_000),
                                     (17_999_000, 33, 1_536_000), (39_999_000, 40, 2_796_000), (50_000_000, 45, 4_796_000)]:  # fmt: skip
            self.assertEqual(zeigaku(taxable), taxable * rate // 100 - minus, taxable)


# ---------------------------------------------------------------------------
# 1人の所得控除（物的控除）：根拠のない1円未満の端数は区間で比べる
# ---------------------------------------------------------------------------
#   [HK]  生命保険料控除（所法76①一：新生命保険料）・地震保険料控除（所法77①、5万円）・寄附金控除（所法78①：総所得金額等の40%、2千円）・
#         小規模企業共済等掛金控除（所法75①：支払った金額）：docs/public-sources/20261109_round2_hoken-kifu-laws.md §2.1・§3・§4・§5
#   [IR]  医療費控除（所法73①：総所得金額等の5%と10万円の少ない方を超える部分、200万円が上限）：docs/public-sources/20261109_R1-laws_income-tax.md §4
#   式の1円未満（40%・5%・2分の1・4分の1）は条文に端数の定めがない（[HK] §2.1 の注）ので、切捨てと切上げの両端の区間に evaluate の値（幅を含む）が入ることを確かめる。


@dataclass
class Single:
    year: int
    birth: _dt.date
    salary: int
    ideco: int
    donation: int
    medical: int
    earthquake: int
    life: int


def random_single(rng: random.Random, year: int) -> Single:
    def maybe(lo: int, hi: int) -> int:
        return rng.randint(lo, hi) if rng.random() < 0.6 else 0

    return Single(
        year, _dt.date(rng.randint(1950, 2000), rng.randint(1, 12), rng.randint(1, 28)),
        _rand_salary(rng, 300_000, 12_000_000, (1_900_000, 2_200_000, 6_600_000)),
        maybe(1, 816_000), maybe(2_001, 4_000_000), maybe(1, 3_000_000), maybe(1, 80_000), maybe(1, 120_000),
    )  # fmt: skip


def single_ir(s: Single) -> dict[str, Any]:
    y, pid = s.year, "p-s"
    facts: list[dict[str, Any]] = [
        {"id": "sal", "kind": "salary_payment", "roles": {"recipient": pid}, "when": {"on": f"{y}-12-20"},
         "amounts": {"gross": s.salary, "withholding_tax": 0}, "attributes": {"counterparty": "架空の会社", "due_on": f"{y}-12-20"}},
    ]  # fmt: skip
    assets: list[dict[str, Any]] = []
    if s.ideco:
        facts.append({"id": "ma", "kind": "mutual_aid_payment", "roles": {"payer": pid, "member": pid}, "when": {"on": f"{y}-09-30"},
                      "amounts": {"amount": s.ideco}, "attributes": {"contribution_type": "individual_defined_contribution"}})  # fmt: skip
    if s.donation:
        facts.append({"id": "dn", "kind": "donation", "roles": {"donor": pid}, "when": {"on": f"{y}-08-01"}, "amounts": {"amount": s.donation},
                      "attributes": {"recipient_name": "架空市", "recipient_type": "local_government", "receipt_issued": True, "return_gift": False}})  # fmt: skip
    if s.medical:
        facts.append({"id": "md", "kind": "medical_payment", "roles": {"payer": pid, "patient": pid}, "when": {"on": f"{y}-07-10"},
                      "amounts": {"amount": s.medical}, "attributes": {"incurred_on": f"{y}-07-01", "medical_kinds": ["medical_treatment"]}})  # fmt: skip
    if s.earthquake:
        assets.append({"id": "ct-eq", "kind": "insurance_contract", "roles": {"policyholder": pid}, "when": {"from_on": f"{y - 1}-04-01"},
                       "attributes": {"product_type": "earthquake", "concluded_on": f"{y - 1}-03-01", "insured_object": "dwelling",
                                      "insured_object_owner": pid, "residential_use": True}})  # fmt: skip
        facts.append({"id": "ip-eq", "kind": "insurance_payment", "roles": {"payer": pid}, "when": {"on": f"{y}-04-01"},
                      "amounts": {"amount": s.earthquake}, "attributes": {"contract_id": "ct-eq", "flow": "premium"}})  # fmt: skip
    if s.life:
        assets.append({"id": "ct-life", "kind": "insurance_contract", "roles": {"policyholder": pid, "insured": pid}, "when": {"from_on": "2015-04-01"},
                       "attributes": {"product_type": "life", "concluded_on": "2015-03-01", "beneficiary_ids": [pid]}})  # fmt: skip
        facts.append({"id": "ip-life", "kind": "insurance_payment", "roles": {"payer": pid}, "when": {"on": f"{y}-05-01"},
                      "amounts": {"amount": s.life}, "attributes": {"contract_id": "ct-life", "flow": "premium"}})  # fmt: skip
    return make_ir([{"id": pid, "birth_on": s.birth.isoformat()}], facts, assets=assets)


def _new_life(x: int) -> Fraction:
    """新生命保険料の控除額（[HK] 所法76①一）。"""
    if x <= 20_000:
        return Fraction(x)
    if x <= 40_000:
        return 20_000 + Fraction(x - 20_000, 2)
    if x <= 80_000:
        return 30_000 + Fraction(x - 40_000, 4)
    return Fraction(40_000)


def oracle_single(s: Single) -> dict[str, tuple[int, int]]:
    """概念 → (下端, 上端)。端数の両端（切捨て・切上げ）で計算した区間。"""
    y = s.year
    total = kyuyo_shotoku(y, s.salary)  # 給与だけで所得金額調整控除はない（扶養親族がいない）
    exact = {
        "所得税.小規模企業共済等掛金控除の額": Fraction(s.ideco),
        "所得税.寄附金控除の額": max(Fraction(0), min(Fraction(s.donation), Fraction(total * 40, 100)) - 2_000) if s.donation else Fraction(0),
        "所得税.医療費控除の額": max(Fraction(0), min(Fraction(2_000_000), s.medical - min(Fraction(100_000), Fraction(total * 5, 100)))),
        "所得税.地震保険料控除の額": Fraction(min(50_000, s.earthquake)),
        "所得税.生命保険料控除の額": _new_life(s.life) if s.life else Fraction(0),
    }
    out: dict[str, tuple[int, int]] = {k: (_floor(v), _ceil(v)) for k, v in exact.items()}
    base = kiso(y, total)
    out["所得税.基礎控除の額"] = (base, base)
    lo_sum = base + sum(lo for lo, _ in out.values()) - base
    hi_sum = base + sum(hi for _, hi in out.values()) - base
    out["所得税.所得控除の合計"] = (lo_sum, hi_sum)
    taxable_hi = max(0, total - lo_sum) // 1_000 * 1_000
    taxable_lo = max(0, total - hi_sum) // 1_000 * 1_000
    out["所得税.課税総所得金額"] = (taxable_lo, taxable_hi)
    out["所得税.課税総所得金額に対する税額"] = (zeigaku(taxable_lo), zeigaku(taxable_hi))
    t_lo, t_hi = zeigaku(taxable_lo), zeigaku(taxable_hi)
    out["所得税.所得税及び復興特別所得税の額"] = (t_lo + _floor(Fraction(t_lo * 21, 1_000)), t_hi + _floor(Fraction(t_hi * 21, 1_000)))
    return out


def compare_single(s: Single, out: Comparison) -> None:
    res = evaluate(single_ir(s), make_query((s.year,)), system=system())
    assert isinstance(res, EvaluationResult), getattr(res, "errors", res)
    sc = res.scenario("base")
    t = TimeKey("tax_year", s.year)
    for concept, (lo, hi) in sorted(oracle_single(s).items()):
        v = sc.value(concept, "p-s", t)
        if State.OUT_OF_SCOPE in v.states or (State.UNDETERMINED in v.states and v.value is None):
            out.withheld += 1
            if len(out.withheld_examples) < 5:
                why = v.out_of_scope.reason if v.out_of_scope else str([sp.target for sp in v.undetermined.splits][:2]) if v.undetermined else ""
                out.withheld_examples.append(f"{s.year} {concept}: {why[:200]}")
            continue
        got = v.value
        g_lo, g_hi = (got.min, got.max) if isinstance(got, YenRange) else (got.amount, got.amount)  # type: ignore[union-attr]
        out.compared += 1
        if not (lo <= g_lo and g_hi <= hi):
            out.mismatches.append(f"{s.year} {concept}: evaluate [{g_lo}, {g_hi}] がオラクルの区間 [{lo}, {hi}] の外（{s}）")


def run_single_sweep(seed: int, n: int) -> Comparison:
    rng = random.Random(seed)
    out = Comparison()
    for i in range(n):
        compare_single(random_single(rng, 2025 if i % 2 == 0 else 2026), out)
    return out




if __name__ == "__main__":
    unittest.main()
