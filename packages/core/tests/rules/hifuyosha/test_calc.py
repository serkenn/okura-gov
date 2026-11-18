"""hifuyosha の純粋関数（calc.py）のユニットテスト。境目と読みの分かれやすい箇所だけ。出典は各テストのコメントの docs の節。データは架空。"""

from __future__ import annotations

import datetime as dt
import unittest
from fractions import Fraction

from okura_core.injection_points import POINTS
from okura_core.rules.hifuyosha import calc as c

D = dt.date
LIMITS = c.AgeLimits(60, 19, 23)
RULES = c.SupportRules(Fraction(1, 3), 100_000, 50_000, Fraction(1, 2), 1_000, 650_000)


class TestAge(unittest.TestCase):
    def test_birthday_eve(self) -> None:
        # 誕生日の前日に加算、1月1日生まれは12月31日に加算（impl-prep_kenpo §5.5、R1 §3）。
        # 令和7年中に19歳以上23歳未満になるのは平成15年1月2日〜平成19年1月1日生まれ（KOURITU-19-23：kyosai-law-and-criteria §3.2）
        dec31 = D(2025, 12, 31)
        self.assertEqual(c.age_on(D(2007, 1, 1), dec31), 19)
        self.assertEqual(c.age_on(D(2007, 1, 2), dec31), 18)
        self.assertEqual(c.age_on(D(2003, 1, 2), dec31), 22)
        self.assertEqual(c.age_on(D(2003, 1, 1), dec31), 23)
        self.assertEqual(c.age_on(D(2004, 2, 29), D(2025, 2, 27)), 20)  # 応当日のない年は2月28日に満了
        self.assertEqual(c.age_on(D(2004, 2, 29), D(2025, 2, 28)), 21)


class TestBaseCategory(unittest.TestCase):
    def test_boundaries(self) -> None:
        # 19歳以上23歳未満（12月31日現在・配偶者を除く）、60歳以上・障害者（SH §1.1・§1.2）
        self.assertEqual(c.base_category(18, 18, False, False, LIMITS), c.BASE_DEFAULT)
        self.assertEqual(c.base_category(18, 19, False, False, LIMITS), c.BASE_YOUNG)
        self.assertEqual(c.base_category(22, 22, False, False, LIMITS), c.BASE_YOUNG)
        self.assertEqual(c.base_category(22, 23, False, False, LIMITS), c.BASE_DEFAULT)
        self.assertEqual(c.base_category(20, 20, False, True, LIMITS), c.BASE_DEFAULT)  # 配偶者は除く
        self.assertEqual(c.base_category(20, 20, True, False, LIMITS), c.BASE_SENIOR)  # 障害者は180万円（読み：KYB §2.3）
        self.assertEqual(c.base_category(59, 60, False, False, LIMITS), c.BASE_DEFAULT)  # 60歳は判定日の年齢
        self.assertEqual(c.base_category(60, 60, False, True, LIMITS), c.BASE_SENIOR)


