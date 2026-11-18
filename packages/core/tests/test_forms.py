"""様式の欄の対応表（okura_core.forms）のユニットテスト。

- 対応表のデータ：年分の一覧、帳票の一覧、概念 ID の実在と値の型、出典（docs のファイル#節）の実在、読み込みの検査。
- 欄の値の生成（fill_forms）：上流の判定コアの値はスタブ（ResultValue を直接作る）。変換（そのまま・合計・条件）の代表例、
  状態（予測は出さない・見積りは印・計画は条件・未確定は幅・対象外）、令和8年分の拒否、様式の式と単位の検査、申告の型。
テストのデータは架空の値だけ。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from okura_core.concepts import load_dictionary
from okura_core.forms import (
    FieldStatus,
    FormsRefusal,
    FormsResult,
    FormTableError,
    RefusalCategory,
    YearTables,
    check_against_dictionary,
    determine_filing_type,
    fill_forms,
    load_index,
    load_year,
    parse_form,
)
from okura_core.money import YenRange
from okura_core.result import (
    Category,
    Flag,
    Means,
    OutOfScopeCategory,
    OutOfScopeReason,
    ResultValue,
    Split,
    State,
    TimeKey,
    Undetermined,
    YenAmount,
)

from .support import REPO

YEAR = 2025
T = TimeKey("tax_year", YEAR)
P = "p-1"

#: 申告の型を「通常」にする値（determine_filing_type が読む概念）。
TYPE_ZEROS = (
    "所得税.純損失の金額",
    "所得税.翌年以後に繰り越す雑損失の金額",
    "所得税.繰り越された純損失の金額",
    "所得税.純損失の繰越控除額",
    "所得税.繰り越された雑損失の金額",
    "所得税.雑損失の繰越控除額",
    "所得税.退職所得の金額",
    "所得税.上場株式等に係る配当所得等の金額",
    "所得税.上場株式等に係る譲渡所得等の金額",
    "所得税.上場株式等の譲渡損失の繰越控除額",
)

EXPECTED_FORMS = {
    "KOA020-01", "KOA020-02", "KOA020-03", "KOA020-04", "KOA020-05",
    "KOA110-01", "KOA110-02", "KOA130-01", "KOA130-02",
    "KOA210-01", "KOA210-02", "KOA210-03", "KOA210-04",
    "KOA220-01", "KOA220-02", "KOA220-03", "KOA220-04",
    "KOB560-01", "KOB565-01", "KOB570-01", "KOB575-01",
    "KOB070-01", "KOB070-02", "KOB070-03", "KOB070-04",  # 給与所得者の特定支出に関する明細書（2026-11-12 の3回目）
}  # fmt: skip


def _undetermined() -> Undetermined:
    return Undetermined(splits=(Split("s-1", Means.JUDGMENT, {"kind": "試験"}, ("a", "b"), True),), outcomes=())


def rv(concept: str, value, states=(), *, person: str = P, time: TimeKey = T, scope: bool = True, vid: str | None = None) -> ResultValue:
    """判定コアの値のスタブ。value は int（円）・YenRange・bool・str（区分）・None。"""
    states = frozenset(states)
    if isinstance(value, bool):
        v = Flag(value)
    elif isinstance(value, int):
        v = YenAmount(value)
    elif isinstance(value, str):
        v = Category(value)
    else:
        v = value
    oos = OutOfScopeReason(OutOfScopeCategory.NOT_IMPLEMENTED, "試験の対象外") if State.OUT_OF_SCOPE in states else None
    und = _undetermined() if State.UNDETERMINED in states and State.OUT_OF_SCOPE not in states else None
    return ResultValue(
        id=vid or f"v:{concept}:{person}",
        concept=concept,
        variable=None,
        person=person,
        time=time,
        value=v,
        states=states,
        basis=(),
        undetermined=und,
        out_of_scope=oos,
        filing_scope=scope,
    )


def values(**overrides) -> list[ResultValue]:
    """申告の型が「通常」になる値に、概念 → 値 か 概念 → ResultValue を足す（キーは概念 ID の「所得税.」の後ろ）。"""
    out = {c: rv(c, 0) for c in TYPE_ZEROS}
    for k, v in overrides.items():
        c = "所得税." + k
        out[c] = v if isinstance(v, ResultValue) else rv(c, v)
    return list(out.values())


def first_table(res) -> object:
    assert isinstance(res, FormsResult), res
    return res.form("KOA020-01")


_HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*$")


def reference_problem(ref: str) -> str | None:
    """出典（ファイル#節）が実在するか（test_architecture の規則と同じ：見出しが節の文字列で始まり、続きが英数字・「.数字」でない）。"""
    path, _, anchor = ref.partition("#")
    if not path or ".." in Path(path).parts or Path(path).is_absolute():
        return f"相対パスでない: {ref}"
    file = REPO / path
    if not file.is_file():
        return f"ファイルがない: {ref}"
    if anchor:
        heads = [m.group(1) for line in file.read_text(encoding="utf-8").splitlines() if (m := _HEADING.match(line))]
        for h in heads:
            rest = h[len(anchor):]
            if h.startswith(anchor) and (rest == "" or (not (rest[0].isascii() and rest[0].isalnum()) and re.match(r"\.[0-9]", rest) is None)):
                return None
        return f"節の見出しがない: {ref}"
    return None


