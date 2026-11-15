# -*- coding: utf-8 -*-
u"""RevoBIM Addins - logic bench.

    python bench_logic.py
    python bench_logic.py --selftest

The rules that decide anything - what the folder walk finds, what a button is
called, what the search matches, how the groups come out, what the settings
round trip to - are plain functions with no WPF in them, so they can be run
here against a synthetic extensions tree with no Revit anywhere.  That is the
part of a tool where bugs can be found; the part that can only be tested by
clicking is where they survive.
"""

from __future__ import print_function

import io
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import import_check  # noqa: E402

import_check.install_stubs()

import rba_core  # noqa: E402
import rba_scan  # noqa: E402
import rba_theme  # noqa: E402
import rba_ui  # noqa: E402
import rba_window  # noqa: E402
import rba_shortcuts  # noqa: E402
import rba_drawer  # noqa: E402
import rba_favs  # noqa: E402
import rba_tween  # noqa: E402

RESULTS = []


def check(title, condition, detail=u""):
    RESULTS.append((title, bool(condition), detail))
    return bool(condition)


# ----------------------------------------------------------------------
# a synthetic extensions tree
# ----------------------------------------------------------------------

def put(path, text=u""):
    folder = os.path.dirname(path)
    if not os.path.isdir(folder):
        os.makedirs(folder)
    handle = io.open(path, "w", encoding="utf-8")
    try:
        handle.write(text)
    finally:
        handle.close()


def build_tree():
    root = tempfile.mkdtemp(prefix="rba_tree_")
    ext = os.path.join(root, "RevoBIM PY.extension")
    tab = os.path.join(ext, "RevoBIM PY.tab")

    # a plain pushbutton whose title comes from bundle.yaml
    button = os.path.join(tab, "Coordination.panel", "Nudge Up.pushbutton")
    put(os.path.join(button, "bundle.yaml"), u"title: Nudge Up\ntooltip: Raise services\n")
    put(os.path.join(button, "script.py"), u"# nothing\n")

    # a pushbutton with no bundle.yaml - title from __title__, tip from __doc__
    button2 = os.path.join(tab, "Coordination.panel", "Match Offset.pushbutton")
    put(os.path.join(button2, "script.py"),
        u'__title__ = "Match Offset"\n__doc__ = "Match an elevation"\n')

    # a pushbutton with neither - title from the folder name
    button3 = os.path.join(tab, "Management.panel", "Sheet Manager.pushbutton")
    put(os.path.join(button3, "script.py"), u"# nothing\n")

    # a button whose NAME says nothing about what it does: the whole reason
    # for the secondary search. Its description lives in a parenthesised run
    # of strings and in a module docstring, which is how the real tools in
    # this extension are actually written.
    button4 = os.path.join(tab, "BWIC Tools.panel", "Hole Maker.pushbutton")
    # NOTE the coding line: every real script in this extension has one, and
    # a docstring reader that only lstrips finds nothing past it.
    put(os.path.join(button4, "script.py"),
        u'# -*- coding: utf-8 -*-\n'
        u'u"""Places penetration families where services cross walls."""\n'
        u'__title__ = "Hole Maker"\n'
        u'__doc__ = ("Sleeve and puddle flange placement, sized from the real "\n'
        u'           "cross section of the service.")\n')

    # a __doc__ with escaped line breaks in it, as BWIC Penetration has
    button5 = os.path.join(tab, "BWIC Tools.panel", "Breaks.pushbutton")
    put(os.path.join(button5, "script.py"),
        u'__title__ = "Breaks"\n'
        u'__doc__ = "Wall and Slab tabs.\\n\\nWall: select the services."\n')

    # a pulldown with a child, and an icon only on the pulldown
    pulldown = os.path.join(tab, "Management.panel", "Routines.pulldown")
    put(os.path.join(pulldown, "bundle.yaml"), u"title: Routines\n")
    put(os.path.join(pulldown, "icon.png"), u"x")
    child = os.path.join(pulldown, "QFR Remover.pushbutton")
    put(os.path.join(child, "script.py"), u'__title__ = "QFR\\nRemover"\n')

    # something that is not a button at all
    put(os.path.join(tab, "Management.panel", "notes.txt"), u"ignore me")
    return root, ext


# ----------------------------------------------------------------------
# the checks
# ----------------------------------------------------------------------

def check_scan(root, ext):
    items = rba_scan.scan([root])
    titles = sorted([item.title for item in items])
    check(u"the walk finds every launchable button and nothing else",
          titles == [u"Breaks", u"Hole Maker", u"Match Offset", u"Nudge Up",
                     u"QFR Remover", u"Sheet Manager"],
          u"got {0}".format(titles))

    by_title = {}
    for item in items:
        by_title[item.title] = item

    check(u"bundle.yaml title wins", by_title[u"Nudge Up"].title == u"Nudge Up")
    check(u"__title__ is used where there is no bundle.yaml",
          by_title[u"Match Offset"].title == u"Match Offset")
    check(u"the folder name is used where there is neither",
          by_title[u"Sheet Manager"].title == u"Sheet Manager")
    check(u"a newline in __title__ is flattened, as the ribbon flattens it",
          by_title[u"QFR Remover"].title == u"QFR Remover")
    check(u"__doc__ becomes the tooltip",
          by_title[u"Match Offset"].tooltip == u"Match an elevation")
    check(u"bundle.yaml tooltip wins",
          by_title[u"Nudge Up"].tooltip == u"Raise services")
    check(u"a pulldown child reports the pulldown as its parent",
          by_title[u"QFR Remover"].parent == u"Routines")
    check(u"a pulldown child reports the panel, not the pulldown, as its panel",
          by_title[u"QFR Remover"].panel == u"Management")
    check(u"a child with no icon inherits the pulldown's",
          by_title[u"QFR Remover"].icon.endswith(u"icon.png"))
    check(u"a button with no icon anywhere gets none",
          by_title[u"Sheet Manager"].icon == u"")
    check(u"scanning an .extension folder directly works too",
          len(rba_scan.scan([ext])) == 6)
    check(u"the same folder scanned twice does not double up",
          len(rba_scan.scan([root, ext])) == 6)

    described = by_title[u"Hole Maker"].description
    check(u"a parenthesised __doc__ run is read into the description",
          u"cross section" in described, u"got {0}".format(described))
    check(u"the module docstring is read into the description too",
          u"penetration" in described, u"got {0}".format(described))
    check(u"the bundle tooltip is in the description as well",
          u"Raise services" in by_title[u"Nudge Up"].description)
    breaks = by_title[u"Breaks"].description
    check(u"an escaped line break in __doc__ leaves no stray n behind",
          u" n " not in breaks and u"tabs." in breaks and u"Wall:" in breaks,
          u"got {0!r}".format(breaks))
    check(u"the description is not pooled into the name",
          u"penetration" not in rba_core.normalise(by_title[u"Hole Maker"].name_text))
    return items


