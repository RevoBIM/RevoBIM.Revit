# -*- coding: utf-8 -*-
"""Stub Revit and .NET API for running Tag Aligner under plain CPython.

Every name is declared in the namespace the REAL API puts it in, so an import
from the wrong namespace fails here instead of as a blank pyRevit window.
The DB side is a small working model: tags with heads, leaders, elbows and
pins, view bounding boxes that grow to cover the leader (as Revit's do), and
Transactions / SubTransactions that really roll back.
"""
import math
import sys
import types

# ==========================================================================
# module plumbing
# ==========================================================================

_MODULES = {}


def _mod(name):
    if name in _MODULES:
        return _MODULES[name]
    m = types.ModuleType(name)
    _MODULES[name] = m
    if "." in name:
        parent, child = name.rsplit(".", 1)
        setattr(_mod(parent), child, m)
    return m


def declare(namespace, **names):
    m = _mod(namespace)
    for k, v in names.items():
        setattr(m, k, v)
    return m


class _Anything(object):
    """Placeholder for WPF and .NET classes the bench never exercises."""

    def __init__(self, *a, **k):
        pass

    def __getattr__(self, name):
        return _Anything()

    def __call__(self, *a, **k):
        return _Anything()


def _placeholder(name):
    return type(str(name), (_Anything,), {})


# ==========================================================================
# clr
# ==========================================================================

clr = types.ModuleType("clr")
clr.REFERENCED = []


def _add_reference(name):
    clr.REFERENCED.append(name)


clr.AddReference = _add_reference
_MODULES["clr"] = clr

# ==========================================================================
# System
# ==========================================================================


class _List(list):
    def __class_getitem__(cls, item):
        return cls

    def Add(self, x):
        self.append(x)


class _ListFactory(object):
    def __getitem__(self, item):
        return _List


declare("System")
declare("System.Collections.Generic", List=_ListFactory())
declare("System.IO", File=_placeholder("File"), MemoryStream=_placeholder("MemoryStream"))
declare("System.Diagnostics", Process=_placeholder("Process"))
declare("System.Windows", Thickness=_placeholder("Thickness"),
        Visibility=_placeholder("Visibility"),
        TextWrapping=_placeholder("TextWrapping"))
declare("System.Windows.Controls", TextBlock=_placeholder("TextBlock"))
declare("System.Windows.Interop", WindowInteropHelper=_placeholder("WindowInteropHelper"))
declare("System.Windows.Markup", XamlReader=_placeholder("XamlReader"))
declare("System.Windows.Media", Color=_placeholder("Color"),
        SolidColorBrush=_placeholder("SolidColorBrush"))
declare("System.Windows.Media.Imaging", BitmapImage=_placeholder("BitmapImage"),
        BitmapCacheOption=_placeholder("BitmapCacheOption"))

# ==========================================================================
# Autodesk.Revit.DB  (a small working model)
# ==========================================================================


class XYZ(object):
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.X, self.Y, self.Z = float(x), float(y), float(z)

    def Add(self, o):
        return XYZ(self.X + o.X, self.Y + o.Y, self.Z + o.Z)

    def Subtract(self, o):
        return XYZ(self.X - o.X, self.Y - o.Y, self.Z - o.Z)

    def Multiply(self, k):
        return XYZ(self.X * k, self.Y * k, self.Z * k)

    def DotProduct(self, o):
        return self.X * o.X + self.Y * o.Y + self.Z * o.Z

    def DistanceTo(self, o):
        return math.sqrt((self.X - o.X) ** 2 + (self.Y - o.Y) ** 2 + (self.Z - o.Z) ** 2)

    def Normalize(self):
        n = math.sqrt(self.DotProduct(self)) or 1.0
        return XYZ(self.X / n, self.Y / n, self.Z / n)

    def __add__(self, o):
        return self.Add(o)

    def __repr__(self):
        return "XYZ({0:.4f}, {1:.4f}, {2:.4f})".format(self.X, self.Y, self.Z)


class ElementId(object):
    def __init__(self, v):
        self.Value = int(v)

    def __eq__(self, o):
        return isinstance(o, ElementId) and o.Value == self.Value

    def __hash__(self):
        return hash(self.Value)


class Transform(object):
    Identity = None

    def OfPoint(self, p):
        return p


Transform.Identity = Transform()


class BoundingBoxXYZ(object):
    def __init__(self, mn, mx):
        self.Min, self.Max = mn, mx
        self.Transform = Transform.Identity


