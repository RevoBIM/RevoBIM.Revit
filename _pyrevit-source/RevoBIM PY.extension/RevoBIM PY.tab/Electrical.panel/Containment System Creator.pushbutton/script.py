# -*- coding: utf-8 -*-
"""Containment System Creator - RevoBIM PY

Creates a complete containment service type in one go, and edits existing
ones across all their fittings.

The model holds containment service types as Revit families and types:
"Cable Tray with Fittings" and "Conduit with Fittings" system types, each of
which points at a fitting family type for every fitting slot it owns
(horizontal bend, vertical inside bend, tee, cross, transition, union ...).

Containment kinds follow the Revit categories the model actually uses:
Cable Tray and Cable Ladder are tray types named as such, while Cable Trunking
and Cable Basket are also Cable Tray system types whose identity lives in the
family naming ("_TrunkingTray", "_Cable Basket") rather than the type name.
The kind of every type is therefore resolved from its type name first, then
its system family name, then its fitting family names. Conduit kinds are
auto-detected from the naming tokens present in the model.

Given a containment kind and a new service name, this tool:

  1. takes the first matching source type, e.g. BGL_Ladder_LV_SubMain
  2. duplicates it and renames it, e.g. BGL_Ladder_ELV
  3. duplicates EVERY fitting type that source type references, renames each
     one to the new service name
  4. writes BGL_Function and BGL_Type Mark on the new system type and,
     optionally, on each new fitting type
  5. assigns the newly created fitting types back onto the new system type

Everything happens inside one transaction, so a failure rolls the whole
service back rather than leaving a half-built system behind.

Every window the tool opens can be shrunk to its header bar at the bottom of
the screen so the model can be seen - see csc_drawer.py.
"""

__title__ = "Containment\nSystem Creator"
__author__ = "RevoBIM"
__version__ = "1.4.1"
__doc__ = ("Create a new containment service type (cable tray or conduit) by "
           "duplicating an existing 'with fittings' type together with all of "
           "its fitting types, renaming them and stamping BGL_Function and "
           "Type Mark on all of them.")

import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
# a cached copy from an older install must not outlive an upgrade
for _module in ("csc_clr", "csc_drawer"):
    sys.modules.pop(_module, None)

import csc_clr  # noqa: F401  assemblies first, ahead of every System import
import csc_drawer

from System.Windows import (FontWeights, Thickness, Visibility,
                            VerticalAlignment)
from System.Windows.Controls import (TreeViewItem, StackPanel, TextBlock,
                                     Orientation, ComboBoxItem)
from System.Windows.Media import SolidColorBrush, Color
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption

from pyrevit import forms, script, revit

from Autodesk.Revit.DB import (FilteredElementCollector, Transaction, Element,
                               ElementId, FamilySymbol, Category,
                               BuiltInCategory, BuiltInParameter, StorageType)
from Autodesk.Revit.DB.Electrical import CableTrayType, ConduitType


# ===========================================================================
# constants
# ===========================================================================

DOC = revit.doc

# Containment kinds for the Cable Tray category.
#
# Trunking and Basket are not separate Revit categories - they are Cable Tray
# system types, and what identifies them is the naming token, which may sit on
# the type name, on the system family name, or on the fitting family names.
# Each kind therefore carries every spelling it is known by; the longest alias
# that matches wins, so "BGL_TrunkingTray_..." lands on Cable Trunking rather
# than being swept up by the generic "Tray" alias.
TRAY_KIND_DEFS = [
    ("Cable Tray",     ["Cable Tray", "CableTray", "Tray"]),
    ("Cable Ladder",   ["Cable Ladder", "CableLadder", "Ladder"]),
    ("Cable Trunking", ["Trunking Tray", "TrunkingTray", "Trunking"]),
    ("Cable Basket",   ["Cable Basket", "CableBasket", "Basket"]),
]

UNFILTERED = "All types (kind auto-detected)"

FIT_SCHEMES = [
    ("Full prefix   e.g.  BGL_Ladder_ELV", "full"),
    ("Name only     e.g.  ELV", "name"),
    ("Swap token    e.g.  LV Sub-Main -> ELV", "swap"),
]

MARK_PARAM_NAMES = ["BGL_Type Mark", "BGL_TypeMark", "BGL_Type_Mark"]

BLUE = SolidColorBrush(Color.FromRgb(79, 163, 227))
ORANGE = SolidColorBrush(Color.FromRgb(232, 145, 45))
GREY = SolidColorBrush(Color.FromRgb(157, 164, 178))    # Revit icon grey
WHITE = SolidColorBrush(Color.FromRgb(232, 240, 248))   # Revit text
RED = SolidColorBrush(Color.FromRgb(217, 83, 79))
GREEN = SolidColorBrush(Color.FromRgb(78, 192, 109))

ICON_PATH = script.get_bundle_file("icon.png")


# ===========================================================================
# small helpers
# ===========================================================================

def eid_value(element_id):
    """An ElementId as a plain number, across Revit releases.

    Revit 2024 added ElementId.Value (Int64) and deprecated IntegerValue;
    IntegerValue was then removed in 2026. Prefer the new property and fall
    back to the old one so the same code runs on 2024 through 2027.
    """
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


def same_id(first, second):
    return eid_value(first) == eid_value(second)


def get_name(elem):
    """Element name, working around the IronPython Element.Name ambiguity."""
    if elem is None:
        return ""
    try:
        return elem.Name
    except Exception:
        pass
    try:
        return Element.Name.GetValue(elem)
    except Exception:
        return ""


def norm(text):
    """Lower-case, alphanumerics only."""
    if not text:
        return ""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def norm_map(text):
    """Normalised string plus a map from normalised index to original index."""
    chars = []
    idx = []
    for i, ch in enumerate(text):
        if ch.isalnum():
            chars.append(ch.lower())
            idx.append(i)
    return "".join(chars), idx


def loose_replace(text, find, repl):
    """Replace `find` inside `text` ignoring case and separators.

    "LV Sub-Main" with find "LV_SubMain" -> repl.  Returns None if not found.
    """
    ntext, imap = norm_map(text)
    nfind, _ = norm_map(find)
    if not nfind or not ntext:
        return None
    pos = ntext.find(nfind)
    if pos < 0:
        return None
    start = imap[pos]
    end = imap[pos + len(nfind) - 1] + 1
    return text[:start] + repl + text[end:]


def split_parts(name):
    """Split on separators keeping them, so the name can be rebuilt exactly.

    Tokens land on even indices, separators on odd ones.
    """
    return re.split(r"([_\s\-]+)", name or "")


def raw_tokens(name):
    """The word tokens of a name, index-aligned with split_parts."""
    return split_parts(name)[0::2]


def kind_token_span(type_name, kind):
    """Find `kind` as a whole run of tokens. Returns (start, end) or None.

    "BGL_Ladder_LV_SubMain" + "Ladder"     -> (1, 2)
    "BGL_Cable_Tray_LV"     + "Cable Tray" -> (1, 3)
    "BGL_FlexConduit_LV"    + "Conduit"    -> None  (not a whole token)
    """
    needle = norm(kind)
    if not needle:
        return None
    toks = [norm(t) for t in raw_tokens(type_name)]
    for i in range(len(toks)):
        joined = ""
        for j in range(i, len(toks)):
            joined += toks[j]
            if joined == needle:
                return (i, j + 1)
            if len(joined) > len(needle):
                break
    return None


