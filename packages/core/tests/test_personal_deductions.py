"""規則モジュール personal_deductions（rules/personal_deductions/）のテスト。

年分は令和7年分（2025）と令和8年分（2026）。期待値は docs の一次情報（各テストのコメントの節）。
扶養所属・法律婚のグループは、割当てが与えられた前提で OpenFisca に直接渡す（evaluate はこの版ではグループを組み立てない）。
まだない上流の概念（合計所得金額など）と未実装の人の区分は、入力として与えて単独で確かめる。テストのデータは架空の人だけ。
"""

from __future__ import annotations

import datetime as _dt
import unittest
from typing import Any

from openfisca_core.simulation_builder import SimulationBuilder

from okura_core import evaluate
from okura_core.result import Count, Flag, OutOfScopeCategory, State, TimeKey, YenAmount, check_result_json

from .support import make_ir, make_query, person, salary, system

R7, R8 = 2025, 2026
T25, T26 = TimeKey("tax_year", R7), TimeKey("tax_year", R8)

# よく使う変数名
TOTAL = "所得税_合計所得金額"
RELATIVE = "所得税_申告者の親族か"
SAME_LIVING = "所得税_申告者と生計を一にするか"


def _date(s: str) -> _dt.date:
    return _dt.date.fromisoformat(s)


def _birth_for_age(year: int, age: int) -> str:
    """その年の12月31日の現況で age 歳の、1月1日生まれでない生年月日（3月3日生まれ）。"""
    return f"{year - age}-03-03"


def _sim(year: int, people: dict[str, dict[str, Any]], *, dependents: dict[str, list[str]] | None = None, couples: list[tuple[str, str]] | None = None):
    """OpenFisca の simulation を作る。dependents：申告者 → 扶養親族等、couples：法律婚の組。"""
    y = str(year)
    persons = {p: {k: {y: v} for k, v in vs.items()} for p, vs in people.items()}
    situation: dict[str, Any] = {"人物一覧": persons}
    if dependents is not None:
        members = {q for qs in dependents.values() for q in qs}
        groups = {f"f-{a}": {"申告者一覧": [a], "扶養親族等一覧": qs} for a, qs in dependents.items()}
        groups.update({f"f-{p}": {"申告者一覧": [p]} for p in people if p not in members and p not in dependents})
        situation["扶養所属一覧"] = groups
    if couples is not None:
        paired = {x for c in couples for x in c}
        marriages = {f"m-{a}": {"配偶者一覧": [a, b]} for a, b in couples}
        marriages.update({f"m-{p}": {"配偶者一覧": [p]} for p in people if p not in paired})
        situation["法律婚一覧"] = marriages
    return SimulationBuilder().build_from_entities(system(), situation)


def _one(year: int, var: str, facts: dict[str, Any], **kw: Any) -> Any:
    sim = _sim(year, {"a": facts}, **kw)
    return sim.calculate(var, str(year))[0]


def _ok(res):
    if not res.ok:
        raise AssertionError(res.to_dict())
    problems = check_result_json(res.to_dict())
    if problems:
        raise AssertionError(problems)
    return res


class TestAge(unittest.TestCase):
    """年齢：12月31日の終了時の年齢（1月1日生まれは1つ加わる）。出典 misc §1.2・§1.3、実測 misc-fetch-and-age-check §4.2。"""

    def _age(self, year: int, birth: str, death: str | None = None) -> int:
        facts: dict[str, Any] = {"所得税_生年月日": _date(birth)}
        if death:
            facts["所得税_死亡日"] = _date(death)
        return int(_one(year, "所得税_年齢", facts))

    def test_january_first_birthdays(self) -> None:
        cases = [
            # 令和7年分の特定扶養親族：平成15年1月2日〜平成19年1月1日生（misc §1.2）
            (R7, "2003-01-02", 22),
            (R7, "2003-01-01", 23),
            (R7, "2007-01-01", 19),
            (R7, "2007-01-02", 18),
            # 令和8年分の特定扶養親族：平成16年1月2日〜平成20年1月1日生（misc §1.2）
            (R8, "2004-01-02", 22),
            (R8, "2004-01-01", 23),
            (R8, "2008-01-01", 19),
            (R8, "2008-01-02", 18),
            # 16歳以上：令和7年分は平成22年1月1日以前、令和8年分は平成23年1月1日以前（misc §1.2）
            (R7, "2010-01-01", 16),
            (R7, "2010-01-02", 15),
            (R8, "2011-01-01", 16),
            (R8, "2011-01-02", 15),
            # 70歳以上：令和7年分は昭和31年1月1日以前、令和8年分は昭和32年1月1日以前（misc §1.2）
            (R7, "1956-01-01", 70),
            (R7, "1956-01-02", 69),
            (R8, "1957-01-01", 70),
            (R8, "1957-01-02", 69),
        ]
        for year, birth, age in cases:
            with self.subTest(year=year, birth=birth):
                self.assertEqual(self._age(year, birth), age)

    def test_february_29(self) -> None:
        # 2004-02-29 生まれは令和8年分で22歳（実測 misc-fetch-and-age-check §4.2）
        self.assertEqual(self._age(R8, "2004-02-29"), 22)

    def test_age_at_death(self) -> None:
        # 死亡の時の現況（所法85③：misc §1.1）。誕生日の前に死亡すれば年齢は加わらない
        self.assertEqual(self._age(R8, "1956-07-01", "2026-05-10"), 69)
        self.assertEqual(self._age(R8, "1956-07-01", "2026-08-10"), 70)




class TestBasicDeduction(unittest.TestCase):
    """基礎控除：所法86①（gaps §4.1）＋措法41の16の2（R1 §2、実測 R1 §3）。"""

    def _check(self, year: int, cases: list[tuple[int, int]]) -> None:
        for total, expected in cases:
            with self.subTest(year=year, total=total):
                self.assertEqual(int(_one(year, "所得税_基礎控除の額", {TOTAL: total})), expected)

    def test_r7(self) -> None:
        self._check(
            R7,
            [
                (0, 950_000),
                (1_320_000, 950_000),
                (1_320_001, 880_000),
                (3_360_000, 880_000),
                (3_360_001, 680_000),
                (4_890_000, 680_000),
                (4_890_001, 630_000),
                (6_550_000, 630_000),
                (6_550_001, 580_000),
                (23_500_000, 580_000),
                (23_500_001, 480_000),
                (24_000_000, 480_000),
                (24_000_001, 320_000),
                (24_500_000, 320_000),
                (24_500_001, 160_000),
                (25_000_000, 160_000),
                (25_000_001, 0),
            ],
        )

    def test_r8(self) -> None:
        self._check(
            R8,
            [
                (0, 1_040_000),
                (4_890_000, 1_040_000),
                (4_890_001, 670_000),
                (6_550_000, 670_000),
                (6_550_001, 620_000),
                (23_500_000, 620_000),
                (23_500_001, 480_000),
                (24_500_001, 160_000),
                (25_000_000, 160_000),
                (25_000_001, 0),
            ],
        )



