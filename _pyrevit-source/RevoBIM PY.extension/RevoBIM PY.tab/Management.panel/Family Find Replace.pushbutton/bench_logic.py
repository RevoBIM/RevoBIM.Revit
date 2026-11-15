# -*- coding: utf-8 -*-
"""Logic bench for Family Find & Replace, run under plain CPython.

    python bench_logic.py              run every check against ffr_core.py
    python bench_logic.py --selftest   break each function on purpose and prove
                                       the matching check fails

The functions under test are lifted out of ffr_core.py by name with ast and run
against small stand-ins for XYZ and Transform, so what is tested is the code
that ships rather than a copy of it. A check that still passes once its own
function has been broken is inert, and the selftest says so.

Covers the drafting-view swap of import symbols for detail items: the centre
measured in the block's own axes, the rotation read from it, mirror detection,
the plane a mirrored block is reproduced across, keeping moves in the view's
plane, recognising a drafting view, and how an import is labelled.

From 1.6.1 it also runs the whole centring sequence - measure square, turn,
mirror, work out the move - for detail items of a different size and shape to
the symbol, with origins at a corner and well outside the drawing, and checks
every one lands on the symbol's centre. That is the case that failed in 1.6.0.

From 1.6.2 the default is insertion point to insertion point, as a family swap
does, read from the block's own placement transform. The bench proves that
transform is found first - stepping through a wrapper instance, never into a
block that holds anything besides one other block - that its angle survives the
DWG's unit scaling, and that an item placed on it lands origin on origin at the
block's rotation whatever its shape.

From 1.7.0 it also proves the shrink-to-taskbar drawer in ffr_drawer.py: the
parking and reopening arithmetic, including a second monitor above the primary
one, and the Drawer class itself driven against a stand-in window that behaves
like WPF where a drawer goes wrong - it vetoes a height below MinHeight or
under SizeToContent, ignores assignments while an animation holds them, can
throw on a frame, and runs timer ticks only when pumped, as a dispatcher does.
"""

import ast
import io
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.join(HERE, 'ffr_core.py')
DRAWER = os.path.join(HERE, 'ffr_drawer.py')

WANTED = (
    'fmt', 'plane_angle', 'is_mirrored_in_plane', '_extents_centre',
    'mirror_plane_normal', 'flatten_to_plane', 'is_drafting_view',
    'TypeRecord', 'rotate_in_plane', 'reflect_across', 'centre_from_unrotated',
    'placed_offset', 'box_centre', '_is_instance', 'block_transform',
    'insertion_candidates', 'frame_from_transform', 'angle_gap',
)


# ---------------------------------------------------------------------------
# stand-ins
# ---------------------------------------------------------------------------

class XYZ(object):
    def __init__(self, x, y, z):
        self.X, self.Y, self.Z = float(x), float(y), float(z)

    def Add(self, o):
        return XYZ(self.X + o.X, self.Y + o.Y, self.Z + o.Z)

    def Subtract(self, o):
        return XYZ(self.X - o.X, self.Y - o.Y, self.Z - o.Z)

    def Multiply(self, k):
        return XYZ(self.X * k, self.Y * k, self.Z * k)

    def DotProduct(self, o):
        return self.X * o.X + self.Y * o.Y + self.Z * o.Z

    def CrossProduct(self, o):
        return XYZ(self.Y * o.Z - self.Z * o.Y, self.Z * o.X - self.X * o.Z,
                   self.X * o.Y - self.Y * o.X)

    def GetLength(self):
        return math.sqrt(self.DotProduct(self))

    def Normalize(self):
        return self.Multiply(1.0 / self.GetLength())

    def __repr__(self):
        return '(%.3f, %.3f, %.3f)' % (self.X, self.Y, self.Z)


XYZ.BasisX = XYZ(1, 0, 0)
XYZ.BasisY = XYZ(0, 1, 0)
XYZ.BasisZ = XYZ(0, 0, 1)


class Transform(object):
    """Rotate by a in plan, optionally mirror local Y, then move to origin."""

    def __init__(self, a, mirror, origin):
        c, s = math.cos(a), math.sin(a)
        self.BasisX = XYZ(c, s, 0)
        self.BasisY = XYZ(-s, c, 0).Multiply(-1.0 if mirror else 1.0)
        self.BasisZ = XYZ(0, 0, 1)
        self.Origin = origin

    def OfPoint(self, p):
        return (self.Origin.Add(self.BasisX.Multiply(p.X))
                .Add(self.BasisY.Multiply(p.Y))
                .Add(self.BasisZ.Multiply(p.Z)))

    @property
    def Inverse(self):
        outer = self

        class _Inverse(object):
            def OfPoint(self, p):
                d = p.Subtract(outer.Origin)
                return XYZ(d.DotProduct(outer.BasisX),
                           d.DotProduct(outer.BasisY),
                           d.DotProduct(outer.BasisZ))
        return _Inverse()


class FakeView(object):
    def __init__(self, view_type):
        self.ViewType = view_type


class BrokenView(object):
    @property
    def ViewType(self):
        raise RuntimeError('view went away')


def close(a, b, tol=1.0e-6):
    return a.Subtract(b).GetLength() < tol


def angle_close(a, b, tol=1.0e-6):
    return abs(((a - b + 180.0) % 360.0) - 180.0) < tol


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------

class GenTransform(object):
    """A general affine placement, with Multiply, as Revit's Transform has."""

    def __init__(self, bx, by, bz, origin):
        self.BasisX, self.BasisY, self.BasisZ, self.Origin = bx, by, bz, origin

    @classmethod
    def place(cls, degrees, mirror=False, origin=None, scale=1.0):
        a = math.radians(degrees)
        c, s = math.cos(a), math.sin(a)
        return cls(XYZ(c, s, 0).Multiply(scale),
                   XYZ(-s, c, 0).Multiply(-scale if mirror else scale),
                   XYZ(0, 0, scale), origin or XYZ(0, 0, 0))

    def OfVector(self, v):
        return (self.BasisX.Multiply(v.X).Add(self.BasisY.Multiply(v.Y))
                .Add(self.BasisZ.Multiply(v.Z)))

    def OfPoint(self, p):
        return self.Origin.Add(self.OfVector(p))

    def Multiply(self, other):
        return GenTransform(self.OfVector(other.BasisX),
                            self.OfVector(other.BasisY),
                            self.OfVector(other.BasisZ),
                            self.OfPoint(other.Origin))


