# -*- coding: utf-8 -*-
"""RevoBIM PY - Style Manager logic bench.

Runs under plain CPython from this folder. The real functions are lifted out of
script.py by name and run against stub Revit objects, so what is tested is the
code that ships, not a copy of it.

    python bench_logic.py              run the checks
    python bench_logic.py --selftest   break the code on purpose, one way at a
                                       time, and confirm a check fails each time
"""
from __future__ import print_function

import ast
import io
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, 'script.py')

NAMES = ['safe_str', 'fmt_num', 'eid_int', 'dup_value', 'build_signature',
         'GROUP_COLOURS', 'GROUP_LABELS', 'group_label', 'GroupRegistry',
         'compute_duplicates', 'fill_pattern_definition', 'ASSET_IDENTITY',
         '_asset_props', 'asset_settings', 'USAGE_CAP', 'usage_text',
         'analyze_parameters', 'colour_from_int', 'choose_keeper']


# ------------------------------------------------------------------ stubs
class ElementId(object):
    InvalidElementId = None

    def __init__(self, value):
        self.Value = int(value)


ElementId.InvalidElementId = ElementId(-1)


class StorageType(object):
    String = 'String'
    ElementId = 'ElementId'
    Integer = 'Integer'
    Double = 'Double'


class Collector(object):
    def __init__(self, doc):
        self.doc = doc
        self.cat = None

    def OfCategoryId(self, eid):
        self.cat = eid.Value
        return self

    def WhereElementIsNotElementType(self):
        return iter([e for e in self.doc.elements if e.cat == self.cat])

    def WhereElementIsElementType(self):
        return iter([])


class DBStub(object):
    pass


DB = DBStub()
DB.ElementId = ElementId
DB.StorageType = StorageType
DB.FilteredElementCollector = Collector


class Param(object):
    def __init__(self, value):
        self.value = value
        self.HasValue = value is not None
        self.StorageType = StorageType.String

    def AsString(self):
        return self.value


class Category(object):
    def __init__(self, name):
        self.Name = name


class Element(object):
    """An element holding values against particular parameter definitions."""

    def __init__(self, eid, cat, values, counter):
        self.Id = ElementId(eid)
        self.cat = cat
        self.Category = Category('Cat %d' % cat)
        self.values = values          # definition -> text
        self.counter = counter

    def get_Parameter(self, definition):
        self.counter['by_definition'] = self.counter.get('by_definition', 0) + 1
        if definition in self.values:
            return Param(self.values[definition])
        return None

    def LookupParameter(self, name):
        self.counter['by_name'] = self.counter.get('by_name', 0) + 1
        for definition, value in self.values.items():
            if definition.Name == name:
                return Param(value)
        return None


class Definition(object):
    def __init__(self, name):
        self.Name = name


class ParameterElement(object):
    def __init__(self, definition):
        self.definition = definition

    def GetDefinition(self):
        return self.definition


class Doc(object):
    def __init__(self):
        self.elements = []
        self.params = {}

    def GetElement(self, eid):
        return self.params.get(eid.Value)


class UV(object):
    def __init__(self, u, v):
        self.U = u
        self.V = v


class Grid(object):
    def __init__(self, angle_deg, offset_mm, shift_mm=0.0, segments_mm=()):
        self.Angle = math.radians(angle_deg)
        self.Offset = offset_mm / 304.8
        self.Shift = shift_mm / 304.8
        self.Origin = UV(0.0, 0.0)
        self.segments = [s / 304.8 for s in segments_mm]

    def GetSegments(self):
        return list(self.segments)


class Fill(object):
    def __init__(self, grids, solid=False):
        self.grids = grids
        self.IsSolidFill = solid

    def GetFillGrids(self):
        return list(self.grids)


class Prop(object):
    def __init__(self, name, value):
        self.Name = name
        self.value = value

    @property
    def Value(self):
        return self.value

    def GetValueAsDoubles(self):
        if isinstance(self.value, (list, tuple)):
            return list(self.value)
        raise TypeError('not an array')

    def GetAllConnectedProperties(self):
        return []


class Asset(object):
    def __init__(self, props):
        self.props = props

    @property
    def Size(self):
        return len(self.props)

    def Get(self, index):
        return self.props[index]


