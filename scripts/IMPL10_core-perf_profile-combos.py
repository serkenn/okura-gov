"""直列（workers 1）で、基準でない候補の組の計算（_resolve_dependencies が求める組）だけを cProfile で測る（使い捨て。2026-11-12 の5回目）。

使い方（リポジトリの根で。packages/core/src の今の版）：python -I -X utf8 scripts/IMPL10_core-perf_profile-combos.py <家庭の番号 例 01>
"""
import cProfile, glob, io, json, os, pstats, sys, time, importlib
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.abspath("packages/core/src"))
E = importlib.import_module("okura_core.evaluate")
from okura_core.country import build_system
system = build_system()
Q = {"income_tax_years": [2025, 2026], "resident_tax_fiscal_years": [2026, 2027], "kokuho_fiscal_years": [2026, 2027],
     "dependent_judgment_dates": ["2026-04-01"], "scenarios": [], "workers": 1}
ex = sys.argv[1]
ir = json.load(open(glob.glob(f"packages/ir/src/okura_ir/examples/valid/{ex}_*.json")[0], encoding="utf-8"))
E.evaluate(ir, Q, system=system)
prof = cProfile.Profile()
orig = E._resolve_dependencies
stat = {"n": 0, "t": 0.0}
def res(keys, deps_of, over, affected, runs, new_runs, simulate, *a, **k):
    def sim2(items):
        t = time.perf_counter()
        prof.enable()
        r = simulate(items)
        prof.disable()
        stat["n"] += len(items); stat["t"] += time.perf_counter() - t
        return r
    return orig(keys, deps_of, over, affected, runs, new_runs, sim2, *a, **k)
E._resolve_dependencies = res
t = time.perf_counter()
E.evaluate(ir, Q, system=system)
print("total", round(time.perf_counter() - t, 2), "combos", stat)
s = io.StringIO()
st = pstats.Stats(prof, stream=s)
st.sort_stats("cumulative").print_stats(60)
st.sort_stats("tottime").print_stats(30)
print(s.getvalue())
