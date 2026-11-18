"""対象外の検出の共通の部分（規則モジュールに依らないもの）と、中間表現の項目の数の上限。

- どの規則モジュールも使わない記録・判断・選択・注入データは、項目ごとに「対象外（未対応）」として返す。
  ただし、中間表現の語彙が「計算に使わない」と明記した種類・書類の種別（okura_ir.vocabulary.NOT_USED_IN_CALCULATION・
  NOT_USED_IN_CALCULATION_VALUES。理由と根拠は packages/ir/README.md §6.4）は、記録してよいが計算に使わないものなので、未対応にせず結果にも出さない
  （2026-11-12。所得に関係しうる記録・使う記録に触れた判断としても数えない）。
- そのうち「所得に関係しうるもの」（INCOME_RELATED_KINDS）を持つ人・年分は、その人の全部の所得に依存する値
  （所得の種類ごとの所得の集約点と、それに依存する値：Registry.outputs の needs_complete_income）を対象外にする。
  医療費の支払・社会保険料の支払・寄附・住所・保険の加入などの所得に関係しない記録では止めない（2026-11-11 のレビューの指摘）。
  所得に関係しない記録でも、それを使う規則（医療費控除など）が未実装なら、その規則の概念の仮置きの変数に依存する値は
  evaluate が対象外にする（仮置きの変数の規則）。
- 使わない判断・選択が、規則モジュールの使う記録を対象にしていれば、その記録から作った入力を対象外にする（touched）。
- 居住者かどうかの判定（abroad_stay・判断.住所の所在）を使う規則モジュールがない間は、年分と重なる国外の滞在・住所の判断が
  ある人・年分の値を全部対象外にする（居住者かどうかの判定は範囲の中で未実装。非居住者本人の申告は範囲外：D20・SCOPE §4）。

INCOME_RELATED_KINDS は法令の解釈を含む表（どの事実が所得の金額に効きうるか）で、安全側に広く取った。
根拠は語彙の文書の各行の「中身」（docs/hypotheses/20261109_round3_design-vocabulary.md §1・§2。仮説）と、
所得の種類の条文（docs/public-sources/20261109_R1-laws_income-tax.md §4）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from okura_ir.vocabulary import NOT_USED_IN_CALCULATION, NOT_USED_IN_CALCULATION_VALUES

from .registry import RECORD_SECTIONS, Registry, heads, overlaps_year
from .result import OutOfScopeCategory, OutOfScopeItem, OutOfScopeReason, Problem

# ---------------------------------------------------------------------------
# 中間表現の項目の数の上限（評価の時間を抑える仮の値。法令の値ではない）
# ---------------------------------------------------------------------------

#: 人の数の上限。家族の人数としては大きいが、テストが多くの架空の人を1回で評価する（tests/test_kyuyo_egov.py：2,000人）。
MAX_PERSONS = 2_000
#: 記録・判断・選択（relations〜choices）の項目の合計の上限。okura_ir の検査と評価の時間は項目の数に比例する
#: （2万件の置き換えの連鎖で約14秒、給与の記録5万件で約30秒：packages/ir/README.md §6.3、2026-11-11 のレビュー）。
MAX_RECORDS = 20_000
_COUNTED = RECORD_SECTIONS + ("judgments", "choices")


def size_problems(ir: Any) -> list[Problem]:
    """中間表現の項目の数が上限を超えていれば問題を返す（okura_ir.validate の前に呼ぶ。形が違えば何も言わない）。"""
    if not isinstance(ir, dict):
        return []
    out: list[Problem] = []
    persons = ir.get("persons")
    if isinstance(persons, list) and len(persons) > MAX_PERSONS:
        out.append(Problem("$.ir.persons", "max_items", f"人は {MAX_PERSONS:,} 人まで（{len(persons):,} 人）"))
    total = sum(len(ir[s]) for s in _COUNTED if isinstance(ir.get(s), list))
    if total > MAX_RECORDS:
        out.append(
            Problem("$.ir", "max_items", f"記録・判断・選択の項目は合計 {MAX_RECORDS:,} 件まで（{total:,} 件）")
        )
    return out


# ---------------------------------------------------------------------------
# 所得に関係しうる記録・判断・選択の種類
# ---------------------------------------------------------------------------

INCOME_RELATED_RECORD_KINDS: frozenset[str] = frozenset(
    {
        # 取引
        "salary_payment", "business_receipt", "business_expense", "payroll_paid", "pension_payment",
        "retirement_payment", "dividend", "security_sale", "windfall_receipt", "benefit_receipt", "rent_flow",
        "casualty",  # 事業用の資産の損失は事業所得の必要経費（被災事業用資産）になりうる
        # 書類・届出
        "prior_income_fixed", "withholding_slip", "brokerage_annual", "blue_return_procedure", "bookkeeping_status",
        "family_employee_notice", "retirement_record", "ct_return", "rental_inventory",
        "specific_expense",  # 2026-11-12：給与所得者の特定支出（所法57の2。kyuyo KY-11）
        # 人の属性（業務・消費税・専従者）
        "business", "business_engagement", "ct_liability", "invoice_registration",
        # 資産
        "depreciable_asset", "rental_property", "lease", "loan",
        # 提出した申告書（申告した配当・課税方式の記載は合計所得金額に効く）
        "filed_document",
    }
)  # fmt: skip

INCOME_RELATED_DECISION_KINDS: frozenset[str] = frozenset(
    {
        "判断.事業と称するに至る程度", "判断.不動産の事業的規模", "判断.雇用か請負か", "判断.業務関連性", "判断.按分の割合",
        "判断.家内労働者等", "判断.減価償却の区分", "判断.不動産の区分の材料", "判断.正規の簿記の宣言", "判断.専従者給与の相当性",
        "判断.退職の性質", "判断.年金の性質", "判断.大口株主等",
        "選択.株式等の申告", "選択.現金主義（業務に係る雑所得）", "選択.消費税等の経理方式", "選択.減価償却", "選択.不動産所得の計上",
        "計画.申告の方法と時期",  # 青色申告特別控除の額（e-Tax・期限内）
        "選択.特定支出控除",  # 2026-11-12：給与所得の金額（所法57の2③。kyuyo KY-11）
    }
)  # fmt: skip

INCOME_RELATED_KINDS: frozenset[str] = INCOME_RELATED_RECORD_KINDS | INCOME_RELATED_DECISION_KINDS

#: 居住者かどうかに関わる記録・判断（居住者の判定を使うモジュールがない間の安全側の検出）。
RESIDENCY_RECORD_KINDS: frozenset[str] = frozenset({"abroad_stay"})
RESIDENCY_DECISION_KINDS: frozenset[str] = frozenset({"判断.住所の所在"})

RESIDENCY_REASON = (
    "居住者か非居住者かの判定はこの版では未対応（非居住者本人の申告は範囲外：D20・SCOPE §4）。"
    "この年分と重なる国外の滞在・住所の判断がある"
)


def strings_in(obj: Any) -> set[str]:
    """オブジェクトの中の文字列を全部集める（判断の対象の人・記録の ID を拾うため）。"""
    out: set[str] = set()
    if isinstance(obj, str):
        out.add(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            out |= strings_in(v)
    elif isinstance(obj, list):
        for v in obj:
            out |= strings_in(v)
    return out


def record_persons(rec: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(sorted(set(rec.get("roles", {}).values())))


@dataclass(frozen=True)
class InputScope:
    """シナリオの入力の対象外の検出の結果（年分に依らない部分と、年分で絞る材料）。"""

    items: tuple[OutOfScopeItem, ...]
    #: どのモジュールも使わない、所得に関係しうる記録・判断・選択：(人, when, ID)
    income_related: tuple[tuple[str, Mapping[str, Any] | None, str], ...]
    #: 記録の ID → それを対象にした、どのモジュールも使わない判断・選択の ID
    touched: Mapping[str, tuple[str, ...]]

    def incomplete_income(self, year: int) -> dict[str, tuple[str, ...]]:
        """人 → その年分と重なる、使わない所得に関係しうる記録・判断・選択の ID。"""
        out: dict[str, set[str]] = {}
        for pid, when, rid in self.income_related:
            if overlaps_year(when, year):
                out.setdefault(pid, set()).add(rid)
        return {p: tuple(sorted(v)) for p, v in out.items()}


def not_used_in_calculation(rec: Mapping[str, Any]) -> bool:
    """中間表現の語彙が「計算に使わない」と明記した種類・書類の種別か（packages/ir/README.md §6.4。2026-11-12）。"""
    if rec["kind"] in NOT_USED_IN_CALCULATION:
        return True
    attrs = rec.get("attributes")
    if not isinstance(attrs, Mapping):
        return False
    return any(rec["kind"] == k and attrs.get(a) == v for k, a, v in NOT_USED_IN_CALCULATION_VALUES)


def input_scope(ir: Mapping[str, Any], injected_entries: Any, reg: Registry) -> InputScope:
    person_ids = {p["id"] for p in ir["persons"]}
    used_decisions = reg.used_decision_kinds
    used_record_ids = {
        r["id"] for s in RECORD_SECTIONS for r in ir[s] if reg.uses_record(r)
    }
    items: list[OutOfScopeItem] = []
    income: list[tuple[str, Mapping[str, Any] | None, str]] = []
    touched: dict[str, set[str]] = {}
    for section in RECORD_SECTIONS:
        for rec in ir[section]:
            if reg.uses_record(rec):  # 種類より細かい宣言（RecordKind）は書類の種別などで絞る
                continue
            if not_used_in_calculation(rec):  # 計算に使わない種類・書類の種別（ir README §6.4）は未対応にしない
                continue
            persons = record_persons(rec)
            items.append(
                OutOfScopeItem(
                    {"section": section, "record_id": rec["id"], "kind": rec["kind"]},
                    persons,
                    OutOfScopeCategory.NOT_IMPLEMENTED,
                    "どの規則モジュールもこの種類の記録を使わない（使う種類は registry の record_kinds）",
                )
            )
            if rec["kind"] in INCOME_RELATED_RECORD_KINDS:
                income += [(p, rec.get("when"), rec["id"]) for p in persons]
    for section in ("judgments", "choices"):
        replaced = {x["replaces"] for x in ir[section] if x.get("replaces")}
        for j in ir[section]:
            if j["kind"] in used_decisions or not_used_in_calculation(j):
                continue
            mentioned = strings_in(j.get("subject", {}))
            persons = tuple(sorted(mentioned & person_ids))
            items.append(
                OutOfScopeItem(
                    {"section": section, "record_id": j["id"], "kind": j["kind"]},
                    persons,
                    OutOfScopeCategory.NOT_IMPLEMENTED,
                    "どの規則モジュールもこの種類の判断・選択を使わない",
                )
            )
            if j["kind"] in INCOME_RELATED_DECISION_KINDS and j["id"] not in replaced:
                income += [(p, j.get("when"), j["id"]) for p in persons]
            for rid in mentioned & used_record_ids:
                touched.setdefault(rid, set()).add(j["id"])
    for e in injected_entries:
        if e.point in reg.used_injection_points:
            continue
        items.append(
            OutOfScopeItem(
                {"section": "injected", "record_id": e.id, "kind": e.point},
                (),
                OutOfScopeCategory.NOT_IMPLEMENTED,
                "どの規則モジュールもこの注入点を使わない（使う注入点は registry の injections）",
            )
        )
    return InputScope(tuple(items), tuple(income), {r: tuple(sorted(v)) for r, v in touched.items()})


def residency_exclusions(ir: Mapping[str, Any], year: int, reg: Registry) -> dict[str, OutOfScopeReason]:
    """人 → 居住者の判定が未実装のための対象外の理由（居住者の判定を使うモジュールが登録されていれば空）。"""
    if (RESIDENCY_RECORD_KINDS & reg.used_record_kinds) or (RESIDENCY_DECISION_KINDS & reg.used_decision_kinds):
        return {}
    found: dict[str, list[str]] = {}
    for rec in ir["facts"]:
        if rec["kind"] in RESIDENCY_RECORD_KINDS and overlaps_year(rec.get("when"), year):
            found.setdefault(rec["roles"]["person"], []).append(rec["id"])
    for j in heads(ir["judgments"]):
        if j["kind"] in RESIDENCY_DECISION_KINDS and overlaps_year(j.get("when"), year):
            found.setdefault(j["subject"]["person"], []).append(j["id"])
    return {
        p: OutOfScopeReason(OutOfScopeCategory.NOT_IMPLEMENTED, RESIDENCY_REASON, tuple(sorted(ids)))
        for p, ids in found.items()
    }


# 死亡した人について、死亡した年より後の日付で書かれるのが通常の記録の種類。死亡した年分の評価
# （準確定申告の期限：所法124・125。rules/tax/inputs.py が年分によらず読む）で使うので、後の年分で
# 「生存していない人の記録」として未対応に数えない。
POST_DEATH_KINDS: frozenset[str] = frozenset({"heirship", "estate_liquidator"})


def not_alive_items(ir: Mapping[str, Any], year: int, alive: frozenset[str]) -> list[OutOfScopeItem]:
    """年分と重なる記録・判断・選択のうち、その年分に生存していない人（生まれる前・死亡した年より後）を対象にするもの。

    その人はその年分の situation に入れない（値を出さない）。記録は黙って捨てず、項目として返す。
    ただし死亡の後の日付で書かれるのが通常の種類（POST_DEATH_KINDS）は、死亡した年分の評価で使うので返さない。
    """
    person_ids = {p["id"] for p in ir["persons"]}
    out: list[OutOfScopeItem] = []
    for section in RECORD_SECTIONS:
        for rec in ir[section]:
            if not overlaps_year(rec.get("when"), year) or not_used_in_calculation(rec):
                continue
            if rec.get("kind") in POST_DEATH_KINDS:
                continue
            gone = tuple(p for p in record_persons(rec) if p not in alive)
            if gone:
                out.append(_gone_item(section, rec, gone, year))
    for section in ("judgments", "choices"):
        for j in ir[section]:
            if not overlaps_year(j.get("when"), year) or not_used_in_calculation(j):
                continue
            gone = tuple(sorted((strings_in(j.get("subject", {})) & person_ids) - alive))
            if gone:
                out.append(_gone_item(section, j, gone, year))
    return out


def _gone_item(section: str, rec: Mapping[str, Any], gone: tuple[str, ...], year: int) -> OutOfScopeItem:
    return OutOfScopeItem(
        {"section": section, "record_id": rec["id"], "kind": rec["kind"], "tax_year": year},
        gone,
        OutOfScopeCategory.NOT_IMPLEMENTED,
        "この年分に生存していない人（生年月日がこの年より後、又は死亡日がこの年より前）を対象にする記録・判断・選択がある。"
        "その人はこの年分の評価に入れない（死亡後に支給期の到来する給与等は、死亡した年分の評価で所基通9−17 により扱う。"
        "この年分の記録としては使わない）",
    )
