# -*- coding: utf-8 -*-
"""Nudge - logic bench. Runs under plain CPython against a stub Revit API.

    python bench_logic.py              run the checks
    python bench_logic.py --selftest   break the engine on purpose, one way at
                                       a time, and prove a check catches each

Not loaded by pyRevit - nothing imports it.
"""

from __future__ import print_function

import os
import sys
import types
import io

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.normpath(os.path.join(HERE, '..', '..', '..', '..', 'lib'))
ENGINE = os.path.join(LIB, 'revobim', 'nudge.py')

MM = 1.0 / 304.8


# ---------------------------------------------------------------------------
# stub Revit API
# ---------------------------------------------------------------------------

def build_stubs(with_framing_category=True):
    log = {'moves': []}

    class XYZ(object):
        def __init__(s, x, y, z):
            s.X, s.Y, s.Z = x, y, z

    class ElementId(object):
        InvalidElementId = None

        def __init__(s, v):
            s.Value = v

        def __eq__(s, o):
            return isinstance(o, ElementId) and o.Value == s.Value

        def __ne__(s, o):
            return not s.__eq__(o)

        def __hash__(s):
            return hash(s.Value)
    ElementId.InvalidElementId = ElementId(-1)

    class StorageType(object):
        Double = 'Double'

    class BIP(object):
        pass
    for name in ('RBS_OFFSET_PARAM', 'RBS_START_OFFSET_PARAM',
                 'RBS_END_OFFSET_PARAM', 'INSTANCE_FREE_HOST_OFFSET_PARAM',
                 'INSTANCE_ELEVATION_PARAM', 'STRUCTURAL_BEAM_END0_ELEVATION',
                 'STRUCTURAL_BEAM_END1_ELEVATION'):
        setattr(BIP, name, name)

    class BIC(object):
        pass
    cats = ['OST_PipeFitting', 'OST_DuctFitting', 'OST_CableTrayFitting',
            'OST_ConduitFitting', 'OST_PipeAccessory', 'OST_DuctAccessory',
            'OST_MechanicalEquipment', 'OST_ElectricalEquipment',
            'OST_ElectricalFixtures', 'OST_PlumbingFixtures',
            'OST_LightingFixtures', 'OST_Sprinklers', 'OST_GenericModel',
            'OST_FabricationDuctwork', 'OST_FabricationPipework',
            'OST_FabricationContainment', 'OST_FabricationHangers']
    if with_framing_category:
        cats.append('OST_MEPAncillaryFraming')
    ids = {}
    for i, name in enumerate(cats):
        ids[name] = -2000000 - i
        setattr(BIC, name, -2000000 - i)

    class ElementTransformUtils(object):
        @staticmethod
        def MoveElement(doc, eid, vector):
            element = doc.by_id[eid.Value]
            if element.Pinned:
                raise Exception('pinned element cannot move')
            log['moves'].append((eid.Value, vector.Z))
            element.translate(vector.Z)

    class Transaction(object):
        def __init__(s, doc, name):
            s.on = False

        def Start(s):
            s.on = True

        def Commit(s):
            s.on = False

        def RollBack(s):
            s.on = False

        def HasStarted(s):
            return s.on

    class FabricationPart(object):
        pass

    DB = types.ModuleType('Autodesk.Revit.DB')
    DB.XYZ = XYZ
    DB.ElementId = ElementId
    DB.StorageType = StorageType
    DB.BuiltInParameter = BIP
    DB.BuiltInCategory = BIC
    DB.ElementTransformUtils = ElementTransformUtils
    DB.Transaction = Transaction
    DB.FabricationPart = FabricationPart

    revit = types.ModuleType('Autodesk.Revit')
    revit.DB = DB
    mods = {
        'Autodesk': types.ModuleType('Autodesk'),
        'Autodesk.Revit': revit,
        'Autodesk.Revit.DB': DB,
        'Autodesk.Revit.UI': types.ModuleType('Autodesk.Revit.UI'),
    }
    for mod, names in (('Autodesk.Revit.DB.Plumbing', ['Pipe', 'FlexPipe']),
                       ('Autodesk.Revit.DB.Mechanical', ['Duct', 'FlexDuct']),
                       ('Autodesk.Revit.DB.Electrical',
                        ['CableTray', 'Conduit'])):
        m = types.ModuleType(mod)
        for n in names:
            setattr(m, n, type(n, (object,), {}))
        mods[mod] = m
    sel = types.ModuleType('Autodesk.Revit.UI.Selection')
    sel.ISelectionFilter = object
    sel.ObjectType = types.SimpleNamespace(Element='Element')
    mods['Autodesk.Revit.UI.Selection'] = sel
    exc = types.ModuleType('Autodesk.Revit.Exceptions')
    exc.OperationCanceledException = type('OCE', (Exception,), {})
    mods['Autodesk.Revit.Exceptions'] = exc

    class _List(object):
        def __getitem__(s, t):
            return Coll
    scg = types.ModuleType('System.Collections.Generic')
    scg.List = _List()
    mods['System'] = types.ModuleType('System')
    mods['System.Collections'] = types.ModuleType('System.Collections')
    mods['System.Collections.Generic'] = scg

    return mods, DB, ids, log, mods['Autodesk.Revit.DB.Plumbing'].Pipe


