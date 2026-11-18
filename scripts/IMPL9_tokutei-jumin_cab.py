"""IMPL9 tokutei-jumin cab: e-Tax の仕様書（CAB 形式）を標準ライブラリだけで読み、給与所得者の特定支出に関する明細書の様式ID・欄を探す。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL9_tokutei-jumin_cab.py list <CAB> [<CAB> ...]
      CAB の中のファイルの一覧（名前・大きさ）を .work/etax_spec_extract/IMPL9_tokutei-jumin_cab/list_<CAB の名前>.tsv に書く。
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL9_tokutei-jumin_cab.py extract <CAB> <語> [<語> ...]
      名前に語のどれかを含むファイルだけを、新しい空のディレクトリ .work/downloads/<YYYYMMDD-HHMMSS>_IMPL9_tokutei-jumin_cab/ に展開する
      （MSZIP の圧縮だけ扱う。展開したものは信頼できないデータ。中では何も実行しない）。
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL9_tokutei-jumin_cab.py grep <ディレクトリ> <語> [<語> ...]
      展開した xlsx（zip の XML）・xsd・csv・txt の文字を読み、語を含むセル・行を .work/etax_spec_extract/IMPL9_tokutei-jumin_cab/grep_<ts>.tsv に書く。
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL9_tokutei-jumin_cab.py sheet <xlsx> <出力の名前>
      xlsx の全部のシートのセルを（シート、セル番地、値）の TSV にして .work/etax_spec_extract/IMPL9_tokutei-jumin_cab/<出力の名前>.tsv に書く。

- CAB の形式（CFHEADER・CFFOLDER・CFFILE・CFDATA、MSZIP は 'CK' ＋ deflate で、前のブロックの出力を辞書にする）は Microsoft の公開仕様の形。
- ネットワークを使わない。
"""
import hashlib
import pathlib
import re
import struct
import sys
import time
import zipfile
import zlib
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent.parent
NAME = "IMPL9_tokutei-jumin_cab"
# e-Tax の仕様書には著作権があるため、抜き出した内容はリポジトリ（scripts/results）に置かず、
# git の管理外の .work/etax_spec_extract/ に書く（HANDOFF.md D21 R7：中身はリポジトリに写さない）。
OUT = ROOT / ".work" / "etax_spec_extract" / NAME


def _cstr(b, off):
    end = b.index(b"\0", off)
    return b[off:end], end + 1


def parse(path):
    b = pathlib.Path(path).read_bytes()
    if b[:4] != b"MSCF":
        raise ValueError("CAB でない")
    (cb_cab, coff_files) = struct.unpack_from("<I4xI", b, 8)
    c_folders, c_files, flags = struct.unpack_from("<HHH", b, 26)
    off = 36
    cb_hdr_res = cb_fold_res = cb_data_res = 0
    if flags & 0x4:
        cb_hdr_res, cb_fold_res, cb_data_res = struct.unpack_from("<HBB", b, off)
        off += 4 + cb_hdr_res
    if flags & 0x1:
        _, off = _cstr(b, off)
        _, off = _cstr(b, off)
    if flags & 0x2:
        _, off = _cstr(b, off)
        _, off = _cstr(b, off)
    folders = []
    for _ in range(c_folders):
        start, n_data, comp = struct.unpack_from("<IHH", b, off)
        folders.append((start, n_data, comp))
        off += 8 + cb_fold_res
    files = []
    off = coff_files
    for _ in range(c_files):
        size, ustart, ifold, _date, _time, attr = struct.unpack_from("<IIHHHH", b, off)
        raw, off = _cstr(b, off + 16)
        name = raw.decode("utf-8" if attr & 0x80 else "cp932", "replace")
        files.append({"name": name, "size": size, "offset": ustart, "folder": ifold})
    return b, folders, files, cb_data_res


def folder_bytes(b, folder, cb_data_res):
    start, n_data, comp = folder
    if comp & 0xF not in (0, 1):
        raise ValueError(f"MSZIP でない圧縮（{comp & 0xF}）")
    off, out, prev = start, bytearray(), b""
    for _ in range(n_data):
        _csum, cb_data, cb_unc = struct.unpack_from("<IHH", b, off)
        data = b[off + 8 + cb_data_res: off + 8 + cb_data_res + cb_data]
        off += 8 + cb_data_res + cb_data
        if comp & 0xF == 0:
            chunk = data
        else:
            if data[:2] != b"CK":
                raise ValueError("MSZIP のブロックの印がない")
            d = zlib.decompressobj(-15, zdict=prev) if prev else zlib.decompressobj(-15)
            chunk = d.decompress(data[2:]) + d.flush()
        if len(chunk) != cb_unc:
            raise ValueError("展開の大きさが違う")
        out += chunk
        prev = bytes(out[-32768:])
    return bytes(out)


