# -*- coding: utf-8 -*-
"""The one thing a tool calls.

    from revobim.egg import egg_hook
    egg_hook.attach_to_window(window, theme=lambda: self.theme_name)

That is the whole wiring. It finds the logo itself, so it does not matter what
the tool's XAML calls it.

**Three SLOW clicks** on the RevoBIM logo - each one between a quarter of a
second and two seconds after the last. Faster than that is a double click and
starts the run again; slower and the run has gone cold.

Everything in here is wrapped: a tool must never fail to open because its easter
egg would not attach. Every attach, click and launch is written to
%APPDATA%\\RevoBIM\\easter_egg.log, because that rule is exactly what makes a
hook that never fires indistinguishable from one that was never asked for.
"""

from revobim.egg import egg_clr  # noqa: F401  - assemblies first, always

from System.Windows import LogicalTreeHelper, UIElement
from System.Windows.Controls import Image, TextBlock
from System.Windows.Input import MouseButtonEventHandler
from System.Windows.Media import ColorConverter, SolidColorBrush

from revobim.egg import egg_log, egg_settings, egg_shell

__version__ = "1.5.0"

DEFAULT_CLICKS = 3

# The house behaviour is three SLOW clicks. Up to 1.4.0 this was one 650ms
# window for the whole run, which is a *fast* triple click - clicking the way
# the tools are documented never reached three and the egg simply never opened.
DEFAULT_GAP_MIN_MS = 250
DEFAULT_GAP_MAX_MS = 2000

# Names worth trying before falling back to searching by what things are.
LOGO_NAMES = ("LogoMark", "LogoText", "LogoIcon", "Logo", "HeaderLogo",
              "HeaderIcon", "BrandMark", "BrandText", "RevoBIMLogo",
              "RevoBIMText", "TitleIcon", "AppIcon", "IconImage")

BRAND = "revobim"
TRANSPARENT = "#00FFFFFF"

# Handlers are parked here. An IronPython bound method makes a fresh delegate on
# every attribute access, so a handler nothing holds a reference to is collected
# and the event quietly stops firing.
_HOOKS = []


class _Counter(object):
    """Counts slow clicks.

    WPF has no triple click - `ClickCount` only ever reports 1 or 2 - so the run
    is counted here off the event timestamps rather than a timer. Timestamps
    also settle the two problems a timer does not:

    - the same physical click reaching this handler twice, because the egg is
      attached to both a logo and something containing it. Identical timestamp,
      counted once. `is` will not do it: it compares Python object identity, not
      .NET object identity.
    - a run that is meant to be slow. A gap that is too short is a double click
      and starts again; too long and the run has gone cold.
    """

    def __init__(self, elements, host_window, theme, clicks, gap_min, gap_max,
                 tool):
        self.elements = elements
        self.host_window = host_window
        self.theme = theme
        self.clicks = clicks
        self.gap_min = gap_min
        self.gap_max = gap_max
        self.tool = tool
        self.count = 0
        self.last = None
        self.stamp = None
        self.delegate = MouseButtonEventHandler(self.on_click)

    def on_click(self, sender, args):
        try:
            now = self._stamp(args)
            if self.stamp is not None and now == self.stamp:
                return          # one click, two elements, one count
            self.stamp = now

            gap = None if self.last is None else (now - self.last)
            self.last = now

            if gap is None or gap > self.gap_max or gap < self.gap_min:
                self.count = 1
                why = "start" if gap is None else (
                    "too slow" if gap > self.gap_max else "too fast")
                egg_log.write("click 1 ({0}, gap {1})".format(why, gap),
                              self.tool)
                return

            self.count += 1
            egg_log.write("click {0} of {1} (gap {2}ms)".format(
                self.count, self.clicks, gap), self.tool)

            if self.count >= self.clicks:
                self.count = 0
                self.last = None
                # Only the click that fires it is swallowed. The others are left
                # alone, so a header that calls DragMove on a bubbled
                # MouseLeftButtonDown still drags the window normally.
                args.Handled = True
                opened = egg_shell.launch(host_window=self.host_window,
                                          theme=self.theme)
                egg_log.write("launch {0}".format(
                    "ok" if opened else "FAILED - see egg_shell"), self.tool)
        except Exception:
            self.count = 0
            egg_log.write("click handler threw: {0}".format(
                _last_error()), self.tool)

    def _stamp(self, args):
        try:
            return int(args.Timestamp)
        except Exception:
            # No timestamp on the args is not a reason to give up; fall back to
            # the environment's own tick count.
            try:
                from System import Environment
                return int(Environment.TickCount)
            except Exception:
                return 0

    def detach(self):
        for element in self.elements:
            try:
                element.RemoveHandler(
                    UIElement.PreviewMouseLeftButtonDownEvent, self.delegate)
            except Exception:
                pass
        self.count = 0
        self.elements = []