class Coll(object):
    def __init__(s, items=None):
        s.items = list(items or [])

    def Add(s, x):
        s.items.append(x)

    def __iter__(s):
        return iter(s.items)

    @property
    def Count(s):
        return len(s.items)


class Param(object):
    def __init__(s, v, read_only=False):
        s.v = v
        s.IsReadOnly = read_only
        s.StorageType = 'Double'

    def AsDouble(s):
        return s.v

    def Set(s, v):
        s.v = v
        return True


class Level(object):
    def __init__(s, project_elevation, survey_elevation):
        s.ProjectElevation = project_elevation
        s.Elevation = survey_elevation


class Conn(object):
    def __init__(s, owner, z):
        s.owner = owner
        s.z = z

    @property
    def Origin(s):
        return types.SimpleNamespace(Z=s.z + s.owner.dz)


class LivePoint(object):
    """A location point that follows the element as it moves."""

    def __init__(s, owner, z):
        s.owner = owner
        s.z = z

    @property
    def Point(s):
        return types.SimpleNamespace(Z=s.z + s.owner.dz)


class RodInfo(object):
    def __init__(s, lengths, hosted=False):
        s.lengths = list(lengths)
        s.CanRodsBeHosted = hosted

    @property
    def RodCount(s):
        return len(s.lengths)

    def GetRodLength(s, i):
        return s.lengths[i]

    def SetRodLength(s, i, v):
        s.lengths[i] = v


# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------

def load_engine(source=None, with_framing_category=True):
    for name in list(sys.modules):
        if name.startswith(('revobim', 'Autodesk', 'System')):
            del sys.modules[name]
    mods, DB, ids, log, Pipe = build_stubs(with_framing_category)
    sys.modules.update(mods)
    if source is None:
        source = io.open(ENGINE, encoding='utf-8').read()
    module = types.ModuleType('revobim.nudge')
    module.__file__ = ENGINE
    exec(compile(source, ENGINE, 'exec'), module.__dict__)
    return module, DB, ids, log, Pipe


