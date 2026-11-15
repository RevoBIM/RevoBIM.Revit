# -*- coding: utf-8 -*-
"""RevoBIM PY - Panel Template Mngr: everything that writes.

Nothing in this module runs on the WPF thread.  The window is modeless so Revit
stays usable, which means every write has to go through an ExternalEvent - the
handler here is raised by the window and does its work inside Revit's own API
context.

Everything one press of a button creates belongs in one transaction, so a
failure rolls back cleanly.  Revit's own dialogs are suppressed for the duration
of a run: a DialogBoxShowing handler that calls OverrideResult, plus an
IFailuresPreprocessor on the transaction that deletes warnings.

Runs on IronPython 2.7 and IronPython 3: no f-strings, no print statements.
"""

import pstm_clr                                                  # noqa: F401
import clr

from pstm_core import (eid_value, as_id, element_name, set_element_name,
                       unique_name, invoke_named, invoke_static_named,
                       method_shapes)

from Autodesk.Revit.DB import (Transaction, ElementId, XYZ,
                               ElementTransformUtils, IFailuresPreprocessor,
                               FailureProcessingResult, FailureSeverity,
                               FilteredElementCollector)

TransactionGroup = None
try:
    from Autodesk.Revit.DB import TransactionGroup as _TG
    TransactionGroup = _TG
except Exception:
    pass
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent

PanelScheduleView = None
PanelScheduleTemplate = None
try:
    from Autodesk.Revit.DB.Electrical import PanelScheduleView as _PSV
    PanelScheduleView = _PSV
except Exception:
    pass
try:
    from Autodesk.Revit.DB.Electrical import PanelScheduleTemplate as _PST
    PanelScheduleTemplate = _PST
except Exception:
    pass


# ---------------------------------------------------------------------------
# Suppressing Revit's own noise
# ---------------------------------------------------------------------------

class WarningSwallower(IFailuresPreprocessor):
    """Delete warnings so a run does not stop on a dialog."""

    def PreprocessFailures(self, accessor):
        try:
            for failure in accessor.GetFailureMessages():
                try:
                    if failure.GetSeverity() == FailureSeverity.Warning:
                        accessor.DeleteWarning(failure)
                except Exception:
                    pass
        except Exception:
            pass
        return FailureProcessingResult.Continue


class DialogSwallower(object):
    """Answer Revit's task dialogs for the duration of a run.

    Hooked to DialogBoxShowing exactly once and then switched on and off with a
    flag.  Unsubscribing an IronPython bound method from a .NET event is not
    reliable - each attribute access makes a fresh delegate - so a swallower
    that tried to unhook per run risked either leaking handlers or, worse,
    leaving every Revit dialog answered for the rest of the session.
    """

    def __init__(self, uiapp):
        self.uiapp = uiapp
        self.hooked = False
        self.active = False

    def _handler(self, sender, args):
        if not self.active:
            return
        try:
            args.OverrideResult(1)   # IDOK
        except Exception:
            pass

    def hook(self):
        if self.hooked:
            return
        try:
            self.uiapp.DialogBoxShowing += self._handler
            self.hooked = True
        except Exception:
            self.hooked = False

    def __enter__(self):
        self.hook()
        self.active = True
        return self

    def __exit__(self, exc_type, exc_value, tb):
        self.active = False
        return False


def _start_transaction(doc, name):
    """A started transaction with warnings swallowed, or None."""
    trans = Transaction(doc, name)
    try:
        trans.Start()
    except Exception:
        return None
    # the preprocessor is held on the transaction, which is held by the caller,
    # so it stays alive until the commit
    try:
        opts = trans.GetFailureHandlingOptions()
        opts.SetFailuresPreprocessor(WarningSwallower())
        opts.SetClearAfterRollback(True)
        trans.SetFailureHandlingOptions(opts)
    except Exception:
        pass
    return trans


def run_transaction(doc, name, fn):
    """One transaction, warnings swallowed, rolled back on any failure."""
    trans = _start_transaction(doc, name)
    if trans is None:
        return None, 'could not start a transaction'
    try:
        result = fn()
        trans.Commit()
        return result, ''
    except Exception as ex:
        try:
            trans.RollBack()
        except Exception:
            pass
        return None, str(ex)


def owns_transactions(fn):
    """Mark a job as running its own transactions.

    A job that writes to many elements must not be one transaction.  Revit
    answers a bad element with "A managed exception was thrown by Revit or by
    one of its external applications", the transaction rolls back, and every
    other element in the batch is lost with it - which is a whole afternoon's
    Apply undone by one panel.  A job marked this way is run outside
    run_transaction and takes its own transactions in small pieces.
    """
    fn.owns_transaction = True
    return fn


