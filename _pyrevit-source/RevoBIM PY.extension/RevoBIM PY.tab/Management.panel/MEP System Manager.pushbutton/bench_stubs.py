# -*- coding: utf-8 -*-
"""A stub Revit and .NET API for the bench, run under plain CPython.

Every name is declared in the namespace the real API puts it in, so a
mis-namespaced import fails here with ImportError instead of showing up in
Revit as a blank white pyRevit window. Nothing here is shipped to Revit's
engine - pyRevit never imports it.
"""
import sys
import types

NAMES = {
    u"System": u"Action AppDomain TimeSpan Int64 String",
    u"System.IO": u"StringReader MemoryStream File FileStream FileMode StreamWriter",
    u"System.IO.Compression": u"ZipArchive ZipArchiveMode CompressionLevel",
    u"System.Text": u"UTF8Encoding",
    u"Microsoft": u"",
    u"Microsoft.Win32": u"SaveFileDialog",
    u"System.Xml": u"XmlReader",
    u"System.Data": u"DataTable",
    u"System.Collections.Generic": u"List",
    u"System.Diagnostics": u"Process",
    u"System.Windows": (u"WindowState SystemParameters PresentationSource Visibility Clipboard "
                        u"Thickness HorizontalAlignment VerticalAlignment FontWeights "
                        u"CornerRadius UIElement TextWrapping Window Point TextTrimming "
                        u"GridLength GridUnitType SizeToContent"),
    u"System.Windows.Markup": u"XamlReader",
    u"System.Windows.Documents": u"Run TextElement",
    u"System.Windows.Input": (u"Key MouseButtonState Keyboard ModifierKeys Cursors "
                              u"MouseWheelEventArgs Mouse"),
    u"System.Windows.Interop": u"WindowInteropHelper",
    u"System.Windows.Media": u"SolidColorBrush ColorConverter Geometry Brushes Color",
    u"System.Windows.Media.Imaging": u"BitmapImage BitmapCacheOption",
    u"System.Windows.Controls": (u"Grid ColumnDefinition Expander DataGrid DataGridTextColumn DataGridLength "
                                 u"DataGridLengthUnitType StackPanel DockPanel TextBlock "
                                 u"TextBox Button CheckBox ScrollViewer Border Orientation "
                                 u"Dock ScrollBarVisibility ItemsControl ComboBox Grid"),
    u"System.Windows.Controls.Primitives": u"Popup PlacementMode Thumb",
    u"System.Windows.Data": u"Binding",
    u"System.Windows.Shapes": u"Path",
    u"System.Windows.Threading": u"DispatcherTimer Dispatcher",
    u"System.Windows.Forms": u"Screen",
    u"Autodesk": u"",
    u"Autodesk.Revit": u"",
    u"Autodesk.Revit.DB": (u"FilteredElementCollector BuiltInParameter BuiltInCategory "
                           u"StorageType View3D Element ElementId FamilyInstance Transaction "
                           u"TransactionGroup IFailuresPreprocessor FailureProcessingResult "
                           u"FailureSeverity FailureResolutionType TemporaryViewMode ViewFamilyType ViewFamily "
                           u"BoundingBoxXYZ XYZ WorksharingUtils CheckoutStatus "
                           u"RoutingPreferenceRuleGroupType RoutingConditions RoutingCondition "
                           u"RoutingPreferenceErrorLevel TransactionStatus ElementCategoryFilter "
                           u"InsulationLiningBase MEPCurve FamilySymbol "
                           u"OverrideGraphicSettings Color FillPatternElement "
                           u"FilteredWorksetCollector WorksetKind RevitLinkInstance "
                           u"LinePatternElement ElementTransformUtils Line"),
    u"Autodesk.Revit.DB.Plumbing": u"Pipe PipeType PipingSystem PipingSystemType PlumbingUtils",
    u"Autodesk.Revit.DB.Mechanical": u"Duct DuctType DuctShape DuctSizeSettings MechanicalSystem",
    u"Autodesk.Revit.DB.Electrical": u"CableTray Conduit CableTrayType ConduitType",
    u"Autodesk.Revit.UI.Selection": u"ObjectType ISelectionFilter",
    u"Autodesk.Revit.Exceptions": u"OperationCanceledException",
    u"Autodesk.Revit.UI": (u"PostableCommand RevitCommandId "
                           u"IExternalEventHandler ExternalEvent ExternalEventRequest "
                           u"TaskDialog TaskDialogCommonButtons TaskDialogResult UIThemeManager"),
}

