# -*- coding: utf-8 -*-
"""Minimal spreadsheet reader for RevoBIM VlookUp.

Reads .xlsx / .xlsm straight out of the Office Open XML zip using
System.IO.Compression and System.Xml, and .csv / .txt as delimited text.
No Excel, no COM, no installed package - so it works on any machine that
runs Revit, and it does not lock the file while Excel has it open.

Everything comes back as text. Numbers are formatted the way Excel shows
them, dates are converted from their serial number, and blank cells become
empty strings so every row is the same length.
"""

import clr
import os
import re

clr.AddReference('System.Xml')
for _asm in ('System.IO.Compression', 'System.IO.Compression.FileSystem'):
    try:
        clr.AddReference(_asm)
    except Exception:
        pass

from System import DateTime, Array, Byte
from System.IO import (FileStream, FileMode, FileAccess, FileShare,
                       MemoryStream, StreamReader, File)
from System.IO.Compression import ZipArchive, ZipArchiveMode
from System.Text import Encoding
from System.Xml import XmlReader, XmlReaderSettings, XmlNodeType

MAX_ROWS = 60000
MAX_COLS = 512

try:
    TEXT_TYPES = (str, unicode)          # noqa: F821  (IronPython 2.7)
except NameError:
    TEXT_TYPES = (str,)


class SpreadsheetError(Exception):
    pass


class Sheet(object):
    def __init__(self, name):
        self.name = name
        self.rows = []          # list of list of text
        self.truncated = False

    @property
    def width(self):
        w = 0
        for r in self.rows:
            if len(r) > w:
                w = len(r)
        return w


class Workbook(object):
    def __init__(self, path):
        self.path = path
        self.sheets = []
        self.warnings = []
        self.stamp = ''

    def sheet_names(self):
        return [s.name for s in self.sheets]

    def sheet(self, name):
        for s in self.sheets:
            if s.name == name:
                return s
        return None


# ---------------------------------------------------------------- helpers

def column_letter(index):
    """0 -> A, 26 -> AA."""
    n = int(index) + 1
    out = ''
    while n > 0:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out


def column_index(ref):
    """'BC12' -> 54."""
    n = 0
    for ch in ref:
        if 'A' <= ch <= 'Z':
            n = n * 26 + (ord(ch) - 64)
        elif 'a' <= ch <= 'z':
            n = n * 26 + (ord(ch) - 96)
        else:
            break
    return n - 1


def _pad(row, width):
    while len(row) < width:
        row.append(u'')
    return row


def _serial_to_text(value):
    """Excel serial date -> readable text. 1899-12-30 is the 1900 leap bug.

    The serial is parsed as a float first: int('45000.5') throws, which used to
    send every date that carried a time straight back out as a raw serial.
    """
    try:
        number = float(value)
    except Exception:
        return str(value)
    try:
        whole = int(number)
        frac = number - whole
        base = DateTime(1899, 12, 30).AddDays(number)
        if whole == 0:
            return base.ToString('HH:mm:ss')
        if abs(frac) < 1.0 / 86400.0:
            return base.ToString('dd/MM/yyyy')
        return base.ToString('dd/MM/yyyy HH:mm')
    except Exception:
        return str(value)


def _number_text(raw):
    try:
        val = float(raw)
    except Exception:
        return raw
    if abs(val) >= 1e15:
        return str(val)
    if abs(val - round(val)) < 1e-9:
        return str(int(round(val)))
    txt = '{0:.10f}'.format(val)
    txt = txt.rstrip('0').rstrip('.')
    return txt or '0'


# ---------------------------------------------------------------- ooxml

_BUILTIN_DATE_IDS = set(list(range(14, 23)) + [27, 30, 36, 45, 46, 47, 50, 57, 58])


def _entry_text(archive, name):
    lowered = name.lower()
    for entry in archive.Entries:
        if entry.FullName.lower() == lowered:
            stream = entry.Open()
            try:
                reader = StreamReader(stream, Encoding.UTF8)
                return reader.ReadToEnd()
            finally:
                stream.Close()
    return None


def _entry(archive, name):
    lowered = name.lower()
    for entry in archive.Entries:
        if entry.FullName.lower() == lowered:
            return entry
    return None


def _xml_reader(text):
    settings = XmlReaderSettings()
    settings.IgnoreComments = True
    stream = MemoryStream(Encoding.UTF8.GetBytes(text))
    return XmlReader.Create(stream, settings)


