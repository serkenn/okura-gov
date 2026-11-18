"""規則モジュール kyuyo の situation への写し方（中間表現の salary_payment・withholding_slip → 所得税_給与等の収入金額）。

- 年分（D23 K3・所基通36−9）：受給者ごとに、支給日（attributes.due_on）の年の支払を数える。due_on は中間表現で必須。
  死亡の日より後に支給日が来る給与は所得税に入れない（所基通9−17、D22 S10）。死亡の日と同じ支給日・定めのない支給日の給与は判断の分かれ目。
- 給与等の収入金額＝総支給額（gross）＋現物の定期券の価額−非課税の通勤手当（tsukin.py）。同じ支払者で源泉徴収票があれば、
  その「支払金額」を優先し、明細は食い違いの検出に使う（D23 K4）。
- 入力が足りない・読みが分かれるところ（通勤の状況や合理的な運賃の未入力、限度額の当て方）は単調な判断の両端で評価する（D21 R6、tsukin HT5）。
- 事業専従者控除額のみなし給与（所法57④）：income_kinds の 所得税_事業専従者としてみなされる給与の収入金額 を段階評価の段（StageSpec(run=None)）で読んで足す。
  同じ段で、判断.退職の性質 で退職手当等に当たらず給与とした支払（income_kinds の 所得税_退職手当等に当たらないとした給与等の収入金額。IK-25）も足す。
- 未払のまま回収することができないこととなった給与（所法64①。KY-08）：回収不能額等を 所得税_回収することができないこととなった給与等の金額 に入れる
  （給与等の収入金額は変えない。なかったものとみなす額は 所得税_給与所得 の式で当てる：uncollectible.py）。
- 認定賞与（36−9(4)）は due_on（定めがなければ支給を受けた日）の年で数える。
- 役員の利益連動の賞与（36−9(2)）は決議等の日（resolution_on）、各人ごとの支給金額が後で定められたときはその日（amount_fixed_on）の年で数える
  （due_date。死亡の前後・通勤手当の版も同じ日）。resolution_on がなければ入力の不足として対象外（due_on の年分で検出）。
- 同じ月に交通手段の違う通勤の状況（一次情報なし）と、障害者の 2km 未満の自動車通勤（質疑応答事例 03/18 の「差し支えない」取扱い）は、
  限度額の候補の全部を両端にして、読みの分かれ目（判断.通勤手当の限度の当て方）で評価する（D21 R6・D22 S1）。
- 対象外（その人・年分の 所得税_給与等の収入金額 を対象外にし、依存する値へ伝える）：役員の利益連動の賞与で決議等の日がない、
  合計が int32 の上限を超える、支払者の分からない源泉徴収票を明細と突き合わせられないとき、同じ支払者の源泉徴収票が複数あるとき。
- 記録の印（予測・見積り・計画）は状態として由来に入れる（evaluate がトレースに沿って依存する値へ伝える）。
"""

from __future__ import annotations

import datetime as _dt
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ...basis import BasisEntry, BasisType, ReadingFlag, SourceKind
from ...candidates import Candidate
from ...money import INT32_MAX
from ...registry import DecisionSlot, DecisionSpec, ModuleInputs, YearContext
from ...result import OutOfScopeCategory, OutOfScopeReason, State
from .tsukin import Item, Limit, Version, mixed_limit, monthly_limit, nontaxable_bounds, version_for, versions_from_parameters
from .tokutei import (
    C_TOKUTEI,
    J_ROUTE,
    ROUTE_RULE,
    TOKUTEI_RULE,
    TOTAL_RULE,
    FORM_COLUMNS,
    FORM_ROWS,
    V_APPLY,
    V_TOTAL,
    category_code_sum,
    collect,
    expense_year,
    form_row_variable,
    form_rows,
    needs_route_judgment,
)

#: 給与所得者の特定支出に関する明細書（KOB070）の欄の材料（2026-11-12 の3回目：variables.FORM_VARIABLES）
V_FORM_ROWS: tuple[tuple[str, str, str], ...] = tuple(
    tuple(form_row_variable(k, col) for col in FORM_COLUMNS) for k in range(1, len(FORM_ROWS) + 1)  # type: ignore[misc]
)
V_FORM_WORK = "所得税_特定支出に関する明細書の勤務必要経費の小計"
V_FORM_CODES = "所得税_適用を受ける特定支出の区分の合計"

V_INCOME = "所得税_給与等の収入金額"
#: 事業専従者控除額のうち専従者の給与の収入金額とみなす額（所法57④。income_kinds が作る入力。段 STAGE_DEEMED で読む）。
V_DEEMED = "所得税_事業専従者としてみなされる給与の収入金額"
#: 生計を一にする親族の事業から受けた給与のうち、所法56 によりないものとみなす額（income_kinds が作る入力。段 STAGE_DEEMED で読んで引く。2026-11-12）。
V_FAMILY_OUT = "所得税_生計を一にする親族の事業から受けた給与のうち収入金額に含めない額"
#: 判断.退職の性質 で退職手当等に当たらず給与とした支払の額（income_kinds が作る入力。段 STAGE_DEEMED で読んで足す。IK-25、2026-11-12）。
V_RETIRE_SALARY = "所得税_退職手当等に当たらないとした給与等の収入金額"
STAGE_DEEMED = "事業専従者のみなし給与"
#: 未払のまま回収することができないこととなった給与の金額（所法64①の回収不能額等。KY-08。uncollectible.py の段が読む）。
V_UNCOLLECTIBLE = "所得税_回収することができないこととなった給与等の金額"

K_FARE = "判断.通勤の合理的な運賃"
K_READING = "判断.通勤手当の限度の当て方"
K_DEATH = "判断.給与の支給期が死亡前か"
#: 障害者が交通用具を使用する特別の事情（質疑応答事例 03/18。2026-11-12 に語彙を足した。判断を直接読む：未入力・食い違いは読みの両端）。
K_SPECIAL = "判断.障害者の通勤の特別の事情"

#: 通勤手当の非課税の額の両端（単調な判断の両端評価。D21 R6）。
LOW = "low"
HIGH = "high"
BOUND_CANDIDATES = (Candidate(LOW, "非課税を小さく取る端"), Candidate(HIGH, "非課税を大きく取る端"))

OFFICER_BONUS = "officer_bonus_by_resolution"

UNSUPPORTED_PAYMENT_REASON = (
    "入力の不足：役員の利益連動の賞与（payment_type: officer_bonus_by_resolution）に決議等の日（attributes.resolution_on）がない"
    "（所基通36−9(2)：収入すべき時期は決議等があった日、各人ごとの支給金額が後で定められたときはその日〔attributes.amount_fixed_on〕。"
    "支給日 due_on では年分を決めない）"
)
SLIP_NO_PAYER_REASON = (
    "入力の不足：支払者の名（attributes.counterparty）がない給与の源泉徴収票があり、給与の明細と突き合わせられない"
    "（どの支払者の給与を源泉徴収票で優先するか決められない：D23 K4）。源泉徴収票に counterparty を書く"
)
DUPLICATE_SLIP_REASON = (
    "入力の矛盾：同じ支払者（attributes.counterparty）の給与の源泉徴収票が同じ年分に2枚以上ある（訂正か別の期間かを区別できない）。"
    "訂正なら訂正前の票を記録から除き、前の支払者の分を通算した票なら attributes.includes_prior_payers に前の支払者を書く"
)