def _dependent(year: int, age: int, total: int = 0, **extra: Any) -> dict[str, Any]:
    return {"所得税_生年月日": _date(_birth_for_age(year, age)), RELATIVE: True, SAME_LIVING: True, TOTAL: total, **extra}


class TestDependents(unittest.TestCase):
    """扶養親族・扶養控除：所法2①三十四〜三十四の四、84①（R1 §2・§4、elderly-abroad-laws §1）、措法41の16（同 §2）。"""

    def _deduction(self, year: int, q: dict[str, Any]) -> int:
        sim = _sim(year, {"p": {TOTAL: 5_000_000}, "q": q}, dependents={"p": ["q"]})
        return int(sim.calculate("所得税_扶養控除の額", str(year))[0])

    def test_amount_by_age(self) -> None:
        for year in (R7, R8):
            for age, expected in [(15, 0), (16, 380_000), (18, 380_000), (19, 630_000), (22, 630_000), (23, 380_000), (69, 380_000), (70, 480_000)]:
                with self.subTest(year=year, age=age):
                    self.assertEqual(self._deduction(year, _dependent(year, age)), expected)

    def test_income_requirement_boundary(self) -> None:
        # 令和7年分 58万円以下、令和8年分 62万円以下（R1 §2）
        for year, limit in ((R7, 580_000), (R8, 620_000)):
            with self.subTest(year=year):
                self.assertEqual(self._deduction(year, _dependent(year, 30, limit)), 380_000)
                self.assertEqual(self._deduction(year, _dependent(year, 30, limit + 1)), 0)

    def test_cohabiting_elderly_lineal_ascendant(self) -> None:
        # 同居老親等 58万円＝48万円＋10万円（elderly-abroad-laws §1.2）
        q = _dependent(R8, 75, **{"所得税_申告者の直系尊属か": True, "所得税_申告者と同居を常況としているか": True})
        self.assertEqual(self._deduction(R8, q), 580_000)
        # 同居でない・直系尊属でないと48万円
        self.assertEqual(self._deduction(R8, _dependent(R8, 75, **{"所得税_申告者の直系尊属か": True})), 480_000)
        self.assertEqual(self._deduction(R8, _dependent(R8, 75, **{"所得税_申告者と同居を常況としているか": True})), 480_000)

    def test_requirements(self) -> None:
        self.assertEqual(self._deduction(R8, _dependent(R8, 30, **{RELATIVE: False})), 0)
        self.assertEqual(self._deduction(R8, _dependent(R8, 30, **{SAME_LIVING: False})), 0)
        self.assertEqual(self._deduction(R8, _dependent(R8, 30, **{"所得税_申告者等の事業専従者か": True})), 0)

    def test_sum_goes_to_the_filer_only(self) -> None:
        sim = _sim(R8, {"p": {TOTAL: 5_000_000}, "q": _dependent(R8, 20), "r": _dependent(R8, 16)}, dependents={"p": ["q", "r"]})
        self.assertEqual(list(sim.calculate("所得税_扶養控除の額", str(R8))), [1_010_000, 0, 0])

    def test_under_16_is_a_dependent_but_not_deductible(self) -> None:
        # 年少扶養親族：扶養親族に当たるが控除対象扶養親族でない（misc §1.2）
        sim = _sim(R8, {"p": {TOTAL: 5_000_000}, "q": _dependent(R8, 10)}, dependents={"p": ["q"]})
        self.assertTrue(sim.calculate("所得税_扶養親族に当たるか", str(R8))[1])
        self.assertFalse(sim.calculate("所得税_控除対象扶養親族に当たるか", str(R8))[1])


class TestNonResidentDependents(unittest.TestCase):
    """非居住者である扶養親族：所法2①三十四の二ロ（elderly-abroad-laws §3.1）、書類（同 §3.2）。"""

    def _flag(self, age: int, **extra: Any) -> bool:
        q = _dependent(
            R8, age, **{"所得税_判定の時に住所が国内にあるか": False, "所得税_国外居住親族の書類の要件を満たすか": True, **extra}
        )
        sim = _sim(R8, {"p": {TOTAL: 5_000_000}, "q": q}, dependents={"p": ["q"]})
        return bool(sim.calculate("所得税_控除対象扶養親族に当たるか", str(R8))[1])

    def test_ages(self) -> None:
        self.assertFalse(self._flag(15))
        self.assertTrue(self._flag(16))
        self.assertTrue(self._flag(29))
        self.assertFalse(self._flag(30))
        self.assertFalse(self._flag(69))
        self.assertTrue(self._flag(70))

    def test_30_to_69_categories(self) -> None:
        study = {"所得税_留学により国内に住所及び居所を有しなくなった者か": True}
        doc_study = {"所得税_国外居住親族の留学の区分の書類の要件を満たすか": True}
        doc_38 = {"所得税_国外居住親族の38万円以上の区分の書類の要件を満たすか": True}
        self.assertTrue(self._flag(35, **study, **doc_study))
        self.assertTrue(self._flag(35, **{"所得税_身体障害者手帳の障害の程度の級": 3}))
        self.assertTrue(self._flag(35, **{"所得税_申告者から受けた生活費等の支払の額": 380_000}, **doc_38))
        self.assertFalse(self._flag(35, **{"所得税_申告者から受けた生活費等の支払の額": 379_999}, **doc_38))

    def test_30_to_69_documents_by_category(self) -> None:
        # 所令262④二・三（elderly-abroad-laws §3.2）：留学は留学ビザ等書類、38万円以上は38万円送金書類が要る。障害者は第1号の書類だけ
        self.assertFalse(self._flag(35, **{"所得税_留学により国内に住所及び居所を有しなくなった者か": True}))
        self.assertFalse(self._flag(35, **{"所得税_申告者から受けた生活費等の支払の額": 380_000}))
        # 38万円送金書類があれば、第1号の書類（送金関係書類）がなくてもよい（第3号はイ・ロの2つ）
        self.assertTrue(self._flag(35, **{"所得税_申告者から受けた生活費等の支払の額": 380_000, "所得税_国外居住親族の書類の要件を満たすか": False,
                                          "所得税_国外居住親族の38万円以上の区分の書類の要件を満たすか": True}))
        self.assertFalse(self._flag(35, **{"所得税_身体障害者手帳の障害の程度の級": 3, "所得税_国外居住親族の書類の要件を満たすか": False}))
        # 区分の要件のない年齢では区分ごとの書類を見ない
        self.assertFalse(self._flag(70, **{"所得税_国外居住親族の書類の要件を満たすか": False, "所得税_国外居住親族の38万円以上の区分の書類の要件を満たすか": True}))

    def test_documents_are_required(self) -> None:
        self.assertFalse(self._flag(20, **{"所得税_国外居住親族の書類の要件を満たすか": False}))


