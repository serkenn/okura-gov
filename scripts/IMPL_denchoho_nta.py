"""IMPL_denchoho: 国税庁の電子帳簿保存法関係のページ（特設サイト、一問一答、取扱通達、事務処理規程のサンプル）を取得する。

実行（リポジトリのルートで。段階ごとに実行する）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_denchoho_nta.py <stage>
  stage: STAGES のキー（discover / docs など）

- 標準ライブラリのみ。User-Agent は okura-gov-research/0.1。リクエストの間は 1.5 秒あける。個人の情報は送らない。
- 取得したもの（HTML・PDF・docx など）は、実行ごとに新しい空のディレクトリ
  .work/downloads/<ts>_denchoho_nta_<stage>/ に置く（信頼できないデータ。中でコードを実行しない）。
- 出力は scripts/results/IMPL_denchoho_nta/<stage>/：
  - <key>.txt  … HTML は本文のテキスト、docx は word/document.xml の段落テキスト（zipfile と正規表現だけで取り出す）
  - <key>.links.tsv … HTML のリンク（href の絶対 URL とリンクの文字）
  - fetch_log.json … URL、HTTP ステータス、Content-Type、サイズ、SHA-256、Last-Modified、保存先
  PDF はここではテキストにしない（Read ツールの pages 指定で読む）。保存先のパスを fetch_log.json に書く。
HTML のテキスト化は scripts/R4_fetch_nta.py から写して改変した（import はしていない）。
"""
import hashlib
import html.parser
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "okura-gov-research/0.1"
WAIT = 1.5
MAX_BYTES = 30 * 1024 * 1024  # これより大きいものは途中で打ち切る
NTA = "https://www.nta.go.jp"

STAGES = {
    # 入口のページを取り、リンクを集める（URL は国税庁サイトのトップから辿れる電子帳簿保存法の入口）
    "discover": [
        ("robots", NTA + "/robots.txt"),
        ("jirei-index", NTA + "/law/joho-zeikaishaku/sonota/jirei/index.htm"),
        ("tokusetsu-index", NTA + "/law/joho-zeikaishaku/sonota/jirei/tokusetsu/index.htm"),
    ],
    # discover の jirei-index / tokusetsu-index のリンクから選んだページ
    "pages": [
        ("qa-index", NTA + "/law/joho-zeikaishaku/sonota/jirei/4-3.htm"),        # 一問一答（Q&A）
        ("hourei-tsutatsu", NTA + "/law/joho-zeikaishaku/sonota/jirei/03.htm"),  # 関係法令・取扱通達等
        ("gaiyo", NTA + "/law/joho-zeikaishaku/sonota/jirei/02.htm"),            # 電子帳簿保存法の概要
        ("pamphlet", NTA + "/law/joho-zeikaishaku/sonota/jirei/08.htm"),         # パンフレット
        ("tokusetsu-01", NTA + "/law/joho-zeikaishaku/sonota/jirei/tokusetsu/01.htm"),
        ("tokusetsu-02", NTA + "/law/joho-zeikaishaku/sonota/jirei/tokusetsu/02.htm"),
        ("tokusetsu-03", NTA + "/law/joho-zeikaishaku/sonota/jirei/tokusetsu/03.htm"),
    ],
    # pages の qa-index / hourei-tsutatsu / pamphlet のリンクから選んだ資料
    "docs": [
        ("qa-dentori-r0807", NTA + "/law/joho-zeikaishaku/sonota/jirei/pdf/0026007-006_05.pdf"),        # 一問一答【電子取引関係】(令和8年7月)
        ("qa-dentori-r0807-diff", NTA + "/law/joho-zeikaishaku/sonota/jirei/pdf/0026007-006_06.pdf"),   # 同 変更箇所下線あり
        ("qa-chobo-r0807", NTA + "/law/joho-zeikaishaku/sonota/jirei/pdf/0026007-006_01.pdf"),          # 一問一答【電子計算機を使用して作成する帳簿書類関係】(令和8年7月)
        ("tsutatsu-r0706", NTA + "/law/joho-zeikaishaku/sonota/jirei/pdf/0025006-066.pdf"),             # 電子帳簿保存法取扱通達（令和7年6月27日付一部改正分まで）
        ("tsutatsu-kaisetsu-r0706", NTA + "/law/joho-zeikaishaku/sonota/2506/pdf/01-4.pdf"),            # 取扱通達解説（趣旨説明）（令和7年6月27日現在）
        ("pamph-dentori-r0611", NTA + "/law/joho-zeikaishaku/sonota/jirei/tokusetsu/pdf/0024011-003_01.pdf"),  # 令和6年1月以降の電子取引データの保存方法について（令和6年11月）
        ("pamph-dentori-check-r0611", NTA + "/law/joho-zeikaishaku/sonota/jirei/tokusetsu/pdf/0024011-003_02.pdf"),  # 電子取引データ保存要件チェックシート
        ("pamph-r7kaisei", NTA + "/law/joho-zeikaishaku/sonota/jirei/pdf/0025003-097_01.pdf"),          # 令和7年度税制改正による見直しの概要（令和7年4月）
        ("samples-page", NTA + "/law/joho-zeikaishaku/sonota/jirei/0021006-031.htm"),                   # 参考資料（各種規程等のサンプル）
    ],
    # docs の samples-page のリンクから選んだ、電子取引に関するサンプル
    "samples": [
        ("kitei-kojin", NTA + "/law/joho-zeikaishaku/sonota/jirei/word/0021006-031_e.docx"),   # 事務処理規程（個人事業者の例）
        ("kitei-hojin", NTA + "/law/joho-zeikaishaku/sonota/jirei/word/0021006-031_d.docx"),   # 事務処理規程（法人の例）
        ("sakuinbo", NTA + "/law/joho-zeikaishaku/sonota/jirei/excel/0021006-031_c.xlsx"),     # 索引簿の作成例
    ],
    # 帳簿の電子保存（法4条1項・規則2条1項の「正規の簿記の原則」）の扱いを確かめるための資料（pages の tokusetsu-02 / pamphlet のリンク）
    "docs2": [
        ("pamph-chobo-r0507", NTA + "/law/joho-zeikaishaku/sonota/jirei/tokusetsu/pdf/0023006-085_02.pdf"),  # はじめませんか、帳簿・書類のデータ保存（令和5年7月）
        ("pamph-r0806", NTA + "/law/joho-zeikaishaku/sonota/jirei/tokusetsu/pdf/0026006-122.pdf"),            # 電子帳簿等保存制度を活用して…（令和8年6月）
    ],
}



