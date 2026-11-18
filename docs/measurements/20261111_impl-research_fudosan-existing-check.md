# 実測（impl-research fudosan）：不動産所得の損失のうち通算できない部分が既存の文書にあるかの確認

- 実施日：2026-11-11。種別：実測。
- スクリプト：`scripts/IMPL2_fudosan_existing.py`（標準ライブラリだけ。実行：`C:\Users\user\.pyenv\pyenv-win\versions\3.11.9\python.exe -I -X utf8 scripts/IMPL2_fudosan_existing.py`）。結果：`scripts/results/IMPL2_fudosan_existing/check.json`。条文は `scripts/results/IMPL2_phase2c_egov/fudosan/`（［M-2C］＝`docs/measurements/20261111_impl-research_phase2c-fetch-and-checks.md` §1）。

## 結果

- 既存の `docs/public-sources/20261109_round2b_fudosan-laws-and-nta.md`（［PS-F］）に次がある（文字列の照合：`措法41の4`、`措令26の6`、`措法41の4の2`、`措法41の4の3`、`別荘`、`所法69②`、`所令178` のすべてが `20261109_round2b_fudosan-*` のいずれかの文書にある）。
  - §4.1（所法69②・所令178①二、別荘等の損失）、§4.3（措法41の4①、措令26の6①②、措通41の4−1〜3、収支内訳書の書き方の説明）、§4.4（措法41の4の2 特定組合員等、措法41の4の3 国外中古建物）、TA1391（「損益通算の対象とならない不動産所得の損失」）。
  - 仮説 `docs/hypotheses/20261109_round2b_fudosan-calculation-model.md` に、通算できない部分（措令26の6①の min）を生じなかったものとみなす計算の順序、組合事業・国外中古建物は「対象外」とする扱いがある。
- 今回取得した令和7年分・令和8年分の版（措法 2025-12-31・2026-11-11・2026-12-31・2027-01-01）で、措法第41条の4 に「を取得するために要した負債の利子の額があるときは」「所得税法第六十九条第一項の規定その他の所得税に関する法令の規定の適用については、生じなかつたものとみなす」の文言があることを確かめた（`check.json` の statutes）。［M-2C］§3 で第41条の4 は R7・R8 で同文。

## 判断

新しい公開資料の文書は足さない（タスク (7) の「なければ足す」の条件に当たらない）。`docs/public-sources/20261109_round2_genka-laws-and-nta.md` などの「根拠条文は実装前に確認」は、上の ［PS-F］ §4.1・§4.3・§4.4 が根拠になる。措通41の4−3 の割合の端数の扱いは ［PS-F］§9-3 のとおり未解決（今回も一次情報を探していない）。
