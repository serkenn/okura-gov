# core-perf：判定コアの計算の速さ（直す前と後。実測）

- 種類：実測。実行日：2026-11-12。対象：`packages/core/src/okura_core` の共有の部分（evaluate・situation・registry・result・explain・concepts）。
- 目的：結果の値・判定・状態を1つも変えずに速くしたことを、直す前の版と同じ規則モジュールで突き合わせて確かめ、時間を記録する。
- スクリプト：
  - `scripts/IMPL5_core-perf_devtree.py`：直す前の版の写し（`.work/perf/snap_src`。作業の始めに `packages/core/src/okura_core` を丸ごと写したもの。リポジトリに commit がないので写しで比べる）に、持ち場の共有のファイルだけを今の版から重ねた木を作る（並行の担当が規則モジュールを書き換えている間も、同じ規則で比べるため）。
  - `scripts/IMPL5_core-perf_snapshot.py`：okura_ir の `examples/valid` の家庭（と 500 人の給与だけの家庭）を問い（one＝所得税の令和8年分、y25＝令和7年分と提出日、fy＝令和9年度の住民税・国保・国年、dd＝判定日 2026-04-01、w500）で評価し、結果の JSON と時間を保存する。
  - `scripts/IMPL5_core-perf_compare.py`：前と後の結果の JSON を、根拠の参照の形の違い（後は根拠の一覧 `basis` の番号。版 1）と後で足した項目（`differences`・`forms`・問いの `forms`）を戻して比べる。
- 出力：`scripts/results/IMPL5_core-perf/`（`before_*.log`・`after_*.log`：時間と JSON の大きさ、`compare.txt`：突き合わせ、`timing_clean.txt`：ほかの計算と同時に走らせなかった計測）。結果の JSON そのもの（前の w500 は 210MB）は `.work/perf/` に置いた（リポジトリに入れない）。

## 1. 再現の手順

```
P=.work/venvs/core/Scripts/python.exe
$P -I -X utf8 scripts/IMPL5_core-perf_devtree.py .work/perf/dev_src            # 後の版（前の写し＋共有のファイル）
PERF_MODES=one,y25 $P -I -X utf8 scripts/IMPL5_core-perf_snapshot.py .work/perf/before .work/perf/snap_src
PERF_MODES=one,y25 $P -I -X utf8 scripts/IMPL5_core-perf_snapshot.py .work/perf/after .work/perf/dev_src
PERF_EXAMPLES=01,04,05 PERF_MODES=fy,dd ...（同じ。fy・dd は前の版が遅いので3家庭だけ）
$P -I -X utf8 scripts/IMPL5_core-perf_compare.py .work/perf/before .work/perf/after
```

## 2. 突き合わせ（compare.txt）

同じ 19・違う 0。08 は前も後も同じ誤り（規則モジュールの側：income_kinds の `missing` に dict、`判断.国内源泉所得の内訳` の候補なし）。
01 の dd は前の版が `ScenarioResult` の検査で失敗（判定日の単位で、段の読んだ値の依存の ID が結果に出さない所得税の値を指した）。後の版はその ID を、結果に出す値に届くまで置き換えて評価できる（`evaluate._stage_values` の resolve。前の版で成功していた評価の出力は変わらない）。

## 3. 時間（秒。Windows 11、Python 3.11.9、openfisca-core 46.0.1）

| 家庭・問い | 前 | 後 |
|---|---|---|
| 01（3人）one | 5.44 | 0.90 |
| 05（1人）one | 2.07 | 0.48 |
| 500人（給与だけ）one | 222.6（JSON 210MB） | 34.8（JSON 41MB） |
| 02 one / 03 one / 06 y25 / 07 one | 92.9 / 117.3 / 193.8 / 134.9 | 13.9 / 16.6 / 28.6 / 17.2 |
| 01 fy / 04 fy / 04 dd | 92.2 / 224.6 / 249.6 | 11.7 / 19.6 / 32.0 |

前の one・y25 の 02〜07 は、後の計測と一部が同時に走った（前の時間は少し大きく出ている）。01・05・500人は同時に走らせずに測った（`timing_clean.txt`）。
JSON の大きさ（01 one）：1,955KiB → 601KiB。

## 4. 測った原因と直したこと（packages/core/README.md §5.4）

- 期間の文字列の解析（家族1組で 34,658 回）：入力を変数ごとの配列で入れ、期間のオブジェクトを使い回す。
- 段階評価の回・候補の組ごとの Simulation の組み立て直し：Simulation を使い回し、違った入力に依存した値だけを計算し直す（`evaluate._Engine`）。
- 中間の回の値の集め方・由来の重複（理由のリストが依存をたどるたびに重なり、03 で `_merge_reasons` だけで 9 秒）。
- 根拠の項目の作り直し（`parameter_basis` 13,412 回）・概念の依存の閉包（1,682 回）・版のハッシュ：プロセスで1回。
- build_inputs・グループの組み立て：読んだ判断・端数の候補が同じなら使い回す。

## 5. 分からなかったこと・残り

- 目標の「家族1組 0.3 秒以下」は 1人の家庭（05：0.48 秒）でも届かなかった。残りの時間の約半分は規則モジュールの式の計算（OpenFisca。トレースつき）で、
  段の回（8回＋最後）ごとの値の集め方が残りの多く。候補の組が多い家庭（02・03・07：未入力の判断が多い）と、上限を超えたつながりの点の比較（fy・dd）は、なお 10〜30 秒。

## 6. 2回目（2026-11-12 午後）：段の回の使い回し・入力の集まりのビット・トレーサー

- 直す前の版：作業の始めに `packages/core/src` を `.work/perf2/snap_src` に写したもの（1回目の後の版。規則モジュールは並行の担当の 2026-11-12 午後の版）。
  後の版：`PERF_SNAP=.work/perf2/snap_src` で `scripts/IMPL5_core-perf_devtree.py` を実行した木（写しに持ち場の共有のファイルを重ねたもの。
  規則モジュールの concepts.yaml は写しのままなので、同じ日に足した年齢の境目の宣言は入らない）。
