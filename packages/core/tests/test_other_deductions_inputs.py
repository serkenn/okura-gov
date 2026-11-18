"""規則モジュール other_deductions の前処理（中間表現 → 支払者の入力変数）と親族の判定。テストのデータは架空の家庭（個人の情報を使わない）。

期待値の出典：医療費の場面は docs/measurements/20261109_impl-prep_iryohi-verification.md §5.1（S3・S3-3〜S3-6 の再計算）、
docs/public-sources/20261109_impl-prep_iryohi-nta-mhlw.md、保険・寄附は docs/public-sources/20261109_round2_hoken-kifu-laws.md、
社会保険料は docs/public-sources/20261109_impl-prep_zeigaku-tax-calc.md §7。
"""

from __future__ import annotations

import datetime as _dt
import unittest
from types import SimpleNamespace
from typing import Any

import okura_ir

from okura_core.registry import Decided, ModuleInputs, YearContext, YearWindow, alive_in_year
from okura_core.result import State
from okura_core.rules.other_deductions import MODULE
from okura_core.rules.other_deductions.inputs import build_inputs
from okura_core.rules.other_deductions.kinship import kinship, relation_index
from okura_core.situation import resolve_decisions

from .support import make_ir, person

V_MED = "所得税_補塡後の医療費の額"
V_SELF = "所得税_特定一般用医薬品等購入費の額"
V_CHOICE = "所得税_セルフメディケーション税制の選択"
V_SOCIAL = "所得税_支払った社会保険料の額"
V_MUTUAL = "所得税_支払った小規模企業共済等掛金の額"
V_NEW = "所得税_新生命保険料の額"
V_OLD = "所得税_旧生命保険料の額"
V_CARE = "所得税_介護医療保険料の額"
V_NEW_A = "所得税_新個人年金保険料の額"
V_REGIME = "所得税_生命保険料の新旧の選択"
V_QUAKE = "所得税_地震保険料の額"
V_LONG = "所得税_旧長期損害保険料の額"
V_DON = "所得税_特定寄附金の額"
J_SEIKEI = "判断.生計を一にする"
J_RANGE = "判断.医療費の範囲"

#: このモジュールの判断・選択の1か所だけを解く（前処理を単独で確かめる。ほかのモジュールの宣言に結びつけない）。
_ONLY_THIS_MODULE = SimpleNamespace(modules=(MODULE,))


def run(ir: dict[str, Any], year: int, pick: dict[str, Any] | None = None, *, rounding: str = "floor") -> ModuleInputs:
    """中間表現を検査し、判断・選択を決めて build_inputs を呼ぶ。未入力の1か所は pick（分かれ目の ID → 値）か、最初の候補。
    根拠のない端数（RoundingSlotSpec(variable=None)）の候補は rounding。"""
    problems = okura_ir.validate(ir)
    assert problems == [], problems
    alive = tuple(p["id"] for p in ir["persons"] if alive_in_year(p, year))
    base = YearContext(ir, year, alive)
    decisions = resolve_decisions(base, _ONLY_THIS_MODULE)
    decided = dict(decisions.fixed)
    for slot in decisions.open:
        value = (pick or {}).get(slot.id, slot.candidates[0].value)
        decided[decisions.slot_keys[slot.id]] = Decided(value, (), frozenset(), open=True)
    window = YearWindow(rounding={sp.name: rounding for sp in MODULE.roundings if sp.variable is None})
    return build_inputs(YearContext(ir, year, alive, decided, window=window))


def open_slots(ir: dict[str, Any], year: int) -> set[str]:
    alive = tuple(p["id"] for p in ir["persons"] if alive_in_year(p, year))
    return {s.id for s in resolve_decisions(YearContext(ir, year, alive), _ONLY_THIS_MODULE).open}


def val(out: ModuleInputs, var: str, pid: str) -> Any:
    return out.values[(var, pid)].value


def reasons(out: ModuleInputs, var: str, pid: str) -> list[str]:
    return [e.reason.reason for e in out.exclusions if e.variable == var and e.person == pid]


def missing(out: ModuleInputs, var: str, pid: str) -> list[str]:
    """入力の未確定の分かれ目（一次情報・語彙にない事実で決まらない読み）の決める手段。"""
    return [s.means.value for s in out.values[(var, pid)].missing]


def judgment(jid: str, kind: str, subject: dict[str, Any], value: Any, *, when: dict[str, Any] | None = None, mark: str | None = None) -> dict[str, Any]:
    j: dict[str, Any] = {
        "id": jid,
        "kind": kind,
        "judged_by": {"label": "架空の判断者"},
        "judged_at": "2026-03-01T09:00:00+09:00",
        "subject": subject,
        "value": value,
    }
    if when is not None:
        j["when"] = when
    if mark is not None:
        j["mark"] = mark
    return j


def choice(cid: str, kind: str, chooser: str, subject: dict[str, Any], value: Any, when: dict[str, Any] | None = None) -> dict[str, Any]:
    c: dict[str, Any] = {"id": cid, "kind": kind, "chosen_by": chooser, "chosen_at": "2026-03-02T09:00:00+09:00", "subject": subject, "value": value}
    if when is not None:
        c["when"] = when
    return c


def seikei(jid: str, a: str, b: str, from_on: str, to_on: str | None = None, value: bool = True) -> dict[str, Any]:
    when: dict[str, Any] = {"from_on": from_on}
    if to_on:
        when["to_on"] = to_on
    return judgment(jid, J_SEIKEI, {"person": a, "other_person": b}, value, when=when)


def medical(rid: str, payer: str, patient: str, paid: str, incurred: str, amount: int, kinds: tuple[str, ...] = ("medical_treatment",), **attrs: Any) -> dict[str, Any]:
    return {
        "id": rid,
        "kind": "medical_payment",
        "roles": {"payer": payer, "patient": patient},
        "when": {"on": paid},
        "amounts": {"amount": amount},
        "attributes": {"incurred_on": incurred, "medical_kinds": list(kinds), **attrs},
    }


def reimbursement(rid: str, recipient: str, on: str, amount: int, targets: tuple[str, ...] | None, benefit: str = "hospitalization_benefit") -> dict[str, Any]:
    attrs: dict[str, Any] = {"benefit_type": benefit}
    if targets is not None:
        attrs["target_payment_ids"] = list(targets)
    return {"id": rid, "kind": "reimbursement", "roles": {"recipient": recipient}, "when": {"on": on}, "amounts": {"amount": amount}, "attributes": attrs}


def parentage(rid: str, parent: str, child: str, on: str = "1960-01-01") -> dict[str, Any]:
    return {"id": rid, "kind": "parentage", "roles": {"parent": parent, "child": child}, "when": {"on": on}, "attributes": {"basis": "birth_mother"}}


def marriage(rid: str, a: str, b: str, from_on: str, to_on: str | None = None, **attrs: Any) -> dict[str, Any]:
    when: dict[str, Any] = {"from_on": from_on}
    if to_on:
        when["to_on"] = to_on
    rec: dict[str, Any] = {"id": rid, "kind": "marriage", "roles": {"spouse_a": a, "spouse_b": b}, "when": when}
    if attrs:
        rec["attributes"] = attrs
    return rec


def s3_family(**over: Any) -> dict[str, Any]:
    """docs/inferences/20261109_R4-modeling_scenarios.md の S3（令和7年分）の架空の家庭。期待値は 実測 …iryohi-verification.md §5.1。"""
    facts = [
        medical("p1", "p-f", "p-c", "2025-06-30", "2025-06-10", 120_000, ("hospitalization",)),
        reimbursement("u1", "p-f", "2025-07-15", 150_000, ("p1",)),
        medical("p2", "p-f", "p-f", "2025-09-05", "2025-09-05", 180_000),
        medical("p3", "p-f", "p-g", "2025-10-15", over.get("p3_incurred", "2025-09-20"), 60_000),
        medical("p4", "p-m", "p-c", "2025-07-20", "2025-07-20", 50_000),
        medical("p5", "p-m", "p-m", "2025-08-20", "2025-08-20", 40_000),
    ]
    judgments = [
        seikei("j-fc", "p-f", "p-c", "2025-01-01", "2025-12-31"),
        seikei("j-mc", "p-m", "p-c", "2025-01-01", "2025-12-31"),
        seikei("j-fg", "p-f", "p-g", "2025-01-01", "2025-09-30"),
        seikei("j-fg2", "p-f", "p-g", "2025-10-01", "2025-12-31", value=False),  # 10月に施設へ入り独立（S3 の入力）
    ]
    return make_ir(
        [person("p-f", "1970-01-01"), person("p-m", "1972-01-01"), person("p-c", "2005-04-01"), person("p-g", "1945-01-01")],
        facts + over.get("extra_facts", []),
        relations=[
            marriage("rel-m", "p-f", "p-m", "2000-01-01"),
            parentage("rel-fc", "p-f", "p-c", "2005-04-01"),
            parentage("rel-mc", "p-m", "p-c", "2005-04-01"),
            parentage("rel-gf", "p-g", "p-f", "1970-01-01"),
        ],
        judgments=judgments + over.get("extra_judgments", []),
        choices=over.get("choices", []),
    )


