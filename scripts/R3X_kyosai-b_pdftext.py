"""R3X kyosai-b: 取得した PDF（財務省の運用方針の全文、組合が掲載した通知の写しなど）から、頁ごとの文字列を取り出す。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ。ネットワークは使わない）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_kyosai-b_pdftext.py <名前>=<PDF のパス> [...]

- 入力の PDF は scripts/R3X_kyosai-b_fetch.py などが .work/downloads/<ts>_.../ に置いた信頼できないデータ。
  このスクリプトはリポジトリのルートで実行し、PDF のパスを引数で受け取って読むだけ（ダウンロード先の中では何も実行しない）。
- PDF の読み出し（標準セキュリティハンドラの RC4・AESV2 の復号、オブジェクトストリームの展開、フォントの /ToUnicode による文字の復元、
  BT〜ET の位置の追跡）は scripts/R2X_aoiro_pdftext.py の関数を写した（import はしない）。AES は FIPS-197 の試験ベクタで自己検査する。
  AES-256（V5）は復号を書いていないので、その旨を記録して文字を取り出さない。展開は zlib に上限（64MiB）をつける。
- 出力：scripts/results/R3X_kyosai-b_pdftext/<名前>_lines.txt（頁ごとに、y がほぼ同じ文字列を x の昇順につないだ行。横書き用の近似）
        scripts/results/R3X_kyosai-b_pdftext/<名前>_text.tsv（頁, x, y, フォント, 文字列）
        scripts/results/R3X_kyosai-b_pdftext/summary.json（ファイルの SHA-256、暗号の種類、鍵の検査、AES の自己検査、頁数、行数）
- 縦書きの頁（総務省の新旧対照表など）は行の復元がうまくいかない。縦書きの資料は描画を読む。
"""
import hashlib
import json
import pathlib
import re
import sys
import zlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "scripts" / "results" / "R3X_kyosai-b_pdftext"
MAXOUT = 64 * 1024 * 1024


# ---------------------------------------------------------------- AES-128（scripts/IMPL_output_verify.py から写した）
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
M9, M11, M13, M14 = ([_gmul(x, k) for x in range(256)] for k in (9, 11, 13, 14))


def _expand(key):
    w = [list(key[i:i + 4]) for i in range(0, 16, 4)]
    rcon = 1
    for i in range(4, 44):
        t = list(w[i - 1])
        if i % 4 == 0:
            t = t[1:] + t[:1]
            t = [SBOX[x] for x in t]
            t[0] ^= rcon
            rcon = _xt(rcon)
        w.append([w[i - 4][j] ^ t[j] for j in range(4)])
    return [sum(w[r * 4:r * 4 + 4], []) for r in range(11)]


def aes128_decrypt_block(rk, block):
    s = [b ^ k for b, k in zip(block, rk[10])]
    for rnd in range(9, -1, -1):
        s = [s[((c - r) % 4) * 4 + r] for c in range(4) for r in range(4)]
        s = [INV_SBOX[x] for x in s]
        s = [x ^ k for x, k in zip(s, rk[rnd])]
        if rnd:
            ns = []
            for c in range(4):
                a = s[c * 4:c * 4 + 4]
                ns += [M14[a[0]] ^ M11[a[1]] ^ M13[a[2]] ^ M9[a[3]],
                       M9[a[0]] ^ M14[a[1]] ^ M11[a[2]] ^ M13[a[3]],
                       M13[a[0]] ^ M9[a[1]] ^ M14[a[2]] ^ M11[a[3]],
                       M11[a[0]] ^ M13[a[1]] ^ M9[a[2]] ^ M14[a[3]]]
            s = ns
    return bytes(s)


def aes128_cbc_decrypt(key, data):
    rk = _expand(key)
    iv, out = data[:16], bytearray()
    for i in range(16, len(data) - len(data) % 16, 16):
        blk = data[i:i + 16]
        out += bytes(x ^ y for x, y in zip(aes128_decrypt_block(rk, blk), iv))
        iv = blk
    if out and 1 <= out[-1] <= 16:
        out = out[:-out[-1]]
    return bytes(out)


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