def check_search(items):
    check(u"every word typed has to match",
          rba_core.matches_search(u"Sheet Manager Management", [u"sheet", u"man"]))
    check(u"a word that is not there fails the match",
          not rba_core.matches_search(u"Sheet Manager", [u"sheet", u"duct"]))
    check(u"word order does not matter",
          rba_core.matches_search(u"Nudge Up Coordination", [u"up", u"nudge"]))
    check(u"an empty search matches everything",
          rba_core.matches_search(u"anything", []))
    check(u"the search reaches the panel and tab, not just the name",
          rba_core.matches_search(
              [item for item in items if item.title == u"Nudge Up"][0].search_text,
              [u"coordination"]))
    groups = rba_scan.group_items(items, group_by=u"panel", search=u"nudge")
    found = [item.title for group in groups for item in group.items]
    check(u"a search narrows the list", found == [u"Nudge Up"], u"got {0}".format(found))


def check_two_tier(items):
    primary, secondary = rba_scan.search_split(items, u"penetration")
    check(u"a word only in the description does not match on name",
          [entry.title for entry in primary] == [], u"got {0}".format(primary))
    check(u"but it does come back in the secondary list",
          [entry.title for entry in secondary] == [u"Hole Maker"],
          u"got {0}".format([entry.title for entry in secondary]))

    primary, secondary = rba_scan.search_split(items, u"hole")
    check(u"a name match lands in the primary list",
          [entry.title for entry in primary] == [u"Hole Maker"])
    check(u"and is not repeated in the secondary list", secondary == [])

    primary, secondary = rba_scan.search_split(items, u"")
    check(u"an empty search returns everything as primary",
          len(primary) == len(items) and secondary == [])

    primary, secondary = rba_scan.search_split(items, u"zzzz")
    check(u"a search matching nothing returns two empty lists",
          primary == [] and secondary == [])

    primary, secondary = rba_scan.search_split(items, u"sleeve flange")
    check(u"the secondary list needs every word too, same as the primary",
          [entry.title for entry in secondary] == [u"Hole Maker"])

    primary, secondary = rba_scan.search_split(items, u"management")
    check(u"a panel name is a description match, not a name match",
          u"Sheet Manager" in [entry.title for entry in secondary] or
          u"Sheet Manager" in [entry.title for entry in primary])


def check_grouping(items):
    groups = rba_scan.group_items(items, group_by=u"panel")
    titles = [group.title for group in groups]
    check(u"grouping by panel gives one group per panel",
          sorted(titles) == [u"BWIC Tools", u"Coordination", u"Management"],
          u"got {0}".format(titles))
    counts = dict([(group.title, len(group.items)) for group in groups])
    check(u"a pulldown child is grouped under its panel", counts[u"Management"] == 2)
    by_tab = rba_scan.group_items(items, group_by=u"tab")
    check(u"grouping by tab gives one group", len(by_tab) == 1)
    order = [item.title for item in
             [group for group in groups if group.title == u"Management"][0].items]
    check(u"items inside a group come out in natural order",
          order == [u"QFR Remover", u"Sheet Manager"], u"got {0}".format(order))
    for item in items:
        item.live = (item.title != u"Sheet Manager")
    hidden = rba_scan.group_items(items, group_by=u"panel", hide_unloaded=True)
    remaining = [entry.title for group in hidden for entry in group.items]
    check(u"hide_unloaded drops an addin that is not on the ribbon",
          u"Sheet Manager" not in remaining)
    shown = rba_scan.group_items(items, group_by=u"panel", hide_unloaded=False)
    check(u"with hide_unloaded off it is still listed",
          u"Sheet Manager" in [entry.title for group in shown for entry in group.items])


def check_natural_order():
    values = [u"P-10", u"P-2", u"P-100", u"P-9"]
    values.sort(key=rba_core.natural_key)
    check(u"natural order, not string order",
          values == [u"P-2", u"P-9", u"P-10", u"P-100"], u"got {0}".format(values))


def check_settings():
    folder = tempfile.mkdtemp(prefix="rba_set_")
    original = rba_core.appdata_root
    rba_core.appdata_root = lambda: folder
    try:
        values = rba_core.load_settings()
        check(u"a missing settings file gives the defaults",
              values[u"icon_size"] == rba_core.DEFAULTS[u"icon_size"])
        values[u"icon_size"] = u"48"
        values[u"folders"] = u"C:\\one|C:\\two"
        check(u"settings save", rba_core.save_settings(values))
        back = rba_core.load_settings()
        check(u"settings round trip", back[u"icon_size"] == u"48")
        check(u"a pipe separated list round trips",
              rba_core.as_list(back, u"folders") == [u"C:\\one", u"C:\\two"])

        path = rba_core.settings_path()
        handle = io.open(path, "a", encoding="utf-8")
        try:
            handle.write(u"some_key_from_a_later_version=7\n")
        finally:
            handle.close()
        check(u"an unknown key is ignored rather than breaking the load",
              rba_core.load_settings()[u"icon_size"] == u"48")

        handle = io.open(path, "w", encoding="utf-8")
        try:
            handle.write(u"this file is not key=value at all\n\x00\n")
        finally:
            handle.close()
        check(u"a damaged file falls back to the defaults key by key",
              rba_core.load_settings()[u"icon_size"] == rba_core.DEFAULTS[u"icon_size"])

        stale = {u"settings_version": u"1", u"icon_size": u"6"}
        rba_core.MIGRATIONS[2] = [u"icon_size"]
        try:
            migrated = rba_core.apply_migrations(dict(stale))
            check(u"a key whose meaning changed is reset by its migration",
                  migrated[u"icon_size"] == rba_core.DEFAULTS[u"icon_size"])
        finally:
            del rba_core.MIGRATIONS[2]
    finally:
        rba_core.appdata_root = original
        shutil.rmtree(folder, ignore_errors=True)


