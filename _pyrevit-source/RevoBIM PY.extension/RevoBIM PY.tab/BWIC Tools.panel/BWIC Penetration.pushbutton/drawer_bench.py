# -*- coding: utf-8 -*-
"""Drive the shrink drawer against a stand-in window, outside Revit.

Fake WPF types, a timer that runs its ticks at once and a clock that moves
20 ms each read. Run by import_check.py; returns the failing checks.
Not loaded by the tool itself.
"""
import importlib
import sys


def run(here):
    sys.path.insert(0, here)
    dr = importlib.import_module('bwic_drawer')
    sys.path.pop(0)

    class E(object):           # an enum-ish token
        def __init__(s, n): s.n = n
        def __repr__(s): return s.n
    class Vis:      Visible, Collapsed, Hidden = E('Visible'), E('Collapsed'), E('Hidden')
    class VA:       Top, Stretch = E('Top'), E('Stretch')
    class STC:      Manual, Height = E('Manual'), E('Height')
    class Win:      TopProperty, HeightProperty = 'Top', 'Height'
    class Pt(object):
        def __init__(s, x, y): s.X, s.Y = x, y
    class Elapsed(object):
        def __init__(s, c): s.c = c
        @property
        def TotalSeconds(s): s.c.t += 0.02; return s.c.t
    class Clock(object):
        def __init__(s): s.t = 0.0
        @property
        def Elapsed(s): return Elapsed(s)
    class SW:
        @staticmethod
        def StartNew(): return Clock()
    class Evt(object):
        def __init__(s): s.h = []
        def __iadd__(s, f): s.h.append(f); return s
        def __isub__(s, f): s.h.remove(f); return s
    class Timer(object):
        live = []
        def __init__(s): s.Tick = Evt(); s.Interval = None; s.on = False
        def Start(s):
            s.on = True; Timer.live.append(s)
            for _ in range(200):                 # run the ticks at once
                if not s.on: break
                for h in list(s.Tick.h): h(s, None)
        def Stop(s): s.on = False
    class TS:
        @staticmethod
        def FromMilliseconds(ms): return ms
    class Dbl: NaN = float('nan')
    for k, v in dict(Visibility=Vis, VerticalAlignment=VA, SizeToContent=STC, Window=Win,
                     Point=Pt, Stopwatch=SW, DispatcherTimer=Timer, TimeSpan=TS,
                     Double=Dbl).items():
        setattr(dr, k, v)
    dr.work_area = lambda w: (0.0, 0.0, 1920.0, 1040.0)

    class El(object):
        def __init__(s, h=0.0): s.Visibility = Vis.Visible; s.ActualHeight = h; s.Height = Dbl.NaN; s.VerticalAlignment = VA.Stretch; s.Parent = None
        def TranslatePoint(s, p, w): return Pt(0, 13.0)
    class Grid(El):
        def __init__(s, kids): El.__init__(s, 600.0); s.Children = kids
    class Btn(object):
        Tag = ''; ToolTip = ''
    class Window(object):
        def __init__(s, top, h, mh, stc):
            s.Left, s.Top, s.ActualWidth, s.ActualHeight = 300.0, top, 430.0, h
            s.Height, s.MinHeight, s.SizeToContent, s.ResizeMode = h, mh, stc, 'NoResize'
            s.Closed = Evt(); s.activated = 0; s.released = []
        def BeginAnimation(s, prop, val): s.released.append((prop, val))
        def Activate(s): s.activated += 1
        def close(s):
            for h in s.Closed.h: h(s, None)

    def make(top, h, mh, stc, grips=None, lift=None, preset=None):
        header = El(49.0); tabs = El(); footer = El(); hidden = El()
        hidden.Visibility = Vis.Collapsed           # a panel that was ALREADY hidden
        body = Grid([header, tabs, footer, hidden]); header.Parent = body
        w = Window(top, h, mh, stc); b = Btn()
        return w, dr.Drawer(w, header, b, grips=grips, lift=lift), b, body, (tabs, footer, hidden)

    checks = []
    def ok(label, cond): checks.append((label, bool(cond)))

    grips = El()
    w, d, b, body, (tabs, footer, hidden) = make(120.0, 700.0, 380.0, STC.Height, grips=grips)
    d.shrink()
    bar = 49.0 + 26.0
    ok('parks at the bottom of the screen', abs(w.Top - (1040 - 8 - bar)) < 1e-6)
    ok('parked height is the bar', abs(w.Height - bar) < 1e-6)
    ok('is marked shrunk', d.shrunk and b.Tag == 'shrunk')
    ok('timer is stopped after landing', not d.busy and not Timer.live[-1].on)
    ok('tick handler removed', Timer.live[-1].Tick.h == [])
    ok('Top and Height released', ('Top', None) in w.released and ('Height', None) in w.released)
    ok('body siblings collapsed', tabs.Visibility is Vis.Collapsed and footer.Visibility is Vis.Collapsed)
    ok('grips parked', grips.Visibility is Vis.Collapsed)
    ok('MinHeight relaxed', w.MinHeight == 0)
    ok('SizeToContent relaxed', w.SizeToContent is STC.Manual)
    ok('body pinned for the slide', body.Height == 600.0 and body.VerticalAlignment is VA.Top)
    ok('true size reports the real window', d.true_size() == (430.0, 700.0))

    d.expand()
    ok('reopens to where it was', abs(w.Top - 120.0) < 1e-6 and abs(w.Height - 700.0) < 1e-6)
    ok('glyph back to shrink', b.Tag == '' and not d.shrunk)
    ok('siblings back as they were', tabs.Visibility is Vis.Visible and footer.Visibility is Vis.Visible)
    ok('an already hidden panel stays hidden', hidden.Visibility is Vis.Collapsed)
    ok('grips back', grips.Visibility is Vis.Visible)
    ok('MinHeight restored', w.MinHeight == 380.0)
    ok('SizeToContent restored', w.SizeToContent is STC.Height)
    ok('body unpinned', body.Height != body.Height and body.VerticalAlignment is VA.Stretch)
    ok('window activated', w.activated == 1)
    ok('slot released', d not in dr._SLOTS)

    # a moved bar opens upward from where it now sits
    d.shrink(); w.Left, w.Top = 900.0, 900.0; d.expand()
    ok('moved bar opens upward from where it sits',
       abs(w.Top - (900.0 + bar - 700.0)) < 1e-6 and w.Left == 900.0)

    # a dialog lifts its owner and stacks above it
    mw, md, mb, _, _ = make(120.0, 700.0, 380.0, STC.Height)
    sw, sd, sb, _, _ = make(150.0, 620.0, 0.0, STC.Manual, lift=md)
    sd.shrink()
    ok('dialog parks its owner first', md.shrunk and md.lift is None)
    ok('owner takes the bottom slot', dr._SLOTS.get(md) == 0)
    ok('dialog stacks above the owner', dr._SLOTS.get(sd) == 1 and sw.Top < mw.Top)
    sd.expand()
    ok('reopening the dialog brings the owner back', not md.shrunk and abs(mw.Top - 120.0) < 1e-6)
    sd.shrink(); sw.close()
    ok('closing a parked dialog brings the owner back', not md.shrunk)
    ok('closing frees the dialog slot', sd not in dr._SLOTS)

    # a frame that throws lands the window at its end state
    w2, d2, b2, _, _ = make(120.0, 700.0, 380.0, STC.Height)
    orig = dr.lerp
    dr.lerp = lambda a, b, t: (_ for _ in ()).throw(RuntimeError('frame'))
    d2.shrink(); dr.lerp = orig
    ok('a throwing frame still lands', d2.shrunk and abs(w2.Height - bar) < 1e-6 and not d2.busy)

    # toggle is ignored mid slide
    w3, d3, b3, _, _ = make(120.0, 700.0, 380.0, STC.Height)
    d3.busy = True; d3.toggle(); d3.busy = False
    ok('toggle ignored while sliding', not d3.shrunk)

    return checks



if __name__ == '__main__':
    import os
    results = run(os.path.dirname(os.path.abspath(__file__)))
    for label, passed in results:
        sys.stdout.write('{}  {}\n'.format('ok  ' if passed else 'FAIL', label))
