# -*- coding: utf-8 -*-
"""Family Viewer - the Excel round trip.

The list goes out as a real `.xlsx`, gets edited in Excel, and comes back in as
staged changes.  Nothing is written to the model by the import: it stages, and
Apply in the main window is still the only thing that writes.

The workbook is built straight as Office Open XML into a zip through
`System.IO.Compression` and `System.Xml` - no Excel, no installed package, and
full control over the frozen header, the column widths, the autofilter and the
cell fills.  Same approach as the Drawing Register's exporter and the Excel for
Revit tool, and the same house convention: **orange cells are editable, grey
ones are read only**, with a legend sheet saying so.

The id column carries the element id and is what the import matches on.  Names
change - that is the point of exporting - so matching on a name would lose the
row the moment somebody renamed it, which is the one thing the round trip is
for.
"""

import fv_clr  # noqa: F401  - must be first

import os

from System.IO import Directory, File, MemoryStream
from System.Text import Encoding, UTF8Encoding

import fv_core
from fv_model import KEY_NAME

# the fixed columns, in the order they are written
ID_HEAD = 'Element id'
KIND_HEAD = 'Row'
FAMILY_HEAD = 'Family'
TYPE_HEAD = 'Type'
CATEGORY_HEAD = 'Category'
COUNT_HEAD = 'Count'

READ_ONLY = [ID_HEAD, KIND_HEAD, CATEGORY_HEAD, COUNT_HEAD]

# style indexes written into styles.xml, referenced by every cell
S_PLAIN = 0
S_HEAD = 1
S_LOCKED = 2
S_EDIT = 3
S_TITLE = 4
S_NOTE = 5


# ---------------------------------------------------------------------------
# little XML helpers
# ---------------------------------------------------------------------------

def _esc(text):
    out = str(text if text is not None else '')
    out = out.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    out = out.replace('"', '&quot;')
    # Excel refuses a file carrying a control character, and a parameter value
    # read out of Revit can hold one
    cleaned = []
    for char in out:
        code = ord(char)
        if code < 32 and char not in ('\t', '\n'):
            continue
        cleaned.append(char)
    return ''.join(cleaned)


def _column_letter(index):
    """1 -> A, 27 -> AA."""
    letters = ''
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _cell_ref(column, row):
    return _column_letter(column) + str(row)


# ---------------------------------------------------------------------------
# writing
# ---------------------------------------------------------------------------

def _zip_types():
    """ZipArchive, asked for at the point of use rather than at module load.

    Its assembly moved between .NET Framework 4.8 and .NET 8, and a reference
    that is not there yet turns a module-level import into an ImportError that
    kills the whole tool before any of it runs - which is exactly what shipping
    it at the top of this file did.  Nothing here is needed to LIST families,
    so a missing zip assembly should cost the export and nothing else.
    """
    from System.IO.Compression import (CompressionLevel, ZipArchive,
                                       ZipArchiveMode)
    return ZipArchive, ZipArchiveMode, CompressionLevel


def available():
    """True where this Revit can do the Excel round trip at all."""
    try:
        _zip_types()
        return True
    except Exception:
        return False


def write(path, headings, rows, title, notes=None):
    """Write the workbook.

    `rows` is a list of lists, matching `headings`.  Returns the path.
    """
    ZipArchive, ZipArchiveMode, CompressionLevel = _zip_types()
    sheet = _sheet_xml(headings, rows)
    legend = _legend_xml(title, headings, notes or [])

    parts = {
        '[Content_Types].xml': _content_types(),
        '_rels/.rels': _root_rels(),
        'xl/workbook.xml': _workbook(),
        'xl/_rels/workbook.xml.rels': _workbook_rels(),
        'xl/styles.xml': _styles(),
        'xl/worksheets/sheet1.xml': sheet,
        'xl/worksheets/sheet2.xml': legend,
    }

    folder = os.path.dirname(path)
    if folder and not Directory.Exists(folder):
        Directory.CreateDirectory(folder)

    encoding = UTF8Encoding(False)
    stream = MemoryStream()
    archive = ZipArchive(stream, ZipArchiveMode.Create, True)
    try:
        for name, text in sorted(parts.items()):
            entry = archive.CreateEntry(name, CompressionLevel.Optimal)
            handle = entry.Open()
            try:
                data = encoding.GetBytes(text)
                handle.Write(data, 0, data.Length)
            finally:
                handle.Close()
    finally:
        archive.Dispose()

    File.WriteAllBytes(path, stream.ToArray())
    stream.Dispose()
    return path


