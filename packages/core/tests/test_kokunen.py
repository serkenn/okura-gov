"""規則モジュール kokunen（rules/kokunen/）のユニットテスト。関数と1つの変数の式を直接呼ぶ（上流の値は入力として与える）。

期待値の出典：docs/public-sources/20261109_round2_kokuho-premium-structure.md（[KHP]）§11.1（月額 令和7年度 17,510円・令和8年度 17,920円・
令和9年度 18,290円）、§10（5円未満切捨て・5円以上は10円に切上げ）、§12.2（全額免除 (n＋1)×35万＋32万、4分の3 88万・半額 128万・4分の1 168万、
加算 38万・48万・63万）、§12.1（障害者等 135万円）。第3号：docs/public-sources/20261109_round3_dai3go-notice-search.md §3・§3.1（130万円未満、
同一世帯は2分の1未満、別世帯は援助額より少ない）、docs/public-sources/20261109_R3-tsutatsu_shakaihoken-juminzei.md §1.3（労働契約）。
"""

from __future__ import annotations

import datetime as dt
import unittest
from fractions import Fraction
from typing import Any

from openfisca_core.simulation_builder import SimulationBuilder

from okura_core.rules.kokunen.calc import (
    LaborContract,
    PartialRules,
    SpouseSupport,
    age_on,
    chain_addition,
    contract_annual_income,
    counts_as_dependent,
    full_exemption_threshold,
    meets_full,
    monthly_premium,
    needs_overall_judgment,
    listed_before_carry,
    partial_tier,
    partial_tier_with_status,
    stricter,
    supported_principle,
)

from okura_core.registry import YearContext, YearWindow
from okura_core.rules.kokunen.periods import (
    additional_premium_count,
    additional_premium_paid_count,
    birthday,
    childcare_count,
    disability_benefit_listed,
    elapsed_day,
    fiscal_months,
    is_student_record,
    student_months,
)

from .support import make_ir, system


HALF = Fraction(1, 2)  # 健保.同一の世帯の収入の割合 の値（試験の入力）


def _calc(var: str, year: str, **inputs: Any) -> Any:
    people = {"p": {k: {year: v} for k, v in inputs.items()}}
    return SimulationBuilder().build_from_entities(system(), {"人物一覧": people}).calculate(var, year)[0]


class TestMonthlyPremium(unittest.TestCase):
    def test_fiscal_years(self) -> None:
        # 所得の年分 F−1 の situation で年度 F の値
        self.assertEqual(int(_calc("年金_保険料の月額", "2024")), 17_510)
        self.assertEqual(int(_calc("年金_保険料の月額", "2025")), 17_920)
        self.assertEqual(int(_calc("年金_保険料の月額", "2026")), 18_290)

    def test_rounding_rule(self) -> None:
        self.assertEqual(monthly_premium(1_005, Fraction(1)), 1_010)
        self.assertEqual(monthly_premium(1_004, Fraction(1)), 1_000)
        self.assertEqual(monthly_premium(17_000, Fraction(1054, 1000)), 17_920)