class _Enum(object):
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return self.name

    __str__ = __repr__


class TransactionStatus(object):
    Uninitialized = _Enum("Uninitialized")
    Started = _Enum("Started")
    Committed = _Enum("Committed")
    RolledBack = _Enum("RolledBack")


class FailureSeverity(object):
    Warning = _Enum("Warning")
    Error = _Enum("Error")


class FailureProcessingResult(object):
    Continue = _Enum("Continue")


class IFailuresPreprocessor(object):
    pass


class _Options(object):
    def __init__(self):
        self.pre = None

    def SetFailuresPreprocessor(self, p):
        self.pre = p


class Element(object):
    def __init__(self, doc, eid):
        self.Document = doc
        self.Id = ElementId(eid)
        self.Pinned = False
        self._params = {}
        doc._add(self)

    def get_Parameter(self, pid):
        v = self._params.get(pid)
        return None if v is None else _Param(v)

    def GetTypeId(self):
        return getattr(self, "_type_id", ElementId(-1))

    # snapshot support for transactions
    def _state(self):
        return dict((k, _copy(v)) for k, v in self.__dict__.items()
                    if k not in ("Document",))

    def _restore(self, st):
        doc = self.Document
        self.__dict__.clear()
        self.__dict__.update(dict((k, _copy(v)) for k, v in st.items()))
        self.Document = doc


def _copy(v):
    if isinstance(v, XYZ):
        return XYZ(v.X, v.Y, v.Z)
    if isinstance(v, dict):
        return dict((k, _copy(x)) for k, x in v.items())
    if isinstance(v, list):
        return [_copy(x) for x in v]
    return v


class _Param(object):
    def __init__(self, v):
        self.v = v
        self.HasValue = True

    def AsDouble(self):
        return self.v


class BuiltInParameter(object):
    TEXT_SIZE = "TEXT_SIZE"


class Reference(object):
    def __init__(self, eid):
        self.ElementId = ElementId(eid)

    def __eq__(self, o):
        return isinstance(o, Reference) and o.ElementId == self.ElementId

    def __hash__(self):
        return hash(self.ElementId)


class _TagBase(Element):
    """A tag whose text box is offset from its head (as a real family origin
    often is) and whose view box grows to cover the leader end and elbow."""

    def __init__(self, doc, eid, view, head, width, height, leader_end=None,
                 origin_offset=(0.3, -0.1)):
        Element.__init__(self, doc, eid)
        self.OwnerViewId = view.Id
        self._head = XYZ(head.X, head.Y, head.Z)
        self.width = width
        self.height = height
        self.HasLeader = leader_end is not None
        self._leader_end = leader_end
        self._off = origin_offset
        self.move_calls = 0
        self._seen = None
        self._see()

    def _see(self):
        """What the view box reflects: the state at the last Regenerate."""
        self._seen = (XYZ(self._head.X, self._head.Y, self._head.Z),
                      self.HasLeader, _copy(self._leader_points()))

    @property
    def TagHeadPosition(self):
        return XYZ(self._head.X, self._head.Y, self._head.Z)

    @TagHeadPosition.setter
    def TagHeadPosition(self, p):
        if self.Pinned:
            raise RuntimeError("pinned")
        self._head = XYZ(p.X, p.Y, p.Z)

    def _text_box(self, view, head):
        r, u = view.RightDirection, view.UpDirection
        o = head.Add(r.Multiply(self._off[0] * self.width)).Add(
            u.Multiply(self._off[1] * self.height))
        corners = []
        for a in (0.0, self.width):
            for b in (0.0, self.height):
                corners.append(o.Add(r.Multiply(a)).Add(u.Multiply(b)))
        return corners

    def _leader_points(self):
        return []

    def get_BoundingBox(self, view):
        head, leader, leader_pts = self._seen
        pts = self._text_box(view, head)
        if leader:
            pts = pts + leader_pts
        xs = [p.X for p in pts]
        ys = [p.Y for p in pts]
        zs = [p.Z for p in pts]
        return BoundingBoxXYZ(XYZ(min(xs), min(ys), min(zs)), XYZ(max(xs), max(ys), max(zs)))


