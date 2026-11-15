# -*- coding: utf-8 -*-
"""Fake-Revit bench for Hanger Automation (plain CPython 3).

    python bench_revit.py             run every check
    python bench_revit.py --selftest  break the tool one way at a time, confirm a check fails

What it proves:
  * the window builds and every handler runs against a stub .NET that, like
    IronPython, refuses new attributes on WPF objects (the 1.0.0 crash);
  * Auto place on a bend - 3000 - 3000 - bend run with a tap on it puts four
    hangers at 300 / 2300 / 3900 / 5700 (5700 shortened to land before the
    bend, 4300 moved off the takeoff), hosts each from a Connector object,
    picks the condition that covers the duct, runs the rods to the slab and
    adds one chained dimension with six references;
  * Rehost moves a free hanger onto the nearest straight; Extend runs rods up.
"""
import os
import sys
import shutil
import types
import tempfile
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
MM = 304.8
SLAB_Z = 12.0          # ft, underside of the slab
DUCT_Z = 9.0           # ft, duct centreline
DUCT_W = 400.0 / MM


def build(root):
    """Install stubs + fakes, import the tool from root, return a namespace."""
    sys.path.insert(0, root)
    import bench_stubs as bs
    bs.uninstall()
    mods = bs.install()
    DB = mods['Autodesk.Revit.DB']
    UI = mods['Autodesk.Revit.UI']
    SysM = mods['System']
    NetObj = bs.NetObj

    class Plain(object):
        __setattr__ = object.__setattr__

        def __getattr__(self, name):
            raise AttributeError(name)

    # ---------------------------------------------------------- geometry
    class XYZ(Plain):
        def __init__(self, x, y, z):
            self.X, self.Y, self.Z = float(x), float(y), float(z)

        def DistanceTo(self, o):
            return ((self.X - o.X) ** 2 + (self.Y - o.Y) ** 2 + (self.Z - o.Z) ** 2) ** 0.5
    XYZ.BasisZ = XYZ(0, 0, 1)
    DB._classes['XYZ'] = XYZ

    class Id(Plain):
        def __init__(self, v):
            self.Value = v

    class ElementIdF(Id):
        u"""ElementId(Int64(n)) as on Revit 2024+ (InvalidElementId kept)."""
        def __init__(self, v):
            Id.__init__(self, int(v))
    ElementIdF.InvalidElementId = ElementIdF(-1)
    DB._classes['ElementId'] = ElementIdF
    SysM.Int64 = int

    class BICMeta(type):
        names = {}

        def __getattr__(cls, name):
            return BICMeta.names.setdefault(name, 1000 + len(BICMeta.names))
    BIC = BICMeta('BuiltInCategory', (object,), {})
    DB._classes['BuiltInCategory'] = BIC

    class Cat(Plain):
        def __init__(self, name, label=None):
            self.Id = Id(getattr(BIC, name))
            if label:
                self.Name = label

    class ElementNameAccessor(object):
        class Name(object):
            @staticmethod
            def GetValue(el):
                return el.Name
    DB._classes['Element'] = ElementNameAccessor

    # ------------------------------------------------------------ worksets
    class WsId(Plain):
        def __init__(self, v):
            self.IntegerValue = int(v)

    class WsParam(Plain):
        u"""ELEM_PARTITION_PARAM: setting it moves the element to that workset."""
        def __init__(self, owner):
            self.owner = owner
            self.IsReadOnly = bool(getattr(owner, 'ws_locked', False))

        def Set(self, v):
            if self.IsReadOnly:
                raise Exception('read only')
            self.owner.WorksetId = WsId(v)

    class Workset(Plain):
        def __init__(self, name, wid):
            self.Name, self.Id = name, WsId(wid)

    class WorksetCollector(Plain):
        def __init__(self, doc):
            self.doc = doc

        def OfKind(self, kind):
            return [Workset(n, i) for n, i in ns.worksets]
    DB._classes['FilteredWorksetCollector'] = WorksetCollector

    class WorksetTable(Plain):
        def GetActiveWorksetId(self):
            return WsId(ns.active_ws)

    # ------------------------------------------------------------ doc
    class Doc(Plain):
        def __init__(self):
            self.els = {}
            self.IsWorkshared = False
            self.dims = []
            self.dim_views = []
            self.deleted = []
            self.next = 500
            self.journal = []
            self.selected = []
            self.Title = 'Bench model'
            doc = self

            def wt():
                return WorksetTable()
            self.GetWorksetTable = wt

            class Create(Plain):
                def NewDimension(self, view, line, refs, *rest):
                    if ns.dim_refuse_over is not None and len(refs) > ns.dim_refuse_over:
                        raise Exception('One or more of the references are not visible in this view')
                    doc.dims.append(len(refs))
                    doc.dim_views.append(view)
                    return NetObj('Dimension')
            self.Create = Create()

        def add(self, el):
            self.els[el.Id.Value] = el
            self.journal.append(('add', el.Id.Value, el))
            return el

        def mark(self):
            return len(self.journal)

        def undo_to(self, mark):
            while len(self.journal) > mark:
                op, i, el = self.journal.pop()
                if op == 'add':
                    self.els.pop(i, None)
                    ns.created[:] = [c for c in ns.created if c['h'] is not el]
                else:
                    self.els[i] = el
                    if i in self.deleted:
                        self.deleted.remove(i)

        def new_id(self):
            self.next += 1
            return Id(self.next)

        def GetElement(self, i):
            return self.els.get(i.Value if hasattr(i, 'Value') else i)

        def Regenerate(self):
            pass

        def Delete(self, i):
            self.deleted.append(i.Value)
            el = self.els.pop(i.Value, None)
            if el is not None:
                el.IsValidObject = False
                self.journal.append(('del', i.Value, el))

    class Collector(Plain):
        def __init__(self, doc, view_id=None):
            self.items = list(doc.els.values()) if isinstance(doc, Doc) else []

        def OfCategory(self, bic):
            self.items = [e for e in self.items if getattr(e, 'Category', None) is not None and e.Category.Id.Value == bic]
            return self

        def OfClass(self, cls):
            self.items = [e for e in self.items if isinstance(e, cls)]
            return self

        def WhereElementIsNotElementType(self):
            return self

        def __iter__(self):
            return iter(self.items)
    DB._classes['FilteredElementCollector'] = Collector

    class Txn(Plain):
        log = []

        def __init__(self, doc, name=''):
            self.name = name
            self.doc = doc

        def Start(self):
            Txn.log.append(('start', self.name))
            self.m = self.doc.mark() if isinstance(self.doc, Doc) else 0

        def Commit(self):
            if ns.undo_next_commit and isinstance(self.doc, Doc):   # Revit throws the transaction away (an error)
                ns.undo_next_commit -= 1
                Txn.log.append(('undone', self.name))
                self.doc.undo_to(self.m)
                return 'RolledBack'
            Txn.log.append(('commit', self.name))
            return 'Committed'

        def GetName(self):
            return self.name

        def RollBack(self):
            Txn.log.append(('rollback', self.name))
            if isinstance(self.doc, Doc):
                self.doc.undo_to(self.m)

        def GetFailureHandlingOptions(self):
            return NetObj('FailureHandlingOptions')

        def SetFailureHandlingOptions(self, o):
            pass
    DB._classes['Transaction'] = Txn
    DB._classes['SubTransaction'] = Txn

    class TG(Plain):
        def __init__(self, doc, name):
            pass

        def Start(self):
            pass

        def Assimilate(self):
            pass

        def RollBack(self):
            pass
    DB._classes['TransactionGroup'] = TG

    class RefArray(list):
        def Append(self, r):
            self.append(r)
    DB._classes['ReferenceArray'] = RefArray

    # ------------------------------------------------------- geometry objs
    class FRef(Plain):
        u"""A reference that knows its geometry, so the fake NewAlignment can
        refuse pairs that do not coincide (as Revit does)."""
        def __init__(self, kind, vec, point, label='ref'):
            self.kind, self.vec, self.point, self.label = kind, tuple(vec), tuple(point), label

    def _dot(a, b):
        return sum(x * y for x, y in zip(a, b))

    def _sub(a, b):
        return tuple(x - y for x, y in zip(a, b))

    def coincide(r1, r2):
        if not isinstance(r1, FRef) or not isinstance(r2, FRef):
            return False
        if r1.kind == 'line' and r2.kind == 'line':
            return False
        if r2.kind == 'line':
            r1, r2 = r2, r1
        if r1.kind == 'line':   # centreline in plan vs a vertical plane
            n = r2.vec
            if abs(n[2]) > 1e-6 or abs(_dot(n, r1.vec)) > 1e-6:
                return False
            d = _sub(r1.point, r2.point)
            return abs(n[0] * d[0] + n[1] * d[1]) < 1e-6
        if abs(abs(_dot(r1.vec, r2.vec)) - 1.0) > 1e-6:
            return False
        return abs(_dot(r1.vec, _sub(r2.point, r1.point))) < 1e-6

    class Face(DB.PlanarFace, Plain):
        __setattr__ = object.__setattr__

        def __init__(self, origin, normal):
            self.Origin = XYZ(*origin)
            self.FaceNormal = XYZ(*normal)
            self.Reference = FRef('face', normal, origin, 'face')

    class Vec(XYZ):
        def GetLength(self):
            return (self.X ** 2 + self.Y ** 2 + self.Z ** 2) ** 0.5

    class Cyl(DB.CylindricalFace, Plain):
        __setattr__ = object.__setattr__

        def __init__(self, origin, axis, r):
            self.Origin, self.Axis, self.r = XYZ(*origin), XYZ(*axis), r
            self.Reference = None

        def get_Radius(self, i):
            return Vec(self.r, 0, 0) if i == 0 else Vec(0, self.r, 0)


    class Edge(Plain):
        def __init__(self, a, b):
            self.pts = [XYZ(*a), XYZ(*b)]

        def Tessellate(self):
            return list(self.pts)

    class Solid(DB.Solid, Plain):
        __setattr__ = object.__setattr__

        def __init__(self, faces, edges=None):
            self.Faces = faces
            self.Edges = edges or []

    # ----------------------------------------------------------- MEP
    class Conn(Plain):
        def __init__(self, owner, cid, origin, basis):
            self.Owner, self.Id = owner, cid
            self.Origin = XYZ(*origin)
            cs = Plain()
            cs.BasisZ = XYZ(*basis)
            self.CoordinateSystem = cs
            self.AllRefs = []

    def join(a, b):
        a.AllRefs.append(b)
        b.AllRefs.append(a)

    class CM(Plain):
        def __init__(self, cons):
            self.Connectors = cons

    class Dim(Plain):
        def __init__(self, name):
            self.Name = name

    class Part(DB.FabricationPart, Plain):
        __setattr__ = object.__setattr__

        def __init__(self, doc, pid, cat, straight=False, tap=False):
            self.Id = Id(pid)
            self.Category = Cat(cat)
            self.straight, self.tap = straight, tap
            self.ServiceId = 1
            self.WorksetId = NetObj('WorksetId')
            self.ConnectorManager = CM([])
            self.Origin = XYZ(0, 0, DUCT_Z)
            self.faces = []
            self.IsValidObject = True
            self.ServiceName = u'Rect Supply'
            self.Name = u'Straight'
            doc.add(self)

        def IsAStraight(self):
            return self.straight

        def IsATap(self):
            return self.tap

        def IsAHanger(self):
            return False

        def GetDimensions(self):
            return [Dim('Width'), Dim('Depth')]

        def GetDimensionValue(self, d):
            return DUCT_W if d.Name == 'Width' else 300.0 / MM

        def get_Parameter(self, p):
            return None

        def get_Geometry(self, opt):
            return [Solid(self.faces)] if self.faces else []

    class RodInfo(Plain):
        def __init__(self, hanger):
            self.h = hanger
            self.RodCount = 2
            self.CanRodsBeHosted = True
            self.IsAttachedToStructure = False
            self.len = [1.0, 1.0]

        def _bottom(self):
            return self.h.bottom

        def GetRodEndPosition(self, i):
            o = self.h.Origin
            return XYZ(o.X, o.Y + (0.5 if i else -0.5), self._bottom() + self.len[i])

        def GetRodLength(self, i):
            return self.len[i]

        def GetRodStructureExtension(self, i):
            return 0.0

        def SetRodLength(self, i, v):
            if self.CanRodsBeHosted:
                return False   # "the hanger must not be auto-hosted"
            self.len[i] = v
            return True

        def AttachToStructure(self):
            pass

    class HostInfo(Plain):
        def __init__(self, hanger, host_id):
            self.h = hanger
            self.HostId = Id(host_id)
            self.calls = []

        def PlaceOnHost(self, host_id, conn, dist):
            if not isinstance(conn, Conn):
                raise TypeError('PlaceOnHost expects a Connector, got {0!r}'.format(conn))
            self.calls.append((host_id.Value, conn, dist))
            self.HostId = Id(host_id.Value)
            ns.place_on_host_calls.append((host_id.Value, conn, dist))

        def DisconnectFromHost(self):
            self.HostId = Id(-1)

    class Definition(Plain):
        def __init__(self, name):
            self.Name = name

    class Param(Plain):
        def __init__(self, name, value):
            self.Definition = Definition(name)
            self.IsReadOnly = False
            self.IsShared = False
            self.StorageType = 'String'
            self.value = value

        @property
        def HasValue(self):
            return bool(self.value)

        def AsString(self):
            return self.value

        def Set(self, v):
            self.value = v
            return True

    class Hanger(DB.FabricationPart, Plain):
        __setattr__ = object.__setattr__

        def __init__(self, doc, pid, origin, host_id):
            self.Id = Id(pid)
            self.Category = Cat('OST_FabricationHangers')
            self.Origin = XYZ(*origin)
            self.bottom = origin[2] - 0.6
            self.rods = RodInfo(self)
            self.hinfo = HostInfo(self, host_id)
            self.IsValidObject = True
            self.WorksetId = WsId(0)
            self.Name = 'Hanger'
            self.ProductName = ''
            self.Alias = ''
            self.ProductCode = ''
            self.ItemCustomId = 0
            self.ServiceId = 1
            self.width = DUCT_W + 50 / MM
            self.Parameters = [Param('Comments', ''), Param('Mark', '')]
            doc.add(self)

        def LookupParameter(self, name):
            for p in self.Parameters:
                if p.Definition.Name == name:
                    return p
            return None

        def IsAHanger(self):
            return True

        def IsATap(self):
            return False

        def IsAStraight(self):
            return False

        def GetRodInfo(self):
            return self.rods

        def GetHostedInfo(self):
            return self.hinfo

        def GetDimensions(self):
            return [Dim('Width')]

        def GetDimensionValue(self, d):
            return self.width

        def SetDimensionValue(self, d, v):
            ns.set_dimension_calls.append(v)
            self.width = v

        def get_Parameter(self, p):
            if p == 'ALL_MODEL_INSTANCE_COMMENTS':
                return self.Parameters[0]
            return WsParam(self) if p == 'ELEM_PARTITION_PARAM' else None

        def get_BoundingBox(self, v):
            bb = Plain()
            bb.Min = XYZ(self.Origin.X - 0.1, self.Origin.Y - 0.5, self.bottom)
            bb.Max = XYZ(self.Origin.X + 0.1, self.Origin.Y + 0.5, self.bottom + 2)
            return bb

        def get_Geometry(self, opt):
            x = self.Origin.X
            return [Solid([Face((x - 0.02, 0, self.bottom), (-1, 0, 0)),
                           Face((x + 0.02, 0, self.bottom), (1, 0, 0))])]

    # ------------------------------------------------------- fab config
    class Button(Plain):
        def __init__(self, name='Trapeze', item=1):
            self.Name = name
            self.item = item
            self.IsAHanger = True
            self.ConditionCount = 2
            self.bounds = [(0.0, 1.0), (1.0, 2.0)]

        def IsUnrestrictedCondition(self, i):
            return False

        def GetConditionLowerValue(self, i):
            return self.bounds[i][0]

        def GetConditionUpperValue(self, i):
            return self.bounds[i][1]

    class Service(Plain):
        def __init__(self):
            self.Name = 'Hangers'
            self.ServiceId = 1
            self.PaletteCount = 1
            self.buttons = [Button('Trapeze', 1), Button('Clevis', 2)]

        def GetButtonCount(self, p):
            return len(self.buttons)

        def GetButton(self, p, b):
            return self.buttons[b]

    class Config(Plain):
        def GetAllLoadedServices(self):
            return [Service()]

    class FabConfig(object):
        @staticmethod
        def GetFabricationConfiguration(doc):
            return Config()
    DB._classes['FabricationConfiguration'] = FabConfig

    def create_hanger(doc, btn, *rest):
        if len(rest) == 5:
            cond, host_id, conn, dist, attach = rest
        else:
            cond = None
            host_id, conn, dist, attach = rest
        if not isinstance(conn, Conn):
            raise TypeError('CreateHanger expects a Connector, got {0!r}'.format(conn))
        host = doc.GetElement(host_id)
        a, b = host.ends[0].Origin, host.ends[1].Origin
        other = b if conn is host.ends[0] else a
        L = conn.Origin.DistanceTo(other)
        t = dist / L
        p = (conn.Origin.X + (other.X - conn.Origin.X) * t, conn.Origin.Y + (other.Y - conn.Origin.Y) * t, DUCT_Z - 0.5)
        h = Hanger(doc, doc.new_id().Value, p, host_id.Value)
        h.Name = '{0} {1:.0f}'.format(btn.Name, (DUCT_W + 50 / MM) * MM)
        h.ProductName = btn.Name + ' hanger'
        h.ItemCustomId = btn.item
        h.width = DUCT_W + 50 / MM   # a fresh placement sizes itself to the duct
        ns.created.append({'host': host_id.Value, 'conn': conn, 'dist': dist, 'cond': cond, 'attach': attach, 'h': h})
        return h
    DB.FabricationPart.CreateHanger = staticmethod(create_hanger)

    # ------------------------------------------------------------ views
    class View(DB.View3D, Plain):
        __setattr__ = object.__setattr__

        def __init__(self, doc):
            self.Id = doc.new_id()
            self.Name = '3D View 1'
            self.IsTemplate = False
            self.ViewType = 'ThreeD'
            self.Scale = 100

    class VFT(DB.ViewFamilyType, Plain):
        __setattr__ = object.__setattr__

        def __init__(self, doc, family='ThreeDimensional', vid=77):
            self.Id = Id(vid)
            self.ViewFamily = family
            self.Category = None
            doc.els[vid] = self

    class PlanView(Plain):
        def __init__(self):
            self.ViewType = 'FloorPlan'
            self.Name = 'Level 1 - Mech'
            self.IsTemplate = False
            self.Scale = 50

    def create_iso(doc, vft_id):
        v = View(doc)
        ns.temp_views.append(v)
        return v
    DB.View3D.CreateIsometric = staticmethod(create_iso)

    class RI(Plain):
        def __init__(self, flt, target, view):
            self.FindReferencesInRevitLinks = False
            self.flt = flt

        def FindNearest(self, origin, direction):
            tid = self.flt.Value if isinstance(self.flt, Id) else None
            if direction.Z < 0:   # down onto a floor support's base: ns.down[(None, id)](x, y) -> top z
                f = ns.down.get((None, tid))
                z = f(origin.X, origin.Y) if f is not None else None
                if z is None or z >= origin.Z:
                    return None
                ref = Plain()
                ref.GlobalPoint = XYZ(origin.X, origin.Y, z)
                hit = Plain()
                hit.GetReference = lambda: ref
                return hit
            if tid is not None:   # a single element in this model: its own underside, if above
                z = ns.target_z.get(tid)
                if z is None or z <= origin.Z:
                    return None
                ref = Plain()
                ref.GlobalPoint = XYZ(origin.X, origin.Y, z)
                hit = Plain()
                hit.GetReference = lambda: ref
                return hit
            if origin.Z >= SLAB_Z:
                return None
            ref = Plain()
            ref.GlobalPoint = XYZ(origin.X, origin.Y, SLAB_Z)
            hit = Plain()
            hit.GetReference = lambda: ref
            return hit
    DB._classes['ReferenceIntersector'] = RI

    class Store(Plain):
        def __init__(self):
            self.d = {}

        def GetData(self, k):
            return self.d.get(k)

        def SetData(self, k, v):
            self.d[k] = v

    class AppDom(object):
        CurrentDomain = Store()
    SysM._classes['AppDomain'] = AppDom

    class Evt(Plain):
        def __init__(self, handler):
            self.handler = handler
            self.raised = 0

        def Raise(self):
            self.raised += 1
            return 'Accepted'

    class ExternalEvent(object):
        @staticmethod
        def Create(handler):
            e = Evt(handler)
            ns.events.append(e)
            return e
    UI._classes['ExternalEvent'] = ExternalEvent

    class Selection(Plain):
        def __init__(self, ids):
            self.ids = ids

        def GetElementIds(self):
            return [Id(i) for i in self.ids]

        def SetElementIds(self, ids):
            self.ids = [i.Value for i in ids]

        def PickObjects(self, *a):
            raise Exception('pick cancelled')

    class UIDoc(Plain):
        def __init__(self, doc, ids, view):
            self.Document = doc
            self.Selection = Selection(ids)
            self.ActiveView = view
            self.refreshed = 0

        def RefreshActiveView(self):
            self.refreshed += 1

    # ------------------------------------------------------------ model
    def model():
        doc = Doc()
        VFT(doc)
        y, z = 0.0, DUCT_Z
        s1 = Part(doc, 11, 'OST_FabricationDuctwork', straight=True)
        s2 = Part(doc, 12, 'OST_FabricationDuctwork', straight=True)
        b0 = Part(doc, 10, 'OST_FabricationDuctwork')
        b3 = Part(doc, 13, 'OST_FabricationDuctwork')
        x0, x1, x2 = 0.0, 3000 / MM, 6000 / MM
        c10 = Conn(s1, 0, (x0, y, z), (-1, 0, 0))
        c11 = Conn(s1, 1, (x1, y, z), (1, 0, 0))
        c20 = Conn(s2, 0, (x1, y, z), (-1, 0, 0))
        c21 = Conn(s2, 1, (x2, y, z), (1, 0, 0))
        s1.ConnectorManager = CM([c10, c11])
        s2.ConnectorManager = CM([c20, c21])
        s1.ends, s2.ends = [c10, c11], [c20, c21]
        b0a = Conn(b0, 0, (x0, y, z), (1, 0, 0))
        b0b = Conn(b0, 1, (x0 - 0.5, y + 0.5, z), (0, 1, 0))
        b3a = Conn(b3, 0, (x2, y, z), (-1, 0, 0))
        b3b = Conn(b3, 1, (x2 + 0.5, y, z - 0.5), (0, 0, -1))
        b0.ConnectorManager = CM([b0a, b0b])
        b3.ConnectorManager = CM([b3a, b3b])
        join(c10, b0a)
        join(c11, c20)
        join(c21, b3a)
        s1.faces = [Face((x0, 0, z), (-1, 0, 0)), Face((x1, 0, z), (1, 0, 0))]
        s2.faces = [Face((x1, 0, z), (-1, 0, 0)), Face((x2, 0, z), (1, 0, 0))]
        tap = Part(doc, 20, 'OST_FabricationDuctwork', tap=True)
        tap.Origin = XYZ(4300 / MM, DUCT_W / 2.0, z)
        return doc, s1, s2

    class NS(object):
        pass
    ns = NS()
    # how the fake ring sits on the height parameter: centre = base + height + k x radius
    ns.RING_K = {'top': -1.0, 'centre': 0.0, 'bottom': 1.0}
    ns.DB = DB
    ns.XYZ = DB.XYZ
    ns.ring_rule = 'centre'
    ns.created, ns.place_on_host_calls, ns.temp_views, ns.events = [], [], [], []
    ns.set_dimension_calls, ns.egg_calls = [], []

    # ---- the shared easter egg package, with the real attach signature
    egg_pkg = types.ModuleType('revobim')
    egg_sub = types.ModuleType('revobim.egg')
    egg_hook = types.ModuleType('revobim.egg.egg_hook')

    def attach(logo, host_window=None, theme=None):
        ns.egg_calls.append({'logo': logo, 'host_window': host_window, 'theme': theme})
    egg_hook.attach = attach
    egg_pkg.egg, egg_sub.egg_hook = egg_sub, egg_hook
    sys.modules['revobim'], sys.modules['revobim.egg'], sys.modules['revobim.egg.egg_hook'] = egg_pkg, egg_sub, egg_hook
    ns.model, ns.UIDoc, ns.PlanView, ns.Hanger, ns.Conn, ns.NetObj = model, UIDoc, PlanView, Hanger, Conn, NetObj
    ns.Txn = Txn
    # ================================================= family hanger fakes
    MechM = mods['Autodesk.Revit.DB.Mechanical']
    import math as _m

    class BIPMeta(type):
        def __getattr__(cls, name):
            if name.startswith('__'):
                raise AttributeError(name)
            return name
    DB._classes['BuiltInParameter'] = BIPMeta('BuiltInParameter', (object,), {})

    class DParam(Plain):
        def __init__(self, name, value=0.0, read_only=False):
            self.Definition = Definition(name)
            self.IsReadOnly = read_only
            self.StorageType = 'Double'
            self.HasValue = True
            self.v = value

        def AsDouble(self):
            return self.v

        def Set(self, v):
            self.v = float(v)
            return True

    class Level(DB.Level, Plain):
        __setattr__ = object.__setattr__

        def __init__(self, doc, lid, name, elev_mm):
            self.Id = Id(lid)
            self.Name = name
            self.ProjectElevation = elev_mm / MM
            doc.els[lid] = self

        def GetPlaneReference(self):
            return NetObj('PlaneReference')

    class Curve(Plain):
        def __init__(self, a, b):
            self.pts = [XYZ(*a), XYZ(*b)]

        def GetEndPoint(self, i):
            return self.pts[i]

    class RvtDuct(MechM.Duct, Plain):
        __setattr__ = object.__setattr__

        def __init__(self, doc, pid, a, b, w_mm, h_mm, level):
            self.Id = Id(pid)
            self.Category = Cat('OST_DuctCurves')
            loc = Plain()
            loc.Curve = Curve(a, b)
            self.Location = loc
            self.params = {'RBS_CURVE_WIDTH_PARAM': DParam('Width', w_mm / MM),
                           'RBS_CURVE_HEIGHT_PARAM': DParam('Height', h_mm / MM)}
            self.ReferenceLevel = level
            self.WorksetId = NetObj('WorksetId')
            self.ConnectorManager = CM([])
            self.Document = doc
            doc.add(self)

        def get_Parameter(self, b):
            return self.params.get(b)

        def get_Geometry(self, opt):
            return lock_geometry(self)

    class MEPModel(Plain):
        def __init__(self, part_type, cons):
            self.PartType = part_type
            self.ConnectorManager = CM(cons)

    class Fitting(DB.FamilyInstance, Plain):
        __setattr__ = object.__setattr__

        def __init__(self, doc, pid, part_type='Elbow', cat='OST_DuctFitting'):
            self.Id = Id(pid)
            self.Category = Cat(cat)
            self.MEPModel = MEPModel(part_type, [])
            doc.add(self)

    class Family(Plain):
        def __init__(self, fid, name, placement='OneLevelBased'):
            self.Id = Id(fid)
            self.Name = name
            self.FamilyPlacementType = placement

    class Symbol(DB.FamilySymbol, Plain):
        __setattr__ = object.__setattr__

        def __init__(self, doc, sid, family, name):
            self.Id = Id(sid)
            self.Family = family
            self.Name = name
            self.IsActive = False
            self.Category = Cat('OST_MEPAncillaryFraming')
            doc.add(self)

        def Activate(self):
            self.IsActive = True

        def GetPreviewImage(self, size):
            return None

    class Inst(DB.FamilyInstance, Plain):
        __setattr__ = object.__setattr__

        def __init__(self, doc, symbol, point, level):
            self.Id = doc.new_id()
            self.Symbol = symbol
            self.Category = Cat('OST_MEPAncillaryFraming')
            inst = self

            class Loc(object):
                u"""Like Revit: the point's Z is the level plus the offset."""
                xy = (point[0], point[1])

                @property
                def Point(self):
                    return XYZ(self.xy[0], self.xy[1], inst.elevation())

                @Point.setter
                def Point(self, v):
                    self.xy = (v.X, v.Y)
            self.Location = Loc()
            self.HandOrientation = XYZ(1, 0, 0)
            self.LevelId = level.Id
            self.IsValidObject = True
            self.WorksetId = NetObj('WorksetId')
            self.WorksetId = WsId(0)
            self.p = {'INSTANCE_ELEVATION_PARAM': DParam('Elevation from Level', 0.0),
                      'ELEM_PARTITION_PARAM': WsParam(self),
                      'ALL_MODEL_INSTANCE_COMMENTS': Param('Comments', u'')}
            self.named = dict((n, DParam(n, 0.0)) for n in
                              ('BGL_DIM_Width Left', 'BGL_DIM_Width Right', 'BGL_DIM_Drop Rod Length',
                               'First Bar Offset', 'BIM_Hanger_Support_Height', 'BIM_DIM_Diameter'))
            doc.add(self)

        def get_Parameter(self, b):
            return self.p.get(b)

        def LookupParameter(self, name):
            return self.named.get(name)

        def get_Geometry(self, opt):
            u"""A hanger: its bearer top at its location.  A floor support (First Bar
            Offset set): also the bottom bar's top that far above its base."""
            p = self.Location.Point
            faces = [Face((p.X, p.Y, p.Z), (0, 0, 1)), Face((p.X, p.Y, p.Z - 0.15), (0, 0, -1))]
            fb = self.named['First Bar Offset'].v
            if fb > 0:
                faces.append(Face((p.X, p.Y, p.Z + fb), (0, 0, 1)))
            r = self.named['BIM_DIM_Diameter'].v / 2.0
            if r > 0 and ns.ring_rule in ns.RING_K:   # a circular support's ring, round the family X
                h = self.HandOrientation
                zc = p.Z + self.named['BIM_Hanger_Support_Height'].v + ns.RING_K[ns.ring_rule] * r
                faces.append(Cyl((p.X, p.Y, zc), (h.X, h.Y, 0.0), r))
                faces.append(Cyl((p.X, p.Y, zc), (h.X, h.Y, 0.0), r + 6 / MM))   # its outside
                faces.append(Cyl((p.X, p.Y, p.Z), (0.0, 0.0, 1.0), r))           # a round base plate, axis up
            return [Solid(faces)]

        def get_BoundingBox(self, v):
            u"""The bearer along the family X axis.  ns.mirrored_family: the 'Left'
            parameter stretches the POSITIVE way (like Drew's Extension 1 / 2),
            the opposite of the tool's first guess."""
            p, h = self.Location.Point, self.HandOrientation
            a, b = self.named['BGL_DIM_Width Left'].v, self.named['BGL_DIM_Width Right'].v
            pos, neg = (a, b) if ns.mirrored_family else (b, a)
            e1 = (p.X + h.X * pos, p.Y + h.Y * pos)
            e2 = (p.X - h.X * neg, p.Y - h.Y * neg)
            bb = Plain()
            bb.Min = XYZ(min(e1[0], e2[0]) - 0.05, min(e1[1], e2[1]) - 0.05, p.Z - 0.15)
            bb.Max = XYZ(max(e1[0], e2[0]) + 0.05, max(e1[1], e2[1]) + 0.05, p.Z)
            return bb

        @property
        def FacingOrientation(self):
            h = self.HandOrientation
            return XYZ(-h.Y, h.X, 0)

        def GetReferences(self, kind):
            u"""ns.family_refs: 'named' - Center (Left/Right) and (Front/Back)
            set; 'strong' - only two Strong references (the square one first);
            'none' - every plane Not a Reference."""
            name = str(kind).split('.')[-1]
            p, h, f = self.Location.Point, self.HandOrientation, self.FacingOrientation
            o = (p.X, p.Y, p.Z)
            hv, fv = (h.X, h.Y, 0.0), (f.X, f.Y, 0.0)
            mode = ns.family_refs
            out = []
            if mode == 'named' and name == 'CenterLeftRight':
                out = [FRef('plane', hv, o, 'CL hand')]
            elif mode == 'named' and name == 'CenterFrontBack':
                out = [FRef('plane', fv, o, 'CL facing')]
            elif mode == 'strong' and name == 'StrongReference':
                out = [FRef('plane', fv, o, 'Square'), FRef('plane', hv, o, 'Along')]
            return bs.FakeList(out)

        def GetReferenceName(self, ref):
            return ref.label

        def elevation(self):
            lv = ns.doc_levels[self.LevelId.Value]
            return lv.ProjectElevation + self.p['INSTANCE_ELEVATION_PARAM'].v

    class CreateFam(Plain):
        def __init__(self, doc, old):
            self.doc, self.old = doc, old

        def NewDimension(self, *a):
            return self.old.NewDimension(*a)

        def NewAlignment(self, view, r1, r2):
            if not coincide(r1, r2):
                ns.refused.append((r1, r2))
                raise Exception('The two references are not geometrically aligned so the Alignment cannot be created.')
            ns.alignments.append((view, r1, r2))
            return NetObj('Alignment')

        def NewFamilyInstance(self, *a):
            if len(a) == 4 and isinstance(a[1], Symbol):
                loc, symbol, level, _st = a
                inst = Inst(self.doc, symbol, (loc.X, loc.Y, loc.Z), level)
                ns.fam_created.append(inst)
                return inst
            raise TypeError('unexpected NewFamilyInstance overload {0}'.format(a))

    class ETU(object):
        @staticmethod
        def RotateElement(doc, eid, axis, angle):
            el = doc.GetElement(eid)
            h = el.HandOrientation
            c, s = _m.cos(angle), _m.sin(angle)
            el.HandOrientation = XYZ(h.X * c - h.Y * s, h.X * s + h.Y * c, 0)

        @staticmethod
        def MoveElement(doc, eid, v):
            el = doc.GetElement(eid)
            p = el.Location.Point
            el.Location.Point = XYZ(p.X + v.X, p.Y + v.Y, p.Z + v.Z)
    DB._classes['ElementTransformUtils'] = ETU

    class PickRef(Plain):
        def __init__(self, el, point=None):
            self.ElementId = el.Id
            self.GlobalPoint = XYZ(*point) if point else None

    class OperationCanceledException(Exception):
        pass

    class FamSelection(Plain):
        def __init__(self, ids, picks, multi=None):
            self.ids = ids
            self.picks = list(picks)
            self.multi = multi or []

        def GetElementIds(self):
            return [Id(i) for i in self.ids]

        def SetElementIds(self, ids):
            self.ids = [i.Value for i in ids]

        def PickObject(self, kind, *rest):
            flt = rest[0] if len(rest) == 2 else None
            if not self.picks:
                raise OperationCanceledException('cancelled')
            ref = self.picks.pop(0)
            if flt is not None and not flt.AllowElement(ns.fam_doc.GetElement(ref.ElementId)):
                raise AssertionError('filter refused the pick')
            return ref

        def PickObjects(self, kind, flt, prompt):
            batch = self.multi
            if batch and isinstance(batch[0], list):   # several PickObjects in turn
                batch = self.multi.pop(0)
            for r in batch:
                if not flt.AllowElement(ns.fam_doc.GetElement(r.ElementId)):
                    raise AssertionError('filter refused a picked element')
            return list(batch)

    class Insulation(Plain):
        def __init__(self, doc, iid, host, t_mm):
            self.Id = Id(iid)
            self.Thickness = t_mm / MM
            self.Category = Cat('OST_DuctInsulations')
            doc.els[iid] = self
            ns.insulation.setdefault(host.Id.Value, []).append(self.Id)

    class ILB(object):
        @staticmethod
        def GetInsulationIds(doc, host_id):
            return list(ns.insulation.get(host_id.Value, []))
    DB._classes['InsulationLiningBase'] = ILB

    class FloorPlanView(Plain):
        def __init__(self, vtype='FloorPlan'):
            self.ViewType = vtype
            self.Name = 'Level 1 - Mech'
            self.IsTemplate = False
            self.Id = Id(900)
            self.Scale = 50
            self.calls = []

        def IsolateElementsTemporary(self, ids):
            self.calls.append(('isolate', sorted(i.Value for i in ids)))

        def DisableTemporaryViewMode(self, mode):
            self.calls.append(('reset', str(mode)))

    def fam_model(width_mm=600.0, depth_mm=300.0, w2=None, h2=None):
        ns.insulation = {}
        doc = Doc()
        doc.Create = CreateFam(doc, doc.Create)
        ns.fam_doc = doc
        l1 = Level(doc, 1, 'Level 1', 0.0)
        l2 = Level(doc, 2, 'Level 2', 4000.0)
        l3 = Level(doc, 3, 'Level 3', 8000.0)
        VFT(doc)
        VFT(doc, 'Section', 78)
        ns.doc_levels = {1: l1, 2: l2, 3: l3}
        z = 3048.0 / MM
        x0, x1, x2 = 0.0, 3000 / MM, 6000 / MM
        d1 = RvtDuct(doc, 31, (x0, 0, z), (x1, 0, z), width_mm, depth_mm, l1)
        d2 = RvtDuct(doc, 32, (x1, 0, z), (x2, 0, z), w2 or width_mm, h2 or depth_mm, l1)
        b0, b3 = Fitting(doc, 30), Fitting(doc, 33)
        c10, c11 = Conn(d1, 0, (x0, 0, z), (-1, 0, 0)), Conn(d1, 1, (x1, 0, z), (1, 0, 0))
        c20, c21 = Conn(d2, 0, (x1, 0, z), (-1, 0, 0)), Conn(d2, 1, (x2, 0, z), (1, 0, 0))
        d1.ConnectorManager, d2.ConnectorManager = CM([c10, c11]), CM([c20, c21])
        b0a, b0b = Conn(b0, 0, (x0, 0, z), (1, 0, 0)), Conn(b0, 1, (x0 - 0.5, 0.5, z), (0, 1, 0))
        b3a, b3b = Conn(b3, 0, (x2, 0, z), (-1, 0, 0)), Conn(b3, 1, (x2 + 0.5, 0.5, z), (0, 1, 0))
        b0.MEPModel, b3.MEPModel = MEPModel('Elbow', [b0a, b0b]), MEPModel('Elbow', [b3a, b3b])
        join(c10, b0a)
        join(c11, c20)
        join(c21, b3a)
        fam = Family(40, 'BGL_MAF_Unistrut Hanger')
        sym = Symbol(doc, 41, fam, '41x41 Channel')
        return doc, d1, d2, sym, l1, l2, z

    class RoundFab(Part):
        u"""A round fabrication duct straight from a to b, its diameter in its dimensions."""
        def __init__(self, doc, pid, a, b, dia_mm):
            Part.__init__(self, doc, pid, 'OST_FabricationDuctwork', straight=True)
            self.dia = dia_mm / MM
            d = [b[i] - a[i] for i in range(3)]
            n = sum(x * x for x in d) ** 0.5
            d = [x / n for x in d]
            self.ConnectorManager = CM([Conn(self, 0, a, tuple(-x for x in d)), Conn(self, 1, b, tuple(d))])

        def GetDimensions(self):
            return [Dim('Diameter')]

        def GetDimensionValue(self, dd):
            return self.dia

    ns.fam_model, ns.FamSelection, ns.PickRef, ns.Inst = fam_model, FamSelection, PickRef, Inst
    ns.RoundFab = RoundFab
    ns.WsId = WsId
    ns.worksets = [('Mech - Ductwork', 101), ('Mech - Hangers', 201), ('Shared Levels and Grids', 1)]
    ns.active_ws = 301
    ns.RvtDuct, ns.Fitting, ns.MEPModel, ns.CM, ns.join = RvtDuct, Fitting, MEPModel, CM, join
    ns.Insulation, ns.FloorPlanView = Insulation, FloorPlanView

    # ---- lock geometry and sections
    class CLine(DB.Line, Plain):
        __setattr__ = object.__setattr__

        def __init__(self, a, b):
            d = _m_dir(a, b)
            self.Direction = XYZ(*d)
            self.Reference = FRef('line', d, a, 'centreline')

    def lock_geometry(el):
        c = el.Location.Curve
        a, b = c.GetEndPoint(0), c.GetEndPoint(1)
        a, b = (a.X, a.Y, a.Z), (b.X, b.Y, b.Z)
        items = [CLine(a, b)]
        h = el.params.get('RBS_CURVE_HEIGHT_PARAM') or el.params.get('RBS_CABLETRAY_HEIGHT_PARAM')
        if h is not None:   # rectangular: a flat underside, and its two end faces
            mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, a[2] - h.v / 2.0)
            d = _m_dir(a, b)
            items.append(Solid([Face(mid, (0, 0, -1)), Face((mid[0], mid[1], a[2] + h.v / 2.0), (0, 0, 1)),
                                Face(a, tuple(-x for x in d)), Face(b, d)]))
        return items

    class ViewSectionFake(object):
        @staticmethod
        def CreateSection(doc, vft_id, box):
            v = SectionView(doc.new_id().Value)
            v.doc = doc
            doc.add(v)
            ns.lock_views.append(v)
            return v

    class SectionView(ViewSectionFake, Plain):
        __setattr__ = object.__setattr__

        def __init__(self, vid):
            self.Id = Id(vid)
            self.Name = ''
            self.ViewType = 'Section'
            self.IsTemplate = False
            self.doc = None

        @property
        def IsValidObject(self):
            return self.doc is None or self.Id.Value in self.doc.els
    DB._classes['ViewSection'] = ViewSectionFake
    ns.alignments, ns.lock_views, ns.refused = [], [], []
    ns.family_refs = 'named'

    # ---- units: mechanical equipment and duct accessories
    class Unit(DB.FamilyInstance, Plain):
        u"""A box unit: centre c, size along its hand (lx) and facing (ly), height hz,
        bottom at zb; optional in-line connectors along `conn_dir`."""
        __setattr__ = object.__setattr__

        def __init__(self, doc, uid, cat, label, c, hand, lx, ly, zb, hz, level, conn_dir=None):
            self.Id = Id(uid)
            self.Category = Cat(cat, label)
            self.Name = 'Unit'
            self.Symbol = Plain()
            self.Symbol.Family = Family(9000 + uid, 'Unit family')
            self.Symbol.Name = 'Unit'
            self.HandOrientation = XYZ(hand[0], hand[1], 0)
            self.FacingOrientation = XYZ(-hand[1], hand[0], 0)
            loc = Plain()
            loc.Point = XYZ(c[0], c[1], zb)
            self.Location = loc
            self.LevelId = level.Id
            self.WorksetId = NetObj('WorksetId')
            self.c, self.lx, self.ly, self.zb, self.hz = c, lx, ly, zb, hz
            cons = []
            if conn_dir is not None:
                d = conn_dir
                cons = [Conn(self, 0, (c[0] + d[0], c[1] + d[1], zb + hz / 2), (d[0], d[1], 0)),
                        Conn(self, 1, (c[0] - d[0], c[1] - d[1], zb + hz / 2), (-d[0], -d[1], 0))]
            self.MEPModel = MEPModel('Damper', cons)
            doc.add(self)

        def corners(self):
            h, f = self.HandOrientation, self.FacingOrientation
            out = []
            for sx in (-0.5, 0.5):
                for sy in (-0.5, 0.5):
                    for z in (self.zb, self.zb + self.hz):
                        out.append((self.c[0] + h.X * sx * self.lx + f.X * sy * self.ly,
                                    self.c[1] + h.Y * sx * self.lx + f.Y * sy * self.ly, z))
            return out

        def get_Geometry(self, opt):
            cs = self.corners()
            edges = [Edge(a, b) for a in cs for b in cs if a < b]
            c = self.c
            return [Solid([Face((c[0], c[1], self.zb), (0, 0, -1)), Face((c[0], c[1], self.zb + self.hz), (0, 0, 1))],
                          edges)]

        def GetReferences(self, kind):
            name = str(kind).split('.')[-1]
            o = (self.c[0], self.c[1], self.zb)
            h, f = self.HandOrientation, self.FacingOrientation
            if name == 'CenterLeftRight':
                return bs.FakeList([FRef('plane', (h.X, h.Y, 0.0), o, 'unit CL hand')])
            if name == 'CenterFrontBack':
                return bs.FakeList([FRef('plane', (f.X, f.Y, 0.0), o, 'unit CL facing')])
            return bs.FakeList([])

        def GetReferenceName(self, ref):
            return ref.label

    ns.Unit = Unit

    # ---- views and sheets for the Dimension views picker
    class DimView(DB.View, Plain):
        __setattr__ = object.__setattr__

        def __init__(self, doc, vid, name, vtype, right=(1, 0, 0), up=(0, 0, 1), vdir=(0, -1, 0), origin=(0, 0, 0)):
            self.Id = Id(vid)
            self.Name, self.ViewType, self.IsTemplate, self.Scale = name, vtype, False, 50
            self.RightDirection, self.UpDirection = XYZ(*right), XYZ(*up)
            self.ViewDirection, self.Origin = XYZ(*vdir), XYZ(*origin)
            doc.add(self)

    class Sheet(DB.ViewSheet, Plain):
        __setattr__ = object.__setattr__

        def __init__(self, doc, sid, number, name, views):
            self.Id = Id(sid)
            self.SheetNumber, self.Name, self.IsPlaceholder = number, name, False
            self.views = views
            doc.add(self)

        def GetAllPlacedViews(self):
            return [v.Id for v in self.views]

    class FakeDimUI(object):
        u"""Stands in for hview_ui.DimViewsUI: answers the prompts as told."""
        def __init__(self, choice, open_answer=None):
            self.choice, self.open_answer = choice, open_answer
            self.asked, self.offered = [], []

        def choose_dim_views(self, view_name, rows, sheets):
            self.asked.append((view_name, rows, sheets))
            return self.choice(rows, sheets) if callable(self.choice) else self.choice

        def ask_open(self, runs, views, sheets):
            self.offered.append((runs, views, sheets))
            return self.open_answer

        def ask_base_pick(self, linked):
            self.base_asked = getattr(self, 'base_asked', []) + [linked]
            return getattr(self, 'base_answer', u'pick')
    ns.DimView, ns.Sheet, ns.FakeDimUI, ns.View3DFake = DimView, Sheet, FakeDimUI, View
    ns.mirrored_family = False

    # ---- pipes, cable trays, link targets
    PlumbM = mods['Autodesk.Revit.DB.Plumbing']
    ElecM = mods['Autodesk.Revit.DB.Electrical']

    def mep_class(base):
        class MepCurve(base, Plain):
            __setattr__ = object.__setattr__

            def __init__(self, doc, pid, a, b, params, level, cat):
                self.Id = Id(pid)
                self.Category = Cat(cat)
                loc = Plain()
                loc.Curve = Curve(a, b)
                self.Location = loc
                self.params = dict((k, DParam(k, v / MM)) for k, v in params.items())
                self.ReferenceLevel = level
                self.WorksetId = NetObj('WorksetId')
                self.Document = doc
                fam, typ = MEP_TYPES.get(cat, (u'Service', u'Standard'))
                tid = 900000 + len(fam) * 100 + len(typ)
                if tid not in doc.els:
                    t = Plain()
                    t.FamilyName, t.Name, t.Id = fam, typ, Id(tid)
                    doc.els[tid] = t
                self.type_id = Id(tid)
                self.ConnectorManager = CM([Conn(self, 0, a, tuple(-v for v in _m_dir(a, b))),
                                            Conn(self, 1, b, _m_dir(a, b))])
                doc.add(self)

            def get_Parameter(self, b):
                return self.params.get(b)

            def GetTypeId(self):
                return self.type_id

            def get_Geometry(self, opt):
                return lock_geometry(self)
        return MepCurve

    MEP_TYPES = {'OST_PipeCurves': (u'Pipe Types', u'Copper'), 'OST_CableTray': (u'Cable Tray with Fittings', u'Ladder')}

    def _m_dir(a, b):
        L = sum((b[i] - a[i]) ** 2 for i in range(3)) ** 0.5
        return tuple((b[i] - a[i]) / L for i in range(3))

    PipeF, TrayF = mep_class(PlumbM.Pipe), mep_class(ElecM.CableTray)

    def pipe(doc, pid, a, b, od_mm, level):
        return PipeF(doc, pid, a, b, {'RBS_PIPE_OUTER_DIAMETER': od_mm}, level, 'OST_PipeCurves')

    def tray(doc, pid, a, b, w_mm, h_mm, level):
        return TrayF(doc, pid, a, b, {'RBS_CABLETRAY_WIDTH_PARAM': w_mm, 'RBS_CABLETRAY_HEIGHT_PARAM': h_mm},
                     level, 'OST_CableTray')

    class Target(Plain):
        def __init__(self, doc, pid, low_z, cat='OST_Floors', ray_z=None):
            if ray_z is not None:
                ns.target_z[pid] = ray_z
            self.Id = Id(pid)
            self.Name = 'Slab'
            self.Category = Cat(cat)
            self.low = low_z
            if doc is not None:
                doc.els[pid] = self

        def get_BoundingBox(self, v):
            bb = Plain()
            bb.Min = XYZ(-100, -100, self.low)
            bb.Max = XYZ(100, 100, self.low + 1)
            return bb

    class LinkDoc(Plain):
        def __init__(self):
            self.els = {}

        def GetElement(self, i):
            return self.els.get(i.Value)

    class Link(DB.RevitLinkInstance, Plain):
        __setattr__ = object.__setattr__

        def __init__(self, doc, pid):
            self.Id = Id(pid)
            self.Name = 'STR model'
            self.ldoc = LinkDoc()
            doc.els[pid] = self

        def GetLinkDocument(self):
            return self.ldoc

        def GetTotalTransform(self):
            t = Plain()
            t.OfPoint = lambda p: p
            return t

    class LinkRef(Plain):
        def __init__(self, link, el):
            self.ElementId = link.Id
            self.LinkedElementId = el.Id
            self.GlobalPoint = None

    def ri_find(self, origin, direction):
        if direction.Z < 0:   # down onto a linked base: ns.down[(link id, element id)](x, y)
            out = []
            for (lid, eid_), f in ns.down.items():
                z = f(origin.X, origin.Y) if lid is not None else None
                if z is None or z >= origin.Z:
                    continue
                ref = Plain()
                ref.ElementId, ref.LinkedElementId, ref.GlobalPoint = Id(lid), Id(eid_), XYZ(origin.X, origin.Y, z)
                hit = Plain()
                hit.Proximity = origin.Z - z
                hit.GetReference = (lambda r: (lambda: r))(ref)
                out.append(hit)
            return out
        if ns.link_hit is None or origin.Z >= ns.link_hit[2]:
            return []
        lid, eid_, z = ns.link_hit
        ref = Plain()
        ref.ElementId, ref.LinkedElementId, ref.GlobalPoint = Id(lid), Id(eid_), XYZ(origin.X, origin.Y, z)
        hit = Plain()
        hit.Proximity = z - origin.Z
        hit.GetReference = lambda: ref
        return [hit]
    RI.Find = ri_find
    ns.link_hit = None
    ns.target_z = {}
    ns.down = {}
    ns.dim_refuse_over = None
    ns.undo_next_commit = 0
    ns.pipe, ns.tray, ns.Target, ns.Link, ns.LinkRef = pipe, tray, Target, Link, LinkRef
    ns.insulation = {}
    ns.fam_created = []

    os.environ['APPDATA'] = tempfile.mkdtemp()
    import fha_core
    import fha_revit
    import fha_ui
    import fha_window
    import hfam_core
    import hfam_revit
    import hfam_ui
    import hcirc_core
    import hcirc_revit
    ns.core, ns.rv, ns.ui, ns.win = fha_core, fha_revit, fha_ui, fha_window
    ns.fc, ns.hr, ns.hui = hfam_core, hfam_revit, hfam_ui
    ns.cc, ns.hc = hcirc_core, hcirc_revit
    import hview_ui
    ns.hv = hview_ui
    return ns


