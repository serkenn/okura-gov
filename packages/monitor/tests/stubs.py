"""取得のスタブ：URL ごとに決めた応答を返し、受けたリクエストを記録する。"""
from okura_monitor.fetch import Response


class StubFetcher:
    def __init__(self, responses):
        self.responses = responses  # url -> Response か、(headers -> Response) の関数
        self.calls = []

    def get(self, url, headers=None):
        self.calls.append((url, dict(headers or {})))
        r = self.responses[url]
        return r(headers or {}) if callable(r) else r


def resp(status=200, body=b"", **headers):
    return Response(status, "https://example.invalid/", {k.lower().replace("_", "-"): v for k, v in headers.items()}, body)
