# -*- coding: utf-8 -*-
"""Find in View - bench test of the rules themselves.

    python bench_logic.py
    python bench_logic.py --selftest

The Revit API is stubbed and only the collector is replaced, so the rules under
test are the real shipped code: the filter rule, the scan's hit counting, the
view type decisions, the zoom arithmetic and the settings round trip.
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import import_check  # noqa: E402 - it owns the stub API

import_check.install_stubs()

import fiv_core   # noqa: E402
import fiv_model  # noqa: E402


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------

class FakeId(object):
    def __init__(self, value):
        self.Value = value

    def __eq__(self, other):
        return isinstance(other, FakeId) and other.Value == self.Value

    def __hash__(self):
        return hash(self.Value)


class FakeCategory(object):
    def __init__(self, name, value):
        self.Name = name
        self.Id = FakeId(value)


class FakeElement(object):
    def __init__(self, value, category, box=None):
        self.Id = FakeId(value)
        self.Category = category
        self._box = box

    def get_BoundingBox(self, view):
        return self._box


class FakeBox(object):
    def __init__(self, low, high):
        self.Min = FakePoint(low)
        self.Max = FakePoint(high)
        self.Transform = None


class FakePoint(object):
    def __init__(self, values):
        self.X, self.Y, self.Z = values


class FakeView(object):
    def __init__(self, name, view_type, value, scale=100, template=False):
        self.Name = name
        self.ViewType = view_type
        self.Id = FakeId(value)
        self.Scale = scale
        self.IsTemplate = template


def make_row(name, type_label, sheet=''):
    view = FakeView(name, 'FloorPlan', 1)
    row = fiv_model.ViewRow.__new__(fiv_model.ViewRow)
    row.view = view
    row.view_id = view.Id
    row.name = name
    row.type_label = type_label
    row.scale = '1:100'
    row.sheet = sheet
    row.discipline = ''
    row.sort_index = 0
    return row


# ---------------------------------------------------------------------------
# the bench
# ---------------------------------------------------------------------------

CHECKS = []


def check(label):
    def wrap(function):
        CHECKS.append((label, function))
        return function
    return wrap


def expect(condition, message):
    if not condition:
        raise AssertionError(message)


# --------------------------------------------------------------- view listing

@check('a floor plan is listable')
def _():
    expect(fiv_model.is_listable(FakeView('L1', 'FloorPlan', 1)), 'floor plan refused')


@check('a 3D view is listable')
def _():
    expect(fiv_model.is_listable(FakeView('3D', 'ThreeD', 2)), '3D view refused')


@check('a drafting view is not listed')
def _():
    expect(not fiv_model.is_listable(FakeView('Det', 'DraftingView', 3)),
           'a drafting view cannot show model elements')


@check('a schedule is not listed')
def _():
    expect(not fiv_model.is_listable(FakeView('Sched', 'Schedule', 4)), 'schedule listed')


@check('a legend is not listed')
def _():
    expect(not fiv_model.is_listable(FakeView('Leg', 'Legend', 5)), 'legend listed')


@check('a view template is not listed')
def _():
    expect(not fiv_model.is_listable(FakeView('T', 'FloorPlan', 6, template=True)),
           'view template listed')


@check('view types read out in house wording')
def _():
    expect(fiv_model.view_type_label(FakeView('a', 'CeilingPlan', 1)) == 'Ceiling Plan',
           'ceiling plan mislabelled')
    expect(fiv_model.view_type_label(FakeView('a', 'ThreeD', 1)) == '3D View',
           'ThreeD should read as 3D View')
    expect(fiv_model.view_type_label(FakeView('a', 'EngineeringPlan', 1)) == 'Structural Plan',
           'engineering plan mislabelled')


@check('the view type list follows the house order, not the model order')
def _():
    rows = [make_row('a', '3D View'), make_row('b', 'Floor Plan'), make_row('c', 'Section')]
    present = fiv_model.view_types_present(rows)
    expect(present == ['Floor Plan', 'Section', '3D View'],
           'unexpected order: {0}'.format(present))


@check('a view type present twice appears once')
def _():
    rows = [make_row('a', 'Floor Plan'), make_row('b', 'Floor Plan')]
    expect(fiv_model.view_types_present(rows) == ['Floor Plan'], 'duplicated type')


@check('a scale reads as 1:n')
def _():
    expect(fiv_model.scale_text(FakeView('a', 'FloorPlan', 1, scale=50)) == '1:50',
           'scale mislabelled')


# ---------------------------------------------------------------- filter rule

TICKED = ['Floor Plan', 'Section']


def passes(row, query='', ticked=None):
    return fiv_model.passes_filters(row, ticked or TICKED, query)


@check('an unticked view type is filtered out')
def _():
    expect(not passes(make_row('3D', '3D View')), '3D view survived')


@check('a ticked view type survives')
def _():
    expect(passes(make_row('L1', 'Floor Plan')), 'floor plan filtered out')


@check('the keyword search matches the view name')
def _():
    expect(passes(make_row('L01 Ground Power', 'Floor Plan'), query='power'),
           'search missed the name')


@check('the keyword search is case insensitive and order independent')
def _():
    expect(passes(make_row('L01 Ground Power', 'Floor Plan'), query='POWER ground'),
           'search should not care about case or order')


@check('every word in the search has to match')
def _():
    expect(not passes(make_row('L01 Ground Power', 'Floor Plan'), query='power lighting'),
           'a word that does not match should filter the row out')


@check('the search also looks at the sheet and the type')
def _():
    row = make_row('L01', 'Floor Plan', sheet='E-101')
    expect(passes(row, query='E-101'), 'sheet not searched')
    expect(passes(row, query='floor'), 'type not searched')


@check('the filters compound rather than override each other')
def _():
    row = make_row('L01 Power', 'Floor Plan', sheet='E-101')
    expect(passes(row, query='power'), 'a row meeting every filter was dropped')
    expect(not passes(row, query='lighting'), 'the search should still bite')
    expect(not passes(row, query='power', ticked=['Section']),
           'the view type should still bite')


@check('the filter rule reads nothing off the document')
def _():
    row = make_row('L1', 'Floor Plan')
    row.view = None
    expect(passes(row), 'the filter rule touched the view')


# ------------------------------------------------------------ zoom arithmetic

@check('the padded box grows by a percentage of its own extent')
def _():
    low, high = fiv_core.padded_box((0, 0, 0), (10, 10, 10), 25, 0)
    expect(low == (-2.5, -2.5, -2.5) and high == (12.5, 12.5, 12.5),
           'got {0} {1}'.format(low, high))


@check('a single point still produces a box Revit will accept')
def _():
    low, high = fiv_core.padded_box((5, 5, 5), (5, 5, 5), 25, 1.0)
    expect(high[0] - low[0] == 2.0, 'a degenerate box was not opened out')


@check('the minimum padding wins over a small percentage')
def _():
    low, high = fiv_core.padded_box((0, 0, 0), (1, 1, 1), 10, 0.5)
    expect(low[0] == -0.5 and high[0] == 1.5, 'the floor padding was ignored')


@check('the padding is per axis, so a long thin run is not distorted')
def _():
    low, high = fiv_core.padded_box((0, 0, 0), (100, 2, 2), 10, 0)
    expect(high[0] - low[0] == 120.0, 'the long axis is wrong')
    expect(abs((high[1] - low[1]) - 2.4) < 1e-9, 'the short axis is wrong')


@check('the zoom rectangle spans a plan view correctly')
def _():
    origin = (0.0, 0.0, 0.0)
    right, up, normal = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)
    low, high = fiv_core.zoom_rectangle((0, 0, 0), (10, 4, 3), origin, right, up,
                                        normal, 0, 0)
    expect(low[0] == 0 and high[0] == 10, 'the width is wrong')
    expect(low[1] == 0 and high[1] == 4, 'the height is wrong')


@check('the zoom rectangle covers every corner on a view cut at an angle')
def _():
    # a section looking along 45 degrees: two opposite corners of a model
    # aligned box project WELL INSIDE the real extent, which is the bug
    root = 2.0 ** 0.5 / 2.0
    origin = (0.0, 0.0, 0.0)
    right = (root, -root, 0.0)
    up = (0.0, 0.0, 1.0)
    normal = (root, root, 0.0)
    box_low, box_high = (0.0, 0.0, 0.0), (10.0, 10.0, 3.0)

    low, high = fiv_core.zoom_rectangle(box_low, box_high, origin, right, up,
                                        normal, 0, 0)

    # every corner of the box has to land inside the rectangle, in the view's
    # own frame, or the zoom cuts the selection off
    rect = [fiv_core.to_frame(low, origin, right, up, normal),
            fiv_core.to_frame(high, origin, right, up, normal)]
    for corner in fiv_core.box_corners(box_low, box_high):
        seen = fiv_core.to_frame(corner, origin, right, up, normal)
        for axis in (0, 1):
            span_low = min(rect[0][axis], rect[1][axis])
            span_high = max(rect[0][axis], rect[1][axis])
            expect(span_low - 1e-9 <= seen[axis] <= span_high + 1e-9,
                   'corner {0} falls outside the rectangle on axis {1}'.format(
                       corner, axis))


@check('two opposite corners alone would not have covered it')
def _():
    """The check above only means something if the old way really failed."""
    root = 2.0 ** 0.5 / 2.0
    origin = (0.0, 0.0, 0.0)
    right = (root, -root, 0.0)
    up = (0.0, 0.0, 1.0)
    normal = (root, root, 0.0)
    naive = [fiv_core.to_frame((0.0, 0.0, 0.0), origin, right, up, normal),
             fiv_core.to_frame((10.0, 10.0, 3.0), origin, right, up, normal)]
    span = abs(naive[1][0] - naive[0][0])
    proper = fiv_core.zoom_rectangle((0.0, 0.0, 0.0), (10.0, 10.0, 3.0), origin,
                                     right, up, normal, 0, 0)
    real = abs(fiv_core.to_frame(proper[1], origin, right, up, normal)[0] -
               fiv_core.to_frame(proper[0], origin, right, up, normal)[0])
    expect(real > span + 1.0,
           'the two corner rectangle was {0} wide against the real {1}'.format(
               span, real))


@check('a point round trips through the view frame and back')
def _():
    origin = (3.0, -2.0, 1.5)
    root = 2.0 ** 0.5 / 2.0
    right, up, normal = (root, root, 0.0), (0.0, 0.0, 1.0), (root, -root, 0.0)
    point = (7.0, 4.0, 2.0)
    there = fiv_core.to_frame(point, origin, right, up, normal)
    back = fiv_core.from_frame(there, origin, right, up, normal)
    for axis in range(3):
        expect(abs(back[axis] - point[axis]) < 1e-9,
               'the round trip lost the point: {0}'.format(back))


@check('the zoom padding is a share of what is on screen, not of the model box')
def _():
    origin = (0.0, 0.0, 0.0)
    right, up, normal = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)
    low, high = fiv_core.zoom_rectangle((0, 0, 0), (10, 10, 100), origin, right,
                                        up, normal, 10, 0)
    expect(abs((high[0] - low[0]) - 12.0) < 1e-9,
           'the on screen width should have grown by a tenth, got {0}'.format(
               high[0] - low[0]))


@check('a box has eight corners, not two')
def _():
    corners = fiv_core.box_corners((0, 0, 0), (1, 1, 1))
    expect(len(set(corners)) == 8, 'got {0} distinct corners'.format(len(set(corners))))


@check('boxes union across every axis')
def _():
    box = fiv_core.union_box([((0, 0, 0), (1, 1, 1)), ((-5, 2, 0), (2, 3, 9))])
    expect(box == ((-5, 0, 0), (2, 3, 9)), 'got {0}'.format(box))


@check('a union of nothing is nothing, not a zero box')
def _():
    expect(fiv_core.union_box([]) is None, 'an empty union should be None')
    expect(fiv_core.union_box([None, None]) is None, 'None entries should be dropped')


@check('millimetres convert to feet')
def _():
    expect(abs(fiv_core.mm_to_feet(304.8) - 1.0) < 1e-9, 'mm to feet is wrong')


@check('the element box is the union of the elements own boxes')
def _():
    elements = [FakeElement(1, None, FakeBox((0, 0, 0), (1, 1, 1))),
                FakeElement(2, None, FakeBox((4, 4, 0), (5, 5, 2)))]
    box = fiv_model.elements_box(elements)
    expect(box == ((0, 0, 0), (5, 5, 2)), 'got {0}'.format(box))


@check('an element with no geometry is left out rather than zeroing the box')
def _():
    elements = [FakeElement(1, None, FakeBox((2, 2, 0), (3, 3, 1))),
                FakeElement(2, None, None)]
    box = fiv_model.elements_box(elements)
    expect(box == ((2, 2, 0), (3, 3, 1)), 'got {0}'.format(box))


@check('nothing with geometry at all gives no box, so the zoom is skipped')
def _():
    expect(fiv_model.elements_box([FakeElement(1, None, None)]) is None,
           'a box was invented from nothing')


# -------------------------------------------------------------------- tiling

def rect(view_id, left, top, right, bottom):
    return (view_id, left, top, right, bottom)


TILED = [rect(1, 0, 0, 960, 1000), rect(2, 960, 0, 1920, 1000)]
STACKED = [rect(1, 0, 0, 1920, 1000), rect(2, 0, 0, 1920, 1000)]


@check('two windows side by side read as tiled')
def _():
    expect(fiv_core.looks_tiled(TILED), 'a tiled pair was not recognised')


@check('maximised or tabbed windows do not read as tiled')
def _():
    expect(not fiv_core.looks_tiled(STACKED),
           'windows on top of each other are not tiled, whatever their number')


@check('one window on its own is not tiled')
def _():
    expect(not fiv_core.looks_tiled([rect(1, 0, 0, 1920, 1000)]), 'one window is not a tiling')
    expect(not fiv_core.looks_tiled([]), 'no windows is not a tiling')


@check('windows that just touch at the edge still read as tiled')
def _():
    pair = [rect(1, 0, 0, 960, 1000), rect(2, 960, 0, 1920, 1000)]
    expect(fiv_core.overlap_ratio(pair[0], pair[1]) == 0.0, 'a shared edge is not an overlap')


@check('a small overlap is tolerated, a large one is not')
def _():
    nearly = [rect(1, 0, 0, 1000, 1000), rect(2, 950, 0, 1950, 1000)]
    expect(fiv_core.looks_tiled(nearly), 'a 5% overlap should still read as tiled')
    heavy = [rect(1, 0, 0, 1000, 1000), rect(2, 400, 0, 1400, 1000)]
    expect(not fiv_core.looks_tiled(heavy), 'a 60% overlap is not a tiling')


@check('three tiles still read as tiled')
def _():
    three = [rect(1, 0, 0, 640, 1000), rect(2, 640, 0, 1280, 1000),
             rect(3, 1280, 0, 1920, 1000)]
    expect(fiv_core.looks_tiled(three), 'three tiles were not recognised')


@check('the tile reused is the top left one that is not the host')
def _():
    rects = [rect(1, 0, 0, 640, 500),      # host, top left
             rect(3, 640, 0, 1280, 500),   # top middle
             rect(4, 0, 500, 640, 1000)]   # bottom left
    expect(fiv_core.pick_tile_to_reuse(rects, 1, 9) == 3,
           'the tile read down the page then across is wrong')


@check('the host tile is never the one reused')
def _():
    rects = [rect(1, 0, 0, 640, 500), rect(3, 640, 0, 1280, 500)]
    expect(fiv_core.pick_tile_to_reuse(rects, 1, 9) == 3, 'the host was taken over')


@check('the view being opened is never the tile reused')
def _():
    rects = [rect(1, 0, 0, 640, 500), rect(9, 640, 0, 1280, 500)]
    expect(fiv_core.pick_tile_to_reuse(rects, 1, 9) is None,
           'the target view would have been closed to make room for itself')


@check('a host on its own leaves no tile to reuse')
def _():
    expect(fiv_core.pick_tile_to_reuse([rect(1, 0, 0, 1920, 1000)], 1, 9) is None,
           'there is nothing to take over')


@check('tiling off leaves the windows alone')
def _():
    to_close, mode = fiv_model.plan_tiling(TILED, 1, 9, {'open_tiled': '0'})
    expect(to_close is None and mode == fiv_core.TILE_NEVER,
           'the layout was touched with tiling off')


@check('Tile Views is used when the view you came from is the only one open')
def _():
    to_close, mode = fiv_model.plan_tiling([rect(1, 0, 0, 1920, 1000)], 1, 9,
                                           {'open_tiled': '1'})
    expect(to_close is None, 'the only open window was closed')
    expect(mode == fiv_core.TILE_ALWAYS, 'one window on its own has to be tiled')


@check('Tile Views is used when nothing at all is open')
def _():
    to_close, mode = fiv_model.plan_tiling([], 1, 9, {'open_tiled': '1'})
    expect(mode == fiv_core.TILE_ALWAYS, 'there is nothing to open into')


@check('Tile Views is never used once a second view is open')
def _():
    for rects in (TILED, STACKED,
                  [rect(1, 0, 0, 640, 500), rect(3, 640, 0, 1280, 500),
                   rect(4, 0, 500, 640, 1000)]):
        to_close, mode = fiv_model.plan_tiling(rects, 1, 9, {'open_tiled': '1'})
        expect(mode != fiv_core.TILE_ALWAYS,
               'an arrangement the user made must not be re-tiled')


@check('a tiled layout has its first other tile taken over, and is not re-tiled')
def _():
    rects = [rect(1, 0, 0, 640, 500), rect(3, 640, 0, 1280, 500)]
    to_close, mode = fiv_model.plan_tiling(rects, 1, 9,
                                           {'open_tiled': '1', 'reuse_tile': '1'})
    expect(to_close == 3, 'the first other tile was not taken over')
    expect(mode == fiv_core.TILE_NEVER, 'the layout was re-tiled anyway')


@check('reuse off adds a view without closing or tiling anything')
def _():
    rects = [rect(1, 0, 0, 640, 500), rect(3, 640, 0, 1280, 500)]
    to_close, mode = fiv_model.plan_tiling(rects, 1, 9,
                                           {'open_tiled': '1', 'reuse_tile': '0'})
    expect(to_close is None, 'a window was closed with reuse off')
    expect(mode == fiv_core.TILE_NEVER, 'the layout was re-tiled anyway')


@check('a stack of windows is opened into, not tiled or closed')
def _():
    to_close, mode = fiv_model.plan_tiling(STACKED, 1, 9,
                                           {'open_tiled': '1', 'reuse_tile': '1'})
    expect(to_close is None, 'a tabbed or stacked window was closed')
    expect(mode == fiv_core.TILE_NEVER, 'a stack is still the user\'s layout')


@check('a view already open is brought forward, untouched')
def _():
    rects = [rect(1, 0, 0, 640, 500), rect(9, 640, 0, 1280, 500)]
    to_close, mode = fiv_model.plan_tiling(rects, 1, 9,
                                           {'open_tiled': '1', 'reuse_tile': '1'})
    expect(to_close is None, 'a window was closed for no reason')
    expect(mode == fiv_core.TILE_NEVER, 'nothing needed tiling')


@check('an already open view is never closed to make room for itself')
def _():
    rects = [rect(1, 0, 0, 640, 500), rect(9, 640, 0, 1280, 500),
             rect(3, 0, 500, 640, 1000)]
    to_close, mode = fiv_model.plan_tiling(rects, 1, 9,
                                           {'open_tiled': '1', 'reuse_tile': '1'})
    expect(to_close is None and mode == fiv_core.TILE_NEVER,
           'the target was already up: nothing should have moved')


@check('the zoom is widened only when the window is about to be re-tiled')
def _():
    settings = {'zoom_padding_pct': '10', 'tile_zoom_extra_pct': '40'}
    origin = (0.0, 0.0, 0.0)
    right, up, normal = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)
    plain = fiv_core.zoom_rectangle((0, 0, 0), (10, 10, 1), origin, right, up,
                                    normal, 10, 0)
    widened = fiv_core.zoom_rectangle((0, 0, 0), (10, 10, 1), origin, right, up,
                                      normal, 50, 0)
    expect((widened[1][0] - widened[0][0]) > (plain[1][0] - plain[0][0]),
           'the tile allowance did not widen anything')
    expect(fiv_core.as_int(settings.get('tile_zoom_extra_pct'), 35) == 40,
           'the tile allowance is not read from the settings')


# ------------------------------------------------------------- the egg

@check('three slow clicks on the logo open the egg')
def _():
    clicks = []
    fire = False
    for moment in (0.0, 0.6, 1.2):
        fire, clicks = fiv_core.egg_click(clicks, moment)
    expect(fire, 'three slow clicks did not open it')


@check('two slow clicks do not open it')
def _():
    clicks = []
    fire = False
    for moment in (0.0, 0.6):
        fire, clicks = fiv_core.egg_click(clicks, moment)
    expect(not fire, 'it opened on the second click')


@check('a double click is too fast to count')
def _():
    clicks = []
    fire = False
    for moment in (0.0, 0.08, 0.16):
        fire, clicks = fiv_core.egg_click(clicks, moment)
    expect(not fire, 'an ordinary double or triple click opened the egg')


@check('a fast click starts the count again rather than counting')
def _():
    clicks = []
    fire, clicks = fiv_core.egg_click(clicks, 0.0)
    fire, clicks = fiv_core.egg_click(clicks, 0.05)
    expect(len(clicks) == 1, 'the fast click was counted: got {0}'.format(clicks))


@check('a long pause starts the count again')
def _():
    clicks = []
    fire, clicks = fiv_core.egg_click(clicks, 0.0)
    fire, clicks = fiv_core.egg_click(clicks, 0.6)
    fire, clicks = fiv_core.egg_click(clicks, 30.0)
    expect(not fire, 'clicks minutes apart were treated as a sequence')
    expect(len(clicks) == 1, 'the count did not restart')


@check('the count clears once it has fired, so the next three start fresh')
def _():
    clicks = []
    for moment in (0.0, 0.6, 1.2):
        fire, clicks = fiv_core.egg_click(clicks, moment)
    expect(clicks == [], 'the fourth click would open it again straight away')


# --------------------------------------------------- typing element ids

@check('semicolons separate ids, as Revit own dialog says')
def _():
    expect(fiv_core.parse_ids('1234; 5678') == ['1234', '5678'],
           'got {0}'.format(fiv_core.parse_ids('1234; 5678')))


@check('commas, spaces and new lines separate them too')
def _():
    found = fiv_core.parse_ids('1234, 5678 9012\n3456')
    expect(found == ['1234', '5678', '9012', '3456'], 'got {0}'.format(found))


@check('the same id typed twice is only looked up once')
def _():
    expect(fiv_core.parse_ids('1234; 1234; 5678') == ['1234', '5678'],
           'a duplicate survived')


@check('a unique id survives the split, dashes and all')
def _():
    unique = 'e3f2a1b0-1234-4567-89ab-cdef01234567-0001d4c9'
    expect(fiv_core.parse_ids(unique) == [unique], 'a unique id was cut up')


@check('an empty box gives nothing to look up')
def _():
    for text in ('', '   ', ';;;', '\n\n'):
        expect(fiv_core.parse_ids(text) == [],
               '{0!r} produced tokens'.format(text))


@check('a trailing separator does not produce a blank token')
def _():
    expect(fiv_core.parse_ids('1234;') == ['1234'], 'a blank token got through')


def with_real_element_ids(function):
    """The stub ElementId hands back another stub, so the fake document has
    nothing to read: swap in the bench's own id for the length of the check."""
    original = fiv_model.ElementId
    fiv_model.ElementId = FakeId
    try:
        return function()
    finally:
        fiv_model.ElementId = original


