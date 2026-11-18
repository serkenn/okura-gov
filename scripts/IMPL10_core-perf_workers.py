"""複数の問いをまとめた評価（IMPL5_core-perf_snapshot.py の multi）を、並列の数（問いの workers）を変えて評価し、時間と、結果の JSON が
並列の数によらず同じかを記録する（使い捨て。テストにしない。2026-11-12 の5回目）。

使い方（リポジトリの根で）：
  python -I -X utf8 scripts/IMPL10_core-perf_workers.py <出力のディレクトリ> <okura_core を置いた src> <並列の数の並び 例 16,1> [<家庭の番号の並び 例 01,08>]

- 並列の数ごとに、全部の家庭を続けて評価する（最初の並列の数の前に1回、暖機として家庭 01 を評価する：ワーカーの起動〔プロセスで1回〕を
  時間に入れない）。暖機の時間も出す。
- 結果の JSON は <出力>/w<数>/<家庭>__multi.json に置き（同じ数を2回目に書いたら w<数>_r<順番>）、最初の並列の数の結果と突き合わせる
  （バイト列が同じか。同じ数を2回並べると、並列の実行どうしの決定性も見る）。
"""
import glob
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
out_dir, src, workers_list = sys.argv[1], sys.argv[2], [int(x) for x in sys.argv[3].split(",")]
keep = sys.argv[4].split(",") if len(sys.argv) > 4 else None
sys.path.insert(0, os.path.abspath(src))

import okura_core  # noqa: E402
from okura_core.evaluate import evaluate  # noqa: E402
from okura_core.result import dumps  # noqa: E402
from okura_core.country import build_system  # noqa: E402

print("okura_core:", okura_core.__file__, flush=True)
system = build_system()
MULTI = {
    "income_tax_years": [2025, 2026],
    "resident_tax_fiscal_years": [2026, 2027],
    "kokuho_fiscal_years": [2026, 2027],
    "dependent_judgment_dates": ["2026-04-01"],
    "scenarios": [],
}
examples = sorted(glob.glob("packages/ir/src/okura_ir/examples/valid/*.json"))
if keep:
    examples = [e for e in examples if os.path.basename(e)[:2] in keep]
irs = {os.path.splitext(os.path.basename(e))[0]: json.load(open(e, encoding="utf-8")) for e in examples}
first = next(iter(irs.values()))
texts: dict[str, dict[str, str]] = {}
for i, w in enumerate(workers_list):
    label = f"w{w}" if f"w{w}" not in texts else f"w{w}_r{i}"
    t = time.perf_counter()
    evaluate(first, {**MULTI, "workers": w}, system=system)  # 暖機（ワーカーの起動とプロセスで1回の表）
    print(f"workers={w} 暖機 {time.perf_counter() - t:.2f}s", flush=True)
    os.makedirs(os.path.join(out_dir, label), exist_ok=True)
    texts[label] = {}
    for name, ir in irs.items():
        t = time.perf_counter()
        res = evaluate(ir, {**MULTI, "workers": w}, system=system)
        dt = time.perf_counter() - t
        txt = dumps(res)
        texts[label][name] = txt
        with open(os.path.join(out_dir, label, name + "__multi.json"), "w", encoding="utf-8") as f:
            f.write(txt)
        print(f"{label} {name:70s} {dt:7.2f}s {len(txt.encode('utf-8')) / 1024:8.0f} KiB ok={res.ok}", flush=True)
labels = list(texts)
for lab in labels[1:]:
    same = [n for n in irs if texts[lab][n] == texts[labels[0]][n]]
    diff = [n for n in irs if texts[lab][n] != texts[labels[0]][n]]
    print(f"突き合わせ {labels[0]} と {lab}：同じ {len(same)}・違う {len(diff)} {diff}", flush=True)
