# -*- coding: utf-8 -*-
"""MEP System Manager - version, settings and every rule that decides a value.

Nothing in here touches clr, System.* or Autodesk.*, so every rule can be run
under plain CPython by bench_logic.py against a table of cases.
"""
import io
import os
import math
import re

__version__ = u"3.9.0"
TOOL_NAME = u"MEP System Manager"
SETTINGS_NAME = u"mep_system_manager.txt"
DEBUG_NAME = u"mep_system_manager_debug.txt"
ERROR_NAME = u"mep_system_manager_last_error.txt"
MODELESS_FLAG = u"mep_system_manager_modeless.flag"
# the tool was Pipe System Manager up to 1.6.0; its settings are carried over
LEGACY_SETTINGS_NAME = u"pipe_system_manager.txt"

MM_PER_FOOT = 304.8
UNASSIGNED = u"Unassigned"

# ============================================================
# settings
# ============================================================

SETTINGS_VERSION = 4

# ============================================================
# the three disciplines, one tab each
# ============================================================

DOMAINS = (u"pipe", u"duct", u"cont", u"ws")

DOMAIN_INFO = {
    u"pipe": {
        u"tab": u"Pipe System Manager",
        u"noun": (u"pipe", u"pipes"),
        u"system_word": u"System No",
        u"type_word": u"Pipe Type",
        u"export": u"Pipe systems",
        u"group_options": ((u"system_type", u"System Type"),
                           (u"classification", u"System Classification"),
                           (u"param", u"A parameter...")),
        u"check_labels": {},
        u"checks": (u"standards", u"sizes", u"open_ends", u"mismatch", u"no_system"),
        u"swap_source": u"the new type's routing preferences",
        u"isolate": (u"OST_PipeCurves", u"OST_PipeFitting", u"OST_PipeAccessory",
                     u"OST_FlexPipeCurves", u"OST_PipeInsulations"),
    },
    u"duct": {
        u"tab": u"Duct System Manager",
        u"noun": (u"duct", u"ducts"),
        u"system_word": u"System No",
        u"type_word": u"Duct Type",
        u"export": u"Duct systems",
        u"group_options": ((u"system_type", u"System Type"),
                           (u"classification", u"System Classification"),
                           (u"param", u"A parameter...")),
        u"check_labels": {},
        u"checks": (u"standards", u"sizes", u"open_ends", u"mismatch", u"no_system"),
        u"swap_source": u"the new type's routing preferences",
        u"isolate": (u"OST_DuctCurves", u"OST_DuctFitting", u"OST_DuctAccessory",
                     u"OST_FlexDuctCurves", u"OST_DuctInsulations", u"OST_DuctLinings"),
    },
    u"cont": {
        u"tab": u"Containment System Manager",
        u"noun": (u"tray or conduit", u"trays and conduits"),
        u"system_word": u"Run",
        u"type_word": u"Type",
        u"export": u"Containment",
        # the service type is where containment is grouped from: Revit's own
        # Service Type parameter, or a parameter of the user's choosing
        u"group_options": ((u"system_type", u"Service Type parameter"),
                           (u"param", u"Custom parameter...")),
        u"check_labels": {u"mismatch": u"Fitting on another service",
                          u"no_system": u"No service type"},
        # no routing preference sizes to check a tray or conduit against
        u"checks": (u"standards", u"open_ends", u"mismatch", u"no_system"),
        u"swap_source": u"the matching fitting slot on the new type",
        u"isolate": (u"OST_CableTray", u"OST_Conduit", u"OST_CableTrayFitting",
                     u"OST_ConduitFitting"),
    },
    # not a discipline: every system of all three, by system type, and the
    # worksets their elements sit on
    u"ws": {
        u"tab": u"Workset Assigner",
        u"noun": (u"element", u"elements"),
        u"system_word": u"System",
        u"type_word": u"System Type",
        u"export": u"Worksets",
        u"group_options": (),
        u"check_labels": {},
        u"checks": (),
        u"swap_source": u"",
        u"isolate": (),
    },
}

# the discipline tabs; the workset tab is not one of them
DISCIPLINES = (u"pipe", u"duct", u"cont")


def domain_info(domain):
    return DOMAIN_INFO.get(domain) or DOMAIN_INFO[u"pipe"]


def noun(domain, count):
    single, plural = domain_info(domain)[u"noun"]
    return single if count == 1 else plural


# settings every tab shares
SHARED_DEFAULTS = {
    u"settings_version": u"4",
    u"theme": u"auto",                 # auto | dark | light
    u"active_tab": u"pipe",
    u"isolate_what": u"fittings",      # pipes | fittings | systems
    u"isolate_zoom": u"1",
    u"isolate_section_box": u"0",
    u"section_margin_mm": u"300",
    u"isolate_select": u"0",
    u"last_view": u"",
    u"show_results": u"issues",        # issues | always | never
    u"debug": u"0",                    # the Debug tick, bottom left
    u"highlighted": u"",               # view id:element ids this tool coloured red
    u"isolated_view": u"",             # the last view this tool isolated in
    u"lookup_linked": u"0",            # Pick System: look inside linked models
    u"fitting_mode": u"size_second",   # size_second | together | reapply | after
    u"accessory_params": u"BGL_Diameter",   # instance size parameters to set
    u"allow_disconnect": u"0",         # let Revit disconnect a family it cannot keep
    u"resize_whole_run": u"1",
    u"resize_mode": u"partial",        # partial | run
    u"resize_fittings": u"1",          # size the fittings joined to resized trays too
    u"ws_grouping": u"type",           # Workset Assigner: type | discipline
    u"ws_mixed_only": u"0",            # Workset Assigner: only systems on 2+ worksets
    u"window_mode": u"modeless",       # modeless | modal
    u"export_dir": u"",
}

# settings each tab keeps for itself, stored as <domain>.<key>
DOMAIN_DEFAULTS = {
    u"group_by": u"system_type",       # system_type | classification | param
    u"group_param": u"",
    u"system_from": u"",               # blank = the system's own name (containment: its run)
    u"split_system": u"1",
    u"split_type": u"1",
    u"split_size": u"1",
    u"scope": u"project",              # project | view
    u"swap_fittings": u"1",
    u"keep_size": u"1",
    u"retain": u"Comments|Mark",
    u"expanded": u"",
    u"checks_on": u"1",                # the toolbar switch: all checks on or off
    u"standards": u"",                 # Service>>TypeA|TypeB;;Service>>...
    u"check_standards": u"1",
    u"check_sizes": u"1",
    u"check_open_ends": u"1",
    u"check_mismatch": u"1",
    u"check_no_system": u"1",
    u"issues_only": u"0",
    u"multi_type_only": u"0",          # containment: only services using 2+ types
    u"nest_systems": u"0",             # each System No its own fold in its service type
}

# where a tab's default differs from the rest
DOMAIN_OVERRIDES = {
    u"duct": {u"nest_systems": u"1"},
    u"pipe": {u"nest_systems": u"1"},
}


def full_key(domain, key):
    return u"{0}.{1}".format(domain, key)


DEFAULTS = dict(SHARED_DEFAULTS)
for _domain in DOMAINS:
    for _key, _value in DOMAIN_DEFAULTS.items():
        DEFAULTS[full_key(_domain, _key)] = DOMAIN_OVERRIDES.get(_domain, {}).get(_key, _value)


class DomainView(object):
    """One tab's settings: a per-discipline key (group_by) reads and writes
    <domain>.group_by in the one settings dict; a shared key (theme) reads
    the dict itself. Every rule that takes settings works through one of
    these unchanged, and save_settings writes the dict underneath."""

    def __init__(self, base, domain):
        self.base = base
        self.domain = domain

    def _key(self, key):
        return full_key(self.domain, key) if key in DOMAIN_DEFAULTS else key

    def get(self, key, default=None):
        return self.base.get(self._key(key), default)

    def __getitem__(self, key):
        return self.base[self._key(key)]

    def __setitem__(self, key, value):
        self.base[self._key(key)] = value

    def __contains__(self, key):
        return self._key(key) in self.base

    def copy(self):
        return DomainView(dict(self.base), self.domain)

    def resolved(self):
        """A plain dict of what this tab sees, for the jobs that run in Revit."""
        out = {}
        for key in SHARED_DEFAULTS:
            out[key] = self.base.get(key, SHARED_DEFAULTS[key])
        for key in DOMAIN_DEFAULTS:
            out[key] = self.base.get(full_key(self.domain, key),
                                     DEFAULTS.get(full_key(self.domain, key), DOMAIN_DEFAULTS[key]))
        out[u"domain"] = self.domain
        return out


MIGRATIONS = {
    # version: keys reset to their default when a file older than it is read
    3: [u"debug"],      # was on by default; now the Debug tick, off unless ticked
    4: [u"fitting_mode"],   # a saved "together" kept the old order, so 3.7.0's
                            # two passes never ran on a settings file that had one
}


def settings_dir():
    base = os.environ.get(u"APPDATA") or os.path.expanduser(u"~")
    return os.path.join(base, u"RevoBIM")


def settings_path():
    return os.path.join(settings_dir(), SETTINGS_NAME)


def parse_settings(text, legacy=False):
    """key=value per line, split on the first = only. A damaged line is
    skipped; unknown keys are ignored; anything missing takes its default.
    legacy: a Pipe System Manager file, whose per-discipline keys had no
    prefix - they become the Pipe tab's."""
    values = dict(DEFAULTS)
    found = {}
    for raw in (text or u"").splitlines():
        line = raw.strip()
        if not line or line.startswith(u"#") or u"=" not in line:
            continue
        key, value = line.split(u"=", 1)
        key = key.strip()
        if legacy and key in DOMAIN_DEFAULTS:
            key = full_key(u"pipe", key)
        if key in DEFAULTS:
            found[key] = value.strip()
    try:
        version = int(found.get(u"settings_version", u"0"))
    except Exception:
        version = 0
    for key, value in found.items():
        values[key] = value
    for mig_version in sorted(MIGRATIONS):
        if version < mig_version:
            for key in MIGRATIONS[mig_version]:
                values[key] = DEFAULTS[key]
    values[u"settings_version"] = u"{0}".format(SETTINGS_VERSION)
    return values