- 足したスクリプト：`scripts/IMPL6_core-perf_profile.py`（家庭1つ・問い1つを cProfile で測る。原因の特定に使った）。
  `IMPL5_core-perf_compare.py` に `PERF_SAME_SCHEMA=1`（前も後も根拠の一覧の形のとき。後で足した `age_boundaries` と結果のスキーマの版を戻して比べる）、
  `IMPL5_core-perf_devtree.py` に `PERF_SNAP`（写しの場所）を足した。
- 再現：
  ```
  PERF_SNAP=.work/perf2/snap_src $P -I -X utf8 scripts/IMPL5_core-perf_devtree.py .work/perf2/dev_src
  PERF_MODES=one,y25,fy,dd $P -I -X utf8 scripts/IMPL5_core-perf_snapshot.py .work/perf2/before_c .work/perf2/snap_src
  PERF_MODES=one,y25,fy,dd $P -I -X utf8 scripts/IMPL5_core-perf_snapshot.py .work/perf2/after_c .work/perf2/dev_src
  PERF_SAME_SCHEMA=1 $P -I -X utf8 scripts/IMPL5_core-perf_compare.py .work/perf2/before_c .work/perf2/after_c
  ```
- 出力：`scripts/results/IMPL6_core-perf/`（`timing_clean_before.log`・`timing_clean_after.log`：前を全部、続けて後を全部、自分のほかの計算と同時に
  走らせずに測った時間〔並行の担当の計算は同じ機械で動いていた〕、`compare_clean.txt`：突き合わせ。`before.log`・`after.log`・`compare.txt` は
  作業の途中の計測で、前の一部はプロファイラと同時に走った）。

### 6.1 突き合わせ

同じ 40・違う 0（`compare_clean.txt`。10家庭 × 4つの問い。08 は前も後も同じ誤り〔規則モジュールの側〕）。11 は写しの後に中間表現の担当が足した家庭で、前の版でも評価できた。

### 6.2 時間（秒。前 → 後）

| 家庭 | one | y25 | fy | dd |
|---|---|---|---|---|
| 01（3人） | 1.20 → 1.11 | 1.43 → 1.25 | 15.07 → 4.95 | 30.64 → 5.08 |
| 02 | 16.57 → 7.36 | 8.84 → 4.21 | 16.09 → 5.12 | 43.31 → 7.04 |
| 03 | 25.48 → 16.50 | 11.80 → 8.54 | 16.88 → 7.77 | 22.41 → 15.23 |
| 04 | 3.63 → 2.44 | 1.78 → 1.10 | 26.06 → 8.83 | 43.62 → 7.06 |
| 05（1人） | 0.54 → 0.61 | 1.04 → 0.99 | 0.62 → 0.55 | 0.65 → 0.60 |
| 06 | 12.30 → 4.57 | 41.39 → 15.23 | 31.86 → 7.98 | 13.66 → 4.93 |
| 07 | 25.03 → 12.12 | 21.35 → 10.79 | 33.93 → 14.34 | 24.60 → 12.39 |
| 09 | 1.01 → 0.69 | 0.97 → 0.68 | 1.14 → 0.88 | 0.90 → 0.71 |
| 10 | 2.44 → 1.71 | 2.49 → 1.73 | 2.79 → 1.93 | 2.31 → 1.57 |
| 11 | 8.48 → 6.42 | 8.45 → 6.20 | 9.73 → 7.09 | 7.90 → 5.76 |

（one は2回の速い方、ほかは1回。05 の one は誤差の範囲〔0.5〜0.6 秒〕。）

### 6.3 測った原因と直したこと（packages/core/README.md §5.4）

- 段の回の計算が候補の組ごとに全部やり直されていた（02 one：32 組 × 9 回 = 288 回の計算と値の集め方）。回の段に渡す値は、その回の値を集めるのに
  使った変数がトレースで依存した入力・対象外の検出・グループだけで決まるので、それが同じ回は使い回し、段の関数だけを今の判断で実行する
  （`evaluate._RoundNode`・`_RoundMemo`）。02 one で計算は 288 → 113 回。段の関数が読む判断（同居・生計など）で回の結果を分けると 158 回にしか減らなかった
  （段の関数は軽いので、段に渡す値だけを使い回すのがよい）。
- 値の集め方で、推移的に依存した入力の集まり（数千の要素）の和を値ごとに取っていた（04 fy で値の集め方の約半分）：整数のビットにした（`_InputIndex`）。
  同じ uses の組を何度も伝えていた（`absorb`）：2回目は飛ばす。
- OpenFisca の FullTracer の記録（時間・値）：依存だけを記録するトレーサーにした。依存の表の逆向きの辺を毎回作り直していた・回の依存の集まりを毎回最初から
  たどっていた：足し引きにした。トレースの閉包を値の集め方ごとに作り直していた：トレースの項目が同じ間は使い回す。
- build_year：全員分のキーの集まり・検査した build_inputs の結果・使わない判断の対象の検出を使い回す・絞る。

### 6.4 分からなかったこと・残り

- 目標（数秒以内、家族1組の通常の問い 0.5 秒以内）に届かない家庭が残った：03 one（16.5）・dd（15.2）、07（10〜14）、06 y25（15.2）。
  01 one は 1.1 秒、05 は 0.5〜0.6 秒。
- 残りの原因（03 one のプロファイル：`.work/perf2/prof03_f.txt`。作業用で、リポジトリに入れない）：候補の組が多く（03：48 組）、後ろの段（住民税の段）の回は
  組ごとに入力の値が本当に違う（家内労働者等・青色申告特別控除の要件・申告の時期で所得が変わる）ので使い回せない。そこでは OpenFisca の式の計算
  （1回の計算の Python の手間：calculate の呼び出し 10万回）と値の集め方がほぼ半分ずつ。式そのもの（規則モジュール）の時間は小さい。
  さらに速くするには、候補の組をまとめて1つの Simulation の配列で計算する（OpenFisca の配列の使い方。トレースが組ごとに分かれなくなるので、
  値の依存の扱いを考え直す要がある）か、段の回の値を値ごとに差分で集め直す仕組みが要る（未着手）。
- 07 は候補の組が上限（64）を超え、点の比較（`_affected_inputs` → 点ごとの段の計算し直し）が時間の大半。

