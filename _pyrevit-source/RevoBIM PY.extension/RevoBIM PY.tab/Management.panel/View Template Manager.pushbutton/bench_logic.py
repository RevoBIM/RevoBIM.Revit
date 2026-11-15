# -*- coding: utf-8 -*-
"""Logic checks for the View Template Manager, run under plain CPython 3 against
the stub API in import_check.py - no Revit, no window.

    python bench_logic.py              the checks
    python bench_logic.py --selftest   swap in a broken version of each rule
                                       and prove a check notices

Everything here is a plain function in vtm_core, vtm_settings or vtm_theme:
what a cell accepts, where a paste lands, how column order is merged and
saved, and which palette a theme mode means. That is where the bugs that
survive to the user live when they are not tested this way.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import import_check  # noqa: E402

import_check.install_stubs()

import vtm_core as core  # noqa: E402
import vtm_drawer as drawer  # noqa: E402
import vtm_settings as settings  # noqa: E402
import vtm_theme as theme  # noqa: E402


# --------------------------------------------------------------------------
# fakes
# --------------------------------------------------------------------------


class FakeId(object):
    def __init__(self, value):
        self.Value = value


class FakeView(object):
    def __init__(self, value, name):
        self.Id = FakeId(value)
        self.Name = name


def make_cell(kind, value, text, editable=True):
    cell = core.Cell()
    cell.kind = kind
    cell.value = value
    cell.text = text
    cell.editable = editable
    return cell


def make_column(key, kind, options=None):
    column = core.ColumnDef(key, "col {0}".format(key))
    column.kind = kind
    column.options = options or []
    return column


DETAIL = [(1, "Coarse"), (2, "Medium"), (3, "Fine")]
PHASE_FILTER = [(0, "(None)"), (77, "Show All"), (78, "Show New")]


def make_row():
    row = core.TemplateRow(FakeView(501, "MEP - Plan"))
    row.cells = {
        -1: make_cell(core.KIND_TEXT, "Old note", "Old note"),
        -2: make_cell(core.KIND_INT, 100, "1 : 100"),
        -3: make_cell(core.KIND_YESNO, 1, "Yes"),
        -4: make_cell(core.KIND_CHOICE, 2, "Medium"),
        -5: make_cell(core.KIND_ELEMENT, 77, "Show All"),
        -6: make_cell(core.KIND_DOUBLE, None, "1200"),
        -7: make_cell(core.KIND_TEXT, "Locked", "Locked", editable=False),
    }
    row.controllable = set([-2, -4, -9])
    row.controlled = set([-2, -4])
    return row


COLUMNS = {
    -1: make_column(-1, core.KIND_TEXT),
    -2: make_column(-2, core.KIND_INT),
    -3: make_column(-3, core.KIND_YESNO, [(1, "Yes"), (0, "No")]),
    -4: make_column(-4, core.KIND_CHOICE, DETAIL),
    -5: make_column(-5, core.KIND_ELEMENT, PHASE_FILTER),
    -6: make_column(-6, core.KIND_DOUBLE),
    -7: make_column(-7, core.KIND_TEXT),
}


class Results(object):
    def __init__(self):
        self.failures = []
        self.count = 0

    def eq(self, label, got, want):
        self.count += 1
        if got != want:
            self.failures.append("{0}: got {1!r}, want {2!r}".format(label, got, want))


def stage(row, key, text, mode=core.MODE_VALUES):
    return core.stage_text(row, COLUMNS.get(key), key, text, mode)[0]


# --------------------------------------------------------------------------
# the checks
# --------------------------------------------------------------------------


def check_parsing(r):
    r.eq("parse_int plain", core.parse_int("50"), 50)
    r.eq("parse_int scale", core.parse_int("1 : 50"), 50)
    r.eq("parse_int scale tight", core.parse_int("1:200"), 200)
    r.eq("parse_int thousands", core.parse_int("1,000"), 1000)
    r.eq("parse_int junk", core.parse_int("fifty"), None)
    r.eq("parse_int blank", core.parse_int("  "), None)
    r.eq("parse_bool yes", core.parse_bool("Yes"), True)
    r.eq("parse_bool tick", core.parse_bool(core.TICK), True)
    r.eq("parse_bool dash", core.parse_bool(core.DASH), False)
    r.eq("parse_bool 0", core.parse_bool("0"), False)
    r.eq("parse_bool maybe", core.parse_bool("maybe"), None)
    r.eq("match_option case", core.match_option(DETAIL, "fine"), (3, "Fine"))
    r.eq("match_option miss", core.match_option(DETAIL, "Ultra"), None)
    r.eq("match_option none word", core.match_option(PHASE_FILTER, "none"), (0, "(None)"))
    r.eq("match_option blank", core.match_option(PHASE_FILTER, ""), (0, "(None)"))
    r.eq("match_option blank, no none option", core.match_option(DETAIL, ""), None)


def check_staging(r):
    row = make_row()
    r.eq("text new", stage(row, -1, "New note"), core.STAGED)
    r.eq("text held", row.edits.get(-1), "New note")
    r.eq("text back to original", stage(row, -1, "Old note"), core.SAME)
    r.eq("text edit cleared", -1 in row.edits, False)

    r.eq("scale typed as scale", stage(row, -2, "1 : 50"), core.STAGED)
    r.eq("scale value", row.edits.get(-2), 50)
    r.eq("scale shows as scale", row.edit_text.get(-2), "1 : 50")
    r.eq("scale typed bare, same", stage(row, -2, "100"), core.SAME)
    r.eq("scale cleared", -2 in row.edits, False)
    r.eq("scale junk", stage(row, -2, "big"), core.SKIPPED)

    r.eq("yes/no to no", stage(row, -3, "no"), core.STAGED)
    r.eq("yes/no value", (row.edits.get(-3), row.edit_text.get(-3)), (0, "No"))
    r.eq("yes/no back", stage(row, -3, "YES"), core.SAME)
    r.eq("yes/no junk", stage(row, -3, "perhaps"), core.SKIPPED)

    r.eq("choice by label", stage(row, -4, "fine"), core.STAGED)
    r.eq("choice value", (row.edits.get(-4), row.edit_text.get(-4)), (3, "Fine"))
    r.eq("choice unknown", stage(row, -4, "Ultra"), core.SKIPPED)
    r.eq("choice unknown keeps edit", row.edits.get(-4), 3)

    r.eq("element to none", stage(row, -5, ""), core.STAGED)
    r.eq("element none value", row.edits.get(-5), 0)

    r.eq("double new", stage(row, -6, "1500"), core.STAGED)
    r.eq("double same", stage(row, -6, "1200"), core.SAME)

    r.eq("read only", stage(row, -7, "x"), core.SKIPPED)
    r.eq("not on template", stage(row, -99, "x"), core.SKIPPED)
    r.eq("used column", stage(row, core.KEY_USED, "3"), core.SKIPPED)

    r.eq("name blank", stage(row, core.KEY_NAME, " "), core.SKIPPED)
    r.eq("name new", stage(row, core.KEY_NAME, "MEP - Plan 2"), core.STAGED)
    r.eq("name back", stage(row, core.KEY_NAME, "MEP - Plan"), core.SAME)
    r.eq("name cleared", core.KEY_NAME in row.edits, False)

    ticks = core.MODE_CONTROLLED
    r.eq("tick off", stage(row, -2, core.DASH, ticks), core.STAGED)
    r.eq("tick off held", row.flag_edits.get(-2), False)
    r.eq("tick back on", stage(row, -2, "yes", ticks), core.SAME)
    r.eq("tick cleared", -2 in row.flag_edits, False)
    r.eq("tick on, not controlled", stage(row, -9, core.TICK, ticks), core.STAGED)
    r.eq("tick not offered", stage(row, -3, core.TICK, ticks), core.SKIPPED)
    r.eq("tick junk", stage(row, -4, "sometimes", ticks), core.SKIPPED)
    r.eq("tick on name", stage(row, core.KEY_NAME, core.TICK, ticks), core.SKIPPED)


def check_clipboard(r):
    values = {(0, 0): "a", (0, 1): "b", (1, 1): "d"}
    text = core.copy_text(set(values), lambda row, col: values[(row, col)])
    r.eq("copy ragged keeps the gap", text, "a\tb\r\n\td")
    r.eq("copy nothing", core.copy_text(set(), lambda row, col: ""), "")
    r.eq("copy flattens tabs", core.copy_text(set([(0, 0)]), lambda a, b: "x\ty"), "x y")

    r.eq("parse Excel block", core.parse_clipboard("a\tb\r\nc\td\r\n"),
         [["a", "b"], ["c", "d"]])
    r.eq("parse single", core.parse_clipboard("x"), [["x"]])
    r.eq("parse empty", core.parse_clipboard(""), [[""]])
    r.eq("parse none", core.parse_clipboard(None), [])

    one = [["Fine"]]
    picked = set([(0, 2), (3, 2), (5, 4)])
    r.eq("one value into every cell",
         core.paste_plan(one, picked, 10, 10),
         [(0, 2, "Fine"), (3, 2, "Fine"), (5, 4, "Fine")])

    block = [["a", "b"], ["c", "d"]]
    r.eq("block from the top-left",
         core.paste_plan(block, set([(5, 2)]), 10, 10),
         [(5, 2, "a"), (5, 3, "b"), (6, 2, "c"), (6, 3, "d")])
    r.eq("block clipped at the bottom edge",
         core.paste_plan(block, set([(9, 2)]), 10, 10),
         [(9, 2, "a"), (9, 3, "b")])
    r.eq("block clipped at the right edge",
         core.paste_plan(block, set([(0, 9)]), 10, 10),
         [(0, 9, "a"), (1, 9, "c")])

    row_block = [["x", "y"]]
    rect = set([(r_, c_) for r_ in range(1, 4) for c_ in range(0, 2)])
    r.eq("a row tiled down a taller selection",
         core.paste_plan(row_block, rect, 10, 10),
         [(1, 0, "x"), (1, 1, "y"), (2, 0, "x"), (2, 1, "y"),
          (3, 0, "x"), (3, 1, "y")])

    col_block = [["p"], ["q"]]
    three = set([(0, 0), (1, 0), (2, 0)])
    r.eq("no tiling when it does not divide",
         core.paste_plan(col_block, three, 10, 10),
         [(0, 0, "p"), (1, 0, "q")])
    ragged = set([(0, 0), (1, 1)])
    r.eq("no tiling over a ragged selection",
         core.paste_plan(row_block, ragged, 10, 10),
         [(0, 0, "x"), (0, 1, "y")])
    r.eq("nothing selected", core.paste_plan(one, set(), 10, 10), [])


def check_order(r):
    r.eq("merge keeps saved order, slots new ones",
         settings.merge_order([3, 1], [1, 2, 3, 4]), [3, 4, 1, 2])
    r.eq("merge drops what has gone",
         settings.merge_order([9, 1], [1, 2]), [1, 2])
    r.eq("merge from nothing", settings.merge_order([], [1, 2, 3]), [1, 2, 3])
    r.eq("merge, new first column",
         settings.merge_order([2, 3], [1, 2, 3]), [1, 2, 3])

    full = ["a", "b", "c", "d", "e"]
    r.eq("reorder leaves hidden columns where they were",
         settings.reorder_full(full, ["c", "a", "e"]), ["c", "b", "a", "d", "e"])
    r.eq("reorder, nothing moved", settings.reorder_full(full, ["a", "c"]), full)

    fixed = settings.FIXED_KEYS
    r.eq("freeze the identity block", settings.leading_frozen(list(fixed) + [5]), 4)
    r.eq("freeze stops at a parameter",
         settings.leading_frozen([fixed[0], fixed[1], 5, fixed[2]]), 2)
    r.eq("Used dragged right is not frozen",
         settings.leading_frozen([fixed[0], 5, 6, fixed[2]]), 1)
    r.eq("nothing frozen", settings.leading_frozen([5, fixed[0]]), 0)


def check_settings(r):
    r.eq("token, fixed", settings.key_token("__name__", "Template Name"), "__name__")
    r.eq("token, built-in", settings.key_token(-1005112, "Scale"), "b:-1005112")
    r.eq("token, by name", settings.key_token(331, "BGL|View;Group="), "n:BGL View Group")

    columns = {"__name__": "Template Name", -5: "Scale", 331: "BGL Group",
               332: "BGL Group"}
    mapping = settings.token_map(columns)
    r.eq("token map round trip",
         settings.tokens_to_keys(["b:-5", "n:BGL Group", "n:Missing", "__name__"],
                                 mapping)[:2], [-5, mapping["n:BGL Group"]])
    r.eq("token map drops unknown",
         len(settings.tokens_to_keys(["n:Missing"], mapping)), 0)

    r.eq("carry another project's column",
         settings.carry_unknown(["b:1", "n:A"], ["b:1", "n:X", "n:A", "n:Y"],
                                set(["b:1", "n:A"])),
         ["b:1", "n:X", "n:A", "n:Y"])
    r.eq("carry, nothing foreign",
         settings.carry_unknown(["n:A", "b:1"], ["b:1", "n:A"], set(["b:1", "n:A"])),
         ["n:A", "b:1"])

    widths = settings.merge_widths("n:Other:210;b:-5:90", {-5: 140, 331: 12},
                                   {-5: "Scale", 331: "BGL Group"})
    r.eq("widths keep foreign, update own, drop silly", widths,
         "b:-5:140;n:Other:210")
    r.eq("widths decode", settings.decode_widths(widths, {"b:-5": -5}), {-5: 140})
    r.eq("widths decode junk", settings.decode_widths("b:-5:x;nope;b:-5:5", {"b:-5": -5}),
         {})

    r.eq("reset forgets this model's widths, hidden ones too",
         settings.forget_widths("b:-5:140;n:Hidden:90;n:Other:210",
                                set(["b:-5", "n:Hidden"])), "n:Other:210")
    r.eq("reset with nothing saved", settings.forget_widths("", set(["b:-5"])), "")

    data = settings.parse("theme=light\ncolumn_order=b:-5|n:A=B\nnot_a_key=1\n")
    r.eq("parse a value holding '='", data["column_order"], "b:-5|n:A=B")
    r.eq("parse ignores unknown keys", "not_a_key" in data, False)
    r.eq("parse fills defaults", data["width"], settings.DEFAULTS["width"])
    again = settings.parse(settings.render(data))
    r.eq("render / parse round trip", again, data)
    r.eq("damaged file falls back", settings.parse("\x00garbage")["theme"], "follow")


class Darkish(object):
    """UITheme.Dark is 0: falsy, but it is still a reading."""

    def __bool__(self):
        return False

    __nonzero__ = __bool__

    def ToString(self):
        return "Dark"


class FakeManager(object):
    CurrentCanvasTheme = Darkish()
    CurrentTheme = None


class FakeColour(object):
    def __init__(self, value):
        self.Red = self.Green = self.Blue = value


class FakeApp(object):
    def __init__(self, value):
        self.BackgroundColor = FakeColour(value)


class FakeUIApp(object):
    def __init__(self, value):
        self.Application = FakeApp(value)


def check_theme(r):
    r.eq("mode cycle", [theme.next_mode(m) for m in theme.MODES],
         [theme.DARK, theme.LIGHT, theme.FOLLOW])
    r.eq("mode junk", theme.normalise_mode("purple"), theme.FOLLOW)
    r.eq("mode label", theme.mode_label("follow"), "Auto")
    r.eq("fixed dark", theme.resolve("dark"), theme.DARK)
    r.eq("fixed light", theme.resolve("light"), theme.LIGHT)
    r.eq("luminance dark", theme.luminance_theme(30, 30, 33), theme.DARK)
    r.eq("luminance light", theme.luminance_theme(250, 250, 250), theme.LIGHT)

    ui = sys.modules["Autodesk.Revit.UI"]
    saved = ui._cache.pop("UIThemeManager", None)
    ui._allowed = []                       # a release with no UIThemeManager
    try:
        r.eq("follow, no manager, light canvas",
             theme.resolve("follow", FakeUIApp(255)), theme.LIGHT)
        r.eq("follow, no manager, dark canvas",
             theme.resolve("follow", FakeUIApp(20)), theme.DARK)
        r.eq("follow, nothing to read", theme.resolve("follow", None), theme.DARK)
    finally:
        ui._allowed = None
    ui._cache["UIThemeManager"] = FakeManager
    try:
        r.eq("follow, canvas Dark reads as dark though it is falsy",
             theme.resolve("follow", FakeUIApp(255)), theme.DARK)
    finally:
        ui._cache.pop("UIThemeManager", None)
        if saved is not None:
            ui._cache["UIThemeManager"] = saved

# --------------------------------------------------------------------------
# the drawer, driven against a stand-in window
# --------------------------------------------------------------------------


class Event(object):
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def fire(self, *args):
        for handler in list(self.handlers):
            handler(*args)


class FakeTimer(object):
    """Runs its ticks at once when started, until stopped."""

    def __init__(self):
        self.Tick = Event()
        self.running = False
        self.ticks = 0
        self.fail_start = False

    def Start(self):
        if self.fail_start:
            raise RuntimeError("no dispatcher")
        self.running = True
        while self.running and self.ticks < 2000:
            self.ticks += 1
            self.Tick.fire(self, None)

    def Stop(self):
        self.running = False


class Clock(object):
    """Moves 20 ms on every read."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        self.now += 0.02
        return self.now


