"""R3X kyosai-b: 取得済みの資料から、共済組合の被扶養者の認定基準（大臣の定め）の改正の番号・日付・適用日と、
19歳以上23歳未満の150万円の文言を機械的に取り出して突き合わせる。ネットワークは使わない。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_kyosai-b_checks.py

入力（すべて取得済みのデータから作ったテキスト。読むだけで、解釈して実行することはない）:
  - scripts/results/R3X_kyosai-b_pdftext/unyo_k_*_lines.txt
      財務省「国家公務員共済組合法等の運用方針」の4つの版（裁判所共済組合の写し R5.3.28 現在、Wayback の保存 R7.4.1 現在・R8.8.1 現在、
      財務省の現行 R8.10.1 現在）を scripts/R3X_kyosai-b_pdftext.py で行にしたもの
  - scripts/results/R3X_kyosai-b_pdftext/tokyo_03_soumu_vertical.txt（総務省の改正通知 総行福第210号の別紙。縦書きの列の復元）
  - scripts/results/R3X_kyosai-b_pdftext/tokyo_03_soumu_lines.txt（同じ通知の1〜2頁の横書きの部分）
  - scripts/results/R3X_kyosai-b_pdftext/tokyo_00_tsuchi_lines.txt（公立学校共済組合東京支部の通知。関連通知の番号の記載）
  - scripts/results/R3X_kyosai-b_pdftext/pmac_hourei_sonota_text.tsv（私学共済事業「私立学校教職員共済制度関係法令集」令和8年版「その他」）
  - .work/text/<ts>_R3X_kyosai-b_kokka_pcm/pcm_*.txt、.work/text/<ts>_R3X_kyosai-b_kokka_b/mhlw_pcm_495250041.txt
      （e-Gov パブリック・コメントの結果の公示の画面のテキスト。scripts/R3X_kyosai-b_fetch.py が書いたもの）
出力: scripts/results/R3X_kyosai-b_checks/checks.json（検査ごとの結果と、根拠にした行）
"""
import glob
import json
import pathlib
import re
import sys
import unicodedata

ROOT = pathlib.Path(__file__).resolve().parent.parent
PT = ROOT / "scripts" / "results" / "R3X_kyosai-b_pdftext"
OUT = ROOT / "scripts" / "results" / "R3X_kyosai-b_checks"

KANJI = {"〇": "0", "○": "0", "一": "1", "二": "2", "三": "3", "四": "4", "五": "5", "六": "6", "七": "7", "八": "8", "九": "9"}


# NFKC で全角の括弧は半角になるので、半角の括弧で書く
CLAUSE_RE = r"年額130万円以上の所得がある者\(.*?所得がある者\)"