class TestLivelihood(unittest.TestCase):
    def test_half_of_insured(self) -> None:
        # 同一の世帯：被保険者の年間収入の2分の1未満（SH §1.1）
        half = Fraction(1, 2)
        self.assertTrue(c.same_household_ok(1_199_999, 2_400_000, 1_300_000, False, half))
        self.assertFalse(c.same_household_ok(1_200_000, 2_400_000, 1_300_000, False, half))
        # ただし書：基準額未満で被保険者の年間収入を上回らず、中心的役割なら可
        self.assertTrue(c.same_household_ok(1_200_000, 2_400_000, 1_300_000, True, half))
        self.assertFalse(c.same_household_ok(1_200_000, 1_199_999, 1_300_000, True, half))

    def test_support_types(self) -> None:
        # 別居の仕送りの基準の型（SA2 §2）
        self.assertTrue(c.support_ok(c.SUPPORT_S52, 999_999, 1_000_000, 0, 0, RULES))
        self.assertFalse(c.support_ok(c.SUPPORT_S52, 1_000_000, 1_000_000, 0, 0, RULES))
        self.assertTrue(c.support_ok(c.SUPPORT_THIRD, 1_000_000, 500_000, 0, 0, RULES))  # 50万 ≥ 150万×1/3
        self.assertFalse(c.support_ok(c.SUPPORT_THIRD, 1_000_001, 500_000, 0, 0, RULES))
        # MIYAGI 基準-10 の例：別居の母 給与月11万・送金月5.5万 → 可（被保険者の年間収入は十分に大きい）
        self.assertTrue(c.support_ok(c.SUPPORT_MONTHLY, 1_320_000, 660_000, 0, 6_000_000, RULES))
        self.assertFalse(c.support_ok(c.SUPPORT_MONTHLY, 1_320_000, 648_000, 0, 6_000_000, RULES))
        self.assertFalse(c.support_ok(c.SUPPORT_MONTHLY, 1_320_000, 660_000, 0, 1_979_999, RULES))  # 合計が組合員の収入を上回る
        self.assertTrue(c.support_ok(c.SUPPORT_AT_LEAST_AND_MIN, 600_000, 650_000, 0, 0, RULES))
        self.assertFalse(c.support_ok(c.SUPPORT_AT_LEAST_AND_MIN, 600_000, 649_999, 0, 0, RULES))

    def test_uninjected_candidates_split_or_agree(self) -> None:
        # 未注入なら調査で集めた型の全部で評価する（D21 R6）。型で結論が分かれる例と、分かれない例
        kinds = {cand.data["型"] for cand in POINTS["健保.別居の仕送りの基準"].candidates}
        split = {c.support_ok(k, 1_000_000, 600_000, 0, 6_000_000, RULES) for k in kinds}
        agree = {c.support_ok(k, 0, 1_200_000, 0, 6_000_000, RULES) for k in kinds}
        self.assertEqual(split, {True, False})
        self.assertEqual(agree, {True})


class TestKyodo(unittest.TestCase):
    def test_spouses(self) -> None:
        # 夫婦共同扶養（PSK §3）：多い方、差が1割以内なら届出、共済の扶養手当、国保の配偶者
        tenth = Fraction(1, 10)
        self.assertEqual(c.kyodo_main("a", "b", 5_000_000, 4_000_000, True, tenth), "a")
        self.assertEqual(c.kyodo_main("a", "b", 5_000_000, 4_500_000, True, tenth), c.KYODO_NEEDS_NOTICE)
        self.assertEqual(c.kyodo_main("a", "b", 5_000_000, 4_499_999, True, tenth), "a")
        self.assertEqual(c.kyodo_main("a", "b", 4_000_000, 5_000_000, True, tenth, allowance_holder="a"), "a")
        self.assertEqual(c.kyodo_main("a", "b", 4_000_000, 4_100_000, False, tenth), "b")


class TestContract(unittest.TestCase):
    ON = D(2026, 4, 1)

    def run_(self, amounts: dict, attrs: dict, end: dt.date | None = None, rule: str | None = None) -> c.ContractIncome:
        base = {"salary_income_only_statement": True, **attrs}
        return c.contract_income(amounts, base, contract_end=end, on=self.ON, commuting_rule=rule, min_years=1)

    def test_annual(self) -> None:
        # 時給×所定労働時間×52週（換算式は出典にない：法令の読み）＋諸手当＋賞与（SH §1.3、PSK §1.2）
        r = self.run_({"hourly_wage": 1_200, "monthly_commuting_allowance": 5_000, "bonus": 50_000}, {"scheduled_minutes_per_week": 1_200})
        self.assertTrue(r.usable)
        self.assertEqual(r.amount, Fraction(1_200 * 20 * 52 + 5_000 * 12 + 50_000))

    def test_unusable(self) -> None:
        self.assertFalse(self.run_({"hourly_wage": 1_200}, {"scheduled_minutes_per_week": 600, "shift_based": True}).usable)
        self.assertFalse(self.run_({"hourly_wage": 1_200}, {"scheduled_minutes_per_week": 600}, end=D(2027, 3, 30)).usable)
        self.assertTrue(self.run_({"hourly_wage": 1_200}, {"scheduled_minutes_per_week": 600}, end=D(2027, 3, 31)).usable)
        stated = {"scheduled_minutes_per_week": 600, "commuting_allowance_stated": True, "commuting_allowance_as_reimbursement": True}
        self.assertFalse(self.run_({"hourly_wage": 1_200}, stated).usable)
        self.assertTrue(self.run_({"hourly_wage": 1_200}, stated, rule="実費弁償として記載された手当は含まない").usable)


