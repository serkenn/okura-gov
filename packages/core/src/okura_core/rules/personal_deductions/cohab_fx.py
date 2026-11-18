"""規則モジュール personal_deductions：同居老親等の「同居」の老人ホーム等（判断.老人ホーム等：VOC J-08）と、
国外居住親族への支払の円換算の方法（選択.円換算の方法：VOC C-11）。2026-11-12。

- 判断.老人ホーム等（措法41の16①、国税庁の説明：docs/public-sources/20261109_round2_elderly-abroad-guidance.md §1.1）：
  病気の治療のための入院は、期間が長くても同居に当たる。老人ホーム等へ入所している場合は、その老人ホームが居所となり、同居しているとはいえない。
  判定の時（所法85③）に入院・施設入所（institution_stay）の期間の中にいる親族について、その施設が老人ホーム等と判断されれば
  `所得税_申告者と同居を常況としているか`（同居老親等の同居）を偽にする（判断.同居を常況 が真でも：施設が居所になるため）。
  「老人ホーム等」の範囲（介護老人保健施設・グループホームなど）を書いた資料はない（同 §6-1）ので、施設の種類から決めず判断で受け取る。
  1か所を置く入所：治療のための入院（institution が hospital で for_treatment が偽でない）でないもの、又は判断が入力されたもの。
  その年12月31日に老人扶養親族の年齢の下限以上の人だけ（同居老親等は老人扶養親族のうちの者）。未入力は候補（真・偽）の全部で評価する（D21 R6）。
  読んだときだけ開く（lazy）：段は、判断.同居を常況 などで同居とされた親族の、判定の時を含む入所についてだけ読む。
  所法79③ の同居特別障害者の「同居」に老人ホーム等の扱いを書いた資料は docs にないので、この判断は同居老親等の同居にだけ使う。
- 選択.円換算の方法（所法2①三十四の二ロ(3)・所規47の2⑩、所基通2−50：同 §3.4）：38万円以上の判定の支払の額は、
  送金の記録の円の額（remittance.amounts.amount）の合計。外貨建ての支払の円の額は、所基通2−50 の方法（送金日の仲値、現に支出した本邦通貨の額、
  年間の合計額の一括換算）で換算したもので、判定コアは為替相場を持たない（elderly-abroad-model HE3.2 の「相場の値は事実として受け取る」）。
  選択は、その円の額の換算の方法の記録として、外貨建ての送金がある組の支払の額の入力の由来（事実の ID）と根拠に付ける（値は変えない）。
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Callable, Iterable, Iterator, Mapping
from typing import Any

from ...basis import BasisEntry, BasisType, SourceKind
from ...candidates import Candidate
from ...dependents.ir_facts import covers
from ...dependents.kinship import age_on
from ...registry import DecisionSlot, DecisionSpec, YearContext, overlaps_year
from ...result import State

J_HOME = "判断.老人ホーム等"
C_FX = "選択.円換算の方法"

_BOOL = (Candidate(True, "true"), Candidate(False, "false"))

HOME_RULE = BasisEntry(
    type=BasisType.RULE,
    name="同居老親等の「同居」：老人ホーム等へ入所している場合は、その老人ホームが居所となり、同居しているとはいえない（病気の治療のための入院は同居）",
    source_kind=SourceKind.NTA_EXPLANATION,
    law="租税特別措置法第41条の16第1項。国税庁の質疑応答事例「「同居」の範囲（長期間入院）」、タックスアンサー No.1180 の（注）、年末調整のしかた",
    references=("docs/public-sources/20261109_round2_elderly-abroad-guidance.md#1.1",),
)

FX_RULE = BasisEntry(
    type=BasisType.RULE,
    name=(
        "国外居住親族への生活費等の支払の円換算：送金日の電信売買相場の仲値・現に支出した本邦通貨の額・年間の合計額の一括換算のうち"
        "選んだ方法で換算した円の額（送金の記録の amounts.amount）を合計する（判定コアは為替相場を持たない）"
    ),
    source_kind=SourceKind.CIRCULAR,
    law="所得税法第2条第1項第34号の2ロ(3)、所得税法施行規則第47条の2第10項、所得税基本通達2−50",
    references=("docs/public-sources/20261109_round2_elderly-abroad-guidance.md#3.4",),
)


def home_key(stay_id: str) -> str:
    return f"老人ホーム等:{stay_id}"


def treatment_stay(stay: Mapping[str, Any]) -> bool:
    """治療のための入院か（入院の側。判断がなければ同居を変えない）。"""
    a = stay.get("attributes", {})
    return a.get("institution") == "hospital" and a.get("for_treatment") is not False


def home_slots(ctx: YearContext) -> Iterator[DecisionSlot]:
    """判断.老人ホーム等 の1か所（入所ごと。モジュールの先頭の説明）。"""
    judged = {j["subject"]["stay_id"] for j in ctx.judgments(J_HOME)}
    age_min = int(ctx.parameters.所得税.老人扶養親族.年齢の下限)
    year_end = _dt.date(ctx.year, 12, 31)
    for stay in sorted(ctx.records("institution_stay"), key=lambda r: r["id"]):
        d = stay["roles"]["person"]
        sid = stay["id"]
        if d not in ctx.persons or not overlaps_year(stay.get("when"), ctx.year):
            continue
        if sid not in judged and (treatment_stay(stay) or age_on(ctx.birth_on(d), year_end) < age_min):
            continue
        yield DecisionSlot(
            key=home_key(sid),
            target={"person": d, "stay_id": sid, "tax_year": ctx.year, "purpose": "同居老親等の同居：入所している施設が老人ホーム等か（措法41の16①）"},
            matches=lambda j, s=sid: j["subject"]["stay_id"] == s,
            candidates=_BOOL,
            persons=(d,),
            lazy=True,
        )


def home_override(
    stays: Iterable[Mapping[str, Any]], t: _dt.date, read: Callable[[str], Any]
) -> tuple[bool, tuple[str, ...], frozenset[State]]:
    """判定の時 t を含む入所のうち、老人ホーム等と判断された（候補の）ものがあるか。

    read(key) は判断の1か所の値（Decided）。1か所を宣言していない入所（治療のための入院など）は KeyError で飛ばす。
    返す値：(老人ホーム等に入所しているか, 読んだ入所と判断の ID, 判断の状態)。
    """
    found = False
    ids: set[str] = set()
    states: set[State] = set()
    for stay in sorted(stays, key=lambda r: r["id"]):
        if not covers(stay.get("when"), t):
            continue
        try:
            dec = read(home_key(stay["id"]))
        except KeyError:
            continue
        ids.add(stay["id"])
        ids |= set(dec.record_ids)
        states |= set(dec.states)
        if dec.value is True:
            found = True
    return found, tuple(sorted(ids)), frozenset(states)


def fx_provenance(
    remits: Iterable[Mapping[str, Any]], choices: Iterable[Mapping[str, Any]], sender: str, year: int
) -> tuple[tuple[str, ...], tuple[BasisEntry, ...]]:
    """送金者 sender から受けた支払のうち外貨建てのものがあれば、その年分の 選択.円換算の方法 の ID と根拠（FX_RULE）。"""
    if not any("foreign_amount" in r.get("attributes", {}) for r in remits):
        return (), ()
    ids = tuple(
        sorted(c["id"] for c in choices if c["subject"]["person"] == sender and overlaps_year(c.get("when"), year))
    )
    return ids, (FX_RULE,)


DECISIONS: tuple[DecisionSpec, ...] = (
    DecisionSpec(J_HOME, home_slots),
    # 選択.円換算の方法：値を変えないので1か所を置かず、段が ctx.choices で読む（使う選択として登録する宣言）
    DecisionSpec(C_FX, lambda ctx: ()),
)
