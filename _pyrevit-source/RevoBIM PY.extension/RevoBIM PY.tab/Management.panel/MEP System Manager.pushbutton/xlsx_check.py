# -*- coding: utf-8 -*-
"""Bench check of the Excel export, under plain CPython:

    python xlsx_check.py            build workbooks of several shapes, zip them,
                                    and check each against the rules Excel enforces
    python xlsx_check.py --selftest break msm_xlsx on purpose and confirm the
                                    check catches every breakage

Lenient readers open files Excel then offers to repair, so passing an
independent parser proves nothing; these are the rules Excel itself holds.
Nothing here is shipped to Revit's engine.
"""
import io
import os
import re
import sys
import types
import zipfile
from xml.dom import minidom

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import msm_core as core  # noqa: E402

NS_MAIN = u"http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = u"http://schemas.openxmlformats.org/officeDocument/2006/relationships"
SHEET_ORDER = (u"sheetPr", u"dimension", u"sheetViews", u"sheetFormatPr", u"cols",
               u"sheetData", u"sheetProtection", u"autoFilter", u"mergeCells",
               u"conditionalFormatting", u"pageMargins", u"pageSetup")
BAD_SHEET = re.compile(u"[\\[\\]:*?/\\\\]")
REF = re.compile(u"^([A-Z]+)([0-9]+)$")


class Fail(Exception):
    pass


def load_xlsx_module(patch=None):
    source = io.open(os.path.join(HERE, u"msm_xlsx.py"), encoding=u"utf-8").read()
    if patch:
        before, after = patch
        if before not in source:
            raise AssertionError(u"selftest anchor missing in msm_xlsx.py: " + before)
        source = source.replace(before, after, 1)
    module = types.ModuleType(u"msm_xlsx")
    module.__file__ = os.path.join(HERE, u"msm_xlsx.py")
    exec(compile(source, module.__file__, u"exec"), module.__dict__)
    return module


# ============================================================
# shapes of workbook
# ============================================================

def _row(service, system, ptype, size, count, length, flag=False, check=u""):
    return {u"group": service, u"system": system, u"ptype": ptype, u"size": size,
            u"count": count, u"length": length, u"length_ft": float(length) / 0.3048,
            u"fittings": 2, u"fitting_ids": [count, count + 100], u"systems": [system],
            u"flag": flag, u"check": check, u"key": system + ptype + size}


def shapes(x):
    normal = x.system_sheets([
        (u"Cold Water", [_row(u"Cold Water", u"CWS 1", u"Copper", u"22", 4, u"12.5"),
                         _row(u"Cold Water", u"CWS 2", u"MLCP & <PEX>", u"15-54", 3, u"3.0",
                              True, u"Type not allowed \u00d72 \u00b7 Open end")]),
        (u"Hot Water", [_row(u"Hot Water", u"HWS 1", u"Copper", u"28", 1, u"0.4")])])
    one_column = [x.Sheet(u"One", [(u"Only", 10)], [[(u"a", x.S_TEXT)], [(3, x.S_INT)]])]
    empty = x.system_sheets([])
    long_names = [x.Sheet(u"Mechanical services [level 1]: supply/extract ducts", [(u"A", 10)],
                          [[(1, x.S_INT)]]),
                  x.Sheet(u"Mechanical services [level 1]: supply/extract pipes", [(u"A", 10)],
                          [[(2, x.S_INT)]]),
                  x.Sheet(u"", [(u"A", 10)], [[(u"x", x.S_TEXT)]]),
                  x.Sheet(u"one", [(u"A", 10)], []),
                  x.Sheet(u"ONE", [(u"A", 10)], [])]
    checks_off = x.system_sheets([
        (u"Cold Water", [_row(u"Cold Water", u"CWS 2", u"PVC", u"22", 3, u"3.0",
                              True, u"Type not allowed")])], False)
    ducts = x.system_sheets([
        (u"Supply Air", [_row(u"Supply Air", u"SA 1", u"Galv", u"600x300", 2, u"4.0")])],
        True, u"duct")
    containment = x.system_sheets([
        (u"LV", [_row(u"LV", u"Run 7", u"Cable Tray: Ladder", u"300x100", 5, u"9.5", True,
                      u"No service type")])], True, u"cont")
    return [(u"pipe systems", normal), (u"checks off", checks_off),
            (u"duct systems", ducts), (u"containment", containment), (u"one column", one_column),
            (u"no rows", empty), (u"awkward tab names", long_names)]


