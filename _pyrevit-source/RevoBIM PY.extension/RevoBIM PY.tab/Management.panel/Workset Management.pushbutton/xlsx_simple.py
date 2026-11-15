# -*- coding: utf-8 -*-
"""RevoBIM PY - Workset Management : the spreadsheet.

Office Open XML written straight into a zip with System.IO.Compression, and
read back the same way.  No Excel, no installed package, and full control over
fills, borders, column widths and the frozen header row.

Same approach as the Drawing Register's xlsx_writer, with a reader added.
"""

import clr

for _assembly in ("System.IO.Compression",
                  "System.IO.Compression.FileSystem",
                  "System.Xml"):
    try:
        clr.AddReference(_assembly)
    except Exception:
        pass

from System import Array, Byte                              # noqa: E402
from System.IO import MemoryStream, StreamReader            # noqa: E402
from System.IO.Compression import (ZipArchive, ZipArchiveMode,   # noqa: E402
                                   ZipFile, CompressionLevel)
from System.Text import Encoding                            # noqa: E402
from System.Xml import XmlDocument                          # noqa: E402


# ---------------------------------------------------------------- styles
# cellXfs indices used by the caller
STYLE_PLAIN = 0
STYLE_HEADER = 1
STYLE_EXISTING = 2      # orange
STYLE_NEW = 3           # green
STYLE_LOCKED = 4        # grey, read only column
STYLE_NOTE = 5          # italic muted


def _esc(text):
    if text is None:
        return u""
    out = u"{0}".format(text)
    out = out.replace(u"&", u"&amp;").replace(u"<", u"&lt;")
    out = out.replace(u">", u"&gt;").replace(u'"', u"&quot;")
    cleaned = []
    for char in out:
        code = ord(char)
        if code in (9, 10, 13) or code >= 32:
            cleaned.append(char)
    return u"".join(cleaned)


def col_letter(index):
    """1 -> A"""
    letters = u""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


CONTENT_TYPES = u"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"""

ROOT_RELS = u"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

WORKBOOK_RELS = u"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