JIKI = "docs/public-sources/20261111_impl-research_kyuyo-jiki-laws-and-nta.md"
TSUKIN = "docs/public-sources/20261111_impl-research_tsukin-laws-and-nta.md"

AFTER_DEATH_RULE = BasisEntry(
    type=BasisType.RULE,
    name="死亡後に支給期の到来する給与は所得税に入れない",
    source_kind=SourceKind.CIRCULAR,
    law="所得税基本通達9−17（相続税法の規定により相続税の課税価格計算の基礎に算入されるものについては課税しない。支給期は同36−9）",
    references=(f"{JIKI}#2.2", f"{JIKI}#3"),
)
FUDOSAN = "docs/public-sources/20261109_round2b_fudosan-laws-and-nta.md"
DEEMED_RULE = BasisEntry(
    type=BasisType.RULE,
    name="事業専従者控除額を専従者の給与所得に係る収入金額とみなす",
    source_kind=SourceKind.LAW,
    law="所得税法第57条第4項（控除額は所法57③。白色の事業専従者控除：income_kinds が計算する）",
    references=(f"{FUDOSAN}#5.1",),
)
FAMILY_OUT_RULE = BasisEntry(
    type=BasisType.RULE,
    name="生計を一にする親族の事業から受けた給与（青色事業専従者給与を除く）はないものとみなす",
    source_kind=SourceKind.LAW,
    law="所得税法第56条（その親族が支払を受けた対価の額は各種所得の金額の計算上ないものとみなす）・第57条第1項（青色事業専従者給与は前条にかかわらず給与所得の収入金額）。"
    "額は income_kinds が支払った人の事業から計算する",
    references=(f"{FUDOSAN}#5.1", "docs/public-sources/20261109_round2_aoiro-laws-and-nta.md#4.1"),
)
DEEMED_BONUS_RULE = BasisEntry(
    type=BasisType.RULE,
    name="認定賞与の収入すべき時期：支給日が定められていればその支給日、なければ現実に支給を受けた日",
    source_kind=SourceKind.CIRCULAR,
    law="所得税基本通達36−9(4)。中間表現の due_on（定めがないときは支給を受けた日を書き due_stipulated: false）の年で数える。"
    "「その日が明らかでない場合」（事業年度の終了の日）は記録の語彙がないので当てない",
    references=(f"{JIKI}#2.1",),
    flags=(ReadingFlag.LEGAL_READING,),
)
SLIP_PRIORITY_RULE = BasisEntry(
    type=BasisType.RULE,
    name="源泉徴収票の「支払金額」を優先し、給与の明細の値は食い違いの検出に使う",
    source_kind=SourceKind.NTA_EXPLANATION,
    law="HANDOFF D23 K4。「支払金額」はその年中に支払の確定した給与等の総額で、非課税の通勤手当を除く（手引「支払金額」欄、通勤手当の案内）",
    references=(f"{JIKI}#3", f"{TSUKIN}#5"),
)
COMMUTING_RULE = BasisEntry(
    type=BasisType.RULE,
    name="給与等の収入金額＝総支給額−非課税の通勤手当",
    source_kind=SourceKind.CABINET_ORDER,
    law="所得税法第9条第1項第5号・同施行令第20条の2（柱書「所得税を課さない」の読み。国税庁の説明：通勤手当の案内の §3・§4）",
    references=(f"{TSUKIN}#1", f"{TSUKIN}#2.2", f"{TSUKIN}#5"),
    flags=(ReadingFlag.LEGAL_READING,),
)
STATED_NONTAXABLE_RULE = BasisEntry(
    type=BasisType.RULE,
    name="通勤手当の非課税の額は支払者の区分（給与明細の記載）を使った",
    source_kind=SourceKind.NTA_EXPLANATION,
    law="通勤の状況の事実がないときの代わりの経路（支払者が付けた区分。質疑応答事例 03/22 の区分識別）",
    references=(f"{TSUKIN}#4.4",),
    flags=(ReadingFlag.LEGAL_READING,),
)
OFFICER_BONUS_RULE = BasisEntry(
    type=BasisType.RULE,
    name="役員の利益連動の賞与の収入すべき時期：決議等があった日（各人ごとの支給金額が後で定められたときはその日）",
    source_kind=SourceKind.CIRCULAR,
    law="所得税基本通達36−9(2)（中間表現の resolution_on・amount_fixed_on の年で数える。支給期〔所基通9−17 の注〕も同じ日）",
    references=(f"{JIKI}#2.1", f"{JIKI}#2.2"),
)
MIXED_MEANS_RULE = BasisEntry(
    type=BasisType.RULE,
    name="同じ月に交通手段の違う通勤の状況：それぞれの交通手段の号の限度額の全部を候補にして評価した",
    source_kind=SourceKind.NTA_EXPLANATION,
    law="月の中途の変更の当て方の一次情報は距離の変更だけ（質疑応答事例 03/20「特段の規定はありません」）。交通手段の変更は一次情報がないので"
    "候補の全部で評価し、分かれれば未確定（D21 R6・D22 S1。決める手段：判断.通勤手当の限度の当て方 か 明細の commuting_nontaxable_stated）",
    references=(f"{TSUKIN}#4.4",),
    flags=(ReadingFlag.LEGAL_READING,),
)
DISABLED_SHORT_RULE = BasisEntry(
    type=BasisType.RULE,
    name="障害者の片道2km未満の自動車通勤：交通機関を利用したとした場合の合理的な運賃の額を限度額として差し支えない（当てはめは候補で評価）",
    source_kind=SourceKind.NTA_EXPLANATION,
    law="質疑応答事例 03/18。判断.障害者の通勤の特別の事情 が未入力（又は食い違い）なので、全額課税と合理的な運賃の額の両端で評価する（D21 R6。"
    "決める手段：判断.障害者の通勤の特別の事情・判断.通勤手当の限度の当て方 か 明細の commuting_nontaxable_stated）",
    references=(f"{TSUKIN}#4.4",),
    flags=(ReadingFlag.LEGAL_READING,),
)
SHOTOKU4 = "docs/public-sources/20261112_impl-research4_shotoku-laws-and-nta.md"
UNCOLLECTIBLE_RULE = BasisEntry(
    type=BasisType.RULE,
    name="未払のまま回収することができないこととなった給与（uncollectible_amount）の金額を、所得税法第64条第1項の回収不能額等とした",
    source_kind=SourceKind.LAW,
    law=(
        "所得税法第64条第1項（事業所得・事業から生じたものだけが除かれ、給与所得は除かれていない）・施行令第180条第2項・第152条（更正の請求の特例）、"
        "所得税基本通達64−1（51−11〜51−16 に準ずる）。使用人の未払給与に当てた国税庁の説明は見つからない（役員の未払賞与の辞退は64−2）ので、"
        "条文の文言で当てる（法令の読み）。未払の部分は源泉徴収されていないので、回収不能額等は記録の額の全額（配当の個別通達の考え方：PS4-SH §1.3）。"
        "なかったものとみなす額は給与所得の金額の計算で当てる（kyuyo の 所得税_給与所得。給与等の収入金額は変えない）"
    ),
    references=(f"{SHOTOKU4}#1", f"{SHOTOKU4}#1.1", f"{SHOTOKU4}#1.3"),
    flags=(ReadingFlag.LEGAL_READING,),
)
UNCOLLECTIBLE_INPUT_REASON = (
    "回収することができないこととなった金額（amounts.uncollectible_amount）が、未払（attributes.unpaid）でない支払に書かれているか、総支給額を超える（記録を直せば決まる）"
)
RETIRE_SALARY_RULE = BasisEntry(
    type=BasisType.RULE,
    name="判断.退職の性質 で退職手当等に当たらず給与とした支払を、給与等の収入金額に足した（income_kinds の値）",
    source_kind=SourceKind.CIRCULAR,
    law=(
        "所得税法第28条第1項・第30条第1項、所得税基本通達30−1（退職手当等に当たらないもの）・36−9(1)（支給日の定めを記録する欄がないので、"
        "支払の日〔when.on〕を支給を受けた日として年分を決める：法令の読み）。額と年分は income_kinds が決める"
    ),
    references=(f"{JIKI}#2.1", "docs/public-sources/20261109_round2b_taishoku-laws-and-guidance.md#1.2"),
    flags=(ReadingFlag.LEGAL_READING,),
)
DISABLED_SPECIAL_RULE = BasisEntry(
    type=BasisType.RULE,
    name="障害者の片道2km未満の自動車通勤：判断.障害者の通勤の特別の事情 により、真なら合理的な運賃の額を限度額、偽なら全額課税とした",
    source_kind=SourceKind.NTA_EXPLANATION,
    law="質疑応答事例 03/18（交通機関を利用したとした場合の合理的な運賃の額を非課税限度額として差し支えない）",
    references=(f"{TSUKIN}#4.4",),
    flags=(ReadingFlag.LEGAL_READING,),
)
ITEMIZED_RULE = BasisEntry(
    type=BasisType.RULE,
    name="給与明細書等で区分して表示されていない通勤手当は非課税にしない",
    source_kind=SourceKind.NTA_EXPLANATION,
    law="質疑応答事例 03/22（「給与明細書等において…通勤手当として区分識別できるのであれば」非課税）",
    references=(f"{TSUKIN}#4.4",),
)


