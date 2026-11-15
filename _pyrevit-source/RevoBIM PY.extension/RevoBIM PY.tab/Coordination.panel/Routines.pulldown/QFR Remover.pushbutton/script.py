# -*- coding: utf-8 -*-
"""QFR Remover - RevoBIM PY / Coordination / Routines

Strips a chosen family (or families) out of the model and closes the gap.

Pick one or more families from Cable Tray Fittings, Pipe Fittings and Duct
Fittings in the tick list. Every instance of those families is deleted, and
the two runs either side of each deleted fitting are merged into ONE
continuous element - the shorter piece is absorbed, the survivor is stretched
over the whole span, and whatever was on the far end is reconnected.

Where a true merge is not possible (different type, size or system either
side) the tool falls back to trimming the two pieces together and connecting
them, and says so in the report.

Handles back-to-back removals (two doomed fittings touching each other) by
walking through them to the first surviving element on each side.

Written for Revit 2024 / pyRevit 2.7 (IronPython 2.7).
"""

__title__ = 'QFR\nRemover'
__author__ = 'RevoBIM'
__doc__ = ('Delete every instance of the chosen Cable Tray / Pipe / Duct '
           'fitting families and merge the runs either side into one '
           'continuous element.')

import math

from pyrevit import revit, DB, script, forms

import clr
clr.AddReference('PresentationCore')
clr.AddReference('PresentationFramework')
clr.AddReference('WindowsBase')

from System.Collections.Generic import List
from System.Windows import Thickness, GridLength, GridUnitType, Visibility, \
    TextAlignment, TextTrimming
from System.Windows.Controls import CheckBox, Grid, ColumnDefinition, TextBlock
from System.Windows.Media import SolidColorBrush, Color

from Autodesk.Revit.DB.Plumbing import Pipe
from Autodesk.Revit.DB.Mechanical import Duct
from Autodesk.Revit.DB.Electrical import CableTray, Conduit


# ---------------------------------------------------------------------------
# tweakables
# ---------------------------------------------------------------------------
MM = 304.8                      # mm per foot
CONN_TOL = 25.0 / MM            # connector search radius (25 mm)
ANGLE_TOL = math.radians(1.0)   # how far off-axis the two runs may be
MIN_LEN = 5.0 / MM              # shortest straight piece we will leave behind
TOUCH_TOL = 0.5 / MM            # "already touching" distance
SIZE_TOL = 0.5 / MM             # size match tolerance for merging

TARGET_CATS = [
    DB.BuiltInCategory.OST_CableTrayFitting,
    DB.BuiltInCategory.OST_PipeFitting,
    DB.BuiltInCategory.OST_DuctFitting,
]

RUN_TYPES = (Pipe, Duct, CableTray, Conduit)

doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()
logger = script.get_logger()


def brush(r, g, b):
    return SolidColorBrush(Color.FromRgb(r, g, b))


INK = brush(0xEA, 0xEE, 0xF3)
INK_SOFT = brush(0x9E, 0xA8, 0xB4)
BLUE = brush(0x3D, 0x9B, 0xE9)


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def conn_manager(el):
    """ConnectorManager for a run element or a fitting."""
    try:
        cm = getattr(el, 'ConnectorManager', None)
        if cm:
            return cm
    except Exception:
        pass
    try:
        model = getattr(el, 'MEPModel', None)
        if model is not None and model.ConnectorManager:
            return model.ConnectorManager
    except Exception:
        pass
    return None


def end_connectors(el):
    cm = conn_manager(el)
    if cm is None:
        return []
    out = []
    try:
        for c in cm.Connectors:
            try:
                if c.ConnectorType == DB.ConnectorType.End:
                    out.append(c)
            except Exception:
                continue
    except Exception:
        return []
    return out


def is_run(el):
    """True for a straight, curve driven pipe / duct / tray / conduit."""
    if el is None:
        return False
    if not isinstance(el, RUN_TYPES):
        return False
    return isinstance(el.Location, DB.LocationCurve)