# ---------------------------------------------------------------- オブジェクトの読み出し
def raw_objects(pdf):
    """(num, gen, 辞書の部分, 生のストリーム or None)"""
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
    """/key <16進> または /key (リテラル) の文字列をバイト列で返す（暗号の辞書の /O・/U と /ID の1つ目）"""
    m = re.search(rb"/" + key + rb"\s*<([0-9a-fA-F]+)>", b)
    if m:
        return bytes.fromhex(m.group(1).decode())
    m = re.search(rb"/" + key + rb"\s*\(((?:[^()\\]|\\.)*)\)", b, re.S)
    return unescape_literal(m.group(1))


# ---------------------------------------------------------------- 追加（R3X kyosai-b）：AES-256（V5・R5/R6、AESV3）
# FIPS-197 の AES を、鍵長 128・256 ビットの暗号化と復号の両方について書いた（R6 の鍵の算出に AES-128-CBC の暗号化が要る）。
# 自己検査：FIPS-197 Appendix C.1（AES-128）と C.3（AES-256）の試験ベクタ（aes_selftest_all）。
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


M2, M3 = ([_gmul(x, k) for x in range(256)] for k in (2, 3))


def aes_encrypt_block_n(rk, nr, block):
    s = [b ^ k for b, k in zip(block, rk[0])]
    for rnd in range(1, nr + 1):
        s = [SBOX[x] for x in s]
        s = [s[((c + r) % 4) * 4 + r] for c in range(4) for r in range(4)]
        if rnd != nr:
            ns = []
            for c in range(4):
                a = s[c * 4:c * 4 + 4]
                ns += [M2[a[0]] ^ M3[a[1]] ^ a[2] ^ a[3],
                       a[0] ^ M2[a[1]] ^ M3[a[2]] ^ a[3],
                       a[0] ^ a[1] ^ M2[a[2]] ^ M3[a[3]],
                       M3[a[0]] ^ a[1] ^ a[2] ^ M2[a[3]]]
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
                ns += [M14[a[0]] ^ M11[a[1]] ^ M13[a[2]] ^ M9[a[3]],
                       M9[a[0]] ^ M14[a[1]] ^ M11[a[2]] ^ M13[a[3]],
                       M13[a[0]] ^ M9[a[1]] ^ M14[a[2]] ^ M11[a[3]],
                       M11[a[0]] ^ M13[a[1]] ^ M9[a[2]] ^ M14[a[3]]]
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


def aes_selftest_all():
    pt = bytes.fromhex("00112233445566778899aabbccddeeff")
    res = {}
    for name, key, ct in (("C.1_AES128", bytes(range(16)), "69c4e0d86a7b0430d8cdb78070b4c55a"),
                          ("C.3_AES256", bytes(range(32)), "8ea2b7ca516745bfeafc49904b496089")):
        rk, nr = aes_expand_n(key)
        e = aes_encrypt_block_n(rk, nr, pt).hex()
        d = aes_decrypt_block_n(rk, nr, bytes.fromhex(ct))
        res[name] = (e == ct) and (d == pt)
    return res


def _hash_r6(password, salt, udata, r):
    """PDF 2.0（ISO 32000-2）の暗号の鍵の算出（R5 は SHA-256 だけ、R6 は SHA-256/384/512 と AES-128-CBC の繰り返し）。"""
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


