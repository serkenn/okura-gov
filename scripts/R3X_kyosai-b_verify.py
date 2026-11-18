"""R3X kyosai-b 検証（反証役）：共済組合の被扶養者の認定基準（大臣の定め）の文書
（docs/*/20261109_round3_kyosai-b-*.md）に書かれた数値・番号・日付・適用日・URL・引用を、一次情報を取り直して確かめる。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_kyosai-b_verify.py fetch
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_kyosai-b_verify.py fetch_cmap
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_kyosai-b_verify.py fetch_extra
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_kyosai-b_verify.py check [<ダウンロード先のディレクトリ>]
  （check は最新の fetch・fetch_cmap・fetch_extra の結果を使う）

fetch_cmap（ネットワークを使う）:
  - 運用方針（抄）の PDF は CID フォントに /ToUnicode がない。Adobe の CMap 資源（UniJIS-UTF16-H/V）をデータとして取得し、
    正規表現で読んで CID → Unicode の逆引きを作る（実行しない）。.work/downloads/<ts>_R3X_kyosai-b_verify_cmap/
fetch_extra（ネットワークを使う）:
  - 文書の抜けの確認（私学共済事業の 19〜23歳の Q&A）、実測の K2 の表のほかの2案件、地方の運用方針の転載を探した資料（404）。
    .work/downloads/<ts>_R3X_kyosai-b_verify_extra/

fetch（ネットワークを使う）:
  - 担当が使った一次情報（財務省の運用方針の全文 PDF と通達一覧、Internet Archive の旧版、裁判所共済組合の写し、
    e-Gov パブリック・コメントの結果の公示、公立学校共済組合東京支部の案内と添付 PDF、地方職員共済組合のチラシ、
    宮城県市町村職員共済組合のお知らせ、運用方針（抄）、防衛省共済組合の Q&A、私学共済事業の法令集）を取り直す。
  - 反証のための追加の取得：e-Gov パブリック・コメントの案件番号 395081950〜395081958（財務省の同じ番号帯。
    財計第3839号・第1627号・第1988号の案件があるかを見る）、e-Gov 法令API v2 の条文（国共済令・地共済令・私学令の第3条、
    行政手続法第39条、国共済法第3条・第53条、地共済法第55条）。
  - 取得したファイルは信頼できないデータとして、新しい空のディレクトリ .work/downloads/<YYYYMMDD-HHMMSS>_R3X_kyosai-b_verify/ に置く
    （その中で何も実行しない）。リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。個人の情報は送らない。官報は取得しない。
  - 取得記録：scripts/results/R3X_kyosai-b_verify/fetch_<ts>.json
check（ネットワークを使わない）:
  - 取り直したファイルを読むだけ（PDF・HTML・JSON を解釈して実行することはない）。
  - PDF の文字の取り出しは、担当のスクリプト scripts/R3X_kyosai-b_pdftext.py の低い層（RC4・AESV2・AESV3 の復号、オブジェクトの読み出し、
    /ToUnicode）を写した（import はしない）。文字列の並べ方は担当と変え、**内容ストリームに現れた順のまま**つなぐ（担当は y・x で並べ替えた）。
    低い層は同じコードなので独立ではない。独立の確認は、(1) 取り直したファイルの SHA-256 と担当の取得の一致、(2) 描画を目で読む照合
    （実測の文書に記録）で補う。
  - 出力：scripts/results/R3X_kyosai-b_verify/
      text/<id>.txt          取り直した資料の頁ごとの文字列（PDF は内容ストリームの順、HTML は抽出したテキスト、法令は条のテキスト）
      checks.json            検査 V1〜V11・V13 の結果（V12 は quote_audit.json）
      check_stdout.txt       check の要約の表示（リダイレクトで保存）
      quote_audit.json       3つの文書の「」と > の引用が、取り直した資料のどれに（正規化して）含まれるか
"""
import glob
import hashlib
import html.parser
import json
import pathlib
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "okura-gov-research/0.1"
WAIT = 1.5
MAXBYTES = 64 * 1024 * 1024
MAXOUT = 64 * 1024 * 1024
OUT = ROOT / "scripts" / "results" / "R3X_kyosai-b_verify"
PRIOR = ROOT / "scripts" / "results" / "R3X_kyosai-b_fetch"
API = "https://laws.e-gov.go.jp/api/2"
PCM = "https://public-comment.e-gov.go.jp/servlet/Public?CLASSNAME=PCM1040&Mode=1&id="
DOCS = {
    "PS": ROOT / "docs" / "public-sources" / "20261109_round3_kyosai-b-ministerial-criteria.md",
    "MS": ROOT / "docs" / "measurements" / "20261109_round3_kyosai-b-fetch-and-checks.md",
    "HY": ROOT / "docs" / "hypotheses" / "20261109_round3_kyosai-b-parameters.md",
}

# 担当の取得の id（scripts/results/R3X_kyosai-b_fetch/*.json）と同じ id で取り直す
WEB = {
    "mof_unyo_hoshin_current": "https://www.mof.go.jp/about_mof/act/kokuji_tsuutatsu/tsuutatsu/TU-19591001-2927-11.pdf",
    "mof_tsuutatsu_s": "https://www.mof.go.jp/about_mof/act/kokuji_tsuutatsu/tsuutatsu/tsuutatsu_s.htm",
    "wb_20250721_mof_unyo": "https://web.archive.org/web/20250721103617id_/https://www.mof.go.jp/about_mof/act/kokuji_tsuutatsu/tsuutatsu/TU-19591001-2927-11.pdf",
    "wb_20260926_mof_unyo": "https://web.archive.org/web/20260926161059id_/https://www.mof.go.jp/about_mof/act/kokuji_tsuutatsu/tsuutatsu/TU-19591001-2927-11.pdf",
    "courts_unyo_hoshin": "https://www.kyousai.courts.or.jp/files/user/img/houki/1-01.pdf",
    "pcm_395081949": PCM + "395081949",
    "mhlw_pcm_495250041": PCM + "495250041",
    "kouritu_tokyo_19_23": "https://www.kouritu.or.jp/tokyo/topics/19-23kizyungaku/index.html",
    "kouritu_tokyo_00_tsuchi": "https://www.kouritu.or.jp/tokyo/content/files/0f79f0f5da86d0d0a0fef9885fb76e23.pdf",
    "kouritu_tokyo_03_soumu": "https://www.kouritu.or.jp/tokyo/content/files/3ba94cb45594628e0778652af5dc4b35.pdf",
    "chikyosai_info_250924": "https://www.chikyosai.or.jp/info/short/pdf/info_250924.pdf",
    "miyagi_fget96": "https://www.kyosai-miyagi.or.jp/osirase/fget96",
    "sigichokai_hoshin_kyosai": "https://www.si-gichokai.jp/kyousai/nenkin_gaiyo/pdf/hoshin_kyosai.pdf",
    "boueikyosai_164": "https://www.boueikyosai.or.jp/site/folder1/164.html",
    "pmac_kanko_hourei": "https://www.pmac.shigaku.go.jp/annai/kanko/jimu/hourei/index.html",
    "pmac_hourei_mokuji_2026": "https://www.pmac.shigaku.go.jp/annai/kanko/jimu/hourei/ndc94q0000002jy6-att/hourei_hanrei_mokuji_2026.pdf",
    "pmac_hourei_sonota_2026": "https://www.pmac.shigaku.go.jp/annai/kanko/jimu/hourei/ndc94q0000002jy6-att/hourei_sonota_2026.pdf",
}
# 反証のための追加：同じ番号帯のパブリック・コメントの案件（財計第3839号・第1627号・第1988号の案件を探す）
PROBE = {f"pcm_probe_{n}": PCM + str(n) for n in range(395081950, 395081959)}
# e-Gov 法令API v2：(id, law_id, asof, [本則の条番号])
LAWS = [
    ("law_kokkyo_rei", "333CO0000000207", "2025-10-01", ["3"]),
    ("law_chikyo_rei", "337CO0000000352", "2025-10-01", ["2", "3", "4"]),
    ("law_shigaku_rei", "328CO0000000425", "2025-10-01", ["3"]),
    ("law_gyotetsu", "405AC0000000088", "2025-08-12", ["39"]),
    ("law_kokkyo", "333AC0000000128", "2026-11-09", ["3", "53"]),
    ("law_chikyo", "337AC0000000152", "2026-11-09", ["55"]),
]


