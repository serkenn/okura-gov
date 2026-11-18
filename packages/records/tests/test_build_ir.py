"""build_ir の検査：架空の家庭から作った中間表現が okura_ir の検査に通ること、変換の規則、問題の出どころ。"""

from __future__ import annotations

import copy
import json
import os
import unittest

from okura_ir import validate

from okura_records import facts_ledger, judgments_ledger
from okura_records.build_ir import IR_SECTIONS, build_ir
from okura_records.meta_vocabulary import TRANSACTION_FACT_KINDS, field_shape

from .helpers import fresh_dir, household_fact_entries, household_judgment_entries, jsonl, write_household

FACTS, _ = facts_ledger.read(jsonl(household_fact_entries()), "facts.jsonl")
JUDGMENTS, _ = judgments_ledger.read(jsonl(household_judgment_entries()), "judgments.jsonl")


def household_transactions() -> dict:
    from okura_records.adapter import normalize
    from okura_records.safe_loader import load_ledger

    with fresh_dir() as d:
        write_household(d)
        loaded = load_ledger(os.path.join(d, "main.beancount"))
        doc, problems = normalize(loaded.ledger)
        assert not problems, problems
        return doc


TX_DOC = household_transactions()


def tx(meta: dict, postings: list | None = None, *, tx_id: str = "tx-1", flag: str = "*", date: str = "2026-02-10", line: int = 10) -> dict:
    return {
        "id": tx_id,
        "date": date,
        "flag": flag,
        "payee": "架空の店",
        "narration": "架空の説明",
        "tags": [],
        "links": [],
        "meta": {"id": {"string": tx_id}, **meta},
        "postings": postings
        if postings is not None
        else [
            {"account": "Expenses:Misc", "account_root": "expenses", "amount": 1000, "currency": "JPY", "interpolated": False,
             "meta": {"fact_amount": {"string": "amount"}}},
            {"account": "Assets:Cash", "account_root": "assets", "amount": -1000, "currency": "JPY", "interpolated": True, "meta": {}},
        ],
        "source": {"file": "main.beancount", "line": line},
    }


def doc_with(*transactions: dict, documents: list | None = None) -> dict:
    return {"format": "okura-transactions/0", "currency": "JPY", "main": "main.beancount", "source_files": [],
            "transactions": list(transactions), "documents": documents or []}


def s(value: str) -> dict:
    return {"string": value}


def codes(result) -> set[str]:
    return {p.code for p in result.problems}


