"""作り直した版の候補の評価を、直す前の版で「全部の分かれ目を1つの候補に決めた」評価と突き合わせる（使い捨て。テストにしない。2026-11-12 の4回目）。

作り直した版は、値ごとに依存する分かれ目 D だけで組合せを評価し、ほかの分かれ目には依存しないとする。これを確かめるため、全部の
分かれ目（未入力の判断・選択・候補のある注入・読んだときだけ開く1か所・根拠のない端数と読みの候補）の候補を、分かれ目の ID ごとに
決まった乱数で1つ選び（標本）、直す前の版で、各分かれ目の候補をその1つだけにして評価する（分かれ目が開かないので、その組だけの値）。
作り直した版の結果をその標本に当てはめた値（確定ならその値、未確定なら標本の候補に合う outcomes の値、幅なら幅）と比べる。
依存する分かれ目の外の分かれ目が値を変えるなら（2つ以上の分かれ目が同時に変わるときだけでも）、標本のどれかで食い違う。

比べるもの（値ごと）：
- 作り直した版が上限を超えた（評価しなかった）値は比べない（対象外かどうかも）。注入されていない（候補を持たない）注入点で
  未確定の値は、値を比べない（対象外は比べる）。
- 直す前の版が対象外なら、作り直した版も対象外（依存する組のどれかで対象外なら対象外にする規則）。
- 作り直した版が対象外なら比べない（標本の組では対象外でないことがある）。
- どちらも値があれば、作り直した版の値（標本に当てはめたもの。幅ならその範囲）に直す前の版の値が入る。
- 状態（予測・見積り・計画）：直す前の版の状態は作り直した版の状態に含まれる。

使い方（リポジトリの根で）：
  python -I -X utf8 scripts/IMPL8_core-perf_sample.py <直す前の src> <作り直した版の結果のディレクトリ> <標本の数> <出力のファイル> [家庭の番号,…]
作り直した版の結果は IMPL5_core-perf_snapshot.py（PERF_MODES=multi）の出力（同じ問い）。
環境変数 PERF_SAMPLE_DIR を渡すと、標本ごとの直す前の版の結果をそこに残す（<家庭>__s<番号>.json。IMPL8_core-perf_classify.py が使う）。
"""
import dataclasses
import glob
import hashlib
import importlib
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
old_src, new_dir, n_samples, out_path = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
which = sys.argv[5].split(",") if len(sys.argv) > 5 else None
sys.path.insert(0, os.path.abspath(old_src))

E = importlib.import_module("okura_core.evaluate")
from okura_core.country import build_system  # noqa: E402
from okura_core.result import dumps  # noqa: E402

MULTI = {
    "income_tax_years": [2025, 2026],
    "resident_tax_fiscal_years": [2026, 2027],
    "kokuho_fiscal_years": [2026, 2027],
    "dependent_judgment_dates": ["2026-04-01"],
    "scenarios": [],
}


def pick(seed: int, slot_id: str, labels: list[str]) -> str:
    h = hashlib.sha256(f"{seed}\0{slot_id}".encode("utf-8")).digest()
    return labels[int.from_bytes(h[:8], "big") % len(labels)]


SEED = [0]
orig_resolve = E.resolve_decisions
orig_rounding = E.rounding_slots


def one(slot):
    lab = pick(SEED[0], slot.id, [c.label for c in slot.candidates])
    return dataclasses.replace(slot, candidates=tuple(c for c in slot.candidates if c.label == lab))


def resolve(ctx, reg):
    d = orig_resolve(ctx, reg)
    return dataclasses.replace(d, open=tuple(one(s) for s in d.open), lazy=tuple(one(s) for s in d.lazy))


def rounding(reg):
    return tuple((one(s), spec) for s, spec in orig_rounding(reg))


E.resolve_decisions = resolve
E.rounding_slots = rounding
system = build_system()


def sample_labels(seed: int, value: dict) -> dict[str, str]:
    out = {}
    u = value.get("undetermined") or {}
    for sp in list(u.get("splits") or []) + list(value.get("evaluated") or []):
        out[sp["id"]] = pick(seed, sp["id"], sp["candidates"]) if sp.get("candidates") else None
    return out