def midpoint(p, q):
    return DB.XYZ((p.X + q.X) / 2.0, (p.Y + q.Y) / 2.0, (p.Z + q.Z) / 2.0)


def frozen(pt):
    """A copy of an XYZ that will outlive the element it came from."""
    return DB.XYZ(pt.X, pt.Y, pt.Z)


class WarningSwallower(DB.IFailuresPreprocessor):
    """Deleting fittings shouts about lost connections. We know."""

    def PreprocessFailures(self, accessor):
        for failure in accessor.GetFailureMessages():
            if failure.GetSeverity() == DB.FailureSeverity.Warning:
                accessor.DeleteWarning(failure)
        return DB.FailureProcessingResult.Continue


def quiet(transaction):
    opts = transaction.GetFailureHandlingOptions()
    opts.SetFailuresPreprocessor(WarningSwallower())
    opts.SetClearAfterRollback(True)
    transaction.SetFailureHandlingOptions(opts)
    return transaction


# ---------------------------------------------------------------------------
# gathering the families
# ---------------------------------------------------------------------------
class FamilyRow(object):
    def __init__(self, name, category, ids):
        self.name = name
        self.category = category
        self.ids = ids
        self.checked = False

    @property
    def count(self):
        return len(self.ids)


def view_for_scope():
    """The active view, unless it is something we cannot collect from."""
    try:
        view = doc.ActiveView
    except Exception:
        return None
    if view is None:
        return None
    if isinstance(view, DB.ViewSheet):
        return None
    try:
        if view.IsTemplate:
            return None
    except Exception:
        pass
    return view


def collect_families(view=None):
    cats = List[DB.BuiltInCategory]()
    for c in TARGET_CATS:
        cats.Add(c)

    if view is not None:
        collector = DB.FilteredElementCollector(doc, view.Id)
    else:
        collector = DB.FilteredElementCollector(doc)

    instances = collector.WherePasses(DB.ElementMulticategoryFilter(cats)) \
                         .OfClass(DB.FamilyInstance) \
                         .WhereElementIsNotElementType() \
                         .ToElements()

    buckets = {}
    for fi in instances:
        try:
            fam = fi.Symbol.Family.Name
        except Exception:
            continue
        cat = fi.Category.Name if fi.Category else 'Fittings'
        buckets.setdefault((cat, fam), []).append(fi.Id)

    rows = []
    for (cat, fam), ids in buckets.items():
        rows.append(FamilyRow(fam, cat, ids))
    rows.sort(key=lambda r: (r.category, r.name.lower()))
    return rows


# ---------------------------------------------------------------------------
# working out what sits either side of each doomed fitting
# ---------------------------------------------------------------------------
class GapJob(object):
    """One gap to close: element A meets element B."""

    def __init__(self, id_a, pt_a, id_b, pt_b, fitting_name):
        self.id_a = id_a
        self.pt_a = pt_a
        self.id_b = id_b
        self.pt_b = pt_b
        self.fitting_name = fitting_name

    def key(self):
        a = self.id_a.IntegerValue
        b = self.id_b.IntegerValue
        return (min(a, b), max(a, b))


def neighbour_through(el, entry_pt, doomed, seen):
    """Follow a doomed fitting out of its other side to a survivor."""
    if el.Id.IntegerValue in seen:
        return None
    seen.add(el.Id.IntegerValue)

    for c in end_connectors(el):
        try:
            if c.Origin.DistanceTo(entry_pt) < CONN_TOL:
                continue                        # this is the way we came in
            if not c.IsConnected:
                continue
            for ref in c.AllRefs:
                try:
                    if ref.ConnectorType != DB.ConnectorType.End:
                        continue
                    owner = ref.Owner
                except Exception:
                    continue
                if owner is None or owner.Id == el.Id:
                    continue
                if owner.Id.IntegerValue in doomed:
                    found = neighbour_through(owner, ref.Origin, doomed, seen)
                    if found:
                        return found
                else:
                    return (owner.Id, frozen(ref.Origin))
        except Exception:
            continue
    return None


