"""JSON Schema の部分集合の各キーワードの解釈のテスト（jsonschema_subset）。"""

from __future__ import annotations

import math
import unittest

from okura_ir.jsonschema_subset import (
    SUPPORTED_KEYWORDS,
    SchemaError,
    check_schema,
    evaluate,
    json_equal,
    translate_pattern,
)


def codes(instance, schema, root=None):
    return [(p.code, p.path) for p in evaluate(instance, schema, root=root).problems]


class TypeKeywordTest(unittest.TestCase):
    def test_each_type_accepts_its_values(self) -> None:
        cases = {
            "object": [{}],
            "array": [[]],
            "string": ["", "あ"],
            "integer": [0, -5, 10**20],
            "number": [0, 1.5, -2],
            "boolean": [True, False],
            "null": [None],
        }
        for type_name, values in cases.items():
            for value in values:
                with self.subTest(type_name=type_name, value=value):
                    self.assertEqual(codes(value, {"type": type_name}), [])

    def test_integer_rejects_bool_float_and_string(self) -> None:
        for value in (True, False, 1.0, 1.5, "1", "100*3", None, [1], {"n": 1}):
            with self.subTest(value=value):
                self.assertEqual(codes(value, {"type": "integer"}), [("type", "$")])

    def test_number_rejects_bool_nan_and_infinity(self) -> None:
        for value in (True, math.nan, math.inf, -math.inf, "1"):
            with self.subTest(value=value):
                self.assertEqual(codes(value, {"type": "number"}), [("type", "$")])

    def test_type_list(self) -> None:
        schema = {"type": ["string", "null"]}
        self.assertEqual(codes(None, schema), [])
        self.assertEqual(codes("a", schema), [])
        self.assertEqual(codes(1, schema), [("type", "$")])

    def test_values_outside_json_are_rejected(self) -> None:
        for value in ((1, 2), {1, 2}, b"x", object()):
            with self.subTest(value=value):
                self.assertEqual(codes(value, {"type": "array"}), [("type", "$")])

    def test_type_failure_suppresses_other_keywords(self) -> None:
        schema = {"type": "integer", "minimum": 0, "enum": [1, 2]}
        self.assertEqual(codes("x", schema), [("type", "$")])

    def test_string_with_surrogate_is_rejected(self) -> None:
        self.assertEqual(codes("a\ud800b", {"type": "string"}), [("invalid_string", "$")])


class ObjectKeywordTest(unittest.TestCase):
    def test_required_reports_missing_child_path(self) -> None:
        schema = {"type": "object", "required": ["a", "b"]}
        self.assertEqual(codes({"a": 1}, schema), [("required", "$.b")])

    def test_properties_are_evaluated_with_paths(self) -> None:
        schema = {"type": "object", "properties": {"a": {"type": "integer"}, "日本語": {"type": "string"}}}
        self.assertEqual(codes({"a": "x", "日本語": 1}, schema), [("type", "$.a"), ("type", '$["日本語"]')])

    def test_additional_properties_false(self) -> None:
        schema = {"type": "object", "additionalProperties": False, "properties": {"a": {}}}
        self.assertEqual(codes({"a": 1, "b": 2}, schema), [("additional_property", "$.b")])

    def test_additional_properties_schema(self) -> None:
        schema = {"type": "object", "additionalProperties": {"type": "integer"}, "properties": {"a": {}}}
        self.assertEqual(codes({"a": "x", "b": 2, "c": "y"}, schema), [("type", "$.c")])

    def test_additional_properties_absent_allows_anything(self) -> None:
        self.assertEqual(codes({"z": object()}, {"type": "object"}), [])

    def test_non_string_keys_are_rejected(self) -> None:
        self.assertEqual(codes({1: "a"}, {"type": "object"}), [("invalid_key", "$")])


class EnumConstTest(unittest.TestCase):
    def test_json_equality_distinguishes_bool_and_number(self) -> None:
        self.assertFalse(json_equal(True, 1))
        self.assertFalse(json_equal(0, False))
        self.assertTrue(json_equal(1, 1.0))
        self.assertTrue(json_equal({"a": [1, "x"]}, {"a": [1.0, "x"]}))
        self.assertFalse(json_equal([1, 2], [2, 1]))

    def test_enum(self) -> None:
        schema = {"enum": [1, "a", None]}
        self.assertEqual(codes(1, schema), [])
        self.assertEqual(codes(None, schema), [])
        self.assertEqual(codes(True, schema), [("enum", "$")])
        self.assertEqual(codes("b", schema), [("enum", "$")])

    def test_empty_enum_forbids(self) -> None:
        self.assertEqual(codes("x", {"enum": []}), [("forbidden", "$")])

    def test_const(self) -> None:
        self.assertEqual(codes("0", {"const": "0"}), [])
        self.assertEqual(codes(0, {"const": "0"}), [("const", "$")])
        self.assertEqual(codes(True, {"const": 1}), [("const", "$")])
        self.assertEqual(codes({"a": [1]}, {"const": {"a": [1]}}), [])