class TestKinship(unittest.TestCase):
    """親族（民法725〜729。docs/public-sources/20261109_R4-modeling_concepts.md §3.1、国税庁の説明は …misc-age-kinship-attribution.md §2.3）。"""

    def _idx(self, relations: list[dict[str, Any]]) -> Any:
        return relation_index({"relations": relations})

    def test_blood_degrees(self) -> None:
        rel = [parentage("a", "g", "p"), parentage("b", "p", "c"), parentage("d", "g", "u"), parentage("e", "u", "x")]
        idx = self._idx(rel)
        on = _dt.date(2026, 1, 1)
        self.assertEqual((kinship(idx, "c", "p", on).kind, kinship(idx, "c", "p", on).degree), ("血族", 1))
        self.assertEqual(kinship(idx, "c", "g", on).degree, 2)  # 祖父母：2親等
        self.assertEqual(kinship(idx, "p", "u", on).degree, 2)  # 兄弟姉妹：2親等（共同の祖先までの世代数：民法726）
        self.assertEqual(kinship(idx, "c", "x", on).degree, 4)  # いとこ：4親等

    def test_not_related_is_false_not_error(self) -> None:
        idx = self._idx([parentage("a", "g", "p")])
        self.assertIs(kinship(idx, "p", "stranger", _dt.date(2026, 1, 1)).relative, False)

    def test_six_degree_limit(self) -> None:
        # 6親等内の血族（民法725一）：直系で7世代離れれば親族でない
        chain = [parentage(f"r{i}", f"n{i}", f"n{i + 1}") for i in range(7)]
        idx = self._idx(chain)
        on = _dt.date(2026, 1, 1)
        self.assertEqual(kinship(idx, "n0", "n6", on).degree, 6)
        self.assertIs(kinship(idx, "n0", "n7", on).relative, False)

    def test_spouse_and_affinity(self) -> None:
        idx = self._idx([marriage("m", "a", "b", "2000-01-01"), parentage("p1", "x", "a"), parentage("p2", "y", "b")])
        on = _dt.date(2026, 1, 1)
        self.assertEqual(kinship(idx, "a", "b", on).kind, "配偶者")
        self.assertEqual(kinship(idx, "a", "y", on).kind, "姻族")  # 配偶者の親（1親等の姻族）
        self.assertEqual(kinship(idx, "a", "y", on).degree, 1)

    def test_spouse_of_blood_relative_is_affinity(self) -> None:
        # 自己の血族の配偶者（子の配偶者：1親等の姻族）
        idx = self._idx([parentage("p", "a", "c"), marriage("m", "c", "s", "2015-01-01")])
        k = kinship(idx, "a", "s", _dt.date(2026, 1, 1))
        self.assertEqual((k.kind, k.degree), ("姻族", 1))

    def test_stepchild_is_affinity(self) -> None:
        # 配偶者の子は1親等の姻族（TA1180QA Q2：…misc-age-kinship-attribution.md §2.3）
        idx = self._idx([marriage("m", "a", "b", "2020-01-01"), parentage("p", "b", "c", "2010-01-01")])
        k = kinship(idx, "a", "c", _dt.date(2026, 1, 1))
        self.assertEqual((k.relative, k.kind, k.degree), (True, "姻族", 1))

    def test_adoption_creates_blood_relation(self) -> None:
        # 第727条：養子と養親及びその血族の間（…misc-age-kinship-attribution.md §2.3 SG-s0567）
        adoption = {"id": "ad", "kind": "adoption", "roles": {"adoptive_parent": "a", "adoptee": "c"}, "when": {"from_on": "2020-01-01"}}
        idx = self._idx([adoption, parentage("p", "g", "a")])
        self.assertEqual(kinship(idx, "c", "a", _dt.date(2026, 1, 1)).degree, 1)
        self.assertEqual(kinship(idx, "c", "g", _dt.date(2026, 1, 1)).degree, 2)
        self.assertIs(kinship(idx, "c", "a", _dt.date(2019, 1, 1)).relative, False)  # 縁組の前

    def test_adoption_ended(self) -> None:
        # 第729条：離縁で終了
        adoption = {"id": "ad", "kind": "adoption", "roles": {"adoptive_parent": "a", "adoptee": "c"}, "when": {"from_on": "2020-01-01", "to_on": "2024-12-31"}}
        idx = self._idx([adoption])
        self.assertIs(kinship(idx, "c", "a", _dt.date(2026, 1, 1)).relative, False)

    def test_divorce_ends_spouse_and_affinity(self) -> None:
        # 第728条第1項：姻族関係は離婚で終了
        idx = self._idx([marriage("m", "a", "b", "2000-01-01", "2020-01-01", ended_by="divorce"), parentage("p", "y", "b")])
        on = _dt.date(2026, 1, 1)
        self.assertIs(kinship(idx, "a", "b", on).relative, False)
        self.assertIs(kinship(idx, "a", "y", on).relative, False)

    def test_death_keeps_affinity_until_declaration(self) -> None:
        # 第728条第2項・SG-s0564：死亡後も、終了の意思表示までは姻族関係が続く
        idx = self._idx([marriage("m", "a", "b", "2000-01-01", "2020-01-01", ended_by="death"), parentage("p", "y", "b")])
        self.assertEqual(kinship(idx, "a", "y", _dt.date(2026, 1, 1)).kind, "姻族")
        idx2 = self._idx([marriage("m", "a", "b", "2000-01-01", "2020-01-01", ended_by="death", affinity_termination_on="2025-01-01"), parentage("p", "y", "b")])
        self.assertIs(kinship(idx2, "a", "y", _dt.date(2026, 1, 1)).relative, False)

    def test_unknown_end_is_undecided(self) -> None:
        idx = self._idx([marriage("m", "a", "b", "2000-01-01", "2020-01-01"), parentage("p", "y", "b")])
        self.assertIsNone(kinship(idx, "a", "y", _dt.date(2026, 1, 1)).relative)

    def test_marriage_mark_propagates(self) -> None:
        rec = marriage("m", "a", "b", "2026-01-01")
        rec["mark"] = "予測"
        k = kinship(self._idx([rec]), "a", "b", _dt.date(2026, 6, 1))
        self.assertEqual(k.states, frozenset({State.FORECAST}))