class IndependentTag(_TagBase):
    """Revit 2022+ shape: one elbow per tagged reference."""

    def __init__(self, *a, **k):
        elbow = k.pop("elbow", None)
        _TagBase.__init__(self, *a, **k)
        self._ref = Reference(9000 + self.Id.Value)
        self._elbows = {}
        if elbow is not None:
            self._elbows[self._ref.ElementId.Value] = elbow
        self._see()

    def _leader_points(self):
        out = [self._leader_end] if self._leader_end else []
        return out + list(getattr(self, "_elbows", {}).values())

    def GetTaggedReferences(self):
        return [self._ref]

    def HasLeaderElbow(self, ref):
        return ref.ElementId.Value in self._elbows

    def GetLeaderElbow(self, ref):
        p = self._elbows[ref.ElementId.Value]
        return XYZ(p.X, p.Y, p.Z)

    def SetLeaderElbow(self, ref, p):
        if self.Pinned:
            raise RuntimeError("pinned")
        self._elbows[ref.ElementId.Value] = XYZ(p.X, p.Y, p.Z)


class SpatialElementTag(_TagBase):
    """Room / space tag shape: a single LeaderElbow property."""

    def __init__(self, *a, **k):
        elbow = k.pop("elbow", None)
        _TagBase.__init__(self, *a, **k)
        self.LeaderElbow = elbow
        self.HasElbow = elbow is not None
        self._see()

    def _leader_points(self):
        out = [self._leader_end] if self._leader_end else []
        if getattr(self, "LeaderElbow", None) is not None:
            out.append(self.LeaderElbow)
        return out


class TextElement(Element):
    pass


class TextElementType(Element):
    pass


class View(Element):
    def __init__(self, doc, eid, right, up, scale, vtype="FloorPlan"):
        Element.__init__(self, doc, eid)
        self.RightDirection = right
        self.UpDirection = up
        self.Scale = scale
        self.ViewType = _Enum(vtype)


class ElementTransformUtils(object):
    @staticmethod
    def MoveElement(doc, eid, v):
        e = doc.GetElement(eid)
        if e.Pinned:
            raise RuntimeError("pinned")
        e._head = e._head.Add(v)
        if getattr(e, "_leader_end", None) is not None:
            e._leader_end = e._leader_end.Add(v)
        e.move_calls += 1


class WorksharingUtils(object):
    @staticmethod
    def CheckoutElements(doc, ids):
        return [i for i in ids if i.Value not in doc.owned_by_others]


class _Collector(object):
    def __init__(self, doc):
        self.doc = doc
        self.items = list(doc._elements.values())

    def WhereElementIsNotElementType(self):
        self.items = [e for e in self.items if not isinstance(e, TextElementType)]
        return self

    def OfClass(self, cls):
        self.items = [e for e in self.items if isinstance(e, cls)]
        return self

    def ToElements(self):
        return list(self.items)


FilteredElementCollector = _Collector


class Document(object):
    def __init__(self, workshared=False):
        self._elements = {}
        self.IsWorkshared = workshared
        self.owned_by_others = set()
        self._regenerated = True
        self._tx_stack = []
        self.families = {}
        self.closed_family_docs = 0
        self.edit_family_inside_tx = 0

    def _add(self, e):
        self._elements[e.Id.Value] = e

    def GetElement(self, x):
        if isinstance(x, Reference):
            x = x.ElementId
        return self._elements.get(x.Value)

    def Regenerate(self):
        self.regen_count = getattr(self, "regen_count", 0) + 1
        for e in self._elements.values():
            if isinstance(e, _TagBase):
                e._see()

    def _snapshot(self):
        return dict((k, e._state()) for k, e in self._elements.items())

    def _restore(self, snap):
        for k, st in snap.items():
            self._elements[k]._restore(st)

    def EditFamily(self, family):
        if self._tx_stack:
            self.edit_family_inside_tx += 1
            raise RuntimeError("EditFamily inside a transaction")
        return self.families[family.Id.Value]

    def Close(self, save):
        pass


class FamilyDoc(Document):
    def __init__(self, owner):
        Document.__init__(self)
        self.owner = owner

    def Close(self, save):
        self.owner.closed_family_docs += 1


class Family(Element):
    IsEditable = True


class FamilySymbol(Element):
    def __init__(self, doc, eid, family, name="Standard"):
        Element.__init__(self, doc, eid)
        self.Family = family
        self.FamilyName = "BGL_Tag_" + str(family.Id.Value)
        self.Name = name