def run_batches(doc, name, items, apply_one, chunk=20, progress=None,
                label_of=None):
    """Write `items` in chunks, retrying a failed chunk one item at a time.

    `apply_one(item)` does the write and returns (ok, note); it may raise.
    Everything happens inside a TransactionGroup, so Revit's undo still sees
    one step, but a chunk that Revit refuses is rolled back and then replayed
    item by item - so the one item at fault is named and only that one is lost.

    Returns (results, group_error) where results is a list of (item, ok, note)
    in the order the items were given.
    """
    results = {}
    total = len(items) or 1
    label_of = label_of or (lambda item: '')

    group = None
    if TransactionGroup is not None:
        try:
            group = TransactionGroup(doc, name)
            group.Start()
        except Exception:
            group = None

    def _one_by_one(batch, seen):
        for item in batch:
            _tick(progress, seen[0], total, label_of(item))
            seen[0] += 1
            trans = _start_transaction(doc, name)
            if trans is None:
                results[id(item)] = (False, 'could not start a transaction')
                continue
            try:
                ok, note = apply_one(item)
                trans.Commit()
                results[id(item)] = (ok, note)
            except Exception as ex:
                try:
                    trans.RollBack()
                except Exception:
                    pass
                results[id(item)] = (False, 'Revit refused this one: {0}'.format(ex))

    try:
        index = 0
        seen = [0]
        while index < len(items):
            batch = items[index:index + chunk]
            if chunk <= 1:
                # already one at a time - a chunk retry would just do it twice
                _one_by_one(batch, seen)
                index += chunk
                continue
            trans = _start_transaction(doc, name)
            if trans is None:
                _one_by_one(batch, seen)
                index += chunk
                continue
            try:
                done_here = 0
                for item in batch:
                    _tick(progress, seen[0] + done_here, total, label_of(item))
                    done_here += 1
                    ok, note = apply_one(item)
                    results[id(item)] = (ok, note)
                trans.Commit()
                seen[0] += len(batch)
            except Exception:
                # something in this chunk was more than Revit would take.  Undo
                # the chunk and find out which one, rather than losing all of it
                try:
                    trans.RollBack()
                except Exception:
                    pass
                for item in batch:
                    results.pop(id(item), None)
                _one_by_one(batch, seen)
            index += chunk
        _tick(progress, total, total, '')
    finally:
        if group is not None:
            try:
                group.Assimilate()
            except Exception:
                try:
                    group.RollBack()
                except Exception:
                    pass

    out = []
    for item in items:
        ok, note = results.get(id(item), (False, 'never reached'))
        out.append((item, ok, note))
    return out, ''


# ---------------------------------------------------------------------------
# Template writes
# ---------------------------------------------------------------------------

def panel_schedule_data(template):
    try:
        return template.GetTableData()
    except Exception:
        return None


def schedule_type_of(element):
    """The PanelScheduleType of a template, however this release exposes it."""
    try:
        found = element.GetPanelScheduleType()
        if found is not None:
            return found
    except Exception:
        pass
    try:
        data = element.GetTableData()
        found = data.ScheduleType
        if found is not None:
            return found
    except Exception:
        pass
    # last resort: pick the enum member matching the element's own flags
    wanted = ''
    for attribute, word in (('IsBranchPanelSchedule', 'branch'),
                            ('IsSwitchboardSchedule', 'switchboard'),
                            ('IsDataPanelSchedule', 'data')):
        try:
            if getattr(element, attribute):
                wanted = word
                break
        except Exception:
            pass
    if not wanted:
        return None
    try:
        import System
        from Autodesk.Revit.DB.Electrical import PanelScheduleType
        for name in System.Enum.GetNames(clr.GetClrType(PanelScheduleType)):
            if wanted in name.lower():
                return getattr(PanelScheduleType, name)
    except Exception:
        pass
    return None


def is_template(element):
    """Did we get a template back, or an ordinary panel schedule view?"""
    try:
        return bool(element.IsPanelScheduleTemplate())
    except Exception:
        pass
    try:
        return element.GetType().Name == 'PanelScheduleTemplate'
    except Exception:
        return False


def any_phase_load_type():
    """Some PanelSchedulePhaseLoadType, for when the data will not report one."""
    try:
        import System
        from Autodesk.Revit.DB.Electrical import PanelSchedulePhaseLoadType
        names = list(System.Enum.GetNames(clr.GetClrType(PanelSchedulePhaseLoadType)))
        if names:
            return getattr(PanelSchedulePhaseLoadType, names[0])
    except Exception:
        pass
    return None


