r"""R2X_kokuho: e-Gov 法令API v2 で、国民健康保険料（税）と国民年金保険料の構造に関係する条文を時点（asof）ごとに取得する。

実行:
  C:\Users\user\.pyenv\pyenv-win\versions\3.11.9\python.exe -I -X utf8 scripts/R2X_kokuho_egov.py index   # 条番号と見出しの索引だけ（最新の asof）
  C:\Users\user\.pyenv\pyenv-win\versions\3.11.9\python.exe -I -X utf8 scripts/R2X_kokuho_egov.py         # JOBS をすべて取得
標準ライブラリのみ。リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。
テキスト化の処理（inline / render / walk）は scripts/IMPL_kyuyo_fetch.py（それ自体 scripts/R1_egov_articles.py の写し）を写したもの。

取得するもの（law_id は scripts/R2X_kokuho_lawsearch.py の結果で確かめた）
- 国民健康保険法（333AC0000000192）、同施行令（333CO0000000362）、同施行規則（333M50000100053）
- 地方税法（325AC0000000226）の国民健康保険税の節、同施行令（325CO0000000245）
- 国民年金法（334AC0000000141）、同施行令（334CO0000000184）、同施行規則（335M50000100012）
- 国民年金法による改定率の改定等に関する政令（417CO0000000092）
- 介護保険法（409AC0000000123）第9条（介護納付金賦課額の対象＝第2号被保険者の定義。取得日の版だけ）
asof：2025-04-01（令和7年度の初日）、2026-04-01（令和8年度の初日）、2026-11-09（取得日）、2027-04-01（令和9年度の初日。未施行の版が登録されていればそれ）

ダウンロードした JSON は .work/downloads/<ts>_R2X_kokuho_egov/ に置く（信頼できないデータ。中でコードを実行しない）。
抜き出した結果は scripts/results/R2X_kokuho_egov/ に書く。
- fetch_log_<mode>.json：取得URL、asof、law_revision_id、改正法令、施行日、状態、生データの SHA-256 とバイト数
- index_<略称>.txt：条番号と見出し（本則）、附則の AmendLawNum の一覧
- articles_<略称>_<asof>.txt：抜き出した条（本則）と、附則の条（名指し・読み替え・令和の改正法令の施行期日と適用年度）
- keyword_hits_<略称>_<asof>.json：キーワードの出現箇所（本則/附則、条、項、前後の文）
- article_diffs.json：法令ごとに、隣り合う asof の間で本則の条の本文が変わった条番号の一覧（附則は含まない）
"""
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

ASOFS = ["2025-04-01", "2026-04-01", "2026-11-09", "2027-04-01"]

KW_KOKUHO = ["子ども・子育て支援納付金", "賦課限度額", "基礎賦課額", "後期高齢者支援金等賦課額", "介護納付金賦課額",
             "被保険者均等割", "世帯別平等割", "所得割", "資産割", "六歳に達する日", "十八歳に達する日", "出産",
             "基礎控除", "四十三万円", "世帯主", "百分の七十", "十分の七", "十分の五", "十分の二", "減額",
             "十五万円", "第七百三条の四第六項", "第七百三条の五第一項", "第二十九条の七第二項第四号", "第二十九条の七第六項"]
# 地方税法・同施行令は条文が多いので、国保税に固有の語だけで出現箇所を記録する
KW_CHIHO = ["国民健康保険税", "子ども・子育て支援納付金", "第七百三条の四", "第七百三条の五", "第五十六条の八十八の二",
            "第五十六条の八十九", "十八歳に達する日", "六歳に達する日", "被保険者均等割", "世帯別平等割"]
KW_KOKUNEN = ["保険料改定率", "一万七千", "納付猶予", "五十歳", "学生納付特例", "前年の所得", "扶養親族等",
              "三十五万円", "百二十八万円", "八十八万円", "百六十八万円", "出産", "三十万", "二十二万円", "三十二万円"]

