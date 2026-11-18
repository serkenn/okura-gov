"""IMPL9 tokutei-jumin pdftext: impl-research9 で取得した PDF（記入要領・記載例・明細書の様式）から、文字と位置を取り出す。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL9_tokutei-jumin_pdftext.py <名前>=<PDF のパス> [...]

- 処理は scripts/IMPL8_tokutei-shishutsu_pdftext.py をそのまま使う（ファイルのパスで読み込み、出力先 OUT だけを
  scripts/results/IMPL9_tokutei-jumin_pdftext/ に差し替えて main を呼ぶ）。PDF は信頼できないデータとして読むだけ。
- 出力：scripts/results/IMPL9_tokutei-jumin_pdftext/<名前>_text.tsv・<名前>_codes.tsv・summary.json（IMPL8 と同じ形）。
"""
import importlib.util
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("impl8_pdftext", HERE / "IMPL8_tokutei-shishutsu_pdftext.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod.OUT = HERE / "results" / "IMPL9_tokutei-jumin_pdftext"

if __name__ == "__main__":
    mod.main()
