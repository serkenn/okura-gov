---
name: add-injection-point
description: okura-gov の判定コアに、市町村・保険者ごとに変わる値（条例の率・額、級地、保険者の運用など）の注入点を足す・注入点の欄や候補を足すときに使う。「注入点を足す」「市町村ごとに違う」「保険者の運用」「条例で決まる」「注入データ」「injection_points」など。データそのものはリポジトリに置かない（利用側が出典つきで注入する：D17・D19）。
---

# 注入点を足す（okura-gov。D17・D19・D21 R6）

最初に `AGENTS.md` を読む。仕組みは `packages/core/README.md` §3（`injected`）・§5.3、注入点の一覧は `packages/core/src/okura_core/injection_points.py`、型は `injection.py`。

## 0. 注入点にしてよいか

- **市町村・保険者ごとに変わる値だけ**を注入点にする（条例の率・額、超過課税、均等割の上乗せ、級地、国保の賦課の方式、保険者の認定の運用など）。
- 法令が全国一律に決める値（所得割の非課税の額、森林環境税の額、政令の賦課限度額など）は注入点にせず、規則モジュールのパラメータにする（add-rule）。
- 「条例・保険者に委ねる」ことを示す一次情報（法令の条・通知）が `docs/public-sources` にあること。なければ primary-source スキルで先に記録する。
- `injection_points.py` は共有のファイル。**並行の担当と調整してから触る。**

## 1. 触るファイル

| ファイル | 書くこと |
|---|---|
| `docs/public-sources/…` | 委任の根拠の条文、候補の型の元になった資料（保険者・組合の案内、条例の例）と取得日 |
| `packages/core/src/okura_core/injection_points.py` | `InjectionPoint` の定義と、ファイルの末尾の `POINTS` の並び（`for p in (…)`）への1行 |
| `rules/<名前>/concepts.yaml` | 使う概念の `注入データ` に注入点の名前 |
| `rules/<名前>/__init__.py` ほか | `RuleModule.injections=(InjectionSpec(注入点, slots),)`、`build_inputs` で `ctx.injection(注入点, key)` |
| `rules/<名前>/README.md`、`packages/core/README.md` §5.3 | 注入点の説明と数 |
| `packages/core/tests/test_<名前>*.py` | ユニットテスト |

## 2. 手順

1. **形を決める**（`InjectionPoint`。既存の `住民税.級地` などに倣う）：
   - `name`：`<制度>.<名前>`（制度は 住民税・国保・健保 など）。`institution`・`title`。
   - `issuer_kinds`：`municipality`・`prefecture`・`insurer` のどれか（道府県の団体コードは上2桁＋000＋検査数字の形）。
   - `fields`：`DataField(name, kind, title, required, values, fields)`。数の欄は整数（文字列を受け付けない）。列挙は `values`。
   - `timing`：どの時点の値か（例：前年の12月31日の級地区分）と、その根拠の条。
   - `references`：docs のファイル#節。
2. **候補を決める**（未注入のときの範囲の評価。D19・D21 R6）：
   - 取りうる範囲が有限で法令が決めるもの（級地の1〜3、料か税か、軽減の割合）は、その全部を `NamedCandidate` にする。
   - 保険者の運用は、**調査で集めた運用の型だけ**を候補にし、型の名前に資料の略称を書く。
   - 率・額のように範囲が有限でないものは **候補を持たない**（既定値で計算しない）。未注入なら依存する値は「未確定」（決める手段＝注入）になる。
   - 候補は2つ以上か、持たないか（`test_injection.py` が確かめる）。`candidates_note` に理由を書く。
3. **概念辞書**：使う概念の `注入データ` に注入点の名前を書く。注入点の制度は、概念の制度か「依存してよい制度」。
4. **モジュールで使う**（`packages/core/README.md` §5.3・§10）：
   - `InjectionSpec(注入点, slots)`。`slots(ctx)` が `InjectionSlot(key, 団体の種類, 団体のコード, on, …)` を返す（団体は各人の1月1日の住所の市町村、加入している保険者など。key の既定の形は `injection_key(…)`）。
   - 値は `ctx.injection(注入点, key)` が返す `Decided`：注入されていれば `value`（中身の `data`）・`record_ids`・`basis`（出典）。未注入で候補があれば分かれ目として候補の全部で評価される。未注入で候補がなければ `value` は `None`・`missing` があるので、仮の値を書いて `out.set(…, missing=d.missing)` する。
   - 由来（`record_ids`・`basis`）を入力に入れる。
5. **注入データの約束**（利用側が渡すもの）：`{id, point, issuer{kind, code}, applies{from_on, to_on?}, source{url, retrieved_on, source_kind, title?, sha256?}, data{}}`。出典と適用期間のないものは受け付けない（SCOPE §8）。同じ注入点・団体で適用期間が重なれば誤り。
6. **データそのものはリポジトリに置かない**（SCOPE §4）。テスト・例の団体コードは実在しない `99` で始まるコードを使う。
7. **README を直す**：モジュールの README と `packages/core/README.md` §5.3 の注入点の数・一覧（日付つき）。

## 3. ユニットテスト（D24）

`build_inputs` か式を直接呼び、次を確かめる（evaluate を通さない）：

- 注入したとき：値と根拠（注入データの ID・出典）が入力に入る。
- 未注入で候補があるとき：候補ごとの値。候補で結論が同じなら断定、違えば分かれ目になること。
- 未注入で候補がないとき：`missing` が付き、依存する値が未確定になる材料が出ること。

## 4. 確かめ方

```
.work/venvs/core/Scripts/python.exe -I -X utf8 -m pytest -q -p no:cacheprovider packages/core/tests/test_injection.py packages/core/tests/test_<名前>.py
.work/venvs/core/Scripts/python.exe -I -X utf8 -m pytest -q -p no:cacheprovider packages/core/tests/test_architecture.py packages/core/tests/test_architecture_modules.py packages/core/tests/test_architecture_imports.py
.work/venvs/core/Scripts/python.exe -I -X utf8 -m pytest -q -p no:cacheprovider packages/core/tests/test_out_of_scope_inventory.py
```

`test_injection.py` は、候補のスキーマ・出典の実在・候補の数・概念辞書の `注入データ`・使う注入点を対象外にしないこと（使う注入点は登録から求める）を確かめる。最後に core の全部のテスト（バックグラウンドで）。
