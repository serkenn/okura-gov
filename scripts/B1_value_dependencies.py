"""実測：値ごとの候補の評価が、依存する分かれ目を少なく数えていないか（B1 の直しの確かめ。2026-11-13）。

架空の家庭（4人が4つの市町村に住む）を、市町村の注入データ（級地・135万円の非課税の判定の時点）なしで評価した結果 R0 と、
注入データを渡して評価した結果を比べる。ネットワークに出ない。家族のデータを使わない（入力は架空の家庭だけ）。

確かめること：
  A. R0 で、所得税の値に、住民税の注入点の分かれ目が1つもない（制度の境目）。
  B. R0 で決まった値（未確定でも対象外でもない値）は、注入データのどの組でも同じ値になる（「決まった」が正しい）。
  C. R0 で未確定の値の、評価した候補ごとの値（outcomes）に、注入データを渡した結果の値が入っている。
  D. 1つの市町村の注入データだけを基準の組から変えたとき、値が変わった値は、R0 でその市町村の分かれ目に依存している
     （ほかの人だけが住む市町村の注入データに依存しないとした値が、本当に変わらない）。

使い方（リポジトリの根で。判定コアの仮想環境）：
  .work/venvs/core/Scripts/python.exe -I -X utf8 scripts/B1_value_dependencies.py scripts/inputs/B1_value_dependencies/family.json scripts/results/B1_value_dependencies/<日時>
  第3引数に r0 を付けると、注入データなしの評価だけをして、依存する市町村の数の分布を出す（直す前のコードとの比較用。A だけ確かめる）。
"""

from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path
from typing import Any

from okura_core.evaluate import evaluate
from okura_core.injection_points import POINTS

QUERY = {"income_tax_years": [2026], "resident_tax_fiscal_years": [2027], "kokuho_fiscal_years": [], "kokunen_fiscal_years": [],
         "dependent_judgment_dates": [], "scenarios": [], "workers": 1}
P_KYUCHI = "住民税.級地"
P_TIMING = "住民税.135万円の非課税の判定の時点"
#: 注入データを引く日（令和9年度：級地は前年の12月31日、判定の時点は賦課期日）を含む適用期間
APPLIES = {"from_on": "2026-01-01", "to_on": "2027-12-31"}


def entry(point: str, code: str, data: Any) -> dict[str, Any]:
    return {
        "id": f"inj-{'kyuchi' if point == P_KYUCHI else 'timing'}-{code}",  # ID は ASCII
        "point": point,
        "issuer": {"kind": "municipality", "code": code},
        "applies": APPLIES,
        "source": {"url": "https://example.invalid/fictional.html", "retrieved_on": "2026-11-13", "source_kind": "自治体の資料"},
        "data": data,
    }


