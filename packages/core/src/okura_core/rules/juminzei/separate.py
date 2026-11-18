"""段階評価の段「住民税の分離課税の所得への所得控除」（D23 K1）：所得控除が総所得金額から引ききれないとき、上場株式等の分離課税の所得から控除する額。

- 第314条の2第11項：所得控除は総所得金額・山林所得金額・退職所得金額から順次控除する。附則第33条の2第7項第3号・第35条の2第8項第3号（第35条の2の2第8項で準用）
  の読替えで「総所得金額」に上場株式等に係る配当所得等の金額・譲渡所得等の金額が加わる（docs/public-sources/20261111_impl-research3_juminzei-laws-and-soumu.md §3）。
- 区分の間の順序を定める住民税の一次情報はない（同 §3）。住民税の所得割の率は区分の間で同じなので、順序で変わるのは千円未満の切捨ての差だけ
  （docs/hypotheses/20261111_impl-research3_all-model.md H10）。そこで、所得税の措通31・32共−4 の順（配当が先）で書き、もう一つの順と課税標準の合計が
  違う人には分かれ目（決める手段：一次情報）を付ける（一次情報なしで候補評価）。
"""

from __future__ import annotations

from ...registry import StageContext, StageOutput
from ...result import Means, Split
from . import calc

STAGE = "住民税の分離課税の所得への所得控除"

R_DED = "住民税_所得控除の合計"
# 住民税の雑損失の繰越控除の後の値（第313条第9項。所得税と繰越が同じ人は所得税の値と同じ：JM-32。2026-11-12）
R_GROSS = "住民税_雑損失の繰越控除の後の総所得金額"
R_DIV = "住民税_雑損失の繰越控除の後の上場株式等に係る配当所得等の金額"
R_GAIN = "住民税_雑損失の繰越控除の後の上場株式等に係る譲渡所得等の金額"
READS = (R_DED, R_GROSS, R_DIV, R_GAIN)

W_DIV = "住民税_上場株式等に係る配当所得等の金額から控除する所得控除の額"
W_GAIN = "住民税_上場株式等に係る譲渡所得等の金額から控除する所得控除の額"
WRITES = (W_DIV, W_GAIN)


def run(ctx: StageContext) -> StageOutput:
    out = StageOutput()
    unit = int(ctx.parameters.住民税.税率.端数.課税標準の単位)
    for p in ctx.persons:
        ded, gross, div, gain = (ctx.value(v, p) for v in READS)
        used = [ded, gross, div, gain]
        remaining = int(ded.value) - int(gross.value)
        d, g = int(div.value), int(gain.value)
        if remaining <= 0 or (d <= 0 and g <= 0):
            out.set(W_DIV, p, 0, uses=used)
            out.set(W_GAIN, p, 0, uses=used)
            continue
        x, y = calc.separate_deductions(remaining, d, g, calc.ORDER_DIVIDEND_FIRST)
        miss: tuple[Split, ...] = ()
        totals = {o: calc.separate_taxable_total(remaining, d, g, o, unit) for o in (calc.ORDER_DIVIDEND_FIRST, calc.ORDER_GAIN_FIRST)}
        if len(set(totals.values())) > 1:
            miss = (
                Split(
                    id=f"一次情報:住民税の分離課税の所得への所得控除の順序:{p}:{ctx.year}",
                    means=Means.PRIMARY_SOURCE,
                    target={"person": p, "事項": "所得控除を上場株式等に係る配当所得等の金額と譲渡所得等の金額のどちらから先に控除するか（住民税の一次情報がない）"},
                    candidates=tuple(totals),
                    splits_conclusion=True,
                ),
            )
        out.set(W_DIV, p, x, uses=used, missing=miss)
        out.set(W_GAIN, p, y, uses=used, missing=miss)
    return out


__all__ = ["READS", "STAGE", "WRITES", "run"]
