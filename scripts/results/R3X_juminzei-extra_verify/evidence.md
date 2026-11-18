# R3X juminzei-extra 検証：検査の結果

- 取得：20261111-032246（.work\downloads\20261111-032246_R3X_juminzei-extra_verify_laws、.work\downloads\20261111-032246_R3X_juminzei-extra_verify_web）。生成：scripts/R3X_juminzei-extra_verify.py
- 結果：OK 444・NG 5・判定なし 9（情報、動的なページの差、文言の限定が要るもの）。NG は文書の記述と一次情報が合わないもの。

| ID | 文書の箇所 | 文書の記述（期待） | 結果 | 見つかったもの |
|---|---|---|---|---|
| V0-rev | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §0・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §2.1 | chiho asof 2025-01-01：law_revision_id=325AC0000000226_20250101_506AC0000000004・状態=PreviousEnforced・SHA-256 先頭=228e182f179fb138 | OK | 今回：325AC0000000226_20250101_506AC0000000004 PreviousEnforced 228e182f179fb138 |
| V0-rev | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §0・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §2.1 | chiho asof 2026-01-01：law_revision_id=325AC0000000226_20260101_507AC0000000041・状態=PreviousEnforced・SHA-256 先頭=ba0a40e550be7762 | OK | 今回：325AC0000000226_20260101_507AC0000000041 PreviousEnforced ba0a40e550be7762 |
| V0-rev | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §0・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §2.1 | chiho asof 2026-04-01：law_revision_id=325AC0000000226_20260401_508AC0000000002・状態=PreviousEnforced・SHA-256 先頭=06db2ba6ccfec62e | OK | 今回：325AC0000000226_20260401_508AC0000000002 PreviousEnforced 06db2ba6ccfec62e |
| V0-rev | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §0・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §2.1 | chiho asof 2026-11-09：law_revision_id=325AC0000000226_20261101_508AC0000000002・状態=CurrentEnforced・SHA-256 先頭=3dd29e0078bf24e0 | OK | 今回：325AC0000000226_20261101_508AC0000000002 CurrentEnforced 3dd29e0078bf24e0 |
| V0-rev | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §0・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §2.1 | chiho asof 2027-01-01：law_revision_id=325AC0000000226_20270101_508AC0000000002・状態=UnEnforced・SHA-256 先頭=ee21722ce5fd1561 | OK | 今回：325AC0000000226_20270101_508AC0000000002 UnEnforced ee21722ce5fd1561 |
| V0-rev | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §0・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §2.1 | chiho asof 2028-01-01：law_revision_id=325AC0000000226_20280101_508AC0000000002・状態=UnEnforced・SHA-256 先頭=ba69aa86514c9750 | OK | 今回：325AC0000000226_20280101_508AC0000000002 UnEnforced ba69aa86514c9750 |
| V0-rev | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §0・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §2.1 | chiho asof 2030-01-01：law_revision_id=325AC0000000226_20290624_508AC0000000051・状態=UnEnforced・SHA-256 先頭=3257c8e4f4aa68e8 | OK | 今回：325AC0000000226_20290624_508AC0000000051 UnEnforced 3257c8e4f4aa68e8 |
| V0-rev | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §0・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §2.1 | chiho-rei asof 2026-01-01：law_revision_id=325CO0000000245_20260101_507CO0000000119・状態=PreviousEnforced・SHA-256 先頭=e6224a70357bbc64 | OK | 今回：325CO0000000245_20260101_507CO0000000119 PreviousEnforced e6224a70357bbc64 |
| V0-rev | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §0・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §2.1 | chiho-rei asof 2026-11-09：law_revision_id=325CO0000000245_20261101_508CO0000000083・状態=CurrentEnforced・SHA-256 先頭=9bc03b230fb0ed10 | OK | 今回：325CO0000000245_20261101_508CO0000000083 CurrentEnforced 9bc03b230fb0ed10 |
| V0-rev | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §0・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §2.1 | chiho-rei asof 2027-01-01：law_revision_id=325CO0000000245_20270101_508CO0000000083・状態=UnEnforced・SHA-256 先頭=962bfc48e43c49b4 | OK | 今回：325CO0000000245_20270101_508CO0000000083 UnEnforced 962bfc48e43c49b4 |
| V0-rev | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §0・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §2.1 | chiho-kisoku asof 2026-01-01：law_revision_id=329M50000002023_20260101_507M60000008116・状態=PreviousEnforced・SHA-256 先頭=285e203a423a4fee | OK | 今回：329M50000002023_20260101_507M60000008116 PreviousEnforced 285e203a423a4fee |
| V0-rev | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §0・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §2.1 | chiho-kisoku asof 2026-11-09：law_revision_id=329M50000002023_20261101_508M60000008045・状態=CurrentEnforced・SHA-256 先頭=5ffb833bd3a3d7c4 | OK | 今回：329M50000002023_20261101_508M60000008045 CurrentEnforced 5ffb833bd3a3d7c4 |
| V0-rev | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §0・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §2.1 | chiho-kisoku asof 2027-01-01：law_revision_id=329M50000002023_20270101_508M60000008089・状態=UnEnforced・SHA-256 先頭=e8d5c022315165a3 | OK | 今回：329M50000002023_20270101_508M60000008089 UnEnforced e8d5c022315165a3 |
| V0-rev | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §0・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §2.1 | sochi asof 2026-11-09：law_revision_id=332AC0000000026_20261101_507AC0000000013・状態=CurrentEnforced・SHA-256 先頭=e6e6013bbc0608c6 | OK | 今回：332AC0000000026_20261101_507AC0000000013 CurrentEnforced e6e6013bbc0608c6 |
| V0-kisoku | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §0 | 地方税法施行規則＝昭和29年総理府令第23号（law_id 329M50000002023） | OK | 昭和二十九年総理府令第二十三号 |
| V1-01 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.1 | 第294条第1項柱書：第2号・第4号の者は均等割額 | OK | chiho@2025-01-01 main:294 第1項 |
| V1-01 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.1 | 第294条第1項柱書：第2号・第4号の者は均等割額 | OK | chiho@2026-01-01 main:294 第1項 |
| V1-01 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.1 | 第294条第1項柱書：第2号・第4号の者は均等割額 | OK | chiho@2026-04-01 main:294 第1項 |
| V1-01 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.1 | 第294条第1項柱書：第2号・第4号の者は均等割額 | OK | chiho@2026-11-09 main:294 第1項 |
| V1-01 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.1 | 第294条第1項柱書：第2号・第4号の者は均等割額 | OK | chiho@2027-01-01 main:294 第1項 |
| V1-01 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.1 | 第294条第1項柱書：第2号・第4号の者は均等割額 | OK | chiho@2028-01-01 main:294 第1項 |
| V1-02 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.1 | 第294条第1項第2号 | OK | chiho@2025-01-01 main:294 第1項 第2号 |
| V1-02 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.1 | 第294条第1項第2号 | OK | chiho@2026-01-01 main:294 第1項 第2号 |
| V1-02 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.1 | 第294条第1項第2号 | OK | chiho@2026-04-01 main:294 第1項 第2号 |
| V1-02 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.1 | 第294条第1項第2号 | OK | chiho@2026-11-09 main:294 第1項 第2号 |
| V1-02 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.1 | 第294条第1項第2号 | OK | chiho@2027-01-01 main:294 第1項 第2号 |
| V1-02 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.1 | 第294条第1項第2号 | OK | chiho@2028-01-01 main:294 第1項 第2号 |
| V1-03 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.1 | 第24条第1項柱書 | OK | chiho@2025-01-01 main:24 第1項 |
| V1-03 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.1 | 第24条第1項柱書 | OK | chiho@2026-01-01 main:24 第1項 |
| V1-03 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.1 | 第24条第1項柱書 | OK | chiho@2026-04-01 main:24 第1項 |
| V1-03 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.1 | 第24条第1項柱書 | OK | chiho@2026-11-09 main:24 第1項 |
| V1-03 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.1 | 第24条第1項柱書 | OK | chiho@2027-01-01 main:24 第1項 |
| V1-03 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.1 | 第24条第1項柱書 | OK | chiho@2028-01-01 main:24 第1項 |
| V1-04 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.1 | 第24条第1項第2号 | OK | chiho@2025-01-01 main:24 第1項 第2号 |
| V1-04 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.1 | 第24条第1項第2号 | OK | chiho@2026-01-01 main:24 第1項 第2号 |
| V1-04 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.1 | 第24条第1項第2号 | OK | chiho@2026-04-01 main:24 第1項 第2号 |
| V1-04 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.1 | 第24条第1項第2号 | OK | chiho@2026-11-09 main:24 第1項 第2号 |
| V1-04 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.1 | 第24条第1項第2号 | OK | chiho@2027-01-01 main:24 第1項 第2号 |
| V1-04 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.1 | 第24条第1項第2号 | OK | chiho@2028-01-01 main:24 第1項 第2号 |
| V1-05 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.1 | 第24条第7項 | OK | chiho@2025-01-01 main:24 第7項 |
| V1-05 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.1 | 第24条第7項 | OK | chiho@2026-01-01 main:24 第7項 |
| V1-05 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.1 | 第24条第7項 | OK | chiho@2026-04-01 main:24 第7項 |
| V1-05 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.1 | 第24条第7項 | OK | chiho@2026-11-09 main:24 第7項 |
| V1-05 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.1 | 第24条第7項 | OK | chiho@2027-01-01 main:24 第7項 |
| V1-05 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.1 | 第24条第7項 | OK | chiho@2028-01-01 main:24 第7項 |
| V1-06 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.2 | 第318条（賦課期日 1月1日） | OK | chiho@2025-01-01 main:318 第1項 |
| V1-06 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.2 | 第318条（賦課期日 1月1日） | OK | chiho@2026-01-01 main:318 第1項 |
| V1-06 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.2 | 第318条（賦課期日 1月1日） | OK | chiho@2026-04-01 main:318 第1項 |
| V1-06 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.2 | 第318条（賦課期日 1月1日） | OK | chiho@2026-11-09 main:318 第1項 |
| V1-06 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.2 | 第318条（賦課期日 1月1日） | OK | chiho@2027-01-01 main:318 第1項 |
| V1-06 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.2 | 第318条（賦課期日 1月1日） | OK | chiho@2028-01-01 main:318 第1項 |
| V1-07 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.2 | 第39条（同） | OK | chiho@2025-01-01 main:39 第1項 |
| V1-07 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.2 | 第39条（同） | OK | chiho@2026-01-01 main:39 第1項 |
| V1-07 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.2 | 第39条（同） | OK | chiho@2026-04-01 main:39 第1項 |
| V1-07 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.2 | 第39条（同） | OK | chiho@2026-11-09 main:39 第1項 |
| V1-07 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.2 | 第39条（同） | OK | chiho@2027-01-01 main:39 第1項 |
| V1-07 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.2 | 第39条（同） | OK | chiho@2028-01-01 main:39 第1項 |
| V1-08 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.2 | 第317条の2第8項（家屋敷等の申告） | OK | chiho@2026-01-01 main:317_2 第8項 |
| V1-08 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.2 | 第317条の2第8項（家屋敷等の申告） | OK | chiho@2026-11-09 main:317_2 第8項 |
| V1-08 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.2 | 第317条の2第8項（家屋敷等の申告） | OK | chiho@2027-01-01 main:317_2 第8項 |
| V1-09 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.3 | 第294条第2項 | OK | chiho@2025-01-01 main:294 第2項 |
| V1-09 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.3 | 第294条第2項 | OK | chiho@2026-01-01 main:294 第2項 |
| V1-09 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.3 | 第294条第2項 | OK | chiho@2026-04-01 main:294 第2項 |
| V1-09 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.3 | 第294条第2項 | OK | chiho@2026-11-09 main:294 第2項 |
| V1-09 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.3 | 第294条第2項 | OK | chiho@2027-01-01 main:294 第2項 |
| V1-09 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.3 | 第294条第2項 | OK | chiho@2028-01-01 main:294 第2項 |
| V1-10 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.3 | 第294条第3項 | OK | chiho@2025-01-01 main:294 第3項 |
| V1-10 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.3 | 第294条第3項 | OK | chiho@2026-01-01 main:294 第3項 |
| V1-10 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.3 | 第294条第3項 | OK | chiho@2026-04-01 main:294 第3項 |
| V1-10 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.3 | 第294条第3項 | OK | chiho@2026-11-09 main:294 第3項 |
| V1-10 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.3 | 第294条第3項 | OK | chiho@2027-01-01 main:294 第3項 |
| V1-10 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.3 | 第294条第3項 | OK | chiho@2028-01-01 main:294 第3項 |
| V1-11 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.3 | 第294条第4項 | OK | chiho@2025-01-01 main:294 第4項 |
| V1-11 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.3 | 第294条第4項 | OK | chiho@2026-01-01 main:294 第4項 |
| V1-11 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.3 | 第294条第4項 | OK | chiho@2026-04-01 main:294 第4項 |
| V1-11 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.3 | 第294条第4項 | OK | chiho@2026-11-09 main:294 第4項 |
| V1-11 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.3 | 第294条第4項 | OK | chiho@2027-01-01 main:294 第4項 |
| V1-11 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.3 | 第294条第4項 | OK | chiho@2028-01-01 main:294 第4項 |
| V1-12 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.4 | 第737条第1項 | OK | chiho@2025-01-01 main:737 第1項 |
| V1-12 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.4 | 第737条第1項 | OK | chiho@2026-01-01 main:737 第1項 |
| V1-12 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.4 | 第737条第1項 | OK | chiho@2026-04-01 main:737 第1項 |
| V1-12 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.4 | 第737条第1項 | OK | chiho@2026-11-09 main:737 第1項 |
| V1-12 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.4 | 第737条第1項 | OK | chiho@2027-01-01 main:737 第1項 |
| V1-12 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.4 | 第737条第1項 | OK | chiho@2028-01-01 main:737 第1項 |
| V1-13 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 第295条第1項ただし書 | OK | chiho@2025-01-01 main:295 第1項 |
| V1-13 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 第295条第1項ただし書 | OK | chiho@2026-01-01 main:295 第1項 |
| V1-13 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 第295条第1項ただし書 | OK | chiho@2026-04-01 main:295 第1項 |
| V1-13 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 第295条第1項ただし書 | OK | chiho@2026-11-09 main:295 第1項 |
| V1-13 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 第295条第1項ただし書 | OK | chiho@2027-01-01 main:295 第1項 |
| V1-13 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 第295条第1項ただし書 | OK | chiho@2028-01-01 main:295 第1項 |
| V1-14 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 第295条第1項第1号 | OK | chiho@2025-01-01 main:295 第1項 第1号 |
| V1-14 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 第295条第1項第1号 | OK | chiho@2026-01-01 main:295 第1項 第1号 |
| V1-14 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 第295条第1項第1号 | OK | chiho@2026-04-01 main:295 第1項 第1号 |
| V1-14 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 第295条第1項第1号 | OK | chiho@2026-11-09 main:295 第1項 第1号 |
| V1-14 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 第295条第1項第1号 | OK | chiho@2027-01-01 main:295 第1項 第1号 |
| V1-14 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 第295条第1項第1号 | OK | chiho@2028-01-01 main:295 第1項 第1号 |
| V1-15 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 第295条第1項第2号（135万円） | OK | chiho@2025-01-01 main:295 第1項 第2号 |
| V1-15 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 第295条第1項第2号（135万円） | OK | chiho@2026-01-01 main:295 第1項 第2号 |
| V1-15 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 第295条第1項第2号（135万円） | OK | chiho@2026-04-01 main:295 第1項 第2号 |
| V1-15 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 第295条第1項第2号（135万円） | OK | chiho@2026-11-09 main:295 第1項 第2号 |
| V1-15 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 第295条第1項第2号（135万円） | OK | chiho@2027-01-01 main:295 第1項 第2号 |
| V1-15 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 第295条第1項第2号（135万円） | OK | chiho@2028-01-01 main:295 第1項 第2号 |
| V1-16 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 第295条第3項 | OK | chiho@2025-01-01 main:295 第3項 |
| V1-16 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 第295条第3項 | OK | chiho@2026-01-01 main:295 第3項 |
| V1-16 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 第295条第3項 | OK | chiho@2026-04-01 main:295 第3項 |
| V1-16 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 第295条第3項 | OK | chiho@2026-11-09 main:295 第3項 |
| V1-16 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 第295条第3項 | OK | chiho@2027-01-01 main:295 第3項 |
| V1-16 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 第295条第3項 | OK | chiho@2028-01-01 main:295 第3項 |
| V1-17 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 第295条に第294条第1項第2号を名指しして除く文言はない | OK | chiho@2025-01-01 main:295 |
| V1-17 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 第295条に第294条第1項第2号を名指しして除く文言はない | OK | chiho@2026-01-01 main:295 |
| V1-17 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 第295条に第294条第1項第2号を名指しして除く文言はない | OK | chiho@2026-04-01 main:295 |
| V1-17 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 第295条に第294条第1項第2号を名指しして除く文言はない | OK | chiho@2026-11-09 main:295 |
| V1-17 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 第295条に第294条第1項第2号を名指しして除く文言はない | OK | chiho@2027-01-01 main:295 |
| V1-17 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 第295条に第294条第1項第2号を名指しして除く文言はない | OK | chiho@2028-01-01 main:295 |
| V1-18 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 第24条の5第1項ただし書 | OK | chiho@2025-01-01 main:24_5 第1項 |
| V1-18 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 第24条の5第1項ただし書 | OK | chiho@2026-01-01 main:24_5 第1項 |
| V1-18 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 第24条の5第1項ただし書 | OK | chiho@2026-04-01 main:24_5 第1項 |
| V1-18 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 第24条の5第1項ただし書 | OK | chiho@2026-11-09 main:24_5 第1項 |
| V1-18 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 第24条の5第1項ただし書 | OK | chiho@2027-01-01 main:24_5 第1項 |
| V1-18 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 第24条の5第1項ただし書 | OK | chiho@2028-01-01 main:24_5 第1項 |
| V1-19 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 第24条の5第3項 | OK | chiho@2025-01-01 main:24_5 第3項 |
| V1-19 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 第24条の5第3項 | OK | chiho@2026-01-01 main:24_5 第3項 |
| V1-19 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 第24条の5第3項 | OK | chiho@2026-04-01 main:24_5 第3項 |
| V1-19 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 第24条の5第3項 | OK | chiho@2026-11-09 main:24_5 第3項 |
| V1-19 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 第24条の5第3項 | OK | chiho@2027-01-01 main:24_5 第3項 |
| V1-19 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 第24条の5第3項 | OK | chiho@2028-01-01 main:24_5 第3項 |
| V1-20 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.5 | 施行令第47条の3 は第295条第3項の政令の基準 | OK | chiho-rei@2026-11-09 main:47_3 第1項 |
| V1-21 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.6 | 第300条第1項（列挙に家屋敷なし） | OK | chiho@2026-11-09 main:300 第1項 |
| V1-22 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.6 | 第300条第2項 | OK | chiho@2026-11-09 main:300 第2項 |
| V1-23 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.6 | 第320条 | OK | chiho@2025-01-01 main:320 第1項 |
| V1-23 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.6 | 第320条 | OK | chiho@2026-01-01 main:320 第1項 |
| V1-23 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.6 | 第320条 | OK | chiho@2026-04-01 main:320 第1項 |
| V1-23 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.6 | 第320条 | OK | chiho@2026-11-09 main:320 第1項 |
| V1-23 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.6 | 第320条 | OK | chiho@2027-01-01 main:320 第1項 |
| V1-23 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.6 | 第320条 | OK | chiho@2028-01-01 main:320 第1項 |
| V1-24 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.6 | 第41条第1項 | OK | chiho@2026-11-09 main:41 第1項 |
| V1-25-41 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.6 | 第41条第3項が第294条第1項第2号の均等割を名指し | OK | chiho@2026-11-09 main:41 第3項 |
| V1-25-17_2 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.6 | 第17条の2第2項が第294条第1項第2号の均等割を名指し | OK | chiho@2026-11-09 main:17_2 第2項 |
| V1-25-17_4 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.6 | 第17条の4第6項が第294条第1項第2号の均等割を名指し | OK | chiho@2026-11-09 main:17_4 第6項 |
| V1-25-739_2 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.6 | 第739条の2第1項が第294条第1項第2号の均等割を名指し | OK | chiho@2026-11-09 main:739_2 第1項 |
| V1-25-739_5 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.6 | 第739条の5第1項が第294条第1項第2号の均等割を名指し | OK | chiho@2026-11-09 main:739_5 第1項 |
| V1-26 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.6 | 第319条第2項 | OK | chiho@2026-11-09 main:319 第2項 |
| V1-27 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.7 | 第310条（3,000円） | OK | chiho@2025-01-01 main:310 第1項 |
| V1-27 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.7 | 第310条（3,000円） | OK | chiho@2026-01-01 main:310 第1項 |
| V1-27 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.7 | 第310条（3,000円） | OK | chiho@2026-04-01 main:310 第1項 |
| V1-27 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.7 | 第310条（3,000円） | OK | chiho@2026-11-09 main:310 第1項 |
| V1-27 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.7 | 第310条（3,000円） | OK | chiho@2027-01-01 main:310 第1項 |
| V1-27 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.7 | 第310条（3,000円） | OK | chiho@2028-01-01 main:310 第1項 |
| V1-28 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.7 | 第38条（1,000円） | OK | chiho@2026-01-01 main:38 第1項 |
| V1-28 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.7 | 第38条（1,000円） | OK | chiho@2026-11-09 main:38 第1項 |
| V1-28 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.7 | 第38条（1,000円） | OK | chiho@2027-01-01 main:38 第1項 |
| V1-29 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.7 | 森林環境税法第3条（施行地に住所を有する個人） | OK | shinrin@2026-11-09 main:3 第1項 |
| V1-30 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.8・§1.6・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §4.1 | asof 2025-01-01：「家屋敷」を含む条（本則・原始附則）は ['main:20_3', 'main:20_4', 'main:24', 'main:294', 'main:317_2']、改正附則に 0 | OK | ['main:20_3', 'main:20_4', 'main:24', 'main:294', 'main:317_2'] 改正附則=[] |
| V1-31 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.8 | asof 2025-01-01：「家屋敷とは」「家屋敷をいう」はない | OK | [] |
| V1-30 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.8・§1.6・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §4.1 | asof 2025-01-01：「第二百九十四条第一項第二号」を含む条（本則・原始附則）は ['main:17_2', 'main:17_2_2', 'main:17_4', 'main:41', 'main:317_2', 'main:739_2', 'main:739_5']、改正附則に 0 | OK | ['main:17_2', 'main:17_2_2', 'main:17_4', 'main:41', 'main:317_2', 'main:739_2', 'main:739_5'] 改正附則=[] |
| V1-30 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.8・§1.6・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §4.1 | asof 2026-01-01：「家屋敷」を含む条（本則・原始附則）は ['main:20_3', 'main:20_4', 'main:24', 'main:294', 'main:317_2']、改正附則に 0 | OK | ['main:20_3', 'main:20_4', 'main:24', 'main:294', 'main:317_2'] 改正附則=[] |
| V1-31 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.8 | asof 2026-01-01：「家屋敷とは」「家屋敷をいう」はない | OK | [] |
| V1-30 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.8・§1.6・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §4.1 | asof 2026-01-01：「第二百九十四条第一項第二号」を含む条（本則・原始附則）は ['main:17_2', 'main:17_2_2', 'main:17_4', 'main:41', 'main:317_2', 'main:739_2', 'main:739_5']、改正附則に 0 | OK | ['main:17_2', 'main:17_2_2', 'main:17_4', 'main:41', 'main:317_2', 'main:739_2', 'main:739_5'] 改正附則=[] |
| V1-30 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.8・§1.6・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §4.1 | asof 2026-04-01：「家屋敷」を含む条（本則・原始附則）は ['main:20_3', 'main:20_4', 'main:24', 'main:294', 'main:317_2']、改正附則に 0 | OK | ['main:20_3', 'main:20_4', 'main:24', 'main:294', 'main:317_2'] 改正附則=[] |
| V1-31 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.8 | asof 2026-04-01：「家屋敷とは」「家屋敷をいう」はない | OK | [] |
| V1-30 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.8・§1.6・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §4.1 | asof 2026-04-01：「第二百九十四条第一項第二号」を含む条（本則・原始附則）は ['main:17_2', 'main:17_2_2', 'main:17_4', 'main:41', 'main:317_2', 'main:739_2', 'main:739_5']、改正附則に 0 | OK | ['main:17_2', 'main:17_2_2', 'main:17_4', 'main:41', 'main:317_2', 'main:739_2', 'main:739_5'] 改正附則=[] |
| V1-30 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.8・§1.6・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §4.1 | asof 2026-11-09：「家屋敷」を含む条（本則・原始附則）は ['main:20_3', 'main:20_4', 'main:24', 'main:294', 'main:317_2']、改正附則に 0 | OK | ['main:20_3', 'main:20_4', 'main:24', 'main:294', 'main:317_2'] 改正附則=[] |
| V1-31 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.8 | asof 2026-11-09：「家屋敷とは」「家屋敷をいう」はない | OK | [] |
| V1-30 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.8・§1.6・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §4.1 | asof 2026-11-09：「第二百九十四条第一項第二号」を含む条（本則・原始附則）は ['main:17_2', 'main:17_2_2', 'main:17_4', 'main:41', 'main:317_2', 'main:739_2', 'main:739_5']、改正附則に 0 | OK | ['main:17_2', 'main:17_2_2', 'main:17_4', 'main:41', 'main:317_2', 'main:739_2', 'main:739_5'] 改正附則=[] |
| V1-30 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.8・§1.6・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §4.1 | asof 2027-01-01：「家屋敷」を含む条（本則・原始附則）は ['main:20_3', 'main:20_4', 'main:24', 'main:294', 'main:317_2']、改正附則に 0 | OK | ['main:20_3', 'main:20_4', 'main:24', 'main:294', 'main:317_2'] 改正附則=[] |
| V1-31 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.8 | asof 2027-01-01：「家屋敷とは」「家屋敷をいう」はない | OK | [] |
| V1-30 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.8・§1.6・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §4.1 | asof 2027-01-01：「第二百九十四条第一項第二号」を含む条（本則・原始附則）は ['main:17_2', 'main:17_2_2', 'main:17_4', 'main:41', 'main:317_2', 'main:739_2', 'main:739_5']、改正附則に 0 | OK | ['main:17_2', 'main:17_2_2', 'main:17_4', 'main:41', 'main:317_2', 'main:739_2', 'main:739_5'] 改正附則=[] |
| V1-30 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.8・§1.6・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §4.1 | asof 2028-01-01：「家屋敷」を含む条（本則・原始附則）は ['main:20_3', 'main:20_4', 'main:24', 'main:294', 'main:317_2']、改正附則に 0 | OK | ['main:20_3', 'main:20_4', 'main:24', 'main:294', 'main:317_2'] 改正附則=[] |
| V1-31 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.8 | asof 2028-01-01：「家屋敷とは」「家屋敷をいう」はない | OK | [] |
| V1-30 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.8・§1.6・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §4.1 | asof 2028-01-01：「第二百九十四条第一項第二号」を含む条（本則・原始附則）は ['main:17_2', 'main:17_2_2', 'main:17_4', 'main:41', 'main:317_2', 'main:739_2', 'main:739_5']、改正附則に 0 | OK | ['main:17_2', 'main:17_2_2', 'main:17_4', 'main:41', 'main:317_2', 'main:739_2', 'main:739_5'] 改正附則=[] |
| V1-32 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.8 | chiho-rei asof 2026-11-09：「家屋敷」は 0（本則・原始附則・改正附則） | OK | [] [] |
| V1-32 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.8 | chiho-rei asof 2027-01-01：「家屋敷」は 0（本則・原始附則・改正附則） | OK | [] [] |
| V1-32 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.8 | chiho-kisoku asof 2026-11-09：「家屋敷」は 0（本則・原始附則・改正附則） | OK | [] [] |
| V1-32 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.8 | chiho-kisoku asof 2027-01-01：「家屋敷」は 0（本則・原始附則・改正附則） | OK | [] [] |
| V2-01 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.1 | 第314条の9第1項（確定申告書に記載・3/5・第314条の3及び前三条の後） | OK | chiho@2025-01-01 main:314_9 第1項 |
| V2-01 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.1 | 第314条の9第1項（確定申告書に記載・3/5・第314条の3及び前三条の後） | OK | chiho@2026-01-01 main:314_9 第1項 |
| V2-01 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.1 | 第314条の9第1項（確定申告書に記載・3/5・第314条の3及び前三条の後） | OK | chiho@2026-04-01 main:314_9 第1項 |
| V2-01 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.1 | 第314条の9第1項（確定申告書に記載・3/5・第314条の3及び前三条の後） | OK | chiho@2026-11-09 main:314_9 第1項 |
| V2-01 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.1 | 第314条の9第1項（確定申告書に記載・3/5・第314条の3及び前三条の後） | OK | chiho@2027-01-01 main:314_9 第1項 |
| V2-01 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.1 | 第314条の9第1項（確定申告書に記載・3/5・第314条の3及び前三条の後） | OK | chiho@2028-01-01 main:314_9 第1項 |
| V2-02 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.1 | 第314条の9第2項（還付・委託のみなし） | OK | chiho@2025-01-01 main:314_9 第2項 |
| V2-02 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.1 | 第314条の9第2項（還付・委託のみなし） | OK | chiho@2026-01-01 main:314_9 第2項 |
| V2-02 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.1 | 第314条の9第2項（還付・委託のみなし） | OK | chiho@2026-04-01 main:314_9 第2項 |
| V2-02 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.1 | 第314条の9第2項（還付・委託のみなし） | OK | chiho@2026-11-09 main:314_9 第2項 |
| V2-02 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.1 | 第314条の9第2項（還付・委託のみなし） | OK | chiho@2027-01-01 main:314_9 第2項 |
| V2-02 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.1 | 第314条の9第2項（還付・委託のみなし） | OK | chiho@2028-01-01 main:314_9 第2項 |
| V2-03 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.1 | 第314条の9第3項（道府県民税分も市町村が扱う） | OK | chiho@2025-01-01 main:314_9 第3項 |
| V2-03 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.1 | 第314条の9第3項（道府県民税分も市町村が扱う） | OK | chiho@2026-01-01 main:314_9 第3項 |
| V2-03 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.1 | 第314条の9第3項（道府県民税分も市町村が扱う） | OK | chiho@2026-04-01 main:314_9 第3項 |
| V2-03 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.1 | 第314条の9第3項（道府県民税分も市町村が扱う） | OK | chiho@2026-11-09 main:314_9 第3項 |
| V2-03 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.1 | 第314条の9第3項（道府県民税分も市町村が扱う） | OK | chiho@2027-01-01 main:314_9 第3項 |
| V2-03 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.1 | 第314条の9第3項（道府県民税分も市町村が扱う） | OK | chiho@2028-01-01 main:314_9 第3項 |
| V2-04 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.1 | 第37条の4（2/5・第35条及び前三条の後） | OK | chiho@2025-01-01 main:37_4 第1項 |
| V2-04 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.1 | 第37条の4（2/5・第35条及び前三条の後） | OK | chiho@2026-01-01 main:37_4 第1項 |
| V2-04 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.1 | 第37条の4（2/5・第35条及び前三条の後） | OK | chiho@2026-04-01 main:37_4 第1項 |
| V2-04 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.1 | 第37条の4（2/5・第35条及び前三条の後） | OK | chiho@2026-11-09 main:37_4 第1項 |
| V2-04 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.1 | 第37条の4（2/5・第35条及び前三条の後） | OK | chiho@2027-01-01 main:37_4 第1項 |
| V2-04 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.1 | 第37条の4（2/5・第35条及び前三条の後） | OK | chiho@2028-01-01 main:37_4 第1項 |
| V2-05 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.1 | asof 2025-01-01：第37条の4 に第2項はない | OK |  |
| V2-05 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.1 | asof 2026-01-01：第37条の4 に第2項はない | OK |  |
| V2-05 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.1 | asof 2026-04-01：第37条の4 に第2項はない | OK |  |
| V2-05 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.1 | asof 2026-11-09：第37条の4 に第2項はない | OK |  |
| V2-05 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.1 | asof 2027-01-01：第37条の4 に第2項はない | OK |  |
| V2-05 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.1 | asof 2028-01-01：第37条の4 に第2項はない | OK |  |
| V2-06 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.2 | 第71条の27第1項 | OK | chiho@2026-11-09 main:71_27 第1項 |
| V2-07 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.2 | 第71条の28（百分の五） | OK | chiho@2025-01-01 main:71_28 第1項 |
| V2-07 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.2 | 第71条の28（百分の五） | OK | chiho@2026-01-01 main:71_28 第1項 |
| V2-07 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.2 | 第71条の28（百分の五） | OK | chiho@2026-04-01 main:71_28 第1項 |
| V2-07 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.2 | 第71条の28（百分の五） | OK | chiho@2026-11-09 main:71_28 第1項 |
| V2-07 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.2 | 第71条の28（百分の五） | OK | chiho@2027-01-01 main:71_28 第1項 |
| V2-07 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.2 | 第71条の28（百分の五） | OK | chiho@2028-01-01 main:71_28 第1項 |
| V2-08 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.2 | 第71条の49（百分の五） | OK | chiho@2025-01-01 main:71_49 第1項 |
| V2-08 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.2 | 第71条の49（百分の五） | OK | chiho@2026-01-01 main:71_49 第1項 |
| V2-08 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.2 | 第71条の49（百分の五） | OK | chiho@2026-04-01 main:71_49 第1項 |
| V2-08 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.2 | 第71条の49（百分の五） | OK | chiho@2026-11-09 main:71_49 第1項 |
| V2-08 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.2 | 第71条の49（百分の五） | OK | chiho@2027-01-01 main:71_49 第1項 |
| V2-08 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.2 | 第71条の49（百分の五） | OK | chiho@2028-01-01 main:71_49 第1項 |
| V2-09 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.2 | 第71条の31第1項（特別徴収義務者） | OK | chiho@2026-11-09 main:71_31 第1項 |
| V2-10 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.2 | 第313条第12項（ロを除く） | OK | chiho@2026-04-01 main:313 第12項 |
| V2-10 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.2 | 第313条第12項（ロを除く） | OK | chiho@2026-11-09 main:313 第12項 |
| V2-10 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.2 | 第313条第12項（ロを除く） | OK | chiho@2027-01-01 main:313 第12項 |
| V2-11 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.2 | 第313条第12項（2026-01-01 以前は括弧書きなし） | OK | chiho@2025-01-01 main:313 第12項 |
| V2-11 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.2 | 第313条第12項（2026-01-01 以前は括弧書きなし） | OK | chiho@2026-01-01 main:313 第12項 |
| V2-12 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.2 | 第313条第13項 | OK | chiho@2026-11-09 main:313 第13項 |
| V2-13 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.2 | 第313条第15項 | OK | chiho@2026-11-09 main:313 第15項 |
| V2-14 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.2 | 施行規則第1条の12の2第1項第1号 | OK | chiho-kisoku@2026-01-01 main:1_12_2 第1項 第1号 |
| V2-14 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.2 | 施行規則第1条の12の2第1項第1号 | OK | chiho-kisoku@2026-11-09 main:1_12_2 第1項 第1号 |
| V2-14 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.2 | 施行規則第1条の12の2第1項第1号 | OK | chiho-kisoku@2027-01-01 main:1_12_2 第1項 第1号 |
| V2-15 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.2 | 施行規則第1条の12の2第2項 | OK | chiho-kisoku@2026-11-09 main:1_12_2 第2項 |
| V2-16 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.2 | 施行規則第1条の12の3第1項第1号（株式等譲渡所得割額） | OK | chiho-kisoku@2026-11-09 main:1_12_3 第1項 第1号 |
| V2-17 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.2 | 施行規則第2条の3第2項（付記事項） | OK | chiho-kisoku@2026-11-09 main:2_3 第2項 |
| V2-18 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.3 | 施行令第48条の9の3第1項 | OK | chiho-rei@2026-01-01 main:48_9_3 第1項 |
| V2-18 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.3 | 施行令第48条の9の3第1項 | OK | chiho-rei@2026-11-09 main:48_9_3 第1項 |
| V2-18 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.3 | 施行令第48条の9の3第1項 | OK | chiho-rei@2027-01-01 main:48_9_3 第1項 |
| V2-19 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.3 | 施行令第48条の9の3第3項（追徴→その他の未納） | OK | chiho-rei@2026-11-09 main:48_9_3 第3項 |
| V2-20 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.3 | 施行令第48条の9の4第1項（還付） | OK | chiho-rei@2026-11-09 main:48_9_4 第1項 |
| V2-21 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.3 | 施行令第48条の9の5第1項（7.3%・同年度分への充当は加算なし） | OK | chiho-rei@2026-11-09 main:48_9_5 第1項 |
| V2-22 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.3 | 施行令第48条の9の5第2項（第20条の4の2第2項・第5項の準用） | OK | chiho-rei@2026-11-09 main:48_9_5 第2項 |
| V2-23 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.3・§4-7（未確認だった点） | 施行令附則第3条の2第1項は第48条の9の5第1項の年7.3% を還付加算金特例基準割合に替える | OK | chiho-rei@2026-11-09 orig:3_2 第1項 |
| V2-23 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.3・§4-7（未確認だった点） | 施行令附則第3条の2第1項は第48条の9の5第1項の年7.3% を還付加算金特例基準割合に替える | OK | chiho-rei@2027-01-01 orig:3_2 第1項 |
| V2-24 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.4 | 附則第5条の4第6項（第314条の9 の前三条の読替え） | OK | chiho@2026-04-01 orig:5_4 第6項 |
| V2-24 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.4 | 附則第5条の4第6項（第314条の9 の前三条の読替え） | OK | chiho@2026-11-09 orig:5_4 第6項 |
| V2-24 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.4 | 附則第5条の4第6項（第314条の9 の前三条の読替え） | OK | chiho@2027-01-01 orig:5_4 第6項 |
| V2-25 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.4 | 附則第5条の4第2項（第37条の3・第37条の4 の読替え） | OK | chiho@2026-11-09 orig:5_4 第2項 |
| V2-26 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §4-8（未確認だった点）・docs/hypotheses/20261109_round3_juminzei-extra-model.md 未決4 | asof 2026-04-01：第314条の9第1項の「前三条」を読み替える原始附則は 3_3-6・5-4・5_4-6・6-6 だけで、附則第7条の2（申告特例控除）に第314条の9 の語はない | OK | ['3_3-6', '5-4', '5_4-6', '6-6'] 7_2に314条の9=False |
| V2-26 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §4-8（未確認だった点）・docs/hypotheses/20261109_round3_juminzei-extra-model.md 未決4 | asof 2026-11-09：第314条の9第1項の「前三条」を読み替える原始附則は 3_3-6・5-4・5_4-6・6-6 だけで、附則第7条の2（申告特例控除）に第314条の9 の語はない | OK | ['3_3-6', '5-4', '5_4-6', '6-6'] 7_2に314条の9=False |
| V2-26 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §4-8（未確認だった点）・docs/hypotheses/20261109_round3_juminzei-extra-model.md 未決4 | asof 2027-01-01：第314条の9第1項の「前三条」を読み替える原始附則は 3_3-6・5-4・5_4-6・6-6 だけで、附則第7条の2（申告特例控除）に第314条の9 の語はない | OK | ['3_3-6', '5-4', '5_4-6', '6-6'] 7_2に314条の9=False |
| V2-27 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §4-8（未確認だった点） | 附則第7条の2第4項：申告特例控除は第314条の7第1項・第11項の後の所得割から | OK | chiho@2026-11-09 orig:7_2 第4項 |
| V2-30 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.5 | 第23条第1項第15号（イ・ロ・ハ） | OK | chiho@2026-04-01 main:23 第1項 第15号 |
| V2-30 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.5 | 第23条第1項第15号（イ・ロ・ハ） | OK | chiho@2026-11-09 main:23 第1項 第15号 |
| V2-30 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.5 | 第23条第1項第15号（イ・ロ・ハ） | OK | chiho@2027-01-01 main:23 第1項 第15号 |
| V2-30 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.5 | 第23条第1項第15号（イ・ロ・ハ） | OK | chiho@2028-01-01 main:23 第1項 第15号 |
| V2-31 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.5 | 第23条第1項第15号（2026-01-01 以前はロなし） | OK | chiho@2025-01-01 main:23 第1項 第15号 |
| V2-31 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.5 | 第23条第1項第15号（2026-01-01 以前はロなし） | OK | chiho@2026-01-01 main:23 第1項 第15号 |
| V2-32 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.5 | 施行令第7条の3 | OK | chiho-rei@2026-11-09 main:7_3 第1項 |
| V2-32 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.5 | 施行令第7条の3 | OK | chiho-rei@2027-01-01 main:7_3 第1項 |
| V2-33 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.5 | asof 2026-01-01 の施行令第7条の3 は「見出しのない空の条」 | **NG** | 取得した本文='削除'：見出しはないが本文は「削除」（空ではない）→ 文言を訂正 |
| V2-34 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.5 | 措法第9条の3第1号（大口株主等以外） | OK | sochi@2025-01-01 main:9_3 第1項 第1号 |
| V2-34 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.5 | 措法第9条の3第1号（大口株主等以外） | OK | sochi@2025-06-30 main:9_3 第1項 第1号 |
| V2-34 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.5 | 措法第9条の3第1号（大口株主等以外） | OK | sochi@2025-12-31 main:9_3 第1項 第1号 |
| V2-34 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.5 | 措法第9条の3第1号（大口株主等以外） | OK | sochi@2026-11-09 main:9_3 第1項 第1号 |
| V2-35 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.5・§4-6（未確認だった点） | 措法第8条の4第1項第1号の括弧書き（同族会社と合算して 3% 以上） | OK | sochi@2025-01-01 main:8_4 第1項 第1号 |
| V2-35 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.5・§4-6（未確認だった点） | 措法第8条の4第1項第1号の括弧書き（同族会社と合算して 3% 以上） | OK | sochi@2025-06-30 main:8_4 第1項 第1号 |
| V2-35 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.5・§4-6（未確認だった点） | 措法第8条の4第1項第1号の括弧書き（同族会社と合算して 3% 以上） | OK | sochi@2025-12-31 main:8_4 第1項 第1号 |
| V2-35 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.5・§4-6（未確認だった点） | 措法第8条の4第1項第1号の括弧書き（同族会社と合算して 3% 以上） | OK | sochi@2026-11-09 main:8_4 第1項 第1号 |
| V2-36 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §4-6（未確認だった点） | 措法第8条の4第1項第1号の文言は asof 2025-01-01・2025-06-30・2025-12-31・2026-11-09 で同じ | OK | {'2025-01-01': '961aac15d75b', '2025-06-30': '961aac15d75b', '2025-12-31': '961aac15d75b', '2026-11-09': '961aac15d75b'} |
| V2-37 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.5 | 令和8年法律第2号 附則第1条本文（令和8年4月1日施行） | OK | chiho@2030-01-01 令和八年三月三一日法律第二号:1 第1項 |
| V2-38 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.5・§3.4 | 令和8年法律第2号 附則第3条第1項（道府県民税：令和8年度以後） | OK | 別段の定めがあるものを除き、第一条の規定による改正後の地方税法（以下「新法」という。）の規定中個人の道府県民税に関する部分（地方税法第四十一条第四項において準用する新法第三百三十二条の二、新法第七十一条の二十の二、第七十一条の四十一の二、第七十一条の六十一の二及び第七百三十九条の六の規定を除く。）は、令和八年度以後の年度分の個人の道府県民税について適用し、令和七年度分までの個人の道府県民税について |
| V2-39 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.5・§3.4 | 令和8年法律第2号 附則第11条第1項（市町村民税：令和8年度以後） | OK | 別段の定めがあるものを除き、新法の規定中個人の市町村民税に関する部分（新法第三百三十二条の二の規定を除く。）は、令和八年度以後の年度分の個人の市町村民税について適用し、令和七年度分までの個人の市町村民税については、なお従前の例による。 |
| V2-40 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.5 | 令和8年法律第2号 附則第3条第3項（施行日以後に支払を受けるべき特定配当等） | OK | ３新法の規定中新法第二十三条第一項第十五号に規定する特定配当等に係る道府県民税に関する部分は、この法律の施行の日（以下「施行日」という。）以後に支払を受けるべき同号に規定する特定配当等について適用し、施行日前に支払を受けるべき旧法第二十三条第一項第十五号に規定する特定配当等については、なお従前の例による。 |
| V2-41 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.5 | 令和8年法律第2号の附則で「特定配当等」を含む項は附則第3条第3項だけ | — | e-Gov に収録された附則は第1条〜第22条（22 条）で、その中では ['3-3']。本文 PDF の附則第28条・第29条（他の法律の改正規定）にも「特定配当等」がある（V5-47）→ 「e-Gov 収録分（附則第1条〜第22条）では」と限定する |
| V2-42 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.5 | 令和4年法律第1号 附則第1条第5号（第313条第13項・第314条の9第1項・第317条の2第1項ただし書などは令和6年1月1日） | OK | この法律は、令和四年四月一日から施行する。ただし、次の各号に掲げる規定は、当該各号に定める日から施行する。一第七条の規定公布の日二第一条中地方税法第二十条の九の三第三項及び第七十二条の四十八の二第五項の改正規定、第四条中地方税法等の一部を改正する法律（令和二年法律第五号）附則第五条第三項の規定によりなおその効力を有するものとされた同法附則第一条第五号に掲げる規定による改正前の地方税法第二十条の九の |
| V2-43 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.5 | 令和4年法律第1号 附則第11条第1項（六年新法は令和6年度以後） | OK | 六年新法の規定中個人の市町村民税に関する部分は、令和六年度以後の年度分の個人の市町村民税について適用し、令和五年度分までの個人の市町村民税については、なお従前の例による。 |
| V3-01 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.1 | asof 2026-01-01：附則第5条の4 は旧制度（平成二十年度から平成二十八年度まで・居住年 平成十一年から平成十八年まで） | OK |  |
| V3-02 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.1 | asof 2026-01-01：附則第5条の4の2（平成十一年から平成十八年まで又は平成二十一年から令和七年まで）に基礎控除の差の加算・申告書の定めはない | OK |  |
| V3-03 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.1 | asof 2026-04-01：附則第5条の4の2 はない | OK |  |
| V3-03 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.1 | asof 2026-11-09：附則第5条の4の2 はない | OK |  |
| V3-03 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.1 | asof 2027-01-01：附則第5条の4の2 はない | OK |  |
| V3-04 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.2 | 附則第5条の4第5項（年度・居住年・3/5（4/5）・基・加算・3%（4%）・58,500円（78,000円）） | OK | chiho@2026-04-01 orig:5_4 第5項 |
| V3-04 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.2 | 附則第5条の4第5項（年度・居住年・3/5（4/5）・基・加算・3%（4%）・58,500円（78,000円）） | OK | chiho@2026-11-09 orig:5_4 第5項 |
| V3-05 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.2 | 附則第5条の4第5項第1号 | OK | chiho@2026-11-09 orig:5_4 第5項 第1号 |
| V3-06 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.2 | 附則第5条の4第5項第2号 | OK | chiho@2026-11-09 orig:5_4 第5項 第2号 |
| V3-07 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.2 | 附則第5条の4第1項（2/5（1/5）・第35条及び第37条の後・2%（1%）・39,000円（19,500円）） | OK | chiho@2026-11-09 orig:5_4 第1項 |
| V3-08 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.2 | 附則第5条の4第7項（平成26年〜令和3年・特定取得（第5項）・特別特定取得（第16項）：4.2%・5.6%・81,900円・109,200円） | OK | chiho@2026-11-09 orig:5_4 第7項 |
| V3-09 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.2 | 附則第5条の4第3項（2.8%・1.4%・54,600円・27,300円） | OK | chiho@2026-11-09 orig:5_4 第3項 |
| V3-10 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.2 | 附則第5条の4第4項 | OK | chiho@2026-11-09 orig:5_4 第4項 |
| V3-11 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.2 | 附則第5条の4第8項 | OK | chiho@2026-11-09 orig:5_4 第8項 |
| V3-12 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.2 | 附則第5条の4 に還付・申告書・「限度とする」の文言はない | OK | chiho@2026-04-01 orig:5_4 |
| V3-12 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.2 | 附則第5条の4 に還付・申告書・「限度とする」の文言はない | OK | chiho@2026-11-09 orig:5_4 |
| V3-12 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.2 | 附則第5条の4 に還付・申告書・「限度とする」の文言はない | OK | chiho@2027-01-01 orig:5_4 |
| V3-13 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.2・§4-10・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §4.1 | chiho-rei asof 2026-11-09：「住宅借入金」は本則・原始附則・改正附則に 0 | OK | 本則・原始附則=[] 改正附則=[] |
| V3-13 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.2・§4-10・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §4.1 | chiho-rei asof 2027-01-01：「住宅借入金」は本則・原始附則・改正附則に 0 | OK | 本則・原始附則=[] 改正附則=[] |
| V3-13 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.2・§4-10・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §4.1 | chiho-kisoku asof 2026-11-09：「住宅借入金等特別税額控除」は本則・原始附則・改正附則に 0 | OK | 本則・原始附則=[] 改正附則=[] |
| V3-13 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.2・§4-10・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §4.1 | chiho-kisoku asof 2027-01-01：「住宅借入金等特別税額控除」は本則・原始附則・改正附則に 0 | OK | 本則・原始附則=[] 改正附則=[] |
| V3-14 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.3 | asof 2027-01-01 の附則第5条の4第5項（令和二十五年度・令和十二年・第二項から第十八項まで・平成19/20年の括弧書きなし・加算は平成二十八年から令和七年まで） | OK | chiho@2027-01-01 orig:5_4 第5項 |
| V3-14 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.3 | asof 2027-01-01 の附則第5条の4第5項（令和二十五年度・令和十二年・第二項から第十八項まで・平成19/20年の括弧書きなし・加算は平成二十八年から令和七年まで） | OK | chiho@2028-01-01 orig:5_4 第5項 |
| V3-15 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.3 | asof 2027-01-01 の附則第5条の4第7項（特別特定取得は同条第十二項） | OK | chiho@2027-01-01 orig:5_4 第7項 |
| V3-16 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.3 | 令和8年法律第2号 附則第1条第2号（附則第5条の4の2第1項・第5項の「令和二十年度」→「令和二十五年度」、「令和七年」→「令和十二年」などは令和9年1月1日） | OK | この法律は、令和八年四月一日から施行する。ただし、次の各号に掲げる規定は、当該各号に定める日から施行する。一第一条中地方税法第三十七条の二第二項の改正規定（同項第五号中「第五項」を「第四項」に改める部分を除く。）、同条第三項の改正規定、同法第三百十四条の七第二項の改正規定（同項第五号中「第五項」を「第四項」に改める部分を除く。）及び同条第三項の改正規定並びに附則第三条第五項及び第六項並びに第十一条 |
| V3-17 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.4 | 令和8年法律第2号 附則第11条第10項（令和8年1月1日以後の居住に九年一月新法、前は従前の例） | OK | １０九年一月新法附則第五条の四第五項から第八項までの規定は、市町村民税の所得割の納税義務者が令和八年一月一日以後に新租税特別措置法第四十一条第一項に規定する居住用家屋（同条第十六項の規定により同条第一項に規定する居住用家屋とみなされる同条第十六項に規定する特例居住用家屋を含む。）若しくは既存住宅（同条第十七項の規定により同条第一項に規定する既存住宅とみなされる同条第十七項に規定する特例既存住宅及び |
| V3-18 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.4 | 令和8年法律第2号 附則第3条第12項（道府県民税） | OK | １２九年一月新法附則第五条の四第一項から第四項までの規定は、道府県民税の所得割の納税義務者が令和八年一月一日以後に所得税法等の一部を改正する法律（令和八年法律第十二号。以下この項及び第十八項並びに附則第十一条第十五項において「所得税法等改正法」という。）第七条の規定による改正後の租税特別措置法（昭和三十二年法律第二十六号。次条並びに附則第五条及び第十一条から第十三条までにおいて「新租税特別措置法」 |
| V3-19 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.4 | 令和4年法律第1号 附則第10条第3項（令和4年1月1日以後の居住に新法、前は従前の例） | OK | ３新法附則第五条の四の二第五項から第八項までの規定は、市町村民税の所得割の納税義務者が令和四年一月一日以後に新租税特別措置法第四十一条第一項に規定する居住用家屋若しくは既存住宅又は増改築等をした家屋（当該増改築等に係る部分に限る。第七項において同じ。）を同条第一項の定めるところによりその者の居住の用に供する場合について適用し、市町村民税の所得割の納税義務者が同日前に旧租税特別措置法第四十一条第一項 |
| V3-20 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.4 | 令和4年法律第1号 附則第3条第3項（道府県民税） | OK | ３新法附則第五条の四の二第一項から第四項までの規定は、道府県民税の所得割の納税義務者が令和四年一月一日以後に所得税法等の一部を改正する法律（令和四年法律第四号。以下この項及び第五項において「所得税法等改正法」という。）第十一条の規定による改正後の租税特別措置法（昭和三十二年法律第二十六号。以下「新租税特別措置法」という。）第四十一条第一項に規定する居住用家屋若しくは既存住宅又は増改築等をした家屋（ |
| V3-21 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.4 | 令和4年法律第1号 附則第10条第6項（旧法附則第61条第3項による読替えの控除は従前の例） | OK | ６市町村民税の所得割の納税義務者が令和四年一月一日前に旧租税特別措置法第四十一条第一項に規定する居住用家屋若しくは既存住宅若しくは増改築等をした家屋を同項の定めるところによりその者の居住の用に供した場合又は同日前に旧震災特例法第十三条の二第一項に規定する居住用家屋若しくは既存住宅若しくは増改築等をした家屋若しくは認定住宅を同項の定めるところによりその者の居住の用に供した場合における旧法附則第六十一 |
| V3-22 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.4（追加） | 令和4年法律第1号 附則第1条第3号：附則第5条の4の2第1項・第5項の改正規定と附則第10条第1項〜第3項は令和5年1月1日施行 | OK | この法律は、令和四年四月一日から施行する。ただし、次の各号に掲げる規定は、当該各号に定める日から施行する。一第七条の規定公布の日二第一条中地方税法第二十条の九の三第三項及び第七十二条の四十八の二第五項の改正規定、第四条中地方税法等の一部を改正する法律（令和二年法律第五号）附則第五条第三項の規定によりなおその効力を有するものとされた同法附則第一条第五号に掲げる規定による改正前の地方税法第二十条の九の |
| V3-23 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.4・§4-2 | e-Gov の地方税法（asof 2030-01-01）の改正附則で令和4年法律第1号を引く項は、同法自身の附則のほかにない | OK | [] |
| V3-24 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.4（追加） | e-Gov の版は改正附則が後の法律で改められたことを反映する：平成31年法律第2号 附則第11条・第18条の第5項〜第7項（令和8年法律第2号 第37条で削る）は 2026-01-01 にあり、2026-04-01 以後にない | OK | {'2026-01-01': ['11-5', '11-6', '11-7', '18-5', '18-6', '18-7'], '2026-04-01': [], '2026-11-09': [], '2030-01-01': []} |
| V3-25 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.4（追加） | 同じ e-Gov の asof 2030-01-01 で、令和4年法律第1号 附則第10条第3項は制定時の文言のまま（V3-19） | OK |  |
| V3-26 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.4（追加）・docs/hypotheses/20261109_round3_juminzei-extra-model.md H3-2 | asof 2021-12-31 の附則第5条の4の2第5項：居住年 平成二十一年から令和三年まで・令和十五年度まで・3%・58,500円・基礎控除の加算なし | OK | chiho@2021-12-31 orig:5_4_2 第5項 |
| V3-27 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.4（追加） | asof 2021-12-31 の附則第5条の4の2第7項：平成二十六年から令和三年まで・4.2%・81,900円 | OK | chiho@2021-12-31 orig:5_4_2 第7項 |
| V3-26 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.4（追加）・docs/hypotheses/20261109_round3_juminzei-extra-model.md H3-2 | asof 2022-04-01 の附則第5条の4の2第5項：居住年 平成二十一年から令和三年まで・令和十五年度まで・3%・58,500円・基礎控除の加算なし | OK | chiho@2022-04-01 orig:5_4_2 第5項 |
| V3-27 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.4（追加） | asof 2022-04-01 の附則第5条の4の2第7項：平成二十六年から令和三年まで・4.2%・81,900円 | OK | chiho@2022-04-01 orig:5_4_2 第7項 |
| V3-26 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.4（追加）・docs/hypotheses/20261109_round3_juminzei-extra-model.md H3-2 | asof 2023-01-01 の附則第5条の4の2第5項：居住年 平成二十一年から令和七年まで・令和二十年度まで・3%・58,500円・基礎控除の加算なし | OK | chiho@2023-01-01 orig:5_4_2 第5項 |
| V3-27 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.4（追加） | asof 2023-01-01 の附則第5条の4の2第7項：平成二十六年から令和三年まで・4.2%・81,900円 | OK | chiho@2023-01-01 orig:5_4_2 第7項 |
| V3-30 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.5 | 附則第45条第4項（市町村民税・震災特例法第13条第1項） | OK | chiho@2026-11-09 orig:45 第4項 |
| V3-31 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.5 | 附則第45条第6項（平成26年〜令和3年、平成26年は4月1日以後、4.2%・81,900円） | OK | chiho@2026-11-09 orig:45 第6項 |
| V3-32 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.5 | 附則第45条第3項（道府県民税） | OK | chiho@2026-11-09 orig:45 第3項 |
| V3-33 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.5 | 附則第61条第2項（「令和三年」→「令和四年」） | OK | chiho@2026-11-09 orig:61 第2項 |
| V3-34 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.5 | 附則第61条第1項 | OK | chiho@2026-11-09 orig:61 第1項 |
| V3-35 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.2 | 所得税法第86条第2項（基礎控除の名） | OK | shotoku@2026-01-01 main:86 第2項 |
| V4-tbl | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §3.2 | main:294 の6版の並び AABBBB | OK | AABBBB |
| V4-tbl | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §3.2 | main:24 の6版の並び AABBBB | OK | AABBBB |
| V4-tbl | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §3.2 | main:295 の6版の並び AAAAAA | OK | AAAAAA |
| V4-tbl | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §3.2 | main:24_5 の6版の並び AAAAAA | OK | AAAAAA |
| V4-tbl | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §3.2 | main:318 の6版の並び AAAAAA | OK | AAAAAA |
| V4-tbl | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §3.2 | main:39 の6版の並び AAAAAA | OK | AAAAAA |
| V4-tbl | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §3.2 | main:320 の6版の並び AAAAAA | OK | AAAAAA |
| V4-tbl | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §3.2 | main:737 の6版の並び AAAAAA | OK | AAAAAA |
| V4-tbl | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §3.2 | main:310 の6版の並び AAAAAA | OK | AAAAAA |
| V4-tbl | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §3.2 | main:317_2 の6版の並び ABBBBB | OK | ABBBBB |
| V4-tbl | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §3.2 | main:314_9 の6版の並び AAAAAA | OK | AAAAAA |
| V4-tbl | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §3.2 | main:37_4 の6版の並び AAAAAA | OK | AAAAAA |
| V4-tbl | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §3.2 | main:71_28 の6版の並び AAAAAA | OK | AAAAAA |
| V4-tbl | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §3.2 | main:71_49 の6版の並び AAAAAA | OK | AAAAAA |
| V4-tbl | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §3.2 | main:313 の6版の並び AABBBB | OK | AABBBB |
| V4-tbl | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §3.2 | main:23 の6版の並び ABCDEF | OK | ABCDEF |
| V4-tbl | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §3.2 | orig:5_4 の6版の並び ABCCDD | OK | ABCCDD |
| V4-tbl | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §3.2 | orig:45 の6版の並び AABBCC | OK | AABBCC |
| V4-tbl | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §3.2 | orig:61 の6版の並び AABBBB | OK | AABBBB |
| V4-tbl2 | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §3.2・docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.3 | chiho-rei:48_9_3 は 2026-01-01・2026-11-09・2027-01-01 で同じ | OK | AAA |
| V4-tbl2 | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §3.2・docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.3 | chiho-rei:48_9_4 は 2026-01-01・2026-11-09・2027-01-01 で同じ | OK | AAA |
| V4-tbl2 | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §3.2・docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.3 | chiho-rei:48_9_5 は 2026-01-01・2026-11-09・2027-01-01 で同じ | OK | AAA |
| V4-tbl2 | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §3.2・docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.3 | chiho-kisoku:1_12_2 は 2026-01-01・2026-11-09・2027-01-01 で同じ | OK | AAA |
| V4-tbl2 | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §3.2・docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.3 | chiho-kisoku:1_12_3 は 2026-01-01・2026-11-09・2027-01-01 で同じ | OK | AAA |
| V4-diff | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.1・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §3.2 | 第294条の 2026-01-01→2026-04-01 の違いはマンション関係の組合の名前だけ | OK | [('建替', '再生'), ('敷地', '等'), ('', '却組合、マンション除')] |
| V4-diff | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §1.1・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §3.2 | 第24条の 2026-01-01→2026-04-01 の違いはマンション関係の組合の名前だけ | OK | [('建替', '再生'), ('敷地', '等'), ('', '却組合、マンション除')] |
| V4-amend | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §4.2 | 令和の改正附則で担当の正規表現（_laws.py の AMEND_RE）に当たる項は 47 件、そのうち「四十八万円」は 0 | OK | 件数=47、四十八万円=0 |
| V4-amend48 | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §4.2（範囲を広げた） | 平成を含む全部の改正附則で「四十八万円」を含む項は 0 | OK | [] |
| V5-meta | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §2.3 | shichoson：頁数・フォント（情報） | — | 頁=142 フォント=['F1:WinAnsiEncoding', 'F2:Identity-H+ToUnicode', 'F3:Identity-H+ToUnicode'] SHA-256=107ba94cd6bd4b5e Last-Modified=Thu, 07 May 2026 04:14:33 GMT |
| V5-meta | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §2.3 | dofuken：頁数・フォント（情報） | — | 頁=199 フォント=['F1:Identity-H+ToUnicode', 'F2:Identity-H+ToUnicode', 'F3:WinAnsiEncoding'] SHA-256=b8c40110f3a48e8d Last-Modified=Fri, 14 Aug 2026 04:51:28 GMT |
| V5-meta | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §2.3 | kaisei_tsuchi：頁数・フォント（情報） | — | 頁=47 フォント=['C2_0:Identity-H+ToUnicode', 'TT0:WinAnsiEncoding+ToUnicode', 'TT1:WinAnsiEncoding+ToUnicode'] SHA-256=321af651108b58ab Last-Modified=Thu, 16 Apr 2026 09:11:20 GMT |
| V5-meta | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §2.3 | r8_houritsu：頁数・フォント（情報） | — | 頁=226 フォント=['TT1:Identity-H+ToUnicode', 'TT2:Identity-V+ToUnicode'] SHA-256=0282d962b36395be Last-Modified=Tue, 31 Mar 2026 20:35:29 GMT |
| V5-fonts | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §2.3 | shichoson：使われているフォントは {'F1': 'WinAnsiEncoding', 'F2': 'Identity-H', 'F3': 'Identity-H'} | OK | 今回：{'F1': 'WinAnsiEncoding', 'F2': 'Identity-H', 'F3': 'Identity-H'}（使われた頁の数 {'F1': 142, 'F2': 142, 'F3': 120}） |
| V5-fonts | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §2.3 | dofuken：使われているフォントは {'F1': 'Identity-H', 'F2': 'Identity-H'} | **NG** | 今回：{'F1': 'Identity-H', 'F2': 'Identity-H', 'F3': 'WinAnsiEncoding'}（使われた頁の数 {'F1': 199, 'F2': 168, 'F3': 49}） |
| V5-fonts | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §2.3 | r8_houritsu：使われているフォントは {'TT1': 'Identity-H', 'TT2': 'Identity-V'} | OK | 今回：{'TT1': 'Identity-H', 'TT2': 'Identity-V'}（使われた頁の数 {'TT1': 226, 'TT2': 226}） |
| V5-pages | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §1・§2.1・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §2.3 | 頁数：取扱通知（市町村税）142・（道府県税）199・総税企第44号 47・令和8年法律第2号 226 | OK | [142, 199, 47, 226] |
| V5-01 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §1 | p.1 の改正の列の最後は令和8年4月1日総税市第25号（期待 p.[1]） | OK | 見つかった頁=[1] 抜粋=７年７月３日総税市第８１号令和７年９月２９日総税市第１１３号令和８年４月１日総税市第２５号（目次）第１章一般的事項第１節通則第２節納税義務の承継第３節連帯納税 |
| V5-02 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §1・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §4.4 | 取扱通知（市町村税）の「家屋敷」は p.31 の 1 回だけ | OK | 回数=1 |
| V5-03 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §1.1 | 4の3（非課税の措置は適用されない）（期待 p.[31]） | OK | 見つかった頁=[31] 抜粋=、法施行地に事務所、事業所又は家屋敷を有する場合においては、その所在する市町村において、均等割を課する。この場合においては、法第２９５条第１項の規定による非課税の措置は適用されないことに留意すること。（法２９４①Ⅱ）４の４前年中に所得税法（ |
| V5-04 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §1.1 | 5（法294③・④）（期待 p.[31]） | OK | 見つかった頁=[31] 抜粋=かかわらず、市町村民税を課することができないものであること。（法２９４③・④）(３)(１)及び(２)の取扱いについては、住民基本台帳法第３ |
| V5-05 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §1.1 | 6（１人１箇所）（期待 p.[31]） | OK | 見つかった頁=[31] 抜粋=この場合における住所とは、納税義務者本人の生活の本拠をいい、地方税法上その施行地を通じて１人１箇所に限られるものであること。住所の具体的な認定に当たっては、住民基本台帳法の施行に伴う |
| V5-06 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §1.1 | 6(1)（勤務日以外には家族のもと）（期待 p.[32]） | OK | 見つかった頁=[32] 抜粋=-32-確定困難な者で、勤務日以外には家族のもとにおいて生活をともにする者については、家族の居住地にあるものとする。(２)職業の関係上家族の居住地を離れて転々と居を移している |
| V5-07 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §1.1 | 6(2) ただし書（同一場所に1年以上）（期待 p.[32]） | OK | 見つかった頁=[32] 抜粋=ている者の住所は、家族の居住地にあるものとして取り扱うこと。ただし、同一場所に１年以上居住している場合においては、本人の住所は、当該場所にあるものとして取り扱うこと。(３)船舶に乗り組んでいる船員の住所については、航海と航海 |
| V5-07b | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §1.1 | 6(3) 船員（期待 p.[32]） | OK | 見つかった頁=[32] 抜粋=いては、本人の住所は、当該場所にあるものとして取り扱うこと。(３)船舶に乗り組んでいる船員の住所については、航海と航海の中間期間又は休暇等に際して妻子その他の家族のも |
| V5-07c | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §1.1 | 6(4) たまたま出国した者（期待 p.[32]） | OK | 見つかった頁=[32] 抜粋=ある主たる定けい港所在の市町村にあるものとして取り扱うこと。(４)法施行地に住所を有するかどうかは、実質的に判断すべきであるから、たまたま出国した者であっても、その者の出国の期間、目的、出国中の居住の状況等から単に旅行 |
| V5-07d | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §1.1 | 6(5) 公務員に所得税法第3条第1項は適用しない（期待 p.[32]） | OK | 見つかった頁=[32] 抜粋=しない期間についても国内に住所を有するものとみなすものとする所得税法第３条第１項の規定は、個人住民税については、適用されないこと。(６)自衛隊隊員の住所については次の取扱いによるものである |
| V5-07e | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §1.1 | 6(6) 自衛隊隊員（期待 p.[32]） | OK | 見つかった頁=[32] 抜粋=３条第１項の規定は、個人住民税については、適用されないこと。(６)自衛隊隊員の住所については次の取扱いによるものであること。ア自衛隊法（昭和２９年法律第１６５号）第５５条及び自衛隊法 |
| V5-08 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §1.1 | 第1章第1節6（事務所又は事業所）（期待 p.[6]） | OK | 見つかった頁=[6] 抜粋=とは、それが自己の所有に属するものであるか否かにかかわらず、事業の必要から設けられた人的及び物的設備であって、そこで継続して事業が行われる場所をいうものであること。この場合において事務所等において行われ |
| V5-09 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §1.1 | 第1章第1節6(2)（2、3か月程度の現場事務所）（期待 p.[6]） | OK | 見つかった頁=[6] 抜粋=ある程度の継続性をもったものであることを要するから、たまたま２、３か月程度の一時的な事業の用に供する目的で設けられる現場事務所、仮小屋等は事務所等の範囲に入らないものであること。７金融機関の指定市町村税は、会計管理者若しく |
| V5-10 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §1.1 | 32（同日の現況）（期待 p.[57]） | OK | 見つかった頁=[57] 抜粋=税に係る所得割を除く。）の賦課期日は１月１日とされているので納税義務の有無に関する事実の認定は、同日の現況においてこれを行うものであること。（法３１８）３３市町村は、個人の市町村民税を賦課し、及び徴収する場合にお |
| V5-11 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §1.1 | 33の2（合算額で計算）（期待 p.[58]） | OK | 見つかった頁=[58] 抜粋=又は法第３２８条の１２の規定による重加算金の計算については、個人の道府県民税及び個人の市町村民税の額の合算額によりこれらの規定を適用するものとする。３４市町村民税の所得割の延滞金の計算に当たってその計算の基 |
| V5-12 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §1.2 | 25の2(1)（5分の3）（期待 p.[50]） | OK | 見つかった頁=[50] 抜粋=において「株式等譲渡所得割額」という。）を課された場合には、当該配当割額又は当該株式等譲渡所得割額に５分の３を乗じて得た金額を、その者に係る所得割の額から控除するものであること。（法３１４の９①）(２)(１)により所得割の額から控除すべ |
| V5-12b | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §1.2 | 25の2 の書き出し（期待 p.[49]） | OK | 見つかった頁=[49] 抜粋=に、その翌年の１月１日に指定都市に住所を有した年があるとき。２５の２法第３１４条の９の規定の適用に当たっては、次の諸点に留意すること。(１)市町村は、所得割の納税義務者 |
| V5-13 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §1.2 | 25の2(2)（賦課決定後・納税通知書の前）（期待 p.[50]） | OK | 見つかった頁=[50] 抜粋=額（以下この項において「控除不足額」という。）があるときは、賦課決定後、納税通知書を発する前に、当該控除不足額のうち法第３１４条の９第２項後段に規定する還付をすべき金額（以下この項において「還付をすべき金額」という。）により同一 |
| V5-13b | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §1.2 | 25の2(2)（同一年度分）（期待 p.[50]） | OK | 見つかった頁=[50] 抜粋=すべき金額（以下この項において「還付をすべき金額」という。）により同一年度分の個人の道府県民税、個人の市町村民税又は森林環境税を納付し、又は納入するものであること。（法３１４の９②・③、令４８の |
| V5-14 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §1.2 | 25の2(4)（未納に充て、残りを還付）（期待 p.[50]） | OK | 見つかった頁=[50] 抜粋=は森林環境税に係る徴収金があるときは、これに納付又は納入し、それでもなお納付又は納入をすることができなかった部分の金額があるときは、当該金額を当該納税義務者に還付するものであること。（法３１４の９②・③、令４８の９の３③、４８の９の４①）( |
| V5-15 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §1.2 | 25の2(6)（確定した日＝(2)の賦課決定の日）（期待 p.[50]） | OK | 見つかった頁=[50] 抜粋=始期は、当該控除不足額が確定した日の翌日をいうものであるが、控除不足額が確定した日とは、(２)の賦課決定の日をいうものであること。(７)(６)の控除不足額に加算すべき金額に係る端数計算につ |
| V5-16 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §1.3 | 28 柱書（法附則５の４⑤～⑧）（期待 p.[51]） | OK | 見つかった頁=[51] 抜粋=３０日自治市第３７号）により行うものであること。（法附則６）２８法附則第５条の４の規定に基づく住宅借入金等特別税額控除の適用に当たっては、次の諸点に留意すること。（法附則５の４⑤～⑧）(１)この控除は、取得した住宅を居住の用に供した年が平成 |
| V5-17 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §1.3 | 28(1)（平成21年から令和12年まで）（期待 p.[51]） | OK | 見つかった頁=[51] 抜粋=こと。（法附則５の４⑤～⑧）(１)この控除は、取得した住宅を居住の用に供した年が平成２１年から令和１２年までの各年である所得割の納税義務者を対象とするものであること。(２)法附則第５条の４第５項第１号には、前年分の所得税に係 |
| V5-18 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §1.3 | 28(2)（措法第41条の3の2 を適用しない）（期待 p.[51]） | OK | 見つかった頁=[51] 抜粋=等特別税額控除額が規定されているものであるが、この控除額は、租税特別措置法第４１条の３の２の規定（特定の増改築等に係る住宅借入金等特別税額控除に係る控除額の特例の規定）については適用しないで計算するものであること。(３)法附則第５条の４第５ |
| V5-19 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §1.3 | 28(3)（控除前の所得税額）（期待 p.[51]） | OK | 見つかった頁=[51] 抜粋=、前年分の所得税額が規定されているものであるが、この金額は、住宅借入金等特別税額控除を行う前の段階の所得税額であること(４)市町村は、給与支払報告書等の記載により、控除額を算出す |
| V5-20 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §1.3 | 28(4)（給与支払報告書等の記載）（期待 p.[51]） | OK | 見つかった頁=[51] 抜粋=借入金等特別税額控除を行う前の段階の所得税額であること(４)市町村は、給与支払報告書等の記載により、控除額を算出するために必要な情報を把握するものであること。２８の３所得税については、居住者と非居住者とにより控除を認 |
| V5-21 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §1.3 | 28の3（税額控除の範囲は異ならない）（期待 p.[51]） | OK | 見つかった頁=[51] 抜粋=税額控除の範囲が異なっているが、個人の市町村民税については、前年中に非居住者であった期間を有する者についても税額控除の範囲は異ならないものであるから留意すること。第３節申告制 |
| V5-22 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §1.3・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §4.4 | 28 の柱書〜(4) に「基礎控除」「４８万円」「四十八万円」は 0 | OK | 範囲の長さ=403 |
| V5-23 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §1.4 | 26(2)（他の税額控除に先立ち）（期待 p.[51]） | OK | 見つかった頁=[51] 抜粋=は先物取引に係る課税雑所得等の金額を含まないものであること。(２)この控除の額は、他の税額控除に先立ち、税率適用後の所得割の額から控除するものであること。２７肉用牛の売却による事業所得については、課税の特例の対象 |
| V5-23b | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §1.4 | 26 は調整控除の項（期待 p.[50]） | OK | 見つかった頁=[50] 抜粋=５項の規定の適用を受けるものであること。（令４８の９の５②）２６調整控除の適用に当たっては、次の諸点に留意すること。（法３１４の６）(１)合計課税所得 |
| V5-24 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §1.4 | 29（毎年3月15日まで）（期待 p.[51]） | OK | 見つかった頁=[51] 抜粋=村内に住所を有することにより市町村民税の納税義務を負う者は、毎年３月１５日までに、法第３１７条の２第１項の申告書を提出しなければならないものであること。ただし、本人の申告をまたず課税資料を他から得られる者及び課 |
| V5-25 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §1.4 | 30（確定申告書の提出の日に申告書の提出があったものとみなす）（期待 p.[52]） | OK | 見つかった頁=[52] 抜粋=所得税法第２条第１項第３７号の確定申告書を提出した場合には、当該確定申告書が提出された日に法第３１７条の２第１項から第４項までの規定による申告書が提出されたものとみなし、当該確定申告書に記載された事項のうち同条第１項各号に掲げる |
| V5-28 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §4-8（未確認だった点） | 取扱通知（市町村税）で「申告特例控除」は p.48 の 1 回だけ（配当割額等の控除との順序の記述はない）（情報） | — | 頁=[48] 回数=1 |
| V5-26 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §5-1・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §4.4 | 取扱通知（道府県税）の「家屋敷」は p.30 の 1 回、「独立性」は p.144 の 1 回（不動産取得税） | OK | 家屋敷=[30] 独立性=[144] |
| V5-27 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §1 | 取扱通知（道府県税）の最後の改正は令和8年4月1日総税都第15号（期待 p.[1]） | OK | 見つかった頁=[1] 抜粋=和７年７月３日総税都第４７号令和７年９月２９日総税都第７３号令和８年４月１日総税都第１５号（目次）第１章一般的事項第１節通則第２節納税義務の承継第３節連帯納税 |
| V5-30 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §2.1 | 総税企第44号 第一 1(2)（同族会社との合計で 3% 以上 → 総合課税のまま配当割の対象）（期待 p.[2]） | OK | 見つかった頁=[2] 抜粋=（改正前は五十八万円以下）とする。（法第二十三条関係）（２）所得割の納税義務者が、自己の同族会社である法人との合計で株式等の保有割合が百分の三以上となる内国法人から支払を受ける上場株式等の配当等について、引き続き総合課税の対象とした上で、配 |
| V5-31 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §2.1 | 総税企第44号 第一 1(10)（加算・令和二十五年度・令和十二年）（期待 p.[4]） | OK | 見つかった頁=[4] 抜粋=に本特例措置を適用する措置を講ずる。（法附則第四条の五関係）（10）住宅借入金等特別税額控除について、以下の措置を講ずる。（法附則第五条の四関係）イ居住年が平成二十八年から令和七年までの各年である場合に係る控除限度額の計算上用いる所得税の課 |
| V5-32 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §2.1 | 総税企第44号 第二 1(8)（市町村民税）（期待 p.[14]） | OK | 見つかった頁=[14] 抜粋=-13-四条の五関係）（８）住宅借入金等特別税額控除について、以下の措置を講ずる。（法附則第五条の四関係）イ居住年が平成二十八年から令和七年までの各年である場合に係る控除限度額の計算上用いる所得税の課税 |
| V5-33 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §2.1・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §4.4 | 総税企第44号に「令和四年法律」は 0 | OK |  |
| V5-40 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.4・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §4.3 | 令和8年法律第2号の本文 PDF に「令和四年法律第一」は 0 | OK | 「令和四年法律」は p.[102, 203]（いずれも令和四年法律第五十六号） |
| V5-41 | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §4.3 | 「四十八万円」は p.25・52・73・74・78 | OK | [25, 52, 73, 74, 78] |
| V5-42 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §3.1 | 本文 PDF に「（居住年が平成二十八年から令和七年までの」（期待 p.[]） | OK | 見つかった頁=[73, 74] 抜粋=の適用を受けないときは」を「には」に改め、「合計額」の下に「（居住年が平成二十八年から令和七年までの各年である場合には、当該納税義務者の前年分の所得税に係る同法 |
| V5-43 | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §4.3 | 「（…の一部改正）」の見出しは 15 種（「地方税法等の一部を改正する法律の一部改正」2 回・「地方税法等の一部を改正する等の法律の一部改正」1 回） | **NG** | 見出し 19 個・18 種：p.1 第一条 地方税法の一部改正; p.167 第四条 地方税法等の一部を改正する等の法律附則第三十一条第二項の規定によりなおその効力を; p.169 第五条 森林環境税及び森林環境譲与税に関する法律の一部改正; p.170 第六条 特別法人事業税及び特別法人事業譲与税に関する法律の一部改正; p.212 第二十三条 道路運送車両法の一部改正; p.215 第二十五条 日本国とアメリカ合衆国との間の相互協力及び安全保障条約第六条に基づく施設及び区域; p.216 第二十六条 日本国における国際連合の軍隊の地位に関する協定の実施に伴う地方税法の臨時特例に関; p.216 第二十七条 自動車損害賠償保障法の一部改正; p.217 第二十八条 外国居住者等の所得に対する相互主義による所得税等の非課税等に関する法律の一部改正; p.218 第二十九条 租税条約等の実施 |
| V5-44 | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §4.3 | p.222：第三十五条地方税法等の一部を改正する法律（平成二十六年法律第四号）の…（期待 p.[222]） | OK | 見つかった頁=[222] 抜粋=車税等」とする。（地方税法等の一部を改正する法律の一部改正）第三十五条地方税法等の一部を改正する法律（平成二十六年法律第四号）の一部を次のように改正する。附則第十五条第一項中「の種別割」を削り、「第四百六十三条の |
| V5-44 | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §4.3 | p.224：第三十六条地方税法等の一部を改正する等の法律の一部を次のように改正す…（期待 p.[224]） | OK | 見つかった頁=[224] 抜粋=（2）（ⅱ）（地方税法等の一部を改正する等の法律の一部改正）第三十六条地方税法等の一部を改正する等の法律の一部を次のように改正する。附則第四十条を次のように改める。第四十条削除附則第五十三条を次のように改める。第五十三条削除（地方税法等の一 |
| V5-44 | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §4.3 | p.224：第三十七条地方税法等の一部を改正する法律（平成三十一年法律第二号）の…（期待 p.[224]） | OK | 見つかった頁=[224] 抜粋=。第五十三条削除（地方税法等の一部を改正する法律の一部改正）第三十七条地方税法等の一部を改正する法律（平成三十一年法律第二号）の一部を次のように改正する。 |
| V5-44 | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §4.3 | p.225：附則第十一条第五項から第七項までを削る。附則第十八条第五項から第七項…（期待 p.[225]） | OK | 見つかった頁=[225] 抜粋=-225-附則第十一条第五項から第七項までを削る。附則第十八条第五項から第七項までを削る。（船員法等の一部を改正する法律の一部改正）第三十八条船員法等 |
| V5-44 | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §4.3 | p.221：第三十四条総合特別区域法第二十二条の二第一項…（期待 p.[221]） | OK | 見つかった頁=[221] 抜粋=動車税」に改める。（総合特別区域法の一部改正に伴う経過措置）第三十四条総合特別区域法第二十二条の二第一項の指定自家用貨物自動車のうち令和七年度以前の年度分の旧法に規 |
| V5-44 | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §4.3 | p.168：第四条地方税法等の一部を改正する等の法律（平成二十八年法律第十三号）…（期待 p.[168]） | OK | 見つかった頁=[168] 抜粋=-168-第四条地方税法等の一部を改正する等の法律（平成二十八年法律第十三号）附則第三十一条第二項の規定によりなおその効力を有するものとさ |
| V5-45 | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §4.3 | 第37条（平成31年法律第2号の一部改正）が附則第53条を「削除」とする | **NG** | 附則第40条・第53条を「削除」とするのは第36条（平成28年法律第13号の一部改正）。第37条は平成31年法律第2号の附則第11条第5項〜第7項・第18条第5項〜第7項を削る（p.225）。p.224・225 は頁の画像でも確かめた → 訂正 |
| V5-47 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §2.5 | 本文 PDF の附則のうち他の法律の改正規定（第23条以後、p.212〜）にも「特定配当等」がある（情報） | — | p.[217, 218, 219] |
| V6-01 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §2.2 | 総務省の案内：平成21年から令和12年12月31日まで・翌年度の個人住民税 | OK |  |
| V6-02 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §2.2 | 総務省の案内：5％(97,500円を限度)・7％(136,500円を限度)・平成26年から令和3年12月31日まで | OK |  |
| V6-03 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §2.2 | 総務省の案内：市区町村への申告は不要・手続は今までと変わらない | OK |  |
| V6-04 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §2.2 | 総務省の案内：算出例（225,000円・190,000円 → 35,000円）と注（源泉徴収税額が0円）。35,000円と注は画像の代替テキスト（alt）にある | OK |  |
| V6-05 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §2.2 | 総務省の案内：旧制度は期限までに申告しなければ自動的に新制度 | OK |  |
| V6-06 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §2.2・§4.2 | 総務省の案内に「基礎控除」「48万」はない | OK |  |
| V6-10 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §4.1 | 杉並区：平成21年から令和12年12月末・9万7,500円・13万6,500円・申告不要・更新日 2026年6月13日 | OK |  |
| V6-20 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §3.1 | 船橋市：対象・条例の額以下は課税されない・4,000円・月割なし・更新日 令和6(2024)年5月2日・根拠条文 | OK |  |
| V6-21 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §3.1 | 船橋市：家屋敷とは（独立性・自己所有でなくても・現に居住していなくても・単身赴任者の妻子・貸付は除く・実質的な支配権） | OK |  |
| V6-30 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §3.2 | 熊本市：区以外の区・住民登録は関係ない・根拠条文・家屋敷の書き方・単身赴任の条件・配偶者の申告・最終更新日 | OK |  |
| V6-40 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §3.3 | 鹿児島市：条例第12条・独立性のある住宅・住民登録外居住者・4,500円（3,000円＋1,500円）・第24条第7項・更新日 | OK |  |
| V6-50 | docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md §4.3 | 目黒区：令和6年度分以降・大口株主等を除く・課税方式を一致・更新日 | OK |  |
| V6-60 | docs/public-sources/20261109_round3_juminzei-extra-law-text.md §0・docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §2.2 | 総務省の税制改正の一覧（ichiran04.html）に令和8年法律第2号の本文 PDF（001066281.pdf）へのリンクがある | OK | [('/main_content/001066281.pdf', '地方税法等の一部を改正する法律（令和8年法律第2号）')] |
| V6-web | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §2.2・docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md | shichoson：Last-Modified 2026-05-07・792394 バイト・SHA-256 先頭 107ba94cd6bd4b5e | OK | 今回：2026-05-07 792394 107ba94cd6bd4b5e |
| V6-web | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §2.2・docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md | dofuken：Last-Modified 2026-08-14・1001894 バイト・SHA-256 先頭 b8c40110f3a48e8d | OK | 今回：2026-08-14 1001894 b8c40110f3a48e8d |
| V6-web | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §2.2・docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md | kaisei_tsuchi：Last-Modified 2026-04-16・531864 バイト・SHA-256 先頭 321af651108b58ab | OK | 今回：2026-04-16 531864 321af651108b58ab |
| V6-web | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §2.2・docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md | r8_houritsu：Last-Modified 2026-03-31・511245 バイト・SHA-256 先頭 0282d962b36395be | OK | 今回：2026-03-31 511245 0282d962b36395be |
| V6-web | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §2.2・docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md | soumu_juutaku_loan：Last-Modified 2026-05-20・45536 バイト・SHA-256 先頭 43d772eb48c24aa0 | OK | 今回：2026-05-20 45536 43d772eb48c24aa0 |
| V6-web | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §2.2・docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md | suginami_juutaku：Last-Modified 2026-08-04・16203 バイト・SHA-256 先頭 2c4fd2f6dc6568fd | OK | 今回：2026-08-04 16203 2c4fd2f6dc6568fd |
| V6-web | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §2.2・docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md | funabashi_ieyashiki：Last-Modified 2026-11-07・27197 バイト・SHA-256 先頭 550f8a5377cb5762 | — | 今回：2026-11-10 27197 dd8ccc071dc71d18（取得の時点で変わる動的なページ。引用した文は本文の検査で確かめた） |
| V6-web | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §2.2・docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md | kumamoto_ieyashiki：Last-Modified 2026-11-06・72083 バイト・SHA-256 先頭 8fcb806df6102fb5 | OK | 今回：2026-11-06 72083 8fcb806df6102fb5 |
| V6-web | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §2.2・docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md | kagoshima_ieyashiki：Last-Modified 2026-03-16・20309 バイト・SHA-256 先頭 cdceb055e3354154 | — | 今回：2026-03-16 20309 b7ed0438482ac6d3（取得の時点で変わる動的なページ。引用した文は本文の検査で確かめた） |
| V6-web | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §2.2・docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md | meguro_kabu：Last-Modified 2026-10-29・23214 バイト・SHA-256 先頭 67ff67515578577a | OK | 今回：2026-10-29 23214 67ff67515578577a |
| V6-robots | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §2.2 | robots.txt：soumu.go.jp・city.kumamoto.jp・city.kagoshima.lg.jp は 200、ほかは 404 | OK | {'www.soumu.go.jp': 200, 'www.city.suginami.tokyo.jp': 404, 'www.city.funabashi.lg.jp': 404, 'www.city.kumamoto.jp': 200, 'www.city.kagoshima.lg.jp': 200, 'www.city.meguro.tokyo.jp': 404} |
| V7-HC1 | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §5 | HC1：市 57000・県 38000（合計 95000） | OK | 再計算：市 57000・県 38000・合計 95000 |
| V7-HC1b | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §5 | HC1b：市 45000・県 30000（合計 75000） | OK | 再計算：市 45000・県 30000・合計 75000 |
| V7-HC2 | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §5 | HC2：市 76000・県 19000（合計 95000） | OK | 再計算：市 76000・県 19000・合計 95000 |
| V7-HC3 | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §5 | HC3：市 45000・県 30000（合計 75000） | OK | 再計算：市 45000・県 30000・合計 75000 |
| V7-HC4 | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §5 | HC4：市 81900・県 54600（合計 136500） | OK | 再計算：市 81900・県 54600・合計 136500 |
| V7-HC5 | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §5 | HC5：市 0・県 0（合計 0） | OK | 再計算：市 0・県 0・合計 0 |
| V7-HC6 | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §5 | HC6：市 30003/5・県 20002/5（合計 10001） | OK | 再計算：市 30003/5・県 20002/5・合計 10001 |
| V7-HC8 | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §5 | HC8：市 38100・県 25400（合計 63500） | OK | 再計算：市 38100・県 25400・合計 63500 |
| V7-HC9 | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §5 | HC9：市 58500・県 39000（合計 97500） | OK | 再計算：市 58500・県 39000・合計 97500 |
| V7-F1-HX1-A | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §5 | F1-HX1-A：市 42000・県 28000（合計 70000） | OK | 再計算：市 42000・県 28000・合計 70000 |
| V7-F1-HX1-B | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §5 | F1-HX1-B：市 30000・県 20000（合計 50000） | OK | 再計算：市 30000・県 20000・合計 50000 |
| V7-F1-HX2-A | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §5 | F1-HX2-A：市 58500・県 39000（合計 97500） | OK | 再計算：市 58500・県 39000・合計 97500 |
| V7-F1-HX2-B | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §5 | F1-HX2-B：市 58500・県 39000（合計 97500） | OK | 再計算：市 58500・県 39000・合計 97500 |
| V7-F1-HX3-A | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §5 | F1-HX3-A：市 18000・県 12000（合計 30000） | OK | 再計算：市 18000・県 12000・合計 30000 |
| V7-F1-HX4-A | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §5 | F1-HX4-A：市 33000・県 22000（合計 55000） | OK | 再計算：市 33000・県 22000・合計 55000 |
| V7-F1-HX4-B | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §5 | F1-HX4-B：市 30000・県 20000（合計 50000） | OK | 再計算：市 30000・県 20000・合計 50000 |
| V7-195 | docs/inferences/20261109_round3_juminzei-extra-implications.md I4-3 | 上限に届く控除限度の基は 195万円（3%・58,500円、2%・39,000円。指定都市・特定取得の率と上限でも同じ） | OK | [Fraction(1950000, 1)] |
| V7-sum | docs/hypotheses/20261109_round3_juminzei-extra-model.md H3-1 | 市町村民税＋道府県民税＝5%・97,500円、7%・136,500円（一般の市・指定都市とも） | OK |  |
| V7-DC1 | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §5.1 | DC1：市で控除・県で控除・控除不足額 = (3000, 2000, 0) | OK | (Fraction(3000, 1), Fraction(2000, 1), Fraction(0, 1)) |
| V7-DC2 | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §5.1 | DC2：市で控除・県で控除・控除不足額 = (1000, 0, 4000) | OK | (1000, 0, Fraction(4000, 1)) |
| V7-DC3 | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §5.1 | DC3：市で控除・県で控除・控除不足額 = (Fraction(9702, 5), Fraction(6468, 5), 0) | OK | (Fraction(9702, 5), Fraction(6468, 5), Fraction(0, 1)) |
| V7-F2 | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §5.2・docs/hypotheses/20261109_round3_juminzei-extra-model.md H4-3 | F2 S=10000：法令の順（住宅→配当割）＝(所得割, 控除不足額) (0, 3000)、逆の順＝(0, 0) | OK | (0, 3000) (0, 0) |
| V7-F2 | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §5.2・docs/hypotheses/20261109_round3_juminzei-extra-model.md H4-3 | F2 S=20000：法令の順（住宅→配当割）＝(所得割, 控除不足額) (7000, 0)、逆の順＝(7000, 0) | OK | (7000, 0) (7000, 0) |
| V7-F2 | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §5.2・docs/hypotheses/20261109_round3_juminzei-extra-model.md H4-3 | F2 S=0：法令の順（住宅→配当割）＝(所得割, 控除不足額) (0, 3000)、逆の順＝(0, 3000) | OK | (0, 3000) (0, 3000) |
| V8-c2 | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §3.1 | _checks2.py は OK 15 件（ほかに数えただけ 3 行） | **NG** | OK=15 数えただけ=11 |
| V8-c3 | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §3.1 | _checks3.py は OK 58 件（ほかに数えただけ 2 行） | OK |  |
| V8-c3h | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §3.1 | _checks3.py の出力の SHA-256 先頭（evidence.md 3290c49731afd81e、cases.md 68d9e672fe78b49a、checks.json a250b19ef5b77bbf） | OK | {'evidence.md': '3290c49731afd81e', 'cases.md': '68d9e672fe78b49a', 'checks.json': 'a250b19ef5b77bbf'} |
| V8-c1 | docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md §3.1 | _checks.py は OK 394・NG 0 | OK | 394 0 |
