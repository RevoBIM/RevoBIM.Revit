# -*- coding: utf-8 -*-
"""View Manager: create plan views from view templates, levels and a scope box,
and create dependent views from scope boxes."""

__title__ = "View Manager"
__author__ = "RevoBIM PY"
__doc__ = ("View Manager - create plan views from view templates x levels on "
           "one scope box, or create dependent views from scope boxes.")

# The window is modeless so Revit stays usable while it is open. That needs the
# engine kept alive, or every handler in the window is dead the moment the
# command returns.
__persistentengine__ = True

# ---------------------------------------------------------------------------
#  RevoBIM PY  -  View Manager (Create Views / Dependent Views)
#  Version 1.11.0       Revit 2024 - 2027
# ---------------------------------------------------------------------------

VERSION = "1.11.0"

# --- Dependent Views naming ------------------------------------------------
NAME_PREFIX = "DEP_"          # prefix added to the host view name
NAME_SEPARATOR = "_"          # separator placed before the scope box name

# How many views go into one transaction. Each commit is a full document
# regeneration, so one transaction per view is what made this slow; a chunk
# Revit refuses is replayed one at a time so nothing is lost to batching.
CHUNK_SIZE = 25

# --- Create Views naming ---------------------------------------------------
CREATE_SEPARATOR = "_"        # between template abbreviation and level abbreviation

# View template abbreviations - FIRST MATCH WINS, so the order is the rule.
# Anything specific has to sit above the general term it contains, or the
# general one swallows it: "EXT Lighting" above "Lighting", and "HVAC Pipework"
# above the plain "hvac" that belongs to ventilation.
TEMPLATE_ABBREVIATIONS = [
    (("fire alarm", "firealarm"),                    "FA"),
    (("ext lighting", "external lighting"),          "LTG-EXT"),
    (("lighting",),                                  "LTG"),
    (("water service", "domestic", "dhw", "mcws"),   "DOM"),
    (("hvac pipework", "heating", "lthw", "mthw"),   "HTG"),
    (("containment", "cable tray", "trunking"),      "CONT"),
    (("ventilation", "hvac", "ducting", "ductwork"), "VENT"),
    (("drainage", "soil", "waste"),                  "DRN"),
    (("power", "small power"),                       "PWR"),
    (("security", "cctv"),                           "SEC"),
]

# The template list opens filtered to this view family. Create Views makes
# floor plans, so the other families are one pick away rather than in the way.
DEFAULT_TEMPLATE_FAMILY = "FloorPlan"

# Per-template abbreviations set in Settings, keyed on the exact template name.
# These beat the keyword table. Held in a module-level dict so the persistent
# engine keeps them between runs; the file is the record.
OVERRIDES = {}
OVERRIDES_FILE = "view_manager_abbreviations.txt"

# Per-level and per-scope-box abbreviations, also set in Settings; per project.
LEVEL_OVERRIDES = {}
BOX_OVERRIDES = {}

# Level name aliases - checked after an explicit floor token, before any number.
LEVEL_ALIASES = [
    ("roof",      "RF"),
    ("ground",    "00"),
    ("mezzanine", "MZ"),
    ("basement",  "B1"),
    ("podium",    "PD"),
    ("plant",     "PL"),
]

# --- imports (order matters under IronPython) ------------------------------
from pyrevit import HOST_APP  # noqa: F401  (ensures pyRevit context loads first)

import codecs
import os
import re
import sys
import traceback

import clr
for _asm in ('PresentationCore', 'PresentationFramework', 'WindowsBase',
             'System.Xaml', 'System.Xml', 'System', 'RevitAPI', 'RevitAPIUI'):
    try:
        clr.AddReference(_asm)
    except Exception:
        pass

from System import Action, Int64, TimeSpan
from System.Diagnostics import Stopwatch
from System.Windows import (Visibility, Clipboard, Thickness, FontWeights,
                            VerticalAlignment, TextTrimming, Point,
                            PresentationSource, SystemParameters, ResizeMode,
                            LogicalTreeHelper)
from System.Windows.Media import (FontFamily, VisualTreeHelper, ColorConverter,
                                SolidColorBrush)
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Controls import (Border, CheckBox, RadioButton, StackPanel,
                                     Orientation, TextBlock)
from System.Windows.Controls.Primitives import ButtonBase
from System.Windows.Media import Brushes
from System.Windows.Input import Key, Keyboard, ModifierKeys
from System.Windows.Threading import DispatcherPriority, DispatcherTimer
from System.IO import StringReader
from System.Xml import XmlReader

from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, BuiltInParameter, ElementId,
    View, ViewPlan, ViewFamily, ViewFamilyType, ViewDuplicateOption,
    Level, Element, Category, Transaction, TransactionGroup,
    IFailuresPreprocessor, FailureProcessingResult, FailureSeverity,
    RevitLinkInstance, PlanViewPlane, XYZ, UV, LinkElementId, Transform
)
# Worksharing names live in DB too but are not on every release, so they are
# asked for on their own - a missing name here must not take the tool down.
try:
    from Autodesk.Revit.DB import (FilteredWorksetCollector, WorksetKind,
                                   WorksetVisibility)
    WORKSETS_AVAILABLE = True
except Exception:
    FilteredWorksetCollector = None
    WorksetKind = None
    WorksetVisibility = None
    WORKSETS_AVAILABLE = False
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent

uiapp = __revit__                                   # noqa: F821
uidoc = uiapp.ActiveUIDocument
doc = uidoc.Document
app = doc.Application

# Parked at module level: the persistent engine collects anything that is not.
_SHRINK_CLOCK = Stopwatch.StartNew()
WINDOW = None
EVENT = None
HANDLER = None


# ---------------------------------------------------------------------------
#  Compatibility helpers  (Revit 2024 - 2027)
# ---------------------------------------------------------------------------
def eid_value(element_id):
    """ElementId.IntegerValue was removed in Revit 2026 - prefer .Value."""
    if element_id is None:
        return 0
    try:
        return element_id.Value
    except Exception:
        pass
    try:
        return element_id.IntegerValue
    except Exception:
        return 0


def key_of(element):
    try:
        return int(eid_value(element.Id))
    except Exception:
        return 0


def make_eid(number):
    """ElementId takes an Int64 from 2026 and an int before that."""
    try:
        return ElementId(Int64(number))
    except Exception:
        pass
    try:
        return ElementId(int(number))
    except Exception:
        return ElementId.InvalidElementId


def is_invalid(element_id):
    try:
        return element_id is None or eid_value(element_id) <= 0
    except Exception:
        return True


def as_element(document, result):
    """Normalise what a Revit create/duplicate call hands back.

    `View.Duplicate` returns an ElementId, but `ViewPlan.Create` returns the
    ViewPlan itself - and which one you get has moved between releases. Taking
    either is the only safe way to call them.
    """
    if result is None:
        return None
    if isinstance(result, ElementId):
        return document.GetElement(result)
    try:
        if hasattr(result, "Id"):
            return result
    except Exception:
        pass
    try:
        return document.GetElement(result)
    except Exception:
        return None


def describe(ex):
    """Exception type and message, which is what a Revit refusal hides in."""
    try:
        name = type(ex).__name__
    except Exception:
        name = "Exception"
    try:
        text = str(ex).strip().replace("\r", " ").replace("\n", " ")
    except Exception:
        text = "<unreadable>"
    return "{0}: {1}".format(name, text or "<no message>")


def set_name(element, name):
    """Renaming route varies by IronPython version; confirm by reading back."""
    errors = []
    try:
        element.Name = name
        if element.Name == name:
            return True, ""
    except Exception as ex:
        errors.append("direct: " + describe(ex))
    try:
        Element.Name.SetValue(element, name)
        if element.Name == name:
            return True, ""
        errors.append("SetValue: name did not take")
    except Exception as ex:
        errors.append("SetValue: " + describe(ex))
    try:
        p = element.get_Parameter(BuiltInParameter.VIEW_NAME)
        if p is not None and not p.IsReadOnly:
            p.Set(name)
            if element.Name == name:
                return True, ""
            errors.append("VIEW_NAME: name did not take")
    except Exception as ex:
        errors.append("VIEW_NAME: " + describe(ex))
    return False, "; ".join(errors)


def revit_version():
    bits = []
    for attr in ("VersionNumber", "VersionBuild", "VersionName", "SubVersionNumber"):
        try:
            value = getattr(app, attr, None)
            if value:
                bits.append("{0}={1}".format(attr, value))
        except Exception:
            pass
    return ", ".join(bits) or "unknown"


def engine_version():
    try:
        return sys.version.replace("\n", " ")
    except Exception:
        return "unknown"


def settings_folder():
    """House settings are global - an abbreviation is a standard, not a job."""
    folder = os.path.join(os.getenv("APPDATA"), "RevoBIM")
    if not os.path.isdir(folder):
        os.makedirs(folder)
    return folder


def log_folder():
    folder = os.path.join(settings_folder(), "logs")
    if not os.path.isdir(folder):
        os.makedirs(folder)
    return folder


class AbbrevStore(object):
    """name<TAB>abbreviation, one file per kind.

    Template abbreviations are a house standard, so they are global. Level and
    scope box names belong to one job (41AM_F02A), so those are kept per
    project, keyed on the central model's file name.
    """

    def __init__(self, file_name, per_project, items=None, what="name"):
        self.file_name = file_name
        self.per_project = per_project
        self.items = items if items is not None else {}
        self.what = what

    def path(self):
        folder = settings_folder()
        if self.per_project:
            folder = os.path.join(folder, "view_manager_projects", project_key())
            if not os.path.isdir(folder):
                os.makedirs(folder)
        return os.path.join(folder, self.file_name)

    def load(self):
        self.items.clear()
        try:
            path = self.path()
            if not os.path.isfile(path):
                return
            handle = codecs.open(path, "r", "utf-8")
            try:
                for line in handle:
                    line = line.rstrip("\r\n")
                    if not line or line.startswith("#") or "\t" not in line:
                        continue
                    name, abbr = line.split("\t", 1)
                    name = name.strip()
                    abbr = abbr.strip()
                    if name and abbr:
                        self.items[name] = abbr
            finally:
                handle.close()
        except Exception:
            pass

    def save(self):
        """Returns (saved, note) - the caller says so rather than failing quietly."""
        try:
            handle = codecs.open(self.path(), "w", "utf-8")
            try:
                handle.write(u"# RevoBIM PY - View Manager\n")
                handle.write(u"# {0}<TAB>abbreviation. Edited from the tool's "
                             u"Settings window.\n".format(self.what))
                for name in sorted(self.items.keys()):
                    handle.write(u"{0}\t{1}\n".format(name, self.items[name]))
            finally:
                handle.close()
            return True, ""
        except Exception as ex:
            return False, describe(ex)


def project_key():
    """A folder name for this project: the central file if workshared."""
    name = ""
    try:
        if doc.IsWorkshared:
            from Autodesk.Revit.DB import ModelPathUtils
            central = doc.GetWorksharingCentralModelPath()
            name = ModelPathUtils.ConvertModelPathToUserVisiblePath(central)
    except Exception:
        name = ""
    if not name:
        try:
            name = doc.PathName or ""
        except Exception:
            name = ""
    if not name:
        try:
            name = doc.Title or ""
        except Exception:
            name = ""
    name = os.path.splitext(os.path.basename(name.replace("/", "\\").split("\\")[-1]))[0]
    name = re.sub(r'[<>:"/\\|?*]+', "-", name).strip(" .") or "Untitled"
    return name


TEMPLATE_STORE = AbbrevStore(OVERRIDES_FILE, False, OVERRIDES, "View template name")
LEVEL_STORE = AbbrevStore("level_abbreviations.txt", True, LEVEL_OVERRIDES, "Level name")
BOX_STORE = AbbrevStore("scope_box_abbreviations.txt", True, BOX_OVERRIDES, "Scope box name")


def overrides_path():
    return TEMPLATE_STORE.path()


def load_overrides():
    """Read every saved abbreviation. Never raises."""
    TEMPLATE_STORE.load()
    LEVEL_STORE.load()
    BOX_STORE.load()


def save_overrides():
    return TEMPLATE_STORE.save()


