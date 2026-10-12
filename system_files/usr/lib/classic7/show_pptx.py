"""Show: PowerPoint 2007+ files (.pptx, .ppsx, .potx, .pptm) to and from the presentation model."""
from __future__ import annotations

import copy
import posixpath
import re
import uuid
import zipfile
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from lxml import etree

import show_model as sm

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
    "dgm": "http://schemas.openxmlformats.org/drawingml/2006/diagram",
    "dsp": "http://schemas.microsoft.com/office/drawing/2008/diagram",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
    "ct": "http://schemas.openxmlformats.org/package/2006/content-types",
    "p14": "http://schemas.microsoft.com/office/powerpoint/2010/main",
}
A = "{%s}" % NS["a"]
P = "{%s}" % NS["p"]
R = "{%s}" % NS["r"]
REL_BASE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
MISSING = object()

PRESET_COLORS = {"black": "000000", "white": "FFFFFF", "red": "FF0000", "green": "008000", "blue": "0000FF",
                 "yellow": "FFFF00", "gray": "808080", "grey": "808080", "silver": "C0C0C0", "navy": "000080",
                 "maroon": "800000", "purple": "800080", "teal": "008080", "olive": "808000", "lime": "00FF00",
                 "aqua": "00FFFF", "cyan": "00FFFF", "fuchsia": "FF00FF", "magenta": "FF00FF", "orange": "FFA500",
                 "darkBlue": "00008B", "darkRed": "8B0000", "darkGreen": "006400", "ltGray": "D3D3D3",
                 "dkGray": "A9A9A9", "lightGray": "D3D3D3", "darkGray": "A9A9A9"}


class PptxError(Exception):
    pass


# ==== reading =====================================================================================
def _scan_local_headers(path: str) -> dict[str, bytes]:
    """Read a zip file without its central directory (damaged or cut-off files): walk the local
    file headers one after another."""
    import struct
    import zlib
    with open(path, "rb") as f:
        data = f.read()
    out = {}
    pos = data.find(b"PK\x03\x04")
    while 0 <= pos < len(data) - 30:
        (_sig, _ver, flags, method, _t, _d, _crc, csize, _usize, nlen, xlen) = struct.unpack(
            "<IHHHHHIIIHH", data[pos:pos + 30])
        name = data[pos + 30:pos + 30 + nlen].decode("utf-8", "replace")
        start = pos + 30 + nlen + xlen
        nxt = data.find(b"PK\x03\x04", start + (csize if not flags & 8 else 0))
        end = start + csize if (csize and not flags & 8) else (nxt if nxt > 0 else len(data))
        raw = data[start:end]
        try:
            content = zlib.decompressobj(-15).decompress(raw) if method == 8 else raw
            out[name] = content
        except zlib.error:
            pass
        pos = nxt
    return out


class _Package:
    def __init__(self, path: str):
        self.zip = None
        self.loose: dict[str, bytes] = {}
        try:
            self.zip = zipfile.ZipFile(path)
            self.names = set(self.zip.namelist())
        except (zipfile.BadZipFile, OSError) as e:
            try:
                self.loose = _scan_local_headers(path)
            except OSError:
                self.loose = {}
            if "[Content_Types].xml" not in self.loose:
                raise PptxError("The file is not a PowerPoint 2007 presentation (or it is damaged).") from e
            self.names = set(self.loose)

    def read(self, name: str) -> bytes | None:
        name = name.lstrip("/")
        if name not in self.names:
            return None
        if self.zip is None:
            return self.loose.get(name)
        try:
            return self.zip.read(name)
        except (zipfile.BadZipFile, OSError, EOFError, ValueError):
            return None

    def xml(self, name: str):
        data = self.read(name)
        if data is None:
            return None
        parser = etree.XMLParser(resolve_entities=False, huge_tree=True, remove_blank_text=False, recover=True,
                                 no_network=True)
        try:
            return etree.fromstring(data, parser)
        except etree.XMLSyntaxError:
            return None

    def rels(self, part: str) -> dict:
        d, b = posixpath.split(part.lstrip("/"))
        root = self.xml(posixpath.join(d, "_rels", b + ".rels"))
        out = {}
        if root is None:
            return out
        for rel in root.findall("{%s}Relationship" % NS["pr"]):
            target = rel.get("Target", "")
            if rel.get("TargetMode") == "External":
                full = target
            else:
                full = posixpath.normpath(posixpath.join(d, target)) if not target.startswith("/") else target[1:]
            out[rel.get("Id")] = (rel.get("Type", "").rsplit("/", 1)[-1], full, rel.get("TargetMode") == "External")
        return out


def _int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _bool(v, default=None):
    if v is None:
        return default
    return v in ("1", "true", "on")


def _choose(el):
    """mc:AlternateContent: the Fallback (plain DrawingML) or the first Choice."""
    fb = el.find("mc:Fallback", NS)
    if fb is not None and len(fb):
        return list(fb)
    ch = el.find("mc:Choice", NS)
    return list(ch) if ch is not None else []


def parse_color(el) -> dict | None:
    """The colour inside el (a:solidFill, a:fgClr, ...): the first colour child with its transforms."""
    if el is None:
        return None
    for c in el:
        tag = etree.QName(c).localname
        col = None
        if tag == "srgbClr":
            col = {"rgb": (c.get("val") or "000000").upper()}
        elif tag == "schemeClr":
            col = {"scheme": c.get("val", "tx1")}
        elif tag == "sysClr":
            col = {"rgb": (c.get("lastClr") or ("FFFFFF" if c.get("val") == "window" else "000000")).upper()}
        elif tag == "prstClr":
            col = {"rgb": PRESET_COLORS.get(c.get("val"), "000000")}
        elif tag == "scrgbClr":
            def f(k):
                return max(0, min(255, round(_int(c.get(k)) / 100000 * 255)))
            col = {"rgb": "%02X%02X%02X" % (f("r"), f("g"), f("b"))}
        elif tag == "hslClr":
            import colorsys
            r_, g_, b_ = colorsys.hls_to_rgb(_int(c.get("hue")) / 21600000, _int(c.get("lum")) / 100000,
                                            _int(c.get("sat")) / 100000)
            col = {"rgb": "%02X%02X%02X" % (round(r_ * 255), round(g_ * 255), round(b_ * 255))}
        if col is not None:
            mods = [[etree.QName(m).localname, _int(m.get("val"))] for m in c
                    if etree.QName(m).localname in ("lumMod", "lumOff", "tint", "shade", "alpha", "alphaMod",
                                                    "satMod")]
            if mods:
                col["mods"] = mods
            return col
    return None


def _with_ph(color: dict | None, ph: dict | None) -> dict | None:
    """Replace the theme's placeholder colour (phClr) by a real one, keeping the transforms."""
    if color is None:
        return None
    if color.get("scheme") == "phClr":
        base = copy.deepcopy(ph) if ph else {"scheme": "accent1"}
        mods = list(base.get("mods", [])) + list(color.get("mods", []))
        if mods:
            base["mods"] = mods
        return base
    return color


def subst_fill(fill, ph):
    if not fill:
        return fill
    f = copy.deepcopy(fill)
    if f.get("type") == "solid":
        f["color"] = _with_ph(f.get("color"), ph)
    elif f.get("type") == "grad":
        f["stops"] = [[pos, _with_ph(c, ph)] for pos, c in f.get("stops", [])]
    elif f.get("type") == "pattern":
        f["fg"] = _with_ph(f.get("fg"), ph)
        f["bg"] = _with_ph(f.get("bg"), ph)
    return f


