"""adapter.normalize の検査：取引 ID、JPY の整数、メタデータの語彙と型、証憑、決定性。"""

from __future__ import annotations

import hashlib
import json
import os
import unittest

from okura_records.adapter import FORMAT, normalize, typed_value
from okura_records.safe_loader import load_ledger

from .helpers import BASE_LEDGER, HOUSEHOLD_FILES, RECEIPT_BYTES, fresh_dir, write_household, write_text


def _normalize_text(d: str, text: str):
    main = write_text(os.path.join(d, "main.beancount"), text)
    loaded = load_ledger(main)
    if not loaded.ok:
        return None, list(loaded.problems)
    return normalize(loaded.ledger)


def _codes(problems) -> set[str]:
    return {p.code for p in problems}


TX = '2026-01-02 * "架空の店" "買い物"\n  id: "{id}"\n  Expenses:Misc {amount}\n  Assets:Cash\n'


class NormalizeHouseholdTests(unittest.TestCase):
    def test_household_output(self):
        with fresh_dir() as d:
            paths = write_household(d)
            loaded = load_ledger(paths["ledger"])
            self.assertTrue(loaded.ok, loaded.problems)
            doc, problems = normalize(loaded.ledger)
            self.assertEqual(problems, [])
            self.assertEqual(doc["format"], FORMAT)
            self.assertEqual(doc["main"], "main.beancount")
            self.assertEqual([s["path"] for s in doc["source_files"]], ["accounts.beancount", "main.beancount"])
            ids = [t["id"] for t in doc["transactions"]]
            self.assertEqual(len(ids), len(set(ids)))
            hospital = next(t for t in doc["transactions"] if t["id"] == "tx-2026-0210-hospital")
            self.assertEqual(hospital["date"], "2026-02-10")
            self.assertEqual(hospital["payee"], "架空総合病院")
            self.assertEqual(hospital["meta"]["patient"], {"string": "p-g"})
            self.assertEqual(hospital["meta"]["incurred_on"], {"date": "2026-01-28"})
            self.assertNotIn("filename", hospital["meta"])
            self.assertNotIn("lineno", hospital["meta"])
            expense, card = hospital["postings"]
            self.assertEqual((expense["account"], expense["amount"], expense["currency"]), ("Expenses:Medical", 120000, "JPY"))
            self.assertEqual(expense["account_root"], "expenses")
            self.assertEqual(expense["meta"], {"fact_amount": {"string": "amount"}})
            self.assertEqual((card["amount"], card["interpolated"]), (-120000, True))
            (document,) = doc["documents"]
            self.assertEqual(document["path"], "receipts/2026-02-10-hospital.pdf")
            self.assertEqual(document["sha256"], hashlib.sha256(RECEIPT_BYTES).hexdigest())
            self.assertEqual(document["transaction_id"], "tx-2026-0210-hospital")
            text = json.dumps(doc, ensure_ascii=False)
            self.assertNotIn(d, text)
            self.assertNotIn(d.replace("\\", "/"), text)

    def test_deterministic_across_directories(self):
        outputs = []
        for _ in range(2):
            with fresh_dir() as d:
                write_household(d)
                loaded = load_ledger(os.path.join(d, "main.beancount"))
                doc, problems = normalize(loaded.ledger)
                self.assertEqual(problems, [])
                outputs.append(json.dumps(doc, ensure_ascii=False, sort_keys=True))
        self.assertEqual(outputs[0], outputs[1])

    def test_example_files_match_helpers(self):
        from .helpers import EXAMPLE_DIR

        with fresh_dir() as d:
            write_household(d)
            for rel in HOUSEHOLD_FILES:
                with self.subTest(file=rel):
                    with open(os.path.join(d, rel), "rb") as a, open(os.path.join(EXAMPLE_DIR, rel), "rb") as b:
                        self.assertEqual(a.read(), b.read(), "examples/household を helpers.write_household で作り直す")


