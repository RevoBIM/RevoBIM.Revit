# -*- coding: utf-8 -*-
"""Bench test for the shrink-to-taskbar drawer.

Drives the real pstm_drawer.Drawer against a stand-in window: a timer that runs
its ticks at once, a clock that moves 20 ms every time it is read, and a screen
whose work area can be put anywhere - including on a monitor ABOVE the primary
one, where the work-area top is negative.

    python drawer_check.py               run the checks
    python drawer_check.py --breakages   break the drawer on purpose, one way at
                                         a time, and prove a check catches each

Most of what can go wrong with a drawer goes wrong silently - a window that
never resizes again, a bar on the wrong monitor, a hidden panel that comes back
- so every check here has a breakage that proves it would notice.
"""

import io
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import import_check                                              # noqa: E402
import_check.install_stubs()

SOURCE_PATH = os.path.join(HERE, 'pstm_drawer.py')


# ---------------------------------------------------------------------------
# Stand-ins for the WPF the drawer touches
# ---------------------------------------------------------------------------

class Event(object):
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def __isub__(self, handler):
        self.handlers.remove(handler)
        return self

    def fire(self, sender, args):
        for handler in list(self.handlers):
            handler(sender, args)


class Enum(object):
    """Named values that compare by name, like a .NET enum member."""
    def __init__(self, **values):
        for name, value in values.items():
            setattr(self, name, value)


VIS = Enum(Visible='Visible', Collapsed='Collapsed', Hidden='Hidden')
RESIZE = Enum(NoResize='NoResize', CanResize='CanResize')
SIZE_TO = Enum(Manual='Manual', Height='Height', WidthAndHeight='WidthAndHeight')
VALIGN = Enum(Top='Top', Stretch='Stretch')
KEY = Enum(H='H', Escape='Escape', Enter='Enter', F11='F11', F5='F5')
MODS = Enum(Control=2, Shift=4, Alt=1)
START = Enum(CenterScreen='CenterScreen', CenterOwner='CenterOwner')
NAN = float('nan')


class Corners(object):
    def __init__(self, a, b=None, c=None, d=None):
        self.TopLeft = a
        self.TopRight = a if b is None else b
        self.BottomRight = a if c is None else c
        self.BottomLeft = a if d is None else d

    def uniform(self):
        return (self.TopLeft == self.TopRight == self.BottomRight == self.BottomLeft)


class Pt(object):
    def __init__(self, x, y):
        self.X = x
        self.Y = y


class WindowType(object):
    TopProperty = 'TopProperty'
    HeightProperty = 'HeightProperty'


class Dbl(object):
    NaN = NAN


class Element(object):
    def __init__(self, visibility='Visible'):
        self.Visibility = visibility


class Panel(object):
    def __init__(self):
        self.Children = []


class Header(object):
    def __init__(self, height=50.0):
        self.ActualHeight = height
        self.CornerRadius = Corners(5, 5, 0, 0)
        self.Parent = None

    def TranslatePoint(self, point, relative_to):
        return Pt(1, 1)          # the window's one pixel outer border


class Button(object):
    def __init__(self):
        self.Click = Event()
        self.Tag = None
        self.ToolTip = None


class Root(object):
    def __init__(self):
        self.Height = NAN
        self.VerticalAlignment = 'Stretch'


