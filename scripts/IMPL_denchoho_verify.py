"""IMPL_denchoho_verify: denchoho トピックの文書（電子帳簿保存法と記録の保存）を、一次情報に当たり直して独立に検証する。

実行（リポジトリのルートで。段階ごとに実行する）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_denchoho_verify.py <stage> [args]
  stage:
    laws          e-Gov 法令API v2 から法令本文（JSON）を取得し、条・項・号の単位でテキストに書き出す（検証者が読むため）
    lawcheck DIR  laws で取得した DIR（.work/downloads/<ts>_IMPL_denchoho_verify_laws）の JSON を読み、
                  文書の主張（条番号・文言・版・施行日）を CHECKS の文字列照合で確かめる
    nta           国税庁の資料（PDF・HTML・docx・xlsx）を新しい空のディレクトリに取得し、SHA-256・Last-Modified を記録する。
                  HTML は本文のテキスト、docx・xlsx は zip の中の XML から文字だけを取り出す（展開・実行はしない）
    nta2          実測の文書 §4 の表のうち nta で取っていない残りのページ・資料を同じ方法で取得する
    ntacompare    実測の文書 §4 の表と nta / nta2 の取得記録（バイト数・Last-Modified・SHA-256）を照合する
    calc          保存期間の起算日・満了日（民法第143条の読み方）と、3月15日の曜日を計算する

- 標準ライブラリのみ。User-Agent は okura-gov-research/0.1。リクエストの間は 1.5 秒あける。個人の情報は送らない。
- 取得したもの（信頼できないデータ）は、実行ごとに新しい空のディレクトリ .work/downloads/<ts>_IMPL_denchoho_verify_<stage>/ に置く。
  その中ではインタプリタ・ツールを実行しない（このスクリプトは scripts/ にあり、パスを引数で渡して読むだけ）。
- 出力は scripts/results/IMPL_denchoho_verify/。
- e-Gov API の使い方は scripts/R1_egov_articles.py・scripts/R4_fetch_laws.py を読んで書いた（import はしていない。
  テキスト化の関数は検証の独立性のため自分で書き直した）。
"""
import datetime
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
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "scripts" / "results" / "IMPL_denchoho_verify"
UA = "okura-gov-research/0.1"
API = "https://laws.e-gov.go.jp/api/2"
SLEEP = 1.5

# ---------------------------------------------------------------- e-Gov
LAWS = {
    # 略称: (law_id, [asof...])
    "denchou": ("410AC0000000025", ["2021-12-31", "2022-01-01", "2023-12-31", "2024-01-01", "2025-12-31", "2026-11-09", "2026-12-31", "2027-01-01"]),
    "denchou-ki": ("410M50000040043", ["2021-12-31", "2022-01-01", "2023-12-31", "2024-01-01", "2025-12-31", "2026-11-09", "2026-12-31", "2027-01-01"]),
    "shotoku": ("340AC0000000033", ["2025-12-31", "2026-11-09", "2026-12-31"]),
    "shotoku-ki": ("340M50000040011", ["2025-12-31", "2026-11-09", "2026-12-31"]),
    # 文書では「取得していない」とされていた所得税法施行令第195条を確かめるため
    "shotoku-rei": ("340CO0000000096", ["2026-11-09"]),
    # 期間の計算（民法第138条〜第143条）
    "minpo": ("129AC0000000089", ["2026-11-09"]),
    # 期限が休日に当たる場合（国税通則法第10条第2項）
    "tsusoku": ("337AC0000000066", ["2026-11-09"]),
}
# 書き出す条（本則）。None は書き出さない（lawcheck だけで使う）
DUMP_ARTS = {
    "denchou": ["2", "4", "7", "8"],
    "denchou-ki": ["2", "4", "5"],
    "shotoku": ["2", "120", "148", "150", "232"],
    "shotoku-ki": ["63", "102"],
    "shotoku-rei": ["195"],
    "minpo": ["138", "139", "140", "141", "142", "143"],
    "tsusoku": ["10"],
}
DUMP_SUPPL = {
    "denchou": ["令和三年三月三一日法律第一一号", "令和七年三月三一日法律第一三号"],
    "denchou-ki": ["令和三年三月三一日財務省令第二五号", "令和三年一二月二七日財務省令第八〇号",
                   "令和五年三月三一日財務省令第二二号", "令和七年三月三一日財務省令第二八号"],
}


def http_get(url, accept="*/*"):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            body, st, hdr = r.read(), r.status, dict(r.headers)
    except urllib.error.HTTPError as e:
        body, st, hdr = e.read(), e.code, dict(e.headers or {})
    time.sleep(SLEEP)
    return st, body, hdr


def txt(n):
    """要素の文字だけを連結する（ルビの読み Rt は落とす）。"""
    if isinstance(n, str):
        return n
    if n.get("tag") == "Rt":
        return ""
    return "".join(txt(c) for c in n.get("children", []))


def kids(n, tag=None):
    return [c for c in n.get("children", []) if isinstance(c, dict) and (tag is None or c.get("tag") == tag)]


def iter_nodes(n, path=()):
    if isinstance(n, dict):
        yield n, path
        for c in n.get("children", []):
            yield from iter_nodes(c, path + (n.get("tag"),))


def main_articles(root):
    return {n["attr"].get("Num"): n for n, p in iter_nodes(root) if n.get("tag") == "Article" and "SupplProvision" not in p}


def suppl_blocks(root, amend):
    return [n for n, p in iter_nodes(root) if n.get("tag") == "SupplProvision" and n.get("attr", {}).get("AmendLawNum") == amend]


def suppl_articles(root, amend):
    out = {}
    for s in suppl_blocks(root, amend):
        for n, p in iter_nodes(s):
            if n.get("tag") == "Article":
                out.setdefault(n["attr"].get("Num"), n)
    return out


