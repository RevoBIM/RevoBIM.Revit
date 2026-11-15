# -*- coding: utf-8 -*-
"""Office Open XML read and write, with no external dependency.

A .xlsx is a zip of XML parts.  Writing one by hand is a few hundred lines and
costs nothing at runtime; the alternatives all cost more.  Excel interop needs
Excel installed and leaves orphaned processes when a script dies mid-run,
openpyxl is a CPython package that cannot be relied on under the IronPython
engine pyRevit picks, and CSV loses the colour, the widths and the header rows
that make the export worth having.

Under IronPython the zip and XML work goes through .NET; under CPython it uses
the standard library, which is what lets the whole module be bench-tested off
a real Revit.

Everything here is deliberately ignorant of Revit — it moves rows of strings
and a style id per cell, and nothing else.
"""

import os
import re

IRONPYTHON = False
try:                                   # pragma: no cover - environment probe
    import clr                         # noqa: F401
    IRONPYTHON = True
except ImportError:
    pass

if IRONPYTHON:                         # pragma: no cover - Revit only
    import System                      # noqa: F401
    clr.AddReference('System.IO.Compression')
    clr.AddReference('System.IO.Compression.FileSystem')
    from System.IO import File, MemoryStream, SeekOrigin
    from System.IO.Compression import ZipArchive, ZipArchiveMode
    from System.IO.Compression import CompressionLevel
    from System.Text import Encoding
    from System.IO import StreamReader
else:
    import zipfile
    import io


# =============================================================== zip access ==

class ZipOut(object):
    """Collects named parts and writes them as one zip."""

    def __init__(self):
        self.parts = []

    def add(self, name, text):
        self.parts.append((name, text))

    def save(self, path):
        folder = os.path.dirname(path)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)
        if IRONPYTHON:                 # pragma: no cover - Revit only
            stream = MemoryStream()
            archive = ZipArchive(stream, ZipArchiveMode.Create, True)
            try:
                for name, text in self.parts:
                    entry = archive.CreateEntry(name, CompressionLevel.Optimal)
                    writer = entry.Open()
                    try:
                        data = Encoding.UTF8.GetBytes(text)
                        writer.Write(data, 0, data.Length)
                    finally:
                        writer.Close()
            finally:
                archive.Dispose()
            stream.Seek(0, SeekOrigin.Begin)
            File.WriteAllBytes(path, stream.ToArray())
            stream.Dispose()
        else:
            handle = zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED)
            try:
                for name, text in self.parts:
                    handle.writestr(name, text.encode('utf-8'))
            finally:
                handle.close()


def zip_read(path, wanted):
    """Return {name: text} for the parts asked for that exist."""
    out = {}
    if IRONPYTHON:                     # pragma: no cover - Revit only
        data = File.ReadAllBytes(path)
        stream = MemoryStream(data)
        archive = ZipArchive(stream, ZipArchiveMode.Read)
        try:
            for entry in archive.Entries:
                name = entry.FullName.replace('\\', '/')
                if name not in wanted:
                    continue
                reader = StreamReader(entry.Open(), Encoding.UTF8)
                try:
                    out[name] = reader.ReadToEnd()
                finally:
                    reader.Close()
        finally:
            archive.Dispose()
            stream.Dispose()
    else:
        handle = zipfile.ZipFile(path, 'r')
        try:
            for name in handle.namelist():
                key = name.replace('\\', '/')
                if key in wanted:
                    out[key] = handle.read(name).decode('utf-8')
        finally:
            handle.close()
    return out


# ==================================================================== utils ==

def esc(text):
    """XML-escape, and drop the control characters Excel refuses to open."""
    if text is None:
        return ''
    try:
        text = unicode(text)           # noqa: F821 - IronPython 2.7
    except NameError:
        text = str(text)
    text = (text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                .replace('"', '&quot;'))
    out = []
    for ch in text:
        code = ord(ch)
        if code in (9, 10, 13) or code >= 32:
            out.append(ch)
    return ''.join(out)


def col_letter(index):
    n = int(index)
    out = ''
    while True:
        out = chr(ord('A') + (n % 26)) + out
        n = n // 26 - 1
        if n < 0:
            break
    return out


