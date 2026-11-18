"""未払のまま回収することができないこととなった給与（所得税法第64条第1項・施行令第180条第2項。kyuyo の README KY-08、2026-11-12）。

なかったものとみなす額＝回収不能額等のうち、次のいずれか低い金額まで（所令180②。所基通64−2の2 は回収不能額等を含む3つのうち最も低い金額）：
  一 回収不能額等が生じた時の直前において確定している総所得金額・退職所得金額・山林所得金額の合計額（所基通64−3：損益通算の後の各種所得の金額
     〔赤字の所得はないもの〕の合計で、純損失・雑損失の繰越控除の後。山林所得は範囲外：D20）
  二 給与所得の金額から、回収不能額等に相当する収入金額がなかったものとした場合の給与所得の金額を控除した残額
     （所得税_回収不能額等に係る給与所得の金額の差額。二号の額は回収不能額等以下なので、回収不能額等そのものとの比較は要らない）
根拠：docs/public-sources/20261112_impl-research4_shotoku-laws-and-nta.md §1・§1.1・§1.3（仮説 H1、推測 I1）。

当て方（法令の読み：法64① の「当該各種所得の金額の合計額のうち、その回収することができないこととなつた金額…に対応する部分の金額は、
当該各種所得の金額の計算上、なかつたものとみなす」）：なかったものとみなすのは各種所得の金額の部分なので、給与所得の金額（所法28）から
min(一, 二) を引く（所得税_給与所得 の式）。給与等の収入金額（所法28④・措法41の3の11① などが使う「その年中の給与等の収入金額」）は変えない。
二号が低ければ、収入金額から回収不能額等を除いて計算した給与所得の金額と同じになる（推測 I1）。一号が低ければ、二号の差額より小さい額だけを
所得の金額から引く（収入金額をどれだけ減らしたかには読み替えない。質疑応答事例〔PS4-SH §1.3〕の「赤字なら0円として計算」は一号の合計に損益通算の後の額を使うことと同じ）。

一号の額は、給与所得を回収不能額等の前の額にして income_totals が計算する（所得税_回収不能額等の前の総所得金額と退職所得金額の合計額）。
その額は給与所得の金額（この段の出力に依存する）を引かないので、この段は循環しない。所得金額調整控除の第1項の「扶養親族等を有するか」は
personal_deductions の段（この段の後：判定用の合計所得金額が給与所得の金額を引く）が書く。そこで income_totals は第1項を「有するか」が偽のとき
（特別障害者に当たる本人だけに当てる）と真のときの2つの額を出し、なかったものとみなす額がどちらでも同じならその額を使う。
違うとき（給与等の収入金額が850万円を超え、損失で一号の額が二号の額の近くまで減る人）は、段の「有するか」を late_reads で読む
（2026-11-12。共有の段階評価の不動点の繰り返し：registry.StageSpec.late_reads。KY-10）：最初の計算では「有するか」がまだ決まらない（pending）ので
上限を対象外にし、evaluate が最後の計算の「有するか」を渡して段を計算し直す。「有するか」が真なら真のときの額、偽なら偽のときの額を上限にする。
繰り返しが収束しなければ（互いの上限が互いの「有するか」を変え続ける）、pending のときと同じく対象外にする。
"""

from __future__ import annotations

from ...basis import BasisEntry, BasisType, ReadingFlag, SourceKind
from ...registry import StageContext, StageOutput, StageSpec
from ...result import OutOfScopeCategory, OutOfScopeReason

STAGE_UNCOLLECTIBLE = "未払の給与の回収不能"
V_UNCOLLECTIBLE = "所得税_回収することができないこととなった給与等の金額"
V_DIFF = "所得税_回収不能額等に係る給与所得の金額の差額"
V_CAP = "所得税_給与の回収不能額等の上限"
#: income_totals の窓口（所令180②一の額。第1項の「有するか」が偽のときと真のとき）。
V_TOTAL = "所得税_回収不能額等の前の総所得金額と退職所得金額の合計額"
V_TOTAL_WITH_1 = "所得税_所得金額調整控除の第1項を当てたとした回収不能額等の前の総所得金額と退職所得金額の合計額"
#: personal_deductions の段 所得金額調整控除の対象の親族等 が書く（この段の後。late_reads で読む）。
V_HAS = "所得税_所得金額調整控除の対象の親族等を有するか"

