# -*- coding: utf-8 -*-
"""Bench test for the batched apply.

The thing this proves is the one that cannot be proved in Revit without a
model: when Revit throws on one panel - "A managed exception was thrown by
Revit or by one of its external applications" - the other panels in the batch
still get written, and the one at fault is named.

Run it the same way as import_check.py, from this folder.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import import_check                                              # noqa: E402
import_check.install_stubs()

import pstm_ops as ops                                           # noqa: E402


# ---------------------------------------------------------------------------
# A Revit that behaves badly in the specific ways the real one does
# ---------------------------------------------------------------------------

class FakeId(object):
    def __init__(self, value):
        self.Value = value
        self.IntegerValue = value

    def GetType(self):
        class T(object):
            Name = 'ElementId'
        return T()


class FakeView(object):
    """A panel schedule view.  `mode` decides how it misbehaves."""

    def __init__(self, ident, template, mode='ok'):
        self.Id = FakeId(ident)
        self.template = template
        self.mode = mode
        self.doc = None

    def GetTemplate(self):
        return FakeId(self.template)

    def GenerateInstanceFromTemplate(self, tid):
        if self.mode == 'throw':
            raise Exception('A managed exception was thrown by Revit or by one '
                            'of its external applications.')
        if self.mode == 'silent':
            return                      # accepted, and does nothing
        self.doc.pending[self.Id.Value] = tid.Value

    def GetType(self):
        class T(object):
            Name = 'PanelScheduleView'
        return T()


class FakeDoc(object):
    def __init__(self, views):
        self.views = dict([(v.Id.Value, v) for v in views])
        for v in views:
            v.doc = self
        self.pending = {}
        self.committed = 0
        self.rolled_back = 0

    def GetElement(self, eid):
        return self.views.get(getattr(eid, 'Value', eid))

    def Delete(self, eid):
        self.views.pop(getattr(eid, 'Value', eid), None)

    def Regenerate(self):
        pass

    # -- what a transaction does to it --------------------------------
    def commit(self):
        for view_id, tid in self.pending.items():
            view = self.views.get(view_id)
            if view is not None:
                view.template = tid
        self.pending = {}
        self.committed += 1

    def rollback(self):
        self.pending = {}
        self.rolled_back += 1


class FakeTransaction(object):
    def __init__(self, doc, name):
        self.doc = doc

    def Start(self):
        pass

    def Commit(self):
        self.doc.commit()

    def RollBack(self):
        self.doc.rollback()

    def GetFailureHandlingOptions(self):
        return self

    def SetFailuresPreprocessor(self, _):
        pass

    def SetClearAfterRollback(self, _):
        pass

    def SetFailureHandlingOptions(self, _):
        pass


class FakeGroup(object):
    def __init__(self, doc, name):
        pass

    def Start(self):
        pass

    def Assimilate(self):
        pass

    def RollBack(self):
        pass


def _patch():
    ops.Transaction = FakeTransaction
    ops.TransactionGroup = FakeGroup
    ops.placed_view_ids = lambda doc: set()
    ops._type_mismatch = lambda doc, view, tid: ''
    ops._generate_from = _generate_from
    ops.template_on = lambda view: view.GetTemplate().Value
    ops.as_id = lambda thing: thing if isinstance(thing, FakeId) else (
        getattr(thing, 'Id', thing))
    ops.eid_value = lambda eid: getattr(eid, 'Value', eid) or 0


def _generate_from(view, tid):
    try:
        view.GenerateInstanceFromTemplate(tid)
        return True, ''
    except Exception as ex:
        raise ex


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------

def _jobs(views, template):
    return [{'panel_id': v.Id, 'view_id': v.Id, 'template_id': FakeId(template),
             'label': 'Panel {0}'.format(v.Id.Value)} for v in views]


def case_one_bad_panel_does_not_lose_the_rest(problems):
    views = [FakeView(i, 100, 'ok') for i in range(1, 11)]
    views[4].mode = 'throw'
    doc = FakeDoc(views)
    result = ops.apply_moves(doc, _jobs(views, 200), None, False, chunk=20)

    moved = [v.Id.Value for v in views if v.template == 200]
    if len(moved) != 9:
        problems.append('one bad panel in a chunk of ten left {0} written, '
                        'expected 9'.format(len(moved)))
    if len(result['failed']) != 1:
        problems.append('expected exactly one failure, got {0}'.format(
            result['failed']))
    elif 'Panel 5' not in result['failed'][0][0]:
        problems.append('the failure did not name the panel at fault: '
                        '{0}'.format(result['failed'][0]))


def case_two_bad_panels_in_different_chunks(problems):
    views = [FakeView(i, 100, 'ok') for i in range(1, 26)]
    views[2].mode = 'throw'
    views[20].mode = 'throw'
    doc = FakeDoc(views)
    result = ops.apply_moves(doc, _jobs(views, 200), None, False, chunk=10)
    moved = len([v for v in views if v.template == 200])
    if moved != 23:
        problems.append('two bad panels out of 25 left {0} written, '
                        'expected 23'.format(moved))
    if len(result['failed']) != 2:
        problems.append('expected two failures, got {0}'.format(result['failed']))


def case_silent_refusal_is_reported_not_counted(problems):
    views = [FakeView(i, 100, 'ok') for i in range(1, 6)]
    views[1].mode = 'silent'
    doc = FakeDoc(views)
    result = ops.apply_moves(doc, _jobs(views, 200), None, False, chunk=20)
    if len(result['done']) != 4:
        problems.append('a panel that silently did not move was counted as '
                        'done: {0}'.format(result['done']))
    if len(result['failed']) != 1:
        problems.append('a panel that silently did not move was not reported: '
                        '{0}'.format(result['failed']))


def case_every_panel_bad(problems):
    views = [FakeView(i, 100, 'throw') for i in range(1, 4)]
    doc = FakeDoc(views)
    result = ops.apply_moves(doc, _jobs(views, 200), None, False, chunk=20)
    if result['done']:
        problems.append('nothing should have been written: {0}'.format(
            result['done']))
    if len(result['failed']) != 3:
        problems.append('all three should be reported, got {0}'.format(
            result['failed']))


def case_already_right_is_left_alone(problems):
    views = [FakeView(i, 200, 'throw') for i in range(1, 4)]
    doc = FakeDoc(views)
    result = ops.apply_moves(doc, _jobs(views, 200), None, False, chunk=20)
    if len(result['done']) != 3:
        problems.append('panels already on the template should not be touched: '
                        '{0}'.format(result))


def case_single_phase_counts_in_ones(problems):
    import pstm_core as core
    settings = {'slot_step': '3', 'slot_min': '3', 'slot_max': '24'}

    three = core.slot_options(settings, core.slots_per_way(False))
    if three[:4] != [3, 6, 9, 12]:
        problems.append('three phase should count in threes, got '
                        '{0}'.format(three[:6]))

    single = core.slot_options(settings, core.slots_per_way(True))
    if single[:5] != [1, 2, 3, 4, 5]:
        problems.append('single phase should count in ones from one, got '
                        '{0}'.format(single[:6]))
    if single[-1] != 24:
        problems.append('single phase should still stop at the maximum, got '
                        '{0}'.format(single[-1]))

    # a way is a way whichever list it came from
    if core.ways_from_slots(12, 3) != 4 or core.ways_from_slots(12, 1) != 12:
        problems.append('ways per slot count is wrong: {0} / {1}'.format(
            core.ways_from_slots(12, 3), core.ways_from_slots(12, 1)))


def case_locked_panels_are_skipped_not_failed(problems):
    """A panel somebody else owns is left alone and the rest still go through."""
    import pstm_model as model

    views = [FakeView(i, 100, 'ok') for i in range(1, 8)]
    doc = FakeDoc(views)
    mine = set([2, 5])          # panels 2 and 5 are somebody else's

    class FakeOwnership(object):
        def __init__(self, _doc):
            pass

        def locked_any(self, elements):
            for el in elements:
                if getattr(el, 'Id', None) is not None and el.Id.Value in mine:
                    return 'workset "Electrical" is owned by jsmith'
            return ''

    real = model.Ownership
    model.Ownership = FakeOwnership
    try:
        result = ops.apply_moves(doc, _jobs(views, 200), None, False, chunk=20)
    finally:
        model.Ownership = real

    moved = sorted([v.Id.Value for v in views if v.template == 200])
    if moved != [1, 3, 4, 6, 7]:
        problems.append('locked panels should be skipped and the rest written, '
                        'written: {0}'.format(moved))
    if len(result.get('locked') or []) != 2:
        problems.append('expected two locked panels reported, got {0}'.format(
            result.get('locked')))
    if result.get('failed'):
        problems.append('a locked panel is not a failure: {0}'.format(
            result['failed']))
    for _, why in (result.get('locked') or []):
        if 'jsmith' not in why:
            problems.append('the lock reason should name the owner: '
                            '{0}'.format(why))


def case_regenerate_repours_every_schedule(problems):
    """Regenerate re-pours from the template each view is already on."""
    import pstm_model as model

    views = [FakeView(i, 300 + i, 'ok') for i in range(1, 6)]
    views[1].template = 0            # no template on this one
    views[3].mode = 'throw'
    doc = FakeDoc(views)
    poured = []

    def _watch(view, tid):
        poured.append((view.Id.Value, tid.Value))
        view.GenerateInstanceFromTemplate(tid)
        return True, ''

    class FakeOwnership(object):
        def __init__(self, _doc):
            pass

        def locked(self, element):
            if element.Id.Value == 3:
                return 'checked out by jsmith'
            return ''

        def locked_any(self, elements):
            return ''

    real_gen, real_views = ops._generate_from, ops.instance_views
    real_own = model.Ownership
    ops._generate_from = _watch
    ops.instance_views = lambda d: views
    model.Ownership = FakeOwnership
    try:
        result = ops.job_regenerate(doc, None, 20)()
    finally:
        ops._generate_from, ops.instance_views = real_gen, real_views
        model.Ownership = real_own

    # 1 and 5 are clean; 2 has no template, 3 is locked, 4 throws.  1 and 4 are
    # attempted twice on purpose - 4 takes its chunk down, and the chunk is then
    # replayed one at a time, which is what stops 4 from costing 1 and 5.
    if sorted(set([v for v, _ in poured])) != [1, 4, 5]:
        problems.append('regenerate poured the wrong set: {0}'.format(poured))
    for view_id, tid in poured:
        if tid != 300 + view_id:
            problems.append('regenerate must re-pour the template the view is '
                            'already on, got {0} for view {1}'.format(
                                tid, view_id))
    if len(result['done']) != 2:
        problems.append('expected two regenerated, got {0}'.format(result['done']))
    if len(result.get('locked') or []) != 1:
        problems.append('the locked schedule was not reported: {0}'.format(
            result.get('locked')))
    if len(result['failed']) != 2:
        problems.append('the templateless and the throwing one should both be '
                        'reported: {0}'.format(result['failed']))
    if result.get('total') != 5:
        problems.append('total should count every schedule, got {0}'.format(
            result.get('total')))


def case_edit_template_only_claims_what_it_can_open(problems):
    """A template Revit exposes as a view opens; a plain element does not."""

    class FakeElement(object):
        def __init__(self, ident, name):
            self.Id = FakeId(ident)
            self.name = name

    class FakeTemplateView(FakeElement):
        def __init__(self, ident, name):
            FakeElement.__init__(self, ident, name)

        def IsPanelScheduleTemplate(self):
            return True

    class Doc(object):
        def __init__(self, elements):
            self.elements = dict([(e.Id.Value, e) for e in elements])

        def GetElement(self, eid):
            return self.elements.get(getattr(eid, 'Value', eid))

    plain = FakeElement(10, 'BGL_Schedule One Column TP Master')
    as_view = FakeTemplateView(11, 'BGL_Schedule One Column SP Master')
    doc = Doc([plain, as_view])

    real_view, real_coll, real_name = (ops._as_view, ops.FilteredElementCollector,
                                       ops.element_name)
    ops._as_view = lambda el: el if isinstance(el, FakeTemplateView) else None
    ops.element_name = lambda el: getattr(el, 'name', '')

    class Collector(object):
        def __init__(self, _doc):
            pass

        def OfClass(self, _cls):
            return [as_view]

    ops.FilteredElementCollector = Collector
    try:
        # the one Revit exposes as a view is found by its id
        found = ops.template_as_view(doc, as_view.Id, as_view.name)
        if found is not as_view:
            problems.append('a template exposed as a view was not found by id')

        # a plain PanelScheduleTemplate element has no view to open
        found = ops.template_as_view(doc, plain.Id, plain.name)
        if found is not None:
            problems.append('a plain template element must not be reported as '
                            'openable, got {0}'.format(found))

        # found by name where the ids do not line up
        found = ops.template_as_view(doc, FakeId(99), as_view.name)
        if found is not as_view:
            problems.append('a template exposed as a view was not found by name')
    finally:
        ops._as_view, ops.FilteredElementCollector = real_view, real_coll
        ops.element_name = real_name


CASES = [
    case_single_phase_counts_in_ones,
    case_edit_template_only_claims_what_it_can_open,
    case_regenerate_repours_every_schedule,
    case_locked_panels_are_skipped_not_failed,
    case_one_bad_panel_does_not_lose_the_rest,
    case_two_bad_panels_in_different_chunks,
    case_silent_refusal_is_reported_not_counted,
    case_every_panel_bad,
    case_already_right_is_left_alone,
]


def main():
    _patch()
    problems = []
    for case in CASES:
        try:
            case(problems)
        except Exception as ex:
            problems.append('{0} blew up: {1}'.format(case.__name__, ex))
    if problems:
        sys.stdout.write('FAILED - {0} problem(s)\n'.format(len(problems)))
        for line in problems:
            sys.stdout.write('  * {0}\n'.format(line))
        return 1
    sys.stdout.write('OK - {0} batching cases pass\n'.format(len(CASES)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
