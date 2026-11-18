"""kyuyo の対象外の一覧 (c) を直した箇所の境目（ユニットテスト。2026-11-11、D24③）。

- KY-01：役員の利益連動の賞与の収入すべき時期（所基通36−9(2)：docs/public-sources/20261111_impl-research_kyuyo-jiki-laws-and-nta.md §2.1）。
- KY-03：同じ月に交通手段の違う通勤の状況（一次情報なし：候補の全部を両端に。D21 R6・D22 S1）。
- 障害者の片道2km未満の自動車通勤（質疑応答事例 03/18：docs/public-sources/20261111_impl-research_tsukin-laws-and-nta.md §4.4）。
"""

from __future__ import annotations

import datetime as _dt
import unittest
from typing import Any

from okura_core.rules.kyuyo.inputs import _death_class, due_date
from okura_core.rules.kyuyo.tsukin import Limit, mixed_limit, monthly_limit, versions_from_parameters

from .support import system


def _bonus(**attrs: Any) -> dict[str, Any]:
    base = {"counterparty": "架空の会社", "payment_type": "officer_bonus_by_resolution", "due_on": "2027-01-10"}
    base.update(attrs)
    return {"id": "s-1", "kind": "salary_payment", "roles": {"recipient": "p-1"}, "when": {"on": "2027-01-10"}, "attributes": base, "amounts": {"gross": 1}}


def _r8() -> Any:
    return next(v for v in versions_from_parameters(system().get_parameters_at_instant("2026-01-01")) if v.key == "令和8年4月以後")


class OfficerBonusDueDateTest(unittest.TestCase):
    def test_resolution_date_decides_the_year_not_due_on(self) -> None:
        self.assertEqual(due_date(_bonus(resolution_on="2026-12-25")), _dt.date(2026, 12, 25))

    def test_amount_fixed_date_when_only_the_total_was_resolved(self) -> None:
        self.assertEqual(due_date(_bonus(resolution_on="2026-12-25", amount_fixed_on="2027-01-05")), _dt.date(2027, 1, 5))

    def test_missing_resolution_date_is_an_input_gap(self) -> None:
        self.assertIsNone(due_date(_bonus()))

    def test_other_payments_use_due_on(self) -> None:
        rec = _bonus(resolution_on="2026-12-25")
        rec["attributes"]["payment_type"] = "bonus"
        self.assertEqual(due_date(rec), _dt.date(2027, 1, 10))

    def test_death_is_compared_with_the_resolution_date(self) -> None:
        rec = _bonus(resolution_on="2026-06-30", due_on="2026-07-31")
        self.assertEqual(_death_class(rec, _dt.date(2026, 7, 1)), "before")  # 支給日は死亡後でも、決議等の日が死亡前
        self.assertEqual(_death_class(rec, _dt.date(2026, 6, 30)), "open")  # 同じ日は判断の分かれ目（従来どおり）


class MixedMeansTest(unittest.TestCase):
    def test_range_spans_every_means(self) -> None:
        v = _r8()
        vehicle = monthly_limit({"means": "vehicle", "one_way_km": {"num": 5, "den": 1}}, None, v)
        transit = monthly_limit({"means": "transit"}, 20_000, v)
        m = mixed_limit([vehicle, transit])
        self.assertEqual((m.low, m.high, m.split, m.needs_fare), (4_200, 20_000, True, False))

    def test_same_amount_is_not_split(self) -> None:
        m = mixed_limit([Limit(4_200, 4_200), Limit(4_200, 4_200)])
        self.assertFalse(m.split)


class DisabledShortDistanceTest(unittest.TestCase):
    def test_under_2km_is_zero_unless_disabled(self) -> None:
        v = _r8()
        st = {"means": "vehicle", "one_way_km": {"num": 199, "den": 100}}
        self.assertEqual(monthly_limit(st, 6_000, v), Limit(0, 0))
        d = monthly_limit(st, 6_000, v, disabled=True)
        self.assertEqual((d.low, d.high, d.split, d.needs_fare), (0, 6_000, True, False))
        u = monthly_limit(st, None, v, disabled=True)
        self.assertEqual((u.low, u.high, u.needs_fare), (0, 150_000, True))

    def test_2km_or_more_is_not_affected(self) -> None:
        v = _r8()
        st = {"means": "vehicle", "one_way_km": {"num": 2, "den": 1}}
        self.assertEqual(monthly_limit(st, 6_000, v, disabled=True).high, 4_200)

    def test_special_circumstances_judgment_decides(self) -> None:
        """判断.障害者の通勤の特別の事情（2026-11-12）：真なら合理的な運賃の額、偽なら全額課税（両端にしない）。"""
        v = _r8()
        st = {"means": "vehicle", "one_way_km": {"num": 199, "den": 100}}
        self.assertEqual(monthly_limit(st, 6_000, v, disabled=True, special=True), Limit(6_000, 6_000))
        self.assertEqual(monthly_limit(st, 6_000, v, disabled=True, special=False), Limit(0, 0))
        u = monthly_limit(st, None, v, disabled=True, special=True)
        self.assertEqual((u.low, u.high, u.needs_fare, u.split), (0, 150_000, True, False))


class UncollectibleSalaryTest(unittest.TestCase):
    """KY-08（2026-11-12）：未払のまま回収できなくなった給与（所法64①・所令180②：docs/public-sources/20261112_impl-research4_shotoku-laws-and-nta.md §1）。"""

    def _ctx(self, recs: list[dict[str, Any]]) -> Any:
        from okura_core.registry import YearContext

        ir = {"schema_version": "0", "persons": [{"id": "p-1", "birth_on": "1980-01-01"}], "relations": [], "residences": [], "insurance_memberships": [],
              "facts": recs, "assets": [], "filed_documents": [], "judgments": [], "choices": []}  # fmt: skip
        return YearContext(ir, 2026, ("p-1",))

    def _pay(self, **kw: Any) -> dict[str, Any]:
        amounts = {"gross": 300_000, **kw.pop("amounts", {})}
        return {"id": "s-1", "kind": "salary_payment", "roles": {"recipient": "p-1"}, "when": {"on": "2026-12-25"},
                "attributes": {"counterparty": "架空の会社", "due_on": "2026-12-25", **kw}, "amounts": amounts}  # fmt: skip

    def test_amount_and_limits(self) -> None:
        from okura_core.rules.kyuyo.inputs import _uncollectible

        pay = self._pay(unpaid=True, amounts={"uncollectible_amount": 300_000})
        self.assertEqual(_uncollectible(self._ctx([pay]), "p-1", [pay]).amount, 300_000)
        paid = self._pay(amounts={"uncollectible_amount": 1})  # 未払でない支払に書いた：入力の矛盾
        self.assertIsNotNone(_uncollectible(self._ctx([paid]), "p-1", [paid]).reason)
        # 損失を生じうる所得の記録がある人も、2026-11-12 から所令180②一の上限を当てて計算する（test_kyuyo_uncollectible.py）