def zipped(x, sheets):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, u"w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in x.build_parts(sheets):
            archive.writestr(name, text.encode(u"utf-8"))
    return zipfile.ZipFile(io.BytesIO(buffer.getvalue()))


# ============================================================
# the rules
# ============================================================

def _children(node):
    return [n for n in node.childNodes if n.nodeType == n.ELEMENT_NODE]


def _col_number(letters):
    number = 0
    for ch in letters:
        number = number * 26 + (ord(ch) - 64)
    return number


def check_workbook(book):
    names = book.namelist()
    docs = {}
    for name in names:
        try:
            docs[name] = minidom.parseString(book.read(name))
        except Exception as error:
            raise Fail(u"{0} is not well-formed XML: {1}".format(name, error))

    # content types cover every part, and name nothing missing
    types_doc = docs.get(u"[Content_Types].xml")
    if types_doc is None:
        raise Fail(u"no [Content_Types].xml")
    overrides = set([n.getAttribute(u"PartName").lstrip(u"/")
                     for n in types_doc.getElementsByTagName(u"Override")])
    defaults = set([n.getAttribute(u"Extension")
                    for n in types_doc.getElementsByTagName(u"Default")])
    for part in overrides:
        if part not in names:
            raise Fail(u"[Content_Types].xml names {0}, which is not in the file".format(part))
    for name in names:
        if name == u"[Content_Types].xml":
            continue
        ext = name.rsplit(u".", 1)[-1]
        if name not in overrides and ext not in defaults:
            raise Fail(u"{0} has no content type".format(name))
        if name.startswith(u"xl/") and name.endswith(u".xml") and name not in overrides:
            raise Fail(u"{0} is only covered by the generic xml default".format(name))

    # relationships resolve
    rels = docs.get(u"xl/_rels/workbook.xml.rels")
    if rels is None:
        raise Fail(u"no xl/_rels/workbook.xml.rels")
    targets = {}
    for rel in rels.getElementsByTagName(u"Relationship"):
        target = u"xl/" + rel.getAttribute(u"Target")
        if target not in names:
            raise Fail(u"workbook relationship points at missing {0}".format(target))
        targets[rel.getAttribute(u"Id")] = target

    book_doc = docs[u"xl/workbook.xml"]
    sheets = book_doc.getElementsByTagName(u"sheet")
    if not sheets:
        raise Fail(u"workbook has no sheets")
    seen = set()
    selected = 0
    sheet_parts = []
    for sheet in sheets:
        name = sheet.getAttribute(u"name")
        if not name or len(name) > 31 or BAD_SHEET.search(name) or name.startswith(u"'"):
            raise Fail(u"illegal tab name {0!r}".format(name))
        if name.lower() in seen:
            raise Fail(u"two tabs named {0!r}".format(name))
        seen.add(name.lower())
        rid = sheet.getAttributeNS(NS_REL, u"id") or sheet.getAttribute(u"r:id")
        if rid not in targets:
            raise Fail(u"tab {0!r} has no relationship".format(name))
        sheet_parts.append(targets[rid])

    # styles: counts match, and the two reserved fills are in place
    styles = docs[u"xl/styles.xml"]
    for tag, child in ((u"fonts", u"font"), (u"fills", u"fill"), (u"borders", u"border"),
                       (u"cellXfs", u"xf"), (u"cellStyleXfs", u"xf")):
        holder = styles.getElementsByTagName(tag)[0]
        found = len([c for c in _children(holder) if c.tagName == child])
        if int(holder.getAttribute(u"count")) != found:
            raise Fail(u"styles {0} count says {1}, holds {2}".format(
                tag, holder.getAttribute(u"count"), found))
    fills = styles.getElementsByTagName(u"patternFill")
    if len(fills) < 2 or fills[0].getAttribute(u"patternType") != u"none" or \
            fills[1].getAttribute(u"patternType") != u"gray125":
        raise Fail(u"the first two fills must be none and gray125")
    xf_count = int(styles.getElementsByTagName(u"cellXfs")[0].getAttribute(u"count"))

    for part in sheet_parts:
        doc = docs[part]
        root = doc.documentElement
        order = [c.tagName for c in _children(root)]
        for tag in order:
            if tag not in SHEET_ORDER:
                raise Fail(u"{0}: unexpected <{1}>".format(part, tag))
        places = [SHEET_ORDER.index(t) for t in order]
        if places != sorted(places) or len(set(order)) != len(order):
            raise Fail(u"{0}: worksheet children out of schema order: {1}".format(
                part, u", ".join(order)))
        views = doc.getElementsByTagName(u"sheetView")
        selected += len([v for v in views if v.getAttribute(u"tabSelected") == u"1"])
        for merge in doc.getElementsByTagName(u"mergeCell"):
            ref = merge.getAttribute(u"ref")
            if u":" not in ref or ref.split(u":")[0] == ref.split(u":")[1]:
                raise Fail(u"{0}: single-cell merge {1}".format(part, ref))
        dim = doc.getElementsByTagName(u"dimension")
        last_row = last_col = 0
        previous_row = 0
        for row in doc.getElementsByTagName(u"row"):
            number = int(row.getAttribute(u"r"))
            if number <= previous_row:
                raise Fail(u"{0}: row {1} out of order".format(part, number))
            previous_row = number
            previous_col = 0
            for cell in row.getElementsByTagName(u"c"):
                match = REF.match(cell.getAttribute(u"r"))
                if not match or int(match.group(2)) != number:
                    raise Fail(u"{0}: cell {1} is not on row {2}".format(
                        part, cell.getAttribute(u"r"), number))
                col = _col_number(match.group(1))
                if col <= previous_col:
                    raise Fail(u"{0}: cell {1} out of column order".format(
                        part, cell.getAttribute(u"r")))
                previous_col = col
                last_row, last_col = max(last_row, number), max(last_col, col)
                style = int(cell.getAttribute(u"s") or 0)
                if style >= xf_count:
                    raise Fail(u"{0}: cell {1} uses style {2}, only {3} exist".format(
                        part, cell.getAttribute(u"r"), style, xf_count))
                kind = cell.getAttribute(u"t")
                if kind == u"inlineStr":
                    if not cell.getElementsByTagName(u"is"):
                        raise Fail(u"{0}: inline string {1} has no <is>".format(
                            part, cell.getAttribute(u"r")))
                elif cell.getElementsByTagName(u"v"):
                    text = cell.getElementsByTagName(u"v")[0].firstChild.data
                    try:
                        float(text)
                    except Exception:
                        raise Fail(u"{0}: {1} holds {2!r} as a number".format(
                            part, cell.getAttribute(u"r"), text))
        if dim:
            ref = dim[0].getAttribute(u"ref").split(u":")[-1]
            match = REF.match(ref)
            if last_row and (not match or int(match.group(2)) < last_row or
                             _col_number(match.group(1)) < last_col):
                raise Fail(u"{0}: dimension {1} does not cover the cells".format(part, ref))
    if selected != 1:
        raise Fail(u"{0} tabs marked selected - Excel wants exactly one".format(selected))

    # an autofilter needs its hidden defined name
    filtered = set()
    for index, part in enumerate(sheet_parts):
        if docs[part].getElementsByTagName(u"autoFilter"):
            filtered.add(index)
    named = set([int(n.getAttribute(u"localSheetId"))
                 for n in book_doc.getElementsByTagName(u"definedName")
                 if n.getAttribute(u"name") == u"_xlnm._FilterDatabase"])
    if filtered != named:
        raise Fail(u"autofilters on tabs {0} but _FilterDatabase names for {1}".format(
            sorted(filtered), sorted(named)))