class FakeWindow(object):
    """Enough of a WPF Window for the drawer, recording what happens to it."""

    def __init__(self, left=100.0, top=80.0, width=1200.0, height=800.0,
                 min_height=560.0, size_to='Manual', header_height=50.0):
        self.Left = left
        self._top = top
        self._height = height if size_to == 'Manual' else NAN
        self._actual_height = height
        self.Width = width
        self.MinHeight = min_height
        self.ResizeMode = 'CanResize'
        self.SizeToContent = size_to
        self.Owner = None
        self.WindowStartupLocation = 'CenterOwner'
        self.PreviewKeyDown = Event()
        self.Closed = Event()
        self.released = []            # BeginAnimation(prop, None) calls
        self.frames = []              # (top, height, root height) per frame
        self.activated = 0
        self.dragged = 0
        self.throw_on_top = 0         # throw on this many Top assignments

        self.header = Header(header_height)
        self.button = Button()
        self.body = Element('Visible')
        self.footer = Element('Visible')
        self.grips = Element('Visible')
        self.overlay = Element('Collapsed')     # was hidden before; must stay so
        self.grid = Panel()
        self.grid.Children = [self.header, self.body, self.footer, self.grips,
                              self.overlay]
        self.header.Parent = self.grid
        self.Content = Root()

    # Top and Height, recording every frame of a slide
    @property
    def Top(self):
        return self._top

    @Top.setter
    def Top(self, value):
        if self.throw_on_top > 0:
            self.throw_on_top -= 1
            raise RuntimeError('frame refused')
        self._top = value
        self.frames.append((value, self._actual_height, self.Content.Height))

    @property
    def Height(self):
        return self._height

    @Height.setter
    def Height(self, value):
        # a Height below MinHeight is refused, as WPF clamps it
        if value == value and value < self.MinHeight:
            value = self.MinHeight
        self._height = value
        if value == value:
            self._actual_height = value

    @property
    def ActualHeight(self):
        return self._actual_height

    @property
    def ActualWidth(self):
        return self.Width

    def FindName(self, name):
        return {'HeaderBar': self.header, 'ShrinkButton': self.button}.get(name)

    def BeginAnimation(self, prop, animation):
        if animation is None:
            self.released.append(prop)

    def Activate(self):
        self.activated += 1

    def DragMove(self):
        self.dragged += 1

    def close(self):
        self.Closed.fire(self, None)


class Timer(object):
    """Runs every tick at once, the way a slide would play out, frame by frame.

    An exception out of a tick is NOT raised back to whoever called Start.  A
    real DispatcherTimer never calls Tick from inside Start - the exception
    goes to the dispatcher, and the code that started the slide never hears of
    it.  Raising it here instead would let the slide's own fallback catch it
    and hide a drawer that, in Revit, is stranded mid-slide for good.
    """
    escaped = []

    def __init__(self, interval_ms, on_tick):
        self.on_tick = on_tick
        self.running = False

    def Start(self):
        self.running = True
        guard = 0
        while self.running and guard < 500:
            guard += 1
            try:
                self.on_tick(None, None)
            except Exception as ex:
                Timer.escaped.append(ex)
                return

    def Stop(self):
        self.running = False


def broken_timer(interval_ms, on_tick):
    raise RuntimeError('no timer on this machine')


class Clock(object):
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        self.now += 0.02
        return self.now


class KeyArgs(object):
    def __init__(self, key):
        self.Key = key
        self.Handled = False


class MouseArgs(object):
    def __init__(self, clicks):
        self.ClickCount = clicks
        self.Handled = False


PRIMARY = (0.0, 0.0, 1920.0, 1040.0)
ABOVE = (0.0, -1080.0, 1920.0, 1040.0)      # a second monitor above the primary


# ---------------------------------------------------------------------------
# Loading the module under test - from disk, or from a deliberately broken copy
# ---------------------------------------------------------------------------

def load_drawer(source=None):
    text = source if source is not None else io.open(
        SOURCE_PATH, encoding='utf-8').read()
    module = types.ModuleType('pstm_drawer_under_test')
    module.__file__ = SOURCE_PATH
    exec(compile(text, SOURCE_PATH, 'exec'), module.__dict__)
    module.Visibility = VIS
    module.ResizeMode = RESIZE
    module.SizeToContent = SIZE_TO
    module.VerticalAlignment = VALIGN
    module.CornerRadius = Corners
    module.Point = Pt
    module.Window = WindowType
    module.Double = Dbl
    module.Key = KEY
    module.ModifierKeys = MODS
    module.WindowStartupLocation = START
    module._LIVE[:] = []
    return module