class Reader:
    def __init__(self, path: str):
        self.pkg = _Package(path)
        self.pres = sm.Presentation()
        self.max_id = 0
        self.media_map: dict[str, str] = {}

    # -- entry
    def read(self) -> sm.Presentation:
        rels = self.pkg.rels("")
        main = next((t for _id, (kind, t, ext) in rels.items() if kind == "officeDocument"), "ppt/presentation.xml")
        root = self.pkg.xml(main)
        if root is None:
            raise PptxError("The file has no presentation in it.")
        prels = self.pkg.rels(main)
        sz = root.find("p:sldSz", NS)
        if sz is not None:
            self.pres.width, self.pres.height = _int(sz.get("cx"), 9144000), _int(sz.get("cy"), 6858000)
        masters = {}
        for mid in root.findall("p:sldMasterIdLst/p:sldMasterId", NS):
            rid = mid.get(R + "id")
            if rid in prels:
                part = prels[rid][1]
                m = self.read_master(part)
                masters[part] = m
                self.pres.masters.append(m)
        if not self.pres.masters:
            self.pres.masters.append(sm.new_master("office", self.pres.width, self.pres.height))
        self.layout_by_part = {}
        for part, m in masters.items():
            for lay_part, lay in getattr(m, "_layout_parts", {}).items():
                self.layout_by_part[lay_part] = lay
        for sid in root.findall("p:sldIdLst/p:sldId", NS):
            rid = sid.get(R + "id")
            if rid in prels:
                try:
                    self.pres.slides.append(self.read_slide(prels[rid][1]))
                except Exception as e:   # noqa: BLE001 (one broken slide must not lose the rest)
                    s = sm.Slide(layout=self.pres.master.layouts[0] if self.pres.master.layouts else None)
                    tb = sm.Shape(kind="sp", txbox=True, x=457200, y=457200, cx=8229600, cy=914400)
                    tb.text = sm.TextBody(paragraphs=[sm.Paragraph(runs=[sm.Run(f"(This slide could not be read: {e})")])])
                    s.shapes.append(tb)
                    self.pres.slides.append(s)
        core = self.pkg.xml("docProps/core.xml")
        if core is not None:
            for el in core:
                tag = etree.QName(el).localname
                if tag == "title":
                    self.pres.title = el.text or ""
                elif tag == "creator":
                    self.pres.author = el.text or ""
        ppr = self.pkg.xml(posixpath.join(posixpath.dirname(main), "presProps.xml"))
        if ppr is not None:
            show = ppr.find("p:showPr", NS)
            if show is not None and _bool(show.get("loop")):
                self.pres.show_loop = True
        for m in self.pres.masters:
            for k in ("_layout_parts",):
                if hasattr(m, k):
                    delattr(m, k)
        sm.bump_ids(self.max_id)
        return self.pres

    # -- media
    def media(self, part: str, rid: str | None) -> str | None:
        if not rid:
            return None
        rels = self.pkg.rels(part)
        if rid not in rels or rels[rid][2]:
            return None
        target = rels[rid][1]
        if target in self.media_map:
            return self.media_map[target]
        data = self.pkg.read(target)
        if data is None:
            return None
        key = self.pres.add_media(data, posixpath.splitext(target)[1])
        self.media_map[target] = key
        return key

    # -- theme
    def read_theme(self, part: str) -> sm.Theme:
        root = self.pkg.xml(part)
        th = sm.Theme()
        if root is None:
            return th
        th.name = root.get("name", "Office Theme")
        th.raw_xml = self.pkg.read(part)
        cs = root.find("a:themeElements/a:clrScheme", NS)
        if cs is not None:
            th.colors_name = cs.get("name", "Office")
            for key in sm.SCHEME_KEYS:
                el = cs.find("a:" + key, NS)
                c = parse_color(el)
                if c and "rgb" in c:
                    th.colors[key] = c["rgb"]
        fs = root.find("a:themeElements/a:fontScheme", NS)
        if fs is not None:
            th.fonts_name = fs.get("name", "Office")
            mj = fs.find("a:majorFont/a:latin", NS)
            mn = fs.find("a:minorFont/a:latin", NS)
            if mj is not None and mj.get("typeface"):
                th.major_font = mj.get("typeface")
            if mn is not None and mn.get("typeface"):
                th.minor_font = mn.get("typeface")
        fmt = root.find("a:themeElements/a:fmtScheme", NS)
        if fmt is not None:
            th.fill_styles = [self.parse_fill_el(el, part) for el in fmt.findall("a:fillStyleLst/*", NS)]
            th.line_styles = [self.parse_line(el, part) for el in fmt.findall("a:lnStyleLst/a:ln", NS)]
            th.bg_fill_styles = [self.parse_fill_el(el, part) for el in fmt.findall("a:bgFillStyleLst/*", NS)]
        return th

    # -- fills and lines
    def parse_fill_el(self, el, part):
        tag = etree.QName(el).localname
        if tag == "noFill":
            return None
        if tag == "solidFill":
            return {"type": "solid", "color": parse_color(el) or {"rgb": "000000"}}
        if tag == "gradFill":
            stops = []
            for gs in el.findall("a:gsLst/a:gs", NS):
                c = parse_color(gs)
                if c:
                    stops.append([_int(gs.get("pos")), c])
            lin = el.find("a:lin", NS)
            path = el.find("a:path", NS)
            return {"type": "grad", "stops": stops, "angle": _int(lin.get("ang")) / 60000.0 if lin is not None else 90.0,
                    "path": path.get("path") if path is not None else None}
        if tag == "blipFill":
            blip = el.find("a:blip", NS)
            key = self.media(part, blip.get(R + "embed")) if blip is not None else None
            return {"type": "pic", "image": key, "tile": el.find("a:tile", NS) is not None} if key else None
        if tag == "pattFill":
            return {"type": "pattern", "fg": parse_color(el.find("a:fgClr", NS)) or {"rgb": "000000"},
                    "bg": parse_color(el.find("a:bgClr", NS)) or {"rgb": "FFFFFF"}, "prst": el.get("prst")}
        if tag == "grpFill":
            return {"type": "group"}
        return MISSING

    def find_fill(self, parent, part):
        if parent is None:
            return MISSING
        for el in parent:
            tag = etree.QName(el).localname
            if tag in ("noFill", "solidFill", "gradFill", "blipFill", "pattFill", "grpFill"):
                return self.parse_fill_el(el, part)
        return MISSING

    def parse_line(self, ln, part):
        if ln is None:
            return MISSING
        f = self.find_fill(ln, part)
        if f is None:
            return None
        line = {"width": _int(ln.get("w"), 9525) if ln.get("w") else None}
        if f is not MISSING and f:
            line["color"] = f.get("color") if f.get("type") == "solid" else \
                (f["stops"][0][1] if f.get("type") == "grad" and f.get("stops") else {"rgb": "000000"})
        dash = ln.find("a:prstDash", NS)
        if dash is not None:
            line["dash"] = dash.get("val", "solid")
        if ln.get("cap"):
            line["cap"] = ln.get("cap")
        for end in ("headEnd", "tailEnd"):
            e = ln.find("a:" + end, NS)
            if e is not None and e.get("type") not in (None, "none"):
                k = "head" if end == "headEnd" else "tail"
                line[k] = e.get("type")
                line[k + "_size"] = e.get("w", "med")
        if ln.find("a:round", NS) is not None:
            line["join"] = "round"
        elif ln.find("a:bevel", NS) is not None:
            line["join"] = "bevel"
        elif ln.find("a:miter", NS) is not None:
            line["join"] = "miter"
        return line

    # -- text
    def parse_rpr(self, rpr, part) -> dict:
        d = {}
        if rpr is None:
            return d
        if rpr.get("sz"):
            d["size"] = _int(rpr.get("sz")) / 100.0
        for k, attr in (("bold", "b"), ("italic", "i")):
            if rpr.get(attr) is not None:
                d[k] = _bool(rpr.get(attr), False)
        if rpr.get("u") is not None:
            d["underline"] = rpr.get("u") != "none"
        if rpr.get("strike") is not None:
            d["strike"] = rpr.get("strike") != "noStrike"
        if rpr.get("baseline"):
            d["baseline"] = round(_int(rpr.get("baseline")) / 1000)
        if rpr.get("cap") and rpr.get("cap") != "none":
            d["caps"] = rpr.get("cap")
        latin = rpr.find("a:latin", NS)
        if latin is not None and latin.get("typeface"):
            d["font"] = latin.get("typeface")
        fill = rpr.find("a:solidFill", NS)
        if fill is not None:
            c = parse_color(fill)
            if c:
                d["color"] = c
        else:
            grad = rpr.find("a:gradFill", NS)
            if grad is not None:
                f = self.parse_fill_el(grad, part)
                if f and f.get("stops"):
                    d["color"] = f["stops"][0][1]
        link = rpr.find("a:hlinkClick", NS)
        if link is not None and link.get(R + "id"):
            rels = self.pkg.rels(part)
            target = rels.get(link.get(R + "id"))
            if target and target[2]:
                d["link"] = target[1]
        return d

    def parse_ppr(self, ppr, part) -> dict:
        d = {}
        if ppr is None:
            return d
        if ppr.get("algn"):
            d["align"] = ppr.get("algn")
        if ppr.get("marL") is not None:
            d["marL"] = _int(ppr.get("marL"))
        if ppr.get("indent") is not None:
            d["indent"] = _int(ppr.get("indent"))

        def spacing(el):
            if el is None:
                return None
            pct = el.find("a:spcPct", NS)
            pts = el.find("a:spcPts", NS)
            if pct is not None:
                return pct, _int(pct.get("val")) / 1000.0
            if pts is not None:
                return pts, _int(pts.get("val")) / 100.0
            return None
        ln = spacing(ppr.find("a:lnSpc", NS))
        if ln:
            d["line_spacing"] = ln[1] if etree.QName(ln[0]).localname == "spcPct" else -ln[1]
        for key, tag in (("space_before", "spcBef"), ("space_after", "spcAft")):
            sp = spacing(ppr.find("a:" + tag, NS))
            if sp:
                d[key] = -sp[1] if etree.QName(sp[0]).localname == "spcPct" else sp[1]
        b = None
        if ppr.find("a:buNone", NS) is not None:
            b = {"none": True}
        else:
            ch = ppr.find("a:buChar", NS)
            au = ppr.find("a:buAutoNum", NS)
            if ch is not None:
                b = {"char": ch.get("char", "•")}
            elif au is not None:
                b = {"auto": au.get("type", "arabicPeriod"), "start": _int(au.get("startAt"), 1)}
            if b is not None:
                bf = ppr.find("a:buFont", NS)
                if bf is not None and bf.get("typeface"):
                    b["font"] = bf.get("typeface")
                bc = ppr.find("a:buClr", NS)
                if bc is not None:
                    c = parse_color(bc)
                    if c:
                        b["color"] = c
                bs = ppr.find("a:buSzPct", NS)
                if bs is not None:
                    b["size"] = _int(bs.get("val"), 100000) / 1000.0
        if b is not None:
            d["bullet"] = b
        defr = self.parse_rpr(ppr.find("a:defRPr", NS), part)
        d.update(defr)
        return d

    def parse_lst_style(self, lst, part) -> list | None:
        if lst is None or not len(lst):
            return None
        out = [None] * 9
        for i in range(9):
            el = lst.find(f"a:lvl{i + 1}pPr", NS)
            if el is not None:
                out[i] = self.parse_ppr(el, part)
        return out if any(out) else None

    def parse_body(self, tx, part) -> sm.TextBody:
        body = sm.TextBody()
        bp = tx.find("a:bodyPr", NS)
        self.apply_body_pr(body, bp, set_defaults=True)
        body.paragraphs = []
        for p_el in tx.findall("a:p", NS):
            par = sm.Paragraph()
            ppr = p_el.find("a:pPr", NS)
            if ppr is not None:
                par.level = _int(ppr.get("lvl"), 0)
                pd = self.parse_ppr(ppr, part)
                for k in ("align", "marL", "indent", "bullet", "space_before", "space_after", "line_spacing"):
                    if k in pd:
                        setattr(par, k, pd[k])
            for el in p_el:
                tag = etree.QName(el).localname
                if tag in ("r", "fld"):
                    t = el.find("a:t", NS)
                    run = sm.Run(text=t.text or "" if t is not None else "")
                    for k, v in self.parse_rpr(el.find("a:rPr", NS), part).items():
                        setattr(run, k, v)
                    if tag == "fld":
                        ftype = el.get("type", "")
                        run.field = "slidenum" if ftype == "slidenum" else ("datetime" if ftype.startswith("datetime") else None)
                    par.runs.append(run)
                elif tag == "br":
                    run = sm.Run(text="\v")
                    for k, v in self.parse_rpr(el.find("a:rPr", NS), part).items():
                        setattr(run, k, v)
                    par.runs.append(run)
            end = p_el.find("a:endParaRPr", NS)
            if end is not None and end.get("sz"):
                par.end_size = _int(end.get("sz")) / 100.0
            body.paragraphs.append(par)
        if not body.paragraphs:
            body.paragraphs = [sm.Paragraph()]
        return body

    def apply_body_pr(self, body: sm.TextBody, bp, set_defaults=False):
        if bp is None:
            return
        if bp.get("anchor"):
            body.anchor = bp.get("anchor")
        if bp.get("anchorCtr") is not None:
            body.anchor_ctr = _bool(bp.get("anchorCtr"), False)
        ins = list(body.insets)
        for i, k in enumerate(("lIns", "tIns", "rIns", "bIns")):
            if bp.get(k) is not None:
                ins[i] = _int(bp.get(k))
        body.insets = tuple(ins)
        if bp.get("wrap"):
            body.wrap = bp.get("wrap") != "none"
        if bp.get("vert"):
            body.vert = bp.get("vert")
        if bp.get("numCol"):
            body.columns = _int(bp.get("numCol"), 1)
        if bp.find("a:normAutofit", NS) is not None:
            na = bp.find("a:normAutofit", NS)
            body.autofit = "norm"
            body.font_scale = _int(na.get("fontScale"), 100000) / 100000.0
            body.line_reduction = _int(na.get("lnSpcReduction"), 0) / 100000.0
        elif bp.find("a:spAutoFit", NS) is not None:
            body.autofit = "shape"
        elif bp.find("a:noAutofit", NS) is not None:
            body.autofit = "none"

    # -- shapes
    def parse_xfrm(self, s: sm.Shape, xfrm) -> bool:
        if xfrm is None:
            return False
        off = xfrm.find("a:off", NS)
        ext = xfrm.find("a:ext", NS)
        if off is not None:
            s.x, s.y = _int(off.get("x")), _int(off.get("y"))
        if ext is not None:
            s.cx, s.cy = _int(ext.get("cx")), _int(ext.get("cy"))
        s.rot = _int(xfrm.get("rot")) / 60000.0
        s.flip_h = _bool(xfrm.get("flipH"), False)
        s.flip_v = _bool(xfrm.get("flipV"), False)
        return off is not None and ext is not None

    def parse_geometry(self, s: sm.Shape, sppr):
        pg = sppr.find("a:prstGeom", NS) if sppr is not None else None
        if pg is not None:
            s.geom = pg.get("prst", "rect")
            for gd in pg.findall("a:avLst/a:gd", NS):
                m = re.match(r"val\s+(-?\d+)", gd.get("fmla", ""))
                if m:
                    s.adj[gd.get("name")] = int(m.group(1))
            return
        cg = sppr.find("a:custGeom", NS) if sppr is not None else None
        if cg is not None:
            paths = []
            for path in cg.findall("a:pathLst/a:path", NS):
                cmds = []
                for c in path:
                    tag = etree.QName(c).localname
                    pts = [(_int(pt.get("x")), _int(pt.get("y"))) for pt in c.findall("a:pt", NS)]
                    if tag == "moveTo" and pts:
                        cmds.append(("M", *pts[0]))
                    elif tag == "lnTo" and pts:
                        cmds.append(("L", *pts[0]))
                    elif tag == "cubicBezTo" and len(pts) == 3:
                        cmds.append(("C", *pts[0], *pts[1], *pts[2]))
                    elif tag == "quadBezTo" and len(pts) == 2:
                        cmds.append(("Q", *pts[0], *pts[1]))
                    elif tag == "arcTo":
                        cmds.append(("A", _int(c.get("wR")), _int(c.get("hR")), _int(c.get("stAng")),
                                     _int(c.get("swAng"))))
                    elif tag == "close":
                        cmds.append(("Z",))
                paths.append((_int(path.get("w")), _int(path.get("h")), cmds, path.get("fill") != "none"))
            s.path = paths or None

    def apply_style_refs(self, s: sm.Shape, style_el, theme: sm.Theme, fill, line):
        """p:style: theme fill/line by index plus a colour; text colour from fontRef."""
        if style_el is None:
            return fill, line
        fr = style_el.find("a:fillRef", NS)
        lr = style_el.find("a:lnRef", NS)
        fo = style_el.find("a:fontRef", NS)
        if fill is MISSING and fr is not None:
            idx = _int(fr.get("idx"))
            ph = parse_color(fr)
            if idx == 0:
                fill = None
            elif 1 <= idx <= len(theme.fill_styles):
                fill = subst_fill(theme.fill_styles[idx - 1], ph)
            elif idx >= 1001 and idx - 1001 < len(theme.bg_fill_styles):
                fill = subst_fill(theme.bg_fill_styles[idx - 1001], ph)
            else:
                fill = {"type": "solid", "color": ph or sm.scheme("accent1")}
        if lr is not None:
            idx = _int(lr.get("idx"))
            ph = parse_color(lr)
            base = None
            if 1 <= idx <= len(theme.line_styles) and theme.line_styles[idx - 1] not in (None, MISSING):
                base = copy.deepcopy(theme.line_styles[idx - 1])
                base["color"] = _with_ph(base.get("color", {"scheme": "phClr"}), ph)
            elif idx >= 1:
                base = {"color": ph or sm.scheme("accent1", ("shade", 50000)), "width": 9525 * idx * 2}
            if line is MISSING:
                line = base
            elif line and base:
                merged = dict(base)
                merged.update({k: v for k, v in line.items() if v is not None})
                line = merged
        elif line not in (MISSING, None) and line.get("color") is None:
            line["color"] = sm.scheme("tx1")
        if fo is not None:
            c = parse_color(fo)
            if c:
                s.style_text_color = c
        return fill, line

    def parse_shape(self, el, part, theme: sm.Theme, ctx: dict) -> sm.Shape | None:
        tag = etree.QName(el).localname
        if tag == "AlternateContent":
            for c in _choose(el):
                sh = self.parse_shape(c, part, theme, ctx)
                if sh is not None:
                    return sh
            return None
        s = sm.Shape()
        nv = el.find("*/p:cNvPr", NS)
        if nv is None:
            nv = el.find("*/dsp:cNvPr", NS)
        if nv is not None:
            s.id = _int(nv.get("id"), s.id)
            s.name = nv.get("name", "")
            link = nv.find("a:hlinkClick", NS)
            if link is not None and link.get(R + "id"):
                tgt = self.pkg.rels(part).get(link.get(R + "id"))
                if tgt and tgt[2]:
                    s.link = tgt[1]
        self.max_id = max(self.max_id, s.id)
        ph_el = el.find("*/p:nvPr/p:ph", NS)
        if ph_el is not None:
            s.ph = sm.Placeholder(ph_el.get("type", "obj" if ph_el.get("idx") else "body"), _int(ph_el.get("idx"), 0),
                                  ph_el.get("orient", ""), ph_el.get("sz", ""))
            if ph_el.get("type") is None:
                s.ph.type = "obj"
        if tag in ("sp", "cxnSp"):
            s.kind = "sp"
            cnv = el.find("p:nvSpPr/p:cNvSpPr", NS)
            if cnv is not None and _bool(cnv.get("txBox")):
                s.txbox = True
            sppr = el.find("p:spPr", NS)
            if sppr is None:
                sppr = el.find("dsp:spPr", NS)
            has_xfrm = self.parse_xfrm(s, sppr.find("a:xfrm", NS) if sppr is not None else None)
            self.parse_geometry(s, sppr)
            fill = self.find_fill(sppr, part)
            line = self.parse_line(sppr.find("a:ln", NS) if sppr is not None else None, part)
            style_el = el.find("p:style", NS)
            if style_el is None:
                style_el = el.find("dsp:style", NS)
            fill, line = self.apply_style_refs(s, style_el, theme, fill, line)
            tx = el.find("p:txBody", NS)
            if tx is None:
                tx = el.find("dsp:txBody", NS)
            if tx is not None:
                s.text = self.parse_body(tx, part)
                s.level_styles = self.parse_lst_style(tx.find("a:lstStyle", NS), part)
                s._body_pr_set = self._body_attrs(tx.find("a:bodyPr", NS))
            if s.ph is not None:
                self.inherit_placeholder(s, has_xfrm, fill, line, ctx)
            else:
                s.fill = None if fill is MISSING else fill
                s.line = None if line is MISSING else line
            if tag == "cxnSp" and not s.geom:
                s.geom = "line"
            if s.fill and s.fill.get("type") == "group":
                s.fill = copy.deepcopy(ctx.get("group_fill"))
            return s
        if tag == "pic":
            s.kind = "pic"
            sppr = el.find("p:spPr", NS)
            has_xfrm = self.parse_xfrm(s, sppr.find("a:xfrm", NS) if sppr is not None else None)
            self.parse_geometry(s, sppr)
            bf = el.find("p:blipFill", NS)
            if bf is not None:
                blip = bf.find("a:blip", NS)
                if blip is not None:
                    s.image = self.media(part, blip.get(R + "embed"))
                src = bf.find("a:srcRect", NS)
                if src is not None:
                    s.crop = tuple(_int(src.get(k)) for k in ("l", "t", "r", "b"))
            line = self.parse_line(sppr.find("a:ln", NS) if sppr is not None else None, part)
            fill, line = self.apply_style_refs(s, el.find("p:style", NS), theme, MISSING, line)
            s.line = None if line is MISSING else line
            if s.ph is not None and not has_xfrm:
                self.inherit_placeholder(s, False, MISSING, MISSING, ctx)
            return s
        if tag == "grpSp":
            s.kind = "group"
            gp = el.find("p:grpSpPr", NS)
            xfrm = gp.find("a:xfrm", NS) if gp is not None else None
            self.parse_xfrm(s, xfrm)
            if xfrm is not None:
                choff = xfrm.find("a:chOff", NS)
                chext = xfrm.find("a:chExt", NS)
                if choff is not None and chext is not None:
                    s.child_rect = (_int(choff.get("x")), _int(choff.get("y")), _int(chext.get("cx")),
                                    _int(chext.get("cy")))
            gfill = self.find_fill(gp, part)
            sub_ctx = dict(ctx, group_fill=None if gfill is MISSING else gfill)
            for c in el:
                if etree.QName(c).localname in ("sp", "pic", "grpSp", "graphicFrame", "cxnSp", "AlternateContent"):
                    ch = self.parse_shape(c, part, theme, sub_ctx)
                    if ch is not None:
                        s.children.append(ch)
            return s
        if tag == "graphicFrame":
            xfrm = el.find("p:xfrm", NS)
            has_xfrm = self.parse_xfrm(s, xfrm)
            gd = el.find("a:graphic/a:graphicData", NS)
            uri = gd.get("uri", "") if gd is not None else ""
            tbl = gd.find("a:tbl", NS) if gd is not None else None
            if tbl is not None:
                s.kind = "table"
                s.table = self.parse_table(tbl, part)
                return s
            if gd is not None and uri.endswith("/diagram"):
                g = self.parse_diagram(gd, part, theme, ctx, s)
                if g is not None:
                    return g
            s.kind = "chart" if uri.endswith("/chart") else "other"
            s.raw = etree.tostring(el)
            s.raw_parts = self.collect_parts(el, part)
            if s.kind == "chart":
                try:
                    import show_chart
                    tree = next((t for t in s.raw_parts.values() if t.get("kind") == "chart"), None)
                    if tree and tree.get("data"):
                        s.chart = show_chart.parse(tree["data"])
                except Exception:   # noqa: BLE001
                    s.chart = None
            if s.ph is not None and not has_xfrm:
                self.inherit_placeholder(s, False, MISSING, MISSING, ctx)
            return s
        if tag == "contentPart":
            return None
        return None

    def collect_parts(self, el, part) -> dict:
        """The parts an element points to (charts with their data), to write them back unchanged."""
        out = {}
        rels = self.pkg.rels(part)
        for node in el.iter():
            for k, v in node.attrib.items():
                if k.startswith(R) and v in rels and not rels[v][2]:
                    out[v] = self._part_tree(rels[v][1], rels[v][0])
        return out

    def _part_tree(self, name, kind, depth=0):
        data = self.pkg.read(name)
        sub = {}
        if depth < 3:
            for rid, (k, target, ext) in self.pkg.rels(name).items():
                if ext:
                    sub[rid] = {"external": target, "kind": k}
                else:
                    sub[rid] = self._part_tree(target, k, depth + 1)
        return {"name": name, "kind": kind, "data": data, "rels": sub, "ctype": self.content_type(name)}

    def content_type(self, name):
        if not hasattr(self, "_ct"):
            self._ct = {"defaults": {}, "overrides": {}}
            root = self.pkg.xml("[Content_Types].xml")
            if root is not None:
                for d in root.findall("ct:Default", NS):
                    self._ct["defaults"][d.get("Extension", "").lower()] = d.get("ContentType")
                for o in root.findall("ct:Override", NS):
                    self._ct["overrides"][o.get("PartName", "").lstrip("/")] = o.get("ContentType")
        return self._ct["overrides"].get(name) or self._ct["defaults"].get(posixpath.splitext(name)[1][1:].lower(),
                                                                          "application/octet-stream")

    def parse_diagram(self, gd, part, theme, ctx, frame: sm.Shape):
        """SmartArt: PowerPoint stores a drawn copy (dsp:drawing); show it as a group of shapes."""
        rels = self.pkg.rels(part)
        rel_ids = gd.find("dgm:relIds", NS)
        if rel_ids is None:
            return None
        dm = rels.get(rel_ids.get(R + "dm"))
        drawing_part = None
        if dm:
            for rid, (kind, target, ext) in self.pkg.rels(dm[1]).items():
                if kind == "diagramDrawing":
                    drawing_part = target
        if drawing_part is None:
            for rid, (kind, target, ext) in rels.items():
                if kind == "diagramDrawing":
                    drawing_part = target
        root = self.pkg.xml(drawing_part) if drawing_part else None
        if root is None:
            return None
        tree = root.find("dsp:spTree", NS)
        if tree is None:
            return None
        g = sm.Shape(kind="group", id=frame.id, name=frame.name or "Diagram", x=frame.x, y=frame.y, cx=frame.cx,
                     cy=frame.cy)
        g.child_rect = (0, 0, frame.cx, frame.cy)
        for c in tree:
            if etree.QName(c).localname in ("sp", "grpSp", "pic"):
                ch = self.parse_dsp_shape(c, drawing_part, theme, ctx)
                if ch is not None:
                    g.children.append(ch)
        return g if g.children else None

    def parse_dsp_shape(self, el, part, theme, ctx):
        # dsp shapes look like p shapes in another namespace: rename and reuse
        clone = copy.deepcopy(el)
        for node in clone.iter():
            q = etree.QName(node)
            if q.namespace == NS["dsp"]:
                node.tag = "{%s}%s" % (NS["p"], q.localname)
        for node in clone.iter():
            if etree.QName(node).localname == "nvSpPr":
                pass
        s = self.parse_shape(clone, part, theme, ctx)
        if s is not None and s.text is None:
            tx = clone.find("p:txBody", NS)
            if tx is not None:
                s.text = self.parse_body(tx, part)
        if s is not None:
            txx = clone.find("p:txXfrm", NS)
            if txx is not None and s.text is not None:
                pass
        return s

    def parse_table(self, tbl, part) -> sm.Table:
        t = sm.Table()
        pr = tbl.find("a:tblPr", NS)
        if pr is not None:
            t.first_row = _bool(pr.get("firstRow"), False)
            t.band_rows = _bool(pr.get("bandRow"), False)
            t.first_col = _bool(pr.get("firstCol"), False)
            t.last_row = _bool(pr.get("lastRow"), False)
            t.last_col = _bool(pr.get("lastCol"), False)
            t.band_cols = _bool(pr.get("bandCol"), False)
            sid = pr.find("a:tableStyleId", NS)
            import show_render
            t.style = show_render.TABLE_STYLES.get((sid.text or "").strip(), "medium2-accent1") if sid is not None \
                else "medium2-accent1"
            if pr.find("a:solidFill", NS) is not None or pr.find("a:noFill", NS) is not None:
                t.style = "none" if sid is None else t.style
        t.col_widths = [_int(gc.get("w")) for gc in tbl.findall("a:tblGrid/a:gridCol", NS)]
        for tr in tbl.findall("a:tr", NS):
            t.row_heights.append(_int(tr.get("h"), 370840))
            row = []
            for tc in tr.findall("a:tc", NS):
                cell = sm.TableCell()
                cell.span = _int(tc.get("gridSpan"), 1)
                cell.row_span = _int(tc.get("rowSpan"), 1)
                cell.merged = _bool(tc.get("hMerge"), False) or _bool(tc.get("vMerge"), False)
                tx = tc.find("a:txBody", NS)
                if tx is not None:
                    cell.text = self.parse_body(tx, part)
                tcpr = tc.find("a:tcPr", NS)
                if tcpr is not None:
                    f = self.find_fill(tcpr, part)
                    if f is not MISSING:
                        cell.fill = f
                    cell.anchor = tcpr.get("anchor", "t")
                    cell.margins = tuple(_int(tcpr.get(k), d) for k, d in
                                         (("marL", 91440), ("marT", 45720), ("marR", 91440), ("marB", 45720)))
                    for side, tagn in (("l", "lnL"), ("r", "lnR"), ("t", "lnT"), ("b", "lnB")):
                        ln = tcpr.find("a:" + tagn, NS)
                        if ln is not None:
                            parsed = self.parse_line(ln, part)
                            if parsed is not MISSING and parsed and parsed.get("color"):
                                cell.borders[side] = parsed
                row.append(cell)
            t.rows.append(row)
        return t

    def _body_attrs(self, bp) -> set:
        if bp is None:
            return set()
        out = set(bp.attrib.keys())
        for c in bp:
            out.add(etree.QName(c).localname)
        return out

    def inherit_placeholder(self, s: sm.Shape, has_xfrm, fill, line, ctx):
        """A placeholder takes what it doesn't set itself from the layout (then the master)."""
        src = None
        layout, master = ctx.get("layout"), ctx.get("master")
        if master is not None:
            src = sm.find_layout_placeholder(layout, master, s.ph)
        if not has_xfrm:
            if src is not None:
                s.x, s.y, s.cx, s.cy = src.x, src.y, src.cx, src.cy
                s.inherit = True
        s.fill = (copy.deepcopy(src.fill) if src is not None else None) if fill is MISSING else fill
        s.line = (copy.deepcopy(src.line) if src is not None else None) if line is MISSING else line
        if s.kind == "sp" and s.geom == "rect" and src is not None and src.geom != "rect":
            s.geom = src.geom
        if src is not None:
            s.prompt = src.prompt or sm.PROMPTS.get(s.ph.type, "")
            if s.style_text_color is None:
                s.style_text_color = src.style_text_color
            if s.text is not None and src.text is not None:
                own = getattr(s, "_body_pr_set", set())
                for attr, key in (("anchor", "anchor"), ("anchor_ctr", "anchorCtr"), ("wrap", "wrap"),
                                  ("vert", "vert")):
                    if key not in own:
                        setattr(s.text, attr, getattr(src.text, attr))
                if not own & {"lIns", "tIns", "rIns", "bIns"}:
                    s.text.insets = src.text.insets
                if not own & {"normAutofit", "spAutoFit", "noAutofit"}:
                    s.text.autofit = src.text.autofit
            elif s.text is None and src.text is not None and s.kind == "sp":
                s.text = sm.TextBody(anchor=src.text.anchor, insets=src.text.insets, autofit=src.text.autofit,
                                     wrap=src.text.wrap, vert=src.text.vert)
        else:
            s.prompt = sm.PROMPTS.get(s.ph.type, "")
        if hasattr(s, "_body_pr_set"):
            del s._body_pr_set

    def read_tree(self, tree, part, theme, ctx) -> list:
        out = []
        if tree is None:
            return out
        for el in tree:
            if etree.QName(el).localname in ("sp", "pic", "grpSp", "graphicFrame", "cxnSp", "AlternateContent"):
                try:
                    s = self.parse_shape(el, part, theme, ctx)
                except Exception:   # noqa: BLE001 (skip a shape we can't read)
                    s = None
                if s is not None:
                    out.append(s)
        return out

    def read_background(self, csld, part, theme):
        bg = csld.find("p:bg", NS) if csld is not None else None
        if bg is None:
            return None
        bgpr = bg.find("p:bgPr", NS)
        if bgpr is not None:
            f = self.find_fill(bgpr, part)
            return None if f is MISSING else f
        ref = bg.find("p:bgRef", NS)
        if ref is not None:
            idx = _int(ref.get("idx"))
            ph = parse_color(ref)
            if idx >= 1001 and idx - 1001 < len(theme.bg_fill_styles):
                return subst_fill(theme.bg_fill_styles[idx - 1001], ph)
            if 1 <= idx <= len(theme.fill_styles):
                return subst_fill(theme.fill_styles[idx - 1], ph)
            return {"type": "solid", "color": ph or sm.scheme("bg1")}
        return None

    # -- masters, layouts, slides
    def read_master(self, part) -> sm.Master:
        root = self.pkg.xml(part)
        if root is None:
            m = sm.new_master("office", self.pres.width, self.pres.height)
            m._layout_parts = {}
            return m
        rels = self.pkg.rels(part)
        m = sm.Master()
        m.design = ""
        theme_part = next((t for _i, (k, t, e) in rels.items() if k == "theme"), None)
        m.theme = self.read_theme(theme_part) if theme_part else sm.Theme()
        cm = root.find("p:clrMap", NS)
        if cm is not None:
            m.color_map = {k: v for k, v in cm.attrib.items()}
        csld = root.find("p:cSld", NS)
        m.background = self.read_background(csld, part, m.theme) or {"type": "solid", "color": sm.scheme("bg1")}
        tx = root.find("p:txStyles", NS)
        m.title_style = sm.office_title_style()
        m.body_style = sm.office_body_style()
        m.other_style = sm.office_other_style()
        if tx is not None:
            for attr, tag in (("title_style", "p:titleStyle"), ("body_style", "p:bodyStyle"),
                              ("other_style", "p:otherStyle")):
                lst = self.parse_lst_style(tx.find(tag, NS), part)
                if lst:
                    base = getattr(m, attr)
                    merged = []
                    for i in range(9):
                        d = dict(base[i]) if i < len(base) else {}
                        if lst[i]:
                            d.update(lst[i])
                        merged.append(d)
                    setattr(m, attr, merged)
        ctx = {"master": m, "layout": None}
        shapes = self.read_tree(csld.find("p:spTree", NS) if csld is not None else None, part, m.theme, ctx)
        m.placeholders = [s for s in shapes if s.ph is not None]
        m.shapes = [s for s in shapes if s.ph is None]
        for s in m.placeholders:
            s.prompt = sm.PROMPTS.get(s.ph.type, "")
        m._layout_parts = {}
        for lid in root.findall("p:sldLayoutIdLst/p:sldLayoutId", NS):
            rid = lid.get(R + "id")
            if rid in rels:
                lay = self.read_layout(rels[rid][1], m)
                m.layouts.append(lay)
                m._layout_parts[rels[rid][1]] = lay
        if not m.layouts:
            m.layouts = sm._scaled_layouts(self.pres.width, self.pres.height)
        return m

    def read_layout(self, part, m: sm.Master) -> sm.Layout:
        root = self.pkg.xml(part)
        lay = sm.Layout()
        if root is None:
            return lay
        lay.type = root.get("type", "cust")
        lay.show_master_shapes = _bool(root.get("showMasterSp"), True)
        csld = root.find("p:cSld", NS)
        lay.name = csld.get("name", lay.type) if csld is not None else lay.type
        lay.background = self.read_background(csld, part, m.theme)
        ctx = {"master": m, "layout": None}
        shapes = self.read_tree(csld.find("p:spTree", NS) if csld is not None else None, part, m.theme, ctx)
        lay.placeholders = [s for s in shapes if s.ph is not None]
        lay.shapes = [s for s in shapes if s.ph is None]
        for s in lay.placeholders:
            txt = s.text.plain().strip().split("\n")[0] if s.text else ""
            if txt and not txt.startswith("Click to edit Master") and s.ph.type not in ("dt", "ftr", "sldNum"):
                s.prompt = txt
            else:
                s.prompt = sm.PROMPTS.get(s.ph.type, "Click to add text")
            # the layout's sample text isn't content
            if s.text is not None:
                s.text.paragraphs = [sm.Paragraph(level=p.level, align=p.align) for p in s.text.paragraphs[:1]] or \
                    [sm.Paragraph()]
        return lay

    def read_slide(self, part) -> sm.Slide:
        root = self.pkg.xml(part)
        rels = self.pkg.rels(part)
        layout_part = next((t for _i, (k, t, e) in rels.items() if k == "slideLayout"), None)
        layout = self.layout_by_part.get(layout_part) if layout_part else None
        if layout is None and self.pres.masters and self.pres.master.layouts:
            layout = self.pres.master.layouts[0]
        master = next((m for m in self.pres.masters if layout in m.layouts), self.pres.master)
        s = sm.Slide(layout=layout)
        s.hidden = root.get("show") == "0"
        s.hide_master_shapes = root.get("showMasterSp") == "0"
        csld = root.find("p:cSld", NS)
        s.name = csld.get("name", "") if csld is not None else ""
        s.background = self.read_background(csld, part, master.theme)
        ctx = {"master": master, "layout": layout}
        s.shapes = self.read_tree(csld.find("p:spTree", NS) if csld is not None else None, part, master.theme, ctx)
        tr = root.find("p:transition", NS)
        if tr is None:
            for ac in root.findall("mc:AlternateContent", NS):
                for c in _choose(ac):
                    if etree.QName(c).localname == "transition":
                        tr = c
        if tr is not None:
            s.transition = self.parse_transition(tr)
        timing = root.find("p:timing", NS)
        if timing is not None:
            s.raw_timing = etree.tostring(timing)
            self.read_animations(s, timing)
        notes_part = next((t for _i, (k, t, e) in rels.items() if k == "notesSlide"), None)
        if notes_part:
            nroot = self.pkg.xml(notes_part)
            if nroot is not None:
                texts = []
                for sp in nroot.iter(P + "sp"):
                    ph = sp.find("p:nvSpPr/p:nvPr/p:ph", NS)
                    if ph is not None and ph.get("type") == "body":
                        for p_el in sp.findall("p:txBody/a:p", NS):
                            texts.append("".join((t.text or "") for t in p_el.iter(A + "t")))
                s.notes = "\n".join(texts).strip("\n")
        return s

    def read_animations(self, slide: sm.Slide, timing):
        """Entrance effects (the ones Show can play) onto the shapes, in their click order."""
        by_id = {sh.id: sh for sh in sm.walk(slide.shapes)}
        order = 0
        for ctn in timing.iter(P + "cTn"):
            if ctn.get("presetClass") != "entr":
                continue
            tgt = ctn.find(".//p:spTgt", NS)
            if tgt is None:
                continue
            sh = by_id.get(_int(tgt.get("spid")))
            if sh is None or sh.anim:
                continue
            order += 1
            pid = _int(ctn.get("presetID"))
            effect = {1: "appear", 10: "fade", 22: "wipe", 2: "fly", 53: "zoom", 23: "zoom", 21: "wipe",
                      16: "wipe", 3: "wipe", 4: "zoom", 9: "fade"}.get(pid, "fade")
            node = ctn.get("nodeType", "clickEffect")
            trig = {"clickEffect": "click", "withEffect": "with", "afterEffect": "after"}.get(node, "click")
            sh.anim = {"effect": effect, "trigger": trig, "order": order}
        slide.raw_anim_sig = anim_signature(slide)

    def parse_transition(self, tr) -> sm.Transition:
        t = sm.Transition()
        t.speed = tr.get("spd", "fast")
        if tr.get("dur"):
            d = _int(tr.get("dur"))
            t.speed = "slow" if d >= 1000 else ("med" if d >= 700 else "fast")
        t.on_click = tr.get("advClick", "1") not in ("0", "false")
        if tr.get("advTm"):
            t.after_ms = _int(tr.get("advTm"))
        for c in tr:
            name = etree.QName(c).localname
            if name in ("sndAc", "extLst"):
                continue
            t.type = name
            t.dir = c.get("dir", "") or c.get("orient", "")
            if name == "split":
                t.dir = (c.get("orient", "horz"), c.get("dir", "out"))
                t.dir = f"{t.dir[0]}-{t.dir[1]}"
            if name == "fade":
                t.through_black = _bool(c.get("thruBlk"), False)
            break
        return t