def check_content(x):
    """The export carries what the table shows."""
    book = zipped(x, shapes(x)[0][1])
    detail = book.read(u"xl/worksheets/sheet1.xml").decode(u"utf-8")
    for text in (u"CWS 1", u"MLCP &amp; &lt;PEX&gt;", u"15-54",
                 u"Type not allowed \u00d72 \u00b7 Open end"):
        if text not in detail:
            raise Fail(u"the rows sheet is missing {0!r}".format(text))
    if u"<v>22</v>" not in detail and u"<v>22.0</v>" not in detail:
        raise Fail(u"a plain size is not written as a number")
    summary = book.read(u"xl/worksheets/sheet2.xml").decode(u"utf-8")
    if u"Total" not in summary:
        raise Fail(u"the summary has no total line")
    off = zipped(x, shapes(x)[1][1])
    detail = off.read(u"xl/worksheets/sheet1.xml").decode(u"utf-8")
    summary = off.read(u"xl/worksheets/sheet2.xml").decode(u"utf-8")
    if u"Checks" in detail or u"Type not allowed" in detail or u"needing a look" in summary:
        raise Fail(u"with checks off the export still carries them")
    if u's="{0}"'.format(x.S_FTEXT) in detail or u's="{0}"'.format(x.S_FTEXT) in summary:
        raise Fail(u"with checks off a row is still washed red")
    cont = zipped(x, shapes(x)[3][1])
    names = cont.read(u"xl/workbook.xml").decode(u"utf-8")
    detail = cont.read(u"xl/worksheets/sheet1.xml").decode(u"utf-8")
    summary = cont.read(u"xl/worksheets/sheet2.xml").decode(u"utf-8")
    if u'name="Containment"' not in names:
        raise Fail(u"the containment export's tab is not called Containment")
    for text in (u">Run<", u">Type<", u"Cable Tray: Ladder", u"300x100", u"No service type"):
        if text not in detail:
            raise Fail(u"the containment rows sheet is missing {0!r}".format(text))
    if u"Trays and conduits" not in summary or u">Runs<" not in summary:
        raise Fail(u"the containment summary does not use its own words")
    duct = zipped(x, shapes(x)[2][1]).read(u"xl/worksheets/sheet1.xml").decode(u"utf-8")
    if u"Duct Type" not in duct or u"600x300" not in duct:
        raise Fail(u"the duct export does not use its own words")
    lines = core.export_summary([(u"A", [{u"count": 2, u"length_ft": 10.0, u"flag": True,
                                          u"systems": [u"S1"], u"fitting_ids": [1, 2]},
                                         {u"count": 1, u"length_ft": 0.0, u"flag": False,
                                          u"systems": [u"S1"], u"fitting_ids": [2]}])])
    if lines[0][u"pipes"] != 3 or lines[0][u"systems"] != 1 or lines[0][u"fittings"] != 2 \
            or lines[0][u"flagged"] != 1:
        raise Fail(u"export_summary counts wrong: {0}".format(lines[0]))