## 7. 3回目（2026-11-12 夜）：複数の問いをまとめた評価

- 問い（multi）：所得税 2025・2026、住民税・国保 2026・2027 年度、被扶養者の判定日 2026-04-01 をまとめて1回の evaluate で評価する
  （SCOPE §8・D19 の複数の問い。`IMPL5_core-perf_snapshot.py` の `PERF_MODES=multi`）。評価の単位は (2025)・(2026)・(2026, 2026-04-01) の3つ。
- 直す前の版：作業の始めに `packages/core/src/okura_core` を `.work/perf3/snap_src` に写したもの。後の版：`PERF_SNAP=.work/perf3/snap_src
  PERF_FILES=evaluate.py,situation.py,registry.py` で `IMPL5_core-perf_devtree.py` を実行した木（写しに、変えた3つのファイルだけを重ねる。
  並行の担当が forms・規則モジュールを書き換えているので、`PERF_FILES` を足した）。
- 足した・変えたスクリプト：`scripts/IMPL7_core-perf_rounds.py`（単位ごとの時間・回の使い回しの当たり外れ・点の比較の situation ごとの時間）。
  `IMPL5_core-perf_snapshot.py`・`IMPL6_core-perf_profile.py` に問い `multi`、`IMPL5_core-perf_compare.py` に `PERF_SAME_SCHEMA=2`（何も戻さない）と
  `PERF_SORT_REASONS=1`（対象外の理由の文の並びをそろえる。§7.2）、`IMPL5_core-perf_devtree.py` に `PERF_FILES`。
- 再現：
  ```
  PERF_SNAP=.work/perf3/snap_src PERF_FILES=evaluate.py,situation.py,registry.py $P -I -X utf8 scripts/IMPL5_core-perf_devtree.py .work/perf3/dev_src
  PERF_MODES=multi $P -I -X utf8 scripts/IMPL5_core-perf_snapshot.py .work/perf3/before_c .work/perf3/snap_src
  PERF_MODES=multi $P -I -X utf8 scripts/IMPL5_core-perf_snapshot.py .work/perf3/after_c .work/perf3/dev_src
  PERF_SORT_REASONS=1 PERF_SAME_SCHEMA=2 $P -I -X utf8 scripts/IMPL5_core-perf_compare.py .work/perf3/before_c .work/perf3/after_c
  $P -I -X utf8 scripts/IMPL7_core-perf_rounds.py units 08 .work/perf3/snap_src      # rounds・slots も同じ（slots は y26 を付けた）
  $P -I -X utf8 scripts/IMPL6_core-perf_profile.py 08 multi scripts/results/IMPL7_core-perf/profile08_before.txt .work/perf3/snap_src
  ```
- 出力：`scripts/results/IMPL7_core-perf/`（`timing_clean_before.log`・`timing_clean_after.log`：前を全部、続けて後を全部、自分のほかの計算と
  同時に走らせずに測った時間〔並行の担当の計算は同じ機械で動いていた〕、`compare_clean.txt`：理由の文の並びをそろえた突き合わせ、
  `compare_clean_unsorted.txt`：そろえない突き合わせ、`compare_rerun_before.txt`：前の版どうしの突き合わせ、`units08_*.txt`・`rounds08_before.txt`・
  `slots08_y26_*.txt`：`IMPL7_core-perf_rounds.py` の出力、`profile08_before.txt`・`profile01_before.txt`：cProfile、`before.log`：作業の途中の計測）。

### 7.1 時間（秒。前 → 後。timing_clean_*.log）

| 01 | 02 | 03 | 04 | 05 | 06 | 07 | 08 | 09 | 10 | 11 |
|---|---|---|---|---|---|---|---|---|---|---|
| 15.8 → 11.0 | 23.5 → 16.5 | 31.7 → 27.6 | 18.4 → 14.2 | 2.3 → 1.8 | 18.6 → 13.6 | 30.9 → 25.8 | 131.1 → 93.7 | 1.9 → 4.4 | 7.5 → 4.9 | 20.2 → 18.5 |

- 1回ずつ。並行の担当の計算が同じ機械で動いていて、同じ版の2回でも 10% ほど違う（08 の前：`before.log` 145.5・`timing_clean_before.log` 131.1）。
  09 の後（4.4）は前（1.9）より遅いが、09 は分かれ目が少なく、変えた仕組みはほとんど働かない（ほかの計算と重なったと考える。測り直していない）。
- 目標（家庭ごと数秒以内）には届かなかった（§7.5）。

### 7.2 突き合わせ

- 同じ 11・違う 0（`compare_clean.txt`。対象外の理由の文〔「／」でつないだもの〕の並びをそろえて比べた）。
- そろえないと 08 だけ違う（`compare_clean_unsorted.txt`：`所得税.特定親族特別控除の額` など 24 の値の、対象外の理由の文の並び）。
  **直す前の版どうしでも同じように違う**（`compare_rerun_before.txt`：同じ版・同じ入力の2回の実行）。並びはプロセスごとに変わる
  （直す前からの不具合。SCOPE §1 の「決定的」に反する）。原因の見込み：`evaluate._assemble` が値の由来を集めるときに、入力の変数の
  集合（`direct_of`：文字列の set）の順に段の値の理由をつなぐ。Python の文字列のハッシュはプロセスごとに変わる（`-I` は PYTHONHASHSEED を
  読まない）ので、集合の順が変わる。直し方の案：`sorted(direct_of)` の順にする（理由の文の並びが今のどれかの実行と変わるので、この作業では
  直していない。確かめていない）。

### 7.3 測った原因（scripts/results/IMPL7_core-perf）

- 時間のほとんどは、候補の組が上限（64）を超えた人のつながりの「点の比較」（`_affected_inputs`）：08 の前のプロファイルで 321 秒のうち 311 秒
  （`profile08_before.txt`）。08 では3つの単位の全部で上限を超え（分かれ目 15〜36。`units08_before.txt`）、点（3つ）× 分かれ目 × 候補ごとに
  段階評価の全部の段（8回）を計算し直す（converge 524 回、OpenFisca の計算と値の集め方をした回 952）。
  単位 (2026) では、段を計算し直した situation 253 のうち、どの回も使い回せたもの 158（18.4 秒）、どこかの回を計算し直したもの 95（42.0 秒、
  計算し直した回 405）（`slots08_y26_before.txt`）。分かれ目が所得を変える（不動産の事業的規模・事業と称するに至る程度・減価償却の選択など）と、
  第0回から第7回まで全部を計算し直す。
