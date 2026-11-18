"""R2X_yoshiki_pdftext: 国税庁の様式 PDF（空のユーザーパスワードで暗号化）を標準ライブラリだけで復号し、
(1) ページごとの中身の種類（テキスト層の有無、画像の有無と大きさ）、(2) 様式ID（NTA で始まる16文字）とその文字、
(3) テキスト層の文字列と位置、(4) 欄コード（G01 など）と同じ高さにある文字列の対応、を書き出す。

実行（Windows）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_yoshiki_pdftext.py <出力名> <PDF>
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_yoshiki_pdftext.py --selftest

- 復号（RC4/AESV2、Standard セキュリティハンドラ R3・R4、ユーザーパスワード空）と、90ms-RKSJ（Shift_JIS）の文字列の読み方は
  scripts/IMPL_output_verify.py（2026-11-09 の独立検証のスクリプト）の pdf_streams・aes128_* を写した（import はしない）。
  そのうえで、オブジェクトストリーム（/ObjStm）の中のオブジェクトも読めるようにし、テキストの位置は Tm に加えて Td・TD・T* も追う。
- PDF は信頼できないデータとして、ファイルを読むだけにする（中のスクリプト・フォーム・リンクは解釈しない）。
  展開後のストリームの大きさは MAX_INFLATE で打ち切る。
- AES は FIPS-197 Appendix C.1 の試験ベクタで自己検査してから使う。
- 出力：scripts/results/R2X_yoshiki_pdftext/<出力名>_summary.json（ページごとの中身、様式ID、鍵の検査）、
  <出力名>_text.tsv（頁, x, y, フォント, 文字列）、<出力名>_codes.tsv（欄コードと同じ高さで左にある文字列）。
"""
import hashlib
import json
import pathlib
import re
import sys
import zlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "scripts" / "results" / "R2X_yoshiki_pdftext"
MAX_INFLATE = 64 * 1024 * 1024


# ---------------------------------------------------------------- AES-128（復号のみ）。IMPL_output_verify.py から写した
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


