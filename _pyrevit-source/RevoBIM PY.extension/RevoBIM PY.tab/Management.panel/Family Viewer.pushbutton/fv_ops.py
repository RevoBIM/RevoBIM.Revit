# -*- coding: utf-8 -*-
"""Family Viewer - everything that has to happen on Revit's own thread.

The window is modeless, so it cannot touch the API directly.  Every read of the
model, every preview image and both Select buttons go out through one
IExternalEventHandler.  Execute runs on Revit's UI thread, which is the same
thread the window's dispatcher runs on, so the callback can be invoked straight
from Execute with no marshalling.
"""

import fv_clr  # noqa: F401  - must be first

from System.Collections.Generic import List

from Autodesk.Revit.DB import ElementId, FilteredElementCollector
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent

import fv_core
import fv_model
from fv_core import eid_value

PREVIEW_BATCH = 10


class Job(object):
    def __init__(self, kind, payload=None, done=None, failed=None):
        self.kind = kind
        self.payload = payload or {}
        self.done = done
        self.failed = failed


class FamilyViewerHandler(IExternalEventHandler):
    """One handler, a queue of jobs.  Raise() is cheap; Revit runs them when it
    is next idle."""

    def __init__(self):
        self.queue = []
        self.name = 'RevoBIM Family Viewer'

    def GetName(self):
        return self.name

    def add(self, job):
        self.queue.append(job)

    def Execute(self, uiapp):
        while self.queue:
            job = self.queue.pop(0)
            try:
                result = self._run(uiapp, job)
            except Exception:
                text = fv_core.format_exc()
                fv_core.log('job "' + str(job.kind) + '" failed:\n' + text)
                if job.failed:
                    try:
                        job.failed(text)
                    except Exception:
                        pass
                continue
            if job.done:
                try:
                    job.done(result)
                except Exception:
                    fv_core.log('callback for "' + str(job.kind) +
                                '" failed:\n' + fv_core.format_exc())

    # -- the jobs ---------------------------------------------------------

    def _run(self, uiapp, job):
        if job.kind == 'read':
            return self._read(uiapp, job.payload)
        if job.kind == 'preview':
            return self._preview(uiapp, job.payload)
        if job.kind == 'select':
            return self._select(uiapp, job.payload)
        if job.kind == 'lists':
            return self._lists(uiapp, job.payload)
        if job.kind == 'apply':
            return self._apply(uiapp, job.payload)
        if job.kind == 'place':
            return self._place(uiapp, job.payload)
        if job.kind == 'view_categories':
            return self._view_categories(uiapp, job.payload)
        if job.kind == 'debug':
            return self._debug(uiapp, job.payload)
        if job.kind == 'instances':
            return self._instances(uiapp, job.payload)
        if job.kind == 'isolate':
            return self._isolate(uiapp, job.payload)
        if job.kind == 'restore_view':
            return self._restore_view(uiapp, job.payload)
        raise ValueError('unknown job: ' + str(job.kind))

    def _debug(self, uiapp, payload):
        """What Revit itself says about this session, for the report."""
        uidoc, doc = self._doc(uiapp)
        found = {}
        try:
            app = uiapp.Application
            found['revit'] = str(app.VersionName) + ' (' + \
                str(app.VersionNumber) + ', build ' + str(app.VersionBuild) + ')'
        except Exception:
            found['revit'] = '(could not be read)'
        for name, call in (('document', lambda: doc.Title),
                           ('path', lambda: doc.PathName),
                           ('workshared', lambda: str(doc.IsWorkshared)),
                           ('active view', lambda: uidoc.ActiveView.Name),
                           ('view type',
                            lambda: str(uidoc.ActiveView.ViewType))):
            try:
                found[name] = str(call())
            except Exception:
                found[name] = '(could not be read)'

        # what is actually in the active view, by category - the single most
        # useful thing when the answer is "nothing showed up"
        tally = {}
        try:
            collector = FilteredElementCollector(doc, uidoc.ActiveView.Id)
            collector = collector.WhereElementIsNotElementType()
            for element in collector:
                try:
                    cat = element.Category
                except Exception:
                    cat = None
                name = cat.Name if cat is not None else '(no category)'
                tally[name] = tally.get(name, 0) + 1
        except Exception:
            pass
        found['view_categories'] = tally
        return found

    def _instances(self, uiapp, payload):
        uidoc, doc = self._doc(uiapp)
        view = None
        if payload.get('scope') == fv_model.SCOPE_VIEW:
            try:
                view = uidoc.ActiveView
            except Exception:
                view = None
        rows, seen = fv_model.read_instances(
            doc,
            payload.get('type_ids', []),
            columns=payload.get('columns'),
            view=view,
            ignore_nested=payload.get('ignore_nested', True),
            phase_id=payload.get('phase_id'),
            phase_mode=payload.get('phase_mode', 'existing'),
            cap=payload.get('cap', 20000))
        return {'rows': rows, 'seen': seen,
                'cap': payload.get('cap', 20000)}

    def _isolate(self, uiapp, payload):
        """Zoom to the picked elements, then isolate them in the view.

        Temporary Hide/Isolate is a view setting, so it needs a transaction -
        it is not a UI command that can be posted - and it is left in place
        until Restore View is pressed rather than reset on the way out.
        """
        from Autodesk.Revit.DB import Transaction

        uidoc, doc = self._doc(uiapp)
        view = None
        try:
            view = uidoc.ActiveView
        except Exception:
            view = None
        if view is None:
            raise ValueError('There is no active view to isolate in.')

        picked = payload.get('element_ids') or []
        collection = List[ElementId]()
        if picked:
            for value in picked:
                try:
                    collection.Add(ElementId(int(value)))
                except Exception:
                    continue
        else:
            ids = fv_model.instance_ids(
                doc,
                payload.get('type_ids', []),
                view=view,
                ignore_nested=payload.get('ignore_nested', True),
                phase_id=payload.get('phase_id'),
                phase_mode=payload.get('phase_mode', 'existing'))
            for element_id in ids:
                collection.Add(element_id)
        if not collection.Count:
            return {'count': 0, 'view_name': getattr(view, 'Name', '')}

        try:
            uidoc.Selection.SetElementIds(collection)
        except Exception:
            pass
        # zoom first: isolating first would zoom to a view that has already
        # been emptied of everything else, which is not the same framing
        try:
            uidoc.ShowElements(collection)
        except Exception:
            pass

        transaction = Transaction(doc, 'RevoBIM Family Viewer - isolate')
        transaction.Start()
        try:
            view.IsolateElementsTemporary(collection)
            transaction.Commit()
        except Exception:
            try:
                if transaction.HasStarted():
                    transaction.RollBack()
            except Exception:
                pass
            raise
        return {'count': collection.Count,
                'view_name': getattr(view, 'Name', '')}

    def _restore_view(self, uiapp, payload):
        """Reset Temporary Hide/Isolate on the active view."""
        from Autodesk.Revit.DB import Transaction, TemporaryViewMode

        uidoc, doc = self._doc(uiapp)
        view = None
        try:
            view = uidoc.ActiveView
        except Exception:
            view = None
        if view is None:
            return {'view_name': ''}

        transaction = Transaction(doc, 'RevoBIM Family Viewer - restore view')
        transaction.Start()
        try:
            view.DisableTemporaryViewMode(
                TemporaryViewMode.TemporaryHideIsolate)
            transaction.Commit()
        except Exception:
            try:
                if transaction.HasStarted():
                    transaction.RollBack()
            except Exception:
                pass
            raise
        return {'view_name': getattr(view, 'Name', '')}

    def _view_categories(self, uiapp, payload):
        uidoc, doc = self._doc(uiapp)
        view = None
        try:
            view = uidoc.ActiveView
        except Exception:
            view = None
        return {
            'ids': sorted(fv_model.categories_in_view(doc, view)),
            'view_name': getattr(view, 'Name', '') if view is not None else '',
        }

    def _apply(self, uiapp, payload):
        """Write the staged edits.

        One transaction for the whole run so a failure rolls back cleanly, with
        warnings deleted by a failure preprocessor.  Elements are borrowed
        first: a write to an element nobody has checked out writes nothing and
        says nothing, because Revit asks in a dialog and a run that suppresses
        dialogs answers it.  Every value is read back afterwards, because a
        void API call is not evidence.
        """
        from Autodesk.Revit.DB import Transaction, TransactionStatus

        uidoc, doc = self._doc(uiapp)
        edits = payload.get('edits', [])
        if not edits:
            return {'written': 0, 'problems': [], 'locked': []}

        wanted_ids = set()
        for edit in edits:
            try:
                wanted_ids.add(int(edit['id']))
            except Exception:
                continue

        meter = fv_core.ProgressMeter(payload.get('progress'), len(edits))
        meter.update('borrow', 0)
        locked = _borrow(doc, wanted_ids)
        meter.update('index', 0)

        # built once for the whole run, filled only if something needs them:
        # every instance of the edited types in one pass of the model, and
        # the project's worksets by name
        self._index = fv_model.InstanceIndex(
            doc, [edit['id'] for edit in edits
                  if edit.get('kind', 'type') == 'type' and
                  str(edit.get('id', '')).lstrip('-').isdigit()])
        self._worksets = None

        written = 0
        problems = []
        transaction = Transaction(doc, 'RevoBIM Family Viewer - apply changes')
        try:
            transaction.Start()
            try:
                transaction.SetFailureHandlingOptions(
                    _swallow_warnings(transaction))
            except Exception:
                pass

            for done, edit in enumerate(edits):
                meter.update('write', done)
                label = edit.get('label', '')
                try:
                    element_id = int(edit['id'])
                except Exception:
                    problems.append((label, 'the element id was not readable'))
                    continue
                if element_id in locked:
                    continue
                element = None
                try:
                    element = doc.GetElement(ElementId(element_id))
                except Exception:
                    element = None
                if element is None:
                    problems.append((label, 'the element is no longer there'))
                    continue

                if edit.get('key') == fv_model.KEY_NAME:
                    ok, why = fv_model.rename_element(element, edit.get('value'))
                elif edit.get('key') == fv_model.WORKSET_KEY:
                    ok, why = self._write_workset(doc, element, edit)
                else:
                    ok, why = self._write_value(doc, element, edit)
                if ok:
                    written += 1
                else:
                    problems.append((label, why))

            meter.update('write', len(edits))
            meter.update('commit', 0)
            status = transaction.Commit()
            meter.update('done')
            if status != TransactionStatus.Committed:
                return {'written': 0, 'problems': [
                    ('the whole run', 'Revit did not commit the transaction')],
                    'locked': sorted(locked)}
        except Exception:
            try:
                if transaction.HasStarted():
                    transaction.RollBack()
            except Exception:
                pass
            raise

        return {'written': written, 'problems': problems,
                'locked': sorted(locked)}

    def _write_workset(self, doc, element, edit):
        """A type does not sit on a workset - its instances do - so moving a
        type means moving every instance of it."""
        if self._worksets is None:
            self._worksets = fv_model.workset_ids(doc)
        ok, why = fv_model.set_workset(element, edit.get('value'), doc,
                                       self._worksets)
        if ok:
            return True, ''
        if 'does not sit on a workset' not in why:
            return False, why
        instances = self._index.of(edit['id'])
        if not instances:
            return False, 'nothing is placed, so there is nothing to move'
        done = 0
        last = ''
        for instance in instances:
            moved, said = fv_model.set_workset(instance, edit.get('value'),
                                               doc, self._worksets)
            if moved:
                done += 1
            else:
                last = said
        if done:
            return True, ''
        return False, last or 'no instance would move'

    def _write_value(self, doc, element, edit):
        """A parameter that lives on the type is written there; one that lives
        on the instance is written to every instance of that type, and the row
        says how many."""
        name = edit.get('key')
        value = edit.get('value')
        ok, why = fv_model.set_param(element, name, value, doc)
        if ok:
            return True, ''
        if 'does not carry' not in why:
            return False, why

        instances = self._index.of(edit['id'])
        if not instances:
            return False, 'nothing carries that parameter'
        done = 0
        last = ''
        for instance in instances:
            got, said = fv_model.set_param(instance, name, value, doc)
            if got:
                done += 1
            else:
                last = said
        if done:
            return True, ''
        return False, last or 'no instance would take that value'

    def _place(self, uiapp, payload):
        """Revit's own placement command, started on the chosen type.

        PostRequestForElementTypePlacement is the only way to hand the user the
        normal placement experience - snapping, hosting, the options bar - and
        it needs the symbol activated first, because an unactivated symbol
        cannot be placed and the request is refused with nothing said.
        """
        uidoc, doc = self._doc(uiapp)
        try:
            type_id = int(payload.get('type_id'))
        except Exception:
            raise ValueError('No type was picked.')
        element = doc.GetElement(ElementId(type_id))
        if element is None:
            raise ValueError('That type is no longer in the project.')

        name = fv_model.type_name_of(element)
        family = fv_model.family_name_of(element)

        activated = False
        try:
            if not element.IsActive:
                from Autodesk.Revit.DB import Transaction
                transaction = Transaction(doc, 'RevoBIM Family Viewer - activate type')
                transaction.Start()
                element.Activate()
                doc.Regenerate()
                transaction.Commit()
                activated = True
        except Exception:
            fv_core.log('could not activate the symbol:\n' + fv_core.format_exc())

        uidoc.PostRequestForElementTypePlacement(element)
        return {'name': name, 'family': family, 'activated': activated}


    def _doc(self, uiapp):
        uidoc = uiapp.ActiveUIDocument
        if uidoc is None:
            raise ValueError('There is no open document.')
        return uidoc, uidoc.Document

    def _lists(self, uiapp, payload):
        uidoc, doc = self._doc(uiapp)
        view = None
        try:
            view = uidoc.ActiveView
        except Exception:
            view = None
        return {
            'categories': fv_model.list_categories(
                doc,
                payload.get('include_system', False),
                payload.get('include_annotation', False)),
            'phases': fv_model.list_phases(doc),
            'worksets': fv_model.list_worksets(doc),
            'view_name': getattr(view, 'Name', '') if view is not None else '',
            'doc_title': getattr(doc, 'Title', ''),
        }

    def _read(self, uiapp, payload):
        uidoc, doc = self._doc(uiapp)
        scope = payload.get('scope', fv_model.SCOPE_PROJECT)

        # the active view is fetched for the view scope and for no other, and
        # fv_model.read drops it again if the scope does not want it - one
        # word decides it in both places rather than two flags that can
        # disagree
        view = None
        if scope == fv_model.SCOPE_VIEW:
            try:
                view = uidoc.ActiveView
            except Exception:
                view = None

        result = fv_model.read(
            doc,
            view=view,
            scope=scope,
            wanted_category_ids=payload.get('categories'),
            columns=payload.get('columns'),
            include_system=payload.get('include_system', False),
            include_annotation=payload.get('include_annotation', False),
            ignore_nested=payload.get('ignore_nested', True),
            phase_id=payload.get('phase_id'),
            phase_mode=payload.get('phase_mode', 'existing'),
            progress=payload.get('progress'))
        result.view_name = getattr(view, 'Name', '') if view is not None else ''
        return result

    def _preview(self, uiapp, payload):
        """Preview images, a handful at a time, so a model with two thousand
        types never stalls the window generating them all at once."""
        uidoc, doc = self._doc(uiapp)
        size = int(payload.get('size', 48))
        made = {}
        for type_id in payload.get('ids', [])[:PREVIEW_BATCH]:
            try:
                element = doc.GetElement(ElementId(int(type_id)))
            except Exception:
                element = None
            if element is None:
                made[type_id] = None
                continue
            made[type_id] = _preview_bitmap(element, size)
        return made

    def _select(self, uiapp, payload):
        uidoc, doc = self._doc(uiapp)
        view = None
        if payload.get('scope') == 'view':
            try:
                view = uidoc.ActiveView
            except Exception:
                view = None

        picked = payload.get('element_ids') or []
        collection = List[ElementId]()
        if picked:
            # elements picked one by one: those elements, not every instance of
            # their types.  The scope does not narrow them either - they were
            # named, and a name is more specific than a scope.
            for value in picked:
                try:
                    collection.Add(ElementId(int(value)))
                except Exception:
                    continue
        else:
            ids = fv_model.instance_ids(
                doc,
                payload.get('type_ids', []),
                view=view,
                ignore_nested=payload.get('ignore_nested', True),
                phase_id=payload.get('phase_id'),
                phase_mode=payload.get('phase_mode', 'existing'))
            for element_id in ids:
                collection.Add(element_id)
        try:
            uidoc.Selection.SetElementIds(collection)
        except Exception:
            raise
        if payload.get('zoom') and collection.Count:
            try:
                uidoc.ShowElements(collection)
            except Exception:
                pass
        return {'count': collection.Count,
                'scope': payload.get('scope'),
                'picked': bool(picked),
                'view_name': getattr(view, 'Name', '') if view is not None else ''}