def _d(text: str) -> _dt.date:
    return _dt.date.fromisoformat(text)


def _ym(d: _dt.date) -> tuple[int, int]:
    return (d.year, d.month)


def due_date(rec: Mapping[str, Any]) -> _dt.date | None:
    """収入すべき時期の日（所基通36−9）。役員の利益連動の賞与（(2)）は各人ごとの支給金額が定められた日（amount_fixed_on）か
    決議等の日（resolution_on）、決議等の日がなければ None（入力の不足）。それ以外は支給日 due_on（(1)・(3)・(4)）。"""
    attrs = rec["attributes"]
    if attrs.get("payment_type") == OFFICER_BONUS:
        on = attrs.get("amount_fixed_on") or attrs.get("resolution_on")
        return _d(on) if on else None
    return _d(attrs["due_on"])


def _due(rec: Mapping[str, Any]) -> _dt.date:
    on = due_date(rec)
    return on if on is not None else _d(rec["attributes"]["due_on"])


def _table_on(rec: Mapping[str, Any]) -> _dt.date:
    """限度額の版を選ぶ日：差額の追給は元の支給日（附則の「受けるべき通勤手当」・特定差額追給手当）、それ以外は支給日（36−9 の日）。"""
    attrs = rec["attributes"]
    if attrs.get("payment_type") == "retroactive_difference":
        return _d(attrs["original_due_on"])
    return _due(rec)


def _paid_ym(rec: Mapping[str, Any]) -> tuple[int, int]:
    """支給を受けた月（未払なら支給日の月）。"""
    if rec["attributes"].get("unpaid"):
        return _ym(_due(rec))
    return _ym(_d(rec["when"]["on"]))


def _period_overlaps_month(when: Mapping[str, Any], ym: tuple[int, int]) -> bool:
    y, m = ym
    first = _dt.date(y, m, 1)
    last = (_dt.date(y + (m == 12), m % 12 + 1, 1) - _dt.timedelta(days=1))
    start = _d(when["from_on"])
    end = _d(when["to_on"]) if when.get("to_on") else None
    return start <= last and (end is None or end >= first)


def _states_of(rec: Mapping[str, Any]) -> set[State]:
    return {State.from_mark(rec["mark"])} if "mark" in rec else set()


# ---------------------------------------------------------------------------
# 年分の材料（支給日で年分を決める）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DeathDecision:
    """死亡の日と同じ日の支給日・定めのない支給日の給与（判断の分かれ目）。"""

    record: Mapping[str, Any]


@dataclass
class Row:
    """通勤手当のある1回の支払と、その版・状況から決まる1か月の限度額。"""

    record: Mapping[str, Any]
    payer: str
    limit: Limit
    stated: int | None
    fare_key: str | None
    status_ids: tuple[str, ...]
    status_states: frozenset[State]
    version: Version
    covering: tuple[Mapping[str, Any], ...]
    disabled: bool = False
    special: bool | None = None  # 判断.障害者の通勤の特別の事情（disabled のときだけ読む）

    @property
    def allowance(self) -> int:
        a = self.record["amounts"]
        return a.get("commuting_allowance", 0) + a.get("commuting_pass_value", 0)

    @property
    def months(self) -> int:
        return max(1, self.record["attributes"].get("commuting_months", 1))

    @property
    def uses_stated(self) -> bool:
        """支払者の区分（明細の記載）を非課税の額として使うか（通勤の状況・判断で限度額が決まらず、区分があるとき）。"""
        return self.stated is not None and (self.limit.needs_fare or self.limit.split)

    def item(self, limit: int) -> Item:
        return Item(self.allowance, limit, self.months, self.payer, _ym(_table_on(self.record)), _paid_ym(self.record))


@dataclass
class Plan:
    """1人の年分の材料（判断の分かれ目の宣言と入力の組み立ての両方が使う）。"""

    pid: str
    payments: list[Mapping[str, Any]]
    deaths: list[Mapping[str, Any]]
    after_death: list[Mapping[str, Any]]
    unsupported: list[Mapping[str, Any]]
    slips: list[Mapping[str, Any]]
    slip_payers: set[str]
    duplicate_slip: tuple[str, ...]
    no_payer_slip: bool
    rows: list[Row]
    mixed: tuple[str, ...]


