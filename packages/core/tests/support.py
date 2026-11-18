"""テストの共通の道具。テストのデータはどれも架空の家庭（個人の情報を使わない）。"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

from okura_core.country import OkuraTaxBenefitSystem, build_system

REPO = Path(__file__).resolve().parents[3]
CORE_SRC = REPO / "packages" / "core" / "src" / "okura_core"


@functools.cache
def system() -> OkuraTaxBenefitSystem:
    """テストで使い回す TaxBenefitSystem（読み込みの時間を省く。テストの中では変更しない）。"""
    return build_system()


def person(pid: str, birth_on: str = "1990-01-01") -> dict[str, Any]:
    return {"id": pid, "birth_on": birth_on}


def salary(
    rid: str, recipient: str, on: str, gross: int, *, mark: str | None = None, counterparty: str = "架空の会社", due_on: str | None = None
) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "id": rid,
        "kind": "salary_payment",
        "roles": {"recipient": recipient},
        "when": {"on": on},
        "amounts": {"gross": gross},
        "attributes": {"counterparty": counterparty, "due_on": due_on or on},
    }
    if mark is not None:
        rec["mark"] = mark
    return rec


def make_ir(persons: list[dict[str, Any]], facts: list[dict[str, Any]], **sections: list[dict[str, Any]]) -> dict[str, Any]:
    ir: dict[str, Any] = {
        "schema_version": "0",
        "persons": persons,
        "relations": [],
        "residences": [],
        "insurance_memberships": [],
        "facts": facts,
        "assets": [],
        "filed_documents": [],
        "judgments": [],
        "choices": [],
    }
    for k, v in sections.items():
        if k not in ir:
            raise KeyError(k)
        ir[k] = v
    return ir


def make_query(years: tuple[int, ...] = (2026,), **kw: Any) -> dict[str, Any]:
    q: dict[str, Any] = {
        "income_tax_years": list(years),
        "resident_tax_fiscal_years": [],
        "kokuho_fiscal_years": [],
        "dependent_judgment_dates": [],
        "scenarios": [],
    }
    q.update(kw)
    return q


def wages_ir(year: int, wages: list[int]) -> tuple[dict[str, Any], list[str]]:
    """給与だけの架空の人を、給与等の収入金額ごとに1人ずつ作る（1回の評価で多くの境目を確かめるため）。"""
    persons = []
    facts = []
    ids = []
    for i, w in enumerate(wages):
        pid = f"p-{i:04d}"
        ids.append(pid)
        persons.append(person(pid))
        facts.append(salary(f"s-{i:04d}", pid, f"{year}-06-25", w))
    return make_ir(persons, facts), ids
