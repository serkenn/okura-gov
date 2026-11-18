# 実測：仮説・推測の文書に出てくる語彙の名前と区分の機械的な走査（round3 design）

- 作成日：2026-11-09
- 種別：実測（measurements）。対象は外部の資料ではなく、このリポジトリの `docs/hypotheses/20261109_*.md` と `docs/inferences/20261109_*.md`（ファイル名に `_round3_` を含むものを除く。61 ファイル）。ネットワークは使っていない。
- スクリプト：`scripts/R3X_design_vocab-scan.py`（Python 標準ライブラリだけ）
- 実行：リポジトリのルートで
  - 走査：`C:\Users\user\.pyenv\pyenv-win\versions\3.11.9\python.exe -I -X utf8 scripts/R3X_design_vocab-scan.py`
  - 引用の検査：同じコマンドに `cite-check <文書.md> ...` を付ける（§6）
- 出力：`scripts/results/R3X_design_vocab-scan/`
  - `corpus.json`（対象 61 ファイルのバイト数・SHA-256・行数。再実行で同じ結果になるかは、この SHA-256 が同じかで確かめる）
  - `sections.tsv`（見出し 778 件）、`tokens.tsv`（バッククォートの中身 1,121 件）、`token_summary.json`、`prefix_summary.json`、`named_functions.tsv`、`variants.json`、`classification_rows.tsv`、`cite_check.json`
- この文書は数えた結果だけを書く。どれをどう統合するかの提案は仮説 `docs/hypotheses/20261109_round3_design-vocabulary.md` ほかに書く。
- 限界：部分文字列の一致で数えているので、文脈の違い（たとえば「見込み」が D19 の印の意味か、法令の「見込額」の意味か）は区別していない。行の分類（§5）は「同じ行に区分の語があるか」だけで、行の意味を読み取っていない。

## 1. バッククォートで囲んだ語の分類（`token_summary.json`）

| 分類 | 何を数えたか | 異なり | 出現 |
|---|---|---|---|
| path | 文書・スクリプトのパス | 214 | 491 |
| ascii_ident | 英数字の識別子（`payer`、`kind`、欄コード `G58` など） | 187 | 274 |
| other | 上のどれでもないもの（式、日本語の関数名など） | 133 | 211 |
| dotted_jp | 日本語を含み「.」で区切った名前（概念 ID らしいもの） | 61 | 84 |
| ascii_expr | 英数字と記号の式（`year:2025-10-15` など） | 26 | 36 |
| form_id | 様式の ID（`KOA020-01` など） | 14 | 14 |
| meta_key | `xxx:` の形（beancount のメタデータのキー） | 4 | 11 |

- meta_key は `id:`・`payer:`・`patient:`（各3回、2ファイル：R2-tools_adoption、R4-modeling_entity-model）と `evidence:`（2回、impl-prep_denchoho-record-layer）だけ。
- 記録層のキーとして英小文字の名前が出てくるのは、impl-prep_iryohi-model（`payer`・`patient`・`provider`・`paid_on`・`incurred_on`・`amount`・`kind`・`evidence`・`selfmed_mark`・`deposit_applied_on` と `kind` の値 17 個）、impl-prep_denchoho-record-layer（`evidence_id`・`person`・`received_at`・`source`・`original_filename`・`media_type`・`doc_type`・`date`・`amount`・`currency`・`counterparty`・`derived_from`・`edit_kind`・`retain_from`・`retain_until`、ログの `seq`・`prev_sha256`・`kind`・`at`・`actor`・`sha256`）、round2b_invoice-model（`ct_liability`・`invoice_registration`・`ct_return`・`ct_accounting_method`・`ct_accrual_choice`・`ct_simplified_karibarai`・`price_excluding_ct`・`counterparty_registered`）の3文書。
- 同じキーが2つの文書で別のものを指す例：`kind`（iryohi では医療費の種類の語彙、denchoho ではログの記録の種類）、`evidence`（iryohi では「証憑の種類と識別」、denchoho では `evidence_id` の並び）。`amount` は両方で金額。
- 英語の概念名：`total_income_sum`（合計所得金額）と `total_income_for_deductions`（総所得金額等）が impl-prep_iryohi-model と round2b_kabu-model に出る。ほかの文書は同じ概念を日本語の `所得税.合計所得金額` などで書く（§2）。

## 2. 概念 ID らしい名前の接頭辞（`prefix_summary.json`）

