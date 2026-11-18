"""income_kinds の式を OpenFisca で単独で確かめる（まだない上流の概念は、仮置きの変数に値を与える）。

出典は各テストのコメントの docs の節。テストのデータは架空。令和7年分（2025）・令和8年分（2026）の両方で確かめる。
"""

from __future__ import annotations

import unittest
from typing import Any

from openfisca_core.simulation_builder import SimulationBuilder

from ...support import system

YEARS = (2025, 2026)


def calc(variable: str, year: int, person: dict[str, Any]) -> int:
    """1人の状況で変数を計算する（person：変数名 → 値。全部の年分に同じ値を入れる）。"""
    data = {name: {str(year): value} for name, value in person.items()}
    sim = SimulationBuilder().build_from_entities(system(), {"人物一覧": {"p": data}})
    return sim.calculate(variable, str(year)).tolist()[0]


class TestPension(unittest.TestCase):
    """公的年金等控除額・雑所得（nenkin §2.1〜§2.3）。年齢と雑所得以外の合計所得金額は仮置きの変数に値を与える。"""

    def base(self, income: int, age: int, other: int = 0, rounding: str = "floor") -> dict[str, Any]:
        return {
            "所得税_公的年金等の収入金額": income,
            "所得税_年齢": age,
            "所得税_公的年金等に係る雑所得以外の合計所得金額": other,
            "所得税_所得の金額の端数の候補": rounding,
        }

    def test_ta_example(self) -> None:
        # nenkin §2.3 の計算例（TA No.1600）：65歳以上、雑所得以外 500万円、収入 350万円 → 雑所得 2,350,000 円
        for y in YEARS:
            p = self.base(3_500_000, 70, 5_000_000)
            self.assertEqual(calc("所得税_公的年金等に係る雑所得の金額", y, p), 2_350_000)
            self.assertEqual(calc("所得税_公的年金等控除額", y, p), 1_150_000)

    def test_boundaries(self) -> None:
        # nenkin §2.3：65歳未満 60万円以下は0、65歳以上 110万円以下は0。雑所得以外 1,000万円の境目（§2.1 第1号・第2号）
        for y in YEARS:
            self.assertEqual(calc("所得税_公的年金等に係る雑所得の金額", y, self.base(600_000, 64)), 0)
            self.assertEqual(calc("所得税_公的年金等に係る雑所得の金額", y, self.base(600_001, 64)), 1)
            self.assertEqual(calc("所得税_公的年金等に係る雑所得の金額", y, self.base(1_100_000, 65)), 0)
            self.assertEqual(calc("所得税_公的年金等に係る雑所得の金額", y, self.base(1_100_001, 65)), 1)
            self.assertEqual(calc("所得税_公的年金等に係る雑所得の金額", y, self.base(2_000_000, 40, 10_000_000)), 1_225_000)
            self.assertEqual(calc("所得税_公的年金等に係る雑所得の金額", y, self.base(2_000_000, 40, 10_000_001)), 1_325_000)

    def test_income_is_floored(self) -> None:
        # 1,300,001×0.75−275,000＝700,000.75：手引き 3-2_07「1円未満の端数は切り捨て」（hasu-tebiki §3。令和8年分の手引きは未公表で令和7年分を使う）。候補に依らない
        y = 2026
        self.assertEqual(calc("所得税_公的年金等に係る雑所得の金額", y, self.base(1_300_001, 40, rounding="ceil")), 700_000)
        self.assertEqual(calc("所得税_公的年金等控除額", y, self.base(1_300_001, 40, rounding="ceil")), 600_001)

    def test_no_pension_gives_zero_deduction(self) -> None:
        for y in YEARS:
            self.assertEqual(calc("所得税_公的年金等控除額", y, {"所得税_公的年金等の収入金額": 0}), 0)


class TestRetirement(unittest.TestCase):
    """退職所得（所法30②③⑥：taishoku §2.1、例は §4.2 の TA2732）。"""

    def base(self, income: int, years: int, kind: str = "一般", disabled: bool = False, rounding: str = "floor") -> dict[str, Any]:
        return {
            "所得税_退職手当等の収入金額": income,
            "所得税_退職所得の勤続年数": years,
            "所得税_退職手当等の区分": kind,
            "所得税_障害者になったことに直接基因する退職か": disabled,
            "所得税_所得の金額の端数の候補": rounding,
        }

    def test_examples(self) -> None:
        for y in YEARS:
            self.assertEqual(calc("所得税_退職所得の金額", y, self.base(8_000_000, 11)), 1_800_000)  # TA2732 例1
            self.assertEqual(calc("所得税_退職所得の金額", y, self.base(23_000_000, 30)), 4_000_000)  # TA2732 例2

    def test_disability_adds_one_million(self) -> None:
        # 所法30⑥三：800万円（20年）に100万円を加算 → (2,000万−900万)÷2
        self.assertEqual(calc("所得税_退職所得の金額", 2026, self.base(20_000_000, 20, disabled=True)), 5_500_000)

    def test_short_and_officer(self) -> None:
        self.assertEqual(calc("所得税_退職所得の金額", 2026, self.base(5_000_001, 5, kind="短期")), 1_500_001)
        self.assertEqual(calc("所得税_退職所得の金額", 2026, self.base(5_000_000, 5, kind="特定役員")), 3_000_000)

    def test_odd_remainder_uses_candidate(self) -> None:
        # 残額の2分の1の端数：所法30 に定めがない
        self.assertEqual(calc("所得税_退職所得の金額", 2026, self.base(8_000_001, 11, rounding="floor")), 1_800_000)
        self.assertEqual(calc("所得税_退職所得の金額", 2026, self.base(8_000_001, 11, rounding="ceil")), 1_800_001)