# ---------------------------------------------------------------------------
# worksharing and warnings
# ---------------------------------------------------------------------------

def _borrow(doc, element_ids):
    """Check the elements out before the transaction starts.

    A write to an element another user has is refused, and in a run that
    suppresses dialogs it is refused SILENTLY - which reads exactly like Apply
    doing nothing.  Anything somebody else holds is reported by id instead.
    """
    locked = set()
    if not element_ids:
        return locked
    try:
        if not doc.IsWorkshared:
            return locked
    except Exception:
        return locked

    from Autodesk.Revit.DB import WorksharingUtils

    collection = List[ElementId]()
    for value in element_ids:
        try:
            collection.Add(ElementId(int(value)))
        except Exception:
            continue
    try:
        WorksharingUtils.CheckoutElements(doc, collection)
    except Exception:
        fv_core.log('CheckoutElements refused:\n' + fv_core.format_exc())

    for value in element_ids:
        try:
            element_id = ElementId(int(value))
        except Exception:
            continue
        try:
            status = WorksharingUtils.GetCheckoutStatus(doc, element_id)
            if str(status) == 'OwnedByOtherUser':
                locked.add(int(value))
                continue
        except Exception:
            pass
        # element ownership and workset ownership are two different locks, and
        # an element on a workset somebody else owns has a perfectly clean
        # checkout status - asking only one misses half the cases
        try:
            element = doc.GetElement(element_id)
            workset = doc.GetWorksetTable().GetWorkset(element.WorksetId)
            if workset.Owner:
                import getpass
                if str(workset.Owner) != str(getpass.getuser()):
                    locked.add(int(value))
        except Exception:
            pass
    return locked