# (略称, law_id, [asof...], [本則の条番号 Num。"__ALL__" は全文], [キーワード])
JOBS = [
    ("kokuho", "333AC0000000192", ASOFS,
     ["4", "5", "6", "9", "72_3_2", "76", "76_2", "76_3", "76_4", "77", "77_2", "78", "81", "81_2", "82_3", "116", "116_2"], KW_KOKUHO),
    ("kokuho-rei", "333CO0000000362", ASOFS, ["27_2", "29_7", "29_7_2", "29_8", "29_9"], KW_KOKUHO),
    ("kokuho-ki", "333M50000100053", ["2026-11-09"], [], KW_KOKUHO),
    ("chiho", "325AC0000000226", ASOFS,
     ["20_4_2", "703_4", "703_5", "703_5_2", "705", "706", "706_2", "313", "314_2"], KW_CHIHO),
    ("chiho-rei", "325CO0000000245", ASOFS, ["6_17", "56_88_2", "56_89"], KW_CHIHO),
    ("kokunen", "334AC0000000141", ASOFS,
     ["7", "36_3", "87", "87_2", "88", "88_2", "88_3", "89", "90", "90_2", "90_3", "93"], KW_KOKUNEN),
    ("kokunen-rei", "334CO0000000184", ASOFS,
     ["5_4", "6_5", "6_6", "6_7", "6_7_2", "6_8", "6_8_2", "6_9", "6_9_2", "6_10", "6_11", "6_12"], KW_KOKUNEN),
    ("kokunen-ki", "335M50000100012", ["2026-11-09"], ["77_2", "77_5"], KW_KOKUNEN),
    ("kaiteiritsu", "417CO0000000092", ASOFS, ["__ALL__"], KW_KOKUNEN),
    ("kaigo", "409AC0000000123", ["2026-11-09"], ["9"], ["第二号被保険者"]),
]