# ---------------------------------------------------------------------------
# 対応表のデータ
# ---------------------------------------------------------------------------


class TestTables(unittest.TestCase):
    def test_years(self) -> None:
        self.assertEqual(load_year(YEAR).status, "公表済み")
        r08 = load_year(2026)
        self.assertEqual((r08.status, r08.forms), ("未公表", ()))
        self.assertIsNone(load_year(2024))
        self.assertEqual(sorted(load_index()), [2025, 2026])

    def test_forms_of_r07(self) -> None:
        self.assertEqual({f.form for f in load_year(YEAR).forms}, EXPECTED_FORMS)

    def test_concepts_exist_and_types_match(self) -> None:
        """対応表が使う概念 ID が概念辞書に実在し、所得税の人ごと・年ごとの実装済みの概念で、欄・条件の型と合う。"""
        problems = check_against_dictionary(load_year(YEAR), load_dictionary())
        self.assertEqual(problems, [], "\n".join(problems))

    def test_check_against_dictionary_finds_errors(self) -> None:
        bad = parse_form(
            {
                "帳票": "KOA999-01",
                "名称": "試験",
                "様式番号": "個0",
                "様式の根拠": "試験",
                "記載事項の根拠": "試験",
                "出典": ["docs/x.md"],
                "使う型": ["通常"],
                "欄": [
                    {"位置": "a", "型": "金額", "対応": {"そのまま": "所得税.ない概念"}},
                    {"位置": "b", "型": "金額", "対応": {"そのまま": "所得税.青色申告の承認を受けているか"}},
                    {"位置": "c", "型": "金額", "対応": {"場合": [{"もし": [{"概念": "所得税.扶養控除の額", "判定": "真"}], "値": 0}]}},
                ],
            }
        )
        t = YearTables(YEAR, "公表済み", ("docs/x.md",), (bad,))
        problems = check_against_dictionary(t, load_dictionary())
        self.assertEqual(len(problems), 3, problems)
        self.assertIn("概念辞書にない", problems[0])

    def test_check_against_dictionary_allows_resident_tax_year_concepts(self) -> None:
        """住民税の人ごと・年ごとの概念は欄に写せる（年分＋1 の年度の値として読む）。ほかの制度（国保）は写せない。"""
        form = parse_form(
            {
                "帳票": "KOA999-01",
                "名称": "試験",
                "様式番号": "個0",
                "様式の根拠": "試験",
                "記載事項の根拠": "試験",
                "出典": ["docs/x.md"],
                "使う型": ["通常"],
                "欄": [
                    {"位置": "a", "型": "金額", "対応": {"そのまま": "住民税.第二表の特例控除対象の寄附金の額"}},
                    {"位置": "b", "型": "印", "対応": {"そのまま": "国保.被保険者か"}},
                ],
            }
        )
        problems = check_against_dictionary(YearTables(YEAR, "公表済み", ("docs/x.md",), (form,)), load_dictionary())
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("国保.被保険者か", problems[0])

    def test_references_exist(self) -> None:
        refs = [r for entry in load_index().values() for r in entry["出典"]]
        for t in load_year(YEAR).forms:
            refs += list(t.references) + list(t.hypotheses)
            refs += [r for f in t.fields for r in f.references]
        for ref in sorted(set(refs)):
            with self.subTest(ref=ref):
                self.assertIsNone(reference_problem(ref))

    def test_positions_and_codes_are_unique_per_form(self) -> None:
        for t in load_year(YEAR).forms:
            positions = [f.position for f in t.fields]
            codes = [f.code for f in t.fields if f.code]
            with self.subTest(form=t.form):
                self.assertEqual(len(positions), len(set(positions)))
                self.assertEqual(len(codes), len(set(codes)))

    def test_first_table_codes(self) -> None:
        """第一表の代表的な欄の位置名 → 欄コード（output-forms-and-specs §2.2）。"""
        t = load_year(YEAR).form("KOA020-01")
        expect = {
            "所得金額等/合計": ("⑫", "G50"),
            "所得控除/扶養": ("㉓", "G58"),
            "所得控除/特定親族特別": ("㉔", "G110"),
            "税金の計算/課税される所得金額": ("㉛", "G65"),
            "税金の計算/第3期分の税額/納める税金": ("52", "G81"),
        }
        for pos, (num, code) in expect.items():
            with self.subTest(pos=pos):
                f = t.field_at(pos)
                self.assertEqual((f.number, f.code), (num, code))
        self.assertEqual(t.field_at("所得控除/扶養").unit, 10000)
        self.assertEqual(t.field_at("税金の計算/課税される所得金額").unit, 1000)

    def test_expansion_of_rows_and_columns(self) -> None:
        t = parse_form(
            {
                "帳票": "KOA999-01",
                "名称": "試験",
                "様式番号": "個0",
                "様式の根拠": "試験",
                "記載事項の根拠": "試験",
                "出典": ["docs/x.md"],
                "使う型": ["通常"],
                "欄": [
                    {"位置": "行{行}/{列}", "行": 2, "列": ["甲", "乙"], "コード": [["E01", "G01"], ["E02", None]], "型": "金額",
                     "対応": {"なし": "事実", "理由": "試験"}},
                ],
            }
        )  # fmt: skip
        self.assertEqual([(f.position, f.code, f.row) for f in t.fields], [("行1/甲", "E01", 1), ("行1/乙", "G01", 1), ("行2/甲", "E02", 2)])

    def test_parse_errors(self) -> None:
        base = {
            "帳票": "KOA999-01",
            "名称": "試験",
            "様式番号": "個0",
            "様式の根拠": "試験",
            "記載事項の根拠": "試験",
            "出典": ["docs/x.md"],
            "使う型": ["通常"],
        }
        cases = {
            "知らないキー": {**base, "欄": [{"位置": "a", "型": "金額", "対応": {"値": 0}, "謎": 1}]},
            "結果が2つ": {**base, "欄": [{"位置": "a", "型": "金額", "対応": {"値": 0, "空欄": "x"}}]},
            "欄コードの重複": {**base, "欄": [{"位置": "a", "コード": "G01", "型": "金額", "対応": {"値": 0}},
                                          {"位置": "b", "コード": "G01", "型": "金額", "対応": {"値": 0}}]},
            "位置の重複": {**base, "欄": [{"位置": "a", "型": "金額", "対応": {"値": 0}}, {"位置": "a", "型": "金額", "対応": {"値": 0}}]},
            "知らない判定": {**base, "欄": [{"位置": "a", "型": "金額", "対応": {"場合": [{"もし": [{"概念": "所得税.x", "判定": "大"}], "値": 0}]}}]},
            "単位": {**base, "欄": [{"位置": "a", "型": "金額", "単位": 7, "対応": {"値": 0}}]},
            "検査の位置": {**base, "欄": [{"位置": "a", "型": "金額", "対応": {"値": 0}}], "検査": [{"式": "合計", "左": "a", "右": ["z"]}]},
        }  # fmt: skip
        for name, data in cases.items():
            with self.subTest(case=name), self.assertRaises(FormTableError):
                parse_form(data)


