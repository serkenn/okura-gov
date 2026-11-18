"""直す前と後で違う値を、基準（オラクル・標本）に当てて分ける（使い捨て。テストにしない。2026-11-12 の4回目）。

入力：
- 直す前・後の結果（IMPL5_core-perf_snapshot.py の PERF_MODES=multi の出力。同じ問い）。
- オラクル（IMPL8_core-perf_oracle.py：直す前の版で上限を引き上げ、人のつながりの直積の全部を評価したもの。あれば）。
- 標本（IMPL8_core-perf_sample.py を PERF_SAMPLE_DIR つきで動かした、直す前の版で全部の分かれ目を1つの候補に決めた評価）。

値の区分：確定・未確定（評価：候補ごとの値つき）・未確定（注入：候補を持たない注入点）・未確定（上限：評価しなかった）・対象外。
違う値ごとの判定（比べる項目：値・状態・未確定の分かれ目と outcomes・対象外の区分と理由の文〔「／」の並びをそろえる〕・evaluated の ID）：
- オラクルがあり、オラクルが上限を超えていない値：後がオラクルと同じなら「後＝オラクル」。前もオラクルと違えば、前の近似の誤り。
- オラクルがない値は標本で：前が確定（値 X）で、標本のどれかで X と違う（又は対象外）なら「前は誤って断定」。後が上限で、標本の値が
  分かれるなら「後の未確定（上限）は値が本当に分かれる」、分かれないなら「標本では分かれない（後は安全側）」。後が評価した値なら、
  IMPL8_core-perf_sample.py の突き合わせ（食い違い 0）で確かめた。
- 由来の項目（facts・depends_on・basis）だけの違いは別に数える。

使い方（リポジトリの根で）：
  python -I -X utf8 scripts/IMPL8_core-perf_classify.py <前> <後> <オラクル（なければ -）> <標本のディレクトリ> <出力のファイル>
"""
import collections
import glob
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
before_dir, after_dir, oracle_dir, sample_dir, out_path = sys.argv[1:6]


def cls(v):
    if v.get("out_of_scope"):
        return "対象外"
    u = v.get("undetermined")
    if u:
        if any("評価しなかった理由" in s["target"] for s in u["splits"]):
            return "未確定(上限)"
        if not u["outcomes"]:
            return "未確定(注入)"
        return "未確定(評価)"
    return "確定"


def core(v):
    """結論の項目（値・状態・未確定・対象外・evaluated）。対象外の理由の文は「／」の並びをそろえる。"""
    oos = v.get("out_of_scope")
    if oos:
        oos = {**oos, "reason": "／".join(sorted(oos["reason"].split("／")))}
    u = v.get("undetermined")
    if u:
        u = {"splits": sorted(s["id"] for s in u["splits"]), "outcomes": sorted(json.dumps(o, ensure_ascii=False, sort_keys=True) for o in u["outcomes"])}
    return {
        "value": v.get("value"),
        "states": sorted(v["states"]),
        "undetermined": u,
        "out_of_scope": oos,
        "evaluated": sorted((e["id"], e["splits_conclusion"]) for e in v.get("evaluated") or []),
    }


def load(path):
    if not os.path.exists(path):
        return None
    r = json.load(open(path, encoding="utf-8"))
    return {v["id"]: v for s in r.get("scenarios", []) for v in s["values"]}


lines = []
grand = collections.Counter()
for bpath in sorted(glob.glob(os.path.join(before_dir, "*__multi.json"))):
    name = os.path.basename(bpath)
    before, after = load(bpath), load(os.path.join(after_dir, name))
    if after is None:
        continue
    oracle = load(os.path.join(oracle_dir, name)) if oracle_dir != "-" else None
    samples = [load(p) for p in sorted(glob.glob(os.path.join(sample_dir, name.replace("__multi.json", "") + "__s*.json")))]
    trans = collections.Counter()
    verdict = collections.Counter()
    examples = collections.defaultdict(list)
    prov_only = 0
    for vid in sorted(set(before) | set(after)):
        b, a = before.get(vid), after.get(vid)
        if b is None or a is None:
            trans[("なし" if b is None else cls(b), "なし" if a is None else cls(a))] += 1
            continue
        cb, ca = core(b), core(a)
        if cb == ca:
            if any(b.get(k) != a.get(k) for k in ("facts", "depends_on", "basis")):
                prov_only += 1
            continue
        t = (cls(b), cls(a))
        trans[t] += 1
        o = oracle.get(vid) if oracle else None
        if o is not None and cls(o) != "未確定(上限)":
            co = core(o)
            if ca == co:
                key = "後＝オラクル（前はオラクルと違う：前の近似の誤り）"
            elif {k: ca[k] for k in ("value", "states", "undetermined", "out_of_scope")} == {k: co[k] for k in ("value", "states", "undetermined", "out_of_scope")}:
                key = "後＝オラクル（evaluated の並べ方だけ違う）"
            else:
                key = "後≠オラクル"
        elif t[0] == "確定" and samples:
            vals = [s.get(vid) for s in samples if s is not None and s.get(vid) is not None]
            differs = [s for s in vals if s.get("out_of_scope") or (not s.get("undetermined") and s.get("value") != b.get("value"))]
            if differs:
                key = "前は誤って断定（標本で値・対象外が変わる）"
            elif t[1] == "未確定(上限)":
                key = "前の確定は標本と合う・後は上限（安全側）"
            else:
                key = "前の確定は標本と合う・後も評価した"
        elif t[1] == "未確定(上限)" and samples:
            vals = {json.dumps([s.get(vid, {}).get("value"), bool(s.get(vid, {}).get("out_of_scope"))], ensure_ascii=False) for s in samples if s is not None}
            key = "後は上限：標本で値が分かれる" if len(vals) > 1 else "後は上限：標本では分かれない（安全側）"
        elif t[0] in ("未確定(上限)",):
            key = "前は上限で評価しなかった・後は評価した（標本の突き合わせで確かめた）"
        else:
            key = "そのほか（個別に見る）"
        verdict[key] += 1
        if len(examples[key]) < 3:
            examples[key].append(vid)
    lines.append(f"## {name}")
    lines.append(f"- 区分の移り（前 → 後）：{dict(sorted(trans.items()))}")
    for k, n in sorted(verdict.items()):
        lines.append(f"- {k}：{n}（例 {', '.join(examples[k])}）")
        grand[k] += n
    lines.append(f"- 由来の項目（facts・depends_on・basis）だけ違う値：{prov_only}")
lines.append("## 合計")
for k, n in sorted(grand.items()):
    lines.append(f"- {k}：{n}")
open(out_path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("\n".join(lines))
