"""R2B taishoku: 退職所得（所得税・復興特別所得税・住民税）の条文を、e-Gov 法令API v2 で時点（asof）ごとに取得し、
条ごとのテキスト、版の間の差分、改正附則（「退職」を含むもの）を書く。

実行（Windows）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2B_taishoku_egov.py index [略称 ...]  # 「退職」を含む条の索引だけ
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2B_taishoku_egov.py fetch [略称 ...]  # JOBS の条を全時点で取得
標準ライブラリのみ。リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。
e-Gov の使い方は scripts/R1_egov_articles.py と scripts/IMPL_kyuyo_fetch.py を写した（import はしない）。

- ダウンロードした JSON は .work/downloads/<ts>_R2B_taishoku_egov_<mode>/ に置く（信頼できないデータ。中で何も実行しない）。
- 出力は scripts/results/R2B_taishoku_egov/:
  - index_<略称>.txt                本則の条のうち、見出しか本文に「退職」を含む条（出現数つき）と、「退職」を含む附則の改正法令番号
  - <略称>_<asof>.txt               抜き出した本則の条と、改正附則のうち「退職」を含む条（版の情報つき）
  - diff_<略称>_<asofA>_vs_<asofB>.md 条ごとの変化の有無と、変化した条の差分
  - fetch_log_<mode>.json           取得した URL・版・状態・生データの SHA-256
"""
import difflib
import hashlib
import json
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "okura-gov-research/0.1"
API = "https://laws.e-gov.go.jp/api/2"
SLEEP = 1.5
OUT = ROOT / "scripts" / "results" / "R2B_taishoku_egov"
KW = "退職"

# 令和6年分の年末（令和7年分との違いを見る）, 令和7年分の年末, 今日（令和8年分の途中）, 令和8年分の年末, 令和9年分の初日
ASOF_SHOTOKU = ["2024-12-31", "2025-12-31", "2026-11-09", "2026-12-31", "2027-01-01"]
# 令和8年度分の賦課期日, 今日, 令和9年度分の賦課期日
ASOF_CHIHO = ["2026-01-01", "2026-11-09", "2027-01-01"]

# (略称, 法令名, law_id, index 用の asof, fetch 用の asofs, 本則の条番号 Num, 改正附則を探す AmendLawNum の部分文字列)
JOBS = [
    ("shotoku", "所得税法", "340AC0000000033", "2026-11-09", ASOF_SHOTOKU,
     ["2", "22", "30", "31", "69", "87", "89", "120", "121", "122", "199", "200", "201", "202", "203", "226"],
     ["令和三年三月三一日法律第一一号", "令和七年三月三一日法律第一三号", "令和八年三月三一日法律第一二号"]),
    ("shotoku-rei", "所得税法施行令", "340CO0000000096", "2026-11-09", ASOF_SHOTOKU,
     ["11_2", "69", "69_2", "70", "71", "71_2", "72", "76", "77", "319_3", "319_3_2"],
     ["令和三年三月三一日政令第", "令和七年三月三一日政令第", "令和八年三月三一日政令第"]),
    ("shotoku-ki", "所得税法施行規則", "340M50000040011", "2026-11-09", ["2025-12-31", "2026-11-09", "2027-01-01"],
     ["77", "77_2", "77_3", "77_4"], ["令和七年", "令和八年"]),
    ("sochi", "租税特別措置法", "332AC0000000026", "2026-11-09", ["2025-12-31", "2026-11-09", "2027-01-01"],
     ["29_4", "29_5"], ["令和七年三月三一日法律第一三号", "令和八年三月三一日法律第一二号"]),
    ("fukko", "東日本大震災からの復興のための施策を実施するために必要な財源の確保に関する特別措置法", "423AC0000000117", "2026-11-09",
     ["2025-12-31", "2026-11-09", "2027-01-01"], ["8", "9", "10", "12", "13", "17", "18", "28", "31"], []),
    ("tsusoku", "国税通則法", "337AC0000000066", "2026-11-09", ["2026-11-09"], ["118", "119"], []),
    ("chiho", "地方税法", "325AC0000000226", "2026-11-09", ASOF_CHIHO,
     ["20_4_2", "23", "24", "32", "50_2", "50_3", "50_4", "50_5", "50_6", "50_7", "50_8", "50_9", "50_10",
      "292", "294", "295", "313", "314_2", "317_2", "317_3_2", "45_3_2",
      "328", "328_2", "328_3", "328_4", "328_5", "328_6", "328_7", "328_8", "328_9", "328_10", "328_11", "328_12",
      "328_13", "328_14", "328_15", "328_16"],
     ["令和七年三月三一日法律第七号", "令和八年三月三一日法律第二号"]),
    ("chiho-rei", "地方税法施行令", "325CO0000000245", "2026-11-09", ["2026-11-09", "2027-01-01"], ["7_2_2", "46_2_2", "48_17"], []),
    ("kokuho-rei", "国民健康保険法施行令", "333CO0000000362", "2026-11-09", ["2026-11-09"], ["29_7"], []),
]