# ---------------------------------------------------------------------------
# 欄の値の生成
# ---------------------------------------------------------------------------


class TestFillTransforms(unittest.TestCase):
    def test_copy(self) -> None:
        f = first_table(fill_forms(values(扶養控除の額=630000), P, YEAR)).field_at("所得控除/扶養")
        self.assertEqual((f.status, f.value, f.code, f.mapping_kind), (FieldStatus.OUTPUT, 630000, "G58", "そのまま"))
        self.assertEqual(f.value_ids, ("v:所得税.扶養控除の額:p-1",))
        self.assertIn("個12-1072", f.basis.law or "")
        self.assertTrue(f.basis.references)

    def test_sum(self) -> None:
        """⑲⑳：勤労学生控除と障害者控除の合計（手引き 3-3_15_2）。"""
        f = first_table(fill_forms(values(勤労学生控除の額=270000, 障害者控除の額=400000), P, YEAR)).field_at("所得控除/勤労学生・障害者")
        self.assertEqual((f.status, f.value, f.mapping_kind), (FieldStatus.OUTPUT, 670000, "合計"))
        self.assertEqual(len(f.value_ids), 2)

    def test_condition_category(self) -> None:
        """⑰⑱の区分（G17）：ひとり親控除なら「1」、そうでなければ空欄。"""
        on = first_table(fill_forms(values(ひとり親控除の額=350000), P, YEAR)).field_at("所得控除/寡婦・ひとり親/区分")
        off = first_table(fill_forms(values(ひとり親控除の額=0), P, YEAR)).field_at("所得控除/寡婦・ひとり親/区分")
        self.assertEqual((on.status, on.value), (FieldStatus.OUTPUT, "1"))
        self.assertEqual((off.status, off.value), (FieldStatus.BLANK, None))

    def test_condition_selects_concept(self) -> None:
        """㉘：セルフメディケーション税制を選んだらその額、選ばなければ医療費控除の額。区分 G21 も選択で決まる。"""
        common = dict(医療費控除の額=150000, セルフメディケーション税制による医療費控除の額=20000)
        self_med = first_table(fill_forms(values(セルフメディケーション税制の選択=True, **common), P, YEAR))
        medical = first_table(fill_forms(values(セルフメディケーション税制の選択=False, **common), P, YEAR))
        self.assertEqual(self_med.field_at("所得控除/医療費").value, 20000)
        self.assertEqual(self_med.field_at("所得控除/医療費/区分").value, "1")
        self.assertEqual(medical.field_at("所得控除/医療費").value, 150000)
        self.assertIs(medical.field_at("所得控除/医療費/区分").status, FieldStatus.BLANK)

    def test_condition_on_category_value(self) -> None:
        """申告の種類（G01）：第120条の確定申告は「1」。準確定の書き分けは一次情報が足りないので未確定。"""
        ok = first_table(fill_forms(values(申告の種類="第120条"), P, YEAR)).field_at("見出し/申告の種類")
        other = first_table(fill_forms(values(申告の種類="第125条"), P, YEAR)).field_at("見出し/申告の種類")
        self.assertEqual(ok.value, "1")
        self.assertEqual((other.status, other.category), (FieldStatus.UNDETERMINED, "一次情報"))

    def test_query_year_and_no_concept(self) -> None:
        t = first_table(fill_forms(values(), P, YEAR))
        self.assertEqual(t.field_at("見出し/年分").value, "7")
        mynumber = t.field_at("見出し/個人番号")
        self.assertEqual((mynumber.status, mynumber.value), (FieldStatus.NOT_OUTPUT, None))
        # 対応する概念がない欄（外国税額控除は範囲外：D20）。㊴〜㊶ は 2026-11-12 に外部で計算した額の概念に写した（結果に値がなければ値なし）
        foreign = t.field_at("税金の計算/外国税額控除等")
        self.assertEqual((foreign.status, foreign.category), (FieldStatus.NO_CONCEPT, "対象外"))
        credit = t.field_at("税金の計算/住宅耐震改修特別控除等")
        self.assertIs(credit.status, FieldStatus.MISSING)

    def test_missing_value(self) -> None:
        f = first_table(fill_forms(values(), P, YEAR)).field_at("所得控除/扶養")
        self.assertIs(f.status, FieldStatus.MISSING)
        self.assertIn("所得税.扶養控除の額", f.reason or "")

    def test_other_person_and_year_are_ignored(self) -> None:
        vs = values(扶養控除の額=380000) + [
            rv("所得税.扶養控除の額", 999, person="p-2", vid="x1"),
            rv("所得税.扶養控除の額", 999, time=TimeKey("tax_year", 2026), vid="x2"),
        ]
        self.assertEqual(first_table(fill_forms(vs, P, YEAR)).field_at("所得控除/扶養").value, 380000)

    def test_resident_tax_field_reads_the_next_fiscal_year(self) -> None:
        """第二表の寄附 G32：住民税の概念は年分＋1 の年度の申告者の値を写す。年分の値・ほかの年度・ほかの人の値は読まない（値なし）。"""
        cid = "住民税.第二表の特例控除対象の寄附金の額"
        pos = "住民税/都道府県・市区町村への寄附（特例控除対象）"

        def g32(extra: list[ResultValue]) -> object:
            res = fill_forms(values() + extra, P, YEAR)
            assert isinstance(res, FormsResult), res
            return res.form("KOA020-02").field_at(pos)

        f = g32([rv(cid, 120000, time=TimeKey("fiscal_year", YEAR + 1), vid="j1")])
        self.assertEqual((f.status, f.value, f.code, f.value_ids), (FieldStatus.OUTPUT, 120000, "G32", ("j1",)))
        others = [
            rv(cid, 1, time=T, vid="x1"),
            rv(cid, 2, time=TimeKey("fiscal_year", YEAR), vid="x2"),
            rv(cid, 3, time=TimeKey("fiscal_year", YEAR + 1), person="p-2", vid="x3"),
        ]
        missing = g32(others)
        self.assertIs(missing.status, FieldStatus.MISSING)
        self.assertIn(cid, missing.reason or "")


