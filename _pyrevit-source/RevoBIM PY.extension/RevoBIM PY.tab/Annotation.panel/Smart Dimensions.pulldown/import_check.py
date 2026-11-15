# -*- coding: utf-8 -*-
"""Bench check for the Smart Dimensions modules.

Run this with any CPython outside Revit:

    python import_check.py

It stands up a stub Revit API that declares every name **in the namespace the
real API puts it in**, then imports the shipped modules against it and checks
every ``from ... import ...`` line in the folder resolves. A mis-namespaced
import therefore fails here on the bench rather than showing up in Revit as a
blank white pyRevit window - which is what an exception at module load looks
like, with nothing readable in it.

It proves nothing about the geometry. It proves the modules load.
"""

import ast
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# stub namespaces - membership matters more than behaviour
# ---------------------------------------------------------------------------


class _Enum(object):
    def __init__(self, name, members):
        self._name = name
        for index, member in enumerate(members):
            setattr(self, member, _EnumValue(member, index + 1))

    def __repr__(self):
        return "<enum {0}>".format(self._name)


class _EnumValue(object):
    def __init__(self, name, value):
        self.name = name
        self.value = value

    def __str__(self):
        return self.name

    def __int__(self):
        return self.value

    def __eq__(self, other):
        return isinstance(other, _EnumValue) and other.name == self.name

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(self.name)


class _Stub(object):
    def __init__(self, *args, **kwargs):
        self._args = args

    def __getattr__(self, item):
        return _Stub()

    def __call__(self, *args, **kwargs):
        return _Stub()


def ensure_module(name):
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)
    return sys.modules[name]


def make_module(name, members):
    parts = name.split(".")
    # every prefix has to be importable, and an existing one must not be
    # replaced - "System" may already be carrying "System.IO"
    for index in range(1, len(parts) + 1):
        ensure_module(".".join(parts[:index]))
    for index in range(1, len(parts)):
        parent = sys.modules[".".join(parts[:index])]
        setattr(parent, parts[index], sys.modules[".".join(parts[: index + 1])])
    module = sys.modules[name]
    for key, value in members.items():
        setattr(module, key, value)
    return module


class XYZ(object):
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.X, self.Y, self.Z = float(x), float(y), float(z)

    def __add__(self, other):
        return XYZ(self.X + other.X, self.Y + other.Y, self.Z + other.Z)

    def __sub__(self, other):
        return XYZ(self.X - other.X, self.Y - other.Y, self.Z - other.Z)

    def __mul__(self, factor):
        return XYZ(self.X * factor, self.Y * factor, self.Z * factor)

    def __div__(self, factor):
        return XYZ(self.X / factor, self.Y / factor, self.Z / factor)

    __truediv__ = __div__

    def DotProduct(self, other):
        return self.X * other.X + self.Y * other.Y + self.Z * other.Z

    def CrossProduct(self, other):
        return XYZ(
            self.Y * other.Z - self.Z * other.Y,
            self.Z * other.X - self.X * other.Z,
            self.X * other.Y - self.Y * other.X,
        )

    def GetLength(self):
        return (self.X ** 2 + self.Y ** 2 + self.Z ** 2) ** 0.5

    def Normalize(self):
        length = self.GetLength()
        return XYZ(self.X / length, self.Y / length, self.Z / length)

    def Negate(self):
        return XYZ(-self.X, -self.Y, -self.Z)

    def DistanceTo(self, other):
        return (self - other).GetLength()


XYZ.BasisX = XYZ(1, 0, 0)
XYZ.BasisY = XYZ(0, 1, 0)
XYZ.BasisZ = XYZ(0, 0, 1)


class ElementId(object):
    def __init__(self, value=0):
        try:
            self.Value = int(value)
        except Exception:
            self.Value = int(getattr(value, "value", 0))


class _UnitUtils(object):
    @staticmethod
    def ConvertToInternalUnits(value, unit):
        return value / 304.8

    @staticmethod
    def ConvertFromInternalUnits(value, unit):
        return value * 304.8


class _NameProperty(object):
    """Stands in for the ``Element.Name`` property descriptor."""

    @staticmethod
    def GetValue(element):
        return getattr(element, "_name", "")