class Options(object):
    View = None


class Line2(object):
    """Stands in for a curve - anything that is not an instance."""


class GeoInstance(object):
    def __init__(self, transform, symbol):
        self.Transform = transform
        self._symbol = symbol

    def GetSymbolGeometry(self):
        return list(self._symbol)


class FakeImport(object):
    def __init__(self, geometry, total=None, own=None):
        self._geometry = geometry
        self._total = total
        self._own = own

    def get_Geometry(self, options):
        return list(self._geometry)

    def GetTotalTransform(self):
        return self._total

    def GetTransform(self):
        return self._own


def load(source):
    tree = ast.parse(source)
    ns = {'math': math, 'XYZ': XYZ, 'Options': Options}
    found = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and \
                node.name in WANTED:
            module = ast.Module(body=[node], type_ignores=[])
            exec(compile(module, CORE, 'exec'), ns)
            found.add(node.name)
    missing = set(WANTED) - found
    if missing:
        raise RuntimeError('not found in ffr_core.py: ' + ', '.join(
            sorted(missing)))
    return ns


# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------

#: An L-shaped block with its base point at the corner, as most CAD blocks are.
#: Local extents 0..600 x 0..200, so its true middle is (300, 100) in its own
#: axes - nowhere near the base point.
BLOCK = [XYZ(0, 0, 0), XYZ(600, 0, 0), XYZ(600, 80, 0), XYZ(80, 80, 0),
         XYZ(80, 200, 0), XYZ(0, 200, 0)]
CASES = ((0, False), (30, False), (135, False), (-90, False), (0, True),
         (60, True), (200, True))
RIGHT, UP, NORMAL = XYZ.BasisX, XYZ.BasisY, XYZ.BasisZ


def check_centre(ns):
    """The middle of the block as drawn, at any rotation, mirrored or not."""
    errors = []
    for degrees, mirror in CASES:
        t = Transform(math.radians(degrees), mirror, XYZ(5000, 3000, 0))
        world = [t.OfPoint(p) for p in BLOCK]
        truth = t.OfPoint(XYZ(300, 100, 0))
        got = ns['_extents_centre'](world, t.Inverse, t)
        if got is None or not close(got, truth):
            errors.append('centre at %d deg%s: got %r, true %r' % (
                degrees, ' mirrored' if mirror else '', got, truth))
    return errors


def check_angle(ns):
    errors = []
    for degrees, mirror in CASES:
        t = Transform(math.radians(degrees), mirror, XYZ(0, 0, 0))
        got = math.degrees(ns['plane_angle'](t.BasisX, RIGHT, UP))
        if not angle_close(got, degrees):
            errors.append('angle at %d deg: read %.3f' % (degrees, got))
    return errors


def check_mirror_detect(ns):
    errors = []
    for degrees, mirror in CASES:
        t = Transform(math.radians(degrees), mirror, XYZ(0, 0, 0))
        got = ns['is_mirrored_in_plane'](t.BasisX, t.BasisY, RIGHT, UP)
        if bool(got) != mirror:
            errors.append('mirror at %d deg: read %s, is %s' % (
                degrees, got, mirror))
    return errors


def check_mirror_reproduce(ns):
    """Rotate then mirror across mirror_plane_normal must give the block's axes."""
    errors = []
    for degrees, mirror in CASES:
        if not mirror:
            continue
        t = Transform(math.radians(degrees), True, XYZ(0, 0, 0))
        a = ns['plane_angle'](t.BasisX, RIGHT, UP)
        x_dir = RIGHT.Multiply(math.cos(a)).Add(UP.Multiply(math.sin(a)))
        across = ns['mirror_plane_normal'](NORMAL, x_dir)

        def reflect(v):
            return v.Subtract(across.Multiply(2.0 * v.DotProduct(across)))
        placed_x = XYZ(math.cos(a), math.sin(a), 0)
        placed_y = XYZ(-math.sin(a), math.cos(a), 0)
        if not (close(reflect(placed_x), t.BasisX) and
                close(reflect(placed_y), t.BasisY)):
            errors.append('mirror at %d deg not reproduced' % degrees)
    return errors


def check_flatten(ns):
    errors = []
    got = ns['flatten_to_plane'](XYZ(3, -4, 7), NORMAL)
    if not close(got, XYZ(3, -4, 0)):
        errors.append('flatten kept depth: %r' % got)
    tilted = XYZ(0, 1, 1).Normalize()
    got = ns['flatten_to_plane'](XYZ(2, 5, 1), tilted)
    if abs(got.DotProduct(tilted)) > 1.0e-9:
        errors.append('flatten left a component along a tilted normal')
    return errors


def check_drafting_detect(ns):
    errors = []
    probe = ns['is_drafting_view']
    if probe(FakeView('DraftingView')) is not True:
        errors.append('a drafting view was not recognised')
    for other in ('FloorPlan', 'Section', 'ThreeD', 'Legend', 'Detail'):
        if probe(FakeView(other)):
            errors.append('%s was taken for a drafting view' % other)
    if probe(None) or probe(BrokenView()):
        errors.append('no view, or a failing view, read as drafting')
    return errors


def check_label(ns):
    errors = []
    record = ns['TypeRecord'](1, u'Import symbol', u'LIGHT-01', u'Imports',
                              'Import', 3)
    record.is_import = True
    if record.label != u'LIGHT-01':
        errors.append('import labelled %r' % record.label)
    family = ns['TypeRecord'](2, u'600x600', u'Recessed Light', u'Lighting',
                              'WorkPlaneBased', 3)
    if family.label != u'Recessed Light : 600x600':
        errors.append('family labelled %r' % family.label)
    return errors


