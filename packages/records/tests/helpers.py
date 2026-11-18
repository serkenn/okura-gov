"""テストの補助：一時ディレクトリ、副作用の検出用の印のファイル、架空の家庭の台帳。

架空の家庭（実在の家族ではない）：
  p-a 親A（会社員）、p-b 親B（個人で業務）、p-c 子（別の市町村で一人暮らしの大学生）、p-g 祖父母（同居）。
  市町村の団体コードは実在しない 99 で始まるもの。金額・日付はすべて架空。
"""

from __future__ import annotations

import contextlib
import os
import stat
import tempfile
from typing import Any, Iterator, Mapping, Sequence

from okura_records.jsonl_ledger import append_entry

ROOT_OF_PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE_DIR = os.path.join(ROOT_OF_PACKAGE, "examples", "household")


@contextlib.contextmanager
def fresh_dir() -> Iterator[str]:
    """まだ一度も使っていない新しい空のディレクトリ（終わったら消す）。"""
    with tempfile.TemporaryDirectory(prefix="okura-records-test-") as d:
        yield os.path.realpath(d)


def write_bytes(path: str, data: bytes) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def write_text(path: str, text: str) -> str:
    return write_bytes(path, text.encode("utf-8"))


def _is_link_or_junction(p: str) -> bool:
    try:
        st = os.lstat(p)
    except OSError:
        return False
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def markers(directory: str) -> list[str]:
    """directory の下にある印のファイル（名前に marker を含む）の一覧。

    リンク・ジャンクションの先はたどらない（親を指すジャンクションで無限にたどらないため。印は directory の中の実体に書かれる）。
    """
    found: list[str] = []
    for current, dirs, files in os.walk(directory):
        dirs[:] = [x for x in dirs if not _is_link_or_junction(os.path.join(current, x))]
        found.extend(os.path.join(current, f) for f in files if "marker" in f)
    return sorted(os.path.relpath(p, directory) for p in found)


def eval_plugin_line(marker_path: str, module: str = "beancount.plugins.check_commodity") -> str:
    """設定の文字列が eval される既存のプラグインで、印のファイルを1つ書くだけのコードを動かす plugin 行。"""
    tail = "and 0.01" if module.endswith("check_average_cost") else "and {}"
    m = marker_path.replace("\\", "/")
    return f'plugin "{module}" "__import__(\'pathlib\').Path(\'{m}\').write_text(\'executed\') {tail}"'


def plugin_module_source(marker_name: str) -> str:
    """import されると同じディレクトリに印のファイルを書くだけのプラグインのモジュール。"""
    return (
        "import os\n"
        f"_m = os.path.join(os.path.dirname(os.path.abspath(__file__)), {marker_name!r})\n"
        "with open(_m, 'w') as _f:\n"
        "    _f.write('imported')\n"
        "__plugins__ = ('noop',)\n"
        "def noop(entries, options_map):\n"
        "    return entries, []\n"
    )


BASE_LEDGER = "2026-01-01 open Assets:Cash JPY\n2026-01-01 open Expenses:Misc JPY\n"


def jsonl(entries: Sequence[Mapping[str, Any]]) -> bytes:
    data = b""
    for entry in entries:
        data = append_entry(data, entry)
    return data


# ---------------------------------------------------------------------------
# 架空の家庭
# ---------------------------------------------------------------------------

ACCOUNTS = """\
; 勘定の開設（勘定科目名に法的な意味を持たせない。D3・D11）
2026-01-01 open Assets:Bank:A JPY
2026-01-01 open Assets:Bank:B JPY
2026-01-01 open Assets:Cash JPY
2026-01-01 open Assets:Receivable:A JPY
2026-01-01 open Liabilities:Card:A JPY
2026-01-01 open Income:Salary:A JPY
2026-01-01 open Income:Business:B JPY
2026-01-01 open Income:Dividend:A JPY
2026-01-01 open Expenses:Tax:Withholding JPY
2026-01-01 open Expenses:SocialInsurance JPY
2026-01-01 open Expenses:Insurance JPY
2026-01-01 open Expenses:Medical JPY
2026-01-01 open Expenses:Utilities JPY
2026-01-01 open Expenses:Donation JPY
2026-01-01 open Expenses:Family:Allowance JPY
"""

