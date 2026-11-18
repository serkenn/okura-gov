"""様式の欄の対応表の科目の割当て（design-output UO19）と行の割当て（UO23）、それに足した概念の境目のユニットテスト（2026-11-12）。

上流の判定コアの値はスタブ（ResultValue を直接作る）。OpenFisca の式は上流の変数に値を与えた Simulation で式だけを確かめる。
テストのデータは架空の値だけ。
"""

from __future__ import annotations

import datetime as _dt
import unittest
from typing import Any

from openfisca_core.simulation_builder import SimulationBuilder

from okura_core.forms import FieldStatus, FormsResult, FormTableError, fill_forms, load_year, parse_form
from okura_core.forms.rows import ASSIGNED, MISSING, UNDETERMINED, assign_rows
from okura_core.forms.table import KAMOKU_FILE, parse_kamoku
from okura_core.registry import ModuleInputs
from okura_core.result import DateValue, ResultValue, State
from okura_core.rules.income_kinds.breakdown import KEYS, RECORD_KEYS, Breakdown, write_breakdown
from okura_ir.vocabulary import EXPENSE_CATEGORIES

from .support import system
from .test_forms import TYPE_ZEROS, T, rv, values

F = "p-1"  # 申告者
SPOUSE = "p-2"


def _d(on: str, person: str) -> ResultValue:
    return ResultValue(
        id=f"v:生年月日:{person}", concept="所得税.生年月日", variable=None, person=person, time=T,
        value=DateValue(_dt.date.fromisoformat(on)), states=frozenset(), basis=(),
    )  # fmt: skip


def _family(
    *,
    spouse: str = "なし",
    same: bool = False,
    special: int = 0,
    relatives: tuple[tuple[str, str, bool, bool, str], ...] = (),
) -> list[ResultValue]:
    """申告者の値と親族の値。relatives は（人、申告者、扶養親族か、特定親族か、生年月日）。いない人は「なし」。"""
    out = [
        rv("所得税.法律婚の相手", spouse, person=F),
        rv("所得税.同一生計配偶者に当たるか", same, person=F),
        rv("所得税.配偶者特別控除の額", special, person=F),
        rv("所得税.扶養親族等とする申告者", "なし", person=F),
    ]
    for p, claimant, dep, spec, born in relatives:
        out += [
            rv("所得税.扶養親族等とする申告者", claimant, person=p),
            rv("所得税.扶養親族に当たるか", dep, person=p),
            rv("所得税.特定親族に当たるか", spec, person=p),
            _d(born, p),
        ]
    return out


