"""規則モジュール income_totals の入力の組み立て（rules/income_totals/inputs.py）：提出した申告書の記載 → 繰り越された損失の入力。

条文の要件：前年以前3年内（所法70①・71①、措法37の12の2⑤）、青色の年分（所法70①）、連続して申告（所法70④・71②、措法37の12の2⑦）、
docs/public-sources/20261109_round2_aoiro-laws-and-nta.md §5.2、docs/public-sources/20261109_round3_shibo-shukkoku-laws-and-nta.md §8、
docs/public-sources/20261109_round2b_kabu-law-and-nta.md §6。金額は架空。
"""

from __future__ import annotations

import unittest
from typing import Any

from okura_core.money import INT32_MAX
from okura_core.registry import Decided, YearContext
from okura_core.rules.income_totals.inputs import (
    V_NET_BY_YEAR,
    CARRYBACK_CHOICE,
    PLAN_JUDGMENT,
    STOCK_CHOICE,
    V_CHOSEN_BACK,
    V_PREV_BLUE,
    V_PREV_RET,
    V_PREV_RET_STATED,
    V_PREV_TIMBER,
    V_PREV_TAX,
    V_PREV_TAXABLE,
    V_TIMELY,
    V2_BACK,
    V2_PRIOR,
    V2_TAXABLE,
    SECOND_FIELD,
    SUSPENSION_JUDGMENT,
    second_key,
    V_CASUALTY,
    V_LISTED,
    V_NET,
    V_OFFSET,
    build_inputs,
    carried_casualty_loss,
    carried_listed_loss,
    carried_net_loss,
    carry_key,
    carryback_relevant,
    offset_key,
    offset_relevant,
    returns_by_year,
)

from .support import make_ir, person


def ret(rid: str, tax_year: int, *amounts: dict[str, Any], doc: str = "final_return", person_id: str = "p") -> dict[str, Any]:
    attrs: dict[str, Any] = {"document_type": doc, "tax_year": tax_year, "recipient": "tax_office"}
    if amounts:
        attrs["reported_amounts"] = list(amounts)
    return {"id": rid, "kind": "filed_document", "roles": {"filer": person_id}, "when": {"on": f"{tax_year + 1}-03-10"}, "attributes": attrs}


def item(name: str, amount: int, origin: int | None = None) -> dict[str, Any]:
    d: dict[str, Any] = {"item": name, "amount": amount}
    if origin is not None:
        d["origin_tax_year"] = origin
    return d


def approval(first_year: int, pid: str = "p") -> dict[str, Any]:
    return {
        "id": f"blue-{first_year}",
        "kind": "blue_return_procedure",
        "roles": {"person": pid},
        "when": {"on": f"{first_year}-03-01"},
        "attributes": {"procedure": "approval_notice", "first_tax_year": first_year},
    }


def ctx(year: int, *filed: dict[str, Any], facts: list[dict[str, Any]] | None = None, decided: dict | None = None, choices: list | None = None) -> YearContext:
    ir = make_ir([person("p")], facts or [], filed_documents=list(filed), choices=choices or [])
    return YearContext(ir, year, ("p",), decided)


def net(c: YearContext) -> Any:
    return carried_net_loss(c, "p", returns_by_year(c, "p"))