def selftest():
    rk = _expand(bytes(range(16)))
    return aes128_decrypt_block(rk, bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a")).hex() == "00112233445566778899aabbccddeeff"


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


# ---------------------------------------------------------------- PDF のオブジェクト
def inflate(b):
    d = zlib.decompressobj()
    out = d.decompress(b, MAX_INFLATE)
    return out


def top_objects(pdf):
    """(objnum, gen, 辞書部分, 生のストリーム or None)"""
    for m in re.finditer(rb"(\d+)\s+(\d+)\s+obj\b", pdf):
        end = pdf.find(b"endobj", m.end())
        if end < 0:
            continue
        body = pdf[m.end():end]
        sm = re.search(rb"stream\r?\n", body)
        if not sm:
            yield int(m.group(1)), int(m.group(2)), body, None
            continue
        dic = body[:sm.start()]
        lm = re.search(rb"/Length\s+(\d+)(?!\s+\d+\s+R)", dic)
        raw = body[sm.end():sm.end() + int(lm.group(1))] if lm else body[sm.end():body.rfind(b"endstream")].rstrip(b"\r\n")
        yield int(m.group(1)), int(m.group(2)), dic, raw


def load(pdf):
    """全オブジェクトを {num: (辞書, 展開後のストリーム or None)} にする。暗号化はユーザーパスワード空で解く。"""
    enc = re.search(rb"/Encrypt\s+(\d+)\s+0\s+R", pdf)
    info = {"encrypted": bool(enc)}
    key, aes = None, False
    if enc:
        encnum = int(enc.group(1))
        em = re.search(rb"\b%d\s+0\s+obj(.*?)endobj" % encnum, pdf, re.S).group(1)
        o = bytes.fromhex(re.search(rb"/O\s*<([0-9a-fA-F]+)>", em).group(1).decode())
        u = bytes.fromhex(re.search(rb"/U\s*<([0-9a-fA-F]+)>", em).group(1).decode())
        p = int(re.search(rb"/P\s+(-?\d+)", em).group(1))
        r = int(re.search(rb"/R\s+(\d+)", em).group(1))
        v = int(re.search(rb"/V\s+(\d+)", em).group(1))
        if v >= 5:
            # AES-256（AESV3, R5/R6）は SHA-256 系の鍵の作り方が別で、このスクリプトでは扱わない（読まずに印だけ残す）
            info.update(V=v, R=r, unsupported="V5 以上（AESV3）の暗号化は未対応。文字は取り出していない")
            return info, {}
        ln = re.search(rb"/Length\s+(\d+)", em)
        klen = (int(ln.group(1)) // 8) if ln else 5
        aes = b"AESV2" in em
        if aes:
            klen = 16
        id0 = bytes.fromhex(re.search(rb"/ID\s*\[\s*<([0-9a-fA-F]+)>", pdf).group(1).decode())
        h = hashlib.md5(PAD + o + (p & 0xFFFFFFFF).to_bytes(4, "little") + id0).digest()
        if r >= 3:
            for _ in range(50):
                h = hashlib.md5(h[:klen]).digest()
        key = h[:klen]
        if r >= 3:
            x = _rc4(key, hashlib.md5(PAD + id0).digest())
            for i in range(1, 20):
                x = _rc4(bytes(k ^ i for k in key), x)
            key_ok = x == u[:16]
        else:
            key_ok = _rc4(key, PAD) == u
        info.update(V=v, R=r, P=p, aes=aes, key_len=klen, key_ok=key_ok, encrypt_obj=encnum)
    objs = {}
    for num, gen, dic, raw in top_objects(pdf):
        if enc and num == info["encrypt_obj"]:
            continue
        if raw is not None:
            if key is not None and b"/XRef" not in dic:
                okey = hashlib.md5(key + num.to_bytes(3, "little") + gen.to_bytes(2, "little") + (b"sAlT" if aes else b"")).digest()[:min(len(key) + 5, 16)]
                raw = aes128_cbc_decrypt(okey, raw) if aes else _rc4(okey, raw)
            data = raw
            if b"FlateDecode" in dic:
                try:
                    data = inflate(raw)
                except Exception as e:  # noqa
                    data = b""
                    info.setdefault("inflate_errors", []).append([num, repr(e)])
            objs[num] = (dic, data)
        else:
            objs[num] = (dic, None)
    # オブジェクトストリームの中身（中のオブジェクトは個別には暗号化されない）
    for num, (dic, data) in list(objs.items()):
        if data and b"/ObjStm" in dic:
            n = int(re.search(rb"/N\s+(\d+)", dic).group(1))
            first = int(re.search(rb"/First\s+(\d+)", dic).group(1))
            head = data[:first].split()
            pairs = [(int(head[i]), int(head[i + 1])) for i in range(0, min(len(head), 2 * n) - 1, 2)]
            for k, (onum, off) in enumerate(pairs):
                end = pairs[k + 1][1] if k + 1 < len(pairs) else len(data) - first
                objs.setdefault(onum, (data[first + off:first + end], None))
    return info, objs


def resolve_pages(objs):
    """/Type /Catalog → /Pages → /Kids を辿り、ページのオブジェクト番号の順序を返す。"""
    cat = next((n for n, (d, _) in objs.items() if re.search(rb"/Type\s*/Catalog", d)), None)
    if cat is None:
        return []
    root = int(re.search(rb"/Pages\s+(\d+)\s+0\s+R", objs[cat][0]).group(1))
    out = []

    def walk(n, depth=0):
        if depth > 20 or n not in objs:
            return
        d = objs[n][0]
        if re.search(rb"/Type\s*/Pages", d):
            kids = re.search(rb"/Kids\s*\[([^\]]*)\]", d)
            for k in re.findall(rb"(\d+)\s+0\s+R", kids.group(1) if kids else b""):
                walk(int(k), depth + 1)
        else:
            out.append(n)
    walk(root)
    return out


def page_contents(objs, pnum):
    d = objs[pnum][0]
    m = re.search(rb"/Contents\s*(\[[^\]]*\]|\d+\s+0\s+R)", d)
    if not m:
        return b""
    nums = [int(x) for x in re.findall(rb"(\d+)\s+0\s+R", m.group(1))]
    if len(nums) == 1 and objs.get(nums[0], (b"", None))[1] is None:
        # 配列への間接参照
        arr = objs[nums[0]][0]
        nums = [int(x) for x in re.findall(rb"(\d+)\s+0\s+R", arr)]
    return b"\n".join((objs.get(c, (b"", b""))[1] or b"") for c in nums)


def page_resources(objs, pnum):
    """ページの /Resources（直接の辞書か間接参照。無ければ親の /Pages から継ぐ）を返す。"""
    n = pnum
    for _ in range(20):
        d = objs.get(n, (b"", None))[0]
        rm = re.search(rb"/Resources\s+(\d+)\s+0\s+R", d)
        if rm and int(rm.group(1)) in objs:
            return objs[int(rm.group(1))][0]
        if b"/Resources" in d:
            return d[d.find(b"/Resources"):]
        pm = re.search(rb"/Parent\s+(\d+)\s+0\s+R", d)
        if not pm:
            return d
        n = int(pm.group(1))
    return b""


def parse_cmap(b):
    m = {}
    for blk in re.findall(rb"beginbfchar(.*?)endbfchar", b, re.S):
        for a, c in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", blk):
            m[int(a, 16)] = bytes.fromhex(c.decode()).decode("utf-16-be", "replace")
    for blk in re.findall(rb"beginbfrange(.*?)endbfrange", b, re.S):
        for a, z, c in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", blk):
            base = int(c, 16)
            for k in range(int(a, 16), min(int(z, 16), int(a, 16) + 65536) + 1):
                m[k] = chr(base + k - int(a, 16)) if base + k - int(a, 16) < 0x110000 else "�"
    return m


def page_fonts(objs, pnum):
    """フォント名 → 文字列を読む関数。ToUnicode があればそれを使い（Type0 は2バイト、その他は1バイト）、
    無ければ符号化名に RKSJ を含むものは cp932、それ以外は latin-1 で読む。"""
    res = page_resources(objs, pnum)
    fm = re.search(rb"/Font\s*(<<.*?>>|\d+\s+0\s+R)", res, re.S)
    out = {}
    if not fm:
        return out
    blob = fm.group(1)
    if blob[:2] != b"<<":
        blob = objs.get(int(blob.split()[0]), (b"", None))[0]
    for name, n in re.findall(rb"/([\w.+-]+)\s+(\d+)\s+0\s+R", blob):
        fd = objs.get(int(n), (b"", None))[0]
        tu = re.search(rb"/ToUnicode\s+(\d+)\s+0\s+R", fd)
        enc = re.search(rb"/Encoding\s*/([\w-]+)", fd)
        two = b"/Type0" in fd
        if tu and objs.get(int(tu.group(1)), (b"", None))[1]:
            cm = parse_cmap(objs[int(tu.group(1))][1])
            out[name.decode()] = ("cmap2" if two else "cmap1", cm)
        elif enc and b"RKSJ" in enc.group(1):
            out[name.decode()] = ("cp932", None)
        else:
            out[name.decode()] = ("latin-1", None)
    return out


def decode_with(font, raw):
    kind, cm = font if font else ("cp932", None)
    if kind == "cmap2":
        return "".join(cm.get(int.from_bytes(raw[i:i + 2], "big"), "�") for i in range(0, len(raw) - 1, 2))
    if kind == "cmap1":
        return "".join(cm.get(b, chr(b)) for b in raw)
    return raw.decode(kind, "replace")


def page_xobjects(objs, pnum):
    res = page_resources(objs, pnum)
    xs = []
    xm = re.search(rb"/XObject\s*(<<.*?>>|\d+\s+0\s+R)", res, re.S)
    if xm:
        blob = xm.group(1)
        if blob[:2] != b"<<":
            blob = objs.get(int(blob.split()[0]), (b"", None))[0]
        for name, n in re.findall(rb"/(\w+)\s+(\d+)\s+0\s+R", blob):
            od = objs.get(int(n), (b"", None))[0]
            st = re.search(rb"/Subtype\s*/(\w+)", od)
            w = re.search(rb"/Width\s+(\d+)", od)
            h = re.search(rb"/Height\s+(\d+)", od)
            f = re.search(rb"/Filter\s*/(\w+)", od)
            xs.append({"name": name.decode(), "obj": int(n), "subtype": st.group(1).decode() if st else None,
                       "w": int(w.group(1)) if w else None, "h": int(h.group(1)) if h else None,
                       "filter": f.group(1).decode() if f else None})
    return xs


TOKEN = re.compile(rb"<([0-9A-Fa-f\s]*)>|\(((?:[^()\\]|\\.|\((?:[^()\\]|\\.)*\))*)\)|\[|\]|/[^\s/\[\]()<>]+|[-+]?\d*\.?\d+|[A-Za-z'\"*]+")


def unescape(lit):
    out = bytearray()
    i = 0
    while i < len(lit):
        c = lit[i]
        if c == 0x5C and i + 1 < len(lit):
            n = lit[i + 1]
            if n in b"nrtbf":
                out.append({ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12}[n])
                i += 2
            elif 0x30 <= n <= 0x37:
                m = re.match(rb"[0-7]{1,3}", lit[i + 1:])
                out.append(int(m.group(0), 8) & 0xFF)
                i += 1 + len(m.group(0))
            else:
                out.append(n)
                i += 2
        else:
            out.append(c)
            i += 1
    return bytes(out)


def text_runs(content, fonts=None):
    """BT..ET の中を順に読み、(x, y, フォント, 文字列) を返す。文字列はフォントごとの読み方（page_fonts）で読む。
    フォントが分からないときは cp932（90ms-RKSJ の Type0 を想定）として読む。"""
    fonts = fonts or {}
    runs = []
    for bt in re.findall(rb"\bBT\b(.*?)\bET\b", content, re.S):
        x = y = 0.0
        lx = ly = 0.0
        lead = 0.0
        font = ""
        stack = []
        for m in TOKEN.finditer(bt):
            tok = m.group(0)
            if m.group(1) is not None:
                stack.append(("str", bytes.fromhex(re.sub(rb"\s", b"", m.group(1)).decode() or "")))
            elif m.group(2) is not None:
                stack.append(("str", unescape(m.group(2))))
            elif tok == b"[":
                stack.append(("[", None))
            elif tok == b"]":
                arr = []
                while stack and stack[-1][0] != "[":
                    arr.append(stack.pop())
                if stack:
                    stack.pop()
                stack.append(("arr", list(reversed(arr))))
            elif tok.startswith(b"/"):
                stack.append(("name", tok[1:].decode("latin-1")))
            elif re.fullmatch(rb"[-+]?\d*\.?\d+", tok):
                stack.append(("num", float(tok)))
            else:
                op = tok
                nums = [v for k, v in stack if k == "num"]
                if op == b"Tf" and any(k == "name" for k, _ in stack):
                    font = [v for k, v in stack if k == "name"][-1]
                elif op == b"Tm" and len(nums) >= 6:
                    lx, ly = nums[-2], nums[-1]
                    x, y = lx, ly
                elif op in (b"Td", b"TD") and len(nums) >= 2:
                    lx, ly = lx + nums[-2], ly + nums[-1]
                    x, y = lx, ly
                    if op == b"TD":
                        lead = -nums[-1]
                elif op == b"TL" and nums:
                    lead = nums[-1]
                elif op == b"T*":
                    ly -= lead
                    x, y = lx, ly
                elif op in (b"Tj", b"'", b'"', b"TJ"):
                    if op in (b"'", b'"'):
                        ly -= lead
                        x, y = lx, ly
                    parts = []
                    for k, v in stack:
                        if k == "str":
                            parts.append(v)
                        elif k == "arr":
                            parts += [vv for kk, vv in v if kk == "str"]
                    s = decode_with(fonts.get(font), b"".join(parts))
                    if s.strip():
                        runs.append((x, y, font, s))
                stack = []
    return runs


def analyze(name, path):
    pdf = pathlib.Path(path).read_bytes()
    info, objs = load(pdf)
    pages = resolve_pages(objs)
    summary = {"file": pathlib.Path(path).name, "sha256": hashlib.sha256(pdf).hexdigest(), "bytes": len(pdf),
               "aes_selftest": selftest(), **info, "n_objects": len(objs), "pages": []}
    rows = []
    for pno, pnum in enumerate(pages, 1):
        content = page_contents(objs, pnum)
        runs = text_runs(content, page_fonts(objs, pnum))
        xs = page_xobjects(objs, pnum)
        mb = re.search(rb"/MediaBox\s*\[([^\]]*)\]", objs[pnum][0])
        summary["pages"].append({"page": pno, "obj": pnum, "mediabox": mb.group(1).decode().split() if mb else None,
                                 "content_bytes": len(content), "n_text_runs": len(runs), "xobjects": xs})
        rows += [(pno, r[0], r[1], r[2], r[3]) for r in runs]
    alltext = " ".join(r[4] for r in rows)
    ids = sorted(set(re.findall(r"NTA[0-9A-Z]{13}", alltext.replace(" ", ""))))
    summary["form_ids"] = [{"id": i, "chars_4_to_6": [f"{c}(U+{ord(c):04X})" for c in i[3:6]]} for i in ids]
    outl = []
    for n, (d, data) in objs.items():
        for t in re.findall(rb"/Title\s*\(((?:[^()\\]|\\.)*)\)", d):
            outl.append(unescape(t).decode("latin-1"))
    summary["titles_in_dicts"] = outl[:50]
    OUT.mkdir(parents=True, exist_ok=True)
    rows.sort(key=lambda r: (r[0], -r[2], r[1]))
    with open(OUT / f"{name}_text.tsv", "w", encoding="utf-8") as f:
        f.write(f"# file={summary['file']} sha256={summary['sha256']}\n")
        f.write("page\tx\ty\tfont\ttext\n")
        for r in rows:
            f.write(f"{r[0]}\t{r[1]:.1f}\t{r[2]:.1f}\t{r[3]}\t{r[4]}\n")
    code_rx = re.compile(r"[A-Z]\d{2,3}")
    with open(OUT / f"{name}_codes.tsv", "w", encoding="utf-8") as f:
        f.write("page\tcode\tx\ty\tsame_line_left_texts(x昇順, 160pt以内)\tsame_line_right_texts(x昇順, 60pt以内)\n")
        for r in rows:
            if code_rx.fullmatch(r[4].strip()):
                left = sorted((q for q in rows if q[0] == r[0] and abs(q[2] - r[2]) <= 2.5 and r[1] - 160 < q[1] < r[1]
                               and not code_rx.fullmatch(q[4].strip())), key=lambda q: q[1])
                right = sorted((q for q in rows if q[0] == r[0] and abs(q[2] - r[2]) <= 2.5 and r[1] < q[1] < r[1] + 60
                                and not code_rx.fullmatch(q[4].strip())), key=lambda q: q[1])
                f.write(f"{r[0]}\t{r[4].strip()}\t{r[1]:.1f}\t{r[2]:.1f}\t{' / '.join(q[4] for q in left)}\t{' / '.join(q[4] for q in right)}\n")
    summary["n_rows"] = len(rows)
    summary["n_codes"] = sum(1 for r in rows if code_rx.fullmatch(r[4].strip()))
    (OUT / f"{name}_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "titles_in_dicts"}, ensure_ascii=False)[:3000])


def page_images(path):
    """ページごとの画像 XObject（復号後のストリーム）の SHA-256 と、テキストの数を返す。2つの PDF の中身の同一性を見るため。"""
    pdf = pathlib.Path(path).read_bytes()
    info, objs = load(pdf)
    out = []
    for pno, pnum in enumerate(resolve_pages(objs), 1):
        imgs = []
        for x in page_xobjects(objs, pnum):
            if x["subtype"] == "Image":
                data = objs.get(x["obj"], (b"", b""))[1] or b""
                imgs.append({"w": x["w"], "h": x["h"], "filter": x["filter"], "sha256": hashlib.sha256(data).hexdigest()})
        content = page_contents(objs, pnum)
        out.append({"page": pno, "images": imgs, "content_sha256": hashlib.sha256(content).hexdigest(),
                    "n_text_runs": len(text_runs(content, page_fonts(objs, pnum)))})
    return {"file": pathlib.Path(path).name, "sha256": hashlib.sha256(pdf).hexdigest(), "pages": out}


def compare(name, pairs):
    """pairs: [(PDF_a, PDF_b), ...]。ファイル全体・ページごとの画像・内容ストリームの SHA-256 を比べる。"""
    res = []
    for a, b in pairs:
        A, B = page_images(a), page_images(b)
        imgs_a = [i["sha256"] for p in A["pages"] for i in p["images"] if (i["w"] or 0) > 1000]
        imgs_b = [i["sha256"] for p in B["pages"] for i in p["images"] if (i["w"] or 0) > 1000]
        res.append({"a": A, "b": B, "same_file": A["sha256"] == B["sha256"],
                    "large_images_a": len(imgs_a), "large_images_b": len(imgs_b),
                    "large_images_of_b_found_in_a": [s in imgs_a for s in imgs_b],
                    "contents_equal_by_page": [pa["content_sha256"] == pb["content_sha256"] for pa, pb in zip(A["pages"], B["pages"])]})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}_compare.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in res:
        print(r["a"]["file"][:60], "|", r["b"]["file"][:60], "same_file", r["same_file"], "imgs_b_in_a", r["large_images_of_b_found_in_a"],
              "contents_eq", r["contents_equal_by_page"])


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if argv and argv[0] == "--selftest":
        print("aes_selftest", selftest())
        return 0
    if argv and argv[0] == "--compare":
        # 使い方: --compare <出力名> <PDF_a1> <PDF_b1> [<PDF_a2> <PDF_b2> ...]
        rest = argv[2:]
        compare(re.sub(r"[^A-Za-z0-9_-]", "_", argv[1]), list(zip(rest[0::2], rest[1::2])))
        return 0
    if len(argv) != 2:
        print(__doc__)
        return 2
    analyze(re.sub(r"[^A-Za-z0-9_-]", "_", argv[0]), argv[1])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
