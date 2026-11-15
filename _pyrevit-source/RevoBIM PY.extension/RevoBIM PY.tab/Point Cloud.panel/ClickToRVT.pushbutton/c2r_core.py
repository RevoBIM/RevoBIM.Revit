# -*- coding: utf-8 -*-
"""Click to RVT Element - the pure part.

Geometry, shape fitting, recognition of what a click on a point cloud landed
on, sizing and type snapping, settings, palettes and the shrink-drawer
arithmetic. Nothing here touches .NET or Revit, so the whole of it runs under
plain CPython on the bench as well as under IronPython inside Revit.

All lengths are millimetres. Points are (x, y, z) tuples in Revit's global
(internal) coordinates converted to mm. `harvest(box, spacing_mm)` is the one
door to the cloud: it returns the points inside an oriented box.
"""
from __future__ import division
import math

MM_PER_FT = 304.8

# =====================================================================
# kinds
# =====================================================================

KINDS = [
    # key, label, group, glyph (16 x 16 stroked path)
    (u'pipe', u'Pipe', u'MEP', u'M2,6 L14,6 M2,10 L14,10 M2,6 L2,10 M14,6 L14,10'),
    (u'duct', u'Duct', u'MEP', u'M2,4 L14,4 L14,12 L2,12 Z'),
    (u'tray', u'Cable tray', u'MEP', u'M2,5 L2,11 L14,11 L14,5'),
    (u'conduit', u'Conduit', u'MEP', u'M2,8 L14,8 M2,6 L2,10 M14,6 L14,10'),
    (u'wall', u'Wall', u'Architecture', u'M3,2 L13,2 L13,14 L3,14 Z M3,6 L13,6 M3,10 L13,10'),
    (u'floor', u'Floor', u'Architecture', u'M1,11 L15,11 L15,14 L1,14 Z'),
    (u'ceiling', u'Ceiling', u'Architecture', u'M1,2 L15,2 L15,5 L1,5 Z'),
    (u'column', u'Column', u'Structure', u'M5,1 L11,1 L11,15 L5,15 Z'),
    (u'beam', u'Beam', u'Structure', u'M1,5 L15,5 L15,11 L1,11 Z M1,8 L15,8'),
]
KIND_KEYS = [k[0] for k in KINDS]
KIND_LABEL = dict((k[0], k[1]) for k in KINDS)
GROUP_ACCENT = {u'MEP': u'Blue', u'Architecture': u'Orange', u'Structure': u'GreenGlyph'}


class RecogniseError(Exception):
    """Raised with a message the status line can show as it is."""
    pass


# =====================================================================
# vectors
# =====================================================================

def v_add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def v_sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def v_mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def v_dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def v_cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def v_len(a):
    return math.sqrt(v_dot(a, a))


def v_unit(a):
    n = v_len(a)
    if n < 1e-12:
        return (0.0, 0.0, 0.0)
    return (a[0] / n, a[1] / n, a[2] / n)


def v_dist(a, b):
    return v_len(v_sub(a, b))


Z_UP = (0.0, 0.0, 1.0)


# =====================================================================
# linear algebra
# =====================================================================

def eig_sym3(m):
    """Eigen decomposition of a symmetric 3x3 (cyclic Jacobi).
    Returns (values, vectors) sorted by value, largest first."""
    a = [[float(m[r][c]) for c in range(3)] for r in range(3)]
    v = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    for _sweep in range(60):
        off = abs(a[0][1]) + abs(a[0][2]) + abs(a[1][2])
        scale = abs(a[0][0]) + abs(a[1][1]) + abs(a[2][2]) + 1e-300
        if off <= 1e-14 * scale:
            break
        for p, q in ((0, 1), (0, 2), (1, 2)):
            apq = a[p][q]
            if abs(apq) < 1e-300:
                continue
            theta = (a[q][q] - a[p][p]) / (2.0 * apq)
            sign = 1.0 if theta >= 0 else -1.0
            t = sign / (abs(theta) + math.sqrt(theta * theta + 1.0))
            c = 1.0 / math.sqrt(t * t + 1.0)
            s = t * c
            for k in range(3):
                akp = a[k][p]
                akq = a[k][q]
                a[k][p] = c * akp - s * akq
                a[k][q] = s * akp + c * akq
            for k in range(3):
                apk = a[p][k]
                aqk = a[q][k]
                a[p][k] = c * apk - s * aqk
                a[q][k] = s * apk + c * aqk
            for k in range(3):
                vkp = v[k][p]
                vkq = v[k][q]
                v[k][p] = c * vkp - s * vkq
                v[k][q] = s * vkp + c * vkq
    vals = [a[i][i] for i in range(3)]
    vecs = [(v[0][i], v[1][i], v[2][i]) for i in range(3)]
    order = sorted(range(3), key=lambda i: -vals[i])
    return [vals[i] for i in order], [v_unit(vecs[i]) for i in order]


def solve3(A, b):
    """Gaussian elimination with partial pivoting; None when singular."""
    m = [[float(A[r][0]), float(A[r][1]), float(A[r][2]), float(b[r])] for r in range(3)]
    for col in range(3):
        piv = max(range(col, 3), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-14:
            return None
        m[col], m[piv] = m[piv], m[col]
        for r in range(3):
            if r != col:
                f = m[r][col] / m[col][col]
                for c in range(col, 4):
                    m[r][c] -= f * m[col][c]
    return [m[r][3] / m[r][r] for r in range(3)]


def mean3(pts):
    n = float(len(pts))
    sx = sy = sz = 0.0
    for p in pts:
        sx += p[0]
        sy += p[1]
        sz += p[2]
    return (sx / n, sy / n, sz / n)


def pca(pts):
    """(mean, values, vectors) of a point set, largest variance first."""
    m = mean3(pts)
    xx = xy = xz = yy = yz = zz = 0.0
    for p in pts:
        dx = p[0] - m[0]
        dy = p[1] - m[1]
        dz = p[2] - m[2]
        xx += dx * dx
        xy += dx * dy
        xz += dx * dz
        yy += dy * dy
        yz += dy * dz
        zz += dz * dz
    n = float(len(pts))
    vals, vecs = eig_sym3([[xx / n, xy / n, xz / n], [xy / n, yy / n, yz / n], [xz / n, yz / n, zz / n]])
    return m, vals, vecs


def percentile(values, q):
    """q in 0..1 on an unsorted list."""
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    x = q * (len(s) - 1)
    i = int(math.floor(x))
    if i >= len(s) - 1:
        return s[-1]
    f = x - i
    return s[i] * (1.0 - f) + s[i + 1] * f


# =====================================================================
# oriented boxes
# =====================================================================

def make_box(centre, axes, half):
    return {u'c': tuple(centre), u'ax': [v_unit(a) for a in axes], u'h': tuple(half)}


def aabb(centre, half):
    return make_box(centre, [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)], half)


def to_local(box, p):
    d = v_sub(p, box[u'c'])
    ax = box[u'ax']
    return (v_dot(d, ax[0]), v_dot(d, ax[1]), v_dot(d, ax[2]))


def in_box(box, p, pad=0.0):
    loc = to_local(box, p)
    h = box[u'h']
    return abs(loc[0]) <= h[0] + pad and abs(loc[1]) <= h[1] + pad and abs(loc[2]) <= h[2] + pad


def box_planes(box):
    """Six (normal, origin) pairs with normals pointing into the box."""
    out = []
    for k in range(3):
        a = box[u'ax'][k]
        h = box[u'h'][k]
        out.append((a, v_sub(box[u'c'], v_mul(a, h))))
        out.append((v_mul(a, -1.0), v_add(box[u'c'], v_mul(a, h))))
    return out


def flip_planes(planes):
    return [(v_mul(n, -1.0), o) for n, o in planes]


def frame_for_axis(a, hint=None):
    """Right-handed (a, s, t). For a run that is not vertical s is horizontal
    and t points up; for a vertical one s follows the hint (a face normal)."""
    a = v_unit(a)
    if abs(a[2]) < 0.9:
        s = v_unit(v_cross(Z_UP, a))
        t = v_cross(a, s)
        return a, s, t
    h = hint if hint is not None else (1.0, 0.0, 0.0)
    h = v_sub(h, v_mul(a, v_dot(h, a)))
    if v_len(h) < 0.3:
        h = v_cross(a, (0.0, 1.0, 0.0))
    s = v_unit(h)
    t = v_cross(a, s)
    return a, s, t


# =====================================================================
# point sets
# =====================================================================

def voxel(pts, cell):
    """One point per cell, first come first kept."""
    inv = 1.0 / cell
    seen = set()
    out = []
    fl = math.floor
    for p in pts:
        k = (int(fl(p[0] * inv)), int(fl(p[1] * inv)), int(fl(p[2] * inv)))
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out


class Grid(object):
    """Spatial hash for radius searches."""

    def __init__(self, pts, cell):
        self.pts = pts
        self.cell = float(cell)
        self.inv = 1.0 / self.cell
        self.cells = {}
        for i in range(len(pts)):
            self.cells.setdefault(self.key(pts[i]), []).append(i)

    def key(self, p):
        inv = self.inv
        return (int(math.floor(p[0] * inv)), int(math.floor(p[1] * inv)), int(math.floor(p[2] * inv)))

    def near(self, p, r):
        rr = r * r
        n = int(math.ceil(r * self.inv))
        kx, ky, kz = self.key(p)
        pts = self.pts
        cells = self.cells
        out = []
        for dx in range(-n, n + 1):
            for dy in range(-n, n + 1):
                for dz in range(-n, n + 1):
                    lst = cells.get((kx + dx, ky + dy, kz + dz))
                    if not lst:
                        continue
                    for i in lst:
                        q = pts[i]
                        ex = q[0] - p[0]
                        ey = q[1] - p[1]
                        ez = q[2] - p[2]
                        if ex * ex + ey * ey + ez * ez <= rr:
                            out.append(i)
        return out

    def nearest(self, p, r):
        best = None
        bd = None
        for i in self.near(p, r):
            d = v_dist(self.pts[i], p)
            if bd is None or d < bd:
                bd = d
                best = i
        return best