@check('ids are looked up, and the ones that are not there are named')
def _():
    class FakeDoc(object):
        def GetElement(self, key):
            value = getattr(key, 'Value', key)
            if value in (11, 12):
                return FakeElement(value, FakeCategory('Pipes', -2001))
            return None

    found, ids, missing = with_real_element_ids(
        lambda: fiv_model.find_by_ids(FakeDoc(), ['11', '12', '99']))
    expect(len(found) == 2, 'expected two elements, got {0}'.format(len(found)))
    expect(missing == ['99'], 'the missing id was not reported: {0}'.format(missing))


@check('the same element reached by two ids is only selected once')
def _():
    class FakeDoc(object):
        def GetElement(self, key):
            return FakeElement(11, FakeCategory('Pipes', -2001))

    found, ids, missing = with_real_element_ids(
        lambda: fiv_model.find_by_ids(FakeDoc(), ['11', '11b']))
    expect(len(found) == 1, 'the element came back twice')


@check('a token that is not a number is tried as a unique id')
def _():
    asked = []

    class FakeDoc(object):
        def GetElement(self, key):
            asked.append(key)
            return None

    with_real_element_ids(lambda: fiv_model.find_by_ids(FakeDoc(), ['abc-123']))
    expect(asked and asked[0] == 'abc-123',
           'the token was not passed through as a unique id: {0}'.format(asked))