class TestSpecifiedRelative(unittest.TestCase):
    """特定親族特別控除：所法84の2（R1 §3）。額の表：令和7年分 Q&A 1−5、令和8年分 あらまし p.2（kyuyo-sources §4.3・§4.4）。"""

    TABLE = [
        (850_000, 630_000),
        (850_001, 610_000),
        (900_000, 610_000),
        (900_001, 510_000),
        (950_000, 510_000),
        (950_001, 410_000),
        (1_000_000, 410_000),
        (1_000_001, 310_000),
        (1_050_000, 310_000),
        (1_050_001, 210_000),
        (1_100_000, 210_000),
        (1_100_001, 110_000),
        (1_150_000, 110_000),
        (1_150_001, 60_000),
        (1_200_000, 60_000),
        (1_200_001, 30_000),
        (1_230_000, 30_000),
        (1_230_001, 0),
    ]

    def _amounts(self, year: int, total: int, age: int = 20) -> tuple[int, int]:
        sim = _sim(year, {"p": {TOTAL: 5_000_000}, "q": _dependent(year, age, total)}, dependents={"p": ["q"]})
        y = str(year)
        return int(sim.calculate("所得税_扶養控除の額", y)[0]), int(sim.calculate("所得税_特定親族特別控除の額", y)[0])

    def test_table(self) -> None:
        for year in (R7, R8):
            for total, expected in self.TABLE:
                with self.subTest(year=year, total=total):
                    self.assertEqual(self._amounts(year, total), (0, expected))

    def test_boundary_with_dependent(self) -> None:
        # 上限まで特定扶養親族 63万円、1円超えると特定親族 63万円（R1 §3）
        for year, limit in ((R7, 580_000), (R8, 620_000)):
            with self.subTest(year=year):
                self.assertEqual(self._amounts(year, limit), (630_000, 0))
                self.assertEqual(self._amounts(year, limit + 1), (0, 630_000))

    def test_age_range(self) -> None:
        self.assertEqual(self._amounts(R8, 700_000, 18), (0, 0))
        self.assertEqual(self._amounts(R8, 700_000, 19), (0, 630_000))
        self.assertEqual(self._amounts(R8, 700_000, 22), (0, 630_000))
        self.assertEqual(self._amounts(R8, 700_000, 23), (0, 0))

    def test_exclusion(self) -> None:
        q = _dependent(R8, 20, 700_000, **{"所得税_特定親族特別控除の適用除外に当たるか": True})
        sim = _sim(R8, {"p": {TOTAL: 5_000_000}, "q": q}, dependents={"p": ["q"]})
        self.assertEqual(int(sim.calculate("所得税_特定親族特別控除の額", str(R8))[0]), 0)


class TestSpouse(unittest.TestCase):
    """配偶者控除（所法83：spouse §1.2）・配偶者特別控除（所法83の2：spouse §1.3、実測 spouse-fetch-and-tables §3.2）。"""

    def _calc(self, year: int, own: int, spouse: int, *, spouse_age: int = 50, **own_facts: Any) -> tuple[int, int]:
        people = {
            "p": {TOTAL: own, "所得税_配偶者がいるか": True, "所得税_配偶者と生計を一にするか": True, **own_facts},
            "s": {TOTAL: spouse, "所得税_生年月日": _date(_birth_for_age(year, spouse_age))},
        }
        sim = _sim(year, people, couples=[("p", "s")])
        y = str(year)
        return int(sim.calculate("所得税_配偶者控除の額", y)[0]), int(sim.calculate("所得税_配偶者特別控除の額", y)[0])

    def test_spouse_deduction_tiers(self) -> None:
        for own, general, elderly in [(9_000_000, 380_000, 480_000), (9_000_001, 260_000, 320_000), (9_500_000, 260_000, 320_000), (9_500_001, 130_000, 160_000), (10_000_000, 130_000, 160_000), (10_000_001, 0, 0)]:
            with self.subTest(own=own):
                self.assertEqual(self._calc(R8, own, 100_000)[0], general)
                self.assertEqual(self._calc(R8, own, 100_000, spouse_age=70)[0], elderly)

    def test_boundary_between_the_two(self) -> None:
        for year, limit in ((R7, 580_000), (R8, 620_000)):
            with self.subTest(year=year):
                self.assertEqual(self._calc(year, 5_000_000, limit), (380_000, 0))
                self.assertEqual(self._calc(year, 5_000_000, limit + 1), (0, 380_000))

    def test_special_table(self) -> None:
        # 実測 spouse-fetch-and-tables §3.2 の表（本人900万円以下 / 900万円超950万円以下 / 950万円超1,000万円以下）
        rows = [
            (950_000, 380_000, 260_000, 130_000),
            (950_001, 360_000, 240_000, 120_000),
            (1_000_000, 360_000, 240_000, 120_000),
            (1_000_001, 310_000, 210_000, 110_000),
            (1_050_001, 260_000, 180_000, 90_000),
            (1_100_001, 210_000, 140_000, 70_000),
            (1_150_001, 160_000, 110_000, 60_000),
            (1_200_001, 110_000, 80_000, 40_000),
            (1_250_001, 60_000, 40_000, 20_000),
            (1_300_000, 60_000, 40_000, 20_000),
            (1_300_001, 30_000, 20_000, 10_000),
            (1_330_000, 30_000, 20_000, 10_000),
            (1_330_001, 0, 0, 0),
        ]
        for year in (R7, R8):
            for spouse, a, b, c in rows:
                with self.subTest(year=year, spouse=spouse):
                    self.assertEqual(self._calc(year, 9_000_000, spouse)[1], a)
                    self.assertEqual(self._calc(year, 9_000_001, spouse)[1], b)
                    self.assertEqual(self._calc(year, 9_500_001, spouse)[1], c)

    def test_own_income_over_ten_million(self) -> None:
        self.assertEqual(self._calc(R8, 10_000_001, 800_000), (0, 0))

    def test_exclusions(self) -> None:
        self.assertEqual(self._calc(R8, 5_000_000, 100_000, **{"所得税_配偶者が青色事業専従者等か": True}), (0, 0))
        self.assertEqual(self._calc(R8, 5_000_000, 100_000, **{"所得税_配偶者と生計を一にするか": False}), (0, 0))
        # 所法83の2② の適用除外（spouse §1.4）
        self.assertEqual(self._calc(R8, 5_000_000, 800_000, **{"所得税_配偶者特別控除の適用除外に当たるか": True}), (0, 0))

    def test_no_spouse_in_group(self) -> None:
        sim = _sim(R8, {"p": {TOTAL: 5_000_000, "所得税_配偶者と生計を一にするか": True}}, couples=[])
        self.assertEqual(int(sim.calculate("所得税_配偶者控除の額", str(R8))[0]), 0)

    def test_spouse_listed_as_someone_elses_dependent(self) -> None:
        # 所令218：他の居住者の扶養親族とされた配偶者は同一生計配偶者に当たらない（misc §3.2。割当ては入力）
        people = {
            "p": {TOTAL: 5_000_000, "所得税_配偶者と生計を一にするか": True},
            "s": {TOTAL: 100_000},
            "g": {TOTAL: 5_000_000},
        }
        sim = _sim(R8, people, couples=[("p", "s")], dependents={"g": ["s"]})
        self.assertEqual(int(sim.calculate("所得税_配偶者控除の額", str(R8))[0]), 0)


