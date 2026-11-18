"""R3X chiho-sochi: e-Gov 法令API v2 で、地方税法・同施行令・同施行規則・租税特別措置法を時点（asof）ごとに取得し、
住民税の所得の計算（地方税法第313条第2項・第32条第2項）と租税特別措置法の所得計算の特例の関係を、条文の文字列で調べる。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_chiho-sochi_egov.py

- e-Gov 法令API v2 の使い方（/law_data、/laws の検索、テキスト化）は scripts/R1_egov_articles.py と scripts/IMPL_kyuyo_fetch.py を写した（import しない）。
- リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。
- ダウンロードした JSON は新しい空のディレクトリ .work/downloads/<YYYYMMDD-HHMMSS>_R3X_chiho-sochi_egov/ に置く（信頼できないデータ。中で何も実行しない）。
- 出力は scripts/results/R3X_chiho-sochi_egov/：
  - fetch_log.json：取得URL、asof、law_revision_id、施行日、状態、生データの SHA-256 とバイト数
  - articles_<略称>_<asof>.txt：抜き出した条（本則）のテキスト
  - phrase_hits_<略称>_<asof>.md：「所得税に関する法令」「の例によらない」などの語を含む文（場所つき。本則・附則の全文）
  - sochi_refs_<略称>_<asof>.md：「租税特別措置法」を含む文の数と、調べる6つの条（第25条の2・第27条・第29条の4・第41条の3の11・第41条の4・
    第41条の15の3）の条番号の文字列を含む文
  - toc_sochi_<asof>.txt：租税特別措置法の章・節・款の題名と条の見出し（本則）
"""
import hashlib
import json
import pathlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "okura-gov-research/0.1"
API = "https://laws.e-gov.go.jp/api/2"
SLEEP = 1.5

CHIHO, CHIHO_REI, SOCHI = "325AC0000000226", "325CO0000000245", "332AC0000000026"

# 調べる措置法の条（漢数字の条番号の文字列 → 略記）
TARGETS = {
    "第二十五条の二": "措法25の2（青色申告特別控除）",
    "第二十七条": "措法27（家内労働者等）",
    "第二十九条の四": "措法29の4（給与所得控除の最低控除額等の特例）",
    "第四十一条の三の十一": "措法41の3の11（所得金額調整控除）",
    "第四十一条の四": "措法41の4（不動産所得の損益通算の特例）",
    "第四十一条の十五の三": "措法41の15の3（公的年金等控除の最低控除額等の特例）",
}
PHRASES = ["所得税に関する法令", "の例によらない", "の例によらず", "規定を除く。）の例により", "租税特別措置法の規定"]

# (略称, law_id or None（題名で検索）, 題名, [asof...], [本則の条番号 Num])
JOBS = [
    # 2026-12-01 は措法の令和8年改正（第29条の4 の新設と旧第29条の4 の第29条の5 への繰下げ）の施行日。第292条第1項第6号の引用を見るため
    ("chiho", CHIHO, "地方税法", ["2026-11-09", "2026-12-01", "2027-01-01"], ["1", "23", "32", "72_49_12", "292", "313"]),
    ("chiho-rei", CHIHO_REI, "地方税法施行令", ["2026-11-09", "2027-01-01"], ["7_10_5", "7_11", "48_5_2", "48_5_3"]),
    # 所得金額調整控除が措法第41条の3の3 にあった時点の施行令（第7条の10の5・第48条の5の2 の当時の文言を見るため）と、
    # 令和6年政令第136号（附則第1条第1号：第7条の10の5・第48条の5の2 の改正規定は令和7年1月1日施行）の前後、令和8年度の賦課期日の版
    ("chiho-rei", CHIHO_REI, "地方税法施行令", ["2021-01-01", "2024-12-31", "2025-01-01", "2026-01-01"], ["7_10_5", "48_5_2"]),
    ("chiho-ki", None, "地方税法施行規則", ["2026-11-09"], ["6_8"]),
    ("sochi", SOCHI, "租税特別措置法", ["2026-11-09", "2026-12-01", "2027-01-01"],
     ["1", "2", "25_2", "27", "29_4", "41_3_11", "41_4", "41_15_3"]),
    # 平成30年度改正の所得金額調整控除が当時どの条にあったかを見るため（目次だけ）
    ("sochi", SOCHI, "租税特別措置法", ["2021-01-01"], ["41_3_3"]),
]