def kind_matches(type_name, kind):
    return kind_token_span(type_name, kind) is not None


class Kind(object):
    """A containment kind and every naming token it answers to."""

    def __init__(self, label, aliases=None):
        self.label = label
        names = list(aliases) if aliases else [label]
        if label not in names:
            names.append(label)
        # longest first, so the most specific spelling wins
        self.aliases = sorted(names, key=lambda a: -len(norm(a)))

    def match_in(self, text):
        """The longest alias present in `text`, spelled as `text` spells it.

        Returning the spelling found rather than the alias definition matters:
        grafting the kind onto a new type name must reproduce the model's own
        spelling ("TrunkingTray"), not the canonical one ("Trunking Tray").
        """
        if not text:
            return None
        for alias in self.aliases:
            span = kind_token_span(text, alias)
            if span is not None:
                parts = split_parts(text)
                return "".join(parts[2 * span[0]:2 * span[1] - 1])
        return None


def tray_kinds():
    return [Kind(label, aliases) for label, aliases in TRAY_KIND_DEFS]


def best_kind(kinds, text):
    """(Kind, alias) with the longest alias matching `text`, or (None, None)."""
    winner = None
    winning_alias = None
    best_len = -1
    for kind in kinds:
        alias = kind.match_in(text)
        if alias is None:
            continue
        length = len(norm(alias))
        if length > best_len:
            winner, winning_alias, best_len = kind, alias, length
    return winner, winning_alias


def family_signal(family_name):
    """The part of a system family name that actually says something.

    Every Cable Tray type lives in a family called "Cable Tray with Fittings",
    so the raw family name would match the generic "Cable Tray" kind for
    Trunking and Basket types too and drown out the real signal. Strip the
    "with/without fittings" suffix, and if what is left is just the category
    name, treat the family name as carrying no information.
    """
    stripped = re.sub(r"with(out)?\s+fittings\s*$", "", family_name or "",
                      flags=re.IGNORECASE).strip(" _-")
    if norm(stripped) in ("cabletray", "conduit", ""):
        return ""
    return stripped


def assign_kind(info, kinds):
    """Work out which containment kind a system type belongs to.

    Looks at the type name first, then the system family name, then the
    fitting family names - Trunking and Basket are Cable Tray system types
    whose identity lives in the family naming ("_TrunkingTray",
    "_Cable Basket") rather than in the type name.
    """
    kind, alias = best_kind(kinds, info.name)
    if kind is not None:
        return kind, alias, alias          # alias also found in the type name

    kind, alias = best_kind(kinds, family_signal(info.family_name))
    if kind is not None:
        return kind, alias, None

    winner = None
    winning_alias = None
    best_len = -1
    for family in info.fitting_family_names:
        found, alias = best_kind(kinds, family)
        if found is None:
            continue
        length = len(norm(alias))
        if length > best_len:
            winner, winning_alias, best_len = found, alias, length
    return winner, winning_alias, None


def common_token_depth(names):
    """How many leading tokens every name shares (the company prefix)."""
    token_lists = [raw_tokens(n) for n in names if n]
    token_lists = [t for t in token_lists if t]
    if not token_lists:
        return 0
    if len(token_lists) == 1:
        return 1 if len(token_lists[0]) > 1 else 0
    depth = 0
    shortest = min(len(t) for t in token_lists)
    while depth < shortest - 1:
        first = token_lists[0][depth].lower()
        if all(t[depth].lower() == first for t in token_lists):
            depth += 1
        else:
            break
    return depth


def detect_kinds(names):
    """Auto-detect the containment kind tokens present in a set of names."""
    depth = common_token_depth(names)
    found = []
    seen = set()
    for name in names:
        toks = raw_tokens(name)
        if len(toks) > depth:
            tok = toks[depth]
        elif toks:
            tok = toks[-1]
        else:
            continue
        if not tok:
            continue
        key = tok.lower()
        if key not in seen:
            seen.add(key)
            found.append(tok)
    return sorted(found, key=lambda s: s.lower()), depth


def prefix_and_sep(source_name, alias, auto_depth):
    """Return (prefix, separator) for building the new type name.

    "BGL_Ladder_LV_SubMain" + alias "Ladder" -> ("BGL_Ladder", "_")

    `alias` is the kind spelling that appears in the TYPE name. When the kind
    is only identifiable from the family naming - as with Trunking and Basket -
    there is no token to cut at, so the shared prefix of every type in the
    class is used instead and the user can edit the resulting name.
    """
    parts = split_parts(source_name)
    token_count = (len(parts) + 1) // 2

    span = kind_token_span(source_name, alias) if alias else None

    if span is not None:
        last_token = span[1] - 1
    else:
        last_token = auto_depth
    if last_token > token_count - 1:
        last_token = token_count - 1
    if last_token < 0:
        last_token = 0

    cut = 2 * last_token + 1
    prefix = "".join(parts[:cut])
    sep = parts[cut] if len(parts) > cut else "_"
    return prefix, sep


def service_token(source_name, prefix, sep):
    """The part of the source name that names the service, e.g. LV_SubMain."""
    tail = source_name[len(prefix):]
    if tail.startswith(sep):
        tail = tail[len(sep):]
    return tail.strip("_- ")


def shared_stem(source_name, auto_depth):
    """The leading tokens every type in the class shares, e.g. "BGL"."""
    parts = split_parts(source_name)
    token_count = (len(parts) + 1) // 2
    last = auto_depth - 1
    if last > token_count - 1:
        last = token_count - 1
    if last < 0:
        return "", "_"
    cut = 2 * last + 1
    return "".join(parts[:cut]), (parts[cut] if len(parts) > cut else "_")


def fitting_category_ids(doc):
    ids = set()
    for bic in (BuiltInCategory.OST_CableTrayFitting,
                BuiltInCategory.OST_ConduitFitting):
        try:
            cat = Category.GetCategory(doc, bic)
            if cat is not None:
                ids.add(eid_value(cat.Id))
        except Exception:
            pass
    return ids


FITTING_CAT_IDS = fitting_category_ids(DOC) if DOC is not None else set()


def is_fitting_symbol(elem):
    if not isinstance(elem, FamilySymbol):
        return False
    cat = elem.Category
    if cat is None:
        return False
    try:
        if eid_value(cat.Id) in FITTING_CAT_IDS:
            return True
    except Exception:
        pass
    try:
        return "fitting" in cat.Name.lower()
    except Exception:
        return False


# ===========================================================================
# parameter helpers
# ===========================================================================

def find_function_param(elem):
    """BGL_Function, or the closest thing to it on this element."""
    param = elem.LookupParameter("BGL_Function")
    if param is not None:
        return param
    best = None
    for p in elem.Parameters:
        try:
            pname = p.Definition.Name
        except Exception:
            continue
        low = pname.lower()
        if "function" not in low:
            continue
        if p.IsReadOnly:
            continue
        if low.startswith("bgl"):
            return p
        if best is None:
            best = p
    return best


