# -*- coding: utf-8 -*-
"""View templates from the Duplicate window: duplicate, rename, and edit a
template's properties in a window laid out like Revit's own View Templates
dialog - Parameter, Value, Include.

Reading happens in the window; every write goes out through TemplateHandler,
an external event the main window creates while Revit is running its command
(ExternalEvent.Create wants that context - a button click on a modeless
window is not it).
"""

import shtm_clr  # noqa: F401  - references the assemblies first

import traceback

import shtm_core
import shtm_model
import shtm_ui
import theme
from shtm_core import eid_value
from shtm_ui import ui_safe, styled, text_block

from Autodesk.Revit.DB import (
    FilteredElementCollector, Transaction, ElementTransformUtils,
    Transform, CopyPasteOptions, ElementId, StorageType, View,
)
from Autodesk.Revit.UI import IExternalEventHandler

from System.Collections.Generic import List as NetList
from System.Windows import (
    Thickness, Visibility, VerticalAlignment, HorizontalAlignment, TextTrimming,
)
from System.Windows.Controls import (
    Grid, TextBlock, TextBox, CheckBox, ComboBox, ComboBoxItem, Border,
)

# the parameters Revit edits through a dialog of its own (V/G overrides, view
# range, model display...) have no value the API can set; they keep their
# Include tick and say so
REVIT_ONLY = u"edit in Revit"

SCALE_PARAMS = ("VIEW_SCALE_PULLDOWN_METRIC", "VIEW_SCALE_PULLDOWN_IMPERIAL")
# Revit greys this one out in its own dialog: it follows View Scale
SCALE_FOLLOWS = ("VIEW_SCALE",)

ENUMS = {
    "VIEW_DETAIL_LEVEL": ("DetailLevel", "ViewDetailLevel",
                          [("Coarse", u"Coarse"), ("Medium", u"Medium"), ("Fine", u"Fine")]),
    "VIEW_DISCIPLINE": ("Discipline", "ViewDiscipline",
                        [("Architectural", u"Architectural"), ("Structural", u"Structural"),
                         ("Mechanical", u"Mechanical"), ("Electrical", u"Electrical"),
                         ("Plumbing", u"Plumbing"), ("Coordination", u"Coordination")]),
    "VIEW_PARTS_VISIBILITY": ("PartsVisibility", "PartsVisibility",
                              [("ShowPartsOnly", u"Show Parts"),
                               ("ShowOriginalOnly", u"Show Original"),
                               ("ShowPartsAndOriginal", u"Show Both")]),
}

# an element-id parameter whose current value is <none> still needs to know
# what it can be set to
ELEMENT_CLASSES = {"VIEW_PHASE_FILTER": "PhaseFilter", "VIEW_PHASE": "Phase"}

NONE_LABEL = u"<none>"

# the "Edit..." rows of Revit's dialog that this editor has a tab for
VG_TABS = {"VIS_GRAPHICS_MODEL": "model", "VIS_GRAPHICS_ANNOTATION": "annotation",
           "VIS_GRAPHICS_FILTERS": "filters", "PLAN_VIEW_RANGE": "range"}

# Model Display's visual style, by DisplayStyle member name
DISPLAY_STYLES = [("Wireframe", u"Wireframe"), ("HLR", u"Hidden Line"),
                  ("Shading", u"Shaded"), ("ShadingWithEdges", u"Shaded with edges"),
                  ("FlatColors", u"Consistent Colors"), ("Realistic", u"Realistic"),
                  ("RealisticWithEdges", u"Realistic with edges")]
DISPLAY_KEY = "display_style"

# view range planes and the relative levels a template uses
PLANES = [("TopClipPlane", u"Top"), ("CutPlane", u"Cut plane"),
          ("BottomClipPlane", u"Bottom"), ("ViewDepthPlane", u"View depth")]
RANGE_LEVELS = [("Current", u"Associated Level"), ("LevelAbove", u"Level Above"),
                ("LevelBelow", u"Level Below"), ("Unlimited", u"Unlimited")]


# ====================== reading ======================

def _bip_name(param):
    try:
        return u"{0}".format(param.Definition.BuiltInParameter)
    except Exception:
        return u""


def _is_yes_no(param):
    try:
        from Autodesk.Revit.DB import SpecTypeId
        return param.Definition.GetDataType() == SpecTypeId.Boolean.YesNo
    except Exception:
        return False


def _db_type(name):
    try:
        import Autodesk.Revit.DB as db
        return getattr(db, name)
    except Exception:
        return None


def _element_choices(doc, param, bip):
    """What an element-id parameter can be set to: everything of the class of
    what it holds now (or of the class it is known to hold), by name."""
    current = None
    try:
        current = doc.GetElement(param.AsElementId())
    except Exception:
        current = None
    cls = current.GetType() if current is not None else None
    if cls is None and bip in ELEMENT_CLASSES:
        cls = _db_type(ELEMENT_CLASSES[bip])
    if cls is None:
        return None
    choices = []
    try:
        for element in FilteredElementCollector(doc).OfClass(cls):
            choices.append((eid_value(element.Id), shtm_model.element_name(element)))
    except Exception:
        return None
    choices.sort(key=lambda c: shtm_core.natural_key(c[1]))
    if bip not in ELEMENT_CLASSES:
        choices.insert(0, (-1, NONE_LABEL))
    return choices