class TestOthers(unittest.TestCase):
    def test_attestation_consecutive(self) -> None:
        # 事業主の証明は原則として連続2回まで（SH §1.5）
        since = D(2023, 10, 20)
        self.assertTrue(c.attestation_allowed([D(2025, 6, 1), D(2026, 6, 1)], D(2026, 6, 1), 2, since))
        self.assertFalse(c.attestation_allowed([D(2024, 6, 1), D(2025, 6, 1), D(2026, 6, 1)], D(2026, 6, 1), 2, since))
        self.assertTrue(c.attestation_allowed([D(2023, 6, 1), D(2025, 6, 1), D(2026, 6, 1)], D(2026, 6, 1), 2, since))

    def test_window(self) -> None:
        # 3か月連続の各月の額（OITA）と平均（FUKUOKA）：KY §6.4
        months = {(2026, 4): 110_000, (2026, 5): 120_000, (2026, 6): 100_000}
        self.assertEqual(c.window_annual(months, D(2026, 7, 1), {"月数": 3, "比べる値": "各月の額"}, False), 1_200_000)
        self.assertEqual(c.window_annual(months, D(2026, 7, 1), {"月数": 3, "比べる値": "連続する月の平均"}, False), 1_320_000)
        self.assertEqual(c.window_annual(months, D(2026, 7, 1), {"月数": 4, "比べる値": "各月の額"}, False), 0)

    def test_window_exception_fukuoka_and_hiroshima(self) -> None:
        # 推測 I11（仮説 H12）：月額基準 108,334円。7月〜9月の平均 115,000円 → 判定日 2026-10-01 の3か月平均の年額 1,380,000円（基準 130万円以上）
        on = D(2026, 10, 1)
        avg3 = {"月数": 3, "比べる値": "連続する月の平均"}
        recent = {(2026, 7): 115_000, (2026, 8): 115_000, (2026, 9): 115_000}
        self.assertEqual(c.window_annual(recent, on, avg3, False), 1_380_000)
        # FUKUOKA-KIJUN 第3 5(1) ただし書（impl-research4 hifuyosha-insurers §1）：「明らか」なら窓を当てない
        self.assertEqual(c.window_after_exception(recent, on, avg3, False, True), 0)
        self.assertEqual(c.window_after_exception(recent, on, avg3, False, False), 1_380_000)
        # 広島大学支部の申立書（§2）：申立てで3か月平均の窓は当てないが、12か月の実績は当てる（結果的に超えれば取消し）
        low = {**{k: 60_000 for k in c.months_before(D(2026, 7, 1), 9)}, **recent}  # 9か月×60,000＋345,000＝885,000円
        high = {**{k: 110_000 for k in c.months_before(D(2026, 7, 1), 9)}, **recent}  # 9か月×110,000＋345,000＝1,335,000円
        self.assertEqual(c.window_after_exception(low, on, avg3, True, True), 885_000)
        self.assertEqual(c.window_after_exception(high, on, avg3, True, True), 1_335_000)
        self.assertEqual(c.window_after_exception(low, on, avg3, True, False), 1_380_000)

    def test_hiroshima_type_is_a_separate_candidate(self) -> None:
        # H12：広島大学支部の型は取消しの日の定めが FUKUOKA と違うので別の型（impl-research4 hifuyosha-insurers §1・§2）
        from okura_core.rules.hifuyosha import inputs as hi

        cands = {x.label: x.data for x in POINTS["健保.年間収入の見込みの型"].candidates}
        fukuoka = cands["連続3か月の平均・確定申告（FUKUOKA-KIJUN 第3 5）"]
        hiroshima = next(v for k, v in cands.items() if "広島大学支部" in k)
        self.assertEqual(fukuoka["月額の連続超過"]["取消の日"], "超えた最後の月の翌月の初日")  # §1 の表の③「月額基準額以上となった月の翌月初日」
        self.assertEqual(hiroshima["月額の連続超過"]["取消の日"], "超えた最後の月の翌月の初日")  # §2「3ヶ月平均をとった翌月（4ヶ月目）」
        self.assertTrue(hiroshima[hi.F_OBVIOUS])
        labels = [x.label for x in hi._effect_candidates(hi.P_TYPE, hi._type_effect)]
        self.assertEqual(len([lb for lb in labels if "広島大学支部" in lb]), 1)
        self.assertFalse(any("広島大学支部" in lb and "FUKUOKA" in lb for lb in labels))

    def test_expense_treatment(self) -> None:
        table = POINTS["健保.事業収入から差し引ける経費"].candidates[1].data  # 協会けんぽの表
        self.assertEqual(c.expense_treatment("売上原価", table), (c.DEDUCT, None))
        self.assertEqual(c.expense_treatment("減価償却費", table), (c.NO_DEDUCT, None))
        self.assertEqual(c.expense_treatment("地代家賃", table), (c.INDIVIDUAL, None))
        self.assertEqual(c.expense_treatment(None, {"方式": "費目を限定しない"}), (c.DEDUCT, None))


