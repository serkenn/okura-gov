"""IMPL6_tanaoroshi_pdftext: scripts/IMPL6_tanaoroshi_web_fetch.py が取得した PDF（国税庁の手引き・書き方・記載例）から文字と位置を取り出す。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ。ネットワークは使わない）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL6_tanaoroshi_pdftext.py <名前>=<PDF のパス> [...]

- 取り出しの処理は scripts/IMPL4_web_pdftext.py（ファイルの場所から読み込む。中身は変えない）を使い、出力先だけを
  scripts/results/IMPL6_tanaoroshi_pdftext/ に変える（<名前>_text.tsv：頁, x, y, フォント, 文字列。summary.json）。
- 入力の PDF は .work/downloads/<ts>_IMPL6_tanaoroshi_web_fetch_<set>/ の信頼できないデータ。パスを引数で受け取って読むだけ。
"""
import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("impl4_web_pdftext", ROOT / "scripts" / "IMPL4_web_pdftext.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
_mod.OUT = ROOT / "scripts" / "results" / "IMPL6_tanaoroshi_pdftext"

if __name__ == "__main__":
    _mod.OUT.mkdir(parents=True, exist_ok=True)
    _mod.main()
