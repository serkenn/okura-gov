"""共有の扶養の割当ての部品（okura_core/dependents。2026-11-12：juminzei JM-24〜26・personal_deductions PD-05）のユニットテスト。

期待値の出典：
  [ATTR] docs/public-sources/20261109_impl-prep_misc-age-kinship-attribution.md §1.1（所法85③ の判定の時）・§3.2（所令218〜219）
  [PSJ] docs/public-sources/20261109_impl-prep_juminzei-hikazei-fuyo-shinkoku.md §4.2（地令46の3〜46の5：住民税は記載が2人以上なら所得の合計額が最も大きい納税義務者）
  [EA] docs/public-sources/20261109_round2_elderly-abroad-laws.md §3.1（控除対象扶養親族：居住者16歳以上、非居住者は年齢の区分と書類）
  [JIN] docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md §1.5（障害者・特別障害者の区分）
テストのデータは架空。
"""

from __future__ import annotations

import datetime as _dt
import unittest

from okura_core.dependents.allocation import (
    Alloc,
    Candidacy,
    DependentLimits,
    DepListing,
    RelationFacts,
    Rule,
    allocate_one,
    categorize,
    largest,
)
from okura_core.dependents.ir_facts import IrIndex
from okura_core.dependents.person_at import DisabilityLimits, disability_at, judgment_day, person_at, residence_at

from .support import make_ir, person

D = _dt.date


def _cand(*people: str) -> dict[str, Candidacy]:
    return {p: Candidacy(True) for p in people}


def _pick(amounts: dict[str, int]):  # noqa: ANN202
    def pick(people: list[str], a: Alloc) -> str | None:
        tied = largest({p: amounts[p] for p in people})
        return tied[0] if tied else None

    return pick


class AllocateOneTest(unittest.TestCase):
    """所令218〜219（Rule.INCOME_TAX）と地令46の3〜46の5（Rule.LOCAL_TAX）の違い。"""

    def test_two_listers_income_tax_takes_the_earliest(self) -> None:
        # [ATTR]§3.2：所令219②一 既に記載している人（最も早い提出日）。所得は小さくてもその人
        listings = [DepListing("a", D(2026, 1, 10), "f-a"), DepListing("b", D(2026, 2, 1), "f-b")]
        got = allocate_one(_cand("a", "b"), None, False, (), (), listings, {}, _pick({"a": 1, "b": 9}), Rule.INCOME_TAX)
        self.assertEqual(got.claimant, "a")

    def test_two_listers_local_tax_takes_the_largest_income(self) -> None:
        # [PSJ]§4.2：地令46の5② 記載が2人以上なら前年の総所得金額等が最も大きい納税義務者（「既に記載」の段はない）
        listings = [DepListing("a", None, "f-a"), DepListing("b", None, "f-b")]
        got = allocate_one(_cand("a", "b"), None, False, (), (), listings, {}, _pick({"a": 1, "b": 9}), Rule.LOCAL_TAX)
        self.assertEqual(got.claimant, "b")

    def test_single_lister_and_no_listing(self) -> None:
        one = [DepListing("a", None, "f-a")]
        self.assertEqual(allocate_one(_cand("a", "b"), None, False, (), (), one, {}, _pick({"a": 1, "b": 9}), Rule.LOCAL_TAX).claimant, "a")
        # 記載がなく候補が2人：所得の合計額が最も大きい人（所令219②二・地令46の5②）
        for rule in Rule:
            self.assertEqual(allocate_one(_cand("a", "b"), None, False, (), (), (), {}, _pick({"a": 1, "b": 9}), rule).claimant, "b")
        # 候補でない人の記載は数えない
        self.assertEqual(allocate_one({"a": Candidacy(False), "b": Candidacy(True)}, None, False, (), (), one, {}, _pick({}), Rule.LOCAL_TAX).claimant, "b")

    def test_spouse_comes_first_unless_only_others_listed(self) -> None:
        # 所令218②・地令46の3：他の人だけが記載していればその人、それ以外は配偶者（同一生計配偶者）
        listed = [DepListing("a", None, "f-a")]
        for rule in Rule:
            self.assertIsNone(allocate_one(_cand("a"), "s", True, (), (), (), {}, _pick({"a": 1}), rule).claimant)
            self.assertEqual(allocate_one(_cand("a"), "s", True, (), (), listed, {}, _pick({"a": 1}), rule).claimant, "a")
            self.assertIsNone(allocate_one(_cand("a"), "s", True, (), ("f-s",), listed, {}, _pick({"a": 1}), rule).claimant)