def _sheet_xml(headings, rows):
    last = _column_letter(len(headings))
    body = []
    body.append('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>')
    body.append('<worksheet xmlns="http://schemas.openxmlformats.org/'
                'spreadsheetml/2006/main">')

    body.append('<sheetViews><sheetView workbookViewId="0" tabSelected="1">'
                '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" '
                'state="frozen"/></sheetView></sheetViews>')

    body.append('<cols>')
    for index, head in enumerate(headings):
        width = 16
        if head == FAMILY_HEAD:
            width = 34
        elif head == TYPE_HEAD:
            width = 28
        elif head == CATEGORY_HEAD:
            width = 20
        elif head in (ID_HEAD, KIND_HEAD, COUNT_HEAD):
            width = 11
        body.append('<col min="{0}" max="{0}" width="{1}" '
                    'customWidth="1"/>'.format(index + 1, width))
    body.append('</cols>')

    body.append('<sheetData>')
    body.append('<row r="1" ht="20" customHeight="1">')
    for index, head in enumerate(headings):
        body.append(_text_cell(_cell_ref(index + 1, 1), head, S_HEAD))
    body.append('</row>')

    for number, values in enumerate(rows):
        excel_row = number + 2
        body.append('<row r="{0}">'.format(excel_row))
        for index, head in enumerate(headings):
            value = values[index] if index < len(values) else ''
            style = S_LOCKED if head in READ_ONLY else S_EDIT
            body.append(_text_cell(_cell_ref(index + 1, excel_row), value,
                                   style))
        body.append('</row>')
    body.append('</sheetData>')

    body.append('<autoFilter ref="A1:{0}{1}"/>'.format(
        last, max(1, len(rows) + 1)))
    body.append('</worksheet>')
    return ''.join(body)


def _text_cell(ref, value, style):
    """Everything is written as an inline string.

    A shared string table would be smaller, but a type mark of "12" coming back
    as the number twelve - and a leading zero disappearing with it - is the
    classic way an Excel round trip quietly corrupts a schedule.  Inline text
    keeps what was exported.
    """
    return ('<c r="{0}" s="{1}" t="inlineStr"><is><t xml:space="preserve">'
            '{2}</t></is></c>').format(ref, style, _esc(value))


def _legend_xml(title, headings, notes):
    lines = [
        (title, S_TITLE),
        ('', S_NOTE),
        ('Orange cells can be edited and read back in. Grey cells are read '
         'only.', S_NOTE),
        ('Element id is what the import matches on, so do not change it, '
         'sort it away or delete the column.', S_NOTE),
        ('Adding rows does nothing: the import only looks at rows whose id it '
         'already knows.', S_NOTE),
        ('Family renames the family. It can be changed on the family row, on '
         'its type rows, or all of them - but if the rows give one family two '
         'different new names, the import leaves it alone and says so. System '
         'families (walls, pipes, ducts) cannot be renamed.', S_NOTE),
        ('Nothing is written to the model by the import. It stages the '
         'changes, and Apply in Family Viewer is still the only thing that '
         'writes.', S_NOTE),
        ('', S_NOTE),
        ('Columns in this export:', S_NOTE),
    ]
    for head in headings:
        mark = ' (read only)' if head in READ_ONLY else ' (editable)'
        lines.append(('    ' + head + mark, S_NOTE))
    for note in notes:
        lines.append(('', S_NOTE))
        lines.append((note, S_NOTE))

    body = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<worksheet xmlns="http://schemas.openxmlformats.org/'
            'spreadsheetml/2006/main">',
            '<cols><col min="1" max="1" width="110" customWidth="1"/></cols>',
            '<sheetData>']
    for index, pair in enumerate(lines):
        text, style = pair
        body.append('<row r="{0}">'.format(index + 1))
        body.append(_text_cell('A' + str(index + 1), text, style))
        body.append('</row>')
    body.append('</sheetData></worksheet>')
    return ''.join(body)


def _content_types():
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
            'content-types">'
            '<Default Extension="rels" ContentType="application/'
            'vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType='
            '"application/vnd.openxmlformats-officedocument.spreadsheetml.'
            'worksheet+xml"/>'
            '<Override PartName="/xl/worksheets/sheet2.xml" ContentType='
            '"application/vnd.openxmlformats-officedocument.spreadsheetml.'
            'worksheet+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            '</Types>')


def _root_rels():
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
            '2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/officeDocument" '
            'Target="xl/workbook.xml"/></Relationships>')