def norm(s):
    """全角を半角に（NFKC）し、空白を除く。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s))


def kanji_amount(s):
    """「百三十万円」「百五十万円」「百八十万円」「十九歳」「二十三歳」「六十歳」と2つの法律番号を算用数字にする（この検査で使う語だけ）。"""
    table = {"百三十万円": "130万円", "百五十万円": "150万円", "百八十万円": "180万円",
             "十九歳": "19歳", "二十三歳": "23歳", "六十歳": "60歳",
             # 地方の運用方針（縦書き）の法律番号の漢数字
             "昭和三十四年法律第百四十一号": "昭和34年法律第141号", "昭和二十九年法律第百十五号": "昭和29年法律第115号"}
    for k, v in table.items():
        s = s.replace(k, v)
    return s


def read_lines(path):
    return path.read_text(encoding="utf-8").splitlines()


def unyo_versions():
    """国の運用方針の各版：表紙の「現在」「最終改正」、第2条関係 第1項第2号 2(3) の文、令和7年以降の附則。"""
    res = {}
    for name in ["unyo_k_courts", "unyo_k_wb20250721", "unyo_k_wb20260926", "unyo_k_current"]:
        p = PT / f"{name}_lines.txt"
        if not p.exists():
            res[name] = {"error": "missing " + str(p.relative_to(ROOT))}
            continue
        lines = read_lines(p)
        head = lines[0]
        cover = [norm(x) for x in lines[1:8] if x.strip() and not x.startswith("===")]
        # 2(3) の文：「年額１３０万円以上の所得がある者」で始まる行から、「所得がある者）」で終わる行まで
        start = next((i for i, x in enumerate(lines) if "年額１３０万円以上の所得がある者" in x), None)
        clause = None
        if start is not None:
            buf = []
            for x in lines[start:start + 14]:
                # 頁の区切り（"=== page N"、"-N-" の頁番号、空行）は飛ばす
                if x.startswith("=== page") or re.fullmatch(r"\s*-\d+-\s*", x) or not x.strip():
                    continue
                buf.append(x)
                if "所得がある者）" in x:
                    break
            clause = norm("".join(buf))
        # 附則（令和…）とその次の行
        fusoku = []
        for i, x in enumerate(lines):
            if x.startswith("附則（令和"):
                fusoku.append({"line": i + 1, "fusoku": norm(x), "next": norm(lines[i + 1]) if i + 1 < len(lines) else ""})
        res[name] = {
            "source_header": head,
            "cover": cover[:3],
            "clause_2_3": clause,
            "has_19_23": bool(clause and "19歳以上23歳未満" in clause),
            "has_150": bool(clause and "150万円以上" in clause),
            "fusoku_reiwa": fusoku,
        }
    return res


def pcm_pages():
    """e-Gov パブリック・コメントの結果の公示（国家公務員：395081949・395081944・395081959、厚労省：495250041）の欄。"""
    keys = ["案件番号", "定めようとする命令などの題名", "根拠法令条項", "行政手続法に基づく手続か", "案の公示日", "受付締切日時",
            "結果の公示日", "命令等の公布日", "提出意見数"]
    out = {}
    files = sorted(glob.glob(str(ROOT / ".work" / "text" / "*_R3X_kyosai-b_kokka_pcm" / "pcm_3*.txt")))
    files += sorted(glob.glob(str(ROOT / ".work" / "text" / "*_R3X_kyosai-b_kokka_b" / "mhlw_pcm_495250041.txt")))
    for f in files:
        t = pathlib.Path(f).read_text(encoding="utf-8")
        rec = {"file": str(pathlib.Path(f).relative_to(ROOT)).replace("\\", "/")}
        for k in keys:
            m = re.search(r"\|\s*" + re.escape(k) + r"\s*\|\s*([^\n|]+)", t)
            if m:
                rec[k] = " ".join(m.group(1).split())
        m = re.search(r"意見公募手続を実施しないで命令等を定めた場合にはその旨及びその理由\s*\|\s*([^\n]+)", t)
        if m:
            rec["39条4項の理由"] = " ".join(m.group(1).split())
        out[pathlib.Path(f).stem] = rec
    return out


def soumu_notice():
    """総務省の改正通知（総行福第210号）：宛先の頁の番号・日付・件名、別紙の改正後・改正前の (三) の文、附則。"""
    lines = read_lines(PT / "tokyo_03_soumu_lines.txt")
    head = lines[0]
    p1 = [norm(x) for x in lines if "総行福" in x or "運用方針の一部改正について" in x]
    vert = read_lines(PT / "tokyo_03_soumu_vertical.txt")
    # 縦書きの列の復元では、表の上の欄（改正後）と下の欄（改正前）の間に " ‖ " が入る
    after, before = [], []
    in_band = False
    for x in vert:
        if x.startswith("=== page 3 band 1"):
            in_band = True
            continue
        if x.startswith("==="):
            in_band = False
        if in_band and " ‖ " in x:
            a, b = x.split(" ‖ ", 1)
            after.append(a)
            before.append(b)
        elif in_band:
            after.append(x)
    a_txt = kanji_amount(norm("".join(after)))
    b_txt = kanji_amount(norm("".join(before)))
    ma = re.search(CLAUSE_RE, a_txt)
    mb = re.search(CLAUSE_RE, b_txt)
    fusoku = [norm(x) for x in vert if "この運用方針の改正は" in x]
    return {
        "source_header": head,
        "page1_2_lines": p1,
        "kaisei_mae_title": [norm(x) for x in vert if "自治甲公第十号" in x][:1],
        "after_clause_3": ma.group(0) if ma else None,
        "before_clause_3": mb.group(0) if mb else None,
        "after_has_19_23_150": bool(ma and "19歳以上23歳未満" in ma.group(0) and "150万円以上" in ma.group(0)),
        "before_has_19_23": bool(mb and "19歳以上23歳未満" in mb.group(0)),
        "fusoku": fusoku,
    }


def tokyo_related():
    lines = read_lines(PT / "tokyo_00_tsuchi_lines.txt")
    out = []
    for i, x in enumerate(lines):
        if "総行福" in x or "保発" in x or "適用" in x or "公立東京給" in x:
            out.append(norm(x + (lines[i + 1] if "総行福第２１" in x else "")))
    return {"source_header": lines[0], "lines": out}


def shigaku_saitei():
    """私学共済事業の法令集（令和8年版「その他」）20頁：「私立学校教職員共済法施行令第三条の規定による…の認定について」。"""
    p = PT / "pmac_hourei_sonota_text.tsv"
    rows = []
    # 行の区切りは CRLF。文字列の中に単独の CR・LF が入ることがあるので、CRLF だけで区切り、欄が5つない行は数えて飛ばす
    raw = p.read_bytes().decode("utf-8").split("\r\n")
    head = raw[0]
    skipped = 0
    for ln in raw[2:]:
        parts = ln.split("\t", 4)
        if len(parts) != 5:
            skipped += 1
            continue
        pg, x, y, font, text = parts
        if pg == "20":
            rows.append((float(x), float(y), font, text))
    # 本文（フォント TT4、x が 249〜260 の列）を y の降順につなぐ。続きの2行（y 281.7・279.6）は列の頭に組まれている
    body = [r for r in rows if r[2].startswith("TT4")]
    tail = [r for r in body if r[1] > 200]
    main = [r for r in body if r[1] <= 200]
    main_txt = "".join(r[3] for r in sorted(main, key=lambda r: (-r[1], r[0])))
    tail_txt = "".join(r[3] for r in sorted(tail, key=lambda r: (-r[1], r[0])))
    title = "".join(r[3] for r in sorted([r for r in rows if 199 <= r[1] <= 203 and 180 <= r[0] <= 195], key=lambda r: (-r[1], r[0])))
    meta = [r[3] for r in rows if r[2].startswith(("TT2", "TT3")) and r[1] > 200]
    full = norm(main_txt + tail_txt)
    return {
        "source_header": head,
        "title": norm(title),
        "meta_rows": meta,
        "body": full,
        "has_19_23_150": "19歳以上23歳未満" in full and "150万円以上" in full,
        "has_item_4": bool(re.search(r"者）?4", full)),
        "tsv_rows_skipped": skipped,
    }


def compare_clause(texts):
    """3つの大臣の定めの (3) の文を、組合員・加入者の語の違いをならして比べる。"""
    ns = {}
    for k, t in texts.items():
        if t is None:
            ns[k] = None
            continue
        s = kanji_amount(norm(t))
        s = s.replace("組合員", "＊").replace("加入者", "＊")
        s = re.sub(r"[、，]", "", s)
        m = re.search(CLAUSE_RE, s)
        ns[k] = m.group(0) if m else s
    vals = [v for v in ns.values() if v]
    return {"normalized": ns, "all_equal": len(set(vals)) == 1 and len(vals) == len(ns)}


def block_diff():
    """国の運用方針の各版で、第2条関係「第１項第２号」の項（1〜5）全体を文（。で区切る）の単位で比べる。
    前の版にない文・後の版にない文を、隣り合う版の組ごとに出す。"""
    order = ["unyo_k_courts", "unyo_k_wb20250721", "unyo_k_wb20260926", "unyo_k_current"]
    blocks = {}
    for name in order:
        lines = read_lines(PT / f"{name}_lines.txt")
        start = next(i for i, x in enumerate(lines) if x.strip() == "第１項第２号")
        buf = []
        for x in lines[start + 1:]:
            if x.strip() == "第１項第３号":
                break
            if x.startswith("=== page") or re.fullmatch(r"\s*-\d+-\s*", x) or not x.strip():
                continue
            buf.append(x)
        sents = [s + "。" for s in "".join(buf).split("。") if s]
        blocks[name] = sents
    pairs = []
    for a, b in zip(order, order[1:]):
        sa, sb = set(blocks[a]), set(blocks[b])
        pairs.append({"from": a, "to": b, "only_in_from": [s for s in blocks[a] if s not in sb],
                      "only_in_to": [s for s in blocks[b] if s not in sa]})
    return {"n_sentences": {k: len(v) for k, v in blocks.items()}, "pairs": pairs}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    res = {}
    res["K1_unyo_versions"] = unyo_versions()
    res["K2_pcm"] = pcm_pages()
    res["K3_soumu_notice"] = soumu_notice()
    res["K4_tokyo_related"] = tokyo_related()
    res["K5_shigaku_saitei"] = shigaku_saitei()
    cur = res["K1_unyo_versions"].get("unyo_k_current", {}).get("clause_2_3")
    res["K6_compare_clause_3"] = compare_clause({
        "kokka_unyo_R8_10_1": cur,
        "chiho_unyo_after_R7_7_23": res["K3_soumu_notice"]["after_clause_3"],
        "shigaku_saitei_R7_8_29": res["K5_shigaku_saitei"]["body"],
    })
    res["K7_unyo_block_diff"] = block_diff()
    (OUT / "checks.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    # 要約を表示
    for k, v in res["K1_unyo_versions"].items():
        print(k, v.get("cover"), "19-23:", v.get("has_19_23"), "150:", v.get("has_150"),
              "附則(令和) 末尾:", [f["fusoku"] for f in v.get("fusoku_reiwa", [])][-6:])
    for k, v in res["K2_pcm"].items():
        print(k, v.get("定めようとする命令などの題名"), v.get("結果の公示日"), v.get("命令等の公布日"))
    s = res["K3_soumu_notice"]
    print("soumu:", s["page1_2_lines"][:2], "after 19-23/150:", s["after_has_19_23_150"], "before 19-23:", s["before_has_19_23"], s["fusoku"])
    print("shigaku:", res["K5_shigaku_saitei"]["title"], res["K5_shigaku_saitei"]["meta_rows"], res["K5_shigaku_saitei"]["has_19_23_150"])
    print("compare:", json.dumps(res["K6_compare_clause_3"], ensure_ascii=False, indent=1))
    print("block diff:", json.dumps(res["K7_unyo_block_diff"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
