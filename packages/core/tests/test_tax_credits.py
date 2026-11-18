"""規則モジュール tax の外部で計算した税額控除（第一表 ㉞・㊴〜㊶）と差引所得税額（㊷）のテスト（2026-11-12。ユニットテストだけ：D24）。

上流の値（算出税額・配当控除・各控除の額）は入力として与えて、式と純粋関数を直接確かめる。テストのデータは架空の金額・架空の人。

期待値の出典：[CR] docs/public-sources/20261112_impl-research6_forms-tax-credits.md（令和7年分 確定申告の手引き 3-4_29・3-4_32・3-4_36）。
"""

from __future__ import annotations

import unittest
from typing import Any

from openfisca_core.simulation_builder import SimulationBuilder

from okura_core.registry import ModuleInputs
from okura_core.result import State
from okura_core.rules.tax.calc import CREDIT_ORDER, NO_CATEGORY, business_credit_category, deduct_credits, housing_credit_category
from okura_core.rules.tax.inputs import (
    EXTERNAL_CREDIT_VARIABLES,
    MULTIPLE_EXTERNAL_CREDIT_REASON,
    external_credit_inputs,
    external_credits_by_person,
)

from .support import system

V_BIZ = "所得税_事業所得等の特例に係る税額控除の額"
V_SEISMIC = "所得税_住宅耐震改修特別控除の額"
V_RENO = "所得税_住宅特定改修特別税額控除の額"
V_NEW = "所得税_認定住宅等新築等特別税額控除の額"


def sim(year: int, **inputs: Any):
    """1人分の simulation（与えた変数だけを入力にする）。"""
    period = str(year)
    return SimulationBuilder().build_from_entities(system(), {"人物一覧": {"p": {k: {period: v} for k, v in inputs.items()}}})


def credit(rid: str, pid: str, year: int, ctype: str, amount: int, **extra: Any) -> dict[str, Any]:
    return {
        "id": rid,
        "kind": "external_tax_credit",
        "roles": {"person": pid},
        "when": {"tax_year": year},
        "amounts": {"credit_amount": amount},
        "attributes": {"credit_type": ctype},
        **extra,
    }


class TestDeductCredits(unittest.TestCase):
    """[CR] §4：㉜ から ㉝・㉞・㉟・㊱〜㊳・㊴〜㊶ を差し引き、赤字は0。"""

    def test_order_is_the_tebiki_order(self) -> None:
        self.assertEqual(
            CREDIT_ORDER, ("配当控除", "事業所得等の特例に係る税額控除", "住宅借入金等特別控除", "政党等寄附金等特別控除", "住宅耐震改修特別控除等")
        )

    def test_boundary_at_tax(self) -> None:
        # 控除の合計が税額と同じ → 0、1円少ない → 1、1円多い → 0（赤字にしない）
        self.assertEqual(deduct_credits(100_000, [10_000, 20_000, 30_000, 15_000, 25_000]).差引所得税額, 0)
        self.assertEqual(deduct_credits(100_000, [10_000, 20_000, 30_000, 15_000, 24_999]).差引所得税額, 1)
        r = deduct_credits(100_000, [10_000, 20_000, 30_000, 15_000, 25_001])
        self.assertEqual(r.差引所得税額, 0)
        self.assertEqual(r.差し引いた額, (10_000, 20_000, 30_000, 15_000, 25_000))  # 最後の控除は残った税額まで

    def test_earlier_credit_is_used_first(self) -> None:
        # 税額 50,000：㉞ 40,000 が先に全部、㉟ 30,000 は残り 10,000 まで、㊴〜㊶ は0
        r = deduct_credits(50_000, [0, 40_000, 30_000, 0, 20_000])
        self.assertEqual((r.差引所得税額, r.差し引いた額), (0, (0, 40_000, 10_000, 0, 0)))

    def test_rejects_negative(self) -> None:
        with self.assertRaises(ValueError):
            deduct_credits(1_000, [-1])
        with self.assertRaises(ValueError):
            deduct_credits(-1, [0])


class TestCategories(unittest.TestCase):
    def test_business_category(self) -> None:
        # [CR] §2：㉞ は「区分」に「1」
        self.assertEqual(business_credit_category(0), NO_CATEGORY)
        self.assertEqual(business_credit_category(1), "1")

    def test_housing_category(self) -> None:
        # [CR] §3：住宅耐震改修 1・住宅特定改修 2・認定住宅等新築等 3・複数 4
        self.assertEqual(housing_credit_category(0, 0, 0), NO_CATEGORY)
        self.assertEqual(housing_credit_category(1, 0, 0), "1")
        self.assertEqual(housing_credit_category(0, 1, 0), "2")
        self.assertEqual(housing_credit_category(0, 0, 1), "3")
        self.assertEqual(housing_credit_category(1, 0, 1), "4")
        self.assertEqual(housing_credit_category(1, 1, 1), "4")