class ArrayKeywordTest(unittest.TestCase):
    def test_items_paths(self) -> None:
        schema = {"type": "array", "items": {"type": "integer"}}
        self.assertEqual(codes([1, "x", 3, None], schema), [("type", "$[1]"), ("type", "$[3]")])

    def test_min_items(self) -> None:
        schema = {"type": "array", "minItems": 2}
        self.assertEqual(codes([1], schema), [("min_items", "$")])
        self.assertEqual(codes([1, 2], schema), [])


class NumberKeywordTest(unittest.TestCase):
    def test_minimum_maximum_are_inclusive(self) -> None:
        schema = {"type": "integer", "minimum": 0, "maximum": 10}
        self.assertEqual(codes(0, schema), [])
        self.assertEqual(codes(10, schema), [])
        self.assertEqual(codes(-1, schema), [("minimum", "$")])
        self.assertEqual(codes(11, schema), [("maximum", "$")])

    def test_minimum_ignores_non_numbers(self) -> None:
        self.assertEqual(codes(True, {"minimum": 5}), [])
        self.assertEqual(codes("1", {"minimum": 5}), [])


class PatternKeywordTest(unittest.TestCase):
    def test_pattern_is_a_search_not_a_full_match(self) -> None:
        self.assertEqual(codes("abc", {"type": "string", "pattern": "b"}), [])

    def test_dollar_does_not_match_before_trailing_newline(self) -> None:
        schema = {"type": "string", "pattern": "^a$"}
        self.assertEqual(codes("a", schema), [])
        self.assertEqual(codes("a\n", schema), [("pattern", "$")])

    def test_dollar_in_class_and_escaped_dollar_are_literal(self) -> None:
        self.assertEqual(translate_pattern("^[$]x$"), r"^[$]x\Z")
        self.assertEqual(translate_pattern(r"^\$x$"), r"^\$x\Z")
        self.assertEqual(translate_pattern(r"^[\]$]$"), r"^[\]$]\Z")
        self.assertEqual(codes("$", {"type": "string", "pattern": "^[$]$"}), [])

    def test_digit_class_is_ascii_only(self) -> None:
        schema = {"type": "string", "pattern": "^\\d+$"}
        self.assertEqual(codes("123", schema), [])
        self.assertEqual(codes("١٢٣", schema), [("pattern", "$")])

    def test_unicode_escapes_in_class(self) -> None:
        schema = {"type": "string", "pattern": "^[^\\u0000-\\u001f]{1,3}$"}
        self.assertEqual(codes("あいう", schema), [])
        self.assertEqual(codes("a\tb", schema), [("pattern", "$")])
        self.assertEqual(codes("abcd", schema), [("pattern", "$")])


class FormatKeywordTest(unittest.TestCase):
    def test_date(self) -> None:
        schema = {"type": "string", "format": "date"}
        self.assertEqual(codes("2024-02-29", schema), [])
        for bad in ("2026-02-30", "20260210", "2026-1-01", "2026-01-01T00:00", "２０２６-01-01", "2026-13-01"):
            with self.subTest(bad=bad):
                self.assertEqual(codes(bad, schema), [("format", "$")])

    def test_format_applies_to_strings_only(self) -> None:
        self.assertEqual(codes(5, {"format": "date"}), [])


class RefKeywordTest(unittest.TestCase):
    ROOT = {
        "$defs": {
            "yen": {"type": "integer", "minimum": 0},
            "alias": {"$ref": "#/$defs/yen"},
        },
        "type": "object",
        "properties": {"a": {"$ref": "#/$defs/alias"}},
    }

    def test_ref_resolves_and_records_annotations(self) -> None:
        outcome = evaluate({"a": 5}, self.ROOT)
        self.assertEqual(outcome.problems, [])
        names = sorted((a.name, a.path, a.value) for a in outcome.annotations)
        self.assertEqual(names, [("alias", "$.a", 5), ("yen", "$.a", 5)])

    def test_failed_ref_records_no_annotation(self) -> None:
        outcome = evaluate({"a": -1}, self.ROOT)
        self.assertEqual([(p.code, p.path) for p in outcome.problems], [("minimum", "$.a")])
        self.assertEqual(outcome.annotations, [])

    def test_unknown_ref_raises_schema_error(self) -> None:
        with self.assertRaises(SchemaError):
            evaluate(1, {"$ref": "#/$defs/missing"})

    def test_ref_outside_defs_is_not_supported(self) -> None:
        with self.assertRaises(SchemaError):
            evaluate(1, {"$ref": "#/properties/a"})


