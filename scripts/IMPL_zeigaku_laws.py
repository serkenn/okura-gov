"""IMPL zeigaku: 子供自身の所得税の計算と申告義務に関係する条文を e-Gov 法令API v2 で取得し、テキストにする。

実行（pyenv のシムは使わない）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_zeigaku_laws.py

- コードは scripts/R1_egov_articles.py と scripts/R4_fetch_laws.py から写した（import はしない）。標準ライブラリのみ。
- 取得した JSON は .work/downloads/<ts>_IMPL_zeigaku_laws/ に置く（信頼できないデータ。中でコードを実行しない）。
- 抜き出した条文・版の情報は scripts/results/IMPL_zeigaku_laws/ に書く。
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
TODAY = "2026-11-09"

FUKKO_TITLE = "東日本大震災からの復興のための施策を実施するために必要な財源の確保に関する特別措置法"

# (略称, law_id または None（法令名で検索）, 法令名, [asof...], [条番号（Num）], 見出しの正規表現, [別表の見出し], 改正履歴を取るか)
# asof の意味：2024-12-31＝令和6年分の年末、2025-12-31＝令和7年分の年末、2026-12-31＝令和8年分の年末（未施行の版）、
#              2027-01-01・2027-04-01＝令和9年以後に施行予定の改正があるかの確認
JOBS = [
    ("shotoku", "340AC0000000033", "所得税法", ["2024-12-31", "2025-12-31", "2026-12-31"],
     ["2", "21", "22", "28", "74", "82", "86", "87", "89", "104", "120", "121", "122", "138"], None, ["別表第五"], False),
    ("shotoku-rei", "340CO0000000096", "所得税法施行令", ["2025-12-31", "2026-12-31"],
     ["11_3", "208", "262", "262_2", "264", "267"], None, [], False),
    ("shotoku-ki", None, "所得税法施行規則", ["2025-12-31", "2026-12-31"],
     [], r"勤労学生|確定申告書|専修学校|各種学校", [], False),
    ("tsusoku", None, "国税通則法", ["2025-12-31", "2026-12-31"], ["118", "119", "120"], None, [], False),
    ("fukko", None, FUKKO_TITLE, ["2025-12-31", "2026-12-31", "2027-01-01"],
     [str(n) for n in range(1, 40)] + ["__INDEX__"], None, [], True),
    ("kokunen", "334AC0000000141", "国民年金法", [TODAY], ["90", "90_3"], None, [], False),
    ("kokunen-rei", "334CO0000000184", "国民年金法施行令", ["2025-04-01", TODAY, "2027-04-01"],
     ["6_6", "6_9", "6_10", "6_11"], None, [], True),
    ("gakko", None, "学校教育法", [TODAY], ["1", "124", "134"], None, [], False),
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


# ---- 以下の inline / render / walk は scripts/R1_egov_articles.py から写したもの ----
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
    if tag in ("ArticleCaption", "ArticleTitle", "SupplProvisionLabel", "ChapterTitle", "SectionTitle", "AppdxTableTitle"):
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
# ---- 写したものここまで ----


def find_law_id(title, dl, idx):
    """scripts/R4_fetch_laws.py の find_law_id を写したもの。法令名が完全一致するものだけを採る。"""
    q = urllib.parse.urlencode({"law_title": title, "response_format": "json", "asof": TODAY})
    st, body = get(f"{API}/laws?{q}", dl / f"{idx:02d}_laws_search.json")
    data = json.loads(body)
    for law in data.get("laws", []):
        rv = law.get("current_revision_info") or law.get("revision_info") or {}
        if rv.get("law_title") == title:
            return law["law_info"]["law_id"], law["law_info"].get("law_num")
    return None, None


def fetch_revisions(law_id, dl, short):
    """scripts/R4_fetch_laws.py の fetch_revisions を写したもの（期間だけ変えた）。"""
    q = urllib.parse.urlencode({"response_format": "json", "amendment_date_from": "2024-01-01"})
    st, body = get(f"{API}/law_revisions/{law_id}?{q}", dl / f"revisions_{short}.json")
    data = json.loads(body)
    out = []
    for rv in data.get("revisions", []):
        out.append({k: rv.get(k) for k in ("law_revision_id", "amendment_promulgate_date", "amendment_enforcement_date",
                                           "amendment_scheduled_enforcement_date", "amendment_law_title", "amendment_law_num",
                                           "current_revision_status")})
    return st, out


def main():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_IMPL_zeigaku_laws"
    dl.mkdir(parents=True, exist_ok=False)
    out = ROOT / "scripts" / "results" / "IMPL_zeigaku_laws"
    out.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "fetches": [], "errors": [], "revisions": {}}
    idx = 0
    for short, law_id, title, asofs, arts, cap_re, appdx, want_rev in JOBS:
        idx += 1
        try:
            law_num = None
            if law_id is None:
                law_id, law_num = find_law_id(title, dl, idx)
                if not law_id:
                    log["errors"].append({"short": short, "error": "law_id not found"})
                    print("ERR law_id", short, flush=True)
                    continue
            texts = {}
            for asof in asofs:
                q = {"response_format": "json", "asof": asof}
                url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode(q)
                st, body = get(url, dl / f"{idx:02d}_{short}_{asof}.json")
                if st != 200:
                    log["errors"].append({"short": short, "asof": asof, "status": st, "body": body[:300].decode("utf-8", "replace")})
                    print("ERR", short, asof, st, flush=True)
                    continue
                d = json.loads(body)
                ri = d.get("revision_info") or {}
                li = d.get("law_info") or {}
                rec = {"short": short, "title": title, "law_id": law_id, "law_num": law_num or li.get("law_num"), "asof": asof, "url": url,
                       "law_revision_id": ri.get("law_revision_id"), "amendment_law_num": ri.get("amendment_law_num"),
                       "amendment_law_title": ri.get("amendment_law_title"),
                       "amendment_enforcement_date": ri.get("amendment_enforcement_date"),
                       "current_revision_status": ri.get("current_revision_status"), "updated": ri.get("updated")}
                root = d["law_full_text"]
                main_arts, appdx_nodes = [], []

                def collect(n, path):
                    if n.get("tag") == "Article" and "SupplProvision" not in path:
                        main_arts.append(n)
                    if n.get("tag") == "AppdxTable":
                        appdx_nodes.append(n)
                walk(root, collect)
                header = [f"# {short} {title} {law_id} asof={asof}",
                          f"# law_revision_id={ri.get('law_revision_id')} 改正法令={ri.get('amendment_law_num')} 施行日={ri.get('amendment_enforcement_date')} 状態={ri.get('current_revision_status')}",
                          f"# 取得URL={url}", f"# 取得日時={ts}", ""]
                lines = []
                by_num = {a["attr"].get("Num"): a for a in main_arts}
                if "__INDEX__" in arts:
                    lines.append("## 本則の条番号と見出し")
                    lines += [f"{a['attr'].get('Num')}\t{article_caption(a)}" for a in main_arts]
                    lines.append("")
                sel = [n for n in arts if n != "__INDEX__" and n in by_num]
                missing = [n for n in arts if n != "__INDEX__" and n not in by_num]
                if cap_re:
                    sel += [a["attr"].get("Num") for a in main_arts if re.search(cap_re, article_caption(a)) and a["attr"].get("Num") not in sel]
                for num in sel:
                    lines.append(f"## Num={num}")
                    render(by_num[num], 0, lines)
                    lines.append("")
                for an in appdx:
                    hits = [t for t in appdx_nodes if any(isinstance(c, dict) and c.get("tag") == "AppdxTableTitle" and inline(c).startswith(an) for c in t.get("children", []))]
                    lines.append(f"## 別表 {an}: {len(hits)} 件（先頭60行だけ）")
                    for t in hits:
                        tl = []
                        render(t, 0, tl)
                        lines += tl[:60]
                        lines.append(f"... 全 {len(tl)} 行")
                    lines.append("")
                if missing and "__INDEX__" not in arts:
                    lines.append(f"## 見つからない条番号: {missing}")
                rec["extracted"] = sel
                rec["missing"] = missing
                log["fetches"].append(rec)
                texts[asof] = lines
                (out / f"{short}_{asof}.txt").write_text("\n".join(header + lines) + "\n", encoding="utf-8")
                print("ok", short, asof, ri.get("law_revision_id"), len(sel), flush=True)
            ks = sorted(texts)
            for a, b in zip(ks, ks[1:]):
                diff = "\n".join(difflib.unified_diff(texts[a], texts[b], f"{short}@{a}", f"{short}@{b}", lineterm=""))
                (out / f"{short}_diff_{a}_vs_{b}.diff").write_text(diff + "\n", encoding="utf-8")
            if want_rev:
                st, revs = fetch_revisions(law_id, dl, short)
                log["revisions"][short] = {"status": st, "items": revs}
        except Exception as e:  # noqa
            log["errors"].append({"short": short, "error": repr(e)})
            print("ERR", short, repr(e), flush=True)
    (out / "fetch_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", out)


if __name__ == "__main__":
    sys.exit(main())
