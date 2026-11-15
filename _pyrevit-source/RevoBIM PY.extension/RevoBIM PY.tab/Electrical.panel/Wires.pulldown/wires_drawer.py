# -*- coding: utf-8 -*-
"""RevoBIM PY - Wires: shrink to taskbar.

Every Wires window carries a shrink control in the top right. Pressed, the
window slides down to the bottom of the screen like a drawer closing, leaving
only its header bar floating clear of the taskbar so the model can be seen;
the control turns into a green up arrow that opens it again. Ctrl+Shift+H does
the same from the keyboard.

One WindowDrawer per window, built by wires_ui.dress_header, so the gesture is
identical everywhere.

The five things that make or break it, four of which fail silently:

1. An animation holds its end value and outranks every later assignment, so
   both animations are released in _land - in a try of their own, apart from
   writing the final numbers, because _land is also the fallback when the
   animation never started.
2. MinHeight and SizeToContent both veto a Height animation. Relaxed before
   the slide, restored when the window reopens.
3. The body is pinned at its own height for the slide and clipped by the
   shrinking window, so it reads as a drawer and not a squash.
4. (Resize grips: these windows have none, so there are none to park.)
5. While parked, Escape, Enter and F11 reopen rather than reaching the
   window's buttons, and a double-click on the bar reopens. The bar stays
   draggable; carried elsewhere, the window opens upward from where it sits.

The arithmetic is in plain functions at the top so the bench can prove it,
including a second monitor above the primary one, where the work area's top
is negative.
"""

import clr

for _asm in ('PresentationCore', 'PresentationFramework', 'WindowsBase',
             'mscorlib', 'System', 'System.Windows.Forms', 'System.Drawing'):
    try:
        clr.AddReference(_asm)
    except Exception:
        pass

DURATION_MS = 260
MARGIN = 8           # gap between the parked bar and the taskbar
TOLERANCE = 2.0      # how far the bar can drift and still count as unmoved
TIP_SHRINK = 'Shrink to the bottom of the screen (Ctrl+Shift+H)'
TIP_EXPAND = 'Bring the window back (Ctrl+Shift+H, Enter or double-click)'


# ---------------------------------------------------------------------------
# the arithmetic - pure, proved on the bench
# ---------------------------------------------------------------------------
def park_top(work_top, work_height, bar_height, margin=MARGIN):
    """Where the bar sits once parked: just above the bottom of the work area
    of the screen the window is on, whatever that screen's offset."""
    return float(work_top) + float(work_height) - float(bar_height) - margin


def clamp_top(top, height, work_top, work_height):
    """Keep a window of this height on the work area, top edge first."""
    lowest = float(work_top) + float(work_height) - float(height)
    top = min(float(top), lowest)
    return max(top, float(work_top))


def reopen_top(saved_top, parked_top, bar_top_now, bar_height, full_height,
               work_top, work_height, tolerance=TOLERANCE):
    """Where the window's top goes when it opens again.

    Left where it was parked, the window goes back exactly where it came from.
    Carried somewhere else, it opens upward from where the bar now sits - the
    bar's bottom edge becomes the window's bottom edge - so it does not jump
    back to a place the user has already moved on from. Either way it is kept
    on the screen.
    """
    if abs(float(bar_top_now) - float(parked_top)) <= tolerance:
        top = float(saved_top)
    else:
        top = float(bar_top_now) + float(bar_height) - float(full_height)
    return clamp_top(top, full_height, work_top, work_height)


