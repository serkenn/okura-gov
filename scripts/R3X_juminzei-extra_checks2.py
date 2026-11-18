"""R3X juminzei-extra（補足）: R3X_juminzei-extra_checks.py で確かめていない文字列を、取得済みのテキストで機械的に確かめる（ネットワークは使わない）。

1. 令和8年4月1日 総税企第44号（地方税法等の改正の施行通知）：
   - 第一 道府県税 1(2)：自己の同族会社との合計で 3% 以上となる内国法人からの上場株式等の配当等を「引き続き総合課税の対象とした上で、配当割の対象とする」
   - 第二 市町村税 1(8)：住宅借入金等特別税額控除の控除限度額への「基礎控除の額から四十八万円を控除して得た額」の加算（居住年 平成28年〜令和7年）と適用期限の延長
2. 総務省の取扱通知（市町村税関係）第2章第2節 25の2(4)（控除不足額の充当と還付の順序）・28 の柱書。
3. 総務省「個人住民税の住宅ローン控除」の案内のページに、令和8年改正の基礎控除の差の加算が書かれているか（語の出現回数）。
4. 地方税法 第737条第1項・第317条の2第8項・第294条第1項（家屋敷）の全文（asof 2026-11-09）。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_juminzei-extra_checks2.py

入力（読むだけ。.work/downloads の中のものは読まない）:
- scripts/results/R3X_chiho-sochi_pdftext/r8_kaisei_tsuchi.txt（scripts/R3X_chiho-sochi_pdftext.py の出力）
- scripts/results/R3X_juminzei-extra_pdftext/shichoson_lines.txt（scripts/R3X_juminzei-extra_pdftext.py の出力）
- scripts/results/R3X_juminzei-extra_web/soumu_juutaku_loan.txt（scripts/R3X_juminzei-extra_web.py の出力）
- scripts/results/R3X_juminzei-extra_laws/chiho_2026-11-09.articles.json（scripts/R3X_juminzei-extra_laws.py の出力）
出力：scripts/results/R3X_juminzei-extra_checks2/evidence.md・checks.json
PDF の行のつなぎ方は scripts/R3X_juminzei-extra_checks.py の notice_text と scripts/R3X_chiho-sochi_checks.py の pdf_flat を写した（import はしない）。
"""
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
RES = ROOT / "scripts" / "results"
OUT = RES / "R3X_juminzei-extra_checks2"


def norm(s):
    return re.sub(r"[\s\u3000]+", "", s)


def pdf_flat(path):
    """R3X_chiho-sochi_pdftext の出力（=== p.N === 区切り）を、頁の区切りと頁番号の行を除いてつなぐ"""
    t = path.read_text(encoding="utf-8")
    lines = [ln for ln in t.splitlines()[1:] if not ln.startswith("=== p.") and not re.fullmatch(r"\s*[-－–]\s*[0-9０-９]+\s*[-－–]?\s*|\s*[0-9０-９]+\s*", ln)]
    return norm("".join(lines))


def notice_text(path):
    """R3X_juminzei-extra_pdftext の出力（=== page N === 区切り）をつなぐ。頁ごとの開始位置も返す"""
    buf, starts, page = [], [], 0
    for ln in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"=== page (\d+) ===", ln)
        if m:
            page = int(m.group(1))
            starts.append((len("".join(buf)), page))
            continue
        if ln.startswith("# file=") or re.fullmatch(r"-\d+-", ln.strip()):
            continue
        buf.append(norm(ln))
    return "".join(buf), starts


def page_at(starts, pos):
    p = None
    for off, pg in starts:
        if off <= pos:
            p = pg
    return p


RESULTS = []