def flatten(node, label, out):
    """条・項・号・イロハの単位で (ラベル, そのレベルの文だけ) を out に積む。"""
    tag = node.get("tag")
    if tag == "Article":
        cap = "".join(txt(c) for c in kids(node, "ArticleCaption"))
        out.append((label, f"[見出し]{cap}"))
        for p in kids(node, "Paragraph"):
            flatten(p, f"{label}-{p['attr'].get('Num')}", out)
        return
    sub = {"Paragraph": "Item", "Item": "Subitem1", "Subitem1": "Subitem2", "Subitem2": "Subitem3", "Subitem3": "Subitem4"}
    sent_tag = {"Paragraph": "ParagraphSentence", "Item": "ItemSentence", "Subitem1": "Subitem1Sentence",
                "Subitem2": "Subitem2Sentence", "Subitem3": "Subitem3Sentence", "Subitem4": "Subitem4Sentence"}
    if tag in sent_tag:
        title = "".join(txt(c) for c in kids(node) if c.get("tag", "").endswith("Title") or c.get("tag") == "ParagraphNum")
        body = "　".join(txt(c) for c in kids(node, sent_tag[tag]))
        out.append((label, f"{title}　{body}".strip()))
        # 号の中の表など（TableStruct）も文字だけ拾う
        for c in kids(node):
            if c.get("tag") in ("TableStruct", "List", "AmendProvision"):
                out.append((label + "#" + c.get("tag"), txt(c)))
        if tag in sub:
            for c in kids(node, sub[tag]):
                flatten(c, f"{label}-{c['attr'].get('Num')}", out)


def provision_map(art, prefix):
    out = []
    flatten(art, prefix, out)
    return dict(out), out


def get_text(root, spec):
    """spec = ('main' | <AmendLawNum>, '条-項-号-...')。対応するレベルの文を返す（下位を含めない）。
    ラベルが条だけ（'7'）なら条全体（全レベルを連結）。"""
    where, path = spec
    if path == "#block":  # 附則のかたまり全体（条に分かれていない附則もある）
        bl = suppl_blocks(root, where)
        return "\n".join(txt(b) for b in bl) if bl else None
    arts =main_articles(root) if where == "main" else suppl_articles(root, where)
    anum = path.split("-")[0].rstrip("*")
    art = arts.get(anum)
    if art is None:
        return None
    m, seq = provision_map(art, anum)
    if path.rstrip("*") == anum:  # 条全体
        return "\n".join(f"{k}: {v}" for k, v in seq)
    if path.endswith("*"):  # 下位を含めて連結
        base = path[:-1]
        return "\n".join(f"{k}: {v}" for k, v in seq if k == base or k.startswith(base + "-") or k.startswith(base + "#"))
    return m.get(path)


def stage_laws():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_IMPL_denchoho_verify_laws"
    dl.mkdir(parents=True, exist_ok=False)
    out = OUT / "laws"
    out.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "fetches": [], "revisions": {}}
    for short, (law_id, asofs) in LAWS.items():
        for asof in asofs:
            url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode({"response_format": "json", "asof": asof})
            st, body, hdr = http_get(url, "application/json")
            p = dl / f"{short}_{asof}.json"
            p.write_bytes(body)
            rec = {"short": short, "law_id": law_id, "asof": asof, "url": url, "status": st, "bytes": len(body),
                   "sha256": hashlib.sha256(body).hexdigest()}
            if st == 200:
                d = json.loads(body)
                ri = d.get("revision_info") or {}
                for k in ("law_revision_id", "law_title", "amendment_law_num", "amendment_promulgate_date",
                          "amendment_enforcement_date", "current_revision_status", "updated"):
                    rec[k] = ri.get(k)
                root = d["law_full_text"]
                lines = [f"# {short} {law_id} asof={asof}", f"# {url}",
                         f"# law_revision_id={rec['law_revision_id']} 改正法令={rec['amendment_law_num']} 施行日={rec['amendment_enforcement_date']} 状態={rec['current_revision_status']}",
                         f"# SHA-256(JSON)={rec['sha256']}", ""]
                arts = main_articles(root)
                for a in DUMP_ARTS.get(short, []):
                    if a not in arts:
                        lines.append(f"## 本則 第{a}条: なし")
                        continue
                    _, seq = provision_map(arts[a], a)
                    lines.append(f"## 本則 Num={a}")
                    lines += [f"{k}: {v}" for k, v in seq]
                    lines.append("")
                for amend in DUMP_SUPPL.get(short, []):
                    sa = suppl_articles(root, amend)
                    lines.append(f"## 附則 {amend}（条 {len(sa)} 個）")
                    for num, art in sa.items():
                        _, seq = provision_map(art, f"附{num}")
                        lines += [f"{k}: {v}" for k, v in seq]
                    lines.append("")
                (out / f"{short}_{asof}.txt").write_text("\n".join(lines), encoding="utf-8")
            log["fetches"].append(rec)
            print("ok", short, asof, st, rec.get("law_revision_id"), flush=True)
        if short in ("denchou", "denchou-ki"):
            url = f"{API}/law_revisions/{law_id}?" + urllib.parse.urlencode({"response_format": "json"})
            st, body, hdr = http_get(url, "application/json")
            (dl / f"revisions_{short}.json").write_bytes(body)
            revs = []
            if st == 200:
                for rv in json.loads(body).get("revisions", []):
                    revs.append({k: rv.get(k) for k in ("law_revision_id", "amendment_law_num", "amendment_promulgate_date",
                                                        "amendment_enforcement_date", "current_revision_status")})
            log["revisions"][short] = {"url": url, "status": st, "revisions": revs}
    (out / "fetch_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", dl)


