"""直す前と後の結果の JSON を、根拠の参照の形の違い（番号 → 項目）を戻して比べる（使い捨て。テストにしない）。

  python -I -X utf8 scripts/IMPL5_core-perf_compare.py <前のディレクトリ> <後のディレクトリ>

前も後も同じ結果の形（根拠の一覧 basis の番号。結果のスキーマの版 1 以降）のときは、環境変数 PERF_SAME_SCHEMA=1 で形を戻さずに比べる
（2026-11-12 の2回目の計測）。PERF_SAME_SCHEMA=2 は何も戻さずに比べる（2026-11-12 の3回目。前も後も年齢の境目を持つ版）。
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
before_dir, after_dir = sys.argv[1], sys.argv[2]


def normalize_after(d):
    if not d.get("ok"):
        return d
    table = d.pop("basis")
    d["result_schema_version"] = "0"
    d["versions"]["result_schema"] = "0"
    d["query"].pop("forms", None)
    for sc in d["scenarios"]:
        sc.pop("differences", None)
        sc.pop("forms", None)
        for v in sc["values"]:
            v["basis"] = [table[i] for i in v["basis"]]
        for b in sc["boundaries"]:
            b["criterion"]["basis"] = table[b["criterion"]["basis"]]
    return d


def sort_reasons(d):
    """対象外の理由の文（「／」でつないだもの）の並びをそろえる（PERF_SORT_REASONS=1。2026-11-12 の3回目）。

    直す前の版でも、同じ入力の2回の実行で並びが変わる（例 08：値の由来の集め方が文字列の集合の順に依存し、プロセスごとに
    文字列のハッシュが変わる。scripts/results/IMPL7_core-perf/compare_rerun_before.txt）ので、並びを除いて比べる。"""
    if isinstance(d, dict):
        return {k: ("／".join(sorted(v.split("／"))) if k == "reason" and isinstance(v, str) else sort_reasons(v)) for k, v in d.items()}
    if isinstance(d, list):
        return [sort_reasons(x) for x in d]
    return d


def first_diff(a, b, path="$"):
    if type(a) is not type(b):
        return f"{path}: 型 {type(a).__name__} != {type(b).__name__}"
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                return f"{path}.{k}: 片方にない"
            r = first_diff(a[k], b[k], f"{path}.{k}")
            if r:
                return r
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: 長さ {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            r = first_diff(x, y, f"{path}[{i}]")
            if r:
                return r
        return None
    return None if a == b else f"{path}: {str(a)[:200]} != {str(b)[:200]}"


same = diff = 0
for name in sorted(os.listdir(before_dir)):
    pa, pb = os.path.join(before_dir, name), os.path.join(after_dir, name)
    if not os.path.exists(pb):
        print(f"{name}: 後の結果がない")
        continue
    a = json.load(open(pa, encoding="utf-8"))
    b = json.load(open(pb, encoding="utf-8"))
    if "error" in a or "error" in b:
        print(f"{name}: 前 {a.get('error', 'ok')} / 後 {b.get('error', 'ok')}")
        continue
    if os.environ.get("PERF_SAME_SCHEMA") == "2":
        pass  # 前も後も同じ結果の形（2026-11-12 の3回目）：何も戻さずに比べる（入力のハッシュだけ除く）
    elif os.environ.get("PERF_SAME_SCHEMA") != "1":
        b = normalize_after(b)
    elif b.get("ok"):
        # 後で足した年齢の境目（結果のスキーマの版 2。2026-11-12）を戻す：前の版にはない項目
        b["result_schema_version"] = a["result_schema_version"]
        b["versions"]["result_schema"] = a["versions"]["result_schema"]
        for sc in b["scenarios"]:
            sc.pop("age_boundaries", None)
    if os.environ.get("PERF_SORT_REASONS") == "1":
        a, b = sort_reasons(a), sort_reasons(b)
    a["versions"].pop("input_sha256", None)
    b["versions"].pop("input_sha256", None)
    r = first_diff(a, b)
    if r:
        diff += 1
        print(f"{name}: 違う {r}")
    else:
        same += 1
        print(f"{name}: 同じ")
print(f"同じ {same} / 違う {diff}")