def check_roots():
    folder = tempfile.mkdtemp(prefix="rba_root_")
    try:
        check(u"a nominated folder that exists is used",
              rba_scan.resolve_roots(folder) == [folder])
        check(u"a nominated folder that does not exist falls back to the defaults",
              rba_scan.resolve_roots(os.path.join(folder, u"nope")) ==
              rba_scan.default_roots())
        check(u"a blank setting falls back to the defaults",
              rba_scan.resolve_roots(u"") == rba_scan.default_roots())
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def check_theme():
    check(u"the theme chip cycles auto, dark, light",
          [rba_theme.next_mode(u"auto"), rba_theme.next_mode(u"dark"),
           rba_theme.next_mode(u"light")] == [u"dark", u"light", u"auto"])
    check(u"an explicit mode is not overridden by Revit",
          rba_theme.resolve(u"light") == u"light")
    check(u"a nonsense mode is treated as auto and still resolves",
          rba_theme.resolve(u"tangerine") in (u"dark", u"light"))
    check(u"both palettes carry the same keys",
          set(rba_theme.DARK.keys()) == set(rba_theme.LIGHT.keys()))
    check(u"the light accents are not the dark ones",
          rba_theme.LIGHT[u"AccBlue"] != rba_theme.DARK[u"AccBlue"])

    # Dark is 0 in Revit's enum, so a truthiness test reports it as Light.
    class FakeManager(object):
        CurrentCanvasTheme = 0

    module = sys.modules[u"Autodesk.Revit.UI"]
    before = getattr(module, u"UIThemeManager", None)
    module.UIThemeManager = FakeManager
    try:
        check(u"UITheme.Dark, which is 0, is read as dark and not as a failed read",
              rba_theme.revit_theme() == u"dark")
        FakeManager.CurrentCanvasTheme = 1
        check(u"UITheme.Light is read as light", rba_theme.revit_theme() == u"light")
    finally:
        module.UIThemeManager = before


SHORTCUT_FILE = u"""<?xml version="1.0" encoding="utf-8"?>
<Shortcuts>
	<ShortcutItem CommandName="Visibility/Graphics" CommandId="ID_VIEW_CATEGORY_VISIBILITY" Shortcuts="VG#VV" Paths="View&gt;Graphics" />
	<ShortcutItem CommandName="Wall" CommandId="ID_OBJECTS_WALL" Shortcuts="WA" Paths="Architecture&gt;Build" />
	<ShortcutItem CommandName="Save" CommandId="ID_REVIT_FILE_SAVE" Shortcuts="Ctrl+S" Paths="File" />
	<ShortcutItem CommandName="Nothing" CommandId="ID_NOTHING" Shortcuts="" Paths="" />
</Shortcuts>
"""

ADDIN_ID = u"CustomCtrl_%CustomCtrl_%RevoBIM PY%Management%RevoBIM Addin Manager"


def check_shortcuts():
    items = rba_shortcuts.parse(SHORTCUT_FILE)
    check(u"every ShortcutItem is found", len(items) == 4, u"got {0}".format(len(items)))
    check(u"several shortcuts on one command are split on the hash",
          rba_shortcuts.keys_of(items[0]) == [u"VG", u"VV"])
    check(u"a command with no shortcut yields none",
          rba_shortcuts.keys_of(items[3]) == [])

    check(u"modifier order does not change the shortcut",
          rba_shortcuts.normalise_keys(u"shift+ctrl+s") ==
          rba_shortcuts.normalise_keys(u"Ctrl+Shift+S"))
    check(u"a plain sequence is upper cased",
          rba_shortcuts.normalise_keys(u"vg") == u"VG")

    clash = rba_shortcuts.find_conflicts(items, u"VV")
    check(u"a clash on the second of two shortcuts is still a clash",
          [one[u"CommandId"] for one in clash] == [u"ID_VIEW_CATEGORY_VISIBILITY"])
    check(u"a clash is found whatever order the modifiers were typed in",
          len(rba_shortcuts.find_conflicts(items, u"s+ctrl".replace(u"s+ctrl", u"Shift+Ctrl+S"))) == 0 and
          len(rba_shortcuts.find_conflicts(items, u"Ctrl+S")) == 1)
    check(u"a free shortcut clashes with nothing",
          rba_shortcuts.find_conflicts(items, u"ZQ") == [])
    check(u"a command does not clash with itself",
          rba_shortcuts.find_conflicts(items, u"WA", u"ID_OBJECTS_WALL") == [])
    check(u"the clash is described by name and path",
          u"Wall" in rba_shortcuts.describe(items[1]))

    written = rba_shortcuts.upsert(SHORTCUT_FILE, ADDIN_ID,
                                   u"RevoBIM Addin Manager",
                                   u"RevoBIM PY > Management", u"ra")
    check(u"a new command is added inside the Shortcuts element",
          written.count(u"</Shortcuts>") == 1 and ADDIN_ID in written)
    check(u"the new shortcut is stored normalised",
          u'Shortcuts="RA"' in written)
    check(u"nothing already in the file is disturbed",
          u'Shortcuts="VG#VV"' in written and u'Shortcuts="WA"' in written)
    check(u"the addition parses back out",
          len(rba_shortcuts.parse(written)) == 5)

    again = rba_shortcuts.upsert(written, ADDIN_ID, u"RevoBIM Addin Manager",
                                 u"RevoBIM PY > Management", u"rb")
    check(u"assigning a second time rewrites rather than duplicating",
          len(rba_shortcuts.parse(again)) == 5 and u'Shortcuts="RB"' in again)
    check(u"and the rest of that line survives the rewrite",
          u'CommandName="RevoBIM Addin Manager"' in again)

    kept = rba_shortcuts.upsert(SHORTCUT_FILE, u"ID_OBJECTS_WALL", u"Wall",
                                u"Architecture>Build", u"WB", replace=False)
    check(u"adding without replacing keeps the shortcut already there",
          u'Shortcuts="WA#WB"' in kept)

    gone = rba_shortcuts.remove(written, ADDIN_ID, u"RA")
    check(u"removing empties the attribute rather than the line",
          u'Shortcuts=""' in gone and ADDIN_ID in gone)
    check(u"and the command then reports no shortcut",
          rba_shortcuts.current_keys(gone, ADDIN_ID) == [])

    check(u"an empty file still produces a valid one",
          u"<Shortcuts>" in rba_shortcuts.upsert(u"", ADDIN_ID, u"X", u"Y", u"QQ"))
    check(u"an ampersand in a name is escaped",
          u"&amp;" in rba_shortcuts.build_item(u"ID", u"Cut & Paste", u"", u"CP"))
    check(u"the shortcuts file is looked for under the Revit version",
          rba_shortcuts.shortcuts_path(u"2024").endswith(
              os.path.join(u"Autodesk Revit 2024", u"KeyboardShortcuts.xml")))