class TestBusiness(unittest.TestCase):
    """事業所得・業務に係る雑所得（jigyo §1・§2、aoiro §3.1）。減価償却費などの未実装の概念は既定の0。"""

    def test_white_business(self) -> None:
        p = {"所得税_事業所得の総収入金額": 3_000_000, "所得税_事業所得の必要経費": 1_000_000}
        for y in YEARS:
            self.assertEqual(calc("所得税_事業所得の金額", y, p), 2_000_000)

    def test_loss_is_negative(self) -> None:
        p = {"所得税_事業所得の総収入金額": 500_000, "所得税_事業所得の必要経費": 800_000}
        self.assertEqual(calc("所得税_事業所得の金額", 2026, p), -300_000)

    def test_home_worker_by_year(self) -> None:
        # jigyo §2.1：令和7年分 65万円、令和8年分 69万円
        p = {"所得税_事業所得の総収入金額": 1_000_000, "所得税_事業所得の必要経費": 100_000, "所得税_家内労働者等か": True}
        self.assertEqual(calc("所得税_事業所得の金額", 2025, p), 350_000)
        self.assertEqual(calc("所得税_事業所得の金額", 2026, p), 310_000)

    def test_home_worker_limited_by_revenue(self) -> None:
        p = {"所得税_事業所得の総収入金額": 500_000, "所得税_事業所得の必要経費": 100_000, "所得税_家内労働者等か": True}
        self.assertEqual(calc("所得税_事業所得の金額", 2026, p), 0)

    def test_home_worker_misc(self) -> None:
        p = {"所得税_業務に係る雑所得の総収入金額": 1_000_000, "所得税_業務に係る雑所得の必要経費": 50_000, "所得税_家内労働者等か": True}
        self.assertEqual(calc("所得税_業務に係る雑所得の金額", 2025, p), 350_000)
        self.assertEqual(calc("所得税_業務に係る雑所得の金額", 2026, p), 310_000)

    def test_misc_without_home_worker(self) -> None:
        p = {"所得税_業務に係る雑所得の総収入金額": 300_000, "所得税_業務に係る雑所得の必要経費": 500_000}
        self.assertEqual(calc("所得税_業務に係る雑所得の金額", 2026, p), -200_000)

    def test_blue_deduction(self) -> None:
        # aoiro §3.1：65万円（期限内 e-Tax・正規の簿記）、55万円（期限内 書面）、10万円（それ以外）
        base = {"所得税_事業所得の総収入金額": 5_000_000, "所得税_事業所得の必要経費": 1_000_000, "所得税_青色申告の承認の状態": "承認"}
        for filing, book, want in (
            ("期限内の電子申告", True, 650_000),
            ("期限内の書面の申告", True, 550_000),
            ("期限内の申告でない", True, 100_000),
            ("期限内の電子申告", False, 100_000),
        ):
            p = {**base, "所得税_正規の簿記の要件": book, "所得税_青色申告特別控除の申告の要件": filing}
            for y in YEARS:
                with self.subTest(filing=filing, book=book, y=y):
                    self.assertEqual(calc("所得税_青色申告特別控除額", y, p), want)
                    self.assertEqual(calc("所得税_事業所得の金額", y, p), 4_000_000 - want)

    def test_blue_limit_is_profit(self) -> None:
        p = {
            "所得税_事業所得の総収入金額": 1_300_000,
            "所得税_事業所得の必要経費": 1_000_000,
            "所得税_青色申告の承認の状態": "承認",
            "所得税_正規の簿記の要件": True,
            "所得税_青色申告特別控除の申告の要件": "期限内の電子申告",
        }
        self.assertEqual(calc("所得税_事業所得の金額", 2026, p), 0)

    def test_not_approved_has_no_deduction(self) -> None:
        p = {"所得税_事業所得の総収入金額": 3_000_000, "所得税_事業所得の必要経費": 0, "所得税_正規の簿記の要件": True, "所得税_青色申告特別控除の申告の要件": "期限内の電子申告"}
        self.assertEqual(calc("所得税_青色申告特別控除額", 2026, p), 0)
        self.assertEqual(calc("所得税_事業所得の金額", 2026, p), 3_000_000)

    def test_depreciation_and_family_are_subtracted(self) -> None:
        p = {"所得税_事業所得の総収入金額": 3_000_000, "所得税_事業所得の必要経費": 500_000, "所得税_事業所得の減価償却費": 200_000, "所得税_事業所得の事業専従者控除額": 500_000, "所得税_事業所得の青色事業専従者給与の額": 0}
        self.assertEqual(calc("所得税_事業所得の金額", 2026, p), 1_800_000)

    def test_home_worker_with_salary(self) -> None:
        # 措法27（jigyo §2.1）：給与所得がある家内労働者等の特例の額は 69万円 − 給与所得控除額（令和8年分）
        p = {"所得税_事業所得の総収入金額": 1_000_000, "所得税_事業所得の必要経費": 100_000, "所得税_家内労働者等か": True, "所得税_給与等の収入金額": 1_000_000, "所得税_給与所得控除額": 650_000}
        self.assertEqual(calc("所得税_事業所得の金額", 2026, p), 1_000_000 - max(100_000, 40_000))
        p["所得税_給与所得控除額"] = 100_000
        self.assertEqual(calc("所得税_事業所得の金額", 2026, p), 1_000_000 - 590_000)