def set_slot_count(template, slots, config_value, flags):
    """Push a new slot count onto a template.

    The documented declaration is

        void UpdateCircuitTableForTemplate(PanelSchedulePhaseLoadType newType,
                                           int nNumSlots,
                                           bool bPhasesAsCurrents)

    Three arguments, and **PanelConfiguration is not one of them** - the
    configuration is fixed when the template is created.  Every earlier guess
    here passed a PanelConfiguration first, which Revit rejected with "expected
    PanelSchedulePhaseLoadType, got PanelConfiguration", so the circuit table
    was never built and the template did not survive.

    The phase load type and the currents flag are read off the template's own
    data, which already carries the source's settings by the time this runs.
    """
    data = panel_schedule_data(template)
    if data is None:
        return False, 'the template has no table data'

    flags = flags or {}

    phase_type = None
    try:
        phase_type = data.PhaseLoadType
    except Exception:
        phase_type = None
    if phase_type is None:
        phase_type = any_phase_load_type()
    if phase_type is None:
        return False, 'could not work out the phase load type'

    as_currents = False
    try:
        as_currents = bool(data.PhasesAsCurrents)
    except Exception:
        as_currents = bool(flags.get('PhasesAsCurrents', False))

    values = {}
    # anything read off the source, under its own property name
    for prop, value in flags.items():
        try:
            values[str(prop).lower()] = bool(value)
        except Exception:
            pass
    values.update({
        'newtype': phase_type,
        'phaseloadtype': phase_type,
        'type': phase_type,
        'nnumslots': int(slots),
        'numslots': int(slots),
        'numberofslots': int(slots),
        'slots': int(slots),
        'slot': int(slots),
        'bphasesascurrents': as_currents,
        'phasesascurrents': as_currents,
        'currents': as_currents,
    })
    orders = [(phase_type, int(slots), as_currents)]

    ok, err = invoke_named(data, 'UpdateCircuitTableForTemplate', values, orders)
    if not ok:
        shapes = method_shapes(_data_type(data), 'UpdateCircuitTableForTemplate')
        detail = 'could not set the slot count: {0}'.format(err)
        if shapes:
            detail += ' [Revit wants: {0}]'.format('; '.join(shapes))
        return False, detail
    return True, ''


def _data_type(data):
    try:
        return clr.GetClrType(data.GetType())
    except Exception:
        return None


def any_configuration():
    """Some PanelConfiguration, for when the source will not report one."""
    try:
        import System
        from Autodesk.Revit.DB.Electrical import PanelConfiguration
        names = list(System.Enum.GetNames(clr.GetClrType(PanelConfiguration)))
        for wanted in ('OneColumn',):
            if wanted in names:
                return getattr(PanelConfiguration, wanted)
        if names:
            return getattr(PanelConfiguration, names[0])
    except Exception:
        pass
    return None


def _create_template(doc, name, source, config_value):
    """Build a bare template.

    The documented declaration, identical on 2024 and 2026, is

        PanelScheduleTemplate.Create(Document document,
                                     PanelScheduleType type,
                                     PanelConfiguration config,
                                     string strName)

    - four arguments, and NOT in the order the class summary suggests.  The
    call still goes through reflection so a release that changes it is handled,
    but the positional fallback is now the real order rather than a guess.
    """
    if PanelScheduleTemplate is None:
        return None, 'PanelScheduleTemplate is not on this release'

    sched_type = schedule_type_of(source)
    if sched_type is None:
        return None, 'could not work out the panel schedule type'

    if config_value is None:
        try:
            config_value = source.GetTableData().PanelConfiguration
        except Exception:
            config_value = None
    if config_value is None:
        # never leave it None: that makes the four argument overload
        # unfillable and drops the call to a fallback for no reason
        config_value = any_configuration()

    try:
        clr_type = clr.GetClrType(PanelScheduleTemplate)
    except Exception as ex:
        return None, 'no CLR type: {0}'.format(ex)

    values = {
        'document': doc, 'doc': doc,
        'name': name,
        'scheduletype': sched_type, 'type': sched_type,
        'panelconfig': config_value, 'config': config_value,
    }
    orders = [(doc, sched_type, config_value, name)]
    ok, result = invoke_static_named(clr_type, 'Create', values, orders)
    if ok and result is not None:
        return result, ''

    shapes = method_shapes(clr_type, 'Create')
    detail = str(result)
    if shapes:
        detail += ' [Revit wants: {0}]'.format('; '.join(shapes))
    return None, detail


def _pour_layout(new_el, source):
    """Get the source's layout and appearance into the new template.

    SetTableData first, deliberately.  Element.CopyFrom copies *all* values from
    the other element, which includes its name - a copy that then could not be
    renamed sat in the model under the source's own name, which is exactly what
    "it says it created them but they are not there" looks like.  CopyFrom is
    kept only as a fallback, and the caller always renames afterwards.
    """
    tried = []
    try:
        new_el.SetTableData(source.GetTableData())
        return True, tried
    except Exception as ex:
        tried.append('SetTableData: {0}'.format(ex))
    try:
        new_el.CopyFrom(source)
        return True, tried
    except Exception as ex:
        tried.append('CopyFrom: {0}'.format(ex))
    return False, tried


def still_there(doc, element_id):
    """Is the element still in the document, right now?"""
    try:
        found = doc.GetElement(element_id)
    except Exception:
        return False
    if found is None:
        return False
    try:
        return bool(found.IsValidObject)
    except Exception:
        return True