class Part(object):
    def __init__(self, visibility="Visible"):
        self.Visibility = visibility


class Panel(object):
    def __init__(self, children):
        self.Children = children


class Header(Part):
    def __init__(self):
        Part.__init__(self)
        self.ActualHeight = 52.0
        self.CornerRadius = "5,5,0,0"
        self.BorderThickness = "0,0,0,1"
        self.Parent = None

    def TranslatePoint(self, point, window):
        return Spot(0.0, 1.0)


class Spot(object):
    def __init__(self, x, y):
        self.X, self.Y = x, y


class Root(object):
    def __init__(self, height):
        self.Height = float("nan")
        self.ActualHeight = height
        self.VerticalAlignment = "Stretch"
        self.pins = []

    def __setattr__(self, name, value):
        if name == "Height" and value == value and hasattr(self, "pins"):
            self.pins.append(value)
        object.__setattr__(self, name, value)


class Button(object):
    def __init__(self):
        self.Tag = None
        self.ToolTip = None
        self.Click = Event()


class Window(object):
    def __init__(self, left=100.0, top=100.0, width=1420.0, height=820.0, owner=None):
        self.Left, self.Top, self.Width, self.Height = left, top, width, height
        self.MinHeight = 520.0
        self.SizeToContent = "WidthAndHeight"
        self.Owner = owner
        self.Content = Root(height)
        self.Closed = Event()
        self.activated = 0
        self.dragged = 0
        self.tops = []

    def __setattr__(self, name, value):
        if name == "Top" and hasattr(self, "tops"):
            self.tops.append(value)
        object.__setattr__(self, name, value)

    @property
    def ActualWidth(self):
        return self.Width

    @property
    def ActualHeight(self):
        return self.Height

    def Activate(self):
        self.activated += 1

    def DragMove(self):
        self.dragged += 1