def survivors_around(fitting, doomed):
    """The live elements on each side of a fitting we are about to delete."""
    found = []
    for c in end_connectors(fitting):
        try:
            if not c.IsConnected:
                continue
        except Exception:
            continue
        for ref in c.AllRefs:
            try:
                if ref.ConnectorType != DB.ConnectorType.End:
                    continue
                owner = ref.Owner
            except Exception:
                continue
            if owner is None or owner.Id == fitting.Id:
                continue
            if owner.Id.IntegerValue in doomed:
                seen = set([fitting.Id.IntegerValue])
                hop = neighbour_through(owner, frozen(ref.Origin), doomed, seen)
                if hop:
                    found.append(hop)
            else:
                found.append((owner.Id, frozen(ref.Origin)))
            break
    return found


def build_jobs(fittings, doomed):
    jobs = []
    keys = set()
    notes = []
    for fi in fittings:
        try:
            name = fi.Symbol.Family.Name
        except Exception:
            name = 'fitting'
        sides = survivors_around(fi, doomed)
        if len(sides) < 2:
            if len(sides) == 1:
                notes.append('{0} {1} had only one connected side - '
                             'nothing to join together.'
                             .format(name, output.linkify(fi.Id)))
            continue
        if len(sides) > 2:
            notes.append('{0} {1} was connected on {2} sides - deleted, but '
                         'the gap was left for you to close by hand.'
                         .format(name, output.linkify(fi.Id), len(sides)))
            continue
        (id_a, pt_a), (id_b, pt_b) = sides[0], sides[1]
        if id_a.IntegerValue == id_b.IntegerValue:
            continue
        job = GapJob(id_a, pt_a, id_b, pt_b, name)
        if job.key() in keys:
            continue
        keys.add(job.key())
        jobs.append(job)
    return jobs, notes


# ---------------------------------------------------------------------------
# connector plumbing
# ---------------------------------------------------------------------------
def open_connector(el, pt):
    """The connector on el nearest pt, preferring a free one."""
    if el is None:
        return None
    best, best_d = None, 1e18
    for c in end_connectors(el):
        try:
            if c.IsConnected:
                continue
            d = c.Origin.DistanceTo(pt)
        except Exception:
            continue
        if d < best_d:
            best, best_d = c, d
    if best is not None and best_d <= CONN_TOL:
        return best

    best, best_d = None, 1e18
    for c in end_connectors(el):
        try:
            d = c.Origin.DistanceTo(pt)
        except Exception:
            continue
        if d < best_d:
            best, best_d = c, d
    if best is not None and best_d <= CONN_TOL:
        return best
    return None


def other_end(el, conn):
    """The connector at the opposite end of a run."""
    for c in end_connectors(el):
        try:
            if c.Origin.DistanceTo(conn.Origin) > CONN_TOL:
                return c
        except Exception:
            continue
    return None


def partner_of(conn):
    """(id, origin) of whatever is plugged into this connector."""
    try:
        if not conn.IsConnected:
            return None
        owner_id = conn.Owner.Id
    except Exception:
        return None
    for ref in conn.AllRefs:
        try:
            if ref.ConnectorType != DB.ConnectorType.End:
                continue
            owner = ref.Owner
        except Exception:
            continue
        if owner is None or owner.Id == owner_id:
            continue
        return (owner.Id, frozen(ref.Origin))
    return None


def facing_each_other(ca, cb):
    """Are the two open ends on the same axis, pointing at one another?"""
    try:
        da = ca.CoordinateSystem.BasisZ.Normalize()
        db = cb.CoordinateSystem.BasisZ.Normalize()
    except Exception:
        return True, ''

    if da.AngleTo(db.Negate()) > ANGLE_TOL:
        return False, 'the two runs are not parallel'

    gap = cb.Origin.Subtract(ca.Origin)
    if gap.GetLength() > TOUCH_TOL:
        if gap.Normalize().AngleTo(da) > ANGLE_TOL:
            return False, 'the two runs are parallel but offset from each other'
    return True, ''


