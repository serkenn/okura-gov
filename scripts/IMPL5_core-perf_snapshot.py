"""代表の家庭（okura_ir の examples/valid の全部）と 500 人の給与だけの家庭を評価し、結果の JSON と時間を保存する（使い捨て。テストにしない）。

使い方（リポジトリの根で）：
  python -I -X utf8 scripts/IMPL5_core-perf_snapshot.py <出力のディレクトリ> [<okura_core を置いた src のディレクトリ>]
2つ目を渡すと、その src を先に読む（直す前の版の比較に使う）。
"""
import glob
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
out_dir = sys.argv[1]
if len(sys.argv) > 2:
    sys.path.insert(0, os.path.abspath(sys.argv[2]))
sys.path.insert(0, os.path.abspath("packages/core"))
os.makedirs(out_dir, exist_ok=True)

t0 = time.perf_counter()
import okura_core  # noqa: E402
from okura_core.evaluate import evaluate  # noqa: E402
from okura_core.result import dumps  # noqa: E402
from okura_core.country import build_system  # noqa: E402

print("okura_core:", okura_core.__file__)
t1 = time.perf_counter()
system = build_system()
t2 = time.perf_counter()
print(f"import {t1 - t0:.2f}s build_system {t2 - t1:.2f}s")

FULL = {
    "income_tax_years": [2025, 2026],
    "filing_date": {"on": "2027-03-10", "planned": True},
    "resident_tax_fiscal_years": [2026, 2027],
    "kokuho_fiscal_years": [2026, 2027],
    "kokunen_fiscal_years": [2026, 2027],
    "dependent_judgment_dates": ["2026-04-01"],
    "scenarios": [],
}
ONE = {
    "income_tax_years": [2026],
    "resident_tax_fiscal_years": [],
    "kokuho_fiscal_years": [],
    "dependent_judgment_dates": [],
    "scenarios": [],
}


MODES = os.environ.get("PERF_MODES", "one").split(",")
FY = {**ONE, "income_tax_years": [], "resident_tax_fiscal_years": [2027], "kokuho_fiscal_years": [2027], "kokunen_fiscal_years": [2027]}
DD = {**ONE, "income_tax_years": [], "dependent_judgment_dates": ["2026-04-01"]}
Y25 = {**ONE, "income_tax_years": [2025], "filing_date": {"on": "2026-03-10", "planned": True}}
#: 複数の問いをまとめた評価（2026-11-12 の3回目：所得税 2025・2026、住民税・国保 2026・2027 年度、判定日 2026-04-01）
MULTI = {
    "income_tax_years": [2025, 2026],
    "resident_tax_fiscal_years": [2026, 2027],
    "kokuho_fiscal_years": [2026, 2027],
    "dependent_judgment_dates": ["2026-04-01"],
    "scenarios": [],
}
QUERIES = {"one": ONE, "full": FULL, "fy": FY, "dd": DD, "y25": Y25, "multi": MULTI}


def run(ir, q, label, save=True, repeat=1):
    best = None
    for _ in range(repeat):
        t = time.perf_counter()
        try:
            res = evaluate(ir, q, system=system)
        except Exception as e:  # 直す前の版の誤りも記録する
            print(f"{label:60s} ERROR {type(e).__name__}: {str(e)[:150]}")
            with open(os.path.join(out_dir, label + ".json"), "w", encoding="utf-8") as f:
                f.write(json.dumps({"error": type(e).__name__, "message": str(e)}, ensure_ascii=False))
            return None
        dt = time.perf_counter() - t
        best = dt if best is None else min(best, dt)
    txt = dumps(res)
    if save:
        with open(os.path.join(out_dir, label + ".json"), "w", encoding="utf-8") as f:
            f.write(txt)
    print(f"{label:60s} {best:7.3f}s  {len(txt.encode('utf-8')) / 1024:8.0f} KiB  ok={res.ok}")
    return best


examples = sorted(glob.glob("packages/ir/src/okura_ir/examples/valid/*.json"))
if os.environ.get("PERF_EXAMPLES"):
    keep = os.environ["PERF_EXAMPLES"].split(",")
    examples = [e for e in examples if os.path.basename(e)[:2] in keep]
first = True
for ex in examples:
    ir = json.load(open(ex, encoding="utf-8"))
    name = os.path.splitext(os.path.basename(ex))[0]
    if first:
        evaluate(ir, ONE, system=system)  # 暖機
        first = False
    for mode in MODES:
        if mode == "w500":
            continue
        run(ir, QUERIES[mode], name + "__" + mode, repeat=2 if mode == "one" else 1)

# 500 人（給与だけ。収入金額を少しずつ変える）
persons = []
facts = []
for i in range(500):
    pid = f"p-{i:04d}"
    persons.append({"id": pid, "birth_on": "1990-01-01"})
    facts.append({
        "id": f"s-{i:04d}", "kind": "salary_payment", "roles": {"recipient": pid}, "when": {"on": "2026-06-25"},
        "amounts": {"gross": 500_000 + i * 20_011}, "attributes": {"counterparty": "架空の会社", "due_on": "2026-06-25"},
    })
ir500 = {"schema_version": "0", "persons": persons, "relations": [], "residences": [], "insurance_memberships": [],
         "facts": facts, "assets": [], "filed_documents": [], "judgments": [], "choices": []}
if "w500" in MODES:
    run(ir500, ONE, "wages500__one")
