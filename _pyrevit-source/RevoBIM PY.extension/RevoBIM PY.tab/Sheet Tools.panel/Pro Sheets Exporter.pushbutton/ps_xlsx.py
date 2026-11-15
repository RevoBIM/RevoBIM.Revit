# -*- coding: utf-8 -*-
"""A small Excel writer with no dependencies: Office Open XML straight to a zip.

No Excel, no interop and no CPython package. Interop needs Excel installed and
strands processes when a script dies; openpyxl is a CPython package that the
IronPython engine pyRevit picks cannot be relied on to load. A workbook is a
zip of XML files, and writing those directly gives full control over rotated
text, merges, borders, frozen panes, print titles and embedded logos.

The parts that make it reusable, from the Drawing Register's writer:

**A styles registry.** Fonts, fills, borders and cell formats are deduplicated
and handed back as indices, so a caller asks for "bold, centred, thin border"
and never maintains a table of style numbers. Excel insists the first two
fills are ``none`` and ``gray125``, in that order.

**Inline strings.** Text is written ``t="inlineStr"``, which skips the shared
strings part entirely.

**Schema order.** OOXML fixes the order of the elements inside
``<worksheet>`` and Excel enforces it - ``sheetPr, dimension, sheetViews,
sheetFormatPr, cols, sheetData, mergeCells, pageMargins, pageSetup,
drawing``. Lenient readers do not care, which is exactly how this ships
broken: a file can open everywhere else and still make Excel offer to repair
it. Each sheet is built in that order rather than patched together.

**A row that carries only a height is still written.** Heights live on
``<row>``, so a row with no cells - the lower half of a merged band - would
silently lose its height.

Nothing here touches Revit. The zip itself is written with .NET's
System.IO.Compression where it is available and with Python's zipfile where
it is not, which is what lets the bench build a real workbook and open it.
"""

import ps_refs  # noqa: F401  - must be first

import os
import re
import struct


MAIN_NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PKG_REL_NS = 'http://schemas.openxmlformats.org/package/2006/relationships'
CT_NS = 'http://schemas.openxmlformats.org/package/2006/content-types'
XDR_NS = ('http://schemas.openxmlformats.org/drawingml/2006/'
          'spreadsheetDrawing')
A_NS = 'http://schemas.openxmlformats.org/drawingml/2006/main'

REL_DOC = REL_NS + '/officeDocument'
REL_SHEET = REL_NS + '/worksheet'
REL_STYLES = REL_NS + '/styles'
REL_DRAWING = REL_NS + '/drawing'
REL_IMAGE = REL_NS + '/image'

CT_WORKBOOK = ('application/vnd.openxmlformats-officedocument.'
               'spreadsheetml.sheet.main+xml')
CT_SHEET = ('application/vnd.openxmlformats-officedocument.'
            'spreadsheetml.worksheet+xml')
CT_STYLES = ('application/vnd.openxmlformats-officedocument.'
             'spreadsheetml.styles+xml')
CT_DRAWING = 'application/vnd.openxmlformats-officedocument.drawing+xml'

IMAGE_TYPES = {'.png': ('png', 'image/png'),
               '.jpg': ('jpeg', 'image/jpeg'),
               '.jpeg': ('jpeg', 'image/jpeg')}

# Excel's paper codes for the sizes a register gets printed on.
PAPER = {'A4': 9, 'A3': 8}

EMU_PER_PIXEL = 9525


# ==========================================================================
# small helpers
# ==========================================================================

_BAD_XML = re.compile(u'[\x00-\x08\x0b\x0c\x0e-\x1f]')


def escape(text):
    """Text made safe for an XML element or attribute."""
    text = _BAD_XML.sub(u'', u'{0}'.format(text if text is not None else u''))
    return (text.replace(u'&', u'&amp;').replace(u'<', u'&lt;')
            .replace(u'>', u'&gt;').replace(u'"', u'&quot;'))


def column_letter(index):
    """1 -> A, 26 -> Z, 27 -> AA."""
    letters = u''
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = u'{0}{1}'.format(chr(65 + remainder), letters)
    return letters


def cell_ref(row, col):
    return u'{0}{1}'.format(column_letter(col), row)


def range_ref(row1, col1, row2, col2):
    return u'{0}:{1}'.format(cell_ref(row1, col1), cell_ref(row2, col2))