def _read_shared_strings(archive):
    text = _entry_text(archive, 'xl/sharedStrings.xml')
    if not text:
        return []
    out = []
    reader = _xml_reader(text)
    buf = []
    in_si = False
    in_t = False
    skip_depth = 0
    try:
        while reader.Read():
            nt = reader.NodeType
            name = reader.LocalName
            if nt == XmlNodeType.Element:
                if name == 'si':
                    in_si = True
                    buf = []
                    if reader.IsEmptyElement:
                        out.append(u'')
                        in_si = False
                elif name == 'rPh':
                    skip_depth += 0 if reader.IsEmptyElement else 1
                elif name == 't' and in_si and skip_depth == 0:
                    in_t = True
                    if reader.IsEmptyElement:
                        in_t = False
            elif nt in (XmlNodeType.Text, XmlNodeType.CDATA,
                        XmlNodeType.SignificantWhitespace, XmlNodeType.Whitespace):
                if in_t:
                    buf.append(reader.Value)
            elif nt == XmlNodeType.EndElement:
                if name == 't':
                    in_t = False
                elif name == 'rPh':
                    skip_depth = max(0, skip_depth - 1)
                elif name == 'si':
                    out.append(u''.join(buf))
                    in_si = False
    finally:
        reader.Close()
    return out


def _read_date_styles(archive):
    """Return a list, one entry per cellXf, True where the format is a date."""
    text = _entry_text(archive, 'xl/styles.xml')
    if not text:
        return []
    custom = {}
    for match in re.finditer(r'<numFmt[^>]*numFmtId="(\d+)"[^>]*formatCode="([^"]*)"', text):
        custom[int(match.group(1))] = match.group(2)
    body = text
    start = body.find('<cellXfs')
    if start < 0:
        return []
    end = body.find('</cellXfs>', start)
    if end < 0:
        end = len(body)
    section = body[start:end]
    out = []
    for match in re.finditer(r'<xf\b[^>]*>', section):
        tag = match.group(0)
        idm = re.search(r'numFmtId="(\d+)"', tag)
        fmt_id = int(idm.group(1)) if idm else 0
        is_date = fmt_id in _BUILTIN_DATE_IDS
        if not is_date and fmt_id in custom:
            code = custom[fmt_id]
            code = re.sub(r'\[[^\]]*\]', '', code)
            code = re.sub(r'"[^"]*"', '', code)
            lowered = code.lower()
            if ('y' in lowered or 'd' in lowered
                    or 'h' in lowered or 's' in lowered
                    or ('m' in lowered and ('/' in lowered or '-' in lowered or ':' in lowered))):
                is_date = True
        out.append(is_date)
    return out


def _read_sheet_map(archive):
    """[(sheet name, part path)] in workbook order."""
    wb_text = _entry_text(archive, 'xl/workbook.xml')
    if not wb_text:
        raise SpreadsheetError('The file has no xl/workbook.xml - it is not an xlsx workbook.')
    rels_text = _entry_text(archive, 'xl/_rels/workbook.xml.rels') or ''
    rels = {}
    for match in re.finditer(r'<Relationship\b[^>]*>', rels_text):
        tag = match.group(0)
        rid = re.search(r'Id="([^"]+)"', tag)
        target = re.search(r'Target="([^"]+)"', tag)
        if rid and target:
            path = target.group(1).replace('\\', '/')
            if path.startswith('/'):
                path = path[1:]
            elif not path.lower().startswith('xl/'):
                path = 'xl/' + path
            rels[rid.group(1)] = path
    out = []
    for match in re.finditer(r'<sheet\b[^>]*>', wb_text):
        tag = match.group(0)
        name = re.search(r'name="([^"]*)"', tag)
        rid = re.search(r'r:id="([^"]+)"', tag)
        if not rid:
            rid = re.search(r'id="([^"]+)"', tag)
        state = re.search(r'state="([^"]*)"', tag)
        if not name or not rid:
            continue
        if state and state.group(1).lower() in ('hidden', 'veryhidden'):
            continue
        path = rels.get(rid.group(1))
        if path:
            out.append((_unescape(name.group(1)), path))
    return out


def _unescape(text):
    return (text.replace('&lt;', '<').replace('&gt;', '>')
                .replace('&quot;', '"').replace('&apos;', "'")
                .replace('&amp;', '&'))


