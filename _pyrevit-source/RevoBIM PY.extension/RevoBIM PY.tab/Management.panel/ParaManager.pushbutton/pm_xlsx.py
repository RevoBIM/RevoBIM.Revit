# -*- coding: utf-8 -*-
"""A small .xlsx writer and reader. Parts are plain text, so the bench can check them."""
import pm_clr
import re

CONTENT = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
           '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
           '<Default Extension="xml" ContentType="application/xml"/>'
           '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
           '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
           '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
           '</Types>')
RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>')
WORKBOOK = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Parameters" sheetId="1" r:id="rId1"/></sheets></workbook>')
WORKBOOK_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
                 '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                 '</Relationships>')
STYLES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
          '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
          '<font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Calibri"/></font></fonts>'
          '<fills count="3"><fill><patternFill patternType="none"/></fill>'
          '<fill><patternFill patternType="gray125"/></fill>'
          '<fill><patternFill patternType="solid"><fgColor rgb="FF3C4454"/></patternFill></fill></fills>'
          '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
          '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
          '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
          '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/></cellXfs>'
          '</styleSheet>')


def escape(text):
    return (u'{0}'.format(text).replace(u'&', u'&amp;').replace(u'<', u'&lt;')
            .replace(u'>', u'&gt;').replace(u'"', u'&quot;'))


def unescape(text):
    return (text.replace(u'&lt;', u'<').replace(u'&gt;', u'>').replace(u'&quot;', u'"')
            .replace(u'&apos;', u"'").replace(u'&amp;', u'&'))


def column_name(index):
    name = u''
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        name = chr(65 + rest) + name
    return name


def column_index(reference):
    total = 0
    for ch in re.match(u'[A-Z]+', reference).group(0):
        total = total * 26 + ord(ch) - 64
    return total - 1


def sheet_xml(rows):
    width = max([len(r) for r in rows] or [1])
    out = [u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           u'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
           u'<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
           u'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
           u'<cols><col min="1" max="{0}" width="30" customWidth="1"/></cols><sheetData>'.format(width)]
    for r, row in enumerate(rows):
        out.append(u'<row r="{0}">'.format(r + 1))
        style = u' s="1"' if r == 0 else u''
        for c, value in enumerate(row):
            out.append(u'<c r="{0}{1}"{2} t="inlineStr"><is><t xml:space="preserve">{3}</t></is></c>'.format(
                column_name(c), r + 1, style, escape(value)))
        out.append(u'</row>')
    out.append(u'</sheetData><autoFilter ref="A1:{0}{1}"/></worksheet>'.format(
        column_name(width - 1), max(1, len(rows))))
    return u''.join(out)


def build_parts(rows):
    return {'[Content_Types].xml': CONTENT, '_rels/.rels': RELS, 'xl/workbook.xml': WORKBOOK,
            'xl/_rels/workbook.xml.rels': WORKBOOK_RELS, 'xl/styles.xml': STYLES,
            'xl/worksheets/sheet1.xml': sheet_xml(rows)}


def read_shared_strings(xml):
    out = []
    for si in re.findall(u'<si>(.*?)</si>|<si/>', xml or u'', re.S):
        out.append(unescape(u''.join(re.findall(u'<t[^>]*>(.*?)</t>', si, re.S))))
    return out


def rows_from_parts(parts):
    """Rows of the first sheet, from this tool's inline text or Excel's shared strings."""
    shared = read_shared_strings(parts.get('xl/sharedStrings.xml'))
    sheet = parts.get('xl/worksheets/sheet1.xml', u'')
    rows = []
    for body in re.findall(u'<row\\b[^>]*?(?:/>|>(.*?)</row>)', sheet, re.S):
        cells = {}
        for attrs, inner in re.findall(u'<c\\b([^>]*?)(?:/>|>(.*?)</c>)', body, re.S):
            ref = re.search(u'r="([A-Z]+)\\d+"', attrs)
            if ref is None:
                continue
            kind = re.search(u't="(\\w+)"', attrs)
            kind = kind.group(1) if kind else u'n'
            if kind == u'inlineStr':
                value = unescape(u''.join(re.findall(u'<t[^>]*>(.*?)</t>', inner, re.S)))
            else:
                found = re.search(u'<v>(.*?)</v>', inner, re.S)
                raw = found.group(1) if found else u''
                value = shared[int(raw)] if kind == u's' and raw else unescape(raw)
            cells[column_index(ref.group(1))] = value
        rows.append([cells.get(i, u'') for i in range(max(cells) + 1)] if cells else [])
    return rows


def write_file(path, rows):
    from System.IO import File, FileStream, FileMode, StreamWriter
    from System.IO.Compression import ZipArchive, ZipArchiveMode
    from System.Text import UTF8Encoding
    if File.Exists(path):
        File.Delete(path)
    stream = FileStream(path, FileMode.Create)
    try:
        archive = ZipArchive(stream, ZipArchiveMode.Create)
        try:
            parts = build_parts(rows)
            for name in sorted(parts):
                writer = StreamWriter(archive.CreateEntry(name).Open(), UTF8Encoding(False))
                try:
                    writer.Write(parts[name])
                finally:
                    writer.Dispose()
        finally:
            archive.Dispose()
    finally:
        stream.Dispose()


def read_file(path):
    from System.IO import FileStream, FileMode, FileAccess, FileShare, StreamReader
    from System.IO.Compression import ZipArchive, ZipArchiveMode
    stream = FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite)
    try:
        archive = ZipArchive(stream, ZipArchiveMode.Read)
        try:
            parts = {}
            for entry in archive.Entries:
                if entry.FullName.endswith('.xml'):
                    reader = StreamReader(entry.Open())
                    try:
                        parts[entry.FullName] = reader.ReadToEnd()
                    finally:
                        reader.Dispose()
            return rows_from_parts(parts)
        finally:
            archive.Dispose()
    finally:
        stream.Dispose()
