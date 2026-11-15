# -*- coding: utf-8 -*-
"""RevoBIM PY - Filter Manager : a minimal Excel reader and writer.

Office Open XML written straight into a zip, with no Excel and no installed
package. The XML building and parsing are plain string work so the bench can
test them; only the zip itself needs .NET.

The parser is deliberately tolerant: Excel rewrites a file it has saved, so
what comes back is not what went out. Values arrive as shared strings rather
than inline ones, empty cells are dropped entirely, and rows are numbered
rather than ordered.
"""

import re

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


# ---------------------------------------------------------------------------
#  Column letters
# ---------------------------------------------------------------------------
def column_letter(index):
    """0 -> A, 25 -> Z, 26 -> AA."""
    letters = ""
    index = int(index)
    while True:
        letters = chr(ord("A") + (index % 26)) + letters
        index = index // 26 - 1
        if index < 0:
            break
    return letters


def column_index(letters):
    """A -> 0, Z -> 25, AA -> 26."""
    total = 0
    for char in str(letters).upper():
        if not ("A" <= char <= "Z"):
            continue
        total = total * 26 + (ord(char) - ord("A") + 1)
    return total - 1


# ---------------------------------------------------------------------------
#  Escaping
# ---------------------------------------------------------------------------
def escape(text):
    if text is None:
        return ""
    out = u"{0}".format(text)
    out = out.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    out = out.replace('"', "&quot;")
    # control characters are not legal in XML at all
    return "".join(c for c in out if c >= " " or c in "\t\n")


def unescape(text):
    if text is None:
        return ""
    out = u"{0}".format(text)
    out = out.replace("&lt;", "<").replace("&gt;", ">")
    out = out.replace("&quot;", '"').replace("&apos;", "'")
    return out.replace("&amp;", "&")


# ---------------------------------------------------------------------------
#  Writing
# ---------------------------------------------------------------------------
# the style ids styles.xml declares, in order
STYLE_PLAIN = 0
STYLE_HEADER = 1
STYLE_LOCKED = 2
STYLE_EDITABLE = 3
STYLE_NOTE = 4
STYLE_CATEGORY = 5
STYLE_RULE = 6
STYLE_DARK = 7
STYLE_DARK_TITLE = 8


def sheet_xml(rows, widths=None, header_rows=1, freeze=True, styles=None,
              validations=None):
    """The worksheet part.

    styles is an optional grid the same shape as rows, holding the style id
    for each cell, so a sheet can show at a glance which cells are meant to
    be edited and which are keys.
    """
    out = []
    out.append('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>')
    out.append('<worksheet xmlns="{0}">'.format(NS))

    if freeze and header_rows:
        out.append('<sheetViews><sheetView workbookViewId="0">'
                   '<pane ySplit="{0}" topLeftCell="A{1}" '
                   'activePane="bottomLeft" state="frozen"/>'
                   '</sheetView></sheetViews>'.format(header_rows,
                                                      header_rows + 1))

    if widths:
        out.append("<cols>")
        for index, width in enumerate(widths):
            out.append('<col min="{0}" max="{0}" width="{1}" '
                       'customWidth="1"/>'.format(index + 1, width))
        out.append("</cols>")

    out.append("<sheetData>")
    for row_index, row in enumerate(rows):
        number = row_index + 1
        out.append('<row r="{0}">'.format(number))
        for col_index, value in enumerate(row):
            style = STYLE_PLAIN
            if styles is not None and row_index < len(styles) \
                    and col_index < len(styles[row_index]):
                style = styles[row_index][col_index]
            elif row_index < header_rows:
                style = STYLE_HEADER

            blank = value is None or value == ""
            if blank and style == STYLE_PLAIN:
                continue

            attrs = ' s="{0}"'.format(style) if style else ""
            if blank:
                out.append('<c r="{0}{1}"{2}/>'.format(
                    column_letter(col_index), number, attrs))
            else:
                out.append('<c r="{0}{1}" t="inlineStr"{2}>'
                           '<is><t xml:space="preserve">{3}</t></is></c>'.format(
                               column_letter(col_index), number, attrs,
                               escape(value)))
        out.append("</row>")
    out.append("</sheetData>")

    if validations:
        out.append('<dataValidations count="{0}">'.format(len(validations)))
        for sqref, formula in validations:
            # showErrorMessage is off on purpose: the lists are a guide, and
            # a name Excel does not know about should still be typeable
            out.append('<dataValidation type="list" allowBlank="1" '
                       'showInputMessage="1" showErrorMessage="0" '
                       'sqref="{0}"><formula1>{1}</formula1>'
                       '</dataValidation>'.format(escape(sqref),
                                                  escape(formula)))
        out.append("</dataValidations>")

    out.append("</worksheet>")
    return "".join(out)