class TestExemptionThresholds(unittest.TestCase):
    def test_full_exemption_boundary(self) -> None:
        self.assertEqual(full_exemption_threshold(0, 350_000, 320_000), 670_000)
        self.assertEqual(full_exemption_threshold(2, 350_000, 320_000), 1_370_000)
        self.assertTrue(meets_full(670_000, 670_000, False, 1_350_000))
        self.assertFalse(meets_full(670_001, 670_000, False, 1_350_000))
        # 地方税法の障害者・寡婦・ひとり親は135万円以下でも満たす
        self.assertTrue(meets_full(1_350_000, 670_000, True, 1_350_000))
        self.assertFalse(meets_full(1_350_001, 670_000, True, 1_350_000))

    def test_partial_tiers(self) -> None:
        r = PartialRules(880_000, 1_280_000, 1_680_000)
        self.assertEqual(partial_tier(880_000, 0, r), "4分の3免除")
        self.assertEqual(partial_tier(880_001, 0, r), "半額免除")
        self.assertEqual(partial_tier(1_280_000 + 380_000, 380_000, r), "半額免除")
        self.assertEqual(partial_tier(1_680_001, 0, r), "なし")
        # 本人・世帯主・配偶者の全員が満たす区分は寛大でないほう
        self.assertEqual(stricter("4分の3免除", "4分の1免除"), "4分の1免除")

    def test_specified_age_dependents(self) -> None:
        # 特定年齢扶養親族（30歳以上70歳未満）は控除対象扶養親族に限る
        self.assertFalse(counts_as_dependent(True, 30, False))
        self.assertTrue(counts_as_dependent(True, 29, False))
        self.assertTrue(counts_as_dependent(True, 70, False))

    def test_student_special_boundary(self) -> None:
        base = {"年金_一部免除の加算額": 380_000, "年金_免除判定所得": 2_000_000}
        self.assertTrue(_calc("年金_学生納付特例の所得基準を満たすか", "2025", 年金_一部免除判定所得=1_660_000, **base))
        self.assertFalse(_calc("年金_学生納付特例の所得基準を満たすか", "2025", 年金_一部免除判定所得=1_660_001, **base))

    def test_full_exemption_variable_needs_head_and_spouse(self) -> None:
        own = {"年金_免除判定所得": 670_000, "年金_全額免除の所得基準額": 670_000}
        self.assertTrue(_calc("年金_全額免除の所得基準を満たすか", "2025", 年金_世帯主及び配偶者が全額免除の所得基準を満たすか=True, **own))
        self.assertFalse(_calc("年金_全額免除の所得基準を満たすか", "2025", 年金_世帯主及び配偶者が全額免除の所得基準を満たすか=False, **own))