def template_rows(doc, template):
    """Every parameter the template can control, as Revit lists them:
    {"id", "name", "include", "kind", "value", "choices", "editable"}."""
    controlled = list(template.GetTemplateParameterIds())
    loose = set([eid_value(i) for i in template.GetNonControlledTemplateParameterIds()])
    params = {}
    for param in template.Parameters:
        try:
            params[eid_value(param.Id)] = param
        except Exception:
            continue
    rows = []
    for pid in controlled:
        key = eid_value(pid)
        param = params.get(key)
        row = {"id": key, "include": key not in loose, "kind": "revit",
               "value": REVIT_ONLY, "choices": None, "editable": False,
               "name": shtm_model.parameter_name_from_id(doc, pid) or u"{0}".format(key)}
        if param is None:
            rows.append(row)
            continue
        row["name"] = param.Definition.Name
        bip = _bip_name(param)
        try:
            storage = param.StorageType
        except Exception:
            storage = None
        read_only = False
        try:
            read_only = bool(param.IsReadOnly)
        except Exception:
            pass
        if bip in SCALE_PARAMS:
            row.update(kind="scale", value=shtm_core.scale_text(template.Scale),
                       editable=True)
        elif bip in SCALE_FOLLOWS:
            row.update(kind="text", value=shtm_model.param_text(param), editable=False)
        elif bip in ENUMS:
            prop, _enum, labels = ENUMS[bip]
            current = u""
            try:
                current = u"{0}".format(getattr(template, prop))
            except Exception:
                pass
            shown = dict(labels).get(current, current)
            row.update(kind="enum", value=shown, editable=True,
                       choices=[(name, label) for name, label in labels])
            row["bip"] = bip
        elif storage == StorageType.ElementId:
            choices = _element_choices(doc, param, bip)
            # shown by the element's own name, the same text the choices use
            current = NONE_LABEL
            try:
                held = doc.GetElement(param.AsElementId())
                if held is not None:
                    current = shtm_model.element_name(held)
            except Exception:
                pass
            row.update(kind="element", value=current, choices=choices,
                       editable=bool(choices) and not read_only)
        elif storage == StorageType.Integer and _is_yes_no(param):
            row.update(kind="yesno", value=u"Yes" if param.AsInteger() == 1 else u"No",
                       choices=[(1, u"Yes"), (0, u"No")], editable=not read_only)
        elif storage in (StorageType.String, StorageType.Double):
            row.update(kind="text", value=shtm_model.param_text(param),
                       editable=not read_only)
        elif storage == StorageType.Integer:
            # an integer on a template is almost always a list of choices
            # (Show Hidden Lines, Far Clipping...). Neither a typed value nor
            # SetValueString sets one, so the choices are the values this
            # project already uses for it, read from every view: each comes
            # with the number Revit stores and the text it shows
            row.update(kind="intchoice", value=shtm_model.param_text(param),
                       current_int=param.AsInteger(), editable=False,
                       read_only=read_only)
        if bip in VG_TABS:
            row.update(kind="tab", tab=VG_TABS[bip], value=u"Edit...", editable=False)
        rows.append(row)
    _fill_int_choices(doc, rows)
    display = _display_row(template)
    if display is not None:
        rows.insert(0, display)
    # Revit's own order is kept
    return rows


def _fill_int_choices(doc, rows):
    """Choices for the integer rows from every view and template in the
    project: (stored number, shown text). Editable once there are two."""
    wanted = [r for r in rows if r["kind"] == "intchoice"]
    if not wanted:
        return
    try:
        from System import Enum
        from Autodesk.Revit.DB import BuiltInParameter
    except Exception:
        return
    seen = dict([(r["id"], {}) for r in wanted])
    members = {}
    for row in wanted:
        try:
            members[row["id"]] = Enum.ToObject(BuiltInParameter, row["id"])
        except Exception:
            continue
    try:
        views = list(FilteredElementCollector(doc).OfClass(View))
    except Exception:
        views = []
    for view in views:
        for key in members:
            try:
                param = view.get_Parameter(members[key])
                if param is None or not param.HasValue:
                    continue
                number = param.AsInteger()
                if number not in seen[key]:
                    text = param.AsValueString() or u"{0}".format(number)
                    seen[key][number] = text
            except Exception:
                continue
    for row in wanted:
        choices = seen.get(row["id"], {})
        if row.get("current_int") is not None and row["current_int"] not in choices:
            choices[row["current_int"]] = row["value"] or u"{0}".format(row["current_int"])
        pairs = sorted(choices.items(), key=lambda pair: pair[0])
        row["choices"] = [(number, text) for number, text in pairs]
        row["editable"] = len(pairs) > 1 and not row.get("read_only")
        if not row["value"] and row.get("current_int") in choices:
            row["value"] = choices[row["current_int"]]


def _display_row(template):
    """The visual style (Model Display's Style), as a row of its own: Revit
    keeps it inside the Graphic Display Options dialog."""
    current = u""
    try:
        current = u"{0}".format(template.DisplayStyle)
    except Exception:
        current = u""
    if current not in dict(DISPLAY_STYLES):
        return None
    shown = dict(DISPLAY_STYLES).get(current, current)
    return {"id": DISPLAY_KEY, "name": u"Visual Style (Model Display)", "include": None,
            "kind": "display", "value": shown, "editable": bool(current),
            "choices": list(DISPLAY_STYLES)}


def category_rows(doc, template, kind):
    """The top-level categories of `kind` ("Model" or "Annotation") that the
    template can show or hide: {"id", "name", "visible", "halftone"}."""
    rows = []
    try:
        categories = list(doc.Settings.Categories)
    except Exception:
        return rows
    for category in categories:
        try:
            if u"{0}".format(category.CategoryType) != kind:
                continue
            if not template.CanCategoryBeHidden(category.Id):
                continue
            visible = not template.GetCategoryHidden(category.Id)
            halftone = bool(template.GetCategoryOverrides(category.Id).Halftone)
        except Exception:
            continue
        rows.append({"id": eid_value(category.Id), "name": category.Name,
                     "visible": visible, "halftone": halftone})
    rows.sort(key=lambda r: shtm_core.natural_key(r["name"]))
    return rows