class OneOfKeywordTest(unittest.TestCase):
    def test_exactly_one_branch(self) -> None:
        schema = {"oneOf": [{"type": "integer"}, {"type": "string"}]}
        self.assertEqual(codes(1, schema), [])
        self.assertEqual(codes(None, schema), [("one_of_none", "$")])

    def test_multiple_branches(self) -> None:
        schema = {"oneOf": [{"type": "integer"}, {"minimum": 0}]}
        self.assertEqual(codes(1, schema), [("one_of_multiple", "$")])

    def test_annotations_only_from_the_chosen_branch(self) -> None:
        root = {
            "$defs": {"a": {"type": "integer"}, "b": {"type": "string"}},
            "oneOf": [{"$ref": "#/$defs/a"}, {"$ref": "#/$defs/b"}],
        }
        outcome = evaluate("x", root)
        self.assertEqual(outcome.problems, [])
        self.assertEqual([a.name for a in outcome.annotations], ["b"])

    DISCRIMINATED = {
        "type": "object",
        "required": ["kind"],
        "properties": {"kind": {"type": "string"}, "v": {}},
        "oneOf": [
            {"properties": {"kind": {"const": "x"}, "v": {"type": "integer"}}},
            {"properties": {"kind": {"const": "y"}, "v": {"type": "string"}}},
        ],
    }

    def test_discriminated_one_of_reports_the_matching_branch(self) -> None:
        self.assertEqual(codes({"kind": "x", "v": 1}, self.DISCRIMINATED), [])
        self.assertEqual(codes({"kind": "x", "v": "s"}, self.DISCRIMINATED), [("type", "$.v")])
        self.assertEqual(codes({"kind": "y", "v": 1}, self.DISCRIMINATED), [("type", "$.v")])

    def test_discriminated_one_of_unknown_kind(self) -> None:
        self.assertEqual(codes({"kind": "z"}, self.DISCRIMINATED), [("unknown_kind", "$.kind")])

    def test_discriminated_one_of_missing_kind_is_reported_once(self) -> None:
        self.assertEqual(codes({"v": 1}, self.DISCRIMINATED), [("required", "$.kind")])
        self.assertEqual(codes({"kind": 3}, self.DISCRIMINATED), [("type", "$.kind")])


class BooleanSchemaTest(unittest.TestCase):
    def test_false_forbids_and_empty_object_allows(self) -> None:
        schema = {"type": "object", "properties": {"a": False, "b": {}}}
        self.assertEqual(codes({"b": [object()]}, schema), [])
        self.assertEqual(codes({"a": 1}, schema), [("forbidden", "$.a")])


class CheckSchemaTest(unittest.TestCase):
    def test_supported_keywords_are_exactly_the_documented_subset(self) -> None:
        self.assertEqual(
            SUPPORTED_KEYWORDS,
            {
                "type", "required", "properties", "additionalProperties", "enum", "const", "items",
                "minItems", "minimum", "maximum", "pattern", "format", "$defs", "$ref", "oneOf",
            },
        )

    def test_unsupported_keywords_are_reported(self) -> None:
        for keyword, value in (
            ("maxLength", 3), ("allOf", [{}]), ("if", {}), ("not", {}), ("uniqueItems", True),
            ("patternProperties", {}), ("prefixItems", [{}]), ("unevaluatedProperties", False),
        ):
            with self.subTest(keyword=keyword):
                problems = check_schema({keyword: value})
                self.assertIn("schema_error", [p.code for p in problems])
                with self.assertRaises(SchemaError):
                    evaluate(None, {keyword: value})

    def test_annotation_keywords_are_allowed(self) -> None:
        schema = {"$schema": "x", "$id": "y", "$comment": "c", "title": "t", "description": "d", "type": "null"}
        self.assertEqual(check_schema(schema), [])
        self.assertEqual(codes(None, schema), [])

    def test_bad_schemas(self) -> None:
        bad = [
            {"format": "date-time"},
            {"pattern": "("},
            {"type": "decimal"},
            {"required": ["a", "a"]},
            {"minItems": -1},
            {"$ref": "#/$defs/none"},
            {"properties": {"a": {"$defs": {}}}},
            {"properties": {"a": True}},
            {"oneOf": []},
            {"$defs": {"a": {"$ref": "#/$defs/b"}, "b": {"$ref": "#/$defs/a"}}},
        ]
        for schema in bad:
            with self.subTest(schema=schema):
                self.assertNotEqual(check_schema(schema), [])

    def test_good_schema(self) -> None:
        schema = {
            "$defs": {"d": {"type": "string", "format": "date"}},
            "type": "object",
            "required": ["a"],
            "additionalProperties": False,
            "properties": {"a": {"$ref": "#/$defs/d"}, "b": False, "c": {"type": "array", "items": {}, "minItems": 1}},
            "oneOf": [{"required": ["a"]}, {"required": ["c"]}],
        }
        self.assertEqual(check_schema(schema), [])


if __name__ == "__main__":
    unittest.main()
