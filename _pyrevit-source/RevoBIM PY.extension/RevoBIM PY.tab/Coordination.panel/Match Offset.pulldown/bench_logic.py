# -*- coding: utf-8 -*-
"""RevoBIM Match Offset - bench logic.

Runs under plain CPython from this folder, with no Revit and no WPF:

    python bench_logic.py
    python bench_logic.py --selftest

Every check runs the shipped code, not a copy of it. The Revit API is stubbed
only as far as it has to be, so measure(), shift() and the settings loader are
the real functions being tested rather than a restatement of them.

--selftest breaks each area on purpose and confirms the checks notice, because
a check nobody has tested passes for the wrong reason.
"""

import math
import os
import shutil
import sys
import tempfile
import types


# ======================================================================
# the stub API, installed before anything of the tool is imported
# ======================================================================

class Sentinel(type):
    def __getattr__(cls, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return type(str(name), (object,), {})


class XYZ(object):
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.X, self.Y, self.Z = float(x), float(y), float(z)


class ElementId(object):
    """Real ElementIds are ints. Built from a BuiltInCategory the stub hands
    back a class, so the name is hashed to a stable number - distinct per
    category, and the same one every time it is asked for."""

    def __init__(self, value=0):
        try:
            self.Value = int(value)
            return
        except Exception:
            pass
        name = getattr(value, '__name__', None) or str(value)
        self.Value = -(abs(hash(name)) % 10000000) - 1


class LocationCurve(object):
    def __init__(self, curve=None):
        self.Curve = curve


class LocationPoint(object):
    def __init__(self, point=None):
        self.Point = point


class FakeSolidBox(object):
    def __init__(self, low, high):
        self.Min = low
        self.Max = high
        self.Transform = None


class FakeFace(object):
    """A planar face: which way it points, how big it is, how high it sits."""

    def __init__(self, normal_z, area, z):
        self.FaceNormal = XYZ(0.0, 0.0, normal_z)
        self.Area = area
        self.Origin = XYZ(0.0, 0.0, z)


class FakeSolid(object):
    def __init__(self, low_z, high_z, volume=1.0, faces=None, dx=1.0, dy=1.0):
        self.Volume = volume
        self._box = FakeSolidBox(XYZ(0.0, 0.0, low_z), XYZ(dx, dy, high_z))
        self.Faces = faces or []

    def GetBoundingBox(self):
        return self._box


MOVED = []
ELEMENTS = {}


def raise_element(element, delta_ft):
    """Move a fake element the way Revit moves a real one.

    The fakes have to move for the read back to mean anything: a test whose
    element never moves proves that shift() was called, not that it worked.
    """
    delta = float(delta_ft)
    curve = getattr(element.Location, 'Curve', None) \
        if element.Location is not None else None
    if curve is not None:
        curve.start = XYZ(curve.start.X, curve.start.Y, curve.start.Z + delta)
        curve.end = XYZ(curve.end.X, curve.end.Y, curve.end.Z + delta)
    if element.box is not None:
        element.box = FakeBox(
            XYZ(element.box.Min.X, element.box.Min.Y,
                element.box.Min.Z + delta),
            XYZ(element.box.Max.X, element.box.Max.Y,
                element.box.Max.Z + delta))
    point = getattr(element.Location, 'Point', None) \
        if element.Location is not None else None
    if point is not None:
        element.Location.Point = XYZ(point.X, point.Y, point.Z + delta)
    for solid in getattr(element, 'solids', None) or []:
        box = getattr(solid, '_box', None)
        if box is not None:
            box.Min = XYZ(box.Min.X, box.Min.Y, box.Min.Z + delta)
            box.Max = XYZ(box.Max.X, box.Max.Y, box.Max.Z + delta)
        for face in getattr(solid, 'Faces', None) or []:
            face.Origin = XYZ(face.Origin.X, face.Origin.Y,
                              face.Origin.Z + delta)


class ElementTransformUtils(object):
    @staticmethod
    def MoveElement(doc, element_id, vector):
        MOVED.append((element_id, vector.Z))
        element = ELEMENTS.get(element_id.Value)
        if element is not None and not getattr(element, 'stuck', False):
            raise_element(element, vector.Z)


class FilteredElementCollector(object):
    def __init__(self, doc):
        self.doc = doc

    def OfClass(self, cls):
        return self

    def ToElements(self):
        return getattr(self.doc, 'levels', [])


class WorksharingUtils(object):
    @staticmethod
    def GetCheckoutStatus(doc, element_id):
        return getattr(doc, 'checkout_status', 'NotOwned')

    @staticmethod
    def GetWorksharingTooltipInfo(doc, element_id):
        info = types.SimpleNamespace()
        info.Owner = getattr(doc, 'owner', u"")
        return info

    @staticmethod
    def CheckoutElements(doc, ids):
        return None


class FailureOptions(object):
    def SetFailuresPreprocessor(self, preprocessor):
        self.preprocessor = preprocessor

    def SetClearAfterRollback(self, flag):
        self.clear = flag


class Transaction(object):
    """Enough of a transaction for the real apply_to to run through it."""

    def __init__(self, doc, name):
        self.doc = doc
        self.name = name
        self.rolled_back = False

    def Start(self):
        return 'Started'

    def GetFailureHandlingOptions(self):
        return FailureOptions()

    def SetFailureHandlingOptions(self, options):
        self.options = options

    def Commit(self):
        return getattr(self.doc, 'commit_result', 'Committed')

    def RollBack(self):
        self.rolled_back = True


class OperationCanceledException(Exception):
    pass


class FailureSeverity(object):
    """Stable members, unlike the Sentinel metaclass, because the code
    compares against them with =="""
    Warning = 'Warning'
    Error = 'Error'
    DocumentCorruption = 'DocumentCorruption'


class TransactionGroup(object):
    def __init__(self, doc, name):
        self.doc = doc
        self.name = name
        self.state = 'new'

    def Start(self):
        self.state = 'started'

    def Assimilate(self):
        self.state = 'assimilated'

    def RollBack(self):
        self.state = 'rolledback'


class FakeFailure(object):
    def __init__(self, severity, text, resolvable=False):
        self.severity = severity
        self.text = text
        self.resolvable = resolvable

    def GetSeverity(self):
        return self.severity

    def GetDescriptionText(self):
        return self.text

    def HasResolutions(self):
        return self.resolvable


class FakeAccessor(object):
    def __init__(self, failures):
        self.failures = failures
        self.deleted = []
        self.resolved = []

    def GetFailureMessages(self):
        return self.failures

    def DeleteWarning(self, failure):
        self.deleted.append(failure.text)

    def ResolveFailure(self, failure):
        self.resolved.append(failure.text)


class FakeDoc(object):
    IsWorkshared = False

    def __init__(self):
        self.levels = []
        self.commit_result = 'Committed'
        self.Application = types.SimpleNamespace(Username=u"drew")

    def GetElement(self, element_id):
        return ELEMENTS.get(getattr(element_id, 'Value', element_id))


def install_stubs():
    spaces = {
        'Autodesk.Revit.DB': {
            'BuiltInCategory': Sentinel('BuiltInCategory', (object,), {}),
            'BuiltInParameter': Sentinel('BuiltInParameter', (object,), {}),
            'CheckoutStatus': Sentinel('CheckoutStatus', (object,), {}),
            'ElementId': ElementId,
            'ElementTransformUtils': ElementTransformUtils,
            'FilteredElementCollector': FilteredElementCollector,
            'Level': type('Level', (object,), {}),
            'LocationCurve': LocationCurve,
            'LocationPoint': LocationPoint,
            'Options': type('Options', (object,), {}),
            'Solid': FakeSolid,
            'PlanarFace': FakeFace,
            'GeometryInstance': type('GeometryInstance', (object,), {}),
            'ViewDetailLevel': Sentinel('ViewDetailLevel', (object,), {}),
            'WorksharingUtils': WorksharingUtils,
            'XYZ': XYZ,
            'Transaction': Transaction,
            'IFailuresPreprocessor': type('IFailuresPreprocessor',
                                          (object,), {}),
            'FailureProcessingResult': Sentinel('FailureProcessingResult',
                                                (object,), {}),
            'FailureSeverity': FailureSeverity,
            'TransactionGroup': TransactionGroup,
            'Line': type('Line', (object,), {
                'CreateBound': staticmethod(
                    lambda a, b: FakeCurve(a, b))}),
            'SubTransaction': type('SubTransaction', (object,), {}),
            'RoutingPreferenceRuleGroupType': type(
                'RoutingPreferenceRuleGroupType', (object,), {
                    'Junctions': 'Junctions', 'Elbows': 'Elbows',
                    'Crosses': 'Crosses', 'Unions': 'Unions',
                    'Transitions': 'Transitions', 'Segments': 'Segments'}),
            'BuiltInParameter': Sentinel('BuiltInParameter', (object,), {}),
            'StorageType': type('StorageType', (object,), {
                'Double': 'Double', 'Integer': 'Integer',
                'String': 'String', 'ElementId': 'ElementId'}),
        },
        'Autodesk.Revit.DB.Plumbing': {
            'PlumbingUtils': type('PlumbingUtils', (object,), {}),
            'Pipe': type('Pipe', (object,), {}),
        },
        'Autodesk.Revit.DB.Structure': {
            'StructuralType': type('StructuralType', (object,), {
                'NonStructural': 'NonStructural'}),
        },
        'Autodesk.Revit.UI.Selection': {
            'ISelectionFilter': type('ISelectionFilter', (object,), {}),
            'ObjectType': Sentinel('ObjectType', (object,), {}),
        },
        'Autodesk.Revit.Exceptions': {
            'OperationCanceledException': OperationCanceledException,
        },
    }
    for path, members in spaces.items():
        module = types.ModuleType(path)
        for name, value in members.items():
            setattr(module, name, value)
        sys.modules[path] = module
        parts = path.split('.')
        for depth in range(1, len(parts)):
            parent = '.'.join(parts[:depth])
            if parent not in sys.modules:
                sys.modules[parent] = types.ModuleType(parent)
        setattr(sys.modules['.'.join(parts[:-1])], parts[-1], module)


install_stubs()

import mo_core            # noqa: E402
import mo_model           # noqa: E402
import mo_run             # noqa: E402
import mo_debug           # noqa: E402
import mos_geom as geom   # noqa: E402
import mos_model as slope_model   # noqa: E402
import mos_run            # noqa: E402
import mo_shortcuts       # noqa: E402
import mo_theme           # noqa: E402


# ======================================================================
# fakes
# ======================================================================

class FakeParam(object):
    def __init__(self, value, read_only=False, direction=1.0):
        self.value = float(value)
        self.IsReadOnly = read_only
        self.element = None
        # Which way the element goes when the value goes up: -1 for an
        # offset from host on a family hanging under a ceiling.
        self.direction = float(direction)

    def AsDouble(self):
        return self.value

    def AsElementId(self):
        return ElementId(int(self.value))

    def Set(self, value):
        """Setting the offset parameter moves the element, as Revit does."""
        delta = float(value) - self.value
        self.value = float(value)
        if self.element is not None:
            raise_element(self.element, delta * self.direction)
        return True


class FakeCurve(object):
    def __init__(self, start, end):
        self.start = start
        self.end = end

    def GetEndPoint(self, index):
        return self.start if index == 0 else self.end

    def Project(self, point):
        run = ((self.end.X - self.start.X) ** 2 +
               (self.end.Y - self.start.Y) ** 2) ** 0.5
        if run < 1e-9:
            return types.SimpleNamespace(XYZPoint=self.start)
        travelled = ((point.X - self.start.X) ** 2 +
                     (point.Y - self.start.Y) ** 2) ** 0.5
        fraction = max(0.0, min(1.0, travelled / run))
        z = self.start.Z + (self.end.Z - self.start.Z) * fraction
        return types.SimpleNamespace(
            XYZPoint=XYZ(point.X, point.Y, z))


class FakeBox(object):
    def __init__(self, low, high):
        self.Min = low
        self.Max = high


class FakeElement(object):
    """Enough of an element for the real measure() and shift() to run."""

    def __init__(self, eid=1, params=None, curve=None, box=None,
                 category=u"Pipes", category_id=100, mep=True):
        self.Id = ElementId(eid)
        self.params = params or {}
        self.Location = LocationCurve(curve) if curve is not None else None
        self.ConnectorManager = types.SimpleNamespace(Connectors=[]) \
            if mep else None
        self.box = box
        self.Category = types.SimpleNamespace(
            Name=category, Id=ElementId(category_id))
        self.Pinned = False
        self.GroupId = ElementId(-1)
        self.WorksetId = ElementId(0)
        self.LevelId = ElementId(-1)
        self.solids = []
        self.named = {}
        ELEMENTS[self.Id.Value] = self

    def get_Parameter(self, bip):
        return self.params.get(bip.__name__)

    def get_BoundingBox(self, view):
        return self.box

    def get_Geometry(self, options):
        return self.solids

    def LookupParameter(self, name):
        return self.named.get(name)


def pipe(centre_ft, diameter_ft, offset_ft=None, eid=1, slope_end=None,
         category_id=100):
    """A horizontal pipe whose centreline sits at centre_ft."""
    start = XYZ(0.0, 0.0, centre_ft)
    end = XYZ(10.0, 0.0, centre_ft if slope_end is None else slope_end)
    params = {
        'RBS_PIPE_OUTER_DIAMETER': FakeParam(diameter_ft),
    }
    if offset_ft is not None:
        params['RBS_OFFSET_PARAM'] = FakeParam(offset_ft)
    half = diameter_ft / 2.0
    box = FakeBox(XYZ(0.0, -half, centre_ft - half),
                  XYZ(10.0, half, centre_ft + half))
    element = FakeElement(eid, params, FakeCurve(start, end), box,
                          u"Pipes", category_id)
    if offset_ft is not None:
        params['RBS_OFFSET_PARAM'].element = element
    return element


def fixture(bottom_ft, top_ft, eid=2):
    """A point placed family in a category that is not point based, so it
    is measured from its box."""
    return FakeElement(eid, {}, None,
                       FakeBox(XYZ(0.0, 0.0, bottom_ft),
                               XYZ(1.0, 1.0, top_ft)),
                       u"Generic Models", eid_of(u"generic_models"),
                       mep=False)


def eid_of(key):
    return mo_model.category_id_map().get(key, -1)


def terminal(insertion_ft, bottom_ft, top_ft, key=u"air_terminals", eid=3):
    """A piece of plant or a terminal: an insertion point, and a bounding
    box that takes in whatever the family draws around it."""
    element = FakeElement(eid, {}, None,
                          FakeBox(XYZ(0.0, 0.0, bottom_ft),
                                  XYZ(1.0, 1.0, top_ft)),
                          u"Air Terminals", eid_of(key), mep=False)
    element.Location = LocationPoint(XYZ(0.0, 0.0, insertion_ft))
    return element


class Bench(object):
    def __init__(self):
        self.passed = 0
        self.failures = []

    def ok(self, label, condition):
        if condition:
            self.passed += 1
        else:
            self.failures.append(label)

    def eq(self, label, got, want, tolerance=None):
        if tolerance is None:
            self.ok(label, got == want)
            if got != want:
                self.failures[-1] = u"{0}: got {1!r}, wanted {2!r}".format(
                    label, got, want)
            return
        close = abs(float(got) - float(want)) <= tolerance
        self.ok(label, close)
        if not close:
            self.failures[-1] = u"{0}: got {1}, wanted {2}".format(
                label, got, want)


# ======================================================================
# rounding
# ======================================================================

def group_rounding(b):
    r = mo_core.round_value
    b.eq('step 0 is no rounding', r(2437.3, 0), 2437.3)
    b.eq('negative step is no rounding', r(2437.3, -5), 2437.3)
    b.eq('up to 25', r(2437.0, 25, 'up'), 2450.0)
    b.eq('up to 5', r(2437.0, 5, 'up'), 2440.0)
    b.eq('up to 50', r(2437.0, 50, 'up'), 2450.0)
    b.eq('up leaves a multiple alone', r(2450.0, 25, 'up'), 2450.0)
    b.eq('up leaves a multiple alone, float noise',
         r(2450.0000000001, 25, 'up'), 2450.0, 1e-6)
    b.eq('up just past a multiple', r(2450.2, 25, 'up'), 2475.0, 1e-6)
    b.eq('nearest rounds down below the half',
         r(2437.0, 25, 'nearest'), 2425.0)
    b.eq('nearest rounds up above the half',
         r(2440.0, 25, 'nearest'), 2450.0)
    b.eq('nearest at exactly the half rounds up',
         r(2437.5, 25, 'nearest'), 2450.0)
    b.eq('down to 25', r(2437.0, 25, 'down'), 2425.0)
    b.eq('down leaves a multiple alone', r(2450.0, 25, 'down'), 2450.0)
    b.eq('up on a negative goes towards zero',
         r(-2437.0, 25, 'up'), -2425.0)
    b.eq('down on a negative goes away from zero',
         r(-2437.0, 25, 'down'), -2450.0)
    b.eq('nearest on a negative', r(-2437.0, 25, 'nearest'), -2425.0)
    b.eq('zero stays zero', r(0.0, 25, 'up'), 0.0)
    b.eq('unknown mode falls back to up', r(2437.0, 25, 'sideways'), 2450.0)
    b.eq('a fractional step works', r(2437.0, 12.5, 'up'), 2437.5, 1e-9)
    b.eq('text in, unchanged out', r('nonsense', 25, 'up'), 'nonsense')
    b.eq('step 1 rounds to whole mm', r(2437.4, 1, 'up'), 2438.0, 1e-9)


# ======================================================================
# anchors, slopes, deltas
# ======================================================================

def group_anchors(b):
    a = mo_core.anchor_value
    b.eq('bottom anchor', a(1.0, 2.0, 3.0, mo_core.ANCHOR_BOTTOM), 1.0)
    b.eq('middle anchor', a(1.0, 2.0, 3.0, mo_core.ANCHOR_MIDDLE), 2.0)
    b.eq('top anchor', a(1.0, 2.0, 3.0, mo_core.ANCHOR_TOP), 3.0)
    b.eq('an unknown anchor is the middle', a(1.0, 2.0, 3.0, u"sideways"), 2.0)

    d = mo_core.delta_for
    b.eq('bottom delta up', d(1.0, 2.0, 3.0, u"bottom", 4.0), 3.0)
    b.eq('top delta down', d(1.0, 2.0, 3.0, u"top", 1.0), -2.0)
    b.eq('middle delta of nothing', d(1.0, 2.0, 3.0, u"middle", 2.0), 0.0)

    b.ok('a zero delta counts as matched', mo_core.already_matched(0.0))
    b.ok('0.05mm counts as matched',
         mo_core.already_matched(0.05 / mo_core.MM_PER_FT))
    b.ok('1mm does not count as matched',
         not mo_core.already_matched(1.0 / mo_core.MM_PER_FT))

    s = mo_core.slope_degrees
    b.eq('flat is zero degrees', s(0.0, 10.0), 0.0)
    b.eq('45 degrees', s(10.0, 10.0), 45.0, 1e-9)
    b.eq('a fall reads the same as a rise', s(-10.0, 10.0), 45.0, 1e-9)
    b.eq('a vertical run is 90 degrees', s(10.0, 0.0), 90.0)
    b.eq('a zero length run is flat', s(0.0, 0.0), 0.0)
    b.ok('1 in 80 is under half a degree', s(1.0, 80.0) < 0.75)


# ======================================================================
# capturing the datum
# ======================================================================

def group_capture(b):
    ft = mo_core.mm_to_ft
    cap = mo_core.capture_datum

    datum, raw, rounded, moved = cap(ft(2400), ft(2500), ft(2600), u"bottom")
    b.eq('no rounding keeps the bottom', mo_core.ft_to_mm(datum), 2400.0, 1e-6)
    b.ok('no rounding is not reported as rounding', not moved)
    b.eq('the raw value is the bottom', raw, 2400.0, 1e-6)

    datum, raw, rounded, moved = cap(ft(2437), ft(2500), ft(2600), u"bottom",
                                     0.0, 25.0, u"up", u"project")
    b.eq('rounded up on the project datum', rounded, 2450.0, 1e-6)
    b.eq('the datum carries the rounded value',
         mo_core.ft_to_mm(datum), 2450.0, 1e-6)
    b.ok('rounding is reported', moved)

    level = ft(3000)
    datum, raw, rounded, moved = cap(level + ft(2437), level + ft(2500),
                                     level + ft(2600), u"bottom",
                                     level, 25.0, u"up", u"level")
    b.eq('the level datum rounds the offset, not the elevation',
         rounded, 2450.0, 1e-6)
    b.eq('the level datum comes back as an absolute elevation',
         mo_core.ft_to_mm(datum), 5450.0, 1e-6)

    datum, raw, rounded, moved = cap(level + ft(2437), level + ft(2500),
                                     level + ft(2600), u"bottom",
                                     level, 25.0, u"up", u"project")
    b.eq('the project datum rounds the elevation',
         rounded, 5450.0, 1e-6)

    datum, raw, rounded, moved = cap(ft(2450), ft(2500), ft(2600), u"bottom",
                                     0.0, 25.0, u"up", u"project")
    b.ok('a value already on the step is not reported as rounded', not moved)

    datum, raw, rounded, moved = cap(ft(2400), ft(2500), ft(2612),
                                     u"top", 0.0, 50.0, u"up", u"project")
    b.eq('rounding works off the top anchor too', rounded, 2650.0, 1e-6)


# ======================================================================
# settings
# ======================================================================

def group_settings(b):
    parse = mo_core.parse_settings

    values = parse(u"")
    b.eq('an empty file is all defaults', values[u"round_step_mm"], u"0")
    b.eq('theme defaults to auto', values[u"theme"], u"auto")

    values = parse(u"round_step_mm=25\ntheme=light\n")
    b.eq('a value is read', values[u"round_step_mm"], u"25")
    b.eq('another value is read', values[u"theme"], u"light")
    b.eq('the rest are still defaults', values[u"round_mode"], u"up")

    values = parse(u"shortcuts_path=C:\\x\\y=z\\KeyboardShortcuts.xml")
    b.eq('a value containing = survives',
         values[u"shortcuts_path"], u"C:\\x\\y=z\\KeyboardShortcuts.xml")

    values = parse(u"nonsense\n\n# a comment\nkey_bottom=AB\n")
    b.eq('a line with no = is dropped', values[u"key_bottom"], u"AB")
    b.eq('a comment is dropped', values[u"theme"], u"auto")

    values = parse(u"a_key_this_version_never_had=1\ntheme=dark\n")
    b.eq('an unknown key does not break the load', values[u"theme"], u"dark")
    b.ok('an unknown key is not kept',
         u"a_key_this_version_never_had" not in values)

    values = parse(u"  theme  =  light  \n")
    b.eq('whitespace is trimmed', values[u"theme"], u"light")

    values = mo_core.migrate(parse(u"settings_version=0\n"))
    b.eq('migrate stamps the current version',
         values[u"settings_version"], mo_core.to_text(
             mo_core.SETTINGS_VERSION))

    text = mo_core.serialise_settings(dict(mo_core.DEFAULTS))
    round_trip = parse(text)
    same = True
    for key in mo_core.DEFAULTS:
        if round_trip.get(key) != mo_core.DEFAULTS.get(key):
            same = False
    b.ok('the defaults round trip through the file format', same)
    b.ok('serialise writes one line per key',
         len(text.strip().splitlines()) == len(mo_core.DEFAULTS))

    b.eq('the services categories are on by default',
         len(mo_core.enabled_categories(mo_core.DEFAULTS)),
         len(mo_core.DEFAULT_CATEGORY_KEYS))
    b.ok('but not all of them - moving a beam because somebody clicked one '
         'is worse than needing a box ticked first',
         len(mo_core.DEFAULT_CATEGORY_KEYS) < len(mo_core.CATEGORY_KEYS))
    b.eq('an unknown category key is dropped',
         mo_core.enabled_categories({u"categories": u"pipes|nonsense|ducts"}),
         [u"pipes", u"ducts"])
    b.eq('a repeated category key is dropped',
         mo_core.enabled_categories({u"categories": u"pipes|pipes"}),
         [u"pipes"])
    b.eq('an empty category list is empty',
         mo_core.enabled_categories({u"categories": u"  "}), [])

    b.ok('on reads as on', mo_core.is_on({u"x": u"on"}, u"x"))
    b.ok('true reads as on', mo_core.is_on({u"x": u"TRUE"}, u"x"))
    b.ok('off reads as off', not mo_core.is_on({u"x": u"off"}, u"x"))
    b.ok('a missing key reads as off', not mo_core.is_on({}, u"x"))
    b.eq('on_off writes on', mo_core.on_off(True), u"on")
    b.eq('on_off writes off', mo_core.on_off(False), u"off")

    # a real round trip on disk, in a temp APPDATA
    folder = tempfile.mkdtemp(prefix='mo_settings_')
    original = mo_core.appdata_dir
    mo_core.appdata_dir = lambda: folder
    try:
        values = dict(mo_core.DEFAULTS)
        values[u"round_step_mm"] = u"25"
        values[u"categories"] = u"pipes|ducts"
        b.ok('settings save', mo_core.save_settings(values))
        back = mo_core.load_settings()
        b.eq('settings load back', back[u"round_step_mm"], u"25")
        b.eq('the category list loads back', back[u"categories"],
             u"pipes|ducts")
        handle = open(os.path.join(folder, mo_core.SETTINGS_FILE), 'wb')
        handle.write(b"\x00\x01 not a settings file at all")
        handle.close()
        damaged = mo_core.load_settings()
        b.eq('a damaged file falls back to the defaults',
             damaged[u"round_step_mm"], u"0")
    finally:
        mo_core.appdata_dir = original
        shutil.rmtree(folder, ignore_errors=True)


# ======================================================================
# formatting and prompts
# ======================================================================

def group_categories(b):
    """The category list: every standard MEP category, under headings."""
    keys = mo_core.CATEGORY_KEYS
    ancillary = u"mep_ancillary_framing"
    b.ok('MEP ancillary framing is in the list', ancillary in keys)
    b.ok('and ticked by default', ancillary in mo_core.DEFAULT_CATEGORY_KEYS)
    b.eq('under the fabrication and supports heading',
         mo_core.category_group(ancillary), mo_core.FABRICATION)
    b.ok('measured as support steel, not as equipment',
         mo_core.is_framing(ancillary) and
         not mo_core.is_point_based(ancillary))
    b.ok('but it is not a fabrication part', not mo_core.is_fabrication(
        ancillary))
    b.ok('and not a hanger', not mo_core.is_hanger(ancillary))
    b.eq('its category is the MEP ancillary framing one',
         [r[2] for r in mo_core.CATEGORY_DEFS if r[0] == ancillary],
         [u"OST_MEPAncillaryFraming"])

    # an older settings file gets the new category added, not its list reset
    trimmed = dict(mo_core.DEFAULTS)
    trimmed[u"settings_version"] = u"5"
    trimmed[u"categories"] = u"pipes|ducts"
    out = mo_core.migrate(trimmed)
    b.eq('a v5 list somebody trimmed keeps its trim and gains the new row',
         out[u"categories"], u"pipes|ducts|mep_ancillary_framing")
    b.eq('and is stamped current', out[u"settings_version"],
         mo_core.to_text(mo_core.SETTINGS_VERSION))
    current = dict(mo_core.DEFAULTS)
    current[u"categories"] = u"pipes"
    b.eq('a current file that has it unticked keeps it unticked',
         mo_core.migrate(current)[u"categories"], u"pipes")
    b.eq('adding a key already there does not repeat it',
         mo_core.with_categories(u"a|b", (u"b", u"c")), u"a|b|c")
    b.eq('adding to an empty list', mo_core.with_categories(u"", (u"c",)),
         u"c")
    b.eq('no key appears twice', len(set(keys)), len(keys))
    labels = [row[1] for row in mo_core.CATEGORY_DEFS]
    b.eq('no label appears twice', len(set(labels)), len(labels))
    members = [row[2] for row in mo_core.CATEGORY_DEFS]
    b.eq('no BuiltInCategory appears twice', len(set(members)), len(members))
    b.ok('every member name is a BuiltInCategory name',
         all([m.startswith(u"OST_") for m in members]))
    b.ok('every group is one of the declared ones',
         all([row[3] in mo_core.CATEGORY_GROUPS
              for row in mo_core.CATEGORY_DEFS]))
    b.ok('every group has something in it',
         all([len(mo_core.categories_in(g)) > 0
              for g in mo_core.CATEGORY_GROUPS]))
    b.eq('the groups account for every category',
         sum([len(mo_core.categories_in(g))
              for g in mo_core.CATEGORY_GROUPS]), len(keys))

    # the ones Drew asked for by name, and the rest of the standard set
    for key in (u"air_terminals", u"elec_fixtures", u"pipe_insulation",
                u"duct_insulation", u"duct_lining", u"plumbing_equipment",
                u"mech_control_devices", u"telephone_devices",
                u"audio_visual", u"nurse_call_devices", u"fire_protection",
                u"medical_equipment", u"food_service"):
        b.ok('{0} is in the list'.format(key), key in keys)
    b.eq('air terminals is the right Revit category',
         [row[2] for row in mo_core.CATEGORY_DEFS
          if row[0] == u"air_terminals"], [u"OST_DuctTerminal"])
    b.eq('and specialty equipment keeps Revit own spelling of it',
         [row[2] for row in mo_core.CATEGORY_DEFS
          if row[0] == u"specialty_equipment"], [u"OST_SpecialityEquipment"])

    b.ok('every services category is on by default',
         all([row[4] for row in mo_core.CATEGORY_DEFS
              if row[3] in (mo_core.PIPEWORK, mo_core.DUCTWORK,
                            mo_core.ELECTRICAL, mo_core.FIRE)]))
    b.ok('and no structural one is',
         not any([row[4] for row in mo_core.categories_in(mo_core.OTHER)]))
    b.ok('structural framing is in the list but off',
         u"structural_framing" in keys and
         u"structural_framing" not in mo_core.DEFAULT_CATEGORY_KEYS)

    b.eq('a category knows its group',
         mo_core.category_group(u"air_terminals"), mo_core.DUCTWORK)
    b.eq('and an unknown one does not raise',
         mo_core.category_group(u"nonsense"), mo_core.OTHER)
    b.eq('a category knows its label',
         mo_core.category_label(u"air_terminals"), u"Air terminals")

    # the defaults string is the on-by-default keys and nothing else
    defaults = mo_core.enabled_categories(mo_core.DEFAULTS)
    b.eq('the default list is exactly the on-by-default keys',
         defaults, list(mo_core.DEFAULT_CATEGORY_KEYS))

    # a settings file written before the list grew is reset by the migration
    old = mo_core.parse_settings(
        u"settings_version=3\ncategories=pipes|ducts\n")
    b.eq('an old list reads back as it was written', old[u"categories"],
         u"pipes|ducts")
    migrated = mo_core.migrate(dict(old))
    b.eq('and the migration puts the new list in, so air terminals are not '
         'silently missing for anybody who had pressed Apply',
         migrated[u"categories"], mo_core.DEFAULTS[u"categories"])
    current = mo_core.migrate(mo_core.parse_settings(
        u"settings_version={0}\ncategories=pipes|ducts\n".format(
            mo_core.SETTINGS_VERSION)))
    b.eq('a list saved since is left alone', current[u"categories"],
         u"pipes|ducts")


def hanger(bearing_ft, rod_top_ft, under_ft, eid=5, one_lump=False):
    """A trapeze: a channel bearer with two rods standing on it.

    Drawn the way a fabrication hanger really is - the bearer, the rods and
    the anchors as separate solids - unless one_lump asks for the old
    single-solid shape, which is what a coarse family gives and what the
    fallback has to cope with.
    """
    box = FakeBox(XYZ(0.0, 0.0, under_ft), XYZ(1.0, 1.0, rod_top_ft))
    element = FakeElement(eid, {}, None, box,
                          u"Fabrication Hangers", eid_of(u"fab_hangers"),
                          mep=False)
    if one_lump:
        faces = [FakeFace(1.0, 48000.0, bearing_ft),
                 FakeFace(1.0, 300.0, rod_top_ft),
                 FakeFace(1.0, 300.0, rod_top_ft),
                 FakeFace(-1.0, 90000.0, under_ft)]
        element.solids = [FakeSolid(under_ft, rod_top_ft, 1.0, faces)]
        return element

    # The bearer: a channel, 2 ft long and a hand wide, with its flange tops
    # at the bearing height and the inside of its back - the bigger face -
    # an inch and a half below them.
    bearer = FakeSolid(under_ft, bearing_ft, 1.0,
                       [FakeFace(1.0, 0.07, bearing_ft),
                        FakeFace(1.0, 0.07, bearing_ft),
                        FakeFace(1.0, 0.26, bearing_ft - 0.13),
                        FakeFace(-1.0, 0.26, under_ft)],
                       dx=2.0, dy=0.13)
    rods = []
    for _ in (0, 1):
        rods.append(FakeSolid(bearing_ft - 0.13, rod_top_ft, 1.0,
                              [FakeFace(1.0, 0.0008, rod_top_ft)],
                              dx=0.03, dy=0.03))
    element.solids = [bearer] + rods
    return element


def fab_part(bottom_ft, top_ft, level_ft=0.0, relative=True, key=u"fab_ductwork",
             eid=6, box_pad=0.0):
    """A fabrication part carrying its own top and bottom of part."""
    element = FakeElement(eid, {}, None,
                          FakeBox(XYZ(0.0, 0.0, bottom_ft - box_pad),
                                  XYZ(1.0, 1.0, top_ft + box_pad)),
                          u"Fabrication Ductwork", eid_of(key), mep=False)
    element.solids = [FakeSolid(bottom_ft, top_ft)]
    element.named = {
        u"Bottom of Part": FakeParam(bottom_ft - level_ft if relative
                                     else bottom_ft),
        u"Top of Part": FakeParam(top_ft - level_ft if relative else top_ft),
    }
    return element


def group_fabrication(b):
    """Fabrication parts and hangers."""
    ft = mo_core.mm_to_ft

    for key in (u"fab_ductwork", u"fab_pipework", u"fab_containment",
                u"fab_hangers"):
        b.ok('{0} is in the list'.format(key), key in mo_core.CATEGORY_KEYS)
        b.ok('{0} is a fabrication category'.format(key),
             mo_core.is_fabrication(key))
        b.eq('{0} is under Fabrication'.format(key),
             mo_core.category_group(key), mo_core.FABRICATION)
    b.ok('only the hanger category is a hanger',
         mo_core.is_hanger(u"fab_hangers") and
         not mo_core.is_hanger(u"fab_ductwork"))
    b.ok('a Revit duct is not a fabrication part',
         not mo_core.is_fabrication(u"ducts"))
    b.ok('the fabrication categories are on by default',
         all([k in mo_core.DEFAULT_CATEGORY_KEYS for k in mo_core.FAB_KEYS]))

    # the bearing face rule on its own
    pick = mo_core.best_bearing
    b.eq('the biggest upward face wins, not the highest',
         pick([(1.0, 300.0, 9.0), (1.0, 48000.0, 2.4)]), 2.4)
    b.ok('a face pointing down is never the bearing',
         pick([(-1.0, 99999.0, 1.0)]) is None)
    b.ok('a sloping face is not a bearing either',
         pick([(0.2, 99999.0, 3.0)]) is None)
    b.eq('a face a touch off level still counts',
         pick([(0.97, 48000.0, 2.4)]), 2.4)
    b.ok('nothing upward at all gives nothing', pick([]) is None)
    b.ok('nonsense in the list is stepped over',
         pick([(None, u"x", u"y"), (1.0, 5.0, 1.5)]) == 1.5)

    # telling the bearer from the rods
    bear = mo_core.bearing_from_members
    up = mo_core.is_upright
    b.ok('a rod is upright', up(2.0, 5.0, 0.03))
    b.ok('a bearer is not', not up(2.0, 2.2, 2.0))
    b.ok('a flange plate on its side is not a rod either',
         not up(2.0, 2.13, 2.0))
    b.ok('a piece with no width at all is upright', up(2.0, 3.0, 0.0))
    rods = [(2.0, 5.0, 0.03, 0.001, [(1.0, 0.0008, 5.0)]),
            (2.0, 5.0, 0.03, 0.001, [(1.0, 0.0008, 5.0)])]
    channel = (1.87, 2.0, 2.0, 0.26,
               [(1.0, 0.07, 2.0), (1.0, 0.07, 2.0), (1.0, 0.26, 1.87)])
    b.eq('the flange the duct sits on wins, not the bigger face inside the '
         'channel', bear([channel] + rods), 2.0)
    b.eq('the biggest-face rule is the one that gets that wrong',
         mo_core.best_bearing([f for m in [channel] + rods for f in m[4]]),
         1.87)
    anchor = (4.9, 5.0, 0.33, 0.11, [(1.0, 0.11, 5.0)])
    b.eq('an anchor plate up at the soffit is not a bearer',
         bear([channel, anchor] + rods), 2.0)
    b.ok('a hanger drawn as one lump has no bearer to find',
         bear([channel]) is None)
    b.ok('and neither has one drawn as rods alone', bear(rods) is None)
    b.eq('a bearer with nothing but a rod end above it still answers',
         bear([channel, rods[0]]), 2.0)
    b.ok('nonsense in the pieces is stepped over',
         bear([channel, (u"a", u"b", u"c", u"d", None)] + rods) == 2.0)

    # a hanger measures at its bearing, not at the top of its rods
    rig = hanger(ft(2400), ft(3200), ft(2340))
    m = mo_model.measure(None, rig)
    b.ok('a hanger measures', m.ok)
    b.eq('at the top of its bearer', m.route, u"the top of its bearer")
    b.eq('which is the top of the bearer', mo_core.ft_to_mm(m.bottom),
         2400.0, 1e-6)
    b.eq('and all three anchors are it, because a hanger is one height',
         (round(m.bottom, 9), round(m.middle, 9), round(m.top, 9)),
         (round(ft(2400), 9),) * 3)
    b.ok('not the top of its rods',
         abs(mo_core.ft_to_mm(m.top) - 3200.0) > 100.0)

    # which is what makes matching a duct onto a hanger do the useful thing
    duct = pipe(ft(2500), ft(200), eid=701)
    dm = mo_model.measure(None, duct)
    datum = mo_core.capture_datum(dm.bottom, dm.middle, dm.top, u"bottom")[0]
    delta = mo_core.delta_for(m.bottom, m.middle, m.top, u"bottom", datum)
    b.eq('matching a duct bottom onto a hanger puts the bearer under the '
         'duct', mo_core.ft_to_mm(delta), 2400.0 - 2400.0 + 0.0, 1e-6)
    b.eq('and the duct bottom is where the bearer goes',
         mo_core.ft_to_mm(datum), 2400.0, 1e-6)

    rig = hanger(ft(2400), ft(3200), ft(2340), 702)
    m = mo_model.measure(None, rig, u"size", False, 0.5, None,
                         mo_core.FROM_SOLID, mo_core.FROM_PARAMETERS,
                         mo_core.FROM_BOX)
    b.eq('with the setting on the box a hanger goes back to its extents',
         m.route, u"bounding box")

    rig = hanger(ft(2400), ft(3200), ft(2340), 703)
    rig.solids = []
    m = mo_model.measure(None, rig)
    b.eq('a hanger with no solids falls back to its box', m.route,
         u"bounding box")
    b.ok('rather than refusing', m.ok)

    rig = hanger(ft(2400), ft(3200), ft(2340), 709, one_lump=True)
    m = mo_model.measure(None, rig)
    b.eq('a hanger drawn as one solid falls back to its biggest upward face',
         m.route, u"its biggest upward face")
    b.eq('which still lands on the bearer', mo_core.ft_to_mm(m.bottom),
         2400.0, 1e-6)
    b.ok('and never on the top of its rods',
         abs(mo_core.ft_to_mm(m.top) - 3200.0) > 100.0)

    # the pieces as the debug report writes them out
    rig = hanger(ft(2400), ft(3200), ft(2340), 710)
    said = u"\n".join(mo_model.hanger_lines(rig))
    b.ok('the debug report names the bearer', u"a bearer" in said)
    b.ok('and names the rods', u"a rod" in said)
    b.ok('and gives the faces it had to choose between',
         said.count(u"up face") >= 3)
    rig.solids = []
    b.ok('a hanger with no geometry says so rather than printing nothing',
         u"no solids" in u"".join(mo_model.hanger_lines(rig)))

    # a fabrication part reads its own top and bottom of part
    part = fab_part(ft(2500), ft(2900), ft(0.0), True, u"fab_ductwork", 704)
    m = mo_model.measure(None, part)
    b.ok('a fabrication part measures', m.ok)
    b.ok('from its own parameters', m.route.startswith(u"top and bottom"))
    b.eq('bottom of part', mo_core.ft_to_mm(m.bottom), 2500.0, 1e-6)
    b.eq('top of part', mo_core.ft_to_mm(m.top), 2900.0, 1e-6)
    b.eq('and the middle is between them', mo_core.ft_to_mm(m.middle),
         2700.0, 1e-6)

    # the same part with the parameters written as project elevations
    part = fab_part(ft(2500), ft(2900), ft(0.0), False, u"fab_ductwork", 705)
    m = mo_model.measure(None, part)
    b.eq('read as a project elevation it still lands right',
         mo_core.ft_to_mm(m.bottom), 2500.0, 1e-6)

    # a parameter that agrees with nothing is not trusted
    part = fab_part(ft(2500), ft(2900), 0.0, True, u"fab_ductwork", 706)
    part.named = {u"Bottom of Part": FakeParam(ft(9000)),
                  u"Top of Part": FakeParam(ft(9400))}
    m = mo_model.measure(None, part)
    b.eq('a parameter nine metres from the solids is not believed',
         m.route, u"its solids")
    b.eq('and the solids answer instead', mo_core.ft_to_mm(m.bottom),
         2500.0, 1e-6)

    # no parameter at all
    part = fab_part(ft(2500), ft(2900), 0.0, True, u"fab_ductwork", 707)
    part.named = {}
    m = mo_model.measure(None, part)
    b.eq('a part with no top or bottom of part uses its solids', m.route,
         u"its solids")
    b.ok('and still measures', m.ok)

    # the box is wider than the part, and the solids win
    part = fab_part(ft(2500), ft(2900), 0.0, True, u"fab_ductwork", 708,
                    box_pad=ft(400))
    part.named = {}
    m = mo_model.measure(None, part)
    b.eq('the solids, not the box that takes in the connectors',
         mo_core.ft_to_mm(m.bottom), 2500.0, 1e-6)

    # agreeing() on its own
    agree = mo_model.agreeing
    value, how = agree([(u"from its level", 10.0), (u"as a project elevation",
                                                    2.0)], (1.9, 4.0))
    b.eq('the reading the solids agree with wins', value, 2.0)
    b.eq('and it says which reading that was', how, u"as a project elevation")
    value, how = agree([(u"from its level", 50.0)], (1.9, 4.0))
    b.ok('neither agreeing gives nothing', value is None)
    b.ok('and says so', u"disagree" in how)
    value, how = agree([(u"from its level", 2.0)], None)
    b.ok('nothing to check against gives nothing', value is None)


class FakeRodInfo(object):
    def __init__(self, lengths, hosted=False):
        self.lengths = list(lengths)
        self.CanRodsBeHosted = hosted
        self.RodCount = len(lengths)

    def GetRodLength(self, index):
        return self.lengths[index]

    def SetRodLength(self, index, length):
        self.lengths[index] = length


def group_hanger_rods(b):
    """A hanger hangs from the soffit, so moving it changes its rods."""
    ft = mo_core.mm_to_ft
    after = mo_core.rod_length_after

    b.eq('dropping a hanger 100 makes its rods 100 longer',
         after(1.0, -ft(100)), 1.0 + ft(100), 1e-9)
    b.eq('raising it 100 makes them 100 shorter',
         after(1.0, ft(100)), 1.0 - ft(100), 1e-9)
    b.eq('not moving it leaves them alone', after(1.0, 0.0), 1.0, 1e-12)
    b.ok('raising it further than the rods are long leaves no rod',
         after(ft(300), ft(400)) is None)
    b.ok('and exactly to the soffit leaves none either',
         after(ft(300), ft(300)) is None)
    b.ok('nonsense gives nothing rather than a bad length',
         after(u"x", 1.0) is None)

    # the whole thing, against the real function
    rig = hanger(ft(2400), ft(3200), ft(2340), 801)
    rig.GetRodInfo = lambda: FakeRodInfo([ft(800), ft(800)])
    said = mo_model.keep_rod_tops(rig, -ft(150))
    b.ok('the rods are re-cut', u"2 rod" in said)

    info = FakeRodInfo([ft(800), ft(800)])
    rig = hanger(ft(2400), ft(3200), ft(2340), 802)
    rig.GetRodInfo = lambda: info
    mo_model.keep_rod_tops(rig, -ft(150))
    b.eq('each one by exactly the move', info.lengths[0], ft(950), 1e-9)
    b.eq('and the second the same', info.lengths[1], ft(950), 1e-9)

    info = FakeRodInfo([ft(800)], hosted=True)
    rig = hanger(ft(2400), ft(3200), ft(2340), 803)
    rig.GetRodInfo = lambda: info
    said = mo_model.keep_rod_tops(rig, -ft(150))
    b.eq('hosted rods are left to Revit', info.lengths[0], ft(800), 1e-12)
    b.ok('and the run says so', u"hosted" in said)

    info = FakeRodInfo([ft(100)])
    rig = hanger(ft(2400), ft(3200), ft(2340), 804)
    rig.GetRodInfo = lambda: info
    said = mo_model.keep_rod_tops(rig, ft(400))
    b.eq('a rod with nothing left is not written', info.lengths[0], ft(100),
         1e-12)
    b.ok('and it is reported rather than left quiet',
         u"no length left" in said)

    rig = hanger(ft(2400), ft(3200), ft(2340), 805)
    b.eq('a hanger with no rod info says nothing at all',
         mo_model.keep_rod_tops(rig, -ft(150)), u"")

    rig = hanger(ft(2400), ft(3200), ft(2340), 806)
    rig.GetRodInfo = lambda: FakeRodInfo([ft(800)])
    b.eq('a hanger that has not moved is left alone',
         mo_model.keep_rod_tops(rig, 0.0), u"")

    b.ok('and the tick is on by default',
         mo_core.is_on(mo_core.DEFAULTS, u"fab_hanger_rods"))


def group_point_based(b):
    """Equipment and fixtures set out on their offset from level."""
    ft = mo_core.mm_to_ft

    b.ok('an air terminal is point based',
         mo_core.is_point_based(u"air_terminals"))
    for key in (u"mech_equipment", u"elec_equipment", u"elec_fixtures",
                u"lighting_fixtures", u"plumbing_fixtures", u"sprinklers",
                u"data_devices", u"specialty_equipment"):
        b.ok('{0} is point based'.format(key), mo_core.is_point_based(key))
    for key in (u"pipes", u"ducts", u"pipe_fittings", u"duct_fittings",
                u"pipe_accessories", u"duct_accessories", u"cable_trays",
                u"generic_models", u"structural_framing",
                u"pipe_insulation"):
        b.ok('{0} is not - a fitting travels with its run and a generic '
             'model is usually a hole, and for both the extent is what '
             'matters'.format(key), not mo_core.is_point_based(key))
    b.ok('every point based key is a real category',
         all([k in mo_core.CATEGORY_KEYS
              for k in mo_core.POINT_BASED_KEYS]))

    # the box, the solids and the level offset all say different things
    plant = terminal(ft(2500), ft(1900), ft(3100))
    plant.solids = [FakeSolid(ft(2300), ft(2800))]

    m = mo_model.measure(None, plant)
    b.ok('by default it is measured from its real faces',
         m.route.startswith(u"its solid faces"))
    b.eq('bottom is the real bottom face, not the box',
         mo_core.ft_to_mm(m.bottom), 2300.0, 1e-6)
    b.eq('top is the real top face', mo_core.ft_to_mm(m.top), 2800.0, 1e-6)
    b.eq('and middle is its own offset from level - the number in the '
         'properties palette, and the one thing every family agrees on',
         mo_core.ft_to_mm(m.middle), 2500.0, 1e-6)

    m = mo_model.measure(None, plant, u"size", False, 0.5, None,
                         mo_core.FROM_INSERTION)
    b.eq('on the offset from level all three are it', m.route,
         u"its offset from level")
    b.eq('bottom', mo_core.ft_to_mm(m.bottom), 2500.0, 1e-6)
    b.eq('top - a level offset is one number, not three',
         mo_core.ft_to_mm(m.top), 2500.0, 1e-6)

    m = mo_model.measure(None, plant, u"size", False, 0.5, None,
                         mo_core.FROM_BOX)
    b.eq('on the bounding box it goes back to the extents', m.route,
         u"bounding box")
    b.eq('which reaches 400 below the lowest thing the family draws',
         mo_core.ft_to_mm(m.bottom), 1900.0, 1e-6)

    # two different families land on the same offset from level
    source = terminal(ft(2500), ft(2200), ft(2900), u"air_terminals", 601)
    target = terminal(ft(1000), ft(300), ft(1800), u"mech_equipment", 602)
    level_only = (u"size", False, 0.5, None, mo_core.FROM_INSERTION)
    datum = mo_core.capture_datum(
        *[getattr(mo_model.measure(None, source, *level_only), n)
          for n in ('bottom', 'middle', 'top')] + [u"bottom"])[0]
    after = mo_model.measure(None, target, *level_only)
    delta = mo_core.delta_for(after.bottom, after.middle, after.top,
                              u"bottom", datum)
    b.eq('the delta takes the plant to the terminal own offset from level',
         mo_core.ft_to_mm(delta), 1500.0, 1e-6)
    for anchor in (u"bottom", u"middle", u"top"):
        got = mo_core.delta_for(after.bottom, after.middle, after.top,
                                anchor, datum)
        b.eq('and {0} gives the same answer, which is the point'.format(
            anchor), mo_core.ft_to_mm(got), 1500.0, 1e-6)

    # a category that is not point based is still measured from its box
    m = mo_model.measure(None, fixture(ft(2000), ft(2400), 603))
    b.eq('a generic model keeps its extents', m.route, u"bounding box")
    b.eq('bottom', mo_core.ft_to_mm(m.bottom), 2000.0, 1e-6)

    # a point based family with no insertion point and no solids falls back
    stubborn = terminal(ft(2500), ft(2200), ft(2900), u"air_terminals", 604)
    stubborn.Location = None
    m = mo_model.measure(None, stubborn)
    b.eq('a point based family with no insertion point falls back to the box',
         m.route, u"bounding box")
    b.ok('rather than refusing', m.ok)

    # a pipe is untouched by any of it
    m = mo_model.measure(None, pipe(ft(2500), ft(100)))
    b.eq('a pipe is still measured from its size parameters', m.route,
         u"size parameters")

    b.eq('the setting defaults to the real faces', 
         mo_core.DEFAULTS[u"point_measure"], mo_core.FROM_SOLID)
    b.ok('with the offset from level still there for anyone who wants all '
         'three anchors to be it',
         mo_core.FROM_INSERTION in (u"insertion",))


def group_text(b):
    f = mo_core.format_mm
    b.eq('a whole number has no decimal', f(2450.0), u"2450")
    b.eq('a half millimetre keeps one place', f(2450.5), u"2450.5")
    b.eq('a rounding artefact reads as zero', f(0.0001), u"0")
    b.eq('a negative keeps its sign', f(-125.0), u"-125")
    b.eq('nonsense does not raise', f(u"x"), u"?")

    p = mo_core.parse_number
    b.eq('a plain number parses', p(u"25"), 25.0)
    b.eq('a decimal parses', p(u"2.5"), 2.5)
    b.eq('a thousands comma parses', p(u"2,450"), 2450.0)
    b.eq('a mm suffix parses', p(u"25mm"), 25.0)
    b.eq('empty falls back', p(u"", 7.0), 7.0)
    b.eq('nonsense falls back', p(u"abc", 7.0), 7.0)
    b.eq('None falls back', p(None, 7.0), 7.0)

    prompt = mo_core.prompt_text(u"bottom", None, False, 0)
    b.ok('the first prompt asks for the source', u"take the" in prompt)
    prompt = mo_core.prompt_text(u"bottom", 2450.0, False, 0)
    b.ok('the running prompt carries the value', u"2450" in prompt)
    b.ok('the running prompt says how to stop', u"Esc" in prompt)
    b.ok('the running prompt does not mention rounding when there is none',
         u"rounded" not in prompt)
    prompt = mo_core.prompt_text(u"bottom", 2450.0, True, 25.0)
    b.ok('the running prompt says when it rounded', u"rounded to 25" in prompt)

    b.eq('to_text on None is empty', mo_core.to_text(None), u"")
    b.eq('to_text on a number', mo_core.to_text(25), u"25")
    b.eq('eid_value reads .Value', mo_core.eid_value(ElementId(7)), 7)
    b.eq('eid_value on None is zero', mo_core.eid_value(None), 0)


# ======================================================================
# the report
# ======================================================================

def group_report(b):
    report = mo_core.Report()
    b.ok('a clean run shows nothing', not report.should_show(u"problems"))
    report.note(u"already on the datum")
    b.ok('a note alone does not open the window',
         not report.should_show(u"problems"))
    b.ok('always opens on a note', report.should_show(u"always"))
    b.ok('never stays shut', not report.should_show(u"never"))
    report.problem(u"in a group")
    b.ok('a problem opens the window', report.should_show(u"problems"))
    b.ok('never stays shut even with a problem',
         not report.should_show(u"never"))
    report.matched_one()
    report.matched_one()
    b.eq('matches are counted', report.matched, 2)
    b.eq('notes and problems are kept apart',
         (len(report.notes), len(report.problems)), (1, 1))


# ======================================================================
# measuring, against the stub API
# ======================================================================

def group_measure(b):
    ft = mo_core.mm_to_ft
    element = pipe(ft(2500), ft(100))
    m = mo_model.measure(None, element)
    b.ok('a pipe measures', m.ok)
    b.eq('the middle is the centreline', mo_core.ft_to_mm(m.middle), 2500.0,
         1e-6)
    b.eq('the bottom is half a diameter below',
         mo_core.ft_to_mm(m.bottom), 2450.0, 1e-6)
    b.eq('the top is half a diameter above',
         mo_core.ft_to_mm(m.top), 2550.0, 1e-6)
    b.eq('a level pipe has no slope', m.slope, 0.0, 1e-9)
    b.eq('the size parameters were used', m.route, u"size parameters")

    element = pipe(ft(2500), ft(100))
    element.params['RBS_REFERENCE_INSULATION_THICKNESS'] = FakeParam(ft(25))
    m = mo_model.measure(None, element, u"size", False)
    b.eq('insulation is left out by default',
         mo_core.ft_to_mm(m.top), 2550.0, 1e-6)
    m = mo_model.measure(None, element, u"size", True)
    b.eq('insulation is counted when asked for',
         mo_core.ft_to_mm(m.top), 2575.0, 1e-6)
    b.eq('insulation grows the bottom too',
         mo_core.ft_to_mm(m.bottom), 2425.0, 1e-6)

    element = pipe(ft(2500), ft(100))
    m = mo_model.measure(None, element, u"box")
    b.eq('the box route is reported', m.route, u"bounding box")
    b.eq('the box gives the same answer on a bare pipe',
         mo_core.ft_to_mm(m.bottom), 2450.0, 1e-6)

    element = pipe(ft(2500), ft(100))
    element.params = {}
    m = mo_model.measure(None, element)
    b.eq('no size parameter falls back to the box', m.route, u"bounding box")

    element = pipe(ft(2500), ft(100), slope_end=ft(2600))
    m = mo_model.measure(None, element)
    b.ok('a sloping run reports a slope', m.slope > 0.1)
    b.eq('a sloping run with no pick point uses its mid height',
         mo_core.ft_to_mm(m.middle), 2550.0, 1e-6)
    m = mo_model.measure(None, element, u"size", False, 0.5,
                         XYZ(0.0, 0.0, 0.0))
    b.eq('a sloping run measured at the start of the run',
         mo_core.ft_to_mm(m.middle), 2500.0, 1e-6)
    m = mo_model.measure(None, element, u"size", False, 0.5,
                         XYZ(10.0, 0.0, 0.0))
    b.eq('a sloping run measured at the end of the run',
         mo_core.ft_to_mm(m.middle), 2600.0, 1e-6)

    element = fixture(ft(2000), ft(2400))
    m = mo_model.measure(None, element)
    b.ok('a point placed family measures', m.ok)
    b.eq('its bottom is the box bottom', mo_core.ft_to_mm(m.bottom), 2000.0,
         1e-6)
    b.eq('its middle is the box centre', mo_core.ft_to_mm(m.middle), 2200.0,
         1e-6)
    b.eq('its top is the box top', mo_core.ft_to_mm(m.top), 2400.0, 1e-6)

    element = fixture(ft(2000), ft(2400))
    element.box = None
    m = mo_model.measure(None, element)
    b.ok('no geometry is refused rather than guessed', not m.ok)
    b.ok('and it says why', u"geometry" in m.reason)

    b.eq('half_height reads the round size',
         mo_model.half_height(pipe(0.0, ft(200)), False), ft(100), 1e-9)
    element = FakeElement(3, {'RBS_CURVE_HEIGHT_PARAM': FakeParam(ft(300))})
    b.eq('half_height prefers a rectangular height',
         mo_model.half_height(element, False), ft(150), 1e-9)
    b.ok('half_height on nothing is None',
         mo_model.half_height(FakeElement(4, {}), False) is None)


# ======================================================================
# writing, against the stub API
# ======================================================================

def group_shift(b):
    ft = mo_core.mm_to_ft
    del MOVED[:]

    element = pipe(ft(2500), ft(100), offset_ft=ft(2500))
    route = mo_model.shift(None, element, ft(50))
    b.eq('the offset parameter is the first route', route, u"offset parameter")
    b.eq('the offset parameter took the delta, not the value',
         element.params['RBS_OFFSET_PARAM'].value, ft(2550), 1e-9)
    b.eq('nothing was moved', len(MOVED), 0)

    element = pipe(ft(2500), ft(100), offset_ft=ft(2500))
    element.params['RBS_OFFSET_PARAM'].IsReadOnly = True
    route = mo_model.shift(None, element, ft(50))
    b.eq('a read only offset falls through to a move', route, u"moved")
    b.eq('the move carried the delta', MOVED[-1][1], ft(50), 1e-9)

    element = fixture(ft(2000), ft(2400))
    route = mo_model.shift(None, element, ft(-125))
    b.eq('a family with no offset parameter is moved', route, u"moved")
    b.eq('a downward move is negative', MOVED[-1][1], ft(-125), 1e-9)

    element = pipe(ft(2500), ft(100), offset_ft=ft(2500))
    route = mo_model.shift(None, element, 0.0)
    b.eq('a zero delta does nothing at all', route, u"already there")
    b.eq('and it does not write the parameter',
         element.params['RBS_OFFSET_PARAM'].value, ft(2500), 1e-9)

    element = pipe(ft(2500), ft(100))
    element.GroupId = ElementId(55)
    b.ok('an element in a group is spotted', mo_model.in_group(element))
    element.GroupId = ElementId(-1)
    b.ok('an element not in a group is not', not mo_model.in_group(element))

    element = pipe(ft(2500), ft(100))
    b.eq('an unconnected element has no connections',
         mo_model.connected_count(element), 0)
    element.ConnectorManager = types.SimpleNamespace(Connectors=[
        types.SimpleNamespace(IsConnected=True),
        types.SimpleNamespace(IsConnected=False)])
    b.eq('connections are counted', mo_model.connected_count(element), 1)

    b.eq('describe names the category and the id',
         mo_model.describe(pipe(0.0, ft(100), eid=42)), u"Pipes 42")


# ======================================================================
# the end to end rule: capture, then apply
# ======================================================================

def group_end_to_end(b):
    ft = mo_core.mm_to_ft

    for anchor, expected in ((u"bottom", 2450.0), (u"middle", 2500.0),
                             (u"top", 2550.0)):
        source = pipe(ft(2500), ft(100))
        m = mo_model.measure(None, source)
        datum, raw, rounded, moved = mo_core.capture_datum(
            m.bottom, m.middle, m.top, anchor)
        b.eq('{0} datum comes off the right edge'.format(anchor),
             mo_core.ft_to_mm(datum), expected, 1e-6)

        target = pipe(ft(1000), ft(300), offset_ft=ft(1000), eid=9)
        tm = mo_model.measure(None, target)
        delta = mo_core.delta_for(tm.bottom, tm.middle, tm.top, anchor, datum)
        mo_model.shift(None, target, delta)
        after = mo_model.measure(None, target)
        got = mo_core.anchor_value(after.bottom, after.middle, after.top,
                                   anchor)
        b.eq('a 300 pipe lands with its {0} on the datum'.format(anchor),
             mo_core.ft_to_mm(got), expected, 1e-6)

    # the whole point of bottom matching: two different sizes, one soffit
    source = pipe(ft(2500), ft(100))
    m = mo_model.measure(None, source)
    datum = mo_core.capture_datum(m.bottom, m.middle, m.top, u"top")[0]
    target = pipe(ft(1000), ft(600), offset_ft=ft(1000), eid=11)
    tm = mo_model.measure(None, target)
    mo_model.shift(None, target, mo_core.delta_for(
        tm.bottom, tm.middle, tm.top, u"top", datum))
    after = mo_model.measure(None, target)
    b.eq('a 600 pipe matched on top sits 300 lower at its centre',
         mo_core.ft_to_mm(after.middle), 2250.0, 1e-6)
    b.eq('and its top is level with the source top',
         mo_core.ft_to_mm(after.top), 2550.0, 1e-6)

    # rounding applies once, at capture, and every target lands on it
    source = pipe(ft(2437), ft(100))
    m = mo_model.measure(None, source)
    datum, raw, rounded, moved = mo_core.capture_datum(
        m.bottom, m.middle, m.top, u"bottom", 0.0, 25.0, u"up", u"project")
    b.eq('the source bottom rounds up', rounded, 2400.0, 1e-6)
    landed = []
    for index, size in enumerate((100, 250, 400)):
        target = pipe(ft(900), ft(size), offset_ft=ft(900), eid=20 + index)
        tm = mo_model.measure(None, target)
        mo_model.shift(None, target, mo_core.delta_for(
            tm.bottom, tm.middle, tm.top, u"bottom", datum))
        after = mo_model.measure(None, target)
        landed.append(round(mo_core.ft_to_mm(after.bottom), 4))
    b.eq('every target lands on the one rounded datum', landed,
         [2400.0, 2400.0, 2400.0])


# ======================================================================
# keyboard shortcuts
# ======================================================================

SAMPLE = u'''<?xml version="1.0" encoding="utf-8" standalone="yes"?>
<Shortcuts>
  <ShortcutItem CommandName="Align" CommandId="ID_ALIGN" Shortcuts="AL" Paths="Modify" />
  <ShortcutItem CommandName="Array" CommandId="ID_ARRAY" Shortcuts="AR" Paths="Modify" />
  <ShortcutItem CommandName="Beam Annotations" CommandId="ID_BEAM_ANNO" Shortcuts="AB" Paths="Annotate" />
  <ShortcutItem CommandName="Some Addin Thing" CommandId="CustomCtrl_%CustomCtrl_%Other%Panel%Thing" Shortcuts="AQ;ZZ" Paths="Other" />
  <ShortcutItem CommandName="RevoBIM Match Offset Bottom" CommandId="CustomCtrl_%CustomCtrl_%RevoBIM PY%Coordination%Match Offset%RevoBIM Match Offset Bottom" Paths="RevoBIM PY" />
  <ShortcutItem CommandName="RevoBIM Match Offset Middle" CommandId="CustomCtrl_%CustomCtrl_%RevoBIM PY%Coordination%Match Offset%RevoBIM Match Offset Middle" Shortcuts="QQ" Paths="RevoBIM PY" />
</Shortcuts>
'''

BOTTOM = u"RevoBIM Match Offset Bottom"
MIDDLE = u"RevoBIM Match Offset Middle"
TOP = u"RevoBIM Match Offset Top"


def group_shortcuts(b):
    s = mo_shortcuts

    b.eq('a key is upper cased', s.normalise_key(u"ab"), u"AB")
    b.eq('spacing is tidied', s.normalise_key(u"  ctrl   b "), u"CTRL B")
    b.eq('a plus is a separator', s.normalise_key(u"ctrl+b"), u"CTRL B")
    b.eq('an empty key stays empty', s.normalise_key(u"  "), u"")
    b.eq('several keys split on the semicolon',
         s.split_keys(u"AB;ZZ"), [u"AB", u"ZZ"])
    b.eq('a repeated key collapses', s.split_keys(u"AB;ab"), [u"AB"])
    b.eq('keys join back with a semicolon',
         s.join_keys([u"AB", u"ZZ"]), u"AB;ZZ")
    b.ok('AB is a valid key', s.key_is_valid(u"AB"))
    b.ok('F5 is a valid key', s.key_is_valid(u"F5"))
    b.ok('an empty key is not valid', not s.key_is_valid(u""))
    b.ok('punctuation is not valid', not s.key_is_valid(u"A!"))
    b.ok('a whole word is not valid', not s.key_is_valid(u"ALIGNMENT"))

    items = s.parse_items(SAMPLE)
    b.eq('every entry is found', len(items), 6)
    b.eq('the command name is read', items[0].command_name, u"Align")
    b.eq('the keys are read', items[3].keys, [u"AQ", u"ZZ"])
    b.eq('an entry with no Shortcuts reads as none', items[4].keys, [])

    b.ok('our command is found by name',
         s.find_item(items, BOTTOM) is not None)
    b.ok('a command that is not there is not found',
         s.find_item(items, u"Nothing Like This") is None)
    b.ok('the id is built the way Revit writes it',
         s.command_id_for(BOTTOM).endswith(
             u"%RevoBIM PY%Coordination%Match Offset%" + BOTTOM))

    clashes = s.find_conflicts(items, u"AB")
    b.eq('AB clashes with one command', len(clashes), 1)
    b.eq('and it names it', clashes[0].command_name, u"Beam Annotations")
    b.eq('a free key clashes with nothing',
         len(s.find_conflicts(items, u"QZ")), 0)
    b.eq('a command does not clash with itself',
         len(s.find_conflicts(items, u"QQ", MIDDLE)), 0)

    plan = s.plan_assignments(SAMPLE, [(BOTTOM, u"AB"), (MIDDLE, u"AQ"),
                                       (TOP, u"AT")])
    b.eq('the plan has one entry per assignment', len(plan), 3)
    b.ok('the bottom clash is planned for', len(plan[0][u"conflicts"]) == 1)
    b.ok('the middle clash is planned for', len(plan[1][u"conflicts"]) == 1)
    b.ok('the free key has no clash', len(plan[2][u"conflicts"]) == 0)
    b.ok('a command missing from the file is flagged',
         not plan[2][u"found"])
    b.ok('a command present in the file is not flagged', plan[0][u"found"])

    plan = s.plan_assignments(SAMPLE, [(MIDDLE, u"QQ")])
    b.ok('a key a command already has reads as already set',
         plan[0][u"already"])

    # our own three do not count as clashing with each other
    plan = s.plan_assignments(SAMPLE, [(BOTTOM, u"QQ"), (MIDDLE, u"QQ")])
    b.eq('our own commands are not reported as clashing with each other',
         len(plan[0][u"conflicts"]), 0)

    text, report = s.apply_assignments(
        SAMPLE, [(BOTTOM, u"AB")], True)
    b.eq('one assignment is reported', len(report[u"assigned"]), 1)
    b.eq('the clash is cleared', len(report[u"cleared"]), 1)
    items = s.parse_items(text)
    b.eq('our command has the key',
         s.find_item(items, BOTTOM).keys, [u"AB"])
    b.eq('the other command lost it',
         s.find_item(items, u"Beam Annotations").keys, [])
    b.ok('nothing else was disturbed',
         s.find_item(items, u"Align").keys == [u"AL"])
    b.eq('the file still has every entry', len(items), 6)

    text, report = s.apply_assignments(SAMPLE, [(BOTTOM, u"AB")], False)
    b.eq('with clearing off the assignment is refused',
         len(report[u"refused"]), 1)
    b.eq('and nothing is assigned', len(report[u"assigned"]), 0)
    b.eq('and the file is unchanged', text, SAMPLE)

    text, report = s.apply_assignments(SAMPLE, [(TOP, u"AT")], True)
    b.eq('a command not in the file is added', len(report[u"added"]), 1)
    items = s.parse_items(text)
    b.eq('the added entry is there', len(items), 7)
    b.eq('and it carries the key', s.find_item(items, TOP).keys, [u"AT"])
    b.ok('the closing tag survives', text.strip().endswith(u"</Shortcuts>"))

    text, report = s.apply_assignments(SAMPLE, [(MIDDLE, u"AQ")], True)
    items = s.parse_items(text)
    b.eq('a second key goes in front of the one already there',
         s.find_item(items, MIDDLE).keys, [u"AQ", u"QQ"])
    b.eq('the command that held AQ keeps its other key',
         s.find_item(items, u"Some Addin Thing").keys, [u"ZZ"])

    text, report = s.apply_assignments(
        SAMPLE, [(BOTTOM, u"AB"), (MIDDLE, u"AQ"), (TOP, u"AT")], True)
    items = s.parse_items(text)
    b.eq('all three land together', [
        s.find_item(items, BOTTOM).keys,
        s.find_item(items, MIDDLE).keys[:1],
        s.find_item(items, TOP).keys],
        [[u"AB"], [u"AQ"], [u"AT"]])
    b.eq('both clashes are cleared in one pass',
         len(report[u"cleared"]), 2)

    text, report = s.apply_assignments(SAMPLE, [(BOTTOM, u"A!")], True)
    b.eq('an impossible key is refused', len(report[u"refused"]), 1)

    b.ok('the shortcuts path is built from the Revit year',
         s.shortcuts_path(u"2026").replace('\\', '/').endswith(
             u"Autodesk Revit 2026/KeyboardShortcuts.xml"))
    b.eq('an override path wins',
         s.shortcuts_path(u"2026", u"D:/x.xml"), u"D:/x.xml")
    b.ok('a backup is named after the file',
         u"KeyboardShortcuts.xml.backup_" in s.backup_path(
             u"C:/x/KeyboardShortcuts.xml").replace('\\', '/'))

    # a real write, to a temp file
    folder = tempfile.mkdtemp(prefix='mo_keys_')
    try:
        path = os.path.join(folder, 'KeyboardShortcuts.xml')
        handle = open(path, 'wb')
        handle.write(SAMPLE.encode('utf-8'))
        handle.close()
        original = os.environ.get('APPDATA')
        os.environ['APPDATA'] = folder
        try:
            new_text, _report = s.apply_assignments(
                s.read_file(path), [(BOTTOM, u"AB")], True)
            backup = s.write_file(path, new_text)
            b.ok('a backup is written', os.path.isfile(backup))
            b.eq('the backup is what was there before',
                 s.read_file(backup), SAMPLE)
            b.eq('the file now carries the key',
                 s.find_item(s.parse_items(s.read_file(path)), BOTTOM).keys,
                 [u"AB"])
        finally:
            if original is None:
                os.environ.pop('APPDATA', None)
            else:
                os.environ['APPDATA'] = original
    finally:
        shutil.rmtree(folder, ignore_errors=True)


# ======================================================================
# theme
# ======================================================================

def group_theme(b):
    t = mo_theme
    b.eq('the chip goes auto to dark', t.next_in_cycle(u"auto"), u"dark")
    b.eq('the chip goes dark to light', t.next_in_cycle(u"dark"), u"light")
    b.eq('the chip goes light back to auto', t.next_in_cycle(u"light"),
         u"auto")
    b.eq('nonsense goes to dark', t.next_in_cycle(u"purple"), u"dark")
    b.eq('dark resolves to dark', t.resolve(u"dark"), u"dark")
    b.eq('light resolves to light', t.resolve(u"light"), u"light")
    b.eq('auto resolves to whatever Revit says, and to dark with no Revit',
         t.resolve(u"auto"), u"dark")
    b.ok('both palettes carry the same keys', t.keys_match())
    b.ok('the light accents are darker than the dark ones',
         t.LIGHT_PALETTE[u"BlueBrush"] != t.DARK_PALETTE[u"BlueBrush"])
    b.ok('the light background is light',
         t.LIGHT_PALETTE[u"WindowBrush"].upper() > u"#900000")
    b.eq('every palette key is a brush name ending in Brush',
         sorted(set([k.endswith(u"Brush")
                     for k in t.DARK_PALETTE])), [True])


def group_logging(b):
    """The log buffers and is written once, in a finally."""
    folder = tempfile.mkdtemp(prefix='mo_log_')
    original = mo_core.appdata_dir
    mo_core.appdata_dir = lambda: folder
    try:
        mo_core.flush_log()
        path = os.path.join(folder, mo_core.LOG_FILE)
        mo_core.log(u"one")
        mo_core.log(u"two")
        b.ok('nothing is written until the flush', not os.path.isfile(path))
        mo_core.flush_log()
        b.ok('the flush writes the file', os.path.isfile(path))
        text = open(path, 'rb').read().decode('utf-8')
        b.ok('both lines are there', u"one" in text and u"two" in text)
        b.eq('the buffer is emptied', len(mo_core._LOG_BUFFER), 0)
        mo_core.flush_log()
        again = open(path, 'rb').read().decode('utf-8')
        b.eq('a second flush writes nothing twice', again, text)
    finally:
        mo_core.appdata_dir = original
        del mo_core._LOG_BUFFER[:]
        shutil.rmtree(folder, ignore_errors=True)


def group_config(b):
    """The settings are resolved once, into the right types."""
    doc = FakeDoc()
    settings = dict(mo_core.DEFAULTS)
    config = mo_run.RunConfig(doc, u"bottom", settings)
    b.eq('the anchor is carried', config.anchor, u"bottom")
    b.eq('the label is carried', config.label, u"Bottom")
    b.eq('the step is a number', config.step, 0.0)
    b.eq('the tolerance is a number', config.slope_tol, 0.5)
    b.ok('sloped runs are skipped by default', config.skip_sloped)
    b.ok('connected fittings are skipped by default', config.skip_fittings)
    b.ok('a model that is not workshared is known to be',
         not config.workshared)
    b.eq('the services categories are on', len(config.categories),
         len(mo_core.DEFAULT_CATEGORY_KEYS))
    b.ok('moving the source is off when rounding is off',
         not config.move_source)

    settings[u"round_step_mm"] = u"25"
    config = mo_run.RunConfig(doc, u"top", settings)
    b.eq('the step parses', config.step, 25.0)
    b.ok('moving the source is on once rounding is on', config.move_source)

    settings[u"move_source_on_round"] = u"off"
    config = mo_run.RunConfig(doc, u"top", settings)
    b.ok('and off again when the tick is cleared', not config.move_source)

    settings[u"round_step_mm"] = u"nonsense"
    config = mo_run.RunConfig(doc, u"top", settings)
    b.eq('a step that will not parse is no rounding', config.step, 0.0)

    settings[u"round_step_mm"] = u"-25"
    config = mo_run.RunConfig(doc, u"top", settings)
    b.eq('a negative step is no rounding', config.step, 0.0)

    config = mo_run.RunConfig(doc, u"bottom", dict(mo_core.DEFAULTS))
    b.eq('a pipe is named as a pipe',
         config.category_key(pipe(0.0, 0.1, category_id=eid_of_pipes())),
         u"pipes")


def eid_of_pipes():
    return mo_model.category_id_map().get(u"pipes", -1)


def group_source_move(b):
    """The first element clicked lands on the rounded value too."""
    ft = mo_core.mm_to_ft
    doc = FakeDoc()
    settings = dict(mo_core.DEFAULTS)
    settings[u"round_step_mm"] = u"25"
    settings[u"round_datum"] = u"project"
    config = mo_run.RunConfig(doc, u"bottom", settings)

    report = mo_core.Report()
    source = pipe(ft(2487), ft(100), offset_ft=ft(2487), eid=301)
    datum_ft, datum_mm, measurement = mo_run.take_datum(
        doc, source, config, report)
    b.eq('the datum rounds up', datum_mm, 2450.0, 1e-6)
    b.eq('the source has not moved yet',
         mo_core.ft_to_mm(mo_model.measure(doc, source).bottom), 2437.0, 1e-6)

    moved = mo_run.apply_to(doc, source, config, datum_ft, report, None,
                            measurement)
    b.ok('the source moves', moved)
    b.eq('the source now sits on the rounded datum',
         mo_core.ft_to_mm(mo_model.measure(doc, source).bottom), 2450.0, 1e-6)
    b.eq('and it is counted as matched', report.matched, 1)

    target = pipe(ft(1000), ft(400), offset_ft=ft(1000), eid=302)
    mo_run.apply_to(doc, target, config, datum_ft, report)
    b.eq('a later element lands on the same value',
         mo_core.ft_to_mm(mo_model.measure(doc, target).bottom), 2450.0, 1e-6)
    b.eq('source and target agree exactly',
         round(mo_core.ft_to_mm(mo_model.measure(doc, source).bottom), 6),
         round(mo_core.ft_to_mm(mo_model.measure(doc, target).bottom), 6))

    # with the tick off, the source is left exactly where it was
    settings[u"move_source_on_round"] = u"off"
    config = mo_run.RunConfig(doc, u"bottom", settings)
    b.ok('the config says not to move the source', not config.move_source)

    # and with rounding off there is nothing to move it to
    settings[u"round_step_mm"] = u"0"
    settings[u"move_source_on_round"] = u"on"
    config = mo_run.RunConfig(doc, u"bottom", settings)
    b.ok('rounding off means the source is never moved',
         not config.move_source)
    report = mo_core.Report()
    source = pipe(ft(2437), ft(100), offset_ft=ft(2437), eid=303)
    datum_ft, datum_mm, measurement = mo_run.take_datum(
        doc, source, config, report)
    b.eq('an unrounded datum is the value as read', datum_mm, 2387.0, 1e-6)
    b.eq('and nothing was reported as rounded', len(report.notes), 0)

    # the top anchor rounds the top, not the centreline
    settings[u"round_step_mm"] = u"50"
    config = mo_run.RunConfig(doc, u"top", settings)
    report = mo_core.Report()
    source = pipe(ft(2500), ft(100), offset_ft=ft(2500), eid=304)
    datum_ft, datum_mm, measurement = mo_run.take_datum(
        doc, source, config, report)
    b.eq('the top rounds from the top', datum_mm, 2550.0, 1e-6)
    mo_run.apply_to(doc, source, config, datum_ft, report, None, measurement)
    b.eq('a top already on the step does not move the source',
         mo_core.ft_to_mm(mo_model.measure(doc, source).top), 2550.0, 1e-6)

    # the middle anchor rounds the centreline
    config = mo_run.RunConfig(doc, u"middle", settings)
    report = mo_core.Report()
    source = pipe(ft(2487), ft(100), offset_ft=ft(2487), eid=305)
    datum_ft, datum_mm, measurement = mo_run.take_datum(
        doc, source, config, report)
    b.eq('the middle rounds from the centreline', datum_mm, 2500.0, 1e-6)
    mo_run.apply_to(doc, source, config, datum_ft, report, None, measurement)
    b.eq('and the source centreline lands on it',
         mo_core.ft_to_mm(mo_model.measure(doc, source).middle), 2500.0, 1e-6)


def group_apply_refusals(b):
    """apply_to refuses what it should, and says so."""
    ft = mo_core.mm_to_ft
    doc = FakeDoc()
    config = mo_run.RunConfig(doc, u"bottom", dict(mo_core.DEFAULTS))
    datum = ft(2450)

    report = mo_core.Report()
    element = pipe(ft(1000), ft(100), offset_ft=ft(1000), eid=401)
    element.GroupId = ElementId(9)
    b.ok('an element in a group is refused',
         not mo_run.apply_to(doc, element, config, datum, report))
    b.eq('and it is a problem, not a note', len(report.problems), 1)
    b.ok('and the problem names the group', u"group" in report.problems[0])

    report = mo_core.Report()
    element = pipe(ft(2500), ft(100), offset_ft=ft(2500), eid=402)
    b.ok('an element already on the datum does not move',
         not mo_run.apply_to(doc, element, config, ft(2450), report))
    b.eq('and it is a note, not a problem', len(report.problems), 0)
    b.eq('the note says so', len(report.notes), 1)

    report = mo_core.Report()
    element = pipe(ft(1000), ft(100), offset_ft=ft(1000), eid=403)
    element.box = None
    element.Location = None
    b.ok('an element with no geometry is refused',
         not mo_run.apply_to(doc, element, config, datum, report))
    b.eq('and it is a problem', len(report.problems), 1)

    report = mo_core.Report()
    doc.commit_result = 'RolledBack'
    element = pipe(ft(1000), ft(100), offset_ft=ft(1000), eid=404)
    b.ok('a transaction that did not commit is refused',
         not mo_run.apply_to(doc, element, config, datum, report))
    b.ok('and it says Revit rolled it back',
         u"rolled the move back" in report.problems[0])
    b.ok('and offers the debug report when Revit said nothing',
         u"debug report" in report.problems[0] or
         u" - " in report.problems[0])
    doc.commit_result = 'Committed'

    report = mo_core.Report()
    element = pipe(ft(1000), ft(100), offset_ft=ft(1000), eid=405)
    element.params['RBS_OFFSET_PARAM'].element = None   # write goes nowhere
    b.ok('a write that does not take is refused',
         not mo_run.apply_to(doc, element, config, datum, report))
    b.ok('and it says what it read back',
         u"read back" in report.problems[0])

    report = mo_core.Report()
    element = pipe(ft(1000), ft(100), offset_ft=ft(1000), eid=406,
                   slope_end=ft(1400))
    b.ok('a sloping run is refused',
         not mo_run.apply_to(doc, element, config, datum, report))
    b.ok('and it says how steep it is',
         u"pitched" in report.problems[0])


def group_slope_basics(b):
    """Lengths, directions and gradients."""
    a = geom.Pt(0, 0, 0)
    c = geom.Pt(30, 40, 0)
    b.eq('plan length is the plan length', geom.plan_length(a, c), 50.0, 1e-9)
    b.eq('length takes the height in', geom.length(
        geom.Pt(0, 0, 0), geom.Pt(3, 4, 12)), 13.0, 1e-9)
    b.eq('a plan direction is a unit vector',
         round(geom.plan_direction(a, c)[0], 6), 0.6)
    b.ok('a vertical line has no plan direction',
         geom.plan_direction(geom.Pt(0, 0, 0), geom.Pt(0, 0, 5)) is None)

    b.eq('a level run has no gradient',
         geom.gradient(geom.Pt(0, 0, 2), geom.Pt(10, 0, 2)), 0.0, 1e-12)
    b.eq('1 in 80 falling reads negative',
         geom.gradient(geom.Pt(0, 0, 0), geom.Pt(80, 0, -1)), -0.0125, 1e-12)
    b.eq('1 in 80 rising reads positive',
         geom.gradient(geom.Pt(0, 0, 0), geom.Pt(80, 0, 1)), 0.0125, 1e-12)
    b.ok('a vertical run has no gradient at all',
         geom.gradient(geom.Pt(0, 0, 0), geom.Pt(0, 0, 5)) is None)

    b.eq('one in n reads the gradient back', geom.one_in_n(-0.0125), 80.0,
         1e-9)
    b.eq('one in n ignores the direction', geom.one_in_n(0.0125), 80.0, 1e-9)
    b.ok('level has no one in n', geom.one_in_n(0.0) is None)
    b.eq('1 in 80 back to a gradient', geom.gradient_from_n(80), 0.0125, 1e-12)
    b.eq('a silly n is level', geom.gradient_from_n(0.4), 0.0)
    b.eq('nonsense is level', geom.gradient_from_n(u"x"), 0.0)

    b.eq('a level pipe has no pitch',
         geom.pitch_degrees(geom.Pt(0, 0, 0), geom.Pt(10, 0, 0)), 0.0, 1e-9)
    b.eq('a vertical pipe is 90 degrees',
         geom.pitch_degrees(geom.Pt(0, 0, 0), geom.Pt(0, 0, 10)), 90.0, 1e-9)
    b.ok('1 in 80 is well under the upright line',
         geom.pitch_degrees(geom.Pt(0, 0, 0), geom.Pt(80, 0, -1)) < 1.0)

    b.eq('a right angle reads as 90',
         geom.plan_angle_between((1.0, 0.0), (0.0, 1.0)), 90.0, 1e-9)
    b.ok('the same direction is in line',
         geom.is_in_line((1.0, 0.0), (1.0, 0.0)))
    b.ok('the opposite direction is also in line',
         geom.is_in_line((1.0, 0.0), (-1.0, 0.0)))
    b.ok('a right angle is not in line',
         not geom.is_in_line((1.0, 0.0), (0.0, 1.0)))
    b.ok('one degree out is still in line',
         geom.is_in_line((1.0, 0.0), (0.99985, 0.01745)))


def group_slope_crossing(b):
    """Where the two centrelines cross in plan."""
    main0, main1 = geom.Pt(0, 0, 0), geom.Pt(100, 0, -1.25)
    branch0, branch1 = geom.Pt(40, -20, 3), geom.Pt(40, -5, 3)

    crossing = geom.plan_intersection(main0, main1, branch0, branch1)
    b.ok('they cross', u"refusal" not in crossing)
    b.eq('the crossing is 40 percent along the main',
         crossing[u"t_a"], 0.4, 1e-12)
    b.eq('the crossing x', crossing[u"x"], 40.0, 1e-9)
    b.eq('the crossing y', crossing[u"y"], 0.0, 1e-9)
    b.ok('the branch has to reach past its own end',
         crossing[u"t_b"] > 1.0)

    point = geom.point_on_line(main0, main1, crossing[u"t_a"])
    b.eq('the height at the crossing follows the main fall',
         point.z, -0.5, 1e-9)

    parallel = geom.plan_intersection(main0, main1, geom.Pt(0, 5, 0),
                                      geom.Pt(100, 5, 0))
    b.eq('parallel lines are refused', parallel.get(u"refusal"),
         geom.PARALLEL)
    vertical = geom.plan_intersection(main0, main1, geom.Pt(5, 5, 0),
                                      geom.Pt(5, 5, 9))
    b.eq('a vertical branch is refused', vertical.get(u"refusal"),
         geom.VERTICAL)

    beyond = geom.plan_intersection(main0, main1, geom.Pt(130, -20, 0),
                                    geom.Pt(130, -5, 0))
    b.ok('a crossing past the end reads past the end',
         beyond[u"t_a"] > 1.0)
    far = geom.point_on_line(main0, main1, beyond[u"t_a"])
    b.eq('and the apparent height carries the fall on past the end',
         far.z, -1.625, 1e-9)

    tol = 1.0 / geom.MM_PER_FT
    b.eq('a crossing in the middle is inside',
         geom.classify_main(0.5, 100.0, tol), geom.INSIDE)
    b.eq('a crossing at the far end is at the end',
         geom.classify_main(1.0, 100.0, tol), geom.AT_END)
    b.eq('a crossing at the near end is at the start',
         geom.classify_main(0.0, 100.0, tol), geom.AT_START)
    b.eq('a crossing a hair inside the end still counts as the end',
         geom.classify_main(1.0 - 0.000005, 100.0, tol), geom.AT_END)
    b.eq('a crossing well past the end is beyond it',
         geom.classify_main(1.3, 100.0, tol), geom.BEYOND_END)
    b.eq('a crossing before the start is before it',
         geom.classify_main(-0.3, 100.0, tol), geom.BEFORE_START)

    b.eq('a branch that has to stretch out is an extend',
         geom.classify_branch(1.4, tol, 15.0), geom.EXTEND)
    b.eq('a branch that crosses the main is a trim',
         geom.classify_branch(0.5, tol, 15.0), geom.TRIM)
    b.eq('a crossing behind the run is refused',
         geom.classify_branch(-0.2, tol, 15.0), geom.BEHIND)
    b.eq('a branch that already ends on the main is an extend of nothing',
         geom.classify_branch(1.0, tol, 15.0), geom.EXTEND)


def group_slope_gradient(b):
    """The gradient the branch is put on."""
    t = geom.target_gradient
    b.eq('the main fall, falling towards the junction',
         t(-0.0125, 0.0, geom.FROM_MAIN, geom.TOWARDS), -0.0125, 1e-12)
    b.eq('a rising main still gives a fall towards the junction',
         t(0.0125, 0.0, geom.FROM_MAIN, geom.TOWARDS), -0.0125, 1e-12)
    b.eq('away from the junction is the other sign',
         t(-0.0125, 0.0, geom.FROM_MAIN, geom.AWAY), 0.0125, 1e-12)
    b.eq('keeping the direction keeps a rising branch rising',
         t(-0.0125, 0.02, geom.FROM_MAIN, geom.KEEP_DIRECTION), 0.0125, 1e-12)
    b.eq('keeping the direction keeps a falling branch falling',
         t(-0.0125, -0.02, geom.FROM_MAIN, geom.KEEP_DIRECTION), -0.0125,
         1e-12)
    b.eq('a fixed 1 in 40 ignores the main',
         t(-0.0125, 0.0, geom.FIXED, geom.TOWARDS, 40.0), -0.025, 1e-12)
    b.eq('keeping the slope hands the branch its own back',
         t(-0.0125, 0.031, geom.KEEP_SLOPE, geom.TOWARDS), 0.031, 1e-12)
    b.eq('keeping the slope of a level branch is level',
         t(-0.0125, None, geom.KEEP_SLOPE, geom.TOWARDS), 0.0)
    b.eq('a level main gives a level target',
         t(0.0, 0.0, geom.FROM_MAIN, geom.TOWARDS), 0.0, 1e-12)

    b.eq('no tilt is needed when it is already right',
         geom.tilt_angle(-0.0125, -0.0125), 0.0, 1e-12)
    b.ok('tilting a level run onto a fall is a positive angle',
         geom.tilt_angle(0.0, -0.0125) > 0)
    b.ok('tilting a falling run onto level is a negative angle',
         geom.tilt_angle(-0.0125, 0.0) < 0)
    b.eq('the axis is square to the run in plan',
         geom.tilt_axis((1.0, 0.0)), (-0.0, 1.0))


def group_slope_transform(b):
    """The tilt and the stretch, checked against what they were asked for."""
    for start_grad, target in ((0.0, -0.0125), (0.02, -0.0125),
                               (-0.03, -0.025), (-0.0125, 0.0),
                               (0.0, 0.0)):
        anchor = geom.Pt(0.0, 0.0, 0.0)
        free = geom.Pt(20.0, 0.0, 20.0 * start_grad)
        v = geom.plan_direction(anchor, free)
        angle = geom.tilt_angle(geom.gradient(anchor, free), target)
        tilted = geom.apply_tilt(free, anchor, angle, geom.tilt_axis(v))
        b.eq('tilting from {0} onto {1} lands on it'.format(start_grad,
                                                            target),
             geom.gradient(tilted, free), target, 1e-9)
        b.eq('and the tilt is about the free end, which does not move',
             geom.length(free, free), 0.0)
        b.eq('and the run keeps its length',
             geom.length(tilted, free), geom.length(anchor, free), 1e-9)

    # a run that comes in at an angle in plan, not along an axis
    anchor = geom.Pt(3.0, 7.0, 12.0)
    free = geom.Pt(18.0, 27.0, 12.0)
    v = geom.plan_direction(anchor, free)
    angle = geom.tilt_angle(0.0, -0.02)
    tilted = geom.apply_tilt(free, anchor, angle, geom.tilt_axis(v))
    b.eq('a run at an angle in plan tilts the same way',
         geom.gradient(tilted, free), -0.02, 1e-9)
    b.eq('and it does not swing round in plan',
         geom.plan_direction(tilted, free), geom.plan_direction(anchor, free),
         None)
    # Tilting keeps the 3D length, so the plan length shrinks by the cosine.
    # At 1 in 50 over 25 feet that is five millimetres of the far end
    # creeping towards the junction, which is why the uprights are re-cut to
    # the run's new joint position rather than assumed to still fit.
    import math as _math
    b.eq('and its plan length shrinks by exactly the cosine',
         geom.plan_length(tilted, free),
         geom.plan_length(anchor, free) * _math.cos(angle), 1e-9)

    # stretching along the axis
    fixed = geom.Pt(0.0, 0.0, 10.0)
    direction = geom.unit3(fixed, geom.Pt(80.0, 0.0, 9.0))
    landing = geom.stretch_to_plan_point(fixed, direction, 160.0, 0.0)
    b.eq('the stretch reaches the crossing in plan', landing.x, 160.0, 1e-9)
    b.eq('and stays on its own line in plan', landing.y, 0.0, 1e-9)
    b.eq('and the height falls out of the gradient', landing.z, 8.0, 1e-9)
    short = geom.stretch_to_plan_point(fixed, direction, 40.0, 0.0)
    b.eq('trimming back works the same way', short.z, 9.5, 1e-9)
    b.ok('a vertical direction cannot be stretched in plan',
         geom.stretch_to_plan_point(fixed, (0.0, 0.0, 1.0), 5.0, 0.0) is None)


def group_slope_plan(b):
    """build_plan: the whole decision, taken before anything is touched."""
    main0, main1 = geom.Pt(0, 0, 0), geom.Pt(100, 0, -1.25)
    tol = 1.0 / geom.MM_PER_FT

    plan = geom.build_plan(main0, main1, geom.Pt(40, -20, 3),
                           geom.Pt(40, -5, 3), end_tolerance_ft=tol)
    b.ok('a crossing in the middle of the main is a plan', plan.ok)
    b.eq('and it is a tee', plan.junction, geom.TEE)
    b.eq('and it is inside the main', plan.main_case, geom.INSIDE)
    b.eq('and the branch stretches out to it', plan.branch_case, geom.EXTEND)
    b.eq('the crossing height follows the main fall', plan.crossing.z, -0.5,
         1e-9)
    b.eq('the branch is put on the main fall, towards the junction',
         plan.target_gradient, -0.0125, 1e-12)
    b.eq('the branch meets the main square on', plan.plan_angle, 90.0, 1e-9)
    b.ok('nothing is extended', not plan.extends_main)

    plan = geom.build_plan(main0, main1, geom.Pt(100, -20, 3),
                           geom.Pt(100, -5, 3), end_tolerance_ft=tol)
    b.eq('a crossing at the end of the main is a bend', plan.junction,
         geom.BEND)
    b.eq('and it is at the end', plan.main_case, geom.AT_END)
    b.ok('and nothing is extended', not plan.extends_main)

    plan = geom.build_plan(main0, main1, geom.Pt(130, -20, 3),
                           geom.Pt(130, -5, 3), end_tolerance_ft=tol,
                           allow_apparent=True, main_end_free=True)
    b.ok('an apparent crossing past a free end is allowed', plan.ok)
    b.eq('and it is a bend', plan.junction, geom.BEND)
    b.ok('and the main is extended to reach it', plan.extends_main)
    b.eq('and the branch is raised to the apparent height',
         plan.crossing.z, -1.625, 1e-9)

    plan = geom.build_plan(main0, main1, geom.Pt(130, -20, 3),
                           geom.Pt(130, -5, 3), end_tolerance_ft=tol,
                           allow_apparent=True, main_end_free=False)
    b.ok('an apparent crossing past a connected end is refused', not plan.ok)
    b.eq('and it says why', plan.refusal, u"main end connected")
    b.ok('and the refusal reads as a sentence',
         u"joined to it" in geom.refusal_text(plan.refusal))

    plan = geom.build_plan(main0, main1, geom.Pt(130, -20, 3),
                           geom.Pt(130, -5, 3), end_tolerance_ft=tol,
                           allow_apparent=False, main_end_free=True)
    b.ok('and it is refused outright when apparent is turned off',
         not plan.ok)
    b.eq('with its own reason', plan.refusal, u"apparent")

    plan = geom.build_plan(main0, main1, geom.Pt(40, 5, 3),
                           geom.Pt(40, 20, 3), end_tolerance_ft=tol)
    b.ok('a branch pointing away from the main is refused', not plan.ok)
    b.eq('and it says so', plan.refusal, geom.BEHIND)

    plan = geom.build_plan(main0, main1, geom.Pt(0, 5, 3),
                           geom.Pt(100, 5, 3), end_tolerance_ft=tol)
    b.ok('a branch running alongside the main is refused', not plan.ok)
    b.eq('as side by side rather than as plain parallel, which is the '
         'difference between "these never meet" and "these are the same run"',
         plan.refusal, u"side by side")

    plan = geom.build_plan(main0, main1, geom.Pt(0, 0, 0),
                           geom.Pt(100, 0, -1.25), end_tolerance_ft=tol)
    b.ok('a branch exactly on the main line never crosses it, so it is the '
         'in-line case rather than a junction', not plan.ok)
    b.eq('and here it is refused only because the end is not free',
         plan.refusal, u"main end connected")

    plan = geom.build_plan(main0, main1, geom.Pt(160, 1, 3),
                           geom.Pt(130, 0.5, 3), end_tolerance_ft=tol,
                           main_end_free=True)
    b.eq('a branch a degree off the main line gets a union, not a bend',
         plan.junction, geom.UNION)
    b.eq('and it meets it at the end', plan.main_case, geom.AT_END)
    plan = geom.build_plan(main0, main1, geom.Pt(160, 1, 3),
                           geom.Pt(130, 0.5, 3), end_tolerance_ft=tol,
                           main_end_free=True, in_line_tolerance_deg=0.5)
    b.eq('tighten the in-line tolerance and the same one is a bend',
         plan.junction, geom.BEND)

    plan = geom.build_plan(main0, main1, geom.Pt(40, -20, 3),
                           geom.Pt(40, -5, 3), geom.KEEP_SLOPE,
                           end_tolerance_ft=tol)
    b.eq('with the slope tick cleared the branch keeps its own fall',
         plan.target_gradient, 0.0, 1e-12)
    b.eq('and there is no tilt', plan.tilt, 0.0, 1e-12)
    b.eq('but the crossing height is still the main\'s',
         plan.crossing.z, -0.5, 1e-9)


def group_slope_end_to_end(b):
    """A real junction, worked through exactly as the tool works it.

    A 100ft main falling 1 in 80, and a level branch coming in square from
    the side, ending well short of it. Tilt about the end that meets the
    main, stretch that end out to the crossing, then raise the lot.
    """
    main0, main1 = geom.Pt(0, 0, 0), geom.Pt(100, 0, -1.25)
    anchor = geom.Pt(40, -30, 2.0)
    free = geom.Pt(40, -12, 2.0)
    tol = 1.0 / geom.MM_PER_FT

    plan = geom.build_plan(main0, main1, anchor, free, end_tolerance_ft=tol)
    b.ok('the plan is good', plan.ok)

    tilted_anchor = geom.apply_tilt(free, anchor, plan.tilt, plan.axis)
    b.eq('after the tilt the run is on the target fall',
         geom.gradient(tilted_anchor, free), plan.target_gradient, 1e-9)

    direction = geom.unit3(tilted_anchor, free)
    landing = geom.stretch_to_plan_point(tilted_anchor, direction,
                                         plan.crossing.x, plan.crossing.y)
    b.eq('the stretched end is over the crossing in x', landing.x,
         plan.crossing.x, 1e-9)
    b.eq('the stretched end is over the crossing in y', landing.y,
         plan.crossing.y, 1e-9)
    b.eq('the stretch did not change the fall',
         geom.gradient(tilted_anchor, landing), plan.target_gradient, 1e-9)

    rise = plan.crossing.z - landing.z
    final = geom.Pt(landing.x, landing.y, landing.z + rise)
    lifted_anchor = geom.Pt(tilted_anchor.x, tilted_anchor.y,
                            tilted_anchor.z + rise)
    b.eq('the free end lands on the main centreline, to the micron',
         geom.length(final, plan.crossing), 0.0, 1e-9)
    b.eq('and the run is still on the target fall afterwards',
         geom.gradient(lifted_anchor, final), plan.target_gradient, 1e-9)
    # The far end creeps towards the junction as the run tilts, by the
    # cosine of the tilt over the run's length. At 1 in 80 over 30 feet that
    # is under two tenths of a millimetre, and it is why the uprights are
    # re-cut to the run's new joint rather than assumed to still reach it.
    creep_mm = geom.plan_length(anchor, lifted_anchor) * geom.MM_PER_FT
    b.ok('the far end creeps in plan, but by well under a millimetre',
         creep_mm < 1.0)
    b.ok('and it creeps towards the junction, not away from it',
         geom.plan_length(lifted_anchor, final) <
         geom.plan_length(anchor, free) + 1e-9 + geom.plan_length(free, final))
    b.ok('the run falls towards the junction', final.z < lifted_anchor.z)

    # the same junction with the branch already past the main, so it trims
    anchor = geom.Pt(40, -30, 2.0)
    free = geom.Pt(40, 25, 2.0)
    plan = geom.build_plan(main0, main1, anchor, free, end_tolerance_ft=tol)
    b.eq('a branch that overshoots the main is trimmed back',
         plan.branch_case, geom.TRIM)
    tilted_anchor = geom.apply_tilt(free, anchor, plan.tilt, plan.axis)
    direction = geom.unit3(tilted_anchor, free)
    landing = geom.stretch_to_plan_point(tilted_anchor, direction,
                                         plan.crossing.x, plan.crossing.y)
    rise = plan.crossing.z - landing.z
    final = geom.Pt(landing.x, landing.y, landing.z + rise)
    b.eq('and it still lands exactly on the crossing',
         geom.length(final, plan.crossing), 0.0, 1e-9)
    b.ok('and it is shorter than it was',
         geom.plan_length(anchor, final) < geom.plan_length(anchor, free))

    # an apparent intersection past the free end of the main
    anchor = geom.Pt(130, -30, 2.0)
    free = geom.Pt(130, -12, 2.0)
    plan = geom.build_plan(main0, main1, anchor, free, end_tolerance_ft=tol,
                           main_end_free=True)
    b.ok('the main is extended', plan.extends_main)
    tilted_anchor = geom.apply_tilt(free, anchor, plan.tilt, plan.axis)
    direction = geom.unit3(tilted_anchor, free)
    landing = geom.stretch_to_plan_point(tilted_anchor, direction,
                                         plan.crossing.x, plan.crossing.y)
    rise = plan.crossing.z - landing.z
    final = geom.Pt(landing.x, landing.y, landing.z + rise)
    b.eq('and the branch is raised to the apparent height at that fall',
         final.z, -1.625, 1e-9)
    b.eq('which is the main fall carried 30 feet past its end',
         final.z - main1.z, -30.0 * 0.0125, 1e-9)


def group_slope_config(b):
    """The slope settings, resolved once."""
    settings = dict(mo_core.DEFAULTS)
    config = mos_run.SlopeConfig(settings)
    b.ok('the slope tick is on by default', config.match_slope)
    b.eq('and the fall comes from the main', config.source, u"main")
    b.eq('falling towards the junction', config.direction, u"towards")
    b.ok('trimming is on by default', config.trim)
    b.eq('and the junction is worked out to suit', config.fitting, u"auto")
    b.ok('apparent intersections are allowed', config.apparent)
    b.ok('and the main may be extended to reach one', config.extend_main)
    b.eq('46 degrees is the upright line', config.steep, 46.0)
    b.eq('the walk stops at 400 elements', config.limit, 400)
    b.eq('the fixed fall is 1 in 80', config.fixed_n, 80.0)

    settings[u"slope_match_slope"] = u"off"
    config = mos_run.SlopeConfig(settings)
    b.eq('clearing the tick keeps the branch fall', config.source,
         geom.KEEP_SLOPE)

    settings[u"slope_match_slope"] = u"on"
    settings[u"slope_source"] = u"fixed"
    settings[u"slope_fixed_n"] = u"40"
    config = mos_run.SlopeConfig(settings)
    b.eq('a fixed fall is read', config.source, u"fixed")
    b.eq('and its number with it', config.fixed_n, 40.0)

    settings[u"slope_trim"] = u"off"
    config = mos_run.SlopeConfig(settings)
    b.ok('trimming can be turned off', not config.trim)

    settings[u"slope_end_tol_mm"] = u"nonsense"
    config = mos_run.SlopeConfig(settings)
    b.ok('a tolerance that will not parse falls back rather than being zero',
         config.end_tol > 0)

    fresh = dict(mo_core.DEFAULTS)
    config = mos_run.SlopeConfig(fresh)
    b.ok('pairs is the default, so a run of separate joints is click click',
         config.pairs)
    fresh[u"slope_repeat"] = u"main"
    b.ok('and one main with many branches is still there',
         not mos_run.SlopeConfig(fresh).pairs)
    fresh[u"slope_repeat"] = u"nonsense"
    b.ok('anything else is not pairs, rather than crashing',
         not mos_run.SlopeConfig(fresh).pairs)


def group_silence(b):
    """The tick that holds everything back."""
    settings = dict(mo_core.DEFAULTS)
    b.ok('nothing is suppressed by default', not mo_core.is_silent(settings))
    settings[u"silent"] = u"on"
    b.ok('the tick suppresses', mo_core.is_silent(settings))
    settings[u"silent"] = u"off"
    b.ok('and clears again', not mo_core.is_silent(settings))
    b.ok('a settings file with no such key at all is not silent',
         not mo_core.is_silent({}))

    # the tick is about what reaches the screen, not about what the run did
    report = mo_core.Report()
    report.problem(u"something to look at")
    b.ok('a problem is still a problem when messages are suppressed',
         report.should_show(u"problems"))
    b.ok('which is the point - the run still knows, it just does not say, '
         'and the debug report still goes to disk',
         len(report.problems) == 1)

    # it round trips through the file like everything else
    folder = tempfile.mkdtemp(prefix='mo_silent_')
    original = mo_core.appdata_dir
    mo_core.appdata_dir = lambda: folder
    try:
        values = dict(mo_core.DEFAULTS)
        values[u"silent"] = u"on"
        mo_core.save_settings(values)
        b.ok('it survives a save and a load',
             mo_core.is_silent(mo_core.load_settings()))
    finally:
        mo_core.appdata_dir = original
        shutil.rmtree(folder, ignore_errors=True)


def group_prompts(b):
    """The status line, which is the only thing the tool says while it runs."""
    settings = dict(mo_core.DEFAULTS)
    pairs = mos_run.SlopeConfig(settings)
    settings[u"slope_repeat"] = u"main"
    one_main = mos_run.SlopeConfig(settings)

    class FakeMain(object):
        def describe(self):
            return u"1 in 60"

    start = mos_run.prompt_for(None, pairs, 0)
    b.ok('the first prompt asks for the main', u"pick the MAIN" in start)
    b.ok('and says how to stop', u"Esc" in start)
    b.ok('and carries no count before anything has been done',
         u"joined" not in start)

    second = mos_run.prompt_for(FakeMain(), pairs, 0)
    b.ok('the second prompt asks for the pipe to bring in',
         u"bring into it" in second)
    b.ok('and carries the main fall', u"1 in 60" in second)

    later = mos_run.prompt_for(None, pairs, 3)
    b.ok('after three joints it says so', u"3 joined" in later)
    b.ok('and is back to asking for a main', u"pick the MAIN" in later)

    many = mos_run.prompt_for(FakeMain(), one_main, 2)
    b.ok('with one main it keeps asking for branches',
         u"pick branches" in many)
    b.ok('and carries the count too', u"2 joined" in many)


def group_debug(b):
    """The debug report: the thing that makes a bad run reportable."""
    b.eq('feet read out as millimetres', mo_debug.mm(1.0), u"304.8")
    b.eq('and to the places asked for', mo_debug.mm(1.0, 0), u"305")
    b.eq('a point reads as three millimetre numbers',
         mo_debug.pt(geom.Pt(1, 0, -1)), u"(304.8, 0.0, -304.8) mm")
    b.eq('no point says so', mo_debug.pt(None), u"none")
    b.ok('a falling gradient says falling',
         u"falling" in mo_debug.fall(-0.0125))
    b.ok('and says one in eighty', u"1 in 80" in mo_debug.fall(-0.0125))
    b.ok('a rising gradient says rising', u"rising" in mo_debug.fall(0.0125))
    b.eq('level says level', mo_debug.fall(0.0), u"level")
    b.eq('no gradient says none', mo_debug.fall(None), u"none")

    recorder = mo_debug.Recorder(u"Match Offset Slope")
    recorder.section(u"the main")
    recorder.pair(u"gradient", mo_debug.fall(-0.0125))
    recorder.failure(u"Error", u"Pipes overlap")
    recorder.blew_up(u"the fitting", u"line one\nline two")
    text = recorder.text()
    b.ok('the section heading is in the report', u"the main" in text)
    b.ok('the pair is in the report', u"gradient" in text)
    b.ok('Revit\'s own words are in the report', u"Pipes overlap" in text)
    b.ok('and are marked as Revit\'s', u"REVIT SAID" in text)
    b.ok('an exception is in the report', u"the fitting" in text)
    b.ok('with every line of it', u"line two" in text)
    b.eq('failures are counted', len(recorder.failures), 1)
    b.eq('exceptions are counted', len(recorder.exceptions), 1)

    settings = dict(mo_core.DEFAULTS)
    settings[u"round_step_mm"] = u"25"
    recorder = mo_debug.Recorder()
    recorder.header(None, None, settings)
    text = recorder.text()
    b.ok('the settings are in the report', u"round_step_mm" in text)
    b.ok('and a changed one is marked', u"<- changed" in text)
    b.ok('the version is in the report', mo_core.__version__ in text)
    b.ok('a category list is summarised rather than dumped',
         u"{0} categories".format(len(mo_core.DEFAULT_CATEGORY_KEYS)) in text)
    b.ok('and not dumped in full', u"cable_tray_fittings" not in text)

    report = mo_core.Report()
    report.debug = recorder
    report.problem(u"something went wrong")
    report.matched_one()
    report.say(u"a line only the report sees")
    report.note_pair(u"a number", 42)
    recorder.tail(report)
    text = recorder.text()
    b.ok('the problem is repeated at the end', u"something went wrong" in text)
    b.ok('a say line is in the report', u"only the report sees" in text)
    b.ok('a note pair is in the report', u"a number" in text)
    b.eq('the recorder carries the matched count', recorder.matched, 1)
    b.eq('and the problem count', recorder.problems, 1)

    quiet = mo_core.Report()
    quiet.say(u"nothing should happen")
    quiet.note_pair(u"nor here", 1)
    b.eq('with no recorder a say line goes nowhere', len(quiet.notes), 0)
    b.eq('and does not become a problem', len(quiet.problems), 0)


def group_failures(b):
    """What Revit objected to, kept rather than thrown away."""
    pre = mo_run.PREPROCESSOR
    pre.drain()

    warning = FakeFailure(FailureSeverity.Warning, u"Pipes overlap")
    error = FakeFailure(FailureSeverity.Error, u"Cannot make a tee",
                        resolvable=True)
    stuck = FakeFailure(FailureSeverity.Error, u"No resolution here")

    accessor = FakeAccessor([warning])
    pre.PreprocessFailures(accessor)
    b.eq('a warning is deleted', accessor.deleted, [u"Pipes overlap"])
    found = pre.drain()
    b.eq('and it is still written down', len(found), 1)
    b.eq('with what Revit said', found[0][1], u"Pipes overlap")
    b.eq('and draining empties the list', len(pre.drain()), 0)

    accessor = FakeAccessor([error])
    pre.PreprocessFailures(accessor)
    b.eq('an error with a resolution is resolved', accessor.resolved,
         [u"Cannot make a tee"])
    b.eq('and not deleted as a warning', accessor.deleted, [])
    b.eq('and it is written down too', len(pre.drain()), 1)

    accessor = FakeAccessor([stuck])
    pre.PreprocessFailures(accessor)
    b.eq('an error with no resolution is left alone', accessor.resolved, [])
    found = pre.drain()
    b.eq('but still written down', len(found), 1)
    b.ok('which is the whole point - the commit will roll back and this is '
         'the only record of why', u"No resolution" in found[0][1])

    accessor = FakeAccessor([warning, error, stuck])
    pre.PreprocessFailures(accessor)
    b.eq('a mixed batch is all recorded', len(pre.drain()), 3)

    text = mo_run.failure_text([(u"Error", u"Cannot make a tee"),
                                (u"Warning", u"Pipes overlap")])
    b.ok('the sentence carries both', u"Cannot make a tee" in text and
         u"Pipes overlap" in text)
    b.eq('nothing to say is an empty sentence', mo_run.failure_text([]), u"")
    b.eq('the same thing twice is said once',
         mo_run.failure_text([(u"Error", u"Same"), (u"Error", u"Same")]),
         u"Same")
    many = [(u"Error", u"one"), (u"Error", u"two"), (u"Error", u"three"),
            (u"Error", u"four")]
    b.eq('and a flood is capped at three',
         mo_run.failure_text(many), u"one; two; three")

    b.ok('Committed reads as committed', mos_run.committed('Committed'))
    b.ok('RolledBack does not', not mos_run.committed('RolledBack'))
    b.ok('Uninitialized does not', not mos_run.committed('Uninitialized'))


def group_junction_advice(b):
    """The sentence that has to explain a refused junction."""
    b.eq('square on is square on', mos_run.off_the_line(90.0), 90.0, 1e-9)
    b.eq('135 degrees is 45 off the line',
         mos_run.off_the_line(135.0), 45.0, 1e-9)
    b.eq('45 degrees is also 45 off the line',
         mos_run.off_the_line(45.0), 45.0, 1e-9)
    b.eq('in line is nothing off the line',
         mos_run.off_the_line(180.0), 0.0, 1e-9)

    square = mos_run.angle_advice(90.0)
    b.ok('a square junction says a plain tee should have worked',
         u"plain tee" in square)
    oblique = mos_run.angle_advice(135.0)
    b.ok('an oblique junction says what family it needs',
         u"oblique" in oblique or u"swept" in oblique)
    b.ok('and says how far off the line it is', u"45.0 degrees off" in oblique)
    b.ok('and says most pipe types have only the 90',
         u"90 degree" in oblique)

    b.ok('with no families at all it says where to load one',
         u"Pipe Settings" in mos_run.offer_advice([]))
    b.ok('with families it lists them',
         u"BGL_Tee" in mos_run.offer_advice([u"Junction: BGL_Tee"]))


def group_restretch(b):
    """Moving one end of a pipe must not reverse its curve.

    The bug this exists for looked almost right on screen: the pipe was the
    correct length in the correct place, and the joint at its far end had
    quietly come apart because Revit's connectors are bound to the curve's
    ends by index and the curve had been written back to front.
    """
    ft = mo_core.mm_to_ft

    # index 0 is the end that stays
    element = pipe(ft(2500), ft(100), eid=501)
    ends = slope_model.ends_of(element)
    b.eq('the fake pipe starts where it should', ends[0].x, 0.0, 1e-9)
    done, order = slope_model.restretch(element, ends[0],
                                        geom.Pt(25.0, 0.0, ends[0].z))
    b.ok('the stretch takes', done)
    b.eq('and says which end stayed', order, u"0 stays")
    after = slope_model.ends_of(element)
    b.eq('index 0 is still the end that stayed', after[0].x, 0.0, 1e-9)
    b.eq('and index 1 is the end that moved', after[1].x, 25.0, 1e-9)

    # index 1 is the end that stays - the case that shipped broken
    element = pipe(ft(2500), ft(100), eid=502)
    ends = slope_model.ends_of(element)
    done, order = slope_model.restretch(element, ends[1],
                                        geom.Pt(-15.0, 0.0, ends[1].z))
    b.ok('the stretch takes the other way round too', done)
    b.eq('and says the other end stayed', order, u"1 stays")
    after = slope_model.ends_of(element)
    b.eq('index 1 is STILL the end that stayed', after[1].x, 10.0, 1e-9)
    b.eq('and index 0 is the end that moved', after[0].x, -15.0, 1e-9)
    b.ok('so the curve points the way it always did',
         (after[1].x - after[0].x) > 0)

    # the direction is what matters, not the numbers
    element = pipe(ft(2500), ft(100), eid=503)
    before = slope_model.ends_of(element)
    was = geom.unit3(before[0], before[1])
    slope_model.restretch(element, before[1], geom.Pt(-40.0, 0.0, before[1].z))
    now = geom.unit3(*slope_model.ends_of(element))
    b.ok('the curve direction is unchanged',
         was[0] * now[0] + was[1] * now[1] + was[2] * now[2] > 0.999)

    # a stretch that would leave nothing is refused rather than written
    element = pipe(ft(2500), ft(100), eid=504)
    ends = slope_model.ends_of(element)
    done, why = slope_model.restretch(element, ends[0], ends[0])
    b.ok('a zero length pipe is refused', not done)
    b.ok('and it says why', u"no length" in why)
    b.eq('and the pipe is untouched',
         slope_model.ends_of(element)[1].x, 10.0, 1e-9)

    # an element with no curve at all
    done, why = slope_model.restretch(fixture(ft(2000), ft(2400), eid=505),
                                      geom.Pt(0, 0, 0), geom.Pt(1, 0, 0))
    b.ok('an element with no curve is refused', not done)
    b.ok('and it says so', u"no curve" in why)


def group_vectors(b):
    """The 3D turns that put a junction family onto three pipes."""
    b.eq('two directions square on', geom.angle_between((1, 0, 0),
                                                        (0, 1, 0)), 90.0, 1e-9)
    b.eq('the same direction is no angle',
         geom.angle_between((1, 0, 0), (2, 0, 0)), 0.0, 1e-9)
    b.eq('opposite is half a turn',
         geom.angle_between((1, 0, 0), (-1, 0, 0)), 180.0, 1e-9)
    b.ok('a zero vector does not raise',
         geom.angle_between((0, 0, 0), (1, 0, 0)) == 0.0)

    axis, angle = geom.rotation_to((1, 0, 0), (0, 1, 0))
    turned = geom.rotate_vector((1, 0, 0), axis, angle)
    b.eq('a quarter turn lands on the target', geom.angle_between(
        turned, (0, 1, 0)), 0.0, 1e-6)
    axis, angle = geom.rotation_to((1, 0, 0), (-1, 0, 0))
    turned = geom.rotate_vector((1, 0, 0), axis, angle)
    b.eq('a half turn lands on the target too - the cross product is zero '
         'there and an axis has to be made', geom.angle_between(
             turned, (-1, 0, 0)), 0.0, 1e-6)
    axis, angle = geom.rotation_to((1, 0, 0), (1, 0, 0))
    b.eq('no turn is needed when it is already there', angle, 0.0, 1e-12)

    spin = geom.spin_angle((0, 1, 0), (0, 0, 1), (1, 0, 0))
    b.eq('a spin about x takes y onto z', abs(spin), math.pi / 2.0, 1e-9)
    b.eq('the component along the axis is ignored',
         abs(geom.spin_angle((5, 1, 0), (5, 0, 1), (1, 0, 0))),
         math.pi / 2.0, 1e-9)

    # a square tee onto a square junction
    result = geom.orientation_for((1, 0, 0), (0, 1, 0), (0, 1, 0), (1, 0, 0))
    b.eq('a square tee turns onto a square junction exactly', result[4], 0.0,
         1e-6)
    # a 45 degree lateral onto a 45 degree junction
    half = math.sqrt(0.5)
    result = geom.orientation_for((1, 0, 0), (half, half, 0),
                                  (half, half, 0), (0, 1, 0))
    b.eq('a 45 degree lateral turns onto a 45 degree junction', result[4],
         0.0, 1e-6)
    # a square tee cannot be turned onto a 45 degree junction
    result = geom.orientation_for((1, 0, 0), (0, 1, 0),
                                  (half, half, 0), (0, 1, 0))
    b.ok('a square tee is left 45 degrees out on a 45 degree junction, '
         'which is what stops it being forced in',
         abs(result[4] - 45.0) < 1e-6)
    # and one that is out of plane
    result = geom.orientation_for((1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 0, 0))
    b.eq('a square tee turns onto a vertical run', result[4], 0.0, 1e-6)

    # where two axes cross
    meeting = geom.closest_point_between(geom.Pt(5, 0, 0), (-1, 0, 0),
                                         geom.Pt(0, 5, 0), (0, -1, 0))
    b.eq('two lines that cross meet where they cross',
         (round(meeting.x, 9), round(meeting.y, 9), round(meeting.z, 9)),
         (0.0, 0.0, 0.0))
    meeting = geom.closest_point_between(geom.Pt(0, 0, 0), (1, 0, 0),
                                         geom.Pt(0, 4, 2), (0, 0, -1))
    b.eq('two that pass meet in the middle of the gap', meeting.y, 2.0, 1e-9)
    parallel = geom.closest_point_between(geom.Pt(0, 0, 0), (1, 0, 0),
                                          geom.Pt(0, 3, 0), (1, 0, 0))
    b.eq('two parallel lines fall back to the first point', parallel.x, 0.0)


def group_squaring(b):
    """Where a square tee and a bend go, for a branch that arrives at an
    angle Revit will not tee into directly."""
    half = math.sqrt(0.5)
    crossing = geom.Pt(0, 0, 0)
    main = (1.0, 0.0, 0.0)
    branch = (half, half, 0.0)          # arriving at 45 degrees

    tee, bend = geom.square_junction(crossing, main, branch, 1.0)
    b.ok('a square junction can be worked out', tee is not None)
    b.eq('the stub is exactly the length asked for',
         geom.length(bend, tee), 1.0, 1e-9)
    b.eq('and it is square to the main, in three dimensions not just plan',
         geom.v_dot(geom.v_unit(geom.v_sub(bend, tee)), main), 0.0, 1e-12)
    b.eq('the bend sits on the branch centreline, so the run it was just '
         'put on does not have to move again',
         geom.angle_between(geom.v_sub(bend, crossing), branch), 0.0, 1e-9)
    # v_sub(a, b) is b minus a, so this is (crossing - bend) . branch:
    # positive means the crossing is still ahead of the bend along the
    # branch's own direction of travel, which is the bend sitting back up
    # the branch rather than out past the main.
    b.ok('the bend is back along the branch, not past the main',
         geom.v_dot(geom.v_sub(bend, crossing), branch) > 0)

    # the deflection at the bend is the angle the branch was off by
    stub_dir = geom.v_unit(geom.v_sub(bend, tee))
    b.eq('the bend turns the branch by the angle it was off the square',
         geom.angle_between(branch, stub_dir), 45.0, 1e-9)

    # a sloping main and a sloping branch
    main = geom.v_unit((1.0, 0.0, -0.0167))
    branch = geom.v_unit((half, half, -0.0125))
    tee, bend = geom.square_junction(crossing, main, branch, 0.75)
    b.eq('a sloping main still gets a square stub',
         geom.v_dot(geom.v_unit(geom.v_sub(bend, tee)), main), 0.0, 1e-12)
    b.eq('of the right length', geom.length(bend, tee), 0.75, 1e-9)
    b.eq('and the bend is still on the branch line',
         geom.angle_between(geom.v_sub(bend, crossing), branch), 0.0, 1e-9)

    # a longer stub slides the tee further along the main
    near_tee, _near_bend = geom.square_junction(crossing, main, branch, 0.5)
    far_tee, _far_bend = geom.square_junction(crossing, main, branch, 2.0)
    b.ok('a longer stub slides the tee further along the main',
         geom.length(crossing, far_tee) > geom.length(crossing, near_tee))
    b.ok('and it slides away from the side the branch comes from',
         geom.v_dot(geom.v_sub(crossing, far_tee), branch) < 0)

    # a branch already square needs no sliding at all
    tee, bend = geom.square_junction(crossing, (1.0, 0.0, 0.0),
                                     (0.0, 1.0, 0.0), 1.0)
    b.eq('a square branch leaves the tee exactly where the crossing is',
         geom.length(crossing, tee), 0.0, 1e-12)
    b.eq('and the stub runs straight back down the branch',
         geom.length(crossing, bend), 1.0, 1e-9)

    # a branch in line with the main cannot be squared at all
    tee, bend = geom.square_junction(crossing, (1.0, 0.0, 0.0),
                                     (1.0, 0.0, 0.0), 1.0)
    b.ok('a branch in line with the main is refused', tee is None)


def group_assignment(b):
    """Which way round a junction family goes on the main.

    The bug this exists for produced two different answers on identical
    geometry, one run apart: a 45 degree swept junction was placed
    perfectly one minute and refused as "its branch sits at 135 degrees and
    the junction needs 45" the next.
    """
    half = math.sqrt(0.5)
    # a branch arriving at 45 degrees to a main running along x
    want_a = (-1.0, 0.0, 0.0)
    want_b = (1.0, 0.0, 0.0)
    want_c = (-half, -half, 0.0)
    options = [(want_a,), (want_b,)]
    wanted = slope_model.required_angles(options, want_c)
    b.eq('one way round the junction needs 45 degrees',
         round(min(wanted), 6), 45.0)
    b.eq('and the other way it needs 135', round(max(wanted), 6), 135.0)

    pick = slope_model.choose_assignment
    b.eq('a 135 degree swept junction fits the 135 way round',
         pick(135.0, [45.0, 135.0], 1.5), 1)
    b.eq('and a 45 degree one fits the 45 way round',
         pick(45.0, [45.0, 135.0], 1.5), 0)
    b.eq('a square tee fits neither', pick(90.0, [45.0, 135.0], 1.5), -1)
    b.eq('a square tee does fit a square junction',
         pick(90.0, [90.0, 90.0], 1.5), 0)
    b.eq('a degree out is still a fit', pick(134.2, [45.0, 135.0], 1.5), 1)
    b.eq('five degrees out is not', pick(130.0, [45.0, 135.0], 1.5), -1)

    # the order the two are offered in must not decide the answer
    b.eq('the 135 family fits whichever order the halves come in',
         pick(135.0, [135.0, 45.0], 1.5), 0)
    b.ok('which is the whole point - BreakCurve does not say which half it '
         'hands back, so the order is not something to rely on',
         pick(135.0, [45.0, 135.0], 1.5) >= 0 and
         pick(135.0, [135.0, 45.0], 1.5) >= 0)

    # a branch square to the main
    want_c = (0.0, -1.0, 0.0)
    wanted = slope_model.required_angles(options, want_c)
    b.eq('a square branch needs 90 degrees either way round',
         [round(x, 6) for x in wanted], [90.0, 90.0])
    b.eq('so a square tee fits it', pick(90.0, wanted, 1.5), 0)
    b.eq('and a 45 degree swept junction does not',
         pick(135.0, wanted, 1.5), -1)


def group_flow(b):
    """Which way round a swept junction goes, which its connector
    directions do not say."""
    b.eq('the higher end of a main is upstream',
         geom.upstream_of(geom.Pt(0, 0, 1.6), geom.Pt(10, 0, 1.5)),
         geom.UPSTREAM_FIRST)
    b.eq('and the other way round', geom.upstream_of(
        geom.Pt(0, 0, 1.5), geom.Pt(10, 0, 1.6)), geom.UPSTREAM_SECOND)
    b.eq('a level main has no answer', geom.upstream_of(
        geom.Pt(0, 0, 1.5), geom.Pt(10, 0, 1.5)), geom.UPSTREAM_UNKNOWN)
    b.eq('a hair of fall still reads', geom.upstream_of(
        geom.Pt(0, 0, 1.5001), geom.Pt(10, 0, 1.5)), geom.UPSTREAM_FIRST)

    sweeps = geom.sweeps_with_the_flow
    b.ok('the arm leans back towards where the water comes from, so the '
         'acute run connector belongs on the upstream half',
         sweeps(45.0, True))
    b.ok('and the obtuse one belongs downstream', sweeps(135.0, False))
    b.ok('the acute one downstream is the junction facing back up the flow',
         not sweeps(45.0, False))
    b.ok('and the obtuse one upstream is the same mistake the other way',
         not sweeps(135.0, True))
    b.ok('a square junction reads as upstream either way, which is right - '
         'a square tee has no flow direction to get wrong',
         sweeps(90.0, True) and not sweeps(90.0, False))

    # the two ways round always disagree, which is why one has to be chosen
    for angle in (30.0, 45.0, 60.0, 120.0, 135.0, 150.0):
        b.ok('at {0} degrees exactly one way round faces the flow'.format(
            angle), sweeps(angle, True) != sweeps(angle, False))

    with_flow = geom.branch_arrives_with_the_flow
    half = math.sqrt(0.5)
    b.ok('a branch heading downstream arrives with the flow',
         with_flow((1.0, 0.0, 0.0), (half, half, 0.0)))
    b.ok('a branch heading upstream arrives against it',
         not with_flow((1.0, 0.0, 0.0), (-half, half, 0.0)))
    b.ok('a branch square to the main does neither',
         not with_flow((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)))


def group_in_line(b):
    """Two runs on the same line, made into one run."""
    main0, main1 = geom.Pt(0, 0, 1.0), geom.Pt(10, 0, 0.8)   # falling
    tol = 1.0 / geom.MM_PER_FT

    # a level run beyond the main's far end, running back towards it
    plan = geom.build_plan(main0, main1, geom.Pt(20, 0, 0.3),
                           geom.Pt(12, 0, 0.3), end_tolerance_ft=tol,
                           main_end_free=True)
    b.ok('two runs on the same line are a plan, not a refusal', plan.ok)
    b.eq('and the case says so', plan.main_case, geom.IN_LINE)
    b.eq('the junction is a union', plan.junction, geom.UNION)
    b.eq('the meeting point is the main own end', plan.crossing.x, 10.0, 1e-9)
    b.eq('at the main own elevation there', plan.crossing.z, 0.8, 1e-9)
    b.eq('the branch stretches out to it', plan.branch_case, geom.EXTEND)
    b.eq('it is dead on the line', plan.lateral, 0.0, 1e-12)
    b.eq('the fall carries the main on, which is the other sign because the '
         'branch runs the other way along it',
         plan.target_gradient, -plan.main_gradient, 1e-12)
    b.ok('so it does need tilting', abs(plan.tilt) > 1e-6)

    # the same, but the branch already runs the same way as the main
    plan = geom.build_plan(main0, main1, geom.Pt(12, 0, 0.3),
                           geom.Pt(20, 0, 0.3), end_tolerance_ft=tol,
                           main_end_free=True)
    b.ok('a branch pointing away from the main is still refused as behind',
         not plan.ok)
    b.eq('and says so', plan.refusal, geom.BEHIND)

    # a run beyond the main's near end instead
    plan = geom.build_plan(main0, main1, geom.Pt(-20, 0, 0.3),
                           geom.Pt(-12, 0, 0.3), end_tolerance_ft=tol,
                           main_end_free=True)
    b.ok('the other end works the same way', plan.ok)
    b.eq('and it meets the near end', plan.crossing.x, 0.0, 1e-9)
    b.eq('the fall carries on the same way this time',
         plan.target_gradient, plan.main_gradient, 1e-12)

    # a run that overshoots and has to be trimmed back
    plan = geom.build_plan(main0, main1, geom.Pt(20, 0, 0.3),
                           geom.Pt(6, 0, 0.3), end_tolerance_ft=tol,
                           main_end_free=True)
    b.eq('a run that overshoots the main is trimmed back',
         plan.branch_case, geom.TRIM)
    b.eq('to the main own end all the same', plan.crossing.x, 10.0, 1e-9)

    # side by side rather than in line
    plan = geom.build_plan(main0, main1, geom.Pt(20, 2, 0.3),
                           geom.Pt(12, 2, 0.3), end_tolerance_ft=tol,
                           main_end_free=True,
                           lateral_tolerance_ft=50.0 / geom.MM_PER_FT)
    b.ok('two feet off the line is not the same line', not plan.ok)
    b.eq('and it says which kind of parallel it is', plan.refusal,
         u"side by side")
    b.ok('and the refusal reads as a sentence',
         u"too far apart" in geom.refusal_text(plan.refusal))

    # a few millimetres off is still the same line
    off = geom.Pt(20, 0.02, 0.3)
    plan = geom.build_plan(main0, main1, off, geom.Pt(12, 0.02, 0.3),
                           end_tolerance_ft=tol, main_end_free=True,
                           lateral_tolerance_ft=50.0 / geom.MM_PER_FT)
    b.ok('a few millimetres off the line still counts as in line', plan.ok)
    b.ok('and the offset is reported so it can be nudged across',
         plan.lateral > 0)

    # the main end has to be free
    plan = geom.build_plan(main0, main1, geom.Pt(20, 0, 0.3),
                           geom.Pt(12, 0, 0.3), end_tolerance_ft=tol,
                           main_end_free=False)
    b.ok('a main end with something joined to it is refused', not plan.ok)
    b.eq('and says so', plan.refusal, u"main end connected")

    # the tick clears it
    plan = geom.build_plan(main0, main1, geom.Pt(20, 0, 0.3),
                           geom.Pt(12, 0, 0.3), end_tolerance_ft=tol,
                           main_end_free=True, allow_in_line=False)
    b.ok('with the tick cleared it is parallel again', not plan.ok)
    b.eq('and refused as parallel', plan.refusal, geom.PARALLEL)

    # genuinely parallel runs are still refused with the tick on
    plan = geom.build_plan(main0, main1, geom.Pt(0, 5, 0.3),
                           geom.Pt(10, 5, 0.3), end_tolerance_ft=tol,
                           main_end_free=True)
    b.ok('a run alongside the main is still refused', not plan.ok)

    # the fall rule on its own
    rule = geom.in_line_gradient
    b.eq('carrying a falling main on the same way keeps the sign',
         rule(-0.0125, True), -0.0125, 1e-12)
    b.eq('and the other way takes the opposite sign for the same fall',
         rule(-0.0125, False), 0.0125, 1e-12)
    b.eq('keeping the slope hands the run its own back',
         rule(-0.0125, True, geom.KEEP_SLOPE, 0.031), 0.031, 1e-12)
    b.eq('a fixed fall follows the main down',
         rule(-0.0125, True, geom.FIXED, 0.0, 40.0), -0.025, 1e-12)
    b.eq('and reverses with the run', rule(-0.0125, False, geom.FIXED,
                                           0.0, 40.0), 0.025, 1e-12)

    b.eq('how far off a line a point sits, in plan',
         geom.lateral_offset(geom.Pt(0, 0, 0), geom.Pt(10, 0, 0),
                             geom.Pt(5, 3, 9)), 3.0, 1e-12)
    b.eq('a point on the line is not off it',
         geom.lateral_offset(geom.Pt(0, 0, 0), geom.Pt(10, 0, 0),
                             geom.Pt(5, 0, 9)), 0.0, 1e-12)
    b.eq('where a point falls along a line',
         geom.parameter_along(geom.Pt(0, 0, 0), geom.Pt(10, 0, 0),
                              geom.Pt(2.5, 4, 0)), 0.25, 1e-12)
    b.eq('the nearer end of a line', geom.nearer_end(
        geom.Pt(0, 0, 0), geom.Pt(10, 0, 0), geom.Pt(9, 1, 0)).x, 10.0)


def group_routing_names(b):
    """The rule group names, which were asked for in the singular."""
    kind, spelling = slope_model.rule_group((u"Junctions", u"Junction"))
    b.ok('the plural spelling resolves', kind is not None)
    b.eq('and it is the one the enum actually uses', spelling, u"Junctions")
    kind, spelling = slope_model.rule_group((u"Nonsense",))
    b.ok('a name the enum does not have resolves to nothing', kind is None)
    b.eq('and says so rather than throwing', spelling, u"")
    b.ok('the available names can be listed for the report',
         u"Junctions" in slope_model.group_names_available())

    for label, spellings in slope_model.ROUTING_GROUPS:
        kind, _spelling = slope_model.rule_group(spellings)
        b.ok('{0} resolves to a rule group'.format(label), kind is not None)


def fake_level(eid, name, elevation_ft):
    level = types.SimpleNamespace(Id=ElementId(eid), Name=name,
                                  ProjectElevation=elevation_ft)
    ELEMENTS[eid] = level
    return level


def hosted_terminal(insertion_ft, bottom_ft, top_ft, eid, param, value_ft,
                    direction=1.0, stuck=False, level=None):
    """A terminal that carries one of the family offset parameters, wired
    so that writing it moves the family the way Revit would."""
    element = terminal(insertion_ft, bottom_ft, top_ft, eid=eid)
    offset = FakeParam(value_ft, direction=direction)
    offset.element = element
    element.params[param] = offset
    element.solids = [FakeSolid(bottom_ft, top_ft,
                                faces=[FakeFace(-1.0, 1.0, bottom_ft)])]
    element.stuck = stuck
    if level is not None:
        element.LevelId = level.Id
    return element


def group_across_levels(b):
    """A family matched to something on another level."""
    ft = mo_core.mm_to_ft
    turn = mo_core.host_offset_direction

    b.eq('an offset that went the way it was asked runs up', turn(1.0, 1.0), 1)
    b.eq('one that went exactly the other way runs down', turn(1.0, -1.0), -1)
    b.eq('one that moved nothing is not a route', turn(1.0, 0.0), 0)
    b.eq('one that moved something else entirely is not either',
         turn(1.0, 0.4), 0)
    b.eq('asking for nothing proves nothing', turn(0.0, 0.0), 0)
    b.eq('nonsense is not a direction', turn(u"x", 1.0), 0)

    # level based: written through its elevation from level
    del MOVED[:]
    unit = hosted_terminal(ft(1000), ft(800), ft(1200), 901,
                           'INSTANCE_ELEVATION_PARAM', ft(800))
    route = mo_model.shift(None, unit, ft(250))
    b.eq('a family on a level is written through its elevation from level',
         route, u"elevation from level")
    b.eq('which took the delta', unit.params['INSTANCE_ELEVATION_PARAM'].value,
         ft(1050), 1e-9)
    b.eq('and nothing was moved by hand', len(MOVED), 0)

    # under a ceiling: Revit will not move it, and its offset runs down
    grille = hosted_terminal(ft(2700), ft(2650), ft(2700), 902,
                             'INSTANCE_FREE_HOST_OFFSET_PARAM', 0.0,
                             direction=-1.0, stuck=True)
    route = mo_model.shift(None, grille, ft(-100))
    b.ok('a ceiling grille goes through its offset from host',
         route.startswith(u"offset from host"))
    b.ok('and the route says it runs down', u"down" in route)
    b.eq('the grille went down by what was asked',
         mo_core.ft_to_mm(mo_model.vertical_marker(grille)), 2600.0, 1e-6)
    b.eq('because the offset went up by it',
         grille.params['INSTANCE_FREE_HOST_OFFSET_PARAM'].value, ft(100),
         1e-9)

    # on a floor: the offset runs up and is left as written
    box = hosted_terminal(ft(300), ft(300), ft(400), 903,
                          'INSTANCE_FREE_HOST_OFFSET_PARAM', ft(300),
                          stuck=True)
    route = mo_model.shift(None, box, ft(50))
    b.eq('a floor box offset runs up', route, u"offset from host")
    b.eq('and it went up', mo_core.ft_to_mm(mo_model.vertical_marker(box)),
         350.0, 1e-6)

    # an offset that moves nothing is put back and the move is tried
    dud = hosted_terminal(ft(500), ft(500), ft(600), 904,
                          'INSTANCE_FREE_HOST_OFFSET_PARAM', ft(10),
                          direction=0.0)
    del MOVED[:]
    route = mo_model.shift(None, dud, ft(75))
    b.eq('a dead offset falls through to a move', route, u"moved")
    b.eq('and is put back as it was',
         dud.params['INSTANCE_FREE_HOST_OFFSET_PARAM'].value, ft(10), 1e-9)
    b.eq('and the move went', mo_core.ft_to_mm(mo_model.vertical_marker(dud)),
         575.0, 1e-6)

    # a read only elevation is stepped over
    lock = hosted_terminal(ft(900), ft(900), ft(1000), 905,
                           'INSTANCE_ELEVATION_PARAM', ft(900))
    lock.params['INSTANCE_ELEVATION_PARAM'].IsReadOnly = True
    b.eq('a read only elevation is not written', mo_model.shift(None, lock,
                                                                ft(20)),
         u"moved")

    # end to end: a duct on level 2, a fan coil on level 1
    doc = FakeDoc()
    upper = fake_level(951, u"Level 02", ft(3700))
    lower = fake_level(952, u"Level 01", ft(0))
    duct = pipe(ft(6655), ft(200), offset_ft=ft(2955), eid=906)
    duct.LevelId = upper.Id
    unit = hosted_terminal(ft(2400), ft(2400), ft(2900), 907,
                           'INSTANCE_ELEVATION_PARAM', ft(2400),
                           level=lower)
    settings = dict(mo_core.DEFAULTS)
    config = mo_run.RunConfig(doc, u"bottom", settings)
    report = mo_core.Report()
    datum_ft, datum_mm, _m = mo_run.take_datum(doc, duct, config, report)
    b.eq('the duct bottom is the datum, in project elevation', datum_mm,
         6555.0, 1e-6)
    b.eq('and the run knows which level it came off',
         config.datum_level[0], u"Level 02")
    moved = mo_run.apply_to(doc, unit, config, datum_ft, report)
    b.ok('the fan coil on the level below moves', moved)
    b.eq('its bottom lands on the duct bottom',
         mo_core.ft_to_mm(mo_model.measure(doc, unit).bottom), 6555.0, 1e-6)
    b.eq('worked out against its own level, not the duct\'s',
         mo_core.ft_to_mm(unit.params['INSTANCE_ELEVATION_PARAM'].value),
         6555.0, 1e-6)
    b.ok('and the report says what that came out at',
         any([u"Level 01" in n and u"6555 mm above its own level" in n
              for n in report.notes]))
    b.eq('without opening the results window for it', report.problems, [])

    # same level: nothing extra to say
    beside = hosted_terminal(ft(6800), ft(6800), ft(7000), 908,
                             'INSTANCE_ELEVATION_PARAM', ft(3100),
                             level=upper)
    before = len(report.notes)
    mo_run.apply_to(doc, beside, config, datum_ft, report)
    b.eq('a family on the duct\'s own level gets no level note',
         len([n for n in report.notes[before:] if u"own level" in n]), 0)
    b.eq('and still lands on it',
         mo_core.ft_to_mm(mo_model.measure(doc, beside).bottom), 6555.0, 1e-6)


def strut(centre_ft, depth_ft, eid, drops_to_ft=None):
    """A length of channel drawn along a line at its centre, the way support
    steel is: a LocationCurve, a box, and its solids either side of it."""
    low = centre_ft - depth_ft / 2.0
    high = centre_ft + depth_ft / 2.0
    element = FakeElement(eid, {}, FakeCurve(XYZ(0.0, 0.0, centre_ft),
                                             XYZ(3.0, 0.0, centre_ft)),
                          FakeBox(XYZ(0.0, 0.0, low), XYZ(3.0, 0.14, high)),
                          u"MEP Ancillary Framing",
                          eid_of(u"mep_ancillary_framing"), mep=True)
    element.solids = [FakeSolid(low, high, 1.0,
                                [FakeFace(1.0, 0.4, high),
                                 FakeFace(1.0, 0.3, low + 0.01),
                                 FakeFace(-1.0, 0.4, low)],
                                dx=3.0, dy=0.14)]
    if drops_to_ft is not None:
        for _ in (0, 1):
            element.solids.append(FakeSolid(high, drops_to_ft, 1.0,
                                            [FakeFace(1.0, 0.001,
                                                      drops_to_ft)],
                                            dx=0.03, dy=0.03))
        element.box = FakeBox(XYZ(0.0, 0.0, low), XYZ(3.0, 0.14, drops_to_ft))
    return element


def group_framing(b):
    """MEP ancillary framing put flush under a duct."""
    ft = mo_core.mm_to_ft
    depth = ft(41)

    piece = strut(ft(6000), depth, 961)
    m = mo_model.measure(None, piece)
    b.ok('a strut measures', m.ok)
    b.eq('at the top face it supports on', m.route,
         u"the top face it supports on")
    b.eq('which is the top of the channel', mo_core.ft_to_mm(m.top),
         6020.5, 1e-6)
    b.eq('and all three anchors are it',
         (round(m.bottom, 9), round(m.middle, 9)), (round(m.top, 9),) * 2)
    b.ok('not its centreline, which is what put it half its depth proud',
         abs(mo_core.ft_to_mm(m.bottom) - 6000.0) > 10.0)

    # the case in the section: a duct bottom at 6555, a strut under it
    doc = FakeDoc()
    config = mo_run.RunConfig(doc, u"bottom", dict(mo_core.DEFAULTS))
    report = mo_core.Report()
    duct = pipe(ft(6655), ft(200), offset_ft=ft(6655), eid=962)
    datum_ft, datum_mm, _m = mo_run.take_datum(doc, duct, config, report)
    piece = strut(ft(6400), depth, 963)
    b.ok('the strut moves', mo_run.apply_to(doc, piece, config, datum_ft,
                                           report))
    after = solid_top_bottom(piece)
    b.eq('its top is flush with the bottom of the duct',
         mo_core.ft_to_mm(after[1]), 6555.0, 1e-6)
    b.eq('and the channel hangs below it',
         mo_core.ft_to_mm(after[0]), 6555.0 - 41.0, 1e-6)
    b.eq('with nothing to look at', report.problems, [])

    # drops drawn in the family are not the top of it
    piece = strut(ft(6000), depth, 964, drops_to_ft=ft(6800))
    m = mo_model.measure(None, piece)
    b.eq('a strut with drops drawn in it bears on the channel, not the drops',
         mo_core.ft_to_mm(m.top), 6020.5, 1e-6)
    b.eq('found as its bearer', m.route, u"the top of its bearer")

    # the settings
    piece = strut(ft(6000), depth, 965)
    m = mo_model.measure(None, piece, u"size", False, 0.5, None,
                         mo_core.FROM_SOLID, mo_core.FROM_PARAMETERS,
                         mo_core.FROM_BEARING, mo_core.FROM_SOLID)
    b.eq('set to its real faces, bottom is the underside',
         mo_core.ft_to_mm(m.bottom), 5979.5, 1e-6)
    b.eq('and top the top', mo_core.ft_to_mm(m.top), 6020.5, 1e-6)
    m = mo_model.measure(None, piece, u"size", False, 0.5, None,
                         mo_core.FROM_SOLID, mo_core.FROM_PARAMETERS,
                         mo_core.FROM_BEARING, mo_core.FROM_BOX)
    b.eq('set to its box, it is its box', m.route, u"bounding box")
    piece.solids = []
    m = mo_model.measure(None, piece)
    b.eq('with no solids the top of its box stands in', m.route,
         u"the top of its bounding box")
    b.eq('at the same height', mo_core.ft_to_mm(m.top), 6020.5, 1e-6)
    b.eq('the setting defaults to the top face',
         mo_core.DEFAULTS[u"framing_measure"], u"top")


def solid_top_bottom(element):
    low = min([s._box.Min.Z for s in element.solids])
    high = max([s._box.Max.Z for s in element.solids])
    return low, high


GROUPS = (
    ('rounding', group_rounding),
    ('anchors and slopes', group_anchors),
    ('capturing the datum', group_capture),
    ('settings', group_settings),
    ('the category list', group_categories),
    ('equipment set out on its level offset', group_point_based),
    ('fabrication parts and hangers', group_fabrication),
    ('hanger rods after a move', group_hanger_rods),
    ('text and prompts', group_text),
    ('the report', group_report),
    ('measuring', group_measure),
    ('writing', group_shift),
    ('capture then apply', group_end_to_end),
    ('keyboard shortcuts', group_shortcuts),
    ('theme', group_theme),
    ('logging', group_logging),
    ('the resolved config', group_config),
    ('the source moves onto the rounded value', group_source_move),
    ('a family matched across levels', group_across_levels),
    ('support steel flush under a duct', group_framing),
    ('refusals', group_apply_refusals),
    ('slope basics', group_slope_basics),
    ('the crossing in plan', group_slope_crossing),
    ('the branch gradient', group_slope_gradient),
    ('the tilt and the stretch', group_slope_transform),
    ('the slope plan', group_slope_plan),
    ('a junction end to end', group_slope_end_to_end),
    ('the slope config', group_slope_config),
    ('suppressing messages', group_silence),
    ('the status prompts', group_prompts),
    ('the debug report', group_debug),
    ('what Revit objected to', group_failures),
    ('the junction advice', group_junction_advice),
    ('moving one end of a pipe', group_restretch),
    ('turning a fitting onto three pipes', group_vectors),
    ('the routing rule group names', group_routing_names),
    ('squaring an angled branch in', group_squaring),
    ('which way round the junction goes', group_assignment),
    ('the direction of flow', group_flow),
    ('two runs made into one', group_in_line),
)


# ======================================================================
# deliberate breakages
# ======================================================================

def break_rounding():
    original = mo_core.round_value

    def always_nearest(value_mm, step_mm, mode=u"up"):
        return original(value_mm, step_mm, u"nearest")
    mo_core.round_value = always_nearest
    return lambda: setattr(mo_core, 'round_value', original)


def break_anchor():
    original = mo_core.anchor_value

    def swapped(bottom, middle, top, anchor):
        return original(top, middle, bottom, anchor)
    mo_core.anchor_value = swapped
    return lambda: setattr(mo_core, 'anchor_value', original)


def break_half_height():
    original = mo_model.half_height

    def doubled(element, include_insulation):
        value = original(element, include_insulation)
        return None if value is None else value * 2.0
    mo_model.half_height = doubled
    return lambda: setattr(mo_model, 'half_height', original)


def break_settings_split():
    original = mo_core.parse_settings

    def split_every(text):
        values = dict(mo_core.DEFAULTS)
        for line in mo_core.to_text(text).splitlines():
            parts = line.split(u"=")
            if len(parts) < 2:
                continue
            key = parts[0].strip()
            if key in mo_core.DEFAULTS:
                values[key] = parts[1].strip()
        return values
    mo_core.parse_settings = split_every
    return lambda: setattr(mo_core, 'parse_settings', original)


def break_conflict_search():
    original = mo_shortcuts.find_conflicts
    mo_shortcuts.find_conflicts = lambda items, key, keep=u"": []
    return lambda: setattr(mo_shortcuts, 'find_conflicts', original)


def break_key_normalise():
    original = mo_shortcuts.normalise_key
    mo_shortcuts.normalise_key = lambda text: mo_core.to_text(text).strip()
    return lambda: setattr(mo_shortcuts, 'normalise_key', original)


def break_theme_cycle():
    original = mo_theme.next_in_cycle
    mo_theme.next_in_cycle = lambda current: u"dark"
    return lambda: setattr(mo_theme, 'next_in_cycle', original)


def break_shift_absolute():
    original = mo_model.shift

    def writes_the_value(doc, element, delta_ft):
        parameter = element.params.get('RBS_OFFSET_PARAM') \
            if hasattr(element, 'params') else None
        if parameter is not None and not parameter.IsReadOnly:
            parameter.Set(float(delta_ft))
            return u"offset parameter"
        return original(doc, element, delta_ft)
    mo_model.shift = writes_the_value
    return lambda: setattr(mo_model, 'shift', original)


def break_source_left_behind():
    """The v1.0.0 behaviour: the datum is rounded but the element it was
    read off stays where it was."""
    original = mo_run.RunConfig.__init__

    def never_move(self, doc, anchor, settings):
        original(self, doc, anchor, settings)
        self.move_source = False
    mo_run.RunConfig.__init__ = never_move
    return lambda: setattr(mo_run.RunConfig, '__init__', original)


def break_log_never_flushes():
    original = mo_core.flush_log
    mo_core.flush_log = lambda: None
    return lambda: setattr(mo_core, 'flush_log', original)


def break_tilt_sign():
    """The sign that is easy to get backwards and impossible to read."""
    original = geom.tilt_angle
    geom.tilt_angle = lambda now, target: -original(now, target)
    return lambda: setattr(geom, 'tilt_angle', original)


def break_crossing_height():
    """Take the height at the main's mid point rather than at the crossing."""
    original = geom.point_on_line
    geom.point_on_line = lambda a0, a1, t: original(a0, a1, 0.5)
    return lambda: setattr(geom, 'point_on_line', original)


def break_fall_direction():
    """Fall away from the junction rather than towards it."""
    original = geom.target_gradient

    def backwards(main_gradient, branch_gradient, source=geom.FROM_MAIN,
                  direction=geom.TOWARDS, fixed_n=80.0):
        return -original(main_gradient, branch_gradient, source, direction,
                         fixed_n)
    geom.target_gradient = backwards
    return lambda: setattr(geom, 'target_gradient', original)


def break_apparent_guard():
    """Let an apparent crossing through even when the main end is joined."""
    original = geom.build_plan

    def always_free(main_start, main_end, anchor, free_end, source=geom.FROM_MAIN,
                    direction=geom.TOWARDS, fixed_n=80.0,
                    end_tolerance_ft=1.0 / geom.MM_PER_FT,
                    allow_apparent=True, main_end_free=False,
                    in_line_tolerance_deg=2.0):
        return original(main_start, main_end, anchor, free_end, source,
                        direction, fixed_n, end_tolerance_ft, allow_apparent,
                        True, in_line_tolerance_deg)
    geom.build_plan = always_free
    return lambda: setattr(geom, 'build_plan', original)


def break_failure_memory():
    """The 1.2.0 behaviour: warnings deleted, errors ignored, nothing kept."""
    original = mo_run.SwallowWarnings.PreprocessFailures

    def forgetful(self, accessor):
        for failure in accessor.GetFailureMessages():
            try:
                accessor.DeleteWarning(failure)
            except Exception:
                pass
        return None
    mo_run.SwallowWarnings.PreprocessFailures = forgetful
    return lambda: setattr(mo_run.SwallowWarnings, 'PreprocessFailures',
                           original)


def break_angle_advice():
    """Report the raw angle and stop, which is what 1.2.0 did."""
    original = mos_run.angle_advice
    mos_run.angle_advice = lambda angle: u"The branch meets the main at " \
        u"{0:.1f} degrees.".format(angle)
    return lambda: setattr(mos_run, 'angle_advice', original)


def break_debug_settings():
    """A report with no settings in it, which is a report that cannot be
    acted on."""
    original = mo_debug.Recorder.header
    mo_debug.Recorder.header = lambda self, uiapp, doc, settings: None
    return lambda: setattr(mo_debug.Recorder, 'header', original)


def break_curve_direction():
    """The 1.3.0 behaviour: write the fixed end first whichever end it is,
    which reverses the curve half the time."""
    original = slope_model.restretch

    def naive(element, fixed_end, landing):
        ends = slope_model.ends_of(element)
        if ends is None:
            return False, u"no curve"
        if geom.length(fixed_end, landing) < slope_model.JOIN_TOL_FT:
            return False, u"the pipe would have no length left"
        slope_model.set_line(element, fixed_end, landing)
        return True, u"0 stays"
    slope_model.restretch = naive
    return lambda: setattr(slope_model, 'restretch', original)


def break_group_spelling():
    """Ask the enum for the singular, as 1.3.1 did."""
    original = slope_model.ROUTING_GROUPS
    slope_model.ROUTING_GROUPS = tuple(
        [(label, (spellings[-1],)) for label, spellings in original])
    return lambda: setattr(slope_model, 'ROUTING_GROUPS', original)


def break_square_only():
    """Let a square tee be forced onto an angled junction."""
    original = geom.orientation_for

    def always_fits(from_run, from_branch, to_run, to_branch):
        result = original(from_run, from_branch, to_run, to_branch)
        return result[0], result[1], result[2], result[3], 0.0
    geom.orientation_for = always_fits
    return lambda: setattr(geom, 'orientation_for', original)


def break_stub_not_square():
    """Put the bend on the perpendicular through the crossing instead of on
    the branch's own line, which moves the run that was just set out."""
    original = geom.square_junction

    def lazy(crossing, main_dir, branch_dir, stub):
        across = geom.v_add(branch_dir,
                            geom.v_scale(main_dir,
                                         -geom.v_dot(main_dir, branch_dir)))
        unit = geom.v_unit(across)
        if unit is None:
            return None, None
        bend = geom.Pt(crossing.x - unit[0] * stub,
                       crossing.y - unit[1] * stub,
                       crossing.z - unit[2] * stub)
        return crossing, bend
    geom.square_junction = lazy
    return lambda: setattr(geom, 'square_junction', original)


def break_one_assignment_only():
    """The 1.5.0 behaviour: test one way round, and drive the family's angle
    parameter to suit it rather than trying the other way."""
    original = slope_model.choose_assignment

    def first_only(natural, wanted, tolerance_deg):
        if wanted and abs(wanted[0] - natural) <= tolerance_deg:
            return 0
        return -1
    slope_model.choose_assignment = first_only
    return lambda: setattr(slope_model, 'choose_assignment', original)


def break_flow_blind():
    """Choose the way round on the angles alone, as every version up to
    1.6.0 did - which places the junction facing back up the flow half the
    time and joins it perfectly."""
    original = geom.sweeps_with_the_flow
    geom.sweeps_with_the_flow = lambda angle, upstream: True
    return lambda: setattr(geom, 'sweeps_with_the_flow', original)


def break_in_line_fall():
    """Carry the main's fall on without reversing it for a run that points
    the other way, which puts the two into a V instead of one line."""
    original = geom.in_line_gradient

    def unreversed(main_gradient, same_way, source=geom.FROM_MAIN,
                   branch_gradient=None, fixed_n=80.0):
        return original(main_gradient, True, source, branch_gradient, fixed_n)
    geom.in_line_gradient = unreversed
    return lambda: setattr(geom, 'in_line_gradient', original)


def break_structural_on():
    """Ship with structural framing ticked, so a misclick moves a beam."""
    original = mo_core.DEFAULT_CATEGORY_KEYS
    mo_core.DEFAULT_CATEGORY_KEYS = tuple(mo_core.CATEGORY_KEYS)
    saved = mo_core.DEFAULTS[u"categories"]
    mo_core.DEFAULTS[u"categories"] = u"|".join(mo_core.CATEGORY_KEYS)

    def restore():
        mo_core.DEFAULT_CATEGORY_KEYS = original
        mo_core.DEFAULTS[u"categories"] = saved
    return restore


def break_point_from_box():
    """Measure equipment from its bounding box, as every version before
    1.12.0 did - so an air terminal is set out by its flange."""
    original = mo_model.measured_at_a_point
    mo_model.measured_at_a_point = lambda element: False
    return lambda: setattr(mo_model, 'measured_at_a_point', original)


def break_hanger_from_the_top():
    """Take a hanger at the top of its geometry, which is the top of its
    rods up at the soffit, where nothing sits."""
    original = mo_model.bearing_top
    mo_model.bearing_top = lambda element: (None, u"")
    return lambda: setattr(mo_model, 'bearing_top', original)


def break_bearer_is_the_biggest_face():
    """Take the biggest upward face a hanger has, which on a channel is the
    inside of its back and not the flanges the duct sits on."""
    original = mo_core.bearing_from_members
    mo_core.bearing_from_members = lambda *a, **k: None
    mo_model.bearing_from_members = mo_core.bearing_from_members

    def put_back():
        mo_core.bearing_from_members = original
        mo_model.bearing_from_members = original
    return put_back


def break_fab_parameters_trusted():
    """Believe Top of Part and Bottom of Part whatever the solids say."""
    original = mo_model.agreeing

    def credulous(candidates, extent, tolerance=mo_model.AGREE_FT):
        for _label, value in candidates:
            if value is not None:
                return value, u"from its level"
        return None, u"no parameter to read"
    mo_model.agreeing = credulous
    return lambda: setattr(mo_model, 'agreeing', original)


def break_solids_are_the_box():
    """Measure equipment from its bounding box while calling it the solids."""
    original = mo_model.solid_extent

    def from_the_box(element):
        box = mo_model.bounding_box(element)
        if box is None:
            return None
        return (float(box.Min.Z), float(box.Max.Z))
    mo_model.solid_extent = from_the_box
    return lambda: setattr(mo_model, 'solid_extent', original)


def break_rods_left_behind():
    """Move the hanger and leave the rods, so the tops come away from the
    soffit and the hanger hangs on nothing."""
    original = mo_model.keep_rod_tops
    mo_model.keep_rod_tops = lambda element, delta_ft: u""
    return lambda: setattr(mo_model, 'keep_rod_tops', original)


def break_report_split():
    original = mo_core.Report.should_show
    mo_core.Report.should_show = lambda self, mode: bool(
        self.problems or self.notes)
    return lambda: setattr(mo_core.Report, 'should_show', original)


def break_levels_moved_by_hand():
    """Move every family by hand, as 1.15.0 did - which a ceiling grille
    ignores, and which never writes the family's own offset."""
    original_writable = mo_model.writable
    mo_model.writable = lambda element, names: None
    return lambda: setattr(mo_model, 'writable', original_writable)


def break_host_offset_one_way():
    """Assume an offset from host always runs up."""
    original = mo_model.host_offset_direction
    mo_model.host_offset_direction = lambda asked, moved, tolerance=None: 1
    return lambda: setattr(mo_model, 'host_offset_direction', original)


def break_migration_resets_categories():
    """Reset the whole category list to add one row, as v4 and v5 did."""
    original = mo_core.with_categories
    mo_core.with_categories = lambda saved, keys: mo_core.DEFAULTS[
        u"categories"]
    return lambda: setattr(mo_core, 'with_categories', original)


def break_framing_as_a_line():
    """Measure support steel like a duct, from its centreline - which is
    what left it half its depth proud of the duct it went under."""
    original = mo_model.is_ancillary_framing
    mo_model.is_ancillary_framing = lambda element: False
    return lambda: setattr(mo_model, 'is_ancillary_framing', original)


BREAKAGES = (
    ('rounding always rounds to nearest', break_rounding),
    ('the top and bottom anchors are swapped', break_anchor),
    ('half height is doubled', break_half_height),
    ('settings split on every =', break_settings_split),
    ('conflicts are never found', break_conflict_search),
    ('keys are not normalised', break_key_normalise),
    ('the theme chip never cycles', break_theme_cycle),
    ('shift writes the value instead of the delta', break_shift_absolute),
    ('a note opens the results window', break_report_split),
    ('the source is left behind when rounding', break_source_left_behind),
    ('the log never flushes', break_log_never_flushes),
    ('the tilt is applied the wrong way round', break_tilt_sign),
    ('the crossing height is taken at the main mid point',
     break_crossing_height),
    ('the branch falls away from the junction', break_fall_direction),
    ('an apparent crossing ignores a joined main end', break_apparent_guard),
    ('Revit failures are deleted and forgotten', break_failure_memory),
    ('a refused junction reports the angle and nothing else',
     break_angle_advice),
    ('the debug report carries no settings', break_debug_settings),
    ('moving a pipe end reverses its curve', break_curve_direction),
    ('the rule groups are asked for in the singular', break_group_spelling),
    ('a square tee is forced onto an angled junction', break_square_only),
    ('the bend is put off the branch centreline', break_stub_not_square),
    ('only one way round the junction is tried', break_one_assignment_only),
    ('the way round ignores the direction of flow', break_flow_blind),
    ('structural categories ship ticked', break_structural_on),
    ('equipment is measured from its bounding box', break_point_from_box),
    ('a hanger is taken at the top of its rods', break_hanger_from_the_top),
    ('top and bottom of part are believed whatever the solids say',
     break_fab_parameters_trusted),
    ('the solids are read off the bounding box', break_solids_are_the_box),
    ('hanger rods are left behind by the move', break_rods_left_behind),
    ('a hanger is taken at its biggest upward face',
     break_bearer_is_the_biggest_face),
    ('families are moved by hand, never through their own offset',
     break_levels_moved_by_hand),
    ('an offset from host is assumed to run up', break_host_offset_one_way),
    ('a new category resets a trimmed list',
     break_migration_resets_categories),
    ('support steel is measured along its centreline',
     break_framing_as_a_line),
    ('an in-line fall is not reversed for a run facing the other way',
     break_in_line_fall),
)


# ======================================================================
# running
# ======================================================================

def run_all():
    """Run every group. A group that raises is a failure, not a crash.

    A breakage severe enough to make a check raise is still a breakage the
    bench noticed, and losing the rest of the run to it would hide the other
    checks that would also have failed.
    """
    bench = Bench()
    for label, group in GROUPS:
        try:
            group(bench)
        except Exception as err:
            bench.failures.append(u"{0} raised: {1}: {2}".format(
                label, type(err).__name__, err))
    return bench


def main(argv):
    if '--selftest' in argv:
        lines = ['RevoBIM Match Offset - bench logic selftest', '']
        inert = []
        for label, breaker in BREAKAGES:
            restore = breaker()
            try:
                bench = run_all()
            finally:
                restore()
            caught = bool(bench.failures)
            lines.append('  {0}  {1}{2}'.format(
                'caught ' if caught else 'MISSED ', label,
                '  ({0} checks failed)'.format(len(bench.failures))
                if caught else ''))
            if not caught:
                inert.append(label)
        lines.append('')
        if inert:
            lines.append('{0} breakage(s) went unnoticed: {1}'.format(
                len(inert), ', '.join(inert)))
            sys.stdout.write('\n'.join(lines) + '\n')
            return 1
        lines.append('every breakage was caught')
        sys.stdout.write('\n'.join(lines) + '\n')
        return 0

    bench = run_all()
    lines = ['RevoBIM Match Offset - bench logic', '']
    for failure in bench.failures:
        lines.append('  FAIL  {0}'.format(failure))
    lines.append('')
    total = bench.passed + len(bench.failures)
    if bench.failures:
        lines.append('{0} of {1} checks failed'.format(
            len(bench.failures), total))
        sys.stdout.write('\n'.join(lines) + '\n')
        return 1
    lines.append('all {0} checks pass'.format(total))
    sys.stdout.write('\n'.join(lines) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