def _salary_slips(ctx: YearContext, pid: str) -> list[Mapping[str, Any]]:
    return [
        r
        for r in ctx.records("withholding_slip")
        if r["roles"]["recipient"] == pid and r["attributes"]["slip_type"] == "salary" and r["when"].get("tax_year") == ctx.year
    ]


def _payments_by_person(ctx: YearContext) -> dict[str, list[Mapping[str, Any]]]:
    """受給者 → その年分の支払（36−9 の日の年。役員の利益連動の賞与で決議等の日がないものは due_on の年で入力の不足として検出する）。"""
    out: dict[str, list[Mapping[str, Any]]] = {}
    for rec in ctx.records("salary_payment"):
        if _due(rec).year == ctx.year:
            out.setdefault(rec["roles"]["recipient"], []).append(rec)
    return out


def _statuses_by_payer(ctx: YearContext) -> dict[tuple[str, str], list[Mapping[str, Any]]]:
    out: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for rec in ctx.records("commuting_status"):
        out.setdefault((rec["roles"]["worker"], rec["attributes"]["counterparty"]), []).append(rec)
    return out


def _payer_of_slip(slip: Mapping[str, Any]) -> str | None:
    return slip["attributes"].get("counterparty")


def _slip_payers(slips: list[Mapping[str, Any]]) -> tuple[list[Mapping[str, Any]], set[str], tuple[str, ...], bool]:
    """有効な源泉徴収票（前の支払者を通算した票に含まれる票は除く）・票で覆われる支払者・同じ支払者の重複・支払者の名がない票の有無。"""
    included: set[str] = set()
    for s in slips:
        included.update(s["attributes"].get("includes_prior_payers", ()))
    effective: list[Mapping[str, Any]] = []
    seen: dict[str, str] = {}
    duplicates: list[str] = []
    no_payer = False
    # 前の支払者の分はほかの票の「支払金額」に含まれる（手引「支払金額」欄）。その支払者の票・明細は別に数えない
    covered: set[str] = set(included)
    for s in sorted(slips, key=lambda r: r["id"]):
        payer = _payer_of_slip(s)
        if payer is None:
            no_payer = True
            effective.append(s)
            continue
        others = set().union(*(set(t["attributes"].get("includes_prior_payers", ())) for t in slips if t is not s))
        if payer in others:
            continue  # ほかの票に通算された前の支払者の票（「支払金額」を二重に数えない）
        if payer in seen:
            duplicates += [seen[payer], s["id"]]
            continue
        seen[payer] = s["id"]
        effective.append(s)
        covered.add(payer)
    return effective, covered, tuple(sorted(set(duplicates))), no_payer


def _plan_person(ctx: YearContext, pid: str, recs: list[Mapping[str, Any]], statuses: Mapping[tuple[str, str], list[Mapping[str, Any]]], versions: tuple[Version, ...]) -> Plan:
    death = ctx.death_on(pid)
    recs = sorted(recs, key=lambda r: r["id"])
    included: list[Mapping[str, Any]] = []
    deaths: list[Mapping[str, Any]] = []
    after: list[Mapping[str, Any]] = []
    unsupported: list[Mapping[str, Any]] = []
    for r in recs:
        if due_date(r) is None:
            unsupported.append(r)
            continue
        status = _death_class(r, death)
        if status == "after":
            after.append(r)
        elif status == "open":
            deaths.append(r)
        else:
            included.append(r)
    slips = _salary_slips(ctx, pid)
    effective, covered, dup, no_payer = _slip_payers(slips)
    rows: list[Row] = []
    mixed: list[str] = []
    for r in included + deaths:
        payer = r["attributes"]["counterparty"]
        if payer in covered:
            continue
        row = _row(ctx, pid, r, payer, statuses.get((pid, payer), ()), versions, mixed)
        if row is not None:
            rows.append(row)
    return Plan(pid, included, deaths, after, unsupported, effective, covered, dup, no_payer and bool(included + deaths), rows, tuple(sorted(set(mixed))))


def _death_class(rec: Mapping[str, Any], death: _dt.date | None) -> str:
    """支給期と死亡の関係：before（死亡の前。所得税に入れる）・after（死亡の後。所得税に入れない）・open（判断の分かれ目）。"""
    if death is None:
        return "before"
    due = _due(rec)
    stipulated = rec["attributes"].get("due_stipulated", True) or rec["attributes"].get("payment_type") == OFFICER_BONUS
    if due < death:
        return "before"
    if due == death or not stipulated:  # 同じ日の扱い・定めのない給与の死亡後の支払は一次情報がない（UJ2・HJ4）
        return "open"
    return "after"


def _row(
    ctx: YearContext,
    pid: str,
    rec: Mapping[str, Any],
    payer: str,
    statuses: Iterable[Mapping[str, Any]],
    versions: tuple[Version, ...],
    mixed: list[str],
) -> Row | None:
    amounts = rec["amounts"]
    allowance = amounts.get("commuting_allowance", 0) + amounts.get("commuting_pass_value", 0)
    if allowance == 0 or rec["attributes"].get("commuting_itemized") is False:
        return None
    table_on = _table_on(rec)
    ym = _ym(table_on)
    version = version_for(versions, max(table_on, _dt.date(2025, 1, 1)))
    covering = tuple(s for s in statuses if _period_overlaps_month(s["when"], ym))
    fare_key = f"{pid}|{payer}|{ym[0]:04d}-{ym[1]:02d}"
    if _mixed(covering):
        mixed += [s["id"] for s in covering]
    disabled = _disabled_in(ctx, pid, ym)
    special, special_recs = _judged_special(ctx, pid, payer, ym) if disabled else (None, [])
    base = _limit_for(covering, None, version, disabled, special)
    limit = base
    if base.needs_fare:
        fare = _judged_fare(ctx, pid, payer, ym)
        if fare is not None:
            limit = _limit_for(covering, fare, version, disabled, special)
    stated = amounts.get("commuting_nontaxable_stated")
    needs = base.needs_fare and stated is None
    return Row(
        record=rec,
        payer=payer,
        limit=limit,
        stated=stated,
        fare_key=fare_key if needs else None,
        status_ids=tuple(s["id"] for s in [*covering, *special_recs]),
        status_states=frozenset(st for s in [*covering, *special_recs] for st in _states_of(s)),
        version=version,
        covering=covering,
        disabled=disabled,
        special=special,
    )


def _mixed(covering: Iterable[Mapping[str, Any]]) -> bool:
    return len({s["attributes"]["means"] for s in covering}) > 1


def _disabled_in(ctx: YearContext, pid: str, ym: tuple[int, int]) -> bool:
    """その月に障害者の根拠（disability_basis）の期間が重なるか（質疑応答事例 03/18 の「障害者」。区分は問わない）。"""
    return any(r["roles"]["person"] == pid and _period_overlaps_month(r["when"], ym) for r in ctx.records("disability_basis"))


