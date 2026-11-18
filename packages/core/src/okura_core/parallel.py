"""候補の組の評価のプロセスの並列（2026-11-12 の5回目。packages/core/README.md §5.4）。

評価の単位の中で、値ごとの候補の評価（evaluate._resolve_dependencies）が一度に求める候補の組は互いに独立に計算できる
（候補の組1つの段階評価と最後の計算は、その組の判断・選択・端数の候補と中間表現だけで決まる。evaluate の使い回しの表は
計算を速くするだけで値を変えない）。それを標準ライブラリの concurrent.futures のプロセスで分けて計算する。

- ワーカーは spawn で作り（Windows）、OpenFisca の体系の構築（build_system）をワーカーごとに1回だけ行う。プールはプロセスで1つを
  使い回す（evaluate の呼び出しをまたぐ）。
- ワーカーは、問い・中間表現・注入データ（JSON のまま）とシナリオ・評価の単位の番号から、親と同じ手順で評価の単位を組み立て直す
  （evaluate._worker_handle）。最初に全部のワーカーが基準の組（全部が最初の候補）とその分かれ目の依存を計算して使い回しの表を温め
  （Dispatcher.base。親は最初に出したワーカーの結果を使う）、そのあと候補の組を続いた組のまとまりで計算する（Dispatcher.run）。
  親に返すのは、親が使う部分（値・最後の situation の入力の値・検出・分かれ目の依存）だけ。
- 親（evaluate）は、並列のときは計算をせずに割り振りとまとめ（依存する分かれ目の決定・値のまとめ・境目）だけを行い、評価の単位
  （所得税 2025 と 2026 など）をスレッドで並べて進める（ワーカーの結果を待つ間に、ほかの単位を進める）。
- 値の入力の集まりは評価の単位ごとの番号のビット（evaluate._InputIndex）なので、ワーカーの番号を親の番号に付け替える（_Remap）。
- 結果の並びは、組を求めた順（ワーカーの数・終わった順によらない）。並列でも直列（ワーカー 1）でも結果は同じ
  （docs/measurements/20261112_core-perf_before-after.md §9 で全部の家庭を突き合わせた）。
- spawn の子は、呼び出し側のスクリプト（__main__）を読み直す（`if __name__ == "__main__"` のないスクリプトから evaluate を呼ぶと、
  子がスクリプトをもう一度実行する）。子に要るのは okura_core だけなので、子を作る間だけ __main__ を空のモジュールに替える（_without_main）。
"""

from __future__ import annotations

import contextlib
import itertools
import multiprocessing
import os
import sys
import threading
import types
from collections.abc import Iterator, Sequence
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from typing import Any

import numpy

#: 並列にする単位：未入力の判断・選択の分かれ目（最初から開いているもの）がこの数以上（少ない単位は候補の組が少なく、親で直列に
#: 計算する方が速い。ワーカーの起動〔プロセスで1回、数秒〕も避ける。結果は変わらない。測った値：
#: docs/measurements/20261112_core-perf_before-after.md §9）
MIN_OPEN_SLOTS = 2


def default_workers() -> int:
    """並列の既定の数：このプロセスが使える CPU の数。"""
    try:
        n = len(os.sched_getaffinity(0))  # type: ignore[attr-defined]
    except AttributeError:
        n = os.cpu_count() or 1
    return max(1, n)


# ---------------------------------------------------------------------------
# 親：プールと割り振り
# ---------------------------------------------------------------------------

_LOCK = threading.Lock()
_POOL: list[Any] = [None, 0]  # [ProcessPoolExecutor, ワーカーの数]
_TOKENS = itertools.count(1)


@contextlib.contextmanager
def _without_main() -> Iterator[None]:
    """子のプロセスを作る間だけ、__main__ を __file__・__spec__ のない空のモジュールに替える（spawn の子が呼び出し側の
    スクリプトを読み直さないように。multiprocessing.spawn.get_preparation_data は、__main__ に名前もファイルもなければ読み直さない）。"""
    main = sys.modules.get("__main__")
    sys.modules["__main__"] = types.ModuleType("__main__")
    try:
        yield
    finally:
        if main is not None:
            sys.modules["__main__"] = main


def _pool(workers: int) -> ProcessPoolExecutor:
    with _LOCK:
        ex, n = _POOL
        if ex is not None and n != workers:
            ex.shutdown(wait=True, cancel_futures=True)
            ex = None
        if ex is None:
            ex = ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn"), initializer=_init_worker)
            _POOL[0], _POOL[1] = ex, workers
        return ex


def _discard_pool() -> None:
    with _LOCK:
        ex = _POOL[0]
        _POOL[0], _POOL[1] = None, 0
    if ex is not None:
        ex.shutdown(wait=False, cancel_futures=True)