def format_settings(values):
    if isinstance(values, DomainView):
        values = values.base
    lines = [u"# RevoBIM {0} settings".format(TOOL_NAME)]
    for key in sorted(DEFAULTS):
        value = values.get(key, DEFAULTS[key])
        value = u"{0}".format(value).replace(u"\r", u" ").replace(u"\n", u" ")
        lines.append(u"{0}={1}".format(key, value))
    return u"\n".join(lines) + u"\n"


def load_settings(path=None, legacy_path=None):
    """The settings file; failing that, the Pipe System Manager file it
    replaced, carried over; failing that, the defaults."""
    if path is None:
        path = settings_path()
        legacy_path = legacy_path or os.path.join(settings_dir(), LEGACY_SETTINGS_NAME)
    try:
        if os.path.isfile(path):
            with io.open(path, u"r", encoding=u"utf-8") as handle:
                return parse_settings(handle.read())
        if legacy_path and os.path.isfile(legacy_path):
            with io.open(legacy_path, u"r", encoding=u"utf-8") as handle:
                return parse_settings(handle.read(), legacy=True)
    except Exception:
        pass
    return dict(DEFAULTS)


def save_settings(values, path=None):
    if isinstance(values, DomainView):
        values = values.base
    path = path or settings_path()
    try:
        folder = os.path.dirname(path)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        text = format_settings(values)
        with io.open(path, u"w", encoding=u"utf-8") as handle:
            handle.write(text)
        return True
    except Exception:
        return False


def to_bool(value):
    return u"{0}".format(value).strip().lower() in (u"1", u"true", u"yes", u"on")


def from_bool(flag):
    return u"1" if flag else u"0"


def split_list(value):
    return [part.strip() for part in u"{0}".format(value or u"").split(u"|")
            if part.strip()]


def join_list(items):
    return u"|".join([u"{0}".format(item).replace(u"|", u"/") for item in items])


def to_float(value, default):
    try:
        return float(u"{0}".format(value).strip())
    except Exception:
        return default


# ============================================================
# text helpers
# ============================================================

_NUM_RUN = re.compile(u"(\\d+(?:\\.\\d+)?)")


def natural_key(value):
    """P-9, P-10, P-100 rather than P-10, P-100, P-9. Numbers sort as
    numbers; text sorts case-blind. Mixed parts never compare str with int."""
    text = u"{0}".format(value if value is not None else u"")
    parts = _NUM_RUN.split(text)
    key = []
    for index, part in enumerate(parts):
        if index % 2 == 1:
            key.append((0, float(part), u""))
        elif part:
            key.append((1, 0.0, part.lower()))
    return tuple(key)


def format_size(mm):
    """Nominal size text, in mm: 15, 22, 54, 12.5 - never 15.0."""
    try:
        value = round(float(mm), 1)
    except Exception:
        return u""
    if abs(value - round(value)) < 0.05:
        return u"{0}".format(int(round(value)))
    return u"{0:.1f}".format(value)


def feet_to_mm(value):
    return float(value) * MM_PER_FOOT


def feet_to_m(value):
    return float(value) * MM_PER_FOOT / 1000.0


def mm_to_feet(value):
    return float(value) / MM_PER_FOOT


# ============================================================
# checks and pipe type standards
# ============================================================

# (name, label) in the order they read on a row. Each is switched by the
# setting check_<name>.
CHECKS = (
    (u"standards", u"Type not allowed"),
    (u"sizes", u"Size not in routing"),
    (u"open_ends", u"Open end"),
    (u"mismatch", u"Fitting on another system"),
    (u"no_system", u"No system"),
)
CHECK_LABELS = dict(CHECKS)


def check_labels(domain=None):
    labels = dict(CHECK_LABELS)
    if domain:
        labels.update(domain_info(domain)[u"check_labels"])
    return labels


def checks_for(domain):
    return tuple(domain_info(domain)[u"checks"])


def field_titles(domain=None):
    titles = dict(FIELD_TITLES)
    if domain:
        info = domain_info(domain)
        titles[u"system"] = info[u"system_word"]
        titles[u"ptype"] = info[u"type_word"]
    return titles

_STD_ENTRY = u";;"
_STD_SERVICE = u">>"
_STD_TYPE = u"|"


def _std_clean(text):
    text = u"{0}".format(text or u"")
    for sep in (_STD_ENTRY, _STD_SERVICE, _STD_TYPE):
        text = text.replace(sep, u" ")
    return text.strip()


def encode_standards(standards):
    """{service: [allowed pipe type, ...]} -> one settings line, readable by
    hand: Cold Water>>Copper|MLCP;;Hot Water>>Copper. A service with nothing
    ticked is left out - it has no standard, rather than allowing nothing."""
    entries = []
    for service in sorted(standards or {}, key=natural_key):
        types = sorted(set([_std_clean(t) for t in standards[service] if _std_clean(t)]),
                       key=natural_key)
        name = _std_clean(service)
        if name and types:
            entries.append(name + _STD_SERVICE + _STD_TYPE.join(types))
    return _STD_ENTRY.join(entries)


def decode_standards(text):
    out = {}
    for entry in u"{0}".format(text or u"").split(_STD_ENTRY):
        if _STD_SERVICE not in entry:
            continue
        service, types = entry.split(_STD_SERVICE, 1)
        service = service.strip()
        allowed = [t.strip() for t in types.split(_STD_TYPE) if t.strip()]
        if service and allowed:
            out[service] = allowed
    return out


def checks_on(settings):
    return to_bool((settings or {}).get(u"checks_on", u"1"))


def enabled_checks(settings, domain=None):
    """The checks that flag a row. The toolbar switch turns them all off
    without touching which ones are ticked, so switching back restores them.
    A check that means nothing for the discipline (sizes, for containment)
    is never on."""
    if not checks_on(settings):
        return set()
    names = checks_for(domain) if domain else [n for n, _l in CHECKS]
    return set([name for name in names
                if to_bool((settings or {}).get(u"check_" + name, u"1"))])


def allowed_types(standards, group):
    return list((standards or {}).get(group) or [])


def record_issues(record, group, standards, checks):
    """What is wrong with one pipe, as {check: count}. Only enabled checks
    count; a pipe with nothing wrong gives {}."""
    checks = checks or set()
    out = {}
    if u"standards" in checks:
        allowed = allowed_types(standards, group)
        if allowed and (record.get(u"ptype") or u"") not in allowed:
            out[u"standards"] = 1
    if u"sizes" in checks and record.get(u"size_ok") is False:
        out[u"sizes"] = 1
    if u"open_ends" in checks and (record.get(u"open_ends") or 0) > 0:
        out[u"open_ends"] = int(record.get(u"open_ends"))
    if u"mismatch" in checks and (record.get(u"mismatch") or 0) > 0:
        out[u"mismatch"] = int(record.get(u"mismatch"))
    # containment has no systems: the model says whether it has a service type
    has_system = record.get(u"has_system", bool(record.get(u"system_id")))
    if u"no_system" in checks and not has_system:
        out[u"no_system"] = 1
    return out


def check_text(issues, labels=None):
    """{check: count} -> 'Type not allowed x3 · Open end x2'."""
    parts = []
    labels = labels or CHECK_LABELS
    for name, _default in CHECKS:
        label = labels.get(name, _default)
        count = (issues or {}).get(name, 0)
        if count == 1:
            parts.append(label)
        elif count > 1:
            parts.append(u"{0} \u00d7{1}".format(label, count))
    return u" \u00b7 ".join(parts)


def suggest_type(rows, standards, available):
    """The pipe type to offer when the selected rows all sit in one service
    that has a standard: its first allowed type that exists in the model."""
    groups = set([r.get(u"group") for r in rows or []])
    if len(groups) != 1:
        return None
    available = list(available or [])
    for name in allowed_types(standards, groups.pop()):
        if name in available:
            return name
    return None


def only_flagged(rows, on):
    if not on:
        return list(rows)
    return [r for r in rows if r.get(u"flag")]


# ============================================================
# export
# ============================================================

def size_number(text):
    """A size cell as a number when it is one ('22'), else None ('15-54')."""
    try:
        return float(u"{0}".format(text))
    except Exception:
        return None


def export_summary(groups):
    """[(service, rows)] -> one summary line per service."""
    out = []
    for service, rows in groups:
        systems = set()
        fittings = set()
        for row in rows:
            systems.update(row.get(u"systems") or [])
            fittings.update(row.get(u"fitting_ids") or [])
        length_ft = sum([float(r.get(u"length_ft") or 0.0) for r in rows])
        out.append({
            u"service": service,
            u"rows": len(rows),
            u"pipes": sum([int(r.get(u"count") or 0) for r in rows]),
            u"length_m": round(length_ft * MM_PER_FOOT / 1000.0, 1),
            u"systems": len(systems),
            u"fittings": len(fittings),
            u"flagged": len([r for r in rows if r.get(u"flag")]),
        })
    return out


def export_filename(project, label=u"Pipe systems"):
    name = u"{0}".format(project or u"").strip()
    if name.lower().endswith(u".rvt"):
        name = name[:-4]
    name = re.sub(u'[\\\\/:*?"<>|]+', u" ", name).strip()
    name = re.sub(u"\\s+", u" ", name) or u"Project"
    return u"{0} - {1}.xlsx".format(name, label)


# ============================================================
# grouping
# ============================================================

FIELDS = (u"system", u"ptype", u"size", u"count", u"length", u"fittings", u"check")
FIELD_TITLES = {
    u"system": u"System No",
    u"ptype": u"Pipe Type",
    u"size": u"Size (mm)",
    u"count": u"Count",
    u"length": u"Length (m)",
    u"fittings": u"Fittings",
    u"check": u"Checks",
}
NUMERIC_FIELDS = (u"size", u"count", u"length", u"fittings", u"elements")

