"""IMPL_kenpo: e-Gov 法令API v2 で、健康保険の被扶養者認定の実務に関係する条文を取得し、
(1) 指定した条を時点（asof）ごとに抜き出し、(2) 版の間の差分をとり、(3) 本文（本則・附則）から語句を走査する。

実行: python -I -X utf8 scripts/IMPL_kenpo_egov.py
- 標準ライブラリのみ。リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。
- ダウンロードした JSON は .work/downloads/<ts>_IMPL_kenpo_egov/ に置く（信頼できないデータ。その中でコードを実行しない）。
- 結果は scripts/results/IMPL_kenpo_egov/ に書く：
    articles/<略称>_<asof>.txt   抜き出した条（版の情報つき）
    diff_<略称>_<asof1>_vs_<asof2>.diff
    scan_<略称>_<asof>.md / .json  語句の走査結果（条番号・項・文の一部）
    fetch_log.json                取得記録（URL、law_revision_id、施行日、SHA-256）
scripts/R1_egov_articles.py と scripts/R4_fetch_laws.py のコードを写して作った（import はしていない）。
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
WAIT = 1.5
OUT = ROOT / "scripts" / "results" / "IMPL_kenpo_egov"

# 2025-10-01：19歳以上23歳未満150万円の適用日（通知。法令ではない）の時点の版
# 2025-12-31：令和7年分の年末
# 2026-04-01：労働契約による判定の適用日（通知）の時点の版
# 2026-11-09：今日
ASOFS = ["2025-10-01", "2025-12-31", "2026-04-01", "2026-11-09"]

# (略称, 法令名, law_id, [抜き出す条番号（Article@Num）], [走査する正規表現])
SCAN_DEP = [r"被扶養者[^。]{0,80}(被保険者である|被保険者となった|被保険者となる|二以上|同時に|重複|他の保険者)",
            r"(被保険者である|二以上の)[^。]{0,80}被扶養者",
            r"同一の世帯", r"世帯に属"]
JOBS = [
    ("kenpo", "健康保険法", "211AC0000000070", ["3", "43_2", "110"], SCAN_DEP),
    ("kenpo-rei", "健康保険法施行令", "215IO0000000243", [], SCAN_DEP),
    ("kenpo-ki", "健康保険法施行規則", "215M10000008036", ["37_2", "37_3", "38", "50"], SCAN_DEP),
    ("jumin", "住民基本台帳法", "342AC0000000081", ["6", "7", "25"], [r"「世帯」とは", r"世帯を", r"世帯主"]),
    ("kokuho", "国民健康保険法", "333AC0000000192", ["5", "6"], [r"被扶養者"]),
]
# 版の比較をする法令（全ての ASOFS で取得する）。それ以外は今日の版だけ。
ALL_ASOFS_FOR = {"kenpo", "kenpo-ki"}


def get(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            body, st = r.read(), r.status
    except urllib.error.HTTPError as e:
        body, st = e.read(), e.code
    dest.write_bytes(body)
    time.sleep(WAIT)
    return st, body


def text_of(node):
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return ""
    if node.get("tag") == "Rt":  # ルビの読みは捨てる
        return ""
    return "".join(text_of(c) for c in node.get("children", []))


def child(node, tag):
    for c in node.get("children", []):
        if isinstance(c, dict) and c.get("tag") == tag:
            return c
    return None


def iter_tag(node, tag):
    if isinstance(node, dict):
        if node.get("tag") == tag:
            yield node
        for c in node.get("children", []):
            yield from iter_tag(c, tag)


def render(node, depth=0, out=None):
    """条文の構造を、行ごとのテキストにする（項・号・イロハの字下げつき）。R4_fetch_laws.py から写した。"""
    if out is None:
        out = []
    if not isinstance(node, dict):
        return out
    tag = node.get("tag", "")
    ind = "  " * depth
    if tag == "Article":
        cap = child(node, "ArticleCaption")
        tit = child(node, "ArticleTitle")
        out.append(f"{ind}{text_of(cap) if cap else ''}")
        out.append(f"{ind}{text_of(tit) if tit else ''}")
        for c in node.get("children", []):
            if isinstance(c, dict) and c.get("tag") == "Paragraph":
                render(c, depth, out)
        return out
    if tag == "Paragraph":
        num = child(node, "ParagraphNum")
        sen = child(node, "ParagraphSentence")
        out.append(f"{ind}[項{node.get('attr', {}).get('Num', '')}] {text_of(num) if num else ''} {text_of(sen) if sen else ''}".rstrip())
        for c in node.get("children", []):
            if isinstance(c, dict) and c.get("tag") not in ("ParagraphNum", "ParagraphSentence", "ParagraphCaption"):
                render(c, depth + 1, out)
        return out
    m = re.fullmatch(r"(Item|Subitem\d+)", tag)
    if m:
        t = child(node, f"{tag}Title")
        s = child(node, f"{tag}Sentence")
        sent = ""
        if s:
            parts = [text_of(c) for c in s.get("children", []) if isinstance(c, (dict, str))]
            sent = "　".join(p for p in parts if p)
        out.append(f"{ind}{text_of(t) if t else ''} {sent}".rstrip())
        for c in node.get("children", []):
            if isinstance(c, dict) and c.get("tag") not in (f"{tag}Title", f"{tag}Sentence"):
                render(c, depth + 1, out)
        return out
    if tag == "TableStruct":
        for row in iter_tag(node, "TableRow"):
            cells = [text_of(c) for c in row.get("children", []) if isinstance(c, dict)]
            out.append(f"{ind}| " + " | ".join(cells) + " |")
        return out
    for c in node.get("children", []):
        render(c, depth, out)
    return out


def walk_units(full):
    """本則の条と、附則（SupplProvision）の条・項を、(場所の名前, ノード) の組で返す。"""
    units = []
    mp = next(iter_tag(full, "MainProvision"), None)
    if mp:
        arts = list(iter_tag(mp, "Article"))
        units += [(f"本則 第{a.get('attr', {}).get('Num')}条", a) for a in arts] or [("本則", mp)]
    for sp in iter_tag(full, "SupplProvision"):
        label = sp.get("attr", {}).get("AmendLawNum") or "原始附則"
        arts = list(iter_tag(sp, "Article"))
        if arts:
            units += [(f"附則({label}) 第{a.get('attr', {}).get('Num')}条", a) for a in arts]
        else:
            units.append((f"附則({label})", sp))
    return units


def scan(full, patterns):
    hits = []
    for where, node in walk_units(full):
        # 項ごとに走査する（どの項かを残すため）
        paras = list(iter_tag(node, "Paragraph")) or [node]
        for p in paras:
            t = text_of(p)
            pnum = p.get("attr", {}).get("Num", "") if p.get("tag") == "Paragraph" else ""
            for pat in patterns:
                for mt in re.finditer(pat, t):
                    s = max(0, mt.start() - 60)
                    hits.append({"where": where, "paragraph": pnum, "pattern": pat,
                                 "snippet": t[s:mt.end() + 60].replace("\n", " ")})
    return hits


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_IMPL_kenpo_egov"
    dl.mkdir(parents=True, exist_ok=False)
    (OUT / "articles").mkdir(parents=True, exist_ok=True)
    log = {"fetched_at_local": ts, "download_dir": str(dl.relative_to(ROOT)), "fetches": [], "errors": []}
    for short, title, law_id, arts, pats in JOBS:
        asofs = ASOFS if short in ALL_ASOFS_FOR else [ASOFS[-1]]
        texts = {}
        for asof in asofs:
            q = urllib.parse.urlencode({"response_format": "json", "asof": asof})
            url = f"{API}/law_data/{law_id}?{q}"
            dest = dl / f"{short}_{asof}.json"
            st, body = get(url, dest)
            rec = {"short": short, "law": title, "law_id": law_id, "asof": asof, "url": url, "status": st,
                   "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
            if st != 200:
                rec["error"] = body[:300].decode("utf-8", "replace")
                log["fetches"].append(rec)
                print("ERR", short, asof, st, flush=True)
                continue
            d = json.loads(body)
            ri = d.get("revision_info") or {}
            rec.update({k: ri.get(k) for k in ("law_revision_id", "amendment_law_num", "amendment_law_title",
                                               "amendment_enforcement_date", "current_revision_status", "updated")})
            log["fetches"].append(rec)
            full = d["law_full_text"]
            header = [f"# {title} {law_id} asof={asof}",
                      f"# law_revision_id={ri.get('law_revision_id')} 改正法令={ri.get('amendment_law_num')} 施行日={ri.get('amendment_enforcement_date')} 状態={ri.get('current_revision_status')}",
                      f"# 取得URL={url}", f"# 取得日時={ts}", ""]
            mp = next(iter_tag(full, "MainProvision"), None)
            by_num = {a.get("attr", {}).get("Num"): a for a in (iter_tag(mp, "Article") if mp else [])}
            lines = []
            for num in arts:
                a = by_num.get(num)
                if a is None:
                    lines += [f"## Num={num}: 見つからない（この時点の本則にない）", ""]
                    continue
                lines.append(f"## Num={num}")
                lines += render(a)
                lines.append("")
            texts[asof] = "\n".join(lines)
            if arts:
                (OUT / "articles" / f"{short}_{asof}.txt").write_text("\n".join(header) + texts[asof] + "\n", encoding="utf-8")
            hits = scan(full, pats)
            (OUT / f"scan_{short}_{asof}.json").write_text(json.dumps({"law": title, "asof": asof, "law_revision_id": ri.get("law_revision_id"),
                                                                       "patterns": pats, "hits": hits}, ensure_ascii=False, indent=1), encoding="utf-8")
            md = header + [f"走査パターン: {pats}", f"該当: {len(hits)} 件", "", "| 場所 | 項 | パターン | 前後の文 |", "|---|---|---|---|"]
            md += [f"| {h['where']} | {h['paragraph']} | `{h['pattern']}` | {h['snippet'].replace('|', '｜')} |" for h in hits]
            (OUT / f"scan_{short}_{asof}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
            print("ok", short, asof, ri.get("law_revision_id"), "hits", len(hits), flush=True)
        ks = sorted(texts)
        for x, y in zip(ks, ks[1:]):
            if not arts:
                continue
            diff = "\n".join(difflib.unified_diff(texts[x].splitlines(), texts[y].splitlines(), f"{short}@{x}", f"{short}@{y}", lineterm=""))
            (OUT / f"diff_{short}_{x}_vs_{y}.diff").write_text((diff or "(差分なし)") + "\n", encoding="utf-8")
    (OUT / "fetch_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", OUT)


if __name__ == "__main__":
    sys.exit(main())