def projected(seed: int, v: dict):
    """作り直した版の値を標本に当てはめたもの：("値", 値) か ("比べない", 理由)。"""
    if v.get("out_of_scope"):
        return ("比べない", "作り直した版が対象外")
    u = v.get("undetermined")
    if u is None:
        return ("値", v["value"])
    if any("評価しなかった理由" in sp["target"] for sp in u["splits"]):
        return ("比べない", "上限を超えた")
    if not u["outcomes"]:
        return ("比べない", "注入されていない（候補なし）")
    for oc in u["outcomes"]:
        if all(pick(seed, sid, next(sp["candidates"] for sp in u["splits"] if sp["id"] == sid)) == lab for sid, lab in oc["conditions"].items()):
            return ("値", oc["value"])
    return ("食い違い", "標本に合う outcomes がない")


def contains(new, old) -> bool:
    if isinstance(new, dict) and new.get("type") == "yen_range":
        return isinstance(old, dict) and old.get("type") == "yen" and new["min"] <= old["amount"] <= new["max"]
    if isinstance(new, dict) and "amount" in new and isinstance(old, dict) and "amount" in old and new.get("type") == old.get("type"):
        return new["amount"] == old["amount"]
    if not isinstance(new, dict) and isinstance(old, dict) and old.get("type") == "yen":
        return new == old["amount"]  # outcomes の金額は数
    if not isinstance(new, dict) and isinstance(old, dict):
        return new == old.get("value")
    return new == old


lines = []
total = {"比べた": 0, "食い違い": 0}
for path in sorted(glob.glob("packages/ir/src/okura_ir/examples/valid/*.json")):
    name = os.path.splitext(os.path.basename(path))[0]
    if which is not None and name[:2] not in which:
        continue
    new_path = os.path.join(new_dir, name + "__multi.json")
    if not os.path.exists(new_path):
        continue
    new = json.load(open(new_path, encoding="utf-8"))
    new_values = {v["id"]: v for s in new["scenarios"] for v in s["values"]}
    ir = json.load(open(path, encoding="utf-8"))
    compared = bad = 0
    for k in range(n_samples):
        SEED[0] = k
        txt = dumps(E.evaluate(ir, MULTI, system=system))
        if os.environ.get("PERF_SAMPLE_DIR"):  # 標本の結果を残す（IMPL8_core-perf_classify.py が使う）
            os.makedirs(os.environ["PERF_SAMPLE_DIR"], exist_ok=True)
            with open(os.path.join(os.environ["PERF_SAMPLE_DIR"], f"{name}__s{k}.json"), "w", encoding="utf-8") as f:
                f.write(txt)
        old = json.loads(txt)
        for ov in (v for s in old["scenarios"] for v in s["values"]):
            nv = new_values.get(ov["id"])
            if nv is None:
                continue
            nu = nv.get("undetermined") or {}
            if any("評価しなかった理由" in sp["target"] for sp in nu.get("splits") or []):
                continue  # 作り直した版が上限を超えて評価しなかった値（基準の組でだけ集めた。対象外も比べない）
            if ov.get("out_of_scope"):
                if not nv.get("out_of_scope"):
                    bad += 1
                    lines.append(f"{name} 標本{k} {ov['id']}: 直す前は対象外、作り直した版は対象外でない")
                continue
            if ov.get("undetermined"):
                continue  # 注入されていない注入点など（標本では候補のない分かれ目だけが残る）
            kind, val = projected(k, nv)
            if kind == "比べない":
                continue
            compared += 1
            if kind == "食い違い" or not contains(val, ov["value"]):
                bad += 1
                lines.append(f"{name} 標本{k} {ov['id']}: 作り直した版 {json.dumps(val, ensure_ascii=False)} / 直す前 {json.dumps(ov['value'], ensure_ascii=False)}")
                continue
            extra = set(ov["states"]) - set(nv["states"])
            if extra:
                bad += 1
                lines.append(f"{name} 標本{k} {ov['id']}: 状態 {sorted(extra)} が作り直した版にない")
    total["比べた"] += compared
    total["食い違い"] += bad
    msg = f"{name}: 標本 {n_samples}・比べた値 {compared}・食い違い {bad}"
    print(msg, flush=True)
    lines.append(msg)
lines.append(f"合計 {total}")
print(f"合計 {total}")
with open(out_path, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