def find_mark_param(elem):
    """The project's own type mark parameter, falling back to Revit's.

    The model carries BGL_Type Mark as a shared parameter; the built-in
    Type Mark is only used where that is missing.
    """
    for pname in MARK_PARAM_NAMES:
        param = elem.LookupParameter(pname)
        if param is not None and not param.IsReadOnly:
            return param
    for param in elem.Parameters:
        try:
            pname = norm(param.Definition.Name)
        except Exception:
            continue
        if pname.startswith("bgl") and "typemark" in pname \
                and not param.IsReadOnly:
            return param
    try:
        param = elem.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_MARK)
        if param is not None:
            return param
    except Exception:
        pass
    return elem.LookupParameter("Type Mark")


def param_label(param, fallback="(not found)"):
    if param is None:
        return fallback
    try:
        return param.Definition.Name
    except Exception:
        return fallback


def set_element_name(elem, new_name):
    """Rename an element, working around the IronPython Name ambiguity.

    FamilySymbol hides Element.Name, and which of the two routes works varies
    with the IronPython version, so try both and confirm by reading the name
    back rather than trusting that no exception means success.
    """
    try:
        elem.Name = new_name
    except Exception:
        pass
    if get_name(elem) == new_name:
        return True
    try:
        Element.Name.SetValue(elem, new_name)
    except Exception:
        pass
    return get_name(elem) == new_name


def read_param_text(param):
    if param is None:
        return ""
    try:
        if param.StorageType == StorageType.String:
            return param.AsString() or ""
        value = param.AsValueString()
        return value or ""
    except Exception:
        return ""


def write_param_text(param, value):
    """Best-effort write of a string onto a parameter. Returns True on success."""
    if param is None or param.IsReadOnly:
        return False
    try:
        stype = param.StorageType
        if stype == StorageType.String:
            param.Set(value)
            return True
        if stype == StorageType.Integer:
            param.Set(int(value))
            return True
        if stype == StorageType.Double:
            param.Set(float(value))
            return True
    except Exception:
        return False
    return False


def find_param_like(elem, definition, pname):
    """Locate the same parameter on another element."""
    try:
        param = elem.get_Parameter(definition)
        if param is not None:
            return param
    except Exception:
        pass
    for p in elem.Parameters:
        try:
            if p.Definition is not None and p.Definition.Name == pname:
                return p
        except Exception:
            continue
    return None


# ===========================================================================
# model reading
# ===========================================================================

class FittingSlot(object):
    """One fitting parameter on a system type, e.g. 'Horizontal Bend'."""

    def __init__(self, param, symbol):
        self.name = param.Definition.Name
        self.definition = param.Definition
        self.symbol = symbol
        self.symbol_id = symbol.Id
        self.family = symbol.Family
        self.family_name = get_name(symbol.Family)
        self.type_name = get_name(symbol)

    def label(self):
        return "{0} : {1}".format(self.family_name, self.type_name)


class SystemTypeInfo(object):
    """A cable tray / conduit system type and the fittings it points at."""

    def __init__(self, doc, etype):
        self.doc = doc
        self.etype = etype
        self.id = etype.Id
        self.name = get_name(etype)
        try:
            self.family_name = etype.FamilyName or ""
        except Exception:
            self.family_name = ""
        fn_param = find_function_param(etype)
        mk_param = find_mark_param(etype)
        self.function = read_param_text(fn_param)
        self.mark = read_param_text(mk_param)
        self.function_param_name = param_label(fn_param, "BGL_Function")
        self.mark_param_name = param_label(mk_param, "BGL_Type Mark")
        self.slots = self._read_slots()

        seen = set()
        self.fitting_family_names = []
        for slot in self.slots:
            key = slot.family_name.lower()
            if key and key not in seen:
                seen.add(key)
                self.fitting_family_names.append(slot.family_name)

        # filled in by tag_kinds() once the whole set is known
        self.kind = None
        self.kind_label = ""
        self.kind_alias = None
        self.name_alias = None

    @property
    def has_fittings(self):
        if self.slots:
            return True
        return "with fittings" in (self.family_name or "").lower()

    def _read_slots(self):
        slots = []
        for param in self.etype.Parameters:
            try:
                if param.StorageType != StorageType.ElementId:
                    continue
                eid = param.AsElementId()
            except Exception:
                continue
            if eid is None or eid == ElementId.InvalidElementId:
                continue
            elem = self.doc.GetElement(eid)
            if not is_fitting_symbol(elem):
                continue
            try:
                slots.append(FittingSlot(param, elem))
            except Exception:
                continue
        slots.sort(key=lambda s: s.name.lower())
        return slots

    def search_blob(self):
        bits = [self.name, self.family_name, self.function, self.mark,
                self.kind_label]
        for slot in self.slots:
            bits.append(slot.name)
            bits.append(slot.family_name)
            bits.append(slot.type_name)
        return " ".join(bits).lower()


def collect_system_types(doc, cls, kinds):
    """Every 'with fittings' system type of a class, tagged with its kind.

    A type counts as "with fittings" if it actually has fitting types assigned
    to it - which is the real test - or if its family name says so. That is
    more reliable than string-matching the family name alone, and it copes with
    models that name their containment families their own way.
    """
    found = []
    for etype in FilteredElementCollector(doc).OfClass(cls).ToElements():
        info = SystemTypeInfo(doc, etype)
        if info.has_fittings:
            found.append(info)
    found.sort(key=lambda s: s.name.lower())
    tag_kinds(found, kinds)
    return found


def tag_kinds(infos, kinds):
    for info in infos:
        kind, alias, name_alias = assign_kind(info, kinds)
        info.kind = kind
        info.kind_label = kind.label if kind is not None else ""
        info.kind_alias = alias
        info.name_alias = name_alias


def kinds_present(infos, kinds):
    """The kinds that actually have types behind them, in declared order."""
    counts = {}
    for info in infos:
        if info.kind is not None:
            counts[info.kind.label] = counts.get(info.kind.label, 0) + 1
    ordered = [k for k in kinds if counts.get(k.label)]
    unassigned = len([i for i in infos if i.kind is None])
    return ordered, counts, unassigned


def types_for_kind(infos, kind):
    if kind is None:
        return list(infos)
    return [i for i in infos if i.kind is not None and i.kind.label == kind.label]


def existing_system_type_names(doc, cls):
    names = set()
    for etype in FilteredElementCollector(doc).OfClass(cls).ToElements():
        names.add(get_name(etype))
    return names


def family_type_map(doc, family):
    """{type name: FamilySymbol} for one family."""
    out = {}
    try:
        for sid in family.GetFamilySymbolIds():
            sym = doc.GetElement(sid)
            if sym is not None:
                out[get_name(sym)] = sym
    except Exception:
        pass
    return out


# ===========================================================================
# the plan - what would be created, used for both preview and execution
# ===========================================================================

class PlanItem(object):
    def __init__(self, slot, new_type_name, existing_symbol):
        self.slot = slot
        self.new_type_name = new_type_name
        self.existing_symbol = existing_symbol   # not None -> reuse, don't duplicate

    @property
    def reused(self):
        return self.existing_symbol is not None