class TestKamoku(unittest.TestCase):
    def test_every_breakdown_key_is_assigned_in_every_table(self) -> None:
        k = load_year(2025).kamoku
        self.assertIsNotNone(k)
        self.assertEqual(set(k.assignments), set(KEYS))
        # 記録の費目は中間表現の語彙（業務の支出でない dividend_debt_interest を除く）と同じ
        self.assertEqual(set(RECORD_KEYS), set(EXPENSE_CATEGORIES) - {"dividend_debt_interest"})

    def test_expansion_to_breakdown_concepts(self) -> None:
        f = load_year(2025).form("KOA110-01").field_at("経費/その他の経費/イ租税公課")
        first, rest = f.mapping.cases
        self.assertEqual(first.when[0].concept, "所得税.事業所得の必要経費のうち内訳のない額")
        self.assertEqual(
            set(first.outcome.concepts),
            {f"所得税.事業所得の必要経費の内訳.{k}" for k in ("tax", "membership_dues", "consumption_tax")},
        )
        self.assertEqual((rest.outcome.kind, rest.outcome.category), ("なし", "未対応"))
        # 不動産所得用（決算書）は印字のない科目を「その他の経費」に入れる
        g = load_year(2025).form("KOA220-01").field_at("必要経費/その他の経費")
        self.assertIn("所得税.不動産所得の必要経費の内訳.utilities", g.mapping.cases[0].outcome.concepts)

    def test_unclassified_amount_stops_the_items(self) -> None:
        base = dict(
            青色申告の承認を受けているか=False, 事業所得の総収入金額=1_000_000, 事業所得の必要経費=30_000,
            **{f"事業所得の必要経費の内訳.{k}": 0 for k in KEYS},
        )  # fmt: skip
        base["事業所得の必要経費の内訳.tax"] = 10_000
        base["事業所得の必要経費の内訳.consumption_tax"] = 20_000
        ok = fill_forms(values(**base, **{"事業所得の必要経費のうち内訳のない額": 0}), F, 2025)
        self.assertIsInstance(ok, FormsResult)
        f = ok.form("KOA110-01").field_at("経費/その他の経費/イ租税公課")
        self.assertEqual((f.status, f.value), (FieldStatus.OUTPUT, 30_000))
        ng = fill_forms(values(**base, **{"事業所得の必要経費のうち内訳のない額": 1}), F, 2025)
        g = ng.form("KOA110-01").field_at("経費/その他の経費/イ租税公課")
        self.assertEqual((g.status, g.category), (FieldStatus.NO_CONCEPT, "未対応"))

    def test_user_override_moves_the_key(self) -> None:
        """選択.様式への割当て（C-18）：会費（membership_dues）を雑費（other の既定の科目）へ。必要経費の額は変わらない。"""
        base = dict(
            青色申告の承認を受けているか=False, 事業所得の総収入金額=1_000_000, 事業所得の必要経費=30_000,
            事業所得の必要経費のうち内訳のない額=0, **{f"事業所得の必要経費の内訳.{k}": 0 for k in KEYS},
        )  # fmt: skip
        base["事業所得の必要経費の内訳.tax"] = 10_000
        base["事業所得の必要経費の内訳.membership_dues"] = 20_000
        tax, misc = "経費/その他の経費/イ租税公課", "経費/その他の経費/レ雑費"
        default = fill_forms(values(**base, 事業所得の科目の割当ての選択="なし"), F, 2025).form("KOA110-01")
        self.assertEqual((default.field_at(tax).value, default.field_at(misc).value), (30_000, 0))
        moved = fill_forms(values(**base, 事業所得の科目の割当ての選択="membership_dues=other"), F, 2025).form("KOA110-01")
        self.assertEqual((moved.field_at(tax).value, moved.field_at(misc).value), (10_000, 20_000))
        self.assertIn("v:所得税.事業所得の科目の割当ての選択:p-1", moved.field_at(misc).value_ids)
        # 選択の矛盾（income_kinds が対象外にした）・未確定・読めない値は科目の欄を止める
        for value, states, status in (
            (None, (State.OUT_OF_SCOPE,), FieldStatus.OUT_OF_SCOPE),
            (None, (State.UNDETERMINED,), FieldStatus.UNDETERMINED),
            ("membership_dues=unknown_key", (), FieldStatus.OUT_OF_SCOPE),
        ):
            bad = rv("所得税.事業所得の科目の割当ての選択", value, states)
            f = fill_forms(values(**base, 事業所得の科目の割当ての選択=bad), F, 2025).form("KOA110-01").field_at(tax)
            self.assertEqual(f.status, status, value)

    def test_parse_errors(self) -> None:
        k = load_year(2025).kamoku
        form = {
            "帳票": "KOA110-01", "名称": "試験", "様式番号": "個12-0000", "様式の根拠": "試験", "記載事項の根拠": "試験",
            "出典": ["docs/public-sources/20261109_round2_yoshiki-forms-r07.md#7"], "使う型": ["通常"],
            "欄": [{"位置": "経費/a", "型": "金額", "対応": {"科目": "租税公課"}}],
        }  # fmt: skip
        with self.assertRaises(FormTableError):
            parse_form(form, "x.yaml", k)  # 科目の表・所得がない
        with self.assertRaises(FormTableError):
            parse_form({**form, "科目の表": "一般用", "所得": "事業所得", "欄": [{"位置": "経費/a", "型": "金額", "対応": {"科目": "存在しない科目"}}]}, "x.yaml", k)
        t = parse_form({**form, "科目の表": "一般用", "所得": "事業所得"}, "x.yaml", k)
        self.assertEqual(t.fields[0].mapping.kind, "科目")
        with self.assertRaises(FormTableError):  # 表ごとにちょうど1つの科目
            parse_kamoku({"出典": ["x"], "表": ["一般用"], "割当て": {"tax": {"一般用": "租税公課", "別": "x"}}}, KAMOKU_FILE)


