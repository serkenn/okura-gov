# okura-gov を AlmaLinux 9 のコンテナで動かす（判定コア・記録層のコマンド、監視、テスト）。手順は ops/container/README.md。
#
#   podman build -t okura-gov .          # docker build -f Containerfile -t okura-gov . でも同じ
#   podman run --rm okura-gov test       # テストを全部動かす
#
# - 仮想環境は AGENTS.md「仮想環境の作り方」のとおり：core（openfisca-core、AGPL）と records（beancount、GPL）を分け、wheel だけを入れる。
#   自作のパッケージは pip で入れず、okura_dev.pth に src の絶対パスを書く。monitor は標準ライブラリだけ。
# - 家族のデータはイメージに入れない。使うときに標準入力かマウントで渡す。
# - 動かすときは root でないユーザー（UID 10001）。
#
# ベースのイメージは AlmaLinux 9（Python 3.11 が AppStream にある）。
# uv は仮想環境を作るためだけに使い、最後のイメージには入れない（版とダイジェストを固定。2026-11-03 公開の 0.13.7）。
ARG ALMALINUX_IMAGE=docker.io/library/almalinux:9
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490

FROM ${UV_IMAGE} AS uv

# ---------------------------------------------------------------------------- 仮想環境を作る
FROM ${ALMALINUX_IMAGE} AS build
RUN dnf -y install python3.11 && dnf clean all
COPY --from=uv /uv /usr/local/bin/uv
COPY . /opt/okura-gov
WORKDIR /opt/okura-gov
# Python は AlmaLinux の python3.11 だけを使う（uv に取りに行かせない）。
# 動かすときは書き込めないので、バイトコードを先に作っておく。
ENV UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1
RUN set -eu; \
    uv venv .work/venvs/core --python 3.11; \
    uv pip install --python .work/venvs/core/bin/python --only-binary :all: openfisca-core==46.0.1; \
    uv venv .work/venvs/records --python 3.11; \
    uv pip install --python .work/venvs/records/bin/python --only-binary :all: beancount==3.2.3 beanquery==0.2.0; \
    python3.11 -I -m venv --without-pip .work/venvs/monitor; \
    site() { "$1" -I -c "import sysconfig; print(sysconfig.get_paths()['purelib'])"; }; \
    printf '%s\n' /opt/okura-gov/packages/ir/src /opt/okura-gov/packages/core/src \
        > "$(site .work/venvs/core/bin/python)/okura_dev.pth"; \
    printf '%s\n' /opt/okura-gov/packages/ir/src /opt/okura-gov/packages/records/src \
        > "$(site .work/venvs/records/bin/python)/okura_dev.pth"; \
    printf '%s\n' /opt/okura-gov/packages/monitor/src \
        > "$(site .work/venvs/monitor/bin/python)/okura_monitor_dev.pth"; \
    .work/venvs/core/bin/python -I -X utf8 -c "import okura_core, okura_ir; print('core ok')"; \
    .work/venvs/records/bin/python -I -X utf8 -c "import okura_records, okura_ir; print('records ok')"; \
    .work/venvs/monitor/bin/python -I -X utf8 -c "import okura_monitor; print('monitor ok')"; \
    python3.11 -I -X utf8 -m compileall -q --invalidation-mode unchecked-hash \
        packages/ir/src packages/core/src packages/records/src packages/monitor/src ops/container

# ---------------------------------------------------------------------------- 動かすイメージ
FROM ${ALMALINUX_IMAGE}
RUN dnf -y install python3.11 && dnf clean all \
 && useradd --system --uid 10001 --user-group --home-dir /var/lib/okura-gov --no-create-home --shell /sbin/nologin okura \
 && install -d -o okura -g okura -m 0700 /var/lib/okura-gov
COPY --from=build /opt/okura-gov /opt/okura-gov
ENV HOME=/var/lib/okura-gov \
    LANG=C.UTF-8
USER 10001:10001
WORKDIR /opt/okura-gov
# 監視の状態と出力（monitor run --state-dir /var/lib/okura-gov/state --out /var/lib/okura-gov/out）
VOLUME /var/lib/okura-gov
ENTRYPOINT ["/usr/bin/python3.11", "-I", "-X", "utf8", "/opt/okura-gov/ops/container/run.py"]
CMD ["help"]