def filter_rows(doc, template):
    """The filters on the template: {"id", "name", "enabled", "visible",
    "halftone"} - enabled is a 2021+ setting and reads as on before it."""
    rows = []
    try:
        ids = list(template.GetFilters())
    except Exception:
        return rows
    for filter_id in ids:
        element = doc.GetElement(filter_id)
        if element is None:
            continue
        enabled = True
        try:
            enabled = bool(template.GetIsFilterEnabled(filter_id))
        except Exception:
            pass
        try:
            visible = bool(template.GetFilterVisibility(filter_id))
            halftone = bool(template.GetFilterOverrides(filter_id).Halftone)
        except Exception:
            continue
        rows.append({"id": eid_value(filter_id), "name": shtm_model.element_name(element),
                     "enabled": enabled, "visible": visible, "halftone": halftone})
    return rows


def filters_available(doc, template, applied):
    """Every filter in the project not already on the template, by name."""
    out = []
    try:
        # rule-based filters only: Revit will not put a selection filter on
        # a view template
        from Autodesk.Revit.DB import ParameterFilterElement
        for element in FilteredElementCollector(doc).OfClass(ParameterFilterElement):
            key = eid_value(element.Id)
            if key in applied:
                continue
            out.append((key, shtm_model.element_name(element)))
    except Exception:
        pass
    out.sort(key=lambda pair: shtm_core.natural_key(pair[1]))
    return out


def _range_level_key(level_id):
    try:
        from Autodesk.Revit.DB import PlanViewRange
        for key, _label in RANGE_LEVELS:
            if eid_value(getattr(PlanViewRange, key)) == eid_value(level_id):
                return key
    except Exception:
        pass
    return None


def range_rows(doc, template):
    """A plan template's view range, plane by plane: {"plane", "label",
    "level", "level_label", "offset_text"} - or None for a template that has
    none (sections, 3D, schedules...)."""
    try:
        from Autodesk.Revit.DB import PlanViewPlane
        view_range = template.GetViewRange()
    except Exception:
        return None
    rows = []
    for plane_name, label in PLANES:
        try:
            plane = getattr(PlanViewPlane, plane_name)
            level_id = view_range.GetLevelId(plane)
            key = _range_level_key(level_id)
            if key is None:
                level = doc.GetElement(level_id)
                key = u"id:{0}".format(eid_value(level_id))
                level_label = shtm_model.element_name(level) if level else u"(a level)"
            else:
                level_label = dict(RANGE_LEVELS)[key]
            rows.append({"plane": plane_name, "label": label, "level": key,
                         "level_label": level_label,
                         "offset_text": shtm_core.mm_text(view_range.GetOffset(plane))})
        except Exception:
            continue
    return rows


def views_using(doc, template_id):
    """How many views have this template assigned - Revit's own count."""
    count = 0
    try:
        for view in FilteredElementCollector(doc).OfClass(View):
            try:
                if not view.IsTemplate and eid_value(view.ViewTemplateId) == template_id:
                    count += 1
            except Exception:
                continue
    except Exception:
        pass
    return count


def taken_names(doc):
    """Every view and template name, lower case: a new template name has to
    miss them all."""
    names = set()
    try:
        for view in FilteredElementCollector(doc).OfClass(View):
            names.add(shtm_model.element_name(view).strip().lower())
    except Exception:
        pass
    return names


# ====================== writing ======================

def _set_name(element, name):
    try:
        element.Name = name
    except Exception:
        return False
    return shtm_model.element_name(element) == name


def duplicate_template(doc, template, name):
    """A copy of the template under `name`. CopyElements is the route that
    works for templates on every release; View.Duplicate is the fallback."""
    new_id = None
    try:
        ids = NetList[ElementId]()
        ids.Add(template.Id)
        copied = ElementTransformUtils.CopyElements(doc, ids, doc, Transform.Identity,
                                                    CopyPasteOptions())
        # the copy is the view template among what came back
        for item in copied:
            element = doc.GetElement(item)
            try:
                if element is not None and element.IsTemplate:
                    new_id = item
                    break
            except Exception:
                continue
    except Exception:
        new_id = None
    if new_id is None:
        from Autodesk.Revit.DB import ViewDuplicateOption
        new_id = template.Duplicate(ViewDuplicateOption.Duplicate)
    copy = doc.GetElement(new_id)
    if not _set_name(copy, name):
        raise Exception(u"the copy was made but would not take the name '{0}'".format(name))
    return eid_value(new_id)


def write_value(doc, template, row, text):
    """One value onto the template. Returns None, or why it would not go."""
    params = dict([(eid_value(p.Id), p) for p in template.Parameters])
    param = params.get(row["id"])
    kind = row["kind"]
    try:
        if kind == "scale":
            scale = shtm_core.parse_scale(text)
            if scale is None:
                return u"'{0}' is not a scale - type 1 : 50 or 50".format(text)
            template.Scale = scale
            return None
        if kind == "enum":
            prop, enum_name, labels = ENUMS[row["bip"]]
            wanted = [name for name, label in labels if label == text]
            enum = _db_type(enum_name)
            if not wanted or enum is None:
                return u"'{0}' is not one of the choices".format(text)
            setattr(template, prop, getattr(enum, wanted[0]))
            return None
        if kind == "display":
            wanted = [name for name, label in DISPLAY_STYLES if label == text]
            enum = _db_type("DisplayStyle")
            if not wanted or enum is None:
                return u"'{0}' is not one of the choices".format(text)
            template.DisplayStyle = getattr(enum, wanted[0])
            return None
        if param is None:
            return u"Revit no longer lists this parameter on the template"
        if kind == "intchoice":
            numbers = [n for n, label in (row.get("choices") or []) if label == text]
            if not numbers:
                return u"'{0}' is not one of the choices".format(text)
            if not param.Set(int(numbers[0])):
                return u"Revit would not take '{0}'".format(text)
            return None
        if kind == "element":
            ids = [i for i, label in (row.get("choices") or []) if label == text]
            if not ids:
                return u"'{0}' is not one of the choices".format(text)
            if not param.Set(shtm_model.new_element_id(ids[0]) if ids[0] > 0
                             else ElementId.InvalidElementId):
                return u"Revit would not take '{0}'".format(text)
            return None
        if kind == "yesno":
            if not param.Set(1 if text == u"Yes" else 0):
                return u"Revit would not take '{0}'".format(text)
            return None
        if kind == "text":
            if param.StorageType == StorageType.String:
                if not param.Set(text):
                    return u"Revit would not take '{0}'".format(text)
                return None
            if param.SetValueString(text):
                return None
            try:
                if param.Set(float(text)):
                    return None
            except Exception:
                pass
            return u"Revit would not take '{0}'".format(text)
    except Exception as exc:
        return u"{0}".format(exc) or u"Revit would not take it"
    return u"this one is edited in Revit's own View Templates dialog"


