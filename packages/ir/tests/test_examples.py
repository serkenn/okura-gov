"""同梱の例（examples/valid・examples/invalid）を使った単体テスト。"""

from __future__ import annotations

import json
import unittest
from importlib import resources

from okura_ir import loads, validate

EXAMPLES = resources.files("okura_ir").joinpath("examples")


def _json_files(directory) -> list:
    return sorted((p for p in directory.iterdir() if p.name.endswith(".json")), key=lambda p: p.name)


class ValidExamplesTest(unittest.TestCase):
    def test_there_are_valid_examples(self) -> None:
        self.assertGreaterEqual(len(_json_files(EXAMPLES / "valid")), 4)

    def test_valid_examples_have_no_problems(self) -> None:
        for path in _json_files(EXAMPLES / "valid"):
            with self.subTest(example=path.name):
                ir, problems = loads(path.read_bytes())
                self.assertEqual(problems, [])
                self.assertEqual(validate(ir), [])

    def test_valid_examples_use_fictional_municipality_codes(self) -> None:
        # 例の団体コードは実在しない「99」で始まる架空のもの（README）
        for path in _json_files(EXAMPLES / "valid"):
            ir, _ = loads(path.read_bytes())
            for section in ("residences", "facts", "assets"):
                for record in ir[section]:
                    code = record.get("attributes", {}).get("municipality_code")
                    if code is not None:
                        with self.subTest(example=path.name, record=record["id"]):
                            self.assertTrue(code.startswith("99"))


class InvalidExamplesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = EXAMPLES / "invalid"
        self.expected = json.loads((self.directory / "expected.json").read_text(encoding="utf-8"))

    def test_every_invalid_example_has_expectations(self) -> None:
        files = {p.name for p in _json_files(self.directory)} - {"expected.json"}
        self.assertEqual(files, set(self.expected))

    def test_invalid_examples_report_exactly_the_expected_problems(self) -> None:
        for name, spec in self.expected.items():
            with self.subTest(example=name):
                ir, problems = loads((self.directory / name).read_bytes())
                if not problems:
                    problems = validate(ir)
                got = sorted((p.code, p.path) for p in problems)
                want = sorted((x["code"], x["path"]) for x in spec["problems"])
                self.assertEqual(got, want, msg=spec["description"])

    def test_problem_messages_are_present(self) -> None:
        for name in self.expected:
            ir, problems = loads((self.directory / name).read_bytes())
            for problem in problems or validate(ir):
                self.assertTrue(problem.message)
                self.assertEqual(set(problem.to_dict()), {"path", "code", "message"})


if __name__ == "__main__":
    unittest.main()
