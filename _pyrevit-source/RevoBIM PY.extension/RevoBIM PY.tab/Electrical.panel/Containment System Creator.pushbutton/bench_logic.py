# -*- coding: utf-8 -*-
"""Logic bench for Containment System Creator.

Run under plain CPython 3 from this folder:

    python bench_logic.py              every check against the shipped code
    python bench_logic.py --selftest   prove every check by breaking the code

Two halves:

* **The drawer.** csc_drawer.py is loaded as it ships and driven against a
  stand-in window, header, glyphs, timer and clock - a whole shrink and reopen,
  owners going down together, keys, dragging the bar, a frame that throws,
  and the parking arithmetic including a monitor above the primary.
* **The naming rules.** v1.4.0 was rebuilt from the change history rather than
  from the installed files, so the pure naming functions are lifted out of
  script.py by name and re-proved against the cases that defined them in
  v1.0.0 - v1.2.0: the worked BGL_Ladder example, Trunking and Basket found
  through their fitting families, the generic family name ignored, the model's
  own spelling kept, the edit split.

``--selftest`` breaks the code in a specific way for each check, confirms the
breakage really changed the source, and confirms the check then fails.
"""

import ast
import os
import re
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
NAN = float("nan")
AREA = (0.0, 0.0, 1920.0, 1040.0)
ABOVE = (0.0, -1080.0, 1920.0, 1040.0)   # a monitor above the primary


def read(name):
    with open(os.path.join(HERE, name), "rb") as handle:
        return handle.read().decode("utf-8")


# ===========================================================================
# loading code under test
# ===========================================================================

def load_drawer(source):
    module = types.ModuleType("csc_drawer_under_test")
    exec(compile(source, "csc_drawer.py", "exec"), module.__dict__)
    return module


SCRIPT_NAMES = (
    "TRAY_KIND_DEFS", "UNFILTERED", "eid_value", "same_id", "get_name", "norm",
    "norm_map", "loose_replace", "split_parts", "raw_tokens", "kind_token_span",
    "kind_matches", "Kind", "tray_kinds", "best_kind", "family_signal",
    "assign_kind", "common_token_depth", "detect_kinds", "prefix_and_sep",
    "service_token", "shared_stem", "tag_kinds", "kinds_present",
    "types_for_kind", "suggest_type_name", "edit_split", "set_element_name",
)


def load_naming(source):
    """Lift the named top-level definitions out of script.py and run them on
    their own - script.py as a whole needs Revit."""
    module = ast.parse(source, "script.py")
    wanted = []
    for node in module.body:
        name = None
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            name = node.name
        elif (isinstance(node, ast.Assign) and len(node.targets) == 1
              and isinstance(node.targets[0], ast.Name)):
            name = node.targets[0].id
        if name in SCRIPT_NAMES:
            wanted.append(ast.get_source_segment(source, node))
    namespace = {"re": re}
    exec(compile("\n\n".join(wanted), "script.py (naming)", "exec"), namespace)
    missing = [n for n in SCRIPT_NAMES if n not in namespace]
    if missing:
        raise AssertionError("script.py lost: " + ", ".join(missing))
    return types.SimpleNamespace(**namespace)


# ===========================================================================
# stand-ins for WPF
# ===========================================================================

class Pt(object):
    def __init__(self, x, y):
        self.X = x
        self.Y = y


class FakeWpf(object):
    visible = "Visible"
    collapsed = "Collapsed"
    top = "Top"
    manual = "Manual"
    no_resize = "NoResize"
    top_prop = "TopProperty"
    height_prop = "HeightProperty"

    @staticmethod
    def corner(radius):
        return "corner{0}".format(radius)

    @staticmethod
    def point(x, y):
        return Pt(x, y)


class Element(object):
    def __init__(self, visibility="Visible"):
        self.Visibility = visibility
        self.Parent = None


class Header(Element):
    ActualHeight = 52.0

    def __init__(self):
        Element.__init__(self)
        self.CornerRadius = "5,5,0,0"

    def TranslatePoint(self, point, window):
        return Pt(0.0, 2.0)          # outer border 1 + grid margin 1


class Panel(object):
    def __init__(self, children):
        self.Children = children
        for child in children:
            child.Parent = self


