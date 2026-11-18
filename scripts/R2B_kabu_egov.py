"""R2B_kabu: 株式等の譲渡所得・配当所得（申告の選択を含む）の条文を、e-Gov 法令API v2 で時点（asof）ごとに取得し、
条ごとのテキスト、条番号と見出しの索引、キーワードの出現箇所、版どうしの差分を書く。

実行（Windows）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2B_kabu_egov.py            # 全部
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2B_kabu_egov.py sochi chiho  # 略称を指定

標準ライブラリのみ。リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。
e-Gov の使い方（/law_data の JSON、inline / render / walk）は scripts/R1_egov_articles.py と scripts/IMPL_kyuyo_fetch.py を
写した（import はしない）。

- ダウンロードした JSON は .work/downloads/<ts>_R2B_kabu_egov/ に置く（信頼できないデータ。中でコードを実行しない）。
- 出力は scripts/results/R2B_kabu_egov/:
  - articles_<略称>_<asof>.txt    抜き出した本則の条・原始附則の条（版の情報つき）
  - articles_<略称>_<asof>.json   条ごとのテキスト（{"本則:8_4": "...", "附則:33_2": "..."}）。検証のスクリプトが読む
  - index_<略称>_<asof>.txt       本則と原始附則の条番号と見出しの一覧（全条）
  - keyword_hits_<略称>_<asof>.json キーワードの出現箇所（本則/附則、条、項、号、前後の文）
  - diff_<略称>_<asofA>_vs_<asofB>.md 抜き出した条ごとの変化の有無と差分
  - fetch_log.json                取得した URL・law_revision_id・施行日・状態・SHA-256
"""
import difflib
import hashlib
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
NAME = "R2B_kabu_egov"

CAP_KABU = r"配当|株式|特定口座|非課税口座|源泉徴収選択口座|少額上場|未成年者口座|累積投資"
KW_SHOTOKU = ["合計所得金額", "配当控除", "第九十二条", "租税特別措置法第八条の五", "租税特別措置法第三十七条の十一"]
KW_SOCHI = ["総所得金額", "合計所得金額", "第二条第一項第三十号", "第七十二条から第八十七条まで", "確定申告書を提出する場合",
            "その者の選択", "除外したところ", "第九十二条", "所得税法第百二十条", "百分の十五", "百分の五", "三年",
            "三百六十万円", "千八百万円", "百二十万円", "二百四十万円", "千二百万円"]
KW_CHIHO = ["特定配当等", "特定株式等譲渡所得金額", "上場株式等に係る配当所得等の金額", "上場株式等に係る譲渡所得等の金額",
            "合計所得金額", "総所得金額", "申告書", "所得税", "配当割", "株式等譲渡所得割", "百分の三", "百分の五"]
KW_KOKUHO = ["上場株式等", "附則第三十三条の二", "附則第三十五条の二", "他の所得と区分", "特定配当等", "特定株式等譲渡所得金額",
             "総所得金額", "山林所得金額"]

# (略称, law_id, asofs, 本則の条番号, 本則の見出しの正規表現, 原始附則の条番号, 原始附則の見出しの正規表現, キーワード)
#  asof の意味：2025-12-31＝令和7年分の年末、2026-12-31＝令和8年分の年末、2027-01-01＝令和9年分の初日（比較用）、
#  地方税法：2026-01-01＝令和8年度分の賦課期日、2027-01-01＝令和9年度分の賦課期日、
#  国保令：2026-04-01＝令和8年度の初日、2027-04-01＝令和9年度の初日。
JOBS = [
    ("shotoku", "340AC0000000033", ["2025-12-31", "2026-12-31"],
     ["2", "22", "24", "33", "69", "92", "120", "121", "181", "182"], None, [], None, KW_SHOTOKU),
    ("sochi", "332AC0000000026", ["2025-12-31", "2026-12-31", "2027-01-01"],
     ["3", "8_4", "8_5", "8_6", "9", "9_8", "37_10", "37_11", "37_12_2", "37_14"], CAP_KABU, [], None, KW_SOCHI),
    ("sochi-rei", "332CO0000000043", ["2025-12-31", "2026-12-31"],
     ["4_2", "4_3", "25_8", "25_9", "25_11_2"], CAP_KABU, [], None, KW_SOCHI),
    ("chiho", "325AC0000000226", ["2026-01-01", "2027-01-01"],
     ["23", "32", "37_4", "45_2", "292", "313", "314_9", "317_2"], None,
     ["33_2", "35_2", "35_2_2", "35_2_6"], CAP_KABU, KW_CHIHO),
    ("kokuho-rei", "333CO0000000362", ["2026-04-01", "2027-04-01"],
     ["29_3", "29_7"], None, [], None, KW_KOKUHO),
]

BLOCK_LIKE = {"Paragraph", "Item"} | {f"Subitem{i}" for i in range(1, 11)}


