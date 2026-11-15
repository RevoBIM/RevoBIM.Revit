# -*- coding: utf-8 -*-
"""The Excel export, built as Office Open XML text.

Pure Python - no clr, no System, no Autodesk - so the bench can build a
workbook, zip it with CPython and check it against the rules Excel enforces.
msm_ui.write_xlsx does the one .NET part: zipping these parts to disk.

Rules followed (see the RevoBIM table reference):
- the children of <worksheet> in schema order: sheetPr, dimension, sheetViews,
  sheetFormatPr, cols, sheetData, autoFilter, pageMargins, pageSetup - Excel
  repairs a file that
  breaks the order even when lenient readers open it fine
- tab names unique after the 31 character cut, none of []:*?/\\ in them
- exactly one tab selected
- inline strings, so there is no shared string table to keep in step
- numbers written as numbers
"""
import re

import msm_core as core

# cellXfs, in order - the index is the s="" on a cell
S_DEFAULT, S_HEAD, S_TEXT, S_INT, S_DEC, S_FTEXT, S_FINT, S_FDEC, S_FCHECK, \
    S_TTEXT, S_TINT, S_TDEC = range(12)

_BAD_SHEET = re.compile(u"[\\[\\]:*?/\\\\]")
_BAD_XML = re.compile(u"[\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f]")


def col_letter(number):
    """1 -> A, 26 -> Z, 27 -> AA."""
    out = u""
    while number > 0:
        number, rest = divmod(number - 1, 26)
        out = u"ABCDEFGHIJKLMNOPQRSTUVWXYZ"[rest] + out
    return out


def esc(text):
    text = _BAD_XML.sub(u"", u"{0}".format(text))
    return (text.replace(u"&", u"&amp;").replace(u"<", u"&lt;")
            .replace(u">", u"&gt;").replace(u'"', u"&quot;"))


def sheet_names(names):
    """Legal, unique tab names: bad characters out, cut to 31, and a clash
    after the cut numbered rather than left for Excel to refuse."""
    out = []
    seen = set()
    for name in names:
        base = _BAD_SHEET.sub(u" ", u"{0}".format(name or u"")).strip().strip(u"'") or u"Sheet"
        candidate = base[:31]
        number = 2
        while candidate.lower() in seen:
            suffix = u" ({0})".format(number)
            candidate = base[:31 - len(suffix)] + suffix
            number += 1
        seen.add(candidate.lower())
        out.append(candidate)
    return out


class Sheet(object):
    def __init__(self, name, columns, rows, freeze=True, autofilter=True):
        self.name = name
        self.columns = columns      # [(title, width)]
        self.rows = rows            # [[(value, style)]]
        self.freeze = freeze
        self.autofilter = autofilter


def _cell(ref, value, style):
    if value is None or value == u"":
        return u'<c r="{0}" s="{1}"/>'.format(ref, style)
    if isinstance(value, bool):
        value = u"Yes" if value else u"No"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value != value:          # NaN
            return u'<c r="{0}" s="{1}"/>'.format(ref, style)
        return u'<c r="{0}" s="{1}"><v>{2}</v></c>'.format(ref, style, repr(value)
                                                            if isinstance(value, float)
                                                            else value)
    return (u'<c r="{0}" s="{1}" t="inlineStr"><is><t xml:space="preserve">{2}</t>'
            u'</is></c>').format(ref, style, esc(value))


def sheet_xml(sheet, selected):
    width = max(1, len(sheet.columns))
    height = 1 + len(sheet.rows)
    last = u"{0}{1}".format(col_letter(width), height)
    parts = [u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
             u'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
             u'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">',
             # printed A4 landscape, fitted to one page wide
             u'<sheetPr><pageSetUpPr fitToPage="1"/></sheetPr>',
             u'<dimension ref="A1:{0}"/>'.format(last)]
    view = u'<sheetView workbookViewId="0"{0}>'.format(u' tabSelected="1"' if selected else u"")
    if sheet.freeze and sheet.rows:
        view += (u'<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
                 u'<selection pane="bottomLeft" activeCell="A2" sqref="A2"/>')
    view += u"</sheetView>"
    parts.append(u"<sheetViews>{0}</sheetViews>".format(view))
    parts.append(u'<sheetFormatPr defaultRowHeight="15"/>')
    cols = [u'<col min="{0}" max="{0}" width="{1}" customWidth="1"/>'.format(i + 1, w)
            for i, (_title, w) in enumerate(sheet.columns)]
    if cols:
        parts.append(u"<cols>{0}</cols>".format(u"".join(cols)))
    rows = [u'<row r="1">' + u"".join(
        [_cell(u"{0}1".format(col_letter(i + 1)), title, S_HEAD)
         for i, (title, _w) in enumerate(sheet.columns)]) + u"</row>"]
    for r, row in enumerate(sheet.rows):
        number = r + 2
        cells = [_cell(u"{0}{1}".format(col_letter(i + 1), number), value, style)
                 for i, (value, style) in enumerate(row)]
        rows.append(u'<row r="{0}">{1}</row>'.format(number, u"".join(cells)))
    parts.append(u"<sheetData>{0}</sheetData>".format(u"".join(rows)))
    if sheet.autofilter and sheet.rows:
        parts.append(u'<autoFilter ref="A1:{0}"/>'.format(last))
    parts.append(u'<pageMargins left="0.5" right="0.5" top="0.6" bottom="0.6" '
                 u'header="0.3" footer="0.3"/>')
    parts.append(u'<pageSetup paperSize="9" orientation="landscape" fitToWidth="1" '
                 u'fitToHeight="0"/>')
    parts.append(u"</worksheet>")
    return u"".join(parts)


