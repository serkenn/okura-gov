"""R2B invoice の独立検証（反証役）。

別の担当が作った docs/*/20261109_round2b_invoice-* の数値・条番号・通達・日付・URL を、一次情報に当たり直して確かめる。
元の担当のスクリプト（scripts/R2B_invoice_*.py）とその出力は使わない。条文のテキスト化・文言の検査・例の計算は別の実装で行う。

実行（リポジトリのルートで。Python 3.11.9、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2B_invoice_verify.py egov-probe
      e-Gov 法令API v2：/laws の検索、/law_data の直接取得（平成28年法律第15号）、/law_revisions（消費税法・所得税法施行令）
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2B_invoice_verify.py egov-fetch
      JOBS の法令・時点の本文を取得し、対象の条（本則・附則）を独自の方法でテキストにして egov/<略称>_<asof>.json に書く
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2B_invoice_verify.py nta-fetch
      国税庁のページ（HTML・PDF）を取得し、HTML はタグを除いたテキストを nta/<id>.txt に書く。PDF は記録だけ（Read ツールで読む）
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2B_invoice_verify.py check
      egov/・nta/ のテキストに、文書が引用した文言があるかを検査する（ネットワークなし）。checks.md・checks.json
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2B_invoice_verify.py calc
      推測・実測の例の数値を、元のスクリプトとは別の式（取引の仕訳を積み上げる形）で計算し直す（ネットワークなし）。calc.md・calc.json

- e-Gov API の使い方は scripts/R1_egov_articles.py・scripts/IMPL_kyuyo_fetch.py を読んで写した（import しない）。
- 取得したもの（JSON・HTML・PDF）は信頼できないデータとして、取得ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_R2B_invoice_verify_<mode>/ に置き、その中で何も実行しない。
- リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。個人の情報は送らない。官報は取得しない。
- 結果は scripts/results/R2B_invoice_verify/ に書く。
"""
import hashlib
import html
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "scripts" / "results" / "R2B_invoice_verify"
UA = "okura-gov-research/0.1"
API = "https://laws.e-gov.go.jp/api/2"
WAIT = 1.5

H28 = "平成二八年三月三一日法律第一五号"
R6 = "令和六年三月三〇日法律第八号"
R8 = "令和八年三月三一日法律第一二号"
H30REI = "平成三〇年三月三一日政令第一三一号"

# (略称, law_id, [asof], [本則の条 Num], [附則を取り出す AmendLawNum])
JOBS = [
    ("shohi", "363AC0000000108", ["2025-12-31", "2026-09-30", "2026-11-09", "2027-10-01", "2028-04-01"],
     ["2", "9", "9_2", "19", "28", "30", "36", "42", "44", "45", "57_2"], [H28, R6, R8]),
    ("shotoku-rei", "340CO0000000096", ["2025-12-31", "2026-09-30", "2026-11-09"], ["11_2", "138", "139", "182_2"], [H30REI]),
    ("shotoku", "340AC0000000033", ["2025-12-31", "2026-11-09"], ["2"], []),
    ("sochi", "332AC0000000026", ["2025-12-31", "2026-11-09"], ["86_4"], []),
]

NTA = "https://www.nta.go.jp"
INV = NTA + "/taxes/shiraberu/zeimokubetsu/shohi/keigenzeiritsu/"
NTA_PAGES = {
    "keiri_tsutatsu": NTA + "/law/tsutatsu/kobetsu/shotoku/shinkoku/890329/01.htm",
    "ta6909": NTA + "/taxes/shiraberu/taxanswer/shohi/6909.htm",
    "ta6913": NTA + "/taxes/shiraberu/taxanswer/shohi/6913.htm",
    "ta6501": NTA + "/taxes/shiraberu/taxanswer/shohi/6501.htm",
    "r8_tokushu": INV + "invoice-review/index.htm",
    "nitoku": INV + "invoice_2tokurei.htm",
    "keiri_qa": NTA + "/law/joho-zeikaishaku/hojin/shouhizei_faq/01.htm",
    "ta2100": NTA + "/taxes/shiraberu/taxanswer/shotoku/2100.htm",
    # PDF（Read ツールで読む）
    "r8_leaf": INV + "invoice-review/pdf/0026004-099-01-1.pdf",
    "kojin_oshirase": INV + "pdf/0026004-066_01.pdf",
    "kaisei_oshirase": NTA + "/publication/pamph/shohi/kaisei/pdf/r08kaisei.pdf",
    "kakikata_r7": NTA + "/taxes/shiraberu/shinkoku/tebiki/2025/pdf/034.pdf",
    "aoiro_tebiki_r7": NTA + "/taxes/shiraberu/shinkoku/tebiki/2025/pdf/025.pdf",
    "keiri_kaisei_r03": NTA + "/law/tsutatsu/kobetsu/shotoku/shinkoku/kaisei/2102xx/pdf/01.pdf",
}


# ---------------------------------------------------------------- 共通
def http_get(url, accept=None):
    hd = {"User-Agent": UA}
    if accept:
        hd["Accept"] = accept
    req = urllib.request.Request(url, headers=hd)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            out = (r.status, r.read(), dict(r.headers), r.geturl())
    except urllib.error.HTTPError as e:
        out = (e.code, e.read(), dict(e.headers or {}), url)
    time.sleep(WAIT)
    return out