def _judged_special(ctx: YearContext, pid: str, payer: str, ym: tuple[int, int]) -> tuple[bool | None, list[Mapping[str, Any]]]:
    """その月の 判断.障害者の通勤の特別の事情 の値（1つに決まらなければ None：読みの両端で評価する）と、その判断の記録。"""
    hits = [j for j in ctx.judgments(K_SPECIAL) if _fare_matches(j, pid, payer, ym)]
    values = {bool(j["value"]) for j in hits}
    return (values.pop() if len(values) == 1 else None), hits


def _limit_for(
    covering: tuple[Mapping[str, Any], ...], fare: int | None, version: Version, disabled: bool = False, special: bool | None = None
) -> Limit:
    """1か月の限度額。月の中途の距離の変更は長い方の距離の金額で差し支えない（質疑応答事例 03/20）ので、候補の最大を使う。
    交通手段の違う状況が重なる月は、一次情報がないので候補の全部を両端にする（tsukin.mixed_limit）。"""
    if not covering:
        return monthly_limit(None, fare, version)
    limits = [monthly_limit(s["attributes"], fare, version, disabled=disabled, special=special) for s in covering]
    if _mixed(covering):
        return mixed_limit(limits)
    return max(limits, key=lambda x: (x.high, x.low))


def _judged_fare(ctx: YearContext, pid: str, payer: str, ym: tuple[int, int]) -> int | None:
    """その月の合理的な運賃の判断が1つの値に決まっていればその額（食い違う判断なら None：判断の分かれ目になる）。"""
    values = {j["value"]["monthly_amount"] for j in ctx.judgments(K_FARE) if _fare_matches(j, pid, payer, ym)}
    return values.pop() if len(values) == 1 else None


def _fare_matches(j: Mapping[str, Any], pid: str, payer: str, ym: tuple[int, int]) -> bool:
    s = j["subject"]
    return s["person"] == pid and s["counterparty"] == payer and _period_overlaps_month(j["when"], ym)


def _versions(ctx: YearContext, payments: Mapping[str, list[Mapping[str, Any]]]) -> tuple[Version, ...]:
    """通勤手当のある支払があるときだけパラメータを読む（給与だけの人が多い評価の時間を増やさない）。"""
    if any(r["amounts"].get("commuting_allowance") or r["amounts"].get("commuting_pass_value") for rs in payments.values() for r in rs):
        return versions_from_parameters(ctx.parameters)
    return ()


def _plans(ctx: YearContext) -> dict[str, Plan]:
    payments = _payments_by_person(ctx)
    statuses = _statuses_by_payer(ctx)
    versions = _versions(ctx, payments)
    return {pid: _plan_person(ctx, pid, payments.get(pid, []), statuses, versions) for pid in ctx.persons}


# ---------------------------------------------------------------------------
# 判断の分かれ目の宣言
# ---------------------------------------------------------------------------


def _fare_of(ctx: YearContext, row: Row) -> tuple[Limit, str | None]:
    """判断の分かれ目を読んで1か月の限度額を決める（読まなければ row.limit）。open の判断なら候補の端（low・high）を返す。"""
    if row.fare_key is None:
        return row.limit, None
    d = ctx.decision(K_FARE, row.fare_key)
    if isinstance(d.value, Mapping):  # 入力された判断（食い違う判断の候補を含む）
        return _limit_for(row.covering, d.value["monthly_amount"], row.version, row.disabled, row.special), None
    return row.limit, d.value


def _fare_slots(ctx: YearContext) -> Iterable[DecisionSlot]:
    judgments = ctx.judgments(K_FARE)
    for pid, plan in _plans(ctx).items():
        seen: set[str] = set()
        for row in plan.rows:
            if row.fare_key is None or row.fare_key in seen:
                continue
            seen.add(row.fare_key)
            payer = row.payer
            y, m = _ym(_table_on(row.record))
            ym = f"{y:04d}-{m:02d}"

            def matches(j: Mapping[str, Any], *, _pid: str = pid, _payer: str = payer, _cell: tuple[int, int] = (y, m)) -> bool:
                return _fare_matches(j, _pid, _payer, _cell)

            hits = [j for j in judgments if matches(j)]
            conflicting = len({json.dumps(j["value"], sort_keys=True) for j in hits}) > 1
            yield DecisionSlot(
                key=row.fare_key,
                target={"person": pid, "counterparty": payer, "month": ym, "input": "commuting_status または 判断.通勤の合理的な運賃"},
                matches=matches,
                candidates=BOUND_CANDIDATES,
                year_filter=False,  # 差額の追給の元の月は前の年のことがある（matches が月で絞る）
                persons=(pid,),
                monotone=None if conflicting else f"通勤手当の非課税:{pid}",
            )


def _has_reading_gap(plan: Plan) -> bool:
    """読みの分かれるところ（UT1・UT2・UT3）で非課税の額が変わりうるか（限度額の両端のどちらで見ても）。"""
    rows = [r for r in plan.rows if not r.uses_stated]
    if not rows:
        return False
    if any(r.limit.split and r.limit.low != r.limit.high for r in rows):
        return True  # 交通手段の違う状況が重なる月・障害者の 2km 未満（候補の両端。合理的な運賃が入力されていても残る）
    low = nontaxable_bounds(r.item(r.limit.low) for r in rows)
    high = nontaxable_bounds(r.item(r.limit.high) for r in rows)
    return low[0] != low[1] or high[0] != high[1]


def _reading_slots(ctx: YearContext) -> Iterable[DecisionSlot]:
    for pid, plan in _plans(ctx).items():
        if _has_reading_gap(plan):

            def matches(j: Mapping[str, Any], *, _pid: str = pid) -> bool:
                return j["subject"]["person"] == _pid

            yield DecisionSlot(
                key=pid,
                target={
                    "person": pid,
                    "open_readings": "通勤手当の限度額の当て方（1か月を超える期間・2以上の支払者・支給の月・同じ月に交通手段の違う状況・障害者の2km未満の自動車通勤）",
                },
                matches=matches,
                candidates=BOUND_CANDIDATES,
                persons=(pid,),
                monotone=f"通勤手当の非課税:{pid}",
            )


def _death_slots(ctx: YearContext) -> Iterable[DecisionSlot]:
    for pid, plan in _plans(ctx).items():
        for rec in plan.deaths:

            def matches(j: Mapping[str, Any], *, _rid: str = rec["id"]) -> bool:
                return j["subject"]["record_id"] == _rid

            yield DecisionSlot(
                key=rec["id"],
                target={"person": pid, "record_id": rec["id"], "due_on": rec["attributes"]["due_on"]},
                matches=matches,
                year_filter=False,
                persons=(pid,),
            )


def _tokutei_records(ctx: YearContext, pid: str) -> list[Mapping[str, Any]]:
    """その人のその年分の特定支出の候補の支出（specific_expense。年分は attributed_year、無ければ支出の日の年）。KY-11、2026-11-12。"""
    return [r for r in ctx.records("specific_expense") if r["roles"]["payer"] == pid and expense_year(r) == ctx.year]


