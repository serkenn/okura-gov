"""意味の検査（validate.py）のテスト。有効な例を少しずつ変えて確かめる。"""

from __future__ import annotations

import copy
import json
import unittest
from importlib import resources

from okura_ir import validate

VALID = resources.files("okura_ir").joinpath("examples", "valid")


def load_example(name: str) -> dict:
    return json.loads((VALID / name).read_text(encoding="utf-8"))


STUDENT = "01_student_away_and_parent_on_assignment.json"
MEDICAL = "02_medical_payer_differs_from_patient.json"
BUSINESS = "03_business_with_household_apportionment.json"


def codes(ir) -> list[tuple[str, str]]:
    return sorted((p.code, p.path) for p in validate(ir))


def index_of(records: list[dict], record_id: str) -> int:
    return next(i for i, r in enumerate(records) if r["id"] == record_id)


class ReferenceTest(unittest.TestCase):
    def test_kind_reference_mismatch_in_subject(self) -> None:
        ir = load_example(MEDICAL)
        i = index_of(ir["judgments"], "j-taxi-scope")
        ir["judgments"][i]["subject"]["payment_id"] = "sip-g-1"  # 社会保険料の支払
        self.assertEqual(codes(ir), [("reference_kind_mismatch", f"$.judgments[{i}].subject.payment_id")])

    def test_unknown_record_in_basis(self) -> None:
        ir = load_example(STUDENT)
        ir["judgments"][0]["basis"]["record_ids"].append("f-nowhere")
        self.assertEqual(codes(ir), [("unknown_reference", "$.judgments[0].basis.record_ids[3]")])

    def test_section_reference_mismatch(self) -> None:
        ir = load_example(STUDENT)
        ir["filed_documents"][0]["attributes"]["realized_choice_ids"] = ["j-livelihood-ac"]
        self.assertEqual(
            codes(ir), [("reference_kind_mismatch", "$.filed_documents[0].attributes.realized_choice_ids[0]")]
        )

    def test_record_reference_cannot_point_to_a_person(self) -> None:
        ir = load_example(STUDENT)
        ir["judgments"][0]["basis"]["record_ids"] = ["p-a"]
        self.assertEqual(codes(ir), [("unknown_reference", "$.judgments[0].basis.record_ids[0]")])

    def test_person_in_value_and_list_attributes_are_checked(self) -> None:
        ir = load_example(STUDENT)
        ir["choices"][0]["value"]["filer"] = "p-z"
        ir["filed_documents"][0]["attributes"]["entries"][0]["person"] = "p-y"
        self.assertEqual(
            codes(ir),
            [
                ("unknown_person", "$.choices[0].value.filer"),
                ("unknown_person", "$.filed_documents[0].attributes.entries[0].person"),
            ],
        )

    def test_judge_person_must_exist_but_label_is_free(self) -> None:
        ir = load_example(STUDENT)
        ir["judgments"][0]["judged_by"] = {"person": "p-q"}
        ir["judgments"][1]["judged_by"] = {"label": "家族の外の判断者"}
        self.assertEqual(codes(ir), [("unknown_person", "$.judgments[0].judged_by.person")])

    def test_ids_are_unique_across_sections(self) -> None:
        ir = load_example(STUDENT)
        ir["choices"][0]["id"] = "f-enroll-c"
        ir["filed_documents"][0]["attributes"]["realized_choice_ids"] = ["f-enroll-c"]
        problems = codes(ir)
        self.assertIn(("duplicate_id", "$.choices[0].id"), problems)


