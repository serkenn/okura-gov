"""R2B invoice: scripts/R2B_invoice_egov.py が書いた条文のテキスト（articles_shohi_<asof>.txt）から、
消費税法の本則（第9条・第9条の2・第57条の2 など）と、平成28年法律第15号（所得税法等の一部を改正する法律）の附則の
条（第44条・第51条の2・第51条の3・第52条・第53条・第53条の2）を時点ごとに切り出し、
(1) 時点の間の差分（unified diff）と (2) 文言の有無の検査 を出す。ネットワークには接続しない。

実行（リポジトリのルートで。先に R2B_invoice_egov.py fetch を実行しておく）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2B_invoice_compare.py

結果は scripts/results/R2B_invoice_compare/ に書く。
- articles_<asof>.json：切り出した条（キー → 本文の行）
- diff_<条>_<asof1>_vs_<asof2>.diff：差分がある組だけ
- checks.json / checks.md：文言の検査（期待した文言が、どの時点の本文にあるか）
"""
import difflib
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "scripts" / "results" / "R2B_invoice_egov"
OUT = ROOT / "scripts" / "results" / "R2B_invoice_compare"
ASOFS = ["2025-12-31", "2026-09-30", "2026-11-09", "2027-10-01", "2028-04-01"]
H28 = "## 附則 AmendLawNum=平成二八年三月三一日法律第一五号"
R8 = "## 附則 AmendLawNum=令和八年三月三一日法律第一二号"
KANJI = "〇一二三四五六七八九十百"
ART_RE = re.compile(rf"^第[{KANJI}]+条(の[{KANJI}]+)?$")

# (キー, 条の部分の文字列, [期待する文言]) — 文言が本文にあるかを時点ごとに見る
CHECKS = [
    ("本則9", "千万円以下である者（適格請求書発行事業者を除く。）"),
    ("本則9_2", "その年の前年一月一日から六月三十日までの期間"),
    ("本則9_2", "給与等の金額に相当するもの"),
    ("本則2", "基準期間　個人事業者についてはその年の前々年"),
    ("本則19", "一月一日から十二月三十一日までの期間"),
    ("本則57_2", "第九条第一項本文の規定により消費税を納める義務が免除される事業者を除く。）は、税務署長の登録を受けることができる"),
    ("附則H28_第四十四条", "五年施行日から五年施行日以後六年を経過する日までの日の属する課税期間中である事業者"),
    ("附則H28_第四十四条", "登録開始日以後二年を経過する日の属する課税期間"),
    ("附則H28_第五十一条の二", "五年施行日から五年施行日以後三年を経過する日までの日の属する課税期間"),
    ("附則H28_第五十一条の二", "残額の百分の八十に相当する金額"),
    ("附則H28_第五十一条の三", "令和九年及び令和十年に含まれる各課税期間"),
    ("附則H28_第五十一条の三", "残額の百分の七十に相当する金額"),
    ("附則H28_第五十二条", "五年施行日から五年施行日以後三年を経過する日（同条第一項において「適用期限」という。）"),
    ("附則H28_第五十二条", "百分の八十を乗じて算出した金額"),
    ("附則H28_第五十二条", "一億円を超える場合"),
    ("附則H28_第五十二条", "十億円を超える場合"),
    ("附則H28_第五十三条", "令和十一年九月三十日"),
    ("附則H28_第五十三条", "令和十三年九月三十日"),
    ("附則H28_第五十三条", "令和十年九月三十日までの間に行った控除対象課税仕入れ　百分の七十"),
    ("附則H28_第五十三条", "令和十年十月一日から令和十二年九月三十日までの間に行った控除対象課税仕入れ　百分の五十"),
    ("附則H28_第五十三条", "令和十二年十月一日から令和十三年九月三十日までの間に行った控除対象課税仕入れ　百分の三十"),
    ("附則H28_第五十三条", "百分の五十を乗じて算出した金額"),
    ("附則H28_第一条", "九の二　附則第五十一条の三の規定　令和八年十月一日"),
    ("附則H28_第一条", "八　附則第四十四条及び第四十五条の規定　令和三年十月一日"),
    ("附則R8_第一条", "附則第四十四条の改正規定を除く。）及び附則第九十条の規定　令和八年十月一日"),
    ("附則R8_第九十条", "令和八年十月一日以後に開始する課税期間"),
]


def split_sections(lines):
    """articles_*.txt を「本則<Num>」「附則H28_<条>」「附則R8_<条>」ごとの行の list にする。"""
    secs, cur, mode, pending_caption = {}, None, None, None
    for ln in lines:
        if ln.startswith("## Num="):
            mode, cur = "main", "本則" + ln[len("## Num="):].split(":")[0].strip()
            secs[cur] = []
            continue
        if ln.startswith("## 附則"):
            mode = "H28" if ln.startswith(H28) else ("R8" if ln.startswith(R8) else "other")
            cur = None
            continue
        if mode in ("H28", "R8"):
            s = ln.strip()
            if ART_RE.match(s):
                cur = f"附則{mode}_{s}"
                secs[cur] = [pending_caption] if pending_caption else []
                pending_caption = None
                continue
            if s.startswith("（") and s.endswith("）") and "　" not in s:
                pending_caption = s  # 次の条の見出し
                continue
            if cur:
                secs[cur].append(ln)
        elif mode == "main" and cur:
            secs[cur].append(ln)
    return secs


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    data = {}
    for a in ASOFS:
        p = SRC / f"articles_shohi_{a}.txt"
        lines = p.read_text(encoding="utf-8").splitlines()
        header = [x for x in lines[:5] if x.startswith("#")]
        secs = split_sections(lines)
        data[a] = secs
        (OUT / f"articles_{a}.json").write_text(json.dumps({"header": header, "sections": secs}, ensure_ascii=False, indent=1), encoding="utf-8")
    diffs = []
    keys = sorted({k for s in data.values() for k in s})
    for k in keys:
        for a1, a2 in zip(ASOFS, ASOFS[1:]):
            t1, t2 = data[a1].get(k, []), data[a2].get(k, [])
            if t1 != t2:
                d = list(difflib.unified_diff(t1, t2, fromfile=f"{k}@{a1}", tofile=f"{k}@{a2}", lineterm=""))
                fn = f"diff_{k}_{a1}_vs_{a2}.diff"
                (OUT / fn).write_text("\n".join(d), encoding="utf-8")
                diffs.append({"key": k, "from": a1, "to": a2, "file": fn, "lines_changed": sum(1 for x in d if x[:1] in "+-") - 2})
    checks = []
    for key, phrase in CHECKS:
        row = {"key": key, "phrase": phrase, "present": {}}
        for a in ASOFS:
            body = "".join(data[a].get(key, []))
            row["present"][a] = (phrase in body) if body else None
        checks.append(row)
    (OUT / "checks.json").write_text(json.dumps({"asofs": ASOFS, "sections": keys, "diffs": diffs, "checks": checks}, ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["# R2B invoice 文言の検査", "", "None は「その時点の本文にその条がない」。", "",
          "| 条 | 文言 | " + " | ".join(ASOFS) + " |", "|---|---|" + "---|" * len(ASOFS)]
    for c in checks:
        md.append(f"| {c['key']} | {c['phrase']} | " + " | ".join(str(c['present'][a]) for a in ASOFS) + " |")
    md += ["", "## 差分がある組", ""] + [f"- {d['key']}: {d['from']} → {d['to']}（{d['file']}）" for d in diffs]
    (OUT / "checks.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