- 前のプロファイル（08）の内訳：値の集め方（`_assemble`）102 秒、situation の組み立て（`build_year`）62 秒、OpenFisca の計算 60 秒、
  段の関数（`apply_stage`）41 秒（うち `build_family` 18 秒）、回の使い回しの検索（`_RoundMemo.find`）22 秒。
- 調べた見込み：
  - 年度の評価で前年分の所得税を計算し直しているか：していない。年度 F は所得の年分 F−1 の単位に入り（`timepoints.plan_units`）、
    所得税 2025 と年度 2026、所得税 2026 と年度 2027 は同じ単位で1回だけ計算する。
  - 判定日の評価の重複：ある。判定日の単位 (2026, 2026-04-01) は、問いが求める値が 84 なのに、所得税 2026 の全部の出力と点の比較を
    単位 (2026) と別にもう一度行う（08：前 50.6 秒・後 36.3 秒。`units08_*.txt`）。単位をまたいで回の結果を使い回すのは、段に渡す値
    （StageValue.value_ids）と結果に出す値の集まりが単位ごとの値の ID（`v:2026-04-01@2026:…`）を持つので、今の形ではできない（§7.5）。
  - 候補の組合せのたびの再計算：上の点の比較がこれ。
  - OpenFisca の呼び出しを候補でまとめる：していない。トレース（値の依存）は変数ごとで人ごとでないので、組を1つの Simulation に並べると、
    式の分岐で組ごとの依存が混ざり、値の入力の集まり（どの分かれ目に関係するか）が変わりうる（式が値で分岐しないことは保証されていない）。
  - 結果の組み立て（`_merge` など）：1% 未満。

### 7.4 直したこと（packages/core/README.md §5.4）

- 段の関数の出力の使い回し（`situation.apply_stage(memo=…)`）：同じ回の節の値（同じオブジェクト）と、段の関数が読んだ判断・選択・端数の候補が
  同じなら、前の出力（同じオブジェクト）を使う（`build_family` などを繰り返さない）。
- build_inputs・グループの組み立ての使い回しを、段の値を読んだもの（kyuyo の事業専従者のみなし給与など）にも広げた（読んだ段の値が同じ
  オブジェクトのときだけ。`situation._reuse`・`YearContext.stage_log`）。
- `build_year`：モジュールごとの入力・モジュールの入力を合わせたもの・使わない判断の対象の検出・YearBuild を、材料が同じオブジェクトなら使い回す。
  situation の「人物一覧」に入力の値を書かない（使っていなかった）。
- 回の使い回しの検索：同じ YearBuild のオブジェクトは前に合った節を返す。値の並びを C の map で作る。Engine の入れ直し・`_diff_builds` は、
  同じオブジェクトなら比べない。入れ直しは同じでない入力の部分（モジュールごと・段の出力）だけを比べる。
- 上限を超えたつながりの点の比較の表のキーで、組にない根拠のない端数の候補を最初の候補にした（分かれ目を開いて評価し直すときに、前の点を使う）。
- 値の集め方：止める出力が「その回のトレースにある出力の全部」を含むときは全部の出力と同じキーにして、回をまたいで閉包を使い回す。
  段の値の ID の表を同じ回の段どうしで1回だけ作る。
- 単位 (2026) の点の比較の situation 253 のうち、どの回も使い回せたもの 158 は 18.4 → 4.7 秒。計算し直した回のあるもの 95 は 42.0 → 36.5 秒
  （`slots08_y26_*.txt`）。08 の単位ごと：19.5 → 14.9、59.7 → 40.4、50.6 → 36.3 秒（`units08_*.txt`）。

試して戻したもの：値の集め方（`_assemble`）の値ごとの使い回し（前の回・前の候補の組で集めた _Raw を、変わった入力がその値の入力の集まりに
入っていなければ使う）。当たりは 54%（08）だったが、使い回せるのは由来の少ない安い値で、段の出力に依存する高い値は段の出力が変わるたびに
外れ、確かめの手間の分だけ遅くなった（08：98 秒 → 120 秒。後者は当たり外れを数える道具〔作業用。リポジトリに入れない〕をつけた計測）。

### 7.5 分からなかったこと・残り

- 目標（家庭ごと数秒以内。08 を含む）には届かなかった。08 は 93.7 秒、02・03・07・11 は 15〜28 秒。
- 残りは、上限を超えたつながりの点の比較で、所得を変える分かれ目ごとに段階評価の8回を計算し直すこと（1回あたり OpenFisca の計算と
  値の由来の集め方で数十ミリ秒。08 の単位 (2026) だけで 405 回）。結果の値・判定・状態を変えずにここを数秒にするには、次のどれかが要る：
  1. 点の比較の方法を変える（点の数・比べ方は結果の「未確定」の範囲を決めるので、結果が変わりうる。ユーザーの判断が要る）。
  2. 段の回の値を、値の由来ごとに差分で集め直す仕組み（段の出力が変わったときに、その出力に依存する値だけを集め直す。今の値の由来は
     オブジェクトの同じさに頼る部分があり、作り直しが大きい）。
  3. 判定日の単位と所得の年分の単位で、回の結果を共有する（値の ID を単位によらない形で持ち、結果を作るときに単位の ID に直す）。
     08 で約 4 割。
- 直す前からの決定性の不具合（§7.2）は直していない。

## 8. 4回目（2026-11-12 夜）：値ごとに依存する分かれ目だけで組合せを全部評価する（近似をやめた）

