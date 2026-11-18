"""直す前の版（.work/perf4/snap_src）で、候補の組合せの上限を引き上げて評価した結果（使い捨て。テストにしない。2026-11-12 の4回目）。

直す前の版は、人のつながりの候補の組合せが上限以内なら直積の全部を評価する（近似をしない）。上限を引き上げると、上限を超えて
「点の比べ方」の近似（_affected_inputs）を使っていたつながりも全部の組で評価するので、作り直した版（値ごとに依存する分かれ目だけで
評価する）の結果を確かめる基準（オラクル）になる。引き上げた上限も超えるつながりは、直す前と同じく近似のまま（比べない）。

使い方（リポジトリの根で）：
  python -I -X utf8 scripts/IMPL8_core-perf_oracle.py <出力のディレクトリ> <okura_core を置いた src> <上限> <家庭の番号,…>
問いは IMPL5_core-perf_snapshot.py の multi と同じ（所得税 2025・2026、住民税・国保 2026・2027 年度、判定日 2026-04-01）。
"""
import glob
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
out_dir, src, limit, which = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4].split(",")
sys.path.insert(0, os.path.abspath(src))
os.makedirs(out_dir, exist_ok=True)

import okura_core  # noqa: E402
from okura_core import candidates  # noqa: E402
from okura_core.country import build_system  # noqa: E402
from okura_core.evaluate import evaluate  # noqa: E402
from okura_core.result import dumps  # noqa: E402

print("okura_core:", okura_core.__file__)
candidates.MAX_ASSIGNMENTS = limit
candidates.assignments.__defaults__ = (limit,)  # 既定の引数は定義の時点の値なので、ここで替える
system = build_system()
MULTI = {
    "income_tax_years": [2025, 2026],
    "resident_tax_fiscal_years": [2026, 2027],
    "kokuho_fiscal_years": [2026, 2027],
    "dependent_judgment_dates": ["2026-04-01"],
    "scenarios": [],
}
for path in sorted(glob.glob("packages/ir/src/okura_ir/examples/valid/*.json")):
    name = os.path.splitext(os.path.basename(path))[0]
    if name[:2] not in which:
        continue
    ir = json.load(open(path, encoding="utf-8"))
    t = time.perf_counter()
    res = evaluate(ir, MULTI, system=system)
    with open(os.path.join(out_dir, name + "__multi.json"), "w", encoding="utf-8") as f:
        f.write(dumps(res))
    print(f"{name:60s} {time.perf_counter() - t:8.1f}s ok={res.ok}", flush=True)
