# -*- coding: utf-8 -*-
"""A minimal .xlsx writer and reader.

Written straight out as Office Open XML into a zip through
System.IO.Compression - no Excel, no installed package, and it reads back
whatever Excel saves (shared strings, inline strings, numbers) into plain rows
of text. The same idea as Drawing Register's writer, cut down to one sheet.
"""

import shtm_clr  # noqa: F401  - references the assemblies first

import os
import re

from System.IO import File, FileMode, StreamReader
from System.IO.Compression import ZipArchive, ZipArchiveMode
from System.Text import Encoding
from System.Xml import XmlDocument, XmlNamespaceManager

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"


# ====================== writing ======================

def write(path, rows, sheet_name=u"Sheets"):
    """rows: a list of lists of text, header first. Returns the path."""
    if os.path.isfile(path):
        os.remove(path)
    stream = File.Open(path, FileMode.Create)
    try:
        archive = ZipArchive(stream, ZipArchiveMode.Create)
        try:
            _put(archive, "[Content_Types].xml", _content_types())
            _put(archive, "_rels/.rels", _root_rels())
            _put(archive, "xl/workbook.xml", _workbook(sheet_name))
            _put(archive, "xl/_rels/workbook.xml.rels", _workbook_rels())
            _put(archive, "xl/styles.xml", _styles())
            _put(archive, "xl/worksheets/sheet1.xml", _sheet(rows))
        finally:
            archive.Dispose()
    finally:
        stream.Close()
    return path


def _put(archive, name, text):
    entry = archive.CreateEntry(name)
    out = entry.Open()
    try:
        data = Encoding.UTF8.GetBytes(text)
        out.Write(data, 0, data.Length)
    finally:
        out.Close()


def _esc(text):
    text = u"{0}".format(text if text is not None else u"")
    return (text.replace(u"&", u"&amp;").replace(u"<", u"&lt;")
            .replace(u">", u"&gt;").replace(u"\"", u"&quot;"))


def column_letter(index):
    """0 -> A, 25 -> Z, 26 -> AA."""
    letters = u""
    index += 1
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _sheet(rows):
    width = max([len(r) for r in rows]) if rows else 1
    parts = [u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
             u'<worksheet xmlns="{0}" xmlns:r="{1}">'.format(NS_MAIN, NS_REL),
             u'<sheetViews><sheetView workbookViewId="0">'
             u'<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
             u'</sheetView></sheetViews>',
             u'<cols>']
    for index in range(width):
        longest = 8
        for row in rows[:200]:
            if index < len(row):
                longest = max(longest, len(u"{0}".format(row[index] or u"")))
        parts.append(u'<col min="{0}" max="{0}" width="{1}" customWidth="1"/>'.format(
            index + 1, min(60, longest + 2)))
    parts.append(u'</cols><sheetData>')
    for row_index, row in enumerate(rows):
        parts.append(u'<row r="{0}">'.format(row_index + 1))
        style = u' s="1"' if row_index == 0 else u""
        for col_index, value in enumerate(row):
            ref = u"{0}{1}".format(column_letter(col_index), row_index + 1)
            parts.append(u'<c r="{0}" t="inlineStr"{1}><is><t xml:space="preserve">{2}</t></is></c>'
                         .format(ref, style, _esc(value)))
        parts.append(u'</row>')
    parts.append(u'</sheetData>')
    if rows:
        parts.append(u'<autoFilter ref="A1:{0}{1}"/>'.format(
            column_letter(width - 1), len(rows)))
    parts.append(u'</worksheet>')
    return u"".join(parts)


