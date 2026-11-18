"""年齢の境目の説明の仕組み（2026-11-12）：達する日の数え方・判定の日・evaluate._age_boundaries・概念辞書の宣言の形。
どれも関数を直接呼ぶユニットテスト（上流の値はスタブ。D24）。"""

from __future__ import annotations

import datetime as _dt
import unittest
from types import SimpleNamespace

from okura_core.basis import SourceKind
from okura_core.concepts import AgeBoundaryInfo, ConceptProblem, Definition, _concept
from okura_core.evaluate import _age_boundaries, _reference_day
from okura_core.registry import AgeBoundarySpec
from okura_core.result import AgeBoundary, Count, Flag, ResultValue, TimeKey, age_at_end_of, attained_on
from okura_core.timepoints import Unit

D = _dt.date


class TestAttainedOn(unittest.TestCase):
    """年齢は誕生日の前日の終了時に加わる（年齢計算ニ関スル法律・民法第143条）。2月29日生まれは平年の2月28日。"""

    def test_january_first_birth_attains_on_previous_december_31(self) -> None:
        self.assertEqual(attained_on(D(2008, 1, 1), 19), D(2026, 12, 31))
        self.assertEqual(age_at_end_of(D(2008, 1, 1), D(2026, 12, 31)), 19)
        self.assertEqual(age_at_end_of(D(2008, 1, 2), D(2026, 12, 31)), 18)

    def test_february_29_birth(self) -> None:
        self.assertEqual(attained_on(D(2008, 2, 29), 19), D(2027, 2, 28))  # 平年：応当する日がないので月の末日
        self.assertEqual(attained_on(D(2004, 2, 29), 20), D(2024, 2, 28))  # 閏年：応当する日の前日
        self.assertEqual(age_at_end_of(D(2008, 2, 29), D(2027, 2, 27)), 18)
        self.assertEqual(age_at_end_of(D(2008, 2, 29), D(2027, 2, 28)), 19)


class TestReferenceDay(unittest.TestCase):
    def test_year_end_and_death(self) -> None:
        unit = Unit(2026, None, ())
        alive = {"id": "p", "birth_on": "2000-01-01"}
        dead = {"id": "p", "birth_on": "2000-01-01", "death_on": "2026-06-10"}
        self.assertEqual(_reference_day("その年12月31日（死亡の時はその前日）", unit, alive), D(2026, 12, 31))
        self.assertEqual(_reference_day("その年12月31日（死亡の時はその前日）", unit, dead), D(2026, 6, 9))
        self.assertEqual(_reference_day("その年12月31日", unit, dead), D(2026, 12, 31))
        self.assertIsNone(_reference_day("判定日", unit, alive))  # 判定日の単位でない

    def test_judgment_date(self) -> None:
        unit = Unit(2026, D(2026, 4, 1), ())
        p = {"id": "p", "birth_on": "2000-01-01"}
        self.assertEqual(_reference_day("判定日", unit, p), D(2026, 4, 1))
        self.assertEqual(_reference_day("判定日の属する年の12月31日", unit, p), D(2026, 12, 31))


def _value(vid: str, var: str, value: object, time: TimeKey) -> ResultValue:
    return ResultValue(vid, "国年." + var, var, "p", time, value, frozenset(), ())  # type: ignore[arg-type]


