"""R1: e-Gov 法令API v2 の法令本文取得API（/law_data）で、指定した時点（asof）の条文を取り出してテキストにする。

実行:
  python -I scripts/R1_egov_articles.py            # JOBS をすべて実行
  python -I scripts/R1_egov_articles.py index      # 対象法令の「条番号と見出し」の索引だけ作る
標準ライブラリのみ。リクエストの間は 1.5 秒あける。

- 本文（JSON）は .work/downloads/<ts>_egov_articles/ に置く（信頼できないデータ。中でコードを実行しない）。
- 取り出した条文は scripts/results/R1_egov_articles/<略称>_<asof>.txt に書く。
- 改正法令の附則（SupplProvision の AmendLawNum が一致するもの）も取り出せる。
  e-Gov では一部改正法そのものの本文は取得できない（/law_data/<改正法令ID> は 404。R1_egov_revisions.py で実測）ので、
  被改正法令の本文に収録されている改正法令の附則から、施行期日・適用関係を読む。
"""
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

# (略称, law_id, [asof...], [本則の条番号（Num 属性。枝番は "84_2" のように書く）], [附則を取り出す改正法令番号])
SHOTOKU_ARTS = ["2", "22", "23", "27", "28", "34", "35", "57", "69", "72", "73", "79", "82", "83", "83_2",
                "84", "84_2", "85", "86", "143", "148", "190", "194", "232"]
JOBS = [
    ("shotoku", "340AC0000000033", ["2024-12-31", "2025-12-31", "2026-11-09", "2026-12-01", "2027-01-01"], SHOTOKU_ARTS,
     ["令和七年三月三一日法律第一三号", "令和八年三月三一日法律第一二号"]),
    ("shotoku-rei", "340CO0000000096", ["2025-12-31", "2026-11-09"], ["207", "217_2", "219"], []),
    ("sochi", "332AC0000000026", ["2024-12-31", "2025-12-31", "2026-11-09", "2026-12-01", "2027-01-01"], ["29_4", "41_15_5", "41_16_2", "41_17"],
     ["令和七年三月三一日法律第一三号", "令和八年三月三一日法律第一二号"]),
    ("chiho", "325AC0000000226", ["2025-12-31", "2026-11-09", "2027-01-01"], ["23", "24_5", "34", "292", "295", "314_2"],
     ["令和七年三月三一日法律第七号", "令和八年三月三一日法律第二号"]),
    ("kenpo", "211AC0000000070", ["2025-12-31", "2026-11-09"], ["3"], []),
    ("kenpo-ki", "215M10000008036", ["2026-11-09"], ["37_2", "38", "50"], []),
    ("kokunen", "334AC0000000141", ["2026-11-09"], ["7", "8", "90_3"], []),
    ("kokunen-rei", "334CO0000000184", ["2026-11-09"], ["4"], []),
    ("nenrei", "135AC1000000050", ["2026-11-09"], ["__ALL__"], []),
    ("minpo", "129AC0000000089", ["2026-11-09"], ["138", "139", "140", "141", "143"], []),
    ("denchou", "410AC0000000025", ["2026-11-09"], ["1", "2", "4", "5", "7", "8"], []),
    ("denchou-ki", "410M50000040043", ["2026-11-09"], ["1", "2", "3", "4", "5"], []),
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


def inline(n):
    if isinstance(n, str):
        return n
    if n.get("tag") in ("Rt",):  # ルビの読みは落とす
        return ""
    sep = "　" if n.get("tag") in ("ItemSentence", "ParagraphSentence") or n.get("tag", "").endswith("Sentence") else ""
    parts = [inline(c) for c in n.get("children", [])]
    if n.get("tag", "").endswith("Sentence") and any(isinstance(c, dict) and c.get("tag") == "Column" for c in n.get("children", [])):
        return "　".join(p for p in parts if p)
    return "".join(parts) if not sep else "".join(parts)


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


def article_caption(a):
    for c in a.get("children", []):
        if isinstance(c, dict) and c.get("tag") == "ArticleCaption":
            return inline(c)
    return ""


def fetch_full(law_id, asof, dl):
    q = {"response_format": "json", "asof": asof}
    url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode(q)
    st, body = get(url)
    (dl / f"{law_id}_{asof}.json").write_bytes(body)
    if st != 200:
        raise RuntimeError(f"{url} -> {st} {body[:200]!r}")
    return url, json.loads(body)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_egov_articles"
    dl.mkdir(parents=True, exist_ok=False)
    out = ROOT / "scripts" / "results" / "R1_egov_articles"
    out.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "mode": mode, "fetches": []}
    for short, law_id, asofs, arts, amend_nums in JOBS:
        for asof in (asofs[-1:] if mode == "index" else asofs):
            url, d = fetch_full(law_id, asof, dl)
            ri = d.get("revision_info") or {}
            log["fetches"].append({"short": short, "law_id": law_id, "asof": asof, "url": url,
                                   "law_revision_id": ri.get("law_revision_id"),
                                   "amendment_law_num": ri.get("amendment_law_num"),
                                   "amendment_enforcement_date": ri.get("amendment_enforcement_date"),
                                   "current_revision_status": ri.get("current_revision_status")})
            root = d["law_full_text"]
            main_arts, suppl = [], []

            def collect(n, path):
                if n.get("tag") == "Article" and "SupplProvision" not in path:
                    main_arts.append(n)
                if n.get("tag") == "SupplProvision":
                    suppl.append(n)
            walk(root, collect)
            header = [f"# {short} {law_id} asof={asof}",
                      f"# law_revision_id={ri.get('law_revision_id')} 改正法令={ri.get('amendment_law_num')} 施行日={ri.get('amendment_enforcement_date')} 状態={ri.get('current_revision_status')}",
                      f"# 取得URL={url}", f"# 取得日時={ts}", ""]
            if mode == "index":
                idx = header + [f"{a['attr'].get('Num')}\t{article_caption(a)}" for a in main_arts]
                idx += ["", "# 附則（AmendLawNum）"] + sorted({s.get('attr', {}).get('AmendLawNum', '(原始附則)') for s in suppl})
                (out / f"index_{short}.txt").write_text("\n".join(idx), encoding="utf-8")
                continue
            lines = list(header)
            if arts == ["__ALL__"]:
                lines_all = []
                render(root, 0, lines_all)
                lines += lines_all
            else:
                by_num = {a["attr"].get("Num"): a for a in main_arts}
                for num in arts:
                    a = by_num.get(num)
                    if a is None:
                        lines += [f"## 第{num}条: 見つからない（この時点の本則にない）", ""]
                        continue
                    lines.append(f"## Num={num}")
                    render(a, 0, lines)
                    lines.append("")
            for an in amend_nums:
                hits = [s for s in suppl if s.get("attr", {}).get("AmendLawNum") == an]
                lines.append(f"## 附則 AmendLawNum={an}: {len(hits)} 件")
                for s in hits:
                    render(s, 0, lines)
                lines.append("")
            (out / f"{short}_{asof}.txt").write_text("\n".join(lines), encoding="utf-8")
    (out / f"fetch_log_{mode}.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", out)


if __name__ == "__main__":
    main()
