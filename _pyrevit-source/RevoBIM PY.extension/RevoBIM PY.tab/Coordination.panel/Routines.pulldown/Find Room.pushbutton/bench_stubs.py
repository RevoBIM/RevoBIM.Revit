# -*- coding: utf-8 -*-
"""Stub .NET and Revit API for running Find Room's modules under plain
CPython. Every name is declared in the namespace the REAL API puts it in, so
`from System.Windows import ListBoxItem` (wrong: it is in .Controls) fails
here the way it would fail in Revit.

The Revit stubs are thin but behave: FilteredElementCollector asks the fake
document for its elements, so bench_logic can run the real reads and writes
against a fake model.
"""
import sys
import types


class Anything(object):
    """Permissive stand-in: any attribute, any call, any operator."""

    def __init__(self, *a, **k):
        self.__dict__["_a"] = a

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        value = Anything()
        self.__dict__[name] = value
        return value

    def __call__(self, *a, **k):
        return Anything()

    def __iadd__(self, other):
        return self

    def __getitem__(self, k):
        return Anything()

    def __setitem__(self, k, v):
        pass

    def __iter__(self):
        return iter([])

    def __bool__(self):
        return True

    __nonzero__ = __bool__


def _mod(name, **names):
    m = types.ModuleType(name)
    m.__dict__.update(names)
    sys.modules[name] = m
    if "." in name:
        parent, child = name.rsplit(".", 1)
        if parent in sys.modules:
            setattr(sys.modules[parent], child, m)
    return m


def _cls(name, **attrs):
    return type(name, (Anything,), dict(attrs))


# =============================================================================
# Generic List
# =============================================================================
class _GList(list):
    def Add(self, x):
        self.append(x)

    @property
    def Count(self):
        return len(self)


class _ListFactory(object):
    def __getitem__(self, t):
        return _GList


# =============================================================================
# Revit DB stubs
# =============================================================================
class ElementId(object):
    def __init__(self, value):
        if isinstance(value, ElementId):
            value = value.Value
        self.Value = value

    def __eq__(self, other):
        return isinstance(other, ElementId) and other.Value == self.Value

    def __hash__(self):
        return hash(self.Value)

    def __repr__(self):
        return "Id({0})".format(self.Value)


ElementId.InvalidElementId = ElementId(-1)


class XYZ(object):
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.X, self.Y, self.Z = float(x), float(y), float(z)


class Color(object):
    def __init__(self, r, g, b):
        self.Red, self.Green, self.Blue = r, g, b
        self.IsValid = True


class OverrideGraphicSettings(object):
    def __init__(self):
        self.calls = {}
        self.SurfaceForegroundPatternColor = Color(0, 0, 0)

    def __getattr__(self, name):
        if name.startswith("Set"):
            def setter(value):
                self.calls[name] = value
                if name == "SetSurfaceForegroundPatternColor":
                    self.SurfaceForegroundPatternColor = value
            return setter
        raise AttributeError(name)


class _Enum(object):
    """Enum-ish: members are their own names as text."""

    def __init__(self, name, members):
        self._name = name
        for m in members:
            setattr(self, m, _Member(m))


class _Member(str):
    def ToString(self):
        return str(self)


BuiltInCategory = _Enum("BuiltInCategory", [
    "OST_Rooms", "OST_RoomColorFill", "OST_RoomInteriorFill", "OST_RoomReference",
    "OST_MEPSpaces", "OST_MEPSpaceColorFill", "OST_MEPSpaceInteriorFill",
    "OST_MEPSpaceReference", "OST_SectionBox"])
BuiltInParameter = _Enum("BuiltInParameter", [
    "ROOM_NUMBER", "ROOM_NAME", "SYMBOL_NAME_PARAM", "VIEWPORT_SHEET_NUMBER"])
TemporaryViewMode = _Enum("TemporaryViewMode", ["TemporaryViewProperties",
                                                 "TemporaryHideIsolate"])
FailureSeverity = _Enum("FailureSeverity", ["Warning", "Error"])
FailureProcessingResult = _Enum("FailureProcessingResult", ["Continue"])


class FilteredElementCollector(object):
    def __init__(self, doc):
        self.doc = doc
        self.items = []

    def OfCategory(self, cat):
        self.items = self.doc._by_cat(cat)
        return self

    def OfClass(self, cls):
        self.items = self.doc._by_class(cls)
        return self

    def WhereElementIsNotElementType(self):
        return self

    def GetElementCount(self):
        return len(self.items)

    def __iter__(self):
        return iter(list(self.items))


class Transaction(object):
    log = []

    def __init__(self, doc, name=""):
        self.doc = doc
        self.name = name

    def GetFailureHandlingOptions(self):
        return Anything()

    def SetFailureHandlingOptions(self, o):
        pass

    def Start(self):
        Transaction.log.append(("start", self.name))

    def Commit(self):
        Transaction.log.append(("commit", self.name))

    def RollBack(self):
        Transaction.log.append(("rollback", self.name))


class TransactionGroup(Transaction):
    def Assimilate(self):
        Transaction.log.append(("assimilate", self.name))


class Category(object):
    @staticmethod
    def GetCategory(doc, bic):
        return doc._category(bic)


class ParameterFilterRuleFactory(object):
    @staticmethod
    def CreateEqualsRule(pid, value, *rest):
        return ("eq", pid.Value, value)


class ElementParameterFilter(object):
    def __init__(self, rules):
        self.rules = list(rules)