# the Workset Assigner's columns
WS_FIELDS = (u"system", u"workset", u"elements", u"new_workset")
# grouped by discipline only, the system type becomes a column
WS_FIELDS_FLAT = (u"system_type", u"system", u"workset", u"elements", u"new_workset")
WS_TITLES = {u"system": u"System", u"workset": u"Workset now",
             u"elements": u"Elements", u"new_workset": u"New workset",
             u"system_type": u"System Type"}
WS_GROUPINGS = ((u"type", u"Discipline > system type > system"),
                (u"discipline", u"Discipline > system"))
SEARCH_FIELDS = FIELDS + (u"workset", u"new_workset", u"system_type")


def group_label(record, group_by):
    """The service type a pipe is filed under."""
    if group_by == u"classification":
        value = record.get(u"classification")
    elif group_by == u"param":
        value = record.get(u"group_param")
    else:
        value = record.get(u"system_type")
    value = u"{0}".format(value or u"").strip()
    return value or UNASSIGNED


def size_text_of(record):
    """A record's size as shown: its own text (600x300, a diameter) when the
    model gave one, else the round size in mm."""
    text = record.get(u"size_text")
    if text:
        return text
    return format_size(record.get(u"size_mm"))


def size_num_of(record):
    value = record.get(u"size_num")
    if value is None:
        value = record.get(u"size_mm")
    return value


def rect_size_text(width_mm, height_mm):
    return u"{0}x{1}".format(format_size(width_mm), format_size(height_mm))


def round_size_text(diameter_mm):
    return u"\u00d8{0}".format(format_size(diameter_mm))


def row_key(record, split_system, split_type, split_size):
    parts = [
        record.get(u"system") if split_system else u"*",
        record.get(u"ptype") if split_type else u"*",
        size_text_of(record) if split_size else u"*",
    ]
    return u"\u241f".join([u"{0}".format(p or u"") for p in parts])


def _summarise(values, noun):
    values = [v for v in values if v not in (None, u"")]
    distinct = sorted(set(values), key=natural_key)
    if not distinct:
        return u"-"
    if len(distinct) == 1:
        return distinct[0]
    return u"{0} {1}".format(len(distinct), noun)


def build_groups(records, group_by=u"system_type", split_system=True,
                 split_type=True, split_size=True, standards=None, checks=None,
                 domain=None):
    """records -> {service type: [row, ...]}. A row is one combination of
    whichever of system / pipe type / size the rows are split by, with the
    count of pipes in it. Unticking a split merges rows and recounts."""
    groups = {}
    for record in records:
        group = group_label(record, group_by)
        key = row_key(record, split_system, split_type, split_size)
        rows = groups.setdefault(group, {})
        row = rows.get(key)
        if row is None:
            row = {
                u"key": u"{0}\u241e{1}".format(group, key),
                u"group": group,
                u"ids": [],
                u"_systems": [],
                u"_types": [],
                u"_sizes": [],
                u"_fittings": set(),
                u"issues": {},
                u"length_ft": 0.0,
            }
            rows[key] = row
        row[u"ids"].append(record.get(u"id"))
        row[u"_systems"].append(u"{0}".format(record.get(u"system") or u""))
        row[u"_types"].append(u"{0}".format(record.get(u"ptype") or u""))
        row[u"_sizes"].append((size_num_of(record), size_text_of(record)))
        row[u"_fittings"].update(record.get(u"fittings") or [])
        for name, count in record_issues(record, group, standards, checks).items():
            row[u"issues"][name] = row[u"issues"].get(name, 0) + count
        try:
            row[u"length_ft"] += float(record.get(u"length_ft") or 0.0)
        except Exception:
            pass

    out = {}
    for group, rows in groups.items():
        finished = []
        for row in rows.values():
            known = [s for s in row[u"_sizes"] if s[0] is not None and s[1]]
            sizes = [s[0] for s in known]
            size_texts = []
            for _num, text in sorted(known, key=lambda s: (s[0], natural_key(s[1]))):
                if text not in size_texts:
                    size_texts.append(text)
            row[u"system"] = _summarise(row[u"_systems"], u"systems")
            row[u"ptype"] = _summarise(row[u"_types"], u"types")
            if len(size_texts) == 1:
                row[u"size"] = size_texts[0]
            elif size_texts:
                row[u"size"] = u"{0}-{1}".format(size_texts[0], size_texts[-1])
            else:
                row[u"size"] = u"-"
            row[u"size_num"] = min(sizes) if sizes else 0.0
            row[u"count"] = len(row[u"ids"])
            row[u"length"] = u"{0:.1f}".format(
                row[u"length_ft"] * MM_PER_FOOT / 1000.0)
            row[u"system_count"] = len(set([s for s in row[u"_systems"] if s]))
            row[u"systems"] = sorted(set([s for s in row[u"_systems"] if s]),
                                     key=natural_key)
            row[u"fitting_ids"] = sorted(row[u"_fittings"])
            row[u"fittings"] = len(row[u"fitting_ids"])
            row[u"issue_count"] = sum(row[u"issues"].values())
            row[u"check"] = check_text(row[u"issues"], check_labels(domain))
            row[u"flag"] = row[u"issue_count"] > 0
            for scratch in (u"_systems", u"_types", u"_sizes", u"_fittings"):
                del row[scratch]
            finished.append(row)
        out[group] = sort_rows(finished, [(u"system", False), (u"ptype", False),
                                          (u"size", False)])
    return out


def group_order(names):
    """Natural order, with Unassigned always last."""
    named = sorted([n for n in names if n != UNASSIGNED], key=natural_key)
    if UNASSIGNED in names:
        named.append(UNASSIGNED)
    return named


# ============================================================
# sorting and filtering
# ============================================================

def cell_text(row, field):
    value = row.get(field)
    if value is None:
        return u""
    return u"{0}".format(value)


def sort_value(row, field):
    if field == u"size":
        return (0, float(row.get(u"size_num") or 0.0), natural_key(row.get(u"size")))
    if field == u"count":
        return (0, float(row.get(u"count") or 0), ())
    if field == u"length":
        return (0, float(row.get(u"length_ft") or 0.0), ())
    if field == u"fittings":
        return (0, float(row.get(u"fittings") or 0), ())
    if field == u"check":
        return (0, float(row.get(u"issue_count") or 0), natural_key(row.get(u"check")))
    if field == u"elements":
        return (0, float(row.get(u"count") or 0), ())
    return (1, 0.0, natural_key(row.get(field)))


def sort_rows(rows, sort_stack):
    """Multi-level sort, least significant level first, relying on a stable
    sort - one composite key cannot give each level its own direction."""
    ordered = list(rows)
    for level in range(len(sort_stack) - 1, -1, -1):
        field, descending = sort_stack[level]
        ordered.sort(key=lambda r, f=field: sort_value(r, f), reverse=descending)
    return ordered


def toggle_sort(sort_stack, field, add_level, max_levels=6):
    """Click: one level on this field, flipping if it was already the only
    one. Shift-click: add a level, or flip that level alone if present."""
    stack = list(sort_stack)
    for index, (existing, descending) in enumerate(stack):
        if existing == field:
            if add_level or len(stack) == 1:
                stack[index] = (field, not descending)
                return stack
            return [(field, False)]
    if add_level:
        if len(stack) < max_levels:
            stack.append((field, False))
        return stack
    return [(field, False)]


def keyword_match(text, keywords):
    """Every word typed must appear somewhere in the text, case-blind."""
    words = [w for w in u"{0}".format(keywords or u"").lower().split() if w]
    if not words:
        return True
    haystack = u"{0}".format(text or u"").lower()
    for word in words:
        if word not in haystack:
            return False
    return True


def row_passes(row, col_keywords, col_ticks, global_text=u"", exclude=None):
    for field, text in (col_keywords or {}).items():
        if field == exclude:
            continue
        if not keyword_match(cell_text(row, field), text):
            return False
    for field, allowed in (col_ticks or {}).items():
        if field == exclude or allowed is None:
            continue
        if cell_text(row, field) not in allowed:
            return False
    if global_text:
        joined = u" ".join([cell_text(row, f) for f in SEARCH_FIELDS] +
                           [u"{0}".format(row.get(u"group") or u"")])
        if not keyword_match(joined, global_text):
            return False
    return True


def filter_rows(rows, col_keywords=None, col_ticks=None, global_text=u"",
                exclude=None):
    return [r for r in rows
            if row_passes(r, col_keywords, col_ticks, global_text, exclude)]


def tick_values(rows, field, col_keywords=None, col_ticks=None, global_text=u""):
    """What a column's tick list offers: the values the OTHER filters let
    through. Its own filter is left out, the way Excel does it, or a value
    it hides could never be ticked back on."""
    passing = filter_rows(rows, col_keywords, col_ticks, global_text,
                          exclude=field)
    if field in NUMERIC_FIELDS:
        values = sorted(set([cell_text(r, field) for r in passing]),
                        key=lambda t: (natural_key(t),))
    else:
        values = sorted(set([cell_text(r, field) for r in passing]),
                        key=natural_key)
    return values


def ticks_to_filter(all_values, ticked):
    """Everything ticked means no filter; nothing ticked shows nothing."""
    ticked = set(ticked)
    if set(all_values).issubset(ticked):
        return None
    return ticked


def selected_ids(rows):
    seen = set()
    out = []
    for row in rows:
        for element_id in row.get(u"ids") or []:
            if element_id not in seen:
                seen.add(element_id)
                out.append(element_id)
    return out


# ============================================================
# a modeless window whose engine died
# ============================================================

def flag_text(version):
    return u"opened {0}".format(version)


def should_offer_modal(flag_contents, version, window_mode):
    """Offer modal only when the note launch() left says a window of THIS
    version opened and no handler ever ran after it was shown. No note, a
    note from another version, or modal already chosen: open as normal."""
    if window_mode == u"modal" or flag_contents is None:
        return False
    return u"{0}".format(flag_contents).strip() == flag_text(version)


# ============================================================
# keeping the selection through a refresh
# ============================================================

