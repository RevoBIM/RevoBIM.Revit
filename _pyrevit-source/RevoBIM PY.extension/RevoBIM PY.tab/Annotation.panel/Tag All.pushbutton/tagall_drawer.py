# -*- coding: utf-8 -*-
"""Shrink to the taskbar - the drawer every Tag All window carries.

Pressing the shrink button slides the window down to the bottom of its own
screen like a drawer closing, leaving only its header floating clear of the
taskbar so Revit can be worked in. The button turns into a green up arrow
that opens it again; so do a double-click on the bar, Escape, Enter, F11 and
Ctrl+Shift+H.

Built to the RevoBIM drawer standard (theme reference; Pro Sheets 1.49.0):

- Top and Height are eased together on a 15 ms timer for 280 ms, written as
  plain values. A Storyboard on a borderless window's Top/Height fights the
  layout pass, and an animation that is never released holds its end value
  over every later assignment - a window that can never be moved or resized
  again, with nothing raised to say so. There is no animation clock here to
  release.
- MinHeight and SizeToContent both veto a shrinking Height, leaving a window
  half shut; both are relaxed for the slide and put back when it reopens.
- The body is pinned at its height for the slide, so it is drawn away rather
  than squashed and re-measured on every frame.
- On landing, everything beside the header is parked - the resize grips too,
  or they line the bar with invisible handles that swallow the click on the
  arrow - and put back to what it was, so a panel already hidden stays so.
- A dialog parks the window it belongs to first, so that window is not left
  covering the model; a window parks its open dialogs with it. Bars stack.

Nothing in this module touches WPF. Every call that would goes through the
`platform` object handed in - WpfPlatform in tagall_ui for real windows, a
stand-in in bench_logic - so the whole slide can be driven on the bench.
"""
import tagall_core as core

# every live drawer, so a dialog can find its owner's and bars can stack
DRAWERS = []


def drawer_of(window):
    """The drawer carried by a window, or None."""
    if window is None:
        return None
    for drawer in DRAWERS:
        if drawer.window is window:
            return drawer
    try:
        for drawer in DRAWERS:
            if drawer.window == window:
                return drawer
    except Exception:
        pass
    return None