WORKBOOK = u"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="Worksets" sheetId="1" r:id="rId1"/></sheets>
</workbook>"""

STYLES = u"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="5">
<font><sz val="11"/><name val="Calibri"/></font>
<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>
<font><b/><sz val="11"/><color rgb="FF7A3E00"/><name val="Calibri"/></font>
<font><b/><sz val="11"/><color rgb="FF14532D"/><name val="Calibri"/></font>
<font><i/><sz val="10"/><color rgb="FF6B6B70"/><name val="Calibri"/></font>
</fonts>
<fills count="6">
<fill><patternFill patternType="none"/></fill>
<fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FF232326"/><bgColor indexed="64"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFF6C68B"/><bgColor indexed="64"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFA9E0BC"/><bgColor indexed="64"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFEDEDEF"/><bgColor indexed="64"/></patternFill></fill>
</fills>
<borders count="2">
<border><left/><right/><top/><bottom/><diagonal/></border>
<border><left style="thin"><color rgb="FFB0B0B4"/></left><right style="thin"><color rgb="FFB0B0B4"/></right><top style="thin"><color rgb="FFB0B0B4"/></top><bottom style="thin"><color rgb="FFB0B0B4"/></bottom><diagonal/></border>
</borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="6">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="center"/></xf>
<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment vertical="center"/></xf>
<xf numFmtId="0" fontId="2" fillId="3" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment vertical="center"/></xf>
<xf numFmtId="0" fontId="3" fillId="4" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment vertical="center"/></xf>
<xf numFmtId="0" fontId="0" fillId="5" borderId="1" xfId="0" applyFill="1" applyBorder="1" applyAlignment="1"><alignment vertical="center"/></xf>
<xf numFmtId="0" fontId="4" fillId="0" borderId="0" xfId="0" applyFont="1" applyAlignment="1"><alignment vertical="center"/></xf>
</cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""


def _sheet_xml(rows, widths, freeze_rows=1):
    """rows : list of lists of (text, style index).  None cell = skipped."""
    parts = [u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
             u'<worksheet xmlns="http://schemas.openxmlformats.org/'
             u'spreadsheetml/2006/main">']
    if freeze_rows:
        parts.append(u'<sheetViews><sheetView workbookViewId="0" tabSelected="1">'
                     u'<pane ySplit="{0}" topLeftCell="A{1}" activePane="bottomLeft"'
                     u' state="frozen"/></sheetView></sheetViews>'.format(
                         freeze_rows, freeze_rows + 1))
    parts.append(u'<sheetFormatPr defaultRowHeight="18"/>')
    if widths:
        parts.append(u"<cols>")
        for index, width in enumerate(widths):
            parts.append(u'<col min="{0}" max="{0}" width="{1}" customWidth="1"/>'
                         .format(index + 1, width))
        parts.append(u"</cols>")

    parts.append(u"<sheetData>")
    for row_index, row in enumerate(rows):
        number = row_index + 1
        parts.append(u'<row r="{0}">'.format(number))
        for col_index, cell in enumerate(row):
            if cell is None:
                continue
            text, style = cell
            if text is None:
                text = u""
            reference = u"{0}{1}".format(col_letter(col_index + 1), number)
            parts.append(
                u'<c r="{0}" s="{1}" t="inlineStr"><is><t xml:space="preserve">'
                u'{2}</t></is></c>'.format(reference, style, _esc(text)))
        parts.append(u"</row>")
    parts.append(u"</sheetData></worksheet>")
    return u"".join(parts)


def _add_entry(archive, name, text):
    entry = archive.CreateEntry(name, CompressionLevel.Optimal)
    stream = entry.Open()
    try:
        data = Encoding.UTF8.GetBytes(text)
        stream.Write(data, 0, data.Length)
    finally:
        stream.Close()


def write_workbook(path, rows, widths=None, freeze_rows=1):
    """Write the whole workbook.  Returns (ok, message)."""
    try:
        stream = MemoryStream()
        archive = ZipArchive(stream, ZipArchiveMode.Create, True)
        try:
            _add_entry(archive, "[Content_Types].xml", CONTENT_TYPES)
            _add_entry(archive, "_rels/.rels", ROOT_RELS)
            _add_entry(archive, "xl/workbook.xml", WORKBOOK)
            _add_entry(archive, "xl/_rels/workbook.xml.rels", WORKBOOK_RELS)
            _add_entry(archive, "xl/styles.xml", STYLES)
            _add_entry(archive, "xl/worksheets/sheet1.xml",
                       _sheet_xml(rows, widths or [], freeze_rows))
        finally:
            archive.Dispose()

        data = stream.ToArray()
        stream.Close()

        handle = open(path, "wb")
        try:
            handle.write(bytearray(data))
        finally:
            handle.close()
        return True, ""
    except Exception as err:
        return False, u"{0}".format(err)


# ---------------------------------------------------------------- reading

def _entry_text(archive, name):
    entry = archive.GetEntry(name)
    if entry is None:
        return None
    stream = entry.Open()
    try:
        reader = StreamReader(stream)
        try:
            return reader.ReadToEnd()
        finally:
            reader.Close()
    finally:
        try:
            stream.Close()
        except Exception:
            pass


def _first_sheet_name(archive):
    for entry in archive.Entries:
        name = u"{0}".format(entry.FullName)
        if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"):
            return name
    return None


def _split_reference(reference):
    letters = u""
    digits = u""
    for char in u"{0}".format(reference):
        if char.isdigit():
            digits += char
        else:
            letters += char
    column = 0
    for char in letters.upper():
        column = column * 26 + (ord(char) - 64)
    try:
        row = int(digits)
    except Exception:
        row = 0
    return row, column


def read_sheet(path):
    """Returns (rows, message).  rows is {row number : {column number : text}}
    with 1 based indices.  Handles shared strings, inline strings and numbers,
    because Excel rewrites the file its own way once it has been saved."""
    rows = {}
    archive = None
    try:
        archive = ZipFile.OpenRead(path)
    except Exception as err:
        return rows, u"Could not open the file: {0}".format(err)

    try:
        shared = []
        try:
            shared_text = _entry_text(archive, "xl/sharedStrings.xml")
        except Exception:
            shared_text = None
        if shared_text:
            document = XmlDocument()
            document.LoadXml(shared_text)
            for node in document.GetElementsByTagName("si"):
                pieces = []
                for text_node in node.GetElementsByTagName("t"):
                    pieces.append(u"{0}".format(text_node.InnerText))
                shared.append(u"".join(pieces))

        sheet_name = _first_sheet_name(archive)
        if not sheet_name:
            return rows, "No worksheet found in the workbook."
        sheet_text = _entry_text(archive, sheet_name)
        if not sheet_text:
            return rows, "The worksheet is empty."

        document = XmlDocument()
        document.LoadXml(sheet_text)
        for cell in document.GetElementsByTagName("c"):
            reference = cell.GetAttribute("r")
            row_number, column_number = _split_reference(reference)
            if row_number <= 0 or column_number <= 0:
                continue
            cell_type = u"{0}".format(cell.GetAttribute("t") or "")
            value = u""
            if cell_type == "inlineStr":
                pieces = []
                for text_node in cell.GetElementsByTagName("t"):
                    pieces.append(u"{0}".format(text_node.InnerText))
                value = u"".join(pieces)
            elif cell_type == "s":
                raw = u""
                for value_node in cell.GetElementsByTagName("v"):
                    raw = u"{0}".format(value_node.InnerText)
                    break
                try:
                    index = int(float(raw))
                    if 0 <= index < len(shared):
                        value = shared[index]
                except Exception:
                    value = u""
            else:
                for value_node in cell.GetElementsByTagName("v"):
                    value = u"{0}".format(value_node.InnerText)
                    break
            value = value.strip()
            if row_number not in rows:
                rows[row_number] = {}
            rows[row_number][column_number] = value
        return rows, ""
    except Exception as err:
        return rows, u"Could not read the spreadsheet: {0}".format(err)
    finally:
        try:
            if archive is not None:
                archive.Dispose()
        except Exception:
            pass
