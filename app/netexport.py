"""Net log export (trial): PDF and Word (.docx) with a letterhead. Python standard library only.

The letterhead is kept in the config folder and reused for every export. Two styles:
  "built": organization, tagline, contact line and accent colour, with an optional logo beside them
  "image": the user's own letterhead artwork (a banner image) across the top of the page"""
import datetime
import io
import json
import os
import zipfile
from xml.sax.saxutils import escape

LETTERHEAD_DEFAULT = {"org": "", "tagline": "", "contact": "", "accent": "#1f4e79", "style": "built"}
IMAGE_MAX = {"logo": 1024 * 1024, "banner": 3 * 1024 * 1024}


# --- letterhead settings ----------------------------------------------------------------------------
def _image_path(config_dir, kind):
    return os.path.join(config_dir, f"letterhead-{kind}.jpg")


def load_letterhead(config_dir, callsign=""):
    path = os.path.join(config_dir, "letterhead.json")
    lh = dict(LETTERHEAD_DEFAULT)
    try:
        with open(path) as f:
            lh.update({k: str(v) for k, v in json.load(f).items() if k in LETTERHEAD_DEFAULT})
    except (OSError, ValueError):
        pass
    if not lh["org"]:
        lh["org"] = callsign
    if lh["style"] not in ("built", "image"):
        lh["style"] = "built"
    lh["has_logo"] = os.path.exists(_image_path(config_dir, "logo"))
    lh["has_banner"] = os.path.exists(_image_path(config_dir, "banner"))
    return lh


def save_letterhead(config_dir, body):
    lh = {k: str(body.get(k, ""))[:200] for k in LETTERHEAD_DEFAULT}
    if not _hex(lh["accent"]):
        lh["accent"] = LETTERHEAD_DEFAULT["accent"]
    if lh["style"] not in ("built", "image"):
        lh["style"] = "built"
    os.makedirs(config_dir, exist_ok=True)
    with open(os.path.join(config_dir, "letterhead.json"), "w") as f:
        json.dump(lh, f, indent=1)
    for kind in ("logo", "banner"):
        if body.get("remove_" + kind) and os.path.exists(_image_path(config_dir, kind)):
            os.remove(_image_path(config_dir, kind))


def save_image(config_dir, kind, data):
    """kind = "logo" or "banner". The page converts the chosen image to a JPEG before sending it."""
    limit = IMAGE_MAX[kind]
    if not data or len(data) > limit or not data.startswith(b"\xff\xd8") or not jpeg_size(data):
        raise ValueError(f"The {kind} must be a JPEG under {limit // (1024 * 1024)} MB")
    os.makedirs(config_dir, exist_ok=True)
    with open(_image_path(config_dir, kind), "wb") as f:
        f.write(data)


def read_image(config_dir, kind):
    try:
        with open(_image_path(config_dir, kind), "rb") as f:
            return f.read()
    except OSError:
        return None


def _hex(c):
    c = str(c or "").lstrip("#")
    try:
        return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)) if len(c) == 6 else None
    except ValueError:
        return None


def jpeg_size(data):
    """(width, height, components) from a JPEG's start-of-frame marker, or None."""
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seg = int.from_bytes(data[i + 2:i + 4], "big")
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            h = int.from_bytes(data[i + 5:i + 7], "big")
            w = int.from_bytes(data[i + 7:i + 9], "big")
            return (w, h, data[i + 9]) if w and h else None
        i += 2 + seg
    return None


# --- the content both formats share ---------------------------------------------------------------
def _dt(iso):
    if not iso:
        return None
    try:
        return datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(datetime.timezone.utc)
    except ValueError:
        return None


