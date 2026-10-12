"""Show: PowerPoint 97-2003 files (.ppt, .pps, .pot) - read into the presentation model.

The binary format ([MS-PPT]): an OLE compound file whose "PowerPoint Document" stream holds
records (containers and atoms). The newest edit is found through "Current User" -> UserEditAtom ->
PersistDirectoryAtom; slides are OfficeArt drawings (Escher) with text in ClientTextbox records.
What comes in: slides in order, placeholders and text with fonts, sizes, colours, bold/italic/
underline, alignment, bullets and levels, shapes with fills and lines, pictures (PNG/JPEG/DIB/TIFF),
groups, backgrounds, the master's decorations and text styles, notes, transitions, hidden slides.
"""
from __future__ import annotations

import struct
import zlib

import show_model as sm

MASTER_UNIT = 914400 / 576          # EMU per master unit (576 per inch)

# record types
RT_DOCUMENT = 0x03E8
RT_DOCUMENT_ATOM = 0x03E9
RT_SLIDE = 0x03EE
RT_SLIDE_ATOM = 0x03EF
RT_NOTES = 0x03F0
RT_NOTES_ATOM = 0x03F1
RT_ENVIRONMENT = 0x03F2
RT_SLIDE_PERSIST_ATOM = 0x03F3
RT_MAIN_MASTER = 0x03F8
RT_SSSLIDE_INFO = 0x03F9
RT_PPDRAWING_GROUP = 0x040B
RT_PPDRAWING = 0x040C
RT_COLOR_SCHEME = 0x07F0
RT_FONT_COLLECTION = 0x07D5
RT_OUTLINE_TEXT_REF = 0x0F9E
RT_TEXT_HEADER = 0x0F9F
RT_TEXT_CHARS = 0x0FA0
RT_STYLE_TEXT_PROP = 0x0FA1
RT_TX_MASTER_STYLE = 0x0FA3
RT_TEXT_BYTES = 0x0FA8
RT_FONT_ENTITY = 0x0FB7
RT_SLIDE_LIST_WITH_TEXT = 0x0FF0
RT_USER_EDIT = 0x0FF5
RT_PERSIST_DIR = 0x1772
RT_PLACEHOLDER = 0x0BC3
RT_INTERACTIVE_INFO = 0x0FF2
RT_INTERACTIVE_INFO_ATOM = 0x0FF3
RT_TEXT_INTERACTIVE_INFO = 0x0FDF
RT_EXHYPERLINK = 0x0FD7
RT_EXHYPERLINK_ATOM = 0x0FD3
RT_CSTRING = 0x0FBA
RT_EXOBJLIST = 0x0409

OA_DGG = 0xF000
OA_BSTORE = 0xF001
OA_DG = 0xF002
OA_SPGR = 0xF003
OA_SP = 0xF004
OA_FBSE = 0xF007
OA_FSPGR = 0xF009
OA_FSP = 0xF00A
OA_FOPT = 0xF00B
OA_CLIENT_TEXTBOX = 0xF00D
OA_CHILD_ANCHOR = 0xF00F
OA_CLIENT_ANCHOR = 0xF010
OA_CLIENT_DATA = 0xF011
OA_SECONDARY_FOPT = 0xF121
OA_TERTIARY_FOPT = 0xF122

PLACEHOLDERS = {1: "title", 2: "body", 3: "ctrTitle", 4: "subTitle", 7: "dt", 8: "sldNum", 9: "ftr", 10: "hdr",
                13: "title", 14: "body", 15: "ctrTitle", 16: "subTitle", 17: "title", 18: "body", 19: "obj",
                20: "chart", 21: "tbl", 22: "clipArt", 23: "dgm", 24: "media", 25: "pic", 26: "obj"}

SHAPES = {1: "rect", 2: "roundRect", 3: "ellipse", 4: "diamond", 5: "triangle", 6: "rtTriangle", 7: "parallelogram",
          8: "trapezoid", 9: "hexagon", 10: "octagon", 11: "plus", 12: "star5", 13: "rightArrow", 15: "homePlate",
          16: "cube", 20: "line", 21: "plaque", 22: "can", 23: "donut", 32: "straightConnector1",
          33: "bentConnector2", 34: "bentConnector3", 38: "curvedConnector3", 55: "chevron", 56: "pentagon",
          57: "noSmoking", 58: "star8", 59: "star16", 60: "star24", 61: "wedgeRectCallout",
          62: "wedgeRoundRectCallout", 63: "wedgeEllipseCallout", 64: "wave", 65: "foldedCorner", 66: "leftArrow",
          67: "downArrow", 68: "upArrow", 69: "leftRightArrow", 70: "upDownArrow", 71: "irregularSeal1",
          72: "irregularSeal2", 73: "lightningBolt", 74: "heart", 75: "rect", 76: "quadArrow", 84: "bevel",
          85: "leftBracket", 86: "rightBracket", 87: "leftBrace", 88: "rightBrace", 91: "bentArrow", 92: "star24",
          93: "stripedRightArrow", 94: "notchedRightArrow", 95: "blockArc", 96: "smileyFace", 101: "uturnArrow",
          106: "cloudCallout", 109: "flowChartProcess", 110: "flowChartDecision", 111: "flowChartInputOutput",
          112: "flowChartPredefinedProcess", 114: "flowChartDocument", 116: "flowChartTerminator",
          117: "flowChartPreparation", 118: "flowChartManualInput", 119: "flowChartManualOperation",
          120: "flowChartConnector", 127: "flowChartExtract", 128: "flowChartMerge", 132: "flowChartMagneticDisk",
          135: "flowChartDelay", 176: "flowChartAlternateProcess", 177: "flowChartOffpageConnector", 183: "sun",
          184: "moon", 185: "bracketPair", 186: "bracePair", 187: "star4", 188: "doubleWave", 202: "rect"}

TRANSITIONS = {0: "cut", 1: "random", 2: "blinds", 3: "checker", 4: "cover", 5: "dissolve", 6: "fade", 7: "pull",
               8: "randomBar", 9: "wipe", 10: "wipe", 11: "zoom", 13: "split", 17: "diamond", 18: "plus",
               19: "wedge", 20: "push", 21: "comb", 22: "newsflash", 23: "fade", 26: "wheel", 27: "circle"}


class PptError(Exception):
    pass


class Rec:
    __slots__ = ("ver", "inst", "type", "data", "children", "offset")

    def __init__(self, ver, inst, type_, data, offset):
        self.ver, self.inst, self.type, self.data, self.offset = ver, inst, type_, data, offset
        self.children = None

    def kids(self) -> list:
        if self.children is None:
            self.children = parse_records(self.data, 0, len(self.data)) if self.ver == 0xF else []
        return self.children

    def find(self, type_, inst=None):
        for c in self.kids():
            if c.type == type_ and (inst is None or c.inst == inst):
                return c
        return None

    def find_all(self, type_):
        return [c for c in self.kids() if c.type == type_]

    def walk(self):
        for c in self.kids():
            yield c
            yield from c.walk()