class Wpf(object):
    """Just enough of System.Windows for the drawer to run on CPython."""

    class Visibility(object):
        Visible = "Visible"
        Collapsed = "Collapsed"

    class VerticalAlignment(object):
        Top = "Top"
        Stretch = "Stretch"

    class SizeToContent(object):
        Manual = "Manual"

    class Double(object):
        NaN = float("nan")

    @staticmethod
    def Point(x, y):
        return Spot(x, y)

    @staticmethod
    def CornerRadius(radius):
        return "round {0}".format(radius)

    @staticmethod
    def Thickness(value):
        return "thick {0}".format(value)


PRIMARY = (0.0, 0.0, 1920.0, 1040.0)
ABOVE = (0.0, -1080.0, 1920.0, 1040.0)


def build(area=PRIMARY, owner=None, **window_args):
    window = Window(owner=owner, **window_args)
    header = Header()
    toolbar, body, footer = Part(), Part(), Part("Collapsed")
    header.Parent = Panel([header, toolbar, body, footer])
    grips = Part()
    button = Button()
    timer = FakeTimer()
    made = drawer.Drawer(window, header, button, grips=grips, timer=timer,
                         clock=Clock(), area=lambda w: area)
    return made, window, header, (toolbar, body, footer), grips, button, timer


def with_wpf(function):
    def wrapped(results):
        names = ("Visibility", "VerticalAlignment", "SizeToContent", "Double",
                 "Point", "CornerRadius", "Thickness")
        saved = dict((n, getattr(drawer, n)) for n in names)
        for name in names:
            setattr(drawer, name, getattr(Wpf, name))
        del drawer._LIVE[:]
        try:
            function(results)
        finally:
            for name in names:
                setattr(drawer, name, saved[name])
            del drawer._LIVE[:]
    wrapped.__name__ = function.__name__
    return wrapped


