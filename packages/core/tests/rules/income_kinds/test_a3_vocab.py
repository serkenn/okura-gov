"""income_kinds の退職・一時・配当・給付に足した語彙（2026-11-12）の境目のユニットテスト。上流はスタブ。

期待値の出典：docs/public-sources/20261112_impl-a3_taishoku-haito-kyufu.md §1〜§3（所令69①一イ〜ハ・70①一・71の2⑬）、
docs/public-sources/20261109_round2b_taishoku-laws-and-guidance.md §2.3（所令70①二イ・ロ・ハ）、
docs/public-sources/20261109_round2b_kabu-law-and-nta.md §2.1（措法8の5①一・③）、
docs/public-sources/20261109_round2b_nenkin-laws-and-guidance.md §4.3（TA1605）、
docs/public-sources/20261109_impl-prep_jigyo-laws-and-nta.md §6（所基通34−1(5)）。テストのデータは架空。
"""

from __future__ import annotations

import datetime as _dt
import unittest
from typing import Any

from okura_core.registry import Decided, ModuleInputs, YearContext, YearWindow
from okura_core.result import Means
from okura_core.rules.income_kinds.inputs import (
    K_RETIRE,
    RETIRE_PARTIAL_OFFICER_REASON,
    V_RET_INCOME,
    V_RET_OFFICER_INCOME,
    V_RET_PRIOR_YEARS,
    V_RET_YEARS,
    V_RETIRE_SALARY,
    V_WF_EXP,
    V_WF_TOTAL,
    _adjusted_period,
    _dividend_interest,
    _retire_salary,
    _retirement,
    _windfall,
    dividend_period_months,
)

from ...support import make_ir, person, system

D = _dt.date


def _ctx(facts: list[dict[str, Any]], value: dict[str, Any] | None = None, *, year: int = 2026, assets: list[dict[str, Any]] | None = None) -> YearContext:
    window = YearWindow(parameters_at=lambda s: system().parameters(s), parameter_root=system().parameters)
    v = value or {"is_retirement_allowance": True}
    return YearContext(make_ir([person("p-1", "1960-01-01")], facts, assets=assets or []), year, ("p-1",),
                       {(K_RETIRE, "p-1"): Decided(v, (), frozenset(), True)}, window=window)  # fmt: skip


def _pay(rid: str, gross: int, on: str, **attrs: Any) -> dict[str, Any]:
    amounts = {"gross": gross, "withholding_tax": 0}
    if "non_officer_portion" in attrs:
        amounts["non_officer_portion"] = attrs.pop("non_officer_portion")
    return {"id": rid, "kind": "retirement_payment", "roles": {"recipient": "p-1"}, "when": {"on": on},
            "amounts": amounts, "attributes": {"counterparty": "甲", **attrs}}  # fmt: skip


def _rec(rid: str, start: str, end: str, **attrs: Any) -> dict[str, Any]:
    return {"id": rid, "kind": "retirement_record", "roles": {"recipient": "p-1"}, "when": {"from_on": start, "to_on": end},
            "attributes": {"counterparty": "甲", "declaration_submitted": True, **attrs}}  # fmt: skip


def _run(facts: list[dict[str, Any]], value: dict[str, Any] | None = None) -> ModuleInputs:
    out = ModuleInputs()
    _retirement(_ctx(facts, value), out)
    return out


