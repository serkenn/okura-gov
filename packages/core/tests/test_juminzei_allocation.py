"""住民税の扶養の割当て（rules/juminzei/allocation.py の段。README JM-24〜26）のユニットテスト。段の関数を直接呼び、前の段の値はスタブ。

期待値の出典：
  [PSJ] docs/public-sources/20261109_impl-prep_juminzei-hikazei-fuyo-shinkoku.md §4.2（地令46の5①：申告書・報告書・申請書の記載、②：2人以上・記載がなく決まらない
        ときは前年の総所得金額・退職所得金額・山林所得金額の合計額が最も大きい納税義務者）・§5（扶養親族の上限：令和9年度分 62万円）
  [TAI] docs/public-sources/20261109_round2b_taishoku-laws-and-guidance.md §6.3（分離課税に係る退職所得は住民税の合計所得金額に含めない）
テストのデータは架空。
"""

from __future__ import annotations

import unittest
from typing import Any

from okura_core.dependents.family import J_SEIKEI, pair_key
from okura_core.injection import EMPTY
from okura_core.registry import Decided, StageContext, StageValue, YearContext, YearWindow
from okura_core.rules.juminzei import MODULE, allocation as al
from okura_core.timepoints import resident_tax_window

from .support import make_ir, person, system

YEAR = 2026  # 令和9年度分（所得の年分 2026）


def _spec(name: str) -> Any:
    return next(s for s in MODULE.stages if s.name == name)


def _dec(value: Any) -> Decided:
    return Decided(value, (), frozenset(), False)


DEFAULTS: dict[str, Any] = {
    al.R_CLAIMANT_IT: "", al.R_TOTAL: 0, al.R_TOTAL_IT: 0, al.R_GROSS: 0, al.R_DOMICILE: "990001", al.R_AGE: 50, al.R_RESIDENT: True,
    al.R_STUDY: False, al.R_DISABLED: False, al.R_SPECIAL: False, al.R_SP_LIVE: False, al.R_SP_SENJU: False, al.R_COHAB_SPOUSE: False,
    al.R_DIVORCED: False, al.R_MARRIED: False, al.R_WIDOWED: False, al.R_DE_FACTO: False, al.R_MISSING: False, al.R_STUDENT: False,
    al.R_WAGE: 0, al.R_SALARY: 0, al.R_RETIRE: 0, al.R_RETIRE_SEP: 0, al.R_BUSINESS: 0, al.R_MISC: 0, al.R_LABOR: False,
    al.R_IT_SPOUSE: False, al.R_IT_WIDOW: False, al.R_IT_SINGLE: False, al.R_IT_WORKING: False,
    al.R_DIVIDEND: 0, al.R_REAL: 0, al.R_WINDFALL: 0, al.R_PENSION_MISC: 0, al.R_PENSION_RECEIPT: 0, al.R_LISTED_SEP: 0,
}  # fmt: skip


def _jan1(p: str, salary: bool) -> dict[str, Any]:
    """1月1日の給与の支払者の記録（地令46の3① の区分：JM-33）。"""
    return {
        "id": f"j1-{p}", "kind": "jan1_payer_status", "roles": {"person": p}, "when": {"fiscal_year": YEAR + 1},
        "attributes": {"salary_payer_on_jan1": salary, "pension_payer_on_jan1": False, "payer_must_file_report": True},
    }  # fmt: skip


def _doc(rid: str, filer: str, doc: str, child: str = "c", on: str = "2027-01-20") -> dict[str, Any]:
    attrs: dict[str, Any] = {"document_type": doc, "entries": [{"person": child, "section": "dependent_relative"}]}
    attrs["fiscal_year" if doc in al.FISCAL_YEAR_DOCS and doc not in al.TAX_YEAR_DOCS else "tax_year"] = YEAR + 1 if doc in ("resident_tax_return", al.APPLICATION) else YEAR
    return {"id": rid, "kind": "filed_document", "roles": {"filer": filer}, "when": {"on": on}, "attributes": attrs}