def load(pdf):
    enc = re.search(rb"/Filter\s*/Standard", pdf)
    key, key_ok, alg = None, None, None
    if enc:
        # 追加（R3X kyosai-b）：/V・/R・/O・/U・/P・/Length は暗号の辞書のオブジェクトの中だけで探す（PDF 全体の最初の一致を使わない）。
        # /EncryptMetadata false（R4）のときは鍵の計算に 0xFFFFFFFF の4バイトを足す（PDF 1.7 の暗号の鍵の算出手順）。
        ostart = pdf.rfind(b" obj", 0, enc.start())
        oend = pdf.find(b"endobj", enc.start())
        edict = pdf[ostart:oend] if ostart >= 0 and oend > 0 else pdf
        v = int(re.search(rb"/V\s*(\d+)", edict).group(1))
        r = int(re.search(rb"/R\s*(\d+)", edict).group(1))
        if v >= 5:
            # 追加（R3X kyosai-b）：AES-256（V5・R5/R6）。空のユーザーパスワードで U を検査し、UE から鍵を取り出す。
            u, ue = pdfstr(edict, rb"U"), pdfstr(edict, rb"UE")
            key_ok = (_hash_r6(b"", u[32:40], b"", r) == u[:32])
            if not key_ok:
                return {}, False, f"AESV3(V{v},R{r}) 空のユーザーパスワードで開けない"
            ik = _hash_r6(b"", u[40:48], b"", r)
            key = aes_cbc_decrypt_n(ik, bytes(16), ue[:32], unpad=False)
            alg = f"AESV3(V{v},R{r})"
            objs = {}
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
                    except Exception as e:  # noqa
                        dec = b"<<inflate error " + repr(e).encode() + b">>"
                objs[num] = (dic, dec)
            for num, (dic, dec) in list(objs.items()):
                if dec is not None and b"/ObjStm" in dic and not dec.startswith(b"<<inflate error"):
                    nn = int(re.search(rb"/N\s+(\d+)", dic).group(1))
                    first = int(re.search(rb"/First\s+(\d+)", dic).group(1))
                    hdr = [int(x) for x in dec[:first].split()]
                    pairs = [(hdr[i], hdr[i + 1]) for i in range(0, min(len(hdr), 2 * nn), 2)]
                    for i, (onum, off) in enumerate(pairs):
                        end = pairs[i + 1][1] if i + 1 < len(pairs) else len(dec) - first
                        objs.setdefault(onum, (dec[first + off:first + end], None))
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
        alg = "AESV2" if (v == 4 and b"AESV2" in pdf) else "RC4"
        alg = f"{alg}(V{v},R{r})"
    objs = {}
    for num, gen, dic, raw in raw_objects(pdf):
        if raw is None:
            objs[num] = (dic, None)
            continue
        dec = raw
        if key is not None and b"/XRef" not in dic:
            okey = hashlib.md5(key + num.to_bytes(3, "little") + gen.to_bytes(2, "little") + (b"sAlT" if "AESV2" in alg else b"")).digest()[:min(len(key) + 5, 16)]
            dec = aes128_cbc_decrypt(okey, raw) if "AESV2" in alg else _rc4(okey, raw)
        if b"FlateDecode" in dic:
            try:
                dec = inflate(dec)
            except Exception as e:  # noqa
                dec = b"<<inflate error " + repr(e).encode() + b">>"
        objs[num] = (dic, dec)
    # オブジェクトストリームを展開する
    for num, (dic, dec) in list(objs.items()):
        if dec is not None and b"/ObjStm" in dic:
            nn = int(re.search(rb"/N\s+(\d+)", dic).group(1))
            first = int(re.search(rb"/First\s+(\d+)", dic).group(1))
            hdr = [int(x) for x in dec[:first].split()]
            pairs = [(hdr[i], hdr[i + 1]) for i in range(0, min(len(hdr), 2 * nn), 2)]
            for i, (onum, off) in enumerate(pairs):
                end = pairs[i + 1][1] if i + 1 < len(pairs) else len(dec) - first
                objs.setdefault(onum, (dec[first + off:first + end], None))
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
        return enc, lambda raw: raw.decode("cp932", "replace")
    if "UCS2" in enc or "UTF16" in enc:
        return enc, lambda raw: raw.decode("utf-16-be", "replace")
    if tu is not None and objs.get(tu, (None, None))[1]:
        cm = parse_cmap(objs[tu][1])
        two = enc.startswith("Identity") or b"/Type0" in dic
        if two:
            return enc + "+ToUnicode", lambda raw: "".join(cm.get(int.from_bytes(raw[i:i + 2], "big"), "�") for i in range(0, len(raw) - 1, 2))
        return enc + "+ToUnicode", lambda raw: "".join(cm.get(c, chr(c)) for c in raw)
    return enc or "?", lambda raw: raw.decode("latin-1")


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


TOK = re.compile(rb"<([0-9A-Fa-f\s]*)>|\(((?:[^()\\]|\\.)*)\)|\[|\]|/([^\s/\[\]<>()]+)|([-+]?\d*\.?\d+)|([A-Za-z'\"*]+)", re.S)