def check_window_note():
    folder = tempfile.mkdtemp(prefix="rba_note_")
    original = rba_core.appdata_root
    rba_core.appdata_root = lambda: folder
    try:
        check(u"no note before a window has opened", not rba_window.check_alive_note())
        rba_window.write_alive_note()
        check(u"a note is left when a modeless window opens",
              os.path.isfile(rba_window.note_path()))
        rba_window.clear_alive_note()
        check(u"the first handler that runs clears it",
              not os.path.isfile(rba_window.note_path()))
        rba_window.write_alive_note()
        check(u"a note still there at the next launch is reported",
              rba_window.check_alive_note())
        check(u"and reporting it clears it, so it fires once",
              not rba_window.check_alive_note())
    finally:
        rba_core.appdata_root = original
        shutil.rmtree(folder, ignore_errors=True)


def check_window_size():
    folder = tempfile.mkdtemp(prefix="rba_size_")
    original = rba_core.appdata_root
    rba_core.appdata_root = lambda: folder
    try:
        values = rba_core.load_settings()
        check(u"the floating window has a default size",
              rba_core.as_int(values, u"win_w", 0) >= 240 and
              rba_core.as_int(values, u"win_h", 0) >= 320)
        values[u"win_w"] = u"512"
        rba_core.save_settings(values)
        check(u"a resized window is remembered",
              rba_core.as_int(rba_core.load_settings(), u"win_w", 0) == 512)
    finally:
        rba_core.appdata_root = original
        shutil.rmtree(folder, ignore_errors=True)


def check_slow_clicks():
    fired = []
    watcher = rba_ui.SlowClickWatcher(lambda: fired.append(1))
    for stamp in (1000, 1600, 2200):
        watcher.clicked(stamp)
    check(u"three slow clicks open the arcade", len(fired) == 1)

    fired[:] = []
    watcher = rba_ui.SlowClickWatcher(lambda: fired.append(1))
    for stamp in (1000, 1080, 1160):
        watcher.clicked(stamp)
    check(u"three fast clicks are a double click, not the sequence", not fired)

    fired[:] = []
    watcher = rba_ui.SlowClickWatcher(lambda: fired.append(1))
    for stamp in (1000, 1600, 9000):
        watcher.clicked(stamp)
    check(u"a long pause starts the sequence again", not fired)

    fired[:] = []
    watcher = rba_ui.SlowClickWatcher(lambda: fired.append(1))
    for stamp in (1000, 1000, 1600, 1600, 2200):
        watcher.clicked(stamp)
    check(u"the same click arriving twice is counted once", len(fired) == 1)


# ----------------------------------------------------------------------
# shrink to taskbar - arithmetic, then whole slides against a stand-in
# ----------------------------------------------------------------------

class FakeElement(object):

    def __init__(self, name, visibility=u"Visible"):
        self.name = name
        self.Visibility = visibility


class FakeWindow(object):
    u"""Just the surface the drawer touches, and nothing a real Window lacks."""

    def __init__(self, left=100.0, top=100.0, width=400.0, height=800.0,
                 size_to_content=u"Manual"):
        self.Left = left
        self.Top = top
        self.Width = width
        self.Height = height
        self.MinHeight = 320.0
        self.SizeToContent = size_to_content
        self.tops = []

    @property
    def ActualHeight(self):
        return self.Height


class FakeTimer(object):
    u"""Runs its ticks at once when started, until the drawer stops it."""

    def __init__(self, tick):
        self.tick = tick
        self.running = False
        self.ticks = 0

    def start(self):
        self.running = True
        while self.running and self.ticks < 500:
            self.ticks += 1
            self.tick()

    def stop(self):
        self.running = False


class FakePlatform(object):

    def __init__(self, area=(0.0, 0.0, 1920.0, 1040.0), bar=40.0):
        self.area = area
        self.bar = bar
        self.clock = 0.0
        self.siblings_of = {}
        self.pinned = []          # every pin / unpin, in order
        self.glyph = None
        self.activated = 0
        self.timers = []
        self.throw_on_tick = None
        self.window_for_grips = None
        self.grips_seen_hidden_mid_slide = None
        self.ticks = 0

    def now(self):
        self.ticks += 1
        if self.throw_on_tick is not None and self.ticks == self.throw_on_tick:
            raise RuntimeError(u"bench: a frame that throws")
        self.clock += 0.02
        return self.clock

    def timer(self, interval_ms, tick):
        timer = FakeTimer(tick)
        self.timers.append(timer)
        return timer

    def actual_height(self, window):
        return window.ActualHeight

    def size_to_content(self, window):
        return window.SizeToContent

    def relax(self, window):
        window.MinHeight = 0.0
        window.SizeToContent = u"Manual"

    def restore(self, window, min_height, size_to_content):
        window.MinHeight = min_height
        window.SizeToContent = size_to_content

    def bar_height(self, window, header):
        return self.bar

    def work_area(self, window):
        return self.area

    def siblings(self, header, window, skip):
        return [element for element in self.siblings_of.get(id(header), [])
                if element not in skip]

    def hide(self, element):
        token = element.Visibility
        element.Visibility = u"Collapsed"
        return token

    def show(self, element, token):
        element.Visibility = token

    def pin(self, root):
        self.pinned.append(u"pin")

    def unpin(self, root):
        self.pinned.append(u"unpin")

    def round_header(self, header, parked):
        pass

    def set_glyph(self, glyphs, shrunk):
        self.glyph = shrunk

    def activate(self, window):
        self.activated += 1


def _make_drawer(platform, window=None, owner=None, shortcut=True, name=u"main",
                 siblings=None, grips=True):
    window = window or FakeWindow()
    header = FakeElement(name + u" header")
    platform.siblings_of[id(header)] = siblings if siblings is not None else [
        FakeElement(u"search"), FakeElement(u"list"),
        FakeElement(u"closed section", u"Collapsed")]
    grip = FakeElement(u"grips") if grips else None
    drawer = rba_drawer.Drawer(window, header, FakeElement(u"root"),
                               (FakeElement(u"btn"), None, None), platform,
                               grips=grip, owner=owner, name=name,
                               shortcut=shortcut)
    return drawer, window


def _clear_drawers():
    del rba_drawer.DRAWERS[:]


