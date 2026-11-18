"""R2B_kabu: 株式等の配当・譲渡の「申告の選択」によって、判定に使う各制度の所得の値がどう変わるかを、
仮説（docs/hypotheses/20261109_round2b_kabu-model.md）の算入規則で例について計算し、性質を検査する。

実行（Windows）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2B_kabu_scenarios.py

- ネットワークに接続しない。標準ライブラリのみ。
- これは仮説の規則を写した計算であり、法令の正しさを確かめるものではない（確かめ方は推測の文書に書く）。
- 出力：scripts/results/R2B_kabu_scenarios/scenarios.json、scenarios.md

基準額（このスクリプトで使う値と出典の文書）：
- 令和7年分 給与所得控除：給与収入190万円以下は65万円（docs/public-sources/20261109_R1-laws_income-tax.md §2）
- 令和7年分 扶養親族の合計所得金額 58万円以下、勤労学生 85万円以下かつ給与所得等以外 10万円以下、
  特定親族 123万円以下（同 §2・§3）
- 令和8年度分 住民税：扶養親族 58万円以下、特定親族 123万円以下（docs/public-sources/20261109_R1-laws_local-tax.md §2・§3）
- 住民税の未成年者等の非課税 135万円（地方税法第295条第1項第2号。docs/public-sources/20261109_impl-prep_juminzei-hikazei-fuyo-shinkoku.md）
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "scripts" / "results" / "R2B_kabu_scenarios"

R7 = {"kyuyo_min_deduction": 650_000, "fuyo_limit": 580_000, "kinro_limit": 850_000, "kinro_other_limit": 100_000,
      "tokutei_shinzoku_limit": 1_230_000, "jumin_fuyo_limit": 580_000, "jumin_hikazei_135": 1_350_000}


def kyuyo_shotoku_r7(income):
    """令和7年分の給与所得（給与収入190万円以下の範囲だけ。65万円の最低額）。範囲外は扱わない。"""
    if income > 1_900_000:
        raise ValueError("この例では給与収入190万円以下だけを扱う")
    return max(0, income - R7["kyuyo_min_deduction"])


def stock_measures(x):
    """仮説 H2 の算入規則。x は1人1年分の事実と選択。

    x の項目（円）：
      kyuyo_income            給与収入
      div_listed              上場株式等の配当等（大口株主等以外、特定上場株式等の配当等）の収入金額の合計
      div_mode                "fuyo"（申告不要）/ "sogo"（総合課税）/ "bunri"（申告分離課税）
      gain_withholding_acct   源泉徴収選択口座の上場株式等の譲渡所得等の金額（損失はマイナス）
      gain_acct_declared      源泉徴収選択口座の分を申告するか（True/False）
      gain_other              簡易申告口座・一般口座の上場株式等の譲渡所得等の金額（申告が必要。損失はマイナス）
      carry_loss              前年以前3年内の上場株式等に係る譲渡損失の繰越額（連続申告の要件を満たすもの）
      nisa_gain               NISA口座の譲渡益（非課税）
    """
    kyuyo = kyuyo_shotoku_r7(x["kyuyo_income"])
    # 譲渡（申告する分の合計。損失は 0 とみなす：措法37条の11①後段）
    gain = x["gain_other"] + (x["gain_withholding_acct"] if x["gain_acct_declared"] else 0)
    gain_loss = min(0, gain)
    gain_pos = max(0, gain)
    # 配当
    div_sogo = x["div_listed"] if x["div_mode"] == "sogo" else 0
    div_bunri = x["div_listed"] if x["div_mode"] == "bunri" else 0
    # 損益通算（措法37条の12の2①：申告分離の配当等の金額を限度）
    tsusan = min(-gain_loss, div_bunri)
    div_bunri_after = div_bunri - tsusan
    # 繰越控除（措法37条の12の2⑤：譲渡所得等と配当所得等（損益通算後）を限度。順序は譲渡から先、なお残れば配当：措令25条の11の2⑧二）
    carry = x["carry_loss"]
    c1 = min(carry, gain_pos)
    c2 = min(carry - c1, div_bunri_after)
    gain_after_carry = gain_pos - c1
    div_after_carry = div_bunri_after - c2
    sogo = kyuyo + div_sogo  # 総合課税の所得（この例では給与と総合課税の配当だけ）
    m = {}
    # 所得税：合計所得金額＝総合課税の所得＋分離（損益通算後・繰越控除前）
    m["所得税.合計所得金額"] = sogo + div_bunri_after + gain_pos
    # 所得税：総所得金額等（所得控除・医療費控除の足切りの基礎）＝繰越控除後
    m["所得税.総所得金額等"] = sogo + div_after_carry + gain_after_carry
    # 勤労学生の「合計所得金額のうち給与所得等以外の所得に係る部分」（給与以外はすべて株式等とする例）
    m["所得税.勤労学生_給与所得等以外"] = div_sogo + div_bunri_after + gain_pos
    # 住民税（令和6年度分以後は所得税と同じ課税方式）：合計所得金額・総所得金額等は所得税と同じ構造
    m["住民税.合計所得金額"] = m["所得税.合計所得金額"]
    m["住民税.総所得金額等"] = m["所得税.総所得金額等"]
    # 国保：基礎控除前の「総所得金額及び山林所得金額並びに他の所得と区分して計算される所得の金額」（軽減判定は繰越控除後）
    m["国保.所得の合算額(繰越控除後)"] = sogo + div_after_carry + gain_after_carry
    # 健保：保険者のデータがなければ決まらない（配当・譲渡を年間収入に入れるか）
    m["健保.年間収入への算入"] = "未確定（保険者の規則が必要）" if (x["div_listed"] or x["gain_withholding_acct"] or x["gain_other"]) else "株式等の収入なし"
    m["_内訳"] = {"給与所得": kyuyo, "総合配当": div_sogo, "分離配当(通算前)": div_bunri, "損益通算額": tsusan,
                  "分離配当(通算後)": div_bunri_after, "申告する譲渡(損失は0)": gain_pos, "繰越控除(譲渡)": c1, "繰越控除(配当)": c2,
                  "NISA(非課税・不算入)": x["nisa_gain"]}
    return m


def judge_r7(m):
    """令和7年分・令和8年度分の境目に当てる（扶養・勤労学生・特定親族・住民税の135万円）。"""
    g = m["所得税.合計所得金額"]
    return {
        "所得税.扶養親族(58万以下)": g <= R7["fuyo_limit"],
        "所得税.特定親族(58万超123万以下)": R7["fuyo_limit"] < g <= R7["tokutei_shinzoku_limit"],
        "所得税.勤労学生(85万以下かつ給与等以外10万以下)": g <= R7["kinro_limit"] and m["所得税.勤労学生_給与所得等以外"] <= R7["kinro_other_limit"],
        "住民税.扶養親族(58万以下)": m["住民税.合計所得金額"] <= R7["jumin_fuyo_limit"],
        "住民税.未成年者等の非課税(135万以下)": m["住民税.合計所得金額"] <= R7["jumin_hikazei_135"],
    }


BASE = {"kyuyo_income": 0, "div_listed": 0, "div_mode": "fuyo", "gain_withholding_acct": 0, "gain_acct_declared": False,
        "gain_other": 0, "carry_loss": 0, "nisa_gain": 0}
SCENARIOS = [
    # S1：19〜22歳の学生。給与110万円、源泉徴収選択口座で上場株式の配当20万円。配当の課税方式の3通り
    ("S1-不要", {"kyuyo_income": 1_100_000, "div_listed": 200_000, "div_mode": "fuyo"}),
    ("S1-総合", {"kyuyo_income": 1_100_000, "div_listed": 200_000, "div_mode": "sogo"}),
    ("S1-分離", {"kyuyo_income": 1_100_000, "div_listed": 200_000, "div_mode": "bunri"}),
    # S2：学生。給与100万円、源泉徴収選択口座の譲渡益8万円（配当なし）。口座を申告するか
    ("S2-不要", {"kyuyo_income": 1_000_000, "gain_withholding_acct": 80_000, "gain_acct_declared": False}),
    ("S2-申告", {"kyuyo_income": 1_000_000, "gain_withholding_acct": 80_000, "gain_acct_declared": True}),
    # S3：一般口座の譲渡損30万円と、申告分離の配当10万円の損益通算（配当は通算で0になる）
    ("S3-分離で通算", {"kyuyo_income": 0, "div_listed": 100_000, "div_mode": "bunri", "gain_other": -300_000}),
    ("S3-総合(通算不可)", {"kyuyo_income": 0, "div_listed": 100_000, "div_mode": "sogo", "gain_other": -300_000}),
    # S4：繰越損失40万円。源泉徴収選択口座の譲渡益30万円と分離の配当20万円を申告（合計所得金額は繰越前、総所得金額等は繰越後）
    ("S4-繰越", {"kyuyo_income": 0, "div_listed": 200_000, "div_mode": "bunri", "gain_withholding_acct": 300_000,
                 "gain_acct_declared": True, "carry_loss": 400_000}),
    # S5：NISA の譲渡益100万円だけ
    ("S5-NISA", {"kyuyo_income": 0, "nisa_gain": 1_000_000}),
]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, over in SCENARIOS:
        x = dict(BASE)
        x.update(over)
        m = stock_measures(x)
        rows.append({"scenario": name, "input": x, "measures": m, "judge": judge_r7(m)})
    # 性質の検査
    props = []
    by = {r["scenario"]: r for r in rows}
    num_keys = ["所得税.合計所得金額", "所得税.総所得金額等", "住民税.合計所得金額", "国保.所得の合算額(繰越控除後)"]
    for a, b in (("S1-不要", "S1-総合"), ("S1-不要", "S1-分離"), ("S2-不要", "S2-申告")):
        ok = all(by[a]["measures"][k] <= by[b]["measures"][k] for k in num_keys)
        props.append({"id": f"P1 {a}≦{b}", "claim": "申告不要を選ぶと、税・国保の所得の値は申告した場合以下", "ok": ok})
    for r in rows:
        m = r["measures"]
        props.append({"id": f"P2 {r['scenario']}", "claim": "総所得金額等（繰越控除後）≦ 合計所得金額（繰越控除前）",
                      "ok": m["所得税.総所得金額等"] <= m["所得税.合計所得金額"]})
        props.append({"id": f"P3 {r['scenario']}", "claim": "住民税の合計所得金額＝所得税の合計所得金額（課税方式の一致）",
                      "ok": m["住民税.合計所得金額"] == m["所得税.合計所得金額"]})
    props.append({"id": "P4 S5", "claim": "NISA の譲渡益は合計所得金額に入らない", "ok": by["S5-NISA"]["measures"]["所得税.合計所得金額"] == 0})
    out = {"rows": rows, "properties": props}
    (OUT / "scenarios.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    keys = num_keys + ["所得税.勤労学生_給与所得等以外"]
    jkeys = list(rows[0]["judge"].keys())
    md = ["# R2B_kabu_scenarios 結果", "", "## 所得の値（円）", "",
          "| 例 | " + " | ".join(keys) + " |", "|---|" + "---|" * len(keys)]
    for r in rows:
        md.append(f"| {r['scenario']} | " + " | ".join(f"{r['measures'][k]:,}" for k in keys) + " |")
    md += ["", "## 判定（令和7年分・令和8年度分の境目）", "", "| 例 | " + " | ".join(jkeys) + " |", "|---|" + "---|" * len(jkeys)]
    for r in rows:
        md.append(f"| {r['scenario']} | " + " | ".join("○" if r["judge"][k] else "×" for k in jkeys) + " |")
    md += ["", "## 内訳", ""] + [f"- {r['scenario']}: {r['measures']['_内訳']}" for r in rows]
    md += ["", f"## 性質の検査：{sum(p['ok'] for p in props)} / {len(props)}", ""] + [f"- {p['id']}: {'OK' if p['ok'] else 'NG'}（{p['claim']}）" for p in props]
    (OUT / "scenarios.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    return 0 if all(p["ok"] for p in props) else 1


if __name__ == "__main__":
    sys.exit(main())
