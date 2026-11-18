"""直列（workers 1）で、候補の組の最後の situation（YearBuild）が、前の組と同じオブジェクトか・入力の値（型と値の repr）・対象外・グループまで同じかを数える（使い捨て。2026-11-12 の5回目）。

使い方（リポジトリの根で。packages/core/src の今の版）：python -I -X utf8 scripts/IMPL10_core-perf_final-dupes.py <家庭の番号の並び 例 01,02,08>
"""
import glob, json, os, sys, collections, importlib
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.abspath("packages/core/src"))
E = importlib.import_module("okura_core.evaluate")
from okura_core.country import build_system
system = build_system()
Q = {"income_tax_years": [2025, 2026], "resident_tax_fiscal_years": [2026, 2027], "kokuho_fiscal_years": [2026, 2027],
     "dependent_judgment_dates": ["2026-04-01"], "scenarios": [], "workers": 1}
orig = E._simulate
seen_id = collections.Counter()
seen_val = collections.Counter()
keep = []
def sim(build, system_, reg, period, rounding_vars, variables, engine=None):
    variables = list(variables)
    if len(variables) > 50:
        keep.append(build)
        seen_id[id(build)] += 1
        sig = (tuple(build.persons), tuple(sorted((k, type(v.value).__name__, repr(v.value)) for k, v in build.inputs.items())),
               tuple(sorted(map(repr, build.exclusions))), build.group_signature())
        seen_val[hash(sig)] += 1
    return orig(build, system_, reg, period, rounding_vars, variables, engine)
E._simulate = sim
for ex in sys.argv[1].split(","):
    seen_id.clear(); seen_val.clear(); keep.clear()
    ir = json.load(open(glob.glob(f"packages/ir/src/okura_ir/examples/valid/{ex}_*.json")[0], encoding="utf-8"))
    E.evaluate(ir, Q, system=system)
    n = sum(seen_id.values())
    print(ex, "final sims", n, "distinct objects", len(seen_id), "distinct input values", len(seen_val))