def run(x, quiet=False):
    failed = []
    for label, sheets in shapes(x):
        try:
            check_workbook(zipped(x, sheets))
        except Exception as error:
            failed.append((label, error))
    try:
        check_content(x)
    except Exception as error:
        failed.append((u"content", error))
    if not quiet:
        for label, error in failed:
            sys.stdout.write(u"FAIL {0}: {1}\n".format(label, error))
        sys.stdout.write(u"{0} workbooks checked, {1} failed\n".format(
            len(shapes(x)) + 1, len(failed)))
    return failed


BREAKAGES = [
    (u"autoFilter before sheetData",
     (u'    parts.append(u"<sheetData>{0}</sheetData>".format(u"".join(rows)))\n'
      u'    if sheet.autofilter and sheet.rows:\n'
      u'        parts.append(u\'<autoFilter ref="A1:{0}"/>\'.format(last))',
      u'    if sheet.autofilter and sheet.rows:\n'
      u'        parts.append(u\'<autoFilter ref="A1:{0}"/>\'.format(last))\n'
      u'    parts.append(u"<sheetData>{0}</sheetData>".format(u"".join(rows)))')),
    (u"sheetPr after dimension",
     (u"             u'<sheetPr><pageSetUpPr fitToPage=\"1\"/></sheetPr>',\n"
      u"             u'<dimension ref=\"A1:{0}\"/>'.format(last)]",
      u"             u'<dimension ref=\"A1:{0}\"/>'.format(last),\n"
      u"             u'<sheetPr><pageSetUpPr fitToPage=\"1\"/></sheetPr>']")),
    (u"checks column kept with checks off",
     (u"    if checks:\n        columns.append(", u"    if True:\n        columns.append(")),
    (u"rows washed red with checks off",
     (u'flag = bool(row.get(u"flag")) and checks', u'flag = bool(row.get(u"flag"))')),
    (u"titles ignore the tab",
     (u"    titles = core.field_titles(domain)", u"    titles = core.field_titles(None)")),
    (u"every tab named Pipe systems",
     (u"    detail = Sheet(core.domain_info(domain)[u\"export\"], columns, rows)",
      u"    detail = Sheet(u\"Pipe systems\", columns, rows)")),
    (u"every tab selected",
     (u"sheet_xml(sheet, i == 0)", u"sheet_xml(sheet, True)")),
    (u"tab names not cut to 31",
     (u"        candidate = base[:31]\n", u"        candidate = base\n")),
    (u"bad characters left in tab names",
     (u'base = _BAD_SHEET.sub(u" ", u"{0}".format(name or u""))',
      u'base = (u"{0}".format(name or u""))')),
    (u"cellXfs count wrong",
     (u"<cellXfs count=\"12\">", u"<cellXfs count=\"11\">")),
    (u"a sheet with no content type",
     (u"    for i in range(count):\n        content.append(",
      u"    for i in range(count - 1):\n        content.append(")),
    (u"a style index that does not exist",
     (u"    S_TTEXT, S_TINT, S_TDEC = range(12)", u"    S_TTEXT, S_TINT, S_TDEC = range(3, 15)")),
    (u"text not escaped",
     (u'.replace(u"&", u"&amp;")', u'.replace(u"&&", u"&amp;")')),
    (u"autofilter without its defined name",
     (u'        book.append(u"<definedNames>{0}</definedNames>".format(u"".join(defined)))',
      u'        pass')),
    (u"sizes written as text",
     (u"            size = core.size_number(row.get(u\"size\"))",
      u"            size = None")),
    (u"no total line",
     (u"    if lines:\n        all_rows", u"    if False:\n        all_rows")),
]


def selftest():
    if run(load_xlsx_module(), quiet=True):
        sys.stdout.write(u"selftest needs a clean run first\n")
        return 1
    missed = []
    for label, patch in BREAKAGES:
        if not run(load_xlsx_module(patch), quiet=True):
            missed.append(label)
            sys.stdout.write(u"MISSED {0}\n".format(label))
    sys.stdout.write(u"selftest: {0} breakages, {1} missed\n".format(len(BREAKAGES), len(missed)))
    return 1 if missed else 0


def main():
    if u"--selftest" in sys.argv:
        return selftest()
    return 1 if run(load_xlsx_module()) else 0


if __name__ == u"__main__":
    sys.exit(main())