class TestFillStates(unittest.TestCase):
    def test_forecast_is_refused(self) -> None:
        """予測を含む値（申告の範囲）があれば、その申告者・年分の欄を出さない（D19）。"""
        res = fill_forms(values(給与等の収入金額=rv("所得税.給与等の収入金額", 3_000_000, {State.FORECAST})), P, YEAR)
        self.assertIsInstance(res, FormsRefusal)
        self.assertIs(res.category, RefusalCategory.FORECAST)
        self.assertEqual(res.blocking_value_ids, ("v:所得税.給与等の収入金額:p-1",))

    def test_forecast_in_a_used_value_outside_filing_scope_is_refused(self) -> None:
        r = rv("所得税.事業所得の総収入金額", 1_000_000, {State.FORECAST}, scope=False)
        res = fill_forms(values(事業所得の総収入金額=r), P, YEAR)
        self.assertIs(res.category, RefusalCategory.FORECAST)

    def test_estimate_is_marked(self) -> None:
        f = first_table(fill_forms(values(扶養控除の額=rv("所得税.扶養控除の額", 380000, {State.ESTIMATE})), P, YEAR)).field_at("所得控除/扶養")
        self.assertEqual((f.status, f.value, f.marks), (FieldStatus.OUTPUT, 380000, frozenset({State.ESTIMATE})))
        self.assertEqual(f.conditions, ("法令が求める見積りによる値（見積り）",))

    def test_plan_is_conditional(self) -> None:
        f = first_table(fill_forms(values(青色申告特別控除額=rv("所得税.青色申告特別控除額", 650000, {State.PLAN})), P, YEAR)).field_at(
            "その他/青色申告特別控除額"
        )
        self.assertEqual((f.status, f.value), (FieldStatus.OUTPUT, 650000))
        self.assertEqual(f.conditions, ("申告の計画どおりに申告すること（計画）",))
        self.assertEqual(f.to_dict()["marks"], ["計画"])

    def test_undetermined_keeps_the_range(self) -> None:
        r = rv("所得税.医療費控除の額", YenRange(10000, 10001), {State.UNDETERMINED})
        f = first_table(fill_forms(values(医療費控除の額=r, セルフメディケーション税制の選択=False), P, YEAR)).field_at("所得控除/医療費")
        self.assertEqual((f.status, f.value), (FieldStatus.UNDETERMINED, YenRange(10000, 10001)))
        self.assertEqual(f.value_ids, ("v:所得税.セルフメディケーション税制の選択:p-1", "v:所得税.医療費控除の額:p-1"))

    def test_range_in_a_sum(self) -> None:
        r = rv("所得税.障害者控除の額", YenRange(270000, 400000), {State.UNDETERMINED})
        f = first_table(fill_forms(values(勤労学生控除の額=270000, 障害者控除の額=r), P, YEAR)).field_at("所得控除/勤労学生・障害者")
        self.assertEqual((f.status, f.value), (FieldStatus.UNDETERMINED, YenRange(540000, 670000)))

    def test_undetermined_condition(self) -> None:
        r = rv("所得税.セルフメディケーション税制の選択", None, {State.UNDETERMINED})
        f = first_table(fill_forms(values(セルフメディケーション税制の選択=r, 医療費控除の額=1), P, YEAR)).field_at("所得控除/医療費")
        self.assertEqual((f.status, f.value, f.category), (FieldStatus.UNDETERMINED, None, "条件"))

    def test_out_of_scope(self) -> None:
        r = rv("所得税.扶養控除の額", None, {State.OUT_OF_SCOPE})
        f = first_table(fill_forms(values(扶養控除の額=r), P, YEAR)).field_at("所得控除/扶養")
        self.assertIs(f.status, FieldStatus.OUT_OF_SCOPE)
        self.assertIn("試験の対象外", f.reason or "")

    def test_r08_is_refused_as_unpublished(self) -> None:
        res = fill_forms(values(), P, 2026)
        self.assertIsInstance(res, FormsRefusal)
        self.assertEqual((res.category, res.means), (RefusalCategory.UNPUBLISHED, Means.AWAITING_PUBLICATION))
        self.assertTrue(res.references)

    def test_other_years_are_out_of_years(self) -> None:
        self.assertIs(fill_forms([], P, 2024).category, RefusalCategory.OUT_OF_YEARS)