class TestMedicalInputs(unittest.TestCase):
    def test_s3_base(self) -> None:
        # 実測 §5.1：S3 の父の控除の対象 240,000（P1 の補塡後 0）・母 90,000
        out = run(s3_family(), 2025)
        self.assertEqual(val(out, V_MED, "p-f"), 240_000)
        self.assertEqual(val(out, V_MED, "p-m"), 90_000)
        self.assertEqual(val(out, V_MED, "p-c"), 0)
        self.assertEqual(val(out, V_MED, "p-g"), 0)
        self.assertEqual(out.exclusions, [])

    def test_s3_variant_incurred_after_livelihood(self) -> None:
        # 実測 §5.1（R4 S3 の変種）：受診も支払も生計一でない → P3 は対象外（父 180,000 円）。12月31日や支払日だけで見ると基本で 180,000 になる（反証の目印）
        out = run(s3_family(p3_incurred="2025-10-05"), 2025)
        self.assertEqual(val(out, V_MED, "p-f"), 180_000)

    def test_excess_reimbursement_not_taken_from_others(self) -> None:
        # TA1120・質疑応答事例 05/28（…iryohi-nta-mhlw.md §4）：超えた 30,000 円をほかの医療費から差し引かない。合算すると 210,000 円になる（反証の目印）
        self.assertEqual(val(run(s3_family(), 2025), V_MED, "p-f"), 240_000)

    def test_reimbursement_by_other_recipient(self) -> None:
        # 質疑応答事例 05/26：受取人が支払者と違っても差し引く
        extra = [reimbursement("u2", "p-m", "2025-08-30", 10_000, ("p2",), "mutual_aid_benefit")]
        judg = [judgment("j-u2", "判断.補塡の対象", {"reimbursement_id": "u2"}, {"compensates_medical_expenses": True})]
        out = run(s3_family(extra_facts=extra, extra_judgments=judg), 2025)
        self.assertEqual(val(out, V_MED, "p-f"), 230_000)

    def test_multi_year_reimbursement_is_prorated(self) -> None:
        # 実測 §5.1 の S3-4 と質疑応答事例 05/61：支払った額に応じて各年分にあん分。令和7年分 15,000＋180,000＋60,000＝255,000、令和8年分 15,000
        facts = [
            medical("p1a", "p-f", "p-c", "2025-12-28", "2025-12-20", 60_000, ("hospitalization",)),
            medical("p1b", "p-f", "p-c", "2026-01-10", "2026-01-05", 60_000, ("hospitalization",)),
            reimbursement("u1", "p-f", "2026-02-10", 90_000, ("p1a", "p1b")),
            medical("p2", "p-f", "p-f", "2025-09-05", "2025-09-05", 180_000),
            medical("p3", "p-f", "p-g", "2025-10-15", "2025-09-20", 60_000),
        ]
        ir = make_ir(
            [person("p-f", "1970-01-01"), person("p-c", "2005-04-01"), person("p-g", "1945-01-01")],
            facts,
            relations=[parentage("r1", "p-f", "p-c", "2005-04-01"), parentage("r2", "p-g", "p-f", "1970-01-01")],
            judgments=[seikei("j1", "p-f", "p-c", "2025-01-01"), seikei("j2", "p-f", "p-g", "2025-01-01", "2025-09-30")],
        )
        self.assertEqual(val(run(ir, 2025), V_MED, "p-f"), 255_000)
        self.assertEqual(val(run(ir, 2026), V_MED, "p-f"), 15_000)

    def test_estimate_is_marked_and_deducted(self) -> None:
        # 通達73−10（…iryohi-nta-mhlw.md §1）：確定していなければ見込額で差し引く。印 見積り が入力に付く
        est = judgment(
            "e1", "見積り.補塡の見込額", {"payment_ids": ["p2"]},
            {"estimated_amount": 30_000, "benefit_type": "hospitalization_benefit"},
            when={"tax_year": 2025}, mark="見積り",
        )
        out = run(s3_family(extra_judgments=[est]), 2025)
        self.assertEqual(val(out, V_MED, "p-f"), 210_000)
        self.assertIn(State.ESTIMATE, out.values[(V_MED, "p-f")].states)
        self.assertIn("e1", out.values[(V_MED, "p-f")].record_ids)

    def test_estimate_after_confirmed_same_type_is_out_of_scope(self) -> None:
        est = judgment("e1", "見積り.補塡の見込額", {"payment_ids": ["p1"]},
                       {"estimated_amount": 10_000, "benefit_type": "hospitalization_benefit"}, when={"tax_year": 2025}, mark="見積り")
        out = run(s3_family(extra_judgments=[est]), 2025)
        self.assertEqual(val(out, V_MED, "p-f"), 0)
        self.assertTrue(any("確定した補塡と見込額" in r for r in reasons(out, V_MED, "p-f")))

    def test_excluded_benefit_types_do_not_reduce(self) -> None:
        # 通達73−9・質疑応答事例 05/27：傷病手当金・出産手当金は補塡に当たらない
        extra = [reimbursement("u2", "p-f", "2025-11-01", 50_000, ("p2",), "sickness_allowance")]
        self.assertEqual(val(run(s3_family(extra_facts=extra), 2025), V_MED, "p-f"), 240_000)

    def test_mutual_aid_benefit_needs_judgment(self) -> None:
        extra = [reimbursement("u2", "p-f", "2025-11-01", 50_000, ("p2",), "mutual_aid_benefit")]
        ir = s3_family(extra_facts=extra)
        self.assertIn("判断.補塡の対象:u2", open_slots(ir, 2025))
        yes = run(ir, 2025, {"判断.補塡の対象:u2": {"compensates_medical_expenses": True}})
        no = run(ir, 2025, {"判断.補塡の対象:u2": {"compensates_medical_expenses": False}})
        self.assertEqual(val(yes, V_MED, "p-f"), 190_000)
        self.assertEqual(val(no, V_MED, "p-f"), 240_000)

    def test_reimbursement_without_target_excludes(self) -> None:
        extra = [reimbursement("u2", "p-f", "2025-11-01", 50_000, None)]
        out = run(s3_family(extra_facts=extra), 2025)
        self.assertTrue(any("対象の医療費" in r for r in reasons(out, V_MED, "p-f")))

    def test_overlapping_target_sets_are_read_both_ways(self) -> None:
        # 一部だけ重なる補塡：まとめて限度・補塡ごとに限度の両方で計算し、差し引く額が分かれれば未確定（一次情報なし）。対象外にしない
        extra = [reimbursement("u2", "p-f", "2025-11-01", 10_000, ("p1", "p2"))]
        out = run(s3_family(extra_facts=extra), 2025)
        self.assertEqual(reasons(out, V_MED, "p-f"), [])
        self.assertIn("一次情報", missing(out, V_MED, "p-f"))

    def test_identical_target_sets_are_summed(self) -> None:
        # 同じ対象の2つの給付は合計して限度を当てる（法令の読み）：P2 180,000 に 100,000＋100,000 → 全部差し引いて 0
        extra = [reimbursement("u2", "p-f", "2025-11-01", 100_000, ("p2",)), reimbursement("u3", "p-f", "2025-11-02", 100_000, ("p2",), "high_cost_medical_care_benefit")]
        out = run(s3_family(extra_facts=extra), 2025)
        self.assertEqual(val(out, V_MED, "p-f"), 60_000)  # p1 は補塡で 0、p2 は 0、p3 の 60,000

    def test_fraction_allocation_uses_unfounded_rounding(self) -> None:
        # 質疑応答事例 05/61 のあん分：100×100/300＝33.3… の1円未満は根拠がない（D22 S3）。候補で丸める（対象外にしない）
        facts = [
            medical("a", "p-1", "p-1", "2025-05-01", "2025-05-01", 100),
            medical("b", "p-1", "p-1", "2026-05-01", "2026-05-01", 200),
            reimbursement("u", "p-1", "2026-06-01", 100, ("a", "b")),
        ]
        ir = make_ir([person("p-1")], facts)
        for cand, expected in (("floor", 67), ("ceil", 66)):
            with self.subTest(cand=cand):
                out = run(ir, 2025, rounding=cand)
                self.assertEqual(val(out, V_MED, "p-1"), expected)
                self.assertEqual(reasons(out, V_MED, "p-1"), [])

    def test_deceased_patient_paid_by_heir(self) -> None:
        # 質疑応答事例 05/57（…iryohi-nta-mhlw.md §7）：死亡した父の医療費を翌年に子が支払った。受診した時に生計を一にしていれば子の医療費
        father = {**person("p-f", "1950-01-01"), "death_on": "2025-12-20"}
        facts = [medical("a", "p-s", "p-f", "2026-01-15", "2025-12-01", 50_000)]
        ir = make_ir([father, person("p-s")], facts, relations=[parentage("r", "p-f", "p-s", "1990-01-01")])
        self.assertIn("判断.生計を一にする:p-s:p-f@2025-12-01", open_slots(ir, 2026))
        for live, expected in ((True, 50_000), (False, 0)):
            with self.subTest(live=live):
                out = run(ir, 2026, {"判断.生計を一にする:p-s:p-f@2025-12-01": live})
                self.assertEqual(val(out, V_MED, "p-s"), expected)
                self.assertEqual(reasons(out, V_MED, "p-s"), [])

    def test_medicine_needs_range_judgment(self) -> None:
        facts = [medical("a", "p-1", "p-1", "2026-05-01", "2026-05-01", 5_000, ("medicine",))]
        ir = make_ir([person("p-1")], facts)
        sid = f"{J_RANGE}:a"
        self.assertIn(sid, open_slots(ir, 2026))
        self.assertEqual(val(run(ir, 2026, {sid: True}), V_MED, "p-1"), 5_000)
        self.assertEqual(val(run(ir, 2026, {sid: False}), V_MED, "p-1"), 0)

    def test_range_judgment_overrides_default(self) -> None:
        # 美容目的などの範囲外は判断で上書きする（通達73−4）
        facts = [medical("a", "p-1", "p-1", "2026-05-01", "2026-05-01", 5_000)]
        ir = make_ir([person("p-1")], facts, judgments=[judgment("j", J_RANGE, {"payment_id": "a"}, False)])
        self.assertEqual(val(run(ir, 2026), V_MED, "p-1"), 0)

    def test_paid_date_decides_the_year(self) -> None:
        # 通達73−2・質疑応答事例 05/24：現実に支払った年分（受診は前年でも支払の年分）
        facts = [medical("a", "p-1", "p-1", "2026-01-10", "2025-12-20", 5_000)]
        ir = make_ir([person("p-1")], facts)
        self.assertEqual(val(run(ir, 2025), V_MED, "p-1"), 0)
        self.assertEqual(val(run(ir, 2026), V_MED, "p-1"), 5_000)

    def test_open_livelihood_is_two_candidates(self) -> None:
        facts = [medical("a", "p-1", "p-2", "2026-05-10", "2026-05-10", 5_000)]
        ir = make_ir([person("p-1"), person("p-2", "2000-01-01")], facts, relations=[parentage("r", "p-1", "p-2", "2000-01-01")])
        sid = f"{J_SEIKEI}:p-1:p-2@2026-05-10"
        self.assertIn(sid, open_slots(ir, 2026))
        self.assertEqual(val(run(ir, 2026, {sid: True}), V_MED, "p-1"), 5_000)
        self.assertEqual(val(run(ir, 2026, {sid: False}), V_MED, "p-1"), 0)

    def test_no_recorded_relation_is_out_of_scope(self) -> None:
        facts = [medical("a", "p-1", "p-2", "2026-05-10", "2026-05-10", 5_000)]
        out = run(make_ir([person("p-1"), person("p-2")], facts), 2026)
        self.assertEqual(val(out, V_MED, "p-1"), 0)
        self.assertTrue(any("親族であることを" in r for r in reasons(out, V_MED, "p-1")))

    def test_deposit_counts_in_the_year_applied(self) -> None:
        # 質疑応答事例 05/86：12月に支払った保証金が翌年1月に入院費用に充当されたら翌年分。充当の日がなければ c-入力
        facts = [medical("a", "p-1", "p-1", "2025-12-10", "2025-12-10", 5_000, ("deposit", "hospitalization"), deposit_applied_on="2026-01-15")]
        ir = make_ir([person("p-1")], facts)
        self.assertEqual(val(run(ir, 2025), V_MED, "p-1"), 0)
        self.assertEqual(val(run(ir, 2026), V_MED, "p-1"), 5_000)
        no_date = [medical("a", "p-1", "p-1", "2026-05-10", "2026-05-10", 5_000, ("deposit",))]
        self.assertTrue(any("充当された日" in r for r in reasons(run(make_ir([person("p-1")], no_date), 2026), V_MED, "p-1")))


