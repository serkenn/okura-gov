"""R2X elderly-abroad: 老人扶養・同居老親等、国外居住親族、居住者・非居住者の判定、健保の被扶養者（直系尊属・国内居住要件）
に関係する条文を、e-Gov 法令API v2 の /law_data で時点（asof）ごとに取得して、テキストと版の差分にする。

実行（Windows）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_elderly-abroad_laws.py [略称 ...]
  （略称を指定すると、その JOBS だけを実行し、取得記録を fetch_log_<略称…>.json に書く。指定しなければ全部で fetch_log.json）

標準ライブラリのみ。リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。
scripts/R1_egov_articles.py と scripts/IMPL_kyuyo_fetch.py の inline / render / walk / fetch_full を写して作った（import はしない）。

- ダウンロードした JSON は .work/downloads/<ts>_R2X_elderly-abroad_laws/ に置く（信頼できないデータ。中でコードを実行しない）。
- 出力は scripts/results/R2X_elderly-abroad_laws/：
  - fetch_log.json：取得URL、asof、law_revision_id、改正法令、施行日、状態、生データの SHA-256 とバイト数
  - articles_<略称>_<asof>.txt：指定した条（第2条は指定した号だけ）の本文
  - kwhits_<略称>_<asof>.txt：キーワードを含む条（本則・附則）の場所と、その条の本文
  - diff_<略称>_<asof1>_vs_<asof2>.diff：指定した条の本文の版の差分（unified diff）
"""
import difflib
import hashlib
import json
import sys
import pathlib
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "okura-gov-research/0.1"
API = "https://laws.e-gov.go.jp/api/2"
SLEEP = 1.5
NAME = "R2X_elderly-abroad_laws"

KW_SHOTOKU = ["国外居住", "国外居住親族", "親族関係書類", "送金関係書類", "留学ビザ等書類", "三十八万円送金書類", "同居老親等",
              "第三十四号の二", "国内に住所を有しない者と推定", "国内に住所を有する者と推定"]
KW_CHIHO = ["国外居住", "国外居住親族", "親族関係書類", "送金関係書類", "同居老親等", "同居直系尊属", "老人扶養親族",
            "非居住者である", "親族に該当する旨を証する書類", "生計を一にすることを明らかにする書類"]
KW_KENPO = ["日本国内に住所を有", "国内に住所を有しない", "留学", "生活の基礎"]