class HouseholdTests(unittest.TestCase):
    def test_household_builds_valid_ir(self):
        result = build_ir(TX_DOC, FACTS, JUDGMENTS)
        self.assertTrue(result.ok, [p.to_dict() for p in result.problems])
        ir = result.ir
        self.assertEqual(validate(ir), [])
        self.assertEqual(list(ir), ["schema_version", *IR_SECTIONS])
        facts = {f["id"]: f for f in ir["facts"]}
        hospital = facts["tx-2026-0210-hospital"]
        self.assertEqual(hospital["roles"], {"payer": "p-a", "patient": "p-g"})
        self.assertEqual(hospital["when"], {"on": "2026-02-10"})
        self.assertEqual(hospital["amounts"], {"amount": 120000})
        self.assertEqual(hospital["attributes"]["medical_kinds"], ["medical_treatment", "hospitalization"])
        self.assertEqual(hospital["attributes"]["incurred_on"], "2026-01-28")
        self.assertEqual(len(hospital["source"]["evidence_sha256"]), 1)
        salary = facts["tx-2026-0125-salary-a"]
        self.assertEqual(salary["amounts"], {"gross": 300000, "withholding_tax": 8000, "social_insurance_withheld": 45000})
        self.assertEqual(salary["attributes"]["due_on"], "2026-01-25")  # D23 K3：支給日は必須
        # fact_kind の無い記帳は事実にしない
        self.assertNotIn("tx-2026-0430-withdrawal", facts)
        # 事実台帳の記録：record.recorded_at は行の記録日時
        self.assertEqual(facts["biz-b"]["recorded_at"], "2026-01-05T20:00:00+09:00")
        self.assertNotIn("recorded_at", ir["persons"][0])
        # 判断の見直しの連鎖は中間表現に残る（判定コアが先頭を使う）
        self.assertEqual(
            [j["id"] for j in ir["judgments"]], ["j-livelihood-ac", "j-taxi-scope", "j-elec-ratio-v1", "j-elec-ratio-v2", "j-below-c"]
        )
        self.assertEqual(ir["judgments"][2]["recorded_at"], "2026-03-21T09:30:00+09:00")

    def test_no_narration_payee_account_or_memo_in_ir(self):
        text = json.dumps(build_ir(TX_DOC, FACTS, JUDGMENTS).ir, ensure_ascii=False)
        for word in ("入院費", "1月分の給与", "Expenses:", "Liabilities:", "歩行が困難なため", "事実にしない記帳"):
            self.assertNotIn(word, text)

    def test_pure_and_deterministic(self):
        before = copy.deepcopy(TX_DOC)
        first = build_ir(TX_DOC, FACTS, JUDGMENTS)
        second = build_ir(TX_DOC, FACTS, JUDGMENTS)
        self.assertEqual(json.dumps(first.ir, ensure_ascii=False), json.dumps(second.ir, ensure_ascii=False))
        self.assertEqual(TX_DOC, before)
        first.ir["facts"][0]["id"] = "changed"
        self.assertNotEqual(FACTS.records[0].record.get("id"), "changed")
        self.assertNotEqual(build_ir(TX_DOC, FACTS, JUDGMENTS).ir["facts"][0]["id"], "changed")

    def test_ledger_records_of_2026_11_12_vocabulary_are_copied_as_is(self):
        # 事実台帳の 2026-11-12 の種類・欄は、記録をそのまま写す（recorded_at だけ足す）
        extra = [
            ("persons", {"id": "p-d", "birth_on": "1950-01-01", "death_on": "2025-12-01"}),
            ("facts", {"id": "birth-b", "kind": "childbirth", "roles": {"person": "p-b"}, "when": {"on": "2026-08-20"},
                       "attributes": {"expected_delivery_on": "2026-08-25", "delivered_on": "2026-08-20", "multiple_birth": False,
                                      "child_ids": ["p-c"]}}),
            ("facts", {"id": "sap-b", "kind": "special_adoption_petition", "roles": {"petitioner": "p-b", "child": "p-c"},
                       "when": {"from_on": "2026-09-01"}}),
            ("facts", {"id": "npi-app-c", "kind": "npi_application", "roles": {"person": "p-c"}, "when": {"from_on": "2026-04-01"},
                       "attributes": {"application_type": "statutory_exemption_payment", "applied_on": "2026-04-01"}}),
            ("facts", {"id": "liq-d", "kind": "estate_liquidator", "roles": {"decedent": "p-d"}, "when": {"on": "2026-05-10"},
                       "attributes": {"liquidator_name": "架空の弁護士"}}),
            ("facts", {"id": "kh-g", "kind": "kokuho_event", "roles": {"person": "p-g"}, "when": {"from_on": "2026-04-01"},
                       "attributes": {"event": "institution_special_case", "admission_type": "hospital", "deemed_household_id": "hh-1"}}),
            ("relations", {"id": "foster-bx", "kind": "foster_placement", "roles": {"caregiver": "p-b", "placed_person": "p-d"},
                           "when": {"from_on": "2026-01-01"}, "attributes": {"placement": "foster_child", "foster_parent_type": "other"}}),
            ("assets", {"id": "a-pc-b", "kind": "depreciable_asset", "roles": {"owner": "p-b"}, "when": {"from_on": "2026-03-01"},
                        "amounts": {"acquisition_cost": 200000},
                        "attributes": {"name": "パソコン（架空）", "business_id": "biz-b", "receipt_id": "tx-2026-0315-design"}}),
        ]
        entries = household_fact_entries()
        for n, (section, record) in enumerate(extra, start=100):
            entries.append({"ledger": "okura-facts/0", "entry_id": f"fe-{n:04d}", "recorded_at": "2026-07-01T00:00:00+09:00",
                            "recorded_by": {"person": "p-a"}, "op": "add", "section": section, "record": record})
        facts, problems = facts_ledger.read(jsonl(entries), "facts.jsonl")
        self.assertEqual(problems, [])
        result = build_ir(TX_DOC, facts, JUDGMENTS)
        self.assertTrue(result.ok, [p.to_dict() for p in result.problems])
        for section, record in extra:
            with self.subTest(record=record["id"]):
                got = next(r for r in result.ir[section] if r["id"] == record["id"])
                expected = dict(record) if section == "persons" else {**record, "recorded_at": "2026-07-01T00:00:00+09:00"}
                self.assertEqual(got, expected)
        # 例の家庭の台帳の記録（国民年金基金・年金の受給権の制度と障害等級・学生納付特例対象校一覧・課税証明書・保険の契約）
        ir = result.ir
        memberships = {m["id"]: m for m in ir["insurance_memberships"]}
        self.assertEqual(memberships["npf-b"]["kind"], "national_pension_fund")
        self.assertEqual(memberships["pe-g-rosai"]["attributes"],
                         {"benefit": "disability", "scheme": "workers_accident_compensation", "disability_grade": 2})
        facts_by_id = {f["id"]: f for f in ir["facts"]}
        self.assertIs(facts_by_id["enr-c"]["attributes"]["npi_student_school_listed"], True)  # 行の訂正の後
        self.assertEqual(facts_by_id["cert-b-2026"]["amounts"], {"total_income": 800000})

    def test_all_transaction_fields_have_a_shape(self):
        for kind in TRANSACTION_FACT_KINDS.values():
            for name, fld in list(kind.attributes.items()) + list(kind.amounts.items()):
                with self.subTest(kind=kind.kind, field=name):
                    self.assertNotEqual(field_shape(fld.schema), "unsupported")