class TestMiscSum(unittest.TestCase):
    def test_sum_of_three(self) -> None:
        # 所法35②：公的年金等に係るものとそれ以外の合計（nenkin §1.1）。業務の損失は内訳の中で合計に入る
        p = {
            "所得税_公的年金等の収入金額": 1_000_000,
            "所得税_年齢": 40,
            "所得税_公的年金等に係る雑所得以外の合計所得金額": 0,
            "所得税_所得の金額の端数の候補": "floor",
            "所得税_業務に係る雑所得の総収入金額": 100_000,
            "所得税_業務に係る雑所得の必要経費": 300_000,
            "所得税_その他の雑所得の金額": 50_000,
        }
        self.assertEqual(calc("所得税_雑所得の金額", 2026, p), 400_000 - 200_000 + 50_000)


class TestRental(unittest.TestCase):
    """不動産所得（fudosan §2.1・§3.4・§4.3）。青色申告特別控除は不動産所得から先に控除する。"""

    def test_blue_deduction_goes_to_real_estate_first(self) -> None:
        # 措法25の2②⑤：不動産所得の金額、事業所得の金額の順
        p = {
            "所得税_不動産所得の総収入金額": 1_000_000,
            "所得税_事業所得の総収入金額": 1_000_000,
            "所得税_青色申告の承認の状態": "承認",
            "所得税_正規の簿記の要件": True,
            "所得税_青色申告特別控除の申告の要件": "期限内の電子申告",
        }
        self.assertEqual(calc("所得税_青色申告特別控除額", 2026, p), 650_000)
        self.assertEqual(calc("所得税_不動産所得の金額", 2026, p), 350_000)
        self.assertEqual(calc("所得税_事業所得の金額", 2026, p), 1_000_000)
        p["所得税_不動産所得の総収入金額"] = 300_000
        self.assertEqual(calc("所得税_不動産所得の金額", 2026, p), 0)
        self.assertEqual(calc("所得税_事業所得の金額", 2026, p), 1_000_000 - 350_000)

    def test_loss_limited_by_land_interest(self) -> None:
        # fudosan I1：損失 80万円・土地の負債の利子 50万円 → 通算できない 50万円、第一表③ △30万円
        p = {"所得税_不動産所得の総収入金額": 1_200_000, "所得税_不動産所得の必要経費": 2_000_000, "所得税_土地等を取得するために要した負債の利子の額": 500_000}
        self.assertEqual(calc("所得税_不動産所得の金額", 2025, p), -300_000)
        self.assertEqual(calc("所得税_不動産所得の損失のうち生じなかったものとみなす金額", 2025, p), 500_000)
        p["所得税_土地等を取得するために要した負債の利子の額"] = 900_000
        self.assertEqual(calc("所得税_不動産所得の金額", 2025, p), 0)
        self.assertEqual(calc("所得税_不動産所得の損失のうち生じなかったものとみなす金額", 2025, p), 800_000)

    def test_all_villa_loss_does_not_offset(self) -> None:
        # 所法69②・TA1391：別荘等の貸付けの損失
        p = {"所得税_不動産所得の総収入金額": 100_000, "所得税_不動産所得の必要経費": 600_000, "所得税_不動産所得の貸付けがすべて別荘等か": True}
        self.assertEqual(calc("所得税_不動産所得の金額", 2026, p), 0)


class TestWindfall(unittest.TestCase):
    def test_amount(self) -> None:
        # 所法34②③（jigyo §6）
        p = {"所得税_一時所得の総収入金額": 1_000_000, "所得税_一時所得の支出した金額": 100_000}
        for y in YEARS:
            self.assertEqual(calc("所得税_一時所得の金額", y, p), 400_000)


if __name__ == "__main__":
    unittest.main()