def check_drawer_math():
    check(u"the ease starts at 0 and lands at exactly 1",
          rba_core.ease_out(0) == 0.0 and rba_core.ease_out(1) == 1.0)
    check(u"the ease is fast away and gentle at the end",
          rba_core.ease_out(0.5) > 0.8 and rba_core.ease_out(0.9) < 1.0)
    check(u"the ease never overshoots",
          all(0.0 <= rba_core.ease_out(step / 20.0) <= 1.0 for step in range(-5, 30)))
    check(u"a freed slot is reused before a new one is opened",
          rba_core.free_slot([0, 2]) == 1 and rba_core.free_slot([]) == 0)
    area = (0.0, 0.0, 1920.0, 1040.0)
    check(u"the first bar parks 8px clear of the taskbar",
          rba_core.stacked_top(area, 40.0, 0.0) == 1040.0 - 8.0 - 40.0)
    check(u"a second bar parks above the first, 4px apart",
          rba_core.stacked_top(area, 40.0, rba_core.below_height([(0, 40.0)], 1))
          == 1040.0 - 8.0 - 40.0 - 4.0 - 40.0)
    check(u"bars in higher slots do not push a lower one up",
          rba_core.below_height([(1, 40.0), (2, 40.0)], 0) == 0.0)
    above = (0.0, -1080.0, 1920.0, 1040.0)
    check(u"a monitor above the primary parks the bar on that monitor",
          rba_core.stacked_top(above, 40.0, 0.0) == -1080.0 + 1040.0 - 8.0 - 40.0)
    saved = (100.0, 120.0, 400.0, 800.0)
    check(u"an untouched bar reopens exactly where the window was",
          rba_core.expand_rect(saved, (100.0, 992.0), (101.0, 993.0), 40.0, area)
          == (100.0, 120.0, 800.0))
    left, top, height = rba_core.expand_rect(saved, (100.0, 992.0), (900.0, 900.0),
                                             40.0, area)
    check(u"a bar carried elsewhere opens upward from where it now sits",
          left == 900.0 and top + height == 900.0 + 40.0,
          u"got {0}".format((left, top, height)))
    left, top, height = rba_core.expand_rect(saved, (100.0, 992.0), (900.0, 50.0),
                                             40.0, area)
    check(u"and is kept on that screen when there is no room above it",
          top == 0.0 and height == 800.0, u"got {0}".format((left, top, height)))
    left, top, height = rba_core.expand_rect(saved, (100.0, 992.0), (1800.0, 600.0),
                                             40.0, area)
    check(u"and is kept on that screen sideways too", left + 400.0 <= 1920.0)
    left, top, height = rba_core.expand_rect(saved, (100.0, 992.0), (500.0, -500.0),
                                             40.0, above)
    check(u"carried onto a monitor above the primary, it opens on that monitor",
          top >= -1080.0 and top + height <= -1080.0 + 1040.0,
          u"got {0}".format((left, top, height)))


def check_drawer():
    try:
        _check_drawer()
    except Exception:
        import traceback
        check(u"the drawer runs a whole slide without throwing", False,
              traceback.format_exc().splitlines()[-1])
    finally:
        _clear_drawers()


def _check_drawer():
    _clear_drawers()
    platform = FakePlatform()
    drawer, window = _make_drawer(platform)
    siblings = platform.siblings_of[id(drawer.header)]

    drawer.shrink()
    target = 1040.0 - 8.0 - 40.0
    check(u"shrinking parks the window at the bottom of its screen",
          window.Top == target and drawer.shrunk, u"top {0}".format(window.Top))
    check(u"only the bar is left", window.Height == 40.0)
    check(u"the slide took more than one frame - it is a slide, not a jump",
          platform.timers and platform.timers[-1].ticks > 3)
    check(u"no timer is left running once it has landed",
          not platform.timers[-1].running)
    check(u"the button turns into the green up arrow", platform.glyph is True)
    check(u"MinHeight is relaxed so it cannot veto the bar", window.MinHeight == 0.0)
    check(u"the body is pinned for the slide and let go on landing",
          platform.pinned[:2] == [u"pin", u"unpin"])
    check(u"the grips are parked with the window",
          drawer.grips.Visibility == u"Collapsed")
    check(u"everything beside the header is collapsed in the bar",
          all(element.Visibility == u"Collapsed" for element in siblings))
    check(u"the window's true size survives for whoever saves it on close",
          drawer.true_bounds() == (100.0, 100.0, 400.0, 800.0))

    check(u"parked, an ordinary key is swallowed", drawer.on_key(u"A", False, False))
    check(u"parked, a double click on the bar reopens rather than going full screen",
          drawer.on_header_double_click() and not drawer.shrunk)
    check(u"reopened untouched, it is exactly where it was",
          (window.Left, window.Top, window.Height) == (100.0, 100.0, 800.0),
          u"got {0}".format((window.Left, window.Top, window.Height)))
    check(u"MinHeight is put back, or the window could be dragged shut",
          window.MinHeight == 320.0)
    check(u"the grips come back", drawer.grips.Visibility == u"Visible")
    check(u"a section that was closed before stays closed",
          [element.Visibility for element in siblings]
          == [u"Visible", u"Visible", u"Collapsed"])
    check(u"the button is the shrink arrow again", platform.glyph is False)
    check(u"reopened, the window is brought to the front", platform.activated >= 1)
    check(u"open, an ordinary key is the window's", not drawer.on_key(u"A", False, False))

    for key in (u"Escape", u"Return", u"F11"):
        drawer.shrink()
        drawer.on_key(key, False, False)
        check(u"parked, {0} reopens".format(key), not drawer.shrunk)

    drawer.on_key(u"H", True, True)
    check(u"Ctrl+Shift+H shrinks", drawer.shrunk)
    drawer.on_key(u"H", True, True)
    check(u"and Ctrl+Shift+H brings it back", not drawer.shrunk)

    drawer.shrink()
    window.Left, window.Top = 900.0, 900.0         # the bar dragged elsewhere
    drawer.expand()
    check(u"a dragged bar opens upward from where it was left",
          window.Left == 900.0 and window.Top + window.Height == 940.0,
          u"got {0}".format((window.Left, window.Top, window.Height)))
    _clear_drawers()

    # a window sized to its content
    platform = FakePlatform()
    drawer, window = _make_drawer(platform, window=FakeWindow(size_to_content=u"Height"))
    drawer.shrink()
    check(u"SizeToContent is relaxed for the slide", window.SizeToContent == u"Manual")
    drawer.expand()
    check(u"and put back when it reopens", window.SizeToContent == u"Height")
    _clear_drawers()

    # stacking, and a freed slot
    platform = FakePlatform()
    first, first_window = _make_drawer(platform, name=u"first")
    second, second_window = _make_drawer(platform, name=u"second")
    first.shrink()
    second.shrink()
    check(u"two parked bars stack rather than landing on one another",
          second_window.Top == first_window.Top - 4.0 - 40.0,
          u"{0} vs {1}".format(second_window.Top, first_window.Top))
    first.expand()
    third, third_window = _make_drawer(platform, name=u"third")
    third.shrink()
    check(u"a freed slot is reused", third_window.Top == 1040.0 - 8.0 - 40.0)
    _clear_drawers()

    # owners
    platform = FakePlatform()
    main, main_window = _make_drawer(platform, name=u"main")
    dialog, dialog_window = _make_drawer(platform, owner=main, name=u"dialog",
                                         window=FakeWindow(300, 300, 460, 400))
    dialog.shrink()
    check(u"a dialog takes its owner down first", main.shrunk and dialog.shrunk)
    check(u"and parks its own bar above the owner's",
          dialog_window.Top < main_window.Top)
    dialog.expand()
    check(u"reopening the dialog brings its owner back", not main.shrunk)
    dialog.shrink()
    dialog.forget()
    check(u"closing a parked dialog brings its owner back", not main.shrunk)
    _clear_drawers()

    # the shortcut prompt: Ctrl+Shift+H is a shortcut to capture while open
    platform = FakePlatform()
    prompt, _w = _make_drawer(platform, shortcut=False, name=u"prompt")
    check(u"a capture prompt leaves Ctrl+Shift+H to be assigned",
          not prompt.on_key(u"H", True, True) and not prompt.shrunk)
    prompt.shrink()
    check(u"but parked, Ctrl+Shift+H still brings it back",
          prompt.on_key(u"H", True, True) and not prompt.shrunk)
    _clear_drawers()

    # trap 1: a frame that throws lands the window, never half way
    platform = FakePlatform()
    platform.throw_on_tick = 4
    drawer, window = _make_drawer(platform)
    drawer.shrink()
    check(u"a frame that throws lands the window at its end, not half way",
          window.Top == 1040.0 - 8.0 - 40.0 and drawer.shrunk and not drawer.sliding)
    _clear_drawers()

    # a monitor above the primary
    platform = FakePlatform(area=(0.0, -1080.0, 1920.0, 1040.0))
    drawer, window = _make_drawer(platform, window=FakeWindow(100.0, -900.0))
    drawer.shrink()
    check(u"on a monitor above the primary the bar parks on that monitor",
          window.Top == -1080.0 + 1040.0 - 8.0 - 40.0, u"top {0}".format(window.Top))