def check_rotate(ns):
    errors = []
    for degrees in (0, 30, 90, 135, -60, 200):
        a = math.radians(degrees)
        got = ns['rotate_in_plane'](XYZ(4, 1, 2), a, RIGHT, UP)
        want = Transform(a, False, XYZ(0, 0, 0)).OfPoint(XYZ(4, 1, 2))
        if not close(got, want):
            errors.append('turn by %d deg: got %r, want %r' % (degrees, got,
                                                               want))
    return errors


def check_square_measure(ns):
    """A centre measured with the symbol turned square, turned back."""
    errors = []
    pivot = XYZ(5000, 3000, 0)
    for degrees, mirror in CASES:
        a = math.radians(degrees)
        truth = Transform(a, mirror, pivot).OfPoint(XYZ(300, 100, 0))
        # Turned square, only the mirror is left, so the box middle is here:
        square = Transform(0.0, mirror, pivot).OfPoint(XYZ(300, 100, 0))
        got = ns['centre_from_unrotated'](square, pivot, a, RIGHT, UP)
        if not close(got, truth):
            errors.append('square measure at %d deg%s: got %r, true %r' % (
                degrees, ' mirrored' if mirror else '', got, truth))
    return errors


class Box(object):
    def __init__(self, lo, hi, transform=None):
        self.Min, self.Max = lo, hi
        if transform is not None:
            self.Transform = transform


def check_box_centre(ns):
    errors = []
    plain = Box(XYZ(0, 0, 0), XYZ(10, 4, 0))
    if not close(ns['box_centre'](plain), XYZ(5, 2, 0)):
        errors.append('plain box middle wrong')
    moved = Box(XYZ(0, 0, 0), XYZ(10, 4, 0),
                Transform(math.radians(90), False, XYZ(100, 0, 0)))
    if not close(ns['box_centre'](moved), XYZ(98, 5, 0)):
        errors.append('box with its own transform: got %r' % (
            ns['box_centre'](moved),))
    return errors


#: Detail item families of a different size and shape to the block, given by
#: their own extents. One has its origin at a corner; one has it well outside
#: the drawing, as a family drawn carelessly far from its origin would.
DETAILS = (
    ('400x100, origin at corner', XYZ(0, 0, 0), XYZ(400, 100, 0)),
    ('150x150, origin outside', XYZ(900, -700, 0), XYZ(1050, -550, 0)),
    ('700x40, origin centred', XYZ(-350, -20, 0), XYZ(350, 20, 0)),
)


def check_different_shape(ns):
    """The 1.6.0 failure: a detail item unlike the symbol must still centre.

    Runs the same sequence place_detail_item runs, using its helpers, and works
    out where the item truly ends up from the family's own extents - not from
    anything the code under test computed.
    """
    errors = []
    origin = XYZ(5000, 3000, 0)
    for degrees, mirror in CASES:
        a = math.radians(degrees)
        symbol_centre = Transform(a, mirror, origin).OfPoint(XYZ(300, 100, 0))
        for label, lo, hi in DETAILS:
            local_centre = lo.Add(hi).Multiply(0.5)
            insert = symbol_centre
            # 1. square, the box middle sits at insert + local_centre
            square = insert.Add(local_centre)
            offset = ns['flatten_to_plane'](square.Subtract(insert), NORMAL)
            # 2. turn, then mirror across the turned X line
            placed_x = RIGHT.Multiply(math.cos(a)).Add(UP.Multiply(math.sin(a)))
            across = ns['mirror_plane_normal'](NORMAL, placed_x) \
                if mirror else None
            # 3. the move the code works out
            expected = insert.Add(ns['placed_offset'](offset, a, across, RIGHT,
                                                      UP))
            move = ns['flatten_to_plane'](symbol_centre.Subtract(expected),
                                          NORMAL)
            # where the family's middle truly is after all three
            truth = Transform(a, False, insert).OfPoint(local_centre)
            if mirror:
                d = truth.Subtract(insert)
                truth = insert.Add(d.Subtract(
                    across.Multiply(2.0 * d.DotProduct(across))))
            truth = truth.Add(move)
            gap = truth.Subtract(symbol_centre).GetLength()
            if gap > 1.0e-6:
                errors.append('%s at %d deg%s lands %.1f mm off' % (
                    label, degrees, ' mirrored' if mirror else '', gap))
    return errors


def check_block_transform(ns):
    """The block's placement, found the way the drawing uses it."""
    errors = []
    block = GenTransform.place(37, origin=XYZ(4000, 2500, 0), scale=1 / 304.8)
    wrap = GenTransform.place(0, origin=XYZ(100, -50, 0))
    inner = GenTransform.place(90, origin=XYZ(10, 10, 0))

    got, _depth = ns['block_transform'](
        FakeImport([GeoInstance(block, [Line2(), Line2()])]), None)
    if got is None or not close(got.Origin, block.Origin):
        errors.append('a plain block: insertion point not its own')

    got, depth = ns['block_transform'](
        FakeImport([GeoInstance(wrap, [GeoInstance(block, [Line2()])])]), None)
    want = wrap.Multiply(block)
    if got is None or not close(got.Origin, want.Origin) or \
            not close(got.BasisX, want.BasisX) or depth != 1:
        errors.append('a block inside a wrapper: the two placements were not '
                      'combined')

    got, depth = ns['block_transform'](
        FakeImport([GeoInstance(block, [Line2(),
                                        GeoInstance(inner, [Line2()])])]), None)
    if got is None or not close(got.Origin, block.Origin) or depth != 0:
        errors.append('a block holding lines and a nested block: stepped into '
                      'the nested one')

    got, _depth = ns['block_transform'](
        FakeImport([GeoInstance(block, [Line2()]),
                    GeoInstance(inner, [Line2()])]), None)
    if got is not None:
        errors.append('a whole DWG of two blocks: claimed one insertion point')
    return errors