def _facts(**kw: object) -> RelationFacts:
    base = dict(
        kin=True, child=False, cohab=False, cohab_etc=False, ascendant=False, doc=False, doc_study=False, doc_38=False, remit=0,
        ids=(), cohab_ids=(), doc_ids=(), study_ids=(), doc38_ids=(), remit_ids=(), states=frozenset(), cohab_states=frozenset(), remit_states=frozenset(),
    )  # fmt: skip
    base.update(kw)
    return RelationFacts(**base)  # type: ignore[arg-type]


LIM = DependentLimits(16, 16, 30, 70, 380_000, 19, 23, 70, 19, 23, 1_230_000)


class CategorizeTest(unittest.TestCase):
    """personal_deductions/judgments.py の式と同じ要件（[EA]§3.1）。"""

    def _c(self, **kw: object):  # noqa: ANN202
        base = dict(allocated=True, dependent_income_ok=True, income=0, age=40, resident=True, study_abroad=False, disabled=False, special=False, facts=_facts(), lim=LIM)
        base.update(kw)
        return categorize(**base)  # type: ignore[arg-type]

    def test_resident_age_boundaries(self) -> None:
        self.assertFalse(self._c(age=15).control)
        self.assertTrue(self._c(age=16).control)
        self.assertTrue(self._c(age=19).specific)
        self.assertFalse(self._c(age=23).specific)
        self.assertTrue(self._c(age=70).elderly)
        self.assertFalse(self._c(age=70).cohab_elderly)
        self.assertTrue(self._c(age=70, facts=_facts(ascendant=True, cohab=True)).cohab_elderly)

    def test_non_resident_needs_documents(self) -> None:
        self.assertFalse(self._c(resident=False, age=20).control)
        self.assertTrue(self._c(resident=False, age=20, facts=_facts(doc=True)).control)
        # 30歳以上70歳未満は区分の要件：留学・障害者・38万円以上の送金
        self.assertFalse(self._c(resident=False, age=40, facts=_facts(doc=True)).control)
        self.assertTrue(self._c(resident=False, age=40, disabled=True, facts=_facts(doc=True)).control)
        self.assertTrue(self._c(resident=False, age=40, facts=_facts(remit=380_000, doc_38=True)).control)
        self.assertFalse(self._c(resident=False, age=40, facts=_facts(remit=379_999, doc_38=True)).control)

    def test_specified_relative_and_not_allocated(self) -> None:
        got = self._c(age=20, dependent_income_ok=False, income=1_230_000)
        self.assertFalse(got.dependent)
        self.assertTrue(got.specified_relative)
        self.assertFalse(self._c(age=20, dependent_income_ok=False, income=1_230_001).specified_relative)
        self.assertFalse(self._c(allocated=False).dependent)
        self.assertTrue(self._c(special=True, facts=_facts(cohab_etc=True)).cohab_special)


