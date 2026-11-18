"""R2: PyPI の公開 JSON API からリリース履歴と最新版の配布ファイルを取得して記録する。

実行方法（どの Python 3.11+ でも可。標準ライブラリだけを使う）:
    python -I scripts/R2_pypi_release_history.py
出力: scripts/results/R2_pypi_release_history/<package>.txt
送信する情報はパッケージ名だけ（https://pypi.org/pypi/<name>/json への GET）。
"""
import json
import pathlib
import sys
import urllib.request

PACKAGES = ["OpenFisca-Core", "openfisca-japan", "beancount", "beanquery", "beangulp"]
OUT = pathlib.Path(__file__).resolve().parent / "results" / "R2_pypi_release_history"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name in PACKAGES:
        with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/json", timeout=30) as r:
            d = json.load(r)
        lines = [f"package: {name}", f"latest: {d['info']['version']}",
                 f"requires_python: {d['info']['requires_python']}",
                 f"license: {str(d['info'].get('license_expression') or d['info'].get('license')).splitlines()[0][:80]}", "",
                 "# 最近30件（最初のファイルのアップロード日時, バージョン）"]
        rel = sorted((min(f["upload_time"] for f in fs), v) for v, fs in d["releases"].items() if fs)
        lines += [f"{t} {v}" for t, v in rel[-30:]]
        lines += ["", f"# 最新版 {d['info']['version']} の配布ファイル（ファイル名, 種類, sha256）"]
        lines += [f"{f['filename']} {f['packagetype']} {f['digests']['sha256']}" for f in d["releases"][d["info"]["version"]]]
        (OUT / f"{name}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("\n".join(lines[:4]))


if __name__ == "__main__":
    sys.exit(main())