class TestAgeBoundaries(unittest.TestCase):
    """宣言した年齢の数（基準の年齢）で、判定日の終了時の年齢を比べる。規則モジュールの年齢と違えば出さない。"""

    def setUp(self) -> None:
        self.spec = AgeBoundarySpec(
            boundary_id="国年.試験_年齢の下限", related_variable="年金_試験_判定", age_variable="年金_試験_年齢",
            reference="判定日", criterion=None, age_value=20, comparison="以上", exclude_variable=None, from_param=None,
        )
        definition = Definition("国民年金法第7条第1項第3号", SourceKind.LAW, ("docs/public-sources/x.md#2",))
        self.reg = SimpleNamespace(age_boundaries=(self.spec,), dictionary=SimpleNamespace(by_variable=lambda v: SimpleNamespace(definition=definition)))
        self.unit = Unit(2026, D(2026, 4, 1), ())
        self.time = TimeKey("on", "2026-04-01")

    def run_with(self, birth: str, module_age: int) -> list[AgeBoundary]:
        by_key = {
            ("年金_試験_判定", "p"): _value("v:j", "年金_試験_判定", Flag(True), self.time),
            ("年金_試験_年齢", "p"): _value("v:a", "年金_試験_年齢", Count(module_age), self.time),
        }
        ir = {"persons": [{"id": "p", "birth_on": birth}]}
        return _age_boundaries(by_key, ["p"], self.unit, self.reg, ir, None)  # type: ignore[arg-type]

    def test_reaches_the_age_at_the_end_of_the_judgment_date(self) -> None:
        (b,) = self.run_with("2006-04-02", 20)  # 2026-04-01 の終了時に20歳
        self.assertEqual((b.age, b.holds, b.boundary_on, b.days_to_boundary), (20, True, D(2026, 4, 1), 0))
        self.assertEqual(b.criterion.value, 20)
        self.assertEqual(b.to_dict()["kind"], "下限")

    def test_days_until_the_boundary(self) -> None:
        (b,) = self.run_with("2006-04-03", 19)
        self.assertEqual((b.holds, b.boundary_on, b.days_to_boundary, b.crossing_age), (False, D(2026, 4, 2), 1, 20))

    def test_not_shown_when_module_age_is_for_another_day(self) -> None:
        self.assertEqual(self.run_with("2006-04-02", 19), [])

    def test_invariants(self) -> None:
        (b,) = self.run_with("2006-04-03", 19)
        with self.assertRaises(ValueError):
            AgeBoundary(**{**b.__dict__, "days_to_boundary": 2})


class TestDeclarationShape(unittest.TestCase):
    """概念辞書の「年齢の境目」の形：基準（パラメータ）か基準の年齢と比較のどちらか、判定の日は決まった名前。"""

    BASE = {
        "id": "国年.試験", "名称": "試験", "定義": {"条文": "国民年金法", "根拠の種類": "法律", "出典": ["docs/x.md#1"]},
        "判定の時点": "判定日", "層": "事実", "エンティティ": "人物", "期間": "年", "値の型": "真偽", "変数": ["年金_試験"],
        "実装済み": True, "出力": {"申告の欄": False, "申告の範囲": False},
    }

    def parse(self, ab: dict) -> tuple[object, list[ConceptProblem]]:
        problems: list[ConceptProblem] = []
        c = _concept({**self.BASE, "年齢の境目": [ab]}, "x.yaml.概念[0]", "国年", "x.yaml", problems)
        return c, problems

    def test_literal_age_with_comparison(self) -> None:
        c, problems = self.parse({"id": "国年.試験_下限", "比べる年齢": "国年.年齢", "基準の年齢": 20, "比較": "以上", "判定の日": "判定日"})
        self.assertEqual(problems, [])
        self.assertEqual(c.age_boundaries, (AgeBoundaryInfo("国年.試験_下限", "国年.年齢", "判定日", None, 20, "以上"),))  # type: ignore[union-attr]

    def test_shape_errors(self) -> None:
        for ab in (
            {"id": "国年.a", "比べる年齢": "国年.年齢", "基準": "国年.x", "基準の年齢": 20, "比較": "以上", "判定の日": "判定日"},
            {"id": "国年.a", "比べる年齢": "国年.年齢", "基準の年齢": 20, "判定の日": "判定日"},
            {"id": "国年.a", "比べる年齢": "国年.年齢", "基準の年齢": 20, "比較": "以上", "判定の日": "誕生日"},
        ):
            _, problems = self.parse(ab)
            self.assertTrue(problems, ab)


if __name__ == "__main__":
    unittest.main()
