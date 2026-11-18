# impl-research4：国税庁・財務省・総務省・共済組合・厚生労働省・日本年金機構の資料の取得と文字の取り出し（実測）

- 種類：実測。実行日：2026-11-12。
- スクリプト：
  - `scripts/IMPL4_web_fetch.py`（`scripts/IMPL3_web_fetch.py` を写し、SETS・NAME・説明だけを変えた。robots.txt をホストごとに確かめる）
  - `scripts/IMPL4_web_pdftext.py`（`scripts/IMPL3_pdftext.py` を写し、出力先を変え、読めない PDF で止まらないようにした）
  - `scripts/IMPL4_web_lines.py`（`IMPL4_web_pdftext.py` の文字と位置を、横書き・縦書きの行に並べ直す）
- 出力：`scripts/results/IMPL4_web_fetch/<set>/`、`scripts/results/IMPL4_web_pdftext/`、`scripts/results/IMPL4_web_lines/`。
- ダウンロード（信頼できないデータ。新しい空のディレクトリ。中では何も実行していない）：
  `.work/downloads/20261112-014506_IMPL4_web_fetch_nta/`、`…-014518_IMPL4_web_fetch_kifu/`、`…-014535_IMPL4_web_fetch_hifuyosha/`、`…-014600_IMPL4_web_fetch_kokunen/`、`…-014704_IMPL4_web_fetch_nta2/`、`…-020243_IMPL4_web_fetch_verify/`（反証の確認。`docs/measurements/20261112_impl-research4_verification.md`）。

## 1. 再現の手順

```
P=C:\Users\user\.pyenv\pyenv-win\versions\3.11.9\python.exe
%P% -I -X utf8 scripts/IMPL4_web_fetch.py nta kifu hifuyosha kokunen
%P% -I -X utf8 scripts/IMPL4_web_fetch.py nta2
%P% -I -X utf8 scripts/IMPL4_web_fetch.py verify
%P% -I -X utf8 scripts/IMPL4_web_pdftext.py <名前>=<.work/downloads/…/名前.pdf> …   （kifu・hifuyosha・kokunen の PDF の全部）
%P% -I -X utf8 scripts/IMPL4_web_lines.py h hiroshima_130moushitate hiroshima_130moushitate_rei ehime_20250701 okayama_fuyo mhlw_001678029 soumu_se_080331_08152_a
%P% -I -X utf8 scripts/IMPL4_web_lines.py v soumu_001096071
```

## 2. 取得の結果（`scripts/results/IMPL4_web_fetch/<set>/fetch_log_<ts>.json`）

| set | id | 状態 | Last-Modified | SHA-256（先頭16桁） |
|---|---|---|---|---|
| nta | kihon_13_01（所基通 法63・64関係） | 200 | 2024-01-18 | 329de50863233404 |
| nta | kihon_13_index・kihon_06_index | 200（「指定されたページを表示できませんでした」） | — | 700138cae1f347c2 |
| nta | shitsugi_02_27（質疑応答：未収家賃） | 200 | 2025-12-03 | 26eb83cc9663b82e |
| nta | kobetsu_770822_01（個別通達：未払配当金の辞退） | 200 | 2024-01-18 | 7876eaf2edd4c358 |
| nta | ta_1400（給与所得） | 200 | 2026-09-09 | 71c15579cc529b77 |
| nta2 | kihon_09_02（所基通 法51関係〔貸倒損失〕） | 200 | 2026-10-02 | b26e20744c0f2034 |
| nta2 | kihon_09_03（〔返品〕。関係なし） | 200 | 2024-01-18 | 29e597355fff8f57 |
| kifu | mof_ko_19650430_0154 | 200 | 2026-06-05 | 20d113f07c502595 |
| kifu | mof_ko_20261013_277 | 200 | 2026-10-14 | 5198ebd77eec4f7d |
| kifu | mof_ko_20240930_242 | 200 | 2024-10-01 | e8ed52346fa93945 |
| kifu | soumu_001096071（総務省告示第383号） | 200 | 2026-10-13 | 3dd6952cedace60e |
| kifu | soumu_000698503・000948010・000614893（ふるさと納税の告示。関係なし） | 200 | — | 433c83afbc705b5c・5f0f4b2982be2dcf・c3fb7dc02b57e11e |
| kifu | soumu_se_080331_08152_a（平成20年の政令改正の概要） | 200 | 2009-02-25 | 5d3e87fb67378c29 |
| hifuyosha | fukuoka_kijun | 200 | 2026-10-20 | 169b47abbe554618 |
| hifuyosha | hiroshima_130moushitate | 200 | 2023-08-24 | 6f8141b6f64dba7f |
| hifuyosha | hiroshima_130moushitate_rei | 200 | 2022-08-29 | 1bc996430be34c63 |
| hifuyosha | nara_2018_01_18 | **取得せず（robots.txt で許されていない）** | — | — |
| hifuyosha | ehime_20250701 | 200 | 2025-07-01 | 1c2b60530e4d2fce |
| hifuyosha | tokyo_fuyou | **404** | — | f074a7e9c64d1296 |
| hifuyosha | okayama_fuyo | 200 | 2019-02-07 | 3bcab2d413360edd |
| hifuyosha | mhlw_001678029 | 200 | 2026-04-01 | dc76229c5e2a60a8 |
| kokunen | nenkin_gakusei_pdf（学生納付特例対象校一覧 PDF） | 200 | 2026-10-15 | 31dba7288f43d2db |
| kokunen | nenkin_gakutokutaisyouko（ページ） | 200 | 2026-11-02 | 32c5d2983da9d9c2 |
| verify | kashiwa_zyutoku（柏市の住所地特例の案内。反証の確認） | 200 | 2026-06-10 | 6c0df1e4755e9974 |
| verify | mhlw_T251107S0010 | **404** | — | — |

