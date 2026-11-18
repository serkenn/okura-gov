"""R3X design: 仮説・推測の文書（docs/hypotheses・docs/inferences の 20261109_*、round3 を除く）から、
語彙の名前（バッククォートで囲んだ識別子、概念 ID らしいもの、メタデータのキー）と、
語彙に関する節（見出し）と、言い換えの候補の出現数を機械的に数える（ネットワークは使わない）。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_design_vocab-scan.py

入力: docs/hypotheses/20261109_*.md、docs/inferences/20261109_*.md（ファイル名に _round3_ を含むものを除く）
出力: scripts/results/R3X_design_vocab-scan/
  corpus.json      … 対象ファイルの一覧（バイト数・SHA-256・行数）
  sections.tsv     … 見出しの一覧（ファイル、行、レベル、見出し、語彙に関する見出しか）
  tokens.tsv       … バッククォートの中身ごとの出現（ファイル、行、直前の見出し、分類、中身）
  token_summary.json … 分類ごとに、中身 → 出現数・ファイル数・ファイル一覧
  variants.json    … 言い換えの候補（下の VARIANTS）ごとの、表記ごとの出現数とファイル
  classification_rows.tsv … 区分を比べる項目（下の CLASS_ITEMS）を含む表の行・箇条書きの行と、同じ行にある区分の語

第2の使い方（引用の機械的な検査）:
  ...python.exe -I -X utf8 scripts/R3X_design_vocab-scan.py cite-check <文書.md> [<文書.md> ...]
  文書の中の略号の表（行の形「| [略号] | `docs/....md` |」）を読み、本文の「[略号] §n.m」「[略号] T02」「[略号] C1」の
  形の引用について、(1) ファイルがあるか、(2) 節番号 n.m で始まる見出し（「## n.」「### n.m 」など）があるか、
  (3) T/C の番号がファイルの本文にあるか、を調べる。§n-k（節の中の k 番目の項目）は節 n の見出しだけを調べる。
  出力: scripts/results/R3X_design_vocab-scan/cite_check.json
"""
import sys
import hashlib
import json
import pathlib
import re
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "scripts" / "results" / "R3X_design_vocab-scan"

SECTION_KW = re.compile(r"事実|語彙|判断|選択|注入|概念|入力|中間表現|台帳|記録層|境目")

# 言い換えの候補。各組の中の表記は、文書の本文（バッククォートの中を含む）での部分一致の回数を数える。
# 長い表記に含まれる短い表記は、長い表記の分を引いた「単独の」回数も出す。
VARIANTS = {
    "生計": ["生計を一にする", "生計を一に", "生計一", "生計同一"],
    "同一世帯": ["同一の世帯に属する", "同一の世帯", "同一世帯"],
    "判定の時点（健保）": ["判定日", "認定日", "基準日"],
    "事実台帳": ["事実台帳", "人と関係の記録", "取引でない事実", "取引ではない事実"],
    "判断台帳": ["判断台帳", "人の判断", "判断の記録"],
    "選択": ["納税者の選択", "本人の選択", "人の選択", "家族の選択"],
    "注入": ["注入データ", "注入するデータ", "注入点", "保険者データ", "市町村データ", "団体データ", "注入"],
    "見込み": ["見込み", "見積もり", "見積り", "推計"],
    "年間収入": ["年間収入", "年収", "収入の見込み"],
    "支払者": ["支払者", "支払った人", "payer"],
    "受診者": ["受診者", "受診した人", "patient"],
    "扶養の所属": ["扶養所属", "扶養の所属", "所属の割当て", "所属の割当"],
    "申告書の記載": ["申告書等の記載", "申告書の記載", "記載の事実", "提出した申告書"],
    "中間表現": ["中間表現", "事実の語彙"],
    "印": ["未確定", "出典未確認", "対象外", "見込み」の印", "通達による取扱い", "国税庁の説明に基づく"],
    "居住": ["居住者", "非居住者", "国外居住親族", "国内居住要件"],
    "配偶者": ["同一生計配偶者", "控除対象配偶者", "源泉控除対象配偶者", "事実婚", "法律婚"],
    "保険者": ["保険者", "共済組合", "健保組合", "協会けんぽ"],
    "業務": ["業務ID", "業務別", "業務ごと", "事業ごと"],
    "人ID": ["人ID", "person_id", "person", "人の ID"],
}


