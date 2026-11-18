"""IMPL zeigaku 独立検証: zeigaku の文書（docs/*/20261109_impl-prep_zeigaku-*.md）に書かれた条文・数値を、
一次情報（e-Gov 法令API v2、国税庁・日本年金機構のページ）に当たり直して確かめるための実測スクリプト。

実行（pyenv のシムは使わない）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_zeigaku_verify.py laws   # 法令本文の取得と抜き出し → results/.../laws/
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_zeigaku_verify.py laws2  # 補足（施行日・附則・改正履歴・キーワード検索）→ laws2/
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_zeigaku_verify.py web    # 国税庁・年金機構のページと手引き PDF → web/
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_zeigaku_verify.py extra  # 残りのページ（web2/）、復興財源確保法の全条比較（extra/）
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_zeigaku_verify.py calc   # 計算の再計算（laws の後。ネットワーク不要）→ calc/

- 担当（zeigaku）のスクリプトの出力は使わない。法令は新しく取得し直す。
- 取得したものは信頼できないデータ。取得ごとに新しい空のディレクトリ .work/downloads/<YYYYMMDD-HHMMSS>_IMPL_zeigaku_verify_<mode>/ に置き、
  その中ではコードを実行しない（JSON は json.loads、HTML は html.parser でデータとして読むだけ）。
- 結果は scripts/results/IMPL_zeigaku_verify/ に書く。
- e-Gov API の使い方（/law_data/{law_id}?response_format=json&asof=...、/laws?law_title=...）は scripts/R1_egov_articles.py と
  scripts/R4_fetch_laws.py を読んで写した（import はしない）。テキスト化の関数は項・号の番号が必ず出るように自分で書き直した。
- User-Agent okura-gov-research/0.1、リクエストの間は 1.5 秒。標準ライブラリのみ。
"""
import hashlib
import html.parser
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from fractions import Fraction

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "okura-gov-research/0.1"
API = "https://laws.e-gov.go.jp/api/2"
SLEEP = 1.5
OUT = ROOT / "scripts" / "results" / "IMPL_zeigaku_verify"

R8_12 = "令和八年三月三一日法律第一二号"   # 令和8年度の税制改正法（AmendLawNum の表記。R1 の結果で確認済みの表記）

# (略称, law_id, 法令名（law_id が None のときの検索用）, [asof...], [本則の条番号（Num 属性）], [別表の見出しの前方一致],
#  [(附則の AmendLawNum の正規表現, [条番号] または None（全部）)])
LAW_JOBS = [
    ("shotoku", "340AC0000000033", "所得税法", ["2024-12-31", "2025-12-31", "2026-12-31", "2027-01-01"],
     ["2", "21", "22", "28", "74", "82", "84_2", "85", "86", "87", "89", "104", "120", "121", "122", "138"], ["別表第五"],
     [(re.escape(R8_12), ["1", "10"])]),
    ("shotoku-rei", "340CO0000000096", "所得税法施行令", ["2025-12-31", "2026-12-31"],
     ["11_3", "208", "262", "262_2", "264", "267"], [], [(r"^令和八年.*政令第九三号$", ["1", "3"])]),
    ("shotoku-ki", "340M50000040011", "所得税法施行規則", ["2025-12-31", "2026-12-31"], ["47", "47_2"], [], []),
    ("tsusoku", "337AC0000000066", "国税通則法", ["2025-12-31", "2026-12-31"], ["10", "74", "118", "119", "120"], [], []),
    ("tsusoku-rei", "337CO0000000135", "国税通則法施行令", ["2025-12-31", "2026-12-31"], ["40"], [], []),
    ("fukko", "423AC0000000117", "東日本大震災からの復興のための施策を実施するために必要な財源の確保に関する特別措置法",
     ["2025-12-31", "2026-12-31", "2027-01-01"],
     ["8", "9", "10", "12", "13", "16", "17", "18", "19", "24", "27", "28", "31"], [], [(re.escape(R8_12), ["1", "88"])]),
    ("fukko-rei", None, "復興特別所得税に関する政令", ["2025-12-31", "2026-12-31"], ["__GREP__一円未満|端数"], [], []),
    ("fukko-ki", None, "復興特別所得税に関する省令", ["2025-12-31", "2026-12-31"], ["__GREP__一円未満|端数|切り捨て"], [], []),
    ("kokunen", "334AC0000000141", "国民年金法", ["2026-11-09"], ["88", "90", "90_3"], [], []),
    ("kokunen-rei", "334CO0000000184", "国民年金法施行令", ["2025-04-01", "2026-11-09"], ["5_4", "6_6", "6_9", "6_10", "6_12"], [], []),
    ("kokunen-ki", "335M50000100012", "国民年金法施行規則", ["2026-11-09"], ["77_2", "77_4"], [], []),
    ("gakko", "322AC0000000026", "学校教育法", ["2026-11-09"], ["1", "124", "134"], [], []),
    ("sochi", "332AC0000000026", "租税特別措置法", ["2025-12-31", "2026-12-31"], ["29_4", "41_16_2"], [], []),
    ("chiho", "325AC0000000226", "地方税法", ["2026-11-09"], ["314_2"], [], []),
    ("hasu", None, "国等の債権債務等の金額の端数計算に関する法律", ["2026-11-09"], ["__ALL__"], [], []),
]


