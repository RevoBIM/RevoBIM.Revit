# -*- coding: utf-8 -*-
"""Synthetic scanned rooms for bench_logic.py (CPython only).

Surfaces are sampled on a grid with Gaussian noise, the way a scanner sees
them: pipes and ducts only on the side facing the room, walls and slabs on
their room face. `Scene.harvest(box, spacing)` answers like the cloud does.
"""
from __future__ import division
import math
import random

import c2r_core as core


class Scene(object):
    def __init__(self, noise=2.0, seed=7):
        self.pts = []
        self.noise = noise
        self.rnd = random.Random(seed)
        self.calls = 0
        self._index = None

    def _jit(self):
        return self.rnd.gauss(0.0, self.noise)

    def add(self, p):
        self.pts.append((p[0] + self._jit(), p[1] + self._jit(), p[2] + self._jit()))
        self._index = None

    def plane(self, origin, u, v, lu, lv, spacing, skip=None):
        """Rectangle origin + a*u + b*v, a in [0, lu], b in [0, lv]."""
        u = core.v_unit(u)
        v = core.v_unit(v)
        nu = int(lu / spacing) + 1
        nv = int(lv / spacing) + 1
        for i in range(nu):
            for j in range(nv):
                a = i * spacing
                b = j * spacing
                if skip and skip(a, b):
                    continue
                self.add(core.v_add(origin, core.v_add(core.v_mul(u, a), core.v_mul(v, b))))

    def cylinder(self, start, axis, length, r, spacing, arc=(0.0, 240.0), view=None):
        """Visible arc in degrees measured from `view` (a direction square to
        the axis pointing at the scanner) - default: facing down."""
        a, s, t = core.frame_for_axis(axis)
        if view is None:
            view = core.v_mul(t, -1.0)
        view = core.v_unit(core.v_sub(view, core.v_mul(a, core.v_dot(view, a))))
        w = core.v_cross(a, view)
        na = int(length / spacing) + 1
        circ = 2 * math.pi * r * (arc[1] - arc[0]) / 360.0
        nc = max(6, int(circ / spacing) + 1)
        mid = (arc[0] + arc[1]) / 2.0
        for i in range(na):
            base = core.v_add(start, core.v_mul(a, i * spacing))
            for k in range(nc):
                ang = math.radians(arc[0] + (arc[1] - arc[0]) * k / (nc - 1) - mid)
                d = core.v_add(core.v_mul(view, math.cos(ang) * r), core.v_mul(w, math.sin(ang) * r))
                self.add(core.v_add(base, d))

    def box_run(self, start, axis, length, W, H, spacing, faces=(u'bottom', u'left', u'right')):
        """Rectangular run, centre line from start along axis; W across
        (horizontal), H up. Faces listed are the ones scanned."""
        a, s, t = core.frame_for_axis(axis)
        for f in faces:
            if f == u'bottom':
                o = core.v_add(start, core.v_add(core.v_mul(s, -W / 2), core.v_mul(t, -H / 2)))
                self.plane(o, a, s, length, W, spacing)
            elif f == u'top':
                o = core.v_add(start, core.v_add(core.v_mul(s, -W / 2), core.v_mul(t, H / 2)))
                self.plane(o, a, s, length, W, spacing)
            elif f == u'left':
                o = core.v_add(start, core.v_add(core.v_mul(s, -W / 2), core.v_mul(t, -H / 2)))
                self.plane(o, a, t, length, H, spacing)
            elif f == u'right':
                o = core.v_add(start, core.v_add(core.v_mul(s, W / 2), core.v_mul(t, -H / 2)))
                self.plane(o, a, t, length, H, spacing)

    def column(self, centre_xy, w, d, z0, z1, spacing):
        cx, cy = centre_xy
        corners = [(cx - w / 2, cy - d / 2), (cx + w / 2, cy - d / 2), (cx + w / 2, cy + d / 2), (cx - w / 2, cy + d / 2)]
        for k in range(4):
            p = corners[k]
            q = corners[(k + 1) % 4]
            L = math.hypot(q[0] - p[0], q[1] - p[1])
            self.plane((p[0], p[1], z0), (q[0] - p[0], q[1] - p[1], 0.0), (0, 0, 1), L, z1 - z0, spacing)

    # ------------------------------------------------------------------
    def _build(self):
        idx = {}
        for i, p in enumerate(self.pts):
            k = (int(p[0] // 500), int(p[1] // 500), int(p[2] // 500))
            idx.setdefault(k, []).append(i)
        self._index = idx

    def harvest(self, box, spacing):
        self.calls += 1
        if self._index is None:
            self._build()
        h = box[u'h']
        ax = box[u'ax']
        ext = [abs(ax[0][k]) * h[0] + abs(ax[1][k]) * h[1] + abs(ax[2][k]) * h[2] for k in range(3)]
        c = box[u'c']
        lo = [int((c[k] - ext[k]) // 500) for k in range(3)]
        hi = [int((c[k] + ext[k]) // 500) for k in range(3)]
        out = []
        for x in range(lo[0], hi[0] + 1):
            for y in range(lo[1], hi[1] + 1):
                for z in range(lo[2], hi[2] + 1):
                    for i in self._index.get((x, y, z), ()):
                        p = self.pts[i]
                        if core.in_box(box, p):
                            out.append(p)
        if spacing and spacing > 4.5:
            out = core.voxel(out, spacing)
        return out


def room(scene, x0=0.0, y0=0.0, lx=6000.0, ly=5000.0, h=2700.0, spacing=25.0, ceiling=True, floor=True,
         walls=(True, True, True, True)):
    """A box room seen from inside: floor at z 0, ceiling at h."""
    if floor:
        scene.plane((x0, y0, 0.0), (1, 0, 0), (0, 1, 0), lx, ly, spacing)
    if ceiling:
        scene.plane((x0, y0, h), (1, 0, 0), (0, 1, 0), lx, ly, spacing)
    if walls[0]:
        scene.plane((x0, y0, 0.0), (1, 0, 0), (0, 0, 1), lx, h, spacing)
    if walls[1]:
        scene.plane((x0, y0 + ly, 0.0), (1, 0, 0), (0, 0, 1), lx, h, spacing)
    if walls[2]:
        scene.plane((x0, y0, 0.0), (0, 1, 0), (0, 0, 1), ly, h, spacing)
    if walls[3]:
        scene.plane((x0 + lx, y0, 0.0), (0, 1, 0), (0, 0, 1), ly, h, spacing)


LEVELS = [(u'Level 0', 0.0, u'L0'), (u'Level 1', 3500.0, u'L1')]