# ------------------------------------------------------------------ loading
def load(source_text):
    tree = ast.parse(source_text)
    wanted = set(NAMES)
    pieces = []
    for node in tree.body:
        name = None
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            name = node.name
        elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
        if name in wanted:
            pieces.append(ast.get_source_segment(source_text, node))
            wanted.discard(name)
    if wanted:
        raise SystemExit('bench_logic: script.py no longer defines %s'
                         % ', '.join(sorted(wanted)))
    ns = {'unicode': str, 'math': math, 'DB': DB}
    exec(compile('\n\n'.join(pieces), 'script.py', 'exec'), ns)
    return ns


# ------------------------------------------------------------------ checks
def text_row(rid, **changes):
    """A row shaped the way gather_text_styles returns one."""
    exact = {'Font': 'arial', 'Size': '0.008202', 'Width': '1', 'Bold': '0',
             'Italic': '0', 'Underline': '0', 'Colour': '0,0,0', 'LineWeight': '1',
             'Background': '1', 'ShowBorder': '0', 'LeaderOffset': '0.006562',
             'TabSize': '0.026247', 'Arrowhead': 'arrow filled 15 degree'}
    exact.update(changes)
    return {'id': rid, 'name': 'Text %d' % rid, 'values': {'Size': '3 mm'},
            'dup': exact, 'signature': 'TEXT'}


TEXT_KEYS = ['Font', 'Size', 'Width', 'Bold', 'Italic', 'Underline', 'Colour',
             'LineWeight', 'Background', 'ShowBorder', 'LeaderOffset', 'TabSize',
             'Arrowhead']


def check_text_settings(ns):
    """Background and underline take part, and switching a rule off merges them."""
    sig = ns['build_signature']
    opaque = text_row(1, Background='0')
    transparent = text_row(2, Background='1')
    if sig(opaque, TEXT_KEYS) == sig(transparent, TEXT_KEYS):
        return 'opaque and transparent text styles were called duplicates'
    plain = text_row(3, Underline='0')
    underlined = text_row(4, Underline='1')
    if sig(plain, TEXT_KEYS) == sig(underlined, TEXT_KEYS):
        return 'underlined and plain text styles were called duplicates'
    no_background = [k for k in TEXT_KEYS if k != 'Background']
    if sig(opaque, no_background) != sig(transparent, no_background):
        return 'unticking the Background rule did not let them match'
    rows = [text_row(5), text_row(6), text_row(7, Font='calibri')]
    for row in rows:                      # what assign_groups does before grouping
        row['signature'] = sig(row, TEXT_KEYS)
    groups = ns['compute_duplicates'](rows, ns['GroupRegistry']())
    if len(groups) != 1 or groups[0]['count'] != 2:
        return 'expected one group of two, got %r' % [(g['label'], g['count'])
                                                       for g in groups]
    return None


def check_exact_values(ns):
    """Two sizes the project rounds to the same display are still different."""
    sig = ns['build_signature']
    a = text_row(1, Size='0.008202')       # 2.5 mm
    b = text_row(2, Size='0.008333')       # 2.54 mm, both shown as "3 mm"
    if a['values']['Size'] != b['values']['Size']:
        return 'test rows set up wrongly'
    if sig(a, ['Size']) == sig(b, ['Size']):
        return '2.5 mm and 2.54 mm matched because both display as 3 mm'
    return None


def check_scope(ns):
    """Object styles under different parent categories never match."""
    sig = ns['build_signature']
    row = {'values': {'ProjWeight': '2', 'Colour': '0,0,0'}}
    if sig(row, ['ProjWeight', 'Colour'], 'doors') == \
            sig(row, ['ProjWeight', 'Colour'], 'windows'):
        return 'identical subcategories under Doors and Windows were matched'
    return None


def check_colours_stable(ns):
    reg = ns['GroupRegistry']()
    reg.resolve(['a', 'b', 'c'])
    first = dict((k, reg.get(k)) for k in ('a', 'b', 'c'))
    reg.resolve(['a', 'c'])
    if reg.get('a') != first['a'] or reg.get('c') != first['c']:
        return 'groups A and C changed colour when B was resolved'
    return None