class TestDisability(unittest.TestCase):
    """障害者の範囲（所令10：jinteki §1.5）と障害者控除（所法79：jinteki §1.2）。"""

    def test_own_amount(self) -> None:
        for facts, expected in [
            ({}, 0),
            ({"所得税_身体障害者手帳の障害の程度の級": 3}, 270_000),
            ({"所得税_身体障害者手帳の障害の程度の級": 2}, 400_000),
            ({"所得税_身体障害者手帳の障害の程度の級": 1}, 400_000),
            ({"所得税_精神障害者保健福祉手帳の障害等級": 2}, 270_000),
            ({"所得税_精神障害者保健福祉手帳の障害等級": 1}, 400_000),
            ({"所得税_知的障害者と判定されているか": True}, 270_000),
            ({"所得税_知的障害者と判定されているか": True, "所得税_重度の知的障害者と判定されているか": True}, 400_000),
            ({"所得税_事理を弁識する能力を欠く常況にあるか": True}, 400_000),
            ({"所得税_戦傷病者手帳の交付を受けているか": True}, 270_000),
            ({"所得税_原子爆弾被爆者の認定を受けているか": True}, 400_000),
            ({"所得税_常に就床を要し複雑な介護を要するか": True}, 400_000),
            ({"所得税_手帳の申請中で障害が明らかか": True}, 270_000),
        ]:
            with self.subTest(facts=facts):
                self.assertEqual(int(_one(R8, "所得税_障害者控除の額", {"所得税_生年月日": _date("1980-03-03"), **facts})), expected)

    def test_municipal_certification_needs_age_65(self) -> None:
        # 所令10①七：年齢65歳以上。令和8年分は昭和37年1月1日以前生（misc §1.2）
        base = {"所得税_市町村長等の障害者の認定を受けているか": True}
        self.assertEqual(int(_one(R8, "所得税_障害者控除の額", {"所得税_生年月日": _date("1962-01-01"), **base})), 270_000)
        self.assertEqual(int(_one(R8, "所得税_障害者控除の額", {"所得税_生年月日": _date("1962-01-02"), **base})), 0)

    def test_dependent_amounts(self) -> None:
        # 16歳未満の扶養親族も対象（TA1160：jinteki §1.2）。同居特別障害者 75万円
        for facts, expected in [
            ({"所得税_身体障害者手帳の障害の程度の級": 4}, 270_000),
            ({"所得税_身体障害者手帳の障害の程度の級": 1}, 400_000),
            ({"所得税_身体障害者手帳の障害の程度の級": 1, "所得税_申告者等と同居を常況としているか": True}, 750_000),
        ]:
            with self.subTest(facts=facts):
                sim = _sim(R8, {"p": {TOTAL: 5_000_000}, "q": _dependent(R8, 10, **facts)}, dependents={"p": ["q"]})
                self.assertEqual(int(sim.calculate("所得税_障害者控除の額", str(R8))[0]), expected)

    def test_spouse_amounts(self) -> None:
        for spouse, expected in [
            ({"所得税_身体障害者手帳の障害の程度の級": 3}, 270_000),
            ({"所得税_身体障害者手帳の障害の程度の級": 1}, 400_000),
            ({"所得税_身体障害者手帳の障害の程度の級": 1, "所得税_配偶者等と同居を常況としているか": True}, 750_000),
        ]:
            with self.subTest(spouse=spouse):
                people = {"p": {TOTAL: 5_000_000, "所得税_配偶者と生計を一にするか": True}, "s": {TOTAL: 0, **spouse}}
                sim = _sim(R8, people, couples=[("p", "s")])
                self.assertEqual(int(sim.calculate("所得税_障害者控除の額", str(R8))[0]), expected)

    def test_not_same_living_spouse_gives_nothing(self) -> None:
        people = {"p": {TOTAL: 5_000_000}, "s": {TOTAL: 0, "所得税_身体障害者手帳の障害の程度の級": 1}}
        sim = _sim(R8, people, couples=[("p", "s")])
        self.assertEqual(int(sim.calculate("所得税_障害者控除の額", str(R8))[0]), 0)

    def _basis(self, rid: str, pid: str, basis: str, **attrs: Any) -> dict[str, Any]:
        return {"id": rid, "kind": "disability_basis", "roles": {"person": pid}, "when": {"from_on": "2020-01-01"}, "attributes": {"basis": basis, **attrs}}