class AdjustedPeriodTest(unittest.TestCase):
    def test_earlier_service_added_and_prior_basis_cut(self) -> None:
        # イ：一時勤務しなかった期間前の期間を加算。ハ：前の退職手当等の計算の基礎とされた期間の末日以前は含めない
        rr = _rec("r", "2020-04-01", "2026-03-31", service_adjustments=[
            {"type": "earlier_service_same_payer", "period": {"from_on": "2010-04-01", "to_on": "2015-03-31"}},
            {"type": "prior_allowance_basis", "period": {"from_on": "2010-04-01", "to_on": "2012-03-31"}},
        ])  # fmt: skip
        period, one, bad = _adjusted_period(rr)
        self.assertIsNone(bad)
        self.assertEqual(period, [(D(2012, 4, 1), D(2015, 3, 31)), (D(2020, 4, 1), D(2026, 3, 31))])
        self.assertEqual(one, [])

    def test_proviso_keeps_period_and_deducts_70_1_1(self) -> None:
        # ハただし書：今回の計算の基礎に含めるなら除かず、所令70①一（70③：1年未満切捨て）
        rr = _rec("r", "2010-04-01", "2026-03-31", service_adjustments=[
            {"type": "prior_allowance_basis", "period": {"from_on": "2010-04-01", "to_on": "2013-09-30"}, "included_in_payment_basis": True},
        ])  # fmt: skip
        period, one, _ = _adjusted_period(rr)
        self.assertEqual(period, [(D(2010, 4, 1), D(2026, 3, 31))])
        self.assertEqual([y for y, _ in one], [3])
        out = _run([_pay("a", 10_000_000, "2026-04-10", retired_on="2026-03-31"), rr])
        self.assertEqual(out.exclusions, [])
        self.assertEqual((out.values[(V_RET_YEARS, "p-1")].value, out.values[(V_RET_PRIOR_YEARS, "p-1")].value), (16, 3))


class PartialOfficerTest(unittest.TestCase):
    def test_portion_splits_and_reading_is_undetermined(self) -> None:
        # 所令71の2⑬：使用人10年・役員3年の1回の退職手当等。特定役員の部分＝全体−相当と認められる金額
        facts = [_pay("a", 13_000_000, "2026-04-10", retired_on="2026-03-31", non_officer_portion=8_000_000),
                 _rec("r", "2013-04-01", "2026-03-31", officer_period={"from_on": "2023-04-01", "to_on": "2026-03-31"})]  # fmt: skip
        out = _run(facts)
        self.assertEqual(out.exclusions, [])
        self.assertEqual(out.values[(V_RET_OFFICER_INCOME, "p-1")].value, 5_000_000)
        [m] = [s for s in out.values[(V_RET_INCOME, "p-1")].missing if s.means is Means.PRIMARY_SOURCE]
        self.assertIn("71の2⑬", m.id)

    def test_missing_portion_is_input_shortage(self) -> None:
        facts = [_pay("a", 13_000_000, "2026-04-10", retired_on="2026-03-31"),
                 _rec("r", "2013-04-01", "2026-03-31", officer_period={"from_on": "2023-04-01", "to_on": "2026-03-31"})]  # fmt: skip
        self.assertIn(RETIRE_PARTIAL_OFFICER_REASON, {e.reason.reason for e in _run(facts).exclusions})


class PriorDcLumpSumTest(unittest.TestCase):
    def _facts(self, cur_dc: bool | None) -> list[dict[str, Any]]:
        cur = {} if cur_dc is None else {"old_age_dc_lump_sum": cur_dc}
        return [
            _pay("old", 5_000_000, "2019-04-10", retired_on="2019-03-31", counterparty="乙", old_age_dc_lump_sum=False),
            _rec("rold", "2009-04-01", "2019-03-31", counterparty="乙"),
            _pay("new", 2_000_000, "2026-04-10", retired_on="2026-03-31", **cur),
            _rec("rnew", "2015-04-01", "2026-03-31"),
        ]

    def test_seven_years_before(self) -> None:
        # 所令70①二：7年前の退職手当等は、その年に老齢一時金を受けるとき（ハ：19年内）だけ前の退職手当等
        self.assertEqual(_run(self._facts(False)).values[(V_RET_PRIOR_YEARS, "p-1")].value, 0)
        self.assertEqual(_run(self._facts(True)).values[(V_RET_PRIOR_YEARS, "p-1")].value, 4)  # 2015-04-01〜2019-03-31
        unknown = _run(self._facts(None)).values[(V_RET_PRIOR_YEARS, "p-1")]
        self.assertEqual(unknown.value, 0)
        self.assertTrue(unknown.missing)