def col_index(letters):
    n = 0
    for ch in letters.upper():
        if 'A' <= ch <= 'Z':
            n = n * 26 + (ord(ch) - ord('A') + 1)
    return n - 1


_NUMERIC = re.compile(r'^-?\d+(\.\d+)?$')


def looks_numeric(text):
    return bool(text) and bool(_NUMERIC.match(text.strip()))


# ================================================================== styling ==

class Styles(object):
    """Builds styles.xml. Each add_* returns the index cells refer to."""

    def __init__(self):
        self.fonts = []
        self.fills = []
        self.borders = []
        self.xfs = []
        # index 0 of each is the default Excel expects to be present
        self.font('000000', 11, False)
        self.fill(None)
        self.fill(None, pattern='gray125')
        self.border(False)
        self.xf(0, 0, 0)

    def font(self, colour, size=11, bold=False, italic=False, name='Calibri'):
        key = (colour, size, bold, italic, name)
        for i, existing in enumerate(self.fonts):
            if existing == key:
                return i
        self.fonts.append(key)
        return len(self.fonts) - 1

    def fill(self, colour, pattern='solid'):
        key = (colour, pattern)
        for i, existing in enumerate(self.fills):
            if existing == key:
                return i
        self.fills.append(key)
        return len(self.fills) - 1

    def border(self, on, colour='D0D0D0'):
        key = (on, colour)
        for i, existing in enumerate(self.borders):
            if existing == key:
                return i
        self.borders.append(key)
        return len(self.borders) - 1

    def xf(self, font, fill, border, wrap=False, align=None, valign='center',
           indent=0):
        key = (font, fill, border, wrap, align, valign, indent)
        for i, existing in enumerate(self.xfs):
            if existing == key:
                return i
        self.xfs.append(key)
        return len(self.xfs) - 1

    def cell(self, colour=None, bg=None, size=11, bold=False, italic=False,
             border=True, wrap=False, align=None, valign='center'):
        """One call for the common case: returns a style id for a cell."""
        return self.xf(self.font(colour or '000000', size, bold, italic),
                       self.fill(bg) if bg else 0,
                       self.border(border),
                       wrap, align, valign)

    def xml(self):
        parts = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
                 '<styleSheet xmlns="http://schemas.openxmlformats.org/'
                 'spreadsheetml/2006/main">']

        parts.append('<fonts count="{0}">'.format(len(self.fonts)))
        for colour, size, bold, italic, name in self.fonts:
            bits = ['<sz val="{0}"/>'.format(size),
                    '<color rgb="FF{0}"/>'.format(colour),
                    '<name val="{0}"/>'.format(name)]
            if italic:
                bits.insert(0, '<i/>')
            if bold:
                bits.insert(0, '<b/>')
            parts.append('<font>' + ''.join(bits) + '</font>')
        parts.append('</fonts>')

        parts.append('<fills count="{0}">'.format(len(self.fills)))
        for colour, pattern in self.fills:
            if colour is None:
                parts.append('<fill><patternFill patternType="{0}"/></fill>'.format(
                    pattern if pattern == 'gray125' else 'none'))
            else:
                parts.append('<fill><patternFill patternType="solid">'
                             '<fgColor rgb="FF{0}"/><bgColor indexed="64"/>'
                             '</patternFill></fill>'.format(colour))
        parts.append('</fills>')

        parts.append('<borders count="{0}">'.format(len(self.borders)))
        for on, colour in self.borders:
            if not on:
                parts.append('<border><left/><right/><top/><bottom/>'
                             '<diagonal/></border>')
            else:
                edge = ('<{0} style="thin"><color rgb="FF{1}"/></{0}>')
                parts.append('<border>' +
                             edge.format('left', colour) +
                             edge.format('right', colour) +
                             edge.format('top', colour) +
                             edge.format('bottom', colour) +
                             '<diagonal/></border>')
        parts.append('</borders>')

        parts.append('<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" '
                     'fillId="0" borderId="0"/></cellStyleXfs>')
        parts.append('<cellXfs count="{0}">'.format(len(self.xfs)))
        for font, fill, border, wrap, align, valign, indent in self.xfs:
            attrs = ('numFmtId="0" fontId="{0}" fillId="{1}" borderId="{2}" '
                     'applyFont="1" applyFill="1" applyBorder="1"'.format(
                         font, fill, border))
            bits = []
            if wrap:
                bits.append('wrapText="1"')
            if align:
                bits.append('horizontal="{0}"'.format(align))
            if valign:
                bits.append('vertical="{0}"'.format(valign))
            if indent:
                bits.append('indent="{0}"'.format(indent))
            if bits:
                parts.append('<xf {0} applyAlignment="1"><alignment {1}/></xf>'.format(
                    attrs, ' '.join(bits)))
            else:
                parts.append('<xf {0}/>'.format(attrs))
        parts.append('</cellXfs>')
        parts.append('<cellStyles count="1"><cellStyle name="Normal" xfId="0" '
                     'builtinId="0"/></cellStyles>')
        parts.append('</styleSheet>')
        return ''.join(parts)


