"""IMPL9 tokutei-jumin verify: impl-research9 の公開資料の情報（docs/public-sources/20261112_impl-research9_tokutei-jumin-sources.md）に
引用した文言・値が、取り出した写し（scripts/results/IMPL9_*）にあることを確かめる。ネットワークを使わない。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL9_tokutei-jumin_verify.py

前提：次のコマンドを先に実行して写しを作っておく（docs/measurements/20261112_impl-research9_tokutei-jumin-fetch.md）。
  IMPL9_tokutei-jumin_egov.py extract …、IMPL9_tokutei-jumin_web.py nta etax etax2 etax3、IMPL9_tokutei-jumin_pdftext.py …、
  IMPL9_tokutei-jumin_cab.py sheet …（field_Ver7x・field_Ver23x・taisho_Ver7x）
出力：scripts/results/IMPL9_tokutei-jumin_verify/checks.json
"""
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
RES = ROOT / "scripts" / "results"
EG = RES / "IMPL9_tokutei-jumin_egov"
WEB = RES / "IMPL9_tokutei-jumin_web"
PDF = RES / "IMPL9_tokutei-jumin_pdftext"
CAB = ROOT / ".work" / "etax_spec_extract" / "IMPL9_tokutei-jumin_cab"  # 著作権のため git の管理外（D21 R7）
OUT = RES / "IMPL9_tokutei-jumin_verify"

checks = []


def check(cid, desc, ok, detail=None):
    checks.append({"id": cid, "desc": desc, "ok": bool(ok), "detail": detail})


def read(p):
    return p.read_text(encoding="utf-8")


def article(text, num):
    m = re.search(rf"^## (?:本則 )?Num={re.escape(num)}(?: |$).*?(?=^## |\Z)", text, re.S | re.M)
    return m.group(0) if m else ""


def para(art, mark):
    for line in art.splitlines():
        if line.startswith(mark + "　"):
            return line
    return ""


# --- A：地方税法・所得税法・国税通則法 ---
P11 = "１１　前年分の所得税につき納税義務を負わない所得割の納税義務者について、前年中の所得税法第五十七条の二第二項に規定する特定支出の額の合計額が同法第二十八条第二項に規定する給与所得控除額の二分の一に相当する金額を超える場合には"
for asof in ("2026-01-01", "2027-01-01"):
    t = read(EG / f"chiho_{asof}.txt")
    a313, a32 = article(t, "313"), article(t, "32")
    check(f"A1-{asof}", f"地方税法第313条第11項・第32条第11項の冒頭の文言（{asof}）", para(a313, "１１").startswith(P11) and para(a32, "１１").startswith(P11))
    check(f"A2-{asof}", f"第313条第11項は第317条の2第1項の申告書、第32条第11項は第45条の2第1項の申告書（{asof}）",
          "第三百十七条の二第一項の規定による申告書" in para(a313, "１１") and "第四十五条の二第一項の規定による申告書" in para(a32, "１１"))
    check(f"A3-{asof}", f"第313条第3項に「前年分の所得税につき納税義務を負わないと認められたこと」（{asof}）",
          "前年分の所得税につき納税義務を負わないと認められたことその他政令で定める理由により" in para(a313, "３"))
    g = read(EG / f"grep_chiho_{asof}.txt")
    hits = sorted({m for m in re.findall(r"^## (?:本則|附則[^N]*) Num=(\S+) 語=\[([^\]]*)\]", g, re.M) if "納税義務を負わない" in m[1]})
    nums = [h[0] for h in hits]
    check(f"A4-{asof}", f"「納税義務を負わない」を含む条（{asof}）は第32条・第72条の49の12・第313条・第317条の2 だけ", nums == ["313", "317_2", "32", "72_49_12"], nums)
    check(f"A5-{asof}", f"第317条の2第1項ただし書の「所得割の納税義務を負わないと認められる者のうち当該市町村の条例で定めるもの」（{asof}）",
          "所得割の納税義務を負わないと認められる者のうち当該市町村の条例で定めるもの" in article(g, "317_2"))
t26, t27 = read(EG / "chiho_2026-01-01.txt"), read(EG / "chiho_2027-01-01.txt")
check("A6", "第313条第11項・第32条第11項は令和8年度分と令和9年度分の版で同じ",
      para(article(t26, "313"), "１１") == para(article(t27, "313"), "１１") and para(article(t26, "32"), "１１") == para(article(t27, "32"), "１１"))
for asof in ("2026-01-01", "2027-01-01"):
    g = read(EG / f"grep_chihorei_{asof}.txt")
    check(f"A7-{asof}", f"地方税法施行令に「納税義務を負わない」「特定支出」を含む条がない（{asof}）", "## 本則" not in g and "## 附則" not in g)