`dotted_jp` のうち、パスや位置名（`/`・`<>` を含むもの）を除いたものを、最初の「.」の前で分けた。

| 接頭辞 | 異なり | ファイル数 | 例 |
|---|---|---|---|
| 所得税 | 21 | 8 | `所得税.合計所得金額`、`所得税.老人扶養親族`、`所得税.事業所得.総収入金額`、`所得税.申告不要の判定.その他の所得金額` |
| 健保 | 7 | 7 | `健保.年間収入`、`健保.国内居住要件`、`健保.収入基準.60歳以上`、`健保.年間収入.不動産` |
| 住民税 | 6 | 6 | `住民税.合計所得金額`、`住民税.同居直系尊属`、`住民税.国外居住者` |
| 国保 | 6 | 2 | `国保.基礎控除後の総所得金額等`、`国保.世帯`、`国保.軽減判定所得` |
| 判断 | 4 | 1 | `判断.同居を常況`、`判断.住所の所在`、`判断.円換算の方法`、`判断.例外第5号`（round2_elderly-abroad-model） |
| 国年 | 3 | 2 | `国年.配偶者`、`国年.免除判定所得` |
| 端数 | 2 | 1 | `端数.事業専従者控除の除算`、`端数.土地等負債の按分`（round2b_fudosan-calculation-model） |
| 解釈 | 2 | 2 | `解釈.所法56の対象`、`解釈.勤労学生の給与所得等以外の部分`（round2b_fudosan） |
| 基準 | 1 | 1 | `基準.事業的規模の推定`（round2b_fudosan） |
| 所得金額調整控除 | 1 | 1 | `所得金額調整控除.第1項の端数＝1円未満切上げ`（round2_gaps-hypotheses） |
| 同一生計配偶者 | 1 | 1 | `同一生計配偶者.所得上限`（round2_spouse-model） |
| 第83条の2 | 1 | 1 | `第83条の2.超過額の切下げ(超過額)`（round2_spouse-model） |
| 公的年金等控除 | 1 | 1 | `公的年金等控除.その他の合計所得金額`（round2b_nenkin-model） |
| periods | 1 | 1 | `periods.period(年).stop`（OpenFisca の式。概念 ID ではない） |

- 制度の接頭辞（所得税・住民税・健保・国保・国年）のほかに、制度でない接頭辞（判断・端数・解釈・基準）、概念名や条番号を接頭辞にしたもの（所得金額調整控除・同一生計配偶者・第83条の2・公的年金等控除）がある。
- バッククォートの外で `所得税.生命保険料控除.23歳未満特例` のように書いたパラメータ名（round2_hoken-kifu-model H12 の表）は、この数に入っていない。

## 3. 名前つきの関数らしい名前の書き方（`named_functions.tsv`）

端数・期間・年齢などに関わる語を含むバッククォートの中身を、書き方で3つに分けた（異なり。`round2`・`threshold_I1` のような関数でないものも数に入っている）。

| 書き方 | 異なり | 例 |
|---|---|---|
| ascii（英語・ローマ字） | 23 | `kazei_hyojun_sen_en_kirisute`・`fukko_zeigaku_ichi_en_kirisute`（impl-prep_zeigaku）、`round_kazei_shotoku_1000`・`round_kakutei_100`（round2_juminzei-tax）、`floor_to_1000`・`days_within_inclusive_of_start`（round2_kyosai）、`threshold_5pct_floor`（impl-prep_iryohi）、`fx_to_yen_floor`（round2_elderly-abroad）、`floor_yen`（impl-prep_kyuyo の推測）、`aoiro_tokubetsu_r7r8`（round2_aoiro） |
| japanese | 30 | `償却費の端数`・`一括償却_各年の端数`・`所令85_限度`（round2_genka）、`端数.事業専従者控除の除算`（round2b_fudosan）、`第83条の2.割合と切上げ(額, 分子, 分母)`（round2_spouse）、`公的年金等控除額の円未満処理`（round2b_nenkin）、`期限_月以内(...)`・`青色控除_上限(...)`（round2_aoiro）、`年齢(生年月日, 判定日)`（impl-prep_misc）、`年齢(生年月日, 基準日)`（round2_aoiro）、`年齢_年末`・`年齢_年末の翌日`・`暦の年齢`（impl-prep_tools-adoption-recheck） |
| mixed（英語の名前に日本語の引数） | 12 | `evaluate(中間表現, 年分)`（impl-prep_juminzei・impl-prep_zeigaku）、`evaluate_kenpo(中間表現, 判定日 D)`（impl-prep_kenpo）、`shinkoku_yohi(計算の結果, 中間表現, 年分)`（impl-prep_zeigaku）、`kyosai_nintei_bi(事実発生日, 届出受理日)`（round2_kyosai）、`kisanbi_shorui(受領日)`・`manryo(起算日, 年数)`（impl-prep_denchoho） |