class TestCarriedNetLoss(unittest.TestCase):
    def test_c1_shape_blue_year_loss_in_the_window(self) -> None:
        # 2025年の純損失 100万円（青色）→ 2026年分へ繰り越す（docs/measurements/20261109_round2_aoiro-fetch-and-checks.md §4.3 C1）
        c = ctx(2026, ret("r25", 2025, item("net_loss_total", 1_000_000)), facts=[approval(2025)])
        got = net(c)
        self.assertEqual((got.value, got.reasons), (1_000_000, []))
        self.assertIn("r25", got.record_ids)

    def test_oldest_origin_in_the_window_and_used_and_carryback(self) -> None:
        # 前年以前3年内：2026年分の2023年の損失は使える。使った額・繰り戻した額を引く（所法70①かっこ書）
        c = ctx(
            2026,
            ret("r23", 2023, item("net_loss_total", 900_000), item("net_loss_carryback", 100_000)),
            ret("r24", 2024, item("net_loss_carryforward_used", 200_000, 2023)),
            ret("r25", 2025, item("net_loss_carryforward_used", 300_000, 2023)),
            facts=[approval(2020)],
        )
        got = net(c)
        self.assertEqual((got.value, got.reasons), (300_000, []))

    def test_loss_older_than_three_years_is_gone(self) -> None:
        # §4.3 C2 の形：2022年の損失は2026年分では使えない（前年以前3年内の外）
        c = ctx(2026, ret("r22", 2022, item("net_loss_total", 800_000)), ret("r25", 2025), facts=[approval(2020)])
        got = net(c)
        self.assertEqual((got.value, got.reasons), (0, []))

    def test_sum_of_two_origin_years(self) -> None:
        # §4.3 C3 の年をずらした形（2024・2025年の純損失 各50万円 → 2026年分へ合計100万円）
        c = ctx(2026, ret("r24", 2024, item("net_loss_total", 500_000)), ret("r25", 2025, item("net_loss_total", 500_000)), facts=[approval(2020)])
        self.assertEqual(net(c).value, 1_000_000)

    def test_missing_return_of_intermediate_year_is_out_of_scope(self) -> None:
        # 所法70④：連続して申告している場合に限る。途中の年分の記録がなければ決められない
        c = ctx(2026, ret("r24", 2024, item("net_loss_total", 500_000)), facts=[approval(2020)])
        got = net(c)
        self.assertEqual(got.value, 500_000)
        self.assertTrue(any("連続して" in r and "2025" in r for r in got.reasons))

    def test_not_blue_is_out_of_scope(self) -> None:
        # 青色の承認の記録がなければ決められない（白色の変動所得等の繰越は後の段：D21 R3）
        c = ctx(2026, ret("r25", 2025, item("net_loss_total", 500_000)))
        got = net(c)
        self.assertEqual(got.value, 0)
        self.assertTrue(any("青色" in r for r in got.reasons))

    def test_revocation_record_makes_it_undecided(self) -> None:
        rev = {
            "id": "blue-rev",
            "kind": "blue_return_procedure",
            "roles": {"person": "p"},
            "when": {"on": "2025-11-01"},
            "attributes": {"procedure": "revocation_notice", "revoked_from_tax_year": 2024},
        }
        c = ctx(2026, ret("r25", 2025, item("net_loss_total", 500_000)), facts=[approval(2020), rev])
        self.assertTrue(any("青色" in r for r in net(c).reasons))

    def test_two_returns_for_a_year_is_out_of_scope(self) -> None:
        c = ctx(2026, ret("r25a", 2025, item("net_loss_total", 500_000)), ret("r25b", 2025, item("net_loss_total", 600_000)), facts=[approval(2020)])
        self.assertTrue(any("複数" in r for r in net(c).reasons))

    def test_five_year_carryforward_is_later_stage(self) -> None:
        # 特定非常災害の5年の繰越（所法70の2）は後の段（D22 S12）
        c = ctx(2026, ret("r25", 2025, item("net_loss_carryforward_used", 100_000, 2020)), facts=[approval(2019)])
        self.assertTrue(any("5年" in r for r in net(c).reasons))

    def test_inconsistent_amounts(self) -> None:
        c = ctx(2026, ret("r24", 2024, item("net_loss_total", 100_000)), ret("r25", 2025, item("net_loss_carryforward_used", 200_000, 2024)), facts=[approval(2020)])
        self.assertTrue(any("負" in r for r in net(c).reasons))

    def test_both_years_shift(self) -> None:
        # 令和7年分：2024年の純損失は使える、2021年の損失は使えない
        c = ctx(2025, ret("r24", 2024, item("net_loss_total", 700_000)), ret("r21", 2021, item("net_loss_total", 700_000)), facts=[approval(2020)])
        self.assertEqual(net(c).value, 700_000)