for asof in ("2025-12-31", "2026-12-31"):
    s = read(EG / f"shoho_{asof}.txt")
    check(f"A8-{asof}", f"所得税法第5条第1項「居住者は、この法律により、所得税を納める義務がある。」（{asof}）",
          "（Paragraph1）　居住者は、この法律により、所得税を納める義務がある。" in article(s, "5"))
    a120 = article(s, "120")
    check(f"A9-{asof}", f"所得税法第120条第1項：「所得税の額の合計額が配当控除の額を超えるとき」に確定申告書の提出義務（{asof}）",
          "計算した場合の所得税の額の合計額が配当控除の額を超えるとき" in a120 and "申告書を提出しなければならない" in a120)
    tsu = read(EG / f"tsusoku_{asof}.txt")
    a15 = article(tsu, "15")
    check(f"A10-{asof}", f"国税通則法第15条第1項の「納税義務」の定義と第2項第1号「所得税　暦年の終了の時」（{asof}）",
          "国税を納付する義務（源泉徴収等による国税については、これを徴収して国に納付する義務。以下「納税義務」という。）" in a15
          and "一　所得税（次号に掲げるものを除く。）　暦年の終了の時" in a15)

# --- B：地方税法施行規則第1条の12 ---
for asof in ("2026-01-01", "2027-01-01"):
    g = read(EG / f"grep_chihoki_{asof}.txt")
    a = article(g, "1_12")
    check(f"B1-{asof}", f"地方税法施行規則第1条の12（{asof}）：法第32条第11項・第313条第11項の書類＝所令167の4の明細書と所令167の5の書類",
          "法第三十二条第十一項及び第三百十三条第十一項に規定する総務省令で定める書類は、次の各号に掲げるものとする。" in a
          and "一　所得税法施行令（昭和四十年政令第九十六号）第百六十七条の四に掲げる事項を記載した特定支出に関する明細書" in a
          and "二　所得税法施行令第百六十七条の五に規定する書類" in a)
    check(f"B2-{asof}", f"施行規則で「特定支出」を含む条は第1条の12 だけ（{asof}）", re.findall(r"^## (?:本則|附則[^N]*) Num=(\S+)", g, re.M) == ["1_12"])

# --- C：手引き 3-2_06 ---
tb = read(WEB / "nta" / "tebiki_2025_3_2_06.txt")
check("C1", "手引き 3-2_06：㋔欄「区分」は所得金額調整控除の 1・2・3",
      "※ 〔alt:オ〕欄「区分」の□には、Step3「所得金額調整控除の計算」の（1）に該当する場合は「1」を、（2）に該当する場合は「2」を、（1）及び（2）の両方に該当する場合は「3」を記入します。" in tb)
check("C2", "手引き 3-2_06：⑥欄の「区分」は特定支出控除を受ける場合にだけ明細書の区分番号",
      "※ 〔alt:6〕欄の「区分」の□は、給与所得者の特定支出控除を受ける場合にのみ、「給与所得者の特定支出に関する明細書」の区分番号を記入します。" in tb)
check("C7", "手引き 3-2_06 の Step3 (1)（850万円超・特別障害者・23歳未満の扶養親族）と (2)（給与所得と公的年金等の雑所得・10万円超）",
      "(1) あなたの給与等の収入金額（税込）が850万円を超え、" in tb and "(2) あなたに給与所得と公的年金等の雑所得がある場合で、給与所得控除後の給与等の金額と公的年金等の雑所得の金額の合計額が10万円を超える場合" in tb)
check("C3", "手引き 3-2_06 の版（Last-Modified と SHA-256）", "# last_modified=Wed, 24 Dec 2025 08:30:10 GMT" in tb and "d693641fc03301440ac9f3cdc9f0b12c73bfd9484ea5ab293713a79998f5f38c" in tb)

# --- 明細書（039.pdf）の区分の番号と注記 ---
rows = []
for ln in read(PDF / "yoshiki039_text.tsv").splitlines()[2:]:
    a = ln.split("\t", 4)
    if len(a) == 5:
        rows.append((int(a[0]), float(a[1]), float(a[2]), a[3], a[4]))
labels = {}
for kubun_y, name in ((726.1, "通勤費"), (678.1, "職務上の旅費"), (623.0, "転居費"), (561.9, "研修費"), (510.2, "資格取得費"),
                      (452.0, "帰宅旅費"), (399.9, "図書費"), (348.3, "衣服費"), (294.2, "交際費等")):
    toks = sorted((r for r in rows if r[0] == 1 and 58 <= r[1] <= 72 and abs(r[2] - kubun_y) < 0.2), key=lambda r: r[1])
    labels[name] = "".join(r[4].strip() for r in toks).translate(str.maketrans("０１２３４５６７８９", "0123456789"))