def _workbook():
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/'
            'spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.'
            'org/officeDocument/2006/relationships"><sheets>'
            '<sheet name="Families" sheetId="1" r:id="rId1"/>'
            '<sheet name="How this works" sheetId="2" r:id="rId2"/>'
            '</sheets></workbook>')


def _workbook_rels():
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
            '2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet2.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            '</Relationships>')


def _styles():
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/'
            'spreadsheetml/2006/main">'
            '<fonts count="4">'
            '<font><sz val="11"/><name val="Calibri"/></font>'
            '<font><b/><sz val="11"/><color rgb="FFFFFFFF"/>'
            '<name val="Calibri"/></font>'
            '<font><b/><sz val="14"/><name val="Calibri"/></font>'
            '<font><sz val="11"/><color rgb="FF595959"/><name val="Calibri"/>'
            '</font>'
            '</fonts>'
            '<fills count="5">'
            '<fill><patternFill patternType="none"/></fill>'
            '<fill><patternFill patternType="gray125"/></fill>'
            '<fill><patternFill patternType="solid">'
            '<fgColor rgb="FF44546A"/><bgColor indexed="64"/>'
            '</patternFill></fill>'
            '<fill><patternFill patternType="solid">'
            '<fgColor rgb="FFEDEDED"/><bgColor indexed="64"/>'
            '</patternFill></fill>'
            '<fill><patternFill patternType="solid">'
            '<fgColor rgb="FFFCE4C8"/><bgColor indexed="64"/>'
            '</patternFill></fill>'
            '</fills>'
            '<borders count="2"><border/>'
            '<border><left style="thin"><color rgb="FFBFBFBF"/></left>'
            '<right style="thin"><color rgb="FFBFBFBF"/></right>'
            '<top style="thin"><color rgb="FFBFBFBF"/></top>'
            '<bottom style="thin"><color rgb="FFBFBFBF"/></bottom></border>'
            '</borders>'
            '<cellStyleXfs count="1"><xf/></cellStyleXfs>'
            '<cellXfs count="6">'
            '<xf xfId="0"/>'
            '<xf xfId="0" fontId="1" fillId="2" borderId="1" applyFont="1" '
            'applyFill="1" applyBorder="1" applyAlignment="1">'
            '<alignment vertical="center"/></xf>'
            '<xf xfId="0" fillId="3" borderId="1" applyFill="1" '
            'applyBorder="1"/>'
            '<xf xfId="0" fillId="4" borderId="1" applyFill="1" '
            'applyBorder="1"/>'
            '<xf xfId="0" fontId="2" applyFont="1"/>'
            '<xf xfId="0" fontId="3" applyFont="1"/>'
            '</cellXfs>'
            '</styleSheet>')


# ---------------------------------------------------------------------------
# reading it back
# ---------------------------------------------------------------------------

def read(path):
    """Read an exported workbook back.

    Returns (headings, rows), rows being lists of text in heading order.  Only
    the first sheet is looked at; the legend sheet is prose.
    """
    from System.Xml import XmlDocument

    ZipArchive, ZipArchiveMode, _unused = _zip_types()

    stream = MemoryStream(File.ReadAllBytes(path))
    archive = ZipArchive(stream, ZipArchiveMode.Read)
    try:
        shared = _shared_strings(archive)
        text = _entry_text(archive, 'xl/worksheets/sheet1.xml')
    finally:
        archive.Dispose()
        stream.Dispose()
    if not text:
        raise ValueError('That file does not look like a Family Viewer export '
                         '- there is no first worksheet in it.')

    document = XmlDocument()
    document.LoadXml(text)

    table = {}
    widest = 0
    for row_node in document.GetElementsByTagName('row'):
        cells = {}
        for cell in row_node.ChildNodes:
            if cell.Name != 'c':
                continue
            ref = _attribute(cell, 'r')
            column = _column_index(ref)
            if column <= 0:
                continue
            cells[column] = _cell_text(cell, shared)
            widest = max(widest, column)
        number = 0
        try:
            number = int(_attribute(row_node, 'r') or '0')
        except Exception:
            number = 0
        if number:
            table[number] = cells

    if not table:
        return [], []

    order = sorted(table.keys())
    headings = []
    head_cells = table[order[0]]
    for column in range(1, widest + 1):
        headings.append(head_cells.get(column, ''))
    while headings and not headings[-1]:
        headings.pop()

    rows = []
    for number in order[1:]:
        cells = table[number]
        row = []
        for column in range(1, len(headings) + 1):
            row.append(cells.get(column, ''))
        if any(value for value in row):
            rows.append(row)
    return headings, rows


