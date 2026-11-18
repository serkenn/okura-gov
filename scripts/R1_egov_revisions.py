"""R1: e-Gov 法令API v2 で、対象法令の改正履歴と「更新された法令」を取れるかを実測する。

実行:  python -I scripts/R1_egov_revisions.py
標準ライブラリのみ。リクエストの間は 1.5 秒あける。

やること
 1. 対象法令ごとに /law_revisions/{law_id} を叩き、改正履歴（施行日・改正法令・状態・更新日時）を表にする。
 2. /law_revisions/{law_id}?updated_from=... で、データ更新日による絞り込みが効くかを確かめる。
 3. /laws?amendment_law_id=... で、ある改正法令が改正した法令の一覧を取れるかを確かめる。
 4. 一括ダウンロードの「更新法令データ」（file_section=3&update_date=YYYYMMDD）を取得し、
    ZIP の中のファイル名だけを列挙する（展開はしない）。

ダウンロードしたもの（信頼できないデータ）は .work/downloads/<ts>_egov_revisions/ に置く。
要約は scripts/results/R1_egov_revisions/ に書く。
"""
import io
import json
import pathlib
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "okura-gov-research/0.1"
API = "https://laws.e-gov.go.jp/api/2"
SLEEP = 1.5

TARGETS = {
    "340AC0000000033": "所得税法",
    "340CO0000000096": "所得税法施行令",
    "332AC0000000026": "租税特別措置法",
    "325AC0000000226": "地方税法",
    "211AC0000000070": "健康保険法",
    "215M10000008036": "健康保険法施行規則",
    "334AC0000000141": "国民年金法",
    "334CO0000000184": "国民年金法施行令",
    "135AC1000000050": "年齢計算ニ関スル法律",
    "410AC0000000025": "電子帳簿保存法",
    "410M50000040043": "電子帳簿保存法施行規則",
}
# 更新日での絞り込みの確認に使う日付
UPDATED_FROM = "2026-10-01"
# 改正法令IDから被改正法令を引けるかの確認に使う改正法令（令和7年法律第13号 = 所得税法等の一部を改正する法律、と推定。結果で確認する）
AMENDMENT_LAW_IDS = ["507AC0000000013"]
# 一括ダウンロードの更新法令データ（過去3か月が取得範囲と仕様に書かれている）
BULK_DATES = ["20261108", "20261101", "20260801", "20250401"]


def get(url, accept="application/json"):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            body = r.read()
            status, ctype = r.status, r.headers.get("Content-Type")
    except urllib.error.HTTPError as e:
        body = e.read()
        status, ctype = e.code, e.headers.get("Content-Type")
    time.sleep(SLEEP)
    return status, ctype, body


def api(path, **q):
    q.setdefault("response_format", "json")
    url = API + path + "?" + urllib.parse.urlencode(q, doseq=True)
    return (url,) + get(url)


def rev_row(r):
    keys = [
        "law_revision_id", "law_title", "amendment_law_num", "amendment_law_title",
        "amendment_promulgate_date", "amendment_enforcement_date", "amendment_scheduled_enforcement_date",
        "amendment_enforcement_comment", "amendment_type", "mission", "current_revision_status",
        "repeal_status", "updated",
    ]
    return {k: r.get(k) for k in keys}


