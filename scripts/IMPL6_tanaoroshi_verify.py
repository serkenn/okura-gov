"""IMPL6 tanaoroshi verify: impl-research6 の公開資料の情報（docs/public-sources/20261112_impl-research6_tanaoroshi-laws-and-nta.md・
20261112_impl-research6_forms-tebiki.md）に引用した原文の語句が、取得した写しにあるかを確かめる。ネットワークは使わない。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL6_tanaoroshi_verify.py

- 入力：scripts/results/IMPL6_tanaoroshi_laws_egov/（条文の写し・sames.json）、scripts/results/IMPL6_tanaoroshi_web_fetch/（通達・手引きの写し）、
  scripts/results/IMPL6_tanaoroshi_pdftext/t003_text.tsv（損失申告用の手引きの文字）。
- 出力：scripts/results/IMPL6_tanaoroshi_verify/checks.json（語句ごとに見つかったか、版の比較、期限の曜日）。
"""
import datetime as dt
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
RES = ROOT / "scripts" / "results"
OUT = RES / "IMPL6_tanaoroshi_verify"

LAW = RES / "IMPL6_tanaoroshi_laws_egov"
WEB = RES / "IMPL6_tanaoroshi_web_fetch"

# (ファイル, 語句) ：docs に引用した原文の語句
PHRASES = [
    (LAW / "shoho_2025-12-31.txt", "評価の方法を選定しなかつた場合又は選定した評価の方法により評価しなかつた場合には、評価の方法のうち政令で定める方法により評価した金額"),
    (LAW / "shoho_2025-12-31.txt", "家事のために消費した場合"),
    (LAW / "shoho_2025-12-31.txt", "その事業の遂行上生じた売掛金、貸付金、前渡金その他これらに準ずる債権の貸倒れその他政令で定める事由により生じた損失の金額"),
    (LAW / "shorei_2025-12-31.txt", "その年分の所得税について青色申告書を提出することにつき税務署長の承認を受けていない場合には、第一号に掲げる方法"),
    (LAW / "shorei_2025-12-31.txt", "当該事業を開始した日"),
    (LAW / "shorei_2025-12-31.txt", "その新たな評価の方法を採用しようとする年の三月十五日まで"),
    (LAW / "shorei_2025-12-31.txt", "その年十二月三十一日までにその申請につき承認又は却下の処分がなかつたときは、同日においてその承認があつたものとみなす"),
    (LAW / "shorei_2025-12-31.txt", "第九十九条第一項第一号ホ（棚卸資産の評価の方法）に掲げる最終仕入原価法により算出した取得価額による原価法とする"),
    (LAW / "shorei_2025-12-31.txt", "販売した商品の返戻又は値引き"),
    (WEB / "tsutatsu" / "kihon_06_01.txt", "著しく低額（おおむね70%未満）でない限り"),
    (WEB / "tsutatsu" / "kihon_06_01.txt", "その者の通常他に販売する価額"),
    (WEB / "tsutatsu" / "kihon_08_01.txt", "令第99条第1項第1号に掲げる評価の方法に準じて計算する"),
    (WEB / "tsutatsu" / "kihon_08_03.txt", "各年の12月31日において実地棚卸しをしなければならない"),
    (WEB / "tsutatsu" / "kihon_09_02.txt", "備忘価額を控除した残額"),
    (WEB / "tsutatsu" / "kihon_09_02.txt", "不動産貸付業者の未収賃貸料"),
    (WEB / "tebiki" / "t_3_2_01.txt", "家内労働者（措法27）"),
    (WEB / "tebiki" / "t_3_3_13.txt", "計算欄Kに計算欄Hの金額を記入したとき"),
    (WEB / "tebiki" / "t_3_3_13.txt", "計算欄Kに計算欄Jの金額を記入したとき"),
    (WEB / "tebiki" / "t_3_5_01.txt", "雑所得、一時所得、臨時所得、株式等の譲渡所得及び退職所得の金額に対する所得税等の源泉徴収税額の合計額"),
    (WEB / "tebiki" / "t_3_6_02.txt", "確定申告不要制度を選択した"),
    (WEB / "tebiki" / "t_3_6_02.txt", "所得税等の確定申告をした場合は、配当割額及び株式等譲渡所得割額を記入します"),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    found = []
    for path, phrase in PHRASES:
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        found.append({"file": str(path.relative_to(ROOT)).replace("\\", "/"), "phrase": phrase, "found": phrase in text})
    # 損失申告用の手引きの「特例適用条文」の説明（文字の断片をつないで探す）
    tsv = RES / "IMPL6_tanaoroshi_pdftext" / "t003_text.tsv"
    joined = "".join(line.split("\t")[4] for line in tsv.read_text(encoding="utf-8", errors="replace").splitlines()[2:] if line.count("\t") >= 4) if tsv.exists() else ""
    found.append({"file": "scripts/results/IMPL6_tanaoroshi_pdftext/t003_text.tsv", "phrase": "課税の特例を受ける場合には、その適用を受ける条文を記入します",
                  "found": "課税の特例を受ける場合には、その適用を受" in joined and "ける条文を記入します" in joined})
    sames = json.loads((LAW / "sames.json").read_text(encoding="utf-8"))
    changed = {k: v["changed_between_consecutive"] for k, v in sames.items()}
    weekdays = {d: dt.date.fromisoformat(d).strftime("%A") for d in ("2021-03-15", "2021-03-16", "2025-03-15", "2025-03-17", "2026-03-15")}
    out = {"phrases": found, "all_found": all(f["found"] for f in found), "changed_articles_between_versions": changed, "weekdays": weekdays}
    (OUT / "checks.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("all_found", out["all_found"], "missing", [f["phrase"][:30] for f in found if not f["found"]])
    print("changed", changed)
    print("weekdays", weekdays)


if __name__ == "__main__":
    main()