def layout_signature(settings):
    """What decides the shape of the rows. Sorts and filters only carry over
    a refresh when this is unchanged - a Size tick of '22' means nothing once
    sizes are no longer split and read '15-22'."""
    return u"|".join([u"{0}".format((settings or {}).get(k, u"")) for k in
                      (u"group_by", u"group_param", u"system_from",
                       u"split_system", u"split_type", u"split_size", u"ws_grouping")])


def rows_to_reselect(rows, keys, ids):
    """The rows to select after a refresh: any row with the same key as a row
    selected before, or holding any pipe that was selected before. Keys alone
    are not enough - the pipe type is part of a row's key, so after a type
    change the row the pipes now sit in has a new one."""
    keys = set(keys or [])
    ids = set(ids or [])
    out = []
    for row in rows:
        if row.get(u"key") in keys or ids.intersection(row.get(u"ids") or []):
            out.append(row)
    return out


def loosen_for(rows, col_keywords, col_ticks, global_text=u""):
    """Filters that would hide a reselected row are loosened just enough to
    show it: its value is ticked back on in a tick list, and a column keyword
    that rules it out is cleared. Returns (keywords, ticks, loosened fields,
    whether the search box would hide one)."""
    keywords = dict(col_keywords or {})
    ticks = {}
    for field, allowed in (col_ticks or {}).items():
        ticks[field] = None if allowed is None else set(allowed)
    loosened = set()
    for row in rows:
        for field, text in list(keywords.items()):
            if text and not keyword_match(cell_text(row, field), text):
                keywords[field] = u""
                loosened.add(field)
        for field, allowed in ticks.items():
            if allowed is not None and cell_text(row, field) not in allowed:
                allowed.add(cell_text(row, field))
                loosened.add(field)
    hides = False
    if global_text:
        for row in rows:
            if not row_passes(row, {}, {}, global_text):
                hides = True
                break
    return keywords, ticks, sorted(loosened), hides


# ============================================================
# 3D view choice
# ============================================================

DEFAULT_VIEW_LABEL = u"<Default 3D view>"


def default_3d_name(user, workshared):
    if workshared and user:
        return u"{{3D - {0}}}".format(user)
    return u"{3D}"


def pick_default_3d(view_names, user, workshared):
    """Revit's own default 3D: '{3D - user}' on a workshared model, else
    '{3D}'. Either is accepted if present, the user's own first. None means
    it has to be made."""
    preferred = default_3d_name(user, workshared)
    if preferred in view_names:
        return preferred
    if u"{3D}" in view_names:
        return u"{3D}"
    return None


def fit_section_box(default_view, settings):
    """The default 3D view always has its section box fitted round what was
    isolated - it is Revit's scratch view, there to be cropped. A 3D view
    picked from the list only gets one when the setting asks for it, since it
    may be a set-up coordination view whose box somebody placed by hand."""
    if default_view:
        return True
    return to_bool((settings or {}).get(u"isolate_section_box"))


def isolate_categories(domain):
    return tuple(domain_info(domain)[u"isolate"])


def keep_for_isolate(is_selected, category_ok, element_systems, selected_systems,
                     touches_selected):
    """Whether an element found by the isolate walk belongs in the isolate.

    A pipe the user picked always stays. Anything else has to be pipework,
    and has to be on one of the systems the picked pipes are on - touching a
    picked pipe is not enough, since a fitting or valve at a boundary can
    belong to the next system along. Only an element that reports no system
    at all is let in on the strength of touching a picked pipe."""
    if is_selected:
        return True
    if not category_ok:
        return False
    systems = set([s for s in (element_systems or []) if s])
    if systems:
        return bool(systems & set(selected_systems or []))
    return bool(touches_selected)


def nearest_within(point, candidates, tolerance):
    """point (x, y, z); candidates [(id, (x, y, z))]. The id of the nearest
    candidate no further than tolerance away, else None - how a fitting Revit
    replaced during a type change is found again."""
    if point is None:
        return None
    best = None
    best_d = None
    for cid, other in candidates:
        if other is None:
            continue
        d = ((point[0] - other[0]) ** 2 + (point[1] - other[1]) ** 2 +
             (point[2] - other[2]) ** 2) ** 0.5
        if d <= tolerance and (best_d is None or d < best_d):
            best, best_d = cid, d
    return best


# ============================================================
# changing pipe type
# ============================================================

PART_TO_GROUP = {
    u"Elbow": u"Elbows",
    u"Tee": u"Junctions",
    u"TapPerpendicular": u"Junctions",
    u"TapAdjustable": u"Junctions",
    u"SpudPerpendicular": u"Junctions",
    u"SpudAdjustable": u"Junctions",
    u"Wye": u"Junctions",
    u"LateralTee": u"Junctions",
    u"Cross": u"Crosses",
    u"LateralCross": u"Crosses",
    u"Transition": u"Transitions",
    u"Union": u"Unions",
    u"Cap": u"Caps",
}


def routing_group_for(part_type):
    """PartType name -> RoutingPreferenceRuleGroupType name, or None where
    the routing preferences hold nothing for that kind of fitting."""
    return PART_TO_GROUP.get(u"{0}".format(part_type or u"").strip())


def values_equal(a, b, storage=u"String"):
    if storage == u"Double":
        try:
            return abs(float(a) - float(b)) < 1e-6
        except Exception:
            return a == b
    if storage == u"String":
        return (a or u"") == (b or u"")
    return a == b


def plan_restore(snapshot, readback):
    """snapshot / readback: {name: (storage, value)}. Returns the names whose
    value moved when the type changed and so has to be written back."""
    out = []
    for name in sorted(snapshot):
        storage, before = snapshot[name]
        if name not in readback:
            out.append(name)
            continue
        after = readback[name][1]
        if not values_equal(before, after, storage):
            out.append(name)
    return out


def fitting_swap_allowed(neighbour_ids, changing_ids):
    """A fitting is swapped only when every pipe it joins is changing too -
    a tee between a changed run and an untouched one is left alone."""
    neighbours = [n for n in neighbour_ids if n is not None]
    if not neighbours:
        return False
    changing = set(changing_ids)
    for n in neighbours:
        if n not in changing:
            return False
    return True


def chunks(items, size):
    items = list(items)
    return [items[i:i + size] for i in range(0, len(items), size)]


def change_summary(pipe_count, system_names, from_types, to_type, retain,
                   keep_size, swap_fittings, fitting_count, domain=u"pipe"):
    lines = []
    info = domain_info(domain)
    lines.append(u"Change {0} {1} to:  {2}".format(pipe_count, noun(domain, pipe_count), to_type))
    if system_names:
        shown = system_names[:12]
        more = len(system_names) - len(shown)
        lines.append(u"{0}: {1}{2}".format(
            u"Runs" if domain == u"cont" else u"Systems",
            u", ".join(shown), u" and {0} more".format(more) if more > 0 else u""))
    if from_types:
        lines.append(u"Currently: {0}".format(u", ".join(from_types)))
    lines.append(u"")
    lines.append(u"Keep each {0}'s size: {1}".format(info[u"noun"][0],
                                                     u"yes" if keep_size else u"no"))
    if retain:
        lines.append(u"Parameters retained: {0}".format(u", ".join(retain)))
    else:
        lines.append(u"Parameters retained: none ticked in Settings")
    if swap_fittings:
        lines.append(u"Fittings swapped to {0}: up to {1}".format(
            info[u"swap_source"], fitting_count))
    else:
        lines.append(u"Fittings: left as they are")
    return u"\n".join(lines)


def sizes_equal(before, after, tolerance=1e-6):
    """Two size states ({parameter: feet}) are the same size: same
    parameters, every value within tolerance. A round duct that became
    rectangular has different parameters, so it is not the same size."""
    before = before or {}
    after = after or {}
    if set(before) != set(after):
        return False
    for key, value in before.items():
        if abs(value - after[key]) > tolerance:
            return False
    return True


def results_need_a_look(result):
    return bool(result.get(u"failed") or result.get(u"locked") or result.get(u"wrong_kind") or
                result.get(u"not_restored") or result.get(u"size_changed") or
                result.get(u"fitting_failed") or result.get(u"error"))


# ============================================================
# containment: resizing runs
# ============================================================

# the size parameters a run is resized through, by kind
TRAY_WIDTH = u"RBS_CABLETRAY_WIDTH_PARAM"
TRAY_HEIGHT = u"RBS_CABLETRAY_HEIGHT_PARAM"
CONDUIT_DIAMETER = u"RBS_CONDUIT_DIAMETER_PARAM"


def parse_mm(text):
    """A size box: (mm or None, error text). Blank means leave it alone."""
    text = u"{0}".format(text or u"").strip().lower().replace(u"mm", u"").strip()
    if not text:
        return None, u""
    try:
        value = float(text)
    except Exception:
        return None, u"'{0}' is not a number".format(text)
    if value <= 0:
        return None, u"a size has to be more than 0"
    if value > 5000:
        return None, u"{0}mm is more than 5m - check the units".format(format_size(value))
    return value, u""


def resize_plan(elements, width=None, height=None, diameter=None):
    """elements: [{id, kind: tray|conduit, size: {parameter: mm}}]. Returns
    ({id: {parameter: new mm}}, {"unchanged": n, "no_input": n}): a tray takes
    the width and height given, a conduit the diameter; a value it already has
    is not written, and a kind with nothing entered for it is left alone."""
    plan = {}
    counts = {u"unchanged": 0, u"no_input": 0}
    for element in elements:
        kind = element.get(u"kind")
        wanted = {}
        if kind == u"tray":
            if width is not None:
                wanted[TRAY_WIDTH] = width
            if height is not None:
                wanted[TRAY_HEIGHT] = height
        elif kind == u"conduit" and diameter is not None:
            wanted[CONDUIT_DIAMETER] = diameter
        if not wanted:
            counts[u"no_input"] += 1
            continue
        now = element.get(u"size") or {}
        changes = dict((k, v) for k, v in wanted.items()
                       if now.get(k) is None or abs(now[k] - v) > 0.01)
        if changes:
            plan[element[u"id"]] = changes
        else:
            counts[u"unchanged"] += 1
    return plan, counts