def main():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_egov_revisions"
    dl.mkdir(parents=True, exist_ok=False)
    out = ROOT / "scripts" / "results" / "R1_egov_revisions"
    out.mkdir(parents=True, exist_ok=True)
    summary = {"run_at": ts, "api": API, "user_agent": UA, "checks": []}

    # 1. 改正履歴
    md = ["# 改正履歴（/law_revisions）", "", f"取得: {ts}", ""]
    for law_id, name in TARGETS.items():
        url, st, ct, body = api(f"/law_revisions/{law_id}")
        (dl / f"revisions_{law_id}.json").write_bytes(body)
        rec = {"check": "law_revisions", "law_id": law_id, "name": name, "url": url, "status": st, "content_type": ct}
        if st == 200:
            d = json.loads(body)
            revs = [rev_row(r) for r in d.get("revisions", [])]
            rec["revision_count"] = len(revs)
            (out / f"revisions_{law_id}.json").write_text(json.dumps(revs, ensure_ascii=False, indent=1), encoding="utf-8")
            md += [f"## {name}（{law_id}）", "", f"件数: {len(revs)}（新しい順。先頭25件）", "",
                   "| law_revision_id | 施行日 | 改正法令 | 改正法令公布日 | 状態 | updated |", "|---|---|---|---|---|---|"]
            for r in revs[:25]:
                md.append("| {law_revision_id} | {amendment_enforcement_date} | {amendment_law_num} {amendment_law_title} | {amendment_promulgate_date} | {current_revision_status} | {updated} |".format(
                    **{k: (v if v is not None else "") for k, v in r.items()}))
            md.append("")
        summary["checks"].append(rec)
    (out / "revisions.md").write_text("\n".join(md), encoding="utf-8")

    # 2. updated_from による絞り込み
    for law_id in ["340AC0000000033", "211AC0000000070", "135AC1000000050"]:
        url, st, ct, body = api(f"/law_revisions/{law_id}", updated_from=UPDATED_FROM)
        (dl / f"revisions_{law_id}_updated_from.json").write_bytes(body)
        rec = {"check": "law_revisions_updated_from", "law_id": law_id, "updated_from": UPDATED_FROM, "url": url, "status": st}
        if st == 200:
            d = json.loads(body)
            rec["revisions"] = [rev_row(r) for r in d.get("revisions", [])]
        else:
            rec["body_head"] = body[:500].decode("utf-8", "replace")
        summary["checks"].append(rec)

    # 2b. law_id なしで更新法令の一覧を取れるか（/laws に updated_from は仕様上ない。パラメータを無視するか、エラーかを見る）
    url, st, ct, body = api("/laws", updated_from=UPDATED_FROM, limit=5)
    (dl / "laws_updated_from.json").write_bytes(body)
    rec = {"check": "laws_with_updated_from_param", "url": url, "status": st}
    if st == 200:
        d = json.loads(body)
        rec["total_count"] = d.get("total_count")
        rec["note"] = "total_count が全法令数に近ければ、パラメータは無視されている"
    else:
        rec["body_head"] = body[:500].decode("utf-8", "replace")
    summary["checks"].append(rec)
    url, st, ct, body = api("/laws", limit=1)
    rec = {"check": "laws_total_count_without_filter", "url": url, "status": st}
    if st == 200:
        rec["total_count"] = json.loads(body).get("total_count")
    summary["checks"].append(rec)

    # 3. 改正法令ID → 被改正法令
    for aid in AMENDMENT_LAW_IDS:
        url, st, ct, body = api("/laws", amendment_law_id=aid, limit=200)
        (dl / f"laws_amendment_{aid}.json").write_bytes(body)
        rec = {"check": "laws_by_amendment_law_id", "amendment_law_id": aid, "url": url, "status": st}
        if st == 200:
            d = json.loads(body)
            rec["total_count"] = d.get("total_count")
            rec["laws"] = [
                {"law_id": l["law_info"]["law_id"], "law_title": (l.get("revision_info") or {}).get("law_title"),
                 "amendment_law_title": (l.get("revision_info") or {}).get("amendment_law_title"),
                 "amendment_enforcement_date": (l.get("revision_info") or {}).get("amendment_enforcement_date")}
                for l in d.get("laws", [])]
        summary["checks"].append(rec)
        url, st, ct, body = api(f"/laws", law_id=aid)
        rec = {"check": "amendment_law_itself", "law_id": aid, "url": url, "status": st}
        if st == 200:
            d = json.loads(body)
            rec["laws"] = [{"law_num": l["law_info"]["law_num"], "promulgation_date": l["law_info"].get("promulgation_date"),
                            "law_title": (l.get("revision_info") or {}).get("law_title")} for l in d.get("laws", [])]
        summary["checks"].append(rec)

    # 3b. 改正法令（一部改正法）の本文を law_data で直接取れるか
    for aid in AMENDMENT_LAW_IDS:
        url, st, ct, body = api(f"/law_data/{aid}", omit_amendment_suppl_provision="true")
        rec = {"check": "law_data_of_amendment_law", "law_id": aid, "url": url, "status": st, "bytes": len(body)}
        if st != 200:
            rec["body_head"] = body[:300].decode("utf-8", "replace")
        summary["checks"].append(rec)

    # 4. 一括ダウンロードの更新法令データ
    for day in BULK_DATES:
        url = f"https://laws.e-gov.go.jp/bulkdownload?file_section=3&update_date={day}&only_xml_flag=true"
        st, ct, body = get(url, accept="*/*")
        rec = {"check": "bulkdownload_updated", "update_date": day, "url": url, "status": st, "content_type": ct, "bytes": len(body)}
        if st == 200 and body[:2] == b"PK":
            (dl / f"bulk_updated_{day}.zip").write_bytes(body)
            with zipfile.ZipFile(io.BytesIO(body)) as z:  # 名前を列挙するだけ。展開しない
                names = z.namelist()
                csvs = [n for n in names if n.lower().endswith(".csv")]
                csv_text = None
                if csvs:
                    raw = z.read(csvs[0])  # CSV はデータとして読むだけ
                    for enc in ("utf-8-sig", "cp932"):
                        try:
                            csv_text = raw.decode(enc)
                            rec["csv_encoding"] = enc
                            break
                        except UnicodeDecodeError:
                            pass
            rec["entry_count"] = len(names)
            rec["entries_head"] = names[:20]
            if csv_text is not None:
                rec["csv_name"] = csvs[0]
                rows = csv_text.splitlines()
                rec["csv_rows"] = len(rows)
                rec["csv_head"] = rows[:8]
                (out / f"bulk_updated_{day}_{csvs[0].replace('/', '_')}.txt").write_text(csv_text, encoding="utf-8")
        else:
            rec["body_head"] = body[:300].decode("utf-8", "replace")
        summary["checks"].append(rec)

    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