## 4. 言い換えの候補の出現数（`variants.json`）

部分一致の回数。「単独」は、同じ組の長い表記に含まれる分を引いた回数。

| 組 | 表記：出現（ファイル数） |
|---|---|
| 生計 | 生計を一にする 92（28）、生計一 51（6）、生計を一に（単独）10 |
| 同一世帯 | 同一の世帯に属する 10（4）、同一の世帯（単独）19（計 29、10）、同一世帯 54（16） |
| 判定の時点 | 判定日 123（22）、認定日 53（16）、基準日 10（4） |
| 事実台帳 | 事実台帳 14（7）、人と関係の記録 6（2）、取引でない事実 2（2）、取引ではない事実 2（2） |
| 判断台帳 | 判断台帳 40（12）、人の判断 87（27）、判断の記録 4（4） |
| 選択 | 納税者の選択 21（8）、本人の選択 6（3）、人の選択（単独）4、家族の選択 1（1） |
| 注入 | 注入データ 56（17）、注入するデータ 22（9）、保険者データ 41（4）、注入点 1（1）、市町村データ 1（1） |
| 見込み | 見込み 185（41）、見積り 7（3） |
| 年間収入 | 年間収入 94（23）、収入の見込み 35（16）、年収 6（5） |
| 支払者 | 支払者 137（29）、支払った人 18（9）、payer 6（3） |
| 受診者 | 受診者 31（9）、受診した人 4（3）、patient 7（3） |
| 扶養の所属 | 扶養所属 48（6）、扶養の所属 19（10）、所属の割当て 14（4） |
| 申告書の記載 | 申告書の記載 20（13）、申告書等の記載 14（6）、提出した申告書 8（4）、記載の事実 4（3） |
| 中間表現 | 中間表現 120（35）、事実の語彙 2（2） |
| 印 | 未確定 133（36）、対象外 114（32）、出典未確認 48（18） |

## 5. 区分の語が同じ行にある行（`classification_rows.tsv`）

表の行と箇条書きの行のうち、項目の語を含む行を集めた（508 行）。下は、項目ごとに「行に現れた区分の語」が文書で違うものの抜き出し（ファイル名は `docs/hypotheses/20261109_` を省略）。

