"""IMPL_denchoho: e-Gov 法令API v2 で、電子帳簿保存法・同施行規則・所得税法・所得税法施行規則のうち
記録の保存（電子取引データの保存要件、帳簿書類の保存期間）に関係する条を、複数の時点（asof）で取り出す。

実行（リポジトリのルートで）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_denchoho_laws.py

- 標準ライブラリのみ。User-Agent は okura-gov-research/0.1。リクエストの間は 1.5 秒あける。
- 取得した JSON は .work/downloads/<ts>_denchoho_laws/ に置く（信頼できないデータ。中でコードを実行しない）。
- 出力は scripts/results/IMPL_denchoho_laws/。
  - <略称>_<asof>.txt  … 取り出した条（本則）と、指定した改正法令の附則
  - diff_<略称>_<asof1>_vs_<asof2>.diff … 同じ条の時点間の差分
  - index_<略称>.txt … 本則の条番号と見出しの一覧（最後の asof）
  - grep_<略称>.txt … 本則のうち、指定した正規表現に当たる条の番号と該当文（条番号の確認用）
  - revisions_<略称>.json … /law_revisions の版の一覧（施行日つき）
  - fetch_log.json … 取得した URL、版（law_revision_id）、施行日、SHA-256
コードは scripts/R1_egov_articles.py と scripts/R4_fetch_laws.py から写して改変した（import はしていない）。
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

# 時点の意味
#  2021-12-31 / 2022-01-01: 令和3年度改正（令和3年財務省令第25号）の施行の前後
#  2023-12-31 / 2024-01-01: 令和5年度改正（令和5年財務省令第22号）の施行の前後（宥恕措置の終了と猶予措置の開始）
#  2025-12-31: 令和7年分の年末の版、2026-11-09: 今日の版、2026-12-31: 令和8年分の年末の版
#  2027-01-01: 令和7年法律第13号・令和7年財務省令第28号の未施行部分の施行日（e-Gov の /law_revisions で UnEnforced の版がある）
DENCHO_ASOF = ["2021-12-31", "2022-01-01", "2023-12-31", "2024-01-01", "2025-12-31", "2026-11-09", "2026-12-31", "2027-01-01"]
TAX_ASOF = ["2025-12-31", "2026-11-09", "2026-12-31"]

# 取り出す附則（被改正法令の本文に収録されている改正法令の附則。AmendLawNum の文字列で一致させる）
DENCHO_KI_SUPPL = ["令和三年三月三一日財務省令第二五号", "令和三年一二月二七日財務省令第八〇号",
                   "令和五年三月三一日財務省令第二二号", "令和七年三月三一日財務省令第二八号"]
# 「令和五年三月三一日法律第三号」は試しに入れたもので、電帳法の本文に収録された附則には無い（出力は 0 件。e-Gov の電帳法の版の一覧にも令和5年の法律による版は無い）
DENCHO_SUPPL = ["令和三年三月三一日法律第一一号", "令和五年三月三一日法律第三号", "令和七年三月三一日法律第一三号"]

# 本則から、条番号を確かめるために正規表現で探す（帳簿・書類の保存期間の規定）
GREP_SHOTOKU_KI = [r"七年間", r"五年間", r"保存しなければならない", r"帳簿を備え", r"雑所得を生ずべき業務"]
GREP_SHOTOKU = [r"帳簿", r"雑所得を生ずべき業務", r"保存しなければならない"]

# (略称, law_id, [asof...], [本則の条番号（Num 属性。枝番は "84_2" の形）], [附則の AmendLawNum], [grep の正規表現])
JOBS = [
    ("denchou", "410AC0000000025", DENCHO_ASOF, ["1", "2", "4", "7", "8"], DENCHO_SUPPL, []),
    ("denchou-ki", "410M50000040043", DENCHO_ASOF, ["1", "2", "4", "5"], DENCHO_KI_SUPPL, []),
    ("shotoku", "340AC0000000033", TAX_ASOF, ["120", "143", "148", "231_2", "232"], [], GREP_SHOTOKU),
    ("shotoku-ki", "340M50000040011", TAX_ASOF, ["__GREP__"], [], GREP_SHOTOKU_KI),
]
REVISIONS_OF = ["denchou", "denchou-ki"]

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


def fetch_full(law_id, asof, dl):
    q = {"response_format": "json", "asof": asof}
    url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode(q)
    st, body = get(url)
    p = dl / f"{law_id}_{asof}.json"
    p.write_bytes(body)
    if st != 200:
        raise RuntimeError(f"{url} -> {st} {body[:200]!r}")
    return url, json.loads(body), hashlib.sha256(body).hexdigest()


def fetch_revisions(law_id, dl, short):
    q = urllib.parse.urlencode({"response_format": "json"})
    url = f"{API}/law_revisions/{law_id}?{q}"
    st, body = get(url)
    (dl / f"revisions_{law_id}.json").write_bytes(body)
    data = json.loads(body)
    out = []
    for rv in data.get("revisions", []):
        out.append({k: rv.get(k) for k in ("law_revision_id", "amendment_promulgate_date", "amendment_enforcement_date",
                                           "amendment_scheduled_enforcement_date", "amendment_law_title", "amendment_law_num",
                                           "current_revision_status", "updated")})
    return url, st, out


def main():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_denchoho_laws"
    dl.mkdir(parents=True, exist_ok=False)
    out = ROOT / "scripts" / "results" / "IMPL_denchoho_laws"
    out.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "fetches": [], "revisions": {}, "errors": []}
    for short, law_id, asofs, arts, amend_nums, greps in JOBS:
        per_asof_articles = {}
        for asof in asofs:
            try:
                url, d, sha = fetch_full(law_id, asof, dl)
            except Exception as e:  # noqa
                log["errors"].append({"short": short, "asof": asof, "error": repr(e)})
                print(f"ERR {short} {asof} {e!r}", flush=True)
                continue
            ri = d.get("revision_info") or {}
            li = d.get("law_info") or {}
            log["fetches"].append({"short": short, "law_id": law_id, "law_num": li.get("law_num"), "law_title": ri.get("law_title"),
                                   "asof": asof, "url": url, "sha256": sha,
                                   "law_revision_id": ri.get("law_revision_id"),
                                   "amendment_law_num": ri.get("amendment_law_num"),
                                   "amendment_promulgate_date": ri.get("amendment_promulgate_date"),
                                   "amendment_enforcement_date": ri.get("amendment_enforcement_date"),
                                   "current_revision_status": ri.get("current_revision_status"),
                                   "updated": ri.get("updated")})
            root = d["law_full_text"]
            main_arts, suppl = [], []

            def collect(n, path):
                if n.get("tag") == "Article" and "SupplProvision" not in path:
                    main_arts.append(n)
                if n.get("tag") == "SupplProvision":
                    suppl.append(n)
            walk(root, collect)
            header = [f"# {short} {law_id} {li.get('law_num')} {ri.get('law_title')} asof={asof}",
                      f"# law_revision_id={ri.get('law_revision_id')} 改正法令={ri.get('amendment_law_num')} 施行日={ri.get('amendment_enforcement_date')} 状態={ri.get('current_revision_status')}",
                      f"# 取得URL={url}", f"# 取得日時={ts}", f"# SHA-256(JSON)={sha}", ""]
            # grep：本則の条ごとにテキスト化し、正規表現に当たる条を記録
            grep_hits = {}
            if greps:
                for a in main_arts:
                    lines_a = []
                    render(a, 0, lines_a)
                    t = "\n".join(lines_a)
                    for pat in greps:
                        for ln in lines_a:
                            if re.search(pat, ln):
                                grep_hits.setdefault(a["attr"].get("Num"), []).append((pat, ln.strip()[:300]))
                if asof == asofs[-1] or asof == "2026-11-09":
                    g = header + [f"# grep patterns={greps}", ""]
                    for num, hs in grep_hits.items():
                        a = next(x for x in main_arts if x["attr"].get("Num") == num)
                        g.append(f"## Num={num} {article_caption(a)}")
                        for pat, ln in hs:
                            g.append(f"  [{pat}] {ln}")
                        g.append("")
                    (out / f"grep_{short}_{asof}.txt").write_text("\n".join(g), encoding="utf-8")
            if asof == asofs[-1]:
                idx = header + [f"{a['attr'].get('Num')}\t{article_caption(a)}" for a in main_arts]
                idx += ["", "# 附則（AmendLawNum）"] + sorted({s.get('attr', {}).get('AmendLawNum', '(原始附則)') for s in suppl})
                (out / f"index_{short}.txt").write_text("\n".join(idx), encoding="utf-8")
            lines = list(header)
            by_num = {a["attr"].get("Num"): a for a in main_arts}
            sel = list(arts)
            if sel == ["__GREP__"]:
                # 保存期間（七年間・五年間）か「保存しなければならない」に当たる条だけ
                sel = [n for n, hs in grep_hits.items() if any(p in (r"七年間", r"五年間", r"保存しなければならない", r"雑所得を生ずべき業務") for p, _ in hs)]
            arts_text = {}
            for num in sel:
                a = by_num.get(num)
                if a is None:
                    lines += [f"## Num={num}: 見つからない（この時点の本則にない）", ""]
                    arts_text[num] = "(なし)"
                    continue
                al = []
                render(a, 0, al)
                arts_text[num] = "\n".join(al)
                lines.append(f"## Num={num}")
                lines += al
                lines.append("")
            per_asof_articles[asof] = arts_text
            for an in amend_nums:
                hits = [s for s in suppl if s.get("attr", {}).get("AmendLawNum") == an]
                lines.append(f"## 附則 AmendLawNum={an}: {len(hits)} 件")
                for s in hits:
                    render(s, 0, lines)
                lines.append("")
            (out / f"{short}_{asof}.txt").write_text("\n".join(lines), encoding="utf-8")
            print(f"ok {short} {asof} {ri.get('law_revision_id')} arts={len(sel)}", flush=True)
        # 時点間の差分（隣り合う asof）
        ks = list(per_asof_articles)
        for x, y in zip(ks, ks[1:]):
            a, b = per_asof_articles[x], per_asof_articles[y]
            ta = "\n\n".join(f"## Num={n}\n{a.get(n, '(取り出していない)')}" for n in sorted(set(a) | set(b)))
            tb = "\n\n".join(f"## Num={n}\n{b.get(n, '(取り出していない)')}" for n in sorted(set(a) | set(b)))
            diff = "\n".join(difflib.unified_diff(ta.splitlines(), tb.splitlines(), f"{short}@{x}", f"{short}@{y}", lineterm=""))
            (out / f"diff_{short}_{x}_vs_{y}.diff").write_text(diff + "\n", encoding="utf-8")
        if short in REVISIONS_OF:
            try:
                url, st, revs = fetch_revisions(law_id, dl, short)
                log["revisions"][short] = {"url": url, "status": st, "count": len(revs)}
                (out / f"revisions_{short}.json").write_text(json.dumps(revs, ensure_ascii=False, indent=1), encoding="utf-8")
            except Exception as e:  # noqa
                log["errors"].append({"short": short, "revisions_error": repr(e)})
    (out / "fetch_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", out)


if __name__ == "__main__":
    sys.exit(main())
