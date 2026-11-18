"""income_kinds の減価償却・専従者・消費税等・不動産所得・配当の負債の利子（evaluate を通して確かめる）。テストのデータは架空の家庭。

期待値の出典はコメントの docs の節。金額が候補で分かれるものは幅（D22 S3）。
"""

from __future__ import annotations

import unittest
from typing import Any

from okura_core import evaluate
from okura_core.money import YenRange
from okura_core.result import State, TimeKey, YenAmount, check_result_json

from ...support import make_ir, make_query, person, system

T25 = TimeKey("tax_year", 2025)
T26 = TimeKey("tax_year", 2026)
AT = "2027-02-01T10:00:00+09:00"


def run(ir: dict[str, Any], years: tuple[int, ...] = (2026,)) -> Any:
    res = evaluate(ir, make_query(years), system=system())
    if not res.ok:
        raise AssertionError(res.to_dict())
    problems = check_result_json(res.to_dict())
    if problems:
        raise AssertionError(problems)
    return res.scenario("base")


def biz(bid: str, owner: str, start: str = "2020-01-01") -> dict[str, Any]:
    return {"id": bid, "kind": "business", "roles": {"owner": owner}, "when": {"from_on": start}, "attributes": {}}


def receipt(rid: str, owner: str, bid: str, on: str, amount: int) -> dict[str, Any]:
    return {"id": rid, "kind": "business_receipt", "roles": {"recipient": owner}, "when": {"on": on}, "amounts": {"amount": amount}, "attributes": {"business_id": bid}}


def expense(rid: str, payer: str, bid: str | None, on: str, amount: int, category: str = "supplies") -> dict[str, Any]:
    attrs: dict[str, Any] = {"expense_category": category}
    if bid is not None:
        attrs["business_id"] = bid
    return {"id": rid, "kind": "business_expense", "roles": {"payer": payer}, "when": {"on": on}, "amounts": {"amount": amount}, "attributes": attrs}


def judge(jid: str, kind: str, subject: dict[str, Any], value: Any, *, when: dict[str, Any] | None = None, by: str = "p-a") -> dict[str, Any]:
    j: dict[str, Any] = {"id": jid, "kind": kind, "judged_by": {"person": by}, "judged_at": AT, "subject": subject, "value": value}
    if when is not None:
        j["when"] = when
    return j


def choice(cid: str, kind: str, subject: dict[str, Any], value: Any, year: int = 2026, by: str = "p-a") -> dict[str, Any]:
    return {"id": cid, "kind": kind, "chosen_by": by, "chosen_at": AT, "subject": subject, "when": {"tax_year": year}, "value": value}


def jigyo(pid: str, bid: str, value: bool = True, year: int = 2026) -> list[dict[str, Any]]:
    return [
        judge(f"j-biz-{pid}-{bid}-{year}", "判断.事業と称するに至る程度", {"person": pid, "business_id": bid}, value, when={"tax_year": year}, by=pid),
        judge(f"j-home-{pid}-{year}", "判断.家内労働者等", {"person": pid}, False, when={"tax_year": year}, by=pid),
    ]


def related(rid: str, value: bool = True) -> dict[str, Any]:
    return judge(f"j-rel-{rid}", "判断.業務関連性", {"record_id": rid}, value)


def asset(rid: str, owner: str, cost: int, from_on: str, to_on: str | None = None, placed: str | None = None, bid: str = "b-1", **attrs: Any) -> dict[str, Any]:
    when: dict[str, Any] = {"from_on": from_on}
    if to_on:
        when["to_on"] = to_on
    a: dict[str, Any] = {"name": "架空の資産", "business_id": bid, **attrs}
    if placed:
        a["placed_in_service_on"] = placed
    return {"id": rid, "kind": "depreciable_asset", "roles": {"owner": owner}, "when": when, "amounts": {"acquisition_cost": cost}, "attributes": a}


def useful(asset_id: str, years: int) -> dict[str, Any]:
    return judge(f"j-use-{asset_id}", "判断.減価償却の区分", {"asset_id": asset_id}, {"useful_life_years": years})


def dep_choice(asset_id: str, year: int, *, lump: bool = False, special: bool = False, by: str = "p-a") -> dict[str, Any]:
    return choice(f"c-dep-{asset_id}", "選択.減価償却", {"asset_id": asset_id}, {"lump_sum_depreciation": lump, "small_amount_special_rule": special}, year, by=by)


BLUE = {"id": "pr-1", "kind": "blue_return_procedure", "roles": {"person": "p-a"}, "when": {"on": "2020-05-01"}, "attributes": {"procedure": "approval_notice", "first_tax_year": 2020}}


def dep(sc: Any, year: TimeKey, pid: str = "p-a") -> Any:
    return sc.value("所得税.減価償却費の額", pid, year)












class TestParameters(unittest.TestCase):
    def test_rate_table(self) -> None:
        # genka §2.2：別表第八。4年 0.250・5年 0.200・10年 0.100、99 行すべて ceil(1000/n)/1000（H3 の性質）
        import math

        p = system().get_parameters_at_instant("2026-01-01")
        node = p.所得税.減価償却.定額法償却率
        for n in range(2, 101):
            self.assertEqual(getattr(node, f"年数{n}"), math.ceil(1000 / n), n)


if __name__ == "__main__":
    unittest.main()