def check_drawer_maths(r):
    r.eq("ease starts at 0", drawer.ease_out(0), 0.0)
    r.eq("ease ends at 1", drawer.ease_out(1), 1.0)
    r.eq("ease out is fast away", drawer.ease_out(0.5), 0.875)
    r.eq("ease clamps", (drawer.ease_out(-1), drawer.ease_out(3)), (0.0, 1.0))
    r.eq("park on the primary", drawer.parked_top(PRIMARY, 54.0), 978.0)
    r.eq("park above another bar", drawer.parked_top(PRIMARY, 54.0, [54.0]), 920.0)
    r.eq("park on a monitor above", drawer.parked_top(ABOVE, 54.0), -102.0)
    saved = (100.0, 100.0, 1420.0, 820.0)
    r.eq("open where it was",
         drawer.expanded_rect(saved, (100.0, 978.0), (100.0, 978.0), PRIMARY), saved)
    r.eq("a nudge is not a move",
         drawer.expanded_rect(saved, (101.0, 977.0), (100.0, 978.0), PRIMARY), saved)
    r.eq("dragged: open from the bar, kept on screen",
         drawer.expanded_rect(saved, (300.0, 500.0), (100.0, 978.0), PRIMARY),
         (300.0, 220.0, 1420.0, 820.0))
    r.eq("dragged on a monitor above",
         drawer.expanded_rect(saved, (10.0, -500.0), (100.0, -102.0), ABOVE),
         (10.0, -860.0, 1420.0, 820.0))
    r.eq("wider than the screen sits at its left edge",
         drawer.expanded_rect((0.0, 0.0, 3000.0, 820.0), (400.0, 300.0),
                              (0.0, 978.0), PRIMARY)[0], 0.0)
    r.eq("ctrl+shift+H toggles", drawer.key_action("H", True, True, False, False),
         "toggle")
    r.eq("plain H is not ours", drawer.key_action("H", False, False, False, False),
         None)
    r.eq("parked: Escape opens", drawer.key_action("Escape", False, False, True, False),
         "expand")
    r.eq("parked: Enter opens", drawer.key_action("Return", False, False, True, False),
         "expand")
    r.eq("parked: F11 opens", drawer.key_action("F11", False, False, True, False),
         "expand")
    r.eq("parked: Ctrl+C swallowed", drawer.key_action("C", True, False, True, False),
         "swallow")
    r.eq("sliding: all swallowed", drawer.key_action("Escape", False, False, False, True),
         "swallow")