- 変えたこと（ユーザーの方針：D21 R6 に忠実にする。packages/core/README.md §5「値ごとの候補の評価」・§5.4 の4回目）：
  - 上限を超えた人のつながりの「点の比べ方」（`_affected_inputs`）と人のつながりごとの直積（`_plan_parts`・`_new_links`）をやめ、値ごとに、
    計算の過程から決めた依存する分かれ目 D の直積の全部を評価する（`evaluate._resolve_dependencies`）。D の直積が上限（64）を超える値は計算せず
    未確定（D の分かれ目と「評価しなかった理由」。注入されていない注入点にも依存するなら、その分かれ目を前に並べる）。
  - 入力が依存する分かれ目：作り手（build_inputs・グループ・段の関数）が読んだ1か所。build_inputs とグループは読んだ分かれ目の直積の全部で呼んで
    出力ごとに正確に決める（`_producer_dependencies`。1024 組まで）。超えたら、書いた時点までに読んだ1か所（`registry.CAPTURE`）のうち
    `Slot.persons` にその人を含むもの。計算の後の検出が対象外にしうる変数は、検出が読んだ値の分かれ目にも依存する（`_check_target_candidates`）。
  - 所得税の年分の単位と同じ年の判定日の単位を1つの situation で評価する（`_shared_units`）。
  - 決定性の不具合（§7.2）を直した：値の由来を入力の変数の名前の順にたどる（`_assemble` の `direct_of`）。
  - 速さ：基準でない組は要る値だけ集める、集めた値の使い回し（`_assemble(reuse=…)`）、段の出力の uses の組をまとめて足す。
- 直す前の版：作業の始めに `packages/core/src/okura_core` を `.work/perf4/snap_src` に写したもの。写しの `rules/tax/refund.py` の
  `REFUND_RULE.detail` が文字列で、結果の JSON を作るところで止まった（`BasisEntry.detail` は dict。規則モジュールの側。並行の担当の作業中の版と
  思われる）ので、写しだけ `{"説明": …}` に直して前も後も同じ写しで測った（live の `rules/tax/refund.py` は直していない）。
  後の版：`PERF_SNAP=.work/perf4/snap_src PERF_FILES=evaluate.py,situation.py,registry.py,candidates.py,explain.py,result.py` で
  `scripts/IMPL5_core-perf_devtree.py` を実行した木。
- 足したスクリプト：
  - `scripts/IMPL8_core-perf_oracle.py`：直す前の版で候補の組合せの上限を引き上げて（1000）評価する（人のつながりの直積の全部。近似なし）。基準（オラクル）。
  - `scripts/IMPL8_core-perf_sample.py`：全部の分かれ目を分かれ目の ID ごとの決まった乱数で1つの候補に決め、直す前の版でその組だけを評価し、
    作り直した版の結果をその組に当てはめた値と比べる（D の外の分かれ目が値を変えれば、2つ以上が同時に変わるときでも食い違う）。
  - `scripts/IMPL8_core-perf_classify.py`：前と後で違う値を、オラクルと標本に当てて分ける。
- 再現：
  ```
  P=.work/venvs/core/Scripts/python.exe
  PERF_SNAP=.work/perf4/snap_src PERF_FILES=evaluate.py,situation.py,registry.py,candidates.py,explain.py,result.py $P -I -X utf8 scripts/IMPL5_core-perf_devtree.py .work/perf4/dev_src
  PERF_MODES=multi $P -I -X utf8 scripts/IMPL5_core-perf_snapshot.py .work/perf4/before_c .work/perf4/snap_src
  PERF_MODES=multi $P -I -X utf8 scripts/IMPL5_core-perf_snapshot.py .work/perf4/after_c .work/perf4/dev_src   # もう1回 after2_c へ（決定性）
  PERF_SORT_REASONS=1 PERF_SAME_SCHEMA=2 $P -I -X utf8 scripts/IMPL5_core-perf_compare.py .work/perf4/before_c .work/perf4/after_c
  PERF_SAME_SCHEMA=2 $P -I -X utf8 scripts/IMPL5_core-perf_compare.py .work/perf4/after_c .work/perf4/after2_c
  $P -I -X utf8 scripts/IMPL8_core-perf_oracle.py .work/perf4/oracle_c .work/perf4/snap_src 1000 01,02,07
  PERF_SAMPLE_DIR=.work/perf4/samples $P -I -X utf8 scripts/IMPL8_core-perf_sample.py .work/perf4/snap_src .work/perf4/after_c 8 scripts/results/IMPL8_core-perf/sample_check.txt
  $P -I -X utf8 scripts/IMPL8_core-perf_classify.py .work/perf4/before_c .work/perf4/after_c .work/perf4/oracle_c .work/perf4/samples scripts/results/IMPL8_core-perf/classify.txt
  ```
- 出力：`scripts/results/IMPL8_core-perf/`（`timing_clean_before.log`・`timing_clean_after.log`・`timing_clean_after2.log`：前・後・後をもう1回を続けて、
  自分のほかの計算と同時に走らせずに測った時間〔並行の担当の計算は同じ機械で動いていた〕、`compare.txt`：理由の文の並びをそろえた突き合わせ、
  `compare_unsorted.txt`：そろえない突き合わせ、`compare_rerun_after.txt`：後の版どうし、`oracle.log`、`sample_check.txt`、`classify.txt`、
  `states.txt`：値の区分の数）。結果の JSON（`.work/perf4/`）はリポジトリに入れない。

### 8.1 時間（秒。問い multi。timing_clean_*.log）

| 家庭 | 01 | 02 | 03 | 04 | 05 | 06 | 07 | 08 | 09 | 10 | 11 | 12 | 13 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 前 | 11.7 | 17.9 | 29.4 | 16.5 | 2.5 | 15.4 | 29.3 | 109.4 | 2.2 | 8.6 | 21.0 | 1.4 | 1.4 |
| 後 | 14.1 | 19.2 | 23.9 | 10.6 | 1.7 | 27.9 | 30.0 | 55.3 | 1.6 | 4.7 | 15.9 | 1.2 | 1.1 |
| 後（2回目） | 14.9 | 19.6 | 26.4 | 12.3 | 1.9 | 28.0 | 29.4 | 59.6 | 1.6 | 4.6 | 15.1 | 1.2 | 1.2 |

- 目標（家庭ごと数秒以内）には届かなかった。届いたのは 05・09・10・12・13。01・06 は前より遅い：前は上限を超えて基準の組1つだけを計算し、
  ほとんどの値を未確定にしていた（01：未確定〔上限〕625 → 6、06：761 → 69）。後はそれらを依存する分かれ目の全部の組で評価する（01：組 105）。
