# -*- coding: utf-8 -*-
"""Stand-ins for clr, .NET, WPF and the Revit API so the tool's own modules run
under plain CPython. Each name exists only in the namespace the real API puts
it in. NetObj refuses lowercase attributes the way IronPython refuses new
attributes on a .NET object. Windows are built from the real XAML, so FindName
only finds what the layout really names."""
import os
import sys
import types
import xml.dom.minidom

X_NS = 'http://schemas.microsoft.com/winfx/2006/xaml'


class NetObj(object):
    def __init__(self, name='obj'):
        object.__setattr__(self, '_name', name)
        object.__setattr__(self, '_handlers', [])

    def __getattr__(self, name):
        if name.startswith('__') or not name[0].isupper():
            raise AttributeError("'{0}' object has no attribute '{1}'".format(
                self._name, name))
        child = NetObj(name)
        object.__setattr__(self, name, child)
        return child

    def __setattr__(self, name, value):
        if not name[0].isupper():
            raise AttributeError("'{0}' object has no attribute '{1}'".format(
                self._name, name))
        object.__setattr__(self, name, value)

    def __iadd__(self, handler):
        self._handlers.append(handler)
        return self

    def __call__(self, *args, **kwargs):
        return NetObj(self._name + '()')

    def fire(self, sender=None, args=None):
        for handler in list(self._handlers):
            handler(sender, args)

    def __iter__(self):
        return iter(())

    def __setitem__(self, key, value):
        object.__setattr__(self, '_item_' + str(key), value)

    def __getitem__(self, key):
        return self.__dict__.get('_item_' + str(key))


class FakeList(list):
    locked = False

    def Add(self, item):
        if self.locked:
            raise ValueError('Can only change SelectedItems collection in '
                             'multiple selection modes.')
        self.append(item)

    def Clear(self):
        del self[:]

    @property
    def Count(self):
        return len(self)


class FakeView(list):
    def __init__(self):
        list.__init__(self)
        self.grids = []


class FakeTable(object):
    def __init__(self):
        self.Columns = FakeList()
        self.DefaultView = FakeView()
        self.Rows = self

    def BeginLoadData(self):
        pass

    def EndLoadData(self):
        pass

    def Clear(self):
        del self.DefaultView[:]
        for grid in self.DefaultView.grids:
            del grid.SelectedItems[:]

    def Add(self, values):
        self.DefaultView.append(dict(zip(self.Columns, values)))


class Control(NetObj):
    def __init__(self, name):
        NetObj.__init__(self, name)
        self.Text = u''
        self.SelectedItems = FakeList()
        self.SelectedItem = None
        self.Items = FakeList()
        self.Columns = FakeList()
        self.Children = FakeList()
        self.IsEnabled = True
        self.IsChecked = False
        self.IsMouseOver = False
        self.Value = 0
        self.ActualHeight = 40.0

    def __setattr__(self, name, value):
        if name == 'ItemsSource':
            value.grids.append(self)
        if name == 'SelectedItem' and 'SelectedItems' in self.__dict__:
            list.__init__(self.SelectedItems, [] if value is None else [value])
        NetObj.__setattr__(self, name, value)

    def UnselectAll(self):
        del self.SelectedItems[:]

    def SetResourceReference(self, prop, key):
        self.Foreground = key

    def AddHandler(self, event, handler):
        object.__setattr__(self, '_routed', handler)


class FakeDispatcher(object):
    def BeginInvoke(self, priority, action):
        action()

    def Invoke(self, priority, action):
        action()


class FakeResources(dict):
    def __init__(self):
        dict.__init__(self)
        self.MergedDictionaries = FakeList()


