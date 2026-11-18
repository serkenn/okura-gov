"""IMPL2 phase2c: 取得済みのテキストに「端数」の語などがあるかを走査する（公開資料の文書の「定めがない」「見つからなかった」の根拠）。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ。ネットワークは使わない）:
  C:/Users/user/.pyenv/pyenv-win/versions/3.11.9/python.exe -I -X utf8 scripts/IMPL2_phase2c_scans.py

- 入力：scripts/results/IMPL2_phase2c_egov/（条文のテキスト）、IMPL2_phase2c_nta/（国税庁のページのテキスト）、IMPL2_genka_pdftext/（PDF から取り出した文字）。
- 出力：scripts/results/IMPL2_phase2c_scans/scans.json
"""
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
RES = ROOT / "scripts" / "results"
OUT = RES / "IMPL2_phase2c_scans"
EGOV = RES / "IMPL2_phase2c_egov"
ASOFS = ["2025-12-31", "2026-12-31"]


def sections(path):
    t = path.read_text(encoding="utf-8")
    return {p.split("\n", 1)[0].split(" ")[0]: p for p in re.split(r"(?m)^## Num=", t)[1:]}


def pdf_pages(name):
    rows = [ln.rstrip("\n").split("\t") for ln in (RES / "IMPL2_genka_pdftext" / f"{name}_text.tsv").open(encoding="utf-8", errors="replace")]
    pages = {}
    for r in rows:
        if len(r) >= 5 and re.fullmatch(r"[0-9]+", r[0]):
            pages.setdefault(int(r[0]), []).append(r)

    def y(r):
        try:
            return round(float(r[2]))
        except ValueError:
            return 0

    out = {}
    for pg, rs in pages.items():
        lines = {}
        for r in rs:
            lines.setdefault(y(r), []).append(r)
        text = "\n".join("".join(c[4] for c in sorted(lines[k], key=lambda r: float(r[1]) if re.match(r"^[0-9.]+$", r[1]) else 0))
                         for k in sorted(lines, reverse=True))
        out[pg] = re.sub(r"[^\u0020-\u007e\u3000-\u30ff\u4e00-\u9fff\uff00-\uffef\n]", "", text)
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    res = {}
    # 1. 償却に関する条の「円未満」「端数」
    arts = {"shorei": ["120", "120_2", "125", "126", "129", "131", "132", "134", "138", "139"], "shoho": ["49", "51"]}
    res["genka_articles"] = {}
    for short, nums in arts.items():
        for asof in ASOFS:
            secs = sections(EGOV / "genka" / f"{short}_{asof}.txt")
            for n in nums:
                t = secs.get(n, "")
                res["genka_articles"][f"{short}_{n}_{asof}"] = {
                    "found": bool(t), "円未満": t.count("円未満"), "一円": t.count("一円"),
                    "端数の行": [ln.strip()[:140] for ln in t.split("\n") if "端数" in ln]}
    # 2. 耐用年数省令の本則（grep の結果）
    res["taiyo"] = {}
    for asof in ASOFS:
        p = EGOV / "genka" / f"grep_taiyo_{asof}.txt"
        t = p.read_text(encoding="utf-8")
        res["taiyo"][asof] = {"一円未満": t.count("一円未満"), "円未満": t.count("円未満"), "端数の行数": sum(1 for ln in t.split("\n") if "端数" in ln),
                              "端数の行": [ln.strip()[:120] for ln in t.split("\n") if "端数" in ln][:12]}
    # 3. 配当控除など
    res["no_hasu"] = {}
    for label, f, num in (("所法92", "haito/shoho", "92"), ("所法24", "haito/shoho", "24"), ("所法76", "hasu/shoho", "76"), ("所法77", "hasu/shoho", "77")):
        for asof in ASOFS:
            secs = sections(EGOV / f"{f}_{asof}.txt")
            res["no_hasu"][f"{label}_{asof}"] = secs[num].count("端数")
    # 4. 手引き・書き方の PDF
    res["pdf"] = {}
    for name in ("t034", "t025", "t019", "t037", "t039", "t001"):
        pages = pdf_pages(name)
        total = sum(len(v) for v in pages.values())
        yen = {}
        junjo = {}
        for pg, t in pages.items():
            hits = [m.group(0) for m in re.finditer(r"[1１一]円未満", t)]
            if hits:
                yen[pg] = [t[max(0, m.start() - 30):m.start() + 30].replace("\n", " ") for m in re.finditer(r"[1１一]円未満", t)][:4]
            if name == "t001":
                j = [t[max(0, m.start() - 30):m.start() + 30].replace("\n", " ") for m in re.finditer(r"順序|順次", t)]
                if j:
                    junjo[pg] = j[:4]
        res["pdf"][name] = {"pages": len(pages), "chars": total, "1円未満": yen, "順序_順次": junjo}
        if name == "t001":
            d = OUT / "t001_pages"
            d.mkdir(parents=True, exist_ok=True)
            for pg, t in pages.items():
                (d / f"p{pg:03d}.txt").write_text(t, encoding="utf-8")
    # 5. 手引きの HTML・FAQ
    res["html"] = {}
    for rel in ("tebiki_html/t3_2_07", "tebiki_html/t3_4_28", "ta/ta_1600", "ta/ta_2100", "ta/ta_2105", "ta/ta_2106", "genka_keisan2/keisan_r7_teigakuho",
                "genka_keisan2/keisan_r7_ikkatsu", "genka_keisan2/keisan_r7_shogaku", "genka_keisan2/keisan_r7_kikan", "genka_keisan2/keisan_r7_zumi",
                "genka_keisan2/keisan_r7_kyuteigaku", "tsutatsu2/kihon_08_05"):
        t = (RES / "IMPL2_phase2c_nta" / f"{rel}.txt").read_text(encoding="utf-8")
        res["html"][rel] = {"端数の行": [ln.strip()[:120] for ln in t.split("\n") if "端数" in ln and "端数処理" != ln.strip()],
                            "1円未満": len(re.findall(r"[1１一]円未満", t))}
    (OUT / "scans.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("taiyo", "no_hasu")}, ensure_ascii=False, indent=1)[:1600])
    print(json.dumps({k: {"1円未満": v["1円未満"], "順序_順次": v["順序_順次"], "chars": v["chars"]} for k, v in res["pdf"].items()}, ensure_ascii=False, indent=1)[:2500])
    bad = {k: v for k, v in res["genka_articles"].items() if v["円未満"] or v["一円"] or not v["found"]}
    print("genka_articles_with_yen", json.dumps(bad, ensure_ascii=False)[:800])
    print(json.dumps({k: v for k, v in res["html"].items() if v["1円未満"] or v["端数の行"]}, ensure_ascii=False, indent=0)[:1200])


if __name__ == "__main__":
    main()
