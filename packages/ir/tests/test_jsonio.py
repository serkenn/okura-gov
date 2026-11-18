"""loads（JSON の厳密な読み込み）のテスト。"""

from __future__ import annotations

import unittest

from okura_ir import loads


def code_of(data, **kwargs) -> list[str]:
    _, problems = loads(data, **kwargs)
    return [p.code for p in problems]


class LoadsTest(unittest.TestCase):
    def test_reads_bytes_and_str(self) -> None:
        self.assertEqual(loads(b'{"a": [1, "\xe3\x81\x82"]}'), ({"a": [1, "あ"]}, []))
        self.assertEqual(loads('{"a": 1.5}'), ({"a": 1.5}, []))

    def test_duplicate_keys_are_rejected_even_when_nested(self) -> None:
        self.assertEqual(code_of('{"a": {"b": 1, "b": 2}}'), ["json_duplicate_key"])

    def test_non_json_constants_are_rejected(self) -> None:
        for text in ('{"a": NaN}', '{"a": Infinity}', '{"a": -Infinity}'):
            with self.subTest(text=text):
                self.assertEqual(code_of(text), ["json_constant"])

    def test_bom_is_rejected(self) -> None:
        self.assertEqual(code_of(b"\xef\xbb\xbf{}"), ["json_bom"])
        self.assertEqual(code_of("﻿{}"), ["json_bom"])

    def test_invalid_utf8_is_rejected(self) -> None:
        self.assertEqual(code_of(b'{"a": "\xff"}'), ["json_not_utf8"])

    def test_syntax_errors(self) -> None:
        for text in ("{", "{'a': 1}", '{"a": 1,}', "", "[1 2]"):
            with self.subTest(text=text):
                self.assertEqual(code_of(text), ["json_syntax"])

    def test_too_many_digits(self) -> None:
        self.assertEqual(code_of('{"a": ' + "9" * 5000 + "}"), ["json_syntax"])

    def test_nesting_limit_ignores_brackets_in_strings(self) -> None:
        self.assertEqual(code_of("[" * 65 + "]" * 65), ["json_too_deep"])
        self.assertEqual(code_of("[" * 64 + "]" * 64), [])
        self.assertEqual(code_of('["' + "[" * 1000 + '\\"{"]'), [])
        self.assertEqual(code_of('["\\\\", "' + "{" * 100 + '"]'), [])  # 逆斜線で終わる文字列の後
        self.assertEqual(code_of("[" * 200000), ["json_too_deep"])

    def test_size_limit(self) -> None:
        self.assertEqual(code_of(b"[1, 2, 3]", max_bytes=4), ["json_too_large"])
        self.assertEqual(code_of("[1, 2, 3]", max_bytes=4), ["json_too_large"])

    def test_wrong_input_type(self) -> None:
        self.assertEqual(code_of(123), ["json_syntax"])  # type: ignore[arg-type]

    def test_problem_value_is_none(self) -> None:
        value, problems = loads("{")
        self.assertIsNone(value)
        self.assertEqual(len(problems), 1)


if __name__ == "__main__":
    unittest.main()
