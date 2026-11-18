"""R2X_yoshiki: e-Gov 法令API v2 で、確定申告書・確定損失申告書・青色申告書の記載事項と添付書類（様式の欄の対応表の法令上の根拠）を版ごとに取り出す。

実行（Windows）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_yoshiki_egov.py

- scripts/IMPL_output_egov.py（もとは scripts/R1_egov_articles.py の形）を写して作った（import はしない）。標準ライブラリのみ。
- 本文（JSON）は .work/downloads/<YYYYMMDD-HHMMSS>_R2X_yoshiki_egov/ に置く（信頼できないデータ。中で何も実行しない）。
- 出力は scripts/results/R2X_yoshiki_egov/：
  - <略称>_asof<日付>.txt  指定した条（項・号の構造つき）。先頭に law_revision_id・改正法令・施行日・取得URL
  - <略称>_diff_<日付1>_vs_<日付2>.diff  版の間の差分（指定した条だけ）
  - grep_<略称>_asof<日付>.txt  本則の全文から正規表現に当たった条番号と行（様式・別表・明細書など）
  - suppl_<略称>_asof<日付>.txt  指定した改正法令（AmendLawNum）の附則のうち、正規表現に当たる条の全文（施行日・適用関係を読むため）
  - fetch_log.json  取得の記録
- リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。
"""
import difflib
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

# 版：令和7年分の年末（2025-12-31）、令和8年分の年末（2026-12-31）、令和9年1月1日施行分を含む版（2027-01-01）
ASOFS = ["2025-12-31", "2026-12-31", "2027-01-01"]
# (略称, law_id, [asof...], [条番号（Article@Num）], grep の正規表現)
JOBS = [
    ("shotoku", "340AC0000000033", ASOFS, ["120", "123", "149"], r"確定損失申告書|貸借対照表|損益計算書|明細書"),
    ("shotoku-ki", "340M50000040011", ASOFS, ["47", "47_2", "47_3", "48", "65"],
     r"様式|書式|別表第|確定損失申告書|法第百二十三条|法第百四十九条|貸借対照表|損益計算書"),
]
# 附則を取り出す改正法令（AmendLawNum の値）と、附則の条を選ぶ正規表現（条の本文に当たれば条ごと書き出す）
SUPPL = {
    "shotoku": (["令和八年三月三一日法律第一二号"], r"第百二十条|第百二十三条|第百四十九条|施行期日"),
}
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


def main():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2X_yoshiki_egov"
    dl.mkdir(parents=True, exist_ok=False)
    out = ROOT / "scripts" / "results" / "R2X_yoshiki_egov"
    out.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "fetches": []}
    for short, law_id, asofs, arts, grep in JOBS:
        texts = {}
        for asof in asofs:
            url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode({"response_format": "json", "asof": asof})
            st, body = get(url)
            (dl / f"{law_id}_{asof}.json").write_bytes(body)
            if st != 200:
                log["fetches"].append({"short": short, "asof": asof, "url": url, "status": st})
                continue
            d = json.loads(body)
            ri = d.get("revision_info") or {}
            li = d.get("law_info") or {}
            log["fetches"].append({"short": short, "law_id": law_id, "asof": asof, "url": url, "status": st,
                                   "law_title": ri.get("law_title"), "law_num": li.get("law_num"),
                                   "law_revision_id": ri.get("law_revision_id"),
                                   "amendment_law_num": ri.get("amendment_law_num"),
                                   "amendment_enforcement_date": ri.get("amendment_enforcement_date"),
                                   "current_revision_status": ri.get("current_revision_status")})
            root = d["law_full_text"]
            main_arts = []
            walk(root, lambda n, p: main_arts.append(n) if n.get("tag") == "Article" and "SupplProvision" not in p else None)
            header = [f"# {short} {ri.get('law_title')} {law_id} asof={asof}",
                      f"# law_revision_id={ri.get('law_revision_id')} 改正法令={ri.get('amendment_law_num')} 施行日={ri.get('amendment_enforcement_date')} 状態={ri.get('current_revision_status')}",
                      f"# 取得URL={url}", f"# 取得日時={ts}", ""]
            by_num = {a["attr"].get("Num"): a for a in main_arts}
            lines = list(header)
            for num in arts:
                a = by_num.get(num)
                if a is None:
                    lines += [f"## Num={num}: 見つからない", ""]
                    continue
                lines.append(f"## Num={num}")
                render(a, 0, lines)
                lines.append("")
            (out / f"{short}_asof{asof}.txt").write_text("\n".join(lines), encoding="utf-8")
            texts[asof] = lines[len(header):]
            g = list(header)
            rx = re.compile(grep)
            for a in main_arts:
                al = []
                render(a, 0, al)
                hits = [l.strip() for l in al if rx.search(l)]
                if hits:
                    g.append(f"## Num={a['attr'].get('Num')}")
                    g += [h[:400] for h in hits]
            (out / f"grep_{short}_asof{asof}.txt").write_text("\n".join(g), encoding="utf-8")
            nums, srx = SUPPL.get(short, ([], None))
            if srx:
                suppl = []
                walk(root, lambda n, p: suppl.append(n) if n.get("tag") == "SupplProvision" else None)
                sl = list(header)
                rx2 = re.compile(srx)
                for sp in suppl:
                    an = sp.get("attr", {}).get("AmendLawNum", "(原始附則)")
                    if nums and an not in nums:
                        continue
                    sl.append(f"## 附則 AmendLawNum={an}")
                    units = []
                    walk(sp, lambda n, p: units.append(n) if n.get("tag") == "Article" or (n.get("tag") == "Paragraph" and "Article" not in p) else None)
                    for u in units:
                        ul = []
                        render(u, 0, ul)
                        if rx2.search("\n".join(ul)):
                            sl += ul
                            sl.append("")
                (out / f"suppl_{short}_asof{asof}.txt").write_text("\n".join(sl), encoding="utf-8")
        ks = list(texts)
        for a, b in zip(ks, ks[1:]):
            diff = difflib.unified_diff(texts[a], texts[b], fromfile=f"{short}@{a}", tofile=f"{short}@{b}", lineterm="")
            (out / f"{short}_diff_{a}_vs_{b}.diff").write_text("\n".join(diff), encoding="utf-8")
    (out / "fetch_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", out)


if __name__ == "__main__":
    main()