class TestCarriedCasualtyAndListed(unittest.TestCase):
    def test_shibo_7(self) -> None:
        # docs/measurements/20261109_round3_shibo-shukkoku-fetch-and-calc.md §4 [7]：2026年分、繰越し 2023年 500,000・2025年 300,000
        c = ctx(
            2026,
            ret("r23", 2023),
            ret("r24", 2024),
            ret("r25", 2025, item("casualty_loss_carryforward", 500_000, 2023), item("casualty_loss_carryforward", 300_000, 2025)),
        )
        got = carried_casualty_loss(c, returns_by_year(c, "p"))
        self.assertEqual((got.value, got.reasons), (800_000, []))

    def test_casualty_requires_consecutive_returns(self) -> None:
        c = ctx(2026, ret("r25", 2025, item("casualty_loss_carryforward", 500_000, 2023)))
        got = carried_casualty_loss(c, returns_by_year(c, "p"))
        self.assertTrue(any("連続して" in r for r in got.reasons))

    def test_casualty_older_than_three_years_is_later_stage(self) -> None:
        c = ctx(2026, ret("r25", 2025, item("casualty_loss_carryforward", 500_000, 2022)))
        got = carried_casualty_loss(c, returns_by_year(c, "p"))
        self.assertTrue(any("5年" in r for r in got.reasons))

    def test_last_return_missing_but_earlier_lists_carryforward(self) -> None:
        c = ctx(2026, ret("r24", 2024, item("casualty_loss_carryforward", 500_000, 2024)))
        got = carried_casualty_loss(c, returns_by_year(c, "p"))
        self.assertTrue(any("2025年分の申告書の記録がない" in r for r in got.reasons))

    def test_listed_loss(self) -> None:
        # 第三表「翌年以後に繰り越される損失の金額」（docs/public-sources/20261109_round2b_kabu-law-and-nta.md §11.1 の 96）
        c = ctx(2026, ret("r24", 2024), ret("r25", 2025, item("listed_stock_loss_carryforward", 400_000, 2024)))
        got = carried_listed_loss(c, returns_by_year(c, "p"))
        self.assertEqual((got.value, got.reasons), (400_000, []))


class TestBuildInputs(unittest.TestCase):
    def test_every_person_gets_every_input_and_exclusions(self) -> None:
        c = ctx(2026, ret("r25", 2025, item("net_loss_total", 500_000)))
        out = build_inputs(c)
        self.assertEqual(out.values[(V_NET, "p")].value, 0)  # 対象外の入力には0を入れる
        self.assertEqual(out.values[(V_CASUALTY, "p")].value, 0)
        self.assertEqual(out.values[(V_LISTED, "p")].value, 0)
        self.assertEqual(out.values[(V_OFFSET, "p")].value, False)  # 上場株式等の記録がない人
        # 生じた年分ごとの内訳（filing.py が使う入力）も合計と同じ理由で対象外になる
        self.assertEqual([e.variable for e in out.exclusions], [V_NET, *V_NET_BY_YEAR])

    def test_stock_choice_is_read_when_relevant(self) -> None:
        sale = {"id": "s", "kind": "security_sale", "roles": {"seller": "p"}, "when": {"on": "2026-06-01"},
                "amounts": {"proceeds": 100}, "attributes": {"security_class": "listed_stock"}}
        div = {"id": "d", "kind": "dividend", "roles": {"recipient": "p"}, "when": {"on": "2026-06-01"},
               "amounts": {"gross": 100}, "attributes": {"security_class": "listed_stock", "account_type": "other_account"}}
        decided = {(STOCK_CHOICE, offset_key("p")): Decided(True, ("c-1",), frozenset(), open=False)}
        c = ctx(2026, facts=[sale, div], decided=decided)
        self.assertTrue(offset_relevant(c, "p"))
        out = build_inputs(c)
        self.assertEqual(out.values[(V_OFFSET, "p")].value, True)
        self.assertEqual(out.values[(V_OFFSET, "p")].record_ids, ("c-1",))
        self.assertEqual(carry_key("p"), "p:上場株式等の譲渡損失の繰越控除")


