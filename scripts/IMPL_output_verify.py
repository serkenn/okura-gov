"""IMPL_output_verify: トピック output（出力の形式）の文書の主張を、一次情報に当たり直して独立に確かめる（反証役）。

実行（Windows）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_output_verify.py egov
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_output_verify.py web
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_output_verify.py xlsx <ai-ocr.xlsx> <iryouhi_form_v3.1.xlsx>
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_output_verify.py calc
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_output_verify.py egov_extra
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_output_verify.py pdf <PDF...>
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_output_verify.py pdftext <PDF> <出力名>

- egov：所得税法第120条・同法附則（令和八年法律第十二号）・施行規則第47条・第47条の2・第47条の3 を3つの版で取り、主張の文字列を照合する。
- egov_extra：施行規則第47条第3項第二十四号が入った版（2026-03-31・2026-04-01・2026-11-09）と、租税特別措置法第41条の15の5 の本文を取る。
- web：公開資料を取り直し、前の担当が記録した SHA-256 と比べ、引用された文言を照合する（`（期待：見つからない）` を付けた文字列は無いことを確かめる）。
- xlsx：様式の公表時期一覧（ai-ocr.xlsx）と医療費集計フォーム（Ver.3.1）を独立に読む。
- pdf / pdftext：国税庁の様式 PDF（空のユーザーパスワードで AESV2 暗号化）を復号し、様式ID の文字（数字 0 か英字 O か）と、
  文字の位置（収支内訳書の欄コードと科目の対応）を取り出す。AES は FIPS-197 の試験ベクタで自己検査する。
- calc：行数・単位の倍数・様式ID の分解などの再計算。

- 標準ライブラリのみ。既存のスクリプト（IMPL_output_*.py）は import も流用もしない（独立に書く）。
  e-Gov 法令API v2 の叩き方は scripts/R1_egov_revisions.py・scripts/R4_fetch_laws.py の形（GET、UA、間隔、
  /law_data/{law_id}?asof=、/law_revisions/{law_id}）をまねた。
- ダウンロードしたもの（信頼できないデータ）は実行ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_IMPL_output_verify_<sub>/ に置く。その中では何も実行しない。
- 取得は GET だけ。リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。Cookie は使わない。
  対象ホストは laws.e-gov.go.jp・www.nta.go.jp・www.e-tax.nta.go.jp・www.keisan.nta.go.jp だけ（他ホストへのリダイレクトは止める）。
- 出力は scripts/results/IMPL_output_verify/<sub>/ 。各確認は「主張・期待する文字列・見つかったか・前後の原文」を JSON と md に書く。
  文字列の照合は NFKC 正規化して空白を取り除いてから行う（全角・半角、改行の差を吸収する）。
"""
import hashlib
import html.parser
import io
import json
import pathlib
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "okura-gov-research/0.1"
SLEEP = 1.5
OUT = ROOT / "scripts" / "results" / "IMPL_output_verify"
ALLOWED = {"laws.e-gov.go.jp", "www.nta.go.jp", "www.e-tax.nta.go.jp", "www.keisan.nta.go.jp"}
API = "https://laws.e-gov.go.jp/api/2"


class _NoOffHost(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).hostname not in ALLOWED:
            raise urllib.error.HTTPError(newurl, code, "off-host redirect blocked", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = urllib.request.build_opener(_NoOffHost())


def fetch(url, accept="*/*"):
    assert urllib.parse.urlsplit(url).hostname in ALLOWED, url
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept}, method="GET")
    try:
        with OPENER.open(req, timeout=300) as r:
            body, st, final, hdr = r.read(), r.status, r.geturl(), dict(r.headers)
    except urllib.error.HTTPError as e:
        body, st, final, hdr = (e.read() if e.fp else b""), e.code, url, dict(e.headers or {})
    time.sleep(SLEEP)
    return st, final, hdr, body


def norm(s):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s))


def find(text, needle, width=60):
    """NFKC・空白除去で needle を探し、(見つかったか, 前後の原文（正規化後）) を返す。"""
    t, n = norm(text), norm(needle)
    i = t.find(n)
    if i < 0:
        return False, ""
    return True, t[max(0, i - width): i + len(n) + width]


# ---------------------------------------------------------------- e-Gov
def law_text(node):
    if isinstance(node, str):
        return node
    if node.get("tag") == "Rt":
        return ""
    return "".join(law_text(c) for c in node.get("children", []))


def children(node, tag):
    return [c for c in node.get("children", []) if isinstance(c, dict) and c.get("tag") == tag]


def iter_nodes(node, path=()):
    if isinstance(node, dict):
        yield node, path
        for c in node.get("children", []):
            yield from iter_nodes(c, path + (node.get("tag"),))


def main_article(root, num):
    for n, p in iter_nodes(root):
        if n.get("tag") == "Article" and n.get("attr", {}).get("Num") == num and "SupplProvision" not in p:
            return n
    return None


def para(article, num):
    for p in children(article, "Paragraph"):
        if p.get("attr", {}).get("Num") == str(num):
            return p
    return None


def item(paragraph, num):
    for it in children(paragraph, "Item"):
        if it.get("attr", {}).get("Num") == str(num):
            return it
    return None


def item_nums(paragraph):
    return [it.get("attr", {}).get("Num") for it in children(paragraph, "Item")]


def suppl_for(root, amend_law_num):
    for n, p in iter_nodes(root):
        if n.get("tag") == "SupplProvision" and n.get("attr", {}).get("AmendLawNum") == amend_law_num:
            return n
    return None


def suppl_article(sp, num):
    for a in children(sp, "Article"):
        if a.get("attr", {}).get("Num") == str(num):
            return a
    return None