# 別表（題名の先頭一致）。所得税法第201条第2項が引く別表第六（退職所得控除額の表）
APPDX = {"shotoku": ["別表第六"]}
# 原始附則（AmendLawNum のない附則）から抜き出す条。地方税法附則第3条の3（所得割の非課税。分離課税に係る所得割を除く）
ORIG_SUPPL = {"chiho": ["3_3"]}

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


# ---- テキスト化（scripts/IMPL_kyuyo_fetch.py の inline / render を写したもの） ----
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


def text_of(a):
    tl = []
    render(a, 0, tl)
    return "\n".join(tl)


def fetch_full(law_id, asof, dl, tries=4):
    """大きな法令で、HTTP 200 のまま HTML（「ご利用のページが見つかりません」）が返ることがあった（2026-11-09 実測）。
    JSON として読めないときは 15 秒あけて取り直す（最大 tries 回）。取り直した生データも別名で残す。"""
    q = {"response_format": "json", "asof": asof}
    url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode(q)
    last = None
    for i in range(tries):
        st, body = get(url)
        (dl / f"{law_id}_{asof}_try{i + 1}.json").write_bytes(body)
        if st == 200:
            try:
                return url, body, json.loads(body)
            except json.JSONDecodeError as e:
                last = f"try{i + 1}: status 200 but not JSON ({len(body)} bytes): {e}"
        else:
            last = f"try{i + 1}: status {st} {body[:200]!r}"
        print("retry", law_id, asof, last[:120], flush=True)
        time.sleep(15)
    raise RuntimeError(f"{url} -> {last}")


def split(root):
    main_arts, suppl = [], []

    def collect(n, path):
        tags = [p.get("tag") for p in path]
        if n.get("tag") == "Article" and "SupplProvision" not in tags:
            main_arts.append(n)
        if n.get("tag") == "SupplProvision":
            suppl.append(n)
    walk(root, collect)
    return main_arts, suppl