def check_candidate_order(ns):
    """The block's own placement comes before the import's instance transform.

    The 1.6.0 and 1.6.1 failure: GetTransform was asked first, and for an
    import symbol it can come back with no rotation and the wrong origin.
    """
    errors = []
    block = GenTransform.place(52, origin=XYZ(3200, 1800, 0))
    plain = GenTransform.place(0)
    element = FakeImport([GeoInstance(block, [Line2()])], plain, plain)
    for route, transform in ns['insertion_candidates'](element, None):
        if transform is None:
            continue
        if not close(transform.Origin, block.Origin) or \
                not close(transform.BasisX, block.BasisX):
            errors.append('first answer came from "%s", not the block' % route)
        break
    else:
        errors.append('no route answered')
    return errors


def check_frame_scaled(ns):
    """A DWG's unit scaling must not change the angle or the mirror."""
    errors = []
    for degrees, mirror in CASES:
        t = GenTransform.place(degrees, mirror, XYZ(7, 8, 0), 1 / 304.8)
        origin, angle, mirrored = ns['frame_from_transform'](t, RIGHT, UP)
        if not close(origin, XYZ(7, 8, 0)) or \
                not angle_close(math.degrees(angle), degrees) or \
                bool(mirrored) != mirror:
            errors.append('scaled block at %d deg%s read wrong' % (
                degrees, ' mirrored' if mirror else ''))
    return errors


def check_angle_gap(ns):
    errors = []
    for target, got, want in ((1, 359, 2), (359, 1, -2), (90, 90, 0),
                              (-170, 170, 20), (180, 0, 180)):
        gap = math.degrees(ns['angle_gap'](math.radians(target),
                                           math.radians(got)))
        if abs(gap - want) > 1.0e-6:
            errors.append('gap from %d to %d read %.3f, want %d' % (
                got, target, gap, want))
    return errors


def check_insertion_place(ns):
    """Origin on origin at the block's rotation, whatever the item's shape."""
    errors = []
    for degrees, mirror in CASES:
        block = GenTransform.place(degrees, mirror, XYZ(5000, 3000, 0))
        origin, a, mirrored = ns['frame_from_transform'](block, RIGHT, UP)
        for label, lo, hi in DETAILS:
            # placed at origin, turned about it, mirrored through it
            item = GenTransform.place(math.degrees(a), False, origin)
            if mirrored:
                placed_x = RIGHT.Multiply(math.cos(a)).Add(
                    UP.Multiply(math.sin(a)))
                n = ns['mirror_plane_normal'](NORMAL, placed_x)
                item = GenTransform(
                    ns['reflect_across'](item.BasisX, n),
                    ns['reflect_across'](item.BasisY, n),
                    item.BasisZ, item.Origin)
            # every corner of the family lands where the block's would
            for corner in (lo, hi, XYZ(lo.X, hi.Y, 0)):
                if not close(item.OfPoint(corner), block.OfPoint(corner)):
                    errors.append('%s at %d deg%s: off the block' % (
                        label, degrees, ' mirrored' if mirror else ''))
                    break
    return errors


CHECKS = (
    ('centre in the block\'s own axes', check_centre),
    ('rotation read from the block', check_angle),
    ('mirrored blocks recognised', check_mirror_detect),
    ('mirror reproduced on the detail item', check_mirror_reproduce),
    ('moves kept in the view plane', check_flatten),
    ('drafting view recognised', check_drafting_detect),
    ('imports labelled by block name', check_label),
    ('vectors turned in the view plane', check_rotate),
    ('centre measured square, turned back', check_square_measure),
    ('bounding box honours its transform', check_box_centre),
    ('different size and shape lands centred', check_different_shape),
    ('block placement read from its geometry', check_block_transform),
    ('block placement asked for first', check_candidate_order),
    ('angle survives the DWG unit scaling', check_frame_scaled),
    ('turn left over wrapped to the short way', check_angle_gap),
    ('insertion point to insertion point', check_insertion_place),
)


# ---------------------------------------------------------------------------
# shrink to taskbar: stand-ins
# ---------------------------------------------------------------------------

class Event(object):
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def __isub__(self, handler):
        if handler in self.handlers:
            self.handlers.remove(handler)
        return self

    def fire(self, *args):
        for handler in list(self.handlers):
            handler(*args)


class _Enum(object):
    def __init__(self, **values):
        self.__dict__.update(values)


class Corner(object):
    def __init__(self, *radii):
        if len(radii) == 1:
            radii = radii * 4
        (self.TopLeft, self.TopRight, self.BottomRight,
         self.BottomLeft) = radii


class Pt(object):
    def __init__(self, x, y):
        self.X, self.Y = x, y


class KeyboardStub(object):
    Modifiers = 0


class Args(object):
    def __init__(self, key=None, clicks=1):
        self.Key = key
        self.ClickCount = clicks
        self.Handled = False


class StandInWindow(object):
    """A window that fails the way a WPF one does.

    * A Height below MinHeight is coerced up to MinHeight - the veto.
    * Under any SizeToContent but Manual, Height assignments are ignored.
    * While an animation holds Top or Height, assignments to it are ignored
      until BeginAnimation(prop, None) lets go. It starts held, as a window
      some earlier animation finished on would be.
    * fail_frames makes that many Height assignments throw.
    """

    def __init__(self, left=300.0, top=100.0, width=1180.0, height=880.0,
                 min_height=750.0, size='Manual', owner=None):
        self.Left = left
        self._top = top
        self.Width = width
        self._height = height
        self.MinHeight = min_height
        self.SizeToContent = size
        self.ResizeMode = 'CanResize'
        self.Owner = owner
        self.held = {'Top': True, 'Height': True}
        self.PreviewKeyDown = Event()
        self.Closed = Event()
        self.activated = 0
        self.fail_frames = 0

    def BeginAnimation(self, prop, animation):
        if animation is None:
            self.held[prop] = False

    @property
    def Top(self):
        return self._top

    @Top.setter
    def Top(self, value):
        if not self.held['Top']:
            self._top = float(value)

    @property
    def Height(self):
        return self._height

    @Height.setter
    def Height(self, value):
        if self.fail_frames > 0:
            self.fail_frames -= 1
            raise RuntimeError('a frame failed')
        if self.held['Height'] or self.SizeToContent != 'Manual':
            return
        self._height = max(float(value), float(self.MinHeight))

    @property
    def ActualHeight(self):
        return self._height

    @property
    def ActualWidth(self):
        return self.Width

    def Activate(self):
        self.activated += 1


