"""規則モジュール kokuho（rules/kokuho/）のユニットテスト。関数と1つの変数の式を直接呼ぶ（上流の値は入力として与える）。

期待値の出典：docs/public-sources/20261109_round2_kokuho-premium-structure.md（[KHP]）§4.1（住民税の基礎控除の段）、§5（賦課限度額：
令和8年度 67万・26万・17万・3万、合計113万円）、§6.1（軽減の基準：43万円＋10万円×(k−1)、令和8年度 a＝31万円・b＝57万円、令和7年度 30万5千円・56万円）、
§7（未就学児の均等割の十分の五）、§9（18歳未満の子ども分の均等割の全額減額）、§10（国保税の100円未満の切捨て）。テストのデータは架空の金額だけ。
"""

from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import date
from fractions import Fraction

from openfisca_core.simulation_builder import SimulationBuilder

from okura_core.rules.kokuho.calc import (
    Household,
    KeigenRules,
    KubunRule,
    MunicipalRules,
    ResidentIncome,
    household_premium,
    keigen_income,
    keigen_tier,
    resident_basic_deduction,
    resident_income,
    shotokuwari_base,
    unemployment_cut,
    基礎,
    後期,
    介護,
    子ども,
    方式_ハ,
    方式_ロ,
    特定世帯,
    特定継続世帯,
)
from okura_core.rules.kokuho.facts import rule_months
from okura_core.rules.kokuho.inputs import specified_class

from .support import system


def _keigen_rules(income_year_start: str) -> KeigenRules:
    p = system().parameters.国保.軽減
    return KeigenRules(
        int(p.基準額(income_year_start)),
        int(p.給与所得者等の加算額(income_year_start)),
        int(p.五割の被保険者等1人あたりの額(income_year_start)),
        int(p.二割の被保険者等1人あたりの額(income_year_start)),
    )


def _deduction_table() -> list[tuple[int | None, int]]:
    p = system().parameters.国保.所得割の基礎.住民税の基礎控除
    at = "2025-01-01"
    return [(int(getattr(p, s).上限(at)), int(getattr(p, s).控除額(at))) for s in ("第1段", "第2段", "第3段")]


class TestKeigenBoundary(unittest.TestCase):
    """軽減の所得基準の境目（「超えない」が該当）。"""

    def test_reiwa8_thresholds(self) -> None:
        rules = _keigen_rules("2025-01-01")
        # k=1, n=2：7割 43万、5割 43万＋2×31万＝105万、2割 43万＋2×57万＝157万
        cases = [(430_000, "7割"), (430_001, "5割"), (1_050_000, "5割"), (1_050_001, "2割"), (1_570_000, "2割"), (1_570_001, "なし")]
        for total, tier in cases:
            with self.subTest(total=total):
                self.assertEqual(keigen_tier(total, 1, 2, rules), tier)
        # 給与所得者等が3人なら 7割の基準は 43万＋10万×2
        self.assertEqual(keigen_tier(630_000, 3, 3, rules), "7割")
        self.assertEqual(keigen_tier(630_001, 3, 3, rules), "5割")

    def test_reiwa7_per_member_amounts(self) -> None:
        rules = _keigen_rules("2024-01-01")
        self.assertEqual(keigen_tier(430_000 + 305_000, 1, 1, rules), "5割")
        self.assertEqual(keigen_tier(430_000 + 305_001, 1, 1, rules), "2割")
        self.assertEqual(keigen_tier(430_000 + 560_001, 1, 1, rules), "なし")

    def test_keigen_income_adds_back_family_employee_and_pension_special(self) -> None:
        # 専従者給与を差し引かない・分離課税の所得を足す・65歳以上の年金の所得から15万円（控除しきれない額は他の所得から引かない）
        self.assertEqual(keigen_income(ResidentIncome(500_000, family_employee=300_000, separate=100_000), 150_000), 900_000)
        self.assertEqual(keigen_income(ResidentIncome(500_000, pension_income=400_000, pension_65=True), 150_000), 350_000)
        self.assertEqual(keigen_income(ResidentIncome(500_000, pension_income=100_000, pension_65=True), 150_000), 400_000)