def anim_signature(slide: sm.Slide):
    return tuple(sorted((sh.id, (sh.anim or {}).get("effect"), (sh.anim or {}).get("trigger"),
                         (sh.anim or {}).get("order")) for sh in sm.walk(slide.shapes) if sh.anim))


def read_pptx(path: str) -> sm.Presentation:
    return Reader(path).read()


# ==== writing =====================================================================================
CT = {
    "pres": "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
    "show": "application/vnd.openxmlformats-officedocument.presentationml.slideshow.main+xml",
    "template": "application/vnd.openxmlformats-officedocument.presentationml.template.main+xml",
    "slide": "application/vnd.openxmlformats-officedocument.presentationml.slide+xml",
    "layout": "application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml",
    "master": "application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml",
    "theme": "application/vnd.openxmlformats-officedocument.theme+xml",
    "notes": "application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml",
    "notesMaster": "application/vnd.openxmlformats-officedocument.presentationml.notesMaster+xml",
    "presProps": "application/vnd.openxmlformats-officedocument.presentationml.presProps+xml",
    "viewProps": "application/vnd.openxmlformats-officedocument.presentationml.viewProps+xml",
    "tableStyles": "application/vnd.openxmlformats-officedocument.presentationml.tableStyles+xml",
    "core": "application/vnd.openxmlformats-package.core-properties+xml",
    "app": "application/vnd.openxmlformats-officedocument.extended-properties+xml",
}
IMAGE_CT = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "bmp": "image/bmp",
            "tif": "image/tiff", "tiff": "image/tiff", "emf": "image/x-emf", "wmf": "image/x-wmf",
            "svg": "image/svg+xml", "webp": "image/webp", "wdp": "image/vnd.ms-photo"}