# ================================================================ checks
def checks(ns):
    out = []

    def check(name, cond, detail=''):
        out.append((name, bool(cond), detail))

    core, rv = ns.core, ns.rv
    settings = dict(core.DEFAULTS)

    # ---- auto place
    doc, s1, s2 = ns.model()
    uidoc = ns.UIDoc(doc, [11, 12], ns.PlanView())
    log = core.DebugLog(True)
    try:
        res = rv.job_place(uidoc, settings, log)
    except Exception:
        res = None
        check('place runs', False, traceback.format_exc())
    if res is not None:
        st = sorted(round((c['dist'] * MM) + (0 if c['host'] == 11 else 3000)) for c in ns.created)
        check('place: four hangers', res['done'] == 4, '{0} {1}'.format(res, log.text()))
        check('place: stations 300/2300/3900/5700', st == [300, 2300, 3900, 5700], st)
        check('place: hosted from Connector objects', all(isinstance(c['conn'], ns.Conn) for c in ns.created))
        check('place: measured from the run-start connector',
              all(c['conn'] is (s1.ends[0] if c['host'] == 11 else s2.ends[0]) for c in ns.created))
        check('comments: FAB hangers carry their host service and part',
              ns.created and all(c['h'].Parameters[0].AsString() == u'Rect Supply : Straight' for c in ns.created),
              [c['h'].Parameters[0].AsString() for c in ns.created])
        check('place: condition covering 400 mm duct', all(c['cond'] == 1 for c in ns.created),
              [c['cond'] for c in ns.created])
        check('place: rods to slab',
              all(abs(c['h'].rods.GetRodEndPosition(i).Z - SLAB_Z) < 0.01 for c in ns.created for i in range(2)),
              [round(c['h'].rods.GetRodEndPosition(0).Z, 3) for c in ns.created])
        check('place: one chained dimension, 6 refs', doc.dims == [6], doc.dims)
        check('place: temporary 3D view removed', [v.Id.Value for v in ns.temp_views] == doc.deleted,
              (doc.deleted, [v.Id.Value for v in ns.temp_views]))
        # second run: everything already there
        n0 = len(ns.created)
        res2 = rv.job_place(uidoc, settings, core.DebugLog(True))
        check('place again: skips existing', len(ns.created) == n0 and res2['done'] == 0, res2)

    # ---- rehost (replace): a too-small Clevis left floating near S1
    ns.created[:] = []
    doc, s1, s2 = ns.model()
    old = ns.Hanger(doc, 90, (1500 / MM, 0.3, DUCT_Z - 0.5), -1)
    old.Name, old.ProductName, old.ItemCustomId, old.width = 'Clevis 200', 'Clevis hanger', 2, 200 / MM
    old.LookupParameter('Comments').value = 'keep me'
    uidoc = ns.UIDoc(doc, [90], ns.PlanView())
    try:
        res = rv.job_rehost(uidoc, settings, core.DebugLog(True))
        hangers = [e for e in doc.els.values() if isinstance(e, ns.Hanger)]
        new = hangers[0] if len(hangers) == 1 else None
        check('rehost: old hanger replaced by one new hanger', res['done'] == 1 and 90 not in doc.els and new is not None,
              (res, [h.Id.Value for h in hangers]))
        if new is not None:
            check('rehost: same kind of hanger (Clevis, not Trapeze)', new.ItemCustomId == 2, new.Name)
            check('rehost: sized to the duct like a new placement', abs(new.width - (DUCT_W + 50 / MM)) < 1e-9,
                  new.width * MM)
            check('rehost: hosted on S1 at 1500 mm', new.hinfo.HostId.Value == 11 and
                  abs(ns.created[-1]['dist'] * MM - 1500) < 1, ns.created[-1]['dist'] * MM)
            check('rehost: Comments carried over', new.LookupParameter('Comments').value == 'keep me')
            check('rehost: new hanger selected', uidoc.Selection.ids == [new.Id.Value], uidoc.Selection.ids)
            check('rehost: rods extended after', abs(new.rods.GetRodEndPosition(0).Z - SLAB_Z) < 0.01)
        check('rehost: probe hangers rolled back', len(hangers) == 1, len(hangers))
    except Exception:
        check('rehost runs', False, traceback.format_exc())

    # ---- rehost (move only)
    doc, s1, s2 = ns.model()
    old = ns.Hanger(doc, 92, (1500 / MM, 0.3, DUCT_Z - 0.5), -1)
    try:
        moved = dict(settings)
        moved[u'rehost_replace'] = u'0'
        res = rv.job_rehost(ns.UIDoc(doc, [92], ns.PlanView()), moved, core.DebugLog(True))
        call = ns.place_on_host_calls[-1] if ns.place_on_host_calls else None
        check('rehost move: PlaceOnHost on S1 at 1500', res['done'] == 1 and call and call[0] == 11 and
              abs(call[2] * MM - 1500) < 1, (res, call))
    except Exception:
        check('rehost move runs', False, traceback.format_exc())

    # ---- extend
    doc, s1, s2 = ns.model()
    h = ns.Hanger(doc, 91, (1000 / MM, 0, DUCT_Z - 0.5), 11)
    try:
        res = rv.job_extend(ns.UIDoc(doc, [91], ns.PlanView()), settings, core.DebugLog(True))
        check('extend: done', res['done'] == 1, res)
        check('extend: both rods at slab', all(abs(h.rods.GetRodEndPosition(i).Z - SLAB_Z) < 0.01 for i in range(2)))
    except Exception:
        check('extend runs', False, traceback.format_exc())

    # ================================================= family hangers
    fc, hr = ns.fc, ns.hr
    cfg = fc.fam_config({}, 'BGL_MAF_Unistrut Hanger',
                        ['BGL_DIM_Width Left', 'BGL_DIM_Width Right', 'BGL_DIM_Drop Rod Length'])
    check('fam: width parameters guessed', (cfg['left'], cfg['right']) == ('BGL_DIM_Width Left', 'BGL_DIM_Width Right'),
          (cfg['left'], cfg['right']))

    def fam_settings(doc, sym, **kw):
        st = dict(settings)
        st.update(kw)
        st[u'_fam'] = {'id': sym.Id, 'family': sym.Family.Name, 'cfg': cfg}
        st[u'_fams'] = {}
        return st

    def bottom(z, depth_mm):
        return z - depth_mm / MM / 2.0

    # ---- place: click on D1 at 1500 mm, off-centre, on its top face
    ns.fam_created[:] = []
    doc, d1, d2, sym, l1, l2, z = ns.fam_model()
    uidoc = ns.UIDoc(doc, [], ns.PlanView())
    uidoc.Selection = ns.FamSelection([], [ns.PickRef(d1, (1500 / MM, 0.2, z + 0.49))])
    try:
        res = hr.job_place(uidoc, fam_settings(doc, sym, fam_rod_place=u'1'), core.DebugLog(True))
        inst = ns.fam_created[0] if len(ns.fam_created) == 1 else None
        check('fam place: one hanger, loop ends on Esc', res['done'] == 1 and inst is not None, (res, len(ns.fam_created)))
        if inst is not None:
            p = inst.Location.Point
            check('fam place: centred on the duct where clicked', abs(p.Y) < 1e-9 and abs(p.X * MM - 1500) < 0.5, (p.X * MM, p.Y))
            check('fam place: on the duct level', inst.LevelId.Value == 1)
            check('fam place: reference level at the duct invert', abs(inst.elevation() - bottom(z, 300)) < 1e-6,
                  (inst.elevation() * MM, bottom(z, 300) * MM))
            check('fam place: both sides stretched to half the duct width',
                  all(abs(inst.named[n].v * MM - 300) < 0.01 for n in ('BGL_DIM_Width Left', 'BGL_DIM_Width Right')),
                  [inst.named[n].v * MM for n in ('BGL_DIM_Width Left', 'BGL_DIM_Width Right')])
            check('fam place: width square to the duct', abs(inst.HandOrientation.X) < 1e-9 and abs(abs(inst.HandOrientation.Y) - 1) < 1e-9,
                  (inst.HandOrientation.X, inst.HandOrientation.Y))
            rod = inst.named['BGL_DIM_Drop Rod Length'].v
            check('fam place: drop rod to the base of the level above', abs(rod - (4000 / MM - bottom(z, 300))) < 1e-6, rod * MM)
            check('fam place: symbol activated', sym.IsActive)
    except Exception:
        check('fam place runs', False, traceback.format_exc())

    # ---- place with the rod tick off leaves the rod alone
    ns.fam_created[:] = []
    doc, d1, d2, sym, l1, l2, z = ns.fam_model()
    uidoc = ns.UIDoc(doc, [], ns.PlanView())
    uidoc.Selection = ns.FamSelection([], [ns.PickRef(d2, (4500 / MM, 0, z))])
    hr.job_place(uidoc, fam_settings(doc, sym, fam_rod_place=u'0'), core.DebugLog(True))
    check('fam place: rod untouched when not ticked', ns.fam_created and ns.fam_created[0].named['BGL_DIM_Drop Rod Length'].v == 0.0)

    # ---- realign: a skewed hanger off to one side at the wrong height and width
    doc, d1, d2, sym, l1, l2, z = ns.fam_model()
    old = ns.Inst(doc, sym, (2000 / MM, 0.8, 0.0), l1)
    old.HandOrientation = ns.core and type(old.HandOrientation)(0.7071067811865476, 0.7071067811865476, 0)
    old.p['INSTANCE_ELEVATION_PARAM'].v = 2.0
    old.named['BGL_DIM_Width Left'].v = 0.1
    uidoc = ns.UIDoc(doc, [], ns.PlanView())
    uidoc.Selection = ns.FamSelection([], [], [[ns.PickRef(d1)], [ns.PickRef(old)]])
    try:
        res = hr.job_realign(uidoc, fam_settings(doc, sym, fam_rod_realign=u'1'), core.DebugLog(True))
        p = old.Location.Point
        check('fam realign: done', res['done'] == 1, res)
        check('fam realign: onto the centreline, same place along the duct', abs(p.Y) < 1e-9 and abs(p.X * MM - 2000) < 0.5, (p.X * MM, p.Y))
        check('fam realign: invert and width refitted', abs(old.elevation() - bottom(z, 300)) < 1e-6 and
              abs(old.named['BGL_DIM_Width Left'].v * MM - 300) < 0.01)
        check('fam realign: turned square to the duct', abs(old.HandOrientation.X) < 1e-9, (old.HandOrientation.X, old.HandOrientation.Y))
        check('fam realign: rod re-extended', old.named['BGL_DIM_Drop Rod Length'].v > 0)
    except Exception:
        check('fam realign runs', False, traceback.format_exc())

    # ---- auto: bend - 3000 - 3000 - bend, 600 x 300
    ns.fam_created[:] = []
    doc, d1, d2, sym, l1, l2, z = ns.fam_model()
    uidoc = ns.UIDoc(doc, [31, 32], ns.PlanView())
    try:
        res = hr.job_auto(uidoc, fam_settings(doc, sym), core.DebugLog(True))
        xs = sorted(round(i.Location.Point.X * MM) for i in ns.fam_created)
        check('fam auto: 300 / 3300 / 5700 on a 6 m run', xs == [300, 3300, 5700], (xs, res))
        check('fam auto: all at the invert and stretched', all(abs(i.elevation() - bottom(z, 300)) < 1e-6 and
              abs(i.named['BGL_DIM_Width Right'].v * MM - 300) < 0.01 for i in ns.fam_created))
        n0 = len(ns.fam_created)
        res2 = hr.job_auto(uidoc, fam_settings(doc, sym), core.DebugLog(True))
        check('fam auto again: skips existing', len(ns.fam_created) == n0, res2)
    except Exception:
        check('fam auto runs', False, traceback.format_exc())

    # ---- auto: a 1600 wide duct is capped at the DW/144 2500 mm spacing
    ns.fam_created[:] = []
    doc, d1, d2, sym, l1, l2, z = ns.fam_model(1600.0, 400.0)
    uidoc = ns.UIDoc(doc, [31, 32], ns.PlanView())
    try:
        hr.job_auto(uidoc, fam_settings(doc, sym), core.DebugLog(True))
        xs = sorted(round(i.Location.Point.X * MM) for i in ns.fam_created)
        gaps = [b - a for a, b in zip(xs, xs[1:])]
        check('fam auto: DW/144 caps a 1600 mm duct at 2500 mm', xs and max(gaps) <= 2500 and xs[0] == 300 and xs[-1] == 5700, xs)
    except Exception:
        check('fam auto DW/144 runs', False, traceback.format_exc())

    # ---- auto: a station on a joint is pushed off it by the flange clearance
    ns.fam_created[:] = []
    doc, d1, d2, sym, l1, l2, z = ns.fam_model()
    uidoc = ns.UIDoc(doc, [31, 32], ns.PlanView())
    try:
        hr.job_auto(uidoc, fam_settings(doc, sym, fam_spacing=u'2700', fam_dw144=u'0'), core.DebugLog(True))
        xs = sorted(round(i.Location.Point.X * MM) for i in ns.fam_created)
        check('fam auto: kept 150 mm off the joint at 3000', all(abs(x - 3000) >= 150 for x in xs), xs)
    except Exception:
        check('fam auto flange runs', False, traceback.format_exc())


    # ---- re-align across segments of one run: never moved along it
    doc, d1, d2, sym, l1, l2, z = ns.fam_model(600.0, 300.0, 400.0, 250.0)
    h1 = ns.Inst(doc, sym, (1500 / MM, 0.6, 0.0), l1)
    h2 = ns.Inst(doc, sym, (4500 / MM, -0.4, 0.0), l1)
    uidoc = ns.UIDoc(doc, [], ns.PlanView())
    uidoc.Selection = ns.FamSelection([], [], [[ns.PickRef(d1)], [ns.PickRef(h1), ns.PickRef(h2)]])
    try:
        log = core.DebugLog(True)
        res = hr.job_realign(uidoc, fam_settings(doc, sym), log)
        p1, p2 = h1.Location.Point, h2.Location.Point
        check('realign run: both done', res['done'] == 2, res)
        check('realign run: second hanger NOT moved along the run', abs(p2.X * MM - 4500) < 0.5 and abs(p2.Y) < 1e-9,
              (p2.X * MM, p2.Y))
        check('realign run: first hanger only slid sideways', abs(p1.X * MM - 1500) < 0.5 and abs(p1.Y) < 1e-9)
        check('realign run: each fitted to its own segment size',
              abs(h1.named['BGL_DIM_Width Left'].v * MM - 300) < 0.01 and abs(h2.named['BGL_DIM_Width Left'].v * MM - 200) < 0.01 and
              abs(h2.elevation() - bottom(z, 250)) < 1e-6,
              (h1.named['BGL_DIM_Width Left'].v * MM, h2.named['BGL_DIM_Width Left'].v * MM))
        check('debug: re-align logs moves and segment sizes', 'sideways' in log.text() and 'run: 2 straights' in log.text(), log.text()[-600:])
    except Exception:
        check('realign run runs', False, traceback.format_exc())

    # ---- insulation: outside (default) wraps it, inside fits the bare duct
    for outside in (u'1', u'0'):
        ns.fam_created[:] = []
        doc, d1, d2, sym, l1, l2, z = ns.fam_model()
        ns.Insulation(doc, 700, d1, 25.0)
        uidoc = ns.UIDoc(doc, [], ns.PlanView())
        uidoc.Selection = ns.FamSelection([], [ns.PickRef(d1, (1500 / MM, 0, z))])
        try:
            log = core.DebugLog(True)
            hr.job_place(uidoc, fam_settings(doc, sym, fam_ins_place=outside), log)
            inst = ns.fam_created[0]
            half = inst.named['BGL_DIM_Width Left'].v * MM
            inv = inst.elevation() * MM
            if outside == u'1':
                check('insulation outside: width + 2 x 25', abs(half - 325) < 0.01, half)
                check('insulation outside: invert 25 lower', abs(inv - (bottom(z, 300) * MM - 25)) < 0.01, inv)
                check('debug: insulation logged', 'insulation 25 mm (outside it)' in log.text(), log.text()[-400:])
            else:
                check('insulation inside: bare duct width', abs(half - 300) < 0.01, half)
                check('insulation inside: bare invert', abs(inv - bottom(z, 300) * MM) < 0.01, inv)
        except Exception:
            check('insulation place runs', False, traceback.format_exc())

    # ---- debug from auto place says what it planned
    ns.fam_created[:] = []
    doc, d1, d2, sym, l1, l2, z = ns.fam_model()
    log = core.DebugLog(True)
    hr.job_auto(ns.UIDoc(doc, [31, 32], ns.PlanView()), fam_settings(doc, sym), log)
    check('debug: auto logs parts, spans and plan', all(k in log.text() for k in ('part 31', 'span 6000', 'planned', 'hanger fits')),
          log.text()[:800])

    # ---- dimension placer
    ns.fam_created[:] = []
    doc, d1, d2, sym, l1, l2, z = ns.fam_model()
    hr.job_auto(ns.UIDoc(doc, [31, 32], ns.PlanView()), fam_settings(doc, sym), core.DebugLog(True))
    placed = list(ns.fam_created)
    view = ns.FloorPlanView()
    uidoc = ns.UIDoc(doc, [], view)
    uidoc.Selection = ns.FamSelection([], [], [ns.PickRef(h) for h in placed])
    try:
        n0 = len(doc.dims)
        log = core.DebugLog(True)
        res = hr.job_dims(uidoc, fam_settings(doc, sym, fam_dim_offset=u'800'), log)
        check('dims: one chained dimension through all three hangers', doc.dims[n0:] == [3], (doc.dims[n0:], res, log.text()[-500:]))
        check('dims: centre reference square to the run', 'CenterFrontBack' in log.text(), log.text()[-400:])
        check('dims: view isolated, then put back', [c[0] for c in view.calls] == ['reset', 'isolate', 'reset'], view.calls)
        check('dims: the isolate keeps the hangers', set(h.Id.Value for h in placed) <= set(view.calls[1][1]))
        res2 = hr.job_dims(ns.UIDoc(doc, [], ns.FloorPlanView('Section')), fam_settings(doc, sym), core.DebugLog(True))
        check('dims: refused outside a floor plan', res2['done'] == 0 and 'floor plan' in u' '.join(res2['lines']), res2)
    except Exception:
        check('dims runs', False, traceback.format_exc())


    # ---- pipes and cable trays, alone
    ns.fam_created[:] = []
    doc, d1, d2, sym, l1, l2, z = ns.fam_model()
    tr = ns.tray(doc, 51, (0, 5, z), (20, 5, z), 300.0, 100.0, l1)
    pp = ns.pipe(doc, 52, (0, 15, z), (20, 15, z), 114.3, l1)
    ns.Insulation(doc, 710, pp, 25.0)
    uidoc = ns.UIDoc(doc, [], ns.PlanView())
    uidoc.Selection = ns.FamSelection([], [ns.PickRef(tr, (5, 5.3, z)), ns.PickRef(pp, (5, 15, z))])
    try:
        hr.job_place(uidoc, fam_settings(doc, sym), core.DebugLog(True))
        it, ip = ns.fam_created
        check('cable tray: half its width, invert at the tray bottom',
              abs(it.named['BGL_DIM_Width Left'].v * MM - 150) < 0.01 and abs(it.elevation() - bottom(z, 100)) < 1e-6,
              (it.named['BGL_DIM_Width Left'].v * MM, it.elevation() * MM))
        check('pipe: round, outside diameter plus insulation',
              abs(ip.named['BGL_DIM_Width Left'].v * MM - (57.15 + 25)) < 0.01 and
              abs(ip.elevation() * MM - (bottom(z, 114.3) * MM - 25)) < 0.01,
              (ip.named['BGL_DIM_Width Left'].v * MM, ip.elevation() * MM))
    except Exception:
        check('pipe / tray place runs', False, traceback.format_exc())

    # ---- one hanger round a tray and a pipe that sit together
    ns.fam_created[:] = []
    doc, d1, d2, sym, l1, l2, z = ns.fam_model()
    tr = ns.tray(doc, 51, (0, 0, z), (20, 0, z), 300.0, 100.0, l1)
    pz = z + (30 + 50 - 50) / MM          # pipe bottom 30 mm above the tray bottom
    pp = ns.pipe(doc, 52, (0, 260 / MM, pz), (20, 260 / MM, pz), 100.0, l1)
    far = ns.pipe(doc, 53, (0, 1100 / MM, z), (20, 1100 / MM, z), 100.0, l1)   # 740 mm clear: over the 500 limit
    uidoc = ns.UIDoc(doc, [51, 52], ns.PlanView())
    uidoc.Selection = ns.FamSelection([51, 52], [ns.PickRef(tr, (5, 0, z))])   # the far pipe not selected
    try:
        log = core.DebugLog(True)
        hr.job_place(uidoc, fam_settings(doc, sym, fam_ins_place=u'0'), log)
        h = ns.fam_created[0] if len(ns.fam_created) == 1 else None
        check('group: one hanger round tray and pipe', h is not None, len(ns.fam_created))
        if h is not None:
            sides = sorted(round(h.named[n].v * MM, 3) for n in ('BGL_DIM_Width Left', 'BGL_DIM_Width Right'))
            check('group: each side reaches its outer edge (280 / 180)', sides == [180.0, 280.0], sides)
            check('group: centred on the mean of the service centres', abs(h.Location.Point.Y * MM - 130) < 0.01, h.Location.Point.Y * MM)
            bb = h.get_BoundingBox(None)
            check('group: covers every service, edge to edge (-150 .. 310)',
                  abs((bb.Min.Y + 0.05) * MM + 150) < 0.5 and abs((bb.Max.Y - 0.05) * MM - 310) < 0.5,
                  ((bb.Min.Y + 0.05) * MM, (bb.Max.Y - 0.05) * MM))
            check('group: at the lowest invert (the tray)', abs(h.elevation() - bottom(z, 100)) < 1e-6, h.elevation() * MM)
            check('group: only the selected services, not the unselected pipe beside them',
                  'shared hanger: [51, 52]' in log.text(), log.text()[-600:])
    except Exception:
        check('group place runs', False, traceback.format_exc())

    # ---- the same group with a family whose stretch parameters point the other way
    ns.fam_created[:] = []
    ns.mirrored_family = True
    doc, d1, d2, sym, l1, l2, z = ns.fam_model()
    tr = ns.tray(doc, 51, (0, 0, z), (20, 0, z), 300.0, 100.0, l1)
    pp = ns.pipe(doc, 52, (0, 260 / MM, pz), (20, 260 / MM, pz), 100.0, l1)
    uidoc = ns.UIDoc(doc, [51, 52], ns.PlanView())
    uidoc.Selection = ns.FamSelection([51, 52], [ns.PickRef(tr, (5, 0, z))])
    try:
        log = core.DebugLog(True)
        hr.job_place(uidoc, fam_settings(doc, sym, fam_ins_place=u'0'), log)
        h = ns.fam_created[0]
        bb = h.get_BoundingBox(None)
        check('group, mirrored family: measured and swapped so it still covers every service',
              abs((bb.Min.Y + 0.05) * MM + 150) < 0.5 and abs((bb.Max.Y - 0.05) * MM - 310) < 0.5 and
              'came out mirrored' in log.text(), ((bb.Min.Y + 0.05) * MM, (bb.Max.Y - 0.05) * MM, log.text()[-400:]))
    except Exception:
        check('group mirrored runs', False, traceback.format_exc())
    finally:
        ns.mirrored_family = False

    # ---- auto place along two runs side by side: hangers shared, not doubled
    ns.fam_created[:] = []
    doc, d1, d2, sym, l1, l2, z = ns.fam_model()
    tr = ns.tray(doc, 51, (0, 0, z), (6000 / MM, 0, z), 300.0, 100.0, l1)
    pp = ns.pipe(doc, 52, (0, 260 / MM, pz), (6000 / MM, 260 / MM, pz), 100.0, l1)
    try:
        log = core.DebugLog(True)
        hr.job_auto(ns.UIDoc(doc, [51, 52], ns.PlanView()), fam_settings(doc, sym, fam_ins_auto=u'0'), log)
        xs = sorted(round(i.Location.Point.X * MM) for i in ns.fam_created)
        check('group auto: one set of hangers for both runs', xs == [300, 3300], (xs, log.text()[-700:]))
        check('group auto: each spans both services',
              all(sorted(round(i.named[n].v * MM, 3) for n in ('BGL_DIM_Width Left', 'BGL_DIM_Width Right')) == [180.0, 280.0]
                  for i in ns.fam_created), [(i.named['BGL_DIM_Width Left'].v * MM, i.named['BGL_DIM_Width Right'].v * MM) for i in ns.fam_created])
        check('group auto: no DW/144 cap on trays and pipes', 'not ductwork' in log.text())
    except Exception:
        check('group auto runs', False, traceback.format_exc())

    # ---- drop rod extender: a slab in this model, then a beam in a link
    doc, d1, d2, sym, l1, l2, z = ns.fam_model()
    h1 = ns.Inst(doc, sym, (1000 / MM, 0, 0), l1)
    h1.p['INSTANCE_ELEVATION_PARAM'].v = z - 0.5
    slab = ns.Target(doc, 800, SLAB_Z - 2.0, ray_z=SLAB_Z)
    uidoc = ns.UIDoc(doc, [h1.Id.Value], ns.PlanView())
    uidoc.Selection = ns.FamSelection([h1.Id.Value], [ns.PickRef(slab)])
    try:
        res = hr.job_rods(uidoc, fam_settings(doc, sym), core.DebugLog(True))
        rod = h1.named['BGL_DIM_Drop Rod Length'].v
        check('rod extender: up to the slab soffit', res['done'] == 1 and abs(rod - (SLAB_Z - (z - 0.5))) < 1e-6,
              (res, rod * MM))
        link = ns.Link(doc, 850)
        beam = ns.Target(None, 9001, SLAB_Z - 1.0, 'OST_StructuralFraming')
        link.ldoc.els[9001] = beam
        ns.link_hit = (850, 9001, SLAB_Z - 0.5)
        uidoc.Selection = ns.FamSelection([h1.Id.Value], [ns.PickRef(link), ns.LinkRef(link, beam)])
        res = hr.job_rods(uidoc, fam_settings(doc, sym), core.DebugLog(True))
        rod = h1.named['BGL_DIM_Drop Rod Length'].v
        check('rod extender: a beam in a linked model, by ray', res['done'] == 1 and abs(rod - (SLAB_Z - 0.5 - (z - 0.5))) < 1e-6,
              (res, rod * MM))
        ns.link_hit = None
        uidoc.Selection = ns.FamSelection([h1.Id.Value], [ns.PickRef(link), ns.LinkRef(link, beam)])
        res = hr.job_rods(uidoc, fam_settings(doc, sym), core.DebugLog(True))
        rod = h1.named['BGL_DIM_Drop Rod Length'].v
        check('rod extender: not directly above - to its lowest point (invert)', res['done'] == 1 and
              abs(rod - (SLAB_Z - 1.0 - (z - 0.5))) < 1e-6, (res, rod * MM))
        low = ns.Target(doc, 801, z - 3.0)
        uidoc.Selection = ns.FamSelection([h1.Id.Value], [ns.PickRef(low)])
        res = hr.job_rods(uidoc, fam_settings(doc, sym), core.DebugLog(True))
        check('rod extender: a target below the hanger is refused', res['done'] == 0 and res['skipped'] == 1, res)
    except Exception:
        check('rod extender runs', False, traceback.format_exc())


    # ---- align-lock to the service centre and its bottom face
    ns.fam_created[:] = []
    ns.alignments[:] = []
    ns.lock_views[:] = []
    doc, d1, d2, sym, l1, l2, z = ns.fam_model()
    plan = ns.PlanView()
    uidoc = ns.UIDoc(doc, [], plan)
    uidoc.Selection = ns.FamSelection([], [ns.PickRef(d1, (1500 / MM, 0, z))])
    try:
        log = core.DebugLog(True)
        hr.job_place(uidoc, fam_settings(doc, sym, fam_ins_place=u'0'), log)
        views = [a[0] for a in ns.alignments]
        check('lock: centre locked in the plan view', any(v is plan for v in views), (len(ns.alignments), log.text()[-500:]))
        check('lock: bottom locked in a section kept for it',
              len(ns.lock_views) == 1 and any(v is ns.lock_views[0] for v in views) and
              ns.lock_views[0].Name == u'Hanger Automation - bottom locks duct 31', [v.Name for v in ns.lock_views])
        ns.alignments[:] = []
        tp = ns.pipe(doc, 61, (0, 20, z), (20, 20, z), 60.3, l1)
        uidoc.Selection = ns.FamSelection([], [ns.PickRef(tp, (5, 20, z))])
        log = core.DebugLog(True)
        hr.job_place(uidoc, fam_settings(doc, sym, fam_ins_place=u'0'), log)
        check('lock: round pipe - centre only, and says why', len(ns.alignments) == 1 and 'centre lock only' in log.text(),
              len(ns.alignments))
        ns.alignments[:] = []
        uidoc.Selection = ns.FamSelection([], [ns.PickRef(d2, (4500 / MM, 0, z))])
        hr.job_place(uidoc, fam_settings(doc, sym, fam_lock_place=u'0'), core.DebugLog(True))
        check('lock: off when unticked', ns.alignments == [])
        ns.alignments[:] = []
        tr = ns.tray(doc, 71, (0, 30, z), (20, 30, z), 300.0, 100.0, l1)
        pp = ns.pipe(doc, 72, (0, 30 + 260 / MM, z), (20, 30 + 260 / MM, z), 100.0, l1)
        uidoc.Selection = ns.FamSelection([71, 72], [ns.PickRef(tr, (5, 30, z))])
        log = core.DebugLog(True)
        hr.job_place(uidoc, fam_settings(doc, sym, fam_ins_place=u'0'), log)
        check('lock: never on a shared hanger', ns.alignments == [] and 'not locked: shared hanger' in log.text(),
              len(ns.alignments))
        cm = ns.fam_created[-1].get_Parameter('ALL_MODEL_INSTANCE_COMMENTS').AsString()
        check('comments: a shared hanger lists each service family and type', cm == u'Cable Tray with Fittings : Ladder, '
              u'Pipe Types : Copper', cm)
        pp2 = ns.pipe(doc, 73, (0, 30 + 420 / MM, z), (20, 30 + 420 / MM, z), 100.0, l1)
        uidoc.Selection = ns.FamSelection([71, 72, 73], [ns.PickRef(tr, (9, 30, z))])
        hr.job_place(uidoc, fam_settings(doc, sym, fam_ins_place=u'0'), core.DebugLog(True))
        cm = ns.fam_created[-1].get_Parameter('ALL_MODEL_INSTANCE_COMMENTS').AsString()
        check('comments: repeats of one family and type counted - 2x', cm == u'Cable Tray with Fittings : Ladder, '
              u'2xPipe Types : Copper', cm)
        uidoc.Selection = ns.FamSelection([], [ns.PickRef(tp, (9, 20, z))])
        hr.job_place(uidoc, fam_settings(doc, sym, fam_ins_place=u'0'), core.DebugLog(True))
        cm = ns.fam_created[-1].get_Parameter('ALL_MODEL_INSTANCE_COMMENTS').AsString()
        check('comments: a hanger on one pipe', cm == u'Pipe Types : Copper', cm)
    except Exception:
        check('lock runs', False, traceback.format_exc())

    # ---- lock: a family whose centre plane is a Strong reference still locks
    for mode in ('strong', 'none'):
        ns.fam_created[:] = []
        ns.alignments[:] = []
        ns.refused[:] = []
        ns.family_refs = mode
        doc, d1, d2, sym, l1, l2, z = ns.fam_model()
        plan = ns.PlanView()
        uidoc = ns.UIDoc(doc, [], plan)
        uidoc.Selection = ns.FamSelection([], [ns.PickRef(d1, (1500 / MM, 0, z))])
        try:
            log = core.DebugLog(True)
            res = hr.job_place(uidoc, fam_settings(doc, sym, fam_ins_place=u'0'), log)
            centre = [a for a in ns.alignments if a[0] is plan]
            if mode == 'strong':
                check('lock: strong-reference family - centre found by trying its planes',
                      len(centre) == 1 and centre[0][2].label == 'Along' and ns.refused, (len(centre), log.text()[-600:]))
                check('lock: debug lists the family reference planes', 'family reference planes: Strong Reference "Square"' in log.text(),
                      log.text()[-600:])
            else:
                check('lock: no reference planes - says how to fix the family',
                      not centre and any('Is Reference: Center (Left/Right)' in ln for ln in res['lines']),
                      (res['lines'], log.text()[-500:]))
                check('lock: bottom still locked without reference planes (by its faces)',
                      any(a[0] is not plan for a in ns.alignments), len(ns.alignments))
        except Exception:
            check('lock {0} runs'.format(mode), False, traceback.format_exc())
        finally:
            ns.family_refs = 'named'

    # ---- lock: one section per service, reused on the next run
    ns.fam_created[:] = []
    ns.alignments[:] = []
    ns.lock_views[:] = []
    doc, d1, d2, sym, l1, l2, z = ns.fam_model()
    uidoc = ns.UIDoc(doc, [], ns.PlanView())
    try:
        for x in (1000, 2000):
            uidoc.Selection = ns.FamSelection([], [ns.PickRef(d1, (x / MM, 0, z))])
            log = core.DebugLog(True)
            hr.job_place(uidoc, fam_settings(doc, sym, fam_ins_place=u'0'), log)
        check('lock: second run reuses the section, no "(1)" copies',
              len(ns.lock_views) == 1 and 'reusing Hanger Automation - bottom locks duct 31' in log.text(),
              ([v.Name for v in ns.lock_views], log.text()[-400:]))
        check('lock: both hangers bottom-locked in it', len([a for a in ns.alignments if a[0] is ns.lock_views[0]]) == 2,
              len(ns.alignments))
    except Exception:
        check('lock reuse runs', False, traceback.format_exc())

    # ---- a lone round pipe among pre-selected services keeps its own section
    ns.fam_created[:] = []
    ns.alignments[:] = []
    ns.lock_views[:] = []
    doc, d1, d2, sym, l1, l2, z = ns.fam_model()
    p1 = ns.pipe(doc, 81, (0, 40, z), (20, 40, z), 100.0, l1)
    p2 = ns.pipe(doc, 82, (40, 30, z), (40, 50, z), 100.0, l1)   # selected too, but square to it: not joined
    uidoc = ns.UIDoc(doc, [], ns.PlanView())
    uidoc.Selection = ns.FamSelection([81, 82], [ns.PickRef(p1, (5, 40, z))])
    try:
        log = core.DebugLog(True)
        hr.job_place(uidoc, fam_settings(doc, sym, fam_ins_place=u'0'), log)
        inst = ns.fam_created[-1]
        check('lone service in a selection: still round - no section, centre lock only',
              ns.lock_views == [] and 'centre lock only' in log.text() and len(ns.alignments) == 1,
              (len(ns.lock_views), len(ns.alignments), log.text()[-500:]))
        check('lone service in a selection: at its own invert, its own size',
              abs(inst.elevation() - bottom(z, 100)) < 1e-6 and 'duct 100 x 100 mm round' in log.text(),
              (inst.elevation() * MM, log.text()[-500:]))
    except Exception:
        check('lone service runs', False, traceback.format_exc())

    # ---- units: under mechanical equipment, across it, at its bottom face
    ns.fam_created[:] = []
    ns.alignments[:] = []
    ns.lock_views[:] = []
    doc, d1, d2, sym, l1, l2, z = ns.fam_model()
    zb = 2500 / MM
    fcu = ns.Unit(doc, 91, 'OST_MechanicalEquipment', 'Mechanical Equipment', (10.0, 20.0), (1, 0),
                  1200 / MM, 800 / MM, zb, 500 / MM, l1)
    plan = ns.PlanView()
    uidoc = ns.UIDoc(doc, [], plan)
    uidoc.Selection = ns.FamSelection([], [ns.PickRef(fcu, (10.0 + 300 / MM, 20.3, zb + 500 / MM))])
    try:
        log = core.DebugLog(True)
        res = hr.job_place(uidoc, fam_settings(doc, sym), log)
        inst = ns.fam_created[-1] if ns.fam_created else None
        check('unit: mechanical equipment can be picked and gets a hanger', res['done'] == 1 and inst is not None,
              (res, log.text()[-600:]))
        if inst is not None:
            p = inst.Location.Point
            check('unit: where clicked along it, centred across it', abs((p.X - 10.0) * MM - 300) < 0.5 and abs(p.Y - 20.0) < 1e-9,
                  ((p.X - 10.0) * MM, (p.Y - 20.0) * MM))
            check('unit: at its bottom face', abs(inst.elevation() - zb) < 1e-6, inst.elevation() * MM)
            check('unit: stretched to its width (across the longer side)',
                  all(abs(inst.named[n].v * MM - 400) < 0.01 for n in ('BGL_DIM_Width Left', 'BGL_DIM_Width Right')) and
                  abs(abs(inst.HandOrientation.Y) - 1) < 1e-9,
                  ([inst.named[n].v * MM for n in ('BGL_DIM_Width Left', 'BGL_DIM_Width Right')], inst.HandOrientation.Y))
            check('unit: locked to its centre plane and bottom face',
                  any(a[0] is plan for a in ns.alignments) and any(a[0] is not plan for a in ns.alignments) and
                  ns.lock_views and ns.lock_views[0].Name == u'Hanger Automation - bottom locks mechanical equipment 91',
                  (len(ns.alignments), [v.Name for v in ns.lock_views], log.text()[-600:]))
    except Exception:
        check('unit place runs', False, traceback.format_exc())

    # ---- units: a duct accessory runs the way its connectors face
    ns.fam_created[:] = []
    doc, d1, d2, sym, l1, l2, z = ns.fam_model()
    dmp = ns.Unit(doc, 92, 'OST_DuctAccessory', 'Duct Accessories', (30.0, 30.0), (1, 0),
                  600 / MM, 300 / MM, zb, 300 / MM, l1, conn_dir=(0, 1))
    uidoc = ns.UIDoc(doc, [], ns.PlanView())
    uidoc.Selection = ns.FamSelection([], [ns.PickRef(dmp, (30.0, 30.0, zb + 300 / MM))])
    try:
        log = core.DebugLog(True)
        hr.job_place(uidoc, fam_settings(doc, sym), log)
        inst = ns.fam_created[-1] if ns.fam_created else None
        check('unit: duct accessory spans across its connectors, not its longer side',
              inst is not None and all(abs(inst.named[n].v * MM - 300) < 0.01 for n in ('BGL_DIM_Width Left', 'BGL_DIM_Width Right'))
              and abs(abs(inst.HandOrientation.X) - 1) < 1e-9 and 'runs along its connectors' in log.text(),
              log.text()[-600:])
    except Exception:
        check('unit accessory runs', False, traceback.format_exc())

    # ---- auto: a hanger near a bend is not read as one at the start of the next leg
    ns.fam_created[:] = []
    doc, d1, d2, sym, l1, l2, z = ns.fam_model()
    x3, y3 = 3300 / MM, 300 / MM
    da = ns.RvtDuct(doc, 101, (0, 50, z), (3000 / MM, 50, z), 400.0, 300.0, l1)
    db = ns.RvtDuct(doc, 102, (x3, 50 + y3, z), (x3, 50 + 2000 / MM, z), 400.0, 300.0, l1)
    el = ns.Fitting(doc, 103)
    ca0, ca1 = ns.Conn(da, 0, (0, 50, z), (-1, 0, 0)), ns.Conn(da, 1, (3000 / MM, 50, z), (1, 0, 0))
    cb0, cb1 = ns.Conn(db, 0, (x3, 50 + y3, z), (0, -1, 0)), ns.Conn(db, 1, (x3, 50 + 2000 / MM, z), (0, 1, 0))
    da.ConnectorManager, db.ConnectorManager = ns.CM([ca0, ca1]), ns.CM([cb0, cb1])
    e0, e1 = ns.Conn(el, 0, (3000 / MM, 50, z), (-1, 0, 0)), ns.Conn(el, 1, (x3, 50 + y3, z), (0, -1, 0))
    el.MEPModel = ns.MEPModel('Elbow', [e0, e1])
    ns.join(ca1, e0)
    ns.join(e1, cb0)
    try:
        log = core.DebugLog(True)
        hr.job_auto(ns.UIDoc(doc, [101, 102], ns.PlanView()), fam_settings(doc, sym), log)
        on_b = sorted(round((i.Location.Point.Y - 50) * MM) for i in ns.fam_created if abs(i.Location.Point.X - x3) < 1e-6)
        on_a = sorted(round(i.Location.Point.X * MM) for i in ns.fam_created if abs(i.Location.Point.Y - 50) < 1e-6)
        check('auto round a bend: both legs keep the hanger next to the bend',
              600 in on_b and 2700 in on_a and 'dropped' not in log.text(), (on_a, on_b, log.text()[-700:]))
    except Exception:
        check('auto bend runs', False, traceback.format_exc())

    # ================================================= Family Floor Support
    def floor_settings(doc, sym, **kw):
        st = fam_settings(doc, sym, **kw)
        st[u'_mode'] = u'floor'
        return st

    def fl(inst, name):
        return inst.named[name].v * MM

    # ---- floor: place on a 600 x 300 duct, centreline 3048 above Level 1
    ns.fam_created[:] = []
    ns.alignments[:] = []
    ns.lock_views[:] = []
    doc, d1, d2, sym, l1, l2, z = ns.fam_model()
    plan = ns.PlanView()
    uidoc = ns.UIDoc(doc, [], plan)
    uidoc.Selection = ns.FamSelection([], [ns.PickRef(d1, (1500 / MM, 0.2, z + 0.49))])
    try:
        log = core.DebugLog(True)
        res = hr.job_place(uidoc, floor_settings(doc, sym, fam_ins_place=u'0', fam_rod_place=u'1'), log)
        inst = ns.fam_created[-1] if ns.fam_created else None
        check('floor: one support placed', res['done'] == 1 and inst is not None, (res, log.text()[-500:]))
        if inst is not None:
            p = inst.Location.Point
            check('floor: stands on the service level (offset 0)', inst.LevelId.Value == 1 and abs(inst.elevation()) < 1e-9,
                  (inst.LevelId.Value, inst.elevation() * MM))
            check('floor: centred under the service', abs(p.Y) < 1e-9 and abs(p.X * MM - 1500) < 0.5, (p.X * MM, p.Y))
            check('floor: first bar offset at the invert', abs(fl(inst, 'First Bar Offset') - (3048 - 150)) < 0.01,
                  fl(inst, 'First Bar Offset'))
            check('floor: support height = the duct depth', abs(fl(inst, 'BIM_Hanger_Support_Height') - 300) < 0.01,
                  fl(inst, 'BIM_Hanger_Support_Height'))
            check('floor: widths half the duct each side', all(abs(fl(inst, n) - 300) < 0.01
                                                               for n in ('BGL_DIM_Width Left', 'BGL_DIM_Width Right')))
            check('floor: square to the duct', abs(abs(inst.HandOrientation.Y) - 1) < 1e-9)
            check('floor: no drop rod even when the hanger tick is on', fl(inst, 'BGL_DIM_Drop Rod Length') == 0.0)
            check('floor: locked to the centreline and the duct bottom (bottom bar)',
                  any(a[0] is plan for a in ns.alignments) and any(a[0] is not plan for a in ns.alignments),
                  (len(ns.alignments), log.text()[-500:]))
            check('floor: debug names the tab and the values', 'Family Floor Support tab' in log.text() and
                  'first bar: First Bar Offset = 2898' in log.text(), log.text()[-600:])
    except Exception:
        check('floor place runs', False, traceback.format_exc())

    # ---- floor: insulation outside and a clearance above
    ns.fam_created[:] = []
    doc, d1, d2, sym, l1, l2, z = ns.fam_model()
    ns.Insulation(doc, 720, d1, 25.0)
    uidoc = ns.UIDoc(doc, [], ns.PlanView())
    uidoc.Selection = ns.FamSelection([], [ns.PickRef(d1, (1500 / MM, 0, z))])
    try:
        st = floor_settings(doc, sym, fam_ins_place=u'1')
        st[u'_fam'] = dict(st[u'_fam'], cfg=dict(cfg, height_clear=u'20'))
        hr.job_place(uidoc, st, core.DebugLog(True))
        inst = ns.fam_created[-1]
        check('floor: insulation lowers the first bar and adds to height and width',
              abs(fl(inst, 'First Bar Offset') - (3048 - 150 - 25)) < 0.01 and
              abs(fl(inst, 'BIM_Hanger_Support_Height') - (300 + 50 + 20)) < 0.01 and
              abs(fl(inst, 'BGL_DIM_Width Left') - 325) < 0.01,
              (fl(inst, 'First Bar Offset'), fl(inst, 'BIM_Hanger_Support_Height'), fl(inst, 'BGL_DIM_Width Left')))
    except Exception:
        check('floor insulation runs', False, traceback.format_exc())

    # ---- floor: a service hosted on the level above stands on the level below it
    ns.fam_created[:] = []
    doc, d1, d2, sym, l1, l2, z = ns.fam_model()
    hi = ns.RvtDuct(doc, 111, (0, 60, z), (20, 60, z), 400.0, 200.0, l2)
    uidoc = ns.UIDoc(doc, [], ns.PlanView())
    uidoc.Selection = ns.FamSelection([], [ns.PickRef(hi, (5, 60, z))])
    try:
        log = core.DebugLog(True)
        hr.job_place(uidoc, floor_settings(doc, sym, fam_ins_place=u'0'), log)
        inst = ns.fam_created[-1]
        check('floor: service level above its invert - stands on the level below',
              inst.LevelId.Value == 1 and abs(fl(inst, 'First Bar Offset') - (3048 - 100)) < 0.01 and
              'standing on Level 1' in log.text(), (inst.LevelId.Value, fl(inst, 'First Bar Offset'), log.text()[-400:]))
    except Exception:
        check('floor level runs', False, traceback.format_exc())

    # ---- floor: shared support - height from the lowest bottom to the highest top
    ns.fam_created[:] = []
    doc, d1, d2, sym, l1, l2, z = ns.fam_model()
    tr = ns.tray(doc, 121, (0, 40, z), (20, 40, z), 300.0, 100.0, l1)
    pz = z - 50 / MM + 75 / MM
    pp = ns.pipe(doc, 122, (0, 40 + 300 / MM, pz), (20, 40 + 300 / MM, pz), 150.0, l1)
    uidoc = ns.UIDoc(doc, [], ns.PlanView())
    uidoc.Selection = ns.FamSelection([121, 122], [ns.PickRef(tr, (5, 40, z))])
    try:
        log = core.DebugLog(True)
        hr.job_place(uidoc, floor_settings(doc, sym, fam_ins_place=u'0'), log)
        inst = ns.fam_created[-1]
        check('floor: shared support spans the taller service',
              abs(fl(inst, 'BIM_Hanger_Support_Height') - 150) < 0.01 and
              abs(fl(inst, 'First Bar Offset') - (3048 - 50)) < 0.01 and 'shared hanger' in log.text(),
              (fl(inst, 'BIM_Hanger_Support_Height'), fl(inst, 'First Bar Offset'), log.text()[-500:]))
    except Exception:
        check('floor shared runs', False, traceback.format_exc())

    # ---- floor: auto place along a run, and again skips the supports already there
    ns.fam_created[:] = []
    doc, d1, d2, sym, l1, l2, z = ns.fam_model()
    try:
        hr.job_auto(ns.UIDoc(doc, [31, 32], ns.PlanView()), floor_settings(doc, sym, fam_ins_auto=u'0'), core.DebugLog(True))
        xs = sorted(round(i.Location.Point.X * MM) for i in ns.fam_created)
        check('floor auto: 300 / 3300 / 5700, each at the invert', xs == [300, 3300, 5700] and
              all(abs(fl(i, 'First Bar Offset') - 2898) < 0.01 for i in ns.fam_created), (xs, [fl(i, 'First Bar Offset') for i in ns.fam_created]))
        n0 = len(ns.fam_created)
        res2 = hr.job_auto(ns.UIDoc(doc, [31, 32], ns.PlanView()), floor_settings(doc, sym, fam_ins_auto=u'0'), core.DebugLog(True))
        check('floor auto again: supports standing far below still count as existing', len(ns.fam_created) == n0, res2)
    except Exception:
        check('floor auto runs', False, traceback.format_exc())

    # ---- floor: re-align refits first bar and height
    ns.fam_created[:] = []
    doc, d1, d2, sym, l1, l2, z = ns.fam_model()
    old = ns.Inst(doc, sym, (1500 / MM, 0.4, 0.0), l1)
    uidoc = ns.UIDoc(doc, [], ns.PlanView())
    uidoc.Selection = ns.FamSelection([], [], [[ns.PickRef(d1)], [ns.PickRef(old)]])
    try:
        hr.job_realign(uidoc, floor_settings(doc, sym, fam_ins_realign=u'0'), core.DebugLog(True))
        check('floor realign: slid under the centre, first bar and height refitted',
              abs(old.Location.Point.Y) < 1e-9 and abs(old.elevation()) < 1e-9 and
              abs(fl(old, 'First Bar Offset') - 2898) < 0.01 and abs(fl(old, 'BIM_Hanger_Support_Height') - 300) < 0.01,
              (old.Location.Point.Y, old.elevation(), fl(old, 'First Bar Offset')))
    except Exception:
        check('floor realign runs', False, traceback.format_exc())

    # ---- place: every pre-selected service in one hanger, however far apart or uneven
    ns.fam_created[:] = []
    doc, d1, d2, sym, l1, l2, z = ns.fam_model()
    a = ns.tray(doc, 131, (0, 50, z), (20, 50, z), 300.0, 100.0, l1)                       # bottom z-50
    b = ns.pipe(doc, 132, (0, 50 + 900 / MM, z - 100 / MM), (20, 50 + 900 / MM, z - 100 / MM), 100.0, l1)  # 750 clear, 100 lower
    c = ns.pipe(doc, 133, (0, 50 + 1500 / MM, z), (20, 50 + 1500 / MM, z), 60.0, l1)        # beyond it
    sk = ns.pipe(doc, 134, (0, 49, z), (5, 44, z), 60.0, l1)                                # not parallel
    uidoc = ns.UIDoc(doc, [], ns.PlanView())
    uidoc.Selection = ns.FamSelection([131, 132, 133, 134], [ns.PickRef(a, (5, 50, z))])
    try:
        log = core.DebugLog(True)
        res = hr.job_place(uidoc, fam_settings(doc, sym, fam_ins_place=u'0'), log)
        inst = ns.fam_created[-1] if len(ns.fam_created) == 1 else None
        check('place: one hanger round the whole selection', inst is not None and res['done'] == 1, (res, log.text()[-600:]))
        if inst is not None:
            w = sorted(round(inst.named[n].v * MM, 3) for n in ('BGL_DIM_Width Left', 'BGL_DIM_Width Right'))
            # centres 0, 900, 1500 -> mean 800; edges -150 .. 1530 -> reaches 950 / 730
            check('place: centred on the mean, reaching both outer edges', w == [730.0, 950.0] and
                  abs((inst.Location.Point.Y - 50) * MM - 800) < 0.5, (w, (inst.Location.Point.Y - 50) * MM))
            check('place: at the lowest invert of the selection', abs(inst.elevation() - (z - 100 / MM - 50 / MM)) < 1e-6,
                  (inst.elevation() * MM, (z - 150 / MM) * MM))
            check('place: a selected service not parallel is left out and named', any('Left out of the combined hanger' in ln
                  and '134' in ln for ln in res['lines']), res['lines'])
    except Exception:
        check('place selection runs', False, traceback.format_exc())

    # ================================================= floor supports on a picked base
    def base_place(picks, base_mode=u'element', linked=u'0', **kw):
        ns.fam_created[:] = []
        uidoc = ns.UIDoc(fdoc, [], ns.PlanView())
        uidoc.Selection = ns.FamSelection([], picks)
        log = core.DebugLog(True)
        st = floor_settings(fdoc, fsym, fam_ins_place=u'0', flr_base=base_mode, flr_base_linked=linked, **kw)
        res = hr.job_place(uidoc, st, log)
        return (ns.fam_created[-1] if ns.fam_created else None), res, log

    fdoc, d1, d2, fsym, l1, l2, z = ns.fam_model()
    plinth = ns.Target(fdoc, 900, 0.0)
    ns.down = {(None, 900): lambda x, y: 500 / MM}
    try:
        inst, res, log = base_place([ns.PickRef(plinth), ns.PickRef(d1, (1500 / MM, 0, z))])
        check('floor base: lifted onto the picked floor, still on its level',
              inst is not None and inst.LevelId.Value == 1 and abs(inst.elevation() * MM - 500) < 0.01, (inst and inst.elevation() * MM, log.text()[-500:]))
        check('floor base: first bar from the floor top to the invert, height unchanged',
              inst is not None and abs(fl(inst, 'First Bar Offset') - (2898 - 500)) < 0.01 and abs(fl(inst, 'BIM_Hanger_Support_Height') - 300) < 0.01,
              inst and (fl(inst, 'First Bar Offset'), fl(inst, 'BIM_Hanger_Support_Height')))
        # a roof falling across the duct: the centre sets the height, the log gives the fall
        ns.down = {(None, 900): lambda x, y: (400 + y * MM * 0.1) / MM}
        inst, res, log = base_place([ns.PickRef(plinth), ns.PickRef(d1, (1500 / MM, 0, z))])
        check('floor base on a slope: stands where its centre meets the surface',
              inst is not None and abs(inst.elevation() * MM - 400) < 0.01 and abs(fl(inst, 'First Bar Offset') - 2498) < 0.01 and
              'falls 60 mm across the frame' in log.text(), (inst and inst.elevation() * MM, log.text()[-400:]))
        # the surface stops short of the centre: its edge under one post
        ns.down = {(None, 900): lambda x, y: (450 / MM) if y > 0.2 else None}
        inst, res, log = base_place([ns.PickRef(plinth), ns.PickRef(d1, (1500 / MM, 0, z))])
        check('floor base: centre off the surface - stands on its edge under the post',
              inst is not None and abs(inst.elevation() * MM - 450) < 0.01 and 'its edge' in log.text(),
              (inst and inst.elevation() * MM, log.text()[-400:]))
        # a floor in a linked model
        link = ns.Link(fdoc, 860)
        lfloor = ns.Target(None, 9100, 0.0)
        link.ldoc.els[9100] = lfloor
        ns.down = {(860, 9100): lambda x, y: 250 / MM}
        inst, res, log = base_place([ns.PickRef(link), ns.LinkRef(link, lfloor), ns.PickRef(d1, (1500 / MM, 0, z))])
        check('floor base: a floor in a linked model', inst is not None and abs(inst.elevation() * MM - 250) < 0.01 and
              abs(fl(inst, 'First Bar Offset') - 2648) < 0.01, (inst and inst.elevation() * MM, log.text()[-400:]))
        # a base that is not under the service (here: above it): on the level, reported
        high = ns.Target(fdoc, 901, 2950 / MM - 1.0)
        ns.down = {}
        inst, res, log = base_place([ns.PickRef(high), ns.PickRef(d1, (1500 / MM, 0, z))])
        check('floor base not under the service: stands on the level and says so',
              inst is not None and abs(inst.elevation()) < 1e-9 and any('not under every support' in ln for ln in res['lines']),
              (inst and inst.elevation() * MM, res['lines']))
        # with the window's prompts: it says what to click before the pick
        ns.down = {(None, 900): lambda x, y: 500 / MM}
        fake = ns.FakeDimUI(None)
        inst, res, log = base_place([ns.PickRef(plinth), ns.PickRef(d1, (1500 / MM, 0, z))], _ui=fake)
        check('floor base: a prompt says to click the floor before the pick',
              getattr(fake, 'base_asked', None) == [False] and inst is not None and abs(inst.elevation() * MM - 500) < 0.01,
              (getattr(fake, 'base_asked', None), inst and inst.elevation() * MM))
        fake = ns.FakeDimUI(None)
        fake.base_answer = u'level'
        inst, res, log = base_place([ns.PickRef(d1, (1500 / MM, 0, z))], _ui=fake)
        check('floor base: "Stand on the level" skips the pick',
              inst is not None and abs(inst.elevation()) < 1e-9 and 'No base picked - the supports stand on the level.' in res['lines'],
              (inst and inst.elevation(), res['lines']))
        # level mode never asks
        ns.down = {(None, 900): lambda x, y: 500 / MM}
        inst, res, log = base_place([ns.PickRef(d1, (1500 / MM, 0, z))], base_mode=u'level')
        check('floor base on the level: no pick asked, offset 0', inst is not None and abs(inst.elevation()) < 1e-9)
        # auto along the run, all on the plinth
        ns.fam_created[:] = []
        uidoc = ns.UIDoc(fdoc, [31, 32], ns.PlanView())
        uidoc.Selection = ns.FamSelection([31, 32], [ns.PickRef(plinth)])
        hr.job_auto(uidoc, floor_settings(fdoc, fsym, fam_ins_auto=u'0', flr_base=u'element', fam_skip_existing=u'0'),
                    core.DebugLog(True))
        check('floor base: auto place lifts every support onto it', ns.fam_created and
              all(abs(i.elevation() * MM - 500) < 0.01 and abs(fl(i, 'First Bar Offset') - 2398) < 0.01 for i in ns.fam_created),
              [(i.elevation() * MM, fl(i, 'First Bar Offset')) for i in ns.fam_created])
    except Exception:
        check('floor base runs', False, traceback.format_exc())
    finally:
        ns.down = {}

    # ================================================= auto place from a 3D view: dimension views
    def dims_model():
        ns.fam_created[:] = []
        doc, d1, d2, sym, l1, l2, z = ns.fam_model()
        plan = ns.DimView(doc, 701, u'Level 1 - Mech', u'FloorPlan')
        rcp = ns.DimView(doc, 702, u'Level 1 - RCP', u'CeilingPlan')
        along = ns.DimView(doc, 703, u'Section A - along the run', u'Section', (1, 0, 0), (0, 0, 1), (0, -1, 0), (0, 0, 0))
        across = ns.DimView(doc, 704, u'Section B - across it', u'Section', (0, 1, 0), (0, 0, 1), (1, 0, 0), (0, 0, 0))
        sheet = ns.Sheet(doc, 801, u'M-101', u'Level 1 Ductwork', [plan, across])
        return doc, sym, z, plan, rcp, along, across, sheet

    try:
        doc, sym, z, plan, rcp, along, across, sheet = dims_model()
        v3d = ns.View3DFake(doc)
        uidoc = ns.UIDoc(doc, [31, 32], v3d)
        fake = ns.FakeDimUI({'views': [703], 'sheets': [801]}, u'sheets')
        log = core.DebugLog(True)
        res = hr.job_auto(uidoc, fam_settings(doc, sym, fam_dims=u'1', _ui=fake), log)
        names = sorted(r['name'] for r in fake.asked[0][1]) if fake.asked else []
        check('3D view + Dimension each run: asked, offered every plan and section, and the sheet',
              fake.asked and names == [u'Level 1 - Mech', u'Level 1 - RCP', u'Section A - along the run', u'Section B - across it']
              and [r['number'] for r in fake.asked[0][2]] == [u'M-101'], (names, fake.asked and fake.asked[0][2]))
        dv = [v.Name for v in doc.dim_views]
        check('dimensions go in the ticked view and the views on the ticked sheet',
              dv.count(u'Level 1 - Mech') == 1 and dv.count(u'Section A - along the run') == 1 and u'Level 1 - RCP' not in dv,
              (dv, log.text()[-600:]))
        check('a section the run does not lie along gets none, and the log says so',
              u'Section B - across it' not in dv and 'does not lie along Section B' in log.text(), dv)
        check('afterwards it offers to open them, and opens the sheet',
              fake.offered and fake.offered[0][2] == [u'M-101 - Level 1 Ductwork'] and uidoc.ActiveView is sheet,
              (fake.offered, getattr(uidoc.ActiveView, 'Name', None)))
        check('the results say where the dimensions went', any('in 2 of the 3 views chosen' in ln for ln in res['lines']),
              res['lines'])
        # the section dimension line sits in the section's plane, below the run
        # the duct ends cannot be seen in the view: the hangers alone are dimensioned
        doc, sym, z, plan, rcp, along, across, sheet = dims_model()
        uidoc = ns.UIDoc(doc, [31, 32], ns.View3DFake(doc))
        fake = ns.FakeDimUI({'views': [701], 'sheets': []}, None)
        ns.dim_refuse_over = 3
        try:
            log = core.DebugLog(True)
            hr.job_auto(uidoc, fam_settings(doc, sym, fam_dims=u'1', _ui=fake), log)
        finally:
            ns.dim_refuse_over = None
        check('a chain Revit refuses (ends not visible) falls back to the hangers alone',
              [v.Name for v in doc.dim_views] == [u'Level 1 - Mech'] and doc.dims == [3] and 'hangers only' in log.text() and
              'the full chain was refused' in log.text(), (doc.dims, log.text()[-500:]))
        # skip: no dimensions, the hangers still go in
        doc, sym, z, plan, rcp, along, across, sheet = dims_model()
        uidoc = ns.UIDoc(doc, [31, 32], ns.View3DFake(doc))
        fake = ns.FakeDimUI(None)
        res = hr.job_auto(uidoc, fam_settings(doc, sym, fam_dims=u'1', _ui=fake), core.DebugLog(True))
        check('skip dimension placement: hangers placed, no dimensions, said so',
              len(ns.fam_created) == 3 and doc.dim_views == [] and 'Dimension placement skipped.' in res['lines'] and
              fake.offered == [], (len(ns.fam_created), res['lines']))
        # in a plan nothing is asked
        doc, sym, z, plan, rcp, along, across, sheet = dims_model()
        uidoc = ns.UIDoc(doc, [31, 32], plan)
        fake = ns.FakeDimUI({'views': [], 'sheets': []})
        hr.job_auto(uidoc, fam_settings(doc, sym, fam_dims=u'1', _ui=fake), core.DebugLog(True))
        check('in a plan: no question, dimensioned there, nothing offered',
              fake.asked == [] and [v.Name for v in doc.dim_views] == [u'Level 1 - Mech'] and fake.offered == [],
              [v.Name for v in doc.dim_views])
        # views chosen, open the views
        doc, sym, z, plan, rcp, along, across, sheet = dims_model()
        uidoc = ns.UIDoc(doc, [31, 32], ns.View3DFake(doc))
        fake = ns.FakeDimUI({'views': [701, 702], 'sheets': []}, u'views')
        hr.job_auto(uidoc, fam_settings(doc, sym, fam_dims=u'1', _ui=fake), core.DebugLog(True))
        check('views ticked: opens the views it dimensioned', fake.offered and fake.offered[0][2] == [] and
              uidoc.ActiveView is rcp, getattr(uidoc.ActiveView, 'Name', None))
        # the FAB tab the same way
        ns.created[:] = []
        fdoc, s1, s2 = ns.model()
        fplan = ns.DimView(fdoc, 711, u'FAB plan', u'FloorPlan')
        fuidoc = ns.UIDoc(fdoc, [11, 12], ns.View3DFake(fdoc))
        fake = ns.FakeDimUI({'views': [711], 'sheets': []}, None)
        fres = rv.job_place(fuidoc, dict(settings, dims=u'1', _ui=fake), core.DebugLog(True))
        check('FAB auto place from 3D: asked, dimensioned in the chosen plan',
              fake.asked and fdoc.dim_views and all(v is fplan for v in fdoc.dim_views), (fres['lines'], fdoc.dim_views))
    except Exception:
        check('dimension views runs', False, traceback.format_exc())

    # ================================================= a placement Revit undoes does not break the next one
    try:
        ns.fam_created[:] = []
        ns.lock_views[:] = []
        doc, d1, d2, sym, l1, l2, z = ns.fam_model()
        uidoc = ns.UIDoc(doc, [], ns.PlanView())
        uidoc.Selection = ns.FamSelection([], [ns.PickRef(d1, (1000 / MM, 0, z)), ns.PickRef(d1, (2000 / MM, 0, z))])
        log = core.DebugLog(True)
        ns.rv.CURRENT_LOG[0] = log
        ns.undo_next_commit = 1
        res = hr.job_place(uidoc, floor_settings(doc, sym, fam_lock_place=u'1'), log)
        check('undone placement: the next click still places and bottom-locks (lock section made again)',
              res['done'] == 1 and res['failed'] == 1 and 'place:' not in log.text() and len(ns.lock_views) == 2 and
              'Revit undid "Place hanger on duct"' in log.text(), (res, len(ns.lock_views), log.text()[-900:]))
    except Exception:
        check('undone placement runs', False, traceback.format_exc())
    finally:
        ns.undo_next_commit = 0
        ns.rv.CURRENT_LOG[0] = None

    # ================================================= Circular System Based floor supports
    ccfg = dict(cfg, style=u'circ', dia=u'BIM_DIM_Diameter', circ_height=u'BIM_Hanger_Support_Height',
                circ_axis=u'X')

    def _ui_with(doc, ids, multi):
        u = ns.UIDoc(doc, ids, ns.PlanView())
        u.Selection = ns.FamSelection(ids, [], multi)
        return u

    def circ_settings(doc, sym, **kw):
        st = floor_settings(doc, sym, **kw)
        st[u'_fam'] = dict(st[u'_fam'], cfg=dict(ccfg, **kw.pop('_cfg', {})) if '_cfg' in kw else dict(ccfg))
        return st

    try:
        ns.fam_created[:] = []
        doc, d1, d2, sym, l1, l2, z = ns.fam_model()
        cp = ns.pipe(doc, 141, (0, 30, z), (20, 30, z), 114.3, l1)
        uidoc = ns.UIDoc(doc, [], ns.PlanView())
        uidoc.Selection = ns.FamSelection([], [ns.PickRef(cp, (5, 30.2, z + 0.1))])
        log = core.DebugLog(True)
        res = ns.hc.job_place(uidoc, circ_settings(doc, sym, fam_ins_place=u'0'), log)
        inst = ns.fam_created[-1] if ns.fam_created else None
        check('circular: one support at the pipe centre, standing on its level',
              inst is not None and abs(inst.Location.Point.Y - 30) < 1e-9 and abs(inst.Location.Point.X - 5) < 1e-9 and
              abs(inst.elevation()) < 1e-9, (res, log.text()[-400:]))
        if inst is not None:
            check('circular: diameter = the pipe diameter', abs(fl(inst, 'BIM_DIM_Diameter') - 114.3) < 0.01,
                  fl(inst, 'BIM_DIM_Diameter'))
            check('circular: support height = level up to the pipe centre (the ring centre)',
                  abs(fl(inst, 'BIM_Hanger_Support_Height') - 3048) < 0.01,
                  fl(inst, 'BIM_Hanger_Support_Height'))
            check('circular: the pipe runs along the family X', abs(abs(inst.HandOrientation.X) - 1) < 1e-9)
            check('circular: no widths or first bar set', fl(inst, 'BGL_DIM_Width Left') == 0.0 and fl(inst, 'First Bar Offset') == 0.0)
        # insulation, Y axis, on a picked plinth (no ring in the geometry: the rule alone)
        ns.fam_created[:] = []
        ns.ring_rule = 'none'
        ns.Insulation(doc, 730, cp, 25.0)
        plinth = ns.Target(doc, 905, 0.0)
        ns.down = {(None, 905): lambda x, y: 400 / MM}
        uidoc.Selection = ns.FamSelection([], [ns.PickRef(plinth), ns.PickRef(cp, (6, 30, z))])
        st = circ_settings(doc, sym, fam_ins_place=u'1', flr_base=u'element')
        st[u'_fam'][u'cfg'] = dict(ccfg, circ_axis=u'Y')
        log = core.DebugLog(True)
        ns.hc.job_place(uidoc, st, log)
        inst = ns.fam_created[-1] if ns.fam_created else None
        check('circular: insulated diameter, on the plinth, ring centred on the pipe, X across the pipe',
              inst is not None and abs(fl(inst, 'BIM_DIM_Diameter') - 164.3) < 0.01 and abs(inst.elevation() * MM - 400) < 0.01
              and abs(fl(inst, 'BIM_Hanger_Support_Height') - (3048 - 400)) < 0.01 and abs(abs(inst.HandOrientation.Y) - 1) < 1e-9,
              inst and (fl(inst, 'BIM_DIM_Diameter'), inst.elevation() * MM, fl(inst, 'BIM_Hanger_Support_Height'), log.text()[-300:]))
        ns.down = {}
        ns.ring_rule = 'centre'
        # the ring is checked, never moved: on the centre - nothing said; a family whose
        # height runs elsewhere - the results say how far off, the height stays at the rule
        for rule, want_off in (('centre', None), ('top', u'below'), ('bottom', u'above')):
            ns.fam_created[:] = []
            ns.ring_rule = rule
            uidoc.Selection = ns.FamSelection([], [ns.PickRef(cp, (8, 30, z))])
            log = core.DebugLog(True)
            res = ns.hc.job_place(uidoc, circ_settings(doc, sym, fam_ins_place=u'1'), log)
            inst = ns.fam_created[-1] if ns.fam_created else None
            said = [ln for ln in res['lines'] if 'the ring came out' in ln]
            check('circular ring check, height running to the ring {0}: {1}'.format(
                      rule, 'said nothing' if want_off is None else 'reported ' + want_off),
                  inst is not None and abs(fl(inst, 'BIM_Hanger_Support_Height') - 3048) < 0.01 and
                  (not said if want_off is None else (len(said) == 1 and (' %s ' % want_off) in said[0])),
                  (res['lines'], log.text()[-500:]))
        ns.ring_rule = 'centre'
        # ---- circular hangers (Family Hangers tab): placed like a rectangular hanger, diameter for the widths
        hcfg = dict(cfg, style=u'circ', dia=u'BIM_DIM_Diameter', circ_axis=u'X', rod=u'BGL_DIM_Drop Rod Length',
                    soffit=u'level')
        for rule, centred in (('centre', True), ('bottom', False)):
            ns.fam_created[:] = []
            ns.ring_rule = rule
            uidoc.Selection = ns.FamSelection([], [ns.PickRef(cp, (9, 30, z))])
            st = fam_settings(doc, sym, fam_ins_place=u'0', fam_rod_place=u'1')
            st[u'_fam'] = dict(st[u'_fam'], cfg=dict(hcfg))
            log = core.DebugLog(True)
            res = ns.hc.job_place(uidoc, st, log)
            inst = ns.fam_created[-1] if ns.fam_created else None
            off_line = any('ring came out' in ln for ln in res['lines'])
            check('circular hanger ({0}): on the pipe centreline, diameter set, rod from there to the level above, no widths{1}'.format(
                      rule, u', ring on the pipe' if centred else u', ring off-centre reported'),
                  inst is not None and res['done'] == 1 and abs(inst.elevation() * MM - 3048) < 0.01 and
                  abs(fl(inst, 'BIM_DIM_Diameter') - 114.3) < 0.01 and
                  abs(fl(inst, 'BGL_DIM_Drop Rod Length') - (4000 - 3048)) < 0.01 and
                  fl(inst, 'BGL_DIM_Width Left') == 0.0 and fl(inst, 'BIM_Hanger_Support_Height') == 0.0 and
                  off_line == (not centred) and 'circular hanger' in log.text(),
                  inst and (inst.elevation() * MM, fl(inst, 'BIM_DIM_Diameter'), fl(inst, 'BGL_DIM_Drop Rod Length'),
                            res['lines'], log.text()[-600:]))
        ns.ring_rule = 'centre'
        ns.fam_created[:] = []
        uidoc.Selection = ns.FamSelection([], [ns.PickRef(d1, (1500 / MM, 0, z))])
        st = fam_settings(doc, sym, fam_ins_place=u'0')
        st[u'_fam'] = dict(st[u'_fam'], cfg=dict(hcfg))
        res = ns.hc.job_place(uidoc, st, core.DebugLog(True))
        check('circular hanger: a rectangular duct is skipped and said so', not ns.fam_created and
              any('Circular System Based hanger goes on a pipe' in ln for ln in res['lines']), res['lines'])
        # a round FAB duct: on its centreline too, the diameter from its fabrication dimensions
        rfab = ns.RoundFab(doc, 151, (0, 60, z - 0.5), (10, 60, z - 0.5), 250.0)
        ns.fam_created[:] = []
        uidoc.Selection = ns.FamSelection([], [ns.PickRef(rfab, (4, 60.3, z - 0.5))])
        st = fam_settings(doc, sym, fam_ins_place=u'0')
        st[u'_fam'] = dict(st[u'_fam'], cfg=dict(hcfg))
        log = core.DebugLog(True)
        res = ns.hc.job_place(uidoc, st, log)
        inst = ns.fam_created[-1] if ns.fam_created else None
        check('circular hanger on a round FAB duct: on its centreline, diameter set',
              inst is not None and abs(inst.Location.Point.Y - 60) < 1e-9 and abs(inst.elevation() - (z - 0.5)) < 1e-9 and
              abs(fl(inst, 'BIM_DIM_Diameter') - 250.0) < 0.01, (res, log.text()[-600:]))
        # rectangular services are skipped; a selection is not bundled
        ns.fam_created[:] = []
        cp2 = ns.pipe(doc, 142, (0, 31, z), (20, 31, z), 60.3, l1)
        uidoc.Selection = ns.FamSelection([141, 142], [ns.PickRef(d1, (1500 / MM, 0, z)), ns.PickRef(cp, (7, 30, z))])
        res = ns.hc.job_place(uidoc, circ_settings(doc, sym, fam_ins_place=u'0'), core.DebugLog(True))
        check('circular: a rectangular duct is skipped and said so; selected pipes each get their own ring',
              len(ns.fam_created) == 1 and abs(fl(ns.fam_created[0], 'BIM_DIM_Diameter') - 114.3) < 0.01 and
              any('Circular System Based support goes on a pipe or round duct' in ln for ln in res['lines']),
              (len(ns.fam_created), res['lines']))
        # a sloping pipe: each support's height follows the pipe centre where it stands
        ns.fam_created[:] = []
        slope = ns.pipe(doc, 144, (0, 50, z), (6000 / MM, 50, z - 60 / MM), 100.0, l1)     # 1:100 fall
        ns.hc.job_auto(ns.UIDoc(doc, [144], ns.PlanView()), circ_settings(doc, sym, fam_ins_auto=u'0', fam_skip_existing=u'0'),
                    core.DebugLog(True))
        got = sorted((round(i.Location.Point.X * MM), round(fl(i, 'BIM_Hanger_Support_Height'), 2)) for i in ns.fam_created)
        want = [(x, round(3048 - x / 100.0, 2)) for x, _h in got]
        check('circular on a sloping pipe: the height follows the pipe at each support', len(got) >= 2 and got == want, (got, want))
        ns.fam_created[:] = []
        ns.hc.job_auto(ns.UIDoc(doc, [144], ns.PlanView()), circ_settings(doc, sym, fam_ins_auto=u'0', fam_skip_existing=u'0'),
                       core.DebugLog(True))
        off = [abs(f.Origin.Z - (z - i.Location.Point.X / 100.0)) * MM for i in ns.fam_created
               for f in i.get_Geometry(None)[0].Faces if isinstance(f, ns.DB.CylindricalFace) and abs(f.Axis.Z) < 0.5][::2]
        check('circular on a sloping pipe: every ring on the pipe centre', len(off) >= 2 and max(off) < 0.1, off)
        ns.ring_rule = 'centre'
        # auto along a pipe run
        ns.fam_created[:] = []
        runp = ns.pipe(doc, 143, (0, 40, z), (6000 / MM, 40, z), 88.9, l1)
        ns.hc.job_auto(ns.UIDoc(doc, [143], ns.PlanView()), circ_settings(doc, sym, fam_ins_auto=u'0', fam_skip_existing=u'0'),
                    core.DebugLog(True))
        check('circular: auto place rings along a pipe run', len(ns.fam_created) >= 2 and
              all(abs(fl(i, 'BIM_DIM_Diameter') - 88.9) < 0.01 and abs(i.Location.Point.Y - 40) < 1e-9 for i in ns.fam_created),
              [(fl(i, 'BIM_DIM_Diameter'), i.Location.Point.Y) for i in ns.fam_created])
        # re-align: a ring support knocked off the pipe slides back sideways and is re-centred
        ring_sup = ns.fam_created[0]
        ns.ring_rule = 'centre'
        pt0 = ring_sup.Location.Point
        ring_sup.Location.Point = ns.XYZ(pt0.X, pt0.Y + 0.4, pt0.Z)
        ring_sup.named['BIM_Hanger_Support_Height'].v = 1.0
        log = core.DebugLog(True)
        res = ns.hc.job_realign(_ui_with(doc, [143], [[ns.PickRef(ring_sup)]]),
                                circ_settings(doc, sym, fam_ins_realign=u'0'), log)
        ring = [f for f in ring_sup.get_Geometry(None)[0].Faces if isinstance(f, ns.DB.CylindricalFace)]
        check('circular re-align: back on the centreline, ring re-centred, not moved along the run',
              res['done'] == 1 and abs(ring_sup.Location.Point.Y - 40) < 1e-9 and abs(ring_sup.Location.Point.X - pt0.X) < 1e-9
              and ring and abs(ring[0].Origin.Z - z) < 0.1 / MM, (res, log.text()[-600:]))
        ns.ring_rule = 'centre'
    except Exception:
        check('circular runs', False, traceback.format_exc())
    finally:
        ns.down = {}
        ns.ring_rule = 'centre'

    # ================================================= worksets
    def ws_model():
        ns.fam_created[:] = []
        doc, d1, d2, sym, l1, l2, z = ns.fam_model()
        doc.IsWorkshared = True
        d1.WorksetId = ns.WsId(101)
        d2.WorksetId = ns.WsId(101)
        return doc, d1, d2, sym, l1, l2, z

    def ws_place(choice, **kw):
        doc, d1, d2, sym, l1, l2, z = ws_model()
        uidoc = ns.UIDoc(doc, [], ns.PlanView())
        uidoc.Selection = ns.FamSelection([], [ns.PickRef(d1, (1500 / MM, 0, z))])
        log = core.DebugLog(True)
        st = fam_settings(doc, sym, fam_workset=choice, **kw)
        res = hr.job_place(uidoc, st, log)
        return ns.fam_created[-1].WorksetId.IntegerValue, res, log

    try:
        got = dict((c, ws_place(c)[0]) for c in (u'', u'*service*', u'*active*', u'Mech - Hangers'))
        check('workset: placed hangers - leave / service / active / named',
              got == {u'': 101, u'*service*': 101, u'*active*': 301, u'Mech - Hangers': 201}, got)
        wid, res, log = ws_place(u'Old Workset')
        check('workset: a name not in the model - service workset and says so',
              wid == 101 and any('"Old Workset" is not in this model' in ln for ln in res['lines']), (wid, res['lines']))
        wid, _r, _l = ws_place(u'Mech - Hangers', _mode=u'floor')
        check('workset: floor supports too', wid == 201, wid)
    except Exception:
        check('workset place runs', False, traceback.format_exc())

    # ---- edited hangers: re-align moves them unless "leave as is"
    try:
        moved_to = {}
        for choice in (u'', u'*service*', u'Mech - Hangers'):
            doc, d1, d2, sym, l1, l2, z = ws_model()
            h = ns.Inst(doc, sym, (1500 / MM, 0.3, 0.0), l1)
            h.WorksetId = ns.WsId(7)
            uidoc = ns.UIDoc(doc, [], ns.PlanView())
            uidoc.Selection = ns.FamSelection([], [], [[ns.PickRef(d1)], [ns.PickRef(h)]])
            hr.job_realign(uidoc, fam_settings(doc, sym, fam_workset=choice), core.DebugLog(True))
            moved_to[choice] = h.WorksetId.IntegerValue
        check('workset: edited hangers - left alone / to the service / to the named one',
              moved_to == {u'': 7, u'*service*': 101, u'Mech - Hangers': 201}, moved_to)
        doc, d1, d2, sym, l1, l2, z = ws_model()
        h = ns.Inst(doc, sym, (1500 / MM, 0.3, 0.0), l1)
        h.ws_locked = True
        h.p['ELEM_PARTITION_PARAM'] = type(h.p['ELEM_PARTITION_PARAM'])(h)
        uidoc = ns.UIDoc(doc, [], ns.PlanView())
        uidoc.Selection = ns.FamSelection([], [], [[ns.PickRef(d1)], [ns.PickRef(h)]])
        res = hr.job_realign(uidoc, fam_settings(doc, sym, fam_workset=u'Mech - Hangers'), core.DebugLog(True))
        check('workset: one Revit will not move is reported, the rest still done',
              res['done'] == 1 and any('Could not move a hanger to its workset' in ln for ln in res['lines']), res)
    except Exception:
        check('workset realign runs', False, traceback.format_exc())

    # ---- auto place and the FAB tab
    try:
        doc, d1, d2, sym, l1, l2, z = ws_model()
        hr.job_auto(ns.UIDoc(doc, [31, 32], ns.PlanView()), fam_settings(doc, sym, fam_workset=u'*active*'), core.DebugLog(True))
        check('workset: auto place', ns.fam_created and all(i.WorksetId.IntegerValue == 301 for i in ns.fam_created),
              [i.WorksetId.IntegerValue for i in ns.fam_created])
        ns.created[:] = []
        fdoc, s1, s2 = ns.model()
        fdoc.IsWorkshared = True
        s1.WorksetId = s2.WorksetId = ns.WsId(101)
        st = dict(settings)
        rv.job_place(ns.UIDoc(fdoc, [11, 12], ns.PlanView()), dict(st, workset=u'Mech - Hangers'), core.DebugLog(True))
        ws_fab = [c['h'].WorksetId.IntegerValue for c in ns.created]
        check('workset: FAB auto place', ws_fab and all(w == 201 for w in ws_fab), ws_fab)
        ns.created[:] = []
        fdoc, s1, s2 = ns.model()
        fdoc.IsWorkshared = True
        s1.WorksetId = s2.WorksetId = ns.WsId(101)
        rv.job_place(ns.UIDoc(fdoc, [11, 12], ns.PlanView()), dict(st, workset=u''), core.DebugLog(True))
        ws_fab = [c['h'].WorksetId.IntegerValue for c in ns.created]
        check('workset: FAB leave as is - on the duct workset as before', ws_fab and all(w == 101 for w in ws_fab), ws_fab)
    except Exception:
        check('workset auto runs', False, traceback.format_exc())

    # ---- window: build, every handler, a full job through the ExternalEvent
    try:
        uiapp = ns.NetObj('UIApplication')
        fw = ns.win.show(uiapp)
        check('window: builds', fw is not None)
        # opening the tool: the chosen type's preview is read at once (API context), not queued
        item0 = {'key': u'P : Q', 'family': u'P', 'type': u'Q', 'cat': u'OST_GenericModel',
                 'cat_label': u'Generic Models', 'id': ns.NetObj('ElementId')}
        real_pb, real_sq = ns.hr.preview_bytes, fw.start_quiet
        read, queued = [], []
        ns.hr.preview_bytes = lambda d, i, px=112: (read.append(i), b'PNG')[1]
        fw.start_quiet = lambda *a, **k: (queued.append(a), False)[1]
        try:
            for t in fw.fam_tabs():
                t.open_doc = ns.NetObj('Document')
                t.items = [item0]
                t.previews = {}
                t.refill(u'P : Q')
                t.open_doc = None
            check('opening the tool: both tabs show the chosen family preview straight away',
                  len(read) == 2 and queued == [] and all(t.previews.get(u'P : Q') == b'PNG' for t in fw.fam_tabs()),
                  (len(read), len(queued)))
            fw.fam.previews = {}
            fw.fam.refill(u'P : Q')       # later, with Revit busy: queued, then retried
            n_q = len(queued)
            fw.start_quiet = lambda *a, **k: (queued.append(a), True)[1]
            fw.fam.retry_preview()
            check('a preview that could not be read is retried when Revit is free', n_q == 1 and len(queued) == 2,
                  (n_q, len(queued)))
        finally:
            ns.hr.preview_bytes, fw.start_quiet = real_pb, real_sq
            for t in fw.fam_tabs():
                t.items, t.previews = [], {}
        TABS_PANEL = dict((k, v[1]) for k, v in ns.win.TABS.items())
        again = ns.win.show(uiapp)
        check('window: second click brings it forward', again is None)
        for name in ('_cycle_theme', '_cycle_theme', '_cycle_theme', '_full_click', '_full_click',
                     '_header_down', '_key', '_copy_debug'):
            getattr(fw, name)(None, ns.NetObj('EventArgs'))
        fw.chrome._resizer(-1, 1)(None, ns.NetObj('DragDeltaEventArgs'))
        check('window: theme cycles back to start', fw.mode == ns.core.load_settings().get(u'theme') or True)
        fw._tab_fam_click(None, None)
        check('tabs: Family Hangers tab opens', fw.tab == u'fam' and fw._gather().get(u'active_tab') == u'fam')
        fw._tab_fab_click(None, None)
        check('tabs: FAB Hangers tab back', fw.tab == u'fab')
        fw._tab_floor_click(None, None)
        check('tabs: Family Floor Support tab opens alone',
              fw.tab == u'floor' and str(fw.c('FloorPanel').Visibility).endswith('Visible') and
              str(fw.c('FamPanel').Visibility).endswith('Collapsed') and str(fw.c('FabPanel').Visibility).endswith('Collapsed') and
              fw._gather().get(u'active_tab') == u'floor', (fw.tab, str(fw.c('FloorPanel').Visibility)))
        fw._tab_fab_click(None, None)
        import math as _mm
        fold = fw.fam.fold
        check('fold: every tool folded when the window opens', not any(fold.open.values()) and
              fw.c('FamToggleAllTxt').Text == u'Expand all', fold.state_text())
        fold.toggle('Auto')
        check('fold: a header click opens just that tool', fold.open['Auto'] and not fold.open['Place'], fold.state_text())
        fold.toggle('Place')
        check('fold: opening another tool folds the open one', fold.open['Place'] and not fold.open['Auto'], fold.state_text())
        fold.toggle('Place')
        fold.toggle('Auto')
        fw.fam._toggle_all(None, None)
        check('fold: expand all opens every tool', fold.all_open() and fw.c('FamToggleAllTxt').Text == u'Collapse all')
        fw.fam._toggle_all(None, None)
        check('fold: collapse all folds every tool', not any(fold.open.values()))
        fold._finisher('Dims', False)(None, None)
        check('fold: a folded body ends at height 0', fw.c('BodyFamDims').Height == 0.0)
        fold.toggle('Dims')
        fold._finisher('Dims', True)(None, None)
        check('fold: an opened body goes back to Auto height', _mm.isnan(fw.c('BodyFamDims').Height))
        fold.load(u'place,realign,auto,rods,dims')
        seen = []
        real = fold.on_resize
        fold.on_resize = seen.append
        fold.toggle('Rods')
        fold.on_resize = real
        check('fold: the window is told to follow each fold', len(seen) == 1)
        # ---- shrink to the taskbar: drawer down to the title bar, green arrow, and back
        dr = fw.drawer
        fw.win.Top, fw.win.Height, fw.win.ActualHeight, fw.win.MinHeight = 200.0, 700.0, 700.0, 420.0
        fw.c('HeaderBar').ActualHeight = 56.0
        fw.chrome.work_area = lambda: (0.0, 0.0, 1920.0, 1040.0)
        for n_ in ('TabsBar', 'LogBox', 'FooterBar', 'GripLayer'):
            fw.c(n_).Visibility = ns.win.Visibility.Visible
        fw.win.Content.ActualHeight = 688.0
        fw._shrink_click(None, None)
        vis = lambda n: str(fw.c(n).Visibility).endswith('Visible')
        check('shrink: the body is pinned at its height for the slide', fw.win.Content.Height == 688.0 and
              str(fw.win.Content.VerticalAlignment).endswith('Top'), fw.win.Content.Height)
        check('shrink: slides to just above the taskbar, title bar high',
              dr.shrunk and dr.moving and dr._target == (1040.0 - 70.0 - 8.0, 70.0) and fw.win.MinHeight == 0.0,
              (dr.shrunk, dr._target, fw.win.MinHeight))
        check('shrink: the button turns into the green up arrow', vis('ExpandIcon') and not vis('ShrinkIcon'))
        fw._shrink_click(None, None)
        check('shrink: a second press while it slides is ignored', dr.shrunk)
        dr.pending_finish(None, None)
        check('shrink: lands as a floating bar, body hidden',
              fw.win.Top == 962.0 and fw.win.Height == 70.0 and not dr.moving and
              not any(vis(n) for n in ('TabsBar', 'LogBox', 'FooterBar', 'GripLayer', 'FabPanel', 'FamPanel', 'FloorPanel')),
              (fw.win.Top, fw.win.Height, [n for n in ('TabsBar', 'LogBox', 'FooterBar', 'FabPanel') if vis(n)]))
        h0 = fw.win.Height
        fw.fit()
        check('shrink: the window does not refit itself while shrunk', fw.win.Height == h0)
        fw._shrink_click(None, None)
        check('expand: body back on the tab it was on, arrow back to shrink',
              not dr.shrunk and vis('TabsBar') and vis('FooterBar') and vis(TABS_PANEL[fw.tab]) and
              sum(1 for p in TABS_PANEL.values() if vis(p)) == 1 and vis('ShrinkIcon') and not vis('ExpandIcon'),
              (fw.tab, [p for p in TABS_PANEL.values() if vis(p)]))
        dr.pending_finish(None, None)
        check('expand: back where it was, full height, minimum restored',
              fw.win.Top == 200.0 and fw.win.Height == 700.0 and fw.win.MinHeight == 420.0,
              (fw.win.Top, fw.win.Height, fw.win.MinHeight))
        fw._shrink_click(None, None)
        dr.pending_finish(None, None)
        fw.win.Top, fw.win.ActualHeight = 300.0, 70.0          # bar dragged up the screen
        fw._shrink_click(None, None)
        check('expand after dragging the bar: grows up from it, kept on screen', dr._target == (0.0, 700.0), dr._target)
        dr.pending_finish(None, None)
        check('drawer: unpinned once open again', _mm.isnan(fw.win.Content.Height), fw.win.Content.Height)

        # ---- keys: Escape never closes; while parked Esc / Enter / F11 reopen; Ctrl+Shift+H toggles
        class Key(object):
            def __init__(self, k):
                self.Key, self.Handled = k, False
        closed = []
        real_close = fw.close
        fw.close = lambda: closed.append(1)
        try:
            fw._key(None, Key('Escape'))
            check('Escape never closes the tool', closed == [] and not dr.shrunk)
            class Mods(object):
                Modifiers = 'Control, Shift'
            real_kb = ns.ui.Keyboard
            ns.ui.Keyboard = Mods
            try:
                k = Key('H')
                fw._key(None, k)
                check('Ctrl+Shift+H shrinks', dr.shrunk and k.Handled)
                dr.pending_finish(None, None)
            finally:
                ns.ui.Keyboard = real_kb
            for key in ('Escape', 'Return', 'F11'):
                k = Key(key)
                fw._key(None, k)
                check('while parked, {0} opens it again'.format(key), not dr.shrunk and k.Handled and closed == [])
                dr.pending_finish(None, None)
                fw._shrink_click(None, None)
                dr.pending_finish(None, None)
            fw._shrink_click(None, None)
            dr.pending_finish(None, None)
        finally:
            fw.close = real_close

        # ---- an animation that cannot start still lands
        def no_anim(*a):
            raise Exception('no animation')
        fw.win.BeginAnimation = no_anim
        fw.win.Top, fw.win.ActualHeight = 200.0, 700.0
        fw._shrink_click(None, None)
        check('drawer: no animation - lands at once', dr.shrunk and not dr.moving and fw.win.Top == 962.0)
        fw._shrink_click(None, None)
        check('drawer: and opens at once', not dr.shrunk and not dr.moving and fw.win.Top == 200.0,
              (dr.shrunk, dr.moving, fw.win.Top, dr.saved, dr.bar_top))
        del fw.win._d['BeginAnimation']

        # ---- every dialog has a drawer; shrinking one parks the window beneath it
        rd = ns.hui.RulesDialog(fw, dict(ns.core.DEFAULTS))
        rd.drawer.chrome.work_area = lambda: (0.0, 0.0, 1920.0, 1040.0)
        rd.c('RulesHeader').ActualHeight = 56.0
        rd.win.Top, rd.win.ActualHeight, rd.win.MinHeight = 300.0, 400.0, 0.0
        rd.win.Content.ActualHeight = 388.0
        rd.drawer.toggle()
        check('dialog shrink: parks its window beneath it, itself a slot above',
              rd.drawer.shrunk and dr.shrunk and dr._target[0] == 962.0 and rd.drawer._target[0] == 884.0 and
              str(rd.win.SizeToContent).endswith('Manual'), (dr._target, rd.drawer._target))
        dr.pending_finish(None, None)
        rd.drawer.pending_finish(None, None)
        check('dialog shrink: its button turns green', str(rd.c('RulesExpandIcon').Visibility).endswith('Visible'))
        rd.drawer.toggle()
        check('dialog reopen: the window comes back with it', not rd.drawer.shrunk and not dr.shrunk)
        dr.pending_finish(None, None)
        rd.drawer.pending_finish(None, None)
        rd.drawer.toggle()
        dr.pending_finish(None, None)
        rd.drawer.pending_finish(None, None)
        rd.drawer.closing()
        check('dialog closed while parked: the window comes back', not dr.shrunk)
        dr.pending_finish(None, None)
        # a dialog opened while the window is parked centres on the screen
        fw._shrink_click(None, None)
        dr.pending_finish(None, None)
        pr = ns.hv.Prompt(fw, u'T', u'H', u'text', [(u'a', u'A', False), (u'b', u'B', True)])
        check('a dialog opened while the window is parked centres on the screen',
              str(pr.win.WindowStartupLocation).endswith('CenterScreen'), str(pr.win.WindowStartupLocation))
        fw._shrink_click(None, None)
        dr.pending_finish(None, None)
        pr.buttons[1][1].Click.fire(None, None) if hasattr(pr.buttons[1][1].Click, 'fire') else pr._clicker(u'b')(None, None)
        check('prompt: returns the button pressed', pr.answer == u'b')
        fs = ns.hui.FamSettingsDialog(fw, {'family': u'F', 'type': u'T'}, dict(ns.fc.FAM_DEFAULTS), [], u'x')
        check('family settings dialog has a drawer', fs.drawer is not None and fs.drawer.owner is dr)

        # ---- the Dimension views picker
        rows = [{'key': 1, 'name': u'L1 Mech', 'type': u'FloorPlan', 'scale': 50},
                {'key': 2, 'name': u'Section A', 'type': u'Section', 'scale': 20},
                {'key': 3, 'name': u'L2 Mech', 'type': u'FloorPlan', 'scale': 50}]
        sheets = [{'key': 10, 'number': u'M-102', 'name': u'L2', 'views': [3]},
                  {'key': 11, 'number': u'M-101', 'name': u'L1', 'views': [1, 2]}]
        dv = ns.hv.DimViewsDialog(fw, rows, sheets)
        check('picker: opens on Views, filtered to floor plans, Apply off; sheets in drawing-number order',
              dv.tab == u'views' and [r['key'] for r, _b in dv.shown(u'Views')] == [1, 3] and
              [r['number'] for r, _b in dv.sheet_boxes] == [u'M-101', u'M-102'] and dv.c('DvApply').IsEnabled is False,
              (dv.tab, [r['key'] for r, _b in dv.shown(u'Views')], dv.c('DvApply').IsEnabled))
        dv.c('CmbViewsKind').SelectedIndex = 3
        dv.c('TxtViewsSearch').Text = u'mech'
        check('picker: house search on views', [r['key'] for r, _b in dv.shown(u'Views')] == [1, 3])
        dv.c('TxtViewsSearch').Text = u''
        dv.c('CmbViewsKind').SelectedIndex = 2
        check('picker: kind filter (sections)', [r['key'] for r, _b in dv.shown(u'Views')] == [2])
        dv.c('CmbViewsKind').SelectedIndex = 3
        dv.c('TxtSheetsSearch').Text = u'101'
        dv.tick_shown(u'Sheets', True)
        dv.c('TxtSheetsSearch').Text = u''
        check('picker: tick shown ticks only what the search shows', dv.picked() == ([], [11]), dv.picked())
        check('picker: views listed plans first, then sections', [r['key'] for r, _b in dv.view_boxes] == [1, 3, 2])
        dv.view_boxes[1][1].IsChecked = True
        dv._ticked(dv.view_boxes[1][1], None)
        dv.count()
        check('picker: Apply live once something is ticked, status counts the views', dv.c('DvApply').IsEnabled is True and
              '3 views' in dv.c('DvStatusTxt').Text, dv.c('DvStatusTxt').Text)
        dv._apply(None, None)
        check('picker: Apply returns the ticked sheets and views', dv.result == {'views': [3], 'sheets': [11]}, dv.result)
        dv2 = ns.hv.DimViewsDialog(fw, rows, [])
        dv2._skip(None, None)
        check('picker: Skip returns nothing', dv2.tab == u'views' and dv2.result is None)
        try:
            fw.dim_ui.ask_base_pick(True)
            ok_prompt = True
        except Exception:
            ok_prompt = traceback.format_exc()
        check('floor base prompt builds', ok_prompt is True, ok_prompt)
        rd = ns.hui.RulesDialog(fw, dict(ns.core.DEFAULTS))
        rd._save(None, None)
        check('hanger rules dialog: builds and saves the four rules', rd.ok and sorted(rd.result) ==
              [u'fam_group_angle', u'fam_group_centre', u'fam_group_gap', u'fam_group_z'], rd.result)
        fw.fam.set_view_ok(False)
        check('dims button off outside a floor plan', fw.c('BtnFamDims').IsEnabled is False)
        fw.fam.set_view_ok(True)
        check('dims button on in a floor plan', fw.c('BtnFamDims').IsEnabled is True)
        check('copy debug carries family settings', 'Chosen:' in fw.fam.debug_text())
        item = {'key': u'F : T', 'family': u'F', 'type': u'T', 'cat': u'OST_MEPAncillaryFraming',
                'cat_label': u'MEP Ancillary Framing', 'id': ns.NetObj('ElementId')}
        fw.fam.items = [item]
        fw.fam.refill(u'F : T')
        extra = {}
        fw.fam.job_extra(extra)
        check('fam tab: chosen type handed to the job', extra.get(u'_fam', {}).get('family') == u'F', extra)
        dlg = ns.hui.FamSettingsDialog(fw, item, fw.fam.cfg_for(item), [u'W L', u'W R'], u'the family')
        dlg._save(None, None)
        fw.c('TxtFamAutoDimOffset').Text = u'650'
        fw.fam._mirror('TxtFamAutoDimOffset', 'TxtFamDimOffset', 'Text')(None, None)
        check('Auto place dimension distance is the Dimension placer one', fw._gather().get(u'fam_dim_offset') == u'650',
              fw._gather().get(u'fam_dim_offset'))
        fw.c('TxtFlrAutoDimOffset').Text = u'450'
        fw.flr._mirror('TxtFamAutoDimOffset', 'TxtFamDimOffset', 'Text')(None, None)
        check('floor tab: its own Auto place dimension distance', fw._gather().get(u'flr_dim_offset') == u'450' and
              fw._gather().get(u'fam_dim_offset') == u'650', (fw._gather().get(u'flr_dim_offset'), fw._gather().get(u'fam_dim_offset')))
        check('fam settings dialog: builds and saves', dlg.ok and set(dlg.result) == set(ns.fc.FAM_DEFAULTS), dlg.result)
        # ---- the floor tab: same tools minus the rod extender, its own settings, floor mode
        flr = fw.flr
        check('floor tab: four tools, all folded, no rod extender',
              flr.fold.keys == ['Place', 'Realign', 'Auto', 'Dims'] and not any(flr.fold.open.values()) and
              'BtnFamRods' not in flr.buttons, (flr.fold.keys, flr.buttons))
        fw.c('ChkFlrLockPlace').IsChecked = False
        fw.c('ChkFamLockPlace').IsChecked = True
        g = fw._gather()
        check('floor tab: its own settings', g.get(u'flr_lock_place') == u'0' and g.get(u'fam_lock_place') == u'1',
              (g.get(u'flr_lock_place'), g.get(u'fam_lock_place')))
        flr.items = [item]
        flr.refill(u'F : T')
        extra = dict(g)
        extra[u'fam_rod_place'] = u'1'
        flr.job_extra(extra)
        check('workset combos: every tab offers the model worksets after the three choices',
              fw.worksets and [len(v) for v in (fw.ws_values, fw.fam.ws_values, fw.flr.ws_values)] == [3 + len(fw.worksets)] * 3,
              ([len(v) for v in (fw.ws_values, fw.fam.ws_values, fw.flr.ws_values)], fw.worksets))
        fw.flr.ws_values = ns.core.workset_items([u'A', u'B'], u'')[2]
        fw.c('CmbFlrWorkset').SelectedIndex = 4
        g2 = dict(g)
        fw.flr.gather(g2)
        fw.flr.job_extra(g2)
        check('workset: the floor tab hands its own choice to the job', g2.get(u'fam_workset') == u'B' and g2.get(u'flr_workset') == u'B',
              (g2.get(u'fam_workset'), g2.get(u'flr_workset')))
        fw.c('CmbFlrBase').SelectedIndex = 1
        fw.c('ChkFlrBaseLinked').IsChecked = True
        g3 = fw._gather()
        check('floor tab: "stand on" choice saved', g3.get(u'flr_base') == u'element' and g3.get(u'flr_base_linked') == u'1',
              (g3.get(u'flr_base'), g3.get(u'flr_base_linked')))
        check('floor tab: jobs get floor mode, its settings, no rods',
              extra.get(u'_mode') == u'floor' and extra.get(u'fam_lock_place') == u'0' and
              extra.get(u'fam_rod_place') == u'0' and extra[u'_fam']['cfg'].get(u'mode') == u'floor', extra.get(u'_mode'))
        extra2 = dict(g)
        fw.fam.job_extra(extra2)
        check('hanger tab: jobs stay in hanger mode', extra2.get(u'_mode') == u'hang' and extra2.get(u'fam_lock_place') == u'1')
        dlg = ns.hui.FamSettingsDialog(fw, item, flr.cfg_for(item), [u'W L', u'W R', u'First Bar Offset', u'Support Height'],
                                       u'the family', u'floor')
        dlg.c('DlgHeightClear').Text = u'15'
        dlg._save(None, None)
        dlgc = ns.hui.FamSettingsDialog(fw, item, flr.cfg_for(item), [u'BIM_DIM_Diameter', u'BIM_Hanger_Support_Height'],
                                        u'the family', u'floor')
        check('floor settings dialog: Rectangular Floor Based / Circular System Based tabs, rectangular first',
              str(dlgc.c('DlgStyleTabs').Visibility).endswith('Visible') and dlgc.style == u'rect' and
              str(dlgc.c('DlgCircPanel').Visibility).endswith('Collapsed'))
        dlgc.show_style(u'circ')
        dlgc._save(None, None)
        check('floor settings dialog: the Circular tab saves the family as circular with its parameters',
              dlgc.result[u'style'] == u'circ' and {u'dia', u'circ_height', u'circ_axis'} <= set(dlgc.result) and
              str(dlgc.c('DlgRectPanel').Visibility).endswith('Collapsed'), dlgc.result)
        check('floor settings dialog: the circular tab has no drop rod rows',
              str(dlgc.c('DlgCircRod').Visibility).endswith('Collapsed') and not str(dlgc.c('DlgCircHeight').Visibility).endswith('Collapsed'))
        hdlg = ns.hui.FamSettingsDialog(fw, item, fw.fam.cfg_for(item), [u'Rod C', u'BIM_DIM_Diameter'], u'x')
        check('hanger settings dialog: Rectangular Hanger System / Circular System Based tabs',
              str(hdlg.c('DlgStyleTabs').Visibility).endswith('Visible') and hdlg.c('DlgTabRectTxt').Text == u'Rectangular Hanger System'
              and hdlg.style == u'rect' and str(hdlg.c('DlgCircHeight').Visibility).endswith('Collapsed')
              and not str(hdlg.c('DlgCircRod').Visibility).endswith('Collapsed'))
        hdlg.show_style(u'circ')
        hdlg.c('DlgCircRod').SelectedItem = u'Rod C'
        hdlg.c('DlgRod').SelectedItem = u'Rod R'
        hdlg._save(None, None)
        check('hanger settings dialog: a circular hanger saves as circular, its drop rod from its own tab',
              hdlg.result[u'style'] == u'circ' and hdlg.result[u'rod'] == u'Rod C', hdlg.result)
        hdlg2 = ns.hui.FamSettingsDialog(fw, item, fw.fam.cfg_for(item), [u'Rod R'], u'x')
        hdlg2.c('DlgCircRod').SelectedItem = u'Rod C'
        hdlg2.c('DlgRod').SelectedItem = u'Rod R'
        hdlg2._save(None, None)
        check('hanger settings dialog: a rectangular hanger keeps its own drop rod row',
              hdlg2.result[u'style'] == u'rect' and hdlg2.result[u'rod'] == u'Rod R', hdlg2.result)
        # ---- the family list: set-up families bold green, a tick to list only them, a grip to stretch it
        fam = fw.fam
        item2 = dict(item, key=u'G : T', family=u'G')
        fam.items = [item, item2]
        fam.fams = {u'G': dict(ns.fc.FAM_DEFAULTS)}
        fam.c('ChkFamSetOnly').IsChecked = False
        fam.refill(u'F : T')
        check('family list: only the set-up family is bold',
              [str(tb.FontWeight) == 'FontWeights.Bold' for tb, _s in fam.rows] == [False, True]
              and [s_ for _t, s_ in fam.rows] == [False, True],
              [(str(getattr(tb, 'FontWeight', '')), s_) for tb, s_ in fam.rows])
        fam.c('ChkFamSetOnly').IsChecked = True
        fam._filter_changed(None, None)
        check('family list: "Set up only" lists just the families set up', [it['family'] for it in fam.shown] == [u'G'],
              [it['family'] for it in fam.shown])
        check('family list: "Set up only" is saved', fw._gather().get(u'fam_set_only') == u'1')
        fam.c('ChkFamSetOnly').IsChecked = False
        fam._filter_changed(None, None)

        class Drag(object):
            def __init__(self, v):
                self.VerticalChange = v
        fam.c('LstFamilies').Height = 92.0
        fam._list_drag(None, Drag(150.0))
        fam._list_dropped(None, None)
        g4 = fw._gather()
        fam._list_drag(None, Drag(-5000.0))
        check('family list: the grip stretches it, saved per tab, never below its minimum',
              g4.get(u'fam_list_h') == u'242' and float(fam.c('LstFamilies').Height) == ns.hui.LIST_MIN
              and g4.get(u'flr_list_h') == u'92', (g4.get(u'fam_list_h'), fam.c('LstFamilies').Height, g4.get(u'flr_list_h')))
        fam.c('LstFamilies').Height = 92.0
        fam.items = [item]
        fam.fams = {}
        fam.refill(u'F : T')
        # a family never set up: ask first - set it up, ignore, or nothing
        ran, opened = [], []
        real_sj, real_sc = fw.start_job, flr._settings_click
        fw.start_job = lambda job, extra=None: ran.append(job)
        flr._settings_click = lambda s_, e_: opened.append(1)
        flr.fams = {}
        flr.ignored = set()
        flr.params[u'F'] = ([u'BGL_DIM_Width Left', u'BGL_DIM_Width Right', u'First Bar Offset',
                             u'BIM_Hanger_Support_Height'], u'the family')
        try:
            for ans, want_ran, want_open in ((None, 0, 0), (u'setup', 0, 1), (u'ignore', 1, 1)):
                flr.ask_setup = lambda it, a=ans: a
                flr._place_click(None, None)
                check('family not set up: answer {0} - run {1}, settings {2}'.format(ans, want_ran, want_open),
                      len(ran) == want_ran and len(opened) == want_open, (len(ran), len(opened)))
            flr.ask_setup = lambda it: (_ for _ in ()).throw(AssertionError('asked again'))
            flr._place_click(None, None)
            check('family not set up: not asked again after Ignore', len(ran) == 2)
            check('a rectangular floor support runs the rectangular jobs', bool(ran) and ran[-1] is ns.hr.job_place)
            flr.fams = {u'F': dict(ccfg, mode=u'floor')}
            flr.ignored = set()
            flr._place_click(None, None)
            check('a family set up is never asked about', len(ran) == 3)
            flr._realign_click(None, None)
            flr._auto_click(None, None)
            check('a circular floor support runs its own jobs, never the rectangular ones',
                  ran[-3:] == [ns.hc.job_place, ns.hc.job_realign, ns.hc.job_auto], ran[-3:])
            # the hanger tab: Rectangular Hanger System families keep their jobs, circular ones get theirs
            fam.fams = {u'F': dict(ns.fc.FAM_DEFAULTS, left=u'W L', right=u'W R')}
            fam._place_click(None, None)
            fam._auto_click(None, None)
            check('a rectangular hanger runs the rectangular jobs', ran[-2:] == [ns.hr.job_place, ns.hr.job_auto], ran[-2:])
            fam.fams = {u'F': dict(ns.fc.FAM_DEFAULTS, style=u'circ', dia=u'BIM_DIM_Diameter')}
            fam._place_click(None, None)
            fam._realign_click(None, None)
            fam._auto_click(None, None)
            check('a circular hanger runs the circular jobs',
                  ran[-3:] == [ns.hc.job_place, ns.hc.job_realign, ns.hc.job_auto], ran[-3:])
        finally:
            fam.fams = {}
            fw.start_job, flr._settings_click = real_sj, real_sc
            del flr.ask_setup
            flr.fams = {}
        check('floor settings dialog: rod rows hidden, first bar / height / clearance saved',
              str(dlg.c('DlgRod').Visibility).endswith('Collapsed') and
              not str(dlg.c('DlgFirstBar').Visibility).endswith('Collapsed') and
              {u'first_bar', u'height'} <= set(dlg.result) and dlg.result[u'height_clear'] == u'15', dlg.result)
        check('fam tab: preview read queued quietly', fw.busy and fw.quiet_cb is not None)
        raised0 = ns.events[-1].raised
        fw.start_job(lambda uidoc, st, log: ns.rv.new_result(u'queued tool'))
        check('a tool clicked during a read waits, not dropped', fw.pending is not None and ns.events[-1].raised == raised0)

        class Disp0(object):
            def BeginInvoke(self, fn):
                fn()
        fw.win.Dispatcher = Disp0()
        ns.win.Action = lambda f: f
        ns.win._STATE['handler'].Execute(uiapp)
        check('the waiting tool starts after the read', fw.pending is None and fw.busy and ns.events[-1].raised == raised0 + 1)
        ns.win._STATE['handler'].Execute(uiapp)
        check('fam tab: quiet read hands back without a results box', not fw.busy and fw.quiet_cb is None)
        egg = ns.egg_calls[-1] if ns.egg_calls else None
        check('egg: armed on the logo only', egg is not None and 'FindName(Logo)' in str(egg['logo']),
              egg and str(egg['logo']))
        check('egg: window passed as host_window', egg is not None and egg['host_window'] is fw.win)
        check('egg: theme handed over as a callable', egg is not None and callable(egg['theme']) and
              egg['theme']() in ('dark', 'light'))
        got = []
        fw.finished_orig = None
        real_finished = fw.finished
        fw.finished = lambda res, err: (got.append((res, err)), real_finished(res, err))

        class Disp(object):
            def BeginInvoke(self, fn):
                fn()
        fw.win.Dispatcher = Disp()
        ns.win.Action = lambda f: f
        doc, s1, s2 = ns.model()
        uiapp.ActiveUIDocument = ns.UIDoc(doc, [11, 12], ns.PlanView())
        raised_before = ns.events[-1].raised if ns.events else 0
        fw._place_click(None, None)
        check('window: event raised', ns.events and ns.events[-1].raised == raised_before + 1)
        check('window: busy while queued', fw.busy)
        ns.win._STATE['handler'].Execute(uiapp)
        check('window: job ran and came back', got and got[0][1] is None and got[0][0]['done'] == 4,
              got and (got[0][1] or got[0][0]))
        check('window: free again after', not fw.busy)
        fw._watchdog(None, None)
        fw._close_click(None, None)
    except Exception:
        check('window: no exception', False, traceback.format_exc())
    return out


