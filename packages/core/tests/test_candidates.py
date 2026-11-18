"""候補の評価（D21 R6・D22 S3・S20）：未入力の判断・選択と根拠のない端数を、候補の全部で評価してまとめる。

テストの道具の規則モジュール（tests/fixture_modules.py。法令の規則ではない）で、evaluate を通して確かめる。
テストのデータは架空の家庭だけ。
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any

from okura_core import candidates, evaluate
from okura_core.candidates import Candidate, Policy, Slot, TooManyCandidates
from okura_core.money import YenRange
from okura_core.registry import Decided, DecisionSlot, DecisionSpec, YearContext, YearWindow
from okura_core.situation import resolve_decisions
from okura_core.result import Flag, Means, State, TimeKey, YenAmount, check_result_json

from .fixture_modules import fixture_system
from .support import make_ir, make_query, person, salary

T26 = TimeKey("tax_year", 2026)


def _ok(res):
    if not res.ok:
        raise AssertionError(res.to_dict())
    problems = check_result_json(res.to_dict())
    if problems:
        raise AssertionError(problems)
    return res


def _seikei(jid: str, head: str, other: str, value: bool, *, mark: str | None = None, at: str = "2026-08-01T10:00:00+09:00") -> dict:
    j = {
        "id": jid,
        "kind": "判断.生計を一にする",
        "judged_by": {"person": head},
        "judged_at": at,
        "subject": {"person": head, "other_person": other},
        "when": {"from_on": "2026-01-01"},
        "value": value,
    }
    if mark is not None:
        j["mark"] = mark
    return j


class TestMergeTool(unittest.TestCase):
    """candidates.py の純粋関数。"""

    def _slot(self, sid: str, policy: Policy = Policy.JUDGMENT) -> Slot:
        return Slot(sid, Means.JUDGMENT, {}, (Candidate(True, "true"), Candidate(False, "false")), policy)

    def test_same_value_is_determined_and_evaluated_is_kept(self) -> None:
        s = self._slot("u1")
        m = candidates.merge([s], [({"u1": c}, 5) for c in s.candidates])
        self.assertEqual(m.value, 5)
        self.assertIsNone(m.undetermined)
        self.assertEqual([(x.id, x.splits_conclusion) for x in m.evaluated], [("u1", False)])

    def test_judgment_policy_amount_difference_is_undetermined(self) -> None:
        s = self._slot("u1")
        m = candidates.merge([s], [({"u1": s.candidates[0]}, 10), ({"u1": s.candidates[1]}, 0)])
        self.assertIsNone(m.value)
        assert m.undetermined is not None
        self.assertEqual([o.value for o in m.undetermined.outcomes], [10, 0])

    def test_only_the_slot_that_changes_the_value_splits(self) -> None:
        a, b = self._slot("a"), self._slot("b")
        runs = [({"a": x, "b": y}, x.value) for x in a.candidates for y in b.candidates]
        m = candidates.merge([a, b], runs)
        assert m.undetermined is not None
        self.assertEqual([s.id for s in m.undetermined.splits], ["a"])
        self.assertEqual(len(m.undetermined.outcomes), 2)
        self.assertEqual({(x.id, x.splits_conclusion) for x in m.evaluated}, {("a", True), ("b", False)})

    def test_rounding_policy_gives_range_for_amounts(self) -> None:
        s = Slot("r", Means.PRIMARY_SOURCE, {}, (Candidate("floor", "floor"), Candidate("ceil", "ceil")), Policy.ROUNDING)
        m = candidates.merge([s], [({"r": s.candidates[0]}, 3), ({"r": s.candidates[1]}, 4)])
        self.assertEqual(m.value, YenRange(3, 4))
        self.assertIsNone(m.undetermined)

    def test_judgment_and_rounding_together(self) -> None:
        """判断と根拠のない端数の両方が金額を変える：判断の分かれ目だけで未確定、候補ごとの値は端数の幅（2026-11-11 のレビュー）。"""
        u = self._slot("u")
        r = Slot("r", Means.PRIMARY_SOURCE, {}, (Candidate("floor", "floor"), Candidate("ceil", "ceil")), Policy.ROUNDING)
        table = {("true", "floor"): 10, ("true", "ceil"): 11, ("false", "floor"): 0, ("false", "ceil"): 0}
        runs = [({"u": x, "r": y}, table[(x.label, y.label)]) for x in u.candidates for y in r.candidates]
        m = candidates.merge([u, r], runs, amount=True)
        assert m.undetermined is not None
        self.assertEqual([s.id for s in m.undetermined.splits], ["u"])  # 端数は入力しても決まらないので分かれ目に出さない
        self.assertEqual({o.conditions["u"]: o.value for o in m.undetermined.outcomes}, {"true": YenRange(10, 11), "false": 0})
        self.assertEqual({(x.id, x.splits_conclusion) for x in m.evaluated}, {("u", True), ("r", True)})

    def test_reading_policy_gives_range_for_amounts_and_splits_judgments(self) -> None:
        """法令の読みの候補（Policy.READING。2026-11-12）：金額だけが違えば幅、判定が分かれたら未確定（D22 S1・S3）。"""
        s = Slot("読み:x", Means.PRIMARY_SOURCE, {}, (Candidate("a", "a"), Candidate("b", "b")), Policy.READING)
        m = candidates.merge([s], [({"読み:x": s.candidates[0]}, 1000), ({"読み:x": s.candidates[1]}, 1030)])
        self.assertEqual(m.value, YenRange(1000, 1030))
        self.assertIsNone(m.undetermined)
        m = candidates.merge([s], [({"読み:x": s.candidates[0]}, True), ({"読み:x": s.candidates[1]}, False)])
        self.assertIsNone(m.value)
        assert m.undetermined is not None
        self.assertEqual([x.id for x in m.undetermined.splits], ["読み:x"])

    def test_rounding_of_a_count_is_undetermined_not_a_range(self) -> None:
        """整数（人数など）は金額でない：端数の候補で違えば幅にせず未確定（判定が分かれた側。D22 S3）。"""
        r = Slot("r", Means.PRIMARY_SOURCE, {}, (Candidate("floor", "floor"), Candidate("ceil", "ceil")), Policy.ROUNDING)
        runs = [({"r": r.candidates[0]}, 1), ({"r": r.candidates[1]}, 2)]
        self.assertEqual(candidates.merge([r], runs).value, YenRange(1, 2))  # 型だけで決めると金額とみなす（既定）
        m = candidates.merge([r], runs, amount=False)
        self.assertIsNone(m.value)
        assert m.undetermined is not None
        self.assertEqual([o.value for o in m.undetermined.outcomes], [1, 2])

    def test_limit(self) -> None:
        slots = [self._slot(f"u{i}") for i in range(7)]  # 2^7 = 128 > 64
        with self.assertRaises(TooManyCandidates) as cm:
            candidates.assignments(slots)
        self.assertEqual((cm.exception.count, cm.exception.limit), (128, candidates.MAX_ASSIGNMENTS))
        self.assertEqual(len(candidates.assignments(slots[:6])), 64)
        self.assertEqual(candidates.assignments([]), [{}])



class TestLazyDecision(unittest.TestCase):
    """読んだときだけ開く判断・選択の1か所（DecisionSlot.lazy。2026-11-11、反証のレビューの指摘）。

    resolve_decisions は未入力の lazy な1か所を open に入れず lazy に分け、YearContext.decision は読んだ lazy な1か所の分かれ目の ID を
    窓口の decision_reads に記録する（evaluate はそれを見て分かれ目を開く。根拠のない端数の RoundingSlotSpec(variable=None) と同じ形）。
    """

    def _reg(self, *slots: Any) -> Any:
        spec = DecisionSpec("選択.扶養の所属", lambda ctx: list(slots), value_of=lambda rec: rec["value"]["filer"])
        return SimpleNamespace(modules=(SimpleNamespace(decisions=(spec,), injections=()),))

    def _slot(self, d: str, lazy: bool = True) -> DecisionSlot:
        return DecisionSlot(
            key=f"{d}:2026", target={"person": d}, matches=lambda rec, d=d: rec["subject"]["person"] == d,
            candidates=(Candidate("p-a", "p-a"), Candidate("p-b", "p-b")), persons=(d, "p-a", "p-b"), lazy=lazy,
        )

    def test_unread_lazy_slot_is_not_open_and_reading_records_it(self) -> None:
        ir = make_ir([person("p-a"), person("p-b"), person("p-c", "2010-01-01")], [])
        ctx = YearContext(ir, 2026, ("p-a", "p-b", "p-c"))
        dec = resolve_decisions(ctx, self._reg(self._slot("p-c"), self._slot("p-x", lazy=False)))
        self.assertEqual([s.id for s in dec.open], ["選択.扶養の所属:p-x:2026"])
        self.assertEqual([s.id for s in dec.lazy], ["選択.扶養の所属:p-c:2026"])
        self.assertEqual(dec.slot_keys["選択.扶養の所属:p-c:2026"], ("選択.扶養の所属", "p-c:2026"))
        # 窓口：読んだ lazy な1か所だけを記録する（読まない1か所・lazy でない1か所は記録しない）
        reads: set[str] = set()
        key = ("選択.扶養の所属", "p-c:2026")
        win = YearWindow(lazy_decisions={key: "選択.扶養の所属:p-c:2026"}, decision_reads=reads)
        decided = {key: Decided("p-a", (), frozenset(), open=True), ("選択.扶養の所属", "p-x:2026"): Decided("p-a", (), frozenset(), open=True)}
        c2 = YearContext(ir, 2026, ("p-a", "p-b", "p-c"), decided, window=win)
        c2.decision("選択.扶養の所属", "p-x:2026")
        self.assertEqual(reads, set())
        self.assertEqual(c2.decision(*key).value, "p-a")
        self.assertEqual(reads, {"選択.扶養の所属:p-c:2026"})

    def test_entered_choice_fixes_a_lazy_slot(self) -> None:
        choice = {
            "id": "c-1", "kind": "選択.扶養の所属", "chosen_by": "p-a", "chosen_at": "2026-12-01T10:00:00+09:00",
            "subject": {"person": "p-c"}, "when": {"tax_year": 2026},
            "value": {"filer": "p-b", "document_type": "final_return", "section": "dependent_relative"},
        }
        ir = make_ir([person("p-a"), person("p-b"), person("p-c", "2010-01-01")], [], choices=[choice])
        dec = resolve_decisions(YearContext(ir, 2026, ("p-a", "p-b", "p-c")), self._reg(self._slot("p-c")))
        self.assertEqual((dec.open, dec.lazy), ((), ()))
        self.assertEqual(dec.fixed[("選択.扶養の所属", "p-c:2026")].value, "p-b")

    def test_lazy_cannot_be_monotone(self) -> None:
        bad = DecisionSlot(key="k", target={}, matches=lambda rec: False, candidates=(Candidate(0, "a"), Candidate(1, "b")), monotone="g", lazy=True)
        with self.assertRaises(ValueError):
            resolve_decisions(YearContext(make_ir([person("p-a")], []), 2026, ("p-a",)), self._reg(bad))


if __name__ == "__main__":
    unittest.main()