def check_dock_math():
    revit = (200.0, 150.0, 1500.0, 800.0)
    check(u"docked left, the window takes Revit's left edge and full height",
          rba_core.dock_rect(revit, 380.0, u"left", 320.0) == (200.0, 150.0, 380.0, 800.0))
    check(u"docked right, it takes the right edge",
          rba_core.dock_rect(revit, 380.0, u"right", 320.0) == (1320.0, 150.0, 380.0, 800.0))
    check(u"a docked window never goes narrower than its minimum",
          rba_core.dock_rect(revit, 100.0, u"left", 320.0)[2] == 320.0)
    check(u"or wider than Revit itself",
          rba_core.dock_rect(revit, 5000.0, u"right", 320.0)[2] == 1500.0)
    check(u"a rectangle within a pixel is not worth moving the window for",
          not rba_core.rect_differs((1, 2, 3, 4), (1.5, 2, 3, 4)))
    check(u"one that has moved is",
          rba_core.rect_differs((1, 2, 3, 4), (10, 2, 3, 4)))


def check_saved_keys(items):
    u"""Real addin keys through the real settings list.

    1.5.0's favourites checks used keys like "a" and "b" and all passed, while
    every real key - which had "|" inside it - came back from the settings
    file in four pieces. Placeholders proved the list logic and nothing else.
    """
    def round_trip(name, keys):
        values = {}
        try:
            rba_core.set_list(values, name, keys)
        except ValueError as error:
            # Refused is a failure too: the key cannot be saved at all.
            return None, rba_core.to_text(error)
        return rba_core.as_list(values, name), u""

    keys = [item.key for item in items]
    for name in (u"favourites", u"pinned", u"qat", u"collapsed"):
        back, why = round_trip(name, keys)
        check(u"real addin keys survive a round trip through the saved {0} list"
              .format(name), back == keys, why or u"got {0}".format((back or [])[:4]))
    groups = rba_scan.group_items(items, group_by=u"panel")
    group_keys = [group.key for group in groups]
    back, why = round_trip(u"collapsed", group_keys)
    check(u"group keys survive the saved list too", back == group_keys, why)

    old = u"|".join([u"revobim py", u"revobim py", u"annotation", u"tag all",
                     u"revobim py", u"revobim py", u"management", u"sheet manager"])
    check(u"favourites saved as fragments by 1.5.0 are rebuilt into keys",
          rba_core.rejoin_fragments(old).split(rba_core.LIST_SEP)
          == [u"revobim py::revobim py::annotation::tag all",
              u"revobim py::revobim py::management::sheet manager"])
    migrated = rba_core.apply_migrations({u"settings_version": u"1",
                                          u"favourites": old, u"collapsed": u"x|y|z"})
    check(u"loading old settings rebuilds favourites and clears folded groups",
          migrated[u"favourites"].count(u"::") == 6 and migrated[u"collapsed"] == u"")
    raised = False
    try:
        rba_core.set_list({}, u"favourites", [u"has|a pipe"])
    except ValueError:
        raised = True
    check(u"saving an entry that holds the separator is refused, not split", raised)


def check_favourites():
    keys = []
    for key in (u"a", u"b", u"c"):
        keys = rba_core.fav_add(keys, key)
    check(u"new favourites fill in reading order, newest last",
          keys == [u"a", u"b", u"c"])
    check(u"adding a favourite twice does not duplicate it",
          rba_core.fav_add(keys, u"b") == [u"a", u"b", u"c"])
    check(u"removing one closes the gap",
          rba_core.fav_remove(keys, u"b") == [u"a", u"c"])

    order = [u"a", u"b", u"c", u"d", u"e"]
    check(u"dragging forward lands the tile exactly where it was dropped",
          rba_core.move_item(order, 0, 3) == [u"b", u"c", u"d", u"a", u"e"])
    check(u"dragging back does the same",
          rba_core.move_item(order, 4, 1) == [u"a", u"e", u"b", u"c", u"d"])
    check(u"a drop past the end lands last",
          rba_core.move_item(order, 1, 99) == [u"a", u"c", u"d", u"e", u"b"])
    check(u"dropping where it started changes nothing",
          rba_core.move_item(order, 2, 2) == order)

    # a 3 wide grid of 60 x 70 tiles: two rows, five tiles
    rects = [(0, 0, 60, 70), (60, 0, 60, 70), (120, 0, 60, 70),
             (0, 70, 60, 70), (60, 70, 60, 70)]
    check(u"over a tile, the slot is that tile's",
          rba_core.drop_index(rects, (90, 100)) == 4)
    check(u"top left is the first slot", rba_core.drop_index(rects, (5, 5)) == 0)
    check(u"in the empty space after the last tile, it drops at the end",
          rba_core.drop_index(rects, (150, 100)) == 4)
    check(u"below the grid, it drops at the end",
          rba_core.drop_index(rects, (30, 400)) == 4)
    check(u"no tiles, no slot", rba_core.drop_index([], (1, 1)) is None)

    check(u"a reorder keeps hidden favourites in their places",
          rba_favs.merge_order([u"a", u"gone", u"b", u"c"], [u"c", u"a", u"b"])
          == [u"c", u"gone", u"a", u"b"])
    check(u"favourite icons are a size up from the list's",
          rba_core.fav_icon_size(32) > 32 and rba_core.fav_icon_size(16) >= 32)


