# コンテナで動かす（AlmaLinux 9）

okura-gov（判定コア・記録層のコマンド、監視、テスト）を AlmaLinux 9 のコンテナで動かす手順。podman でも docker でも同じファイルを使う。

| ファイル | 中身 |
|---|---|
| `Containerfile` | イメージの作り方（リポジトリの根） |
| `.dockerignore` | ビルドに渡さないもの（`.work/`・`.git/`） |
| `.gitattributes` | 表のデータ（CSV）の改行を CRLF に固定する（§3） |
| `ops/container/run.py` | コンテナの入口。パッケージごとの仮想環境の Python を `-I -X utf8` で起動し直すだけ（標準ライブラリだけ） |

`packages/` の中は変えていない。仮想環境の作り方は AGENTS.md「仮想環境の作り方」のとおり
（core と records を分ける・wheel だけ・`okura_dev.pth`・monitor は標準ライブラリだけ）で、パスが `Scripts/python.exe` でなく `bin/python` になるだけ。

## 1. 作る

```
podman build -t okura-gov .          # docker build -f Containerfile -t okura-gov . でも同じ
```

- 置き場所は `/opt/okura-gov`。仮想環境は `/opt/okura-gov/.work/venvs/{core,records,monitor}`。
- 手元の作業のディレクトリ（`.work/`）はイメージに入らない。リポジトリのほかのファイルは、テストが出典の実在を確かめるので全部入る
  （`docs/`・`scripts/results/` を含む。イメージは大きい）。
- 動かすときは root でないユーザー（UID 10001）。

## 2. 使う

| コマンド | 中で動くもの |
|---|---|
| `core` | `python -I -X utf8 -m okura_core.cli`（標準入力の JSON → 標準出力の JSON。`packages/core/README.md`） |
| `records <引数>…` | `python -I -X utf8 -m okura_records.cli <引数>…`（`build-ir`・`transactions`・`append`。`packages/records/README.md`） |
| `monitor <引数>…` | `python -I -X utf8 -m okura_monitor <引数>…`（`targets`・`run`。`packages/monitor/README.md`） |
| `test [名前]…` | AGENTS.md「テストの動かし方」の表のコマンド（`core`・`ir`・`records`・`monitor`。名前がなければ全部） |
| `python <名前> <引数>…` | 仮想環境（`core`・`records`・`monitor`）の Python を `-I -X utf8` で起動する |

```
podman run --rm -i okura-gov core < input.json > result.json
podman run --rm -v ./ledger:/ledger:ro,Z okura-gov records build-ir --ledger /ledger/main.beancount …
podman run --rm okura-gov monitor targets
podman run --rm okura-gov test
podman run --rm okura-gov test records ir
```

- **家族のデータはイメージに入れない。** 標準入力か、読み取り専用のマウントで渡す。台帳に追記する `records append` のときだけ、書けるマウントにする
  （ホストのディレクトリは UID 10001 が書けること。rootless の podman なら `podman unshare chown 10001:10001 <ディレクトリ>`）。
- 判定コアと記録層はネットワークに出ない。`core`・`records`・`test` は `--network none` を付けて動かせる。
- ネットワークに出るのは `monitor run` だけ（SCOPE §3）。状態と出力は `/var/lib/okura-gov`（ボリューム）に置く：

```
podman volume create okura-gov-monitor
podman run --rm -v okura-gov-monitor:/var/lib/okura-gov okura-gov \
  monitor run --state-dir /var/lib/okura-gov/state --out /var/lib/okura-gov/out
```

  `gh` はイメージに入れていない（`--post-github` は使えない。issue を作る監視は GitHub Actions の `law-monitor.yml` のまま）。

## 3. 改行（表のデータの SHA-256）

判定コアが読む表のデータ（`rules/kyuyo/data/*.csv`・`rules/tax/data/*.csv`）は、`SOURCES.json` に記録した SHA-256 と読むたびに照合される。
記録してある値は、改行が CRLF の中身（Windows の作業ツリー）のもの。Linux・macOS でそのまま取り出すと改行が LF になり、
照合が通らず、給与所得・源泉徴収税額表を使う計算とテストが `DataFileError`・`GensenTableError` で止まる。

`.gitattributes` で、この CSV と元の実測の出力（`scripts/results/IMPL_kyuyo_beppyo5/`・`scripts/results/IMPL3_gensen_tables/`）の改行を CRLF に固定した
（リポジトリの中の保存は LF のまま。記録した SHA-256 と判定コアのコードは変えていない）。

`.gitattributes` が入る前に Linux・macOS で取り出した作業ツリーは、取り出し直す：

```
git rm -q --cached -- 'packages/core/src/okura_core/rules/kyuyo/data/*.csv' 'packages/core/src/okura_core/rules/tax/data/*.csv' \
    'scripts/results/IMPL_kyuyo_beppyo5/*.csv' 'scripts/results/IMPL3_gensen_tables/*.csv'
git checkout HEAD -- 'packages/core/src/okura_core/rules/kyuyo/data/*.csv' 'packages/core/src/okura_core/rules/tax/data/*.csv' \
    'scripts/results/IMPL_kyuyo_beppyo5/*.csv' 'scripts/results/IMPL3_gensen_tables/*.csv'
```

## 4. 版

- AlmaLinux は `almalinux:9` のタグ（OS の修正を取り込むため、ダイジェストでは固定していない）。固定したいときは `--build-arg ALMALINUX_IMAGE=…@sha256:…`。
- Python は AlmaLinux の `python3.11`。uv は仮想環境を作るためだけに使い、最後のイメージには入らない（版とダイジェストを固定。`Containerfile` の `UV_IMAGE`）。
- openfisca-core 46.0.1・beancount 3.2.3・beanquery 0.2.0（D6・D11。Linux の x86_64・aarch64 に wheel がある）。