BLOCK_LIKE = {"Paragraph", "Item"} | {f"Subitem{i}" for i in range(1, 11)}


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            body, st = r.read(), r.status
    except urllib.error.HTTPError as e:
        body, st = e.read(), e.code
    time.sleep(SLEEP)
    return st, body


# ---- テキスト化（scripts/IMPL_kyuyo_fetch.py の inline / render / walk を写したもの） ----
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
            walk(c, fn, path + (n,))


def caption_of(a):
    for c in a.get("children", []):
        if isinstance(c, dict) and c.get("tag") == "ArticleCaption":
            return inline(c)
    return ""


def locate(path, node):
    """場所：本則/附則（AmendLawNum）、条番号、見出し、項番号、号番号。"""
    loc = {"part": "本則", "amend_law_num": None, "article": None, "caption": None, "paragraph": None, "item": None}
    for p in list(path) + [node]:
        t = p.get("tag")
        a = p.get("attr") or {}
        if t == "SupplProvision":
            loc["part"] = "附則"
            loc["amend_law_num"] = a.get("AmendLawNum", "(原始附則)")
        elif t in ("AppdxTable", "AppdxNote", "Appdx", "AppdxStyle", "AppdxFormat", "AppdxFig"):
            loc["part"] = t
        elif t == "Article":
            loc["article"] = a.get("Num")
            loc["caption"] = caption_of(p)
        elif t == "Paragraph":
            loc["paragraph"] = a.get("Num")
        elif t == "Item":
            loc["item"] = a.get("Num")
    return loc


def sentences(root):
    """(場所, 文) の一覧。Sentence 単位。"""
    out = []

    def fn(n, path):
        if n.get("tag") == "Sentence":
            out.append((locate(path, n), inline(n)))
    walk(root, fn)
    return out


def where(loc):
    s = f"{loc['part']}"
    if loc["amend_law_num"]:
        s += f"（{loc['amend_law_num']}）"
    if loc["article"]:
        s += f" 第{loc['article']}条"
    if loc["caption"]:
        s += f" {loc['caption']}"
    if loc["paragraph"]:
        s += f" 第{loc['paragraph']}項"
    if loc["item"]:
        s += f" 第{loc['item']}号"
    return s


def search_law_id(title):
    q = urllib.parse.urlencode({"law_title": title, "response_format": "json"})
    url = f"{API}/laws?{q}"
    st, body = get(url)
    if st != 200:
        return None, url, st
    for it in json.loads(body).get("laws", []):
        ri = it.get("revision_info") or it.get("current_revision_info") or {}
        li = it.get("law_info") or {}
        if ri.get("law_title") == title:
            return li.get("law_id"), url, st
    return None, url, st