class Text(html.parser.HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "dt", "dd", "table", "td", "th"}

    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip, self.base = [], 0, base
        self.links, self._a = [], None

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self._a = [urllib.parse.urljoin(self.base, href), []]

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag == "a" and self._a:
            self.links.append((self._a[0], re.sub(r"\s+", " ", "".join(self._a[1])).strip()))
            self._a = None

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)
            if self._a is not None:
                self._a[1].append(data)

    def text(self):
        t = "".join(self.parts).replace("\r", "")
        t = re.sub(r"[ \t\u3000]*\n[ \t\u3000]*", "\n", t)
        return re.sub(r"\n{2,}", "\n", t).strip()


def decode(body, ctype):
    m = re.search(rb'charset=["\']?([A-Za-z0-9_\-]+)', body[:4096])
    enc = m.group(1).decode() if m else None
    if not enc and ctype and "charset=" in ctype:
        enc = ctype.split("charset=")[-1]
    for e in [enc, "utf-8", "cp932"]:
        if not e:
            continue
        try:
            return body.decode("cp932" if e.lower() in ("shift_jis", "sjis", "x-sjis") else e), e
        except (UnicodeDecodeError, LookupError):
            continue
    return body.decode("utf-8", "replace"), "utf-8(replace)"


def docx_text(path):
    """docx（zip）の word/document.xml から段落ごとのテキストを取り出す。展開はしない。"""
    with zipfile.ZipFile(path) as z:
        info = z.getinfo("word/document.xml")
        if info.file_size > MAX_BYTES:
            raise RuntimeError("document.xml too large")
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    paras = []
    for p in re.findall(r"<w:p[ >].*?</w:p>", xml, flags=re.S):
        p = re.sub(r"<w:tab/>", "\t", p)
        p = re.sub(r"<w:br/>", "\n", p)
        t = "".join(re.findall(r"<w:t(?: [^>]*)?>([^<]*)</w:t>", p))
        paras.append(html.unescape(t))
    return "\n".join(paras)