# ================================================================ 取得
class Extract(html.parser.HTMLParser):
    """scripts/R3X_kyosai-b_fetch.py の Extract を写した（HTML からテキストとリンクを取り出す）。"""
    SKIP = {"script", "style", "noscript"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.links, self.title = [], [], ""
        self._skip = 0
        self._in_title = False
        self._href = None
        self._atext = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in self.SKIP:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag == "a" and a.get("href"):
            self._href = a["href"]
            self._atext = []
        if tag in ("br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "dt", "dd", "table"):
            self.parts.append("\n")
        if tag in ("td", "th"):
            self.parts.append(" | ")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False
        if tag == "a" and self._href is not None:
            self.links.append({"href": self._href, "text": " ".join("".join(self._atext).split())})
            self._href = None
        if tag in ("p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "dd"):
            self.parts.append("\n")

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title:
            self.title += data
        if self._href is not None:
            self._atext.append(data)
        self.parts.append(data)

    def text(self):
        t = "".join(self.parts)
        t = re.sub(r"[ \t　]+\n", "\n", t)
        t = re.sub(r"\n{3,}", "\n\n", t)
        return t.strip()


def http_get(url, accept=None):
    h = {"User-Agent": UA, "Accept-Language": "ja"}
    if accept:
        h["Accept"] = accept
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            deadline = time.monotonic() + 120
            chunks, n = [], 0
            while True:
                b = r.read(65536)
                if not b:
                    break
                chunks.append(b)
                n += len(b)
                if n > MAXBYTES:
                    raise ValueError("body too large")
                if time.monotonic() > deadline:
                    raise TimeoutError("body read timeout")
            return r.status, r.geturl(), dict(r.headers), b"".join(chunks)
    except urllib.error.HTTPError as e:
        try:
            body = e.read()
        except Exception:  # noqa: BLE001
            body = b""
        return e.code, url, dict(e.headers or {}), body


def ext_for(ctype, url, body):
    c = (ctype or "").lower()
    if body[:5] == b"%PDF-" or "pdf" in c:
        return ".pdf"
    if "json" in c:
        return ".json"
    if "html" in c:
        return ".html"
    return ".bin"


def fetch():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R3X_kyosai-b_verify"
    dl.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    log = {"fetched_at_local": ts, "user_agent": UA, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "results": []}
    jobs = [(k, v, None) for k, v in WEB.items()] + [(k, v, None) for k, v in PROBE.items()]
    jobs += [(lid, f"{API}/law_data/{law_id}?" + urllib.parse.urlencode({"response_format": "json", "asof": asof}), "application/json")
             for lid, law_id, asof, _ in LAWS]
    for i, (sid, url, accept) in enumerate(jobs):
        if i:
            time.sleep(WAIT)
        rec = {"id": sid, "url": url}
        try:
            st, final, hdr, body = http_get(url, accept)
            ctype = hdr.get("Content-Type", "")
            ext = ext_for(ctype, final, body)
            p = dl / f"{sid}{ext}"
            p.write_bytes(body)
            rec.update({"status": st, "final_url": final, "content_type": ctype, "bytes": len(body),
                        "sha256": hashlib.sha256(body).hexdigest(), "last_modified": hdr.get("Last-Modified"),
                        "saved": str(p.relative_to(ROOT)).replace("\\", "/")})
        except Exception as e:  # noqa: BLE001
            rec["error"] = repr(e)
        log["results"].append(rec)
        (OUT / f"fetch_{ts}.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps({k: rec.get(k) for k in ("id", "status", "bytes", "last_modified", "error")}, ensure_ascii=False), flush=True)
    return 0


EXTRA = {
    # 担当が取得したが文書に書かれていない私学の案内（19歳以上23歳未満の Q&A：年齢の判定時点、配偶者の範囲、続柄）
    "pmac_qa_48": "https://www.pmac.shigaku.go.jp/qa/detail/qa_48.html",
    # 実測の文書の K2 の表に載る、ほかの2つの案件（財計第1701号・第3570号）
    "pcm_395081944": PCM + "395081944",
    "pcm_395081959": PCM + "395081959",
    # 反証：地方の運用方針の第一項第二号を転載していると見える東京都職員共済組合の資料（Web 検索 1 回で見つけた URL。検索の要約は根拠にしない）
    "tokyo_kyosai_ninteikijun01": "https://www.kyosai.metro.tokyo.jp/prv/qualification/fuyou/data/ninteikijun01.pdf",
    "tokyo_kyosai_4072f241": "https://www.kyosai.metro.tokyo.jp/prv/author6223e/data/4072f241d4166e0248ecf07cc52fe0d5.pdf",
}


def fetch_extra():
    """文書の抜けを確かめるための追加の取得（新しい空のディレクトリ .work/downloads/<ts>_R3X_kyosai-b_verify_extra/）。"""
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R3X_kyosai-b_verify_extra"
    dl.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    log = {"fetched_at_local": ts, "user_agent": UA, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "results": []}
    for i, (sid, url) in enumerate(EXTRA.items()):
        if i:
            time.sleep(WAIT)
        rec = {"id": sid, "url": url}
        try:
            st, final, hdr, body = http_get(url)
            pth = dl / f"{sid}{ext_for(hdr.get('Content-Type', ''), final, body)}"
            pth.write_bytes(body)
            rec.update({"status": st, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
                        "last_modified": hdr.get("Last-Modified"), "saved": str(pth.relative_to(ROOT)).replace("\\", "/")})
        except Exception as e:  # noqa: BLE001
            rec["error"] = repr(e)
        log["results"].append(rec)
        print(json.dumps({k: rec.get(k) for k in ("id", "status", "bytes", "error")}, ensure_ascii=False), flush=True)
    (OUT / f"fetch_extra_{ts}.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


def fetch_cmap():
    """運用方針（抄）の PDF（SIGI）は縦書きの CID フォントに /ToUnicode がなく、文字を取り出せない。
    Adobe の CMap 資源（adobe-type-tools/cmap-resources、Adobe-Japan1-7 の UniJIS-UTF16-H/V）を、データとして取得する
    （新しい空のディレクトリに置き、テキストとして読むだけ。実行しない）。"""
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R3X_kyosai-b_verify_cmap"
    dl.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    log = {"fetched_at_local": ts, "user_agent": UA, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "results": []}
    for i, (name, url) in enumerate(CMAP_URLS.items()):
        if i:
            time.sleep(WAIT)
        rec = {"id": name, "url": url}
        try:
            st, final, hdr, body = http_get(url)
            p = dl / f"{name}.cmap"
            p.write_bytes(body)
            rec.update({"status": st, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
                        "first_line": body[:200].decode("latin-1").splitlines()[0] if body else "",
                        "saved": str(p.relative_to(ROOT)).replace("\\", "/")})
        except Exception as e:  # noqa: BLE001
            rec["error"] = repr(e)
        log["results"].append(rec)
        print(json.dumps({k: rec.get(k) for k in ("id", "status", "bytes", "error")}, ensure_ascii=False), flush=True)
    (OUT / f"fetch_cmap_{ts}.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


# ================================================================ PDF（scripts/R3X_kyosai-b_pdftext.py の低い層を写した）
def _xt(a):
    return ((a << 1) ^ 0x1B) & 0xFF if a & 0x80 else a << 1


def _gmul(a, b):
    r = 0
    while b:
        if b & 1:
            r ^= a
        a = _xt(a)
        b >>= 1
    return r


def _sbox():
    inv = [0] * 256
    for a in range(1, 256):
        for b in range(1, 256):
            if _gmul(a, b) == 1:
                inv[a] = b
                break
    s = []
    for a in range(256):
        x = inv[a]
        y = x
        for i in range(1, 5):
            y ^= ((x << i) | (x >> (8 - i))) & 0xFF
        s.append(y ^ 0x63)
    si = [0] * 256
    for i, v in enumerate(s):
        si[v] = i
    return s, si


SBOX, INV_SBOX = _sbox()
M2, M3, M9, M11, M13, M14 = ([_gmul(x, k) for x in range(256)] for k in (2, 3, 9, 11, 13, 14))


def aes_expand_n(key):
    nk = len(key) // 4
    nr = nk + 6
    w = [list(key[i:i + 4]) for i in range(0, len(key), 4)]
    rcon = 1
    for i in range(nk, 4 * (nr + 1)):
        t = list(w[i - 1])
        if i % nk == 0:
            t = t[1:] + t[:1]
            t = [SBOX[x] for x in t]
            t[0] ^= rcon
            rcon = _xt(rcon)
        elif nk > 6 and i % nk == 4:
            t = [SBOX[x] for x in t]
        w.append([w[i - nk][j] ^ t[j] for j in range(4)])
    return [sum(w[r * 4:r * 4 + 4], []) for r in range(nr + 1)], nr


def aes_encrypt_block_n(rk, nr, block):
    s = [b ^ k for b, k in zip(block, rk[0])]
    for rnd in range(1, nr + 1):
        s = [SBOX[x] for x in s]
        s = [s[((c + r) % 4) * 4 + r] for c in range(4) for r in range(4)]
        if rnd != nr:
            ns = []
            for c in range(4):
                a = s[c * 4:c * 4 + 4]
                ns += [M2[a[0]] ^ M3[a[1]] ^ a[2] ^ a[3], a[0] ^ M2[a[1]] ^ M3[a[2]] ^ a[3],
                       a[0] ^ a[1] ^ M2[a[2]] ^ M3[a[3]], M3[a[0]] ^ a[1] ^ a[2] ^ M2[a[3]]]
            s = ns
        s = [x ^ k for x, k in zip(s, rk[rnd])]
    return bytes(s)


def aes_decrypt_block_n(rk, nr, block):
    s = [b ^ k for b, k in zip(block, rk[nr])]
    for rnd in range(nr - 1, -1, -1):
        s = [s[((c - r) % 4) * 4 + r] for c in range(4) for r in range(4)]
        s = [INV_SBOX[x] for x in s]
        s = [x ^ k for x, k in zip(s, rk[rnd])]
        if rnd:
            ns = []
            for c in range(4):
                a = s[c * 4:c * 4 + 4]
                ns += [M14[a[0]] ^ M11[a[1]] ^ M13[a[2]] ^ M9[a[3]], M9[a[0]] ^ M14[a[1]] ^ M11[a[2]] ^ M13[a[3]],
                       M13[a[0]] ^ M9[a[1]] ^ M14[a[2]] ^ M11[a[3]], M11[a[0]] ^ M13[a[1]] ^ M9[a[2]] ^ M14[a[3]]]
            s = ns
    return bytes(s)


def aes_cbc_encrypt_nopad(key, iv, data):
    rk, nr = aes_expand_n(key)
    out, prev = bytearray(), iv
    for i in range(0, len(data), 16):
        prev = aes_encrypt_block_n(rk, nr, bytes(x ^ y for x, y in zip(data[i:i + 16], prev)))
        out += prev
    return bytes(out)


def aes_cbc_decrypt_n(key, iv, data, unpad=True):
    rk, nr = aes_expand_n(key)
    out, prev = bytearray(), iv
    for i in range(0, len(data) - len(data) % 16, 16):
        blk = data[i:i + 16]
        out += bytes(x ^ y for x, y in zip(aes_decrypt_block_n(rk, nr, blk), prev))
        prev = blk
    if unpad and out and 1 <= out[-1] <= 16:
        out = out[:-out[-1]]
    return bytes(out)


def aes_selftest():
    pt = bytes.fromhex("00112233445566778899aabbccddeeff")
    res = {}
    for name, key, ct in (("FIPS197_C1_AES128", bytes(range(16)), "69c4e0d86a7b0430d8cdb78070b4c55a"),
                          ("FIPS197_C3_AES256", bytes(range(32)), "8ea2b7ca516745bfeafc49904b496089")):
        rk, nr = aes_expand_n(key)
        res[name] = aes_encrypt_block_n(rk, nr, pt).hex() == ct and aes_decrypt_block_n(rk, nr, bytes.fromhex(ct)) == pt
    return res


PAD = bytes.fromhex("28BF4E5E4E758A4164004E56FFFA01082E2E00B6D0683E802F0CA9FE6453697A")


def _rc4(key, data):
    S = list(range(256))
    j = 0
    for i in range(256):
        j = (j + S[i] + key[i % len(key)]) % 256
        S[i], S[j] = S[j], S[i]
    i = j = 0
    out = bytearray()
    for b in data:
        i = (i + 1) % 256
        j = (j + S[i]) % 256
        S[i], S[j] = S[j], S[i]
        out.append(b ^ S[(S[i] + S[j]) % 256])
    return bytes(out)


def inflate(b):
    d = zlib.decompressobj()
    out = d.decompress(b, MAXOUT)
    if d.unconsumed_tail:
        raise ValueError("inflate: 上限を超えた")
    return out


def unescape_literal(s):
    out, i = bytearray(), 0
    while i < len(s):
        c = s[i]
        if c == 0x5C and i + 1 < len(s):
            n = s[i + 1]
            mp = {ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12, ord("("): 40, ord(")"): 41, ord("\\"): 92}
            if n in mp:
                out.append(mp[n])
                i += 2
                continue
            m = re.match(rb"[0-7]{1,3}", s[i + 1:i + 4])
            if m:
                out.append(int(m.group(0), 8) & 0xFF)
                i += 1 + len(m.group(0))
                continue
            i += 1
            continue
        out.append(c)
        i += 1
    return bytes(out)


def raw_objects(pdf):
    for m in re.finditer(rb"(\d+)\s+(\d+)\s+obj\b", pdf):
        end = pdf.find(b"endobj", m.end())
        body = pdf[m.end():end]
        sm = re.search(rb"stream\r?\n", body)
        if not sm:
            yield int(m.group(1)), int(m.group(2)), body, None
            continue
        dic = body[:sm.start()]
        lm = re.search(rb"/Length\s+(\d+)(?!\s+\d+\s+R)", dic)
        raw = body[sm.end():sm.end() + int(lm.group(1))] if lm else body[sm.end():body.rfind(b"endstream")].rstrip(b"\r\n")
        yield int(m.group(1)), int(m.group(2)), dic, raw


def pdfstr(b, key):
    m = re.search(rb"/" + key + rb"\s*<([0-9a-fA-F]+)>", b)
    if m:
        return bytes.fromhex(m.group(1).decode())
    m = re.search(rb"/" + key + rb"\s*\(((?:[^()\\]|\\.)*)\)", b, re.S)
    return unescape_literal(m.group(1))


def _hash_r6(password, salt, udata, r):
    k = hashlib.sha256(password + salt + udata).digest()
    if r == 5:
        return k
    i = 0
    while True:
        k1 = (password + k + udata) * 64
        e = aes_cbc_encrypt_nopad(k[:16], k[16:32], k1)
        h = (hashlib.sha256, hashlib.sha384, hashlib.sha512)[sum(e[:16]) % 3]
        k = h(e).digest()
        i += 1
        if i >= 64 and e[-1] <= i - 32:
            break
    return k[:32]


def _objstm(objs):
    for num, (dic, dec) in list(objs.items()):
        if dec is not None and b"/ObjStm" in dic and not dec.startswith(b"<<inflate error"):
            nn = int(re.search(rb"/N\s+(\d+)", dic).group(1))
            first = int(re.search(rb"/First\s+(\d+)", dic).group(1))
            hdr = [int(x) for x in dec[:first].split()]
            pairs = [(hdr[i], hdr[i + 1]) for i in range(0, min(len(hdr), 2 * nn), 2)]
            for i, (onum, off) in enumerate(pairs):
                end = pairs[i + 1][1] if i + 1 < len(pairs) else len(dec) - first
                objs.setdefault(onum, (dec[first + off:first + end], None))


def load(pdf):
    enc = re.search(rb"/Filter\s*/Standard", pdf)
    key, key_ok, alg = None, None, None
    objs = {}
    if enc:
        ostart = pdf.rfind(b" obj", 0, enc.start())
        oend = pdf.find(b"endobj", enc.start())
        edict = pdf[ostart:oend] if ostart >= 0 and oend > 0 else pdf
        v = int(re.search(rb"/V\s*(\d+)", edict).group(1))
        r = int(re.search(rb"/R\s*(\d+)", edict).group(1))
        if v >= 5:
            u, ue = pdfstr(edict, rb"U"), pdfstr(edict, rb"UE")
            key_ok = (_hash_r6(b"", u[32:40], b"", r) == u[:32])
            if not key_ok:
                return {}, False, f"AESV3(V{v},R{r}) 空のユーザーパスワードで開けない"
            key = aes_cbc_decrypt_n(_hash_r6(b"", u[40:48], b"", r), bytes(16), ue[:32], unpad=False)
            alg = f"AESV3(V{v},R{r})"
            for num, gen, dic, raw in raw_objects(pdf):
                if raw is None:
                    objs[num] = (dic, None)
                    continue
                dec = raw
                if b"/XRef" not in dic and len(raw) >= 32:
                    dec = aes_cbc_decrypt_n(key, raw[:16], raw[16:])
                if b"FlateDecode" in dic:
                    try:
                        dec = inflate(dec)
                    except Exception as e:  # noqa: BLE001
                        dec = b"<<inflate error " + repr(e).encode() + b">>"
                objs[num] = (dic, dec)
            _objstm(objs)
            return objs, key_ok, alg
        o, u = pdfstr(edict, rb"O"), pdfstr(edict, rb"U")
        p = int(re.search(rb"/P\s*(-?\d+)", edict).group(1))
        id0 = pdfstr(pdf, rb"ID\s*\[")
        lm = re.search(rb"/Length\s*(\d+)", re.sub(rb"/CF\s*<<.*?>>\s*>>", b"", edict, flags=re.S))
        n = 16 if r >= 3 else 5
        if r >= 3 and lm and int(lm.group(1)) in (40, 128):
            n = int(lm.group(1)) // 8
        no_meta = r >= 4 and re.search(rb"/EncryptMetadata\s*false", edict) is not None
        h = hashlib.md5(PAD + o + (p & 0xFFFFFFFF).to_bytes(4, "little") + id0 + (b"\xff\xff\xff\xff" if no_meta else b"")).digest()
        if r >= 3:
            for _ in range(50):
                h = hashlib.md5(h[:n]).digest()
        key = h[:n]
        if r >= 3:
            x = _rc4(key, hashlib.md5(PAD + id0).digest())
            for i in range(1, 20):
                x = _rc4(bytes(k ^ i for k in key), x)
            key_ok = (x == u[:16])
        else:
            key_ok = (_rc4(key, PAD) == u)
        alg = ("AESV2" if (v == 4 and b"AESV2" in pdf) else "RC4") + f"(V{v},R{r})"
    for num, gen, dic, raw in raw_objects(pdf):
        if raw is None:
            objs[num] = (dic, None)
            continue
        dec = raw
        if key is not None and b"/XRef" not in dic:
            okey = hashlib.md5(key + num.to_bytes(3, "little") + gen.to_bytes(2, "little") + (b"sAlT" if "AESV2" in alg else b"")).digest()[:min(len(key) + 5, 16)]
            if "AESV2" in alg:
                dec = aes_cbc_decrypt_n(okey, raw[:16], raw[16:])
            else:
                dec = _rc4(okey, raw)
        if b"FlateDecode" in dic:
            try:
                dec = inflate(dec)
            except Exception as e:  # noqa: BLE001
                dec = b"<<inflate error " + repr(e).encode() + b">>"
        objs[num] = (dic, dec)
    _objstm(objs)
    return objs, key_ok, alg


def ref(b, name):
    m = re.search(rb"/" + name + rb"\s*(\d+)\s+0\s+R", b)
    return int(m.group(1)) if m else None


def parse_cmap(b):
    m = {}
    for blk in re.findall(rb"beginbfchar(.*?)endbfchar", b, re.S):
        for a, c in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", blk):
            m[int(a, 16)] = bytes.fromhex(c.decode()).decode("utf-16-be", "replace")
    for blk in re.findall(rb"beginbfrange(.*?)endbfrange", b, re.S):
        for a, z, c in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", blk):
            base = int(c, 16)
            for k in range(int(a, 16), int(z, 16) + 1):
                m[k] = chr(base + k - int(a, 16))
    return m


def font_decoder(objs, fnum):
    dic = objs.get(fnum, (b"", None))[0]
    encm = re.search(rb"/Encoding\s*/([A-Za-z0-9\-]+)", dic)
    enc = encm.group(1).decode() if encm else ""
    tu = ref(dic, rb"ToUnicode")
    if "RKSJ" in enc:
        return lambda raw: raw.decode("cp932", "replace")
    if "UCS2" in enc or "UTF16" in enc:
        return lambda raw: raw.decode("utf-16-be", "replace")
    if tu is not None and objs.get(tu, (None, None))[1]:
        cm = parse_cmap(objs[tu][1])
        if enc.startswith("Identity") or b"/Type0" in dic:
            return lambda raw: "".join(cm.get(int.from_bytes(raw[i:i + 2], "big"), "\ufffd") for i in range(0, len(raw) - 1, 2))
        return lambda raw: "".join(cm.get(c, chr(c)) for c in raw)
    # \u8ffd\u52a0\uff08\u691c\u8a3c\uff09\uff1a/ToUnicode \u304c\u306a\u304f\u3001Identity-H/V \u3067 Adobe-Japan1 \u306e CID \u30d5\u30a9\u30f3\u30c8\u306e\u3068\u304d\u3001
    # Adobe \u306e CMap \u8cc7\u6e90\uff08UniJIS-UTF16-H/V\u3002\u30c7\u30fc\u30bf\u3068\u3057\u3066\u8aad\u3080\u3060\u3051\uff09\u3092\u9006\u306b\u5f15\u3044\u3066 CID \u2192 Unicode \u306b\u3059\u308b
    if AJ1 and enc.startswith("Identity") and b"/Type0" in dic:
        desc = re.search(rb"/DescendantFonts\s*\[?\s*(\d+)\s+0\s+R", dic)
        dd = objs.get(int(desc.group(1)), (b"", None))[0] if desc else b""
        if b"Japan1" in dd:
            return lambda raw: "".join(AJ1.get(int.from_bytes(raw[i:i + 2], "big"), "\ufffd") for i in range(0, len(raw) - 1, 2))
    return lambda raw: raw.decode("latin-1")


AJ1 = {}   # CID -> Unicode\uff08load_aj1 \u3067\u57cb\u3081\u308b\uff09
CMAP_URLS = {
    "UniJIS-UTF16-H": "https://raw.githubusercontent.com/adobe-type-tools/cmap-resources/master/Adobe-Japan1-7/CMap/UniJIS-UTF16-H",
    "UniJIS-UTF16-V": "https://raw.githubusercontent.com/adobe-type-tools/cmap-resources/master/Adobe-Japan1-7/CMap/UniJIS-UTF16-V",
}


def load_aj1(d):
    """UniJIS-UTF16-H/V\uff08Unicode \u2192 CID \u306e CMap\u3002PostScript \u306e CMap \u5f62\u5f0f\u306e\u30c6\u30ad\u30b9\u30c8\uff09\u3092\u8aad\u307f\u3001CID \u2192 Unicode \u306e\u9006\u5f15\u304d\u3092\u4f5c\u308b\u3002
    \u540c\u3058 CID \u306b\u8907\u6570\u306e Unicode \u304c\u3042\u308b\u3068\u304d\u306f\u3001H \u3092\u5148\u306b\u8aad\u307f\u3001\u6700\u521d\u306b\u73fe\u308c\u305f\u3082\u306e\uff08BMP \u306e\u7b26\u53f7\u4f4d\u7f6e\u306e\u5c0f\u3055\u3044\u3082\u306e\uff09\u3092\u63a1\u308b\u3002"""
    inv = {}
    for name in ("UniJIS-UTF16-H", "UniJIS-UTF16-V"):
        p = pathlib.Path(d) / f"{name}.cmap"
        if not p.exists():
            continue
        t = p.read_text(encoding="latin-1")
        for blk in re.findall(r"begincidchar(.*?)endcidchar", t, re.S):
            for u, cid in re.findall(r"<([0-9a-fA-F]+)>\s+(\d+)", blk):
                ch = bytes.fromhex(u).decode("utf-16-be", "replace")
                inv.setdefault(int(cid), ch)
        for blk in re.findall(r"begincidrange(.*?)endcidrange", t, re.S):
            for a, z, cid in re.findall(r"<([0-9a-fA-F]+)>\s*<([0-9a-fA-F]+)>\s+(\d+)", blk):
                if len(a) != 4:
                    continue
                for k in range(int(a, 16), int(z, 16) + 1):
                    inv.setdefault(int(cid) + k - int(a, 16), chr(k))
    return inv


TOK = re.compile(rb"<([0-9A-Fa-f\s]*)>|\(((?:[^()\\]|\\.)*)\)|\[|\]|/([^\s/\[\]<>()]+)|([-+]?\d*\.?\d+)|([A-Za-z'\"*]+)", re.S)


def page_stream_text(objs, pdic, sep="", items=None):
    """内容ストリームの中の文字列表示の演算子（Tj ' " TJ）の文字列を、現れた順にそのままつなぐ（位置による並べ替えはしない）。
    sep を与えると、演算子ごとの文字列の間に sep を入れる。items（list）を与えると、演算子ごとに (x, y, 文字列) を足す
    （x・y は Tm の e・f に Td の移動を足したもの。縦書きの新旧対照表の上下の欄を分けるためだけに使う）。
    items の要素は (x, y, 文字列, フォントの資源名)。"""
    res = pdic
    rnum = ref(pdic, rb"Resources")
    if rnum is not None:
        res = objs.get(rnum, (b"", None))[0]
    fm = re.search(rb"/Font\s*(\d+)\s+0\s+R", res)
    if fm:
        fdict = objs.get(int(fm.group(1)), (b"", None))[0]
    else:
        mm = re.search(rb"/Font\s*<<(.*?)>>", res, re.S)
        fdict = mm.group(1) if mm else b""
    fonts = {name.decode(): font_decoder(objs, int(num)) for name, num in re.findall(rb"/([^\s/<>]+)\s+(\d+)\s+0\s+R", fdict or b"")}
    cont = re.search(rb"/Contents\s*(\[[^\]]*\]|\d+\s+0\s+R)", pdic)
    nums = [int(x) for x in re.findall(rb"(\d+)\s+0\s+R", cont.group(1))] if cont else []
    content = b"\n".join(objs.get(c, (b"", b""))[1] or b"" for c in nums)
    out = []
    for bt in re.findall(rb"\bBT\b(.*?)\bET\b", content, re.S):
        stack, cur, arr = [], None, None
        lx = ly = 0.0
        for m in TOK.finditer(bt):
            h, lit, nm, num, op = m.groups()
            tok = m.group(0)
            if tok == b"[":
                arr = []
                continue
            if tok == b"]":
                stack.append(("arr", arr))
                arr = None
                continue
            if h is not None:
                hx = re.sub(rb"\s", b"", h).decode()
                v = ("str", bytes.fromhex(hx + ("0" if len(hx) % 2 else "")))
            elif lit is not None:
                v = ("str", unescape_literal(lit))
            elif nm is not None:
                v = ("name", nm.decode("latin-1"))
            elif num is not None:
                v = ("num", float(num))
            else:
                v = None
            if v is not None:
                (arr if arr is not None else stack).append(v)
                continue
            o = op.decode("latin-1")
            nums_ = [x[1] for x in stack if x[0] == "num"]
            if o == "Tf" and len(stack) >= 2 and stack[-2][0] == "name":
                cur = stack[-2][1]
            elif o == "Tm" and len(nums_) >= 6:
                lx, ly = nums_[-2], nums_[-1]
            elif o in ("Td", "TD") and len(nums_) >= 2:
                lx, ly = lx + nums_[-2], ly + nums_[-1]
            elif o in ("Tj", "'", '"', "TJ"):
                dec = fonts.get(cur, lambda raw: raw.decode("latin-1"))
                if o == "TJ":
                    parts = [s for s in (stack[-1][1] if stack and stack[-1][0] == "arr" else []) if s[0] == "str"]
                    txt = "".join(dec(s[1]) for s in parts)
                else:
                    strs = [s for s in stack if s[0] == "str"]
                    txt = dec(strs[-1][1]) if strs else ""
                out.append(txt + sep)
                if items is not None:
                    items.append((lx, ly, txt, cur))
            stack = []
        out.append("\n")
    return "".join(out)


def pages_of(objs):
    def kids(num, depth=0):
        dic = objs.get(num, (b"", None))[0]
        if re.search(rb"/Type\s*/Page\b(?!s)", dic):
            return [num]
        km = re.search(rb"/Kids\s*\[([^\]]*)\]", dic)
        out = []
        for k in re.findall(rb"(\d+)\s+0\s+R", km.group(1) if km else b""):
            if depth < 50:
                out += kids(int(k), depth + 1)
        return out
    roots = [n for n, (d, _) in objs.items() if re.search(rb"/Type\s*/Pages\b", d) and not re.search(rb"/Parent\s", d)]
    return kids(roots[0]) if roots else [n for n, (d, _) in sorted(objs.items()) if re.search(rb"/Type\s*/Page\b(?!s)", d)]


def pdf_pages(path):
    pdf = pathlib.Path(path).read_bytes()
    objs, key_ok, alg = load(pdf)
    pages = [page_stream_text(objs, objs[p][0]) for p in pages_of(objs)]
    return {"encrypt": alg, "key_ok": key_ok, "pages": pages}


# ================================================================ 法令（scripts/IMPL_kyuyo_fetch.py の inline / render を写した）
BLOCK_LIKE = {"Paragraph", "Item"} | {f"Subitem{i}" for i in range(1, 11)}


def inline(n):
    if isinstance(n, str):
        return n
    if n.get("tag") in ("Rt",):
        return ""
    return "".join(inline(c) for c in n.get("children", []))


def render(n, depth, lines):
    if isinstance(n, str):
        if n.strip():
            lines.append("  " * depth + n)
        return
    tag = n.get("tag", "")
    ch = n.get("children", [])
    if tag in BLOCK_LIKE:
        title = "".join(inline(c) for c in ch if isinstance(c, dict) and c.get("tag", "").endswith(("Num", "Title")) and c.get("tag") != "ParagraphCaption")
        body = "　".join(inline(s) for s in ch if isinstance(s, dict) and s.get("tag", "").endswith("Sentence"))
        num = n.get("attr", {}).get("Num", "")
        prefix = title if title else (f"（{tag}{num}）" if tag == "Paragraph" else "")
        lines.append("  " * depth + (prefix + "　" if prefix else "") + body)
        for c in ch:
            if isinstance(c, dict) and not (c.get("tag", "").endswith(("Num", "Title", "Sentence")) or c.get("tag") == "ParagraphCaption"):
                render(c, depth + 1, lines)
        return
    if tag in ("ArticleCaption", "ArticleTitle"):
        lines.append("  " * depth + inline(n))
        return
    for c in ch:
        render(c, depth, lines)


def law_articles(path, nums):
    d = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    ri = d.get("revision_info") or {}
    found = {}

    def walk(n, in_suppl):
        if isinstance(n, dict):
            t = n.get("tag")
            if t == "SupplProvision":
                in_suppl = True
            if t == "Article" and not in_suppl and n.get("attr", {}).get("Num") in nums:
                lines = []
                render(n, 0, lines)
                found[n["attr"]["Num"]] = "\n".join(lines)
            for c in n.get("children", []):
                walk(c, in_suppl)
    walk(d["law_full_text"], False)
    return {k: ri.get(k) for k in ("law_title", "law_num", "law_revision_id", "amendment_law_num", "amendment_enforcement_date")}, found


# ================================================================ 検査
def norm(s):
    """NFKC、空白（全角を含む）を除く。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s or ""))


def latest_dl():
    ds = sorted(glob.glob(str(ROOT / ".work" / "downloads" / "*_R3X_kyosai-b_verify")))  # *_verify_cmap は含まない
    return pathlib.Path(ds[-1]) if ds else None


def html_text(path):
    raw = pathlib.Path(path).read_bytes()
    cs = None
    m = re.search(rb"<meta[^>]+charset=[\"']?([\w\-]+)", raw[:4000], re.I)
    if m:
        cs = m.group(1).decode("ascii", "replace")
    for c in [cs, "utf-8", "cp932", "euc-jp"]:
        if not c:
            continue
        try:
            s = raw.decode(c)
            break
        except (LookupError, UnicodeDecodeError):
            continue
    else:
        s = raw.decode("utf-8", "replace")
    p = Extract()
    p.feed(s)
    return p.text(), p.links, " ".join(p.title.split())


def pcm_fields(text):
    keys = ["案件番号", "定めようとする命令などの題名", "根拠法令条項", "行政手続法に基づく手続か", "案の公示日", "結果の公示日",
            "命令等の公布日", "提出意見数"]
    rec = {}
    for k in keys:
        m = re.search(r"\|\s*" + re.escape(k) + r"\s*\|\s*([^\n|]+)", text)
        if m:
            rec[k] = " ".join(m.group(1).split())
    m = re.search(r"理由\s*\|\s*([^\n]+)", text)
    if m:
        rec["39条4項の理由"] = " ".join(m.group(1).split())
    m = re.search(r"（所管省庁・部局名等）\s*\|\s*\n?\s*([^\n]+)", text)
    if m:
        rec["問合せ先"] = " ".join(m.group(1).split())
    return rec


def fuzzy_in(ns, nt):
    """正規化した ns が nt に含まれるか。nt の側の U+FFFD（/ToUnicode に対応のない字形）は任意の1字に一致するとみなす。
    戻り値：None（含まれない）、0（そのまま含まれる）、n>0（U+FFFD を n 字使って含まれる）。"""
    if ns in nt:
        return 0
    if "�" not in nt or not ns:
        return None
    best = None
    L = len(ns)
    for i in range(0, len(nt) - L + 1):
        w = nt[i:i + L]
        n = 0
        for a, b in zip(ns, w):
            if a == b:
                continue
            if b == "�":
                n += 1
                continue
            break
        else:
            if best is None or n < best:
                best = n
    return best


def has(texts, s):
    """texts（頁の list）で、正規化した s を含む頁の番号（1 始まり）の list（U+FFFD を使った一致は "p<頁>~<字数>"）。"""
    ns = norm(s)
    out = []
    for i, t in enumerate(texts):
        r = fuzzy_in(ns, norm(t))
        if r == 0:
            out.append(i + 1)
        elif r:
            out.append(f"p{i + 1}~{r}")
    return out


def soumu_table(recs, page=3, ydiv=425.0):
    """総行福第210号の写しの3頁（縦書きの新旧対照表）を、上の欄（改正後）と下の欄（改正前）の文字列に分ける。"""
    r = recs.get("kouritu_tokyo_03_soumu", {})
    if not r.get("saved"):
        return "", ""
    pdf = (ROOT / r["saved"]).read_bytes()
    objs, _, _ = load(pdf)
    pg = pages_of(objs)[page - 1]
    items = []
    page_stream_text(objs, objs[pg][0], items=items)
    # 本文の縦書きのフォント（いちばん多く使われるフォント）の文字だけを使う（「(三)」などの見出しは別のフォントで横に組まれている）
    cnt = {}
    for it in items:
        cnt[it[3]] = cnt.get(it[3], 0) + 1
    body = max(cnt, key=cnt.get) if cnt else None
    cols = {}
    for x, y, t, f in items:
        if f == body:
            cols.setdefault(round(x * 2) / 2, []).append((y, t))
    up, lo = [], []
    for x in sorted(cols, reverse=True):
        cs = sorted(cols[x], key=lambda q: -q[0])
        up.append("".join(t for y, t in cs if y > ydiv))
        lo.append("".join(t for y, t in cs if y <= ydiv))
    return "".join(up), "".join(lo)


def check(dl):
    sys.stdout.reconfigure(encoding="utf-8")
    if dl is None:
        print("no download dir")
        return 2
    dl = pathlib.Path(dl)
    fl = sorted(OUT.glob("fetch_2*.json"))
    cm = sorted(glob.glob(str(ROOT / ".work" / "downloads" / "*_R3X_kyosai-b_verify_cmap")))
    if cm:
        AJ1.update(load_aj1(cm[-1]))
    flog = json.loads(fl[-1].read_text(encoding="utf-8"))
    recs = {r["id"]: r for r in flog["results"]}
    fx = sorted(OUT.glob("fetch_extra_*.json"))
    if fx:
        for r in json.loads(fx[-1].read_text(encoding="utf-8"))["results"]:
            recs[r["id"]] = r
    (OUT / "text").mkdir(parents=True, exist_ok=True)
    res = {"download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "fetch_log": str(fl[-1].relative_to(ROOT)).replace("\\", "/"),
           "aes_selftest": aes_selftest()}

    # ---------------- V1 取り直したファイルと担当の取得の SHA-256・Last-Modified の比較
    prior = {}
    for f in sorted(PRIOR.glob("*.json")):
        for r in json.loads(f.read_text(encoding="utf-8")).get("results", []):
            prior[r["id"]] = r
    v1 = []
    for sid in list(WEB) + list(EXTRA):
        a, b = recs.get(sid, {}), prior.get(sid, {})
        v1.append({"id": sid, "status_now": a.get("status"), "status_prior": b.get("status"), "sha_now": (a.get("sha256") or "")[:16],
                   "sha_prior": (b.get("sha256") or "")[:16], "same_bytes": bool(a.get("sha256")) and a.get("sha256") == b.get("sha256"),
                   "lm_now": a.get("last_modified"), "lm_prior": b.get("last_modified"), "bytes_now": a.get("bytes")})
    res["V1_refetch_vs_prior"] = v1

    # ---------------- 資料のテキスト
    T = {}   # id -> list of page texts
    meta = {}
    for sid, r in recs.items():
        if not r.get("saved") or r.get("status") != 200:
            continue
        p = ROOT / r["saved"]
        if p.suffix == ".pdf":
            try:
                d = pdf_pages(p)
                T[sid] = d["pages"]
                meta[sid] = {"encrypt": d["encrypt"], "key_ok": d["key_ok"], "pages": len(d["pages"])}
            except Exception as e:  # noqa: BLE001
                meta[sid] = {"error": repr(e)}
        elif p.suffix == ".html":
            t, links, title = html_text(p)
            T[sid] = [t]
            meta[sid] = {"title": title, "links": links}
        elif p.suffix == ".json" and sid.startswith("law_"):
            lid = [x for x in LAWS if x[0] == sid][0]
            ri, arts = law_articles(p, lid[3])
            T[sid] = [arts.get(n, "") for n in lid[3]]
            meta[sid] = {"revision_info": ri, "asof": lid[2], "articles": lid[3]}
    for sid, pages in T.items():
        with open(OUT / "text" / f"{sid}.txt", "w", encoding="utf-8") as f:
            f.write(f"# id={sid} sha256={recs[sid].get('sha256')} url={recs[sid].get('url')}\n")
            for i, t in enumerate(pages, 1):
                f.write(f"\n=== page {i}\n{t}\n")
    res["sources_meta"] = {k: {kk: vv for kk, vv in v.items() if kk != "links"} for k, v in meta.items()}

    upper, lower = soumu_table(recs)
    T["soumu_p3_upper"], T["soumu_p3_lower"] = [upper], [lower]

    def H(sid, s):
        return has(T.get(sid, []), s)

    # ---------------- V2 国の運用方針の4つの版：表紙・2(3)・附則
    v2 = {}
    clause_re = re.compile(r"年額130万円以上の所得がある者\(.*?年額180万円以上の所得がある者\)")
    for sid in ["courts_unyo_hoshin", "wb_20250721_mof_unyo", "wb_20260926_mof_unyo", "mof_unyo_hoshin_current"]:
        pages = T.get(sid, [])
        full = norm("".join(pages))
        cover = norm(pages[0])[:200] if pages else ""
        m = clause_re.search(full)
        fus = re.findall(r"附則\(令和(\d+|元)年(\d+)月(\d+)日財計第(\d+)号\)(.{0,40}?適用する。)", full)
        p3407 = [i + 1 for i, t in enumerate(pages) if "財計第3407号" in norm(t)]
        v2[sid] = {"cover_head": cover[:120], "clause_2_3": m.group(0) if m else None,
                   "clause_has_19_23_150": bool(m and "19歳以上23歳未満の者(組合員の配偶者を除く。)である場合にあつては,年額150万円以上" in m.group(0).replace("、", ",")),
                   "fusoku_reiwa": [{"date": f"令和{a}年{b}月{c}日", "no": f"財計第{d}号", "text": e} for a, b, c, d, e in fus if (a == "元" or int(a) >= 5)],
                   "page_of_3407": p3407, "n_pages": len(pages)}
    res["V2_unyo_versions"] = v2

    # ---------------- V3 第1項第2号の項全体の版ごとの差（内容ストリームの順の文字列で、文の単位）
    blocks = {}
    for sid in ["courts_unyo_hoshin", "wb_20250721_mof_unyo", "wb_20260926_mof_unyo", "mof_unyo_hoshin_current"]:
        full = norm("".join(T.get(sid, [])))
        i = full.find("第1項第2号1共済組合の組合員")
        j = full.find("第1項第3号", i)
        blk = full[i:j] if i >= 0 and j > i else ""
        blk = re.sub(r"-\d+-", "", blk)
        blocks[sid] = [s + "。" for s in blk.split("。") if s]
    order = list(blocks)
    res["V3_block_diff"] = {"n_sentences": {k: len(v) for k, v in blocks.items()},
                            "pairs": [{"from": a, "to": b, "only_in_from": [s for s in blocks[a] if s not in set(blocks[b])],
                                       "only_in_to": [s for s in blocks[b] if s not in set(blocks[a])]} for a, b in zip(order, order[1:])]}

    # ---------------- V4 e-Gov パブリック・コメント（結果の公示）と、同じ番号帯の案件
    v4 = {}
    for sid in ["pcm_395081949", "mhlw_pcm_495250041", "pcm_395081944", "pcm_395081959"] + list(PROBE):
        if sid in T:
            v4[sid] = {"title": meta[sid].get("title"), **pcm_fields(T[sid][0]),
                       "attachments": [lk for lk in meta[sid].get("links", []) if "download" in lk.get("href", "")]}
        else:
            v4[sid] = {"status": recs.get(sid, {}).get("status"), "error": recs.get(sid, {}).get("error")}
    res["V4_pcm"] = v4

    # ---------------- V5 文書に書かれた個別の値の有無（資料, 文字列, 期待：含む/含まない, 文書の箇所）
    E = [
        # 国の運用方針
        ("mof_unyo_hoshin_current", "国家公務員共済組合法等の運用方針（昭和３４年１０月１日蔵計第２９２７号）", True, "PS §0 UNYO-K"),
        ("mof_unyo_hoshin_current", "令和８年１０月１日現在（最終改正令和８年９月３０日財計第４１４０号）", True, "PS §0 UNYO-K"),
        ("wb_20250721_mof_unyo", "令和７年４月１日現在（最終改正令和７年３月３１日財計第１７０１号）", True, "PS §0 UNYO-K-0401"),
        ("wb_20260926_mof_unyo", "令和８年８月１日現在（最終改正令和８年７月３１日財計第３５７０号）", True, "PS §0 UNYO-K-0801"),
        ("courts_unyo_hoshin", "令和５年３月２８日現在", True, "PS §0 UNYO-K-R5"),
        ("courts_unyo_hoshin", "最終改正令和５年３月２８日財計第１５８９号", True, "MS §3.1"),
        ("mof_unyo_hoshin_current", "附則（令和７年８月８日財計第３４０７号）この改正は、令和７年１０月１日から適用する。", True, "PS §1.1"),
        ("mof_unyo_hoshin_current", "附則（令和７年９月３０日財計第３８３９号）この改正は、令和７年１０月１日から適用する。", True, "PS §1.1"),
        ("mof_unyo_hoshin_current", "国、地方公共団体その他から受けている者", True, "PS §3.2"),
        ("mof_unyo_hoshin_current", "被扶養者としようとするとき", True, "PS §1.2"),
        ("wb_20260926_mof_unyo", "被扶養者としようするとき", True, "PS §1.2・MS §3.7"),
        ("mof_unyo_hoshin_current", "被扶養者としようするとき", False, "PS §1.2・MS §3.7"),
        ("wb_20250721_mof_unyo", "１９歳以上２３歳未満", False, "PS §1.1"),
        ("courts_unyo_hoshin", "１９歳以上２３歳未満", False, "MS §3.1"),
        ("mof_tsuutatsu_s", "蔵計第2927号", True, "PS §0 UNYO-K"),
        ("mof_tsuutatsu_s", "主計局給与共済課共済係", True, "PS §0 UNYO-K"),
        # 地方
        ("kouritu_tokyo_19_23", "更新日: 2025年09月30日", True, "PS §0 SOUMU-210"),
        ("kouritu_tokyo_19_23", "03_総務省運用方針改正通知.pdf", True, "PS §0 SOUMU-210"),
        ("kouritu_tokyo_03_soumu", "総行福第２１０号", True, "PS §2.1"),
        ("kouritu_tokyo_03_soumu", "令和７年７月２３日", True, "PS §2.1"),
        ("kouritu_tokyo_03_soumu", "総務省自治行政局公務員部福利課長", True, "PS §2.1"),
        ("kouritu_tokyo_03_soumu", "（公印省略）", True, "PS §2.1"),
        ("kouritu_tokyo_03_soumu", "地方公務員等共済組合法運用方針の一部改正について（通知）", True, "PS §2.1"),
        ("kouritu_tokyo_03_soumu", "このことについて、別紙のとおり改正しましたので通知します。", True, "PS §2.1"),
        ("kouritu_tokyo_03_soumu", "その施行に遺漏のないよう願います。", True, "PS §2.1"),
        ("kouritu_tokyo_03_soumu", "警察庁長官官房人事課長", True, "PS §2.1"),
        ("kouritu_tokyo_03_soumu", "文部科学省初等中等教育局財務課長", True, "PS §2.1"),
        ("kouritu_tokyo_03_soumu", "地方公務員共済組合連合会理事長", True, "PS §2.1"),
        ("kouritu_tokyo_03_soumu", "地方職員共済組合理事長", True, "PS §2.1"),
        ("kouritu_tokyo_03_soumu", "地方共済事務局、団体共済部扱い", True, "PS §2.1"),
        ("kouritu_tokyo_03_soumu", "東京都職員共済組合理事長", True, "PS §2.1"),
        ("kouritu_tokyo_03_soumu", "全国市町村職員共済組合連合会理事長", True, "PS §2.1"),
        ("kouritu_tokyo_03_soumu", "各指定都市職員共済組合理事長", True, "PS §2.1"),
        ("kouritu_tokyo_03_soumu", "地方公務員等共済組合法運用方針（昭和三十七年自治甲公第十号）の一部を次のように改正する。", True, "PS §2.1"),
        ("soumu_p3_upper", "十九歳以上二十三歳未満の者（組合員の配偶者を除く。）である場合にあつては、年額百五十万円以上の所得がある者", True, "PS §2.1"),
        ("soumu_p3_lower", "十九歳", False, "PS §2.1（改正前）"),
        ("kouritu_tokyo_03_soumu", "この運用方針の改正は、令和七年十月一日から適用する。", True, "PS §2.1"),
        ("kouritu_tokyo_00_tsuchi", "７公立東京給第９４３号", True, "PS §0 KT-943"),
        ("kouritu_tokyo_00_tsuchi", "令和７年９月３０日", True, "PS §0 KT-943"),
        ("kouritu_tokyo_00_tsuchi", "令和７年７月２３日総行福第２１０号総務省自治行政局公務員部福利課長発", True, "PS §2.1"),
        ("kouritu_tokyo_00_tsuchi", "適用年月日前の認定基準額は、従前のとおりです。", True, "PS §2.1"),
        ("kouritu_tokyo_00_tsuchi", "令和７年１０月１日から適用", True, "PS §2.1"),
        ("kouritu_tokyo_00_tsuchi", "令和７年７月４日保発０７０４第２号厚生労働省保険局長発", True, "MS §3.4"),
        ("kouritu_tokyo_00_tsuchi", "年齢（１９歳以上２３歳未満）については所得税法上の取扱いに合わせて、その年の１２月３１日現在の年齢で判定します。", True, "PS §2.3"),
        ("chikyosai_info_250924", "年齢要件（19歳以上23歳未満）は、所得税法上と同様にその年の12月31日現在の年齢で判定します。", True, "PS §2.3"),
        ("chikyosai_info_250924", "学生である必要はありません。", True, "PS §2.3"),
        ("miyagi_fget96", "令和7年9月12日", True, "PS §0 MIYAGI-0912"),
        ("sigichokai_hoshin_kyosai", "昭和三十七年十月三日", True, "PS §2.2"),
        ("sigichokai_hoshin_kyosai", "自治甲公第十号", True, "PS §2.2"),
        # 国家公務員の組合の案内
        ("boueikyosai_164", "更新日: 2026年10月15日", True, "PS §0 BOUEI"),
        ("boueikyosai_164", "令和7年10月1日以降の届出で、令和7年10月1日より前の期間について認定する場合、19歳以上23歳未満の被扶養者にかかる年間収入の要件は130万円未満で判定します。", True, "PS §1.3"),
        ("boueikyosai_164", "年齢要件はその年の12月31日時点での年齢が基準となります。", True, "PS §1.3"),
        ("boueikyosai_164", "従来と同様の年間収入の考え方によって判定します。", True, "PS §1.3"),
        ("boueikyosai_164", "12月31日現在の年齢が22歳である年（暦年）の翌年については、年間収入130万円未満かどうかにより判定します。", True, "（文書に記載なし。A28）"),
        # 私学
        ("pmac_kanko_hourei", "令和 8年07月07日", True, "PS §0 PMAC-H-S"),
        ("pmac_kanko_hourei", "内容は令和8年4月1日現在です。", True, "PS §0 PMAC-H-S"),
        ("pmac_hourei_mokuji_2026", "私立学校教職員共済法施行令第三条の規定による", True, "PS §3.1"),
        ("pmac_hourei_mokuji_2026", "の認定について〔昭和三五年文部大臣裁定〕・・・・・・・・・・・・一九六八", True, "PS §0 PMAC-H-S（法令集の頁番号）"),
        # 文書の抜け（担当が取得したが書いていない、または取得の範囲にある記載）
        ("pmac_qa_48", "所得税法（昭和40年法律第33号）上の取り扱いと同様、その年の12月31日現在の年齢で判定します。", True, "（抜け）私学の年齢の判定時点 A3"),
        ("pmac_qa_48", "配偶者とは、健康保険法等における取り扱いと同様、届出をしていないが、事実上婚姻関係と同様の事情にある人を含みます。", True, "（抜け）A1"),
        ("pmac_qa_48", "配偶者を除き、年齢要件にあてはまる続柄の家族であれば改正の対象となります。", True, "（抜け）A6"),
        ("pmac_qa_48", "税制改正における取り扱いと同様、学生であることの要件は求めません。", True, "（抜け）A2"),
        ("chikyosai_info_250924", "18歳に到達する年の12月31日まで及び23歳に到達する年の1月1日以降の年間収入要件は130万円となります。", True, "（抜け）留意点"),
        ("kouritu_tokyo_00_tsuchi", "（収入の中に障害年金を含む者又は障害年金受給程度の障害を有する者を除く。）である場合にあっては", True, "（抜け）KT-943 2"),
        ("kouritu_tokyo_00_tsuchi", "（組合員の配偶者を除く。）（②以外の者）", True, "（抜け）KT-943 表の③"),
        ("kouritu_tokyo_00_tsuchi", "被扶養者申告書の届出が事実発生日から３０日以内に行われない場合には、事実発生日に遡って認定が行われず、所属所受理日からの認定となります", True, "（抜け）KT-943 4(1)"),
        ("sigichokai_hoshin_kyosai", "平成二三年六月一日総行福第二〇三号", True, "（抜け）SIGI の版"),
        ("sigichokai_hoshin_kyosai", "2012/05/28", True, "（抜け）SIGI の版（版面の外）"),
    ]
    v5 = []
    for sid, s, want, where in E:
        pg = H(sid, s)
        v5.append({"source": sid, "string": s, "expect_present": want, "pages": pg, "ok": bool(pg) == want, "doc": where})
    res["V5_expected_strings"] = v5

    # ---------------- V6 私学：法令集「その他」の文部大臣裁定（頁と文言）
    pages = T.get("pmac_hourei_sonota_2026", [])
    sp = [i + 1 for i, t in enumerate(pages) if "主として加入者の収入により生計を維持すること" in norm(t)]
    v6 = {"title_pages": sp, "n_pages": len(pages)}
    for i in sp:
        t = norm(pages[i - 1])
        v6[f"p{i}"] = {
            "has_saitei_date": "昭和三十五年四月九日文部大臣裁定" in t,
            "has_saikin_kaisei": "令和七年八月二九日" in t and "七文科高第七八三号" in t,
            "has_tekiyo": "令和七年一〇月一日から適用する" in t,
            "has_19_23_150": "19歳以上23歳未満の者(加入者の配偶者を除く。)である場合にあつては年額150万円以上の所得がある者" in t,
            "has_kokumin_minkan": "国、民間その他から受けている者" in t.replace(",", "、"),
            "has_item4_marker": bool(re.search(r"所得がある者\)4", t)),
            "excerpt": t[:1500],
        }
    res["V6_shigaku_saitei"] = v6

    # ---------------- V7 3つの大臣の定めの 130/150/180 の文の比較（独立に正規化）
    def clause(t):
        t = norm(t)
        for k, v in {"百三十万円": "130万円", "百五十万円": "150万円", "百八十万円": "180万円", "十九歳": "19歳", "二十三歳": "23歳",
                     "六十歳": "60歳", "昭和三十四年法律第百四十一号": "昭和34年法律第141号", "昭和二十九年法律第百十五号": "昭和29年法律第115号"}.items():
            t = t.replace(k, v)
        t = t.replace("組合員", "＊").replace("加入者", "＊")
        t = re.sub(r"[、,]", "", t)
        m = re.search(r"年額130万円以上の所得がある者\(19歳以上23歳未満.*?年額180万円以上の所得がある者\)", t)
        return m.group(0) if m else None
    # 国：頁番号（-3- など）が文の途中に入るので除く。私学：20頁は回転して組まれ、欄の外の「（昭和三十五年四月九日文部大臣裁定）」が
    # 内容ストリームの順では本文の途中に入るので、その文字列だけを除く（除いたことを記録する）。
    # 地方：3頁は縦書きの新旧対照表（上の欄が改正後、下の欄が改正前）。内容ストリームの順では上下の欄の列が交互に出るので、
    # 演算子ごとの位置（Tm）で列（x）に分け、列の中を y の降順、列を x の降順（右から左）に並べ、y で上の欄と下の欄に分ける。
    kk = re.sub(r"-\d+-", "", norm("".join(T.get("mof_unyo_hoshin_current", []))))
    ss = norm("".join(T.get("pmac_hourei_sonota_2026", []))).replace("()昭和三十五年四月九日文部大臣裁定", "")
    c_k, c_c, c_s = clause(kk), clause(upper), clause(ss)
    lower_n = norm(lower)
    res["V7_compare"] = {"kokka": c_k, "chiho_after": c_c, "shigaku": c_s, "all_equal": c_k is not None and c_k == c_c == c_s,
                         "removed_from_shigaku": "()昭和三十五年四月九日文部大臣裁定", "removed_from_kokka": "-<数字>-（頁番号）",
                         "chiho_before_clause": (re.search(r"年額百三十万円以上の所得がある者\(国民年金法.*?年額百八十万円以上の所得がある者\)", lower_n) or [None])[0],
                         "chiho_before_has_19": "十九歳" in lower_n,
                         "chiho_upper_has_fusoku": "この運用方針の改正は" in norm(upper) or "この運用方針の改正は" in lower_n}

    # ---------------- V8 法令の条文（委任と、文書が引く条）
    v8 = {}
    for lid, law_id, asof, nums in LAWS:
        if lid in T:
            v8[lid] = {"revision_info": meta[lid]["revision_info"], "asof": asof,
                       "articles": {n: T[lid][i][:1500] for i, n in enumerate(nums)}}
        else:
            v8[lid] = {"status": recs.get(lid, {}).get("status"), "error": recs.get(lid, {}).get("error")}
    res["V8_laws"] = v8

    # ---------------- V9 担当の実測の §2 の表（HTTP・Last-Modified・SHA-256 の先頭16桁）と担当の取得記録の一致
    ms = DOCS["MS"].read_text(encoding="utf-8")
    sec2 = ms.split("## 2.", 1)[1].split("## 3.", 1)[0]
    v9 = []
    for ln in sec2.splitlines():
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) < 6 or cells[1] in ("id", "---"):
            continue
        sid, st, lm, sha = cells[1], cells[2], cells[3], cells[4]
        if not re.fullmatch(r"[a-z0-9_]+", sid or ""):
            continue
        b = prior.get(sid)
        if not b:
            v9.append({"id": sid, "in_prior_log": False})
            continue
        ok_st = (st == str(b.get("status"))) if st not in ("—", "") else (b.get("status") is None)
        ok_sha = (sha == (b.get("sha256") or "")[:16]) if re.fullmatch(r"[0-9a-f]{16}", sha) else None
        lm_prior = b.get("last_modified")
        ok_lm = None
        if lm in ("なし",):
            ok_lm = lm_prior is None
        elif re.match(r"\d{4}-\d{2}-\d{2}", lm):
            ok_lm = bool(lm_prior) and time.strftime("%Y-%m-%d", time.strptime(lm_prior[5:16], "%d %b %Y")) == lm[:10]
        v9.append({"id": sid, "doc_status": st, "prior_status": b.get("status"), "ok_status": ok_st, "doc_sha16": sha,
                   "prior_sha16": (b.get("sha256") or "")[:16], "ok_sha": ok_sha, "doc_lm": lm, "prior_lm": lm_prior, "ok_lm": ok_lm,
                   "prior_error": b.get("error"), "prior_bytes": b.get("bytes")})
    res["V9_ms_table_vs_prior_log"] = v9

    # ---------------- V10 文書の参照先のファイルの有無（docs/ と scripts/ のパス）
    v10 = []
    for k, p in DOCS.items():
        t = p.read_text(encoding="utf-8")
        for path in sorted(set(re.findall(r"`((?:docs|scripts)/[^`\s]+)`", t))):
            path_c = path.split("<")[0]
            exists = (ROOT / path_c).exists() if "<" not in path and "*" not in path else bool(glob.glob(str(ROOT / path_c) + "*"))
            v10.append({"doc": k, "path": path, "exists": exists})
    res["V10_referenced_paths"] = v10

    # ---------------- V11 仮説の文書が参照するもの（外部 URL を直接書いていないか、根拠が実測・公開資料の情報だけか）
    hy = DOCS["HY"].read_text(encoding="utf-8")
    # ---------------- V13 地方の運用方針の見出し「施行令第二条［略］」「第一項第二号」の関係：地共済令第2条第1項第2号は被扶養者の規定か
    # （「第一項第二号」が施行令第2条の下の号なのか、法第2条第1項第2号の見出しなのかを、施行令の条文から確かめる）
    cr = dict(zip([x for x in LAWS if x[0] == "law_chikyo_rei"][0][3], T.get("law_chikyo_rei", [])))
    a2 = cr.get("2", "")
    lines2 = a2.splitlines()
    item2 = [ln.strip() for ln in lines2 if ln.strip().startswith("二　")]
    res["V13_chiho_heading"] = {
        "rei2_caption_line": lines2[0] if lines2 else None,
        "rei2_p1_item2": item2[0] if item2 else None,
        "rei2_mentions_seikei_iji": "生計を維持" in a2,
        "rei3_is_hifuyosha_nintei": "主として組合員の収入により生計を維持することの認定" in cr.get("3", ""),
        "rei4_caption_and_ref": ((cr.get("4", "").splitlines() or [""])[0], "法第二条第一項第三号" in cr.get("4", "")),
        "soumu_upper_heading_order": [h for h in ["施行令第二条", "第一項第二号", "一　［略］", "二　次に掲げる者は", "三～五", "施行令第四条", "第一項第五号"]
                                      if norm(h) in norm(upper + lower)],
    }

    res["V11_hypothesis_refs"] = {"urls": re.findall(r"https?://\S+", hy),
                                  "doc_refs": sorted(set(re.findall(r"`(docs/[^`]+)`", hy)))}

    (OUT / "checks.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---------------- V12 引用の監査：3つの文書の「…」と > の行を、取り直した資料のどれかが（正規化して）含むか
    allsrc = {sid: norm("".join(pages)) for sid, pages in T.items()}
    # 版面の都合で文が切れる資料は、V7 で組み直した文字列も資料として加える
    allsrc["mof_unyo_hoshin_current(頁番号を除く)"] = kk
    allsrc["pmac_hourei_sonota_2026(欄外の題を除く)"] = ss
    allsrc["kouritu_tokyo_03_soumu(3頁 上の欄=改正後)"] = norm(upper)
    allsrc["kouritu_tokyo_03_soumu(3頁 下の欄=改正前)"] = norm(lower)
    audit = []
    for k, p in DOCS.items():
        t = p.read_text(encoding="utf-8")
        quotes = re.findall(r"「([^「」]{6,})」", t)
        quotes += [ln[1:].strip() for ln in t.splitlines() if ln.startswith(">")]
        for q in quotes:
            pieces = [x for x in re.split(r"…|（…）|\.\.\.|〔[^〕]*〕|／", q) if len(norm(x)) >= 6]
            if not pieces:
                continue
            hits = {}
            for sid, s in allsrc.items():
                n_ok = sum(1 for x in pieces if fuzzy_in(norm(x), s) is not None)
                if n_ok:
                    hits[sid] = f"{n_ok}/{len(pieces)}"
            full = [sid for sid, v in hits.items() if v.split("/")[0] == v.split("/")[1]]
            audit.append({"doc": k, "quote": q[:200], "pieces": len(pieces), "found_full_in": full, "partial": hits if not full else {}})
    (OUT / "quote_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=1), encoding="utf-8")

    # 要約
    print("aes", res["aes_selftest"])
    print("V1 same bytes:", sum(1 for x in v1 if x["same_bytes"]), "/", len(v1))
    for x in v1:
        if not x["same_bytes"]:
            print("  differs:", x)
    for sid, v in v2.items():
        print("V2", sid, v["cover_head"][:70], "| 19-23/150:", v["clause_has_19_23_150"], "| 3407 page:", v["page_of_3407"],
              "| fusoku:", [(f["date"], f["no"]) for f in v["fusoku_reiwa"]][-7:])
    for pr in res["V3_block_diff"]["pairs"]:
        print("V3", pr["from"], "->", pr["to"], "from-only:", pr["only_in_from"], "to-only:", pr["only_in_to"])
    for sid, v in v4.items():
        print("V4", sid, v.get("定めようとする命令などの題名") or v.get("title") or v, v.get("結果の公示日"), v.get("問合せ先"))
    for x in v5:
        if not x["ok"]:
            print("V5 NG", x)
    print("V5 ok:", sum(1 for x in v5 if x["ok"]), "/", len(v5))
    print("V6", {k: v for k, v in v6.items() if not k.startswith("p")}, {k: {kk: vv for kk, vv in v.items() if kk != "excerpt"} for k, v in v6.items() if re.fullmatch(r"p\d+", k)})
    print("V7 all_equal:", res["V7_compare"]["all_equal"])
    for lid, v in v8.items():
        print("V8", lid, v.get("revision_info"), {n: a[:160] for n, a in v.get("articles", {}).items()})
    for x in v9:
        if not (x.get("ok_status", True) and x.get("ok_sha") in (True, None) and x.get("ok_lm") in (True, None)):
            print("V9 NG", x)
    print("V9 rows:", len(v9))
    for x in v10:
        if not x["exists"]:
            print("V10 missing", x)
    print("V11", res["V11_hypothesis_refs"])
    print("V13", res["V13_chiho_heading"])
    nf = [a for a in audit if not a["found_full_in"]]
    print("V12 quotes:", len(audit), "not fully found:", len(nf))
    return 0


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8")
    if not argv:
        print(__doc__)
        return 2
    if argv[0] == "fetch":
        return fetch()
    if argv[0] == "fetch_cmap":
        return fetch_cmap()
    if argv[0] == "fetch_extra":
        return fetch_extra()
    if argv[0] == "check":
        return check(argv[1] if len(argv) > 1 else latest_dl())
    print("unknown command")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