MAIN = """\
option "title" "架空の家庭（テスト用）"
option "operating_currency" "JPY"
include "accounts.beancount"

2026-01-25 * "架空商事" "1月分の給与"
  id: "tx-2026-0125-salary-a"
  fact_kind: "salary_payment"
  recipient: "p-a"
  counterparty: "架空商事"
  payment_type: "regular"
  due_on: 2026-01-25
  Income:Salary:A             -300000 JPY
    fact_amount: "gross"
  Expenses:Tax:Withholding       8000 JPY
    fact_amount: "withholding_tax"
  Expenses:SocialInsurance      45000 JPY
    fact_amount: "social_insurance_withheld"
  Assets:Bank:A                247000 JPY

2026-02-10 * "架空総合病院" "入院費"
  id: "tx-2026-0210-hospital"
  fact_kind: "medical_payment"
  payer: "p-a"
  patient: "p-g"
  incurred_on: 2026-01-28
  provider: "架空総合病院"
  medical_kinds: "medical_treatment hospitalization"
  Expenses:Medical             120,000 JPY
    fact_amount: "amount"
  Liabilities:Card:A

2026-02-10 document Expenses:Medical "receipts/2026-02-10-hospital.pdf"
  transaction_id: "tx-2026-0210-hospital"

2026-03-04 * "架空タクシー" "通院のタクシー"
  id: "tx-2026-0304-taxi"
  fact_kind: "medical_payment"
  payer: "p-a"
  patient: "p-g"
  incurred_on: 2026-03-04
  medical_kinds: "transport"
  memo: "歩行が困難なため"
  Expenses:Medical               3200 JPY
    fact_amount: "amount"
  Assets:Cash

2026-03-15 * "架空デザイン事務所" "制作の報酬"
  id: "tx-2026-0315-design"
  fact_kind: "business_receipt"
  recipient: "p-b"
  business_id: "biz-b"
  counterparty: "架空デザイン事務所"
  Income:Business:B            -55000 JPY
    fact_amount: "amount"
  Expenses:Tax:Withholding       5615 JPY
    fact_amount: "withholding_tax"
  Assets:Bank:B                 49385 JPY

2026-03-20 * "架空電力" "電気代"
  id: "tx-2026-0320-electricity"
  fact_kind: "business_expense"
  payer: "p-b"
  business_id: "biz-b"
  expense_category: "utilities"
  Expenses:Utilities             12000 JPY
    fact_amount: "amount"
  Assets:Bank:B

2026-04-25 * "仕送り"
  id: "tx-2026-0425-allowance"
  fact_kind: "remittance"
  sender: "p-a"
  recipient: "p-c"
  method: "bank_transfer"
  purpose: "living_expenses"
  Expenses:Family:Allowance      80000 JPY
    fact_amount: "amount"
  Assets:Bank:A

2026-04-30 * "口座からの引き出し"
  id: "tx-2026-0430-withdrawal"
  x_note: "事実にしない記帳（fact_kind なし）"
  Assets:Bank:A                 -10000 JPY
  Assets:Cash                    10000 JPY

2026-06-20 * "架空証券" "投資信託の収益の分配"
  id: "tx-2026-0620-dividend"
  fact_kind: "dividend"
  recipient: "p-a"
  counterparty: "架空証券"
  security_class: "listed_investment_trust"
  account_type: "withholding_specified_account"
  distribution_type: "securities_investment_trust"
  Income:Dividend:A              -10000 JPY
    fact_amount: "gross"
  Expenses:Tax:Withholding        2031 JPY
    fact_amount: "withholding_tax"
  Assets:Bank:A                   7969 JPY

2026-09-25 * "架空商事" "9月分の給与（未払）"
  id: "tx-2026-0925-salary-a-unpaid"
  fact_kind: "salary_payment"
  recipient: "p-a"
  counterparty: "架空商事"
  payment_type: "regular"
  due_on: 2026-09-25
  unpaid: TRUE
  pay_period: "monthly"
  uncollectible_amount: 300000 JPY
  uncollectible_on: 2026-11-10
  Income:Salary:A             -300000 JPY
    fact_amount: "gross"
  Assets:Receivable:A          300000 JPY

2026-10-05 * "架空県共同募金会" "共同募金"
  id: "tx-2026-1005-community-chest"
  fact_kind: "donation"
  donor: "p-a"
  recipient_name: "架空県共同募金会"
  recipient_type: "community_chest"
  receipt_issued: TRUE
  receipt_statement: "none"
  recipient_office_prefecture_code: "990001"
  mic_approved_solicitation: TRUE
  Expenses:Donation              3000 JPY
    fact_amount: "amount"
  Assets:Cash

2026-10-30 * "国民年金保険料の前納（子の分）"
  id: "tx-2026-1030-npi-prepay"
  fact_kind: "social_insurance_payment"
  payer: "p-a"
  liable_person: "p-c"
  premium_type: "national_pension"
  prepaid_period: "2026-10-01/2027-03-31"
  prepaid_due_dates: "2026-11-30 2026-12-31 2027-01-31 2027-02-28 2027-03-31 2027-04-30"
  Expenses:SocialInsurance     104000 JPY
    fact_amount: "amount"
  Assets:Bank:A

2026-11-20 * "架空生命" "生命保険料の前納"
  id: "tx-2026-1120-life-prepay"
  fact_kind: "insurance_payment"
  payer: "p-a"
  contract_id: "a-life-a"
  flow: "premium"
  prepaid: TRUE
  prepaid_due_dates: "2026-12-01 2027-12-01"
  Expenses:Insurance           240000 JPY
    fact_amount: "amount"
  Assets:Bank:A
"""

