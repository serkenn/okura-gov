"""規則モジュール juminzei の入力：中間表現と問いの時点（年度）・注入データから入力変数を書く（registry.YearContext）。

- 年度 F の窓口（ctx.window("住民税", "年度")）がない situation（所得税の年分だけ）では、全員に仮の値を書く（値は使われない）。
- 市町村・道府県のデータは注入データ（injection_points）。未注入で候補があれば候補の全部で評価し、候補がなければ値を0にして missing を付ける
  （依存する値は未確定。既定値で計算しない：D19）。住所のない人には注入の1か所を置かない（その人の税額は注入データによらない）。
- 道府県の注入データは、住所（家屋敷）の市町村の団体コードから求めた都道府県の団体コード（第1・2桁＋000＋検査数字：calc.prefecture_code。
  総務省「全国地方公共団体コード仕様」5・6.1）を issuer.code にした prefecture の項目で引く（2026-11-12。README §5）。
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ...basis import BasisEntry, BasisType, ReadingFlag, SourceKind
from ...candidates import Candidate
from ...registry import (
    DecisionSlot,
    DecisionSpec,
    InjectionSlot,
    InjectionSpec,
    ModuleInputs,
    RecordKind,
    YearContext,
    heads,
    injection_key,
    overlaps_year,
)
from ...result import Means, OutOfScopeCategory, OutOfScopeReason, Split, State
from .calc import NO_DOMICILE, prefecture_code
from .tokutei import resident_specific_slots, resident_specific_value

# 注入点
P_KYUCHI = "住民税.級地"
P_HIKAZEI = "住民税.均等割の非課税の額"
P_KINTO = "住民税.均等割の税率"
P_SHOTOKU = "住民税.所得割の税率"
P_TIMING = "住民税.135万円の非課税の判定の時点"
P_JOREI = "住民税.条例で定める寄附金"
P_KEIGEN = "住民税.均等割の軽減"
P_UNYO = "住民税.家屋敷課税の運用"
#: 住民税.家屋敷課税の運用 の型 B（熊本市の運用：docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §3.2）。
UNYO_B = "配偶者が住所地として課税されていなければ課す"


def issuer_code(kind: str, municipality_code: str) -> str:
    """市町村の団体コードから、注入データを引く団体のコード（municipality はそのまま、prefecture は属する都道府県のコード）。

    検査数字が仕様で決まらない第1・2桁（00）は、どの注入データにも当たらないコードにする（その値は未確定：決める手段は注入）。
    """
    if kind != "prefecture":
        return municipality_code
    try:
        return prefecture_code(municipality_code)
    except ValueError:
        return municipality_code[:2] + "000?"

# 判断・選択の種類
J_YASHIKI = "判断.家屋敷・事務所に当たる"
J_DONATION = "判断.寄附の性質"
J_LARGE = "判断.大口株主等"
C_ONESTOP = "選択.ワンストップ特例"
C_STOCK = "選択.株式等の申告"
#: 住民税の申告の選択（VOC C-14。2026-11-12。JM-39）：その年度分の住民税の申告書を提出するか（file_resident_tax_return）だけを読む。
#: 徴収の方法（collection_method_other_income）は税額を変えないので読まない。特定支出控除（specific_expense_deduction）は 2026-11-12 の2回目から
#: 段 住民税の特定支出控除の申告（tokutei.py。地方税法第313条第11項：README §7 の JM-41）が読む。
C_RESIDENT_RETURN = "選択.住民税の申告"
#: 市町村・保険者の個別の処分（VOC F-D19）のうち、住民税を課す市町村を決めるもの（第294条第3項・第4項）。
AUTHORITY_NON_RECORD_TAXATION = "taxation_at_non_resident_record_municipality"
#: 2026-11-12：処分の税目（authority_decision の tax_item）。このモジュールは個人住民税の処分（住民票と違う市町村での課税・減免）だけを読む
#: （国保料〔税〕の処分は kokuho。docs/hypotheses/20261112_impl-research8_tokutei-shishutsu-reading.md H8）。
AUTHORITY_TAX_ITEM = "resident_tax"
#: 市町村民税の減免の承認（第323条。道府県民税は第45条で同じ割合で減免されたものとする：docs/public-sources/20261112_impl-research8_tokutei-shishutsu-laws.md §8）
AUTHORITY_REDUCTION = "reduction_approved"
V_REDUCTION = "住民税_減免の承認があるか"
AUTHORITY_DECISION_REASON = (
    "入力の不足・矛盾：住民票と違う市町村での課税の決定（authority_decision の taxation_at_non_resident_record_municipality）に、"
    "決定した市町村の団体コード（attributes.municipality_code）がない、又は処分をした者（authority）が市町村でない（第294条第3項：記録を直せば決まる）"
)

RECORD_KINDS = frozenset(
    {
        "resident_record",
        "municipal_tax_domicile",
        "public_assistance",
        "residence_property",
        "residence_status",
        "donation",
        "legal_sex",
        # 2026-11-12（JM-33）：地令46の3① の区分（1月1日の給与・公的年金等の支払者）
        "jan1_payer_status",
        # 2026-11-12（JM-32・JM-33）：住民税の申告書（雑損失の繰越の記録・扶養の記載）、地令46の5 の申請書、給与支払報告書・公的年金等支払報告書
        RecordKind(
            "filed_document",
            "document_type",
            frozenset({"resident_tax_return", "local_tax_order_46_5_application", "salary_payment_report", "public_pension_payment_report"}),
        ),
        # 2026-11-12（JM-38）：住民票と違う市町村での課税の決定（第294条第3項・第4項）。2026-11-12 の2回目（JM-40）：税目（tax_item）で絞り、
        # 住民税の減免の承認（第323条）も読む。国保の処分は kokuho。処分の種類と税目の組合せは okura_ir の検査が止める
        RecordKind("authority_decision", "tax_item", frozenset({AUTHORITY_TAX_ITEM})),
    }
)

#: 賦課期日の判定の時点の候補の値（injection_points の 住民税.135万円の非課税の判定の時点）。
TIMING_JAN1 = "賦課期日（1月1日）"
TIMING_DEC31 = "前年の12月31日"


def _d(s: str | None) -> _dt.date | None:
    return _dt.date.fromisoformat(s) if s else None


def covers(when: Mapping[str, Any] | None, on: _dt.date) -> bool:
    """記録の when（区間・日）が日 on を含むか（区間は両端を含み、to_on がなければ続いている）。"""
    if not when:
        return False
    if "on" in when:
        return _d(when["on"]) == on
    a = _d(when.get("from_on"))
    b = _d(when.get("to_on"))
    return (a is None or a <= on) and (b is None or on <= b)


def _reason(text: str, ids: Iterable[str] = ()) -> OutOfScopeReason:
    return OutOfScopeReason(OutOfScopeCategory.NOT_IMPLEMENTED, text, tuple(sorted(set(ids))))


def _states(records: Iterable[Mapping[str, Any]]) -> frozenset[State]:
    return frozenset(State.from_mark(r["mark"]) for r in records if "mark" in r)


def _missing(sid: str, means: Means, target: Mapping[str, Any]) -> Split:
    return Split(id=sid, means=means, target=dict(target), candidates=(), splits_conclusion=True)


def age_at_end_of(birth: _dt.date, on: _dt.date) -> int:
    """日 on の終了時の年齢（年齢計算ニ関スル法律・民法第143条：誕生日の前日の終了時に加齢する）。"""
    nxt = on + _dt.timedelta(days=1)
    return nxt.year - birth.year - ((nxt.month, nxt.day) < (birth.month, birth.day))


# ---------------------------------------------------------------------------
# 住所
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Domicile:
    """日 on の住所の市町村（なければ空）、使った記録、決まらないときの理由。"""

    code: str
    record_ids: tuple[str, ...]
    states: frozenset[State]
    known: bool  # 住所の記録（又は国外・死亡で住所がないこと）が分かるか
    conflict: str | None = None


def domicile_on(ctx: YearContext, pid: str, on: _dt.date, fiscal_year: int) -> Domicile:
    """日 on（賦課期日）の住所の市町村（第294条第2項〜第4項）。

    - municipal_tax_domicile（その年度、basis が resident_record・decided_different_from_resident_record）があればそれ（第3項・第4項の課税の決定を含む）。
      市町村の処分 authority_decision（その年度、decision が taxation_at_non_resident_record_municipality）も課税の決定として同じに扱う（2026-11-12）。
    - なければ resident_record のうち on を含むもの（住民基本台帳に記録されている市町村）。
    - 死亡日が on より前・判断.住所の所在 が foreign（on を含む）なら住所はない（known）。記録がなければ known=False。
    """
    death = ctx.death_on(pid)
    if death is not None and death < on:
        return Domicile("", (), frozenset(), True)
    doms = [
        r for r in ctx.records("municipal_tax_domicile")
        if r["roles"].get("person") == pid and r.get("when", {}).get("fiscal_year") == fiscal_year and r["attributes"]["basis"] != "house_or_office"
    ]
    # 2026-11-12（VOC F-D19。JM-38）：市町村の処分「住民票と違う市町村での課税の決定」（第294条第3項・第4項）も同じ扱い
    decided = [
        r for r in ctx.records("authority_decision")
        if r["roles"].get("person") == pid and r.get("when", {}).get("fiscal_year") == fiscal_year
        and r["attributes"]["decision"] == AUTHORITY_NON_RECORD_TAXATION and r["attributes"].get("tax_item") == AUTHORITY_TAX_ITEM
    ]
    bad = [r for r in decided if r["attributes"].get("authority") != "municipality" or not r["attributes"].get("municipality_code")]
    if bad:
        return Domicile("", tuple(sorted(r["id"] for r in bad)), _states(bad), True, AUTHORITY_DECISION_REASON)
    doms += decided
    if doms:
        codes = {r["attributes"]["municipality_code"] for r in doms}
        ids = tuple(sorted(r["id"] for r in doms))
        if len(codes) > 1:
            return Domicile("", ids, _states(doms), True, "住民税を課す市町村（municipal_tax_domicile・authority_decision の課税の決定）がその年度に2つ以上ある")
        return Domicile(codes.pop(), ids, _states(doms), True)
    recs = [r for r in ctx.records("resident_record") if r["roles"].get("person") == pid and covers(r.get("when"), on)]
    if recs:
        codes = {r["attributes"]["municipality_code"] for r in recs}
        ids = tuple(sorted(r["id"] for r in recs))
        if len(codes) > 1:
            return Domicile("", ids, _states(recs), True, "その日の住民票の記録（resident_record）が2つ以上の市町村にある")
        return Domicile(codes.pop(), ids, _states(recs), True)
    abroad = [j for j in ctx.judgments("判断.住所の所在") if j["subject"].get("person") == pid and covers(j.get("when"), on)]
    if abroad and all(j["value"] == "foreign" for j in abroad):
        return Domicile("", tuple(sorted(j["id"] for j in abroad)), _states(abroad), True)
    return Domicile("", (), frozenset(), False)


def reduction_records(ctx: YearContext, pid: str, fiscal_year: int) -> list[Mapping[str, Any]]:
    """その年度の住民税の減免の承認（authority_decision の reduction_approved・税目 resident_tax。第323条・第45条。2026-11-12、JM-40）。

    減免は条例の定めによる個別の処分で、額は記録にない。税額は減免の前の額のまま出し、住民税_減免の承認があるか で承認があることを示す
    （減免の後の額を推し量らない：SCOPE §2-4。国保の 国保_減免の承認があるか と同じ扱い）。
    """
    return [
        r for r in ctx.records("authority_decision")
        if r["roles"].get("person") == pid and r.get("when", {}).get("fiscal_year") == fiscal_year
        and r["attributes"]["decision"] == AUTHORITY_REDUCTION and r["attributes"].get("tax_item") == AUTHORITY_TAX_ITEM
    ]  # fmt: skip


def _assistance_on(ctx: YearContext, pid: str, on: _dt.date) -> list[Mapping[str, Any]]:
    return [
        r for r in ctx.records("public_assistance")
        if r["roles"].get("person") == pid and r["attributes"].get("assistance") == "livelihood_assistance" and covers(r.get("when"), on)
    ]


# ---------------------------------------------------------------------------
# 家屋敷（判断.家屋敷・事務所に当たる）
# ---------------------------------------------------------------------------


def yashiki_key(pid: str, property_id: str, on: _dt.date) -> str:
    return f"{pid}:{property_id}:{on.isoformat()}"


def _properties(ctx: YearContext, pid: str, on: _dt.date) -> list[Mapping[str, Any]]:
    """賦課期日に持つ（所有・賃借する）住宅・事務所（residence_property の holder）。"""
    return [r for r in ctx.records("residence_property") if r["roles"].get("holder") == pid and covers(r.get("when"), on)]


def yashiki_slots(ctx: YearContext) -> list[DecisionSlot]:
    w = ctx.window("住民税", "年度")
    if w is None:
        return []
    on = w.date("賦課期日")
    out: list[DecisionSlot] = []
    for pid in ctx.persons:
        home = domicile_on(ctx, pid, on, w.time.value)
        for prop in _properties(ctx, pid, on):
            if prop["attributes"]["municipality_code"] == home.code:
                continue
            pr = prop["id"]
            out.append(
                DecisionSlot(
                    key=yashiki_key(pid, pr, on),
                    target={"person": pid, "property_id": pr, "on": on.isoformat()},
                    matches=lambda j, pid=pid, pr=pr, on=on: j["subject"].get("person") == pid and j["subject"].get("property_id") == pr and covers(j.get("when"), on),
                    year_filter=False,
                    persons=(pid,),
                )
            )
    return out


# ---------------------------------------------------------------------------
# 申告特例（選択.ワンストップ特例）
# ---------------------------------------------------------------------------

ONESTOP_CANDIDATES = (Candidate(True, "申告特例を求めた"), Candidate(False, "申告特例を求めていない"))


def _local_donations(ctx: YearContext, pid: str) -> list[Mapping[str, Any]]:
    return [
        r for r in ctx.records("donation")
        if r["roles"].get("donor") == pid and overlaps_year(r.get("when"), ctx.year) and r["attributes"].get("recipient_type") == "local_government"
    ]


def _filed_returns(ctx: YearContext, pid: str, fiscal_year: int | None) -> list[Mapping[str, Any]]:
    """申告特例がなかったものとみなされる申告書（前年分の確定申告書〔準確定を含む〕・その年度分の住民税の申告書：附則第7条第13項第2号）。"""
    out = []
    for r in ctx.records("filed_document"):
        if r["roles"].get("filer") != pid:
            continue
        a = r["attributes"]
        if a["document_type"] in ("final_return", "quasi_final_return", "loss_return") and a.get("tax_year") == ctx.year:
            out.append(r)
        elif a["document_type"] == "resident_tax_return" and fiscal_year is not None and a.get("fiscal_year") == fiscal_year:
            out.append(r)
    return out


def onestop_slots(ctx: YearContext) -> list[DecisionSlot]:
    w = ctx.window("住民税", "年度")
    if w is None:
        return []
    out: list[DecisionSlot] = []
    for pid in ctx.persons:
        if not _local_donations(ctx, pid) or _filed_returns(ctx, pid, w.time.value):
            continue
        out.append(
            DecisionSlot(
                key=f"{pid}:{ctx.year}",
                target={"person": pid, "tax_year": ctx.year},
                matches=lambda c, pid=pid: c["subject"].get("person") == pid,
                candidates=ONESTOP_CANDIDATES,
                persons=(pid,),
            )
        )
    return out


def _onestop_value(rec: Mapping[str, Any]) -> Any:
    return bool(rec["value"].get("apply"))


RESIDENT_RETURN_CANDIDATES = (
    Candidate(False, "その年度分の住民税の申告書を提出しない"),
    Candidate(True, "その年度分の住民税の申告書を提出する"),
)


def resident_return_slots(ctx: YearContext) -> list[DecisionSlot]:
    """選択.住民税の申告（file_resident_tax_return）の1か所（2026-11-12。JM-39）。

    住民税の申告書の提出は申告特例をなかったものとみなす（附則第7条第13項第2号）。申告特例の1か所と同じ人（地方団体への寄附があり、
    確定申告書・住民税の申告書の提出の記録がない人）に置き、申告特例を求めた候補でだけ読む（読んだときだけ開く：DecisionSlot.lazy）。
    """
    w = ctx.window("住民税", "年度")
    if w is None:
        return []
    fy = w.time.value
    out: list[DecisionSlot] = []
    for pid in ctx.persons:
        if not _local_donations(ctx, pid) or _filed_returns(ctx, pid, fy):
            continue
        out.append(
            DecisionSlot(
                key=f"{pid}:{fy}",
                target={
                    "person": pid,
                    "fiscal_year": fy,
                    "決めるもの": "その年度分の住民税の申告書を提出するか（選択.住民税の申告 の file_resident_tax_return。提出すれば申告特例はなかったものとみなす）",
                },
                matches=lambda c, pid=pid, fy=fy: (
                    c["subject"].get("person") == pid
                    and c.get("when", {}).get("fiscal_year") == fy
                    and "file_resident_tax_return" in c["value"]
                ),
                candidates=RESIDENT_RETURN_CANDIDATES,
                persons=(pid,),
                lazy=True,
            )
        )
    return out


def _resident_return_value(rec: Mapping[str, Any]) -> Any:
    return bool(rec["value"].get("file_resident_tax_return"))


# ---------------------------------------------------------------------------
# 注入データの1か所
# ---------------------------------------------------------------------------


def _municipalities(ctx: YearContext) -> tuple[_dt.date, _dt.date, dict[str, str]] | None:
    """（賦課期日、前年の12月31日、人 → 注入データを引く市町村〔住所地と家屋敷のある市町村〕）。"""
    w = ctx.window("住民税", "年度")
    if w is None:
        return None
    on = w.date("賦課期日")
    out: dict[str, str] = {}
    for pid in ctx.persons:
        d = domicile_on(ctx, pid, on, w.time.value)
        if d.code:
            out[f"{pid}:住所"] = d.code
        for prop in _properties(ctx, pid, on):
            code = prop["attributes"]["municipality_code"]
            if code != d.code:
                out[f"{pid}:家屋敷:{code}"] = code
        for r in ctx.records("municipal_tax_domicile"):
            if r["roles"].get("person") == pid and r.get("when", {}).get("fiscal_year") == w.time.value and r["attributes"]["basis"] == "house_or_office":
                code = r["attributes"]["municipality_code"]
                if code != d.code:
                    out[f"{pid}:家屋敷:{code}"] = code
    return on, w.date("前年の12月31日"), out


def place_persons(places: Mapping[str, str]) -> dict[str, tuple[str, ...]]:
    """市町村 → その市町村の注入データを引く人（_municipalities のキー「<人>:住所」「<人>:家屋敷:<市町村>」から）。

    2026-11-13：市町村・道府県の注入データの1か所（級地・判定の時点・税率・非課税の額・軽減）に、関係する人（InjectionSlot.persons）として
    宣言する。build_inputs は人ごとに、その人の住所の市町村（home.code）の注入データだけを読む（_municipal_inputs・_minor）ので、
    ある人の入力は、ほかの人だけが住む市町村の注入データに依存しない。宣言がないと、候補の評価の安全側の決め方（evaluate の causal_deps）が
    全員の入力を全部の市町村の候補に依存させ、家族が4つの市町村に住むだけで候補の組合せの上限を超えた
    （docs/measurements/20261113_family-run_findings.md の B1）。
    """
    out: dict[str, set[str]] = {}
    for key, code in places.items():
        suffix = ":住所" if key.endswith(":住所") else f":家屋敷:{code}"
        out.setdefault(code, set()).add(key[: -len(suffix)])
    return {c: tuple(sorted(ps)) for c, ps in out.items()}


def municipal_slots(places: Mapping[str, str], kinds: tuple[str, ...], on: _dt.date, keep: Any = None) -> list[InjectionSlot]:
    """人 → 市町村（_municipalities）から、団体（市町村・その道府県）ごとの注入データの1か所を作る。関係する人は、その団体の区域の
    市町村の注入データを引く人（place_persons。道府県は区域内の市町村の人の和）。keep(kind, 団体のコード) が偽の団体は作らない。"""
    persons: dict[str, set[str]] = {}
    slots: dict[str, tuple[str, str, Mapping[str, Any]]] = {}
    for code, ps in sorted(place_persons(places).items()):
        for kind in kinds:
            ic = issuer_code(kind, code)
            if keep is not None and not keep(kind, ic):
                continue
            key = injection_key(kind, ic, on)
            slots.setdefault(key, (kind, ic, {"市町村": code} if kind == "municipality" else {"道府県": ic}))
            persons.setdefault(key, set()).update(ps)
    return [InjectionSlot(k, kind, ic, on, target=target, persons=tuple(sorted(persons[k]))) for k, (kind, ic, target) in sorted(slots.items())]


def _slots_for(point: str, kinds: tuple[str, ...], date_name: str, *, only_injected: bool = False) -> Any:
    def slots(ctx: YearContext) -> list[InjectionSlot]:
        got = _municipalities(ctx)
        if got is None:
            return []
        jan1, dec31, places = got
        on = jan1 if date_name == "賦課期日" else dec31
        keep = (lambda kind, ic: ctx.injected.find(point, kind, ic, on) is not None) if only_injected else None
        return municipal_slots(places, kinds, on, keep)

    return slots


#: 特例控除対象寄附金の指定（総務大臣。地方税法第314条の7第2項）：寄附先の団体ごと・寄附をした日の1か所（2026-11-11）。
P_DESIGNATION = "住民税.特例控除対象寄附金の指定"


def designation_key(donation: Mapping[str, Any]) -> tuple[str, str, _dt.date] | None:
    """寄附先の団体（種類・コード）と寄附をした日。中間表現に寄附先の団体コードがなければ None。"""
    a = donation["attributes"]
    code, kind = a.get("recipient_local_government_code"), a.get("recipient_local_government_kind")
    on = donation.get("when", {}).get("on")
    if not code or not kind or not on:
        return None
    return kind, code, _dt.date.fromisoformat(on)


def _designation_slots(ctx: YearContext) -> list[InjectionSlot]:
    if ctx.window("住民税", "年度") is None:
        return []
    out: dict[str, InjectionSlot] = {}
    for pid in ctx.persons:
        for r in _local_donations(ctx, pid):
            k = designation_key(r)
            if k is None:
                continue
            kind, code, on = k
            key = injection_key(kind, code, on)
            if key in out:
                out[key] = InjectionSlot(key, kind, code, on, target=out[key].target, persons=tuple(sorted({*(out[key].persons or ()), pid})))
            else:
                out[key] = InjectionSlot(key, kind, code, on, target={"寄附先の団体": code}, persons=(pid,))
    return [out[k] for k in sorted(out)]


#: 第314条の7第1項の寄附先の種類：第2号（共同募金会・日本赤十字社）と、第3号・第4号（条例で定めるもの）に当たりうるもの。
CHEST_TYPES = frozenset({"community_chest", "japanese_red_cross"})
NOT_DONATION_TYPES = frozenset({"political_party", "national_government"})


def _other_donations(ctx: YearContext, pid: str) -> list[Mapping[str, Any]]:
    """第1号（都道府県等）でも政党等・国でもない寄附金（第2号〜第4号に当たりうるもの）。"""
    return [
        r for r in ctx.records("donation")
        if r["roles"].get("donor") == pid and overlaps_year(r.get("when"), ctx.year)
        and r["attributes"].get("recipient_type") not in NOT_DONATION_TYPES | {"local_government"}
    ]


def _jorei_slots(ctx: YearContext) -> list[InjectionSlot]:
    """条例で定める寄附金（第314条の7第1項第3号・第4号、第37条の2第1項第3号・第4号）：住所の市町村と道府県の、賦課期日の条例。"""
    w = ctx.window("住民税", "年度")
    if w is None:
        return []
    jan1 = w.date("賦課期日")
    out: dict[str, InjectionSlot] = {}
    for pid in ctx.persons:
        if not [r for r in _other_donations(ctx, pid) if r["attributes"].get("recipient_type") not in CHEST_TYPES]:
            continue
        home = domicile_on(ctx, pid, jan1, w.time.value).code
        if not home:
            continue
        for kind in ("municipality", "prefecture"):
            ic = issuer_code(kind, home)
            key = injection_key(kind, ic, jan1)
            prev = out.get(key)
            persons = tuple(sorted({*(prev.persons or ()), pid})) if prev else (pid,)
            out[key] = InjectionSlot(key, kind, ic, jan1, target={"団体": ic}, persons=persons)
    return [out[k] for k in sorted(out)]


def _keigen_slots(ctx: YearContext) -> list[InjectionSlot]:
    """均等割の軽減（第311条）：住所の市町村の、賦課期日の条例（候補を持たない。読んだ人の値だけが未確定になる）。"""
    got = _municipalities(ctx)
    if got is None:
        return []
    jan1, _, places = got
    return municipal_slots({k: c for k, c in places.items() if k.endswith(":住所")}, ("municipality",), jan1)


def spouse_at_home(ctx: YearContext, pid: str, code: str, jan1: _dt.date, fiscal: int) -> list[str]:
    """賦課期日に市町村 code に住所を有する、pid の配偶者（家屋敷課税の運用の型 B の材料）。"""
    alive = set(ctx.persons)
    return sorted(
        s.other for s in ctx.relations.spouses(pid, jan1) if s.other in alive and domicile_on(ctx, s.other, jan1, fiscal).code == code
    )


def _unyo_slots(ctx: YearContext) -> list[InjectionSlot]:
    """家屋敷課税の運用（型 A・型 B）：家屋敷・事務所のある市町村に配偶者が住所を有するときだけ（それ以外は型によらず同じ：extra-model H2-3）。"""
    w = ctx.window("住民税", "年度")
    if w is None:
        return []
    jan1, fiscal = w.date("賦課期日"), w.time.value
    out: dict[str, InjectionSlot] = {}
    for pid in ctx.persons:
        home = domicile_on(ctx, pid, jan1, fiscal).code
        places = {prop["attributes"]["municipality_code"] for prop in _properties(ctx, pid, jan1)}
        places |= {
            r["attributes"]["municipality_code"] for r in ctx.records("municipal_tax_domicile")
            if r["roles"].get("person") == pid and r.get("when", {}).get("fiscal_year") == fiscal and r["attributes"]["basis"] == "house_or_office"
        }
        for c in sorted(places - {home}):
            sp = spouse_at_home(ctx, pid, c, jan1, fiscal)
            if not sp:
                continue
            key = injection_key("municipality", c, jan1)
            prev = out.get(key)
            persons = tuple(sorted({*(prev.persons or ()), pid, *sp})) if prev else tuple(sorted({pid, *sp}))
            out[key] = InjectionSlot(key, "municipality", c, jan1, target={"市町村": c}, persons=persons)
    return [out[k] for k in sorted(out)]


INJECTIONS: tuple[InjectionSpec, ...] = (
    InjectionSpec(P_DESIGNATION, _designation_slots),
    InjectionSpec(P_JOREI, _jorei_slots),
    InjectionSpec(P_KEIGEN, _keigen_slots),
    InjectionSpec(P_UNYO, _unyo_slots),
    InjectionSpec(P_KYUCHI, _slots_for(P_KYUCHI, ("municipality",), "前年の12月31日")),
    # 均等割の非課税の額は、注入されていればその額。なければ級地の候補から政令の基準どおりの額を作る（README §4：条例の額は
    # 級地ごとの政令の上限以下なので、候補の型「政令の基準どおり（k級地）」はその市町村の級地のものだけが当たりうる）
    InjectionSpec(P_HIKAZEI, _slots_for(P_HIKAZEI, ("municipality",), "賦課期日", only_injected=True)),
    InjectionSpec(P_KINTO, _slots_for(P_KINTO, ("municipality", "prefecture"), "賦課期日")),
    InjectionSpec(P_SHOTOKU, _slots_for(P_SHOTOKU, ("municipality", "prefecture"), "賦課期日")),
    InjectionSpec(P_TIMING, _slots_for(P_TIMING, ("municipality",), "賦課期日")),
)


# ---------------------------------------------------------------------------
# build_inputs
# ---------------------------------------------------------------------------

#: 入力変数の仮の値（窓口のない situation と、住所のない人）。
DEFAULTS: dict[str, Any] = {
    "住民税_賦課期日に住所を有する市町村": NO_DOMICILE,
    "住民税_家屋敷課税の対象か": False,
    "住民税_生活扶助を受けているか": False,
    V_REDUCTION: False,
    "住民税_未成年者か": False,
    "住民税_分離課税の退職所得の区分が決まらないか": False,
    "住民税_非課税の判定を賦課期日の現況で行うか": False,
    "住民税_賦課期日の寡婦・ひとり親の判定が決まらないか": False,
    "住民税_指定都市の区域内に住所を有するか": False,
    "住民税_市町村民税の所得割の税率の分子": 0,
    "住民税_市町村民税の所得割の税率の分母": 1,
    "住民税_道府県民税の所得割の税率の分子": 0,
    "住民税_道府県民税の所得割の税率の分母": 1,
    "住民税_市町村民税の均等割の税率": 0,
    "住民税_道府県民税の均等割の税率": 0,
    "住民税_均等割の非課税の基本額": 0,
    "住民税_均等割の非課税の加算額": 0,
    "住民税_森林環境税の非課税の基本額": 0,
    "住民税_森林環境税の非課税の加算額": 0,
    "住民税_都道府県等に対する寄附金の額": 0,
    "住民税_特例控除対象寄附金の額": 0,
    "住民税_市町村民税の第2号から第4号までの寄附金の額": 0,
    "住民税_道府県民税の第2号から第4号までの寄附金の額": 0,
    "住民税_第2号の寄附金の額": 0,
    "住民税_申告特例控除の対象か": False,
    "住民税_控除の対象の配当割額等": 0,
    "住民税_住宅借入金等特別税額控除の控除限度額に基礎控除の差を加算するか": False,
    "住民税_住宅借入金等特別税額控除の特定取得か": False,
    "住民税_法令上の性別が女性か": False,
    "住民税_退職手当等の支払を受けるべき年の1月1日に住所を有する市町村": "",
    "住民税_退職手当等の支払を受けるべき年の1月1日に生活扶助を受けているか": False,
    "住民税_扶養費の一部を負担しているか": False,
    "住民税_雑損失の繰越の記録があるか": False,
    "住民税_記録による繰り越された雑損失の金額": 0,
    "住民税_純損失の繰越の記録があるか": False,
    "住民税_記録による繰り越された純損失の金額": 0,
}


@dataclass
class _Writer:
    out: ModuleInputs
    pid: str
    done: set[str] = field(default_factory=set)

    def set(self, var: str, value: Any, ids: Iterable[str] = (), states: Iterable[State] = (), *, basis: Iterable[Any] = (), missing: Iterable[Split] = ()) -> None:
        self.out.set(var, self.pid, value, ids, states, basis=basis, missing=missing)
        self.done.add(var)

    def rest(self) -> None:
        for var, v in DEFAULTS.items():
            if var not in self.done:
                self.out.set(var, self.pid, v)
                self.done.add(var)


def _injected(ctx: YearContext, point: str, kind: str, code: str, on: _dt.date) -> Any:
    return ctx.injection(point, injection_key(kind, code, on))


def build_inputs(ctx: YearContext) -> ModuleInputs:
    out = ModuleInputs()
    w = ctx.window("住民税", "年度")
    if w is None:
        for pid in ctx.persons:
            _Writer(out, pid).rest()
        return out
    fiscal = w.time.value
    jan1 = w.date("賦課期日")
    dec31 = w.date("前年の12月31日")
    p = ctx.parameters.住民税
    for pid in ctx.persons:
        wr = _Writer(out, pid)
        home = domicile_on(ctx, pid, jan1, fiscal)
        if home.conflict:
            out.exclude(pid, _reason(home.conflict, home.record_ids), "住民税_賦課期日に住所を有する市町村")
        miss = () if home.known else (
            _missing(f"事実:賦課期日の住所:{pid}:{fiscal}", Means.FACT, {"person": pid, "賦課期日": jan1.isoformat(), "入力": "resident_record（住民票の記録）か municipal_tax_domicile"}),
        )
        wr.set("住民税_賦課期日に住所を有する市町村", home.code or NO_DOMICILE, home.record_ids, home.states, missing=miss)
        aid = _assistance_on(ctx, pid, jan1)
        wr.set("住民税_生活扶助を受けているか", bool(aid), [r["id"] for r in aid], _states(aid))
        red = reduction_records(ctx, pid, fiscal)
        wr.set(V_REDUCTION, bool(red), [r["id"] for r in red], _states(red))
        if home.code:
            _municipal_inputs(ctx, wr, pid, home.code, jan1, dec31, p)
        _minor(ctx, out, wr, pid, home.code, jan1, dec31)
        _yashiki(ctx, wr, pid, home.code, jan1, fiscal)
        _donations(ctx, out, wr, pid, fiscal, home.code, jan1)
        _withheld_local(ctx, out, wr, pid)
        _housing(ctx, out, wr, pid, fiscal)
        _sex(ctx, wr, pid, dec31)
        _retirement_domicile(ctx, wr, pid)
        _retirement_split(wr, ctx, pid)
        _fuyohi(ctx, wr, pid, dec31)
        _casualty_carry(ctx, out, wr, pid, fiscal)
        wr.rest()
    return out


# ---------------------------------------------------------------------------
# 住民税の雑損失の繰越（第313条第9項。2026-11-12、JM-32：docs/public-sources/20261112_impl-research5_juminzei-zasson-and-46-5.md §1）
# ---------------------------------------------------------------------------

CASUALTY_ITEM = "resident_tax_casualty_loss_carryforward"
V_CASUALTY_RECORDED = "住民税_雑損失の繰越の記録があるか"
V_CASUALTY_CARRIED = "住民税_記録による繰り越された雑損失の金額"
CASUALTY_ORIGIN_REASON = (
    "入力の不足・矛盾：住民税の繰り越す雑損失・純損失の金額（reported_amounts の resident_tax_casualty_loss_carryforward・resident_tax_net_loss_carryforward）に"
    "生じた年（origin_tax_year）がない、又は記録の年度の前年より後の年（第313条第8項・第9項）"
)
CASUALTY_OLD_REASON = (
    "住民税の繰り越す雑損失・純損失の金額の生じた年が前年前3年より前（特定非常災害の5年の繰越〔第314条第1項〜第4項〕は後の段：D22 S12）"
)
CASUALTY_CONTINUITY_REASON = (
    "入力の不足：住民税の雑損失・純損失の繰越は、生じた年の末日の属する年度の翌年度（青色申告書を提出した年の純損失は翌々年度）から前年度まで連続して"
    "住民税の申告書（所得税の確定申告書を出せば出したものとみなす：第317条の3）を提出している場合に限る（第313条第8項・第9項）が、その年度の申告書の記録"
    "（filed_document の resident_tax_return・final_return）がない"
)


def _filed_for_fiscal(ctx: YearContext, pid: str, fy: int) -> bool:
    """年度 fy の住民税の申告書を提出したか（住民税の申告書、又は前年分の所得税の確定申告書：第317条の2第1項・第3項・第4項、第317条の3）。"""
    for r in ctx.records("filed_document"):
        if r["roles"].get("filer") != pid:
            continue
        a = r["attributes"]
        if a["document_type"] == "resident_tax_return" and a.get("fiscal_year") == fy:
            return True
        if a["document_type"] in ("final_return", "quasi_final_return", "loss_return") and a.get("tax_year") == fy - 1:
            return True
    return False


NET_ITEM = "resident_tax_net_loss_carryforward"
V_NET_RECORDED = "住民税_純損失の繰越の記録があるか"
V_NET_CARRIED = "住民税_記録による繰り越された純損失の金額"


def _casualty_carry(ctx: YearContext, out: ModuleInputs, wr: _Writer, pid: str, fiscal: int) -> None:
    """前年度の記録（fiscal_year が年度の前年度の書類）の、住民税の所得割の計算で控除しきれず繰り越す雑損失・純損失の金額。前年前3年内（生じた年が
    前年の3年前〜前年）に生じたものの合計。申告書を連続して提出していること：雑損失は生じた年の翌年度から（第313条第9項）、青色申告書を提出した年の
    純損失は翌々年度から（第8項。青色申告書の提出と変動所得・被災事業用資産の損失の区分は記録の約束：記録した額を繰り越された額とする）。"""
    _loss_carry(ctx, out, wr, pid, fiscal, CASUALTY_ITEM, V_CASUALTY_RECORDED, V_CASUALTY_CARRIED, 1)
    _loss_carry(ctx, out, wr, pid, fiscal, NET_ITEM, V_NET_RECORDED, V_NET_CARRIED, 2)


def _loss_carry(
    ctx: YearContext, out: ModuleInputs, wr: _Writer, pid: str, fiscal: int, item_name: str, v_recorded: str, v_carried: str, first_offset: int
) -> None:
    prev = fiscal - 1
    rows = []
    for r in ctx.records("filed_document"):
        if r["roles"].get("filer") != pid or r["attributes"].get("fiscal_year") != prev:
            continue
        for item in r["attributes"].get("reported_amounts", ()):
            if item["item"] == item_name:
                rows.append((r["id"], item))
    if not rows:
        return
    ids = [rid for rid, _ in rows]
    total = 0
    for rid, item in rows:
        origin = item.get("origin_tax_year")
        if origin is None or origin > ctx.year - 1:
            out.exclude(pid, _reason(CASUALTY_ORIGIN_REASON, [rid]), v_carried)
            continue
        if origin < ctx.year - 3:
            if item["amount"]:
                out.exclude(pid, OutOfScopeReason(OutOfScopeCategory.OUT_OF_RANGE, CASUALTY_OLD_REASON, (rid,)), v_carried)
            continue
        missing = [fy for fy in range(origin + first_offset, fiscal) if not _filed_for_fiscal(ctx, pid, fy)]
        if missing:
            out.exclude(pid, _reason(CASUALTY_CONTINUITY_REASON + f"（年度 {missing}）", [rid]), v_carried)
            continue
        total += max(0, int(item["amount"]))
    wr.set(v_recorded, True, ids)
    wr.set(v_carried, total, ids)


def _municipal_inputs(ctx: YearContext, wr: _Writer, pid: str, code: str, jan1: _dt.date, dec31: _dt.date, p: Any) -> None:
    """住所地の市町村・道府県の注入データ（所得割の税率・均等割の税率・均等割の非課税・級地）。"""
    m = _injected(ctx, P_SHOTOKU, "municipality", code, jan1)
    pref = _injected(ctx, P_SHOTOKU, "prefecture", issuer_code("prefecture", code), jan1)
    designated_missing: tuple[Split, ...] = ()
    designated = False
    if m.value is not None:
        if "指定都市" in m.value:
            designated = bool(m.value["指定都市"])
        else:
            designated_missing = (
                _missing(f"注入:住民税.所得割の税率:指定都市:{code}", Means.INJECTION, {"注入点": P_SHOTOKU, "団体": {"kind": "municipality", "code": code}, "欄": "指定都市"}),
            )
    wr.set("住民税_指定都市の区域内に住所を有するか", designated, m.record_ids, m.states, basis=m.basis, missing=tuple(m.missing) + designated_missing)
    num, den = (0, 1) if m.value is None else (int(m.value["税率"]["num"]), int(m.value["税率"]["den"]))
    wr.set("住民税_市町村民税の所得割の税率の分子", num, m.record_ids, m.states, basis=m.basis, missing=m.missing)
    wr.set("住民税_市町村民税の所得割の税率の分母", den, m.record_ids, m.states, basis=m.basis, missing=m.missing)
    pmiss: tuple[Split, ...] = tuple(pref.missing) + designated_missing
    pnum, pden = 0, 1
    if pref.value is not None:
        field_name = "指定都市の区域内に住所を有する者の税率" if designated else "税率"
        if field_name in pref.value:
            pnum, pden = int(pref.value[field_name]["num"]), int(pref.value[field_name]["den"])
        else:
            pc = issuer_code("prefecture", code)
            pmiss += (_missing(f"注入:住民税.所得割の税率:{field_name}:{pc}", Means.INJECTION, {"注入点": P_SHOTOKU, "団体": {"kind": "prefecture", "code": pc}, "欄": field_name}),)
    wr.set("住民税_道府県民税の所得割の税率の分子", pnum, pref.record_ids, pref.states, basis=pref.basis, missing=pmiss)
    wr.set("住民税_道府県民税の所得割の税率の分母", pden, pref.record_ids, pref.states, basis=pref.basis, missing=pmiss)
    for kind, var in (("municipality", "住民税_市町村民税の均等割の税率"), ("prefecture", "住民税_道府県民税の均等割の税率")):
        d = _injected(ctx, P_KINTO, kind, issuer_code(kind, code), jan1)
        rate = 0 if d.value is None else int(d.value["税率"])
        wr.set(var, rate, d.record_ids, d.states, basis=d.basis, missing=d.missing)
    base, add, ids, states, basis = exemption_amounts(ctx, code, jan1, dec31, p)
    wr.set("住民税_均等割の非課税の基本額", base, ids, states, basis=basis)
    wr.set("住民税_均等割の非課税の加算額", add, ids, states, basis=basis)
    k = _injected(ctx, P_KYUCHI, "municipality", code, dec31)
    rate = p.森林環境税.非課税.級地の率[_kyuchi_node(k.value["級地"])]
    f_base = int(p.森林環境税.非課税.基本額) * int(rate.分子) // int(rate.分母)
    f_add = int(p.森林環境税.非課税.加算額) * int(rate.分子) // int(rate.分母)
    kb = tuple(k.basis) + (ctx.parameter_basis("住民税.森林環境税.非課税.基本額"),)
    wr.set("住民税_森林環境税の非課税の基本額", f_base, k.record_ids, k.states, basis=kb)
    wr.set("住民税_森林環境税の非課税の加算額", f_add, k.record_ids, k.states, basis=kb)


def _kyuchi_node(label: str) -> str:
    return {"1級地": "一級地", "2級地": "二級地", "3級地": "三級地"}[label]


def exemption_amounts(ctx: YearContext, code: str, jan1: _dt.date, dec31: _dt.date, p: Any) -> tuple[int, int, tuple[str, ...], frozenset[State], tuple[Any, ...]]:
    """均等割の非課税の基本額・加算額：注入されていればその額、なければ級地（候補）と政令の基準（35万円・21万円×級地の率）から。"""
    entry = ctx.injected.find(P_HIKAZEI, "municipality", code, jan1)
    if entry is not None:
        d = ctx.injection(P_HIKAZEI, injection_key("municipality", code, jan1))
        return int(d.value["基本額"]), int(d.value["加算額"]), d.record_ids, d.states, tuple(d.basis)
    k = _injected(ctx, P_KYUCHI, "municipality", code, dec31)
    q = p.非課税.均等割
    rate = q.級地の率[_kyuchi_node(k.value["級地"])]
    base = int(q.基本額の上限) * int(rate.分子) // int(rate.分母)
    add = int(q.加算額の上限) * int(rate.分子) // int(rate.分母)
    return base, add, k.record_ids, k.states, tuple(k.basis) + (ctx.parameter_basis("住民税.非課税.均等割.基本額の上限"),)


#: 判定の時点が賦課期日の候補で、前年の12月31日と賦課期日の間に変わりうる事実（障害・婚姻・性別）の記録の種類。
_EVENT_KINDS = ("disability_basis", "civil_status", "legal_sex")


def _minor(ctx: YearContext, out: ModuleInputs, wr: _Writer, pid: str, code: str, jan1: _dt.date, dec31: _dt.date) -> None:
    """第295条第1項第2号の未成年者（民法第4条：18歳）。判定の時点は注入データ（未注入なら賦課期日・前年の12月31日の両方）。"""
    birth = ctx.birth_on(pid)
    if not code:
        wr.set("住民税_未成年者か", age_at_end_of(birth, jan1) < 18)
        return
    t = ctx.injection(P_TIMING, injection_key("municipality", code, jan1))
    on = jan1 if t.value["時点"] == TIMING_JAN1 else dec31
    wr.set("住民税_未成年者か", age_at_end_of(birth, on) < 18, t.record_ids, t.states, basis=t.basis)
    # 判定の時点を賦課期日とする候補：障害者は personal_deductions の窓口（翌年1月1日の障害者・婚姻の現況）で判定する（2026-11-12。JM-03）。
    # 婚姻・事実婚が賦課期日に始まる人は寡婦・ひとり親に当たらない（窓口の値で決まる）。賦課期日の前日に婚姻・事実婚が終わった人・性別が変わる人は、
    # 寡婦の扶養親族・ひとり親の子の要件を賦課期日に何で判定するか（所得税の割当ては前年の12月31日）を定めた一次情報がないので分かれ目（一次情報）
    wr.set("住民税_非課税の判定を賦課期日の現況で行うか", on == jan1, t.record_ids, t.states, basis=t.basis)
    ended = _ended_before_jan1(ctx, pid, jan1, dec31) if on == jan1 else []
    miss = () if not ended else (
        _missing(
            f"一次情報:賦課期日に婚姻が終わった人の寡婦・ひとり親:{pid}:{jan1.year}",
            Means.PRIMARY_SOURCE,
            {"person": pid, "記録": ended, "事項": "前年の12月31日に婚姻・事実婚が終わった（性別が変わった）人の、賦課期日の現況による寡婦の扶養親族・ひとり親の子の要件の判定"
             "（所得税の扶養の割当ては前年の12月31日の現況。賦課期日の割当てを定めた一次情報がない）"},
        ),
    )
    wr.set("住民税_賦課期日の寡婦・ひとり親の判定が決まらないか", bool(ended), ended, missing=miss)


def _ended_before_jan1(ctx: YearContext, pid: str, jan1: _dt.date, dec31: _dt.date) -> list[str]:
    """前年の12月31日に婚姻が終わる（終わりの日・配偶者の死亡の日が12月31日）、住民票の記録が12月31日で終わる（事実婚の記載が変わりうる）、
    法令上の性別の記録の境が賦課期日にある記録の ID（寡婦・ひとり親の本人の要件が賦課期日に新たに満たされうる）。"""
    deaths = {p["id"]: p.get("death_on") for p in ctx.ir["persons"]}
    out: list[str] = []
    for r in ctx.records("marriage"):
        roles = r.get("roles", {})
        if pid not in roles.values():
            continue
        other = next((v for v in roles.values() if v != pid), None)
        if (r.get("when") or {}).get("to_on") == dec31.isoformat() or deaths.get(other) == dec31.isoformat():
            out.append(r["id"])
    for kind in ("resident_record", "legal_sex"):
        for r in ctx.records(kind):
            if r.get("roles", {}).get("person") != pid:
                continue
            wh = r.get("when") or {}
            if wh.get("to_on") == dec31.isoformat() or (kind == "legal_sex" and wh.get("from_on") == jan1.isoformat()):
                out.append(r["id"])
    return sorted(out)


@dataclass(frozen=True)
class YashikiHits:
    """家屋敷課税の材料：家屋敷・事務所のある市町村（住所地を除く）→ 記録の ID、使った記録・判断の ID と状態。"""

    by_municipality: Mapping[str, tuple[str, ...]]
    record_ids: tuple[str, ...]
    states: frozenset[State]


def yashiki_hits(ctx: YearContext, pid: str, code: str, jan1: _dt.date, fiscal: int) -> YashikiHits:
    """家屋敷課税（第294条第1項第2号）：住所のない市町村に持つ住宅・事務所のうち、判断.家屋敷・事務所に当たる（未入力なら両方）ものと、
    municipal_tax_domicile（house_or_office：市町村の課税の決定）。code は賦課期日の住所の市町村（なければ空）。"""
    hits: dict[str, list[str]] = {}
    ids: list[str] = []
    states: set[State] = set()
    for prop in _properties(ctx, pid, jan1):
        c = prop["attributes"]["municipality_code"]
        if c == code:
            continue
        d = ctx.decision(J_YASHIKI, yashiki_key(pid, prop["id"], jan1))
        ids += [prop["id"], *d.record_ids]
        states |= set(d.states) | set(_states([prop]))
        if d.value is True:
            hits.setdefault(c, []).append(prop["id"])
    for r in ctx.records("municipal_tax_domicile"):
        if r["roles"].get("person") == pid and r.get("when", {}).get("fiscal_year") == fiscal and r["attributes"]["basis"] == "house_or_office":
            c = r["attributes"]["municipality_code"]
            if c != code:
                hits.setdefault(c, []).append(r["id"])
                ids.append(r["id"])
    return YashikiHits({c: tuple(v) for c, v in sorted(hits.items())}, tuple(ids), frozenset(states))


def _yashiki(ctx: YearContext, wr: _Writer, pid: str, code: str, jan1: _dt.date, fiscal: int) -> None:
    """家屋敷課税の対象か（市町村ごとの均等割の額は段 住民税の均等割 が書く：kintowari.py）。"""
    h = yashiki_hits(ctx, pid, code, jan1, fiscal)
    wr.set("住民税_家屋敷課税の対象か", bool(h.by_municipality), h.record_ids, h.states)


def _donations(ctx: YearContext, out: ModuleInputs, wr: _Writer, pid: str, fiscal: int, home: str, jan1: _dt.date) -> None:
    """前年中に支出した寄附金（第314条の7第1項）。都道府県等（第1号）・特例控除対象寄附金（総務大臣の指定）・第2号〜第4号に当たるもの。"""
    recs = [r for r in ctx.records("donation") if r["roles"].get("donor") == pid and overlaps_year(r.get("when"), ctx.year)]
    nature = {j["subject"]["donation_id"]: j for j in heads(ctx.judgments(J_DONATION))}
    first: list[Mapping[str, Any]] = []
    for r in recs:
        if r["attributes"].get("recipient_type") == "local_government":
            j = nature.get(r["id"])
            if j is not None and j["value"].get("special_benefit") is True:
                continue  # 寄附者に特別の利益が及ぶもの（第1号の括弧書き）
            first.append(r)
    f_ids = [r["id"] for r in first] + [nature[r["id"]]["id"] for r in first if r["id"] in nature]
    total_first = sum(int(r["amounts"]["amount"]) for r in first)
    wr.set("住民税_都道府県等に対する寄附金の額", total_first, f_ids, _states(first))
    # 特例控除対象寄附金：寄附先の団体ごとの総務大臣の指定（注入点 住民税.特例控除対象寄附金の指定。未注入なら指定の有無の両方で評価）
    total_special = 0
    s_ids = list(f_ids)
    s_states = set(_states(first))
    s_basis: list[Any] = []
    miss: list[Split] = []
    no_code = []
    for r in first:
        k = designation_key(r)
        if k is None:
            no_code.append(r)
            continue
        d = ctx.injection(P_DESIGNATION, injection_key(*k))
        s_ids += list(d.record_ids)
        s_states |= set(d.states)
        s_basis += list(d.basis)
        miss += list(d.missing)
        if d.value is not None and d.value.get("指定") is True:
            total_special += int(r["amounts"]["amount"])
    if no_code:
        total_special += sum(int(r["amounts"]["amount"]) for r in no_code)
        miss.append(
            _missing(
                f"事実:寄附先の団体コード:{pid}:{ctx.year}",
                Means.FACT,
                {"person": pid, "寄附金": sorted(r["id"] for r in no_code), "決めるもの": "寄附先の都道府県・市町村の団体コード（donation の recipient_local_government_code・recipient_local_government_kind）。総務大臣の指定（第314条の7第2項）を注入データで引く"},
            )
        )
    wr.set("住民税_特例控除対象寄附金の額", total_special, s_ids, s_states, missing=tuple(miss), basis=s_basis)
    _other_donation_amounts(ctx, wr, pid, home, jan1)
    # 申告特例（附則第7条第8項〜第13項）
    if not first:
        wr.set("住民税_申告特例控除の対象か", False)
        return
    filed = _filed_returns(ctx, pid, fiscal)
    if filed:
        wr.set("住民税_申告特例控除の対象か", False, [r["id"] for r in filed])  # 第13項第2号：確定申告書・住民税の申告書の提出でなかったものとみなす
        return
    d = ctx.decision(C_ONESTOP, f"{pid}:{ctx.year}")
    applied = d.value is True
    choice_ids = list(d.record_ids)
    choice_states = set(d.states)
    if applied:
        # 第13項第2号：その年度分の住民税の申告書を提出する選択（選択.住民税の申告。2026-11-12：JM-39）。申告特例を求めた候補でだけ読む
        rr = ctx.decision(C_RESIDENT_RETURN, f"{pid}:{fiscal}")
        choice_ids += list(rr.record_ids)
        choice_states |= set(rr.states)
        if rr.value is True:
            wr.set("住民税_申告特例控除の対象か", False, choice_ids + [r["id"] for r in first], choice_states)
            return
    recipients = {r["attributes"]["recipient_name"] for r in first}
    if applied and len(recipients) > 5:
        applied = False  # 第13項第3号：申告特例通知書を送付した都道府県知事等の数が5を超えた
    moved: list[str] = []
    invalid: list[str] = []
    if applied:
        # 第13項第4号：申告特例通知書の送付を受けた市町村長が賦課期日の住所地の市町村長と異なるとき（その通知に限る）。通知は申告特例の求めに記載した
        # 住所の市町村へ送られる。寄附をした日の住民票の市町村が賦課期日の住所と同じなら当たらない。違う人は、求めに記載した住所（変更の届出を含む）の語彙が
        # ないので未確定（決める手段：事実）
        for r in first:
            on = r.get("when", {}).get("on")
            if not on:
                continue
            stated = r["attributes"].get("onestop_request_municipality_code")
            if stated is not None:  # 求め（変更の届出を含む）に記載した住所の市町村（2026-11-12 の語彙）：通知はそこへ送られる
                if stated != home:
                    invalid.append(r["id"])
                continue
            day = _dt.date.fromisoformat(on)
            codes = {x["attributes"]["municipality_code"] for x in ctx.records("resident_record") if x["roles"].get("person") == pid and covers(x.get("when"), day)}
            if codes and codes != {home}:
                moved.append(r["id"])
    miss: tuple[Split, ...] = ()
    if moved:
        miss = (
            _missing(
                f"事実:申告特例通知書の送付先:{pid}:{ctx.year}",
                Means.FACT,
                {"person": pid, "寄附金": sorted(moved), "決めるもの": "申告特例の求め（変更の届出を含む）に記載した住所の市町村が賦課期日の住所地か（附則第7条第13項第4号）",
                 "入力": "donation の attributes.onestop_request_municipality_code"},
            ),
        )
    elif invalid and len(invalid) == len([r for r in first if r.get("when", {}).get("on")]):
        applied = False  # 第13項第4号：全部の通知が賦課期日の住所地でない市町村長へ送られた（その通知に限ってなかったものとみなす）
    elif invalid:
        miss = (
            _missing(
                f"一次情報:一部の申告特例通知書がなかったものとみなされるときの申告特例控除額:{pid}:{ctx.year}",
                Means.PRIMARY_SOURCE,
                {"person": pid, "寄附金": sorted(invalid), "事項": "附則第7条第13項第4号で一部の通知だけがなかったものとみなされるときの申告特例控除額"
                 "（附則第7条の2第4項の特例控除額×割合を、残る通知の寄附金で計算する定めを docs に取得していない）"},
            ),
        )
    wr.set("住民税_申告特例控除の対象か", applied, choice_ids + [r["id"] for r in first], choice_states, missing=miss)


#: 第2号の寄附金の分かれ目の候補（docs/public-sources/20261112_impl-research4_juminzei-kifu-laws-and-kokuji.md#1。額は当たる候補で書く）。
CHEST_CANDIDATES = ("第2号の寄附金に当たる", "第2号の寄附金に当たらない")

#: 第2号の寄附金の分かれ目の項目（chest_qualifies が返す）。
CHEST_OPEN_SECOND = "第7条の17第2号（総務大臣が定めるもの）の告示"  # 一次情報（docs にない：impl-research4 juminzei-kifu §3）
CHEST_OPEN_APPROVAL = "総務大臣の承認を受けた募集か"  # 事実（donation の attributes.mic_approved_solicitation）
CHEST_OPEN_PREFECTURE = "主たる事務所・収納した支部の所在の道府県"  # 事実（donation の attributes.recipient_office_prefecture_code）

_KIFU4 = "docs/public-sources/20261112_impl-research4_juminzei-kifu-laws-and-kokuji.md"
CHEST_RULE = BasisEntry(
    type=BasisType.RULE,
    name=(
        "第314条の7第1項第2号の政令で定める寄附金（施行令第48条の8 → 第7条の17）：第1号 共同募金会に厚生労働大臣が定める期間内に支出した寄附金で"
        "総務大臣の承認を受けた募集のもの、第2号 社会福祉事業・更生保護事業の経費に充てる共同募金会への寄附金で総務大臣が定めるもの（告示は docs にない）、"
        "第3号 日本赤十字社への寄附金で総務大臣の承認を受けた募集のもの。所在の条件（賦課期日の住所の道府県内の主たる事務所・支部）は法第314条の7第1項第2号。"
        "共同募金会で承認の募集なら当たる（承認の募集の寄附金は厚生労働大臣が定める期間内に支出したものと読む）、承認でない・欄なしは第2号の告示で決まるので候補。"
        "日本赤十字社は承認の募集なら当たり、承認でなければ当たらない（第3号だけ）。承認の例：総務省告示第383号（令和8年10月〜令和9年3月の共同募金。"
        "令和8年10月〜12月の支出は令和9年度分、令和9年1月〜3月の支出は令和10年度分）"
    ),
    source_kind=SourceKind.CABINET_ORDER,
    law="地方税法第314条の7第1項第2号・第37条の2第1項第2号、同法施行令第48条の8・第7条の17、令和8年総務省告示第383号",
    references=(f"{_KIFU4}#1", f"{_KIFU4}#1.1", f"{_KIFU4}#3", "docs/hypotheses/20261112_impl-research4_all-model.md#H10"),
    flags=(ReadingFlag.LEGAL_READING,),
)


def chest_qualifies(attrs: Mapping[str, Any], home_pref: str) -> tuple[bool | None, tuple[str, ...]]:
    """共同募金会・日本赤十字社への寄附金が第314条の7第1項第2号（施行令第48条の8 → 第7条の17）に当たるか。

    返す値は（当たるか, 分かれ目の項目）。当たるかが None のときは分かれ目の項目（CHEST_OPEN_*）で決まる（額は当たる候補で書く）。
    根拠：docs/public-sources/20261112_impl-research4_juminzei-kifu-laws-and-kokuji.md#1・#1.1・#3、docs/hypotheses/20261112_impl-research4_all-model.md#H10。
    - 所在の道府県（法第314条の7第1項第2号の括弧書き）：記載があって賦課期日の住所の道府県でなければ当たらない。記載がなければ事実の分かれ目。
    - 共同募金会：総務大臣の承認を受けた募集（mic_approved_solicitation が真）なら第1号に当たる。偽・記載なしは第2号（総務大臣が定めるもの）の告示が
      docs にないので一次情報の分かれ目（記載なしは承認の事実の分かれ目も）。
    - 日本赤十字社：第3号だけ。真なら当たる、偽なら当たらない、記載なしは事実の分かれ目。
    """
    pref = attrs.get("recipient_office_prefecture_code")
    if pref is not None and pref != home_pref:
        return False, ()
    approved = attrs.get("mic_approved_solicitation")
    open_: list[str] = []
    if attrs.get("recipient_type") == "japanese_red_cross":
        if approved is False:
            return False, ()
        if approved is None:
            open_.append(CHEST_OPEN_APPROVAL)
    elif approved is not True:
        open_.append(CHEST_OPEN_SECOND)
        if approved is None:
            open_.append(CHEST_OPEN_APPROVAL)
    if pref is None:
        open_.append(CHEST_OPEN_PREFECTURE)
    return (None if open_ else True), tuple(open_)


def _chest_splits(pid: str, year: int, judged: list[tuple[Mapping[str, Any], tuple[str, ...]]]) -> tuple[Split, ...]:
    """第2号の寄附金の分かれ目：一次情報（第7条の17第2号の告示）と事実（承認・所在の記載）を別の分かれ目にする。"""
    out: list[Split] = []
    second = sorted(r["id"] for r, items in judged if CHEST_OPEN_SECOND in items)
    if second:
        out.append(
            Split(
                id=f"一次情報:第2号の寄附金:{pid}:{year}",
                means=Means.PRIMARY_SOURCE,
                target={
                    "person": pid,
                    "寄附金": second,
                    "事項": "共同募金会への寄附金で総務大臣の承認を受けた募集のもの（施行令第7条の17第1号）でないものが、第2号の総務大臣が定めるものに当たるか。"
                    "第2号の告示は docs にない（docs/public-sources/20261112_impl-research4_juminzei-kifu-laws-and-kokuji.md §1・§3）",
                },
                candidates=CHEST_CANDIDATES,
                splits_conclusion=True,
            )
        )
    facts = [(r, [i for i in items if i != CHEST_OPEN_SECOND]) for r, items in judged]
    facts = [(r, items) for r, items in facts if items]
    if facts:
        out.append(
            Split(
                id=f"事実:第2号の寄附金:{pid}:{year}",
                means=Means.FACT,
                target={
                    "person": pid,
                    "寄附金": sorted(r["id"] for r, _ in facts),
                    "決めるもの": sorted({i for _, items in facts for i in items}),
                    "入力": "donation の attributes.mic_approved_solicitation（総務大臣の承認を受けた募集か）・recipient_office_prefecture_code"
                    "（共同募金会の主たる事務所・日本赤十字社の収納した支部の所在の都道府県）",
                },
                candidates=CHEST_CANDIDATES,
                splits_conclusion=True,
            )
        )
    return tuple(out)


def _other_donation_amounts(ctx: YearContext, wr: _Writer, pid: str, home: str, jan1: _dt.date) -> None:
    """第314条の7第1項第2号〜第4号（第37条の2第1項第2号〜第4号）の寄附金の額。市町村民税と道府県民税で別の条例を当てる。

    - 第3号・第4号（条例で定めるもの）：注入データ 住民税.条例で定める寄附金（住所の市町村・道府県。寄附先の名称）と donation の recipient_name を
      突き合わせる。注入されていなければ未確定（候補を持たない注入点：決める手段は注入）。
    - 第2号（共同募金会・日本赤十字社）：chest_qualifies（施行令第48条の8 → 第7条の17、所在の道府県）。決まらない寄附金は額を当たる候補で書き、
      分かれ目（一次情報：第7条の17第2号の告示、事実：承認・所在の記載）を付ける。
    - 第2号の額だけを 住民税_第2号の寄附金の額 にも書く（確定申告書 第二表の「共同募金、日赤その他の寄附」と条例指定の欄を分けるため。
      分かれ目・由来は第2号〜第4号の額と同じ）。
    """
    others = _other_donations(ctx, pid)
    names = ("住民税_市町村民税の第2号から第4号までの寄附金の額", "住民税_道府県民税の第2号から第4号までの寄附金の額")
    if not others or not home:
        for var in (*names, "住民税_第2号の寄附金の額"):
            wr.set(var, 0, [r["id"] for r in others], _states(others))
        return
    chest = [r for r in others if r["attributes"].get("recipient_type") in CHEST_TYPES]
    jorei = [r for r in others if r["attributes"].get("recipient_type") not in CHEST_TYPES]
    # 第2号（2026-11-12 の語彙 recipient_office_prefecture_code・mic_approved_solicitation）：当たらないと決まった寄附金は数えない
    home_pref = issuer_code("prefecture", home)
    judged = [(r, items) for r in chest for hit, items in (chest_qualifies(r["attributes"], home_pref),) if hit is not False]
    chest_total = sum(int(r["amounts"]["amount"]) for r, _ in judged)
    chest_miss = _chest_splits(pid, ctx.year, judged)
    wr.set("住民税_第2号の寄附金の額", chest_total, [r["id"] for r in others], _states(others), basis=[CHEST_RULE] if chest else [], missing=chest_miss)
    for kind, var in zip(("municipality", "prefecture"), names):
        total = chest_total
        ids = [r["id"] for r in others]
        states = set(_states(others))
        basis: list[Any] = [CHEST_RULE] if chest else []
        miss: list[Split] = list(chest_miss)
        if jorei:
            d = ctx.injection(P_JOREI, injection_key(kind, issuer_code(kind, home), jan1))
            ids += list(d.record_ids)
            states |= set(d.states)
            basis += list(d.basis)
            miss += list(d.missing)
            listed = set(d.value["寄附先の名称"]) if d.value is not None else set()
            total += sum(int(r["amounts"]["amount"]) for r in jorei if r["attributes"]["recipient_name"] in listed)
        wr.set(var, total, ids, states, basis=basis, missing=miss)


def _withheld_local(ctx: YearContext, out: ModuleInputs, wr: _Writer, pid: str) -> None:
    """控除の対象の配当割額・株式等譲渡所得割額（第314条の9：前年分の確定申告書に記載した特定配当等・特定株式等譲渡所得金額に課されたもの）。

    - 一般の配当等の記録（dividend）の配当割額（dividend_local_tax）：選択.株式等の申告（income_kinds の1か所）で申告したもの。
    - 大口株主等の配当（判断.大口株主等）：令和9年度分（令和8年中の支払）で 2026-04-01 以後に支払を受けるべきものは、特定配当等のロ
      （同族会社と合わせて3%以上）として配当割の対象で、総合課税で申告するので控除の対象。それより前の支払・令和8年度分は特定配当等でない
      （配当割の記録があれば食い違いとして対象外）。D21 R3、docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.5。
    - 源泉徴収選択口座（brokerage_annual）で申告するもの：年間取引報告書の配当割額（dividend_local_tax：配当を申告するとき）・株式等譲渡所得割額
      （transfer_local_tax：譲渡を申告するとき）。源泉徴収税額があるのに欄がなければ未確定（決める手段：事実。記録の書き足し）。
    """
    var = "住民税_控除の対象の配当割額等"
    large = {j["subject"]["dividend_id"]: j for j in heads(ctx.judgments(J_LARGE))}
    total = 0
    ids: list[str] = []
    states: set[State] = set()
    miss: list[Split] = []
    divs = [
        r for r in ctx.records("dividend")
        if r["roles"].get("recipient") == pid and overlaps_year(r.get("when"), ctx.year) and r["attributes"]["account_type"] != "nisa"
    ]
    for r in divs:
        tax = int(r["amounts"].get("dividend_local_tax", 0) or 0)
        if tax <= 0:
            continue
        j = large.get(r["id"])
        paid = _dt.date.fromisoformat(r["when"]["on"])
        if j is not None and j["value"] is True:
            ids += [r["id"], j["id"]]
            if ctx.year >= 2026 and paid >= _dt.date(2026, 4, 1):
                total += tax
            else:
                out.exclude(pid, _reason("大口株主等の配当に配当割の記録がある（令和8年4月1日より前に支払を受けるべき配当は特定配当等でなく配当割が課されない）", [r["id"], j["id"]]), var)
            continue
        try:
            d = ctx.decision(C_STOCK, f"{pid}:配当")
        except KeyError:
            out.exclude(pid, _reason("配当割の記録がある配当について、申告するかの選択の1か所がない（income_kinds が扱わない配当）", [r["id"]]), var)
            continue
        ids += [r["id"], *d.record_ids]
        states |= set(d.states) | set(_states([r]))
        if isinstance(d.value, Mapping) and d.value.get("declare"):
            total += tax
    for r in ctx.records("brokerage_annual"):
        if r["roles"].get("holder") != pid or not overlaps_year(r.get("when"), ctx.year) or not r["attributes"]["withholding_elected"]:
            continue
        acc = r["attributes"]["account_id"]
        amounts = r["amounts"]
        # 譲渡の申告（{人}:{口座}）は株式等譲渡所得割額、配当の申告（{人}:配当:{口座}）は配当割額（第314条の9第1項：確定申告書に記載したもの）
        for key, field_name in ((f"{pid}:{acc}", "transfer_local_tax"), (f"{pid}:配当:{acc}", "dividend_local_tax")):
            try:
                d = ctx.decision(C_STOCK, key)
            except KeyError:
                continue
            if not (isinstance(d.value, Mapping) and d.value.get("declare")):
                continue
            ids += [r["id"], *d.record_ids]
            states |= set(d.states) | set(_states([r]))
            got = amounts.get(field_name)
            if got is not None:
                total += int(got)
            elif int(amounts.get("withholding_tax", 0) or 0) > 0:
                miss.append(
                    _missing(
                        f"事実:配当割額等:{pid}:{acc}:{field_name}:{ctx.year}",
                        Means.FACT,
                        {"person": pid, "account_id": acc, "brokerage_annual": r["id"], "入力": f"amounts.{field_name}（年間取引報告書の住民税の額）"},
                    )
                )
    wr.set(var, total, ids, states, missing=miss)


#: 住宅借入金等特別税額控除の版の居住年（附則第5条の4第5項・第7項。docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.2）。
HOUSING_FIRST_YEAR = 2009  # 平成21年
HOUSING_ADD_YEARS = (2016, 2025)  # 平成28年〜令和7年：控除限度の基に基礎控除の差を加算
HOUSING_SPECIFIED_YEARS = (2014, 2021)  # 平成26年〜令和3年：特定取得・特別特定取得の率・上限
SPECIFIED_CATEGORIES = frozenset({"specified_acquisition", "specially_specified_acquisition"})
#: 居住年の違う住宅借入金等の版の違いの分かれ目の候補（附則第5条の4 は1つの居住年の版を書く。2つ以上の版を合わせる一次情報がない）。
HOUSING_VERSION_CANDIDATES = ("居住年の版のうち控除限度の大きいもの", "居住年の版のうち控除限度の小さいもの")


#: 前年分の所得税で適用を受けた特例法（housing_loan_credit の special_acts。docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.5）。
ACT_EARTHQUAKE = "great_east_japan_earthquake"  # 震災特例法第13条（附則第45条）
ACT_COVID = "covid19"  # 新型コロナ特例法第6条の2（附則第61条）
#: 附則第45条第6項（第3項）：居住年が平成26年（4月1日以後の居住に限る）〜令和3年の住宅借入金等は 4.2%・81,900円など（取得の区分を問わない）
EARTHQUAKE_SPECIFIED_FROM = _dt.date(2014, 4, 1)


def housing_version(year: int, category: str | None, special_acts: Iterable[str] = (), moved_in_on: _dt.date | None = None) -> tuple[bool, bool | None]:
    """居住年と取得の区分から（基礎控除の差を加算するか, 特定取得・特別特定取得の率・上限か〔区分が要る居住年で記載がなければ None〕）。

    special_acts（前年分の所得税で適用を受けた特例法。§3.5）：
    - 震災特例法（附則第45条第6項）：居住年が平成26年（4月1日以後）〜令和3年なら取得の区分を問わず 4.2%・81,900円など。
    - 新型コロナ特例法（附則第61条第2項）：附則第5条の4第7項と附則第45条第6項の「令和三年」を「令和四年」とする（居住年の終わりを1年延ばす）。
    """
    acts = set(special_acts)
    add = HOUSING_ADD_YEARS[0] <= year <= HOUSING_ADD_YEARS[1]
    last = HOUSING_SPECIFIED_YEARS[1] + (1 if ACT_COVID in acts else 0)
    if ACT_EARTHQUAKE in acts:
        start_ok = moved_in_on is None or moved_in_on >= EARTHQUAKE_SPECIFIED_FROM if year == EARTHQUAKE_SPECIFIED_FROM.year else True
        return add, EARTHQUAKE_SPECIFIED_FROM.year <= year <= last and start_ok
    if not (HOUSING_SPECIFIED_YEARS[0] <= year <= last):
        return add, False
    if category is None:
        return add, None
    return add, category in SPECIFIED_CATEGORIES


def _housing(ctx: YearContext, out: ModuleInputs, wr: _Writer, pid: str, fiscal: int) -> None:
    """住宅借入金等特別税額控除の版（附則第5条の4第5項・第7項）：居住年で控除限度の基に基礎控除の差を加算するかと、特定取得・特別特定取得か
    （housing_loan_credit の acquisition_category。居住年が平成26年〜令和3年で記載がなければ未確定：決める手段は事実）。"""
    var, var_sp = "住民税_住宅借入金等特別税額控除の控除限度額に基礎控除の差を加算するか", "住民税_住宅借入金等特別税額控除の特定取得か"
    recs = [r for r in ctx.records("housing_loan_credit") if r["roles"].get("person") == pid and overlaps_year(r.get("when"), ctx.year)]
    recs = [r for r in recs if int(r["amounts"]["credit_amount"]) > 0]
    if not recs:
        wr.set(var, False)
        wr.set(var_sp, False)
        return
    ids = [r["id"] for r in recs]
    states = _states(recs)
    if any(r["attributes"].get("moved_in_on") is None for r in recs):
        miss = (_missing(f"事実:居住年:{pid}:{ctx.year}", Means.FACT, {"person": pid, "housing_loan_credit": ids, "入力": "attributes.moved_in_on（居住の用に供した日）"}),)
        wr.set(var, False, ids, states, missing=miss)
        wr.set(var_sp, False, ids, states, missing=miss)
        return
    years = sorted({_dt.date.fromisoformat(r["attributes"]["moved_in_on"]).year for r in recs})
    last = 2025 if fiscal == 2026 else 2030  # 令和8年度分は居住年 令和7年まで、令和9年度分は令和12年まで（§3.3）
    bad = [y for y in years if y < HOUSING_FIRST_YEAR or y > min(last, ctx.year)]
    if bad:
        # 前年分の所得税で措法第41条の適用を受けられない居住年（記録の誤り）
        out.exclude(pid, _reason(f"居住年 {bad[0]} 年の住宅借入金等特別控除の記録は、前年分（{ctx.year}年分）の所得税・この年度分の附則第5条の4 の対象の居住年にない", ids), var)
        wr.set(var, False, ids, states)
        wr.set(var_sp, False, ids, states)
        return
    versions: set[tuple[bool, bool | None]] = set()
    for r in recs:
        moved = _dt.date.fromisoformat(r["attributes"]["moved_in_on"])
        versions.add(housing_version(moved.year, r["attributes"].get("acquisition_category"), r["attributes"].get("special_acts", ()), moved))
    miss_l: list[Split] = []
    if any(sp is None for _, sp in versions):
        miss_l.append(
            _missing(
                f"事実:特定取得:{pid}:{ctx.year}",
                Means.FACT,
                {"person": pid, "housing_loan_credit": ids, "入力": "attributes.acquisition_category（特定取得・特別特定取得か：附則第5条の4第7項で控除限度の率・上限が変わる）"},
            )
        )
    if len({(a, bool(sp)) for a, sp in versions}) > 1:
        miss_l.append(
            Split(
                id=f"一次情報:住宅借入金等の居住年の版:{pid}:{ctx.year}",
                means=Means.PRIMARY_SOURCE,
                target={"person": pid, "housing_loan_credit": ids, "事項": "居住年・取得の区分の違う住宅借入金等があるときの控除限度額（附則第5条の4第5項・第7項は1つの版を書く）"},
                candidates=HOUSING_VERSION_CANDIDATES,
                splits_conclusion=True,
            )
        )
    add, sp = max((a, bool(s)) for a, s in versions)
    wr.set(var, add, ids, states, missing=miss_l)
    wr.set(var_sp, sp, ids, states, missing=miss_l)


def _sex(ctx: YearContext, wr: _Writer, pid: str, dec31: _dt.date) -> None:
    """前年の12月31日の法令上の性別（legal_sex）。記録がなく、ひとり親に当たりうる（子がいて、その日に配偶者がいない）人は未確定の材料つき。"""
    recs = [r for r in ctx.records("legal_sex") if r["roles"].get("person") == pid and covers(r.get("when"), dec31)]
    sexes = {r["attributes"]["sex"] for r in recs}
    if len(sexes) == 1:
        wr.set("住民税_法令上の性別が女性か", sexes.pop() == "female", [r["id"] for r in recs], _states(recs))
        return
    miss: tuple[Split, ...] = ()
    if ctx.relations.children(pid, dec31) and not ctx.relations.spouses(pid, dec31):
        miss = (_missing(f"事実:法令上の性別:{pid}", Means.FACT, {"person": pid, "入力": "legal_sex（調整控除のひとり親の父・母：施行令第48条の7の2）"}),)
    wr.set("住民税_法令上の性別が女性か", False, [r["id"] for r in recs], _states(recs), missing=miss)


def _retirement_split(wr: _Writer, ctx: YearContext, pid: str) -> None:
    """源泉徴収の対象の退職手当等（源泉徴収税額の欄がある支払：tax の 所得税_退職手当等の全部が源泉徴収の対象か と同じ読み）とそれ以外の退職手当等が
    両方ある人（JM-19）：第328条の分離課税に係る退職所得と、総合課税の退職所得金額に分ける計算（退職所得控除の当て方）を定めた一次情報が docs にない
    （docs/public-sources/20261109_round2b_taishoku-laws-and-guidance.md §9-3）。分かれ目（一次情報）にする。"""
    pays = [r for r in ctx.records("retirement_payment") if r["roles"].get("recipient") == pid and overlaps_year(r.get("when"), ctx.year)]
    withheld = {"withholding_tax" in r["amounts"] for r in pays}
    if len(withheld) < 2:
        wr.set("住民税_分離課税の退職所得の区分が決まらないか", False, [r["id"] for r in pays])
        return
    ids = sorted(r["id"] for r in pays)
    miss = (
        _missing(
            f"一次情報:分離課税と総合課税の退職所得の区分:{pid}:{ctx.year}",
            Means.PRIMARY_SOURCE,
            {"person": pid, "退職手当等": ids, "事項": "源泉徴収の対象の退職手当等（第328条の分離課税）とそれ以外（第313条の退職所得金額）が両方あるときの、退職所得控除の当て方と所得の分け方"},
        ),
    )
    wr.set("住民税_分離課税の退職所得の区分が決まらないか", True, ids, _states(pays), missing=miss)


def _retirement_domicile(ctx: YearContext, wr: _Writer, pid: str) -> None:
    """退職手当等の支払を受けるべき年（所得の年分）の1月1日の住所と生活扶助（第328条・第295条第2項）。退職手当等がなければ書かない。"""
    pays = [r for r in ctx.records("retirement_payment") if r["roles"].get("recipient") == pid and overlaps_year(r.get("when"), ctx.year)]
    if not pays:
        return
    on = _dt.date(ctx.year, 1, 1)
    home = domicile_on(ctx, pid, on, ctx.year)
    miss = () if home.known else (
        _missing(f"事実:退職の年の1月1日の住所:{pid}:{ctx.year}", Means.FACT, {"person": pid, "日": on.isoformat(), "入力": "resident_record"}),
    )
    wr.set("住民税_退職手当等の支払を受けるべき年の1月1日に住所を有する市町村", home.code, home.record_ids, home.states, missing=miss)
    aid = _assistance_on(ctx, pid, on)
    wr.set("住民税_退職手当等の支払を受けるべき年の1月1日に生活扶助を受けているか", bool(aid), [r["id"] for r in aid], _states(aid))


#: 住民税の非課税の判定（第295条第1項第2号）の寡婦の「扶養親族を有する」の取扱い（総務省の取扱通知 第2章第1節第1の3：扶養親族が他の納税義務者の
#: 扶養親族とされていても、寡婦がその扶養費の一部を負担していれば有するものとして取り扱う。docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md §2.5）。
J_FUYOHI = "判断.扶養費の一部負担"


def _divorced(ctx: YearContext, pid: str, dec31: _dt.date) -> list[Mapping[str, Any]]:
    """前年の12月31日までに離婚で終わった婚姻（寡婦のイの材料。夫か・再婚していないかは所得税の判定が見る）。"""
    out = []
    for r in ctx.records("marriage"):
        if pid not in (r["roles"].get("spouse_a"), r["roles"].get("spouse_b")) or r.get("attributes", {}).get("ended_by") != "divorce":
            continue
        end = (r.get("when") or {}).get("to_on")
        if end and _dt.date.fromisoformat(end) <= dec31:
            out.append(r)
    return out


def fuyohi_slots(ctx: YearContext) -> list[DecisionSlot]:
    """離婚した人だけ（ほかの人の判定には効かない）。未入力なら負担している・していないの両方で評価する（D21 R6）。"""
    w = ctx.window("住民税", "年度")
    if w is None:
        return []
    dec31 = w.date("前年の12月31日")
    return [
        DecisionSlot(key=pid, target={"person": pid, "tax_year": ctx.year}, matches=lambda j, pid=pid: j["subject"].get("person") == pid, persons=(pid,))
        for pid in ctx.persons
        if _divorced(ctx, pid, dec31)
    ]


def _fuyohi(ctx: YearContext, wr: _Writer, pid: str, dec31: _dt.date) -> None:
    if not _divorced(ctx, pid, dec31):
        wr.set("住民税_扶養費の一部を負担しているか", False)
        return
    d = ctx.decision(J_FUYOHI, pid)
    wr.set("住民税_扶養費の一部を負担しているか", d.value is True, d.record_ids, d.states)


DECISIONS: tuple[DecisionSpec, ...] = (
    DecisionSpec(J_YASHIKI, yashiki_slots),
    DecisionSpec(C_ONESTOP, onestop_slots, value_of=_onestop_value),
    DecisionSpec(C_RESIDENT_RETURN, resident_return_slots, value_of=_resident_return_value),
    # 2026-11-12 の2回目（JM-41）：同じ選択の specific_expense_deduction（地方税法第313条第11項）。段 住民税の特定支出控除の申告 が読む（読んだときだけ開く）
    DecisionSpec(C_RESIDENT_RETURN, resident_specific_slots, value_of=resident_specific_value),
    DecisionSpec(J_FUYOHI, fuyohi_slots),
)