class Content(object):
    def __init__(self, height):
        self.Height = NAN
        self.VerticalAlignment = "Stretch"
        self._height = height

    @property
    def ActualHeight(self):
        return self._height


class Button(object):
    ToolTip = None


class Window(object):
    def __init__(self, left=100.0, top=100.0, width=1080.0, height=710.0,
                 min_height=560.0, resize="CanResizeWithGrip"):
        self.Left = left
        self._top = top
        self.Width = width
        self.Height = height
        self.MinHeight = min_height
        self.SizeToContent = "Height"
        self.ResizeMode = resize
        self.Content = Content(height - 2.0)
        self.released = []
        self.activated = 0
        self.drags = 0
        self.top_writes = 0
        self.fail_on_write = None
        self.tops = []

    @property
    def Top(self):
        return self._top

    @Top.setter
    def Top(self, value):
        self.top_writes += 1
        if self.fail_on_write == self.top_writes:
            raise RuntimeError("frame threw")
        self._top = value
        self.tops.append(value)

    @property
    def ActualHeight(self):
        return self.Height

    @property
    def ActualWidth(self):
        return self.Width

    def BeginAnimation(self, prop, value):
        if value is None:
            self.released.append(prop)

    def Activate(self):
        self.activated += 1

    def DragMove(self):
        self.drags += 1


class Clock(object):
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        self.now += 0.02
        return self.now


class InstantTicker(object):
    """Runs every tick at once when started."""

    def __init__(self, interval_ms, callback):
        self.callback = callback
        self.running = False

    def start(self):
        self.running = True
        guard = 0
        while self.running and guard < 1000:
            self.callback()
            guard += 1

    def stop(self):
        self.running = False


class ManualTicker(object):
    """Ticks only when told to."""
    last = None

    def __init__(self, interval_ms, callback):
        self.callback = callback
        self.running = False
        ManualTicker.last = self

    def start(self):
        self.running = True

    def stop(self):
        self.running = False

    def step(self):
        if self.running:
            self.callback()


class Args(object):
    def __init__(self, clicks=1):
        self.ClickCount = clicks
        self.Handled = False


class Rig(object):
    """A window with everything the drawer touches."""

    def __init__(self, mod, ticker=InstantTicker, area=AREA, **window_kw):
        mod._SLOTS[:] = []
        self.window = Window(**window_kw)
        self.header = Header()
        self.hint = Element()
        self.body = Element()
        self.footer = Element()
        self.extra = Element("Collapsed")      # was already hidden
        self.panel = Panel([self.header, self.hint, self.body, self.footer,
                            self.extra])
        self.button = Button()
        self.shrink_glyph = Element("Visible")
        self.expand_glyph = Element("Collapsed")
        self.drawer = mod.WindowDrawer(
            self.window, self.header, self.button, self.shrink_glyph,
            self.expand_glyph, wpf=FakeWpf(), ticker=ticker, clock=Clock(),
            work_area=lambda w: area)


def joined_rig(mod, other, **window_kw):
    """A second window sharing the module's slots (no reset)."""
    keep = list(mod._SLOTS)
    rig = Rig(mod, **window_kw)
    mod._SLOTS[:] = keep
    return rig


# ===========================================================================
# checks - each raises AssertionError with a reason when it fails
# ===========================================================================

def expect(condition, message):
    if not condition:
        raise AssertionError(message)


def close(a, b):
    return abs(a - b) < 1e-6


def check_ease(mod, naming):
    expect(mod.ease_out(0.0) == 0.0 and mod.ease_out(1.0) == 1.0,
           "ease_out does not run 0 -> 1")
    expect(close(mod.ease_out(0.5), 0.875), "ease_out(0.5) is not cubic: {0}"
           .format(mod.ease_out(0.5)))
    values = [mod.ease_out(i / 20.0) for i in range(21)]
    expect(all(b >= a for a, b in zip(values, values[1:])),
           "ease_out is not monotonic")
    expect(mod.ease_out(-1) == 0.0 and mod.ease_out(2) == 1.0,
           "ease_out is not clamped")