class Plan(object):
    def __init__(self):
        self.source = None
        self.new_type_name = ""
        self.suggested_type_name = ""
        self.function = ""
        self.mark = ""
        self.params_on_fittings = True
        self.items = []
        self.errors = []
        self.notes = []


def suggest_type_name(source, auto_depth, new_name):
    """The type name the naming rule produces, before any user override.

    Three cases:
      the kind token is in the type name  -> cut there and append
        BGL_Ladder_LV_SubMain  ->  BGL_Ladder_ELV
      the kind was only identifiable from the family naming -> graft the kind
      token onto the shared stem, so the new type reads like the rest
        BGL_LV_SubMain (Trunking families)  ->  BGL_TrunkingTray_ELV
      no kind at all -> shared stem plus the next token
    """
    if source is None or not new_name:
        return ""
    if source.name_alias:
        prefix, sep = prefix_and_sep(source.name, source.name_alias, auto_depth)
        return prefix + sep + new_name
    if source.kind_alias:
        stem, sep = shared_stem(source.name, auto_depth)
        if stem:
            return stem + sep + source.kind_alias + sep + new_name
        return source.kind_alias + "_" + new_name
    prefix, sep = prefix_and_sep(source.name, None, auto_depth)
    return prefix + sep + new_name


def build_plan(doc, cls, source, auto_depth, new_name,
               function_value, mark_value, scheme, params_on_fittings,
               existing_names=None, full_name_override=None):
    if existing_names is None:
        existing_names = existing_system_type_names(doc, cls)
    plan = Plan()
    plan.source = source
    plan.function = function_value
    plan.mark = mark_value
    plan.params_on_fittings = params_on_fittings

    new_name = (new_name or "").strip()
    if not new_name:
        plan.errors.append("Enter a name for the new service type.")
        return plan
    if re.search(r"[\\:{}\[\]|;<>?`~]", new_name):
        plan.errors.append("The name contains a character Revit will not accept.")
        return plan
    if source is None:
        plan.errors.append("No source type available for this kind.")
        return plan

    prefix, sep = prefix_and_sep(source.name, source.name_alias, auto_depth)
    plan.suggested_type_name = suggest_type_name(source, auto_depth, new_name)

    override = (full_name_override or "").strip()
    plan.new_type_name = override if override else plan.suggested_type_name

    if re.search(r"[\\:{}\[\]|;<>?`~]", plan.new_type_name):
        plan.errors.append(
            "The full type name contains a character Revit will not accept.")
        return plan

    if plan.new_type_name in existing_names:
        plan.errors.append(
            'A type called "{0}" already exists.'.format(plan.new_type_name))

    old_token = service_token(source.name, prefix, sep)

    seen_symbols = {}
    for slot in source.slots:
        key = eid_value(slot.symbol_id)
        if key in seen_symbols:
            continue
        seen_symbols[key] = True

        if scheme == "name":
            target = new_name
        elif scheme == "swap":
            swapped = loose_replace(slot.type_name, old_token, new_name)
            target = swapped if swapped else new_name
        else:
            target = plan.new_type_name

        existing = family_type_map(doc, slot.family)
        clash = existing.get(target)
        if clash is not None and same_id(clash.Id, slot.symbol_id):
            plan.errors.append(
                'Fitting "{0}" would be renamed onto itself in family "{1}".'
                .format(target, slot.family_name))
            clash = None
        plan.items.append(PlanItem(slot, target, clash))

    if not plan.items:
        plan.errors.append(
            "This type has no fitting types assigned, so there is nothing to "
            "duplicate alongside it.")

    reused = [i for i in plan.items if i.reused]
    if reused:
        plan.notes.append(
            "{0} fitting type(s) of that name already exist and will be "
            "reused rather than duplicated.".format(len(reused)))

    return plan


# ===========================================================================
# execution
# ===========================================================================

def execute_plan(doc, plan):
    """Run the plan inside one transaction. Returns (ok, log_lines)."""
    log = []
    trans = Transaction(doc, "RevoBIM: Create Containment System")
    trans.Start()
    try:
        new_type = plan.source.etype.Duplicate(plan.new_type_name)
        log.append("System type")
        log.append("    {0}".format(plan.source.name))
        log.append("      -> {0}".format(get_name(new_type)))

        if not write_param_text(find_function_param(new_type), plan.function):
            log.append("      ! BGL_Function could not be written "
                       "(parameter missing or read-only)")
        if not write_param_text(find_mark_param(new_type), plan.mark):
            log.append("      ! Type Mark could not be written")

        log.append("")
        log.append("Fittings")

        created = 0
        reused = 0
        symbol_by_source = {}

        for item in plan.items:
            slot = item.slot
            key = eid_value(slot.symbol_id)

            if key in symbol_by_source:
                new_symbol = symbol_by_source[key]
            elif item.reused:
                new_symbol = item.existing_symbol
                symbol_by_source[key] = new_symbol
                reused += 1
                log.append("    {0}".format(slot.name))
                log.append("      = {0} : {1}   (existing type reused)"
                           .format(slot.family_name, item.new_type_name))
            else:
                new_symbol = slot.symbol.Duplicate(item.new_type_name)
                symbol_by_source[key] = new_symbol
                created += 1
                log.append("    {0}".format(slot.name))
                log.append("      {0} : {1}".format(slot.family_name,
                                                    slot.type_name))
                log.append("        -> {0} : {1}".format(
                    slot.family_name, get_name(new_symbol)))
                if plan.params_on_fittings:
                    ok_fn = write_param_text(find_function_param(new_symbol),
                                             plan.function)
                    ok_mk = write_param_text(find_mark_param(new_symbol),
                                             plan.mark)
                    if not ok_fn:
                        log.append("        ! BGL_Function not written")
                    if not ok_mk:
                        log.append("        ! Type Mark not written")

            target_param = find_param_like(new_type, slot.definition, slot.name)
            if target_param is None or target_param.IsReadOnly:
                log.append("        ! could not assign this fitting back onto "
                           "the new system type")
            else:
                target_param.Set(new_symbol.Id)

        for symbol in symbol_by_source.values():
            try:
                if not symbol.IsActive:
                    symbol.Activate()
            except Exception:
                pass

        doc.Regenerate()
        trans.Commit()

        log.append("")
        log.append("{0} fitting type(s) created, {1} reused, all assigned to "
                   "{2}.".format(created, reused, plan.new_type_name))
        return True, log

    except Exception as err:
        if trans.HasStarted():
            trans.RollBack()
        return False, ["Nothing was created - the whole operation was rolled "
                       "back.", "", str(err)]


# ===========================================================================
# editing an existing system
# ===========================================================================

class RenameItem(object):
    def __init__(self, element, slot_name, old_name, new_name, note=""):
        self.element = element
        self.slot_name = slot_name       # "System type" or the fitting slot
        self.old_name = old_name
        self.new_name = new_name
        self.note = note

    @property
    def changes(self):
        return bool(self.new_name) and self.new_name != self.old_name


