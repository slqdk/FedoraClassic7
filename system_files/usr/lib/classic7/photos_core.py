"""Photo Viewer: the picture list of a folder, and saving rotations/flips to the file.

JPEG files are turned without re-compressing: only the EXIF "Orientation" tag is changed (or
added), which every viewer and browser follows. Other formats Pillow can write (PNG, BMP, TIFF,
WebP, still GIF) are saved again with the turned pixels.
"""
from __future__ import annotations

import os
import re
import struct
from pathlib import Path

# 2x2 matrices (display coordinates, y down) of the 8 EXIF orientations
ORIENT = {
    1: (1, 0, 0, 1),
    2: (-1, 0, 0, 1),
    3: (-1, 0, 0, -1),
    4: (1, 0, 0, -1),
    5: (0, 1, 1, 0),
    6: (0, -1, 1, 0),
    7: (0, -1, -1, 0),
    8: (0, 1, -1, 0),
}
BY_MATRIX = {v: k for k, v in ORIENT.items()}
ROT_CW = ORIENT[6]
ROT_CCW = ORIENT[8]
FLIP_H = ORIENT[2]
FLIP_V = ORIENT[4]
IDENTITY = ORIENT[1]


def mul(a, b):
    """a ∘ b (apply b first, then a)."""
    return (a[0] * b[0] + a[1] * b[2], a[0] * b[1] + a[1] * b[3],
            a[2] * b[0] + a[3] * b[2], a[2] * b[1] + a[3] * b[3])


def natural_key(name: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def folder_pictures(path: Path, extensions: set[str]) -> list[Path]:
    try:
        files = [p for p in path.parent.iterdir()
                 if p.is_file() and p.suffix.lower().lstrip(".") in extensions and not p.name.startswith(".")]
    except OSError:
        files = []
    if path not in files and path.exists():
        files.append(path)
    return sorted(files, key=lambda p: natural_key(p.name))


# ---- JPEG: lossless turn via the EXIF orientation tag ----------------------------------------
def _jpeg_segments(data: bytes):
    """Yield (marker, start, length) of the segments before the image data."""
    if data[:2] != b"\xff\xd8":
        raise ValueError("not a JPEG file")
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            raise ValueError("broken JPEG file")
        marker = data[pos + 1]
        if marker == 0xDA:          # start of scan: image data follows
            return
        length = struct.unpack(">H", data[pos + 2:pos + 4])[0]
        yield marker, pos, length + 2
        pos += 2 + length


def jpeg_orientation(data: bytes) -> tuple[int, int | None]:
    """(orientation, byte offset of its value or None)."""
    for marker, start, length in _jpeg_segments(data):
        if marker != 0xE1 or data[start + 4:start + 10] != b"Exif\x00\x00":
            continue
        tiff = start + 10
        endian = data[tiff:tiff + 2]
        if endian not in (b"II", b"MM"):
            continue
        e = "<" if endian == b"II" else ">"
        ifd = tiff + struct.unpack(e + "I", data[tiff + 4:tiff + 8])[0]
        count = struct.unpack(e + "H", data[ifd:ifd + 2])[0]
        for i in range(count):
            entry = ifd + 2 + 12 * i
            tag = struct.unpack(e + "H", data[entry:entry + 2])[0]
            if tag == 0x0112:
                value = struct.unpack(e + "H", data[entry + 8:entry + 10])[0]
                return (value if value in ORIENT else 1), entry + 8
        return 1, None
    return 1, None


def _exif_segment(orientation: int) -> bytes:
    body = (b"Exif\x00\x00" + b"MM\x00\x2a\x00\x00\x00\x08"          # TIFF header, IFD0 at 8
            + struct.pack(">H", 1)                                     # one entry
            + struct.pack(">HHIHH", 0x0112, 3, 1, orientation, 0)      # Orientation, SHORT
            + struct.pack(">I", 0))                                    # no next IFD
    return b"\xff\xe1" + struct.pack(">H", len(body) + 2) + body


def turn_jpeg(path: Path, op) -> None:
    data = path.read_bytes()
    current, offset = jpeg_orientation(data)
    new = BY_MATRIX[mul(op, ORIENT[current])]
    if offset is not None:
        # endianness: the TIFF header of this EXIF block
        tiff = data.rfind(b"Exif\x00\x00", 0, offset) + 6
        e = "<" if data[tiff:tiff + 2] == b"II" else ">"
        out = data[:offset] + struct.pack(e + "H", new) + data[offset + 2:]
    else:
        # put a small EXIF block after SOI and a JFIF APP0, if there is one
        insert = 2
        for marker, start, length in _jpeg_segments(data):
            if marker == 0xE0:
                insert = start + length
            break
        out = data[:insert] + _exif_segment(new) + data[insert:]
    _write_atomic(path, out)


# ---- other formats: save the turned pixels again --------------------------------------------
PIL_WRITABLE = {"png", "bmp", "tif", "tiff", "webp", "gif", "ppm", "pgm", "pbm", "tga", "ico"}


def turn_other(path: Path, op) -> None:
    from PIL import Image, ImageOps
    with Image.open(path) as im:
        if getattr(im, "is_animated", False) and getattr(im, "n_frames", 1) > 1:
            raise ValueError("Animated pictures can't be turned.")
        fmt = im.format
        info = dict(im.info)
        im.load()
        img = ImageOps.exif_transpose(im)
    method = {ROT_CW: Image.Transpose.ROTATE_270, ROT_CCW: Image.Transpose.ROTATE_90,
              ORIENT[3]: Image.Transpose.ROTATE_180, FLIP_H: Image.Transpose.FLIP_LEFT_RIGHT,
              FLIP_V: Image.Transpose.FLIP_TOP_BOTTOM, ORIENT[5]: Image.Transpose.TRANSPOSE,
              ORIENT[7]: Image.Transpose.TRANSVERSE}.get(op)
    if method is None:
        return
    img = img.transpose(method)
    params = {}
    if fmt == "WEBP":
        params["lossless"] = bool(info.get("lossless", False))
        params["quality"] = 95
    if fmt == "PNG" and "icc_profile" in info:
        params["icc_profile"] = info["icc_profile"]
    tmp = path.with_name("." + path.name + ".turning")
    img.save(tmp, format=fmt, **params)
    os.replace(tmp, path)


def can_turn(path: Path) -> bool:
    ext = path.suffix.lower().lstrip(".")
    return ext in ("jpg", "jpeg", "jpe", "jfif") or ext in PIL_WRITABLE


def save_turn(path: Path, op) -> None:
    """Apply op (one of the ORIENT matrices, in display space) to the file."""
    if op == IDENTITY:
        return
    ext = path.suffix.lower().lstrip(".")
    if ext in ("jpg", "jpeg", "jpe", "jfif"):
        turn_jpeg(path, op)
    elif ext in PIL_WRITABLE:
        turn_other(path, op)
    else:
        raise ValueError(f"Pictures of type .{ext} can't be saved turned.")


def _write_atomic(path: Path, data: bytes):
    st = path.stat()
    tmp = path.with_name("." + path.name + ".turning")
    tmp.write_bytes(data)
    os.chmod(tmp, st.st_mode & 0o7777)
    os.replace(tmp, path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
