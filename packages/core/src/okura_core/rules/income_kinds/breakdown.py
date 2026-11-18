"""規則モジュール income_kinds：総収入金額・必要経費の内訳と事業専従者の事業主（2026-11-12。様式の対応表 forms の決算書・収支内訳書の科目：
design-output UO19、第二表の事業専従者の行：UO23）。

- 必要経費の内訳：事業所得・不動産所得の必要経費（所得税.<所得>の必要経費。減価償却費・専従者給与等の前）を、内訳のキーごとに分けた額。
  キーは記録の費目（中間表現の business_expense.attributes.expense_category の閉じた語彙：okura_ir.vocabulary.EXPENSE_CATEGORIES）と、
  記録の費目でない内訳（給与の支払 payroll_paid の wages・professional_fee、消費税等、資産の除却損・災害等の損失・譲渡の費用）。
  所得税法施行規則第47条の3 が内訳書に必要経費を区分して書かせるので、その区分の材料（法令の区分そのものではない。様式の科目への割当ては
  forms/data/r07/割当て/科目.yaml）。
  内訳の合計と必要経費の差は「内訳のない額」（0 が正常。ほかの担当が必要経費を足す箇所を増やして内訳を書かなかったときに、黙って雑費に入れないため）。
- 総収入金額の内訳：事業所得は売上（business_receipt）とその他の収入（それ以外：資産の譲渡の収入・消費税等の還付など）、不動産所得は賃料
  （rent・common_service_fee）、礼金・権利金・更新料（key_money・renewal_fee）、名義書換料・その他（それ以外）。その他は総収入金額との差。
- 事業専従者の事業主・専従者給与等の額（専従者の側の値）：その人を青色事業専従者・事業専従者とする事業主の人の ID と、その事業主の
  必要経費に算入される青色事業専従者給与の額又は事業専従者控除額（所法57①③）。二以上の事業主の専従者は対象外（行の割当てを決められない）。

inputs.py は _Sides.brk（Breakdown）に、必要経費・総収入金額を足すのと同じ箇所で内訳を足す。書き出しは write_breakdown・write_employers。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from openfisca_core.model_api import YEAR, Variable

from ...country.entities import 人物
from ...registry import ModuleInputs
from ...result import OutOfScopeCategory, OutOfScopeReason, Split, State

JIGYO = "docs/public-sources/20261109_impl-prep_jigyo-laws-and-nta.md"
FORMS = "docs/public-sources/20261109_impl-prep_output-forms-and-specs.md"
FUDOSAN = "docs/public-sources/20261109_round2b_fudosan-laws-and-nta.md"
AOIRO = "docs/public-sources/20261109_round2_aoiro-laws-and-nta.md"

#: 所得の側 → 概念・変数の名前の所得。
INCOMES: Mapping[str, str] = {"biz": "事業所得", "rental": "不動産所得"}

#: 記録の費目（okura_ir.vocabulary.EXPENSE_CATEGORIES から業務の支出でない dividend_debt_interest を除いたもの。並びも同じ）。
RECORD_KEYS: tuple[str, ...] = (
    "merchandise", "materials", "outsourcing", "tax", "membership_dues", "shipping", "utilities", "travel", "communication",
    "advertising", "entertainment", "insurance", "repairs", "supplies", "welfare", "rent", "loan_interest", "interest", "fees",
    "management", "other",
)  # fmt: skip
#: 記録の費目でない内訳。inventory_change は売上原価の棚卸高の調整（期首棚卸高－期末棚卸高。負になりうる：所法47・37①。IK-108）、
#: bad_debt は貸倒れ（所法51②④・所令141・所法64①：IK-110）。
OTHER_KEYS: tuple[str, ...] = ("payroll_wages", "payroll_professional_fee", "consumption_tax", "asset_loss", "inventory_change", "bad_debt")
KEYS: tuple[str, ...] = RECORD_KEYS + OTHER_KEYS
#: 仕入金額（売上原価の基礎）の内訳のキー。
PURCHASE_KEYS: tuple[str, ...] = ("merchandise", "materials")

#: 総収入金額の内訳のキー（記録で決まるもの。その他は総収入金額との差）。
REV_SALES = "sales"
REV_HOUSEHOLD = "household"  # 家事消費等（所法39・40①一：IK-109）
REV_RENT = "rent"
REV_KEY_MONEY = "key_money"
RENT_FLOW_KEYS: Mapping[str, str] = {"rent": REV_RENT, "common_service_fee": REV_RENT, "key_money": REV_KEY_MONEY, "renewal_fee": REV_KEY_MONEY}

V_EMPLOYER = "所得税_事業専従者の事業主"
V_EMPLOYEE_AMOUNT = "所得税_事業専従者の専従者給与等の額"
#: 事業主がいないとき（結果の区分の値は空でない文字列：result.Category。人の ID は ASCII なので衝突しない）。
NO_PERSON = "なし"


#: 変数名の制度の接頭辞（「所得税」＋「_」。文字列の定数を変数名と取り違えないよう分けて書く：tests/test_architecture の名前の検査）。
_PREFIX = "所得税"


def exp_variable(side: str, key: str) -> str:
    return f"{_PREFIX}_{INCOMES[side]}の必要経費の内訳_{key}"


def unclassified_variable(side: str) -> str:
    return f"{_PREFIX}_{INCOMES[side]}の必要経費のうち内訳のない額"


#: 総収入金額の内訳の変数（所得の側 → (キー, 変数)。キー None はその他＝総収入金額との差）。
REV_VARIABLES: Mapping[str, tuple[tuple[str | None, str], ...]] = {
    "biz": (
        (REV_SALES, "所得税_事業所得の総収入金額のうち売上の金額"),
        (REV_HOUSEHOLD, "所得税_事業所得の総収入金額のうち家事消費等の金額"),
        (None, "所得税_事業所得の総収入金額のうちその他の収入の金額"),
    ),
    "rental": (
        (REV_RENT, "所得税_不動産所得の総収入金額のうち賃貸料の金額"),
        (REV_KEY_MONEY, "所得税_不動産所得の総収入金額のうち礼金・権利金・更新料の金額"),
        (None, "所得税_不動産所得の総収入金額のうち名義書換料・その他の金額"),
    ),
}


def record_key(rec: Mapping[str, Any]) -> str:
    """支出・給与の支払の記録の内訳のキー。"""
    if rec["kind"] == "payroll_paid":
        return "payroll_professional_fee" if rec["attributes"].get("pay_type") == "professional_fee" else "payroll_wages"
    return str(rec["attributes"]["expense_category"])


@dataclass
class Breakdown:
    """1人の、所得の側ごとの内訳（inputs._Sides.brk）。"""

    exp: dict[str, dict[str, int]] = field(default_factory=dict)
    rev: dict[str, dict[str, int]] = field(default_factory=dict)
    rec_key: dict[str, str] = field(default_factory=dict)  # 記録 → 内訳のキー

    def add_exp(self, side: str, key: str, amount: int) -> None:
        if amount:
            d = self.exp.setdefault(side, {})
            d[key] = d.get(key, 0) + amount

    def add_rev(self, side: str, key: str, amount: int) -> None:
        if amount:
            d = self.rev.setdefault(side, {})
            d[key] = d.get(key, 0) + amount

    def add_record(self, side: str, rec: Mapping[str, Any], amount: int) -> None:
        key = record_key(rec)
        self.rec_key[rec["id"]] = key
        self.add_exp(side, key, amount)

    def move_all_to(self, side: str, other: Breakdown, other_side: str) -> None:
        """自分の side の必要経費の内訳の全部を other の other_side へ移す（所法56 後段）。"""
        for key, amount in sorted(self.exp.pop(side, {}).items()):
            other.add_exp(other_side, key, amount)

    def move_to(self, side: str, other: Breakdown, other_side: str, key: str, amount: int) -> None:
        self.add_exp(side, key, -amount)
        other.add_exp(other_side, key, amount)

    def move_records_to(self, side: str, other: Breakdown, other_side: str, rec_exp: Mapping[str, int], record_ids: Iterable[str]) -> None:
        for rid in sorted(record_ids):
            if rid in rec_exp and rid in self.rec_key:
                self.move_to(side, other, other_side, self.rec_key[rid], rec_exp[rid])


def _input(name: str, label: str, refs: list[str], vt: type = int, default: object | None = None) -> type:
    attrs = {"value_type": vt, "entity": 人物, "definition_period": YEAR, "label": label, "reference": refs, "__module__": __name__}
    if default is not None:
        attrs["default_value"] = default
    return type(name, (Variable,), attrs)


_EXP_REFS = [f"{FORMS}#3", f"{JIGYO}#7.4", f"{FUDOSAN}#2.3"]
_VARS: list[type] = []
for _side in INCOMES:
    for _key in KEYS:
        _VARS.append(_input(exp_variable(_side, _key), f"{INCOMES[_side]}の必要経費のうち内訳のキー {_key} の額（所規47の3 の区分の材料）", _EXP_REFS))
    _VARS.append(_input(unclassified_variable(_side), f"{INCOMES[_side]}の必要経費のうち内訳のキーのない額（0 が正常）", _EXP_REFS))
    for _rk, _rv in REV_VARIABLES[_side]:
        _VARS.append(_input(_rv, f"{INCOMES[_side]}の総収入金額の内訳（{_rv.split('のうち')[-1]}）", [f"{FORMS}#3", f"{FUDOSAN}#2.3"]))
_VARS.append(
    _input(V_EMPLOYER, "その人を青色事業専従者・事業専従者とする事業主の人の ID（いなければ「なし」。二以上なら対象外）", [f"{AOIRO}#4.1", f"{JIGYO}#1.1"], vt=str, default=NO_PERSON)
)
_VARS.append(_input(V_EMPLOYEE_AMOUNT, "事業主の必要経費に算入される青色事業専従者給与の額又は事業専従者控除額（所法57①③。その人の分）", [f"{AOIRO}#4.1", f"{JIGYO}#1.1"]))

#: 売上原価の欄の材料（事業所得。収支内訳書⑤〜⑨・決算書2〜6：IK-108）。
TANAOROSHI = "docs/public-sources/20261112_impl-research6_tanaoroshi-laws-and-nta.md"
V_OPENING = "所得税_事業所得の期首商品棚卸高"
V_CLOSING = "所得税_事業所得の期末商品棚卸高"
V_PURCHASES = "所得税_事業所得の仕入金額"
V_COGS = "所得税_事業所得の売上原価"
COGS_VARIABLES = (V_OPENING, V_CLOSING, V_PURCHASES, V_COGS)
_COGS_REFS = [f"{TANAOROSHI}#1.1", f"{TANAOROSHI}#2.3", f"{TANAOROSHI}#6"]
_VARS.append(_input(V_OPENING, "事業所得の期首棚卸高（前年の12月31日の棚卸しの評価額・その年の期首の棚卸し。その年に始めた業務は0）", _COGS_REFS))
_VARS.append(_input(V_CLOSING, "事業所得の期末棚卸高（所法47①・所令99〜102 の評価の方法で評価した12月31日〔死亡の日〕の棚卸資産の額）", _COGS_REFS))
_VARS.append(_input(V_PURCHASES, "事業所得の仕入金額（必要経費の内訳 merchandise・materials の合計）", _COGS_REFS))
_VARS.append(_input(V_COGS, "事業所得の売上原価（期首棚卸高＋仕入金額－期末棚卸高。所法37①・47①）", _COGS_REFS))


class 所得税_事業所得の差引金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "事業所得の総収入金額から売上原価を差し引いた金額（収支内訳書⑩・決算書7）"
    reference = _COGS_REFS

    def formula_2025_01_01(人, period, parameters):
        return 人("所得税_事業所得の総収入金額", period) - 人("所得税_事業所得の売上原価", period)


_VARS.append(所得税_事業所得の差引金額)


class 所得税_事業所得の売上原価以外の経費の計(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "事業所得の必要経費（減価償却費を含む）のうち売上原価以外の経費の計（収支内訳書⑱・決算書32。専従者給与等の前）"
    reference = _COGS_REFS

    def formula_2025_01_01(人, period, parameters):
        return (
            人("所得税_事業所得の必要経費", period) + 人("所得税_事業所得の減価償却費", period) - 人("所得税_事業所得の売上原価", period)
        )


_VARS.append(所得税_事業所得の売上原価以外の経費の計)

VARIABLES: tuple[type, ...] = tuple(_VARS)


def write_cost_of_sales(
    out: ModuleInputs,
    pid: str,
    brk: Breakdown,
    side: str,
    inventory: tuple[int, int],
    ids: Iterable[str],
    states: Iterable[State],
    missing: Iterable[Split],
    reasons: Iterable[OutOfScopeReason],
) -> None:
    """事業所得の売上原価の欄の材料を書く（inventory は (期首, 期末)）。仕入金額は内訳の merchandise・materials（所法56 の移し替えの後）。"""
    if side != "biz":
        return
    ids, states, missing, reasons = tuple(ids), set(states), tuple(missing), tuple(reasons)
    for r in reasons:
        for v in COGS_VARIABLES:
            out.exclude(pid, r, v)
    excluded = bool(reasons)
    opening, closing = (0, 0) if excluded else inventory
    purchases = 0 if excluded else sum(brk.exp.get(side, {}).get(k, 0) for k in PURCHASE_KEYS)
    for var, value in ((V_OPENING, opening), (V_CLOSING, closing), (V_PURCHASES, purchases), (V_COGS, opening + purchases - closing)):
        out.set(var, pid, value, ids, states, missing=missing)


def write_breakdown(
    out: ModuleInputs,
    pid: str,
    brk: Breakdown,
    side: str,
    totals: tuple[int, int],
    ids: Iterable[str],
    states: Iterable[State],
    missing: Iterable[Split],
    reasons: Iterable[OutOfScopeReason],
) -> None:
    """所得の側の内訳を書く。totals は書いた（総収入金額, 必要経費）。reasons は必要経費・総収入金額が対象外の理由（内訳も対象外）。"""
    if side not in INCOMES:
        return
    ids, states, missing, reasons = tuple(ids), set(states), tuple(missing), tuple(reasons)
    rev_total, exp_total = totals
    names = [exp_variable(side, k) for k in KEYS] + [unclassified_variable(side)] + [v for _, v in REV_VARIABLES[side]]
    for r in reasons:
        for v in names:
            out.exclude(pid, r, v)
    excluded = bool(reasons)
    amounts = brk.exp.get(side, {})
    for key in KEYS:
        out.set(exp_variable(side, key), pid, 0 if excluded else amounts.get(key, 0), ids, states, missing=missing)
    out.set(unclassified_variable(side), pid, 0 if excluded else exp_total - sum(amounts.get(k, 0) for k in KEYS), ids, states, missing=missing)
    revs = brk.rev.get(side, {})
    known = 0
    for key, var in REV_VARIABLES[side]:
        if key is None:
            out.set(var, pid, 0 if excluded else rev_total - known, ids, states, missing=missing)
        else:
            known += revs.get(key, 0)
            out.set(var, pid, 0 if excluded else revs.get(key, 0), ids, states, missing=missing)


def write_employers(
    out: ModuleInputs,
    persons: Iterable[str],
    allowed: Mapping[tuple[str, str, str], tuple[int, list[Split]]],
    deemed: Mapping[str, list[tuple[int, list[str], set[State]]]],
    deemed_from: Mapping[str, set[str]],
    tainted: Mapping[str, list[OutOfScopeReason]],
    unsure: Mapping[str, list[Split]],
) -> None:
    """専従者の側：事業主の人の ID と、その事業主の必要経費に算入される専従者給与等の額（青色は allowed、白色は deemed）。"""
    for p in persons:
        blue = {(o, b): v for (o, e, b), v in allowed.items() if e == p}
        owners = sorted({o for o, _ in blue} | set(deemed_from.get(p, ())))
        if not owners:
            out.set(V_EMPLOYER, p, NO_PERSON)
            out.set(V_EMPLOYEE_AMOUNT, p, 0)
            continue
        if len(owners) > 1:
            r = OutOfScopeReason(
                OutOfScopeCategory.NOT_IMPLEMENTED,
                f"二以上の事業主（{'・'.join(owners)}）の事業専従者：第二表の事業専従者の行に載せる事業主を決める規則がない（様式の対応表）",
            )
            for v in (V_EMPLOYER, V_EMPLOYEE_AMOUNT):
                out.exclude(p, r, v)
            out.set(V_EMPLOYER, p, NO_PERSON)
            out.set(V_EMPLOYEE_AMOUNT, p, 0)
            continue
        owner = owners[0]
        amount = sum(a for a, _ in blue.values()) + sum(a for a, _, _ in deemed.get(p, []))
        ids = [i for _, rs, _ in deemed.get(p, []) for i in rs]
        st: set[State] = set()
        for _, _, s_ in deemed.get(p, []):
            st |= s_
        miss = [x for _, sp in blue.values() for x in sp] + list(unsure.get(owner, []))
        for r in tainted.get(owner, []):
            out.exclude(p, r, V_EMPLOYEE_AMOUNT)
        out.set(V_EMPLOYER, p, owner, ids, st)
        out.set(V_EMPLOYEE_AMOUNT, p, amount, ids, st, missing=miss)
