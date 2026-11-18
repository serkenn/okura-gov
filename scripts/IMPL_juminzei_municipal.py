"""IMPL juminzei: 住民税の非課税の基準・申告の要否について、市の条例・案内、国会の調査資料などの公開資料を取得し、
本文テキストと、キーワードの前後の文字列を取り出す。

実行:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_juminzei_municipal.py           # 全部
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_juminzei_municipal.py <名前>...  # 指定した対象だけ
    （このときの記録は snippets_partial_<ts>.md / fetch_log_partial_<ts>.json に書く）

標準ライブラリのみ。リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。
- 取得の前にホストごとに robots.txt を読み（urllib.robotparser）、禁止されている URL は取得しない。
- ダウンロードしたもの（HTML・PDF）は .work/downloads/<ts>_IMPL_juminzei_municipal/ に置く（信頼できないデータ。
  中でインタプリタやツールを実行しない。PDF は解析せず保存とハッシュだけ。中身は人が PDF ビューアなどで読む）。
- HTML は html.parser でテキストにし、scripts/results/IMPL_juminzei_municipal/<名前>.txt に書く。
- キーワードの前後は scripts/results/IMPL_juminzei_municipal/snippets.md、取得の記録は fetch_log.json。
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

# (名前, URL, 何のために取るか)
TARGETS = [
    ("sapporo_shizei_jorei", "https://www.city.sapporo.jp/ncms/reiki/d1w_reiki_nonframe/H325901010044/H325901010044_j.html",
     "政令指定都市の条例の例：札幌市税条例（現行）。均等割の非課税の基本額・加算額、申告不要の条例の定め"),
    ("sapporo_shizei_jorei_misikou", "https://www.city.sapporo.jp/ncms/reiki/d1w_reiki_nonframe/H325901010044/H325901010044_misikou_j.html",
     "札幌市税条例の未施行の改正"),
    ("yokohama_r8kaisei", "https://www.city.yokohama.lg.jp/kurashi/koseki-zei-hoken/zeikin/y-shizei/kojin-shiminzei-kenminzei/R8kaisei.html",
     "横浜市：令和8年度の個人市民税・県民税の改正"),
    ("yokohama_shosai", "https://www.city.yokohama.lg.jp/kurashi/koseki-zei-hoken/zeikin/y-shizei/kojin-shiminzei-kenminzei/kojin-shiminzei-shosai/index.html",
     "横浜市：個人市民税・県民税の詳細（非課税の基準の案内があるか）"),
    ("sendai_r9kaisei", "https://www.city.sendai.jp/shiminze-kikaku/kurashi/tetsuzuki/zekin/kojin/kaisei/r8.html",
     "仙台市：令和9年度（令和8年分）から適用される改正"),
    ("kobe_r9kaisei", "https://www.city.kobe.lg.jp/a83576/kurashi/tax/shikenminze/r9kaisei.html",
     "神戸市：令和9年度の改正"),
    ("chiba_r9kaisei", "https://www.city.chiba.jp/zaiseikyoku/zeimu/kazeikanri/zeiseikaiseijuminzei2027.html",
     "千葉市：令和9年度から適用される改正"),
    ("osaka_pref_r8zeikai", "https://www.pref.osaka.lg.jp/o050030/zei/alacarte/reiwa8_zeikai.html",
     "大阪府：令和8年度税制改正（個人住民税）"),
    ("setagaya_hikazei", "https://www.city.setagaya.lg.jp/02051/220.html",
     "世田谷区：住民税が課税されない方（令和8年度以降の式）"),
    ("edogawa_hikazei", "https://www.city.edogawa.tokyo.jp/e013/kurashi/zeikin/juminzei/zei_gaiyo/hikazei.html",
     "江戸川区：非課税の基準"),
    ("sangiin_rippou_486", "https://www.sangiin.go.jp/japanese/annai/chousa/rippou_chousa/backnumber/2026pdf/20260806162.pdf",
     "参議院『立法と調査』（2026-08-06）：個人住民税における課税最低限と非課税限度額制度"),
    ("soumu_kojin_juminzei", "https://www.soumu.go.jp/main_sosiki/jichi_zeisei/czaisei/czaisei_seido/150790_06.html",
     "総務省：個人住民税の案内ページ（URL は推測。存在しなければ記録だけ）"),
    # 総務省「地方税法の施行に関する取扱いについて（市町村税関係）」（技術的助言の通知）。
    # リンクは https://www.soumu.go.jp/main_sosiki/jichi_zeisei/czaisei/czaisei_seido/ichiran04.html の一覧から得た。
    ("soumu_ichiran04", "https://www.soumu.go.jp/main_sosiki/jichi_zeisei/czaisei/czaisei_seido/ichiran04.html",
     "総務省：税制改正（地方税）の一覧。取扱通知の PDF へのリンク元"),
    ("soumu_tsuchi_r8_honbun", "https://www.soumu.go.jp/main_content/001067041.pdf",
     "取扱通知（市町村税関係）の一部改正について（総税市第25号）本文"),
    ("soumu_tsuchi_r8_betten1", "https://www.soumu.go.jp/main_content/001067044.pdf", "同 別添(1)"),
    ("soumu_tsuchi_r8_betten2", "https://www.soumu.go.jp/main_content/001067045.pdf", "同 別添(2)"),
    ("soumu_tsuchi_r8_betten3", "https://www.soumu.go.jp/main_content/001067046.pdf", "同 別添(3)"),
    ("soumu_tsuchi_r8_shinkyu", "https://www.soumu.go.jp/main_content/001071661.pdf", "同 改正後全文（令和8年。一覧ページのリンク文字列は「改正後全文」。名前の shinkyu は取得時の誤り）"),
    ("soumu_tsuchi_r7_zenbun", "https://www.soumu.go.jp/main_content/001007020.pdf",
     "取扱通知（市町村税関係）令和7年の改正後全文（一覧ページのリンク文字列は「改正後全文」）"),
    ("kashiwa_r8hikazei", "https://www.city.kashiwa.lg.jp/shiminzei/kojinshiminzei/r8hikazei.html",
     "柏市（2級地）：令和8年度以降の非課税の基準"),
    ("meguro_miseinen", "https://www.city.meguro.tokyo.jp/zeimu/kurashi/juuminzei/zeiseikaisei5.html",
     "目黒区：成年年齢の引下げと住民税の未成年者の非課税（生年月日の境目）"),
    ("yokohama_konan_miseinen", "https://www.city.yokohama.lg.jp/konan/kurashi/koseki_zei_hoken/zeikin/kojin/miseinensha.html",
     "横浜市港南区：未成年者の住民税"),
    ("saitama_miseinen", "https://www.city.saitama.lg.jp/001/153/004/002/001/003/p092338.html",
     "さいたま市：未成年者の非課税（成年年齢の引下げ）"),
]

KEYWORDS = ["非課税", "課さない", "課することができない", "35万円", "三十五万円", "21万円", "二十一万円", "32万円", "10万円",
            "合計所得金額", "級地", "均等割", "所得割", "未成年", "申告", "第295条", "第二百九十五条", "74万円", "69万円", "給与所得控除",
            "令和8年度", "令和9年度", "令和10年度"]


class Text(html.parser.HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "dt", "dd", "section", "article"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip += 1
        if tag in self.BLOCK:
            self.out.append("\n")
        if tag in ("td", "th"):
            self.out.append(" | ")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self.skip = max(0, self.skip - 1)
        if tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)

    def text(self):
        t = "".join(self.out)
        t = re.sub(r"[ \t\u3000]+\n", "\n", t)
        t = re.sub(r"\n{3,}", "\n\n", t)
        return t.strip()


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            body, st, ct, final = r.read(), r.status, r.headers.get("Content-Type", ""), r.geturl()
    except urllib.error.HTTPError as e:
        body, st, ct, final = e.read(), e.code, e.headers.get("Content-Type", ""), url
    except Exception as e:  # noqa
        body, st, ct, final = repr(e).encode(), None, "", url
    time.sleep(SLEEP)
    return st, ct, final, body


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
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_IMPL_juminzei_municipal"
    dl.mkdir(parents=True, exist_ok=False)
    out = ROOT / "scripts" / "results" / "IMPL_juminzei_municipal"
    out.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "robots": {}, "fetches": []}
    robots = {}
    # 引数で名前を指定すると、その対象だけを取得する（例: soumu_tsuchi_r8_betten1）。結果のファイル名に接尾辞をつける。
    only = set(sys.argv[1:])
    suffix = "" if not only else "_partial_" + ts
    log["only"] = sorted(only)
    snippets = [f"# キーワードの前後（IMPL_juminzei_municipal.py, 取得 {ts}）", ""]
    for name, url, why in TARGETS:
        if only and name not in only:
            continue
        host = urllib.parse.urlsplit(url)
        base = f"{host.scheme}://{host.netloc}"
        if base not in robots:
            rp = urllib.robotparser.RobotFileParser()
            st, ct, final, body = fetch(base + "/robots.txt")
            (dl / f"robots_{host.netloc}.txt").write_bytes(body)
            if st == 200:
                rp.parse(body.decode("utf-8", "replace").splitlines())
            else:
                rp.parse([])  # robots.txt がない（404 など）なら制限なしとして扱う
            robots[base] = rp
            log["robots"][base] = {"status": st}
        allowed = robots[base].can_fetch(UA, url)
        entry = {"name": name, "url": url, "why": why, "robots_allowed": allowed}
        if not allowed:
            entry["skipped"] = "robots.txt で禁止"
            log["fetches"].append(entry)
            print("skip(robots)", name, flush=True)
            continue
        st, ct, final, body = fetch(url)
        ext = ".pdf" if (b"%PDF" in body[:8] or "pdf" in (ct or "").lower()) else ".html"
        raw = dl / f"{name}{ext}"
        raw.write_bytes(body)
        entry.update({"status": st, "content_type": ct, "final_url": final, "bytes": len(body),
                      "sha256": hashlib.sha256(body).hexdigest(), "saved": str(raw.relative_to(ROOT)),
                      "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
        if ext == ".html" and st == 200:
            s, enc = decode(body, ct)
            p = Text()
            p.feed(s)
            txt = p.text()
            m = re.search(r"<title[^>]*>(.*?)</title>", s, re.I | re.S)
            entry["title"] = re.sub(r"\s+", " ", m.group(1)).strip() if m else None
            entry["encoding"] = enc
            (out / f"{name}.txt").write_text(f"# {name}\n# URL={url}\n# 取得={entry['fetched_at']} status={st} sha256={entry['sha256']}\n\n{txt}\n", encoding="utf-8")
            entry["text"] = f"scripts/results/IMPL_juminzei_municipal/{name}.txt"
            flat = re.sub(r"\s+", " ", txt)
            snippets += [f"## {name}", f"- URL: {url}", f"- 目的: {why}", ""]
            for k in KEYWORDS:
                hits = [mm.start() for mm in re.finditer(re.escape(k), flat)]
                if not hits:
                    continue
                snippets.append(f"### {k}（{len(hits)} 件。先頭 8 件）")
                for h in hits[:8]:
                    snippets.append(f"- …{flat[max(0, h - 80):h + 160]}…")
                snippets.append("")
        log["fetches"].append(entry)
        print("ok", name, st, ext, len(body), flush=True)
    (out / f"snippets{suffix}.md").write_text("\n".join(snippets) + "\n", encoding="utf-8")
    (out / f"fetch_log{suffix}.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", out)


if __name__ == "__main__":
    main()