NSDECL = ('xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
          'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"')
XML_HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'


def _e(text: str) -> str:
    return escape(text or "", {'"': "&quot;"})


class _Rels:
    def __init__(self):
        self.items: list[tuple[str, str, str, bool]] = []

    def add(self, kind: str, target: str, external: bool = False, full_type: str | None = None) -> str:
        for rid, k, t, ext in self.items:
            if k == (full_type or kind) and t == target and ext == external:
                return rid
        rid = f"rId{len(self.items) + 1}"
        self.items.append((rid, full_type or kind, target, external))
        return rid

    def xml(self) -> str:
        out = [XML_HEAD, '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">']
        for rid, kind, target, ext in self.items:
            typ = kind if kind.startswith("http") else f"{REL_BASE}/{kind}"
            mode = ' TargetMode="External"' if ext else ""
            out.append(f'<Relationship Id="{rid}" Type="{typ}" Target="{_e(target)}"{mode}/>')
        out.append("</Relationships>")
        return "".join(out)


def color_xml(c: dict | None) -> str:
    if not c:
        return '<a:srgbClr val="000000"/>'
    mods = "".join(f'<a:{k} val="{int(v)}"/>' for k, v in c.get("mods", []))
    if "scheme" in c:
        return f'<a:schemeClr val="{c["scheme"]}">{mods}</a:schemeClr>' if mods else f'<a:schemeClr val="{c["scheme"]}"/>'
    val = (c.get("rgb") or "000000").upper()
    return f'<a:srgbClr val="{val}">{mods}</a:srgbClr>' if mods else f'<a:srgbClr val="{val}"/>'