class TestSingleParentAndWidow(unittest.TestCase):
    """ひとり親（所法2①三十一、所令11の2：jinteki §1.1・§1.4）・寡婦（所法2①三十：jinteki §1.1）。"""

    def _single(self, year: int, own: int, child_income: int, **own_facts: Any) -> int:
        child = {"所得税_申告者の子か": True, "所得税_総所得金額等": child_income}
        sim = _sim(year, {"p": {TOTAL: own, **own_facts}, "c": child}, dependents={"p": ["c"]})
        return int(sim.calculate("所得税_ひとり親控除の額", str(year))[0])

    def test_amount_and_limits(self) -> None:
        for year, limit in ((R7, 580_000), (R8, 620_000)):
            with self.subTest(year=year):
                self.assertEqual(self._single(year, 5_000_000, limit), 350_000)
                self.assertEqual(self._single(year, 5_000_001, limit), 0)
                self.assertEqual(self._single(year, 5_000_000, limit + 1), 0)

    def test_married_or_common_law(self) -> None:
        self.assertEqual(self._single(R8, 3_000_000, 0, **{"所得税_配偶者がいるか": True}), 0)
        self.assertEqual(self._single(R8, 3_000_000, 0, **{"所得税_住民票に事実婚の続柄の記載がある相手がいるか": True}), 0)
        self.assertEqual(self._single(R8, 3_000_000, 0, **{"所得税_配偶者がいるか": True, "所得税_配偶者の生死が明らかでない者か": True}), 350_000)

    def test_not_a_child(self) -> None:
        sim = _sim(R8, {"p": {TOTAL: 3_000_000}, "c": {"所得税_総所得金額等": 0}}, dependents={"p": ["c"]})
        self.assertEqual(int(sim.calculate("所得税_ひとり親控除の額", str(R8))[0]), 0)

    def _widow(self, year: int, own: int, **facts: Any) -> int:
        return int(_one(year, "所得税_寡婦控除の額", {TOTAL: own, **facts}))

    def test_widowed(self) -> None:
        k = "所得税_夫と死別した後婚姻をしていない者又は夫の生死の明らかでない者か"
        for year in (R7, R8):
            with self.subTest(year=year):
                self.assertEqual(self._widow(year, 5_000_000, **{k: True}), 270_000)
                self.assertEqual(self._widow(year, 5_000_001, **{k: True}), 0)
                self.assertEqual(self._widow(year, 3_000_000, **{k: True, "所得税_住民票に事実婚の続柄の記載がある相手がいるか": True}), 0)

    def test_divorced_needs_a_dependent(self) -> None:
        k = "所得税_夫と離婚した後婚姻をしていない者か"
        self.assertEqual(self._widow(R8, 3_000_000, **{k: True}), 0)
        sim = _sim(R8, {"p": {TOTAL: 3_000_000, k: True}, "q": _dependent(R8, 75)}, dependents={"p": ["q"]})
        self.assertEqual(int(sim.calculate("所得税_寡婦控除の額", str(R8))[0]), 270_000)

    def test_single_parent_takes_precedence(self) -> None:
        # 寡婦は「ひとり親に該当しないもの」（所法2①三十）
        k = "所得税_夫と死別した後婚姻をしていない者又は夫の生死の明らかでない者か"
        child = {"所得税_申告者の子か": True, "所得税_総所得金額等": 0}
        sim = _sim(R8, {"p": {TOTAL: 3_000_000, k: True}, "c": child}, dependents={"p": ["c"]})
        self.assertEqual(int(sim.calculate("所得税_寡婦控除の額", str(R8))[0]), 0)
        self.assertEqual(int(sim.calculate("所得税_ひとり親控除の額", str(R8))[0]), 350_000)


class TestWorkingStudent(unittest.TestCase):
    """勤労学生：所法2①三十二（gaps §1.1、R1 §2）、控除額 27万円（所法82）。"""

    def _amount(self, year: int, **facts: Any) -> int:
        base = {"所得税_学校教育法第1条の学校の学生等か": True, "所得税_給与等の収入金額": 1_000_000, "所得税_給与所得": 300_000, TOTAL: 300_000}
        return int(_one(year, "所得税_勤労学生控除の額", {**base, **facts}))

    def test_income_limit(self) -> None:
        for year, limit in ((R7, 850_000), (R8, 890_000)):
            with self.subTest(year=year):
                self.assertEqual(self._amount(year, **{TOTAL: limit, "所得税_給与所得": limit}), 270_000)
                self.assertEqual(self._amount(year, **{TOTAL: limit + 1, "所得税_給与所得": limit + 1}), 0)

    def test_other_income_limit(self) -> None:
        # 給与所得等以外の所得 10万円以下（R1 §2）
        self.assertEqual(self._amount(R8, **{TOTAL: 400_000}), 270_000)
        self.assertEqual(self._amount(R8, **{TOTAL: 400_001}), 0)

    def test_business_income_needs_the_judgment(self) -> None:
        facts = {"所得税_事業所得の金額": 300_000, TOTAL: 600_000}
        self.assertEqual(self._amount(R8, **facts), 0)
        self.assertEqual(self._amount(R8, **facts, **{"所得税_事業所得等が自己の勤労に基づくか": True}), 270_000)

    def test_not_a_student_or_no_earned_income(self) -> None:
        self.assertEqual(self._amount(R8, **{"所得税_学校教育法第1条の学校の学生等か": False}), 0)
        self.assertEqual(self._amount(R8, **{"所得税_給与等の収入金額": 0, "所得税_給与所得": 0, TOTAL: 0}), 0)

    def _enrollment(self, rid: str, pid: str, school_type: str) -> dict[str, Any]:
        return {"id": rid, "kind": "enrollment", "roles": {"person": pid}, "when": {"from_on": "2024-04-01"}, "attributes": {"school_type": school_type}}




def _stay(rid: str, pid: str, start: str, end: str | None = None, purpose: str = "tourism") -> dict[str, Any]:
    when: dict[str, str] = {"from_on": start}
    if end:
        when["to_on"] = end
    return {"id": rid, "kind": "abroad_stay", "roles": {"person": pid}, "when": when, "attributes": {"country": "ZZ", "purpose": purpose}}


def _address(jid: str, pid: str, value: str, start: str, end: str) -> dict[str, Any]:
    return {
        "id": jid,
        "kind": "判断.住所の所在",
        "judged_by": {"person": pid},
        "judged_at": "2027-01-10T09:00:00+09:00",
        "subject": {"person": pid},
        "when": {"from_on": start, "to_on": end},
        "value": value,
    }




def _parentage(rid: str, parent: str, child: str, on: str) -> dict[str, Any]:
    return {"id": rid, "kind": "parentage", "roles": {"parent": parent, "child": child}, "when": {"on": on}, "attributes": {"basis": "birth_mother"}}


def _marriage(rid: str, a: str, b: str, start: str, end: str | None = None, ended_by: str | None = None) -> dict[str, Any]:
    when: dict[str, str] = {"from_on": start}
    if end:
        when["to_on"] = end
    rec: dict[str, Any] = {"id": rid, "kind": "marriage", "roles": {"spouse_a": a, "spouse_b": b}, "when": when}
    if ended_by:
        rec["attributes"] = {"ended_by": ended_by}
    return rec




if __name__ == "__main__":
    unittest.main()