def _run(docs: list[dict[str, Any]], values: dict[tuple[str, str], Any], facts: list[dict[str, Any]] | None = None) -> Any:
    persons = [person("a", "1970-01-01"), person("b", "1972-01-01"), person("c", "2006-05-01")]
    rel = [
        {"id": "r-ac", "kind": "parentage", "roles": {"parent": "a", "child": "c"}, "when": {"on": "2006-05-01"}, "attributes": {"basis": "birth_in_marriage"}},
        {"id": "r-bc", "kind": "parentage", "roles": {"parent": "b", "child": "c"}, "when": {"on": "2006-05-01"}, "attributes": {"basis": "birth_mother"}},
    ]
    ir = make_ir(persons, facts or [], relations=rel, filed_documents=docs)
    decided = {(J_SEIKEI, pair_key("a", "c")): _dec(True), (J_SEIKEI, pair_key("b", "c")): _dec(True)}
    window = YearWindow(parameters_at=lambda s: system().parameters(s), parameter_root=system().parameters, windows=(resident_tax_window(YEAR + 1),), injected=EMPTY)
    base = YearContext(ir, YEAR, ("a", "b", "c"), decided, window=window)
    stage_values = {}
    for p in ("a", "b", "c"):
        for var, default in DEFAULTS.items():
            if p in ("a", "b") and var in (al.R_TOTAL, al.R_TOTAL_IT):
                default = 3_000_000  # 親は所得があり、子の扶養親族にならない
            stage_values[(var, p)] = StageValue(var, p, values.get((var, p), default))
    return al.run(StageContext(base, _spec(al.STAGE), stage_values))


def _v(out: Any, var: str, p: str) -> Any:
    return out.inputs.values[(var, p)].value if hasattr(out, "inputs") else out.values[(var, p)].value


def _out(out: Any) -> Any:
    return out.inputs if hasattr(out, "inputs") else out


class SameAsIncomeTaxTest(unittest.TestCase):
    def test_one_lister_same_claimant(self) -> None:
        out = _run([_doc("f-a", "a", "final_return")], {(al.R_CLAIMANT_IT, "c"): "a", (al.R_AGE, "c"): 20})
        o = _out(out)
        self.assertEqual(o.values[(al.W_CLAIMANT, "c")].value, "a")
        self.assertFalse(o.values[(al.W_SEP, "c")].value)  # 所得税と同じ：所得税の判定をそのまま使う
        self.assertFalse(o.values[(al.W_SELF, "a")].value)
        self.assertEqual(o.exclusions, [])


class ListingRuleTest(unittest.TestCase):
    """JM-25：2人以上の記載で、住民税の所属（所得の合計額が最も大きい納税義務者：[PSJ]§4.2）が所得税の申告者と違う。"""

    def test_largest_income_wins_for_resident_tax(self) -> None:
        docs = [_doc("f-a", "a", "final_return", on="2026-01-10"), _doc("f-b", "b", "salary_payment_report", on="2027-01-20")]
        vals = {(al.R_CLAIMANT_IT, "c"): "a", (al.R_GROSS, "a"): 3_000_000, (al.R_GROSS, "b"): 5_000_000, (al.R_AGE, "c"): 20, (al.R_WAGE, "b"): 6_000_000}
        raw = _run(docs, vals, [_jan1("b", True)])  # b は給与所得等以外の所得を有しなかった者：給与支払報告書の記載（JM-33）
        o = _out(raw)
        self.assertEqual(o.values[(al.W_CLAIMANT, "c")].value, "b")
        self.assertTrue(o.values[(al.W_SEP, "c")].value)
        self.assertTrue(o.values[(al.W_DEP, "c")].value)
        self.assertTrue(o.values[(al.W_CTRL, "c")].value)  # 20歳（前年の12月31日）・居住者：控除対象扶養親族・特定扶養親族
        self.assertTrue(o.values[(al.W_TOKU, "c")].value)
        self.assertTrue(o.values[(al.W_SELF, "a")].value and o.values[(al.W_SELF, "b")].value)
        groups = {g.id: g.roles for g in raw.groups["住民税扶養所属一覧"]}
        self.assertEqual(groups["住民税扶養所属:b"].get("住民税の扶養親族等一覧"), ("c",))

    def test_application_overrides_reports(self) -> None:
        # [PSJ]§4.2：第46条の5第1項ただし書：申請書を出せば、申請した人の所属はその申請書の記載による（2026-11-12 の JM-33 で読みを直した：
        # 申請書が置き換えるのは申請した人の給与支払報告書の記載だけ。ほかの人の報告書の記載は残り、2人以上なら第2項）
        app = _doc("f-a2", "a", al.APPLICATION)
        app["attributes"]["entries"] = []  # a は申請書で c を自己の扶養親族としない
        docs = [_doc("f-a", "a", "salary_payment_report"), app, _doc("f-b", "b", "salary_payment_report")]
        vals = {(al.R_CLAIMANT_IT, "c"): "a", (al.R_GROSS, "a"): 5_000_000, (al.R_GROSS, "b"): 1_000_000, (al.R_AGE, "c"): 20}
        vals |= {(al.R_WAGE, "a"): 6_000_000, (al.R_WAGE, "b"): 1_500_000}
        o = _out(_run(docs, vals, [_jan1("a", True), _jan1("b", True)]))
        self.assertEqual(o.values[(al.W_CLAIMANT, "c")].value, "b")  # 申請書がなければ2人の記載で所得の大きい a
        o = _out(_run(docs[:1] + docs[2:], vals, [_jan1("a", True), _jan1("b", True)]))
        self.assertEqual(o.values[(al.W_CLAIMANT, "c")].value, "a")