RECEIPT_BYTES = b"%PDF-1.4\n% fictional receipt for tests\n"

_A = {"person": "p-a"}


def _fe(n: int, at: str, section: str, record: Mapping[str, Any] | None, *, op: str = "add",
        replaces: str | None = None, reason: str | None = None, by: Mapping[str, str] = _A) -> dict[str, Any]:
    entry: dict[str, Any] = {"ledger": "okura-facts/0", "entry_id": f"fe-{n:04d}", "recorded_at": at,
                             "recorded_by": dict(by), "op": op, "section": section}
    if record is not None:
        entry["record"] = dict(record)
    if replaces is not None:
        entry["replaces"] = replaces
    if reason is not None:
        entry["reason"] = reason
    return entry


def _je(n: int, at: str, section: str, record: Mapping[str, Any] | None, *, op: str = "add",
        replaces: str | None = None, reason: str | None = None) -> dict[str, Any]:
    entry = _fe(n, at, section, record, op=op, replaces=replaces, reason=reason)
    entry["ledger"] = "okura-judgments/0"
    entry["entry_id"] = f"je-{n:04d}"
    return entry


def household_fact_entries() -> list[dict[str, Any]]:
    t = "2026-01-05T20:00:00+09:00"
    return [
        _fe(1, t, "persons", {"id": "p-a", "birth_on": "1975-04-10"}),
        _fe(2, t, "persons", {"id": "p-b", "birth_on": "1977-09-21"}),
        _fe(3, t, "persons", {"id": "p-c", "birth_on": "2005-06-51"}),  # 打ち間違い（fe-0012 で訂正）
        _fe(4, t, "persons", {"id": "p-g", "birth_on": "1945-02-02"}),
        _fe(5, t, "relations", {"id": "rel-marriage-ab", "kind": "marriage", "roles": {"spouse_a": "p-a", "spouse_b": "p-b"},
                                "when": {"from_on": "2003-10-10"}}),
        _fe(6, t, "relations", {"id": "rel-parent-ac", "kind": "parentage", "roles": {"parent": "p-a", "child": "p-c"},
                                "when": {"on": "2005-06-15"}, "attributes": {"basis": "birth_in_marriage"}}),
        _fe(7, t, "relations", {"id": "rel-parent-ga", "kind": "parentage", "roles": {"parent": "p-g", "child": "p-a"},
                                "when": {"on": "1975-04-10"}, "attributes": {"basis": "birth_mother"}}),
        _fe(8, t, "residences", {"id": "res-a", "kind": "resident_record", "roles": {"person": "p-a"},
                                 "when": {"from_on": "2003-10-10"},
                                 "attributes": {"municipality_code": "990011", "household_id": "hh-1", "householder": True,
                                                "relation_to_householder": "householder"}}),
        _fe(9, t, "residences", {"id": "res-c", "kind": "resident_record", "roles": {"person": "p-c"},
                                 "when": {"from_on": "2024-04-01"},
                                 "attributes": {"municipality_code": "990022", "household_id": "hh-2", "householder": True}}),
        _fe(10, t, "facts", {"id": "biz-b", "kind": "business", "roles": {"owner": "p-b"}, "when": {"from_on": "2020-04-01"},
                             "attributes": {"description": "架空のデザイン業"}}),
        _fe(11, t, "facts", {"id": "enr-c", "kind": "enrollment", "roles": {"person": "p-c"},
                             "when": {"from_on": "2024-04-01", "to_on": "2028-03-31"},
                             "attributes": {"school_type": "school_act_article1", "attendance": "full_time"}}),
        _fe(12, "2026-01-06T08:00:00+09:00", "persons", {"id": "p-c", "birth_on": "2005-06-15"}, op="correct",
            replaces="fe-0003", reason="生年月日の打ち間違い"),
        _fe(13, "2026-01-06T08:05:00+09:00", "facts", {"id": "cohab-ag-dup", "kind": "cohabitation",
                                                         "roles": {"person": "p-a", "other_person": "p-g"},
                                                         "when": {"from_on": "2018-04-01"}}),
        _fe(14, "2026-01-06T08:06:00+09:00", "relations", {"id": "rel-cohab-ag", "kind": "cohabitation",
                                                             "roles": {"person": "p-a", "other_person": "p-g"},
                                                             "when": {"from_on": "2018-04-01"}}),
        _fe(15, "2026-01-06T08:07:00+09:00", "facts", None, op="delete", replaces="fe-0013",
            reason="section を間違えた（relations に記録し直した）"),
        # 2026-11-11：Phase 3 の語彙（法令上の性別、加入している医療保険と保険者・被扶養者の資格）
        _fe(16, "2026-01-06T09:00:00+09:00", "facts", {"id": "sex-b", "kind": "legal_sex", "roles": {"person": "p-b"},
                                                         "when": {"from_on": "1977-09-21"}, "attributes": {"sex": "female"}}),
        _fe(17, "2026-01-06T09:01:00+09:00", "insurance_memberships",
            {"id": "mi-a", "kind": "medical_insurance", "roles": {"member": "p-a"}, "when": {"from_on": "2010-04-01"},
             "attributes": {"scheme": "kyokai_kenpo", "insurer_id": "ins-99000001", "capacity": "insured"}}),
        _fe(18, "2026-01-06T09:02:00+09:00", "insurance_memberships",
            {"id": "mi-c", "kind": "medical_insurance", "roles": {"member": "p-c", "insured": "p-a"},
             "when": {"from_on": "2010-04-01"},
             "attributes": {"scheme": "kyokai_kenpo", "insurer_id": "ins-99000001", "capacity": "dependent"}}),
        # 2026-11-12：語彙の追加（国民年金基金の加入員、年金の受給権の制度と障害等級、学生納付特例対象校一覧の記載、
        # 課税（非課税）証明書の記載、保険の契約の保険金等の支払の定め）
        _fe(19, "2026-01-06T09:03:00+09:00", "insurance_memberships",
            {"id": "npf-b", "kind": "national_pension_fund", "roles": {"member": "p-b"}, "when": {"from_on": "2021-04-01"},
             "attributes": {"fund_id": "npf-99000001"}}),
        _fe(20, "2026-01-06T09:04:00+09:00", "insurance_memberships",
            {"id": "pe-g-old", "kind": "pension_entitlement", "roles": {"member": "p-g"}, "when": {"from_on": "2010-02-02"},
             "attributes": {"benefit": "old_age", "scheme": "corporate_pension"}}),
        _fe(21, "2026-01-06T09:05:00+09:00", "insurance_memberships",
            {"id": "pe-g-rosai", "kind": "pension_entitlement", "roles": {"member": "p-g"}, "when": {"from_on": "2001-07-01"},
             "attributes": {"benefit": "disability", "scheme": "workers_accident_compensation", "disability_grade": 2}}),
        _fe(22, "2026-01-06T09:06:00+09:00", "facts", {"id": "enr-c", "kind": "enrollment", "roles": {"person": "p-c"},
                                                         "when": {"from_on": "2024-04-01", "to_on": "2028-03-31"},
                                                         "attributes": {"school_type": "school_act_article1", "attendance": "full_time",
                                                                        "npi_student_school_listed": True}},
            op="correct", replaces="fe-0011", reason="学生納付特例対象校一覧の記載の書き漏れ"),
        _fe(23, "2026-06-10T19:00:00+09:00", "facts", {"id": "cert-b-2026", "kind": "income_certificate", "roles": {"person": "p-b"},
                                                         "when": {"on": "2026-06-10"}, "amounts": {"total_income": 800000},
                                                         "attributes": {"fiscal_year": 2026, "issuer": "架空市"}}),
        _fe(24, "2026-06-10T19:01:00+09:00", "assets",
            {"id": "a-life-a", "kind": "insurance_contract", "roles": {"policyholder": "p-a", "insured": "p-a"},
             "when": {"from_on": "2016-04-01"},
             "attributes": {"product_type": "life", "concluded_on": "2016-04-01", "insurer_name": "架空生命",
                            "benefit_payment_terms": "other"}}),
    ]