class TestWidowHusbandAndResidentRecord(unittest.TestCase):
    """寡婦の「夫」（所法2①三十：jinteki §1.1）を相手の法令上の性別で決めること、住民票の記載を確かめられない人の対象外の範囲（2026-11-11）。"""

    T = _dt.date(2026, 12, 31)

    def _idx(self, facts: list[dict[str, Any]]):
        from okura_core.registry import RECORD_SECTIONS
        from okura_core.rules.personal_deductions.ir_facts import IrIndex

        ir: dict[str, Any] = {s: [] for s in RECORD_SECTIONS}
        ir["persons"] = [{"id": p, "birth_on": "1970-01-01"} for p in ("w", "h")]
        ir["facts"] = facts
        return IrIndex(ir)

    @staticmethod
    def _divorce(by: str = "divorce") -> dict[str, Any]:
        return {"id": "m1", "kind": "marriage", "roles": {"spouse_a": "w", "spouse_b": "h"},
                "when": {"from_on": "2000-01-01", "to_on": "2020-06-30"}, "attributes": {"ended_by": by}}  # fmt: skip

    @staticmethod
    def _sex(pid: str, sex: str) -> dict[str, Any]:
        return {"id": f"sex-{pid}", "kind": "legal_sex", "roles": {"person": pid}, "when": {"from_on": "1970-01-01"}, "attributes": {"sex": sex}}

    def test_husband_by_legal_sex(self) -> None:
        from okura_core.rules.personal_deductions.ir_facts import ended_marriages

        for facts, expected in (([self._sex("h", "male")], True), ([self._sex("h", "female")], False), ([], None)):
            with self.subTest(expected=expected):
                (e,) = ended_marriages(self._idx([self._divorce(), *facts]), "w", self.T)
                self.assertTrue(e.divorced)
                self.assertIs(e.husband, expected)

    def test_unknown_sex_stops_only_without_a_known_husband(self) -> None:
        from okura_core.rules.personal_deductions.checks import _widow_sex_unknown_ids

        self.assertEqual(_widow_sex_unknown_ids(self._idx([self._divorce()]), "w", self.T), ("m1",))
        self.assertEqual(_widow_sex_unknown_ids(self._idx([self._divorce(), self._sex("h", "male")]), "w", self.T), ())

    def test_resident_record_unknown(self) -> None:
        from okura_core.rules.personal_deductions.ir_facts import cohabitation

        rec = {"id": "rr", "kind": "resident_record", "roles": {"person": "w"}, "when": {"from_on": "2000-01-01"},
               "attributes": {"municipality_code": "999991", "household_id": "hh", "householder": False}}  # fmt: skip
        self.assertTrue(cohabitation(self._idx([]), "w", self.T).unknown)
        self.assertTrue(cohabitation(self._idx([rec]), "w", self.T).unknown)
        rec["attributes"]["relation_to_householder"] = "child"
        self.assertFalse(cohabitation(self._idx([rec]), "w", self.T).unknown)


class TestAttributionSlotClaimants(unittest.TestCase):
    """選択.扶養の所属 の1か所（所令219②二の同額）：中間表現だけで申告者になりえない人を候補に数えない（2026-11-11 の反証のレビュー）。"""

    def _slots(self, extra_judgments: list[dict[str, Any]]) -> list[Any]:
        from okura_core.registry import YearContext
        from okura_core.rules.personal_deductions.allocation import attribution_slots

        persons = [person("f", "1970-01-01"), person("m", "1972-01-01"), person("c", "2010-01-01")]
        relations = [
            {"id": "pf", "kind": "parentage", "roles": {"parent": "f", "child": "c"}, "when": {"on": "2010-01-01"}, "attributes": {"basis": "birth_in_marriage"}},
            {"id": "pm", "kind": "parentage", "roles": {"parent": "m", "child": "c"}, "when": {"on": "2010-01-01"}, "attributes": {"basis": "birth_mother"}},
        ]  # fmt: skip
        ir = make_ir(persons, [], relations=relations, judgments=extra_judgments)
        return list(attribution_slots(YearContext(ir, R8, ("f", "m", "c"), {})))

    def test_two_parents_need_the_slot(self) -> None:
        self.assertEqual([s.key for s in self._slots([])], ["所属:c"])

    def test_whole_year_non_resident_parent_is_not_a_claimant(self) -> None:
        j = {"id": "j1", "kind": "判断.住所の所在", "subject": {"person": "m"}, "when": {"from_on": "2020-01-01"}, "value": "foreign",
             "judged_by": "f", "judged_at": "2026-01-01T00:00:00+09:00"}  # fmt: skip
        self.assertEqual(self._slots([j]), [])


