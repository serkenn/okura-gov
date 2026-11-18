"""還付等を受けるための申告書を提出するか（所得税法第122条第1項。選択.還付申告：VOC C-13。2026-11-12）。

第122条の申告書は、控除しきれない源泉徴収税額・予納税額がある居住者が「提出することができる」申告書で、出すかは納税者の選択
（docs/public-sources/20261109_impl-prep_zeigaku-tax-calc.md §4.2・§5.3）。控除しきれない源泉徴収税額等がある人は第120条第1項の
提出義務の外（同 §5.1 の括弧書き）なので、選択が効くのは 所得税.還付申告ができるか が真の人だけ。

段 `還付申告の選択`（StageSpec）が 所得税_還付申告ができるか を読み、真の人だけ 選択.還付申告 の1か所を読む（DecisionSlot.lazy：読んだときだけ
開く。還付のない人では分かれ目にも直積にも出ない）。その年分の確定申告書（準確定・確定損失を含む）を提出した記録があれば、選択を読まずに
提出したとする（通達121−1：申告不要の人から出された申告書は、還付金の額の記載があれば第122条の申告書）。未入力なら両方の候補で評価する（D22 S20。勧めない）。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from ...basis import BasisEntry, BasisType, SourceKind
from ...candidates import Candidate
from ...registry import DecisionSlot, DecisionSpec, StageContext, StageOutput, StageSpec, YearContext

K_REFUND = "選択.還付申告"
STAGE_REFUND = "還付申告の選択"
R_CAN_REFUND = "所得税_還付申告ができるか"
V_REFUND_CHOICE = "所得税_還付申告の選択"
#: 提出した申告書として数える書類の種別（その年分）。
FILED_RETURNS = ("final_return", "quasi_final_return", "loss_return")
REFUND_CANDIDATES = (Candidate(False, "還付等を受けるための申告書を提出しない"), Candidate(True, "還付等を受けるための申告書を提出する"))
_DOC = "docs/public-sources/20261109_impl-prep_zeigaku-tax-calc.md"

REFUND_RULE = BasisEntry(
    type=BasisType.RULE,
    name="所得税法第122条第1項（還付等を受けるための申告書を提出することができる）・所得税基本通達121−1",
    source_kind=SourceKind.LAW,
    references=(f"{_DOC}#4.2", f"{_DOC}#5.3"),
    law="所得税法第122条第1項",
    # detail は JSON にできる dict（BasisEntry.detail。文字列を渡すと結果の JSON を作るところで止まった：2026-11-12）
    detail={"note": "控除しきれない源泉徴収税額・予納税額がある人だけが、選択（選択.還付申告）か提出した確定申告書の記録で第122条の申告書を出す。"},
)


def refund_key(pid: str) -> str:
    return pid


def refund_slots(ctx: YearContext) -> Iterable[DecisionSlot]:
    for pid in ctx.persons:
        yield DecisionSlot(
            key=refund_key(pid),
            target={
                "person": pid,
                "tax_year": ctx.year,
                "決めるもの": "控除しきれない源泉徴収税額・予納税額の還付を受けるための申告書（所得税法第122条）を提出するか（選択.還付申告）",
            },
            matches=lambda c, _pid=pid: c.get("subject", {}).get("person") == _pid,
            candidates=REFUND_CANDIDATES,
            persons=(pid,),
            lazy=True,
        )


def filed_returns(ir: Mapping[str, Any], pid: str, year: int) -> list[str]:
    """その年分の確定申告書（準確定・確定損失を含む）を提出した記録の ID。"""
    return sorted(
        r["id"]
        for r in ir["filed_documents"]
        if r["kind"] == "filed_document"
        and r["roles"].get("filer") == pid
        and r["attributes"]["document_type"] in FILED_RETURNS
        and r["attributes"].get("tax_year") == year
    )


def run_refund(ctx: StageContext) -> StageOutput:
    out = StageOutput()
    for pid in ctx.persons:
        can = ctx.value(R_CAN_REFUND, pid)
        if can.value is not True:
            out.set(V_REFUND_CHOICE, pid, False, uses=[can])  # 第122条の申告書を出せない人（選択を読まない）
            continue
        filed = filed_returns(ctx.ir, pid, ctx.year)
        if filed:
            out.set(V_REFUND_CHOICE, pid, True, filed, uses=[can])
            continue
        d = ctx.decision(K_REFUND, refund_key(pid))
        out.set(V_REFUND_CHOICE, pid, d.value is True, d.record_ids, d.states, uses=[can], missing=d.missing)
    return out


DECISION = DecisionSpec(K_REFUND, refund_slots)
STAGE = StageSpec(
    name=STAGE_REFUND,
    title="還付等を受けるための申告書を提出するか（所得税法第122条。還付申告ができる人だけ選択を読む）",
    reads=(R_CAN_REFUND,),
    writes=(V_REFUND_CHOICE,),
    run=run_refund,
    basis=(REFUND_RULE,),
)
