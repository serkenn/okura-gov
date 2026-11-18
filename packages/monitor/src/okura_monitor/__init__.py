"""okura_monitor：法令・通知・通達の変更を監視し、issue の下書きを作る（D9・D17 Q9・SCOPE §3）。

- 判定コア（okura_core）・記録（okura_records）を import しない。判定コアの YAML はテキストとして読むだけ。
- ネットワークに出るのは、このパッケージだけ（SCOPE §3）。
- 前回の状態は、利用側が渡すディレクトリ（--state-dir）に置く。ライブラリ自身はデータを持たない。
- Python の標準ライブラリだけを使う。
"""

__version__ = "0.1.0"
USER_AGENT = "okura-gov-monitor/0.1"