def page_rows(objs, pno, pdic):
    res = pdic
    rnum = ref(pdic, rb"Resources")
    if rnum is not None:
        res = objs.get(rnum, (b"", None))[0]
    fonts = {}
    fm = re.search(rb"/Font\s*(\d+)\s+0\s+R", res)
    fdict = objs.get(int(fm.group(1)), (b"", None))[0] if fm else (re.search(rb"/Font\s*<<(.*?)>>", res, re.S) or re.search(b"()", b"")).group(1)
    for name, num in re.findall(rb"/([^\s/<>]+)\s+(\d+)\s+0\s+R", fdict or b""):
        fonts[name.decode()] = font_decoder(objs, int(num))
    cont = re.search(rb"/Contents\s*(\[[^\]]*\]|\d+\s+0\s+R)", pdic)
    nums = [int(x) for x in re.findall(rb"(\d+)\s+0\s+R", cont.group(1))] if cont else []
    content = b"\n".join(objs.get(c, (b"", b""))[1] or b"" for c in nums)
    rows = []
    for bt in re.findall(rb"\bBT\b(.*?)\bET\b", content, re.S):
        stack, x, y, lx, ly, cur, lead = [], 0.0, 0.0, 0.0, 0.0, None, 0.0
        arr = None
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
                v = ("str", bytes.fromhex(re.sub(rb"\s", b"", h).decode() + ("0" if len(re.sub(rb"\s", b"", h)) % 2 else "")))
            elif lit is not None:
                v = ("str", unescape_literal(lit))
            elif nm is not None:
                v = ("name", nm.decode("latin-1"))
            elif num is not None:
                v = ("num", float(num))
            else:
                v = None
            if v is not None:
                if arr is not None:
                    arr.append(v)
                else:
                    stack.append(v)
                continue
            o = op.decode("latin-1")
            nums_ = [s[1] for s in stack if s[0] == "num"]
            if o == "Tf" and len(stack) >= 2 and stack[-2][0] == "name":
                cur = stack[-2][1]
            elif o == "Tm" and len(nums_) >= 6:
                x, y = nums_[-2], nums_[-1]
                lx, ly = x, y
            elif o in ("Td", "TD") and len(nums_) >= 2:
                lx, ly = lx + nums_[-2], ly + nums_[-1]
                x, y = lx, ly
                if o == "TD":
                    lead = -nums_[-1]
            elif o == "TL" and nums_:
                lead = nums_[-1]
            elif o == "T*":
                ly -= lead
                x, y = lx, ly
            elif o in ("Tj", "'", '"', "TJ"):
                enc, dec = fonts.get(cur, ("?", lambda raw: raw.decode("latin-1")))
                if o == "TJ":
                    parts = [s for s in (stack[-1][1] if stack and stack[-1][0] == "arr" else []) if s[0] == "str"]
                    txt = "".join(dec(s[1]) for s in parts)
                else:
                    strs = [s for s in stack if s[0] == "str"]
                    txt = dec(strs[-1][1]) if strs else ""
                if txt.strip():
                    rows.append((pno, x, y, f"{cur}:{enc}", txt))
            stack = []
    return rows


def pages_of(objs):
    # /Type /Pages の根から /Kids をたどって頁の順にする
    def kids(num):
        dic = objs.get(num, (b"", None))[0]
        if re.search(rb"/Type\s*/Page\b(?!s)", dic):
            return [num]
        km = re.search(rb"/Kids\s*\[([^\]]*)\]", dic)
        out = []
        for k in re.findall(rb"(\d+)\s+0\s+R", km.group(1) if km else b""):
            out += kids(int(k))
        return out
    roots = [n for n, (d, _) in objs.items() if re.search(rb"/Type\s*/Pages\b", d) and not re.search(rb"/Parent\s", d)]
    return kids(roots[0]) if roots else [n for n, (d, _) in sorted(objs.items()) if re.search(rb"/Type\s*/Page\b(?!s)", d)]


def lines_of(rows, tol=2.0):
    """同じ頁で y の差が tol 以下の文字列を1行にまとめ、x の昇順につなぐ（横書き用の近似）。"""
    out = []
    for pno in sorted({r[0] for r in rows}):
        pr = sorted((r for r in rows if r[0] == pno), key=lambda r: (-r[2], r[1]))
        cur, cy = [], None
        for r in pr:
            if cy is None or abs(r[2] - cy) <= tol:
                cur.append(r)
                cy = r[2] if cy is None else cy
            else:
                out.append((pno, cy, "".join(q[4] for q in sorted(cur, key=lambda q: q[1]))))
                cur, cy = [r], r[2]
        if cur:
            out.append((pno, cy, "".join(q[4] for q in sorted(cur, key=lambda q: q[1]))))
    return out