def run_members(records, ids, group_by=u"system_type", system_from=u""):
    """The trays and conduits a whole-run resize will take, worked out from
    the table: every record on the same run (the Run column), service and
    kind as a selected one. The Run column comes from the same walk the
    resize uses, so the two agree. None when System No is taken from a
    parameter - the runs are not in the table then."""
    if system_from:
        return None
    ids = set(ids)
    wanted = set()
    for record in records:
        if record.get(u"id") in ids:
            wanted.add((record.get(u"kind"), group_label(record, group_by), record.get(u"system")))
    return sorted([r[u"id"] for r in records
                   if (r.get(u"kind"), group_label(r, group_by), r.get(u"system")) in wanted])


def resize_summary(runs, trays, conduits, width, height, diameter, whole_run):
    lines = [u"Resize {0} run{1}{2}:".format(runs, u"" if runs == 1 else u"s",
                                            u" (whole runs)" if whole_run else u"")]
    if trays:
        size = u"{0} x {1}".format(format_size(width) if width else u"(width as is)",
                                   format_size(height) if height else u"(height as is)")
        lines.append(u"   {0} cable tray{1} to {2}".format(
            trays, u"" if trays == 1 else u"s", size)
            if (width or height) else
            u"   {0} cable tray{1} - no tray size given, left as they are".format(
                trays, u"" if trays == 1 else u"s"))
    if conduits:
        lines.append(u"   {0} conduit{1} to \u00d8{2}".format(
            conduits, u"" if conduits == 1 else u"s", format_size(diameter))
            if diameter else
            u"   {0} conduit{1} - no diameter given, left as they are".format(
                conduits, u"" if conduits == 1 else u"s"))
    lines.append(u"")
    lines.append(u"Each run is resized on its own. If Revit reports an error, what it objects "
                 u"to is put back as it was and listed, and you can isolate it with the "
                 u"elements Revit named shown in red.")
    return u"\n".join(lines)


# ============================================================
# the red highlight, and taking it off again
# ============================================================

def encode_highlight(view_id, ids):
    ids = [int(i) for i in ids if i]
    if not view_id or not ids:
        return u""
    return u"{0}:{1}".format(int(view_id), u"|".join([u"{0}".format(i) for i in ids]))


def decode_highlight(text):
    """(view id, [ids]) or (0, [])."""
    text = u"{0}".format(text or u"")
    if u":" not in text:
        return 0, []
    head, tail = text.split(u":", 1)
    try:
        view_id = int(head)
    except Exception:
        return 0, []
    ids = []
    for part in tail.split(u"|"):
        try:
            ids.append(int(part))
        except Exception:
            pass
    return view_id, ids


# ============================================================
# the debug table
# ============================================================

DEBUG_ROW_LIMIT = 2000
DEBUG_CELL_LIMIT = 400


def md_cell(value):
    """One Markdown table cell: pipes escaped, line breaks as <br>, cut short."""
    text = u"{0}".format(u"" if value is None else value)
    text = text.replace(u"\\", u"\\\\").replace(u"|", u"\\|")
    text = text.replace(u"\r\n", u"\n").replace(u"\r", u"\n").replace(u"\n", u"<br>")
    if len(text) > DEBUG_CELL_LIMIT:
        text = text[:DEBUG_CELL_LIMIT] + u"... (cut)"
    return text


def add_debug_row(rows, row, limit=DEBUG_ROW_LIMIT):
    """Keep the newest rows: a long session drops its oldest first."""
    rows.append(row)
    if len(rows) > limit:
        del rows[:len(rows) - limit]
    return rows


DEBUG_COLUMNS = (u"time", u"tab", u"action", u"step", u"element", u"detail")


def debug_table(environment, rows):
    """environment: [(key, value)], rows: [{time, tab, action, step, element,
    detail}] -> Markdown, ready to paste into a chat."""
    out = [u"### {0} debug table - v{1}".format(TOOL_NAME, __version__), u""]
    out.append(u"| Key | Value |")
    out.append(u"| --- | --- |")
    for key, value in environment:
        out.append(u"| {0} | {1} |".format(md_cell(key), md_cell(value)))
    out.append(u"")
    out.append(u"| # | " + u" | ".join([c.capitalize() for c in DEBUG_COLUMNS]) + u" |")
    out.append(u"| --- " * (len(DEBUG_COLUMNS) + 1) + u"|")
    for index, row in enumerate(rows):
        cells = [md_cell(row.get(c, u"")) for c in DEBUG_COLUMNS]
        out.append(u"| {0} | {1} |".format(index + 1, u" | ".join(cells)))
    if not rows:
        out.append(u"| - | " + u" | ".join([u""] * len(DEBUG_COLUMNS)) + u" |")
    return u"\n".join(out) + u"\n"


# ============================================================
# the Workset Assigner
# ============================================================

DISCIPLINE_LABEL = {u"pipe": u"Pipework", u"duct": u"Ductwork", u"cont": u"Containment"}
# the order the Workset Assigner shows them in
WS_DISCIPLINE_ORDER = (u"cont", u"pipe", u"duct")


def workset_summary(counts):
    """{workset name: elements} -> 'MEP-Plumbing' or 'Mixed: A (12), B (3)'."""
    counts = dict((k, v) for k, v in (counts or {}).items() if v)
    if not counts:
        return u"-"
    if len(counts) == 1:
        return list(counts.keys())[0]
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], natural_key(kv[0])))
    return u"Mixed: " + u", ".join([u"{0} ({1})".format(k, v) for k, v in ordered])


def ws_group_label(discipline, system_type):
    return u"{0} \u00b7 {1}".format(DISCIPLINE_LABEL.get(discipline, discipline),
                                     system_type or UNASSIGNED)


def ws_group_order(names):
    """Containment, then Pipework, then Ductwork; natural order inside each."""
    rank = dict((DISCIPLINE_LABEL[d], i) for i, d in enumerate(WS_DISCIPLINE_ORDER))

    def key(name):
        head = name.split(u" \u00b7 ", 1)[0]
        return (rank.get(head, 9), natural_key(name))
    return sorted(names, key=key)


def workset_rows(systems, pending, names):
    """systems: [{key, discipline, type, name, ids, worksets: {id: n}}];
    pending: {key: workset id}; names: {workset id: name}.
    -> ({group label: [row]}, {group label: type-wide summary})."""
    groups = {}
    totals = {}
    for system in systems:
        label = ws_group_label(system.get(u"discipline"), system.get(u"type"))
        counts = {}
        for wid, n in (system.get(u"worksets") or {}).items():
            name = names.get(wid, u"workset {0}".format(wid))
            counts[name] = counts.get(name, 0) + n
            totals.setdefault(label, {})
            totals[label][name] = totals[label].get(name, 0) + n
        target = (pending or {}).get(system[u"key"])
        on = [w for w, n in (system.get(u"worksets") or {}).items() if n]
        row = {u"key": system[u"key"], u"group": label,
               u"discipline": system.get(u"discipline"),
               u"system_type": system.get(u"type") or UNASSIGNED,
               u"mixed": len(on) > 1,
               u"system": system.get(u"name") or u"(unnamed)",
               u"workset": workset_summary(counts),
               u"elements": len(system.get(u"ids") or []),
               u"count": len(system.get(u"ids") or []),
               u"ids": list(system.get(u"ids") or []),
               u"new_workset": names.get(target, u"") if target is not None else u"",
               u"pend": target is not None, u"flag": False}
        groups.setdefault(label, []).append(row)
    for label in groups:
        groups[label] = sorted(groups[label], key=lambda r: natural_key(r[u"system"]))
    notes = dict((label, workset_summary(totals.get(label))) for label in groups)
    return groups, notes


def workset_tree(systems, pending, names, grouping=u"type", mixed_only=False):
    """The Workset Assigner's two levels:
    [(discipline label, [(section name, rows, note)])], disciplines in
    Containment / Pipework / Ductwork order. grouping "type": a section per
    system type. "discipline": one section holding the discipline's systems,
    the system type a column. mixed_only keeps only systems whose elements
    are on more than one workset; an emptied section or discipline goes."""
    groups, notes = workset_rows(systems, pending, names)
    by_discipline = {}
    for label in groups:
        rows = [r for r in groups[label] if r[u"mixed"]] if mixed_only else groups[label]
        if not rows:
            continue
        discipline = rows[0][u"discipline"]
        by_discipline.setdefault(discipline, []).append((label, rows, notes.get(label, u"-")))
    tree = []
    for discipline in WS_DISCIPLINE_ORDER:
        sections = by_discipline.get(discipline)
        if not sections:
            continue
        title = DISCIPLINE_LABEL[discipline]
        if grouping == u"discipline":
            rows = []
            for _label, section_rows, _note in sections:
                rows.extend(section_rows)
            rows = sorted(rows, key=lambda r: (natural_key(r[u"system_type"]),
                                               natural_key(r[u"system"])))
            tree.append((title, [(title, rows, u"")]))
        else:
            ordered = ws_group_order([s[0] for s in sections])
            lookup = dict((s[0], s) for s in sections)
            tree.append((title, [lookup[name] for name in ordered]))
    return tree


def mixed_count(systems):
    return len([s for s in systems or []
                if len([w for w, n in (s.get(u"worksets") or {}).items() if n]) > 1])


def filter_choices(choices, text):
    """[(name, value)] narrowed to the names holding every word typed.
    (shown, matched): a search that matches nothing keeps the whole list and
    says so, rather than leaving an empty dropdown."""
    choices = list(choices or [])
    if not (text or u"").strip():
        return choices, True
    shown = [c for c in choices if keyword_match(c[0], text)]
    if not shown:
        return choices, False
    return shown, True


def stage_worksets(pending, keys, workset_id):
    """Nothing is written until Apply: staging only records the choice."""
    out = dict(pending or {})
    for key in keys:
        out[key] = workset_id
    return out