class EditPlan(object):
    def __init__(self):
        self.info = None
        self.prefix = ""
        self.sep = "_"
        self.old_token = ""
        self.new_token = ""
        self.new_full_name = ""
        self.function = ""
        self.mark = ""
        self.function_param_name = ""
        self.mark_param_name = ""
        self.rename_fittings = True
        self.params_on_fittings = True
        self.renames = []
        self.param_targets = []          # (label, element)
        self.errors = []
        self.notes = []

    @property
    def renaming(self):
        return [r for r in self.renames if r.changes]


def unique_in_family(doc, family, name, keep_id):
    """True if `name` is free within `family`, ignoring the element itself."""
    for other_name, symbol in family_type_map(doc, family).items():
        if other_name != name:
            continue
        try:
            if same_id(symbol.Id, keep_id):
                continue
        except Exception:
            pass
        return False
    return True


def edit_split(info, auto_depth):
    """Where the fixed prefix ends and the editable service name begins.

    With a kind token in the type name, cut just after it. Without one there is
    nothing to anchor to, so cut after the prefix every type in the class
    shares - the whole rest of the name is then the service name.
    """
    if info.name_alias:
        return prefix_and_sep(info.name, info.name_alias, auto_depth)
    return shared_stem(info.name, auto_depth)


def build_edit_plan(doc, cls, info, auto_depth, new_token, function_value,
                    mark_value, rename_fittings, params_on_fittings,
                    existing_names=None):
    """Work out what renaming an existing system's service name would do."""
    plan = EditPlan()
    plan.info = info
    plan.function = function_value
    plan.mark = mark_value
    plan.rename_fittings = rename_fittings
    plan.params_on_fittings = params_on_fittings

    if info is None:
        plan.errors.append("Select a system type first.")
        return plan

    plan.function_param_name = param_label(find_function_param(info.etype),
                                           "BGL_Function (not on this type)")
    plan.mark_param_name = param_label(find_mark_param(info.etype),
                                       "BGL_Type Mark (not on this type)")

    prefix, sep = edit_split(info, auto_depth)
    plan.prefix, plan.sep = prefix, sep
    plan.old_token = service_token(info.name, prefix, sep)

    new_token = (new_token or "").strip()
    plan.new_token = new_token
    if not new_token:
        plan.errors.append("The type name cannot be empty.")
        return plan
    if re.search(r"[\\:{}\[\]|;<>?`~]", new_token):
        plan.errors.append("The name contains a character Revit will not accept.")
        return plan

    plan.new_full_name = (prefix + sep + new_token) if prefix else new_token

    if existing_names is None:
        existing_names = existing_system_type_names(doc, cls)
    if plan.new_full_name != info.name and plan.new_full_name in existing_names:
        plan.errors.append(
            'A type called "{0}" already exists.'.format(plan.new_full_name))

    plan.renames.append(RenameItem(info.etype, "System type", info.name,
                                   plan.new_full_name))
    plan.param_targets.append(("System type  " + info.name, info.etype))

    seen = {}
    for slot in info.slots:
        key = eid_value(slot.symbol_id)
        if key in seen:
            continue
        seen[key] = True

        target = None
        note = ""
        if norm(slot.type_name) == norm(info.name):
            target = plan.new_full_name
        else:
            swapped = loose_replace(slot.type_name, plan.old_token, new_token)
            if swapped:
                target = swapped
            else:
                note = ("does not carry the service name - left as it is")

        if target and target != slot.type_name:
            if not unique_in_family(doc, slot.family, target, slot.symbol_id):
                note = ('"{0}" already exists in this family - left as it is'
                        .format(target))
                target = None

        plan.renames.append(RenameItem(slot.symbol, slot.name, slot.type_name,
                                       target, note))
        plan.param_targets.append(
            ("{0}  {1} : {2}".format(slot.name, slot.family_name,
                                     slot.type_name), slot.symbol))

    if not rename_fittings:
        plan.renames = plan.renames[:1]
    if not params_on_fittings:
        plan.param_targets = plan.param_targets[:1]

    skipped = [r for r in plan.renames if r.note]
    if skipped:
        plan.notes.append(
            "{0} fitting type(s) will not be renamed - see the list above."
            .format(len(skipped)))

    return plan


def execute_edit(doc, plan):
    """Apply an edit plan inside one transaction. Returns (ok, log_lines)."""
    log = []
    trans = Transaction(doc, "RevoBIM: Edit Containment System")
    trans.Start()
    try:
        renamed = 0
        log.append("Renamed")
        for item in plan.renames:
            if not item.changes:
                if item.note:
                    log.append("    {0}".format(item.slot_name))
                    log.append("      {0}   ! {1}".format(item.old_name,
                                                          item.note))
                continue
            if set_element_name(item.element, item.new_name):
                renamed += 1
                log.append("    {0}".format(item.slot_name))
                log.append("      {0}".format(item.old_name))
                log.append("        -> {0}".format(item.new_name))
            else:
                log.append("    {0}".format(item.slot_name))
                log.append("      ! could not rename {0}".format(item.old_name))
        if renamed == 0:
            log.append("    (nothing to rename)")

        log.append("")
        log.append("Parameters")
        log.append("    {0} = {1}".format(plan.function_param_name,
                                          plan.function))
        log.append("    {0} = {1}".format(plan.mark_param_name, plan.mark))
        log.append("")

        written = 0
        for label, element in plan.param_targets:
            problems = []
            notes = []

            fn_param = find_function_param(element)
            if not write_param_text(fn_param, plan.function):
                problems.append("BGL_Function")
            elif param_label(fn_param) != plan.function_param_name:
                notes.append("function written to " + param_label(fn_param))

            mk_param = find_mark_param(element)
            if not write_param_text(mk_param, plan.mark):
                problems.append("type mark")
            elif param_label(mk_param) != plan.mark_param_name:
                # e.g. the fittings carry Revit's Type Mark, not BGL_Type Mark
                notes.append("mark written to " + param_label(mk_param))

            if problems or notes:
                log.append("    {0}".format(label))
                for note in notes:
                    log.append("      -  {0}".format(note))
                if problems:
                    log.append("      !  could not write {0}".format(
                        " and ".join(problems)))
            if not problems:
                written += 1

        log.append("    {0} of {1} element(s) took both values.".format(
            written, len(plan.param_targets)))

        doc.Regenerate()
        trans.Commit()

        log.append("")
        log.append("{0} type(s) renamed, {1} type(s) updated.".format(
            renamed, len(plan.param_targets)))
        return True, log

    except Exception as err:
        if trans.HasStarted():
            trans.RollBack()
        return False, ["Nothing was changed - the whole operation was rolled "
                       "back.", "", str(err)]


# ===========================================================================
# UI - shared bits
# ===========================================================================

def init_window(window, layout):
    """Load a layout, keeping Esc for the drawer.

    pyRevit's own Esc handler closes the window, and it is hooked before
    anything the tool can add, so while the window is parked Esc would close
    it instead of bringing it back. Ask pyRevit not to hook it; the drawer
    closes on Esc itself whenever the window is open. An older pyRevit without
    the keyword keeps its own handler.
    """
    path = script.get_bundle_file(layout)
    try:
        forms.WPFWindow.__init__(window, path, handle_esc=False)
    except TypeError:
        forms.WPFWindow.__init__(window, path)


