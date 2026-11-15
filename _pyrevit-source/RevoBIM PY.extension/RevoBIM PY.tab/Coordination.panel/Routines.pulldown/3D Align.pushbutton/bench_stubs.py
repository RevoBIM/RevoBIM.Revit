# -*- coding: utf-8 -*-
"""Stub Revit and .NET API for the 3D Align bench. CPython only, never loaded
by Revit.

Every name is declared in the namespace the real API puts it in, and nothing
else is: `from Autodesk.Revit.DB import ObjectType` fails here exactly as it
fails in Revit. The Revit DB fakes behave enough like Revit for the move,
the rollback, the pin, the borrow and the read-back to be exercised.
"""
import copy
import sys
import types


# ==========================================================================
# Revit DB fakes
# ==========================================================================

class XYZ(object):
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.X, self.Y, self.Z = float(x), float(y), float(z)


class ElementId(object):
    def __init__(self, value):
        self.Value = value


class Line(object):
    def __init__(self, p0, p1):
        self.p = [p0, p1]

    def GetEndPoint(self, index):
        return self.p[index]


class LocationCurve(object):
    def __init__(self, curve):
        self.Curve = curve


class _Members(object):
    def __init__(self, **members):
        self.__dict__.update(members)


BuiltInCategory = _Members(OST_PipeCurves=-2008044, OST_DuctCurves=-2008000,
                           OST_CableTray=-2008130, OST_Conduit=-2008132,
                           OST_PipeFitting=-2008049)
BuiltInParameter = _Members(RBS_CALCULATED_SIZE='RBS_CALCULATED_SIZE')
FailureSeverity = _Members(Warning='Warning', Error='Error')
FailureProcessingResult = _Members(Continue='Continue', ProceedWithRollBack='ProceedWithRollBack')
TransactionStatus = _Members(Committed='Committed', RolledBack='RolledBack')
ObjectType = _Members(Element='Element')


class IFailuresPreprocessor(object):
    pass


class ISelectionFilter(object):
    pass


class OperationCanceledException(Exception):
    pass


class _Message(object):
    def __init__(self, severity, text):
        self.severity, self.text = severity, text

    def GetSeverity(self):
        return self.severity

    def GetDescriptionText(self):
        return self.text


class _Accessor(object):
    def __init__(self, messages):
        self.messages = messages
        self.deleted = []

    def GetFailureMessages(self):
        return list(self.messages)

    def DeleteWarning(self, message):
        self.deleted.append(message)


class _Options(object):
    def __init__(self):
        self.pre = None
        self.clear = False

    def SetFailuresPreprocessor(self, pre):
        self.pre = pre

    def SetClearAfterRollback(self, value):
        self.clear = value


class Transaction(object):
    def __init__(self, doc, name):
        self.doc, self.name = doc, name
        self.options = _Options()
        self.snapshot = None

    def GetFailureHandlingOptions(self):
        return self.options

    def SetFailureHandlingOptions(self, options):
        self.options = options

    def Start(self):
        self.doc.transactions += 1
        self.doc.pending = []
        self.snapshot = self.doc.take_snapshot()

    def RollBack(self):
        self.doc.restore(self.snapshot)
        return TransactionStatus.RolledBack

    def Commit(self):
        messages = [_Message(FailureSeverity.Warning, w) for w in self.doc.warnings_on_commit]
        messages += [_Message(FailureSeverity.Error, e) for e in self.doc.pending]
        if messages and self.options.pre is not None:
            result = self.options.pre.PreprocessFailures(_Accessor(messages))
            if result == FailureProcessingResult.ProceedWithRollBack:
                self.doc.restore(self.snapshot)
                return TransactionStatus.RolledBack
        self.doc.commits += 1
        return TransactionStatus.Committed


class ElementTransformUtils(object):
    @staticmethod
    def MoveElement(doc, element_id, vector):
        element = doc.GetElement(element_id)
        if element.Pinned:
            raise Exception('The element is pinned')
        if doc.silent_noop:
            return
        if element.refuse_connected and any(c.IsConnected for c in element.connectors):
            doc.pending.append(u'Can\'t keep elements joined.')
        element.shift(vector)
        for other_id in element.drags:
            doc.GetElement(ElementId(other_id)).shift_end(vector)


class _Tooltip(object):
    def __init__(self, owner):
        self.Owner = owner