## 3. PDF の文字の取り出し（`scripts/results/IMPL4_web_pdftext/summary.json`）

| 名前 | 結果 |
|---|---|
| soumu_001096071 | 1頁・431行（縦書き。`IMPL4_web_lines.py v` で読める文にした） |
| soumu_se_080331_08152_a | 1頁・50行 |
| hiroshima_130moushitate | 1頁・73行（読める） |
| hiroshima_130moushitate_rei | 1頁・63行（一部の文字化け・行の混ざり） |
| ehime_20250701 | 3頁・296行（一部の字が化ける：「場合」→「場�」など） |
| okayama_fuyo | 5頁・334行 |
| mhlw_001678029 | 5頁・1522行 |
| mof_ko_19650430_0154・mof_ko_20240930_242・mof_ko_20261013_277 | **暗号化 AESV2（V4,R4）で鍵の検査に失敗（key_ok=False）、0行**。このスクリプトでは読めなかった |
| tokyo_fuyou | 0頁（404 の HTML） |
| nenkin_gakusei_pdf | **エラー**（`ValueError('chr() arg not in range(0x110000)')`、ToUnicode の範囲の解析） |

- 財務省の告示 PDF の本文は、Claude Code の Read 機能（PDF を読む機能）で読んだ：
  `mof_ko_20261013_277` は `.work/downloads/20261112-014518_IMPL4_web_fetch_kifu/mof_ko_20261013_277.pdf` を直接、
  `mof_ko_19650430_0154` は WebFetch が保存した同じ URL の写し（162KB）を読んだ。この手順はスクリプトでは再現できない（再現するには Read 機能で同じ PDF を開く）。
  読んだ本文は `docs/public-sources/20261112_impl-research4_juminzei-kifu-laws-and-kokuji.md` §2.1・§2.2。
- HTML のテキスト（`scripts/results/IMPL4_web_fetch/<set>/<id>.txt`）は、そのまま読める。所基通 64-1〜64-3の4 は `nta/kihon_13_01.txt` の 24〜50 行、51-11〜51-16 は `nta2/kihon_09_02.txt` の 20〜45 行。

## 4. 検索の記録（一次情報ではない。URL を見つけるために使った）

WebSearch（2026-11-12）で使った語：「所得税基本通達 64-1 回収不能 収入金額 給与」「国税庁 質疑応答 未払給与 支払を受けられなくなった 所得税法第64条 更正の請求」
「"今後1年間の収入が" "以上とならないことが明らか" 被扶養者 3か月 共済組合」「共同募金会 指定寄附金 告示 昭和40年大蔵省告示第154号」
「総務省告示 地方税法施行令第七条の十七第一号 共同募金会」「地方税法施行令第七条の十七第二号 総務大臣が定める…」「日本年金機構 学生納付特例 対象となる学校…」。
使用人の未払給与に法64①を当てる国税庁の質疑応答、地方税法施行令第7条の17第2号・第3号の告示は、これらの検索では見つからなかった。