def get(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            body, st = r.read(), r.status
    except urllib.error.HTTPError as e:
        body, st = e.read(), e.code
    dest.write_bytes(body)
    time.sleep(SLEEP)
    return st, body


# ---- テキスト化（scripts/R1_egov_articles.py / IMPL_kyuyo_fetch.py の inline / render を写したもの） ----
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
    loc = {"part": "本則", "amend_law_num": None, "article": None, "caption": None, "paragraph": None, "item": None}
    for p in list(path) + [node]:
        t = p.get("tag")
        a = p.get("attr") or {}
        if t == "SupplProvision":
            loc["part"] = "附則"
            loc["amend_law_num"] = a.get("AmendLawNum", "(原始附則)")
        elif t == "Article":
            loc["article"] = a.get("Num")
            loc["caption"] = caption_of(p)
        elif t == "Paragraph":
            loc["paragraph"] = a.get("Num")
        elif t == "Item":
            loc["item"] = a.get("Num")
    return loc


def keyword_hits(root, keywords):
    hits = []

    def fn(n, path):
        if n.get("tag") == "Sentence":
            txt = inline(n)
            for kw in keywords:
                i = txt.find(kw)
                if i >= 0:
                    hits.append({"keyword": kw, **locate(path, n), "snippet": txt[max(0, i - 120): i + 200]})
    walk(root, fn)
    return hits


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8")
    only = set(argv)
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_{NAME}"
    dl.mkdir(parents=True, exist_ok=False)
    out = ROOT / "scripts" / "results" / NAME
    out.mkdir(parents=True, exist_ok=True)
    logp = out / "fetch_log.json"
    log = json.loads(logp.read_text(encoding="utf-8")) if logp.exists() else {"runs": []}
    run = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "fetches": []}
    for short, law_id, asofs, main_nums, main_re, suppl_nums, suppl_re, kws in JOBS:
        if only and short not in only:
            continue
        texts_by_asof = {}
        for asof in asofs:
            url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode({"response_format": "json", "asof": asof})
            st, body = get(url, dl / f"{law_id}_{asof}.json")
            if st != 200:
                print("NG", short, asof, st, body[:200])
                run["fetches"].append({"short": short, "asof": asof, "url": url, "status": st})
                continue
            d = json.loads(body)
            ri = d.get("revision_info") or {}
            entry = {"short": short, "law_id": law_id, "asof": asof, "url": url, "status": st,
                     "law_title": ri.get("law_title"), "law_revision_id": ri.get("law_revision_id"),
                     "amendment_law_num": ri.get("amendment_law_num"),
                     "amendment_enforcement_date": ri.get("amendment_enforcement_date"),
                     "current_revision_status": ri.get("current_revision_status"),
                     "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
            run["fetches"].append(entry)
            print("ok", short, asof, ri.get("law_revision_id"), ri.get("current_revision_status"), flush=True)
            root = d["law_full_text"]
            main_arts, orig_suppl_arts = [], []

            def collect(n, path):
                if n.get("tag") != "Article":
                    return
                sp = [p for p in path if p.get("tag") == "SupplProvision"]
                if not sp:
                    main_arts.append(n)
                elif "AmendLawNum" not in (sp[-1].get("attr") or {}):
                    orig_suppl_arts.append(n)
            walk(root, collect)
            header = [f"# {short} {law_id} asof={asof}",
                      f"# 法令名={ri.get('law_title')} law_revision_id={ri.get('law_revision_id')} 改正法令={ri.get('amendment_law_num')} "
                      f"施行日={ri.get('amendment_enforcement_date')} 状態={ri.get('current_revision_status')}",
                      f"# 取得URL={url}", f"# 取得日時={ts}", f"# 生データ SHA-256={entry['sha256']}", ""]
            idx = list(header) + ["## 本則"] + [f"{a['attr'].get('Num')}\t{caption_of(a)}" for a in main_arts]
            idx += ["", "## 原始附則"] + [f"{a['attr'].get('Num')}\t{caption_of(a)}" for a in orig_suppl_arts]
            (out / f"index_{short}_{asof}.txt").write_text("\n".join(idx), encoding="utf-8")
            sel = []
            for part, arts, nums, rx in (("本則", main_arts, main_nums, main_re), ("附則", orig_suppl_arts, suppl_nums, suppl_re)):
                by_num = {a["attr"].get("Num"): a for a in arts}
                chosen = list(nums)
                if rx:
                    for a in arts:
                        if re.search(rx, caption_of(a)) and a["attr"].get("Num") not in chosen:
                            chosen.append(a["attr"].get("Num"))
                for num in chosen:
                    sel.append((part, num, by_num.get(num)))
            lines = list(header)
            texts = {}
            for part, num, a in sel:
                key = f"{part}:{num}"
                if a is None:
                    lines += [f"## {key}: 見つからない（この時点にない）", ""]
                    texts[key] = None
                    continue
                tl = []
                render(a, 0, tl)
                texts[key] = "\n".join(tl)
                lines.append(f"## {key}")
                lines += tl
                lines.append("")
            (out / f"articles_{short}_{asof}.txt").write_text("\n".join(lines), encoding="utf-8")
            (out / f"articles_{short}_{asof}.json").write_text(
                json.dumps({"meta": entry, "articles": texts}, ensure_ascii=False, indent=1), encoding="utf-8")
            kh = keyword_hits(root, kws)
            (out / f"keyword_hits_{short}_{asof}.json").write_text(
                json.dumps({"meta": entry, "keywords": kws, "hits": kh}, ensure_ascii=False, indent=1), encoding="utf-8")
            texts_by_asof[asof] = texts
        av = list(texts_by_asof)
        for a, b in zip(av, av[1:]):
            ta, tb = texts_by_asof[a], texts_by_asof[b]
            md = [f"# {short}: {a} と {b} の比較（抜き出した条のみ）", ""]
            for key in sorted(set(ta) | set(tb)):
                xa, xb = ta.get(key), tb.get(key)
                if xa == xb:
                    md.append(f"- {key}: 同じ")
                    continue
                md.append(f"- {key}: **違う**")
                md.append("```diff")
                md += list(difflib.unified_diff((xa or "").splitlines(), (xb or "").splitlines(), a, b, lineterm="", n=0))
                md.append("```")
            (out / f"diff_{short}_{a}_vs_{b}.md").write_text("\n".join(md), encoding="utf-8")
    log["runs"].append(run)
    logp.write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