def xlsx_text(path):
    """xlsx（zip）の共有文字列と各シートのセルを取り出す。展開はしない。"""
    out = []
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        for n in names:
            if z.getinfo(n).file_size > MAX_BYTES:
                raise RuntimeError(f"{n} too large")
        shared = []
        if "xl/sharedStrings.xml" in names:
            xml = z.read("xl/sharedStrings.xml").decode("utf-8", "replace")
            for si in re.findall(r"<si>(.*?)</si>", xml, flags=re.S):
                shared.append(html.unescape("".join(re.findall(r"<t(?: [^>]*)?>([^<]*)</t>", si))))
        for n in sorted(x for x in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", x)):
            out.append(f"## {n}")
            xml = z.read(n).decode("utf-8", "replace")
            for m in re.finditer(r'<c r="([A-Z]+\d+)"([^>]*?)(?:/>|>(.*?)</c>)', xml, flags=re.S):
                ref, attrs, inner = m.group(1), m.group(2), m.group(3) or ""
                v = re.search(r"<v>([^<]*)</v>", inner)
                t = re.search(r"<t(?: [^>]*)?>([^<]*)</t>", inner)
                if 't="s"' in attrs and v:
                    val = shared[int(v.group(1))]
                elif t:
                    val = html.unescape(t.group(1))
                elif v:
                    val = v.group(1)
                else:
                    continue
                out.append(f"{ref}\t{val}")
    return "\n".join(out)


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            body = r.read(MAX_BYTES + 1)
            return r.status, dict(r.headers), body
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read(65536)


def main():
    stage = sys.argv[1] if len(sys.argv) > 1 else "discover"
    jobs = STAGES[stage]
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_denchoho_nta_{stage}"
    dl.mkdir(parents=True, exist_ok=False)
    out = ROOT / "scripts" / "results" / "IMPL_denchoho_nta" / stage
    out.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "stage": stage, "download_dir": str(dl.relative_to(ROOT)), "items": []}
    for key, url in jobs:
        ent = {"key": key, "url": url}
        try:
            st, hdr, body = fetch(url)
            ctype = hdr.get("Content-Type", "")
            ext = ".pdf" if "pdf" in ctype or url.lower().endswith(".pdf") else \
                  ".docx" if url.lower().endswith(".docx") or "wordprocessingml" in ctype else \
                  ".xlsx" if url.lower().endswith(".xlsx") else \
                  ".txt" if url.lower().endswith(".txt") else ".htm"
            p = dl / f"{key}{ext}"
            p.write_bytes(body[:MAX_BYTES])
            ent.update({"status": st, "content_type": ctype, "bytes": len(body), "truncated": len(body) > MAX_BYTES,
                        "sha256": hashlib.sha256(body).hexdigest(), "last_modified": hdr.get("Last-Modified"),
                        "saved": str(p.relative_to(ROOT))})
            if st == 200 and ext == ".htm":
                text, enc = decode(body, ctype)
                tp = Text(url)
                tp.feed(text)
                (out / f"{key}.txt").write_text(f"# source={url}\n# fetched_at={ts}\n# encoding={enc}\n# sha256={ent['sha256']}\n\n{tp.text()}\n", encoding="utf-8")
                (out / f"{key}.links.tsv").write_text("\n".join(f"{h}\t{t}" for h, t in tp.links) + "\n", encoding="utf-8")
                ent["output"] = f"scripts/results/IMPL_denchoho_nta/{stage}/{key}.txt"
            elif st == 200 and ext == ".txt":
                text, enc = decode(body, ctype)
                (out / f"{key}.txt").write_text(f"# source={url}\n# fetched_at={ts}\n\n{text}\n", encoding="utf-8")
            elif st == 200 and ext == ".docx":
                (out / f"{key}.txt").write_text(f"# source={url}\n# fetched_at={ts}\n# sha256={ent['sha256']}\n# 取り出し: word/document.xml の段落\n\n{docx_text(p)}\n", encoding="utf-8")
                ent["output"] = f"scripts/results/IMPL_denchoho_nta/{stage}/{key}.txt"
            elif st == 200 and ext == ".xlsx":
                (out / f"{key}.txt").write_text(f"# source={url}\n# fetched_at={ts}\n# sha256={ent['sha256']}\n# 取り出し: sharedStrings とシートのセル\n\n{xlsx_text(p)}\n", encoding="utf-8")
                ent["output"] = f"scripts/results/IMPL_denchoho_nta/{stage}/{key}.txt"
            print(f"{st} {key} {len(body)} {ctype}", flush=True)
        except Exception as e:  # noqa
            ent["error"] = repr(e)
            print(f"ERR {key} {e!r}", flush=True)
        log["items"].append(ent)
        time.sleep(WAIT)
    (out / "fetch_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", out)


if __name__ == "__main__":
    sys.exit(main())
