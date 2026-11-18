#!/usr/bin/env bash
# R2: OpenFisca-Core 実測用 venv の依存一覧（バージョンつき）と、OSV での既知脆弱性の照会。
# venv の作り方（リポジトリのルートで。PyPI の wheel だけ、版を固定）:
#   uv venv .work/venvs/R2-openfisca --python 3.11
#   uv pip install --python .work/venvs/R2-openfisca/Scripts/python.exe --only-binary :all: "openfisca-core[web-api]==46.0.1"
# 送信するのはパッケージ名とバージョンだけ（個人の情報は送らない）。
# 使い方: bash scripts/R2_openfisca_deps_osv.sh
set -euo pipefail
OUT=scripts/results/R2_openfisca_deps_osv
mkdir -p "$OUT"
uv pip freeze --python .work/venvs/R2-openfisca/Scripts/python.exe | tr -d '\r' > "$OUT/freeze.txt"
{
  printf '{"queries":['
  sep=""
  while IFS='=' read -r name _ ver; do
    [ -z "$name" ] && continue
    printf '%s{"package":{"ecosystem":"PyPI","name":"%s"},"version":"%s"}' "$sep" "$name" "$ver"
    sep=","
  done < "$OUT/freeze.txt"
  printf ']}'
} > "$OUT/osv_query.json"
curl -s -X POST -H 'Content-Type: application/json' --data @"$OUT/osv_query.json" \
  https://api.osv.dev/v1/querybatch > "$OUT/osv_response.json"
# 該当した脆弱性の詳細（ID ごと）
mkdir -p "$OUT/vulns"
grep -o '"id":"[^"]*"' "$OUT/osv_response.json" | cut -d'"' -f4 | sort -u | while read -r id; do
  curl -s "https://api.osv.dev/v1/vulns/$id" > "$OUT/vulns/$id.json"
done
python -I scripts/R2_osv_summarize.py "$OUT"
date -u +%Y-%m-%dT%H:%M:%SZ > "$OUT/queried_at.txt"
echo "wrote $OUT"