def check_parking_maths(mod, naming):
    expect(mod.bar_height(52.0, 2.0) == 56.0, "bar height wrong")
    expect(close(mod.shrunk_top(AREA, 56.0, []), 976.0),
           "bar not 8px above the taskbar: {0}".format(
               mod.shrunk_top(AREA, 56.0, [])))
    expect(close(mod.shrunk_top(AREA, 56.0, [56.0]), 916.0),
           "second bar not stacked 4px above the first")
    expect(close(mod.shrunk_top(ABOVE, 56.0, []), -104.0),
           "monitor above the primary parks on the wrong screen: {0}".format(
               mod.shrunk_top(ABOVE, 56.0, [])))
    expect(mod.parked_left(1500.0, 1080.0, AREA) == 840.0,
           "parked bar runs off the right of the screen")
    expect(mod.free_slot([None, "a"]) == 0, "freed slot not reused")
    expect(mod.free_slot(["a"]) == 1, "next slot wrong")


def check_expand_rect(mod, naming):
    rect = mod.expand_rect(-50.0, -20.0, 1080.0, 710.0, (100.0, 976.0),
                           (100.0, 976.0), AREA)
    expect(rect == (-50.0, -20.0),
           "undragged bar did not reopen exactly where it was: {0}".format(rect))
    rect = mod.expand_rect(100.0, 100.0, 1080.0, 710.0, (1500.0, 990.0),
                           (100.0, 976.0), AREA)
    expect(rect == (840.0, 330.0),
           "dragged bar did not reopen kept on its screen: {0}".format(rect))
    rect = mod.expand_rect(100.0, 100.0, 1080.0, 1200.0, (100.0, 500.0),
                           (100.0, 976.0), AREA)
    expect(rect[1] == 0.0, "window taller than the screen not opened at its top")
    rect = mod.expand_rect(100.0, 100.0, 1080.0, 710.0, (100.0, -150.0),
                           (100.0, 976.0), ABOVE)
    expect(rect == (100.0, -750.0),
           "monitor above the primary reopened on the wrong screen: {0}"
           .format(rect))


def check_drawer_cycle(mod, naming):
    rig = Rig(mod)
    win = rig.window
    rig.drawer.shrink()
    expect(rig.drawer.state == mod.PARKED, "did not park")
    expect(win.Height == 56.0, "parked window is not just its bar: {0}"
           .format(win.Height))
    expect(close(win.Top, 976.0), "bar not 8px above the taskbar: {0}"
           .format(win.Top))
    expect(win.Left == 100.0, "bar moved sideways")
    expect(win.MinHeight == 0, "MinHeight not relaxed")
    expect(win.SizeToContent == "Manual", "SizeToContent not relaxed")
    expect(win.ResizeMode == "NoResize", "resize grip left on the parked bar")
    expect(set(win.released) >= {"TopProperty", "HeightProperty"},
           "held animations not released: {0}".format(win.released))
    for part in (rig.hint, rig.body, rig.footer, rig.extra):
        expect(part.Visibility == "Collapsed", "a part below the header shows")
    expect(rig.header.CornerRadius == "corner5", "parked bar corners not rounded")
    expect(win.Content.VerticalAlignment == "Stretch" and
           win.Content.Height != win.Content.Height,
           "body left pinned after landing")
    expect(rig.expand_glyph.Visibility == "Visible" and
           rig.shrink_glyph.Visibility == "Collapsed",
           "button did not turn into the green up arrow")
    expect(rig.button.ToolTip == mod.EXPAND_TIP, "tooltip not updated")
    expect(mod._SLOTS[0] is rig.drawer, "bar not in the bottom slot")

    win.released = []
    rig.drawer.expand()
    expect(rig.drawer.state == mod.OPEN, "did not reopen")
    expect((win.Left, win.Top, win.Height) == (100.0, 100.0, 710.0),
           "did not reopen exactly where it was: {0}".format(
               (win.Left, win.Top, win.Height)))
    expect(win.MinHeight == 560.0, "MinHeight not put back")
    expect(win.SizeToContent == "Height", "SizeToContent not put back")
    expect(win.ResizeMode == "CanResizeWithGrip", "resize grip not put back")
    for part in (rig.hint, rig.body, rig.footer):
        expect(part.Visibility == "Visible", "a part did not come back")
    expect(rig.extra.Visibility == "Collapsed",
           "a part that was already hidden came back visible")
    expect(rig.header.CornerRadius == "5,5,0,0", "header corners not put back")
    expect(rig.shrink_glyph.Visibility == "Visible" and
           rig.expand_glyph.Visibility == "Collapsed", "glyphs not swapped back")
    expect(win.activated == 1, "reopened window not activated")
    expect(not [s for s in mod._SLOTS if s is not None], "slot not freed")