@check('the categories of a set of elements are collected without duplicates')
def _():
    pipes = FakeCategory('Pipes', -2001)
    trays = FakeCategory('Cable Trays', -2008)
    ids, names = fiv_model.categories_of(
        [FakeElement(1, pipes), FakeElement(2, pipes), FakeElement(3, trays)])
    expect(len(ids) == 2, 'a category was counted twice')
    expect(sorted(names) == ['Cable Trays', 'Pipes'], 'got {0}'.format(names))


@check('an element with no category does not break the category list')
def _():
    ids, names = fiv_model.categories_of([FakeElement(1, None)])
    expect(ids == [] and names == [], 'got {0} {1}'.format(ids, names))


@check('changing the selection by id gives the same categories as selecting it')
def _():
    # the id box and the Revit selection have to agree, or the summary says one
    # thing and the zoom does another
    pipes = FakeCategory('Pipes', -2001)
    elements = [FakeElement(1, pipes), FakeElement(2, pipes)]

    class FakeSelection(object):
        def GetElementIds(self):
            return [element.Id for element in elements]

    class FakeUiDoc(object):
        def __init__(self):
            self.Document = self
            self.Selection = FakeSelection()

        def GetElement(self, element_id):
            for element in elements:
                if element.Id == element_id:
                    return element
            return None

    _found, _ids, from_selection, names_a = fiv_model.read_selection(FakeUiDoc())
    from_ids, names_b = fiv_model.categories_of(elements)
    expect(len(from_selection) == len(from_ids), 'the two routes disagree')
    expect(names_a == names_b, '{0} against {1}'.format(names_a, names_b))