class DividendPeriodTest(unittest.TestCase):
    def test_months(self) -> None:
        # 措法8の5③：1月未満の端数は1月、12月を超えるときは12月
        self.assertEqual(dividend_period_months(D(2026, 1, 1), D(2026, 3, 31)), 3)
        self.assertEqual(dividend_period_months(D(2026, 1, 1), D(2026, 4, 1)), 4)
        self.assertEqual(dividend_period_months(D(2025, 1, 1), D(2026, 6, 30)), 12)


class WindfallTest(unittest.TestCase):
    def _wf(self, rid: str, amount: int, **attrs: Any) -> dict[str, Any]:
        return {"id": rid, "kind": "windfall_receipt", "roles": {"recipient": "p-1"}, "when": {"on": "2026-05-01"},
                "amounts": {"amount": amount}, "attributes": {"reason": "gift", "business_related": False, **attrs}}  # fmt: skip

    def _total(self, facts: list[dict[str, Any]], value: dict[str, Any] | None = None) -> Any:
        out = ModuleInputs()
        _windfall(_ctx(facts, value), out)
        return out

    def test_donor_type(self) -> None:
        # 所基通34−1(5)：法人からの贈与は一時所得、個人からの贈与は数えない
        out = self._total([self._wf("w1", 300_000, donor_type="corporation"), self._wf("w2", 500_000, donor_type="individual")])
        v = out.values[(V_WF_TOTAL, "p-1")]
        self.assertEqual((v.value, v.missing), (300_000, ()))

    def test_unpaid_pension(self) -> None:
        # TA1605：未支給年金は一時所得。障害・遺族は非課税かの一次情報がないので未確定
        b = lambda reason: {"id": f"b-{reason}", "kind": "benefit_receipt", "roles": {"recipient": "p-1"}, "when": {"on": "2026-08-01"},  # noqa: E731
                            "amounts": {"amount": 200_000}, "attributes": {"benefit_type": "unpaid_pension_of_deceased", "unpaid_pension_reason": reason}}
        v = self._total([b("old_age")]).values[(V_WF_TOTAL, "p-1")]
        self.assertEqual((v.value, v.missing), (200_000, ()))
        v = self._total([b("survivor")]).values[(V_WF_TOTAL, "p-1")]
        self.assertEqual(v.missing[0].means, Means.PRIMARY_SOURCE)

    def test_retirement_judged_occasional(self) -> None:
        # 判断.退職の性質 で退職手当等に当たらず一時所得：一時所得に数え、退職所得は0
        facts = [_pay("a", 1_000_000, "2026-04-10", retired_on="2026-03-31")]
        value = {"is_retirement_allowance": False, "income_type": "occasional"}
        self.assertEqual(self._total(facts, value).values[(V_WF_TOTAL, "p-1")].value, 1_000_000)
        out = _run(facts, value)
        self.assertEqual((out.values[(V_RET_INCOME, "p-1")].value, out.values[(V_RET_INCOME, "p-1")].missing), (0, ()))
        self.assertIn((V_WF_EXP, "p-1"), self._total(facts, value).values)