def main():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R3X_chiho-sochi_egov"
    dl.mkdir(parents=True, exist_ok=False)
    out = ROOT / "scripts" / "results" / "R3X_chiho-sochi_egov"
    out.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "searches": [], "fetches": []}
    for short, law_id, title, asofs, arts in JOBS:
        if law_id is None:
            law_id, surl, sst = search_law_id(title)
            log["searches"].append({"title": title, "url": surl, "status": sst, "law_id": law_id})
            print("search", title, law_id, flush=True)
            if not law_id:
                continue
        for asof in asofs:
            url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode({"response_format": "json", "asof": asof})
            st, body = get(url)
            (dl / f"{law_id}_{asof}.json").write_bytes(body)
            entry = {"short": short, "law_id": law_id, "asof": asof, "url": url, "status": st,
                     "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
            if st != 200:
                log["fetches"].append(entry)
                print("NG", short, asof, st, flush=True)
                continue
            d = json.loads(body)
            ri = d.get("revision_info") or {}
            entry.update({"law_title": ri.get("law_title"), "law_revision_id": ri.get("law_revision_id"),
                          "amendment_law_num": ri.get("amendment_law_num"),
                          "amendment_enforcement_date": ri.get("amendment_enforcement_date"),
                          "current_revision_status": ri.get("current_revision_status")})
            log["fetches"].append(entry)
            print("ok", short, asof, ri.get("law_revision_id"), flush=True)
            root = d["law_full_text"]
            header = [f"# {short} {law_id} asof={asof}",
                      f"# 法令名={ri.get('law_title')} law_revision_id={ri.get('law_revision_id')} 改正法令={ri.get('amendment_law_num')} "
                      f"施行日={ri.get('amendment_enforcement_date')} 状態={ri.get('current_revision_status')}",
                      f"# 取得URL={url}", f"# 取得日時={ts}", f"# 生データ SHA-256={entry['sha256']}", ""]
            # 本則の条
            main_arts = []

            def collect(n, path):
                if n.get("tag") == "Article" and not any(p.get("tag") == "SupplProvision" for p in path):
                    main_arts.append(n)
            walk(root, collect)
            by_num = {a["attr"].get("Num"): a for a in main_arts}
            if arts:
                lines = list(header)
                for num in arts:
                    a = by_num.get(num)
                    if a is None:
                        lines += [f"## Num={num}: 見つからない（この時点の本則にない）", ""]
                        continue
                    lines.append(f"## Num={num}")
                    render(a, 0, lines)
                    lines.append("")
                (out / f"articles_{short}_{asof}.txt").write_text("\n".join(lines), encoding="utf-8")
            sents = sentences(root)
            # 語の出現
            ph = list(header) + [f"文の数（本則・附則・別表の Sentence）: {len(sents)}", ""]
            for kw in PHRASES:
                hits = [(loc, s) for loc, s in sents if kw in s]
                ph.append(f"## 「{kw}」を含む文：{len(hits)} 件")
                for loc, s in hits:
                    i = s.find(kw)
                    ph.append(f"- {where(loc)}：…{s[max(0, i - 200): i + 200]}…")
                ph.append("")
            (out / f"phrase_hits_{short}_{asof}.md").write_text("\n".join(ph), encoding="utf-8")
            # 措置法の参照
            sr = list(header)
            so = [(loc, s) for loc, s in sents if "租税特別措置法" in s]
            sr.append(f"「租税特別措置法」を含む文：{len(so)} 件（本則 {sum(1 for l, _ in so if l['part'] == '本則')} 件、"
                      f"附則 {sum(1 for l, _ in so if l['part'] == '附則')} 件）")
            # 「租税特別措置法第…条」の形で引く条番号の集計（「同法第…」は数えない）
            refs = {}
            for loc, s in so:
                for m in re.finditer(r"租税特別措置法(施行令|施行規則)?第([〇一二三四五六七八九十百千]+条(?:の[〇一二三四五六七八九十]+)*)", s):
                    key = ("措令" if m.group(1) == "施行令" else "措規" if m.group(1) == "施行規則" else "措法") + "第" + m.group(2)
                    refs[key] = refs.get(key, 0) + 1
            sr.append(f"「租税特別措置法（施行令・施行規則）第…条」の形の参照：{len(refs)} 種類（多い順。「同法第…」の形は数えていない）")
            sr += [f"- {k}: {v}" for k, v in sorted(refs.items(), key=lambda kv: -kv[1])]
            sr.append("")
            for art, label in TARGETS.items():
                # 「租税特別措置法」を含む文のうち、調べる条番号の文字列を含むもの（後ろに「の」が続く別の条は除く）
                pat = re.compile(re.escape(art) + r"(?!の)")
                hits = [(loc, s) for loc, s in so if pat.search(s)]
                sr.append(f"## {label}：「租税特別措置法」を含む文で「{art}」（直後に「の」が続かない）を含むもの {len(hits)} 件")
                for loc, s in hits:
                    i = pat.search(s).start()
                    sr.append(f"- {where(loc)}：…{s[max(0, i - 160): i + 160]}…")
                sr.append("")
            (out / f"sochi_refs_{short}_{asof}.md").write_text("\n".join(sr), encoding="utf-8")
            # 措置法の目次
            if short == "sochi":
                toc = list(header)

                def tocfn(n, path):
                    t = n.get("tag")
                    if any(p.get("tag") == "SupplProvision" for p in path):
                        return
                    if t in ("PartTitle", "ChapterTitle", "SectionTitle", "SubsectionTitle", "DivisionTitle"):
                        toc.append({"PartTitle": "", "ChapterTitle": "", "SectionTitle": "  ", "SubsectionTitle": "    ",
                                    "DivisionTitle": "      "}[t] + inline(n))
                    if t == "Article":
                        toc.append("        " + n["attr"].get("Num", "") + "\t" + caption_of(n))
                walk(root, tocfn)
                (out / f"toc_sochi_{asof}.txt").write_text("\n".join(toc), encoding="utf-8")
    (out / "fetch_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", out, dl)


if __name__ == "__main__":
    main()