class TestDai3go(unittest.TestCase):
    def test_support_branches(self) -> None:
        # 同一世帯：130万円未満かつ第2号の年間収入の2分の1未満
        self.assertTrue(supported_principle(SpouseSupport(1_299_999, 1_300_000, True, 2_600_000, 0, HALF)))
        self.assertFalse(supported_principle(SpouseSupport(1_300_000, 1_300_000, True, 3_000_000, 0, HALF)))
        s = SpouseSupport(1_200_000, 1_300_000, True, 2_400_000, 0, HALF)
        self.assertFalse(supported_principle(s))
        self.assertTrue(needs_overall_judgment(s))  # 2分の1以上で第2号の年間収入を上回らない：機構の総合的な勘案
        self.assertFalse(needs_overall_judgment(SpouseSupport(1_200_000, 1_300_000, True, 1_100_000, 0, HALF)))
        # 別世帯：援助による収入額より少ない。障害者は180万円未満
        self.assertTrue(supported_principle(SpouseSupport(1_000_000, 1_300_000, False, 0, 1_000_001, HALF)))
        self.assertFalse(supported_principle(SpouseSupport(1_000_000, 1_300_000, False, 0, 1_000_000, HALF)))
        self.assertTrue(supported_principle(SpouseSupport(1_700_000, 1_800_000, False, 0, 2_000_000, HALF)))

    def test_variable_requirements(self) -> None:
        ok = {
            "年金_判定日の年齢": 59,
            "年金_配偶者が第2号被保険者か": True,
            "年金_国内居住の要件を満たすか": True,
            "年金_被扶養配偶者の年間収入": 1_000_000,
            "年金_第2号被保険者と同一の世帯に属するか": True,
            "年金_第2号被保険者の年間収入": 5_000_000,
        }
        self.assertTrue(_calc("年金_第3号被保険者に当たるか", "2026", **ok))
        for change in ({"年金_判定日の年齢": 60}, {"年金_判定日の年齢": 19}, {"年金_本人が第2号被保険者か": True}, {"年金_国内居住の要件を満たすか": False}):
            with self.subTest(change=change):
                self.assertFalse(_calc("年金_第3号被保険者に当たるか", "2026", **{**ok, **change}))
        # 収入の基準は健保の約束の概念（健保.配偶者の収入の基準額）：障害者は180万円未満、そうでなければ130万円未満
        disabled = {"健保_障害を支給事由とする給付の受給要件に該当する程度の障害を有するか": True}
        self.assertTrue(_calc("年金_第3号被保険者に当たるか", "2026", **{**ok, "年金_被扶養配偶者の年間収入": 1_700_000, **disabled}))
        self.assertFalse(_calc("年金_第3号被保険者に当たるか", "2026", **{**ok, "年金_被扶養配偶者の年間収入": 1_700_000}))
        self.assertFalse(_calc("年金_第3号被保険者に当たるか", "2026", **{**ok, "年金_被扶養配偶者の年間収入": 1_300_000}))
        self.assertTrue(_calc("年金_第3号被保険者に当たるか", "2026", **{**ok, "年金_被扶養配偶者の年間収入": 1_299_999, "年金_第2号被保険者の年間収入": 2_600_000}))
        self.assertFalse(_calc("年金_第3号被保険者に当たるか", "2026", **{**ok, "年金_被扶養配偶者の年間収入": 1_299_999, "年金_第2号被保険者の年間収入": 2_599_998}))
        # 19歳以上23歳未満の150万円の区分は配偶者を除く（健保.配偶者の収入の基準額）
        young = {"健保_判定日": dt.date(2026, 4, 1), "健保_判定日の年齢": 21, "健保_判定日の属する年の12月31日の年齢": 21}
        self.assertEqual(int(_calc("健保_配偶者の収入の基準額", "2026", **young)), 1_300_000)
        self.assertEqual(str(_calc("健保_同一の世帯の収入の割合", "2026")), "1/2")

    def test_labor_contract(self) -> None:
        c = LaborContract(100_000, 0, 5_000, True, None, False, True, True, False, True)
        self.assertEqual(contract_annual_income(c), 1_260_000)
        self.assertIsNone(contract_annual_income(LaborContract(100_000, 0, None, True, None, False, True, True, False, True)))  # 通勤手当の金額が不明確
        self.assertIsNone(contract_annual_income(LaborContract(100_000, 0, 0, False, None, False, True, True, True, True)))  # シフト制

    def test_age_on_day_before_birthday(self) -> None:
        self.assertEqual(age_on(dt.date(2006, 4, 1), dt.date(2026, 3, 31)), 20)
        self.assertEqual(age_on(dt.date(2006, 4, 1), dt.date(2026, 3, 30)), 19)
        self.assertEqual(age_on(dt.date(1967, 1, 1), dt.date(2026, 12, 31)), 60)