class WorksharingUtils(object):
    @staticmethod
    def CheckoutElements(doc, ids):
        return [i for i in ids if i.Value not in doc.held_by_other]

    @staticmethod
    def GetWorksharingTooltipInfo(doc, element_id):
        return _Tooltip(doc.held_by_other.get(element_id.Value, u''))


class TaskDialog(object):
    @staticmethod
    def Show(title, text):
        return None


# ==========================================================================
# model fakes (not part of any namespace)
# ==========================================================================

class FakeCategory(object):
    def __init__(self, value, name):
        self.Id = ElementId(value)
        self.Name = name


class FakeParameter(object):
    def __init__(self, text):
        self.text = text

    def AsString(self):
        return self.text


class FakeRef(object):
    def __init__(self, owner, connector_type=1):
        self.Owner = owner
        self.ConnectorType = connector_type


class FakeConnector(object):
    def __init__(self, other):
        self.refs = [FakeRef(other)]
        self.IsConnected = True

    @property
    def AllRefs(self):
        return list(self.refs) if self.IsConnected else []

    def DisconnectFrom(self, ref):
        self.refs = [r for r in self.refs if r is not ref]
        self.IsConnected = bool(self.refs)


class _ConnectorManager(object):
    def __init__(self, element):
        self.element = element

    @property
    def Connectors(self):
        return list(self.element.connectors)


class _Owner(object):
    def __init__(self, value):
        self.Id = ElementId(value)


class FakeElement(object):
    def __init__(self, value, p0, p1, category='pipe', pinned=False, group=-1,
                 connections=0, refuse_connected=False, drags=()):
        cats = {'pipe': (BuiltInCategory.OST_PipeCurves, u'Pipes'),
                'duct': (BuiltInCategory.OST_DuctCurves, u'Ducts'),
                'tray': (BuiltInCategory.OST_CableTray, u'Cable Trays'),
                'conduit': (BuiltInCategory.OST_Conduit, u'Conduits'),
                'fitting': (BuiltInCategory.OST_PipeFitting, u'Pipe Fittings')}
        self.Id = ElementId(value)
        self.Category = FakeCategory(*cats[category])
        self.Location = LocationCurve(Line(XYZ(*p0), XYZ(*p1)))
        self.Pinned = pinned
        self.GroupId = ElementId(group)
        self.connectors = [FakeConnector(_Owner(9000 + i)) for i in range(connections)]
        self.ConnectorManager = _ConnectorManager(self)
        self.refuse_connected = refuse_connected
        self.drags = list(drags)

    def get_Parameter(self, member):
        return FakeParameter(u'100mm')

    def shift(self, v):
        line = self.Location.Curve
        line.p = [XYZ(p.X + v.X, p.Y + v.Y, p.Z + v.Z) for p in line.p]

    def shift_end(self, v):
        line = self.Location.Curve
        p = line.p[1]
        line.p[1] = XYZ(p.X + v.X, p.Y + v.Y, p.Z + v.Z)

    def axis(self):
        return tuple((p.X, p.Y, p.Z) for p in self.Location.Curve.p)


class FakeDoc(object):
    def __init__(self, elements, workshared=False):
        self.elements = dict((e.Id.Value, e) for e in elements)
        self.IsWorkshared = workshared
        self.held_by_other = {}
        self.transactions = 0
        self.commits = 0
        self.pending = []
        self.warnings_on_commit = []
        self.silent_noop = False

    def GetElement(self, element_id):
        value = element_id.Value if hasattr(element_id, 'Value') else element_id
        return self.elements.get(value)

    def take_snapshot(self):
        return copy.deepcopy(dict((k, (e.Location.Curve.p, e.Pinned,
                                       [(c.IsConnected, list(c.refs)) for c in e.connectors]))
                                  for k, e in self.elements.items()))

    def restore(self, snapshot):
        for key, (points, pinned, conns) in snapshot.items():
            element = self.elements[key]
            element.Location.Curve.p = copy.deepcopy(points)
            element.Pinned = pinned
            for connector, (connected, refs) in zip(element.connectors, conns):
                connector.IsConnected = connected
                connector.refs = refs


class _Reference(object):
    def __init__(self, element):
        self.ElementId = element.Id


class FakeSelection(object):
    def __init__(self, doc, picks, selected=()):
        self.doc = doc
        self.picks = list(picks)
        self.selected = list(selected)
        self.prompts = []
        self.filters = []

    def PickObject(self, object_type, selection_filter, prompt):
        self.prompts.append(prompt)
        self.filters.append(selection_filter)
        if not self.picks:
            raise OperationCanceledException()
        element = self.picks.pop(0)
        if element is None:
            raise OperationCanceledException()
        if not selection_filter.AllowElement(element):
            raise AssertionError('the filter refused a pick the test expected to be allowed')
        return _Reference(element)

    def GetElementIds(self):
        return [e.Id for e in self.selected]

    def SetElementIds(self, ids):
        self.selected = [self.doc.GetElement(i) for i in ids]