- 残りの時間は「評価した組 × 段の回」：組ごとに段階評価の回（8回）を通し、値の入力が変わった回だけ OpenFisca の計算と値の集め方をし直す
  （01 で組 105、1組 約 0.14 秒。08 の単位 (2026) で組 212）。値の集め方（`_assemble`）・OpenFisca の計算・situation の組み立てがほぼ同じ割合。

### 8.2 決定性

- 後の版どうし（同じ入力の2回の実行）は、理由の文の並びをそろえずに 13 家庭とも同じ（`compare_rerun_after.txt`）。§7.2 の不具合は直った。

### 8.3 突き合わせ（compare.txt・states.txt・classify.txt）

- 同じ：05・09・10・11・12・13（前も後も上限にかからない家庭は、由来の項目まで同じ）。違う：01・02・03・04・06・07・08（全部、前に上限を超えた家庭）。
- 値の区分（確定／未確定〔上限〕。states.txt）：01 303／625 → 943／6、02 0／942 → 993／33、03 374／182 → 312／245、04 673／2 → 674／0、
  06 0／761 → 773／69、07 0／929 → 719／329、08 180／1084 → 981／394。
- 違う値の判定（classify.txt。値・状態・未確定・対象外・evaluated のどれかが違う値）：
  1. オラクルと同じで、前がオラクルと違う（前の近似の誤り）：809（01・02・07 の単位 (2025)）。前は上限を超えて未確定（関係する分かれ目ありと判定）か、
     関係なしとして基準の組の値で断定していた。例：01 の `v:2025:p-a:所得税.ひとり親に当たるか`（前は未確定〔上限〕、オラクルと後は候補の全部で確定）。
  2. オラクルと値・状態・未確定・対象外が同じで、evaluated だけ違う：1328。前（とオラクル）はグループの組み方を変える分かれ目を全部の値の
     evaluated に出していた。後は、その値の人のインスタンスが変わるときだけ出す（値は変わらない）。
  3. オラクルと違う：131（01 6・02 33・07 92）。全部「オラクルは未確定（注入：候補のない注入点）、後は未確定（上限）」で値（なし）は同じ。後は依存する
     分かれ目の直積が 64 を超えるので評価せず、注入の分かれ目と依存する分かれ目を出す（前とオラクルは注入の分かれ目だけを出していた：
     評価しなかった分かれ目が「何を入力すれば決まるか」に出ないのを直した）。
  4. 前は上限で評価しなかった・後は評価した：1749。標本の突き合わせ（下）で確かめた。
  5. 後は上限（未確定）：標本で値が分かれる 223（未確定は正しい）、標本では分かれない 519（8 標本では分かれなかった。依存する分かれ目の数で上限を
     超えたので評価していない：安全側）。
  6. 前は確定、後は上限：62（03 だけ。標本の値は前の確定と合う）。前は単位 (2025) の直積 10368 で上限を超え、点の比較で関係なしとして基準の組の値で
     断定していた。後は依存する分かれ目（計算の後の検出が読む値の分かれ目を含む）の直積が 64 を超える。標本 8 では前の値と違う組は見つからなかった
     （前の断定が誤りかは分からない）。前の断定は直積の全部を確かめていないので、R6 では未確定が正しい。
  7. そのほか 8（08）：前も後も対象外で、後の理由の文が多い（前は上限を超えて基準の組の理由だけ、後は依存する組の全部の理由）。
  - ほかに、由来の項目（facts・depends_on・basis）だけ違う値が 01 57・02 67・03 23・04 61・06 59・07 73・08 6（依存する組の全部の和にした）。
    04 は前も後も上限にかかる値が 2 つだけで、それ以外の違いは由来だけ。01 の判定日の単位の値が 24 増えた（`v:2026-04-01@2026:…`）：判定日の単位を年分の
    単位と一緒に評価すると、段が読んだ所得税の値の ID を、依存先に置き換えずにそのまま持つ（値は年分の単位と同じ）。
- 標本の突き合わせ（sample_check.txt）：13 家庭 × 8 標本で、作り直した版が評価した値 59,944 を比べ、食い違い 0。
  作業の途中の版では食い違いが出た：(a) 07 で、計算の後の検出（personal_deductions の寡婦・ひとり親の住民票の検出）が対象外を出す組を評価した組の中で
  一度も通らず、その検出が読む値の分かれ目を依存に入れていなかった（検出が対象外にしうる変数を、検出のコードに書いた自分のモジュールの変数に広げて
  直した）。(b) 上限を超えた値の対象外を比べていた（突き合わせの道具の誤り。上限を超えた値は比べない）。

### 8.4 分からなかったこと・残り

- 目標の時間に届かない（§8.1）。速くするには、組ごとの段の回の計算を減らす仕組み（候補の組を1つの Simulation に並べる、回の値を差分で集め直す）が要る。
- 標本 8 では「後は上限・標本では分かれない」519 と「前は確定・後は上限」62 が本当に分かれないかは決まらない（直積の全部は大きすぎて評価していない）。
- 依存の決め方の約束（packages/core/README.md §9）：build_inputs の読んだ分かれ目の直積が 1024 を超えるときの `DecisionSlot.persons` の宣言、
  計算の後の検出がコードに名前を書いていない変数を対象外にするとき（評価した組で一度出すまで依存に入らない）。
- オラクルは 01・02 と 07 の単位 (2025) だけ（ほかは直積が大きく、直す前の版では時間と記憶域が足りない）。

## 9. 5回目（2026-11-12 深夜）：候補の組のプロセスの並列（parallel.py）