class TestIncomeScope2026(unittest.TestCase):
    """2026-11-12 に足した規則の境目。出典：scripts/results/IMPL3_egov_fetch/kokunen/grep_kokunenrei_2027-04-01.txt（国年令第6条の11・第6条の12：
    上場株式等の所得は列挙にない）、docs/public-sources/20261109_impl-prep_zeigaku-tax-calc.md §8.1（令和7年政令第355号附則第2条第2項）、
    docs/hypotheses/20261111_impl-research3_all-model.md H8（135万円の経路の読み(a)）、docs/public-sources/20261111_impl-research3_kokunen-laws.md §3・§4。"""

    def test_listed_income_excluded(self) -> None:
        # 譲渡損失を配当所得等から控除する（損益通算）なら、合計所得金額に入る額は 300,000−100,000
        self.assertEqual(listed_before_carry(300_000, -100_000, True), 200_000)
        self.assertEqual(listed_before_carry(300_000, -100_000, False), 300_000)
        v = _calc(
            "年金_免除判定所得", "2025",
            住民税_合計所得金額=2_000_000, 所得税_上場株式等に係る配当所得等の金額=300_000,
            所得税_上場株式等に係る譲渡所得等の金額=-100_000, 所得税_上場株式等の譲渡損失の損益通算を適用するか=True,
        )
        self.assertEqual(int(v), 1_800_000)

    def test_partial_income_resident_deductions_and_months(self) -> None:
        base = {
            "住民税_総所得金額等": 2_000_000,
            "住民税_上場株式等に係る分離課税の所得の金額": 100_000,
            "住民税_配偶者特別控除の額": 330_000,
            "住民税_特定親族特別控除の額": 450_000,
        }
        # 令和8年度（所得の年分 2025）：本則は両方を引く。令和8年6月以前の月分は特定親族特別控除額を引かない
        self.assertEqual(int(_calc("年金_一部免除判定所得", "2025", **base)), 2_000_000 - 100_000 - 330_000 - 450_000)
        self.assertEqual(int(_calc("年金_令和8年6月以前の月分の一部免除判定所得", "2025", **base)), 2_000_000 - 100_000 - 330_000)
        # 令和9年度：その月はないので同じ値
        self.assertEqual(int(_calc("年金_令和8年6月以前の月分の一部免除判定所得", "2026", **base)), 2_000_000 - 100_000 - 330_000 - 450_000)

    def test_route_135(self) -> None:
        r = PartialRules(880_000, 1_280_000, 1_680_000)
        self.assertEqual(partial_tier_with_status(3_000_000, 0, r, True, 1_350_000, 1_350_000), "4分の3免除")
        self.assertEqual(partial_tier_with_status(3_000_000, 0, r, True, 1_350_001, 1_350_000), "なし")
        self.assertEqual(partial_tier_with_status(3_000_000, 0, r, False, 0, 1_350_000), "なし")
        common = {"年金_一部免除判定所得": 3_000_000, "年金_全額免除の所得基準額": 670_000, "年金_配偶者が全額免除の所得基準を満たすか": True, "所得税_寡婦に当たるか": True}
        self.assertEqual(str(_calc("年金_一部免除の区分", "2025", 年金_免除判定所得=1_350_000, **common)), "4分の3免除")
        self.assertEqual(str(_calc("年金_一部免除の区分", "2025", 年金_免除判定所得=1_350_001, **common)), "なし")
        self.assertTrue(_calc("年金_納付猶予の所得基準を満たすか", "2025", 年金_免除判定所得=1_350_000, **common))
        self.assertFalse(_calc("年金_納付猶予の所得基準を満たすか", "2025", 年金_免除判定所得=1_350_001, **common))

    def test_chain_dependent(self) -> None:
        amounts = {"general": 380_000, "elderly_amount": 480_000, "specific_amount": 630_000, "disabled_amount": 270_000, "special_amount": 400_000}
        flags = {"dependent": True, "deductible": True, "specific": False, "elderly": False, "disabled": False, "special": False}
        self.assertEqual(chain_addition(age=20, **{**flags, "specific": True}, **amounts), (1, 630_000, 0))
        self.assertEqual(chain_addition(age=18, **flags, **amounts), (1, 630_000, 0))  # 19歳未満の控除対象扶養親族は特定扶養親族等
        # 特定年齢扶養親族（30歳以上70歳未満）で控除対象扶養親族でなければ数えないが、障害者の額は引く
        self.assertEqual(chain_addition(age=40, **{**flags, "deductible": False, "special": True}, **amounts), (0, 0, 400_000))
        self.assertEqual(chain_addition(age=40, **{**flags, "dependent": False}, **amounts), (0, 0, 0))

    def test_childcare_period_dates(self) -> None:
        # 民法第143条：応当日がなければその月の末日に満了し、経過した日はその翌日
        self.assertEqual(elapsed_day(dt.date(2027, 1, 31), 3), dt.date(2027, 5, 1))
        self.assertEqual(elapsed_day(dt.date(2027, 1, 30), 3), dt.date(2027, 4, 30))
        self.assertEqual(elapsed_day(dt.date(2026, 11, 15), 12), dt.date(2027, 11, 15))
        self.assertEqual(birthday(dt.date(2024, 2, 29), 1), dt.date(2025, 3, 1))

    def test_additional_premium_amount(self) -> None:
        self.assertEqual(int(_calc("年金_付加保険料の月額", "2025")), 400)


