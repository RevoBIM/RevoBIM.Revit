# -*- coding: utf-8 -*-
"""Bench check for the Excel export. Runs under plain CPython, no Revit.

    python xlsx_check.py            validate the generated workbooks
    python xlsx_check.py --selftest break each rule and confirm it is caught

The rule that matters most: **OOXML fixes the order of the elements inside
<worksheet> and Excel enforces it even though lenient readers do not.** Getting
that wrong is what produced "We found a problem with some content in ...",
with no indication of which part was at fault.
"""

import re
import sys
import zipfile

import xlsx_io
import excel_bridge

# ECMA-376, CT_Worksheet: this sequence is not advisory
WORKSHEET_ORDER = [
    'sheetPr', 'dimension', 'sheetViews', 'sheetFormatPr', 'cols', 'sheetData',
    'sheetCalcPr', 'sheetProtection', 'protectedRanges', 'scenarios',
    'autoFilter', 'sortState', 'dataConsolidate', 'customSheetViews',
    'mergeCells', 'phoneticPr', 'conditionalFormatting', 'dataValidations',
    'hyperlinks', 'printOptions', 'pageMargins', 'pageSetup', 'headerFooter',
    'rowBreaks', 'colBreaks', 'customProperties', 'cellWatches',
    'ignoredErrors', 'drawing', 'legacyDrawing', 'tableParts', 'extLst',
]

REQUIRED_PARTS = ['[Content_Types].xml', '_rels/.rels', 'xl/workbook.xml',
                  'xl/_rels/workbook.xml.rels', 'xl/styles.xml']


def direct_children(body, parent):
    """Names of the elements directly inside <parent>, in document order."""
    out = []
    depth = 0
    for m in re.finditer(r'<(/?)([\w:]+)([^>]*?)(/?)>', body):
        close, name, _attrs, selfclose = m.groups()
        if name == parent:
            continue
        if depth == 0 and not close:
            out.append(name)
        if not close and not selfclose:
            depth += 1
        elif close:
            depth -= 1
    return out


def check_workbook(path, problems):
    def fail(msg):
        problems.append('{0}: {1}'.format(path.split('/')[-1], msg))

    try:
        z = zipfile.ZipFile(path)
    except Exception as err:
        fail('not a readable zip - {0}'.format(err))
        return
    names = z.namelist()

    if z.testzip() is not None:
        fail('corrupt zip entry')
    for part in REQUIRED_PARTS:
        if part not in names:
            fail('missing part {0}'.format(part))

    # every sheet the workbook declares must exist and be related
    book = z.read('xl/workbook.xml').decode('utf-8')
    rels = z.read('xl/_rels/workbook.xml.rels').decode('utf-8')
    ctypes = z.read('[Content_Types].xml').decode('utf-8')
    declared = re.findall(r'<sheet name="([^"]*)"[^>]*r:id="([^"]*)"', book)
    if not declared:
        fail('no sheets declared in workbook.xml')
    seen_names = []
    for name, rid in declared:
        if name.lower() in seen_names:
            fail('duplicate tab name {0}'.format(name))
        seen_names.append(name.lower())
        if len(name) > 31:
            fail('tab name over 31 characters: {0}'.format(name))
        if re.search(r'[:\\/?*\[\]]', name):
            fail('illegal character in tab name: {0}'.format(name))
        hit = re.search(r'Id="{0}"[^>]*Target="([^"]*)"'.format(rid), rels)
        if not hit:
            fail('sheet {0} has no relationship {1}'.format(name, rid))
            continue
        target = 'xl/' + hit.group(1).lstrip('/')
        if target not in names:
            fail('relationship points at a missing part: {0}'.format(target))
        if target not in ctypes.replace('/xl/', 'xl/'):
            fail('no content type override for {0}'.format(target))

    selected = 0
    for part in names:
        if not part.startswith('xl/worksheets/'):
            continue
        body = z.read(part).decode('utf-8')

        if not body.startswith('<?xml'):
            fail('{0} has no XML declaration'.format(part))
        children = direct_children(body[body.index('<worksheet'):], 'worksheet')
        seq = [WORKSHEET_ORDER.index(c) for c in children if c in WORKSHEET_ORDER]
        unknown = [c for c in children if c not in WORKSHEET_ORDER]
        if unknown:
            fail('{0} has unexpected elements {1}'.format(part, unknown))
        if seq != sorted(seq):
            fail('{0} elements out of schema order: {1}'.format(part, children))

        selected += len(re.findall(r'tabSelected="1"', body))

        for ref in re.findall(r'<mergeCell ref="([^"]+)"', body):
            a, _, b = ref.partition(':')
            if not b or a == b:
                fail('{0} single-cell merge {1}'.format(part, ref))

        # every cell reference must sit on the row that declares it
        for rm in re.finditer(r'<row r="(\d+)"[^>]*?(/>|>(.*?)</row>)', body, re.S):
            rnum = rm.group(1)
            for cm in re.finditer(r'<c r="([A-Z]+)(\d+)"', rm.group(3) or ''):
                if cm.group(2) != rnum:
                    fail('{0} cell {1}{2} inside row {3}'.format(
                        part, cm.group(1), cm.group(2), rnum))

        # a numeric cell must actually hold a number
        for cm in re.finditer(r'<c [^>]*?(?<!t="inlineStr")><v>([^<]*)</v></c>', body):
            if not xlsx_io.looks_numeric(cm.group(1)):
                fail('{0} non-numeric value in a numeric cell: {1}'.format(
                    part, cm.group(1)))

        # style ids must exist in styles.xml
        styles = z.read('xl/styles.xml').decode('utf-8')
        count = int(re.search(r'<cellXfs count="(\d+)"', styles).group(1))
        for sid in set(re.findall(r'<c [^>]*?s="(\d+)"', body)):
            if int(sid) >= count:
                fail('{0} uses style {1} but only {2} exist'.format(part, sid, count))

        if '&' in re.sub(r'&(amp|lt|gt|quot|apos|#\d+);', '', body):
            fail('{0} has an unescaped ampersand'.format(part))

    if selected > 1:
        fail('{0} sheets marked tabSelected'.format(selected))


