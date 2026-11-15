# -*- coding: utf-8 -*-
"""Bench stub of the .NET and Revit API, for running the tool under CPython.

Every name is declared in the namespace the REAL API puts it in, and a
module refuses any name it does not declare - so `from System.Windows.Media
import LogicalTreeHelper` fails here exactly as it fails in Revit, where it
shows as a blank white pyRevit window.

install() puts the stubs in sys.modules; bench_logic.py swaps fakes into
Autodesk.Revit.DB to drive the apply routines against a fake model.
"""

import sys
import types


class NetStub(object):
    """Stands in for any .NET class or instance: constructible, callable,
    indexable (List[T]), and any attribute is another stub."""

    def __init__(self, *args, **kwargs):
        self._args = args

    def __call__(self, *args, **kwargs):
        return NetStub()

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return NetStub()

    def __getitem__(self, item):
        return NetStub

    def __iter__(self):
        return iter([])

    def __iadd__(self, other):
        return self

    def __or__(self, other):
        return self

    def __and__(self, other):
        return self


class StrictModule(types.ModuleType):
    """A namespace that only hands out the names it declares."""

    def __init__(self, name, names):
        types.ModuleType.__init__(self, name)
        self.__declared__ = set(names)
        self.__path__ = []
        for item in names:
            setattr(self, item, type(str(item), (NetStub,), {}))

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        raise ImportError("cannot import name {0} from {1}".format(name, self.__name__))


NAMESPACES = {
    "System": ["Action", "AppDomain", "TimeSpan", "Array", "Byte", "Int64"],
    "System.IO": ["File", "MemoryStream", "StringReader", "StreamReader"],
    "System.IO.Compression": ["ZipArchive", "ZipArchiveMode", "ZipFile", "CompressionLevel"],
    "System.Text": ["Encoding"],
    "System.Xml": ["XmlDocument", "XmlReader"],
    "System.Data": ["DataTable", "DataView"],
    "System.Diagnostics": ["Process"],
    "System.Collections": [],
    "System.Collections.Generic": ["List"],
    "System.Windows": [
        "CornerRadius", "FontWeights", "FrameworkElement", "GridLength", "GridUnitType",
        "HorizontalAlignment", "LogicalTreeHelper", "PresentationSource", "ResizeMode",
        "TextTrimming", "TextWrapping", "Thickness", "VerticalAlignment", "Visibility",
        "Window", "WindowStartupLocation", "WindowStyle"],
    "System.Windows.Controls": [
        "Border", "Button", "CheckBox", "ColumnDefinition", "DataGridCell", "DataGridCellInfo",
        "DataGridEditingUnit", "DataGridLength", "DataGridLengthUnitType",
        "DataGridTemplateColumn",
        "DataGridTextColumn", "Grid", "ListBox", "ListBoxItem", "Orientation",
        "RowDefinition", "ScrollBarVisibility", "ScrollViewer", "StackPanel",
        "TextBlock", "TextBox", "WrapPanel"],
    "System.Windows.Controls.Primitives": ["PlacementMode", "Popup", "Thumb", "ToggleButton"],
    "System.Windows.Data": ["Binding"],
    "System.Windows.Input": ["Cursors", "Key", "Keyboard", "ModifierKeys"],
    "System.Windows.Interop": ["WindowInteropHelper"],
    "System.Windows.Markup": ["XamlReader"],
    "System.Windows.Media": ["ColorConverter", "FontFamily", "SolidColorBrush",
                             "VisualTreeHelper"],
    "System.Windows.Media.Imaging": ["BitmapCacheOption", "BitmapImage"],
    "System.Windows.Threading": ["DispatcherPriority", "DispatcherTimer"],
    "System.Windows.Forms": ["Screen"],
    "Microsoft": [],
    "Microsoft.Win32": ["OpenFileDialog", "SaveFileDialog"],
    "Autodesk": [],
    "Autodesk.Revit": [],
    "Autodesk.Revit.DB": [
        "BuiltInCategory", "BuiltInParameter", "CategoryType", "Color", "DeleteWorksetOption",
        "DeleteWorksetSettings", "DisplayStyle", "Element", "ElementId", "ElementWorksetFilter",
        "FailureProcessingResult", "FillPatternElement", "FilteredElementCollector",
        "FilteredWorksetCollector", "IFailuresPreprocessor", "ImportInstance",
        "OverrideGraphicSettings", "StorageType", "TemporaryViewMode", "Transaction",
        "TransactionGroup", "View", "View3D", "ViewDetailLevel", "ViewDiscipline",
        "ViewFamilyType", "Workset", "WorksetId", "WorksetKind", "WorksetTable",
        "WorksetVisibility", "WorksharingUtils"],
    "Autodesk.Revit.UI": ["ExternalEvent", "IExternalEventHandler", "TaskDialog",
                          "UIThemeManager"],
}

# System.Uri is deliberately not declared: it moved assemblies at Revit 2025,
# so an import of it has to fail on the bench as it fails in Revit.


class ClrStub(types.ModuleType):
    def __init__(self):
        types.ModuleType.__init__(self, "clr")
        self.references = []

    def AddReference(self, name):
        self.references.append(name)


def install():
    """Fresh stubs every call, so one check cannot leak state into the next."""
    for name in list(sys.modules.keys()):
        if name == "clr" or name.split(".")[0] in ("System", "Microsoft", "Autodesk"):
            del sys.modules[name]
        if name.startswith("wsm_"):
            del sys.modules[name]
    sys.modules["clr"] = ClrStub()
    for name, names in NAMESPACES.items():
        sys.modules[name] = StrictModule(name, names)
    # parents expose children as attributes, the way import machinery expects
    for name in NAMESPACES:
        if "." in name:
            parent, child = name.rsplit(".", 1)
            module = sys.modules[parent]
            module.__declared__.add(child)
            setattr(module, child, sys.modules[name])
    return sys.modules