class Element(object):
    def __init__(self, visibility='Visible', height=40.0):
        self.Visibility = visibility
        self.ActualHeight = height
        self.Height = float('nan')
        self.VerticalAlignment = 'Stretch'
        self.CornerRadius = Corner(5.0, 5.0, 0.0, 0.0)

    def TranslatePoint(self, point, relative_to):
        return Pt(0.0, 1.0)          # inside a 1px window border


class Root(Element):
    def __init__(self, children, height):
        Element.__init__(self, height=height)
        self.Children = children


class StandInButton(object):
    def __init__(self):
        self.Tag = None
        self.ToolTip = None
        self.Click = Event()


class PumpedTimer(object):
    """Ticks only when the test pumps it, as a DispatcherTimer only ticks when
    the dispatcher runs - so an exception thrown in a frame comes out of the
    frame, not out of whatever started the timer."""

    def __init__(self, handler):
        self.handler = handler
        self.running = False
        self.Tick = Event()
        self.Tick += handler

    def Start(self):
        self.running = True

    def Stop(self):
        self.running = False


#: Primary screen, taskbar along the bottom.
AREA = (0.0, 0.0, 1920.0, 1040.0)
#: Header 40 + a 1px border above and below.
BAR = 42.0


class Rig(object):
    """Fresh registries, a clock that moves 20 ms a read, pumped timers."""

    def __init__(self, d, area=AREA):
        self.d = d
        del d['_DRAWERS'][:]
        del d['_PARKED'][:]
        d['Keyboard'].Modifiers = 0
        self.timers = []
        self.area = area
        self._t = [0.0]

    def clock(self):
        self._t[0] += 0.02
        return self._t[0]

    def make_timer(self, milliseconds, handler):
        timer = PumpedTimer(handler)
        self.timers.append(timer)
        return timer

    def window(self, siblings=None, owner=None, can_toggle=None, **kw):
        win = StandInWindow(owner=owner, **kw)
        header = Element(height=40.0)
        body = siblings if siblings is not None else [
            Element('Visible'), Element('Collapsed'), Element('Visible')]
        root = Root([header] + body, win.ActualHeight - 2.0)
        button = StandInButton()
        drawer = self.d['Drawer'](
            win, header, root, button, can_toggle=can_toggle,
            clock=self.clock, make_timer=self.make_timer,
            area_of=lambda w: self.area)
        return drawer, win, header, body, root, button

    def settle(self):
        for _ in range(2000):
            live = [t for t in self.timers if t.running]
            if not live:
                return
            for timer in live:
                timer.handler(None, None)
        raise RuntimeError('a slide never finished')


def load_drawer(source):
    """Run ffr_drawer.py's definitions against stand-ins for WPF."""
    tree = ast.parse(source)
    ns = {
        'time': time,
        'Double': _Enum(NaN=float('nan')),
        'Visibility': _Enum(Visible='Visible', Collapsed='Collapsed',
                            Hidden='Hidden'),
        'VerticalAlignment': _Enum(Top='Top', Stretch='Stretch'),
        'SizeToContent': _Enum(Manual='Manual', Height='Height'),
        'ResizeMode': _Enum(NoResize='NoResize', CanResize='CanResize'),
        'CornerRadius': Corner,
        'Point': Pt,
        'Window': _Enum(TopProperty='Top', HeightProperty='Height'),
        'Key': _Enum(H='H', Escape='Escape', Return='Return'),
        'Keyboard': KeyboardStub,
        'ModifierKeys': _Enum(Control=2, Shift=4),
    }
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Assign)):
            module = ast.Module(body=[node], type_ignores=[])
            exec(compile(module, DRAWER, 'exec'), ns)
    for name in ('Drawer', 'ease_out', 'parked_top', 'stacked_below',
                 'reopen_frame', 'clamp_top', '_DRAWERS', '_PARKED'):
        if name not in ns:
            raise RuntimeError('not found in ffr_drawer.py: ' + name)
    return ns


# ---------------------------------------------------------------------------
# shrink to taskbar: checks
# ---------------------------------------------------------------------------

def check_ease(ns):
    d = ns['drawer']
    errors = []
    ease = d['ease_out']
    if ease(0.0) != 0.0 or ease(1.0) != 1.0:
        errors.append('does not start at 0 and end at 1')
    if abs(ease(0.5) - 0.875) > 1.0e-9:
        errors.append('half way reads %.3f, a cubic ease out is 0.875' %
                      ease(0.5))
    last = -1.0
    for i in range(21):
        value = ease(i / 20.0)
        if value < last:
            errors.append('goes backwards at %.2f' % (i / 20.0))
            break
        last = value
    return errors


def check_stack(ns):
    d = ns['drawer']
    errors = []
    first = d['parked_top'](1040.0, BAR, 0.0)
    if abs(first - (1040.0 - 8.0 - BAR)) > 1.0e-9:
        errors.append('first bar parked at %.1f, want 8px above the taskbar'
                      % first)
    rig = Rig(d)
    one = rig.window(left=100.0)
    two = rig.window(left=900.0)
    one[0].shrink()
    rig.settle()
    two[0].shrink()
    rig.settle()
    if two[1].Top + BAR > one[1].Top - 4.0 + 1.0e-6:
        errors.append('second bar at %.1f overlaps the first at %.1f' % (
            two[1].Top, one[1].Top))
    return errors