def read_header(buf: bytes, pos: int):
    if pos + 8 > len(buf):
        return None
    vi, t, ln = struct.unpack_from("<HHI", buf, pos)
    return vi & 0xF, vi >> 4, t, ln


def parse_records(buf: bytes, start: int, end: int) -> list:
    out = []
    pos = start
    while pos + 8 <= end:
        h = read_header(buf, pos)
        if h is None:
            break
        ver, inst, t, ln = h
        body_end = min(end, pos + 8 + ln)
        out.append(Rec(ver, inst, t, buf[pos + 8:body_end], pos))
        if ln == 0 and t == 0:
            break
        pos = pos + 8 + ln
    return out


def record_at(buf: bytes, pos: int) -> Rec | None:
    h = read_header(buf, pos)
    if h is None:
        return None
    ver, inst, t, ln = h
    return Rec(ver, inst, t, buf[pos + 8:pos + 8 + ln], pos)


# ---- the file -----------------------------------------------------------------------------------
class PptReader:
    def __init__(self, path: str):
        import olefile
        try:
            ole = olefile.OleFileIO(path)
        except (OSError, Exception) as e:   # noqa: BLE001
            raise PptError("The file is not a PowerPoint presentation (or it is damaged).") from e
        try:
            if not ole.exists("PowerPoint Document"):
                if ole.exists("PP97_DUALSTORAGE") or ole.exists("PP40"):
                    raise PptError("Presentations from PowerPoint 95 and older can't be opened.")
                raise PptError("The file is not a PowerPoint presentation.")
            try:
                self.doc = ole.openstream("PowerPoint Document").read()
                self.pictures = ole.openstream("Pictures").read() if ole.exists("Pictures") else b""
                cu = ole.openstream("Current User").read() if ole.exists("Current User") else b""
            except OSError as e:
                raise PptError("The presentation is damaged.") from e
        finally:
            ole.close()
        self.current_edit = None
        if len(cu) >= 20:
            try:
                rec = record_at(cu, 0)
                if rec is not None and len(rec.data) >= 12:
                    _size, token, off = struct.unpack_from("<III", rec.data, 0)
                    if token in (0xE391C05F, 0xF3D1C4DF):
                        if token == 0xF3D1C4DF:
                            raise PptError("The presentation is protected with a password.")
                        self.current_edit = off
            except struct.error:
                pass
        self.persist: dict[int, int] = {}
        self.fonts: list[str] = []
        self.blips: list = []
        self.pres = sm.Presentation()
        self.max_id = 0
        self.links: dict[int, str] = {}

    # -- persist directory
    def load_persist(self):
        off = self.current_edit
        seen = set()
        doc_ref = None
        if off is None or off >= len(self.doc):
            off = self._find_last_user_edit()
        while off is not None and off not in seen and 0 <= off < len(self.doc):
            seen.add(off)
            rec = record_at(self.doc, off)
            if rec is None or rec.type != RT_USER_EDIT or len(rec.data) < 20:
                break
            (_last_slide, _ver, _minor, _major, off_last, off_dir, doc_persist) = struct.unpack_from(
                "<IHBBIII", rec.data, 0)
            if doc_ref is None:
                doc_ref = doc_persist
            d = record_at(self.doc, off_dir)
            if d is not None and d.type == RT_PERSIST_DIR:
                pos = 0
                while pos + 4 <= len(d.data):
                    (word,) = struct.unpack_from("<I", d.data, pos)
                    pid, count = word & 0xFFFFF, word >> 20
                    pos += 4
                    for i in range(count):
                        if pos + 4 > len(d.data):
                            break
                        (o,) = struct.unpack_from("<I", d.data, pos)
                        pos += 4
                        self.persist.setdefault(pid + i, o)      # the newest edit wins
            off = off_last if off_last else None
        return doc_ref

    def _find_last_user_edit(self):
        """No usable Current User stream: look for the last UserEditAtom in the stream."""
        pos = 0
        last = None
        while pos + 8 <= len(self.doc):
            h = read_header(self.doc, pos)
            if h is None:
                break
            ver, inst, t, ln = h
            if t == RT_USER_EDIT:
                last = pos
            pos += 8 + ln
        return last

    def persist_rec(self, ref: int) -> Rec | None:
        off = self.persist.get(ref)
        if off is None or off >= len(self.doc):
            return None
        return record_at(self.doc, off)

    # -- entry
    def read(self) -> sm.Presentation:
        doc_ref = self.load_persist()
        doc = self.persist_rec(doc_ref) if doc_ref is not None else None
        if doc is None or doc.type != RT_DOCUMENT:
            doc = next((r for r in parse_records(self.doc, 0, len(self.doc)) if r.type == RT_DOCUMENT), None)
        if doc is None:
            raise PptError("The presentation has no slides that can be read.")
        da = doc.find(RT_DOCUMENT_ATOM)
        if da is not None and len(da.data) >= 8:
            x, y = struct.unpack_from("<ii", da.data, 0)
            if x > 0 and y > 0:
                self.pres.width, self.pres.height = int(x * MASTER_UNIT), int(y * MASTER_UNIT)
        env = doc.find(RT_ENVIRONMENT)
        if env is not None:
            fc = env.find(RT_FONT_COLLECTION)
            if fc is not None:
                for fe in fc.find_all(RT_FONT_ENTITY):
                    name = fe.data[:64].decode("utf-16-le", "replace").split("\x00")[0]
                    self.fonts.append(name or "Arial")
        dg = doc.find(RT_PPDRAWING_GROUP)
        if dg is not None:
            self.load_blips(dg)
        exl = doc.find(RT_EXOBJLIST)
        if exl is not None:
            for h in exl.find_all(RT_EXHYPERLINK):
                atom = h.find(RT_EXHYPERLINK_ATOM)
                strs = h.find_all(RT_CSTRING)
                if atom is not None and len(atom.data) >= 4 and strs:
                    (hid,) = struct.unpack_from("<I", atom.data, 0)
                    url = strs[1] if len(strs) > 1 else strs[0]
                    self.links[hid] = url.data.decode("utf-16-le", "replace")
        # the slide list (with the outline text of each slide)
        slide_texts: dict[int, list] = {}
        order: list[int] = []
        master_refs: list[int] = []
        for slwt in doc.find_all(RT_SLIDE_LIST_WITH_TEXT):
            cur = None
            for r in slwt.kids():
                if r.type == RT_SLIDE_PERSIST_ATOM and len(r.data) >= 4:
                    (ref,) = struct.unpack_from("<I", r.data, 0)
                    cur = ref
                    if slwt.inst == 0:
                        order.append(ref)
                        slide_texts[ref] = []
                    elif slwt.inst == 1:
                        master_refs.append(ref)
                elif cur is not None and slwt.inst == 0 and r.type in (RT_TEXT_HEADER, RT_TEXT_CHARS, RT_TEXT_BYTES,
                                                                       RT_STYLE_TEXT_PROP):
                    slide_texts[cur].append(r)
        self.master_cache: dict[int, tuple] = {}
        masters = {}
        for ref in master_refs:
            rec = self.persist_rec(ref)
            if rec is not None and rec.type == RT_MAIN_MASTER:
                masters[ref] = self.read_master(rec)
                break
        if masters:
            self.master = next(iter(masters.values()))
        else:
            self.master = sm.new_master("office", self.pres.width, self.pres.height)
            self.master.design = ""
            self.master_schemes = None
        self.pres.masters = [self.master]
        for ref in order:
            rec = self.persist_rec(ref)
            if rec is None or rec.type != RT_SLIDE:
                continue
            try:
                self.pres.slides.append(self.read_slide(rec, self._group_texts(slide_texts.get(ref, []))))
            except Exception as e:   # noqa: BLE001
                s = sm.Slide(layout=self.master.layouts[0])
                tb = sm.Shape(kind="sp", txbox=True, x=457200, y=457200, cx=8229600, cy=914400)
                tb.text = sm.TextBody(paragraphs=[sm.Paragraph(runs=[sm.Run(f"(This slide could not be read: {e})")])])
                s.shapes.append(tb)
                self.pres.slides.append(s)
        sm.bump_ids(self.max_id)
        return self.pres

    def _group_texts(self, recs: list) -> list:
        """SlideListWithText records -> [(text type, text, style record)] in order."""
        out = []
        cur = None
        for r in recs:
            if r.type == RT_TEXT_HEADER:
                ttype = struct.unpack_from("<I", r.data, 0)[0] if len(r.data) >= 4 else 4
                cur = [ttype, "", None]
                out.append(cur)
            elif cur is not None and r.type == RT_TEXT_CHARS:
                cur[1] = r.data.decode("utf-16-le", "replace")
            elif cur is not None and r.type == RT_TEXT_BYTES:
                cur[1] = r.data.decode("latin-1")
            elif cur is not None and r.type == RT_STYLE_TEXT_PROP:
                cur[2] = r
        return out

    # -- pictures
    def load_blips(self, dg: Rec):
        dgg = dg.find(OA_DGG)
        if dgg is None:
            return
        bs = dgg.find(OA_BSTORE)
        if bs is None:
            return
        for fbse in bs.kids():
            if fbse.type != OA_FBSE or len(fbse.data) < 36:
                self.blips.append(None)
                continue
            fo = struct.unpack_from("<I", fbse.data, 28)[0]
            cb_name = fbse.data[33]
            blip = None
            if len(fbse.data) > 36 + cb_name:
                blip = record_at(fbse.data, 36 + cb_name)
            if (blip is None or blip.type < 0xF018) and self.pictures and fo < len(self.pictures):
                blip = record_at(self.pictures, fo)
            self.blips.append(self.decode_blip(blip) if blip is not None else None)

    def decode_blip(self, b: Rec):
        """(bytes, extension) of a picture record, or None."""
        t, inst, data = b.type, b.inst, b.data
        two = inst & 1 if t not in (0xF01A, 0xF01B, 0xF01C) else (inst in (0x3D5, 0x217, 0x543))
        if t in (0xF01D, 0xF02A, 0xF01E, 0xF01F, 0xF029):
            skip = 16 + (16 if (inst & 1) else 0) + 1
            raw = data[skip:]
            if t == 0xF01F:
                return _dib_to_bmp(raw), "bmp"
            ext = {0xF01D: "jpg", 0xF02A: "jpg", 0xF01E: "png", 0xF029: "tif"}[t]
            return raw, ext
        if t in (0xF01A, 0xF01B, 0xF01C):
            skip = 16 + (16 if two else 0)
            hdr = data[skip:skip + 34]
            if len(hdr) < 34:
                return None
            comp = hdr[32]
            raw = data[skip + 34:]
            if comp == 0:
                try:
                    raw = zlib.decompress(raw)
                except zlib.error:
                    return None
            ext = {0xF01A: "emf", 0xF01B: "wmf", 0xF01C: "pict"}[t]
            png = _metafile_png(raw, ext)
            if png is not None:
                return png, "png"
            return raw, ext
        return None

    def media_key(self, pib: int) -> str | None:
        if pib <= 0 or pib > len(self.blips):
            return None
        b = self.blips[pib - 1]
        if not b:
            return None
        data, ext = b
        return self.pres.add_media(data, ext)

    # -- colours
    def color(self, value: int, scheme: list) -> dict:
        r, g, b, flags = value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF, (value >> 24) & 0xFF
        if flags & 0x08 and scheme and r < len(scheme):
            return {"rgb": scheme[r]}
        if flags & 0x10:
            return {"rgb": scheme[1] if scheme else "000000"}
        return {"rgb": "%02X%02X%02X" % (r, g, b)}

    def cf_color(self, raw: bytes, scheme: list) -> dict:
        r, g, b, idx = raw[0], raw[1], raw[2], raw[3]
        if idx != 0xFE and idx < 8 and scheme:
            return {"rgb": scheme[idx]}
        return {"rgb": "%02X%02X%02X" % (r, g, b)}

    @staticmethod
    def read_scheme(rec: Rec | None) -> list | None:
        if rec is None or len(rec.data) < 32:
            return None
        out = []
        for i in range(8):
            r, g, b = rec.data[i * 4], rec.data[i * 4 + 1], rec.data[i * 4 + 2]
            out.append("%02X%02X%02X" % (r, g, b))
        return out

    # -- master
    def read_master(self, rec: Rec) -> sm.Master:
        m = sm.new_master("office", self.pres.width, self.pres.height)
        m.design = ""
        scheme = self.read_scheme(rec.find(RT_COLOR_SCHEME)) or ["FFFFFF", "000000", "808080", "000000", "BBE0E3",
                                                                   "333399", "009999", "99CC00"]
        self.master_scheme = scheme
        th = m.theme
        th.name = "Office Theme"
        th.raw_xml = None
        th.colors.update({"lt1": scheme[0], "dk1": scheme[1], "dk2": scheme[3], "lt2": scheme[4],
                          "accent1": scheme[5], "accent2": scheme[6], "accent3": scheme[7],
                          "hlink": scheme[6], "folHlink": scheme[7]})
        if self.fonts:
            th.major_font = th.minor_font = self.fonts[0]
        # text styles: TxMasterStyleAtom per text type
        styles = {}
        for tm in rec.find_all(RT_TX_MASTER_STYLE):
            try:
                styles[tm.inst] = self.parse_master_style(tm, scheme)
            except (struct.error, IndexError):
                pass
        if 0 in styles:
            m.title_style = [dict(m.title_style[i], **styles[0][min(i, len(styles[0]) - 1)]) for i in range(9)]
        if 1 in styles:
            m.body_style = [dict(m.body_style[i], **styles[1][min(i, len(styles[1]) - 1)]) for i in range(9)]
        if 4 in styles:
            m.other_style = [dict(m.other_style[i], **styles[4][min(i, len(styles[4]) - 1)]) for i in range(9)]
        self.type_styles = styles
        drawing = rec.find(RT_PPDRAWING)
        shapes, bg = self.read_drawing(drawing, scheme, master=True) if drawing is not None else ([], None)
        if bg:
            m.background = bg
        m.shapes = [s for s in shapes if s.ph is None]
        phs = [s for s in shapes if s.ph is not None]
        for s in phs:
            s.prompt = sm.PROMPTS.get(s.ph.type, "")
            if s.text is not None:
                s.text.paragraphs = [sm.Paragraph()]
        # the master's placeholder positions are the layouts' too (PowerPoint 97 has no layouts)
        by_type = {s.ph.type: s for s in phs}
        for lay in m.layouts:
            for lph in lay.placeholders:
                t = lph.ph.type
                src = by_type.get(t) or by_type.get({"ctrTitle": "title", "subTitle": "body", "obj": "body"}.get(t, t))
                if src is not None and lay.type in ("obj", "titleOnly") and t in ("title", "body"):
                    lph.x, lph.y, lph.cx, lph.cy = src.x, src.y, src.cx, src.cy
                if src is not None and t in ("dt", "ftr", "sldNum"):
                    lph.x, lph.y, lph.cx, lph.cy = src.x, src.y, src.cx, src.cy
        for mp in m.placeholders:
            src = by_type.get(mp.ph.type)
            if src is not None:
                mp.x, mp.y, mp.cx, mp.cy = src.x, src.y, src.cx, src.cy
                mp.fill, mp.line = src.fill, src.line
        return m

    def parse_master_style(self, tm: Rec, scheme) -> list:
        data = tm.data
        (levels,) = struct.unpack_from("<H", data, 0)
        pos = 2
        out = []
        for _i in range(min(levels, 5)):
            if tm.inst >= 5:
                pos += 2
            pf, pos = self.parse_pf(data, pos, scheme)
            cf, pos = self.parse_cf(data, pos, scheme)
            d = {}
            d.update(_pf_to_para(pf, fonts=self.fonts))
            d.update(_cf_to_run(cf, self.fonts))
            out.append(d)
        return out

    # -- text properties
    def parse_pf(self, data: bytes, pos: int, scheme) -> tuple[dict, int]:
        (masks,) = struct.unpack_from("<I", data, pos)
        pos += 4
        pf = {}
        if masks & 0xF:
            (flags,) = struct.unpack_from("<H", data, pos)
            pos += 2
            pf["bullet_flags"] = flags
            pf["bullet_mask"] = masks & 0xF
        if masks & 0x80:
            pf["bullet_char"] = chr(struct.unpack_from("<H", data, pos)[0])
            pos += 2
        if masks & 0x10:
            pf["bullet_font"] = struct.unpack_from("<H", data, pos)[0]
            pos += 2
        if masks & 0x40:
            pf["bullet_size"] = struct.unpack_from("<h", data, pos)[0]
            pos += 2
        if masks & 0x20:
            pf["bullet_color"] = self.cf_color(data[pos:pos + 4], scheme)
            pos += 4
        if masks & 0x800:
            pf["align"] = struct.unpack_from("<H", data, pos)[0]
            pos += 2
        if masks & 0x1000:
            pf["line"] = struct.unpack_from("<h", data, pos)[0]
            pos += 2
        if masks & 0x2000:
            pf["before"] = struct.unpack_from("<h", data, pos)[0]
            pos += 2
        if masks & 0x4000:
            pf["after"] = struct.unpack_from("<h", data, pos)[0]
            pos += 2
        if masks & 0x100:
            pf["marL"] = struct.unpack_from("<h", data, pos)[0]
            pos += 2
        if masks & 0x400:
            pf["indent"] = struct.unpack_from("<h", data, pos)[0]
            pos += 2
        if masks & 0x8000:
            pos += 2
        if masks & 0x100000:
            (count,) = struct.unpack_from("<H", data, pos)
            pos += 2 + 4 * count
        if masks & 0x10000:
            pos += 2
        if masks & 0xE0000:
            pos += 2
        if masks & 0x200000:
            pos += 2
        return pf, pos

    def parse_cf(self, data: bytes, pos: int, scheme) -> tuple[dict, int]:
        (masks,) = struct.unpack_from("<I", data, pos)
        pos += 4
        cf = {}
        if masks & 0xFFFF:
            (style,) = struct.unpack_from("<H", data, pos)
            pos += 2
            if masks & 0x1:
                cf["bold"] = bool(style & 0x1)
            if masks & 0x2:
                cf["italic"] = bool(style & 0x2)
            if masks & 0x4:
                cf["underline"] = bool(style & 0x4)
        if masks & 0x10000:
            cf["font"] = struct.unpack_from("<H", data, pos)[0]
            pos += 2
        if masks & 0x200000:
            pos += 2
        if masks & 0x400000:
            pos += 2
        if masks & 0x800000:
            pos += 2
        if masks & 0x20000:
            cf["size"] = struct.unpack_from("<H", data, pos)[0]
            pos += 2
        if masks & 0x40000:
            cf["color"] = self.cf_color(data[pos:pos + 4], scheme)
            pos += 4
        if masks & 0x80000:
            cf["position"] = struct.unpack_from("<h", data, pos)[0]
            pos += 2
        if masks & 0x100000:
            pos += 4
        if masks & 0x1000000:
            pos += 2
        if masks & 0x2000000:
            pos += 2
        if masks & 0x4000000:
            pos += 4
        return cf, pos

    def build_text(self, text: str, style: Rec | None, scheme, ttype: int) -> sm.TextBody:
        """Characters plus StyleTextPropAtom -> a text body with paragraphs and runs."""
        text = text.replace("\x00", "")
        n = len(text) + 1        # the style runs count a final paragraph mark
        pf_runs, cf_runs = [], []
        if style is not None:
            data = style.data
            pos = 0
            try:
                total = 0
                while total < n and pos + 6 <= len(data):
                    (count,) = struct.unpack_from("<I", data, pos)
                    (indent,) = struct.unpack_from("<H", data, pos + 4)
                    pos += 6
                    pf, pos = self.parse_pf(data, pos, scheme)
                    pf_runs.append((count, indent, pf))
                    total += count
                total = 0
                while total < n and pos + 8 <= len(data):
                    (count,) = struct.unpack_from("<I", data, pos)
                    pos += 4
                    cf, pos = self.parse_cf(data, pos, scheme)
                    cf_runs.append((count, cf))
                    total += count
            except struct.error:
                pass
        body = sm.TextBody()
        body.paragraphs = []
        paras = text.split("\r")
        # paragraph formats by character position
        pf_at = []
        for count, indent, pf in pf_runs:
            pf_at.append((count, indent, pf))
        cf_iter = []
        for count, cf in cf_runs:
            cf_iter.append([count, cf])
        ci = 0
        pi = 0
        pf_left = pf_at[0][0] if pf_at else 0
        pos = 0
        for ptext in paras:
            par = sm.Paragraph()
            if pf_at:
                count, indent, pf = pf_at[min(pi, len(pf_at) - 1)]
                par.level = min(4, indent)
                for k, v in _pf_to_para(pf, explicit=True, fonts=self.fonts).items():
                    setattr(par, k, v)
            # runs inside the paragraph
            i = 0
            while i < len(ptext):
                if ci < len(cf_iter):
                    left, cf = cf_iter[ci]
                else:
                    left, cf = len(ptext) - i, {}
                take = max(1, min(left, len(ptext) - i))
                piece = ptext[i:i + take].replace("\x0b", "\v")
                run = sm.Run(text=piece)
                for k, v in _cf_to_run(cf, self.fonts).items():
                    setattr(run, k, v)
                par.runs.append(run)
                i += take
                if ci < len(cf_iter):
                    cf_iter[ci][0] -= take
                    if cf_iter[ci][0] <= 0:
                        ci += 1
            # the paragraph mark
            if ci < len(cf_iter):
                cf_iter[ci][0] -= 1
                if cf_iter[ci][0] <= 0:
                    ci += 1
            pos += len(ptext) + 1
            pf_left -= len(ptext) + 1
            while pf_at and pf_left <= 0 and pi < len(pf_at) - 1:
                pi += 1
                pf_left += pf_at[pi][0]
            # merge equal runs
            merged = []
            for r in par.runs:
                if merged and _same(merged[-1], r):
                    merged[-1].text += r.text
                else:
                    merged.append(r)
            par.runs = merged
            body.paragraphs.append(par)
        if not body.paragraphs:
            body.paragraphs = [sm.Paragraph()]
        return body

    # -- drawings
    def read_drawing(self, drawing: Rec, scheme, master=False, texts=None) -> tuple[list, dict | None]:
        dg = drawing.find(OA_DG)
        if dg is None:
            return [], None
        bg = None
        for c in dg.kids():
            if c.type == OA_SP:
                fsp = c.find(OA_FSP)
                if fsp is not None and len(fsp.data) >= 8 and struct.unpack_from("<I", fsp.data, 4)[0] & 0x400:
                    props = self.props(c)
                    bg = self.fill_from(props, scheme, default_filled=True)
        spgr = dg.find(OA_SPGR)
        shapes = []
        if spgr is not None:
            ctx = {"texts": texts or [], "text_i": 0, "scheme": scheme, "master": master}
            shapes = self.read_group_children(spgr, ctx)
        return shapes, bg

    def props(self, sp: Rec) -> dict:
        out = {}
        for t in (OA_FOPT, OA_SECONDARY_FOPT, OA_TERTIARY_FOPT):
            rec = sp.find(t)
            if rec is None:
                continue
            n = rec.inst
            data = rec.data
            complex_pos = 6 * n
            for i in range(n):
                if 6 * i + 6 > len(data):
                    break
                opid, op = struct.unpack_from("<Hi", data, 6 * i)
                pid = opid & 0x3FFF
                if opid & 0x8000:
                    out[pid] = data[complex_pos:complex_pos + max(0, op)]
                    complex_pos += max(0, op)
                else:
                    out[pid] = op
        return out

    def read_group_children(self, spgr: Rec, ctx) -> list:
        out = []
        first = True
        for c in spgr.kids():
            if c.type == OA_SP:
                if first:
                    first = False
                    continue          # the group's own shape
                s = self.read_shape(c, ctx)
                if s is not None:
                    out.append(s)
            elif c.type == OA_SPGR:
                g = self.read_group(c, ctx)
                if g is not None:
                    out.append(g)
                first = False
        return out

    def read_group(self, spgr: Rec, ctx) -> sm.Shape | None:
        head = spgr.find(OA_SP)
        if head is None:
            return None
        g = sm.Shape(kind="group")
        fspgr = head.find(OA_FSPGR)
        if fspgr is not None and len(fspgr.data) >= 16:
            l, t, r, b = struct.unpack_from("<iiii", fspgr.data, 0)
            g.child_rect = (int(l * MASTER_UNIT), int(t * MASTER_UNIT), int(max(1, r - l) * MASTER_UNIT),
                            int(max(1, b - t) * MASTER_UNIT))
        self.place(g, head)
        g.children = self.read_group_children(spgr, dict(ctx, in_group=True))
        if g.child_rect is not None:
            # children are in the group's own coordinates: keep them as such (EMU-like numbers)
            pass
        return g if g.children else None

    def place(self, s: sm.Shape, sp: Rec):
        anchor = sp.find(OA_CLIENT_ANCHOR)
        child = sp.find(OA_CHILD_ANCHOR)
        if anchor is not None:
            if len(anchor.data) >= 16:
                top, left, right, bottom = struct.unpack_from("<iiii", anchor.data, 0)
            elif len(anchor.data) >= 8:
                top, left, right, bottom = struct.unpack_from("<hhhh", anchor.data, 0)
            else:
                return
            s.x, s.y = int(left * MASTER_UNIT), int(top * MASTER_UNIT)
            s.cx, s.cy = int(max(0, right - left) * MASTER_UNIT), int(max(0, bottom - top) * MASTER_UNIT)
            if s.kind == "group" and s.child_rect is not None:
                pass
        elif child is not None and len(child.data) >= 16:
            left, top, right, bottom = struct.unpack_from("<iiii", child.data, 0)
            s.x, s.y = int(left * MASTER_UNIT), int(top * MASTER_UNIT)
            s.cx, s.cy = int(max(0, right - left) * MASTER_UNIT), int(max(0, bottom - top) * MASTER_UNIT)
        fsp = sp.find(OA_FSP)
        if fsp is not None and len(fsp.data) >= 8:
            sid, flags = struct.unpack_from("<II", fsp.data, 0)
            s.id = sid if sid else s.id
            self.max_id = max(self.max_id, s.id)
            s.flip_h = bool(flags & 0x40)
            s.flip_v = bool(flags & 0x80)
        props = self.props(sp)
        rot = props.get(0x0004)
        if isinstance(rot, int) and rot:
            s.rot = (rot / 65536.0) % 360
            # 45..135 and 225..315: the anchor is stored turned by 90 degrees
            if 45 <= s.rot < 135 or 225 <= s.rot < 315:
                cxp, cyp = s.x + s.cx / 2, s.y + s.cy / 2
                s.cx, s.cy = s.cy, s.cx
                s.x, s.y = int(cxp - s.cx / 2), int(cyp - s.cy / 2)

    def fill_from(self, props: dict, scheme, default_filled=True) -> dict | None:
        bools = props.get(0x01BF)
        filled = default_filled
        if isinstance(bools, int):
            if bools & (1 << 20):            # fUseFilled
                filled = bool(bools & (1 << 4))
        if not filled:
            return None
        ftype = props.get(0x0180, 0)
        color = self.color(props[0x0181], scheme) if isinstance(props.get(0x0181), int) else {"rgb": "FFFFFF"}
        opacity = props.get(0x0182)
        if isinstance(opacity, int) and opacity < 65536:
            color = dict(color, mods=[["alpha", int(opacity / 65536 * 100000)]])
        if ftype in (4, 5, 6, 7):
            back = self.color(props[0x0183], scheme) if isinstance(props.get(0x0183), int) else {"rgb": "FFFFFF"}
            ang = props.get(0x018B, 0)
            ang = (ang / 65536.0) if isinstance(ang, int) else 0
            focus = props.get(0x018C, 0)
            stops = [[0, color], [100000, back]]
            if isinstance(focus, int) and focus in (100, -100):
                stops = [[0, back], [100000, color]]
            elif isinstance(focus, int) and focus == 50:
                stops = [[0, color], [50000, back], [100000, color]]
            return {"type": "grad", "stops": stops, "angle": (90 - ang) % 360,
                    "path": "circle" if ftype in (5, 6) else None}
        if ftype in (2, 3):
            key = self.media_key(props.get(0x0186, 0)) if isinstance(props.get(0x0186), int) else None
            if key:
                return {"type": "pic", "image": key, "tile": ftype == 2}
        if ftype == 1:
            back = self.color(props[0x0183], scheme) if isinstance(props.get(0x0183), int) else {"rgb": "FFFFFF"}
            return {"type": "pattern", "fg": color, "bg": back, "prst": "pct50"}
        return {"type": "solid", "color": color}

    def line_from(self, props: dict, scheme, default_line=True) -> dict | None:
        bools = props.get(0x01FF)
        on = default_line
        if isinstance(bools, int) and bools & (1 << 19):
            on = bool(bools & (1 << 3))
        if not on:
            return None
        color = self.color(props[0x01C0], scheme) if isinstance(props.get(0x01C0), int) else {"rgb": "000000"}
        width = props.get(0x01CB, 9525)
        line = {"color": color, "width": width if isinstance(width, int) and width > 0 else 9525}
        dash = props.get(0x01CE)
        if isinstance(dash, int) and dash:
            line["dash"] = {1: "dash", 2: "sysDot", 3: "dashDot", 4: "lgDashDotDot", 5: "dot", 6: "dash",
                            7: "lgDash", 8: "dashDot", 9: "lgDashDot", 10: "lgDashDotDot"}.get(dash, "dash")
        for pid, key in ((0x01D0, "head"), (0x01D1, "tail")):
            v = props.get(pid)
            if isinstance(v, int) and v:
                line[key] = {1: "triangle", 2: "stealth", 3: "diamond", 4: "oval", 5: "arrow"}.get(v, "triangle")
        return line

    def read_shape(self, sp: Rec, ctx) -> sm.Shape | None:
        fsp = sp.find(OA_FSP)
        if fsp is None or len(fsp.data) < 8:
            return None
        _sid, flags = struct.unpack_from("<II", fsp.data, 0)
        if flags & 0x8 or flags & 0x400:       # deleted / background
            return None
        spt = fsp.inst
        props = self.props(sp)
        scheme = ctx["scheme"]
        s = sm.Shape(kind="sp")
        self.place(s, sp)
        # placeholder?
        cd = sp.find(OA_CLIENT_DATA)
        ph_type = None
        if cd is not None:
            pa = cd.find(RT_PLACEHOLDER)
            if pa is not None and len(pa.data) >= 6:
                ph_type = pa.data[4]
            ii = cd.find(RT_INTERACTIVE_INFO)
            if ii is not None:
                atom = ii.find(RT_INTERACTIVE_INFO_ATOM)
                if atom is not None and len(atom.data) >= 12:
                    hid = struct.unpack_from("<I", atom.data, 8)[0]
                    if hid in self.links:
                        s.link = self.links[hid]
        pib = props.get(0x0104)
        if isinstance(pib, int) and pib > 0 and (spt == 75 or ph_type in (25, 19, 22) or spt in (1, 202)):
            s.kind = "pic"
            s.image = self.media_key(pib)
            crops = [props.get(k, 0) for k in (0x0102, 0x0100, 0x0103, 0x0101)]   # l t r b
            s.crop = tuple(int((c if isinstance(c, int) else 0) / 65536 * 100000) for c in crops)
            s.line = self.line_from(props, scheme, default_line=False)
            if ph_type is not None and ph_type in PLACEHOLDERS:
                s.ph = sm.Placeholder(PLACEHOLDERS[ph_type], 0)
            return s
        if spt == 0 and 0x0145 in props:
            s.path = _freeform(props)
            s.geom = "rect"
        else:
            s.geom = SHAPES.get(spt, "rect")
        if spt in (20, 32, 33, 34, 38) or s.geom in ("line", "straightConnector1"):
            s.geom = "line" if spt == 20 else s.geom
            s.fill = None
            s.line = self.line_from(props, scheme, default_line=True)
        elif ph_type is not None:
            s.fill = self.fill_from(props, scheme, default_filled=False)
            s.line = self.line_from(props, scheme, default_line=False)
        elif spt == 202:
            s.txbox = True
            s.fill = self.fill_from(props, scheme, default_filled=False)
            s.line = self.line_from(props, scheme, default_line=False)
        else:
            s.fill = self.fill_from(props, scheme, default_filled=True)
            s.line = self.line_from(props, scheme, default_line=True)
        if ph_type is not None and ph_type in PLACEHOLDERS:
            s.ph = sm.Placeholder(PLACEHOLDERS[ph_type], {"dt": 10, "ftr": 11, "sldNum": 12}.get(PLACEHOLDERS[ph_type], 0))
            if s.ph.type in ("body", "obj") and ph_type in (14, 19, 26):
                s.ph.idx = 1
        # text
        tb = sp.find(OA_CLIENT_TEXTBOX)
        text_info = None
        if tb is not None:
            ttype, text, style = 4, None, None
            for r in tb.kids():
                if r.type == RT_TEXT_HEADER and len(r.data) >= 4:
                    ttype = struct.unpack_from("<I", r.data, 0)[0]
                elif r.type == RT_TEXT_CHARS:
                    text = r.data.decode("utf-16-le", "replace")
                elif r.type == RT_TEXT_BYTES:
                    text = r.data.decode("latin-1")
                elif r.type == RT_STYLE_TEXT_PROP:
                    style = r
                elif r.type == RT_OUTLINE_TEXT_REF and len(r.data) >= 4:
                    idx = struct.unpack_from("<I", r.data, 0)[0]
                    if 0 <= idx < len(ctx["texts"]):
                        ttype, text, style = ctx["texts"][idx]
            if text is not None:
                text_info = (ttype, text, style)
        if text_info is not None:
            ttype, text, style = text_info
            s.text = self.build_text(text, style, scheme, ttype)
            if ctx.get("master"):
                pass
        elif s.ph is not None:
            s.text = sm.TextBody()
        if s.text is not None:
            ins = [props.get(k) for k in (0x0081, 0x0082, 0x0083, 0x0084)]
            dflt = (91440, 45720, 91440, 45720)
            s.text.insets = tuple(v if isinstance(v, int) else d for v, d in zip(ins, dflt))
            anchor = props.get(0x0087, 0)
            if isinstance(anchor, int):
                s.text.anchor = {0: "t", 1: "ctr", 2: "b", 3: "t", 4: "ctr", 5: "b"}.get(anchor, "t")
                s.text.anchor_ctr = anchor in (3, 4, 5)
            wrap = props.get(0x0085, 0)
            s.text.wrap = wrap != 2
            fit = props.get(0x00BF)
            if isinstance(fit, int) and fit & 0x2 and s.ph is None:
                s.text.autofit = "shape"
            if s.ph is None and ph_type is None:
                # text in an ordinary shape: the "other" text style (18 pt, left)
                if spt not in (202,) and s.fill is not None:
                    for par in s.text.paragraphs:
                        if par.align is None:
                            par.align = "ctr"
                    if anchor == 0 and 0x0087 not in props:
                        s.text.anchor = "ctr"
            if s.ph is not None and s.ph.type in ("title", "ctrTitle") and 0x0087 not in props:
                s.text.anchor = "ctr" if s.ph.type == "title" else "ctr"
        return s

    # -- slides
    def read_slide(self, rec: Rec, texts: list) -> sm.Slide:
        atom = rec.find(RT_SLIDE_ATOM)
        layout_type, master_ref, notes_ref, sflags = 0, 0, 0, 0x7
        if atom is not None and len(atom.data) >= 24:
            layout_type = struct.unpack_from("<I", atom.data, 0)[0]
            master_ref, notes_ref = struct.unpack_from("<II", atom.data, 12)
            sflags = struct.unpack_from("<H", atom.data, 20)[0]
        scheme = self.master_scheme if getattr(self, "master_scheme", None) else None
        if not sflags & 0x2:
            own = self.read_scheme(rec.find(RT_COLOR_SCHEME))
            if own:
                scheme = own
        scheme = scheme or ["FFFFFF", "000000", "808080", "000000", "BBE0E3", "333399", "009999", "99CC00"]
        drawing = rec.find(RT_PPDRAWING)
        shapes, bg = self.read_drawing(drawing, scheme, texts=texts) if drawing is not None else ([], None)
        types = {s.ph.type for s in shapes if s.ph is not None}
        layout = self._layout_for(layout_type, types)
        s = sm.Slide(layout=layout)
        s.shapes = shapes
        if not sflags & 0x4 and bg is not None:
            s.background = bg
        if not sflags & 0x1:
            s.hide_master_shapes = True
        info = rec.find(RT_SSSLIDE_INFO)
        if info is not None and len(info.data) >= 13:
            slide_time, _snd, direction, effect, flags, speed = struct.unpack_from("<iIBBHB", info.data, 0)
            t = s.transition
            t.type = TRANSITIONS.get(effect, "fade") if (effect or direction) else "none"
            if effect == 0 and direction == 0:
                t.type = "none"
            if effect == 6 and direction == 1:
                t.through_black = True
            if t.type in ("cover", "pull", "push", "wipe"):
                t.dir = {0: "l", 1: "u", 2: "r", 3: "d", 4: "lu", 5: "ru", 6: "ld", 7: "rd"}.get(direction, "l")
                if t.type == "wipe":
                    t.dir = {0: "r", 1: "d", 2: "l", 3: "u"}.get(direction, "r")
            elif t.type == "split":
                t.dir = {0: "horz-out", 1: "horz-in", 2: "vert-out", 3: "vert-in"}.get(direction, "horz-out")
            elif t.type in ("blinds", "randomBar", "checker", "comb"):
                t.dir = "vert" if direction else "horz"
            t.speed = {0: "slow", 1: "med", 2: "fast"}.get(speed, "fast")
            t.on_click = not (flags & 0x400) or bool(flags & 0x1) or True
            if flags & 0x400:
                t.after_ms = max(0, slide_time)
            s.hidden = bool(flags & 0x4)
        # placeholder defaults per text type ("half"/"quarter" body sizes, centred titles...)
        for sh in s.shapes:
            if sh.ph is not None and sh.ph.type in ("ctrTitle", "subTitle") and sh.text is not None:
                st5 = self.type_styles.get(6 if sh.ph.type == "ctrTitle" else 5) if hasattr(self, "type_styles") else None
                if st5:
                    sh.level_styles = [st5[min(i, len(st5) - 1)] for i in range(5)]
        # notes
        if notes_ref:
            n = self.persist_rec(notes_ref)
            if n is not None and n.type == RT_NOTES:
                d = n.find(RT_PPDRAWING)
                if d is not None:
                    try:
                        nshapes, _bg = self.read_drawing(d, scheme)
                        for ns in nshapes:
                            if ns.ph is not None and ns.ph.type == "body" and ns.text is not None:
                                s.notes = ns.text.plain().replace("\v", "\n").strip()
                    except (struct.error, IndexError):
                        pass
        return s

    def _layout_for(self, geom: int, types: set) -> sm.Layout:
        m = self.master
        name = {0: "title", 1: "obj", 2: "obj", 7: "titleOnly", 8: "twoObj", 9: "twoObj", 14: "twoObj",
                16: "blank", 17: "blank"}.get(geom)
        if "ctrTitle" in types or "subTitle" in types:
            name = "title"
        elif name is None:
            name = "obj" if "body" in types or "obj" in types else ("titleOnly" if "title" in types else "blank")
        return m.layout(name) or m.layouts[0]


