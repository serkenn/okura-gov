"""複数の問いの評価で、時間がどこにかかるかを数える（使い捨て。テストにしない。2026-11-12 の3回目）。

問い：所得税 2025・2026、住民税・国保 2026・2027 年度、被扶養者の判定日 2026-04-01（IMPL5_core-perf_snapshot.py の multi）。
y26 を付けると所得税 2026・年度 2027 だけ（評価の単位 (2026, '') の1つ）。

使い方（リポジトリの根で）：
  python -I -X utf8 scripts/IMPL7_core-perf_rounds.py <units|rounds|slots> <家庭の番号 例 08> <okura_core を置いた src> [y26]

- units：評価の単位ごとの時間と、人のつながりごとの分かれ目の数・候補の数・上限を超えたか・点の比較（_affected_inputs）の時間。
- rounds：単位ごとの、段階評価の回ごとの使い回し（_RoundMemo.find）の当たり・外れの数（外れ＝OpenFisca の計算と値の集め方をした回）。
- slots：上限を超えたつながりの分かれ目の一覧と、点の比較で段を計算し直した situation ごとの時間と外れた回。
"""
import collections
import glob
import importlib
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
mode, ex, src = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, os.path.abspath(src))
sys.path.insert(0, os.path.abspath("packages/core"))
E = importlib.import_module("okura_core.evaluate")
from okura_core.country import build_system  # noqa: E402

system = build_system()
Q = {"income_tax_years": [2025, 2026], "resident_tax_fiscal_years": [2026, 2027], "kokuho_fiscal_years": [2026, 2027],
     "dependent_judgment_dates": ["2026-04-01"], "scenarios": []}
if len(sys.argv) > 4 and sys.argv[4] == "y26":
    Q = {**Q, "income_tax_years": [2026], "resident_tax_fiscal_years": [2027], "kokuho_fiscal_years": [2027],
         "dependent_judgment_dates": []}

stat: collections.Counter = collections.Counter()
missed: list[int] = []
orig_find = E._RoundMemo.find


def find(self, r, build):
    node = orig_find(self, r, build)
    stat[(r, node is not None)] += 1
    if node is None:
        missed.append(r)
    return node


E._RoundMemo.find = find
orig_unit = E._evaluate_unit


def unit(ir, u, *a, **k):
    stat.clear()
    t = time.perf_counter()
    res = orig_unit(ir, u, *a, **k)
    line = f"  単位 {u.key} {time.perf_counter() - t:6.2f}s 値 {len(res[0])}"
    if mode == "rounds":
        line += " 回（番号, 当たり）→ 数 " + str(sorted(stat.items()))
    print(line)
    return res


E._evaluate_unit = unit
orig_aff = E._affected_inputs


def affected(slots, runs, build_for, over, *a, **k):
    if mode == "slots":
        print("  つながり 分かれ目", len(slots), "上限を超えた" if over else "")
        for s in slots:
            print("    ", s.id, [c.label for c in s.candidates])

        def timed(assignment):
            missed.clear()
            t = time.perf_counter()
            b = build_for(assignment)
            diff = [s.id for s in slots if assignment[s.id].label != runs[0].assignment[s.id].label]
            print(f"      situation {time.perf_counter() - t:.2f}s 外れた回 {missed[:]} 変えた分かれ目 {diff[:3]}")
            return b

        return orig_aff(slots, runs, timed, over, *a, **k)
    t = time.perf_counter()
    res = orig_aff(slots, runs, build_for, over, *a, **k)
    if mode == "units":
        print(f"    つながり 分かれ目 {len(slots)} 組 {len(runs)} 上限を超えた {over} 候補の数 {[len(s.candidates) for s in slots]}"
              f" 点の比較 {time.perf_counter() - t:6.2f}s")
    return res


E._affected_inputs = affected
for p in sorted(glob.glob(f"packages/ir/src/okura_ir/examples/valid/{ex}_*.json")):
    ir = json.load(open(p, encoding="utf-8"))
    t = time.perf_counter()
    E.evaluate(ir, Q, system=system)
    print(os.path.basename(p), f"{time.perf_counter() - t:.2f}s")