class TestAdded20261112(unittest.TestCase):
    """2026-11-12 に足した規則の境目：協議が整わないときの標準報酬月額（PSK §3 別紙1(5)）、健保則37の3（PSK §4.1）、
    境目の説明の基準（SH §1.1、SA2 §2）、私学共済の優先する扶養義務者（KY §5 PMAC-01）。"""

    def test_remuneration(self) -> None:
        self.assertEqual(c.kyodo_by_remuneration("a", "b", 300_000, 300_001), "b")
        self.assertEqual(c.kyodo_by_remuneration("a", "b", 300_000, 300_000), c.KYODO_NEEDS_NOTICE)

    def test_certificate(self) -> None:
        # 別紙2(3)：直近の課税（非課税）証明書の所得金額が多い方。同額は通知に書かれていない（None）
        self.assertEqual(c.kyodo_by_certificate("a", "b", 1_000_000, 1_000_001), "b")
        self.assertEqual(c.kyodo_by_certificate("a", "b", 1_000_001, 1_000_000), "a")
        self.assertIsNone(c.kyodo_by_certificate("a", "b", 1_000_000, 1_000_000))

    def test_scholarship_point(self) -> None:
        # HF-03：注入点の候補は含む・含まないの2つ
        self.assertEqual({x.data["給付型の奨学金"] for x in POINTS["健保.給付型の奨学金の扱い"].candidates}, {"含む", "含まない"})

    def test_designated_activity(self) -> None:
        self.assertTrue(c.excluded_designated_activity(False, "medical_care_or_attendance"))
        self.assertTrue(c.excluded_designated_activity(None, "sightseeing_or_recreation"))
        self.assertFalse(c.excluded_designated_activity(False, "other"))
        self.assertFalse(c.excluded_designated_activity(True, "medical_care_or_attendance"))

    def test_half_threshold_matches_comparison(self) -> None:
        for ins in (3_000_000, 3_000_001):
            t = c.half_threshold(ins, Fraction(1, 2))
            self.assertTrue(Fraction(t - 1) < Fraction(ins, 2) and not Fraction(t) < Fraction(ins, 2))

    def test_support_minimum_is_the_border(self) -> None:
        for kind in c.SUPPORT_TYPES:
            for income, other in ((400_000, 0), (1_250_000, 100_000)):
                m = c.support_minimum(kind, income, other, RULES)
                with self.subTest(kind=kind, income=income):
                    self.assertTrue(c.support_ok(kind, income, m, other, 10**9, RULES))
                    self.assertFalse(c.support_ok(kind, income, m - 1, other, 10**9, RULES))

    def test_priority(self) -> None:
        R = c.CloserRelative
        self.assertEqual(c.priority_blocks([R("p", True, False)], None), (True, ()))
        self.assertEqual(c.priority_blocks([R("p", False, True, 3_000_001)], 3_000_000), (True, ()))
        self.assertEqual(c.priority_blocks([R("p", False, True, 3_000_000)], 3_000_000), (False, ()))
        self.assertEqual(c.priority_blocks([R("p", False, True, None)], 3_000_000), (False, ("p",)))


if __name__ == "__main__":
    unittest.main()