class FakeUIDoc(object):
    def __init__(self, doc, picks, selected=()):
        self.Document = doc
        self.Selection = FakeSelection(doc, picks, selected)


class FakeUIApp(object):
    def __init__(self, uidoc):
        self.ActiveUIDocument = uidoc


class FakeEnum(object):
    """A .NET enum value: UITheme.Dark is 0 and so is falsy."""
    def __init__(self, number, name):
        self.number, self.name = number, name

    def __int__(self):
        return self.number

    def __bool__(self):
        return bool(self.number)
    __nonzero__ = __bool__

    def __str__(self):
        return self.name


# ==========================================================================
# namespaces
# ==========================================================================

def _dummy(name):
    return type(name, (object,), {})


class _GenericList(object):
    def __getitem__(self, item_type):
        class _List(list):
            def Add(self, item):
                self.append(item)
        return _List


NAMESPACES = {
    'clr': {'AddReference': lambda name: None, 'GetClrType': lambda t: t},
    'System': {'Action': _dummy('Action'), 'Object': object, 'Exception': Exception},
    'System.Collections': {},
    'System.Collections.Generic': {'List': _GenericList()},
    'System.IO': {'File': _dummy('File'), 'MemoryStream': _dummy('MemoryStream')},
    'System.Diagnostics': {'Process': _dummy('Process')},
    'System.Windows': dict((n, _dummy(n)) for n in (
        'Window', 'FrameworkElement', 'GridLength', 'GridUnitType', 'PresentationSource',
        'SystemParameters', 'TextWrapping', 'Thickness', 'CornerRadius',
        'HorizontalAlignment', 'VerticalAlignment', 'FontWeights', 'Visibility')),
    'System.Windows.Controls': dict((n, _dummy(n)) for n in (
        'Border', 'ColumnDefinition', 'Grid', 'StackPanel', 'TextBlock', 'Button')),
    'System.Windows.Forms': {'Screen': _dummy('Screen')},
    'System.Windows.Input': {'Key': _dummy('Key')},
    'System.Windows.Interop': {'WindowInteropHelper': _dummy('WindowInteropHelper')},
    'System.Windows.Markup': {'XamlReader': _dummy('XamlReader')},
    'System.Windows.Media': {'Color': _dummy('Color'), 'SolidColorBrush': _dummy('SolidColorBrush')},
    'System.Windows.Media.Imaging': {'BitmapImage': _dummy('BitmapImage'),
                                     'BitmapCacheOption': _dummy('BitmapCacheOption')},
    'Autodesk': {},
    'Autodesk.Revit': {},
    'Autodesk.Revit.DB': {
        'BuiltInCategory': BuiltInCategory, 'BuiltInParameter': BuiltInParameter,
        'ElementId': ElementId, 'ElementTransformUtils': ElementTransformUtils,
        'FailureProcessingResult': FailureProcessingResult, 'FailureSeverity': FailureSeverity,
        'IFailuresPreprocessor': IFailuresPreprocessor, 'Line': Line,
        'LocationCurve': LocationCurve, 'Transaction': Transaction,
        'TransactionStatus': TransactionStatus, 'WorksharingUtils': WorksharingUtils, 'XYZ': XYZ},
    'Autodesk.Revit.UI': {'TaskDialog': TaskDialog},
    'Autodesk.Revit.UI.Selection': {'ISelectionFilter': ISelectionFilter, 'ObjectType': ObjectType},
    'Autodesk.Revit.Exceptions': {'OperationCanceledException': OperationCanceledException},
}


def install():
    for name in sorted(NAMESPACES, key=lambda n: n.count('.')):
        module = types.ModuleType(name)
        module.__path__ = []
        for key, value in NAMESPACES[name].items():
            setattr(module, key, value)
        sys.modules[name] = module
        if '.' in name:
            parent, child = name.rsplit('.', 1)
            setattr(sys.modules[parent], child, module)


TOOL_MODULES = ('a3d_clr', 'a3d_settings', 'a3d_geom', 'theme', 'a3d_core', 'a3d_ui')


def purge():
    for name in TOOL_MODULES:
        sys.modules.pop(name, None)