def _entry_text(archive, name):
    entry = archive.GetEntry(name)
    if entry is None:
        return ''
    handle = entry.Open()
    try:
        buffer = MemoryStream()
        handle.CopyTo(buffer)
        data = buffer.ToArray()
        buffer.Dispose()
        return Encoding.UTF8.GetString(data)
    finally:
        handle.Close()


def _shared_strings(archive):
    """Excel rewrites inline strings as shared ones when it saves, so a file
    that has been through Excel has to be read either way."""
    from System.Xml import XmlDocument

    text = _entry_text(archive, 'xl/sharedStrings.xml')
    if not text:
        return []
    document = XmlDocument()
    document.LoadXml(text)
    found = []
    for node in document.GetElementsByTagName('si'):
        found.append(_gather_text(node))
    return found


def _gather_text(node):
    parts = []
    for child in node.GetElementsByTagName('t'):
        parts.append(child.InnerText)
    if not parts:
        return node.InnerText or ''
    return ''.join(parts)


def _attribute(node, name):
    try:
        item = node.Attributes.GetNamedItem(name)
        return '' if item is None else item.Value
    except Exception:
        return ''


def _column_index(ref):
    letters = ''
    for char in str(ref or ''):
        if char.isalpha():
            letters += char.upper()
        else:
            break
    if not letters:
        return 0
    index = 0
    for char in letters:
        index = index * 26 + (ord(char) - 64)
    return index


def _cell_text(cell, shared):
    kind = _attribute(cell, 't')
    if kind == 'inlineStr':
        return _gather_text(cell)
    if kind == 's':
        try:
            return shared[int(cell.InnerText)]
        except Exception:
            return ''
    value = ''
    for child in cell.ChildNodes:
        if child.Name == 'v':
            value = child.InnerText
            break
    if kind == 'str':
        return value
    # a number Excel wrote back: 12.0 for something that went out as 12
    if value.endswith('.0'):
        trimmed = value[:-2]
        try:
            int(trimmed)
            return trimmed
        except Exception:
            pass
    return value


def log_path():
    return fv_core.log_path()


# ---------------------------------------------------------------------------
# what an import changes - worked out without touching anything
# ---------------------------------------------------------------------------

class ImportPlan(object):
    """The outcome of comparing a workbook with the list, before any of it is
    staged.  Every row read lands in exactly one of: changed, unchanged,
    unknown (its id is not in the read), or no_id (its id would not read)."""

    def __init__(self):
        self.rows_read = 0
        self.changes = []          # (staging key, value, target row, heading)
        self.changed_rows = 0
        self.unchanged = 0
        self.unknown = 0
        self.no_id = 0
        self.refused = []          # one line per value that could not stage
        self.families = set()      # family names holding a change

    @property
    def failed(self):
        return len(self.refused) + self.unknown + self.no_id