class PersonAtTest(unittest.TestCase):
    """判定する人の判定の時の現況（所法85③：[ATTR]§1.1、障害の区分：[JIN]§1.5）。"""

    LIM = DisabilityLimits(65, 2, 1)

    def _ir(self, judgments: list[dict], facts: list[dict]) -> dict:
        return make_ir([person("p", "2000-06-15")], facts, judgments=judgments)

    def test_emigrant_is_abroad_on_dec31(self) -> None:
        j = {"id": "j-1", "kind": "判断.住所の所在", "judged_by": {"person": "p"}, "judged_at": "2026-12-01T00:00:00+09:00",
             "subject": {"person": "p"}, "when": {"from_on": "2026-09-01"}, "value": "foreign"}  # fmt: skip
        stay = {"id": "a-1", "kind": "abroad_stay", "roles": {"person": "p"}, "when": {"from_on": "2026-09-01"}, "attributes": {"country": "US", "purpose": "study"}}
        ir = self._ir([j], [stay])
        resident, study, _ = residence_at(ir, IrIndex(ir), "p", D(2026, 12, 31))
        self.assertEqual((resident, study), (False, True))
        resident, _, _ = residence_at(ir, IrIndex(ir), "p", D(2026, 8, 31))
        self.assertTrue(resident)
        at = person_at(ir, IrIndex(ir), "p", D(2000, 6, 15), D(2026, 12, 31), D(2026, 12, 31), self.LIM)
        self.assertEqual((at.age, at.resident, at.study_abroad, at.missing), (26, False, True, ()))

    def test_stay_without_judgment_is_undetermined(self) -> None:
        stay = {"id": "a-1", "kind": "abroad_stay", "roles": {"person": "p"}, "when": {"from_on": "2026-09-01"}, "attributes": {"country": "US", "purpose": "work"}}
        ir = self._ir([], [stay])
        at = person_at(ir, IrIndex(ir), "p", D(2000, 6, 15), D(2026, 12, 31), D(2026, 12, 31), self.LIM)
        self.assertIsNone(at.resident)
        self.assertEqual(len(at.missing), 1)

    def test_disability_grades(self) -> None:
        def basis(grade: int) -> dict:
            return {"id": f"d-{grade}", "kind": "disability_basis", "roles": {"person": "p"}, "when": {"from_on": "2020-01-01"},
                    "attributes": {"basis": "physical_disability_certificate", "grade": grade}}  # fmt: skip

        for grade, want in ((1, (True, True)), (2, (True, True)), (3, (True, False))):
            ir = self._ir([], [basis(grade)])
            disabled, special, _, missing = disability_at(ir, IrIndex(ir), "p", D(2026, 12, 31), 26, self.LIM)
            self.assertEqual((disabled, special, missing), (*want, []))

    def test_age_on_the_death_day(self) -> None:
        # 死亡の時は前日の終了時（所得税.年齢 と同じ読み）
        self.assertEqual(judgment_day(D(2026, 6, 15), D(2026, 6, 15)), D(2026, 6, 14))
        self.assertEqual(judgment_day(D(2026, 12, 31), None), D(2026, 12, 31))


class JudgeTimeTest(unittest.TestCase):
    """PD-05：出国する人を出国しない居住者が判定するときの判定の時（[ATTR]§1.1 所法85③：判定する居住者の12月31日）。"""

    def test_judge_time_follows_the_judge(self) -> None:
        from okura_core.dependents.family import build_family
        from okura_core.registry import YearContext

        j = {"id": "j-1", "kind": "判断.住所の所在", "judged_by": {"person": "d"}, "judged_at": "2026-12-01T00:00:00+09:00",
             "subject": {"person": "d"}, "when": {"from_on": "2026-09-01"}, "value": "foreign"}  # fmt: skip
        ir = make_ir([person("c", "1970-01-01"), person("d", "2000-01-01")], [], judgments=[j])
        fam = build_family(YearContext(ir, 2026, ("c", "d")))
        self.assertEqual(fam.cut("d"), D(2026, 8, 31))  # 出国の時：国外へ移る日の前日
        self.assertEqual(fam.judge_time("c", "d"), D(2026, 12, 31))  # d の出国は c の判定の時を変えない
        self.assertEqual(fam.judge_time("d", "c"), D(2026, 8, 31))

    def test_view_variables_use_the_judge_time_values(self) -> None:
        from openfisca_core.simulation_builder import SimulationBuilder

        from .support import system

        def calc(var: str, **values: object) -> object:
            situation = {"人物一覧": {"p": {k: {"2026": v} for k, v in values.items()}}}
            return SimulationBuilder().build_from_entities(system(), situation).calculate(var, "2026")[0]

        own = {"所得税_判定の時に住所が国内にあるか": True, "所得税_生年月日": "2000-01-01"}
        self.assertTrue(calc("所得税_扶養等の判定に使う居住者か", **own))
        at = {**own, "所得税_判定する人の判定の時の値を使うか": True, "所得税_判定する人の判定の時に居住者か": False, "所得税_判定する人の判定の時の年齢": 26}
        self.assertFalse(calc("所得税_扶養等の判定に使う居住者か", **at))
        self.assertEqual(calc("所得税_扶養等の判定に使う年齢", **at), 26)


if __name__ == "__main__":
    unittest.main()
