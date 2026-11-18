"""personal_deductions の 判断.老人ホーム等（J-08）と 選択.円換算の方法（C-11）：cohab_fx.py の関数を直接呼ぶ（2026-11-12）。

テストのデータは架空の家庭。根拠：docs/public-sources/20261109_round2_elderly-abroad-guidance.md §1.1（老人ホーム等は同居でない、
治療のための入院は同居）・§3.4（所基通2−50 の円換算）。
"""

from __future__ import annotations

import datetime as _dt
import unittest
from typing import Any

from okura_core.registry import Decided, YearContext, YearWindow
from okura_core.rules.personal_deductions import MODULE
from okura_core.rules.personal_deductions.cohab_fx import (
    C_FX,
    FX_RULE,
    J_HOME,
    fx_provenance,
    home_key,
    home_override,
    home_slots,
)

from .support import make_ir, person, system

YEAR = 2026


def _stay(rid: str, pid: str, institution: str, start: str, end: str | None = None, for_treatment: bool | None = None) -> dict[str, Any]:
    attrs: dict[str, Any] = {"institution": institution}
    if for_treatment is not None:
        attrs["for_treatment"] = for_treatment
    when: dict[str, Any] = {"from_on": start}
    if end is not None:
        when["to_on"] = end
    return {"id": rid, "kind": "institution_stay", "roles": {"person": pid}, "when": when, "attributes": attrs}


def _home_judgment(jid: str, stay_id: str, value: bool) -> dict[str, Any]:
    return {"id": jid, "kind": J_HOME, "judged_by": {"person": "c"}, "judged_at": "2026-12-01T09:00:00+09:00",
            "subject": {"stay_id": stay_id}, "value": value}  # fmt: skip


def _ctx(facts: list[dict[str, Any]], judgments: list[dict[str, Any]] = ()) -> YearContext:
    persons = [person("c", "1975-01-01"), person("g", "1950-05-01"), person("y", "1960-05-01")]  # g は71歳、y は66歳（2026年12月31日）
    ir = make_ir(persons, facts, judgments=list(judgments))
    return YearContext(ir, YEAR, ("c", "g", "y"), {}, window=YearWindow(parameters_at=lambda s: system().parameters(s)))


def _decided(value: bool, ids: tuple[str, ...] = ()) -> Decided:
    return Decided(value, ids, frozenset(), not ids)


class TestRegistration(unittest.TestCase):
    def test_kinds_are_declared(self) -> None:
        kinds = {d.kind for d in MODULE.decisions}
        self.assertIn(J_HOME, kinds)
        self.assertIn(C_FX, kinds)
        self.assertIn("institution_stay", MODULE.record_kinds)


class TestHomeSlots(unittest.TestCase):
    def test_care_facility_of_elderly_person_gets_lazy_slot(self) -> None:
        slots = list(home_slots(_ctx([_stay("s1", "g", "care_facility", "2026-04-01")])))
        self.assertEqual([s.key for s in slots], [home_key("s1")])
        self.assertTrue(slots[0].lazy)
        self.assertEqual([c.value for c in slots[0].candidates], [True, False])

    def test_treatment_stay_and_under_age_get_no_slot(self) -> None:
        facts = [
            _stay("s1", "g", "hospital", "2026-04-01"),  # 治療のための入院（for_treatment の記載なし）は入院の側
            _stay("s2", "y", "care_facility", "2026-04-01"),  # 66歳：老人扶養親族の年齢の下限（70歳）未満
            _stay("s3", "g", "care_facility", "2024-01-01", "2025-12-31"),  # その年分と重ならない
        ]
        self.assertEqual(list(home_slots(_ctx(facts))), [])

    def test_hospital_not_for_treatment_or_judged_gets_slot(self) -> None:
        facts = [_stay("s1", "g", "hospital", "2026-04-01", for_treatment=False), _stay("s2", "g", "hospital", "2026-05-01")]
        keys = [s.key for s in home_slots(_ctx(facts, [_home_judgment("j1", "s2", True)]))]
        self.assertEqual(keys, [home_key("s1"), home_key("s2")])


class TestHomeOverride(unittest.TestCase):
    T = _dt.date(YEAR, 12, 31)

    def test_home_at_judgment_time_breaks_cohabitation(self) -> None:
        stays = [_stay("s1", "g", "care_facility", "2026-04-01")]
        found, ids, _ = home_override(stays, self.T, lambda k: _decided(True, ("j1",)))
        self.assertTrue(found)
        self.assertEqual(ids, ("j1", "s1"))

    def test_not_a_home_keeps_cohabitation_but_records_the_read(self) -> None:
        stays = [_stay("s1", "g", "care_facility", "2026-04-01")]
        found, ids, _ = home_override(stays, self.T, lambda k: _decided(False, ("j1",)))
        self.assertFalse(found)
        self.assertEqual(ids, ("j1", "s1"))

    def test_stay_ended_before_judgment_time_is_not_read(self) -> None:
        stays = [_stay("s1", "g", "care_facility", "2026-04-01", "2026-12-30")]

        def read(key: str) -> Decided:
            raise AssertionError("判定の時を含まない入所の判断を読んだ")

        self.assertEqual(home_override(stays, self.T, read), (False, (), frozenset()))

    def test_undeclared_slot_is_skipped(self) -> None:
        def read(key: str) -> Decided:
            raise KeyError(key)

        found, ids, _ = home_override([_stay("s1", "g", "hospital", "2026-04-01")], self.T, read)
        self.assertEqual((found, ids), (False, ()))


class TestFxProvenance(unittest.TestCase):
    def _remit(self, foreign: bool) -> dict[str, Any]:
        attrs: dict[str, Any] = {"method": "bank_transfer"}
        if foreign:
            attrs["foreign_amount"] = {"currency": "USD", "value": {"num": 2600, "den": 1}}
        return {"id": "r1", "kind": "remittance", "roles": {"sender": "c", "recipient": "g"}, "when": {"on": "2026-03-01"},
                "amounts": {"amount": 390_000}, "attributes": attrs}  # fmt: skip

    def _choice(self, cid: str, pid: str, year: int) -> dict[str, Any]:
        return {"id": cid, "kind": C_FX, "chosen_by": pid, "chosen_at": "2026-12-01T09:00:00+09:00",
                "subject": {"person": pid}, "when": {"tax_year": year}, "value": {"method": "ttm"}}  # fmt: skip

    def test_foreign_remittance_carries_the_choice_and_rule(self) -> None:
        choices = [self._choice("x1", "c", YEAR), self._choice("x2", "c", YEAR - 1), self._choice("x3", "g", YEAR)]
        self.assertEqual(fx_provenance([self._remit(True)], choices, "c", YEAR), (("x1",), (FX_RULE,)))

    def test_yen_remittance_does_not_use_the_choice(self) -> None:
        self.assertEqual(fx_provenance([self._remit(False)], [self._choice("x1", "c", YEAR)], "c", YEAR), ((), ()))


if __name__ == "__main__":
    unittest.main()
