"""規則モジュール other_deductions：雑損控除と政党等寄附金特別控除等のテスト。

期待値の出典：所法72 と TA1110（docs/public-sources/20261109_round2_hoken-kifu-laws.md §6、docs/public-sources/20261109_round2_hoken-kifu-nta-soumu.md §5）、
措法41の18〜41の18の3（docs/public-sources/20261111_impl-research_seito-kifu-laws-and-nta.md §1〜§3・§7）、
テストケースは docs/inferences/20261111_impl-research_seito-kifu-cases.md S1〜S8。テストのデータは架空の家庭。
"""

from __future__ import annotations

import unittest
from fractions import Fraction
from typing import Any

from okura_core import evaluate
from okura_core.registry import Decided, StageValue, YearContext, YearWindow
from okura_core.result import EvaluationResult, State, TimeKey, YenAmount, check_result_json
from okura_core.rules.other_deductions.calc import (
    casualty_deduction,
    donation_credit_rules_from_parameters,
    donation_credits,
    tenth_fraction_matters,
)
from okura_core.rules.other_deductions.casualty import R_ENDED_MISSING, R_NOT_LIVING, R_TIE, STAGE_NAME, STAGE_READS, attribute_claimant
from okura_core.rules.other_deductions.inputs import build_inputs
from okura_core.rounding import FUNCTIONS

from .support import make_ir, make_query, person, salary, system
from .test_other_deductions_calc import calc as sim_calc
from .test_other_deductions_inputs import choice, judgment, open_slots, parentage, reasons, run, seikei, val

T26 = TimeKey("tax_year", 2026)
R10 = Fraction(1, 10)
V_LOSS = "所得税_雑損の損失の金額"
V_REL = "所得税_雑損の災害関連支出の金額"
SID = "判断.雑損の計算:c1"


def _ok(res: Any) -> EvaluationResult:
    assert isinstance(res, EvaluationResult), getattr(res, "errors", res)
    assert check_result_json(res.to_dict()) == []
    return res


def casualty(rid: str = "c1", owner: str = "p-a", on: str = "2026-07-01", cause: str = "storm_or_flood", **amounts: int) -> dict[str, Any]:
    return {
        "id": rid, "kind": "casualty", "roles": {"owner": owner}, "when": {"on": on},
        "amounts": {"pre_loss_value": 2_000_000, "post_loss_value": 500_000, **amounts}, "attributes": {"cause": cause},
    }  # fmt: skip


def expenditure(rid: str, cid: str, payer: str, on: str, amount: int, etype: str = "removal") -> dict[str, Any]:
    return {"id": rid, "kind": "casualty_expenditure", "roles": {"payer": payer}, "when": {"on": on}, "amounts": {"amount": amount}, "attributes": {"casualty_id": cid, "expenditure_type": etype}}