def make(module, window, area=PRIMARY, mods=0, timer=Timer):
    drawer = module.Drawer(window, timer_factory=timer, clock=Clock(),
                           area_of=lambda w: area)
    drawer._modifiers = lambda: mods
    return drawer


def close(a, b, tol=0.6):
    return abs(float(a) - float(b)) <= tol


# ---------------------------------------------------------------------------
# The checks.  Each takes the module and appends to problems.
# ---------------------------------------------------------------------------

def check_arithmetic(m, problems):
    if m.ease_out(0) != 0.0 or m.ease_out(1) != 1.0:
        problems.append('ease_out must run 0 to 1')
    if not close(m.ease_out(0.5), 0.875, 0.001):
        problems.append('ease_out(0.5) should be 0.875, got {0}'.format(
            m.ease_out(0.5)))
    last = -1.0
    for i in range(21):
        value = m.ease_out(i / 20.0)
        if value < last:
            problems.append('ease_out must never go backwards')
            break
        last = value
    if m.lowest_free([0, 1, 3]) != 2 or m.lowest_free([]) != 0:
        problems.append('lowest_free must reuse the lowest gap')
    if m.shrunk_top(0, 1040, 52, 0) != 980:
        problems.append('a bar on the primary lands at 980, got {0}'.format(
            m.shrunk_top(0, 1040, 52, 0)))
    if m.shrunk_top(-1080, 1040, 52, 0) != -100:
        problems.append('a bar on the monitor above lands at -100, got {0}'.format(
            m.shrunk_top(-1080, 1040, 52, 0)))
    # a bar dragged hard right reopens inside the screen, not off its edge
    rect = m.reopen_rect((100, 80, 1200, 800), 1800, 500, 52, True, PRIMARY)
    if rect[0] + rect[2] > 1920 or rect[1] < 0:
        problems.append('reopen_rect must keep the window on its screen: '
                        '{0}'.format(rect))


def check_shrink_lands(m, problems):
    w = FakeWindow()
    d = make(m, w)
    d.shrink()
    bar = 50.0 + 2.0
    if not d.shrunk or d.sliding:
        problems.append('after the slide the drawer should be shrunk and still')
    if not close(w.ActualHeight, bar):
        problems.append('the window should be exactly the bar ({0}), got '
                        '{1}'.format(bar, w.ActualHeight))
    if not close(w.Top, 1040 - 8 - bar):
        problems.append('the bar should rest 8 px above the work area, got '
                        'top {0}'.format(w.Top))
    if w.button.Tag != 'shrunk':
        problems.append('the button should be tagged "shrunk" so the style '
                        'swaps in the green arrow')
    if w.MinHeight != 0.0:
        problems.append('MinHeight must be relaxed while shrunk, or it vetoes '
                        'the slide and leaves the window half shut')
    if w.ResizeMode != 'NoResize':
        problems.append('a parked bar must not be resizable')
    for name in ('body', 'footer', 'grips'):
        if getattr(w, name).Visibility != 'Collapsed':
            problems.append('the {0} should be collapsed while shrunk - left '
                            'visible, grips swallow the click on the '
                            'arrow'.format(name))
    if not w.header.CornerRadius.uniform():
        problems.append('a parked bar should be rounded on all four corners')
    root = w.Content
    if root.Height == root.Height or root.VerticalAlignment != 'Stretch':
        problems.append('the root must be unpinned once landed, so it draws '
                        'its whole outline around the bar')


def check_animation_released(m, problems):
    w = FakeWindow()
    d = make(m, w)
    d.shrink()
    if w.released.count('TopProperty') < 1 or w.released.count('HeightProperty') < 1:
        problems.append('the end of a slide must release Top and Height with '
                        'BeginAnimation(prop, None) - a held animation value '
                        'outranks every later assignment and the window never '
                        'resizes again')
    d.expand()
    if w.released.count('TopProperty') < 2 or w.released.count('HeightProperty') < 2:
        problems.append('reopening must release the animation too')