@check('nothing selected produces no box, so the open skips the zoom')
def _():
    expect(fiv_model.elements_box([]) is None,
           'an empty selection must not produce something to zoom to')


# --------------------------------------------------- the view used last

def remembered_rows():
    rows = []
    for value, name in ((11, 'L01 Ground Power'), (12, 'L02 Power'),
                        (13, 'Roof Plan')):
        row = make_row(name, 'Floor Plan')
        row.view_id = FakeId(value)
        rows.append(row)
    return rows


@check('the view used last is found by its id')
def _():
    found = fiv_model.find_remembered(remembered_rows(), 12, '')
    expect(found is not None and found.name == 'L02 Power', 'the id did not match')


@check('the id wins over the name, so a renamed view is still found')
def _():
    rows = remembered_rows()
    found = fiv_model.find_remembered(rows, 12, 'Roof Plan')
    expect(found.name == 'L02 Power',
           'the name was preferred over the id: a renamed view would be lost')


@check('the name is the fallback, for a model whose ids have all moved')
def _():
    found = fiv_model.find_remembered(remembered_rows(), 99, 'Roof Plan')
    expect(found is not None and found.name == 'Roof Plan', 'the name fallback failed')


@check('a view that is no longer there selects nothing')
def _():
    expect(fiv_model.find_remembered(remembered_rows(), 99, 'Gone') is None,
           'something was selected that should not have been')


@check('nothing remembered selects nothing')
def _():
    expect(fiv_model.find_remembered(remembered_rows(), 0, '') is None,
           'a blank memory should not pick the first row')


@check('the view used last is a remembered setting, by name and by id')
def _():
    for key in ('last_view', 'last_view_id'):
        expect(key in fiv_core.DEFAULTS, '{0} is not remembered'.format(key))


# ------------------------------------------------------- performance

class RecordingCollector(object):
    """A view collector that records what it was asked, and hands back a busy
    view: 5000 elements, of which the selection is two."""

    calls = []

    def __init__(self, doc, view_id=None):
        self.filtered = False
        RecordingCollector.calls.append(self)

    def WherePasses(self, element_filter):
        self.filtered = True
        return self

    def WhereElementIsNotElementType(self):
        return self

    def ToElementIds(self):
        if self.filtered:
            # narrowed inside Revit: only the selection's categories come back
            return [FakeId(11), FakeId(12), FakeId(13)]
        return [FakeId(value) for value in range(5000)] + [FakeId(11), FakeId(12)]


def with_recording(function):
    RecordingCollector.calls = []
    original = (fiv_model.FilteredElementCollector, fiv_model.ElementMulticategoryFilter)
    fiv_model.FilteredElementCollector = RecordingCollector
    fiv_model.ElementMulticategoryFilter = lambda ids: 'category filter'
    try:
        return function()
    finally:
        fiv_model.FilteredElementCollector, fiv_model.ElementMulticategoryFilter = original


@check('the view check is narrowed by category inside Revit')
def _():
    view = FakeView('L1', 'FloorPlan', 1)
    with_recording(lambda: fiv_model.drawn_in_view(
        None, view, [FakeId(11), FakeId(12)], [FakeId(-2001)]))
    expect(RecordingCollector.calls and RecordingCollector.calls[-1].filtered,
           'every element in the view was handed to Python to find two pipes')


@check('narrowing by category gives the same answer as not narrowing')
def _():
    view = FakeView('L1', 'FloorPlan', 1)
    narrowed = with_recording(lambda: fiv_model.drawn_in_view(
        None, view, [FakeId(11), FakeId(12)], [FakeId(-2001)]))
    whole = with_recording(lambda: fiv_model.drawn_in_view(
        None, view, [FakeId(11), FakeId(12)], None))
    expect(narrowed == whole == set([11, 12]),
           '{0} against {1}'.format(narrowed, whole))


@check('with no categories to narrow by, the view check still answers')
def _():
    view = FakeView('L1', 'FloorPlan', 1)
    found = with_recording(lambda: fiv_model.drawn_in_view(
        None, view, [FakeId(11)], []))
    expect(found == set([11]), 'got {0}'.format(found))
    expect(not RecordingCollector.calls[-1].filtered,
           'an empty filter was applied, which would match nothing')


@check('a row works out its search text once and reuses it')
def _():
    row = fiv_model.ViewRow(FakeView('L01 Ground Power', 'FloorPlan', 1))
    first = row.search_text()
    row.name = 'changed after the first read'
    expect(row.search_text() is first, 'the search text was rebuilt on a keystroke')
    expect(first == first.lower(), 'the cached text should already be lower case')


@check('a cached sort key is the same as a freshly made one')
def _():
    row = fiv_model.ViewRow(FakeView('L10 Plan', 'FloorPlan', 1))
    expect(row.sort_key('name') == fiv_core.natural_key('L10 Plan'),
           'the cache changed the sort order')
    expect(row.sort_key('name') is row.sort_key('name'), 'the key was not reused')


@check('the level parameters are looked up once, not once per element')
def _():
    first = fiv_model.level_members()
    expect(first and fiv_model.level_members() is first,
           'the reflection lookups ran again')


# ------------------------------------------------------ the shrink drawer

BAR = 60.0


@check('the slide starts where it is and ends where it is going')
def _():
    expect(fiv_core.drawer_frame(100.0, 900.0, 0.0) == 100.0, 'the first frame moved')
    expect(fiv_core.drawer_frame(100.0, 900.0, 1.0) == 900.0, 'the last frame fell short')


@check('the curve is quick away and gentle in, not linear')
def _():
    half = fiv_core.ease_out(0.5)
    expect(half > 0.5, 'an ease out is past half way at half time, got {0}'.format(half))
    expect(fiv_core.ease_out(0.0) == 0.0 and fiv_core.ease_out(1.0) == 1.0,
           'the curve does not start and end where it should')


@check('a frame beyond the end does not overshoot')
def _():
    expect(fiv_core.drawer_frame(0.0, 100.0, 1.4) == 100.0, 'the window flew past its mark')
    expect(fiv_core.drawer_frame(0.0, 100.0, -0.3) == 0.0, 'a negative frame moved backwards')


@check('the parked bar is the header plus the border above AND below it')
def _():
    expect(fiv_core.bar_height(46.0, 7.0) == 60.0,
           'got {0} - the border below the header was forgotten'.format(
               fiv_core.bar_height(46.0, 7.0)))


@check('a bar is never zero high, whatever the header reports')
def _():
    expect(fiv_core.bar_height(0.0, 0.0) >= 1.0, 'the bar would be invisible')


@check('the bar parks just above the taskbar')
def _():
    top = fiv_core.shrunk_top(0.0, 1040.0, BAR, 0)
    expect(top == 1040.0 - BAR - fiv_core.DRAWER_GAP, 'got {0}'.format(top))


@check('a second bar stacks above the first, not on top of it')
def _():
    first = fiv_core.shrunk_top(0.0, 1040.0, BAR, 0)
    second = fiv_core.shrunk_top(0.0, 1040.0, BAR, 1)
    expect(second < first, 'the second bar landed below the first')
    expect(abs((first - second) - (BAR + fiv_core.DRAWER_STACK)) < 1e-9,
           'the bars overlap: gap is {0}'.format(first - second))


@check('a monitor above the primary one parks on that monitor')
def _():
    # the work area top is NEGATIVE there, and reading it as zero is what
    # sends the bar to the wrong screen
    top = fiv_core.shrunk_top(-1080.0, 1040.0, BAR, 0)
    expect(top < 0.0, 'the bar was parked on the primary screen instead')
    expect(top == -1080.0 + 1040.0 - BAR - fiv_core.DRAWER_GAP,
           'got {0}'.format(top))


@check('a freed parking slot is reused rather than left as a gap')
def _():
    expect(fiv_core.free_slot([0, 2]) == 1, 'the gap was skipped')
    expect(fiv_core.free_slot([]) == 0, 'the first bar did not take the first slot')
    expect(fiv_core.free_slot([0, 1]) == 2, 'two bars did not stack to a third')


@check('a window opens upward out of the bar it was left in')
def _():
    parked = fiv_core.shrunk_top(0.0, 1040.0, BAR, 0)
    top = fiv_core.expand_top(parked, 700.0, BAR, 0.0, 1040.0)
    expect(abs((top + 700.0) - (parked + BAR)) < 1e-9,
           'the bottom of the window should land at the bottom of the bar')


@check('a bar carried to the top of the screen still opens on screen')
def _():
    top = fiv_core.expand_top(5.0, 700.0, BAR, 0.0, 1040.0)
    expect(top >= 0.0, 'the window opened off the top of the screen: {0}'.format(top))


@check('a window taller than the screen is clamped, not hidden')
def _():
    top = fiv_core.expand_top(900.0, 2000.0, BAR, 0.0, 1040.0)
    expect(top == 0.0, 'got {0}'.format(top))