# ================================================================== writing ==

class Sheet(object):
    """Rows of (text, style_id, is_number) tuples, plus layout."""

    def __init__(self, name):
        self.name = name
        self.rows = []
        self.widths = {}
        self.freeze = None             # (rows, cols)
        self.selected = False
        self.autofilter = None         # (first_row, first_col, last_row, last_col)
        self.merges = []
        self.row_heights = {}

    def add_row(self, cells, height=None):
        self.rows.append(cells)
        if height:
            self.row_heights[len(self.rows)] = height
        return len(self.rows)

    def width(self, col_index_, value):
        self.widths[col_index_] = value

    def xml(self):
        # OOXML fixes the order of these elements and Excel enforces it, even
        # though lenient readers do not: sheetPr, dimension, sheetViews,
        # sheetFormatPr, cols, sheetData, ..., autoFilter, ..., mergeCells.
        # Building the string in that order is the whole trick — inserting
        # sheetViews later put it after <cols> and every file needed repairing.
        parts = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
                 '<worksheet xmlns="http://schemas.openxmlformats.org/'
                 'spreadsheetml/2006/main">']

        last_row = len(self.rows)
        last_col = 0
        for cells in self.rows:
            last_col = max(last_col, len(cells))
        if last_row and last_col:
            parts.append('<dimension ref="A1:{0}{1}"/>'.format(
                col_letter(last_col - 1), last_row))

        if self.freeze:
            rows, cols = self.freeze
            top_left = '{0}{1}'.format(col_letter(cols), rows + 1)
            pane = ['<pane']
            if cols:
                pane.append(' xSplit="{0}"'.format(cols))
            if rows:
                pane.append(' ySplit="{0}"'.format(rows))
            pane.append(' topLeftCell="{0}" activePane="bottomRight" '
                        'state="frozen"/>'.format(top_left))
            parts.append('<sheetViews><sheetView tabSelected="{0}" '
                         'workbookViewId="0">{1}</sheetView></sheetViews>'.format(
                             1 if self.selected else 0, ''.join(pane)))
        else:
            parts.append('<sheetViews><sheetView tabSelected="{0}" '
                         'workbookViewId="0"/></sheetViews>'.format(
                             1 if self.selected else 0))

        parts.append('<sheetFormatPr defaultRowHeight="15"/>')

        if self.widths:
            parts.append('<cols>')
            for idx in sorted(self.widths.keys()):
                parts.append('<col min="{0}" max="{0}" width="{1}" '
                             'customWidth="1"/>'.format(
                                 idx + 1, round(float(self.widths[idx]), 2)))
            parts.append('</cols>')

        parts.append('<sheetData>')
        for r, cells in enumerate(self.rows):
            height = self.row_heights.get(r + 1)
            if height:
                parts.append('<row r="{0}" ht="{1}" customHeight="1">'.format(
                    r + 1, height))
            else:
                parts.append('<row r="{0}">'.format(r + 1))
            for c, cell in enumerate(cells):
                if cell is None:
                    continue
                text, style, numeric = cell
                ref = '{0}{1}'.format(col_letter(c), r + 1)
                attrs = ' s="{0}"'.format(style) if style else ''
                if text is None or text == '':
                    parts.append('<c r="{0}"{1}/>'.format(ref, attrs))
                elif numeric and looks_numeric(text):
                    parts.append('<c r="{0}"{1}><v>{2}</v></c>'.format(
                        ref, attrs, esc(text.strip())))
                else:
                    # inline strings: no shared-string table to keep in step,
                    # which matters more than the file size here
                    parts.append('<c r="{0}"{1} t="inlineStr"><is><t '
                                 'xml:space="preserve">{2}</t></is></c>'.format(
                                     ref, attrs, esc(text)))
            parts.append('</row>')
        parts.append('</sheetData>')

        if self.autofilter and self.autofilter[2] > self.autofilter[0]:
            r0, c0, r1, c1 = self.autofilter
            parts.append('<autoFilter ref="{0}{1}:{2}{3}"/>'.format(
                col_letter(c0), r0 + 1, col_letter(c1), r1 + 1))

        merges = [m for m in self.merges if not (m[0] == m[2] and m[1] == m[3])]
        if merges:
            parts.append('<mergeCells count="{0}">'.format(len(merges)))
            for r0, c0, r1, c1 in merges:
                parts.append('<mergeCell ref="{0}{1}:{2}{3}"/>'.format(
                    col_letter(c0), r0 + 1, col_letter(c1), r1 + 1))
            parts.append('</mergeCells>')

        parts.append('</worksheet>')
        return ''.join(parts)


