"""SAKUSEI reconcile：作成コーナー（令和7年分）との照合の実測（HANDOFF D15⑤・D16・D17 Q7・D21 R5・D24①）。

架空の家庭（scripts/inputs/SAKUSEI_reconcile/<case>.json）について、判定コアの様式の欄の値（期待値）と、
作成コーナーに同じ内容を入れて得た申告書の欄の値（観測値）を突き合わせる。照合はテストではない（D24①）。
食い違ったときに正とするのは法令（D15⑤）。作成コーナーの値は、食い違いを見つけるための二次的な観測。

実行（リポジトリの根で。判定コアの仮想環境）:
  .work/venvs/core/Scripts/python.exe -I -X utf8 scripts/SAKUSEI_reconcile.py expect scripts/inputs/SAKUSEI_reconcile/<case>.json
      期待値を計算し、scripts/results/SAKUSEI_reconcile/<case_id>/<YYYYMMDD-HHMMSS>/ に
        manifest.json     実行の記録（ケースの SHA-256、リポジトリの commit、評価の時間）
        expected.json     判定コアの様式の欄の値（申告者・年分の forms）と申告の型
        input_sheet.md    作成コーナーに入れる内容（中間表現の記録を人が読める形にしたもの＋作成コーナーだけで要る記載）
        observation.tsv   記入表（期待値つき。観測値の列は空。作成コーナーの表示を書き込む）
      を書く。
  .work/venvs/core/Scripts/python.exe -I -X utf8 scripts/SAKUSEI_reconcile.py compare scripts/results/SAKUSEI_reconcile/<case_id>/<run>
      記入済みの observation.tsv と expected.json を突き合わせ、同じディレクトリに compare.json と compare.md を書く。

記入表の約束（observation.tsv）:
  - 先頭の「# 観測した帳票:」の行に、作成コーナーの出力で全部の欄を見た帳票の番号（KOA020-01 など）をカンマ区切りで書く。
    書いた帳票では、観測値が空の行を「作成コーナーで空欄」とみなす。書かない帳票の行は「未観測」として数えない。
  - 「# 一部だけ観測した帳票:」（2026-11-13）：画面でしか見られなかった帳票。観測値を書いた行だけ比べ、空の行は未観測に数える。
  - 観測値は表示のとおりに書く（3桁区切り・円はあってよい）。チェック欄は ○。0 と空欄は同じとみなす（申告書は 0 を空欄で出すことがある）。
    単位のある欄（期待値の備考に「欄は N 円単位」）は、欄に書く形（値 ÷ 単位）で書く。様式に印刷された 0（00・0000）は写さない。
  - 期待値の行にない欄に作成コーナーが値を出したら、行を足す（帳票・位置名か欄番号・観測値。期待値は空）。
  - 備考の列には、作成コーナーの画面の文言・注意の表示など、照合の手がかりを書いてよい。

- ネットワークを使わない。判定コア（okura_core）と中間表現（okura_ir）を import するだけ。
- ケースは架空の家庭だけ（AGENTS.md「安全のルール」）。
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import re
import sys
import time
import unicodedata

ROOT = pathlib.Path(__file__).resolve().parent.parent
NAME = "SAKUSEI_reconcile"
OUT = ROOT / "scripts" / "results" / NAME
COLUMNS = ["帳票", "帳票名", "位置名", "欄番号", "欄コード", "行", "状態", "期待値", "観測値", "備考"]
#: 照合しない欄の状態（対応表に概念のない欄：氏名・住所など、出力しない欄：個人番号）
SKIP_STATUS = ("対応なし", "出力しない")


def _commit() -> str:
    head = (ROOT / ".git" / "HEAD").read_text(encoding="utf-8").strip()
    if head.startswith("ref: "):
        ref = ROOT / ".git" / head[5:]
        if ref.exists():
            return ref.read_text(encoding="utf-8").strip()
        packed = ROOT / ".git" / "packed-refs"
        if packed.exists():
            for line in packed.read_text(encoding="utf-8").splitlines():
                if line.endswith(" " + head[5:]):
                    return line.split()[0]
        return "unknown"
    return head


def _render(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "○" if v else ""
    if isinstance(v, (int, str)):
        return str(v)
    return json.dumps(v, ensure_ascii=False, sort_keys=True)


def _clean(s: str) -> str:
    return s.replace("\t", " ").replace("\n", " ")


# ---------------------------------------------------------------- expect

def _age_at(birth: str, on: dt.date) -> int:
    b = dt.date.fromisoformat(birth)
    return on.year - b.year - ((on.month, on.day) < (b.month, b.day))


def input_sheet(case: dict) -> str:
    """中間表現の記録を、作成コーナーに入れるために人が読める形にする（語彙の名前を添える。法令の判断はしない）。"""
    from okura_ir import vocabulary as voc

    titles = {k.kind: k.title for kinds in voc.RECORD_SECTIONS.values() for k in kinds}
    titles.update({k.kind: k.title for kinds in voc.LEDGER_SECTIONS.values() for k in kinds})
    ir = case["ir"]
    names = case.get("names", {})
    year_end = dt.date(case["tax_year"], 12, 31)

    def who(pid):
        return f"{names.get(pid, pid)}（{pid}）" if isinstance(pid, str) else str(pid)

    def kv(d):
        if not d:
            return ""
        parts = []
        for k, v in d.items():
            if isinstance(v, str) and v in names:
                v = who(v)
            parts.append(f"{k}={json.dumps(v, ensure_ascii=False) if not isinstance(v, (str, int)) else v}")
        return "、".join(parts)

    L = [f"# 作成コーナーに入れる内容：{case['case_id']} {case['title']}", "",
         f"- 年分：{case['tax_year']}年分（令和{case['tax_year'] - 2018}年分）。申告者：{who(case['filer'])}",
         "- **架空の家庭。** 氏名・住所などは下の架空の値だけを使う。個人番号は入れない。提出方法は「書面」を選び、e-Tax に送信しない。", ""]
    if case.get("purpose"):
        L += ["## 確かめたいこと", ""] + [f"- {p}" for p in case["purpose"]] + [""]
    L += ["## 人", "", "| ID | 呼び名 | 生年月日 | 年末の年齢 |", "|---|---|---|---|"]
    for p in ir["persons"]:
        age = _age_at(p["birth_on"], year_end) if p.get("birth_on") else ""
        L.append(f"| {p['id']} | {names.get(p['id'], '')} | {p.get('birth_on', '')} | {age} |")
    L.append("")
    if case.get("sakusei_only"):
        L += ["## 作成コーナーだけで要る記載（中間表現にない、書類に印字された値など）", "", "| 項目 | 値 | 注 |", "|---|---|---|"]
        for s in case["sakusei_only"]:
            L.append(f"| {s['item']} | {_render(s['value'])} | {s.get('note', '')} |")
        L.append("")
    for section in list(voc.RECORD_SECTIONS) + list(voc.LEDGER_SECTIONS):
        recs = ir.get(section) or []
        if not recs:
            continue
        L += [f"## {section}", ""]
        for r in recs:
            title = titles.get(r.get("kind"), "")
            head = f"- `{r['id']}` {r.get('kind')}（{title}）"
            body = []
            if r.get("roles"):
                body.append("役割：" + "、".join(f"{k}={who(v)}" for k, v in r["roles"].items()))
            for key in ("subject", "judged_by"):
                if r.get(key):
                    body.append(f"{key}：" + kv(r[key]))
            if r.get("chosen_by"):
                body.append(f"chosen_by：{who(r['chosen_by'])}")
            if r.get("when"):
                body.append("時：" + kv(r["when"]))
            if r.get("amounts"):
                body.append("金額：" + "、".join(f"{k}={v:,}" if isinstance(v, int) else f"{k}={v}" for k, v in r["amounts"].items()))
            if r.get("attributes"):
                body.append("属性：" + kv(r["attributes"]))
            if "value" in r:
                body.append("値：" + (json.dumps(r["value"], ensure_ascii=False) if not isinstance(r["value"], str) else r["value"]))
            if r.get("note"):
                body.append("注：" + r["note"])
            L.append(head)
            L += [f"  - {b}" for b in body]
        L.append("")
    return "\n".join(L) + "\n"


def cmd_expect(case_path: pathlib.Path) -> int:
    from okura_ir.validate import validate
    from okura_core.evaluate import evaluate

    raw = case_path.read_bytes()
    case = json.loads(raw)
    for k in ("case_id", "title", "tax_year", "filer", "ir"):
        if k not in case:
            print(f"ケースに {k} がない", file=sys.stderr)
            return 2
    problems = validate(case["ir"])
    if problems:
        print("中間表現の誤り：", problems, file=sys.stderr)
        return 2
    query = {"income_tax_years": [case["tax_year"]], "resident_tax_fiscal_years": [], "kokuho_fiscal_years": [],
             "dependent_judgment_dates": [], "scenarios": [], "forms": {"persons": [case["filer"]]}}
    t0 = time.perf_counter()
    res = evaluate(case["ir"], query)
    seconds = round(time.perf_counter() - t0, 1)
    d = res.to_dict() if hasattr(res, "to_dict") else res
    if d.get("errors"):
        print("評価の誤り：", d["errors"], file=sys.stderr)
        return 2
    base = d["scenarios"][0]
    forms = [f for f in base.get("forms") or [] if f.get("person") == case["filer"] and f.get("tax_year") == case["tax_year"]]
    if len(forms) != 1:
        print("申告者・年分の forms が1つでない", file=sys.stderr)
        return 2
    forms = forms[0]
    run = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = OUT / case["case_id"] / run
    out.mkdir(parents=True, exist_ok=False)
    manifest = {"script": f"scripts/{NAME}.py", "case": case_path.resolve().relative_to(ROOT).as_posix(),
                "case_sha256": hashlib.sha256(raw).hexdigest(), "commit": _commit(), "run": run,
                "query": query, "evaluate_seconds": seconds, "forms_ok": forms.get("ok"),
                "out_of_scope": base.get("out_of_scope") or []}
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    expected = {"case_id": case["case_id"], "tax_year": case["tax_year"], "filer": case["filer"], "forms": forms}
    (out / "expected.json").write_text(json.dumps(expected, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "input_sheet.md").write_text(input_sheet(case), encoding="utf-8")
    lines = [f"# case={case['case_id']} run={run} commit={manifest['commit'][:12]} 申告の型={(forms.get('filing_type') or {}).get('value')}",
             "# 観測した帳票: ",
             "# 一部だけ観測した帳票: ",
             "# 観測の日時: ",
             "# 作成コーナーの画面の版（トップの年分・更新日など）: ",
             "\t".join(COLUMNS)]
    n = 0
    for form in forms.get("forms") or []:
        if form.get("use") is False:
            continue
        for f in form.get("fields") or []:
            if f.get("status") in SKIP_STATUS:
                continue
            # 2026-11-13：欄の単位（unit。値は円）。期待値は欄に書く形（値 ÷ 単位）にし、円の値を備考に残す
            value, note, unit = f.get("value"), "", f.get("unit") or 1
            if unit > 1 and isinstance(value, int) and not isinstance(value, bool):
                value, note = value // unit, f"判定コアの値 {f.get('value')} 円・欄は {unit} 円単位"
            row = [form["form"], form.get("name") or "", f.get("position") or "", f.get("number") or "", f.get("code") or "",
                   _render(f.get("row")), f.get("status") or "", _render(value), "", note]
            lines.append("\t".join(_clean(c) for c in row))
            n += 1
    (out / "observation.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    used = [f["form"] for f in forms.get("forms") or [] if f.get("use") is not False]
    print(f"{out.relative_to(ROOT).as_posix()}  帳票 {used}  記入表の行 {n}  対象外 {len(manifest['out_of_scope'])}  評価 {seconds}s")
    return 0


# ---------------------------------------------------------------- compare

def norm(s: str):
    s = unicodedata.normalize("NFKC", s or "").strip()
    s = s.replace(",", "").replace("円", "").replace(" ", "")
    # 0 と空欄は同じとみなす。申告書には 00・0000 のように位の 0 だけが印字される欄がある（2026-11-13 の A01 の観測）
    if s in ("", "-", "―", "－") or re.fullmatch(r"0+", s):
        return None
    if s in ("○", "◯", "✓", "レ", "True", "true"):
        return True
    if re.fullmatch(r"[△▲-]?\d+", s):
        return -int(s.lstrip("△▲-")) if s[0] in "△▲-" else int(s)
    return s


def read_tsv(path: pathlib.Path):
    header, rows, meta = None, [], {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            m = re.match(r"#\s*([^:：]+)[:：]\s*(.*)$", line)
            if m:
                meta[m.group(1).strip()] = m.group(2).strip()
            continue
        if not line.strip():
            continue
        cells = line.split("\t")
        if header is None:
            header = cells
            continue
        cells += [""] * (len(header) - len(cells))
        rows.append(dict(zip(header, cells)))
    return meta, rows


def cmd_compare(run_dir: pathlib.Path) -> int:
    meta, rows = read_tsv(run_dir / "observation.tsv")
    observed_forms = {x.strip() for x in re.split(r"[,、\s]+", meta.get("観測した帳票", "")) if x.strip()}
    # 2026-11-13：画面だけで一部の欄を見た帳票（PDF に出ない収支内訳書など）。観測値を書いた行だけ比べ、空の行は未観測
    partial_forms = {x.strip() for x in re.split(r"[,、\s]+", meta.get("一部だけ観測した帳票", "")) if x.strip()}
    if not observed_forms and not partial_forms:
        print("「# 観測した帳票:」が空。作成コーナーで見た帳票を書く", file=sys.stderr)
        return 2
    results = []
    for r in rows:
        form = r.get("帳票", "")
        status = r.get("状態", "")
        exp, obs = norm(r.get("期待値", "")), norm(r.get("観測値", ""))
        if form in partial_forms and form not in observed_forms and not r.get("観測値", "").strip():
            cls = "未観測"
        elif form not in observed_forms and form not in partial_forms:
            cls = "未観測"
        elif not status:
            cls = "作成コーナーだけ（記入表にない欄）" if obs is not None else "空の追加行"
        elif status == "未確定":
            cls = "未確定（期待値なし）"
        elif exp == obs:
            cls = "一致"
        elif exp is None:
            cls = "不一致（作成コーナーだけに値）"
        elif obs is None:
            cls = "不一致（判定コアだけに値）"
        else:
            cls = "不一致"
        results.append({"class": cls, **{k: r.get(k, "") for k in COLUMNS}})
    counts: dict[str, int] = {}
    for x in results:
        counts[x["class"]] = counts.get(x["class"], 0) + 1
    summary = {"run_dir": run_dir.resolve().relative_to(ROOT).as_posix(), "observed_forms": sorted(observed_forms),
               "partially_observed_forms": sorted(partial_forms),
               "meta": meta, "counts": counts, "rows": results}
    (run_dir / "compare.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    L = [f"# 照合の結果 {summary['run_dir']}", "", f"- 観測した帳票：{', '.join(sorted(observed_forms))}",
         f"- 一部だけ観測した帳票（画面で見た欄だけ）：{', '.join(sorted(partial_forms)) or 'なし'}",
         f"- 観測の日時：{meta.get('観測の日時', '')}", f"- 作成コーナーの画面の版：{meta.get('作成コーナーの画面の版（トップの年分・更新日など）', '')}", "",
         "| 区分 | 件数 |", "|---|---|"] + [f"| {k} | {v} |" for k, v in sorted(counts.items())] + [""]
    interesting = [x for x in results if x["class"] not in ("一致", "未観測", "空の追加行")]
    if interesting:
        L += ["## 一致しなかった欄・期待値のない欄", "", "| 区分 | 帳票 | 位置名 | 欄番号 | 状態 | 期待値 | 観測値 | 備考 |", "|---|---|---|---|---|---|---|---|"]
        for x in interesting:
            L.append(f"| {x['class']} | {x['帳票']} | {x['位置名']} | {x['欄番号']} | {x['状態']} | {x['期待値']} | {x['観測値']} | {x['備考']} |")
    (run_dir / "compare.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(json.dumps(counts, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    if not sys.flags.isolated:
        print("python -I -X utf8 で起動する", file=sys.stderr)
        sys.exit(2)
    a = sys.argv[1:]
    if a[:1] == ["expect"] and len(a) == 2:
        sys.exit(cmd_expect(pathlib.Path(a[1])))
    if a[:1] == ["compare"] and len(a) == 2:
        sys.exit(cmd_compare(pathlib.Path(a[1])))
    print(__doc__)
    sys.exit(2)
