"""R2X elderly-abroad: 取得済みの条文テキスト（R2X_elderly-abroad_laws の出力）と公開資料のテキスト（R2X_elderly-abroad_web の出力）を読み、
文書に書く主張を機械的に確かめる（ネットワークには接続しない）。

実行（Windows）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_elderly-abroad_checks.py

入力（先に次の2つを実行しておく）:
  scripts/R2X_elderly-abroad_laws.py（全部と koukirei・chiho-ki） → scripts/results/R2X_elderly-abroad_laws/
  scripts/R2X_elderly-abroad_web.py robots elderly abroad kenpo   → scripts/results/R2X_elderly-abroad_web/text/<set>_<ts>/
出力:
  scripts/results/R2X_elderly-abroad_checks/checks.json（各検査の名前・結果・根拠の文字列）
  scripts/results/R2X_elderly-abroad_checks/checks.md（同じ内容の表）
標準ライブラリのみ。読むのはテキストだけで、ダウンロードしたファイルの中のものは何も実行しない。
"""
import datetime
import difflib
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
LAWS = ROOT / "scripts" / "results" / "R2X_elderly-abroad_laws"
WEB = ROOT / "scripts" / "results" / "R2X_elderly-abroad_web" / "text"
OUT = ROOT / "scripts" / "results" / "R2X_elderly-abroad_checks"

results = []


def check(name, ok, evidence):
    results.append({"name": name, "ok": bool(ok), "evidence": evidence})


def read(p):
    return p.read_text(encoding="utf-8")


def latest_text_dir(set_name):
    ds = sorted(WEB.glob(f"{set_name}_*"))
    return ds[-1]