@with_wpf
def check_drawer_drive(r):
    made, window, header, parts, grips, button, timer = build()
    toolbar, body, footer = parts

    made.shrink()
    r.eq("parked", (made.shrunk, made.sliding), (True, False))
    r.eq("slid over several frames", timer.ticks > 5, True)
    tops = [t for t in window.tops]
    r.eq("slid downward the whole way", tops == sorted(tops), True)
    r.eq("lands at the bottom of the screen", window.Top, 978.0)
    r.eq("only the bar is left", window.Height, 54.0)
    r.eq("MinHeight relaxed", window.MinHeight, 0)
    r.eq("SizeToContent relaxed", window.SizeToContent, "Manual")
    r.eq("body hidden", (toolbar.Visibility, body.Visibility), ("Collapsed", "Collapsed"))
    r.eq("header kept", header.Visibility, "Visible")
    r.eq("header rounded all round", header.CornerRadius, "round 5")
    r.eq("grips parked", grips.Visibility, "Collapsed")
    r.eq("button is the green arrow", button.Tag, drawer.SHRUNK)
    r.eq("pinned for the slide", window.Content.pins[:1], [820.0])
    r.eq("released once parked", window.Content.VerticalAlignment, "Stretch")
    r.eq("true size while parked", made.true_size(), (1420.0, 820.0))

    made.shrink()
    r.eq("a second shrink is ignored", window.Top, 978.0)

    made.expand()
    r.eq("open", (made.shrunk, made.sliding), (False, False))
    r.eq("back where it was", (window.Left, window.Top, window.Height),
         (100.0, 100.0, 820.0))
    r.eq("MinHeight back", window.MinHeight, 520.0)
    r.eq("SizeToContent back", window.SizeToContent, "WidthAndHeight")
    r.eq("body back", (toolbar.Visibility, body.Visibility), ("Visible", "Visible"))
    r.eq("a part already hidden stays hidden", footer.Visibility, "Collapsed")
    r.eq("header corners back", header.CornerRadius, "5,5,0,0")
    r.eq("grips back", grips.Visibility, "Visible")
    r.eq("button back", button.Tag, None)
    r.eq("root unpinned", window.Content.Height != window.Content.Height, True)
    r.eq("activated", window.activated, 1)
    r.eq("no true size when open", made.true_size(), None)

    # the button and the keys
    button.Click.fire(button, None)
    r.eq("button shrinks", made.shrunk, True)

    class Args(object):
        ClickCount = 1
    r.eq("bar click drags", (made.header_down(Args()), window.dragged), (True, 1))
    Args.ClickCount = 2
    made.header_down(Args())
    r.eq("bar double-click opens", made.shrunk, False)
    r.eq("open: header is the window's", made.header_down(Args()), False)
    r.eq("open: Escape is the window's", made.handle_key("Escape", False, False), False)
    made.handle_key("H", True, True)
    r.eq("ctrl+shift+H shrinks", made.shrunk, True)
    r.eq("parked: Ctrl+C swallowed", made.handle_key("C", True, False), True)
    made.handle_key("Escape", False, False)
    r.eq("parked: Escape opens", made.shrunk, False)

    # dragged while parked
    made.shrink()
    window.Left, window.Top = 300.0, 500.0
    made.expand()
    r.eq("dragged bar opens from where it is", (window.Left, window.Top),
         (300.0, 220.0))