def new_dl(mode):
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2B_invoice_verify_{mode}"
    dl.mkdir(parents=True, exist_ok=False)
    return ts, dl


def rel(p):
    return str(p.relative_to(ROOT)).replace("\\", "/")


def sha(b):
    return hashlib.sha256(b).hexdigest()


# ---------------------------------------------------------------- e-Gov
def flat(n, out):
    """法令の JSON の木を、項・号の区切りに印をつけた 1 本の文字列にする（元の担当の render とは別の実装）。"""
    if isinstance(n, str):
        out.append(n)
        return
    tag = n.get("tag", "")
    if tag == "Rt":
        return
    if tag == "Paragraph":
        out.append(f"\n〔第{n.get('attr', {}).get('Num', '?')}項〕")
    elif tag == "Item" or tag.startswith("Subitem"):
        out.append("\n")
    elif tag == "Column":
        out.append("　")
    elif tag in ("ArticleCaption", "ArticleTitle"):
        out.append("\n")
    for c in n.get("children", []):
        flat(c, out)


def text_of(n):
    out = []
    flat(n, out)
    return re.sub(r"[ \u3000]{2,}", "　", "".join(out)).strip()


def iter_nodes(n, path=()):
    if isinstance(n, dict):
        yield n, path
        for c in n.get("children", []):
            yield from iter_nodes(c, path + (n,))