def _tokutei_slots(ctx: YearContext) -> Iterable[DecisionSlot]:
    """選択.特定支出控除（所法57の2③：申告書等の記載と明細書・証明書の添付）の1か所。特定支出の額の合計額が正の人だけが読む（lazy）。"""
    if not ctx.records("specific_expense"):
        return
    for pid in ctx.persons:
        if not _tokutei_records(ctx, pid):
            continue

        def matches(c: Mapping[str, Any], *, _pid: str = pid) -> bool:
            return c["subject"]["person"] == _pid

        yield DecisionSlot(
            key=pid,
            target={
                "person": pid,
                "tax_year": ctx.year,
                "決めるもの": "その年分の申告書等で特定支出控除の適用を受けるか（選択.特定支出控除。所得税法第57条の2第3項）",
            },
            matches=matches,
            persons=(pid,),
            lazy=True,
        )


#: 判断.特定支出の通常の範囲の額 の未入力の両端（単調な判断の群。D21 R6）：除く部分を0とする端（支出金額の全部）と、全部とする端（0）。
ROUTE_FULL = "full"
ROUTE_NONE = "none"
ROUTE_CANDIDATES = (
    Candidate(ROUTE_FULL, "通常の範囲を支出金額の全部とする端（特定支出の額を大きく取る）"),
    Candidate(ROUTE_NONE, "通常の範囲を0とする端（特定支出の額を小さく取る）"),
)


def _route_slots(ctx: YearContext) -> Iterable[DecisionSlot]:
    """判断.特定支出の通常の範囲の額（KY-13、2026-11-12 の2回目）の1か所：旅費・帰宅旅費・転居の運賃と宿泊費の支出ごと。
    特定支出の額は各支出の通常の範囲の額について単調に増え、給与所得の金額はそれについて単調に減るので、人ごとの単調な判断の群にする。"""
    judgments = ctx.judgments(J_ROUTE)
    for pid in ctx.persons:
        for rec in _tokutei_records(ctx, pid):
            if not needs_route_judgment(rec):
                continue

            def matches(j: Mapping[str, Any], *, _rid: str = rec["id"]) -> bool:
                return j["subject"]["record_id"] == _rid

            hits = [j for j in judgments if matches(j)]
            conflicting = len({json.dumps(j["value"], sort_keys=True) for j in hits}) > 1
            yield DecisionSlot(
                key=rec["id"],
                target={
                    "person": pid,
                    "record_id": rec["id"],
                    "決めるもの": "支出のうち通常の経路・方法による部分・通常必要な運賃・著しく超えない宿泊費の額（判断.特定支出の通常の範囲の額）",
                },
                matches=matches,
                candidates=ROUTE_CANDIDATES,
                year_filter=False,
                persons=(pid,),
                monotone=None if conflicting else f"特定支出の通常の範囲:{pid}",
            )


def _route_caps(ctx: YearContext, recs: Iterable[Mapping[str, Any]]) -> tuple[dict[str, int | None], list[str], set[State]]:
    """記録の ID → 通常の範囲の額（判断。未入力の端は全部〔None〕か0）、使った判断の ID、状態。"""
    caps: dict[str, int | None] = {}
    ids: list[str] = []
    states: set[State] = set()
    for rec in recs:
        if not needs_route_judgment(rec):
            continue
        d = ctx.decision(J_ROUTE, rec["id"])
        ids.extend(d.record_ids)
        states.update(d.states)
        if isinstance(d.value, Mapping):
            caps[rec["id"]] = int(d.value["countable_amount"])
        else:
            caps[rec["id"]] = 0 if d.value == ROUTE_NONE else None
    return caps, ids, states


def _tokutei_inputs(ctx: YearContext, out: ModuleInputs) -> None:
    """特定支出の額の合計額と、特定支出控除の適用を受けるか（KY-11）。記録のない人は 0・偽。"""
    any_records = bool(ctx.records("specific_expense"))
    p = ctx.parameters.所得税.特定支出 if any_records else None
    for pid in ctx.persons:
        recs = _tokutei_records(ctx, pid) if any_records else []
        if not recs:
            out.set(V_TOTAL, pid, 0)
            out.set(V_APPLY, pid, False)
            _set_form_rows(out, pid, None)
            continue
        caps, judged_ids, judged_states = _route_caps(ctx, recs)
        c = collect(recs, books_cap=int(p.勤務必要経費の上限), sleeper_cap=int(p.寝台料金の除外の上限), caps=caps)
        for reason in c.problems:
            out.exclude(pid, reason, V_TOTAL)
            for v in (*(x for row in V_FORM_ROWS for x in row), V_FORM_WORK, V_FORM_CODES):
                out.exclude(pid, reason, v)
        total = 0 if c.problems else c.total
        basis = [TOTAL_RULE, ROUTE_RULE] if caps else [TOTAL_RULE]
        ids, states = c.ids + judged_ids, _states_of_all(recs, c.ids) | judged_states
        out.set(V_TOTAL, pid, total, ids, states, basis=basis)
        _set_form_rows(out, pid, None if c.problems else c, ids, states, basis)
        if total > 0:
            d = ctx.decision(C_TOKUTEI, pid)
            out.set(V_APPLY, pid, bool(d.value), d.record_ids, d.states, basis=[TOKUTEI_RULE] if d.value else [])
        else:
            out.set(V_APPLY, pid, False)


def _set_form_rows(out: ModuleInputs, pid: str, c: Any, ids: Any = (), states: Any = frozenset(), basis: Any = ()) -> None:
    """明細書（KOB070）の区分の行の Ⓐ・Ⓑ・Ⓒ、⑩ 小計、⑫ 区分の合計（2026-11-12 の3回目）。c が None なら0（記録がない・入力の不足）。"""
    if c is None:
        for v in (*(x for row in V_FORM_ROWS for x in row), V_FORM_WORK):
            out.set(v, pid, 0)
        out.set(V_FORM_CODES, pid, "0")
        return
    for names, values in zip(V_FORM_ROWS, form_rows(c)):
        for v, x in zip(names, values):
            out.set(v, pid, x, ids, states, basis=basis)
    out.set(V_FORM_WORK, pid, c.work, ids, states, basis=basis)
    out.set(V_FORM_CODES, pid, str(category_code_sum(c)), ids, states, basis=basis)


DECISIONS: tuple[DecisionSpec, ...] = (
    DecisionSpec(K_FARE, _fare_slots),
    DecisionSpec(C_TOKUTEI, _tokutei_slots),
    DecisionSpec(J_ROUTE, _route_slots),
    DecisionSpec(K_READING, _reading_slots),
    DecisionSpec(K_DEATH, _death_slots),
    # 判断.障害者の通勤の特別の事情：分かれ目の1か所を置かず、行ごとに判断を直接読む（未入力・食い違いは 判断.通勤手当の限度の当て方 の両端）。
    # 種類を「使う判断」として登録するための宣言
    DecisionSpec(K_SPECIAL, lambda ctx: ()),
)