class TestCasualtyFormula(unittest.TestCase):
    """所法72①の足切り（TA1110 の式と同じになること）。"""

    def _d(self, loss: int, related: int, income: int) -> int:
        return casualty_deduction(loss, related, income, FUNCTIONS["floor"], rate=R10, related_limit=50_000)

    def test_first_item_tenth(self) -> None:
        self.assertEqual(self._d(1_000_000, 0, 3_000_000), 700_000)
        self.assertEqual(self._d(200_000, 50_000, 3_000_000), 0)  # 足切り以下

    def test_second_item_related_over_50000(self) -> None:
        # 第2号：min(損失 −（支出 − 5万）, 10分の1) を足切りにする
        self.assertEqual(self._d(400_000, 150_000, 3_000_000), 100_000)  # 足切り＝min(30万, 30万)＝30万
        self.assertEqual(self._d(400_000, 150_000, 1_000_000), 300_000)  # 足切り＝min(30万, 10万)＝10万

    def test_third_item_all_related(self) -> None:
        # 第3号：損失の金額がすべて災害関連支出：足切り＝min(5万, 10分の1)
        self.assertEqual(self._d(300_000, 300_000, 3_000_000), 250_000)
        self.assertEqual(self._d(300_000, 300_000, 200_000), 280_000)

    def test_ta1110_formula_matches(self) -> None:
        for loss, related, income in ((500_000, 100_000, 2_000_000), (1_000, 0, 0), (300_000, 300_000, 3_000_000), (150_000, 60_000, 800_000)):
            with self.subTest(loss=loss, related=related, income=income):
                ta = max(loss - income // 10, related - 50_000, 0)
                self.assertEqual(self._d(loss, related, income), ta)

    def test_income_loss_treated_as_zero(self) -> None:
        self.assertEqual(self._d(100_000, 0, -500_000), 100_000)

    def test_fraction_matters(self) -> None:
        self.assertTrue(tenth_fraction_matters(1_000_000, 0, 3_000_005, R10, 50_000))
        self.assertFalse(tenth_fraction_matters(1_000_000, 0, 3_000_000, R10, 50_000))

    def test_variable_rounding_is_candidate(self) -> None:
        # 10分の1の1円未満は根拠がなく候補で評価（式で候補の変数を引く）
        v = sim_calc(2026, "所得税_雑損控除の額", 所得税_雑損の損失の金額=1_000_000, 所得税_雑損の災害関連支出の金額=0, 所得税_総所得金額等=3_000_005, 所得税_雑損控除の足切りの端数="ceil")
        self.assertEqual(v, 1_000_000 - 300_001)


class TestCasualtyInputs(unittest.TestCase):
    def test_damage_and_expenditure_with_recovery(self) -> None:
        # TA1110 注3：保険金等はまず損害金額から、超える分は災害等関連支出から
        ir = make_ir([person("p-a")], [casualty(insurance_recovery=1_600_000), expenditure("e1", "c1", "p-a", "2026-07-10", 300_000)])
        out = run(ir, 2026, {SID: False})
        self.assertEqual(val(out, V_LOSS, "p-a"), 200_000)  # 損害150万−保険160万→0、支出30万−10万＝20万
        self.assertEqual(val(out, V_REL, "p-a"), 200_000)

    def test_damage_only(self) -> None:
        out = run(make_ir([person("p-a")], [casualty()]), 2026, {SID: False})
        self.assertEqual(val(out, V_LOSS, "p-a"), 1_500_000)
        self.assertEqual(val(out, V_REL, "p-a"), 0)

    def test_not_ordinarily_necessary_asset_is_excluded(self) -> None:
        out = run(make_ir([person("p-a")], [casualty()]), 2026, {SID: True})
        self.assertEqual(val(out, V_LOSS, "p-a"), 0)

    def test_judgment_fixes_value(self) -> None:
        ir = make_ir([person("p-a")], [casualty()], judgments=[judgment("j", "判断.雑損の計算", {"casualty_id": "c1"}, {"not_ordinarily_necessary_asset": False})])
        self.assertNotIn(SID, open_slots(ir, 2026))
        self.assertEqual(val(run(ir, 2026), V_LOSS, "p-a"), 1_500_000)

    def test_acquisition_cost_basis(self) -> None:
        ir = make_ir(
            [person("p-a")],
            [casualty(acquisition_cost=1_000_000)],
            judgments=[judgment("j", "判断.雑損の計算", {"casualty_id": "c1"}, {"not_ordinarily_necessary_asset": False, "loss_measure": "acquisition_cost_basis"})],
        )
        self.assertEqual(val(run(ir, 2026), V_LOSS, "p-a"), 500_000)

    def test_missing_post_value_is_out_of_scope(self) -> None:
        rec = casualty()
        del rec["amounts"]["post_loss_value"]
        out = run(make_ir([person("p-a")], [rec]), 2026, {SID: False})
        self.assertTrue(reasons(out, V_LOSS, "p-a"))

    def test_theft_expenditure_not_disaster_related(self) -> None:
        # 第206条第2項：盗難・横領の原状回復は災害関連支出に入らない（第1項第4号）
        ir = make_ir([person("p-a")], [casualty(cause="theft"), expenditure("e1", "c1", "p-a", "2026-07-10", 80_000, "restoration")])
        out = run(ir, 2026, {SID: False})
        self.assertEqual(val(out, V_LOSS, "p-a"), 1_580_000)
        self.assertEqual(val(out, V_REL, "p-a"), 0)

    def test_expenditure_in_next_year(self) -> None:
        # 通達72−5：災害等関連支出は支出した日の年分
        ir = make_ir([person("p-a")], [casualty(on="2025-07-01"), expenditure("e1", "c1", "p-a", "2026-02-10", 80_000)])
        out = run(ir, 2026, {SID: False})
        self.assertEqual(val(out, V_LOSS, "p-a"), 80_000)
        self.assertEqual(val(out, V_REL, "p-a"), 80_000)

    def test_prior_year_override(self) -> None:
        # 通達72−5 ただし書：1月1日〜3月15日の支出を前年分とする判断
        ir = make_ir(
            [person("p-a")],
            [casualty(on="2025-07-01"), expenditure("e1", "c1", "p-a", "2026-02-10", 80_000)],
            judgments=[judgment("j", "判断.雑損の計算", {"casualty_id": "c1"}, {"not_ordinarily_necessary_asset": False, "expenditure_tax_year": 2025})],
        )
        self.assertEqual(val(run(ir, 2026), V_LOSS, "p-a"), 0)
        self.assertEqual(val(run(ir, 2025), V_LOSS, "p-a"), 1_580_000)

    def test_expenditure_by_another_person_is_read_both_ways(self) -> None:
        # 支払者が控除を受ける人でない支出：含める・含めないの一次情報がない → 含める値で入れ、損失の金額を未確定（決める手段は一次情報）
        ir = make_ir([person("p-a"), person("p-b")], [casualty(), expenditure("e1", "c1", "p-b", "2026-07-10", 80_000)])
        out = run(ir, 2026, {SID: False})
        self.assertEqual(reasons(out, V_LOSS, "p-a"), [])
        self.assertEqual(val(out, V_LOSS, "p-a"), 1_580_000)
        self.assertEqual([s.means.value for s in out.values[(V_LOSS, "p-a")].missing], ["一次情報"])

    def test_theft_removal_is_read_both_ways(self) -> None:
        # 所令206①四「その他これに類する支出」（［PS3-KM］§1）：盗難の除去の支出は類する支出かの一次情報がない → 未確定。災害関連支出には入れない
        ir = make_ir([person("p-a")], [casualty(cause="theft"), expenditure("e1", "c1", "p-a", "2026-07-10", 80_000, "removal")])
        out = run(ir, 2026, {SID: False})
        self.assertEqual(val(out, V_REL, "p-a"), 0)
        self.assertTrue(out.values[(V_LOSS, "p-a")].missing)
        own = run(make_ir([person("p-a")], [casualty(cause="theft"), expenditure("e1", "c1", "p-a", "2026-07-10", 80_000, "restoration")]), 2026, {SID: False})
        self.assertFalse(own.values[(V_LOSS, "p-a")].missing)

    def test_period_after_disaster_ended(self) -> None:
        # 所令206①二（［PS3-KM］§1）：やんだ日 E の1年後の応当日までは期間内、3年後の応当日までは やむを得ない事情 の判断（未入力なら両方）、それより後は数えない
        def ir(paid: str, ended: str | None = "2025-06-30") -> dict[str, Any]:
            rec = casualty(on="2025-06-01")
            if ended:
                rec["attributes"]["disaster_ended_on"] = ended
            return make_ir([person("p-a")], [rec, expenditure("e1", "c1", "p-a", paid, 80_000, "restoration")])

        uid = "判断.雑損の計算:c1:やむを得ない事情"
        self.assertEqual(val(run(ir("2026-06-30"), 2026, {SID: False}), V_REL, "p-a"), 80_000)  # E の1年後の応当日
        self.assertNotIn(uid, open_slots(ir("2026-06-30"), 2026))
        self.assertIn(uid, open_slots(ir("2026-07-01"), 2026))
        self.assertEqual(val(run(ir("2026-07-01"), 2026, {SID: False, uid: True}), V_REL, "p-a"), 80_000)
        self.assertEqual(val(run(ir("2026-07-01"), 2026, {SID: False, uid: False}), V_REL, "p-a"), 0)
        self.assertEqual(val(run(ir("2028-07-01"), 2028, {SID: False}), V_REL, "p-a"), 0)  # 3年後の応当日の翌日
        self.assertNotIn(uid, open_slots(ir("2028-07-01"), 2028))
        self.assertIn(R_ENDED_MISSING, reasons(run(ir("2026-07-01", None), 2026, {SID: False}), V_LOSS, "p-a"))

    def test_business_use_is_not_casualty_deduction(self) -> None:
        # 所法72①かっこ書き：被災事業用資産（第70条第3項）は雑損控除の対象から除く（損失は事業所得等の側）。人の全部を対象外にしない
        rec = casualty()
        rec["attributes"]["business_use"] = True
        out = run(make_ir([person("p-a")], [rec]), 2026)
        self.assertEqual(val(out, V_LOSS, "p-a"), 0)
        self.assertEqual([e for e in out.exclusions if e.person == "p-a"], [])

    def test_restoration_portion_judgment(self) -> None:
        # 通達72−3（…hoken-kifu-nta-soumu.md §5.3）：原状回復の支出のうち判断の額を数える。合計を超える判断は対象外
        facts = [casualty(), expenditure("e1", "c1", "p-a", "2026-07-10", 100_000, "restoration")]
        for portion, loss in ((30_000, 1_530_000), (100_001, None)):
            with self.subTest(portion=portion):
                j = judgment("j", "判断.雑損の計算", {"casualty_id": "c1"}, {"not_ordinarily_necessary_asset": False, "restoration_portion": portion})
                out = run(make_ir([person("p-a")], facts, judgments=[j]), 2026)
                if loss is None:
                    self.assertTrue(reasons(out, V_LOSS, "p-a"))
                else:
                    self.assertEqual(val(out, V_LOSS, "p-a"), loss)

    def test_cause_other_is_out_of_scope(self) -> None:
        out = run(make_ir([person("p-a")], [casualty(cause="other")]), 2026)
        self.assertTrue(reasons(out, V_LOSS, "p-a"))


class TestCasualtyEvaluate(unittest.TestCase):
    def _sc(self, ir: dict[str, Any]) -> Any:
        return _ok(evaluate(ir, make_query((2026,)), system=system())).scenario("base")





    def test_threshold_parameter_by_year(self) -> None:
        for year, limit in ((2025, 580_000), (2026, 620_000)):
            with self.subTest(year=year):
                self.assertEqual(int(system().get_parameters_at_instant(f"{year}-01-01").所得税.雑損控除.親族の総所得金額等の上限), limit)



class TestCasualtyAttribution(unittest.TestCase):
    """所令205（…hoken-kifu-laws.md §6）：親族の資産の損失を控除する居住者。基準額は令和8年分 62万円。上流（扶養の割当て・総所得金額等）はスタブ。"""

    L = 620_000

    def _a(self, living: list[str], measures: dict[str, int], **kw: Any) -> Any:
        kw.setdefault("dependent_of", None)
        kw.setdefault("spouse_claimant", None)
        kw.setdefault("spouses", [])
        return attribute_claimant("c", living, measures, self.L, **kw)

    def test_limit_boundary(self) -> None:
        # 第1項：62万円以下なら親族の資産（生計を一にする居住者の控除）、1円超えれば所有者本人
        # 合計額は総所得金額等（措令4の2⑨・25の11の2⑳ の読替えで上場株式等の所得を加える：［PS3-JJ］§1・§2）
        self.assertEqual(self._a(["a"], {"c": 620_000, "a": 5_000_000}).claimant, "a")
        self.assertEqual(self._a(["a"], {"c": 620_001, "a": 5_000_000}).claimant, "c")
        self.assertEqual(self._a([], {"c": 0}).claimant, "c")

    def test_second_paragraph_order(self) -> None:
        m = {"c": 400_000, "a": 5_000_000, "b": 3_000_000}
        self.assertEqual(self._a(["a", "b"], m, dependent_of="b").claimant, "b")  # 第1号：扶養親族としている人
        self.assertEqual(self._a(["a", "b"], m, spouses=["b"]).claimant, "b")  # 第2号イ：配偶者
        self.assertEqual(self._a(["a", "b"], m).claimant, "a")  # 第2号ロ：合計額が最も大きい人
        self.assertEqual(self._a(["a", "b"], m).candidates, ())
        # 一次情報で決まらない：候補の全部（第1号の人と第2号で決まる人・同額の人）
        x = self._a(["a", "b"], m, dependent_of="x")
        self.assertEqual((x.reason, x.candidates), (R_NOT_LIVING, ("a", "x")))
        tie = self._a(["a", "b"], {**m, "b": 5_000_000})
        self.assertEqual((tie.reason, tie.candidates), (R_TIE, ("a", "b")))

    def test_inputs_put_loss_on_claimant(self) -> None:
        # 子 p-c（総所得金額等 40万円、親 p-a の扶養親族）の資産の損失は p-a に入れ、p-c には入れない（…hoken-kifu-cases.md C8）
        ir = make_ir([person("p-a"), person("p-c", "2005-01-01")], [casualty(owner="p-c")], relations=[parentage("r", "p-a", "p-c", "2005-01-01")])
        income = {"p-a": 5_000_000, "p-c": 400_000}
        sv: dict[tuple[str, str], StageValue] = {}
        for p in ("p-a", "p-c"):
            vals = {
                "所得税_総所得金額": income[p], "所得税_退職所得金額": 0, "所得税_総所得金額等": income[p],
                "所得税_扶養親族等の申告者": "p-a" if p == "p-c" else "", "所得税_扶養親族に当たるか": p == "p-c",
                "所得税_同一生計配偶者に当たるか": False, "所得税_居住者か": True,
            }  # fmt: skip
            for var in STAGE_READS:
                sv[(var, p)] = StageValue(var, p, vals[var], states=frozenset({State.FORECAST}) if p == "p-c" else frozenset())
        window = YearWindow(parameters_at=system().get_parameters_at_instant, stage_values={STAGE_NAME: sv})
        decided = {("判断.雑損の計算", "c1"): Decided(False, (), frozenset(), open=True), ("判断.生計を一にする", "p-a:p-c@2026-07-01"): Decided(True, (), frozenset(), open=True)}
        out = build_inputs(YearContext(ir, 2026, ("p-a", "p-c"), decided, window=window))
        self.assertEqual(out.values[(V_LOSS, "p-a")].value, 1_500_000)
        self.assertEqual(out.values[(V_LOSS, "p-c")].value, 0)
        self.assertTrue(any(State.FORECAST in u.states for u in out.values[(V_LOSS, "p-a")].uses or ()))  # 読んだ値の予測が伝わる


class TestDonationCredits(unittest.TestCase):
    """[SK] §1〜§3 の式と seito-kifu-cases の設例。"""

    def rules(self, year: int = 2026):
        return donation_credit_rules_from_parameters(system().get_parameters_at_instant(f"{year}-01-01").所得税.政党等寄附金特別控除等)

    def credits(self, seito: int = 0, npo: int = 0, koeki: int = 0, special: int = 0, income: int = 3_000_000, tax: int = 100_000):
        return donation_credits(seito, npo, koeki, special, income, tax, self.rules())

    def test_s1_political(self) -> None:
        self.assertEqual(self.credits(seito=30_000), (0, 0, 8_400))

    def test_s2_other_donation_reduces_2000(self) -> None:
        self.assertEqual(self.credits(seito=30_000, special=1_000), (0, 0, 8_700))

    def test_s3_cap_25_percent(self) -> None:
        self.assertEqual(self.credits(seito=2_000_000, income=10_000_000, tax=100_000), (0, 0, 25_000))

    def test_s4_cap_40_percent(self) -> None:
        self.assertEqual(self.credits(seito=2_000_000, income=1_000_000, tax=1_000_000), (0, 0, 119_400))

    def test_s5_npo_after_koeki_credit(self) -> None:
        # 公益 12,300 が先にあるとして NPO の限度は 25,000 − 12,300 ＝ 12,700（式で確かめる：公益は (x−2千)×40% ＝12,300 に合わせる）
        k = self.credits(npo=100_000, koeki=32_750, tax=100_000)
        self.assertEqual(k[0], 12_300)
        self.assertEqual(k[1], 12_700)

    def test_s6_three_kinds_party_separate(self) -> None:
        k, n, s = self.credits(seito=50_000, npo=50_000, koeki=50_000, tax=200_000)
        self.assertEqual(k, 19_200)  # (50,000−2,000)×40%
        self.assertLessEqual(k + n, 50_000)  # 25%枠の共有
        self.assertEqual(n, 20_000)  # (50,000−max(0,2,000−50,000)=50,000)×40%=20,000
        self.assertEqual(s, 15_000)  # 他の寄附 10万 → (50,000−0)×30%＝15,000（別枠の25%＝50,000 以内）

    def test_floor_100(self) -> None:
        # (5,099−2,000)×30%＝929.7 → 900
        self.assertEqual(self.credits(seito=5_099)[2], 900)

    def test_negative_rejected(self) -> None:
        with self.assertRaises(ValueError):
            donation_credits(-1, 0, 0, 0, 0, 0, self.rules())

    def test_formula_variable(self) -> None:
        # 算出税額が 10万円、政党等 30,000、税額控除を選んだ
        v = sim_calc(2026, "所得税_政党等寄附金特別控除等の額", 所得税_税額控除を受ける政党等寄附金の額=30_000, 所得税_算出税額=100_000, 所得税_総所得金額等=3_000_000)
        self.assertEqual(v, 8_400)




if __name__ == "__main__":
    unittest.main()
