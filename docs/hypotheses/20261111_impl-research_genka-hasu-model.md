# 仮説（impl-research genka）：減価償却費の端数の規則

- 作成：2026-11-11。根拠：［PS-GK］`docs/public-sources/20261111_impl-research_genka-hasu-nta.md`、［M-2C］`docs/measurements/20261111_impl-research_phase2c-fetch-and-checks.md`、［M-V］`docs/measurements/20261111_impl-research_phase2c-verification.md`。関連する既存の仮説：`docs/hypotheses/20261109_round2_genka-model.md` H3。

## H1 償却費の1円未満

- 規則の案：`償却費の端数` は**切り上げ**（作成コーナー よくある質問「減価償却費の計算で小数点以下の端数が生じた場合、切上げ処理を行っています。」。令和5〜7年分で同文）。根拠の種類は「国税庁の説明」（作成コーナーのよくある質問。D21 R5 で法令・通達・手引きの次）、印つき。根拠：［PS-GK］§2。
- 法令・通達・手引きに金額の 1 円未満の定めは見つからなかった（［PS-GK］§1・§3・§4）。ただし青色申告決算書の書き方（037.pdf・039.pdf）は読めていない。
- 法人の別表十六（一）の記載要領は切捨て（［PS-GK］§3）だが、個人の所得税の説明ではない。D21 R5 の順位では「国税庁の説明」（個人の FAQ）を採り、結論に法人の様式の切捨てを併記しない。
- 通基通119−6 の「確定金額を算出する過程の算出額」は税額の段階の話と読み（`docs/hypotheses/20261111_impl-research_hasu-model.md` H3）、ここには適用しない。

## H2 その他の端数（未確定のまま）

- `事業専用割合後の端数`、`一括償却_各年の端数`（`docs/hypotheses/20261109_round2_genka-model.md` §の表）は、FAQ の文言（「減価償却費の計算で小数点以下の端数が生じた場合」）に含まれるかが決まらない（［PS-GK］§5）。候補の全部で評価し（切上げ／切捨て）、金額だけの差なら D22 S3 で幅を返す。作成コーナーとの照合で確かめる（`docs/inferences/20261111_impl-research_hasu-cases.md`）。
