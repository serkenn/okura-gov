"""R2X_spouse: e-Gov 法令API v2 で、配偶者控除・配偶者特別控除（所得税・住民税）、年の途中の結婚・死別の特例、
健康保険の被扶養者（配偶者）、国民年金の第3号被保険者に関する条文を、年分・年度に対応する版ごとに取り出す。

実行（Windows）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_spouse_egov.py [略称 ...]
  （略称を指定するとその法令だけを取得する。取得記録は fetch_log_<略称>.json。2026-11-09 は全体を1回、chiho-rei を後から1回実行した）

- scripts/R1_egov_articles.py・scripts/IMPL_misc_egov.py のコードを写して作った（import はしない）。標準ライブラリのみ。
- 本文（JSON）は .work/downloads/<YYYYMMDD-HHMMSS>_R2X_spouse_egov/ に置く（信頼できないデータ。中で何も実行しない）。
- 出力は scripts/results/R2X_spouse_egov/：
  - <略称>_asof<日付>.txt          指定した条（項・号の構造つき）。先頭に law_revision_id・改正法令・施行日・状態・取得URL
  - <略称>_diff_<日付1>_vs_<日付2>.diff  版の間の差分（指定した条だけ）
  - <略称>_suppl_<改正法令番号>.txt  改正法令の附則（施行日・適用年分の経過措置を読むため）
  - <略称>_scan.json              本則の全文から正規表現で拾った行（国民年金法施行規則の第3号関係など）
  - fetch_log.json                取得の記録（URL・版・状態）
- リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。
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

# 所得税：令和6年分（比較用）・令和7年分・令和8年分の年末の版。2026-12-31 は未施行の改正（令和8年法律第12号、2026-12-01 施行）を含む版。
ASOF_SHOTOKU = ["2024-12-31", "2025-12-31", "2026-12-31"]
# 住民税：令和7年度分（比較用。賦課期日 2025-01-01 の後の年末）・令和8年度分（2026-01-01）・令和9年度分（2027-01-01）
ASOF_CHIHO = ["2025-12-31", "2026-01-01", "2027-01-01"]
TODAY = "2026-11-09"

# (略称, 法令名, law_id, [asof...], [条番号], 第2条第1項の号, 見出しの正規表現, [附則を取り出す改正法令番号], 附則を取り出す asof)
JOBS = [
    ("shotoku", "所得税法", "340AC0000000033", ASOF_SHOTOKU,
     ["83", "83_2", "85", "195_2"], ["30", "33", "33_2", "33_3", "33_4"], None,
     ["令和七年三月三一日法律第一三号", "令和八年三月三一日法律第一二号"], "2026-12-31"),
    ("shotoku-rei", "所得税法施行令", "340CO0000000096", ["2025-12-31", "2026-12-31"],
     ["218", "218_2", "220"], [], None, [], None),
    ("chiho", "地方税法", "325AC0000000226", ASOF_CHIHO,
     ["34", "37", "292", "314_2", "314_6"], [], None,
     ["令和七年三月三一日法律第七号", "令和八年三月三一日法律第二号"], "2027-01-01"),
    ("kokunen", "国民年金法", "334AC0000000141", [TODAY],
     ["5", "7", "8", "9", "12"], [], None, [], None),
    ("kokunen-rei", "国民年金法施行令", "334CO0000000184", [TODAY],
     ["4"], [], None, [], None),
    ("kokunen-ki", "国民年金法施行規則", "335M50000100012", [TODAY],
     [], [], r"第三号被保険者|被扶養配偶者|国内居住|日本国内に住所", [], None),
    ("kenpo", "健康保険法", "211AC0000000070", [TODAY],
     ["3"], [], None, [], None),
    # 住民税の配偶者の所属（第46条の3・第46条の4）と、前年の中途の死亡・再婚の特例（地方税法第314条の2第10項の委任先。見出しで探す）
    ("chiho-rei", "地方税法施行令", "325CO0000000245", ["2026-01-01", "2027-01-01"],
     ["46_3", "46_4"], [], r"再婚", [], None),
]

# 本則の全文から拾う行（行＝項・号の1単位）
SCAN = {
    "kokunen7_3": r"第七条第一項第三号",
    "kokunen7_1_3": r"第七条第一項第一号及び第三号",  # 第1号・第3号の適用除外（施行規則第1条の2 の見出し）
    "hifuyo_haigusha": r"被扶養配偶者",
    "dai3": r"第三号被保険者",
    "jijitsukon": r"事実上婚姻関係と同様の事情",
    "saikon": r"再婚|第三百十四条の二第十項",
}
SCAN_TARGETS = {"kokunen", "kokunen-rei", "kokunen-ki", "chiho-rei"}

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


def article_caption(a):
    for c in a.get("children", []):
        if isinstance(c, dict) and c.get("tag") == "ArticleCaption":
            return inline(c)
    return ""


def fetch_full(law_id, asof, dl, with_suppl):
    q = {"response_format": "json", "asof": asof}
    if not with_suppl:
        q["omit_amendment_suppl_provision"] = "true"
    url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode(q)
    st, body = get(url)
    (dl / f"{law_id}_{asof}{'_suppl' if with_suppl else ''}.json").write_bytes(body)
    if st != 200:
        raise RuntimeError(f"{url} -> {st} {body[:200]!r}")
    return url, json.loads(body)


def art2_items(a, wanted):
    lines = []
    for p in a.get("children", []):
        if not (isinstance(p, dict) and p.get("tag") == "Paragraph" and p.get("attr", {}).get("Num") == "1"):
            continue
        for it in p.get("children", []):
            if isinstance(it, dict) and it.get("tag") == "Item" and it.get("attr", {}).get("Num") in wanted:
                lines.append(f"### 第2条第1項 Item Num={it['attr']['Num']}")
                render(it, 0, lines)
                lines.append("")
    return lines


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    only = set(sys.argv[1:])  # 略称を指定したらその法令だけ取得する（例: chiho-rei）
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2X_spouse_egov"
    dl.mkdir(parents=True, exist_ok=False)
    out = ROOT / "scripts" / "results" / "R2X_spouse_egov"
    out.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "fetches": [], "errors": []}
    for short, title, law_id, asofs, arts, items2, cap_re, suppl_laws, suppl_asof in JOBS:
        if only and short not in only:
            continue
        texts = {}
        scan = {}
        for asof in asofs:
            with_suppl = bool(suppl_laws) and asof == suppl_asof
            try:
                url, d = fetch_full(law_id, asof, dl, with_suppl)
            except Exception as e:  # noqa: BLE001
                log["errors"].append({"law": title, "asof": asof, "error": repr(e)})
                print("ERR", short, asof, e, flush=True)
                continue
            ri = d.get("revision_info") or {}
            log["fetches"].append({"short": short, "law": title, "law_id": law_id, "asof": asof, "url": url,
                                   "with_amendment_suppl": with_suppl,
                                   "law_revision_id": ri.get("law_revision_id"),
                                   "amendment_law_title": ri.get("amendment_law_title"),
                                   "amendment_law_num": ri.get("amendment_law_num"),
                                   "amendment_enforcement_date": ri.get("amendment_enforcement_date"),
                                   "current_revision_status": ri.get("current_revision_status"),
                                   "updated": ri.get("updated")})
            root = d["law_full_text"]
            marts, suppl = [], []

            def collect(n, path):
                if n.get("tag") == "Article" and "SupplProvision" not in path:
                    marts.append(n)
                if n.get("tag") == "SupplProvision":
                    suppl.append(n)
            walk(root, collect)
            by_num = {a["attr"].get("Num"): a for a in marts}
            header = [f"# {short} {title} {law_id} asof={asof}",
                      f"# law_revision_id={ri.get('law_revision_id')} 改正法令={ri.get('amendment_law_num')} "
                      f"施行日={ri.get('amendment_enforcement_date')} 状態={ri.get('current_revision_status')}",
                      f"# 取得URL={url}", f"# 取得日時={ts}", ""]
            lines = list(header)
            if items2 and "2" in by_num:
                lines.append("## Num=2（第1項の指定した号だけ）")
                lines += art2_items(by_num["2"], items2)
            picked = list(arts)
            if cap_re:
                for a in marts:
                    n = a["attr"].get("Num")
                    if re.search(cap_re, article_caption(a)) and n not in picked:
                        picked.append(n)
            for num in picked:
                a = by_num.get(num)
                if a is None:
                    lines += [f"## Num={num}: 見つからない（この版の本則にない）", ""]
                    continue
                lines.append(f"## Num={num}")
                render(a, 0, lines)
                lines.append("")
            texts[asof] = "\n".join(lines[len(header):])
            (out / f"{short}_asof{asof}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
            if with_suppl:
                for an in suppl_laws:
                    hits = [s for s in suppl if s.get("attr", {}).get("AmendLawNum") == an]
                    sl = list(header) + [f"## 附則 AmendLawNum={an}: {len(hits)} 件", ""]
                    for s in hits:
                        render(s, 0, sl)
                    (out / f"{short}_suppl_{an}.txt").write_text("\n".join(sl) + "\n", encoding="utf-8")
            if short in SCAN_TARGETS:
                res = {}
                for a in marts:
                    alines = []
                    render(a, 0, alines)
                    num = a["attr"].get("Num")
                    cap = article_caption(a)
                    for ln in alines:
                        for key, pat in SCAN.items():
                            if re.search(pat, ln):
                                res.setdefault(key, []).append({"article": num, "caption": cap, "line": ln.strip()[:800]})
                scan[asof] = {"law_revision_id": ri.get("law_revision_id"),
                              "counts": {k: len(v) for k, v in res.items()}, "hits": res}
            print(f"ok {short} {asof} {ri.get('law_revision_id')} suppl={with_suppl}", flush=True)
        ks = list(texts)
        for i in range(len(ks) - 1):
            x, y = ks[i], ks[i + 1]
            diff = difflib.unified_diff(texts[x].splitlines(), texts[y].splitlines(),
                                        fromfile=f"{short}@{x}", tofile=f"{short}@{y}", lineterm="", n=0)
            (out / f"{short}_diff_{x}_vs_{y}.diff").write_text("\n".join(diff) + "\n", encoding="utf-8")
        if scan:
            (out / f"{short}_scan.json").write_text(json.dumps(scan, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / (f"fetch_log_{'_'.join(sorted(only))}.json" if only else "fetch_log.json")).write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", out)


if __name__ == "__main__":
    main()