# 附則のうち、名指しで全文を取り出す条：{略称: [(AmendLawNum, 条の Num)]}
SUPPL_ARTS = {
    "kokunen": [("平成一六年六月一一日法律第一〇四号", "19"), ("平成二六年六月一一日法律第六四号", "14")],
    "chiho-rei": [("(原始附則)", "18_8")],
}
# 年代を問わず、次の語を含む附則の条を全文で取り出す（本則の国保料・国保税の規定を附則で読み替えているもの）
SUPPL_ANY_KW = {
    "kokuho-rei": ["第二十九条の七第二項第四号中", "第二十九条の七第六項第一号中", "第二十九条の七第五項第一号中"],
    "chiho": ["第七百三条の四第六項中", "第七百三条の五第一項中", "第七百三条の四の規定の適用", "第七百三条の五の規定の適用"],
    "chiho-rei": ["第五十六条の八十九第一項中"],
}
# 令和の改正法令の附則（施行期日・適用年度）を取り出す条件：{略称: [附則の文に含まれていれば取り出す語]}
# 附則が短い（20,000字未満）ときは附則全体を、長いときは語を含む条と第1条（施行期日）だけを書き出す。
SUPPL_REIWA_KW = {
    "kokuho": ["保険料", "子ども・子育て支援納付金", "国民健康保険法の一部改正"],
    "kokuho-rei": ["保険料"],
    "chiho": ["国民健康保険税"],
    "chiho-rei": ["国民健康保険税"],
    "kokunen": ["保険料"],
    "kokunen-rei": ["保険料", "所得"],
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
                    hits.append({"keyword": kw, **locate(path, n), "snippet": txt[max(0, i - 120): i + 160]})
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
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2X_kokuho_egov"
    dl.mkdir(parents=True, exist_ok=False)
    out = ROOT / "scripts" / "results" / "R2X_kokuho_egov"
    out.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "mode": mode, "download_dir": str(dl.relative_to(ROOT)), "fetches": []}
    art_diffs = {}  # 略称 → 隣り合う asof の間で本則の条の本文が変わった条番号
    for short, law_id, asofs, arts, kws in JOBS:
        prev_texts, prev_asof = None, None
        for asof in (asofs[-2:-1] if (mode == "index" and len(asofs) > 1) else (asofs if mode != "index" else asofs[-1:])):
            url, body, d = fetch_full(law_id, asof, dl)
            ri = d.get("revision_info") or {}
            entry = {"short": short, "law_id": law_id, "asof": asof, "url": url,
                     "law_title": ri.get("law_title"),
                     "law_revision_id": ri.get("law_revision_id"),
                     "amendment_law_num": ri.get("amendment_law_num"),
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
            # 本則の条ごとの本文を前の asof と比べ、変わった条番号を記録する（版の差の一覧）
            texts = {a["attr"].get("Num"): inline(a) for a in main_arts}
            if prev_texts is not None:
                changed = sorted(k for k in set(texts) | set(prev_texts) if texts.get(k) != prev_texts.get(k))
                art_diffs.setdefault(short, []).append({"from": prev_asof, "to": asof, "changed_articles": changed})
            prev_texts, prev_asof = texts, asof
            header = [f"# {short} {law_id} asof={asof}",
                      f"# law_revision_id={ri.get('law_revision_id')} 改正法令={ri.get('amendment_law_num')} 施行日={ri.get('amendment_enforcement_date')} 状態={ri.get('current_revision_status')}",
                      f"# 取得URL={url}", f"# 取得日時={ts}", ""]
            if mode == "index":
                idx = header + [f"{a['attr'].get('Num')}\t{caption_of(a)}" for a in main_arts]
                idx += ["", "# 附則（AmendLawNum）"] + sorted({s.get('attr', {}).get('AmendLawNum', '(原始附則)') for s in suppl})
                (out / f"index_{short}.txt").write_text("\n".join(idx), encoding="utf-8")
                continue
            lines = list(header)
            if arts == ["__ALL__"]:
                render(root, 0, lines)
            else:
                by_num = {a["attr"].get("Num"): a for a in main_arts}
                for num in arts:
                    a = by_num.get(num)
                    if a is None:
                        lines += [f"## Num={num}: 見つからない（この時点の本則にない）", ""]
                        continue
                    lines.append(f"## Num={num}")
                    render(a, 0, lines)
                    lines.append("")
            hits = keyword_hits(root, kws)
            (out / f"keyword_hits_{short}_{asof}.json").write_text(json.dumps(hits, ensure_ascii=False, indent=1), encoding="utf-8")
            # 名指しの附則の条を全文で書き出す（キーワードの出現箇所は keyword_hits_*.json にある）
            sup_arts = {}
            for an, num in SUPPL_ARTS.get(short, []):
                sup_arts.setdefault((an, num), set()).add("(名指し)")
            # 年代を問わず、本則の国保料（税）の条を読み替える附則の条（SUPPL_ANY_KW の語を含むもの）
            for sp in suppl:
                an = sp.get("attr", {}).get("AmendLawNum", "(原始附則)")
                for a in sp.get("children", []):
                    if isinstance(a, dict) and a.get("tag") == "Article":
                        hit = [k for k in SUPPL_ANY_KW.get(short, []) if k in inline(a)]
                        if hit:
                            sup_arts.setdefault((an, a["attr"].get("Num")), set()).update(hit)
            # 令和の改正法令の附則
            rkw = SUPPL_REIWA_KW.get(short)
            if rkw:
                lines.append("# ---- 令和の改正法令の附則（" + "・".join(rkw) + " を含むもの） ----")
                for sp in suppl:
                    an = sp.get("attr", {}).get("AmendLawNum", "")
                    if not an.startswith("令和"):
                        continue
                    whole = inline(sp)
                    if not any(k in whole for k in rkw):
                        continue
                    if len(whole) < 20000:
                        lines.append(f"## 附則 AmendLawNum={an}（全体）")
                        render(sp, 0, lines)
                        lines.append("")
                    else:
                        arts_in = [a for a in sp.get("children", []) if isinstance(a, dict) and a.get("tag") == "Article"]
                        for k, a in enumerate(arts_in):
                            if k == 0 or any(x in inline(a) for x in rkw):
                                lines.append(f"## 附則 AmendLawNum={an} Num={a['attr'].get('Num')}（附則が長いので語を含む条と第1条だけ）")
                                render(a, 0, lines)
                                lines.append("")
            if sup_arts:
                lines.append("# ---- 名指しの附則の条 ----")
                for s in suppl:
                    an = s.get("attr", {}).get("AmendLawNum", "(原始附則)")
                    for a in s.get("children", []):
                        if isinstance(a, dict) and a.get("tag") == "Article" and (an, a["attr"].get("Num")) in sup_arts:
                            lines.append(f"## 附則 AmendLawNum={an} Num={a['attr'].get('Num')} キーワード={sorted(sup_arts[(an, a['attr'].get('Num'))])}")
                            render(a, 0, lines)
                            lines.append("")
            (out / f"articles_{short}_{asof}.txt").write_text("\n".join(lines), encoding="utf-8")
    (out / f"fetch_log_{mode}.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    if mode != "index":
        (out / "article_diffs.json").write_text(json.dumps(art_diffs, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", out)


if __name__ == "__main__":
    main()