_SHEET_BAD = re.compile(u'[\\[\\]:*?/\\\\]')


def safe_sheet_name(name, taken):
    """A worksheet name Excel accepts, unique among ``taken`` (lower case).

    No ``[ ] : * ? / \\``, not blank, at most 31 characters, and unique
    *after* the cut - two long discipline names that only differ past the
    31st character would otherwise collide and Excel refuses the file.
    """
    base = _SHEET_BAD.sub(u'-', u'{0}'.format(name or u'')).strip().strip(u"'")
    if not base:
        base = u'Sheet'
    base = base[:31]
    candidate = base
    number = 2
    while candidate.lower() in taken:
        suffix = u' ({0})'.format(number)
        candidate = base[:31 - len(suffix)] + suffix
        number += 1
    taken.add(candidate.lower())
    return candidate


def width_pixels(chars):
    """Excel's column width in characters as screen pixels."""
    return int(round(chars * 7.0 + 5))


def height_pixels(points):
    return int(round(points * 96.0 / 72.0))


def image_size(path):
    """(width, height) in pixels of a PNG or JPEG, read from its header.

    Read by hand rather than through System.Drawing so the bench can run it,
    and because the only thing needed is two numbers.
    """
    try:
        handle = open(path, 'rb')
        try:
            data = handle.read(65536)
        finally:
            handle.close()
    except Exception:
        return None
    data = bytearray(data)
    if data[:8] == bytearray(b'\x89PNG\r\n\x1a\n') and len(data) >= 24:
        width, height = struct.unpack('>II', bytes(data[16:24]))
        return int(width), int(height)
    if data[:2] == bytearray(b'\xff\xd8'):
        index = 2
        while index + 9 < len(data):
            if data[index] != 0xFF:
                index += 1
                continue
            marker = data[index + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                          0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                height, width = struct.unpack(
                    '>HH', bytes(data[index + 5:index + 9]))
                return int(width), int(height)
            length = (data[index + 2] << 8) + data[index + 3]
            index += 2 + length
    return None


# ==========================================================================
# styles
# ==========================================================================

class Styles(object):
    """Fonts, fills, borders and cell formats, deduplicated into indices."""

    def __init__(self, font_name=u'Calibri', font_size=10,
                 border_color=u'FF7F7F7F'):
        self.font_name = font_name
        self.font_size = font_size
        # One colour for every border line in the book. The RD9 form draws
        # them black; the grey is kept for anything else built on this.
        self.border_color = border_color
        self.fonts = [(font_size, False, False, u'FF000000', font_name)]
        # The first two are required by Excel, in this order.
        self.fills = [u'none', u'gray125']
        self.borders = [(None, None, None, None)]
        self.formats = [(0, 0, 0, None)]

    def _index(self, table, item):
        if item in table:
            return table.index(item)
        table.append(item)
        return len(table) - 1

    def style(self, size=None, bold=False, italic=False, color=u'FF000000',
              fill=None, border=None, h=None, v=u'center', wrap=False,
              rotate=0, indent=0, font=None):
        """The index of a cell format.

        ``border`` is (left, right, top, bottom), each None, 'thin' or
        'medium'; or one of those strings for all four sides. ``font`` is a
        typeface name when the cell is not in the book's own.
        """
        font = self._index(self.fonts, (size or self.font_size, bool(bold),
                                        bool(italic), color,
                                        font or self.font_name))
        fill_id = self._index(self.fills, fill) if fill else 0
        if isinstance(border, (tuple, list)):
            sides = tuple(border)
        elif border:
            sides = (border, border, border, border)
        else:
            sides = (None, None, None, None)
        border_id = self._index(self.borders, sides)
        align = (h, v, bool(wrap), int(rotate or 0), int(indent or 0))
        return self._index(self.formats, (font, fill_id, border_id, align))

    def xml(self):
        out = [u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
               u'<styleSheet xmlns="{0}">'.format(MAIN_NS)]
        out.append(u'<fonts count="{0}">'.format(len(self.fonts)))
        for size, bold, italic, color, name in self.fonts:
            out.append(u'<font>{0}{1}<sz val="{2}"/><color rgb="{3}"/>'
                       u'<name val="{4}"/><family val="2"/></font>'.format(
                           u'<b/>' if bold else u'', u'<i/>' if italic else u'',
                           size, color, escape(name)))
        out.append(u'</fonts>')
        out.append(u'<fills count="{0}">'.format(len(self.fills)))
        for fill in self.fills:
            if fill in (u'none', u'gray125'):
                out.append(u'<fill><patternFill patternType="{0}"/></fill>'
                           .format(fill))
            else:
                out.append(u'<fill><patternFill patternType="solid">'
                           u'<fgColor rgb="{0}"/><bgColor indexed="64"/>'
                           u'</patternFill></fill>'.format(fill))
        out.append(u'</fills>')
        out.append(u'<borders count="{0}">'.format(len(self.borders)))
        for sides in self.borders:
            parts = []
            for tag, kind in zip((u'left', u'right', u'top', u'bottom'), sides):
                if kind:
                    parts.append(u'<{0} style="{1}"><color rgb="{2}"/>'
                                 u'</{0}>'.format(tag, kind,
                                                  self.border_color))
                else:
                    parts.append(u'<{0}/>'.format(tag))
            out.append(u'<border>{0}<diagonal/></border>'.format(u''.join(parts)))
        out.append(u'</borders>')
        out.append(u'<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" '
                   u'fillId="0" borderId="0"/></cellStyleXfs>')
        out.append(u'<cellXfs count="{0}">'.format(len(self.formats)))
        for font, fill_id, border_id, align in self.formats:
            if align is None:
                out.append(u'<xf numFmtId="0" fontId="0" fillId="0" '
                           u'borderId="0" xfId="0"/>')
                continue
            h, v, wrap, rotate, indent = align
            attrs = []
            if h:
                attrs.append(u'horizontal="{0}"'.format(h))
            if v:
                attrs.append(u'vertical="{0}"'.format(v))
            if wrap:
                attrs.append(u'wrapText="1"')
            if rotate:
                attrs.append(u'textRotation="{0}"'.format(rotate))
            if indent:
                attrs.append(u'indent="{0}"'.format(indent))
            out.append(u'<xf numFmtId="0" fontId="{0}" fillId="{1}" '
                       u'borderId="{2}" xfId="0" applyFont="1" applyFill="1" '
                       u'applyBorder="1" applyAlignment="1"><alignment {3}/>'
                       u'</xf>'.format(font, fill_id, border_id,
                                       u' '.join(attrs)))
        out.append(u'</cellXfs>')
        out.append(u'<cellStyles count="1"><cellStyle name="Normal" xfId="0" '
                   u'builtinId="0"/></cellStyles>')
        out.append(u'</styleSheet>')
        return u''.join(out)


# ==========================================================================
# a worksheet
# ==========================================================================

class Sheet(object):

    def __init__(self, name):
        self.name = name
        self.cells = {}            # (row, col): (value, style, is_number)
        self.merges = []
        self.widths = {}           # col: characters
        self.heights = {}          # row: points
        self.freeze = None         # (rows above, columns left)
        self.print_rows = None     # (first, last) repeated on every page
        # Pictures placed by position in pixels from the sheet's top left,
        # so a caller lays them out against the form rather than counting
        # columns: [(path, x, y, width, height)].
        self.images = []
        self.print_area = False    # print the used block and nothing else
        self.landscape = True
        self.paper = PAPER['A3']
        self.fit_width = True
        # (left, right, top, bottom, header, footer) in inches.
        self.margins = (0.4, 0.4, 0.5, 0.5, 0.3, 0.3)
        self.selected = False

    def set(self, row, col, value, style=0, number=False):
        self.cells[(row, col)] = (value, style, bool(number))

    def style_range(self, row1, col1, row2, col2, style):
        """Give every cell in a block a format, keeping any value already set.

        Excel draws a border per cell, so a merged range only has a border
        all the way round if every cell inside it carries one.
        """
        for row in range(row1, row2 + 1):
            for col in range(col1, col2 + 1):
                value, _old, number = self.cells.get((row, col),
                                                     (None, 0, False))
                self.cells[(row, col)] = (value, style, number)

    def merge(self, row1, col1, row2, col2, value=None, style=0):
        """Merge a block, put a value in its top left, style all of it."""
        self.style_range(row1, col1, row2, col2, style)
        if value is not None:
            self.set(row1, col1, value, style)
        if (row1, col1) != (row2, col2):
            self.merges.append((row1, col1, row2, col2))

    # Stored as float. IronPython refuses a precision format on an int -
    # u'{0:.2f}'.format(15) is "Precision not allowed in integer format
    # specifier" there, where CPython quietly converts - and 1.24.0 lost
    # every register to a row height of 15.
    def width(self, col, chars):
        self.widths[col] = float(chars)

    def height(self, row, points):
        self.heights[row] = float(points)

    def image(self, path, x, y, width, height):
        """Place a picture ``width`` x ``height`` pixels at ``x``, ``y``."""
        self.images.append((path, int(x), int(y), max(1, int(width)),
                            max(1, int(height))))

    def anchor(self, x, y):
        """(col, col offset, row, row offset), zero based, of a pixel point.

        A oneCellAnchor's offset has to fall inside its cell: Excel moves a
        picture whose offset runs past the column edge, differently in
        different versions. So the column and row are found from the widths
        and heights rather than an offset from A1 being trusted.
        """
        col, left = 1, 0
        while True:
            span = width_pixels(self.widths.get(col, 8.43))
            if x < left + span or col >= 16384:
                break
            left += span
            col += 1
        row, top = 1, 0
        while True:
            span = height_pixels(self.heights.get(row, 15))
            if y < top + span or row >= 1048576:
                break
            top += span
            row += 1
        return col - 1, x - left, row - 1, y - top

    def extent(self):
        rows = [key[0] for key in self.cells] + list(self.heights.keys())
        cols = [key[1] for key in self.cells] + list(self.widths.keys())
        return (max(rows) if rows else 1), (max(cols) if cols else 1)

    def xml(self, drawing_rid=None):
        last_row, last_col = self.extent()
        out = [u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
               u'<worksheet xmlns="{0}" xmlns:r="{1}">'.format(MAIN_NS, REL_NS)]

        # -- sheetPr: fit to page has to be switched on here as well as in
        # pageSetup, or Excel ignores fitToWidth.
        if self.fit_width:
            out.append(u'<sheetPr><pageSetUpPr fitToPage="1"/></sheetPr>')

        out.append(u'<dimension ref="{0}"/>'.format(
            range_ref(1, 1, last_row, last_col)))

        # -- sheetViews
        view = u'<sheetView workbookViewId="0"{0}>'.format(
            u' tabSelected="1"' if self.selected else u'')
        if self.freeze and (self.freeze[0] or self.freeze[1]):
            rows, cols = self.freeze
            top_left = cell_ref(rows + 1, cols + 1)
            if rows and cols:
                pane = u'bottomRight'
            elif rows:
                pane = u'bottomLeft'
            else:
                pane = u'topRight'
            split = u''
            if cols:
                split += u' xSplit="{0}"'.format(cols)
            if rows:
                split += u' ySplit="{0}"'.format(rows)
            view += (u'<pane{0} topLeftCell="{1}" activePane="{2}" '
                     u'state="frozen"/><selection pane="{2}" activeCell="{1}" '
                     u'sqref="{1}"/>'.format(split, top_left, pane))
        view += u'</sheetView>'
        out.append(u'<sheetViews>{0}</sheetViews>'.format(view))

        out.append(u'<sheetFormatPr defaultRowHeight="15"/>')

        # -- cols
        if self.widths:
            out.append(u'<cols>')
            for col in sorted(self.widths):
                out.append(u'<col min="{0}" max="{0}" width="{1:.2f}" '
                           u'customWidth="1"/>'.format(
                               col, float(self.widths[col])))
            out.append(u'</cols>')

        # -- sheetData. Every row with cells or with a height of its own.
        out.append(u'<sheetData>')
        rows = set([key[0] for key in self.cells]) | set(self.heights.keys())
        for row in sorted(rows):
            attrs = u' r="{0}"'.format(row)
            if row in self.heights:
                attrs += u' ht="{0:.2f}" customHeight="1"'.format(
                    float(self.heights[row]))
            cells = sorted([key for key in self.cells if key[0] == row],
                           key=lambda key: key[1])
            if not cells:
                out.append(u'<row{0}/>'.format(attrs))
                continue
            out.append(u'<row{0}>'.format(attrs))
            for key in cells:
                value, style, number = self.cells[key]
                ref = cell_ref(key[0], key[1])
                style_attr = u' s="{0}"'.format(style) if style else u''
                if value is None or value == u'':
                    out.append(u'<c r="{0}"{1}/>'.format(ref, style_attr))
                elif number:
                    out.append(u'<c r="{0}"{1}><v>{2}</v></c>'.format(
                        ref, style_attr, value))
                else:
                    out.append(u'<c r="{0}"{1} t="inlineStr"><is>'
                               u'<t xml:space="preserve">{2}</t></is></c>'
                               .format(ref, style_attr, escape(value)))
            out.append(u'</row>')
        out.append(u'</sheetData>')

        # -- mergeCells. Never a single cell: Excel calls that corrupt.
        merges = [m for m in self.merges if (m[0], m[1]) != (m[2], m[3])]
        if merges:
            out.append(u'<mergeCells count="{0}">'.format(len(merges)))
            for row1, col1, row2, col2 in merges:
                out.append(u'<mergeCell ref="{0}"/>'.format(
                    range_ref(row1, col1, row2, col2)))
            out.append(u'</mergeCells>')

        out.append(u'<pageMargins left="{0}" right="{1}" top="{2}" '
                   u'bottom="{3}" header="{4}" footer="{5}"/>'.format(
                       *self.margins))
        out.append(u'<pageSetup paperSize="{0}" orientation="{1}"{2}/>'.format(
            self.paper, u'landscape' if self.landscape else u'portrait',
            u' fitToWidth="1" fitToHeight="0"' if self.fit_width else u''))
        if drawing_rid:
            out.append(u'<drawing r:id="{0}"/>'.format(drawing_rid))
        out.append(u'</worksheet>')
        return u''.join(out)


# ==========================================================================
# the workbook
# ==========================================================================

class Workbook(object):

    def __init__(self, font_name=u'Calibri', font_size=10,
                 border_color=u'FF7F7F7F'):
        self.styles = Styles(font_name, font_size, border_color)
        self.sheets = []
        self._taken = set()

    def add_sheet(self, name):
        sheet = Sheet(safe_sheet_name(name, self._taken))
        if not self.sheets:
            sheet.selected = True
        self.sheets.append(sheet)
        return sheet

    @staticmethod
    def usable_image(path):
        """(extension, content type) of a picture Excel can show, or None."""
        if not path or not os.path.isfile(path):
            return None
        kind = IMAGE_TYPES.get(os.path.splitext(path)[1].lower())
        if kind is None or image_size(path) is None:
            return None
        return kind

    def _media(self):
        """{path: (zip name, extension, content type)} - each file once.

        The same logo on every worksheet is one file in the zip, and a PNG
        and a JPEG side by side are two, each with its own extension -
        Excel refuses a picture whose extension has no Default type.
        """
        media = {}
        for sheet in self.sheets:
            for path, _x, _y, _w, _h in sheet.images:
                if path in media:
                    continue
                kind = self.usable_image(path)
                if kind is None:
                    continue
                media[path] = (u'image{0}.{1}'.format(len(media) + 1, kind[0]),
                               kind[0], kind[1])
        return media

    def parts(self):
        """[(zip path, text or ('file', path))] in a stable order."""
        media = self._media()
        placed = [[one for one in sheet.images if one[0] in media]
                  for sheet in self.sheets]
        drawn = [index for index, pictures in enumerate(placed) if pictures]

        types = [u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
                 u'<Types xmlns="{0}">'.format(CT_NS),
                 u'<Default Extension="rels" ContentType="application/'
                 u'vnd.openxmlformats-package.relationships+xml"/>',
                 u'<Default Extension="xml" ContentType="application/xml"/>']
        declared = set()
        for path in sorted(media, key=lambda one: media[one][0]):
            _name, extension, content = media[path]
            if extension in declared:
                continue
            declared.add(extension)
            types.append(u'<Default Extension="{0}" ContentType="{1}"/>'
                         .format(extension, content))
        types.append(u'<Override PartName="/xl/workbook.xml" '
                     u'ContentType="{0}"/>'.format(CT_WORKBOOK))
        for number in range(1, len(self.sheets) + 1):
            types.append(u'<Override PartName="/xl/worksheets/sheet{0}.xml" '
                         u'ContentType="{1}"/>'.format(number, CT_SHEET))
        for index in drawn:
            types.append(u'<Override PartName="/xl/drawings/drawing{0}.xml" '
                         u'ContentType="{1}"/>'.format(index + 1, CT_DRAWING))
        types.append(u'<Override PartName="/xl/styles.xml" ContentType="{0}"/>'
                     .format(CT_STYLES))
        types.append(u'</Types>')

        parts = [(u'[Content_Types].xml', u''.join(types)),
                 (u'_rels/.rels',
                  u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                  u'<Relationships xmlns="{0}"><Relationship Id="rId1" '
                  u'Type="{1}" Target="xl/workbook.xml"/></Relationships>'
                  .format(PKG_REL_NS, REL_DOC))]
        parts.append((u'xl/workbook.xml', self._workbook_xml()))

        rels = [u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
                u'<Relationships xmlns="{0}">'.format(PKG_REL_NS)]
        for number in range(1, len(self.sheets) + 1):
            rels.append(u'<Relationship Id="rId{0}" Type="{1}" '
                        u'Target="worksheets/sheet{0}.xml"/>'.format(
                            number, REL_SHEET))
        rels.append(u'<Relationship Id="rId{0}" Type="{1}" '
                    u'Target="styles.xml"/>'.format(len(self.sheets) + 1,
                                                    REL_STYLES))
        rels.append(u'</Relationships>')
        parts.append((u'xl/_rels/workbook.xml.rels', u''.join(rels)))
        parts.append((u'xl/styles.xml', self.styles.xml()))

        for index, sheet in enumerate(self.sheets):
            number = index + 1
            pictures = placed[index]
            parts.append((u'xl/worksheets/sheet{0}.xml'.format(number),
                          sheet.xml(u'rId1' if pictures else None)))
            if not pictures:
                continue
            parts.append((
                u'xl/worksheets/_rels/sheet{0}.xml.rels'.format(number),
                u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                u'<Relationships xmlns="{0}"><Relationship Id="rId1" '
                u'Type="{1}" Target="../drawings/drawing{2}.xml"/>'
                u'</Relationships>'.format(PKG_REL_NS, REL_DRAWING, number)))
            parts.append((u'xl/drawings/drawing{0}.xml'.format(number),
                          self._drawing_xml(sheet, pictures)))
            links = [u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
                     u'<Relationships xmlns="{0}">'.format(PKG_REL_NS)]
            for slot, picture in enumerate(pictures, 1):
                links.append(u'<Relationship Id="rId{0}" Type="{1}" '
                             u'Target="../media/{2}"/>'.format(
                                 slot, REL_IMAGE, media[picture[0]][0]))
            links.append(u'</Relationships>')
            parts.append((
                u'xl/drawings/_rels/drawing{0}.xml.rels'.format(number),
                u''.join(links)))
        if drawn:
            for path in sorted(media, key=lambda one: media[one][0]):
                parts.append((u'xl/media/{0}'.format(media[path][0]),
                              ('file', path)))
        return parts

    def _workbook_xml(self):
        book = [u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
                u'<workbook xmlns="{0}" xmlns:r="{1}">'.format(MAIN_NS, REL_NS),
                u'<bookViews><workbookView activeTab="0"/></bookViews>',
                u'<sheets>']
        for number, sheet in enumerate(self.sheets, 1):
            book.append(u'<sheet name="{0}" sheetId="{1}" r:id="rId{1}"/>'
                        .format(escape(sheet.name), number))
        book.append(u'</sheets>')
        # Excel sorts defined names itself and repairs a book whose names
        # are out of its order, so they are written sorted: Print_Area
        # before Print_Titles, and by sheet within each.
        names = []
        for index, sheet in enumerate(self.sheets):
            quoted = u"'{0}'".format(sheet.name.replace(u"'", u"''"))
            if sheet.print_area:
                last_row, last_col = sheet.extent()
                names.append((u'_xlnm.Print_Area', index, u'{0}!$A$1:${1}${2}'
                              .format(quoted, column_letter(last_col),
                                      last_row)))
            if sheet.print_rows:
                first, last = sheet.print_rows
                names.append((u'_xlnm.Print_Titles', index,
                              u'{0}!${1}:${2}'.format(quoted, first, last)))
        if names:
            book.append(u'<definedNames>')
            for name, index, value in sorted(names):
                book.append(u'<definedName name="{0}" localSheetId="{1}">'
                            u'{2}</definedName>'.format(name, index,
                                                        escape(value)))
            book.append(u'</definedNames>')
        book.append(u'</workbook>')
        return u''.join(book)

    def _drawing_xml(self, sheet, pictures):
        out = [u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
               u'<xdr:wsDr xmlns:xdr="{0}" xmlns:a="{1}">'.format(XDR_NS, A_NS)]
        for slot, (_path, x, y, width, height) in enumerate(pictures, 1):
            col, col_off, row, row_off = sheet.anchor(x, y)
            cx = int(width * EMU_PER_PIXEL)
            cy = int(height * EMU_PER_PIXEL)
            out.append(
                u'<xdr:oneCellAnchor><xdr:from><xdr:col>{0}</xdr:col>'
                u'<xdr:colOff>{1}</xdr:colOff><xdr:row>{2}</xdr:row>'
                u'<xdr:rowOff>{3}</xdr:rowOff></xdr:from>'
                u'<xdr:ext cx="{4}" cy="{5}"/>'
                u'<xdr:pic><xdr:nvPicPr><xdr:cNvPr id="{6}" name="Logo {7}"/>'
                u'<xdr:cNvPicPr><a:picLocks noChangeAspect="1"/></xdr:cNvPicPr>'
                u'</xdr:nvPicPr><xdr:blipFill><a:blip xmlns:r="{8}" '
                u'r:embed="rId{7}"/><a:stretch><a:fillRect/></a:stretch>'
                u'</xdr:blipFill><xdr:spPr><a:xfrm><a:off x="0" y="0"/>'
                u'<a:ext cx="{4}" cy="{5}"/></a:xfrm><a:prstGeom prst="rect">'
                u'<a:avLst/></a:prstGeom></xdr:spPr></xdr:pic>'
                u'<xdr:clientData/></xdr:oneCellAnchor>'.format(
                    col, int(col_off * EMU_PER_PIXEL), row,
                    int(row_off * EMU_PER_PIXEL), cx, cy, slot + 1, slot,
                    REL_NS))
        out.append(u'</xdr:wsDr>')
        return u''.join(out)

    def save(self, path):
        """Write the workbook. (ok, message)."""
        parts = self.parts()
        try:
            folder = os.path.dirname(path)
            if folder and not os.path.isdir(folder):
                os.makedirs(folder)
        except Exception as err:
            return False, u'The folder could not be made: {0}'.format(err)
        # .NET first, Python's zipfile if that fails for any reason - not
        # only when .NET is missing. One route refusing on one machine is
        # no reason for the register to be lost, and both errors are kept
        # so a file that still did not appear says why twice over.
        errors = []
        for route, writer in ((u'.NET', _save_dotnet),
                              (u'zipfile', _save_python)):
            try:
                writer(path, parts)
                return True, u''
            except ImportError:
                continue
            except Exception as err:
                errors.append(u'{0}: {1}'.format(route, err))
        return False, u'; '.join(errors) or u'no zip writer available'


def _save_dotnet(path, parts):
    """Through System.IO.Compression. ImportError where there is no .NET."""
    from System.IO import File, FileMode, FileStream
    from System.IO.Compression import ZipArchive, ZipArchiveMode
    from System.Text import UTF8Encoding
    encoding = UTF8Encoding(False)          # no byte order mark
    if File.Exists(path):
        File.Delete(path)
    stream = FileStream(path, FileMode.Create)
    try:
        archive = ZipArchive(stream, ZipArchiveMode.Create)
        try:
            for name, payload in parts:
                if isinstance(payload, tuple):
                    data = File.ReadAllBytes(payload[1])
                else:
                    data = encoding.GetBytes(payload)
                entry = archive.CreateEntry(name)
                out = entry.Open()
                try:
                    out.Write(data, 0, data.Length)
                finally:
                    out.Close()
        finally:
            archive.Dispose()
    finally:
        stream.Close()


def _save_python(path, parts):
    import zipfile
    archive = zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED)
    try:
        for name, payload in parts:
            if isinstance(payload, tuple):
                handle = open(payload[1], 'rb')
                try:
                    data = handle.read()
                finally:
                    handle.close()
            else:
                data = payload.encode('utf-8')
            archive.writestr(name, data)
    finally:
        archive.close()