class TestFillChecks(unittest.TestCase):
    def test_unit_mismatch_is_refused(self) -> None:
        """㉓ は万円単位の印字（0000）。端数のある値は判定コアと様式の食い違い。"""
        res = fill_forms(values(扶養控除の額=380001), P, YEAR)
        self.assertIs(res.category, RefusalCategory.MISMATCH)
        self.assertIn("所得控除/扶養", res.problems[0])

    def test_unit_is_in_output(self) -> None:
        """2026-11-13：欄の単位を出力に出す（値は円、欄に書くのは値 ÷ 単位。作成コーナーとの照合 A01 の D4）。"""
        page = fill_forms(values(扶養控除の額=380_000), P, YEAR).form("KOA020-01")
        f = page.field_at("所得控除/扶養")
        self.assertEqual((f.value, f.unit, f.to_dict()["unit"]), (380_000, 10000, 10000))
        self.assertEqual(page.field_at("収入金額等/給与").to_dict()["unit"], 1)

    def test_printed_formula_mismatch_is_refused(self) -> None:
        """⑩＝⑦＋⑧＋⑨（様式の印字）。"""
        vs = values(公的年金等に係る雑所得の金額=100, 業務に係る雑所得の金額=200, その他の雑所得の金額=300, 雑所得の金額=601)
        self.assertIs(fill_forms(vs, P, YEAR).category, RefusalCategory.MISMATCH)
        vs = values(公的年金等に係る雑所得の金額=100, 業務に係る雑所得の金額=200, その他の雑所得の金額=300, 雑所得の金額=600)
        self.assertIsInstance(fill_forms(vs, P, YEAR), FormsResult)

    def test_difference_formula(self) -> None:
        """収支内訳書（一般用）㉑＝⑲－⑳。⑲ は 事業所得の金額＋事業専従者控除額 の合計で写す。"""
        common = dict(
            青色申告の承認を受けているか=False,
            事業所得の総収入金額=5_000_000,
            事業所得の必要経費=1_000_000,
            家内労働者等か=False,
            事業所得の事業専従者控除額=500_000,
        )
        res = fill_forms(values(事業所得の金額=3_500_000, **common), P, YEAR)
        page = res.form("KOA110-01")
        self.assertEqual(page.field_at("専従者控除前の所得金額").value, 4_000_000)
        self.assertEqual(page.field_at("所得金額").value, 3_500_000)


