#!/usr/bin/env bash
# R2: beancount 実測用 venv の依存一覧と、OSV / GitHub Advisory での既知脆弱性の照会。
# 前提: scripts/R2_beancount_check.py の先頭の手順で .work/venvs/R2-beancount を作ってあること。
# 送信するのはパッケージ名とバージョンだけ（個人の情報は送らない）。
# 使い方（リポジトリのルートで）: bash scripts/R2_beancount_deps_osv.sh
set -euo pipefail
OUT=scripts/results/R2_beancount_deps_osv
mkdir -p "$OUT"
uv pip freeze --python .work/venvs/R2-beancount > "$OUT/freeze.txt"
# freeze の結果と、使わないが比較のために beangulp 0.2.0 も照会する
{
  printf '{"queries":['
  sep=""
  while IFS='=' read -r name _ ver; do
    [ -z "$name" ] && continue
    printf '%s{"package":{"ecosystem":"PyPI","name":"%s"},"version":"%s"}' "$sep" "$name" "$ver"
    sep=","
  done < <(tr -d '\r' < "$OUT/freeze.txt")
  printf '%s{"package":{"ecosystem":"PyPI","name":"beangulp"},"version":"0.2.0"}' "$sep"
  printf ']}'
} > "$OUT/osv_query.json"
curl -s -X POST -H 'Content-Type: application/json' --data @"$OUT/osv_query.json" \
  https://api.osv.dev/v1/querybatch > "$OUT/osv_response.json"
# 全バージョンについての照会（beancount 系と hledger-web）
for spec in PyPI:beancount PyPI:beanquery PyPI:beangulp Hackage:hledger Hackage:hledger-lib Hackage:hledger-web; do
  eco=${spec%%:*}; name=${spec#*:}
  curl -s -X POST -H 'Content-Type: application/json' \
    -d "{\"package\":{\"ecosystem\":\"$eco\",\"name\":\"$name\"}}" https://api.osv.dev/v1/query \
    > "$OUT/osv_allversions_${eco}_${name}.json"
done
# GitHub Advisory（gh CLI が使える場合）
if command -v gh >/dev/null 2>&1; then
  for p in beancount beanquery beangulp; do
    MSYS_NO_PATHCONV=1 gh api "advisories?ecosystem=pip&affects=$p&per_page=50" > "$OUT/ghsa_pip_$p.json" || true
  done
  for r in beancount/beancount simonmichael/hledger ledger/ledger; do
    MSYS_NO_PATHCONV=1 gh api "repos/$r/security-advisories" > "$OUT/ghsa_repo_${r//\//_}.json" || true
  done
fi
date -u +%Y-%m-%dT%H:%M:%SZ > "$OUT/queried_at.txt"
echo "wrote $OUT"