@with_wpf
def check_drawer_owner(r):
    main, main_window = build()[:2]
    dialog, dialog_window = build(owner=main_window, left=500.0, top=300.0,
                                  width=620.0, height=460.0)[:2]
    dialog.shrink()
    r.eq("dialog takes its owner down", main.shrunk, True)
    r.eq("owner parked at the bottom", main_window.Top, 978.0)
    r.eq("dialog parks just above", dialog_window.Top, 920.0)
    dialog.expand()
    r.eq("owner back when the dialog opens", (main.shrunk, main_window.Top),
         (False, 100.0))
    dialog.shrink()
    dialog_window.Closed.fire(dialog_window, None)
    r.eq("owner back when a parked dialog closes", main.shrunk, False)
    r.eq("closed dialog let go", dialog in drawer._LIVE, False)

    main.shrink()
    main.restore_now()
    r.eq("restore_now opens at once", (main.shrunk, main_window.Top), (False, 100.0))

    third, third_window, header, parts, grips, button, timer = build(area=ABOVE,
                                                                  top=-900.0)
    timer.fail_start = True
    third.shrink()
    r.eq("no timer: lands anyway", (third.shrunk, third.sliding), (True, False))
    r.eq("on the monitor above", third_window.Top, -102.0)


# --------------------------------------------------------------------------
# readability: every foreground on every background it is drawn on
# --------------------------------------------------------------------------


