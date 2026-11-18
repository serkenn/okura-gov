"""同梱の ir.schema.json の性質のテスト（語彙の表との一致、部分集合、数の欄の型など）。"""

from __future__ import annotations

import unittest
from importlib import resources
from typing import Any, Iterator

from okura_ir import SCHEMA_VERSION, load_schema
from okura_ir import vocabulary as v
from okura_ir.build_schema import build_schema, render
from okura_ir.jsonschema_subset import check_schema
from okura_ir.validate import ALL_SECTION_NAMES


def walk(node: Any, pointer: str = "#") -> Iterator[tuple[str, dict[str, Any]]]:
    """スキーマの中のスキーマのノード（dict）を全部たどる。"""
    if not isinstance(node, dict):
        return
    yield pointer, node
    for name, sub in node.get("$defs", {}).items():
        yield from walk(sub, f"{pointer}/$defs/{name}")
    for name, sub in node.get("properties", {}).items():
        yield from walk(sub, f"{pointer}/properties/{name}")
    for key in ("items", "additionalProperties"):
        if isinstance(node.get(key), dict):
            yield from walk(node[key], f"{pointer}/{key}")
    for i, sub in enumerate(node.get("oneOf", [])):
        yield from walk(sub, f"{pointer}/oneOf/{i}")


class SchemaFileTest(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = load_schema()

    def test_file_is_generated_from_vocabulary(self) -> None:
        text = resources.files("okura_ir").joinpath("schema", "ir.schema.json").read_text(encoding="utf-8")
        self.assertEqual(text, render(build_schema()), "vocabulary.py を直したら build_schema --write で作り直す")
        self.assertEqual(self.schema, build_schema())

    def test_schema_uses_only_the_subset(self) -> None:
        self.assertEqual(check_schema(self.schema), [])

    def test_version(self) -> None:
        self.assertEqual(SCHEMA_VERSION, "0")
        self.assertEqual(self.schema["properties"]["schema_version"]["const"], SCHEMA_VERSION)
        self.assertEqual(self.schema["$schema"], "https://json-schema.org/draft/2020-12/schema")

    def test_no_number_type_and_integers_are_bounded(self) -> None:
        for pointer, node in walk(self.schema):
            types = node.get("type")
            names = types if isinstance(types, list) else [types]
            with self.subTest(pointer=pointer):
                self.assertNotIn("number", names, "数の欄は整数か整数の分数にする（float を入れない）")
                if "integer" in names:
                    self.assertIn("minimum", node)
                    self.assertIn("maximum", node)

    def test_patterns_are_anchored(self) -> None:
        for pointer, node in walk(self.schema):
            if "pattern" in node:
                with self.subTest(pointer=pointer):
                    self.assertTrue(node["pattern"].startswith("^") and node["pattern"].endswith("$"))

    def test_const_is_used_only_for_discriminators_and_version(self) -> None:
        for pointer, node in walk(self.schema):
            if "const" in node:
                with self.subTest(pointer=pointer):
                    self.assertTrue(
                        pointer.endswith("/properties/kind") or pointer == "#/properties/schema_version", pointer
                    )

    def test_root_sections(self) -> None:
        required = self.schema["required"]
        self.assertEqual(required[:2], ["schema_version", "persons"])
        self.assertEqual(tuple(required[2:]), ALL_SECTION_NAMES)
        self.assertFalse(self.schema["additionalProperties"])


class VocabularyTest(unittest.TestCase):
    def test_kinds_are_unique(self) -> None:
        record_kinds = [k.kind for kinds in v.RECORD_SECTIONS.values() for k in kinds]
        ledger_kinds = [k.kind for kinds in v.LEDGER_SECTIONS.values() for k in kinds]
        self.assertEqual(len(record_kinds), len(set(record_kinds)))
        self.assertEqual(len(ledger_kinds), len(set(ledger_kinds)))

    def test_record_kind_names_are_snake_case(self) -> None:
        import re

        for kinds in v.RECORD_SECTIONS.values():
            for k in kinds:
                with self.subTest(kind=k.kind):
                    self.assertRegex(k.kind, r"^[a-z][a-z0-9_]*$")
                    for name in list(k.roles) + list(k.amounts) + list(k.attributes):
                        self.assertTrue(re.fullmatch(r"[a-z][a-z0-9_]*", name), name)

    def test_amounts_are_integer_yen(self) -> None:
        for kinds in v.RECORD_SECTIONS.values():
            for k in kinds:
                for name, f in k.amounts.items():
                    with self.subTest(kind=k.kind, amount=name):
                        self.assertIn(f.schema, (v.YEN, v.SYEN))

    def test_ledger_prefixes_and_marks(self) -> None:
        expected_mark = {"判断": None, "見込み": v.MARK_FORECAST, "見積り": v.MARK_ESTIMATE, "計画": v.MARK_PLAN}
        for k in v.JUDGMENT_KINDS:
            prefix = k.kind.split(".", 1)[0]
            with self.subTest(kind=k.kind):
                self.assertIn(prefix, expected_mark)
                self.assertEqual(k.mark, expected_mark[prefix])
        for k in v.CHOICE_KINDS:
            with self.subTest(kind=k.kind):
                self.assertTrue(k.kind.startswith("選択."))
                self.assertIsNone(k.mark)

    def test_every_kind_has_a_vocabulary_id(self) -> None:
        import re

        all_kinds = [k for kinds in v.RECORD_SECTIONS.values() for k in kinds]
        all_kinds += [k for kinds in v.LEDGER_SECTIONS.values() for k in kinds]
        for k in all_kinds:
            with self.subTest(kind=k.kind):
                self.assertTrue(re.match(r"^(F-[A-Z]\d\d|J-\d\d|C-\d\d|P-\d\d|補)", k.vocab), k.vocab)
                self.assertTrue(k.title)


if __name__ == "__main__":
    unittest.main()