class TestShotokuwariBase(unittest.TestCase):
    """所得割の算定の基礎（基礎控除後の総所得金額等）。"""

    def test_basic_deduction_tiers(self) -> None:
        table = _deduction_table()
        self.assertEqual(resident_basic_deduction(24_000_000, table), 430_000)
        self.assertEqual(resident_basic_deduction(24_000_001, table), 290_000)
        self.assertEqual(resident_basic_deduction(25_000_000, table), 150_000)
        self.assertEqual(resident_basic_deduction(25_000_001, table), 0)

    def test_casualty_carryforward_is_not_deducted(self) -> None:
        # 雑損失の繰越控除をしない（足し戻す）・分離課税の所得を足す・0 未満は 0
        self.assertEqual(shotokuwari_base(ResidentIncome(1_000_000, casualty_carryforward=200_000, separate=50_000), 430_000), 820_000)
        self.assertEqual(shotokuwari_base(ResidentIncome(300_000), 430_000), 0)

    def test_variable_uses_fiscal_year_deduction(self) -> None:
        people = {
            "p": {"住民税_総所得金額等": {"2026": 3_000_000}, "住民税_合計所得金額": {"2026": 3_000_000}},
            "q": {"住民税_総所得金額等": {"2026": 24_500_000}, "住民税_合計所得金額": {"2026": 24_500_000}},
        }
        sim = SimulationBuilder().build_from_entities(system(), {"人物一覧": people})
        self.assertEqual([int(x) for x in sim.calculate("国保_基礎控除後の総所得金額等", "2026")], [2_570_000, 24_210_000])

    def test_resident_tax_windows_split_the_income_stages(self) -> None:
        # 2026-11-11：住民税の窓口（分離課税の所得・総所得金額等に含まれる退職所得・雑損失の繰越控除）で所得の段階を分ける。
        # 総所得金額等 300万円（うち分離課税 50万円・退職所得 20万円）、雑損失の繰越控除 10万円 →
        # 所得割の基礎＝(300−50−20)＋10＋50−43＝247万円（退職所得を含めない・雑損失を足し戻す）
        people = {
            "p": {
                "住民税_総所得金額等": {"2026": 3_000_000},
                "住民税_合計所得金額": {"2026": 3_000_000},
                "住民税_上場株式等に係る分離課税の所得の金額": {"2026": 500_000},
                "住民税_総所得金額等に含まれる退職所得金額": {"2026": 200_000},
                "住民税_雑損失の繰越控除額": {"2026": 100_000},
            }
        }
        sim = SimulationBuilder().build_from_entities(system(), {"人物一覧": people})
        self.assertEqual(int(sim.calculate("国保_基礎控除後の総所得金額等", "2026")[0]), 2_470_000)

    def test_earners_are_counted_per_household(self) -> None:
        # 給与所得者等（給与等の収入金額55万円超、公的年金等60万円超〔65歳以上125万円超〕）を世帯で数え、7割の基準額に 10万円×(k−1) を足す
        people = {
            "h": {"住民税_給与等の収入金額": {"2026": 550_001}, "国保_被保険者か": {"2026": True}},
            "s": {"住民税_公的年金等の収入金額": {"2026": 1_250_001}, "住民税_65歳以上の者に係る公的年金等控除額の控除を受けたか": {"2026": True},
                  "国保_被保険者か": {"2026": True}},
            "c": {"住民税_公的年金等の収入金額": {"2026": 1_250_000}, "住民税_65歳以上の者に係る公的年金等控除額の控除を受けたか": {"2026": True},
                  "国保_被保険者か": {"2026": True}},
        }
        groups = {"hh": {"世帯主一覧": ["h"], "世帯員一覧": ["s", "c"]}}
        sim = SimulationBuilder().build_from_entities(system(), {"人物一覧": people, "国保世帯一覧": groups})
        self.assertEqual([bool(x) for x in sim.calculate("国保_軽減の判定で数える給与所得者等か", "2026")], [True, True, False])
        # 合算額 0、n＝3、k＝2：7割の基準額 43万円＋10万円 を超えない
        self.assertEqual(str(sim.calculate("国保_軽減の区分", "2026")[0]), "7割")


