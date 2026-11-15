# -*- coding: utf-8 -*-
u"""Hanger Automation - Circular System Based floor supports: the pure rules
(no Revit, no WPF), so the bench can test them in plain Python.

The circular path is separate from the rectangular one: hfam_core / hfam_revit
hold the rectangular rules and never call anything here.  A family is circular
only when it is saved as Circular System Based in Family settings (cfg style).
"""
import fha_core as core

RING_TOL_MM = 30.0       # a round face / arc counts as the ring within this of half the diameter ...
RING_TOL_SHARE = 0.35    # ... or this share of it, whichever is larger
CENTRE_OK_MM = 1.0       # the ring centre is 'on' the service centre within this


def is_circ(cfg):
    u"""A family saved as Circular System Based: a floor support or (1.14.0) a
    hanger - the style is saved per family, whichever tab saved it."""
    return (cfg or {}).get(u'style') == u'circ'


def circ_x_dir(run_axis, along, across):
    u"""Where the family's X must point so the service runs along its X - or,
    run_axis 'Y', along its Y (X then lies across the service)."""
    return across if run_axis == u'Y' else along


def width_axis(run_axis):
    u"""The rectangular 'width runs along' axis that turns a family the same way
    (for the dimension placer, which reads hangers by their width axis)."""
    return u'Y' if run_axis != u'Y' else u'X'


def support_height(z_centre, stand_z):
    u"""The support height parameter: from the base (the level, or the top of
    the floor / roof / equipment picked) up to the service centre AT THIS
    SUPPORT - the family's height parameter runs from its reference level to
    the ring centre, so the ring sits on the service's centreline, and a
    sloping pipe gets a different height at every support.  The same rule as
    the rectangular supports' first bar, but to the centre, not the invert."""
    return z_centre - stand_z


def hanger_offset(z_centre, level_z):
    u"""A circular hanger's offset from its level: its reference goes on the
    service centreline (1.14.1) - the pipe / round duct centre where it hangs,
    so it follows a sloping pipe.  (A Rectangular Hanger System hanger goes at
    the invert instead - hfam_revit, unchanged.)"""
    return z_centre - level_z


def ring_off(ring_z, z_centre):
    u"""How far (ft) the measured ring centre sits above (+) / below (-) the
    service centre - a check only: the height is never changed by it."""
    return ring_z - z_centre


def ring_tol(want_r):
    return max(RING_TOL_MM / core.MM, want_r * RING_TOL_SHARE)


def pick_ring(cands, want_r, q, along):
    u"""The ring in a placed support from its round faces and arcs.

    cands: (radius, centre (x, y, z), axis (x, y, z), kind) in model feet.
    The ring's axis is level, it passes close to the service centre q in plan,
    and its radius is nearest half the diameter set.  Returns a dict - z (the
    ring centre's height where the axis passes q), r, kind, off (plan distance
    of the axis from q), along (|cos| between the axis and the run: 1 = the
    service runs through the ring) - or None."""
    tol = ring_tol(want_r)
    best = None
    for r, c, a, kind in cands:
        la = core.vlen(a)
        if la < 1e-9 or r <= 0:
            continue
        a = core.vscale(a, 1.0 / la)
        if abs(a[2]) > 0.25:           # a level ring only (its axis runs flat)
            continue
        if abs(r - want_r) > tol:
            continue
        d = core.vsub(q, c)
        t = core.vdot(d, a)
        foot = core.vadd(c, core.vscale(a, t))   # the point on the axis nearest q
        off = ((q[0] - foot[0]) ** 2 + (q[1] - foot[1]) ** 2) ** 0.5
        if off > want_r + tol:
            continue
        plan = (a[0], a[1], 0.0)
        lp = core.vlen(plan)
        cos = abs(core.vdot(plan, along)) / lp if lp > 1e-9 else 0.0
        key = (round(abs(r - want_r) * core.MM, 1), round(off * core.MM, 1))
        if best is None or key < best[0]:
            best = (key, {'z': foot[2], 'r': r, 'kind': kind, 'off': off, 'along': cos,
                          'centre': foot})
    return best[1] if best else None