def check(cid, target, expect, ok, note=""):
    RESULTS.append({"id": cid, "target": target, "expect": expect, "ok": ok, "note": note})


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    md = ["# R3X juminzei-extra（補足）：検査の結果", "", "生成：scripts/R3X_juminzei-extra_checks2.py。文字列は空白・改行を除いて比べた。", ""]

    # 1. 施行通知（令和8年 総税企第44号）
    r8 = pdf_flat(RES / "R3X_chiho-sochi_pdftext" / "r8_kaisei_tsuchi.txt")
    r8c = [
        ("T1", "第一 道府県税 1(2)（配当割）",
         "所得割の納税義務者が、自己の同族会社である法人との合計で株式等の保有割合が百分の三以上となる内国法人から支払を受ける上場株式等の配当等に"),
        ("T2", "同（続き）", "ついて、引き続き総合課税の対象とした上で、配当割の対象とする。（法第二十三条、第三十二条、令第七条の三関係）"),
        ("T3", "第二 市町村税 1(8)（住宅借入金等特別税額控除）の見出し", "住宅借入金等特別税額控除について、以下の措置を講ずる。"),
        ("T4", "同 イ",
         "居住年が平成二十八年から令和七年までの各年である場合に係る控除限度額の計算上用いる所得税の課税総所得金額等について、前年分の所得税に係る基礎控除の額から四十八万円を控除して得た額を加算する。"),
        ("T5", "同 ロ（行の順序が入れ替わって取り出されるので断片で）", "適用期限を令和二十五年度分の個人の市町村民税及び居住年が令和十二"),
        ("T6", "同 ロ（断片2）", "年であるものまで延長する等所要の措置を講ずる。"),
    ]
    md += ["## 1. 令和8年4月1日 総税企第44号（scripts/results/R3X_chiho-sochi_pdftext/r8_kaisei_tsuchi.txt）", "",
           "| ID | 箇所 | 結果 | 文字列 |", "|---|---|---|---|"]
    for cid, label, text in r8c:
        ok = norm(text) in r8
        check(cid, f"r8_kaisei_tsuchi：{label}", text, ok)
        md.append(f"| {cid} | {label} | {'OK' if ok else 'NG'} | {text} |")
    for kw in ["同族会社", "配当割", "住宅借入金等特別税額控除"]:
        n = r8.count(kw)
        RESULTS.append({"id": f"TN-{kw}", "target": "r8_kaisei_tsuchi（全頁）", "expect": f"「{kw}」の出現数", "ok": None, "note": str(n)})
        md.append(f"| TN-{kw} | 全頁の「{kw}」の出現数 | — | {n} |")
    md.append("")

    # 2. 取扱通知（市町村税関係）
    t, starts = notice_text(RES / "R3X_juminzei-extra_pdftext" / "shichoson_lines.txt")
    nc = [
        ("S1", "第2章第2節 25の2(4)",
         "還付をすべき金額のうち(２)の納付又は納入をすることができなかった部分の金額がある場合においては、当該納税義務者の未納に係る地方団体の徴収金又は森林環境税に係る徴収金があるときは、これに納付又は納入し、それでもなお納付又は納入をすることができなかった部分の金額があるときは、当該金額を当該納税義務者に還付するものであること。"),
        ("S2", "同 25の2(2)（充当の先）", "により同一年度分の個人の道府県民税、個人の市町村民税又は森林環境税を納付し、又は納入するものであること。"),
        ("S3", "同 28 柱書", "法附則第５条の４の規定に基づく住宅借入金等特別税額控除の適用に当たっては、次の諸点に留意すること。（法附則５の４⑤～⑧）"),
        ("S4", "同 28の3", "個人の市町村民税については、前年中に非居住者であった期間を有する者についても税額控除の範囲は異ならないものであるから留意すること。"),
        ("S5", "同 29（申告義務の免除）", "ただし、本人の申告をまたず課税資料を他から得られる者及び課税資料の提出の必要のない者として次に掲げる者は、申告義務が免除されているものであること。"),
    ]
    md += ["## 2. 取扱通知（市町村税関係）（scripts/results/R3X_juminzei-extra_pdftext/shichoson_lines.txt）", "",
           "| ID | 箇所 | 頁（PDF） | 結果 |", "|---|---|---|---|"]
    for cid, label, text in nc:
        pos = t.find(norm(text))
        check(cid, f"取扱通知（市町村税）：{label}", text, pos >= 0, f"p.{page_at(starts, pos)}" if pos >= 0 else "")
        md.append(f"| {cid} | {label} | {page_at(starts, pos) if pos >= 0 else '-'} | {'OK' if pos >= 0 else 'NG'} |")
    md.append("")

    # 3. 総務省の住宅ローン控除の案内（語の出現回数）
    w = (RES / "R3X_juminzei-extra_web" / "soumu_juutaku_loan.txt").read_text(encoding="utf-8")
    wn = norm(w)
    md += ["## 3. 総務省の住宅ローン控除の案内（scripts/results/R3X_juminzei-extra_web/soumu_juutaku_loan.txt）の語の出現回数", "",
           "| 語 | 出現数 |", "|---|---|"]
    for kw in ["基礎控除", "48万", "４８万", "四十八万", "令和12年12月31日", "5％(97,500円を限度)", "申告は不要"]:
        n = wn.count(norm(kw))
        RESULTS.append({"id": f"W-{kw}", "target": "soumu_juutaku_loan.txt", "expect": f"「{kw}」の出現数", "ok": None, "note": str(n)})
        md.append(f"| {kw} | {n} |")
    md.append("")

    # 4. 地方税法の条（家屋敷）
    arts = json.loads((RES / "R3X_juminzei-extra_laws" / "chiho_2026-11-09.articles.json").read_text(encoding="utf-8"))["articles"]
    lc = [
        ("L1", "本則:737", "道府県民税、市町村民税及び固定資産税に関する規定の都及び地方自治法第二百五十二条の十九第一項の市（以下この条及び次条において「指定都市」という。）に対する準用及び適用については、特別区並びに指定都市の区及び総合区の区域は、一の市の区域とみなし"),
        ("L2", "本則:317_2", "市町村長は、市町村民税の賦課徴収について必要があると認める場合には、当該市町村の条例で定めるところにより、第二百九十四条第一項第二号に掲げる者に、賦課期日現在において有する事務所、事業所又は家屋敷の所在その他必要な事項を申告させることができる。"),
        ("L3", "本則:294", "市町村民税は、第一号の者に対しては均等割額及び所得割額の合算額により、第三号の者に対しては均等割額及び法人税割額の合算額により、第二号及び第四号の者に対しては均等割額により、第五号の者に対しては法人税割額により課する。"),
        ("L4", "本則:295", "市町村は、この法律の施行地に住所を有する者で均等割のみを課すべきもののうち、前年の合計所得金額が政令で定める基準に従い当該市町村の条例で定める金額以下である者に対しては、均等割を課することができない。"),
    ]
    md += ["## 4. 地方税法 asof 2026-11-09（scripts/results/R3X_juminzei-extra_laws/chiho_2026-11-09.articles.json）", "",
           "| ID | 条 | 結果 | 文字列 |", "|---|---|---|---|"]
    for cid, key, text in lc:
        ok = norm(text) in norm(arts.get(key, ""))
        check(cid, f"地方税法 asof=2026-11-09 {key}", text, ok)
        md.append(f"| {cid} | {key} | {'OK' if ok else 'NG'} | {text} |")
    # 「家屋敷」の語の定義（「家屋敷とは」「家屋敷をいう」）が地方税法の抜き出した条にあるか
    defs = [k for k, v in arts.items() if re.search(r"家屋敷(とは|をいう)", v)]
    RESULTS.append({"id": "L-def", "target": "地方税法 asof=2026-11-09 の抜き出した条", "expect": "「家屋敷とは」「家屋敷をいう」を含む条", "ok": None, "note": str(defs)})
    md += ["", f"- 抜き出した条のうち「家屋敷とは」「家屋敷をいう」を含む条：{defs if defs else 'なし'}", ""]

    ok = sum(1 for r in RESULTS if r["ok"] is True)
    ng = [r for r in RESULTS if r["ok"] is False]
    md += [f"## 検査の数", "", f"- 文字列の検査 {ok + len(ng)} 件（OK {ok}、NG {len(ng)}）。ほかに数を数えただけの行（結果 —）がある。"]
    (OUT / "evidence.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (OUT / "checks.json").write_text(json.dumps(RESULTS, ensure_ascii=False, indent=1), encoding="utf-8")
    print("OK", ok, "NG", len(ng))
    for r in ng:
        print("NG", r["id"], r["target"])


if __name__ == "__main__":
    main()