class TransactionIdTests(unittest.TestCase):
    def test_missing_numeric_bad_and_duplicate_ids(self):
        cases = {
            "transaction_id_missing": '2026-01-02 * "x"\n  Expenses:Misc 1 JPY\n  Assets:Cash\n',
            "transaction_id_type": '2026-01-02 * "x"\n  id: 12345\n  Expenses:Misc 1 JPY\n  Assets:Cash\n',
            "transaction_id_pattern": TX.format(id="取引-1", amount="1 JPY"),
            "transaction_id_duplicate": TX.format(id="tx-1", amount="1 JPY") + TX.format(id="tx-1", amount="2 JPY"),
        }
        for code, text in cases.items():
            with self.subTest(code=code), fresh_dir() as d:
                doc, problems = _normalize_text(d, BASE_LEDGER + text)
                self.assertIsNone(doc)
                self.assertIn(code, _codes(problems))


class AmountTests(unittest.TestCase):
    def test_non_jpy_and_decimals_are_rejected(self):
        cases = {
            "currency_not_jpy": [
                '2026-01-01 open Assets:Usd USD\n2026-01-02 * "x"\n  id: "tx-1"\n  Assets:Usd 10 USD\n  Assets:Usd -10 USD\n',
                "2026-01-01 commodity USD\n",
                "2026-01-01 open Assets:Any\n2026-01-02 balance Assets:Any 0 USD\n",
            ],
            "amount_not_integer": [
                TX.format(id="tx-1", amount="1000.50 JPY"),
                TX.format(id="tx-1", amount="1000.00 JPY"),
                TX.format(id="tx-1", amount="10/3 JPY"),
                "2026-01-02 balance Assets:Cash 0.0 JPY\n",
            ],
            "amount_out_of_range": [TX.format(id="tx-1", amount="1000000000001 JPY")],
        }
        for code, texts in cases.items():
            for text in texts:
                with self.subTest(code=code, text=text), fresh_dir() as d:
                    doc, problems = _normalize_text(d, BASE_LEDGER + text)
                    self.assertIsNone(doc)
                    self.assertIn(code, _codes(problems), [p.to_dict() for p in problems])

    def test_arithmetic_and_commas_become_integers(self):
        with fresh_dir() as d:
            doc, problems = _normalize_text(d, BASE_LEDGER + TX.format(id="tx-1", amount="(50000 + 2,000) JPY"))
            self.assertEqual(problems, [])
            self.assertEqual([p["amount"] for p in doc["transactions"][0]["postings"]], [52000, -52000])

    def test_cost_and_price_are_rejected(self):
        with fresh_dir() as d:
            doc, problems = _normalize_text(d, BASE_LEDGER + TX.format(id="tx-1", amount="100 JPY @ 1 JPY"))
            self.assertIsNone(doc)
            self.assertIn("cost_or_price", _codes(problems))


class DirectiveAndFlagTests(unittest.TestCase):
    def test_unsupported_directives(self):
        cases = [
            "2026-01-02 price USD 150 JPY\n",
            '2026-01-01 open Equity:Opening JPY\n2026-01-02 pad Assets:Cash Equity:Opening\n2026-01-03 balance Assets:Cash 100 JPY\n',
            '2026-01-02 custom "budget" "x" TRUE\n',
            '2026-01-02 query "q" "SELECT 1"\n',
        ]
        for text in cases:
            with self.subTest(text=text), fresh_dir() as d:
                doc, problems = _normalize_text(d, BASE_LEDGER + text)
                self.assertIsNone(doc)
                self.assertIn("directive_not_supported", _codes(problems), [p.to_dict() for p in problems])

    def test_note_event_close_are_allowed(self):
        with fresh_dir() as d:
            text = BASE_LEDGER + '2026-01-02 note Assets:Cash "メモ"\n2026-01-02 event "location" "架空市"\n2026-12-31 close Expenses:Misc\n'
            doc, problems = _normalize_text(d, text)
            self.assertEqual(problems, [])
            self.assertEqual(doc["transactions"], [])

    def test_flags(self):
        with fresh_dir() as d:
            doc, problems = _normalize_text(d, BASE_LEDGER + TX.format(id="tx-1", amount="1 JPY").replace("*", "!", 1))
            self.assertEqual(problems, [])
            self.assertEqual(doc["transactions"][0]["flag"], "!")
        with fresh_dir() as d:
            doc, problems = _normalize_text(d, BASE_LEDGER + TX.format(id="tx-1", amount="1 JPY").replace("*", "P", 1))
            self.assertIn("flag_not_supported", _codes(problems))