SHOTOKU4 = "docs/public-sources/20261112_impl-research4_shotoku-laws-and-nta.md"
CAP_RULE = BasisEntry(
    type=BasisType.RULE,
    name="所令180②一の上限：回収不能額等が生じた時の直前に確定している総所得金額・退職所得金額の合計額（損益通算・繰越控除の後）",
    source_kind=SourceKind.CABINET_ORDER,
    law=(
        "所得税法施行令第180条第2項第1号、所得税基本通達64−2の2・64−3（損益通算の後〔赤字の所得はないもの〕、純損失・雑損失の繰越控除の後）。"
        "なかったものとみなす額は第1号と第2号のいずれか低い金額で、給与所得の金額の計算で当てる（法64①の「各種所得の金額の計算上」の読み）。"
        "総所得金額に租税特別措置法の読替え（上場株式等の所得を加えるもの）は当てない（docs で見た読替えの対象は所法2①30・71〜87 で、所令180 はない：法令の読み）"
    ),
    references=(f"{SHOTOKU4}#1.1", f"{SHOTOKU4}#1.3", "docs/public-sources/20261109_impl-prep_iryohi-law-text.md#3.2"),
    flags=(ReadingFlag.LEGAL_READING,),
)
ORDER_LIMIT_REASON = (
    "未払の給与の回収不能額等（所得税法第64条第1項）のなかったものとみなす額が、所得金額調整控除の第1項の「扶養親族等を有するか」で変わり、"
    "その判定（扶養の判定の段の後）と上限が互いに依存して1つに決まらない（施行令第180条第2項第1号の総所得金額は第1項の控除の後の額。"
    "判定コアの段階評価の不動点の繰り返しが収束しない）"
)


def run(ctx: StageContext) -> StageOutput:
    """全員に上限（所令180②一の額）を書く。回収不能額等のない人は0（給与所得の式は差額が0なら上限を使わない）で、読んだ値を伝えない。"""
    out = StageOutput()
    for pid in ctx.persons:
        u = ctx.value(V_UNCOLLECTIBLE, pid)
        if not u.value:
            out.set(V_CAP, pid, 0, uses=())
            continue
        diff = ctx.value(V_DIFF, pid)
        t0 = ctx.value(V_TOTAL, pid)
        t1 = ctx.value(V_TOTAL_WITH_1, pid)
        uses = (u, diff, t0, t1)
        if min(int(t0.value), int(diff.value)) == min(int(t1.value), int(diff.value)):
            out.set(V_CAP, pid, int(t0.value), uses=uses, basis=(CAP_RULE,))
            continue
        has = ctx.late(V_HAS, pid)  # 「有するか」で上限が変わる人だけ読む（読んだ人だけ不動点の繰り返しをする）
        if has.pending:
            out.exclude(pid, OutOfScopeReason(OutOfScopeCategory.NOT_IMPLEMENTED, ORDER_LIMIT_REASON, tuple(u.facts)), V_CAP)
            out.set(V_CAP, pid, int(t0.value), uses=uses, basis=(CAP_RULE,))
            continue
        cap = t1 if has.value else t0
        out.set(V_CAP, pid, int(cap.value), uses=(u, diff, cap, has), basis=(CAP_RULE,))
    return out


STAGE = StageSpec(
    name=STAGE_UNCOLLECTIBLE,
    title="未払の給与の回収不能額等（所得税法第64条第1項）の上限（施行令第180条第2項第1号：直前に確定している総所得金額・退職所得金額の合計額）を income_totals の値から写す",
    reads=(V_UNCOLLECTIBLE, V_DIFF, V_TOTAL, V_TOTAL_WITH_1),
    writes=(V_CAP,),
    run=run,
    late_reads=(V_HAS,),
)
