# -*- coding: utf-8 -*-
u"""RevoBIM Addin Manager - hand-eased animation for the favourites grid.

The house rules for any RevoBIM animation, and how each is met here:

* **No WPF animation objects.** A Storyboard or BeginAnimation holds its end
  value and outranks every later assignment; the bench forbids them. Every
  frame here is a plain assignment.
* **Frames come from CompositionTarget.Rendering**, which fires once per
  rendered frame in step with the screen - not a DispatcherTimer, which drifts
  against it and reads as judder.
* **Time from the frame**, `RenderingEventArgs.RenderingTime`, not
  `time.time()`, which can move in 15 ms steps on Windows. A frame time seen
  twice is skipped, and a slow frame is clamped so a Revit hiccup never makes
  a tile jump.
* **Render transforms only.** What moves is a ScaleTransform and a
  TranslateTransform - render-only - so nothing is laid out per frame.
* **One stored EventHandler**, so the `-=` that unhooks the frame handler
  removes exactly what `+=` added. A bound method makes a fresh delegate on
  every access in IronPython and would never come off.

`Tweens` itself has no WPF in it: `tick(now)` advances everything to a time,
which is how the logic bench drives whole animations against a fake clock.
"""

import rba_clr  # noqa: F401

from System import EventHandler
from System.Diagnostics import Stopwatch
from System.Windows.Media import CompositionTarget

import rba_core

from rba_core import log_exception

MAX_FRAME = 0.034          # a slow frame counts as at most this much progress


class Tweens(object):

    def __init__(self):
        self.active = {}               # name -> tween
        self.last = None
        self.on_idle = None            # called when the last tween finishes
        self.on_busy = None            # called when the first one starts

    def add(self, name, start, end, seconds, apply, ease=None, done=None):
        u"""Animate a value from start to end, calling apply(value) each frame.

        A new tween under a name already running replaces it, starting from
        wherever the value is now - so a drop that interrupts a lift does not
        snap back first.
        """
        if name in self.active:
            start = self.active[name][u"value"]
        was_idle = not self.active
        self.active[name] = {u"start": float(start), u"end": float(end),
                             u"seconds": max(0.001, float(seconds)),
                             u"elapsed": 0.0, u"apply": apply,
                             u"ease": ease or rba_core.ease_out,
                             u"done": done, u"value": float(start)}
        try:
            apply(float(start))
        except Exception:
            log_exception(u"tween/apply")
        if was_idle and self.on_busy is not None:
            self.on_busy()

    def stop(self, name):
        self.active.pop(name, None)

    def busy(self):
        return bool(self.active)

    def tick(self, now):
        u"""Advance every tween to time now (seconds). Returns how many ran."""
        if not self.active:
            return 0
        if self.last is None:
            self.last = now
            return len(self.active)
        step = now - self.last
        if step <= 0:
            return len(self.active)        # the same frame seen twice
        self.last = now
        step = min(step, MAX_FRAME)
        finished = []
        for name in list(self.active.keys()):
            tween = self.active.get(name)
            if tween is None:
                continue
            tween[u"elapsed"] += step
            progress = tween[u"elapsed"] / tween[u"seconds"]
            if progress >= 1.0:
                value = tween[u"end"]
            else:
                value = tween[u"start"] + (tween[u"end"] - tween[u"start"]) * \
                    tween[u"ease"](progress)
            tween[u"value"] = value
            try:
                tween[u"apply"](value)
            except Exception:
                log_exception(u"tween/apply")
                progress = 1.0
            if progress >= 1.0:
                finished.append((name, tween))
        for name, tween in finished:
            # Only remove it if a newer tween has not taken the name since.
            if self.active.get(name) is tween:
                del self.active[name]
            if tween[u"done"] is not None:
                try:
                    tween[u"done"]()
                except Exception:
                    log_exception(u"tween/done")
        if not self.active:
            self.last = None
            # Only on the frame the last one finished - not every frame after.
            if finished and self.on_idle is not None:
                self.on_idle()
        return len(self.active)

    def finish_all(self):
        u"""Land everything at its end at once - for a grid being rebuilt."""
        for name in list(self.active.keys()):
            tween = self.active.pop(name)
            try:
                tween[u"apply"](tween[u"end"])
            except Exception:
                pass
            if tween[u"done"] is not None:
                try:
                    tween[u"done"]()
                except Exception:
                    pass
        self.last = None


class FrameDriver(object):
    u"""Hooks a Tweens to CompositionTarget.Rendering while it has work."""

    def __init__(self, tweens):
        self.tweens = tweens
        self.watch = None
        self.hooked = False
        # Stored once: the same object is added and removed, so -= finds it.
        self.handler = EventHandler(self._on_frame)
        tweens.on_busy = self.hook
        tweens.on_idle = self.unhook

    def hook(self):
        if self.hooked:
            return
        try:
            CompositionTarget.Rendering += self.handler
            self.hooked = True
        except Exception:
            log_exception(u"tween/hook")

    def unhook(self):
        if not self.hooked:
            return
        try:
            CompositionTarget.Rendering -= self.handler
        except Exception:
            log_exception(u"tween/unhook")
        self.hooked = False

    def _on_frame(self, sender, args):
        try:
            now = args.RenderingTime.TotalSeconds
        except Exception:
            # Not a RenderingEventArgs on this host: fall back to a stopwatch.
            if self.watch is None:
                self.watch = Stopwatch.StartNew()
            now = self.watch.Elapsed.TotalSeconds
        self.tweens.tick(now)