def summary(log):
    start, end = _dt(log.get("start")), _dt(log.get("end"))
    ents = log.get("entries") or []
    dur = ""
    if start and end:
        mins = int((end - start).total_seconds() // 60)
        dur = f"{mins // 60} h {mins % 60:02d} min" if mins >= 60 else f"{mins} min"
    return {
        "name": log.get("name") or "Net",
        "date": start.strftime("%A, %B %d, %Y").replace(" 0", " ") if start else "",
        "time": (start.strftime("%H:%M") + (" – " + end.strftime("%H:%M") if end else " – (open)") + " UTC") if start else "",
        "duration": dur,
        "ncs": log.get("ncs") or "",
        "logger": log.get("logger") or "",
        "freq": log.get("freq") or "",
        "count": len(ents),
        "traffic": [e.get("call", "") for e in ents if e.get("traffic")],
        "short": sum(1 for e in ents if e.get("short")),
        "acked": sum(1 for e in ents if e.get("ack")),
    }


COLUMNS = [("#", 20), ("UTC", 36), ("Call", 66), ("Name", 112), ("Location", 104), ("Flags", 40), ("Ack", 30), ("Notes", 104)]


def rows(log):
    out = []
    for i, e in enumerate(log.get("entries") or [], 1):
        t = _dt(e.get("t"))
        loc = e.get("loc") or ""
        if e.get("miles") is not None and loc and not loc.startswith("("):
            loc += f" · {e['miles']} mi"
        flags = " ".join(k for k, f in (("T", "traffic"), ("S", "short"), ("M", "mobile")) if e.get(f))
        out.append([str(i), t.strftime("%H:%M") if t else "", e.get("call", ""), e.get("name", ""), loc, flags,
                    "Yes" if e.get("ack") else "", e.get("notes", "")])
    return out


LEGEND = "Flags: T = traffic · S = short time · M = mobile. Ack = acknowledged by net control."


def filename(log, ext):
    base = "".join(c if c.isalnum() or c in "-_" else "_" for c in (log.get("name") or "net")).strip("_") or "net"
    return f"{base}-{log.get('id') or 'log'}.{ext}"


# --- PDF ---------------------------------------------------------------------------------------------
# Standard Helvetica metrics (1/1000 em), characters 32..126
_HELV = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278] + [556] * 10 + \
        [278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
         667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500, 556, 556,
         278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334,
         260, 334, 584]
_HELVB = [278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278] + [556] * 10 + \
         [333, 333, 584, 584, 584, 611, 975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778,
          667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556, 333, 556, 611, 556, 611, 556,
          333, 611, 611, 278, 278, 556, 278, 889, 611, 611, 611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389,
          280, 389, 584]
FONTS = {"R": ("Helvetica", _HELV), "B": ("Helvetica-Bold", _HELVB), "I": ("Helvetica-Oblique", _HELV)}


def _w(text, font, size):
    widths = FONTS[font][1]
    return sum(widths[ord(c) - 32] if 32 <= ord(c) <= 126 else 556 for c in text) * size / 1000


def _wrap(text, font, size, width):
    lines = []
    for para in str(text or "").split("\n"):
        line = ""
        for word in para.split(" "):
            cand = (line + " " + word) if line else word
            if _w(cand, font, size) <= width:
                line = cand
                continue
            if line:
                lines.append(line)
            while _w(word, font, size) > width:   # a single word wider than the column
                n = len(word)
                while n > 1 and _w(word[:n], font, size) > width:
                    n -= 1
                lines.append(word[:n])
                word = word[n:]
            line = word
        lines.append(line)
    return lines or [""]


def _pdfstr(text):
    b = str(text).encode("cp1252", "replace")
    return b"(" + b.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b")"