class TestRows(unittest.TestCase):
    def test_spouse_row_needs_same_livelihood_or_special_deduction(self) -> None:
        a = assign_rows("配偶者や親族", 5, _family(spouse=SPOUSE, same=True), F)
        self.assertEqual((a.status, a.persons[0]), (ASSIGNED, SPOUSE))
        a = assign_rows("配偶者や親族", 5, _family(spouse=SPOUSE, same=False, special=0), F)
        self.assertIsNone(a.persons[0])
        a = assign_rows("配偶者や親族", 5, _family(spouse=SPOUSE, same=False, special=10_000), F)
        self.assertEqual(a.persons[0], SPOUSE)

    def test_relatives_order_filter_and_overflow(self) -> None:
        rel = (
            ("c-3", F, True, False, "2015-04-01"),  # 16歳未満の扶養親族も載せる
            ("c-1", F, True, False, "2000-01-01"),
            ("c-2", F, False, True, "2004-01-01"),  # 特定親族
            ("x-1", "p-9", True, False, "1999-01-01"),  # ほかの申告者の扶養親族
            ("x-2", F, False, False, "1998-01-01"),  # 扶養親族でも特定親族でもない
        )
        a = assign_rows("配偶者や親族", 5, _family(relatives=rel), F)
        self.assertEqual(a.persons, (None, "c-1", "c-2", "c-3", None))
        more = rel[:3] + (("c-4", F, True, False, "2016-01-01"), ("c-5", F, True, False, "2017-01-01"))
        a = assign_rows("配偶者や親族", 5, _family(relatives=more), F)
        self.assertEqual(a.persons[1:], ("c-1", "c-2", "c-3", "c-4"))
        self.assertEqual(a.overflow, ("c-5",))

    def test_missing_and_undetermined(self) -> None:
        a = assign_rows("配偶者や親族", 5, [rv("所得税.法律婚の相手", "なし", person=F)], F)
        self.assertEqual(a.status, MISSING)
        vals = _family(relatives=(("c-1", F, True, False, "2000-01-01"),))
        vals = [v for v in vals if not (v.person == "c-1" and v.concept == "所得税.扶養親族に当たるか")]
        vals.append(rv("所得税.扶養親族に当たるか", None, {State.UNDETERMINED}, person="c-1"))
        a = assign_rows("配偶者や親族", 5, vals, F)
        self.assertEqual((a.status, a.persons), (UNDETERMINED, (None,) * 5))

    def test_fill_reads_the_row_person(self) -> None:
        rel = (("c-1", F, False, True, "2004-05-06"),)
        vals = values() + _family(spouse=SPOUSE, same=True, relatives=rel) + [
            _d("1980-01-01", SPOUSE),
            rv("所得税.特定親族特別控除の1人分の額", 630_000, person="c-1"),
        ]  # fmt: skip
        res = fill_forms(vals, F, 2025)
        self.assertIsInstance(res, FormsResult)
        page = res.form("KOA020-02")
        b1, b2, b3 = (page.field_at(f"配偶者や親族/行{i}/生年月日") for i in (1, 2, 3))
        self.assertEqual((b1.subject, b1.value), (SPOUSE, _dt.date(1980, 1, 1)))
        self.assertEqual((b2.subject, b2.value), ("c-1", _dt.date(2004, 5, 6)))
        self.assertEqual(b3.status, FieldStatus.BLANK)
        n2 = page.field_at("配偶者や親族/行2/氏名")
        self.assertEqual((n2.status, n2.category, n2.subject), (FieldStatus.NO_CONCEPT, "事実", "c-1"))
        self.assertEqual(page.field_at("配偶者や親族/行2/特親").value, 630_000)
        self.assertEqual(page.row_assignment("配偶者や親族").persons[:2], (SPOUSE, "c-1"))

    def test_forecast_in_assignment_is_refused(self) -> None:
        vals = values() + _family(relatives=(("c-1", F, True, False, "2000-01-01"),))
        vals = [v for v in vals if not (v.person == "c-1" and v.concept == "所得税.扶養親族等とする申告者")]
        vals.append(rv("所得税.扶養親族等とする申告者", F, {State.FORECAST}, person="c-1"))
        self.assertFalse(fill_forms(vals, F, 2025).ok)


