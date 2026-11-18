"""記録層の問題（入力の誤り・拒否の理由）の型。

- where：問題のある場所。台帳なら `main.beancount:12`、JSON Lines なら `facts.jsonl:3`、
  中間表現なら `$.facts[0].roles.payer`（okura_ir の path の書き方）。
- code：機械が読む分類（README の「問題の code」の表）。
- message：人が読む説明（日本語）。
- origin：中間表現の問題のとき、その要素の出どころ（`facts.jsonl:3 (fe-0003)`・`main.beancount:12 (tx-…)`）。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Problem:
    where: str
    code: str
    message: str
    origin: str | None = None

    def to_dict(self) -> dict[str, str]:
        out = {"where": self.where, "code": self.code, "message": self.message}
        if self.origin is not None:
            out["origin"] = self.origin
        return out
