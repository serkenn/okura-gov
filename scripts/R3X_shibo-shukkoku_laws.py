"""R3X shibo-shukkoku: 年の中途の死亡・出国の申告（準確定申告）と、損失の繰越・繰戻しに関係する条文を
e-Gov 法令API v2 で取得する。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_shibo-shukkoku_laws.py index
      INDEX_LAWS の本則の「条番号と見出し」の索引を作る（どの条を取り出すかを決めるため）。
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_shibo-shukkoku_laws.py articles
      JOBS の条（本則）を各時点（asof）の版で取り出し、時点の間の差分を書く。
      あわせて、令和七年・令和八年の改正法令の附則のうち、KW（死亡・出国など）に当たる条を取り出す。
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_shibo-shukkoku_laws.py articles <略称> ...
      JOBS のうち指定した略称だけを取り出す（取得記録は fetch_log_articles_<略称>-....json）。

- API の使い方とテキスト化は scripts/R1_egov_articles.py・scripts/IMPL_kyuyo_fetch.py を写した。import はしない。
- ダウンロードした JSON は .work/downloads/<YYYYMMDD-HHMMSS>_R3X_shibo-shukkoku_laws_<mode>/ に置く
  （信頼できないデータ。中でコードを実行しない）。
- 出力は scripts/results/R3X_shibo-shukkoku_laws/。
  - index_<略称>.txt … 本則の条番号と見出し
  - <略称>_<asof>.txt … 取り出した条と附則。先頭に law_revision_id・改正法令・施行日・取得URL・SHA-256
  - diff_<略称>_<asof1>_vs_<asof2>.diff … 時点の間の差分
  - suppl_hits_<略称>_<asof>.txt … 令和七年・令和八年の改正附則のうち KW に当たる条
  - fetch_log_<mode>.json … 取得した URL、版、SHA-256
- リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。個人の情報は送らない。
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
OUT = ROOT / "scripts" / "results" / "R3X_shibo-shukkoku_laws"

# 時点：令和7年分の年末（2025-12-31）、取得日（2026-11-09。現に施行されている版）、
#       令和8年分の年末（2026-12-31。2026-11-09 時点では未施行の改正を含む）、令和9年分の初日（2027-01-01）
ASOFS_SHOTOKU = ["2025-12-31", "2026-11-09", "2026-12-31", "2027-01-01"]
ASOFS_OTHER = ["2026-11-09", "2027-01-01"]

# 索引を作る法令（略称, 法令名, law_id）
INDEX_LAWS = [
    ("shotoku", "所得税法", "340AC0000000033"),
    ("shotoku-rei", "所得税法施行令", "340CO0000000096"),
    ("shotoku-ki", "所得税法施行規則", "340M50000040011"),
    ("tsusoku", "国税通則法", "337AC0000000066"),
    ("sochi", "租税特別措置法", "332AC0000000026"),
    ("chiho", "地方税法", "325AC0000000226"),
]

# (略称, 法令名, law_id, [本則の条番号（Num 属性。枝番は "70_2"）], [asof...])
JOBS = [
    ("shotoku", "所得税法", "340AC0000000033",
     ["2", "3", "69", "70", "70_2", "71", "71_2", "72", "85", "87", "89", "102", "115", "120", "121", "122", "123",
      "124", "125", "126", "127", "128", "129", "130", "131", "138", "139", "140", "141", "142", "165", "166"], ASOFS_SHOTOKU),
    ("shotoku-rei", "所得税法施行令", "340CO0000000096",
     ["14", "15", "201", "204", "204_2", "206", "258", "263", "267", "271", "272", "273"], ASOFS_SHOTOKU),
    ("shotoku-ki", "所得税法施行規則", "340M50000040011",
     ["47", "48", "49", "54"], ASOFS_SHOTOKU),
    ("sochi", "租税特別措置法", "332AC0000000026", ["41_16_2"], ASOFS_SHOTOKU),
    ("tsusoku", "国税通則法", "337AC0000000066", ["2", "5", "10", "11", "23", "117"], ASOFS_OTHER),
    ("tsusoku-rei", "国税通則法施行令", "337CO0000000135", ["2"], ASOFS_OTHER),
    ("shukujitsu", "国民の祝日に関する法律", "323AC1000000178", ["1", "2", "3"], ASOFS_OTHER),
    ("chiho", "地方税法", "325AC0000000226", ["9", "294", "318"], ASOFS_OTHER),
]

# 附則を拾う改正法令（AmendLawNum の先頭）とキーワード
SUPPL_PREFIX = ("令和七年", "令和八年")
SUPPL_KW = (r"死亡|出国|第百二十四条|第百二十五条|第百二十六条|第百二十七条|第百四十一条|第七十一条|雑損失|"
            r"第八十五条|年の中途|第四十一条の十六の二")

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


# ---- 本文のテキスト化（scripts/IMPL_kyuyo_fetch.py の inline / render を写したもの） ----
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


def split(root):
    main_arts, suppl = [], []

    def collect(n, path):
        if n.get("tag") == "Article" and "SupplProvision" not in path:
            main_arts.append(n)
        if n.get("tag") == "SupplProvision":
            suppl.append(n)
    walk(root, collect)
    return main_arts, suppl


def child_text(n, tag):
    for c in n.get("children", []):
        if isinstance(c, dict) and c.get("tag") == tag:
            return inline(c)
    return ""


def fetch_json(url, dl, fname):
    st, body = get(url)
    (dl / fname).write_bytes(body)
    if st != 200:
        raise RuntimeError(f"{url} -> {st} {body[:200]!r}")
    return json.loads(body), hashlib.sha256(body).hexdigest()


def rev_info(d):
    ri = d.get("revision_info") or {}
    return {k: ri.get(k) for k in ("law_revision_id", "law_title", "amendment_law_num", "amendment_law_title",
                                   "amendment_enforcement_date", "amendment_promulgate_date", "current_revision_status", "updated")}


def law_url(law_id, asof):
    return f"{API}/law_data/{law_id}?" + urllib.parse.urlencode({"response_format": "json", "asof": asof})


def header_lines(short, title, law_id, li, asof, ri, url, run_at, sha):
    return [f"# {short} {title} law_id={law_id} 法令番号={li.get('law_num')} asof={asof}",
            f"# law_revision_id={ri['law_revision_id']} 改正法令={ri['amendment_law_num']}（{ri['amendment_law_title']}） "
            f"施行日={ri['amendment_enforcement_date']} 状態={ri['current_revision_status']} updated={ri['updated']}",
            f"# 取得URL={url}", f"# 取得日時={run_at} sha256={sha}", ""]


def mode_index(dl, log):
    for short, title, law_id in INDEX_LAWS:
        asof = "2026-11-09"
        url = law_url(law_id, asof)
        try:
            d, sha = fetch_json(url, dl, f"{short}_{asof}.json")
        except Exception as e:  # noqa
            log["errors"].append({"short": short, "asof": asof, "error": repr(e)})
            print("ERR", short, repr(e), flush=True)
            continue
        ri, li = rev_info(d), d.get("law_info") or {}
        main_arts, suppl = split(d["law_full_text"])
        lines = header_lines(short, title, law_id, li, asof, ri, url, log["run_at"], sha)
        lines += [f"{a['attr'].get('Num')}\t{child_text(a, 'ArticleTitle')}\t{child_text(a, 'ArticleCaption')}" for a in main_arts]
        (OUT / f"index_{short}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        log["fetches"].append({"short": short, "law_id": law_id, "law_num": li.get("law_num"), "asof": asof, "url": url,
                               "sha256": sha, "n_articles": len(main_arts), "n_suppl": len(suppl), **ri})
        print("ok index", short, len(main_arts), ri["law_revision_id"], flush=True)


def extract(d, nums):
    main_arts, suppl = split(d["law_full_text"])
    by_num = {a["attr"].get("Num"): a for a in main_arts}
    body = []
    for num in nums:
        a = by_num.get(num)
        body.append(f"## Num={num}")
        if a is None:
            body += ["（この時点の本則にない）", ""]
            continue
        render(a, 0, body)
        body.append("")
    hits_out = []
    for s in suppl:
        an = (s.get("attr") or {}).get("AmendLawNum", "") or ""
        if not an.startswith(SUPPL_PREFIX):
            continue
        sa = []
        walk(s, lambda n, p: sa.append(n) if n.get("tag") == "Article" else None)
        hits = []
        for a in sa:
            t = []
            render(a, 0, t)
            joined = "\n".join(t)
            kws = sorted(set(re.findall(SUPPL_KW, joined)))
            if kws:
                hits.append((a["attr"].get("Num"), kws, t))
        if hits:
            hits_out.append(f"## 附則 AmendLawNum={an}（KW に当たる条だけ）")
            for num, kws, t in hits:
                hits_out.append(f"### 附則 Num={num} KW={','.join(kws)}")
                hits_out.extend(t)
                hits_out.append("")
    return body, hits_out


def mode_articles(dl, log, only=None):
    for short, title, law_id, nums, asofs in JOBS:
        if only and short not in only:
            continue
        texts = {}
        for asof in asofs:
            url = law_url(law_id, asof)
            try:
                d, sha = fetch_json(url, dl, f"{short}_{asof}.json")
            except Exception as e:  # noqa
                log["errors"].append({"short": short, "asof": asof, "error": repr(e)})
                print("ERR", short, asof, repr(e), flush=True)
                continue
            ri, li = rev_info(d), d.get("law_info") or {}
            body, hits = extract(d, nums)
            head = header_lines(short, title, law_id, li, asof, ri, url, log["run_at"], sha)
            texts[asof] = body
            (OUT / f"{short}_{asof}.txt").write_text("\n".join(head + body) + "\n", encoding="utf-8")
            (OUT / f"suppl_hits_{short}_{asof}.txt").write_text("\n".join(head + hits) + "\n", encoding="utf-8")
            log["fetches"].append({"short": short, "law_id": law_id, "law_num": li.get("law_num"), "asof": asof, "url": url,
                                   "sha256": sha, "suppl_hit_lines": len(hits), **ri})
            print("ok", short, asof, ri["law_revision_id"], flush=True)
        keys = [a for a in asofs if a in texts]
        for x, y in zip(keys, keys[1:]):
            diff = "\n".join(difflib.unified_diff(texts[x], texts[y], f"{short}@{x}", f"{short}@{y}", lineterm=""))
            (OUT / f"diff_{short}_{x}_vs_{y}.diff").write_text(diff + "\n", encoding="utf-8")
            log.setdefault("diff_line_counts", {})[f"{short}_{x}_vs_{y}"] = len(diff.splitlines())


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    only = sys.argv[2:]
    if mode not in ("index", "articles"):
        print(__doc__)
        return 2
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R3X_shibo-shukkoku_laws_{mode}"
    dl.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "mode": mode, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "fetches": [], "errors": []}
    if mode == "index":
        mode_index(dl, log)
    else:
        mode_articles(dl, log, only)
    suffix = mode + ("_" + "-".join(only) if only else "")
    (OUT / f"fetch_log_{suffix}.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", OUT, "errors", len(log["errors"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