class ParameterFilterElement(object):
    @staticmethod
    def Create(doc, name, cats, ef):
        return doc._new_filter(name, list(cats), ef)


class IFailuresPreprocessor(object):
    pass


class WorksharingUtils(object):
    @staticmethod
    def CheckoutElements(doc, ids):
        return [i for i in ids if doc._can_borrow(i)]

    @staticmethod
    def GetWorksharingTooltipInfo(doc, i):
        info = Anything()
        info.Owner = "someone"
        return info


_DB_NAMES = dict(
    FilteredElementCollector=FilteredElementCollector, BuiltInCategory=BuiltInCategory,
    BuiltInParameter=BuiltInParameter, ElementId=ElementId, XYZ=XYZ,
    Transaction=Transaction, TransactionGroup=TransactionGroup,
    OverrideGraphicSettings=OverrideGraphicSettings, Color=Color,
    FillPatternElement=_cls("FillPatternElement"),
    ParameterFilterElement=ParameterFilterElement,
    ParameterFilterRuleFactory=ParameterFilterRuleFactory,
    ElementParameterFilter=ElementParameterFilter, FilterRule=_cls("FilterRule"),
    RevitLinkInstance=_cls("RevitLinkInstance"), ViewPlan=_cls("ViewPlan"),
    Category=Category, WorksharingUtils=WorksharingUtils,
    IFailuresPreprocessor=IFailuresPreprocessor,
    FailureProcessingResult=FailureProcessingResult, FailureSeverity=FailureSeverity,
    TemporaryViewMode=TemporaryViewMode, Level=_cls("Level"),
)


# =============================================================================
# Revit UI stubs
# =============================================================================
class IExternalEventHandler(object):
    pass


class _Raise(object):
    answer = "Accepted"


class ExternalEvent(object):
    raised = []

    def __init__(self, handler):
        self.handler = handler

    @staticmethod
    def Create(handler):
        return ExternalEvent(handler)

    def Raise(self):
        ExternalEvent.raised.append(self)
        return _Member(_Raise.answer)

    def Dispose(self):
        pass


class _Theme(object):
    """UITheme.Dark is 0 in Revit - falsy. Reproduced so a truthiness test
    of CurrentCanvasTheme fails here exactly as it does in Revit."""

    def __init__(self, name, value):
        self.name, self.value = name, value

    def ToString(self):
        return self.name

    def __bool__(self):
        return bool(self.value)

    __nonzero__ = __bool__


UITheme_Dark = _Theme("Dark", 0)
UITheme_Light = _Theme("Light", 1)


class UIThemeManager(object):
    CurrentCanvasTheme = UITheme_Dark
    CurrentTheme = UITheme_Light


_UI_NAMES = dict(IExternalEventHandler=IExternalEventHandler, ExternalEvent=ExternalEvent,
                 TaskDialog=_cls("TaskDialog"), UIThemeManager=UIThemeManager)


# =============================================================================
# .NET namespaces (only what Find Room uses - in the right places)
# =============================================================================
class _DispatcherTimer(object):
    def __init__(self):
        self.Interval = None
        self.Tick = Anything()
        self.running = False

    def Start(self):
        self.running = True

    def Stop(self):
        self.running = False


class _Action(object):
    def __init__(self, fn):
        self.fn = fn

    def __call__(self):
        return self.fn()


def install():
    for name in list(sys.modules):
        if name == "System" or name.startswith("System.") or name.startswith("Autodesk") \
                or name == "clr":
            del sys.modules[name]
    _mod("clr", AddReference=lambda name: None)
    _mod("System", Action=_Action, TimeSpan=Anything(), AppDomain=Anything(),
         Byte=int, Int64=int)
    _mod("System.IO", File=Anything(), MemoryStream=Anything)
    _mod("System.Collections")
    _mod("System.Collections.Generic", List=_ListFactory())
    _mod("System.Windows", **dict((n, Anything()) for n in (
        "Visibility", "Thickness", "GridLength", "GridUnitType", "VerticalAlignment",
        "HorizontalAlignment", "TextTrimming", "TextAlignment", "TextWrapping",
        "FontWeights", "Clipboard", "SystemParameters", "FrameworkElement",
        "CornerRadius", "PresentationSource", "WindowStyle", "Window")))
    _mod("System.Windows.Controls", **dict((n, Anything) for n in (
        "ListBoxItem", "Grid", "ColumnDefinition", "TextBlock", "StackPanel",
        "Orientation", "ComboBoxItem", "Border", "ListBox", "Button")))
    _mod("System.Windows.Shapes", Path=Anything)
    _mod("System.Windows.Input", Key=Anything(), Mouse=Anything(), Keyboard=Anything())
    _mod("System.Windows.Threading", DispatcherTimer=_DispatcherTimer)
    _mod("System.Windows.Markup", XamlReader=Anything())
    _mod("System.Windows.Media", SolidColorBrush=Anything, ColorConverter=Anything(),
         Geometry=Anything())
    _mod("System.Windows.Media.Imaging", BitmapImage=Anything, BitmapCacheOption=Anything())
    _mod("System.Windows.Interop", WindowInteropHelper=Anything)
    _mod("System.Windows.Forms", Screen=Anything())
    _mod("Autodesk")
    _mod("Autodesk.Revit")
    _mod("Autodesk.Revit.DB", **_DB_NAMES)
    _mod("Autodesk.Revit.UI", **_UI_NAMES)


install()
