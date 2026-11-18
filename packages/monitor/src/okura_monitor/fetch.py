"""HTTP の取得。テストではこの Fetcher をスタブに差し替える（get だけを持つ物なら何でもよい）。

- User-Agent は okura-gov-monitor/0.1。リクエストの間は min_interval 秒（1秒未満にはしない）あける。
- 本文の読み取り全体に制限時間と大きさの上限をかける（ソケットの timeout は1回の読み取りごとにしか効かない：
  docs/measurements/20261109_R3-tsutatsu_fetch-and-monitor-probe.md §2-8）。
- 官報（kanpo.go.jp）は robots.txt で巡回が禁止されている（docs/public-sources/20261109_R1-laws_monitoring-sources.md §4）ので、
  リダイレクト先を含めて取得を拒否する。https 以外も拒否する。
"""
from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Mapping, Protocol

from . import USER_AGENT

DISALLOWED_HOSTS = ("kanpo.go.jp",)


class FetchError(Exception):
    """取得できなかった（通信の失敗・制限時間・大きさの上限・拒否したホスト）。"""


@dataclass
class Response:
    status: int
    url: str
    headers: dict[str, str] = field(default_factory=dict)  # 名前は小文字
    body: bytes = b""

    def header(self, name: str) -> str | None:
        return self.headers.get(name.lower())


class Fetcher(Protocol):
    def get(self, url: str, headers: Mapping[str, str] | None = None) -> Response: ...


def check_url(url: str) -> None:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https":
        raise FetchError(f"https 以外は取得しない: {url}")
    host = (parts.hostname or "").lower()
    for bad in DISALLOWED_HOSTS:
        if host == bad or host.endswith("." + bad):
            raise FetchError(f"取得しないホスト（robots.txt で禁止）: {host}")


class _CheckedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class UrllibFetcher:
    def __init__(self, *, user_agent: str = USER_AGENT, min_interval: float = 1.5, timeout: float = 60.0,
                 deadline: float = 300.0, max_bytes: int = 200_000_000, sleep=time.sleep, clock=time.monotonic):
        self.user_agent = user_agent
        self.min_interval = max(1.0, float(min_interval))
        self.timeout = timeout
        self.deadline = deadline
        self.max_bytes = max_bytes
        self._sleep = sleep
        self._clock = clock
        self._last: float | None = None
        self._opener = urllib.request.build_opener(_CheckedRedirect())
        self.requests = 0

    def _wait(self) -> None:
        if self._last is not None:
            rest = self.min_interval - (self._clock() - self._last)
            if rest > 0:
                self._sleep(rest)

    def get(self, url: str, headers: Mapping[str, str] | None = None) -> Response:
        check_url(url)
        self._wait()
        h = {"User-Agent": self.user_agent, "Accept-Language": "ja"}
        if headers:
            h.update(headers)
        req = urllib.request.Request(url, headers=h)
        self.requests += 1
        try:
            try:
                with self._opener.open(req, timeout=self.timeout) as resp:
                    body = self._read(resp)
                    return Response(resp.status, resp.geturl(), {k.lower(): v for k, v in resp.headers.items()}, body)
            except urllib.error.HTTPError as e:  # 304・404・500 など
                try:
                    body = e.read(1_000_000)
                except Exception:  # noqa: BLE001
                    body = b""
                hdrs = {k.lower(): v for k, v in (e.headers or {}).items()}
                return Response(e.code, url, hdrs, body)
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                raise FetchError(f"{url}: {e!r}") from e
        finally:
            self._last = self._clock()

    def _read(self, resp) -> bytes:
        limit = self._clock() + self.deadline
        chunks, size = [], 0
        while True:
            b = resp.read(65536)
            if not b:
                break
            size += len(b)
            if size > self.max_bytes:
                raise FetchError(f"大きさの上限（{self.max_bytes} バイト）を超えた")
            chunks.append(b)
            if self._clock() > limit:
                raise FetchError(f"本文の読み取りが {self.deadline} 秒を超えた")
        return b"".join(chunks)