class WindowDrawer(object):

    def __init__(self, window, header, button, platform, on_change=None):
        self.window = window
        self.header = header
        self.button = button
        self.platform = platform
        self.on_change = on_change
        self.shrunk = False
        self.sliding = False
        self.saved = None
        self.slot = None
        self.bar = 0.0
        self.landed_top = 0.0
        self.hidden = []
        self.corner = None
        self.lifted = []        # owners this dialog parked on its way down
        self.followers = []     # dialogs parked along with this window
        self.timer = None       # held, or the collector takes it mid-slide
        DRAWERS.append(self)
        if button is not None:
            platform.on_click(button, self._button_click)
        platform.on_closed(window, self._closed)

    # ---------- state ----------

    def busy(self):
        return self.shrunk or self.sliding

    def true_size(self):
        """The window's real size: what it was before it was parked. A
        window closed while parked must not save a forty-pixel height."""
        if self.saved is not None and self.busy():
            return self.saved["width"], self.saved["height"]
        return self.window.Width, self.platform.height(self.window)

    def _changed(self):
        if self.on_change is not None:
            try:
                self.on_change(self.shrunk)
            except Exception:
                pass

    # ---------- gestures ----------

    def _button_click(self, sender, args):
        self.toggle()

    def toggle(self):
        if self.shrunk:
            return self.expand()
        return self.shrink()

    def header_down(self, click_count):
        """A press on the header. Returns True when the drawer took it: a
        double-click on a parked bar reopens it, and nothing on the header
        acts while the window is sliding. A single press on a parked bar
        returns False, so the caller still drags the bar."""
        if self.sliding:
            return True
        if self.shrunk and click_count >= 2:
            self.expand()
            return True
        return False

    def key(self, name, control, shift):
        """A key press. Returns True when the drawer took it. Ctrl+Shift+H
        toggles; while parked Escape, Enter and F11 reopen the window rather
        than closing it, answering a prompt nobody can see, or filling the
        screen with it."""
        if control and shift and name == "H":
            self.toggle()
            return True
        if self.busy() and name in ("Escape", "Enter", "Return", "F11"):
            if self.shrunk:
                self.expand()
            return True
        return False

    # ---------- shrinking ----------

    def shrink(self, animate=True):
        if self.busy():
            return False
        window = self.window
        platform = self.platform
        # busy before anything else: parking the dialogs below makes each of
        # them try to park its owner - this window - and an owner not yet
        # marked busy would be shrunk again by its own dialog, round and round
        # for ever. That recursion is what the bench caught here.
        self.sliding = True
        self.saved = {"left": window.Left, "top": window.Top, "width": window.Width,
                      "height": platform.height(window), "min_height": window.MinHeight,
                      "size_to_content": window.SizeToContent}
        # a dialog parks the window it belongs to first, so that one is not
        # left covering the model; a window parks its open dialogs with it
        owner = drawer_of(platform.owner(window))
        if owner is not None and not owner.busy():
            owner.shrink(animate=False)
            self.lifted.append(owner)
        for follower in [drawer_of(item) for item in platform.owned(window)]:
            if follower is not None and not follower.busy():
                follower.shrink(animate=False)
                self.followers.append(follower)
        window.SizeToContent = platform.manual_size()
        window.MinHeight = 0
        self.bar = platform.bar_height(self.header, window)
        area_top, area_bottom = platform.work_area(window)
        self.slot = core.free_slot([drawer.slot for drawer in DRAWERS
                                    if drawer is not self and drawer.busy() and drawer.slot is not None])
        self.landed_top = core.shrunk_top(area_top, area_bottom, self.bar, self.slot)
        platform.pin(window, self.saved["height"])
        self._slide(window.Top, self.landed_top, self.saved["height"], self.bar, self._landed, animate)
        return True

    def _landed(self):
        window = self.window
        platform = self.platform
        self.hidden = []
        for part in platform.parts_beside(self.header, window):
            self.hidden.append((part, platform.visibility(part)))
            platform.collapse(part)
        platform.unpin(window)
        self.corner = platform.round_header(self.header)
        window.Height = self.bar
        window.Top = self.landed_top
        self.sliding = False
        self.shrunk = True
        platform.shrunk_look(self.button, True)
        self._changed()

    # ---------- expanding ----------

    def expand(self, animate=True):
        if self.sliding or not self.shrunk:
            return False
        window = self.window
        platform = self.platform
        saved = self.saved
        area_top, area_bottom = platform.work_area(window)
        left, top, height = core.expand_geometry(
            saved["left"], saved["top"], saved["height"], window.Left, window.Top,
            self.landed_top, self.bar, area_top, area_bottom)
        # put back exactly what was there, so a panel already hidden stays so
        for part, visibility in self.hidden:
            platform.restore_visibility(part, visibility)
        self.hidden = []
        platform.restore_header(self.header, self.corner)
        self.corner = None
        platform.pin(window, height)
        platform.shrunk_look(self.button, False)
        self.shrunk = False
        self.sliding = True
        window.Left = left
        self._slide(window.Top, top, platform.height(window), height, self._opened, animate)
        return True

    def _opened(self):
        window = self.window
        platform = self.platform
        platform.unpin(window)
        window.MinHeight = self.saved["min_height"]
        window.SizeToContent = self.saved["size_to_content"]
        self.sliding = False
        self.slot = None
        platform.activate(window)
        lifted, self.lifted = self.lifted, []
        followers, self.followers = self.followers, []
        for drawer in lifted + followers:
            if drawer.shrunk:
                drawer.expand(animate=False)
        self._changed()

    # ---------- the slide ----------

    def _slide(self, top_from, top_to, height_from, height_to, done, animate):
        """Ease Top and Height together, then land exactly on the end values.

        Finishing happens once. The tick is handed its own timer and stops
        that one - not whatever `self.timer` happens to hold, which is the
        previous slide's until the platform has handed the new one back - and
        a tick arriving after the finish does nothing. Without both, a slide
        could finish over and over: each landing recorded the panels it had
        already parked as "collapsed", so they never came back. A frame that
        throws lands the window at the end state rather than leaving it half
        way.
        """
        window = self.window
        platform = self.platform
        state = {"finished": False}

        def finish(timer=None):
            if state["finished"]:
                return
            state["finished"] = True
            if timer is not None:
                try:
                    timer.Stop()
                except Exception:
                    pass
            self._stop_timer()
            try:
                window.Top = top_to
                window.Height = height_to
            except Exception:
                pass
            done()

        if not animate:
            finish()
            return
        start = platform.now()

        def tick(timer):
            if state["finished"]:
                try:
                    timer.Stop()
                except Exception:
                    pass
                return
            try:
                progress = (platform.now() - start) / float(core.DRAWER_MS)
                if progress >= 1.0:
                    finish(timer)
                    return
                window.Top = core.tween(top_from, top_to, progress)
                window.Height = core.tween(height_from, height_to, progress)
            except Exception:
                finish(timer)

        timer = platform.timer(core.DRAWER_TICK_MS, tick)
        if not state["finished"]:
            self.timer = timer

    def _stop_timer(self):
        if self.timer is not None:
            try:
                self.timer.Stop()
            except Exception:
                pass
        self.timer = None

    # ---------- closing ----------

    def _closed(self, sender=None, args=None):
        """A window closed while parked gives its slot up and brings back
        the window it parked on its way down."""
        self._stop_timer()
        lifted, self.lifted = self.lifted, []
        for drawer in lifted:
            if drawer.shrunk:
                drawer.expand(animate=False)
        self.shrunk = False
        self.sliding = False
        self.slot = None
        if self in DRAWERS:
            DRAWERS.remove(self)
