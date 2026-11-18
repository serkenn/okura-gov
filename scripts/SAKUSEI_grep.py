"""SAKUSEI: 取得したファイル群を正規表現で検索し、位置（ファイル、行番号、文字オフセット）を出す。

実行:
  python -I scripts/SAKUSEI_grep.py [--ctx N] [--save NAME] <dir_or_file> [<dir_or_file> ...] -- <pattern> [<pattern> ...]

- パターンは複数渡せる（OR として扱う。pyenv の .bat シムで | が壊れるため）。
- 端末には前後 N 文字（既定 60）の文脈を表示する（確認用。リポジトリには書かない）。
- --save NAME を付けると、位置だけ（ファイル、SHA-256、行、オフセット、一致の長さ、一致したパターン）を
  scripts/results/SAKUSEI_grep/NAME.json に書く。コードの本文は書かない。
- --keep-ident を付けると、一致した文字列が識別子（と `function`、`=`、`(`）だけでできているときに限り、
  その識別子名（関数名など）を identifier 欄に残す。
- 取得したファイルは信頼できないデータ。文字列として読むだけで実行しない。
標準ライブラリのみ。
"""
import hashlib
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def read_text(p):
    b = p.read_bytes()
    for enc in ("utf-8", "cp932"):
        try:
            return b.decode(enc), b
        except UnicodeDecodeError:
            pass
    return b.decode("cp932", errors="replace"), b


IDENT = re.compile(r"(?:function\s+)?[A-Za-z_$][A-Za-z0-9_$.]*(?:\s*=\s*function)?\s*\(?")


def clean(s):
    return re.sub(r"[\x00-\x1f\x7f]", " ", s)


def main(a):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ctx, save, keep_ident = 60, None, False
    while a and a[0].startswith("--") and a[0] != "--":
        if a[0] == "--ctx":
            ctx = int(a[1]); a = a[2:]
        elif a[0] == "--save":
            save = a[1]; a = a[2:]
        elif a[0] == "--keep-ident":
            keep_ident = True; a = a[1:]
        else:
            raise SystemExit(f"unknown option {a[0]}")
    i = a.index("--")
    targets, pats = a[:i], a[i + 1:]
    rx = re.compile("|".join(f"(?P<p{k}>{p})" for k, p in enumerate(pats)))
    files = []
    for t in targets:
        p = pathlib.Path(t)
        files += sorted(x for x in p.rglob("*") if x.is_file()) if p.is_dir() else [p]
    hits = []
    for f in files:
        t, b = read_text(f)
        sha = hashlib.sha256(b).hexdigest()
        line_starts = [0] + [m.end() for m in re.finditer("\n", t)]
        import bisect
        for m in rx.finditer(t):
            ln = bisect.bisect_right(line_starts, m.start())
            rel = f.as_posix().split(".work/downloads/")[-1]
            print(f"{rel}:{ln}:@{m.start()}: {clean(t[max(0, m.start() - ctx):m.end() + ctx])}")
            k = int(m.lastgroup[1:]) if m.lastgroup else -1
            hits.append({"file": rel, "sha256": sha, "line": ln, "offset": m.start(), "length": len(m.group(0)),
                         "pattern": pats[k] if k >= 0 else None})
            s = m.group(0).strip()
            if keep_ident and IDENT.fullmatch(s):
                hits[-1]["identifier"] = re.sub(r"^function\s+|\s*=\s*function\s*\($|\s*\($", "", s)
    print(f"# hits={len(hits)}")
    if save:
        out = ROOT / "scripts" / "results" / "SAKUSEI_grep"
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{save}.json").write_text(json.dumps({"patterns": pats, "targets": targets, "hits": hits},
                                                     ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
