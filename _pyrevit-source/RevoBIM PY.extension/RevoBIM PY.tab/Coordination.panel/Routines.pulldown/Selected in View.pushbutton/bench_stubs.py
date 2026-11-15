# -*- coding: utf-8 -*-
"""Stub Revit / .NET API for CPython bench runs.

Each name is declared in the namespace the real API puts it in, and a
module raises ImportError for any name it does not declare - so importing
something from the wrong namespace fails here, not in Revit.
"""
import sys
import types


class _Any(object):
    """Accepts any construction and attribute writes; subscriptable."""
    def __init__(self, *a, **k):
        pass

    def __class_getitem__(cls, item):
        return cls


class _Meta(type):
    def __getitem__(cls, item):
        return cls


def _cls(name, attrs=None):
    return _Meta(name, (_Any,), dict(attrs or {}))


class FakeId(object):
    def __init__(self, value):
        self.Value = value

    def __eq__(self, other):
        return isinstance(other, FakeId) and other.Value == self.Value

    def __hash__(self):
        return hash(self.Value)

    def __repr__(self):
        return 'Id({0})'.format(self.Value)


class _List(object):
    def __init__(self, *a):
        self.items = []

    def Add(self, x):
        self.items.append(x)

    def __iter__(self):
        return iter(self.items)


class _ListMeta(type):
    def __getitem__(cls, item):
        return _List


List = _ListMeta('List', (object,), {})


class _Request(object):
    Accepted = 'Accepted'
    Pending = 'Pending'
    Denied = 'Denied'
    TimedOut = 'TimedOut'


class BuiltInCategory(object):
    OST_RvtLinks = -2001352
    OST_Cameras = -2000500
    OST_IOSSketchGrid = -2000270
    OST_PointClouds = -2010001
    OST_RasterImages = -2000560
    OST_PipeCurves = -2008044


class BuiltInParameter(object):
    SYMBOL_NAME_PARAM = 'SYMBOL_NAME_PARAM'
    ALL_MODEL_TYPE_NAME = 'ALL_MODEL_TYPE_NAME'


class Element(object):
    pass


class RevitLinkInstance(Element):
    pass


class ImportInstance(Element):
    pass


class PointCloudInstance(Element):
    pass


class IndependentTag(Element):
    pass


class SpatialElementTag(Element):
    pass


class FilteredElementCollector(object):
    def __init__(self, doc, view_id=None):
        self.doc = doc
        self.view_id = view_id

    def WhereElementIsNotElementType(self):
        return [e for e in self.doc.in_view(self.view_id) if not getattr(e, 'is_type', False)]