| 項目 | 文書：行 | 行にある区分の語 | 行の書き出し（要約せず先頭だけ） |
|---|---|---|---|
| 経理方式 | round2_genka-model:29 | 事実 | 「事実 \| 本人が課税事業者か・経理方式（税込／税抜） \| … \| 記録層（人・年分ごとの状態）」 |
| 経理方式 | round2b_invoice-model:33 | 判断,D4,選択 | 「判断台帳（D4・D12）に「消費税等の経理方式」を…納税者の選択として持つ」 |
| 経理方式 | round2b_invoice-model:122 | 判断,選択 | 「判断：`ct_accounting_method`（経理方式の選択）…」 |
| 同一の世帯 | impl-prep_kenpo-input-facts:31・78・79 | 判断（D4） | 「同一の世帯に属するか…**判断**」「コアは判断がなければ判定を止めて…」 |
| 同一の世帯 | round2_kyosai-model:54・55 | 事実,判断,注入,コア | 「コアの規則（共済）：同一の世帯 ⇔ 生計を共にする（判断）か…」「コアの規則（健保）：保険者データに…」 |
| 同一の世帯 | round2_spouse-model:132 | 事実,判断,選択 | 「同居・別居、同一世帯 \| 人×人×区間 \| 事実（同一世帯の評価は判断の余地あり）」 |
| 同一の世帯 | R4-modeling_entity-model:102 | 事実,未決 | 「被保険者と同一の世帯に属するか（未決 U3）」 |
| 続柄 | R4-modeling_entity-model:237 | 事実 | 「親族か、続柄・親等 \| **事実**（戸籍）」 |
| 続柄 | impl-prep_kenpo-input-facts:129 | 事実 | 「組の事実 \| 続柄（被保険者との）…」 |
| 続柄 | impl-prep_misc-hypotheses:54 | 事実,判断,コア | 「親等の計算をコアに置く…「続柄」を記録層に直接書く案もあるが…日付つきの事実から導く方が…」 |
| 続柄 | round2_kyosai-model:41 | 事実,コア | 「入力の事実：続柄（被保険者から見た関係の経路…）。コアが経路から…に分類し」 |
| 業務の区分・事業的規模 | round2_aoiro-model:164 | D4 | 「業務の区分（不動産・事業・山林）、不動産の貸付けが事業的規模か \| 人×業務×年分（D4）」 |
| 業務の区分・事業的規模 | R4-modeling_entity-model:233 | 事実,判断,D4,コア | 「社会通念上事業と称するに至る程度か \| **人の判断（D4）**。所得区分そのものは**判定コア**が…」 |
| 帳簿の方式 | round2_aoiro-model:48 | 事実 | 「記録層が持つ事実：業務ごとの帳簿の方式…」 |
| 帳簿の方式 | round2_aoiro-model:165 | D4 | 「帳簿の方式（正規の簿記・簡易帳簿・現金式）、正規の簿記で記録・作成している旨の宣言 \| 人×業務×年分（D4）」 |
| 申告書等の記載 | R4-modeling_entity-model:278 | 事実,判断,D4,選択 | 「扶養の所属（D4 の選択／申告書等の記載の事実…）」 |
| 申告書等の記載 | round2_spouse-model:137 | 事実,判断 | 「申告書等の記載（誰をどの区分で、提出日） \| … \| 判断→提出後は事実」 |
| 大口株主等 | round2b_kabu-model:38・92 | 事実,判断／事実 | 「「大口株主等に当たるか」をその配当の事実（判断つき）として受け取る」「大口株主等か（同族会社との合算） \| 本人（事実の確認）」 |
| 指定都市 | round2_juminzei-tax-calc-model:49 | （なし） | 「指定都市 \| 政令の20市の一覧（施行日つき） \| なし \| ［法令］§4」（注入する列が「なし」） |
| 指定都市 | round2_spouse-model:79・142 | 事実,注入 | 「納税義務者の住所が指定都市かは…注入データにする」 |
| 指定都市 | round2_elderly-abroad-model:90 | 事実,注入 | 「…注入点は要らない。…「指定都市か」は、住所の市町村の事実（E6）から決まる」 |
| 級地 | impl-prep_juminzei-judgment-model:93 | コア | 「判定コアのパラメータは「市町村（または級地）→ 基本額・加算額」…」（同じ節の 94 行に「既定値」） |
| 級地 | round2_kyosai-model:126 | 注入 | 「均等割の非課税の条例の額・級地（SCOPE §5.3 の注入データ）は…」 |
| 寄附先の種類 | round2_hoken-kifu-model:75 | 事実 | 「寄附先の種類…は…団体の属性なので、出典つきの宣言的なデータ…として持つ」 |
| 寄附先の種類 | round2_juminzei-tax-calc-model:67 | （なし） | 「寄附金税額控除 \| 寄附ごとの寄附先の区分、寄附した日、金額…」（入力の事実の列） |

- round2_hoken-kifu-model の 94 行（「住所の市町村が**指定都市**か」）は、同じ節の 91 行の見出し「注入データ（市町村・都道府県ごと、または国の告示）」の下の箇条（行そのものには区分の語がないので、上の表の数え方では拾っていない。目で確かめた）。
- impl-prep_juminzei-judgment-model H6（94 行）は「条例を確認していない市町村は、級地ごとの政令基準の上限…を既定値にし」と書く（目で確かめた）。

## 6. 引用の機械的な検査（`cite-check`）

- 仮説の文書（round3 design）の中の「[略号] §n」の引用が、略号の表のファイルの見出しにあるかを調べる。結果は `cite_check.json`。
- 2026-11-09 の実行結果は、仮説の文書の末尾の「引用の検査」に書く（この文書を書いた時点では、仮説の文書はまだない）。

## 7. 分からなかったこと

- 部分一致なので、「同一世帯」が共済の地共済法ロの語か、健保の「同一の世帯」の略記かは区別できない。
- `classification_rows.tsv` の 508 行のうち、上の §5 に挙げなかった行は目で全部は確かめていない。
