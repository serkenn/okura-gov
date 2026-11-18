"""validate が例外で落ちず、問題の一覧を返すことのテスト。"""

from __future__ import annotations

import copy
import json
import math
import random
import unittest
from importlib import resources

from okura_ir import Problem, validate

VALID = resources.files("okura_ir").joinpath("examples", "valid")

JUNK = [
    None, True, False, 0, -1, 1.5, math.nan, math.inf, "", "100*3", "2026-02-30", [], [None], {}, {"x": 1},
    {1: 2}, (1, 2), {1, 2}, b"bytes", object(), "a\ud800", 10**30, "x" * 3000,
]


def _paths(node, prefix=()):
    """値の場所（キー・添字の列）を全部たどる。"""
    yield prefix
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _paths(v, prefix + (k,))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _paths(v, prefix + (i,))


def _replace(root, path, value):
    if not path:
        return value
    node = root
    for k in path[:-1]:
        node = node[k]
    node[path[-1]] = value
    return root


class RobustnessTest(unittest.TestCase):
    def assert_problem_list(self, result) -> None:
        self.assertIsInstance(result, list)
        for problem in result:
            self.assertIsInstance(problem, Problem)
            self.assertNotIn(problem.code, {"internal_error", "schema_error"})

    def test_top_level_junk(self) -> None:
        for value in JUNK + [{"schema_version": 0}, {"schema_version": "0"}, {"schema_version": "0", "persons": "x"}]:
            with self.subTest(value=repr(value)[:40]):
                result = validate(value)
                self.assert_problem_list(result)
                self.assertNotEqual(result, [])

    def test_self_referencing_structures(self) -> None:
        ir = json.loads((VALID / "01_student_away_and_parent_on_assignment.json").read_text(encoding="utf-8"))
        loop: list = []
        loop.append(loop)
        ir["persons"] = loop
        d: dict = {}
        d["self"] = d
        ir["facts"][0]["attributes"] = d
        self.assert_problem_list(validate(ir))

    def test_random_mutations_never_raise(self) -> None:
        rng = random.Random(20261111)
        for path in sorted(VALID.iterdir(), key=lambda p: p.name):
            if not path.name.endswith(".json"):
                continue
            base = json.loads(path.read_text(encoding="utf-8"))
            places = list(_paths(base))
            for _ in range(150):
                ir = copy.deepcopy(base)
                for _ in range(rng.randint(1, 3)):
                    # JUNK の値は写しを入れる（同じ list・dict を2か所に入れると、ほかの入れ替えで自分を含む構造になり、_paths が止まらない。
                    # 2026-11-12：例を足して乱数の並びが変わり、[None] の中に [None] 自身を入れる組合せが出た）
                    ir = _replace(ir, rng.choice(places), copy.deepcopy(rng.choice(JUNK)))
                    places_now = list(_paths(ir)) if isinstance(ir, (dict, list)) else [()]
                    places = places_now or [()]
                with self.subTest(example=path.name):
                    self.assert_problem_list(validate(ir))
                places = list(_paths(base))


if __name__ == "__main__":
    unittest.main()