# ---------------------------------------------------------------------------
# the drawer
# ---------------------------------------------------------------------------
class WindowDrawer(object):
    """Shrink and reopen one window. Every step swallows its own failure:
    a window that will not animate must still never become unusable."""

    def __init__(self, window, header, root, button):
        self.window = window
        self.header = header
        self.root = root
        self.button = button
        self.parked = False
        self.busy = False
        self.saved = {}
        self.parked_top = None
        self.suspended = []
        try:
            if button is not None:
                button.Click += self._on_click
        except Exception:
            pass
        try:
            window.PreviewKeyDown += self._on_key
        except Exception:
            pass

    # -- events --------------------------------------------------------------
    def _on_click(self, sender, args):
        self.toggle()

    def _on_key(self, sender, args):
        try:
            from System.Windows.Input import Key, Keyboard, ModifierKeys
            key = args.Key
            mods = Keyboard.Modifiers
            ctrl_shift = (ModifierKeys.Control | ModifierKeys.Shift)
            if key == Key.H and (mods & ctrl_shift) == ctrl_shift:
                args.Handled = True
                self.toggle()
                return
            if self.parked and key in (Key.Escape, Key.Return, Key.Enter,
                                       Key.F11):
                args.Handled = True
                self.expand()
        except Exception:
            pass

    def header_pressed(self, args):
        """The bar's MouseLeftButtonDown: a double-click while parked
        reopens; anything else drags, parked or not."""
        try:
            if self.parked and args.ClickCount >= 2:
                self.expand()
                return
        except Exception:
            pass
        try:
            self.window.DragMove()
        except Exception:
            pass

    def toggle(self):
        if self.parked:
            self.expand()
        else:
            self.shrink()

    # -- the screen ------------------------------------------------------------
    def _work_area(self):
        """(top, height) of the work area of the screen the window is on, in
        the window's own units. Falls back to the primary screen."""
        try:
            from System.Windows.Forms import Screen
            from System.Windows.Interop import WindowInteropHelper
            from System.Windows import PresentationSource
            handle = WindowInteropHelper(self.window).Handle
            area = Screen.FromHandle(handle).WorkingArea
            scale = 1.0
            try:
                source = PresentationSource.FromVisual(self.window)
                scale = float(source.CompositionTarget.TransformToDevice.M22) \
                    or 1.0
            except Exception:
                scale = 1.0
            return float(area.Top) / scale, float(area.Height) / scale
        except Exception:
            pass
        try:
            from System.Windows import SystemParameters
            area = SystemParameters.WorkArea
            return float(area.Top), float(area.Height)
        except Exception:
            return 0.0, 1000.0

    def _bar_height(self):
        try:
            # the header plus the chrome's 1px edge above and below it
            return float(self.header.ActualHeight) + 2.0
        except Exception:
            return 52.0

    # -- shrink ----------------------------------------------------------------
    def shrink(self):
        if self.parked or self.busy:
            return
        window = self.window
        try:
            self.saved = {
                'top': float(window.Top),
                'height': float(window.ActualHeight),
                'min_height': window.MinHeight,
                'size_to_content': window.SizeToContent,
            }
        except Exception:
            return
        work_top, work_height = self._work_area()
        bar = self._bar_height()
        self.parked_top = park_top(work_top, work_height, bar)

        # 2: nothing may veto the slide
        try:
            from System.Windows import SizeToContent
            window.SizeToContent = SizeToContent.Manual
        except Exception:
            pass
        try:
            window.MinHeight = 0
            window.Height = self.saved['height']
        except Exception:
            pass
        # 3: pin the body, let the window clip it
        self._pin(True)
        self._suspend_buttons(True)
        self.parked = True
        self._glyph(True)
        self._slide(self.parked_top, bar, None)

    # -- reopen ----------------------------------------------------------------
    def expand(self):
        if not self.parked or self.busy:
            return
        window = self.window
        work_top, work_height = self._work_area()
        try:
            bar_top_now = float(window.Top)
        except Exception:
            bar_top_now = self.parked_top
        full = self.saved.get('height', 400.0)
        top = reopen_top(self.saved.get('top', bar_top_now), self.parked_top,
                         bar_top_now, self._bar_height(), full,
                         work_top, work_height)
        self.parked = False
        self._glyph(False)
        self._slide(top, full, self._reopened)

    def _reopened(self):
        window = self.window
        try:
            window.MinHeight = self.saved.get('min_height', 0)
        except Exception:
            pass
        try:
            wanted = self.saved.get('size_to_content')
            if wanted is not None:
                window.SizeToContent = wanted
        except Exception:
            pass
        self._pin(False)
        self._suspend_buttons(False)
        try:
            window.Activate()
        except Exception:
            pass

    # -- the slide -------------------------------------------------------------
    def _slide(self, top, height, after):
        """Animate Top and Height together, then land on the exact numbers."""
        self.busy = True
        state = {'landed': False}

        def _land(sender=None, args=None):
            if state['landed']:
                return
            state['landed'] = True
            self._land(top, height)
            self.busy = False
            if after is not None:
                try:
                    after()
                except Exception:
                    pass

        try:
            from System import TimeSpan
            from System.Windows import Window, Duration
            from System.Windows.Media.Animation import (
                DoubleAnimation, QuadraticEase, EasingMode,
            )
            span = Duration(TimeSpan.FromMilliseconds(DURATION_MS))
            ease = QuadraticEase()
            ease.EasingMode = EasingMode.EaseInOut

            move = DoubleAnimation(float(self.window.Top), float(top), span)
            move.EasingFunction = ease
            size = DoubleAnimation(float(self.window.ActualHeight),
                                   float(height), span)
            size.EasingFunction = ease
            move.Completed += _land
            self.window.BeginAnimation(Window.HeightProperty, size)
            self.window.BeginAnimation(Window.TopProperty, move)
        except Exception:
            # could not animate: go straight there
            _land()

    def _land(self, top, height):
        """1: release both animations, then write the final numbers. Two
        separate trys, because a failed release must not stop the numbers
        being written - and this is the fallback path as well."""
        try:
            from System.Windows import Window
            self.window.BeginAnimation(Window.TopProperty, None)
            self.window.BeginAnimation(Window.HeightProperty, None)
        except Exception:
            pass
        try:
            self.window.Top = top
            self.window.Height = height
        except Exception:
            pass

    # -- pieces ----------------------------------------------------------------
    def _pin(self, on):
        root = self.root
        if root is None:
            return
        try:
            from System import Double
            from System.Windows import VerticalAlignment
            if on:
                root.Height = root.ActualHeight
                root.VerticalAlignment = VerticalAlignment.Top
            else:
                root.Height = Double.NaN
                root.VerticalAlignment = VerticalAlignment.Stretch
        except Exception:
            pass

    def _glyph(self, parked):
        """Down-to-the-bar while open; the green up arrow while parked."""
        try:
            from System.Windows import Visibility
            down = self.window.FindName('ShrinkGlyph')
            up = self.window.FindName('ExpandGlyph')
            if down is not None:
                down.Visibility = Visibility.Collapsed if parked \
                    else Visibility.Visible
            if up is not None:
                up.Visibility = Visibility.Visible if parked \
                    else Visibility.Collapsed
        except Exception:
            pass
        try:
            if self.button is not None:
                self.button.ToolTip = TIP_EXPAND if parked else TIP_SHRINK
        except Exception:
            pass

    def _suspend_buttons(self, parked):
        """5: while parked, Enter and Escape belong to the drawer, not to a
        Keep or Cancel button the user cannot see."""
        if parked:
            self.suspended = []
            for button in _buttons(self.window):
                try:
                    if button.IsDefault or button.IsCancel:
                        self.suspended.append(
                            (button, bool(button.IsDefault),
                             bool(button.IsCancel)))
                        button.IsDefault = False
                        button.IsCancel = False
                except Exception:
                    pass
            return
        for button, default, cancel in self.suspended:
            try:
                button.IsDefault = default
                button.IsCancel = cancel
            except Exception:
                pass
        self.suspended = []


def _buttons(root):
    """Every Button under root, walking the logical tree."""
    found = []
    try:
        from System.Windows import LogicalTreeHelper
        from System.Windows.Controls import Button
    except Exception:
        return found
    stack = [root]
    seen = 0
    while stack and seen < 5000:
        node = stack.pop()
        seen += 1
        try:
            if isinstance(node, Button):
                found.append(node)
        except Exception:
            pass
        try:
            for child in LogicalTreeHelper.GetChildren(node):
                stack.append(child)
        except Exception:
            pass
    return found