def load_icon(image_control):
    """Put the tool icon in a window header.

    Loaded from a byte stream rather than a Uri: System.Uri moved assemblies
    in .NET 8, so "from System import Uri" fails outright on Revit 2025 and
    later. Bytes work the same on every release, and OnLoad caching means the
    stream can be released immediately. Purely decorative, so any failure is
    swallowed rather than taking the tool down with it.
    """
    if image_control is None:
        return
    try:
        if not os.path.isfile(ICON_PATH):
            return

        from System.IO import File, MemoryStream

        stream = MemoryStream(File.ReadAllBytes(ICON_PATH))
        try:
            bitmap = BitmapImage()
            bitmap.BeginInit()
            bitmap.CacheOption = BitmapCacheOption.OnLoad
            bitmap.StreamSource = stream
            bitmap.EndInit()
            try:
                bitmap.Freeze()
            except Exception:
                pass
            image_control.Source = bitmap
        finally:
            stream.Close()
    except Exception:
        pass


def set_owner(child, parent):
    """Parent a child window, tolerating pyRevit's own interop owner, and
    link the drawers so the two windows go down and come back together."""
    try:
        child.Owner = parent
    except Exception:
        pass
    try:
        child.drawer.owner = parent.drawer
    except Exception:
        pass


def text_block(text, brush=None, bold=False, size=12, left=0):
    block = TextBlock()
    block.Text = text
    block.Foreground = brush if brush is not None else WHITE
    block.FontSize = size
    block.VerticalAlignment = VerticalAlignment.Center
    if bold:
        block.FontWeight = FontWeights.SemiBold
    if left:
        block.Margin = Thickness(left, 0, 0, 0)
    return block


# ===========================================================================
# results window
# ===========================================================================

class ResultsDialog(forms.WPFWindow):
    def __init__(self, title, headline, body, ok=True):
        init_window(self, "ResultsDialog.xaml")
        self.drawer = csc_drawer.attach(self)
        load_icon(self.app_icon)
        self.version_text.Text = "v" + __version__
        self.dialog_title.Text = title
        self.headline.Text = headline
        self.headline.Foreground = GREEN if ok else RED
        self.body.Text = body

    def drag_window(self, sender, args):
        self.drawer.header_down(sender, args)

    def ok_clicked(self, sender, args):
        self.Close()


# ===========================================================================
# create-system dialog
# ===========================================================================

class CreateSystemDialog(forms.WPFWindow):
    """Collects the new service definition and previews the result."""

    def __init__(self, doc, cls, label, kinds, all_types, auto_depth):
        init_window(self, "CreateSystemDialog.xaml")
        self.drawer = csc_drawer.attach(self)
        self.doc = doc
        self.cls = cls
        self.all_types = all_types
        self.auto_depth = auto_depth
        self.existing_names = existing_system_type_names(doc, cls)
        self.plan = None
        self.created = False
        self._loading = True
        self._function_touched = False
        self._mark_touched = False
        self._fullname_touched = False

        load_icon(self.app_icon)
        self.version_text.Text = "v" + __version__
        self.dialog_title.Text = "New {0} System".format(label)

        present, counts, unassigned = kinds_present(all_types, kinds)
        for kind in present:
            item = ComboBoxItem()
            item.Content = "{0}   ({1})".format(kind.label,
                                                counts.get(kind.label, 0))
            item.Tag = kind
            self.cmb_kind.Items.Add(item)
        item = ComboBoxItem()
        if unassigned:
            item.Content = "{0}   ({1}, {2} unmatched)".format(
                UNFILTERED, len(all_types), unassigned)
        else:
            item.Content = "{0}   ({1})".format(UNFILTERED, len(all_types))
        item.Tag = None
        self.cmb_kind.Items.Add(item)

        for caption, code in FIT_SCHEMES:
            item = ComboBoxItem()
            item.Content = caption
            item.Tag = code
            self.cmb_fitname.Items.Add(item)
        self.cmb_fitname.SelectedIndex = 0

        self.cmb_kind.SelectedIndex = 0
        self._loading = False
        self.reload_sources()

    # -- helpers ------------------------------------------------------------

    def selected_kind(self):
        item = self.cmb_kind.SelectedItem
        return item.Tag if item is not None else None

    def selected_scheme(self):
        item = self.cmb_fitname.SelectedItem
        return item.Tag if item is not None else "full"

    def selected_source(self):
        item = self.cmb_source.SelectedItem
        return item.Tag if item is not None else None

    def reload_sources(self):
        if self._loading:
            return
        self._loading = True
        self.cmb_source.Items.Clear()
        matches = types_for_kind(self.all_types, self.selected_kind())
        for info in matches:
            item = ComboBoxItem()
            if info.family_name:
                item.Content = "{0}      [{1}]   ({2} fittings)".format(
                    info.name, info.family_name, len(info.slots))
            else:
                item.Content = "{0}   ({1} fittings)".format(info.name,
                                                             len(info.slots))
            item.Tag = info
            self.cmb_source.Items.Add(item)
        if matches:
            self.cmb_source.SelectedIndex = 0
        self._loading = False
        self.refresh_preview()

    # -- events -------------------------------------------------------------

    def drag_window(self, sender, args):
        self.drawer.header_down(sender, args)

    def kind_changed(self, sender, args):
        self.reload_sources()

    def source_changed(self, sender, args):
        self.refresh_preview()

    def source_changed_evt(self, sender, args):
        self.refresh_preview()

    def name_changed(self, sender, args):
        if self._loading:
            return
        value = self.txt_name.Text
        # mirror the name into the two parameter boxes until the user edits them
        if not self._function_touched:
            self._loading = True
            self.txt_function.Text = value
            self._loading = False
        if not self._mark_touched:
            self._loading = True
            self.txt_mark.Text = value
            self._loading = False
        self.refresh_preview()

    def mirror_edited(self, sender, args):
        if self._loading:
            return
        if sender is self.txt_function:
            self._function_touched = True
        elif sender is self.txt_mark:
            self._mark_touched = True
        self.refresh_preview()

    def fullname_edited(self, sender, args):
        if self._loading:
            return
        self._fullname_touched = bool(self.txt_fullname.Text.strip())
        self.refresh_preview()

    def reset_fullname(self, sender, args):
        self._fullname_touched = False
        self.refresh_preview()

    # -- preview ------------------------------------------------------------

    def refresh_preview(self):
        if self._loading:
            return
        source = self.selected_source()
        override = self.txt_fullname.Text if self._fullname_touched else None
        plan = build_plan(self.doc, self.cls, source,
                          self.auto_depth, self.txt_name.Text,
                          self.txt_function.Text, self.txt_mark.Text,
                          self.selected_scheme(),
                          bool(self.chk_params_on_fittings.IsChecked),
                          self.existing_names, override)
        self.plan = plan

        if not self._fullname_touched:
            self._loading = True
            self.txt_fullname.Text = plan.new_type_name
            self._loading = False

        if source is None:
            self.preview_head.Text = ""
            self.preview_body.Text = "No source type found for this kind."
        else:
            head = "{0}\n   ->  {1}".format(source.name,
                                            plan.new_type_name or "...")
            self.preview_head.Text = head
            lines = []
            lines.append("Source family: {0}".format(
                source.family_name or "(none)"))
            if source.kind_label:
                if source.name_alias:
                    lines.append("Kind         : {0}   (from the type name)"
                                 .format(source.kind_label))
                else:
                    lines.append("Kind         : {0}   (from the family "
                                 "naming - check the name above)"
                                 .format(source.kind_label))
            lines.append("")
            lines.append("{0} = {1}".format(source.function_param_name,
                                            self.txt_function.Text))
            lines.append("{0} = {1}".format(source.mark_param_name,
                                            self.txt_mark.Text))
            lines.append("")
            lines.append("{0} fitting type(s) will be created:"
                         .format(len(plan.items)))
            for item in plan.items:
                lines.append("   {0}".format(item.slot.name))
                lines.append("      {0} : {1}".format(item.slot.family_name,
                                                      item.slot.type_name))
                arrow = "      =  " if item.reused else "      -> "
                suffix = "   (existing, reused)" if item.reused else ""
                lines.append("{0}{1} : {2}{3}".format(
                    arrow, item.slot.family_name, item.new_type_name, suffix))
            for note in plan.notes:
                lines.append("")
                lines.append(note)
            self.preview_body.Text = "\n".join(lines)

        if plan.errors:
            self.warn_text.Text = plan.errors[0]
            self.btn_create.IsEnabled = False
        else:
            self.warn_text.Text = ""
            self.btn_create.IsEnabled = bool(plan.items)

    # -- actions ------------------------------------------------------------

    def cancel_clicked(self, sender, args):
        self.created = False
        self.Close()

    def create_clicked(self, sender, args):
        self.refresh_preview()
        if self.plan is None or self.plan.errors:
            return
        ok, log = execute_plan(self.doc, self.plan)
        self.created = ok
        self.summary = "\n".join(log)
        self.show_summary = bool(self.chk_select_after.IsChecked)
        self.ok = ok
        self.Close()