class ConversionTests(unittest.TestCase):
    def build_one(self, transaction: dict, documents: list | None = None):
        # 判断台帳が家庭の取引を参照するので、家庭の取引に1件を足して作る
        doc = doc_with(*TX_DOC["transactions"], transaction, documents=TX_DOC["documents"] + (documents or []))
        return build_ir(doc, FACTS, JUDGMENTS)

    def fact(self, transaction: dict, documents: list | None = None) -> dict:
        result = self.build_one(transaction, documents)
        self.assertTrue(result.ok, [p.to_dict() for p in result.problems])
        return next(f for f in result.ir["facts"] if f["id"] == transaction["id"])

    def test_value_shapes(self):
        remittance = tx(
            {
                "fact_kind": s("remittance"),
                "sender": s("p-a"),
                "recipient": s("p-c"),
                "method": s("bank_transfer"),
                "foreign_amount": {"amount": {"number": "123.45", "currency": "USD"}},
                "exchange_rate": s("15025/100"),
                "beneficiaries": s("p-c p-g"),
                "used_on": {"date": "2026-02-11"},
                "fee": {"amount": {"number": "500", "currency": "JPY"}},
                "mark": s("予測"),
                "note": s("留学先への送金（架空）"),
                "memo": s("写さない"),
                "x_ref": {"decimal": "3"},
            }
        )
        fact = self.fact(remittance)
        self.assertEqual(fact["attributes"]["foreign_amount"], {"currency": "USD", "value": {"num": 2469, "den": 20}})
        self.assertEqual(fact["attributes"]["exchange_rate"], {"num": 15025, "den": 100})
        self.assertEqual(fact["attributes"]["beneficiaries"], ["p-c", "p-g"])
        self.assertEqual(fact["amounts"], {"amount": 1000, "fee": 500})
        self.assertEqual(fact["mark"], "予測")
        self.assertEqual(fact["note"], "留学先への送金（架空）")
        self.assertNotIn("memo", json.dumps(fact, ensure_ascii=False))

    def test_period_and_bool_and_int(self):
        insurance = tx(
            {
                "fact_kind": s("social_insurance_payment"),
                "payer": s("p-a"),
                "liable_person": s("p-c"),
                "premium_type": s("national_pension"),
                "prepaid_period": s("2026-04-01/2027-03-31"),
                "payroll_deduction": {"bool": False},
            }
        )
        fact = self.fact(insurance)
        self.assertEqual(fact["attributes"]["prepaid_period"], {"from_on": "2026-04-01", "to_on": "2027-03-31"})
        self.assertIs(fact["attributes"]["payroll_deduction"], False)
        benefit = tx({"fact_kind": s("benefit_receipt"), "recipient": s("p-c"), "benefit_type": s("scholarship_grant"),
                      "period": s("2026-04-01/.."), "daily_amount": {"amount": {"number": "0", "currency": "JPY"}}},
                     [{"account": "Income:Grant", "account_root": "income", "amount": -50000, "currency": "JPY",
                       "interpolated": False, "meta": {"fact_amount": s("amount")}}])
        fact = self.fact(benefit)
        self.assertEqual(fact["when"], {"from_on": "2026-04-01"})
        self.assertEqual(fact["amounts"], {"amount": 50000, "daily_amount": 0})

    def test_vocabulary_added_2026_11_11(self):
        # 語彙の追加（packages/ir/README.md §6.2）：取引のメタデータから中間表現の欄へそのまま写る
        bonus = tx(
            {
                "fact_kind": s("salary_payment"),
                "recipient": s("p-a"),
                "counterparty": s("架空商事"),
                "payment_type": s("officer_bonus_by_resolution"),
                "due_on": {"date": "2026-06-30"},
                "resolution_on": {"date": "2026-05-20"},
                "amount_fixed_on": {"date": "2026-05-25"},
                "paid_outside_japan": {"bool": False},
                "payer_withholding_exempt_household": {"bool": False},
                "payer_family_company_officer": {"bool": True},
                "interest_or_rent_from_payer": {"bool": True},
            },
            [{"account": "Income:Salary", "account_root": "income", "amount": -500000, "currency": "JPY",
              "interpolated": False, "meta": {"fact_amount": s("gross")}},
             {"account": "Assets:Bank", "account_root": "assets", "amount": 500000, "currency": "JPY", "interpolated": True, "meta": {}}],
            tx_id="tx-bonus",
        )
        a = self.fact(bonus)["attributes"]
        self.assertEqual((a["resolution_on"], a["amount_fixed_on"]), ("2026-05-20", "2026-05-25"))
        self.assertEqual((a["payer_family_company_officer"], a["interest_or_rent_from_payer"]), (True, True))
        donation = tx(
            {
                "fact_kind": s("donation"),
                "donor": s("p-a"),
                "recipient_name": s("架空市"),
                "recipient_type": s("local_government"),
                "recipient_local_government_code": s("990001"),
                "recipient_local_government_kind": s("municipality"),
            },
            tx_id="tx-furusato",
        )
        a = self.fact(donation)["attributes"]
        self.assertEqual((a["recipient_local_government_code"], a["recipient_local_government_kind"]), ("990001", "municipality"))

    def test_vocabulary_added_2026_11_12(self):
        # 2026-11-12 の語彙の追加（packages/ir/README.md §6.2）：取引のメタデータから中間表現の欄へそのまま写る
        salary = tx(
            {
                "fact_kind": s("salary_payment"),
                "recipient": s("p-c"),
                "payer": s("p-b"),
                "counterparty": s("架空のデザイン業"),
                "payment_type": s("bonus"),
                "due_on": {"date": "2026-12-10"},
                "unpaid": {"bool": True},
                "uncollectible_amount": {"amount": {"number": "40000", "currency": "JPY"}},
                "uncollectible_on": {"date": "2027-01-31"},
                "prior_month_net_salary": {"amount": {"number": "0", "currency": "JPY"}},
                "payer_business_id": s("biz-b"),
                "paid_by_foreign_mission": {"bool": False},
                "pay_period": s("multiple_months"),
                "pay_period_months": {"decimal": "6"},
            },
            [{"account": "Income:Salary", "account_root": "income", "amount": -40000, "currency": "JPY",
              "interpolated": False, "meta": {"fact_amount": s("gross")}},
             {"account": "Assets:Receivable", "account_root": "assets", "amount": 40000, "currency": "JPY", "interpolated": True, "meta": {}}],
            tx_id="tx-unpaid-bonus",
        )
        fact = self.fact(salary)
        self.assertEqual(fact["amounts"], {"gross": 40000, "uncollectible_amount": 40000, "prior_month_net_salary": 0})
        a = fact["attributes"]
        self.assertEqual((a["uncollectible_on"], a["payer_business_id"], a["pay_period"], a["pay_period_months"]),
                         ("2027-01-31", "biz-b", "multiple_months", 6))
        self.assertIs(a["paid_by_foreign_mission"], False)
        expense = tx({"fact_kind": s("business_expense"), "payer": s("p-b"), "business_id": s("biz-b"),
                      "expense_category": s("materials"), "receipt_id": s("tx-2026-0315-design")}, tx_id="tx-material")
        self.assertEqual(self.fact(expense)["attributes"]["receipt_id"], "tx-2026-0315-design")
        donation = tx({"fact_kind": s("donation"), "donor": s("p-a"), "recipient_name": s("架空の支部"),
                       "recipient_type": s("japanese_red_cross"), "receipt_statement": s("none"),
                       "recipient_office_prefecture_code": s("990001"), "mic_approved_solicitation": {"bool": False},
                       "onestop_request_municipality_code": s("990011")}, tx_id="tx-red-cross")
        a = self.fact(donation)["attributes"]
        self.assertEqual((a["recipient_office_prefecture_code"], a["mic_approved_solicitation"], a["onestop_request_municipality_code"]),
                         ("990001", False, "990011"))

    def test_date_list(self):
        # 日付の並び（prepaid_due_dates）：空白区切りの文字列 → 日付の配列。並べ替え・重複の除去をしない（書いた順のまま）
        prepay = tx({"fact_kind": s("social_insurance_payment"), "payer": s("p-a"), "liable_person": s("p-c"),
                     "premium_type": s("national_pension"), "prepaid_due_dates": s("2027-01-31  2026-12-31 2026-12-31")}, tx_id="tx-prepay")
        self.assertEqual(self.fact(prepay)["attributes"]["prepaid_due_dates"], ["2027-01-31", "2026-12-31", "2026-12-31"])
        household = {f["id"]: f for f in build_ir(TX_DOC, FACTS, JUDGMENTS).ir["facts"]}
        self.assertEqual(household["tx-2026-1120-life-prepay"]["attributes"]["prepaid_due_dates"], ["2026-12-01", "2027-12-01"])
        self.assertEqual(len(household["tx-2026-1030-npi-prepay"]["attributes"]["prepaid_due_dates"]), 6)

    def test_evidence_attached(self):
        documents = [{"date": "2026-02-10", "account": "Expenses:Misc", "path": "r.pdf", "sha256": "b" * 64, "bytes": 1,
                      "transaction_id": "tx-1", "tags": [], "links": [], "meta": {}, "source": {"file": "main.beancount", "line": 20}},
                     {"date": "2026-02-10", "account": "Expenses:Misc", "path": "a.pdf", "sha256": "a" * 64, "bytes": 1,
                      "transaction_id": "tx-1", "tags": [], "links": [], "meta": {}, "source": {"file": "main.beancount", "line": 21}}]
        donation = tx({"fact_kind": s("donation"), "donor": s("p-a"), "recipient_name": s("架空市")})
        self.assertEqual(self.fact(donation, documents)["source"], {"transaction_ids": ["tx-1"], "evidence_sha256": ["a" * 64, "b" * 64]})