class _Page:
    def __init__(self):
        self.ops = []

    def text(self, x, y, s, font="R", size=10, rgb=(0, 0, 0)):
        self.ops.append(b"BT /F%s %.2f Tf %.3f %.3f %.3f rg %.2f %.2f Td %s Tj ET" % (
            font.encode(), size, *(c / 255 for c in rgb), x, y, _pdfstr(s)))

    def rect(self, x, y, w, h, rgb):
        self.ops.append(b"%.3f %.3f %.3f rg %.2f %.2f %.2f %.2f re f" % (*(c / 255 for c in rgb), x, y, w, h))

    def line(self, x1, y1, x2, y2, rgb, width=0.75):
        self.ops.append(b"%.3f %.3f %.3f RG %.2f w %.2f %.2f m %.2f %.2f l S" % (*(c / 255 for c in rgb), width, x1, y1, x2, y2))

    def image(self, name, x, y, w, h):
        self.ops.append(b"q %.2f 0 0 %.2f %.2f %.2f cm /%s Do Q" % (w, h, x, y, name.encode()))


def _letterhead_images(lh, imgs):
    """(logo, banner) bytes to use: the banner only in "image" style, the logo only in "built" style."""
    imgs = imgs or {}
    banner = imgs.get("banner") if lh.get("style") == "image" else None
    logo = imgs.get("logo") if not banner else None
    return (logo if logo and jpeg_size(logo) else None), (banner if banner and jpeg_size(banner) else None)