def sample_data(cols=4, rows=6):
    fields = []
    for i in range(cols):
        fields.append({'name': ['Mark', 'Type Mark & Co', 'Volume', 'Comments',
                                'Level', 'Notes'][i % 6],
                       'letter': xlsx_io.col_letter(i),
                       'is_type': i == 1, 'editable': i != 2, 'reason': ''})
    data = []
    for r in range(rows):
        data.append({'eid': str(9000 + r),
                     'values': ['M<{0}>'.format(r), 'T&{0}'.format(r),
                                '{0}.5'.format(r), '', 'L1', ''][:cols],
                     'editable': [True, True, False, True, True, True][:cols],
                     'is_type': [False, True, False, False, False, False][:cols]})
    return fields, data


def run(problems):
    fields, rows = sample_data()
    cases = [
        ('round trip', lambda p: excel_bridge.export_round_trip(
            p, 'BGL_G_Sheet List', fields, rows, 'Model A')),
        ('presentation', lambda p: excel_bridge.export_presentation(
            p, 'BGL_G_Sheet List', fields, rows, 'Model A')),
        ('one column', lambda p: excel_bridge.export_presentation(
            p, 'Single', fields[:1], [{'eid': '1', 'values': ['x'],
                                       'editable': [True], 'is_type': [False]}],
            'Model A')),
        ('no rows', lambda p: excel_bridge.export_round_trip(
            p, 'Empty', fields, [], 'Model A')),
        ('awkward name', lambda p: excel_bridge.export_round_trip(
            p, 'A/B:C*D?E[F]G that is far longer than excel will ever allow',
            fields, rows, 'Model A')),
    ]
    for label, build in cases:
        path = '/tmp/_chk_{0}.xlsx'.format(label.replace(' ', '_'))
        try:
            build(path)
        except Exception as err:
            problems.append('{0}: export raised {1}'.format(label, err))
            continue
        check_workbook(path, problems)

        # and it must still read back
        try:
            xlsx_io.read_sheet(path, 0)
        except Exception as err:
            problems.append('{0}: could not be read back - {1}'.format(label, err))


def selftest():
    """Break each rule on purpose. A rule nobody has tested is not a rule."""
    print('Self test - each of these must be CAUGHT:')
    ok = True

    original = xlsx_io.Sheet.xml

    def broken_order(self):
        body = original(self)
        views = re.search(r'<sheetViews>.*?</sheetViews>', body, re.S)
        if not views:
            return body
        body = body.replace(views.group(0), '')
        return body.replace('<sheetData>', views.group(0) + '<sheetData>')

    checks = [
        ('sheetViews after cols', broken_order),
        ('single-cell merge', None),
        ('duplicate tab name', None),
    ]

    xlsx_io.Sheet.xml = broken_order
    problems = []
    fields, rows = sample_data()
    excel_bridge.export_round_trip('/tmp/_bad.xlsx', 'X', fields, rows, 'M')
    check_workbook('/tmp/_bad.xlsx', problems)
    xlsx_io.Sheet.xml = original
    hit = any('schema order' in p for p in problems)
    print('  {0} sheetViews after cols'.format('CAUGHT ' if hit else 'MISSED '))
    ok = ok and hit

    # single-cell merge
    wb = xlsx_io.Workbook()
    sh = wb.sheet('S')
    sh.add_row([('a', 0, False), ('b', 0, False)])
    sh.add_row([('c', 0, False), ('d', 0, False)])
    sh.merges.append((0, 0, 0, 0))
    body = sh.xml()
    hit = '<mergeCell' not in body
    print('  {0} single-cell merge dropped'.format('CAUGHT ' if hit else 'MISSED '))
    ok = ok and hit

    # duplicate tab name
    wb = xlsx_io.Workbook()
    a = wb.sheet('Same')
    b = wb.sheet('Same')
    hit = a.name != b.name
    print('  {0} duplicate tab name renamed ({1} / {2})'.format(
        'CAUGHT ' if hit else 'MISSED ', a.name, b.name))
    ok = ok and hit

    # long name collision
    wb = xlsx_io.Workbook()
    long_name = 'A' * 40
    a = wb.sheet(long_name)
    b = wb.sheet(long_name)
    hit = a.name != b.name and len(b.name) <= 31
    print('  {0} truncated names collide ({1})'.format(
        'CAUGHT ' if hit else 'MISSED ', b.name))
    ok = ok and hit
    return ok


def main():
    if '--selftest' in sys.argv:
        ok = selftest()
        print('\nSelf test {0}'.format('PASSED' if ok else 'FAILED'))
        return 0 if ok else 1

    problems = []
    run(problems)
    if problems:
        print('FAILED - {0} problem(s):'.format(len(problems)))
        for p in problems:
            print('  ' + p)
        return 1
    print('All workbook checks passed.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