# ---------------------------------------------------------------------------
# 入力の組み立て
# ---------------------------------------------------------------------------


@dataclass
class _Build:
    total: int = 0
    ids: set[str] = field(default_factory=set)
    states: set[State] = field(default_factory=set)
    basis: list[BasisEntry] = field(default_factory=list)


def _reading_pick(ctx: YearContext, plan: Plan) -> tuple[str | None, list[str], set[State]]:
    """読みの分かれ目の値：low か high（宣言の時点で分かれ目がなければ None）。"""
    if not _has_reading_gap(plan):
        return None, [], set()
    d = ctx.decision(K_READING, plan.pid)
    return d.value, list(d.record_ids), set(d.states)


def _commuting_nontaxable(ctx: YearContext, plan: Plan, rows: list[Row], b: _Build) -> int:
    """明細で計算する支払者の支払 rows について、非課税の通勤手当の額。plan は年分の宣言を決めた材料（読みの分かれ目の有無に使う）。"""
    if not rows:
        return 0
    items: list[Item] = []
    stated_total = 0
    used_stated = False
    param_names: set[tuple[str, str]] = set()
    pick, ids, states = _reading_pick(ctx, plan)
    b.ids.update(ids)
    b.states.update(states)
    for row in rows:
        b.ids.update(row.status_ids)
        b.states.update(row.status_states)
        if row.uses_stated:
            assert row.stated is not None
            stated_total += min(row.stated, row.allowance)
            used_stated = True
            continue
        limit, side = _fare_of(ctx, row)
        if row.fare_key is not None:
            d = ctx.decision(K_FARE, row.fare_key)
            b.ids.update(d.record_ids)
            b.states.update(d.states)
        if side is None and limit.split:
            side = pick  # 交通手段の違う状況が重なる月・障害者の 2km 未満：読みの分かれ目の端（合理的な運賃が入力されているときも）
        chosen = limit.high if side == HIGH else limit.low
        items.append(row.item(chosen))
        day = f"{ctx.year}-01-01"
        for n in row.version.parameter_names(row=limit.used_row):
            param_names.add((n, day))
    low, high = nontaxable_bounds(items)
    nontax = high if pick == HIGH else low
    b.basis.append(COMMUTING_RULE)
    if any(_mixed(r.covering) for r in rows if not r.uses_stated):
        b.basis.append(MIXED_MEANS_RULE)
    if any(r.disabled and r.limit.split and not _mixed(r.covering) for r in rows if not r.uses_stated):
        b.basis.append(DISABLED_SHORT_RULE)
    if any(r.disabled and r.special is not None for r in rows if not r.uses_stated):
        b.basis.append(DISABLED_SPECIAL_RULE)
    if used_stated:
        b.basis.append(STATED_NONTAXABLE_RULE)
    for n, day in sorted(param_names):
        b.basis.append(ctx.parameter_basis(n, on=day))
    return stated_total + nontax


def _detail_range(rows_by_slip: list[Row], payments: list[Mapping[str, Any]]) -> tuple[int, int]:
    """明細から求めた額の範囲（最小・最大。入力の足りないところは両端で見る）。"""
    gross = sum(r["amounts"]["gross"] + r["amounts"].get("commuting_pass_value", 0) for r in payments)
    stated = sum(min(r.stated, r.allowance) for r in rows_by_slip if r.uses_stated and r.stated is not None)
    rows = [r for r in rows_by_slip if not r.uses_stated]
    low = nontaxable_bounds(r.item(r.limit.low) for r in rows)
    high = nontaxable_bounds(r.item(r.limit.high) for r in rows)
    return gross - (stated + high[1]), gross - (stated + low[0])


def _warning(slip: Mapping[str, Any], names: list[str], low: int, high: int) -> BasisEntry:
    return BasisEntry(
        type=BasisType.RULE,
        name="警告：源泉徴収票の支払金額と給与の明細の額が食い違う（源泉徴収票の値を使った）",
        source_kind=SourceKind.NTA_EXPLANATION,
        law="HANDOFF D23 K4（明細の値は食い違いの検出に使う）",
        references=(f"{JIKI}#3",),
        detail={
            "warning": True,
            "slip_id": slip["id"],
            "counterparty": names,
            "payment_amount": slip["amounts"]["payment_amount"],
            "details_low": low,
            "details_high": high,
        },
    )


def _slip_rows(
    ctx: YearContext,
    plan: Plan,
    statuses: Mapping[tuple[str, str], list[Mapping[str, Any]]],
    versions: tuple[Version, ...],
    payers: set[str],
    included: list[Mapping[str, Any]],
) -> tuple[list[Mapping[str, Any]], list[Row]]:
    """源泉徴収票で覆われた支払者の明細（食い違いの検出用）。死亡後の支払などは含めない。"""
    recs = [r for r in included if r["attributes"]["counterparty"] in payers]
    rows: list[Row] = []
    mixed: list[str] = []
    for r in recs:
        payer = r["attributes"]["counterparty"]
        row = _row(ctx, plan.pid, r, payer, statuses.get((plan.pid, payer), ()), versions, mixed)
        if row is not None:
            rows.append(row)
    return recs, rows