def build_pdf(log, lh, imgs):
    W, H, M = 612, 792, 50
    accent = _hex(lh.get("accent")) or (31, 78, 121)
    grey, light, ink = (100, 108, 120), (243, 245, 248), (20, 26, 38)
    s, data = summary(log), rows(log)
    logo, banner = _letterhead_images(lh, imgs)
    size = jpeg_size(logo) if logo else None
    bsize = jpeg_size(banner) if banner else None
    pages = [_Page()]
    p = pages[0]
    y = H - M

    # letterhead
    if bsize:   # the user's own artwork, as wide as the text and at most 2 inches tall
        scale = min((W - 2 * M) / bsize[0], 144 / bsize[1])
        bw, bh = bsize[0] * scale, bsize[1] * scale
        p.image("Im2", M + (W - 2 * M - bw) / 2, y - bh + 10, bw, bh)
        y -= bh + 16
    else:
        lx = M
        if size:
            lw, lh_ = size[0], size[1]
            scale = min(54 / lh_, 120 / lw)
            iw, ih = lw * scale, lh_ * scale
            p.image("Im1", M, y - ih, iw, ih)
            lx = M + iw + 14
            block = max(ih, 54)
        else:   # just the text lines that are there
            block = 24 + (16 if lh.get("tagline") else 0) + (14 if lh.get("contact") else 0)
        p.text(lx, y - 20, lh.get("org") or "", "B", 20, accent)
        if lh.get("tagline"):
            p.text(lx, y - 36, lh["tagline"], "R", 11, grey)
        if lh.get("contact"):
            p.text(lx, y - 50, lh["contact"], "R", 9, grey)
        y -= block + 10
        p.line(M, y, W - M, y, accent, 2)
    y -= 30

    # title and net details
    p.text(M, y, "NET LOG", "B", 9, grey)
    y -= 20
    p.text(M, y, s["name"], "B", 17, ink)
    y -= 24
    details = [("Date", s["date"]), ("Time", s["time"]), ("Duration", s["duration"] or "—"),
               ("Net control", s["ncs"] or "—")] + ([("Logger", s["logger"])] if s["logger"] else []) + [("Frequency", s["freq"] or "—"),
               ("Check-ins", f"{s['count']} total · {len(s['traffic'])} with traffic · {s['short']} short time")]
    colw = (W - 2 * M) / 2
    for i, (k, v) in enumerate(details):
        x = M + (i % 2) * colw
        p.text(x, y, k.upper(), "B", 7.5, grey)
        p.text(x, y - 12, v, "R", 10, ink)
        if i % 2:
            y -= 30
    y -= 8 if len(details) % 2 == 0 else 38

    # check-in table
    pad, fs, lead = 4, 8.6, 11
    widths = [w for _, w in COLUMNS]

    def header(pg, y):
        hh = 18
        pg.rect(M, y - hh, W - 2 * M, hh, accent)
        x = M
        for (name, w) in COLUMNS:
            pg.text(x + pad, y - 12.5, name.upper(), "B", 7.5, (255, 255, 255))
            x += w
        return y - hh

    y = header(p, y)
    if not data:
        y -= 16
        p.text(M + pad, y, "No check-ins were logged.", "I", 9, grey)
    for n, r in enumerate(data):
        cells = [_wrap(v, "B" if c == 2 else "R", fs, widths[c] - 2 * pad) for c, v in enumerate(r)]
        rh = max(len(c) for c in cells) * lead + 2 * pad - 2
        if y - rh < M + 30:   # new page: compact letterhead line and the table header again
            p = _Page()
            pages.append(p)
            y = H - M
            p.text(M, y - 10, lh.get("org") or "", "B", 11, accent)
            right = f"{s['name']} · {s['date']}"
            p.text(W - M - _w(right, "R", 9), y - 10, right, "R", 9, grey)
            y -= 18
            p.line(M, y, W - M, y, accent, 1)
            y = header(p, y - 10)
        if n % 2:
            p.rect(M, y - rh, W - 2 * M, rh, light)
        x = M
        for c, lines in enumerate(cells):
            for k, ln in enumerate(lines):
                p.text(x + pad, y - pad - 7 - k * lead, ln, "B" if c == 2 else "R", fs, ink)
            x += widths[c]
        y -= rh
        p.line(M, y, W - M, y, (220, 226, 236), 0.5)

    # legend and traffic list
    y -= 14
    for ln in _wrap(LEGEND, "I", 8, W - 2 * M):
        p.text(M, y, ln, "I", 8, grey)
        y -= 11
    if s["traffic"]:
        y -= 8
        for ln in _wrap("Stations with traffic: " + ", ".join(s["traffic"]), "R", 9.5, W - 2 * M):
            if y < M + 30:
                p = _Page()
                pages.append(p)
                y = H - M - 10
            p.text(M, y, ln, "R", 9.5, ink)
            y -= 13

    # footers
    made = "Generated by RigPanel · " + datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    for i, pg in enumerate(pages, 1):
        pg.line(M, M - 8, W - M, M - 8, (220, 226, 236), 0.5)
        pg.text(M, M - 22, made, "R", 7.5, grey)
        t = f"Page {i} of {len(pages)}"
        pg.text(W - M - _w(t, "R", 7.5), M - 22, t, "R", 7.5, grey)

    # assemble
    objs = []

    def add(b):
        objs.append(b)
        return len(objs)

    fonts = {k: add(b"<< /Type /Font /Subtype /Type1 /BaseFont /%s /Encoding /WinAnsiEncoding >>" % v[0].encode())
             for k, v in FONTS.items()}
    xobjs = {}
    for name, data_, sz in (("Im1", logo, size), ("Im2", banner, bsize)):
        if sz:
            cs = {1: b"/DeviceGray", 3: b"/DeviceRGB", 4: b"/DeviceCMYK"}.get(sz[2], b"/DeviceRGB")
            xobjs[name] = add(b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace %s /BitsPerComponent 8 "
                              b"/Filter /DCTDecode /Length %d >>\nstream\n" % (sz[0], sz[1], cs, len(data_)) + data_ + b"\nendstream")
    res = b"<< /Font << " + b" ".join(b"/F%s %d 0 R" % (k.encode(), n) for k, n in fonts.items()) + b" >>" + \
          (b" /XObject << " + b" ".join(b"/%s %d 0 R" % (k.encode(), n) for k, n in xobjs.items()) + b" >>" if xobjs else b"") + b" >>"
    pages_id = len(objs) + 1 + 2 * len(pages)   # filled in after the page objects
    kids = []
    for pg in pages:
        stream = b"\n".join(pg.ops)
        c = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        kids.append(add(b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %d %d] /Resources %s /Contents %d 0 R >>"
                        % (pages_id, W, H, res, c)))
    assert add(b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % k for k in kids) + b"] /Count %d >>" % len(kids)) == pages_id
    title = (s["name"] + " - Net log").encode("latin-1", "replace").replace(b"\\", b"").replace(b"(", b"").replace(b")", b"")
    info = add(b"<< /Title (" + title + b") /Producer (RigPanel) >>")
    catalog = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id)

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for n, b in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % n + b + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1))
    for o in offsets:
        out.write(b"%010d 00000 n \n" % o)
    out.write(b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, catalog, info, xref))
    return out.getvalue()