# 文書の主張の照合。 (ID, 文書の箇所, 略称, asof, (where, path), [含まれるべき文字列], 説明)
R3_11 = "令和三年三月三一日法律第一一号"
R7_13 = "令和七年三月三一日法律第一三号"
R3_25 = "令和三年三月三一日財務省令第二五号"
R3_80 = "令和三年一二月二七日財務省令第八〇号"
R5_22 = "令和五年三月三一日財務省令第二二号"
R7_28 = "令和七年三月三一日財務省令第二八号"
CHECKS = [
    # ---- 電帳法
    ("L-2-4", "PS §1", "denchou", "2026-11-09", ("main", "2-1-4"), ["保存義務者", "国税に関する法律の規定により国税関係帳簿書類の保存をしなければならないこととされている者"], "法第2条第4号"),
    ("L-2-5", "PS §1", "denchou", "2026-11-09", ("main", "2-1-5"), ["電子取引", "注文書、契約書、送り状、領収書、見積書その他これらに準ずる書類に通常記載される事項", "授受を電磁的方式により行う取引"], "法第2条第5号"),
    ("L-7", "PS §1", "denchou", "2026-11-09", ("main", "7-1"), ["所得税（源泉徴収に係る所得税を除く。）及び法人税に係る保存義務者は、電子取引を行った場合には、財務省令で定めるところにより、当該電子取引の取引情報に係る電磁的記録を保存しなければならない。"], "法第7条（現行）"),
    ("L-7-2027", "PS §1", "denchou", "2027-01-01", ("main", "7-1"), ["所得税（源泉徴収に係る所得税を除く。）及び法人税に係る保存義務者は、電子取引を行った場合には、財務省令で定めるところにより、当該電子取引の取引情報に係る電磁的記録を保存しなければならない。"], "法第7条（2027-01-01版も同文）"),
    ("L-8-2", "PS §1", "denchou", "2026-11-09", ("main", "8-2"), ["前条に規定する財務省令で定めるところに従って保存が行われている電磁的記録", "国税関係書類以外の書類とみなす"], "法第8条第2項"),
    ("L-8-3-2", "PS §1", "denchou", "2026-11-09", ("main", "8-3-2"), ["所得税法第百五十条第一項第一号（青色申告の承認の取消し）", "「帳簿書類）」とあるのは、「帳簿書類）又は", "第七条（電子取引の取引情報に係る電磁的記録の保存）のいずれか"], "法第8条第3項第2号"),
    ("L-8-5", "PS §1", "denchou", "2026-11-09", ("main", "8-5"), ["前条の保存義務者により行われた電子取引の取引情報に係る電磁的記録", "第六十八条第一項から第三項まで（重加算税）", "百分の十の割合"], "法第8条第5項（現行）"),
    ("L-8-5-2027", "PS §1", "denchou", "2027-01-01", ("main", "8-5"), ["特定電磁的記録", "その保存が国税の納税義務の適正な履行に資するものとして財務省令で定める要件を満たしている場合における当該特定電磁的記録", "百分の十"], "法第8条第5項（2027-01-01版）"),
    ("L-4-1", "PS §3", "denchou", "2026-11-09", ("main", "4-1"), ["国税関係帳簿（財務省令で定めるものを除く。", "自己が最初の記録段階から一貫して電子計算機を使用して作成する場合には", "代えることができる"], "法第4条第1項"),
    ("L-4-3", "PS §4", "denchou", "2026-11-09", ("main", "4-3"), ["財務省令で定める装置により電磁的記録に記録する場合"], "法第4条第3項（スキャナ保存）"),
    ("L-S-R3-1-5", "PS §1", "denchou", "2026-11-09", (R3_11, "1-1-5*"), ["令和四年一月一日", "第十二条の規定"], "令和3年法律第11号 附則第1条第5号チ"),
    ("L-S-R3-82-6", "PS §1", "denchou", "2026-11-09", (R3_11, "82-6"), ["新電子帳簿保存法第七条の規定は、令和四年一月一日以後に行う電子取引の取引情報について適用"], "令和3年法律第11号 附則第82条第6項"),
    ("L-S-R7-1-5", "PS §1・§7", "denchou", "2026-11-09", (R7_13, "1-1-5*"), ["令和九年一月一日", "第九条の規定"], "令和7年法律第13号 附則第1条第5号ニ"),
    ("L-S-R7-61", "PS §1・§7", "denchou", "2027-01-01", (R7_13, "61"), ["第八条第五項の規定は、令和九年一月一日以後に", "法定申告期限", "所得税（源泉徴収に係る所得税を除く。"], "令和7年法律第13号 附則第61条（2027-01-01版の本文に収録。現行版の本文には附則第1条と第80条だけ）"),
    ("L-S-R7-61-cur", "PS §1・§7", "denchou", "2026-11-09", (R7_13, "1-1-5-2"), ["附則第六十一条の規定"], "令和7年法律第13号 附則第1条第5号ニ（現行版）"),
    # ---- 規則
    ("K-4-1-place", "PS §2.1", "denchou-ki", "2026-11-09", ("main", "4-1"), ["当該取引情報の受領が書面により行われたとした場合又は当該取引情報の送付が書面により行われその写しが作成されたとした場合に、国税に関する法律の規定により、当該書面を保存すべきこととなる場所に、当該書面を保存すべきこととなる期間"], "規則第4条第1項 柱書（場所・期間）"),
    ("K-4-1-5000", "PS §2.4", "denchou-ki", "2026-11-09", ("main", "4-1"), ["五千万円以下である事業者である場合", "取引年月日その他の日付及び取引先ごとに整理されたもの"], "規則第4条第1項 柱書（検索要件の緩和）"),
    ("K-4-1-1", "PS §2.2", "denchou-ki", "2026-11-09", ("main", "4-1-1"), ["タイムスタンプが付された後", "授受を行うこと"], "規則第4条第1項第1号"),
    ("K-4-1-2", "PS §2.2", "denchou-ki", "2026-11-09", ("main", "4-1-2*"), ["速やかに", "その業務の処理に係る通常の期間を経過した後、速やかに", "事務の処理に関する規程を定めている場合に限る"], "規則第4条第1項第2号"),
    ("K-4-1-3", "PS §2.2", "denchou-ki", "2026-11-09", ("main", "4-1-3*"), ["授受及び当該電磁的記録の保存を行うこと", "訂正又は削除を行うことができないこと"], "規則第4条第1項第3号"),
    ("K-4-1-4", "PS §2.2", "denchou-ki", "2026-11-09", ("main", "4-1-4"), ["当該電磁的記録の記録事項について正当な理由がない訂正及び削除の防止に関する事務処理の規程を定め、当該規程に沿った運用を行い、当該電磁的記録の保存に併せて当該規程の備付けを行うこと"], "規則第4条第1項第4号"),
    ("K-4-2", "PS §2.4", "denchou-ki", "2026-11-09", ("main", "4-2*"), ["業務を行う個人", "その年の前々年", "一月一日から十二月三十一日まで"], "規則第4条第2項（事業者・判定期間・基準期間）"),
    ("K-4-3", "PS §2.6", "denchou-ki", "2026-11-09", ("main", "4-3*"), ["災害その他やむを得ない事情", "相当の理由", "出力することにより作成した書面"], "規則第4条第3項（猶予）"),
    ("K-2-1", "PS §3", "denchou-ki", "2026-11-09", ("main", "2-1"), ["資産、負債及び資本に影響を及ぼす一切の取引につき、正規の簿記の原則", "複式簿記の原則", "以外のもの"], "規則第2条第1項"),
    ("K-2-1-2022", "PS §3", "denchou-ki", "2022-01-01", ("main", "2-1"), ["正規の簿記の原則", "以外のもの"], "規則第2条第1項（2022-01-01版）"),
    ("K-2-2-1", "PS §2.3・§3", "denchou-ki", "2026-11-09", ("main", "2-2-1*"), ["当該保存義務者が開発したプログラム", "イ及びロに掲げる書類を除く"], "規則第2条第2項第1号"),
    ("K-2-2-2", "PS §2.3", "denchou-ki", "2026-11-09", ("main", "2-2-2"), ["整然とした形式及び明瞭な状態で、速やかに出力することができるようにしておくこと"], "規則第2条第2項第2号"),
    ("K-2-6-2", "PS §2.2", "denchou-ki", "2026-11-09", ("main", "2-6-2*"), ["総務大臣が認定する時刻認証業務"], "規則第2条第6項第2号（ロ）"),
    ("K-2-6-5", "PS §2.3", "denchou-ki", "2026-11-09", ("main", "2-6-5*"), ["取引年月日その他の日付、取引金額及び取引先", "範囲を指定して", "二以上の任意の記録項目を組み合わせて"], "規則第2条第6項第5号"),
    ("K-2-6-6", "PS §2.3", "denchou-ki", "2026-11-09", ("main", "2-6-6"), ["第二項第一号の規定は", "準用する"], "規則第2条第6項第6号"),
    ("K-4-1-refs", "PS §2.3", "denchou-ki", "2026-11-09", ("main", "4-1"), ["第二条第二項第二号及び第六項第五号並びに同項第六号において準用する同条第二項第一号（同号イに係る部分に限る。）", "同条第六項第五号（ロ及びハに係る部分に限る。）"], "規則第4条第1項 柱書（引く要件）"),
    ("K-4-1-2023", "PS §2.4", "denchou-ki", "2023-12-31", ("main", "4-1"), ["千万円以下"], "規則第4条第1項（2023-12-31版）"),
    ("K-5-5-2027", "PS §1", "denchou-ki", "2027-01-01", ("main", "5-5*"), ["特定電子計算機処理システム"], "規則第5条第5項（2027-01-01版）"),
    ("K-5-6-2027", "PS §1", "denchou-ki", "2027-01-01", ("main", "5-6*"), ["届出書"], "規則第5条第6項（2027-01-01版）"),
    ("K-S-R5-1", "PS §7", "denchou-ki", "2026-11-09", (R5_22, "1"), ["令和六年一月一日"], "令和5年財務省令第22号 附則第1条"),
    ("K-S-R5-2-2", "PS §7", "denchou-ki", "2026-11-09", (R5_22, "2-2"), ["新令第四条の規定は、施行日以後に行う電子取引の取引情報について適用"], "令和5年財務省令第22号 附則第2条第2項"),
    ("K-S-R3-2-3", "PS §2.6", "denchou-ki", "2026-11-09", (R3_25, "2-3"), ["令和五年十二月三十一日までの間に電子取引を行う場合", "やむを得ない事情があると認め", "出力することにより作成した書面"], "令和3年財務省令第25号 附則第2条第3項（宥恕措置）"),
    ("K-S-R3-80", "PS §2.6", "denchou-ki", "2026-11-09", (R3_80, "#block"), ["令和四年一月一日から施行する"], "令和3年財務省令第80号 附則（条に分かれていない）"),
    ("K-S-R7-28", "PS §0.1・M §2", "denchou-ki", "2026-11-09", (R7_28, "#block"), ["令和九年一月一日から施行する", "「第二条第十五項」を「第二条第十六項」に改める部分", "令和七年四月一日"], "令和7年財務省令第28号 附則"),
    # ---- 所得税法・同施行規則
    ("S-232-1", "PS §5.1", "shotoku", "2026-11-09", ("main", "232-1"), ["不動産所得、事業所得若しくは山林所得を生ずべき業務を行う居住者", "財務省令で定める簡易な方法により記録し"], "所法第232条第1項"),
    ("S-232-2", "PS §5.2", "shotoku", "2026-11-09", ("main", "232-2"), ["雑所得を生ずべき業務を行う居住者", "その年の前々年分のこれらの雑所得を生ずべき業務に係る収入金額が三百万円を超えるもの"], "所法第232条第2項"),
    ("S-232-2-2025", "PS §5.2", "shotoku", "2025-12-31", ("main", "232-2"), ["その年の前々年分のこれらの雑所得を生ずべき業務に係る収入金額が三百万円を超えるもの"], "所法第232条第2項（2025-12-31版）"),
    ("S-232-2-quote", "PS §5.2（文書の書き方のまま）", "shotoku", "2026-11-09", ("main", "232-2"), ["その年の前々年分の当該業務に係る収入金額が三百万円を超えるもの"], "所法第232条第2項：文書の言い回しが原文にあるか"),
    ("S-120-4", "PS §5.4", "shotoku", "2026-11-09", ("main", "120-4*"), ["明細書"], "所法第120条第4項"),
    ("S-120-5", "PS §5.4", "shotoku", "2026-11-09", ("main", "120-5"), ["確定申告期限の翌日から起算して五年を経過する日", "同日前六月以内に", "六月を経過する日", "提示又は提出"], "所法第120条第5項"),
    ("S-120-6", "PS §5.2", "shotoku", "2026-11-09", ("main", "120-6"), ["雑所得を生ずべき業務を行う居住者", "千万円を超えるもの"], "所法第120条第6項"),
    ("S-148-1", "PS §5.3", "shotoku", "2026-11-09", ("main", "148-1"), ["帳簿書類を備え付けて", "保存しなければならない"], "所法第148条第1項"),
    ("S-150-1-1", "PS §1", "shotoku", "2026-11-09", ("main", "150-1-1"), ["第百四十八条第一項（青色申告者の帳簿書類）"], "所法第150条第1項第1号"),
    ("R-63-1", "PS §5.3", "shotoku-ki", "2026-11-09", ("main", "63-1*"), ["七年間", "五年間", "現金預金取引等関係書類"], "所規第63条第1項"),
    ("R-63-2", "PS §5.3", "shotoku-ki", "2026-11-09", ("main", "63-2"), ["前々年分の不動産所得の金額及び事業所得の金額の合計額", "令第百九十五条第一号"], "所規第63条第2項"),
    ("R-63-3", "PS §5.3", "shotoku-ki", "2026-11-09", ("main", "63-3"), ["現金預金取引等関係書類", "現金の収受若しくは払出し又は預貯金の預入若しくは引出しに際して作成されたもの"], "所規第63条第3項"),
    ("R-63-4", "PS §5.1", "shotoku-ki", "2026-11-09", ("main", "63-4*"), ["その閉鎖の日の属する年の翌年三月十五日の翌日", "その作成又は受領の日の属する年の翌年三月十五日の翌日"], "所規第63条第4項（起算日）"),
    ("R-63-5", "PS §5.3", "shotoku-ki", "2026-11-09", ("main", "63-5*"), ["財務大臣"], "所規第63条第5項"),
    ("R-102-2", "PS §5.1", "shotoku-ki", "2026-11-09", ("main", "102-2"), ["財務大臣の定める"], "所規第102条第2項"),
    ("R-102-3", "PS §5.1", "shotoku-ki", "2026-11-09", ("main", "102-3*"), ["棚卸表", "請求書、納品書、送り状、領収書その他これらに類する書類"], "所規第102条第3項"),
    ("R-102-4", "PS §5.1", "shotoku-ki", "2026-11-09", ("main", "102-4"), ["第六十三条第四項（青色申告者の帳簿書類の整理保存）に規定する起算日から七年間", "五年間"], "所規第102条第4項"),
    ("R-102-7", "PS §5.2", "shotoku-ki", "2026-11-09", ("main", "102-7"), ["現金の収受若しくは払出し又は預貯金の預入若しくは引出しに際して作成されたもの"], "所規第102条第7項"),
    ("R-102-8", "PS §5.2", "shotoku-ki", "2026-11-09", ("main", "102-8"), ["翌年三月十五日の翌日から五年間"], "所規第102条第8項"),
    ("O-195", "PS §5.3（未取得とされた箇所）", "shotoku-rei", "2026-11-09", ("main", "195*"), ["三百万円"], "所得税法施行令第195条"),
    ("M-143", "INF I4", "minpo", "2026-11-09", ("main", "143*"), ["起算日に応当する日の前日に満了する"], "民法第143条"),
    ("M-140", "INF I4", "minpo", "2026-11-09", ("main", "140*"), ["期間の初日は、算入しない"], "民法第140条"),
    ("T-10-2", "INF I4", "tsusoku", "2026-11-09", ("main", "10-2"), ["日曜日", "これらの日の翌日をもつてその期限とみなす"], "国税通則法第10条第2項"),
    # ---- 実測（M §2）の版の差分の主張
    ("D-ki-2021-art4", "M §2", "denchou-ki", "2021-12-31", ("main", "4"), ["電子計算機出力マイクロフィルム"], "規則第4条の見出し（2021-12-31版）"),
    ("D-ki-2022-art4", "M §2", "denchou-ki", "2022-01-01", ("main", "4"), ["電子取引の取引情報に係る電磁的記録の保存"], "規則第4条の見出し（2022-01-01版）"),
    ("D-ki-2021-2-1", "M §2", "denchou-ki", "2021-12-31", ("main", "2-1"), ["!正規の簿記の原則"], "規則第2条第1項（2021-12-31版に正規の簿記の文言が無い）"),
    ("D-ki-2022-4-1-2", "M §2", "denchou-ki", "2022-01-01", ("main", "4-1-2"), ["保存を行う者又はその者を直接監督する者に関する情報を確認することができるようにしておくこと"], "規則第4条第1項第2号（2022-01-01版）"),
    ("D-ki-2024-4-1-2", "M §2", "denchou-ki", "2024-01-01", ("main", "4-1-2"), ["!直接監督する者"], "規則第4条第1項第2号（2024-01-01版で削除）"),
    ("D-ki-2022-2-6-2", "M §2", "denchou-ki", "2022-01-01", ("main", "2-6-2*"), ["一般財団法人日本データ通信協会"], "規則第2条第6項第2号ロ（2022-01-01版）"),
    ("D-ki-2023-2-6-2", "M §2", "denchou-ki", "2023-12-31", ("main", "2-6-2*"), ["総務大臣が認定する時刻認証業務", "!日本データ通信協会"], "規則第2条第6項第2号ロ（2023-12-31版）"),
    ("D-ki-2023-2-6-3", "M §2", "denchou-ki", "2023-12-31", ("main", "2-6-3"), ["入力を行う者又はその者を直接監督する者に関する情報"], "規則第2条第6項第3号（2023-12-31版）"),
    ("D-ki-2024-2-6-3", "M §2", "denchou-ki", "2024-01-01", ("main", "2-6-3"), ["!入力を行う者"], "規則第2条第6項第3号（2024-01-01版）"),
    ("D-ki-2023-4-3", "M §2", "denchou-ki", "2023-12-31", ("main", "4-3"), ["!相当の理由"], "規則第4条第3項（2023-12-31版に猶予の文言なし）"),
    ("D-ki-2024-2-9-1", "M §2", "denchou-ki", "2024-01-01", ("main", "2-9-1"), ["第二条第十五項"], "規則第2条第9項第1号（2024-01-01版）"),
    ("D-ki-2025-2-9-1", "M §2", "denchou-ki", "2025-12-31", ("main", "2-9-1"), ["第二条第十六項"], "規則第2条第9項第1号（2025-12-31版）"),
    ("D-ki-2027-4-1", "M §2", "denchou-ki", "2027-01-01", ("main", "4-1"), ["以下この項及び第三項並びに次条第五項第一号において同じ。"], "規則第4条第1項（2027-01-01版）"),
    ("D-sho-2025-120-4", "M §2", "shotoku", "2025-12-31", ("main", "120-4*"), ["社会保険診療報酬支払基金"], "所法第120条第4項（2025-12-31版）"),
    ("D-sho-2026-120-4", "M §2", "shotoku", "2026-11-09", ("main", "120-4*"), ["医療情報基盤・診療報酬審査支払機構", "!社会保険診療報酬支払基金"], "所法第120条第4項（2026-11-09版）"),
    ("D-ki-2026-5-5", "M §2", "denchou-ki", "2026-12-31", ("main", "5-5"), ["法第八条第四項に規定する財務省令で定める要件"], "規則第5条第5項（2026-12-31版＝優良な電子帳簿の要件）"),
    ("D-ki-2027-5-4", "M §2", "denchou-ki", "2027-01-01", ("main", "5-4"), ["法第八条第四項に規定する財務省令で定める要件"], "規則第5条第4項（2027-01-01版で第5項から繰り上がり）"),
    # ---- 公開資料の情報 §4（スキャナ保存の要件の要約）
    ("K-2-6-2-scan", "PS §4", "denchou-ki", "2026-11-09", ("main", "2-6-2*"), ["ロに掲げる要件を除く", "二百ドット以上", "二百五十六階調以上", "訂正又は削除を行うことができないこと"], "規則第2条第6項第2号（スキャナ・タイムスタンプ・訂正削除）"),
    ("K-2-6-4-scan", "PS §4", "denchou-ki", "2026-11-09", ("main", "2-6-4"), ["カラーディスプレイ"], "規則第2条第6項第4号"),
]