@check('opening on a monitor above the primary one stays on it')
def _():
    parked = fiv_core.shrunk_top(-1080.0, 1040.0, BAR, 0)
    top = fiv_core.expand_top(parked, 700.0, BAR, -1080.0, 1040.0)
    expect(top < 0.0, 'the window jumped to the primary screen')
    expect(top >= -1080.0, 'the window opened above its own screen')


# --------------------------------------- already in the view you are in

def here(enabled=True, view_can_zoom=True, selected=3, drawn=3, needs_all=True):
    return fiv_core.zoom_here_decision(enabled, view_can_zoom, selected, drawn,
                                       needs_all)


@check('everything selected is in this view, so it zooms without a window')
def _():
    expect(here() == fiv_core.HERE_ZOOM, 'the window opened for no reason')


@check('none of it is in this view, so the window opens')
def _():
    expect(here(drawn=0) == fiv_core.HERE_WINDOW, 'it zoomed to nothing')


@check('some of it here and some elsewhere opens the window')
def _():
    # four pipes on this level and one on the next is exactly when the view
    # list is what you wanted
    expect(here(selected=5, drawn=4) == fiv_core.HERE_WINDOW,
           'a partial match skipped the view list')


@check('a partial match can be made to zoom, where that is asked for')
def _():
    expect(here(selected=5, drawn=4, needs_all=False) == fiv_core.HERE_ZOOM,
           'the setting was ignored')


@check('the tick box off always opens the window')
def _():
    expect(here(enabled=False) == fiv_core.HERE_WINDOW, 'the option was ignored')


@check('a view that cannot be zoomed opens the window')
def _():
    # a sheet, a schedule, a legend, a drafting view
    expect(here(view_can_zoom=False) == fiv_core.HERE_WINDOW,
           'it tried to zoom a view that cannot show model elements')


@check('nothing selected never takes the shortcut')
def _():
    expect(here(selected=0, drawn=0) == fiv_core.HERE_WINDOW,
           'a shortcut was taken with nothing to frame')


# ------------------------------------------------ which box takes the caret

@check('nothing selected puts the caret in the element id box')
def _():
    expect(fiv_core.first_field(False) == fiv_core.FIELD_ID,
           'skipping Find by ID should leave you ready to type an id')


@check('a selection puts the caret in the view search')
def _():
    expect(fiv_core.first_field(True) == fiv_core.FIELD_SEARCH,
           'with a selection the next thing typed is a view name')


# ------------------------------------------------------------- levels

LEVELS = [('L00 Ground', 0.0), ('L01 First', 12.0), ('L02 Second', 24.0)]


@check('the level below is the level something is on')
def _():
    expect(fiv_core.nearest_level(LEVELS, 14.0) == 'L01 First',
           'something 2ft above L01 belongs to L01')


@check('services in the ceiling void belong to the floor below, not the one above')
def _():
    # 22ft of a 24ft storey: nearer to L02, but it is L01's ceiling void
    expect(fiv_core.nearest_level(LEVELS, 22.0) == 'L01 First',
           'the level rounded to the nearest instead of taking the one below')


@check('sitting exactly on a level is that level, not the one below')
def _():
    expect(fiv_core.nearest_level(LEVELS, 12.0) == 'L01 First', 'off by a level')


@check('something below the lowest level takes the lowest level')
def _():
    expect(fiv_core.nearest_level(LEVELS, -30.0) == 'L00 Ground',
           'a basement element got no level at all')


@check('something above the top level stays on the top level')
def _():
    expect(fiv_core.nearest_level(LEVELS, 900.0) == 'L02 Second', 'got the wrong end')


@check('a project with no levels gives no answer rather than a wrong one')
def _():
    expect(fiv_core.nearest_level([], 5.0) is None, 'a level was invented')


@check('levels out of order still resolve correctly')
def _():
    jumbled = [('L02 Second', 24.0), ('L00 Ground', 0.0), ('L01 First', 12.0)]
    expect(fiv_core.nearest_level(jumbled, 13.0) == 'L01 First',
           'the answer depended on the order they were read in')


@check('one element on one level reads as just that level')
def _():
    expect(fiv_core.summarise_levels(['L01']) == 'L01', 'got a count for one element')


@check('several levels are counted, most used first')
def _():
    found = fiv_core.summarise_levels(['L02', 'L01', 'L01', 'L01', 'L02'])
    expect(found == 'L01 (3), L02 (2)', 'got {0}'.format(found))


@check('a tie between levels is broken by name, not by luck')
def _():
    found = fiv_core.summarise_levels(['L10', 'L02', 'L10', 'L02'])
    expect(found == 'L02 (2), L10 (2)', 'got {0}'.format(found))


@check('an element with no level is counted as having none, not dropped')
def _():
    found = fiv_core.summarise_levels(['L01', None, ''])
    expect('no level (2)' in found, 'got {0}'.format(found))


@check('the level is read from the parameter that category actually uses')
def _():
    class FakeParameter(object):
        def __init__(self, value):
            self.value = value

        def AsElementId(self):
            return FakeId(self.value)

    class FakeLevel(object):
        Name = 'L01 First'

    class FakeDoc(object):
        def GetElement(self, element_id):
            return FakeLevel() if getattr(element_id, 'Value', 0) == 77 else None

    class FakePipe(object):
        def get_Parameter(self, member):
            # only the MEP reference level answers, as on a real pipe
            return FakeParameter(77) if 'RBS_START' in str(member) else None

        def GetParameters(self, name):
            return []

    found = fiv_model.level_from_parameters(FakeDoc(), FakePipe())
    expect(found == 'L01 First', 'got {0!r}'.format(found))


@check('an element whose parameters say nothing does not invent a level')
def _():
    class Silent(object):
        def get_Parameter(self, member):
            return None

        def GetParameters(self, name):
            return []

    class FakeDoc(object):
        def GetElement(self, element_id):
            return None

    expect(fiv_model.level_from_parameters(FakeDoc(), Silent()) == '',
           'a level came from nowhere')


# --------------------------------------------- switching a category on

@check('nothing hidden means nothing is changed')
def _():
    plan = fiv_core.plan_unhide(True, 'auto', [], [], True)
    expect(plan == fiv_core.UNHIDE_NONE, 'the view would have been written to '
           'for no reason')


@check('the tick box off means the view is never written to')
def _():
    plan = fiv_core.plan_unhide(False, 'auto', [-2001], [], True)
    expect(plan == fiv_core.UNHIDE_NONE, 'a hidden category was fixed with the '
           'option turned off')


@check('a view with a template gets temporary view properties')
def _():
    plan = fiv_core.plan_unhide(True, 'auto', [-2001], [], True)
    expect(plan == fiv_core.UNHIDE_TEMPORARY, 'got {0}'.format(plan))


@check('a view with no template is changed for real, because there is no temporary mode to enter')
def _():
    plan = fiv_core.plan_unhide(True, 'auto', [-2001], [], False)
    expect(plan == fiv_core.UNHIDE_PERMANENT, 'got {0}'.format(plan))


@check('asking for temporary on a view with no template lands on permanent')
def _():
    plan = fiv_core.plan_unhide(True, 'temporary', [-2001], [], False)
    expect(plan == fiv_core.UNHIDE_PERMANENT,
           'temporary view properties need a template to enter with')


@check('asking for permanent never enters temporary mode')
def _():
    plan = fiv_core.plan_unhide(True, 'permanent', [-2001], [], True)
    expect(plan == fiv_core.UNHIDE_PERMANENT, 'the request was overridden')


@check('an element hidden on its own is enough to act on')
def _():
    plan = fiv_core.plan_unhide(True, 'auto', [], ['an element'], False)
    expect(plan == fiv_core.UNHIDE_PERMANENT,
           'an element hidden one at a time was ignored')


@check('a category the view has switched off is found')
def _():
    view = FakeView('L1', 'FloorPlan', 1)
    view._hidden = set([-2001])
    view.GetCategoryHidden = lambda category_id: category_id.Value in view._hidden
    hidden = fiv_model.hidden_categories_in(view, [FakeId(-2001), FakeId(-2008)])
    expect(len(hidden) == 1 and hidden[0].Value == -2001,
           'got {0}'.format([entry.Value for entry in hidden]))


@check('a view that will not answer about a category is not treated as hiding it')
def _():
    class Awkward(object):
        def GetCategoryHidden(self, category_id):
            raise Exception('not a category this view knows')

    expect(fiv_model.hidden_categories_in(Awkward(), [FakeId(-2001)]) == [],
           'an unanswerable category was reported as hidden')


@check('elements the view still will not draw are reported, with the reasons')
def _():
    class FakeDoc(object):
        pass

    original = fiv_model.drawn_in_view
    fiv_model.drawn_in_view = lambda doc, view, ids, cats=None: set([11])
    try:
        note = fiv_model.still_missing(FakeDoc(), None, [FakeId(11), FakeId(12)])
    finally:
        fiv_model.drawn_in_view = original
    expect('1 of the selection' in note, 'got {0}'.format(note))
    expect('view filter' in note and 'crop' in note,
           'the note does not name what switching a category on cannot fix')