def stretch_to(el, near_pt, new_pt):
    """Move the end of a run nearest near_pt out to new_pt."""
    loc = el.Location
    if not isinstance(loc, DB.LocationCurve):
        return False
    curve = loc.Curve
    p0 = curve.GetEndPoint(0)
    p1 = curve.GetEndPoint(1)
    if p0.DistanceTo(near_pt) <= p1.DistanceTo(near_pt):
        keep, keep_is_end = p1, True
    else:
        keep, keep_is_end = p0, False
    if keep.DistanceTo(new_pt) < MIN_LEN:
        return False
    try:
        if keep_is_end:
            loc.Curve = DB.Line.CreateBound(new_pt, keep)
        else:
            loc.Curve = DB.Line.CreateBound(keep, new_pt)
    except Exception:
        return False
    return True


def size_of(conn):
    try:
        if conn.Shape == DB.ConnectorProfileType.Round:
            return ('R', round(conn.Radius / SIZE_TOL), 0)
        return ('X', round(conn.Width / SIZE_TOL), round(conn.Height / SIZE_TOL))
    except Exception:
        return ('?', 0, 0)


def service_text(el):
    """System type / service type, whichever this category uses."""
    for name in ('Service Type', 'System Type'):
        try:
            p = el.LookupParameter(name)
            if p is not None and p.StorageType == DB.StorageType.String:
                return (p.AsString() or '').strip()
        except Exception:
            pass
    try:
        system = el.MEPSystem
        if system is not None:
            return 'sys:{0}'.format(system.GetTypeId().IntegerValue)
    except Exception:
        pass
    return ''


def mergeable(a, b, ca, cb):
    """Can these two runs become one element?"""
    if a.GetTypeId() != b.GetTypeId():
        return False, 'the two runs are different types'
    if size_of(ca) != size_of(cb):
        return False, 'the two runs are different sizes'
    if service_text(a) != service_text(b):
        return False, 'the two runs are on different systems / service types'
    for el in (a, b):
        cm = conn_manager(el)
        try:
            if cm is None or cm.Connectors.Size != 2:
                return False, 'one of the runs has more than two connectors'
        except Exception:
            return False, 'could not read the connectors'
    return True, ''


# ---------------------------------------------------------------------------
# merging two runs into one continuous element
# ---------------------------------------------------------------------------
REMAP = {}          # absorbed element id -> the element that swallowed it


def resolve(eid):
    key = eid.IntegerValue
    hops = 0
    while key in REMAP and hops < 64:
        eid = REMAP[key]
        key = eid.IntegerValue
        hops += 1
    return eid