def _pf_to_para(pf: dict, explicit: bool = False, fonts: list | None = None) -> dict:
    d = {}
    if "align" in pf:
        d["align"] = {0: "l", 1: "ctr", 2: "r", 3: "just", 4: "dist"}.get(pf["align"], "l")
    if "marL" in pf:
        d["marL"] = int(pf["marL"] * MASTER_UNIT)
    if "indent" in pf:
        # PowerPoint 97: indent = where the first line (and the bullet) starts, marL = the text
        d["indent"] = int((pf["indent"] - pf.get("marL", 0)) * MASTER_UNIT) if "marL" in pf else None
        if d["indent"] is None:
            d.pop("indent")
    if "line" in pf:
        v = pf["line"]
        d["line_spacing"] = float(v) if v >= 0 else -(-v / 8.0)
    for key, src in (("space_before", "before"), ("space_after", "after")):
        if src in pf:
            v = pf[src]
            d[key] = -float(v) if v >= 0 else (-v / 8.0)
    if "bullet_flags" in pf:
        flags, mask = pf["bullet_flags"], pf["bullet_mask"]
        if mask & 0x1:
            if flags & 0x1:
                b = {"char": pf.get("bullet_char", "•")}
                if "bullet_color" in pf and flags & 0x4:
                    b["color"] = pf["bullet_color"]
                if "bullet_size" in pf and flags & 0x8 and pf["bullet_size"] > 0:
                    b["size"] = float(pf["bullet_size"])
                if "bullet_font" in pf and flags & 0x2 and fonts and 0 <= pf["bullet_font"] < len(fonts):
                    b["font"] = fonts[pf["bullet_font"]]
                d["bullet"] = b
            else:
                d["bullet"] = {"none": True}
    elif "bullet_char" in pf and not explicit:
        d["bullet"] = {"char": pf["bullet_char"]}
    return d