def check_second_screen(ns):
    """A monitor above the primary has a negative working-area top."""
    d = ns['drawer']
    errors = []
    if d['clamp_top'](-1200.0, 800.0, -1080.0, -40.0) != -1080.0:
        errors.append('clamp_top on the upper screen did not stop at -1080')
    upper = (0.0, -1080.0, 1920.0, -40.0)
    rig = Rig(d, area=upper)
    drawer, win = rig.window(left=100.0, top=-900.0)[:2]
    drawer.shrink()
    rig.settle()
    if abs(win.Top - (-40.0 - 8.0 - BAR)) > 1.0e-6:
        errors.append('parked at %.1f, not above the upper screen\'s '
                      'taskbar' % win.Top)
    win.Left, win.Top = 50.0, -1075.0          # dragged to the screen's top
    drawer.expand()
    rig.settle()
    if abs(win.Top - (-1080.0)) > 1.0e-6:
        errors.append('reopened at top %.1f - should stay on the upper '
                      'screen at -1080' % win.Top)
    return errors


def check_moved(ns):
    d = ns['drawer']
    errors = []
    saved = (300.0, 100.0, 1180.0, 880.0)
    parked = (300.0, 990.0)
    frame = d['reopen_frame'](saved, 300.0, 990.0, parked, BAR, AREA)
    if frame != (300.0, 100.0):
        errors.append('not moved: reopened at %r, want where it was' % (frame,))
    frame = d['reopen_frame'](saved, 500.0, 950.0, parked, BAR, AREA)
    if frame != (500.0, 950.0 + BAR - 880.0):
        errors.append('moved: reopened at %r, want up from the bar' % (frame,))
    frame = d['reopen_frame'](saved, 1500.0, 950.0, parked, BAR, AREA)
    if frame[0] != 1920.0 - 1180.0:
        errors.append('moved off the right edge: left %.1f, want kept on '
                      'screen' % frame[0])
    rig = Rig(d)
    drawer, win = rig.window()[:2]
    drawer.shrink()
    rig.settle()
    win.Left, win.Top = 500.0, 950.0
    drawer.expand()
    rig.settle()
    if (win.Left, win.Top) != (500.0, 950.0 + BAR - 880.0):
        errors.append('the drawer reopened a dragged bar at (%.1f, %.1f)' % (
            win.Left, win.Top))
    return errors


def check_lands(ns):
    d = ns['drawer']
    errors = []
    rig = Rig(d)
    drawer, win, header, body, root, button = rig.window()
    drawer.shrink()
    rig.settle()
    if drawer.state != 'shrunk':
        errors.append('state %s, want shrunk' % drawer.state)
    if win.Height != BAR:
        errors.append('height %.1f, want the bar, %.1f' % (win.Height, BAR))
    if win.Top != 1040.0 - 8.0 - BAR:
        errors.append('top %.1f, want 8px above the taskbar' % win.Top)
    if [e.Visibility for e in body] != ['Collapsed'] * 3:
        errors.append('body and grips still showing on the bar')
    if button.Tag != 'shrunk':
        errors.append('button Tag %r - it would not turn into the green '
                      'arrow' % button.Tag)
    if win.ResizeMode != 'NoResize':
        errors.append('the bar can still be resized')
    if root.VerticalAlignment != 'Top':
        errors.append('the body was not pinned for the slide')
    if header.CornerRadius.BottomLeft != 5.0:
        errors.append('the bar\'s bottom corners were left square')
    return errors


def check_released(ns):
    d = ns['drawer']
    errors = []
    rig = Rig(d)
    drawer, win = rig.window()[:2]
    drawer.shrink()
    rig.settle()
    for prop in ('Top', 'Height'):
        if win.held[prop]:
            errors.append('%s still held by an animation - the window could '
                          'never be moved or sized again' % prop)
    return errors


def check_relaxed(ns):
    d = ns['drawer']
    errors = []
    rig = Rig(d)
    drawer, win = rig.window(min_height=750.0, size='Height')[:2]
    drawer.shrink()
    rig.settle()
    if win.Height != BAR:
        errors.append('height %.1f after shrinking - MinHeight or '
                      'SizeToContent vetoed the slide' % win.Height)
    drawer.expand()
    rig.settle()
    if win.MinHeight != 750.0 or win.SizeToContent != 'Height':
        errors.append('MinHeight %.0f and SizeToContent %s after reopening - '
                      'not put back' % (win.MinHeight, win.SizeToContent))
    return errors


def check_reopens(ns):
    d = ns['drawer']
    errors = []
    rig = Rig(d)
    drawer, win, header, body, root, button = rig.window()
    drawer.shrink()
    rig.settle()
    drawer.expand()
    rig.settle()
    if drawer.state != 'open':
        errors.append('state %s, want open' % drawer.state)
    if (win.Left, win.Top, win.Height) != (300.0, 100.0, 880.0):
        errors.append('reopened at (%.1f, %.1f) %.1f high, want where it was'
                      % (win.Left, win.Top, win.Height))
    if [e.Visibility for e in body] != ['Visible', 'Collapsed', 'Visible']:
        errors.append('body shown as %r, want as it was' % (
            [e.Visibility for e in body],))
    if root.VerticalAlignment != 'Stretch' or root.Height == root.Height:
        errors.append('body left pinned - it would not stretch with the '
                      'window')
    if win.ResizeMode != 'CanResize' or button.Tag != '' or \
            header.CornerRadius.BottomLeft != 0.0:
        errors.append('resize, button or header corners not put back')
    if not win.activated:
        errors.append('not activated once open')
    return errors


def check_owner(ns):
    d = ns['drawer']
    errors = []
    rig = Rig(d)
    main, main_win = rig.window()[:2]
    dialog, dialog_win = rig.window(owner=main_win, left=400.0, top=300.0,
                                    width=520.0, height=300.0,
                                    min_height=0.0, size='Height')[:2]
    dialog.shrink()
    rig.settle()
    if main.state != 'shrunk':
        errors.append('the main window was left standing over Revit')
    elif not main_win.Top > dialog_win.Top:
        errors.append('the dialog\'s bar is not above the main window\'s')
    dialog.expand()
    rig.settle()
    if main.state != 'open' or main_win.Height != 880.0:
        errors.append('opening the dialog did not bring the main window back')
    dialog.shrink()
    rig.settle()
    dialog_win.Closed.fire(None, None)
    rig.settle()
    if main.state != 'open':
        errors.append('closing a parked dialog left the main window parked')
    return errors