# --- Word (.docx) ----------------------------------------------------------------------------------
NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
      'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
      'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
      'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"')
TEXT_W = 10080   # 7 in between 0.75 in margins, in twentieths of a point


def _run(text, bold=False, italic=False, size=None, color=None, caps=False, spacing=None):
    rpr = '<w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/>' + ("<w:b/>" if bold else "") + ("<w:i/>" if italic else "") + \
          ("<w:caps/>" if caps else "") + (f'<w:color w:val="{color}"/>' if color else "") + \
          (f'<w:spacing w:val="{spacing}"/>' if spacing else "") + (f'<w:sz w:val="{int(size * 2)}"/><w:szCs w:val="{int(size * 2)}"/>' if size else "")
    return f'<w:r><w:rPr>{rpr}</w:rPr><w:t xml:space="preserve">{escape(str(text))}</w:t></w:r>'


def _p(runs, after=0, before=0, jc=None, border=None, tabs=None, keep=False):
    ppr = ("<w:keepNext/>" if keep else "") + (border or "") + (tabs or "") + \
          f'<w:spacing w:before="{before}" w:after="{after}"/>' + (f'<w:jc w:val="{jc}"/>' if jc else "")
    return f"<w:p><w:pPr>{ppr}</w:pPr>{runs}</w:p>"


def _cell(content, width, fill=None, valign="center"):
    return (f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/>' + (f'<w:shd w:val="clear" w:color="auto" w:fill="{fill}"/>' if fill else "") +
            f'<w:vAlign w:val="{valign}"/></w:tcPr>{content}</w:tc>')


def _table(widths, rows_xml, borders=True):
    b = ('<w:tblBorders><w:top w:val="single" w:sz="4" w:color="DCE2EC"/><w:left w:val="nil"/><w:bottom w:val="single" w:sz="4" w:color="DCE2EC"/>'
         '<w:right w:val="nil"/><w:insideH w:val="single" w:sz="4" w:color="DCE2EC"/><w:insideV w:val="nil"/></w:tblBorders>') if borders else \
        ('<w:tblBorders><w:top w:val="nil"/><w:left w:val="nil"/><w:bottom w:val="nil"/><w:right w:val="nil"/>'
         '<w:insideH w:val="nil"/><w:insideV w:val="nil"/></w:tblBorders>')
    return (f'<w:tbl><w:tblPr><w:tblW w:w="{sum(widths)}" w:type="dxa"/>{b}<w:tblLayout w:type="fixed"/>'
            '<w:tblCellMar><w:top w:w="50" w:type="dxa"/><w:left w:w="80" w:type="dxa"/><w:bottom w:w="50" w:type="dxa"/>'
            '<w:right w:w="80" w:type="dxa"/></w:tblCellMar></w:tblPr><w:tblGrid>' +
            "".join(f'<w:gridCol w:w="{w}"/>' for w in widths) + "</w:tblGrid>" + "".join(rows_xml) + "</w:tbl>")


def _field(code):
    """A PAGE / NUMPAGES field; every run carries the footer's small grey font so the number matches."""
    rpr = '<w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/><w:color w:val="646C78"/><w:sz w:val="15"/><w:szCs w:val="15"/></w:rPr>'
    return (f'<w:r>{rpr}<w:fldChar w:fldCharType="begin"/></w:r><w:r>{rpr}<w:instrText xml:space="preserve"> {code} </w:instrText></w:r>'
            f'<w:r>{rpr}<w:fldChar w:fldCharType="separate"/></w:r>' + _run("1", size=7.5, color="646C78") +
            f'<w:r>{rpr}<w:fldChar w:fldCharType="end"/></w:r>')


