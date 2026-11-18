"""IMPL8 tokutei-shishutsu verify: 取り出した条文の写しと様式の文字から、公開資料の情報（docs/public-sources/20261112_impl-research8_tokutei-shishutsu-laws.md）
の主張を機械的に確かめる。ネットワークは使わない（scripts/IMPL8_tokutei-shishutsu_egov.py extract・scripts/IMPL8_tokutei-shishutsu_pdftext.py の結果を読むだけ）。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL8_tokutei-shishutsu_verify.py

出力 scripts/results/IMPL8_tokutei-shishutsu_verify/checks.json（確かめたことごとに ok・根拠の抜き書き）
"""
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
EGOV = ROOT / "scripts" / "results" / "IMPL8_tokutei-shishutsu_egov"
PDF = ROOT / "scripts" / "results" / "IMPL8_tokutei-shishutsu_pdftext"
OUT = ROOT / "scripts" / "results" / "IMPL8_tokutei-shishutsu_verify"


def article(path, num):
    t = path.read_text(encoding="utf-8")
    m = re.search(rf"^## Num={re.escape(num)}\n(.*?)(?=^## |\Z)", t, re.M | re.S)
    return m.group(1) if m else ""


def para(text, head):
    """全角数字の項番号（例 "１１"）で始まる行。"""
    for line in text.splitlines():
        if line.startswith(head + "　"):
            return line
    return ""


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks = []

    def check(name, ok, evidence):
        checks.append({"name": name, "ok": bool(ok), "evidence": evidence[:400] if isinstance(evidence, str) else evidence})

    a7 = article(EGOV / "shoho_2025-12-31.txt", "57_2")
    a8 = article(EGOV / "shoho_2026-12-31.txt", "57_2")
    check("所法57の2 の本文が令和7年分（asof 2025-12-31）と令和8年分（asof 2026-12-31）で同じ", a7 and a7 == a8, f"len={len(a7)}")
    check("所法57の2① は給与所得控除額の二分の一を超える部分を、第28条第2項の残額から控除する（同条第4項にかかわらず）",
          "給与所得控除額の二分の一に相当する金額を超えるときは" in a8 and "同項及び同条第四項の規定にかかわらず、同条第二項の残額からその超える部分の金額を控除した金額とする" in a8,
          a8.splitlines()[2] if len(a8.splitlines()) > 2 else "")
    check("所法57の2② 第7号の勤務必要経費は合計65万円まで", "六十五万円を超える場合には、六十五万円までの支出に限る" in a8, "")
    check("所法57の2③ 申告書等への記載と明細書・証明の書類の添付がある場合に限り適用", "確定申告書、修正申告書又は更正請求書" in a8 and "添付がある場合に限り、適用する" in a8, para(a8, "３"))
    check("所法57の2② キャリアコンサルタントの証明は第4号・第5号だけで教育訓練に係る部分に限る",
          a8.count("キャリアコンサルタント") >= 2 and "教育訓練に係る部分に限る" in a8, "")
    r = (EGOV / "shorei_2026-12-31.txt").read_text(encoding="utf-8")
    check("所令167の3① 通勤費は航空機の利用を除き、交通機関は1月当たりの定期乗車券の価額の合計額が上限",
          "航空機の利用に係るものを除く" in r and "一月当たりの定期乗車券又は定期乗船券の価額" in r, "")
    check("所令167の3③ 転居費は転任の事実が生じた日以後1年以内", "転任の事実が生じた日以後一年以内" in r, "")
    k = (EGOV / "grep_shoki_2026-12-31.txt").read_text(encoding="utf-8")
    check("所規36の5③ 特別車両料金等から寝台料金で6,600円以下のものを除く", "寝台料金で六千六百円以下のものを除く" in k, "")
    s7 = article(EGOV / "sochi_2025-12-31.txt", "29_4")
    s8 = article(EGOV / "sochi_2026-12-31.txt", "29_4")
    check("措法29の4（asof 2025-12-31）は未払賃金の特例（旧条）", "未払賃金" in s7 and "特定支出" not in s7, s7.splitlines()[0] if s7 else "")
    p3 = para(s8, "３")
    check("措法29の4③（asof 2026-12-31）は第2項の適用がある場合の所法57の2① の読替え",
          "所得税法第五十七条の二第一項" in p3 and "同項の規定を適用した場合の同項に規定する給与所得の金額に相当する金額" in p3, p3)
    t = article(EGOV / "sochi_2026-12-31.txt", "41_3_11")
    check("措法41の3の11④五 給与所得控除後の給与等の金額は、給与等の収入金額から第28条第3項の給与所得控除額を控除した残額",
          "給与等の収入金額から所得税法第二十八条第三項に規定する給与所得控除額を控除した残額" in t, "")
    c6 = article(EGOV / "chiho_2026-01-01.txt", "313")
    c7 = article(EGOV / "chiho_2027-01-01.txt", "313")
    p11a, p11b = para(c6, "１１"), para(c7, "１１")
    check("地法313⑪ は令和8年度分・令和9年度分で同じ文言で、前年分の所得税の納税義務がない者の住民税の申告書による特定支出控除",
          p11a and p11a == p11b and "前年分の所得税につき納税義務を負わない" in p11a and "第三百十七条の二第一項の規定による申告書" in p11a, p11a)
    p2 = para(c7, "２")
    check("地法313② 総所得金額等は所得税法の計算の例により算定", "計算の例により算定する" in p2, p2)
    d32 = article(EGOV / "chiho_2027-01-01.txt", "32")
    check("地法32⑪ 道府県民税も同じ（第45条の2第1項の申告書）", "第四十五条の二第一項の規定による申告書" in para(d32, "１１"), para(d32, "１１"))
    g323 = article(EGOV / "chiho_2027-01-01.txt", "323")
    check("地法323 市町村民税の減免は条例の定めによる", "条例の定めるところにより、市町村民税を減免することができる" in g323, "")
    # 明細書（様式）の「(赤字の場合は０)」の位置：⑰ の欄の名称の近く
    rows = []
    for ln in (PDF / "yoshiki039_text.tsv").read_text(encoding="utf-8").splitlines():
        p = ln.split("\t")
        if len(p) >= 5 and p[0] == "1":
            rows.append((float(p[1]), float(p[2]), p[4]))
    red = [(x, y) for x, y, s in rows if "赤字の" in s]
    l17 = [(x, y) for x, y, s in rows if s.startswith("⑰") and x < 200]
    check("明細書の「(赤字の場合は０)」は ⑰（特定支出控除の金額）の欄にある（y の差が10未満）",
          red and l17 and min(abs(r[1] - l[1]) for r in red for l in l17) < 10, {"赤字の": red, "⑰": l17})
    (OUT / "checks.json").write_text(json.dumps(checks, ensure_ascii=False, indent=1), encoding="utf-8")
    for c in checks:
        print("OK " if c["ok"] else "NG ", c["name"])


if __name__ == "__main__":
    main()