def merge_runs(a, b, ca, cb, unpin):
    """Stretch the longer run over the shorter one, delete the shorter,
    then reconnect whatever was hanging off its far end."""
    try:
        len_a = a.Location.Curve.Length
        len_b = b.Location.Curve.Length
    except Exception:
        return None, 'could not read the run geometry'

    if len_b > len_a:                       # keep the longer one
        a, b = b, a
        ca, cb = cb, ca

    keep_id = a.Id
    drop_id = b.Id

    far = other_end(b, cb)
    if far is None:
        return None, 'could not find the far end of the piece being absorbed'
    far_pt = frozen(far.Origin)
    partner = partner_of(far)
    gap_pt = frozen(ca.Origin)

    curve = a.Location.Curve
    p0, p1 = curve.GetEndPoint(0), curve.GetEndPoint(1)
    anchor = p1 if p0.DistanceTo(gap_pt) <= p1.DistanceTo(gap_pt) else p0
    if anchor.DistanceTo(far_pt) < MIN_LEN:
        return None, 'merging would leave a piece shorter than 5 mm'

    pinned = []
    for el in (a, b):
        try:
            if el.Pinned:
                if not unpin:
                    return None, 'one of the runs is pinned'
                el.Pinned = False
                pinned.append(el.Id)
        except Exception:
            pass

    try:
        doc.Delete(drop_id)
    except Exception as err:
        return None, 'could not delete the absorbed piece ({0})' \
                     .format(str(err).split('\n')[0])

    keeper = doc.GetElement(keep_id)
    if keeper is None:
        return None, 'the surviving run disappeared'
    if not stretch_to(keeper, gap_pt, far_pt):
        return None, 'could not stretch the run over the gap'

    if partner:
        other = doc.GetElement(resolve(partner[0]))
        if other is not None:
            k_conn = open_connector(doc.GetElement(keep_id), far_pt)
            o_conn = open_connector(other, partner[1])
            if k_conn is not None and o_conn is not None \
                    and not o_conn.IsConnected:
                try:
                    k_conn.ConnectTo(o_conn)
                except Exception:
                    pass                    # geometry is right, link is not

    for eid in pinned:
        try:
            el = doc.GetElement(eid)
            if el is not None:
                el.Pinned = True
        except Exception:
            pass

    return (keep_id, drop_id), ''


# ---------------------------------------------------------------------------
# closing one gap
# ---------------------------------------------------------------------------
def butt_together(a, b, ca, cb, unpin):
    """Fallback: trim the two ends to meet and connect them."""
    pinned = []
    for el in (a, b):
        try:
            if el.Pinned:
                if not unpin:
                    return 'failed', 'one of the runs is pinned'
                el.Pinned = False
                pinned.append(el.Id)
        except Exception:
            pass

    a_id, b_id = a.Id, b.Id
    a_run, b_run = is_run(a), is_run(b)
    pa, pb = frozen(ca.Origin), frozen(cb.Origin)

    if a_run and b_run:
        meet = midpoint(pa, pb)
        if not stretch_to(a, pa, meet) or not stretch_to(b, pb, meet):
            return 'failed', 'trimming would leave a piece shorter than 5 mm'
    elif a_run:
        meet = pb
        if not stretch_to(a, pa, meet):
            return 'failed', 'trimming would leave a piece shorter than 5 mm'
    elif b_run:
        meet = pa
        if not stretch_to(b, pb, meet):
            return 'failed', 'trimming would leave a piece shorter than 5 mm'
    else:
        meet = pa
        if pa.DistanceTo(pb) > TOUCH_TOL:
            return 'failed', 'a fitting sits on both sides - nothing to stretch'

    ca = open_connector(doc.GetElement(a_id), meet)
    cb = open_connector(doc.GetElement(b_id), meet)
    if ca is None or cb is None:
        return 'failed', 'lost the open end after trimming'

    status, message = 'joined', ''
    try:
        ca.ConnectTo(cb)
    except Exception as err:
        status = 'trimmed'
        message = ('trimmed together but Revit would not connect them ({0})'
                   .format(str(err).split('\n')[0]))

    for eid in pinned:
        try:
            el = doc.GetElement(eid)
            if el is not None:
                el.Pinned = True
        except Exception:
            pass

    return status, message


