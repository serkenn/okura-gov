# テストから src の okura_monitor を読めるようにする（パッケージを入れていない環境でも動かすため）。
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