class ProblemTests(unittest.TestCase):
    def check(self, transaction: dict, code: str):
        result = build_ir(doc_with(*TX_DOC["transactions"], transaction, documents=TX_DOC["documents"]), FACTS, JUDGMENTS)
        self.assertIsNone(result.ir)
        self.assertIn(code, codes(result), [p.to_dict() for p in result.problems])
        return result

    def test_fact_kind_problems(self):
        self.check(tx({"fact_kind": s("medical")}), "fact_kind_unknown")
        self.check(tx({"fact_kind": s("business")}), "fact_kind_unknown")  # 取引から作らない種類（事実台帳に書く）
        self.check(tx({"fact_kind": {"decimal": "1"}}), "fact_kind_unknown")
        self.check(tx({"payer": s("p-a")}, []), "fact_keys_without_kind")
        self.check(tx({}), "fact_keys_without_kind")  # fact_amount だけある

    def test_key_and_value_problems(self):
        base = {"fact_kind": s("medical_payment"), "payer": s("p-a"), "patient": s("p-g"), "medical_kinds": s("medicine")}
        self.check(tx({**base, "incurred_on": {"date": "2026-02-01"}, "sender": s("p-a")}), "fact_key_not_for_kind")
        self.check(tx({**base, "incurred_on": s("2026-02-01")}), "fact_value_type")
        self.check(tx({**base, "incurred_on": {"date": "2026-02-01"}, "payer": {"decimal": "1"}}), "fact_value_type")
        self.check(tx({**base, "incurred_on": {"date": "2026-02-01"}, "medical_kinds": s("  ")}), "fact_value_type")
        self.check(tx({**base, "incurred_on": {"date": "2026-02-01"}, "period": s("2026-01-01/..")}), "fact_when")
        self.check(tx({**base, "incurred_on": {"date": "2026-02-01"}}, flag="!"), "fact_flag_pending")
        prepay = {"fact_kind": s("social_insurance_payment"), "payer": s("p-a"), "liable_person": s("p-c"), "premium_type": s("other")}
        for bad in ("2026-02-30", "2026/11/30", "2026-11-30,2026-12-31", "20261130", " ", "２０２６-１１-３０"):
            with self.subTest(prepaid_due_dates=bad):
                self.check(tx({**prepay, "prepaid_due_dates": s(bad)}), "fact_value_type")
        self.check(tx({**prepay, "prepaid_due_dates": {"date": "2026-11-30"}}), "fact_value_type")  # 文字列で書く

    def test_amount_problems(self):
        base = {"fact_kind": s("medical_payment"), "payer": s("p-a"), "patient": s("p-g"), "medical_kinds": s("medicine"),
                "incurred_on": {"date": "2026-02-01"}}
        refund = [{"account": "Expenses:Medical", "account_root": "expenses", "amount": -500, "currency": "JPY", "interpolated": False,
                   "meta": {"fact_amount": s("amount")}},
                  {"account": "Assets:Cash", "account_root": "assets", "amount": 500, "currency": "JPY", "interpolated": True, "meta": {}}]
        self.check(tx(base, refund), "fact_amount_reversed")
        twice = [{"account": "Expenses:Medical", "account_root": "expenses", "amount": 500, "currency": "JPY", "interpolated": False,
                  "meta": {"fact_amount": s("amount")}},
                 {"account": "Expenses:Medical", "account_root": "expenses", "amount": 300, "currency": "JPY", "interpolated": False,
                  "meta": {"fact_amount": s("amount")}},
                 {"account": "Assets:Cash", "account_root": "assets", "amount": -800, "currency": "JPY", "interpolated": True, "meta": {}}]
        self.check(tx(base, twice), "fact_amount_duplicate")
        self.check(tx({**base, "amount": {"amount": {"number": "1000", "currency": "JPY"}}}), "fact_amount_duplicate")
        self.check(tx({**base, "amount": {"amount": {"number": "10", "currency": "USD"}}}, []), "fact_value_type")
        self.check(tx({**base, "amount": {"amount": {"number": "10.5", "currency": "JPY"}}}, []), "fact_value_type")
        wrong_field = [{"account": "Expenses:Medical", "account_root": "expenses", "amount": 500, "currency": "JPY",
                        "interpolated": False, "meta": {"fact_amount": s("gross")}}]
        self.check(tx(base, wrong_field), "fact_amount_field")

    def test_ir_problems_carry_origin(self):
        unknown_person = tx({"fact_kind": s("donation"), "donor": s("p-zzz"), "recipient_name": s("架空市")}, line=42)
        result = self.check(unknown_person, "unknown_person")
        problem = next(p for p in result.problems if p.code == "unknown_person")
        self.assertTrue(problem.where.startswith("$.facts["))
        self.assertEqual(problem.origin, "main.beancount:42 (tx-1)")

    def test_ledger_record_problem_carries_origin(self):
        entries = household_fact_entries()
        entries.append({"ledger": "okura-facts/0", "entry_id": "fe-0099", "recorded_at": "2026-07-01T00:00:00+09:00",
                        "recorded_by": {"person": "p-a"}, "op": "add", "section": "facts",
                        "record": {"id": "enr-x", "kind": "enrollment", "roles": {"person": "p-c"}, "when": {"from_on": "2026-04-01"},
                                   "attributes": {"school_type": "university"}}})
        facts, problems = facts_ledger.read(jsonl(entries), "facts.jsonl")
        self.assertEqual(problems, [])
        result = build_ir(TX_DOC, facts, JUDGMENTS)
        self.assertIsNone(result.ir)
        self.assertIn(f"facts.jsonl:{len(entries)} (fe-0099)", {p.origin for p in result.problems})

    def test_duplicate_id_between_ledger_and_transactions(self):
        entries = household_fact_entries()
        entries.append({"ledger": "okura-facts/0", "entry_id": "fe-0099", "recorded_at": "2026-07-01T00:00:00+09:00",
                        "recorded_by": {"person": "p-a"}, "op": "add", "section": "facts",
                        "record": {"id": "tx-2026-0304-taxi", "kind": "business", "roles": {"owner": "p-a"}, "when": {"from_on": "2026-01-01"}}})
        facts, _ = facts_ledger.read(jsonl(entries), "facts.jsonl")
        self.assertIn("duplicate_id", codes(build_ir(TX_DOC, facts, JUDGMENTS)))

    def test_input_shape(self):
        self.assertIn("input_shape", codes(build_ir({"format": "other"}, FACTS, JUDGMENTS)))
        self.assertIn("input_shape", codes(build_ir(TX_DOC, JUDGMENTS, FACTS)))
        self.assertIn("input_shape", codes(build_ir(doc_with({"id": "tx-1"}), FACTS, JUDGMENTS)))