def _build_once(doc, source, name, slots, config_value, flags, copy_layout):
    """Make one template, checking after every step that it still exists.

    Revit can accept a call, leave the element looking fine, and then drop it at
    commit because something about it is not valid.  From the outside that is
    "it says it created them but they are not there" with nothing to go on, so
    each step is followed by a look to see whether the element survived it.

    Returns (element, steps).  element is None if it did not make it, and steps
    says how far it got.
    """
    steps = []

    element, why = _create_template(doc, name, source, config_value)
    if element is None:
        return None, ['Create refused it: {0}'.format(why)]
    element_id = element.Id
    steps.append('created')
    if not still_there(doc, element_id):
        return None, steps + ['then it vanished straight after Create']

    if copy_layout:
        try:
            element.SetTableData(source.GetTableData())
            steps.append('layout copied from the source')
        except Exception as ex:
            steps.append('SetTableData refused: {0}'.format(ex))
        if not still_there(doc, element_id):
            return None, steps + ['then it vanished when the layout went in']

    if slots:
        ok, err = set_slot_count(element, slots, config_value, flags)
        steps.append('slot count set' if ok else 'slot count failed: {0}'.format(err))
        if not still_there(doc, element_id):
            return None, steps + ['then it vanished when the slot count went in']

    try:
        doc.Regenerate()
        steps.append('regenerated')
    except Exception as ex:
        steps.append('Regenerate refused: {0}'.format(ex))
    if not still_there(doc, element_id):
        return None, steps + ['then it vanished at regeneration']

    return element, steps


def duplicate_template(doc, source, new_name, slots, config_value, taken,
                       flags=None, copy_layout=True):
    """Copy a template, rename it, and give it a fixed slot count.

    A PanelScheduleTemplate cannot be copied or duplicated by Revit, so the only
    route is Create plus the source's table data.  If the layout copy is what
    destroys it, the whole thing is tried again without the layout - a template
    of the right type, configuration, size and name is far more use than none.
    """
    name = unique_name(new_name, taken)

    element, steps = _build_once(doc, source, name, slots, config_value,
                                 flags, copy_layout)

    fallback_note = ''
    if element is None and copy_layout:
        second = unique_name(name, taken)
        element, more = _build_once(doc, source, second, slots, config_value,
                                    flags, False)
        if element is not None:
            fallback_note = ('the source layout could not be carried over, so '
                             'this is a plain template of the right type, '
                             'configuration and size - with the layout it '
                             '{0}'.format('; '.join(steps)))
            name = second
        else:
            return None, ('could not duplicate "{0}" - with the layout it {1}; '
                          'without it {2}').format(element_name(source),
                                                   '; '.join(steps),
                                                   '; '.join(more))

    if element is None:
        return None, 'could not duplicate "{0}" - it {1}'.format(
            element_name(source), '; '.join(steps))

    notes = []
    if fallback_note:
        notes.append(fallback_note)

    if element_name(element) != name:
        if not set_element_name(element, name):
            spare = unique_name(name + ' Copy', taken)
            if set_element_name(element, spare):
                notes.append('Revit would not take the name "{0}", so it is '
                             'called "{1}"'.format(name, spare))
            else:
                notes.append('Revit would not rename it - it is called '
                             '"{0}"'.format(element_name(element)))
    final = element_name(element)
    taken.add(final.lower())

    if not is_template(element):
        notes.append('it came back as a panel schedule view rather than a '
                     'template, so it will not appear in the template list')

    return element, '; '.join(notes)


def template_on(view):
    """Which template a panel schedule view is on, right now."""
    try:
        return eid_value(as_id(view.GetTemplate()))
    except Exception:
        return 0


def _regenerate(doc):
    try:
        doc.Regenerate()
    except Exception:
        pass


def _generate_from(view, tid):
    """Call the one-argument GenerateInstanceFromTemplate, and only that one.

    There is a parameterless overload on some releases which rebuilds the
    instance from the template it is ALREADY on.  Reflection that goes looking
    for "an overload we can fill" can land on it, in which case Revit does real
    work, raises nothing, and the panel stays exactly where it was - which is
    what "47 changes waiting" after a successful Apply actually was.  So the
    overload is picked by its parameter type, not by name matching.
    """
    import System
    try:
        clr_type = clr.GetClrType(view.GetType())
    except Exception:
        clr_type = None
    if clr_type is not None:
        for method in clr_type.GetMethods():
            if method.Name != 'GenerateInstanceFromTemplate':
                continue
            params = list(method.GetParameters())
            if len(params) != 1:
                continue
            if getattr(params[0].ParameterType, 'Name', '') != 'ElementId':
                continue
            try:
                method.Invoke(view, System.Array[System.Object]([tid]))
                return True, ''
            except Exception as ex:
                inner = getattr(ex, 'InnerException', None)
                return False, str(inner or ex)
    try:
        view.GenerateInstanceFromTemplate(tid)
        return True, ''
    except Exception as ex:
        return False, str(ex)


def placed_view_ids(doc):
    """Ids of schedule views that are sitting on a sheet.

    Rebuilding one of those would take it off its sheet, so the rebuild route
    below refuses to touch them.
    """
    out = set()
    try:
        from Autodesk.Revit.DB import ScheduleSheetInstance
    except Exception:
        return out
    try:
        for inst in FilteredElementCollector(doc).OfClass(ScheduleSheetInstance):
            try:
                out.add(eid_value(as_id(inst.ScheduleId)))
            except Exception:
                pass
    except Exception:
        pass
    return out