def _cf_to_run(cf: dict, fonts: list) -> dict:
    d = {}
    for k in ("bold", "italic", "underline"):
        if k in cf:
            d[k] = cf[k]
    if "size" in cf and cf["size"]:
        d["size"] = float(cf["size"])
    if "color" in cf:
        d["color"] = cf["color"]
    if "font" in cf and 0 <= cf["font"] < len(fonts):
        d["font"] = fonts[cf["font"]]
    if cf.get("position"):
        d["baseline"] = int(cf["position"])
    return d


def _same(a: sm.Run, b: sm.Run) -> bool:
    return all(getattr(a, k) == getattr(b, k) for k in ("font", "size", "bold", "italic", "underline", "strike",
                                                         "color", "baseline", "link"))


def _freeform(props: dict) -> list | None:
    verts = props.get(0x0145)
    segs = props.get(0x0146)
    if not isinstance(verts, (bytes, bytearray)) or len(verts) < 6:
        return None
    n, _alloc, cb = struct.unpack_from("<HHH", verts, 0)
    pts = []
    pos = 6
    for _i in range(n):
        if cb == 4 and pos + 4 <= len(verts):
            x, y = struct.unpack_from("<hh", verts, pos)
        elif pos + 8 <= len(verts):
            x, y = struct.unpack_from("<ii", verts, pos)
        else:
            break
        pts.append((x, y))
        pos += cb if cb in (4, 8) else 8
    if not pts:
        return None
    w = props.get(0x0142, 21600)
    h = props.get(0x0143, 21600)
    left = props.get(0x0140, 0)
    top = props.get(0x0141, 0)
    w = (w if isinstance(w, int) else 21600) - (left if isinstance(left, int) else 0)
    h = (h if isinstance(h, int) else 21600) - (top if isinstance(top, int) else 0)
    cmds = []
    pi = 0
    if isinstance(segs, (bytes, bytearray)) and len(segs) >= 6:
        ns, _a, cbs = struct.unpack_from("<HHH", segs, 0)
        pos = 6
        for _i in range(ns):
            if pos + 2 > len(segs):
                break
            (seg,) = struct.unpack_from("<H", segs, pos)
            pos += max(2, cbs)
            kind, count = seg >> 13, seg & 0x1FFF
            if kind == 0:          # lines
                for _k in range(max(1, count)):
                    if pi < len(pts):
                        cmds.append(("L", *pts[pi]))
                        pi += 1
            elif kind == 1:        # curves
                for _k in range(max(1, count)):
                    if pi + 2 < len(pts):
                        cmds.append(("C", *pts[pi], *pts[pi + 1], *pts[pi + 2]))
                        pi += 3
            elif kind == 2:        # move to
                if pi < len(pts):
                    cmds.append(("M", *pts[pi]))
                    pi += 1
            elif kind == 3:
                cmds.append(("Z",))
            elif kind == 4:
                break
    else:
        cmds.append(("M", *pts[0]))
        for p in pts[1:]:
            cmds.append(("L", *p))
    if cmds and cmds[0][0] != "M":
        cmds.insert(0, ("M", *pts[0]))
    return [(max(1, w), max(1, h), [(c[0], *[v - (left if j % 2 == 0 else top) for j, v in enumerate(c[1:])])
                                    for c in cmds], True)]