expect = {"通勤費": "1", "職務上の旅費": "256", "転居費": "2", "研修費": "4", "資格取得費": "8", "帰宅旅費": "16", "図書費": "32", "衣服費": "64", "交際費等": "128"}
check("C4", "明細書 1面の【区分 n】の番号（文字の位置から：通勤1・旅費256・転居2・研修4・資格8・帰宅16・図書32・衣服64・交際128）", labels == expect, labels)
line45 = "".join(r[4] for r in sorted((r for r in rows if r[0] == 1 and abs(r[2] - 44.8) < 0.2), key=lambda r: r[1]))
check("E1", "明細書：「◎上記⑪の金額を申告書第二表の「特例適用条文等」欄に書きます。記載例：特例適用条文等 所法５７の２ XXX,XXX円」",
      "◎上記⑪の金額を申告書第二表の「特例適用条文等」欄に書きます。記載例：特例適用条文等所法５７の２XXX,XXX円" in line45.replace(" ", ""), line45)
line32 = "".join(r[4] for r in sorted((r for r in rows if r[0] == 1 and abs(r[2] - 31.9) < 0.2), key=lambda r: r[1]))
check("C5", "明細書：「…申告書第一表の「所得金額等」欄の給与の「区分」欄に書きます。」（前半は ToUnicode のないフォント）",
      "申告書第一表の「所得金額等」欄の給与の「区分」欄に書きます。" in line32.replace(" ", ""), line32)
head = read(PDF / "yoshiki039_text.tsv").splitlines()[0]
check("C6", "明細書 039.pdf の SHA-256 が impl-research8 の写しと同じ", "f4d2a144bdadbb3bd91ab142f5e04e8dd4387d343fac589c695ffde8682f0b4d" in head)


# --- D：e-Tax 対象帳票一覧・帳票フィールド仕様書 ---
def cells(name, sheet):
    d = {}
    for ln in read(CAB / f"{name}.tsv").splitlines()[2:]:
        s, c, v = ln.split("\t", 2)
        if s == sheet:
            d[c] = v
    return d


tl = cells("taisho_Ver7x", "対象帳票一覧（申告）")
check("D1", "対象帳票一覧（申告）Ver7x：KOB070 給与所得者の特定支出に関する明細書 7.0（4面）",
      tl.get("A6") == "KOB070" and tl.get("B6") == "給与所得者の特定支出に関する明細書" and tl.get("L6") == "7.0" and tl.get("E6") == "4面")
fk = cells("field_Ver7x", "KOB070")
check("D2", "帳票フィールド仕様書 KOB070 7.0 の様式ID・版", fk.get("G2") == "KOB070" and fk.get("O2") == "7.0")
want = {
    60: ("11", "特定支出の合計額", "BGL00000"),
    61: ("12", "適用を受ける特定支出の区分の合計", "BGM00000"),
    62: ("13", "給与等の収入金額の合計額", "BGN00000"),
    63: ("14", "特定支出控除適用前の給与所得金額", "BGO00000"),
    64: ("15", "給与所得控除額", "BGP00000"),
    65: ("16", "(15)*1/2", "BGQ00000"),
    66: ("17", "特定支出控除の金額", "BGR00000"),
    67: ("18", "特定支出控除適用後の給与所得金額", "BGS00000"),
}
got = {r: (fk.get(f"C{r}"), fk.get(f"D{r}"), fk.get(f"M{r}")) for r in want}
check("D3", "KOB070 の ⑪〜⑱ の欄（帳票項番・項目名・XML タグ）", got == want, {str(k): v for k, v in got.items()})
check("D4", "KOB070 ⑫ の値の範囲 0≦x≦511、⑰ の計算「BGL00000－BGQ00000 赤字の場合は0」、⑱ の計算「BGN00000－BGP00000－BGR00000」",
      fk.get("J61") == "0≦x≦511" and fk.get("L66") == "【計算】BGL00000－BGQ00000 赤字の場合は0" and fk.get("L67") == "【計算】BGN00000－BGP00000－BGR00000")
fa = cells("field_Ver23x", "KOA020")
check("D5", "帳票フィールド仕様書 KOA020 23.0：収入金額等の給与 区分 ABB00075（1≦x≦3）、所得金額等の給与 区分 ABB00365（1≦x≦511）",
      fa.get("O2") == "23.0" and fa.get("E49") == "給与　区分" and fa.get("J49") == "1≦x≦3" and fa.get("M49") == "ABB00075"
      and fa.get("C50") == "オ" and fa.get("M50") == "ABB00080"
      and fa.get("E65") == "給与　区分" and fa.get("J65") == "1≦x≦511" and fa.get("M65") == "ABB00365" and fa.get("C66") == "6" and fa.get("M66") == "ABB00370")
check("E2", "KOA020 23.0：第二表「特例適用条文等」は文字の1欄（ABF00000）", fa.get("D177") == "特例適用条文等" and fa.get("B177") == "文字" and fa.get("M177") == "ABF00000")

OUT.mkdir(parents=True, exist_ok=True)
(OUT / "checks.json").write_text(json.dumps({"ok": sum(c["ok"] for c in checks), "total": len(checks), "checks": checks}, ensure_ascii=False, indent=1), encoding="utf-8")
for c in checks:
    print("OK " if c["ok"] else "NG ", c["id"], c["desc"], "" if c["ok"] else c["detail"])
print(sum(c["ok"] for c in checks), "/", len(checks))