class FakeWindow(Control):
    def __init__(self, path):
        Control.__init__(self, 'Window')
        self.Resources = FakeResources()
        self.Dispatcher = FakeDispatcher()
        self.Left = 100.0
        self.Top = 100.0
        self.Width = 1000.0
        self.Height = 800.0
        self.MinHeight = 620.0
        self.MinWidth = 1040.0
        self.SizeToContent = 'Manual'
        self.Tag = None
        self.IsLoaded = False
        object.__setattr__(self, '_controls', {})
        dom = xml.dom.minidom.parse(path)
        object.__setattr__(self, '_names', set())
        object.__setattr__(self, '_single', set())
        for node in dom.getElementsByTagName('*'):
            value = node.getAttributeNS(X_NS, 'Name') \
                or node.getAttribute('x:Name')
            if value:
                self._names.add(value)
                if node.getAttribute('SelectionMode') == 'Single':
                    self._single.add(value)

    def __setattr__(self, name, value):
        if name == 'Owner' and not value.IsLoaded:
            raise ValueError('Cannot set Owner to a Window not yet shown.')
        Control.__setattr__(self, name, value)

    def FindName(self, name):
        if name not in self._names:
            return None
        if name not in self._controls:
            self._controls[name] = Control(name)
            if name in self._single:
                self._controls[name].SelectedItems.locked = True
        return self._controls[name]

    def FindResource(self, key):
        return 'resource:' + key

    def Close(self):
        args = NetObj('CancelArgs')
        args.Cancel = False
        self.Closing.fire(self, args)
        if not args.Cancel:
            self.Closed.fire(self, None)

    def ShowDialog(self):
        object.__setattr__(self, '_shown', True)
        return SHOW_DIALOG(self)

    def Show(self):
        self.IsLoaded = True
        object.__setattr__(self, '_shown', True)


def SHOW_DIALOG(window):
    return None


class FakeStream(object):
    def __init__(self, path, mode=None, access=None):
        self.path = path

    def Close(self):
        pass


class XamlReader(object):
    @staticmethod
    def Load(stream):
        path = stream.path
        if os.path.basename(path) == 'Theme.xaml':
            return {'theme': path}
        return FakeWindow(path)


class TypedArray(object):
    def __getitem__(self, item):
        return lambda values: list(values)


class TypedList(object):
    def __getitem__(self, item):
        return FakeList


class Marker(object):
    def __init__(self, **values):
        self.__dict__.update(values)


def enum(*names):
    return type('Enum', (object,), dict([(n, n) for n in names]))


class FakeAppDomain(object):
    data = {}

    def GetData(self, key):
        return self.data.get(key)

    def SetData(self, key, value):
        self.data[key] = value


class AppDomain(object):
    CurrentDomain = FakeAppDomain()


class Handler(object):
    pass


# ---------- fake Revit documents ----------

class Id(object):
    def __init__(self, value):
        self.Value = value

    def __eq__(self, other):
        return isinstance(other, Id) and other.Value == self.Value

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        return hash(self.Value)


class Definition(object):
    def __init__(self, name, spec, bip=-1):
        self.Name = name
        self.spec = spec
        self.BuiltInParameter = bip

    def GetGroupTypeId(self):
        return 'group'

    def GetDataType(self):
        return Marker(TypeId=self.spec)


class Param(object):
    """storage is String, Double, Integer or ElementId. Double holds internal
    feet where spec says length; AsValueString gives display text."""
    def __init__(self, name, storage, value, spec='', read_only=False,
                 guid=None, bip=-1, refuse=False, text=None, doc=None):
        self.Definition = Definition(name, spec, bip)
        self.StorageType = storage
        self.value = value
        self.HasValue = value is not None
        self.IsReadOnly = read_only
        self.IsShared = guid is not None
        self.GUID = guid
        self.refuse = refuse
        self.text = text
        self.doc = doc

    def AsString(self):
        return self.value

    def AsDouble(self):
        return self.value

    def AsInteger(self):
        return self.value

    def AsElementId(self):
        return self.value

    def AsValueString(self):
        if self.text is not None:
            return self.text
        if self.Definition.spec == 'length':
            return '{0:g} mm'.format(round(self.value * 304.8, 3))
        if self.Definition.spec == 'bool':
            return 'Yes' if self.value else 'No'
        return str(self.value)

    def Set(self, value):
        if self.refuse:
            return False
        self.doc.journal.append((self, self.value, self.HasValue, self.text))
        self.value = value
        self.text = None
        self.HasValue = True
        self.doc.writes += 1
        return True

    def SetValueString(self, text):
        if self.refuse:
            return False
        import re
        match = re.match(r'^\s*([-+]?\d+(?:\.\d+)?)\s*(mm)?\s*$', text)
        if match is None:
            return False
        number = float(match.group(1))
        if self.Definition.spec == 'length':
            number = number / 304.8
        elif match.group(2):
            return False               # a Number refuses units
        return self.Set(number)