# -- finding the logo ====================================================

def find_logo(window, names=None, deep=True):
    """Every element worth hooking, best first.

    Named elements are tried first, then anything that looks like the brand.
    A tool whose header calls its logo something this does not know about still
    gets an egg, which is the point: wiring it must not depend on remembering to
    use one particular x:Name.

    `deep=False` does the named lookups only. The automatic attachment runs for
    every window every addin in Revit opens, and a dozen `FindName` calls is
    nothing while walking the logical tree of every dialog is not.
    """
    found = []
    seen = []

    def take(element):
        if element is None:
            return
        for other in seen:
            if _same(element, other):
                return
        seen.append(element)
        found.append(element)

    for name in (names or LOGO_NAMES):
        try:
            take(window.FindName(name))
        except Exception:
            pass

    if not found and deep:
        for element in _walk(window):
            try:
                if isinstance(element, TextBlock):
                    text = (element.Text or "").lower()
                    if BRAND in text:
                        take(element)
                elif isinstance(element, Image):
                    label = (element.Name or "").lower()
                    if "logo" in label or "icon" in label or "brand" in label:
                        take(element)
            except Exception:
                continue
    return found


def _walk(node, depth=0):
    """The logical tree, which is readable before the window has rendered.

    The visual tree would need the window up; a tool wires its egg during
    construction, so that is too late to be useful.
    """
    if node is None or depth > 40:
        return
    yield node
    try:
        children = LogicalTreeHelper.GetChildren(node)
    except Exception:
        return
    try:
        for child in children:
            for item in _walk(child, depth + 1):
                yield item
    except Exception:
        return


def _same(one, other):
    """.NET reference equality. `is` compares Python identity and will not do."""
    try:
        return bool(object.ReferenceEquals(one, other))
    except Exception:
        pass
    try:
        from System import Object
        return bool(Object.ReferenceEquals(one, other))
    except Exception:
        return one is other


def _make_clickable(element):
    """A TextBlock is only hit testable where its glyphs actually are.

    Click the gap between RevoBIM's o and B and nothing happens at all, which
    reads as the egg being broken rather than as a miss. A transparent
    Background is invisible and makes the whole box take the click.
    """
    try:
        element.IsHitTestVisible = True
    except Exception:
        pass
    try:
        if element.Background is None:
            element.Background = SolidColorBrush(
                ColorConverter.ConvertFromString(TRANSPARENT))
    except Exception:
        pass


# -- attaching ===========================================================

def attach_to_window(window, theme=None, names=None, clicks=None,
                     gap_min_ms=None, gap_max_ms=None, tool=None):
    """Wire the egg to a window's logo, whatever that window calls it.

    This is the call to use. It finds the logo, owns the game window to this
    one, makes the target properly clickable and logs what it did.

    Returns a callable that unhooks it, or None.
    """
    try:
        elements = find_logo(window, names)
        if not elements:
            egg_log.write(
                "attach FAILED: no logo found. Tried the names {0} and then "
                "any TextBlock reading RevoBIM. Pass names=[...] or an element "
                "directly.".format(", ".join(names or LOGO_NAMES)), tool)
            return None
        return attach(elements, host_window=window, theme=theme,
                      clicks=clicks, gap_min_ms=gap_min_ms,
                      gap_max_ms=gap_max_ms, tool=tool)
    except Exception:
        egg_log.write("attach_to_window threw: {0}".format(_last_error()), tool)
        return None


