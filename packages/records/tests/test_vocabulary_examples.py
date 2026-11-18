"""語彙の全種類を記録層から作れること：例（examples/ の下の全部）の build_ir の結果が okura_ir の検査に通る、
語彙のすべての種類が書く場所（ledger_map）どおりに例にある、README §4.3 の表が語彙の表と一致する。
build_ir・台帳の読み込みを直接呼ぶ（CLI は通さない。D24）。"""

from __future__ import annotations

import os
import unittest

from okura_ir import validate
from okura_ir import vocabulary as irv

from okura_records import facts_ledger, judgments_ledger
from okura_records.build_ir import build_ir
from okura_records.jsonl_ledger import append_entry
from okura_records.ledger_map import (
    FACTS_LEDGER,
    JUDGMENTS_LEDGER,
    PLACEMENTS,
    SECTION_OF_KIND,
    TRANSACTION,
    replace_guide,
)
from okura_records.meta_vocabulary import TRANSACTION_FACT_KINDS

from .helpers import ROOT_OF_PACKAGE

EXAMPLES = os.path.join(ROOT_OF_PACKAGE, "examples")
VOCABULARY = os.path.join(EXAMPLES, "vocabulary")


def _read(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def load_example(directory: str):
    """(取引 JSON, 事実台帳の状態, 判断台帳の状態)。どこかに問題があれば AssertionError。"""
    from okura_records.adapter import normalize
    from okura_records.safe_loader import load_ledger

    loaded = load_ledger(os.path.join(directory, "main.beancount"))
    assert loaded.ok, [p.to_dict() for p in loaded.problems]
    doc, problems = normalize(loaded.ledger)
    assert not problems, [p.to_dict() for p in problems]
    facts, problems = facts_ledger.read(_read(os.path.join(directory, "facts.jsonl")), "facts.jsonl")
    assert not problems, [p.to_dict() for p in problems]
    judgments, problems = judgments_ledger.read(_read(os.path.join(directory, "judgments.jsonl")), "judgments.jsonl")
    assert not problems, [p.to_dict() for p in problems]
    return doc, facts, judgments


def example_dirs() -> list[str]:
    return sorted(
        os.path.join(EXAMPLES, name)
        for name in os.listdir(EXAMPLES)
        if os.path.isfile(os.path.join(EXAMPLES, name, "main.beancount"))
    )


VOCAB_DOC, VOCAB_FACTS, VOCAB_JUDGMENTS = load_example(VOCABULARY)


def codes(problems) -> set[str]:
    return {p.code for p in problems}


class ExampleTests(unittest.TestCase):
    def test_every_example_builds_ir_that_passes_okura_ir(self):
        dirs = example_dirs()
        self.assertIn(VOCABULARY, dirs)
        self.assertGreaterEqual(len(dirs), 2)
        for directory in dirs:
            with self.subTest(example=os.path.basename(directory)):
                result = build_ir(*load_example(directory))
                self.assertTrue(result.ok, [p.to_dict() for p in result.problems])
                self.assertEqual(validate(result.ir), [])

    def test_every_kind_has_an_example_in_its_place(self):
        ir = build_ir(VOCAB_DOC, VOCAB_FACTS, VOCAB_JUDGMENTS).ir
        tx_ids = {t["id"] for t in VOCAB_DOC["transactions"]}
        from_transactions = {f["kind"] for f in ir["facts"] if f["id"] in tx_ids}
        from_facts_ledger = {r.record.get("kind") for r in VOCAB_FACTS.records}
        from_judgments_ledger = {r.record.get("kind") for r in VOCAB_JUDGMENTS.records}
        written = {TRANSACTION: from_transactions, FACTS_LEDGER: from_facts_ledger, JUDGMENTS_LEDGER: from_judgments_ledger}
        for p in PLACEMENTS:
            with self.subTest(kind=p.kind):
                self.assertIn(p.kind, written[p.primary], f"{p.kind} の例が {p.primary} に無い")
        # 取引の種類を事実台帳に書く例（記帳していない入出金）
        self.assertTrue(from_facts_ledger & set(TRANSACTION_FACT_KINDS))
        self.assertTrue(VOCAB_FACTS.in_section("persons"))
        # 例は書く場所以外に書いていない（事実台帳の取引の種類を除く）
        places = {p.kind: (p.primary, *p.also) for p in PLACEMENTS}
        for kind in from_facts_ledger - {None}:
            self.assertIn(FACTS_LEDGER, places[kind], kind)

    def test_example_shows_correction_deletion_and_revision(self):
        ops = {e["op"] for e in _jsonl(os.path.join(VOCABULARY, "facts.jsonl"))} | {
            e["op"] for e in _jsonl(os.path.join(VOCABULARY, "judgments.jsonl"))
        }
        self.assertEqual(ops, {"add", "correct", "delete"})
        self.assertTrue(any("replaces" in r.record for r in VOCAB_JUDGMENTS.records))


def _jsonl(path: str) -> list[dict]:
    import json

    return [json.loads(line) for line in _read(path).decode("utf-8").splitlines()]


class PlacementTests(unittest.TestCase):
    def test_every_vocabulary_kind_has_exactly_one_place(self):
        kinds = [k.kind for ks in irv.RECORD_SECTIONS.values() for k in ks] + [k.kind for ks in irv.LEDGER_SECTIONS.values() for k in ks]
        self.assertEqual(sorted(kinds), sorted(p.kind for p in PLACEMENTS))
        self.assertEqual(len(SECTION_OF_KIND), len(kinds))

    def test_places_follow_the_rule(self):
        for p in PLACEMENTS:
            with self.subTest(kind=p.kind):
                if p.kind in TRANSACTION_FACT_KINDS:
                    self.assertEqual((p.section, p.primary, p.also), ("facts", TRANSACTION, (FACTS_LEDGER,)))
                elif p.section in irv.LEDGER_SECTIONS:
                    self.assertEqual((p.primary, p.also), (JUDGMENTS_LEDGER, ()))
                else:
                    self.assertEqual((p.primary, p.also), (FACTS_LEDGER, ()))
        self.assertEqual(sum(1 for p in PLACEMENTS if p.primary == TRANSACTION), 20)

    def test_readme_table_matches_vocabulary(self):
        readme = _read(os.path.join(ROOT_OF_PACKAGE, "README.md")).decode("utf-8")
        self.assertEqual(replace_guide(readme), readme, "README §4.3 の表が古い（python -I -X utf8 -m okura_records.ledger_map --write …）")


def _entry(n: int, section: str, record: dict, *, ledger: str = "okura-facts/0") -> dict:
    return {"ledger": ledger, "entry_id": f"x-{n:04d}", "recorded_at": "2027-12-01T00:00:00+09:00", "recorded_by": {"person": "p-a"},
            "op": "add", "section": section, "record": record}


class SectionMismatchTests(unittest.TestCase):
    MARRIAGE = {"id": "m-1", "kind": "marriage", "roles": {"spouse_a": "p-a", "spouse_b": "p-g"}, "when": {"from_on": "2027-01-01"}}

    def build(self, facts_entries=(), judgment_entries=()):
        facts_data = _read(os.path.join(VOCABULARY, "facts.jsonl"))
        for e in facts_entries:
            facts_data = append_entry(facts_data, e)
        judgments_data = _read(os.path.join(VOCABULARY, "judgments.jsonl"))
        for e in judgment_entries:
            judgments_data = append_entry(judgments_data, e)
        facts, p1 = facts_ledger.read(facts_data, "facts.jsonl")
        judgments, p2 = judgments_ledger.read(judgments_data, "judgments.jsonl")
        self.assertEqual(p1 + p2, [])
        return build_ir(VOCAB_DOC, facts, judgments)

    def test_kind_in_wrong_section_is_rejected_with_its_place(self):
        result = self.build([_entry(1, "facts", self.MARRIAGE)])
        self.assertEqual(codes(result.problems), {"record_section_mismatch"})
        self.assertIn("relations", result.problems[0].message)
        choice = {"id": "c-1", "kind": "選択.還付申告", "chosen_by": "p-a", "chosen_at": "2027-01-01T00:00:00+09:00",
                  "subject": {"person": "p-a"}, "when": {"tax_year": 2026}, "value": True}
        result = self.build(judgment_entries=[_entry(1, "judgments", choice, ledger="okura-judgments/0")])
        self.assertEqual(codes(result.problems), {"record_section_mismatch"})

    def test_wrong_section_deleted_later_is_not_a_problem(self):
        # 現在の状態だけを見る（examples/household の fe-0013 → fe-0015 と同じ：違う section に書いて取り消した）
        delete = dict(_entry(2, "facts", self.MARRIAGE), op="delete", replaces="x-0001", reason="section を間違えた")
        del delete["record"]
        result = self.build([_entry(1, "facts", self.MARRIAGE), delete, _entry(3, "relations", self.MARRIAGE)])
        self.assertTrue(result.ok, [p.to_dict() for p in result.problems])

    def test_unknown_kind_is_left_to_okura_ir(self):
        unknown = {"id": "u-1", "kind": "no_such_kind", "roles": {}, "when": {"on": "2026-01-01"}}
        self.assertEqual(codes(self.build([_entry(1, "facts", unknown)]).problems), {"unknown_kind"})


class WrittenTwiceTests(unittest.TestCase):
    def build_with(self, record: dict):
        data = _read(os.path.join(VOCABULARY, "facts.jsonl"))
        facts, problems = facts_ledger.read(append_entry(data, _entry(1, "facts", record)), "facts.jsonl")
        self.assertEqual(problems, [])
        return build_ir(VOCAB_DOC, facts, VOCAB_JUDGMENTS)

    def test_same_transaction_in_both_places_is_rejected(self):
        record = {"id": "mp-dup", "kind": "medical_payment", "roles": {"payer": "p-a", "patient": "p-g"}, "when": {"on": "2026-02-10"},
                  "amounts": {"amount": 120000}, "attributes": {"incurred_on": "2026-01-28", "medical_kinds": ["hospitalization"]},
                  "source": {"transaction_ids": ["tx-2026-0210-hospital"]}}
        result = self.build_with(record)
        self.assertIsNone(result.ir)
        self.assertEqual(codes(result.problems), {"fact_written_twice"})
        self.assertIn("(x-0001)", result.problems[0].origin)

    def test_unbooked_transaction_kind_in_facts_ledger_is_accepted(self):
        record = {"id": "mp-unbooked", "kind": "medical_payment", "roles": {"payer": "p-g", "patient": "p-g"}, "when": {"on": "2026-06-10"},
                  "amounts": {"amount": 3000}, "attributes": {"incurred_on": "2026-06-10", "medical_kinds": ["medical_treatment"]}}
        result = self.build_with(record)
        self.assertTrue(result.ok, [p.to_dict() for p in result.problems])
        # 別の種類の記録が取引を根拠に挙げるのは二重ではない（例：取引の領収書を根拠にした判断・書類）
        other = {"id": "hc-x", "kind": "health_checkup_record", "roles": {"person": "p-a"}, "when": {"on": "2026-02-10"},
                 "attributes": {"activity": "other"}, "source": {"transaction_ids": ["tx-2026-0210-hospital"]}}
        self.assertTrue(self.build_with(other).ok)


class AppendDraftsTests(unittest.TestCase):
    DRAFT = {"entry_id": "fe-9001", "recorded_at": "2027-12-01T00:00:00+09:00", "recorded_by": {"person": "p-a"}, "op": "add",
             "section": "facts", "record": {"id": "cl-x", "kind": "care_level", "roles": {"person": "p-x"},
                                            "when": {"from_on": "2027-04-01"}, "attributes": {"level": "support_1"}}}

    def test_drafts_are_sealed_and_appended(self):
        existing = _read(os.path.join(VOCABULARY, "facts.jsonl"))
        second = dict(self.DRAFT, entry_id="fe-9002", op="delete", replaces="fe-9001", reason="書き間違い")
        del second["record"]
        added, problems = facts_ledger.append_drafts(existing, [self.DRAFT, second], "facts.jsonl")
        self.assertEqual(problems, [])
        self.assertEqual(added.count(b"\n"), 2)
        state, problems = facts_ledger.read(existing + added, "facts.jsonl")
        self.assertEqual(problems, [])
        self.assertNotIn("cl-x", {r.record.get("id") for r in state.records})
        # 1件のオブジェクトも受け付け、ledger を補う
        added, problems = facts_ledger.append_drafts(existing, self.DRAFT, "facts.jsonl")
        self.assertEqual(problems, [])
        self.assertIn(b'"ledger":"okura-facts/0"', added)
        self.assertIn("cl-x", {r.record.get("id") for r in facts_ledger.read(existing + added, "f")[0].records})

    def test_bad_drafts_and_broken_ledgers_are_not_appended(self):
        existing = _read(os.path.join(VOCABULARY, "facts.jsonl"))
        cases = [
            (dict(self.DRAFT, prev_sha256=None), "draft_shape"),
            ([], "draft_shape"),
            (["x"], "draft_shape"),
            (dict(self.DRAFT, section="judgments"), "entry_field"),  # 事実台帳に無い section
            (dict(self.DRAFT, entry_id="fe-0001"), "entry_id_duplicate"),
            (dict(self.DRAFT, ledger="okura-judgments/0"), "entry_ledger_mismatch"),
        ]
        for draft, code in cases:
            with self.subTest(code=code):
                added, problems = facts_ledger.append_drafts(existing, draft, "facts.jsonl")
                self.assertIsNone(added)
                self.assertIn(code, codes(problems))
        tampered = existing.replace(b'"birth_on":"1975-04-10"', b'"birth_on":"1975-04-11"', 1)
        added, problems = facts_ledger.append_drafts(tampered, self.DRAFT, "facts.jsonl")
        self.assertIsNone(added)
        self.assertIn("chain_broken", codes(problems))


if __name__ == "__main__":
    unittest.main()