class Workbook(object):

    def __init__(self):
        self.styles = Styles()
        self.sheets = []

    def sheet(self, name):
        # duplicate tab names make a workbook Excel refuses to open, and two
        # long names can collide after the 31-character truncation
        wanted = sheet_name_safe(name)
        taken = [x.name.lower() for x in self.sheets]
        if wanted.lower() in taken:
            n = 2
            while True:
                suffix = ' ({0})'.format(n)
                candidate = wanted[:31 - len(suffix)] + suffix
                if candidate.lower() not in taken:
                    wanted = candidate
                    break
                n += 1
        s = Sheet(wanted)
        s.selected = not self.sheets      # only the first tab opens selected
        self.sheets.append(s)
        return s

    def save(self, path):
        z = ZipOut()
        z.add('[Content_Types].xml', self._content_types())
        z.add('_rels/.rels',
              '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<Relationships xmlns="http://schemas.openxmlformats.org/'
              'package/2006/relationships">'
              '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
              'officeDocument/2006/relationships/officeDocument" '
              'Target="xl/workbook.xml"/></Relationships>')
        z.add('xl/workbook.xml', self._workbook())
        z.add('xl/_rels/workbook.xml.rels', self._workbook_rels())
        z.add('xl/styles.xml', self.styles.xml())
        for i, sheet in enumerate(self.sheets):
            z.add('xl/worksheets/sheet{0}.xml'.format(i + 1), sheet.xml())
        z.save(path)

    def _content_types(self):
        parts = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
                 '<Types xmlns="http://schemas.openxmlformats.org/package/'
                 '2006/content-types">',
                 '<Default Extension="rels" ContentType="application/'
                 'vnd.openxmlformats-package.relationships+xml"/>',
                 '<Default Extension="xml" ContentType="application/xml"/>',
                 '<Override PartName="/xl/workbook.xml" ContentType="application/'
                 'vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
                 '<Override PartName="/xl/styles.xml" ContentType="application/'
                 'vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>']
        for i in range(len(self.sheets)):
            parts.append('<Override PartName="/xl/worksheets/sheet{0}.xml" '
                         'ContentType="application/vnd.openxmlformats-'
                         'officedocument.spreadsheetml.worksheet+xml"/>'.format(i + 1))
        parts.append('</Types>')
        return ''.join(parts)

    def _workbook(self):
        parts = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
                 '<workbook xmlns="http://schemas.openxmlformats.org/'
                 'spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats'
                 '.org/officeDocument/2006/relationships"><sheets>']
        for i, sheet in enumerate(self.sheets):
            parts.append('<sheet name="{0}" sheetId="{1}" r:id="rId{1}"/>'.format(
                esc(sheet_name_safe(sheet.name)), i + 1))
        parts.append('</sheets></workbook>')
        return ''.join(parts)

    def _workbook_rels(self):
        parts = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
                 '<Relationships xmlns="http://schemas.openxmlformats.org/'
                 'package/2006/relationships">']
        for i in range(len(self.sheets)):
            parts.append('<Relationship Id="rId{0}" Type="http://schemas.'
                         'openxmlformats.org/officeDocument/2006/relationships/'
                         'worksheet" Target="worksheets/sheet{0}.xml"/>'.format(i + 1))
        parts.append('<Relationship Id="rId{0}" Type="http://schemas.'
                     'openxmlformats.org/officeDocument/2006/relationships/'
                     'styles" Target="styles.xml"/>'.format(len(self.sheets) + 1))
        parts.append('</Relationships>')
        return ''.join(parts)