DB_NAMES = {
    "BuiltInCategory": _Enum(
        "BuiltInCategory",
        [
            "OST_PipeCurves",
            "OST_DuctCurves",
            "OST_CableTray",
            "OST_Conduit",
            "OST_GenericModel",
            "OST_Walls",
            "OST_Columns",
            "OST_StructuralColumns",
        ],
    ),
    "BuiltInParameter": _Enum(
        "BuiltInParameter", ["RBS_CURVE_DIAMETER_PARAM", "RBS_CURVE_WIDTH_PARAM"]
    ),
    "Dimension": type("Dimension", (object,), {}),
    "DimensionType": type("DimensionType", (object,), {}),
    "DimensionStyleType": _Enum("DimensionStyleType", ["Linear", "LinearFixed", "Angular"]),
    "Element": type("Element", (object,), {"Name": _NameProperty}),
    "ElementId": ElementId,
    "FailureProcessingResult": _Enum("FailureProcessingResult", ["Continue", "ProceedWithCommit"]),
    "FailureSeverity": _Enum("FailureSeverity", ["Warning", "Error"]),
    "FamilyInstance": type("FamilyInstance", (object,), {}),
    "FamilyInstanceReferenceType": _Enum(
        "FamilyInstanceReferenceType",
        [
            "CenterLeftRight",
            "CenterFrontBack",
            "CenterElevation",
            "Left",
            "Right",
            "Front",
            "Back",
            "Top",
            "Bottom",
            "StrongReference",
            "WeakReference",
            "NotAReference",
        ],
    ),
    "FilteredElementCollector": type("FilteredElementCollector", (object,), {}),
    "GeometryInstance": type("GeometryInstance", (object,), {}),
    "IFailuresPreprocessor": type("IFailuresPreprocessor", (object,), {}),
    "Line": type("Line", (object,), {"CreateBound": staticmethod(lambda a, b: _Stub())}),
    "LocationCurve": type("LocationCurve", (object,), {}),
    "LocationPoint": type("LocationPoint", (object,), {}),
    "Options": type("Options", (object,), {}),
    "PlanarFace": type("PlanarFace", (object,), {}),
    "Reference": type(
        "Reference",
        (object,),
        {"ParseFromStableRepresentation": staticmethod(lambda doc, rep: _Stub())},
    ),
    "ReferenceArray": type("ReferenceArray", (object,), {}),
    "RevitLinkInstance": type("RevitLinkInstance", (object,), {}),
    "Solid": type("Solid", (object,), {}),
    "SubTransaction": type("SubTransaction", (object,), {}),
    "Transaction": type("Transaction", (object,), {}),
    "Transform": type("Transform", (object,), {}),
    "UnitTypeId": type("UnitTypeId", (object,), {"Millimeters": _Stub()}),
    "UnitUtils": _UnitUtils,
    "ViewDetailLevel": _Enum("ViewDetailLevel", ["Coarse", "Medium", "Fine"]),
    "ViewType": _Enum(
        "ViewType",
        ["FloorPlan", "CeilingPlan", "EngineeringPlan", "AreaPlan", "Section", "ThreeD"],
    ),
    "XYZ": XYZ,
}

UI_NAMES = {
    "TaskDialog": type("TaskDialog", (object,), {"Show": staticmethod(lambda *a: None)}),
    "RevitCommandId": type(
        "RevitCommandId",
        (object,),
        {"LookupPostableCommandId": staticmethod(lambda cid: _Stub())},
    ),
    "PostableCommand": _Enum("PostableCommand", ["KeyboardShortcuts"]),
    "UIApplication": type("UIApplication", (object,), {}),
    "UIDocument": type("UIDocument", (object,), {}),
}

SELECTION_NAMES = {
    "ISelectionFilter": type("ISelectionFilter", (object,), {}),
    "ObjectType": _Enum("ObjectType", ["Element", "LinkedElement", "Face", "PointOnElement"]),
    "PickBoxStyle": _Enum("PickBoxStyle", ["Crossing", "Enclosing"]),
}

EVENTS_NAMES = {
    "DialogBoxShowingEventArgs": type("DialogBoxShowingEventArgs", (object,), {}),
}

EXCEPTION_NAMES = {
    "OperationCanceledException": type("OperationCanceledException", (Exception,), {}),
    "InvalidOperationException": type("InvalidOperationException", (Exception,), {}),
    "ArgumentException": type("ArgumentException", (Exception,), {}),
}

SYSTEM_NAMES = {"EventHandler": _Stub, "Uri": _Stub}
SYSTEM_IO_NAMES = {"File": _Stub, "MemoryStream": _Stub, "Path": _Stub}
SYSTEM_MEDIA_NAMES = {"BrushConverter": _Stub, "Brushes": _Stub}
SYSTEM_IMAGING_NAMES = {"BitmapImage": _Stub, "BitmapCacheOption": _Stub}
SYSTEM_GENERIC_NAMES = {"List": _Stub}