@check('everything drawn means nothing is reported')
def _():
    original = fiv_model.drawn_in_view
    fiv_model.drawn_in_view = lambda doc, view, ids, cats=None: set([11, 12])
    try:
        note = fiv_model.still_missing(None, None, [FakeId(11), FakeId(12)])
    finally:
        fiv_model.drawn_in_view = original
    expect(note == '', 'a clean run said something: {0}'.format(note))


@check('a view that will not report what it draws says nothing rather than guessing')
def _():
    original = fiv_model.drawn_in_view
    fiv_model.drawn_in_view = lambda doc, view, ids, cats=None: None
    try:
        note = fiv_model.still_missing(None, None, [FakeId(11)])
    finally:
        fiv_model.drawn_in_view = original
    expect(note == '', 'an unanswerable check invented a problem')


# ------------------------------------------------------ did the zoom land

def frame_rect(low, high):
    return (low, high)


@check('a view framed on the selection reads as landed')
def _():
    ok, reason = fiv_core.zoom_landed((0, 0), (10, 10), (-1, -1), (11, 11))
    expect(ok, 'a good framing was rejected: {0}'.format(reason))


@check('a view zoomed out to the whole model does not read as landed')
def _():
    ok, reason = fiv_core.zoom_landed((0, 0), (10, 10), (-500, -500), (500, 500))
    expect(not ok, 'zoomed to fit was accepted as zoomed to the selection')
    expect('times the selection' in reason, 'the reason should say how far out')


@check('a view cutting the selection off does not read as landed')
def _():
    ok, reason = fiv_core.zoom_landed((0, 0), (10, 10), (3, 3), (7, 7))
    expect(not ok, 'a view showing a quarter of the selection was accepted')
    expect('cutting' in reason, 'got {0}'.format(reason))


@check('a view centred somewhere else does not read as landed')
def _():
    ok, reason = fiv_core.zoom_landed((0, 0), (10, 10), (100, 100), (120, 120))
    expect(not ok, 'the selection is not even on screen')
    expect('middle' in reason, 'got {0}'.format(reason))


@check('the window being a different shape from the selection is allowed')
def _():
    # ZoomAndCenterRectangle fits the rectangle to the window, so one axis
    # always comes back larger than asked for
    ok, reason = fiv_core.zoom_landed((0, 0), (10, 10), (-10, -1), (20, 11))
    expect(ok, 'a wide window was treated as a failure: {0}'.format(reason))


@check('the corners can come back either way round')
def _():
    ok, _reason = fiv_core.zoom_landed((10, 10), (0, 0), (11, 11), (-1, -1))
    expect(ok, 'the check depends on the order the corners arrive in')


@check('a zero sized selection does not divide by zero')
def _():
    ok, _reason = fiv_core.zoom_landed((5, 5), (5, 5), (0, 0), (10, 10))
    expect(ok, 'a point selection should be accepted, not crash')


class FakeZoomPoint(object):
    def __init__(self, values):
        self.X, self.Y, self.Z = values


class FakeUiViewZoom(object):
    """A UIView that reframes itself the first time, the way a window Revit has
    only just created does."""

    def __init__(self, reframes=1, corners=None):
        self.calls = []
        self.reframes = reframes
        self.stubborn = corners

    def ZoomAndCenterRectangle(self, low, high):
        self.calls.append((low, high))

    def GetZoomCorners(self):
        if self.stubborn is not None:
            return [FakeZoomPoint(self.stubborn[0]), FakeZoomPoint(self.stubborn[1])]
        if len(self.calls) <= self.reframes:
            # Revit framed the window itself and ignored the call
            return [FakeZoomPoint((-500.0, -500.0, 0.0)),
                    FakeZoomPoint((500.0, 500.0, 0.0))]
        return [FakeZoomPoint((-2.0, -2.0, 0.0)), FakeZoomPoint((12.0, 12.0, 0.0))]


def run_zoom(ui_view, settings=None):
    elements = [FakeElement(1, None, FakeBox((0, 0, 0), (10, 10, 3)))]
    view = FakeView('L1', 'FloorPlan', 5)

    class FakeUiDoc(object):
        def RefreshActiveView(self):
            pass

    original = fiv_model.find_ui_view
    fiv_model.find_ui_view = lambda uidoc, view_id: ui_view
    try:
        return fiv_model.zoom_to_elements(FakeUiDoc(), view, elements,
                                          settings or {'zoom_padding_pct': '15'})
    finally:
        fiv_model.find_ui_view = original


@check('a zoom Revit ignores is tried again rather than reported as done')
def _():
    ui_view = FakeUiViewZoom(reframes=1)
    ok, note = run_zoom(ui_view)
    expect(ok, 'the retry did not recover it: {0}'.format(note))
    expect(len(ui_view.calls) == 2,
           'expected a second attempt, got {0}'.format(len(ui_view.calls)))


@check('a zoom that takes first time is not repeated')
def _():
    ui_view = FakeUiViewZoom(reframes=0)
    ok, _note = run_zoom(ui_view)
    expect(ok, 'a good zoom was reported as a failure')
    expect(len(ui_view.calls) == 1, 'the view was zoomed more than once for nothing')


@check('a view that will not hold the zoom is reported, with what it is showing')
def _():
    ui_view = FakeUiViewZoom(corners=((-500.0, -500.0, 0.0), (500.0, 500.0, 0.0)))
    ok, note = run_zoom(ui_view)
    expect(not ok, 'a view showing the whole model was reported as framed')
    expect('times the selection' in note, 'the note does not say what happened: {0}'.format(note))


@check('the number of attempts is a setting and is honoured')
def _():
    ui_view = FakeUiViewZoom(corners=((-500.0, -500.0, 0.0), (500.0, 500.0, 0.0)))
    run_zoom(ui_view, {'zoom_padding_pct': '15', 'zoom_attempts': '2'})
    expect(len(ui_view.calls) == 2, 'got {0} attempts'.format(len(ui_view.calls)))


@check('a view that will not report what it is showing is left after one go')
def _():
    class Silent(FakeUiViewZoom):
        def GetZoomCorners(self):
            raise Exception('not supported')

    ui_view = Silent()
    ok, _note = run_zoom(ui_view)
    expect(ok, 'an unverifiable zoom should be taken at face value, not failed')
    expect(len(ui_view.calls) == 1, 'it retried something it cannot check')


# ------------------------------------------------------- posting the tile

class FakePostable(object):
    """A PostableCommand enum carrying only the members named."""

    def __init__(self, members):
        for member in members:
            setattr(self, member, 'enum:' + member)


class FakeCommandId(object):
    """RevitCommandId with a say in what it knows and what it refuses."""

    def __init__(self, known=None, throws_on=None):
        self.known = set(known or [])
        self.throws_on = set(throws_on or [])

    def LookupPostableCommandId(self, member):
        name = str(member).split(':')[-1]
        if name in self.throws_on:
            raise Exception('not available in this context')
        return 'cmd:' + name if name in self.known else None

    def LookupCommandId(self, name):
        if name in self.throws_on:
            raise Exception('not available in this context')
        return 'cmd:' + name if name in self.known else None


class FakeUiApp(object):
    def __init__(self, can_post=True, refuse=None):
        self.can_post = can_post
        self.refuse = set(refuse or [])
        self.posted = []

    def CanPostCommand(self, command_id):
        return self.can_post

    def PostCommand(self, command_id):
        if command_id in self.refuse:
            raise Exception('Revit refused the command')
        self.posted.append(command_id)


def with_fake_commands(postable, command_id, function):
    original = (fiv_model.PostableCommand, fiv_model.RevitCommandId)
    fiv_model.PostableCommand = postable
    fiv_model.RevitCommandId = command_id
    try:
        return function()
    finally:
        fiv_model.PostableCommand, fiv_model.RevitCommandId = original


@check('the tile command posts when the first name is the right one')
def _():
    app = FakeUiApp()
    ok, report = with_fake_commands(
        FakePostable(['TileWindows']), FakeCommandId(['TileWindows']),
        lambda: fiv_model.post_tile_windows(app))
    expect(ok, 'the post failed: {0}'.format(report))
    expect(app.posted == ['cmd:TileWindows'], 'the wrong command was posted')


@check('a release that spells the member differently still tiles')
def _():
    app = FakeUiApp()
    ok, report = with_fake_commands(
        FakePostable(['TileViews']), FakeCommandId(['TileViews']),
        lambda: fiv_model.post_tile_windows(app))
    expect(ok, 'the second name was not tried: {0}'.format(report))
    expect(report == 'TileViews', 'the report should name the route that worked')


@check('the string command id is tried when no enum member fits')
def _():
    app = FakeUiApp()
    ok, report = with_fake_commands(
        FakePostable([]), FakeCommandId(['ID_WINDOW_TILE']),
        lambda: fiv_model.post_tile_windows(app))
    expect(ok, 'the id route was not tried: {0}'.format(report))
    expect(app.posted == ['cmd:ID_WINDOW_TILE'], 'the wrong route was taken')


