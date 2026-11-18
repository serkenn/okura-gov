"""hifuyosha の入力の関数（inputs.py）のユニットテスト：注入データ（保険者の運用）の有無で結論が分かれる・分かれない、重複と夫婦共同扶養。

YearContext を判定日の窓口つきで直接作り、注入データ・判断の1か所の値はスタブ（Decided）で与える。データは架空。
"""

from __future__ import annotations

import datetime as dt
import unittest
from typing import Any

from okura_core.injection_points import POINTS
from okura_core.registry import Decided, YearContext, YearWindow, injection_key, injection_kind
from okura_core.rules.hifuyosha import inputs as h
from okura_core.timepoints import judgment_window

from ...support import make_ir, system

ON = dt.date(2026, 6, 1)


def ctx_of(ir: dict[str, Any], decided: dict[tuple[str, str], Decided] | None = None) -> YearContext:
    window = YearWindow(parameters_at=lambda s: system().parameters(s), windows=(judgment_window("健保", ON),))
    persons = tuple(p["id"] for p in ir["persons"])
    return YearContext(ir, ON.year, persons, decided or {}, window=window)


def person(pid: str, birth: str = "1980-01-01") -> dict[str, Any]:
    return {"id": pid, "birth_on": birth}


def member(rid: str, who: str, scheme: str = "kyokai_kenpo", insured: str | None = None) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "id": rid,
        "kind": "medical_insurance",
        "roles": {"member": who},
        "when": {"from_on": "2020-04-01"},
        "attributes": {"scheme": scheme, "insurer_id": "ins-x", "capacity": "insured" if insured is None else "dependent"},
    }
    if insured is not None:
        rec["roles"]["insured"] = insured
    return rec


def forecast(jid: str, insured: str, amount: int) -> dict[str, Any]:
    return {
        "id": jid,
        "kind": "見込み.被保険者の年間収入",
        "judged_by": {"person": insured},
        "judged_at": "2026-05-01T09:00:00+09:00",
        "subject": {"insured": insured},
        "when": {"on": ON.isoformat()},
        "value": {"annual_amount": amount},
        "mark": "予測",
    }


def parent(rid: str, p: str, child: str) -> dict[str, Any]:
    return {"id": rid, "kind": "parentage", "roles": {"parent": p, "child": child}, "when": {"on": "2010-01-01"}, "attributes": {"basis": "birth_mother"}}


class TestSameHousehold(unittest.TestCase):
    """同一の世帯（PSK §2.3、SA2 §1.2・§1.3）：単身赴任の別居は、協会けんぽの型では別居、運用方針の型では同一の世帯。"""

    def setUp(self) -> None:
        self.ir = make_ir(
            [person("a"), person("s")],
            [],
            relations=[
                {"id": "sep", "kind": "separation_reason", "roles": {"person": "a", "other_person": "s"}, "when": {"from_on": "2026-04-01"}, "attributes": {"reason": "member_transfer"}}
            ],
        )

    def same(self, data: dict[str, Any] | None) -> bool:
        decided = {}
        if data is not None:
            decided[(injection_kind(h.P_SAME), injection_key("insurer", "ins-x", ON))] = Decided(data, ("inj-1",), frozenset(), False)
        return h.same_household(ctx_of(self.ir, decided), ON, "a", "s", "健康保険", "ins-x", h.Origin())

    def test_candidates_split(self) -> None:
        # 未注入なら全部の型で評価する（D21 R6）：この家庭では型で結論が分かれる
        results = {c.label: self.same(dict(c.data)) for c in POINTS[h.P_SAME].candidates}
        self.assertEqual(set(results.values()), {True, False})
        self.assertFalse(results["実態の同居（協会けんぽ K-SEN・K-FAQ 10）"])
        self.assertTrue(results["実態の同居・転勤等の別居を含む（UNYO-K 5）"])

    def test_judgment_needs_no_injection(self) -> None:
        # 判断.健保の同一の世帯 があれば保険者の運用を読まない（結論は分かれない）
        self.ir["judgments"].append(
            {
                "id": "j04",
                "kind": "判断.健保の同一の世帯",
                "judged_by": {"person": "a"},
                "judged_at": "2026-05-01T09:00:00+09:00",
                "subject": {"insured": "a", "person": "s"},
                "when": {"from_on": "2026-04-01"},
                "value": {"same_household": True, "criterion": "actual_living"},
            }
        )
        o = h.Origin()
        self.assertTrue(h.same_household(ctx_of(self.ir), ON, "a", "s", "健康保険", "ins-x", o))
        self.assertEqual(o.ids, {"j04"})