def staged_rows(systems, pending, names):
    """Every staged system as a row, from the whole read - not from what the
    table happens to show. A staged system hidden by a filter, or by
    "only systems on more than one workset", is still applied."""
    groups, _notes = workset_rows(systems, pending, names)
    return [r for rows in groups.values() for r in rows if r[u"key"] in (pending or {})]


def workset_plan_text(rows, pending, names):
    """What Apply will do, by target workset."""
    by_target = {}
    for row in rows:
        target = (pending or {}).get(row[u"key"])
        if target is None:
            continue
        by_target.setdefault(target, []).append(row)
    lines = []
    total = 0
    for target in sorted(by_target, key=lambda t: natural_key(names.get(t, u""))):
        items = by_target[target]
        count = sum([len(r[u"ids"]) for r in items])
        total += count
        lines.append(u"To {0}: {1} system{2}, {3} element{4}".format(
            names.get(target, target), len(items), u"" if len(items) == 1 else u"s",
            count, u"" if count == 1 else u"s"))
        for row in items[:8]:
            lines.append(u"   {0} - {1} (now {2})".format(row[u"group"], row[u"system"],
                                                         row[u"workset"]))
        if len(items) > 8:
            lines.append(u"   ...and {0} more".format(len(items) - 8))
    return total, u"\n".join(lines)


# ============================================================
# containment: changing the service type
# ============================================================

SERVICE_SCOPES = ((u"rows", u"The selected rows"),
                  (u"runs", u"The whole runs of the selected rows"),
                  (u"services", u"Every run in the selected rows' service types"))


def service_scope_ids(records, ids, scope, group_by=u"system_type", system_from=u""):
    """The trays and conduits a service change reaches: the rows picked,
    their whole runs, or everything under their service types."""
    ids = set(ids)
    if scope == u"services":
        labels = set([group_label(r, group_by) for r in records if r.get(u"id") in ids])
        return sorted([r[u"id"] for r in records if group_label(r, group_by) in labels])
    if scope == u"runs":
        members = run_members(records, ids, group_by, system_from)
        if members is not None:
            return members
    return sorted([r[u"id"] for r in records if r.get(u"id") in ids])


# ============================================================
# resize: when Revit objects
# ============================================================

RESIZE_MODES = (
    (u"partial", u"Resize everything Revit allows - leave and show the rest"),
    (u"run", u"Put the whole run back if Revit objects to any of it"),
)

# Revit's failure texts, in the words a modeller would use - matched on a
# fragment so small wording changes between releases still match
FAILURE_HINTS = (
    (u"insufficient space",
     u"Revit could not fit the fittings at the new size - usually a straight too short "
     u"between two fittings, or a bend or tee that would overlap the next one when bigger. "
     u"Lengthen that straight or move the fitting, then resize again."),
    (u"opposite direction",
     u"Revit could not fit the fittings at the new size - usually a straight too short "
     u"between two fittings, or a bend or tee that would overlap the next one when bigger. "
     u"Lengthen that straight or move the fitting, then resize again."),
    (u"disconnect the family",
     u"Revit is asking whether to disconnect a family that cannot stay connected at the new "
     u"size. Settings > \"Let Revit disconnect a family it cannot keep\" answers yes and "
     u"lists what it disconnected, so you can reconnect it."),
    (u"line is too short",
     u"The pipe is shorter than the fittings the new size needs. Lengthen it, move the "
     u"fittings either side, or leave this one as it was."),
    (u"disconnect",
     u"The new size would leave elements disconnected - check the fittings at the red "
     u"elements take that size."),
    (u"cannot be created",
     u"A fitting could not be made at the new size - the type's fitting family may not go "
     u"that big."),
    (u"out of range",
     u"A size is outside what the fitting family allows."),
)


def explain_failure(text):
    """A Revit failure message -> what it usually means and what to do, or ''."""
    low = u"{0}".format(text or u"").lower()
    for fragment, hint in FAILURE_HINTS:
        if fragment in low:
            return hint
    return u""


# ============================================================
# the frozen system type heading
# ============================================================

def sticky_pick(sections, header_height):
    """sections: [(top, bottom, open)] in the order they are drawn, measured
    from the top of the visible area (a heading scrolled above it has a
    negative top). -> (index of the section to pin, or None; how far to push
    the pinned heading up, 0 or negative).

    A section is pinned while its own heading has scrolled out of sight and
    it still has rows showing below the pinned heading. As the next heading
    comes up under the pinned one it pushes it up and out, so one heading
    hands over to the next rather than jumping."""
    chosen = None
    for index, (top, bottom, is_open) in enumerate(sections):
        if top >= 0:
            break
        if is_open and bottom > 0:
            chosen = index
    if chosen is None:
        return None, 0.0
    if sections[chosen][1] <= 0:
        return None, 0.0
    push = 0.0
    for top, _bottom, _open in sections[chosen + 1:]:
        if top >= 0:
            if top < header_height:
                push = top - header_height
            break
    # the section's own end also pushes it out: its last row is going
    end = sections[chosen][1]
    if end < header_height:
        push = min(push, end - header_height)
    return chosen, push


# ============================================================
# containment: the types each service type uses
# ============================================================

def types_by_group(records, group_by=u"system_type"):
    """{service type: {type: trays and conduits}} from every record read -
    not from the table's rows, which merge types when Type is not split."""
    out = {}
    for record in records or []:
        group = group_label(record, group_by)
        ptype = record.get(u"ptype") or u"(no type)"
        out.setdefault(group, {})
        out[group][ptype] = out[group].get(ptype, 0) + 1
    return out


def short_type(name):
    """'Cable Tray: BHE_Ladder' reads 'BHE_Ladder' on a heading that is all
    cable tray; a conduit keeps its word so the two cannot be confused."""
    text = u"{0}".format(name or u"")
    if text.startswith(u"Cable Tray: "):
        return text[len(u"Cable Tray: "):]
    return text


def type_summary(counts):
    """{type: n} -> ('3 types: A x12 \u00b7 B x3 \u00b7 C x1', more than one type)."""
    items = sorted((counts or {}).items(), key=lambda kv: (-kv[1], natural_key(kv[0])))
    if not items:
        return u"", False
    parts = [u"{0} \u00d7{1}".format(short_type(k), v) for k, v in items]
    if len(items) == 1:
        return u"Type: " + parts[0], False
    return u"{0} types: {1}".format(len(items), u" \u00b7 ".join(parts)), True


def multi_type_groups(by_group):
    return set([g for g, counts in (by_group or {}).items() if len(counts) > 1])


# ============================================================
# resize: the fittings between the trays
# ============================================================

# A fitting's size is set through its own parameters, named for the
# dimension - never through its connectors. In cable tray fitting families a
# connector's "Height" is often tied to the tray's width (the connector is
# drawn turned round in the family), and sizing through it put a new height
# on the fittings' width.
SIZE_WORDS = {u"width": (u"width",), u"height": (u"height", u"depth"),
              u"diameter": (u"diameter",)}
# names that carry a size word but are not the tray's size
SIZE_EXCLUDE = (u"offset", u"elevation", u"level", u"radius", u"length", u"angle",
                u"thickness", u"flange", u"extension", u"clearance", u"bend", u"slope",
                u"rise", u"insulation", u"lining", u"spacing", u"cover")


def size_param_names(params, dim):
    """params: [(name, value mm, writable)] -> the writable names that are the
    fitting's own parameter for that dimension ("Tray Height", "Height 1"),
    never an offset, a bend radius or a length."""
    out = []
    for name, value, writable in params or []:
        if not writable or value is None:
            continue
        low = (name or u"").lower()
        if not [w for w in SIZE_WORDS.get(dim, ()) if w in low]:
            continue
        if [x for x in SIZE_EXCLUDE if x in low]:
            continue
        out.append(name)
    return out


def fitting_size_targets(trays, tolerance=0.5):
    """trays: [{"width": mm, "height": mm, "diameter": mm}] joined to a fitting
    -> {dimension: mm} for each dimension every joined tray agrees on. Where
    they differ - a reducer, a tee onto a narrower branch - that dimension is
    the family's business and is left alone."""
    out = {}
    for dim in (u"width", u"height", u"diameter"):
        values = [t.get(dim) for t in trays or [] if t.get(dim) is not None]
        if not values:
            continue
        if max(values) - min(values) <= tolerance:
            out[dim] = values[0]
    return out


def fitting_param_plan(params, targets, tolerance=0.5):
    """params: [(name, value mm, writable)], targets: {dimension: mm}
    -> ([(name, new mm)] still to set, [dimensions with no parameter to set])."""
    values = dict((name, value) for name, value, _w in params or [])
    todo = []
    missing = []
    for dim, mm in sorted((targets or {}).items()):
        names = size_param_names(params, dim)
        if not names:
            missing.append(dim)
            continue
        for name in names:
            if abs(values[name] - mm) > tolerance:
                todo.append((name, mm))
    return todo, missing


# ============================================================
# isolating one system after another
# ============================================================

def views_to_reset(target_id, previous_id):
    """The views a new isolate resets: the one it isolates in, and the one the
    last isolate went into if that was another - so checking system after
    system never leaves an old isolate standing in a view out of sight."""
    out = []
    for number in (target_id, previous_id):
        try:
            number = int(number or 0)
        except Exception:
            number = 0
        if number and number not in out:
            out.append(number)
    return out


def leftovers(visible, wanted):
    """Pipework, ductwork or containment still showing in the view that is not
    part of the new isolate - what an old isolate left behind."""
    wanted = set(wanted or [])
    return sorted([n for n in (visible or []) if n not in wanted])


# ============================================================
# default sort per tab
# ============================================================

def default_sort(domain):
    """How a service type's rows are sorted until the user picks: containment
    by type, then run - the types used are what a containment check is about;
    everything else by system."""
    if domain == u"cont":
        return [(u"ptype", False), (u"system", False)]
    return [(u"system", False)]


def sort_place(stack, field):
    """(level, descending) of a field in the sort, or None."""
    for index, (existing, descending) in enumerate(stack or []):
        if existing == field:
            return index, descending
    return None


# ============================================================
# a colour per type
# ============================================================