@check('a name Revit throws on does not stop the later routes')
def _():
    app = FakeUiApp()
    ok, report = with_fake_commands(
        FakePostable(['TileWindows', 'TileViews']),
        FakeCommandId(['TileViews'], throws_on=['TileWindows']),
        lambda: fiv_model.post_tile_windows(app))
    expect(ok, 'a throwing lookup stopped the run: {0}'.format(report))


@check('CanPostCommand saying no does not stop the post')
def _():
    # Tile is greyed while one view window is open, and Revit may not create the
    # second one until this command ends - so a no here is not an answer
    app = FakeUiApp(can_post=False)
    ok, report = with_fake_commands(
        FakePostable(['TileWindows']), FakeCommandId(['TileWindows']),
        lambda: fiv_model.post_tile_windows(app))
    expect(ok, 'CanPostCommand was used as a gate: {0}'.format(report))
    expect(app.posted, 'nothing was posted')


@check('every route failing is reported, not swallowed')
def _():
    app = FakeUiApp()
    ok, report = with_fake_commands(
        FakePostable([]), FakeCommandId([]),
        lambda: fiv_model.post_tile_windows(app))
    expect(not ok, 'it claimed to have posted something')
    expect('TileWindows' in report and 'ID_WINDOW_TILE' in report,
           'the report does not name what was tried: {0}'.format(report))
    expect(len(report.splitlines()) == len(fiv_model.TILE_COMMANDS),
           'every route should have a line in the report')


@check('a post that throws is reported with what Revit said')
def _():
    app = FakeUiApp(refuse=['cmd:TileWindows'])
    ok, report = with_fake_commands(
        FakePostable(['TileWindows']), FakeCommandId(['TileWindows']),
        lambda: fiv_model.post_tile_windows(app))
    expect(not ok, 'a refused post was reported as a success')
    expect('refused the command' in report, 'Revit\'s own words were lost')


@check('no application at all is reported rather than crashing')
def _():
    ok, report = fiv_model.post_tile_windows(None)
    expect(not ok and report, 'a missing application should report, not throw')


@check('the failure message names the menu item and the way to silence it')
def _():
    text = fiv_model.tile_failure_message('TileWindows - not found')
    expect('Tile Views' in text, 'the message does not say where the command is')
    expect('warn_tile_failure' in text, 'the message does not say how to stop it')
    expect('TileWindows - not found' in text, 'the report was not carried through')


# ------------------------------------------------------------------ selection

@check('the selected categories are collected without duplicates')
def _():
    pipes = FakeCategory('Pipes', -2001)
    trays = FakeCategory('Cable Trays', -2008)
    elements = [FakeElement(1, pipes), FakeElement(2, pipes), FakeElement(3, trays)]

    class FakeSelection(object):
        def GetElementIds(self):
            return [element.Id for element in elements]

    class FakeUiDoc(object):
        def __init__(self):
            self.Document = self
            self.Selection = FakeSelection()

        def GetElement(self, element_id):
            for element in elements:
                if element.Id == element_id:
                    return element
            return None

    found, ids, category_ids, names = fiv_model.read_selection(FakeUiDoc())
    expect(len(found) == 3, 'lost an element')
    expect(sorted(names) == ['Cable Trays', 'Pipes'], 'got {0}'.format(names))
    expect(len(category_ids) == 2, 'a category was counted twice')


@check('elements are counted per category for the selection summary')
def _():
    pipes = FakeCategory('Pipes', -2001)
    counts = fiv_model.category_counts([FakeElement(1, pipes), FakeElement(2, pipes)])
    expect(counts == {'Pipes': 2}, 'got {0}'.format(counts))


@check('an element with no category is still counted')
def _():
    counts = fiv_model.category_counts([FakeElement(1, None)])
    expect(counts == {'No category': 1}, 'got {0}'.format(counts))


# ------------------------------------------------------------------- settings

def with_temp_settings(function):
    folder = tempfile.mkdtemp(prefix='fiv_bench_')
    original_dir = fiv_core.SETTINGS_DIR
    original_path = fiv_core.SETTINGS_PATH
    fiv_core.SETTINGS_DIR = folder
    fiv_core.SETTINGS_PATH = os.path.join(folder, 'find_in_view.txt')
    try:
        return function(fiv_core.SETTINGS_PATH)
    finally:
        fiv_core.SETTINGS_DIR = original_dir
        fiv_core.SETTINGS_PATH = original_path


@check('settings round trip through the key=value file')
def _():
    def body(path):
        data = fiv_core.load_settings()
        data['theme'] = 'light'
        data['remember_search'] = '1'
        data['view_types'] = fiv_core.pack_list(['Floor Plan', 'Section'])
        expect(fiv_core.save_settings(data), 'the save reported failure')
        again = fiv_core.load_settings()
        expect(again['theme'] == 'light', 'the theme did not survive')
        expect(again['remember_search'] == '1', 'the tick did not survive')
        expect(fiv_core.unpack_list(again['view_types']) == ['Floor Plan', 'Section'],
               'the view types did not survive')
    with_temp_settings(body)


@check('a missing settings file falls back to the defaults')
def _():
    def body(path):
        data = fiv_core.load_settings()
        expect(data['theme'] == 'dark', 'the default theme is wrong')
        expect(data['zoom_padding_pct'] == '15', 'the default padding is wrong')
        expect(data['view_types'] == '', 'every view type should start ticked')
    with_temp_settings(body)


@check('a damaged settings file falls back key by key rather than throwing')
def _():
    def body(path):
        handle = open(path, 'w')
        handle.write('theme=light\nthis line is nonsense\n=\nremember_search=1\n')
        handle.close()
        data = fiv_core.load_settings()
        expect(data['theme'] == 'light', 'a good key was lost')
        expect(data['remember_search'] == '1', 'a good key after a bad one was lost')
        expect(data['window_width'] == '1040', 'a missing key did not default')
    with_temp_settings(body)


@check('a key from an older version is ignored rather than breaking the load')
def _():
    def body(path):
        handle = open(path, 'w')
        handle.write('theme=light\nsome_old_key=42\n')
        handle.close()
        data = fiv_core.load_settings()
        expect('some_old_key' not in data, 'an unknown key was let in')
        expect(data['theme'] == 'light', 'the load broke on the unknown key')
    with_temp_settings(body)


@check('a value containing = survives, because the split is on the first one')
def _():
    def body(path):
        handle = open(path, 'w')
        handle.write('search=size=A1\n')
        handle.close()
        expect(fiv_core.load_settings()['search'] == 'size=A1', 'the value was cut short')
    with_temp_settings(body)


@check('a pipe in a stored value cannot corrupt the list')
def _():
    packed = fiv_core.pack_list(['Floor Plan', 'Odd|Name'])
    expect(fiv_core.unpack_list(packed) == ['Floor Plan', 'Odd Name'],
           'got {0}'.format(fiv_core.unpack_list(packed)))


@check('booleans read the way a text file writes them')
def _():
    expect(fiv_core.as_bool('1') and fiv_core.as_bool('true') and fiv_core.as_bool('On'),
           'a true value read as false')
    expect(not fiv_core.as_bool('0') and not fiv_core.as_bool('no'),
           'a false value read as true')
    expect(fiv_core.as_bool('rubbish', True), 'the fallback was ignored')


@check('numbers read with a fallback rather than throwing')
def _():
    expect(fiv_core.as_int('42') == 42, 'a plain number failed')
    expect(fiv_core.as_int('nonsense', 7) == 7, 'the fallback was ignored')


@check('the removed filters left no settings behind')
def _():
    for key in fiv_core.REMOVED_SETTINGS:
        expect(key not in fiv_core.DEFAULTS,
               '{0} is still a setting after the filter that used it was '
               'removed'.format(key))


@check('the choices that are still free to honour are still remembered')
def _():
    for key in ('theme', 'view_types', 'last_view', 'window_width', 'open_tiled'):
        expect(key in fiv_core.DEFAULTS, '{0} stopped being remembered'.format(key))


@check('a settings file written by an older version still loads')
def _():
    def body(path):
        handle = open(path, 'w')
        handle.write('theme=light\nonly_elements=1\nscan_limit=2000\n')
        handle.close()
        data = fiv_core.load_settings()
        expect(data['theme'] == 'light', 'the load broke on the removed keys')
        expect('only_elements' not in data, 'a removed key was let back in')
    with_temp_settings(body)


@check('natural sort reads numbers as numbers')
def _():
    names = ['L10 Plan', 'L2 Plan', 'L1 Plan']
    names.sort(key=fiv_core.natural_key)
    expect(names == ['L1 Plan', 'L2 Plan', 'L10 Plan'], 'got {0}'.format(names))


@check('plurals read properly in the status line')
def _():
    expect(fiv_core.plural(1, 'element') == '1 element', 'singular is wrong')
    expect(fiv_core.plural(3, 'element') == '3 elements', 'plural is wrong')
    expect(fiv_core.plural(2, 'category', 'categories') == '2 categories',
           'the irregular plural is wrong')


