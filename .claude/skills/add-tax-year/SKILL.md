---
name: add-tax-year
description: okura-gov の判定コアに新しい年分（所得税の年分、住民税・国保・国年の年度、被扶養者・第3号の判定日の範囲）を足すとき、または新しい年分の様式の欄の対応表を足すときに使う。「令和9年分を足す」「対象の年分を広げる」「新しい年度に対応」「令和8年分の様式が公表された」「年分外を直す」など。
---

# 年分を足す（okura-gov）

最初に `AGENTS.md` を読む。**対象の年分は SCOPE §5 の範囲（HANDOFF D14）なので、足す前にユーザーに確認する。**
対応関係：所得税の年分 Y ⇔ 住民税・国保・国年の年度 Y+1（年度の値は所得の年分 Y の situation で計算する：`packages/core/README.md` §5.2）。

## 1. 触るファイル

| ファイル | 書くこと | 持ち場 |
|---|---|---|
| `docs/public-sources/`・`docs/measurements/` | 年分 Y の法令の版・基準額・表・様式・休日（primary-source スキル） | — |
| `rules/*/parameters/**/*.yaml` | 年分 Y で値が変わる葉に、日付のキー（適用開始日）を足す。時限の特例の終わりに `value: null` | 各モジュール |
| `rules/*/data/`（CSV と `SOURCES.json`） | 年分ごとの表（源泉徴収税額表、給与所得の別表など） | 各モジュール |
| `rules/tax/parameters/所得税/休日.yaml` | 年 Y・Y+1 の休日（暦要項と通達：D22 S8。申告期限の計算） | tax |
| `packages/core/src/okura_core/timepoints.py` | `SUPPORTED_INCOME_TAX_YEARS`・`SUPPORTED_FISCAL_YEARS`・`SUPPORTED_JUDGMENT_DATES` | 共有（調整してから） |
| `forms/data/index.yaml`・`forms/data/r<和暦の2桁>/` | 様式の欄の対応表（公表前は `状態: 未公表`） | forms |
| 各 `rules/<名前>/README.md`、`packages/core/README.md` §5.2・§6.1、`SCOPE.md` §5、`HANDOFF.md` | 対象の年分の記述（SCOPE と HANDOFF はユーザーの確認の後） | — |

## 2. 手順

1. **ユーザーに確認する**：足す年分・年度・判定日の範囲。
2. **一次情報を集める**（primary-source スキル）：
   - 法令の版：所得税は `asof=<Y>-12-31`、住民税は年度 Y+1 の賦課期日 `asof=<Y+1>-01-01` を基本に、関係する法令（`okura_monitor targets` で一覧できる）の本文。未施行の改正（`current_revision_status` が UnEnforced）も確かめる。
   - 改正法令の附則（適用年分・経過措置）、措置法の時限の特例の期限。
   - 国税庁の表（源泉徴収税額表など）・手引き・様式、暦要項（休日）。
3. **パラメータの棚卸し**：Grep で `rules/*/parameters/**/*.yaml` の葉を全部見て、葉ごとに年分 Y の値を確かめる。
   - 変わらない：日付のキーは足さない（前の値が続く）。確かめたことを public-sources に書く。
   - 変わる：`<Y>-01-01`（住民税の年度の値は、その葉の既存の日付のキーの付け方に合わせる）を足し、`metadata` の `施行日`・`law`・`law_revision`・`reference` を書く。
   - 終わる：終わりの日に `value: null`。既に先の日付のキー（例 `2027-01-01`）がある葉は、その値が今の版と合うかを確かめる。
4. **表のデータ**：年分 Y の表を `data/` に足し、`SOURCES.json` に取得元・取得日・SHA-256。
5. **対象の年分を広げる**（共有の `timepoints.py`。並行の担当と調整してから）。`evaluate.py` は `timepoints` の一覧を引く。
6. **式の年分の分かれ**：式・`build_inputs` の中で年分ごとに分けている所（`ctx.parameters_at`・年分の条件）を Grep で探し、Y で正しいかを確かめる。注入点の判定の時点（`injection_points.py` の `timing`）も。
7. **様式の欄の対応表**（`forms/README.md` §3）：様式が公表されるまでは `index.yaml` に `状態: 未公表` と理由・出典を書く（`未公表` で拒否される）。公表されたら `data/r<和暦の2桁>/` に帳票ごとの YAML を足し（前の年分の表＋差分：yoshiki-mapping-table H8）、`状態: 公表済み` にする。令和8年分以後は「社会保険料控除等の明細書」の扱いも確かめる（`forms/README.md` §3）。
8. **対象外の一覧**：年分で変わる行（ある年分からの改正で範囲内になる・外れる）を各 README で直し、`### 集計` も直す。
9. **ユニットテスト**：年分 Y で値・式が変わる所だけ、年分 Y−1 と Y の両側の境目のテストを足す（期待値に出典）。前の年分のテストは変えない。様式は `test_forms.py` の年分の一覧・概念の実在のテストが新しい年分を拾うかを確かめる。
10. **記録**：README・SCOPE §5・HANDOFF の今の状態を、日付つきで直す（SCOPE・HANDOFF はユーザーの確認の後）。

## 3. 確かめ方

```
.work/venvs/core/Scripts/python.exe -I -X utf8 -m pytest -q -p no:cacheprovider packages/core/tests/test_timepoints.py packages/core/tests/test_data_and_parameters.py packages/core/tests/test_forms.py
.work/venvs/core/Scripts/python.exe -I -X utf8 -m pytest -q -p no:cacheprovider packages/core/tests/test_architecture.py packages/core/tests/test_architecture_modules.py packages/core/tests/test_architecture_imports.py
.work/venvs/core/Scripts/python.exe -I -X utf8 -m pytest -q -p no:cacheprovider packages/core/tests/test_out_of_scope_inventory.py
```

最後に core の全部のテスト（数十分。バックグラウンドで）。

## 4. 注意

- 値を前の年分から写して「同じはず」で済ませない。変わらないことも一次情報で確かめて記録する。
- 年分 Y の作成コーナーとの照合は、ユーザーが手で行う完成の確認（D16・D24①）。テストにしない。
- シェルの引数にバッククォートや `$()` を入れない。ファイルは Edit・Write で書く。