class DocumentCategoryTest(unittest.TestCase):
    """JM-33：地令46の5① の書類を記載した人の区分で分ける（[JZ] docs/public-sources/20261112_impl-research5_juminzei-zasson-and-46-5.md §2）。"""

    def test_salary_only_person_final_return_does_not_count(self) -> None:
        # a は給与だけ（1月1日に給与の支払を受ける）：医療費控除の確定申告書の記載は第46条の5第1項の書類でない。b は事業所得があり申告義務者：確定申告書の記載で b
        docs = [_doc("f-a", "a", "final_return"), _doc("f-b", "b", "final_return")]
        vals = {(al.R_CLAIMANT_IT, "c"): "a", (al.R_GROSS, "a"): 5_000_000, (al.R_GROSS, "b"): 1_000_000, (al.R_AGE, "c"): 20}
        vals |= {(al.R_WAGE, "a"): 6_000_000, (al.R_BUSINESS, "b"): 1_000_000}
        o = _out(_run(docs, vals, [_jan1("a", True)]))
        self.assertEqual(o.values[(al.W_CLAIMANT, "c")].value, "b")
        # 同じ記載で、a が1月1日に給与の支払を受けていない（申告義務者）なら2人の記載：所得の合計額が最も大きい a
        o = _out(_run(docs, vals, [_jan1("a", False)]))
        self.assertEqual(o.values[(al.W_CLAIMANT, "c")].value, "a")

    def test_declaration_stands_for_report(self) -> None:
        # 給与支払報告書の記録がない給与所得者は、扶養控除等申告書の記載を報告書の記載とする（法令の読み）
        docs = [_doc("f-a", "a", "employee_dependents_declaration")]
        vals = {(al.R_CLAIMANT_IT, "c"): "a", (al.R_GROSS, "a"): 1_000_000, (al.R_GROSS, "b"): 5_000_000, (al.R_AGE, "c"): 20, (al.R_WAGE, "a"): 2_000_000}
        o = _out(_run(docs, vals, [_jan1("a", True)]))
        self.assertEqual(o.values[(al.W_CLAIMANT, "c")].value, "a")

    def test_unknown_category_splits(self) -> None:
        # a の1月1日の支払者の記録がない：申告義務者なら記載なし（所得の大きい b）、給与所得等以外の所得を有しなかった者なら a。分かれるので未確定
        docs = [_doc("f-a", "a", "employee_dependents_declaration")]
        vals = {(al.R_CLAIMANT_IT, "c"): "a", (al.R_GROSS, "a"): 1_000_000, (al.R_GROSS, "b"): 5_000_000, (al.R_AGE, "c"): 20, (al.R_WAGE, "a"): 2_000_000}
        o = _out(_run(docs, vals))
        miss = o.values[(al.W_CLAIMANT, "c")].missing
        self.assertIn(f"事実:地令46の5の書類の区分:c:{YEAR + 1}", [m.id for m in miss])


class SeparateRetirementTest(unittest.TestCase):
    """JM-24：分離課税に係る退職所得がある人（住民税の合計所得金額から除く：[TAI]§6.3）。"""

    def test_dependent_only_for_resident_tax(self) -> None:
        # 所得税の合計所得金額 100万円（扶養親族でない）、住民税の合計所得金額 40万円（62万円以下：[PSJ]§5）
        vals = {(al.R_TOTAL_IT, "c"): 1_000_000, (al.R_TOTAL, "c"): 400_000, (al.R_GROSS, "a"): 2_000_000, (al.R_GROSS, "b"): 1_000_000, (al.R_AGE, "c"): 20}
        o = _out(_run([_doc("f-a", "a", "final_return")], vals))
        self.assertEqual(o.values[(al.W_CLAIMANT, "c")].value, "a")
        self.assertTrue(o.values[(al.W_SEP, "c")].value)
        self.assertTrue(o.values[(al.W_DEP, "c")].value)
        self.assertFalse(o.values[(al.W_SPEC_REL, "c")].value)

    def test_boundary_of_the_cap(self) -> None:
        for total, want in ((620_000, True), (620_001, False)):
            vals = {(al.R_TOTAL_IT, "c"): 1_000_000, (al.R_TOTAL, "c"): total, (al.R_AGE, "c"): 30}
            o = _out(_run([_doc("f-a", "a", "final_return")], vals))
            with self.subTest(total=total):
                self.assertEqual(o.values[(al.W_DEP, "c")].value, want)