class TestBreakdown(unittest.TestCase):
    def test_moves_and_write(self) -> None:
        src, dst = Breakdown(), Breakdown()
        r1 = {"id": "e-1", "kind": "business_expense", "attributes": {"expense_category": "rent"}}
        r2 = {"id": "e-2", "kind": "payroll_paid", "attributes": {"pay_type": "professional_fee"}}
        src.add_record("rental", r1, 600)
        src.add_record("rental", r2, 300)
        src.move_records_to("rental", dst, "biz", {"e-1": 600, "e-2": 300}, ["e-1"])
        self.assertEqual(src.exp["rental"], {"rent": 0, "payroll_professional_fee": 300})
        self.assertEqual(dst.exp["biz"], {"rent": 600})
        src.add_rev("rental", "rent", 1_000)
        src.add_rev("rental", "key_money", 200)
        out = ModuleInputs()
        write_breakdown(out, "p", src, "rental", (1_500, 400), (), (), (), ())
        val = {k[0]: v.value for k, v in out.values.items()}
        self.assertEqual(val["所得税_不動産所得の必要経費の内訳_payroll_professional_fee"], 300)
        self.assertEqual(val["所得税_不動産所得の必要経費のうち内訳のない額"], 100)  # 400 − 300
        self.assertEqual(val["所得税_不動産所得の総収入金額のうち名義書換料・その他の金額"], 300)  # 1,500 − 1,000 − 200


def _calc(year: int, var: str, **vars_: Any) -> Any:
    situation = {"人物一覧": {"p": {v: {str(year): x} for v, x in vars_.items()}}}
    return SimulationBuilder().build_from_entities(system(), situation).calculate(var, str(year))[0]


class TestFilingConcepts(unittest.TestCase):
    ABROAD = "所得税_国外居住親族の区分"

    def _abroad(self, age: int, *, resident: bool = False, study: bool = False, disabled: bool = False, remit: int = 0) -> str:
        return str(
            _calc(
                2025, self.ABROAD,
                所得税_扶養等の判定に使う居住者か=resident, 所得税_扶養等の判定に使う年齢=age,
                所得税_扶養等の判定に使う留学により国内に住所及び居所を有しなくなった者か=study,
                所得税_国外居住親族の留学の区分の書類の要件を満たすか=study,
                所得税_扶養等の判定に使う障害者か=disabled,
                所得税_申告者から受けた生活費等の支払の額=remit,
                所得税_国外居住親族の38万円以上の区分の書類の要件を満たすか=remit > 0,
            )  # fmt: skip
        )

    def test_abroad_class_age_boundaries(self) -> None:
        self.assertEqual(self._abroad(40, resident=True), "居住者")
        self.assertEqual(self._abroad(15), "16歳未満")
        self.assertEqual(self._abroad(16), "16歳以上30歳未満又は70歳以上")
        self.assertEqual(self._abroad(29), "16歳以上30歳未満又は70歳以上")
        self.assertEqual(self._abroad(30), "該当なし")
        self.assertEqual(self._abroad(69), "該当なし")
        self.assertEqual(self._abroad(70), "16歳以上30歳未満又は70歳以上")

    def test_abroad_class_30_to_69(self) -> None:
        self.assertEqual(self._abroad(30, disabled=True, study=True, remit=380_000), "障害者")
        self.assertEqual(self._abroad(30, study=True), "留学")
        self.assertEqual(self._abroad(30, remit=380_000), "38万円以上")
        self.assertEqual(self._abroad(30, remit=379_999), "該当なし")
        self.assertEqual(self._abroad(30, study=True, remit=380_000), "留学及び38万円以上")

    def test_medical_threshold(self) -> None:
        e, f = "所得税_医療費控除の足切りの基準の額", "所得税_医療費控除の足切りの額"
        self.assertEqual(int(_calc(2025, e, 所得税_総所得金額等=2_000_000)), 100_000)
        self.assertEqual(int(_calc(2025, f, 所得税_総所得金額等=2_000_020)), 100_000)
        self.assertEqual(int(_calc(2025, e, 所得税_総所得金額等=2_000_020)), 100_001)
        self.assertEqual(int(_calc(2025, e, 所得税_総所得金額等=-500_000)), 0)
        self.assertEqual(int(_calc(2025, e, 所得税_総所得金額等=1_000_010, 所得税_医療費控除の足切りの端数="ceil")), 50_001)


if __name__ == "__main__":
    unittest.main()