def shutdown() -> None:
    """プールを止める（テスト・長く動くアプリが資源を返すとき。止めなくても終了の時に止まる）。"""
    with _LOCK:
        ex = _POOL[0]
        _POOL[0], _POOL[1] = None, 0
    if ex is not None:
        ex.shutdown(wait=True, cancel_futures=True)


def chunks(items: Sequence[Any], workers: int) -> list[list[Any]]:
    """組の並びを、続いた組のまとまりに分ける（ワーカーの数の2倍まで。並びの順を保つ。続いた組は段の回を使い回しやすい）。"""
    n = len(items)
    if n == 0:
        return []
    k = max(1, min(n, 2 * workers))
    size, extra = divmod(n, k)
    out: list[list[Any]] = []
    i = 0
    for j in range(k):
        step = size + (1 if j < extra else 0)
        out.append(list(items[i:i + step]))
        i += step
    return out


class _Remap:
    """ワーカーの入力の番号（ワーカーの _InputIndex）を親の番号に付け替える。ワーカーの単位の組み立てごと（hid）に、
    ワーカーの番号 i → 親の番号の表を持つ（ワーカーは新しく足した番号だけを送る）。"""

    def __init__(self, index: Any) -> None:
        self.index = index
        self.maps: dict[Any, list[int]] = {}
        self.ident: dict[Any, int] = {}  # 先頭から番号が同じ数（その範囲のビットは付け替えない）
        self.arrays: dict[Any, numpy.ndarray] = {}
        self.cache: dict[tuple[Any, int], int] = {}

    def absorb(self, hid: Any, start: int, keys: Sequence[tuple[str, str]]) -> None:
        pos = self.maps.setdefault(hid, [])
        if len(pos) != start:
            raise AssertionError(f"ワーカーの入力の番号の続きが合わない: {len(pos)} != {start}")
        for k in keys:
            pos.append(self.index.of(k).bit_length() - 1)
        m = self.ident.get(hid, 0)
        while m < len(pos) and pos[m] == m:
            m += 1
        self.ident[hid] = m
        if keys:
            self.arrays[hid] = numpy.asarray(pos, dtype=numpy.int64)

    def convert(self, hid: Any, b: int) -> int:
        if b == 0 or b.bit_length() <= self.ident.get(hid, 0):
            return b
        hit = self.cache.get((hid, b))
        if hit is not None:
            return hit
        raw = numpy.frombuffer(b.to_bytes((b.bit_length() + 7) // 8, "little"), dtype=numpy.uint8)
        where = self.arrays[hid][numpy.flatnonzero(numpy.unpackbits(raw, bitorder="little"))]
        flags = numpy.zeros(int(where.max()) + 1, dtype=bool)
        flags[where] = True
        out = int.from_bytes(numpy.packbits(flags, bitorder="little").tobytes(), "little")
        self.cache[(hid, b)] = out
        return out


class Dispatcher:
    """評価の単位1つの計算をワーカーに割り振る（evaluate._evaluate_unit が持つ）。

    spec は単位を組み立て直す材料（中間表現・問い・注入データの JSON、シナリオの番号、単位の番号。最初に割り振るときに pickle する）。
    attach で親の単位の入力の番号（_InputIndex）を渡す。
    - base：全部のワーカーに単位を組み立てさせ、基準の組（全部が最初の候補）とその分かれ目の依存を計算させる（使い回しの表を温める）。
      最初に出したワーカーの基準の組を返す（どのワーカーの計算も同じ）。
    - run：候補の組の並びを、続いた組のまとまりに分けてワーカーで計算する。
    """

    def __init__(self, workers: int, spec: tuple[Any, ...]) -> None:
        self.workers = workers
        self.spec = spec
        self.blob: bytes | None = None
        self.token = f"{os.getpid()}:{next(_TOKENS)}"
        self.remap: _Remap | None = None
        self.exact: Any = None
        self.exact_blob: bytes | None = None

    def attach(self, index: Any) -> None:
        self.remap = _Remap(index)

    def _submit(self, calls: list[tuple[Any, ...]]) -> list[Any]:
        import pickle

        if self.blob is None:
            self.blob = pickle.dumps(self.spec, protocol=pickle.HIGHEST_PROTOCOL)
        ex = _pool(self.workers)
        with _SUBMIT, _without_main():  # __main__ の差し替えは、単位を並べて評価するスレッドどうしで重ねない
            return [ex.submit(fn, self.token, self.blob, *args) for fn, *args in calls]

    def base(self) -> tuple[dict[str, Any], bool] | None:
        """基準の組の計算（親の番号に付け替えたもの）と、入力の依存を集めたか（track）。ワーカーが落ちたら None。
        最初のワーカーの作り手の依存の表を持っておき、run でほかのワーカーに渡す。"""
        try:
            futures = self._submit([(_run_base, i == 0) for i in range(self.workers)])
            hid, start, keys, payload = futures[0].result()
        except BrokenProcessPool:
            _discard_pool()
            return None
        assert self.remap is not None and payload is not None
        self.remap.absorb(hid, start, keys)
        packed, track, self.exact = payload
        self.exact_blob = None
        return self._convert(hid, packed, set()), track

    def run(self, track: bool, items: Sequence[tuple[tuple[tuple[str, str], ...], frozenset[str] | None]]) -> list[dict[str, Any]] | None:
        """組（(分かれ目の ID, 候補の名前) の並びと、集める値）の並びを計算し、親の番号に付け替えた結果を同じ順で返す。
        ワーカーが落ちた（BrokenProcessPool）ら None（呼び出し側が直列で計算する。結果は同じ）。"""
        assert self.remap is not None
        try:
            import pickle

            if self.exact_blob is None:
                self.exact_blob = pickle.dumps(self.exact, protocol=pickle.HIGHEST_PROTOCOL)
            futures = self._submit([(_run_chunk, self.exact_blob, track, part) for part in chunks(items, self.workers)])
            out: list[dict[str, Any]] = []
            for f in futures:
                hid, start, keys, packed = f.result()
                self.remap.absorb(hid, start, keys)
                done: set[int] = set()  # 1つのまとまりの結果の中で同じ値（_Raw）は同じオブジェクト（pickle が共有を保つ）：付け替えは1回だけ
                for p in packed:
                    out.append(self._convert(hid, p, done))
            return out
        except BrokenProcessPool:
            _discard_pool()
            return None

    def _convert(self, hid: Any, p: dict[str, Any], done: set[int]) -> dict[str, Any]:
        """ワーカーの番号のビットを親の番号に付け替える。ワーカーは前の組で集めた値（_Raw）を使い回す（evaluate._assemble の reuse）ので、
        同じまとまりの複数の組が同じ _Raw のオブジェクトを持つ。done（付け替えたオブジェクトの id。まとまりの結果を持っている間だけ使う）で
        2回付け替えない（2回付け替えると別の入力を指す）。"""
        assert self.remap is not None
        conv = self.remap.convert
        for r in p["raws"].values():
            if id(r) in done:
                continue
            done.add(id(r))
            r.inputs = conv(hid, r.inputs)
            r.extra = conv(hid, r.extra)
        p["check_bits"] = {k: conv(hid, v) for k, v in p["check_bits"].items()}
        if p["attribution"] is not None:
            p["attribution"] = {k: conv(hid, v) for k, v in p["attribution"].items()}
        return p


_SUBMIT = threading.Lock()


# ---------------------------------------------------------------------------
# ワーカー
# ---------------------------------------------------------------------------

#: ワーカーが持つ単位の数（親は単位を並べて評価する。古いものから手放す）
_KEEP = 4
_W: dict[str, Any] = {"system": None, "serial": 0}
#: token →（hid, 単位, 送った番号の数）
_HANDLES: dict[str, list[Any]] = {}


def _init_worker() -> None:
    from .country import build_system
    from .evaluate import REGISTRY  # evaluate は parallel を import するので、ここで引く

    _W["system"] = build_system(REGISTRY)


def _handle(token: str, spec: bytes) -> list[Any]:
    import pickle

    entry = _HANDLES.get(token)
    if entry is None:
        while len(_HANDLES) >= _KEEP:
            del _HANDLES[next(iter(_HANDLES))]  # 先に手放す（記憶域）
        ir, query, injected, si, ji = pickle.loads(spec)
        from .evaluate import _worker_handle

        h = _worker_handle(ir, query, injected, si, ji, _W["system"])
        _W["serial"] += 1
        entry = _HANDLES[token] = [(os.getpid(), _W["serial"]), h, 0]
    return entry


def _new_keys(entry: list[Any]) -> tuple[int, list[tuple[str, str]]]:
    keys = entry[1].index.keys
    start = entry[2]
    entry[2] = len(keys)
    return start, list(keys[start:])


def _run_base(token: str, spec: bytes, want: bool) -> tuple[Any, int, list[tuple[str, str]], Any]:
    entry = _handle(token, spec)
    packed = entry[1].base(want)  # 1回だけ計算する（2回目からは同じもの）
    if not want:
        return entry[0], 0, [], None  # 温めるだけ（番号は送らない）
    start, new = _new_keys(entry)
    return entry[0], start, new, packed


def _run_chunk(
    token: str, spec: bytes, exact: bytes, track: bool, items: Sequence[Any]
) -> tuple[Any, int, list[tuple[str, str]], list[dict[str, Any]]]:
    import pickle

    entry = _handle(token, spec)
    h = entry[1]
    if not h.installed:
        h.install(pickle.loads(exact))
    packed = [h.run(labels, needed, track) for labels, needed in items]
    start, new = _new_keys(entry)
    return entry[0], start, new, packed