class TestSelfMedicationInputs(unittest.TestCase):
    """S3-5（…iryohi-verification.md §5.1）と TA1129・1133（…iryohi-nta-mhlw.md §6.1・§6.2）。"""

    def _ir(self, *, torikumi_person: str = "p-m", label: str = "present", choice_value: str | None = None) -> dict[str, Any]:
        facts: list[dict[str, Any]] = [
            medical("otc", "p-m", "p-m", "2025-05-01", "2025-05-01", 30_000, ("medicine",), selfmed_label=label, product_name="架空かぜ薬"),
            {"id": "hc", "kind": "health_checkup_record", "roles": {"person": torikumi_person}, "when": {"on": "2025-06-01"}, "attributes": {"activity": "periodic_health_checkup"}},
        ]
        choices = []
        if choice_value is not None:
            choices = [choice("c", "選択.医療費控除かセルフメディケーション税制か", "p-m", {"person": "p-m"}, choice_value, when={"tax_year": 2025})]
        return make_ir([person("p-m"), person("p-c", "2005-01-01")], facts, relations=[parentage("r", "p-m", "p-c", "2005-01-01")], choices=choices,
                       judgments=[judgment("j", J_RANGE, {"payment_id": "otc"}, True)])

    def test_purchases_are_counted_with_own_activity(self) -> None:
        out = run(self._ir(choice_value="self_medication"), 2025)
        self.assertEqual(val(out, V_SELF, "p-m"), 30_000)
        self.assertIs(val(out, V_CHOICE, "p-m"), True)

    def test_family_members_activity_does_not_count(self) -> None:
        # TA1129・TA1133：申告者本人の取組が要る（厚労QA Q16）
        out = run(self._ir(torikumi_person="p-c"), 2025)
        self.assertEqual(val(out, V_SELF, "p-m"), 0)

    def test_choice_is_open_when_eligible(self) -> None:
        ir = self._ir()
        sid = "選択.医療費控除かセルフメディケーション税制か:p-m"
        self.assertIn(sid, open_slots(ir, 2025))
        self.assertIs(val(run(ir, 2025, {sid: "self_medication"}), V_CHOICE, "p-m"), True)
        self.assertIs(val(run(ir, 2025, {sid: "medical_expense_deduction"}), V_CHOICE, "p-m"), False)

    def test_no_choice_slot_without_eligibility(self) -> None:
        ir = make_ir([person("p-m")], [medical("a", "p-m", "p-m", "2025-05-01", "2025-05-01", 5_000)])
        self.assertNotIn("選択.医療費控除かセルフメディケーション税制か:p-m", open_slots(ir, 2025))

    def test_chosen_without_activity_is_out_of_scope(self) -> None:
        ir = make_ir([person("p-m")], [], choices=[choice("c", "選択.医療費控除かセルフメディケーション税制か", "p-m", {"person": "p-m"}, "self_medication", when={"tax_year": 2025})])
        out = run(ir, 2025)
        self.assertTrue(reasons(out, V_CHOICE, "p-m"))

    def test_unknown_label_needs_override(self) -> None:
        ir = self._ir(label="unknown", choice_value="self_medication")
        sid = "判断.セルフメディケーション表示の上書き:otc"
        self.assertIn(sid, open_slots(ir, 2025))
        self.assertEqual(val(run(ir, 2025, {sid: {"eligible_item": True}}), V_SELF, "p-m"), 30_000)
        self.assertEqual(val(run(ir, 2025, {sid: {"eligible_item": False}}), V_SELF, "p-m"), 0)

    def test_override_excludes_absent_label_item(self) -> None:
        ir = self._ir(label="absent", choice_value="self_medication")
        ir["judgments"].append(judgment("o", "判断.セルフメディケーション表示の上書き", {"payment_id": "otc"}, {"eligible_item": True}))
        self.assertEqual(val(run(ir, 2025), V_SELF, "p-m"), 30_000)

    def test_override_with_other_tax_year_is_out_of_scope(self) -> None:
        ir = self._ir(choice_value="self_medication")
        ir["judgments"].append(judgment("o", "判断.セルフメディケーション表示の上書き", {"payment_id": "otc"}, {"eligible_item": True, "tax_year": 2026}))
        self.assertTrue(any("年分" in r for r in reasons(run(ir, 2025), V_SELF, "p-m")))

    def test_activity_other_only_is_out_of_scope(self) -> None:
        ir = self._ir(choice_value="self_medication")
        ir["facts"][1]["attributes"]["activity"] = "other"
        self.assertTrue(any("other" in r for r in reasons(run(ir, 2025), V_SELF, "p-m")))

    def test_reimbursed_purchase_is_reduced(self) -> None:
        # 対象の購入だけを対象にする補塡は、その額を除く（措法41の17）。割り振りの読みはどれも同じなので確定
        ir = self._ir(choice_value="self_medication")
        ir["facts"].append(reimbursement("u", "p-m", "2025-07-01", 1_000, ("otc",)))
        out = run(ir, 2025)
        self.assertEqual(reasons(out, V_SELF, "p-m"), [])
        self.assertEqual(missing(out, V_SELF, "p-m"), [])


