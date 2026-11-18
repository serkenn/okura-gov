# 仮説（impl-research hasu）：生命保険料・地震保険料・公的年金等の端数の規則

- 作成：2026-11-11。根拠：［PS-HS］`docs/public-sources/20261111_impl-research_hasu-tebiki-and-nta.md`、［M-2C］`docs/measurements/20261111_impl-research_phase2c-fetch-and-checks.md`、［M-V］`docs/measurements/20261111_impl-research_phase2c-verification.md`。D21 R5（法令＞通達＞手引き＞国税庁の説明）、D22 S2・S3。

## H1 生命保険料控除・地震保険料控除

- 規則：計算で生じた1円未満は切り上げ（`切上げ.生命保険料控除`、`切上げ.地震保険料控除`）。根拠の種類は「手引き」（令和7年分は「切り上げて差し支えありません」、令和8年分は年末調整のしかたで「切り上げます」、［PS-HS］§1・§2）。
- 適用の箇所（手引きの計算欄）：区分ごとの式（C・D・H・I・J、G・I）の結果を切り上げる（注は「控除額の計算において算出した金額」）。**合計の前か後かは明示がない**（［PS-HS］§7-2）。区分ごとの式の結果に切上げを適用する案と、合計で切上げる案を候補にする（`docs/inferences/20261111_impl-research_hasu-cases.md`）。
- 「差し支えありません」は任意の表現。D21 R5 に基づき切上げを採り、結果の根拠に「手引き（令和7年分）」「手引きの本文は任意」と記録する。

## H2 公的年金等の雑所得

- 規則：雑所得の金額の1円未満は切捨て（`切捨て.公的年金等の雑所得`）。根拠の種類は「手引き」（3-2_07、令和7年分）。［PS-HS］§3。
- 令和8年分の手引きは未公表（［PS-HS］§6）。令和7年分と同じ規則を令和8年分に使い、根拠に「手引き（令和7年分）」と記録する。
- 控除額は `収入 − 雑所得` で出す（控除額そのものの端数は定めがない）。既存 `docs/hypotheses/20261109_round2b_nenkin-model.md` の未解決事項 `公的年金等控除額の円未満処理` の候補は、雑所得の切捨てに確定する。

## H3 税額の段階の1円未満（通基通119−6）

- 配当控除額（`docs/hypotheses/20261111_impl-research_haito-model.md`）、復興特別所得税額（`docs/hypotheses/20261111_impl-research_gensen-model.md`）の1円未満は切捨て。根拠の種類は「通達」（［PS-HS］§5）。
- 所得金額の段階には適用しない（手引き・FAQ が別の処理を定めている：生命保険料の切上げ、減価償却費の切上げ。`docs/hypotheses/20261111_impl-research_genka-hasu-model.md`）。