class MetadataTests(unittest.TestCase):
    def test_unknown_keys_are_rejected_and_free_keys_allowed(self):
        with fresh_dir() as d:
            text = BASE_LEDGER + '2026-01-02 * "x"\n  id: "tx-1"\n  patiant: "p-a"\n  Expenses:Misc 1 JPY\n  Assets:Cash\n'
            doc, problems = _normalize_text(d, text)
            self.assertIn("meta_unknown_key", _codes(problems))
        with fresh_dir() as d:
            text = BASE_LEDGER + '2026-01-02 * "x"\n  id: "tx-1"\n  memo: "覚え書き"\n  x_shop: "架空の店"\n  x-ref: 3\n  Expenses:Misc 1 JPY\n    color: "red"\n  Assets:Cash\n'
            doc, problems = _normalize_text(d, text)
            self.assertEqual({p.code for p in problems}, {"meta_unknown_key"})  # posting の color だけ
            self.assertTrue(all("color" in p.message for p in problems))

    def test_typed_values(self):
        with fresh_dir() as d:
            text = BASE_LEDGER + (
                '2026-01-02 * "x"\n  id: "tx-1"\n  provider: "架空医院"\n  incurred_on: 2026-01-01\n'
                "  payroll_deduction: TRUE\n  fee: 300 JPY\n  daily_amount: 5000 JPY\n  note: \"説明\"\n"
                "  Expenses:Misc 1 JPY\n  Assets:Cash\n"
            )
            doc, problems = _normalize_text(d, text)
            self.assertEqual(problems, [])
            meta = doc["transactions"][0]["meta"]
            self.assertEqual(meta["provider"], {"string": "架空医院"})
            self.assertEqual(meta["incurred_on"], {"date": "2026-01-01"})
            self.assertEqual(meta["payroll_deduction"], {"bool": True})
            self.assertEqual(meta["fee"], {"amount": {"number": "300", "currency": "JPY"}})

    def test_typed_value_function(self):
        from decimal import Decimal

        self.assertEqual(typed_value(Decimal("2.5")), {"decimal": "2.5"})
        self.assertIsNone(typed_value(Decimal("NaN")))
        self.assertEqual(typed_value(None), {"null": True})
        self.assertIsNone(typed_value(object()))


class DocumentTests(unittest.TestCase):
    def test_document_with_unknown_transaction(self):
        with fresh_dir() as d:
            write_text(os.path.join(d, "r.pdf"), "x")
            text = BASE_LEDGER + '2026-01-02 document Assets:Cash "r.pdf"\n  transaction_id: "tx-9999"\n'
            doc, problems = _normalize_text(d, text)
            self.assertIn("document_transaction_unknown", _codes(problems))

    def test_document_without_transaction_is_kept(self):
        with fresh_dir() as d:
            write_text(os.path.join(d, "docs", "r.pdf"), "x")
            doc, problems = _normalize_text(d, BASE_LEDGER + '2026-01-02 document Assets:Cash "docs/r.pdf"\n')
            self.assertEqual(problems, [])
            self.assertEqual(doc["documents"][0]["path"], "docs/r.pdf")
            self.assertNotIn("transaction_id", doc["documents"][0])


if __name__ == "__main__":
    unittest.main()