class TestSocialInsuranceInputs(unittest.TestCase):
    """社会保険料（所法74①。…zeigaku-tax-calc.md §7）。"""

    def _payment(self, rid: str, payer: str, liable: str, on: str, amount: int, premium: str = "national_pension", **attrs: Any) -> dict[str, Any]:
        return {"id": rid, "kind": "social_insurance_payment", "roles": {"payer": payer, "liable_person": liable}, "when": {"on": on}, "amounts": {"amount": amount}, "attributes": {"premium_type": premium, **attrs}}

    def _family(self, facts: list[dict[str, Any]], *, judgments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return make_ir([person("p-a"), person("p-b", "2006-01-01")], facts, relations=[parentage("r", "p-a", "p-b", "2006-01-01")], judgments=judgments or [])

    def test_own_premium_and_family_premium(self) -> None:
        ir = self._family(
            [self._payment("s1", "p-a", "p-a", "2026-04-30", 100_000), self._payment("s2", "p-a", "p-b", "2026-05-01", 50_000)],
            judgments=[seikei("j", "p-a", "p-b", "2026-01-01")],
        )
        self.assertEqual(val(run(ir, 2026), V_SOCIAL, "p-a"), 150_000)
        self.assertEqual(val(run(ir, 2026), V_SOCIAL, "p-b"), 0)

    def test_not_same_livelihood_is_not_counted(self) -> None:
        ir = self._family([self._payment("s1", "p-a", "p-b", "2026-05-01", 50_000)], judgments=[seikei("j", "p-a", "p-b", "2026-01-01", value=False)])
        out = run(ir, 2026)
        self.assertEqual(val(out, V_SOCIAL, "p-a"), 0)
        self.assertEqual(reasons(out, V_SOCIAL, "p-a"), [])

    def test_livelihood_differs_between_payment_and_year_end(self) -> None:
        # 判定の時点の一次情報がない（…zeigaku-tax-calc.md §7）：支払日と12月31日で違えば、読みの分かれ目で未確定（D22 S1。対象外にしない）
        ir = self._family(
            [self._payment("s1", "p-a", "p-b", "2026-05-01", 50_000)],
            judgments=[seikei("j1", "p-a", "p-b", "2026-01-01", "2026-06-30"), seikei("j2", "p-a", "p-b", "2026-07-01", value=False)],
        )
        out = run(ir, 2026)
        self.assertEqual(reasons(out, V_SOCIAL, "p-a"), [])
        [split] = out.values[(V_SOCIAL, "p-a")].missing
        self.assertEqual((split.means.value, split.candidates), ("一次情報", ("支払日の現況", "12月31日の現況")))

    def test_salary_withheld_year_is_payment_date(self) -> None:
        # 第74条第1項「給与から控除される場合」・TA1130「差し引かれた金額」：支払った日の年分。未払の給与からは数えない
        def rec(rid: str, on: str, due: str, **attrs: Any) -> dict[str, Any]:
            return {"id": rid, "kind": "salary_payment", "roles": {"recipient": "p-a"}, "when": {"on": on}, "amounts": {"gross": 300_000, "social_insurance_withheld": 40_000}, "attributes": {"counterparty": "架空の会社", "due_on": due, **attrs}}
        late = make_ir([person("p-a")], [rec("w", "2027-01-10", "2026-12-25")])
        self.assertEqual((val(run(late, 2026), V_SOCIAL, "p-a"), val(run(late, 2027), V_SOCIAL, "p-a")), (0, 40_000))
        unpaid = make_ir([person("p-a")], [rec("w", "2026-12-25", "2026-12-25", unpaid=True)])
        self.assertEqual(val(run(unpaid, 2026), V_SOCIAL, "p-a"), 0)

    def test_salary_withheld_goes_to_recipient(self) -> None:
        # 第74条第1項「給与から控除される場合」
        rec = {"id": "w", "kind": "salary_payment", "roles": {"recipient": "p-a"}, "when": {"on": "2026-06-25"}, "amounts": {"gross": 300_000, "social_insurance_withheld": 40_000}, "attributes": {"counterparty": "架空の会社", "due_on": "2026-06-25"}}
        self.assertEqual(val(run(make_ir([person("p-a")], [rec]), 2026), V_SOCIAL, "p-a"), 40_000)

    def test_payroll_duplicate_is_out_of_scope(self) -> None:
        ir = make_ir([person("p-a")], [self._payment("s1", "p-a", "p-a", "2026-05-01", 1_000, payroll_deduction=True)])
        self.assertTrue(any("給与" in r for r in reasons(run(ir, 2026), V_SOCIAL, "p-a")))

    def test_prepaid_within_year_is_counted(self) -> None:
        # 通達74・75−1(2)：その年に到来する納付期日の分は全額がその年の支払額
        ir = make_ir([person("p-a")], [self._payment("s1", "p-a", "p-a", "2026-04-01", 12_000, prepaid_period={"from_on": "2026-04-01", "to_on": "2026-12-31"})])
        self.assertEqual(val(run(ir, 2026), V_SOCIAL, "p-a"), 12_000)

    def test_prepaid_over_years_is_out_of_scope(self) -> None:
        # 按分の材料（納付期日）がなければ c-入力（全額の選択なら決まる）
        ir = make_ir([person("p-a")], [self._payment("s1", "p-a", "p-a", "2026-04-01", 12_000, prepaid_period={"from_on": "2026-04-01", "to_on": "2027-03-31"})])
        self.assertTrue(any("prepaid_due_dates" in r for r in reasons(run(ir, 2026), V_SOCIAL, "p-a")))

    def test_prepaid_over_years_pro_rata_or_whole(self) -> None:
        # 通達74・75−1(2)：総額×その年中に到来する納付期日の回数÷総回数。74・75−2：前納期間が1年以内なら全額を支払った年分にできる（選択）
        dates = [f"{2026 + (m > 12)}-{(m - 1) % 12 + 1:02d}-28" for m in range(4, 16)]  # 2026-04〜2027-03 の12回
        rec = self._payment("s1", "p-a", "p-a", "2026-04-01", 12_000, prepaid_period={"from_on": "2026-04-01", "to_on": "2027-03-31"}, prepaid_due_dates=dates)
        ir = make_ir([person("p-a")], [rec])
        sid = "選択.前納した社会保険料の控除の年分:s1"
        self.assertIn(sid, open_slots(ir, 2026))
        self.assertEqual((val(run(ir, 2026, {sid: "pro_rata"}), V_SOCIAL, "p-a"), val(run(ir, 2027, {sid: "pro_rata"}), V_SOCIAL, "p-a")), (9_000, 3_000))
        self.assertEqual((val(run(ir, 2026, {sid: "all_in_paid_year"}), V_SOCIAL, "p-a"), val(run(ir, 2027, {sid: "all_in_paid_year"}), V_SOCIAL, "p-a")), (12_000, 0))
        # 1年を超える前納：法令で前納できるものかの一次情報がない → 全額の選択で按分と違えば未確定
        long = dict(rec, attributes=dict(rec["attributes"], prepaid_period={"from_on": "2026-04-01", "to_on": "2028-03-31"}))
        out = run(make_ir([person("p-a")], [long]), 2026, {sid: "all_in_paid_year"})
        self.assertEqual((val(out, V_SOCIAL, "p-a"), missing(out, V_SOCIAL, "p-a")), (12_000, ["一次情報"]))

    def test_other_premium_type_is_out_of_scope(self) -> None:
        ir = make_ir([person("p-a")], [self._payment("s1", "p-a", "p-a", "2026-05-01", 1_000, premium="other")])
        self.assertTrue(any("other" in r for r in reasons(run(ir, 2026), V_SOCIAL, "p-a")))

    def test_pension_withheld_goes_to_recipient(self) -> None:
        # 公的年金から差し引かれた（特別徴収された）額は受給者の支払（TA No.1130・手引き p.15：…zeigaku-tax-calc.md §7.2）
        rec = {"id": "pn", "kind": "pension_payment", "roles": {"recipient": "p-a"}, "when": {"on": "2026-06-15"}, "amounts": {"gross": 100_000, "social_insurance_withheld": 8_000}, "attributes": {"scheme": "national_pension", "benefit_reason": "old_age"}}
        out = run(make_ir([person("p-a")], [rec]), 2026)
        self.assertEqual(val(out, V_SOCIAL, "p-a"), 8_000)
        self.assertEqual(reasons(out, V_SOCIAL, "p-a"), [])

    def test_non_public_pension_withheld_is_read_both_ways(self) -> None:
        # 企業年金など特別徴収の対象でない年金から差し引かれた額：数える・数えないの一次情報がない → 数える値で入れて未確定
        rec = {"id": "pn", "kind": "pension_payment", "roles": {"recipient": "p-a"}, "when": {"on": "2026-06-15"}, "amounts": {"gross": 100_000, "social_insurance_withheld": 8_000}, "attributes": {"scheme": "corporate_pension", "benefit_reason": "old_age"}}
        out = run(make_ir([person("p-a")], [rec]), 2026)
        self.assertEqual((reasons(out, V_SOCIAL, "p-a"), val(out, V_SOCIAL, "p-a"), missing(out, V_SOCIAL, "p-a")), ([], 8_000, ["一次情報"]))

    def _slip(self, rid: str, payer: str | None, social: int | None, prior: list[str] | None = None) -> dict[str, Any]:
        amounts = {"payment_amount": 3_600_000, "withholding_tax": 50_000}
        if social is not None:
            amounts["social_insurance"] = social
        attrs: dict[str, Any] = {"slip_type": "salary", "year_end_adjusted": True}
        if payer is not None:
            attrs["counterparty"] = payer
        if prior:
            attrs["includes_prior_payers"] = prior
        return {"id": rid, "kind": "withholding_slip", "roles": {"recipient": "p-a"}, "when": {"tax_year": 2026}, "amounts": amounts, "attributes": attrs}

    def _pay(self, rid: str, payer: str, social: int) -> dict[str, Any]:
        return {"id": rid, "kind": "salary_payment", "roles": {"recipient": "p-a"}, "when": {"on": "2026-06-25"}, "amounts": {"gross": 300_000, "social_insurance_withheld": social}, "attributes": {"counterparty": payer, "due_on": "2026-06-25"}}

    def test_slip_social_insurance_is_preferred(self) -> None:
        # D23 K4：源泉徴収票の「社会保険料等の金額」を優先し、その支払者の明細の額は数えない。票のない支払者の明細は数える
        ir = make_ir([person("p-a")], [self._pay("w1", "架空の会社", 40_000), self._pay("w2", "架空の店", 5_000), self._slip("sl", "架空の会社", 480_000)])
        out = run(ir, 2026)
        self.assertEqual(val(out, V_SOCIAL, "p-a"), 485_000)
        self.assertEqual(reasons(out, V_SOCIAL, "p-a"), [])

    def test_slip_with_prior_payer_covers_its_payslips(self) -> None:
        # 前の支払者を通算した票（includes_prior_payers）は、前の支払者の明細も覆う
        ir = make_ir([person("p-a")], [self._pay("w1", "架空の会社", 40_000), self._pay("w2", "架空の前の会社", 5_000), self._slip("sl", "架空の会社", 500_000, ["架空の前の会社"])])
        self.assertEqual(val(run(ir, 2026), V_SOCIAL, "p-a"), 500_000)

    def test_slip_without_social_field_keeps_payslips(self) -> None:
        ir = make_ir([person("p-a")], [self._pay("w1", "架空の会社", 40_000), self._slip("sl", "架空の会社", None)])
        self.assertEqual(val(run(ir, 2026), V_SOCIAL, "p-a"), 40_000)

    def test_duplicate_slips_are_out_of_scope(self) -> None:
        ir = make_ir([person("p-a")], [self._slip("s1", "架空の会社", 480_000), self._slip("s2", "架空の会社", 480_000)])
        self.assertTrue(any("2枚" in r for r in reasons(run(ir, 2026), V_SOCIAL, "p-a")))

    def test_slip_without_payer_and_payslips_is_out_of_scope(self) -> None:
        ir = make_ir([person("p-a")], [self._pay("w1", "架空の会社", 40_000), self._slip("sl", None, 480_000)])
        self.assertTrue(any("支払者の名" in r for r in reasons(run(ir, 2026), V_SOCIAL, "p-a")))


class TestMutualAidInputs(unittest.TestCase):
    def _rec(self, payer: str, member: str) -> dict[str, Any]:
        return {"id": "m1", "kind": "mutual_aid_payment", "roles": {"payer": payer, "member": member}, "when": {"on": "2026-05-01"}, "amounts": {"amount": 23_000}, "attributes": {"contribution_type": "individual_defined_contribution"}}

    def test_own_payment(self) -> None:
        # 所法75①：支払った金額の全額（…hoken-kifu-laws.md §5）
        self.assertEqual(val(run(make_ir([person("p-a")], [self._rec("p-a", "p-a")]), 2026), V_MUTUAL, "p-a"), 23_000)

    def test_paid_by_someone_else_is_out_of_scope(self) -> None:
        # HANDOFF D21 R3：加入者以外の支払は後の段
        out = run(make_ir([person("p-a"), person("p-b")], [self._rec("p-a", "p-b")]), 2026)
        self.assertTrue(reasons(out, V_MUTUAL, "p-a"))
        self.assertTrue(reasons(out, V_MUTUAL, "p-b"))


def contract(cid: str, product: str, concluded: str, *, holder: str = "p-a", from_on: str | None = None, to_on: str | None = None, **attrs: Any) -> dict[str, Any]:
    when: dict[str, Any] = {"from_on": from_on or concluded}
    if to_on:
        when["to_on"] = to_on
    return {"id": cid, "kind": "insurance_contract", "roles": {"policyholder": holder}, "when": when, "attributes": {"product_type": product, "concluded_on": concluded, **attrs}}


def premium(rid: str, payer: str, cid: str, on: str, amount: int, flow: str = "premium", **attrs: Any) -> dict[str, Any]:
    return {"id": rid, "kind": "insurance_payment", "roles": {"payer": payer}, "when": {"on": on}, "amounts": {"amount": amount}, "attributes": {"contract_id": cid, "flow": flow, **attrs}}


class TestLifeInsuranceInputs(unittest.TestCase):
    """所法76⑤〜⑩・通達76−1・76−6（…hoken-kifu-laws.md §2.2、…hoken-kifu-nta-soumu.md §1）。"""

    def _ir(self, contracts: list[dict[str, Any]], payments: list[dict[str, Any]], **sec: Any) -> dict[str, Any]:
        return make_ir([person("p-a"), person("p-b", "2006-01-01")], payments, assets=contracts, relations=[parentage("r", "p-a", "p-b", "2006-01-01")], **sec)

    def test_new_and_old_by_conclusion_date(self) -> None:
        # 平成24年1月1日の境（第5項・第6項）。旧契約の医療保険は旧生命保険料（第6項第4号）。新契約の医療保険は介護医療保険料（第7項）
        contracts = [
            contract("c-old", "life", "2011-12-31", beneficiary_ids=["p-b"]),
            contract("c-new", "life", "2012-01-01", beneficiary_ids=["p-b"]),
            contract("c-medold", "medical_or_care", "2011-12-31", beneficiary_ids=["p-a"]),
            contract("c-med", "medical_or_care", "2012-01-01", beneficiary_ids=["p-a"]),
        ]
        payments = [premium("a", "p-a", "c-old", "2026-05-01", 10_000), premium("b", "p-a", "c-new", "2026-05-01", 20_000),
                    premium("c", "p-a", "c-medold", "2026-05-01", 3_000), premium("d", "p-a", "c-med", "2026-05-01", 4_000)]
        out = run(self._ir(contracts, payments), 2026, {"選択.保険料控除の区分:p-a": "both"})
        self.assertEqual(val(out, V_NEW, "p-a"), 20_000)
        self.assertEqual(val(out, V_OLD, "p-a"), 13_000)
        self.assertEqual(val(out, V_CARE, "p-a"), 4_000)

    def test_payer_not_policyholder(self) -> None:
        # TA1140 Q1・質疑応答 03/35：支払った人が控除する（契約者は問わない）
        contracts = [contract("c1", "life", "2015-01-01", holder="p-b", beneficiary_ids=["p-a"])]
        out = run(self._ir(contracts, [premium("a", "p-a", "c1", "2026-05-01", 10_000)]), 2026)
        self.assertEqual(val(out, V_NEW, "p-a"), 10_000)

    def test_dividend_reduces_within_section(self) -> None:
        # TA1140 注1・通達76−6（注）：剰余金は差し引く（ほかの区分からは差し引かない）
        contracts = [contract("c1", "life", "2015-01-01", beneficiary_ids=["p-a"])]
        payments = [premium("a", "p-a", "c1", "2026-05-01", 10_000), premium("b", "p-a", "c1", "2026-06-01", 2_000, flow="dividend")]
        self.assertEqual(val(run(self._ir(contracts, payments), 2026), V_NEW, "p-a"), 8_000)

    def test_dividend_exceeding_premium_is_zero(self) -> None:
        # 「控除した残額」（所法76①）は0未満にしない（区分をまたがない：通達76−6（注））。払込みに充てた剰余金も差し引く
        contracts = [contract("c1", "life", "2015-01-01", beneficiary_ids=["p-a"])]
        payments = [premium("a", "p-a", "c1", "2026-05-01", 1_000), premium("b", "p-a", "c1", "2026-06-01", 2_000, flow="dividend", applied_to_premium=True)]
        out = run(self._ir(contracts, payments), 2026)
        self.assertEqual((reasons(out, V_NEW, "p-a"), val(out, V_NEW, "p-a")), ([], 0))

    def test_beneficiary_must_be_payer_or_relative(self) -> None:
        contracts = [contract("c1", "life", "2015-01-01")]
        self.assertTrue(any("受取人" in r for r in reasons(run(self._ir(contracts, [premium("a", "p-a", "c1", "2026-05-01", 10_000)]), 2026), V_NEW, "p-a")))
        ir = make_ir([person("p-a"), person("p-x")], [premium("a", "p-a", "c1", "2026-05-01", 10_000)], assets=[contract("c1", "life", "2015-01-01", beneficiary_ids=["p-x"])])
        self.assertTrue(any("受取人" in r for r in reasons(run(ir, 2026), V_NEW, "p-a")))

    def test_short_term_contract_with_benefit_terms(self) -> None:
        # 所令209①：満了の日の生存（又は災害等による死亡）に限り支払う定めの5年未満の契約は特定保険契約（数えない）。それ以外の定めは数える
        for terms, expected in (("survival_at_maturity_only", 0), ("survival_or_special_cause_death", 0), ("other", 10_000)):
            with self.subTest(terms=terms):
                short = [contract("c1", "life", "2015-01-01", to_on="2019-12-31", beneficiary_ids=["p-a"], benefit_payment_terms=terms)]
                out = run(self._ir(short, [premium("a", "p-a", "c1", "2015-05-01", 10_000)]), 2015)
                self.assertEqual((reasons(out, V_NEW, "p-a"), val(out, V_NEW, "p-a"), missing(out, V_NEW, "p-a")), ([], expected, []))

    def test_rider_attached_to_old_contract_makes_it_new(self) -> None:
        # 所法76⑩：平成24年以後に旧契約に附帯して新契約を締結 → その旧契約は新契約（附帯した日以後の支払。通達76−1 の支払った時の現況）
        contracts = [contract("c1", "life", "2026-06-01", beneficiary_ids=["p-a"], rider=True, attached_to_contract_id="c0"), contract("c0", "life", "2010-01-01", beneficiary_ids=["p-a"])]
        payments = [premium("a", "p-a", "c1", "2026-06-01", 1_000), premium("b", "p-a", "c0", "2026-05-31", 10_000), premium("c", "p-a", "c0", "2026-06-01", 10_000)]
        out = run(self._ir(contracts, payments), 2026, {"選択.保険料控除の区分:p-a": "both"})
        self.assertEqual((val(out, V_NEW, "p-a"), val(out, V_OLD, "p-a"), missing(out, V_NEW, "p-a"), missing(out, V_OLD, "p-a")), (11_000, 10_000, [], []))

    def test_short_term_contract_is_read_both_ways(self) -> None:
        # 所令209①（［PS3-KM］§2）：5年未満のうち満了時の生存等に限り支払う契約だけが対象外。支払の定めは語彙にない事実 → 未確定（5年ちょうどは確定）
        short = [contract("c1", "life", "2015-01-01", to_on="2019-12-31", beneficiary_ids=["p-a"])]
        out = run(self._ir(short, [premium("a", "p-a", "c1", "2015-05-01", 10_000)]), 2015)
        self.assertEqual((reasons(out, V_NEW, "p-a"), missing(out, V_NEW, "p-a")), ([], ["事実"]))
        five = [contract("c1", "life", "2015-01-01", to_on="2020-01-01", beneficiary_ids=["p-a"])]
        self.assertEqual(missing(run(self._ir(five, [premium("a", "p-a", "c1", "2015-05-01", 10_000)]), 2015), V_NEW, "p-a"), [])

    def test_rider_with_old_contract_is_read_both_ways(self) -> None:
        # 所法76⑩：平成24年以後に旧契約に附帯した新契約 → その旧契約は新契約とみなす。どの旧契約かは語彙にない事実 → 全区分を未確定
        contracts = [contract("c1", "life", "2015-01-01", beneficiary_ids=["p-a"], rider=True), contract("c0", "life", "2010-01-01", beneficiary_ids=["p-a"])]
        payments = [premium("a", "p-a", "c1", "2026-05-01", 10_000), premium("b", "p-a", "c0", "2026-05-01", 10_000)]
        out = run(self._ir(contracts, payments), 2026, {"選択.保険料控除の区分:p-a": "both"})
        self.assertEqual(val(out, V_NEW, "p-a"), 10_000)
        self.assertEqual(missing(out, V_OLD, "p-a"), ["事実"])
        alone = run(self._ir(contracts[:1], payments[:1]), 2026)
        self.assertEqual((reasons(alone, V_NEW, "p-a"), missing(alone, V_NEW, "p-a")), ([], []))

    def test_annuity_requires_judgment(self) -> None:
        contracts = [contract("c1", "individual_annuity", "2015-01-01", beneficiary_ids=["p-a"])]
        payments = [premium("a", "p-a", "c1", "2026-05-01", 10_000)]
        self.assertTrue(any("個人年金" in r for r in reasons(run(self._ir(contracts, payments), 2026), V_NEW, "p-a")))
        ir = self._ir(contracts, payments, judgments=[judgment("j", "判断.生命保険の区分", {"contract_id": "c1"}, {"category": "individual_annuity"})])
        self.assertEqual(val(run(ir, 2026, {"選択.保険料控除の区分:p-a": "both"}), V_NEW_A, "p-a"), 10_000)

    def test_annuity_recipient_must_be_payer_or_spouse(self) -> None:
        contracts = [contract("c1", "individual_annuity", "2015-01-01", beneficiary_ids=["p-b"])]
        ir = self._ir(contracts, [premium("a", "p-a", "c1", "2026-05-01", 10_000)], judgments=[judgment("j", "判断.生命保険の区分", {"contract_id": "c1"}, {"category": "individual_annuity"})])
        # 第8項第1号を満たさない年金の契約：一般の生命保険料に当たるかの一次情報がない → 一般の値で入れて未確定
        out = run(ir, 2026, {"選択.保険料控除の区分:p-a": "both"})
        self.assertEqual((val(out, V_NEW_A, "p-a"), val(out, V_NEW, "p-a"), missing(out, V_NEW, "p-a")), (0, 10_000, ["一次情報"]))

    def test_regime_choice_slot_only_when_both(self) -> None:
        contracts = [contract("n", "life", "2015-01-01", beneficiary_ids=["p-a"]), contract("o", "life", "2010-01-01", beneficiary_ids=["p-a"])]
        payments = [premium("a", "p-a", "n", "2026-05-01", 10_000), premium("b", "p-a", "o", "2026-05-01", 10_000)]
        ir = self._ir(contracts, payments)
        sid = "選択.保険料控除の区分:p-a"
        self.assertIn(sid, open_slots(ir, 2026))
        self.assertEqual(val(run(ir, 2026, {sid: "old_only"}), V_REGIME, "p-a"), "old_only")
        only_new = self._ir(contracts[:1], payments[:1])
        self.assertNotIn(sid, open_slots(only_new, 2026))
        self.assertEqual(val(run(only_new, 2026), V_REGIME, "p-a"), "both")

    def test_person_level_choice_is_used(self) -> None:
        contracts = [contract("n", "life", "2015-01-01", beneficiary_ids=["p-a"]), contract("o", "life", "2010-01-01", beneficiary_ids=["p-a"])]
        payments = [premium("a", "p-a", "n", "2026-05-01", 10_000), premium("b", "p-a", "o", "2026-05-01", 10_000)]
        choices = [choice("c", "選択.保険料控除の区分", "p-a", {"person": "p-a"}, {"life_insurance_regime": "new_only"}, when={"tax_year": 2026})]
        out = run(self._ir(contracts, payments, choices=choices), 2026)
        self.assertEqual(val(out, V_REGIME, "p-a"), "new_only")
        self.assertIn("c", out.values[(V_REGIME, "p-a")].record_ids)

    def test_contract_level_choice_is_input_error(self) -> None:
        # 新旧の選択は区分ごと（05/76）：契約ごとの選択は c-入力（何を直せばよいかを返す）
        contracts = [contract("n", "life", "2015-01-01", beneficiary_ids=["p-a"])]
        choices = [choice("c", "選択.保険料控除の区分", "p-a", {"person": "p-a", "contract_id": "n"}, {"life_insurance_regime": "new_only"}, when={"tax_year": 2026})]
        out = run(self._ir(contracts, [premium("a", "p-a", "n", "2026-05-01", 10_000)], choices=choices), 2026)
        self.assertTrue(any("contract_id を書かない" in r for r in reasons(out, V_NEW, "p-a")))

    def test_prepaid_premium_is_out_of_scope(self) -> None:
        # 通達76−3(3)：前納は払込期日の回数であん分。払込期日がなければ c-入力
        contracts = [contract("n", "life", "2015-01-01", beneficiary_ids=["p-a"])]
        self.assertTrue(any("prepaid_due_dates" in r for r in reasons(run(self._ir(contracts, [premium("a", "p-a", "n", "2026-05-01", 10_000, prepaid=True)]), 2026), V_NEW, "p-a")))

    def test_prepaid_premium_is_apportioned_by_due_dates(self) -> None:
        # 通達76−3(3)：10,000×2÷3 の1円未満は根拠のない端数（候補で評価）。翌年分は 10,000×1÷3
        contracts = [contract("n", "life", "2015-01-01", beneficiary_ids=["p-a"])]
        ir = self._ir(contracts, [premium("a", "p-a", "n", "2026-05-01", 10_000, prepaid=True, prepaid_due_dates=["2026-06-01", "2026-12-01", "2027-06-01"])])
        self.assertEqual((val(run(ir, 2026), V_NEW, "p-a"), val(run(ir, 2026, rounding="ceil"), V_NEW, "p-a")), (6_666, 6_667))
        self.assertEqual(val(run(ir, 2027), V_NEW, "p-a"), 3_333)

    def test_other_product_is_out_of_scope(self) -> None:
        contracts = [contract("n", "other", "2015-01-01")]
        self.assertTrue(any("other" in r for r in reasons(run(self._ir(contracts, [premium("a", "p-a", "n", "2026-05-01", 10_000)]), 2026), V_QUAKE, "p-a")))


class TestEarthquakeInputs(unittest.TestCase):
    """所法77①（…hoken-kifu-laws.md §3）。"""

    def _ir(self, contract_attrs: dict[str, Any], *, judgments: list[dict[str, Any]] | None = None, payer: str = "p-a") -> dict[str, Any]:
        return make_ir(
            [person("p-a"), person("p-b", "2006-01-01")],
            [premium("a", payer, "c1", "2026-05-01", 30_000)],
            assets=[contract("c1", "earthquake", "2020-01-01", **contract_attrs)],
            relations=[parentage("r", "p-a", "p-b", "2006-01-01")],
            judgments=judgments or [],
        )

    def test_own_dwelling(self) -> None:
        out = run(self._ir({"insured_object": "dwelling", "insured_object_owner": "p-a", "residential_use": True}), 2026)
        self.assertEqual(val(out, V_QUAKE, "p-a"), 30_000)

    def test_household_goods_need_no_residential_flag(self) -> None:
        out = run(self._ir({"insured_object": "household_goods", "insured_object_owner": "p-a"}), 2026)
        self.assertEqual(val(out, V_QUAKE, "p-a"), 30_000)

    def test_relative_owner_needs_same_livelihood(self) -> None:
        ir = self._ir({"insured_object": "dwelling", "insured_object_owner": "p-b", "residential_use": True}, judgments=[seikei("j", "p-a", "p-b", "2026-01-01")])
        self.assertEqual(val(run(ir, 2026), V_QUAKE, "p-a"), 30_000)
        ir2 = self._ir({"insured_object": "dwelling", "insured_object_owner": "p-b", "residential_use": True}, judgments=[seikei("j", "p-a", "p-b", "2026-01-01", value=False)])
        self.assertEqual(val(run(ir2, 2026), V_QUAKE, "p-a"), 0)

    def test_residential_flag(self) -> None:
        # 常時居住の用に供しない家屋は地震保険料に当たらない（0）。記載がなければ c-入力
        out = run(self._ir({"insured_object": "dwelling", "insured_object_owner": "p-a", "residential_use": False}), 2026)
        self.assertEqual((reasons(out, V_QUAKE, "p-a"), val(out, V_QUAKE, "p-a")), ([], 0))
        out2 = run(self._ir({"insured_object": "dwelling", "insured_object_owner": "p-a"}), 2026)
        self.assertTrue(any("residential_use" in r for r in reasons(out2, V_QUAKE, "p-a")))

    def test_residential_ratio(self) -> None:
        # 通達77−5：一部を居住の用に供する家屋は居住割合で按分。77−6：おおむね90%以上は全額
        for ratio, expected in (({"num": 1, "den": 2}, 15_000), ({"num": 9, "den": 10}, 30_000), ({"num": 0, "den": 1}, 0)):
            with self.subTest(ratio=ratio):
                out = run(self._ir({"insured_object": "dwelling", "insured_object_owner": "p-a", "residential_ratio": ratio}), 2026)
                self.assertEqual((reasons(out, V_QUAKE, "p-a"), val(out, V_QUAKE, "p-a")), ([], expected))

    def test_missing_object_is_out_of_scope(self) -> None:
        self.assertTrue(reasons(run(self._ir({}), 2026), V_QUAKE, "p-a"))

    def test_long_term_dates_and_unrecorded_requirements(self) -> None:
        # 平成18年法律第10号附則第10条第2項：締結 H18.12.31 まで・保険期間10年以上は記録で、満期返戻金・変更なしは語彙にない事実（未確定）
        def ir(concluded: str, to_on: str | None) -> dict[str, Any]:
            return make_ir([person("p-a")], [premium("a", "p-a", "c1", "2026-05-01", 30_000)], assets=[contract("c1", "long_term_non_life", concluded, to_on=to_on)])

        ok = run(ir("2006-12-31", "2016-12-31"), 2026)
        self.assertEqual((reasons(ok, V_LONG, "p-a"), val(ok, V_LONG, "p-a"), missing(ok, V_LONG, "p-a")), ([], 30_000, ["事実"]))
        self.assertEqual(val(run(ir("2007-01-01", None), 2026), V_LONG, "p-a"), 0)  # 平成19年以後の締結
        self.assertEqual(val(run(ir("2006-01-01", "2015-12-31"), 2026), V_LONG, "p-a"), 0)  # 保険期間10年未満

    def test_long_term_refund_and_changes(self) -> None:
        # 附則第10条第2項・TA1145：満期返戻金等のあるもの、平成19年1月1日以後に変更していないもの
        def out(**attrs: Any) -> ModuleInputs:
            c = contract("c1", "long_term_non_life", "2006-12-31", to_on="2016-12-31", **attrs)
            return run(make_ir([person("p-a")], [premium("a", "p-a", "c1", "2026-05-01", 30_000)], assets=[c]), 2026)

        ok = out(maturity_refund="maturity_refund_rider", contract_changes_on=["2006-12-31"])
        self.assertEqual((val(ok, V_LONG, "p-a"), missing(ok, V_LONG, "p-a")), (30_000, []))
        self.assertEqual(val(out(maturity_refund="maturity_refund_rider", contract_changes_on=["2007-01-01"]), V_LONG, "p-a"), 0)
        self.assertEqual(val(out(maturity_refund="none", contract_changes_on=[]), V_LONG, "p-a"), 0)
        self.assertEqual(missing(out(maturity_refund="durability_mutual_aid"), V_LONG, "p-a"), ["事実"])  # 変更の記録がない：c-入力

    def test_contract_choice_between_quake_and_long_term(self) -> None:
        # 附則第10条第3項：一の契約が両方に当たるときは契約ごとの選択で一方に
        ch = [choice("c", "選択.保険料控除の区分", "p-a", {"person": "p-a", "contract_id": "c1"}, {"earthquake_or_old_long_term": "earthquake"}, when={"tax_year": 2026})]
        ir = make_ir([person("p-a")], [premium("a", "p-a", "c1", "2026-05-01", 30_000)],
                     assets=[contract("c1", "long_term_non_life", "2005-01-01", insured_object="dwelling", insured_object_owner="p-a", residential_use=True)], choices=ch)
        out = run(ir, 2026)
        self.assertEqual((val(out, V_QUAKE, "p-a"), val(out, V_LONG, "p-a")), (30_000, 0))


class TestDonationInputs(unittest.TestCase):
    """所法78②（…hoken-kifu-laws.md §4）。"""

    def _rec(self, rid: str = "d1", recipient: str = "local_government", **attrs: Any) -> dict[str, Any]:
        return {"id": rid, "kind": "donation", "roles": {"donor": "p-a"}, "when": {"on": "2026-05-01"}, "amounts": {"amount": 30_000}, "attributes": {"recipient_name": "架空市", "recipient_type": recipient, **attrs}}

    def test_government_donation_is_counted(self) -> None:
        self.assertEqual(val(run(make_ir([person("p-a")], [self._rec()]), 2026), V_DON, "p-a"), 30_000)

    def test_return_gift_does_not_reduce(self) -> None:
        # 質疑応答事例 02/37：返礼品は一時所得の問題で、寄附金の額を減らさない（…hoken-kifu-nta-soumu.md §3.5）
        rec = self._rec()
        rec["amounts"]["return_gift_value"] = 9_000
        rec["attributes"]["return_gift"] = True
        self.assertEqual(val(run(make_ir([person("p-a")], [rec]), 2026), V_DON, "p-a"), 30_000)

    def test_other_recipients_are_read_both_ways(self) -> None:
        # 日本赤十字社は特定公益増進法人（TA1150）。共同募金会は記載によらず特定寄附金（impl-research4 juminzei-kifu §2.1・§2.3、仮説 H11、推測 I10）。
        # other は語彙にない区分（事実）→ 未確定
        for kind in ("japanese_red_cross", "community_chest"):
            with self.subTest(kind=kind):
                out = run(make_ir([person("p-a")], [self._rec(recipient=kind)]), 2026)
                self.assertEqual((reasons(out, V_DON, "p-a"), val(out, V_DON, "p-a"), missing(out, V_DON, "p-a")), ([], 30_000, []))
        out = run(make_ir([person("p-a")], [self._rec(recipient="other")]), 2026)
        self.assertEqual((reasons(out, V_DON, "p-a"), val(out, V_DON, "p-a"), missing(out, V_DON, "p-a")), ([], 30_000, ["事実"]))
        rec = self._rec()
        del rec["attributes"]["recipient_type"]
        self.assertTrue(any("recipient_type" in r for r in reasons(run(make_ir([person("p-a")], [rec]), 2026), V_DON, "p-a")))

    def test_receipt_statement_settles_other_recipients(self) -> None:
        # 所法78②二〜四：受領証等の記載（指定寄附金・特定公益増進法人の業務・公益信託）で特定寄附金。other で記載なしは当たらない
        cases = (
            ("other", "designated_donation", 30_000),
            ("other", "specified_public_interest_business", 30_000),
            ("other", "public_interest_trust", 30_000),
            ("other", "none", 0),
            ("community_chest", "designated_donation", 30_000),
        )
        for kind, statement, expected in cases:
            with self.subTest(kind=kind, statement=statement):
                out = run(make_ir([person("p-a")], [self._rec(recipient=kind, receipt_statement=statement)]), 2026)
                self.assertEqual((reasons(out, V_DON, "p-a"), val(out, V_DON, "p-a"), missing(out, V_DON, "p-a")), ([], expected, []))
        # 共同募金会は「記載なし」でも特定寄附金（所令217①五・告示154号第4号・第4号の2：impl-research4 juminzei-kifu §2.1・§2.3）
        chest = run(make_ir([person("p-a")], [self._rec(recipient="community_chest", receipt_statement="none")]), 2026)
        self.assertEqual((val(chest, V_DON, "p-a"), missing(chest, V_DON, "p-a")), (30_000, []))

    def test_credit_type_recipients_follow_the_choice(self) -> None:
        # 税額控除か所得控除かの選択（措法41の18①②・41の18の2①②。[SK] §1・§2）。未入力は候補を開く
        for kind, slot_kind, var in (
            ("political_party", "政党等", "所得税_税額控除を受ける政党等寄附金の額"),
            ("certified_npo", "認定NPO法人等", "所得税_税額控除を受ける認定NPO法人等寄附金の額"),
            ("public_interest_corporation", "公益社団法人等", "所得税_税額控除を受ける公益社団法人等寄附金の額"),
            ("school_corporation", "公益社団法人等", "所得税_税額控除を受ける公益社団法人等寄附金の額"),
        ):
            with self.subTest(kind=kind):
                ir = make_ir([person("p-a")], [self._rec(recipient=kind)])
                sid = f"選択.寄附金の控除の方式:p-a:{slot_kind}"
                self.assertIn(sid, open_slots(ir, 2026))
                self.assertEqual(val(run(ir, 2026, {sid: "tax_credit"}), var, "p-a"), 30_000)
                self.assertEqual(val(run(ir, 2026, {sid: "tax_credit"}), V_DON, "p-a"), 0)
                self.assertEqual(val(run(ir, 2026, {sid: "income_deduction"}), V_DON, "p-a"), 30_000)
                self.assertEqual(val(run(ir, 2026, {sid: "income_deduction"}), var, "p-a"), 0)

    def test_candidate_branch_donation_excluded_in_r8(self) -> None:
        # 令和8年分：公職の候補者が特定政党支部に対してする寄附は対象外（[SK] §4、令和7年法律第2号附則第5条）
        rec = self._rec(recipient="political_party")
        rec["attributes"]["candidate_to_specified_party_branch"] = True
        out = run(make_ir([person("p-a")], [rec]), 2026, {})
        self.assertEqual(val(out, "所得税_税額控除を受ける政党等寄附金の額", "p-a"), 0)
        self.assertEqual(val(out, V_DON, "p-a"), 0)

    def test_judgment_excludes_special_benefit(self) -> None:
        ir = make_ir([person("p-a")], [self._rec()], judgments=[judgment("j", "判断.寄附の性質", {"donation_id": "d1"}, {"special_benefit": True})])
        self.assertEqual(val(run(ir, 2026), V_DON, "p-a"), 0)

    def test_admission_facts_open_a_slot(self) -> None:
        ir = make_ir([person("p-a")], [self._rec(admission_related_facts="架空の入学に関する事実")])
        sid = "判断.寄附の性質:d1"
        self.assertIn(sid, open_slots(ir, 2026))
        self.assertEqual(val(run(ir, 2026, {sid: False}), V_DON, "p-a"), 30_000)
        self.assertEqual(val(run(ir, 2026, {sid: True}), V_DON, "p-a"), 0)

    def test_outside_year_is_not_counted(self) -> None:
        self.assertEqual(val(run(make_ir([person("p-a")], [self._rec()]), 2025), V_DON, "p-a"), 0)


if __name__ == "__main__":
    unittest.main()