class TestCarrybackInputs(unittest.TestCase):
    """繰戻しの入力（前年分の申告書の記載・選択.損失申告と繰戻し・計画.申告の方法と時期）。"""

    def _ctx(self, *filed: dict[str, Any], choice: Any = 500_000, within: bool | None = True, facts: list | None = None) -> YearContext:
        decided = {
            (CARRYBACK_CHOICE, "p"): Decided(choice, ("c-back",), frozenset(), open=False),
            (PLAN_JUDGMENT, "p"): Decided({"method": "paper", **({} if within is None else {"within_deadline": within})}, ("j-plan",), frozenset(), open=False),
        }
        choices = [
            {"id": "c-back", "kind": CARRYBACK_CHOICE, "chosen_by": "p", "chosen_at": "2027-02-01T10:00:00+09:00", "subject": {"person": "p"},
             "when": {"tax_year": 2026}, "value": {"file_loss_return": True, "carryback_amount": 500_000}}
        ]
        return ctx(2026, *filed, facts=facts if facts is not None else [approval(2020)], decided=decided, choices=choices)

    def test_values_from_the_last_return(self) -> None:
        c = self._ctx(ret("r25", 2025, item("taxable_income_total", 3_000_000), item("income_tax_after_credits", 202_500)))
        self.assertTrue(carryback_relevant(c, "p"))
        out = build_inputs(c)
        self.assertEqual(out.values[(V_PREV_TAXABLE, "p")].value, 3_000_000)
        self.assertEqual(out.values[(V_PREV_TAX, "p")].value, 202_500)
        self.assertEqual(out.values[(V_PREV_BLUE, "p")].value, True)
        self.assertEqual(out.values[(V_CHOSEN_BACK, "p")].value, 500_000)
        self.assertEqual(out.values[(V_CHOSEN_BACK, "p")].record_ids, ("c-back",))
        self.assertEqual(out.values[(V_TIMELY, "p")].value, True)
        self.assertEqual(out.values[(V_PREV_RET_STATED, "p")].value, False)
        self.assertEqual(out.exclusions, [])

    def test_retirement_and_timber_items(self) -> None:
        # 所令271①三の控除先（課税退職所得金額・課税山林所得金額）の記載。両方あれば「記載がある」
        c = self._ctx(ret("r25", 2025, item("taxable_income_total", 1), item("income_tax_after_credits", 1), item("taxable_retirement_income", 400_000), item("taxable_timber_income", 0)))
        out = build_inputs(c)
        self.assertEqual(out.values[(V_PREV_RET, "p")].value, 400_000)
        self.assertEqual(out.values[(V_PREV_TIMBER, "p")].value, 0)
        self.assertEqual(out.values[(V_PREV_RET_STATED, "p")].value, True)

    def test_missing_records_exclude_only_when_carrying_back(self) -> None:
        for filed, facts, needle in (
            ((), [approval(2020)], "記録が1件に決まらない"),
            ((ret("r25", 2025, item("taxable_income_total", 1), item("income_tax_after_credits", 1)),), [], "青色申告書か"),
            ((ret("r25", 2025, item("taxable_income_total", 1)),), [approval(2020)], "税額控除後"),
        ):
            with self.subTest(needle=needle):
                out = build_inputs(self._ctx(*filed, facts=facts))
                self.assertEqual({e.variable for e in out.exclusions}, {V_PREV_TAXABLE, V_PREV_TAX, V_PREV_BLUE, V_PREV_RET, V_PREV_TIMBER, V_PREV_RET_STATED})
                self.assertIn(needle, out.exclusions[0].reason.reason)
                self.assertFalse(build_inputs(self._ctx(*filed, facts=facts, choice=0)).exclusions)

    def test_deadline_not_stated(self) -> None:
        out = build_inputs(self._ctx(ret("r25", 2025, item("taxable_income_total", 1), item("income_tax_after_credits", 1)), within=None))
        self.assertEqual([e.variable for e in out.exclusions], [V_TIMELY])

    def test_not_relevant_person(self) -> None:
        out = build_inputs(ctx(2026))
        self.assertEqual(out.values[(V_CHOSEN_BACK, "p")].value, 0)
        self.assertEqual(out.values[(V_TIMELY, "p")].value, False)
        self.assertEqual(out.exclusions, [])