def _read_worksheet(archive, part, name, shared, date_styles):
    sheet = Sheet(name)
    entry = _entry(archive, part)
    if entry is None:
        return sheet
    stream = entry.Open()
    settings = XmlReaderSettings()
    settings.IgnoreComments = True
    reader = XmlReader.Create(stream, settings)

    row_cells = {}
    cell_col = -1
    cell_type = None
    cell_style = -1
    buf = []
    in_value = False
    in_formula = False
    row_count = 0
    try:
        while reader.Read():
            nt = reader.NodeType
            name_ = reader.LocalName
            if nt == XmlNodeType.Element:
                if name_ == 'row':
                    row_cells = {}
                elif name_ == 'c':
                    ref = reader.GetAttribute('r')
                    cell_col = column_index(ref) if ref else (max(row_cells.keys()) + 1 if row_cells else 0)
                    cell_type = reader.GetAttribute('t')
                    style_attr = reader.GetAttribute('s')
                    try:
                        cell_style = int(style_attr) if style_attr else -1
                    except Exception:
                        cell_style = -1
                    buf = []
                    if reader.IsEmptyElement:
                        cell_col = -1
                elif name_ == 'f':
                    in_formula = not reader.IsEmptyElement
                elif name_ in ('v', 't'):
                    in_value = not reader.IsEmptyElement
            elif nt in (XmlNodeType.Text, XmlNodeType.CDATA,
                        XmlNodeType.SignificantWhitespace, XmlNodeType.Whitespace):
                if in_value and not in_formula:
                    buf.append(reader.Value)
            elif nt == XmlNodeType.EndElement:
                if name_ in ('v', 't'):
                    in_value = False
                elif name_ == 'f':
                    in_formula = False
                elif name_ == 'c':
                    if cell_col >= 0 and cell_col < MAX_COLS:
                        row_cells[cell_col] = _cell_text(
                            u''.join(buf), cell_type, cell_style, shared, date_styles)
                    cell_col = -1
                    buf = []
                elif name_ == 'row':
                    if row_cells:
                        width = max(row_cells.keys()) + 1
                        row = [row_cells.get(i, u'') for i in range(width)]
                    else:
                        row = []
                    sheet.rows.append(row)
                    row_count += 1
                    if row_count >= MAX_ROWS:
                        sheet.truncated = True
                        break
                elif name_ == 'sheetData':
                    break
    finally:
        try:
            reader.Close()
        except Exception:
            pass
        try:
            stream.Close()
        except Exception:
            pass

    width = sheet.width
    for row in sheet.rows:
        _pad(row, width)
    while sheet.rows and not any(c.strip() for c in sheet.rows[-1]):
        sheet.rows.pop()
    return sheet


def _cell_text(raw, cell_type, style, shared, date_styles):
    if cell_type == 's':
        try:
            idx = int(float(raw))
        except Exception:
            return u''
        if 0 <= idx < len(shared):
            return shared[idx]
        return u''
    if cell_type in ('str', 'inlineStr'):
        return _unescape(raw)
    if cell_type == 'b':
        return u'Yes' if raw.strip() in ('1', 'true', 'TRUE') else u'No'
    if cell_type == 'e':
        return raw
    if raw == u'':
        return u''
    is_date = False
    if 0 <= style < len(date_styles):
        is_date = date_styles[style]
    if is_date:
        return _serial_to_text(raw)
    return _number_text(raw)


def _read_xlsx(path, workbook):
    stream = FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite)
    try:
        archive = ZipArchive(stream, ZipArchiveMode.Read)
        try:
            shared = _read_shared_strings(archive)
            date_styles = _read_date_styles(archive)
            for name, part in _read_sheet_map(archive):
                sheet = _read_worksheet(archive, part, name, shared, date_styles)
                if sheet.truncated:
                    workbook.warnings.append(
                        u'"{0}" was cut off at {1} rows.'.format(name, MAX_ROWS))
                workbook.sheets.append(sheet)
        finally:
            archive.Dispose()
    finally:
        stream.Close()


# ---------------------------------------------------------------- csv

def _decode_bytes(data):
    for enc in (Encoding.UTF8, Encoding.Default):
        try:
            text = enc.GetString(data)
            if text:
                return text
        except Exception:
            pass
    return ''


def _sniff_delimiter(line):
    best = ','
    best_count = 0
    in_quote = False
    counts = {',': 0, ';': 0, '\t': 0, '|': 0}
    for ch in line:
        if ch == '"':
            in_quote = not in_quote
        elif not in_quote and ch in counts:
            counts[ch] += 1
    for ch in (',', ';', '\t', '|'):
        if counts[ch] > best_count:
            best = ch
            best_count = counts[ch]
    return best


