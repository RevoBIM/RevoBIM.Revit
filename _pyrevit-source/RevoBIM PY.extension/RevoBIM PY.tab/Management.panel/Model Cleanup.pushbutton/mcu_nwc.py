# -*- coding: utf-8 -*-
"""NWC export - every rule, no Revit.

The export runs first in Clean Up, on the model being cleaned, into the same
folder the copy is saved in. One primary 3D view is named after the model;
every other ticked view is a secondary named model_<view>.
"""
import re

import mcu_core as core

SOURCE_DEFAULTS = u"defaults"
SOURCE_CUSTOM = u"custom"

COORDINATES = [(u"shared", u"Shared"), (u"internal", u"Project internal")]
PARAMETERS = [(u"all", u"All"), (u"elements", u"Elements"), (u"none", u"None")]

BOOL_OPTIONS = core.NWC_BOOL_OPTIONS


def choice(value, options, default):
    value = core.to_text(value).strip().lower()
    return value if value in [key for key, _ in options] else default


def faceting(value):
    try:
        number = float(core.to_text(value).strip())
    except Exception:
        return 1.0
    return min(10.0, max(0.1, number))


def options_plan(template):
    """What to set on NavisworksExportOptions, as plain values. With the
    exporter defaults, only the view scope is set."""
    plan = {u"ExportScope": u"View"}
    if template.get(u"nwc_source") == SOURCE_DEFAULTS:
        return plan
    plan[u"Coordinates"] = u"Shared" if choice(
        template.get(u"nwc_coordinates"), COORDINATES, u"shared") == u"shared" else u"Internal"
    plan[u"Parameters"] = {u"all": u"All", u"elements": u"Elements", u"none": u"None"}[
        choice(template.get(u"nwc_parameters"), PARAMETERS, u"all")]
    plan[u"FacetingFactor"] = faceting(template.get(u"nwc_faceting"))
    for key, prop, _, default in BOOL_OPTIONS:
        plan[prop] = core.as_bool(template.get(key, default), default == u"1")
    return plan


# ============================================================
# which views
# ============================================================

def selection(template):
    views = core.split_retain(template.get(u"nwc_views"))
    primary = core.to_text(template.get(u"nwc_primary"))
    return normalise(views, primary)


def normalise(views, primary):
    """Ticked views, in natural order, and a primary that is one of them.
    A primary that is not ticked is ticked; no primary means the first."""
    views = [v for v in views if core.to_text(v).strip()]
    if primary and primary not in views:
        views.append(primary)
    views = sorted(set(views), key=core.natural_key)
    if not primary or primary not in views:
        primary = views[0] if views else u""
    return views, primary


def untick(views, primary, name):
    views = [v for v in views if v != name]
    if primary == name:
        primary = u""
    return normalise(views, primary)


def rows(names, search, views, only_selected=False):
    words = [w for w in core.to_text(search).lower().split() if w]
    chosen = set(views)
    out = []
    for name in sorted(set(names), key=core.natural_key):
        if only_selected and name not in chosen:
            continue
        if words and not all(w in name.lower() for w in words):
            continue
        out.append(name)
    return out


def safe_part(text):
    text = core.to_text(text)
    text = re.sub(u'[\\\\/:*?"<>|]', u"-", text)
    text = re.sub(u"\\s+", u" ", text).strip().strip(u".")
    return text or u"View"


def file_names(model_stem, views, primary):
    """[(view name, file name without .nwc)] - primary first, named after the
    model; secondaries named model_<view>. Clashes get a number."""
    stem = safe_part(core.model_stem(model_stem)) or u"Model"
    views, primary = normalise(views, primary)
    out = []
    used = set()
    ordered = ([primary] if primary else []) + [v for v in views if v != primary]
    for view in ordered:
        name = stem if view == primary else u"{0}_{1}".format(stem, safe_part(view))
        base, count = name, 2
        while name.lower() in used:
            name = u"{0} ({1})".format(base, count)
            count += 1
        used.add(name.lower())
        out.append((view, name))
    return out


def resolve(names_to_ids, planned):
    """Split the planned exports into found (view id, view, file) and the
    names this model does not have."""
    found, missing = [], []
    for view, file_name in planned:
        view_id = names_to_ids.get(view)
        if view_id:
            found.append((view_id, view, file_name))
        else:
            missing.append(view)
    return found, missing


def summary(views, primary, model_stem):
    if not views:
        return u"No 3D views ticked - NWC export will be skipped."
    names = file_names(model_stem, views, primary)
    text = u"{0} view(s). Primary: {1}. Files: {2}".format(
        len(views), primary, u", ".join(n + u".nwc" for _, n in names[:4]))
    if len(names) > 4:
        text += u" and {0} more".format(len(names) - 4)
    return text


def problems(template, available):
    """Reasons the export cannot run as set - empty when it can."""
    out = []
    if not core.as_bool(template.get(u"export_nwc")):
        return out
    if not available:
        out.append(u"The Navisworks exporter is not installed for this Revit.")
    views, _ = selection(template)
    if not views:
        out.append(u"NWC export is on, but no 3D view is ticked.")
    return out