# 事実か判断かの区分を比べる項目。表の行（「|」で始まる行）と箇条書きの行のうち、項目の語を含む行を集め、
# 同じ行に現れる区分の語（事実・判断・D4・選択・注入・コア）を記録する（行の意味の読み取りはしない）。
CLASS_ITEMS = {
    "同一の世帯": ["同一の世帯", "同一世帯"],
    "経理方式": ["経理方式"],
    "続柄": ["続柄"],
    "帳簿の方式": ["帳簿の方式", "簿記"],
    "申告書等の記載": ["申告書等の記載", "申告書の記載", "記載の事実"],
    "生計を一にする": ["生計を一にする", "生計一"],
    "大口株主等": ["大口株主"],
    "業務の区分・事業的規模": ["業務の区分", "事業的規模", "事業と称するに至る"],
    "見込み・見込額": ["見込額", "見込み"],
    "級地": ["級地"],
    "指定都市": ["指定都市"],
    "寄附先の種類": ["寄附先の種類", "寄附先の区分", "寄附先の法的な種類"],
}
CLASS_WORDS = ["事実", "判断", "D4", "選択", "注入", "コア", "未決", "見込み"]


def corpus():
    files = []
    for sub in ("hypotheses", "inferences"):
        for p in sorted((ROOT / "docs" / sub).glob("20261109_*.md")):
            if "_round3_" in p.name:
                continue
            files.append(p)
    return files