class TestImplResearch3Additions(unittest.TestCase):
    """2026-11-11 に対象外をやめた箇所の境目（PD-01・08・10・11・12・15・18、所令219① ただし書、年の途中の住所の変更）。"""

    def test_age_at_death_on_the_day_before_the_birthday(self) -> None:
        # 死亡の時の年齢はその日の終了時に加わる1歳を含めない（impl-research3 H6、kojo-misc §4）
        facts = {"所得税_生年月日": _date("1956-07-01")}
        self.assertEqual(int(_one(R8, "所得税_年齢", {**facts, "所得税_死亡日": _date("2026-06-30")})), 69)
        self.assertEqual(int(_one(R8, "所得税_年齢", {**facts, "所得税_死亡日": _date("2026-07-01")})), 70)

    def test_missing_spouse_periods(self) -> None:
        # 所令11（jinteki §1.6）：三 船舶・航空機の事故は3月以上、四 危難が去った後1年以上、五 3年以上
        from okura_core.rules.personal_deductions.ir_facts import missing_spouse_applies as f

        t = _dt.date(2026, 12, 31)
        vessel = {"circumstance": "vessel_or_aircraft_accident"}
        nov30 = _dt.date(2026, 11, 30)
        self.assertEqual(f({**vessel, "since_on": "2026-08-30"}, nov30, True), (True, ""))  # 応当する日の終了で満了
        self.assertEqual(f({**vessel, "since_on": "2026-08-30"}, nov30, False), (False, ""))  # 死亡の時（その日の途中）は満了していない
        self.assertEqual(f({**vessel, "since_on": "2026-09-01"}, nov30, True), (False, ""))
        self.assertEqual(f({"circumstance": "peril", "since_on": "2025-06-01", "peril_ended_on": "2025-12-31"}, t, True), (True, ""))
        self.assertIsNone(f({"circumstance": "peril", "since_on": "2025-06-01"}, t, True)[0])  # 危難が去った日がない
        self.assertEqual(f({"circumstance": "other", "since_on": "2024-01-01"}, t, True), (False, ""))
        self.assertEqual(f({"circumstance": "other", "since_on": "2023-12-31"}, t, True), (True, ""))  # 第5号
        self.assertIsNone(f({"since_on": "2026-01-01"}, t, True)[0])  # 事由がなく3月以上3年未満

    def test_special_disability_by_class_and_severity(self) -> None:
        from okura_core.rules.personal_deductions.ir_facts import application_special, war_special

        def rec(**a: Any) -> dict[str, Any]:
            return {"attributes": a}

        self.assertTrue(war_special(rec(war_injury_class="item_3")))  # 所令10②四：第三項症まで
        self.assertFalse(war_special(rec(war_injury_class="item_4")))
        self.assertIsNone(war_special(rec()))
        self.assertTrue(application_special(rec(grade=2), 2))
        self.assertFalse(application_special(rec(grade=3), 2))
        self.assertIsNone(application_special(rec(), 2))
        base = {"所得税_生年月日": _date("1950-03-03")}
        self.assertTrue(_one(R8, "所得税_特別障害者に当たるか", {**base, "所得税_戦傷病者手帳に特別項症から第三項症までと記載されているか": True}))
        muni = {"所得税_市町村長等の特別障害者に準ずる認定を受けているか": True}
        self.assertTrue(_one(R8, "所得税_特別障害者に当たるか", {**base, **muni}))
        self.assertFalse(_one(R8, "所得税_特別障害者に当たるか", {"所得税_生年月日": _date("1962-03-03"), **muni}))  # 65歳未満

    def test_vocational_school_course(self) -> None:
        # 所法2①三十二ロ・ハ、所令11の3①、課程の要件は証明書の有無（zeigaku §6.1〜6.3、zeigaku-calc-model H3）
        from okura_core.rules.personal_deductions.ir_facts import course_student

        def rec(school: str, **a: Any) -> dict[str, Any]:
            return {"attributes": {"school_type": school, **a}}

        self.assertEqual(course_student(rec("specialized_training_college", establisher_type="school_corporation", course_certificate=True)), (True, ""))
        self.assertEqual(course_student(rec("specialized_training_college", establisher_type="school_corporation", course_certificate=False)), (False, ""))
        self.assertIsNone(course_student(rec("miscellaneous_school", establisher_type="other_corporation", course_certificate=True))[0])
        self.assertEqual(course_student(rec("miscellaneous_school", establisher_type="other_corporation", establisher_certificate=True, course_certificate=True)), (True, ""))
        self.assertEqual(course_student(rec("accredited_vocational_training", course_certificate=True)), (True, ""))
        self.assertTrue(_one(R8, "所得税_学生に当たるか", {"所得税_政令で定める課程を履修する専修学校等の学生等か": True}))

    def test_estimate_for_a_filer_who_died(self) -> None:
        # 所基通85−1(2)：死亡した申告者の親族の合計所得金額は見積額（kojo-misc §4）
        dep = {"所得税_合計所得金額": 1_000_000, "所得税_死亡した申告者のための見積りを使うか": True, "所得税_死亡した申告者のための合計所得金額の見積額": 620_000}
        self.assertTrue(_one(R8, "所得税_扶養親族の合計所得金額要件", dep))
        self.assertFalse(_one(R8, "所得税_扶養親族の合計所得金額要件", {**dep, "所得税_死亡した申告者のための合計所得金額の見積額": 620_001}))
        self.assertFalse(_one(R8, "所得税_扶養親族の合計所得金額要件", {**dep, "所得税_死亡した申告者のための見積りを使うか": False}))

    def test_has_fixpoints(self) -> None:
        # 措法41の3の11①：親族自身の第1項の控除で上限以下になるか（PD-15）。互いに依存すると最小・最大の不動点が分かれる
        from okura_core.rules.personal_deductions.allocation import _HasCandidate, adjustment_first_item, has_fixpoints

        self.assertEqual(adjustment_first_item(8_500_000, 8_500_000, 10_000_000, 1, 10), 0)
        self.assertEqual(adjustment_first_item(8_500_001, 8_500_000, 10_000_000, 1, 10), 1)  # 1円未満切上げ
        one_way = {"c": [_HasCandidate("d", 620_000, 700_000, 150_000)], "d": [_HasCandidate("e", 620_000, 0, 0)]}
        self.assertEqual(has_fixpoints(one_way), ({"c": True, "d": True}, {"c": True, "d": True}))
        mutual = {"c": [_HasCandidate("d", 620_000, 700_000, 150_000)], "d": [_HasCandidate("c", 620_000, 700_000, 150_000)]}
        self.assertEqual(has_fixpoints(mutual), ({"c": False, "d": False}, {"c": True, "d": True}))

    def test_later_document_withdraws_a_listing(self) -> None:
        # 所令219① ただし書・所基通85−2（misc §3.2・§3.3）
        from okura_core.rules.personal_deductions.allocation import _withdrawn

        def doc(on: str, people: list[str]) -> dict[str, Any]:
            return {"roles": {"filer": "f"}, "when": {"on": on},
                    "attributes": {"document_type": "employee_dependents_declaration", "entries": [{"person": p, "section": "dependent_relative"} for p in people]}}  # fmt: skip

        docs = [doc("2026-01-05", ["c"]), doc("2026-06-01", [])]
        self.assertTrue(_withdrawn(docs, "f", "c", "dep", _dt.date(2026, 1, 5)))
        self.assertFalse(_withdrawn(docs[:1], "f", "c", "dep", _dt.date(2026, 1, 5)))

    def test_spouse_outside_the_group(self) -> None:
        # 所令220①：相手が別の人を配偶者としたとき（PD-18）。グループの代わりに段の入力で同一生計配偶者を判定する
        facts = {
            "所得税_合計所得金額": 3_000_000,
            "所得税_配偶者と生計を一にするか": True,
            "所得税_法律婚のグループ外の配偶者がいるか": True,
            "所得税_グループ外の配偶者の合計所得金額": 580_000,
            "所得税_グループ外の配偶者の年齢": 50,
        }
        self.assertTrue(_one(R7, "所得税_同一生計配偶者に当たるか", facts, couples=[]))
        self.assertFalse(_one(R7, "所得税_同一生計配偶者に当たるか", {**facts, "所得税_グループ外の配偶者の合計所得金額": 580_001}, couples=[]))

    def test_consistent_address_changes(self) -> None:
        from okura_core.rules.personal_deductions.inputs import _consistent

        t = _dt.date(2026, 12, 31)
        entry = [_address("j1", "a", "foreign", "2025-01-01", "2026-03-31"), _address("j2", "a", "domestic", "2026-04-01", "2026-12-31")]
        self.assertTrue(_consistent(entry, R8, t))
        self.assertFalse(_consistent([*entry, _address("j3", "a", "foreign", "2026-12-01", "2026-12-31")], R8, t))