# ===========================================================================
# edit-system dialog
# ===========================================================================

class EditSystemDialog(forms.WPFWindow):
    """Edits an existing system's service name and its two parameters,
    across the system type and every fitting type in its routing preferences.
    """

    def __init__(self, doc, cls, info, auto_depth):
        init_window(self, "EditSystemDialog.xaml")
        self.drawer = csc_drawer.attach(self)
        self.doc = doc
        self.cls = cls
        self.info = info
        self.auto_depth = auto_depth
        self.existing_names = existing_system_type_names(doc, cls)
        self.plan = None
        self.applied = False
        self._loading = True

        load_icon(self.app_icon)
        self.version_text.Text = "v" + __version__

        prefix, sep = edit_split(info, auto_depth)
        self.prefix_text.Text = (prefix + sep) if prefix else "(whole name)"

        self.subject_name.Text = info.name
        bits = []
        if info.kind_label:
            bits.append(info.kind_label)
        if info.family_name:
            bits.append(info.family_name)
        bits.append("{0} fitting type(s) in the routing preferences".format(
            len(info.slots)))
        self.subject_meta.Text = "   |   ".join(bits)

        self.txt_token.Text = service_token(info.name, prefix, sep)
        self.txt_function.Text = info.function
        self.txt_mark.Text = info.mark

        self._loading = False
        self.refresh_preview()

    # -- events -------------------------------------------------------------

    def drag_window(self, sender, args):
        self.drawer.header_down(sender, args)

    def field_changed(self, sender, args):
        self.refresh_preview()

    def cancel_clicked(self, sender, args):
        self.applied = False
        self.Close()

    # -- preview ------------------------------------------------------------

    def refresh_preview(self):
        if self._loading:
            return
        plan = build_edit_plan(
            self.doc, self.cls, self.info, self.auto_depth,
            self.txt_token.Text, self.txt_function.Text, self.txt_mark.Text,
            bool(self.chk_rename_fittings.IsChecked),
            bool(self.chk_params_on_fittings.IsChecked),
            self.existing_names)
        self.plan = plan

        self.preview_head.Text = "{0}\n   ->  {1}".format(
            self.info.name, plan.new_full_name or "...")

        lines = []
        lines.append("{0} = {1}".format(plan.function_param_name,
                                        self.txt_function.Text))
        lines.append("{0} = {1}".format(plan.mark_param_name,
                                        self.txt_mark.Text))
        lines.append("")

        changing = plan.renaming
        if changing:
            lines.append("{0} type name(s) will change:".format(len(changing)))
        else:
            lines.append("No type names will change.")
        for item in plan.renames:
            lines.append("   {0}".format(item.slot_name))
            lines.append("      {0}".format(item.old_name))
            if item.note:
                lines.append("      !  {0}".format(item.note))
            elif item.changes:
                lines.append("      -> {0}".format(item.new_name))
            else:
                lines.append("      =  unchanged")

        lines.append("")
        lines.append("Parameters will be written to {0} element(s)."
                     .format(len(plan.param_targets)))
        for note in plan.notes:
            lines.append("")
            lines.append(note)
        self.preview_body.Text = "\n".join(lines)

        if plan.errors:
            self.warn_text.Text = plan.errors[0]
            self.btn_apply.IsEnabled = False
        else:
            self.warn_text.Text = ""
            self.btn_apply.IsEnabled = True

    # -- actions ------------------------------------------------------------

    def apply_clicked(self, sender, args):
        self.refresh_preview()
        if self.plan is None or self.plan.errors:
            return
        ok, log = execute_edit(self.doc, self.plan)
        self.applied = ok
        self.ok = ok
        self.summary = "\n".join(log)
        self.Close()


# ===========================================================================
# main window
# ===========================================================================