def check_fill_patterns(ns):
    define = ns['fill_pattern_definition']
    cross = define(Fill([Grid(0, 3), Grid(90, 3)]))[1]
    cross_reordered = define(Fill([Grid(90, 3), Grid(0, 3)]))[1]
    diagonal = define(Fill([Grid(45, 3), Grid(135, 3)]))[1]
    dashed = define(Fill([Grid(0, 3, segments_mm=(2, 1)), Grid(90, 3)]))[1]
    if cross != cross_reordered:
        return 'the same grids in a different order compared as different'
    if cross == diagonal:
        return 'a square cross-hatch and a diagonal one compared as the same'
    if cross == dashed:
        return 'a dashed grid and a solid grid compared as the same'
    if define(Fill([], solid=True))[1] != 'solid':
        return 'solid fill not recognised'
    return None


def check_assets(ns):
    settings = ns['asset_settings']
    red = Asset([Prop('UIName', 'Red paint'), Prop('description', 'one'),
                 Prop('generic_diffuse', (0.8, 0.1, 0.1, 1.0)),
                 Prop('generic_glossiness', 0.5)])
    red_renamed = Asset([Prop('UIName', 'Paint - red'), Prop('description', 'two'),
                         Prop('generic_diffuse', (0.8, 0.1, 0.1, 1.0)),
                         Prop('generic_glossiness', 0.5)])
    blue = Asset([Prop('UIName', 'Red paint'), Prop('description', 'one'),
                  Prop('generic_diffuse', (0.1, 0.1, 0.8, 1.0)),
                  Prop('generic_glossiness', 0.5)])
    if settings(red)[0] != settings(red_renamed)[0]:
        return 'two assets differing only in name and description compared different'
    if settings(red)[0] == settings(blue)[0]:
        return 'a red and a blue generic asset compared as the same'
    return None


def build_doc(rows_spec, elements_spec):
    """rows_spec: [(param id, name)]; elements_spec: [(cat, {param id: value})]."""
    doc = Doc()
    counter = {}
    defs = {}
    for pid, name in rows_spec:
        definition = Definition(name)
        defs[pid] = definition
        doc.params[pid] = ParameterElement(definition)
    for index, (cat, values) in enumerate(elements_spec):
        doc.elements.append(Element(1000 + index, cat,
                                    dict((defs[p], v) for p, v in values.items()),
                                    counter))
    return doc, counter


def check_parameter_counts(ns):
    analyse = ns['analyze_parameters']
    cap = ns['USAGE_CAP']

    # 120 elements all holding a value: counted past the old ceiling of 20,
    # stopped at the cap, shown as "50+", and the walk stops there too
    doc, counter = build_doc([(1, 'BGL_Note')], [(7, {1: 'x'})] * 120)
    row = {'id': 1, 'name': 'BGL_Note', 'param_name': 'BGL_Note', 'cat_ids': [7]}
    _lines, result = analyse(doc, [row], [row])
    count = result[1][0]
    if count < cap:
        return 'counted %d of 120 elements holding a value' % count
    if ns['usage_text'](count) != '%d+' % cap:
        return 'a capped count read %r rather than "%d+"' % (ns['usage_text'](count), cap)
    if counter.get('by_definition', 0) > cap + 1:
        return 'kept reading after the cap: %d lookups for a cap of %d' % (
            counter['by_definition'], cap)

    # an unused parameter reads 0
    doc, counter = build_doc([(2, 'BGL_Spare')], [(7, {})] * 30)
    row = {'id': 2, 'name': 'BGL_Spare', 'param_name': 'BGL_Spare', 'cat_ids': [7]}
    _lines, result = analyse(doc, [row], [row])
    if result[2][0] != 0:
        return 'an unused parameter counted %d' % result[2][0]

    # two parameters with the same name: each counts only its own values, and
    # neither is looked up by name
    doc, counter = build_doc([(3, 'Width'), (4, 'Width')],
                             [(7, {3: '10'})] * 5)
    rows = [{'id': 3, 'name': 'Width', 'param_name': 'Width', 'cat_ids': [7]},
            {'id': 4, 'name': 'Width', 'param_name': 'Width', 'cat_ids': [7]}]
    _lines, result = analyse(doc, rows, rows)
    if result[3][0] != 5 or result[4][0] != 0:
        return 'same-named parameters were confused: %d and %d' % (
            result[3][0], result[4][0])
    if counter.get('by_name'):
        return 'looked parameters up by name %d time(s)' % counter['by_name']
    return None