def _ctx(facts: list[dict[str, Any]], memberships: list[dict[str, Any]]) -> YearContext:
    ir = make_ir([{"id": "a", "birth_on": "1990-05-01"}], facts, insurance_memberships=memberships)
    return YearContext(ir, 2026, ("a",), {}, window=YearWindow())


_FIRST = {"id": "np", "kind": "national_pension", "roles": {"member": "a"}, "when": {"from_on": "2020-04-01"}, "attributes": {"category": "first"}}


class TestVocabulary20261112(unittest.TestCase):
    """2026-11-12 に足した語彙の境目：各種学校の修業年限（国年令第6条の6第9号：[PS3-KN] §2）、
    第89条第1項第1号のかっこ書きの3年・第2項の申出・付加保険料の申出（docs/public-sources/20261112_impl-c_kokunen-88-3-89-text.md §1・§2、[PS3-KN] §3）。"""

    def test_miscellaneous_school_length(self) -> None:
        rec = {"attributes": {"school_type": "miscellaneous_school"}}
        self.assertFalse(is_student_record(rec))
        self.assertFalse(is_student_record({"attributes": {"school_type": "miscellaneous_school", "course_length_months": 11}}))
        self.assertTrue(is_student_record({"attributes": {"school_type": "miscellaneous_school", "course_length_months": 12}}))

    def test_disability_three_years(self) -> None:
        # 障害状態に該当しなくなった日 2023-06-15 → 3年を経過した日 2026-06-15 の属する月（2026年6月）まで法定免除、7月から付加保険料を納付できる
        pens = {
            "id": "pe", "kind": "pension_entitlement", "roles": {"member": "a"}, "when": {"from_on": "2020-01-10"},
            "attributes": {"benefit": "disability", "scheme": "national_pension", "disability_state_ended_on": "2023-06-15"},
        }
        c = additional_premium_count(_ctx([], [_FIRST, pens]), "a", 2026, set())
        self.assertEqual(sorted(c.months), [(2026, m) for m in range(7, 13)] + [(2027, m) for m in range(1, 4)])
        # 第89条第2項の申出の月は法定免除を当てない
        app = {"id": "ap", "kind": "npi_application", "roles": {"person": "a"}, "when": {"from_on": "2026-04-01", "to_on": "2026-04-30"}, "attributes": {"application_type": "statutory_exemption_payment"}}
        c2 = additional_premium_count(_ctx([app], [_FIRST, pens]), "a", 2026, set())
        self.assertIn((2026, 4), c2.months)
        self.assertNotIn((2026, 5), c2.months)

    def test_additional_premium_application(self) -> None:
        app = {"id": "ap", "kind": "npi_application", "roles": {"person": "a"}, "when": {"from_on": "2026-09-20"}, "attributes": {"application_type": "additional_premium"}}
        ctx = _ctx([app], [_FIRST])
        can = additional_premium_count(ctx, "a", 2026, set())
        self.assertEqual(can.value, 12)
        self.assertEqual(additional_premium_paid_count(ctx, "a", can).value, 7)  # 2026年9月〜2027年3月
        fund = {"id": "nf", "kind": "national_pension_fund", "roles": {"member": "a"}, "when": {"from_on": "2027-01-01"}}
        can2 = additional_premium_count(_ctx([app], [_FIRST, fund]), "a", 2026, set())
        self.assertEqual(can2.value, 9)  # 基金の加入員の月（2027年1月〜3月）を除く