TYPE_COLOURS = 10       # brushes Type0 .. Type9 in both palettes


def type_colours(names, count=TYPE_COLOURS):
    """{type name: colour index}. Handed out in natural name order across all
    of a tab's types, so a type keeps its colour through refreshes, filters
    and whichever service type it turns up in; past ten they repeat."""
    ordered = sorted(set([n for n in names or [] if n]), key=natural_key)
    return dict((name, index % count) for index, name in enumerate(ordered))


def summary_parts(counts, colours):
    """{type: n}, {type: colour index} -> [(text, colour index or None)]:
    the service heading's type list, each type in its own colour."""
    items = sorted((counts or {}).items(), key=lambda kv: (-kv[1], natural_key(kv[0])))
    if not items:
        return []
    parts = [(u"{0} types: ".format(len(items)) if len(items) > 1 else u"Type: ", None)]
    for index, (name, n) in enumerate(items):
        if index:
            parts.append((u" \u00b7 ", None))
        parts.append((short_type(name), (colours or {}).get(name)))
        parts.append((u" \u00d7{0}".format(n), None))
    return parts


# ============================================================
# waiting on Revit
# ============================================================

BUSY_TIMEOUT_S = 20.0


def busy_expired(started, now, limit=BUSY_TIMEOUT_S):
    """Whether a request Revit has not run yet has waited long enough that the
    window should be freed. Revit runs a request when it is idle; one it has
    not got to must never leave the window frozen until a restart."""
    if not started:
        return False
    return (now - started) >= limit


# ============================================================
# Pick System
# ============================================================

KIND_DOMAIN = {u"pipe": u"pipe", u"duct": u"duct", u"tray": u"cont", u"conduit": u"cont"}


def picked_system_ids(records, picked, group_by=u"system_type"):
    """records of a tab, picked: the ids of the element picked or, for a
    fitting, the trays / pipes / ducts joined to it. -> every id on the same
    system (System No or Run) in the same service type, so the whole system
    is selected however its rows are split. [] if none of them was read."""
    picked = set(picked or [])
    wanted = set()
    for record in records or []:
        if record.get(u"id") in picked:
            wanted.add((group_label(record, group_by), record.get(u"system")))
    if not wanted:
        return []
    return sorted([r[u"id"] for r in records
                   if (group_label(r, group_by), r.get(u"system")) in wanted])


# ============================================================
# System No folds
# ============================================================

def nest_by_system(rows):
    """[(System No, rows)] in natural order - a service type's rows split into
    one fold per system number."""
    by = {}
    for row in rows or []:
        by.setdefault(row.get(u"system") or u"", []).append(row)
    return [(name, by[name]) for name in sorted(by, key=natural_key)]


def nested_name(service, system):
    return u"{0} \u00b7 {1}".format(service, system or UNASSIGNED)


# ============================================================
# Re-apply Type
# ============================================================

def reapply_plan(fittings, selected):
    """fittings: {fitting id: [(pipe id, pipe type id)]} - what each fitting on
    the selection joins. -> ({fitting id: type id to re-apply},
    {"not_selected": n, "mixed_types": n}). A fitting is re-applied only when
    every pipe it joins is selected and on the same type - a fitting between a
    selected pipe and one left alone, or between two types, is not touched."""
    selected = set(selected or [])
    plan = {}
    left = {u"not_selected": 0, u"mixed_types": 0}
    for fid, joined in (fittings or {}).items():
        if not joined:
            continue
        if [p for p, _t in joined if p not in selected]:
            left[u"not_selected"] += 1
            continue
        types = set([t for _p, t in joined])
        if len(types) != 1:
            left[u"mixed_types"] += 1
            continue
        plan[fid] = types.pop()
    return plan, left


# ============================================================
# linked models
# ============================================================

def pick_allowed(is_link, in_link, on_system, lookup_linked):
    """Whether Pick System may take what the cursor is over.
    is_link: the whole linked model (a link instance); in_link: an element
    inside a linked model; on_system: a pipe, duct, tray, conduit, fitting or
    accessory. With linked lookup off (the default) nothing from a linked
    model is taken; with it on, a link may be clicked to pick inside it."""
    if is_link:
        return bool(lookup_linked)
    if in_link:
        return bool(lookup_linked) and bool(on_system)
    return bool(on_system)


# ============================================================
# Change Pipe Type: the size mapping
# ============================================================

SIZE_SORTS = ((u"size", u"Size"), (u"type", u"Current type"), (u"count", u"Count"))


def size_rows(records):
    """The selected pipes as rows of the mapping table, one per current type
    and size: [{key, type, size, count, ids}]."""
    by = {}
    for record in records or []:
        size = record.get(u"size_mm")
        if size is None:
            continue
        size = round(float(size), 1)
        key = (record.get(u"ptype") or u"", size)
        row = by.setdefault(key, {u"key": key, u"type": key[0], u"size": size,
                                  u"count": 0, u"ids": []})
        row[u"count"] += 1
        row[u"ids"].append(record[u"id"])
    return sort_size_rows(list(by.values()), u"size")


def sort_size_rows(rows, key=u"size"):
    """Grouped together by size (the default), or by current type, or by how
    many pipes - largest first."""
    if key == u"type":
        return sorted(rows, key=lambda r: (natural_key(r[u"type"]), r[u"size"]))
    if key == u"count":
        return sorted(rows, key=lambda r: (-r[u"count"], r[u"size"], natural_key(r[u"type"])))
    return sorted(rows, key=lambda r: (r[u"size"], natural_key(r[u"type"])))


def size_colours(rows, count=TYPE_COLOURS):
    """{size: colour index} - each different size its own colour."""
    sizes = sorted(set([r[u"size"] for r in rows or []]))
    return dict((size, index % count) for index, size in enumerate(sizes))


def default_target(size, available):
    """The size a pipe goes to on the new type unless changed: the same size
    if the new type offers it, else the next size up, else the largest
    offered. None when the new type's sizes could not be read."""
    available = sorted(set([round(float(a), 1) for a in available or []]))
    if not available:
        return None
    for value in available:
        if abs(value - size) <= 0.5:
            return value
    for value in available:
        if value > size:
            return value
    return available[-1]


def size_map_from(rows, choices):
    """rows as size_rows made them, choices: {row key: target mm or None}
    -> {pipe id: target mm}. A row with no choice keeps its size."""
    out = {}
    for row in rows or []:
        target = (choices or {}).get(row[u"key"])
        for number in row[u"ids"]:
            out[number] = target if target is not None else row[u"size"]
    return out


def mapping_summary(rows, choices, target_type):
    """Lines for the confirm: 'Copper 22 x12 -> MLCP 25'."""
    lines = []
    for row in rows or []:
        target = (choices or {}).get(row[u"key"])
        lines.append(u"{0} {1} \u00d7{2}  \u2192  {3} {4}".format(
            row[u"type"], format_size(row[u"size"]), row[u"count"], target_type,
            format_size(target if target is not None else row[u"size"])))
    return lines


# ============================================================
# groups
# ============================================================

def group_decision(nested, held_by=u""):
    """Whether pipes in a group can be changed as Edit Group would. Every copy
    of the group type is updated, so any copy somebody else holds stops the
    whole group - changing some copies and not others would split it."""
    if nested:
        return False, u"it is in a group nested inside another group"
    if held_by:
        return False, (u"a copy of its group is held by {0} - every copy has to be "
                       u"updated together").format(held_by)
    return True, u""


# ---------------- where a group's members sit ----------------
# Points are (x, y, z); rotations radians about Z, as Revit's LocationPoint.

def rot_z(point, angle):
    c, s = math.cos(angle), math.sin(angle)
    x, y, z = point
    return (x * c - y * s, x * s + y * c, z)


def sub3(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def add3(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def dist3(a, b):
    d = sub3(a, b)
    return math.sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2])


def to_local(point, origin, rotation):
    """A point in a group copy's own frame - the same for the same member of
    every copy, however the copy is placed and turned."""
    return rot_z(sub3(point, origin), -rotation)


def centroid(points):
    points = [p for p in points or [] if p is not None]
    if not points:
        return None
    n = float(len(points))
    return (sum([p[0] for p in points]) / n, sum([p[1] for p in points]) / n,
            sum([p[2] for p in points]) / n)


def _angle_xy(point):
    return math.atan2(point[1], point[0])


def local_frame(points):
    """A frame taken from the elements themselves - their centre, and the
    direction of the one furthest from it. The same members give the same
    frame in every copy of a group, however it is placed or turned, so
    nothing depends on a group's origin (a group whose location cannot be
    read used to break the maths outright). (centre, angle) or (None, 0)."""
    middle = centroid(points)
    if middle is None:
        return None, 0.0
    furthest, best = None, -1.0
    for point in points:
        offset = sub3(point, middle)
        d = offset[0] * offset[0] + offset[1] * offset[1]
        if d > best:
            furthest, best = offset, d
    if furthest is None or best < 1e-12:
        return middle, 0.0
    return middle, _angle_xy(furthest)


def align_transform(old_points, new_points):
    """The copy has been swapped to the rebuilt group type, so its members
    have moved. -> (turn, about this point, then move by) that puts them back
    where they were, from where they were and where they are now. None when
    there is nothing to line up on."""
    old_centre, old_angle = local_frame(old_points)
    new_centre, new_angle = local_frame(new_points)
    if old_centre is None or new_centre is None:
        return None
    turn = old_angle - new_angle
    moved_centre = new_centre                      # rotation is about the centre itself
    move = sub3(old_centre, moved_centre)
    return turn, new_centre, move


def apply_alignment(point, turn, about, move):
    """Where a point ends up under that alignment - what the bench checks."""
    return add3(add3(rot_z(sub3(point, about), turn), about), move)

def counterpart(local, candidates, tolerance):
    """The member of the edited copy sitting where this pipe sits in its own
    copy: {id: local point} -> id, or None."""
    best, best_d = None, None
    for number, point in (candidates or {}).items():
        d = dist3(local, point)
        if d <= tolerance and (best_d is None or d < best_d):
            best, best_d = number, d
    return best