class TestAssignments(unittest.TestCase):
    """1人が2人の被保険者の被扶養者にならない（PSK §4.2）。夫婦共同扶養は年間収入の多い方（PSK §3）。"""

    def test_conflict_is_undetermined(self) -> None:
        ir = make_ir(
            [person("a"), person("b"), person("c", "2010-01-01")],
            [],
            insurance_memberships=[member("ma", "a"), member("mb", "b"), member("mc1", "c", insured="a"), member("mc2", "c", insured="b")],
        )
        got = h.assignments(ctx_of(ir), ON)["c"]
        self.assertEqual((got.insured, got.conflict), ("a", ("b",)))
        self.assertEqual([s.target["kind"] for s in got.missing], ["選択.被扶養者の届出"])

    def test_spouses_higher_income(self) -> None:
        ir = make_ir(
            [person("a"), person("b"), person("c", "2010-01-01")],
            [],
            relations=[
                {"id": "mar", "kind": "marriage", "roles": {"spouse_a": "a", "spouse_b": "b"}, "when": {"from_on": "2009-01-01"}},
                parent("pa", "a", "c"),
                parent("pb", "b", "c"),
            ],
            insurance_memberships=[member("ma", "a"), member("mb", "b"), member("mc1", "c", insured="a"), member("mc2", "c", insured="b")],
            judgments=[forecast("fa", "a", 4_000_000), forecast("fb", "b", 5_000_000)],
        )
        got = h.assignments(ctx_of(ir), ON)["c"]
        self.assertEqual((got.insured, got.conflict, got.missing), ("b", (), ()))


class TestKyodo(unittest.TestCase):
    """夫婦共同扶養（PSK §3）：育児休業等の期間中は異動しない（別紙3）、協議が整わなければ標準報酬月額（別紙1(5)）。"""

    def ir(self, *, leave: dict[str, Any] | None = None, dispute: bool = False) -> dict[str, Any]:
        ma, mb = member("ma", "a"), member("mb", "b")
        ma["amounts"], mb["amounts"] = {"standard_monthly_remuneration": 300_000}, {"standard_monthly_remuneration": 280_000}
        facts = [] if leave is None else [{"id": "lv", "kind": "childcare_leave", "roles": {"person": "a"}, "when": {"from_on": "2026-04-01"}, "attributes": leave}]
        decisions = []
        if dispute:
            decisions = [
                {"id": "f1", "kind": "insurer_decision", "roles": {"dependent": "c", "insured": "a"}, "when": {"on": "2026-04-10"}, "attributes": {"decision": "notification_filed"}},
                {"id": "d1", "kind": "insurer_decision", "roles": {"dependent": "c", "insured": "b"}, "when": {"on": "2026-05-01"}, "attributes": {"decision": "rejected", "joint_support_agreement": False}},
            ]
        return make_ir(
            [person("a"), person("b"), person("c", "2020-01-01")],
            facts + decisions,
            relations=[
                {"id": "mar", "kind": "marriage", "roles": {"spouse_a": "a", "spouse_b": "b"}, "when": {"from_on": "2009-01-01"}},
                parent("pa", "a", "c"),
                parent("pb", "b", "c"),
            ],
            insurance_memberships=[ma, mb, member("mc", "c", insured="a")],
            judgments=[forecast("fa", "a", 3_000_000), forecast("fb", "b", 5_000_000)],
        )

    def main(self, ir: dict[str, Any]) -> tuple[str | None, list[str]]:
        got, _info, o = h.kyodo_main(ctx_of(ir), ON, "c", "a")
        return got, [s.id for s in o.missing]

    def test_childcare_leave(self) -> None:
        self.assertEqual(self.main(self.ir()), ("b", []))
        self.assertEqual(self.main(self.ir(leave={"leave_type": "childcare_leave", "child_ids": ["x"]})), ("a", []))
        self.assertEqual(self.main(self.ir(leave={"leave_type": "childcare_leave", "child_ids": ["c"]})), ("b", []))  # 新たに誕生した子
        got, miss = self.main(self.ir(leave={"leave_type": "childcare_leave"}))
        self.assertEqual((got, [m.split(":")[0] for m in miss]), ("a", ["育児休業等の子"]))

    def test_dispute_uses_remuneration(self) -> None:
        self.assertEqual(self.main(self.ir(dispute=True)), ("a", []))


class TestExclusionAndPriority(unittest.TestCase):
    """健保則37の3（PSK §4.1）と、私学共済の優先する扶養義務者（KY §5 PMAC-01）。"""

    def test_designated_activity(self) -> None:
        cs = {"id": "cs", "kind": "civil_status", "roles": {"person": "s"}, "when": {"from_on": "2026-01-01"}, "attributes": {"japanese_national": False}}
        for act, expected in (("medical_care_or_attendance", ["cs"]), ("other", [])):
            ir = make_ir([person("s")], [{**cs, "attributes": {**cs["attributes"], "designated_activity": act}}])
            self.assertEqual([r["id"] for r in h.designated_activity_records(ctx_of(ir), "s", ON)], expected)

    def test_closer_relative_in_employee_insurance(self) -> None:
        def ir(p_scheme: str) -> dict[str, Any]:
            return make_ir(
                [person("g", "1950-01-01"), person("p"), person("c", "2010-01-01")],
                [],
                relations=[parent("r1", "g", "p"), parent("r2", "p", "c")],
                insurance_memberships=[member("mg", "g", "private_school_mutual_aid"), member("mp", "p", p_scheme)],
                judgments=[forecast("fg", "g", 4_000_000), forecast("fp", "p", 3_000_000)],
            )

        self.assertTrue(h.priority_blocked(ctx_of(ir("kyokai_kenpo")), ON, "c", "g", h.Origin()))
        self.assertFalse(h.priority_blocked(ctx_of(ir("national_health_insurance")), ON, "c", "g", h.Origin()))


