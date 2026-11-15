# -*- coding: utf-8 -*-
"""A stand-in Revit and .NET for CPython. Every name sits in the namespace the
real API puts it in, so a mis-namespaced import fails on the bench."""
import sys
import types


class Dummy(object):
    def __init__(self, *args, **kwargs):
        pass


class Enumish(type):
    def __getattr__(cls, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return name


class EnumDummy(Dummy, metaclass=Enumish):
    pass


class ElementId(object):
    def __init__(self, value):
        self.Value = value


class NameSlot(object):
    def __get__(self, obj, owner):
        if obj is None:
            return self
        return obj.stored_name

    def __set__(self, obj, value):
        obj.set_name(value)

    def GetValue(self, element):
        return element.stored_name

    def SetValue(self, element, value):
        element.set_name(value)


class Element(object):
    Name = NameSlot()

    def __init__(self, key, name, doc):
        self.Id = ElementId(key)
        self.stored_name = name
        self.doc = doc
        doc.add(self)

    def set_name(self, value):
        self.doc.check_name(self, value)
        self.stored_name = value


class View(Element):
    IsTemplate = False

    def __init__(self, key, name, doc, view_type='FloorPlan'):
        Element.__init__(self, key, name, doc)
        self.ViewType = view_type


class ViewSheet(View):
    def __init__(self, key, name, number, doc):
        View.__init__(self, key, name, doc, 'DrawingSheet')
        self.stored_number = number
        self.params = {}

    def LookupParameter(self, name):
        return self.params.get(name)

    @property
    def SheetNumber(self):
        return self.stored_number

    @SheetNumber.setter
    def SheetNumber(self, value):
        self.doc.check_number(self, value)
        self.stored_number = value


class Param(object):
    IsReadOnly = False
    StorageType = 'String'

    def __init__(self, value=None, stick=True, doc=None):
        self.value = value
        self.stick = stick
        self.doc = doc

    def AsString(self):
        return self.value

    def Set(self, value):
        if self.stick:
            self.value = value
        return True


class Family(Element):
    class Cat(object):
        Name = 'Pipe Fittings'
    FamilyCategory = Cat()


class ElementType(Element):
    FamilyName = 'Pipe Types'


class RevitLinkType(ElementType):
    pass


class CADLinkType(ElementType):
    pass


class FilteredElementCollector(object):
    def __init__(self, doc):
        self.doc = doc
        self.cls = Element

    def OfClass(self, cls):
        self.cls = cls
        return self

    def __iter__(self):
        return iter([e for e in self.doc.elements.values() if isinstance(e, self.cls)])


class _Tx(object):
    def __init__(self, doc, name=None):
        self.doc = doc

    def Start(self):
        self.snap = self.doc.snapshot()

    def RollBack(self):
        self.doc.restore(self.snap)

    def Commit(self):
        self.doc.on_commit()
        return 'Committed'


class TransactionGroup(object):
    def __init__(self, doc, name=None):
        self.doc = doc

    def Start(self):
        self.snap = self.doc.snapshot()

    def Assimilate(self):
        pass

    def RollBack(self):
        self.doc.restore(self.snap)


class Transaction(_Tx):
    class Options(object):
        def SetFailuresPreprocessor(self, value):
            pass

        def SetClearAfterRollback(self, value):
            pass

    def GetFailureHandlingOptions(self):
        return self.Options()

    def SetFailureHandlingOptions(self, value):
        pass


class SubTransaction(_Tx):
    def Commit(self):
        return 'Committed'


class WorksharingUtils(object):
    @staticmethod
    def CheckoutElements(doc, ids):
        return [i for i in ids if i.Value not in doc.owned]

    @staticmethod
    def GetWorksharingTooltipInfo(doc, element_id):
        info = Dummy()
        info.Owner = doc.owned.get(element_id.Value)
        return info


class ListType(list):
    def Add(self, value):
        self.append(value)


class ListFactory(object):
    def __getitem__(self, item):
        return ListType


REVIT_DB = {
    'BuiltInParameter': EnumDummy, 'CADLinkType': CADLinkType,
    'Element': Element, 'ElementId': ElementId, 'ElementType': ElementType,
    'Family': Family, 'FilteredElementCollector': FilteredElementCollector,
    'IFailuresPreprocessor': Dummy, 'FailureProcessingResult': EnumDummy,
    'RevitLinkType': RevitLinkType, 'SubTransaction': SubTransaction,
    'Transaction': Transaction, 'TransactionGroup': TransactionGroup, 'View': View, 'ViewSheet': ViewSheet,
    'WorksharingUtils': WorksharingUtils,
}

NAMESPACES = {
    'System': ['Action', 'AppDomain', 'Double', 'TimeSpan'],
    'System.Collections': [],
    'System.Collections.Generic': [],
    'System.IO': ['File', 'MemoryStream', 'StringReader'],
    'System.Windows': [
        'FontWeights', 'FrameworkElement', 'GridLength', 'GridUnitType',
        'PresentationSource', 'Size', 'SizeToContent', 'SystemParameters', 'TextTrimming', 'TextWrapping',
        'Thickness', 'VerticalAlignment', 'Visibility',
        'WindowStartupLocation'],
    'System.Windows.Controls': ['Border', 'ColumnDefinition', 'Grid', 'TextBlock'],
    'System.Windows.Documents': ['Run', 'TextElement'],
    'System.Windows.Forms': ['Screen'],
    'System.Windows.Input': ['Key', 'Keyboard', 'ModifierKeys'],
    'System.Windows.Interop': ['WindowInteropHelper'],
    'System.Windows.Markup': ['XamlReader'],
    'System.Windows.Media': ['ColorConverter', 'SolidColorBrush'],
    'System.Windows.Media.Imaging': ['BitmapCacheOption', 'BitmapImage'],
    'System.Windows.Threading': ['DispatcherTimer'],
    'System.Xml': ['XmlReader'],
    'Autodesk': [], 'Autodesk.Revit': [],
    'Autodesk.Revit.UI': ['ExternalEvent', 'IExternalEventHandler', 'TaskDialog'],
}


def install():
    for name in list(sys.modules):
        if name == 'clr' or name.split('.')[0] in ('System', 'Autodesk') or name.startswith('brn_'):
            del sys.modules[name]
    clr = types.ModuleType('clr')
    clr.AddReference = lambda name: None
    sys.modules['clr'] = clr
    for name, members in NAMESPACES.items():
        module = types.ModuleType(name)
        module.__path__ = []
        for member in members:
            setattr(module, member, EnumDummy)
        sys.modules[name] = module
    db = types.ModuleType('Autodesk.Revit.DB')
    for key, value in REVIT_DB.items():
        setattr(db, key, value)
    sys.modules['Autodesk.Revit.DB'] = db
    sys.modules['Autodesk.Revit'].DB = db
    sys.modules['Autodesk.Revit'].UI = sys.modules['Autodesk.Revit.UI']
    sys.modules['Autodesk'].Revit = sys.modules['Autodesk.Revit']
    sys.modules['System.Collections.Generic'].List = ListFactory()