def check_slide_is_animated(m, problems):
    w = FakeWindow()
    d = make(m, w)
    start = w.Top
    d.shrink()
    end = w.Top
    middle = [top for top, _, _ in w.frames[:-1] if start < top < end]
    if len(middle) < 5:
        problems.append('the shrink should play over several frames, got '
                        '{0}'.format(len(middle)))
    tops = [top for top, _, _ in w.frames]
    if any(b < a for a, b in zip(tops, tops[1:])):
        problems.append('a shrinking window must only ever move down')


def check_body_pinned_while_sliding(m, problems):
    w = FakeWindow()
    d = make(m, w)
    d.shrink()
    during = [root for _, _, root in w.frames[:-1]]
    if not during or any(not close(r, 800) for r in during if r == r) \
            or any(r != r for r in during):
        problems.append('the body must be pinned at its full height for the '
                        'whole slide, or the grid re-measures every frame: '
                        '{0}'.format(sorted(set([round(r, 1) if r == r else 'nan'
                                                 for r in during]))[:4]))


def check_expand_restores(m, problems):
    w = FakeWindow()
    d = make(m, w)
    d.shrink()
    d.expand()
    if d.parked:
        problems.append('after reopening the drawer should not be parked')
    if not (close(w.Left, 100) and close(w.Top, 80) and close(w.ActualHeight, 800)):
        problems.append('an untouched bar should reopen exactly where it came '
                        'from, got ({0}, {1}, h {2})'.format(
                            w.Left, w.Top, w.ActualHeight))
    if w.MinHeight != 560.0:
        problems.append('MinHeight must be put back, or the window can be '
                        'dragged shut for the rest of the session')
    if w.ResizeMode != 'CanResize':
        problems.append('ResizeMode must be put back')
    for name in ('body', 'footer', 'grips'):
        if getattr(w, name).Visibility != 'Visible':
            problems.append('the {0} should be visible again'.format(name))
    if w.overlay.Visibility != 'Collapsed':
        problems.append('a panel that was hidden before shrinking must stay '
                        'hidden after - visibility goes back to what it WAS')
    if w.button.Tag is not None:
        problems.append('the button should go back to the shrink glyph')
    if not w.header.CornerRadius.BottomLeft == 0:
        problems.append('the header corners should go back to square bottoms')
    root = w.Content
    if root.Height == root.Height:
        problems.append('the root must be unpinned after reopening')
    if w.activated < 1:
        problems.append('a window brought back should be activated')


def check_moved_bar_opens_upward(m, problems):
    w = FakeWindow()
    d = make(m, w)
    d.shrink()
    w.Left, w.Top = 300.0, 900.0           # the user carried the bar
    d.expand()
    if not close(w.Top + w.ActualHeight, 900 + 52):
        problems.append('a moved bar should open upward from where it sits - '
                        'bottom at the bar bottom - got top {0}'.format(w.Top))
    if not close(w.Left, 300):
        problems.append('a moved bar should open where it sits, not jump home')

    # carried near the top, there is no room to open upward: it stays on screen
    w2 = FakeWindow()
    d2 = make(m, w2)
    d2.shrink()
    w2.Left, w2.Top = 300.0, 100.0
    d2.expand()
    if not close(w2.Top, 0):
        problems.append('a bar carried near the top should open from the top '
                        'of the screen, not off it - got top {0}'.format(w2.Top))


def check_monitor_above(m, problems):
    w = FakeWindow(top=-1000.0)
    d = make(m, w, area=ABOVE)
    d.shrink()
    if not close(w.Top, -1080 + 1040 - 8 - 52):
        problems.append('on a monitor above the primary the bar must land on '
                        'that monitor (top -100), got {0}'.format(w.Top))