def run(ir: dict[str, Any], injected: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    d = evaluate(ir, QUERY, injected)
    d = d.to_dict() if hasattr(d, "to_dict") else d
    if not d.get("ok", True):
        raise SystemExit("評価に失敗した: " + json.dumps(d.get("errors"), ensure_ascii=False)[:800])
    return {v["id"]: v for v in d["scenarios"][0]["values"]}


def decided(v: dict[str, Any]) -> bool:
    return not v.get("undetermined") and not v.get("out_of_scope")


def shown(v: dict[str, Any]) -> str:
    if v.get("out_of_scope"):
        return "対象外"
    if v.get("undetermined"):
        return "未確定"
    return json.dumps(v.get("value"), ensure_ascii=False, sort_keys=True)


def plain(value: Any) -> Any:
    """結果の値（{"type": …, "amount"・"value": …}）を、未確定の候補ごとの値（outcomes）と同じ生の値にする。"""
    if isinstance(value, dict) and "type" in value:
        return value.get("amount", value.get("value"))
    return value


def municipality_of(split_id: str) -> str | None:
    parts = split_id.split(":")
    return parts[parts.index("municipality") + 1] if "municipality" in parts else None


def main() -> None:
    ir = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out_dir = Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)
    ir.pop("_comment", None)
    codes = sorted({r["attributes"]["municipality_code"] for r in ir["residences"]})
    kyuchi = [c.data for c in POINTS[P_KYUCHI].candidates]
    timing = [c.data for c in POINTS[P_TIMING].candidates]
    labels = {P_KYUCHI: [c.label for c in POINTS[P_KYUCHI].candidates], P_TIMING: [c.label for c in POINTS[P_TIMING].candidates]}
    only_r0 = len(sys.argv) > 3 and sys.argv[3] == "r0"
    options = list(itertools.product(range(len(kyuchi)), range(len(timing))))  # 市町村1つの（級地, 判定の時点）の候補の組

    def injected(choice: dict[str, tuple[int, int]]) -> list[dict[str, Any]]:
        out = []
        for code in codes:
            k, t = choice[code]
            out += [entry(P_KYUCHI, code, kyuchi[k]), entry(P_TIMING, code, timing[t])]
        return out

    r0 = run(ir, [])
    base_choice = {code: options[0] for code in codes}
    combos: list[tuple[str, dict[str, tuple[int, int]], str | None]] = [("基準", base_choice, None)]
    for code in codes:  # 1つの市町村だけを変える
        for opt in options[1:]:
            combos.append((f"{code} だけ {opt}", {**base_choice, code: opt}, code))
    n = len(options)
    for shift in range(1, 6):  # 全部の市町村を同時に変える組（決まった並び）
        combos.append((f"同時 {shift}", {code: options[(i * shift + shift) % n] for i, code in enumerate(codes)}, None))

    problems: list[str] = []
    # A. 所得税の値に住民税の注入点の分かれ目がない
    for vid, v in sorted(r0.items()):
        if v["concept"].startswith("所得税.") and v.get("undetermined"):
            bad = [s["id"] for s in v["undetermined"]["splits"] if s["id"].startswith("注入.住民税.")]
            if bad:
                problems.append(f"A {vid}: 所得税の値が住民税の注入点に依存している {bad[:2]}")
    if only_r0:
        combos = []

    def matches(conditions: dict[str, str], choice: dict[str, tuple[int, int]]) -> bool:
        """未確定の候補の組（分かれ目の ID → 候補の名前）が、注入データの組 choice と食い違わないか（級地・判定の時点の分かれ目だけを見る）。"""
        for sid, label in conditions.items():
            code = municipality_of(sid)
            if code is None or code not in choice:
                continue
            k, t = choice[code]
            if sid.startswith(f"注入.{P_KYUCHI}:") and label != labels[P_KYUCHI][k]:
                return False
            if sid.startswith(f"注入.{P_TIMING}:") and label != labels[P_TIMING][t]:
                return False
        return True

    results: dict[str, dict[str, dict[str, Any]]] = {}
    for name, choice, _changed in combos:
        results[name] = run(ir, injected(choice))
    base = results.get("基準", {})
    changed_values = 0
    for name, choice, changed in combos:
        rk = results[name]
        for vid, v0 in sorted(r0.items()):
            vk = rk.get(vid)
            if vk is None:
                problems.append(f"{name} {vid}: 注入データを渡した結果に値がない")
                continue
            if decided(v0):
                # B. 決まった値は変わらない
                if not decided(vk) or vk.get("value") != v0.get("value"):
                    problems.append(f"B {name} {vid}: 注入データなしで {shown(v0)} と決まった値が {shown(vk)} になった")
            elif v0.get("undetermined") and decided(vk):
                outs = v0["undetermined"].get("outcomes") or []
                # C. 注入データの組に合う候補ごとの値と同じ（候補を評価していない未確定〔outcomes が空〕は比べない）
                fit = [o for o in outs if matches(o.get("conditions") or {}, choice)]
                if outs and not any(o.get("value") == plain(vk.get("value")) for o in fit):
                    problems.append(f"C {name} {vid}: {shown(vk)} が、注入データの組に合う候補ごとの値 {[o.get('value') for o in fit][:6]} にない")
            if changed is not None and shown(vk) != shown(base[vid]):
                # D. 1つの市町村だけを変えて変わった値は、その市町村の分かれ目に依存している
                changed_values += 1
                deps = {municipality_of(s["id"]) for s in (v0.get("undetermined") or {}).get("splits", [])}
                if changed not in deps:
                    problems.append(f"D {name} {vid}: 市町村 {changed} の注入データだけを変えて値が変わった（{shown(base[vid])} → {shown(vk)}）が、依存する分かれ目にその市町村がない")

    per_person: dict[str, dict[str, int]] = {}
    for v in r0.values():
        inst = v["concept"].split(".")[0]
        d = per_person.setdefault(inst, {"決まった": 0, "未確定": 0, "対象外": 0, "上限を超えて評価しなかった": 0})
        if v.get("out_of_scope"):
            d["対象外"] += 1
        elif v.get("undetermined"):
            d["未確定"] += 1
            if any("評価しなかった理由" in json.dumps(s.get("target"), ensure_ascii=False) for s in v["undetermined"]["splits"]):
                d["上限を超えて評価しなかった"] += 1
        else:
            d["決まった"] += 1
    # 依存する市町村の数（注入データなしの結果で、住民税の値が依存する市町村の数の分布）
    spread: dict[int, int] = {}
    for v in r0.values():
        if v["concept"].startswith("住民税.") and v.get("undetermined"):
            k = len({municipality_of(s["id"]) for s in v["undetermined"]["splits"]} - {None})
            spread[k] = spread.get(k, 0) + 1
    summary = {
        "市町村": codes,
        "評価した注入データの組": len(combos),
        "値の数": len(r0),
        "注入データなしの結果（制度ごと）": per_person,
        "住民税の未確定の値が依存する市町村の数（数 → 値の件数）": {str(k): spread[k] for k in sorted(spread)},
        "1つの市町村だけを変えて変わった値の延べの数": changed_values,
        "問題": problems,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1)[:4000])
    if problems:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