def sheet_name_safe(name):
    """Excel refuses : \\ / ? * [ ] and anything over 31 characters."""
    out = re.sub(r'[:\\/?*\[\]]', '-', name or 'Sheet1')
    return out[:31] or 'Sheet1'


# ================================================================== reading ==

_CELL_RE = re.compile(r'<c\s+([^>]*?)(/>|>(.*?)</c>)', re.S)
_ROW_RE = re.compile(r'<row\s+[^>]*?r="(\d+)"[^>]*?(/>|>(.*?)</row>)', re.S)
_ATTR_RE = re.compile(r'(\w+)="([^"]*)"')
_T_RE = re.compile(r'<t[^>]*>(.*?)</t>', re.S)
_V_RE = re.compile(r'<v[^>]*>(.*?)</v>', re.S)


def unesc(text):
    return (text.replace('&lt;', '<').replace('&gt;', '>')
                .replace('&quot;', '"').replace('&apos;', "'")
                .replace('&amp;', '&'))


def read_sheet(path, sheet_index=0):
    """Return a list of rows, each a list of strings. Sparse cells are filled."""
    wanted = set(['xl/worksheets/sheet{0}.xml'.format(sheet_index + 1),
                  'xl/sharedStrings.xml'])
    parts = zip_read(path, wanted)
    body = parts.get('xl/worksheets/sheet{0}.xml'.format(sheet_index + 1))
    if body is None:
        raise ValueError('That file does not contain a readable worksheet.')

    shared = []
    shared_xml = parts.get('xl/sharedStrings.xml')
    if shared_xml:
        for chunk in re.findall(r'<si>(.*?)</si>', shared_xml, re.S):
            shared.append(unesc(''.join(_T_RE.findall(chunk))))

    rows = {}
    widest = 0
    for match in _ROW_RE.finditer(body):
        r = int(match.group(1)) - 1
        inner = match.group(3) or ''
        cells = {}
        for cm in _CELL_RE.finditer(inner):
            attrs = dict(_ATTR_RE.findall(cm.group(1)))
            ref = attrs.get('r', '')
            letters = re.match(r'([A-Za-z]+)', ref)
            c = col_index(letters.group(1)) if letters else 0
            payload = cm.group(3) or ''
            kind = attrs.get('t', '')
            if kind == 'inlineStr':
                value = unesc(''.join(_T_RE.findall(payload)))
            elif kind == 's':
                hit = _V_RE.search(payload)
                idx = int(hit.group(1)) if hit else -1
                value = shared[idx] if 0 <= idx < len(shared) else ''
            elif kind == 'str':
                value = unesc(''.join(_V_RE.findall(payload)))
            else:
                hit = _V_RE.search(payload)
                value = unesc(hit.group(1)) if hit else ''
            cells[c] = value
            widest = max(widest, c + 1)
        rows[r] = cells

    if not rows:
        return []
    out = []
    for r in range(max(rows.keys()) + 1):
        cells = rows.get(r, {})
        out.append([cells.get(c, '') for c in range(widest)])
    return out