class NoLegalInterpretationTests(unittest.TestCase):
    """独立したレビューで足した検査：build_ir は合計・所得区分の決定・勘定科目名からの推測をしない（D5 改・D3・D11）。"""

    BASE = {"fact_kind": s("medical_payment"), "payer": s("p-a"), "patient": s("p-g"), "medical_kinds": s("medicine"),
            "incurred_on": {"date": "2026-02-01"}}

    def facts(self, *extra: dict) -> dict:
        result = build_ir(doc_with(*TX_DOC["transactions"], *extra, documents=TX_DOC["documents"]), FACTS, JUDGMENTS)
        self.assertTrue(result.ok, [p.to_dict() for p in result.problems])
        return {f["id"]: f for f in result.ir["facts"]}

    @staticmethod
    def postings(account: str) -> list:
        return [{"account": account, "account_root": "expenses", "amount": 1000, "currency": "JPY", "interpolated": False,
                 "meta": {"fact_amount": s("amount")}},
                {"account": "Assets:Cash", "account_root": "assets", "amount": -1000, "currency": "JPY", "interpolated": True, "meta": {}}]

    def test_two_payments_stay_two_facts(self):
        baseline = self.facts()
        facts = self.facts(tx(self.BASE, tx_id="tx-r1", line=900), tx(self.BASE, tx_id="tx-r2", line=901))
        self.assertEqual(len(facts), len(baseline) + 2)
        self.assertEqual(facts["tx-r1"]["amounts"], {"amount": 1000})
        self.assertEqual(facts["tx-r2"]["amounts"], {"amount": 1000})

    def test_account_names_do_not_change_the_fact(self):
        a = self.facts(tx(self.BASE, self.postings("Expenses:Medical"), tx_id="tx-r1"))["tx-r1"]
        b = self.facts(tx(self.BASE, self.postings("Expenses:Food:Restaurant"), tx_id="tx-r1"))["tx-r1"]
        self.assertEqual(a, b)

    def test_fact_fields_come_only_from_the_ledger(self):
        fact = self.facts(tx(self.BASE, tx_id="tx-r1"))["tx-r1"]
        self.assertEqual(set(fact), {"id", "kind", "roles", "when", "amounts", "attributes", "source"})
        written = set(fact["roles"]) | set(fact["attributes"]) | set(fact["amounts"])
        self.assertEqual(written, {"payer", "patient", "medical_kinds", "incurred_on", "amount"})


if __name__ == "__main__":
    unittest.main()