def bbox_moved(before, after, tolerance):
    """A copy's extents before and after the swap: ((min), (max)) pairs.
    True if either corner moved further than tolerance - the copy is not
    where it was."""
    if not before or not after:
        return False
    return dist3(before[0], after[0]) > tolerance or dist3(before[1], after[1]) > tolerance


# ============================================================
# selecting across groups
# ============================================================

def groups_to_clear(selected, active, ctrl):
    """selected: [how many rows each group has selected], active: the group
    just clicked in. -> the groups whose selection goes. A plain click keeps
    only the group clicked in, as Windows does; Ctrl adds to what is there."""
    if ctrl:
        return []
    return [i for i, count in enumerate(selected or []) if i != active and count]


# ============================================================
# reporting a traceback
# ============================================================

def error_rows(text, keep=4):
    """A traceback as rows for the debug table: the message first, then the
    last few frames as "file line - code". One long cell is cut off by the
    table and says nothing."""
    lines = [l.rstrip() for l in u"{0}".format(text or u"").splitlines() if l.strip()]
    if not lines:
        return []
    rows = [(u"message", lines[-1])]
    frames = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if line.startswith(u"File "):
            where = line
            code = u""
            if index + 1 < len(lines) and not lines[index + 1].strip().startswith(u"File "):
                code = lines[index + 1].strip()
            parts = where.split(u'"')
            name = parts[1].replace(u"\\", u"/").split(u"/")[-1] if len(parts) > 2 else where
            tail = where.split(u",", 1)[1].strip() if u"," in where else u""
            frames.append((u"at", u"{0} {1} - {2}".format(name, tail, code).strip()))
            index += 2
            continue
        index += 1
    return rows + frames[-keep:]


# ============================================================
# pipe accessories on a resized system
# ============================================================

ACCESSORY_SIZE_WORDS = (u"diameter", u"size", u"dn", u"nominal", u"bore")


def accessory_size_plan(params, old_mm, new_mm, tolerance=0.5):
    """params: [(name, value mm, writable, instance)] of a valve, strainer or
    other accessory joined to a pipe that has changed size.
    -> ([(name, new mm)] to set, [why a size was left]).

    Only an instance parameter is set: a diameter driven by the type belongs
    to every accessory of that type, so changing it would resize accessories
    nobody asked about. The parameter must be named for the size and hold the
    old size now, which keeps an offset or a length out of it."""
    todo = []
    left = []
    for name, value, writable, instance in params or []:
        if value is None:
            continue
        low = (name or u"").lower()
        if not [w for w in ACCESSORY_SIZE_WORDS if w in low]:
            continue
        if [x for x in SIZE_EXCLUDE if x in low]:
            continue
        if abs(value - old_mm) > tolerance:
            continue
        if not instance:
            left.append(u"{0} is driven by the type".format(name))
            continue
        if not writable:
            left.append(u"{0} cannot be written".format(name))
            continue
        todo.append((name, new_mm))
    return todo, left


# ============================================================
# rebuilding a group after the change
# ============================================================

def group_members_now(members, alive, replacements):
    """What goes back into the rebuilt group: the members still in the model,
    plus what Revit put in place of the ones it deleted. Changing a pipe's
    type makes Revit delete and recreate fittings, so the list a group was
    opened with is not the list it closes with - the deleted ids would stop
    the rebuild outright, and the new elements would be left loose."""
    out = [n for n in members or [] if n in set(alive or [])]
    for number in replacements or []:
        if number not in out:
            out.append(number)
    return out


# ============================================================
# how the fittings are changed
# ============================================================

FITTING_MODES = (
    (u"size_second", u"Type and fittings first, sizes after"),
    (u"together", u"Type, size and fittings in one step"),
    (u"reapply", u"Revit's Reapply Type, after the pipes"),
    (u"after", u"After the pipes, one fitting at a time"),
)


def accessory_named_plan(params, names, new_mm):
    """The accessory size parameters named in Settings (BGL_Diameter and any
    others) -> ([(name, new mm)] to set, [why one was left]). Named outright,
    so the value it holds now does not have to match the pipe's old size -
    but it still has to be an instance parameter, since a type-driven one
    belongs to every accessory of that type."""
    wanted = [n.lower() for n in names or []]
    todo = []
    left = []
    for name, _value, writable, instance in params or []:
        if (name or u"").lower() not in wanted:
            continue
        if not instance:
            left.append(u"{0} is driven by the type".format(name))
            continue
        if not writable:
            left.append(u"{0} cannot be written".format(name))
            continue
        todo.append((name, new_mm))
    return todo, left


def pipes_to_resize(before, size_map, tolerance=0.5):
    """The pipes whose size actually has to change in the second pass -
    before: {pipe id: (type name, size mm)} as they were."""
    out = []
    for number, target in sorted((size_map or {}).items()):
        was = (before or {}).get(number, (u"", None))[1]
        if was is None or abs(was - target) > tolerance:
            out.append(number)
    return out


def failure_text(errors, warnings, status):
    """What Revit said when it refused, rather than "rolled it back": its own
    message, and the hint for it where there is one."""
    said = [t for t, _ids in (errors or [])] or [t for t, _ids in (warnings or [])]
    unique = []
    for text in said:
        if text and text not in unique:
            unique.append(text)
    if not unique:
        return u"Revit rolled it back ({0}) without saying why".format(status)
    hint = explain_failure(unique[0])
    out = u"Revit refused: {0}".format(u"; ".join(unique)[:300])
    return out + (u" - " + hint if hint else u"")


def still_wrong_size(sizes, size_map, tolerance=0.5):
    """After the size pass: the pipes not at the size they were meant to
    reach. sizes: {pipe id: size now in mm}. A pipe refused while its
    neighbours were still at the old size often takes it once they have
    moved, so these get one more go at the end."""
    out = []
    for number, target in sorted((size_map or {}).items()):
        now = (sizes or {}).get(number)
        if now is not None and abs(now - target) > tolerance:
            out.append(number)
    return out


def unique_reasons(lines):
    """The same refusal reported once. A pipe tried again at the end fails the
    same way, and every attempt was being written down - the log read as two
    identical paragraphs."""
    out = []
    for line in lines or []:
        text = u"{0}".format(line).strip()
        if text and text not in out:
            out.append(text)
    return out


def length_note(feet):
    """A refused pipe's length, so what has to be lengthened is in the log."""
    if feet is None:
        return u""
    return u" (this pipe is {0} long)".format(format_size(feet_to_mm(feet)))


# a refusal the pipe's neighbours moving cannot change
HOPELESS = (u"line is too short",)


def retry_candidates(numbers, failed_lines):
    """Of the pipes still at the wrong size, the ones worth one more go once
    their neighbours have moved. A pipe Revit called too short stays too
    short, and trying it again only repeats the warning."""
    said = {}
    for line in failed_lines or []:
        head = u"{0}".format(line).split(u" - ", 1)
        if len(head) == 2 and head[0].strip().isdigit():
            said.setdefault(int(head[0]), []).append(head[1].lower())
    out = []
    for number in numbers or []:
        texts = u" ".join(said.get(number, []))
        if [word for word in HOPELESS if word in texts]:
            continue
        out.append(number)
    return out


# ============================================================
# shrink to the taskbar: the drawer's arithmetic
# ============================================================

DRAWER_MS = 280.0      # one slide, either way
DRAWER_TICK_MS = 15    # frame interval
DRAWER_CLEAR = 8.0     # the parked bar floats this far above the taskbar
DRAWER_GAP = 4.0       # between stacked bars
DRAWER_MOVED = 2.0     # a bar dragged further than this has been moved


def ease_out(progress):
    """Cubic ease out, clamped: fast away, settling gently."""
    p = min(1.0, max(0.0, float(progress)))
    return 1.0 - (1.0 - p) ** 3


def slide_value(start, end, progress):
    return start + (end - start) * ease_out(progress)


def slide_progress(started, now, length=DRAWER_MS):
    if length <= 0:
        return 1.0
    return min(1.0, max(0.0, (now - started) / float(length)))


def bar_height(frame_top, header_height):
    """The parked window's height: its header plus the frame above and below
    it (the rounded border is drawn the same on both sides)."""
    frame = max(0.0, float(frame_top or 0.0))
    return max(1.0, float(header_height or 0.0) + 2.0 * frame)


def parked_top(area_top, area_height, bar, below=0.0):
    """Where a bar parks: floating DRAWER_CLEAR above the bottom of the
    working area, stacked above `below` (the height already taken by bars
    parked first). A monitor above the primary has a negative top - that is
    the working area's own top, never zero."""
    top = area_top + area_height - DRAWER_CLEAR - bar - below
    return max(area_top, top)


def stacked_below(bars):
    """Height taken by bars already parked: each bar plus a gap."""
    return sum(float(b) + DRAWER_GAP for b in bars or [])


def bar_moved(parked_at, bar_at):
    """parked_at / bar_at are (left, top). Has the user dragged the bar?"""
    if parked_at is None or bar_at is None:
        return False
    return (abs(parked_at[0] - bar_at[0]) > DRAWER_MOVED or
            abs(parked_at[1] - bar_at[1]) > DRAWER_MOVED)


def reopen_bounds(saved, parked_at, bar_at, bar, area):
    """Where a parked window opens to: (left, top). saved is the window's
    (left, top, width, height) before it parked; area is the working area
    (left, top, width, height) of the screen the bar is on now.

    Left where it parked, it goes back exactly where it was. Carried
    somewhere else, it opens upward from where the bar now sits - its bottom
    edge on the bar's - kept on that screen."""
    left, top, width, height = saved
    if not bar_moved(parked_at, bar_at):
        return left, top
    a_left, a_top, a_width, a_height = area
    new_top = bar_at[1] + bar - height
    new_top = min(new_top, a_top + a_height - height)
    new_top = max(new_top, a_top)
    new_left = min(bar_at[0], a_left + a_width - width)
    new_left = max(new_left, a_left)
    return new_left, new_top