def http_get(url, accept="application/json", timeout=300):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept, "Accept-Language": "ja"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body, st, hdr, final = r.read(), r.status, dict(r.headers), r.geturl()
    except urllib.error.HTTPError as e:
        body, st, hdr, final = (e.read() if hasattr(e, "read") else b""), e.code, dict(e.headers or {}), url
    time.sleep(SLEEP)
    return st, body, hdr, final


# ---------- 法令本文のテキスト化（項・号の番号を必ず出す） ----------
def text_of(n):
    if isinstance(n, str):
        return n
    if not isinstance(n, dict) or n.get("tag") == "Rt":
        return ""
    if n.get("tag") == "Column":
        return "".join(text_of(c) for c in n.get("children", [])) + "　"
    return "".join(text_of(c) for c in n.get("children", []))


ITEM_TAGS = {"Item"} | {f"Subitem{i}" for i in range(1, 11)}


def render(n, depth, out):
    if isinstance(n, str) or not isinstance(n, dict):
        return
    tag = n.get("tag", "")
    ch = [c for c in n.get("children", []) if isinstance(c, dict)]
    ind = "  " * depth
    if tag == "Article":
        cap = "".join(text_of(c) for c in ch if c.get("tag") == "ArticleCaption")
        tit = "".join(text_of(c) for c in ch if c.get("tag") == "ArticleTitle")
        out.append(f"{ind}【{tit}】{cap}  (Num={n.get('attr', {}).get('Num')})")
        for c in ch:
            if c.get("tag") not in ("ArticleCaption", "ArticleTitle"):
                render(c, depth + 1, out)
        return
    if tag == "Paragraph":
        num = n.get("attr", {}).get("Num", "")
        sent = "".join(text_of(c) for c in ch if c.get("tag") == "ParagraphSentence")
        out.append(f"{ind}[第{num}項] {sent}")
        for c in ch:
            if c.get("tag") not in ("ParagraphNum", "ParagraphSentence", "ParagraphCaption"):
                render(c, depth + 1, out)
        return
    if tag in ITEM_TAGS:
        tit = "".join(text_of(c) for c in ch if c.get("tag", "").endswith("Title"))
        sent = "".join(text_of(c) for c in ch if c.get("tag", "").endswith("Sentence"))
        out.append(f"{ind}({tit}) {sent}")
        for c in ch:
            if not (c.get("tag", "").endswith("Title") or c.get("tag", "").endswith("Sentence")):
                render(c, depth + 1, out)
        return
    if tag == "TableRow":
        out.append(ind + "| " + " | ".join(" ".join(text_of(c).split()) for c in ch) + " |")
        return
    if tag in ("AppdxTableTitle", "SupplProvisionLabel", "RelatedArticleNum"):
        out.append(ind + text_of(n))
        return
    for c in ch:
        render(c, depth, out)


def walk(n, fn, path=()):
    if isinstance(n, dict):
        fn(n, path)
        for c in n.get("children", []):
            walk(c, fn, path + (n.get("tag"),))


def find_law_id(title, dl, tag):
    q = urllib.parse.urlencode({"law_title": title, "response_format": "json", "asof": "2026-11-09"})
    st, body, _, _ = http_get(f"{API}/laws?{q}")
    (dl / f"search_{tag}.json").write_bytes(body)
    for law in json.loads(body).get("laws", []):
        rv = law.get("current_revision_info") or law.get("revision_info") or {}
        if rv.get("law_title") == title:
            return law["law_info"]["law_id"]
    return None