def workbook_parts(sheets):
    """Every part of the file, as {path inside the zip: text}.

    sheets is a list of dicts: name, rows, and optionally widths,
    header_rows, styles and validations.
    """
    if isinstance(sheets, dict):
        sheets = [sheets]

    parts = {}
    overrides = []
    rels = []
    entries = []
    for index, sheet in enumerate(sheets):
        number = index + 1
        path = "xl/worksheets/sheet{0}.xml".format(number)
        parts[path] = sheet_xml(sheet.get("rows") or [],
                                sheet.get("widths"),
                                sheet.get("header_rows", 1),
                                sheet.get("freeze", True),
                                sheet.get("styles"),
                                sheet.get("validations"))
        overrides.append(
            '<Override PartName="/{0}" ContentType="application/vnd.'
            'openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'.format(
                path))
        rels.append(
            '<Relationship Id="rId{0}" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet{0}.xml"/>'.format(number))
        entries.append('<sheet name="{0}" sheetId="{1}" r:id="rId{1}"/>'.format(
            escape(sheet.get("name", "Sheet{0}".format(number)))[:31], number))

    style_rel = len(sheets) + 1
    rels.append(
        '<Relationship Id="rId{0}" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'.format(style_rel))

    parts["[Content_Types].xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
        'content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats'
        '-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.'
        'openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        + "".join(overrides) +
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.'
        'openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '</Types>')

    parts["_rels/.rels"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
        'relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/></Relationships>')

    parts["xl/workbook.xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="{0}" xmlns:r="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships"><sheets>{1}</sheets></workbook>'.format(
            NS, "".join(entries)))

    parts["xl/_rels/workbook.xml.rels"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
        'relationships">' + "".join(rels) + '</Relationships>')

    parts["xl/styles.xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="{0}">'
        '<fonts count="5">'
        '<font><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Calibri"/></font>'
        '<font><color rgb="FF808080"/><sz val="11"/><name val="Calibri"/></font>'
        '<font><i/><color rgb="FF808080"/><sz val="11"/><name val="Calibri"/></font>'
        '<font><color rgb="FFE4E4E4"/><sz val="11"/><name val="Calibri"/></font>'
        '</fonts>'
        '<fills count="8">'
        '<fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid">'
        '<fgColor rgb="FF1F4E2C"/><bgColor indexed="64"/></patternFill></fill>'
        '<fill><patternFill patternType="solid">'
        '<fgColor rgb="FFD9D9D9"/><bgColor indexed="64"/></patternFill></fill>'
        '<fill><patternFill patternType="solid">'
        '<fgColor rgb="FFFFE08A"/><bgColor indexed="64"/></patternFill></fill>'
        '<fill><patternFill patternType="solid">'
        '<fgColor rgb="FF6FAEE2"/><bgColor indexed="64"/></patternFill></fill>'
        '<fill><patternFill patternType="solid">'
        '<fgColor rgb="FF8FD3A3"/><bgColor indexed="64"/></patternFill></fill>'
        '<fill><patternFill patternType="solid">'
        '<fgColor rgb="FF2B2B2E"/><bgColor indexed="64"/></patternFill></fill>'
        '</fills>'
        '<borders count="2"><border/>'
        '<border><left style="thin"><color rgb="FFD0D0D0"/></left>'
        '<right style="thin"><color rgb="FFD0D0D0"/></right>'
        '<top style="thin"><color rgb="FFD0D0D0"/></top>'
        '<bottom style="thin"><color rgb="FFD0D0D0"/></bottom></border>'
        '</borders>'
        '<cellStyleXfs count="1"><xf/></cellStyleXfs>'
        '<cellXfs count="9">'
        '<xf xfId="0"/>'
        '<xf xfId="0" fontId="1" fillId="2" borderId="1" applyFont="1" '
        'applyFill="1" applyBorder="1"><alignment vertical="center"/></xf>'
        '<xf xfId="0" fontId="2" fillId="3" borderId="1" applyFont="1" '
        'applyFill="1" applyBorder="1"/>'
        '<xf xfId="0" fillId="4" borderId="1" applyFill="1" applyBorder="1"/>'
        '<xf xfId="0" fontId="3" applyFont="1"/>'
        '<xf xfId="0" fillId="5" borderId="1" applyFill="1" applyBorder="1"/>'
        '<xf xfId="0" fillId="6" borderId="1" applyFill="1" applyBorder="1"/>'
        '<xf xfId="0" fontId="4" fillId="7" applyFont="1" applyFill="1"><alignment vertical="center" wrapText="1"/></xf>'
        '<xf xfId="0" fontId="1" fillId="7" applyFont="1" applyFill="1"><alignment vertical="center"/></xf>'
        '</cellXfs>'
        '</styleSheet>'.format(NS))

    return parts