class TestScholarship(unittest.TestCase):
    """2026-11-11 に足した 見込み.年間収入 の種類（奨学金の貸与・給付）：貸与は含めない、給付は保険者の運用で未確定。"""

    def test_loan_is_excluded_and_grant_is_undetermined(self) -> None:
        def fc(amounts: list[dict[str, Any]]) -> dict[str, Any]:
            return {
                "id": "j-s", "kind": "見込み.年間収入", "judged_by": {"person": "s"}, "judged_at": "2026-05-01T10:00:00+09:00", "mark": "予測",
                "subject": {"person": "s"}, "when": {"on": ON.isoformat()}, "value": {"amounts": amounts},
            }

        def income(amounts: list[dict[str, Any]]) -> Any:
            ir = make_ir([person("s", "2006-01-01")], [], judgments=[fc(amounts)])
            return h.income_of(ctx_of(ir), ON, "s", None)

        loan = income([{"income_type": "salary", "amount": 600_000}, {"income_type": "scholarship_loan", "amount": 480_000}])
        self.assertEqual(loan.forecast, 600_000)
        self.assertFalse([m for m in loan.o_forecast.missing if "奨学金" in m.id])
        grant = income([{"income_type": "salary", "amount": 600_000}, {"income_type": "scholarship_grant", "amount": 120_000}])
        self.assertEqual(grant.forecast, 720_000)
        self.assertTrue([m for m in grant.o_forecast.missing if "奨学金" in m.id])


class TestConstancy(unittest.TestCase):
    """判断.収入の恒常性（J-29。2026-11-12：README HF-14）：年間収入は恒常的な収入の状況で算定し、一時的な収入は含めない
    （gaps-sources §6.3、kyosai-law-and-criteria §6.2・§6.3）。直近の確定申告の運用の事業収入の実績から、一時的とした受取を除く。"""

    def setUp(self) -> None:
        def receipt(rid: str, amount: int) -> dict[str, Any]:
            return {"id": rid, "kind": "business_receipt", "roles": {"recipient": "s"}, "when": {"on": "2025-08-01"}, "amounts": {"amount": amount}, "attributes": {}}

        self.ir = make_ir(
            [person("a"), person("s", "2000-01-01")],
            [receipt("r1", 300_000), receipt("r2", 200_000)],
            insurance_memberships=[member("ma", "a"), member("ms", "s", insured="a")],
        )
        self.judgment = {
            "id": "j1", "kind": h.K_CONSTANCY, "judged_by": {"person": "a"}, "judged_at": "2026-05-01T09:00:00+09:00",
            "subject": {"person": "s", "record_ids": ["r2"]}, "value": "temporary",
        }
        # 直近の確定申告の運用（判定日 2026-06-01 → 令和7年分の受取）
        self.typ = {(injection_kind(h.P_TYPE), injection_key("insurer", "ins-x", ON)): Decided({"事業収入": "直近の確定申告"}, ("inj-t",), frozenset(), False)}

    def income(self, value: str | None) -> Any:
        decided = dict(self.typ)
        if value is not None:
            self.ir["judgments"] = [self.judgment]
            decided[(h.K_CONSTANCY, h.constancy_key("s", "r2"))] = Decided(value, ("j1",), frozenset(), False)
        return h.income_of(ctx_of(self.ir, decided), ON, "s", "ins-x")

    def test_temporary_receipt_is_excluded(self) -> None:
        got = self.income("temporary")
        self.assertEqual(got.forecast, 300_000)
        self.assertIn("j1", got.o_forecast.ids)
        self.assertEqual(self.income("recurring").forecast, 500_000)

    def test_without_judgment_counts_total(self) -> None:
        # 判断がなければ運用の定めどおり確定申告の総収入（1か所を宣言しない）
        self.assertEqual(self.income(None).forecast, 500_000)
        self.assertEqual(h._constancy_slots(ctx_of(self.ir)), [])

    def test_slot_only_for_judged_receipt(self) -> None:
        self.ir["judgments"] = [self.judgment]
        slots = h._constancy_slots(ctx_of(self.ir))
        self.assertEqual([s.key for s in slots], ["s:r2"])
        self.assertTrue(slots[0].lazy)
        self.assertEqual({c.value for c in slots[0].candidates or ()}, {"recurring", "temporary"})


if __name__ == "__main__":
    unittest.main()