def _swallow_warnings(transaction):
    """Warnings deleted, so a run is never stopped by one."""
    from Autodesk.Revit.DB import (FailureProcessingResult, IFailuresPreprocessor)

    class Swallower(IFailuresPreprocessor):
        def PreprocessFailures(self, accessor):
            try:
                for failure in accessor.GetFailureMessages():
                    accessor.DeleteWarning(failure)
            except Exception:
                pass
            return FailureProcessingResult.Continue

    options = transaction.GetFailureHandlingOptions()
    options.SetFailuresPreprocessor(Swallower())
    options.SetClearAfterRollback(True)
    return options


# ---------------------------------------------------------------------------
# preview images
# ---------------------------------------------------------------------------

def _preview_bitmap(element_type, size):
    """ElementType.GetPreviewImage hands back a System.Drawing.Bitmap.  It is
    saved to a MemoryStream as PNG and read back into a BitmapImage with
    BitmapCacheOption.OnLoad - never through BitmapImage.UriSource, because
    System.Uri moved assemblies and throws ImportError on 2025 and later, and
    because OnLoad is what lets the stream be closed straight away.
    """
    from System.Drawing import Size as DrawingSize
    from System.Drawing.Imaging import ImageFormat
    from System.IO import MemoryStream
    from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption

    bitmap = None
    try:
        bitmap = element_type.GetPreviewImage(DrawingSize(size, size))
    except Exception:
        bitmap = None
    if bitmap is None:
        return None

    stream = MemoryStream()
    try:
        bitmap.Save(stream, ImageFormat.Png)
        stream.Position = 0
        image = BitmapImage()
        image.BeginInit()
        image.CacheOption = BitmapCacheOption.OnLoad
        image.StreamSource = stream
        image.EndInit()
        try:
            image.Freeze()
        except Exception:
            pass
        return image
    except Exception:
        return None
    finally:
        try:
            stream.Dispose()
        except Exception:
            pass
        try:
            bitmap.Dispose()
        except Exception:
            pass


def build():
    """The handler and its ExternalEvent, parked by the caller so the
    persistent engine cannot collect them out from under the window."""
    handler = FamilyViewerHandler()
    event = ExternalEvent.Create(handler)
    return handler, event