def check_tweens():
    check(u"the lift's ease starts at 0 and lands at exactly 1",
          rba_core.ease_out_back(0) == 0.0 and rba_core.ease_out_back(1) == 1.0)
    check(u"the lift overshoots a little before it settles",
          max(rba_core.ease_out_back(step / 50.0) for step in range(51)) > 1.02)

    seen = []
    done = []
    tweens = rba_tween.Tweens()
    tweens.add(u"s", 1.0, 1.14, 0.17, seen.append, rba_core.ease_out_back,
               lambda: done.append(1))
    clock = 0.0
    tweens.tick(clock)
    for frame in range(40):
        clock += 0.016
        tweens.tick(clock)
    check(u"a tween lands exactly on its end value", seen[-1] == 1.14,
          u"got {0}".format(seen[-1]))
    check(u"and says so exactly once", done == [1])
    check(u"and stops running once it has landed", not tweens.busy())

    seen = []
    tweens = rba_tween.Tweens()
    tweens.add(u"x", 0.0, 100.0, 1.0, seen.append, lambda p: p)
    tweens.tick(0.0)
    tweens.tick(0.010)
    tweens.tick(0.010)          # the same frame twice
    check(u"a frame seen twice does not move anything twice",
          abs(seen[-1] - 1.0) < 1e-6, u"got {0}".format(seen[-1]))
    tweens.tick(5.0)            # a long Revit hiccup
    check(u"a slow frame is clamped, so nothing jumps",
          seen[-1] < 10.0, u"got {0}".format(seen[-1]))

    seen = []
    tweens = rba_tween.Tweens()
    tweens.add(u"y", 0.0, 50.0, 1.0, seen.append, lambda p: p)
    tweens.tick(0.0)
    for frame in range(10):
        tweens.tick(0.016 * (frame + 1))
    halfway = seen[-1]
    tweens.add(u"y", 0.0, 0.0, 0.2, seen.append)
    check(u"a tween that replaces another starts from where the value is",
          abs(seen[-1] - halfway) < 1e-6)

    calls = []
    tweens = rba_tween.Tweens()
    tweens.on_busy = lambda: calls.append(u"busy")
    tweens.on_idle = lambda: calls.append(u"idle")
    tweens.add(u"a", 0.0, 1.0, 0.05, lambda v: None)
    tweens.add(u"b", 0.0, 1.0, 0.05, lambda v: None)
    tweens.tick(0.0)
    for frame in range(10):
        tweens.tick(0.016 * (frame + 1))
    check(u"the frame hook goes on once and comes off once",
          calls == [u"busy", u"idle"], u"got {0}".format(calls))

    landed = []
    tweens = rba_tween.Tweens()
    tweens.add(u"z", 0.0, 7.0, 10.0, landed.append)
    tweens.finish_all()
    check(u"a grid rebuilt mid-flight lands everything at its end",
          landed[-1] == 7.0 and not tweens.busy())


def run():
    root, ext = build_tree()
    try:
        items = check_scan(root, ext)
        check_search(items)
        check_two_tier(items)
        check_saved_keys(items)
        check_grouping(items)
        check_natural_order()
        check_settings()
        check_roots()
        check_theme()
        check_slow_clicks()
        check_window_note()
        check_window_size()
        check_shortcuts()
        check_drawer_math()
        check_drawer()
        check_dock_math()
        check_favourites()
        check_tweens()
    finally:
        shutil.rmtree(root, ignore_errors=True)

    failed = 0
    for title, passed, detail in RESULTS:
        if passed:
            print(u"ok    {0}".format(title))
        else:
            failed += 1
            print(u"FAIL  {0}  {1}".format(title, detail))
    print(u"")
    print(u"{0} of {1} checks pass".format(len(RESULTS) - failed, len(RESULTS)))
    return failed


# ----------------------------------------------------------------------
# selftest - break the logic and confirm the checks notice
# ----------------------------------------------------------------------


def _broken_landed_open(self):
    u"""The drawer forgetting trap 2 on the way back up."""
    if self.grips is not None:
        self.platform.show(self.grips, self.grips_token)
    self.grips_token = None
    self.platform.activate(self.window)
    if self.lifted_owner and self.owner is not None:
        self.lifted_owner = False
        self.owner.expand()


def _broken_landed_parked(self):
    u"""The drawer collapsing the body without remembering what was closed."""
    window = self.window
    window.Height = self.bar
    self.hidden = []
    for element in self.platform.siblings(self.header, window, []):
        self.platform.hide(element)
        self.hidden.append((element, u"Visible"))
    self.platform.unpin(self.root)
    self.landed = (window.Left, window.Top)
    self.shrunk = True
    self.platform.set_glyph(self.glyphs, True)


_REAL_SHRINK = rba_drawer.Drawer.shrink


def _shrink_alone(self, instant=False):
    u"""A dialog that leaves its owner standing over Revit."""
    owner, self.owner = self.owner, None
    try:
        _REAL_SHRINK(self, instant)
    finally:
        self.owner = owner


