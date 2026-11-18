"""R3X chiho-sochi: 総務省などの公開資料（HTML・PDF）を取得する。住民税の所得の計算に租税特別措置法の所得計算の特例が
及ぶこと（地方税法第313条第2項・第32条第2項の「所得税法その他の所得税に関する法令の規定による…計算の例」）を
明示した資料を探すため。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_chiho-sochi_web.py <組の名前>

- 組（SETS）ごとに、新しい空のディレクトリ .work/downloads/<YYYYMMDD-HHMMSS>_R3X_chiho-sochi_web_<組>/ に置く
  （信頼できないデータ。中でインタプリタやツールを実行しない。PDF は保存とハッシュだけ。文字の取り出しは
  scripts/R3X_chiho-sochi_pdftext.py がパスを引数で受け取って行う）。
- 取得の前にホストごとに robots.txt を読み（urllib.robotparser）、禁止されている URL は取得しない。
- リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。官報は取得しない。
- HTML は html.parser でテキストとリンク（href と文字列）にし、scripts/results/R3X_chiho-sochi_web/<組>/<名前>.txt・<名前>_links.tsv に書く。
- 取得の記録（URL・状態・Content-Type・Last-Modified・SHA-256・保存先）は scripts/results/R3X_chiho-sochi_web/<組>/fetch_log.json。
  scripts/IMPL_juminzei_municipal.py の取得・テキスト化の部分を写した（import はしない）。
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
import urllib.robotparser

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "okura-gov-research/0.1"
SLEEP = 1.5
SOUMU = "https://www.soumu.go.jp"

# 組の名前 → [(名前, URL, 何のために取るか)]
SETS = {
    # 1回目：一覧のページ（リンクを得るため）
    "index": [
        ("soumu_ichiran04", f"{SOUMU}/main_sosiki/jichi_zeisei/czaisei/czaisei_seido/ichiran04.html",
         "総務省「税制改正（地方税）」の一覧。改正法・政令・取扱通知・留意事項の通知へのリンク元"),
        ("soumu_tsuchi_index", f"{SOUMU}/menu_hourei/s_tsuchi.html",
         "総務省「通知・通達」の一覧（URL は推測。なければ記録だけ）"),
    ],
    # 2回目：index の ichiran04 のリンク「通知・通達」の先
    "index2": [
        ("soumu_t_tsutatsu", f"{SOUMU}/menu_hourei/tsutatsu/t_tsutatsu.html",
         "総務省「通知・通達」（ichiran04 のリンク）。施行通知（総税企など）を探す"),
    ],
    # 3回目：通知などの PDF（リンクは index・index2 の *_links.tsv と、その前後の文字列から得た）
    "docs": [
        ("r8_kaisei_tsuchi", f"{SOUMU}/main_content/001069033.pdf",
         "令和8年4月1日 総税企第44号「地方税法、同法施行令、同法施行規則の改正等について」（t_tsutatsu）"),
        ("r8_ryuiten", f"{SOUMU}/main_content/001052119.pdf",
         "令和8年度地方税制改正・地方税務行政の運営に当たっての留意事項等について（ichiran04）"),
        ("r8_gaiyo", f"{SOUMU}/main_content/001047636.pdf", "令和8年度税制改正の概要（地方税）（ichiran04）"),
        ("r8_houritsu_sansho", f"{SOUMU}/main_content/001060866.pdf", "地方税法等の一部を改正する法律（令和8年法律第2号）参照条文（ichiran04）"),
        ("toriatsukai_shichoson_zenbun", f"{SOUMU}/main_content/001071661.pdf",
         "地方税法の施行に関する取扱いについて（市町村税関係）改正後全文（ichiran04 の令和8年の「改正後全文」）"),
        ("toriatsukai_dofuken_zenbun", f"{SOUMU}/main_content/001087182.pdf",
         "地方税法の施行に関する取扱いについて（道府県税関係）改正後全文（ichiran04 の令和8年の「改正後全文」）"),
        ("toriatsukai_shichoson_r8_honbun", f"{SOUMU}/main_content/001067041.pdf", "同（市町村税関係）の一部改正について（総税市第25号）本文"),
        ("toriatsukai_shichoson_r8_betten1", f"{SOUMU}/main_content/001067044.pdf", "同 別添(1)"),
        ("r7_kaisei_tsuchi", f"{SOUMU}/main_content/001004707.pdf",
         "令和7年4月1日 総税企第59号「地方税法、同法施行令、同法施行規則の改正等について」"),
        ("r7_ryuiten", f"{SOUMU}/main_content/000988698.pdf", "令和7年度地方税制改正・地方税務行政の運営に当たっての留意事項等について"),
        ("h30_kaisei_tsuchi", f"{SOUMU}/main_content/000543593.pdf",
         "平成30年4月1日 総税企第50号「地方税法、同法施行令、同法施行規則の改正等について」（給与所得控除・所得金額調整控除・青色申告特別控除の見直しの年）"),
        ("h30_ryuiten", f"{SOUMU}/main_content/000530377.pdf", "平成30年度地方税制改正・地方税務行政の運営に当たっての留意事項等について"),
        ("h30_gaiyo", f"{SOUMU}/main_content/000522323.pdf", "平成30年度税制改正の概要（地方税）"),
    ],
}


class Text(html.parser.HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "dt", "dd", "section", "article"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = [], 0
        self.links, self._a = [], None

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip += 1
        if tag in self.BLOCK:
            self.out.append("\n")
        if tag in ("td", "th"):
            self.out.append(" | ")
        if tag == "a":
            href = dict(attrs).get("href")
            self._a = [href, []] if href else None

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self.skip = max(0, self.skip - 1)
        if tag in self.BLOCK:
            self.out.append("\n")
        if tag == "a" and self._a is not None:
            self.links.append((self._a[0], re.sub(r"\s+", " ", "".join(self._a[1])).strip()))
            self._a = None

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)
            if self._a is not None:
                self._a[1].append(data)

    def text(self):
        t = "".join(self.out)
        t = re.sub(r"[ \t\u3000]+\n", "\n", t)
        t = re.sub(r"\n{3,}", "\n\n", t)
        return t.strip()


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    lm = ""
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            body, st, ct, final = r.read(), r.status, r.headers.get("Content-Type", ""), r.geturl()
            lm = r.headers.get("Last-Modified", "")
    except urllib.error.HTTPError as e:
        body, st, ct, final = e.read(), e.code, e.headers.get("Content-Type", ""), url
    except Exception as e:  # noqa
        body, st, ct, final = repr(e).encode(), None, "", url
    time.sleep(SLEEP)
    return st, ct, final, body, lm


def decode(body, ct):
    m = re.search(r"charset=([\w-]+)", ct or "", re.I)
    cands = [m.group(1)] if m else []
    m2 = re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", body[:4000], re.I)
    if m2:
        cands.append(m2.group(1).decode("ascii", "replace"))
    cands += ["utf-8", "cp932", "euc-jp"]
    for c in cands:
        try:
            return body.decode(c), c
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", "replace"), "utf-8(replace)"


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in SETS:
        print("組の名前を指定する:", ", ".join(SETS))
        sys.exit(2)
    sname = sys.argv[1]
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R3X_chiho-sochi_web_{sname}"
    dl.mkdir(parents=True, exist_ok=False)
    out = ROOT / "scripts" / "results" / "R3X_chiho-sochi_web" / sname
    out.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "set": sname, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "robots": {}, "fetches": []}
    robots = {}
    for name, url, why in SETS[sname]:
        host = urllib.parse.urlsplit(url)
        base = f"{host.scheme}://{host.netloc}"
        if base not in robots:
            rp = urllib.robotparser.RobotFileParser()
            st, ct, final, body, lm = fetch(base + "/robots.txt")
            (dl / f"robots_{host.netloc}.txt").write_bytes(body)
            if st == 200:
                rp.parse(body.decode("utf-8", "replace").splitlines())
            else:
                rp.parse([])  # robots.txt がない（404 など）なら制限なしとして扱う
            robots[base] = rp
            log["robots"][base] = {"status": st, "sha256": hashlib.sha256(body).hexdigest()}
        allowed = robots[base].can_fetch(UA, url)
        entry = {"name": name, "url": url, "why": why, "robots_allowed": allowed}
        if not allowed:
            entry["skipped"] = "robots.txt で禁止"
            log["fetches"].append(entry)
            print("skip(robots)", name, flush=True)
            continue
        st, ct, final, body, lm = fetch(url)
        ext = ".pdf" if (body[:5] == b"%PDF-" or "pdf" in (ct or "").lower()) else ".html"
        raw = dl / f"{name}{ext}"
        raw.write_bytes(body)
        entry.update({"status": st, "content_type": ct, "last_modified": lm, "final_url": final, "bytes": len(body),
                      "sha256": hashlib.sha256(body).hexdigest(), "saved": str(raw.relative_to(ROOT)).replace("\\", "/"),
                      "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
        if ext == ".html" and st == 200:
            s, enc = decode(body, ct)
            p = Text()
            p.feed(s)
            txt = p.text()
            m = re.search(r"<title[^>]*>(.*?)</title>", s, re.I | re.S)
            entry["title"] = re.sub(r"\s+", " ", m.group(1)).strip() if m else None
            entry["encoding"] = enc
            (out / f"{name}.txt").write_text(f"# {name}\n# URL={url}\n# 取得={entry['fetched_at']} status={st} sha256={entry['sha256']}\n\n{txt}\n",
                                             encoding="utf-8")
            with open(out / f"{name}_links.tsv", "w", encoding="utf-8") as f:
                f.write("href(絶対)\t文字列\n")
                for href, label in p.links:
                    f.write(f"{urllib.parse.urljoin(final, href)}\t{label}\n")
            entry["text"] = f"scripts/results/R3X_chiho-sochi_web/{sname}/{name}.txt"
        log["fetches"].append(entry)
        print("ok", name, st, ext, len(body), lm, flush=True)
    (out / "fetch_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", out, dl)


if __name__ == "__main__":
    main()