# which assembly msm_clr has to reference before a namespace can be seen
ASSEMBLY_FOR = {
    u"System.Windows": u"PresentationFramework",
    u"System.Windows.Documents": u"PresentationFramework",
    u"System.Windows.Markup": u"PresentationFramework",
    u"System.Windows.Controls": u"PresentationFramework",
    u"System.Windows.Controls.Primitives": u"PresentationFramework",
    u"System.Windows.Data": u"PresentationFramework",
    u"System.Windows.Shapes": u"PresentationFramework",
    u"System.Windows.Interop": u"PresentationFramework",
    u"System.Windows.Input": u"PresentationCore",
    u"System.Windows.Media": u"PresentationCore",
    u"System.Windows.Media.Imaging": u"PresentationCore",
    u"System.Windows.Threading": u"WindowsBase",
    u"System.Xml": u"System.Xml",
    u"System.Data": u"System.Data",
    u"System.Windows.Forms": u"System.Windows.Forms",
    u"System.IO.Compression": u"System.IO.Compression",
    u"Microsoft.Win32": u"PresentationFramework",
}


class _Meta(type):
    def __getattr__(cls, name):
        if name.startswith(u"__"):
            raise AttributeError(name)
        return _Member(u"{0}.{1}".format(cls.__name__, name))

    def __getitem__(cls, item):
        return cls


class Stub(object, metaclass=_Meta):
    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        if name.startswith(u"__"):
            raise AttributeError(name)
        return _Member(name)


class _Member(object):
    def __init__(self, name):
        self._name = name

    def __repr__(self):
        return self._name

    def __str__(self):
        return self._name.split(u".")[-1]

    def __call__(self, *args, **kwargs):
        return _Member(self._name + u"()")

    def __getattr__(self, name):
        if name.startswith(u"__"):
            raise AttributeError(name)
        return _Member(self._name + u"." + name)

    def __int__(self):
        return abs(hash(self._name)) % 100000

    def __iadd__(self, other):
        return self

    def __or__(self, other):
        return self

    def __eq__(self, other):
        return isinstance(other, _Member) and other._name == self._name

    def __hash__(self):
        return hash(self._name)


def build(overrides=None):
    """Put stub clr, System.* and Autodesk.* into sys.modules. overrides:
    {namespace: {Name: object}} replaces a stub with a working fake."""
    overrides = overrides or {}
    remove()
    clr = types.ModuleType(u"clr")
    clr.References = []
    clr.AddReference = lambda name: clr.References.append(name)
    sys.modules[u"clr"] = clr
    for namespace, names in NAMES.items():
        module = types.ModuleType(namespace)
        module.__path__ = []
        for name in names.split():
            setattr(module, name, type(name, (Stub,), {}))
        for name, obj in overrides.get(namespace, {}).items():
            setattr(module, name, obj)
        sys.modules[namespace] = module
    # intermediate namespaces (System.Collections) exist in .NET even when
    # nothing is imported from them directly
    for namespace in sorted(NAMES, key=len):
        parts = namespace.split(u".")
        for depth in range(1, len(parts)):
            partial = u".".join(parts[:depth])
            if partial not in sys.modules:
                holder = types.ModuleType(partial)
                holder.__path__ = []
                sys.modules[partial] = holder
    for namespace in sorted(list(sys.modules), key=len):
        if not (namespace == u"System" or namespace.startswith(u"System.")
                or namespace.startswith(u"Autodesk") or namespace.startswith(u"Microsoft")):
            continue
        if u"." in namespace:
            parent, child = namespace.rsplit(u".", 1)
            setattr(sys.modules[parent], child, sys.modules[namespace])
    return clr


def remove():
    for name in list(sys.modules):
        if name == u"clr" or name == u"System" or name.startswith(u"System.") \
                or name == u"Autodesk" or name.startswith(u"Autodesk.") \
                or name == u"Microsoft" or name.startswith(u"Microsoft."):
            del sys.modules[name]


def forget_tool_modules():
    for name in list(sys.modules):
        if name.startswith(u"msm_"):
            del sys.modules[name]