class IntervalTest(unittest.TestCase):
    def test_adjacent_resident_records_do_not_overlap(self) -> None:
        self.assertEqual(codes(load_example(STUDENT)), [])

    def test_open_ended_resident_record_overlaps_later_one(self) -> None:
        ir = load_example(STUDENT)
        i = index_of(ir["residences"], "res-a-1")
        del ir["residences"][i]["when"]["to_on"]
        j = index_of(ir["residences"], "res-a-2")
        self.assertEqual(codes(ir), [("overlapping_interval", f"$.residences[{j}].when")])

    def test_overlap_hidden_behind_a_short_interval(self) -> None:
        ir = load_example(STUDENT)
        base = {"kind": "resident_record", "roles": {"person": "p-c"},
                "attributes": {"municipality_code": "990003", "household_id": "hh-3", "householder": True}}
        ir["residences"] = [
            {**base, "id": "r-long", "when": {"from_on": "2020-01-01", "to_on": "2030-12-31"}},
            {**base, "id": "r-short", "when": {"from_on": "2021-01-01", "to_on": "2021-12-31"}},
            {**base, "id": "r-late", "when": {"from_on": "2023-01-01"}},
        ]
        self.assertEqual(
            codes(ir),
            [("overlapping_interval", "$.residences[1].when"), ("overlapping_interval", "$.residences[2].when")],
        )

    def test_free_text_allows_newlines_but_not_other_controls(self) -> None:
        ir = load_example(STUDENT)
        ir["relations"][3]["note"] = "1行目\r\n2行目\tタブ"
        self.assertEqual(codes(ir), [])
        ir["relations"][3]["note"] = "垂直タブ\x0b"
        self.assertEqual(codes(ir), [("pattern", "$.relations[3].note")])

    def test_period_inside_attributes_is_checked(self) -> None:
        ir = load_example(MEDICAL)
        i = index_of(ir["facts"], "sip-g-1")
        ir["facts"][i]["attributes"]["prepaid_period"] = {"from_on": "2026-04-01", "to_on": "2026-03-31"}
        self.assertEqual(codes(ir), [("period_reversed", f"$.facts[{i}].attributes.prepaid_period")])


class MembershipTest(unittest.TestCase):
    def test_insured_role_on_insured_capacity(self) -> None:
        ir = load_example(STUDENT)
        ir["insurance_memberships"][0]["roles"]["insured"] = "p-b"
        self.assertEqual(codes(ir), [("unexpected_insured_person", "$.insurance_memberships[0].roles.insured")])

    def test_dependent_of_oneself(self) -> None:
        ir = load_example(STUDENT)
        ir["insurance_memberships"][1]["roles"]["insured"] = "p-b"
        self.assertEqual(codes(ir), [("same_person", "$.insurance_memberships[1].roles")])