# (略称, law_id, [asof...], 指定する条 [(条番号 Num, 第1項の号の Num の list か None)], キーワード, 差分を取るか)
# asof の選び方：所得税は年分の12月31日（令和7年分＝2025-12-31、令和8年分＝2026-12-31）と取得日（2026-11-09）。
# 住民税は賦課期日（令和8年度分＝2026-01-01、令和9年度分＝2027-01-01）と取得日。健保は取得日と 2025-12-31。
JOBS = [
    ("shotoku", "340AC0000000033", ["2025-12-31", "2026-11-09", "2026-12-31"],
     [("2", ["3", "4", "5", "34", "34_2", "34_3", "34_4", "34_5"]), ("3", None), ("84", None), ("85", None),
      ("120", None), ("190", None), ("194", None)], KW_SHOTOKU, True),
    ("shotoku-rei", "340CO0000000096", ["2025-12-31", "2026-11-09", "2026-12-31"],
     [("13", None), ("14", None), ("15", None), ("262", None), ("316_2", None)], KW_SHOTOKU, True),
    ("shotoku-ki", "340M50000040011", ["2025-12-31", "2026-11-09", "2026-12-31"],
     [("47_2", None), ("73_2", None)], KW_SHOTOKU, True),
    ("sochi", "332AC0000000026", ["2025-12-31", "2026-11-09", "2026-12-31"],
     [("41_16", None)], ["同居老親等", "第四十一条の十六"], True),
    ("sochi-rei", "332CO0000000043", ["2026-11-09"], [], ["同居老親等", "第四十一条の十六"], False),
    ("chiho", "325AC0000000226", ["2026-01-01", "2026-11-09", "2027-01-01"],
     [("23", None), ("34", None), ("37", None), ("292", None), ("314_2", None), ("314_6", None)], KW_CHIHO, True),
    ("chiho-ki", "329M50000002023", ["2026-01-01", "2026-11-09", "2027-01-01"], [], KW_CHIHO, True),
    ("kenpo", "211AC0000000070", ["2025-12-31", "2026-11-09"], [("3", None)], KW_KENPO, True),
    ("kenpo-ki", "215M10000008036", ["2025-12-31", "2026-11-09"], [("37_2", None), ("37_3", None), ("38", None)], [], True),
    # 高齢者の医療の確保に関する法律：後期高齢者医療の被保険者（健保法第3条第1項第7号・第7項ただし書が参照）
    ("koukirei", "357AC0000000080", ["2026-11-09"], [("50", None), ("51", None)], [], False),
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


# ---- テキスト化（scripts/R1_egov_articles.py の inline / render を写したもの） ----
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


def render_article_items(a, item_nums):
    """第1項のうち指定した号だけを出す（所得税法第2条のように長い定義の条のため）。"""
    lines = []
    for c in a.get("children", []):
        if isinstance(c, dict) and c.get("tag") in ("ArticleCaption", "ArticleTitle"):
            lines.append(inline(c))
    for p in a.get("children", []):
        if not (isinstance(p, dict) and p.get("tag") == "Paragraph" and p.get("attr", {}).get("Num") == "1"):
            continue
        for it in p.get("children", []):
            if isinstance(it, dict) and it.get("tag") == "Item" and it.get("attr", {}).get("Num") in item_nums:
                render(it, 0, lines)
    return lines


def fetch_full(law_id, asof, dl):
    q = {"response_format": "json", "asof": asof}
    url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode(q)
    st, body = get(url)
    (dl / f"{law_id}_{asof}.json").write_bytes(body)
    if st != 200:
        raise RuntimeError(f"{url} -> {st} {body[:200]!r}")
    return url, body, json.loads(body)


def main():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_{NAME}"
    dl.mkdir(parents=True, exist_ok=False)
    out = ROOT / "scripts" / "results" / NAME
    out.mkdir(parents=True, exist_ok=True)
    only = sys.argv[1:]
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "user_agent": UA, "only": only, "fetches": []}
    for short, law_id, asofs, arts, kws, do_diff in JOBS:
        if only and short not in only:
            continue
        texts = {}
        for asof in asofs:
            url, body, d = fetch_full(law_id, asof, dl)
            ri = d.get("revision_info") or {}
            entry = {"short": short, "law_id": law_id, "asof": asof, "url": url,
                     "law_title": ri.get("law_title"), "law_revision_id": ri.get("law_revision_id"),
                     "amendment_law_num": ri.get("amendment_law_num"),
                     "amendment_enforcement_date": ri.get("amendment_enforcement_date"),
                     "current_revision_status": ri.get("current_revision_status"),
                     "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
            log["fetches"].append(entry)
            print("ok", short, asof, ri.get("law_revision_id"), ri.get("current_revision_status"), flush=True)
            root = d["law_full_text"]
            main_arts, suppl_arts = [], []

            suppl_nodes = []

            def collect(n, path):
                if n.get("tag") == "SupplProvision":
                    suppl_nodes.append(n)
                if n.get("tag") != "Article":
                    return
                sp = [p for p in path if p.get("tag") == "SupplProvision"]
                if sp:
                    suppl_arts.append((sp[-1].get("attr", {}).get("AmendLawNum", "(原始附則)"), n))
                else:
                    main_arts.append(n)
            walk(root, collect)
            # 条を持たない附則（項だけの附則）は、附則全体を1つの単位として扱う
            for s in suppl_nodes:
                has_art = []
                walk(s, lambda n, p: has_art.append(1) if n.get("tag") == "Article" else None)
                if not has_art:
                    suppl_arts.append((s.get("attr", {}).get("AmendLawNum", "(原始附則)"), s))
            header = [f"# {short} {law_id} asof={asof}",
                      f"# 法令名={ri.get('law_title')} law_revision_id={ri.get('law_revision_id')} 改正法令={ri.get('amendment_law_num')} "
                      f"施行日={ri.get('amendment_enforcement_date')} 状態={ri.get('current_revision_status')}",
                      f"# 取得URL={url}", f"# 取得日時={ts}", f"# 生データ SHA-256={entry['sha256']}", ""]
            # 指定した条
            body_lines = []
            by_num = {a["attr"].get("Num"): a for a in main_arts}
            for num, items in arts:
                a = by_num.get(num)
                if a is None:
                    body_lines += [f"## Num={num}: 見つからない（この時点の本則にない）", ""]
                    continue
                body_lines.append(f"## Num={num}" + (f"（第1項の号 {','.join(items)} だけ）" if items else ""))
                if items:
                    body_lines += render_article_items(a, set(items))
                else:
                    render(a, 0, body_lines)
                body_lines.append("")
            texts[asof] = body_lines
            if arts:
                (out / f"articles_{short}_{asof}.txt").write_text("\n".join(header + body_lines), encoding="utf-8")
            # キーワードを含む条（本則・附則）
            if kws:
                kl = list(header) + [f"# キーワード={kws}", ""]
                summary = []
                for part, amend, a in [("本則", None, a) for a in main_arts] + [("附則", an, a) for an, a in suppl_arts]:
                    lines = []
                    render(a, 0, lines)
                    txt = "\n".join(lines)
                    found = [k for k in kws if k in txt]
                    if not found:
                        continue
                    num = a.get("attr", {}).get("Num")
                    summary.append(f"{part}\t{amend or ''}\tNum={num}\t{','.join(found)}")
                    # 本則の長い条（定義の条など）は、キーワードを含む行だけを出す
                    if part == "本則" and len(txt) > 20000:
                        kl.append(f"## {part} Num={num} 該当行のみ（{len(txt)}字の条のため）: {','.join(found)}")
                        kl += [ln for ln in lines if any(k in ln for k in found)]
                    else:
                        kl.append(f"## {part} {amend or ''} Num={num}: {','.join(found)}")
                        kl += lines
                    kl.append("")
                kl = kl[:6] + ["# 一覧（部分\t改正法令\t条\tキーワード）"] + summary + [""] + kl[6:]
                (out / f"kwhits_{short}_{asof}.txt").write_text("\n".join(kl), encoding="utf-8")
        if do_diff and arts:
            for a1, a2 in zip(asofs, asofs[1:]):
                diff = difflib.unified_diff(texts[a1], texts[a2], fromfile=f"{short}@{a1}", tofile=f"{short}@{a2}", lineterm="", n=1)
                (out / f"diff_{short}_{a1}_vs_{a2}.diff").write_text("\n".join(diff) + "\n", encoding="utf-8")
    (out / ("fetch_log.json" if not only else f"fetch_log_{'_'.join(only)}.json")).write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", out)


if __name__ == "__main__":
    main()