def household_judgment_entries() -> list[dict[str, Any]]:
    return [
        _je(1, "2026-02-01T21:00:00+09:00", "judgments",
            {"id": "j-livelihood-ac", "kind": "判断.生計を一にする", "judged_by": {"person": "p-a"},
             "judged_at": "2026-02-01T20:55:00+09:00", "subject": {"person": "p-a", "other_person": "p-c"},
             "when": {"from_on": "2026-01-01", "to_on": "2026-12-31"}, "value": True,
             "basis": {"method": "学費と生活費を仕送りしている（架空）"}}),
        _je(2, "2026-03-05T08:10:00+09:00", "judgments",
            {"id": "j-taxi-scope", "kind": "判断.医療費の範囲", "judged_by": {"person": "p-a"},
             "judged_at": "2026-03-05T08:00:00+09:00", "subject": {"payment_id": "tx-2026-0304-taxi"}, "value": True,
             "basis": {"transaction_ids": ["tx-2026-0304-taxi"], "method": "歩行が困難で公共交通機関を使えなかった（架空）"}}),
        _je(3, "2026-03-21T09:00:00+09:00", "judgments",
            {"id": "j-elec-ratio-v1", "kind": "判断.按分の割合", "judged_by": {"person": "p-b"},
             "judged_at": "2026-03-21T09:00:00+09:00",
             "subject": {"person": "p-b", "record_ids": ["tx-2026-0320-electricity"], "business_id": "biz-b"},
             "when": {"tax_year": 2026},
             "value": {"purpose": "household_expense_business_share", "ratio": {"num": 3, "den": 10}, "measure": "time"},
             "basis": {"method": "仕事に使う時間の割合（架空）"}}),
        _je(4, "2026-03-21T09:30:00+09:00", "judgments",
            {"id": "j-elec-ratio-v1", "kind": "判断.按分の割合", "judged_by": {"person": "p-b"},
             "judged_at": "2026-03-21T09:00:00+09:00",
             "subject": {"person": "p-b", "record_ids": ["tx-2026-0320-electricity"], "business_id": "biz-b"},
             "when": {"tax_year": 2026},
             "value": {"purpose": "household_expense_business_share", "ratio": {"num": 3, "den": 10}, "measure": "time"},
             "basis": {"method": "仕事に使う時間の割合（1日8時間のうち、平日だけ。架空）"}},
            op="correct", replaces="je-0003", reason="根拠の書き漏れ"),
        _je(5, "2026-12-31T10:00:00+09:00", "judgments",
            {"id": "j-elec-ratio-v2", "kind": "判断.按分の割合", "judged_by": {"person": "p-b"},
             "judged_at": "2026-12-31T10:00:00+09:00",
             "subject": {"person": "p-b", "record_ids": ["tx-2026-0320-electricity"], "business_id": "biz-b"},
             "when": {"tax_year": 2026},
             "value": {"purpose": "household_expense_business_share", "ratio": {"num": 1, "den": 4}, "measure": "time"},
             "basis": {"method": "年の途中で仕事の時間が減った（架空）"}, "replaces": "j-elec-ratio-v1"}),
        _je(6, "2027-02-01T10:30:00+09:00", "choices",
            {"id": "c-medical-2026", "kind": "選択.医療費控除かセルフメディケーション税制か", "chosen_by": "p-a",
             "chosen_at": "2027-02-01T10:30:00+09:00", "subject": {"person": "p-a"}, "when": {"tax_year": 2026},
             "value": "medical_expense_deduction"}),
        # 2026-11-12：語彙の追加（被扶養者の収入の見込みの例外の判断、前納した社会保険料の控除の年分の選択）
        _je(7, "2027-02-01T11:00:00+09:00", "judgments",
            {"id": "j-below-c", "kind": "判断.収入が基準額以上とならないことが明らか", "judged_by": {"person": "p-a"},
             "judged_at": "2026-04-01T09:00:00+09:00", "subject": {"person": "p-c"}, "when": {"on": "2026-04-01"}, "value": True,
             "basis": {"method": "前年のアルバイトの実績（架空）"}}),
        _je(8, "2027-02-01T11:05:00+09:00", "choices",
            {"id": "c-npi-prepay-2026", "kind": "選択.前納した社会保険料の控除の年分", "chosen_by": "p-a",
             "chosen_at": "2027-02-01T11:05:00+09:00", "subject": {"payment_id": "tx-2026-1030-npi-prepay"}, "value": "pro_rata"}),
    ]


def write_household(directory: str) -> dict[str, str]:
    """架空の家庭の台帳一式を directory に書く。パスの dict を返す。"""
    paths = {
        "ledger": write_text(os.path.join(directory, "main.beancount"), MAIN),
        "accounts": write_text(os.path.join(directory, "accounts.beancount"), ACCOUNTS),
        "receipt": write_bytes(os.path.join(directory, "receipts", "2026-02-10-hospital.pdf"), RECEIPT_BYTES),
        "facts": write_bytes(os.path.join(directory, "facts.jsonl"), jsonl(household_fact_entries())),
        "judgments": write_bytes(os.path.join(directory, "judgments.jsonl"), jsonl(household_judgment_entries())),
    }
    return paths


HOUSEHOLD_FILES = ("main.beancount", "accounts.beancount", "receipts/2026-02-10-hospital.pdf", "facts.jsonl", "judgments.jsonl")