class TestFormulas(unittest.TestCase):
    def test_base_tax_subtracts_external_credits(self) -> None:
        # 算出 100,000 − 配当 10,000 − ㉞ 20,000 − ㉟ 30,000 − 政党等 5,000 − ㊴〜㊶（15,000＋10,000）＝ 10,000
        s = sim(
            2025,
            所得税_算出税額=100_000,
            所得税_配当控除の額=10_000,
            所得税_住宅借入金等特別控除の額=30_000,
            所得税_政党等寄附金特別控除等の額=5_000,
            **{V_BIZ: 20_000, V_SEISMIC: 15_000, V_RENO: 10_000, V_NEW: 0},
        )
        self.assertEqual(int(s.calculate("所得税_住宅耐震改修特別控除等の額", "2025")[0]), 25_000)
        self.assertEqual(s.calculate("所得税_住宅耐震改修特別控除等の区分", "2025")[0], "4")
        self.assertEqual(s.calculate("所得税_事業所得等の特例に係る税額控除の区分", "2025")[0], "1")
        self.assertEqual(int(s.calculate("所得税_基準所得税額", "2025")[0]), 10_000)

    def test_base_tax_is_zero_when_credits_exceed(self) -> None:
        s = sim(2026, 所得税_算出税額=30_000, 所得税_配当控除の額=0, 所得税_住宅借入金等特別控除の額=0, 所得税_政党等寄附金特別控除等の額=0,
                **{V_BIZ: 0, V_SEISMIC: 0, V_RENO: 0, V_NEW: 30_001})
        self.assertEqual(int(s.calculate("所得税_基準所得税額", "2026")[0]), 0)
        self.assertEqual(s.calculate("所得税_住宅耐震改修特別控除等の区分", "2026")[0], "3")
        self.assertEqual(s.calculate("所得税_事業所得等の特例に係る税額控除の区分", "2026")[0], NO_CATEGORY)


class TestFormFields(unittest.TestCase):
    """第一表の ㉞・㊴〜㊶ の欄と区分（KOA020-01.yaml）。区分が「なし」なら空欄、ほかは区分の値を写す。"""

    def test_fields(self) -> None:
        from okura_core.forms import FieldStatus, fill_forms

        from .test_forms import P, YEAR, first_table, values

        on = first_table(
            fill_forms(
                values(事業所得等の特例に係る税額控除の額=20000, 事業所得等の特例に係る税額控除の区分="1", 住宅耐震改修特別控除等の額=25000, 住宅耐震改修特別控除等の区分="4"),
                P,
                YEAR,
            )
        )
        self.assertEqual((on.field_at("税金の計算/㉞").value, on.field_at("税金の計算/㉞/区分").value), (20000, "1"))
        self.assertEqual((on.field_at("税金の計算/住宅耐震改修特別控除等").value, on.field_at("税金の計算/住宅耐震改修特別控除等/区分").value), (25000, "4"))
        off = first_table(
            fill_forms(
                values(事業所得等の特例に係る税額控除の額=0, 事業所得等の特例に係る税額控除の区分=NO_CATEGORY, 住宅耐震改修特別控除等の額=0, 住宅耐震改修特別控除等の区分=NO_CATEGORY),
                P,
                YEAR,
            )
        )
        self.assertIs(off.field_at("税金の計算/㉞/区分").status, FieldStatus.BLANK)
        self.assertIs(off.field_at("税金の計算/住宅耐震改修特別控除等/区分").status, FieldStatus.BLANK)
        self.assertEqual(off.field_at("税金の計算/住宅耐震改修特別控除等").value, 0)


class TestInputs(unittest.TestCase):
    def test_types_go_to_their_variables_and_other_years_are_ignored(self) -> None:
        recs = [
            credit("a", "p", 2025, "business_income_special", 20_000),
            credit("b", "p", 2025, "seismic_retrofit", 15_000, mark="見積り"),
            credit("c", "p", 2025, "specified_housing_renovation", 10_000),
            credit("d", "p", 2024, "certified_housing_new_build", 99_000),
        ]
        out = ModuleInputs()
        external_credit_inputs(out, "p", external_credits_by_person(recs, 2025))
        self.assertEqual(out.exclusions, [])
        got = {var: (out.values[(var, "p")].value, out.values[(var, "p")].record_ids) for var in EXTERNAL_CREDIT_VARIABLES.values()}
        self.assertEqual(got, {V_BIZ: (20_000, ("a",)), V_SEISMIC: (15_000, ("b",)), V_RENO: (10_000, ("c",)), V_NEW: (0, ())})
        self.assertEqual(out.values[(V_SEISMIC, "p")].states, frozenset({State.from_mark("見積り")}))

    def test_two_records_of_one_type_are_out_of_scope(self) -> None:
        # TX-26：同じ人・年分・種類に2件以上は対象外（その種類の変数だけ）。違う種類は合計する（区分4）ので対象外にしない
        recs = [credit("a", "p", 2025, "seismic_retrofit", 1_000), credit("b", "p", 2025, "seismic_retrofit", 2_000), credit("c", "p", 2025, "certified_housing_new_build", 3_000)]
        out = ModuleInputs()
        external_credit_inputs(out, "p", external_credits_by_person(recs, 2025))
        self.assertEqual([(e.variable, e.reason.reason, e.reason.record_ids) for e in out.exclusions], [(V_SEISMIC, MULTIPLE_EXTERNAL_CREDIT_REASON, ("a", "b"))])
        self.assertEqual(out.values[(V_NEW, "p")].value, 3_000)

    def test_other_person_is_separate(self) -> None:
        out = ModuleInputs()
        external_credit_inputs(out, "q", external_credits_by_person([credit("a", "p", 2025, "business_income_special", 5_000)], 2025))
        self.assertEqual(out.values[(V_BIZ, "q")].value, 0)


if __name__ == "__main__":
    unittest.main()