class Writer:
    def __init__(self, pres: sm.Presentation, kind: str = "pres"):
        self.pres = pres
        self.kind = kind
        self.files: dict[str, bytes | str] = {}
        self.overrides: dict[str, str] = {}
        self.media_written: dict[str, str] = {}
        self.extra_parts = 0

    def write(self, path: str):
        pres = self.pres
        pres_rels = _Rels()
        master_ids, slide_ids = [], []
        layout_part_of = {}
        for mi, m in enumerate(pres.masters):
            mpart = f"ppt/slideMasters/slideMaster{mi + 1}.xml"
            mrels = _Rels()
            lay_ids = []
            for li, lay in enumerate(m.layouts):
                n = sum(len(x.layouts) for x in pres.masters[:mi]) + li + 1
                lpart = f"ppt/slideLayouts/slideLayout{n}.xml"
                layout_part_of[id(lay)] = lpart
                lrels = _Rels()
                lrels.add("slideMaster", f"../slideMasters/slideMaster{mi + 1}.xml")
                self.put(lpart, self.layout_xml(lay, m, lpart, lrels), CT["layout"])
                self.put(self.rels_name(lpart), lrels.xml())
                rid = mrels.add("slideLayout", f"../slideLayouts/slideLayout{n}.xml")
                lay_ids.append((2147483649 + n + mi * 100, rid))
            tpart = f"ppt/theme/theme{mi + 1}.xml"
            self.put(tpart, m.theme.raw_xml if m.theme.raw_xml else theme_xml(m.theme), CT["theme"])
            trid = mrels.add("theme", f"../theme/theme{mi + 1}.xml")
            del trid
            self.put(mpart, self.master_xml(m, lay_ids, mpart, mrels), CT["master"])
            self.put(self.rels_name(mpart), mrels.xml())
            master_ids.append((2147483648 + mi * 100, pres_rels.add("slideMaster", f"slideMasters/slideMaster{mi + 1}.xml")))
        has_notes = any(s.notes.strip() for s in pres.slides)
        notes_master_rid = None
        if has_notes:
            tn = len(pres.masters) + 1
            self.put(f"ppt/theme/theme{tn}.xml", theme_xml(sm.Theme()), CT["theme"])
            nmr = _Rels()
            nmr.add("theme", f"../theme/theme{tn}.xml")
            self.put("ppt/notesMasters/notesMaster1.xml", notes_master_xml(), CT["notesMaster"])
            self.put(self.rels_name("ppt/notesMasters/notesMaster1.xml"), nmr.xml())
            notes_master_rid = pres_rels.add("notesMaster", "notesMasters/notesMaster1.xml")
        for si, slide in enumerate(pres.slides):
            spart = f"ppt/slides/slide{si + 1}.xml"
            srels = _Rels()
            lay = slide.layout if slide.layout is not None else pres.master.layouts[0]
            lpart = layout_part_of.get(id(lay)) or layout_part_of[id(pres.master.layouts[0])]
            srels.add("slideLayout", "../slideLayouts/" + posixpath.basename(lpart))
            if slide.notes.strip():
                npart = f"ppt/notesSlides/notesSlide{si + 1}.xml"
                nrels = _Rels()
                nrels.add("notesMaster", "../notesMasters/notesMaster1.xml")
                nrels.add("slide", f"../slides/slide{si + 1}.xml")
                self.put(npart, notes_xml(slide.notes), CT["notes"])
                self.put(self.rels_name(npart), nrels.xml())
                srels.add("notesSlide", f"../notesSlides/notesSlide{si + 1}.xml")
            self.put(spart, self.slide_xml(slide, si, spart, srels), CT["slide"])
            self.put(self.rels_name(spart), srels.xml())
            slide_ids.append((256 + si, pres_rels.add("slide", f"slides/slide{si + 1}.xml")))
        pres_rels.add("presProps", "presProps.xml")
        pres_rels.add("viewProps", "viewProps.xml")
        pres_rels.add("theme", "theme/theme1.xml")
        pres_rels.add("tableStyles", "tableStyles.xml")
        self.put("ppt/presentation.xml", self.presentation_xml(master_ids, slide_ids, notes_master_rid),
                 CT[self.kind] if self.kind in ("pres", "show", "template") else CT["pres"])
        self.put("ppt/_rels/presentation.xml.rels", pres_rels.xml())
        loop = ' loop="1"' if pres.show_loop else ""
        self.put("ppt/presProps.xml", f'{XML_HEAD}<p:presentationPr {NSDECL}><p:showPr showNarration="1"{loop}>'
                 '<p:present/><p:sldAll/><p:penClr><a:prstClr val="red"/></p:penClr></p:showPr></p:presentationPr>',
                 CT["presProps"])
        self.put("ppt/viewProps.xml", f'{XML_HEAD}<p:viewPr {NSDECL}><p:normalViewPr><p:restoredLeft sz="15620"/>'
                 '<p:restoredTop sz="94660"/></p:normalViewPr><p:gridSpacing cx="76200" cy="76200"/></p:viewPr>',
                 CT["viewProps"])
        self.put("ppt/tableStyles.xml", f'{XML_HEAD}<a:tblStyleLst xmlns:a="{NS["a"]}" '
                 'def="{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}"/>', CT["tableStyles"])
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.put("docProps/core.xml", f'{XML_HEAD}<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/'
                 'package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" '
                 'xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" '
                 'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
                 f'<dc:title>{_e(pres.title)}</dc:title><dc:creator>{_e(pres.author)}</dc:creator>'
                 f'<cp:lastModifiedBy>{_e(pres.author)}</cp:lastModifiedBy><cp:revision>1</cp:revision>'
                 f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>'
                 f'<dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified></cp:coreProperties>',
                 CT["core"])
        self.put("docProps/app.xml", f'{XML_HEAD}<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/'
                 '2006/extended-properties"><Application>Classic 7 Show</Application>'
                 f'<PresentationFormat>On-screen Show</PresentationFormat><Slides>{len(pres.slides)}</Slides>'
                 '<AppVersion>12.0000</AppVersion></Properties>', CT["app"])
        root_rels = _Rels()
        root_rels.add("officeDocument", "ppt/presentation.xml")
        root_rels.add("http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties",
                      "docProps/core.xml", full_type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties")
        root_rels.add("extended-properties", "docProps/app.xml")
        self.put("_rels/.rels", root_rels.xml())
        defaults = {"rels": "application/vnd.openxmlformats-package.relationships+xml", "xml": "application/xml"}
        for name in self.files:
            ext = posixpath.splitext(name)[1][1:].lower()
            if ext in IMAGE_CT and name.startswith("ppt/media/"):
                defaults[ext] = IMAGE_CT[ext]
        ct = [XML_HEAD, '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">']
        for ext, typ in defaults.items():
            ct.append(f'<Default Extension="{ext}" ContentType="{typ}"/>')
        for name, typ in self.overrides.items():
            ct.append(f'<Override PartName="/{name}" ContentType="{typ}"/>')
        ct.append("</Types>")
        tmp = path + ".saving"
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", "".join(ct))
            order = sorted(self.files, key=lambda n: (not n.startswith("_rels"), not n.startswith("docProps"), n))
            for name in order:
                data = self.files[name]
                z.writestr(name, data.encode("utf-8") if isinstance(data, str) else data)
        import os
        os.replace(tmp, path)

    # -- helpers
    def put(self, name, data, ctype=None):
        self.files[name] = data
        if ctype:
            self.overrides[name] = ctype

    @staticmethod
    def rels_name(part):
        d, b = posixpath.split(part)
        return posixpath.join(d, "_rels", b + ".rels")

    def media_target(self, key: str) -> str:
        if key not in self.media_written:
            ext = posixpath.splitext(key)[1].lstrip(".").lower() or "png"
            name = f"ppt/media/image{len(self.media_written) + 1}.{ext}"
            self.files[name] = self.pres.media[key]
            self.media_written[key] = name
        return "../media/" + posixpath.basename(self.media_written[key])

    # -- fills, lines
    def fill_xml(self, fill, rels: _Rels) -> str:
        if fill is None:
            return "<a:noFill/>"
        t = fill.get("type")
        if t == "solid":
            return f"<a:solidFill>{color_xml(fill.get('color'))}</a:solidFill>"
        if t == "grad":
            stops = "".join(f'<a:gs pos="{int(pos)}">{color_xml(c)}</a:gs>' for pos, c in fill.get("stops", []))
            if fill.get("path"):
                shade = (f'<a:path path="{fill["path"]}"><a:fillToRect l="50000" t="50000" r="50000" b="50000"/>'
                         '</a:path>')
            else:
                shade = f'<a:lin ang="{int(round(float(fill.get("angle") or 0) * 60000))}" scaled="0"/>'
            return f'<a:gradFill rotWithShape="1"><a:gsLst>{stops}</a:gsLst>{shade}</a:gradFill>'
        if t == "pic" and fill.get("image") in self.pres.media:
            rid = rels.add("image", self.media_target(fill["image"]))
            mode = "<a:tile/>" if fill.get("tile") else "<a:stretch><a:fillRect/></a:stretch>"
            return f'<a:blipFill dpi="0" rotWithShape="1"><a:blip r:embed="{rid}"/><a:srcRect/>{mode}</a:blipFill>'
        if t == "pattern":
            return (f'<a:pattFill prst="{fill.get("prst") or "pct50"}"><a:fgClr>{color_xml(fill.get("fg"))}</a:fgClr>'
                    f'<a:bgClr>{color_xml(fill.get("bg"))}</a:bgClr></a:pattFill>')
        return "<a:noFill/>"

    def line_xml(self, line) -> str:
        if line is None:
            return "<a:ln><a:noFill/></a:ln>"
        w = int(line.get("width") or 9525)
        cap = f' cap="{line["cap"]}"' if line.get("cap") else ""
        inner = f"<a:solidFill>{color_xml(line.get('color'))}</a:solidFill>"
        if line.get("dash") and line["dash"] != "solid":
            inner += f'<a:prstDash val="{line["dash"]}"/>'
        join = line.get("join")
        if join:
            inner += {"round": "<a:round/>", "bevel": "<a:bevel/>", "miter": '<a:miter lim="800000"/>'}.get(join, "")
        for k, tag in (("head", "headEnd"), ("tail", "tailEnd")):
            if line.get(k) and line[k] != "none":
                size = line.get(k + "_size", "med")
                inner += f'<a:{tag} type="{line[k]}" w="{size}" len="{size}"/>'
        return f'<a:ln w="{w}"{cap}>{inner}</a:ln>'

    # -- text
    def rpr_xml(self, d: dict, rels: _Rels, tag: str = "a:rPr") -> str:
        attrs = ' lang="en-US"' if tag == "a:rPr" else ""
        if d.get("size"):
            attrs += f' sz="{int(round(float(d["size"]) * 100))}"'
        if d.get("bold") is not None:
            attrs += f' b="{1 if d["bold"] else 0}"'
        if d.get("italic") is not None:
            attrs += f' i="{1 if d["italic"] else 0}"'
        if d.get("underline") is not None:
            attrs += f' u="{"sng" if d["underline"] else "none"}"'
        if d.get("strike") is not None:
            attrs += f' strike="{"sngStrike" if d["strike"] else "noStrike"}"'
        if d.get("baseline"):
            attrs += f' baseline="{int(d["baseline"]) * 1000}"'
        if d.get("caps"):
            attrs += f' cap="{d["caps"]}"'
        if tag == "a:rPr":
            attrs += ' dirty="0"'
        inner = ""
        if d.get("color"):
            inner += f"<a:solidFill>{color_xml(d['color'])}</a:solidFill>"
        if d.get("font"):
            inner += f'<a:latin typeface="{_e(d["font"])}"/>'
        if d.get("link"):
            rid = rels.add("hyperlink", d["link"], external=True)
            inner += f'<a:hlinkClick r:id="{rid}"/>'
        return f"<{tag}{attrs}>{inner}</{tag}>" if inner else f"<{tag}{attrs}/>"

    def ppr_xml(self, d: dict, level: int | None, rels: _Rels, tag: str = "a:pPr", defrpr: dict | None = None) -> str:
        attrs = ""
        if d.get("marL") is not None:
            attrs += f' marL="{int(d["marL"])}"'
        if level:
            attrs += f' lvl="{int(level)}"'
        if d.get("indent") is not None:
            attrs += f' indent="{int(d["indent"])}"'
        if d.get("align"):
            attrs += f' algn="{d["align"]}"'
        inner = ""
        ls = d.get("line_spacing")
        if ls is not None:
            inner += (f'<a:lnSpc><a:spcPct val="{int(round(ls * 1000))}"/></a:lnSpc>' if ls > 0 else
                      f'<a:lnSpc><a:spcPts val="{int(round(-ls * 100))}"/></a:lnSpc>')
        for key, t in (("space_before", "spcBef"), ("space_after", "spcAft")):
            v = d.get(key)
            if v is not None:
                inner += (f'<a:{t}><a:spcPct val="{int(round(-v * 1000))}"/></a:{t}>' if v < 0 else
                          f'<a:{t}><a:spcPts val="{int(round(v * 100))}"/></a:{t}>')
        b = d.get("bullet")
        if b is not None:
            if b.get("none"):
                inner += "<a:buNone/>"
            else:
                if b.get("color"):
                    inner += f"<a:buClr>{color_xml(b['color'])}</a:buClr>"
                if b.get("size"):
                    inner += f'<a:buSzPct val="{int(round(float(b["size"]) * 1000))}"/>'
                if b.get("font"):
                    inner += f'<a:buFont typeface="{_e(b["font"])}"/>'
                if "auto" in b:
                    start = int(b.get("start", 1))
                    st = f' startAt="{start}"' if start != 1 else ""
                    inner += f'<a:buAutoNum type="{b["auto"]}"{st}/>'
                else:
                    inner += f'<a:buChar char="{_e(b.get("char", "•"))}"/>'
        if defrpr:
            inner += self.rpr_xml(defrpr, rels, "a:defRPr")
        if not attrs and not inner:
            return ""
        return f"<{tag}{attrs}>{inner}</{tag}>" if inner else f"<{tag}{attrs}/>"

    def lst_style_xml(self, levels: list | None, rels: _Rels) -> str:
        if not levels:
            return "<a:lstStyle/>"
        out = []
        for i, d in enumerate(levels):
            if d:
                run = {k: d[k] for k in ("size", "bold", "italic", "underline", "strike", "color", "font", "caps")
                       if d.get(k) is not None}
                x = self.ppr_xml(d, None, rels, f"a:lvl{i + 1}pPr", run or None)
                out.append(x or f"<a:lvl{i + 1}pPr/>")
        return f"<a:lstStyle>{''.join(out)}</a:lstStyle>"

    def body_pr_xml(self, body: sm.TextBody, full: bool = True) -> str:
        attrs = ""
        if body.wrap is False:
            attrs += ' wrap="none"'
        names = ("lIns", "tIns", "rIns", "bIns")
        for k, v, dflt in zip(names, body.insets, (91440, 45720, 91440, 45720)):
            if v != dflt:
                attrs += f' {k}="{int(v)}"'
        attrs += f' rtlCol="0" anchor="{body.anchor}"'
        if body.anchor_ctr:
            attrs += ' anchorCtr="1"'
        if body.vert and body.vert != "horz":
            attrs += f' vert="{body.vert}"'
        if body.columns and body.columns > 1:
            attrs += f' numCol="{body.columns}"'
        if body.autofit == "norm":
            fs = f' fontScale="{int(round(body.font_scale * 100000))}"' if body.font_scale < 0.999 else ""
            lr = f' lnSpcReduction="{int(round(body.line_reduction * 100000))}"' if body.line_reduction > 0.001 else ""
            inner = f"<a:normAutofit{fs}{lr}/>"
        elif body.autofit == "shape":
            inner = "<a:spAutoFit/>"
        else:
            inner = "<a:noAutofit/>" if full else ""
        return f"<a:bodyPr{attrs}>{inner}</a:bodyPr>"

    def paragraphs_xml(self, body: sm.TextBody, rels: _Rels) -> str:
        out = []
        for par in body.paragraphs:
            d = {k: getattr(par, k) for k in ("align", "marL", "indent", "bullet", "space_before", "space_after",
                                               "line_spacing") if getattr(par, k) is not None}
            x = [self.ppr_xml(d, par.level, rels)]
            for run in par.runs:
                rd = {k: getattr(run, k) for k in ("size", "bold", "italic", "underline", "strike", "color", "font",
                                                    "caps", "baseline", "link") if getattr(run, k) not in (None, 0)
                      or (k in ("bold", "italic", "underline", "strike") and getattr(run, k) is False)}
                rpr = self.rpr_xml(rd, rels)
                if run.field:
                    ftype = "slidenum" if run.field == "slidenum" else "datetime1"
                    fid = "{" + str(uuid.uuid4()).upper() + "}"
                    out_text = run.text or ("‹#›" if run.field == "slidenum" else "")
                    x.append(f'<a:fld id="{fid}" type="{ftype}">{rpr}<a:t>{_e(out_text)}</a:t></a:fld>')
                    continue
                parts = run.text.replace(" ", "\v").split("\v")
                for i, piece in enumerate(parts):
                    if i:
                        x.append(f"<a:br>{rpr}</a:br>")
                    if piece:
                        x.append(f"<a:r>{rpr}<a:t>{_e(piece)}</a:t></a:r>")
            end = f' sz="{int(round(par.end_size * 100))}"' if par.end_size else ""
            x.append(f'<a:endParaRPr lang="en-US"{end} dirty="0"/>')
            out.append("<a:p>" + "".join(x) + "</a:p>")
        return "".join(out) or "<a:p/>"

    def text_body_xml(self, body: sm.TextBody, rels: _Rels, tag="p:txBody", levels=None, full=True) -> str:
        return (f"<{tag}>{self.body_pr_xml(body, full)}{self.lst_style_xml(levels, rels)}"
                f"{self.paragraphs_xml(body, rels)}</{tag}>")

    # -- shapes
    def xfrm_xml(self, s: sm.Shape, tag="a:xfrm", child: tuple | None = None) -> str:
        attrs = ""
        if s.rot:
            attrs += f' rot="{int(round(s.rot * 60000)) % 21600000}"'
        if s.flip_h:
            attrs += ' flipH="1"'
        if s.flip_v:
            attrs += ' flipV="1"'
        ch = ""
        if child is not None:
            ch = f'<a:chOff x="{int(child[0])}" y="{int(child[1])}"/><a:chExt cx="{int(child[2])}" cy="{int(child[3])}"/>'
        return (f'<{tag}{attrs}><a:off x="{int(s.x)}" y="{int(s.y)}"/><a:ext cx="{max(0, int(s.cx))}" '
                f'cy="{max(0, int(s.cy))}"/>{ch}</{tag}>')

    def geom_xml(self, s: sm.Shape) -> str:
        if s.path:
            paths = []
            for pw, ph, cmds, *rest in s.path:
                fill = "" if (not rest or rest[0]) else ' fill="none"'
                x = []
                for c in cmds:
                    op = c[0]
                    if op == "M":
                        x.append(f'<a:moveTo><a:pt x="{int(c[1])}" y="{int(c[2])}"/></a:moveTo>')
                    elif op == "L":
                        x.append(f'<a:lnTo><a:pt x="{int(c[1])}" y="{int(c[2])}"/></a:lnTo>')
                    elif op == "C":
                        x.append("<a:cubicBezTo>" + "".join(f'<a:pt x="{int(c[i])}" y="{int(c[i + 1])}"/>'
                                                            for i in (1, 3, 5)) + "</a:cubicBezTo>")
                    elif op == "Q":
                        x.append("<a:quadBezTo>" + "".join(f'<a:pt x="{int(c[i])}" y="{int(c[i + 1])}"/>'
                                                          for i in (1, 3)) + "</a:quadBezTo>")
                    elif op == "A":
                        x.append(f'<a:arcTo wR="{int(c[1])}" hR="{int(c[2])}" stAng="{int(c[3])}" swAng="{int(c[4])}"/>')
                    elif op == "Z":
                        x.append("<a:close/>")
                paths.append(f'<a:path w="{int(pw)}" h="{int(ph)}"{fill}>{"".join(x)}</a:path>')
            return ('<a:custGeom><a:avLst/><a:gdLst/><a:ahLst/><a:cxnLst/><a:rect l="0" t="0" r="r" b="b"/>'
                    f'<a:pathLst>{"".join(paths)}</a:pathLst></a:custGeom>')
        av = "".join(f'<a:gd name="{k}" fmla="val {int(v)}"/>' for k, v in sorted(s.adj.items()))
        return f'<a:prstGeom prst="{s.geom or "rect"}"><a:avLst>{av}</a:avLst></a:prstGeom>'

    def ph_xml(self, s: sm.Shape) -> str:
        if s.ph is None:
            return "<p:nvPr/>"
        attrs = ""
        if s.ph.type not in ("obj",):
            attrs += f' type="{s.ph.type}"'
        if s.ph.orient:
            attrs += f' orient="{s.ph.orient}"'
        if s.ph.size:
            attrs += f' sz="{s.ph.size}"'
        if s.ph.idx:
            attrs += f' idx="{s.ph.idx}"'
        return f"<p:nvPr><p:ph{attrs}/></p:nvPr>"

    def shape_xml(self, s: sm.Shape, rels: _Rels, ids: set, in_master=False, layout_ph=False) -> str:
        sid = s.id
        while sid in ids or sid < 2:
            sid += 1000
        ids.add(sid)
        name = _e(s.name or f"Shape {sid}")
        link = ""
        if s.link:
            link = f'<a:hlinkClick r:id="{rels.add("hyperlink", s.link, external=True)}"/>'
        cnv = f'<p:cNvPr id="{sid}" name="{name}">{link}</p:cNvPr>' if link else f'<p:cNvPr id="{sid}" name="{name}"/>'
        if s.kind == "group":
            ch = s.child_rect or (s.x, s.y, s.cx, s.cy)
            kids = "".join(self.shape_xml(c, rels, ids, in_master) for c in s.children)
            return (f'<p:grpSp><p:nvGrpSpPr>{cnv}<p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
                    f'<p:grpSpPr>{self.xfrm_xml(s, child=ch)}</p:grpSpPr>{kids}</p:grpSp>')
        if s.kind == "pic":
            rid = rels.add("image", self.media_target(s.image)) if s.image in self.pres.media else ""
            crop = ""
            if any(s.crop):
                crop = '<a:srcRect ' + " ".join(f'{k}="{int(v)}"' for k, v in zip("ltrb", s.crop) if v) + "/>"
            else:
                crop = "<a:srcRect/>"
            blip = f'<a:blip r:embed="{rid}"/>' if rid else "<a:blip/>"
            line = self.line_xml(s.line) if s.line else ""
            fill = self.fill_xml(s.fill, rels) if s.fill else ""
            xfrm = "" if (s.inherit and s.ph is not None) else self.xfrm_xml(s)
            return (f'<p:pic><p:nvPicPr>{cnv}<p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr>'
                    f'{self.ph_xml(s)}</p:nvPicPr><p:blipFill>{blip}{crop}<a:stretch><a:fillRect/></a:stretch>'
                    f'</p:blipFill><p:spPr>{xfrm}{self.geom_xml(s)}{fill}{line}</p:spPr></p:pic>')
        if s.kind == "table" and s.table is not None:
            return (f'<p:graphicFrame><p:nvGraphicFramePr>{cnv}<p:cNvGraphicFramePr><a:graphicFrameLocks noGrp="1"/>'
                    f'</p:cNvGraphicFramePr>{self.ph_xml(s)}</p:nvGraphicFramePr>{self.xfrm_xml(s, "p:xfrm")}'
                    '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table">'
                    f'{self.table_xml(s.table, rels)}</a:graphicData></a:graphic></p:graphicFrame>')
        if s.kind in ("chart", "other") and s.raw:
            return self.raw_frame_xml(s, rels, sid)
        if s.kind in ("chart", "other"):
            return ""
        # an ordinary shape (or placeholder)
        xfrm = "" if (s.inherit and s.ph is not None) else self.xfrm_xml(s)
        geom = "" if (s.ph is not None and s.geom == "rect" and not s.path) else self.geom_xml(s)
        fill = ""
        line = ""
        if s.ph is None or s.fill is not None:
            fill = self.fill_xml(s.fill, rels)
        if s.ph is None or s.line is not None:
            line = self.line_xml(s.line)
        if s.ph is not None and not s.fill and not s.line:
            fill = line = ""
        txbox = ' txBox="1"' if s.txbox else ""
        locks = '<a:spLocks noGrp="1"/>' if s.ph is not None else ""
        cnvsp = f"<p:cNvSpPr{txbox}>{locks}</p:cNvSpPr>" if locks else f"<p:cNvSpPr{txbox}/>"
        style = ""
        if s.ph is None and s.style_text_color is not None:
            style = ('<p:style><a:lnRef idx="0"><a:scrgbClr r="0" g="0" b="0"/></a:lnRef><a:fillRef idx="0">'
                     '<a:scrgbClr r="0" g="0" b="0"/></a:fillRef><a:effectRef idx="0"><a:scrgbClr r="0" g="0" b="0"/>'
                     f'</a:effectRef><a:fontRef idx="minor">{color_xml(s.style_text_color)}</a:fontRef></p:style>')
        tx = ""
        levels = s.level_styles
        if s.ph is not None and s.extra_level and not levels:
            levels = []
            for i in range(9):
                lv = dict(s.extra_level)
                step = lv.pop("size_step", 0)
                if step:
                    base = self.pres.master.body_style[i].get("size", 32) if self.pres.master.body_style else 32
                    lv["size"] = max(8, base + step)
                levels.append(lv)
        if s.text is not None:
            tx = self.text_body_xml(s.text, rels, levels=levels, full=s.ph is None)
        elif s.ph is not None:
            tx = '<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:endParaRPr lang="en-US" dirty="0"/></a:p></p:txBody>'
        if s.ph is not None and in_master and s.text is None:
            tx = '<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:endParaRPr lang="en-US"/></a:p></p:txBody>'
        tag = "p:cxnSp" if (s.geom in ("line", "straightConnector1", "bentConnector3", "curvedConnector3")
                            and s.text is None and s.ph is None) else "p:sp"
        if tag == "p:cxnSp":
            return (f'<p:cxnSp><p:nvCxnSpPr>{cnv}<p:cNvCxnSpPr/><p:nvPr/></p:nvCxnSpPr>'
                    f'<p:spPr>{xfrm}{geom}{fill}{line}</p:spPr>{style}</p:cxnSp>')
        return (f'<p:sp><p:nvSpPr>{cnv}{cnvsp}{self.ph_xml(s)}</p:nvSpPr><p:spPr>{xfrm}{geom}{fill}{line}</p:spPr>'
                f'{style}{tx}</p:sp>')

    def raw_frame_xml(self, s: sm.Shape, rels: _Rels, sid: int) -> str:
        """A chart (or other object) from a file: its XML and parts, written back unchanged."""
        try:
            el = etree.fromstring(s.raw)
        except etree.XMLSyntaxError:
            return ""
        mapping = {}
        for old_rid, tree in (getattr(s, "raw_parts", None) or {}).items():
            target = self.write_part_tree(tree)
            if target:
                mapping[old_rid] = rels.add(tree["kind"], "../" + target.split("/", 1)[1] if target.startswith("ppt/")
                                            else target)
        for node in el.iter():
            for k, v in list(node.attrib.items()):
                if k.startswith(R) and v in mapping:
                    node.set(k, mapping[v])
        nv = el.find("p:nvGraphicFramePr/p:cNvPr", NS)
        if nv is not None:
            nv.set("id", str(sid))
        xfrm = el.find("p:xfrm", NS)
        if xfrm is not None:
            off, ext = xfrm.find("a:off", NS), xfrm.find("a:ext", NS)
            if off is not None:
                off.set("x", str(int(s.x)))
                off.set("y", str(int(s.y)))
            if ext is not None:
                ext.set("cx", str(int(s.cx)))
                ext.set("cy", str(int(s.cy)))
        return etree.tostring(el).decode()

    def write_part_tree(self, tree) -> str | None:
        if tree.get("external") or not tree.get("data"):
            return None
        self.extra_parts += 1
        d, b = posixpath.split(tree["name"])
        stem, ext = posixpath.splitext(b)
        name = posixpath.join(d, f"{stem}_c7{self.extra_parts}{ext}")
        data = tree["data"]
        sub = _Rels()
        mapping = {}
        for rid, child in tree.get("rels", {}).items():
            if child.get("external"):
                mapping[rid] = sub.add(child["kind"], child["external"], external=True)
                continue
            target = self.write_part_tree(child)
            if target:
                mapping[rid] = sub.add(child["kind"], posixpath.relpath(target, d))
        if mapping and data:
            try:
                el = etree.fromstring(data)
                for node in el.iter():
                    for k, v in list(node.attrib.items()):
                        if k.startswith(R) and v in mapping:
                            node.set(k, mapping[v])
                data = etree.tostring(el, xml_declaration=True, encoding="UTF-8", standalone=True)
            except etree.XMLSyntaxError:
                pass
        self.files[name] = data
        if tree.get("ctype") and not name.startswith("ppt/media/"):
            self.overrides[name] = tree["ctype"]
        elif name.startswith("ppt/media/"):
            pass
        if sub.items:
            self.files[self.rels_name(name)] = sub.xml()
        if not tree.get("ctype") or tree.get("ctype") == "application/octet-stream":
            ext_ = ext.lstrip(".").lower()
            if ext_ == "xlsx":
                self.overrides[name] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        return name

    def table_xml(self, t: sm.Table, rels: _Rels) -> str:
        import show_render
        flags = "".join(f' {k}="1"' for k, v in (("firstRow", t.first_row), ("bandRow", t.band_rows),
                                                 ("firstCol", t.first_col), ("lastRow", t.last_row),
                                                 ("lastCol", t.last_col), ("bandCol", t.band_cols)) if v)
        sid = show_render.TABLE_STYLE_IDS.get(t.style, "{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}")
        out = [f"<a:tbl><a:tblPr{flags}><a:tableStyleId>{sid}</a:tableStyleId></a:tblPr><a:tblGrid>"]
        out += [f'<a:gridCol w="{int(w)}"/>' for w in t.col_widths]
        out.append("</a:tblGrid>")
        for ri, row in enumerate(t.rows):
            h = t.row_heights[ri] if ri < len(t.row_heights) else 370840
            out.append(f'<a:tr h="{int(h)}">')
            for cell in row:
                attrs = ""
                if cell.span > 1:
                    attrs += f' gridSpan="{cell.span}"'
                if cell.row_span > 1:
                    attrs += f' rowSpan="{cell.row_span}"'
                if cell.merged:
                    attrs += ' hMerge="1"'
                body = self.text_body_xml(cell.text, rels, tag="a:txBody", full=False)
                pr_attrs = ""
                for k, v, d in zip(("marL", "marT", "marR", "marB"), cell.margins, (91440, 45720, 91440, 45720)):
                    if v != d:
                        pr_attrs += f' {k}="{int(v)}"'
                if cell.anchor and cell.anchor != "t":
                    pr_attrs += f' anchor="{cell.anchor}"'
                inner = ""
                for side, tag in (("l", "lnL"), ("r", "lnR"), ("t", "lnT"), ("b", "lnB")):
                    ln = cell.borders.get(side)
                    if ln:
                        inner += self.line_xml(ln).replace("<a:ln", f"<a:{tag}", 1).replace("</a:ln>", f"</a:{tag}>")
                if cell.fill != "auto":
                    inner += self.fill_xml(cell.fill, rels)
                out.append(f"<a:tc{attrs}>{body}<a:tcPr{pr_attrs}>{inner}</a:tcPr></a:tc>")
            out.append("</a:tr>")
        out.append("</a:tbl>")
        return "".join(out)

    def tree_xml(self, shapes, rels, in_master=False) -> str:
        ids = {1}
        body = "".join(self.shape_xml(s, rels, ids, in_master) for s in shapes)
        return ('<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
                '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/>'
                f'<a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>{body}</p:spTree>'), ids

    def bg_xml(self, fill, rels) -> str:
        if not fill:
            return ""
        return f'<p:bg><p:bgPr>{self.fill_xml(fill, rels)}<a:effectLst/></p:bgPr></p:bg>'

    # -- parts
    def presentation_xml(self, master_ids, slide_ids, notes_rid) -> str:
        pres = self.pres
        mids = "".join(f'<p:sldMasterId id="{i}" r:id="{rid}"/>' for i, rid in master_ids)
        sids = "".join(f'<p:sldId id="{i}" r:id="{rid}"/>' for i, rid in slide_ids)
        notes = f'<p:notesMasterIdLst><p:notesMasterId r:id="{notes_rid}"/></p:notesMasterIdLst>' if notes_rid else ""
        sld_type = ""
        if (pres.width, pres.height) == sm.SLIDE_4_3:
            sld_type = ' type="screen4x3"'
        lvls = "".join(f'<a:lvl{i + 1}pPr marL="{i * 457200}" algn="l" defTabSz="914400" rtl="0" eaLnBrk="1" '
                       'latinLnBrk="0" hangingPunct="1"><a:defRPr sz="1800" kern="1200"><a:solidFill>'
                       '<a:schemeClr val="tx1"/></a:solidFill><a:latin typeface="+mn-lt"/><a:ea typeface="+mn-ea"/>'
                       '<a:cs typeface="+mn-cs"/></a:defRPr></a:lvl' + f'{i + 1}pPr>' for i in range(9))
        sids_xml = f"<p:sldIdLst>{sids}</p:sldIdLst>" if sids else ""
        return (f'{XML_HEAD}<p:presentation {NSDECL} saveSubsetFonts="1"><p:sldMasterIdLst>{mids}</p:sldMasterIdLst>'
                f'{notes}{sids_xml}<p:sldSz cx="{pres.width}" cy="{pres.height}"{sld_type}/>'
                '<p:notesSz cx="6858000" cy="9144000"/><p:defaultTextStyle><a:defPPr><a:defRPr lang="en-US"/>'
                f'</a:defPPr>{lvls}</p:defaultTextStyle></p:presentation>')

    def master_xml(self, m: sm.Master, lay_ids, part, rels: _Rels) -> str:
        tree, _ids = self.tree_xml(m.shapes + m.placeholders, rels, in_master=True)
        cmap = " ".join(f'{k}="{v}"' for k, v in m.color_map.items())
        lids = "".join(f'<p:sldLayoutId id="{i}" r:id="{rid}"/>' for i, rid in lay_ids)

        def style(tag, levels):
            body = []
            for i, d in enumerate(levels[:9]):
                run = {k: d[k] for k in ("size", "bold", "italic", "color", "font", "caps") if d.get(k) is not None}
                body.append(self.ppr_xml(d, None, rels, f"a:lvl{i + 1}pPr", run) or f"<a:lvl{i + 1}pPr/>")
            return f"<p:{tag}>{''.join(body)}</p:{tag}>"
        bg = self.bg_xml(m.background, rels) or ('<p:bg><p:bgRef idx="1001"><a:schemeClr val="bg1"/></p:bgRef></p:bg>')
        return (f'{XML_HEAD}<p:sldMaster {NSDECL}><p:cSld>{bg}{tree}</p:cSld><p:clrMap {cmap}/>'
                f'<p:sldLayoutIdLst>{lids}</p:sldLayoutIdLst><p:txStyles>{style("titleStyle", m.title_style)}'
                f'{style("bodyStyle", m.body_style)}{style("otherStyle", m.other_style)}</p:txStyles></p:sldMaster>')

    def layout_xml(self, lay: sm.Layout, m: sm.Master, part, rels: _Rels) -> str:
        shapes = []
        for ph in lay.placeholders:
            c = copy.copy(ph)
            c.inherit = False
            if c.text is not None and c.text.is_empty() and c.prompt and c.ph.type not in ("dt", "ftr", "sldNum"):
                c.text = copy.deepcopy(c.text)
                c.text.paragraphs = [sm.Paragraph(level=0, runs=[sm.Run(text=c.prompt)])]
            shapes.append(c)
        tree, _ids = self.tree_xml(lay.shapes + shapes, rels)
        show = "" if lay.show_master_shapes else ' showMasterSp="0"'
        ltype = f' type="{lay.type}"' if lay.type and lay.type != "cust" else ""
        return (f'{XML_HEAD}<p:sldLayout {NSDECL}{ltype} preserve="1"{show}><p:cSld name="{_e(lay.name)}">'
                f'{self.bg_xml(lay.background, rels)}{tree}</p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>'
                '</p:sldLayout>')

    def slide_xml(self, slide: sm.Slide, index: int, part, rels: _Rels) -> str:
        tree, ids = self.tree_xml(slide.shapes, rels)
        attrs = ""
        if slide.hidden:
            attrs += ' show="0"'
        if slide.hide_master_shapes:
            attrs += ' showMasterSp="0"'
        name = f' name="{_e(slide.name)}"' if slide.name else ""
        trans = transition_xml(slide.transition)
        timing = ""
        sig = anim_signature(slide)
        if slide.raw_timing and sig == getattr(slide, "raw_anim_sig", None):
            refs = {int(x) for x in re.findall(rb'spid="(\d+)"', slide.raw_timing)}
            have = {s.id for s in sm.walk(slide.shapes)}
            if refs <= have:
                timing = slide.raw_timing.decode("utf-8")
        elif sig:
            timing = timing_xml(slide)
        return (f'{XML_HEAD}<p:sld {NSDECL}{attrs}><p:cSld{name}>{self.bg_xml(slide.background, rels)}{tree}</p:cSld>'
                f'<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>{trans}{timing}</p:sld>')


def timing_xml(slide: sm.Slide) -> str:
    """Entrance animations as PowerPoint 2007 writes them (click, with previous, after previous)."""
    steps = []
    for sh in sorted((x for x in sm.walk(slide.shapes) if x.anim and x.anim.get("effect") not in (None, "none")),
                     key=lambda x: x.anim.get("order", 0)):
        trig = sh.anim.get("trigger", "click")
        if trig == "click" or not steps:
            steps.append([sh])
        else:
            steps[-1].append(sh)
    ids = iter(range(3, 100000))
    out = []
    for grp in steps:
        click_id = next(ids)
        inner = []
        for k, sh in enumerate(grp):
            eff = sh.anim["effect"]
            pid, sub, behaviour = {
                "appear": (1, 0, ""),
                "fade": (10, 0, f'<p:animEffect transition="in" filter="fade"><p:cBhvr><p:cTn id="{{b}}" dur="500"/>'
                                f'<p:tgtEl><p:spTgt spid="{sh.id}"/></p:tgtEl></p:cBhvr></p:animEffect>'),
                "wipe": (22, 4, f'<p:animEffect transition="in" filter="wipe(up)"><p:cBhvr><p:cTn id="{{b}}" dur="500"/>'
                                f'<p:tgtEl><p:spTgt spid="{sh.id}"/></p:tgtEl></p:cBhvr></p:animEffect>'),
                "fly": (2, 4, f'<p:anim calcmode="lin" valueType="num"><p:cBhvr additive="base"><p:cTn id="{{b}}" '
                              f'dur="500" fill="hold"/><p:tgtEl><p:spTgt spid="{sh.id}"/></p:tgtEl><p:attrNameLst>'
                              '<p:attrName>ppt_y</p:attrName></p:attrNameLst></p:cBhvr><p:tavLst><p:tav tm="0">'
                              '<p:val><p:strVal val="1+#ppt_h/2"/></p:val></p:tav><p:tav tm="100000"><p:val>'
                              '<p:strVal val="#ppt_y"/></p:val></p:tav></p:tavLst></p:anim>'),
                "zoom": (53, 16, f'<p:anim calcmode="lin" valueType="num"><p:cBhvr><p:cTn id="{{b}}" dur="500" '
                                 f'fill="hold"/><p:tgtEl><p:spTgt spid="{sh.id}"/></p:tgtEl><p:attrNameLst><p:attrName>'
                                 'ppt_w</p:attrName></p:attrNameLst></p:cBhvr><p:tavLst><p:tav tm="0"><p:val><p:fltVal '
                                 'val="0"/></p:val></p:tav><p:tav tm="100000"><p:val><p:strVal val="#ppt_w"/></p:val>'
                                 '</p:tav></p:tavLst></p:anim>'),
            }.get(eff, (10, 0, ""))
            node = "clickEffect" if k == 0 else ("withEffect" if sh.anim.get("trigger") == "with" else "afterEffect")
            par_id, eff_id, set_id = next(ids), next(ids), next(ids)
            beh = behaviour.replace("{b}", str(next(ids))) if behaviour else ""
            inner.append(
                f'<p:par><p:cTn id="{par_id}" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst>'
                f'<p:par><p:cTn id="{eff_id}" presetID="{pid}" presetClass="entr" presetSubtype="{sub}" fill="hold" '
                f'nodeType="{node}"><p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst>'
                f'<p:set><p:cBhvr><p:cTn id="{set_id}" dur="1" fill="hold"><p:stCondLst><p:cond delay="0"/>'
                f'</p:stCondLst></p:cTn><p:tgtEl><p:spTgt spid="{sh.id}"/></p:tgtEl><p:attrNameLst><p:attrName>'
                'style.visibility</p:attrName></p:attrNameLst></p:cBhvr><p:to><p:strVal val="visible"/></p:to></p:set>'
                f'{beh}</p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn></p:par>')
        out.append(f'<p:par><p:cTn id="{click_id}" fill="hold"><p:stCondLst><p:cond delay="indefinite"/></p:stCondLst>'
                   f'<p:childTnLst>{"".join(inner)}</p:childTnLst></p:cTn></p:par>')
    if not out:
        return ""
    bld = "".join(f'<p:bldP spid="{sh.id}" grpId="0"/>' for grp in steps for sh in grp if sh.text is not None)
    return ('<p:timing><p:tnLst><p:par><p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot"><p:childTnLst>'
            '<p:seq concurrent="1" nextAc="seek"><p:cTn id="2" dur="indefinite" nodeType="mainSeq"><p:childTnLst>'
            f'{"".join(out)}</p:childTnLst></p:cTn><p:prevCondLst><p:cond evt="onPrev" delay="0"><p:tgtEl><p:sldTgt/>'
            '</p:tgtEl></p:cond></p:prevCondLst><p:nextCondLst><p:cond evt="onNext" delay="0"><p:tgtEl><p:sldTgt/>'
            '</p:tgtEl></p:cond></p:nextCondLst></p:seq></p:childTnLst></p:cTn></p:par></p:tnLst>'
            + (f"<p:bldLst>{bld}</p:bldLst>" if bld else "") + '</p:timing>')


def transition_xml(t: sm.Transition) -> str:
    if t is None:
        return ""
    attrs = f' spd="{t.speed}"' if t.speed and t.speed != "fast" else ""
    if not t.on_click:
        attrs += ' advClick="0"'
    if t.after_ms is not None:
        attrs += f' advTm="{int(t.after_ms)}"'
    if t.type in (None, "", "none"):
        return f"<p:transition{attrs}/>" if attrs else ""
    inner = ""
    typ = t.type
    if typ == "fade":
        inner = '<p:fade thruBlk="1"/>' if t.through_black else "<p:fade/>"
    elif typ in ("push", "wipe", "cover", "pull"):
        d = t.dir or ("l" if typ != "wipe" else "r")
        inner = f'<p:{typ} dir="{d}"/>'
    elif typ == "split":
        orient, _sep, d = (t.dir or "horz-out").partition("-")
        inner = f'<p:split orient="{orient or "horz"}" dir="{d or "out"}"/>'
    elif typ in ("randomBar", "blinds", "checker", "comb"):
        inner = f'<p:{typ} dir="{t.dir or "horz"}"/>'
    elif typ == "zoom":
        inner = f'<p:zoom dir="{t.dir or "in"}"/>'
    elif typ == "wheel":
        inner = '<p:wheel spokes="1"/>'
    elif typ in ("cut", "dissolve", "circle", "diamond", "plus", "wedge", "newsflash", "random"):
        inner = f"<p:{typ}/>"
    else:
        inner = "<p:fade/>"
    return f"<p:transition{attrs}>{inner}</p:transition>"


def notes_xml(text: str) -> str:
    paras = "".join(f'<a:p><a:r><a:rPr lang="en-US" dirty="0"/><a:t>{_e(line)}</a:t></a:r></a:p>' if line else
                    '<a:p><a:endParaRPr lang="en-US" dirty="0"/></a:p>' for line in text.split("\n"))
    return (f'{XML_HEAD}<p:notes {NSDECL}><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/>'
            '<p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/>'
            '<a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
            '<p:sp><p:nvSpPr><p:cNvPr id="2" name="Slide Image Placeholder 1"/><p:cNvSpPr><a:spLocks noGrp="1" '
            'noRot="1" noChangeAspect="1"/></p:cNvSpPr><p:nvPr><p:ph type="sldImg"/></p:nvPr></p:nvSpPr><p:spPr/></p:sp>'
            '<p:sp><p:nvSpPr><p:cNvPr id="3" name="Notes Placeholder 2"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>'
            '<p:nvPr><p:ph type="body" idx="1"/></p:nvPr></p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/>'
            f'{paras}</p:txBody></p:sp></p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:notes>')


def notes_master_xml() -> str:
    return (f'{XML_HEAD}<p:notesMaster {NSDECL}><p:cSld><p:bg><p:bgRef idx="1001"><a:schemeClr val="bg1"/></p:bgRef>'
            '</p:bg><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr>'
            '<a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm>'
            '</p:grpSpPr><p:sp><p:nvSpPr><p:cNvPr id="2" name="Slide Image Placeholder 1"/><p:cNvSpPr><a:spLocks '
            'noGrp="1" noRot="1" noChangeAspect="1"/></p:cNvSpPr><p:nvPr><p:ph type="sldImg" idx="2"/></p:nvPr>'
            '</p:nvSpPr><p:spPr><a:xfrm><a:off x="1143000" y="685800"/><a:ext cx="4572000" cy="3429000"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/><a:ln w="12700"><a:solidFill><a:prstClr '
            'val="black"/></a:solidFill></a:ln></p:spPr></p:sp><p:sp><p:nvSpPr><p:cNvPr id="3" name="Notes '
            'Placeholder 2"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr><p:ph type="body" sz="quarter" '
            'idx="3"/></p:nvPr></p:nvSpPr><p:spPr><a:xfrm><a:off x="685800" y="4343400"/><a:ext cx="5486400" '
            'cy="4114800"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr><p:txBody><a:bodyPr '
            'vert="horz" lIns="91440" tIns="45720" rIns="91440" bIns="45720" rtlCol="0"/><a:lstStyle/><a:p><a:pPr '
            'lvl="0"/><a:r><a:rPr lang="en-US"/><a:t>Click to edit Master text styles</a:t></a:r></a:p></p:txBody>'
            '</p:sp></p:spTree></p:cSld><p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" '
            'accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" '
            'folHlink="folHlink"/><p:notesStyle><a:lvl1pPr marL="0" algn="l" defTabSz="914400" rtl="0" eaLnBrk="1" '
            'latinLnBrk="0" hangingPunct="1"><a:defRPr sz="1200" kern="1200"><a:solidFill><a:schemeClr val="tx1"/>'
            '</a:solidFill><a:latin typeface="+mn-lt"/><a:ea typeface="+mn-ea"/><a:cs typeface="+mn-cs"/></a:defRPr>'
            '</a:lvl1pPr></p:notesStyle></p:notesMaster>')


def theme_xml(t: sm.Theme) -> str:
    def clr(k):
        v = t.colors.get(k, "000000")
        if k == "dk1" and v.upper() == "000000":
            return '<a:sysClr val="windowText" lastClr="000000"/>'
        if k == "lt1" and v.upper() == "FFFFFF":
            return '<a:sysClr val="window" lastClr="FFFFFF"/>'
        return f'<a:srgbClr val="{v}"/>'
    colors = "".join(f"<a:{k}>{clr(k)}</a:{k}>" for k in sm.SCHEME_KEYS)

    def grad(*stops):
        gs = "".join(f'<a:gs pos="{p}"><a:schemeClr val="phClr">{m}</a:schemeClr></a:gs>' for p, m in stops)
        return f'<a:gradFill rotWithShape="1"><a:gsLst>{gs}</a:gsLst><a:lin ang="16200000" scaled="1"/></a:gradFill>'
    fills = ('<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
             + grad((0, '<a:tint val="50000"/><a:satMod val="300000"/>'), (35000, '<a:tint val="37000"/><a:satMod val="300000"/>'),
                    (100000, '<a:tint val="15000"/><a:satMod val="350000"/>'))
             + grad((0, '<a:shade val="51000"/><a:satMod val="130000"/>'), (80000, '<a:shade val="93000"/><a:satMod val="130000"/>'),
                    (100000, '<a:shade val="94000"/><a:satMod val="135000"/>')))
    lines = "".join(f'<a:ln w="{w}" cap="flat" cmpd="sng" algn="ctr"><a:solidFill><a:schemeClr val="phClr">{m}'
                    '</a:schemeClr></a:solidFill><a:prstDash val="solid"/></a:ln>'
                    for w, m in ((9525, '<a:shade val="95000"/><a:satMod val="105000"/>'), (25400, ""), (38100, "")))
    effects = '<a:effectStyle><a:effectLst/></a:effectStyle>' * 3
    bgs = ('<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
           + grad((0, '<a:tint val="40000"/><a:satMod val="350000"/>'), (40000, '<a:tint val="45000"/><a:shade val="99000"/><a:satMod val="350000"/>'),
                  (100000, '<a:shade val="20000"/><a:satMod val="255000"/>'))
           + grad((0, '<a:tint val="80000"/><a:satMod val="300000"/>'), (100000, '<a:shade val="30000"/><a:satMod val="200000"/>')))
    return (f'{XML_HEAD}<a:theme xmlns:a="{NS["a"]}" name="{_e(t.name)}"><a:themeElements>'
            f'<a:clrScheme name="{_e(t.colors_name)}">{colors}</a:clrScheme>'
            f'<a:fontScheme name="{_e(t.fonts_name)}"><a:majorFont><a:latin typeface="{_e(t.major_font)}"/>'
            f'<a:ea typeface=""/><a:cs typeface=""/></a:majorFont><a:minorFont><a:latin typeface="{_e(t.minor_font)}"/>'
            '<a:ea typeface=""/><a:cs typeface=""/></a:minorFont></a:fontScheme>'
            f'<a:fmtScheme name="Office"><a:fillStyleLst>{fills}</a:fillStyleLst><a:lnStyleLst>{lines}</a:lnStyleLst>'
            f'<a:effectStyleLst>{effects}</a:effectStyleLst><a:bgFillStyleLst>{bgs}</a:bgFillStyleLst></a:fmtScheme>'
            '</a:themeElements><a:objectDefaults/><a:extraClrSchemeLst/></a:theme>')


def write_pptx(pres: sm.Presentation, path: str, kind: str = "pres"):
    Writer(pres, kind).write(path)