class Transaction(object):
    def __init__(self, doc, name=""):
        self.doc = doc
        self.name = name
        self.options = _Options()
        self.status = TransactionStatus.Uninitialized

    def GetFailureHandlingOptions(self):
        return self.options

    def SetFailureHandlingOptions(self, o):
        self.options = o

    def Start(self):
        self.snap = self.doc._snapshot()
        self.doc._tx_stack.append(self)
        self.status = TransactionStatus.Started
        return self.status

    def Commit(self):
        self.doc._tx_stack.remove(self)
        if getattr(self.doc, "refuse_commit", False):
            self.doc._restore(self.snap)
            self.status = TransactionStatus.RolledBack
            return self.status
        self.status = TransactionStatus.Committed
        return self.status

    def RollBack(self):
        if self in self.doc._tx_stack:
            self.doc._tx_stack.remove(self)
        self.doc._restore(self.snap)
        self.status = TransactionStatus.RolledBack
        return self.status


class SubTransaction(object):
    def __init__(self, doc):
        self.doc = doc

    def Start(self):
        if not self.doc._tx_stack:
            raise RuntimeError("SubTransaction outside a Transaction")
        self.snap = self.doc._snapshot()
        return TransactionStatus.Started

    def RollBack(self):
        self.doc._restore(self.snap)
        return TransactionStatus.RolledBack


declare("Autodesk")
declare("Autodesk.Revit")
declare("Autodesk.Revit.DB",
        XYZ=XYZ, ElementId=ElementId, Transform=Transform,
        BoundingBoxXYZ=BoundingBoxXYZ, Transaction=Transaction,
        SubTransaction=SubTransaction, TransactionStatus=TransactionStatus,
        FailureSeverity=FailureSeverity,
        FailureProcessingResult=FailureProcessingResult,
        IFailuresPreprocessor=IFailuresPreprocessor,
        IndependentTag=IndependentTag, SpatialElementTag=SpatialElementTag,
        TextElement=TextElement, TextElementType=TextElementType,
        BuiltInParameter=BuiltInParameter, ElementTransformUtils=ElementTransformUtils,
        WorksharingUtils=WorksharingUtils,
        FilteredElementCollector=FilteredElementCollector,
        Element=Element, View=View, Reference=Reference,
        Family=Family, FamilySymbol=FamilySymbol)

# ==========================================================================
# Autodesk.Revit.UI / Selection / Exceptions
# ==========================================================================


class OperationCanceledException(Exception):
    pass


class ISelectionFilter(object):
    pass


class ObjectType(object):
    Element = _Enum("Element")


class UITheme(object):
    Dark = _Enum("Dark")
    Light = _Enum("Light")


class UIThemeManager(object):
    CurrentCanvasTheme = UITheme.Dark
    CurrentTheme = UITheme.Dark


class TaskDialog(object):
    shown = []

    @staticmethod
    def Show(title, text):
        TaskDialog.shown.append((title, text))


declare("Autodesk.Revit.UI", TaskDialog=TaskDialog, UIThemeManager=UIThemeManager,
        UITheme=UITheme)
declare("Autodesk.Revit.UI.Selection", ISelectionFilter=ISelectionFilter,
        ObjectType=ObjectType)
declare("Autodesk.Revit.Exceptions",
        OperationCanceledException=OperationCanceledException)


class Selection(object):
    def __init__(self, uidoc):
        self.uidoc = uidoc
        self.ids = []
        self.pick_many = None   # list of elements, or "cancel"
        self.pick_one = None    # element, or "cancel"

    def GetElementIds(self):
        return list(self.ids)

    def SetElementIds(self, ids):
        self.ids = list(ids)

    def PickObjects(self, kind, flt, prompt):
        if self.pick_many == "cancel" or self.pick_many is None:
            raise OperationCanceledException()
        return [Reference(e.Id.Value) for e in self.pick_many if flt.AllowElement(e)]

    def PickObject(self, kind, flt, prompt):
        if self.pick_one == "cancel" or self.pick_one is None:
            raise OperationCanceledException()
        assert flt.AllowElement(self.pick_one)
        return Reference(self.pick_one.Id.Value)


class UIDocument(object):
    def __init__(self, doc, view):
        self.Document = doc
        self.ActiveView = view
        self.Selection = Selection(self)


def install():
    for name, m in _MODULES.items():
        sys.modules[name] = m


def uninstall_tool_modules():
    for name in list(sys.modules):
        if name.startswith("ta_"):
            del sys.modules[name]