class TestResearch4(unittest.TestCase):
    """2026-11-12（impl-research4）：KN-17・KN-19・KN-20 の境目。
    出典：docs/public-sources/20261112_impl-research4_kokunen-laws.md（[PS4-KN]）§1〜§3、仮説 H4〜H6、推測 I4〜I6。"""

    def test_listed_school_is_student(self) -> None:
        # [PS4-KN] §1：第10号（国年則第77条の6）は日本年金機構の学生納付特例対象校一覧に記載された施設（H4・D22 S1 の読み）
        for st in ("accredited_vocational_training", "other"):
            with self.subTest(school_type=st):
                self.assertTrue(is_student_record({"attributes": {"school_type": st, "npi_student_school_listed": True}}))
                self.assertFalse(is_student_record({"attributes": {"school_type": st, "npi_student_school_listed": False}}))
                self.assertFalse(is_student_record({"attributes": {"school_type": st}}))

    def test_listed_field_decides_the_split(self) -> None:
        def enrol(**attrs: Any) -> dict[str, Any]:
            return {"id": "en", "kind": "enrollment", "roles": {"person": "a"}, "when": {"from_on": "2026-04-01", "to_on": "2027-03-31"},
                    "attributes": {"school_type": "other", **attrs}}

        months = fiscal_months(2026)
        c = student_months(_ctx([enrol(npi_student_school_listed=True)], []), "a", months, "学生納付特例の期間")
        self.assertEqual((c.value, c.missing), (12, []))
        c = student_months(_ctx([enrol(npi_student_school_listed=False)], []), "a", months, "学生納付特例の期間")
        self.assertEqual((c.value, c.missing), (0, []))
        c = student_months(_ctx([enrol()], []), "a", months, "学生納付特例の期間")
        self.assertEqual({s.id for s in c.missing}, {"事実:国年の準ずる教育施設:en"})  # 欄がなければ分かれ目（事実）

    def test_childcare_applies_to_births_before_enforcement(self) -> None:
        # I5：出産予定日（出産の日）2026-05-15・第1号 → 第88条の3第1項の期間は 2026年8月〜2027年4月。附則第10条で2026年10月以後の月に当てる
        # → 令和8年度（2026年4月〜2027年3月）は 2026年10月〜2027年3月の6か月、経過措置の分かれ目はない（[PS4-KN] §2）
        persons = [{"id": "a", "birth_on": "1990-05-01"}, {"id": "c", "birth_on": "2026-05-15"}]
        birth = {"id": "cb", "kind": "childbirth", "roles": {"person": "a"}, "when": {"on": "2026-05-15"},
                 "attributes": {"expected_delivery_on": "2026-05-20", "delivered_on": "2026-05-15", "child_ids": ["c"]}}
        co = {"id": "co", "kind": "cohabitation", "roles": {"person": "a", "other_person": "c"}, "when": {"from_on": "2026-05-15"}}
        ir = make_ir(persons, [birth], relations=[co], insurance_memberships=[_FIRST])
        c = childcare_count(YearContext(ir, 2026, ("a", "c"), {}, window=YearWindow()), "a", 2026)
        self.assertEqual(sorted(c.months), [(2026, m) for m in range(10, 13)] + [(2027, m) for m in range(1, 4)])
        self.assertFalse(any("経過措置" in s.id for s in c.missing))
        # I5 例2：出産 2025-08-01 → 期間は 2025年11月〜2026年7月で、2026年10月以後の月がないので 0
        persons2 = [{"id": "a", "birth_on": "1990-05-01"}, {"id": "c", "birth_on": "2025-08-01"}]
        birth2 = {**birth, "when": {"on": "2025-08-01"}, "attributes": {"delivered_on": "2025-08-01", "child_ids": ["c"]}}
        ir2 = make_ir(persons2, [birth2], relations=[{**co, "when": {"from_on": "2025-08-01"}}], insurance_memberships=[_FIRST])
        self.assertEqual(childcare_count(YearContext(ir2, 2026, ("a", "c"), {}, window=YearWindow()), "a", 2026).value, 0)

    def test_disability_benefits_of_article_89(self) -> None:
        # I6：国年令第6条の5第1項（[PS4-KN] §3）。障害厚生年金は1級・2級に限る、労災・企業年金は列挙にない、共済の3級は第1号か第6号かで分かれる
        self.assertTrue(disability_benefit_listed("national_pension", None))
        self.assertTrue(disability_benefit_listed("employees_pension", 2))
        self.assertFalse(disability_benefit_listed("employees_pension", 3))
        self.assertIsNone(disability_benefit_listed("employees_pension", None))
        self.assertTrue(disability_benefit_listed("mutual_aid", 1))
        self.assertIsNone(disability_benefit_listed("mutual_aid", 3))
        # 2026-11-12：共済の障害の年金の種類（mutual_aid_disability_kind）：第6号の旧法の障害年金は等級を問わない、第1号は1級・2級に限る
        self.assertTrue(disability_benefit_listed("mutual_aid", 3, "old_law_disability_pension"))
        self.assertFalse(disability_benefit_listed("mutual_aid", 3, "disability_mutual_aid_pension"))
        self.assertFalse(disability_benefit_listed("mutual_aid", 3, "disability_employees_pension"))
        self.assertIsNone(disability_benefit_listed("mutual_aid", None, "disability_employees_pension"))
        self.assertFalse(disability_benefit_listed("workers_accident_compensation", 1))
        self.assertFalse(disability_benefit_listed("corporate_pension", None))
        self.assertIsNone(disability_benefit_listed("other", 1))

        def pens(scheme: str, **attrs: Any) -> dict[str, Any]:
            return {"id": "pe", "kind": "pension_entitlement", "roles": {"member": "a"}, "when": {"from_on": "2020-01-10"},
                    "attributes": {"benefit": "disability", "scheme": scheme, **attrs}}

        # 障害厚生年金3級：法定免除でない → 付加保険料を12か月納付できる。2級：法定免除で0か月。分かれ目はない（第2項の除かれる者の政令は §3 にある）
        c3 = additional_premium_count(_ctx([], [_FIRST, pens("employees_pension", disability_grade=3)]), "a", 2026, set())
        c2 = additional_premium_count(_ctx([], [_FIRST, pens("employees_pension", disability_grade=2)]), "a", 2026, set())
        self.assertEqual((c3.value, c3.missing, c2.value, c2.missing), (12, [], 0, []))
        # 障害厚生年金2級で障害状態に該当しなくなった日 2023-06-15 → 3年を経過した日の属する月（2026年6月）の翌月から納付できる（国年令第6条の5第2項第1号ロ）
        ce = additional_premium_count(_ctx([], [_FIRST, pens("employees_pension", disability_grade=2, disability_state_ended_on="2023-06-15")]), "a", 2026, set())
        self.assertEqual(ce.value, 9)
        # 労災の年金だけ：当たらない
        self.assertEqual(additional_premium_count(_ctx([], [_FIRST, pens("workers_accident_compensation")]), "a", 2026, set()).value, 12)