def _type_mismatch(doc, view, tid):
    """Why this template cannot go on this panel, or '' if it can.

    Revit's own Change Template dialog only lists templates that suit the
    panel.  Handing the API one that does not is answered with "A managed
    exception was thrown by Revit or by one of its external applications" -
    true, unreadable, and it used to take the whole transaction with it.
    Checking first turns that into a sentence naming the panel and the reason.
    """
    try:
        template = doc.GetElement(tid)
    except Exception:
        return ''
    if template is None:
        return 'that template is not in the model any more'
    try:
        theirs = schedule_type_of(template)
        mine = schedule_type_of(view)
    except Exception:
        return ''
    if theirs is None or mine is None:
        return ''
    if str(theirs) != str(mine):
        return ('that template is a {0} template and this panel has a {1} '
                'schedule'.format(str(theirs), str(mine)))
    return ''


def _create_for_panel(doc, panel_id, tid):
    """A panel with no schedule at all gets one, on the template asked for."""
    if PanelScheduleView is None:
        return False, 'the panel schedule API is not available on this release'
    made = None
    try:
        made = PanelScheduleView.CreateInstanceView(doc, as_id(panel_id), tid)
    except Exception as first:
        try:
            made = PanelScheduleView.CreateInstanceView(doc, as_id(panel_id))
        except Exception as second:
            return False, ('could not make a panel schedule for it: {0}; '
                           'and without a template: {1}'.format(first, second))
    if made is None:
        return False, 'Revit made no panel schedule for this panel'
    if template_on(made) != eid_value(tid):
        ok, err = _generate_from(made, tid)
        if not ok:
            return False, err
    return True, 'a panel schedule was created for this panel'


def _rebuild_on_template(doc, panel_id, view, tid):
    """Last resort: throw the schedule away and make a new one on the template.

    CreateInstanceView(doc, panel, template) is the one route that cannot be
    ignored, because the template is chosen at creation.  It costs the old view
    - so it is only reached after the polite route has been tried and proved
    not to have worked.

    If the rebuild does not take either, this RAISES, so the caller's
    transaction rolls back and the panel keeps the schedule it had.  A deleted
    schedule replaced by one that is still on the wrong template would be worse
    than not trying.
    """
    if PanelScheduleView is None:
        return False, 'the panel schedule API is not available on this release'
    old_id = None
    try:
        old_id = view.Id
    except Exception:
        pass
    if old_id is not None:
        try:
            doc.Delete(old_id)
        except Exception as ex:
            return False, 'could not clear the old schedule: {0}'.format(ex)
    try:
        made = PanelScheduleView.CreateInstanceView(doc, as_id(panel_id), tid)
    except Exception as ex:
        return False, 'rebuild refused: {0}'.format(ex)
    if made is None:
        return False, 'rebuild made no panel schedule'
    _regenerate(doc)
    if template_on(made) != eid_value(tid):
        raise RuntimeError('rebuilt the schedule and it still did not take the '
                           'template, so it was put back')
    return True, 'schedule rebuilt - Revit would not swap the template in place'


def assign_template(doc, panel_id, view, template_id, placed=None,
                    allow_rebuild=True):
    """Put a template onto a panel, and check it actually took.

    GenerateInstanceFromTemplate is the documented way to set a template, but
    it returns void, so the only way to know it worked is to read the template
    back off the view afterwards - after a regenerate, because before one the
    view still reports the old id.  Reporting "done" on the strength of the
    call not throwing is what left a table full of changes that said they had
    been applied and had not.

    Returns (ok, note) where note is empty for a clean in-place swap, or a
    short line worth showing when something had to be done the hard way.
    """
    tid = as_id(template_id)
    if tid is None:
        return False, 'no template to assign'
    wanted = eid_value(tid)

    if view is None:
        return _create_for_panel(doc, panel_id, tid)

    if template_on(view) == wanted:
        return True, ''
    ok, err = _generate_from(view, tid)
    if ok:
        _regenerate(doc)
        if template_on(view) == wanted:
            return True, ''
        err = ('Revit took the call without complaint and left the panel '
               'on its old template')
    if not allow_rebuild:
        return False, err
    if placed and eid_value(view.Id) in placed:
        return False, (err + '; its schedule is placed on a sheet, so it '
                       'was left alone rather than rebuilt')
    try:
        ok2, note = _rebuild_on_template(doc, panel_id, view, tid)
    except Exception as ex:
        return False, '{0}; {1}'.format(err, ex)
    if ok2:
        return True, note
    return False, '{0}; {1}'.format(err, note)


# ---------------------------------------------------------------------------
# Jobs.  Each of these is handed to the external event as a single callable.
# ---------------------------------------------------------------------------

def _tick(progress, done, total, label):
    if progress is None:
        return
    try:
        progress(done, total, label)
    except Exception:
        pass


def _resolve_view(doc, job):
    """The panel's schedule view, looked up now rather than carried in.

    The window reads the model once and can then sit open for an hour; an
    Element handle that old is not something to hand to a transaction.
    """
    view_id = as_id(job.get('view_id'))
    if view_id is None:
        return None
    try:
        return doc.GetElement(view_id)
    except Exception:
        return None