class ContainmentSystemCreator(forms.WPFWindow):

    def __init__(self):
        init_window(self, "ContainmentSystemCreator.xaml")
        self.drawer = csc_drawer.attach(self)
        load_icon(self.app_icon)
        self.version_text.Text = "v" + __version__
        self.doc = DOC
        self.selection = None        # (info, cls, kinds, auto_depth)
        self._syncing = False
        self.load_model()

    # -- data ---------------------------------------------------------------

    def load_model(self):
        # cable tray kinds are the four the model uses; conduit kinds are
        # whatever the conduit type naming actually contains
        self.tray_kinds = tray_kinds()
        self.tray_types = collect_system_types(self.doc, CableTrayType,
                                               self.tray_kinds)

        provisional = collect_system_types(self.doc, ConduitType, [])
        conduit_tokens, self.conduit_depth = detect_kinds(
            [t.name for t in provisional])
        if not conduit_tokens:
            conduit_tokens = ["Conduit"]
        self.conduit_kinds = [Kind(tok) for tok in conduit_tokens]
        self.conduit_types = provisional
        tag_kinds(self.conduit_types, self.conduit_kinds)

        _, self.tray_depth = detect_kinds([t.name for t in self.tray_types])

        self.fill_tree(self.tray_tree, self.tray_types, self.tray_search.Text)
        self.fill_tree(self.conduit_tree, self.conduit_types,
                       self.conduit_search.Text)

        self.tray_count.Text = "{0} cable tray type(s), {1} fitting assignment(s)".format(
            len(self.tray_types), sum(len(t.slots) for t in self.tray_types))
        self.conduit_count.Text = "{0} conduit type(s), {1} fitting assignment(s)".format(
            len(self.conduit_types),
            sum(len(t.slots) for t in self.conduit_types))

        self.btn_tray_top.IsEnabled = bool(self.tray_types)
        self.btn_tray_bottom.IsEnabled = bool(self.tray_types)
        self.btn_conduit_top.IsEnabled = bool(self.conduit_types)
        self.btn_conduit_bottom.IsEnabled = bool(self.conduit_types)

        self.clear_selection()

    def fill_tree(self, tree, infos, filter_text):
        tree.Items.Clear()
        needle = (filter_text or "").strip().lower()
        shown = 0
        for info in infos:
            if needle and needle not in info.search_blob():
                continue
            shown += 1
            node = TreeViewItem()
            node.Tag = info
            head = StackPanel()
            head.Orientation = Orientation.Horizontal
            head.Children.Add(text_block(info.name, WHITE, True, 12))
            if info.kind_label:
                head.Children.Add(text_block(info.kind_label, GREEN,
                                             False, 11, 14))
            if info.family_name:
                head.Children.Add(text_block("[" + info.family_name + "]",
                                             GREY, False, 11, 14))
            if info.function:
                head.Children.Add(text_block(
                    "{0}: {1}".format(info.function_param_name, info.function),
                    BLUE, False, 11, 14))
            if info.mark:
                head.Children.Add(text_block(
                    "{0}: {1}".format(info.mark_param_name, info.mark),
                    ORANGE, False, 11, 14))
            head.Children.Add(text_block("{0} fittings".format(len(info.slots)),
                                         GREY, False, 11, 14))
            node.Header = head

            for slot in info.slots:
                child = TreeViewItem()
                child.Tag = info          # picking a fitting selects its system
                row = StackPanel()
                row.Orientation = Orientation.Horizontal
                label = text_block(slot.name, GREY, False, 11)
                label.MinWidth = 150
                row.Children.Add(label)
                row.Children.Add(text_block(slot.label(), WHITE, False, 11, 8))
                child.Header = row
                node.Items.Add(child)

            tree.Items.Add(node)
        return shown

    # -- events -------------------------------------------------------------

    def drag_window(self, sender, args):
        self.drawer.header_down(sender, args)

    def close_window(self, sender, args):
        self.Close()

    def tray_search_changed(self, sender, args):
        self.tray_search_hint.Visibility = (
            Visibility.Visible if not self.tray_search.Text
            else Visibility.Collapsed)
        self.fill_tree(self.tray_tree, self.tray_types, self.tray_search.Text)

    def conduit_search_changed(self, sender, args):
        self.conduit_search_hint.Visibility = (
            Visibility.Visible if not self.conduit_search.Text
            else Visibility.Collapsed)
        self.fill_tree(self.conduit_tree, self.conduit_types,
                       self.conduit_search.Text)

    def refresh_clicked(self, sender, args):
        self.load_model()
        self.status_text.Foreground = GREY
        self.status_text.Text = "Reloaded from the model."

    # -- selection ----------------------------------------------------------

    def clear_selection(self):
        self.selection = None
        self.btn_edit.IsEnabled = False
        self.btn_edit.Content = "Edit System Parameters"

    def note_selection(self, tree, other, cls, kinds, depth):
        if self._syncing:
            return
        item = tree.SelectedItem
        info = getattr(item, "Tag", None) if item is not None else None
        if info is None:
            return

        # only one of the two trees holds the selection at a time
        self._syncing = True
        try:
            stale = other.SelectedItem
            if stale is not None:
                try:
                    stale.IsSelected = False
                except Exception:
                    pass
        finally:
            self._syncing = False

        self.selection = (info, cls, kinds, depth)
        self.btn_edit.IsEnabled = True
        self.btn_edit.Content = "Edit System Parameters"
        self.status_text.Foreground = GREY
        self.status_text.Text = 'Selected "{0}"'.format(info.name)

    def tray_selected(self, sender, args):
        self.note_selection(self.tray_tree, self.conduit_tree, CableTrayType,
                            self.tray_kinds, self.tray_depth)

    def conduit_selected(self, sender, args):
        self.note_selection(self.conduit_tree, self.tray_tree, ConduitType,
                            self.conduit_kinds, self.conduit_depth)

    def edit_selected(self, sender, args):
        if not self.selection:
            return
        info, cls, _kinds, depth = self.selection

        dialog = EditSystemDialog(self.doc, cls, info, depth)
        set_owner(dialog, self)
        dialog.ShowDialog()

        if not getattr(dialog, "applied", False):
            summary = getattr(dialog, "summary", None)
            if summary and not getattr(dialog, "ok", True):
                failed = ResultsDialog("Nothing Changed",
                                       "The system could not be updated.",
                                       summary, ok=False)
                set_owner(failed, self)
                failed.ShowDialog()
            return

        name = dialog.plan.new_full_name
        self.load_model()
        self.status_text.Foreground = GREEN
        self.status_text.Text = 'Updated "{0}".'.format(name)

        result = ResultsDialog("System Updated",
                               '"{0}" and its fittings are up to date.'
                               .format(name),
                               getattr(dialog, "summary", ""), ok=True)
        set_owner(result, self)
        result.ShowDialog()

    def create_tray_system(self, sender, args):
        self.run_creator(CableTrayType, "Cable Tray", self.tray_kinds,
                         self.tray_types, self.tray_depth)

    def create_conduit_system(self, sender, args):
        self.run_creator(ConduitType, "Conduit", self.conduit_kinds,
                         self.conduit_types, self.conduit_depth)

    # -- flow ---------------------------------------------------------------

    def run_creator(self, cls, label, kinds, all_types, auto_depth):
        if not all_types:
            self.status_text.Text = (
                "No '{0} with Fittings' types found in this model.".format(label))
            self.status_text.Foreground = RED
            return

        dialog = CreateSystemDialog(self.doc, cls, label, kinds, all_types,
                                    auto_depth)
        set_owner(dialog, self)
        dialog.ShowDialog()

        if not getattr(dialog, "created", False):
            summary = getattr(dialog, "summary", None)
            if summary and not getattr(dialog, "ok", True):
                failed = ResultsDialog("System Not Created",
                                       "The system could not be created.",
                                       summary, ok=False)
                set_owner(failed, self)
                failed.ShowDialog()
            return

        name = dialog.plan.new_type_name
        self.load_model()
        self.status_text.Text = 'Created "{0}".'.format(name)
        self.status_text.Foreground = GREEN

        if getattr(dialog, "show_summary", True):
            result = ResultsDialog(
                "System Created",
                '"{0}" is ready to use.'.format(name),
                getattr(dialog, "summary", ""), ok=True)
            set_owner(result, self)
            result.ShowDialog()


# ===========================================================================
# go
# ===========================================================================

if __name__ == "__main__":
    if DOC is None:
        forms.alert("Open a project before running Containment System Creator.",
                    title="RevoBIM")
    else:
        ContainmentSystemCreator().ShowDialog()