def _luminance(hex_text):
    hex_text = hex_text.lstrip("#")[-6:]
    channels = []
    for i in (0, 2, 4):
        c = int(hex_text[i:i + 2], 16) / 255.0
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast(a, b):
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


# (foreground, background, minimum WCAG ratio). 4.5 for body text, 3 for
# large or secondary text and glyphs.
PAIRS = [
    ("BrushText", "BrushWindow", 4.5), ("BrushText", "BrushGrid", 4.5),
    ("BrushText", "BrushField", 4.5), ("BrushText", "BrushBar", 4.5),
    ("BrushText", "BrushCard", 4.5), ("BrushText", "BrushRowAlt", 4.5),
    ("BrushText", "BrushSelection", 4.5), ("BrushText", "BrushRowHighlight", 4.5),
    ("BrushText", "BrushRowHover", 4.5), ("BrushText", "BrushHover", 4.5),
    ("BrushText", "BrushTipBg", 4.5), ("BrushText", "BrushHeaderFiltered", 4.5),
    ("BrushText", "BrushCopy", 4.5),
    ("BrushMuted", "BrushGrid", 3.0), ("BrushMuted", "BrushBar", 3.0),
    ("BrushMuted", "BrushField", 3.0), ("BrushMuted", "BrushCard", 3.0),
    ("BrushOrange", "BrushDirty", 3.0), ("BrushOrange", "BrushBar", 3.0),
    ("BrushOrange", "BrushCard", 3.0),
    ("BrushBlue", "BrushBar", 3.0), ("BrushBlue", "BrushGrid", 3.0),
    ("BrushGreen", "BrushBar", 3.0), ("BrushRed", "BrushGrid", 3.0),
    ("BrushOnAccent", "BrushGreen", 3.0),
]


def check_contrast(r):
    for name, palette in sorted(theme.PALETTES.items()):
        for fore, back, minimum in PAIRS:
            ratio = contrast(palette[fore], palette[back])
            r.eq("{0}: {1} on {2} at least {3}:1 (is {4:.2f})".format(
                name, fore, back, minimum, ratio), ratio >= minimum, True)


GROUPS = [check_parsing, check_staging, check_clipboard, check_order,
          check_settings, check_theme, check_drawer_maths, check_drawer_drive,
          check_drawer_owner, check_contrast]


def run(groups=None):
    results = Results()
    for group in groups or GROUPS:
        try:
            group(results)
        except Exception as error:
            results.failures.append("{0} raised {1}: {2}".format(
                group.__name__, type(error).__name__, error))
    return results


# --------------------------------------------------------------------------
# selftest
# --------------------------------------------------------------------------


def _broken_parse_int(text):
    try:
        return int(text)
    except Exception:
        return None


def _broken_paste_plan(block, selected, row_count, col_count):
    if not block or not selected:
        return []
    top = min(r for r, c in selected)
    left = min(c for r, c in selected)
    if len(block) == 1 and len(block[0]) == 1:
        return [(r, c, block[0][0]) for r, c in sorted(selected)]
    return [(top + i, left + j, v) for i, line in enumerate(block)
            for j, v in enumerate(line) if top + i < row_count and left + j < col_count]


def _broken_merge_order(saved, default):
    out = [k for k in saved if k in default]
    return out + [k for k in default if k not in out]


def _broken_leading_frozen(keys, limit=4):
    return min(limit, len([k for k in keys if k in settings.FIXED_KEYS]))


def _broken_carry_unknown(new, old, known):
    return list(new)


def _broken_reorder_full(full, shown):
    return list(shown) + [k for k in full if k not in shown]


def _broken_match_option(options, text):
    for value, label in options:
        if label == text:
            return value, label
    return None


def _broken_copy_text(cells, value_at):
    rows = sorted(set(r for r, c in cells))
    return u"\r\n".join(u"\t".join(value_at(r, c) for c in sorted(set(
        c for rr, c in cells if rr == r))) for r in rows)