def article_block(text, num):
    """articles_*.txt から「## Num=<num>」の節を取り出す（ヘッダ行は除く）。"""
    m = re.search(rf"^## Num={re.escape(num)}[^\n]*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    return m.group(1) if m else None


def paragraph(block, para_kanji_or_1):
    """条の本文から項を取り出す。第1項は '（Paragraph1）' で始まる行、第2項以後は全角数字＋全角空白で始まる行。"""
    lines = block.splitlines()
    out, on = [], False
    for ln in lines:
        head = ln.lstrip()
        is_new = head.startswith("（Paragraph1）") or re.match(r"^[０-９]+　", head)
        if is_new:
            on = (head.startswith("（Paragraph1）") and para_kanji_or_1 == "1") or head.startswith(para_kanji_or_1 + "　")
        if on:
            out.append(ln)
    return "\n".join(out)


def item_line(block, kanji_num):
    for ln in block.splitlines():
        if ln.lstrip().startswith(kanji_num + "　"):
            return ln.strip()
    return None


# ---------- 1. 所得税法：老人扶養親族・控除額・国外居住親族の定義が令和7年分・令和8年分で同じか ----------
SHOTOKU = {a: read(LAWS / f"articles_shotoku_{a}.txt") for a in ("2025-12-31", "2026-11-09", "2026-12-31")}
for asof, t in SHOTOKU.items():
    b2 = article_block(t, "2")
    b84 = article_block(t, "84")
    check(f"所法2①三十四の四（老人扶養親族＝控除対象扶養親族のうち年齢70歳以上）@{asof}",
          "三十四の四　老人扶養親族　控除対象扶養親族のうち、年齢七十歳以上の者をいう。" in b2, item_line(b2, "三十四の四"))
    check(f"所法84①（老人扶養親族48万円）@{asof}", "老人扶養親族である場合には四十八万円" in b84, paragraph(b84, "1").strip()[:200])
m34 = {a: re.search(r"合計所得金額が(.+?)以下である者をいう。", item_line(article_block(t, "2"), "三十四")).group(1) for a, t in SHOTOKU.items()}
check("所法2①三十四（扶養親族の所得要件）：2025-12-31・2026-11-09は五十八万円、2026-12-31は六十二万円",
      m34 == {"2025-12-31": "五十八万円", "2026-11-09": "五十八万円", "2026-12-31": "六十二万円"}, m34)


def item_with_sub(block, kanji_num):
    lines = block.splitlines()
    out, on = [], False
    for ln in lines:
        if ln.startswith(kanji_num + "　"):
            on = True
            out.append(ln)
            continue
        if on and ln.startswith("  "):
            out.append(ln)
        elif on:
            break
    return "\n".join(out)


i342 = {a: item_with_sub(article_block(t, "2"), "三十四の二") for a, t in SHOTOKU.items()}
check("所法2①三十四の二（控除対象扶養親族：居住者16歳以上／非居住者16〜30歳未満・70歳以上・30〜70歳未満で留学・障害者・38万円以上）が3版で同文",
      len(set(i342.values())) == 1 and "三十八万円以上" in i342["2026-12-31"], i342["2026-12-31"])
b120 = {a: paragraph(article_block(t, "120"), "３") for a, t in SHOTOKU.items()}
check("所法120③（確定申告書に国外居住親族の書類を添付・提示）が3版で同文", len(set(b120.values())) == 1, b120["2026-12-31"][:300])
b194 = {a: "\n".join(paragraph(article_block(t, "194"), k) for k in ("５", "６", "７")) for a, t in SHOTOKU.items()}
check("所法194⑤〜⑦が2026-11-09と2026-12-31で同文", b194["2026-11-09"] == b194["2026-12-31"], "")
check("所法194⑤〜⑦：2025-12-31→2026-11-09 の違いは「控除対象扶養親族」→「源泉控除対象親族」の語だけ",
      b194["2025-12-31"].replace("控除対象扶養親族", "源泉控除対象親族") == b194["2026-11-09"],
      "置き換え後に一致するか")
b85 = {a: paragraph(article_block(t, "85"), "３") for a, t in SHOTOKU.items()}
check("所法85③（12月31日の現況、死亡時は死亡の時）が3版で同文", len(set(b85.values())) == 1 and "その年十二月三十一日の現況" in b85["2026-12-31"], b85["2026-12-31"][:200])
b3 = {a: article_block(t, "3") for a, t in SHOTOKU.items()}
check("所法3（公務員は国内に住所を有しない期間も国内に住所を有するものとみなす）が3版で同文", len(set(b3.values())) == 1, b3["2026-12-31"].strip()[:200])

# ---------- 2. 所得税法施行令 第13条〜第15条、所得税法施行規則 第47条の2 第5項〜第10項 ----------
REI = {a: read(LAWS / f"articles_shotoku-rei_{a}.txt") for a in ("2025-12-31", "2026-11-09", "2026-12-31")}
for num in ("13", "14", "15", "262"):
    blocks = {a: article_block(t, num) for a, t in REI.items()}
    check(f"所令{num}が3版で同文", len(set(blocks.values())) == 1, (blocks["2026-12-31"] or "")[:120].replace("\n", " "))
KI = {a: read(LAWS / f"articles_shotoku-ki_{a}.txt") for a in ("2025-12-31", "2026-11-09", "2026-12-31")}
p5_10 = {a: "\n".join(paragraph(article_block(t, "47_2"), k) for k in ("５", "６", "７", "８", "９", "１０")) for a, t in KI.items()}
check("所規47の2⑤〜⑩（親族関係書類・送金関係書類・留学ビザ等書類・38万円送金書類の定義）が3版で同文",
      len(set(p5_10.values())) == 1 and "三十八万円以上" in p5_10["2026-12-31"], p5_10["2026-12-31"][:160])

# ---------- 3. 租税特別措置法 第41条の16（同居の老親等）と、「同居老親等」の語が法令にあるか ----------
SOCHI = {a: read(LAWS / f"articles_sochi_{a}.txt") for a in ("2025-12-31", "2026-11-09", "2026-12-31")}
s4116 = {a: article_block(t, "41_16") for a, t in SOCHI.items()}
check("措法41の16が3版で同文", len(set(s4116.values())) == 1, "")
check("措法41の16①：直系尊属・同居を常況・48万円に「十万円を加算」",
      all(k in s4116["2026-12-31"] for k in ("直系尊属", "同居を常況としている者", "十万円を加算")), paragraph(s4116["2026-12-31"], "1").strip())
for f in sorted(LAWS.glob("kwhits_sochi*_*.txt")):
    t = read(f)
    summary = t.split("# キーワード=")[0]
    check(f"{f.name}：本則・附則に「同居老親等」の語がない（キーワード一覧に出ない）", "同居老親等" not in summary, "一覧の行数=" + str(summary.count("Num=")))
for f in sorted(LAWS.glob("kwhits_shotoku*_*.txt")):
    t = read(f)
    summary = t.split("# キーワード=")[0]
    check(f"{f.name}：本則・附則に「同居老親等」の語がない", "同居老親等" not in summary, "")

# ---------- 4. 地方税法：住民税の老人扶養・同居直系尊属・非居住者の控除対象扶養親族 ----------
CHIHO = {a: read(LAWS / f"articles_chiho_{a}.txt") for a in ("2026-01-01", "2026-11-09", "2027-01-01")}
for asof, t in CHIHO.items():
    b = article_block(t, "314_2")
    i11 = item_with_sub(paragraph(b, "1").replace("\n  ", "\n"), "十一")
    check(f"地法314の2①十一（扶養控除 33万・特定45万・老人38万、非居住者の区分）@{asof}",
          all(k in i11 for k in ("三十三万円", "四十五万円", "老人扶養親族", "三十八万円）", "非居住者", "三十八万円以上")), i11[:200])
    p4 = paragraph(b, "４")
    check(f"地法314の2④（同居直系尊属の老人扶養親族は45万円）@{asof}", "直系尊属" in p4 and "四十五万円" in p4 and "同居直系尊属" in p4, p4.strip())
    p8 = paragraph(b, "８")
    check(f"地法314の2⑧（前年12月31日の現況）@{asof}", "前年の十二月三十一日" in p8 and "第四項の規定に該当する老人扶養親族" in p8, "")
    b34 = article_block(t, "34")
    p34_4 = paragraph(b34, "４")
    check(f"地法34④（道府県民税も同居直系尊属45万円）@{asof}", "直系尊属" in p34_4 and "四十五万円" in p34_4, p34_4.strip()[:120])
    b3146 = article_block(t, "314_6")
    check(f"地法314の6（調整控除）の人的控除差：老人扶養親族10万円・同居直系尊属13万円@{asof}",
          "当該老人扶養親族一人につき十万円" in b3146 and "当該老人扶養親族一人につき十三万円" in b3146, "")
# 人的控除額の差（所得税 − 住民税）が調整控除の表の額と一致するか（算術の確認）
check("所得税と住民税の控除額の差：老人扶養 48万−38万＝10万、同居老親等 58万−45万＝13万（地法314の6の表の額と一致）",
      (480000 - 380000, 580000 - 450000) == (100000, 130000), {"老人扶養": 480000 - 380000, "同居": 580000 - 450000})
check("所得税の同居老親等の扶養控除額＝所法84①の48万円＋措法41の16①の10万円＝58万円", 480000 + 100000 == 580000, 580000)

CHIKI = {a: read(LAWS / f"kwhits_chiho-ki_{a}.txt") for a in ("2026-01-01", "2026-11-09", "2027-01-01")}
for asof, t in CHIKI.items():
    hits = [ln.strip()[:80] for ln in t.splitlines() if "「国外居住者」という" in ln or "「控除対象外国外扶養親族」という" in ln]
    check(f"地方税法施行規則2の2：「国外居住者」「控除対象外国外扶養親族」の定義の項がある@{asof}", len(hits) == 2, hits)

# ---------- 5. 健康保険法・同施行規則・高齢者医療確保法 ----------
KENPO = {a: read(LAWS / f"articles_kenpo_{a}.txt") for a in ("2025-12-31", "2026-11-09")}
k7 = {a: paragraph(article_block(t, "3"), "７") for a, t in KENPO.items()}
check("健保法3⑦が2版で同文", k7["2025-12-31"] == k7["2026-11-09"], "")
check("健保法3⑦一：直系尊属・配偶者・子・孫・兄弟姉妹は「同一の世帯に属し」を要件にしない",
      "直系尊属" in item_line(k7["2026-11-09"], "一") and "同一の世帯" not in item_line(k7["2026-11-09"], "一"), item_line(k7["2026-11-09"], "一"))
check("健保法3⑦二：上記以外の三親等内の親族は「同一の世帯に属し」を要件にする", "同一の世帯に属し" in item_line(k7["2026-11-09"], "二"), item_line(k7["2026-11-09"], "二"))
KKI = {a: read(LAWS / f"articles_kenpo-ki_{a}.txt") for a in ("2025-12-31", "2026-11-09")}
check("健保則37の2・37の3・38が2版で同文", KKI["2025-12-31"].split("\n", 6)[-1] == KKI["2026-11-09"].split("\n", 6)[-1], "")
kk = read(LAWS / "articles_koukirei_2026-11-09.txt")
check("高齢者医療確保法50①一：区域内に住所を有する75歳以上の者は後期高齢者医療の被保険者", "七十五歳以上の者" in kk, item_line(article_block(kk, "50"), "一"))

# ---------- 6. 公開資料のテキスト ----------
el = latest_text_dir("elderly")
ta1180 = read(el / "ta_1180.txt")
check("TA1180：老人扶養親族 同居老親等以外48万円・同居老親等58万円の表がある", re.search(r"同居老親等以外の者\s*\|\s*48万円\s*\|\s*同居老親等\s*\|\s*58万円", ta1180) is not None, "")
check("TA1180：入院は1年以上でも同居、老人ホーム等は同居といえない（注）", "1年以上といった長期" in ta1180 and "老人ホーム等へ入所している場合には、その老人ホームが居所となり" in ta1180, "")
sg = read(el / "shitsugi_shotoku_05_32.txt")
check("質疑応答事例「同居」の範囲（長期間入院）：回答要旨と関係法令（措法41の16）、基準日", "病気の治療のための入院である限り" in sg and "租税特別措置法第41条の16" in sg and "令和7年8月1日現在" in sg, "")
toc = read(el / "sochiho_tsutatsu_toc.txt")
hits_4116 = [ln for ln in toc.splitlines() if re.search(r"第41条の16(?!の)|41の16[-－]", ln)]
heads = [ln.strip() for ln in toc.splitlines() if re.match(r"\s*第41条の1[5-7]", ln)]
check("措置法通達（所得税）の目次に第41条の16の項がない（41条の15の5の次が41条の17）", not hits_4116, heads)
ab = latest_text_dir("abroad")
kg = read(ab / "kokugai_index.txt")
check("国外居住親族のページ：Q&Aへのリンク名は「令和７年６月更新」（PDF本体の表紙は最終改訂 令和8年8月：人が読んで確認）", "令和７年６月更新" in kg, "")
kn = latest_text_dir("kenpo")
r01 = [ln.strip() for ln in read(kn / "R01_kokunai.txt").splitlines() if ln.strip() and ln.strip() != "|"]
r05 = [ln.strip() for ln in read(kn / "R05_kokunai_kaisei.txt").splitlines() if ln.strip() and ln.strip() != "|"]
i, j = r01.index("第1　国内居住要件の考え方について"), r05.index("第1　国内居住要件の考え方について")
d = list(difflib.unified_diff(r01[i:], r05[j:], lineterm="", n=0))
check("厚労省DBの R01 通知（00tc4995）の本文と、令和5年改正通知（00tc7769）に載る改正後の本文が、第1以降でテキストとして同じ", not d, d[:10])
s52 = read(kn / "S52_tsuchi.txt")
check("S52通知：60歳以上又は障害者は180万円未満（同一世帯・別世帯の両方の記）", s52.count("六〇歳以上の者である場合") == 3 and s52.count("一八〇万円未満") == 3, "")
check("S52通知：60歳の判定の時点を書いた文がない（「十二月三十一日」「時点」の語がない）", "十二月三十一日" not in s52 and "時点" not in s52, "")
ny = read(kn / "nenkin_kyojuyoken.txt")
check("機構「従業員の家族が海外居住の場合の手続き」：別居なら年収が仕送り額未満、海外で同居なら2分の1未満", "仕送り額未満" in ny and "2分の1未満" in ny, "")

OUT.mkdir(parents=True, exist_ok=True)
summary = {"run_at": datetime.datetime.now().isoformat(timespec="seconds"), "n": len(results), "n_ok": sum(r["ok"] for r in results), "results": results}
(OUT / "checks.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
md = ["| # | 検査 | 結果 |", "|---|---|---|"] + [f"| {k + 1} | {r['name']} | {'OK' if r['ok'] else '**NG**'} |" for k, r in enumerate(results)]
(OUT / "checks.md").write_text("\n".join(md) + "\n", encoding="utf-8")
print(f"{summary['n_ok']}/{summary['n']} OK")
for r in results:
    if not r["ok"]:
        print("NG:", r["name"], str(r["evidence"])[:300])