class TemplateHandler(IExternalEventHandler):
    """Duplicate, rename or edit a view template, in one transaction each."""

    def __init__(self):
        # a queue, not a slot: a second job asked for while the first is
        # still waiting for Revit must not overwrite it
        self.jobs = []

    def Execute(self, uiapp):
        jobs = list(self.jobs)
        del self.jobs[:]
        for job in jobs:
            self._one(uiapp, job)

    def _one(self, uiapp, job):
        report = {"ok": False, "problems": [], "refused": {}, "id": job.get("id"),
                  "name": None}
        transaction = None
        try:
            doc, refused = shtm_ui.job_document(uiapp, job)
            if refused:
                raise Exception(refused)
            template = doc.GetElement(shtm_model.new_element_id(job["id"]))
            if template is None:
                raise Exception(u"the view template is no longer in the model")
            action = job["action"]
            transaction = Transaction(doc, u"RevoBIM - {0} view template".format(action))
            transaction.Start()
            if action == "duplicate":
                report["id"] = duplicate_template(doc, template, job["name"])
                report["name"] = job["name"]
            elif action == "rename":
                if not _set_name(template, job["name"]):
                    raise Exception(u"Revit would not take the name '{0}' - it may "
                                    u"be in use".format(job["name"]))
                report["name"] = job["name"]
            elif action == "edit":
                self._edit(doc, template, job, report)
            status = transaction.Commit()
            if u"{0}".format(status) != u"Committed":
                raise Exception(u"Revit did not keep the change ({0})".format(status))
            report["ok"] = True
        except Exception as exc:
            try:
                if transaction is not None and transaction.HasStarted():
                    transaction.RollBack()
            except Exception:
                pass
            report["problems"].append(u"{0}".format(exc))
            shtm_ui.log(u"view template job failed:\n" + traceback.format_exc())
        callback = job.get("done")
        if callback is not None:
            try:
                callback(report)
            except Exception:
                shtm_ui.log(u"the view template callback failed")

    def _edit(self, doc, template, job, report):
        changes = job["changes"]
        if changes.get("name"):
            if _set_name(template, changes["name"]):
                report["name"] = changes["name"]
            else:
                report["problems"].append(u"Revit would not take the name '{0}' - it "
                                          u"may be in use".format(changes["name"]))
        if changes.get("include"):
            loose = set([eid_value(i) for i in
                         template.GetNonControlledTemplateParameterIds()])
            for key, on in changes["include"].items():
                if on:
                    loose.discard(key)
                else:
                    loose.add(key)
            ids = NetList[ElementId]()
            for key in sorted(loose):
                ids.Add(shtm_model.new_element_id(key))
            template.SetNonControlledTemplateParameterIds(ids)
        rows = dict([(r["id"], r) for r in job["rows"]])
        for key, text in changes.get("values", {}).items():
            row = rows.get(key)
            if row is None:
                continue
            why = write_value(doc, template, row, text)
            if why:
                report["refused"][key] = why
        self._categories(template, changes.get("categories") or {}, report)
        self._filters(template, changes.get("filters") or {}, report)
        self._range(template, changes.get("range") or {}, report)

    def _categories(self, template, edits, report):
        """Visibility and halftone per category, as V/G's Model and Annotation
        tabs set them."""
        for key, change in edits.items():
            category_id = shtm_model.new_element_id(key)
            try:
                if "visible" in change:
                    template.SetCategoryHidden(category_id, not change["visible"])
                if "halftone" in change:
                    settings = template.GetCategoryOverrides(category_id)
                    settings.SetHalftone(change["halftone"])
                    template.SetCategoryOverrides(category_id, settings)
            except Exception as exc:
                report["refused"][u"cat:{0}".format(key)] = u"{0}".format(exc)

    def _filters(self, template, edits, report):
        """Filters added, taken off, and each one's enabled, visible and
        halftone - the V/G Filters tab."""
        for key in edits.get("remove", []):
            try:
                template.RemoveFilter(shtm_model.new_element_id(key))
            except Exception as exc:
                report["refused"][u"filter:{0}".format(key)] = u"{0}".format(exc)
        for key in edits.get("add", []):
            try:
                template.AddFilter(shtm_model.new_element_id(key))
            except Exception as exc:
                report["refused"][u"filter:{0}".format(key)] = u"{0}".format(exc)
        for key, change in (edits.get("set") or {}).items():
            filter_id = shtm_model.new_element_id(key)
            try:
                if "enabled" in change:
                    template.SetIsFilterEnabled(filter_id, change["enabled"])
                if "visible" in change:
                    template.SetFilterVisibility(filter_id, change["visible"])
                if "halftone" in change:
                    settings = template.GetFilterOverrides(filter_id)
                    settings.SetHalftone(change["halftone"])
                    template.SetFilterOverrides(filter_id, settings)
            except Exception as exc:
                report["refused"][u"filter:{0}".format(key)] = u"{0}".format(exc)

    def _range(self, template, edits, report):
        """The view range, plane by plane, then set back in one go."""
        if not edits:
            return
        try:
            from Autodesk.Revit.DB import PlanViewPlane, PlanViewRange
            view_range = template.GetViewRange()
            for plane_name, change in edits.items():
                plane = getattr(PlanViewPlane, plane_name)
                if "level" in change:
                    key = change["level"]
                    if key.startswith(u"id:"):
                        level_id = shtm_model.new_element_id(int(key[3:]))
                    else:
                        level_id = getattr(PlanViewRange, key)
                    view_range.SetLevelId(plane, level_id)
                if "offset" in change:
                    view_range.SetOffset(plane, change["offset"])
            template.SetViewRange(view_range)
        except Exception as exc:
            report["refused"][u"range"] = u"{0}".format(exc)

    def GetName(self):
        return "RevoBIM Sheet Manager - view templates"