def check_keeper(ns):
    """Each group is merged into its most-used style; a tie is broken by name so
    the choice never depends on the order the model was read in."""
    pick = ns['choose_keeper']
    group = [{'id': 1, 'name': 'Arial 2.5', 'usage': 4},
             {'id': 2, 'name': 'Arial 2.5mm', 'usage': 212},
             {'id': 3, 'name': 'Text 2.5', 'usage': 0}]
    if pick(group)['id'] != 2:
        return 'kept "%s" rather than the most-used style' % pick(group)['name']
    tie = [{'id': 5, 'name': 'Zeta', 'usage': 7}, {'id': 6, 'name': 'alpha', 'usage': 7}]
    if pick(tie)['id'] != 6 or pick(list(reversed(tie)))['id'] != 6:
        return 'a tie was settled by read order rather than by name'
    unanalysed = [{'id': 7, 'name': 'B', 'usage': None}, {'id': 8, 'name': 'A', 'usage': 1}]
    if pick(unanalysed)['id'] != 8:
        return 'an unknown count beat a real one'
    return None


CHECKS = [check_text_settings, check_exact_values, check_scope, check_colours_stable,
          check_fill_patterns, check_assets, check_parameter_counts, check_keeper]

# (what is broken, text to find, what to put instead)
BREAKAGES = [
    ('duplicate rules ignore the exact values',
     '    if exact and key in exact:', '    if False:'),
    ('scope left out of the signature',
     '    parts = [scope]', "    parts = [u'']"),
    ('fill pattern grids compared in stored order',
     "u';'.join(sorted(exact))", "u';'.join(exact)"),
    ('asset identity fields compared',
     '        if any(word in low for word in ASSET_IDENTITY):', '        if False:'),
    ('the old 20-element ceiling put back',
     "                for row in active:\n",
     "                for row in active:\n"
     "                    if counts[row['id']] and len(where[row['id']]) >= 20:\n"
     "                        continue\n"),
    ('parameters looked up by name',
     "        definition = definitions.get(row['id'])", '        definition = None'),
    ('fall back to the name when an element lacks the parameter',
     '                return element.get_Parameter(definition)',
     '                found = element.get_Parameter(definition)\n'
     '                if found is not None:\n                    return found'),
    ('no early exit at the cap',
     "                active = [r for r in active if counts[r['id']] < USAGE_CAP]\n"
     "                if not active:\n                    break",
     '                pass'),
    ('keep the least-used style',
     '        return (-uses, safe_str(row.get(\'name\', \'\')).lower())',
     '        return (uses, safe_str(row.get(\'name\', \'\')).lower())'),
    ('settle a tie by read order',
     '        return (-uses, safe_str(row.get(\'name\', \'\')).lower())',
     '        return (-uses,)'),
    ('group colours reassigned on every read',
     '            if sig not in self.assigned:\n                self.assigned[sig] = self.next_free()',
     '            self.assigned[sig] = self.next_free()'),
]


def run(text):
    ns = load(text)
    failures = []
    for check in CHECKS:
        try:
            problem = check(ns)
        except Exception as ex:
            problem = 'raised %s: %s' % (type(ex).__name__, ex)
        if problem:
            failures.append('%s: %s' % (check.__name__, problem))
    return failures


def main():
    text = io.open(SOURCE, encoding='utf-8').read()
    failures = run(text)
    if '--selftest' not in sys.argv:
        for line in failures:
            print('  FAIL %s' % line)
        print('FAILED' if failures else 'All logic checks passed (%d).' % len(CHECKS))
        sys.exit(1 if failures else 0)

    if failures:
        print('Cannot selftest - the real code already fails:')
        for line in failures:
            print('  %s' % line)
        sys.exit(1)
    inert = []
    for label, old, new in BREAKAGES:
        if old not in text:
            inert.append('%s (text to break not found)' % label)
            print('  MISSED  %s - text to break not found' % label)
            continue
        hit = run(text.replace(old, new, 1))
        print('  %-7s %s' % ('caught' if hit else 'MISSED', label))
        if not hit:
            inert.append(label)
    if inert:
        print('SELFTEST FAILED - not caught: %s' % '; '.join(inert))
        sys.exit(1)
    print('Selftest passed - every breakage was caught.')


if __name__ == '__main__':
    main()