def check_carried(ns):
    d = ns['drawer']
    errors = []
    rig = Rig(d)
    main, main_win = rig.window()[:2]
    child, child_win = rig.window(owner=main_win, left=500.0, top=200.0,
                                  width=460.0, height=400.0,
                                  min_height=0.0)[:2]
    main.shrink()
    rig.settle()
    if child.state != 'shrunk':
        errors.append('an open dialog was left standing over Revit')
    elif not child_win.Top < main_win.Top:
        errors.append('the dialog\'s bar is not stacked above the main one')
    main.expand()
    rig.settle()
    if child.state != 'open':
        errors.append('the dialog did not come back with the main window')
    return errors


def check_keys(ns):
    d = ns['drawer']
    errors = []
    rig = Rig(d)
    drawer, win = rig.window()[:2]
    args = Args('Escape')
    win.PreviewKeyDown.fire(None, args)
    if args.Handled:
        errors.append('Escape swallowed on an open window')
    d['Keyboard'].Modifiers = 2 | 4
    args = Args('H')
    win.PreviewKeyDown.fire(None, args)
    rig.settle()
    d['Keyboard'].Modifiers = 0
    if drawer.state != 'shrunk' or not args.Handled:
        errors.append('Ctrl+Shift+H did not shrink the window')
    for key in ('Escape', 'Return'):
        if drawer.state != 'shrunk':
            drawer.shrink()
            rig.settle()
        args = Args(key)
        win.PreviewKeyDown.fire(None, args)
        rig.settle()
        if drawer.state != 'open' or not args.Handled:
            errors.append('%s on the parked bar did not reopen it' % key)
    return errors


def check_double_click(ns):
    d = ns['drawer']
    errors = []
    rig = Rig(d)
    drawer = rig.window()[0]
    if drawer.on_header_down(Args(clicks=2)):
        errors.append('took a double click on an open window')
    drawer.shrink()
    rig.settle()
    if drawer.on_header_down(Args(clicks=1)) or drawer.state != 'shrunk':
        errors.append('a single click on the bar did more than drag')
    if not drawer.on_header_down(Args(clicks=2)):
        errors.append('a double click on the bar did not reopen it')
    rig.settle()
    if drawer.state != 'open':
        errors.append('state %s after the double click' % drawer.state)
    return errors


def check_failing_frame(ns):
    d = ns['drawer']
    errors = []
    rig = Rig(d)
    drawer, win = rig.window()[:2]
    win.fail_frames = 1
    drawer.shrink()
    rig.settle()
    if drawer.state != 'shrunk' or win.Height != BAR:
        errors.append('a frame that threw left it %s at %.1f high' % (
            drawer.state, win.Height))
    return errors


def check_busy(ns):
    d = ns['drawer']
    errors = []
    rig = Rig(d)
    busy = [True]
    drawer, win, header, body, root, button = rig.window(
        can_toggle=lambda: not busy[0])
    button.Click.fire(None, None)
    rig.settle()
    if drawer.state != 'open':
        errors.append('slid away while a run was going')
    busy[0] = False
    button.Click.fire(None, None)
    rig.settle()
    if drawer.state != 'shrunk':
        errors.append('the button did nothing once the run was over')
    return errors


DRAWER_CHECKS = (
    ('slide eases out', check_ease),
    ('bars park clear of the taskbar and stack', check_stack),
    ('second screen above the primary', check_second_screen),
    ('dragged bar opens upward from where it sits', check_moved),
    ('shrinks to a bar', check_lands),
    ('animation released', check_released),
    ('MinHeight and SizeToContent relaxed', check_relaxed),
    ('reopens exactly as it was', check_reopens),
    ('a dialog takes its owner down first', check_owner),
    ('a window takes its dialogs with it', check_carried),
    ('parked keys reopen', check_keys),
    ('double click on the bar reopens', check_double_click),
    ('a failing frame lands at the end', check_failing_frame),
    ('held while a run is going', check_busy),
)


def run(sources, quiet=False):
    try:
        ns = load(sources['core'])
        ns['drawer'] = load_drawer(sources['drawer'])
    except Exception as err:
        return [('loading', [str(err)])]
    failed = []
    for name, check in CHECKS + DRAWER_CHECKS:
        try:
            errors = check(ns)
        except Exception as err:
            errors = ['raised %s: %s' % (type(err).__name__, err)]
        if errors:
            failed.append((name, errors))
        if not quiet:
            print('  %-40s %s' % (name, 'FAIL' if errors else 'ok'))
            for line in errors[:4]:
                print('      ' + line)
    return failed


# ---------------------------------------------------------------------------
# selftest: each break must be caught by the check named beside it
# ---------------------------------------------------------------------------