def _broken_revit_theme(uiapp=None, fallback=theme.DARK):
    import Autodesk.Revit.UI as revit_ui
    manager = getattr(revit_ui, "UIThemeManager", None)
    value = getattr(manager, "CurrentCanvasTheme", None) if manager else None
    if value:                                 # the UITheme.Dark == 0 bug
        return theme.DARK if "dark" in value.ToString().lower() else theme.LIGHT
    if uiapp is not None:
        colour = uiapp.Application.BackgroundColor
        return theme.luminance_theme(colour.Red, colour.Green, colour.Blue)
    return fallback


def _broken_finish(self):
    """Forgets to clear sliding - the slide is never released."""
    self.timer.Stop()
    anim, self.anim = self.anim, None
    if anim is None:
        return
    frm, to, done, _began = anim
    self.place(frm, to, 1.0)
    done()


def _broken_opened(self):
    """Forgets to put MinHeight back."""
    self.pin(False)
    self.show_grips(True)
    self.set_button(False)
    self.saved = None
    self.parked = None


SELFTESTS = [
    ("a muddy dark palette passes", theme, "PALETTES",
     dict(theme.PALETTES, dark=dict(theme.PALETTES["dark"], BrushText="#6A7280")),
     check_contrast),
    ("linear slide", drawer, "ease_out", lambda p: max(0.0, min(1.0, p)),
     check_drawer_maths),
    ("parks on the primary from a monitor above", drawer, "parked_top",
     lambda area, bar, stacked=(), margin=8.0, gap=4.0: area[3] - margin - bar,
     check_drawer_maths),
    ("bars stacked on top of each other", drawer, "parked_top",
     lambda area, bar, stacked=(), margin=8.0, gap=4.0:
     area[1] + area[3] - margin - bar, check_drawer_owner),
    ("jumps back after a drag", drawer, "expanded_rect",
     lambda saved, bar, parked, area, tolerance=2.0: saved, check_drawer_maths),
    ("Escape closes a parked window", drawer, "key_action",
     lambda key, ctrl, shift, shrunk, sliding:
     "toggle" if (ctrl and shift and key == "H") else None, check_drawer_drive),
    ("body squashed, not drawn away", drawer.Drawer, "pin",
     lambda self, on: None, check_drawer_drive),
    ("slide never released", drawer.Drawer, "finish", _broken_finish,
     check_drawer_drive),
    ("MinHeight left at 0", drawer.Drawer, "opened", _broken_opened,
     check_drawer_drive),
    ("owner left parked after the dialog closes", drawer.Drawer, "forget",
     lambda self: drawer._LIVE.remove(self) if self in drawer._LIVE else None,
     check_drawer_owner),
    ("scale not read", core, "parse_int", _broken_parse_int, check_parsing),
    ("no tiling", core, "paste_plan", _broken_paste_plan, check_clipboard),
    ("case-sensitive choices", core, "match_option", _broken_match_option,
     check_parsing),
    ("ragged copy loses its gap", core, "copy_text", _broken_copy_text,
     check_clipboard),
    ("SAME leaves the edit held", core, "_clear", lambda row, key: None,
     check_staging),
    ("new columns land at the end", settings, "merge_order", _broken_merge_order,
     check_order),
    ("hidden columns move", settings, "reorder_full", _broken_reorder_full,
     check_order),
    ("Used frozen far right", settings, "leading_frozen", _broken_leading_frozen,
     check_order),
    ("other projects' columns forgotten", settings, "carry_unknown",
     _broken_carry_unknown, check_settings),
    ("reset keeps hidden widths", settings, "forget_widths",
     lambda text, known: text or u"", check_settings),
    ("Dark read as a failed read", theme, "revit_theme", _broken_revit_theme,
     check_theme),
]


def selftest():
    problems = []
    for label, module, name, broken, group in SELFTESTS:
        original = getattr(module, name)
        setattr(module, name, broken)
        try:
            if not run([group]).failures:
                problems.append("{0}: a broken {1}.{2} passed {3}.".format(
                    label, module.__name__, name, group.__name__))
        finally:
            setattr(module, name, original)
    return problems


def main(argv):
    if "--selftest" in argv:
        problems = selftest()
        if problems:
            sys.stderr.write("SELFTEST FAILED\n")
            for line in problems:
                sys.stderr.write("  " + line + "\n")
            return 1
        sys.stderr.write("bench_logic selftest: all {0} breakages caught\n".format(
            len(SELFTESTS)))
        return 0
    results = run()
    if results.failures:
        sys.stderr.write("FAILED\n")
        for line in results.failures:
            sys.stderr.write("  " + line + "\n")
        return 1
    sys.stderr.write("bench_logic: all {0} checks pass\n".format(results.count))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