def _split_csv(text, delim):
    rows = []
    row = []
    field = []
    in_quote = False
    i = 0
    length = len(text)
    while i < length:
        ch = text[i]
        if in_quote:
            if ch == '"':
                if i + 1 < length and text[i + 1] == '"':
                    field.append('"')
                    i += 1
                else:
                    in_quote = False
            else:
                field.append(ch)
        else:
            if ch == '"':
                in_quote = True
            elif ch == delim:
                row.append(u''.join(field))
                field = []
            elif ch == '\r':
                pass
            elif ch == '\n':
                row.append(u''.join(field))
                field = []
                rows.append(row)
                row = []
                if len(rows) >= MAX_ROWS:
                    return rows, True
            else:
                field.append(ch)
        i += 1
    if field or row:
        row.append(u''.join(field))
        rows.append(row)
    return rows, False


def _read_csv(path, workbook):
    data = File.ReadAllBytes(path)
    text = _decode_bytes(data)
    if text and text[0] == u'\ufeff':
        text = text[1:]
    first = ''
    for line in text.split('\n'):
        if line.strip():
            first = line
            break
    delim = _sniff_delimiter(first)
    rows, truncated = _split_csv(text, delim)
    sheet = Sheet(os.path.splitext(os.path.basename(path))[0])
    sheet.rows = rows
    sheet.truncated = truncated
    width = sheet.width
    for row in sheet.rows:
        _pad(row, width)
    while sheet.rows and not any(c.strip() for c in sheet.rows[-1]):
        sheet.rows.pop()
    if truncated:
        workbook.warnings.append(u'The file was cut off at {0} rows.'.format(MAX_ROWS))
    workbook.sheets.append(sheet)


# ---------------------------------------------------------------- entry point

def read_workbook(path):
    """Read a spreadsheet and return a Workbook. Raises SpreadsheetError."""
    if not path:
        raise SpreadsheetError('No file chosen.')
    if not os.path.isfile(path):
        raise SpreadsheetError('The file cannot be found:\n{0}'.format(path))
    ext = os.path.splitext(path)[1].lower()
    workbook = Workbook(path)
    if ext in ('.csv', '.txt', '.tsv'):
        _read_csv(path, workbook)
    elif ext in ('.xlsx', '.xlsm', '.xltx', '.xltm'):
        try:
            _read_xlsx(path, workbook)
        except SpreadsheetError:
            raise
        except Exception as err:
            raise SpreadsheetError(
                'The workbook could not be read.\n\n{0}\n\n'
                'If it is open in Excel with unsaved changes, save it first.'.format(err))
    elif ext == '.xls':
        raise SpreadsheetError(
            'The old binary .xls format is not readable without Excel.\n'
            'Open it in Excel and save as .xlsx or .csv.')
    else:
        raise SpreadsheetError('Unsupported file type "{0}".\n'
                               'Use .xlsx, .xlsm or .csv.'.format(ext))
    if not workbook.sheets:
        raise SpreadsheetError('No readable worksheets were found in the file.')
    try:
        workbook.stamp = File.GetLastWriteTime(path).ToString('dd/MM/yyyy HH:mm')
    except Exception:
        workbook.stamp = ''
    return workbook


def header_names(sheet, header_row):
    """Column captions from the nominated 1-based row, with a fallback."""
    names = []
    width = sheet.width
    values = []
    idx = header_row - 1
    if 0 <= idx < len(sheet.rows):
        values = sheet.rows[idx]
    for i in range(width):
        text = values[i].strip() if i < len(values) else u''
        if not text:
            text = u'(column {0})'.format(column_letter(i))
        names.append(text)
    # a duplicate caption would make the mapping ambiguous
    seen = {}
    out = []
    for i, name in enumerate(names):
        if name in seen:
            seen[name] += 1
            out.append(u'{0} [{1}]'.format(name, column_letter(i)))
        else:
            seen[name] = 1
            out.append(name)
    return out


def data_rows(sheet, header_row):
    """Rows after the header row, each padded to the sheet width."""
    width = sheet.width
    out = []
    for i in range(header_row, len(sheet.rows)):
        row = list(sheet.rows[i])
        _pad(row, width)
        out.append(row)
    return out
