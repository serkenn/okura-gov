"""R2X_hoken-kifu: e-Gov 法令API v2 で、生命保険料控除・地震保険料控除・寄附金控除・小規模企業共済等掛金控除・
雑損控除と、住民税の対応する控除・寄附金税額控除（ふるさと納税の特例控除・申告特例）の条文を、時点（asof）ごとに取得する。

実行:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_hoken-kifu_egov.py
標準ライブラリのみ。リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。
scripts/R1_egov_articles.py と scripts/IMPL_kyuyo_fetch.py の取得・テキスト化の関数を写したもの（import しない）。

取得するもの（JOBS を参照）
- 所得税法：第72条、第75条〜第78条、第87条、第120条。附則（改正附則）のうち「長期損害保険料」を含むもの
- 所得税法施行令：第205条、第206条、第208条の2〜第217条、第262条
- 所得税法施行規則：第47条の2
- 租税特別措置法：第41条の15の5、第41条の18〜第41条の18の3。令和7年法律第13号・令和8年法律第12号の附則のうち
  「第四十一条の十五の五」を含むもの
- 地方税法：第34条、第37条の2、第314条の2、第314条の7、第317条の2。原始附則のうち見出しに「寄附金」を含む条。
  改正附則のうち「長期損害保険料」を含むもの
- 地方税法施行令：キーワード検索のみ

出力（scripts/results/R2X_hoken-kifu_egov/）
- fetch_log.json：取得URL、asof、law_revision_id、施行日、状態、生データの SHA-256 とバイト数
- articles_<略称>_<asof>.txt：抜き出した条（本則・附則）のテキスト
- article_hashes.json：条ごとの本文テキストの SHA-256（asof 間の同一・相違の判定用）
- diff_<略称>_<条>_<asofA>_<asofB>.txt：asof 間で本文が違う条の差分（unified diff）
- keyword_hits_<略称>_<asof>.json：キーワードの出現箇所（本則/附則、条、項、前後の文）
- revisions_<略称>.json：改正履歴（2025-01-01 以後）
ダウンロードした JSON は .work/downloads/<ts>_R2X_hoken-kifu_egov/ に置く（信頼できないデータ。中でコードを実行しない）。
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

R7_SHOTOKU = "令和七年三月三一日法律第一三号"
R8_SHOTOKU = "令和八年三月三一日法律第一二号"
R7_CHIHO = "令和七年三月三一日法律第七号"
R8_CHIHO = "令和八年三月三一日法律第二号"

KW_SHOTOKU = ["長期損害保険", "旧長期損害保険料", "新生命保険料", "介護医療保険料", "個人年金保険料", "特定寄附金",
              "小規模企業共済等掛金", "雑損控除", "四十一条の十五の五", "二十三歳未満"]
KW_CHIHO = ["長期損害保険", "寄附金税額控除", "特例控除", "申告特例", "地方団体の数", "五以下", "生命保険料控除",
            "地震保険料控除", "二十三歳未満", "四十一条の十五の五", "特例控除対象寄附金", "第三十七条の二第二項"]

# (略称, law_id, [asof...], [本則の条番号 Num], 附則の取り出し規則, [キーワード])
#  附則の取り出し規則：("amend", [AmendLawNum...], 含む文字列 or None) / ("orig_caption", 見出しに含む文字列) / ("any_text", 本文に含む文字列)
JOBS = [
    ("shotoku", "340AC0000000033", ["2024-12-31", "2025-12-31", "2026-12-31", "2027-01-01"],
     ["72", "75", "76", "77", "78", "87", "120"],
     [("any_text", "長期損害保険料")], KW_SHOTOKU),
    ("shotoku-rei", "340CO0000000096", ["2025-12-31", "2026-12-31", "2027-01-01"],
     ["205", "206", "208_2", "208_3", "208_4", "208_5", "208_6", "208_7", "208_8", "209", "210", "210_2", "211", "212",
      "213", "214", "215", "216", "217", "262"],
     [("any_text", "長期損害保険")], KW_SHOTOKU),
    ("shotoku-ki", "340M50000040011", ["2025-12-31", "2026-12-31", "2027-01-01"],
     ["47_2"], [], KW_SHOTOKU),
    ("sochi", "332AC0000000026", ["2025-12-31", "2026-11-09", "2026-12-31", "2027-01-01"],
     ["41_15_5", "41_18", "41_18_2", "41_18_3"],
     [("amend", [R7_SHOTOKU, R8_SHOTOKU], "四十一条の十五の五")], KW_SHOTOKU),
    ("chiho", "325AC0000000226", ["2025-12-31", "2026-11-09", "2027-01-01"],
     ["34", "37_2", "314_2", "314_7", "317_2"],
     [("orig_caption", "寄附金"), ("any_text", "長期損害保険料")], KW_CHIHO),
    ("chiho-rei", "325CO0000000245", ["2026-11-09"], [], [], KW_CHIHO),
]
REVISIONS = [("shotoku", "340AC0000000033"), ("shotoku-rei", "340CO0000000096"), ("sochi", "332AC0000000026"),
             ("chiho", "325AC0000000226")]

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


# ---- テキスト化（scripts/R1_egov_articles.py の inline / render を写したもの） ----
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


def text_of(node):
    lines = []
    render(node, 0, lines)
    return lines


def locate(path, node):
    loc = {"part": "MainProvision", "amend_law_num": None, "article": None, "caption": None, "paragraph": None}
    for p in list(path) + [node]:
        t = p.get("tag")
        a = p.get("attr") or {}
        if t == "SupplProvision":
            loc["part"] = "SupplProvision"
            loc["amend_law_num"] = a.get("AmendLawNum", "(原始附則)")
        elif t == "Article":
            loc["article"] = a.get("Num")
            loc["caption"] = caption_of(p)
        elif t == "Paragraph":
            loc["paragraph"] = a.get("Num")
    return loc


def keyword_hits(root, keywords):
    hits = []

    def fn(n, path):
        if n.get("tag", "") == "Sentence":
            txt = inline(n)
            for kw in keywords:
                i = txt.find(kw)
                if i >= 0:
                    hits.append({"keyword": kw, **locate(path, n), "snippet": txt[max(0, i - 120): i + 200]})
    walk(root, fn)
    return hits


def fetch_full(law_id, asof, dl):
    q = {"response_format": "json", "asof": asof}
    url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode(q)
    st, body = get(url)
    (dl / f"{law_id}_{asof}.json").write_bytes(body)
    if st != 200:
        raise RuntimeError(f"{url} -> {st} {body[:200]!r}")
    return url, body, json.loads(body)


def main():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2X_hoken-kifu_egov"
    dl.mkdir(parents=True, exist_ok=False)
    out = ROOT / "scripts" / "results" / "R2X_hoken-kifu_egov"
    out.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "fetches": [], "revisions": []}
    hashes = {}   # short -> key -> asof -> sha256
    texts = {}    # short -> key -> asof -> [lines]
    for short, law_id, asofs, arts, suppl_rules, kws in JOBS:
        for asof in asofs:
            url, body, d = fetch_full(law_id, asof, dl)
            ri = d.get("revision_info") or {}
            entry = {"short": short, "law_id": law_id, "asof": asof, "url": url, "law_title": ri.get("law_title"),
                     "law_revision_id": ri.get("law_revision_id"), "amendment_law_num": ri.get("amendment_law_num"),
                     "amendment_enforcement_date": ri.get("amendment_enforcement_date"),
                     "current_revision_status": ri.get("current_revision_status"),
                     "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
            log["fetches"].append(entry)
            print("ok", short, asof, ri.get("law_revision_id"), flush=True)
            root = d["law_full_text"]
            main_arts, suppl = [], []

            def collect(n, path):
                tags = [p.get("tag") for p in path]
                if n.get("tag") == "Article" and "SupplProvision" not in tags:
                    main_arts.append(n)
                if n.get("tag") == "SupplProvision":
                    suppl.append(n)
            walk(root, collect)
            header = [f"# {short} {law_id} asof={asof}",
                      f"# 法令名={ri.get('law_title')} law_revision_id={ri.get('law_revision_id')} 改正法令={ri.get('amendment_law_num')} "
                      f"施行日={ri.get('amendment_enforcement_date')} 状態={ri.get('current_revision_status')}",
                      f"# 取得URL={url}", f"# 取得日時={ts}", f"# 生データ SHA-256={entry['sha256']}", ""]
            lines = list(header)
            by_num = {a["attr"].get("Num"): a for a in main_arts}
            for num in arts:
                a = by_num.get(num)
                key = f"本則:{num}"
                if a is None:
                    lines += [f"## Num={num}: 見つからない（この時点の本則にない）", ""]
                    hashes.setdefault(short, {}).setdefault(key, {})[asof] = None
                    continue
                tl = text_of(a)
                lines.append(f"## Num={num}")
                lines += tl
                lines.append("")
                hashes.setdefault(short, {}).setdefault(key, {})[asof] = hashlib.sha256("\n".join(tl).encode("utf-8")).hexdigest()
                texts.setdefault(short, {}).setdefault(key, {})[asof] = tl
            for rule in suppl_rules:
                kind = rule[0]
                for s in suppl:
                    an = (s.get("attr") or {}).get("AmendLawNum", "(原始附則)")
                    if kind == "amend" and an not in rule[1]:
                        continue
                    if kind == "orig_caption" and an != "(原始附則)":
                        continue
                    for a in [x for x in s.get("children", []) if isinstance(x, dict) and x.get("tag") == "Article"]:
                        tl = text_of(a)
                        joined = "\n".join(tl)
                        if kind == "amend" and rule[2] and rule[2] not in joined:
                            continue
                        if kind == "orig_caption" and rule[1] not in caption_of(a):
                            continue
                        if kind == "any_text" and rule[1] not in joined:
                            continue
                        num = (a.get("attr") or {}).get("Num")
                        key = f"附則[{an}]:{num}"
                        lines.append(f"## {key}")
                        lines += tl
                        lines.append("")
                        hashes.setdefault(short, {}).setdefault(key, {})[asof] = hashlib.sha256(joined.encode("utf-8")).hexdigest()
                        texts.setdefault(short, {}).setdefault(key, {})[asof] = tl
            (out / f"articles_{short}_{asof}.txt").write_text("\n".join(lines), encoding="utf-8")
            kh = keyword_hits(root, kws)
            (out / f"keyword_hits_{short}_{asof}.json").write_text(
                json.dumps({"law_id": law_id, "asof": asof, "law_revision_id": ri.get("law_revision_id"), "keywords": kws,
                            "hits": kh}, ensure_ascii=False, indent=1), encoding="utf-8")
    # asof 間の差分
    diffs = []
    for short, keys in texts.items():
        for key, by_asof in keys.items():
            asofs = sorted(by_asof)
            for a0, a1 in zip(asofs, asofs[1:]):
                if by_asof[a0] != by_asof[a1]:
                    ud = list(difflib.unified_diff(by_asof[a0], by_asof[a1], fromfile=f"{short} {key} asof={a0}",
                                                   tofile=f"{short} {key} asof={a1}", lineterm="", n=0))
                    safe = key.replace(":", "_").replace("[", "_").replace("]", "_").replace("(", "").replace(")", "")
                    fn = f"diff_{short}_{safe}_{a0}_{a1}.txt"
                    (out / fn).write_text("\n".join(ud), encoding="utf-8")
                    diffs.append({"short": short, "key": key, "from": a0, "to": a1, "file": fn})
    (out / "article_hashes.json").write_text(json.dumps({"hashes": hashes, "diffs": diffs}, ensure_ascii=False, indent=1), encoding="utf-8")
    for short, law_id in REVISIONS:
        q = urllib.parse.urlencode({"response_format": "json", "amendment_date_from": "2025-01-01"})
        url = f"{API}/law_revisions/{law_id}?{q}"
        st, body = get(url)
        (dl / f"revisions_{law_id}.json").write_bytes(body)
        revs = []
        if st == 200:
            for rv in json.loads(body).get("revisions", []):
                revs.append({k: rv.get(k) for k in ("law_revision_id", "amendment_promulgate_date", "amendment_enforcement_date",
                                                   "amendment_scheduled_enforcement_date", "amendment_law_title", "amendment_law_num",
                                                   "current_revision_status")})
        (out / f"revisions_{short}.json").write_text(json.dumps({"url": url, "status": st, "revisions": revs}, ensure_ascii=False, indent=1), encoding="utf-8")
        log["revisions"].append({"short": short, "url": url, "status": st, "n": len(revs), "sha256": hashlib.sha256(body).hexdigest()})
    (out / "fetch_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", out, "diffs", len(diffs))


if __name__ == "__main__":
    sys.exit(main())