class RetirementJudgedSalaryTest(unittest.TestCase):
    """IK-25（2026-11-12）：判断.退職の性質 で退職手当等に当たらず給与（所基通30−1：taishoku §1.2）とした支払。年分は所基通36−9(1)
    （kyuyo-jiki §2.1。支給日の欄がないので支払の日を支給を受けた日とする法令の読み）。"""

    SALARY = {"is_retirement_allowance": False, "income_type": "salary"}

    def _ctx(self, facts: list[dict[str, Any]], value: dict[str, Any] | None, *, year: int = 2026, death: str | None = None,
             judgments: list[dict[str, Any]] | None = None) -> YearContext:  # fmt: skip
        p = {**person("p-1", "1960-01-01"), **({"death_on": death} if death else {})}
        window = YearWindow(parameters_at=lambda s: system().parameters(s), parameter_root=system().parameters)
        v = value or {"is_retirement_allowance": True}
        return YearContext(make_ir([p], facts, judgments=judgments or []), year, ("p-1",), {(K_RETIRE, "p-1"): Decided(v, (), frozenset(), True)}, window=window)

    def _salary(self, facts: list[dict[str, Any]], value: dict[str, Any] | None, **kw: Any) -> Any:
        out = ModuleInputs()
        _retire_salary(self._ctx(facts, value, **kw), out)
        return out.values[(V_RETIRE_SALARY, "p-1")]

    def test_salary_moves_to_kyuyo_and_retirement_income_is_zero(self) -> None:
        facts = [_pay("a", 1_000_000, "2026-04-10", retired_on="2026-03-31")]
        self.assertEqual(self._salary(facts, self.SALARY).value, 1_000_000)
        out = _run(facts, self.SALARY)
        self.assertEqual((out.values[(V_RET_INCOME, "p-1")].value, out.values[(V_RET_INCOME, "p-1")].missing), (0, ()))
        # 退職手当等に当たる判断（未入力の候補も同じ）なら給与に数えない
        self.assertEqual(self._salary(facts, None).value, 0)

    def test_year_is_the_payment_date(self) -> None:
        # 退職の日 2025-12-31・支払 2026-01-15：給与としては支払の年（2026年分）。退職の年分（2025年分）の退職所得は0
        facts = [_pay("a", 800_000, "2026-01-15", retired_on="2025-12-31")]
        js = [{"id": "j-1", "kind": "判断.退職の性質", "subject": {"payment_id": "a"}, "value": self.SALARY}]
        self.assertEqual(self._salary(facts, self.SALARY, judgments=js).value, 800_000)
        self.assertEqual(self._salary(facts, None).value, 0)  # 退職の年分でなく、給与とした判断もない年は読まない
        self.assertEqual(self._salary(facts, self.SALARY, year=2025, judgments=js).value, 0)
        out = ModuleInputs()
        _retirement(self._ctx(facts, self.SALARY, year=2025, judgments=js), out)
        self.assertEqual(out.values[(V_RET_INCOME, "p-1")].value, 0)

    def test_income_type_missing_stays_undetermined(self) -> None:
        facts = [_pay("a", 1_000_000, "2026-04-10", retired_on="2026-03-31")]
        out = _run(facts, {"is_retirement_allowance": False})
        self.assertEqual(out.values[(V_RET_INCOME, "p-1")].missing[0].means, Means.FACT)
        self.assertEqual(self._salary(facts, {"is_retirement_allowance": False}).value, 0)

    def test_payment_after_death_is_split(self) -> None:
        # 死亡の日以後の支払：支給期が死亡の前か（所基通9−17）は支給日の定めで決まり、欄がないので分かれ目（事実）
        facts = [_pay("a", 1_000_000, "2026-04-10", retired_on="2026-03-31")]
        v = self._salary(facts, self.SALARY, death="2026-04-01")
        self.assertEqual((v.value, [m.means for m in v.missing]), (1_000_000, [Means.FACT]))


class DividendInterestLinkTest(unittest.TestCase):
    def test_linked_loans_prorate_each(self) -> None:
        # 所令59：支出に借入れ（loan_id）があれば、その借入れの保有の月数で按分。12,000×6/12＋12,000×12/12
        loans = [
            {"id": "l1", "kind": "loan", "roles": {"borrower": "p-1"}, "when": {"from_on": "2026-07-01"}, "amounts": {"principal": 1_000_000}, "attributes": {}},
            {"id": "l2", "kind": "loan", "roles": {"borrower": "p-1"}, "when": {"from_on": "2020-01-01"}, "amounts": {"principal": 1_000_000}, "attributes": {}},
        ]  # fmt: skip
        exp = lambda rid, loan: {"id": rid, "kind": "business_expense", "roles": {"payer": "p-1"}, "when": {"on": "2026-12-20"},  # noqa: E731
                                 "amounts": {"amount": 12_000}, "attributes": {"expense_category": "dividend_debt_interest", "loan_id": loan}}
        amount, _, _, miss = _dividend_interest(_ctx([exp("e1", "l1"), exp("e2", "l2")], assets=loans), "p-1", 100_000)
        self.assertEqual((amount, miss), (18_000, None))


if __name__ == "__main__":
    unittest.main()
