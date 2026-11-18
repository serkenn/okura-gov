"""R4: e-Gov 法令API v2 で法令本文を取得し、人・親族・生計・世帯などの定義に関係する条を抜き出す。

実行: python -I scripts/R4_fetch_laws.py
- ダウンロードした JSON は .work/downloads/<ts>_R4_laws/ に置く（信頼できないデータ。実行はしない）。
- 抜き出した条文・版の情報・キーワードの出現箇所は scripts/results/R4_fetch_laws/ に書く。
- 標準ライブラリのみ。リクエストの間は 1.5 秒あける。

取得するのは指定した日（asof）の時点で最新の版。基本は実行日 TODAY の版。所得税法・所得税法施行令は、
令和7年分の年末時点（2025-12-31）と、未施行の改正の施行予定日（2026-12-01、2027-01-01）の版も取得し、
抜き出した条を比べる（EXTRA_ASOF）。
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
TODAY = "2026-11-09"
WAIT = 1.5

# 法令名（完全一致）: (抜き出す条番号のリスト, 見出しで追加で拾う正規表現)
# 条番号は XML の Article@Num の形式（第83条の2 → "83_2"）。
TARGETS = {
    "所得税法": (["2", "5", "56", "57", "73", "74", "79", "81", "83", "83_2", "84", "84_2", "85", "86", "190", "194", "195"], None),
    "所得税法施行令": ([], r"扶養親族|配偶者|生計|親族|専従者|医療費"),
    "所得税法施行規則": (["1_3", "1_4"], r"寡婦|ひとり親|事実上婚姻"),
    "民法": (["4", "22", "143", "725", "726", "727", "728", "729", "730", "739", "752", "877"], None),
    "明治三十五年法律第五十号（年齢計算ニ関スル法律）": ([], r"."),
    "健康保険法": (["1", "3"], r"被扶養者"),
    "健康保険法施行規則": (["37_2", "37_3"], r"被扶養者"),
    "国民年金法": (["5", "7", "8", "9", "12"], r"生計維持"),
    "国民年金法施行令": (["4"], r"生計維持|被扶養配偶者"),
    "住民基本台帳法": (["1", "5", "6", "7", "22", "23", "25", "26"], r"世帯"),
    "住民基本台帳法施行令": ([], r"世帯"),
    "地方税法": (["23", "24", "34", "39", "292", "294", "314_2", "318", "703_4"], None),
    "国民健康保険法": (["5", "6", "9", "76"], None),
    "児童手当法": (["3", "4"], None),
}
# 比較のために追加で取得する版。2025-12-31 は令和7年分の年末時点、2026-12-01 と 2027-01-01 は未施行の改正（令和8年法律第12号など）の施行予定日
EXTRA_ASOF = {"所得税法": ["2025-12-31", "2026-12-01", "2027-01-01"], "所得税法施行令": ["2025-12-31", "2026-12-01", "2027-01-01"]}
REVISIONS_OF = ["所得税法", "所得税法施行令"]
SEARCH_KEYWORDS = ["家計", "「家計」とは"]
AMOUNT_STRINGS = ["百三十万円", "百五十万円", "百八十万円"]
KEYWORDS = ["家計", "生計を一に", "生計を同じく", "生計を維持", "同一の世帯", "世帯主", "世帯", "親族", "同居"]


def get(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        body = r.read()
        status = r.status
    dest.write_bytes(body)
    time.sleep(WAIT)
    return status, body


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


def render(node, depth=0, out=None):
    """条文の構造を、行ごとのテキストにする（項・号・イロハの字下げつき）。"""
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
            parts = []
            for c in s.get("children", []):
                if isinstance(c, dict) and c.get("tag") == "Column":
                    parts.append(text_of(c))
                else:
                    parts.append(text_of(c))
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


def iter_tag(node, tag):
    if isinstance(node, dict):
        if node.get("tag") == tag:
            yield node
        for c in node.get("children", []):
            yield from iter_tag(c, tag)


def main_articles(full):
    mp = next(iter_tag(full, "MainProvision"), None)
    return list(iter_tag(mp, "Article")) if mp else []


def find_law_id(title, dl, idx):
    q = urllib.parse.urlencode({"law_title": title, "response_format": "json", "asof": TODAY})
    st, body = get(f"{API}/laws?{q}", dl / f"{idx:02d}_laws_{title}.json")
    data = json.loads(body)
    for law in data.get("laws", []):
        rv = law.get("current_revision_info") or law.get("revision_info") or {}
        if rv.get("law_title") == title:
            return law["law_info"]["law_id"], law["law_info"].get("law_num")
    return None, None


def fetch_text(law_id, asof, dl, name):
    q = urllib.parse.urlencode({"response_format": "json", "asof": asof, "omit_amendment_suppl_provision": "true"})
    st, body = get(f"{API}/law_data/{law_id}?{q}", dl / name)
    data = json.loads(body)
    return data


def extract(data, nums, cap_re):
    arts = main_articles(data["law_full_text"])
    sel = []
    for a in arts:
        num = a.get("attr", {}).get("Num", "")
        cap = child(a, "ArticleCaption")
        captxt = text_of(cap) if cap else ""
        if num in nums or (cap_re and re.search(cap_re, captxt)):
            sel.append((num, "\n".join(render(a))))
    if not arts:  # 条のない古い法令（本則が項だけ）は本則全体を出す
        mp = next(iter_tag(data["law_full_text"], "MainProvision"), None)
        if mp:
            sel.append(("MainProvision", "\n".join(render(mp))))
    return arts, sel


# 定義規定らしい書き方（「〇〇」とは / 「〇〇」には）を本則全体から探す
DEF_PATTERNS = [r"「世帯」とは", r"「世帯主」とは", r"「家計」とは", r"「生計を一にする」", r"「親族」とは", r"「配偶者」(?:とは|には)",
                r"「被扶養者」とは", r"「被保険者」とは", r"「住所」とは"]


def definition_checks(data):
    mp = next(iter_tag(data["law_full_text"], "MainProvision"), None)
    res = {}
    if not mp:
        return res
    units = main_articles(data["law_full_text"]) or [mp]
    for pat in DEF_PATTERNS:
        for a in units:
            t = text_of(a)
            for m in re.finditer(pat, t):
                s = max(0, m.start() - 40)
                res.setdefault(pat, []).append({"article": a.get("attr", {}).get("Num"), "snippet": t[s:m.end() + 80]})
    return res


def fetch_revisions(law_id, dl, title):
    q = urllib.parse.urlencode({"response_format": "json", "amendment_date_from": "2025-01-01"})
    st, body = get(f"{API}/law_revisions/{law_id}?{q}", dl / f"revisions_{title}.json")
    data = json.loads(body)
    out = []
    for rv in data.get("revisions", []):
        out.append({k: rv.get(k) for k in ("law_revision_id", "amendment_promulgate_date", "amendment_enforcement_date",
                                           "amendment_scheduled_enforcement_date", "amendment_law_title", "amendment_law_num",
                                           "current_revision_status")})
    return out


def main():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R4_laws"
    dl.mkdir(parents=True, exist_ok=False)
    out = ROOT / "scripts" / "results" / "R4_fetch_laws"
    out.mkdir(parents=True, exist_ok=True)
    (out / "articles").mkdir(exist_ok=True)
    log = {"fetched_at": ts, "asof": TODAY, "download_dir": str(dl.relative_to(ROOT)), "laws": [], "keyword_hits": {}, "errors": []}
    idx = 0
    for title, (nums, cap_re) in TARGETS.items():
        idx += 1
        try:
            law_id, law_num = find_law_id(title, dl, idx)
            if not law_id:
                log["errors"].append({"law": title, "error": "law_id not found"})
                continue
            versions = [TODAY] + EXTRA_ASOF.get(title, [])
            texts = {}
            for asof in versions:
                data = fetch_text(law_id, asof, dl, f"{idx:02d}_law_data_{title}_{asof}.json")
                rv = data.get("revision_info", {})
                arts, sel = extract(data, nums, cap_re)
                body = "\n\n".join(t for _, t in sel)
                texts[asof] = body
                fn = out / "articles" / f"{title}_asof{asof}.txt"
                header = (f"# {title}（{law_num}） law_id={law_id}\n# asof={asof} law_revision_id={rv.get('law_revision_id')}\n"
                          f"# amendment_enforcement_date={rv.get('amendment_enforcement_date')} amendment_law_title={rv.get('amendment_law_title')}\n"
                          f"# updated={rv.get('updated')} current_revision_status={rv.get('current_revision_status')}\n"
                          f"# source={API}/law_data/{law_id}?asof={asof}\n\n")
                fn.write_text(header + body + "\n", encoding="utf-8")
                entry = {"law": title, "law_id": law_id, "law_num": law_num, "asof": asof,
                         "law_revision_id": rv.get("law_revision_id"),
                         "amendment_enforcement_date": rv.get("amendment_enforcement_date"),
                         "amendment_law_title": rv.get("amendment_law_title"),
                         "amendment_law_num": rv.get("amendment_law_num"),
                         "updated": rv.get("updated"), "current_revision_status": rv.get("current_revision_status"),
                         "articles_in_main_provision": len(arts), "extracted": [n for n, _ in sel],
                         "output": str(fn.relative_to(ROOT))}
                log["laws"].append(entry)
                if asof == TODAY:
                    # 本則の全条について、キーワードが出てくる条番号を記録
                    hits = {}
                    for a in arts:
                        t = text_of(a)
                        for k in KEYWORDS:
                            c = t.count(k)
                            if c:
                                hits.setdefault(k, []).append({"article": a.get("attr", {}).get("Num"), "count": c})
                    log["keyword_hits"][title] = hits
                    log.setdefault("definition_checks", {})[title] = definition_checks(data)
                    # 被扶養者の収入基準（130万円・150万円とされるもの）が本文に書かれているか（附則も含む全文で数える）
                    full = text_of(data["law_full_text"])
                    log.setdefault("amount_string_counts", {})[title] = {s: full.count(s) for s in AMOUNT_STRINGS}
                print(f"ok {title} {asof} {rv.get('law_revision_id')} extracted={len(sel)}", flush=True)
            for other in EXTRA_ASOF.get(title, []):
                # 古い版は「古い→今日」、未施行の版は「今日→将来」の向きで差分をとる
                x, y = (other, TODAY) if other < TODAY else (TODAY, other)
                diff = "\n".join(difflib.unified_diff(texts[x].splitlines(), texts[y].splitlines(), f"{title}@{x}", f"{title}@{y}", lineterm=""))
                (out / "articles" / f"{title}_diff_{x}_vs_{y}.diff").write_text(diff + "\n", encoding="utf-8")
            if title in REVISIONS_OF:
                log.setdefault("revisions_since_2025", {})[title] = fetch_revisions(law_id, dl, title)
        except Exception as e:  # noqa
            log["errors"].append({"law": title, "error": repr(e)})
            print(f"ERR {title} {e!r}", flush=True)

    # 「家計」が法令本文に出てくるか：キーワード検索API
    md = [f"# キーワード検索の結果（e-Gov 法令API v2 /keyword, asof={TODAY}, 取得 {ts}）", ""]
    for n, kw in enumerate(SEARCH_KEYWORDS):
        try:
            q = urllib.parse.urlencode({"keyword": kw, "response_format": "json", "asof": TODAY, "limit": 1000, "sentences_limit": 3})
            st, body = get(f"{API}/keyword?{q}", dl / f"keyword_{n}.json")
            data = json.loads(body)
            items = []
            for it in data.get("items", []):
                li, rv = it.get("law_info", {}), it.get("revision_info", {})
                items.append({"law_id": li.get("law_id"), "law_num": li.get("law_num"), "law_title": rv.get("law_title"),
                              "law_type": li.get("law_type"),
                              "sentences": [{"position": s.get("position"), "text": s.get("text")} for s in it.get("sentences", [])]})
            res = {"keyword": kw, "asof": TODAY, "total_count": data.get("total_count"), "sentence_count": data.get("sentence_count"),
                   "next_offset": data.get("next_offset"), "items": items}
            (out / f"keyword_{n}.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
            md += [f"## keyword = {kw}", "",
                   f"- total_count={res['total_count']} sentence_count={res['sentence_count']} next_offset={res['next_offset']} 法令数(items)={len(items)}",
                   f"- 生データの要約: scripts/results/R4_fetch_laws/keyword_{n}.json", "",
                   "| 法令種別 | 法令名 | 法令番号 | 最初の該当箇所（position） | 該当文の冒頭 |", "|---|---|---|---|---|"]
            for it in items:
                s = it["sentences"][0] if it["sentences"] else {}
                txt = re.sub(r"<[^>]+>", "", (s.get("text") or ""))
                k = txt.find(kw)
                frag = txt[max(0, k - 40): k + 60] if k >= 0 else txt[:100]
                md.append(f"| {it['law_type']} | {it['law_title']} | {it['law_num']} | {s.get('position')} | {frag.replace('|', '｜')} |")
            md.append("")
            print(f"ok keyword {n} total_count={data.get('total_count')}", flush=True)
        except urllib.error.HTTPError as e:
            # このAPIは該当0件のとき 404 と {"code":"404001","message":"取得結果が０件です。"} を返す
            body = e.read().decode("utf-8", "replace")
            time.sleep(WAIT)
            log.setdefault("keyword_http_errors", []).append({"keyword": kw, "status": e.code, "body": body})
            md += [f"## keyword = {kw}", "", f"- HTTP {e.code}: {body}", ""]
            print(f"http {e.code} keyword {n}", flush=True)
        except Exception as e:  # noqa
            log["errors"].append({"keyword": kw, "error": repr(e)})
            print(f"ERR keyword {n} {e!r}", flush=True)
    (out / "keyword_summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    (out / "fetch_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
