"""R2X juminzei-tax: 個人住民税の税額の計算（所得割・均等割・調整控除・税額控除・端数処理）の条文を、
e-Gov 法令API v2 で時点（asof）ごとに取得し、条ごとのテキストと版の間の差分を書く。

実行:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_juminzei-tax_laws.py            # 全部
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_juminzei-tax_laws.py shinrin    # 指定した略称だけ

標準ライブラリのみ。リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。
e-Gov の使い方は scripts/R1_egov_articles.py と scripts/IMPL_juminzei_laws.py を写した（import はしない）。

- ダウンロードした JSON は .work/downloads/<ts>_R2X_juminzei-tax_laws/ に置く（信頼できないデータ。中でコードを実行しない）。
- 出力は scripts/results/R2X_juminzei-tax_laws/:
  - <略称>_<asof>.txt          抜き出した本則の条・原始附則の条（版の情報つき）
  - <略称>_<asof>.articles.json 条ごとのテキスト（{"本則:314_6": "...", "附則:5_4": "..."}）。計算の検査（R2X_juminzei-tax_calc.py）が読む
  - <略称>_<asof>.amend.txt    改正附則（AmendLawNum が指定の正規表現に合うもの）の本文
  - index_<略称>_<asof>.txt    本則と原始附則の条番号と見出しの一覧
  - diff_<略称>_<asofA>_vs_<asofB>.md 条ごとの変化の有無と、変化した条の差分
  - fetch_log.json / fetch_log_<略称>.json 取得した URL・版・状態
"""
import difflib
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "okura-gov-research/0.1"
API = "https://laws.e-gov.go.jp/api/2"
SLEEP = 1.5
NAME = "R2X_juminzei-tax_laws"

# 令和8年度分の賦課期日, 今日（現行）, 令和9年度分の賦課期日, 令和10年度分の賦課期日（令和9年度分との違いを見るため）
ASOFS = ["2026-01-01", "2026-11-09", "2027-01-01", "2028-01-01"]

CHIHO_MAIN = ["1", "20_4_2", "24", "24_5", "32", "33", "34", "35", "36", "37", "37_2", "37_3", "37_4", "38", "41",
              "292", "294", "310", "311", "313", "314", "314_2", "314_3", "314_5", "314_6", "314_7", "314_8", "314_9", "319",
              # 退職所得の分離課税（D20 で退職所得を対象に含めた）
              "50_2", "50_3", "50_4", "328", "328_2", "328_3", "328_6"]
CHIHO_SUPPL_NUMS = ["3_3", "4_5", "5", "5_2:5_3", "5_4", "5_5", "5_6", "5_7", "5_12", "5_13", "7", "7_2", "7_3",
                    # 上場株式等の配当・譲渡の分離課税（D20 で対象に含めた）
                    "33_2", "35_2", "35_2_2", "35_2_6"]
CHIHO_SUPPL_RE = r"配当控除|住宅借入金|寄附金|特別税額控除|所得割の非課税|均等割|所得割の税率|特例控除|調整控除"