class TestSecondPriorCarryback(unittest.TestCase):
    """前々年分への繰戻し（所法140⑤・141④、所令272：docs/public-sources/20261109_round2_aoiro-laws-and-nta.md §5.3、
    docs/public-sources/20261109_round3_shibo-shukkoku-laws-and-nta.md §9）。"""

    CLOSE = {"id": "close", "kind": "blue_return_procedure", "roles": {"person": "p"}, "when": {"on": "2026-06-30"},
             "attributes": {"procedure": "business_transfer_or_closure"}}

    def _filed(self, year: int) -> tuple[dict[str, Any], ...]:
        return (
            ret("r1", year - 1, item("net_loss_total", 1_000_000), item("net_loss_carryback", 200_000)),
            ret("r2", year - 2, item("taxable_income_total", 4_000_000), item("income_tax_after_credits", 300_000)),
        )

    def _ctx(self, year: int, facts: list, decided: dict, choices: list | None = None) -> YearContext:
        return ctx(year, *self._filed(year), facts=[approval(2020), *facts], decided=decided, choices=choices)

    def test_closure_carries_back_the_rest_and_removes_it_from_carryforward(self) -> None:
        # 前年の純損失 100万円のうち前年に 20万円を繰り戻し済み → 残り 80万円を全部前々年分へ。繰越控除の対象は0
        c = self._ctx(2026, [self.CLOSE], {(CARRYBACK_CHOICE, second_key("p")): Decided(INT32_MAX, (), frozenset(), open=True)})
        out = build_inputs(c)
        self.assertEqual(out.values[(V2_BACK, "p")].value, 800_000)
        self.assertEqual(out.values[(V2_PRIOR, "p")].value, 200_000)
        self.assertEqual(out.values[(V2_TAXABLE, "p")].value, 4_000_000)
        self.assertEqual(out.values[(V_NET, "p")].value, 0)
        self.assertEqual(out.exclusions, [])
        # 繰り戻さない候補：繰越控除の対象に残る
        c0 = self._ctx(2026, [self.CLOSE], {(CARRYBACK_CHOICE, second_key("p")): Decided(0, (), frozenset(), open=True)})
        self.assertEqual(build_inputs(c0).values[(V_NET, "p")].value, 800_000)

    def test_no_fact_and_judgment_neither(self) -> None:
        # 事実がなく、選択に額があり、休止等の判断が「どちらでもない」→ 前々年分へは繰り戻せない
        choice = [{"id": "c2", "kind": CARRYBACK_CHOICE, "chosen_by": "p", "chosen_at": "2027-02-01T10:00:00+09:00", "subject": {"person": "p"},
                   "when": {"tax_year": 2026}, "value": {"file_loss_return": True, SECOND_FIELD: 500_000}}]
        decided = {
            (CARRYBACK_CHOICE, second_key("p")): Decided(500_000, ("c2",), frozenset(), open=False),
            (CARRYBACK_CHOICE, "p"): Decided(0, ("c2",), frozenset(), open=False),
            (PLAN_JUDGMENT, "p"): Decided({"within_deadline": True}, (), frozenset(), open=False),
            (SUSPENSION_JUDGMENT, "p"): Decided("neither", (), frozenset(), open=True),
        }
        out = build_inputs(self._ctx(2026, [], decided, choice))
        self.assertEqual(out.values[(V2_BACK, "p")].value, 0)
        self.assertEqual(out.values[(V_NET, "p")].value, 800_000)
        decided[(SUSPENSION_JUDGMENT, "p")] = Decided("considerable_suspension", (), frozenset(), open=True)
        self.assertEqual(build_inputs(self._ctx(2026, [], decided, choice)).values[(V2_BACK, "p")].value, 500_000)

    def test_r7_second_prior_year_uses_the_same_table(self) -> None:
        # 令和7年分の前々年分（令和5年分）の所法89① の表は令和6年分〜令和8年分と同じ（docs/public-sources/20261112_impl-research4_shotoku-laws-and-nta.md §2）
        # → 2026-11-12 から対象外にせず計算する（IT-15）。繰り戻した額は繰越控除から除く
        close = {**self.CLOSE, "when": {"on": "2025-06-30"}}
        out = build_inputs(self._ctx(2025, [close], {(CARRYBACK_CHOICE, second_key("p")): Decided(INT32_MAX, (), frozenset(), open=True)}))
        self.assertEqual(out.exclusions, [])
        self.assertEqual(out.values[(V2_BACK, "p")].value, 800_000)
        self.assertEqual(out.values[(V_NET, "p")].value, 0)


if __name__ == "__main__":
    unittest.main()