def selftest():
    breakages = [
        (u"the search stops requiring every word",
         u"matches_search",
         lambda: setattr(rba_core, u"matches_search",
                         lambda hay, terms: True)),
        (u"a newline in a title stops being flattened",
         u"_flatten",
         lambda: setattr(rba_scan, u"_flatten", lambda value: value)),
        (u"natural order falls back to string order",
         u"natural_key",
         lambda: setattr(rba_core, u"natural_key", lambda value: value)),
        (u"the theme read treats Dark, which is 0, as a failed read",
         u"revit_theme",
         lambda: setattr(rba_theme, u"revit_theme",
                         lambda: u"light")),
        (u"a fast triple click counts as the slow sequence",
         u"CLICK_FLOOR_MS",
         lambda: setattr(rba_ui, u"CLICK_FLOOR_MS", 0)),
        (u"the two tier search pools name and description into one list",
         u"search_split",
         lambda: setattr(rba_scan, u"search_split",
                         lambda items, search=u"", hide_unloaded=False:
                         ([item for item in items
                           if rba_core.matches_search(item.search_text,
                                                      rba_core.words(search))], []))),
        (u"the conflict check stops noticing a shortcut already in use",
         u"find_conflicts",
         lambda: setattr(rba_shortcuts, u"find_conflicts",
                         lambda items, keys, command_id=None: [])),
        (u"modifier order is taken literally, so Ctrl+Shift+S misses Shift+Ctrl+S",
         u"normalise_keys",
         lambda: setattr(rba_shortcuts, u"normalise_keys",
                         lambda keys: rba_core.to_text(keys).strip())),
        (u"assigning twice appends a second entry instead of rewriting",
         u"upsert",
         lambda: setattr(rba_shortcuts, u"upsert",
                         lambda text, command_id, name, paths, keys, replace=True:
                         text.replace(u"</Shortcuts>",
                                      rba_shortcuts.build_item(command_id, name,
                                                               paths, keys) +
                                      u"\n</Shortcuts>", 1))),
        (u"the alive note is never written, so a dead window cannot be spotted",
         u"write_alive_note",
         lambda: setattr(rba_window, u"write_alive_note", lambda: None)),
        (u"the ease overshoots and bounces past the landing",
         u"ease_out",
         lambda: setattr(rba_core, u"ease_out", lambda progress: progress * 1.2)),
        (u"every bar parks in slot 0, on top of the others",
         u"free_slot",
         lambda: setattr(rba_core, u"free_slot", lambda used: 0)),
        (u"a dragged bar jumps back to where it used to be",
         u"expand_rect",
         lambda: setattr(rba_core, u"expand_rect",
                         lambda saved, landed, now, bar, area:
                         (saved[0], saved[1], saved[3]))),
        (u"MinHeight and SizeToContent are never put back",
         u"_landed_open",
         lambda: setattr(rba_drawer.Drawer, u"_landed_open", _broken_landed_open)),
        (u"a closed section comes back open after the drawer",
         u"_landed_parked",
         lambda: setattr(rba_drawer.Drawer, u"_landed_parked", _broken_landed_parked)),
        (u"a dialog shrinks without taking its owner down",
         u"shrink",
         lambda: setattr(rba_drawer.Drawer, u"shrink", _shrink_alone)),
        (u"docking ignores the side and always snaps left",
         u"dock_rect",
         lambda: setattr(rba_core, u"dock_rect",
                         lambda target, width, side, min_width:
                         (target[0], target[1], width, target[3]))),
        (u"an escaped line break loses its backslash and leaves the n",
         u"_strip_quoting",
         lambda: setattr(rba_scan, u"_strip_quoting",
                         lambda fragment: fragment.replace(u"\\", u" ")
                         .replace(u'"', u" ").replace(u"__doc__", u" ")
                         .replace(u"=", u" ").replace(u"(", u" ").replace(u")", u" "))),
        (u"a new favourite jumps to the front instead of the next free spot",
         u"fav_add",
         lambda: setattr(rba_core, u"fav_add",
                         lambda keys, key: [key] + [k for k in keys if k != key])),
        (u"a dragged tile lands one slot short of where it was dropped",
         u"move_item",
         lambda: setattr(rba_core, u"move_item",
                         lambda seq, source, target: list(seq))),
        (u"letting go in the empty space after the tiles drops nowhere",
         u"drop_index",
         lambda: setattr(rba_core, u"drop_index",
                         lambda rects, point: next(
                             (i for i, (l, t, w, h) in enumerate(rects)
                              if l <= point[0] < l + w and t <= point[1] < t + h),
                             None) if rects else None)),
        (u"a reorder throws away favourites that are not on screen",
         u"merge_order",
         lambda: setattr(rba_favs, u"merge_order", lambda saved, shown: list(shown))),
        (u"an addin key is built with the list separator inside it again",
         u"KEY_SEP",
         lambda: setattr(rba_scan, u"KEY_SEP", u"|")),
        (u"old fragments are thrown away instead of rebuilt",
         u"rejoin_fragments",
         lambda: setattr(rba_core, u"rejoin_fragments", lambda raw: u"")),
        (u"the lift has no overshoot - it just slides",
         u"ease_out_back",
         lambda: setattr(rba_core, u"ease_out_back",
                         lambda progress, overshoot=1.6: rba_core.ease_out(progress))),
        (u"a slow frame is not clamped, so a hiccup makes a tile jump",
         u"MAX_FRAME",
         lambda: setattr(rba_tween, u"MAX_FRAME", 99.0)),
        (u"the description reader stops reading the module docstring",
         u"_module_docstring",
         lambda: setattr(rba_scan, u"_module_docstring", lambda text: u"")),
    ]
    caught = 0
    for title, attribute, breakage in breakages:
        owner = None
        for module in ((rba_scan,) if attribute == u"KEY_SEP" else ()) + (
                rba_core, rba_scan, rba_theme, rba_ui, rba_window,
                rba_shortcuts, rba_drawer, rba_drawer.Drawer, rba_favs, rba_tween,
                rba_tween.Tweens):
            if hasattr(module, attribute):
                owner = module
                break
        before = getattr(owner, attribute)
        del RESULTS[:]
        breakage()
        try:
            root, ext = build_tree()
            try:
                items = check_scan(root, ext)
                check_search(items)
                check_two_tier(items)
                check_saved_keys(items)
                check_natural_order()
                check_theme()
                check_slow_clicks()
                check_window_note()
                check_shortcuts()
                check_drawer_math()
                check_drawer()
                check_dock_math()
                check_favourites()
                check_tweens()
            finally:
                shutil.rmtree(root, ignore_errors=True)
        except Exception:
            pass
        failed = len([entry for entry in RESULTS if not entry[1]])
        setattr(owner, attribute, before)
        if failed:
            caught += 1
            print(u"ok    caught: {0}".format(title))
        else:
            print(u"FAIL  breaking '{0}' changed nothing".format(title))
    del RESULTS[:]
    print(u"")
    print(u"{0} of {1} breakages caught".format(caught, len(breakages)))
    return len(breakages) - caught


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(1 if selftest() else 0)
    sys.exit(1 if run() else 0)