def apply_moves(doc, jobs, progress=None, allow_rebuild=True, chunk=20):
    """Put templates onto panels.  jobs: {panel_id, view_id, template_id, label}.

    Three passes, not one transaction and not one regenerate per panel:

      1. swap the template on every panel, in chunks;
      2. once those are committed - a commit regenerates - read every panel
         back and see which ones actually moved;
      3. rebuild the ones that did not, one transaction each, because a delete
         and a create is the risky part and must not be able to take anything
         else down with it.

    Doing it this way is what stops "A managed exception was thrown by Revit"
    on one panel from rolling back the other forty-six.

    Takes its own transactions - do not call it inside one.
    """
    done = []
    failed = []
    notes = []
    locked = []
    placed = placed_view_ids(doc)
    name = 'RevoBIM apply panel schedule templates'

    # asked again here rather than trusted from the window's read: ownership
    # is cached from central and the window may have been open for an hour
    import pstm_model as model
    owner = model.Ownership(doc)

    def _locked_reason(doc_, job, view):
        try:
            panel = doc_.GetElement(as_id(job.get('panel_id')))
        except Exception:
            panel = None
        return owner.locked_any([e for e in (view, panel) if e is not None])

    # -- pass 1: the polite swap ------------------------------------
    def _swap(job):
        view = _resolve_view(doc, job)
        tid = as_id(job.get('template_id'))
        if tid is None:
            return False, 'no template to assign'
        if view is not None and template_on(view) == eid_value(tid):
            return True, ''
        stop = _locked_reason(doc, job, view)
        if stop:
            job['locked'] = stop
            return False, stop
        if view is None:
            return _create_for_panel(doc, job.get('panel_id'), tid)
        mismatch = _type_mismatch(doc, view, tid)
        if mismatch:
            return False, mismatch
        return _generate_from(view, tid)

    first, _ = run_batches(doc, name, list(jobs), _swap, chunk, progress,
                           lambda j: j.get('label', ''))

    # -- pass 2: what actually landed -------------------------------
    stuck = []
    for job, ok, note in first:
        label = job.get('label', '')
        if not ok:
            # a panel somebody else has is not a failure to report as one -
            # it is reported separately, and the run carries on
            if job.get('locked'):
                locked.append((label, job['locked']))
            else:
                failed.append((label, note))
            continue
        view = _resolve_view(doc, job)
        wanted = eid_value(as_id(job.get('template_id')))
        if view is not None and template_on(view) != wanted:
            stuck.append(job)
        else:
            done.append(label)
            if note:
                notes.append((label, note))

    if not stuck:
        return {'done': done, 'failed': failed, 'notes': notes,
                'locked': locked}

    # -- pass 3: rebuild the ones Revit would not swap ---------------
    if not allow_rebuild:
        for job in stuck:
            failed.append((job.get('label', ''),
                           'Revit took the call and left the panel on its '
                           'old template, and rebuilding is switched off in '
                           'Settings'))
        return {'done': done, 'failed': failed, 'notes': notes,
                'locked': locked}

    rebuildable = []
    for job in stuck:
        view = _resolve_view(doc, job)
        if view is not None and eid_value(view.Id) in placed:
            failed.append((job.get('label', ''),
                           'Revit would not swap the template and its '
                           'schedule is placed on a sheet, so it was left '
                           'alone rather than rebuilt'))
        else:
            rebuildable.append(job)

    def _rebuild(job):
        view = _resolve_view(doc, job)
        return _rebuild_on_template(doc, job.get('panel_id'), view,
                                    as_id(job.get('template_id')))

    # one at a time: a delete and a create is not something to batch
    second, _ = run_batches(doc, name, rebuildable, _rebuild, 1, progress,
                            lambda j: j.get('label', ''))
    for job, ok, note in second:
        label = job.get('label', '')
        if ok:
            done.append(label)
            if note:
                notes.append((label, note))
        else:
            failed.append((label, note))
    return {'done': done, 'failed': failed, 'notes': notes, 'locked': locked}


def job_apply_assignments(doc, jobs, progress=None, allow_rebuild=True,
                          chunk=20):
    """The Apply button: apply_moves, run outside run_transaction."""
    @owns_transactions
    def _work():
        return apply_moves(doc, jobs, progress, allow_rebuild, chunk)
    return _work


def wants_uiapp(fn):
    """Mark a job that needs the UIApplication, not just the Document.

    Opening a view is a UI request, not a model edit, so it cannot be done
    from the window thread and there is nothing for a transaction to do.
    """
    fn.wants_uiapp = True
    return fn


def _as_view(element):
    """The element, if Revit will treat it as a view.  Otherwise None."""
    if element is None:
        return None
    try:
        from Autodesk.Revit.DB import View
        if isinstance(element, View):
            return element
    except Exception:
        pass
    return None