def check_stacking(m, problems):
    a, b, c = FakeWindow(), FakeWindow(), FakeWindow()
    da, db = make(m, a), make(m, b)
    da.shrink()
    db.shrink()
    if not close(b.Top, a.Top - 52 - 4):
        problems.append('a second bar should stack 4 px above the first, got '
                        '{0} over {1}'.format(b.Top, a.Top))
    da.expand()
    dc = make(m, c)
    dc.shrink()
    if dc.slot != 0 or not close(c.Top, 980):
        problems.append('a freed slot should be reused, got slot {0} top '
                        '{1}'.format(dc.slot, c.Top))


def check_owner_lifting(m, problems):
    main, dialog = FakeWindow(), FakeWindow(left=400, top=300, width=500,
                                            height=300, min_height=170)
    dialog.Owner = main
    dm, dd = make(m, main), make(m, dialog)
    dd.shrink()
    if not dm.shrunk:
        problems.append('shrinking a dialog must take its owner down too, or '
                        'the owner just sits over Revit')
    if not dialog.Top < main.Top:
        problems.append('the dialog bar should stack above its owner')
    dd.expand()
    if dm.shrunk or not (close(main.Top, 80) and close(main.ActualHeight, 800)):
        problems.append('bringing the dialog back must bring its owner back')
    if main.activated:
        problems.append('the owner should come back behind the dialog, not be '
                        'activated over it')

    # closing a dialog while it is parked brings the owner back
    dd.shrink()
    dialog.close()
    if dm.shrunk:
        problems.append('closing a parked dialog must bring its owner back')
    if dd in m._LIVE:
        problems.append('a closed window must leave the live list')


def check_keys(m, problems):
    w = FakeWindow()
    d = make(m, w, mods=MODS.Control | MODS.Shift)
    args = KeyArgs('H')
    w.PreviewKeyDown.fire(w, args)
    if not d.shrunk or not args.Handled:
        problems.append('Ctrl+Shift+H should shrink the window')
    for key in ('Escape', 'Enter', 'F11'):
        if not d.shrunk:
            d.shrink()
        args = KeyArgs(key)
        d._modifiers = lambda: 0
        w.PreviewKeyDown.fire(w, args)
        if d.shrunk or not args.Handled:
            problems.append('{0} on a parked bar should bring it back and be '
                            'handled, not reach a close prompt'.format(key))
    args = KeyArgs('Escape')
    w.PreviewKeyDown.fire(w, args)
    if args.Handled:
        problems.append('Escape on an open window is not the drawer\'s')


def check_header_clicks(m, problems):
    w = FakeWindow()
    d = make(m, w)
    if d.on_header_down(MouseArgs(2)):
        problems.append('an open window\'s header is not the drawer\'s')
    d.shrink()
    if not d.on_header_down(MouseArgs(1)) or w.dragged != 1:
        problems.append('a single click on a parked bar should drag it')
    if not d.on_header_down(MouseArgs(1), can_drag=False) or w.dragged != 1:
        problems.append('can_drag=False must not drag (no modal loop mid job)')
    d.on_header_down(MouseArgs(2))
    if d.shrunk:
        problems.append('a double click on a parked bar should bring it back')


def check_button(m, problems):
    w = FakeWindow()
    d = make(m, w)
    w.button.Click.fire(w.button, None)
    if not d.shrunk:
        problems.append('the shrink button must be wired to the drawer')
    w.button.Click.fire(w.button, None)
    if d.shrunk:
        problems.append('the green arrow must bring the window back')


def check_frame_that_throws(m, problems):
    w = FakeWindow()
    d = make(m, w)
    w.throw_on_top = 1
    try:
        d.shrink()
    except Exception as ex:
        problems.append('a frame that throws must not escape: {0}'.format(ex))
        return
    if not d.shrunk or not close(w.Top, 980):
        problems.append('a frame that throws should land the window at the '
                        'end state, got shrunk={0} top={1}'.format(d.shrunk, w.Top))


