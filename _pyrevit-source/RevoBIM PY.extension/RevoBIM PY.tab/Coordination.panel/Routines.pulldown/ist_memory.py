# -*- coding: utf-8 -*-
u"""RevoBIM PY - Hide Service Type : the hide memory.

Revit's Temporary Hide is one layer per view: anyone's next temporary hide or
isolate, or Revit's own Reset, takes it all away, and it is gone when the model
closes.  This is the tool's own temporary hide instead:

- Host elements and whole links are hidden with Revit's own Hide in View, and
  only the ones that were NOT already hidden are written down - so putting
  them back never unhides something someone else hid on purpose.
- Linked rows are hidden by view filters (Revit will not hide a linked element
  by id), and the filter's rules are written down so it can be made again.
- The record lives in %APPDATA%\\RevoBIM\\hide_memory\\<model>.json, per view,
  and survives closing Revit.  The floating Reset Hide window reads it.

Reset puts back exactly what was recorded.  Hide again hides it again.
Forget drops the record (resetting first if it is still hidden).
"""

import ist_clr  # noqa: F401  - assemblies first, always

import os
import io
import json
import time

import ist_core
from ist_core import eid_value

MEMORY_DIR = os.path.join(ist_core.SETTINGS_DIR, u"hide_memory")

HIDDEN = u"hidden"
SHOWN = u"shown"


# ===========================================================================
# which model, which file
# ===========================================================================

def _fnv(text):
    u"""A short, stable hash of the model path for the file name - stable
    across sessions and engines, unlike Python's own hash()."""
    value = 0x811c9dc5
    for ch in text:
        value ^= ord(ch)
        value = (value * 0x01000193) & 0xffffffff
    return u"{0:08x}".format(value)


def model_key(doc):
    u"""The central model for a workshared model, the file for a local one,
    the title for an unsaved one - so every local copy of one central shares
    one memory."""
    path = u""
    try:
        if doc.IsWorkshared:
            from Autodesk.Revit.DB import ModelPathUtils
            central = doc.GetWorksharingCentralModelPath()
            path = ModelPathUtils.ConvertModelPathToUserVisiblePath(central)
    except Exception:
        path = u""
    if not path:
        try:
            path = doc.PathName or u""
        except Exception:
            path = u""
    if not path:
        try:
            path = u"unsaved:" + (doc.Title or u"")
        except Exception:
            path = u"unsaved"
    return path


def memory_path(key):
    title = os.path.basename(key.replace(u"\\", u"/")) or u"model"
    clean = u"".join(ch if ch.isalnum() or ch in u"-_ ." else u"_"
                     for ch in title)[:60].strip() or u"model"
    return os.path.join(MEMORY_DIR, u"{0}_{1}.json".format(clean, _fnv(key)))


# ===========================================================================
# the store
# ===========================================================================

def empty_store(key):
    return {u"model": key, u"last": None, u"views": {}}


def load(key):
    path = memory_path(key)
    try:
        if os.path.isfile(path):
            handle = io.open(path, u"r", encoding=u"utf-8")
            try:
                data = json.loads(handle.read())
            finally:
                handle.close()
            if isinstance(data, dict) and isinstance(data.get(u"views"), dict):
                data.setdefault(u"model", key)
                data.setdefault(u"last", None)
                return data
    except Exception:
        pass
    return empty_store(key)


def save(key, data):
    path = memory_path(key)
    try:
        folder = os.path.dirname(path)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        text = json.dumps(data, indent=1, sort_keys=True)
        if not isinstance(text, type(u"")):
            text = text.decode(u"utf-8")
        handle = io.open(path, u"w", encoding=u"utf-8")
        try:
            handle.write(text)
        finally:
            handle.close()
        return True
    except Exception:
        return False


def stamp(key):
    u"""When the file last changed - the window polls this rather than
    reading the file every second."""
    try:
        return os.path.getmtime(memory_path(key))
    except Exception:
        return 0


def _entry(data, view_uid, view_name):
    views = data.setdefault(u"views", {})
    entry = views.get(view_uid)
    if entry is None:
        entry = {u"name": view_name, u"host": [], u"links": [],
                 u"filters": {}, u"state": HIDDEN, u"time": 0}
        views[view_uid] = entry
    entry[u"name"] = view_name or entry.get(u"name") or u"?"
    entry.setdefault(u"host", [])
    entry.setdefault(u"links", [])
    entry.setdefault(u"filters", {})
    return entry