# (略称, 法令名（/laws の law_title 完全一致）, 既知の law_id（None なら検索）, asofs, 本則の条番号（"__ALL__" で全部）,
#  本則で見出しか本文に当たったら抜き出す正規表現, 原始附則の条番号（"__ALL__" で全部）, 原始附則で見出しか本文に当たったら抜き出す正規表現,
#  抜き出す改正附則の AmendLawNum の正規表現)
JOBS = [
    ("chiho", "地方税法", "325AC0000000226", ASOFS, CHIHO_MAIN, None, CHIHO_SUPPL_NUMS, CHIHO_SUPPL_RE,
     [r"^令和七年三月三一日法律第七号$", r"^令和八年三月三一日法律第二号$"]),
    # 人的控除差調整額に「所得税の基礎控除の額−48万円」を加えた改正（寄附金税額控除・申告特例・住宅借入金等）がいつ施行されたかを見る
    ("chiho-0401", "地方税法", "325AC0000000226", ["2026-03-31", "2026-04-01"], ["37_2", "314_7"], None, ["5_4", "5_4_2", "7_2"], None, []),
    # 改正附則のうち、e-Gov が施行前の版では表示しない項（令和8年法律第2号附則第11条の第11項・第13項など）を見るための遠い時点
    ("chiho-far", "地方税法", "325AC0000000226", ["2030-01-01"], [], None, [], None,
     [r"^令和八年三月三一日法律第二号$"]),
    ("chiho-rei", "地方税法施行令", "325CO0000000245", ["2026-11-09", "2027-01-01"], [],
     r"第三百十四条の七|第三十七条の二|附則第五条の四|附則第五条の五|附則第七条|第三百十四条の六|第二十条の四の二|第三百十条|第三十八条|第三百十四条の三|第三十五条第二項|寄附金税額控除|住宅借入金等特別税額控除",
     [], r"附則第五条の四|住宅借入金|寄附金税額控除|配当控除|特例控除",
     [r"^令和八年"]),
    ("shinrin", "森林環境税及び森林環境譲与税に関する法律", None, ["2026-11-09", "2027-01-01"], ["__ALL__"], None, ["__ALL__"], None, []),
    ("shinrin-rei", "森林環境税及び森林環境譲与税に関する法律施行令", None, ["2026-11-09", "2027-01-01"], ["__ALL__"], None, ["__ALL__"], None, []),
    # 指定都市（地方自治法第252条の19第1項）の一覧。所得割の標準税率・調整控除・寄附金税額控除などの率が変わる
    ("shitei", "地方自治法第二百五十二条の十九第一項の指定都市の指定に関する政令", None, ["2026-11-09", "2027-01-01"], ["__ALL__"], None, ["__ALL__"], None, []),
    ("shinsai", "東日本大震災からの復興に関し地方公共団体が実施する防災のための施策に必要な財源の確保に係る地方税の臨時特例に関する法律",
     None, ["2026-11-09"], ["__ALL__"], None, ["__ALL__"], None, []),
]

# 全文（本則・原始附則）から出現箇所を書き出す語（端数処理と上限の定めを探す）
HIT_PATTERNS = [r"一円未満の端数", r"百円未満の端数", r"千円未満の端数", r"一円に切り上げ|これを切り上げ|切り上げた金額", r"制限税率"]

BLOCK_LIKE = {"Paragraph", "Item"} | {f"Subitem{i}" for i in range(1, 11)}