class Elem(object):
    def __init__(self, doc, idv, category, params, type_id=None, name='',
                 family=''):
        self.Id = Id(idv)
        self.UniqueId = 'uid-{0}'.format(idv)
        self.Category = category
        self.params = params
        self.Name = name
        self.FamilyName = family
        self.family_id = None
        self.type_id = type_id
        for param in params:
            param.doc = doc
        doc.elements[idv] = self

    def GetTypeId(self):
        return Id(self.type_id if self.type_id else -1)

    def GetType(self):
        return Marker(Name='FamilySymbol')

    @property
    def Parameters(self):
        return list(self.params)

    def LookupParameter(self, name):
        for param in self.params:
            if param.Definition.Name == name:
                return param
        return None

    def get_Parameter(self, key):
        for param in self.params:
            if param.GUID == key or param.Definition.BuiltInParameter == key:
                return param
        return None


class FamParam(object):
    """A parameter as the family editor sees it."""
    def __init__(self, name, instance, storage, spec='', guid=None, idv=1,
                 formula=False, reporting=False, default=None):
        self.Definition = Definition(name, spec)
        self.IsInstance = instance
        self.StorageType = storage
        self.IsShared = guid is not None
        self.GUID = guid
        self.Id = Id(idv)
        self.IsDeterminedByFormula = formula
        self.IsReporting = reporting
        self.default = default


class Family(object):
    def __init__(self, doc, idv, name, params):
        self.Id = Id(idv)
        self.Name = name
        self.IsEditable = True
        self.IsInPlace = False
        self.params = params
        doc.families[idv] = self


class ExternalDef(object):
    def __init__(self, name, guid, spec):
        self.Name = name
        self.GUID = guid
        self.spec = spec

    def GetDataType(self):
        return Marker(TypeId=self.spec)


class FamilyManager(object):
    def __init__(self, famdoc, params):
        self.famdoc = famdoc
        self.Parameters = list(params)

    def ReplaceParameter(self, current, definition, group, instance):
        if self.famdoc.project.formula_error:
            raise ValueError('The replacement would cause a formula error.')
        if not self.famdoc.modifiable:
            raise ValueError('outside a transaction')
        new = FamParam(definition.Name, instance, current.StorageType,
                       definition.spec, definition.GUID,
                       formula=current.IsDeterminedByFormula,
                       default=current.default)
        self.Parameters[self.Parameters.index(current)] = new
        self.famdoc.swaps.append((current, new))
        return new


class FamilyDoc(object):
    IsFamilyDocument = True

    def __init__(self, project, family):
        self.project = project
        self.family = family
        self.FamilyManager = FamilyManager(self, family.params)
        self.swaps = []
        self.journal = []
        self.elements = {}
        self.fail_ids = set()
        self.transactions = 0
        self.modifiable = False
        self.closed = False

    def Close(self, save):
        assert save is False
        self.closed = True
        self.project.closed += 1

    def LoadFamily(self, target, options):
        """As Revit does: an old parameter is gone from every element and the
        new one starts at the family default, whatever the project held."""
        if target.modifiable:
            raise ValueError('the target document is modifiable')
        if target.refuse_load_in_group and 'open' in target.groups:
            raise ValueError('cannot load inside a transaction group')
        if target.load_returns_none:
            return None
        box = Marker(Value=None)
        options.OnFamilyFound(True, box)
        assert box.Value is True
        self.family.params = list(self.FamilyManager.Parameters)
        target.loads += 1
        for old, new in self.swaps:
            for elem in target.elements.values():
                if elem.family_id != self.family.Id.Value:
                    continue
                if bool(elem.type_id) != bool(old.IsInstance):
                    continue
                keep = [p for p in elem.params if p.Definition.Name
                        != old.Definition.Name]
                if len(keep) != len(elem.params):
                    made = Param(new.Definition.Name, new.StorageType,
                                 new.default, new.Definition.spec,
                                 read_only=new.IsDeterminedByFormula,
                                 guid=new.GUID, doc=target)
                    elem.params = keep + [made]
        return self.family