STYLES = (
    u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    u'<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    u'<numFmts count="1"><numFmt numFmtId="164" formatCode="0.0"/></numFmts>'
    u'<fonts count="4">'
    u'<font><sz val="11"/><name val="Calibri"/></font>'
    u'<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>'
    u'<font><b/><sz val="11"/><color rgb="FFC0392B"/><name val="Calibri"/></font>'
    u'<font><b/><sz val="11"/><name val="Calibri"/></font>'
    u'</fonts>'
    u'<fills count="5">'
    u'<fill><patternFill patternType="none"/></fill>'
    u'<fill><patternFill patternType="gray125"/></fill>'
    u'<fill><patternFill patternType="solid"><fgColor rgb="FF1B72BE"/><bgColor indexed="64"/></patternFill></fill>'
    u'<fill><patternFill patternType="solid"><fgColor rgb="FFFBE4E2"/><bgColor indexed="64"/></patternFill></fill>'
    u'<fill><patternFill patternType="solid"><fgColor rgb="FFE8EEF4"/><bgColor indexed="64"/></patternFill></fill>'
    u'</fills>'
    u'<borders count="2">'
    u'<border><left/><right/><top/><bottom/><diagonal/></border>'
    u'<border><left style="thin"><color rgb="FFD0D0D0"/></left><right style="thin"><color rgb="FFD0D0D0"/></right>'
    u'<top style="thin"><color rgb="FFD0D0D0"/></top><bottom style="thin"><color rgb="FFD0D0D0"/></bottom><diagonal/></border>'
    u'</borders>'
    u'<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    u'<cellXfs count="12">'
    u'<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    u'<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1"/>'
    u'<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1"/>'
    u'<xf numFmtId="1" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1"/>'
    u'<xf numFmtId="164" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1"/>'
    u'<xf numFmtId="0" fontId="0" fillId="3" borderId="1" xfId="0" applyFill="1" applyBorder="1"/>'
    u'<xf numFmtId="1" fontId="0" fillId="3" borderId="1" xfId="0" applyNumberFormat="1" applyFill="1" applyBorder="1"/>'
    u'<xf numFmtId="164" fontId="0" fillId="3" borderId="1" xfId="0" applyNumberFormat="1" applyFill="1" applyBorder="1"/>'
    u'<xf numFmtId="0" fontId="2" fillId="3" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1"/>'
    u'<xf numFmtId="0" fontId="3" fillId="4" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1"/>'
    u'<xf numFmtId="1" fontId="3" fillId="4" borderId="1" xfId="0" applyNumberFormat="1" applyFont="1" applyFill="1" applyBorder="1"/>'
    u'<xf numFmtId="164" fontId="3" fillId="4" borderId="1" xfId="0" applyNumberFormat="1" applyFont="1" applyFill="1" applyBorder="1"/>'
    u'</cellXfs>'
    u'<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    u'</styleSheet>')


def build_parts(sheets):
    """[Sheet] -> [(path in the zip, xml text)], [Content_Types].xml first."""
    names = sheet_names([s.name for s in sheets])
    count = len(sheets)
    content = [u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
               u'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
               u'<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
               u'<Default Extension="xml" ContentType="application/xml"/>',
               u'<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
               u'<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>']
    for i in range(count):
        content.append(u'<Override PartName="/xl/worksheets/sheet{0}.xml" ContentType='
                       u'"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                       .format(i + 1))
    content.append(u"</Types>")

    root_rels = (u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 u'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 u'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                 u'relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')

    book = [u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            u'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            u'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">',
            u'<bookViews><workbookView activeTab="0"/></bookViews><sheets>']
    for i, name in enumerate(names):
        book.append(u'<sheet name="{0}" sheetId="{1}" r:id="rId{1}"/>'.format(esc(name), i + 1))
    book.append(u"</sheets>")
    defined = []
    for i, sheet in enumerate(sheets):
        if sheet.autofilter and sheet.rows:
            defined.append(u'<definedName name="_xlnm._FilterDatabase" localSheetId="{0}" '
                           u'hidden="1">\'{1}\'!$A$1:${2}${3}</definedName>'.format(
                               i, esc(names[i]).replace(u"'", u"''"),
                               col_letter(max(1, len(sheet.columns))), 1 + len(sheet.rows)))
    if defined:
        book.append(u"<definedNames>{0}</definedNames>".format(u"".join(defined)))
    book.append(u"</workbook>")

    rels = [u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            u'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">']
    for i in range(count):
        rels.append(u'<Relationship Id="rId{0}" Type="http://schemas.openxmlformats.org/'
                    u'officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{0}.xml"/>'
                    .format(i + 1))
    rels.append(u'<Relationship Id="rId{0}" Type="http://schemas.openxmlformats.org/'
                u'officeDocument/2006/relationships/styles" Target="styles.xml"/>'.format(count + 1))
    rels.append(u"</Relationships>")

    parts = [(u"[Content_Types].xml", u"".join(content)),
             (u"_rels/.rels", root_rels),
             (u"xl/workbook.xml", u"".join(book)),
             (u"xl/_rels/workbook.xml.rels", u"".join(rels)),
             (u"xl/styles.xml", STYLES)]
    for i, sheet in enumerate(sheets):
        parts.append((u"xl/worksheets/sheet{0}.xml".format(i + 1), sheet_xml(sheet, i == 0)))
    return parts


# ============================================================
# the MEP System Manager workbook
# ============================================================

def _num(value):
    try:
        return float(value)
    except Exception:
        return None


def system_sheets(groups, checks=True, domain=u"pipe"):
    """[(service, rows as shown)] -> [Sheet]: the rows first, then a summary
    per service with a total line. With checks off, the Checks column and the
    rows-needing-a-look column are left out and nothing is washed red."""
    titles = core.field_titles(domain)
    columns = [(u"Service", 26), (titles[u"system"], 22),
               (titles[u"ptype"], 30), (titles[u"size"], 11),
               (titles[u"count"], 9), (titles[u"length"], 11),
               (titles[u"fittings"], 10)]
    if checks:
        columns.append((titles[u"check"], 52))
    rows = []
    for service, service_rows in groups:
        for row in service_rows:
            flag = bool(row.get(u"flag")) and checks
            text, whole, dec = ((S_FTEXT, S_FINT, S_FDEC) if flag
                                else (S_TEXT, S_INT, S_DEC))
            size = core.size_number(row.get(u"size"))
            line = [
                (service, text),
                (row.get(u"system") or u"", text),
                (row.get(u"ptype") or u"", text),
                (size if size is not None else (row.get(u"size") or u""),
                 whole if size is not None and size == int(size) else
                 (dec if size is not None else text)),
                (int(row.get(u"count") or 0), whole),
                (_num(row.get(u"length")), dec),
                (int(row.get(u"fittings") or 0), whole),
            ]
            if checks:
                line.append((row.get(u"check") or u"", S_FCHECK if flag else text))
            rows.append(line)
    detail = Sheet(core.domain_info(domain)[u"export"], columns, rows)

    summary_cols = [(u"Service", 26), (u"Rows", 8),
                    (core.domain_info(domain)[u"noun"][1].capitalize(), 11), (u"Length (m)", 11),
                    (u"Runs" if domain == u"cont" else u"Systems", 9), (u"Fittings", 10)]
    if checks:
        summary_cols.append((u"Rows needing a look", 20))
    lines = core.export_summary(groups)
    summary_rows = []
    for line in lines:
        flagged = line[u"flagged"] if checks else 0
        text, whole, dec = ((S_FTEXT, S_FINT, S_FDEC) if flagged
                            else (S_TEXT, S_INT, S_DEC))
        cells = [(line[u"service"], text), (line[u"rows"], whole),
                 (line[u"pipes"], whole), (line[u"length_m"], dec),
                 (line[u"systems"], whole), (line[u"fittings"], whole)]
        if checks:
            cells.append((flagged, whole))
        summary_rows.append(cells)
    if lines:
        all_rows = [r for _s, rs in groups for r in rs]
        total = core.export_summary([(u"Total", all_rows)])[0]
        cells = [(u"Total", S_TTEXT), (total[u"rows"], S_TINT),
                 (total[u"pipes"], S_TINT), (total[u"length_m"], S_TDEC),
                 (total[u"systems"], S_TINT), (total[u"fittings"], S_TINT)]
        if checks:
            cells.append((total[u"flagged"], S_TINT))
        summary_rows.append(cells)
    summary = Sheet(u"Summary", summary_cols, summary_rows, autofilter=False)
    return [detail, summary]