# ====================== the editor window ======================

W_INCLUDE = 70.0
W_VALUE = 240.0

TAB_BUTTONS = [("props", "TabProps"), ("model", "TabModel"),
               ("annotation", "TabAnnotation"), ("filters", "TabFilters"),
               ("range", "TabRange")]


class TemplateEditor(object):
    """Revit's View Templates dialog for one template, with the parts Revit
    hides behind "Edit..." given tabs of their own:

        Properties      every parameter the template controls - Value and
                        Include - plus its visual style
        V/G Model       each model category: visible, halftone
        V/G Annotation  each annotation category: visible, halftone
        V/G Filters     the filters on it: enabled, visible, halftone; add
                        a filter or take one off
        View Range      a plan template's top, cut, bottom and view depth

    Nothing is written until Apply, and then only what changed, in one
    transaction."""

    def __init__(self, doc, template_id, run_job, mode="auto", owner=None,
                 saved=None):
        self.doc = doc
        self.template_id = template_id
        self.run_job = run_job
        self.mode = mode
        self.owner = owner
        self.saved = saved
        self.rows = []
        self.edits = {}
        self.includes = {}
        self.controls = {}
        self.lines = {}
        self.refused = {}
        self.busy = False
        self.tab = "props"
        self.list_lines = []
        self.watchdog = None
        self.name = u""
        self.categories = {"model": [], "annotation": []}
        self.cat_edits = {"model": {}, "annotation": {}}
        self.filters = []
        self.filter_edits = {}
        self.filter_add = []
        self.filter_remove = set()
        self.ranges = None
        self.range_edits = {}
        self.window = shtm_ui.load_window("ShtmTemplate.xaml", mode)
        self.find = self.window.FindName
        self.chrome = shtm_ui.Chrome(self.window, busy=lambda: self.busy)
        shtm_ui.load_icon(self.find("LogoImage"))
        shtm_ui.attach_egg(self.window, self.find("LogoHost"), lambda: self.mode)
        self.find("VersionText").Text = u"v{0}".format(shtm_core.__version__)
        self.find("ThemeChip").Content = theme.label(mode)
        self._wire()
        self.read()

    def _wire(self):
        pairs = [("ApplyBtn", self._apply), ("CloseBtnFooter", self._close),
                 ("ThemeChip", self._cycle_theme),
                 ("IncludeAllBtn", lambda s, e: self._include_all(True)),
                 ("IncludeNoneBtn", lambda s, e: self._include_all(False))]
        for key, name in TAB_BUTTONS:
            pairs.append((name, self._tab_clicked(key)))
        for name, action in pairs:
            try:
                self.find(name).Click += ui_safe(action)
            except Exception:
                shtm_ui.log(u"template editor: could not wire {0}".format(name))
        try:
            self.find("ParamSearch").TextChanged += ui_safe(lambda s, e: self._filter())
            self.find("TemplateName").TextChanged += ui_safe(lambda s, e: self._paint_apply())
        except Exception:
            shtm_ui.log(u"template editor: could not wire the search")

    # ---- reading ----

    def read(self):
        template = self.doc.GetElement(shtm_model.new_element_id(self.template_id))
        if template is None:
            self.find("StatusText").Text = u"this view template is no longer in the model"
            self.find("ApplyBtn").IsEnabled = False
            return
        self.name = shtm_model.element_name(template)
        self.find("TemplateName").Text = self.name
        self.find("SubTitle").Text = u"Edit view template"
        self.find("UsingText").Text = u"Number of views with this template assigned:  {0}".format(
            views_using(self.doc, self.template_id))
        self.rows = template_rows(self.doc, template)
        self.edits = dict([(r["id"], r["value"]) for r in self.rows])
        self.includes = dict([(r["id"], r["include"]) for r in self.rows
                              if r["include"] is not None])
        self.categories = {"model": category_rows(self.doc, template, "Model"),
                           "annotation": category_rows(self.doc, template, "Annotation")}
        self.cat_edits = {"model": {}, "annotation": {}}
        self.filters = filter_rows(self.doc, template)
        self.filter_edits = {}
        self.filter_add = []
        self.filter_remove = set()
        self.ranges = range_rows(self.doc, template)
        self.range_edits = {}
        self._build()
        self._show_tab(self.tab)

    def _build(self):
        host = self.find("RowsHost")
        host.Children.Clear()
        self.controls = {}
        self.lines = {}
        for index, row in enumerate(self.rows):
            line = Grid()
            for width in (None, W_VALUE, W_INCLUDE):
                line.ColumnDefinitions.Add(shtm_ui._column(width))
            shell = _row_shell(index)
            name = text_block(row["name"], "Lbl.Body")
            name.TextTrimming = TextTrimming.CharacterEllipsis
            name.ToolTip = row["name"]
            line.Children.Add(name)
            control = self._value_control(row)
            Grid.SetColumn(control, 1)
            line.Children.Add(control)
            tick = None
            if row["include"] is not None:
                tick = _tick(row["include"])
                tick.Checked += self._include_ticked(row["id"], True)
                tick.Unchecked += self._include_ticked(row["id"], False)
                Grid.SetColumn(tick, 2)
                line.Children.Add(tick)
            shell.Child = line
            host.Children.Add(shell)
            self.lines[row["id"]] = (shell, name, tick)

    def _value_control(self, row):
        if row["kind"] == "tab":
            # Revit's "Edit..." button: here it opens the tab that edits it
            button = shtm_ui.button(u"Edit...", "Btn.Flat")
            button.Margin = Thickness(0, 0, 8, 0)
            button.Height = 26
            button.Click += self._tab_clicked(row["tab"])
            return button
        if row["editable"] and row.get("choices"):
            labels = [label for _key, label in row["choices"]]
            box = _combo(labels, row["value"])
            box.Margin = Thickness(0, 0, 8, 0)
            box.SelectionChanged += self._picked(row["id"], labels)
            self.controls[row["id"]] = box
            return box
        if row["editable"]:
            box = shtm_ui.text_box(u"", None, "Txt.Field")
            box.Text = row["value"]
            box.Height = 26
            box.MinHeight = 0
            box.Margin = Thickness(0, 0, 8, 0)
            box.TextChanged += self._typed(row["id"])
            self.controls[row["id"]] = box
            return box
        shown = text_block(row["value"] or REVIT_ONLY, "Lbl.Muted")
        shown.TextTrimming = TextTrimming.CharacterEllipsis
        shown.ToolTip = (u"Revit edits this only in its own View Templates dialog - "
                         u"the Include tick still works here")
        return shown

    # ---- tabs ----

    def _tab_clicked(self, key):
        def handler(sender, event):
            self._show_tab(key)
        return ui_safe(handler)

    def _show_tab(self, key):
        self.tab = key
        props = key == "props"
        self.find("PropsPane").Visibility = Visibility.Visible if props else Visibility.Collapsed
        self.find("ListPane").Visibility = Visibility.Collapsed if props else Visibility.Visible
        for name in ("IncludeAllBtn", "IncludeNoneBtn"):
            self.find(name).Visibility = Visibility.Visible if props else Visibility.Collapsed
        for tab_key, name in TAB_BUTTONS:
            self.find(name).SetResourceReference(
                _foreground(), "OrangeBrush" if tab_key == key else "MutedBrush")
        self.find("ParamSearch").Text = u""
        if key in ("model", "annotation"):
            self._build_categories(key)
        elif key == "filters":
            self._build_filters()
        elif key == "range":
            self._build_range()
        self._paint_apply()

    def _list_header(self, columns):
        header = self.find("ListHeader")
        header.ColumnDefinitions.Clear()
        header.Children.Clear()
        for index, (label, width) in enumerate(columns):
            header.ColumnDefinitions.Add(shtm_ui._column(width))
            caption = text_block(label, "Lbl.Section")
            if index:
                caption.HorizontalAlignment = HorizontalAlignment.Center
            Grid.SetColumn(caption, index)
            header.Children.Add(caption)

    def _list_line(self, index, widths):
        line = Grid()
        for width in widths:
            line.ColumnDefinitions.Add(shtm_ui._column(width))
        shell = _row_shell(index)
        shell.Child = line
        return shell, line

    # ---- V/G Model and Annotation ----

    def _build_categories(self, key):
        tools = self.find("ListTools")
        tools.Children.Clear()
        tools.Children.Add(text_block(
            u"Each {0} category the template can show or hide. Untick Visible to "
            u"hide it; Halftone greys it out.".format(
                u"model" if key == "model" else u"annotation"), "Lbl.Muted"))
        widths = (None, 90.0, 90.0)
        self._list_header([(u"Category", None), (u"Visible", 90.0), (u"Halftone", 90.0)])
        host = self.find("ListHost")
        host.Children.Clear()
        self.list_lines = []
        edits = self.cat_edits[key]
        for index, row in enumerate(self.categories[key]):
            shell, line = self._list_line(index, widths)
            name = text_block(row["name"], "Lbl.Body")
            name.TextTrimming = TextTrimming.CharacterEllipsis
            line.Children.Add(name)
            for column, field in ((1, "visible"), (2, "halftone")):
                tick = _tick(edits.get(row["id"], {}).get(field, row[field]))
                tick.Checked += self._flag(edits, row["id"], field, True)
                tick.Unchecked += self._flag(edits, row["id"], field, False)
                Grid.SetColumn(tick, column)
                line.Children.Add(tick)
            host.Children.Add(shell)
            self.list_lines.append((shell, row["name"]))
        if not self.categories[key]:
            host.Children.Add(text_block(u"   Revit lists none for this template.",
                                         "Lbl.Muted"))

    def _flag(self, edits, key, field, on):
        @ui_safe
        def handler(sender, event):
            edits.setdefault(key, {})[field] = on
            self._paint_apply()
        return handler

    # ---- V/G Filters ----

    def _build_filters(self):
        tools = self.find("ListTools")
        tools.Children.Clear()
        applied = set([r["id"] for r in self.filters]) | set(self.filter_add)
        available = filters_available(self.doc, None, applied)
        bar = Grid()
        bar.ColumnDefinitions.Add(shtm_ui._column(None))
        bar.ColumnDefinitions.Add(shtm_ui._column("auto"))
        picker = shtm_ui.ValuePicker([name for _key, name in available], u"",
                                     strict=True, placeholder=u"pick a filter to add")
        bar.Children.Add(picker.root)
        add = shtm_ui.button(u"Add filter", "Btn.Flat", (8, 0, 0, 0))
        add.Click += ui_safe(lambda s, e: self._add_filter(picker, available))
        Grid.SetColumn(add, 1)
        bar.Children.Add(add)
        tools.Children.Add(bar)
        widths = (None, 80.0, 80.0, 80.0, 44.0)
        self._list_header([(u"Filter", None), (u"Enabled", 80.0), (u"Visible", 80.0),
                           (u"Halftone", 80.0), (u"", 44.0)])
        host = self.find("ListHost")
        host.Children.Clear()
        self.list_lines = []
        names = dict(available)
        shown = list(self.filters) + [
            {"id": key, "name": names.get(key) or self._filter_name(key), "enabled": True,
             "visible": True, "halftone": False, "adding": True}
            for key in self.filter_add]
        for index, row in enumerate(shown):
            shell, line = self._list_line(index, widths)
            removing = row["id"] in self.filter_remove
            label = row["name"] + (u"   (adding)" if row.get("adding") else u"") + \
                (u"   (taking off)" if removing else u"")
            name = text_block(label, "Lbl.Body")
            name.TextTrimming = TextTrimming.CharacterEllipsis
            if row.get("adding"):
                name.SetResourceReference(TextBlock.ForegroundProperty, "OrangeBrush")
            elif removing:
                name.SetResourceReference(TextBlock.ForegroundProperty, "RedBrush")
            line.Children.Add(name)
            if not row.get("adding"):
                for column, field in ((1, "enabled"), (2, "visible"), (3, "halftone")):
                    tick = _tick(self.filter_edits.get(row["id"], {}).get(field, row[field]))
                    tick.IsEnabled = not removing
                    tick.Checked += self._flag(self.filter_edits, row["id"], field, True)
                    tick.Unchecked += self._flag(self.filter_edits, row["id"], field, False)
                    Grid.SetColumn(tick, column)
                    line.Children.Add(tick)
            drop = shtm_ui.button(u"↺" if (removing or row.get("adding")) else u"✕",
                                  "Btn.Flat")
            drop.ToolTip = (u"Keep it" if removing else u"Don't add it" if row.get("adding")
                            else u"Take this filter off the template")
            drop.Click += self._toggle_filter(row["id"], bool(row.get("adding")))
            Grid.SetColumn(drop, 4)
            line.Children.Add(drop)
            host.Children.Add(shell)
            self.list_lines.append((shell, row["name"]))
        if not shown:
            host.Children.Add(text_block(u"   No filters on this template - add one above.",
                                         "Lbl.Muted"))

    def _filter_name(self, key):
        element = self.doc.GetElement(shtm_model.new_element_id(key))
        return shtm_model.element_name(element) if element is not None else u"{0}".format(key)

    def _add_filter(self, picker, available):
        wanted = [key for key, name in available if name == picker.text]
        if not wanted:
            return
        self.filter_add.append(wanted[0])
        self._build_filters()
        self._paint_apply()

    def _toggle_filter(self, key, adding):
        @ui_safe
        def handler(sender, event):
            if adding:
                if key in self.filter_add:
                    self.filter_add.remove(key)
            elif key in self.filter_remove:
                self.filter_remove.discard(key)
            else:
                self.filter_remove.add(key)
            self._build_filters()
            self._paint_apply()
        return handler

    # ---- View Range ----

    def _build_range(self):
        tools = self.find("ListTools")
        tools.Children.Clear()
        host = self.find("ListHost")
        host.Children.Clear()
        self.list_lines = []
        if not self.ranges:
            self._list_header([(u"View Range", None)])
            tools.Children.Add(text_block(
                u"Only plan view templates have a view range.", "Lbl.Muted"))
            return
        tools.Children.Add(text_block(
            u"Offsets in millimetres from the chosen level. Unlimited ignores its "
            u"offset.", "Lbl.Muted"))
        widths = (150.0, None, 150.0)
        self._list_header([(u"Plane", 150.0), (u"Level", None), (u"Offset (mm)", 150.0)])
        labels = [label for _key, label in RANGE_LEVELS]
        for index, row in enumerate(self.ranges):
            shell, line = self._list_line(index, widths)
            line.Children.Add(text_block(row["label"], "Lbl.Body"))
            edit = self.range_edits.get(row["plane"], {})
            choices = list(labels)
            if row["level_label"] not in choices:
                choices.append(row["level_label"])
            current = dict(RANGE_LEVELS).get(edit.get("level"), row["level_label"])
            box = _combo(choices, current)
            box.Margin = Thickness(0, 0, 8, 0)
            box.SelectionChanged += self._range_level(row, choices)
            Grid.SetColumn(box, 1)
            line.Children.Add(box)
            offset = shtm_ui.text_box(u"0", None, "Txt.Field")
            offset.Text = edit.get("offset", row["offset_text"])
            offset.Height = 26
            offset.MinHeight = 0
            offset.TextChanged += self._range_offset(row["plane"])
            Grid.SetColumn(offset, 2)
            line.Children.Add(offset)
            host.Children.Add(shell)
            self.list_lines.append((shell, row["label"]))

    def _range_level(self, row, choices):
        keys = dict([(label, key) for key, label in RANGE_LEVELS])

        @ui_safe
        def handler(sender, event):
            index = sender.SelectedIndex
            if 0 <= index < len(choices):
                label = choices[index]
                self.range_edits.setdefault(row["plane"], {})["level"] = keys.get(
                    label, row["level"])
            self._paint_apply()
        return handler

    def _range_offset(self, plane):
        @ui_safe
        def handler(sender, event):
            self.range_edits.setdefault(plane, {})["offset"] = sender.Text or u""
            self._paint_apply()
        return handler

    # ---- editing ----

    def _picked(self, key, labels):
        @ui_safe
        def handler(sender, event):
            index = sender.SelectedIndex
            if 0 <= index < len(labels):
                self.edits[key] = labels[index]
            self._paint_apply()
        return handler

    def _typed(self, key):
        @ui_safe
        def handler(sender, event):
            self.edits[key] = sender.Text or u""
            self._paint_apply()
        return handler

    def _include_ticked(self, key, on):
        @ui_safe
        def handler(sender, event):
            self.includes[key] = on
            self._paint_apply()
        return handler

    def _include_all(self, on):
        for key in self.lines:
            tick = self.lines[key][2]
            if tick is not None:
                tick.IsChecked = on

    def _filter(self):
        words = (self.find("ParamSearch").Text or u"").strip().lower().split()

        def shown(text):
            return Visibility.Visible if all(w in text.lower() for w in words) \
                else Visibility.Collapsed
        if self.tab == "props":
            for row in self.rows:
                shell = self.lines[row["id"]][0]
                shell.Visibility = shown(u"{0} {1}".format(row["name"], row["value"]))
        else:
            for shell, text in self.list_lines:
                shell.Visibility = shown(text)

    def changes(self):
        changes = shtm_core.template_changes(self.rows, self.edits, self.includes,
                                             self.name, self.find("TemplateName").Text)
        categories = {}
        for key in ("model", "annotation"):
            categories.update(shtm_core.flag_changes(
                self.categories[key], self.cat_edits[key], ("visible", "halftone")))
        changes["categories"] = categories
        settable = dict([(key, value) for key, value in self.filter_edits.items()
                         if key not in self.filter_remove])
        changes["filters"] = {
            "set": shtm_core.flag_changes(self.filters, settable,
                                          ("enabled", "visible", "halftone")),
            "add": list(self.filter_add), "remove": sorted(self.filter_remove)}
        ranges, bad = shtm_core.range_changes(self.ranges or [], self.range_edits)
        changes["range"] = ranges
        changes["range_bad"] = bad
        return changes

    def _count(self, changes):
        filters = changes["filters"]
        return (len(changes["values"]) + len(changes["include"])
                + (1 if changes["name"] else 0) + len(changes["categories"])
                + len(filters["set"]) + len(filters["add"]) + len(filters["remove"])
                + len(changes["range"]))

    def _paint_apply(self):
        changes = self.changes()
        count = self._count(changes)
        bad = changes["range_bad"]
        button = self.find("ApplyBtn")
        button.IsEnabled = bool(count) and not self.busy and not bad
        styled(button, "Btn.Green" if count and not bad else "Btn.Flat")
        button.Content = (u"Apply {0}".format(shtm_core.plural(count, u"change"))
                          if count else u"Apply")
        status = self.find("StatusText")
        if bad:
            status.Text = u"View Range: an offset is not a number of millimetres"
            self.range_warned = True
        elif getattr(self, "range_warned", False):
            status.Text = u"Changed rows show orange; nothing is written until Apply."
            self.range_warned = False
        for key in self.lines:
            shell, name, tick = self.lines[key]
            changed = key in changes["values"] or key in changes["include"]
            if key in self.refused:
                name.SetResourceReference(TextBlock.ForegroundProperty, "RedBrush")
                name.ToolTip = self.refused[key]
            elif changed:
                name.SetResourceReference(TextBlock.ForegroundProperty, "OrangeBrush")
            else:
                name.SetResourceReference(TextBlock.ForegroundProperty, "TextBrush")

    def _apply(self, sender, event):
        changes = self.changes()
        if not self._count(changes) or changes["range_bad"]:
            return
        self.busy = True
        self.find("ApplyBtn").IsEnabled = False
        self.find("StatusText").Text = u"writing to the template..."
        job = {"action": "edit", "id": self.template_id, "changes": changes,
               "rows": self.rows, "doc": self.doc, "done": self._done}
        if not self.run_job(job):
            self.busy = False
            self.find("StatusText").Text = u"Revit would not take the request - nothing was written"
            self._paint_apply()
            return
        self._watch()

    def _watch(self):
        """Revit runs the job when it next goes idle. If it has said nothing
        in 30 seconds the window stops waiting, so it is never stuck busy."""
        def give_up():
            if self.busy:
                self.busy = False
                self.find("StatusText").Text = (
                    u"Revit has not run the change yet - it will when it is idle; "
                    u"reopen the editor to see it")
                self._paint_apply()
        self.watchdog = shtm_ui.debounce(30000, give_up)
        self.watchdog.Start()

    def _done(self, report):
        self.busy = False
        try:
            self.watchdog.Stop()
        except Exception:
            pass
        self.refused = report.get("refused") or {}
        problems = list(report.get("problems") or [])
        if report.get("ok"):
            self.read()
        if self.refused:
            problems.append(u"{0} would not take: {1}".format(
                shtm_core.plural(len(self.refused), u"change"),
                u"; ".join([u"{0}".format(v) for v in list(self.refused.values())[:3]])))
        self.find("StatusText").Text = (u"; ".join(problems) if problems
                                        else u"written to the template")
        self.find("StatusText").SetResourceReference(
            TextBlock.ForegroundProperty, "OrangeBrush" if problems else "GreenBrush")
        self._paint_apply()
        if self.saved is not None:
            try:
                self.saved(self.template_id, report)
            except Exception:
                shtm_ui.log(u"template editor: the saved callback failed")

    def _close(self, sender, event):
        self.window.Close()

    def _cycle_theme(self, sender, event):
        self.mode = theme.next_mode(self.mode)
        theme.apply(self.window, self.mode)
        self.find("ThemeChip").Content = theme.label(self.mode)

    def show(self):
        if self.owner is not None:
            try:
                shtm_ui.bring_back(self.owner)
                self.window.Owner = self.owner
            except Exception:
                pass
        self.window.Show()
        return self.window


def _row_shell(index):
    shell = Border()
    shell.Padding = Thickness(8, 3, 8, 3)
    shell.SetResourceReference(Border.BorderBrushProperty, "GridLineBrush")
    shell.BorderThickness = Thickness(0, 0, 0, 1)
    if index % 2:
        shell.SetResourceReference(Border.BackgroundProperty, "RowAltBg")
    return shell


def _tick(on):
    tick = CheckBox()
    styled(tick, "Chk.Flat")
    tick.IsChecked = bool(on)
    tick.HorizontalAlignment = HorizontalAlignment.Center
    tick.VerticalAlignment = VerticalAlignment.Center
    return tick


def _combo(labels, current):
    box = ComboBox()
    styled(box, "Cmb.Flat")
    for label in labels:
        item = ComboBoxItem()
        item.Content = label
        styled(item, "Cmb.Item")
        box.Items.Add(item)
    if current in labels:
        box.SelectedIndex = labels.index(current)
    box.Height = 26
    return box


def _foreground():
    from System.Windows.Controls import Control
    return Control.ForegroundProperty