class Doc(object):
    def __init__(self):
        self.elements = {}
        self.families = {}
        self.modifiable = False
        self.refuse_load_in_group = False
        self.load_returns_none = False
        self.formula_error = False
        self.loads = 0
        self.closed = 0
        self.IsWorkshared = False
        self.held = set()
        self.journal = []
        self.writes = 0
        self.fail_ids = set()
        self.groups = []
        self.transactions = 0

    def GetElement(self, eid):
        return self.elements.get(eid.Value) or self.families.get(eid.Value)

    def EditFamily(self, family):
        if self.modifiable:
            raise ValueError('the document is modifiable')
        return FamilyDoc(self, family)

    def Equals(self, other):
        return self is other


class Collector(object):
    def __init__(self, doc):
        self.doc = doc
        self.items = list(doc.elements.values())

    def WhereElementIsNotElementType(self):
        self.items = [e for e in self.items if e.type_id]
        return self

    def WhereElementIsElementType(self):
        self.items = [e for e in self.items if not e.type_id]
        return self

    def OfCategoryId(self, cat_id):
        self.items = [e for e in self.items if e.Category.Id == cat_id]
        return self

    def __iter__(self):
        return iter(self.items)


class Options(object):
    def SetFailuresPreprocessor(self, item):
        pass

    def SetClearAfterRollback(self, flag):
        pass


class Transaction(object):
    def __init__(self, doc, name=''):
        self.doc = doc
        self.started = False
        self.ended = False

    def GetFailureHandlingOptions(self):
        return Options()

    def SetFailureHandlingOptions(self, options):
        pass

    def Start(self):
        self.started = True
        self.doc.transactions += 1
        self.doc.journal = []
        self.doc.modifiable = True

    def HasStarted(self):
        return self.started

    def HasEnded(self):
        return self.ended

    def Commit(self):
        self.ended = True
        self.doc.modifiable = False
        for entry in self.doc.journal:
            for elem in self.doc.elements.values():
                if entry[0] in elem.params and elem.Id.Value in self.doc.fail_ids:
                    self.undo()
                    return 'RolledBack'
        return 'Committed'

    def undo(self):
        for param, value, has, text in reversed(self.doc.journal):
            param.value, param.HasValue, param.text = value, has, text
        self.doc.journal = []

    def RollBack(self):
        self.ended = True
        self.doc.modifiable = False
        self.undo()


class SubTransaction(object):
    def __init__(self, doc):
        pass

    def Start(self):
        pass

    def Commit(self):
        pass

    def RollBack(self):
        pass


class TransactionGroup(object):
    def __init__(self, doc, name=''):
        self.doc = doc
        self.ended = False

    def Start(self):
        self.doc.groups.append('open')

    def Assimilate(self):
        self.doc.groups[-1] = 'assimilated'
        self.ended = True

    def HasStarted(self):
        return True

    def HasEnded(self):
        return self.ended

    def RollBack(self):
        self.doc.groups[-1] = 'rolled back'


class WorksharingUtils(object):
    @staticmethod
    def CheckoutElements(doc, ids):
        if not doc.IsWorkshared:
            raise ValueError('not workshared')
        return [i for i in ids if i.Value not in doc.held]

    @staticmethod
    def GetWorksharingTooltipInfo(doc, eid):
        return Marker(Owner='Sam')