NAMESPACES = {
    'clr': {'AddReference': lambda name: None},
    'System': {'AppDomain': _cls('AppDomain'), 'EventHandler': _cls('EventHandler'),
               'Action': _cls('Action'), 'TimeSpan': _cls('TimeSpan')},
    'System.Collections': {},
    'System.Collections.Generic': {'List': List},
    'System.IO': {'File': _cls('File'), 'MemoryStream': _cls('MemoryStream')},
    'System.Windows': dict((n, _cls(n)) for n in (
        'Thickness', 'CornerRadius', 'GridLength', 'GridUnitType',
        'HorizontalAlignment', 'VerticalAlignment', 'Visibility',
        'TextTrimming', 'FontWeights', 'Clipboard', 'SystemParameters',
        'PresentationSource', 'RoutedEventArgs', 'Window', 'WindowState')),
    'System.Windows.Controls': dict((n, _cls(n)) for n in (
        'StackPanel', 'Grid', 'ColumnDefinition', 'TextBlock', 'CheckBox',
        'Border', 'Button', 'Orientation', 'Image', 'TextBox', 'ScrollViewer')),
    'System.Windows.Controls.Primitives': {'ButtonBase': _cls('ButtonBase'), 'Thumb': _cls('Thumb')},
    'System.Windows.Shapes': {'Path': _cls('Path'), 'Rectangle': _cls('Rectangle')},
    'System.Windows.Media': dict((n, _cls(n)) for n in (
        'Brushes', 'SolidColorBrush', 'ColorConverter', 'Geometry')),
    'System.Windows.Media.Imaging': {'BitmapImage': _cls('BitmapImage'),
                                     'BitmapCacheOption': _cls('BitmapCacheOption')},
    'System.Windows.Markup': {'XamlReader': _cls('XamlReader')},
    'System.Windows.Input': {'Key': _cls('Key')},
    'System.Windows.Interop': {'WindowInteropHelper': _cls('WindowInteropHelper')},
    'System.Windows.Threading': {'DispatcherTimer': _cls('DispatcherTimer')},
    'System.Windows.Forms': {'Screen': _cls('Screen')},
    'Autodesk': {},
    'Autodesk.Revit': {},
    'Autodesk.Revit.DB': {
        'FilteredElementCollector': FilteredElementCollector, 'ElementId': FakeId,
        'Element': Element, 'BuiltInCategory': BuiltInCategory,
        'BuiltInParameter': BuiltInParameter, 'RevitLinkInstance': RevitLinkInstance,
        'ImportInstance': ImportInstance, 'PointCloudInstance': PointCloudInstance,
        'IndependentTag': IndependentTag, 'SpatialElementTag': SpatialElementTag,
    },
    'Autodesk.Revit.UI': {'IExternalEventHandler': _cls('IExternalEventHandler'),
                          'ExternalEvent': _cls('ExternalEvent'),
                          'ExternalEventRequest': _Request,
                          'TaskDialog': _cls('TaskDialog')},
    'Autodesk.Revit.UI.Events': {'SelectionChangedEventArgs': _cls('SelectionChangedEventArgs'),
                                 'ViewActivatedEventArgs': _cls('ViewActivatedEventArgs')},
}


class _StrictModule(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        raise ImportError('stub: {0} is not in namespace {1}'.format(name, self.__name__))


def install():
    for ns, names in NAMESPACES.items():
        mod = _StrictModule(ns)
        mod.__path__ = []
        for k, v in names.items():
            setattr(mod, k, v)
        sys.modules[ns] = mod
    # parents expose children as attributes
    for ns in NAMESPACES:
        if '.' in ns:
            parent, child = ns.rsplit('.', 1)
            if parent in sys.modules:
                setattr(sys.modules[parent], child, sys.modules[ns])


# =====================================================================
# Fake model for logic checks
# =====================================================================
class FakeCategory(object):
    def __init__(self, key, name, ctype='Model', parent=None):
        self.Id = FakeId(key)
        self.Name = name
        self.CategoryType = ctype
        self.Parent = parent


class FakeElement(Element):
    def __init__(self, eid, cat, pinned=False, type_id=None):
        self.Id = FakeId(eid)
        self.Category = cat
        self.Pinned = pinned
        self._type = FakeId(type_id) if type_id is not None else FakeId(-1)

    def GetTypeId(self):
        return self._type


class FakeTag(IndependentTag, FakeElement):
    pass


class FakeLink(RevitLinkInstance, FakeElement):
    pass


class FakeCloud(PointCloudInstance, FakeElement):
    pass


class FakeImport(ImportInstance, FakeElement):
    def __init__(self, eid, cat, linked):
        FakeElement.__init__(self, eid, cat)
        self.IsLinked = linked


class FakeType(object):
    def __init__(self, eid, family, name):
        self.Id = FakeId(eid)
        self.FamilyName = family
        self.Name = name
        self.is_type = True


class FakeView(object):
    def __init__(self, eid, name):
        self.Id = FakeId(eid)
        self.Name = name


class FakeDoc(object):
    Title = 'Bench model'

    def __init__(self):
        self.elements = {}
        self.view_members = {}

    def add(self, e, view=None):
        self.elements[e.Id.Value] = e
        if view is not None:
            self.view_members.setdefault(view.Id.Value, []).append(e)
        return e

    def GetElement(self, eid):
        return self.elements.get(eid.Value)

    def in_view(self, view_id):
        return list(self.view_members.get(view_id.Value, []))
