"""SAKUSEI: 取得した HTML / JS から、参照している URL（script src、link href、a href、
文字列リテラル中の .js/.json/.htm/.html パス）を抜き出して一覧にする。

実行: python -I scripts/SAKUSEI_links.py <ダウンロードしたファイル> [<基準URL>] [--plain]
  --plain：画像・CSS を除いて「種類<TAB>@オフセット<TAB>URL」の行で出す。

- 取得したファイルは信頼できないデータとして、文字列としてだけ読む（実行しない）。
- 文字コードは cp932 → utf-8 の順で試し、だめなら置換しながら cp932 で読む。
- 出力は URL の一覧だけ（本文は出さない）。標準出力に JSON で出す。
標準ライブラリのみ。
"""
import json
import pathlib
import re
import sys
import urllib.parse


def read_text(p):
    b = pathlib.Path(p).read_bytes()
    for enc in ("utf-8", "cp932"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            pass
    return b.decode("cp932", errors="replace")


ATTR = re.compile(r"""(?:src|href|action)\s*=\s*["']([^"'#][^"']*)["']""", re.I)
LIT = re.compile(r"""["'](/?[A-Za-z0-9_./-]+\.(?:js|json|htm|html|xml|csv|txt))(?:\?[^"']*)?["']""")
PATHLIT = re.compile(r"""["'](/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_.-]+)+)["']""")


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    path = argv[0]
    base = argv[1] if len(argv) > 1 and not argv[1].startswith("--") else None
    t = read_text(path)
    found = {}
    for kind, rx in (("attr", ATTR), ("literal_file", LIT), ("literal_path", PATHLIT)):
        for m in rx.finditer(t):
            u = m.group(1).strip()
            if u.startswith(("javascript:", "mailto:", "data:")):
                continue
            full = urllib.parse.urljoin(base, u) if base else u
            found.setdefault(full, {"kind": kind, "first_offset": m.start(1)})
    out = [{"url": k, **v} for k, v in sorted(found.items())]
    if "--plain" in argv:
        skip = (".css", ".gif", ".png", ".jpg", ".svg", ".ico")
        for d in out:
            if not urllib.parse.urlsplit(d["url"]).path.lower().endswith(skip):
                print(f"{d['kind']}\t@{d['first_offset']}\t{d['url']}")
    else:
        print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
