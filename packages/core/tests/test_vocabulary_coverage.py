"""中間表現の語彙の全種類が、どれかの規則モジュールに使われるか、「計算に使わない」と明記されているか（2026-11-12）。

語彙にあるのにどのモジュールも使わない種類は、入力にあると「未対応：どの規則モジュールもこの種類の判断・選択を使わない」で
捨てられる（okura_core.scope.input_scope）。対象外の一覧（test_out_of_scope_inventory.py）は README の行しか数えないので、
語彙の側から突き合わせる静的なテスト（evaluate を通さない：D24）。

- 記録（relations〜filed_documents）：モジュールの record_kinds に種類で書かれているか、種類より細かい宣言（registry.RecordKind）なら、
  その欄の列挙の値の全部が、どれかの宣言か「計算に使わない値」（vocabulary.NOT_USED_IN_CALCULATION_VALUES）に入っているか。
- 判断・選択：モジュールの decisions（DecisionSpec.kind）にあるか。
- 「計算に使わない」（vocabulary.NOT_USED_IN_CALCULATION・NOT_USED_IN_CALCULATION_VALUES）は packages/ir/README.md §6.4 の表と同じで、
  語彙に実在し、どのモジュールも使っていない（使い始めたら表から外す）。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from okura_ir import vocabulary as voc

from okura_core.registry import RecordKind
from okura_core.rules import MODULES

IR_README = Path(__file__).resolve().parents[3] / "packages" / "ir" / "README.md"


def _declared() -> tuple[set[str], dict[tuple[str, str], set[str]], set[str]]:
    """(種類で使う記録, (種類, 欄) → 使う値, 使う判断・選択)。"""
    whole: set[str] = set()
    partial: dict[tuple[str, str], set[str]] = {}
    decisions: set[str] = set()
    for m in MODULES:
        for k in m.record_kinds:
            if isinstance(k, RecordKind):
                partial.setdefault((k.kind, k.attribute), set()).update(k.values)
            else:
                whole.add(k)
        decisions.update(s.kind for s in m.decisions)
    return whole, partial, decisions


def _record_kinds() -> dict[str, voc.RecordKind]:
    return {k.kind: k for kinds in voc.RECORD_SECTIONS.values() for k in kinds}


def _ledger_kinds() -> set[str]:
    return {k.kind for kinds in voc.LEDGER_SECTIONS.values() for k in kinds}


def _enum_values(kind: voc.RecordKind, attribute: str) -> list[str]:
    field = kind.attributes.get(attribute)
    if field is None or "enum" not in field.schema:
        raise AssertionError(f"{kind.kind}.attributes.{attribute} は列挙でない（種類より細かい宣言は列挙の欄で絞る）")
    return list(field.schema["enum"])


def _readme_section() -> str:
    text = IR_README.read_text(encoding="utf-8")
    m = re.search(r"^### 6\.4 計算に使わない種類.*?$(.*?)(?=^##)", text, re.M | re.S)
    if m is None:
        raise AssertionError("packages/ir/README.md に §6.4 計算に使わない種類 がない")
    return m.group(1)


def _readme_entries() -> tuple[set[str], set[tuple[str, str, str]]]:
    kinds: set[str] = set()
    values: set[tuple[str, str, str]] = set()
    for line in _readme_section().splitlines():
        if not line.startswith("| `"):
            continue
        first = line.split("|")[1]
        codes = re.findall(r"`([^`]+)`", first)
        if len(codes) == 1:
            kinds.add(codes[0])
        elif len(codes) == 2 and ": " in codes[1]:
            attr, value = codes[1].split(": ", 1)
            values.add((codes[0], attr, value))
        else:
            raise AssertionError(f"README §6.4 の行の書き方が分からない：{line}")
    return kinds, values


class VocabularyCoverageTest(unittest.TestCase):
    def test_every_record_kind_is_used_or_declared_unused(self) -> None:
        whole, partial, _ = _declared()
        records = _record_kinds()
        missing = []
        for name, kind in records.items():
            if name in whole or name in voc.NOT_USED_IN_CALCULATION:
                continue
            attrs = {a for (k, a) in partial if k == name}
            if not attrs:
                missing.append(name)
                continue
            for attr in sorted(attrs):
                unused = {v for (k, a, v) in voc.NOT_USED_IN_CALCULATION_VALUES if k == name and a == attr}
                for value in _enum_values(kind, attr):
                    if value not in partial[(name, attr)] and value not in unused:
                        missing.append(f"{name}（{attr}: {value}）")
        self.assertEqual(missing, [], "どの規則モジュールも使わず、計算に使わないとも書いていない記録の種類・値")

    def test_every_judgment_and_choice_is_used_or_declared_unused(self) -> None:
        _, _, decisions = _declared()
        missing = sorted(k for k in _ledger_kinds() if k not in decisions and k not in voc.NOT_USED_IN_CALCULATION)
        self.assertEqual(missing, [], "どの規則モジュールも使わず、計算に使わないとも書いていない判断・選択の種類")

    def test_not_used_entries_exist_and_are_really_unused(self) -> None:
        whole, partial, decisions = _declared()
        records = _record_kinds()
        for name in voc.NOT_USED_IN_CALCULATION:
            with self.subTest(kind=name):
                self.assertTrue(name in records or name in _ledger_kinds(), "語彙にない種類")
                self.assertNotIn(name, whole | decisions | {k for (k, _a) in partial}, "使われているので表から外す")
        for name, attr, value in voc.NOT_USED_IN_CALCULATION_VALUES:
            with self.subTest(kind=name, attribute=attr, value=value):
                self.assertIn(name, records)
                self.assertIn(value, _enum_values(records[name], attr))
                self.assertNotIn(name, whole, "種類ごと使われているので表から外す")
                self.assertNotIn(value, partial.get((name, attr), set()), "使われているので表から外す")

    def test_constants_match_readme(self) -> None:
        kinds, values = _readme_entries()
        self.assertEqual(kinds, set(voc.NOT_USED_IN_CALCULATION))
        self.assertEqual(values, set(voc.NOT_USED_IN_CALCULATION_VALUES))

    def test_declared_kinds_exist_in_vocabulary(self) -> None:
        whole, partial, decisions = _declared()
        records = _record_kinds()
        self.assertEqual(sorted(whole - set(records)), [])
        self.assertEqual(sorted(decisions - _ledger_kinds()), [])
        for (name, attr), used in partial.items():
            with self.subTest(kind=name, attribute=attr):
                self.assertIn(name, records)
                self.assertEqual(sorted(used - set(_enum_values(records[name], attr))), [], "列挙にない値を宣言した")


class NotUsedInScopeTest(unittest.TestCase):
    """2026-11-12：scope.input_scope は「計算に使わない」種類・書類の種別を未対応にしない（packages/ir/README.md §6.4）。"""

    def test_not_used_records_are_not_reported_as_unimplemented(self) -> None:
        from okura_core.evaluate import REGISTRY
        from okura_core.scope import input_scope, not_used_in_calculation

        self.assertTrue(all(not_used_in_calculation({"kind": k}) for k in voc.NOT_USED_IN_CALCULATION))
        for kind, attr, value in voc.NOT_USED_IN_CALCULATION_VALUES:
            self.assertTrue(not_used_in_calculation({"kind": kind, "attributes": {attr: value}}))
            self.assertFalse(not_used_in_calculation({"kind": kind, "attributes": {attr: value + "_other"}}))
        ir = {
            "persons": [{"id": "p", "birth_on": "1950-01-01"}],
            "relations": [], "residences": [], "insurance_memberships": [], "assets": [], "filed_documents": [], "judgments": [], "choices": [],
            "facts": [
                {"id": "cl", "kind": "care_level", "roles": {"person": "p"}, "when": {"from_on": "2026-04-01"}, "attributes": {"level": "care_3"}},
                {"id": "x", "kind": "unknown_for_test", "roles": {"person": "p"}, "when": {"on": "2026-04-01"}},
            ],
        }  # fmt: skip
        got = [i.target["record_id"] for i in input_scope(ir, (), REGISTRY).items]
        self.assertEqual(got, ["x"])  # どのモジュールも使わない種類だけが未対応。計算に使わない care_level は出さない


if __name__ == "__main__":
    unittest.main()
