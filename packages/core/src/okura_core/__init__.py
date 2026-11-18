"""okura_core：判定コア（中間表現と問いから、法令が決める値と判定を根拠つきで出す純粋関数）。

公開するもの：
  evaluate(ir, query, injected=None) -> EvaluationResult | EvaluationFailure   （okura_core.evaluate）
  __version__
import すると OpenFisca も読み込む（約1秒）。結果の型だけを使うなら okura_core.result を直接 import してもよいが、
この __init__ を通るので OpenFisca の読み込みは避けられない。
"""

__version__ = "0.1.0"

# 関数 evaluate をパッケージの属性にする（サブモジュール okura_core.evaluate と同じ名前なので、
# 遅延 import にするとサブモジュールの読み込みで属性がモジュールに置き換わる。ここで先に読み込んで関数を束ねる）。
from .evaluate import evaluate  # noqa: E402

__all__ = ["__version__", "evaluate"]