def _dib_to_bmp(dib: bytes) -> bytes:
    if len(dib) < 40:
        return dib
    header_size = struct.unpack_from("<I", dib, 0)[0]
    bit_count = struct.unpack_from("<H", dib, 14)[0]
    colors = struct.unpack_from("<I", dib, 32)[0] if header_size >= 36 else 0
    if bit_count <= 8 and colors == 0:
        colors = 1 << bit_count
    offset = 14 + header_size + colors * 4
    return b"BM" + struct.pack("<IHHI", 14 + len(dib), 0, 0, offset) + dib


def _metafile_png(raw: bytes, ext: str) -> bytes | None:
    """Old clip art is WMF/EMF: let Pillow (or ImageMagick) turn it into a picture if it can."""
    import io
    try:
        from PIL import Image
        with Image.open(io.BytesIO(raw)) as im:
            im.load()
            out = io.BytesIO()
            im.save(out, "PNG")
            return out.getvalue()
    except Exception:   # noqa: BLE001
        pass
    import shutil
    import subprocess
    import tempfile
    tool = shutil.which("magick") or shutil.which("convert")
    if not tool or ext not in ("wmf", "emf"):
        return None
    try:
        with tempfile.TemporaryDirectory() as d:
            src = f"{d}/in.{ext}"
            with open(src, "wb") as f:
                f.write(raw)
            r = subprocess.run([tool, "-density", "150", src, f"{d}/out.png"], capture_output=True, timeout=20)
            if r.returncode == 0:
                with open(f"{d}/out.png", "rb") as f:
                    return f.read()
    except (OSError, subprocess.SubprocessError):
        return None
    return None


def read_ppt(path: str) -> sm.Presentation:
    return PptReader(path).read()