def get(url, dest=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            body, st = r.read(), r.status
    except urllib.error.HTTPError as e:
        body, st = e.read(), e.code
    if dest is not None:
        dest.write_bytes(body)
    time.sleep(SLEEP)
    return st, body


# ---- R1_egov_articles.py / IMPL_juminzei_laws.py から写した描画 ----
def inline(n):
    if isinstance(n, str):
        return n
    if n.get("tag") in ("Rt",):
        return ""
    parts = [inline(c) for c in n.get("children", [])]
    if n.get("tag", "").endswith("Sentence") and any(isinstance(c, dict) and c.get("tag") == "Column" for c in n.get("children", [])):
        return "　".join(p for p in parts if p)
    return "".join(parts)


def render(n, depth, lines):
    if isinstance(n, str):
        if n.strip():
            lines.append("  " * depth + n)
        return
    tag = n.get("tag", "")
    ch = n.get("children", [])
    if tag in BLOCK_LIKE:
        title = "".join(inline(c) for c in ch if isinstance(c, dict) and c.get("tag", "").endswith(("Num", "Title")) and c.get("tag") != "ParagraphCaption")
        sent = [c for c in ch if isinstance(c, dict) and c.get("tag", "").endswith("Sentence")]
        body = "　".join(inline(s) for s in sent)
        cap = [inline(c) for c in ch if isinstance(c, dict) and c.get("tag") == "ParagraphCaption"]
        if cap:
            lines.append("  " * depth + cap[0])
        num = n.get("attr", {}).get("Num", "")
        prefix = title if title else (f"（{tag}{num}）" if tag == "Paragraph" else "")
        lines.append("  " * depth + (prefix + "　" if prefix else "") + body)
        for c in ch:
            if isinstance(c, dict) and not (c.get("tag", "").endswith(("Num", "Title", "Sentence")) or c.get("tag") == "ParagraphCaption"):
                render(c, depth + 1, lines)
        return
    if tag == "TableRow":
        cells = [inline(c).replace("\n", " ") for c in ch if isinstance(c, dict)]
        lines.append("  " * depth + "| " + " | ".join(cells) + " |")
        return
    if tag in ("ArticleCaption", "ArticleTitle", "SupplProvisionLabel", "ChapterTitle", "SectionTitle"):
        lines.append("  " * depth + inline(n))
        return
    for c in ch:
        render(c, depth, lines)


def walk(n, fn, path=()):
    if isinstance(n, dict):
        fn(n, path)
        for c in n.get("children", []):
            walk(c, fn, path + (n.get("tag"),))


def caption(a):
    for c in a.get("children", []):
        if isinstance(c, dict) and c.get("tag") == "ArticleCaption":
            return inline(c)
    return ""


def find_law_id(title, dl, tag, log):
    q = urllib.parse.urlencode({"law_title": title, "response_format": "json", "asof": "2026-11-09"})
    url = f"{API}/laws?{q}"
    st, body = get(url, dl / f"laws_{tag}.json")
    log["lookups"].append({"title": title, "url": url, "status": st})
    if st != 200:
        return None
    data = json.loads(body)
    for law in data.get("laws", []):
        rv = law.get("current_revision_info") or law.get("revision_info") or {}
        if rv.get("law_title") == title:
            return law["law_info"]["law_id"]
    return None


def split(root):
    """本則の条、原始附則（AmendLawNum なし）の条、改正附則（AmendLawNum ごと）に分ける。"""
    main_arts, orig_suppl_arts, amend_suppl = [], [], []

    def fn(n, path):
        if n.get("tag") == "Article":
            if "SupplProvision" not in path:
                main_arts.append(n)
        if n.get("tag") == "SupplProvision":
            if not n.get("attr", {}).get("AmendLawNum"):
                walk(n, lambda m, p: orig_suppl_arts.append(m) if m.get("tag") == "Article" else None)
                # 条のない原始附則（項だけの附則）も拾う
                if not any(isinstance(c, dict) and c.get("tag") == "Article" for c in n.get("children", [])):
                    orig_suppl_arts.append({"tag": "Article", "attr": {"Num": "(no-article)"}, "children": n.get("children", [])})
            else:
                amend_suppl.append(n)
    walk(root, fn)
    if not main_arts:
        # 条のない本則（項だけの政令など）は本則全体を一つの「条」として扱う
        mp = []
        walk(root, lambda m, p: mp.append(m) if m.get("tag") == "MainProvision" else None)
        for m in mp:
            main_arts.append({"tag": "Article", "attr": {"Num": "(no-article)"}, "children": m.get("children", [])})
    return main_arts, orig_suppl_arts, amend_suppl


def text_of(n):
    lines = []
    render(n, 0, lines)
    return "\n".join(l.strip() for l in lines)


def article_diff_md(a_json, b_json, x, y, short):
    keys = sorted(set(a_json) | set(b_json), key=lambda k: (k.split(":")[0], [int(p) if p.isdigit() else p for p in re.split(r"[_:]", k.split(":", 1)[1])]))
    out = [f"# {short}: {x} → {y} の条ごとの変化", "", "| 条 | 変化 |", "|---|---|"]
    details = []
    for k in keys:
        a, b = a_json.get(k), b_json.get(k)
        if a is None:
            out.append(f"| {k} | 新設（{x} にない） |")
        elif b is None:
            out.append(f"| {k} | 削除（{y} にない） |")
        elif a == b:
            out.append(f"| {k} | 同じ |")
        else:
            out.append(f"| {k} | **違う** |")
            sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
            details.append(f"\n## {k}\n")
            for op, i1, i2, j1, j2 in sm.get_opcodes():
                if op == "equal":
                    continue
                ctx_a = a[max(0, i1 - 40):i1].replace("\n", " ")
                details.append(f"- {op}: …{ctx_a}【{a[i1:i2]}】→【{b[j1:j2]}】")
    return "\n".join(out + details) + "\n"


def main():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_{NAME}"
    dl.mkdir(parents=True, exist_ok=False)
    out = ROOT / "scripts" / "results" / NAME
    out.mkdir(parents=True, exist_ok=True)
    only = set(sys.argv[1:])
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "only": sorted(only), "lookups": [], "fetches": [], "errors": []}

    for short, title, law_id, asofs, main_nums, main_re, suppl_nums, suppl_re, amend_nums in JOBS:
        if only and short not in only:
            continue
        try:
            if law_id is None:
                law_id = find_law_id(title, dl, short, log)
                if law_id is None:
                    log["errors"].append({"law": title, "error": "law_id not found"})
                    print(f"ERR {short} law_id not found", flush=True)
                    continue
            arts_by_asof = {}
            for asof in asofs:
                q = {"response_format": "json", "asof": asof}
                url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode(q)
                st, raw = get(url, dl / f"{short}_{asof}.json")
                if st != 200:
                    log["errors"].append({"law": title, "asof": asof, "status": st, "body": raw[:300].decode("utf-8", "replace")})
                    print(f"ERR {short} {asof} {st}", flush=True)
                    continue
                d = json.loads(raw)
                ri = d.get("revision_info") or {}
                li = d.get("law_info") or {}
                log["fetches"].append({"short": short, "law": title, "law_id": law_id, "law_num": li.get("law_num"), "asof": asof, "url": url,
                                       "bytes": len(raw),
                                       "law_revision_id": ri.get("law_revision_id"), "amendment_law_num": ri.get("amendment_law_num"),
                                       "amendment_law_title": ri.get("amendment_law_title"),
                                       "amendment_enforcement_date": ri.get("amendment_enforcement_date"),
                                       "updated": ri.get("updated"),
                                       "current_revision_status": ri.get("current_revision_status")})
                root = d["law_full_text"]
                main_arts, orig_arts, amend_suppl = split(root)
                header = [f"# {title}（{li.get('law_num')}） law_id={law_id} asof={asof}",
                          f"# law_revision_id={ri.get('law_revision_id')} 改正法令={ri.get('amendment_law_num')} 施行日={ri.get('amendment_enforcement_date')} 状態={ri.get('current_revision_status')} updated={ri.get('updated')}",
                          f"# 取得URL={url}", f"# 取得日時={ts}", ""]
                idx = header + ["## 本則"] + [f"{a['attr'].get('Num')}\t{caption(a)}" for a in main_arts]
                idx += ["", "## 原始附則"] + [f"附則{a['attr'].get('Num')}\t{caption(a)}" for a in orig_arts]
                idx += ["", "## 改正附則（AmendLawNum）"] + sorted({s.get('attr', {}).get('AmendLawNum') or "" for s in amend_suppl})
                (out / f"index_{short}_{asof}.txt").write_text("\n".join(idx) + "\n", encoding="utf-8")

                chosen_main, chosen_suppl = [], []
                by_num = {a["attr"].get("Num"): a for a in main_arts}
                missing = []
                if "__ALL__" in main_nums:
                    chosen_main = [a["attr"].get("Num") for a in main_arts]
                else:
                    for num in main_nums:
                        (chosen_main.append(num) if num in by_num else missing.append(f"本則:{num}"))
                if main_re:
                    for a in main_arts:
                        n = a["attr"].get("Num")
                        if n not in chosen_main and (re.search(main_re, text_of(a)) or re.search(main_re, caption(a))):
                            chosen_main.append(n)
                sby = {a["attr"].get("Num"): a for a in orig_arts}
                if "__ALL__" in suppl_nums:
                    chosen_suppl = [a["attr"].get("Num") for a in orig_arts]
                else:
                    for num in suppl_nums:
                        (chosen_suppl.append(num) if num in sby else missing.append(f"附則:{num}"))
                if suppl_re:
                    for a in orig_arts:
                        n = a["attr"].get("Num")
                        if n not in chosen_suppl and (re.search(suppl_re, caption(a)) or re.search(suppl_re, text_of(a))):
                            chosen_suppl.append(n)
                lines = list(header)
                arts_json = {}
                for m in missing:
                    lines += [f"## {m}: 見つからない（この時点にない）", ""]
                for num in chosen_main:
                    lines.append(f"## 本則 Num={num}")
                    render(by_num[num], 0, lines)
                    lines.append("")
                    arts_json[f"本則:{num}"] = text_of(by_num[num])
                for num in chosen_suppl:
                    lines.append(f"## 原始附則 Num={num}")
                    render(sby[num], 0, lines)
                    lines.append("")
                    arts_json[f"附則:{num}"] = text_of(sby[num])
                (out / f"{short}_{asof}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
                (out / f"{short}_{asof}.articles.json").write_text(json.dumps({"law": title, "law_id": law_id, "asof": asof,
                                                                               "law_revision_id": ri.get("law_revision_id"),
                                                                               "articles": arts_json}, ensure_ascii=False, indent=1), encoding="utf-8")
                if amend_nums:
                    alines = list(header)
                    for an in amend_nums:
                        hits = [s for s in amend_suppl if re.search(an, s.get("attr", {}).get("AmendLawNum") or "")]
                        alines.append(f"## 改正附則 AmendLawNum~/{an}/: {len(hits)} 件")
                        for s in hits:
                            alines.append(f"### 改正附則 {s.get('attr', {}).get('AmendLawNum')}")
                            render(s, 0, alines)
                        alines.append("")
                    (out / f"{short}_{asof}.amend.txt").write_text("\n".join(alines) + "\n", encoding="utf-8")
                hits = []
                for kind, arts_ in (("本則", main_arts), ("原始附則", orig_arts)):
                    for a in arts_:
                        t = text_of(a).replace("\n", "")
                        for pat in HIT_PATTERNS:
                            for m in re.finditer(pat, t):
                                hits.append({"pattern": pat, "where": kind, "article": a["attr"].get("Num"), "caption": caption(a),
                                             "snippet": t[max(0, m.start() - 120):m.end() + 60]})
                (out / f"hits_{short}_{asof}.json").write_text(json.dumps(hits, ensure_ascii=False, indent=1), encoding="utf-8")
                arts_by_asof[asof] = arts_json
                print(f"ok {short} {asof} {ri.get('law_revision_id')} {ri.get('current_revision_status')} main={len(chosen_main)} suppl={len(chosen_suppl)} missing={missing}", flush=True)
            got = [a for a in asofs if a in arts_by_asof]
            for x, y in zip(got, got[1:]):
                (out / f"diff_{short}_{x}_vs_{y}.md").write_text(article_diff_md(arts_by_asof[x], arts_by_asof[y], x, y, short), encoding="utf-8")
        except Exception as e:  # noqa
            log["errors"].append({"law": title, "error": repr(e)})
            print(f"ERR {short} {e!r}", flush=True)

    (out / ("fetch_log.json" if not only else f"fetch_log_{'_'.join(sorted(only))}.json")).write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", out)


if __name__ == "__main__":
    sys.exit(main())