def _rules(levy: str = "料", keigen: str = "7割・5割・2割") -> MunicipalRules:
    return MunicipalRules(
        levy=levy,
        kubun={
            基礎: KubunRule(方式_ロ, income_rate=Fraction(10, 100), per_capita=30_000, per_household=20_000, limit=670_000),
            後期: KubunRule(方式_ロ, income_rate=Fraction(3, 100), per_capita=10_000, per_household=5_000, limit=260_000),
            介護: KubunRule(方式_ハ, income_rate=Fraction(2, 100), per_capita=12_000, limit=170_000),
            子ども: KubunRule(方式_ハ, income_rate=Fraction(1, 100), per_capita=1_000, per_adult=500, limit=30_000),
        },
        keigen=keigen,
        preschool_ratio=Fraction(5, 10),
    )


NAMES = (基礎, 後期, 介護, 子ども)


class TestPremium(unittest.TestCase):
    def test_limits_reiwa8(self) -> None:
        """高所得の世帯：区分ごとに限度額（67万・26万・17万・3万）で止まり、合計は113万円。"""
        h = Household(base=8_000_000, base_kaigo=8_000_000, asset=0, asset_kaigo=0, insured=3, kaigo=1, adults=2, preschool=1)
        prem = household_premium(h, "なし", _rules(), NAMES)
        self.assertEqual([int(k.amount) for k in prem.kubun], [670_000, 260_000, 170_000, 30_000])
        self.assertEqual(prem.total, 1_130_000)
        # 基礎の区分：80万＋3万×3−未就学児の減額 1万5千＋平等割 2万 ＝ 89万5千（減額の後の額に限度額を当てる）
        self.assertEqual(prem.kubun[0].exact, 895_000)

    def test_keigen_and_ratio_sets(self) -> None:
        h = Household(base=0, base_kaigo=0, asset=0, asset_kaigo=0, insured=2, kaigo=0, adults=2, preschool=0)
        # 7割：基礎 (3万×2＋2万)×0.3＝24,000、後期 (1万×2＋5千)×0.3＝7,500、子ども (1千＋500)×2×0.3＝900
        self.assertEqual(household_premium(h, "7割", _rules(), NAMES).total, 32_400)
        # 6割・4割の市町村は7割の段階を6割で減額する
        self.assertEqual(household_premium(h, "7割", _rules(keigen="6割・4割"), NAMES).total, 43_200)
        # 6割・4割の市町村は2割の段階を減額しない
        self.assertEqual(
            household_premium(h, "2割", _rules(keigen="6割・4割"), NAMES).total, household_premium(h, "なし", _rules(), NAMES).total
        )

    def test_minor_child_share_and_preschool(self) -> None:
        # 18歳未満（未就学児）は子どもの区分の均等割が全額減額、基礎・後期の均等割は軽減の後の額の十分の五を減額
        h = Household(base=0, base_kaigo=0, asset=0, asset_kaigo=0, insured=2, kaigo=0, adults=1, preschool=1)
        prem = household_premium(h, "なし", _rules(), NAMES)
        self.assertEqual([int(k.amount) for k in prem.kubun], [65_000, 20_000, 0, 1_500])

    def test_tax_rounds_down_to_100_and_detects_fractions(self) -> None:
        r = _rules(levy="税")
        h = Household(base=1_234_567, base_kaigo=0, asset=0, asset_kaigo=0, insured=1, kaigo=0, adults=1, preschool=0)
        prem = household_premium(h, "なし", r, NAMES, [1_234_567])
        exact = sum((k.amount for k in prem.kubun), Fraction(0))
        self.assertEqual(prem.total, int(exact // 100) * 100)
        self.assertTrue(prem.fractional)  # 1,234,567×10/100 などに1円未満の端数（条例の事項）
        self.assertTrue(prem.base_not_thousand)

    def test_injected_rounding_removes_fraction(self) -> None:
        # 2026-11-11：注入データ 国保.端数処理 で所得割額などを丸める（123,456.7 → 切捨て 123,456・切上げ 123,457）
        h = Household(base=1_234_567, base_kaigo=0, asset=0, asset_kaigo=0, insured=1, kaigo=0, adults=1, preschool=0)
        down = household_premium(h, "なし", replace(_rules(), rounding="切捨て"), (基礎,))
        up = household_premium(h, "なし", replace(_rules(), rounding="切上げ"), (基礎,))
        self.assertFalse(down.fractional)
        self.assertEqual((down.total, up.total), (123_456 + 30_000 + 20_000, 123_457 + 30_000 + 20_000))

    def test_specified_household_amount_except_kaigo(self) -> None:
        # 特定世帯：基礎・後期・子どもの平等割を注入データの額にする（介護の区分には特定世帯の定めがない：[PS3-KH] §4）
        rules = _rules()
        kubun = dict(rules.kubun)
        kubun[基礎] = replace(kubun[基礎], per_household_specified=10_000)
        h = Household(base=0, base_kaigo=0, asset=0, asset_kaigo=0, insured=1, kaigo=0, adults=1, preschool=0)
        normal = household_premium(h, "なし", rules, (基礎,)).total
        special = household_premium(h, "なし", replace(rules, kubun=kubun, specified=特定世帯), (基礎,)).total
        self.assertEqual(normal - special, 10_000)

    def test_prorated_and_childbirth_weights(self) -> None:
        # 月割り（1月分 1/12）：6月分の被保険者1人。産前産後（1月分 1/12）：そのうち4月分の所得割・均等割を減額（平等割は減額しない）
        rules = replace(_rules(), month_ratio=Fraction(1, 12), birth_ratio=Fraction(1, 12), household_months=6)
        w = Fraction(6, 12) - Fraction(4, 12)
        h = Household(base=1_200_000 * w, base_kaigo=0, asset=0, asset_kaigo=0, insured=w, kaigo=0, adults=w, preschool=0, household=Fraction(6, 12))
        # 基礎：所得割 120万×10%×2/12＝20,000、均等割 3万×2/12＝5,000、平等割 2万×6/12＝10,000
        self.assertEqual(household_premium(h, "なし", rules, (基礎,)).total, 35_000)


class TestIncomeStages(unittest.TestCase):
    """2026-11-11：繰越控除の順序と非自発的失業者の特例。"""

    def test_casualty_deducted_from_retirement_is_not_added_back(self) -> None:
        # 総所得金額等（繰越控除の後）0、退職所得 30万円、雑損失の繰越控除 50万円：退職所得から30万円を控除 → 足し戻すのは20万円
        self.assertEqual(shotokuwari_base(resident_income(0, 300_000, 0, casualty=500_000), 0), 200_000)
        # 総所得金額等 100万円（退職所得 30万円を含む）：退職所得からは控除していない → 全額を足し戻す
        self.assertEqual(shotokuwari_base(resident_income(1_000_000, 300_000, 0, casualty=500_000), 0), 1_200_000)

    def test_unemployment_cut_boundary(self) -> None:
        # 給与所得 100万円 → 100分の30 は 30万円。損益通算の後の総所得金額が減る額 70万円 以上ならそのまま、未満なら0で止める
        self.assertEqual(unemployment_cut(1_000_000, 700_000, 300_000), 700_000)
        self.assertEqual(unemployment_cut(1_000_000, 699_999, 300_000), 699_999)
        self.assertEqual(unemployment_cut(1_000_000, 2_000_000, 300_000), 700_000)

    def test_rule_months_and_specified_class(self) -> None:
        # 取得した月から喪失した月の前月まで：2026-06-15 取得、2026-09-30 まで資格（喪失 10-01）→ 6月〜9月の4月
        self.assertEqual(rule_months([(date(2026, 6, 15), date(2026, 9, 30))], 2026), frozenset({2, 3, 4, 5}))
        # 特定月 2020-04：令和8年度（2026-04〜2027-03）は5年（60月・59月）を過ぎ8年以内 → 特定継続世帯で変わらない
        self.assertEqual(specified_class(date(2020, 4, 1), 2026), (特定継続世帯, False))
        # 特定月 2021-10：年度の途中で特定世帯から特定継続世帯に変わる → 決まらない
        self.assertEqual(specified_class(date(2021, 10, 1), 2026), (None, True))

    def test_listed_gains_after_carryforward(self) -> None:
        # 2026-11-12（KH-06）：上場株式等に係る譲渡所得等は繰越控除の後（docs/public-sources/20261112_impl-research4_kokuho-laws.md §2、
        # docs/inferences/20261112_impl-research4_all-cases.md I8）。前年の譲渡所得等 50万円・繰越損失 80万円 → 分離課税の所得は 0。
        # 総所得金額等 200万円・合計所得金額 250万円（繰越控除の前の 50万円を含む）→ 所得割の基礎＝200−43＝157万円（繰越控除の前の額を足さない）
        people = {
            "p": {
                "住民税_総所得金額等": {"2026": 2_000_000},
                "住民税_合計所得金額": {"2026": 2_500_000},
                "住民税_上場株式等に係る分離課税の所得の金額": {"2026": 0},
                "住民税_上場株式等の譲渡損失の繰越控除額": {"2026": 500_000},
            }
        }
        sim = SimulationBuilder().build_from_entities(system(), {"人物一覧": people})
        self.assertEqual(int(sim.calculate("国保_基礎控除後の総所得金額等", "2026")[0]), 1_570_000)


_A, _B = "990001", "990002"  # 架空の市町村（A：入院等の前、B：施設の所在地）


def _res(rid: str, pid: str, muni: str, hh: str, head: bool, from_on: str, to_on: str | None = None) -> dict:
    when = {"from_on": from_on} if to_on is None else {"from_on": from_on, "to_on": to_on}
    return {"id": rid, "kind": "resident_record", "roles": {"person": pid}, "when": when,
            "attributes": {"municipality_code": muni, "household_id": hh, "householder": head}}


def _nhi(rid: str, pid: str) -> dict:
    return {"id": rid, "kind": "medical_insurance", "roles": {"member": pid}, "when": {"from_on": "2020-01-01"},
            "attributes": {"scheme": "national_health_insurance"}}


def _institution(pid: str, **attrs: str) -> dict:
    return {"id": f"ev-{pid}", "kind": "kokuho_event", "roles": {"person": pid}, "when": {"from_on": "2026-02-01"},
            "attributes": {"event": "institution_special_case", **attrs}}


def _deem(persons: list[dict], residences: list[dict], facts: list[dict], relations: list[dict] = (), home: bool = False):  # type: ignore[assignment]
    from okura_core.registry import YearContext, YearWindow
    from okura_core.rules.kokuho.facts import deem_institution, deem_student, households, person_facts

    from .support import make_ir

    ids = [p["id"] for p in persons]
    ir = make_ir(persons, facts, residences=residences, relations=list(relations),
                 insurance_memberships=[_nhi(f"mi-{p}", p) for p in ids])
    ctx = YearContext(ir, 2025, tuple(ids), {}, window=YearWindow())
    pf = {p: person_facts(ctx, p, 2026) for p in ids}
    deem_student(ctx, pf, date(2026, 4, 1))
    deem_institution(ctx, pf, date(2026, 4, 1), lambda f: home)
    hs = households(ctx, pf)
    return pf, {m: h for h in hs for m in h.members}


class TestInstitutionSpecialCase(unittest.TestCase):
    """2026-11-12（KH-14）：国保法第116条の2 は住所（市町村）だけをみなし、世帯はみなさない
    （docs/public-sources/20261112_impl-research4_kokuho-laws.md §1・§1.1、docs/hypotheses/20261112_impl-research4_all-model.md H7、
    docs/inferences/20261112_impl-research4_all-cases.md I7）。"""

    def test_address_is_deemed_but_household_is_the_fact(self) -> None:
        # I7 例1：A市で親と同じ世帯の人が、B市の特別養護老人ホーム（措置）に入所し住民票を移した → A市の被保険者、世帯は施設での世帯
        persons = [{"id": "g", "birth_on": "1940-01-01"}, {"id": "s", "birth_on": "1970-01-01"}]
        res = [
            _res("r-g1", "g", _A, "hh-home", False, "2000-01-01", "2026-01-31"),
            _res("r-g2", "g", _B, "hh-fac", True, "2026-02-01"),
            _res("r-s", "s", _A, "hh-home", True, "2000-01-01"),
        ]
        pf, of = _deem(persons, res, [_institution("g", admission_type="elderly_home_placement")])
        self.assertEqual(pf["g"].deemed_municipality, _A)
        self.assertEqual(pf["g"].problems, [])
        self.assertEqual(of["g"].key, "hh:hh-fac")
        self.assertEqual(of["g"].municipality, _A)  # 保険者は入院等の前の市町村

    def test_same_municipality_is_not_deemed(self) -> None:
        # 入院等の前日の住所と施設が同じ市町村なら、第116条の2 は当たらない（他の市町村の住所だけをみなす）
        persons = [{"id": "g", "birth_on": "1940-01-01"}]
        res = [_res("r-g1", "g", _B, "hh-home", True, "2000-01-01", "2026-01-31"), _res("r-g2", "g", _B, "hh-fac", True, "2026-02-01")]
        pf, of = _deem(persons, res, [_institution("g", admission_type="hospital")])
        self.assertIsNone(pf["g"].deemed_municipality)
        self.assertEqual(of["g"].municipality, _B)

    def test_child_welfare_placement_has_two_households(self) -> None:
        # I7 例2：扶養義務者（親）と同じ世帯の子が他市の児童福祉施設に措置入所 → 世帯は施設の世帯か親元の世帯（柏市の運用：§1.2）。注入の値で決まる
        persons = [{"id": "p", "birth_on": "1985-01-01"}, {"id": "c", "birth_on": "2015-01-01"}]
        res = [
            _res("r-p", "p", _A, "hh-p", True, "2010-01-01"),
            _res("r-c1", "c", _A, "hh-p", False, "2015-01-01", "2026-01-31"),
            _res("r-c2", "c", _B, "hh-c", True, "2026-02-01"),
        ]
        rel = [{"id": "pc", "kind": "parentage", "roles": {"parent": "p", "child": "c"}, "when": {"on": "2015-01-01"}, "attributes": {"basis": "birth_mother"}}]
        ev = [_institution("c", admission_type="child_welfare_placement")]
        pf, of = _deem(persons, res, ev, rel, home=False)
        self.assertEqual((pf["c"].child_home, of["c"].key, of["c"].municipality), ("hh-p", "hh:hh-c", _A))
        pf, of = _deem(persons, res, ev, rel, home=True)
        self.assertEqual((of["c"].key, of["c"].head, of["c"].municipality), ("hh:hh-p", "p", _A))
        self.assertEqual(pf["c"].problems, [])
        # 入院等の種類の欄がなく、親がほかの世帯にいる → 分かれ目（事実：admission_type）
        pf, _ = _deem(persons, res, [_institution("c")], rel)
        self.assertEqual([x[0] for x in pf["c"].problems], ["事実:第116条の2の入院等の種類"])
        # 病院への入院なら事実の世帯（法令の読み）
        pf, of = _deem(persons, res, [_institution("c", admission_type="hospital")], rel)
        self.assertEqual((pf["c"].child_home, of["c"].key, pf["c"].problems), (None, "hh:hh-c", []))

    def test_deemed_household_id_wins_and_missing_prior_address_splits(self) -> None:
        persons = [{"id": "p", "birth_on": "1985-01-01"}, {"id": "c", "birth_on": "2015-01-01"}]
        res = [
            _res("r-p", "p", _A, "hh-p", True, "2010-01-01"),
            _res("r-c1", "c", _A, "hh-p", False, "2015-01-01", "2026-01-31"),
            _res("r-c2", "c", _B, "hh-c", True, "2026-02-01"),
        ]
        rel = [{"id": "pc", "kind": "parentage", "roles": {"parent": "p", "child": "c"}, "when": {"on": "2015-01-01"}, "attributes": {"basis": "birth_mother"}}]
        pf, of = _deem(persons, res, [_institution("c", admission_type="child_welfare_placement", deemed_household_id="hh-p")], rel)
        self.assertEqual((pf["c"].child_home, of["c"].key), (None, "hh:hh-p"))
        # 入院等の前日の住民票がない → 住所の市町村が決まらない（事実）
        pf, _ = _deem(persons, [res[0], res[2]], [_institution("c", admission_type="hospital")], rel)
        self.assertEqual([x[0] for x in pf["c"].problems], ["事実:第116条の2の入院等の前の住所"])


class TestBoundaryDeclarations(unittest.TestCase):
    """境目の説明の宣言（D19。2026-11-12）：軽減の区分は 7割・5割・2割 の所得基準の判定を直接読み、各判定は軽減判定所得を基準額（基準の概念）と比べる。"""

    def test_declarations(self) -> None:
        from okura_core.boundaries import declarations, undeclared
        from okura_core.evaluate import REGISTRY

        got = {b.judgment: (b.compared, b.criterion, b.comparison) for b in declarations(REGISTRY) if b.module == "kokuho"}
        for tier in ("7割", "5割", "2割"):
            with self.subTest(tier=tier):
                self.assertEqual(got[f"国保.{tier}軽減の所得基準を満たすか"], ("国保.軽減判定所得", f"国保.{tier}軽減の基準額", "以下"))
        self.assertNotIn("国保の軽減", undeclared(REGISTRY))


def _authority(rid: str, pid: str, decision: str, fiscal_year: int, tax_item: str = "national_health_insurance") -> dict:
    return {"id": rid, "kind": "authority_decision", "roles": {"person": pid}, "when": {"fiscal_year": fiscal_year},
            "attributes": {"decision": decision, "authority": "municipality", "tax_item": tax_item, "municipality_code": _A}}


class TestAuthorityDecision(unittest.TestCase):
    """2026-11-12（KH-17・KH-18）：市町村の個別の処分 authority_decision（F-D19）の修学中の特例の認定と減免の承認
    （[KHP] §1.1：国保法第116条・第77条、仮説 docs/hypotheses/20261109_round2_kokuho-core-vs-injected.md H1・H2）。"""

    _persons = [{"id": "p", "birth_on": "1975-01-01"}, {"id": "c", "birth_on": "2005-06-01"}]
    _homes = [_res("r-p", "p", _A, "hh-p", True, "2010-01-01"), _res("r-c", "c", _B, "hh-c", True, "2024-04-01")]
    _rel = [{"id": "pc", "kind": "parentage", "roles": {"parent": "p", "child": "c"}, "when": {"on": "2005-06-01"}, "attributes": {"basis": "birth_mother"}}]

    def test_student_recognition_deems_parent_household_for_that_fiscal_year_only(self) -> None:
        pf, of = _deem(self._persons, self._homes, [_authority("ad-c", "c", "kokuho_student_special_case_recognized", 2026)], self._rel)
        self.assertEqual((pf["c"].special_case, of["c"].key), ("student_special_case", "hh:hh-p"))
        self.assertEqual(pf["c"].record_ids["特例"], ["ad-c"])
        # ほかの年度の認定は使わない
        pf, of = _deem(self._persons, self._homes, [_authority("ad-c", "c", "kokuho_student_special_case_recognized", 2027)], self._rel)
        self.assertEqual((pf["c"].special_case, of["c"].key), (None, "hh:hh-c"))

    def test_reduction_is_a_household_value(self) -> None:
        from okura_core.rules.kokuho.inputs import Plan, reduction_records

        persons = [{"id": "p", "birth_on": "1975-01-01"}, {"id": "s", "birth_on": "1976-01-01"}]
        res = [_res("r-p", "p", _A, "hh-p", True, "2010-01-01"), _res("r-s", "s", _A, "hh-p", False, "2010-01-01")]
        pf, of = _deem(persons, res, [_authority("ad-p", "p", "reduction_approved", 2026)])
        hs = list({id(h): h for h in of.values()}.values())
        plan = Plan(2026, date(2026, 4, 1), pf, hs, dict(of))
        self.assertEqual([e["id"] for e in reduction_records(plan, of["s"])], ["ad-p"])  # 世帯員にも同じ値
        pf, of = _deem(persons, res, [_authority("ad-p", "p", "reduction_approved", 2027)])
        self.assertEqual(pf["p"].reduction, [])
        # 2026-11-12：住民税の減免（税目 resident_tax）は国保の減免として読まない（juminzei が読む）
        pf, of = _deem(persons, res, [_authority("ad-p", "p", "reduction_approved", 2026, "resident_tax")])
        self.assertEqual(pf["p"].reduction, [])

    def test_record_kinds_use_only_the_kokuho_decisions(self) -> None:
        from okura_core.registry import RecordKind
        from okura_core.rules.kokuho.inputs import record_kinds

        kinds = [k for k in record_kinds() if isinstance(k, RecordKind)]
        self.assertTrue(any(k.matches(_authority("x", "p", "reduction_approved", 2026)) for k in kinds))
        # 2026-11-12：記録の宣言は税目で絞る（住民税の処分は juminzei）
        self.assertFalse(any(k.matches(_authority("x", "p", "reduction_approved", 2026, "resident_tax")) for k in kinds))
        self.assertFalse(any(k.matches(_authority("x", "p", "taxation_at_non_resident_record_municipality", 2026, "resident_tax")) for k in kinds))


if __name__ == "__main__":
    unittest.main()