def connected(grid, members, seed, gap):
    """Indices in `members` reachable from seed in hops no longer than gap."""
    if seed is None or seed not in members:
        return set()
    out = set([seed])
    stack = [seed]
    pts = grid.pts
    while stack:
        i = stack.pop()
        for j in grid.near(pts[i], gap):
            if j in members and j not in out:
                out.add(j)
                stack.append(j)
    return out


def normal_at(grid, p, r):
    idx = grid.near(p, r)
    if len(idx) < 6:
        return None
    _m, _vals, vecs = pca([grid.pts[i] for i in idx])
    return vecs[2]


# =====================================================================
# 2D fits
# =====================================================================

def circle_kasa(pts2):
    n = len(pts2)
    if n < 3:
        return None
    mx = sum(p[0] for p in pts2) / n
    my = sum(p[1] for p in pts2) / n
    suu = suv = svv = su = sv = 0.0
    b0 = b1 = b2 = 0.0
    for p in pts2:
        u = p[0] - mx
        v = p[1] - my
        w = u * u + v * v
        suu += u * u
        suv += u * v
        svv += v * v
        su += u
        sv += v
        b0 -= u * w
        b1 -= v * w
        b2 -= w
    sol = solve3([[suu, suv, su], [suv, svv, sv], [su, sv, float(n)]], [b0, b1, b2])
    if sol is None:
        return None
    cx = -sol[0] / 2.0
    cy = -sol[1] / 2.0
    r2 = cx * cx + cy * cy - sol[2]
    if r2 <= 0:
        return None
    return (cx + mx, cy + my, math.sqrt(r2))


def circle_geometric(pts2, init, iters=10):
    """Gauss-Newton on the true distance, from a Kasa start."""
    cx, cy, r = init
    for _k in range(iters):
        jtj = [[0.0] * 3 for _i in range(3)]
        jtr = [0.0, 0.0, 0.0]
        for p in pts2:
            dx = p[0] - cx
            dy = p[1] - cy
            d = math.sqrt(dx * dx + dy * dy)
            if d < 1e-9:
                continue
            res = d - r
            j = (-dx / d, -dy / d, -1.0)
            for a in range(3):
                jtr[a] += j[a] * res
                for b in range(3):
                    jtj[a][b] += j[a] * j[b]
        step = solve3(jtj, [-jtr[0], -jtr[1], -jtr[2]])
        if step is None:
            break
        cx += step[0]
        cy += step[1]
        r += step[2]
        if abs(step[0]) + abs(step[1]) + abs(step[2]) < 1e-4:
            break
    return (cx, cy, abs(r))


def arc_coverage(pts2, cx, cy):
    """Degrees of arc the points cover round the centre."""
    if len(pts2) < 3:
        return 0.0
    angs = sorted(math.degrees(math.atan2(p[1] - cy, p[0] - cx)) for p in pts2)
    gap = 360.0 - (angs[-1] - angs[0])
    for i in range(1, len(angs)):
        g = angs[i] - angs[i - 1]
        if g > gap:
            gap = g
    return 360.0 - gap


def circle_fit(pts2, trims=3, keep=0.8):
    """Robust circle: Kasa start, geometric refine, trimmed rounds."""
    c = circle_kasa(pts2)
    if c is None:
        return None
    c = circle_geometric(pts2, c)
    cur = list(pts2)
    for _t in range(trims):
        if len(cur) < 12:
            break
        cx, cy, r = c
        cur.sort(key=lambda p: abs(math.sqrt((p[0] - cx) ** 2 + (p[1] - cy) ** 2) - r))
        cur = cur[:max(8, int(len(cur) * keep))]
        c = circle_geometric(cur, c)
    cx, cy, r = c
    se = 0.0
    for p in cur:
        e = math.sqrt((p[0] - cx) ** 2 + (p[1] - cy) ** 2) - r
        se += e * e
    rms = math.sqrt(se / max(1, len(cur)))
    return {u'cx': cx, u'cy': cy, u'r': r, u'rms': rms,
            u'cov': arc_coverage(cur, cx, cy), u'n': len(cur)}