def appdx_tables(root):
    out = []

    def collect(n, path):
        if n.get("tag") == "AppdxTable":
            title = ""
            for c in n.get("children", []):
                if isinstance(c, dict) and c.get("tag") == "AppdxTableTitle":
                    title = inline(c)
            out.append((title, n))
    walk(root, collect)
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    mode = sys.argv[1] if len(sys.argv) > 1 else "fetch"
    only = sys.argv[2:]
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2B_taishoku_egov_{mode}"
    dl.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "mode": mode, "only": only, "download_dir": str(dl.relative_to(ROOT)), "fetches": [], "errors": []}
    for short, title, law_id, idx_asof, asofs, arts, amend_keys in JOBS:
        if only and short not in only:
            continue
        texts = {}  # asof -> {Num: text}
        for asof in ([idx_asof] if mode == "index" else asofs):
            try:
                url, body, d = fetch_full(law_id, asof, dl)
            except Exception as e:  # noqa: BLE001
                log["errors"].append({"short": short, "asof": asof, "error": repr(e)})
                print("ERR", short, asof, repr(e)[:200], flush=True)
                continue
            ri = d.get("revision_info") or {}
            li = d.get("law_info") or {}
            entry = {"short": short, "law_id": law_id, "law_title": ri.get("law_title"), "law_num": li.get("law_num"),
                     "asof": asof, "url": url,
                     "law_revision_id": ri.get("law_revision_id"), "amendment_law_num": ri.get("amendment_law_num"),
                     "amendment_enforcement_date": ri.get("amendment_enforcement_date"),
                     "current_revision_status": ri.get("current_revision_status"),
                     "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
            log["fetches"].append(entry)
            print("ok", short, asof, ri.get("law_revision_id"), flush=True)
            main_arts, suppl = split(d["law_full_text"])
            header = [f"# {short} {law_id} asof={asof}",
                      f"# 法令名={ri.get('law_title')} 法令番号={li.get('law_num')} law_revision_id={ri.get('law_revision_id')} "
                      f"改正法令={ri.get('amendment_law_num')} 施行日={ri.get('amendment_enforcement_date')} 状態={ri.get('current_revision_status')}",
                      f"# 取得URL={url}", f"# 取得日時={ts}", f"# 生データ SHA-256={entry['sha256']}", ""]
            if mode == "index":
                rows = []
                for a in main_arts:
                    t = text_of(a)
                    c = t.count(KW)
                    if c or KW in caption_of(a):
                        rows.append(f"{a['attr'].get('Num')}\t{caption_of(a)}\t{c}")
                amend = {}
                for s in suppl:
                    an = (s.get("attr") or {}).get("AmendLawNum") or "(原始附則)"
                    c = text_of(s).count(KW)
                    if c:
                        amend[an] = amend.get(an, 0) + c
                lines = header + ["## 本則の条（Num, 見出し, 「退職」の出現数）"] + rows
                lines += ["", "## 附則（AmendLawNum, 「退職」の出現数）"] + [f"{k}\t{v}" for k, v in sorted(amend.items())]
                (OUT / f"index_{short}.txt").write_text("\n".join(lines), encoding="utf-8")
                continue
            by_num = {a["attr"].get("Num"): a for a in main_arts}
            lines = list(header)
            texts[asof] = {}
            for num in arts:
                a = by_num.get(num)
                if a is None:
                    lines += [f"## Num={num}: 見つからない（この時点の本則にない）", ""]
                    texts[asof][num] = None
                    continue
                t = text_of(a)
                texts[asof][num] = t
                lines += [f"## Num={num}", t, ""]
            orig = [x for x in suppl if not (x.get("attr") or {}).get("AmendLawNum")]
            for num in ORIG_SUPPL.get(short, []):
                hit = None
                for x in orig:
                    for c in x.get("children", []):
                        if isinstance(c, dict) and c.get("tag") == "Article" and (c.get("attr") or {}).get("Num") == num:
                            hit = c
                tt = text_of(hit) if hit is not None else None
                texts[asof]["原始附則:" + num] = tt
                lines += [f"## 原始附則 Num={num}" + ("" if hit is not None else ": 見つからない"), tt or "", ""]
            for prefix in APPDX.get(short, []):
                found = [(t, n) for t, n in appdx_tables(d["law_full_text"]) if t.strip().startswith(prefix)]
                if not found:
                    lines += [f"## 別表「{prefix}」: 見つからない", ""]
                    texts[asof]["別表:" + prefix] = None
                for t, n in found:
                    tt = text_of(n)
                    texts[asof]["別表:" + prefix] = tt
                    lines += [f"## 別表「{prefix}」（題名={t}）", tt, ""]
            for key in amend_keys:
                hits = [s for s in suppl if key in ((s.get("attr") or {}).get("AmendLawNum") or "")]
                lines.append(f"## 改正附則 AmendLawNum に「{key}」を含むもの: {len(hits)} 件（「{KW}」を含む条・項だけを出す）")
                for s in hits:
                    an = (s.get("attr") or {}).get("AmendLawNum")
                    for c in s.get("children", []):
                        if isinstance(c, dict) and c.get("tag") in ("Article", "Paragraph"):
                            t = text_of(c)
                            if KW in t:
                                lines += [f"### {an} 附則 {c.get('tag')} Num={(c.get('attr') or {}).get('Num')}", t, ""]
                lines.append("")
            (OUT / f"{short}_{asof}.txt").write_text("\n".join(lines), encoding="utf-8")
        if mode != "index":
            ks = sorted(texts)
            for a, b in zip(ks, ks[1:]):
                md = [f"# {short}: {a} と {b} の条ごとの差分", ""]
                keys = list(arts) + ["別表:" + x for x in APPDX.get(short, [])] + ["原始附則:" + x for x in ORIG_SUPPL.get(short, [])]
                for num in keys:
                    ta, tb = texts[a].get(num), texts[b].get(num)
                    if ta == tb:
                        md.append(f"- Num={num}: 変化なし" + ("（両方に無い）" if ta is None else ""))
                    else:
                        md.append(f"- Num={num}: **変化あり**")
                md.append("")
                for num in keys:
                    ta, tb = texts[a].get(num), texts[b].get(num)
                    if ta != tb:
                        md += [f"## Num={num}", "```diff"]
                        md += list(difflib.unified_diff((ta or "").splitlines(), (tb or "").splitlines(), a, b, lineterm="", n=0))
                        md += ["```", ""]
                (OUT / f"diff_{short}_{a}_vs_{b}.md").write_text("\n".join(md), encoding="utf-8")
    suffix = mode + ("_" + "_".join(only) if only else "")
    (OUT / f"fetch_log_{suffix}.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", OUT)


if __name__ == "__main__":
    sys.exit(main())