class TieAndTaxpayerTest(unittest.TestCase):
    def test_tie_is_undetermined(self) -> None:
        # JM-26：記載がなく、前年の総所得金額等が同額：地令46の5② に同額の定めがない → 一次情報の分かれ目
        vals = {(al.R_CLAIMANT_IT, "c"): "a", (al.R_GROSS, "a"): 2_000_000, (al.R_GROSS, "b"): 2_000_000, (al.R_AGE, "c"): 20}
        o = _out(_run([], vals))
        miss = o.values[(al.W_CLAIMANT, "c")].missing
        self.assertTrue(any(s.id == "読み:住民税の扶養の所属の同額:c" for s in miss))
        self.assertTrue(o.values[(al.W_SEP, "c")].value)

    def test_not_a_taxpayer_cannot_claim(self) -> None:
        # 賦課期日に住所がない人は納税義務者でない（所得税では申告者でも、住民税の扶養親族等を有しない）
        vals = {(al.R_CLAIMANT_IT, "c"): "a", (al.R_DOMICILE, "a"): "", (al.R_GROSS, "a"): 9_000_000, (al.R_GROSS, "b"): 1_000_000, (al.R_AGE, "c"): 20}
        o = _out(_run([_doc("f-a", "a", "final_return")], vals))
        self.assertEqual(o.values[(al.W_CLAIMANT, "c")].value, "b")


class SingleParentTest(unittest.TestCase):
    def test_local_single_parent(self) -> None:
        # 住民税の合計所得金額で判定：子が住民税の扶養親族等で総所得金額等が基準以下、本人に配偶者がいない
        vals = {(al.R_TOTAL_IT, "c"): 1_000_000, (al.R_TOTAL, "c"): 400_000, (al.R_GROSS, "c"): 400_000, (al.R_GROSS, "a"): 2_000_000, (al.R_TOTAL, "a"): 2_000_000, (al.R_TOTAL_IT, "a"): 2_000_000, (al.R_AGE, "c"): 20}
        o = _out(_run([_doc("f-a", "a", "final_return")], vals))
        self.assertTrue(o.values[(al.W_SELF, "a")].value)
        self.assertTrue(o.values[(al.W_SINGLE, "a")].value)
        self.assertFalse(o.values[(al.W_WIDOW, "a")].value)

    def test_unchanged_fields_copy_income_tax(self) -> None:
        # 本人の合計所得金額が同じで勤労学生の材料に分離課税の退職所得がなければ、勤労学生は所得税の判定をそのまま写す
        vals = {(al.R_TOTAL_IT, "c"): 1_000_000, (al.R_TOTAL, "c"): 400_000, (al.R_AGE, "c"): 20, (al.R_IT_WORKING, "a"): True}
        o = _out(_run([_doc("f-a", "a", "final_return")], vals))
        self.assertTrue(o.values[(al.W_SELF, "a")].value)
        self.assertTrue(o.values[(al.W_WORKING, "a")].value)


class ChainTest(unittest.TestCase):
    def test_sums_the_chain_person(self) -> None:
        base = YearContext(make_ir([person("a"), person("c")], []), YEAR, ("a", "c"))
        vals = {}
        for p in ("a", "c"):
            vals[(al.W_CLAIMANT, p)] = StageValue(al.W_CLAIMANT, p, "a" if p == "c" else "")
            vals[(al.W_CHAIN, p)] = StageValue(al.W_CHAIN, p, p == "c")
            for var, amount in ((al.R_DED, 450_000), (al.R_SPEC, 0), (al.R_DIS, 0), (al.R_DIFF, 180_000), (al.R_COUNT, True)):
                vals[(var, p)] = StageValue(var, p, amount if p == "c" else 0)
        o = _out(al.run_chain(StageContext(base, _spec(al.STAGE_CHAIN), vals)))
        self.assertEqual(o.values[(al.C_DED, "a")].value, 450_000)
        self.assertEqual(o.values[(al.C_COUNT, "a")].value, 1)
        self.assertEqual(o.values[(al.C_DED, "c")].value, 0)


if __name__ == "__main__":
    unittest.main()