def egov_probe():
    ts, dl = new_dl("egov-probe")
    res = {"run_at": ts, "download_dir": rel(dl), "items": []}
    reqs = [
        ("laws_title_shohi", f"{API}/laws?" + urllib.parse.urlencode({"response_format": "json", "law_title": "消費税法"})),
        ("laws_num_h28_15", f"{API}/laws?" + urllib.parse.urlencode({"response_format": "json", "law_num": "平成二十八年法律第十五号"})),
        ("laws_num_r8_12", f"{API}/laws?" + urllib.parse.urlencode({"response_format": "json", "law_num": "令和八年法律第十二号"})),
        ("laws_num_r5_3", f"{API}/laws?" + urllib.parse.urlencode({"response_format": "json", "law_num": "令和五年法律第三号"})),
        ("laws_title_kaisei", f"{API}/laws?" + urllib.parse.urlencode({"response_format": "json", "law_title": "所得税法等の一部を改正する法律"})),
        ("law_data_428AC0000000015", f"{API}/law_data/428AC0000000015?response_format=json"),
        ("revisions_shohi", f"{API}/law_revisions/363AC0000000108?" + urllib.parse.urlencode({"response_format": "json", "amendment_date_from": "2023-01-01"})),
        ("revisions_shotoku-rei_all", f"{API}/law_revisions/340CO0000000096?response_format=json"),
    ]
    for key, url in reqs:
        st, body, hd, _ = http_get(url, "application/json")
        (dl / f"{key}.json").write_bytes(body)
        ent = {"key": key, "url": url, "status": st, "bytes": len(body), "sha256": sha(body)}
        try:
            d = json.loads(body)
        except Exception:  # noqa
            d = None
            ent["body_head"] = body[:300].decode("utf-8", "replace")
        if d is not None and key.startswith("laws_"):
            ent["total_count"] = d.get("total_count")
            ent["laws"] = []
            for lw in d.get("laws", []):
                li = lw.get("law_info") or {}
                ri = lw.get("revision_info") or lw.get("current_revision_info") or {}
                ent["laws"].append({"law_id": li.get("law_id"), "law_num": li.get("law_num"), "law_type": li.get("law_type"),
                                    "law_title": ri.get("law_title"), "law_revision_id": ri.get("law_revision_id"),
                                    "current_revision_status": ri.get("current_revision_status")})
        elif d is not None and key.startswith("revisions_"):
            revs = d.get("revisions", [])
            ent["n"] = len(revs)
            keep = ("law_revision_id", "amendment_promulgate_date", "amendment_enforcement_date", "amendment_law_title",
                    "amendment_law_num", "current_revision_status")
            ent["revisions"] = [{k: rv.get(k) for k in keep} for rv in revs]
        elif d is not None:
            ent["message"] = d.get("message") if isinstance(d, dict) else None
        res["items"].append(ent)
        print(key, st, ent.get("total_count", ent.get("n")), flush=True)
    (OUT / "egov_probe.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


def egov_fetch():
    ts, dl = new_dl("egov-fetch")
    (OUT / "egov").mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": rel(dl), "fetches": []}
    for short, law_id, asofs, mains, amends in JOBS:
        for asof in asofs:
            url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode({"response_format": "json", "asof": asof})
            d = None
            for attempt in range(4):
                st, body, _, _ = http_get(url, "application/json")
                (dl / f"{law_id}_{asof}_{attempt}.json").write_bytes(body)
                if st == 200 and body.lstrip()[:1] == b"{":
                    try:
                        d = json.loads(body)
                        break
                    except json.JSONDecodeError:
                        pass
                time.sleep(5)
            if d is None:
                raise RuntimeError(f"取得できない: {url} {st}")
            ri = d.get("revision_info") or {}
            meta = {"short": short, "law_id": law_id, "asof": asof, "url": url, "law_title": ri.get("law_title"),
                    "law_revision_id": ri.get("law_revision_id"), "amendment_law_num": ri.get("amendment_law_num"),
                    "amendment_enforcement_date": ri.get("amendment_enforcement_date"),
                    "current_revision_status": ri.get("current_revision_status"), "sha256": sha(body), "bytes": len(body)}
            log["fetches"].append(meta)
            arts = {}
            suppl_nums = {}
            for node, path in iter_nodes(d["law_full_text"]):
                if node.get("tag") != "Article":
                    continue
                sp = [p for p in path if p.get("tag") == "SupplProvision"]
                num = (node.get("attr") or {}).get("Num")
                if not sp:
                    if num in mains:
                        arts[f"本則:{num}"] = text_of(node)
                else:
                    an = (sp[-1].get("attr") or {}).get("AmendLawNum", "原始附則")
                    suppl_nums.setdefault(an, 0)
                    suppl_nums[an] += 1
                    if an in amends:
                        arts[f"附則:{an}:{num}"] = text_of(node)
            (OUT / "egov" / f"{short}_{asof}.json").write_text(
                json.dumps({"meta": meta, "suppl_article_counts": suppl_nums, "articles": arts}, ensure_ascii=False, indent=1),
                encoding="utf-8")
            print("ok", short, asof, ri.get("law_revision_id"), len(arts), flush=True)
    (OUT / "egov_fetch_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- 国税庁
def html_to_text(raw):
    """タグを正規表現で除くだけの、元の担当とは別の簡単なテキスト化。img の alt は〔alt:…〕で残す。"""
    t = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", raw)
    t = re.sub(r'(?is)<img\b[^>]*\balt="([^"]*)"[^>]*>', lambda m: f"〔alt:{m.group(1)}〕", t)
    t = re.sub(r"(?is)<br\s*/?>|</(p|div|li|tr|h[1-6]|dt|dd|table)>", "\n", t)
    t = re.sub(r"(?s)<[^>]+>", "", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t\r\u3000]+\n", "\n", t)
    t = re.sub(r"\n[ \t\u3000]+", "\n", t)
    return re.sub(r"\n{2,}", "\n", t).strip()


def decode(body):
    m = re.search(rb'charset=["\']?([A-Za-z0-9_\-]+)', body[:3000])
    enc = (m.group(1).decode().lower() if m else "utf-8")
    if enc in ("shift_jis", "sjis", "x-sjis"):
        enc = "cp932"
    try:
        return body.decode(enc)
    except (UnicodeDecodeError, LookupError):
        return body.decode("utf-8", "replace")


def nta_fetch():
    ts, dl = new_dl("nta-fetch")
    (OUT / "nta").mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": rel(dl), "items": []}
    for key, url in NTA_PAGES.items():
        st, body, hd, final = http_get(url)
        is_pdf = url.lower().endswith(".pdf")
        fn = dl / (key + (".pdf" if is_pdf else ".htm"))
        fn.write_bytes(body)
        item = {"id": key, "url": url, "final_url": final, "status": st, "last_modified": hd.get("Last-Modified"),
                "content_type": hd.get("Content-Type"), "bytes": len(body), "sha256": sha(body), "saved": rel(fn)}
        if is_pdf:
            item["pdf_magic"] = body[:5] == b"%PDF-"
        elif st == 200:
            txt = html_to_text(decode(body))
            (OUT / "nta" / f"{key}.txt").write_text(f"# url={url}\n# final_url={final}\n# fetched_at={ts}\n"
                                                    f"# last_modified={hd.get('Last-Modified')}\n# sha256={item['sha256']}\n\n{txt}\n",
                                                    encoding="utf-8")
        log["items"].append(item)
        print(key, st, hd.get("Last-Modified"), len(body), flush=True)
    (OUT / "nta_fetch_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- 文言の検査
# (id, 略称, 条のキー, 文言, {asof: 期待(True/False/None)} か None（観察だけ）)
_S = ["2025-12-31", "2026-09-30", "2026-11-09", "2027-10-01", "2028-04-01"]


def _e(*vals):
    """消費税法の 5 時点の期待値。"""
    return dict(zip(_S, vals))


T5 = _e(True, True, True, True, True)
NEW = _e(False, False, True, True, True)      # R8改正の施行（2026-10-01）以後に現れる文言
OLD = _e(True, True, False, False, False)     # R8改正前だけの文言
ABS = _e(None, None, True, True, True)        # 2026-10-01 前には条が無い
H = "附則:" + H28 + ":"
R8A = "附則:" + R8 + ":"
R6A = "附則:" + R6 + ":"
PRE28 = _e(True, True, True, True, False)     # 2028-04-01 の版で変わる文言
EGOV_CHECKS = [
    # PS §1
    ("L01", "shohi", "本則:9", "千万円以下である者（適格請求書発行事業者を除く。）については、第五条第一項の規定にかかわらず", PRE28),
    ("L02", "shohi", "本則:9", "（適格請求書発行事業者及び特定少額資産販売事業者を除く。）", _e(False, False, False, False, True)),
    ("L03", "shohi", "本則:9", "第二十八条第一項に規定する対価の額をいう", T5),
    ("L04", "shohi", "本則:9", "同項に規定する翌課税期間の初日から二年を経過する日の属する課税期間の初日以後でなければ", T5),
    ("L05", "shohi", "本則:2", "基準期間　個人事業者についてはその年の前々年をいい", T5),
    ("L06", "shohi", "本則:2", "適格請求書発行事業者　第五十七条の二第一項の規定による登録を受けた事業者をいう。", T5),
    ("L07", "shohi", "本則:2", "特定少額資産販売事業者　第五十七条の七第一項の規定による登録を受けた事業者をいう。", _e(False, False, False, False, True)),
    ("L08", "shohi", "本則:9_2", "個人事業者　その年の前年一月一日から六月三十日までの期間", T5),
    ("L09", "shohi", "本則:9_2", "国外事業者以外の事業者が第一項の規定を適用する場合", T5),
    ("L10", "shohi", "本則:9_2", "給与等の金額に相当するものとして財務省令で定めるものの合計額をもつて", T5),
    ("L11", "shohi", "本則:19", "一月一日から十二月三十一日までの期間", T5),
    ("L12", "shohi", "本則:19", "第一号に定める期間を一月ごとの期間に短縮すること", T5),
    ("L13", "shohi", "本則:57_2", "第九条第一項本文の規定により消費税を納める義務が免除される事業者を除く。）は、税務署長の登録を受けることができる。", T5),
    ("L14", "shohi", "本則:57_2", "その提出があつた日の属する課税期間の末日の翌日（その提出が政令で定める日の翌日から当該課税期間の末日までの間にされた場合には、当該課税期間の翌課税期間の末日の翌日）", T5),
    ("L15", "shohi", H + "44", "登録開始日が五年施行日から五年施行日以後六年を経過する日までの日の属する課税期間中である事業者に限る。", T5),
    ("L16", "shohi", H + "44", "当該登録開始日から当該課税期間の末日までの間における課税資産の譲渡等及び特定課税仕入れについては、消費税法第九条第一項本文の規定は、適用しない。", PRE28),  # 2028-04-01 の版は「同法第九条」
    ("L17", "shohi", H + "44", "登録開始日以後二年を経過する日の属する課税期間までの各課税期間", T5),
    ("L18", "shohi", H + "44", "ただし、登録開始日の属する課税期間が五年施行日を含む課税期間である場合は、この限りでない。", T5),
    ("L19", "shohi", H + "1", "九　次に掲げる規定　令和五年十月一日", T5),
    ("L20", "shohi", H + "32", "附則第一条第九号に定める日（以下附則第五十三条の二までにおいて「五年施行日」という。）", T5),
    ("L21", "shohi", H + "1", "八　附則第四十四条及び第四十五条の規定　令和三年十月一日", T5),
    # PS §2
    ("L22", "shohi", H + "51_2", "五年施行日から五年施行日以後三年を経過する日までの日の属する課税期間", T5),
    ("L23", "shohi", H + "51_2", "残額の百分の八十に相当する金額", T5),
    ("L24", "shohi", H + "51_2", "消費税法第十九条第一項第三号から第四号の二までの規定の適用を受ける課税期間", T5),
    ("L25", "shohi", H + "51_2", "登録開始日の前日までに消費税法第十条第一項の相続があったことにより", T5),
    ("L26", "shohi", H + "51_2", "申告書（当該申告書に係る国税通則法第十八条第二項に規定する期限後申告書を含む。）にその旨を付記するものとする", T5),
    ("L27", "shohi", H + "51_2", "翌課税期間（以下この項において「特例対象課税期間」という。）に係る同法第四十五条第一項の規定による申告書の提出期限までに", NEW),
    ("L28", "shohi", H + "51_3", "個人事業者である適格請求書発行事業者の令和九年及び令和十年に含まれる各課税期間", ABS),
    ("L29", "shohi", H + "51_3", "残額の百分の七十に相当する金額", ABS),
    ("L30", "shohi", H + "51_3", "特例対象課税期間", ABS),
    ("L31", "shohi", H + "1", "九の二　附則第五十一条の三の規定　令和八年十月一日", NEW),
    ("L32", "shohi", R8A + "1", "附則第四十四条の改正規定を除く。）及び附則第九十条の規定　令和八年十月一日", _e(None, True, True, True, True)),
    ("L33", "shohi", R8A + "1", "九　次に掲げる規定　令和十年四月一日", _e(None, True, True, True, True)),
    ("L34", "shohi", R8A + "90", "令和八年十月一日以後に終了する特例対象課税期間", ABS),
    ("L35", "shohi", R8A + "90", "令和八年十月一日から令和十年三月三十一日までの間における新二十八年改正法附則第五十一条の三第一項及び第二項の規定の適用については", ABS),
    ("L36", "shohi", R8A + "90", "令和八年十月一日以後に開始する課税期間", ABS),
    # PS §3
    ("L37", "shohi", H + "52", "五年施行日から五年施行日以後三年を経過する日（同条第一項において「適用期限」という。）までの間に国内において行った課税仕入れ", T5),
    ("L38", "shohi", H + "52", "百十分の七・八", T5),
    ("L39", "shohi", H + "52", "百八分の六・二四）を乗じて算出した金額に百分の八十を乗じて算出した金額", T5),
    ("L40", "shohi", H + "52", "一の者から行う当該課税仕入れに係る支払対価の額", NEW),
    ("L41", "shohi", H + "52", "合計額が一億円を超える場合における当該超える部分の課税仕入れを除く", NEW),
    ("L42", "shohi", H + "52", "一の事業者から行う当該課税仕入れに係る支払対価の額", OLD),
    ("L43", "shohi", H + "52", "合計額が十億円を超える場合における当該超える部分の課税仕入れを除く", OLD),
    ("L44", "shohi", H + "52", "附則第五十二条第一項の規定の適用を受ける課税仕入れである旨", T5),
    ("L45", "shohi", H + "53", "適用期限の翌日から令和十三年九月三十日までの間に国内において行った控除対象課税仕入れ", NEW),
    ("L46", "shohi", H + "53", "一　適用期限の翌日から令和十年九月三十日までの間に行った控除対象課税仕入れ　百分の七十", NEW),
    ("L47", "shohi", H + "53", "二　令和十年十月一日から令和十二年九月三十日までの間に行った控除対象課税仕入れ　百分の五十", NEW),
    ("L48", "shohi", H + "53", "三　令和十二年十月一日から令和十三年九月三十日までの間に行った控除対象課税仕入れ　百分の三十", NEW),
    ("L49", "shohi", H + "53", "適用期限の翌日から同日以後三年を経過する日までの間に国内において行った控除対象課税仕入れ", OLD),
    ("L50", "shohi", H + "53", "を乗じて算出した金額に百分の五十を乗じて算出した金額", OLD),
    ("L51", "shohi", H + "53", "令和十一年九月三十日", _e(False, False, False, False, False)),
    ("L52", "shohi", H + "53_2", "五年施行日から五年施行日以後六年を経過する日までの間に国内において行う課税仕入れ", T5),
    ("L53", "shohi", H + "53_2", "課税売上高が一億円以下である課税期間又はその特定期間における課税売上高", T5),
    ("L54", "shohi", H + "53_2", "が五千万円以下である課税期間に行うものに限る", T5),
    ("L55", "shohi", H + "53_2", "支払対価の額が少額である場合として政令で定める場合", T5),
    # 一の者 10 億円の適用開始（反証で追加：R6改正法附則第63条）
    ("L56", "shohi", R6A + "63", "附則第五十一条の二第一項及び第五十二条の規定は、令和六年十月一日以後に開始する課税期間", T5),
    # PS §4
    ("L57", "shohi", "本則:45", "課税期間ごとに、当該課税期間の末日の翌日から二月以内に", T5),
    ("L58", "shohi", "本則:42", "ただし、第一号に掲げる金額が二十四万円以下である場合", T5),
    ("L59", "shohi", "本則:42", "直前の課税期間の確定申告書に記載すべき第四十五条第一項第四号に掲げる消費税額で当該六月中間申告対象期間の末日までに確定したものを当該直前の課税期間の月数で除し、これに六を乗じて計算した金額", T5),
    ("L60", "shohi", "本則:44", "その提出期限において、税務署長に同条第一項各号、第四項各号又は第六項各号に掲げる事項を記載した中間申告書の提出があつたものとみなす", T5),
    ("L61", "sochi", "本則:86_4", "その年の十二月三十一日の属する課税期間", {"2025-12-31": True, "2026-11-09": True}),
    ("L62", "sochi", "本則:86_4", "その年の翌年三月三十一日とする", {"2025-12-31": True, "2026-11-09": True}),
    # PS §6
    ("L63", "shohi", "本則:30", "課税売上高が五億円を超えるとき、又は当該課税期間における課税売上割合が百分の九十五に満たないとき", T5),
    ("L64", "shohi", "本則:36", "第九条第一項本文の規定により消費税を納める義務が免除されることとなつた場合", T5),
    ("L65", "shotoku-rei", "本則:182_2", "課税売上割合に準ずる割合として財務省令で定めるところにより計算した割合が百分の八十以上である年に限る", {"2025-12-31": True, "2026-09-30": True, "2026-11-09": True}),
    ("L66", "shotoku-rei", "本則:182_2", "二十万円未満である場合", {"2025-12-31": True, "2026-09-30": True, "2026-11-09": True}),
    ("L67", "shotoku-rei", "本則:182_2", "六十で除しこれにその年において当該業務を行つていた期間の月数を乗じて計算した金額の二分の一に相当する金額", {"2025-12-31": True, "2026-09-30": True, "2026-11-09": True}),
    ("L68", "shotoku-rei", "本則:182_2", "必要経費に算入される金額の計算に関する明細書を添付しなければならない", {"2025-12-31": True, "2026-09-30": True, "2026-11-09": True}),
    ("L69", "shotoku-rei", "本則:182_2", "消費税に関する法令の規定の例により計算した場合", {"2025-12-31": True, "2026-09-30": True, "2026-11-09": True}),
    ("L70", "shotoku-rei", "附則:" + H30REI + ":11", "附則第五十二条第一項（適格請求書発行事業者以外の者から行った課税仕入れに係る税額控除に関する経過措置）", {"2025-12-31": True, "2026-09-30": True, "2026-11-09": True}),
    ("L71", "shotoku-rei", "附則:" + H30REI + ":11", "附則第五十三条第一項（適格請求書発行事業者以外の者から行った課税仕入れに係る税額控除に関する経過措置）", {"2025-12-31": True, "2026-09-30": True, "2026-11-09": True}),
    ("L72", "shotoku-rei", "附則:" + H30REI + ":11", "百分の八十", {"2025-12-31": False, "2026-09-30": False, "2026-11-09": False}),
    ("L73", "shotoku-rei", "附則:" + H30REI + ":11", "百分の七十", {"2025-12-31": False, "2026-09-30": False, "2026-11-09": False}),
    # 仮説が使う所得税の要件（H5・推測 I1）
    ("L74", "shotoku", "本則:2", "のうち、合計所得金額が五十八万円以下である者をいう。", {"2025-12-31": True, "2026-11-09": True}),
    ("L75", "shotoku", "本則:2", "自己の勤労に基づいて得た事業所得、給与所得、退職所得又は雑所得（以下この号において「給与所得等」という。）を有するもののうち", {"2025-12-31": True, "2026-11-09": True}),
    ("L76", "shotoku", "本則:2", "合計所得金額のうち給与所得等以外の所得に係る部分の金額が十万円以下であるもの", {"2025-12-31": True, "2026-11-09": True}),
    ("L77", "shotoku", "本則:2", "ロ 合計所得金額が五百万円以下であること。", {"2025-12-31": True, "2026-11-09": True}),
    ("L78", "shotoku-rei", "本則:11_2", "その年分の総所得金額、退職所得金額及び山林所得金額の合計額が五十八万円以下の子", {"2025-12-31": True, "2026-09-30": True, "2026-11-09": True}),
    ("L79", "shotoku-rei", "本則:138", "十万円未満", {"2025-12-31": True, "2026-09-30": True, "2026-11-09": True}),
    ("L80", "shotoku-rei", "本則:139", "二十万円未満", {"2025-12-31": True, "2026-09-30": True, "2026-11-09": True}),
]

# (id, ページ id, 文言, 期待)
NTA_CHECKS = [
    ("N01", "keiri_tsutatsu", "（改正　令和５.12.27課個2-40）", True),
    ("N02", "keiri_tsutatsu", "令和８.", False),
    ("N03", "keiri_tsutatsu", "直所3-8（例規）", True),
    ("N04", "keiri_tsutatsu", "（5）　消費税等　消費税及び地方消費税をいう。", True),
    ("N05", "keiri_tsutatsu", "（7）　税抜経理方式　消費税等の額とこれに係る取引の対価の額とを区分して経理をする方式をいう。", True),
    ("N06", "keiri_tsutatsu", "（8）　税込経理方式　消費税等の額とこれに係る取引の対価の額とを区分しないで経理をする方式をいう。", True),
    ("N07", "keiri_tsutatsu", "（14）　控除対象外消費税額等　令第182条の２第５項", True),
    ("N08", "keiri_tsutatsu", "（当該金額に１円未満の端数が生じたときは、当該端数を切り捨て、又は四捨五入した後の金額）を当該課税仕入れに係る取引の対価の額と区分して経理をしているときは、継続適用を条件として、当該金額を仮払消費税等の額とすることができる。", True),
    ("N09", "keiri_tsutatsu", "当該所得の種類を異にする業務ごとに上記の取扱いによることができるものとする。", True),
    ("N10", "keiri_tsutatsu", "消費税と地方消費税は同一の方式によるものとする。", True),
    ("N11", "keiri_tsutatsu", "のいずれか一方の取引について税込経理方式を適用できるほか", True),
    ("N12", "keiri_tsutatsu", "個々の固定資産等又は個々の経費等ごとに異なる方式を適用しない。", True),
    ("N13", "keiri_tsutatsu", "税込経理方式を適用して所得税の課税所得金額を計算することに留意する。", True),
    ("N14", "keiri_tsutatsu", "その経理処理をその年12月31日において一括して行うことができるものとする。", True),
    ("N15", "keiri_tsutatsu", "消法第９条第１項本文((小規模事業者に係る納税義務の免除))の規定により消費税を納める義務が免除される個人事業者については、その行う取引について税抜経理方式で経理をしている場合であっても", True),
    ("N16", "keiri_tsutatsu", "当該差額については、当該課税期間を含む年の事業所得等の金額の計算上、総収入金額又は必要経費に算入するものとする。", True),
    ("N17", "keiri_tsutatsu", "納税申告書に記載された税額については当該納税申告書が提出された日の属する年の事業所得等の金額の計算上、必要経費に算入し", True),
    ("N18", "keiri_tsutatsu", "申告期限未到来の当該納税申告書に記載すべき消費税等の額を未払金に計上したときの当該金額については、当該未払金に計上した年の事業所得等の金額の計算上、必要経費に算入することとして差し支えない。", True),
    ("N19", "keiri_tsutatsu", "申告期限未到来の当該納税申告書に記載すべき消費税等の額を未収入金に計上したときの当該金額については、当該未収入金に計上した年の事業所得等の金額の計算上、総収入金額に算入することとして差し支えない。", True),
    ("N20", "keiri_tsutatsu", "その適用することとなる方式により算定した取得価額又は支出する金額により判定することに留意する。", True),
    ("N21", "keiri_tsutatsu", "前払費用（一定の契約に基づき継続的に役務の提供を受けるために支出した費用のうちその年12月31日においてまだ提供を受けていない役務に対応するものをいう。）は含まれない", True),
    ("N22", "keiri_tsutatsu", "その取引の対価の額と区分して経理をした消費税等の額に相当する金額を当該課税仕入れに係る取引の対価の額に含めて所得税の課税所得金額を計算することに留意する。", True),
    ("N23", "keiri_tsutatsu", "消法第36条第５項", True),
    ("N24", "keiri_tsutatsu", "附則第51条の２第１項((適格請求書発行事業者となる小規模事業者に係る税額控除に関する経過措置))の規定の適用を受ける課税期間を含む年において", True),
    ("N25", "keiri_tsutatsu", "(1) 令和５年10月１日から令和８年９月30日までの間に国内において行った課税仕入れ", True),
    ("N26", "keiri_tsutatsu", "(2) 令和８年10月１日から令和11年９月30日までの間に国内において行った課税仕入れ", True),
    ("N27", "keiri_tsutatsu", "（当該課税仕入れに係る支払対価の額が１万円未満であるものに限る。）", True),
    ("N28", "keiri_tsutatsu", "仮払消費税等の額はないものとすることができる。", True),
    ("N29", "keiri_tsutatsu", "附則第51条の３", False),
    ("N30", "ta6909", "[令和8年4月1日現在法令等]", True),
    ("N31", "ta6909", "免税事業者は、税込経理方式を適用しなければなりませんので、次の場合であっても、税抜経理方式と税込経理方式を併用することはできません。", True),
    ("N32", "ta6909", "消費税法等の施行に伴う所得税の取扱いについて（平元.3.29直所3-8外）", True),
    ("N33", "ta6913", "個人事業者においては、その課税期間を含む年の総収入金額に算入", True),
    ("N34", "ta6501", "課税期間の基準期間における課税売上高が1,000万円以下であっても、適格請求書発行事業者の登録を受けている場合には、納税義務は免除されません。", True),
    ("N35", "ta6501", "免税事業者が課税期間の途中で適格請求書発行事業者の登録を受けた場合には、その登録日以後に行った課税資産の譲渡等が消費税の申告の対象となる経過措置", True),
    ("N36", "ta6501", "特定期間における1,000万円の判定は、課税売上高に代えて、給与等支払額の合計額により判定することができます。いずれの基準で判定するかは納税者の任意です。", True),
    ("N37", "ta6501", "令和9年4月1日から令和11年3月31日までの2年間、飲食料品の譲渡について、消費税率が引き下げられます。", True),
    ("N38", "r8_tokushu", "控除可能割合は令和8年10月から2年間70％、令和10年10月から2年間50％、令和12年10月から1年間30％となり、令和13年10月以降は0％となる。改正前は令和8年10月から3年間50％で、その後0％となる予定だった。", True),
    ("N39", "r8_tokushu", "登録の柔軟化は令和11年9月30日が属する課税期間中まで", True),
    ("N40", "r8_tokushu", "法人は3割特例適用不可", True),
    ("N41", "nitoku", "令和５年10月１日から令和８年９月30日までの日の属する課税期間において適用できます。", True),
    ("N42", "nitoku", "令和５年分（10月～12月）", True),
    ("N43", "keiri_qa", "令和3年改正消費税経理通達関係Q＆A（令和3年2月）", True),
    ("N44", "keiri_qa", "についても、同様の改正の趣旨となります。", True),
    ("N45", "keiri_qa", "令和８年10月１日から令和11年９月30日までの間に行われた課税仕入れ", True),
]


def load_egov():
    data = {}
    for p in sorted((OUT / "egov").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        data[(d["meta"]["short"], d["meta"]["asof"])] = d
    return data


def norm(s):
    return re.sub(r"\s+", "", s)


def check():
    data = load_egov()
    rows = []
    for cid, short, key, phrase, expect in EGOV_CHECKS:
        got = {}
        for (s, asof), d in sorted(data.items()):
            if s != short:
                continue
            body = d["articles"].get(key)
            got[asof] = None if body is None else (norm(phrase) in norm(body))
        ok = None
        if expect is not None:
            ok = all(got.get(a) == v for a, v in expect.items())
        rows.append({"id": cid, "src": f"{short} {key}", "phrase": phrase, "got": got, "expect": expect, "ok": ok})
    nta = {}
    for p in (OUT / "nta").glob("*.txt"):
        nta[p.stem] = p.read_text(encoding="utf-8")
    for cid, key, phrase, expect in NTA_CHECKS:
        body = nta.get(key)
        got = None if body is None else (norm(phrase) in norm(body))
        rows.append({"id": cid, "src": f"nta {key}", "phrase": phrase, "got": got, "expect": expect, "ok": got == expect})
    (OUT / "checks.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["# R2B invoice 独立検証：文言の検査", "", "got：時点ごとに、その条（またはページ）にその文言があるか（None＝その時点に条が無い）。"
          "expect と一致すれば ok=True。", "", "| id | 出典 | 文言 | got | ok |", "|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['id']} | {r['src']} | {r['phrase'][:90]} | {json.dumps(r['got'], ensure_ascii=False)} | {r['ok']} |")
    nbad = sum(1 for r in rows if r["ok"] is False)
    md += ["", f"- 検査 {len(rows)} 件、不一致 {nbad} 件"]
    (OUT / "checks.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md[-3:]))
    for r in rows:
        if r["ok"] is False:
            print("NG", r["id"], r["src"], r["phrase"][:60], r["got"])


# ---------------------------------------------------------------- 例の再計算
def calc():
    """仕訳（借方・貸方）を積み上げて、年ごとの事業所得等を出す。元の担当の式（売上−経費−納付）は使わない。"""
    from fractions import Fraction as F

    def ledger_income(entries, year):
        # entries: (年, 勘定, 金額)。収益は +、費用は −。所得＝その年の収益と費用の合計。
        return sum(a for y, acct, a in entries if y == year and acct in ("売上", "雑収入", "経費", "租税公課", "雑損", "減価償却費"))

    def build(method, year_rows, returns, accrue):
        """method: 'komi' | 'nuki'。year_rows[y] = [(種類, 税込の額, 仮受/仮払として区分する額)]。
        returns: [(課税期間の年, 申告書を出した年, 納付すべき額(還付は負))]"""
        e = []
        for y, rows in year_rows.items():
            kariuke = karibarai = 0
            for kind, incl, tax_part in rows:
                if method == "komi":
                    e.append((y, "売上" if kind == "sale" else "経費", incl if kind == "sale" else -incl))
                else:
                    if kind == "sale":
                        e.append((y, "売上", incl - tax_part))
                        kariuke += tax_part
                    else:
                        e.append((y, "経費", -(incl - tax_part)))
                        karibarai += tax_part
            if method == "nuki":
                due = sum(a for py, fy, a in returns if py == y)
                diff = (kariuke - karibarai) - due  # 経理通達 6：差額を課税期間を含む年に
                e.append((y, "雑収入" if diff >= 0 else "雑損", diff))
        if method == "komi":
            for py, fy, a in returns:
                y = py if accrue else fy  # 経理通達 7・8
                e.append((y, "租税公課" if a >= 0 else "雑収入", -a))
        return e

    out = {}
    # 基本の例（実測 §6）
    rows = {2025: [("sale", 1_100_000, 100_000), ("cost", 330_000, 30_000)],
            2026: [("sale", 1_100_000, 100_000), ("cost", 330_000, 30_000)], 2027: []}
    ret = [(2025, 2026, 20_000), (2026, 2027, 20_000)]
    out["basic"] = {name: {y: ledger_income(build(m, rows, ret, acc), y) for y in (2025, 2026, 2027)}
                    for name, m, acc in (("komi_filed", "komi", False), ("komi_accrued", "komi", True), ("nuki", "nuki", None))}
    out["basic"]["menzei"] = {y: ledger_income(build("komi", rows, [], False), y) for y in (2025, 2026, 2027)}
    # 推測 I1
    rows = {2025: [("sale", 660_000, 60_000), ("cost", 77_000, 7_000)], 2026: []}
    ret = [(2025, 2026, 12_000)]
    out["I1"] = {name: ledger_income(build(m, rows, r, acc), 2025)
                 for name, m, r, acc in (("komi_filed", "komi", ret, False), ("komi_accrued", "komi", ret, True),
                                         ("nuki", "nuki", ret, None), ("menzei", "komi", [], False))}
    out["I1_limit"] = 580_000
    out["I1_within"] = {k: v <= 580_000 for k, v in out["I1"].items()}
    # 仮払の区分額を変える例
    out["partial"] = {}
    for kb in (10_000, 8_000, 7_000, 0):
        rows = {2026: [("sale", 1_100_000, 100_000), ("cost", 110_000, kb)]}
        out["partial"][kb] = ledger_income(build("nuki", rows, [(2026, 2027, 18_000)], None), 2026)
    out["partial"]["komi_accrued"] = ledger_income(build("komi", {2026: [("sale", 1_100_000, 0), ("cost", 110_000, 0)]},
                                                         [(2026, 2027, 18_000)], True), 2026)
    # 還付の例
    rows = {2026: [("sale", 550_000, 50_000), ("cost", 2_200_000, 200_000)], 2027: []}
    ret = [(2026, 2027, -150_000)]
    out["refund"] = {name: {y: ledger_income(build(m, rows, ret, acc), y) for y in (2026, 2027)}
                     for name, m, acc in (("komi_filed", "komi", False), ("komi_accrued", "komi", True), ("nuki", "nuki", None))}
    # I3：税抜の取得価額（仮払＝税込×10/110×割合。1円未満は切捨てと四捨五入）
    out["I3"] = []
    for price in (107_000, 108_900):
        for label, r in (("登録", F(1)), ("80%", F(4, 5)), ("70%", F(7, 10))):
            kb = F(price) * F(10, 110) * r
            fl = kb.numerator // kb.denominator
            rd = (kb + F(1, 2)).__floor__()  # 四捨五入（正の値）
            out["I3"].append({"price": price, "case": label, "karibarai_exact": str(kb), "cost_floor": price - fl,
                              "cost_round": price - rd, "under_100k": [price - fl < 100_000, price - rd < 100_000]})
    # 減価償却の例（架空の 3 年均等）
    dep_in, dep_ex = F(330_000, 3), F(300_000, 3)
    out["depr"] = {"komi_accrued": {y: int(1_100_000 - dep_in - 20_000) for y in (2026, 2027, 2028)},
                   "nuki": {y: int(1_000_000 - dep_ex + (100_000 - (30_000 if y == 2026 else 0) - 20_000)) for y in (2026, 2027, 2028)}}
    (OUT / "calc.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    md = ["# R2B invoice 独立検証：例の再計算（仕訳を積み上げる別の実装）", "", "```", json.dumps(out, ensure_ascii=False, indent=1, default=str), "```"]
    (OUT / "calc.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "egov-probe":
        egov_probe()
    elif mode == "egov-fetch":
        egov_fetch()
    elif mode == "nta-fetch":
        nta_fetch()
    elif mode == "check":
        check()
    elif mode == "calc":
        calc()
    else:
        print(__doc__)
