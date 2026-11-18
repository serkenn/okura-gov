"""並列の評価（問い multi、workers は既定）の時間の内訳：単位ごとの基準の組（Dispatcher.base）・組の割り振り（Dispatcher.run）・依存の決定の始まりと終わりの時刻（使い捨て。テストにしない。2026-11-12 の5回目）。

使い方（リポジトリの根で。packages/core/src の今の版）：python -I -X utf8 scripts/IMPL10_core-perf_timeline.py <家庭の番号の並び 例 01,08> [<くり返しの数 既定 2>]
"""
import glob, json, os, sys, time, importlib, threading
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.abspath("packages/core/src"))
from okura_core.evaluate import evaluate
from okura_core.country import build_system
P = importlib.import_module("okura_core.parallel")
E = importlib.import_module("okura_core.evaluate")
system = build_system()
Q = {"income_tax_years": [2025, 2026], "resident_tax_fiscal_years": [2026, 2027], "kokuho_fiscal_years": [2026, 2027],
     "dependent_judgment_dates": ["2026-04-01"], "scenarios": []}
T0 = [0.0]
log = []
def wrap(name, fn):
    def w(*a, **k):
        t = time.perf_counter()
        r = fn(*a, **k)
        extra = len(a[2]) if name == "run" else ""
        log.append((threading.current_thread().name[-8:], name, extra, round(t - T0[0], 2), round(time.perf_counter() - T0[0], 2)))
        return r
    return w
P.Dispatcher.base = wrap("base", P.Dispatcher.base)
P.Dispatcher.run = wrap("run", P.Dispatcher.run)
E._resolve_dependencies = wrap("resolve", E._resolve_dependencies)
E._evaluate_unit = wrap("unit", E._evaluate_unit)
for ex in sys.argv[1].split(","):
    ir = json.load(open(glob.glob(f"packages/ir/src/okura_ir/examples/valid/{ex}_*.json")[0], encoding="utf-8"))
    for rep in range(int(sys.argv[2]) if len(sys.argv) > 2 else 2):
        log.clear()
        T0[0] = time.perf_counter()
        evaluate(ir, Q, system=system)
        print(ex, "total", round(time.perf_counter() - T0[0], 2))
        for x in log:
            print("   ", x)
