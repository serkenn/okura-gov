"""家庭1つ・問い1つの評価を cProfile で測り、時間のかかる関数を出す（使い捨て。テストにしない）。

使い方（リポジトリの根で）：
  python -I -X utf8 scripts/IMPL6_core-perf_profile.py <家庭の番号 例 02> <問い one|y25|fy|dd> <出力のファイル> [<okura_core を置いた src>]
"""
import cProfile
import glob
import io
import json
import os
import pstats
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
ex, mode, out = sys.argv[1], sys.argv[2], sys.argv[3]
if len(sys.argv) > 4:
    sys.path.insert(0, os.path.abspath(sys.argv[4]))
sys.path.insert(0, os.path.abspath("packages/core"))

from okura_core.evaluate import evaluate  # noqa: E402
from okura_core.country import build_system  # noqa: E402

ONE = {"income_tax_years": [2026], "resident_tax_fiscal_years": [], "kokuho_fiscal_years": [],
       "dependent_judgment_dates": [], "scenarios": []}
QUERIES = {
    "one": ONE,
    "y25": {**ONE, "income_tax_years": [2025], "filing_date": {"on": "2026-03-10", "planned": True}},
    "fy": {**ONE, "income_tax_years": [], "resident_tax_fiscal_years": [2027], "kokuho_fiscal_years": [2027],
           "kokunen_fiscal_years": [2027]},
    "dd": {**ONE, "income_tax_years": [], "dependent_judgment_dates": ["2026-04-01"]},
    # 複数の問いをまとめた評価（2026-11-12 の3回目）
    "multi": {"income_tax_years": [2025, 2026], "resident_tax_fiscal_years": [2026, 2027], "kokuho_fiscal_years": [2026, 2027],
              "dependent_judgment_dates": ["2026-04-01"], "scenarios": []},
}
system = build_system()
path = glob.glob(f"packages/ir/src/okura_ir/examples/valid/{ex}_*.json")[0]
ir = json.load(open(path, encoding="utf-8"))
evaluate(ir, ONE, system=system)  # 暖機（プロセスで1回の表を作る）
prof = cProfile.Profile()
t = time.perf_counter()
prof.enable()
evaluate(ir, QUERIES[mode], system=system)
prof.disable()
dt = time.perf_counter() - t
s = io.StringIO()
st = pstats.Stats(prof, stream=s)
st.sort_stats("cumulative").print_stats(70)
st.sort_stats("tottime").print_stats(40)
with open(out, "w", encoding="utf-8") as f:
    f.write(f"{ex} {mode} {dt:.2f}s（プロファイラつき）\n")
    f.write(s.getvalue())
print(f"{ex} {mode} {dt:.2f}s -> {out}")