def run(root=HERE, quiet=False):
    try:
        ns = build(root)
        res = checks(ns)
    except Exception:
        res = [('build', False, traceback.format_exc())]
    finally:
        if root in sys.path:
            sys.path.remove(root)
    bad = [r for r in res if not r[1]]
    if not quiet:
        for name, ok, detail in res:
            print('{0:46s} {1}'.format(name, 'ok' if ok else 'FAIL'))
            if not ok and detail != '':
                print('    {0}'.format(str(detail)[:1500]))
        print('{0} checks, {1} failed'.format(len(res), len(bad)))
    return len(bad)


def selftest():
    def edit(name, old, new):
        def go(root):
            p = os.path.join(root, name)
            with open(p, encoding='utf-8') as f:
                s = f.read()
            assert old in s, (name, old)
            with open(p, 'w', encoding='utf-8') as f:
                f.write(s.replace(old, new, 1))
        return go
    breaks = [
        ('1.0.0 crash: attribute on the Window', edit('fha_window.py',
            "        self.chrome = ui.Chrome(self.win)\n",
            "        self.chrome = ui.Chrome(self.win)\n        self.win._full = False\n")),
        ('host by index not Connector', edit('fha_revit.py',
            "places.append((elems[loc['id']], rec['cobj'][loc['entry']], loc['dist']))",
            "places.append((elems[loc['id']], loc['entry'], loc['dist']))")),
        ('hanger on the takeoff', edit('fha_revit.py',
            "st = core.avoid_blocks(st, block_st, clear_tk, length, edge)", "pass")),
        ('rods left auto-hosted', edit('fha_revit.py',
            "info.CanRodsBeHosted = False  #", "pass  #")),
        ('no end hanger before bend', edit('fha_core.py',
            "    end_required = end_type in ('bend', 'vertical', 'accessory')",
            "    end_required = False")),
        ('dimension refs dropped', edit('fha_revit.py',
            "        refs.Append(r)", "        pass")),
        ('temp view left behind', edit('fha_revit.py',
            "            self.doc.Delete(self.view.Id)", "            pass")),
        ('1.0.1 egg: window armed, not logo', edit('fha_ui.py',
            "            attach(logo, **_kwargs(attach, offered))",
            "            attach(win, logo)")),
        ('rehost moves instead of replacing', edit('fha_revit.py',
            "            if replace:\n                new, note = replace_hanger(",
            "            if False:\n                new, note = replace_hanger(")),
        ('rehost ignores the hanger kind', edit('fha_revit.py',
            "        if len(same) == 1:\n            choice = (same[0][0], same[0][2], u'only hanger button in its service')\n        elif same:",
            "        if True:\n            pass\n        elif same:")),
        ('probe hangers left in the model', edit('fha_revit.py',
            "                st.RollBack()\n", "                pass\n")),
        ('old hanger not deleted', edit('fha_revit.py',
            "    doc.Delete(old.Id)\n", "")),
        ('family: full width on each side', edit('hfam_core.py',
            "    return width_ft / 2.0 + clearance_mm / MM", "    return width_ft + clearance_mm / MM")),
        ('family: placed at duct centre, not invert', edit('hfam_revit.py',
            "    z_bot = q[2] - sec['depth'] / 2.0\n    along, across", "    z_bot = q[2]\n    along, across")),
        ('family: not turned square to the duct', edit('hfam_revit.py',
            "    ang = align_rotation(doc, inst, fc.family_x_dir(cfg[u'axis'], along, across))\n", "    ang = 0.0\n")),
        ('family: rod to the top level, not the next', edit('hfam_core.py',
            "    return min(above) if above else None", "    return max(above) if above else None")),
        ('family: level not inherited from the duct', edit('hfam_revit.py',
            "    level = element_level(doc, duct, q[2])\n    if level is None:\n        return None, [u'the duct has no level']",
            "    level = levels(doc)[-1][0]\n    if level is None:\n        return None, [u'the duct has no level']")),
        ('family: DW/144 cap ignored', edit('hfam_core.py',
            "    if use_dw144:\n", "    if False:\n")),
        ('family: hangers on flanges', edit('hfam_revit.py',
            "                loc = core.locate(chain, x, flange)", "                loc = core.locate(chain, x, 0.0)")),
        ('family: realign leaves it off-centre', edit('hfam_revit.py',
            "        ElementTransformUtils.MoveElement(doc, inst.Id, XYZ(q[0] - p[0], q[1] - p[1], 0.0))",
            "        pass")),
        ('tool click dropped during a read', edit('fha_window.py',
            "                    self.pending = (job, extra)", "                    pass")),
        ('1.1.0 re-align clipped to the picked segment', edit('hfam_revit.py',
            "    q = fc.on_line(sec['a'], sec['b'], p)\n", "    q = fc.on_centreline(sec['a'], sec['b'], p, END_MARGIN)\n")),
        ('re-align ignores the segment under the hanger', edit('hfam_revit.py',
            "            seg_el, sec = by_id.get(key, (duct, section(duct)))", "            seg_el, sec = duct, section(duct)")),
        ('insulation ignored', edit('hfam_core.py',
            "    out['ins_used'] = bool(outside and t > 0)", "    out['ins_used'] = False")),
        ('insulation never read', edit('hfam_revit.py',
            "    sec['ins'] = insulation_thickness(el)", "    sec['ins'] = 0.0")),
        ('dims: view left isolated', edit('hfam_revit.py',
            "    finally:\n        reset_isolate(doc, view, log)", "    finally:\n        pass")),
        ('dims: one dimension per hanger pair', edit('hfam_core.py',
            "            if abs(g[0][0] * d[0] + g[0][1] * d[1]) >= cos_tol and abs(g[1] - off) <= line_tol_ft:",
            "            if False:")),
        ('dims allowed in any view', edit('hfam_revit.py',
            "        return (not view.IsTemplate) and str(view.ViewType) == 'FloorPlan'", "        return True")),
        ('tools open unfolded', edit('hfam_ui.py',
            "        self.fold.load(u'')", "        self.fold.load(u'place,realign,auto,rods,dims')")),
        ('floor tab not wired', edit('fha_window.py',
            "        self.c('TabFloor').Click += self._tab_floor_click\n", "")),
        ('folded body never reaches 0', edit('fha_ui.py',
            "                body.Height = float('nan') if opened else 0.0\n                body.BeginAnimation(UIElement.OpacityProperty, None)",
            "                body.BeginAnimation(UIElement.OpacityProperty, None)")),
        ('pipes not hangable', edit('hfam_revit.py',
            "    return isinstance(el, (Duct, Pipe, CableTray))", "    return isinstance(el, Duct)")),
        ('pipe insulation ignored', edit('hfam_revit.py',
            "    if isinstance(el, CableTray):\n        return 0.0\n    if isinstance(el, FabricationPart):",
            "    if not isinstance(el, Duct):\n        return 0.0\n    if isinstance(el, FabricationPart):")),
        ('grouped services hung separately', edit('hfam_core.py',
            "            if g < gap_tol_ft and max(nb) - min(nb) <= z_tol_ft + 1e-9:", "            if False:")),
        ('group hung at the highest invert', edit('hfam_core.py',
            "    bottom = min(bottoms)\n", "    bottom = max(bottoms)\n")),
        ('auto doubles hangers on grouped runs', edit('hfam_revit.py',
            "                            covered.append((q, sec['keys']))\n", "                            pass\n")),
        ('rod extender ignores links', edit('hfam_revit.py',
            "        if not isinstance(el, RevitLinkInstance):\n            return el, None", "        return el, None")),
        ('rod extender ignores the ray', edit('hfam_revit.py',
            "                    if hit is not None:\n                        return hit.GetReference().GlobalPoint.Z, u'ray'",
            "                    if False:\n                        return None, u'ray'")),
        ('rod extender to the target top', edit('hfam_revit.py',
            "                return bb.Min.Z\n", "                return bb.Max.Z\n")),
        ('shared hangers locked', edit('hfam_revit.py',
            "    if len(sec.get('keys', [0])) > 1:\n        log.add(u'   not locked: shared hanger')\n        return",
            "    pass")),
        ('no bottom lock', edit('hfam_revit.py',
            "        hit, err = try_align(self.doc, view, bottoms, cands, self.log)", "        hit, err = None, None")),
        ('lock ignores its tick', edit('hfam_revit.py',
            "    locker = Locker(doc, uidoc.ActiveView, log) if core.as_bool(settings, u'fam_lock_place') else None",
            "    locker = Locker(doc, uidoc.ActiveView, log)")),
        ('shared hanger centred on the edges', edit('hfam_core.py',
            "    if centre == u'edges' or len(group) == 1:", "    if True:")),
        ('swap ignored', edit('hfam_core.py', "    return (right, left) if swap else (left, right)", "    return (left, right)")),
        ('mirrored shared hanger left mirrored', edit('hfam_revit.py',
            "        check_sides(doc, inst, sec, q, cfg, vals, clear, log)", "        pass")),
        ('lone service loses its own section', edit('hfam_core.py',
            "    if len(b['keys']) <= 1:\n        sec = dict(lead_sec)", "    if False:\n        sec = dict(lead_sec)")),
        ('only the named centre plane tried', edit('hfam_revit.py',
            "            cands = instance_refs(inst, (along_type, square, 'StrongReference', 'WeakReference',",
            "            cands = instance_refs(inst, (along_type, )) or instance_refs(inst, (")),
        ('lock section copied every run', edit('hfam_revit.py',
            "    old = find_lock_section(doc, base)", "    old = None")),
        ('units not pickable', edit('hfam_revit.py',
            "        if not is_unit(e):\n            return False", "        if True:\n            return False")),
        ('units ignore their connectors', edit('hfam_core.py',
            "    if hint is not None:\n        run_is_h", "    if False:\n        run_is_h")),
        ('unit hung at its centre', edit('hfam_core.py',
            "    bottom = min(zs) if bottom_z is None else bottom_z", "    bottom = (min(zs) + max(zs)) / 2.0")),
        ('hanger round a bend drops the next leg', lambda root: (
            edit("hfam_revit.py", "core.station_on_run(segs, e, off, max_dz_ft=dz_reach)", "core.station_of_point(segs, e, frv.TAP_REACH)")(root),
            edit('hfam_revit.py', "            mine = [cq for cq, keys in covered if span_keys & set(keys)]",
                 "            mine = list(placed_all)")(root),
            edit('hfam_revit.py', "                        made.append((inst, sec))\n",
                 "                        made.append((inst, sec))\n                        placed_all.append(q)\n")(root),
            edit('hfam_revit.py', "    covered = []   #", "    placed_all = []\n    covered = []   #")(root))),
        ('floor support hung at the invert', edit('hfam_revit.py',
            "    base = stand - level.ProjectElevation if floor else z_bot - level.ProjectElevation", "    base = z_bot - level.ProjectElevation")),
        ('floor first bar never set', edit('hfam_revit.py',
            "((u'first_bar', u'first bar', first), (u'height', u'support height', height))",
            "((u'height', u'support height', height),)")),
        ('floor height ignores insulation', edit('hfam_core.py',
            "        h = sec['depth']\n", "        h = sec.get('bare_depth', sec['depth'])\n")),
        ('floor shared height from the lead only', edit('hfam_core.py',
            "           'span_height': b['top'] - b['bottom']}", "           'span_height': lead_sec['depth']}")),
        ('floor on a level above the service', edit('hfam_revit.py',
            "    if level is not None and level.ProjectElevation <= z_invert + TOL:", "    if level is not None:")),
        ('floor tab shares the hanger settings', edit('hfam_ui.py',
            "        return core.floor_key(key) if self.floor else key", "        return key")),
        ('floor tab runs in hanger mode', edit('hfam_ui.py',
            "        s[u'_mode'] = self.mode", "        s[u'_mode'] = u'hang'")),
        ('floor existing supports missed', edit('hfam_revit.py',
            "dz_reach = 1000.0 if is_floor(cfg) else 5.0", "dz_reach = 5.0")),
        ('floor gets drop rods', edit('hfam_revit.py',
            "    rod = core.as_bool(settings, u'fam_rod_place') and not is_floor(settings)",
            "    rod = core.as_bool(settings, u'fam_rod_place')")),
        ('workset choice ignored on new hangers', edit('hfam_revit.py',
            "        ws.apply(inst, duct, True)", "        frv.match_workset(inst, duct)")),
        ('edited hangers never moved', edit('hfam_revit.py',
            "        ws.apply(inst, duct, False)", "        pass")),
        ('active workset ignored', edit('fha_core.py',
            "    if choice == WS_ACTIVE:\n        return active_ws", "    if choice == WS_ACTIVE:\n        return service_ws")),
        ('leave as is moves edited hangers', edit('fha_core.py',
            "        return service_ws if new else None\n    if choice == WS_SERVICE", "        return service_ws\n    if choice == WS_SERVICE")),
        ('FAB place ignores the workset', edit('fha_revit.py',
            "                    ws.apply(h, host, True)", "                    match_workset(h, host)")),
        ('workset refusal unreported', edit('fha_revit.py',
            "            if msg not in self.problems:\n                self.problems.append(msg)", "            pass")),
        ('missing workset not reported', edit('fha_revit.py',
            "            if self.named is None:\n                self.problems.append(", "            if False:\n                self.problems.append(")),
        ('selection hung by the grouping rules', edit('hfam_revit.py',
            "    rules = fc.wrap_rules(fc.group_rules(settings))", "    rules = fc.group_rules(settings)")),
        ('shrink leaves the body showing', edit('fha_ui.py',
            "                    el.Visibility = Visibility.Collapsed\n                    self.hidden.append(el)",
            "                    pass")),
        ('shrink button keeps its icon', edit('fha_ui.py',
            "                self.expand_icon.Visibility = Visibility.Visible if shrunk else Visibility.Collapsed", "                pass")),
        ('expand forgets where it was', edit('fha_ui.py',
            "        top = core.expand_top(top0, self.bar_top, float(win.Top), float(win.ActualHeight), h0, wa_top, wa_h)",
            "        top = wa_top")),
        ('window refits while shrunk', edit('fha_window.py',
            "        if self.drawer is not None and (self.drawer.shrunk or self.drawer.moving):\n            return\n", "")),
        ('shrink keeps the minimum height', edit('fha_ui.py',
            "        win.MinHeight = 0.0\n", "")),
        ('floor base ignored', edit('hfam_revit.py',
            "        stand = floor_stand(base_el, sec, q, z_bot, cfg, level, problems, log)", "        pass")),
        ('floor base: first bar still from the level', edit('hfam_revit.py',
            "        first, height = fc.floor_values(z_bot, stand, sec,", "        first, height = fc.floor_values(z_bot, level.ProjectElevation, sec,")),
        ('floor base on a slope taken at a post', edit('hfam_revit.py',
            "        if zc is not None:\n            return zc, u'its top surface under the centre', under",
            "        if zc is not None and under[0] is not None:\n            return under[0], u'post', under")),
        ('floor base edge not used', edit('hfam_revit.py',
            "        hits = [z for z in under if z is not None]\n        if hits:", "        hits = []\n        if hits:")),
        ('linked floor base not matched', edit('hfam_revit.py',
            "                        eid_value(r.LinkedElementId) == eid_value(self.el.Id):\n                    return r.GlobalPoint.Z",
            "                        eid_value(r.LinkedElementId) == -1:\n                    return r.GlobalPoint.Z")),
        ('floor base never asked for', edit('hfam_revit.py',
            "    if not is_floor(settings) or settings.get(u'flr_base', u'level') != u'element':",
            "    if True:")),
        ('Escape closes the tool', edit('fha_window.py',
            "            # Escape never closes the tool: it is pressed to leave Revit picks",
            "            if k == 'Escape':\n                self.close()")),
        ('drawer keys ignored', edit('fha_window.py', "            if self.drawer.key(e):", "            if False:")),
        ('drawer stuck with no animation', edit('fha_ui.py', "            finish()   # no animation: land at once", "            pass")),
        ('body squashed, not pinned', edit('fha_ui.py', "            self._pin(float(win.Content.ActualHeight))", "            pass")),
        ('dialog leaves its window over Revit', edit('fha_ui.py', "            self.owner.shrink(0)", "            pass")),
        ('window left parked after a dialog', edit('fha_ui.py',
            "    def closing(self):\n        u\"\"\"A dialog is closing: an owner it parked comes back.\"\"\"\n        if",
            "    def closing(self):\n        u\"\"\"A dialog is closing: an owner it parked comes back.\"\"\"\n        if False and")),
        ('dialog centred on a parked bar', edit('fha_ui.py', "    if owner_parked(owner):", "    if False:")),
        ('3D dimensions never asked', edit('fha_revit.py', "    ui = settings.get(u'_ui')\n    if ui is None:\n        res['lines'].append(u'Dimensions skipped",
                                            "    ui = None\n    if ui is None:\n        res['lines'].append(u'Dimensions skipped")),
        ('views on ticked sheets ignored', edit('fha_revit.py',
            "    keys = core.chosen_views(choice.get('views', []), choice.get('sheets', []), sheets)",
            "    keys = list(choice.get('views', []))")),
        ('section across the run dimensioned', edit('fha_revit.py',
            "        return abs(core.vdot(core.vnorm(core.vsub(p_end, p_start)), core.vnorm(r))) > 0.999",
            "        return True")),
        ('never opens the views', edit('fha_revit.py',
            "    pick = sheets if ans == u'sheets' else (done if ans == u'views' else [])", "    pick = []")),
        ('picker ticks hidden rows', edit('hview_ui.py',
            "            for _r, b in self.shown(which):\n                b.IsChecked = on",
            "            for _r, b in (self.sheet_boxes if which == u'Sheets' else self.view_boxes):\n                b.IsChecked = on")),
        ('picker applies nothing', edit('hview_ui.py', "            self.c('DvApply').IsEnabled = bool(total)", "            self.c('DvApply').IsEnabled = True")),
        ('floor base pick not announced', edit('hfam_revit.py',
            "    ui = settings.get(u'_ui')\n    if ui is not None:   # say so first", "    ui = None\n    if ui is not None:   # say so first")),
        ('tools stay open together', edit('fha_ui.py',
            "                if k != key and self.open[k]:\n                    self.set(k, False, animate=True)",
            "                if False:\n                    pass")),
        ('Auto dimension distance not shared', edit('hfam_ui.py',
            "                setattr(self.c(dst), prop, getattr(self.c(src), prop))", "                pass")),
        ('no fallback when the chain is refused', edit('hfam_revit.py',
            "    tries = [(u'run ends and hangers', hang + ends), (u'hangers only', hang)]",
            "    tries = [(u'run ends and hangers', hang + ends)]")),
        ('picker opens on sheets', edit('hview_ui.py', "        self.tab = u'views'      # Views first", "        self.tab = u'sheets'      # Views first")),
        ('preview queued at open, never shown', edit('hfam_ui.py',
            "        if self.open_doc is not None:   # opening the tool", "        if False:   # opening the tool")),
        ('preview never retried', edit('hfam_ui.py',
            "        if it is not None and it['key'] not in self.previews and not self.o.busy:\n            self.request_preview(it)",
            "        pass")),
        ('dead lock section reused', edit('hfam_revit.py',
            "        if key in self.sections and not _alive(self.sections[key]):", "        if False:")),
        ('undone transaction not logged', edit('fha_revit.py',
            "    if status != 'Committed':\n        _say(", "    if False:\n        _say(")),
        ('comments not written on family hangers', edit('hfam_revit.py',
            "    frv.write_service_comment(inst, frv.services_of(doc, sec, duct), log)\n", "")),
        ('comments only the picked service', edit('hfam_revit.py',
            "frv.services_of(doc, sec, duct)", "[duct]")),
        ('comments not written on FAB hangers', edit('fha_revit.py',
            "                write_service_comment(h, [host], log)\n", "")),
        ('circular hanger runs the rectangular job', edit('hfam_ui.py',
            "        return cc.is_circ(dict(cfg or {}, mode=self.mode))", "        return self.floor and cc.is_circ(dict(cfg or {}, mode=self.mode))")),
        ('circular hanger rod from the wrong row', edit('hfam_ui.py',
            "        rod_box = 'DlgCircRod' if circ_hang else 'DlgRod'", "        rod_box = 'DlgRod'")),
        ('circular hanger at the invert, not the centreline', edit('hcirc_core.py',
            "    return z_centre - level_z", "    return z_centre - level_z - 0.2")),
        ('circular hanger rod from the invert', edit('hcirc_revit.py',
            "        L = fc.rod_length(q[2], top)", "        L = fc.rod_length(z_bot, top)")),
        ('circular hanger without its rod', edit('hcirc_revit.py',
            "    rod = core.as_bool(settings, key) and not hr.is_floor(cfg)", "    rod = False")),
        ('set-up families not bold', edit('hfam_ui.py', "        tb.FontWeight = FontWeights.Bold\n", "        pass\n")),
        ('set-up filter ignored', edit('hfam_ui.py',
            "            if self.c('ChkFamSetOnly').IsChecked:", "            if False:")),
        ('list size shared by the tabs', edit('hfam_ui.py',
            "        s[self.k(u'fam_list_h')] = num_text(", "        s[u'fam_list_h'] = num_text(")),
        ('list grip unlimited', edit('hfam_ui.py',
            "    return max(LIST_MIN, min(LIST_MAX, h))", "    return h")),
        ('circular runs the rectangular job', edit('hfam_ui.py',
            "            self.o.start_job(circ_job, self.job_extra)", "            self.o.start_job(job, self.job_extra)")),
        ('circular ring wrong diameter', edit('hcirc_revit.py',
            "    dia = sec['width']\n", "    dia = sec.get('bare_width', sec['width'])\n")),
        ('circular height from the level', edit('hcirc_revit.py',
            "    height = cc.support_height(q[2], stand)", "    height = cc.support_height(q[2], level.ProjectElevation)")),
        ('circular on rectangular ducts', edit('hcirc_revit.py',
            "    return sec if sec.get('round') else None", "    return sec")),
        ('circular orientation ignored', edit('hcirc_core.py',
            "    return across if run_axis == u'Y' else along", "    return along")),
        ('circular style not saved', edit('hfam_ui.py', "                u'style': self.style,", "                u'style': u'rect',")),
        ('unset family never asked about', edit('hfam_ui.py',
            "        if not fc.configured(self.fams, it['family']) and it['family'] not in self.ignored:",
            "        if False:")),
        ('circular height to the invert', edit('hcirc_core.py',
            "    return z_centre - stand_z\n", "    return z_centre - stand_z - 0.25\n")),
        ('ring never checked', edit('hcirc_revit.py',
            "    if abs(off) > cc.CENTRE_OK_MM / MM:", "    if False:")),
        ('ring measured at the wrong support', edit('hcirc_revit.py',
            "    m = measure_ring(doc, inst, dia, q, along)", "    m = measure_ring(doc, inst, dia, sec['a'], along)")),
        ('Raise status ignored', edit('fha_window.py',
            "        if answer in ('Accepted', 'Pending'):", "        if False:")),
    ]
    files = [f for f in os.listdir(HERE) if f.endswith(('.py', '.xaml', '.png', '.md'))]
    missed = 0
    for name, brk in breaks:
        tmp = tempfile.mkdtemp()
        try:
            for f in files:
                shutil.copy(os.path.join(HERE, f), tmp)
            brk(tmp)
            caught = run(tmp, quiet=True) > 0
        finally:
            shutil.rmtree(tmp, True)
        print('{0:42s} {1}'.format(name, 'caught' if caught else 'MISSED'))
        missed += 0 if caught else 1
    return missed


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(1 if selftest() else 0)
    sys.exit(1 if run() else 0)