- 変えたこと（packages/core/README.md §5.4 の5回目）：
  - 候補の組の計算を標準ライブラリの `concurrent.futures`（spawn のプロセス。ワーカーごとに OpenFisca の体系を1回だけ組み立てる）で分ける。
    並列の数は問いの `workers`（既定は CPU の数、1 は直列）。最初から開いている判断・選択の分かれ目が2つ以上の評価の単位だけを並列にする（`parallel.MIN_OPEN_SLOTS`）。
  - 並列の単位では、全部のワーカーが単位を組み立て直して基準の組を計算し（使い回しの表を温める）、最初のワーカーが基準の組の分かれ目の依存と
    作り手の依存の表を返す。親は計算せず、依存する分かれ目を決めて組を割り振り、値をまとめる。評価の単位（所得税 2025 と、2026・判定日）はスレッドで並べる。
  - 作り手の依存の表（`exact_cache`）を段の値の中身の等しさで引く（ほかのワーカーに渡すため）。`_diff_bits` は入力の部分を（型, 値）の表でまとめて比べる。
  - 並べ方の段階：(1) 親が基準の組を計算し、組だけをワーカーで（01：14.4 秒、後で 9.6 秒）、(2) 親の入力の番号と作り手の依存の表をワーカーに渡す（9.6 秒）、
    (3) 基準の組もワーカーで、単位をスレッドで並べる（9.8 秒：全部のワーカーが両方の単位の基準の組と依存〔作り手の直積の全部の呼び出し〕を計算して詰まった）、
    (4) 依存は最初のワーカーだけが求め、その表をほかのワーカーに渡す（6.2 秒。今の形）。数は `.work/perf5/tools/` の作業用の計測（リポジトリに入れない）。
- 直す前の版：作業の始めに `packages/core/src/okura_core` を `.work/perf5/snap_src` に写したもの（rules/tax/refund.py の detail は、写す前に本物を直した：§9.4）。
  後の版：`PERF_SNAP=.work/perf5/snap_src PERF_FILES=evaluate.py,query.py,parallel.py` で `scripts/IMPL5_core-perf_devtree.py` を実行した木
  （並行の担当の規則モジュールの書き換えと、同じ作業で足した juminzei の読みの候補〔JM-41〕は入らない：前後で同じ規則）。
- 足したスクリプト：
  - `scripts/IMPL10_core-perf_workers.py`：問い multi を並列の数ごとに全部の家庭で評価し、時間と、並列の数どうしの結果の JSON の突き合わせを出す。
  - `scripts/IMPL10_core-perf_timeline.py`：並列の評価の、単位ごとの基準の組・組の割り振りの時刻。
  - `scripts/IMPL10_core-perf_profile-combos.py`：直列で、基準でない組の計算だけの cProfile。
  - `scripts/IMPL10_core-perf_final-dupes.py`：直列で、組の最後の situation が前の組と同じになる数。
- 再現：
  ```
  P=.work/venvs/core/Scripts/python.exe
  PERF_SNAP=.work/perf5/snap_src PERF_FILES=evaluate.py,query.py,parallel.py $P -I -X utf8 scripts/IMPL5_core-perf_devtree.py .work/perf5/dev_src
  PERF_MODES=multi $P -I -X utf8 scripts/IMPL5_core-perf_snapshot.py .work/perf5/before_c .work/perf5/snap_src
  $P -I -X utf8 scripts/IMPL10_core-perf_workers.py .work/perf5/after .work/perf5/dev_src 16,1
  PERF_SAME_SCHEMA=2 $P -I -X utf8 scripts/IMPL5_core-perf_compare.py .work/perf5/before_c .work/perf5/after/w16
  PERF_MODES=one,y25,fy,dd,full $P -I -X utf8 scripts/IMPL5_core-perf_snapshot.py .work/perf5/before_q .work/perf5/snap_src   # 後も同じ（dev_src。workers は既定）
  PERF_SAME_SCHEMA=2 $P -I -X utf8 scripts/IMPL5_core-perf_compare.py .work/perf5/before_q .work/perf5/after_q
  $P -I -X utf8 scripts/IMPL10_core-perf_timeline.py 01,02,08 1
  $P -I -X utf8 scripts/IMPL10_core-perf_final-dupes.py 01,02,08
  $P -I -X utf8 scripts/IMPL10_core-perf_profile-combos.py 01
  ```
- 出力：`scripts/results/IMPL10_core-perf/`（`timing_clean_before.log`：前、`timing_clean_after.log`：後の workers 16 と 1 と、その突き合わせ。前と後は続けて、
  自分のほかの計算と同時に走らせずに測った〔並行の担当の計算は同じ機械で動いていた〕。`compare.txt`・`compare_bytes_before_after_w16.txt`：前と後〔workers 16〕の
  突き合わせ、`other_queries_*.log`・`compare_other_queries.txt`：ほかの問い、`timeline.txt`・`final_dupes.txt`・`profile_combos01.txt`）。
  結果の JSON（`.work/perf5/`）はリポジトリに入れない。機械：Windows 11、8 コア 16 スレッド（論理プロセッサ 16）、Python 3.11.9、openfisca-core 46.0.1。

### 9.1 時間（秒。問い multi。timing_clean_*.log）

| 家庭 | 01 | 02 | 03 | 04 | 05 | 06 | 07 | 08 | 09 | 10 | 11 | 12 | 13 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 前 | 11.4 | 16.7 | 21.4 | 9.2 | 1.4 | 24.0 | 25.2 | 46.3 | 1.4 | 4.2 | 12.7 | 1.2 | 0.9 |
| 後（workers 16） | 6.2 | 9.9 | 6.3 | 6.2 | 1.9 | 12.7 | 11.0 | 19.4 | 1.5 | 2.6 | 4.2 | 1.3 | 1.2 |
| 後（workers 1） | 14.1 | 19.7 | 25.0 | 11.0 | 1.8 | 28.9 | 29.7 | 52.9 | 1.6 | 4.7 | 14.4 | 1.5 | 1.2 |
| 後（workers 16、2回目） | 7.4 | 10.1 | 6.4 | 6.0 | 1.5 | 12.5 | 11.2 | 18.8 | 1.8 | 2.6 | 3.9 | 1.2 | 1.2 |

- ワーカーの起動（プロセスで1回）：最初の評価（暖機の 01）は 15.9 秒（ワーカー 16 の import と体系の組み立て〔1つ 5〜6 秒〕と、使い回しの表が空の計算）。
  コマンド（`okura_core.cli`）は評価ごとにプロセスを作るので、並列の単位がある家庭ではこの分が毎回かかる（分かれ目の少ない家庭はワーカーを起動しない）。