def _pic(rid, name, pid, cx, cy):
    return (f'<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/>'
            f'<wp:docPr id="{pid}" name="{name}"/><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            f'<pic:pic><pic:nvPicPr><pic:cNvPr id="0" name="{name}.jpg"/><pic:cNvPicPr/></pic:nvPicPr>'
            f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
            '</pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r>')


def build_docx(log, lh, imgs):
    accent = "%02X%02X%02X" % (_hex(lh.get("accent")) or (31, 78, 121))
    s, data = summary(log), rows(log)
    logo, banner = _letterhead_images(lh, imgs)
    size = jpeg_size(logo) if logo else None
    bsize = jpeg_size(banner) if banner else None

    # letterhead in the page header: logo beside the organization block, accent rule underneath
    text = _p(_run(lh.get("org") or "", bold=True, size=20, color=accent)) + \
           (_p(_run(lh["tagline"], size=11, color="646C78")) if lh.get("tagline") else "") + \
           (_p(_run(lh["contact"], size=9, color="646C78")) if lh.get("contact") else "")
    if bsize:   # the user's own artwork across the top, at most 2 inches tall
        scale = min((TEXT_W / 20) / bsize[0], 144 / bsize[1])
        head_body = _p(_pic("rIdBanner", "Letterhead", 2, int(bsize[0] * scale * 12700), int(bsize[1] * scale * 12700)), jc="center")
    elif size:
        scale = min(54 / size[1], 120 / size[0])
        cx, cy = int(size[0] * scale * 12700), int(size[1] * scale * 12700)
        pic = _pic("rIdLogo", "Logo", 1, cx, cy)
        lw = int(size[0] * scale * 20) + 280
        head_body = _table([lw, TEXT_W - lw], ["<w:tr>" + _cell(_p(pic), lw) + _cell(text, TEXT_W - lw) + "</w:tr>"], borders=False)
    else:
        head_body = text
    rule = _p("", after=0) if bsize else \
        _p("", after=0, border=f'<w:pBdr><w:bottom w:val="single" w:sz="16" w:space="1" w:color="{accent}"/></w:pBdr>')
    header = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:hdr {NS}>{head_body}{rule}</w:hdr>'

    made = "Generated by RigPanel · " + datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    footer = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:ftr {NS}>' +
              _p(_run(made, size=7.5, color="646C78") + '<w:r><w:tab/></w:r>' + _run("Page ", size=7.5, color="646C78") +
                 _field("PAGE") + _run(" of ", size=7.5, color="646C78") + _field("NUMPAGES"),
                 tabs=f'<w:tabs><w:tab w:val="right" w:pos="{TEXT_W}"/></w:tabs>',
                 border='<w:pBdr><w:top w:val="single" w:sz="4" w:space="4" w:color="DCE2EC"/></w:pBdr>') + "</w:ftr>")

    body = [_p(_run("Net log", bold=True, size=9, color="646C78", caps=True, spacing=20), before=120, after=40),
            _p(_run(s["name"], bold=True, size=17, color="141A26"), after=160)]
    details = [("Date", s["date"]), ("Time", s["time"]), ("Duration", s["duration"] or "—"),
               ("Net control", s["ncs"] or "—")] + ([("Logger", s["logger"])] if s["logger"] else []) + [("Frequency", s["freq"] or "—"),
               ("Check-ins", f"{s['count']} total · {len(s['traffic'])} with traffic · {s['short']} short time")]
    half = TEXT_W // 2
    drows = []
    for i in range(0, len(details), 2):
        cells = ""
        for k, v in details[i:i + 2]:
            cells += _cell(_p(_run(k, bold=True, size=7.5, color="646C78", caps=True)) + _p(_run(v, size=10)), half, valign="top")
        if len(details[i:i + 2]) == 1:   # odd number of details: keep the two-column grid
            cells += _cell(_p(""), half)
        drows.append("<w:tr>" + cells + "</w:tr>")
    body.append(_table([half, half], drows, borders=False))
    body.append(_p("", after=120))

    widths = [round(w / 512 * TEXT_W) for _, w in COLUMNS]
    widths[-1] += TEXT_W - sum(widths)
    trs = ['<w:tr><w:trPr><w:tblHeader/></w:trPr>' + "".join(
        _cell(_p(_run(n, bold=True, size=7.5, color="FFFFFF", caps=True)), widths[c], fill=accent)
        for c, (n, _) in enumerate(COLUMNS)) + "</w:tr>"]
    for n, r in enumerate(data):
        trs.append('<w:tr><w:trPr><w:cantSplit/></w:trPr>' + "".join(
            _cell(_p(_run(v, bold=(c == 2), size=8.6)), widths[c], fill="F3F5F8" if n % 2 else None) for c, v in enumerate(r)) + "</w:tr>")
    if not data:
        trs.append("<w:tr>" + _cell(_p(_run("No check-ins were logged.", italic=True, size=9, color="646C78")), widths[0]) +
                   "".join(_cell(_p(""), w) for w in widths[1:]) + "</w:tr>")
    body.append(_table(widths, trs))
    body.append(_p(_run(LEGEND, italic=True, size=8, color="646C78"), before=120, after=80))
    if s["traffic"]:
        body.append(_p(_run("Stations with traffic: ", bold=True, size=9.5) + _run(", ".join(s["traffic"]), size=9.5)))

    sect = ('<w:sectPr><w:headerReference w:type="default" r:id="rIdHeader"/><w:footerReference w:type="default" r:id="rIdFooter"/>'
            '<w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1900" w:right="1080" w:bottom="1080" w:left="1080" '
            'w:header="600" w:footer="500" w:gutter="0"/></w:sectPr>')
    document = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {NS}><w:body>{"".join(body)}{sect}</w:body></w:document>'

    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:docDefaults><w:rPrDefault><w:rPr>'
              '<w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial" w:eastAsia="Arial"/><w:sz w:val="20"/><w:szCs w:val="20"/>'
              '<w:lang w:val="en-US"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/>'
              '</w:pPr></w:pPrDefault></w:docDefaults><w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/>'
              '</w:style></w:styles>')
    rel = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    files = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/><Default Extension="jpg" ContentType="image/jpeg"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
            '<Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>'
            '<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>'
            '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{rel}/officeDocument" Target="word/document.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
            '</Relationships>',
        "docProps/core.xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>' + escape(s["name"] + " - Net log") + '</dc:title>'
            '<dc:creator>' + escape(s["ncs"] or "RigPanel") + '</dc:creator></cp:coreProperties>',
        "word/_rels/document.xml.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rIdStyles" Type="{rel}/styles" Target="styles.xml"/>'
            f'<Relationship Id="rIdHeader" Type="{rel}/header" Target="header1.xml"/>'
            f'<Relationship Id="rIdFooter" Type="{rel}/footer" Target="footer1.xml"/></Relationships>',
        "word/document.xml": document,
        "word/styles.xml": styles,
        "word/header1.xml": header,
        "word/footer1.xml": footer,
    }
    media = {"logo": logo if size and not bsize else None, "banner": banner if bsize else None}
    hrels = "".join(f'<Relationship Id="rId{k.title()}" Type="{rel}/image" Target="media/{k}.jpg"/>' for k, v in media.items() if v)
    if hrels:
        files["word/_rels/header1.xml.rels"] = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + hrels + '</Relationships>')
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)
        for k, v in media.items():
            if v:
                z.writestr(f"word/media/{k}.jpg", v)
    return out.getvalue()