def template_as_view(doc, template_id, template_name):
    """A view Revit can open for this template, if there is one.

    PanelScheduleTemplate derives from Element, not from View - the class
    documentation is explicit about it - so most templates cannot be handed to
    RequestViewChange at all.  On the releases where a template is also a
    PanelScheduleView, IsPanelScheduleTemplate() is true on that view and it
    can be opened, so both the id and the name are looked for.
    """
    wanted = eid_value(as_id(template_id))
    element = None
    try:
        element = doc.GetElement(as_id(template_id))
    except Exception:
        element = None

    view = _as_view(element)
    if view is not None:
        return view

    if PanelScheduleView is None:
        return None
    name = (template_name or '').strip().lower()
    try:
        for candidate in FilteredElementCollector(doc).OfClass(PanelScheduleView):
            try:
                if not candidate.IsPanelScheduleTemplate():
                    continue
            except Exception:
                continue
            if eid_value(candidate.Id) == wanted:
                return _as_view(candidate)
            if name and (element_name(candidate) or '').strip().lower() == name:
                return _as_view(candidate)
    except Exception:
        pass
    return None


def job_edit_template(doc, template_id, template_name):
    """Open a panel schedule template in Revit's own editor.

    Returns {'ok', 'note'}.  When Revit offers no way in, `ok` is False and the
    note says what to do by hand rather than the tool claiming it worked - there
    is no API for opening the template editor on a chosen PanelScheduleTemplate,
    and pretending otherwise would just look like a button that does nothing.
    """
    @owns_transactions
    @wants_uiapp
    def _work(uiapp):
        view = template_as_view(doc, template_id, template_name)
        if view is None:
            return {'ok': False, 'note': (
                'Revit does not expose this template as a view, so it cannot be '
                'opened from the API.')}
        try:
            uidoc = uiapp.ActiveUIDocument
        except Exception as ex:
            return {'ok': False, 'note': 'no active document: {0}'.format(ex)}
        try:
            # a request, not an assignment: it is carried out after this API
            # context ends, which is exactly right for a modeless window
            uidoc.RequestViewChange(view)
            return {'ok': True, 'note': ''}
        except Exception as ex:
            return {'ok': False, 'note': 'Revit would not open it: {0}'.format(ex)}
    return _work


def instance_views(doc):
    """Every panel schedule in the project that is a real schedule.

    A PanelScheduleTemplate is also a PanelScheduleView on some releases, so
    the templates themselves have to be filtered out - re-pouring a template
    into itself is not the job.
    """
    out = []
    if PanelScheduleView is None:
        return out
    try:
        for view in FilteredElementCollector(doc).OfClass(PanelScheduleView):
            try:
                if view.IsPanelScheduleTemplate():
                    continue
            except Exception:
                pass
            try:
                if view.IsTemplate:
                    continue
            except Exception:
                pass
            out.append(view)
    except Exception:
        pass
    return out


def job_regenerate(doc, progress=None, chunk=20):
    """Re-pour every panel schedule from the template it is already on.

    Editing a template does not push the change into the schedules already
    made from it, so a schedule sitting on a sheet keeps showing what it showed
    when it was generated.  GenerateInstanceFromTemplate is documented as
    assigning the template's data to the instance, so calling it with the
    view's OWN template is the regenerate - the one place in this tool where
    re-pouring the current template is the point rather than the bug.

    Panels somebody else owns are skipped and named, the same as Apply, and it
    runs in the same batched transactions so one bad schedule cannot roll back
    the rest.
    """
    import pstm_model as model

    @owns_transactions
    def _work():
        views = instance_views(doc)
        owner = model.Ownership(doc)
        placed = placed_view_ids(doc)

        items = []
        for view in views:
            items.append({'view_id': view.Id,
                          'label': element_name(view) or 'panel schedule',
                          'on_sheet': eid_value(view.Id) in placed})

        done = []
        failed = []
        locked = []

        def _one(item):
            try:
                view = doc.GetElement(as_id(item['view_id']))
            except Exception:
                view = None
            if view is None:
                return False, 'that schedule is not in the model any more'
            stop = owner.locked(view)
            if stop:
                item['locked'] = stop
                return False, stop
            tid = as_id(view.GetTemplate())
            if tid is None or eid_value(tid) <= 0:
                return False, 'no template on this schedule to regenerate from'
            return _generate_from(view, tid)

        out, _ = run_batches(doc, 'RevoBIM regenerate panel schedules', items,
                             _one, chunk, progress, lambda i: i.get('label', ''))
        for item, ok, note in out:
            label = item.get('label', '')
            if ok:
                done.append(label)
            elif item.get('locked'):
                locked.append((label, item['locked']))
            else:
                failed.append((label, note))
        return {'done': done, 'failed': failed, 'locked': locked,
                'total': len(items),
                'on_sheet': len([i for i in items if i.get('on_sheet')])}
    return _work


def job_duplicate(doc, source, specs, taken, copy_layout=True, progress=None):
    """specs: list of dicts {slots, name, config, flags}."""
    def _work():
        made = []
        failed = []
        ids = []
        names = []
        total = len(specs)
        for index, spec in enumerate(specs):
            _tick(progress, index, total, spec.get('name', ''))
            el, note = duplicate_template(doc, source, spec.get('name'),
                                          spec.get('slots'), spec.get('config'),
                                          taken, spec.get('flags'), copy_layout)
            if el is None:
                failed.append((spec.get('name'), note))
            else:
                final = element_name(el)
                made.append((final, note))
                try:
                    ids.append(eid_value(el.Id))
                except Exception:
                    pass
                names.append(final)
        _tick(progress, total, total, '')
        return {'made': made, 'failed': failed, 'ids': ids, 'names': names}
    return _work


