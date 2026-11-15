# -*- coding: utf-8 -*-
"""Click to RVT Element - picking on the cloud and reading points out of it.

`PickObject(ObjectType.PointOnElement)` on a point cloud returns a real
scanned point as Reference.GlobalPoint. `PointCloudInstance.GetPoints` with a
six-plane filter returns the points inside a box. Two conventions the API
does not spell out are found at run time rather than assumed: which side of
a filter plane counts as inside, and whether the points come back in the
instance's own space or in global. The debug log says which it was.
"""
import c2r_clr  # noqa: F401  (assembly references first)

from System.Collections.Generic import List
from Autodesk.Revit.DB import XYZ, Plane, PointCloudInstance
from Autodesk.Revit.DB.PointClouds import PointCloudFilterFactory
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter

import c2r_core as core

MM = core.MM_PER_FT


class CloudOnly(ISelectionFilter):
    def AllowElement(self, element):
        return isinstance(element, PointCloudInstance)

    def AllowReference(self, reference, position):
        return True


def is_cancel(exc):
    """Escape during a pick raises Revit's OperationCanceledException."""
    names = [type(exc).__name__]
    try:
        names.append(exc.clsException.GetType().Name)
    except Exception:
        pass
    try:
        names.append(exc.GetType().Name)
    except Exception:
        pass
    return any(u'OperationCanceled' in (n or u'') for n in names)


def pick_point(uidoc, prompt):
    """(PointCloudInstance, (x, y, z) mm) of a clicked scan point."""
    ref = uidoc.Selection.PickObject(ObjectType.PointOnElement, CloudOnly(), prompt)
    inst = uidoc.Document.GetElement(ref.ElementId)
    gp = ref.GlobalPoint
    return inst, (gp.X * MM, gp.Y * MM, gp.Z * MM)


def clouds_in(doc):
    from Autodesk.Revit.DB import FilteredElementCollector
    return list(FilteredElementCollector(doc).OfClass(PointCloudInstance).ToElements())


# conventions found on earlier harvests, per instance unique id
_SEEN = {}


class Harvester(object):
    """Callable `harvest(box, spacing_mm)` over one point cloud instance."""

    def __init__(self, inst, max_points, log):
        self.inst = inst
        self.max_points = int(max_points)
        self.log = log
        self.calls = 0
        self.total = 0
        tr = inst.GetTotalTransform()
        self.inv = tr.Inverse
        self.o = (tr.Origin.X, tr.Origin.Y, tr.Origin.Z)
        self.bx = (tr.BasisX.X, tr.BasisX.Y, tr.BasisX.Z)
        self.by = (tr.BasisY.X, tr.BasisY.Y, tr.BasisY.Z)
        self.bz = (tr.BasisZ.X, tr.BasisZ.Y, tr.BasisZ.Z)
        try:
            self.key = inst.UniqueId
        except Exception:
            self.key = u'cloud'
        seen = _SEEN.get(self.key) or {}
        self.flip = seen.get(u'flip')
        self.space = seen.get(u'space')

    def __call__(self, box, spacing_mm):
        return self.harvest(box, spacing_mm)

    def _filter(self, planes):
        lst = List[Plane]()
        for n, o in planes:
            nn = self.inv.OfVector(XYZ(n[0], n[1], n[2]))
            oo = self.inv.OfPoint(XYZ(o[0] / MM, o[1] / MM, o[2] / MM))
            lst.Add(Plane.CreateByNormalAndOrigin(nn, oo))
        return PointCloudFilterFactory.CreateMultiPlaneFilter(lst)

    def harvest(self, box, spacing_mm):
        self.calls += 1
        planes = core.box_planes(box)
        tries = [self.flip] if self.flip is not None else [False, True]
        for fl in tries:
            pl = core.flip_planes(planes) if fl else planes
            got = self.inst.GetPoints(self._filter(pl), max(1.0, float(spacing_mm)) / MM, self.max_points)
            if got is None or got.Count == 0:
                continue
            out = self._convert(got, box)
            if self.flip is None:
                self.flip = fl
                self._remember()
                self.log(u'harvest: filter planes {0}, points in {1} space'.format(
                    u'flipped' if fl else u'as given', self.space))
            self.total += len(out)
            return out
        return []

    def _remember(self):
        _SEEN[self.key] = {u'flip': self.flip, u'space': self.space}

    def _convert(self, got, box):
        raw = []
        for p in got:
            raw.append((p.X, p.Y, p.Z))
        o = self.o
        bx = self.bx
        by = self.by
        bz = self.bz
        if self.space is None:
            sample = raw[::max(1, len(raw) // 60)]
            as_local = 0
            as_global = 0
            for x, y, z in sample:
                g = ((o[0] + bx[0] * x + by[0] * y + bz[0] * z) * MM,
                     (o[1] + bx[1] * x + by[1] * y + bz[1] * z) * MM,
                     (o[2] + bx[2] * x + by[2] * y + bz[2] * z) * MM)
                if core.in_box(box, g, 50.0):
                    as_local += 1
                if core.in_box(box, (x * MM, y * MM, z * MM), 50.0):
                    as_global += 1
            self.space = u'global' if as_global > as_local else u'instance'
            self._remember()
        if self.space == u'global':
            return [(x * MM, y * MM, z * MM) for x, y, z in raw]
        out = []
        for x, y, z in raw:
            out.append(((o[0] + bx[0] * x + by[0] * y + bz[0] * z) * MM,
                        (o[1] + bx[1] * x + by[1] * y + bz[1] * z) * MM,
                        (o[2] + bx[2] * x + by[2] * y + bz[2] * z) * MM))
        return out