class TestFilingTypeAndForms(unittest.TestCase):
    @staticmethod
    def by_concept(vs: list[ResultValue]) -> dict[str, ResultValue]:
        return {v.concept: v for v in vs}

    def test_types(self) -> None:
        self.assertEqual(determine_filing_type(self.by_concept(values())).value, "通常")
        self.assertEqual(determine_filing_type(self.by_concept(values(純損失の金額=100))).value, "損失申告")
        self.assertEqual(determine_filing_type(self.by_concept(values(上場株式等に係る配当所得等の金額=100))).value, "第三表あり")
        remaining = determine_filing_type(self.by_concept(values(繰り越された純損失の金額=100, 純損失の繰越控除額=40)))
        self.assertIsNone(remaining.value)
        self.assertIn("翌年以後に繰り越すか", remaining.reason or "")
        self.assertIsNone(determine_filing_type({}).value)

    def test_blank_in_loss_return(self) -> None:
        """損失申告では第一表 ⑫・㉛ を記入しない（手引き 損失申告用 p.5）。第三表は出さず第四表を出す。"""
        res = fill_forms(values(純損失の金額=1_000_000, 総所得金額=0), P, YEAR)
        t = first_table(res)
        self.assertIs(t.field_at("所得金額等/合計").status, FieldStatus.BLANK)
        self.assertEqual(t.field_at("見出し/損失").value, "1")
        forms = {f.form for f in res.forms}
        self.assertIn("KOA020-04", forms)
        self.assertNotIn("KOA020-03", forms)

    def test_forms_by_use_conditions(self) -> None:
        white = fill_forms(values(青色申告の承認を受けているか=False, 事業所得の総収入金額=1, 事業所得の必要経費=0), P, YEAR)
        blue = fill_forms(values(青色申告の承認を受けているか=True, 事業所得の総収入金額=1, 事業所得の必要経費=0), P, YEAR)
        self.assertIn("KOA110-01", {f.form for f in white.forms})
        self.assertNotIn("KOA210-01", {f.form for f in white.forms})
        self.assertIn("KOA210-01", {f.form for f in blue.forms})
        self.assertIn(("KOB565-01", "使うかは入力の事実（明細の行の数など）で決まる。利用アプリが決める"), white.not_produced)

    def test_to_dict(self) -> None:
        res = fill_forms(values(扶養控除の額=380000), P, YEAR)
        d = res.to_dict()
        self.assertTrue(d["ok"])
        self.assertEqual(d["filing_type"]["value"], "通常")
        first = next(f for f in d["forms"] if f["form"] == "KOA020-01")
        row = next(x for x in first["fields"] if x["position"] == "所得控除/扶養")
        self.assertEqual((row["value"], row["status"], row["code"]), (380000, "出力", "G58"))
        self.assertFalse(fill_forms([], P, 2026).to_dict()["ok"])


if __name__ == "__main__":
    unittest.main()