def vertical_of(rows, gap=20.0, xtol=3.0):
    """縦書きのフォント（Identity-V）の文字を、頁ごとに縦の帯（y の空きが gap を超えるところで分ける）に分け、
    帯の中では列（x が xtol 以内）を x の降順（右から左）、列の中の文字を y の降順（上から下）に並べる（縦書き用の近似）。"""
    out = []
    for pno in sorted({r[0] for r in rows}):
        pr = [r for r in rows if r[0] == pno and "Identity-V" in r[3]]
        if not pr:
            continue
        ys = sorted({round(r[2], 1) for r in pr}, reverse=True)
        bands, cur = [], [ys[0]]
        for a, b in zip(ys, ys[1:]):
            if a - b > gap:
                bands.append((cur[-1], cur[0]))
                cur = [b]
            else:
                cur.append(b)
        bands.append((cur[-1], cur[0]))
        for bi, (lo, hi) in enumerate(bands, 1):
            br = [r for r in pr if lo - 0.05 <= round(r[2], 1) <= hi + 0.05]
            cols = []
            for r in sorted(br, key=lambda r: -r[1]):
                if cols and abs(cols[-1][0] - r[1]) <= xtol:
                    cols[-1][1].append(r)
                else:
                    cols.append([r[1], [r]])
            for x, cr in cols:
                # 列の中で y の空きが gap を超えるところ（表の上下の欄の境など）に " ‖ " を入れる
                s, prev = [], None
                for q in sorted(cr, key=lambda q: -q[2]):
                    if prev is not None and prev - q[2] > gap:
                        s.append(" ‖ ")
                    s.append(q[4])
                    prev = q[2]
                out.append((pno, bi, x, "".join(s)))
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    rk = _expand(bytes(range(16)))
    selftest = aes128_decrypt_block(rk, bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a")).hex() == "00112233445566778899aabbccddeeff"
    sp = OUT / "summary.json"
    summary = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
    summary["aes_selftest"] = selftest
    summary["aes_selftest_fips197"] = aes_selftest_all()
    print("aes selftest", selftest, summary["aes_selftest_fips197"], flush=True)
    summary.setdefault("files", {})
    for arg in sys.argv[1:]:
        name, path = arg.split("=", 1)
        pdf = pathlib.Path(path).read_bytes()
        objs, key_ok, alg = load(pdf)
        pages = pages_of(objs)
        rows = []
        for i, pnum in enumerate(pages, 1):
            rows += page_rows(objs, i, objs[pnum][0])
        rows.sort(key=lambda r: (r[0], -round(r[2], 1), r[1]))
        head = f"# file={pathlib.Path(path).as_posix()} sha256={hashlib.sha256(pdf).hexdigest()} encrypt={alg} key_ok={key_ok} pages={len(pages)}\n"
        with open(OUT / f"{name}_text.tsv", "w", encoding="utf-8") as f:
            f.write(head)
            f.write("page\tx\ty\tfont\ttext\n")
            for r in rows:
                f.write(f"{r[0]}\t{r[1]:.1f}\t{r[2]:.1f}\t{r[3]}\t{r[4]}\n")
        lines = lines_of(rows)
        with open(OUT / f"{name}_lines.txt", "w", encoding="utf-8") as f:
            f.write(head)
            last = None
            for pno, y, t in lines:
                if pno != last:
                    f.write(f"\n=== page {pno}\n")
                    last = pno
                f.write(t + "\n")
        vlines = vertical_of(rows)
        if vlines:
            with open(OUT / f"{name}_vertical.txt", "w", encoding="utf-8") as f:
                f.write(head)
                last = None
                for pno, bi, x, t in vlines:
                    if (pno, bi) != last:
                        f.write(f"\n=== page {pno} band {bi}\n")
                        last = (pno, bi)
                    f.write(t + "\n")
        summary["files"][name] = {"path": pathlib.Path(path).as_posix(), "sha256": hashlib.sha256(pdf).hexdigest(), "encrypt": alg,
                                  "key_ok": key_ok, "pages": len(pages), "rows": len(rows), "lines": len(lines),
                                  "vertical_columns": len(vlines), "fonts": sorted({r[3] for r in rows})}
        print(name, alg, key_ok, "pages", len(pages), "rows", len(rows), "lines", len(lines), flush=True)
    sp.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