def classify(tok):
    if re.search(r"(docs|scripts|references|research)/|\.(md|py|json|tsv|yaml|yml|csv|xlsx|pdf)\b", tok):
        return "path"
    if re.fullmatch(r"[a-z][a-z0-9_]*:", tok):
        return "meta_key"
    if re.fullmatch(r"(K[A-Z]{2}\d{3}(-\d{2})?|NTA[0-9A-Z]{6,})", tok):
        return "form_id"
    if re.search(r"[^\x00-\x7f]", tok) and re.fullmatch(r"[^\s.]+(\.[^\s.]+)+", tok):
        return "dotted_jp"
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", tok):
        return "ascii_ident"
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.:\-/<>=]*", tok):
        return "ascii_expr"
    return "other"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    files = corpus()
    meta = []
    sections_rows = []
    token_rows = []
    summary = defaultdict(lambda: defaultdict(lambda: {"count": 0, "files": set()}))
    texts = {}
    for p in files:
        raw = p.read_bytes()
        text = raw.decode("utf-8")
        rel = p.relative_to(ROOT).as_posix()
        texts[rel] = text
        lines = text.splitlines()
        meta.append({"file": rel, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "lines": len(lines)})
        heading = ""
        in_fence = False
        for i, ln in enumerate(lines, 1):
            if ln.startswith("```"):
                in_fence = not in_fence
                continue
            m = re.match(r"(#{1,6})\s+(.*)", ln)
            if m and not in_fence:
                heading = m.group(2).strip()
                sections_rows.append((rel, i, len(m.group(1)), heading, "1" if SECTION_KW.search(heading) else "0"))
                continue
            for tok in re.findall(r"`([^`\n]+)`", ln):
                tok = tok.strip()
                if not tok:
                    continue
                c = classify(tok)
                token_rows.append((rel, i, heading, c, tok))
                s = summary[c][tok]
                s["count"] += 1
                s["files"].add(rel)
    (OUT / "corpus.json").write_text(json.dumps({"files": meta, "n_files": len(meta)}, ensure_ascii=False, indent=1), encoding="utf-8")
    with (OUT / "sections.tsv").open("w", encoding="utf-8", newline="\n") as f:
        f.write("file\tline\tlevel\theading\tvocab_related\n")
        for r in sections_rows:
            f.write("\t".join(str(x).replace("\t", " ") for x in r) + "\n")
    with (OUT / "tokens.tsv").open("w", encoding="utf-8", newline="\n") as f:
        f.write("file\tline\theading\tclass\ttoken\n")
        for r in token_rows:
            f.write("\t".join(str(x).replace("\t", " ") for x in r) + "\n")
    out_sum = {}
    for c, d in summary.items():
        out_sum[c] = {
            tok: {"count": v["count"], "n_files": len(v["files"]), "files": sorted(v["files"])}
            for tok, v in sorted(d.items(), key=lambda kv: (-kv[1]["count"], kv[0]))
        }
    (OUT / "token_summary.json").write_text(json.dumps(out_sum, ensure_ascii=False, indent=1), encoding="utf-8")
    var_out = {}
    for group, forms in VARIANTS.items():
        g = {}
        for form in forms:
            per_file = {}
            for rel, text in texts.items():
                n = text.count(form)
                # 同じ組の中で、この表記を含む長い表記の分を引いた単独の回数
                longer = [o for o in forms if o != form and form in o]
                alone = n - sum(text.count(o) for o in longer)
                if n:
                    per_file[rel] = {"count": n, "alone": alone}
            g[form] = {
                "total": sum(v["count"] for v in per_file.values()),
                "total_alone": sum(v["alone"] for v in per_file.values()),
                "n_files": len(per_file),
                "files": per_file,
            }
        var_out[group] = g
    (OUT / "variants.json").write_text(json.dumps(var_out, ensure_ascii=False, indent=1), encoding="utf-8")
    # 概念 ID らしいもの（dotted_jp）の先頭の区切り（接頭辞）ごとの一覧
    prefixes = defaultdict(lambda: {"tokens": set(), "files": set()})
    for rel, i, heading, c, tok in token_rows:
        if c == "dotted_jp" and not re.search(r"[/<>]", tok):
            pre = tok.split(".")[0]
            prefixes[pre]["tokens"].add(tok)
            prefixes[pre]["files"].add(rel)
    (OUT / "prefix_summary.json").write_text(json.dumps(
        {k: {"n_tokens": len(v["tokens"]), "tokens": sorted(v["tokens"]), "files": sorted(v["files"])}
         for k, v in sorted(prefixes.items(), key=lambda kv: -len(kv[1]["tokens"]))},
        ensure_ascii=False, indent=1), encoding="utf-8")
    # 名前つきの関数（端数処理・期間・年齢など）らしいバッククォートの中身と、その書き方
    fn_pat = re.compile(r"端数|切捨|切上|kirisute|floor|round|threshold|年齢|days_within|manryo|kisanbi|期限|繰戻し|"
                        r"青色控除|専従_|所令85|措法28の2|転用|処分年|家事兼用|一括償却|償却費|事業専用割合後|円未満|nintei_bi|"
                        r"所令198|第83条の2|jsGetAge|aoiro_tokubetsu|kyuyo_shotoku|shinkoku_yohi|evaluate")
    with (OUT / "named_functions.tsv").open("w", encoding="utf-8", newline="\n") as f:
        f.write("style\ttoken\tfile\tline\n")
        seen = set()
        for rel, i, heading, c, tok in token_rows:
            if c == "path" or not fn_pat.search(tok):
                continue
            has_jp = re.search(r"[^\x00-\x7f]", tok) is not None
            has_ascii_word = re.search(r"[A-Za-z]{2,}", tok) is not None
            style = "mixed" if (has_jp and has_ascii_word) else ("japanese" if has_jp else "ascii")
            key = (style, tok, rel)
            if key in seen:
                continue
            seen.add(key)
            f.write("\t".join([style, tok.replace("\t", " "), rel, str(i)]) + "\n")
    with (OUT / "classification_rows.tsv").open("w", encoding="utf-8", newline="\n") as f:
        f.write("item\tfile\tline\twords_in_row\trow_head\n")
        for item, kws in CLASS_ITEMS.items():
            for rel, text in texts.items():
                for i, ln in enumerate(text.splitlines(), 1):
                    s = ln.lstrip()
                    if not (s.startswith("|") or s.startswith("-") or re.match(r"[0-9]+\.", s)):
                        continue
                    if not any(k in ln for k in kws):
                        continue
                    words = [w for w in CLASS_WORDS if w in ln]
                    f.write("\t".join([item, rel, str(i), ",".join(words), ln.strip()[:160].replace("\t", " ")]) + "\n")
    print(f"files={len(meta)} sections={len(sections_rows)} tokens={len(token_rows)}")
    for c in sorted(out_sum):
        print(f"class {c}: distinct={len(out_sum[c])} occurrences={sum(v['count'] for v in out_sum[c].values())}")