def attach(logo, host_window=None, theme=None, clicks=None, gap_min_ms=None,
           gap_max_ms=None, tool=None, window_ms=None):
    """Wire the egg to one element, or to several sharing one click count.

    `logo`        a WPF element, or a list of them.
    `host_window` the tool's own window, so the egg is owned by it.
    `theme`       "dark", "light", or a callable returning one.

    `window_ms` is accepted and ignored: it was the whole-run window up to
    1.4.0, and anything still passing it should not break.

    Returns a callable that unhooks it, or None if it could not attach.
    """
    try:
        elements = logo if isinstance(logo, (list, tuple)) else [logo]
        elements = [item for item in elements if item is not None]
        if not elements:
            egg_log.write(
                "attach FAILED: nothing to attach to. FindName almost "
                "certainly returned None - check the x:Name in the layout, or "
                "use attach_to_window(window) and let it find the logo.", tool)
            return None

        settings = egg_settings.load()
        want_clicks = clicks or egg_settings.get_int(
            settings, "clicks", DEFAULT_CLICKS)
        want_min = gap_min_ms or egg_settings.get_int(
            settings, "click_gap_min_ms", DEFAULT_GAP_MIN_MS)
        want_max = gap_max_ms or egg_settings.get_int(
            settings, "click_gap_max_ms", DEFAULT_GAP_MAX_MS)

        counter = _Counter(elements, host_window, theme, want_clicks,
                           want_min, want_max, tool)

        wired = 0
        for element in elements:
            _make_clickable(element)
            if _listen(element, counter):
                wired += 1

        if not wired:
            egg_log.write("attach FAILED: found {0} element(s) but could not "
                          "hook any of them".format(len(elements)), tool)
            return None

        _HOOKS.append(counter)
        _arm_auto()
        egg_log.write(
            "attached to {0} element(s): {1}. {2} clicks, {3}-{4}ms "
            "apart.".format(wired, _describe(elements), want_clicks, want_min,
                            want_max), tool)
        return counter.detach
    except Exception:
        egg_log.write("attach threw: {0}".format(_last_error()), tool)
        return None


def _arm_auto():
    """A fourth anchor: any tool that wires the egg by hand also arms the
    automatic attachment for every other tool in the session.

    Free, idempotent, and it means a single hand-wired tool is enough to bring
    the rest back if startup.py and both hooks have all been lost.
    """
    try:
        from revobim.egg import egg_auto
        egg_auto.install()
    except Exception:
        pass


def _listen(element, counter):
    """Hook the tunnelling event, and hear it even once something has handled it.

    Preview tunnels root to leaf, so a header that handles
    PreviewMouseLeftButtonDown for its own drag runs *before* the logo does and
    marks the event handled - and a plain `+=` handler is never called for a
    handled event. `AddHandler(..., True)` is the only way to still hear it.
    """
    try:
        element.AddHandler(UIElement.PreviewMouseLeftButtonDownEvent,
                           counter.delegate, True)
        return True
    except Exception:
        pass
    try:
        element.PreviewMouseLeftButtonDown += counter.on_click
        return True
    except Exception:
        return False


def _describe(elements):
    names = []
    for element in elements:
        try:
            label = element.Name or element.GetType().Name
        except Exception:
            label = "?"
        names.append(str(label))
    return ", ".join(names)


def _last_error():
    try:
        import traceback
        return traceback.format_exc().replace("\n", " | ")
    except Exception:
        return "unknown"


# -- checking it ---------------------------------------------------------

def diagnose(window=None, names=None):
    """A readable report on why the egg is or is not wired.

    Put it behind a TaskDialog in a tool that is misbehaving:

        from revobim.egg import egg_hook
        TaskDialog.Show("Egg", egg_hook.diagnose(self.window))
    """
    lines = ["RevoBIM easter egg " + __version__]
    try:
        settings = egg_settings.load()
        lines.append("clicks: {0}, {1}-{2}ms apart".format(
            egg_settings.get_int(settings, "clicks", DEFAULT_CLICKS),
            egg_settings.get_int(settings, "click_gap_min_ms",
                                 DEFAULT_GAP_MIN_MS),
            egg_settings.get_int(settings, "click_gap_max_ms",
                                 DEFAULT_GAP_MAX_MS)))
        lines.append("game: {0}".format(settings.get("game")))
    except Exception:
        lines.append("settings could not be read")

    lines.append("hooks live in this engine: {0}".format(len(_HOOKS)))

    if window is not None:
        try:
            found = find_logo(window, names)
            if found:
                lines.append("logo found: " + _describe(found))
            else:
                lines.append("NO LOGO FOUND. Tried: " +
                             ", ".join(names or LOGO_NAMES))
        except Exception:
            lines.append("searching the window threw: " + _last_error())

    lines.append("log: " + egg_log.path())
    lines.append("")
    lines.append("recent:")
    for line in egg_log.tail(12):
        lines.append("  " + line)
    return "\n".join(lines)


def launch(host_window=None, theme=None, game_key=None):
    """Open the egg directly, without the clicks. Handy for testing it."""
    opened = egg_shell.launch(host_window=host_window, theme=theme,
                              game_key=game_key)
    egg_log.write("direct launch {0}".format("ok" if opened else "FAILED"))
    return opened