def merge(data, view_uid, view_name, host=(), links=(), filters=None,
          replace=False, template=None):
    u"""Write one run's hide into the view's record.  With `replace` (the
    default since 1.7.0) a new hide starts a new record - the caller has put
    the old one back first.  Without it, a second hide adds to the first."""
    entry = _entry(data, view_uid, view_name)
    if replace:
        entry[u"host"] = []
        entry[u"links"] = []
        entry[u"filters"] = {}
    entry[u"template"] = template or u""
    entry[u"host"] = sorted(set(entry[u"host"]) | set(int(i) for i in host))
    entry[u"links"] = sorted(set(entry[u"links"]) | set(int(i) for i in links))
    for name, spec in (filters or {}).items():
        entry[u"filters"][name] = spec
    entry[u"state"] = HIDDEN
    entry[u"time"] = time.time()
    data[u"last"] = view_uid
    return entry


def counts(entry):
    return (len(entry.get(u"host") or ()), len(entry.get(u"links") or ()),
            len(entry.get(u"filters") or {}))


def describe(entry):
    host, links, filters = counts(entry)
    parts = []
    if host:
        parts.append(u"{0} element{1}".format(host, u"" if host == 1 else u"s"))
    if links:
        parts.append(u"{0} link{1}".format(links, u"" if links == 1 else u"s"))
    if filters:
        parts.append(u"{0} linked filter{1}".format(
            filters, u"" if filters == 1 else u"s"))
    return u", ".join(parts) or u"nothing"


def ordered_views(data):
    u"""Most recent first."""
    items = list((data.get(u"views") or {}).items())
    items.sort(key=lambda kv: -(kv[1].get(u"time") or 0))
    return items


def remember(doc, view, host=(), links=(), filters=None, replace=False,
             template=None):
    u"""Called after a hide has committed."""
    if not host and not links and not filters:
        return None
    key = model_key(doc)
    data = load(key)
    try:
        uid = view.UniqueId
    except Exception:
        uid = u"{0}".format(eid_value(view.Id))
    entry = merge(data, uid, view.Name, host, links, filters, replace,
                  template)
    save(key, data)
    return entry


def filter_spec(rule, plan, label):
    u"""What it takes to make a linked-row filter again after a Forget or a
    reset that deleted it."""
    return {u"cat": rule.get(u"cat"), u"cat_name": rule.get(u"cat_name"),
            u"plan": [list(p) for p in plan], u"label": label}


# ===========================================================================
# Revit jobs - each runs inside the caller's API context
# ===========================================================================

def _ids(doc, values):
    from Autodesk.Revit.DB import ElementId
    out = []
    for value in values:
        element = doc.GetElement(ElementId(value))
        if element is not None:
            out.append(element)
    return out


def _is_hidden(element, view):
    try:
        return bool(element.IsHidden(view))
    except Exception:
        return False


def find_view(doc, view_uid):
    try:
        view = doc.GetElement(view_uid)
    except Exception:
        view = None
    return view


def reset_entry(doc, view, entry, report):
    u"""Put back exactly what was recorded.  Runs inside a transaction."""
    elements = _ids(doc, list(entry.get(u"host") or ()) +
                    list(entry.get(u"links") or ()))
    back = [e for e in elements if _is_hidden(e, view)]
    missing = len(entry.get(u"host") or ()) + \
        len(entry.get(u"links") or ()) - len(elements)
    shown = 0
    if back:
        try:
            view.UnhideElements(ist_core._net_ids(
                [eid_value(e.Id) for e in back]))
            shown = len(back)
        except Exception:
            # One awkward element must not keep the rest hidden.
            for element in back:
                try:
                    view.UnhideElements(ist_core._net_ids(
                        [eid_value(element.Id)]))
                    shown += 1
                except Exception:
                    continue
    removed = 0
    names = set((entry.get(u"filters") or {}).keys())
    if names:
        known = ist_core.existing_filters(doc)
        applied = set(eid_value(f) for f in view.GetFilters())
        for name in names:
            filter_id = known.get(name)
            if filter_id is not None and eid_value(filter_id) in applied:
                try:
                    view.RemoveFilter(filter_id)
                    removed += 1
                except Exception:
                    continue
    # Leave no orphan filters in the project; Hide again remakes them from
    # the rules written down.
    delete_unused_filters(doc, list(names))
    entry[u"state"] = SHOWN
    if shown:
        report.add(u"{0} element{1} shown again.".format(
            shown, u"" if shown == 1 else u"s"))
    if removed:
        report.add(u"{0} linked filter{1} taken off.".format(
            removed, u"" if removed == 1 else u"s"))
    if missing > 0:
        report.note(u"{0} remembered element{1} no longer in the model.".format(
            missing, u"" if missing == 1 else u"s"))
    return shown + removed