def cmd_list(cabs):
    OUT.mkdir(parents=True, exist_ok=True)
    for cab in cabs:
        b, folders, files, _ = parse(cab)
        lines = [f"# cab={pathlib.Path(cab).name} sha256={hashlib.sha256(b).hexdigest()} folders={len(folders)} "
                 f"compress={[f[2] & 0xF for f in folders]} files={len(files)}", "name\tsize"]
        lines += [f"{f['name']}\t{f['size']}" for f in files]
        (OUT / f"list_{pathlib.Path(cab).stem}.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(cab, len(files))


def cmd_extract(cab, words):
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_{NAME}"
    dl.mkdir(parents=True, exist_ok=False)
    b, folders, files, res = parse(cab)
    cache = {}
    n = 0
    for f in files:
        if not any(w in f["name"] for w in words):
            continue
        if f["folder"] not in cache:
            cache[f["folder"]] = folder_bytes(b, folders[f["folder"]], res)
        data = cache[f["folder"]][f["offset"]: f["offset"] + f["size"]]
        safe = re.sub(r"[^\w.\-]", "_", f["name"].replace("\\", "__"))
        (dl / safe).write_bytes(data)
        n += 1
        print("extract", f["name"], len(data), hashlib.sha256(data).hexdigest()[:16])
    print("done", dl, n)


NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def xlsx_cells(path):
    """xlsx（zip の XML）からセルの値を読む（共有文字列を引く）。"""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        shared = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall("m:si", NS):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        sheet_names = [s.get("name") for s in wb.findall("m:sheets/m:sheet", NS)]
        sheets = sorted((n for n in names if re.match(r"xl/worksheets/sheet\d+\.xml$", n)), key=lambda n: int(re.findall(r"\d+", n)[-1]))
        for i, sn in enumerate(sheets):
            root = ET.fromstring(z.read(sn))
            title = sheet_names[i] if i < len(sheet_names) else sn
            for c in root.iter(f"{{{NS['m']}}}c"):
                v = c.find("m:v", NS)
                if v is None:
                    is_ = c.find("m:is", NS)
                    val = "".join(t.text or "" for t in is_.iter(f"{{{NS['m']}}}t")) if is_ is not None else None
                else:
                    val = shared[int(v.text)] if c.get("t") == "s" else v.text
                if val not in (None, ""):
                    yield title, c.get("r"), val


def cmd_grep(directory, words):
    OUT.mkdir(parents=True, exist_ok=True)
    rows = ["file\tsheet_or_line\tcell\tvalue"]
    for p in sorted(pathlib.Path(directory).iterdir()):
        try:
            if p.suffix.lower() in (".xlsx", ".xlsm"):
                for sheet, ref, val in xlsx_cells(p):
                    if any(w in val for w in words):
                        rows.append(f"{p.name}\t{sheet}\t{ref}\t{val.replace(chr(10), ' ').replace(chr(9), ' ')}")
            elif p.suffix.lower() in (".xsd", ".xml", ".csv", ".txt"):
                raw = p.read_bytes()
                t = None
                for enc in ("utf-8", "cp932"):
                    try:
                        t = raw.decode(enc)
                        break
                    except UnicodeDecodeError:
                        continue
                for i, line in enumerate((t or raw.decode("utf-8", "replace")).splitlines(), 1):
                    if any(w in line for w in words):
                        rows.append(f"{p.name}\t{i}\t\t{line.strip()[:400]}")
        except (zipfile.BadZipFile, ET.ParseError, KeyError) as e:
            rows.append(f"{p.name}\t-\t-\tERROR {e!r}")
    ts = time.strftime("%Y%m%d-%H%M%S")
    (OUT / f"grep_{ts}.tsv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(len(rows) - 1, OUT / f"grep_{ts}.tsv")


def cmd_sheet(path, out_name):
    OUT.mkdir(parents=True, exist_ok=True)
    rows = [f"# file={pathlib.Path(path).name} sha256={hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()}", "sheet\tcell\tvalue"]
    for sheet, ref, val in xlsx_cells(path):
        rows.append(f"{sheet}\t{ref}\t{val.replace(chr(10), ' ').replace(chr(9), ' ')}")
    (OUT / f"{out_name}.tsv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(len(rows) - 2)


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["list"] and len(a) >= 2:
        cmd_list(a[1:])
    elif a[:1] == ["extract"] and len(a) >= 3:
        cmd_extract(a[1], a[2:])
    elif a[:1] == ["grep"] and len(a) >= 3:
        cmd_grep(a[1], a[2:])
    elif a[:1] == ["sheet"] and len(a) == 3:
        cmd_sheet(a[1], a[2])
    else:
        print(__doc__)
        sys.exit(2)