def plan_import(headings, rows, known, edit_key):
    """Compare an exported workbook with the list.

    `known` maps (kind, element id) to the row it was exported from, and MUST
    be built from the whole read rather than the rows a filter left on screen,
    or every row the filter hides comes back "not found".  `edit_key` is the
    window's own rule for whether a cell can be staged at all.  Nothing here
    stages anything; the caller decides what to do with the plan.

    The Family column is a rename of the FAMILY, and the family name sits on
    the family's own row and on every one of its type rows.  Up to 2.0.0 this
    column was left out of the comparison altogether - while the workbook
    coloured it orange and its legend called it editable - so a family renamed
    in Excel was read, compared and silently thrown away.  Now every row that
    carries a new family name votes for it: one new name across them is staged
    once, on the family; two different new names for the same family is a
    conflict and is refused by name rather than guessed at.
    """
    plan = ImportPlan()
    index = {}
    for position, head in enumerate(headings):
        index[head] = position
    editable = [head for head in headings
                if head and head not in READ_ONLY and head != FAMILY_HEAD]
    has_family = FAMILY_HEAD in index

    renames = {}          # family id -> {new name: [row numbers]}
    families = {}         # family id -> the family's own row
    matched = []          # (row number, changed by another column, family id)

    for number, row in enumerate(rows):
        plan.rows_read += 1

        def cell(head):
            position = index.get(head, -1)
            if position < 0 or position >= len(row):
                return ''
            return (row[position] or '').strip()

        kind = cell(KIND_HEAD) or 'type'
        try:
            element_id = int(float(cell(ID_HEAD)))
        except Exception:
            plan.no_id += 1
            continue
        target = known.get((kind, element_id))
        if target is None:
            plan.unknown += 1
            continue

        changed_here = False
        for head in editable:
            wanted = cell(head)
            if head == TYPE_HEAD:
                if kind != 'type':
                    continue
                column_key = KEY_NAME
                now = target.type_name or ''
            else:
                column_key = head
                now = target.cell(head) or ''
            if wanted == now:
                continue
            label = (target.family_name + ' : ' + (target.type_name or '')
                     ).strip(' :')
            if column_key == KEY_NAME and not wanted:
                plan.refused.append(label + ' - a name cannot be blank')
                continue
            key = edit_key(target, column_key)
            if key is None:
                plan.refused.append(label + ' - ' + head +
                                    ' cannot be written from here')
                continue
            plan.changes.append((key, wanted, target, head))
            plan.families.add(target.family_name)
            changed_here = True

        voted = None
        if has_family:
            wanted = cell(FAMILY_HEAD)
            now = target.family_name or ''
            if wanted != now:
                family_id = getattr(target, 'family_id', 0) or 0
                owner = target if kind == 'family' else \
                    known.get(('family', family_id))
                if owner is None:
                    owner = target
                families[family_id, now] = owner
                if not wanted:
                    plan.refused.append(now + ' - a family name cannot be '
                                        'blank')
                else:
                    votes = renames.setdefault((family_id, now), {})
                    votes.setdefault(wanted, []).append(number)
                    voted = (family_id, now)
        matched.append((number, changed_here, voted))

    # one rename per family, however many rows carried it
    staged_families = set()
    for family, votes in sorted(renames.items(), key=lambda pair: pair[0][1]):
        family_id, old_name = family
        if len(votes) > 1:
            plan.refused.append(
                old_name + ' - the rows disagree on its new name (' +
                ' / '.join(sorted(votes)) + '), so it was left alone')
            continue
        new_name = list(votes.keys())[0]
        owner = families[family]
        if not family_id:
            plan.refused.append(old_name + ' - a system family cannot be '
                                'renamed')
            continue
        key = edit_key(owner, KEY_NAME)
        if key is None:
            plan.refused.append(old_name + ' - the family name cannot be '
                                'written from here')
            continue
        plan.changes.append((key, new_name, owner, FAMILY_HEAD))
        plan.families.add(old_name)
        staged_families.add(family)

    for number, changed_here, voted in matched:
        if changed_here or (voted is not None and voted in staged_families):
            plan.changed_rows += 1
        else:
            plan.unchanged += 1
    return plan


def summary(plan, path=''):
    """The words of the import prompt, so the bench can read them too."""
    lines = []
    where = (' from ' + os.path.basename(path)) if path else ''
    lines.append(str(plan.rows_read) + ' rows read' + where + '.')
    lines.append('')
    lines.append('Changed:      ' + str(len(plan.changes)) + ' value' +
                 ('' if len(plan.changes) == 1 else 's') + ' on ' +
                 str(plan.changed_rows) + ' row' +
                 ('' if plan.changed_rows == 1 else 's') + ', across ' +
                 str(len(plan.families)) + ' famil' +
                 ('y' if len(plan.families) == 1 else 'ies'))
    lines.append('Unchanged:    ' + str(plan.unchanged) + ' row' +
                 ('' if plan.unchanged == 1 else 's'))
    lines.append('Not imported: ' + str(plan.failed))
    if plan.refused:
        lines.append('    ' + str(len(plan.refused)) +
                     ' value(s) could not be staged')
    if plan.unknown:
        lines.append('    ' + str(plan.unknown) + ' row(s) are not in this '
                     'model, or not in the families read')
    if plan.no_id:
        lines.append('    ' + str(plan.no_id) + ' row(s) have no readable '
                     'element id')
    lines.append('')
    if plan.changes:
        lines.append('Nothing has been written to the model. The changes are '
                     'staged in teal and their families highlighted; press '
                     'Apply to write them, or Discard to drop them.')
    else:
        lines.append('Nothing in the workbook differs from the model, so '
                     'nothing was staged.')
    if plan.refused:
        lines.append('')
        lines.append('Could not be staged:')
        for line in plan.refused[:15]:
            lines.append('  ' + line)
        if len(plan.refused) > 15:
            lines.append('  ...and ' + str(len(plan.refused) - 15) + ' more')
    return '\n'.join(lines)