def hull2(pts):
    p = sorted(set((round(a[0], 3), round(a[1], 3)) for a in pts))
    if len(p) < 3:
        return p

    def cr(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower = []
    for q in p:
        while len(lower) >= 2 and cr(lower[-2], lower[-1], q) <= 0:
            lower.pop()
        lower.append(q)
    upper = []
    for q in reversed(p):
        while len(upper) >= 2 and cr(upper[-2], upper[-1], q) <= 0:
            upper.pop()
        upper.append(q)
    return lower[:-1] + upper[:-1]


def min_area_rect(pts2, trim=0.01):
    """Orientation from the hull (rotating calipers), extents from trimmed
    percentiles so stray points do not inflate it.
    Returns dict cx, cy, w (along angle), h, angle (radians)."""
    h = hull2(pts2)
    best_ang = 0.0
    if len(h) >= 3:
        best = None
        for i in range(len(h)):
            p = h[i]
            q = h[(i + 1) % len(h)]
            ang = math.atan2(q[1] - p[1], q[0] - p[0])
            c = math.cos(ang)
            s = math.sin(ang)
            us = [x * c + y * s for x, y in h]
            vs = [-x * s + y * c for x, y in h]
            area = (max(us) - min(us)) * (max(vs) - min(vs))
            if best is None or area < best:
                best = area
                best_ang = ang
    # fold into -45..45 degrees so "width" is the side nearest the x axis
    while best_ang > math.pi / 4:
        best_ang -= math.pi / 2
    while best_ang <= -math.pi / 4:
        best_ang += math.pi / 2
    c = math.cos(best_ang)
    s = math.sin(best_ang)
    us = [x * c + y * s for x, y in pts2]
    vs = [-x * s + y * c for x, y in pts2]
    u0 = percentile(us, trim)
    u1 = percentile(us, 1.0 - trim)
    w0 = percentile(vs, trim)
    w1 = percentile(vs, 1.0 - trim)
    cu = (u0 + u1) / 2.0
    cv = (w0 + w1) / 2.0
    return {u'cx': cu * c - cv * s, u'cy': cu * s + cv * c,
            u'w': u1 - u0, u'h': w1 - w0, u'angle': best_ang}


def rect_rms(pts2, cx, cy, w, h, angle):
    """RMS distance from each point to the nearest edge of a rectangle."""
    if not pts2:
        return 0.0
    c = math.cos(angle)
    s = math.sin(angle)
    se = 0.0
    for x, y in pts2:
        dx = x - cx
        dy = y - cy
        u = abs(dx * c + dy * s)
        v = abs(-dx * s + dy * c)
        e = min(abs(u - w / 2.0), abs(v - h / 2.0))
        if u > w / 2.0 and v > h / 2.0:
            e = math.sqrt((u - w / 2.0) ** 2 + (v - h / 2.0) ** 2)
        se += e * e
    return math.sqrt(se / len(pts2))


# =====================================================================
# 2D occupancy grids
# =====================================================================

def flood2(cells, seed, reach=1):
    """Cells reachable from seed stepping up to `reach` cells (Chebyshev)."""
    if seed not in cells:
        return set()
    out = set([seed])
    stack = [seed]
    rng = range(-reach, reach + 1)
    while stack:
        i, j = stack.pop()
        for di in rng:
            for dj in rng:
                k = (i + di, j + dj)
                if k in cells and k not in out:
                    out.add(k)
                    stack.append(k)
    return out


def flood4(cells, seed):
    if seed not in cells:
        return set()
    out = set([seed])
    stack = [seed]
    while stack:
        i, j = stack.pop()
        for k in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
            if k in cells and k not in out:
                out.add(k)
                stack.append(k)
    return out


def dilate(cells, n):
    out = set(cells)
    for i, j in cells:
        for di in range(-n, n + 1):
            for dj in range(-n, n + 1):
                out.add((i + di, j + dj))
    return out


def erode(cells, n):
    out = set()
    for i, j in cells:
        ok = True
        for di in range(-n, n + 1):
            for dj in range(-n, n + 1):
                if (i + di, j + dj) not in cells:
                    ok = False
                    break
            if not ok:
                break
        if ok:
            out.add((i, j))
    return out


def nearest_cell(cells, target, reach):
    best = None
    bd = None
    ti, tj = target
    for di in range(-reach, reach + 1):
        for dj in range(-reach, reach + 1):
            k = (ti + di, tj + dj)
            if k in cells:
                d = di * di + dj * dj
                if bd is None or d < bd:
                    bd = d
                    best = k
    return best


def fill_holes(cells):
    if not cells:
        return set()
    i0 = min(c[0] for c in cells) - 1
    i1 = max(c[0] for c in cells) + 1
    j0 = min(c[1] for c in cells) - 1
    j1 = max(c[1] for c in cells) + 1
    outside = set([(i0, j0)])
    stack = [(i0, j0)]
    while stack:
        i, j = stack.pop()
        for k in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
            if i0 <= k[0] <= i1 and j0 <= k[1] <= j1 and k not in cells and k not in outside:
                outside.add(k)
                stack.append(k)
    out = set(cells)
    for i in range(i0, i1 + 1):
        for j in range(j0, j1 + 1):
            if (i, j) not in outside:
                out.add((i, j))
    return out


def remove_pinches(cells):
    """Fill one cell wherever two filled cells only touch at a corner, so the
    outline is a simple loop Revit will accept as a sketch."""
    cells = set(cells)
    for _round in range(50):
        changed = False
        verts = set()
        for i, j in cells:
            for a in (0, 1):
                for b in (0, 1):
                    verts.add((i + a, j + b))
        for vi, vj in verts:
            a = (vi - 1, vj - 1) in cells
            b = (vi, vj - 1) in cells
            c = (vi - 1, vj) in cells
            d = (vi, vj) in cells
            if a and d and not b and not c:
                cells.add((vi, vj - 1))
                changed = True
            elif b and c and not a and not d:
                cells.add((vi - 1, vj - 1))
                changed = True
        if not changed:
            break
    return cells


def grid_outline(cells):
    """Outer boundary of a hole-free, pinch-free cell set as a list of grid
    vertices, counter-clockwise, collinear points removed."""
    nxt = {}
    for i, j in cells:
        if (i, j - 1) not in cells:
            nxt[(i, j)] = (i + 1, j)
        if (i + 1, j) not in cells:
            nxt[(i + 1, j)] = (i + 1, j + 1)
        if (i, j + 1) not in cells:
            nxt[(i + 1, j + 1)] = (i, j + 1)
        if (i - 1, j) not in cells:
            nxt[(i, j + 1)] = (i, j)
    if not nxt:
        return []
    start = min(nxt.keys())
    loop = [start]
    cur = nxt[start]
    guard = 0
    while cur != start and guard < 100000:
        loop.append(cur)
        cur = nxt.get(cur)
        if cur is None:
            return []
        guard += 1
    out = []
    n = len(loop)
    for k in range(n):
        p = loop[k - 1]
        q = loop[k]
        r = loop[(k + 1) % n]
        if (q[0] - p[0]) * (r[1] - q[1]) - (q[1] - p[1]) * (r[0] - q[0]) != 0:
            out.append(q)
    return out


def inset_orthogonal(poly, d):
    """Move every edge of a counter-clockwise right-angled polygon inward by d."""
    n = len(poly)
    out = []
    for k in range(n):
        p = poly[k - 1]
        q = poly[k]
        r = poly[(k + 1) % n]
        d1 = v_unit((q[0] - p[0], q[1] - p[1], 0.0))
        d2 = v_unit((r[0] - q[0], r[1] - q[1], 0.0))
        out.append((q[0] + d * (-d1[1] - d2[1]), q[1] + d * (d1[0] + d2[0])))
    return out


def polygon_area(poly):
    a = 0.0
    for k in range(len(poly)):
        x0, y0 = poly[k - 1]
        x1, y1 = poly[k]
        a += x0 * y1 - x1 * y0
    return a / 2.0


# =====================================================================
# levels
# =====================================================================

def level_below(levels, z, tol=1.0):
    """levels: list of (name, elevation_mm, id). Highest at or below z."""
    if not levels:
        return None
    s = sorted(levels, key=lambda l: l[1])
    best = s[0]
    for l in s:
        if l[1] <= z + tol:
            best = l
    return best


def level_above(levels, z, tol=1.0):
    s = sorted(levels, key=lambda l: l[1])
    for l in s:
        if l[1] > z + tol:
            return l
    return None


# =====================================================================
# recognition: local hypotheses
# =====================================================================

def local_spacing(g, sample=60):
    """Median distance to the nearest neighbour - how dense the scan is here."""
    n = len(g.pts)
    if n < 3:
        return 5.0
    step = max(1, n // sample)
    ds = []
    for k in range(0, n, step):
        p = g.pts[k]
        best = None
        for i in g.near(p, 60.0):
            if i == k:
                continue
            d = v_dist(g.pts[i], p)
            if d > 1e-6 and (best is None or d < best):
                best = d
        if best is not None:
            ds.append(best)
    return max(2.0, percentile(ds, 0.5)) if ds else 20.0


def _plane_hyp(g, click, tol, sp=5.0):
    near = g.near(click, max(60.0, 4.0 * sp))
    if len(near) < 10:
        return None
    m, _vals, vecs = pca([g.pts[i] for i in near])
    n = vecs[2]
    comp = set()
    for _round in range(2):
        members = set()
        lim = tol * (1.5 if _round == 0 else 1.0)
        for i in range(len(g.pts)):
            if abs(v_dot(v_sub(g.pts[i], m), n)) < lim:
                members.add(i)
        seed = None
        bd = None
        for i in g.near(click, max(40.0, 3.0 * sp)):
            if i in members:
                d = v_dist(g.pts[i], click)
                if bd is None or d < bd:
                    bd = d
                    seed = i
        comp = connected(g, members, seed, max(22.0, 2.5 * sp))
        if len(comp) < 10:
            return None
        m, vals, vecs = pca([g.pts[i] for i in comp])
        n = vecs[2]
    return {u'kind': u'plane', u'n': n, u'c': m, u'idx': comp,
            u'rms': math.sqrt(max(vals[2], 0.0)), u'count': len(comp)}


def _cyl_from_axis(g, click, a, pts_near, tol, sp=5.0):
    a, s, t = frame_for_axis(a)
    p2 = [(v_dot(v_sub(p, click), s), v_dot(v_sub(p, click), t)) for p in pts_near]
    fit = circle_fit(p2)
    if fit is None or not (3.0 <= fit[u'r'] <= 800.0):
        return None
    C = v_add(click, v_add(v_mul(s, fit[u'cx']), v_mul(t, fit[u'cy'])))
    r = fit[u'r']
    for _round in range(2):
        tolc = max(tol, 0.1 * r)
        members = set()
        for i in range(len(g.pts)):
            d = v_sub(g.pts[i], C)
            radial = v_sub(d, v_mul(a, v_dot(d, a)))
            if abs(v_len(radial) - r) < tolc:
                members.add(i)
        seed = None
        bd = None
        for i in g.near(click, max(40.0, tolc * 3, 3.0 * sp)):
            if i in members:
                dd = v_dist(g.pts[i], click)
                if bd is None or dd < bd:
                    bd = dd
                    seed = i
        comp = connected(g, members, seed, max(22.0, 2.5 * sp))
        if len(comp) < 20:
            return None
        cp = [g.pts[i] for i in comp]
        along = [v_dot(v_sub(p, C), a) for p in cp]
        if max(along) - min(along) > max(150.0, 3.0 * r):
            _m, _v, vecs = pca(cp)
            if abs(v_dot(vecs[0], a)) > 0.8:
                a = vecs[0]
        a, s, t = frame_for_axis(a)
        p2 = [(v_dot(v_sub(p, C), s), v_dot(v_sub(p, C), t)) for p in cp]
        fit = circle_fit(p2)
        if fit is None or not (3.0 <= fit[u'r'] <= 800.0):
            return None
        C = v_add(C, v_add(v_mul(s, fit[u'cx']), v_mul(t, fit[u'cy'])))
        r = fit[u'r']
    return {u'kind': u'cyl', u'a': a, u'C': C, u'r': r, u'idx': comp, u'rms': fit[u'rms'],
            u'cov': fit[u'cov'], u'count': len(comp)}


def _cyl_hyp(g, click, rn, tol, sp=5.0):
    near = g.near(click, rn)
    if len(near) < 25:
        return None
    step = max(1, len(near) // 300)
    sample = [g.pts[near[k]] for k in range(0, len(near), step)]
    normals = []
    for p in sample:
        n = normal_at(g, p, max(30.0, 3.0 * sp))
        if n is not None:
            normals.append(n)
    if len(normals) < 20:
        return None
    sxx = sxy = sxz = syy = syz = szz = 0.0
    for n in normals:
        sxx += n[0] * n[0]
        sxy += n[0] * n[1]
        sxz += n[0] * n[2]
        syy += n[1] * n[1]
        syz += n[1] * n[2]
        szz += n[2] * n[2]
    k = float(len(normals))
    vals, vecs = eig_sym3([[sxx / k, sxy / k, sxz / k], [sxy / k, syy / k, syz / k], [sxz / k, syz / k, szz / k]])
    if vals[1] < 0.03:
        return None          # normals all one way: a plane
    if vals[2] > 0.35 * vals[1]:
        return None          # normals not in one plane: not a cylinder
    return _cyl_from_axis(g, click, vecs[2], [g.pts[i] for i in near], tol, sp)


def _thin_hyp(g, click, tol, sp=5.0):
    near = g.near(click, 80.0)
    if len(near) < 12:
        return None
    pts = [g.pts[i] for i in near]
    m, vals, vecs = pca(pts)
    if vals[0] <= 0 or vals[1] / vals[0] > 0.15:
        return None
    a = vecs[0]
    close = []
    for i in g.near(click, 160.0):
        p = g.pts[i]
        d = v_sub(p, m)
        radial = v_sub(d, v_mul(a, v_dot(d, a)))
        if v_len(radial) < 45.0:
            close.append(p)
    if len(close) < 12:
        return None
    hyp = _cyl_from_axis(g, click, a, close, tol, sp)
    if hyp is not None and hyp[u'r'] > 40.0:
        return None
    return hyp


def _cyl_ok(h, tol):
    if h is None:
        return False
    return (h[u'cov'] >= 75.0 and h[u'rms'] <= max(tol * 1.2, 0.15 * h[u'r'])
            and h[u'count'] >= 20)


def local_shape(raw, click, tol, log):
    """Decide whether the click is on a plane or a cylinder."""
    F = voxel(raw, 5.0)
    if len(F) > 14000:
        F = voxel(raw, 8.0)
    g = Grid(F, 25.0)
    sp = local_spacing(g)
    if g.nearest(click, max(60.0, 3.0 * sp)) is None:
        raise RecogniseError(u'No scanned points near the click')
    plane = _plane_hyp(g, click, tol, sp)
    cyls = [_thin_hyp(g, click, tol, sp)]
    for rn in (max(70.0, 5.0 * sp), max(170.0, 9.0 * sp)):
        cyls.append(_cyl_hyp(g, click, rn, tol, sp))
    good = [c for c in cyls if _cyl_ok(c, tol)]
    cyl = max(good, key=lambda c: c[u'count']) if good else None
    log(u'local: {0} pts at about {1:.0f} mm spacing, plane {2}, cylinder {3}'.format(
        len(F), sp, plane[u'count'] if plane else u'-',
        u'r {0:.1f} cov {1:.0f} rms {2:.1f} n {3}'.format(cyl[u'r'], cyl[u'cov'], cyl[u'rms'], cyl[u'count']) if cyl else u'-'))
    if cyl is not None and (plane is None or cyl[u'count'] > 1.3 * plane[u'count']):
        return g, cyl
    if plane is not None:
        return g, plane
    raise RecogniseError(u'Could not fit a plane or a cylinder round the click')


# =====================================================================
# recognition: tracing a straight run along its axis
# =====================================================================

def trace_run(harvest, C, frame, half_s, half_t, on_profile, s0, s1, st, log):
    """Walk the axis both ways from the fitted stretch [s0, s1] while the
    profile keeps finding points. Returns (s0, s1) along a from C."""
    a, s, t = frame
    step = float(st[u'trace_step_mm'])
    gap = float(st[u'trace_gap_mm'])
    maxlen = float(st[u'trace_max_m']) * 1000.0
    spacing = max(float(st[u'spacing_mm']), 8.0)
    binw = 50.0
    ends = [s0, s1]
    for direction in (1.0, -1.0):
        cur = ends[1] if direction > 0 else ends[0]
        while ends[1] - ends[0] < maxlen:
            mid = cur + direction * step / 2.0
            box = make_box(v_add(C, v_mul(a, mid)), (a, s, t), (step / 2.0, half_s, half_t))
            pts = harvest(box, spacing)
            hits = []
            for p in pts:
                d = v_sub(p, C)
                if on_profile(v_dot(d, s), v_dot(d, t)):
                    x = (v_dot(d, a) - cur) * direction
                    if -binw <= x <= step:
                        hits.append(x)
            if not hits:
                break
            bins = set(int(max(0.0, x) // binw) for x in hits)
            nb = int(step // binw)
            last = -1
            misses = 0
            for k in range(nb):
                if k in bins:
                    last = k
                    misses = 0
                else:
                    misses += 1
                    if misses * binw > gap:
                        break
            if last < 0:
                break
            reach = max(x for x in hits if int(max(0.0, x) // binw) <= last)
            reach = min(reach, step)
            if reach <= 1.0:
                break
            cur = cur + direction * reach
            if direction > 0:
                ends[1] = max(ends[1], cur)
            else:
                ends[0] = min(ends[0], cur)
            if reach < step - gap:
                break
    ends[0] = max(ends[0], ends[1] - maxlen)
    log(u'trace: {0:.0f} mm to {1:.0f} mm along the axis'.format(ends[0], ends[1]))
    return ends[0], ends[1]


def _snap_axis(a, deg):
    """Square a nearly level run to level and a nearly plumb one to plumb."""
    a = v_unit(a)
    lim = math.sin(math.radians(deg))
    if abs(a[2]) > math.cos(math.radians(deg)):
        return (0.0, 0.0, 1.0)
    if abs(a[2]) < lim:
        a = v_unit((a[0], a[1], 0.0))
    # a consistent direction: +x first, then +y, then up
    if a[2] < -1e-6 or (abs(a[2]) <= 1e-6 and (a[0] < -1e-6 or (abs(a[0]) <= 1e-6 and a[1] < 0))):
        a = v_mul(a, -1.0)
    return a


# =====================================================================
# recognition: round runs
# =====================================================================

def _round_run(harvest, g, cyl, click, st, log, trace):
    a = _snap_axis(cyl[u'a'], float(st[u'snap_axis_deg']))
    frame = frame_for_axis(a)
    a, s, t = frame
    C = cyl[u'C']
    # move C to the point on the axis level with the click
    C = v_add(C, v_mul(a, v_dot(v_sub(click, C), a)))
    r = cyl[u'r']
    tolc = max(float(st[u'noise_mm']), 0.1 * r)
    cp = [g.pts[i] for i in cyl[u'idx']]
    along = [v_dot(v_sub(p, C), a) for p in cp]
    s0 = percentile(along, 0.01)
    s1 = percentile(along, 0.99)

    def on_profile(u, v):
        return abs(math.sqrt(u * u + v * v) - r) < tolc
    if trace:
        s0, s1 = trace_run(harvest, C, frame, r + 3 * tolc + 20, r + 3 * tolc + 20, on_profile, s0, s1, st, log)
    p2 = [(v_dot(v_sub(p, C), s), v_dot(v_sub(p, C), t)) for p in cp]
    step = max(1, len(p2) // 500)
    circle = [(r * math.cos(k * math.pi / 24), r * math.sin(k * math.pi / 24)) for k in range(48)]
    rec = {u'shape': u'round', u'axis': a, u'frame': frame, u'C': C,
           u'p0': v_add(C, v_mul(a, s0)), u'p1': v_add(C, v_mul(a, s1)),
           u'D': 2.0 * r, u'vertical': abs(a[2]) > 0.99, u'rms': cyl[u'rms'],
           u'cov': cyl[u'cov'], u'npts': cyl[u'count'],
           u'preview': {u'pts': p2[::step], u'shapes': [circle], u'caption': u'Section across the run'}}
    return rec


# =====================================================================
# recognition: rectangular sections (ducts, trays, beams, columns)
# =====================================================================

def section_pass(harvest, pc, a, st, log, hint=None):
    """Cut the cloud square to the axis round the click and find the outline
    of the thing that was clicked."""
    a, s, t = frame_for_axis(a, hint)
    half_len = 250.0
    W = float(st[u'section_half_mm'])
    pts = harvest(make_box(pc, (a, s, t), (half_len, W, W)), max(float(st[u'spacing_mm']), 6.0))
    pts = voxel(pts, 8.0)
    if len(pts) < 30:
        raise RecogniseError(u'Too few points across the section ({0})'.format(len(pts)))
    g = 15.0
    cells = {}
    loc = []
    for p in pts:
        d = v_sub(p, pc)
        x = v_dot(d, a)
        u = v_dot(d, s)
        v = v_dot(d, t)
        q = min(3, max(0, int((x + half_len) / (2 * half_len) * 4)))
        k = (int(math.floor(u / g)), int(math.floor(v / g)))
        cells[k] = cells.get(k, 0) | (1 << q)
        loc.append((k, u, v))
    solid = set(k for k, m in cells.items() if bin(m).count(u'1') >= 2)
    n = int(W / g)
    rows = {}
    cols = {}
    for i, j in solid:
        rows[j] = rows.get(j, 0) + 1
        cols[i] = cols.get(i, 0) + 1
    row_lo = {}
    row_hi = {}
    col_lo = {}
    col_hi = {}
    for i, j in solid:
        row_lo[j] = min(row_lo.get(j, i), i)
        row_hi[j] = max(row_hi.get(j, i), i)
        col_lo[i] = min(col_lo.get(i, j), j)
        col_hi[i] = max(col_hi.get(i, j), j)
    # a slab or a wall crosses the whole window: wide, and reaching both edges
    plate_rows = set(j for j, c in rows.items()
                     if c >= 0.5 * 2 * n and row_lo[j] <= -n + 2 and row_hi[j] >= n - 3)
    plate_cols = set(i for i, c in cols.items()
                     if c >= 0.5 * 2 * n and col_lo[i] <= -n + 2 and col_hi[i] >= n - 3)
    usable = set(k for k in solid if k[1] not in plate_rows and k[0] not in plate_cols)
    seed = nearest_cell(usable, (0, 0), 4)
    if seed is None:
        seed = nearest_cell(usable, (-1, -1), 4)
    if seed is None:
        raise RecogniseError(u'Nothing solid at the click once walls and slabs are set aside')
    comp = flood2(usable, seed, 2)
    cp = [(u, v) for k, u, v in loc if k in comp]
    if len(cp) < 20:
        raise RecogniseError(u'The section round the click is too small to size')
    jtop = max(k[1] for k in comp)
    jbot = min(k[1] for k in comp)
    ilo = min(k[0] for k in comp)
    ihi = max(k[0] for k in comp)
    slab_above = any((jtop + d) in plate_rows for d in (1, 2, 3))
    slab_below = any((jbot - d) in plate_rows for d in (1, 2, 3))
    wall_side = any((ilo - d) in plate_cols or (ihi + d) in plate_cols for d in (1, 2, 3))
    vertical = abs(a[2]) > 0.99
    if vertical:
        rect = min_area_rect(cp)
    else:
        us = [p[0] for p in cp]
        vs = [p[1] for p in cp]
        u0 = percentile(us, 0.01)
        u1 = percentile(us, 0.99)
        w0 = percentile(vs, 0.01)
        w1 = percentile(vs, 0.99)
        rect = {u'cx': (u0 + u1) / 2, u'cy': (w0 + w1) / 2, u'w': u1 - u0, u'h': w1 - w0, u'angle': 0.0}
    rr = rect_rms(cp, rect[u'cx'], rect[u'cy'], rect[u'w'], rect[u'h'], rect[u'angle'])
    circ = circle_fit(cp)
    is_round = bool(circ and circ[u'cov'] >= 120 and circ[u'rms'] < 0.5 * rr and 10 < circ[u'r'] < 800)
    log(u'section: {0} pts, rect {1:.0f} x {2:.0f} rms {3:.1f}, circle {4}, slab above {5}, wall {6}'.format(
        len(cp), rect[u'w'], rect[u'h'], rr,
        u'r {0:.0f} rms {1:.1f} cov {2:.0f}'.format(circ[u'r'], circ[u'rms'], circ[u'cov']) if circ else u'-',
        slab_above, wall_side))
    return {u'frame': (a, s, t), u'rect': rect, u'rms': rr, u'pts2': cp, u'npts': len(cp),
            u'slab_above': slab_above, u'slab_below': slab_below, u'wall_side': wall_side,
            u'round': is_round, u'circle': circ}


def _rect_poly(cx, cy, w, h, ang):
    c = math.cos(ang)
    s = math.sin(ang)
    out = []
    for du, dv in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)):
        out.append((cx + du * c - dv * s, cy + du * s + dv * c))
    return out


def _rect_run(harvest, pc, a, st, log, trace, hint=None):
    a = _snap_axis(a, float(st[u'snap_axis_deg']))
    sec = section_pass(harvest, pc, a, st, log, hint)
    a, s, t = sec[u'frame']
    if sec[u'round']:
        circ = sec[u'circle']
        cyl = {u'a': a, u'C': v_add(pc, v_add(v_mul(s, circ[u'cx']), v_mul(t, circ[u'cy']))),
               u'r': circ[u'r'], u'rms': circ[u'rms'], u'cov': circ[u'cov'], u'count': sec[u'npts'], u'idx': []}
        return _round_from_section(harvest, cyl, pc, st, log, trace, sec)
    rect = sec[u'rect']
    C = v_add(pc, v_add(v_mul(s, rect[u'cx']), v_mul(t, rect[u'cy'])))
    W = rect[u'w']
    H = rect[u'h']
    ang = rect[u'angle']
    tol = float(st[u'noise_mm']) + 10.0
    ca = math.cos(ang)
    sa = math.sin(ang)

    def on_profile(u, v):
        uu = u * ca + v * sa
        vv = -u * sa + v * ca
        return abs(uu) <= W / 2 + tol and abs(vv) <= H / 2 + tol
    s0, s1 = -200.0, 200.0
    if trace:
        s0, s1 = trace_run(harvest, C, (a, s, t), max(W, H) / 2 + 80, max(W, H) / 2 + 80,
                           on_profile, s0, s1, st, log)
    poly = _rect_poly(rect[u'cx'], rect[u'cy'], W, H, ang)
    stride = max(1, len(sec[u'pts2']) // 600)
    rec = {u'shape': u'rect', u'axis': a, u'frame': (a, s, t), u'C': C,
           u'p0': v_add(C, v_mul(a, s0)), u'p1': v_add(C, v_mul(a, s1)),
           u'W': W, u'H': H, u'angle': ang, u'vertical': abs(a[2]) > 0.99,
           u'slab_above': sec[u'slab_above'], u'slab_below': sec[u'slab_below'],
           u'wall_side': sec[u'wall_side'], u'rms': sec[u'rms'], u'npts': sec[u'npts'],
           u'preview': {u'pts': sec[u'pts2'][::stride], u'shapes': [poly],
                        u'caption': u'Section across the run (walls and slabs set aside)'}}
    return rec


def _round_from_section(harvest, cyl, click, st, log, trace, sec):
    a, s, t = frame_for_axis(cyl[u'a'])
    C = cyl[u'C']
    r = cyl[u'r']
    tolc = max(float(st[u'noise_mm']), 0.1 * r)

    def on_profile(u, v):
        return abs(math.sqrt(u * u + v * v) - r) < tolc
    s0, s1 = -200.0, 200.0
    if trace:
        s0, s1 = trace_run(harvest, C, (a, s, t), r + 3 * tolc + 20, r + 3 * tolc + 20, on_profile, s0, s1, st, log)
    circ = sec[u'circle']
    p2 = [(p[0] - circ[u'cx'], p[1] - circ[u'cy']) for p in sec[u'pts2']]
    circle = [(r * math.cos(k * math.pi / 24), r * math.sin(k * math.pi / 24)) for k in range(48)]
    return {u'shape': u'round', u'axis': a, u'frame': (a, s, t), u'C': C,
            u'p0': v_add(C, v_mul(a, s0)), u'p1': v_add(C, v_mul(a, s1)),
            u'D': 2 * r, u'vertical': abs(a[2]) > 0.99, u'rms': cyl[u'rms'], u'cov': cyl[u'cov'],
            u'npts': cyl[u'count'],
            u'preview': {u'pts': p2[::max(1, len(p2) // 500)], u'shapes': [circle], u'caption': u'Section across the run'}}


# =====================================================================
# recognition: walls
# =====================================================================

def _plane_peak(ds, hs, zs, lo, hi, need):
    """Strongest 10 mm band of points between lo and hi (mm off the face)
    that spreads like a face. Returns its offset or None."""
    bins = {}
    for k in range(len(ds)):
        d = ds[k]
        if lo <= d <= hi:
            bins.setdefault(int(d // 10), []).append(k)
    best = None
    bc = 0
    for b, ks in bins.items():
        merged = ks + bins.get(b + 1, [])
        if len(merged) < max(need, bc + 1):
            continue
        hv = [hs[k] for k in merged]
        zv = [zs[k] for k in merged]
        if max(hv) - min(hv) < 200 or max(zv) - min(zv) < 200:
            continue
        bc = len(merged)
        best = sum(ds[k] for k in merged) / len(merged)
    return best


def wall_side_and_thickness(pts, c, n, h, face_count, widths=None):
    """Which side of the face the wall body is on (+1 along n, -1 against)
    and its thickness if the other face was scanned."""
    ds = []
    hs = []
    zs = []
    for p in pts:
        d = v_sub(p, c)
        ds.append(v_dot(d, n))
        hs.append(v_dot(d, h))
        zs.append(d[2])
    need = max(20, int(0.2 * face_count))
    front = _plane_peak(ds, hs, zs, 50.0, 650.0, need)
    back = _plane_peak([-x for x in ds], hs, zs, 50.0, 650.0, need)
    if front is not None and back is not None and widths:
        ef = min(abs(front - w) for w in widths)
        eb = min(abs(back - w) for w in widths)
        if ef <= eb:
            back = None
        else:
            front = None
    if front is not None and back is None:
        return 1.0, front
    if back is not None and front is None:
        return -1.0, back
    nf = len([x for x in ds if 40.0 <= x <= 650.0])
    nb = len([x for x in ds if -650.0 <= x <= -40.0])
    return (1.0 if nf < nb else -1.0), None


def _wall_pass(harvest, plane, click, levels, st, log, widths):
    n = v_unit((plane[u'n'][0], plane[u'n'][1], 0.0))
    c = plane[u'c']
    c = v_add(click, v_mul(n, v_dot(v_sub(c, click), n)))  # on the face, level with the click
    h = v_unit(v_cross(Z_UP, n))
    half = float(st[u'wall_search_m']) * 500.0
    tol = float(st[u'noise_mm'])
    zlo = click[2] - 4500.0
    zhi = click[2] + 4500.0
    centre = (c[0], c[1], (zlo + zhi) / 2.0)
    pts = harvest(make_box(centre, (h, n, Z_UP), (half, max(40.0, 3 * tol), (zhi - zlo) / 2.0)), 40.0)
    if len(pts) < 50:
        raise RecogniseError(u'Too few points on the wall face ({0})'.format(len(pts)))
    cell = 100.0
    cells = {}
    for p in pts:
        d = v_sub(p, c)
        u = v_dot(d, h)
        k = (int(math.floor(u / cell)), int(math.floor(p[2] / cell)))
        cells.setdefault(k, []).append((u, p[2]))
    seed = nearest_cell(cells, (0, int(math.floor(click[2] / cell))), 3)
    if seed is None:
        raise RecogniseError(u'The wall face could not be followed from the click')
    comp = flood2(set(cells.keys()), seed, 2)
    us = []
    zs = []
    for k in comp:
        for u, z in cells[k]:
            us.append(u)
            zs.append(z)
    u0 = percentile(us, 0.002)
    u1 = percentile(us, 0.998)
    z0 = percentile(zs, 0.002)
    z1 = percentile(zs, 0.998)
    log(u'wall face: {0:.0f} mm long, z {1:.0f} to {2:.0f}, {3} cells'.format(u1 - u0, z0, z1, len(comp)))
    lvl = level_below(levels, z0 + 300.0)
    near_floor = lvl is not None and z0 - lvl[1] < 400.0
    if z1 - z0 < 1000.0 and not near_floor:
        return None         # a face that short is the side of a run, not a wall
    local = harvest(make_box(c, (h, n, Z_UP), (300.0, 700.0, 400.0)), max(float(st[u'spacing_mm']), 8.0))
    face_count = len([p for p in local if abs(v_dot(v_sub(p, c), n)) < 2 * tol + 4])
    side, thick = wall_side_and_thickness(local, c, n, h, face_count, widths)
    body = v_mul(n, side)
    log(u'wall body side {0}, thickness {1}'.format(u'+n' if side > 0 else u'-n',
                                                    u'{0:.0f} mm'.format(thick) if thick else u'not scanned'))
    a = v_add(c, v_mul(h, u0))
    b = v_add(c, v_mul(h, u1))
    stride = max(1, len(us) // 700)
    pts2 = [(us[k], zs[k] - z0) for k in range(0, len(us), stride)]
    return {u'shape': u'wall', u'face_a': (a[0], a[1], z0), u'face_b': (b[0], b[1], z0),
            u'body': body, u'thickness': thick, u'base_z': z0, u'top_z': z1,
            u'length': u1 - u0, u'npts': len(us), u'rms': plane[u'rms'],
            u'preview': {u'pts': pts2, u'shapes': [[(u0, 0.0), (u1, 0.0), (u1, z1 - z0), (u0, z1 - z0)]],
                         u'caption': u'Wall face seen square on'}}


# =====================================================================
# recognition: floors and ceilings
# =====================================================================

def flat_points(pts, cell, band):
    """Keep the points of cells that lie flat. A wall cutting through the
    thin slab band spreads its points over the whole band height; a floor
    or ceiling keeps them within the scan noise."""
    zs = {}
    for p in pts:
        k = (int(math.floor(p[0] / cell)), int(math.floor(p[1] / cell)))
        zs.setdefault(k, []).append(p[2])
    good = set()
    lim = 0.45 * band
    for k, v in zs.items():
        if len(v) < 2:
            continue
        m = sum(v) / len(v)
        sd = math.sqrt(sum((z - m) ** 2 for z in v) / len(v))
        if sd < lim:
            good.add(k)
    return [p for p in pts if (int(math.floor(p[0] / cell)), int(math.floor(p[1] / cell))) in good]


def _slab_pass(harvest, plane, click, raw, levels, st, log):
    z0 = plane[u'c'][2]
    half = float(st[u'floor_search_m']) * 500.0
    tol = float(st[u'noise_mm'])
    band = max(30.0, 2.5 * tol)
    pts = harvest(aabb((click[0], click[1], z0), (half, half, band)), 60.0)
    if len(pts) < 50:
        raise RecogniseError(u'Too few points on the slab ({0})'.format(len(pts)))
    cell = float(st[u'slab_cell_mm'])
    pts = flat_points(pts, cell, band)

    def build(ang):
        ca = math.cos(ang)
        sa = math.sin(ang)
        cells = set()
        for p in pts:
            x = p[0] - click[0]
            y = p[1] - click[1]
            u = x * ca + y * sa
            v = -x * sa + y * ca
            cells.add((int(math.floor(u / cell)), int(math.floor(v / cell))))
        cells = erode(dilate(cells, 1), 1)
        seed = nearest_cell(cells, (0, 0), 3)
        if seed is None:
            return set()
        return flood4(cells, seed)
    comp = build(0.0)
    if not comp:
        raise RecogniseError(u'The slab could not be followed from the click')
    rect = min_area_rect([((i + 0.5) * cell, (j + 0.5) * cell) for i, j in comp])
    ang = rect[u'angle']
    short = min(rect[u'w'], rect[u'h'])
    if short < 1300.0 and max(rect[u'w'], rect[u'h']) > 2.0 * short:
        log(u'slab: only {0:.0f} mm wide - the underside of a run, not a slab'.format(short))
        ux = math.cos(ang) if rect[u'w'] >= rect[u'h'] else -math.sin(ang)
        uy = math.sin(ang) if rect[u'w'] >= rect[u'h'] else math.cos(ang)
        return {u'shape': u'strip', u'axis': (ux, uy, 0.0)}
    comp = build(ang)
    comp = remove_pinches(fill_holes(comp))
    outline = grid_outline(comp)
    ca = math.cos(ang)
    sa = math.sin(ang)

    def world(i, j):
        u = i * cell
        v = j * cell
        return (click[0] + u * ca - v * sa, click[1] + u * sa + v * ca)
    half_cell = 0.5 * cell / cell
    loop = [world(i, j) for i, j in inset_orthogonal(outline, half_cell)]
    i0 = min(c[0] for c in comp) + 0.5
    i1 = max(c[0] for c in comp) + 0.5
    j0 = min(c[1] for c in comp) + 0.5
    j1 = max(c[1] for c in comp) + 0.5
    rect_loop = [world(i0, j0), world(i1, j0), world(i1, j1), world(i0, j1)]
    above = len([p for p in raw if 60.0 < p[2] - z0 < 600.0])
    below = len([p for p in raw if 60.0 < z0 - p[2] < 600.0])
    lvl = level_below(levels, z0 + 50.0)
    near_level = lvl is not None and abs(z0 - lvl[1]) < 600.0
    if above > 1.5 * below + 20:
        which = u'floor'
    elif below > 1.5 * above + 20:
        which = u'ceiling'
    else:
        which = u'floor' if near_level else u'ceiling'
    area = abs(polygon_area(loop)) / 1e6 if loop else 0.0
    log(u'slab: {0} at z {1:.0f}, {2} cells, {3} corners, {4:.1f} m2 (above {5}, below {6})'.format(
        which, z0, len(comp), len(loop), area, above, below))
    loc = [(i * cell, j * cell) for i, j in inset_orthogonal(outline, 0.5)]
    return {u'shape': u'slab', u'which': which, u'z': z0, u'loop': loop, u'rect_loop': rect_loop,
            u'area_m2': area, u'npts': len(pts), u'rms': plane[u'rms'],
            u'preview': {u'pts': [((i + 0.5) * cell, (j + 0.5) * cell) for i, j in list(comp)[:900]],
                         u'shapes': [loc], u'caption': u'Slab outline in plan'}}


# =====================================================================
# recognition: the whole thing
# =====================================================================

def recognise(click, harvest, levels, st, widths=None, trace=True, log=None):
    """What did the click land on, how big is it and where does it run?
    `widths` are the project's wall type widths, used to settle a wall's
    thickness when both its faces were scanned."""
    L = log or (lambda m: None)
    tol = max(3.0, float(st[u'noise_mm']))
    B = float(st[u'click_box_mm'])
    raw = harvest(aabb(click, (B, B, B)), float(st[u'spacing_mm']))
    L(u'harvest round the click: {0} pts'.format(len(raw)))
    if len(raw) < 30:
        raise RecogniseError(u'Only {0} scanned points round the click'.format(len(raw)))
    g, hyp = local_shape(raw, click, tol, L)
    if hyp[u'kind'] == u'cyl':
        return _round_run(harvest, g, hyp, click, st, L, trace)
    n = hyp[u'n']
    nz = abs(n[2])
    pts = [g.pts[i] for i in hyp[u'idx']]
    if nz > 0.9:
        m, _vals, vecs = pca(pts)
        u1 = v_unit((vecs[0][0], vecs[0][1], 0.0))
        u2 = v_unit(v_cross(Z_UP, u1))
        e1 = [v_dot(v_sub(p, m), u1) for p in pts]
        e2 = [v_dot(v_sub(p, m), u2) for p in pts]
        open1 = _reaches(e1, m, u1, click, B)
        open2 = _reaches(e2, m, u2, click, B)
        L(u'horizontal face: open along u1 {0}, u2 {1}'.format(open1, open2))
        if open1 and open2:
            slab = _slab_pass(harvest, hyp, click, raw, levels, st, L)
            if slab[u'shape'] == u'strip':
                return _rect_run(harvest, click, slab[u'axis'], st, L, trace)
            return slab
        if open1 or open2:
            axis = u1 if open1 else u2
            return _rect_run(harvest, click, axis, st, L, trace)
        raise RecogniseError(u'A small flat patch ({0:.0f} x {1:.0f} mm), not a run, wall or slab'.format(
            max(e1) - min(e1), max(e2) - min(e2)))
    if nz < 0.3:
        nh = v_unit((n[0], n[1], 0.0))
        h = v_unit(v_cross(Z_UP, nh))
        m = mean3(pts)
        eh = [v_dot(v_sub(p, m), h) for p in pts]
        ez = [p[2] - m[2] for p in pts]
        openh = _reaches(eh, m, h, click, B)
        openz = _reaches(ez, m, Z_UP, click, B)
        L(u'vertical face: open along h {0}, z {1}'.format(openh, openz))
        if openh and openz:
            wall = _wall_pass(harvest, hyp, click, levels, st, L, widths)
            if wall is not None:
                return wall
            return _rect_run(harvest, click, h, st, L, trace)
        if openh:
            return _rect_run(harvest, click, h, st, L, trace)
        if openz:
            return _rect_run(harvest, click, Z_UP, st, L, trace, hint=nh)
        raise RecogniseError(u'A small upright patch ({0:.0f} x {1:.0f} mm), not a run or a wall'.format(
            max(eh) - min(eh), max(ez) - min(ez)))
    raise RecogniseError(u'A sloping surface ({0:.0f} degrees) - not one this tool places'.format(
        math.degrees(math.acos(min(1.0, nz)))))


def _reaches(extents, m, direction, click, B):
    """Does the face run out to the harvest box in this direction (both ways)?"""
    if not extents:
        return False
    lo = min(extents)
    hi = max(extents)
    off = v_dot(v_sub(m, click), direction)
    reach_hi = _chord(click, direction, B)
    margin = 45.0
    return (hi + off >= reach_hi - margin) and (lo + off <= -reach_hi + margin)


def _chord(click, d, B):
    """How far from the click the box goes along d (box is a cube of half B)."""
    best = None
    for k in range(3):
        if abs(d[k]) > 1e-9:
            t = B / abs(d[k])
            if best is None or t < best:
                best = t
    return best if best is not None else B


def end_from_click(rec, click2):
    """Click-the-end mode: the run goes from the first click's station to the
    second click's, along the fitted axis (the first click sits at station 0)."""
    a = rec[u'axis']
    C = rec[u'C']
    s2 = v_dot(v_sub(click2, C), a)
    lo = min(0.0, s2)
    hi = max(0.0, s2)
    if hi - lo < 50.0:
        raise RecogniseError(u'The two clicks are less than 50 mm apart along the run')
    rec[u'p0'] = v_add(C, v_mul(a, lo))
    rec[u'p1'] = v_add(C, v_mul(a, hi))
    return rec


# =====================================================================
# sizes and types
# =====================================================================

def nearest(value, sizes):
    """(size, error) of the closest entry; (None, None) if there are none."""
    best = None
    be = None
    for s in sizes:
        e = abs(s - value)
        if be is None or e < be:
            be = e
            best = s
    return best, be


def round_to(value, step, minimum=None):
    v = round(value / step) * step
    if minimum is not None and v < minimum:
        v = minimum
    return v


def _types_for(cat, kind, opts):
    lst = cat.get(kind) or []
    want = (opts.get(u'types') or {}).get(kind) or u''
    if want:
        chosen = [t for t in lst if t[u'name'] == want]
        if chosen:
            return chosen
    return lst


def _conf(err, size, rms, tol):
    if size <= 0:
        return u'Low'
    if err <= max(3.0, 0.05 * size) and rms <= tol * 1.5:
        return u'High'
    if err <= max(6.0, 0.15 * size):
        return u'Medium'
    return u'Low'


def candidates(rec, cat, opts, st):
    """Every way the recognised shape could be placed, best first. Each is a
    dict with kind, type, sizes and the score it was ranked on."""
    enabled = set(opts.get(u'enabled') or KIND_KEYS)
    tol = float(st[u'noise_mm'])
    out = []
    shape = rec[u'shape']
    if shape == u'round':
        D = rec[u'D']
        ins = float(opts.get(u'insulation_mm') or 0)
        Dp = max(1.0, D - 2.0 * ins)
        if u'pipe' in enabled:
            best = None
            for ty in _types_for(cat, u'pipe', opts):
                for nom, od in ty.get(u'sizes') or []:
                    e = abs(od - Dp)
                    if best is None or e < best[0]:
                        best = (e, ty, nom, od)
            if best is not None:
                e, ty, nom, od = best
                prior = 0.0 if Dp <= 170 else (Dp - 170) * 0.15
                out.append({u'kind': u'pipe', u'type': ty, u'err': e, u'score': e + prior,
                            u'size': {u'diameter': nom},
                            u'text': u'Pipe {0:.0f} mm (OD {1:.1f})'.format(nom, od),
                            u'measure': u'cloud OD {0:.0f} mm{1}'.format(D, u' less {0:.0f} insulation'.format(ins) if ins else u''),
                            u'conf': _conf(e, od, rec[u'rms'], tol)})
        if u'conduit' in enabled:
            best = None
            for ty in _types_for(cat, u'conduit', opts):
                for nom, od in ty.get(u'sizes') or []:
                    e = abs(od - D)
                    if best is None or e < best[0]:
                        best = (e, ty, nom, od)
            if best is not None and D <= float(st[u'conduit_max_mm']) + 15:
                e, ty, nom, od = best
                out.append({u'kind': u'conduit', u'type': ty, u'err': e, u'score': e + 3.0,
                            u'size': {u'diameter': nom},
                            u'text': u'Conduit {0:.0f} mm (OD {1:.1f})'.format(nom, od),
                            u'measure': u'cloud OD {0:.0f} mm'.format(D), u'conf': _conf(e, od, rec[u'rms'], tol)})
        if u'duct' in enabled:
            types = [t for t in _types_for(cat, u'duct', opts) if t.get(u'shape') == u'round'] or \
                [t for t in (cat.get(u'duct') or []) if t.get(u'shape') == u'round']
            if types and D >= 70:
                sizes = cat.get(u'duct_round_sizes') or []
                size, e = nearest(Dp, sizes) if sizes else (round_to(Dp, 25, 50), abs(round_to(Dp, 25, 50) - Dp))
                prior = 15.0 if Dp < 180 else 0.0
                out.append({u'kind': u'duct', u'type': types[0], u'err': e, u'score': e + prior,
                            u'size': {u'diameter': size, u'shape': u'round'},
                            u'text': u'Round duct {0:.0f} mm'.format(size),
                            u'measure': u'cloud {0:.0f} mm'.format(D), u'conf': _conf(e, size, rec[u'rms'], tol)})
    elif shape == u'rect':
        W = rec[u'W']
        H = rec[u'H']
        vert = rec[u'vertical']
        length = v_dist(rec[u'p0'], rec[u'p1'])
        if u'duct' in enabled:
            types = [t for t in _types_for(cat, u'duct', opts) if t.get(u'shape') == u'rect'] or \
                [t for t in (cat.get(u'duct') or []) if t.get(u'shape') == u'rect']
            if types:
                sizes = cat.get(u'duct_rect_sizes') or []
                w, ew = nearest(W, sizes) if sizes else (round_to(W, 50, 100), 0.0)
                h, eh = nearest(H, sizes) if sizes else (round_to(H, 50, 100), 0.0)
                ew = abs(w - W)
                eh = abs(h - H)
                prior = 0.0
                if not vert and H <= 160 and W >= 1.4 * H:
                    prior += 25.0
                if rec.get(u'slab_above') and H >= 200 and not vert:
                    prior += 30.0
                if vert and length >= 2000 and min(W, H) >= 150:
                    prior += 30.0
                out.append({u'kind': u'duct', u'type': types[0], u'err': max(ew, eh), u'score': max(ew, eh) + prior,
                            u'size': {u'width': w, u'height': h, u'shape': u'rect'},
                            u'text': u'Duct {0:.0f} x {1:.0f}'.format(w, h),
                            u'measure': u'cloud {0:.0f} x {1:.0f} mm'.format(W, H),
                            u'conf': _conf(max(ew, eh), min(w, h), rec[u'rms'], tol)})
        if u'tray' in enabled and not vert and cat.get(u'tray'):
            widths = cat.get(u'tray_widths') or []
            w, ew = nearest(W, widths) if widths else (round_to(W, 50, 50), 0.0)
            ew = abs(w - W)
            h = round_to(H, 25.0, 25.0)
            prior = 0.0 if (H <= 160 and W >= 1.4 * H) else 40.0
            out.append({u'kind': u'tray', u'type': _types_for(cat, u'tray', opts)[0], u'err': ew,
                        u'score': ew + prior, u'size': {u'width': w, u'height': h},
                        u'text': u'Cable tray {0:.0f} x {1:.0f}'.format(w, h),
                        u'measure': u'cloud {0:.0f} x {1:.0f} mm'.format(W, H),
                        u'conf': _conf(ew, w, rec[u'rms'], tol)})
        struct = u'column' if vert else u'beam'
        if struct in enabled and cat.get(struct):
            best = None
            for ty in _types_for(cat, struct, opts):
                tw = ty.get(u'w')
                td = ty.get(u'd')
                if not tw or not td:
                    continue
                for ww, dd, swap in ((tw, td, False), (td, tw, True)):
                    e = max(abs(ww - W), abs(dd - H))
                    if best is None or e < best[0]:
                        best = (e, ty, swap)
            if best is not None:
                e, ty, swap = best
                prior = 60.0
                if vert and length >= 2000 and min(W, H) >= 150:
                    prior = 0.0
                if not vert and rec.get(u'slab_above') and H >= 150:
                    prior = 0.0
                out.append({u'kind': struct, u'type': ty, u'err': e, u'score': e + prior,
                            u'size': {u'swap': swap},
                            u'text': u'{0} {1}'.format(KIND_LABEL[struct], ty[u'name']),
                            u'measure': u'cloud {0:.0f} x {1:.0f} mm'.format(W, H),
                            u'conf': _conf(e, min(W, H), rec[u'rms'], tol)})
    elif shape == u'wall' and u'wall' in enabled:
        th = rec.get(u'thickness')
        target = th if th else float(st[u'wall_fallback_mm'])
        types = [t for t in _types_for(cat, u'wall', opts) if t.get(u'width')]
        types.sort(key=lambda t: abs(t[u'width'] - target))
        seen = set()
        for ty in types:
            if ty[u'width'] in seen and len(out) >= 1:
                continue
            seen.add(ty[u'width'])
            e = abs(ty[u'width'] - target)
            out.append({u'kind': u'wall', u'type': ty, u'err': e, u'score': e + (0.0 if th else 5.0),
                        u'size': {u'width': ty[u'width']},
                        u'text': u'Wall {0} ({1:.0f} mm)'.format(ty[u'name'], ty[u'width']),
                        u'measure': (u'cloud thickness {0:.0f} mm'.format(th) if th
                                     else u'other face not scanned - nearest to {0:.0f} mm'.format(target)),
                        u'conf': _conf(e, ty[u'width'], rec[u'rms'], tol) if th else u'Medium'})
            if len(out) >= 4:
                break
    elif shape == u'slab':
        for kind in ((rec[u'which'], u'ceiling' if rec[u'which'] == u'floor' else u'floor')):
            if kind in enabled and cat.get(kind):
                ty = _types_for(cat, kind, opts)[0]
                first = kind == rec[u'which']
                out.append({u'kind': kind, u'type': ty, u'err': 0.0, u'score': 0.0 if first else 50.0,
                            u'size': {},
                            u'text': u'{0} {1}'.format(KIND_LABEL[kind], ty[u'name']),
                            u'measure': u'{0:.1f} m2 at {1:.0f} mm'.format(rec[u'area_m2'], rec[u'z']),
                            u'conf': u'High' if first else u'Low'})
    out.sort(key=lambda c: c[u'score'])
    return out


def describe(rec):
    sh = rec[u'shape']
    if sh == u'round':
        return u'Round, {0:.0f} mm across, {1:.2f} m run{2}'.format(
            rec[u'D'], v_dist(rec[u'p0'], rec[u'p1']) / 1000.0, u' (vertical)' if rec[u'vertical'] else u'')
    if sh == u'rect':
        return u'Rectangular, {0:.0f} x {1:.0f} mm, {2:.2f} m run{3}'.format(
            rec[u'W'], rec[u'H'], v_dist(rec[u'p0'], rec[u'p1']) / 1000.0, u' (vertical)' if rec[u'vertical'] else u'')
    if sh == u'wall':
        return u'Wall face, {0:.2f} m long, {1:.2f} m high'.format(
            rec[u'length'] / 1000.0, (rec[u'top_z'] - rec[u'base_z']) / 1000.0)
    if sh == u'slab':
        return u'{0}, {1:.1f} m2'.format(KIND_LABEL[rec[u'which']], rec[u'area_m2'])
    return sh


# =====================================================================
# settings
# =====================================================================

SETTINGS_VERSION = 1

DEFAULTS = {
    u'settings_version': u'1',
    u'theme': u'follow',
    u'spacing_mm': u'5',
    u'max_points': u'40000',
    u'noise_mm': u'6',
    u'click_box_mm': u'300',
    u'trace_step_mm': u'500',
    u'trace_gap_mm': u'200',
    u'trace_max_m': u'15',
    u'section_half_mm': u'700',
    u'wall_search_m': u'16',
    u'floor_search_m': u'20',
    u'slab_cell_mm': u'150',
    u'floor_outline': u'traced',
    u'wall_height': u'cloud',
    u'wall_fallback_mm': u'100',
    u'snap_axis_deg': u'3',
    u'conduit_max_mm': u'60',
    u'column_w_params': u'b,Width,BGL_Width,w',
    u'column_d_params': u'h,Depth,BGL_Depth,d',
    u'beam_w_params': u'b,Width,BGL_Width,w',
    u'beam_d_params': u'h,Depth,BGL_Depth,d',
    u'kinds': u','.join(KIND_KEYS),
    u'pipe_system': u'',
    u'duct_system': u'',
    u'level': u'',
    u'run_mode': u'trace',
    u'insulation_mm': u'0',
    u'auto_place': u'1',
    u'continuous': u'1',
    u'debug': u'1',
}
for _k in KIND_KEYS:
    DEFAULTS[u'type_' + _k] = u''

NUMERIC = {
    u'spacing_mm': (1.0, 50.0), u'max_points': (1000.0, 500000.0), u'noise_mm': (1.0, 40.0),
    u'click_box_mm': (100.0, 1000.0), u'trace_step_mm': (100.0, 2000.0), u'trace_gap_mm': (50.0, 1000.0),
    u'trace_max_m': (0.5, 100.0), u'section_half_mm': (300.0, 2000.0), u'wall_search_m': (2.0, 100.0),
    u'floor_search_m': (2.0, 100.0), u'slab_cell_mm': (50.0, 500.0), u'wall_fallback_mm': (25.0, 1000.0),
    u'snap_axis_deg': (0.0, 15.0), u'conduit_max_mm': (10.0, 200.0), u'insulation_mm': (0.0, 200.0),
}
CHOICES = {
    u'theme': (u'follow', u'dark', u'light'), u'floor_outline': (u'traced', u'rectangle'),
    u'wall_height': (u'cloud', u'levels'), u'run_mode': (u'trace', u'click'),
    u'auto_place': (u'0', u'1'), u'continuous': (u'0', u'1'), u'debug': (u'0', u'1'),
}


def _migrate_0_to_1(d):
    return d


MIGRATIONS = {0: _migrate_0_to_1}


def load_settings(text):
    d = dict(DEFAULTS)
    raw = {}
    for line in (text or u'').splitlines():
        line = line.strip()
        if not line or line.startswith(u'#') or u'=' not in line:
            continue
        k, v = line.split(u'=', 1)
        raw[k.strip()] = v.strip()
    try:
        ver = int(raw.get(u'settings_version', u'0'))
    except Exception:
        ver = 0
    while ver < SETTINGS_VERSION:
        fn = MIGRATIONS.get(ver)
        if fn is not None:
            raw = fn(raw)
        ver += 1
    for k, v in raw.items():
        if k not in DEFAULTS or k == u'settings_version':
            continue
        if k in NUMERIC:
            try:
                f = float(v)
                lo, hi = NUMERIC[k]
                if lo <= f <= hi:
                    d[k] = v
            except Exception:
                pass
        elif k in CHOICES:
            if v in CHOICES[k]:
                d[k] = v
        else:
            d[k] = v
    d[u'settings_version'] = u'{0}'.format(SETTINGS_VERSION)
    return d


def dump_settings(d):
    lines = [u'# RevoBIM Click to RVT Element settings']
    for k in sorted(d.keys()):
        if k in DEFAULTS:
            lines.append(u'{0}={1}'.format(k, d[k]))
    return u'\n'.join(lines) + u'\n'


def param_names(text):
    return [p.strip() for p in (text or u'').split(u',') if p.strip()]


# =====================================================================
# palettes
# =====================================================================

PALETTES = {
    u'dark': {
        u'Bg': u'#3C4454', u'Bar': u'#222933', u'Field': u'#2D3441', u'Card': u'#343C4A',
        u'Head': u'#323C48', u'Hover': u'#444E5E', u'Sel': u'#3A7392', u'Edge': u'#515C6B',
        u'Text': u'#EEF0F4', u'Muted': u'#BCC2CA', u'Blue': u'#7CC0F2', u'Orange': u'#F2A65A',
        u'Green': u'#2E7D46', u'GreenHover': u'#2A7240', u'GreenGlyph': u'#6FD08C',
        u'Red': u'#E06C66', u'OnAccent': u'#FFFFFF', u'Dot': u'#7CC0F2', u'Fit': u'#F2A65A',
    },
    u'light': {
        u'Bg': u'#F3F4F6', u'Bar': u'#E2E5EA', u'Field': u'#FFFFFF', u'Card': u'#FFFFFF',
        u'Head': u'#E8EBEF', u'Hover': u'#DDE3EA', u'Sel': u'#BFD9EE', u'Edge': u'#B8C0CA',
        u'Text': u'#1E232A', u'Muted': u'#505862', u'Blue': u'#1865A9', u'Orange': u'#945409',
        u'Green': u'#2E7D46', u'GreenHover': u'#276B3C', u'GreenGlyph': u'#2E7D46',
        u'Red': u'#B3261E', u'OnAccent': u'#FFFFFF', u'Dot': u'#1865A9', u'Fit': u'#945409',
    },
}
PALETTE_KEYS = sorted(PALETTES[u'dark'].keys())
TEXT_PAIRS = [
    (u'Text', u'Bg'), (u'Text', u'Bar'), (u'Text', u'Field'), (u'Text', u'Card'), (u'Text', u'Hover'),
    (u'Muted', u'Bg'), (u'Muted', u'Bar'), (u'Muted', u'Card'), (u'Blue', u'Bar'), (u'Blue', u'Card'),
    (u'Orange', u'Bar'), (u'Orange', u'Card'), (u'OnAccent', u'Green'), (u'OnAccent', u'GreenHover'),
    (u'Red', u'Bar'),
]


def hex_rgb(h):
    h = h.lstrip(u'#')
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def luminance(h):
    out = []
    for c in hex_rgb(h):
        c = c / 255.0
        out.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]


def contrast(a, b):
    la = luminance(a)
    lb = luminance(b)
    hi = max(la, lb)
    lo = min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def next_theme(cur):
    order = [u'follow', u'dark', u'light']
    i = order.index(cur) if cur in order else 0
    return order[(i + 1) % 3]


def resolve_theme(setting, canvas_dark):
    if setting == u'dark':
        return u'dark'
    if setting == u'light':
        return u'light'
    return u'dark' if canvas_dark else u'light'


THEME_LABEL = {u'follow': u'Auto', u'dark': u'Dark', u'light': u'Light'}


# =====================================================================
# shrink drawer arithmetic
# =====================================================================

DRAWER_MS = 280
DRAWER_TICK_MS = 15
DRAWER_GAP = 8.0


def ease(p):
    p = max(0.0, min(1.0, p))
    return 1.0 - (1.0 - p) ** 3


def slide_frame(a, b, p):
    return a + (b - a) * ease(p)


def bar_height(header_h):
    return max(28.0, float(header_h) + 2.0)


def parked_top(work_bottom, bar_h, slot=0):
    return work_bottom - DRAWER_GAP - bar_h * (slot + 1) - 4.0 * slot


def expand_top(saved_top, parked, cur_top, full_h, work_top, work_bottom):
    """Back to where it was, unless the bar has been moved - then open
    upward from where it now sits, kept on its screen."""
    if abs(cur_top - parked) <= 2.0:
        top = saved_top
    else:
        top = cur_top
    if top + full_h > work_bottom:
        top = work_bottom - full_h
    if top < work_top:
        top = work_top
    return top


def screen_for(left, top, width, height, screens):
    """screens: list of (l, t, r, b) work areas. The one the window overlaps
    most; the first if it overlaps none."""
    best = None
    ba = -1.0
    for sc in screens:
        ox = max(0.0, min(left + width, sc[2]) - max(left, sc[0]))
        oy = max(0.0, min(top + height, sc[3]) - max(top, sc[1]))
        a = ox * oy
        if a > ba:
            ba = a
            best = sc
    return best