def cmd_egov():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_IMPL_output_verify_egov"
    dl.mkdir(parents=True, exist_ok=False)
    out = OUT / "egov"
    out.mkdir(parents=True, exist_ok=True)
    laws = {"shotoku": "340AC0000000033", "shotoku-ki": "340M50000040011"}
    asofs = ["2025-12-31", "2026-12-31", "2027-01-01"]
    rec = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "revisions": {}, "versions": [], "checks": [], "texts": {}}
    # 改正履歴
    for short, lid in laws.items():
        url = f"{API}/law_revisions/{lid}?" + urllib.parse.urlencode({"response_format": "json", "amendment_date_from": "2025-01-01"})
        st, final, hdr, body = fetch(url, "application/json")
        (dl / f"revisions_{short}.json").write_bytes(body)
        rows = []
        if st == 200:
            for r in json.loads(body).get("revisions", []):
                rows.append({k: r.get(k) for k in ("law_revision_id", "amendment_law_num", "amendment_promulgate_date",
                                                   "amendment_enforcement_date", "amendment_scheduled_enforcement_date",
                                                   "current_revision_status")})
        rec["revisions"][short] = {"url": url, "status": st, "rows": rows}
    data = {}
    for short, lid in laws.items():
        for asof in asofs:
            url = f"{API}/law_data/{lid}?" + urllib.parse.urlencode({"response_format": "json", "asof": asof})
            st, final, hdr, body = fetch(url, "application/json")
            (dl / f"{short}_{asof}.json").write_bytes(body)
            d = json.loads(body) if st == 200 else {}
            ri = d.get("revision_info") or {}
            rec["versions"].append({"short": short, "asof": asof, "url": url, "status": st, "sha256": hashlib.sha256(body).hexdigest(),
                                    "law_revision_id": ri.get("law_revision_id"), "amendment_law_num": ri.get("amendment_law_num"),
                                    "amendment_enforcement_date": ri.get("amendment_enforcement_date"),
                                    "current_revision_status": ri.get("current_revision_status")})
            data[(short, asof)] = d.get("law_full_text")

    checks = rec["checks"]

    def chk(cid, claim, text, needle, expect=True):
        ok, ctx = find(text or "", needle)
        checks.append({"id": cid, "claim": claim, "needle": needle, "expect": expect, "found": ok, "pass": ok == expect, "context": ctx})

    def keep(key, text):
        rec["texts"][key] = text

    for asof in asofs:
        root = data[("shotoku", asof)]
        a120 = main_article(root, "120")
        paras = [p.get("attr", {}).get("Num") for p in children(a120, "Paragraph")]
        keep(f"shotoku@{asof}:120:paragraphs", paras)
        p1 = para(a120, 1)
        keep(f"shotoku@{asof}:120-1:items", item_nums(p1))
        keep(f"shotoku@{asof}:120-1", law_text(p1))
        p3 = para(a120, 3)
        keep(f"shotoku@{asof}:120-3", law_text(p3))
        keep(f"shotoku@{asof}:120-3:items", item_nums(p3))
        for k in range(1, 5):
            it = item(p3, k)
            keep(f"shotoku@{asof}:120-3-{k}", law_text(it) if it else None)
        p4 = para(a120, 4)
        keep(f"shotoku@{asof}:120-4", law_text(p4))
        for k in range(5, 10):
            p = para(a120, k)
            keep(f"shotoku@{asof}:120-{k}", law_text(p) if p else None)
        chk(f"shotoku@{asof}:120-3-1", "第120条第3項第一号：社会保険料控除（第74条第2項第5号の社会保険料に係るもの）を含む", law_text(item(p3, 1)), "社会保険料控除（第七十四条第二項第五号")
        chk(f"shotoku@{asof}:120-3-4", "第120条第3項第四号：勤労学生（第2条第1項第32号ロ又はハ）の証する書類", law_text(item(p3, 4)) if item(p3, 4) else "", "第二条第一項第三十二号ロ又はハ")
        chk(f"shotoku@{asof}:120-3-3", "第120条第3項第三号：非居住者である親族に係る扶養控除・特定親族特別控除", law_text(item(p3, 3)) if item(p3, 3) else "", "特定親族特別控除")
        chk(f"shotoku@{asof}:120-4-sihara", "第120条第4項：社会保険診療報酬支払基金（2025-12-31 版だけにあるはず）", law_text(p4), "社会保険診療報酬支払基金", asof == "2025-12-31")
        chk(f"shotoku@{asof}:120-5", "第120条第5項：5年を経過する日まで領収書の提示又は提出", law_text(para(a120, 5)), "確定申告期限の翌日から起算して五年を経過する日")
        if asof != "2027-01-01":
            chk(f"shotoku@{asof}:120-6", "第120条第6項：前々年分の雑所得の業務の収入金額が千万円を超える者は総収入金額及び必要経費の内容を記載した書類を添付", law_text(para(a120, 6)), "千万円を超えるもの")
        else:
            chk(f"shotoku@{asof}:120-6", "2027-01-01 版第120条第6項：社会保険料控除等の明細書で第3項第一号の書類に代えられる", law_text(para(a120, 6)), "小規模企業共済等掛金控除、生命保険料控除又は地震保険料控除")
            chk(f"shotoku@{asof}:120-8", "2027-01-01 版第120条第8項：旧第6項（総収入金額及び必要経費の内容）", law_text(para(a120, 8)) if para(a120, 8) else "", "千万円を超えるもの")
        sp = suppl_for(root, "令和八年三月三一日法律第一二号")
        keep(f"shotoku@{asof}:suppl_R8_12:present", sp is not None)
        if sp is not None:
            a1 = suppl_article(sp, 1)
            keep(f"shotoku@{asof}:suppl_R8_12:art1", law_text(a1) if a1 else None)
            a10 = suppl_article(sp, 10)
            keep(f"shotoku@{asof}:suppl_R8_12:art10", law_text(a10) if a10 else None)
            if a1:
                p = children(a1, "Paragraph")[0]
                it5 = item(p, 5)
                keep(f"shotoku@{asof}:suppl_R8_12:art1-5", law_text(it5) if it5 else None)
                chk(f"shotoku@{asof}:suppl1-5", "附則第1条第5号：令和九年一月一日、イに第百二十条の改正規定", law_text(it5) if it5 else "", "第百二十条")
                chk(f"shotoku@{asof}:suppl1-5date", "附則第1条第5号：令和九年一月一日", law_text(it5) if it5 else "", "令和九年一月一日")
            if a10:
                chk(f"shotoku@{asof}:suppl10", "附則第10条：新所得税法第百二十条第六項及び第七項…令和九年一月一日以後に令和八年分以後の所得税に係る確定申告書を提出する場合について適用", law_text(a10), "令和九年一月一日以後に令和八年分以後の所得税に係る確定申告書を提出する場合について適用する")
                chk(f"shotoku@{asof}:suppl10cap", "附則第10条の見出し：確定申告書の添付書類に関する経過措置", law_text(a10), "確定申告書の添付書類に関する経過措置")

        rk = data[("shotoku-ki", asof)]
        a47 = main_article(rk, "47")
        p3k = para(a47, 3)
        nums = item_nums(p3k)
        keep(f"shotoku-ki@{asof}:47-3:items", nums)
        for k in (1, 19, 20, 21, 22, 23, 24, 25):
            it = item(p3k, k)
            keep(f"shotoku-ki@{asof}:47-3-{k}", law_text(it) if it else None)
        chk(f"shotoku-ki@{asof}:47-3-20", "規則第47条第3項第二十号：控除対象配偶者等の氏名・生年月日・個人番号", law_text(item(p3k, 20)) if item(p3k, 20) else "", "個人番号")
        chk(f"shotoku-ki@{asof}:47-3-21", "規則第47条第3項第二十一号：控除対象扶養親族又は特定親族の氏名・生年月日・続柄・個人番号", law_text(item(p3k, 21)) if item(p3k, 21) else "", "特定親族")
        chk(f"shotoku-ki@{asof}:47-3-19", "規則第47条第3項第十九号：勤労学生控除又は配当控除に関する事項", law_text(item(p3k, 19)) if item(p3k, 19) else "", "勤労学生控除又は配当控除に関する事項")
        chk(f"shotoku-ki@{asof}:47-3-24-sochi", "規則第47条第3項第二十四号：措法第41条の15の5（2026-12-31 版以降のはず）", law_text(item(p3k, 24)) if item(p3k, 24) else "", "第四十一条の十五の五第一項", asof != "2025-12-31")
        a472 = main_article(rk, "47_2")
        keep(f"shotoku-ki@{asof}:47_2:paragraphs", [p.get("attr", {}).get("Num") for p in children(a472, "Paragraph")])
        for k in (3, 11, 12, 13, 14, 15):
            p = para(a472, k)
            keep(f"shotoku-ki@{asof}:47_2-{k}", law_text(p) if p else None)
        p12 = para(a472, 12)
        for k, needle in ((1, "その年中において支払つた法第七十三条第二項（医療費控除）に規定する医療費"), (2, "という。）を受けた者の氏名"), (3, "病院、診療所その他の者の名称又は氏名"), (4, "その他参考となるべき事項")):
            it = item(p12, k)
            chk(f"shotoku-ki@{asof}:47_2-12-{k}", f"規則第47条の2第12項第{k}号", law_text(it) if it else "", needle)
        chk(f"shotoku-ki@{asof}:47_2-12-head", "規則第47条の2第12項は法第120条第4項第一号の明細書の記載事項", law_text(p12), "第百二十条第四項第一号")
        p13 = para(a472, 13)
        chk(f"shotoku-ki@{asof}:47_2-13-kikou", "規則第47条の2第13項：医療情報基盤・診療報酬審査支払機構（2026-12-31 版以降）", law_text(p13), "医療情報基盤・診療報酬審査支払機構", asof != "2025-12-31")
        p14 = para(a472, 14)
        chk(f"shotoku-ki@{asof}:47_2-14-new", "規則第47条の2第14項：法第120条第6項の明細書の記載事項（2027-01-01 版だけ）", law_text(p14) if p14 else "", "第百二十条第六項", asof == "2027-01-01")
        a473 = main_article(rk, "47_3")
        keep(f"shotoku-ki@{asof}:47_3", law_text(a473))
        chk(f"shotoku-ki@{asof}:47_3-ref", "規則第47条の3の引用（2027-01-01 版で第八項）", law_text(a473), "第百二十条第八項" if asof == "2027-01-01" else "第百二十条第六項")
        chk(f"shotoku-ki@{asof}:47_3-each", "規則第47条の3：それぞれについて", law_text(a473), "業務に係る雑所得のそれぞれについて")
        chk(f"shotoku-ki@{asof}:47_3-exp", "規則第47条の3：必要経費の別", law_text(a473), "商品製品等の売上原価、年初において有する農産物の棚卸高、雇人費、小作料、外注工賃、減価償却費、貸倒金、地代家賃、利子割引料及びその他の経費の別")
        chk(f"shotoku-ki@{asof}:47_3-rev", "規則第47条の3：総収入金額の別", law_text(a473), "賃貸料、山林の伐採又は譲渡による売上高、家事消費の高並びにその他の収入の別")
        # 施行規則の本則で「別表第」を引く条と、「書式」の語
        bethyo = {}
        for n, p in iter_nodes(rk):
            if n.get("tag") == "Article" and "SupplProvision" not in p:
                t = law_text(n)
                for m in re.finditer(r"別表第[一二三四五六七八九十]+(?:の[一二三四五六七八九十]+)?", t):
                    bethyo.setdefault(n["attr"]["Num"], set()).add(m.group(0))
        keep(f"shotoku-ki@{asof}:bethyo_refs", {k: sorted(v) for k, v in bethyo.items()})
        kakutei_shoshiki = []
        for n, p in iter_nodes(rk):
            if n.get("tag") == "Article" and "SupplProvision" not in p:
                t = law_text(n)
                if "確定所得申告書" in t and ("書式" in t or "別表" in t or "様式" in t):
                    kakutei_shoshiki.append(n["attr"]["Num"])
        keep(f"shotoku-ki@{asof}:articles_with_kakutei_and_shoshiki", kakutei_shoshiki)
        # 施行規則の附則（令和八年財務省令第十七号）で第四十七条に触れる条
        for n, p in iter_nodes(rk):
            if n.get("tag") == "SupplProvision" and "令和八年" in (n.get("attr", {}).get("AmendLawNum") or ""):
                t = law_text(n)
                keep(f"shotoku-ki@{asof}:suppl:{n['attr']['AmendLawNum']}", t[:6000])

    (out / "egov_checks.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1, default=list), encoding="utf-8")
    md = [f"# e-Gov 法令API v2 による条文の確認（{ts}）", "", "## 取得した版", "", "| 略称 | asof | 状態 | law_revision_id | 改正法令 | 施行日 | status |", "|---|---|---|---|---|---|---|"]
    for v in rec["versions"]:
        md.append(f"| {v['short']} | {v['asof']} | {v['current_revision_status']} | `{v['law_revision_id']}` | {v['amendment_law_num']} | {v['amendment_enforcement_date']} | {v['status']} |")
    md += ["", "## 改正履歴（amendment_date_from=2025-01-01）", ""]
    for short, r in rec["revisions"].items():
        md.append(f"### {short}（HTTP {r['status']}）")
        md.append("| law_revision_id | 改正法令 | 公布日 | 施行日 | 予定施行日 | 状態 |")
        md.append("|---|---|---|---|---|---|")
        for row in r["rows"]:
            md.append(f"| `{row['law_revision_id']}` | {row['amendment_law_num']} | {row['amendment_promulgate_date']} | {row['amendment_enforcement_date']} | {row['amendment_scheduled_enforcement_date']} | {row['current_revision_status']} |")
        md.append("")
    md += ["## 確認", "", "| id | 主張 | 期待 | 見つかった | 判定 |", "|---|---|---|---|---|"]
    for c in checks:
        md.append(f"| {c['id']} | {c['claim']} | {c['expect']} | {c['found']} | {'OK' if c['pass'] else '**NG**'} |")
    (out / "egov_checks.md").write_text("\n".join(md), encoding="utf-8")
    print("egov done", sum(c["pass"] for c in checks), "/", len(checks))


def cmd_egov_extra():
    """施行規則第47条第3項第二十四号（措法第41条の15の5）が入った版と、その施行日・適用年分を確かめる。
    あわせて第47条の2が引く「別表第一の四」が何か（確定申告書の書式ではないこと）を確かめる。"""
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_IMPL_output_verify_egov_extra"
    dl.mkdir(parents=True, exist_ok=False)
    out = OUT / "egov"
    out.mkdir(parents=True, exist_ok=True)
    rec = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "versions": [], "texts": {}}
    for asof in ("2026-03-31", "2026-04-01", "2026-11-09"):
        url = f"{API}/law_data/340M50000040011?" + urllib.parse.urlencode({"response_format": "json", "asof": asof})
        st, final, hdr, body = fetch(url, "application/json")
        (dl / f"shotoku-ki_{asof}.json").write_bytes(body)
        d = json.loads(body)
        ri = d.get("revision_info") or {}
        rec["versions"].append({"law": "shotoku-ki", "asof": asof, "status": st, "law_revision_id": ri.get("law_revision_id"),
                                "amendment_law_num": ri.get("amendment_law_num"), "amendment_enforcement_date": ri.get("amendment_enforcement_date"),
                                "current_revision_status": ri.get("current_revision_status")})
        root = d["law_full_text"]
        p3 = para(main_article(root, "47"), 3)
        rec["texts"][f"shotoku-ki@{asof}:47-3:items"] = item_nums(p3)
        it24 = item(p3, 24)
        rec["texts"][f"shotoku-ki@{asof}:47-3-24"] = law_text(it24) if it24 else None
        if asof == "2026-11-09":
            a472 = main_article(root, "47_2")
            t = law_text(a472)
            i = t.find("別表第一の四")
            rec["texts"]["shotoku-ki@2026-11-09:47_2:bethyo1-4_context"] = t[max(0, i - 300): i + 100] if i >= 0 else None
            # 別表第一の四 の見出し
            for n, p in iter_nodes(root):
                if n.get("tag") in ("AppdxTable", "AppdxStyle", "AppdxFormat"):
                    title = "".join(law_text(c) for c in n.get("children", []) if isinstance(c, dict) and c.get("tag", "").endswith("Title"))
                    rec["texts"].setdefault("appdx_titles", []).append(f"{n.get('tag')}|{n.get('attr', {}).get('Num')}|{title[:120]}")
    # 租税特別措置法 第41条の15の5 と、それを加えた改正法令の附則（適用年分）
    url = f"{API}/law_data/332AC0000000026?" + urllib.parse.urlencode({"response_format": "json", "asof": "2026-11-09"})
    st, final, hdr, body = fetch(url, "application/json")
    (dl / "sochi_2026-11-09.json").write_bytes(body)
    d = json.loads(body)
    ri = d.get("revision_info") or {}
    rec["versions"].append({"law": "sochi", "asof": "2026-11-09", "status": st, "law_revision_id": ri.get("law_revision_id"),
                            "amendment_law_num": ri.get("amendment_law_num"), "amendment_enforcement_date": ri.get("amendment_enforcement_date"),
                            "current_revision_status": ri.get("current_revision_status")})
    root = d["law_full_text"]
    a = main_article(root, "41_15_5")
    rec["texts"]["sochi@2026-11-09:41_15_5"] = law_text(a) if a else None
    hits = []
    for n, p in iter_nodes(root):
        if n.get("tag") == "SupplProvision":
            an = n.get("attr", {}).get("AmendLawNum") or "(原始附則)"
            for art in children(n, "Article"):
                t = law_text(art)
                if "第四十一条の十五の五" in t:
                    hits.append({"amend_law": an, "article": art.get("attr", {}).get("Num"), "text": t[:1500]})
    rec["texts"]["sochi@2026-11-09:suppl_mentions_41_15_5"] = hits
    (out / "egov_extra.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(rec, ensure_ascii=False, indent=1)[:12000])


# ---------------------------------------------------------------- web
class _Txt(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip, self.links, self._href = [], 0, [], None

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip += 1
        if tag == "a":
            self._href = dict(attrs).get("href")
        self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self.skip:
            self.skip -= 1
        if tag == "a" and self._href:
            self.links.append(self._href)
            self._href = None

    def handle_data(self, d):
        if not self.skip:
            self.out.append(d)


def decode_html(body):
    m = re.search(rb'charset=["\']?([A-Za-z0-9_\-]+)', body[:4096])
    enc = (m.group(1).decode().lower() if m else "utf-8")
    if enc in ("shift_jis", "sjis", "x-sjis", "shift-jis"):
        enc = "cp932"
    try:
        return body.decode(enc)
    except (UnicodeDecodeError, LookupError):
        return body.decode("utf-8", "replace")


# (鍵, URL, 前の担当が記録した SHA-256（無ければ None）, [確かめる文字列...])
WEB = [
    ("system", "https://www.nta.go.jp/taxes/shiraberu/sodan/system.htm", "64d023cca886bdda16c8272d0aaadb9bf5b985a770af262356d4d051dc95c748",
     ["国税庁では、令和８年９月24日に国税システムを更改しました。", "一部の書面申告書や申請・届出書、法定調書の様式が新しくなりました。",
      "様式の受付開始後は、最新の様式で提出をお願いします。", "様式の変更に伴い、申告書の控用はなくなり、申告書の配色は原則、白黒になりました。",
      "お問い合わせ番号", "13桁", "ai-ocr.xlsx", "0026004-138_01.pdf", "固定IPアドレスから動的IPアドレス"]),
    ("info25", "https://www.keisan.nta.go.jp/oshirase/r7info/info25.html", None,
     ["国税システムの更改に伴い、確定申告書等作成コーナーで作成される所得税の一部の申告書・決算書等の様式が変更となりました。"]),
    ("cid1244", "https://www.keisan.nta.go.jp/r7yokuaru/sankou/cid1244.html", None,
     ["令和８年９月19日（土）から", "収支内訳書（一般用）", "所得税の更正の請求書", "財産債務調書", "住宅借入金等特別控除額の計算明細書", "令和５～７年分", "申告書（損失申告用）付表"]),
    ("r07", "https://www.nta.go.jp/taxes/shiraberu/shinkoku/syotoku/r07.htm", "ff769ff6e512b73df0387db39f5fbc6e58f509fd12f5972e2f84e4117e58ac9f",
     ["令和７年分以降用", "yoshiki/01/shinkokusho/pdf/r07/01.pdf", "yoshiki/01/shinkokusho/pdf/r07/05.pdf", "yoshiki/04/pdf/ref1.pdf", "ref3.pdf", "001-1.pdf"]),
    ("tebiki_index", "https://www.nta.go.jp/taxes/shiraberu/shinkoku/tebiki/index.htm", None, ["令和7年分", "令和8年分（期待：見つからない）"]),
    ("t_3-2_06", "https://www.nta.go.jp/taxes/shiraberu/shinkoku/tebiki/2025/03/order2/3-2_06.htm", None, ["所得金額調整控除", "特定支出控除"]),
    ("t_3-2_07", "https://www.nta.go.jp/taxes/shiraberu/shinkoku/tebiki/2025/03/order2/3-2_07.htm", None, ["現金主義", "1,000万円を超える", "収支内訳書"]),
    ("t_3-3_15", "https://www.nta.go.jp/taxes/shiraberu/shinkoku/tebiki/2025/03/order3/3-3_15.htm", None, ["年調以外かつ専修学校等"]),
    ("t_3-3_19", "https://www.nta.go.jp/taxes/shiraberu/shinkoku/tebiki/2025/03/order3/3-3_19.htm", None, ["国外居住親族", "扶養控除欄の「区分」"]),
    ("t_3-3_20", "https://www.nta.go.jp/taxes/shiraberu/shinkoku/tebiki/2025/03/order3/3-3_20.htm", None, ["人数", "特定親族特別控除"]),
    ("t_3-3_24", "https://www.nta.go.jp/taxes/shiraberu/shinkoku/tebiki/2025/03/order3/3-3_24.htm", None, ["セルフメディケーション税制の明細書", "医療費控除の明細書", "区分"]),
    ("t_3-3_27", "https://www.nta.go.jp/taxes/shiraberu/shinkoku/tebiki/2025/03/order3/3-3_27.htm", None,
     ["年末調整を受けた給与を有する方であっても", "同一生計配偶者又は16歳未満の扶養親族の氏名・マイナンバー（個人番号）・続柄・生年月日を記入します"]),
    ("t_3-4_26", "https://www.nta.go.jp/taxes/shiraberu/shinkoku/tebiki/2025/03/order4/3-4_26.htm", None, ["千円未満の端数切捨て"]),
    ("t_3-4_45", "https://www.nta.go.jp/taxes/shiraberu/shinkoku/tebiki/2025/03/order4/3-4_45.htm", None, ["1円未満の端数があるときは、その端数を切り捨てます", "×0.021"]),
    ("t_3-4_39", "https://www.nta.go.jp/taxes/shiraberu/shinkoku/tebiki/2025/03/order4/3-4_39.htm", None, ["100円未満の端数を切り捨てた金額（黒字の金額が100円未満の場合は「0」）", "そのままの金額"]),
    ("t_3-4_41", "https://www.nta.go.jp/taxes/shiraberu/shinkoku/tebiki/2025/03/order4/3-4_41.htm", None, ["100円未満の端数"]),
    ("t_3-6_02", "https://www.nta.go.jp/taxes/shiraberu/shinkoku/tebiki/2025/03/order6/3-6_02.htm", None, ["特別徴収", "自分で納付"]),
    ("t_2_03", "https://www.nta.go.jp/taxes/shiraberu/shinkoku/tebiki/2025/02/2_03.htm", None, ["収受日付印", "令和７年１月", "信書便", "時間外収受箱"]),
    ("shiyo_index", "https://www.e-tax.nta.go.jp/shiyo/index.html", "d442020219b6fcd188e78729567d737b000670582d1dfb88cbfa72baa0dfe116",
     ["一般公開することとしています", "公開内容は、今後の検討（法制面を含みます。）や技術動向などにより、変更される場合があります。",
      "各仕様書の内容は著作権の対象となっています。", "財務・会計ソフトウェア開発者がこの仕様に基づいた供給者ソフトウェアを開発し、市場に供給することを妨げるものではありません。",
      "国税庁は、この仕様書に含まれる情報の利用に伴って発生した不利益や問題について、誰に対しても何ら責任を負うものではありません。",
      "e-Tax等仕様公開に当たっての注意事項」に同意したものとみなされます。", "AI-OCR化対象帳票レイアウトの提供について", "令和8年10月30日更新",
      "リバースエンジニアリング（期待：見つからない）", "仕様書は所定のデータ（Word、Excel等）で提供しています。", "MacOS", "会計ソフトウェアからのデータ引継ぎ",
      "確定申告書等作成コーナーを利用することで、所得税の確定申告書に活用することが可能"]),
    ("ksk2_shiyo3", "https://www.e-tax.nta.go.jp/shiyo/ksk2/ksk2_shiyo3.htm", "7b0da8d393b10b74674db1cf3bf1892a47eb635417a7f7348fc92d2446f21452",
     ["仕様書ダウンロードファイルはCAB形式となっておりますので", "約126MB", "令和8年8月28日", "約772KB", "約9.2MB", "約2.5MB", "約8.9MB", "約1.2MB", "約8.1MB",
      "令和8年1月30日", "約9.4MB", "約8.0MB", "令和8年10月30日", "令和9年1月4日", "令和8年9月24日", "download/e-tax09.CAB", "draft/e-tax09.CAB", "download/e-tax19.CAB"]),
    ("ksk2_shiyo2", "https://www.e-tax.nta.go.jp/shiyo/ksk2/ksk2_shiyo2.htm", None,
     ["令和７年分の所得税の申告手続について", "給与等の支給額が増加した場合", "イメージデータ（PDF形式）", "所得税の額から控除される特別控除額に関する明細書"]),
    ("topics_20260924_chohyo", "https://www.e-tax.nta.go.jp/shiyo/chohyo/topics_20260924_chohyo.htm", None,
     ["令和9年1月4日（月）", "令和8年11月25日（水）", "令和8年9月24日"]),
    ("topics_20261030_shiyo", "https://www.e-tax.nta.go.jp/topics/2026/topics_20261030_shiyo.htm", None,
     ["仕様書の確定版及びXMLスキーマの仕様は、令和8年11月25日（水）に掲載を予定しております。", "令和8年10月30日"]),
    ("topics_20260924_shiyo", "https://www.e-tax.nta.go.jp/topics/2026/topics_20260924_shiyo.htm", None, ["令和8年10月30日", "10月13日"]),
    ("topics_20260910", "https://www.e-tax.nta.go.jp/topics/2026/topics_20260910.htm", None, ["令和8年8月28日", "誤り"]),
    ("faq08", "https://www.e-tax.nta.go.jp/toiawase/faq/nyuryoku/08.htm", None,
     ["令和7年10月31日", "医療費集計フォーム", "医療費の合計額のみを入力", "セルフメディケーション税制", "マイナポータル"]),
    ("ta1119", "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1119.htm", None, ["マイナンバーカード方式", "医療費通知情報", "その医療保険者の電子署名およびその電子署名に係る電子証明書が付されたもの"]),
    ("ta1119qa", "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1119_qa.htm", None,
     ["確定申告書等作成コーナーでは、医療保険者から交付される「医療費通知」データ（XML形式）を利用して確定申告書を作成することができます",
      "QRコード付証明書等作成システム", "「医療費通知」データを被保険者に提供することは、各医療保険者の任意", "「医療費通知情報」の原本はデータ（XML形式）となります"]),
    ("cid1211", "https://www.keisan.nta.go.jp/r7yokuaru/cat2/cat22/cat221/cid1211.html", None, ["995（期待：見つからない）", "医療費集計フォームを利用する", "医療費集計フォームの読込", "ver3.1"]),
    ("cid119", "https://www.keisan.nta.go.jp/r7yokuaru/cat1/cat15/cid119.html", None, [".data", "税金の計算に影響のない項目を昨年分のデータから引き継ぐ", "更正の請求書・修正申告書の作成"]),
    ("cid1102", "https://www.keisan.nta.go.jp/r7yokuaru/cat1/cat15/cid1102.html", None, ["昨年作成コーナーを利用した際に保存したデータを利用する方法"]),
    ("cid179", "https://www.keisan.nta.go.jp/r7yokuaru/cat1/cat15/cid179.html", None, [".xtx", "e-Taxソフトや他の会計ソフト等に組み込んで送信する", "収支内訳書や青色申告決算書の電子申告等データ（拡張子が「.xtx」）を、所得税の申告書データと併せて送信する"]),
    ("etaxweb49", "https://www.e-tax.nta.go.jp/toiawase/qa/e-taxweb/49.htm", None,
     ["民間会計ソフト等で作成した申告書等データ(拡張子.xtx)をe-Taxソフト(WEB版)で読み込んで送信を行うことは可能です。", "作成済みデータの利用", "令和8年10月22日"]),
    ("gaiyo04", "https://www.e-tax.nta.go.jp/toiawase/faq/gaiyo/04.htm", None,
     ["e-TaxソフトWEB版で作成ができない手続であっても、作成済のデータ（拡張子が「.xtx」）があれば、内容の表示及び送信をすることができます。", "令和7年10月31日"]),
    ("etaxweb16", "https://www.e-tax.nta.go.jp/toiawase/qa/e-taxweb/16.htm", None, ["令和6年5月20日", "受信通知", "ログイン画面又はTOP画面から"]),
    ("chosakuken", "https://www.e-tax.nta.go.jp/chuijiko/chosakuken.htm", "325ea4c6f4fe446604518ed5bf800b79963934c2b8d6a6b88c8705ad834cd9f4",
     ["e-Taxホームページで公開している情報（以下「コンテンツ」といいます。）の利用については、", "国税庁ホームページ利用規約」が適用されます。"]),
    ("copy", "https://www.nta.go.jp/chuijiko/copy.htm", "8f274c83732ee2ab0627ae043b11feb4b621790019a82a575098ecf566712dff",
     ["公共データ利用規約（第1.0版）", "確定申告書等作成コーナー", "公売情報ホームページ", "財産評価基準書",
      "あたかも国（又は府省等）が作成したかのような態様で公表・利用してはいけません", "組織や特定の事業を表すシンボルマーク、ロゴ、キャラクターデザイン"]),
    ("cps", "https://www.e-tax.nta.go.jp/cps/cps.htm", "9f8c4ec0d43f8bb9e5e23511e7840ed99cf593e3af4f7d5b0066becb0d1ab0ef",
     ["国税電子申告・納税システムの利用に当たっては、次の利用規約の全ての条項に同意いただく必要があります", "約7.5MB", "e-Tax AP", "医療費通知"]),
    ("iryou_koujo", "https://www.nta.go.jp/taxes/shiraberu/shinkoku/tokushu/keisubetsu/iryou-koujo.htm", None, ["医療費集計フォーム", "セルフメディケーション税制の適用を受ける方は、「医療費集計フォーム」をご利用いただけません。", "995（期待：見つからない）"]),
    ("etax_kiyaku", "https://www.e-tax.nta.go.jp/horeito/horei7.htm", "4e1b53971251c3e75ed768ca59550e50db5da65321dbecf6fc073faee829811a",
     ["「システム利用者」とは、本システムを利用して申告等手続又は国税の納付手続を行う者をいいます。", "複製、改変、編集、頒布等を行わず、また、リバースエンジニアリングを行わないこと。"]),
    ("sakusei_kiyaku_pdf", "https://www.keisan.nta.go.jp/oshirase/r4info/info999.files/01_kiyaku.pdf", "e9d8db424b33610d8dc58eb068f66498fe06c1b264a92c72671c79848dc66822", []),
    # バイナリ（ハッシュだけ。中身は Read ツールで読む）
    ("pdf_01", "https://www.nta.go.jp/taxes/shiraberu/shinkoku/yoshiki/01/shinkokusho/pdf/r07/01.pdf", "833e641919fbc1eb22605a1989c6514eabb742334528d04dd90736ae90afce46", []),
    ("pdf_001-1", "https://www.nta.go.jp/taxes/shiraberu/shinkoku/tebiki/2025/pdf/001-1.pdf", "15f1874c67264a5b8d87ed8800f37e9f527e96a46ec6fda5239f00f82a503a99", []),
    ("pdf_05", "https://www.nta.go.jp/taxes/shiraberu/shinkoku/yoshiki/01/shinkokusho/pdf/r07/05.pdf", "686ecbd849ebe07b11a90d10421561669188e1cfd48b18962bf1be06965a0f24", []),
    ("pdf_ref1", "https://www.nta.go.jp/taxes/shiraberu/shinkoku/yoshiki/04/pdf/ref1.pdf", "7c602c74703668f06e37b5efe40bf924da885cc8387c7fc3c1dd7e5c8fcb23ea", []),
    ("pdf_shomen", "https://www.nta.go.jp/taxes/shiraberu/sodan/pdf/0026004-138_01.pdf", "6227d181d86afbc3bd027de6718d1e59217ee7d3cb87ae74eda02a8067a0e863", []),
    ("pdf_chohyo2027", "https://www.e-tax.nta.go.jp/shiyo/chohyo/shiyo_chohyo_20260924.pdf", "52865038e7ef577d4b798c7e768a52641b5063475bcf73e9ae67d1a13d9c9d82", []),
    ("pdf_chohyo2026", "https://www.e-tax.nta.go.jp/shiyo/chohyo/shiyo_chohyo_20260105.pdf", None, []),
    ("pdf_faq08_3", "https://www.e-tax.nta.go.jp/toiawase/faq/nyuryoku/08_3.pdf", None, []),
    ("pdf_faq08_6", "https://www.e-tax.nta.go.jp/toiawase/faq/nyuryoku/08_6.pdf", None, []),
    ("xlsx_aiocr", "https://www.nta.go.jp/taxes/shiraberu/sodan/ai-ocr.xlsx", "99af2fe209fe817bef3cee6eb9bc9a3169cbe1a519ff9cba09cdb407817cab0c", []),
    ("xlsx_iryouhi", "https://www.keisan.nta.go.jp/r7/syotoku/data/downloadData/iryouhi_form_v3.1.xlsx", "032f862f33e83a84e26469e7ddf702aa4d03531152168e843ad379b88d61a89a", []),
]


def cmd_web(only=None):
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_IMPL_output_verify_web"
    dl.mkdir(parents=True, exist_ok=False)
    out = OUT / "web"
    (out / "text").mkdir(parents=True, exist_ok=True)
    rec = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "pages": []}
    # robots.txt（nta）を確かめる
    for host in ("www.nta.go.jp", "www.e-tax.nta.go.jp", "www.keisan.nta.go.jp"):
        st, final, hdr, body = fetch(f"https://{host}/robots.txt")
        rec.setdefault("robots", []).append({"host": host, "status": st, "sha256": hashlib.sha256(body).hexdigest() if st == 200 else None,
                                             "text": body.decode("utf-8", "replace")[:2000] if st == 200 else None})
    for key, url, prev_sha, needles in WEB:
        if only and key not in only:
            continue
        st, final, hdr, body = fetch(url)
        ext = pathlib.PurePosixPath(urllib.parse.urlsplit(final).path).suffix or ".bin"
        (dl / f"{key}{ext}").write_bytes(body)
        sha = hashlib.sha256(body).hexdigest()
        page = {"key": key, "url": url, "final_url": final, "status": st, "last_modified": hdr.get("Last-Modified"),
                "bytes": len(body), "sha256": sha, "prev_sha256": prev_sha,
                "same_as_prev": (sha == prev_sha) if prev_sha else None, "checks": []}
        if needles and st == 200:
            p = _Txt()
            p.feed(decode_html(body))
            text = "".join(p.out)
            text = re.sub(r"\n\s*\n+", "\n", text)
            (out / "text" / f"{key}.txt").write_text(text, encoding="utf-8")
            hay = text + "\n" + "\n".join(p.links)
            for n in needles:
                neg = n.endswith("（期待：見つからない）")
                n2 = n.replace("（期待：見つからない）", "")
                ok, ctx = find(hay, n2)
                page["checks"].append({"needle": n2, "expect_found": not neg, "found": ok, "pass": ok != neg, "context": ctx})
        rec["pages"].append(page)
        print(key, st, sha[:12], page["same_as_prev"], [c["pass"] for c in page["checks"]])
    (out / f"web_checks_{ts}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    md = [f"# 公開資料の再取得と文言の確認（{ts}）", "", f"- 保存先：`{rec['download_dir']}`", ""]
    md += ["## robots.txt", ""] + [f"- {r['host']}: HTTP {r['status']} {r['sha256'] or ''}" for r in rec["robots"]] + [""]
    md += ["## ページ", "", "| 鍵 | HTTP | Last-Modified | SHA-256（先頭16） | 前回と同じ | 確認 |", "|---|---|---|---|---|---|"]
    for p in rec["pages"]:
        nf = [("（無いはずが有る）" if not c["expect_found"] else "") + c["needle"] for c in p["checks"] if not c["pass"]]
        md.append(f"| {p['key']} | {p['status']} | {p['last_modified']} | `{p['sha256'][:16]}` | {p['same_as_prev']} | "
                  f"{len(p['checks']) - len(nf)}/{len(p['checks'])}" + (f"（不一致：{'／'.join(nf)}）" if nf else "") + " |")
    (out / f"web_checks_{ts}.md").write_text("\n".join(md), encoding="utf-8")


# ---------------------------------------------------------------- xlsx
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "x14": "http://schemas.microsoft.com/office/spreadsheetml/2009/9/main",
      "xm": "http://schemas.microsoft.com/office/excel/2006/main"}
MAXBYTES = 50 * 1024 * 1024


def _read(z, name):
    info = z.getinfo(name)
    if info.file_size > MAXBYTES:
        raise ValueError(f"too large: {name}")
    return z.read(name)


def col2n(c):
    n = 0
    for ch in c:
        n = n * 26 + (ord(ch) - 64)
    return n


def load_xlsx(path):
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        sst = []
        if "xl/sharedStrings.xml" in names:
            for si in ET.fromstring(_read(z, "xl/sharedStrings.xml")).findall("m:si", NS):
                # ふりがな（rPh）を除き、si 直下の t と r/t だけを連結
                txt = ""
                for ch in si:
                    tag = ch.tag.split("}")[1]
                    if tag == "t":
                        txt += ch.text or ""
                    elif tag == "r":
                        for t in ch.iter(f"{{{NS['m']}}}t"):
                            txt += t.text or ""
                sst.append(txt)
        wb = ET.fromstring(_read(z, "xl/workbook.xml"))
        rels = ET.fromstring(_read(z, "xl/_rels/workbook.xml.rels"))
        rmap = {r.get("Id"): r.get("Target") for r in rels}
        sheets = []
        for s in wb.find("m:sheets", NS):
            rid = s.get(f"{{{NS['r']}}}id")
            target = rmap[rid].lstrip("/")
            target = target if target.startswith("xl/") else "xl/" + target
            x = ET.fromstring(_read(z, target))
            dim = x.find("m:dimension", NS)
            cells = {}
            formulas = {}
            for c in x.iter(f"{{{NS['m']}}}c"):
                ref, t = c.get("r"), c.get("t")
                v = c.find("m:v", NS)
                f = c.find("m:f", NS)
                if f is not None:
                    formulas[ref] = f.text
                if t == "s" and v is not None:
                    val = sst[int(v.text)]
                elif t == "inlineStr":
                    val = "".join(tt.text or "" for tt in c.iter(f"{{{NS['m']}}}t"))
                else:
                    val = v.text if v is not None else None
                if val is not None or f is not None:
                    cells[ref] = val
            dvs = []
            for dv in x.iter(f"{{{NS['m']}}}dataValidation"):
                f1 = dv.find("m:formula1", NS)
                dvs.append({"sqref": dv.get("sqref"), "type": dv.get("type"), "operator": dv.get("operator"),
                            "formula1": f1.text if f1 is not None else None,
                            "formula2": (dv.find("m:formula2", NS).text if dv.find("m:formula2", NS) is not None else None)})
            for dv in x.iter(f"{{{NS['x14']}}}dataValidation"):
                f1 = dv.find("x14:formula1/xm:f", NS)
                sq = dv.find("xm:sqref", NS)
                dvs.append({"sqref": sq.text if sq is not None else None, "type": dv.get("type"), "formula1": f1.text if f1 is not None else None, "x14": True})
            merges = [m.get("ref") for m in x.iter(f"{{{NS['m']}}}mergeCell")]
            sheets.append({"name": s.get("name"), "path": target, "dimension": dim.get("ref") if dim is not None else None,
                           "cells": cells, "formulas": formulas, "dvs": dvs, "merges": merges})
        has_vba = any(n.lower().endswith("vbaproject.bin") for n in names)
        app = _read(z, "docProps/app.xml").decode("utf-8", "replace") if "docProps/app.xml" in names else None
    return {"names": names, "sheets": sheets, "has_vba": has_vba, "app_xml": app}


def cmd_xlsx(aiocr, iryouhi):
    out = OUT / "xlsx"
    out.mkdir(parents=True, exist_ok=True)
    res = {}
    # 様式の公表時期一覧
    b = pathlib.Path(aiocr).read_bytes()
    d = load_xlsx(aiocr)
    sh = d["sheets"][0]
    cells = sh["cells"]
    rows = {}
    for ref, v in cells.items():
        m = re.match(r"([A-Z]+)(\d+)$", ref)
        rows.setdefault(int(m.group(2)), {})[m.group(1)] = v
    maxrow = max(rows)
    hdr = {k: rows.get(3, {}).get(k) for k in "ABCDE"}
    data_rows = [r for r in range(4, maxrow + 1) if any((rows.get(r, {}).get(k) or "").strip() for k in "ABCDE")]
    from collections import Counter
    cnt = Counter()
    for r in data_rows:
        rr = rows[r]
        cnt[(rr.get("A"), rr.get("C"), rr.get("D"))] += 1
    shotoku = [r for r in data_rows if rows[r].get("A") == "申告所得税関係"]
    shotoku_status = Counter((rows[r].get("C"), rows[r].get("D")) for r in shotoku)
    kw = {}
    for w in ("令和８年分", "令和8年分", "令和７年分", "社会保険料控除", "医療費控除", "収支内訳書", "申告書一表"):
        kw[w] = [(r, rows[r].get("A"), rows[r].get("B"), rows[r].get("C"), rows[r].get("D")) for r in data_rows if w in (rows[r].get("B") or "")]
    res["aiocr"] = {"sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b), "has_vba": d["has_vba"], "sheet_names": [s["name"] for s in d["sheets"]],
                    "dimension": sh["dimension"], "n_cells_with_value": len(cells), "n_formulas": len(sh["formulas"]),
                    "A1": rows.get(1, {}), "row2": rows.get(2, {}), "header_row3": hdr, "max_row": maxrow, "n_data_rows": len(data_rows),
                    "shotoku_rows": len(shotoku), "shotoku_status": {f"{k[0]}|{k[1]}": v for k, v in shotoku_status.items()},
                    "by_cat_status": {f"{k[0]}|{k[1]}|{k[2]}": v for k, v in sorted(cnt.items(), key=lambda kv: str(kv[0]))},
                    "keyword_rows": kw}
    # 医療費集計フォーム
    b2 = pathlib.Path(iryouhi).read_bytes()
    d2 = load_xlsx(iryouhi)
    s1, s2 = d2["sheets"][0], d2["sheets"][1]
    pick = {k: s1["cells"].get(k) for k in ("A1", "L2", "M2", "B3", "C3", "B4", "C4", "A6", "B6", "C6", "D6", "E6", "F6", "G6", "H6", "I6", "J6",
                                             "A7", "B7", "C7", "D7", "E7", "F7", "G7", "H7", "I7", "J7", "A8", "B8", "A9", "A1003", "A1004")}
    s2_text = "\n".join(v for v in s2["cells"].values() if v)
    s2_checks = {}
    for n in ("995件まで入力が可能です", "所得税の確定申告等作成コーナーの医療費控除の入力画面で読み込むことで、入力した内容が反映されます",
              "セルフメディケーション税制を適用される場合にはご利用いただけません",
              "その給付の目的となった医療費の金額を限度として差し引きます", "引ききれない金額が生じた場合であっても、他の医療費からは差し引きません",
              "保険金などで補填される金額が確定申告書を提出する時までに確定していない場合には、その保険金などの見込額を記載します",
              "『医療を受けた人』・『病院・薬局などの名称』ごとにまとめて入力してください"):
        ok, ctx = find(s2_text, n)
        s2_checks[n] = {"found": ok, "context": ctx}
    a_nums = [s1["cells"].get(f"A{r}") for r in range(9, 1004)]
    res["iryouhi"] = {"sha256": hashlib.sha256(b2).hexdigest(), "bytes": len(b2), "has_vba": d2["has_vba"], "sheet_names": [s["name"] for s in d2["sheets"]],
                      "dims": [s["dimension"] for s in d2["sheets"]], "n_cells": [len(s["cells"]) for s in d2["sheets"]],
                      "n_formulas": [len(s["formulas"]) for s in d2["sheets"]], "n_merges": [len(s["merges"]) for s in d2["sheets"]],
                      "formulas_sheet1": s1["formulas"], "dvs_sheet1": s1["dvs"], "picked_cells": pick,
                      "A9_A1003_first_last": (a_nums[0], a_nums[-1]), "A_count_nonempty_9_1003": sum(1 for a in a_nums if a not in (None, "")),
                      "sheet2_checks": s2_checks, "app_xml": d2["app_xml"],
                      "sheet2_example_dates": [v for k, v in s2["cells"].items() if v and re.fullmatch(r"4\d{4}", v)]}
    (out / "xlsx_checks.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in res["aiocr"].items() if k not in ("by_cat_status", "keyword_rows")}, ensure_ascii=False))
    print(json.dumps({k: v for k, v in res["iryouhi"].items() if k not in ("formulas_sheet1",)}, ensure_ascii=False)[:6000])


# ---------------------------------------------------------------- pdf（様式ID の文字を確かめる）
# 国税庁の様式 PDF は空のユーザーパスワードで AESV2（128bit, R4）暗号化されている（開くのにパスワードは要らない。
# 権限フラグ P=-1068 は bit5「内容のコピー・抽出」を許している）。標準ライブラリに AES がないので、
# 復号だけを書き、FIPS-197 の試験ベクタで自己検査してから使う。抽出した文字列は様式ID の「0（数字）/O（英字）」の確認だけに使う。
def _xt(a):
    return ((a << 1) ^ 0x1B) & 0xFF if a & 0x80 else a << 1


def _gmul(a, b):
    r = 0
    while b:
        if b & 1:
            r ^= a
        a = _xt(a)
        b >>= 1
    return r


def _sbox():
    inv = [0] * 256
    for a in range(1, 256):
        for b in range(1, 256):
            if _gmul(a, b) == 1:
                inv[a] = b
                break
    s = []
    for a in range(256):
        x = inv[a]
        y = x
        for i in range(1, 5):
            y ^= ((x << i) | (x >> (8 - i))) & 0xFF
        s.append(y ^ 0x63)
    si = [0] * 256
    for i, v in enumerate(s):
        si[v] = i
    return s, si


SBOX, INV_SBOX = _sbox()
M9, M11, M13, M14 = ([_gmul(x, k) for x in range(256)] for k in (9, 11, 13, 14))


def _expand(key):
    w = [list(key[i:i + 4]) for i in range(0, 16, 4)]
    rcon = 1
    for i in range(4, 44):
        t = list(w[i - 1])
        if i % 4 == 0:
            t = t[1:] + t[:1]
            t = [SBOX[x] for x in t]
            t[0] ^= rcon
            rcon = _xt(rcon)
        w.append([w[i - 4][j] ^ t[j] for j in range(4)])
    return [sum(w[r * 4:r * 4 + 4], []) for r in range(11)]


def aes128_decrypt_block(rk, block):
    s = [b ^ k for b, k in zip(block, rk[10])]
    for rnd in range(9, -1, -1):
        # InvShiftRows（列優先の状態：s[c*4+r]）
        s = [s[((c - r) % 4) * 4 + r] for c in range(4) for r in range(4)]
        s = [INV_SBOX[x] for x in s]
        s = [x ^ k for x, k in zip(s, rk[rnd])]
        if rnd:
            ns = []
            for c in range(4):
                a = s[c * 4:c * 4 + 4]
                ns += [M14[a[0]] ^ M11[a[1]] ^ M13[a[2]] ^ M9[a[3]],
                       M9[a[0]] ^ M14[a[1]] ^ M11[a[2]] ^ M13[a[3]],
                       M13[a[0]] ^ M9[a[1]] ^ M14[a[2]] ^ M11[a[3]],
                       M11[a[0]] ^ M13[a[1]] ^ M9[a[2]] ^ M14[a[3]]]
            s = ns
    return bytes(s)


def aes128_cbc_decrypt(key, data):
    rk = _expand(key)
    iv, out = data[:16], bytearray()
    for i in range(16, len(data) - len(data) % 16, 16):
        blk = data[i:i + 16]
        out += bytes(x ^ y for x, y in zip(aes128_decrypt_block(rk, blk), iv))
        iv = blk
    if out and 1 <= out[-1] <= 16:
        out = out[:-out[-1]]
    return bytes(out)


PAD = bytes.fromhex("28BF4E5E4E758A4164004E56FFFA01082E2E00B6D0683E802F0CA9FE6453697A")


def _rc4(key, data):
    S = list(range(256))
    j = 0
    for i in range(256):
        j = (j + S[i] + key[i % len(key)]) % 256
        S[i], S[j] = S[j], S[i]
    i = j = 0
    out = bytearray()
    for b in data:
        i = (i + 1) % 256
        j = (j + S[i]) % 256
        S[i], S[j] = S[j], S[i]
        out.append(b ^ S[(S[i] + S[j]) % 256])
    return bytes(out)


def _stream_objects(pdf):
    """(objnum, gen, 辞書, 生のストリーム) を順に返す。"""
    for m in re.finditer(rb"(\d+)\s+(\d+)\s+obj\b", pdf):
        end = pdf.find(b"endobj", m.end())
        body = pdf[m.end():end]
        sm = re.search(rb"stream\r?\n", body)
        if not sm:
            continue
        dic = body[:sm.start()]
        lm = re.search(rb"/Length\s+(\d+)(?!\s+\d+\s+R)", dic)
        raw = body[sm.end():sm.end() + int(lm.group(1))] if lm else body[sm.end():body.rfind(b"endstream")].rstrip(b"\r\n")
        yield int(m.group(1)), int(m.group(2)), dic, raw


def _inflate(dic, b):
    try:
        return zlib_decompress(b) if b"FlateDecode" in dic else b
    except Exception as e:  # noqa
        return b"<<decompress error " + repr(e).encode() + b">>"


def pdf_streams(pdf):
    """暗号化されていればユーザーパスワード空で復号し、(objnum, 辞書, 展開後のバイト列) の一覧と鍵の検査結果を返す。"""
    if not re.search(rb"/Filter\s*/Standard", pdf):
        return None, [(num, dic, _inflate(dic, raw)) for num, gen, dic, raw in _stream_objects(pdf)]
    o = bytes.fromhex(re.search(rb"/O\s*<([0-9a-fA-F]+)>", pdf).group(1).decode())
    u = bytes.fromhex(re.search(rb"/U\s*<([0-9a-fA-F]+)>", pdf).group(1).decode())
    p = int(re.search(rb"/P\s+(-?\d+)", pdf).group(1))
    id0 = bytes.fromhex(re.search(rb"/ID\s*\[\s*<([0-9a-fA-F]+)>", pdf).group(1).decode())
    h = hashlib.md5(PAD + o + (p & 0xFFFFFFFF).to_bytes(4, "little") + id0).digest()
    for _ in range(50):
        h = hashlib.md5(h[:16]).digest()
    key = h[:16]
    # 鍵の検査（Algorithm 5, R>=3）
    x = _rc4(key, hashlib.md5(PAD + id0).digest())
    for i in range(1, 20):
        x = _rc4(bytes(k ^ i for k in key), x)
    key_ok = (x == u[:16])
    out = []
    for num, gen, dic, raw in _stream_objects(pdf):
        if b"/XRef" in dic:
            dec = raw  # XRef ストリームは暗号化されない
        else:
            okey = hashlib.md5(key + num.to_bytes(3, "little") + gen.to_bytes(2, "little") + b"sAlT").digest()[:16]
            dec = aes128_cbc_decrypt(okey, raw)
        out.append((num, dic, _inflate(dic, dec)))
    return key_ok, out


def zlib_decompress(b):
    import zlib
    return zlib.decompress(b)


def parse_cmap(b):
    m = {}
    for blk in re.findall(rb"beginbfchar(.*?)endbfchar", b, re.S):
        for a, c in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", blk):
            m[int(a, 16)] = bytes.fromhex(c.decode()).decode("utf-16-be", "replace")
    for blk in re.findall(rb"beginbfrange(.*?)endbfrange", b, re.S):
        for a, z, c in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", blk):
            base = int(c, 16)
            for k in range(int(a, 16), int(z, 16) + 1):
                m[k] = chr(base + k - int(a, 16))
    return m


def cmd_pdf(paths):
    out = OUT / "pdf"
    out.mkdir(parents=True, exist_ok=True)
    # AES の自己検査（FIPS-197 Appendix C.1：鍵 000102..0f、平文 00112233..ff → 暗号文 69c4e0d8..5a）
    rk = _expand(bytes(range(16)))
    selftest = aes128_decrypt_block(rk, bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a")).hex() == "00112233445566778899aabbccddeeff"
    res = {"aes_selftest": selftest, "files": {}}
    for path in paths:
        pdf = pathlib.Path(path).read_bytes()
        key_ok, streams = pdf_streams(pdf)
        cmaps = [parse_cmap(d) for _, _, d in streams if b"beginbfchar" in d or b"beginbfrange" in d]
        found = []
        for num, dic, d in streams:
            # リテラル文字列
            for s in re.findall(rb"\(((?:[^()\\]|\\.){4,40})\)\s*Tj", d):
                t = s.decode("latin-1")
                if "NTA" in t:
                    found.append({"obj": num, "kind": "literal", "text": t})
            # 16進文字列（2バイト CID）を各 CMap で読む
            hexes = re.findall(rb"<([0-9A-Fa-f]{4,})>", d)
            if hexes and b"BT" in d:
                for ci, cm in enumerate(cmaps):
                    txt = "".join("".join(cm.get(int(h[i:i + 4], 16), "�") for i in range(0, len(h) - 3, 4)) + "|" for h in hexes)
                    for mm in re.finditer(r"N\|?T\|?A\|?[0-9OＯ０|]{1,3}[^�]{0,40}", txt):
                        found.append({"obj": num, "kind": f"hex/cmap{ci}", "text": mm.group(0)})
        etax_ids = []
        for num, dic, d in streams:
            hexes = re.findall(rb"<([0-9A-Fa-f]{4,})>", d)
            if hexes and b"BT" in d:
                for cm in cmaps:
                    for h in hexes:
                        t = "".join(cm.get(int(h[i:i + 4], 16), "�") for i in range(0, len(h) - 3, 4))
                        if re.fullmatch(r"K[O0][A-Z0-9]\d{3}", t):
                            etax_ids.append(t)
            for lit in re.findall(rb"\((K[O0][A-Z0-9]\d{3})\)", d):
                etax_ids.append(lit.decode("ascii"))
        ids = []
        for f in found:
            t = f["text"].replace("|", "")
            mm = re.search(r"NTA[0-9A-Z]{13}", t)
            if mm:
                ids.append({"id": mm.group(0), "chars_4_to_6": [f"{c}(U+{ord(c):04X})" for c in mm.group(0)[3:6]], "via": f["kind"]})
        res["files"][pathlib.Path(path).name] = {"sha256": hashlib.sha256(pdf).hexdigest(), "key_ok": key_ok, "n_streams": len(streams),
                                                 "n_cmaps": len(cmaps), "form_ids": ids,
                                                 "etax_ids_K": sorted({f"{t}:{'O(U+004F)' if t[1] == 'O' else '0(U+0030)'}" for t in etax_ids}), "raw_hits": found[:20]}
    (out / "pdf_form_ids.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1)[:8000])


def cmd_pdftext(path, name):
    """暗号化を解いた PDF の文字を (頁, x, y, フォント, 文字列) で書き出す。90ms-RKSJ（Shift_JIS）の Type0 フォントだけを読む。
    収支内訳書（一般用）の欄コード（G02 など）と科目名の位置の対応を確かめるために使う。"""
    pdf = pathlib.Path(path).read_bytes()
    key_ok, streams = pdf_streams(pdf)
    body = {num: d for num, dic, d in streams}
    # ページの順（/Kids）と各ページの /Contents
    kids = [int(x) for x in re.findall(rb"(\d+)\s+0\s+R", re.search(rb"/Kids\s*\[([^\]]*)\]", b"".join(body.values()) + pdf).group(1))]
    pages = []
    for k in kids:
        m = re.search(rb"\b%d\s+0\s+obj\s*<<(.*?)>>\s*endobj" % k, pdf, re.S)
        cont = re.search(rb"/Contents\s*(\[[^\]]*\]|\d+\s+0\s+R)", m.group(1)).group(1)
        pages.append([int(x) for x in re.findall(rb"(\d+)\s+0\s+R", cont)])
    rows = []
    for pno, cs in enumerate(pages, 1):
        content = b"\n".join(body.get(c, b"") for c in cs)
        for bt in re.findall(rb"BT(.*?)ET", content, re.S):
            fm = re.search(rb"/(\w+)\s+[\d.]+\s+Tf", bt)
            tm = re.search(rb"([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+Tm", bt)
            parts = []
            for h, lit in re.findall(rb"<([0-9A-Fa-f]*)>\s*Tj|\(((?:[^()\\]|\\.)*)\)\s*Tj", bt):
                raw = bytes.fromhex(h.decode()) if h else lit
                parts.append(raw.decode("cp932", "replace"))
            if parts:
                rows.append((pno, float(tm.group(5)) if tm else -1, float(tm.group(6)) if tm else -1,
                             fm.group(1).decode() if fm else "", "".join(parts)))
    outlines = [t.decode("latin-1") for t in re.findall(rb"/Title\s*\(([^)]*)\)", b"".join(body.values()))]
    out = OUT / "pdf"
    out.mkdir(parents=True, exist_ok=True)
    rows.sort(key=lambda r: (r[0], -r[2], r[1]))
    with open(out / f"{name}_text.tsv", "w", encoding="utf-8") as f:
        f.write(f"# file={pathlib.Path(path).name} sha256={hashlib.sha256(pdf).hexdigest()} key_ok={key_ok} pages={pages} outlines={outlines}\n")
        f.write("page\tx\ty\tfont\ttext\n")
        for r in rows:
            f.write(f"{r[0]}\t{r[1]:.1f}\t{r[2]:.1f}\t{r[3]}\t{r[4]}\n")
    # 欄コード（G/E/U/L + 数字）ごとに、同じ高さ（y の差 2.5 以内）で左にある文字列を並べる（科目名の対応を見るため）
    with open(out / f"{name}_codes.tsv", "w", encoding="utf-8") as f:
        f.write("page\tcode\tx\ty\tsame_line_left_texts(x昇順)\n")
        for r in rows:
            if re.fullmatch(r"[GEUL]\d{2,3}", r[4]):
                left = sorted((q for q in rows if q[0] == r[0] and abs(q[2] - r[2]) <= 2.5 and q[1] < r[1] and q[1] > r[1] - 110
                               and not re.fullmatch(r"[GEUL]\d{2,3}", q[4])), key=lambda q: q[1])
                f.write(f"{r[0]}\t{r[4]}\t{r[1]:.1f}\t{r[2]:.1f}\t{' / '.join(q[4] for q in left)}\n")
    print(name, "rows", len(rows), "pages", pages, "outlines", outlines)


# ---------------------------------------------------------------- calc
def cmd_calc():
    out = OUT / "calc"
    out.mkdir(parents=True, exist_ok=True)
    r = {}
    # 医療費集計フォームの行数
    r["iryouhi_rows_9_to_1003"] = 1003 - 9 + 1
    # 「単位の印字」の 0 の数と倍数
    r["unit_multiples"] = {"0000": 10 ** 4, "000": 10 ** 3, "00": 10 ** 2}
    # 半角数字9桁以内の最大値
    r["max_9digits"] = 10 ** 9 - 1
    # 紙の様式ID の中の e-Tax 様式ID 相当の文字列（数字の 0 と英字の O を区別して比べる）
    ids = {"第一表": "NTA1K0A020010230", "第二表": "NTA0K0A020020230", "収支内訳書1": "NTA0KOA110010120", "収支内訳書2": "NTA0KOA110020120",
           "医療費明細書": "NTA0K0B560010180"}
    etax = ["KOA020", "KOA110", "KOB560"]
    r["form_id_contains_etax_id"] = {k: {e: (e in v) for e in etax} for k, v in ids.items()}
    r["form_id_chars"] = {k: [f"{c}(U+{ord(c):04X})" for c in v[3:6]] for k, v in ids.items()}
    # 紙の様式ID を「NTA + 1桁 + 6文字 + 3桁 + 2桁 + 1桁」に分け、6文字の部分を e-Tax の様式ID（英字 O）と比べる。
    # 5文字目を英字 O に置き換えた場合の分解も出す（第一表・第二表・医療費明細書は画像からの転記で 0/O が区別できないため）。
    # 版（2桁）は e-Tax の帳票一覧の版と並べる：令和8年1月受付の一覧で KOA020=23.0・KOB560=18.0、令和9年1月受付の一覧で KOA110=13.0（PDF のテキスト層で確認）。
    etax_versions_r8jan = {"KOA020": "23.0", "KOB560": "18.0"}
    etax_versions_r9jan = {"KOA020": "24.0", "KOA110": "13.0"}
    dec = {}
    for k, v in ids.items():
        vo = v[:5] + v[5].replace("0", "O") + v[6:]
        ver4 = vo[12:16]
        dec[k] = {"as_transcribed": v, "with_letter_O": vo, "prefix": vo[:4], "etax_part": vo[4:10], "page2": vo[10:12], "ver4": ver4,
                  "ver4_as_number": f"{int(ver4[:3])}.{ver4[3]}",
                  "etax_ver_r8jan": etax_versions_r8jan.get(vo[4:10]), "etax_ver_r9jan": etax_versions_r9jan.get(vo[4:10])}
    r["form_id_decomposition"] = dec
    # 復興特別所得税 2.1% と 0.021
    r["fukko_rate_equal"] = abs(0.021 - 2.1 / 100) < 1e-12
    # 所得税関係の帳票一覧の版数の列挙（転記の確認用。値は PDF を Read で読んで比べる）
    (out / "calc.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(r, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sub = sys.argv[1] if len(sys.argv) > 1 else ""
    if sub == "egov":
        cmd_egov()
    elif sub == "egov_extra":
        cmd_egov_extra()
    elif sub == "web":
        cmd_web(set(sys.argv[2:]) or None)
    elif sub == "xlsx":
        cmd_xlsx(sys.argv[2], sys.argv[3])
    elif sub == "calc":
        cmd_calc()
    elif sub == "pdf":
        cmd_pdf(sys.argv[2:])
    elif sub == "pdftext":
        cmd_pdftext(sys.argv[2], sys.argv[3])
    else:
        print(__doc__)