def mode_laws():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_IMPL_zeigaku_verify_laws"
    dl.mkdir(parents=True, exist_ok=False)
    out = OUT / "laws"
    out.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "fetches": [], "errors": []}
    for short, law_id, title, asofs, arts, appdx, suppls in LAW_JOBS:
        try:
            if law_id is None:
                law_id = find_law_id(title, dl, short)
                if not law_id:
                    log["errors"].append({"short": short, "error": "law_id not found"})
                    print("ERR law_id", short, flush=True)
                    continue
            for asof in asofs:
                url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode({"response_format": "json", "asof": asof})
                st, body, _, _ = http_get(url)
                p = dl / f"{short}_{asof}.json"
                p.write_bytes(body)
                if st != 200:
                    log["errors"].append({"short": short, "asof": asof, "status": st, "head": body[:200].decode("utf-8", "replace")})
                    print("ERR", short, asof, st, flush=True)
                    continue
                d = json.loads(body)
                ri = d.get("revision_info") or {}
                li = d.get("law_info") or {}
                rec = {"short": short, "title": title, "law_id": law_id, "law_num": li.get("law_num"), "asof": asof, "url": url,
                       "http_status": st, "sha256": hashlib.sha256(body).hexdigest(),
                       "law_revision_id": ri.get("law_revision_id"), "amendment_law_num": ri.get("amendment_law_num"),
                       "amendment_enforcement_date": ri.get("amendment_enforcement_date"),
                       "current_revision_status": ri.get("current_revision_status")}
                main_arts, suppl, appdx_nodes = [], [], []

                def collect(n, path):
                    if n.get("tag") == "Article" and "SupplProvision" not in path:
                        main_arts.append(n)
                    if n.get("tag") == "SupplProvision":
                        suppl.append(n)
                    if n.get("tag") == "AppdxTable":
                        appdx_nodes.append(n)
                walk(d["law_full_text"], collect)
                lines = [f"# {short} {title} law_id={law_id} asof={asof}",
                         f"# law_revision_id={rec['law_revision_id']} 改正法令={rec['amendment_law_num']} 施行日={rec['amendment_enforcement_date']} 状態={rec['current_revision_status']}",
                         f"# URL={url}", f"# 取得={ts} sha256={rec['sha256']}", ""]
                by_num = {a.get("attr", {}).get("Num"): a for a in main_arts}
                found, missing = [], []
                for num in arts:
                    if num == "__ALL__":
                        render(d["law_full_text"], 0, lines)
                        found.append("__ALL__")
                        continue
                    if num.startswith("__GREP__"):
                        pat = re.compile(num[len("__GREP__"):])
                        hits = []

                        def g(n, path):
                            if n.get("tag") == "Article":
                                t = text_of(n)
                                if pat.search(t):
                                    where = "附則" if "SupplProvision" in path else "本則"
                                    hits.append((where, n))
                        walk(d["law_full_text"], g)
                        lines.append(f"## GREP /{pat.pattern}/ : {len(hits)} 条")
                        for where, n in hits:
                            lines.append(f"### {where}")
                            render(n, 0, lines)
                        found.append(f"GREP:{len(hits)}")
                        continue
                    a = by_num.get(num)
                    if a is None:
                        missing.append(num)
                        lines.append(f"## Num={num}: 本則に見つからない")
                        continue
                    lines.append(f"## Num={num}")
                    render(a, 0, lines)
                    lines.append("")
                    found.append(num)
                for pref in appdx:
                    hits = [t for t in appdx_nodes if any(isinstance(c, dict) and c.get("tag") == "AppdxTableTitle" and text_of(c).startswith(pref)
                                                          for c in t.get("children", []))]
                    for t in hits:
                        tl = []
                        render(t, 0, tl)
                        lines.append(f"## 別表 {pref}（全 {len(tl)} 行）")
                        lines += tl
                        # 計算用に表の行をそのまま JSON にも保存（calc で使う）
                        rows = []

                        def rw(n, path):
                            if n.get("tag") == "TableRow":
                                rows.append([" ".join(text_of(c).split()) for c in n.get("children", []) if isinstance(c, dict)])
                        walk(t, rw)
                        (out / f"{short}_{asof}_{pref}.rows.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
                for pat, nums in suppls:
                    rx = re.compile(pat)
                    hits = [s for s in suppl if rx.search(s.get("attr", {}).get("AmendLawNum", "") or "")]
                    lines.append(f"## 附則 AmendLawNum~/{pat}/ : {len(hits)} 件 {[s.get('attr', {}).get('AmendLawNum') for s in hits]}")
                    for s in hits:
                        arts_s = []
                        walk(s, lambda n, path: arts_s.append(n) if n.get("tag") == "Article" else None)
                        for a in arts_s:
                            if nums is None or a.get("attr", {}).get("Num") in nums:
                                render(a, 0, lines)
                                lines.append("")
                        if not arts_s:  # 条のない附則（項だけ）
                            render(s, 0, lines)
                rec["found"], rec["missing"] = found, missing
                log["fetches"].append(rec)
                (out / f"{short}_{asof}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
                print("ok", short, asof, rec["law_revision_id"], rec["current_revision_status"], "missing", missing, flush=True)
        except Exception as e:  # noqa
            log["errors"].append({"short": short, "error": repr(e)})
            print("ERR", short, repr(e), flush=True)
    (out / "fetch_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", out)


def fetch_law(law_id, asof, dl, tag):
    url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode({"response_format": "json", "asof": asof})
    st, body, _, _ = http_get(url)
    (dl / f"{tag}_{asof}.json").write_bytes(body)
    if st != 200:
        return st, url, None
    return st, url, json.loads(body)


def articles_of(d, nums=None, suppl_pat=None):
    """本則（suppl_pat=None）または AmendLawNum が suppl_pat に合う附則の条を返す。"""
    out = []

    def f(n, path):
        if n.get("tag") != "Article":
            return
        out.append((path, n))
    if suppl_pat is None:
        walk(d["law_full_text"], lambda n, p: out.append(n) if n.get("tag") == "Article" and "SupplProvision" not in p
             and (nums is None or n.get("attr", {}).get("Num") in nums) else None)
        return out
    rx = re.compile(suppl_pat)
    hits = []
    walk(d["law_full_text"], lambda n, p: hits.append(n) if n.get("tag") == "SupplProvision"
         and rx.search(n.get("attr", {}).get("AmendLawNum", "") or "") else None)
    for s in hits:
        walk(s, lambda n, p: out.append(n) if n.get("tag") == "Article" and (nums is None or n.get("attr", {}).get("Num") in nums) else None)
    return out


def mode_laws2():
    """補足の確認：(1) 所法第2条第1項第32号ロの「学生又は生徒」への改正の施行日と経過措置、(2) 担当の実測 §1 の版のうち laws で取り直していないもの、
    (3) 改正履歴（復興財源確保法・国民年金法施行令）、(4) キーワード検索「防衛特別所得税」、(5) 国年令第6条の12第2項第1号の改正の時期、
    (6) 復興財源確保法 第1条・第33条（担当の実測 §2 の「2025-12-31→2026-12-31 で第1条・第33条が変わった」の確認）。"""
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_IMPL_zeigaku_verify_laws2"
    dl.mkdir(parents=True, exist_ok=False)
    out = OUT / "laws2"
    out.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "items": []}
    lines = [f"# laws2 取得={ts}", ""]

    def head(tag, asof, st, url, d):
        ri = (d or {}).get("revision_info") or {}
        rec = {"tag": tag, "asof": asof, "status": st, "url": url, "law_revision_id": ri.get("law_revision_id"),
               "amendment_law_num": ri.get("amendment_law_num"), "amendment_enforcement_date": ri.get("amendment_enforcement_date"),
               "current_revision_status": ri.get("current_revision_status")}
        log["items"].append(rec)
        lines.append(f"## {tag} asof={asof} HTTP {st} {rec['law_revision_id']} 施行日={rec['amendment_enforcement_date']} 状態={rec['current_revision_status']}")
        return rec
    # (1) 所得税法 第2条第1項第32号ロ
    for asof in ("2026-03-31", "2026-04-01"):
        st, url, d = fetch_law("340AC0000000033", asof, dl, "shotoku")
        head("shotoku", asof, st, url, d)
        if d:
            a2 = articles_of(d, ["2"])
            t = text_of(a2[0]) if a2 else ""
            m = re.findall(r"各種学校の.{0,8}で政令で定める課程", t)
            m2 = re.findall(r"合計所得金額が[^円]{1,10}円以下であり、かつ", t)
            lines.append(f"  第2条 第32号ロ: {m}  第32号の金額: {m2}")
            if asof == "2026-04-01":
                for a in articles_of(d, ["1", "2", "3"], re.escape(R8_12)):
                    render(a, 1, lines)
    # 2026-12-31 版に収録された令和8年法律第12号の附則の条番号と、第2条・第3条（勤労学生・扶養親族の金額などの適用関係）
    st, url, d = fetch_law("340AC0000000033", "2026-12-31", dl, "shotoku")
    head("shotoku", "2026-12-31", st, url, d)
    if d:
        arts = articles_of(d, None, re.escape(R8_12))
        lines.append(f"  附則（令和8年法律第12号）に収録された条: {[a.get('attr', {}).get('Num') for a in arts]}")
        for a in arts:
            if a.get("attr", {}).get("Num") in ("2", "3"):
                render(a, 1, lines)
    lines.append("")
    # (2) 版の確認（担当の実測 §1 のうち laws で取り直していないもの）
    for tag, law_id, asof in (("shotoku-rei-r9", "340CO0000000096", "2027-01-01"), ("kokunen-rei", "334CO0000000184", "2027-04-01")):
        st, url, d = fetch_law(law_id, asof, dl, tag)
        head(tag, asof, st, url, d)
        if d and tag == "shotoku-rei-r9":
            for a in articles_of(d, ["262"]):
                t = text_of(a)
                lines.append(f"  第262条 第1項に「第百二十条第三項第一号」: {'第百二十条第三項第一号' in t}  本文の長さ {len(t)}")
    lines.append("")
    # (3) 改正履歴
    for tag, law_id in (("fukko", "423AC0000000117"), ("kokunen-rei", "334CO0000000184")):
        q = urllib.parse.urlencode({"response_format": "json", "amendment_date_from": "2024-01-01"})
        st, body, _, _ = http_get(f"{API}/law_revisions/{law_id}?{q}")
        (dl / f"revisions_{tag}.json").write_bytes(body)
        revs = json.loads(body).get("revisions", []) if st == 200 else []
        lines.append(f"## 改正履歴 {tag} HTTP {st} 件数 {len(revs)}")
        for rv in revs:
            lines.append(f"  {rv.get('law_revision_id')} 施行={rv.get('amendment_enforcement_date')} 予定={rv.get('amendment_scheduled_enforcement_date')} "
                         f"{rv.get('amendment_law_num')} {rv.get('current_revision_status')}")
        log["items"].append({"revisions": tag, "status": st, "count": len(revs)})
        # (5) 国年令第6条の12第2項第1号：各版の施行日を asof にして「第十二号」の有無を見る
        if tag == "kokunen-rei":
            dates = sorted({rv.get("amendment_enforcement_date") for rv in revs if rv.get("amendment_enforcement_date")
                            and "2025-04-02" <= rv.get("amendment_enforcement_date") <= "2026-11-09"})
            prev = None
            for asof in dates:
                st2, url2, d2 = fetch_law(law_id, asof, dl, "kokunen-rei")
                rec = head("kokunen-rei", asof, st2, url2, d2)
                if d2:
                    has = False
                    for a in articles_of(d2, ["6_12"]):
                        t = text_of(a)
                        has = "特定親族特別控除額" in t
                        lines.append(f"  第6条の12 に「第十号の二又は第十二号」: {'第十号の二又は第十二号' in t} / 「特定親族特別控除額」: {has}")
                    if has and prev is False:
                        # 初めて現れた版：その版の改正法令の附則で第六条の十二に触れる条を出す
                        an = rec.get("amendment_law_num") or ""
                        lines.append(f"  → この版（改正法令 {an}）で第6条の12第2項第1号に第12号・特定親族特別控除額が加わった")
                        sps = []
                        walk(d2["law_full_text"], lambda n, p: sps.append(n) if n.get("tag") == "SupplProvision" else None)
                        for s in sps:
                            an2 = s.get("attr", {}).get("AmendLawNum") or "(原始附則)"
                            arts_s = []
                            walk(s, lambda n, p: arts_s.append(n) if n.get("tag") == "Article" else None)
                            for n in [x for x in arts_s if "第六条の十二" in text_of(x)]:
                                lines.append(f"  附則（{an2}）で第六条の十二に触れる条:")
                                render(n, 2, lines)
                    prev = has
    lines.append("")
    # (4) キーワード検索
    for asof in ("2027-01-01", "2026-11-09"):
        q = urllib.parse.urlencode({"keyword": "防衛特別所得税", "response_format": "json", "asof": asof, "limit": 5})
        st, body, _, _ = http_get(f"{API}/keyword?{q}")
        (dl / f"keyword_{asof}.json").write_bytes(body)
        tc = None
        firsts = []
        try:
            data = json.loads(body)
            tc = data.get("total_count")
            for it in data.get("items", [])[:5]:
                rv = it.get("revision_info", {})
                firsts.append((rv.get("law_title"), rv.get("law_revision_id")))
        except Exception as e:  # noqa
            firsts.append(("parse_error", repr(e)))
        lines.append(f"## keyword 防衛特別所得税 asof={asof} HTTP {st} total_count={tc}")
        for f in firsts:
            lines.append(f"  {f}")
        log["items"].append({"keyword": asof, "status": st, "total_count": tc})
    lines.append("")
    # (6) 復興財源確保法 第1条・第33条
    texts = {}
    for asof in ("2025-12-31", "2026-12-31"):
        st, url, d = fetch_law("423AC0000000117", asof, dl, "fukko")
        head("fukko", asof, st, url, d)
        if d:
            texts[asof] = {a.get("attr", {}).get("Num"): text_of(a) for a in articles_of(d, ["1", "11", "33"])}
    if len(texts) == 2:
        for k in ("1", "11", "33"):
            lines.append(f"  復興法 第{k}条 2025-12-31 と 2026-12-31 で同じ: {texts['2025-12-31'].get(k) == texts['2026-12-31'].get(k)}")
    (out / "laws2.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "fetch_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(lines))


# ---------- 国税庁・年金機構のページ ----------
TA = "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/"
WEB = {
    "ta_1130": TA + "1130.htm", "ta_1175": TA + "1175.htm", "ta_1177": TA + "1177.htm", "ta_1199": TA + "1199.htm",
    "ta_1410": TA + "1410.htm", "ta_1900": TA + "1900.htm", "ta_2020": TA + "2020.htm", "ta_2030": TA + "2030.htm",
    "ta_2040": TA + "2040.htm", "ta_2260": TA + "2260.htm",
    "kihon_16_02": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/16/02.htm",
    "kihon_19_01": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/19/01.htm",
    "kihon_19_02": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/19/02.htm",
    "kihon_01_07": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/01/07.htm",
    "nenkin_gakutoku": "https://www.nenkin.go.jp/service/kokunen/menjo/20150514.html",
    "nenkin_20150331": "https://www.nenkin.go.jp/service/kokunen/menjo/20150331.html",
    "nenkin_koujo": "https://www.nenkin.go.jp/service/kokunen/hokenryo/koujo/index.html",
    "tebiki_r07_001pdf": "https://www.nta.go.jp/taxes/shiraberu/shinkoku/tebiki/2025/pdf/001.pdf",
}


class Extract(html.parser.HTMLParser):
    """scripts/IMPL_zeigaku_fetch_web.py（元は scripts/R3_fetch.py）の Extract を写して簡略化したもの。"""
    SKIP = {"script", "style", "noscript"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.title, self._skip, self._in_title = [], "", 0, False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in self.SKIP:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag == "img" and a.get("alt") and not self._skip:
            self.parts.append("⟨" + a["alt"] + "⟩")
        if tag in ("br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "dt", "dd", "table"):
            self.parts.append("\n")
        if tag in ("td", "th"):
            self.parts.append(" | ")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False
        if tag in ("p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "dd"):
            self.parts.append("\n")

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title:
            self.title += data
        self.parts.append(data)

    def text(self):
        t = "".join(self.parts)
        t = re.sub(r"[ \t　]+\n", "\n", t)
        return re.sub(r"\n{3,}", "\n\n", t).strip()


def decode(body, ctype):
    m = re.search(r"charset=([\w\-]+)", ctype or "", re.I)
    cs = m.group(1) if m else None
    if not cs:
        m = re.search(rb"<meta[^>]+charset=[\"']?([\w\-]+)", body[:4000], re.I)
        cs = m.group(1).decode("ascii", "replace") if m else None
    for c in [cs, "utf-8", "cp932"]:
        if c:
            try:
                return body.decode(c)
            except (LookupError, UnicodeDecodeError):
                pass
    return body.decode("utf-8", "replace")


def mode_web():
    mode_web_into("web")


def mode_web_into(sub):
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_IMPL_zeigaku_verify_{sub}"
    dl.mkdir(parents=True, exist_ok=False)
    tx = ROOT / ".work" / "text" / f"{ts}_IMPL_zeigaku_verify_{sub}"
    tx.mkdir(parents=True, exist_ok=False)
    out = OUT / sub
    out.mkdir(parents=True, exist_ok=True)
    robots = {}
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "text_dir": str(tx.relative_to(ROOT)), "robots": [], "items": []}
    for sid, url in WEB.items():
        sp = urllib.parse.urlsplit(url)
        base = f"{sp.scheme}://{sp.netloc}"
        if base not in robots:
            st, body, hdr, _ = http_get(base + "/robots.txt", accept="text/plain")
            (dl / ("robots_" + sp.netloc.replace(".", "_") + ".txt")).write_bytes(body)
            rp = urllib.robotparser.RobotFileParser()
            rp.parse(decode(body, hdr.get("Content-Type", "")).splitlines() if st == 200 else [])
            robots[base] = rp
            log["robots"].append({"url": base + "/robots.txt", "status": st, "sha256": hashlib.sha256(body).hexdigest()})
        rec = {"id": sid, "url": url}
        if not robots[base].can_fetch(UA, url):
            rec["skipped"] = "robots.txt"
            log["items"].append(rec)
            continue
        st, body, hdr, final = http_get(url, accept="*/*", timeout=120)
        ctype = hdr.get("Content-Type", "")
        ext = ".pdf" if ("pdf" in ctype.lower() or url.endswith(".pdf")) else ".html"
        (dl / (sid + ext)).write_bytes(body)
        rec.update({"status": st, "final_url": final, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
                    "last_modified": hdr.get("Last-Modified"), "content_type": ctype, "saved": str((dl / (sid + ext)).relative_to(ROOT))})
        if ext == ".html" and st == 200:
            p = Extract()
            p.feed(decode(body, ctype))
            t = p.text()
            rec["title"] = " ".join(p.title.split())
            m = re.search(r"[［\[]\s*(令和|平成)\s*[0-9０-９元]+年[0-9０-９]+月[0-9０-９]+日現在法令等\s*[］\]]", t)
            rec["as_of_label"] = m.group(0) if m else None
            (tx / (sid + ".txt")).write_text(t, encoding="utf-8")
            (out / (sid + ".txt")).write_text(t, encoding="utf-8")   # 照合用にテキストを結果にも残す（数十KB）
        if ext == ".pdf":
            rec["pdf_page_objects"] = len(re.findall(rb"/Type\s*/Page[^s]", body))
        log["items"].append(rec)
        print(sid, rec.get("status"), rec.get("last_modified"), rec.get("as_of_label"), flush=True)
    (out / "fetch_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", out)


WEB2 = {
    "shitsugi_shotoku_index": "https://www.nta.go.jp/law/shitsugi/shotoku/01.htm",
    "kihon_shotoku_index": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/01.htm",
    "tebiki_index": "https://www.nta.go.jp/taxes/shiraberu/shinkoku/tebiki/index.htm",
    "tebiki_r07": "https://www.nta.go.jp/taxes/shiraberu/shinkoku/syotoku/r07.htm",
    "nencho2026_index": "https://www.nta.go.jp/publication/pamph/gensen/nencho2026/01.htm",
    "nenkin_r8koujo": "https://www.nenkin.go.jp/service/kokunen/hokenryo/koujo/R8koujo/index.html",
    "shinkokusho_r07_01pdf": "https://www.nta.go.jp/taxes/shiraberu/shinkoku/yoshiki/01/shinkokusho/pdf/r07/01.pdf",
}


def mode_extra():
    """(a) 担当の実測 §4 のうち web で取り直していないページの取得記録、(b) 復興財源確保法の本則の全条を 2026-12-31 と 2027-01-01 で比べる、
    (c) キーワード検索「防衛特別所得税」（2027-01-01）の防衛財源確保法の該当文。"""
    global WEB
    saved = WEB
    WEB = WEB2
    try:
        mode_web_into("web2")
    finally:
        WEB = saved
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_IMPL_zeigaku_verify_extra"
    dl.mkdir(parents=True, exist_ok=False)
    out = OUT / "extra"
    out.mkdir(parents=True, exist_ok=True)
    lines = [f"# extra 取得={ts}", ""]
    texts = {}
    for asof in ("2026-12-31", "2027-01-01"):
        st, url, d = fetch_law("423AC0000000117", asof, dl, "fukko")
        ri = (d or {}).get("revision_info") or {}
        lines.append(f"## fukko asof={asof} HTTP {st} {ri.get('law_revision_id')}")
        if d:
            texts[asof] = {a.get("attr", {}).get("Num"): text_of(a) for a in articles_of(d)}
    if len(texts) == 2:
        a, b = texts["2026-12-31"], texts["2027-01-01"]
        def key(n):
            return [int(x) for x in re.findall(r"\d+", n or "0")]
        nums = sorted(set(a) | set(b), key=key)
        same = [n for n in nums if a.get(n) == b.get(n)]
        diff = [n for n in nums if a.get(n) != b.get(n)]
        lines.append(f"  2026-12-31 と 2027-01-01 で同じ条: {same}")
        lines.append(f"  違う条: {diff}")
        for n in nums:
            if n not in a:
                lines.append(f"  2027-01-01 だけにある条 Num={n}: {b[n][:600]}")
            if n not in b:
                lines.append(f"  2026-12-31 だけにある条 Num={n}: {a[n][:600]}")
    q = urllib.parse.urlencode({"keyword": "防衛特別所得税", "response_format": "json", "asof": "2027-01-01", "limit": 5, "sentences_limit": 5})
    st, body, _, _ = http_get(f"{API}/keyword?{q}")
    (dl / "keyword.json").write_bytes(body)
    lines.append(f"## keyword 防衛特別所得税 asof=2027-01-01 HTTP {st}")
    try:
        for it in json.loads(body).get("items", []):
            rv = it.get("revision_info", {})
            if "防衛力" in (rv.get("law_title") or ""):
                for s in it.get("sentences", []):
                    lines.append(f"  {s.get('position')}: {re.sub(r'<[^>]+>', '', s.get('text') or '')[:200]}")
    except Exception as e:  # noqa
        lines.append(f"  parse_error {e!r}")
    (out / "extra.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


# ---------- 計算の再計算（担当の example_calc とは別に、条文の表から直接計算する） ----------
def zen2int(s):
    s = s.translate(str.maketrans("０１２３４５６７８９，", "0123456789,")).replace(",", "").replace("円", "").strip()
    return int(s) if s.isdigit() else None


def load_beppyo5(asof):
    rows = json.loads((OUT / "laws" / f"shotoku_{asof}_別表第五.rows.json").read_text(encoding="utf-8"))
    table = []
    for r in rows:
        if len(r) < 3:
            continue
        lo, hi = zen2int(r[0]), zen2int(r[1])
        if lo is None and hi is None:
            continue
        table.append((lo, hi, r[2]))
    return table


def beppyo5_lookup(table, income):
    for lo, hi, val in table:
        if (lo is None or income >= lo) and (hi is None or income < hi):
            v = zen2int(val)
            if v is not None:
                return v
            m = re.search(r"給与等の金額から([０-９0-9,，]+)円を控除した金額", val)
            if m:
                return income - zen2int(m.group(1))
            return ("UNPARSED", val)
    return None


RATES = [(1_950_000, Fraction(5, 100)), (3_300_000, Fraction(10, 100)), (6_950_000, Fraction(20, 100)), (9_000_000, Fraction(23, 100)),
         (18_000_000, Fraction(33, 100)), (40_000_000, Fraction(40, 100)), (None, Fraction(45, 100))]


def tax89(k):
    t, lo = Fraction(0), 0
    for hi, r in RATES:
        top = k if hi is None else min(k, hi)
        if top > lo:
            t += (top - lo) * r
        if hi is None or k <= hi:
            break
        lo = hi
    return t


def sochi_29_4_r8(income):
    """措法第29条の4第2項（2026-12-31 版）の表。値は laws/sochi_2026-12-31.txt から写す（calc の出力に原文の行を併記して照合する）。"""
    if income < 691_000:
        return 0
    if income < 741_000:
        return 0
    if income < 2_191_000:
        return income - 740_000
    raise ValueError("範囲外")


def mode_calc():
    out = OUT / "calc"
    out.mkdir(parents=True, exist_ok=True)
    res = {}
    t7 = load_beppyo5("2025-12-31")
    t8 = load_beppyo5("2026-12-31")
    t6 = load_beppyo5("2024-12-31")
    res["beppyo5_head"] = {"2024-12-31": t6[:4], "2025-12-31": t7[:4], "2026-12-31": t8[:4]}
    res["beppyo5_rows"] = {"2024-12-31": len(t6), "2025-12-31": len(t7), "2026-12-31": len(t8)}
    res["kyuyo_r7_1400000"] = beppyo5_lookup(t7, 1_400_000)
    res["kyuyo_r8_honsoku_1400000"] = beppyo5_lookup(t8, 1_400_000)
    res["kyuyo_r8_sochi_1400000"] = sochi_29_4_r8(1_400_000)
    # 境目の確認（Z1 検証方法 2、Z3-S 推測の延長）
    res["kyuyo_r8_sochi_1630000"] = sochi_29_4_r8(1_630_000)
    res["kyuyo_r8_sochi_1631000"] = sochi_29_4_r8(1_631_000)
    res["kyuyo_r8_sochi_1581000"] = sochi_29_4_r8(1_581_000)
    res["kyuyo_r8_sochi_1580000"] = sochi_29_4_r8(1_580_000)
    # 例の再計算
    def case(year, kyuyo_income, zatsu, gensen, student, yono=0):
        k = beppyo5_lookup(t7, kyuyo_income) if year == 2025 else sochi_29_4_r8(kyuyo_income)
        gokei = k + zatsu
        kinro_lim = 850_000 if year == 2025 else 890_000
        kinro = 270_000 if (student and gokei <= kinro_lim) else 0
        if year == 2025:
            kiso = 580_000 + (370_000 if gokei <= 1_320_000 else None)
        else:
            kiso = 620_000 + (420_000 if gokei <= 4_890_000 else None)
        kojo = kinro + kiso
        zan = max(0, gokei - kojo)
        kazei = zan // 1000 * 1000
        tax = tax89(kazei)
        fk = Fraction(int(tax)) * Fraction(21, 1000)
        r = {"year": year, "kyuyo_shotoku": k, "gokei": gokei, "kinro": kinro, "kiso": kiso, "kojo": kojo, "kazei": kazei,
             "tax": str(tax), "fukko_exact": str(fk), "fukko_floor": int(fk)}
        for lab, tot in (("floor_first", int(tax) + int(fk)), ("no_floor", Fraction(int(tax)) + fk)):
            dif = tot - gensen - yono
            r[lab] = ("納付", int(dif) // 100 * 100) if dif >= 0 else ("還付", int(-dif))
        return r
    res["Z1"] = case(2026, 1_400_000, 0, 40_000, True)
    res["Z1-R7"] = case(2025, 1_400_000, 0, 40_000, True)
    res["Z1-K"] = case(2026, 1_400_000, 0, 40_000, False)
    res["Z2"] = case(2026, 1_400_000, 500_000, 101_260, True)
    res["Z3"] = case(2026, 1_400_000, 500_000, 0, True)
    res["Z3-S"] = case(2026, 1_400_000, 200_000, 0, True)
    res["Z5-R7"] = case(2025, 1_400_000, 321_000, 101_260, True)
    # Z3-S 推測の延長：給与1か所・給与以外の所得 20万円のとき税額が出始める給与所得・給与収入（令和8年分）
    first = None
    for inc in range(741_000, 2_191_000):
        c = case(2026, inc, 200_000, 0, True)
        if c["kazei"] > 0:
            first = (inc, c["kyuyo_shotoku"], c["kazei"])
            break
    res["Z3S_first_taxable_with_zatsu_200000"] = first
    # 性質：勤労学生控除の有無で課税総所得金額が変わる例（給与だけ。1円刻み）
    prop = {}
    for year, lo, hi in ((2025, 651_000, 1_899_999), (2026, 741_000, 2_190_999)):
        n = 0
        for inc in range(lo, hi + 1):
            a = case(year, inc, 0, 0, True)
            b = case(year, inc, 0, 0, False)
            if a["kazei"] != b["kazei"]:
                n += 1
        prop[year] = n
    res["property_kinro_no_effect_1yen_step"] = prop
    # 予定納税の見込み：税額 15万円に必要な課税総所得金額（5%・10% の段）
    need = None
    for k in range(0, 5_000_000, 1000):
        if tax89(k) >= 150_000:
            need = k
            break
    res["kazei_for_tax_150000"] = need
    # 曜日
    import datetime
    res["weekday"] = {d: datetime.date.fromisoformat(d).strftime("%A") for d in ("2026-03-15", "2026-03-16", "2027-02-16", "2027-03-15")}
    (out / "calc.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    m = sys.argv[1] if len(sys.argv) > 1 else ""
    {"laws": mode_laws, "laws2": mode_laws2, "web": mode_web, "extra": mode_extra, "calc": mode_calc}.get(m, lambda: print(__doc__))()