def _content_types():
    return (u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            u'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            u'<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            u'<Default Extension="xml" ContentType="application/xml"/>'
            u'<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            u'<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            u'<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            u'</Types>')


def _root_rels():
    return (u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            u'<Relationships xmlns="{0}">'
            u'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            u'</Relationships>').format(NS_PKG)


def _workbook(sheet_name):
    return (u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            u'<workbook xmlns="{0}" xmlns:r="{1}">'
            u'<sheets><sheet name="{2}" sheetId="1" r:id="rId1"/></sheets>'
            u'</workbook>').format(NS_MAIN, NS_REL, _esc(sheet_name[:31]))


def _workbook_rels():
    return (u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            u'<Relationships xmlns="{0}">'
            u'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            u'<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            u'</Relationships>').format(NS_PKG)


def _styles():
    return (u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            u'<styleSheet xmlns="{0}">'
            u'<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
            u'<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
            u'<fills count="2"><fill><patternFill patternType="none"/></fill>'
            u'<fill><patternFill patternType="gray125"/></fill></fills>'
            u'<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
            u'<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            u'<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
            u'<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
            u'</styleSheet>').format(NS_MAIN)


# ====================== reading ======================

def read(path):
    """The first worksheet as rows of text. Blank cells come back as empty
    strings so every row is as wide as the widest cell it holds."""
    stream = File.Open(path, FileMode.Open)
    try:
        archive = ZipArchive(stream, ZipArchiveMode.Read)
        try:
            shared = _shared_strings(archive)
            target = _first_sheet_target(archive)
            text = _entry_text(archive, target)
            if text is None:
                return []
            return _parse_sheet(text, shared)
        finally:
            archive.Dispose()
    finally:
        stream.Close()


def _entry_text(archive, name):
    entry = archive.GetEntry(name)
    if entry is None:
        return None
    stream = entry.Open()
    try:
        reader = StreamReader(stream, Encoding.UTF8)
        try:
            return reader.ReadToEnd()
        finally:
            reader.Close()
    finally:
        stream.Close()


def _manager(document):
    manager = XmlNamespaceManager(document.NameTable)
    manager.AddNamespace("m", NS_MAIN)
    manager.AddNamespace("r", NS_REL)
    manager.AddNamespace("p", NS_PKG)
    return manager


def _shared_strings(archive):
    text = _entry_text(archive, "xl/sharedStrings.xml")
    if not text:
        return []
    document = XmlDocument()
    document.LoadXml(text)
    manager = _manager(document)
    out = []
    for item in document.SelectNodes("//m:sst/m:si", manager):
        pieces = []
        for node in item.SelectNodes(".//m:t", manager):
            pieces.append(node.InnerText or u"")
        out.append(u"".join(pieces))
    return out


def _first_sheet_target(archive):
    """Follow workbook.xml to its first sheet through the rels, and fall back
    to the conventional name when either is missing."""
    try:
        workbook = XmlDocument()
        workbook.LoadXml(_entry_text(archive, "xl/workbook.xml") or u"")
        manager = _manager(workbook)
        sheet = workbook.SelectSingleNode("//m:sheets/m:sheet", manager)
        rel_id = sheet.GetAttribute("id", NS_REL)
        rels = XmlDocument()
        rels.LoadXml(_entry_text(archive, "xl/_rels/workbook.xml.rels") or u"")
        rels_manager = _manager(rels)
        for rel in rels.SelectNodes("//p:Relationship", rels_manager):
            if rel.GetAttribute("Id") == rel_id:
                target = rel.GetAttribute("Target")
                if target.startswith("/"):
                    return target[1:]
                return "xl/" + target
    except Exception:
        pass
    return "xl/worksheets/sheet1.xml"


def column_index(ref):
    """'C7' -> 2."""
    letters = re.match(r"[A-Z]+", ref or u"")
    if not letters:
        return 0
    index = 0
    for ch in letters.group(0):
        index = index * 26 + (ord(ch) - 64)
    return index - 1


def _parse_sheet(text, shared):
    document = XmlDocument()
    document.LoadXml(text)
    manager = _manager(document)
    rows = []
    for row in document.SelectNodes("//m:sheetData/m:row", manager):
        cells = []
        for cell in row.SelectNodes("m:c", manager):
            index = column_index(cell.GetAttribute("r"))
            while len(cells) <= index:
                cells.append(u"")
            cells[index] = _cell_text(cell, manager, shared)
        rows.append(cells)
    return rows


def _cell_text(cell, manager, shared):
    kind = cell.GetAttribute("t") or u""
    if kind == "inlineStr":
        pieces = []
        for node in cell.SelectNodes(".//m:t", manager):
            pieces.append(node.InnerText or u"")
        return u"".join(pieces)
    value = cell.SelectSingleNode("m:v", manager)
    if value is None:
        return u""
    raw = value.InnerText or u""
    if kind == "s":
        try:
            return shared[int(raw)]
        except Exception:
            return u""
    if kind == "b":
        return u"TRUE" if raw.strip() == "1" else u"FALSE"
    # a number Excel stored as 2100.0 is the drawing number 2100
    if re.match(r"^-?\d+\.0+$", raw):
        return raw.split(".")[0]
    return raw