def check_no_timer(m, problems):
    w = FakeWindow()
    d = make(m, w, timer=broken_timer)
    d.shrink()
    if not d.shrunk or not close(w.Top, 980):
        problems.append('when no timer can start the window should still land')
    if 'TopProperty' not in w.released:
        problems.append('the release must happen on the no-animation path too')


def check_size_to_content(m, problems):
    w = FakeWindow(width=470, height=260, min_height=170, size_to='Height')
    d = make(m, w)
    d.shrink()
    if not close(w.ActualHeight, 52):
        problems.append('a SizeToContent window must still shrink to the bar, '
                        'got {0}'.format(w.ActualHeight))
    d.expand()
    if w.SizeToContent != 'Height':
        problems.append('SizeToContent must be put back after reopening')
    if not close(w.ActualHeight, 260):
        problems.append('a SizeToContent window should reopen at its size, got '
                        '{0}'.format(w.ActualHeight))


def check_adopt(m, problems):
    main, dialog = FakeWindow(), FakeWindow()
    dm = make(m, main)
    m.adopt(dialog, main)
    if dialog.WindowStartupLocation == 'CenterScreen':
        problems.append('a dialog over an open owner should stay centred on it')
    dm.shrink()
    later = FakeWindow()
    m.adopt(later, main)
    if later.WindowStartupLocation != 'CenterScreen':
        problems.append('a dialog over a parked owner must open mid-screen, not '
                        'centred on a 50 px bar at the bottom of it')
    if later.Owner is not main:
        problems.append('adopt must still set the owner')


def check_idempotent(m, problems):
    w = FakeWindow()
    d = make(m, w)
    d.shrink()
    top = w.Top
    d.shrink()
    if not close(w.Top, top) or not d.shrunk:
        problems.append('shrinking a shrunk window must do nothing')
    d.expand()
    d.expand()
    if not close(w.Top, 80):
        problems.append('reopening an open window must do nothing')


def check_true_size(m, problems):
    w = FakeWindow()
    d = make(m, w)
    d.shrink()
    if d.true_size() != (1200.0, 800.0):
        problems.append('true_size must report the real size while shrunk, or '
                        'size memory saves a 50 px window: {0}'.format(
                            d.true_size()))


CHECKS = [
    check_arithmetic, check_shrink_lands, check_animation_released,
    check_slide_is_animated, check_body_pinned_while_sliding,
    check_expand_restores, check_moved_bar_opens_upward, check_monitor_above,
    check_stacking, check_owner_lifting, check_keys, check_header_clicks,
    check_button, check_frame_that_throws, check_no_timer,
    check_size_to_content, check_adopt, check_idempotent, check_true_size,
]


def run(source=None):
    problems = []
    for check in CHECKS:
        Timer.escaped[:] = []
        try:
            module = load_drawer(source)
            check(module, problems)
        except Exception as ex:
            problems.append('{0} blew up: {1}: {2}'.format(
                check.__name__, ex.__class__.__name__, ex))
        if Timer.escaped:
            problems.append('{0}: an exception escaped a timer tick ({1}) - in '
                            'Revit that strands the window mid-slide'.format(
                                check.__name__, Timer.escaped[0]))
    return problems


# ---------------------------------------------------------------------------
# Breakages: each is (what it breaks, old text, new text).  Every one must be
# caught, or the check it relies on is not checking anything.
# ---------------------------------------------------------------------------