def stage_lawcheck(dl):
    dl = pathlib.Path(dl)
    cache = {}
    res = []
    for cid, where_doc, short, asof, spec, needles, desc in CHECKS:
        key = (short, asof)
        if key not in cache:
            cache[key] = json.loads((dl / f"{short}_{asof}.json").read_bytes())
        d = cache[key]
        t = get_text(d["law_full_text"], spec)
        missing = [n for n in needles if t is None or (n[1:] in t if n.startswith("!") else n not in t)]
        res.append({"id": cid, "doc": where_doc, "law": short, "asof": asof, "spec": list(spec), "desc": desc,
                    "law_revision_id": (d.get("revision_info") or {}).get("law_revision_id"),
                    "found": t is not None, "missing": missing, "ok": t is not None and not missing,
                    "text": t})
    # 版どうしの比較（同じ文言か）
    def same(short, a1, a2, spec):
        for a in (a1, a2):
            if (short, a) not in cache:
                cache[(short, a)] = json.loads((dl / f"{short}_{a}.json").read_bytes())
        t1 = get_text(cache[(short, a1)]["law_full_text"], spec)
        t2 = get_text(cache[(short, a2)]["law_full_text"], spec)
        return t1 is not None and t1 == t2
    comps = []
    for short, a1, a2, spec, desc in [
        ("denchou-ki", "2024-01-01", "2026-11-09", ("main", "4"), "規則第4条：2024-01-01版と現行版が同文か"),
        ("denchou-ki", "2026-11-09", "2026-12-31", ("main", "4"), "規則第4条：現行版と2026-12-31版が同文か"),
        ("denchou-ki", "2026-12-31", "2027-01-01", ("main", "4"), "規則第4条：2026-12-31版と2027-01-01版が同文か"),
        ("denchou-ki", "2022-01-01", "2026-11-09", ("main", "2-1"), "規則第2条第1項：2022-01-01版と現行版が同文か"),
        ("denchou", "2026-11-09", "2027-01-01", ("main", "7"), "法第7条：現行版と2027-01-01版が同文か"),
        ("denchou", "2025-12-31", "2026-11-09", ("main", "8"), "法第8条：2025-12-31版と現行版が同文か"),
        ("shotoku", "2025-12-31", "2026-11-09", ("main", "232"), "所法第232条：2025-12-31版と現行版が同文か"),
        ("shotoku", "2026-11-09", "2026-12-31", ("main", "232"), "所法第232条：現行版と2026-12-31版が同文か"),
        ("shotoku", "2025-12-31", "2026-11-09", ("main", "148"), "所法第148条：2025-12-31版と現行版が同文か"),
        ("shotoku", "2025-12-31", "2026-11-09", ("main", "120-5"), "所法第120条第5項：2025-12-31版と現行版が同文か"),
        ("shotoku", "2025-12-31", "2026-11-09", ("main", "120-4*"), "所法第120条第4項：2025-12-31版と現行版が同文か"),
        ("shotoku", "2025-12-31", "2026-11-09", ("main", "120-1*"), "所法第120条第1項：2025-12-31版と現行版が同文か"),
        ("shotoku", "2025-12-31", "2026-11-09", ("main", "120-6"), "所法第120条第6項：2025-12-31版と現行版が同文か"),
        ("shotoku", "2026-11-09", "2026-12-31", ("main", "120"), "所法第120条：現行版と2026-12-31版が同文か"),
        ("shotoku", "2025-12-31", "2026-11-09", ("main", "143"), "所法第143条：2025-12-31版と現行版が同文か"),
        ("shotoku", "2026-11-09", "2026-12-31", ("main", "143"), "所法第143条：現行版と2026-12-31版が同文か"),
        ("shotoku", "2026-11-09", "2026-12-31", ("main", "148"), "所法第148条：現行版と2026-12-31版が同文か"),
        ("shotoku-ki", "2025-12-31", "2026-11-09", ("main", "63"), "所規第63条：2025-12-31版と現行版が同文か"),
        ("shotoku-ki", "2026-11-09", "2026-12-31", ("main", "63"), "所規第63条：現行版と2026-12-31版が同文か"),
        ("shotoku-ki", "2025-12-31", "2026-11-09", ("main", "102"), "所規第102条：2025-12-31版と現行版が同文か"),
        ("shotoku-ki", "2026-11-09", "2026-12-31", ("main", "102"), "所規第102条：現行版と2026-12-31版が同文か"),
    ]:
        comps.append({"desc": desc, "law": short, "asof": [a1, a2], "spec": list(spec), "same": same(short, a1, a2, spec)})
    # 実測 §2 が「取り出した条」に挙げた所法第231条の2 が、各版の本則にあるか
    exists = []
    for a in ("2025-12-31", "2026-11-09", "2026-12-31"):
        if ("shotoku", a) not in cache:
            cache[("shotoku", a)] = json.loads((dl / f"shotoku_{a}.json").read_bytes())
        arts = main_articles(cache[("shotoku", a)]["law_full_text"])
        exists.append({"law": "shotoku", "asof": a, "article": "231_2", "exists": "231_2" in arts,
                       "articles_231": sorted(k for k in arts if k.split("_")[0] == "231")})
    out = OUT / "laws"
    out.mkdir(parents=True, exist_ok=True)
    (out / "lawcheck.json").write_text(json.dumps({"download_dir": str(dl), "checks": res, "comparisons": comps, "existence": exists}, ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["# lawcheck（文書の主張と e-Gov 原文の文字列照合）", f"- 入力：{dl}", "",
          "| ID | 文書の箇所 | 条 | asof | 版 | 結果 | 見つからない文字列 |", "|---|---|---|---|---|---|---|"]
    for r in res:
        st = "OK" if r["ok"] else ("該当条なし" if not r["found"] else "不一致")
        md.append(f"| {r['id']} | {r['doc']} | {r['desc']} | {r['asof']} | {r['law_revision_id']} | {st} | {'／'.join(r['missing'])} |")
    md += ["", "## 版どうしの比較", "", "| 比較 | 同文 |", "|---|---|"]
    md += [f"| {c['desc']} | {c['same']} |" for c in comps]
    md += ["", "## 条の有無", ""] + [f"- 所法 asof={e['asof']}：第231条の2 は本則に{'ある' if e['exists'] else '無い'}（231 で始まる条：{e['articles_231']}）" for e in exists]
    md += ["", "## 照合した本文（全文）", ""]
    for r in res:
        md += [f"### {r['id']} {r['desc']}（asof={r['asof']}）", "```", r["text"] or "(なし)", "```", ""]
    (out / "lawcheck.md").write_text("\n".join(md), encoding="utf-8")
    bad = [r["id"] for r in res if not r["ok"]]
    print("checks", len(res), "not ok", bad)
    print("comparisons", [(c["desc"], c["same"]) for c in comps])
    print("existence", exists)


# ---------------------------------------------------------------- 国税庁
NTA = "https://www.nta.go.jp"
NTA_TARGETS = [
    ("robots", NTA + "/robots.txt"),
    ("qa-index", NTA + "/law/joho-zeikaishaku/sonota/jirei/4-3.htm"),
    ("hourei-tsutatsu", NTA + "/law/joho-zeikaishaku/sonota/jirei/03.htm"),
    ("samples-page", NTA + "/law/joho-zeikaishaku/sonota/jirei/0021006-031.htm"),
    ("qa-dentori-r0807", NTA + "/law/joho-zeikaishaku/sonota/jirei/pdf/0026007-006_05.pdf"),
    ("qa-chobo-r0807", NTA + "/law/joho-zeikaishaku/sonota/jirei/pdf/0026007-006_01.pdf"),
    ("tsutatsu-r0706", NTA + "/law/joho-zeikaishaku/sonota/jirei/pdf/0025006-066.pdf"),
    ("pamph-dentori-r0611", NTA + "/law/joho-zeikaishaku/sonota/jirei/tokusetsu/pdf/0024011-003_01.pdf"),
    ("pamph-dentori-check-r0611", NTA + "/law/joho-zeikaishaku/sonota/jirei/tokusetsu/pdf/0024011-003_02.pdf"),
    ("pamph-chobo-r0507", NTA + "/law/joho-zeikaishaku/sonota/jirei/tokusetsu/pdf/0023006-085_02.pdf"),
    ("pamph-r0806", NTA + "/law/joho-zeikaishaku/sonota/jirei/tokusetsu/pdf/0026006-122.pdf"),
    ("kitei-kojin", NTA + "/law/joho-zeikaishaku/sonota/jirei/word/0021006-031_e.docx"),
    ("sakuinbo", NTA + "/law/joho-zeikaishaku/sonota/jirei/excel/0021006-031_c.xlsx"),
]


# 実測 §4 の表のうち、nta で取り直していないもの
NTA_TARGETS2 = [
    ("jirei-index", NTA + "/law/joho-zeikaishaku/sonota/jirei/index.htm"),
    ("tokusetsu-index", NTA + "/law/joho-zeikaishaku/sonota/jirei/tokusetsu/index.htm"),
    ("pamphlet", NTA + "/law/joho-zeikaishaku/sonota/jirei/08.htm"),
    ("tokusetsu-01", NTA + "/law/joho-zeikaishaku/sonota/jirei/tokusetsu/01.htm"),
    ("tokusetsu-02", NTA + "/law/joho-zeikaishaku/sonota/jirei/tokusetsu/02.htm"),
    ("qa-dentori-r0807-diff", NTA + "/law/joho-zeikaishaku/sonota/jirei/pdf/0026007-006_06.pdf"),
    ("tsutatsu-kaisetsu-r0706", NTA + "/law/joho-zeikaishaku/sonota/2506/pdf/01-4.pdf"),
    ("pamph-r7kaisei", NTA + "/law/joho-zeikaishaku/sonota/jirei/pdf/0025003-097_01.pdf"),
    ("kitei-hojin", NTA + "/law/joho-zeikaishaku/sonota/jirei/word/0021006-031_d.docx"),
]


def stage_ntacompare():
    """実測の文書 §4 の表（URL・HTTP・バイト・Last-Modified・SHA-256）と、nta / nta2 の取得記録を照合する。"""
    doc = (ROOT / "docs" / "measurements" / "20261109_impl-prep_denchoho-fetch.md").read_text(encoding="utf-8")
    rows = {}
    for line in doc.splitlines():
        m = re.match(r"\|\s*([^|]+?)\s*\|\s*(https://www\.nta\.go\.jp/\S+?)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*([0-9a-f]{64})\s*\|", line)
        if m:
            rows[m.group(2)] = {"key": m.group(1), "status": int(m.group(3)), "bytes": int(m.group(4)), "lm": m.group(5), "sha256": m.group(6)}
    mine = {}
    for sub in ("nta", "nta2"):
        f = OUT / sub / "fetch_log.json"
        if f.exists():
            for r in json.loads(f.read_text(encoding="utf-8"))["fetches"]:
                mine[r["url"]] = r
    out = []
    for url, d in rows.items():
        r = mine.get(url)
        if r is None:
            out.append({"url": url, "doc": d, "result": "取り直していない"})
            continue
        lm = r.get("last_modified")
        lm_iso = datetime.datetime.strptime(lm, "%a, %d %b %Y %H:%M:%S GMT").date().isoformat() if lm else None
        out.append({"url": url, "doc": d, "mine": {"status": r["status"], "bytes": r["bytes"], "lm": lm_iso, "sha256": r["sha256"]},
                    "status_eq": d["status"] == r["status"], "bytes_eq": d["bytes"] == r["bytes"], "lm_eq": d["lm"] == lm_iso,
                    "sha_eq": d["sha256"] == r["sha256"]})
    (OUT / "ntacompare.json").write_text(json.dumps({"rows_in_doc": len(rows), "compared": out}, ensure_ascii=False, indent=1), encoding="utf-8")
    for o in out:
        print(o["doc"]["key"], o.get("result") or all(o[k] for k in ("status_eq", "bytes_eq", "lm_eq", "sha_eq")))
    print("rows_in_doc", len(rows))


class HtmlText(html.parser.HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "dt", "dd", "table", "td", "th", "title"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.links, self.skip, self.href = [], [], 0, None

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag == "a":
            self.href = dict(attrs).get("href")
            self.atext = []

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip -= 1
        if tag == "a" and self.href is not None:
            self.links.append((self.href, "".join(self.atext).strip()))
            self.href = None

    def handle_data(self, data):
        if self.skip:
            return
        self.parts.append(data)
        if self.href is not None:
            self.atext.append(data)


def decode_html(body, hdr):
    m = re.search(rb'charset=["\']?([A-Za-z0-9_\-]+)', body[:2000])
    enc = (m.group(1).decode() if m else None) or "utf-8"
    try:
        return body.decode(enc, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def zip_text(path, member_re):
    """zip の中の XML から <w:t> / <t> の文字だけを取り出す（展開しない）。"""
    out = []
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if re.fullmatch(member_re, name):
                info = z.getinfo(name)
                if info.file_size > 20 * 1024 * 1024:
                    continue
                x = z.read(name).decode("utf-8", errors="replace")
                x = re.sub(r"<rPh\b.*?</rPh>", "", x, flags=re.S)  # ふりがなを除く
                if "worksheets" in name:
                    # セルの番地・型・値（共有文字列は番号のまま。数値の日付・金額を確かめるため）
                    for row in re.findall(r"<row\b.*?</row>", x, flags=re.S):
                        cells = re.findall(r'<c r="([A-Z]+\d+)"([^>]*)>(?:.*?<v>([^<]*)</v>)?', row, flags=re.S)
                        shared = 't="s"'
                        s = " ".join(r + ("(s)" if shared in a else "") + "=" + v for r, a, v in cells if v)
                        if s:
                            out.append(f"[{name}] {s}")
                    continue
                for para in re.split(r"</w:p>|</row>|</si>", x):
                    s = "".join(re.findall(r"<(?:w:)?t(?:\s[^>]*)?>([^<]*)</(?:w:)?t>", para))
                    if s.strip():
                        out.append(f"[{name}] {s}")
    return "\n".join(out)


def stage_nta(targets=None, sub="nta"):
    targets = targets or NTA_TARGETS
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_IMPL_denchoho_verify_{sub}"
    dl.mkdir(parents=True, exist_ok=False)
    out = OUT / sub
    out.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "fetches": []}
    for key, url in targets:
        st, body, hdr = http_get(url)
        ext = pathlib.PurePosixPath(urllib.parse.urlparse(url).path).suffix or ".bin"
        p = dl / f"{key}{ext}.download"  # 拡張子を変えて、関連付けで開かれないようにする
        p.write_bytes(body)
        rec = {"key": key, "url": url, "status": st, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
               "last_modified": hdr.get("Last-Modified"), "content_type": hdr.get("Content-Type"),
               "saved": str(p.relative_to(ROOT)).replace("\\", "/")}
        if st == 200 and ext in (".htm", ".html", ".txt"):
            t = decode_html(body, hdr) if ext != ".txt" else body.decode("utf-8", errors="replace")
            hp = HtmlText()
            hp.feed(t)
            text = re.sub(r"\n\s*\n+", "\n", "".join(hp.parts))
            (out / f"{key}.txt").write_text(text, encoding="utf-8")
            (out / f"{key}.links.tsv").write_text("\n".join(f"{urllib.parse.urljoin(url, h or '')}\t{a}" for h, a in hp.links), encoding="utf-8")
        if st == 200 and ext == ".docx":
            (out / f"{key}.txt").write_text(zip_text(p, r"word/document\.xml"), encoding="utf-8")
        if st == 200 and ext == ".xlsx":
            (out / f"{key}.txt").write_text(zip_text(p, r"xl/(sharedStrings|worksheets/sheet\d+)\.xml"), encoding="utf-8")
        log["fetches"].append(rec)
        print("ok", key, st, len(body), rec["last_modified"], flush=True)
    (out / "fetch_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", dl)


# ---------------------------------------------------------------- 計算
def add_years(d, n):
    try:
        return d.replace(year=d.year + n)
    except ValueError:  # 2月29日
        return d.replace(year=d.year + n, month=3, day=1)


def kisanbi(d):
    """所規第63条第4項：作成・受領（帳簿は閉鎖）の日の属する年の翌年3月15日の翌日。"""
    return datetime.date(d.year + 1, 3, 15) + datetime.timedelta(days=1)


def manryo(start, years):
    """起算日 start を初日として算入し、民法第143条第2項（最後の年においてその起算日に応当する日の前日に満了）で読む。"""
    return add_years(start, years) - datetime.timedelta(days=1)


def manryo_shonichi_fusannyu(start, years):
    """比較用：起算日の翌日から数える（民法第140条の初日不算入をさらに当てはめた読み）。"""
    return manryo(start + datetime.timedelta(days=1), years)


def stage_calc():
    out = OUT / "calc"
    out.mkdir(parents=True, exist_ok=True)
    wd = "月火水木金土日"
    rows = []
    # 文書（推測 I4）の表の再計算
    cases = [("令和7年中に受け取った領収書データ", datetime.date(2025, 6, 1), "2026-03-16", "2031-03-15", "2033-03-15"),
             ("令和8年中に受け取った請求書データ", datetime.date(2026, 11, 9), "2027-03-16", "2032-03-15", "2034-03-15"),
             ("令和7年分の台帳（12月31日に閉鎖）", datetime.date(2025, 12, 31), "2026-03-16", None, "2033-03-15"),
             ("令和8年分の台帳", datetime.date(2026, 12, 31), "2027-03-16", None, "2034-03-15")]
    for name, d, e_k, e5, e7 in cases:
        k = kisanbi(d)
        m5, m7 = manryo(k, 5), manryo(k, 7)
        rows.append({"もの": name, "日付": d.isoformat(), "起算日": k.isoformat(), "起算日(文書)": e_k,
                     "5年満了": m5.isoformat(), "5年満了(文書)": e5, "7年満了": m7.isoformat(), "7年満了(文書)": e7,
                     "一致": k.isoformat() == e_k and (e5 is None or m5.isoformat() == e5) and m7.isoformat() == e7,
                     "参考_初日不算入で読んだ7年満了": manryo_shonichi_fusannyu(k, 7).isoformat()})
    # 医療費（所法第120条第5項）：確定申告期限の翌日から起算して5年を経過する日
    med = []
    for year in (2025, 2026):
        d315 = datetime.date(year + 1, 3, 15)
        kigen = d315
        while kigen.weekday() >= 5:  # 土日（祝日は3月15日前後に無い年だけを対象に、ここでは土日だけ見る）
            kigen += datetime.timedelta(days=1)
        start = kigen + datetime.timedelta(days=1)
        med.append({"年分": year, "3月15日": d315.isoformat(), "曜日": wd[d315.weekday()],
                    "期限（土日なら翌月曜。国税通則法第10条第2項）": kigen.isoformat(),
                    "起算日": start.isoformat(), "5年を経過する日": manryo(start, 5).isoformat()})
    res = {"storage": rows, "medical": med,
           "note": "manryo は起算日を初日に算入し民法第143条第2項で満了日を求める。祝日は考慮していない（3月15日前後の祝日は春分の日のみで、15〜17日には当たらない年を対象にした）。"}
    (out / "calc.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    st = sys.argv[1] if len(sys.argv) > 1 else ""
    if st == "laws":
        stage_laws()
    elif st == "lawcheck":
        stage_lawcheck(sys.argv[2])
    elif st == "nta":
        stage_nta()
    elif st == "nta2":
        stage_nta(NTA_TARGETS2, "nta2")
    elif st == "ntacompare":
        stage_ntacompare()
    elif st == "calc":
        stage_calc()
    else:
        print(__doc__)
        sys.exit(2)
