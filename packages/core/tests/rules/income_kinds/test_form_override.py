"""選択.様式への割当て（C-18）の読み込み（rules/income_kinds/form_override.py。2026-11-12）のユニットテスト。

科目の割当ての選択を、所得の側ごとの区分の概念（「なし」か「費目=費目;…」）にすること、業務の所得の側に当てること、入力の矛盾を
対象外にすることを確かめる。判断（事業と称するに至る程度）は Decided のスタブ。テストのデータは架空の値だけ。
"""

from __future__ import annotations

import unittest
from typing import Any

from okura_core.registry import Decided, ModuleInputs, YearContext
from okura_core.rules.income_kinds.form_override import (
    FORM_MAP_CODE_REASON,
    FORM_MAP_CONFLICT_REASON,
    FORM_MAP_OWNER_REASON,
    decode,
    encode,
    override_variable,
    write_form_overrides,
)

from ...support import make_ir, person

P = "p-1"
BIZ, RENTAL = override_variable("biz"), override_variable("rental")


def _choice(cid: str, mappings: list[tuple[str, str]], *, bid: str | None = None, who: str = P, year: int = 2026) -> dict[str, Any]:
    subject: dict[str, Any] = {"person": who}
    if bid is not None:
        subject["business_id"] = bid
    return {
        "id": cid, "kind": "選択.様式への割当て", "chosen_by": who, "chosen_at": "2026-01-05T09:00:00+09:00", "subject": subject,
        "when": {"tax_year": year}, "value": {"mappings": [{"expense_category": s, "form_item": t} for s, t in mappings]},
    }  # fmt: skip


def _run(choices: list[dict[str, Any]], *, jigyo: bool = True, owner: str = P) -> ModuleInputs:
    facts = [
        {"id": "biz-1", "kind": "business", "roles": {"owner": owner}, "when": {"from_on": "2020-01-01"}},
        {
            "id": "e-1", "kind": "business_expense", "roles": {"payer": owner}, "when": {"on": "2026-03-01"},
            "amounts": {"amount": 1000}, "attributes": {"business_id": "biz-1", "expense_category": "supplies", "incurred_on": "2026-03-01"},
        },
    ]  # fmt: skip
    decided = {("判断.事業と称するに至る程度", f"{owner}:biz-1"): Decided(jigyo, ("j-1",), frozenset(), False)}
    ctx = YearContext(make_ir([person(P), person("p-2")], facts, choices=choices), 2026, (P, "p-2"), decided)
    out = ModuleInputs()
    write_form_overrides(ctx, out)
    return out


def _value(out: ModuleInputs, var: str, pid: str = P) -> Any:
    return out.values[(var, pid)].value


def _reasons(out: ModuleInputs, var: str) -> list[str]:
    return [e.reason.reason for e in out.exclusions if e.variable == var]


class TestFormOverride(unittest.TestCase):
    def test_encode_decode(self) -> None:
        self.assertEqual(encode({"supplies": "other", "rent": "rent", "membership_dues": "other"}), "membership_dues=other;supplies=other")
        self.assertEqual(encode({"rent": "rent"}), "なし")
        self.assertEqual(decode("membership_dues=other;supplies=other"), {"membership_dues": "other", "supplies": "other"})
        self.assertEqual(decode("なし"), {})

    def test_no_choice_is_default(self) -> None:
        out = _run([])
        self.assertEqual((_value(out, BIZ), _value(out, RENTAL), _value(out, BIZ, "p-2")), ("なし", "なし", "なし"))
        self.assertEqual(out.exclusions, [])

    def test_business_id_applies_to_its_side(self) -> None:
        out = _run([_choice("c-1", [("supplies", "other")], bid="biz-1")])
        self.assertEqual((_value(out, BIZ), _value(out, RENTAL)), ("supplies=other", "なし"))
        self.assertEqual(out.values[(BIZ, P)].record_ids, ("c-1", "j-1"))
        # 業務に係る雑所得の業務は様式の表がない
        out = _run([_choice("c-1", [("supplies", "other")], bid="biz-1")], jigyo=False)
        self.assertEqual((_value(out, BIZ), _value(out, RENTAL)), ("なし", "なし"))

    def test_without_business_id_applies_to_both_sides(self) -> None:
        out = _run([_choice("c-1", [("membership_dues", "other")])])
        self.assertEqual((_value(out, BIZ), _value(out, RENTAL)), ("membership_dues=other", "membership_dues=other"))

    def test_inconsistent_inputs(self) -> None:
        # 仕入（売上原価の計算に使う）と語彙の外の符号
        out = _run([_choice("c-1", [("merchandise", "other")])])
        self.assertEqual(_reasons(out, BIZ), [FORM_MAP_CODE_REASON])
        out = _run([_choice("c-1", [("supplies", "dividend_debt_interest")])])
        self.assertEqual(_reasons(out, BIZ), [FORM_MAP_CODE_REASON])
        # 同じ側で同じ費目を2つの違う費目へ（2つの選択の間）。同じ割当ての重複は矛盾でない
        out = _run([_choice("c-1", [("supplies", "other")], bid="biz-1"), _choice("c-2", [("supplies", "fees")])])
        self.assertEqual(_reasons(out, BIZ), [FORM_MAP_CONFLICT_REASON])
        self.assertEqual((_value(out, BIZ), _value(out, RENTAL)), ("なし", "supplies=fees"))
        out = _run([_choice("c-1", [("supplies", "other")], bid="biz-1"), _choice("c-2", [("supplies", "other")])])
        self.assertEqual((out.exclusions, _value(out, BIZ)), ([], "supplies=other"))
        # 業務の持ち主が選んだ人と違う
        out = _run([_choice("c-1", [("supplies", "other")], bid="biz-1", who="p-2")])
        self.assertEqual([(e.person, e.reason.reason) for e in out.exclusions], [("p-2", FORM_MAP_OWNER_REASON)] * 2)
        self.assertEqual(_value(out, BIZ), "なし")

    def test_other_years_are_ignored(self) -> None:
        out = _run([_choice("c-1", [("supplies", "other")], year=2025)])
        self.assertEqual(_value(out, BIZ), "なし")