def pretty_time(milliseconds):
    seconds = float(milliseconds) / 1000.0
    if seconds < 1.0:
        return "{0:.0f}ms".format(float(milliseconds))
    if seconds < 60.0:
        return "{0:.1f}s".format(seconds)
    return "{0:d}m {1:.0f}s".format(int(seconds // 60), seconds % 60)


class JobFailed(Exception):
    """One item refused. Carries the log line already formatted."""
    pass


def quiet_options(transaction):
    """Warnings deleted rather than stopping the run to show each one."""
    try:
        options = transaction.GetFailureHandlingOptions()
        options.SetFailuresPreprocessor(WarningSwallower())
        options.SetForcedModalHandling(False)
        options.SetClearAfterRollback(True)
        try:
            options.SetDelayedMiniWarnings(True)
        except Exception:
            pass
        transaction.SetFailureHandlingOptions(options)
    except Exception:
        pass


class WarningSwallower(IFailuresPreprocessor):
    """Deletes warnings rather than stopping the run to show each one."""

    def PreprocessFailures(self, accessor):
        try:
            for failure in accessor.GetFailureMessages():
                if failure.GetSeverity() == FailureSeverity.Warning:
                    accessor.DeleteWarning(failure)
        except Exception:
            pass
        return FailureProcessingResult.Continue


# DialogBoxShowing is hooked once and switched with a flag: unsubscribing an
# IronPython bound method from a .NET event is not reliable.
SUPPRESSING = [False]
HOOKED = [False]


def _on_dialog_showing(sender, args):
    if not SUPPRESSING[0]:
        return
    try:
        args.OverrideResult(1)          # IDOK
    except Exception:
        pass


def hook_dialogs():
    if HOOKED[0]:
        return
    try:
        uiapp.DialogBoxShowing += _on_dialog_showing
        HOOKED[0] = True
    except Exception:
        pass


def suppress_dialogs(state):
    SUPPRESSING[0] = bool(state)


def scope_box_holds(view, box_id):
    """Is the scope box still the one we set? Cheaper than setting it again."""
    try:
        p = view.get_Parameter(BuiltInParameter.VIEWER_VOLUME_OF_INTEREST_CROP)
        if p is None:
            return False
        return eid_value(p.AsElementId()) == eid_value(box_id)
    except Exception:
        return False


# ---------------------------------------------------------------------------
#  Naming helpers
# ---------------------------------------------------------------------------
INVALID_CHARS = list("{}[]|;<>?`~:\\/*\"")


def sanitise(name):
    out = name or ""
    for ch in INVALID_CHARS:
        out = out.replace(ch, "-")
    out = out.strip()
    return out or "View"


def fallback_abbr(name):
    """Longest alphabetic word, used when nothing in the table matches.

    A consonant squeeze over the whole string turns a code-led name like
    'B_BS_01_ME_HVAC Ducting-DOC' into 'BBSM', which means nothing. The
    longest real word in it is far more recognisable.
    """
    words = re.findall(r"[A-Za-z]{3,}", name or "")
    if words:
        best = max(words, key=len)
        return best[:4].upper()
    letters = re.sub(r"[^A-Za-z]", "", name or "")
    return (letters[:4].upper() or "VIEW")


def abbreviate_template(name):
    """Map a view template name onto its service abbreviation."""
    abbr, _source = abbreviate_detail(name)
    return abbr, _source != "fallback"


def abbreviate_detail(name):
    """(abbreviation, source) where source is override, keyword or fallback.

    An abbreviation set by hand in Settings beats the keyword table outright -
    the whole point of setting one is that the keywords got it wrong.
    """
    key = (name or "").strip()
    if key in OVERRIDES:
        return OVERRIDES[key], "override"
    low = key.lower()
    for keywords, abbr in TEMPLATE_ABBREVIATIONS:
        for kw in keywords:
            if kw in low:
                return abbr, "keyword"
    return fallback_abbr(name), "fallback"


def abbreviate_level(name):
    """The level's abbreviation: one set in Settings, else the rule."""
    return level_abbr_detail(name)[0]


def level_abbr_detail(name):
    key = (name or "").strip()
    if key in LEVEL_OVERRIDES:
        return LEVEL_OVERRIDES[key], "override"
    return level_rule(name), "rule"


def box_abbr_detail(name):
    """A scope box's abbreviation: one set in Settings, else its own name."""
    key = (name or "").strip()
    if key in BOX_OVERRIDES:
        return BOX_OVERRIDES[key], "override"
    return key, "name"


def box_abbr(name):
    return box_abbr_detail(name)[0]


def level_rule(name):
    """Level 0 -> L00, Level 1 -> L01, Roof -> LRF, 41AM_F02A -> L02A.

    An explicit floor token wins over any other number in the name: in
    '41AM_F01' the building code 41 is the first number but the floor is 01,
    and reading the first number collapses a whole building onto one name.
    """
    raw = (name or "").strip()

    # 1. an explicit floor token - F01, F02A, L03
    match = re.search(r"(?:^|[^A-Za-z0-9])[FL](\d{1,2})([A-Za-z]?)(?![A-Za-z0-9])",
                      raw, re.IGNORECASE)
    if match:
        return "L{0:02d}{1}".format(int(match.group(1)), match.group(2).upper())

    # 2. a spelt-out level or floor. An underscore may separate it from the
    #    number but a hyphen may not, so a hyphen can only ever read as a sign.
    match = re.search(
        r"(?:^|[^A-Za-z0-9])(?:level|lvl|floor)[\s_]*(-?\d{1,2})([A-Za-z]?)(?![A-Za-z0-9])",
        raw, re.IGNORECASE)
    if match:
        number = int(match.group(1))
        if number < 0:
            return "LB{0}".format(abs(number))
        return "L{0:02d}{1}".format(number, match.group(2).upper())

    # 3. named levels
    low = raw.lower()
    for alias, abbr in LEVEL_ALIASES:
        if alias in low:
            return "L" + abbr

    # 4. the last number in the name - the trailing one is the floor
    numbers = re.findall(r"-?\d+", raw)
    if numbers:
        number = int(numbers[-1])
        if number < 0:
            return "LB{0}".format(abs(number))
        return "L{0:02d}".format(number)

    letters = re.sub(r"[^A-Za-z]", "", raw)
    consonants = re.sub(r"[AEIOUaeiou]", "", letters) or letters
    return "L" + (consonants[:2].upper() if consonants else "XX")


def unique_name(base, taken):
    candidate = base
    counter = 2
    while candidate in taken:
        candidate = "{0} ({1})".format(base, counter)
        counter += 1
    return candidate


def document_of():
    return doc


# ---------------------------------------------------------------------------
#  Model collection
# ---------------------------------------------------------------------------
def collect_host_views(document):
    """Views able to have dependents created from them."""
    result = []
    for v in FilteredElementCollector(document).OfClass(View):
        try:
            if v.IsTemplate:
                continue
            if not is_invalid(v.GetPrimaryViewId()):
                continue
            if not v.CanViewBeDuplicated(ViewDuplicateOption.AsDependent):
                continue
        except Exception:
            continue
        result.append(v)
    result.sort(key=lambda x: (str(x.ViewType), x.Name.lower()))
    return result


def collect_view_templates(document):
    result = []
    for v in FilteredElementCollector(document).OfClass(View):
        try:
            if v.IsTemplate:
                result.append(v)
        except Exception:
            continue
    result.sort(key=lambda x: x.Name.lower())
    return result


def collect_levels(document):
    levels = list(FilteredElementCollector(document)
                  .OfClass(Level)
                  .WhereElementIsNotElementType()
                  .ToElements())
    levels.sort(key=lambda x: x.Elevation)
    return levels


def collect_scope_boxes(document):
    boxes = list(FilteredElementCollector(document)
                 .OfCategory(BuiltInCategory.OST_VolumeOfInterest)
                 .WhereElementIsNotElementType()
                 .ToElements())
    boxes.sort(key=lambda x: x.Name.lower())
    return boxes


def existing_view_names(document):
    names = set()
    for v in FilteredElementCollector(document).OfClass(View):
        try:
            names.add(v.Name)
        except Exception:
            pass
    return names


# A template's ViewType -> the ViewFamily a new view of that kind needs.
PLAN_FAMILY_BY_TYPE = {
    "FloorPlan": "FloorPlan",
    "CeilingPlan": "CeilingPlan",
    "EngineeringPlan": "StructuralPlan",
    "StructuralPlan": "StructuralPlan",
    "AreaPlan": None,          # needs an area scheme; not offered
}


def plan_family_for(view_type):
    name = str(view_type)
    family_name = PLAN_FAMILY_BY_TYPE.get(name)
    if family_name is None:
        return None, name
    return getattr(ViewFamily, family_name, None), name


def type_name_of(element):
    try:
        return Element.Name.GetValue(element)
    except Exception:
        pass
    try:
        return element.Name
    except Exception:
        return "<unnamed>"


def family_label(view):
    """The view family - FloorPlan, Section, ThreeD and so on."""
    try:
        return str(view.ViewType)
    except Exception:
        return "Other"


def type_label(document, view):
    """The ViewFamilyType the view is an instance of, by name."""
    try:
        type_id = view.GetTypeId()
    except Exception:
        return "(no type)"
    if is_invalid(type_id):
        return "(no type)"
    try:
        element = document.GetElement(type_id)
    except Exception:
        return "(no type)"
    if element is None:
        return "(no type)"
    return type_name_of(element) or "(no type)"


def build_meta(document, views):
    """family and type for every view, read once rather than per rebuild."""
    meta = {}
    for v in views:
        meta[key_of(v)] = (family_label(v), type_label(document, v))
    return meta


def build_filter_options(meta):
    """All, then each family, then each family-and-type pair beneath it."""
    pairs = {}
    for family, type_name in meta.values():
        pairs.setdefault(family, set()).add(type_name)

    options = [(None, None, "All families and types")]
    for family in sorted(pairs.keys()):
        options.append((family, None, "{0}  -  all".format(family)))
        for type_name in sorted(pairs[family]):
            options.append((family, type_name, "    {0}".format(type_name)))
    return options


def view_family_type_for(document, view_type, cache, log=None):
    """A ViewFamilyType matching the plan family of a template.

    A template carries no ViewFamilyType of its own, so one has to be found.
    Sorted by name and the first taken, so the same type is picked every run
    rather than whatever the collector happened to yield first.
    """
    name = str(view_type)
    if name in cache:
        return cache[name]

    family, _ = plan_family_for(view_type)
    candidates = []
    if family is not None:
        for vft in FilteredElementCollector(document).OfClass(ViewFamilyType):
            try:
                if vft.ViewFamily == family:
                    candidates.append(vft)
            except Exception:
                continue
    candidates.sort(key=lambda v: type_name_of(v).lower())
    found = candidates[0] if candidates else None

    if log is not None:
        if found is None:
            log.append("    no ViewFamilyType for ViewType '{0}' (ViewFamily {1})".format(
                name, family))
        elif len(candidates) > 1:
            log.append("    {0} ViewFamilyTypes available for {1}: {2}".format(
                len(candidates), name,
                ", ".join(type_name_of(v) for v in candidates[:8])))
    cache[name] = found
    return found


# Categories worth hiding while a view is being cropped. Linked IFC comes in
# as a linked Revit model, so OST_RvtLinks covers it.
QUIET_CATEGORIES = [
    "OST_RvtLinks",
    "OST_Coordination_Model",
    "OST_PointClouds",
    "OST_RasterImages",
]


def category_id(document, builtin_name):
    builtin = getattr(BuiltInCategory, builtin_name, None)
    if builtin is None:
        return None
    try:
        cat = Category.GetCategory(document, builtin)
        if cat is not None:
            return cat.Id
    except Exception:
        pass
    try:
        return ElementId(builtin)
    except Exception:
        return None


def quieten_view(document, view):
    """Hide links and worksets before the view is cropped.

    Assigning a scope box makes Revit work out the crop against everything the
    view can currently see. A brand new view can see the whole model including
    every linked IFC, and that is where the minutes go. Hidden first, the crop
    is worked out against nothing; the view template then sets the visibility
    that actually belongs on the view.
    """
    notes = []

    hidden_categories = []
    for name in QUIET_CATEGORIES:
        cid = category_id(document, name)
        if cid is None:
            continue
        try:
            if view.CanCategoryBeHidden(cid) and not view.GetCategoryHidden(cid):
                view.SetCategoryHidden(cid, True)
                hidden_categories.append(cid)
        except Exception as ex:
            notes.append("{0}: {1}".format(name, describe(ex)))

    hidden_worksets = []
    if WORKSETS_AVAILABLE and document.IsWorkshared:
        try:
            for workset in FilteredWorksetCollector(document).OfKind(
                    WorksetKind.UserWorkset):
                try:
                    if view.GetWorksetVisibility(workset.Id) != WorksetVisibility.Hidden:
                        view.SetWorksetVisibility(workset.Id, WorksetVisibility.Hidden)
                        hidden_worksets.append(workset.Id)
                except Exception:
                    pass
        except Exception as ex:
            notes.append("worksets: " + describe(ex))

    return (hidden_worksets, hidden_categories), "; ".join(notes)


def restore_quiet(view, hidden):
    """Undo quieten_view once the template is on: categories and worksets.

    A category only stays hidden if the template says so. One the template
    controls refuses the write, which is right - the template's answer wins -
    and one it does not control goes back to showing, like a view made by hand.
    """
    workset_ids, category_ids = hidden if hidden else ([], [])
    for cid in category_ids or []:
        try:
            view.SetCategoryHidden(cid, False)
        except Exception:
            pass
    return restore_worksets(view, workset_ids)


def restore_worksets(view, workset_ids):
    """Hand the worksets back to the global setting after the template is on.

    Only a flag each - the crop is already established by this point, so
    nothing is recomputed. A template that controls workset visibility refuses
    the write, which is correct: the template's answer wins.
    """
    if not (WORKSETS_AVAILABLE and workset_ids):
        return 0
    restored = 0
    for workset_id in workset_ids:
        try:
            view.SetWorksetVisibility(workset_id, WorksetVisibility.UseGlobalSetting)
            restored += 1
        except Exception:
            pass
    return restored


def apply_scope_box(view, box_id, verify=True):
    """Returns (applied, note).

    `verify` reads the value back, which forces a regeneration - fine once
    after the commit, ruinous inside the loop.
    """
    try:
        p = view.get_Parameter(BuiltInParameter.VIEWER_VOLUME_OF_INTEREST_CROP)
    except Exception as ex:
        return False, "scope box parameter lookup failed - " + describe(ex)
    if p is None:
        return False, "view has no scope box parameter"
    if p.IsReadOnly:
        return False, "scope box parameter is read-only (locked by the view template?)"
    try:
        p.Set(box_id)
    except Exception as ex:
        return False, "scope box Set failed - " + describe(ex)
    try:
        if not view.CropBoxActive:
            view.CropBoxActive = True
        if not view.CropBoxVisible:
            view.CropBoxVisible = True
    except Exception:
        pass
    if verify:
        try:
            if is_invalid(p.AsElementId()):
                return False, "scope box did not take (read back as none)"
        except Exception:
            pass
    return True, ""


def apply_template(view, template):
    """Returns (applied, note)."""
    try:
        if hasattr(view, "IsValidViewTemplate"):
            if not view.IsValidViewTemplate(template.Id):
                return False, "template is not valid for this view type"
    except Exception:
        pass
    try:
        view.ViewTemplateId = template.Id
    except Exception as ex:
        return False, "ViewTemplateId Set failed - " + describe(ex)
    try:
        if eid_value(view.ViewTemplateId) != eid_value(template.Id):
            return False, "template did not take (read back as a different id)"
    except Exception:
        pass
    return True, ""



# ---------------------------------------------------------------------------
#  Room tags - which rooms a new plan cuts, and tagging them
# ---------------------------------------------------------------------------
# A room belongs in a plan when the view's cut plane passes through it and its
# point sits inside the crop. Worked out geometrically rather than by asking
# which rooms the view shows: MEP templates often hide the Rooms category while
# showing room tags, and a view-filtered collector would then find none.

ROOM_Z_TOLERANCE = 0.01          # feet; a cut exactly on a floor still counts
DEFAULT_CUT_OFFSET = 4.0         # feet (1200 mm) when a view reports no cut plane
TAG_VIEWS_PER_TRANSACTION = 10


def z_span_cut(z_min, z_max, cut_z, tol=ROOM_Z_TOLERANCE):
    """Does a horizontal plane at cut_z pass through z_min..z_max?"""
    if z_min is None or z_max is None or cut_z is None:
        return False
    low, high = (z_min, z_max) if z_min <= z_max else (z_max, z_min)
    return (low - tol) <= cut_z <= (high + tol)


def point_in_rect(x, y, rect):
    """rect is (min_x, min_y, max_x, max_y) or None for no crop at all."""
    if rect is None:
        return True
    min_x, min_y, max_x, max_y = rect
    return min_x <= x <= max_x and min_y <= y <= max_y


def rect_of_points(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def rooms_in_plan(rooms, cut_z, crop_rect):
    """The subset of room records a plan with this cut and crop should tag."""
    picked = []
    for room in rooms:
        if not z_span_cut(room["z_min"], room["z_max"], cut_z):
            continue
        if not point_in_rect(room["x"], room["y"], crop_rect):
            continue
        picked.append(room)
    return picked


def room_sources(document, include_links):
    """(link instance or None, document, transform) for this model and each link."""
    sources = [(None, document, Transform.Identity)]
    if not include_links:
        return sources
    try:
        for instance in FilteredElementCollector(document).OfClass(RevitLinkInstance):
            try:
                link_doc = instance.GetLinkDocument()
                if link_doc is None:
                    continue              # unloaded
                sources.append((instance, link_doc, instance.GetTotalTransform()))
            except Exception:
                continue
    except Exception:
        pass
    return sources


def collect_room_records(document, include_links, log=None):
    """Every placed, bounded room, with its point and height in host coordinates."""
    records = []
    skipped = 0
    for instance, room_doc, transform in room_sources(document, include_links):
        source_name = "this model" if instance is None else type_name_of(instance)
        count = 0
        try:
            rooms = (FilteredElementCollector(room_doc)
                     .OfCategory(BuiltInCategory.OST_Rooms)
                     .WhereElementIsNotElementType())
        except Exception:
            continue
        for room in rooms:
            try:
                if room.Area <= 0:           # unplaced, unbounded or redundant
                    skipped += 1
                    continue
                location = room.Location
                if location is None:
                    skipped += 1
                    continue
                point = transform.OfPoint(location.Point)
                box = room.get_BoundingBox(None)
                if box is None:
                    skipped += 1
                    continue
                zs = []
                for x in (box.Min.X, box.Max.X):
                    for y in (box.Min.Y, box.Max.Y):
                        for z in (box.Min.Z, box.Max.Z):
                            zs.append(transform.OfPoint(XYZ(x, y, z)).Z)
                records.append({
                    "link": instance,
                    "id": room.Id,
                    "x": point.X, "y": point.Y,
                    "z_min": min(zs), "z_max": max(zs),
                })
                count += 1
            except Exception:
                skipped += 1
        if log is not None:
            log.append("  rooms from {0}: {1}".format(source_name, count))
    if log is not None and skipped:
        log.append("  rooms skipped (unplaced, unbounded or redundant): {0}".format(skipped))
    return records


def view_cut_z(view):
    """The cut plane's height in model coordinates.

    Level heights come from ProjectElevation, never Elevation - Elevation is
    measured from the survey or base point and lands far out on a job whose
    base point is set.
    """
    try:
        view_range = view.GetViewRange()
        level_id = view_range.GetLevelId(PlanViewPlane.CutPlane)
        offset = view_range.GetOffset(PlanViewPlane.CutPlane)
        level = view.Document.GetElement(level_id)
        if level is not None:
            return float(level.ProjectElevation) + float(offset)
    except Exception:
        pass
    try:
        return float(view.GenLevel.ProjectElevation) + DEFAULT_CUT_OFFSET
    except Exception:
        return None


def view_crop_rect(view):
    """The crop's XY extent in model coordinates, or None if it is not cropped."""
    try:
        if not view.CropBoxActive:
            return None
        crop = view.CropBox
        transform = crop.Transform
        points = []
        for x in (crop.Min.X, crop.Max.X):
            for y in (crop.Min.Y, crop.Max.Y):
                p = transform.OfPoint(XYZ(x, y, crop.Min.Z))
                points.append((p.X, p.Y))
        return rect_of_points(points)
    except Exception:
        return None


def tag_rooms_in_view(document, view, rooms, tag_type_id, stats):
    """Tag every room this plan cuts. Inside an open transaction."""
    picked = rooms_in_plan(rooms, view_cut_z(view), view_crop_rect(view))
    placed = 0
    for room in picked:
        try:
            if room["link"] is None:
                link_id = LinkElementId(room["id"])
            else:
                link_id = LinkElementId(room["link"].Id, room["id"])
            tag = document.Create.NewRoomTag(link_id, UV(room["x"], room["y"]), view.Id)
            if tag is None:
                stats["refused"] += 1
                continue
            if tag_type_id is not None:
                try:
                    if eid_value(tag.GetTypeId()) != eid_value(tag_type_id):
                        tag.ChangeTypeId(tag_type_id)
                except Exception:
                    pass
            placed += 1
        except Exception as ex:
            stats["refused"] += 1
            if not stats.get("first_refusal"):
                stats["first_refusal"] = describe(ex)
    stats["tagged"] += placed
    stats["views"] += 1
    return placed, len(picked)



# ---------------------------------------------------------------------------
#  Palettes - dark is Revit's own dark UI, sampled from its Project Browser.
#  Both halves carry exactly the same keys, or a swap leaves a brush behind.
# ---------------------------------------------------------------------------
DARK = {
    "WindowBg": "#3C4454",
    "Panel": "#343C4A",
    "Sunken": "#3C4454",
    "Input": "#2D3441",
    "HeadBar": "#212932",
    "Strip": "#1B1F24",
    "TabHover": "#2D3441",
    "Scrim": "#D81B1F24",
    "Track": "#2D3441",
    "Thumb": "#5A6476",
    "ThumbHover": "#6C778A",
    "Line": "#4E586A",
    "Edge": "#8790A0",
    "EdgeHover": "#A4ADBC",
    "Text": "#EBF5FF",
    "Muted": "#9DA4B2",
    "Disabled": "#7B8290",
    "OnAccent": "#FFFFFF",
    "OnBlue": "#0E2233",
    "Btn": "#465063",
    "BtnHover": "#535E73",
    "BtnDisabled": "#343C4A",
    "Hover": "#465063",
    "Selection": "#2B5473",
    "Blue": "#3D9BE9",
    "Orange": "#F07C10",
    "OrangeWash": "#3A2A14",
    "Green": "#3FA75A",
    "GreenHover": "#4EC06D",
    "GreenPress": "#33843F",
    "GreenEdge": "#2E7D42",
    "Red": "#C0392B",
    "RedHover": "#E04B39",
    "RedPress": "#9E2E22",
    "RedEdge": "#8E2A20",
    "RedDisabled": "#5A3833",
    "RedDisabledText": "#A9A9A9",
}

# ---------------------------------------------------------------------------
#  XAML - shared resources, loaded into every window
# ---------------------------------------------------------------------------
SHARED_RESOURCES = u"""
    <SolidColorBrush x:Key="WindowBg" Color="#3C4454"/>
    <SolidColorBrush x:Key="Panel" Color="#343C4A"/>
    <SolidColorBrush x:Key="Sunken" Color="#3C4454"/>
    <SolidColorBrush x:Key="Input" Color="#2D3441"/>
    <SolidColorBrush x:Key="HeadBar" Color="#212932"/>
    <SolidColorBrush x:Key="Strip" Color="#1B1F24"/>
    <SolidColorBrush x:Key="TabHover" Color="#2D3441"/>
    <SolidColorBrush x:Key="Scrim" Color="#D81B1F24"/>
    <SolidColorBrush x:Key="Track" Color="#2D3441"/>
    <SolidColorBrush x:Key="Thumb" Color="#5A6476"/>
    <SolidColorBrush x:Key="ThumbHover" Color="#6C778A"/>
    <SolidColorBrush x:Key="Line" Color="#4E586A"/>
    <SolidColorBrush x:Key="Edge" Color="#8790A0"/>
    <SolidColorBrush x:Key="EdgeHover" Color="#A4ADBC"/>
    <SolidColorBrush x:Key="Text" Color="#EBF5FF"/>
    <SolidColorBrush x:Key="Muted" Color="#9DA4B2"/>
    <SolidColorBrush x:Key="Disabled" Color="#7B8290"/>
    <SolidColorBrush x:Key="OnAccent" Color="#FFFFFF"/>
    <SolidColorBrush x:Key="OnBlue" Color="#0E2233"/>
    <SolidColorBrush x:Key="Btn" Color="#465063"/>
    <SolidColorBrush x:Key="BtnHover" Color="#535E73"/>
    <SolidColorBrush x:Key="BtnDisabled" Color="#343C4A"/>
    <SolidColorBrush x:Key="Hover" Color="#465063"/>
    <SolidColorBrush x:Key="Selection" Color="#2B5473"/>
    <SolidColorBrush x:Key="Blue" Color="#3D9BE9"/>
    <SolidColorBrush x:Key="Orange" Color="#F07C10"/>
    <SolidColorBrush x:Key="OrangeWash" Color="#3A2A14"/>
    <SolidColorBrush x:Key="Green" Color="#3FA75A"/>
    <SolidColorBrush x:Key="GreenHover" Color="#4EC06D"/>
    <SolidColorBrush x:Key="GreenPress" Color="#33843F"/>
    <SolidColorBrush x:Key="GreenEdge" Color="#2E7D42"/>
    <SolidColorBrush x:Key="Red" Color="#C0392B"/>
    <SolidColorBrush x:Key="RedHover" Color="#E04B39"/>
    <SolidColorBrush x:Key="RedPress" Color="#9E2E22"/>
    <SolidColorBrush x:Key="RedEdge" Color="#8E2A20"/>
    <SolidColorBrush x:Key="RedDisabled" Color="#5A3833"/>
    <SolidColorBrush x:Key="RedDisabledText" Color="#A9A9A9"/>


    <Style TargetType="TextBlock">
      <Setter Property="Foreground" Value="{DynamicResource Text}"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize"   Value="12"/>
    </Style>

    <Style x:Key="Head" TargetType="TextBlock">
      <Setter Property="Foreground" Value="{DynamicResource Muted}"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize" Value="11"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
    </Style>

    <!-- ===================== dark scrollbars ===================== -->
    <Style x:Key="ScrollThumb" TargetType="Thumb">
      <Setter Property="IsTabStop" Value="False"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Thumb">
            <Border x:Name="bd" Background="{DynamicResource Thumb}" CornerRadius="4"
                    Margin="3" SnapsToDevicePixels="True"/>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="Background" Value="{DynamicResource ThumbHover}"/>
              </Trigger>
              <Trigger Property="IsDragging" Value="True">
                <Setter TargetName="bd" Property="Background" Value="{DynamicResource Blue}"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <!-- the track either side of the thumb: invisible, but still clickable -->
    <Style x:Key="ScrollPage" TargetType="RepeatButton">
      <Setter Property="IsTabStop" Value="False"/>
      <Setter Property="Focusable" Value="False"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="RepeatButton">
            <Border Background="Transparent"/>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <!-- no arrow buttons: they are the part that renders as OS chrome -->
    <Style x:Key="ScrollArrow" TargetType="RepeatButton">
      <Setter Property="IsTabStop" Value="False"/>
      <Setter Property="Focusable" Value="False"/>
      <Setter Property="Height" Value="0"/>
      <Setter Property="Width" Value="0"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="RepeatButton">
            <Border Background="Transparent"/>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style TargetType="ScrollBar">
      <Setter Property="Background" Value="{DynamicResource Track}"/>
      <Setter Property="BorderThickness" Value="0"/>
      <Setter Property="Width" Value="11"/>
      <Setter Property="MinWidth" Value="11"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ScrollBar">
            <Grid Background="{TemplateBinding Background}">
              <Track x:Name="PART_Track" IsDirectionReversed="True">
                <Track.DecreaseRepeatButton>
                  <RepeatButton Command="ScrollBar.PageUpCommand"
                                Style="{StaticResource ScrollPage}"/>
                </Track.DecreaseRepeatButton>
                <Track.Thumb>
                  <Thumb Style="{StaticResource ScrollThumb}"/>
                </Track.Thumb>
                <Track.IncreaseRepeatButton>
                  <RepeatButton Command="ScrollBar.PageDownCommand"
                                Style="{StaticResource ScrollPage}"/>
                </Track.IncreaseRepeatButton>
              </Track>
            </Grid>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
      <Style.Triggers>
        <Trigger Property="Orientation" Value="Horizontal">
          <Setter Property="Width" Value="Auto"/>
          <Setter Property="MinWidth" Value="0"/>
          <Setter Property="Height" Value="11"/>
          <Setter Property="MinHeight" Value="11"/>
          <Setter Property="Template">
            <Setter.Value>
              <ControlTemplate TargetType="ScrollBar">
                <Grid Background="{TemplateBinding Background}">
                  <Track x:Name="PART_Track" IsDirectionReversed="False">
                    <Track.DecreaseRepeatButton>
                      <RepeatButton Command="ScrollBar.PageLeftCommand"
                                    Style="{StaticResource ScrollPage}"/>
                    </Track.DecreaseRepeatButton>
                    <Track.Thumb>
                      <Thumb Style="{StaticResource ScrollThumb}"/>
                    </Track.Thumb>
                    <Track.IncreaseRepeatButton>
                      <RepeatButton Command="ScrollBar.PageRightCommand"
                                    Style="{StaticResource ScrollPage}"/>
                    </Track.IncreaseRepeatButton>
                  </Track>
                </Grid>
              </ControlTemplate>
            </Setter.Value>
          </Setter>
        </Trigger>
      </Style.Triggers>
    </Style>

    <Style TargetType="ScrollViewer">
      <Setter Property="Background" Value="Transparent"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ScrollViewer">
            <Grid Background="{TemplateBinding Background}">
              <Grid.ColumnDefinitions>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="Auto"/>
              </Grid.ColumnDefinitions>
              <Grid.RowDefinitions>
                <RowDefinition Height="*"/>
                <RowDefinition Height="Auto"/>
              </Grid.RowDefinitions>
              <ScrollContentPresenter Grid.Row="0" Grid.Column="0"
                                      CanContentScroll="{TemplateBinding CanContentScroll}"
                                      Margin="{TemplateBinding Padding}"/>
              <ScrollBar x:Name="PART_VerticalScrollBar" Grid.Row="0" Grid.Column="1"
                         Orientation="Vertical"
                         Value="{TemplateBinding VerticalOffset}"
                         Maximum="{TemplateBinding ScrollableHeight}"
                         ViewportSize="{TemplateBinding ViewportHeight}"
                         Visibility="{TemplateBinding ComputedVerticalScrollBarVisibility}"/>
              <ScrollBar x:Name="PART_HorizontalScrollBar" Grid.Row="1" Grid.Column="0"
                         Orientation="Horizontal"
                         Value="{TemplateBinding HorizontalOffset}"
                         Maximum="{TemplateBinding ScrollableWidth}"
                         ViewportSize="{TemplateBinding ViewportWidth}"
                         Visibility="{TemplateBinding ComputedHorizontalScrollBarVisibility}"/>
            </Grid>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <!-- ===================== ticks and radios ===================== -->
    <Style TargetType="CheckBox">
      <Setter Property="Foreground" Value="{DynamicResource Text}"/>
      <Setter Property="Background" Value="{DynamicResource Input}"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="Margin" Value="8,3,8,3"/>
      <Setter Property="VerticalContentAlignment" Value="Center"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="CheckBox">
            <StackPanel Orientation="Horizontal" Background="Transparent">
              <Border x:Name="box" Width="14" Height="14" CornerRadius="2"
                      Background="{TemplateBinding Background}"
                      BorderBrush="{DynamicResource Edge}" BorderThickness="1"
                      VerticalAlignment="Center" SnapsToDevicePixels="True">
                <Path x:Name="tick" Stretch="None" Stroke="{DynamicResource OnBlue}" StrokeThickness="1.8"
                      Data="M 3,7 L 6,10 L 11,3" Visibility="Collapsed"
                      HorizontalAlignment="Left" VerticalAlignment="Top"/>
              </Border>
              <ContentPresenter Margin="7,0,0,0" VerticalAlignment="Center"
                                RecognizesAccessKey="True"/>
            </StackPanel>
            <ControlTemplate.Triggers>
              <Trigger Property="IsChecked" Value="True">
                <Setter TargetName="box" Property="Background" Value="{DynamicResource Blue}"/>
                <Setter TargetName="box" Property="BorderBrush" Value="{DynamicResource Blue}"/>
                <Setter TargetName="tick" Property="Visibility" Value="Visible"/>
              </Trigger>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="box" Property="BorderBrush" Value="{DynamicResource EdgeHover}"/>
              </Trigger>
              <Trigger Property="IsEnabled" Value="False">
                <Setter Property="Foreground" Value="{DynamicResource Disabled}"/>
                <Setter TargetName="box" Property="BorderBrush" Value="{DynamicResource Line}"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style TargetType="RadioButton">
      <Setter Property="Foreground" Value="{DynamicResource Text}"/>
      <Setter Property="Background" Value="{DynamicResource Input}"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="Margin" Value="8,3,8,3"/>
      <Setter Property="VerticalContentAlignment" Value="Center"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="RadioButton">
            <StackPanel Orientation="Horizontal" Background="Transparent">
              <Grid Width="14" Height="14" VerticalAlignment="Center">
                <Ellipse x:Name="ring" Fill="{TemplateBinding Background}"
                         Stroke="{DynamicResource Edge}" StrokeThickness="1"/>
                <Ellipse x:Name="dot" Width="6" Height="6" Fill="{DynamicResource Orange}"
                         Visibility="Collapsed"/>
              </Grid>
              <ContentPresenter Margin="7,0,0,0" VerticalAlignment="Center"
                                RecognizesAccessKey="True"/>
            </StackPanel>
            <ControlTemplate.Triggers>
              <Trigger Property="IsChecked" Value="True">
                <Setter TargetName="ring" Property="Stroke" Value="{DynamicResource Orange}"/>
                <Setter TargetName="dot" Property="Visibility" Value="Visible"/>
              </Trigger>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="ring" Property="Stroke" Value="{DynamicResource EdgeHover}"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>


    <!-- ComboBox renders a surface, so it gets a full template or it falls
         back to OS chrome and shows as a white box in a dark window. -->
    <Style x:Key="ComboArrow" TargetType="ToggleButton">
      <Setter Property="IsTabStop" Value="False"/>
      <Setter Property="Focusable" Value="False"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ToggleButton">
            <Border x:Name="bd" Background="{DynamicResource Input}" BorderBrush="{DynamicResource Line}"
                    BorderThickness="1" SnapsToDevicePixels="True">
              <Path x:Name="arrow" HorizontalAlignment="Right" VerticalAlignment="Center"
                    Margin="0,0,7,0" Fill="{DynamicResource Muted}" Stretch="None"
                    Data="M 0,0 L 8,0 L 4,5 Z"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="BorderBrush" Value="{DynamicResource Edge}"/>
                <Setter TargetName="arrow" Property="Fill" Value="{DynamicResource Text}"/>
              </Trigger>
              <Trigger Property="IsChecked" Value="True">
                <Setter TargetName="bd" Property="BorderBrush" Value="{DynamicResource Blue}"/>
                <Setter TargetName="arrow" Property="Fill" Value="{DynamicResource Blue}"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style TargetType="ComboBoxItem">
      <Setter Property="Foreground" Value="{DynamicResource Text}"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ComboBoxItem">
            <Border x:Name="bd" Background="Transparent" Padding="8,5,8,5"
                    SnapsToDevicePixels="True">
              <ContentPresenter/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="Background" Value="{DynamicResource Hover}"/>
              </Trigger>
              <Trigger Property="IsSelected" Value="True">
                <Setter TargetName="bd" Property="Background" Value="{DynamicResource Selection}"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style TargetType="ComboBox">
      <Setter Property="Foreground" Value="{DynamicResource Text}"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize" Value="11.5"/>
      <Setter Property="Height" Value="24"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ComboBox">
            <Grid>
              <ToggleButton Style="{StaticResource ComboArrow}" ClickMode="Press"
                            IsChecked="{Binding IsDropDownOpen, Mode=TwoWay,
                                        RelativeSource={RelativeSource TemplatedParent}}"/>
              <ContentPresenter IsHitTestVisible="False" Margin="8,0,22,0"
                                VerticalAlignment="Center" HorizontalAlignment="Left"
                                Content="{TemplateBinding SelectionBoxItem}"
                                ContentTemplate="{TemplateBinding SelectionBoxItemTemplate}"/>
              <Popup x:Name="PART_Popup" Placement="Bottom" Focusable="False"
                     AllowsTransparency="True" PopupAnimation="None"
                     IsOpen="{TemplateBinding IsDropDownOpen}">
                <Border Background="{DynamicResource Panel}" BorderBrush="{DynamicResource Line}"
                        BorderThickness="1" MaxHeight="320"
                        MinWidth="{Binding ActualWidth,
                                   RelativeSource={RelativeSource TemplatedParent}}">
                  <ScrollViewer VerticalScrollBarVisibility="Auto">
                    <ItemsPresenter/>
                  </ScrollViewer>
                </Border>
              </Popup>
            </Grid>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style TargetType="TextBox">
      <Setter Property="Background" Value="{DynamicResource Input}"/>
      <Setter Property="Foreground" Value="{DynamicResource Text}"/>
      <Setter Property="CaretBrush" Value="{DynamicResource Text}"/>
      <Setter Property="SelectionBrush" Value="{DynamicResource Selection}"/>
      <Setter Property="BorderBrush" Value="{DynamicResource Line}"/>
      <Setter Property="BorderThickness" Value="1"/>
      <Setter Property="Padding" Value="6,4,6,4"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="TextBox">
            <Border Background="{TemplateBinding Background}"
                    BorderBrush="{TemplateBinding BorderBrush}"
                    BorderThickness="{TemplateBinding BorderThickness}">
              <ScrollViewer x:Name="PART_ContentHost"
                            Margin="{TemplateBinding Padding}"
                            Background="Transparent"/>
            </Border>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="Flat" TargetType="Button">
      <Setter Property="Foreground" Value="{DynamicResource Blue}"/>
      <Setter Property="Background" Value="Transparent"/>
      <Setter Property="BorderThickness" Value="0"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize" Value="11"/>
      <Setter Property="Padding" Value="6,2,6,2"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="bd" Background="{TemplateBinding Background}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"
                                Margin="{TemplateBinding Padding}"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="Background" Value="{DynamicResource Hover}"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="Ghost" TargetType="Button">
      <Setter Property="Foreground" Value="{DynamicResource Text}"/>
      <Setter Property="Background" Value="{DynamicResource Btn}"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="Padding" Value="16,7,16,7"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="bd" Background="{TemplateBinding Background}"
                    BorderBrush="{DynamicResource Line}" BorderThickness="1">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"
                                Margin="{TemplateBinding Padding}"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="Background" Value="{DynamicResource BtnHover}"/>
              </Trigger>
              <Trigger Property="IsEnabled" Value="False">
                <Setter Property="Foreground" Value="{DynamicResource Disabled}"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="Danger" TargetType="Button">
      <Setter Property="Foreground" Value="{DynamicResource OnAccent}"/>
      <Setter Property="Background" Value="{DynamicResource Red}"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
      <Setter Property="Padding" Value="22,7,22,7"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="bd" Background="{TemplateBinding Background}"
                    BorderBrush="{DynamicResource RedEdge}" BorderThickness="1">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"
                                Margin="{TemplateBinding Padding}"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="Background" Value="{DynamicResource RedHover}"/>
              </Trigger>
              <Trigger Property="IsPressed" Value="True">
                <Setter TargetName="bd" Property="Background" Value="{DynamicResource RedPress}"/>
              </Trigger>
              <Trigger Property="IsEnabled" Value="False">
                <Setter TargetName="bd" Property="Background" Value="{DynamicResource RedDisabled}"/>
                <Setter Property="Foreground" Value="{DynamicResource RedDisabledText}"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <!-- green only when everything needed is picked -->
    <Style x:Key="Go" TargetType="Button">
      <Setter Property="Foreground" Value="{DynamicResource OnAccent}"/>
      <Setter Property="Background" Value="{DynamicResource Green}"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
      <Setter Property="Padding" Value="22,7,22,7"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="bd" Background="{TemplateBinding Background}"
                    BorderBrush="{DynamicResource GreenEdge}" BorderThickness="1">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"
                                Margin="{TemplateBinding Padding}"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="Background" Value="{DynamicResource GreenHover}"/>
              </Trigger>
              <Trigger Property="IsPressed" Value="True">
                <Setter TargetName="bd" Property="Background" Value="{DynamicResource GreenPress}"/>
              </Trigger>
              <Trigger Property="IsEnabled" Value="False">
                <Setter TargetName="bd" Property="Background" Value="{DynamicResource BtnDisabled}"/>
                <Setter TargetName="bd" Property="BorderBrush" Value="{DynamicResource Line}"/>
                <Setter Property="Foreground" Value="{DynamicResource Disabled}"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <!-- Shrink to the bottom of the screen. The glyph is a ContentTemplate,
         never a Path as Content: one element cannot sit in two windows. The
         Tag trigger swaps in the green up arrow while the window is shrunk. -->
    <DataTemplate x:Key="ShrinkGlyph">
      <Path Stretch="None" SnapsToDevicePixels="True"
            Fill="{Binding Foreground, RelativeSource={RelativeSource AncestorType=Button}}"
            Data="M 6.2,1 L 7.8,1 L 7.8,5.2 L 10.6,5.2 L 7,8.8 L 3.4,5.2 L 6.2,5.2 Z M 2,10.6 L 12,10.6 L 12,12.2 L 2,12.2 Z"/>
    </DataTemplate>
    <DataTemplate x:Key="ExpandGlyph">
      <Path Stretch="None" SnapsToDevicePixels="True" Fill="{DynamicResource Green}"
            Data="M 7,1.2 L 12.2,6.8 L 8.4,6.8 L 8.4,12.6 L 5.6,12.6 L 5.6,6.8 L 1.8,6.8 Z"/>
    </DataTemplate>
    <Style x:Key="ShrinkBtn" TargetType="Button">
      <Setter Property="Foreground" Value="{DynamicResource Text}"/>
      <Setter Property="Background" Value="Transparent"/>
      <Setter Property="Width" Value="34"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="ToolTip" Value="Shrink to the bottom of the screen"/>
      <Setter Property="ContentTemplate" Value="{StaticResource ShrinkGlyph}"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="bd" Background="{TemplateBinding Background}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="Background" Value="{DynamicResource Hover}"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
      <Style.Triggers>
        <Trigger Property="Tag" Value="shrunk">
          <Setter Property="ContentTemplate" Value="{StaticResource ExpandGlyph}"/>
          <Setter Property="ToolTip" Value="Expand the window (or double-click the bar)"/>
        </Trigger>
      </Style.Triggers>
    </Style>

    <Style x:Key="Close" TargetType="Button">
      <Setter Property="Foreground" Value="{DynamicResource Text}"/>
      <Setter Property="Background" Value="Transparent"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize" Value="13"/>
      <Setter Property="Width" Value="34"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="bd" Background="{TemplateBinding Background}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="Background" Value="{DynamicResource Red}"/>
                <Setter Property="Foreground" Value="White"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style TargetType="TabItem">
      <Setter Property="Foreground" Value="{DynamicResource Muted}"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="TabItem">
            <Border x:Name="bd" Background="Transparent" BorderBrush="Transparent"
                    BorderThickness="0,0,0,2" Padding="18,8,18,7" Margin="0,0,2,0">
              <ContentPresenter ContentSource="Header"
                                HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="Background" Value="{DynamicResource TabHover}"/>
              </Trigger>
              <Trigger Property="IsSelected" Value="True">
                <Setter TargetName="bd" Property="Background" Value="{DynamicResource WindowBg}"/>
                <Setter TargetName="bd" Property="BorderBrush" Value="{DynamicResource Orange}"/>
                <Setter Property="Foreground" Value="{DynamicResource Text}"/>
                <Setter Property="FontWeight" Value="SemiBold"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style TargetType="TabControl">
      <Setter Property="Background" Value="{DynamicResource WindowBg}"/>
      <Setter Property="BorderThickness" Value="0"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="TabControl">
            <Grid>
              <Grid.RowDefinitions>
                <RowDefinition Height="Auto"/>
                <RowDefinition Height="*"/>
              </Grid.RowDefinitions>
              <Border Grid.Row="0" Background="{DynamicResource Strip}" BorderBrush="{DynamicResource Line}"
                      BorderThickness="0,0,0,1">
                <TabPanel IsItemsHost="True" Margin="10,0,0,0"/>
              </Border>
              <Border Grid.Row="1" Background="{DynamicResource WindowBg}">
                <ContentPresenter ContentSource="SelectedContent"/>
              </Border>
            </Grid>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <!-- a blue primary action, and a smaller green one for dialogs -->
    <Style x:Key="Primary" TargetType="Button" BasedOn="{StaticResource Ghost}">
      <Setter Property="Background" Value="{DynamicResource Blue}"/>
      <Setter Property="Foreground" Value="{DynamicResource OnBlue}"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
    </Style>
    <Style x:Key="GoSmall" TargetType="Button" BasedOn="{StaticResource Go}">
      <Setter Property="Padding" Value="14,6,14,6"/>
    </Style>

    <!-- the house theme chip: a pill, a half-filled circle and a label -->
    <Style x:Key="ChipButton" TargetType="Button">
      <Setter Property="Foreground" Value="{DynamicResource Text}"/>
      <Setter Property="Background" Value="{DynamicResource Input}"/>
      <Setter Property="BorderBrush" Value="{DynamicResource Line}"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize" Value="11"/>
      <Setter Property="Padding" Value="9,3,10,3"/>
      <Setter Property="Margin" Value="0,0,8,0"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="VerticalAlignment" Value="Center"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="bd" Background="{TemplateBinding Background}"
                    BorderBrush="{TemplateBinding BorderBrush}" BorderThickness="1"
                    CornerRadius="10" Padding="{TemplateBinding Padding}">
              <ContentPresenter VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="bd" Property="Background" Value="{DynamicResource Hover}"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
"""

SHARED_TOKEN = u"    <!--SHARED_RESOURCES-->"



# Light half. Not the dark one inverted: the accents are darkened, because
# the dark accents are chosen to sit on a dark body and wash out on white.
LIGHT = {
    "WindowBg": "#E8ECF1",
    "Panel": "#F4F6F9",
    "Sunken": "#FFFFFF",
    "Input": "#FFFFFF",
    "HeadBar": "#DCE1E8",
    "Strip": "#CDD4DD",
    "TabHover": "#DCE1E8",
    "Scrim": "#8C2A3038",
    "Track": "#E8ECF1",
    "Thumb": "#B5BECA",
    "ThumbHover": "#97A1AF",
    "Line": "#C3CBD6",
    "Edge": "#8A94A3",
    "EdgeHover": "#5E6878",
    "Text": "#1C2330",
    "Muted": "#55606F",
    "Disabled": "#8C95A3",
    "OnAccent": "#FFFFFF",
    "OnBlue": "#FFFFFF",
    "Btn": "#E2E7EE",
    "BtnHover": "#D3DAE3",
    "BtnDisabled": "#EDF0F4",
    "Hover": "#DCE3EC",
    "Selection": "#CFE2F6",
    "Blue": "#1B72BE",
    "Orange": "#B96A12",
    "OrangeWash": "#F8E8D4",
    "Green": "#2E8546",
    "GreenHover": "#379A53",
    "GreenPress": "#256C39",
    "GreenEdge": "#22663A",
    "Red": "#B5342A",
    "RedHover": "#C9473B",
    "RedPress": "#962A20",
    "RedEdge": "#8E2A20",
    "RedDisabled": "#E5C9C5",
    "RedDisabledText": "#8C6F6B",
}

PALETTES = {"dark": DARK, "light": LIGHT}

# theme_mode is stored as follow / dark / light, so following Revit is a state
# rather than the absence of a choice. The chip cycles in this order.
THEME_MODES = ["follow", "dark", "light"]
THEME_LABELS = {"follow": "Auto", "dark": "Dark", "light": "Light"}
THEME = {"mode": "follow", "name": "dark", "read_as": ""}

# every open window that should repaint when the theme changes
THEMED = []


def load_xaml(text):
    """Parse a window with the shared resources dropped in."""
    full = text.replace(SHARED_TOKEN, SHARED_RESOURCES)
    return XamlReader.Load(XmlReader.Create(StringReader(full)))


def make_brush(hex_value):
    colour = ColorConverter.ConvertFromString(hex_value)
    brush = SolidColorBrush(colour)
    try:
        brush.Freeze()
    except Exception:
        pass
    return brush


def revit_theme(fallback="dark"):
    """What Revit is drawing in: canvas first.

    UIThemeManager only exists from 2024, so it is reached by getattr on the
    namespace rather than imported - an import would fail at load on anything
    older. Its values are compared by name, and tested 'is not None': UITheme.Dark
    is 0, so an 'or' would treat dark as a failed read and fall through to light.
    """
    try:
        import Autodesk.Revit.UI as revit_ui
        manager = getattr(revit_ui, "UIThemeManager", None)
    except Exception:
        manager = None

    if manager is not None:
        try:
            value = getattr(manager, "CurrentCanvasTheme", None)
            if value is not None:
                text = str(value).lower()
                if "dark" in text:
                    return "dark", "canvas theme: dark"
                if "light" in text:
                    return "light", "canvas theme: light"
        except Exception:
            pass

    # the canvas background itself, by luminance
    try:
        colour = app.BackgroundColor
        if colour is not None and getattr(colour, "IsValid", True):
            lum = (0.2126 * colour.Red + 0.7152 * colour.Green +
                   0.0722 * colour.Blue) / 255.0
            if lum < 0.5:
                return "dark", "canvas background is dark"
            return "light", "canvas background is light"
    except Exception:
        pass

    if manager is not None:
        try:
            value = getattr(manager, "CurrentTheme", None)
            if value is not None:
                text = str(value).lower()
                if "dark" in text:
                    return "dark", "Revit theme: dark"
                if "light" in text:
                    return "light", "Revit theme: light"
        except Exception:
            pass
    return fallback, "nothing to read - dark"


def resolve_theme():
    mode = THEME.get("mode", "follow")
    if mode in ("dark", "light"):
        THEME["name"] = mode
        THEME["read_as"] = "set by hand"
    else:
        THEME["name"], THEME["read_as"] = revit_theme()
    return THEME["name"]


def apply_palette(window, name=None):
    """Write the palette onto window.Resources.

    window.Resources sits in front of anything merged in, and every colour in
    the layouts is a DynamicResource, so this repaints an open window in place.
    """
    palette = PALETTES.get(name or THEME.get("name", "dark"), DARK)
    for key in palette:
        try:
            window.Resources[key] = make_brush(palette[key])
        except Exception:
            continue


def paint_chip(window):
    try:
        label = window.FindName("ThemeChipText")
        if label is not None:
            label.Text = THEME_LABELS.get(THEME.get("mode", "follow"), "Auto")
        chip = window.FindName("ThemeChip")
        if chip is not None:
            mode = THEME.get("mode", "follow")
            if mode == "follow":
                tip = "Auto - following Revit ({0}). Click for Dark.".format(
                    THEME.get("read_as", ""))
            elif mode == "dark":
                tip = "Dark. Click for Light."
            else:
                tip = "Light. Click for Auto."
            chip.ToolTip = tip
    except Exception:
        pass


class Themed(object):
    """Hook a window up to the shared theme: chip, palette, auto re-check."""

    def __init__(self, window, on_repaint=None):
        self.window = window
        self.on_repaint = on_repaint
        THEMED.append(self)
        apply_palette(window)
        paint_chip(window)
        try:
            chip = window.FindName("ThemeChip")
            if chip is not None:
                chip.Click += self.on_chip
        except Exception:
            pass
        window.Activated += self.on_activated
        window.Closed += self.on_closed

    def on_chip(self, sender, args):
        try:
            mode = THEME.get("mode", "follow")
            index = THEME_MODES.index(mode) if mode in THEME_MODES else 0
            THEME["mode"] = THEME_MODES[(index + 1) % len(THEME_MODES)]
            SETTINGS["theme_mode"] = THEME["mode"]
            save_settings()
            repaint_all()
        except Exception:
            pass

    def on_activated(self, sender, args):
        # Auto re-reads Revit whenever a window comes to the front, so
        # changing Revit's theme is picked up without reopening the tool.
        if THEME.get("mode") != "follow":
            return
        before = THEME.get("name")
        resolve_theme()
        if THEME.get("name") != before:
            repaint_all()
        else:
            for themed in list(THEMED):
                paint_chip(themed.window)

    def on_closed(self, sender, args):
        try:
            THEMED.remove(self)
        except ValueError:
            pass

    def repaint(self):
        apply_palette(self.window)
        paint_chip(self.window)
        if self.on_repaint is not None:
            try:
                self.on_repaint()
            except Exception:
                pass


def repaint_all():
    resolve_theme()
    for themed in list(THEMED):
        try:
            themed.repaint()
        except Exception:
            pass


# ---------------------------------------------------------------------------
#  General settings - one key=value file
# ---------------------------------------------------------------------------
SETTINGS_FILE = "view_manager_settings.txt"
SETTINGS_DEFAULTS = {
    "theme_mode": "follow",
    "room_tags_on": "1",          # the Add room tags tick, when the tool opens
    "room_tag_type": "",          # "Family : Type"; blank = the project default
    "room_tags_links": "1",       # tag rooms in loaded links as well
}
SETTINGS = dict(SETTINGS_DEFAULTS)


def settings_path():
    return os.path.join(settings_folder(), SETTINGS_FILE)


def load_settings():
    SETTINGS.clear()
    SETTINGS.update(SETTINGS_DEFAULTS)
    try:
        path = settings_path()
        if os.path.isfile(path):
            handle = codecs.open(path, "r", "utf-8")
            try:
                for line in handle:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    SETTINGS[key.strip()] = value.strip()
            finally:
                handle.close()
    except Exception:
        pass
    mode = SETTINGS.get("theme_mode", "follow")
    THEME["mode"] = mode if mode in THEME_MODES else "follow"


def save_settings():
    try:
        handle = codecs.open(settings_path(), "w", "utf-8")
        try:
            handle.write(u"# RevoBIM PY - View Manager settings\n")
            for key in sorted(SETTINGS.keys()):
                handle.write(u"{0}={1}\n".format(key, SETTINGS[key]))
        finally:
            handle.close()
        return True, ""
    except Exception as ex:
        return False, describe(ex)


def setting_on(key):
    return str(SETTINGS.get(key, SETTINGS_DEFAULTS.get(key, "0"))).strip() in (
        "1", "true", "True", "yes")


# ---------------------------------------------------------------------------
#  XAML - main window
# ---------------------------------------------------------------------------
XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        xmlns:shell="clr-namespace:System.Windows.Shell;assembly=PresentationFramework"
        Title="RevoBIM PY - View Manager"
        Height="690" Width="1000" MinHeight="520" MinWidth="860"
        WindowStartupLocation="CenterScreen"
        WindowStyle="None" ResizeMode="CanResize"
        Background="{DynamicResource WindowBg}" ShowInTaskbar="True">

  <shell:WindowChrome.WindowChrome>
    <shell:WindowChrome CaptionHeight="0" CornerRadius="0"
                        GlassFrameThickness="0" ResizeBorderThickness="6"/>
  </shell:WindowChrome.WindowChrome>

  <Window.Resources>
    <!--SHARED_RESOURCES-->
  </Window.Resources>

  <Border BorderBrush="{DynamicResource Line}" BorderThickness="1" Background="{DynamicResource WindowBg}">
    <Grid>
      <Grid.RowDefinitions>
        <RowDefinition Height="38"/>
        <RowDefinition Height="*"/>
        <RowDefinition Height="Auto"/>
      </Grid.RowDefinitions>

      <!-- header -->
      <Border x:Name="Header" Grid.Row="0" Background="{DynamicResource HeadBar}">
        <Grid>
          <StackPanel Orientation="Horizontal" VerticalAlignment="Center" Margin="12,0,0,0">
            <TextBlock Text="RevoBIM" Foreground="{DynamicResource Blue}"
                       FontSize="13" FontWeight="Bold"/>
            <TextBlock x:Name="ToolLabel" Text="  View Manager" FontSize="13"/>
          </StackPanel>
          <StackPanel Orientation="Horizontal" HorizontalAlignment="Right" VerticalAlignment="Center">
            <Button x:Name="BtnRefresh" Content="Refresh" Style="{StaticResource Flat}"
                    Margin="0,0,2,0" ToolTip="Re-read the model (F5)"/>
            <Button x:Name="BtnSettings" Style="{StaticResource Flat}" Margin="0,0,6,0"
                    ToolTip="Template abbreviations">
              <StackPanel Orientation="Horizontal">
                <Path Stretch="None" Stroke="{DynamicResource Blue}" StrokeThickness="1.3"
                      VerticalAlignment="Center" Margin="0,0,5,0"
                      Data="M 6,1 L 8,1 L 8.4,2.9 L 10.1,3.6 L 11.7,2.5 L 13.1,3.9 L 12,5.5 L 12.7,7.2 L 14.6,7.6 L 14.6,9.6 L 12.7,10 L 12,11.7 L 13.1,13.3 L 11.7,14.7 L 10.1,13.6 L 8.4,14.3 L 8,16.2 L 6,16.2 L 5.6,14.3 L 3.9,13.6 L 2.3,14.7 L 0.9,13.3 L 2,11.7 L 1.3,10 L -0.6,9.6 L -0.6,7.6 L 1.3,7.2 L 2,5.5 L 0.9,3.9 L 2.3,2.5 L 3.9,3.6 L 5.6,2.9 Z"/>
                <TextBlock Text="Settings" VerticalAlignment="Center"
                           Foreground="{DynamicResource Blue}" FontSize="11"/>
              </StackPanel>
            </Button>
            <Button x:Name="ThemeChip" Style="{StaticResource ChipButton}">
              <StackPanel Orientation="Horizontal">
                <Grid Width="12" Height="12" Margin="0,0,6,0" VerticalAlignment="Center">
                  <Ellipse Stroke="{DynamicResource Text}" StrokeThickness="1.2"/>
                  <Path Fill="{DynamicResource Text}" Data="M 6,0.6 A 5.4,5.4 0 0 0 6,11.4 Z"/>
                </Grid>
                <TextBlock x:Name="ThemeChipText" Text="Auto" VerticalAlignment="Center"
                           FontSize="11"/>
              </StackPanel>
            </Button>
            <TextBlock x:Name="VersionLabel" Text="v0.0.0" Foreground="{DynamicResource Muted}"
                       FontSize="10" VerticalAlignment="Center" Margin="0,0,10,0"/>
            <Button x:Name="BtnShrink" Content="" Style="{StaticResource ShrinkBtn}" Height="38"/>
            <Button x:Name="BtnClose" Content="&#x2715;" Style="{StaticResource Close}" Height="38"/>
          </StackPanel>
        </Grid>
      </Border>

      <!-- tabs -->
      <TabControl x:Name="Tabs" Grid.Row="1">

        <!-- ============================ TAB 1 ============================ -->
        <!-- ====================== TAB 1 - Create Views ====================== -->
        <TabItem>
        <TabItem.Header>
          <StackPanel Orientation="Horizontal">
            <Grid Width="15" Height="15" Margin="0,0,7,0" VerticalAlignment="Center">
              <Path Stretch="None" Stroke="{DynamicResource Green}" StrokeThickness="1.3"
                    Data="M 1,1 L 9,1 L 9,14 L 1,14 Z"/>
              <Path Stretch="None" Stroke="{DynamicResource Green}" StrokeThickness="1.3"
                    Data="M 3,4 L 7,4 M 3,6.5 L 7,6.5"/>
              <Path Stretch="None" Stroke="{DynamicResource Green}" StrokeThickness="1.7"
                    Data="M 11.5,7 L 11.5,13 M 8.5,10 L 14.5,10"/>
            </Grid>
            <TextBlock Text="Create Views" VerticalAlignment="Center"/>
          </StackPanel>
        </TabItem.Header>
          <Grid Margin="12,12,12,6">
            <Grid.ColumnDefinitions>
              <ColumnDefinition Width="1.35*"/>
              <ColumnDefinition Width="10"/>
              <ColumnDefinition Width="1*"/>
              <ColumnDefinition Width="10"/>
              <ColumnDefinition Width="1*"/>
            </Grid.ColumnDefinitions>

            <!-- view templates -->
            <Border Grid.Column="0" Background="{DynamicResource Panel}"
                    BorderBrush="{DynamicResource Line}" BorderThickness="1">
              <Grid>
                <Grid.RowDefinitions>
                  <RowDefinition Height="Auto"/>
                  <RowDefinition Height="Auto"/>
                  <RowDefinition Height="*"/>
                </Grid.RowDefinitions>
                <Grid Grid.Row="0" Margin="10,8,10,4">
                  <TextBlock x:Name="TplHead" Text="VIEW TEMPLATES" Style="{StaticResource Head}"
                             VerticalAlignment="Center"/>
                  <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
                    <Button x:Name="BtnTplAll"  Content="All"  Style="{StaticResource Flat}"/>
                    <Button x:Name="BtnTplNone" Content="None" Style="{StaticResource Flat}"/>
                  </StackPanel>
                </Grid>
                <Grid Grid.Row="1" Margin="10,0,10,8">
                  <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="8"/>
                    <ColumnDefinition Width="Auto"/>
                  </Grid.ColumnDefinitions>
                  <TextBox x:Name="TplSearch" Grid.Column="0"/>
                  <ComboBox x:Name="TplFilter" Grid.Column="2" Width="186"
                            ToolTip="Sort and filter by view family and type"/>
                </Grid>
                <Border Grid.Row="2" Background="{DynamicResource Sunken}"
                        BorderBrush="{DynamicResource Line}" BorderThickness="1"
                        Margin="10,0,10,10">
                  <ScrollViewer VerticalScrollBarVisibility="Auto" HorizontalScrollBarVisibility="Disabled">
                    <StackPanel x:Name="TplList" Margin="2,6,2,6"/>
                  </ScrollViewer>
                </Border>
              </Grid>
            </Border>

            <!-- levels -->
            <Border Grid.Column="2" Background="{DynamicResource Panel}"
                    BorderBrush="{DynamicResource Line}" BorderThickness="1">
              <Grid>
                <Grid.RowDefinitions>
                  <RowDefinition Height="Auto"/>
                  <RowDefinition Height="Auto"/>
                  <RowDefinition Height="*"/>
                </Grid.RowDefinitions>
                <Grid Grid.Row="0" Margin="10,8,10,4">
                  <TextBlock x:Name="LvlHead" Text="LEVELS" Style="{StaticResource Head}"
                             VerticalAlignment="Center"/>
                  <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
                    <Button x:Name="BtnLvlAll"  Content="All"  Style="{StaticResource Flat}"/>
                    <Button x:Name="BtnLvlNone" Content="None" Style="{StaticResource Flat}"/>
                  </StackPanel>
                </Grid>
                <TextBox x:Name="LvlSearch" Grid.Row="1" Margin="10,0,10,8"/>
                <Border Grid.Row="2" Background="{DynamicResource Sunken}"
                        BorderBrush="{DynamicResource Line}" BorderThickness="1"
                        Margin="10,0,10,10">
                  <ScrollViewer VerticalScrollBarVisibility="Auto" HorizontalScrollBarVisibility="Disabled">
                    <StackPanel x:Name="LvlList" Margin="2,6,2,6"/>
                  </ScrollViewer>
                </Border>
              </Grid>
            </Border>

            <!-- scope box, single pick -->
            <Border Grid.Column="4" Background="{DynamicResource Panel}"
                    BorderBrush="{DynamicResource Line}" BorderThickness="1">
              <Grid>
                <Grid.RowDefinitions>
                  <RowDefinition Height="Auto"/>
                  <RowDefinition Height="Auto"/>
                  <RowDefinition Height="*"/>
                </Grid.RowDefinitions>
                <Grid Grid.Row="0" Margin="10,8,10,4">
                  <TextBlock x:Name="CvBoxHead" Text="SCOPE BOX  (pick one)"
                             Style="{StaticResource Head}" VerticalAlignment="Center"/>
                  <Button x:Name="BtnCvBoxNone" Content="Clear" Style="{StaticResource Flat}"
                          HorizontalAlignment="Right"/>
                </Grid>
                <TextBox x:Name="CvBoxSearch" Grid.Row="1" Margin="10,0,10,8"/>
                <Border Grid.Row="2" Background="{DynamicResource Sunken}"
                        BorderBrush="{DynamicResource Line}" BorderThickness="1"
                        Margin="10,0,10,10">
                  <ScrollViewer VerticalScrollBarVisibility="Auto" HorizontalScrollBarVisibility="Disabled">
                    <StackPanel x:Name="CvBoxList" Margin="2,6,2,6"/>
                  </ScrollViewer>
                </Border>
              </Grid>
            </Border>
          </Grid>
        </TabItem>
        <!-- ==================== TAB 2 - Dependent Views ===================== -->
        <TabItem>
        <TabItem.Header>
          <StackPanel Orientation="Horizontal">
            <Grid Width="15" Height="15" Margin="0,0,7,0" VerticalAlignment="Center">
              <Path Stretch="None" Stroke="{DynamicResource Orange}" StrokeThickness="1.3"
                    Data="M 3,1 L 12,1 L 12,5 L 3,5 Z"/>
              <Path Stretch="None" Stroke="{DynamicResource Muted}" StrokeThickness="1.1"
                    Data="M 7.5,5 L 7.5,7.5 M 3,7.5 L 12,7.5 M 3,7.5 L 3,9.5 M 12,7.5 L 12,9.5"/>
              <Path Stretch="None" Stroke="{DynamicResource Orange}" StrokeThickness="1.3"
                    Data="M 0.5,9.5 L 5.5,9.5 L 5.5,13.5 L 0.5,13.5 Z M 9.5,9.5 L 14.5,9.5 L 14.5,13.5 L 9.5,13.5 Z"/>
            </Grid>
            <TextBlock Text="Dependent Views" VerticalAlignment="Center"/>
          </StackPanel>
        </TabItem.Header>
          <Grid Margin="12,12,12,6">
            <Grid.ColumnDefinitions>
              <ColumnDefinition Width="2*"/>
              <ColumnDefinition Width="12"/>
              <ColumnDefinition Width="1.15*"/>
            </Grid.ColumnDefinitions>

            <Border Grid.Column="0" Background="{DynamicResource Panel}"
                    BorderBrush="{DynamicResource Line}" BorderThickness="1">
              <Grid>
                <Grid.RowDefinitions>
                  <RowDefinition Height="Auto"/>
                  <RowDefinition Height="Auto"/>
                  <RowDefinition Height="Auto"/>
                  <RowDefinition Height="*"/>
                </Grid.RowDefinitions>
                <Grid Grid.Row="0" Margin="10,8,10,4">
                  <TextBlock x:Name="ViewsHead" Text="HOST VIEWS" Style="{StaticResource Head}"
                             VerticalAlignment="Center"/>
                  <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
                    <Button x:Name="BtnViewsAll"  Content="All"  Style="{StaticResource Flat}"/>
                    <Button x:Name="BtnViewsNone" Content="None" Style="{StaticResource Flat}"/>
                  </StackPanel>
                </Grid>
                <Grid Grid.Row="1" Margin="10,0,10,8">
                  <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="8"/>
                    <ColumnDefinition Width="Auto"/>
                  </Grid.ColumnDefinitions>
                  <TextBox x:Name="ViewSearch" Grid.Column="0"/>
                  <ComboBox x:Name="ViewFilter" Grid.Column="2" Width="186"
                            ToolTip="Sort and filter by view family and type"/>
                </Grid>

                <Border x:Name="IsolateChip" Grid.Row="2" Margin="10,0,10,8"
                        Visibility="Collapsed" Background="{DynamicResource OrangeWash}"
                        BorderBrush="{DynamicResource Orange}" BorderThickness="1"
                        CornerRadius="2">
                  <Grid Margin="8,4,4,4">
                    <TextBlock x:Name="IsolateText" Text="" FontSize="11"
                               Foreground="{DynamicResource Orange}"
                               VerticalAlignment="Center"/>
                    <Button x:Name="BtnShowAll" Content="Show all views"
                            Style="{StaticResource Flat}" HorizontalAlignment="Right"/>
                  </Grid>
                </Border>

                <Border Grid.Row="3" Background="{DynamicResource Sunken}"
                        BorderBrush="{DynamicResource Line}" BorderThickness="1"
                        Margin="10,0,10,10">
                  <ScrollViewer VerticalScrollBarVisibility="Auto" HorizontalScrollBarVisibility="Disabled">
                    <StackPanel x:Name="ViewList" Margin="2,6,2,6"/>
                  </ScrollViewer>
                </Border>
              </Grid>
            </Border>

            <Border Grid.Column="2" Background="{DynamicResource Panel}"
                    BorderBrush="{DynamicResource Line}" BorderThickness="1">
              <Grid>
                <Grid.RowDefinitions>
                  <RowDefinition Height="Auto"/>
                  <RowDefinition Height="Auto"/>
                  <RowDefinition Height="*"/>
                </Grid.RowDefinitions>
                <Grid Grid.Row="0" Margin="10,8,10,4">
                  <TextBlock x:Name="BoxesHead" Text="SCOPE BOXES" Style="{StaticResource Head}"
                             VerticalAlignment="Center"/>
                  <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
                    <Button x:Name="BtnBoxesAll"  Content="All"  Style="{StaticResource Flat}"/>
                    <Button x:Name="BtnBoxesNone" Content="None" Style="{StaticResource Flat}"/>
                  </StackPanel>
                </Grid>
                <TextBox x:Name="BoxSearch" Grid.Row="1" Margin="10,0,10,8"/>
                <Border Grid.Row="2" Background="{DynamicResource Sunken}"
                        BorderBrush="{DynamicResource Line}" BorderThickness="1"
                        Margin="10,0,10,10">
                  <ScrollViewer VerticalScrollBarVisibility="Auto" HorizontalScrollBarVisibility="Disabled">
                    <StackPanel x:Name="BoxList" Margin="2,6,2,6"/>
                  </ScrollViewer>
                </Border>
              </Grid>
            </Border>
          </Grid>
        </TabItem>

      </TabControl>

      <!-- the ask-before-creating overlay. In the window rather than a
           window of its own: a modal child would disable Revit too. -->
      <Grid x:Name="AskOverlay" Grid.Row="0" Grid.RowSpan="3"
            Background="{DynamicResource Scrim}" Visibility="Collapsed" Panel.ZIndex="10">
        <Border Background="{DynamicResource Panel}" BorderBrush="{DynamicResource Line}"
                BorderThickness="1" CornerRadius="3" Width="560"
                HorizontalAlignment="Center" VerticalAlignment="Center">
          <StackPanel Margin="22,18,22,18">
            <StackPanel Orientation="Horizontal" Margin="0,0,0,12">
              <Border Width="4" Background="{DynamicResource Orange}" Margin="0,0,9,0"/>
              <TextBlock Text="Hide links while cropping?" FontSize="15"
                         FontWeight="SemiBold" VerticalAlignment="Center"/>
            </StackPanel>

            <TextBlock TextWrapping="Wrap" Foreground="{DynamicResource Text}"
                       Margin="0,0,0,10"
                       Text="Assigning a scope box makes Revit work out the crop against everything a new view can see - which on this model means every linked IFC. That is where the time goes."/>
            <TextBlock TextWrapping="Wrap" Foreground="{DynamicResource Muted}"
                       Margin="0,0,0,8"
                       Text="Fast create hides links, coordination models, point clouds and all user worksets in each new view before the scope box goes on, so the crop is worked out against nothing. The view template is applied straight afterwards and sets the visibility that actually belongs on the view, and the worksets are handed back to the global setting."/>
            <TextBlock x:Name="AskWarn" TextWrapping="Wrap"
                       Foreground="{DynamicResource Muted}" FontSize="11"
                       Margin="0,0,0,14"
                       Text="Where the view template does not control links or worksets, the finished view keeps the global setting - the same as a view made by hand."/>

            <CheckBox x:Name="AskRemember" Content="Do not ask again this session"
                      Margin="0,0,0,16"/>

            <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
              <Button x:Name="AskCancel" Content="Cancel" Style="{StaticResource Flat}"
                      Margin="0,0,10,0"/>
              <Button x:Name="AskNormal" Content="Create normally"
                      Style="{StaticResource Ghost}" Margin="0,0,8,0"/>
              <Button x:Name="AskFast" Content="Fast create"
                      Style="{StaticResource Go}" IsEnabled="True"/>
            </StackPanel>
          </StackPanel>
        </Border>
      </Grid>

      <!-- footer -->
      <Border Grid.Row="2" Background="{DynamicResource HeadBar}" BorderBrush="{DynamicResource Line}"
              BorderThickness="0,1,0,0">
       <Grid>
        <Grid.RowDefinitions>
          <RowDefinition Height="3"/>
          <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <!-- progress strip: two Borders rather than a ProgressBar, which
             would fall back to OS chrome like every other stock control -->
        <Grid x:Name="ProgTrack" Grid.Row="0" Background="{DynamicResource Strip}">
          <Border x:Name="ProgFill" Background="{DynamicResource Green}" Width="0"
                  HorizontalAlignment="Left"/>
        </Grid>

        <Grid Grid.Row="1" Margin="12,10,12,10">
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="Auto"/>
            <ColumnDefinition Width="*"/>
            <ColumnDefinition Width="Auto"/>
          </Grid.ColumnDefinitions>

          <StackPanel Grid.Column="0" Orientation="Horizontal" VerticalAlignment="Center">
            <CheckBox x:Name="ChkDebug" Content="Debug"
                      VerticalAlignment="Center" Margin="0,0,14,0"
                      ToolTip="Record every step and open a report to copy."/>
            <CheckBox x:Name="ChkRoomTags" Content="Add room tags"
                      VerticalAlignment="Center" Margin="0,0,14,0"
                      ToolTip="Tag every room each new plan cuts. The tag is chosen in Settings."/>
          </StackPanel>

          <TextBlock x:Name="Status" Grid.Column="1" Text="Ready."
                     Foreground="{DynamicResource Muted}"
                     VerticalAlignment="Center" TextTrimming="CharacterEllipsis"/>

          <StackPanel Grid.Column="2" Orientation="Horizontal" HorizontalAlignment="Right">
            <Button x:Name="BtnReport" Content="Debug report" Style="{StaticResource Ghost}"
                    Margin="0,0,8,0" Visibility="Collapsed"/>
            <Button x:Name="BtnCancel" Content="Close" Style="{StaticResource Ghost}" Margin="0,0,8,0"/>
            <Button x:Name="BtnApply"  Content="Apply Dependents" Style="{StaticResource Danger}"/>
            <Button x:Name="BtnCreate" Content="Create Views" Style="{StaticResource Go}"
                    Visibility="Collapsed" IsEnabled="False"/>
          </StackPanel>
        </Grid>
       </Grid>
      </Border>
    </Grid>
  </Border>
</Window>
"""


# ---------------------------------------------------------------------------
#  XAML - debug report window
# ---------------------------------------------------------------------------
DEBUG_XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        xmlns:shell="clr-namespace:System.Windows.Shell;assembly=PresentationFramework"
        Title="RevoBIM PY - View Manager debug"
        Height="620" Width="860" MinHeight="380" MinWidth="560"
        WindowStartupLocation="CenterOwner"
        WindowStyle="None" ResizeMode="CanResize" Background="{DynamicResource WindowBg}">

  <shell:WindowChrome.WindowChrome>
    <shell:WindowChrome CaptionHeight="0" CornerRadius="0"
                        GlassFrameThickness="0" ResizeBorderThickness="6"/>
  </shell:WindowChrome.WindowChrome>

  <Window.Resources>
    <!--SHARED_RESOURCES-->
  </Window.Resources>

  <Border BorderBrush="{DynamicResource Line}" BorderThickness="1">
    <Grid>
      <Grid.RowDefinitions>
        <RowDefinition Height="38"/>
        <RowDefinition Height="Auto"/>
        <RowDefinition Height="*"/>
        <RowDefinition Height="Auto"/>
      </Grid.RowDefinitions>

      <Border x:Name="DbgHeader" Grid.Row="0" Background="{DynamicResource HeadBar}">
        <Grid>
          <StackPanel Orientation="Horizontal" VerticalAlignment="Center" Margin="12,0,0,0">
            <TextBlock Text="RevoBIM" Foreground="{DynamicResource Blue}" FontSize="13" FontWeight="Bold"/>
            <TextBlock Text="  View Manager debug" FontSize="13"/>
          </StackPanel>
          <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
            <Button x:Name="ThemeChip" Style="{StaticResource ChipButton}">
              <StackPanel Orientation="Horizontal">
                <Grid Width="12" Height="12" Margin="0,0,6,0" VerticalAlignment="Center">
                  <Ellipse Stroke="{DynamicResource Text}" StrokeThickness="1.2"/>
                  <Path Fill="{DynamicResource Text}" Data="M 6,0.6 A 5.4,5.4 0 0 0 6,11.4 Z"/>
                </Grid>
                <TextBlock x:Name="ThemeChipText" Text="Auto" VerticalAlignment="Center"
                           FontSize="11"/>
              </StackPanel>
            </Button>
            <Button x:Name="DbgShrink" Content="" Style="{StaticResource ShrinkBtn}" Height="38"/>
            <Button x:Name="DbgClose" Content="&#x2715;" Style="{StaticResource Close}" Height="38"/>
          </StackPanel>
        </Grid>
      </Border>

      <TextBlock Grid.Row="1" Margin="14,12,14,8" TextWrapping="Wrap"
                 Foreground="{DynamicResource Muted}"
                 Text="Press Copy, then paste the whole thing into the Claude chat. It carries the Revit build, what was picked, and the exact reason each view was refused."/>

      <Border Grid.Row="2" Margin="14,0,14,10" Background="{DynamicResource Input}"
              BorderBrush="{DynamicResource Line}" BorderThickness="1">
        <TextBox x:Name="DbgText" Background="Transparent" Foreground="{DynamicResource Text}"
                 BorderThickness="0" Padding="10"
                 FontFamily="Consolas" FontSize="11.5"
                 IsReadOnly="True" AcceptsReturn="True" TextWrapping="NoWrap"
                 VerticalScrollBarVisibility="Auto" HorizontalScrollBarVisibility="Auto"/>
      </Border>

      <Border Grid.Row="3" Background="{DynamicResource HeadBar}" BorderBrush="{DynamicResource Line}"
              BorderThickness="0,1,0,0">
        <Grid Margin="14,10,14,10">
          <TextBlock x:Name="DbgStatus" Text="" Foreground="{DynamicResource Muted}"
                     VerticalAlignment="Center"/>
          <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
            <Button x:Name="DbgSave" Content="Save to file" Style="{StaticResource Ghost}"
                    Margin="0,0,8,0"/>
            <Button x:Name="DbgCopy" Content="Copy" Style="{StaticResource Primary}"/>
          </StackPanel>
        </Grid>
      </Border>
    </Grid>
  </Border>
</Window>
"""


# ---------------------------------------------------------------------------
#  The external event - the only route a modeless window has to the model
# ---------------------------------------------------------------------------
class ViewManagerEventHandler(IExternalEventHandler):

    def __init__(self):
        self.job = None

    def Execute(self, event_uiapp):
        job = self.job
        self.job = None
        if job is None:
            return
        try:
            job(event_uiapp)
        except Exception:
            try:
                handle = open(os.path.join(log_folder(), "view_manager_last_error.txt"), "w")
                try:
                    handle.write("RevoBIM PY - View Manager v{0}\n".format(VERSION))
                    handle.write(traceback.format_exc())
                finally:
                    handle.close()
            except Exception:
                pass

    def GetName(self):
        return "RevoBIM PY - View Manager"


# ---------------------------------------------------------------------------
#  Shrink to the bottom of the screen - every window in the tool
# ---------------------------------------------------------------------------
# Same mechanics as the Pro Sheets Chrome: Top and Height eased together on a
# DispatcherTimer, because a Storyboard on a borderless window's Top/Height
# fights the layout pass.
SHRINK_MS = 280.0        # length of the slide either way
SHRINK_FRAME_MS = 15     # timer interval
SHRINK_MARGIN = 8        # lowest bar sits this far above the working area
SHRINK_GAP = 4           # gap between stacked bars
SHRINK_FALLBACK_BAR = 40

# Every live Chrome, so a dialog can find its owner's and bars can stack.
# Module level, or the persistent engine collects them.
_CHROMES = []


def ease_out(p):
    """1-(1-p)^3: quick off the mark, settles gently."""
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0
    return 1.0 - (1.0 - p) ** 3


def shrunk_top(area_bottom, bar, slot, margin=SHRINK_MARGIN, gap=SHRINK_GAP):
    """Where a bar lands: the bottom of the working area, above lower bars."""
    return area_bottom - margin - bar - slot * (bar + gap)


def same_object(a, b):
    if a is None or b is None:
        return False
    if a is b:
        return True
    try:
        return bool(a == b)
    except Exception:
        return False


def chrome_of(window):
    for chrome in _CHROMES:
        if same_object(chrome.window, window):
            return chrome
    return None


def inside_button(element, stop):
    """Did a click land on a button inside the header?"""
    node = element
    for _guard in range(48):
        if node is None or same_object(node, stop):
            return False
        try:
            if isinstance(node, ButtonBase):
                return True
        except Exception:
            pass
        parent = None
        try:
            parent = VisualTreeHelper.GetParent(node)
        except Exception:
            parent = None
        if parent is None:
            try:
                parent = LogicalTreeHelper.GetParent(node)
            except Exception:
                parent = None
        node = parent
    return False


class Chrome(object):
    """Shrink a window to its header bar at the bottom of the screen, and back.

    The header's siblings are collapsed once it lands, so the bar is the only
    thing left. The shrink button turns into a green up arrow (its Tag becomes
    "shrunk", which the ShrinkBtn style picks up); that arrow, or a double
    click on the bar, slides it back.
    """

    OPEN = "open"
    SHRINKING = "shrinking"
    SHRUNK = "shrunk"
    EXPANDING = "expanding"

    def __init__(self, window, header, button):
        self.window = window
        self.header = header
        self.button = button
        self.state = Chrome.OPEN
        self.slot = None
        self.saved = None
        self.hidden = []
        self.lifted_owner = False
        self.lifted_children = []
        self.timer = None
        self.tick = None
        _CHROMES.append(self)

        button.Click += self.on_button
        header.PreviewMouseLeftButtonDown += self.on_header_down
        window.Closed += self.on_closed

    # -- relationships ------------------------------------------------------
    def owner(self):
        try:
            return chrome_of(self.window.Owner)
        except Exception:
            return None

    def children(self):
        return [c for c in _CHROMES
                if c is not self and c.owner() is self]

    def busy(self):
        return self.state in (Chrome.SHRINKING, Chrome.EXPANDING)

    # -- platform: overridden by the bench ----------------------------------
    def now_ms(self):
        return float(_SHRINK_CLOCK.ElapsedMilliseconds)

    def start_timer(self, step):
        self.stop_timer()
        timer = DispatcherTimer()
        timer.Interval = TimeSpan.FromMilliseconds(SHRINK_FRAME_MS)

        def on_tick(sender, args):
            step()

        self.tick = on_tick
        timer.Tick += on_tick
        self.timer = timer
        timer.Start()

    def stop_timer(self):
        timer = self.timer
        self.timer = None
        if timer is None:
            return
        try:
            timer.Stop()
        except Exception:
            pass
        try:
            if self.tick is not None:
                timer.Tick -= self.tick
        except Exception:
            pass
        self.tick = None

    def bar_height(self):
        """The header plus the window's outer border above and below it."""
        try:
            height = float(self.header.ActualHeight)
            offset = float(self.header.TranslatePoint(Point(0, 0), self.window).Y)
            bar = height + 2.0 * max(offset, 0.0)
            if bar >= 10.0:
                return bar
        except Exception:
            pass
        return float(SHRINK_FALLBACK_BAR)

    def dpi_scale(self):
        try:
            source = PresentationSource.FromVisual(self.window)
            return float(source.CompositionTarget.TransformToDevice.M22) or 1.0
        except Exception:
            return 1.0

    def work_area_bottom(self):
        """The bottom of the working area of the screen the window is on."""
        try:
            clr.AddReference("System.Windows.Forms")
            from System.Windows.Forms import Screen
            handle = WindowInteropHelper(self.window).Handle
            area = Screen.FromHandle(handle).WorkingArea
            return float(area.Bottom) / self.dpi_scale()
        except Exception:
            pass
        try:
            return float(SystemParameters.WorkArea.Bottom)
        except Exception:
            return 1000.0

    # -- the parts that disappear -------------------------------------------
    def hide_parts(self):
        self.hidden = []
        try:
            siblings = list(self.header.Parent.Children)
        except Exception:
            siblings = []
        for child in siblings:
            if same_object(child, self.header):
                continue
            try:
                self.hidden.append((child, child.Visibility))
                child.Visibility = Visibility.Collapsed
            except Exception:
                pass

    def show_parts(self):
        for child, visibility in self.hidden:
            try:
                child.Visibility = visibility
            except Exception:
                pass
        self.hidden = []

    def set_button(self, tag):
        try:
            self.button.Tag = tag
        except Exception:
            pass

    def free_slot(self):
        taken = set(c.slot for c in _CHROMES
                    if c is not self and c.slot is not None
                    and c.state in (Chrome.SHRINKING, Chrome.SHRUNK))
        slot = 0
        while slot in taken:
            slot += 1
        return slot

    # -- the slide ----------------------------------------------------------
    def animate(self, top0, top1, h0, h1, done):
        window = self.window
        start = self.now_ms()

        def land():
            self.stop_timer()
            try:
                window.Height = max(h1, 1.0)
                window.Top = top1
            except Exception:
                pass
            done()

        def step():
            try:
                p = (self.now_ms() - start) / SHRINK_MS
                e = ease_out(p)
                window.Height = max(h0 + (h1 - h0) * e, 1.0)
                window.Top = top0 + (top1 - top0) * e
                if p >= 1.0:
                    land()
            except Exception:
                # never leave a window half way: put it at the end state
                land()

        self.start_timer(step)

    def current_height(self):
        try:
            height = float(self.window.Height)
            if height == height and height > 0:      # not NaN
                return height
        except Exception:
            pass
        try:
            return float(self.window.ActualHeight)
        except Exception:
            return 600.0

    def shrink(self):
        if self.state != Chrome.OPEN:
            return False

        # a dialog takes its owner down with it, or the owner stays over Revit
        owner = self.owner()
        if owner is not None and owner.state == Chrome.OPEN:
            if owner.shrink():
                self.lifted_owner = True

        window = self.window
        self.saved = {
            "Left": window.Left,
            "Top": window.Top,
            "Height": self.current_height(),
            "MinHeight": window.MinHeight,
            "ResizeMode": window.ResizeMode,
        }
        bar = self.bar_height()
        self.slot = self.free_slot()
        target = shrunk_top(self.work_area_bottom(), bar, self.slot)

        window.MinHeight = 0
        try:
            window.ResizeMode = ResizeMode.NoResize
        except Exception:
            pass
        self.state = Chrome.SHRINKING
        self.animate(window.Top, target, self.saved["Height"], bar, self.on_shrunk)

        # open dialogs go with it, stacked above
        for child in self.children():
            if child.state == Chrome.OPEN and child.shrink():
                self.lifted_children.append(child)
        return True

    def on_shrunk(self):
        self.hide_parts()
        self.state = Chrome.SHRUNK
        self.set_button("shrunk")

    def expand(self):
        if self.state != Chrome.SHRUNK:
            return False
        window = self.window
        saved = self.saved or {}
        self.show_parts()
        self.set_button("")
        try:
            window.Left = saved.get("Left", window.Left)
        except Exception:
            pass
        self.state = Chrome.EXPANDING
        self.slot = None
        self.animate(window.Top, saved.get("Top", window.Top),
                     self.current_height(), saved.get("Height", 600.0),
                     self.on_expanded)

        # a dialog without its owner is no use, so the owner comes back too
        owner = self.owner()
        if owner is not None and owner.state == Chrome.SHRUNK:
            owner.expand()
        for child in list(self.lifted_children):
            if child.state == Chrome.SHRUNK:
                child.expand()
        self.lifted_children = []
        self.lifted_owner = False
        return True

    def on_expanded(self):
        window = self.window
        saved = self.saved or {}
        try:
            window.MinHeight = saved.get("MinHeight", window.MinHeight)
        except Exception:
            pass
        try:
            window.ResizeMode = saved.get("ResizeMode", window.ResizeMode)
        except Exception:
            pass
        self.saved = None
        self.state = Chrome.OPEN
        try:
            window.Activate()
        except Exception:
            pass

    def restore_now(self):
        """Back to full size with no slide - for a window about to be used."""
        if self.state == Chrome.OPEN:
            return
        self.stop_timer()
        self.show_parts()
        self.set_button("")
        saved = self.saved or {}
        window = self.window
        try:
            window.Left = saved.get("Left", window.Left)
            window.Top = saved.get("Top", window.Top)
            window.Height = saved.get("Height", window.Height)
            window.MinHeight = saved.get("MinHeight", window.MinHeight)
            window.ResizeMode = saved.get("ResizeMode", window.ResizeMode)
        except Exception:
            pass
        self.saved = None
        self.slot = None
        self.state = Chrome.OPEN

    # -- events -------------------------------------------------------------
    def on_button(self, sender, args):
        try:
            if self.state == Chrome.OPEN:
                self.shrink()
            elif self.state == Chrome.SHRUNK:
                self.expand()
        except Exception:
            try:
                self.restore_now()
            except Exception:
                pass

    def on_header_down(self, sender, args):
        try:
            if inside_button(args.OriginalSource, self.header):
                return
            if self.busy():
                args.Handled = True          # no drag mid-slide
                return
            if self.state == Chrome.SHRUNK and args.ClickCount == 2:
                args.Handled = True
                self.expand()
        except Exception:
            pass

    def on_closed(self, sender, args):
        self.stop_timer()
        owner = self.owner()
        try:
            _CHROMES.remove(self)
        except ValueError:
            pass
        if self.lifted_owner and owner is not None and owner.state == Chrome.SHRUNK:
            try:
                owner.expand()
            except Exception:
                pass


# ---------------------------------------------------------------------------
#  Debug report window
# ---------------------------------------------------------------------------
class DebugWindow(object):

    def __init__(self, owner, text):
        self.window = load_xaml(DEBUG_XAML)
        f = self.window.FindName
        self.text_box = f("DbgText")
        self.status = f("DbgStatus")
        self.text_box.Text = text
        try:
            self.window.Owner = owner
        except Exception:
            pass
        f("DbgHeader").MouseLeftButtonDown += self.on_drag
        self.chrome = Chrome(self.window, f("DbgHeader"), f("DbgShrink"))
        self.themed = Themed(self.window)
        f("DbgClose").Click += self.on_close
        f("DbgCopy").Click += self.on_copy
        f("DbgSave").Click += self.on_save

    def on_drag(self, sender, args):
        try:
            self.window.DragMove()
        except Exception:
            pass

    def on_close(self, sender, args):
        self.window.Close()

    def on_copy(self, sender, args):
        try:
            Clipboard.SetText(self.text_box.Text)
            self.status.Text = "Copied. Paste it into the chat."
        except Exception as ex:
            self.status.Text = ("Copy failed ({0}) - select the text and press "
                                "Ctrl+C.".format(describe(ex)))

    def on_save(self, sender, args):
        try:
            path = os.path.join(log_folder(), "view_manager_debug.txt")
            handle = open(path, "w")
            try:
                handle.write(self.text_box.Text)
            finally:
                handle.close()
            self.status.Text = "Saved to " + path
        except Exception as ex:
            self.status.Text = "Save failed - " + describe(ex)

    def show(self):
        # Show, never ShowDialog: a modal child would disable Revit's own
        # window too, which is the whole thing this version exists to avoid.
        self.window.Show()


# ---------------------------------------------------------------------------
#  XAML - settings window: four tabs
# ---------------------------------------------------------------------------
ICON_LEVEL = u'''<Path Stretch="None" Stroke="{DynamicResource Blue}" StrokeThickness="1.4"
                  Data="M 1,3 L 15,3 M 1,8 L 15,8 M 1,13 L 15,13 M 12,0.5 L 14,3 L 12,5.5"/>'''
ICON_TEMPLATE = u'''<Path Stretch="None" Stroke="{DynamicResource Green}" StrokeThickness="1.3"
                  Data="M 2,1 L 11,1 L 14,4 L 14,15 L 2,15 Z M 5,6 L 11,6 M 5,9 L 11,9 M 5,12 L 9,12"/>'''
ICON_BOX = u'''<Path Stretch="None" Stroke="{DynamicResource Orange}" StrokeThickness="1.3"
                  StrokeDashArray="2 1.4"
                  Data="M 2,2 L 14,2 L 14,14 L 2,14 Z M 5,5 L 11,5 L 11,11 L 5,11 Z"/>'''
ICON_TAG = u'''<Path Stretch="None" Stroke="{DynamicResource Text}" StrokeThickness="1.3"
                  Data="M 1,8 L 5,3 L 15,3 L 15,13 L 5,13 Z M 7.4,8 A 1.2,1.2 0 1 0 7.39,8"/>'''


def tab_header(icon, label):
    return u'''<TabItem.Header>
          <StackPanel Orientation="Horizontal">
            <Grid Width="16" Height="16" Margin="0,0,7,0" VerticalAlignment="Center">
              {0}
            </Grid>
            <TextBlock Text="{1}" VerticalAlignment="Center"/>
          </StackPanel>
        </TabItem.Header>'''.format(icon, label)


def abbrev_tab(p, icon, label, intro, default_button):
    """One abbreviation tab. Every control is named with its prefix."""
    return u'''
      <TabItem>
        {header}
        <Grid Margin="14,12,14,10">
          <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
          </Grid.RowDefinitions>
          <TextBlock Grid.Row="0" TextWrapping="Wrap" Foreground="{{DynamicResource Muted}}"
                     Text="{intro}"/>
          <TextBox x:Name="{p}Search" Grid.Row="1" Margin="0,10,0,8"/>
          <Border Grid.Row="2" Background="{{DynamicResource Sunken}}"
                  BorderBrush="{{DynamicResource Line}}" BorderThickness="1">
            <ScrollViewer VerticalScrollBarVisibility="Auto"
                          HorizontalScrollBarVisibility="Disabled">
              <StackPanel x:Name="{p}List" Margin="2,4,2,4"/>
            </ScrollViewer>
          </Border>
          <Border Grid.Row="3" Margin="0,10,0,0" Background="{{DynamicResource Panel}}"
                  BorderBrush="{{DynamicResource Line}}" BorderThickness="1">
            <Grid Margin="12,10,12,10">
              <Grid.RowDefinitions>
                <RowDefinition Height="Auto"/>
                <RowDefinition Height="Auto"/>
              </Grid.RowDefinitions>
              <Grid.ColumnDefinitions>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="Auto"/>
                <ColumnDefinition Width="Auto"/>
                <ColumnDefinition Width="Auto"/>
              </Grid.ColumnDefinitions>
              <TextBlock x:Name="{p}Chosen" Grid.Row="0" Grid.ColumnSpan="4"
                         Text="Nothing selected" Foreground="{{DynamicResource Muted}}"
                         Margin="0,0,0,8" TextTrimming="CharacterEllipsis"/>
              <TextBox x:Name="{p}Abbrev" Grid.Row="1" Grid.Column="0" IsEnabled="False"
                       Margin="0,0,8,0" MaxLength="16"/>
              <Button x:Name="{p}Apply" Grid.Row="1" Grid.Column="1" Content="Set"
                      Style="{{StaticResource GoSmall}}" IsEnabled="False" Margin="0,0,6,0"/>
              <Button x:Name="{p}Clear" Grid.Row="1" Grid.Column="2" Content="{default}"
                      Style="{{StaticResource Ghost}}" IsEnabled="False" Margin="0,0,10,0"/>
              <Button x:Name="{p}Reset" Grid.Row="1" Grid.Column="3" Content="Clear all"
                      Style="{{StaticResource Flat}}"/>
            </Grid>
          </Border>
        </Grid>
      </TabItem>'''.format(header=tab_header(icon, label), p=p, intro=intro,
                           default=default_button)


TAG_TAB = u'''
      <TabItem>
        {header}
        <StackPanel Margin="18,16,18,10">
          <TextBlock Text="ROOM TAGS" Style="{{StaticResource Head}}" Margin="0,0,0,8"/>
          <TextBlock TextWrapping="Wrap" Foreground="{{DynamicResource Muted}}" Margin="0,0,0,14"
                     Text="With Add room tags ticked, every new view gets a tag on each room its cut plane passes through, inside its crop. Dependent views show their parent's tags, so they are not tagged separately."/>

          <TextBlock Text="Room tag" Margin="0,0,0,5"/>
          <ComboBox x:Name="TagType" Height="26" HorizontalAlignment="Stretch" Margin="0,0,0,4"/>
          <TextBlock x:Name="TagDefaultNote" Foreground="{{DynamicResource Muted}}" FontSize="11"
                     TextWrapping="Wrap" Margin="0,0,0,16"/>

          <CheckBox x:Name="TagOn" Content="Tick Add room tags when the tool opens" Margin="0,0,0,8"/>
          <CheckBox x:Name="TagLinks" Content="Tag rooms in loaded linked models too" Margin="0,0,0,4"/>
          <TextBlock Foreground="{{DynamicResource Muted}}" FontSize="11" TextWrapping="Wrap"
                     Margin="23,0,0,0"
                     Text="Rooms usually live in the architect's model. Untick to tag only rooms in this model."/>
        </StackPanel>
      </TabItem>'''.format(header=tab_header(ICON_TAG, "Tag settings"))


SETTINGS_XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        xmlns:shell="clr-namespace:System.Windows.Shell;assembly=PresentationFramework"
        Title="RevoBIM PY - View Manager settings"
        Height="660" Width="780" MinHeight="460" MinWidth="600"
        WindowStartupLocation="CenterOwner"
        WindowStyle="None" ResizeMode="CanResize" Background="{DynamicResource WindowBg}">

  <shell:WindowChrome.WindowChrome>
    <shell:WindowChrome CaptionHeight="0" CornerRadius="0"
                        GlassFrameThickness="0" ResizeBorderThickness="6"/>
  </shell:WindowChrome.WindowChrome>

  <Window.Resources>
""" + SHARED_TOKEN + u"""
  </Window.Resources>

  <Border BorderBrush="{DynamicResource Line}" BorderThickness="1"
          Background="{DynamicResource WindowBg}">
    <Grid>
      <Grid.RowDefinitions>
        <RowDefinition Height="38"/>
        <RowDefinition Height="*"/>
        <RowDefinition Height="Auto"/>
      </Grid.RowDefinitions>

      <Border x:Name="SetHeader" Grid.Row="0" Background="{DynamicResource HeadBar}">
        <Grid>
          <StackPanel Orientation="Horizontal" VerticalAlignment="Center" Margin="12,0,0,0">
            <TextBlock Text="RevoBIM" Foreground="{DynamicResource Blue}"
                       FontSize="13" FontWeight="Bold"/>
            <TextBlock Text="  View Manager settings" FontSize="13"/>
          </StackPanel>
          <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
            <Button x:Name="ThemeChip" Style="{StaticResource ChipButton}">
              <StackPanel Orientation="Horizontal">
                <Grid Width="12" Height="12" Margin="0,0,6,0" VerticalAlignment="Center">
                  <Ellipse Stroke="{DynamicResource Text}" StrokeThickness="1.2"/>
                  <Path Fill="{DynamicResource Text}" Data="M 6,0.6 A 5.4,5.4 0 0 0 6,11.4 Z"/>
                </Grid>
                <TextBlock x:Name="ThemeChipText" Text="Auto" VerticalAlignment="Center"
                           FontSize="11"/>
              </StackPanel>
            </Button>
            <Button x:Name="SetShrink" Content="" Style="{StaticResource ShrinkBtn}" Height="38"/>
            <Button x:Name="SetClose" Content="&#x2715;" Style="{StaticResource Close}" Height="38"/>
          </StackPanel>
        </Grid>
      </Border>

      <TabControl x:Name="SetTabs" Grid.Row="1">
""" + abbrev_tab(
    "Lvl", ICON_LEVEL, "Level abbreviations",
    "Pick a level and give it an abbreviation for view names. Anything not set here "
    "follows the rule - F01 and Level 1 read L01, Roof reads LRF. Kept for this project.",
    "Use rule") + abbrev_tab(
    "Tpl", ICON_TEMPLATE, "Template abbreviations",
    "Pick a view template and give it an abbreviation. What is set here beats the "
    "built-in keywords. Kept for every project on this machine.",
    "Use keyword") + abbrev_tab(
    "Box", ICON_BOX, "Scope box abbreviations",
    "Pick a scope box and give it an abbreviation. Dependent views are named "
    "DEP_host_abbreviation; anything not set here uses the scope box's own name. "
    "Kept for this project.",
    "Use name") + TAG_TAB + u"""
      </TabControl>

      <Border Grid.Row="2" Background="{DynamicResource HeadBar}"
              BorderBrush="{DynamicResource Line}" BorderThickness="0,1,0,0">
        <Grid Margin="14,10,14,10">
          <TextBlock x:Name="SetStatus" Text="" Foreground="{DynamicResource Muted}"
                     VerticalAlignment="Center" TextTrimming="CharacterEllipsis"/>
          <Button x:Name="SetDone" Content="Done" Style="{StaticResource Ghost}"
                  HorizontalAlignment="Right"/>
        </Grid>
      </Border>
    </Grid>
  </Border>
</Window>
"""


SOURCE_NOTES = {
    "override": "   set by hand",
    "keyword": "",
    "rule": "",
    "name": "",
    "fallback": "   no keyword",
}


class AbbrevTab(object):
    """One abbreviation tab: pick a name, set its abbreviation, or clear it."""

    def __init__(self, owner, prefix, names, detail, store, kind):
        self.owner = owner
        self.names = names
        self.detail = detail
        self.store = store
        self.kind = kind
        self.chosen = None
        self.rows = []

        f = owner.window.FindName
        self.search = f(prefix + "Search")
        self.list_panel = f(prefix + "List")
        self.chosen_label = f(prefix + "Chosen")
        self.abbrev_box = f(prefix + "Abbrev")
        self.btn_apply = f(prefix + "Apply")
        self.btn_clear = f(prefix + "Clear")

        self.search.TextChanged += self.on_search
        self.abbrev_box.KeyDown += self.on_key
        self.btn_apply.Click += self.on_apply
        self.btn_clear.Click += self.on_clear
        f(prefix + "Reset").Click += self.on_reset
        self.build()

    def brush(self, key):
        return self.owner.window.Resources[key]

    def count_text(self):
        count = len(self.store.items)
        if count:
            return "{0} {1} abbreviation(s) set by hand - saved to {2}".format(
                count, self.kind, self.store.path())
        return "No {0} abbreviations set by hand.".format(self.kind)

    def build(self):
        self.list_panel.Children.Clear()
        self.rows = []
        try:
            kw = (self.search.Text or "").lower().strip()
        except Exception:
            kw = ""
        shown = 0
        for name in self.names:
            abbr, source = self.detail(name)
            if kw and kw not in name.lower() and kw not in (abbr or "").lower():
                continue

            row = Border()
            row.Background = Brushes.Transparent     # or it is not hit testable
            row.Padding = Thickness(8, 4, 8, 4)
            panel = StackPanel()
            panel.Orientation = Orientation.Horizontal

            chip = TextBlock()
            chip.Text = abbr
            chip.Width = 96
            chip.FontFamily = FontFamily("Consolas")
            chip.FontSize = 11.5
            chip.VerticalAlignment = VerticalAlignment.Center
            chip.TextTrimming = TextTrimming.CharacterEllipsis
            if source == "override":
                chip.Foreground = self.brush("Orange")
                chip.FontWeight = FontWeights.SemiBold
            elif source == "fallback":
                chip.Foreground = self.brush("Muted")
            else:
                chip.Foreground = self.brush("Text")

            label = TextBlock()
            label.Text = name
            label.VerticalAlignment = VerticalAlignment.Center
            label.TextTrimming = TextTrimming.CharacterEllipsis

            note = TextBlock()
            note.Text = SOURCE_NOTES.get(source, "")
            note.Foreground = self.brush("Muted")
            note.FontSize = 10.5
            note.VerticalAlignment = VerticalAlignment.Center

            panel.Children.Add(chip)
            panel.Children.Add(label)
            panel.Children.Add(note)
            row.Child = panel

            index = len(self.rows)
            self.rows.append({"name": name, "border": row})

            def on_click(sender, args, i=index):
                self.select(i)

            row.MouseLeftButtonDown += on_click
            self.list_panel.Children.Add(row)
            shown += 1

        if not shown:
            tb = TextBlock()
            tb.Text = "  Nothing matches."
            tb.Foreground = self.brush("Muted")
            self.list_panel.Children.Add(tb)

        if self.chosen is not None:
            for index, record in enumerate(self.rows):
                if record["name"] == self.chosen:
                    self.paint(index)
                    break

    def paint(self, index):
        for i, record in enumerate(self.rows):
            try:
                record["border"].Background = (self.brush("Selection") if i == index
                                               else Brushes.Transparent)
            except Exception:
                pass

    def select(self, index):
        if index >= len(self.rows):
            return
        self.chosen = self.rows[index]["name"]
        self.paint(index)
        abbr, source = self.detail(self.chosen)
        self.chosen_label.Text = self.chosen
        self.chosen_label.Foreground = self.brush("Text")
        self.abbrev_box.Text = abbr
        self.abbrev_box.IsEnabled = True
        self.btn_apply.IsEnabled = True
        self.btn_clear.IsEnabled = (source == "override")
        try:
            self.abbrev_box.Focus()
            self.abbrev_box.SelectAll()
        except Exception:
            pass

    def commit(self, message):
        saved, note = self.store.save()
        if not saved:
            self.owner.say("Could not save - " + note)
            return False
        self.build()
        self.owner.changed()
        self.owner.say(message)
        return True

    def on_search(self, sender, args):
        try:
            self.build()
        except Exception:
            pass

    def on_key(self, sender, args):
        try:
            if args.Key == Key.Enter:
                self.on_apply(sender, args)
        except Exception:
            pass

    def on_apply(self, sender, args):
        if self.chosen is None:
            return
        try:
            value = sanitise((self.abbrev_box.Text or "").strip())
        except Exception:
            value = ""
        if not value:
            self.owner.say("Type an abbreviation first, or press {0}.".format(
                self.btn_clear.Content))
            return
        self.store.items[self.chosen] = value
        if self.commit(u"{0}  ->  {1}".format(self.chosen, value)):
            self.btn_clear.IsEnabled = True

    def on_clear(self, sender, args):
        if self.chosen is None or self.chosen not in self.store.items:
            return
        name = self.chosen
        del self.store.items[name]
        abbr, _source = self.detail(name)
        if self.commit(u"{0} is back to the default  ->  {1}".format(name, abbr)):
            self.abbrev_box.Text = abbr
            self.btn_clear.IsEnabled = False

    def on_reset(self, sender, args):
        if not self.store.items:
            self.owner.say("No {0} abbreviations set by hand to clear.".format(self.kind))
            return
        count = len(self.store.items)
        self.store.items.clear()
        if self.commit("Cleared {0} {1} abbreviation(s).".format(count, self.kind)):
            self.btn_clear.IsEnabled = False
            if self.chosen is not None:
                self.abbrev_box.Text = self.detail(self.chosen)[0]


def room_tag_label(symbol):
    try:
        family = symbol.FamilyName
    except Exception:
        family = ""
    return u"{0} : {1}".format(family, type_name_of(symbol)) if family else type_name_of(symbol)


def collect_room_tag_types(document):
    types = []
    try:
        for symbol in (FilteredElementCollector(document)
                       .OfCategory(BuiltInCategory.OST_RoomTags)
                       .WhereElementIsElementType()):
            types.append(symbol)
    except Exception:
        pass
    types.sort(key=lambda s: room_tag_label(s).lower())
    return types


def default_room_tag_id(document):
    try:
        cid = category_id(document, "OST_RoomTags")
        if cid is not None:
            type_id = document.GetDefaultFamilyTypeId(cid)
            if not is_invalid(type_id):
                return type_id
    except Exception:
        pass
    return None


def resolve_room_tag_type(document):
    """(type id or None, label, note) - the chosen tag, else the default, else first."""
    types = collect_room_tag_types(document)
    if not types:
        return None, "", "No room tag family is loaded in this project."
    wanted = (SETTINGS.get("room_tag_type") or "").strip()
    if wanted:
        for symbol in types:
            if room_tag_label(symbol) == wanted:
                return symbol.Id, wanted, ""
    default_id = default_room_tag_id(document)
    if default_id is not None:
        element = document.GetElement(default_id)
        label = room_tag_label(element) if element is not None else "project default"
        note = ("'{0}' is not loaded here - using the project default.".format(wanted)
                if wanted else "")
        return default_id, label, note
    label = room_tag_label(types[0])
    return types[0].Id, label, ("No project default is set - using the first loaded "
                                "room tag.")


class SettingsWindow(object):
    """Level, template and scope box abbreviations, and the tag settings."""

    def __init__(self, owner, templates, levels, boxes, on_changed, start_tab=0):
        self.on_changed = on_changed
        self.loading = True
        self.window = load_xaml(SETTINGS_XAML)
        f = self.window.FindName
        self.status = f("SetStatus")
        self.tabs = f("SetTabs")

        try:
            self.window.Owner = owner
        except Exception:
            pass

        f("SetHeader").MouseLeftButtonDown += self.on_drag
        f("SetClose").Click += self.on_close
        f("SetDone").Click += self.on_close
        self.chrome = Chrome(self.window, f("SetHeader"), f("SetShrink"))

        self.pages = [
            AbbrevTab(self, "Lvl", [lv.Name for lv in levels],
                      level_abbr_detail, LEVEL_STORE, "level"),
            AbbrevTab(self, "Tpl", [t.Name for t in templates],
                      abbreviate_detail, TEMPLATE_STORE, "template"),
            AbbrevTab(self, "Box", [b.Name for b in boxes],
                      box_abbr_detail, BOX_STORE, "scope box"),
        ]
        self.themed = Themed(self.window, on_repaint=self.on_theme)

        # tag settings
        self.tag_combo = f("TagType")
        self.tag_note = f("TagDefaultNote")
        self.tag_on = f("TagOn")
        self.tag_links = f("TagLinks")
        self.tag_types = collect_room_tag_types(doc)
        self.fill_tag_types()
        self.tag_on.IsChecked = setting_on("room_tags_on")
        self.tag_links.IsChecked = setting_on("room_tags_links")
        self.tag_combo.SelectionChanged += self.on_tag_type
        self.tag_on.Checked += self.on_tag_flags
        self.tag_on.Unchecked += self.on_tag_flags
        self.tag_links.Checked += self.on_tag_flags
        self.tag_links.Unchecked += self.on_tag_flags
        self.tabs.SelectionChanged += self.on_tab
        try:
            self.tabs.SelectedIndex = start_tab
        except Exception:
            pass
        self.loading = False
        self.on_tab(self.tabs, None)

    # -- shared -------------------------------------------------------------
    def say(self, text):
        try:
            self.status.Text = text
        except Exception:
            pass

    def changed(self):
        if self.on_changed is not None:
            try:
                self.on_changed()
            except Exception:
                pass

    def on_theme(self):
        for page in self.pages:
            try:
                page.build()
            except Exception:
                pass

    def on_tab(self, sender, args):
        if sender is not self.tabs:
            return
        index = self.tabs.SelectedIndex
        if 0 <= index < len(self.pages):
            self.say(self.pages[index].count_text())
        else:
            self.say("Saved to " + settings_path())

    # -- tag settings ---------------------------------------------------------
    def fill_tag_types(self):
        self.tag_combo.Items.Clear()
        default_id = default_room_tag_id(doc)
        default_label = ""
        if default_id is not None:
            element = doc.GetElement(default_id)
            if element is not None:
                default_label = room_tag_label(element)
        first = "<Project default>"
        if default_label:
            first = u"<Project default>  ({0})".format(default_label)
        self.tag_combo.Items.Add(first)
        wanted = (SETTINGS.get("room_tag_type") or "").strip()
        index = 0
        for i, symbol in enumerate(self.tag_types):
            label = room_tag_label(symbol)
            self.tag_combo.Items.Add(label)
            if label == wanted:
                index = i + 1
        self.tag_combo.SelectedIndex = index
        if not self.tag_types:
            self.tag_note.Text = "No room tag family is loaded in this project."
        elif wanted and index == 0:
            self.tag_note.Text = (u"'{0}' is not loaded in this project, so the project "
                                  u"default is used here.".format(wanted))
        else:
            self.tag_note.Text = "Kept for every project on this machine."

    def on_tag_type(self, sender, args):
        if self.loading:
            return
        index = self.tag_combo.SelectedIndex
        if index <= 0:
            SETTINGS["room_tag_type"] = ""
            label = "the project default"
        else:
            label = room_tag_label(self.tag_types[index - 1])
            SETTINGS["room_tag_type"] = label
        saved, note = save_settings()
        self.say(u"Room tag: {0}".format(label) if saved else "Could not save - " + note)
        self.tag_note.Text = "Kept for every project on this machine."
        self.changed()

    def on_tag_flags(self, sender, args):
        if self.loading:
            return
        SETTINGS["room_tags_on"] = "1" if bool(self.tag_on.IsChecked) else "0"
        SETTINGS["room_tags_links"] = "1" if bool(self.tag_links.IsChecked) else "0"
        saved, note = save_settings()
        self.say("Tag settings saved." if saved else "Could not save - " + note)
        self.changed()

    # -- window -----------------------------------------------------------------
    def on_drag(self, sender, args):
        try:
            self.window.DragMove()
        except Exception:
            pass

    def on_close(self, sender, args):
        self.window.Close()

    def show(self):
        # Show, never ShowDialog: a modal child disables Revit's own window.
        self.window.Show()


# ---------------------------------------------------------------------------
#  UI
# ---------------------------------------------------------------------------
def ui_safe(fn):
    """Never let a handler exception reach Revit's UI thread."""
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as ex:
            try:
                self = args[0]
                self.set_status("Error: " + describe(ex), error=True)
                self.log.append("HANDLER FAILED in {0}".format(fn.__name__))
                self.log.append(traceback.format_exc())
                self.offer_report()
            except Exception:
                pass
    return wrapper


class ViewManagerWindow(object):

    def __init__(self):
        self.host_views = []
        self.scope_boxes = []
        self.templates = []
        self.levels = []
        self.elements = {}

        self.view_state = {}     # host views
        self.box_state = {}      # scope boxes, dependents tab
        self.tpl_state = {}      # view templates
        self.lvl_state = {}      # levels
        self.cv_box_key = None   # single scope box, create tab

        self.log = []
        self.report_text = ""
        self.busy = False
        self.timings = {}
        self.fast_mode = True          # what the prompt last answered
        self.ask_before_creating = True
        self.pending_job = None
        self.row_sets = {}             # list name -> the rows on screen
        self.anchors = {}              # list name -> where a shift run starts
        self.highlights = {}           # list name -> the highlighted indexes
        self.suppress_toggle = False   # guard while a run is ticked together
        self.isolate_keys = set()      # host views the tool was launched with
        self.view_meta = {}            # view key -> (family, type name)
        self.tpl_meta = {}
        self.view_filter_options = []
        self.tpl_filter_options = []
        self.loading_filters = False   # guard while the dropdowns are filled

        self.window = load_xaml(XAML)
        f = self.window.FindName

        self.header = f("Header")
        self.version_label = f("VersionLabel")
        self.tool_label = f("ToolLabel")
        self.tabs = f("Tabs")
        self.status = f("Status")

        self.btn_close = f("BtnClose")
        self.btn_cancel = f("BtnCancel")
        self.btn_apply = f("BtnApply")
        self.btn_create = f("BtnCreate")
        self.btn_report = f("BtnReport")
        self.btn_refresh = f("BtnRefresh")
        self.btn_settings = f("BtnSettings")
        self.chk_debug = f("ChkDebug")
        self.chk_room_tags = f("ChkRoomTags")
        self.chk_room_tags.Checked += self.on_room_tags_toggled
        self.chk_room_tags.Unchecked += self.on_room_tags_toggled
        self.prog_track = f("ProgTrack")
        self.prog_fill = f("ProgFill")
        self.ask_overlay = f("AskOverlay")
        self.ask_remember = f("AskRemember")
        self.isolate_chip = f("IsolateChip")
        self.isolate_text = f("IsolateText")
        self.view_filter = f("ViewFilter")
        self.tpl_filter = f("TplFilter")

        self.view_search = f("ViewSearch")
        self.box_search = f("BoxSearch")
        self.view_list = f("ViewList")
        self.box_list = f("BoxList")
        self.views_head = f("ViewsHead")
        self.boxes_head = f("BoxesHead")

        self.tpl_search = f("TplSearch")
        self.lvl_search = f("LvlSearch")
        self.cvbox_search = f("CvBoxSearch")
        self.tpl_list = f("TplList")
        self.lvl_list = f("LvlList")
        self.cvbox_list = f("CvBoxList")
        self.tpl_head = f("TplHead")
        self.lvl_head = f("LvlHead")
        self.cvbox_head = f("CvBoxHead")

        self.version_label.Text = "v" + VERSION

        self.header.MouseLeftButtonDown += self.on_drag
        self.chrome = Chrome(self.window, self.header, f("BtnShrink"))
        self.themed = Themed(self.window, on_repaint=self.on_theme_changed)
        self.btn_close.Click += self.on_close
        self.btn_cancel.Click += self.on_close
        self.btn_apply.Click += self.on_apply_dependents
        self.btn_create.Click += self.on_create_views
        self.btn_report.Click += self.on_show_report
        self.btn_refresh.Click += self.on_refresh
        self.btn_settings.Click += self.on_settings
        f("BtnShowAll").Click += self.on_show_all_views
        self.view_filter.SelectionChanged += self.on_view_filter
        self.tpl_filter.SelectionChanged += self.on_tpl_filter
        f("AskFast").Click += self.on_ask_fast
        f("AskNormal").Click += self.on_ask_normal
        f("AskCancel").Click += self.on_ask_cancel
        self.tabs.SelectionChanged += self.on_tab_changed
        self.window.KeyDown += self.on_key
        self.window.Closed += self.on_closed

        self.view_search.TextChanged += self.on_view_search
        self.box_search.TextChanged += self.on_box_search
        f("BtnViewsAll").Click += self.on_views_all
        f("BtnViewsNone").Click += self.on_views_none
        f("BtnBoxesAll").Click += self.on_boxes_all
        f("BtnBoxesNone").Click += self.on_boxes_none

        self.tpl_search.TextChanged += self.on_tpl_search
        self.lvl_search.TextChanged += self.on_lvl_search
        self.cvbox_search.TextChanged += self.on_cvbox_search
        f("BtnTplAll").Click += self.on_tpl_all
        f("BtnTplNone").Click += self.on_tpl_none
        f("BtnLvlAll").Click += self.on_lvl_all
        f("BtnLvlNone").Click += self.on_lvl_none
        f("BtnCvBoxNone").Click += self.on_cvbox_clear

        try:
            self.chk_room_tags.IsChecked = setting_on("room_tags_on")
        except Exception:
            pass
        self.read_model()

        # A tool that acts on a selection reads the selection it was launched
        # with: views picked in the Project Browser isolate the host list and
        # arrive ticked, on the tab that uses them.
        preselected = self.read_preselection()
        if preselected:
            self.isolate_keys = set(preselected)
            for key in preselected:
                self.view_state[key] = True
            try:
                self.tabs.SelectedIndex = 1
            except Exception:
                pass

        self.rebuild_all()
        self.on_tab_changed(self.tabs, None)
        if preselected:
            self.set_status(
                "{0} view(s) selected in Revit are isolated and ticked.".format(
                    len(preselected)))

    # -- model --------------------------------------------------------------
    def read_model(self):
        self.host_views = collect_host_views(doc)
        self.scope_boxes = collect_scope_boxes(doc)
        self.templates = collect_view_templates(doc)
        self.levels = collect_levels(doc)
        self.elements = {}
        for group in (self.host_views, self.scope_boxes, self.templates, self.levels):
            for e in group:
                self.elements[key_of(e)] = e

        # family and type are read once here rather than on every keystroke
        self.view_meta = build_meta(document_of(), self.host_views)
        self.tpl_meta = build_meta(document_of(), self.templates)
        # a pick that no longer exists is dropped rather than carried forward
        live = set(self.elements.keys())
        for state in (self.view_state, self.box_state, self.tpl_state, self.lvl_state):
            for key in list(state.keys()):
                if key not in live:
                    del state[key]
        if self.cv_box_key is not None and self.cv_box_key not in live:
            self.cv_box_key = None
        if self.isolate_keys:
            self.isolate_keys = set(k for k in self.isolate_keys if k in live)

    def rebuild_all(self):
        self.build_views(self.view_search.Text)
        self.build_boxes(self.box_search.Text)
        self.build_templates(self.tpl_search.Text)
        self.build_levels(self.lvl_search.Text)
        self.build_cvboxes(self.cvbox_search.Text)
        self.refresh()

    def live(self, key):
        """Re-resolve an element at write time: modeless means it may be gone."""
        element = doc.GetElement(make_eid(key))
        try:
            if element is None or not element.IsValidObject:
                return None
        except Exception:
            pass
        return element

    # -- shared helpers -----------------------------------------------------
    def brush(self, key):
        return self.window.Resources[key]

    def set_status(self, text, error=False):
        self.status.Text = text
        self.status.Foreground = self.brush("Orange" if error else "Muted")

    def debug_on(self):
        try:
            return bool(self.chk_debug.IsChecked)
        except Exception:
            return False

    def current_tab(self):
        try:
            return self.tabs.SelectedIndex
        except Exception:
            return 0

    def row_content(self, label, sub=None, sub_brush="Muted"):
        if not sub:
            tb = TextBlock()
            tb.Text = label
            return tb
        sp = StackPanel()
        sp.Orientation = Orientation.Horizontal
        t1 = TextBlock()
        t1.Text = label
        t2 = TextBlock()
        t2.Text = "   " + sub
        t2.Foreground = self.brush(sub_brush)
        sp.Children.Add(t1)
        sp.Children.Add(t2)
        return sp

    # -- rows, and selecting a run of them ----------------------------------
    def reset_rows(self, name):
        self.row_sets[name] = []
        self.anchors[name] = None
        self.highlights[name] = set()

    def add_row(self, panel, name, key, label, state_dict,
                sub=None, sub_brush="Muted"):
        """One row: a CheckBox inside a Border that carries the highlight.

        The tick box's own Background is the box itself, so the row needs a
        surface of its own to paint blue.
        """
        chk = CheckBox()
        chk.Tag = key
        chk.IsChecked = bool(state_dict.get(key, False))
        chk.Content = self.row_content(label, sub, sub_brush)

        border = Border()
        border.Background = Brushes.Transparent     # or it is not hit testable
        border.Child = chk

        index = len(self.row_sets[name])
        self.row_sets[name].append({"key": key, "border": border, "check": chk})

        def on_down(sender, args):
            self.on_row_mouse_down(name, index, args)

        def on_toggle(sender, args):
            self.on_row_toggle(name, index, state_dict)

        border.PreviewMouseLeftButtonDown += on_down
        chk.Checked += on_toggle
        chk.Unchecked += on_toggle
        panel.Children.Add(border)

    def on_row_mouse_down(self, name, index, args):
        rows = self.row_sets.get(name) or []
        if index >= len(rows):
            return
        highlight = self.highlights.setdefault(name, set())
        anchor = self.anchors.get(name)

        try:
            modifiers = Keyboard.Modifiers
            shift = bool(modifiers & ModifierKeys.Shift)
            control = bool(modifiers & ModifierKeys.Control)
        except Exception:
            shift = control = False

        if shift and anchor is not None:
            low, high = sorted((anchor, index))
            highlight.clear()
            for i in range(low, high + 1):
                highlight.add(i)
            self.paint_highlight(name)
            args.Handled = True             # extend the run, do not tick it
            return

        if control:
            if index in highlight:
                highlight.discard(index)
            else:
                highlight.add(index)
            self.anchors[name] = index
            self.paint_highlight(name)
            args.Handled = True
            return

        # A plain click on a row outside the run starts again from here. A
        # plain click on a row inside it keeps the run, so the tick carries.
        if index not in highlight:
            highlight.clear()
        self.anchors[name] = index
        self.paint_highlight(name)

    def paint_highlight(self, name):
        rows = self.row_sets.get(name) or []
        highlight = self.highlights.get(name) or set()
        selected_brush = self.brush("Selection")
        for index, record in enumerate(rows):
            try:
                record["border"].Background = (selected_brush if index in highlight
                                               else Brushes.Transparent)
            except Exception:
                pass

    def on_row_toggle(self, name, index, state_dict):
        if self.suppress_toggle:
            return
        rows = self.row_sets.get(name) or []
        if index >= len(rows):
            return
        highlight = self.highlights.get(name) or set()
        value = bool(rows[index]["check"].IsChecked)
        state_dict[rows[index]["key"]] = value

        if index in highlight and len(highlight) > 1:
            self.suppress_toggle = True
            try:
                for other in highlight:
                    if other >= len(rows) or other == index:
                        continue
                    record = rows[other]
                    if bool(record["check"].IsChecked) != value:
                        record["check"].IsChecked = value
                    state_dict[record["key"]] = value
            finally:
                self.suppress_toggle = False
        self.refresh()

    def empty_row(self, text):
        tb = TextBlock()
        tb.Text = "  " + text
        tb.Foreground = self.brush("Muted")
        return tb

    def _bulk(self, name, state_dict, value):
        """All / None over whatever the list is currently showing."""
        self.suppress_toggle = True
        try:
            for record in self.row_sets.get(name) or []:
                state_dict[record["key"]] = value
                record["check"].IsChecked = value
        finally:
            self.suppress_toggle = False
        self.refresh()

    # -- list building ------------------------------------------------------
    def group_header(self, text):
        tb = TextBlock()
        tb.Text = text.upper()
        tb.Foreground = self.brush("Muted")
        tb.FontSize = 10
        tb.FontWeight = FontWeights.SemiBold
        tb.Margin = Thickness(10, 9, 8, 3)
        return tb

    def fill_filter(self, combo, options, keep=None):
        """Refill a dropdown without its own SelectionChanged firing back."""
        self.loading_filters = True
        try:
            combo.Items.Clear()
            for _family, _type_name, label in options:
                combo.Items.Add(label)
            index = 0
            if keep is not None:
                for i, option in enumerate(options):
                    if (option[0], option[1]) == keep:
                        index = i
                        break
            combo.SelectedIndex = index if combo.Items.Count else -1
        finally:
            self.loading_filters = False

    def current_filter(self, combo, options):
        try:
            index = combo.SelectedIndex
        except Exception:
            return (None, None)
        if index is None or index < 0 or index >= len(options):
            return (None, None)
        return (options[index][0], options[index][1])

    def passes_filter(self, meta_pair, wanted):
        family, type_name = wanted
        if family is None:
            return True
        if meta_pair[0] != family:
            return False
        return type_name is None or meta_pair[1] == type_name

    def build_views(self, keyword):
        self.view_list.Children.Clear()
        self.reset_rows("views")

        options = build_filter_options(self.view_meta)
        if options != self.view_filter_options:
            keep = self.current_filter(self.view_filter, self.view_filter_options)
            self.view_filter_options = options
            self.fill_filter(self.view_filter, options, keep)
        wanted = self.current_filter(self.view_filter, self.view_filter_options)

        kw = (keyword or "").lower().strip()
        matches = []
        for v in self.host_views:
            key = key_of(v)
            if self.isolate_keys and key not in self.isolate_keys:
                continue
            pair = self.view_meta.get(key, ("Other", "(no type)"))
            if not self.passes_filter(pair, wanted):
                continue
            if kw and kw not in v.Name.lower() and kw not in pair[0].lower() \
                    and kw not in pair[1].lower():
                continue
            matches.append((pair[0], pair[1], v.Name, key))

        matches.sort(key=lambda m: (m[0].lower(), m[1].lower(), m[2].lower()))

        group = None
        for family, type_name, name, key in matches:
            if (family, type_name) != group:
                group = (family, type_name)
                self.view_list.Children.Add(
                    self.group_header("{0}   -   {1}".format(family, type_name)))
            self.add_row(self.view_list, "views", key, name, self.view_state)

        if not matches:
            self.view_list.Children.Add(self.empty_row("No matching views."))
        self.paint_isolate_chip()

    def build_boxes(self, keyword):
        self.box_list.Children.Clear()
        self.reset_rows("boxes")
        kw = (keyword or "").lower().strip()
        shown = 0
        for b in self.scope_boxes:
            if kw and kw not in b.Name.lower():
                continue
            abbr, source = box_abbr_detail(b.Name)
            if source == "override":
                self.add_row(self.box_list, "boxes", key_of(b), b.Name, self.box_state,
                             "-> " + abbr, "Orange")
            else:
                self.add_row(self.box_list, "boxes", key_of(b), b.Name, self.box_state)
            shown += 1
        if not shown:
            self.box_list.Children.Add(self.empty_row("No matching scope boxes."))

    def build_templates(self, keyword):
        self.tpl_list.Children.Clear()
        self.reset_rows("templates")

        options = build_filter_options(self.tpl_meta)
        if options != self.tpl_filter_options:
            first_fill = not self.tpl_filter_options
            keep = self.current_filter(self.tpl_filter, self.tpl_filter_options)
            if first_fill:
                # Create Views makes plans, so open on the plan templates
                keep = (DEFAULT_TEMPLATE_FAMILY, None)
            self.tpl_filter_options = options
            self.fill_filter(self.tpl_filter, options, keep)
        wanted = self.current_filter(self.tpl_filter, self.tpl_filter_options)

        kw = (keyword or "").lower().strip()
        matches = []
        for t in self.templates:
            key = key_of(t)
            pair = self.tpl_meta.get(key, ("Other", "(no type)"))
            if not self.passes_filter(pair, wanted):
                continue
            if kw and kw not in t.Name.lower() and kw not in pair[0].lower() \
                    and kw not in pair[1].lower():
                continue
            matches.append((pair[0], pair[1], t.Name, key, t))

        matches.sort(key=lambda m: (m[0].lower(), m[1].lower(), m[2].lower()))

        group = None
        for family, type_name, name, key, t in matches:
            if (family, type_name) != group:
                group = (family, type_name)
                self.tpl_list.Children.Add(
                    self.group_header("{0}   -   {1}".format(family, type_name)))

            abbr, matched = abbreviate_template(name)
            plan_family, _ = plan_family_for(t.ViewType)
            if plan_family is None:
                tag = "-> not a plan template"
                colour = "Muted"
            elif matched:
                tag = "-> " + abbr
                colour = "Orange"
            else:
                tag = "-> " + abbr + "  (no keyword)"
                colour = "Muted"
            self.add_row(self.tpl_list, "templates", key, name,
                         self.tpl_state, tag, colour)

        if not matches:
            self.tpl_list.Children.Add(self.empty_row("No matching templates."))

    def build_levels(self, keyword):
        self.lvl_list.Children.Clear()
        self.reset_rows("levels")
        kw = (keyword or "").lower().strip()
        shown = 0
        for lv in self.levels:
            if kw and kw not in lv.Name.lower():
                continue
            self.add_row(self.lvl_list, "levels", key_of(lv), lv.Name,
                         self.lvl_state, "-> " + abbreviate_level(lv.Name), "Orange")
            shown += 1
        if not shown:
            self.lvl_list.Children.Add(self.empty_row("No matching levels."))

    def build_cvboxes(self, keyword):
        self.cvbox_list.Children.Clear()
        kw = (keyword or "").lower().strip()
        shown = 0
        for b in self.scope_boxes:
            if kw and kw not in b.Name.lower():
                continue
            rb = RadioButton()
            rb.GroupName = "CreateViewsScopeBox"
            rb.Tag = key_of(b)
            rb.Content = b.Name
            rb.IsChecked = (self.cv_box_key == key_of(b))

            def on_pick(sender, args):
                try:
                    self.cv_box_key = int(sender.Tag)
                    self.refresh()
                except Exception:
                    pass

            rb.Checked += on_pick
            self.cvbox_list.Children.Add(rb)
            shown += 1
        if not shown:
            self.cvbox_list.Children.Add(self.empty_row("No matching scope boxes."))

    # -- the pre-selection isolate -----------------------------------------
    def read_preselection(self):
        """Views picked in the Project Browser before the tool was opened."""
        host_keys = set(key_of(v) for v in self.host_views)
        try:
            ids = list(uidoc.Selection.GetElementIds())
        except Exception:
            return []

        found = []
        for element_id in ids:
            key = int(eid_value(element_id))
            if key in host_keys and key not in found:
                found.append(key)
        if found:
            return found

        # Nothing picked was a view itself, so fall back to the views the
        # picked elements live on - someone who picked a viewport meant its
        # sheet, and someone who picked an annotation meant its view.
        for element_id in ids:
            try:
                element = doc.GetElement(element_id)
                key = int(eid_value(element.OwnerViewId))
            except Exception:
                continue
            if key in host_keys and key not in found:
                found.append(key)
        return found

    def paint_isolate_chip(self):
        try:
            if self.isolate_keys:
                self.isolate_text.Text = (
                    "Isolated to {0} view(s) selected in Revit".format(
                        len(self.isolate_keys)))
                self.isolate_chip.Visibility = Visibility.Visible
            else:
                self.isolate_chip.Visibility = Visibility.Collapsed
        except Exception:
            pass

    @ui_safe
    def on_show_all_views(self, sender, args):
        """Drop the isolation and leave every tick exactly as it is."""
        self.isolate_keys = set()
        self.build_views(self.view_search.Text)
        self.refresh()

    def selected(self, state_dict):
        return [k for k in state_dict if state_dict[k]]

    def refresh(self):
        nv = len(self.selected(self.view_state))
        nb = len(self.selected(self.box_state))
        nt = len(self.selected(self.tpl_state))
        nl = len(self.selected(self.lvl_state))

        self.views_head.Text = "HOST VIEWS  ({0} of {1} selected)".format(
            nv, len(self.host_views))
        self.boxes_head.Text = "SCOPE BOXES  ({0} of {1} selected)".format(
            nb, len(self.scope_boxes))
        self.tpl_head.Text = "VIEW TEMPLATES  ({0} of {1} selected)".format(
            nt, len(self.templates))
        self.lvl_head.Text = "LEVELS  ({0} of {1} selected)".format(
            nl, len(self.levels))
        self.cvbox_head.Text = ("SCOPE BOX  (pick one)" if self.cv_box_key is None
                                else "SCOPE BOX  (1 picked)")

        ready = bool(nt and nl and self.cv_box_key is not None)
        self.btn_create.IsEnabled = ready and not self.busy
        self.btn_apply.IsEnabled = not self.busy

        if self.busy:
            return

        if self.current_tab() == 0:
            if ready:
                tags = ""
                try:
                    if bool(self.chk_room_tags.IsChecked):
                        tags = ", with room tags"
                except Exception:
                    pass
                self.set_status("{0} view(s) will be created{1}, e.g. {2}".format(
                    nt * nl, tags, self.sample_name()))
            else:
                missing = []
                if not nt:
                    missing.append("a view template")
                if not nl:
                    missing.append("a level")
                if self.cv_box_key is None:
                    missing.append("one scope box")
                self.set_status("Select " + ", ".join(missing) + ".")
        else:
            if nv and nb:
                self.set_status("{0} dependent view(s) will be created.".format(nv * nb))
            else:
                self.set_status("Select at least one view and one scope box.")

    def sample_name(self):
        tpl_keys = self.selected(self.tpl_state)
        lvl_keys = self.selected(self.lvl_state)
        if not tpl_keys or not lvl_keys:
            return ""
        tpl = self.elements.get(tpl_keys[0])
        lvl = self.elements.get(lvl_keys[0])
        if tpl is None or lvl is None:
            return ""
        abbr, _matched = abbreviate_template(tpl.Name)
        return "{0}{1}{2}".format(abbr, CREATE_SEPARATOR, abbreviate_level(lvl.Name))

    # -- debug --------------------------------------------------------------
    def log_environment(self, job):
        self.log = []
        self.log.append("RevoBIM PY - View Manager v{0}".format(VERSION))
        self.log.append("Job: {0}".format(job))
        self.log.append("Revit: {0}".format(revit_version()))
        self.log.append("Python: {0}".format(engine_version()))
        try:
            self.log.append("Document: {0} (workshared={1})".format(
                doc.Title, doc.IsWorkshared))
        except Exception:
            pass
        self.log.append("Counts: host views={0}, scope boxes={1}, templates={2}, "
                        "levels={3}".format(len(self.host_views), len(self.scope_boxes),
                                            len(self.templates), len(self.levels)))
        self.log.append("")

    def build_report(self):
        lines = []
        lines.append("I'm using the RevoBIM PY View Manager tool and hit a problem. "
                     "Here is the debug report - please work out what went wrong and "
                     "give me a fixed script.py.")
        lines.append("")
        lines.append("```")
        lines.extend(self.log)
        lines.append("```")
        self.report_text = "\n".join(lines)
        return self.report_text

    def offer_report(self):
        try:
            self.btn_report.Visibility = Visibility.Visible
        except Exception:
            pass

    @ui_safe
    def on_show_report(self, sender, args):
        text = self.report_text or self.build_report()
        DebugWindow(self.window, text).show()

    def finish(self, message, error=False, force_report=False):
        self.busy = False
        try:
            self.window.IsHitTestVisible = True
            self.prog_fill.Width = 0
        except Exception:
            pass
        self.set_status(message, error=error)
        self.refresh()
        self.set_status(message, error=error)
        if self.debug_on() or force_report:
            self.build_report()
            self.offer_report()
            if self.debug_on():
                DebugWindow(self.window, self.report_text).show()

    # -- the ask-first overlay ---------------------------------------------
    def ask_then(self, job):
        """Put the question up and hold the job until it is answered."""
        self.pending_job = job
        if not self.ask_before_creating:
            self.start_pending()
            return
        try:
            self.ask_overlay.Visibility = Visibility.Visible
        except Exception:
            self.start_pending()

    def start_pending(self):
        job = self.pending_job
        self.pending_job = None
        try:
            self.ask_overlay.Visibility = Visibility.Collapsed
        except Exception:
            pass
        if job is not None:
            self.queue(job)

    def remember_answer(self):
        try:
            if bool(self.ask_remember.IsChecked):
                self.ask_before_creating = False
        except Exception:
            pass

    @ui_safe
    def on_ask_fast(self, sender, args):
        self.fast_mode = True
        self.remember_answer()
        self.start_pending()

    @ui_safe
    def on_ask_normal(self, sender, args):
        self.fast_mode = False
        self.remember_answer()
        self.start_pending()

    @ui_safe
    def on_ask_cancel(self, sender, args):
        self.pending_job = None
        try:
            self.ask_overlay.Visibility = Visibility.Collapsed
        except Exception:
            pass
        self.set_status("Cancelled - nothing was created.")

    # -- queueing work to Revit --------------------------------------------
    def queue(self, job):
        """Hand work to the external event and return at once.

        Never wait for it: Revit raises the event on this very thread, so
        blocking here would deadlock the handler out of its turn.
        """
        self.busy = True
        self.btn_apply.IsEnabled = False
        self.btn_create.IsEnabled = False
        self.set_status("Working...")
        # Pumping the dispatcher to paint progress also pumps mouse and key
        # input, so the window is made untouchable until the run is done.
        try:
            self.window.IsHitTestVisible = False
        except Exception:
            pass
        HANDLER.job = job
        EVENT.Raise()

    def back_on_ui(self, fn):
        try:
            self.window.Dispatcher.Invoke(Action(fn))
        except Exception:
            try:
                fn()
            except Exception:
                pass

    # -- handlers -----------------------------------------------------------
    @ui_safe
    def on_drag(self, sender, args):
        self.window.DragMove()

    @ui_safe
    def on_close(self, sender, args):
        self.window.Close()

    def on_closed(self, sender, args):
        global WINDOW
        WINDOW = None

    @ui_safe
    def on_key(self, sender, args):
        if args.Key == Key.F5 and not self.busy:
            self.on_refresh(sender, args)

    @ui_safe
    def on_settings(self, sender, args):
        SettingsWindow(self.window, self.templates, self.levels, self.scope_boxes,
                       self.on_abbreviations_changed, start_tab=1).show()

    def on_room_tags_toggled(self, sender, args):
        try:
            self.refresh()
        except Exception:
            pass

    def on_theme_changed(self):
        """Rows built in code hold their brushes, so rebuild them."""
        try:
            self.rebuild_all()
        except Exception:
            pass

    def on_abbreviations_changed(self):
        """Relabel every list without disturbing the ticks."""
        try:
            self.rebuild_all()
        except Exception:
            pass

    @ui_safe
    def on_refresh(self, sender, args):
        if self.busy:
            return
        self.read_model()
        self.rebuild_all()

    @ui_safe
    def on_tab_changed(self, sender, args):
        if sender is not self.tabs:
            return
        first = self.current_tab() == 0
        self.btn_create.Visibility = Visibility.Visible if first else Visibility.Collapsed
        self.btn_apply.Visibility = Visibility.Collapsed if first else Visibility.Visible
        try:
            self.chk_room_tags.Visibility = Visibility.Visible if first else Visibility.Collapsed
        except Exception:
            pass
        self.refresh()

    @ui_safe
    def on_view_filter(self, sender, args):
        if self.loading_filters:
            return
        self.build_views(self.view_search.Text)
        self.refresh()

    @ui_safe
    def on_tpl_filter(self, sender, args):
        if self.loading_filters:
            return
        self.build_templates(self.tpl_search.Text)
        self.refresh()

    @ui_safe
    def on_view_search(self, sender, args):
        self.build_views(self.view_search.Text)

    @ui_safe
    def on_box_search(self, sender, args):
        self.build_boxes(self.box_search.Text)

    @ui_safe
    def on_tpl_search(self, sender, args):
        self.build_templates(self.tpl_search.Text)

    @ui_safe
    def on_lvl_search(self, sender, args):
        self.build_levels(self.lvl_search.Text)

    @ui_safe
    def on_cvbox_search(self, sender, args):
        self.build_cvboxes(self.cvbox_search.Text)

    @ui_safe
    def on_views_all(self, sender, args):
        self._bulk("views", self.view_state, True)

    @ui_safe
    def on_views_none(self, sender, args):
        self._bulk("views", self.view_state, False)

    @ui_safe
    def on_boxes_all(self, sender, args):
        self._bulk("boxes", self.box_state, True)

    @ui_safe
    def on_boxes_none(self, sender, args):
        self._bulk("boxes", self.box_state, False)

    @ui_safe
    def on_tpl_all(self, sender, args):
        self._bulk("templates", self.tpl_state, True)

    @ui_safe
    def on_tpl_none(self, sender, args):
        self._bulk("templates", self.tpl_state, False)

    @ui_safe
    def on_lvl_all(self, sender, args):
        self._bulk("levels", self.lvl_state, True)

    @ui_safe
    def on_lvl_none(self, sender, args):
        self._bulk("levels", self.lvl_state, False)

    @ui_safe
    def on_cvbox_clear(self, sender, args):
        self.cv_box_key = None
        for child in self.cvbox_list.Children:
            if isinstance(child, RadioButton):
                child.IsChecked = False
        self.refresh()

    # -- Create Views -------------------------------------------------------
    @ui_safe
    def on_create_views(self, sender, args):
        if self.busy:
            return
        tpl_keys = self.selected(self.tpl_state)
        lvl_keys = self.selected(self.lvl_state)
        box_key = self.cv_box_key

        if not tpl_keys or not lvl_keys or box_key is None:
            self.set_status("Select templates, levels and one scope box.", error=True)
            return

        self.log_environment("Create Views")
        tpl_keys = sorted(tpl_keys, key=lambda k: [key_of(t) for t in self.templates].index(k)
                          if k in [key_of(t) for t in self.templates] else 0)
        lvl_order = dict((key_of(lv), i) for i, lv in enumerate(self.levels))
        lvl_keys = sorted(lvl_keys, key=lambda k: lvl_order.get(k, 0))

        try:
            with_tags = bool(self.chk_room_tags.IsChecked)
        except Exception:
            with_tags = False
        with_links = setting_on("room_tags_links")

        self.ask_then(lambda event_uiapp: self.do_create_views(
            tpl_keys, lvl_keys, box_key, with_tags, with_links))

    def do_create_views(self, tpl_keys, lvl_keys, box_key, with_tags=False,
                        with_links=True):
        box = self.live(box_key)
        if box is None:
            self.back_on_ui(lambda: self.finish(
                "That scope box is no longer in the model - press Refresh.",
                error=True, force_report=True))
            return

        templates = [t for t in [self.live(k) for k in tpl_keys] if t is not None]
        levels = [lv for lv in [self.live(k) for k in lvl_keys] if lv is not None]
        if not templates or not levels:
            self.back_on_ui(lambda: self.finish(
                "The picked templates or levels are no longer in the model - "
                "press Refresh.", error=True, force_report=True))
            return

        self.log.append("Scope box: [{0}] {1}".format(key_of(box), box.Name))
        self.log.append("Selected templates:")
        for t in templates:
            family, type_name = plan_family_for(t.ViewType)
            abbr, matched = abbreviate_template(t.Name)
            self.log.append("  [{0}] {1}  ViewType={2}  ViewFamily={3}  abbr={4}{5}".format(
                key_of(t), t.Name, type_name, family, abbr,
                "" if matched else " (no keyword match)"))
        self.log.append("Selected levels:")
        for lv in levels:
            self.log.append("  [{0}] {1}  elev={2}  abbr={3}".format(
                key_of(lv), lv.Name, lv.Elevation, abbreviate_level(lv.Name)))
        self.log.append("")

        taken = existing_view_names(doc)
        cache = {}
        no_plan = []
        jobs = []

        for tpl in templates:
            vft = view_family_type_for(doc, tpl.ViewType, cache, self.log)
            if vft is None:
                if tpl.Name not in no_plan:
                    no_plan.append(tpl.Name)
                self.log.append("SKIP  template '{0}' - no plan ViewFamilyType "
                                "for ViewType {1}".format(tpl.Name, tpl.ViewType))
                continue

            abbr, _matched = abbreviate_template(tpl.Name)
            vft_name = type_name_of(vft)
            self.log.append("Template '{0}' -> ViewFamilyType '{1}' [{2}]".format(
                tpl.Name, vft_name, key_of(vft)))

            for lvl in levels:
                jobs.append(self.make_view_job(tpl, vft, vft_name, lvl, box,
                                               abbr, taken))

        if not jobs:
            self.back_on_ui(lambda: self.finish(
                "Nothing to create - none of the picked templates are plan "
                "templates.", error=True, force_report=True))
            return

        after = None
        if with_tags:
            def after():
                self.tag_new_views(with_links)

        created, failed, elapsed = self.run_batched(jobs, taken, "views", after=after)

        msg = "Created {0} view(s) on {1} in {2}".format(
            created, box.Name, pretty_time(elapsed))
        stats = getattr(self, "tag_stats", None) or {}
        if with_tags and stats.get("note"):
            msg += "  -  " + stats["note"]
        elif with_tags:
            msg += "  -  {0} room tag(s)".format(stats.get("tagged", 0))
            if stats.get("refused"):
                msg += ", {0} refused".format(stats["refused"])
        if no_plan:
            msg += "  -  not a plan template: " + ", ".join(no_plan[:3])
            if len(no_plan) > 3:
                msg += " +{0} more".format(len(no_plan) - 3)
        if failed:
            msg += "  -  {0} failed".format(failed)

        self.log_timings(created, failed, elapsed)
        self.log.append("Result: created={0}, failed={1}, skipped templates={2}".format(
            created, failed, len(no_plan)))

        def done():
            self.read_model()
            self.rebuild_all()
            self.finish(msg + ".", error=bool(failed or no_plan),
                        force_report=bool(failed))

        self.back_on_ui(done)

    def make_view_job(self, tpl, vft, vft_name, lvl, box, abbr, taken):
        """One view, as a callable the batch runner can replay on its own."""
        target = sanitise("{0}{1}{2}".format(
            abbr, CREATE_SEPARATOR, abbreviate_level(lvl.Name)))

        def job(added):
            stage = ["start"]
            try:
                final = unique_name(target, taken)

                stage[0] = "ViewPlan.Create"
                clock = Stopwatch.StartNew()
                made = ViewPlan.Create(doc, vft.Id, lvl.Id)
                new_view = as_element(doc, made)
                if new_view is None:
                    raise Exception("ViewPlan.Create returned nothing usable "
                                    "({0})".format(type(made).__name__))
                self.timings["create"] += clock.ElapsedMilliseconds

                # name first: a template never locks the name, but it can lock
                # the crop and scope box parameters.
                stage[0] = "rename"
                clock = Stopwatch.StartNew()
                ok_name, name_note = set_name(new_view, final)
                if not ok_name:
                    final = unique_name(target + " 1", taken)
                    ok_name, name_note = set_name(new_view, final)
                self.timings["name"] += clock.ElapsedMilliseconds

                hidden_worksets = []
                quiet_note = ""
                if self.fast_mode:
                    stage[0] = "hide links and worksets"
                    clock = Stopwatch.StartNew()
                    hidden_worksets, quiet_note = quieten_view(doc, new_view)
                    self.timings["quieten"] += clock.ElapsedMilliseconds

                stage[0] = "scope box"
                clock = Stopwatch.StartNew()
                ok_box, box_note = apply_scope_box(new_view, box.Id, verify=False)
                self.timings["scopebox"] += clock.ElapsedMilliseconds

                stage[0] = "view template"
                clock = Stopwatch.StartNew()
                ok_tpl, tpl_note = apply_template(new_view, tpl)
                self.timings["template"] += clock.ElapsedMilliseconds

                if hidden_worksets:
                    stage[0] = "restore worksets"
                    clock = Stopwatch.StartNew()
                    restore_quiet(new_view, hidden_worksets)
                    self.timings["restore"] += clock.ElapsedMilliseconds

                # Only re-assert the scope box where the template actually took
                # it away. Writing it twice every time cost a parameter write
                # and a crop recompute per view for nothing.
                if ok_tpl and ok_box:
                    stage[0] = "scope box (recheck)"
                    if not scope_box_holds(new_view, box.Id):
                        ok_box, box_note = apply_scope_box(new_view, box.Id,
                                                           verify=False)

                taken.add(final)
                added.append(final)
                self.chunk_views.append(new_view.Id)

                note = []
                if not ok_name:
                    note.append("name: " + name_note)
                if not ok_box:
                    note.append("scope box: " + box_note)
                if not ok_tpl:
                    note.append("template: " + tpl_note)
                if quiet_note:
                    note.append("quieten: " + quiet_note)
                return "OK    {0}  [{1}]{2}".format(
                    final, key_of(new_view),
                    "   WARN " + "; ".join(note) if note else "")
            except Exception as ex:
                raise JobFailed(
                    "FAIL  {0}  at stage '{1}'\n"
                    "      template [{2}] {3}, level [{4}] {5}, VFT [{6}] {7}\n"
                    "      {8}\n      {9}".format(
                        target, stage[0], key_of(tpl), tpl.Name,
                        key_of(lvl), lvl.Name, key_of(vft), vft_name,
                        describe(ex),
                        traceback.format_exc().replace("\n", "\n      ").rstrip()))

        return job

    # -- Dependent Views ----------------------------------------------------
    @ui_safe
    def on_apply_dependents(self, sender, args):
        if self.busy:
            return
        view_keys = self.selected(self.view_state)
        box_keys = self.selected(self.box_state)

        if not view_keys:
            self.set_status("Select at least one host view.", error=True)
            return
        if not box_keys:
            self.set_status("Select at least one scope box.", error=True)
            return

        self.log_environment("Apply Dependents")
        view_order = dict((key_of(v), i) for i, v in enumerate(self.host_views))
        box_order = dict((key_of(b), i) for i, b in enumerate(self.scope_boxes))
        view_keys = sorted(view_keys, key=lambda k: view_order.get(k, 0))
        box_keys = sorted(box_keys, key=lambda k: box_order.get(k, 0))

        self.ask_then(lambda event_uiapp: self.do_apply_dependents(
            view_keys, box_keys))

    def do_apply_dependents(self, view_keys, box_keys):
        views = [v for v in [self.live(k) for k in view_keys] if v is not None]
        boxes = [b for b in [self.live(k) for k in box_keys] if b is not None]
        if not views or not boxes:
            self.back_on_ui(lambda: self.finish(
                "The picked views or scope boxes are no longer in the model - "
                "press Refresh.", error=True, force_report=True))
            return

        self.log.append("Selected host views:")
        for v in views:
            self.log.append("  [{0}] {1}  ({2})".format(key_of(v), v.Name, v.ViewType))
        self.log.append("Selected scope boxes:")
        for b in boxes:
            self.log.append("  [{0}] {1}".format(key_of(b), b.Name))
        self.log.append("")

        taken = existing_view_names(doc)
        jobs = []
        skipped = 0
        for host in views:
            for box in boxes:
                target = sanitise("{0}{1}{2}{3}".format(
                    NAME_PREFIX, host.Name, NAME_SEPARATOR, box_abbr(box.Name)))
                if target in taken:
                    skipped += 1
                    self.log.append("SKIP  {0} - a view of that name exists".format(target))
                    continue
                jobs.append(self.make_dependent_job(host, box, target, taken))

        if not jobs:
            self.back_on_ui(lambda: self.finish(
                "Nothing to create - every dependent already exists.",
                error=False))
            return

        created, failed, elapsed = self.run_batched(jobs, taken, "dependents")

        msg = "Created {0} dependent view(s) in {1}".format(
            created, pretty_time(elapsed))
        if skipped:
            msg += "  -  {0} already existed".format(skipped)
        if failed:
            msg += "  -  {0} failed".format(failed)

        self.log_timings(created, failed, elapsed)
        self.log.append("Result: created={0}, skipped={1}, failed={2}".format(
            created, skipped, failed))

        def done():
            self.read_model()
            self.rebuild_all()
            self.finish(msg + ".", error=bool(failed), force_report=bool(failed))

        self.back_on_ui(done)

    def make_dependent_job(self, host, box, target, taken):
        def job(added):
            stage = ["start"]
            try:
                stage[0] = "Duplicate"
                clock = Stopwatch.StartNew()
                made = host.Duplicate(ViewDuplicateOption.AsDependent)
                new_view = as_element(doc, made)
                if new_view is None:
                    raise Exception("Duplicate returned nothing usable "
                                    "({0})".format(type(made).__name__))
                self.timings["create"] += clock.ElapsedMilliseconds

                hidden_worksets = []
                if self.fast_mode:
                    stage[0] = "hide links and worksets"
                    clock = Stopwatch.StartNew()
                    hidden_worksets, _quiet = quieten_view(doc, new_view)
                    self.timings["quieten"] += clock.ElapsedMilliseconds

                stage[0] = "scope box"
                clock = Stopwatch.StartNew()
                ok_box, box_note = apply_scope_box(new_view, box.Id, verify=False)
                self.timings["scopebox"] += clock.ElapsedMilliseconds

                if hidden_worksets:
                    stage[0] = "restore worksets"
                    clock = Stopwatch.StartNew()
                    restore_quiet(new_view, hidden_worksets)
                    self.timings["restore"] += clock.ElapsedMilliseconds

                stage[0] = "rename"
                clock = Stopwatch.StartNew()
                final = unique_name(target, taken)
                ok_name, name_note = set_name(new_view, final)
                if not ok_name:
                    final = unique_name(target + " 1", taken)
                    ok_name, name_note = set_name(new_view, final)
                self.timings["name"] += clock.ElapsedMilliseconds

                taken.add(final)
                added.append(final)

                note = []
                if not ok_box:
                    note.append("scope box: " + box_note)
                if not ok_name:
                    note.append("name: " + name_note)
                return "OK    {0}  [{1}]{2}".format(
                    final, key_of(new_view),
                    "   WARN " + "; ".join(note) if note else "")
            except Exception as ex:
                raise JobFailed(
                    "FAIL  {0}  at stage '{1}'\n"
                    "      host [{2}] {3}, box [{4}] {5}\n"
                    "      {6}\n      {7}".format(
                        target, stage[0], key_of(host), host.Name,
                        key_of(box), box.Name, describe(ex),
                        traceback.format_exc().replace("\n", "\n      ").rstrip()))

        return job

    # -- the batch runner ---------------------------------------------------
    def run_batched(self, jobs, taken, label, after=None):
        """Many views per transaction, because a commit is a regeneration.

        One transaction per view meant one full document regeneration per
        view, which is where the time was going. A chunk Revit refuses is
        rolled back and replayed one at a time, so a single bad view is named
        and only that one is lost - the batch is not.
        """
        self.timings = {"create": 0, "name": 0, "quieten": 0, "scopebox": 0,
                        "template": 0, "restore": 0, "commit": 0, "tags": 0}
        self.created_view_ids = []
        self.chunk_views = []
        self.tag_stats = {}
        created = 0
        failed = 0
        total = len(jobs)
        index = 0
        run_clock = Stopwatch.StartNew()

        suppress_dialogs(True)
        try:
            tgroup = TransactionGroup(doc, "View Manager")
            tgroup.Start()
            try:
                while index < total:
                    chunk = jobs[index:index + CHUNK_SIZE]
                    ok, lines = self.try_chunk(chunk, taken)
                    if ok:
                        created += len(chunk)
                        self.log.extend(lines)
                    else:
                        self.log.append("      chunk of {0} refused - replaying "
                                        "one at a time".format(len(chunk)))
                        for job in chunk:
                            ok_one, lines_one = self.try_chunk([job], taken)
                            if ok_one:
                                created += 1
                            else:
                                failed += 1
                            self.log.extend(lines_one)
                    index += len(chunk)
                    # between chunks only - never with a transaction open
                    self.report_progress(index, total, label)
                if after is not None:
                    # a tagging failure must not take the views down with it
                    try:
                        after()
                    except Exception as ex:
                        self.log.append("FAIL  after the views - " + describe(ex))
                        self.log.append(traceback.format_exc())
                tgroup.Assimilate()
            except Exception as ex:
                if tgroup.HasStarted():
                    tgroup.RollBack()
                self.log.append("ABORTED: " + describe(ex))
                self.log.append(traceback.format_exc())
                raise
        finally:
            suppress_dialogs(False)

        return created, failed, run_clock.ElapsedMilliseconds

    def try_chunk(self, jobs, taken):
        """Run a chunk in one transaction. Returns (committed, log lines)."""
        lines = []
        added = []
        self.chunk_views = []
        t = Transaction(doc, "View Manager")
        t.Start()
        quiet_options(t)

        try:
            for job in jobs:
                lines.append(job(added))
            clock = Stopwatch.StartNew()
            status = t.Commit()
            self.timings["commit"] += clock.ElapsedMilliseconds
            if str(status) != "Committed":
                raise Exception("transaction status was " + str(status))
            # only views whose chunk committed are real enough to tag
            self.created_view_ids.extend(self.chunk_views)
            return True, lines
        except Exception as ex:
            if t.HasStarted():
                try:
                    t.RollBack()
                except Exception:
                    pass
            # the rollback undid the views, so release the names they claimed
            for name in added:
                taken.discard(name)
            text = str(ex) if isinstance(ex, JobFailed) else (
                "FAIL  chunk\n      " + describe(ex))
            return False, ([text] if len(jobs) == 1 else [])

    def tag_new_views(self, with_links):
        """Tag the rooms each committed view cuts, a few views per transaction."""
        clock = Stopwatch.StartNew()
        self.tag_stats = {"tagged": 0, "refused": 0, "views": 0}
        ids = list(self.created_view_ids)
        self.log.append("")
        self.log.append("Room tags ({0} view(s), links {1}):".format(
            len(ids), "included" if with_links else "left out"))
        if not ids:
            return

        type_id, label, note = resolve_room_tag_type(doc)
        if type_id is None:
            self.tag_stats["note"] = note or "no room tag loaded - nothing tagged"
            self.log.append("  " + self.tag_stats["note"])
            return
        self.log.append("  tag: {0}".format(label))
        if note:
            self.log.append("  " + note)

        rooms = collect_room_records(doc, with_links, self.log)
        if not rooms:
            self.tag_stats["note"] = "no placed rooms found - nothing tagged"
            self.log.append("  " + self.tag_stats["note"])
            return

        total = len(ids)
        for start in range(0, total, TAG_VIEWS_PER_TRANSACTION):
            chunk = ids[start:start + TAG_VIEWS_PER_TRANSACTION]
            lines = []
            t = Transaction(doc, "View Manager - room tags")
            t.Start()
            quiet_options(t)
            try:
                for view_id in chunk:
                    view = doc.GetElement(view_id)
                    if view is None:
                        continue
                    placed, wanted = tag_rooms_in_view(doc, view, rooms, type_id,
                                                       self.tag_stats)
                    lines.append("  {0}: {1} of {2} room(s) tagged".format(
                        view.Name, placed, wanted))
                status = t.Commit()
                if str(status) != "Committed":
                    raise Exception("transaction status was " + str(status))
                self.log.extend(lines)
            except Exception as ex:
                if t.HasStarted():
                    try:
                        t.RollBack()
                    except Exception:
                        pass
                self.log.append("  FAIL  tagging {0} view(s) - {1}".format(
                    len(chunk), describe(ex)))
            self.report_progress(min(start + len(chunk), total), total, "room tags")

        if self.tag_stats.get("first_refusal"):
            self.log.append("  first refusal: " + self.tag_stats["first_refusal"] +
                            "  (usually a template hiding Rooms)")
        self.timings["tags"] += clock.ElapsedMilliseconds

    def log_timings(self, created, failed, elapsed):
        self.log.append("")
        self.log.append("Timing: {0} total for {1} created, {2} failed".format(
            pretty_time(elapsed), created, failed))
        for key in ("create", "name", "quieten", "scopebox", "template",
                    "restore", "commit", "tags"):
            value = self.timings.get(key, 0)
            if value:
                self.log.append("  {0:<10} {1}".format(key, pretty_time(value)))
        if created:
            self.log.append("  {0:<10} {1} per view".format(
                "average", pretty_time(float(elapsed) / created)))
        self.log.append("  fast mode {0}".format(
            "ON - links and worksets hidden while cropping"
            if self.fast_mode else "off"))
        self.log.append("  chunk size {0}, {1} transaction(s)".format(
            CHUNK_SIZE, (created + failed + CHUNK_SIZE - 1) // max(CHUNK_SIZE, 1)))
        self.log.append("")

    def report_progress(self, done, total, label):
        def paint():
            try:
                fraction = float(done) / float(total) if total else 0.0
                width = self.prog_track.ActualWidth * fraction
                self.prog_fill.Width = width if width > 0 else 0
                self.set_status("Creating {0}...  {1} of {2}".format(
                    label, done, total))
            except Exception:
                pass
        try:
            self.window.Dispatcher.Invoke(Action(paint), DispatcherPriority.Background)
        except Exception:
            paint()


    # -- show ---------------------------------------------------------------
    def show(self):
        # Owned to Revit's main window, or a modeless window slips behind
        # Revit and reads as a crash.
        try:
            WindowInteropHelper(self.window).Owner = uiapp.MainWindowHandle
        except Exception:
            pass
        self.window.Show()

    def activate(self):
        try:
            if self.chrome.state == Chrome.SHRUNK:
                self.chrome.expand()
                return
        except Exception:
            pass
        try:
            if self.window.WindowState.ToString() == "Minimized":
                from System.Windows import WindowState
                self.window.WindowState = WindowState.Normal
        except Exception:
            pass
        try:
            self.window.Activate()
        except Exception:
            pass


# ---------------------------------------------------------------------------
#  Entry point  (silent - no TaskDialog, no pyRevit output)
# ---------------------------------------------------------------------------
def main():
    global WINDOW, EVENT, HANDLER

    if WINDOW is not None:
        # already open: bring it forward rather than opening a second copy
        WINDOW.activate()
        return

    load_settings()
    resolve_theme()
    load_overrides()
    hook_dialogs()

    if HANDLER is None:
        HANDLER = ViewManagerEventHandler()
    if EVENT is None:
        EVENT = ExternalEvent.Create(HANDLER)

    WINDOW = ViewManagerWindow()
    if not WINDOW.scope_boxes:
        WINDOW.set_status("No scope boxes found in this project.", error=True)
    WINDOW.show()


try:
    main()
except Exception:
    # Nothing to report into - the window never opened. Leave a file behind
    # rather than a pyRevit traceback window.
    try:
        handle = open(os.path.join(log_folder(), "view_manager_last_error.txt"), "w")
        try:
            handle.write("RevoBIM PY - View Manager v{0}\n".format(VERSION))
            handle.write(traceback.format_exc())
        finally:
            handle.close()
    except Exception:
        pass