class TestEmigrationYear(unittest.TestCase):
    """PD-05（2026-11-12）：年の中途の出国（所法2①四十二）は出国の時で判定し（所法85①③）、国外転出時課税の判断で確かめる（D22 S11）。"""

    def _ctx(self, judgments: list[dict[str, Any]], facts: list[dict[str, Any]] = ()) -> Any:
        from okura_core.registry import YearContext

        ir = {"schema_version": "0", "persons": [{"id": "p", "birth_on": "1980-01-01"}], "relations": [], "residences": [], "insurance_memberships": [],
              "facts": [_stay("st", "p", "2026-07-01"), *facts], "assets": [], "filed_documents": [], "judgments": judgments, "choices": []}  # fmt: skip
        return YearContext(ir, 2026, ("p",))

    def _addr(self) -> list[dict[str, Any]]:
        return [_address("a1", "p", "domestic", "2026-01-01", "2026-06-30"), _address("a2", "p", "foreign", "2026-07-01", "2027-12-31")]

    def test_departure_and_cut(self) -> None:
        from okura_core.rules.personal_deductions.ir_facts import cut_date, departure_day

        js = self._addr()
        self.assertEqual(departure_day(2026, js, [], "p"), _date("2026-07-01"))
        notice = {"roles": {"taxpayer": "p"}, "attributes": {"action": "appointment"}, "when": {"on": "2026-06-20"}}
        self.assertIsNone(departure_day(2026, js, [notice], "p"))  # 納税管理人の届出の後は「出国」でない
        self.assertEqual(cut_date(None, _date("2026-07-01")), _date("2026-06-30"))
        self.assertEqual(cut_date(_date("2026-05-01"), _date("2026-07-01")), _date("2026-05-01"))

    def test_emigrant_is_resident_at_departure_and_exit_tax_judgment(self) -> None:
        from okura_core.registry import ModuleInputs
        from okura_core.result import Means
        from okura_core.rules.personal_deductions.inputs import V_ADDRESS, _Source, _write_residence

        def run(exit_value: bool | None) -> Any:
            js = self._addr()
            if exit_value is not None:
                js.append({"id": "x", "kind": "判断.国外転出時課税の対象", "judged_by": {"person": "p"}, "judged_at": "2027-01-10T09:00:00+09:00",
                           "subject": {"person": "p"}, "when": {"tax_year": 2026}, "value": exit_value})  # fmt: skip
            ctx = self._ctx(js)
            src = _Source(ctx)
            out = ModuleInputs()
            self.assertEqual(src.t("p"), _date("2026-06-30"))
            _write_residence(src, "p", src.t("p"), out)
            return out

        out = run(False)
        self.assertEqual((out.values[(V_ADDRESS, "p")].value, out.values[(V_ADDRESS, "p")].missing, out.exclusions), (True, (), []))
        self.assertEqual([m.means for m in run(None).values[(V_ADDRESS, "p")].missing], [Means.JUDGMENT])
        self.assertEqual(len(run(True).exclusions), 1)  # 国外転出時課税の対象：範囲外


class TestBoundaryDeclarations(unittest.TestCase):
    """境目の説明の宣言（D19・SCOPE §2-6。2026-11-12）：主要な判定の宣言の不足がなく、宣言が正しい比べる量と基準を指す。"""

    def test_declarations_point_to_the_criteria(self) -> None:
        from okura_core.boundaries import declarations, undeclared
        from okura_core.evaluate import REGISTRY

        got = {b.judgment: (b.compared, b.criterion, b.comparison) for b in declarations(REGISTRY) if b.module == "personal_deductions"}
        判定に使う = "所得税.扶養等の判定に使う合計所得金額"
        expected = {
            "所得税.扶養親族の合計所得金額要件": (判定に使う, "所得税.扶養親族.合計所得金額の上限", None),
            "所得税.特定親族の合計所得金額要件": (判定に使う, "所得税.特定親族.合計所得金額の上限", None),
            "所得税.特定親族の合計所得金額が特定親族特別控除の段階の上限以下か": (判定に使う, "所得税.特定親族特別控除の段階の上限", "以下"),
            "所得税.勤労学生の合計所得金額要件": ("所得税.合計所得金額", "所得税.勤労学生.合計所得金額の上限", None),
            "所得税.勤労学生の給与所得等以外の所得要件": ("所得税.勤労学生の給与所得等以外の所得の金額", "所得税.勤労学生.給与所得等以外の所得の上限", None),
            "所得税.同一生計配偶者の合計所得金額要件": ("所得税.配偶者の合計所得金額", "所得税.同一生計配偶者.合計所得金額の上限", None),
            "所得税.控除対象配偶者の本人の合計所得金額要件": ("所得税.合計所得金額", "所得税.控除対象配偶者.居住者の合計所得金額の上限", None),
            "所得税.配偶者の合計所得金額が配偶者特別控除の段階の上限以下か": ("所得税.配偶者の合計所得金額", "所得税.配偶者特別控除の配偶者の段階の上限", "以下"),
            "所得税.合計所得金額が配偶者控除等の本人の段階の上限以下か": ("所得税.合計所得金額", "所得税.配偶者控除等の本人の段階の上限", "以下"),
            "所得税.合計所得金額が基礎控除の段階の上限以下か": ("所得税.合計所得金額", "所得税.基礎控除の段階の上限", "以下"),
        }
        for judgment, decl in expected.items():
            with self.subTest(judgment=judgment):
                self.assertEqual(got.get(judgment), decl)
        missing = undeclared(REGISTRY)
        for label in ("扶養", "特定親族", "勤労学生", "配偶者"):
            self.assertNotIn(label, missing)

    def test_tier_uppers(self) -> None:
        # 特定親族特別控除（所法84の2①、R1-laws §3）：第1号 85万円以下、第2号は「84万1円を超える部分×2」を「10万円の整数倍−8万円」に切り下げるので
        # 5万円ごとに額が変わる（85万超90万以下・…・110万超115万以下）、第3号 120万円以下、第4号 123万円以下（特定親族の上限）
        var = "所得税_特定親族特別控除の段階の上限"
        for income, upper in ((850_000, 850_000), (850_001, 900_000), (900_001, 950_000), (1_150_000, 1_150_000), (1_150_001, 1_200_000), (1_230_001, 1_230_000)):
            with self.subTest(var=var, income=income):
                self.assertEqual(_one(R7, var, {"所得税_扶養等の判定に使う合計所得金額": income}), upper)
        # 配偶者特別控除の第1号（所法83の2①一、spouse §1.3）：イ 95万円以下、ロは「93万1円を超える部分」を「5万円の整数倍−3万円」に切り下げる（5万円ごと）、ハ 133万円以下
        var = "所得税_配偶者特別控除の配偶者の段階の上限"
        for income, upper in ((950_000, 950_000), (950_001, 1_000_000), (1_300_000, 1_300_000), (1_300_001, 1_330_000), (2_000_000, 1_330_000)):
            with self.subTest(var=var, income=income):
                self.assertEqual(_one(R7, var, {"所得税_配偶者の合計所得金額": income}), upper)
        # 基礎控除（所法86①・措法41の16の2①、R1-laws §2 の表）：令和7年分は132万円・336万円…、令和8年分は489万円・655万円…
        var = "所得税_基礎控除の段階の上限"
        self.assertEqual(_one(R7, var, {"所得税_合計所得金額": 1_320_001}), 3_360_000)
        self.assertEqual(_one(R8, var, {"所得税_合計所得金額": 1_320_001}), 4_890_000)
        self.assertEqual(_one(R8, var, {"所得税_合計所得金額": 30_000_000}), 25_000_000)