- 目標（家庭ごと数秒以内）に届いたのは 11（4.2）・10・05・09・12・13 で、03・04・01（6〜7）は近い。02（9.9）・06（12.7）・07（11.0）・08（19.4）は
  届かなかった（§9.3）。
- workers 1 は前より 1〜2 割遅く出た（前と後は続けて測ったが、並行の担当の計算が同じ機械で動いていた。直す前の版の計測の直後の作業用の計測では、
  後の workers 1 は前と同じだった〔01：11.5 秒、08：46.3 秒〕。並列の仕組みは直列では働かない。作り手の依存の表を等しさで引く比べ方と、
  `_diff_bits` のまとめた比べ方は直列でも働く）。workers 8 と 16 は同じくらいだった（途中の版の作業用の計測で 02：9.4・10.1 秒。
  物理コアが 8）。

### 9.2 突き合わせ

- 問い multi：前（直列の元の版）と後（workers 16）の結果の JSON は 13 家庭ともバイト列まで同じ（`compare_bytes_before_after_w16.txt`・`compare.txt`：同じ 13・違う 0）。
  後の workers 16 と workers 1 も 13 家庭ともバイト列まで同じ（`timing_clean_after.log` の最後の行）。理由の文の並びをそろえずに同じ（決定的）。
- 並列の実行どうし（workers 16 の1回目と2回目）も 13 家庭ともバイト列まで同じ。
- ほかの問い（one・y25・fy・dd・full。full は提出日と国民年金の年度を含む。後は workers の既定〔16〕）：13 家庭 × 5 = 65 とも同じ
  （`compare_other_queries.txt`：同じ 65・違う 0。`other_queries_*.log` に時間）。
- 結果の値・判定・状態は1つも変わっていない。
- 作業の途中の版では、ほかの問いの 06 full で1つの値（`v:2025:p-w:所得税.還付を受けるための申告書を提出するか`）が、並列のときだけ、実行ごとに
  前と違った（前：確定の偽、並列：依存する分かれ目に国保の注入の分かれ目が入り上限を超えて未確定）。原因：ワーカーは前の組で集めた値（`_Raw`）を使い回すので、
  1つのまとまりの結果の複数の組が同じ `_Raw` のオブジェクトを持ち（pickle は共有を保つ）、親が入力のビットを組ごとに付け替えて、同じオブジェクトを2回
  付け替えていた（別の入力〔国保の入力〕を指した）。オブジェクトごとに1回だけ付け替えるように直した（`parallel.Dispatcher._convert`。
  ユニットテスト `test_parallel.TestRemap.test_shared_raw_objects_are_converted_once`）。上の突き合わせは直した後の版で測り直したもの。

### 9.3 測った原因と残り

- 時間の内訳（`timeline.txt`）：単位ごとに「基準の組（最初のワーカー：段階評価の全部の回と、分かれ目の依存〔作り手を読んだ分かれ目の直積の全部で呼ぶ〕）」→
  「依存する分かれ目を決める（親）」→「組の全部（ほとんどの家庭で1回のまとまり。01：39 組と 67 組、08：26 組と 145 組）をワーカーで」→「まとめ（親）」。
  2つの単位は並べて進む。01（2回目）：基準の組 2.3 秒・3.6 秒（単位 2025・2026。並べて進む）、組の計算 1.7 秒（39 組）・2.5 秒（67 組）、合計 6.7 秒。基準の組（段階評価と作り手の直積の全部の呼び出し）が半分を占める。08：合計 18.4〜19.2 秒。
- 組1つの計算（直列で温まった表のとき。`profile_combos01.txt`：01 の 106 組で 18.7 秒、1組 約 0.18 秒）：最後の値の集め方（`_assemble`）約 52 ミリ秒、
  最後の OpenFisca の計算 約 25 ミリ秒、組で入力の変わった段の回の計算と値の集め方（106 組で 88 回）約 57 ミリ秒、段の回の組み立て（8 回 × 約 5 ミリ秒）。
  ワーカーでは、単位ごとに最初の組で使い回しの表が空（基準の組を計算して温める）。物理コアが 8 なので、組の多い家庭（08：171 組）は 1組 0.2〜0.4 秒 × 組 ÷ 8 が残る。
- (b) 組で変わらない段の使い回し：前から段の回の使い回し（`_RoundMemo`：段に渡す値の依存した入力が同じ回は計算しない）と段の関数の出力の使い回し
  （`apply_stage(memo=…)`）があり、01 では 106 組 × 8 回のうち OpenFisca の計算と値の集め方をした回は 88。さらに、組の最後の situation が前の組と
  入力の値・対象外・グループまで同じ組が 08 で 175 のうち 76（オブジェクトとして同じものは 9。01：108 のうち 16〔同じオブジェクト 0〕、02：133 のうち 41
  〔同じオブジェクト 32〕。`final_dupes.txt`）。これを使い回すには、入力の由来
  （段の値の uses など）を含めた同じさの比べ方と、段の値の確かめ（最後の計算と同じか）を残す方法が要り、未着手。
- (c) 依存が落ち着いたら段の回を打ち切る：段の回は段の順序（読む変数の依存）で決まる別々の段で、回を飛ばすとその回の段が実行されない。
  組で変わらない回は (b) の使い回しで計算していない。それ以上の打ち切りは、上の「最後の situation の使い回し」と同じ仕組みが要る（未着手）。
- 後に残る目標との差の大きいもの：08（18.8 秒）・06（11.7）・07（10.0）・02（9.3）。組1つの計算（値の集め方）を速くするか、上の使い回しが要る。

### 9.4 同じ作業で直した不具合

- `rules/tax/refund.py` の `REFUND_RULE.detail` が文字列で、結果の JSON を作るところ（`BasisEntry.to_dict` の `dict(detail)`）で止まった（§8 で前の担当が写しでだけ直した）。
  本物を `{"note": …}` に直した。同じ誤りがほかにないことを、ソースの構文木で `BasisEntry(...)`・`replace(..., detail=...)` の `detail`（dict か None）・`references`・`flags`
  （タプル）の型を見る静的なユニットテスト（`packages/core/tests/test_basis_entry_types.py`。モジュールの最上位の項目は JSON にできることも確かめる）で確かめた：ほかに 0。