BREAKAGES = [
    ('animation never released',
     "            w.BeginAnimation(Window.TopProperty, None)",
     "            pass"),
    ('MinHeight not relaxed',
     "        _set(w, 'MinHeight', 0.0)", "        pass"),
    ('MinHeight not put back',
     "        _set(w, 'MinHeight', self._kept.get('min_height'))", "        pass"),
    ('SizeToContent not put back',
     "        _set(w, 'SizeToContent', self._kept.get('size_to'))", "        pass"),
    ('ResizeMode not put back',
     "        _set(w, 'ResizeMode', self._kept.get('resize'))", "        pass"),
    ('body not pinned for the slide',
     "        _set(root, 'Height', height)", "        pass"),
    ('root left pinned after landing',
     "        # draw its whole rounded outline around the header\n        self._unpin()",
     "        # draw its whole rounded outline around the header\n        pass"),
    ('body and grips left visible',
     "                child.Visibility = Visibility.Collapsed", "                pass"),
    ('visibility restored as Visible, not as it was',
     "                child.Visibility = was",
     "                child.Visibility = Visibility.Visible"),
    ('work-area top ignored',
     "    return float(area_top) + float(area_height)",
     "    return 0.0 + float(area_height)"),
    ('margin ignored',
     "float(area_height) - margin - float(below)",
     "float(area_height) - float(below)"),
    ('bars not stacked',
     "        top = shrunk_top(area[1], area[3], self.bar, below)",
     "        top = shrunk_top(area[1], area[3], self.bar, 0.0)"),
    ('slots never reused',
     "    while slot in taken:\n        slot += 1\n    return slot",
     "    return len(taken)"),
    ('owner not lifted',
     "            owner.shrink(animate=False)\n            self.lifted = owner",
     "            pass"),
    ('owner not brought back on close',
     "                lifted.expand(animate=False)\n            except Exception:\n                pass\n        try:\n            _LIVE.remove(self)",
     "                pass\n            except Exception:\n                pass\n        try:\n            _LIVE.remove(self)"),
    ('moved bar ignored',
     "                           was_moved(self.landed, now), self._area_of(w))",
     "                           False, self._area_of(w))"),
    ('button never tagged',
     "                self.button.Tag = SHRUNK_TAG", "                pass"),
    ('button never wired',
     "            self.button.Click += self._button_handler", "            pass"),
    ('Escape does not reopen',
     "(Key.Escape, Key.Enter, Key.F11)", "(Key.Enter, Key.F11)"),
    ('frame that throws escapes',
     "            # a frame that throws lands the window at the end state rather than\n            # leaving it stranded half way\n            self._finish_slide()",
     "            raise"),
    ('no timer, no landing',
     "            # could not animate at all: land at the end state\n            self._finish_slide()",
     "            raise"),
    ('not animated at all',
     "        if not animate:\n            self._finish_slide()",
     "        if True:\n            self._finish_slide()"),
    ('adopt ignores a parked owner',
     "            dialog.WindowStartupLocation = WindowStartupLocation.CenterScreen",
     "            pass"),
    ('true_size reports the bar',
     "        if self.parked and self.saved is not None:",
     "        if False:"),
    ('owner activated over the dialog',
     "                lifted.expand(animate=False, activate=False)",
     "                lifted.expand(animate=False)"),
    ('double click on the bar does not reopen',
     "            if args.ClickCount == 2:\n                self.expand()",
     "            if args.ClickCount == 99:\n                self.expand()"),
]


def run_breakages():
    text = io.open(SOURCE_PATH, encoding='utf-8').read()
    missed = []
    for name, old, new in BREAKAGES:
        if old not in text:
            missed.append('{0}: the text to break is not in pstm_drawer.py any '
                          'more - update the breakage'.format(name))
            continue
        broken = text.replace(old, new, 1)
        if not run(broken):
            missed.append('{0}: NOT caught'.format(name))
    return missed


def main():
    if '--breakages' in sys.argv:
        missed = run_breakages()
        if missed:
            sys.stdout.write('FAILED - {0} breakage(s) slipped through\n'.format(
                len(missed)))
            for line in missed:
                sys.stdout.write('  * {0}\n'.format(line))
            return 1
        sys.stdout.write('OK - all {0} breakages caught\n'.format(len(BREAKAGES)))
        return 0
    problems = run()
    if problems:
        sys.stdout.write('FAILED - {0} problem(s)\n'.format(len(problems)))
        for line in problems:
            sys.stdout.write('  * {0}\n'.format(line))
        return 1
    sys.stdout.write('OK - {0} drawer checks pass\n'.format(len(CHECKS)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
