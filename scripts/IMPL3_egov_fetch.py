"""IMPL3 egov: 実装で「一次情報が docs にない」と報告された条文・別表を、e-Gov 法令API v2 で年分・年度の版ごとに取り出す（impl-research3）。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL3_egov_fetch.py fetch
      LAWS の全部（law_id × asof）を /law_data で、REVISIONS を /law_revisions で取得する。
      .work/downloads/<YYYYMMDD-HHMMSS>_IMPL3_egov_fetch/ に置く（新しい空のディレクトリ）。
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL3_egov_fetch.py extract <ダウンロード先> [<ダウンロード先> ...]
      （2026-11-11 の実行：.work/downloads/20261111-231024_IMPL3_egov_fetch と .work/downloads/20261111-232904_IMPL3_egov_fetch。後の方を優先）
      ネットワークを使わず、取得した JSON から条・原始附則の条・別表を取り出す。

- e-Gov の呼び方と条文のテキスト化は scripts/R1_egov_articles.py を写した（import はしない）。原始附則の分け方は
  scripts/R3X_juminzei-extra_laws.py の split、別表の格子は scripts/R2X_genka_laws.py の appdx_grid・fill_grid を写した。
- ダウンロードしたものは信頼できないデータとして新しい空のディレクトリに置き、json.loads で読むだけ。中では何も実行しない。
- 出力 scripts/results/IMPL3_egov_fetch/
    fetch_log_<ts>.json                取得の記録（URL、版、状態、SHA-256、バイト数）
    revisions_<略称>.md                改正の履歴（/law_revisions。施行日・状態・改正法令）
    <topic>/<略称>_<asof>.txt          トピックごとの条文（本則は「Num=」、原始附則は「附則 Num=」）
    <topic>/grep_<略称>_<asof>.txt     トピックごとの語を含む条（本則・原始附則の全条を走査）
    <topic>/appdx_<略称>_<asof>_<n>.json / .tsv  別表（rowspan・colspan を展開した格子）
    sames/<略称>.json                  条ごとの本文の SHA-256 と、版の間で本文が変わった条
- リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。
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
NAME = "IMPL3_egov_fetch"
OUT = ROOT / "scripts" / "results" / NAME

R7, R8 = "2025-12-31", "2026-12-31"          # 所得税：令和7年分・令和8年分の末日の版
FY8, FY9 = "2026-04-01", "2027-04-01"        # 住民税・国保・国年：令和8年度・令和9年度の初日の版
NOW = "2026-11-11"
LAWS = {
    # 2026-01-01・2026-11-30 は源泉徴収税額表（別表第二〜第四）の令和8年中の切替わりを見るため（gensen だけが使う）
    "shoho": ("340AC0000000033", "所得税法", [R7, "2026-01-01", "2026-11-30", R8]),
    "shorei": ("340CO0000000096", "所得税法施行令", [R7, R8]),
    "sochi": ("332AC0000000026", "租税特別措置法", [R7, R8]),
    "sochirei": ("332CO0000000043", "租税特別措置法施行令", [R7, R8]),
    "chiho": ("325AC0000000226", "地方税法", [FY8, FY9]),
    "chihorei": ("325CO0000000245", "地方税法施行令", [FY8, FY9]),
    "kokuho": ("333AC0000000192", "国民健康保険法", [FY8, FY9]),
    "kokuhorei": ("333CO0000000362", "国民健康保険法施行令", [FY8, NOW, FY9]),
    "kokunen": ("334AC0000000141", "国民年金法", [FY8, FY9]),
    "kokunenrei": ("334CO0000000184", "国民年金法施行令", [FY8, FY9]),
    "kokunenki": ("335M50000100012", "国民年金法施行規則", [FY8]),
    "h16kaisei": ("416AC0000000104", "国民年金法等の一部を改正する法律（平成十六年法律第百四号）", [FY8, FY9]),
}
# 改正の履歴（令和9年度の政令が公布されているかを見る）
REVISIONS = ["kokuhorei", "chihorei", "kokunenrei", "kokunen", "kokuho"]

# topic -> {"arts": {略称: [本則の Num]}, "suppl": {略称: [原始附則の Num]}, "grep": {略称: [語]}, "appdx": {略称: [別表の題名の部分]}}
TOPICS = {
    "hikyojusha": {
        "arts": {"shoho": ["2", "5", "7", "22", "85", "161", "164", "165", "166"]},
        "grep": {"shorei": ["非居住者である親族", "国外居住親族"], "shoho": ["非居住者である親族"]},
    },
    "haito": {
        "arts": {"shoho": ["24", "92"], "shorei": ["59"], "sochi": ["9"]},
        "grep": {"sochirei": ["法第九条第", "配当控除"], "shorei": ["配当控除"]},
    },
    "joto-junjo": {
        "arts": {"shoho": ["87", "120", "121"], "sochi": ["8_4", "37_10", "37_11", "37_12_2", "41", "41_2_2"],
                 "sochirei": ["4_2", "25_8", "25_9", "25_11_2"], "shorei": ["204", "205"]},
        "grep": {"sochirei": ["第四十一条の二の二"], "sochi": ["第四十一条の二の二"]},
    },
    "gensen": {
        "arts": {"shoho": ["183", "185", "186", "187", "188", "190"]},
        "appdx": {"shoho": ["別表第二", "別表第三", "別表第四"]},
    },
    "kojo-misc": {
        "arts": {"shorei": ["142", "206", "208_3", "208_4", "208_5", "208_6", "208_7", "209", "210", "210_2", "211", "212"],
                 "shoho": ["51", "72", "76"]},
        "grep": {},
    },
    "juminzei": {
        "arts": {"chiho": ["37_2", "45_2", "45_3", "314_2", "314_7", "317_2", "317_3", "703_4"]},
        "suppl": {"chiho": ["5_5", "5_6", "33_2", "35_2", "35_2_2", "35_4"]},
        "grep": {"chiho": ["第三百十四条の七第二項", "第三百十四条の七第一項第四号", "特例控除対象寄附金", "第三十七条の二第二項"],
                 "chihorei": ["特例控除対象寄附金", "第三百十四条の七第"]},
    },
    "kokuho": {
        "arts": {"kokuho": ["5", "6", "7", "8", "72_3", "72_3_2", "72_3_3", "76", "81"],
                 "kokuhorei": ["29_3", "29_7", "29_7_2", "29_7_3"],
                 "chiho": ["703_4", "703_5"],
                 "chihorei": ["56_88_2", "56_89", "56_89_2"]},
        "grep": {"kokuho": ["月割", "出産"], "kokuhorei": ["月割", "出産", "特定世帯", "特定継続世帯"],
                 "chiho": ["特定世帯", "出産", "月割"], "chihorei": ["特定世帯", "特定継続世帯", "出産被保険者", "月割"]},
    },
    "kokunen": {
        "arts": {"kokunen": ["7", "87", "87_2", "88_2", "88_3", "89", "90", "90_2", "90_3", "94", "94_2"]},
        "grep": {"kokunenrei": ["学生等", "地方税法", "第九十条の二", "第九十条の三", "百三十五万", "納付猶予"],
                 "kokunenki": ["学生等", "第九十条の三", "出産"],
                 "h16kaisei": ["第十九条", "納付することを要しない", "五十歳"]},
        "suppl_all": ["h16kaisei"],
        # 納付猶予：平成16年法律第104号・平成26年法律第64号は /law_data で 404 だったが（2026-11-11 実測）、
        # 国民年金法の本文の中に、その改正附則（AmendLawNum が一致する SupplProvision）として収録されている
        "amend": {"kokunen": {"平成一六年六月一一日法律第一〇四号": ["19"], "平成二六年六月一一日法律第六四号": ["14"]}},
    },
}

BLOCK_LIKE = {"Paragraph", "Item"} | {f"Subitem{i}" for i in range(1, 11)}


def get(url, dest=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            body, st = r.read(), r.status
    except urllib.error.HTTPError as e:
        body, st = e.read(), e.code
    if dest is not None:
        dest.write_bytes(body)
    time.sleep(SLEEP)
    return st, body


# ---- R1_egov_articles.py から写した描画 ----
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


def caption(a):
    for c in a.get("children", []):
        if isinstance(c, dict) and c.get("tag") == "ArticleCaption":
            return inline(c)
    return ""


# ---- R2X_genka_laws.py から写した別表の格子 ----
def appdx_grid(appdx):
    out = {"title": "", "related_article_num": "", "structs": [], "remarks": []}
    for c in appdx.get("children", []):
        if not isinstance(c, dict):
            continue
        t = c.get("tag")
        if t == "AppdxTableTitle":
            out["title"] = inline(c)
        elif t == "RelatedArticleNum":
            out["related_article_num"] = inline(c)
        elif t == "TableStruct":
            st = {"title": "", "rows": [], "remarks": []}
            for x in c.get("children", []):
                if not isinstance(x, dict):
                    continue
                if x.get("tag") == "TableStructTitle":
                    st["title"] = inline(x)
                elif x.get("tag") == "Table":
                    for row in x.get("children", []):
                        if isinstance(row, dict) and row.get("tag") in ("TableRow", "TableHeaderRow"):
                            cells = []
                            for col in row.get("children", []):
                                if isinstance(col, dict):
                                    a = col.get("attr") or {}
                                    cells.append({"text": inline(col).replace("\n", " ").strip(),
                                                  "rowspan": int(a.get("rowspan", 1)), "colspan": int(a.get("colspan", 1))})
                            st["rows"].append(cells)
                elif x.get("tag") == "Remarks":
                    st["remarks"].append(inline(x))
            out["structs"].append(st)
        elif t == "Remarks":
            out["remarks"].append(inline(c))
        else:
            out["remarks"].append(inline(c))
    return out


def fill_grid(rows):
    occupied = {}
    for r, cells in enumerate(rows):
        c = 0
        for cell in cells:
            while (r, c) in occupied:
                c += 1
            for dr in range(cell["rowspan"]):
                for dc in range(cell["colspan"]):
                    occupied[(r + dr, c + dc)] = cell["text"]
            c += cell["colspan"]
    ncols = max((c for (_, c) in occupied), default=-1) + 1
    nrows = max((r for (r, _) in occupied), default=-1) + 1
    return [[occupied.get((r, c), "") for c in range(ncols)] for r in range(nrows)]


def fetch(only=None):
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_{NAME}"
    dl.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "fetches": [], "revisions": []}
    for short, (law_id, name, asofs) in LAWS.items():
        if only and short not in only:
            continue
        for asof in asofs:
            if only and only.get(short) and asof not in only[short]:
                continue
            url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode({"response_format": "json", "asof": asof})
            st, body = get(url, dl / f"{short}_{asof}.json")
            rec = {"short": short, "law_id": law_id, "name": name, "asof": asof, "url": url, "status": st, "bytes": len(body),
                   "sha256": hashlib.sha256(body).hexdigest()}
            if st == 200:
                ri = json.loads(body).get("revision_info") or {}
                rec.update({k: ri.get(k) for k in ("law_revision_id", "law_title", "amendment_law_num", "amendment_enforcement_date",
                                                   "amendment_promulgate_date", "current_revision_status", "updated")})
            log["fetches"].append(rec)
            print(short, asof, st, len(body), rec.get("law_revision_id"), flush=True)
    for short in ([] if only else REVISIONS):
        law_id = LAWS[short][0]
        url = f"{API}/law_revisions/{law_id}?" + urllib.parse.urlencode({"response_format": "json"})
        st, body = get(url, dl / f"revisions_{short}.json")
        log["revisions"].append({"short": short, "law_id": law_id, "url": url, "status": st, "bytes": len(body),
                                 "sha256": hashlib.sha256(body).hexdigest()})
        print("revisions", short, st, len(body), flush=True)
    (OUT / f"fetch_log_{ts}.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("download_dir", dl)


def load(path):
    d = json.loads(path.read_bytes())
    ri = d.get("revision_info") or {}
    main, orig_suppl, appdx = [], [], []

    def fn(n, p):
        if n.get("tag") == "Article" and "SupplProvision" not in p:
            main.append(n)
        if n.get("tag") == "SupplProvision" and not n.get("attr", {}).get("AmendLawNum"):
            walk(n, lambda m, q: orig_suppl.append(m) if m.get("tag") == "Article" else None)
        if n.get("tag") == "AppdxTable" and "SupplProvision" not in p:
            appdx.append(n)
    walk(d["law_full_text"], fn)
    return ri, main, orig_suppl, appdx


def article_text(a):
    lines = []
    render(a, 0, lines)
    return "\n".join(lines)


def revisions_md(dl):
    for short in REVISIONS:
        p = dl / f"revisions_{short}.json"
        if not p.exists():
            continue
        try:
            d = json.loads(p.read_bytes())
        except ValueError:
            continue
        law_id, name, _ = LAWS[short]
        revs = d.get("revisions") or []
        lines = [f"# 改正の履歴 {name} {law_id}（/law_revisions。新しい順に上位40件）", "",
                 "| 施行日 | 状態 | 改正法令 | 公布日 | 改正法令の題名 | law_revision_id |", "|---|---|---|---|---|---|"]
        for r in revs[:40]:
            lines.append(f"| {r.get('amendment_enforcement_date')} | {r.get('current_revision_status')} | {r.get('amendment_law_num')} | "
                         f"{r.get('amendment_promulgate_date')} | {(r.get('amendment_law_title') or '')[:60]} | {r.get('law_revision_id')} |")
        (OUT / f"revisions_{short}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def extract(dls):
    """dls：ダウンロード先の一覧。同じ名前のファイルは後に書いたディレクトリのものを使う。"""
    OUT.mkdir(parents=True, exist_ok=True)

    def find(name):
        hit = [d / name for d in dls if (d / name).exists()]
        return hit[-1] if hit else dls[0] / name
    cache, sames = {}, {}
    for short, (law_id, name, asofs) in LAWS.items():
        for asof in asofs:
            p = find(f"{short}_{asof}.json")
            if not p.exists():
                print("missing", p)
                continue
            try:
                ri, main, osup, appdx = load(p)
            except (ValueError, KeyError) as e:
                print("unreadable", p, e)
                continue
            by_num = {a["attr"].get("Num"): a for a in main}
            sup_by_num = {}
            for a in osup:
                sup_by_num.setdefault(a["attr"].get("Num"), a)
            cache[(short, asof)] = (ri, by_num, sup_by_num, appdx)
            sames.setdefault(short, {})[asof] = {
                **{num: hashlib.sha256(article_text(a).encode("utf-8")).hexdigest() for num, a in by_num.items()},
                **{"附則" + num: hashlib.sha256(article_text(a).encode("utf-8")).hexdigest() for num, a in sup_by_num.items()},
                **{"別表" + appdx_grid(t)["title"][:12]: hashlib.sha256(json.dumps(appdx_grid(t), ensure_ascii=False).encode("utf-8")).hexdigest()
                   for t in appdx}}
    sd = OUT / "sames"
    sd.mkdir(exist_ok=True)
    for short, d in sames.items():
        asofs = sorted(d)
        out = {"asofs": asofs, "changed_between_consecutive": {}}
        for a, b in zip(asofs, asofs[1:]):
            out["changed_between_consecutive"][f"{a}..{b}"] = sorted(n for n in set(d[a]) | set(d[b]) if d[a].get(n) != d[b].get(n))
        (sd / f"{short}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    def header(short, asof, ri):
        law_id, name, _ = LAWS[short]
        return [f"# {name} {law_id} asof={asof}",
                f"# law_revision_id={ri.get('law_revision_id')} 改正法令={ri.get('amendment_law_num')} 施行日={ri.get('amendment_enforcement_date')} "
                f"状態={ri.get('current_revision_status')}",
                f"# 取得URL={API}/law_data/{law_id}?response_format=json&asof={asof}", ""]

    for topic, cfg in TOPICS.items():
        td = OUT / topic
        td.mkdir(exist_ok=True)
        shorts = set(cfg.get("arts", {})) | set(cfg.get("suppl", {})) | set(cfg.get("suppl_all", []))
        for short in sorted(shorts):
            for asof in LAWS[short][2]:
                if (short, asof) not in cache:
                    continue
                ri, by_num, sup_by_num, appdx = cache[(short, asof)]
                lines = header(short, asof, ri)
                for num in cfg.get("arts", {}).get(short, []):
                    a = by_num.get(num)
                    if a is None:
                        lines += [f"## Num={num}: 本則にない", ""]
                        continue
                    lines += [f"## Num={num}", article_text(a), ""]
                sup_nums = list(sup_by_num) if short in cfg.get("suppl_all", []) else cfg.get("suppl", {}).get(short, [])
                for num in sup_nums:
                    a = sup_by_num.get(num)
                    if a is None:
                        lines += [f"## 附則 Num={num}: 原始附則にない", ""]
                        continue
                    lines += [f"## 附則 Num={num}", article_text(a), ""]
                (td / f"{short}_{asof}.txt").write_text("\n".join(lines), encoding="utf-8")
        for short, wanted in cfg.get("amend", {}).items():
            for asof in LAWS[short][2]:
                p = find(f"{short}_{asof}.json")
                if not p.exists():
                    continue
                d = json.loads(p.read_bytes())
                ri = d.get("revision_info") or {}
                lines = header(short, asof, ri) + ["# 改正法令の附則（この法令の本文に収録されているもの）", ""]
                sups = []
                walk(d["law_full_text"], lambda n, q: sups.append(n) if n.get("tag") == "SupplProvision" else None)
                for an, nums in wanted.items():
                    hit = [s for s in sups if (s.get("attr", {}).get("AmendLawNum") or "") == an]
                    lines.append(f"## 改正法令 {an}：SupplProvision {len(hit)} 件")
                    for s in hit:
                        arts = []
                        walk(s, lambda n, q: arts.append(n) if n.get("tag") == "Article" else None)
                        for a in arts:
                            if a["attr"].get("Num") in nums:
                                lines += [f"### 附則 Num={a['attr'].get('Num')}", article_text(a), ""]
                (td / f"amend_{short}_{asof}.txt").write_text("\n".join(lines), encoding="utf-8")
        for short, kws in cfg.get("grep", {}).items():
            for asof in LAWS[short][2]:
                if (short, asof) not in cache:
                    continue
                ri, by_num, sup_by_num, appdx = cache[(short, asof)]
                lines = header(short, asof, ri) + [f"# grep 語={kws}（本則と原始附則の全条）", ""]
                for where, table in (("本則", by_num), ("附則", sup_by_num)):
                    for num, a in table.items():
                        t = article_text(a)
                        hit = [k for k in kws if k in t]
                        if hit:
                            lines += [f"## {where} Num={num} {caption(a)} 当たった語={hit}", t, ""]
                (td / f"grep_{short}_{asof}.txt").write_text("\n".join(lines), encoding="utf-8")
        for short, titles in cfg.get("appdx", {}).items():
            for asof in LAWS[short][2]:
                if (short, asof) not in cache:
                    continue
                ri, by_num, sup_by_num, appdx = cache[(short, asof)]
                for t in appdx:
                    g = appdx_grid(t)
                    key = next((x for x in titles if g["title"].startswith(x) and (g["title"][len(x):len(x) + 1] or "＿") not in "一二三四五六七八九十"), None)
                    if key is None:
                        continue
                    structs = [{"title": s["title"], "rows": fill_grid(s["rows"]), "remarks": s["remarks"]} for s in g["structs"]]
                    obj = {"law": LAWS[short][1], "asof": asof, "law_revision_id": ri.get("law_revision_id"),
                           "title": g["title"], "related_article_num": g["related_article_num"], "structs": structs, "remarks": g["remarks"]}
                    stem = f"appdx_{short}_{asof}_{key}"
                    (td / f"{stem}.json").write_text(json.dumps(obj, ensure_ascii=False, indent=0), encoding="utf-8")
                    tsv = [f"# {g['title']} {g['related_article_num']} asof={asof} {ri.get('law_revision_id')}"]
                    for s in structs:
                        tsv.append(f"## {s['title']}")
                        tsv += ["\t".join(r) for r in s["rows"]]
                        tsv += ["備考：" + x for x in s["remarks"]]
                    tsv += ["備考：" + x for x in g["remarks"]]
                    (td / f"{stem}.tsv").write_text("\n".join(tsv) + "\n", encoding="utf-8")
    revisions_md(find("revisions_kokuho.json").parent)
    print("done", OUT)


LOOKUPS = ["平成十六年法律第百四号", "平成二十六年法律第六十四号"]


def lookup():
    """法令番号で /laws を引き、law_id を記録する（h16kaisei の law_id が 404 だったため。2026-11-11 実測）。"""
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_{NAME}_lookup"
    dl.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    res = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "lookups": []}
    for i, num in enumerate(LOOKUPS):
        url = f"{API}/laws?" + urllib.parse.urlencode({"law_num": num, "response_format": "json"})
        st, body = get(url, dl / f"laws_{i}.json")
        hits = []
        if st == 200:
            for law in json.loads(body).get("laws", []):
                li = law.get("law_info") or {}
                rv = law.get("current_revision_info") or law.get("revision_info") or {}
                hits.append({"law_id": li.get("law_id"), "law_num": li.get("law_num"), "law_title": rv.get("law_title"),
                             "repeal_status": rv.get("repeal_status"), "current_revision_status": rv.get("current_revision_status")})
        res["lookups"].append({"law_num": num, "url": url, "status": st, "hits": hits})
        print(num, st, hits, flush=True)
    (OUT / f"lookup_{ts}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "lookup":
        lookup()
    elif len(sys.argv) >= 2 and sys.argv[1] == "fetch":
        # fetch [略称:asof ...]  … 指定したものだけを取得する（例：shoho:2026-01-01 shoho:2026-11-30）
        only = {}
        for a in sys.argv[2:]:
            k, _, v = a.partition(":")
            only.setdefault(k, []).append(v) if v else only.setdefault(k, [])
        fetch(only or None)
    elif len(sys.argv) >= 3 and sys.argv[1] == "extract":
        extract([pathlib.Path(a) for a in sys.argv[2:]])
    else:
        print(__doc__)
        sys.exit(2)