class TestBoundaryDeclarations(unittest.TestCase):
    """境目の説明の宣言（D19。2026-11-12）：免除・納付猶予・学生納付特例の判定は、所得と基準額（扶養親族等で変わる：基準の概念）・135万円（パラメータ）の比較を直接読む。"""

    def test_declarations(self) -> None:
        from okura_core.boundaries import declarations, undeclared
        from okura_core.evaluate import REGISTRY

        got = {b.judgment: (b.compared, b.criterion, b.comparison) for b in declarations(REGISTRY) if b.module == "kokunen"}
        expected = {
            "国年.免除判定所得が全額免除の所得基準額以下か": ("国年.免除判定所得", "国年.全額免除の所得基準額", "以下"),
            "国年.免除判定所得が障害者等の所得の上限以下か": ("国年.免除判定所得", "国年.全額免除の所得基準.障害者等の所得の上限", None),
            "国年.一部免除判定所得が4分の3免除の所得基準額以下か": ("国年.一部免除判定所得", "国年.4分の3免除の所得基準額", "以下"),
            "国年.一部免除判定所得が半額免除の所得基準額以下か": ("国年.一部免除判定所得", "国年.半額免除の所得基準額", "以下"),
            "国年.一部免除判定所得が4分の1免除の所得基準額以下か": ("国年.一部免除判定所得", "国年.4分の1免除の所得基準額", "以下"),
            "国年.令和8年6月以前の月分の一部免除判定所得が半額免除の所得基準額以下か": ("国年.令和8年6月以前の月分の一部免除判定所得", "国年.半額免除の所得基準額", "以下"),
        }
        for judgment, decl in expected.items():
            with self.subTest(judgment=judgment):
                self.assertEqual(got.get(judgment), decl)
        self.assertNotIn("国年の免除", undeclared(REGISTRY))