# ---------------------------------------------------------------------------
#  Parsing
# ---------------------------------------------------------------------------
_ROW = re.compile(r"<row[^>]*?\br=\"(\d+)\"[^>]*?>(.*?)</row>", re.S)
_ROW_EMPTY = re.compile(r"<row[^>]*?\br=\"(\d+)\"[^>]*?/>", re.S)
_CELL = re.compile(r"<c\b([^>]*?)(?:/>|>(.*?)</c>)", re.S)
_REF = re.compile(r"\br=\"([A-Z]+)(\d+)\"")
_TYPE = re.compile(r"\bt=\"([^\"]+)\"")
_V = re.compile(r"<v[^>]*>(.*?)</v>", re.S)
_IS_T = re.compile(r"<t[^>]*>(.*?)</t>", re.S)
_SI = re.compile(r"<si\b[^>]*>(.*?)</si>", re.S)


def shared_strings(text):
    """The shared string table, in order. Excel writes one after editing."""
    if not text:
        return []
    out = []
    for body in _SI.findall(text):
        out.append("".join(unescape(part) for part in _IS_T.findall(body)))
    return out


def parse_sheet(text, strings=None):
    """A worksheet as a list of rows, each a list of cell strings.

    Missing cells are filled in, because Excel simply leaves out any cell
    that is empty, and missing rows are filled in too.
    """
    strings = strings or []
    if not text:
        return []

    found = {}
    widest = 0
    for number, body in _ROW.findall(text):
        cells = {}
        for attrs, inner in _CELL.findall(body):
            ref = _REF.search(attrs)
            if ref is None:
                continue
            col = column_index(ref.group(1))
            kind = _TYPE.search(attrs)
            kind = kind.group(1) if kind else ""

            value = ""
            if kind == "inlineStr":
                parts = _IS_T.findall(inner or "")
                value = "".join(unescape(p) for p in parts)
            else:
                raw = _V.search(inner or "")
                raw = unescape(raw.group(1)) if raw else ""
                if kind == "s":
                    try:
                        value = strings[int(raw)]
                    except Exception:
                        value = ""
                else:
                    value = raw
            cells[col] = value
            widest = max(widest, col + 1)
        found[int(number)] = cells

    for number in _ROW_EMPTY.findall(text):
        found.setdefault(int(number), {})

    if not found:
        return []

    rows = []
    for number in range(1, max(found.keys()) + 1):
        cells = found.get(number, {})
        rows.append([cells.get(i, "") for i in range(widest)])
    return rows


# ---------------------------------------------------------------------------
#  The zip, which is the only part that needs .NET
# ---------------------------------------------------------------------------
def write_workbook(path, sheets):
    """Write an .xlsx. sheets is one sheet dict or a list of them."""
    import fm_clr  # noqa
    from System.IO import FileStream, FileMode, FileAccess, StreamWriter
    from System.IO.Compression import ZipArchive, ZipArchiveMode

    parts = workbook_parts(sheets)

    stream = FileStream(path, FileMode.Create, FileAccess.Write)
    try:
        archive = ZipArchive(stream, ZipArchiveMode.Create)
        try:
            for name in sorted(parts):
                entry = archive.CreateEntry(name)
                writer = StreamWriter(entry.Open())
                try:
                    writer.Write(parts[name])
                finally:
                    writer.Dispose()
        finally:
            archive.Dispose()
    finally:
        stream.Dispose()
    return path


def read_workbook(path):
    """The first worksheet of an .xlsx, as a list of rows."""
    import fm_clr  # noqa
    from System.IO import FileStream, FileMode, FileAccess, StreamReader
    from System.IO.Compression import ZipArchive, ZipArchiveMode

    sheet = ""
    strings_text = ""

    stream = FileStream(path, FileMode.Open, FileAccess.Read)
    try:
        archive = ZipArchive(stream, ZipArchiveMode.Read)
        try:
            sheet = _entry_text(archive, "xl/worksheets/sheet1.xml")
            if not sheet:
                for entry in archive.Entries:
                    if entry.FullName.startswith("xl/worksheets/") \
                            and entry.FullName.endswith(".xml"):
                        sheet = _read_entry(entry)
                        break
            strings_text = _entry_text(archive, "xl/sharedStrings.xml")
        finally:
            archive.Dispose()
    finally:
        stream.Dispose()

    return parse_sheet(sheet, shared_strings(strings_text))


def _entry_text(archive, name):
    try:
        entry = archive.GetEntry(name)
    except Exception:
        entry = None
    return _read_entry(entry) if entry is not None else ""


def _read_entry(entry):
    from System.IO import StreamReader
    reader = StreamReader(entry.Open())
    try:
        return reader.ReadToEnd()
    finally:
        reader.Dispose()