def build_inputs(ctx: YearContext) -> ModuleInputs:
    out = ModuleInputs()
    plans = _plans(ctx)
    statuses = _statuses_by_payer(ctx)
    versions = _versions(ctx, _payments_by_person(ctx))
    for pid, plan in plans.items():
        b = _Build()
        out_of_scope: list[OutOfScopeReason] = []
        if plan.unsupported:
            out_of_scope.append(OutOfScopeReason(OutOfScopeCategory.NOT_IMPLEMENTED, UNSUPPORTED_PAYMENT_REASON, tuple(r["id"] for r in plan.unsupported)))
        if plan.no_payer_slip:
            out_of_scope.append(OutOfScopeReason(OutOfScopeCategory.NOT_IMPLEMENTED, SLIP_NO_PAYER_REASON, tuple(s["id"] for s in plan.slips)))
        if plan.duplicate_slip:
            out_of_scope.append(OutOfScopeReason(OutOfScopeCategory.NOT_IMPLEMENTED, DUPLICATE_SLIP_REASON, plan.duplicate_slip))
        # 死亡の分かれ目を読んで、明細に入れる支払を決める
        included = list(plan.payments)
        for rec in plan.deaths:
            d = ctx.decision(K_DEATH, rec["id"])
            b.ids.update(d.record_ids)
            b.states.update(d.states)
            if d.value:
                included.append(rec)
        if plan.after_death:
            b.basis.append(AFTER_DEATH_RULE)
        if any(r["attributes"].get("payment_type") == "deemed_bonus" for r in included):
            b.basis.append(DEEMED_BONUS_RULE)
        if any(r["attributes"].get("payment_type") == OFFICER_BONUS for r in included):
            b.basis.append(OFFICER_BONUS_RULE)
        # 源泉徴収票の値を優先する（D23 K4）
        for slip in plan.slips:
            amount = slip["amounts"]["payment_amount"]
            b.total += amount
            b.ids.add(slip["id"])
            b.states.update(_states_of(slip))
            b.basis.append(SLIP_PRIORITY_RULE)
        for slip in plan.slips:
            covers = {_payer_of_slip(slip)} | set(slip["attributes"].get("includes_prior_payers", ()))
            covers.discard(None)
            recs, rows = _slip_rows(ctx, plan, statuses, versions, covers, included) if covers else ([], [])
            if not recs:
                continue
            low, high = _detail_range(rows, recs)
            amount = slip["amounts"]["payment_amount"]
            if not (low <= amount <= high):
                b.basis.append(_warning(slip, sorted(covers), low, high))
                b.ids.update(r["id"] for r in recs)
        # 票のない支払者は明細で計算する
        rest = [r for r in included if r["attributes"]["counterparty"] not in plan.slip_payers]
        b.total += sum(r["amounts"]["gross"] + r["amounts"].get("commuting_pass_value", 0) for r in rest)
        rest_ids = {r["id"] for r in rest}
        b.total -= _commuting_nontaxable(ctx, plan, [row for row in plan.rows if row.record["id"] in rest_ids], b)
        if any(r["attributes"].get("commuting_itemized") is False and r["amounts"].get("commuting_allowance") for r in rest):
            b.basis.append(ITEMIZED_RULE)
        b.ids.update(rest_ids)
        for r in rest:
            b.states.update(_states_of(r))
        # 事業専従者控除額のみなし給与（所法57④）：段階評価で income_kinds の値を読む（最初の段では pending の 0）
        deemed = ctx.stage_value(STAGE_DEEMED, V_DEEMED, pid)
        uses: tuple = ()
        if not deemed.pending and (deemed.value or deemed.reasons or deemed.states):
            uses = (deemed,)
            if deemed.value:
                b.total += int(deemed.value)
                b.basis.append(DEEMED_RULE)
        # 生計を一にする親族の事業から受けた給与のうち所法56 でないものとみなす額：段階評価で income_kinds の値を読んで引く（2026-11-12）
        family_out = ctx.stage_value(STAGE_DEEMED, V_FAMILY_OUT, pid)
        if not family_out.pending and (family_out.value or family_out.reasons or family_out.states):
            uses = (*uses, family_out)
            if family_out.value:
                b.total -= min(int(family_out.value), b.total)
                b.basis.append(FAMILY_OUT_RULE)
        # 判断.退職の性質 で退職手当等に当たらず給与とした支払（IK-25。income_kinds が年分〔支払の日〕と額を決める：2026-11-12）
        retire_salary = ctx.stage_value(STAGE_DEEMED, V_RETIRE_SALARY, pid)
        if not retire_salary.pending and (retire_salary.value or retire_salary.reasons or retire_salary.states or retire_salary.missing):
            uses = (*uses, retire_salary)
            if retire_salary.value:
                b.total += int(retire_salary.value)
                b.basis.append(RETIRE_SALARY_RULE)
        # 未払のまま回収することができないこととなった給与（所法64①・所令180②。KY-08）：給与等の収入金額は変えず、回収不能額等を別の入力にする。
        # なかったものとみなす額（令180②一・二の低い方）は 所得税_給与所得 の式と段 未払の給与の回収不能（uncollectible.py）が当てる（2026-11-12）
        bad = _uncollectible(ctx, pid, included)
        if bad.reason is not None:
            out.exclude(pid, bad.reason, V_UNCOLLECTIBLE)
        out.set(V_UNCOLLECTIBLE, pid, 0 if bad.reason is not None else bad.amount, bad.ids, _states_of_all(included, bad.ids),
                basis=[UNCOLLECTIBLE_RULE] if bad.amount or bad.reason is not None else [])
        if b.total < 0:
            raise ValueError(f"給与等の収入金額が負になった: {pid}")
        if b.total > INT32_MAX:
            out_of_scope.append(
                OutOfScopeReason(
                    OutOfScopeCategory.NOT_IMPLEMENTED,
                    f"給与等の収入金額の合計が判定コアの整数の範囲（{INT32_MAX:,}円）を超える",
                    tuple(sorted(b.ids)),
                )
            )
        for reason in out_of_scope:
            out.exclude(pid, reason, V_INCOME)
        value = 0 if out_of_scope else b.total
        out.set(V_INCOME, pid, value, sorted(b.ids), b.states, basis=_dedupe(b.basis), uses=uses)
    _tokutei_inputs(ctx, out)  # 特定支出控除（所法57の2。KY-11、2026-11-12）
    return out


@dataclass(frozen=True)
class _Uncollectible:
    amount: int = 0
    ids: tuple[str, ...] = ()
    reason: OutOfScopeReason | None = None


def _uncollectible(ctx: YearContext, pid: str, included: list[Mapping[str, Any]]) -> _Uncollectible:
    """未払の給与のうち回収することができないこととなった金額（amounts.uncollectible_amount。所法64①の回収不能額等）。

    令180②：なかったものとみなすのは、回収不能額等のうち、一 回収不能額等が生じた時の直前に確定している総所得金額・退職所得金額・山林所得金額の合計額、
    二 給与所得の金額から回収不能額等がなかったものとした給与所得の金額を控除した残額 のいずれか低い金額まで。一号は income_totals の
    所得税_回収不能額等の前の総所得金額と退職所得金額の合計額（段 未払の給与の回収不能 が読む）、二号は 所得税_回収不能額等に係る給与所得の金額の差額。
    ここでは回収不能額等の額だけを入力にする。未払でない支払に回収不能額を書いた記録・総支給額を超える回収不能額は入力の矛盾（c-入力）。
    """
    recs = [r for r in included if "uncollectible_amount" in r["amounts"]]
    if not recs:
        return _Uncollectible()
    ids = tuple(sorted(r["id"] for r in recs))
    bad = [r["id"] for r in recs if not r["attributes"].get("unpaid") or r["amounts"]["uncollectible_amount"] > r["amounts"]["gross"]]
    if bad:
        return _Uncollectible(ids=ids, reason=OutOfScopeReason(OutOfScopeCategory.NOT_IMPLEMENTED, UNCOLLECTIBLE_INPUT_REASON, tuple(sorted(bad))))
    return _Uncollectible(sum(r["amounts"]["uncollectible_amount"] for r in recs), ids)


def _states_of_all(recs: Iterable[Mapping[str, Any]], ids: Iterable[str]) -> set[State]:
    wanted = set(ids)
    return {s for r in recs if r["id"] in wanted for s in _states_of(r)}


def _dedupe(entries: list[BasisEntry]) -> tuple[BasisEntry, ...]:
    seen: set[tuple[str, str | None, str | None]] = set()
    out: list[BasisEntry] = []
    for e in entries:
        key = (e.name, e.instant, json.dumps(e.detail, ensure_ascii=False, sort_keys=True) if e.detail else None)
        if key not in seen:
            seen.add(key)
            out.append(e)
    return tuple(out)