NAMESPACES = {
    "Autodesk.Revit.DB": DB_NAMES,
    "Autodesk.Revit.UI": UI_NAMES,
    "Autodesk.Revit.UI.Selection": SELECTION_NAMES,
    "Autodesk.Revit.UI.Events": EVENTS_NAMES,
    "Autodesk.Revit.Exceptions": EXCEPTION_NAMES,
    "System": SYSTEM_NAMES,
    "System.IO": SYSTEM_IO_NAMES,
    "System.Windows.Media": SYSTEM_MEDIA_NAMES,
    "System.Windows.Media.Imaging": SYSTEM_IMAGING_NAMES,
    "System.Collections.Generic": SYSTEM_GENERIC_NAMES,
}


def install_stubs():
    clr_module = types.ModuleType("clr")
    clr_module.AddReference = lambda name: None
    sys.modules["clr"] = clr_module

    for name, members in NAMESPACES.items():
        make_module(name, members)

    pyrevit = types.ModuleType("pyrevit")
    pyrevit.HOST_APP = _Stub()
    forms = types.ModuleType("pyrevit.forms")
    forms.WPFWindow = type(
        "WPFWindow", (object,), {"__init__": lambda self, *a, **k: None}
    )
    pyrevit.forms = forms
    sys.modules["pyrevit"] = pyrevit
    sys.modules["pyrevit.forms"] = forms


# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------


def python_files():
    found = []
    for root, _dirs, files in os.walk(HERE):
        for name in files:
            if name.endswith(".py") and name != os.path.basename(__file__):
                found.append(os.path.join(root, name))
    found.sort()
    return found


def check_namespaces(paths):
    """Every ``from <known namespace> import X`` must name something real."""
    problems = []
    for path in paths:
        source = open(path, "r").read()
        try:
            tree = ast.parse(source, path)
        except SyntaxError as err:
            problems.append("{0}: syntax error: {1}".format(os.path.basename(path), err))
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            members = NAMESPACES.get(node.module)
            if members is None:
                continue
            for alias in node.names:
                if alias.name not in members:
                    problems.append(
                        "{0}: '{1}' is not in {2}".format(
                            os.path.basename(path), alias.name, node.module
                        )
                    )
    return problems


BANNED_ATTRS = ("IntegerValue", "iteritems", "itervalues", "iterkeys")

# the one place .IntegerValue is allowed: the guarded fallback helper that
# exists precisely because Revit 2026 removed it
ATTR_EXEMPT_FUNCTIONS = ("eid_value",)


def check_dialect(paths):
    """Nothing that only works on one of the two IronPython engines."""
    problems = []
    for path in paths:
        name = os.path.basename(path)
        source = open(path, "r").read()
        try:
            tree = ast.parse(source, path)
        except SyntaxError:
            continue

        exempt_lines = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in ATTR_EXEMPT_FUNCTIONS:
                for inner in ast.walk(node):
                    if hasattr(inner, "lineno"):
                        exempt_lines.add(inner.lineno)

        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                problems.append("{0}: f-string on line {1}".format(name, node.lineno))
            if isinstance(node, ast.Attribute) and node.attr in BANNED_ATTRS:
                if node.lineno in exempt_lines:
                    continue
                problems.append(
                    "{0}: .{1} on line {2}".format(name, node.attr, node.lineno)
                )
    return problems


def check_imports():
    """Actually load the shipped modules against the stubs."""
    problems = []
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    for module_name in ("smart_dimensions_core", "results_window"):
        try:
            __import__(module_name)
        except Exception as err:
            problems.append("{0}.py failed to load: {1!r}".format(module_name, err))
    return problems


def check_xaml():
    import xml.etree.ElementTree as ET

    problems = []
    for root, _dirs, files in os.walk(HERE):
        for name in files:
            if not name.endswith(".xaml"):
                continue
            try:
                ET.parse(os.path.join(root, name))
            except Exception as err:
                problems.append("{0}: {1}".format(name, err))
    return problems


def main():
    install_stubs()
    paths = python_files()
    problems = []
    problems.extend(check_namespaces(paths))
    problems.extend(check_dialect(paths))
    problems.extend(check_imports())
    problems.extend(check_xaml())

    if problems:
        sys.stderr.write("import_check found {0} problem(s):\n".format(len(problems)))
        for problem in problems:
            sys.stderr.write("  - {0}\n".format(problem))
        return 1
    sys.stdout.write(
        "import_check: {0} python file(s) and every XAML are clean.\n".format(len(paths))
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
