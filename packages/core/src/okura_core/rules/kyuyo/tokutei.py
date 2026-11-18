"""給与所得者の特定支出の控除の特例（所得税法第57条の2。README KY-11、2026-11-12）：特定支出の額の合計額の組み立てと、給与所得の金額の純粋関数。

根拠：docs/public-sources/20261112_impl-research8_tokutei-shishutsu-laws.md（［PS8］）、仮説 docs/hypotheses/20261112_impl-research8_tokutei-shishutsu-reading.md（H1〜H7）。

- 特定支出の額の合計額（所法57の2②、所令167の3、所規36の5）：記録 specific_expense のうち、その年分（attributed_year、無ければ支出の日の年）・その人の支出から、
  証明のないもの・キャリアコンサルタントの証明で研修費・資格取得費でないもの・教育訓練に係る部分でないもの・通勤の航空機の利用を除き、
  特別車両料金等（客室の特別の設備の料金と 6,600円を超える寝台料金）を運賃から除き、交通機関の通勤費は定期乗車券等の価額の合計で抑え、
  転居費は転任の日以後1年以内の支出だけを数え、区分ごとに補塡される部分（非課税）と教育訓練給付金等の部分を引き（明細書のⒶ−Ⓑ＝Ⓒ）、
  勤務必要経費（図書・衣服・交際費等）の合計を 65万円で抑える。
  2026-11-12 の2回目（KY-13）：記録の amount は実際の支出金額。旅費・帰宅旅費の通常の経路・方法による部分、転居の運賃・宿泊費の通常の範囲の額は
  判断.特定支出の通常の範囲の額（caps）で抑える（未入力なら支出金額の全部と0の両端：inputs.py の単調な判断の群）。
- 給与所得の金額（所法57の2①、措法29の4③）：特定支出の額の合計額が給与所得控除額（第28条第3項。令和8・9年は措法29の4①）の2分の1を超えるときだけ、
  第28条第2項の残額（措法29の4② が当たれば同項の給与所得の金額）からその超える部分を控除する。別表第五（第28条第4項）は使わない。
  1円未満は根拠がないので候補で評価する（RoundingSlotSpec）。負になれば 0（H3：法令の読み）。
- 適用を受けるか（所法57の2③：申告書等の記載と明細書・証明書の添付）は 選択.特定支出控除。未入力なら両方で評価する（H4）。
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

from ...basis import BasisEntry, BasisType, ReadingFlag, SourceKind
from ...result import OutOfScopeCategory, OutOfScopeReason
from .calc import DeductionRules, KyuyoPath, KyuyoRules, kyuyo_deduction, kyuyo_shotoku

PS8 = "docs/public-sources/20261112_impl-research8_tokutei-shishutsu-laws.md"

C_TOKUTEI = "選択.特定支出控除"
V_TOTAL = "所得税_特定支出の額の合計額"
V_APPLY = "所得税_特定支出控除の適用を受けるか"
V_ROUNDING = "所得税_特定支出控除の後の給与所得の端数の候補"
ROUNDING = "特定支出控除の後の給与所得の金額の1円未満"
P_BOOKS_CAP = "所得税.特定支出.勤務必要経費の上限"
P_SLEEPER = "所得税.特定支出.寝台料金の除外の上限"

TRANSIT = "commuting_transit"
VEHICLE = "commuting_vehicle"
TRAVEL = "business_travel"
RELOCATION = "relocation"
TRAINING = "training"
QUALIFICATION = "qualification"
HOME_LEAVE = "home_leave"
WORK_NEEDS = ("books", "clothing", "entertainment")  # 第2項第7号（勤務必要経費）
#: 運賃・料金から特別車両料金等を除く区分（所令167の3①一・②一・③一・⑤一、所規36の5③④）
FARE_CATEGORIES = frozenset({TRANSIT, TRAVEL, RELOCATION, HOME_LEAVE})
#: キャリアコンサルタントの証明で特定支出になる区分（第2項第4号・第5号）
CONSULTANT_CATEGORIES = frozenset({TRAINING, QUALIFICATION})
#: 通常の経路・方法の判断が要る区分（所令167の3②・⑤。KY-13、2026-11-12 の2回目）と、判断の要らない転居費の支出の別（同③二・四）
ROUTE_CATEGORIES = frozenset({TRAVEL, HOME_LEAVE})
RELOCATION_ITEMS_WITHOUT_JUDGMENT = frozenset({"vehicle", "moving"})
J_ROUTE = "判断.特定支出の通常の範囲の額"

CONSULTANT_REASON = (
    "入力の不足：キャリアコンサルタントの証明の研修費・資格取得費（certified_by: career_consultant）に、教育訓練に係る支出か"
    "（attributes.education_training）がない（所得税法第57条の2第2項第4号・第5号：教育訓練に係る部分に限る）"
)
PASS_REASON = (
    "入力の不足：交通機関の通勤費（category: commuting_transit）に、給与等の支払者が証明した経路・方法による1か月当たりの定期乗車券等の価額の合計"
    "（amounts.commuter_pass_value）がない（所得税法施行令第167条の3第1項第1号：運賃の合計額がその合計額を超えるときはその合計額）"
)
TRANSFER_REASON = (
    "入力の不足：転居費（category: relocation）に転任の事実が生じた日（attributes.transfer_on）がない"
    "（所得税法施行令第167条の3第3項：転任の事実が生じた日以後1年以内の支出に限る）"
)

TOTAL_RULE = BasisEntry(
    type=BasisType.RULE,
    name="特定支出の額の合計額：証明のある支出の政令の範囲の額から、補塡される部分（非課税）と教育訓練給付金等の部分を除き、勤務必要経費は65万円まで",
    source_kind=SourceKind.LAW,
    law=(
        "所得税法第57条の2第2項、同施行令第167条の3、同施行規則第36条の5第3項・第4項。区分ごとに支出金額（政令の範囲）から除く部分を引く順序は"
        "明細書の Ⓐ−Ⓑ＝Ⓒ（交通機関の通勤費はⒶを定期乗車券等の価額の合計で抑える。勤務必要経費の65万円は⑦〜⑨のⒸの合計に当てる）の読み"
    ),
    references=(f"{PS8}#1", f"{PS8}#2", f"{PS8}#3", f"{PS8}#7.2"),
    flags=(ReadingFlag.LEGAL_READING,),
)
ROUTE_RULE = BasisEntry(
    type=BasisType.RULE,
    name="旅費・帰宅旅費・転居費の運賃と宿泊費は、通常の経路・方法による部分・著しく超えない部分（人の判断）までを特定支出の額に数える",
    source_kind=SourceKind.CABINET_ORDER,
    law=(
        "所得税法施行令第167条の3第2項（最も経済的かつ合理的と認められる通常の経路及び方法によるもの）・第3項第1号（通常必要であると認められる運賃及び料金）・"
        "第3号（通常必要であると認められる額を著しく超える部分を除く）・第5項。その額は人の判断（判断.特定支出の通常の範囲の額。D4）。"
        "特別車両料金等を除いた額をその額で抑える（法令の読み）。判断がなければ支出金額の全部と0の両端で評価する（D21 R6）"
    ),
    references=(f"{PS8}#2",),
    flags=(ReadingFlag.LEGAL_READING,),
)
TOKUTEI_RULE = BasisEntry(
    type=BasisType.RULE,
    name="特定支出控除：特定支出の額の合計額が給与所得控除額の2分の1を超えるとき、第28条第2項の残額（措法29の4② の適用があれば同項の給与所得の金額）からその超える部分を控除",
    source_kind=SourceKind.LAW,
    law=(
        "所得税法第57条の2第1項・第3項（申告書等の記載と明細書・証明書の添付：選択.特定支出控除）、租税特別措置法第29条の4第3項（令和8年分・令和9年分）。"
        "第28条第4項（別表第五）にかかわらない。控除した金額が負になるときは0（所法69① の損益通算の対象でない：法令の読み）"
    ),
    references=(f"{PS8}#1", f"{PS8}#4", f"{PS8}#7.3"),
    flags=(ReadingFlag.LEGAL_READING,),
)


def expense_year(rec: Mapping[str, Any]) -> int:
    """その支出を特定支出の額に数える年分（attributed_year。無ければ支出の日の年）。"""
    y = rec["attributes"].get("attributed_year")
    return int(y) if y is not None else _dt.date.fromisoformat(rec["when"]["on"]).year


def _add_one_year(d: _dt.date) -> _dt.date:
    try:
        return d.replace(year=d.year + 1)
    except ValueError:  # 2月29日
        return d.replace(year=d.year + 1, day=28)


@dataclass
class Collected:
    """1人・1年分の特定支出の額の合計額と、使った記録・入力の不足。"""

    total: int = 0
    ids: list[str] = field(default_factory=list)
    problems: list[OutOfScopeReason] = field(default_factory=list)
    #: 区分（category）ごとの Ⓐ 支出金額（政令の範囲・上限の後）・Ⓑ 補塡される金額のうち非課税部分等・Ⓒ 差引金額（Ⓐ−Ⓑ、負なら0）。明細書の欄（2026-11-12 の3回目）
    gross: dict[str, int] = field(default_factory=dict)
    less: dict[str, int] = field(default_factory=dict)
    net: dict[str, int] = field(default_factory=dict)
    work: int = 0  # 勤務必要経費の小計（第2項第7号：65万円まで。明細書の ⑩）


#: 給与所得者の特定支出に関する明細書（KOB070）の区分の行：（行の名前, 区分〔category〕, 区分番号）。行の番号は明細書の帳票項番 1〜9、
#: 区分番号は明細書の【区分 n】（docs/public-sources/20261112_impl-research9_tokutei-jumin-sources.md §4.3・§5.2）。通勤費は交通機関と交通用具を合わせる。
FORM_ROWS: tuple[tuple[str, tuple[str, ...], int], ...] = (
    ("通勤費", (TRANSIT, VEHICLE), 1),
    ("職務上の旅費", (TRAVEL,), 256),
    ("転居費", (RELOCATION,), 2),
    ("研修費", (TRAINING,), 4),
    ("資格取得費", (QUALIFICATION,), 8),
    ("帰宅旅費", (HOME_LEAVE,), 16),
    ("図書費", ("books",), 32),
    ("衣服費", ("clothing",), 64),
    ("交際費等", ("entertainment",), 128),
)
#: 明細書の区分の行の列（Ⓐ・Ⓑ・Ⓒ）。
FORM_COLUMNS: tuple[str, ...] = ("支出金額", "補塡される金額のうち非課税部分等", "差引金額")
_PREFIX = "所得税"  # 変数名の接頭辞（行・列から作る名前の途中の文字列が変数名に見えないように分ける：tests/test_architecture.py の名前の実在の検査）


def form_row_variable(k: int, column: str) -> str:
    """明細書の区分の行 k（1〜9）の列の入力変数の名前。"""
    return f"{_PREFIX}_特定支出に関する明細書の行{k}_{column}"


def form_rows(c: Collected) -> list[tuple[int, int, int]]:
    """明細書の区分の行ごとの（Ⓐ, Ⓑ, Ⓒ）。Ⓒ は区分ごとの差引金額（負なら0）の和（通勤費は交通機関・交通用具の和）。"""
    return [
        (sum(c.gross.get(k, 0) for k in cats), sum(c.less.get(k, 0) for k in cats), sum(c.net.get(k, 0) for k in cats)) for _, cats, _ in FORM_ROWS
    ]


def category_code_sum(c: Collected) -> int:
    """明細書の ⑫「適用を受ける特定支出の区分の合計」：差引金額が正の区分の区分番号の和（仮説 impl-research9 H4。差引金額が0 の区分を数えない）。"""
    return sum(code for (_, _, net), (_, _, code) in zip(form_rows(c), FORM_ROWS) if net > 0)


def needs_route_judgment(rec: Mapping[str, Any]) -> bool:
    """判断.特定支出の通常の範囲の額 が要る支出か（KY-13）：職務上の旅費・帰宅旅費（所令167の3②⑤「最も経済的かつ合理的と認められる通常の経路及び方法」）と、
    転居費の運賃・宿泊費（同③一「通常必要であると認められる運賃及び料金」・三「通常必要であると認められる額を著しく超える部分を除く」。
    支出の別 relocation_item がなければ運賃か宿泊費の場合がある）。証明のない支出は特定支出でないので要らない。"""
    a = rec["attributes"]
    if a["certified_by"] == "none":
        return False
    if a["category"] in ROUTE_CATEGORIES:
        return True
    return a["category"] == RELOCATION and a.get("relocation_item") not in RELOCATION_ITEMS_WITHOUT_JUDGMENT


def collect(
    records: Iterable[Mapping[str, Any]], *, books_cap: int, sleeper_cap: int, caps: Mapping[str, int | None] | None = None
) -> Collected:
    """その人・その年分の specific_expense から特定支出の額の合計額を作る（所法57の2②・所令167の3・所規36の5）。

    caps：記録の ID → 政令の範囲に入る部分の額（判断.特定支出の通常の範囲の額。KY-13）。None なら支出金額の全部（判断の分かれ目の端）。
    特別車両料金等を除いた額をその額で抑える（法令の読み：通常の経路・方法による旅行の運賃でも特別車両料金等は除く）。"""
    caps = caps or {}
    out = Collected()
    gross: dict[str, int] = {}  # 区分 → 政令の範囲の支出金額（Ⓐ）
    less: dict[str, int] = {}  # 区分 → 除く部分（Ⓑ）
    passes = 0
    missing: dict[str, list[str]] = {}
    for rec in records:
        a, m = rec["attributes"], rec["amounts"]
        out.ids.append(rec["id"])
        cat, cert = a["category"], a["certified_by"]
        if cert == "none":
            continue  # 証明のない支出は特定支出でない（第2項各号）
        if cert == "career_consultant":
            if cat not in CONSULTANT_CATEGORIES:
                continue  # キャリアコンサルタントの証明は研修費・資格取得費だけ
            edu = a.get("education_training")
            if edu is None:
                missing.setdefault(CONSULTANT_REASON, []).append(rec["id"])
                continue
            if not edu:
                continue  # 教育訓練に係る部分に限る
        if cat in (TRANSIT, VEHICLE) and a.get("air_travel"):
            continue  # 通勤費は航空機の利用に係るものを除く（所令167の3①）
        if cat == RELOCATION:
            moved = a.get("transfer_on")
            if moved is None:
                missing.setdefault(TRANSFER_REASON, []).append(rec["id"])
                continue
            on = _dt.date.fromisoformat(rec["when"]["on"])
            start = _dt.date.fromisoformat(moved)
            if not (start <= on < _add_one_year(start)):
                continue  # 転任の事実が生じた日以後1年以内（初日を算入：法令の読み）
        amount = int(m["amount"])
        if cat in FARE_CATEGORIES:
            special = int(m.get("special_seat_fee", 0)) + sum(int(s) for s in a.get("sleeper_fees", ()) if int(s) > sleeper_cap)
            amount -= min(special, amount)
        cap = caps.get(rec["id"])
        if cap is not None:
            amount = min(amount, max(0, int(cap)))  # 通常の経路・方法による部分・著しく超えない部分（判断。KY-13）
        if cat == TRANSIT:
            if "commuter_pass_value" not in m:
                missing.setdefault(PASS_REASON, []).append(rec["id"])
                continue
            passes += int(m["commuter_pass_value"])
        gross[cat] = gross.get(cat, 0) + amount
        less[cat] = less.get(cat, 0) + int(m.get("reimbursed_nontaxable", 0)) + int(m.get("training_benefit", 0))
    for reason, ids in missing.items():
        out.problems.append(OutOfScopeReason(OutOfScopeCategory.NOT_IMPLEMENTED, reason, tuple(sorted(ids))))
    if TRANSIT in gross:
        gross[TRANSIT] = min(gross[TRANSIT], passes)  # 所令167の3①一
    net = {c: max(0, gross[c] - less.get(c, 0)) for c in gross}
    work = min(sum(net.get(c, 0) for c in WORK_NEEDS), books_cap)  # 第2項第7号
    out.total = sum(v for c, v in net.items() if c not in WORK_NEEDS) + work
    out.gross, out.less, out.net, out.work = dict(gross), {c: less.get(c, 0) for c in gross}, net, work
    return out


# ---------------------------------------------------------------------------
# 給与所得の金額（所法57の2①・措法29の4③）
# ---------------------------------------------------------------------------


def tokutei_raw(income: int, total: int, rules: KyuyoRules, drules: DeductionRules) -> Fraction | None:
    """特定支出控除を当てた給与所得の金額（1円未満の丸めと 0 の下限の前）。特定支出の額の合計額が給与所得控除額の2分の1以下なら None。"""
    if total <= 0:
        return None
    deduction = kyuyo_deduction(income, drules).amount
    half = deduction / 2
    if total <= half:
        return None
    d = kyuyo_shotoku(income, rules)
    base = Fraction(d.value) if d.path is KyuyoPath.SOCHI_29_4_2 else income - deduction  # 措法29の4③ の読替え／第28条第2項の残額
    return base - (total - half)


def needs_rounding(raw: Fraction | None) -> bool:
    return raw is not None and raw.denominator != 1


def finish(raw: Fraction, rounder: Callable[[Fraction], int]) -> int:
    """1円未満を候補で丸め、負なら 0（H3）。"""
    v = int(raw) if raw.denominator == 1 else rounder(raw)
    return max(0, v)


def shotoku(income: int, total: int, apply: bool, rules: KyuyoRules, drules: DeductionRules, rounder: Callable[[Fraction], int]) -> int:
    """給与所得の金額（所法64① を当てる前）：適用を受け、2分の1を超えれば第57条の2第1項、そうでなければ第28条・措法29の4②。"""
    if apply:
        raw = tokutei_raw(income, total, rules, drules)
        if raw is not None:
            return finish(raw, rounder)
    return kyuyo_shotoku(income, rules).value


__all__ = [
    "CONSULTANT_REASON",
    "C_TOKUTEI",
    "J_ROUTE",
    "PASS_REASON",
    "ROUNDING",
    "ROUTE_RULE",
    "TOKUTEI_RULE",
    "TOTAL_RULE",
    "TRANSFER_REASON",
    "V_APPLY",
    "V_ROUNDING",
    "V_TOTAL",
    "collect",
    "expense_year",
    "finish",
    "needs_rounding",
    "needs_route_judgment",
    "shotoku",
    "tokutei_raw",
]