class ReplacementTest(unittest.TestCase):
    def test_valid_chain_of_three(self) -> None:
        ir = load_example(BUSINESS)
        i = index_of(ir["judgments"], "j-rent-ratio-v2")
        v3 = copy.deepcopy(ir["judgments"][i])
        v3.update(id="j-rent-ratio-v3", replaces="j-rent-ratio-v2", judged_at="2026-04-01T09:00:00+09:00")
        ir["judgments"].append(v3)
        self.assertEqual(codes(ir), [])

    def test_choice_replacement_rules_are_the_same(self) -> None:
        ir = load_example(BUSINESS)
        c2 = copy.deepcopy(ir["choices"][0])
        c2.update(id="c-ct-method-2026-v2", replaces="c-ct-method-2026", chosen_at="2025-01-01T00:00:00+09:00")
        ir["choices"].append(c2)
        self.assertEqual(codes(ir), [("replacement_time_order", "$.choices[2].replaces")])

    def test_choice_cannot_replace_a_judgment(self) -> None:
        ir = load_example(BUSINESS)
        ir["choices"][0]["replaces"] = "j-rent-ratio-v1"
        self.assertEqual(codes(ir), [("reference_kind_mismatch", "$.choices[0].replaces")])

    def test_self_replacement_is_a_cycle(self) -> None:
        ir = load_example(BUSINESS)
        i = index_of(ir["judgments"], "j-power-ratio")
        ir["judgments"][i]["replaces"] = "j-power-ratio"
        self.assertEqual(codes(ir), [("replacement_cycle", f"$.judgments[{i}].replaces")])

    def test_self_replacement_of_an_already_replaced_judgment_is_also_a_fork(self) -> None:
        ir = load_example(BUSINESS)
        ir["judgments"][0]["replaces"] = ir["judgments"][0]["id"]  # v1 は v2 にも置き換えられている
        self.assertEqual(
            codes(ir),
            [("replacement_cycle", "$.judgments[0].replaces"), ("replacement_fork", "$.judgments[1].replaces")],
        )

    def test_cycle_of_three_is_reported_once_at_the_smallest_id(self) -> None:
        from okura_ir.validate import _replacement_problems

        def j(rid: str, replaces: str | None) -> dict:
            r = {"id": rid, "kind": "判断.事実婚", "judged_at": "2026-01-01T00:00:00+09:00"}
            if replaces is not None:
                r["replaces"] = replaces
            return r

        # 入口（j-0 → j-1）から循環（j-1 → j-2 → j-3 → j-1）に入る。始点の順によらず1回だけ出す
        ir = {"judgments": [j("j-0", "j-1"), j("j-1", "j-2"), j("j-2", "j-3"), j("j-3", "j-1")]}
        problems = [p for p in _replacement_problems(ir, "judgments", "judged_at") if p.code == "replacement_cycle"]
        self.assertEqual([p.path for p in problems], ["$.judgments[1].replaces"])
        self.assertIn("j-1 → j-2 → j-3", problems[0].message)

    def test_long_chain_is_checked_in_linear_time(self) -> None:
        """長い置き換えの連鎖（3,000 件）。以前の実装は始点ごとに終わりまでたどり、3乗の時間がかかった（約 3 分）。"""
        import time

        from okura_ir.validate import _replacement_problems

        n = 3000
        records = [{"id": f"j-{i:05d}", "kind": "判断.事実婚", "judged_at": "2026-01-01T00:00:00+09:00"} for i in range(n)]
        for i in range(1, n):
            records[i]["replaces"] = records[i - 1]["id"]
        t0 = time.perf_counter()
        self.assertEqual(_replacement_problems({"judgments": records}, "judgments", "judged_at"), [])
        records[0]["replaces"] = records[-1]["id"]  # 端をつなぐと全体が1つの循環
        cyc = _replacement_problems({"judgments": records}, "judgments", "judged_at")
        self.assertLess(time.perf_counter() - t0, 10.0)
        self.assertEqual([(p.code, p.path) for p in cyc], [("replacement_cycle", "$.judgments[0].replaces")])

    def test_time_order_compares_offsets(self) -> None:
        ir = load_example(BUSINESS)
        i = index_of(ir["judgments"], "j-rent-ratio-v2")
        # 2026-01-28T09:00+09:00 は 2026-01-28T00:00Z。それより 1 秒後なら合格、1 秒前なら不合格
        ir["judgments"][i]["judged_at"] = "2026-01-28T00:00:01Z"
        self.assertEqual(codes(ir), [])
        ir["judgments"][i]["judged_at"] = "2026-01-27T23:59:59Z"
        self.assertEqual(codes(ir), [("replacement_time_order", f"$.judgments[{i}].replaces")])


class OrderOfChecksTest(unittest.TestCase):
    def test_semantic_checks_wait_for_schema_problems(self) -> None:
        ir = load_example(MEDICAL)
        ir["facts"][0]["amounts"]["amount"] = "120000"
        ir["facts"][0]["roles"]["payer"] = "p-nobody"
        self.assertEqual(codes(ir), [("type", "$.facts[0].amounts.amount")])

    def test_validate_does_not_mutate_and_is_deterministic(self) -> None:
        ir = load_example(BUSINESS)
        ir["judgments"][0]["value"]["ratio"] = {"num": 5, "den": 4}
        before = copy.deepcopy(ir)
        first = validate(ir)
        second = validate(ir)
        self.assertEqual(ir, before)
        self.assertEqual(first, second)
        self.assertEqual([(p.code, p.path) for p in first], [("ratio_out_of_range", "$.judgments[0].value.ratio")])


if __name__ == "__main__":
    unittest.main()