BREAKS = (
    ('centre measured in world axes',
     'q = to_local.OfPoint(point) if to_local is not None else point',
     'q = point',
     'centre in the block\'s own axes'),
    ('rotation axes swapped',
     'return math.atan2(y, x)',
     'return math.atan2(x, y)',
     'rotation read from the block'),
    ('mirror test inverted',
     'return (ax * by - ay * bx) < 0.0',
     'return (ax * by - ay * bx) > 0.0',
     'mirrored blocks recognised'),
    ('mirrored across the wrong axis',
     'return view_normal.CrossProduct(x_dir).Normalize()',
     'return x_dir.Normalize()',
     'mirror reproduced on the detail item'),
    ('move allowed out of the view plane',
     'return vector.Subtract(normal.Multiply(vector.DotProduct(normal)))',
     'return vector',
     'moves kept in the view plane'),
    ('drafting view misnamed',
     "str(view.ViewType) == 'DraftingView'",
     "str(view.ViewType) == 'Drafting'",
     'drafting view recognised'),
    ('import label falls back to family : type',
     'if self.is_import:\n            return self.family_name',
     'if False:\n            return self.family_name',
     'imports labelled by block name'),
    ('turned the wrong way',
     'up.Multiply(x * s + y * c)',
     'up.Multiply(-x * s + y * c)',
     'vectors turned in the view plane'),
    ('square centre turned back the wrong way',
     'return pivot.Add(rotate_in_plane(square_centre.Subtract(pivot), angle,',
     'return pivot.Add(rotate_in_plane(square_centre.Subtract(pivot), -angle,',
     'centre measured square, turned back'),
    ('box transform ignored',
     'return transform.OfPoint(middle)',
     'return middle',
     'bounding box honours its transform'),
    ('offset not turned with the item',
     'moved = rotate_in_plane(offset, angle, right, up)',
     'moved = offset',
     'different size and shape lands centred'),
    ('mirror left out of the worked-out move',
     'moved = reflect_across(moved, mirror_normal)',
     'moved = moved',
     'different size and shape lands centred'),
    ('wrapper placement dropped',
     'transform = transform.Multiply(inner[0].Transform)',
     'transform = inner[0].Transform',
     'block placement read from its geometry'),
    ('stepped into a block holding other things',
     'if len(inner) != 1 or not _is_instance(inner[0]):',
     'if not _is_instance(inner[-1]):\n            break\n        inner = [inner[-1]]\n        if False:',
     'block placement read from its geometry'),
    ('instance transform asked first (the 1.6.1 bug)',
     'transform, depth = block_transform(element, view)',
     'transform, depth = None, 0',
     'block placement asked for first'),
    ('turn left over not wrapped',
     'gap += 2.0 * math.pi',
     'gap += 0.0',
     'turn left over wrapped to the short way'),
    ('placed mirrored the wrong way',
     'return view_normal.CrossProduct(x_dir).Normalize()',
     'return x_dir.Normalize()',
     'insertion point to insertion point'),
)


DRAWER_BREAKS = (
    ('slide eased linearly',
     'return 1.0 - (1.0 - progress) ** 3',
     'return progress',
     'slide eases out'),
    ('parked bars stacked on top of each other',
     'return area_bottom - margin - below - bar',
     'return area_bottom - margin - bar',
     'bars park clear of the taskbar and stack'),
    ('clamped to zero, not to the screen',
     '    if top < area_top:\n        top = area_top',
     '    if top < 0.0:\n        top = 0.0',
     'second screen above the primary'),
    ('dragged bar jumps back home',
     'if not was_moved(now_left, now_top, parked[0], parked[1], tol):',
     'if True:',
     'dragged bar opens upward from where it sits'),
    ('height animation never released',
     'self.window.BeginAnimation(Window.HeightProperty, None)',
     'pass',
     'animation released'),
    ('MinHeight left to veto the slide',
     'window.MinHeight = 0.0',
     'pass',
     'MinHeight and SizeToContent relaxed'),
    ('SizeToContent left to veto the slide',
     'window.SizeToContent = SizeToContent.Manual',
     'pass',
     'MinHeight and SizeToContent relaxed'),
    ('grips and body left showing on the bar',
     'element.Visibility = Visibility.Collapsed',
     'pass',
     'shrinks to a bar'),
    ('button never turns into the green arrow',
     "self.button.Tag = SHRUNK_TAG if shrunk else ''",
     "self.button.Tag = ''",
     'shrinks to a bar'),
    ('body shown however it was before',
     'element.Visibility = visibility',
     'element.Visibility = Visibility.Visible',
     'reopens exactly as it was'),
    ('body left pinned after reopening',
     '        self._unpin()\n',
     '',
     'reopens exactly as it was'),
    ('dialog leaves its owner standing',
     'if owner.shrink(animate=False, lift=True):',
     'if False:',
     'a dialog takes its owner down first'),
    ('closing a dialog leaves its owner parked',
     "        if lifted is not None and lifted.state == 'shrunk':\n"
     "            lifted.expand()",
     '        pass',
     'a dialog takes its owner down first'),
    ('open dialogs left standing over Revit',
     'child.shrink(animate=False,',
     'False and child.shrink(animate=False,',
     'a window takes its dialogs with it'),
    ('Esc and Enter answer a parked window',
     'if key in (Key.Escape, Key.Return):',
     'if False:',
     'parked keys reopen'),
    ('double click on the bar ignored',
     'if clicks < 2:',
     'if True:',
     'double click on the bar reopens'),
    ('a failing frame stops it half way',
     '            # A frame that throws lands the window at the end, rather '
     'than\n'
     '            # leaving it stopped half way with the timer still running.\n'
     '            self._finish()',
     '            raise',
     'a failing frame lands at the end'),
    ('slides while a run is going',
     '        if self.can_toggle is None:\n            return True',
     '        if True:\n            return True',
     'held while a run is going'),
)


def selftest(sources):
    problems = 0
    if run(sources, quiet=True):
        print('  the unbroken source fails - fix that first')
        return 1
    for target, breaks in (('core', BREAKS), ('drawer', DRAWER_BREAKS)):
        for label, old, new, expect in breaks:
            count = sources[target].count(old)
            if count != 1:
                print('  %-42s STALE - the text to break appears %d times' % (
                    label, count))
                problems += 1
                continue
            broken = dict(sources)
            broken[target] = sources[target].replace(old, new)
            failed = dict(run(broken, quiet=True))
            if expect in failed:
                print('  %-42s caught by "%s"' % (label, expect))
            else:
                print('  %-42s NOT CAUGHT - "%s" passed anyway' % (label,
                                                                  expect))
                problems += 1
    return problems


def main():
    sources = {'core': io.open(CORE, encoding='utf-8').read(),
               'drawer': io.open(DRAWER, encoding='utf-8').read()}
    if '--selftest' in sys.argv:
        print('selftest - each deliberate break must be caught:')
        problems = selftest(sources)
        print('%d problem(s)' % problems)
        return 1 if problems else 0
    print('logic bench:')
    failed = run(sources)
    print('%d check(s) failed' % len(failed) if failed
          else 'All logic checks passed.')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