NAMESPACES = {
    'System': dict(Action=lambda fn: fn, Array=TypedArray(), Object=object,
                   AppDomain=AppDomain, Double=Marker(NaN='nan'),
                   TimeSpan=NetObj('TimeSpan'), Guid=lambda text: text),
    'System.IO': dict(File=NetObj('File'), FileAccess=NetObj('FileAccess'),
                      FileMode=NetObj('FileMode'),
                      FileStream=FakeStream, MemoryStream=NetObj('MemoryStream')),
    'System.Collections': {},
    'System.Collections.Generic': dict(List=TypedList()),
    'System.Data': dict(DataTable=FakeTable),
    'System.Windows': dict(
        Clipboard=NetObj('Clipboard'),
        PresentationSource=NetObj('PresentationSource'),
        RoutedEventHandler=lambda fn: fn,
        SizeToContent=enum('Manual', 'Height'),
        SystemParameters=NetObj('SystemParameters'),
        VerticalAlignment=enum('Top', 'Stretch'),
        Visibility=enum('Visible', 'Collapsed', 'Hidden'),
        WindowStartupLocation=enum('CenterScreen', 'CenterOwner')),
    'System.Windows.Controls': dict(
        Button=lambda: Control('Button'), DataGridLength=lambda *a: a,
        DataGridLengthUnitType=enum('Star'),
        DataGridTemplateColumn=lambda: Control('tcol'),
        DataGridTextColumn=lambda: Control('col'),
        TextBlock=NetObj('TextBlock')),
    'System.Windows.Controls.Primitives': dict(ButtonBase=NetObj('ButtonBase')),
    'System.Windows.Data': dict(Binding=lambda name: name),
    'System.Windows.Input': dict(
        Key=enum('Escape', 'Enter', 'F11', 'H', 'Delete'),
        Keyboard=Marker(Modifiers=0, FocusedElement=None),
        ModifierKeys=Marker(Control=2, Shift=4)),
    'System.Windows.Interop': dict(WindowInteropHelper=lambda w: NetObj('helper')),
    'System.Windows.Markup': dict(XamlReader=XamlReader),
    'System.Windows.Media': dict(
        ColorConverter=NetObj('ColorConverter'),
        SolidColorBrush=lambda color: NetObj('Brush')),
    'System.Windows.Media.Imaging': dict(
        BitmapCacheOption=NetObj('BitmapCacheOption'),
        BitmapImage=lambda: NetObj('BitmapImage')),
    'System.Windows.Threading': dict(
        DispatcherPriority=enum('Render', 'Background'),
        DispatcherTimer=lambda *a: NetObj('Timer')),
    'System.Windows.Forms': dict(Screen=NetObj('Screen')),
    'Autodesk': {}, 'Autodesk.Revit': {},
    'Autodesk.Revit.DB': dict(
        ElementId=Id, Element=NetObj('Element'),
        FilteredElementCollector=Collector, IFailuresPreprocessor=Handler,
        SubTransaction=SubTransaction, Transaction=Transaction,
        TransactionGroup=TransactionGroup, WorksharingUtils=WorksharingUtils,
        FailureProcessingResult=enum('Continue', 'ProceedWithRollBack'),
        FamilySource=enum('Family', 'Project'),
        IFamilyLoadOptions=Handler),
    'Autodesk.Revit.UI': dict(ExternalEvent=NetObj('ExternalEvent'),
                              IExternalEventHandler=Handler,
                              TaskDialog=NetObj('TaskDialog')),
}


def install():
    clr = types.ModuleType('clr')
    clr.AddReference = lambda name: None
    sys.modules['clr'] = clr
    for name, values in NAMESPACES.items():
        module = types.ModuleType(name)
        module.__path__ = []
        module.__dict__.update(values)
        sys.modules[name] = module
    for name in NAMESPACES:
        if '.' in name:
            parent, child = name.rsplit('.', 1)
            setattr(sys.modules[parent], child, sys.modules[name])