def job_delete(doc, ids, progress=None):
    def _work():
        removed = []
        failed = []
        total = len(ids)
        for index, item in enumerate(ids):
            _tick(progress, index, total, item.get('label', ''))
            try:
                doc.Delete(as_id(item['id']))
                removed.append(item.get('label', ''))
            except Exception as ex:
                failed.append((item.get('label', ''), str(ex)))
        _tick(progress, total, total, '')
        return {'removed': removed, 'failed': failed}
    return _work


def job_merge(doc, moves, delete_ids, progress=None, allow_rebuild=True):
    """moves: assignment jobs onto the target template, then delete the rest.

    Moves go through the same batched route as Apply, for the same reason: one
    panel Revit will not have must not roll back the rest.  The emptied
    templates are only deleted if every panel really did move off them.
    """
    def _delete_one(item):
        doc.Delete(as_id(item['id']))
        return True, ''

    @owns_transactions
    def _work():
        result = apply_moves(doc, moves, progress, allow_rebuild)
        failed = result.get('failed') or []
        removed = []
        if not failed and delete_ids:
            out, _ = run_batches(doc, 'RevoBIM merge templates',
                                 list(delete_ids), _delete_one, 1, progress,
                                 lambda i: i.get('label', ''))
            for item, ok, note in out:
                if ok:
                    removed.append(item.get('label', ''))
                else:
                    failed.append((item.get('label', ''), note))
        result['removed'] = removed
        result['failed'] = failed
        return result
    return _work


def job_rename(doc, template, new_name, taken):
    def _work():
        name = unique_name(new_name, taken)
        ok = set_element_name(template, name)
        return {'ok': ok, 'name': name}
    return _work


def job_rename_many(doc, pairs, taken, progress=None):
    """pairs: list of (element, wanted_name).

    Renamed in two passes.  Swapping "A" and "B", or shuffling a set of names
    along by one, means a name is briefly taken by the element that is about to
    give it up - so everything goes to a parked name first and lands on its real
    one second.  Without that, half a batch fails on a clash with itself.
    """
    def _work():
        done = []
        failed = []
        notes = []
        held = set([str(n or '').lower() for n in (taken or [])])
        for _, wanted in pairs:
            held.discard(str(wanted or '').lower())

        parked = []
        total = len(pairs) * 2 or 1
        step = 0
        for element, wanted in pairs:
            step += 1
            _tick(progress, step, total, element_name(element))
            before = element_name(element)
            park = unique_name('{0} ~renaming'.format(before), held)
            if set_element_name(element, park):
                held.add(park.lower())
                parked.append((element, before, wanted))
            else:
                failed.append((before, 'Revit would not let go of the old name'))

        for element, before, wanted in parked:
            step += 1
            _tick(progress, step, total, wanted)
            final = unique_name(wanted, held)
            if set_element_name(element, final):
                held.add(final.lower())
                done.append(final)
                if final != wanted:
                    notes.append((before, 'that name was taken, so it is now '
                                          '"{0}"'.format(final)))
            else:
                # put it back rather than leaving a parked name in the model
                set_element_name(element, before)
                failed.append((before, 'Revit refused the new name'))
        _tick(progress, total, total, '')
        return {'done': done, 'failed': failed, 'notes': notes}
    return _work


# ---------------------------------------------------------------------------
# External event
# ---------------------------------------------------------------------------

class PstmEventHandler(IExternalEventHandler):
    """Carries one job at a time from the window into Revit's API context."""

    def __init__(self):
        self.job = None
        self.title = 'RevoBIM Panel Template Mngr'
        self.doc = None
        self.on_complete = None
        self.swallower = None

    def Execute(self, uiapp):
        job = self.job
        self.job = None
        callback = self.on_complete
        result = None
        error = ''
        if job is None:
            # the window has already gone busy waiting for this, so it has to
            # hear back either way or Apply never comes back to life
            if callback is not None:
                try:
                    callback(None, 'the job went missing before it could run')
                except Exception:
                    pass
            return
        try:
            doc = self.doc or uiapp.ActiveUIDocument.Document
            if self.swallower is None:
                self.swallower = DialogSwallower(uiapp)
            with self.swallower:
                if getattr(job, 'owns_transaction', False):
                    # a job that writes to many elements takes its own
                    # transactions in pieces, so one bad element cannot roll
                    # back the rest of the batch
                    result = job(uiapp) if getattr(job, 'wants_uiapp', False) \
                        else job()
                    error = ''
                else:
                    result, error = run_transaction(doc, self.title, job)
        except Exception as ex:
            error = str(ex)
        if callback is not None:
            try:
                callback(result, error)
            except Exception:
                pass

    def GetName(self):
        return 'RevoBIM Panel Template Mngr'


def make_event():
    handler = PstmEventHandler()
    return handler, ExternalEvent.Create(handler)
