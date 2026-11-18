"""減価償却費（資産台帳 depreciable_asset から、人 × 年分の必要経費に算入する額を作る）。

規則（根拠は basis.py の DEPRECIATION・calc.DEPRECIATION_CEIL）：
- 少額（所令138）：取得価額が10万円未満か使用可能期間1年未満（判断.減価償却の区分）→ 業務の用に供した年分に全額。貸付け（主要な業務を除く）は除く。
- 一括（所令139）：20万円未満で選択.減価償却 の lump_sum_depreciation → 業務の用に供した年以後3年、1/3 ずつ（端数は根拠のない端数の候補）。
- 中小事業者の少額（措法28の2）：青色・事業所得又は不動産所得・取得価額の上限（取得の日で区分）未満で small_amount_special_rule → 業務の用に供した年分に全額。
  年間の取得価額の合計額の上限（300万円。開業・廃業の年は月割）を超えたら、どれに当てるかの判断が要るので対象外。
- 通常の償却（所法49①、所令120・120の2・125・132・134、耐用年数省令4〜6・別表第七〜第十一。表の値は parameters/所得税/減価償却.yaml の末尾）：
  - 方法：償却の方法の届出（bookkeeping_status の depreciation_method_notice）の記録がなければ法定償却方法（所令125：平成19年3月31日以前の取得は旧定額法、
    以後は定額法）。届出の記録があれば、届出は資産の区分（所令123①）を自由な文字列でしか書けないので、その資産の区分と取得の日で選べる方法の全部
    （旧定額法・旧定率法／定額法・定率法。無形〔ソフトウエア〕は旧定額法・定額法だけ：所令120①四・120の2①四）を候補にする（選択.減価償却 の
    depreciation_method。D21 R6。読んだときだけ開く）。区分の分からない資産（耐用年数だけの判断）は定率法を選べない区分（建物など）かもしれないが候補に含める（安全側）。
  - 定額法：取得価額×別表第八の償却率。累計は取得価額−1円（無形は取得価額）まで（所令134①二）。
  - 定率法：期首未償却残高×償却率（平成24年3月31日以前の取得は別表第九、以後は別表第十）。その額が償却保証額（取得価額×保証率）に満たない最初の年から
    改定取得価額（その年の期首未償却残高）×改定償却率（所令120の2①一イ(2)・②）。累計は取得価額−1円まで（134①二イ）。
  - 旧定額法：（取得価額−残存価額）×別表第七の旧定額法の償却率。残存価額は取得価額×別表第十一の残存割合（有形10%・無形0）。
    旧定率法：期首未償却残高×別表第七の旧定率法の償却率（所令120①一イ）。有形は累計を取得価額の95%まで（134①一イ）、前年までに達していれば
    （取得価額−95%相当額−1円）÷5 を毎年、累計が取得価額−1円まで（134②）。無形は取得価額まで（134①一ロ）。
  - 年の中途の供用・処分は月数/12（所令132。134③ で②の額にも準用）。1円未満は年ごとの償却費・95%相当額を切上げ（DEPRECIATION_CEIL：
    作成コーナーのよくある質問「減価償却費の計算で小数点以下の端数が生じた場合、切上げ処理」。例は95%相当額）。
  - 前年以前の各年分の償却費（累計）は、業務の用に供した年から今の表と方法で計算し直した値を使う（未償却残高の記録の語彙がない）。
- 家事兼用：判断.按分の割合（asset_business_share）の割合を掛ける。掛けた後の1円未満は根拠のない端数の候補（genka-hasu H2）。
  未償却残高は償却費の全額で減らす（案A：genka-model H4-2）。
- 処分：scrapping・loss・other は除却損（未償却残高−処分価額＋費用−保険金）を所法51①④ で必要経費に。sale は譲渡所得（後の段）で対象外。
  除却の年の償却費は計算する（省略しても所得の金額は変わらない：genka-model H6-3）。一括償却資産は処分しても 1/3 を続け、除却損は出さない（所基通49−40の2）。
- 割増償却・特別償却（2026-11-12。special_dep.py。IK-112）：外部で計算した額（special_depreciation）を受け取り、その年の普通償却費の後に累計へ足す
  （未償却残高・その後の年の基礎と累積の限度に効く）。必要経費は（普通償却費＋割増・特別償却の額）×事業専用割合。少額・一括・措法28の2・リース資産には当てない。
- 減価償却費の計算の行（2026-11-12。asset_rows.py）：その年分に償却費を計算した資産ごとに、様式の償却の列の値（AssetResult.rows）。
  depreciation_schedule は年ごとに償却の基礎・使った率（定率法で改定償却率に切り替えた年からは改定償却率）・月数を返す（YearDep）。
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, NamedTuple

from ...candidates import Candidate
from ...registry import DecisionSlot, YearContext
from ...result import Means, Split, State
from ...rounding import ceil_yen
from ...basis import BasisEntry
from . import assets_special as sp
from . import special_dep as sd
from .asset_rows import AssetRow, write_rows
from .common import calendar_months, date_of, first_year_months, undetermined

K_DEP_CHOICE = "選択.減価償却"
K_DEP_CLASS = "判断.減価償却の区分"

#: 根拠のない端数（按分の後・一括の3分の1など）の名前。
ROUNDING_EXPENSE = "必要経費の1円未満（按分・一括償却・事業専従者控除）"

#: 定額法を使う取得の日の下限（所令120の2①：平成19年4月1日以後に取得）。
STRAIGHT_LINE_FROM = _dt.date(2007, 4, 1)
#: 別表第九（250%）を使う取得の日の上限（耐用年数省令5①二：平成24年3月31日以前に取得）。以後は別表第十（200%）。
DB250_UNTIL = _dt.date(2012, 3, 31)

#: 償却の方法（選択.減価償却 の depreciation_method の値）。
M_SL = "straight_line"  # 定額法（所令120の2①一イ(1)）
M_DB = "declining_balance"  # 定率法（所令120の2①一イ(2)）
M_OSL = "old_straight_line"  # 旧定額法（所令120①一イ(1)）
M_ODB = "old_declining_balance"  # 旧定率法（所令120①一イ(2)）
#: 特別な方法（生産高比例法・旧生産高比例法・リース期間定額法など：assets_special.py。IK-103）のラベルも持つ
METHOD_LABELS = {M_SL: "定額法", M_DB: "定率法", M_OSL: "旧定額法", M_ODB: "旧定率法", **sp.LABELS}
METHOD_FIELD = "depreciation_method"
METHOD_KEY_SUFFIX = ":償却の方法"

DEP_CHOICE_CANDIDATES = (
    Candidate({"lump_sum_depreciation": False, "small_amount_special_rule": False}, "適用しない"),
    Candidate({"lump_sum_depreciation": True, "small_amount_special_rule": True}, "適用する"),
)


@dataclass
class AssetResult:
    """人の年分の資産の集計。"""

    expense: dict[str, int] = field(default_factory=dict)  # 所得の側（biz・misc・rental）→ 必要経費算入額
    revenue: dict[str, int] = field(default_factory=dict)  # 所得の側 → 総収入金額に算入する売却代金（所令81二・三の資産の譲渡）
    selling_expense: dict[str, int] = field(default_factory=dict)  # 所得の側 → その売却の費用（必要経費。減価償却費ではない）
    disposal_loss: dict[str, int] = field(default_factory=dict)  # 所得の側 → 除却損（所法51④の上限の前）
    prepaid_tax: dict[str, int] = field(default_factory=dict)  # 所得の側 → 税抜の取得価額を使った資産の仮払消費税等（その年に取得した分）
    ids: dict[str, set[str]] = field(default_factory=dict)
    states: dict[str, set[State]] = field(default_factory=dict)
    problems: list[tuple[str, tuple[str, ...], str | None]] = field(default_factory=list)  # (理由, 記録, 所得の側か None)
    special_total: int = 0  # その年分に措法28の2 を使った資産の取得価額の合計（年の上限の検査）
    special_open: bool = False  # 措法28の2 を当てた資産に、選択が未入力（候補で評価している）ものがあるか
    missing: list[tuple[Split, str]] = field(default_factory=list)  # (決まらない1か所, 所得の側)。依存する値を未確定にする
    rows: dict[str, AssetRow] = field(default_factory=dict)  # 資産の ID → 減価償却費の計算の行（asset_rows.py。様式の償却の列）
    basis: dict[str, list[BasisEntry]] = field(default_factory=dict)  # 所得の側 → 減価償却費の根拠（割増・特別償却の外部の値：special_dep.py）

    def add_row(self, row: AssetRow) -> None:
        self.rows[row.asset_id] = row

    def write_rows(self, out: Any, pid: str, missing: Any, reasons: Any) -> None:
        """事業所得の側の資産の行を書く（asset_rows.write_rows。並べ方・あふれ・資産の数）。"""
        write_rows(out, pid, self.rows.values(), missing, reasons)

    def add(self, side: str, amount: int, ids: tuple[str, ...], states: set[State]) -> None:
        self.expense[side] = self.expense.get(side, 0) + amount
        self.ids.setdefault(side, set()).update(ids)
        self.states.setdefault(side, set()).update(states)

    def add_revenue(self, side: str, amount: int, ids: tuple[str, ...], states: set[State]) -> None:
        self.revenue[side] = self.revenue.get(side, 0) + amount
        self.ids.setdefault(side, set()).update(ids)
        self.states.setdefault(side, set()).update(states)

    def add_loss(self, side: str, amount: int, ids: tuple[str, ...]) -> None:
        self.disposal_loss[side] = self.disposal_loss.get(side, 0) + amount
        self.ids.setdefault(side, set()).update(ids)

    def add_prepaid(self, side: str, amount: int, ids: tuple[str, ...]) -> None:
        self.prepaid_tax[side] = self.prepaid_tax.get(side, 0) + amount
        self.ids.setdefault(side, set()).update(ids)


def placed_on(asset: Mapping[str, Any]) -> _dt.date:
    a = asset["attributes"]
    return date_of(a.get("placed_in_service_on") or asset["when"]["from_on"])


def disposed_on(asset: Mapping[str, Any]) -> _dt.date | None:
    to_on = asset["when"].get("to_on")
    return date_of(to_on) if to_on else None


def dep_slots(ctx: YearContext) -> list[DecisionSlot]:
    """選択.減価償却：その年分に効く資産（少額でない・一括の3年の間・措法28の2 の候補）ごとに1か所。単調の群（D21 R6）。

    選択の対象は業務の用に供した年分の1か所で、その後の一括償却の年分も同じ選択を読む（一括の年数は3年。読む範囲は in_window が決める）。
    """
    out = []
    for asset in ctx.records("depreciable_asset"):
        pid = asset["roles"]["owner"]
        if pid not in ctx.persons:
            continue
        ms = method_slot(ctx, asset)
        if ms is not None:
            out.append(ms)
        on = placed_on(asset)
        if on.year > ctx.year or ctx.year >= on.year + _lump_years(ctx):
            continue
        cost = asset["amounts"]["acquisition_cost"]
        if cost >= _lump_limit(ctx) and cost >= _special_upper(ctx, asset):
            continue  # 少額でも一括でも措法28の2 でもない（税抜経理でしきい値を割る場合は、税込の額で見ているので選択の1か所を作らないが、上の上限の判定では広めに残る）
        rid = asset["id"]
        out.append(
            DecisionSlot(
                key=rid,
                target={"asset_id": rid, "tax_year": on.year},
                matches=lambda rec, rid=rid, y=on.year: rec["subject"]["asset_id"] == rid
                and rec["when"]["tax_year"] == y
                and not _method_only(rec),
                candidates=DEP_CHOICE_CANDIDATES,
                year_filter=False,
                persons=(pid,),
                monotone=f"減価償却の選択:{pid}",
            )
        )
    return out


def _method_only(rec: Mapping[str, Any]) -> bool:
    """選択.減価償却 の記録が償却の方法だけを書いたものか（一括・少額の特例の1か所の値にしない）。"""
    v = rec.get("value")
    return isinstance(v, Mapping) and METHOD_FIELD in v and not any(
        k in v for k in ("lump_sum_depreciation", "small_amount_special_rule", "depreciate_in_disposal_year")
    )


def method_notices(ctx: YearContext, pid: str) -> tuple[str, ...]:
    """その人の償却の方法の届出の記録（その年分以前の bookkeeping_status で depreciation_method_notice の記載があるもの）の ID。"""
    return tuple(
        sorted(
            r["id"]
            for r in ctx.records("bookkeeping_status")
            if r["roles"]["person"] == pid
            and r["when"]["tax_year"] <= ctx.year
            and str(r["attributes"].get("depreciation_method_notice") or "").strip()
        )
    )


#: 旧定率法を選べる建物の取得の日の上限（所令120①一イ：平成10年3月31日以前に取得された建物）。
OLD_BUILDING_DB_UNTIL = _dt.date(1998, 3, 31)
#: 定率法を選べる建物附属設備・構築物の取得の日の上限（所令120の2①一イ：平成28年3月31日以前に取得）。
ATTACHMENT_DB_UNTIL = _dt.date(2016, 3, 31)


def asset_class(judgment: Mapping[str, Any] | None) -> str | None:
    """資産の種類（判断.減価償却の区分 の asset_class）。なければ耐用年数の表の行から（ソフトウエアは無形、それ以外の行は器具備品・
    車両・機械の行なので machinery_equipment）。どちらもなければ None（区分が分からない）。"""
    value = judgment["value"] if judgment is not None else {}
    if value.get("asset_class"):
        return str(value["asset_class"])
    row = value.get("useful_life_table_row")
    if not row:
        return None
    return "intangible" if row.startswith("ソフトウエア") else "machinery_equipment"


def method_candidates(ctx: YearContext, asset: Mapping[str, Any], judgment: Mapping[str, Any] | None) -> tuple[str, ...]:
    """資産が通常の償却をするときに、その人が採りうる償却の方法（先頭が法定償却方法：所令125）。

    届出の記録がなければ法定償却方法だけ。届出の記録があれば、資産の種類と取得の日で選べる方法の全部（所令120①・120の2①）：
    建物は平成10年3月31日以前の取得だけ旧定率法、平成19年4月1日以後は定額法だけ。建物附属設備・構築物は平成28年3月31日以前の取得だけ
    定率法。無形は旧定額法・定額法だけ。種類が分からない資産は両方を候補にする（選択.減価償却 の depreciation_method で決まる）。
    """
    acquired = date_of(asset["when"]["from_on"])
    old = acquired < STRAIGHT_LINE_FROM
    base = M_OSL if old else M_SL
    cls = asset_class(judgment)
    if cls in sp.CLASSES:  # 鉱業用・坑道・鉱業権・国外リース資産・リース資産（所令120①三・五・六、120の2①三・五・六、125①。IK-103）
        value = judgment["value"] if judgment is not None else {}
        return sp.candidates(cls, acquired, bool(method_notices(ctx, asset["roles"]["owner"])), value, ctx.year, asset, STRAIGHT_LINE_FROM)
    if cls in ("intangible", "other") or not method_notices(ctx, asset["roles"]["owner"]):
        return (base,)
    if cls == "building" and (not old or acquired > OLD_BUILDING_DB_UNTIL):
        return (base,)
    if cls in ("building_attachment", "structure") and not old and acquired > ATTACHMENT_DB_UNTIL:
        return (base,)
    return (base, M_ODB if old else M_DB)


def method_key(rid: str) -> str:
    return f"{rid}{METHOD_KEY_SUFFIX}"


def method_slot(ctx: YearContext, asset: Mapping[str, Any]) -> DecisionSlot | None:
    """償却の方法の1か所（候補が2つ以上で、その年分に償却する資産。読んだときだけ開く：少額・一括・措法28の2 の資産は読まない）。"""
    on = placed_on(asset)
    disposed = disposed_on(asset)
    if on.year > ctx.year or (disposed is not None and disposed.year < ctx.year):
        return None
    rid = asset["id"]
    methods = method_candidates(ctx, asset, dep_class(ctx, rid))
    if len(methods) < 2:
        return None
    return DecisionSlot(
        key=method_key(rid),
        target={"asset_id": rid, "field": METHOD_FIELD, "notices": list(method_notices(ctx, asset["roles"]["owner"]))},
        matches=lambda rec, rid=rid: rec["subject"]["asset_id"] == rid and isinstance(rec.get("value"), Mapping) and METHOD_FIELD in rec["value"],
        candidates=tuple(Candidate({METHOD_FIELD: m}, METHOD_LABELS[m]) for m in methods),
        year_filter=False,
        persons=(asset["roles"]["owner"],),
        lazy=True,
    )


def _lump_years(ctx: YearContext) -> int:
    return 3  # 所令139①「三年間」（条文の語）


def _lump_limit(ctx: YearContext) -> int:
    return int(ctx.parameters.所得税.減価償却.一括償却資産の取得価額の上限)


def _small_limit(ctx: YearContext) -> int:
    return int(ctx.parameters.所得税.減価償却.少額の減価償却資産の取得価額の上限)


def _special_node(ctx: YearContext) -> Any:
    return ctx.parameters.所得税.減価償却.中小事業者の少額減価償却資産


def _special_upper(ctx: YearContext, asset: Mapping[str, Any]) -> int:
    """措法28の2 の取得価額の上限（未満）。取得の日で区分する（令和8年法律第12号附則第35条）。"""
    n = _special_node(ctx)
    acquired = date_of(asset["when"]["from_on"])
    cut = _yyyymmdd(int(n.取得の日の区分の開始))
    return int(n.取得価額の上限_令和8年4月1日以後の取得 if acquired >= cut else n.取得価額の上限_令和8年3月31日までの取得)


def _yyyymmdd(v: int) -> _dt.date:
    return _dt.date(v // 10000, v // 100 % 100, v % 100)


def dep_class(ctx: YearContext, rid: str) -> Mapping[str, Any] | None:
    """判断.減価償却の区分（資産ごと。置き換えの連鎖の先頭。なければ None）。"""
    found = [j for j in ctx.judgments(K_DEP_CLASS) if j["subject"]["asset_id"] == rid]
    return found[0] if found else None


def useful_life(
    ctx: YearContext, asset: Mapping[str, Any], judgment: Mapping[str, Any] | None
) -> tuple[int | None, bool, str | None]:
    """(耐用年数, 無形か, 問題)。判断の useful_life_years か、表の行（別表第一・第三）。中古で年数の判断がなければ簡便法（耐用年数省令3①二）。"""
    value = judgment["value"] if judgment is not None else {}
    row = value.get("useful_life_table_row")
    intangible = asset_class(judgment) == "intangible"
    years = value.get("useful_life_years")
    prior = asset["attributes"].get("prior_use_months")
    if years is not None:
        return int(years), intangible, None
    if row is None:
        return None, intangible, "耐用年数の判断（判断.減価償却の区分の useful_life_years か useful_life_table_row）がない"
    table = ctx.parameters.所得税.減価償却の耐用年数
    try:
        legal = int(getattr(table, row))
    except (AttributeError, KeyError):
        return None, intangible, f"耐用年数の表にない行（{row}）：useful_life_years で耐用年数を入力する"
    if not prior:
        return legal, intangible, None
    return _second_hand_years(legal, int(prior)), intangible, None


def _second_hand_years(legal: int, prior_months: int) -> int:
    """中古資産の耐用年数（簡便法）：耐用年数省令3①二（法定耐用年数の全部経過は×20%、一部経過は 法定−経過＋経過×20%）。1年未満切捨て・2年未満は2年（③⑤）。"""
    legal_m = legal * 12
    if prior_months >= legal_m:
        months = Fraction(legal_m * 20, 100)
    else:
        months = Fraction(legal_m - prior_months) + Fraction(prior_months * 20, 100)
    years = months // 12
    return max(2, int(years))


@dataclass(frozen=True)
class CostInfo:
    """資産の判定と償却に使う取得価額（経理方式で税抜か税込か）と、税抜のときの仮払消費税等。"""

    cost: int | None
    prepaid_tax: int
    problem: str | None = None


def straight_line_rate(ctx: YearContext, years: int) -> int | None:
    node = ctx.parameters.所得税.減価償却.定額法償却率
    try:
        return int(getattr(node, f"年数{years}"))
    except (AttributeError, KeyError):
        return None


@dataclass(frozen=True)
class MethodRates:
    """償却の方法の率（千分率の整数。保証率は十万分率の整数）と、旧償却の限度（百分率・年数）。"""

    method: str
    rate: int
    revised: int | None = None  # 改定償却率（定率法）
    guarantee: int | None = None  # 保証率（定率法）
    residual_pct: int = 0  # 残存割合（旧定額法）
    limit_pct: int | None = None  # 旧償却の有形の累積の限度（取得価額に対する百分率：所令134①一イ）
    equal_years: int | None = None  # 限度に達した後の均等償却の年数（所令134②）


def _row(node: Any, years: int) -> int | None:
    try:
        return int(getattr(node, f"年数{years}"))
    except (AttributeError, KeyError):
        return None


def method_rates(ctx: YearContext, method: str, years: int, acquired: _dt.date, intangible: bool) -> MethodRates | None:
    """方法と耐用年数の率（表にない耐用年数なら None）。"""
    if method == M_SL:
        rate = straight_line_rate(ctx, years)
        return None if rate is None else MethodRates(method, rate)
    t = ctx.parameters.所得税.減価償却
    if method == M_DB:
        node = t.定率法_平成24年3月31日以前の取得 if acquired <= DB250_UNTIL else t.定率法_平成24年4月1日以後の取得
        rate = _row(node.償却率, years)
        return None if rate is None else MethodRates(method, rate, _row(node.改定償却率, years), _row(node.保証率, years))
    limit = t.旧償却の償却累積額の限度
    old = {
        "limit_pct": None if intangible else int(limit.取得価額に対する割合),
        "equal_years": None if intangible else int(limit.均等償却の年数),
    }
    if method == M_OSL:
        rate = _row(t.旧定額法償却率, years)
        residual = int(t.旧定額法の残存割合.無形 if intangible else t.旧定額法の残存割合.有形)
        return None if rate is None else MethodRates(method, rate, residual_pct=residual, **old)
    if method == M_ODB:
        rate = _row(t.旧定率法償却率, years)
        return None if rate is None else MethodRates(method, rate, **old)
    raise ValueError(f"償却の方法: {method}")


def _months(yr: int, placed: _dt.date, disposed: _dt.date | None) -> int:
    """その年の月数（所令132①一イ・二イ・②）。"""
    if yr == placed.year:
        return first_year_months(placed, yr) if disposed is None or disposed.year != yr else calendar_months(placed, disposed)
    if disposed is not None and disposed.year == yr:
        return calendar_months(_dt.date(yr, 1, 1), disposed)
    return 12


class YearDep(NamedTuple):
    """depreciation_schedule の1年分。base・rate・months は減価償却費の計算の行の列（asset_rows.py）の材料。"""

    year: int
    amount: int  # 償却費（全額。事業専用割合を掛ける前）
    accum: int  # その年までの累計
    base: int = 0  # 償却の基礎になる金額（その年の式の基礎。1円未満は切上げ：DEPRECIATION_CEIL）
    rate: Fraction | None = None  # その年に使った率（定率法で改定償却率に切り替えた年からは改定償却率、所令134② の年は 1/5）
    months: int = 0  # 本年中の償却期間（所令132①・②）
    special: int = 0  # 割増・特別償却の額（外部の値。累計 accum に含む。special_dep.py。2026-11-12）


def depreciation_schedule(
    cost: int,
    rates: MethodRates,
    placed: _dt.date,
    disposed: _dt.date | None,
    up_to: int,
    intangible: bool,
    special: Mapping[int, int] | None = None,
) -> list[YearDep]:
    """年ごとの償却費（全額。事業専用割合を掛ける前）。YearDep（年, 償却費, 累計, 償却の基礎, 使った率, 月数）の並び。1円未満は年ごとに切上げ（DEPRECIATION_CEIL）。

    special（年 → 割増・特別償却の額。外部の値：special_dep.py）は、その年の普通償却費の後に累計へ足す（未償却残高を減らし、その後の年の
    定率法・旧定率法の期首未償却残高と累積の限度に効く）。累積の限度を超える部分は足さない（YearDep.special が記録の額より小さくなる：呼び出し側が確かめる）。"""
    cap = cost - (0 if intangible else 1)  # 所令134①二イ・ロ、134②（取得価額−1円）、134①一ロ（無形は取得価額）
    limit95 = ceil_yen(Fraction(cost * rates.limit_pct, 100)) if rates.limit_pct is not None else None
    residual = Fraction(cost * rates.residual_pct, 100)
    guarantee = Fraction(cost * rates.guarantee, 100_000) if rates.guarantee is not None else None
    revised_base: int | None = None  # 改定取得価額（所令120の2②二）
    accum = 0
    out: list[YearDep] = []
    for yr in range(placed.year, up_to + 1):
        if disposed is not None and disposed.year < yr:
            break
        months = _months(yr, placed, disposed)
        book = cost - accum
        upper = cap
        if limit95 is not None and accum >= limit95:
            # 所令134②：前年までの累積が95%に達している → （取得価額−95%相当額−1円）÷5（月数は134③ で132を準用）
            base, rate = Fraction(cost - limit95 - 1), Fraction(1, rates.equal_years)  # type: ignore[arg-type]
        else:
            if limit95 is not None:
                upper = limit95  # 所令134①一イ
            if rates.method == M_SL:
                base, rate = Fraction(cost), Fraction(rates.rate, 1000)
            elif rates.method == M_OSL:
                base, rate = cost - residual, Fraction(rates.rate, 1000)
            elif rates.method == M_ODB:
                base, rate = Fraction(book), Fraction(rates.rate, 1000)
            else:  # 定率法
                adjusted = Fraction(book * rates.rate, 1000)  # 調整前償却額（所令120の2②二イ）
                if revised_base is None and guarantee is not None and rates.revised is not None and adjusted < guarantee:
                    revised_base = book  # 償却保証額に満たない最初の年の期首未償却残高
                if revised_base is None:
                    base, rate = Fraction(book), Fraction(rates.rate, 1000)
                else:  # 改定取得価額 × 改定償却率（所令120の2①一イ(2)）
                    base, rate = Fraction(revised_base), Fraction(rates.revised, 1000)  # type: ignore[arg-type]
        full = base * rate
        amount = min(ceil_yen(full * months / 12), max(0, upper - accum))
        accum += amount
        extra = min((special or {}).get(yr, 0), max(0, upper - accum))
        accum += extra
        out.append(YearDep(yr, amount, accum, ceil_yen(base), rate, months, extra))
    return out


def straight_line_schedule(
    cost: int, rate_num: int, placed: _dt.date, disposed: _dt.date | None, up_to: int, intangible: bool
) -> list[YearDep]:
    """定額法の年ごとの償却費（取得価額×率×月数/12、切上げ、累計は上限まで）。(年, 償却費, 累計) の並び。"""
    return depreciation_schedule(cost, MethodRates(M_SL, rate_num), placed, disposed, up_to, intangible)


def asset_year(
    ctx: YearContext,
    out: AssetResult,
    asset: Mapping[str, Any],
    side: str,
    cost_info: CostInfo,
    blue_at: Callable[[int], bool],
    share: Fraction | None,
    share_ids: tuple[str, ...],
    share_states: set[State],
    business_period: tuple[_dt.date, _dt.date | None],
    blue_now: Callable[[], tuple[bool, bool]] | None = None,
    side_open: bool = False,
) -> None:
    """資産1つの年分の扱いを決めて out に足す。

    blue_now()（2026-11-12）：その年分に青色申告の承認があるか・承認が読みで分かれるか（割増・特別償却の要件：special_dep.py）。
    渡さなければ承認なし・分かれない。side_open：所得の側（事業所得か業務に係る雑所得か）が未入力の判断の候補か。"""
    rid = asset["id"]
    a = asset["attributes"]
    on = placed_on(asset)
    disposed = disposed_on(asset)
    if on.year > ctx.year:
        if sd.records_for(ctx, rid) and any(int(r["when"]["tax_year"]) <= ctx.year for r in sd.records_for(ctx, rid)):
            out.problems.append((sd.SPECIAL_YEAR_REASON, (rid,), side))
        return
    if a.get("acquisition_type") not in (None, "purchase", "self_constructed", "gift", "inheritance"):
        out.problems.append(("減価償却資産の取得の形（other）が扱えない", (rid,), side))
        return
    if cost_info.cost is None:
        out.problems.append((cost_info.problem or "取得価額が決まらない", (rid,), side))
        return
    cost = cost_info.cost
    acquired = date_of(asset["when"]["from_on"])
    decided = ctx.decision(K_DEP_CHOICE, rid) if _has_slot(ctx, asset) else None
    choice = decided.value if decided is not None else {}
    judgment = dep_class(ctx, rid)
    value = judgment["value"] if judgment is not None else {}
    leased = bool(a.get("leased_out"))
    principal_lending = bool(value.get("lending_as_principal_business"))
    usable_short = bool(value.get("usable_period_under_one_year"))
    cls = asset_class(judgment)
    lease_asset = cls in sp.LEASES  # リース資産・国外リース資産は少額（所令138①）・一括（所令139①）の対象外（括弧書き）
    usable_short = usable_short and not lease_asset
    can_small = (not leased or principal_lending) and not lease_asset
    ids = (rid, *( [judgment["id"]] if judgment is not None else []), *(decided.record_ids if decided else ()), *share_ids)
    states = set(share_states) | (set(decided.states) if decided else set()) | ({State.from_mark(judgment["mark"])} if judgment and "mark" in judgment else set())
    # 割増・特別償却（外部の値。special_dep.py。2026-11-12）
    sdp = sd.plan(ctx, asset, side, on.year, disposed.year if disposed is not None else None, blue_now or (lambda: (False, False)), side_open=side_open)
    if sdp.problem is not None:
        out.problems.append((sdp.problem, (rid, *sdp.ids), side))
        return
    ids = (*ids, *sdp.ids)
    states = states | sdp.states
    # 少額（所令138）
    if (cost < _small_limit(ctx) and can_small or usable_short) and sdp.any:
        out.problems.append((sd.SPECIAL_FULL_EXPENSE_REASON, (rid, *sdp.ids), side))
        return
    if cost < _small_limit(ctx) and can_small or usable_short:
        if on.year == ctx.year:
            amount = _after_share(ctx, Fraction(cost), share)
            out.add(side, amount, ids, states)
            _whole_row(out, asset, side, LABEL_SMALL, cost, cost, share, amount, 0, ids, states)
        # 所令81二：取得価額が10万円未満のもので業務の性質上基本的に重要なものを除き、売却代金は譲渡所得でなく業務の総収入金額
        _small_sale(out, asset, side, ids, states, ctx.year, essential_matters=not usable_short or cost < _small_limit(ctx), essential=value.get("essential_to_business"))
        return
    # 割増・特別償却の記録がある資産：選択.減価償却 が未入力（候補）なら一括・措法28の2 を当てない候補だけ（記録が普通償却を前提にする）。
    # 入力した選択で当てるなら入力の矛盾
    if sdp.any and (choice.get("lump_sum_depreciation") or choice.get("small_amount_special_rule")):
        if decided is not None and not decided.open:
            out.problems.append((sd.SPECIAL_FULL_EXPENSE_REASON, (rid, *sdp.ids, *decided.record_ids), side))
            return
        choice = {}
    # 一括（所令139）
    if cost < _lump_limit(ctx) and can_small and choice.get("lump_sum_depreciation"):
        if on.year <= ctx.year < on.year + _lump_years(ctx):
            n = _lump_years(ctx)
            amount = _after_share(ctx, Fraction(cost, n), share)
            out.add(side, amount, ids, states)
            third = _after_share(ctx, Fraction(cost, n), None)  # 事業専用割合を掛ける前の 1/3（端数は同じ根拠のない端数の候補）
            k = ctx.year - on.year + 1
            _whole_row(out, asset, side, LABEL_LUMP, cost, third, share, amount, 0 if k >= n else max(0, cost - third * k), ids, states)
        # 所令81三：業務の性質上基本的に重要なものを除き、売却代金は業務の総収入金額（1/3 は売っても続ける：所基通49−40の2）
        _small_sale(out, asset, side, ids, states, ctx.year, essential_matters=True, essential=value.get("essential_to_business"))
        return
    if disposed is not None and disposed.year < ctx.year:
        return  # 前年以前に処分済み（一括償却資産は上で処分後も 1/3 を続ける：所基通49−40の2）
    # 中小事業者の少額（措法28の2）
    if (
        side in ("biz", "rental")
        and can_small
        and choice.get("small_amount_special_rule")
        and cost < _special_upper(ctx, asset)
        and blue_at(on.year)
        and acquired <= _yyyymmdd(int(_special_node(ctx).取得の日の期限))
    ):
        if on.year == ctx.year:
            out.special_total += cost
            out.special_open = out.special_open or bool(decided is not None and decided.open)
            amount = _after_share(ctx, Fraction(cost), share)
            out.add(side, amount, ids, states)
            _whole_row(out, asset, side, LABEL_SPECIAL_SMALL, cost, cost, share, amount, 0, ids, states)
            _check_annual_limit(ctx, out, on, business_period, rid, side, asset["roles"]["owner"])
        return
    # 通常の償却（定額法・定率法・旧定額法・旧定率法）と特別な方法（生産高比例法・リース期間定額法など：assets_special.py。IK-103）
    special = cls in sp.CLASSES
    years: int | None = None
    intangible = cls in sp.ZERO_RESIDUAL  # 坑道・鉱業権は残存価額0・限度は取得価額（別表第十一、所令134①一ロ・二ロ）
    if not special:
        years, intangible, problem = useful_life(ctx, asset, judgment)
        if years is None:
            out.problems.append((problem or "耐用年数が決まらない", (rid,), side))
            return
    methods = method_candidates(ctx, asset, judgment)
    method = methods[0]
    if len(methods) == 1:
        # 法定償却方法しか採れない（届出の記録がない・資産の種類で選べない）のに、ほかの方法を選んだ記録がある：入力の矛盾（c-入力）
        bad = [
            c["id"]
            for c in ctx.choices(K_DEP_CHOICE)
            if c["subject"]["asset_id"] == rid
            and isinstance(c.get("value"), Mapping)
            and c["value"].get(METHOD_FIELD) not in (None, method)
        ]
        if bad:
            chosen = next(c["value"][METHOD_FIELD] for c in ctx.choices(K_DEP_CHOICE) if c["id"] == bad[0])
            out.problems.append((METHOD_MISMATCH_REASON.format(method=chosen, allowed=METHOD_LABELS[method]), (rid, *bad), side))
            return
    else:
        md = ctx.decision(K_DEP_CHOICE, method_key(rid))
        method = (md.value or {}).get(METHOD_FIELD) if isinstance(md.value, Mapping) else None
        ids = (*ids, *md.record_ids, *method_notices(ctx, asset["roles"]["owner"]))
        states = states | set(md.states)
        if method not in methods:
            out.problems.append((METHOD_MISMATCH_REASON.format(method=method, allowed="・".join(METHOD_LABELS[m] for m in methods)), (rid, *md.record_ids), side))
            return
    if sdp.any and (cls in sp.LEASES or method in (sp.M_LEASE, sp.M_TLEASE, sp.M_FLEASE)):
        out.problems.append((sd.SPECIAL_LEASE_REASON, (rid, *sdp.ids), side))
        return
    if sdp.basis:
        out.basis.setdefault(side, []).extend(sdp.basis)
    if method in sp.METHODS:
        first_tl = _first_transitional(ctx, asset) if method == sp.M_TLEASE else None
        if method == sp.M_TLEASE and _transitional_mixed(ctx, asset):
            out.problems.append((sp.TRANSITIONAL_MIX_REASON, (rid,), side))
            return
        t = ctx.parameters.所得税.減価償却
        spec = sp.Special(cls, method, cost, on, disposed, ctx.year, intangible=_software_row(judgment), special=sdp.by_year)  # type: ignore[arg-type]
        schedule, problem = sp.schedule(
            spec, asset, value, int(t.旧定額法の残存割合.有形), int(t.旧償却の償却累積額の限度.取得価額に対する割合), first_tl
        )
        if problem is not None:
            out.problems.append((problem, (rid, *([judgment["id"]] if judgment is not None else [])), side))
            return
        return _book_year(ctx, out, asset, side, schedule, cost, share, ids, states, method=method, special=sdp.by_year)
    if years is None:  # 特別な資産で定額法・定率法・旧定額法・旧定率法を選んだ：耐用年数が要る
        years, _, problem = useful_life(ctx, asset, judgment)
        if years is None:
            out.problems.append((problem or "耐用年数が決まらない", (rid,), side))
            return
    rates = method_rates(ctx, method, years, acquired, intangible)
    if rates is None:
        table = {M_SL: "別表第八", M_DB: "別表第九・第十", M_OSL: "別表第七", M_ODB: "別表第七"}[method]
        out.problems.append((f"耐用年数 {years} 年が{table}（{METHOD_LABELS[method]}）にない", (rid,), side))
        return
    schedule = depreciation_schedule(cost, rates, on, disposed, ctx.year, intangible, sdp.by_year)
    guarantee = ceil_yen(Fraction(cost * rates.guarantee, 100_000)) if method == M_DB and rates.guarantee is not None else 0
    _book_year(ctx, out, asset, side, schedule, cost, share, ids, states, method=method, years=years, guarantee=guarantee, special=sdp.by_year)


def _software_row(judgment: Mapping[str, Any] | None) -> bool:
    """リース資産が無形（ソフトウエア）か（耐用年数の表の行。所令134①二ロ：限度は取得価額）。"""
    row = (judgment["value"] if judgment is not None else {}).get("useful_life_table_row") or ""
    return str(row).startswith("ソフトウエア")


def _first_transitional(ctx: YearContext, asset: Mapping[str, Any]) -> int:
    """経過リース期間定額法を最初に当てる年分：その資産に経過リース期間定額法を選んだ 選択.減価償却 の年分のうち最も前のもの。
    選択の記録がない（候補で評価している）ときは、当てられる最初の年分（令和8年分か取得の年分の遅い方）。"""
    years = [
        int(c["when"]["tax_year"])
        for c in ctx.choices(K_DEP_CHOICE)
        if c["subject"]["asset_id"] == asset["id"] and isinstance(c.get("value"), Mapping) and c["value"].get(METHOD_FIELD) == sp.M_TLEASE
    ]
    return min(years) if years else max(sp.TRANSITIONAL_FIRST_YEAR, placed_on(asset).year)


def _transitional_mixed(ctx: YearContext, asset: Mapping[str, Any]) -> bool:
    """附則7②ただし書：同じ人のその年の経過リース資産に、リース期間定額法を選んだ記録があるか（経過リース期間定額法は全部で選ぶ）。"""
    owner = asset["roles"]["owner"]
    eligible = {
        a["id"]
        for a in ctx.records("depreciable_asset")
        if a["roles"]["owner"] == owner
        and a["id"] != asset["id"]
        and asset_class(dep_class(ctx, a["id"])) == "lease_asset"
        and sp.transitional_eligible(ctx.year, a)
        and placed_on(a).year <= ctx.year
        and (disposed_on(a) is None or disposed_on(a).year >= ctx.year)  # type: ignore[union-attr]
    }
    return any(
        c["subject"]["asset_id"] in eligible and isinstance(c.get("value"), Mapping) and c["value"].get(METHOD_FIELD) == sp.M_LEASE
        for c in ctx.choices(K_DEP_CHOICE)
    )


def _book_year(
    ctx: YearContext,
    out: AssetResult,
    asset: Mapping[str, Any],
    side: str,
    schedule: list[tuple[int, int, int]],
    cost: int,
    share: Fraction | None,
    ids: tuple[str, ...],
    states: set[State],
    *,
    method: str,
    years: int | None = None,
    guarantee: int = 0,
    special: Mapping[int, int] | None = None,
) -> None:
    """その年分の償却費と、処分（除却・滅失）の損失を out に足す。減価償却費の計算の行（out.rows）も書く。

    schedule は depreciation_schedule の YearDep（償却の基礎・使った率・月数つき）か、特別な方法（assets_special）の (年, 償却費, 累計)。
    特別な方法の行は、償却の基礎・耐用年数・償却率・月数を 0／なし（様式の欄は空欄）にする。
    special（年 → 割増・特別償却の額：special_dep.py。2026-11-12）：累計に入った額が記録の額と違えば（累積の限度を超えた）入力の矛盾。
    その年の額は普通償却費と合わせて必要経費（事業専用割合は合計に掛ける）と行の「割増（特別）償却費」に入る。"""
    rid = asset["id"]
    a = asset["attributes"]
    disposed = disposed_on(asset)
    applied = _special_applied(schedule)
    if special and any(applied.get(y, 0) != v for y, v in special.items() if y <= ctx.year):
        out.problems.append((sd.SPECIAL_EXCESS_REASON, tuple(ids), side))
        return
    this_year = next((s for s in schedule if s[0] == ctx.year), None)
    if this_year is None:
        return
    dep, accum = this_year[1], this_year[2]
    extra = applied.get(ctx.year, 0)
    total = dep + extra
    expense = _after_share(ctx, Fraction(total), share) if total else 0
    if total:
        out.add(side, expense, ids, states)
    detail = this_year if isinstance(this_year, YearDep) else None
    out.add_row(AssetRow(
        asset_id=rid, side=side, acquired=date_of(asset["when"]["from_on"]), method=METHOD_LABELS[method],
        base=detail.base if detail else 0, years=(years or 0) if detail else 0, rate=detail.rate if detail else None,
        months=detail.months if detail else 0, ordinary=dep, share=share, expense=expense, unamortized=cost - accum,
        guarantee=guarantee, special=extra, ids=tuple(ids), states=frozenset(states),
    ))  # fmt: skip
    # 処分（除却・滅失）
    if disposed is not None and disposed.year == ctx.year:
        kind = a.get("disposal_type")
        if kind == "sale":
            out.problems.append((SALE_TRANSFER_REASON, (rid,), side))
            return
        amts = asset["amounts"]
        loss = cost - accum + amts.get("disposal_expenses", 0) - amts.get("disposal_proceeds", 0) - amts.get("insurance_recovery", 0)
        if loss < 0:
            # 所法51①④ の損失は0。超える部分の所得の種類を定める一次情報がない：候補の全部で評価し、業務の側を未確定にする（D22 S1）
            out.missing.append((
                undetermined(
                    f"一次情報:除却の処分価額等が未償却残高を超える部分:{rid}", Means.PRIMARY_SOURCE,
                    {"asset_id": rid, "tax_year": ctx.year, "超える額": -loss, "事項": DISPOSAL_EXCESS_REASON},
                    DISPOSAL_EXCESS_CANDIDATES,
                ),
                side,
            ))
            out.ids.setdefault(side, set()).update(ids)
            return
        if loss:
            out.add_loss(side, _after_share(ctx, Fraction(loss), share), ids)


def _special_applied(schedule: list[Any]) -> dict[int, int]:
    """償却の表の各年に累計へ入った割増・特別償却の額（YearDep は special、特別な方法の (年, 償却費, 累計) は累計の差 − 償却費）。0 の年は持たない。"""
    out: dict[int, int] = {}
    prev = 0
    for s in schedule:
        extra = s.special if isinstance(s, YearDep) else s[2] - prev - s[1]
        prev = s[2]
        if extra:
            out[s[0]] = extra
    return out


DISPOSAL_EXCESS_REASON = (
    "除却・滅失で処分価額・保険金等が未償却残高を超えた。所法51①④の損失は0だが、超える部分の所得の種類（所得に入れない・業務の総収入金額・"
    "譲渡所得）を定める一次情報が docs にない（決める手段は一次情報）"
)
DISPOSAL_EXCESS_CANDIDATES = ("所得に入れない", "業務の総収入金額", "譲渡所得")
ANNUAL_LIMIT_REASON = (
    "措法28の2① の年間の取得価額の合計額の上限（300万円。開業・廃業の年は月割）を超える選択が入力されている。上限に達するまでのどの資産に当てるかは"
    "納税者が選ぶので、選択.減価償却 の small_amount_special_rule を資産ごとに、合計が上限以下になるように入れる（超える資産は false にして通常の償却）"
)
ANNUAL_LIMIT_OPEN = (
    "措法28の2① の年間の取得価額の合計額の上限（300万円。開業・廃業の年は月割）を超える候補がある。どの資産に当てるかは納税者の選択"
    "（選択.減価償却 の small_amount_special_rule を資産ごとに、合計が上限以下になるように入れる）"
)
#: 法定償却方法が生産高比例法・旧生産高比例法・旧国外リース期間定額法などになる資産は assets_special.py（IK-103。2026-11-12 に実装）。
METHOD_MISMATCH_REASON = (
    "選択.減価償却 の depreciation_method（{method}）が、資産の取得の日と種類（判断.減価償却の区分 の asset_class）と償却の方法の届出"
    "（bookkeeping_status の depreciation_method_notice）で選べる償却の方法（{allowed}）でない（所令120①・120の2①・125）"
)
SALE_TRANSFER_REASON = (
    "減価償却資産の譲渡（所令81二・三に当たらない資産の売却代金は譲渡所得〔総合譲渡〕で、後の段：D21 R3）"
)
SALE_ESSENTIAL_MISSING_REASON = (
    "少額・一括償却資産の売却で、業務の性質上基本的に重要なものか（判断.減価償却の区分の essential_to_business）が入力されていない"
    "（所令81二・三：重要なものの売却代金は譲渡所得、そうでなければ業務の総収入金額）"
)


def _small_sale(
    out: AssetResult,
    asset: Mapping[str, Any],
    side: str,
    ids: tuple[str, ...],
    states: set[State],
    year: int,
    *,
    essential_matters: bool,
    essential: bool | None,
) -> None:
    """少額（所令138）・一括（所令139）の減価償却資産をその年に売ったとき：所令81二・三に当たれば売却代金を業務の総収入金額に足す
    （決算の手引き p.4「12 減価償却資産の売却代金」）。業務の性質上基本的に重要なものは譲渡所得（後の段）で対象外。"""
    disposed = disposed_on(asset)
    if disposed is None or disposed.year != year or asset["attributes"].get("disposal_type") != "sale":
        return
    rid = asset["id"]
    if essential_matters and essential is None:
        out.problems.append((SALE_ESSENTIAL_MISSING_REASON, (rid,), side))
        return
    if essential_matters and essential:
        out.problems.append((SALE_TRANSFER_REASON, (rid,), side))
        return
    amts = asset["amounts"]
    if "disposal_proceeds" not in amts:
        out.problems.append(("少額・一括償却資産の売却で、売却代金（disposal_proceeds）の記録がない", (rid,), side))
        return
    out.add_revenue(side, amts["disposal_proceeds"], ids, states)
    if amts.get("disposal_expenses"):
        out.selling_expense[side] = out.selling_expense.get(side, 0) + amts["disposal_expenses"]


def _after_share(ctx: YearContext, amount: Fraction, share: Fraction | None) -> int:
    """事業専用割合を掛けた額（1円未満は根拠のない端数の候補。D22 S3）。割合がないときは割り切れる額（少額・定額法）か、1/3（一括）だけが端数を持つ。"""
    value = amount if share is None else amount * share
    if value.denominator == 1:
        return int(value)
    return ctx.round_unfounded(ROUNDING_EXPENSE, value)


#: 減価償却費の計算の行の償却方法の名前（少額・一括・措法28の2。通常の償却・特別な方法は METHOD_LABELS）。
LABEL_SMALL = "少額の減価償却資産（所令138）"
LABEL_LUMP = "一括償却資産（所令139）"
LABEL_SPECIAL_SMALL = "中小事業者の少額減価償却資産（措法28の2）"


def _whole_row(
    out: AssetResult,
    asset: Mapping[str, Any],
    side: str,
    label: str,
    cost: int,
    ordinary: int,
    share: Fraction | None,
    expense: int,
    unamortized: int,
    ids: tuple[str, ...],
    states: set[State],
) -> None:
    """少額・一括・措法28の2 の行（耐用年数・償却率・本年中の償却期間は 0／なし：式 ロ×ハ×ニ の形でない）。"""
    out.add_row(AssetRow(
        asset_id=asset["id"], side=side, acquired=date_of(asset["when"]["from_on"]), method=label, base=cost, years=0, rate=None,
        months=0, ordinary=ordinary, share=share, expense=expense, unamortized=unamortized, ids=tuple(ids), states=frozenset(states),
    ))  # fmt: skip


def _has_slot(ctx: YearContext, asset: Mapping[str, Any]) -> bool:
    on = placed_on(asset)
    if on.year > ctx.year or ctx.year >= on.year + _lump_years(ctx):
        return False
    cost = asset["amounts"]["acquisition_cost"]
    return not (cost >= _lump_limit(ctx) and cost >= _special_upper(ctx, asset))


def _check_annual_limit(
    ctx: YearContext, out: AssetResult, placed: _dt.date, period: tuple[_dt.date, _dt.date | None], rid: str, side: str, pid: str
) -> None:
    """措法28の2① の年間の上限。入力した選択の合計が超えれば入力の矛盾（c-入力）。未入力の選択の候補で超えるなら、
    どの資産に当てるかは納税者の選択なので、業務の側を未確定にする（分かれ目は判断：選択.減価償却）。"""
    n = _special_node(ctx)
    limit = Fraction(int(n.年間の取得価額の合計額の上限))
    start, end = period
    first = max(start, _dt.date(placed.year, 1, 1))
    last = _dt.date(placed.year, 12, 31) if end is None else min(end, _dt.date(placed.year, 12, 31))
    if start.year == placed.year or (end is not None and end.year == placed.year):
        months = calendar_months(first, last)
        limit = limit * months / 12
    if Fraction(out.special_total) <= limit:
        return
    if not out.special_open:
        out.problems.append((ANNUAL_LIMIT_REASON, (rid,), None))
        return
    sid = f"判断:措法28の2の年間の上限:{pid}:{placed.year}"
    if not any(sp.id == sid for sp, _ in out.missing):
        out.missing.append((
            undetermined(sid, Means.JUDGMENT, {"kind": K_DEP_CHOICE, "person": pid, "tax_year": placed.year, "入力": ANNUAL_LIMIT_OPEN}, ("上限まで", "上限を超えて")),
            side,
        ))