def run_checks(source=None):
    failures = []

    def check(name, ok):
        if not ok:
            failures.append(name)

    nudge, DB, ids, log, Pipe = load_engine(source)

    class Doc(object):
        def __init__(s):
            s.by_id = {}
            s.regens = 0

        def GetElement(s, eid):
            return s.by_id.get(eid.Value)

        def Regenerate(s):
            s.regens += 1
            for e in s.by_id.values():
                if getattr(e, 'carried_by', None) is not None:
                    e.dz = e.carried_by.dz

    doc = Doc()
    # The survey offset must NOT be a multiple of the rounding: at a tidy
    # +45000 mm, rounding against the survey level lands in the same place
    # as rounding against the project level and the check is inert. Real
    # survey offsets are rarely that tidy.
    level = Level(3000 * MM, 3000 * MM + 45002 * MM)
    doc.by_id[100] = level

    class Cat(object):
        def __init__(s, i):
            s.Id = DB.ElementId(i)
            s.Name = 'Cat'

    def make(kind, eid, cat=None, params=None):
        base = DB.FabricationPart if kind.startswith('fab') else object
        if kind == 'pipe':
            base = Pipe

        class E(base):
            pass
        e = E()
        e.Id = DB.ElementId(eid)
        e.Document = doc
        e.LevelId = DB.ElementId(100)
        e.Category = Cat(cat) if cat is not None else None
        e.Pinned = False
        e.dz = 0.0
        e._params = params or {}
        e.Location = None
        e.get_Parameter = lambda b, e=e: e._params.get(b)

        def translate(z, e=e):
            e.dz += z
        e.translate = translate
        doc.by_id[eid] = e
        return e

    # ---- 1. pipe, middle elevation snapped -------------------------------
    pipe = make('pipe', 1, params={'RBS_OFFSET_PARAM': Param(2437 * MM)})
    nudge.shift(pipe, 50 * MM, 5 * MM)
    check('pipe middle elevation 2437+50 -> 2485',
          abs(pipe._params['RBS_OFFSET_PARAM'].v / MM - 2485) < 1e-6)

    # ---- 2. fab straight: always nudgeable, measured against its level ---
    duct = make('fab', 2, cat=ids['OST_FabricationDuctwork'])
    duct.IsAStraight = lambda: True
    duct.IsAHanger = lambda: False
    # centreline 2437 mm above a level at 3000 mm project elevation
    duct.ConnectorManager = types.SimpleNamespace(
        Connectors=[Conduit_ for Conduit_ in
                    (Conn(duct, (3000 + 2437) * MM),
                     Conn(duct, (3000 + 2437) * MM))])
    check('fab straight allowed with every toggle off',
          nudge.is_nudgeable(duct, False, False))
    route = nudge.shift(duct, 50 * MM, 5 * MM)
    check('fab straight routed as fabrication part',
          route == u'fabrication part')
    check('fab straight lands on 2485 above its level (ProjectElevation)',
          abs((2437 * MM + duct.dz) / MM - 2485) < 1e-6)

    # ---- 3. fab fitting gated by the fabrication toggle ------------------
    elbow = make('fab', 3, cat=ids['OST_FabricationDuctwork'])
    elbow.IsAStraight = lambda: False
    elbow.IsAHanger = lambda: False
    check('fab fitting refused with fabrication off',
          not nudge.is_nudgeable(elbow, True, False))
    check('fab fitting allowed with fabrication on',
          nudge.is_nudgeable(elbow, False, True))

    # ---- 4. fab containment and pipework categories recognised -----------
    for cat in ('OST_FabricationPipework', 'OST_FabricationContainment'):
        part = make('fab', 4, cat=ids[cat])
        part.IsAStraight = lambda: True
        check(cat + ' straight allowed', nudge.is_nudgeable(part, False, False))

    # ---- 5. hanger: gated, moved, manual rods re-cut ---------------------
    hanger = make('fab', 5, cat=ids['OST_FabricationHangers'])
    hanger.IsAHanger = lambda: True
    hanger.IsAStraight = lambda: False
    hanger.Location = LivePoint(hanger, (3000 + 2400) * MM)
    rods = RodInfo([600 * MM, 600 * MM], hosted=False)
    hanger.GetRodInfo = lambda: rods
    check('hanger refused with fabrication off',
          not nudge.is_nudgeable(hanger, True, False))
    check('hanger allowed with fabrication on',
          nudge.is_nudgeable(hanger, False, True))
    nudge.shift(hanger, 50 * MM, 5 * MM)
    check('hanger raised 50 mm', abs(hanger.dz / MM - 50) < 1e-6)
    check('raising a hanger shortens manual rods 600 -> 550',
          all(abs(r / MM - 550) < 1e-6 for r in rods.lengths))
    nudge.shift(hanger, -50 * MM, 5 * MM)
    check('lowering a hanger lengthens manual rods back to 600',
          all(abs(r / MM - 600) < 1e-6 for r in rods.lengths))

    hosted = RodInfo([600 * MM], hosted=True)
    hanger.GetRodInfo = lambda: hosted
    nudge.shift(hanger, 50 * MM, 5 * MM)
    check('hosted rods left for Revit to re-solve',
          abs(hosted.lengths[0] / MM - 600) < 1e-6)

    short = RodInfo([30 * MM], hosted=False)
    hanger.GetRodInfo = lambda: short
    route = nudge.shift(hanger, 50 * MM, 5 * MM)
    check('rod that would go negative is left alone',
          abs(short.lengths[0] / MM - 30) < 1e-6)
    check('rod left alone is reported in the route',
          route is not None and u'left' in route)

    # ---- 6. ancillary framing --------------------------------------------
    strut = make('fi', 6, cat=ids['OST_MEPAncillaryFraming'],
                 params={'INSTANCE_FREE_HOST_OFFSET_PARAM': Param(2437 * MM)})
    check('ancillary framing gated by fabrication toggle',
          not nudge.is_nudgeable(strut, True, False)
          and nudge.is_nudgeable(strut, False, True))
    nudge.shift(strut, 50 * MM, 5 * MM)
    check('face-hosted framing written through Offset from Host',
          abs(strut._params['INSTANCE_FREE_HOST_OFFSET_PARAM'].v / MM
              - 2485) < 1e-6)

    trapeze = make('fi', 7, cat=ids['OST_MEPAncillaryFraming'], params={
        'STRUCTURAL_BEAM_END0_ELEVATION': Param(2437 * MM),
        'STRUCTURAL_BEAM_END1_ELEVATION': Param(2437 * MM)})
    route = nudge.shift(trapeze, 50 * MM, 5 * MM)
    check('line-based framing moves both end offsets together',
          route == u'start and end level offset'
          and abs(trapeze._params['STRUCTURAL_BEAM_END0_ELEVATION'].v / MM
                  - 2485) < 1e-6
          and abs(trapeze._params['STRUCTURAL_BEAM_END1_ELEVATION'].v / MM
                  - 2485) < 1e-6)

    # ---- 7. pinned element moved and re-pinned ---------------------------
    pinned = make('fab', 8, cat=ids['OST_FabricationPipework'])
    pinned.IsAStraight = lambda: True
    pinned.IsAHanger = lambda: False
    pinned.Pinned = True
    pinned.ConnectorManager = types.SimpleNamespace(
        Connectors=[Conn(pinned, (3000 + 1000) * MM)])
    nudge.shift(pinned, 50 * MM, 5 * MM)
    check('pinned fab part moved', abs(pinned.dz / MM - 50) < 1e-6)
    check('pinned fab part re-pinned', pinned.Pinned is True)

    # ---- 8. selection: hanger carried by its duct is not moved twice -----
    log['moves'][:] = []
    sel_duct = make('fab', 20, cat=ids['OST_FabricationDuctwork'])
    sel_duct.IsAStraight = lambda: True
    sel_duct.IsAHanger = lambda: False
    sel_duct.ConnectorManager = types.SimpleNamespace(
        Connectors=[Conn(sel_duct, (3000 + 2500) * MM)])
    sel_hanger = make('fab', 21, cat=ids['OST_FabricationHangers'])
    sel_hanger.IsAHanger = lambda: True
    sel_hanger.carried_by = sel_duct
    sel_hanger.Location = LivePoint(sel_hanger, (3000 + 2400) * MM)
    sel_hanger.GetRodInfo = lambda: RodInfo([600 * MM])

    class Sel(object):
        def __init__(s, ids_):
            s.ids = Coll([DB.ElementId(i) for i in ids_])

        def GetElementIds(s):
            return s.ids

        def SetElementIds(s, v):
            pass

    uidoc = types.SimpleNamespace(Document=doc, Selection=Sel([21, 20]))
    moved, skipped = nudge.nudge_selection(uidoc, 50, up=True, snap_mm=5.0)
    check('selection reports both moved', (moved, skipped) == (2, 0))
    check('carried hanger moved once, not twice',
          abs(sel_hanger.dz / MM - 50) < 1e-6)

    # a hanger NOT carried by anything is still nudged in the same pass
    lone = make('fab', 22, cat=ids['OST_FabricationHangers'])
    lone.IsAHanger = lambda: True
    lone.Location = LivePoint(lone, (3000 + 2400) * MM)
    lone.GetRodInfo = lambda: RodInfo([600 * MM])
    sel_duct.dz = 0.0
    sel_hanger.dz = 0.0
    uidoc = types.SimpleNamespace(Document=doc, Selection=Sel([22, 20]))
    nudge.nudge_selection(uidoc, 50, up=True, snap_mm=5.0)
    check('free-standing hanger still nudged alongside a duct',
          abs(lone.dz / MM - 50) < 1e-6)

    # ---- 9. engine loads on a release without MEP ancillary framing ------
    try:
        old, _, ids2, _, _ = load_engine(source, with_framing_category=False)
        check('loads without OST_MEPAncillaryFraming',
              len(old._cat_ids(old.FRAMING_CAT_NAMES)) == 0)
    except Exception:
        check('loads without OST_MEPAncillaryFraming', False)

    return failures