class TestApplication(unittest.TestCase):
    """2026-11-12（KN-23）：選択.国民年金の免除の申請（C-17）。免除等は「…から申請があつたとき」（国年法第90条第1項・第90条の2・第90条の3、
    平成16年法附則第19条②・平成26年法附則第14条①）、産前産後は法律上当然（第88条の2）：docs/public-sources/20261111_impl-research3_kokunen-laws.md §1・§4。"""

    def test_apply_kind(self) -> None:
        from okura_core.rules.kokunen.inputs import _apply_match, apply_kind

        self.assertEqual(apply_kind({"apply": False, "exemption_type": "full"}), "申請しない")
        self.assertEqual(apply_kind({"apply": True}), "種類の指定なし")
        self.assertEqual(apply_kind({"apply": True, "exemption_type": "half"}), "半額免除")
        rec = {"subject": {"person": "a"}, "when": {"fiscal_year": 2026}}
        self.assertTrue(_apply_match("a", 2026)(rec))
        self.assertFalse(_apply_match("a", 2027)(rec))

    def test_applied_criterion(self) -> None:
        from okura_core.rules.kokunen.calc import applied_criterion

        # 一部免除：満たす最も寛大な区分が申請する区分と同じか寛大なら満たす（88万 < 128万 < 168万円）
        self.assertEqual(applied_criterion("半額免除", False, "4分の3免除", False, False, False), "満たす")
        self.assertEqual(applied_criterion("半額免除", False, "半額免除", False, False, False), "満たす")
        self.assertEqual(applied_criterion("4分の3免除", False, "半額免除", False, False, False), "満たさない")
        self.assertEqual(applied_criterion("4分の1免除", False, "なし", False, False, False), "満たさない")
        self.assertEqual(applied_criterion("全額免除", True, "なし", False, False, False), "満たす")
        self.assertEqual(applied_criterion("納付猶予", True, "4分の3免除", False, False, False), "満たさない")
        # 学生納付特例：令和8年度の4月〜6月分（特定親族特別控除額を引かない）と7月以後の月分で分かれる
        self.assertEqual(applied_criterion("学生納付特例", False, "なし", True, False, False), "7月以後の月分だけ満たす")
        self.assertEqual(applied_criterion("学生納付特例", False, "なし", True, True, False), "満たす")
        self.assertTrue(applied_criterion("産前産後", False, "なし", False, False, False).startswith("申請の対象でない"))
        for k in ("申請しない", "選択なし", "種類の指定なし"):
            self.assertEqual(applied_criterion(k, True, "4分の3免除", True, True, True), k)


if __name__ == "__main__":
    unittest.main()