def close_gap(job, unpin, merge):
    """Returns (status, message).

    status: 'merged'  - the two runs are now one element
            'joined'  - two elements, trimmed together and connected
            'trimmed' - geometry closed but Revit refused the connection
            'failed'  - nothing done, roll it back
    """
    a = doc.GetElement(resolve(job.id_a))
    b = doc.GetElement(resolve(job.id_b))
    if a is None or b is None:
        return 'failed', 'one side no longer exists'
    if a.Id.IntegerValue == b.Id.IntegerValue:
        return 'merged', ''             # already swallowed by an earlier merge

    ca = open_connector(a, job.pt_a)
    cb = open_connector(b, job.pt_b)
    if ca is None or cb is None:
        return 'failed', 'could not find the open end on one side'
    if ca.IsConnected or cb.IsConnected:
        return 'failed', 'the open end was already taken by something else'
    try:
        if ca.Domain != cb.Domain:
            return 'failed', 'the two sides are different services'
    except Exception:
        pass

    aligned, why = facing_each_other(ca, cb)
    if not aligned:
        return 'failed', why

    fallback_reason = ''

    if merge and is_run(a) and is_run(b):
        ok, reason = mergeable(a, b, ca, cb)
        if ok:
            sub = DB.SubTransaction(doc)
            sub.Start()
            try:
                pair, problem = merge_runs(a, b, ca, cb, unpin)
            except Exception as err:
                pair, problem = None, str(err).split('\n')[0]
            if pair:
                sub.Commit()
                REMAP[pair[1].IntegerValue] = pair[0]
                return 'merged', ''
            sub.RollBack()
            fallback_reason = problem
            # the rollback invalidated everything we were holding
            a = doc.GetElement(resolve(job.id_a))
            b = doc.GetElement(resolve(job.id_b))
            ca = open_connector(a, job.pt_a)
            cb = open_connector(b, job.pt_b)
            if a is None or b is None or ca is None or cb is None:
                return 'failed', problem or 'merge failed'
        else:
            fallback_reason = reason

    status, message = butt_together(a, b, ca, cb, unpin)
    if status == 'failed':
        return status, message
    if fallback_reason and not message:
        message = fallback_reason
    elif fallback_reason:
        message = '{0}; {1}'.format(fallback_reason, message)
    return status, message


# ---------------------------------------------------------------------------
# the routine
# ---------------------------------------------------------------------------
def run_routine(rows, trim, merge, unpin):
    REMAP.clear()

    ids = []
    for row in rows:
        ids.extend(row.ids)

    fittings = []
    for eid in ids:
        el = doc.GetElement(eid)
        if el is not None:
            fittings.append(el)

    if not fittings:
        forms.alert('Those families have no instances left.',
                    title='QFR Remover')
        return

    doomed = set([f.Id.IntegerValue for f in fittings])

    jobs, notes = ([], [])
    if trim:
        jobs, notes = build_jobs(fittings, doomed)

    tg = DB.TransactionGroup(doc, 'QFR Remover')
    tg.Start()

    deleted = 0
    try:
        t = DB.Transaction(doc, 'QFR Remover - delete fittings')
        quiet(t)
        t.Start()
        kill = List[DB.ElementId]()
        for f in fittings:
            try:
                if f.Pinned and unpin:
                    f.Pinned = False
            except Exception:
                pass
            kill.Add(f.Id)
        try:
            deleted = doc.Delete(kill).Count
        except Exception:
            deleted = 0
            for eid in kill:
                try:
                    doc.Delete(eid)
                    deleted += 1
                except Exception as err:
                    notes.append('Could not delete {0}: {1}'
                                 .format(output.linkify(eid),
                                         str(err).split('\n')[0]))
        t.Commit()
    except Exception as err:
        tg.RollBack()
        forms.alert('Nothing was changed - the delete step failed:\n\n{0}'
                    .format(err), title='QFR Remover')
        return

    merged = 0
    joined = 0
    partial = []
    failed = []

    if trim and jobs:
        t = DB.Transaction(doc, 'QFR Remover - merge runs')
        quiet(t)
        t.Start()
        for job in jobs:
            st = DB.SubTransaction(doc)
            st.Start()
            try:
                status, message = close_gap(job, unpin, merge)
            except Exception as err:
                status, message = 'failed', str(err).split('\n')[0]

            if status == 'failed':
                st.RollBack()
                failed.append((job, message or 'unknown'))
            else:
                st.Commit()
                if status == 'merged':
                    merged += 1
                elif status == 'joined':
                    joined += 1
                    if message:
                        partial.append((job, message))
                else:
                    partial.append((job, message))
        t.Commit()

    tg.Assimilate()

    # ----------------------------- the report -----------------------------
    output.print_md('## QFR Remover')
    output.print_md('**{0}** fitting{1} deleted from {2} famil{3}.'
                    .format(deleted, '' if deleted == 1 else 's',
                            len(rows), 'y' if len(rows) == 1 else 'ies'))
    if trim:
        output.print_md('**{0}** gap{1} merged into one continuous element.'
                        .format(merged, '' if merged == 1 else 's'))
        if joined:
            output.print_md('**{0}** gap{1} could not be merged, so the two '
                            'pieces were trimmed together and connected '
                            'instead.'.format(joined,
                                              '' if joined == 1 else 's'))

    if partial:
        output.print_md('### Joined, but not merged into one element')
        for job, why in partial:
            output.print_md('- {0} to {1} &mdash; {2}'
                            .format(output.linkify(resolve(job.id_a)),
                                    output.linkify(resolve(job.id_b)), why))
    if failed:
        output.print_md('### Gaps that need a look')
        for job, why in failed:
            output.print_md('- {0} to {1} &mdash; {2}'
                            .format(output.linkify(job.id_a),
                                    output.linkify(job.id_b), why))
    if notes:
        output.print_md('### Notes')
        for note in notes:
            output.print_md('- {0}'.format(note))
    if not partial and not failed and not notes:
        output.print_md('All clean.')