def redo_entry(doc, view, entry, values, report):
    u"""Hide the record again.  Runs inside a transaction."""
    elements = _ids(doc, list(entry.get(u"host") or ()) +
                    list(entry.get(u"links") or ()))
    again = []
    for element in elements:
        if _is_hidden(element, view):
            continue
        try:
            if not element.CanBeHidden(view):
                continue
        except Exception:
            pass
        again.append(eid_value(element.Id))
    if again:
        view.HideElements(ist_core._net_ids(again))
    made = 0
    specs = entry.get(u"filters") or {}
    if specs:
        known = ist_core.existing_filters(doc)
        shared = ist_core.shared_parameter_ids(doc)
        for name, spec in specs.items():
            try:
                filter_id = known.get(name)
                if filter_id is None:
                    plan = [tuple(p) for p in spec.get(u"plan") or ()]
                    filter_id = ist_core.make_filter(
                        doc, name, spec.get(u"cat"), plan, shared)
                    known[name] = filter_id
                applied = set(eid_value(f) for f in view.GetFilters())
                if eid_value(filter_id) not in applied:
                    view.AddFilter(filter_id)
                view.SetFilterVisibility(filter_id, False)
                made += 1
            except Exception as err:
                report.note(u"Not filtered - {0}: {1}".format(
                    spec.get(u"label") or name, err))
    entry[u"state"] = HIDDEN
    entry[u"time"] = time.time()
    if again:
        report.add(u"{0} element{1} hidden again.".format(
            len(again), u"" if len(again) == 1 else u"s"))
    if made:
        report.add(u"{0} linked filter{1} back on.".format(
            made, u"" if made == 1 else u"s"))
    return len(again) + made


def delete_unused_filters(doc, names):
    u"""Delete tool filters by name that no view or template still uses."""
    if not names:
        return 0
    known = ist_core.existing_filters(doc)
    targets = [known[n] for n in names if n in known]
    if not targets:
        return 0
    used = set()
    try:
        from Autodesk.Revit.DB import FilteredElementCollector, View
        for other in FilteredElementCollector(doc).OfClass(View):
            try:
                for filter_id in other.GetFilters():
                    used.add(eid_value(filter_id))
            except Exception:
                continue
    except Exception:
        return 0
    gone = 0
    for filter_id in targets:
        if eid_value(filter_id) in used:
            continue
        try:
            doc.Delete(filter_id)
            gone += 1
        except Exception:
            continue
    return gone


def run_job(doc, action, view_uid, values, report):
    u"""One button press from the window: "reset", "redo", "forget" or
    "reset_all".  Opens and closes its own transaction."""
    from Autodesk.Revit.DB import Transaction
    key = model_key(doc)
    data = load(key)
    views = data.get(u"views") or {}
    targets = list(views.keys()) if action == u"reset_all" else [view_uid]
    title = {u"reset": u"Reset Hide", u"redo": u"Hide again",
             u"forget": u"Forget hide", u"reset_all": u"Reset every hide"}
    trans = Transaction(doc, title.get(action, u"Reset Hide"))
    trans.Start()
    try:
        for uid in targets:
            entry = views.get(uid)
            if entry is None:
                continue
            view = find_view(doc, uid)
            if view is None:
                report.note(u"{0}: the view is no longer in the model - "
                            u"forgotten.".format(entry.get(u"name")))
                views.pop(uid, None)
                continue
            if action == u"redo":
                redo_entry(doc, view, entry, values, report)
            elif action in (u"reset", u"reset_all"):
                if entry.get(u"state") != SHOWN:
                    reset_entry(doc, view, entry, report)
            elif action == u"forget":
                if entry.get(u"state") != SHOWN:
                    reset_entry(doc, view, entry, report)
                delete_unused_filters(doc, list(
                    (entry.get(u"filters") or {}).keys()))
                views.pop(uid, None)
                report.add(u"{0}: forgotten.".format(entry.get(u"name")))
        trans.Commit()
    except Exception as err:
        try:
            trans.RollBack()
        except Exception:
            pass
        report.refused = u"Revit refused it: {0}".format(err)
        return report
    if data.get(u"last") not in views:
        ordered = ordered_views(data)
        data[u"last"] = ordered[0][0] if ordered else None
    save(key, data)
    return report


def reset_view_memory(doc, view, report):
    u"""The tool's other resets call this inside their own transaction, so
    every reset puts the remembered hide back too.

    Returns a function that writes the memory file - for the caller to call
    only after its transaction has committed, so the file never says "shown"
    for a hide Revit rolled back.  None when there was nothing to do."""
    key = model_key(doc)
    data = load(key)
    try:
        uid = view.UniqueId
    except Exception:
        return None
    entry = (data.get(u"views") or {}).get(uid)
    if entry is None or entry.get(u"state") == SHOWN:
        return None
    reset_entry(doc, view, entry, report)
    return lambda: save(key, data)


def view_is_hidden(doc, view):
    try:
        uid = view.UniqueId
    except Exception:
        return False
    entry = (load(model_key(doc)).get(u"views") or {}).get(uid)
    return entry is not None and entry.get(u"state") != SHOWN