ALIAS_ROW = re.compile(r"^\|\s*\[([A-Za-z0-9\-]+)\]\s*\|\s*`(docs/[^`]+\.md)`")
CITE = re.compile(r"\[([A-Za-z0-9\-]+)\]((?:\s*(?:§[0-9]+(?:\.[0-9]+)*(?:-[0-9]+)?|[TC][0-9]+[a-z]?)\s*(?:[、・,]\s*)?)+)")
SEC = re.compile(r"§([0-9]+(?:\.[0-9]+)*)(?:-([0-9]+))?")
TC = re.compile(r"\b([TC][0-9]+[a-z]?)\b")


def headings_of(path):
    out = set()
    for ln in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"#{1,6}\s*(?:§)?([0-9]+(?:\.[0-9]+)*)[.\s　]", ln)
        if m:
            out.add(m.group(1))
    return out


def cite_check(docs):
    OUT.mkdir(parents=True, exist_ok=True)
    report = {"documents": [], "n_citations": 0, "n_failures": 0}
    for d in docs:
        p = (ROOT / d) if not pathlib.Path(d).is_absolute() else pathlib.Path(d)
        text = p.read_text(encoding="utf-8")
        aliases = {}
        for ln in text.splitlines():
            m = ALIAS_ROW.match(ln)
            if m:
                aliases[m.group(1)] = m.group(2)
        cache = {}
        results = []
        for i, ln in enumerate(text.splitlines(), 1):
            if ALIAS_ROW.match(ln):
                continue
            for m in CITE.finditer(ln):
                alias, tail = m.group(1), m.group(2)
                if alias not in aliases:
                    results.append({"line": i, "alias": alias, "ref": tail.strip(), "ok": False, "why": "略号が表にない"})
                    continue
                f = ROOT / aliases[alias]
                if not f.exists():
                    results.append({"line": i, "alias": alias, "ref": tail.strip(), "ok": False, "why": "ファイルがない"})
                    continue
                if alias not in cache:
                    cache[alias] = (headings_of(f), f.read_text(encoding="utf-8"))
                heads, body = cache[alias]
                for s in SEC.finditer(tail):
                    ok = s.group(1) in heads
                    results.append({"line": i, "alias": alias, "ref": "§" + s.group(0)[1:], "ok": ok,
                                    "why": "" if ok else "見出しに節番号がない"})
                for t in TC.finditer(tail):
                    ok = re.search(r"\b" + re.escape(t.group(1)) + r"\b", body) is not None
                    results.append({"line": i, "alias": alias, "ref": t.group(1), "ok": ok,
                                    "why": "" if ok else "本文に番号がない"})
        fails = [r for r in results if not r["ok"]]
        report["documents"].append({"document": d, "aliases": aliases, "n_citations": len(results),
                                    "n_failures": len(fails), "failures": fails})
        report["n_citations"] += len(results)
        report["n_failures"] += len(fails)
        print(f"{d}: aliases={len(aliases)} citations={len(results)} failures={len(fails)}")
        for r in fails[:50]:
            print(f"  L{r['line']} [{r['alias']}] {r['ref']} : {r['why']}")
    (OUT / "cite_check.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "cite-check":
        cite_check(sys.argv[2:])
    else:
        main()
