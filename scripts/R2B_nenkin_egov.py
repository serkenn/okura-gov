r"""R2B_nenkin: e-Gov 法令API v2 で、公的年金等の雑所得（老齢・障害・遺族年金）に関係する条文を時点（asof）ごとに取得する。

実行:
  C:\Users\user\.pyenv\pyenv-win\versions\3.11.9\python.exe -I -X utf8 scripts/R2B_nenkin_egov.py
標準ライブラリのみ。リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。個人の情報は送らない。

取得するもの（条の選び方：明示した条番号 ＋ 見出しの正規表現 ＋ 本文の正規表現。原始附則の条も同じ規則で選ぶ）
- 所得税法：第2条、第9条、第22条、第31条、第35条、第36条、第120条、第121条、第203条の2〜第203条の7 と、見出しに「公的年金」を含む条
- 所得税法施行令：見出しに「公的年金」を含む条、本文に「第三十五条第三項」を含む条
- 租税特別措置法・同施行令：見出しに「公的年金」を含む条、本文に「公的年金等控除」を含む条
- 地方税法・同施行令：見出し・本文に「公的年金等控除」「公的年金等に係る所得」を含む条（本則・原始附則）、第313条、第317条の2
- 国民年金法 第25条、厚生年金保険法 第41条、各共済組合法の「公課」を含む条
- 所得税法・措置法の令和7年法律第13号・令和8年法律第12号、地方税法の令和7年法律第7号・令和8年法律第2号の附則のうち「公的年金」を含む条

ダウンロードした JSON は .work/downloads/<ts>_R2B_nenkin_egov/ に置く（信頼できないデータ。中でコードを実行しない）。
結果は scripts/results/R2B_nenkin_egov/ に書く：
  fetch_log.json                       取得URL、asof、law_revision_id、改正法令、施行日、状態、生データの SHA-256
  articles/<略称>_<asof>.txt           抜き出した条（版の情報つき）
  scan/<略称>_<asof>.json              語句の出現箇所（本則/附則、条、項、前後の文）
  diff/<略称>_<asof1>_vs_<asof2>.diff  抜き出した条の版の間の差分
scripts/R1_egov_articles.py と scripts/IMPL_kyuyo_fetch.py のコードを写して作った（import はしていない）。
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
OUT = ROOT / "scripts" / "results" / "R2B_nenkin_egov"
TODAY = "2026-11-09"

R7_SHOTOKU = "令和七年三月三一日法律第一三号"
R8_SHOTOKU = "令和八年三月三一日法律第一二号"
R7_CHIHO = "令和七年三月三一日法律第七号"
R8_CHIHO = "令和八年三月三一日法律第二号"

KW = ["公的年金等", "公的年金等控除", "六十五歳", "四百万円", "二十万円", "租税その他の公課", "公課",
      "第三十五条第三項", "第三十五条第四項", "百十万円", "六十万円", "千万円", "二千万円"]

# 時点の選び方
#   2025-12-31：令和7年分の年末（令和7年分の所得税に適用される版）
#   2026-12-31：令和8年分の年末（令和8年分。令和8年12月1日施行の改正を含む）
#   2027-01-01：令和9年分の初日（所法35⑤など令和9年分からの改正。境目の確認用）
#   2026-01-01：令和8年度分の住民税の賦課期日（令和7年分の所得）
#   2027-01-01：令和9年度分の住民税の賦課期日（令和8年分の所得。2026-11-09 時点で成立している改正までを反映した版）
SHOTOKU_ASOFS = ["2025-12-31", "2026-12-31", "2027-01-01"]
CHIHO_ASOFS = ["2026-01-01", "2027-01-01"]

# (略称, 法令名, law_id, [asof...], [明示する本則の条 Num], 見出しの正規表現, 本文の正規表現, [附則を見る改正法令番号], omit_amendment)
JOBS = [
    ("shotoku", "所得税法", "340AC0000000033", SHOTOKU_ASOFS,
     ["2", "9", "22", "31", "35", "36", "120", "121", "203_2", "203_3", "203_4", "203_5", "203_6", "203_7"],
     r"公的年金", None, [R7_SHOTOKU, R8_SHOTOKU], False),
    ("shotoku-rei", "所得税法施行令", "340CO0000000096", ["2025-12-31", "2026-12-31"],
     [], r"公的年金", r"法第三十五条第三項|第三十五条第三項第三号", [], True),
    ("sochi", "租税特別措置法", "332AC0000000026", SHOTOKU_ASOFS,
     [], r"公的年金", r"公的年金等控除", [R7_SHOTOKU, R8_SHOTOKU], False),
    ("sochi-rei", "租税特別措置法施行令", "332CO0000000043", ["2026-12-31"],
     [], r"公的年金", r"公的年金等控除", [], True),
    ("chiho", "地方税法", "325AC0000000226", CHIHO_ASOFS,
     ["313", "317_2"], r"公的年金等控除", r"公的年金等控除|六十五歳以上", [R7_CHIHO, R8_CHIHO], False),
    ("chiho-rei", "地方税法施行令", "325CO0000000245", CHIHO_ASOFS,
     [], r"公的年金等控除", r"公的年金等控除", [], True),
    ("kokunen", "国民年金法", "334AC0000000141", [TODAY], ["25"], None, None, [], True),
    ("kounen", "厚生年金保険法", "329AC0000000115", [TODAY], ["41"], None, None, [], True),
    ("kokkyo", "国家公務員共済組合法", "333AC0000000128", [TODAY], [], r"公課", r"租税その他の公課", [], True),
    ("chikyo", "地方公務員等共済組合法", "337AC0000000152", [TODAY], [], r"公課", r"租税その他の公課", [], True),
    ("shigaku", "私立学校教職員共済法", "328AC0000000245", [TODAY], [], r"公課", r"租税その他の公課|国家公務員共済組合法第五十二条", [], True),
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


def locate(path, node):
    loc = {"part": "MainProvision", "amend_law_num": None, "article": None, "caption": None, "paragraph": None, "item": None}
    for p in list(path) + [node]:
        t = p.get("tag")
        a = p.get("attr") or {}
        if t == "SupplProvision":
            loc["part"] = "SupplProvision"
            loc["amend_law_num"] = a.get("AmendLawNum", "(原始附則)")
        elif t in ("AppdxTable", "AppdxNote", "Appdx", "AppdxStyle", "AppdxFormat", "AppdxFig"):
            loc["part"] = t
        elif t == "Article":
            loc["article"] = a.get("Num")
            loc["caption"] = caption_of(p)
        elif t == "Paragraph":
            loc["paragraph"] = a.get("Num")
        elif t == "Item":
            loc["item"] = a.get("Num")
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


def fetch_full(law_id, asof, dl, omit):
    q = {"response_format": "json", "asof": asof}
    if omit:
        q["omit_amendment_suppl_provision"] = "true"
    url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode(q)
    st, body = get(url)
    (dl / f"{law_id}_{asof}.json").write_bytes(body)
    if st != 200:
        raise RuntimeError(f"{url} -> {st} {body[:200]!r}")
    return url, body, json.loads(body)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2B_nenkin_egov"
    dl.mkdir(parents=True, exist_ok=False)
    for sub in ("articles", "scan", "diff"):
        (OUT / sub).mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "user_agent": UA, "fetches": []}
    for short, title, law_id, asofs, arts, cap_re, txt_re, amend_nums, omit in JOBS:
        texts = {}
        for asof in asofs:
            url, body, d = fetch_full(law_id, asof, dl, omit)
            ri = d.get("revision_info") or {}
            entry = {"short": short, "law": title, "law_id": law_id, "asof": asof, "url": url,
                     "law_title": ri.get("law_title"), "law_revision_id": ri.get("law_revision_id"),
                     "amendment_law_title": ri.get("amendment_law_title"), "amendment_law_num": ri.get("amendment_law_num"),
                     "amendment_enforcement_date": ri.get("amendment_enforcement_date"),
                     "current_revision_status": ri.get("current_revision_status"),
                     "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
            log["fetches"].append(entry)
            print("ok", short, asof, ri.get("law_revision_id"), flush=True)
            root = d["law_full_text"]
            main_arts, orig_suppl_arts, suppl = [], [], []

            def collect(n, path):
                tags = [p.get("tag") for p in path]
                if n.get("tag") == "Article":
                    if "SupplProvision" not in tags:
                        main_arts.append(n)
                    else:
                        sp = [p for p in path if p.get("tag") == "SupplProvision"][-1]
                        if not (sp.get("attr") or {}).get("AmendLawNum"):
                            orig_suppl_arts.append(n)
                if n.get("tag") == "SupplProvision":
                    suppl.append(n)
            walk(root, collect)
            header = [f"# {short} {title} {law_id} asof={asof}",
                      f"# 法令名={ri.get('law_title')} law_revision_id={ri.get('law_revision_id')} 改正法令={ri.get('amendment_law_num')} "
                      f"施行日={ri.get('amendment_enforcement_date')} 状態={ri.get('current_revision_status')}",
                      f"# 取得URL={url}", f"# 取得日時={ts}", f"# 生データ SHA-256={entry['sha256']}", ""]
            lines = list(header)
            by_num = {a["attr"].get("Num"): a for a in main_arts}
            sel = list(arts)
            for a in main_arts:
                num = a["attr"].get("Num")
                if num in sel:
                    continue
                if (cap_re and re.search(cap_re, caption_of(a))) or (txt_re and re.search(txt_re, text_of(a))):
                    sel.append(num)
            for num in sel:
                a = by_num.get(num)
                if a is None:
                    lines += [f"## 本則 Num={num}: 見つからない（この時点の本則にない）", ""]
                    continue
                lines.append(f"## 本則 Num={num}")
                render(a, 0, lines)
                lines.append("")
            for a in orig_suppl_arts:
                if (cap_re and re.search(cap_re, caption_of(a))) or (txt_re and re.search(txt_re, text_of(a))):
                    lines.append(f"## 原始附則 Num={a['attr'].get('Num')}")
                    render(a, 0, lines)
                    lines.append("")
            for an in amend_nums:
                hits = [s for s in suppl if (s.get("attr") or {}).get("AmendLawNum") == an]
                lines.append(f"## 改正附則 AmendLawNum={an}: {len(hits)} 件（「公的年金」を含む条と第1条（施行期日）だけ）")
                for s in hits:
                    for c in s.get("children", []):
                        if isinstance(c, dict) and c.get("tag") == "Article":
                            t = text_of(c)
                            if "公的年金" in t or c["attr"].get("Num") == "1":
                                lines.append(f"### 附則 Num={c['attr'].get('Num')}")
                                lines.append(t)
                lines.append("")
            txt = "\n".join(lines)
            texts[asof] = txt
            (OUT / "articles" / f"{short}_{asof}.txt").write_text(txt, encoding="utf-8")
            kh = keyword_hits(root, KW)
            (OUT / "scan" / f"{short}_{asof}.json").write_text(
                json.dumps({"law_id": law_id, "asof": asof, "law_revision_id": ri.get("law_revision_id"), "keywords": KW,
                            "n_hits": len(kh), "hits": kh}, ensure_ascii=False, indent=1), encoding="utf-8")
        for a1, a2 in zip(asofs, asofs[1:]):
            l1 = [x for x in texts[a1].splitlines() if not x.startswith("# ")]
            l2 = [x for x in texts[a2].splitlines() if not x.startswith("# ")]
            df = list(difflib.unified_diff(l1, l2, fromfile=f"{short}_{a1}", tofile=f"{short}_{a2}", lineterm="", n=1))
            (OUT / "diff" / f"{short}_{a1}_vs_{a2}.diff").write_text("\n".join(df) if df else "(差分なし)", encoding="utf-8")
    (OUT / "fetch_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", OUT)


if __name__ == "__main__":
    sys.exit(main())