# ---------------------------------------------------------------------------
# selftest - each breakage must be caught
# ---------------------------------------------------------------------------

BREAKAGES = [
    ('Level.Elevation instead of ProjectElevation',
     'return level.ProjectElevation', 'return level.Elevation'),
    ('rods lengthened instead of shortened',
     'new_length = length - moved_ft', 'new_length = length + moved_ft'),
    ('carried hanger moved again',
     'and abs(now - was) > 0.5 * MM:', 'and abs(now - was) > 1e9:'),
    ('fab straights gated by the toggle',
     '        if _is_fab_straight(element):\n            return True\n',
     '        if False:\n            return True\n'),
    ('hosted rods re-cut as well',
     '        if info.CanRodsBeHosted:\n            return (0, 0)\n',
     '        if False:\n            return (0, 0)\n'),
    ('pinned element left unpinned',
     '                element.Pinned = True\n',
     '                pass\n'),
    ('framing category resolved at import',
     "FRAMING_CAT_NAMES = (\n    'OST_MEPAncillaryFraming',\n)",
     "FRAMING_CAT_NAMES = (\n    'OST_MEPAncillaryFraming',\n)\n"
     "_EAGER = DB.BuiltInCategory.OST_MEPAncillaryFraming"),
]


def selftest():
    clean = io.open(ENGINE, encoding='utf-8').read()
    base = run_checks(clean)
    if base:
        print('clean engine fails - fix that first:')
        for f in base:
            print('  -', f)
        return 1

    inert = []
    for label, old, new in BREAKAGES:
        if old not in clean:
            inert.append(label + ' (anchor text not found)')
            continue
        broken = clean.replace(old, new, 1)
        try:
            caught = run_checks(broken)
        except Exception as err:
            caught = ['raised ' + type(err).__name__]
        print('{0:<46} {1}'.format(
            label, 'caught by {0} check(s)'.format(len(caught))
            if caught else 'NOT CAUGHT'))
        if not caught:
            inert.append(label)

    if inert:
        print('\nINERT:')
        for i in inert:
            print('  -', i)
        return 1
    print('\nselftest ok - every breakage caught')
    return 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(selftest())
    result = run_checks()
    if result:
        print('FAILED:')
        for f in result:
            print('  -', f)
        sys.exit(1)
    print('all checks pass')