def check_slide(mod, naming):
    rig = Rig(mod, ticker=ManualTicker)
    win = rig.window
    rig.drawer.shrink()
    expect(rig.drawer.state == mod.CLOSING, "slide did not start")
    expect(win.Height == 710.0,
           "window did not keep its full height on the way down")
    expect(win.Content.Height == 708.0 and win.Content.VerticalAlignment == "Top",
           "body not pinned for the slide")
    win.tops = []
    for _ in range(40):
        ManualTicker.last.step()
    tops = win.tops
    # the last eased frame and the landing can both be the end position
    distinct = sorted(set(round(t, 3) for t in tops))
    expect(len(distinct) >= 5, "no visible slide: {0} distinct frame(s)"
           .format(len(distinct)))
    expect(all(b >= a for a, b in zip(tops, tops[1:])), "slide not downward")
    expect(close(tops[-1], 976.0), "slide did not land on the bar position")
    first_half = tops[len(tops) // 2] - 100.0
    expect(first_half > (976.0 - 100.0) / 2.0, "slide is not eased out")


def check_drag_reopen(mod, naming):
    rig = Rig(mod)
    rig.drawer.shrink()
    rig.window.Left = 1500.0     # the bar carried along the taskbar
    rig.window.Top = 990.0
    rig.drawer.expand()
    expect((rig.window.Left, rig.window.Top) == (840.0, 330.0),
           "dragged bar did not reopen from where it sits, on screen: {0}"
           .format((rig.window.Left, rig.window.Top)))


def check_owners(mod, naming):
    main = Rig(mod)
    dialog = joined_rig(mod, main, left=300.0, top=150.0, width=700.0,
                        height=712.0, min_height=0.0, resize="NoResize")
    dialog.drawer.owner = main.drawer
    dialog.drawer.shrink()
    expect(main.drawer.parked, "dialog shrank but left its owner over Revit")
    expect(mod._SLOTS[0] is main.drawer and mod._SLOTS[1] is dialog.drawer,
           "bars not stacked owner below dialog")
    expect(close(dialog.window.Top, 916.0),
           "dialog bar not parked just above its owner's: {0}"
           .format(dialog.window.Top))
    dialog.drawer.expand()
    expect(main.drawer.state == mod.OPEN and dialog.drawer.state == mod.OPEN,
           "bringing the dialog back did not bring its owner back")
    dialog.drawer.shrink()
    dialog.drawer.on_closed(None, None)
    expect(main.drawer.state == mod.OPEN,
           "closing a parked dialog left its owner parked")
    expect(not [s for s in mod._SLOTS if s is not None], "slots not freed")


def check_keys(mod, naming):
    rig = Rig(mod)
    d = rig.drawer
    expect(d.key_action("A", False, False) is None, "open window lost a key")
    expect(d.key_action("Escape", False, False) == "close",
           "Esc no longer closes an open window")
    expect(d.key_action("H", True, True) == "drawer" and d.parked,
           "Ctrl+Shift+H did not shrink")
    expect(d.key_action("A", False, False) == "drawer" and d.parked,
           "a key reached the parked window")
    expect(d.key_action("Escape", False, False) == "drawer" and not d.parked,
           "Esc on a parked window did not bring it back")
    d.shrink()
    expect(d.key_action("Return", False, False) == "drawer" and not d.parked,
           "Enter on a parked window did not bring it back")
    d.shrink()
    expect(d.key_action("F11", False, False) == "drawer" and not d.parked,
           "F11 on a parked window did not bring it back")
    d.shrink()
    expect(d.key_action("H", True, True) == "drawer" and not d.parked,
           "Ctrl+Shift+H did not bring it back")


def check_busy(mod, naming):
    rig = Rig(mod, ticker=ManualTicker)
    rig.drawer.shrink()
    rig.drawer.toggle()
    expect(rig.drawer.state == mod.CLOSING, "a press mid-slide was acted on")
    expect(rig.drawer.key_action("Escape", False, False) == "drawer",
           "Esc mid-slide reached the window")


def check_frame_throws(mod, naming):
    rig = Rig(mod)
    rig.window.fail_on_write = 3
    rig.drawer.shrink()
    expect(rig.drawer.state == mod.PARKED, "a throwing frame stranded the window")
    expect(close(rig.window.Top, 976.0), "a throwing frame did not land")


def check_header_mouse(mod, naming):
    rig = Rig(mod)
    rig.drawer.header_down(None, Args(1))
    expect(rig.window.drags == 1, "a click on the header did not drag")
    rig.drawer.shrink()
    rig.drawer.header_down(None, Args(1))
    expect(rig.window.drags == 2, "the parked bar cannot be dragged")
    args = Args(2)
    rig.drawer.header_down(None, args)
    expect(rig.drawer.state == mod.OPEN and args.Handled,
           "double-click on the bar did not bring it back")


class Info(object):
    def __init__(self, name, family, fitting_families):
        self.name = name
        self.family_name = family
        self.fitting_family_names = fitting_families
        self.kind = None
        self.kind_label = ""
        self.kind_alias = None
        self.name_alias = None


WF = "Cable Tray with Fittings"


def tray_set():
    return [
        Info("BGL_Ladder_LV_SubMain", WF, ["BGL_Ladder_HorizontalBend"]),
        Info("BGL_CableTray_LV_SubMain", WF, ["BGL_CableTray_HorizontalBend"]),
        Info("BGL_Cable_Tray_Small_Power", WF, ["BGL_CableTray_Tee"]),
        Info("BGL_LV_SubMain_Trunk", WF, ["BGL_TrunkingTray_HorizontalBend"]),
        Info("BGL_Containment_Data", WF, ["BGL_Cable Basket_HorizontalBend"]),
        Info("BGL_Something_Else", WF, ["BGL_Generic_Bend"]),
    ]


def tagged(naming):
    infos = tray_set()
    naming.tag_kinds(infos, naming.tray_kinds())
    _, depth = naming.detect_kinds([i.name for i in infos])
    return dict((i.name, i) for i in infos), depth


def check_worked_example(mod, naming):
    infos, depth = tagged(naming)
    ladder = infos["BGL_Ladder_LV_SubMain"]
    expect(ladder.kind_label == "Cable Ladder", "ladder kind: " + ladder.kind_label)
    name = naming.suggest_type_name(ladder, depth, "ELV")
    expect(name == "BGL_Ladder_ELV", "worked example gives " + name)
    # a kind spelled across two tokens is cut after the second, not the first
    split = infos["BGL_Cable_Tray_Small_Power"]
    expect(split.kind_label == "Cable Tray", "two-token kind not found")
    name = naming.suggest_type_name(split, depth, "ELV")
    expect(name == "BGL_Cable_Tray_ELV", "two-token kind gives " + name)


def check_family_kinds(mod, naming):
    infos, depth = tagged(naming)
    trunk = infos["BGL_LV_SubMain_Trunk"]
    expect(trunk.kind_label == "Cable Trunking",
           "trunking not found through its fittings: " + repr(trunk.kind_label))
    name = naming.suggest_type_name(trunk, depth, "ELV")
    expect(name == "BGL_TrunkingTray_ELV",
           "trunking name not in the model's spelling: " + name)
    basket = infos["BGL_Containment_Data"]
    expect(basket.kind_label == "Cable Basket",
           "basket not found through its fittings: " + repr(basket.kind_label))
    expect(naming.suggest_type_name(basket, depth, "ELV") == "BGL_Cable Basket_ELV",
           "basket name wrong")
    expect(naming.family_signal("Cable Tray with Fittings") == "",
           "generic family name treated as a signal")
    expect(naming.family_signal("BGL_TrunkingTray with Fittings") ==
           "BGL_TrunkingTray", "custom family name lost")


def check_dropdown(mod, naming):
    infos, _ = tagged(naming)
    present, counts, unmatched = naming.kinds_present(
        list(infos.values()), naming.tray_kinds())
    expect([k.label for k in present] ==
           ["Cable Tray", "Cable Ladder", "Cable Trunking", "Cable Basket"],
           "dropdown order: {0}".format([k.label for k in present]))
    expect(unmatched == 1, "unmatched count: {0}".format(unmatched))
    expect(not naming.kind_matches("BGL_FlexConduit_LV", "Conduit"),
           "Conduit matched inside FlexConduit")


def check_edit_split(mod, naming):
    infos, depth = tagged(naming)
    ladder = infos["BGL_Ladder_LV_SubMain"]
    prefix, sep = naming.edit_split(ladder, depth)
    expect((prefix, sep) == ("BGL_Ladder", "_"), "ladder split: {0}".format(
        (prefix, sep)))
    expect(naming.service_token(ladder.name, prefix, sep) == "LV_SubMain",
           "ladder service part wrong")
    trunk = infos["BGL_LV_SubMain_Trunk"]
    prefix, sep = naming.edit_split(trunk, depth)
    expect((prefix, sep) == ("BGL", "_"), "trunking split: {0}".format(
        (prefix, sep)))
    expect(naming.loose_replace("LV Sub-Main", "LV_SubMain", "ELV") == "ELV",
           "fitting rename ignores separators wrongly")


def check_compat(mod, naming):
    class Id2026(object):
        def __init__(self, value):
            self.Value = value

        def __getattr__(self, name):
            raise AttributeError(name)

    class IdLegacy(object):
        def __init__(self, value):
            self.IntegerValue = value

        def __getattr__(self, name):
            raise AttributeError(name)

    expect(naming.eid_value(Id2026(123456)) == 123456,
           "ElementId on Revit 2026 not read")
    expect(naming.eid_value(IdLegacy(77)) == 77, "legacy ElementId not read")
    expect(naming.same_id(Id2026(5), IdLegacy(5)), "ids across releases differ")

    class Stubborn(object):
        Name = "old"

        def __setattr__(self, key, value):
            pass                              # Revit refusing quietly

    class Willing(object):
        Name = "old"

    expect(naming.set_element_name(Stubborn(), "new") is False,
           "a refused rename reported as done")
    expect(naming.set_element_name(Willing(), "new") is True,
           "a rename that took reported as failed")


CHECKS = [
    check_ease, check_parking_maths, check_expand_rect, check_drawer_cycle,
    check_slide, check_drag_reopen, check_owners, check_keys, check_busy,
    check_frame_throws, check_header_mouse, check_worked_example,
    check_family_kinds, check_dropdown, check_edit_split, check_compat,
]


# ===========================================================================
# selftest
# ===========================================================================

D = "csc_drawer.py"
S = "script.py"

BREAKAGES = [
    (check_ease, D, "cubic ease made quadratic",
     "    return 1.0 - inv * inv * inv", "    return 1.0 - inv * inv"),
    (check_parking_maths, D, "bars stacked without the gap",
     "        stacked += height + gap", "        stacked += height"),
    (check_expand_rect, D, "dragged bar not kept on its screen",
     "    left = clamp(bar_now[0], area[0], area[0] + area[2] - width)",
     "    left = bar_now[0]"),
    (check_drawer_cycle, D, "MinHeight never put back",
     "            window.MinHeight = saved.min_height", "            pass"),
    (check_drawer_cycle, D, "held animations not released on shrink",
     "        self._release()\n        self.saved = _Saved(window)",
     "        self.saved = _Saved(window)"),
    (check_drawer_cycle, D, "hidden parts all forced visible",
     "                child.Visibility = visibility",
     "                child.Visibility = self.wpf.visible"),
    (check_slide, D, "body not pinned for the slide",
     "            content.VerticalAlignment = self.wpf.top", "            pass"),
    (check_slide, D, "height cut before the slide",
     "        self.state = CLOSING\n",
     "        self.state = CLOSING\n        window.Height = self.bar\n"),
    (check_drag_reopen, D, "dragged bar jumps back",
     "    if not moved:\n        return saved_left, saved_top",
     "    if True:\n        return saved_left, saved_top"),
    (check_owners, D, "dialog leaves its owner up",
     "            self.owner.shrink(animate=False)", "            pass"),
    (check_keys, D, "keys reach a parked window",
     "            # every other key is swallowed: nothing acts on a hidden window\n"
     "            return True",
     "            # every other key is swallowed: nothing acts on a hidden window\n"
     "            return name in REOPEN_KEYS"),
    (check_busy, D, "keys acted on mid-slide",
     "        if self.busy:\n            return True\n        hotkey",
     "        hotkey"),
    (check_frame_throws, D, "a throwing frame does not land",
     "            # a frame that throws lands the window rather than stranding it\n"
     "            self._stop()\n            self._finish(self._to, self._done)",
     "            # a frame that throws lands the window rather than stranding it\n"
     "            self._stop()"),
    (check_header_mouse, D, "double-click ignored on the bar",
     "                if self.parked:\n                    self.expand()\n"
     "                    args.Handled = True",
     "                if False:\n                    self.expand()\n"
     "                    args.Handled = True"),
    (check_worked_example, S, "kind cut in the wrong place",
     "        last_token = span[1] - 1", "        last_token = span[0]"),
    (check_family_kinds, S, "generic family name treated as a signal",
     '    if norm(stripped) in ("cabletray", "conduit", ""):\n        return ""',
     '    if norm(stripped) in ("cabletray", "conduit", ""):\n        return stripped'),
    (check_family_kinds, S, "canonical spelling instead of the model's",
     '                return "".join(parts[2 * span[0]:2 * span[1] - 1])',
     "                return alias"),
    (check_dropdown, S, "kind matched inside a longer token",
     "            if joined == needle:", "            if needle in joined:"),
    (check_edit_split, S, "trunking split after the wrong token",
     "    return shared_stem(info.name, auto_depth)",
     "    return prefix_and_sep(info.name, None, auto_depth)"),
    (check_compat, S, "IntegerValue preferred over Value",
     "    try:\n        return element_id.Value\n",
     "    try:\n        return element_id.IntegerValue\n"),
    (check_compat, S, "rename not read back",
     "    if get_name(elem) == new_name:\n        return True",
     "    if True:\n        return True"),
]


def run_check(check, drawer_src, script_src):
    try:
        check(load_drawer(drawer_src), load_naming(script_src))
        return None
    except AssertionError as err:
        return str(err)
    except Exception as err:
        return "{0}: {1}".format(type(err).__name__, err)


def run():
    drawer_src, script_src = read(D), read(S)
    failures = 0
    for check in CHECKS:
        problem = run_check(check, drawer_src, script_src)
        print("  {0} {1}{2}".format("ok  " if problem is None else "FAIL",
                                    check.__name__,
                                    "" if problem is None else " - " + problem))
        failures += problem is not None
    return failures


def selftest():
    sources = {D: read(D), S: read(S)}
    covered = set()
    failures = 0
    for check, target, label, old, new in BREAKAGES:
        if run_check(check, sources[D], sources[S]) is not None:
            print("  FAIL {0}: fails on the clean code".format(check.__name__))
            failures += 1
            continue
        if old not in sources[target]:
            print("  FAIL {0}: breakage '{1}' not found in {2}".format(
                check.__name__, label, target))
            failures += 1
            continue
        broken = dict(sources)
        broken[target] = sources[target].replace(old, new, 1)
        if broken[target] == sources[target]:
            print("  FAIL {0}: breakage '{1}' changed nothing".format(
                check.__name__, label))
            failures += 1
            continue
        problem = run_check(check, broken[D], broken[S])
        if problem is None:
            print("  FAIL {0} misses {1}".format(check.__name__, label))
            failures += 1
        else:
            print("  ok   {0} catches {1}".format(check.__name__, label))
            covered.add(check)
    for check in CHECKS:
        if check not in covered:
            print("  FAIL {0} has no proving breakage".format(check.__name__))
            failures += 1
    return failures


def main(argv):
    if "--selftest" in argv:
        print("bench_logic --selftest")
        failures = selftest()
    else:
        print("bench_logic")
        failures = run()
    print("{0} problem(s)".format(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