# ---------------------------------------------------------------- the runner

def run(out=sys.stdout):
    failures = []
    for label, function in CHECKS:
        try:
            function()
        except Exception as error:
            failures.append((label, '{0}: {1}'.format(type(error).__name__, error)))
    for label, message in failures:
        out.write('FAIL  {0}\n        {1}\n'.format(label, message))
    out.write('{0} of {1} checks pass\n'.format(len(CHECKS) - len(failures), len(CHECKS)))
    return 1 if failures else 0


def selftest(out=sys.stdout):
    """Put the old, wrong behaviour back and confirm the bench notices.

    A bench that passes against broken code is worth nothing.
    """
    misses = []

    # 1. a filter rule that ignores the view type ticks, which is what an
    #    unticked type silently surviving would look like.
    original = fiv_model.passes_filters

    def blind(row, ticked, query):
        return original(row, list(ticked) + ['3D View'], query)

    fiv_model.passes_filters = blind
    if run(open(os.devnull, 'w')) == 0:
        misses.append('the bench did not notice the view type ticks being ignored')
    fiv_model.passes_filters = original

    # 2. padding as a flat number rather than a share of the extent.
    original_pad = fiv_core.padded_box

    def flat(minimum, maximum, padding_pct, min_padding_ft):
        return original_pad(minimum, maximum, 0, min_padding_ft)

    fiv_core.padded_box = flat
    if run(open(os.devnull, 'w')) == 0:
        misses.append('the bench did not notice the percentage padding going away')
    fiv_core.padded_box = original_pad

    # 3. a natural sort that falls back to plain text, which puts L10 before
    #    L2 in a project browser sized list.
    original_key = fiv_core.natural_key
    fiv_core.natural_key = lambda text: str(text).lower()
    if run(open(os.devnull, 'w')) == 0:
        misses.append('the bench did not notice natural sort going away')
    fiv_core.natural_key = original_key

    # 4. the old zoom rectangle: two opposite corners of the model aligned
    #    box, which is only right when the view looks down a model axis.
    original_rect = fiv_core.zoom_rectangle

    def two_corners(low, high, origin, right, up, normal, padding_pct, min_padding_ft):
        return fiv_core.padded_box(low, high, padding_pct, min_padding_ft)

    fiv_core.zoom_rectangle = two_corners
    if run(open(os.devnull, 'w')) == 0:
        misses.append('the bench did not notice the zoom going back to two corners')
    fiv_core.zoom_rectangle = original_rect

    # 5. CanPostCommand back as a gate, which is what stopped the tiling
    #    working in 1.4.0.
    original_post = fiv_model.post_tile_windows

    def gated(uiapp):
        try:
            if uiapp is not None and not uiapp.CanPostCommand(None):
                return False, 'Revit will not accept it just now'
        except Exception:
            pass
        return original_post(uiapp)

    fiv_model.post_tile_windows = gated
    if run(open(os.devnull, 'w')) == 0:
        misses.append('the bench did not notice CanPostCommand back as a gate')
    fiv_model.post_tile_windows = original_post

    # 6. tiling unconditionally, the 1.4.0 behaviour: an arrangement that was
    #    already right got flattened and the zoom went approximate with it.
    original_plan = fiv_model.plan_tiling

    def always(rects, host_id, target_id, settings):
        to_close, mode = original_plan(rects, host_id, target_id, settings)
        if mode != fiv_core.TILE_NEVER or fiv_core.as_bool(settings.get('open_tiled')):
            mode = fiv_core.TILE_ALWAYS
        return to_close, mode

    fiv_model.plan_tiling = always
    if run(open(os.devnull, 'w')) == 0:
        misses.append('the bench did not notice the layout being tiled regardless')
    fiv_model.plan_tiling = original_plan

    # 7. a zoom that reports success because the call returned, which is what
    #    let a newly opened view come up showing the whole model.
    original_landed = fiv_core.zoom_landed
    fiv_core.zoom_landed = lambda a, b, c, d: (True, '')
    if run(open(os.devnull, 'w')) == 0:
        misses.append('the bench did not notice the zoom being taken on trust')
    fiv_core.zoom_landed = original_landed

    # 8. tiling whenever the tick box is on, rather than only when the view you
    #    came from is the only window open.
    original_plan2 = fiv_model.plan_tiling

    def eager_tile(rects, host_id, target_id, settings):
        to_close, mode = original_plan2(rects, host_id, target_id, settings)
        if fiv_core.as_bool(settings.get('open_tiled')):
            mode = fiv_core.TILE_ALWAYS
        return to_close, mode

    fiv_model.plan_tiling = eager_tile
    if run(open(os.devnull, 'w')) == 0:
        misses.append('the bench did not notice a layout being re-tiled anyway')
    fiv_model.plan_tiling = original_plan2

    # 9. matching the view used last by name only, which loses it the moment
    #    somebody renames a view.
    original_find = fiv_model.find_remembered

    def by_name_only(rows, view_id_value, name):
        return original_find(rows, 0, name)

    fiv_model.find_remembered = by_name_only
    if run(open(os.devnull, 'w')) == 0:
        misses.append('the bench did not notice the id being ignored')
    fiv_model.find_remembered = original_find

    # 10. an egg that opens on an ordinary double click, which is the whole
    #     reason the gap has a floor as well as a ceiling.
    original_egg = fiv_core.egg_click

    def twitchy(times, now):
        kept = list(times or [])
        kept.append(now)
        if len(kept) >= fiv_core.EGG_CLICKS:
            return True, []
        return False, kept

    fiv_core.egg_click = twitchy
    if run(open(os.devnull, 'w')) == 0:
        misses.append('the bench did not notice the egg opening on a double click')
    fiv_core.egg_click = original_egg

    # 11. writing to the view whether or not anything is hidden, which would
    #     put a transaction and an undo step on every single run.
    original_plan_unhide = fiv_core.plan_unhide

    def always_write(enabled, mode, hidden_categories, hidden_elements, has_template):
        if not enabled:
            return fiv_core.UNHIDE_NONE
        return fiv_core.UNHIDE_PERMANENT

    fiv_core.plan_unhide = always_write
    if run(open(os.devnull, 'w')) == 0:
        misses.append('the bench did not notice the view being written to for nothing')
    fiv_core.plan_unhide = original_plan_unhide

    # 12. the nearest level rounding to whichever is closest rather than
    #     taking the one below, which puts everything in the ceiling void on
    #     the floor above.
    original_level = fiv_core.nearest_level

    def closest(levels, elevation):
        if not levels:
            return None
        return min(levels, key=lambda entry: abs(entry[1] - elevation))[0]

    fiv_core.nearest_level = closest
    if run(open(os.devnull, 'w')) == 0:
        misses.append('the bench did not notice the level rounding to the nearest')
    fiv_core.nearest_level = original_level

    # 13. the shortcut firing on a partial match, which would take you to a
    #     zoom of four pipes and quietly hide that the fifth is elsewhere.
    original_here = fiv_core.zoom_here_decision

    def any_match(enabled, view_can_zoom, selected, drawn, needs_all):
        return original_here(enabled, view_can_zoom, selected, drawn, False)

    fiv_core.zoom_here_decision = any_match
    if run(open(os.devnull, 'w')) == 0:
        misses.append('the bench did not notice the shortcut taking a partial match')
    fiv_core.zoom_here_decision = original_here

    # 14. a bar parked by measuring from zero instead of the work area's own
    #     top, which lands it on the primary screen when the window is on a
    #     monitor above it.
    original_park = fiv_core.shrunk_top

    def primary_only(area_top, area_height, bar, slot=0):
        return original_park(0.0, area_height, bar, slot)

    fiv_core.shrunk_top = primary_only
    if run(open(os.devnull, 'w')) == 0:
        misses.append('the bench did not notice the bar ignoring the screen top')
    fiv_core.shrunk_top = original_park

    # 15. a drawer that reopens to the saved position rather than growing out
    #     of a bar the user has dragged somewhere else.
    original_expand = fiv_core.expand_top

    def ignores_the_bar(parked_top, height, bar, area_top, area_height):
        return original_expand(parked_top, height, 0.0, area_top, area_height)

    fiv_core.expand_top = ignores_the_bar
    if run(open(os.devnull, 'w')) == 0:
        misses.append('the bench did not notice the bar height dropped from the sum')
    fiv_core.expand_top = original_expand

    # 16. the view check back to collecting every element in the view, which
    #     is correct and slow - the kind of regression nothing else notices.
    original_filter = fiv_model._category_filter
    fiv_model._category_filter = lambda category_ids: None
    if run(open(os.devnull, 'w')) == 0:
        misses.append('the bench did not notice the view check going unfiltered')
    fiv_model._category_filter = original_filter

    for message in misses:
        out.write('MISSED  {0}\n'.format(message))
    out.write('{0} of 16 deliberate regressions caught\n'.format(16 - len(misses)))
    return 1 if misses else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(selftest())
    sys.exit(run())