# ---------------------------------------------------------------------------
# the window
# ---------------------------------------------------------------------------
class QFRWindow(forms.WPFWindow):
    def __init__(self, xaml_file, rows):
        forms.WPFWindow.__init__(self, xaml_file)
        self.rows = rows
        self.confirmed = False
        self.trim = True
        self.merge = True
        self.unpin = True

        try:
            self.set_image_source(self.BrandIcon, 'icon.png')
        except Exception:
            pass

        self.HeaderBar.MouseLeftButtonDown += self.on_drag
        self.CloseBtn.Click += self.on_cancel
        self.CancelBtn.Click += self.on_cancel
        self.RunBtn.Click += self.on_run
        self.AllBtn.Click += self.on_all
        self.NoneBtn.Click += self.on_none
        self.SearchBox.TextChanged += self.on_search
        self.ViewChk.Checked += self.on_scope
        self.ViewChk.Unchecked += self.on_scope
        self.TrimChk.Checked += self.on_option
        self.TrimChk.Unchecked += self.on_option

        self.build_list()

    # ------------------------------------------------------------------
    def on_drag(self, sender, args):
        try:
            self.DragMove()
        except Exception:
            pass

    def row_content(self, row):
        grid = Grid()
        for width in (None, 132, 52):
            col = ColumnDefinition()
            if width is None:
                col.Width = GridLength(1, GridUnitType.Star)
            else:
                col.Width = GridLength(width)
            grid.ColumnDefinitions.Add(col)

        name = TextBlock()
        name.Text = row.name
        name.Foreground = INK
        name.TextTrimming = TextTrimming.CharacterEllipsis
        Grid.SetColumn(name, 0)
        grid.Children.Add(name)

        cat = TextBlock()
        cat.Text = row.category.replace(' Fittings', '')
        cat.Foreground = INK_SOFT
        cat.FontSize = 11
        cat.TextTrimming = TextTrimming.CharacterEllipsis
        Grid.SetColumn(cat, 1)
        grid.Children.Add(cat)

        qty = TextBlock()
        qty.Text = str(row.count)
        qty.Foreground = BLUE
        qty.FontSize = 11
        qty.TextAlignment = TextAlignment.Right
        qty.Margin = Thickness(0, 0, 4, 0)
        Grid.SetColumn(qty, 2)
        grid.Children.Add(qty)

        return grid

    def build_list(self):
        term = (self.SearchBox.Text or '').strip().lower()
        self.SearchHint.Visibility = \
            Visibility.Collapsed if self.SearchBox.Text else Visibility.Visible

        style = self.Resources['RowCheck']
        self.FamilyList.Children.Clear()

        shown = 0
        for row in self.rows:
            if term and term not in row.name.lower() \
                    and term not in row.category.lower():
                continue
            box = CheckBox()
            box.Style = style
            box.Tag = row
            box.Content = self.row_content(row)
            box.IsChecked = row.checked
            box.Checked += self.on_tick
            box.Unchecked += self.on_tick
            self.FamilyList.Children.Add(box)
            shown += 1

        if not shown:
            empty = TextBlock()
            empty.Text = ('Nothing matches that search.' if term else
                          'No fitting families in this view.')
            empty.Foreground = INK_SOFT
            empty.Margin = Thickness(12, 8, 12, 8)
            self.FamilyList.Children.Add(empty)

        self.update_status()

    def picked(self):
        return [r for r in self.rows if r.checked]

    def update_status(self):
        picked = self.picked()
        total = sum([r.count for r in picked])
        scope = 'this view' if self.ViewChk.IsChecked else 'the whole project'
        if not picked:
            self.StatusText.Text = 'Nothing selected. Scanning {0}.'.format(scope)
            self.RunBtn.IsEnabled = False
        else:
            self.StatusText.Text = \
                '{0} famil{1} selected - {2} instance{3} in {4} will be ' \
                'deleted{5}.'.format(
                    len(picked), 'y' if len(picked) == 1 else 'ies',
                    total, '' if total == 1 else 's', scope,
                    ' and the runs merged into one element'
                    if self.TrimChk.IsChecked else '')
            self.RunBtn.IsEnabled = True

    # ------------------------------------------------------------------
    def on_tick(self, sender, args):
        row = sender.Tag
        if row is not None:
            row.checked = bool(sender.IsChecked)
        self.update_status()

    def on_search(self, sender, args):
        self.build_list()

    def on_option(self, sender, args):
        self.update_status()

    def on_all(self, sender, args):
        term = (self.SearchBox.Text or '').strip().lower()
        for row in self.rows:
            if term and term not in row.name.lower() \
                    and term not in row.category.lower():
                continue
            row.checked = True
        self.build_list()

    def on_none(self, sender, args):
        for row in self.rows:
            row.checked = False
        self.build_list()

    def on_scope(self, sender, args):
        view = view_for_scope() if self.ViewChk.IsChecked else None
        keep = set([(r.category, r.name) for r in self.rows if r.checked])
        self.rows = collect_families(view)
        for row in self.rows:
            if (row.category, row.name) in keep:
                row.checked = True
        self.build_list()

    def on_cancel(self, sender, args):
        self.confirmed = False
        self.Close()

    def on_run(self, sender, args):
        if not self.picked():
            return
        self.confirmed = True
        self.trim = bool(self.TrimChk.IsChecked)
        self.merge = bool(self.TrimChk.IsChecked)
        self.unpin = bool(self.UnpinChk.IsChecked)
        self.Close()


# ---------------------------------------------------------------------------
# go
# ---------------------------------------------------------------------------
start_view = view_for_scope()
rows = collect_families(start_view)

if not rows and start_view is None:
    forms.alert('No Cable Tray Fittings, Pipe Fittings or Duct Fittings were '
                'found in this project.', title='QFR Remover')
else:
    window = QFRWindow(script.get_bundle_file('QFRWindow.xaml'), rows)
    if start_view is None:
        window.ViewChk.IsChecked = False        # a sheet or template is open
    window.show_dialog()

    if window.confirmed:
        try:
            run_routine(window.picked(), window.trim, window.merge,
                        window.unpin)
        except Exception as err:
            logger.error('QFR Remover failed: %s', err)
            forms.alert('Something went wrong:\n\n{0}'.format(err),
                        title='QFR Remover')
