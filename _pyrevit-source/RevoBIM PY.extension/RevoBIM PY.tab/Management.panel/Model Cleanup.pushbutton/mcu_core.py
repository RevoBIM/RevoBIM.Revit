# -*- coding: utf-8 -*-
"""Model Cleanup - version, settings, templates and every rule that decides
something.

Nothing in this module touches Revit or WPF, so every rule in it runs under
plain CPython on the bench (bench_logic.py). Anything that decides which
elements go, in what order, and when a step may run lives here.
"""
import io
import os
import re
import datetime
import time
import traceback

__version__ = u"2.0.0"

TOOL_NAME = u"Model Cleanup"
RIBBON_NAME = u"Model Cleanup"

SETTINGS_VERSION = 2
# settings_version -> keys whose meaning changed in that version and must be
# reset to the default rather than read.
MIGRATIONS = {
    # 1.4.0: the purge runs 4 passes after the sheets and views have gone
    2: [u"purge_passes"],
}


# ============================================================
# paths and logging
# ============================================================

def appdata_dir():
    base = os.environ.get(u"APPDATA") or os.path.expanduser(u"~")
    path = os.path.join(base, u"RevoBIM")
    try:
        if not os.path.isdir(path):
            os.makedirs(path)
    except Exception:
        pass
    return path


def settings_path():
    return os.path.join(appdata_dir(), u"model_cleanup.txt")


def templates_dir():
    path = os.path.join(appdata_dir(), u"model_cleanup_templates")
    try:
        if not os.path.isdir(path):
            os.makedirs(path)
    except Exception:
        pass
    return path


def log_path():
    return os.path.join(appdata_dir(), u"model_cleanup_debug.txt")


def error_path():
    return os.path.join(appdata_dir(), u"model_cleanup_last_error.txt")


def to_text(value):
    if value is None:
        return u""
    try:
        if isinstance(value, bytes):
            return value.decode(u"utf-8", u"replace")
    except Exception:
        pass
    try:
        return u"{0}".format(value)
    except Exception:
        try:
            return unicode(value)  # noqa: F821 - IronPython 2.7 only
        except Exception:
            return u""


def log(message):
    try:
        stamp = datetime.datetime.now().strftime(u"%Y-%m-%d %H:%M:%S")
        with io.open(log_path(), u"a", encoding=u"utf-8") as handle:
            handle.write(u"{0}  {1}\n".format(stamp, to_text(message)))
    except Exception:
        pass


def write_error(stage, text):
    try:
        with io.open(error_path(), u"w", encoding=u"utf-8") as handle:
            handle.write(u"RevoBIM {0} {1}\nStage: {2}\n\n{3}\n".format(
                TOOL_NAME, __version__, to_text(stage), to_text(text)))
    except Exception:
        pass
    log(u"ERROR in {0}: {1}".format(stage, text))


def format_exception():
    try:
        return to_text(traceback.format_exc())
    except Exception:
        return u"(no traceback)"


# ============================================================
# key=value files
# ============================================================

def read_kv(path):
    """Split on the first '=' only, so a value may itself contain '='."""
    out = {}
    try:
        if not os.path.isfile(path):
            return out
        with io.open(path, u"r", encoding=u"utf-8") as handle:
            text = handle.read()
    except Exception:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(u"#") or u"=" not in line:
            continue
        key, value = line.split(u"=", 1)
        out[key.strip()] = value.strip()
    return out


def write_kv(path, pairs, header=None):
    lines = []
    if header:
        lines.append(u"# " + to_text(header))
    for key, value in pairs:
        lines.append(u"{0}={1}".format(key, to_text(value).replace(u"\n", u" ")))
    data = u"\n".join(lines) + u"\n"
    try:
        with io.open(path, u"w", encoding=u"utf-8") as handle:
            handle.write(data)
        return True
    except Exception:
        log(u"could not write " + to_text(path))
        return False


def as_bool(value, default=False):
    text = to_text(value).strip().lower()
    if text in (u"1", u"true", u"yes", u"on"):
        return True
    if text in (u"0", u"false", u"no", u"off"):
        return False
    return default


def as_int(value, default, low=None, high=None):
    try:
        number = int(float(to_text(value).strip()))
    except Exception:
        return default
    if low is not None and number < low:
        number = low
    if high is not None and number > high:
        number = high
    return number


def bool_text(flag):
    return u"1" if flag else u"0"


def split_list(text):
    return [part.strip() for part in to_text(text).split(u"|") if part.strip()]


def join_list(items):
    seen = []
    for item in items:
        item = to_text(item).strip().replace(u"|", u"/")
        if item and item not in seen:
            seen.append(item)
    return u"|".join(seen)


def split_words(text):
    return [part.strip() for part in re.split(u"[;,]", to_text(text)) if part.strip()]


# ============================================================
# global settings
# ============================================================

GLOBAL_DEFAULTS = [
    (u"settings_version", u"{0}".format(SETTINGS_VERSION)),
    (u"theme_mode", u"auto"),
    (u"last_template", u"Standard Issue"),
    (u"last_folder", u""),
    (u"debug", u"0"),
    (u"template_folder", u""),
    # publish to ACC - one APS app per person or office, not per template
    (u"aps_client_id", u""),
    (u"aps_port", u"8765"),
]


def load_global():
    raw = read_kv(settings_path())
    return merge_defaults(raw, GLOBAL_DEFAULTS)


def save_global(values):
    pairs = []
    for key, default in GLOBAL_DEFAULTS:
        pairs.append((key, values.get(key, default)))
    pairs[0] = (u"settings_version", u"{0}".format(SETTINGS_VERSION))
    return write_kv(settings_path(), pairs, u"Model Cleanup settings")


def merge_defaults(raw, defaults):
    """Defaults key by key; unknown keys dropped; migrated keys reset."""
    out = {}
    saved_version = as_int(raw.get(u"settings_version", u"0"), 0)
    reset = set()
    for version, keys in MIGRATIONS.items():
        if saved_version < version:
            reset.update(keys)
    for key, default in defaults:
        if key in raw and key not in reset:
            out[key] = raw[key]
        else:
            out[key] = default
    return out


# ============================================================
# export settings templates
# ============================================================

DETACH_PRESERVE = u"preserve"
DETACH_DISCARD = u"discard"

TEMPLATE_DEFAULTS = [
    (u"settings_version", u"{0}".format(SETTINGS_VERSION)),
    # detach and save
    (u"detach_mode", DETACH_PRESERVE),
    (u"audit", u"0"),
    (u"sync_comment", u"Model Cleanup - synced before issue"),
    (u"relinquish", u"1"),
    (u"compact", u"1"),
    (u"add_suffix", u"1"),
    (u"file_suffix", u"_Issue"),
    (u"add_date", u"1"),
    (u"open_when_done", u"1"),
    # publish to ACC after the sync
    (u"offer_publish", u"1"),
    (u"publish_links", u"ask"),
    # clean up
    (u"remove_revit_links", u"1"),
    (u"remove_cad", u"1"),
    (u"remove_point_clouds", u"1"),
    (u"delete_unplaced_images", u"1"),
    (u"delete_views_off_sheet", u"1"),
    (u"delete_schedules_off_sheet", u"1"),
    (u"delete_legends_off_sheet", u"0"),
    (u"delete_unused_templates", u"1"),
    (u"delete_unused_filters", u"1"),
    (u"keep_view_words", u"KEEP;Starting"),
    (u"delete_sheets_not_retained", u"0"),
    (u"retain_views", u""),
    (u"retain_sheets", u""),
    # purge
    (u"purge", u"1"),
    (u"purge_passes", u"4"),
    (u"purge_exclude", u""),
    (u"show_used", u"0"),
]

# NWC export - (template key, NavisworksExportOptions property, label, default)
NWC_BOOL_OPTIONS = [
    (u"nwc_links", u"ExportLinks", u"Export Revit links", u"0"),
    (u"nwc_properties", u"ConvertElementProperties", u"Convert element properties", u"1"),
    (u"nwc_levels", u"DivideFileIntoLevels", u"Divide file into levels", u"1"),
    (u"nwc_ids", u"ExportElementIds", u"Export element IDs", u"1"),
    (u"nwc_parts", u"ExportParts", u"Export parts", u"0"),
    (u"nwc_room_attr", u"ExportRoomAsAttribute", u"Export room as attribute", u"0"),
    (u"nwc_room_geo", u"ExportRoomGeometry", u"Export room geometry", u"0"),
    (u"nwc_urls", u"ExportUrls", u"Export URLs", u"1"),
    (u"nwc_materials", u"FindMissingMaterials", u"Try to find missing materials", u"1"),
    (u"nwc_lights", u"ConvertLights", u"Convert lights", u"0"),
    (u"nwc_linked_cad", u"ConvertLinkedCADFormats", u"Convert linked CAD files", u"0"),
]

TEMPLATE_DEFAULTS += [
    (u"export_nwc", u"0"),
    (u"nwc_source", u"custom"),
    (u"nwc_coordinates", u"shared"),
    (u"nwc_parameters", u"all"),
    (u"nwc_faceting", u"1"),
] + [(key, default) for key, _, _, default in NWC_BOOL_OPTIONS] + [
    (u"nwc_views", u""),
    (u"nwc_primary", u""),
]

TEMPLATE_KEYS = [key for key, _ in TEMPLATE_DEFAULTS]

# (key, label) - the order the clean up runs in and the order it is listed.
# The NWC export runs before anything is removed. Then sheets and views go,
# so everything they alone were using is free for the links, templates,
# filters and the purge passes that follow.
CLEANUP_OPS = [
    (u"export_nwc", u"Export NWC first"),
    (u"delete_sheets_not_retained", u"Delete sheets not retained"),
    (u"delete_views_off_sheet", u"Delete views not retained or placed"),
    (u"delete_schedules_off_sheet", u"Delete schedules not retained or placed"),
    (u"delete_legends_off_sheet", u"Delete legends not retained or placed"),
    (u"delete_unplaced_images", u"Delete raster images that are not placed"),
    (u"remove_revit_links", u"Remove Revit links"),
    (u"remove_cad", u"Remove CAD links and imports"),
    (u"remove_point_clouds", u"Remove point clouds"),
    (u"delete_unused_templates", u"Delete unused view templates"),
    (u"delete_unused_filters", u"Delete unused view filters"),
    (u"purge", u"Purge unused elements"),
]

SEED_TEMPLATES = [
    (u"Standard Issue", {}),
    (u"Keep Links", {u"remove_revit_links": u"0", u"remove_cad": u"0",
                     u"remove_point_clouds": u"0"}),
    (u"Purge Only", {u"remove_revit_links": u"0", u"remove_cad": u"0",
                     u"remove_point_clouds": u"0",
                     u"delete_views_off_sheet": u"0",
                     u"delete_sheets_not_retained": u"0",
                     u"delete_schedules_off_sheet": u"0",
                     u"delete_unused_templates": u"0",
                     u"delete_unused_filters": u"0",
                     u"file_suffix": u"_Purged"}),
]

_BAD_NAME_CHARS = u'\\/:*?"<>|'


def sanitize_name(name):
    text = to_text(name)
    for ch in _BAD_NAME_CHARS:
        text = text.replace(ch, u" ")
    text = re.sub(u"\\s+", u" ", text).strip().strip(u".")
    return text[:80]


def template_path(name, folder=None):
    return os.path.join(folder or templates_dir(), sanitize_name(name) + u".txt")


def default_template():
    return dict(TEMPLATE_DEFAULTS)


def seed_templates(folder=None):
    folder = folder or templates_dir()
    written = []
    for name, overrides in SEED_TEMPLATES:
        values = default_template()
        values.update(overrides)
        if save_template(name, values, folder):
            written.append(name)
    return written


def list_templates(folder=None):
    folder = folder or templates_dir()
    names = []
    try:
        for entry in os.listdir(folder):
            if entry.lower().endswith(u".txt"):
                names.append(entry[:-4])
    except Exception:
        pass
    if not names:
        seed_templates(folder)
        names = [name for name, _ in SEED_TEMPLATES]
    return sorted(set(names), key=lambda n: n.lower())


RENAMED_DEFAULTS = {
    # 1.2.1 renamed the tool; a comment saved under the old name is refreshed
    u"sync_comment": (u"RevoBIM Model Cleanup - synced before issue",),
}


def upgrade_template(raw, values):
    """Carry settings that have been renamed or folded into another one
    across, after the defaults have been merged in. raw is the file as read."""
    defaults = dict(TEMPLATE_DEFAULTS)
    for key, old_values in RENAMED_DEFAULTS.items():
        if values.get(key) in old_values:
            values[key] = defaults[key]
    # 2.0.0: "Remove all raster images, placed or not" became "remove only the
    # ones not placed". A template that asked for the old one still gets its
    # unplaced images removed rather than quietly losing the stage.
    if as_bool(raw.get(u"remove_images"), False):
        values[u"delete_unplaced_images"] = u"1"
    return values


def load_template(name, folder=None):
    raw = read_kv(template_path(name, folder))
    return upgrade_template(raw, merge_defaults(raw, TEMPLATE_DEFAULTS))


def save_template(name, values, folder=None):
    name = sanitize_name(name)
    if not name:
        return False
    pairs = []
    for key, default in TEMPLATE_DEFAULTS:
        pairs.append((key, values.get(key, default)))
    pairs[0] = (u"settings_version", u"{0}".format(SETTINGS_VERSION))
    return write_kv(template_path(name, folder), pairs,
                    u"Model Cleanup export settings: " + name)


def delete_template(name, folder=None):
    """Never deletes the last template - the dropdown must never be empty."""
    names = list_templates(folder)
    if len(names) <= 1:
        return False, u"The last template cannot be deleted."
    path = template_path(name, folder)
    try:
        os.remove(path)
        return True, u""
    except Exception as error:
        return False, to_text(error)


# ============================================================
# sharing a template as a file
# ============================================================

EXPORT_PREFIX = u"Model Cleanup Template"
EXPORT_MARKER = u"model_cleanup_template"


def export_file_name(template_name):
    name = sanitize_name(template_name)
    if not name:
        return EXPORT_PREFIX + u".txt"
    return u"{0} - {1}.txt".format(EXPORT_PREFIX, name)


def name_from_file(path):
    stem = to_text(path).replace(u"\\", u"/").rstrip(u"/").split(u"/")[-1]
    if stem.lower().endswith(u".txt"):
        stem = stem[:-4]
    lower = stem.lower()
    prefix = EXPORT_PREFIX.lower()
    if lower.startswith(prefix):
        stem = stem[len(EXPORT_PREFIX):].lstrip(u" -_")
    return sanitize_name(stem) or EXPORT_PREFIX


def unique_template_name(name, existing):
    name = sanitize_name(name) or EXPORT_PREFIX
    taken = set(to_text(n).lower() for n in existing or [])
    if name.lower() not in taken:
        return name
    number = 2
    while u"{0} ({1})".format(name, number).lower() in taken:
        number += 1
    return u"{0} ({1})".format(name, number)


def export_template(values, template_name, path):
    """Write a template to a file the user picked, in the same key=value
    shape the tool stores, plus its name and a marker so an import can tell
    it apart from any other text file."""
    # the version is stamped, or a reload would migrate the file as if it
    # came from an older release and reset the keys a migration touches
    pairs = [(EXPORT_MARKER, u"{0}".format(SETTINGS_VERSION)),
             (u"template_name", sanitize_name(template_name)),
             (u"settings_version", u"{0}".format(SETTINGS_VERSION))]
    for key, default in TEMPLATE_DEFAULTS:
        if key == u"settings_version":
            continue
        pairs.append((key, values.get(key, default)))
    return write_kv(path, pairs,
                    u"{0}: {1} (exported from Model Cleanup {2})".format(
                        EXPORT_PREFIX, sanitize_name(template_name), __version__))


def import_template(path):
    """(values, suggested name, error). Reads a file this tool exported, or
    a template file copied straight out of the settings folder."""
    raw = read_kv(path)
    if not raw:
        return None, u"", u"That file has nothing in it that Model Cleanup can read."
    known = [key for key, _ in TEMPLATE_DEFAULTS if key in raw]
    if EXPORT_MARKER not in raw and len(known) < 5:
        return None, u"", (u"That does not look like a Model Cleanup settings template. "
                           u"It carries {0} of this tool's settings.".format(len(known)))
    values = upgrade_template(raw, merge_defaults(raw, TEMPLATE_DEFAULTS))
    name = sanitize_name(raw.get(u"template_name")) or name_from_file(path)
    return values, name, u""


def pick_template(names, wanted):
    if wanted in names:
        return wanted
    for name in names:
        if name.lower() == to_text(wanted).lower():
            return name
    return names[0] if names else u""


def enabled_ops(template):
    return [(key, label) for key, label in CLEANUP_OPS
            if as_bool(template.get(key), False)]


# ============================================================
# the three steps
# ============================================================

STEP_SYNC = u"sync"
STEP_SAVE_AS = u"save_as"
STEP_CLEANUP = u"cleanup"


def step_states(synced, saved_as, cleaned, busy, target_alive=True):
    """Which step buttons are lit. Clean Up only lights once the model has
    been synced AND saved as - and never twice on the same copy."""
    ready_sync = not busy
    ready_save = bool(synced) and not busy
    ready_clean = (bool(synced) and bool(saved_as) and bool(target_alive)
                   and not cleaned and not busy)
    return {
        STEP_SYNC: ready_sync,
        STEP_SAVE_AS: ready_save,
        STEP_CLEANUP: ready_clean,
    }


def step_badge(enabled, done, skipped=False):
    if skipped:
        return u"Skipped"
    if done:
        return u"Done"
    if enabled:
        return u"Ready"
    return u"Locked"


CONFIRM_WORD = u"CONFIRM"


def confirm_typed(text):
    """Skipping steps 1 and 2 only goes ahead on the exact word, in capitals.
    Surrounding spaces are forgiven; anything else is not."""
    return to_text(text).strip() == CONFIRM_WORD


def effective_steps(synced, saved_as, skipped):
    """What the gate sees: a confirmed skip stands in for both steps."""
    return (bool(synced) or bool(skipped), bool(saved_as) or bool(skipped))


def can_skip(synced, saved_as, skipped, cleaned, busy):
    """The skip button: only before anything has happened."""
    return not (synced or saved_as or skipped or cleaned or busy)


def skip_warning(info):
    """The warning text, sharpened for what is actually open."""
    lines = [
        u"Skipping steps 1 and 2 cleans THE MODEL THAT IS OPEN NOW. There is no "
        u"detached copy: links, views and purged elements are removed from this "
        u"model.",
        u"",
        u"NEVER do this to a central model, or to a local file you will sync. "
        u"Everything removed here would reach the central, and everyone on the "
        u"project, at the next sync.",
    ]
    if info.get(u"workshared"):
        if info.get(u"central") and same_path(info.get(u"central"), info.get(u"path")):
            lines += [u"", u"WARNING: the open file IS the central model."]
        else:
            lines += [u"", u"WARNING: the open model is workshared and still connected "
                           u"to its central" + (u" on ACC." if info.get(u"cloud") else u".")]
    lines += [
        u"",
        u"Only continue on a model you have already detached or copied yourself. "
        u"The tool will not save or sync afterwards - check the result, then save "
        u"it yourself. Revit's Undo reverses the whole clean up in one step.",
        u"",
        u"Type {0} to skip steps 1 and 2.".format(CONFIRM_WORD),
    ]
    return u"\n".join(lines)


def sync_label(is_workshared):
    if is_workshared:
        return u"Sync Current Model"
    return u"Save Current Model"


# ============================================================
# naming the send copy
# ============================================================

def active_suffix(template):
    """The suffix the file name gets, or nothing when it is switched off."""
    if not as_bool(template.get(u"add_suffix"), True):
        return u""
    return to_text(template.get(u"file_suffix")).strip()


def model_stem(path_or_title):
    text = to_text(path_or_title).replace(u"\\", u"/")
    text = text.rstrip(u"/").split(u"/")[-1]
    if text.lower().endswith(u".rvt"):
        text = text[:-4]
    return text


def send_file_name(source, suffix, add_date, today=None, user_name=None):
    stem = model_stem(source)
    if user_name:
        tail = u"_" + to_text(user_name)
        if stem.lower().endswith(tail.lower()) and len(stem) > len(tail):
            stem = stem[:-len(tail)]
    suffix = to_text(suffix).strip()
    if suffix and not stem.endswith(suffix):
        stem += suffix
    if add_date:
        today = today or datetime.date.today()
        stem += u"_" + today.strftime(u"%Y-%m-%d")
    stem = sanitize_name(stem) or u"Model"
    return stem + u".rvt"


def same_path(first, second):
    def norm(value):
        return os.path.normcase(os.path.normpath(to_text(value).strip()))
    if not to_text(first).strip() or not to_text(second).strip():
        return False
    return norm(first) == norm(second)


ROUTE_DETACHED_OPEN = u"detached_open"   # file-based central: open it detached, save
ROUTE_FILE_COPY = u"file_copy"           # not workshared: copy the file, open it
ROUTE_SAVE_OPEN = u"save_open"           # ACC: Revit cannot detach a cloud model on
                                         # open, so the synced open model is saved
                                         # as the copy (a new local central)


def save_as_route(info):
    if not info.get(u"workshared"):
        return ROUTE_FILE_COPY
    if info.get(u"cloud"):
        return ROUTE_SAVE_OPEN
    return ROUTE_DETACHED_OPEN


def save_as_confirmation(info, target, detach_mode):
    """What step 2 will do, said before it does it."""
    route = save_as_route(info)
    head = u"This saves the DETACHED copy:\n{0}\n\n".format(target)
    tail = (u"\n\nFrom here on, that copy is the detached model - Clean Up, the NWC "
            u"export and Save and close all work on it, never on the live model.")
    if route == ROUTE_SAVE_OPEN:
        body = (u"This model is on ACC. Revit cannot detach a cloud model while opening "
                u"it, so the model open now - just synced - is saved as a new local "
                u"central at that path. That saved file is the detached copy: it has no "
                u"link back to ACC, and the model on ACC is not changed.\n\n"
                u"This window then works in the copy. Worksets are kept.")
        if detach_mode == DETACH_DISCARD:
            body += (u" (The template asks to discard worksets, which is not possible for "
                     u"an ACC model.)")
    elif route == ROUTE_FILE_COPY:
        body = (u"This model is not workshared, so the saved file is copied to that path "
                u"and the copy is opened in the background.")
    else:
        body = (u"The central is opened again in the background, detached ({0} "
                u"worksets), and saved to that path. The model open now is not "
                u"touched.").format(u"discarding" if detach_mode == DETACH_DISCARD else u"keeping")
    return head + body + tail


def check_target_path(target, protected_paths):
    """None when the target is usable, otherwise the reason it is not."""
    target = to_text(target).strip()
    if not target:
        return u"Choose where the send copy is saved first."
    if not target.lower().endswith(u".rvt"):
        return u"The send copy must be a .rvt file."
    for path in protected_paths:
        if same_path(target, path):
            return u"That is the live model. Choose a different file for the send copy."
    folder = os.path.dirname(target)
    if folder and not os.path.isdir(folder):
        return u"The folder does not exist: " + folder
    return None


# ============================================================
# which views, schedules and legends go
# ============================================================

NEVER_DELETE_KINDS = set([
    u"DrawingSheet", u"ProjectBrowser", u"SystemBrowser", u"Internal",
    u"Undefined", u"Report", u"CostReport", u"LoadsReport",
    u"PresureLossReport", u"PanelSchedule", u"ColumnSchedule",
])
SCHEDULE_KINDS = set([u"Schedule"])
LEGEND_KINDS = set([u"Legend"])


def has_keep_word(name, keep_words):
    lower = to_text(name).lower()
    for word in keep_words:
        if word and word.lower() in lower:
            return True
    return False


def off_sheet_candidates(items, on_sheet, keep_words, protected, kinds=None,
                         exclude_kinds=None, retained=None, decisions=None):
    """items: dicts with id, name, kind, template, parent (0 when none),
    internal (bool, optional).

    Returns (ids_to_delete, skipped) where skipped maps id -> reason.
    A primary view is kept whenever any of its dependents is kept, because
    deleting a primary view deletes its dependents with it."""
    keep_words = list(keep_words or [])
    protected = set(protected or [])
    on_sheet = set(on_sheet or [])
    skipped = {}
    chosen = []
    kept = set()
    by_id = {}
    note = decisions if decisions is not None else {}
    for item in items:
        by_id[item[u"id"]] = item
        kind = item.get(u"kind", u"")
        if kinds is not None and kind not in kinds:
            continue
        if exclude_kinds is not None and kind in exclude_kinds:
            continue
        if kind in NEVER_DELETE_KINDS:
            note[item[u"id"]] = u"kept: Revit system view"
            continue
        if item.get(u"template"):
            note[item[u"id"]] = u"kept: view template"
            continue
        if item.get(u"internal"):
            skipped[item[u"id"]] = (u"title block revision or keynote schedule "
                                    u"(goes with its sheet)")
            kept.add(item[u"id"])
            continue
        if item[u"id"] in on_sheet:
            note[item[u"id"]] = u"kept: placed on a sheet that stays"
            kept.add(item[u"id"])
            continue
        if item[u"id"] in protected:
            skipped[item[u"id"]] = u"starting or active view"
            kept.add(item[u"id"])
            continue
        if retained and view_key(kind, item.get(u"name", u"")) in retained:
            skipped[item[u"id"]] = u"retained in the template"
            kept.add(item[u"id"])
            continue
        if has_keep_word(item.get(u"name", u""), keep_words):
            skipped[item[u"id"]] = u"name holds a keep word"
            kept.add(item[u"id"])
            continue
        chosen.append(item[u"id"])
    # dependents on sheets anywhere in the model protect their primary view
    for item in items:
        if item[u"id"] in on_sheet:
            kept.add(item[u"id"])
    changed = True
    rescued = set()
    while changed:
        changed = False
        for view_id in list(kept):
            item = by_id.get(view_id)
            parent = item.get(u"parent", 0) if item else 0
            if parent and parent not in kept:
                kept.add(parent)
                rescued.add(parent)
                changed = True
    out = []
    for view_id in chosen:
        if view_id in rescued:
            skipped[view_id] = u"a dependent of it is kept"
            continue
        out.append(view_id)
    for view_id, reason in skipped.items():
        note[view_id] = u"kept: " + reason
    for view_id in out:
        note[view_id] = u"DELETE"
    return out, skipped


def views_to_delete(items, on_sheet, keep_words, protected, retained=None, decisions=None):
    return off_sheet_candidates(
        items, on_sheet, keep_words, protected,
        exclude_kinds=SCHEDULE_KINDS | LEGEND_KINDS, retained=retained, decisions=decisions)


def schedules_to_delete(items, on_sheet, keep_words, protected, retained=None, decisions=None):
    return off_sheet_candidates(items, on_sheet, keep_words, protected,
                                kinds=SCHEDULE_KINDS, retained=retained, decisions=decisions)


def legends_to_delete(items, on_sheet, keep_words, protected, retained=None, decisions=None):
    return off_sheet_candidates(items, on_sheet, keep_words, protected,
                                kinds=LEGEND_KINDS, retained=retained, decisions=decisions)


def sheets_to_delete(sheets, retained_numbers, protected, decisions=None):
    """sheets: dicts with id, number. Every sheet whose number is not
    retained goes, except the starting or active view."""
    retained_numbers = set(retained_numbers or [])
    protected = set(protected or [])
    note = decisions if decisions is not None else {}
    out, skipped = [], {}
    for sheet in sheets:
        if sheet[u"number"] in retained_numbers:
            note[sheet[u"id"]] = u"kept: retained in the template"
            continue
        if sheet[u"id"] in protected:
            skipped[sheet[u"id"]] = u"starting or active view"
            note[sheet[u"id"]] = u"kept: starting or active view"
            continue
        out.append(sheet[u"id"])
        note[sheet[u"id"]] = u"DELETE"
    return out, skipped


def surviving_sheet_ids(sheets, delete_sheets, retained_numbers, protected):
    """The sheets left once the sheet stage has run: the only sheets that
    count as 'placed' for views, schedules and legends."""
    if not delete_sheets:
        return set(sheet[u"id"] for sheet in sheets)
    gone = set(sheets_to_delete(sheets, retained_numbers, protected)[0])
    return set(sheet[u"id"] for sheet in sheets if sheet[u"id"] not in gone)


def unplaced_images(image_type_ids, unused_ids):
    """Raster images Revit itself reports as unused: not placed on any view
    or sheet, and not picked in any element's Image parameter."""
    unused = set(unused_ids or [])
    return [value for value in image_type_ids if value in unused]


def images_freed(image_type_ids, instances, doomed_views, unused_ids):
    """For the preview, before anything is deleted: images unused now, plus
    images whose every placement is on a sheet or view that is going.
    instances: (image type id, owner view id)."""
    doomed_views = set(doomed_views or [])
    owners = {}
    for type_id, view_id in instances:
        owners.setdefault(type_id, set()).add(view_id)
    unused = set(unused_ids or [])
    out = []
    for value in image_type_ids:
        views = owners.get(value)
        if value in unused or (views and views <= doomed_views):
            out.append(value)
    return out


def cascade_hits(deleted_ids, guard):
    """What a delete took that has to stay. Revit's Delete returns every
    element it removed, cascades included - a parent view takes its callouts
    and dependents with it - so a delete that reaches into the guard is rolled
    back rather than trusted to what was predicted."""
    if not guard:
        return []
    guard = set(guard)
    return sorted(set(deleted_ids or []) & guard)


def split_refusals(failures):
    """({id: reason} refused by Revit, {id: reason} held back by the guard)."""
    refused, kept = {}, {}
    for value, reason in (failures or {}).items():
        if to_text(reason).startswith(u"kept - "):
            kept[value] = reason
        else:
            refused[value] = reason
    return refused, kept


def view_guard(all_view_ids, doomed_ids, placed_ids=()):
    """Every view and sheet the plan keeps, plus every view placed on a sheet
    that still exists. The plan counts a sheet the sheet stage tried to
    delete as gone; if Revit refused it, it is still there, and so is every
    view on it."""
    doomed = set(doomed_ids or [])
    kept = set(value for value in all_view_ids if value not in doomed)
    return kept | set(placed_ids or [])


def cascade_reason(hit_names):
    names = [to_text(n) for n in hit_names if to_text(n)]
    if not names:
        return u"kept - deleting it would also delete a view that stays"
    text = u", ".join(u"'{0}'".format(n) for n in names[:3])
    if len(names) > 3:
        text += u" and {0} more".format(len(names) - 3)
    return u"kept - deleting it would also delete {0}, which stays".format(text)


def unused_ids(all_ids, used_ids, keep=None):
    used = set(used_ids or [])
    keep = set(keep or [])
    return [value for value in all_ids if value not in used and value not in keep]


def remaining_ids(ids, deleted):
    """After a view goes, anything that went with it is not asked for again."""
    gone = set(deleted or [])
    return [value for value in ids if value not in gone]


# ============================================================
# views and sheets to retain
# ============================================================

RETAIN_SEP = u"\t"

VIEW_TYPE_LABELS = {
    u"FloorPlan": u"Floor Plans",
    u"CeilingPlan": u"Ceiling Plans",
    u"EngineeringPlan": u"Structural Plans",
    u"AreaPlan": u"Area Plans",
    u"ThreeD": u"3D Views",
    u"Section": u"Sections",
    u"Elevation": u"Elevations",
    u"Detail": u"Detail Views",
    u"DraftingView": u"Drafting Views",
    u"Rendering": u"Renderings",
    u"Walkthrough": u"Walkthroughs",
    u"Legend": u"Legends",
    u"Schedule": u"Schedules/Quantities",
}

# groups Revit puts at the top of the browser, outside the view organisation
TOP_LEVEL_KINDS = set([u"Legend", u"Schedule"])


def view_key(kind, name):
    """A view is named uniquely within its type, so type and name identify it
    in this model and in the next one built to the same standard."""
    return u"{0}::{1}".format(to_text(kind), to_text(name))


def split_retain(text):
    return [part for part in to_text(text).split(RETAIN_SEP) if part.strip()]


def join_retain(keys):
    seen = []
    for key in keys:
        key = to_text(key).replace(u"\t", u" ").replace(u"\n", u" ")
        if key.strip() and key not in seen:
            seen.append(key)
    return RETAIN_SEP.join(sorted(seen, key=natural_key))


def natural_key(value):
    """P-9 before P-10, case-blind."""
    parts = re.split(u"(\\d+)", to_text(value).lower())
    return [(0, int(part), u"") if part.isdigit() else (1, 0, part) for part in parts]


def view_folders(org_folders, kind):
    """Where the browser shows a view: its organisation folders, then its
    type. Legends and schedules sit at the top, outside the organisation."""
    label = VIEW_TYPE_LABELS.get(kind, split_camel(kind))
    if kind in TOP_LEVEL_KINDS:
        return [label]
    folders = [to_text(f) or u"???" for f in (org_folders or [])]
    return folders + [label]


def sheet_folders(org_folders):
    folders = [to_text(f) or u"???" for f in (org_folders or [])]
    return folders or [u"Sheets"]


def _matches(words, item):
    if not words:
        return True
    haystack = u" ".join([item[u"label"]] + list(item[u"folders"])).lower()
    return all(word in haystack for word in words)


def group_state(keys, retained):
    if not keys:
        return u"none"
    hits = sum(1 for key in keys if key in retained)
    if hits == len(keys):
        return u"all"
    return u"none" if hits == 0 else u"some"


def retain_rows(items, search, retained, collapsed=None, only_retained=False):
    """items: dicts with key, label, folders. Returns the rows to draw, in
    browser order: a header each time a folder level changes, then the item.
    Headers carry the keys of every shown item beneath them, so ticking a
    header ticks exactly what the search is showing. A collapsed folder keeps
    its header and hides everything beneath it; a search opens every folder
    so a match is never hidden."""
    retained = set(retained or [])
    collapsed = set() if to_text(search).strip() else set(collapsed or [])
    words = [word for word in to_text(search).lower().split() if word]
    shown = [item for item in items if _matches(words, item)
             and (not only_retained or item[u"key"] in retained)]
    shown.sort(key=lambda item: ([natural_key(f) for f in item[u"folders"]],
                                 natural_key(item[u"label"])))
    under = {}
    for item in shown:
        folders = item[u"folders"]
        for level in range(len(folders)):
            under.setdefault(tuple(folders[:level + 1]), []).append(item[u"key"])
    rows = []
    previous = []
    for item in shown:
        folders = list(item[u"folders"])
        common = 0
        while (common < len(previous) and common < len(folders)
               and previous[common] == folders[common]):
            common += 1
        hidden = False
        for level in range(len(folders)):
            path = tuple(folders[:level + 1])
            path_text = u"\x1f".join(path)
            if level >= common:
                children = under[path]
                rows.append({u"kind": u"header", u"level": level, u"label": folders[level],
                             u"path": path_text, u"children": children,
                             u"count": len(children),
                             u"collapsed": path_text in collapsed,
                             u"state": group_state(children, retained)})
            if path_text in collapsed:
                hidden = True
                break
        previous = folders
        if hidden:
            continue
        rows.append({u"kind": u"item", u"level": len(folders), u"key": item[u"key"],
                     u"label": item[u"label"], u"checked": item[u"key"] in retained})
    return rows


def all_folder_paths(items):
    paths = set()
    for item in items:
        folders = item[u"folders"]
        for level in range(len(folders)):
            paths.add(u"\x1f".join(folders[:level + 1]))
    return paths


def choose_switch_view(candidates, doomed, current):
    """The view to move to before the current one is deleted: the first
    candidate that stays and is not the current view. None when nothing
    qualifies - then the current view is kept instead."""
    doomed = set(doomed or [])
    for view_id in candidates:
        if view_id and view_id != current and view_id not in doomed:
            return view_id
    return None


def view_to_open(active_id, retained_sheet_ids, retained_view_ids, doomed, fallbacks):
    """Where to move the active view before cleaning the open model.

    If the active view is not retained, open a retained sheet (then a
    retained view) and the old one gets closed. If nothing is retained at
    all, only move when the active view is actually being deleted. None
    means stay where you are."""
    retained_sheet_ids = list(retained_sheet_ids or [])
    retained_view_ids = list(retained_view_ids or [])
    doomed = set(doomed or [])
    if not retained_sheet_ids and not retained_view_ids:
        if active_id in doomed:
            return choose_switch_view(fallbacks, doomed, active_id)
        return None
    if active_id in retained_sheet_ids or active_id in retained_view_ids:
        return None
    target = choose_switch_view(retained_sheet_ids + retained_view_ids, doomed, active_id)
    if target is None and active_id in doomed:
        target = choose_switch_view(fallbacks, doomed, active_id)
    return target


# ============================================================
# save and close at the end
# ============================================================

SAVE_AS = u"save_as"          # never saved: ask where
SAVE_PLAIN = u"save"          # not workshared
SAVE_SYNC = u"sync"           # its own central: sync, relinquish, compact
SAVE_LOCAL = u"local"         # a local of someone else's central: ask
SAVE_NONE = u"none"           # Clean Up already saved it and nothing changed since


def save_route(info):
    """How to save the cleaned model and let go of its worksets."""
    path = to_text(info.get(u"path")).strip()
    if not path:
        return SAVE_AS
    if not info.get(u"workshared"):
        return SAVE_PLAIN
    if info.get(u"cloud"):
        return SAVE_LOCAL
    central = to_text(info.get(u"central")).strip()
    if not central or same_path(central, path):
        return SAVE_SYNC
    return SAVE_LOCAL


def local_save_message(info):
    return (
        u"This is a local file of\n{0}\n\n"
        u"Relinquishing worksets needs a sync, and a sync would send the whole "
        u"clean up to that central model and everyone working in it.\n\n"
        u"Save local only: saves this file compact and keeps your worksets.\n"
        u"Sync and relinquish: only if that central is itself a throwaway copy - "
        u"you will be asked to type {1}.").format(
            info.get(u"central") or u"its central model", CONFIRM_WORD)


def folder_of(path):
    path = to_text(path).strip()
    if not path or u"://" in path:
        return u""
    return os.path.dirname(path)


def retention_warnings(template):
    """Settings that quietly make the retain lists do nothing."""
    get = as_bool
    out = []
    sheets = split_retain(template.get(u"retain_sheets"))
    views = split_retain(template.get(u"retain_views"))
    if sheets and not get(template.get(u"delete_sheets_not_retained")):
        out.append(u"sheets")
    if not get(template.get(u"delete_sheets_not_retained")) and (
            views and get(template.get(u"delete_views_off_sheet"))):
        out.append(u"placed_views")
    if views and not get(template.get(u"delete_views_off_sheet")):
        out.append(u"views")
    return out


RETENTION_TEXT = {
    u"sheets": (u"{0} sheets are ticked to retain, but Delete sheets not retained "
                u"is off, so no sheet will be removed."),
    u"placed_views": (u"With Delete sheets not retained off, every sheet stays, so every "
                      u"view placed on a sheet stays too - retained or not."),
    u"views": (u"Views are ticked to retain, but Delete views not retained or placed "
               u"is off, so no view will be removed."),
}


def retention_message(template, warnings):
    lines = []
    for key in warnings:
        text = RETENTION_TEXT[key]
        if key == u"sheets":
            text = text.format(len(split_retain(template.get(u"retain_sheets"))))
        lines.append(u"- " + text)
    return u"\n".join(lines)


def fix_retention(template, warnings):
    fixed = dict(template)
    if u"sheets" in warnings or u"placed_views" in warnings:
        fixed[u"delete_sheets_not_retained"] = u"1"
    if u"views" in warnings:
        fixed[u"delete_views_off_sheet"] = u"1"
    return fixed


KEPT_LABELS = {
    u"PanelSchedule": u"Panel Schedules",
    u"ColumnSchedule": u"Graphical Column Schedules",
    u"Report": u"Reports",
    u"CostReport": u"Cost Reports",
    u"LoadsReport": u"Loads Reports",
    u"PresureLossReport": u"Pressure Loss Reports",
}


def kept_summary(views, decisions):
    """Lines for the Clean Up confirmation: what stays that someone might
    expect to go - a delete stage that is off, or views Revit never lets go."""
    counts = {}
    for item in views:
        reason = decisions.get(item[u"id"], u"")
        if reason == u"kept: its delete stage is off":
            label = u"{0} (their delete stage is off)"
        elif reason == u"kept: Revit system view" and item[u"kind"] not in (
                u"ProjectBrowser", u"SystemBrowser", u"Internal", u"Undefined"):
            label = u"{0} (never deleted by this tool)"
        else:
            continue
        name = KEPT_LABELS.get(item[u"kind"]) or VIEW_TYPE_LABELS.get(
            item[u"kind"], split_camel(item[u"kind"]))
        key = label.format(name)
        counts[key] = counts.get(key, 0) + 1
    return [u"{0} {1}".format(n, k) for k, n in sorted(counts.items())]


def retain_summary(items, retained, noun):
    keys = set(item[u"key"] for item in items)
    kept = len(keys & set(retained or []))
    missing = len(set(retained or []) - keys)
    text = u"{0} of {1} {2} retained".format(kept, len(keys), noun)
    if missing:
        text += u" ({0} more listed in the template are not in this model)".format(missing)
    return text


# ============================================================
# purge groups
# ============================================================

CLASS_GROUPS = {
    u"Material": u"Materials",
    u"LinePatternElement": u"Line Patterns",
    u"FillPatternElement": u"Fill Patterns",
    u"ParameterFilterElement": u"View Filters",
    u"ViewFamilyType": u"View Types",
    u"AppearanceAssetElement": u"Appearance Assets",
    u"PropertySetElement": u"Physical and Thermal Assets",
    u"ImageType": u"Raster Images",
    u"GraphicsStyle": u"Line Styles",
    u"TextNoteType": u"Text Types",
    u"DimensionType": u"Dimension Types",
    u"SpotDimensionType": u"Spot Dimension Types",
    u"GroupType": u"Group Types",
    u"WallType": u"Walls",
    u"FloorType": u"Floors",
    u"CeilingType": u"Ceilings",
    u"RoofType": u"Roofs",
    u"PipeType": u"Pipes",
    u"DuctType": u"Ducts",
    u"CableTrayType": u"Cable Trays",
    u"ConduitType": u"Conduits",
    u"FlexPipeType": u"Flex Pipes",
    u"FlexDuctType": u"Flex Ducts",
    u"PipingSystemType": u"Piping Systems",
    u"MechanicalSystemType": u"Duct Systems",
    u"PipeSegment": u"Pipe Segments",
    u"PipeScheduleType": u"Pipe Schedule Types",
    u"MEPSystemType": u"MEP Systems",
    u"FilledRegionType": u"Filled Region Types",
    u"ElementType": u"Other Types",
    u"Element": u"Other Elements",
    u"LineAndTextAttrSymbol": u"Line and Text Styles",
    u"ElectricalLoadClassification": u"Load Classifications",
}

OTHER_GROUP = u"Other"


def split_camel(text):
    text = to_text(text)
    return re.sub(u"(?<=[a-z0-9])(?=[A-Z])", u" ", text)


def purge_group(category_name, class_name):
    """The name a purgeable element is listed and ticked under. The category
    when it has one, a friendly class name when it does not."""
    category_name = to_text(category_name).strip()
    if category_name:
        return category_name
    class_name = to_text(class_name).strip()
    if class_name in CLASS_GROUPS:
        return CLASS_GROUPS[class_name]
    if class_name:
        return split_camel(class_name)
    return OTHER_GROUP


def purge_selection(entries, excluded):
    """entries: (id, group). Ids whose group is not excluded."""
    excluded = set(excluded or [])
    return [entry[0] for entry in entries if entry[1] not in excluded]


def group_counts(unused_entries, used_entries):
    counts = {}
    for _, group in unused_entries:
        counts.setdefault(group, [0, 0])[0] += 1
    for _, group in used_entries:
        counts.setdefault(group, [0, 0])[1] += 1
    rows = [(group, pair[0], pair[1]) for group, pair in counts.items()]
    rows.sort(key=lambda row: row[0].lower())
    return rows


def visible_groups(rows, show_used, search):
    """Category rows the settings list shows: with show-used off, only groups
    with something to purge."""
    words = [word for word in to_text(search).lower().split() if word]
    out = []
    for group, unused, used in rows:
        if not show_used and unused == 0:
            continue
        lower = group.lower()
        if any(word not in lower for word in words):
            continue
        out.append((group, unused, used))
    return out


# ============================================================
# deleting in chunks, and the purge passes
# ============================================================

def chunks(sequence, size):
    size = max(1, int(size))
    items = list(sequence)
    for start in range(0, len(items), size):
        yield items[start:start + size]


def delete_in_chunks(ids, delete_batch, delete_one, still_there, size=25,
                     progress=None):
    """delete_batch(list) -> True when the whole chunk committed.
    delete_one(id) -> (ok, reason).  still_there(id) -> bool.

    A refused chunk is replayed one element at a time so only the element at
    fault is lost, and anything already removed alongside something else is
    not asked for twice. Progress is reported after every chunk and after
    every replayed element, so a slow replay still moves the bar.
    Returns (deleted_ids, failures {id: reason})."""
    deleted = []
    failures = {}
    pending = list(ids)
    total = max(1, len(pending))
    state = {u"done": 0}

    def report(extra=0):
        if progress is None:
            return
        try:
            progress(min(1.0, float(state[u"done"] + extra) / total))
        except Exception:
            pass

    for chunk in chunks(pending, size):
        live = [value for value in chunk if still_there(value)]
        gone_already = [value for value in chunk if value not in live]
        deleted.extend(gone_already)
        if live:
            ok = False
            try:
                ok = bool(delete_batch(live))
            except Exception:
                ok = False
            if ok:
                deleted.extend(live)
            else:
                for position, value in enumerate(live):
                    if not still_there(value):
                        deleted.append(value)
                    else:
                        try:
                            one_ok, reason = delete_one(value)
                        except Exception as error:
                            one_ok, reason = False, to_text(error)
                        if one_ok:
                            deleted.append(value)
                        else:
                            failures[value] = reason or u"Revit refused"
                    report(len(gone_already) + position + 1)
        state[u"done"] += len(chunk)
        report()
    if not pending and progress is not None:
        try:
            progress(1.0)
        except Exception:
            pass
    return deleted, failures


def purge_loop(scan, delete, excluded, passes, progress=None):
    """scan() -> [(id, group)] currently unused.
    delete(ids, sub_progress) -> (deleted, failures).

    Purging frees more to purge, so it runs in passes, stopping early when a
    pass removes nothing. Ids that failed once are not retried. Each pass
    owns an equal slice of the progress; stopping early jumps to the end."""
    passes = max(1, int(passes))
    total_deleted = []
    failures = {}
    ran = 0

    def report(value):
        if progress is not None:
            try:
                progress(max(0.0, min(1.0, value)))
            except Exception:
                pass

    for index in range(passes):
        base = float(index) / passes
        report(base)
        ids = [value for value in purge_selection(scan(), excluded)
               if value not in failures]
        if not ids:
            break
        ran += 1

        def sub(fraction, base=base):
            report(base + fraction / passes)

        deleted, failed = delete(ids, sub)
        total_deleted.extend(deleted)
        failures.update(failed)
        if not deleted:
            break
    report(1.0)
    return total_deleted, failures, ran


# ============================================================
# progress: stage weights, percent and time left
# ============================================================

# Relative cost of each stage, so the bar moves roughly with the time spent
# rather than giving a link removal the same slice as a three-pass purge.
STAGE_WEIGHTS = {
    u"remove_revit_links": 1.0,
    u"remove_cad": 1.5,
    u"remove_point_clouds": 1.0,
    u"delete_unplaced_images": 0.5,
    u"export_nwc": 5.0,
    u"delete_views_off_sheet": 4.0,
    u"delete_schedules_off_sheet": 1.5,
    u"delete_legends_off_sheet": 0.5,
    u"delete_unused_templates": 1.0,
    u"delete_unused_filters": 1.0,
    u"purge": 6.0,
    u"delete_sheets_not_retained": 2.0,
    u"save": 3.0,
}


def stage_plan(keys):
    """[(key, start, span)] covering 0..1 in order."""
    weights = [(key, STAGE_WEIGHTS.get(key, 1.0)) for key in keys]
    total = sum(weight for _, weight in weights) or 1.0
    plan = []
    start = 0.0
    for key, weight in weights:
        span = weight / total
        plan.append((key, start, span))
        start += span
    return plan


def plan_fraction(plan, key, local):
    for entry_key, start, span in plan:
        if entry_key == key:
            local = max(0.0, min(1.0, float(local)))
            return min(1.0, start + span * local)
    return 0.0


class ProgressClock(object):
    """Percent that never runs backwards, and a time-left estimate from the
    blend of the whole-run average rate and a smoothed recent rate."""

    MIN_ELAPSED = 2.0      # seconds before any estimate is offered
    MIN_FRACTION = 0.02    # and at least 2% done
    SAMPLE_GAP = 0.5       # seconds between rate samples
    SMOOTHING = 0.3        # weight of the newest sample

    def __init__(self, now=None):
        self.now = now or time.time
        self.started = None
        self.fraction = 0.0
        self.rate = None
        self.last_time = None
        self.last_fraction = 0.0
        self.finished_at = None

    def start(self):
        self.started = self.now()
        self.fraction = 0.0
        self.rate = None
        self.last_time = self.started
        self.last_fraction = 0.0
        self.finished_at = None

    def update(self, fraction):
        if self.started is None:
            self.start()
        try:
            fraction = float(fraction)
        except Exception:
            fraction = self.fraction
        fraction = max(self.fraction, min(1.0, max(0.0, fraction)))
        moment = self.now()
        gap = moment - self.last_time
        moved = fraction - self.last_fraction
        if gap >= self.SAMPLE_GAP and moved > 0:
            sample = moved / gap
            if self.rate is None:
                self.rate = sample
            else:
                self.rate = self.SMOOTHING * sample + (1.0 - self.SMOOTHING) * self.rate
            self.last_time = moment
            self.last_fraction = fraction
        self.fraction = fraction
        return fraction

    def finish(self):
        self.update(1.0)
        self.finished_at = self.now()

    def elapsed(self):
        if self.started is None:
            return 0.0
        end = self.finished_at if self.finished_at is not None else self.now()
        return max(0.0, end - self.started)

    def percent(self):
        if self.fraction >= 1.0:
            return 100
        return min(99, int(self.fraction * 100))

    def eta(self):
        """Seconds left, or None while there is not enough to go on."""
        if self.fraction >= 1.0:
            return 0.0
        elapsed = self.elapsed()
        if elapsed < self.MIN_ELAPSED or self.fraction < self.MIN_FRACTION:
            return None
        average = self.fraction / elapsed
        rate = average if self.rate is None else 0.5 * average + 0.5 * self.rate
        if rate <= 0:
            return None
        return (1.0 - self.fraction) / rate


def format_duration(seconds):
    seconds = max(0, int(round(seconds)))
    if seconds < 60:
        return u"{0} s".format(seconds)
    if seconds < 3600:
        return u"{0} min {1:02d} s".format(seconds // 60, seconds % 60)
    return u"{0} h {1:02d} min".format(seconds // 3600, (seconds % 3600) // 60)


def format_clock(seconds):
    seconds = max(0, int(seconds))
    if seconds >= 3600:
        return u"{0}:{1:02d}:{2:02d}".format(seconds // 3600, (seconds % 3600) // 60, seconds % 60)
    return u"{0}:{1:02d}".format(seconds // 60, seconds % 60)


def eta_text(eta_seconds):
    if eta_seconds is None:
        return u"Estimating time left..."
    if eta_seconds < 10:
        return u"Under 10 s left"
    if eta_seconds < 60:
        rounded = int(5 * round(eta_seconds / 5.0))
        return u"About {0} s left".format(rounded)
    return u"About {0} left".format(format_duration(eta_seconds))


def progress_line(clock):
    """The right-hand text under the bar."""
    elapsed = format_clock(clock.elapsed())
    if clock.finished_at is not None:
        return u"Done in {0}".format(format_duration(clock.elapsed()))
    return u"{0}   |   {1} elapsed".format(eta_text(clock.eta()), elapsed)


def should_repaint(last_paint, now, last_percent, percent, interval=0.15):
    """Repaint on every whole percent, and at least every `interval` seconds
    so the time left keeps ticking - but never more often than that for the
    same percent, because pumping the dispatcher is not free."""
    if last_paint is None or percent != last_percent:
        return True
    return (now - last_paint) >= interval


# ============================================================
# theme
# ============================================================

THEME_AUTO = u"auto"
THEME_DARK = u"dark"
THEME_LIGHT = u"light"
THEME_CYCLE = [THEME_AUTO, THEME_DARK, THEME_LIGHT]


def normalise_theme_mode(mode):
    mode = to_text(mode).strip().lower()
    return mode if mode in THEME_CYCLE else THEME_AUTO


def resolve_theme(mode, canvas_dark):
    """auto follows the Revit canvas; unknown canvas falls back to dark."""
    mode = normalise_theme_mode(mode)
    if mode == THEME_AUTO:
        if canvas_dark is None:
            return THEME_DARK
        return THEME_DARK if canvas_dark else THEME_LIGHT
    return mode


def next_theme_mode(mode):
    mode = normalise_theme_mode(mode)
    index = THEME_CYCLE.index(mode)
    return THEME_CYCLE[(index + 1) % len(THEME_CYCLE)]


def theme_chip_label(mode, resolved):
    mode = normalise_theme_mode(mode)
    shown = u"Dark" if resolved == THEME_DARK else u"Light"
    if mode == THEME_AUTO:
        return u"Auto " + shown
    return shown


def colour_is_dark(red, green, blue):
    luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    return luminance < 128.0


# ============================================================
# modeless: the ExternalEvent queue
# ============================================================

# ExternalEvent.Raise() answers: Accepted (queued), Pending (an earlier
# request is still waiting - this job runs with it), Denied and TimedOut.
RAISE_KEEPS = (u"Accepted", u"Pending")


def raise_kept(status):
    """True when the job just queued will run. Only a refused Raise loses the
    job, and only that job - clearing the whole queue on a Pending answer
    once left a window waiting for a callback that had been thrown away."""
    text = to_text(status).strip()
    if u"." in text:
        text = text.split(u".")[-1]
    return text in RAISE_KEEPS


RAISE_HELP = (u"Revit did not take the request ({0}). It is usually in the middle of "
              u"something - an edit mode, a sketch, or one of its own dialogs. Finish "
              u"or cancel that in Revit, then press the button again.")

WAIT_NOTE_SECONDS = 20.0


def waiting_note(seconds):
    """What the status line says while a request waits for Revit."""
    if seconds < WAIT_NOTE_SECONDS:
        return u"Waiting for Revit..."
    return (u"Still waiting for Revit after {0}. Finish or cancel what Revit is doing "
            u"(an edit mode or a dialog), or press Esc here to cancel the "
            u"request.").format(format_duration(seconds))


# ============================================================
# the shrink-to-bar drawer - pure arithmetic
# ============================================================

DRAWER_SECONDS = 0.28
DRAWER_TICK_MS = 15
DRAWER_GAP = 8          # clear of the taskbar
DRAWER_STACK_STEP = 4   # between stacked bars


def ease_out(progress):
    """Cubic ease out, clamped to 0..1."""
    progress = max(0.0, min(1.0, float(progress)))
    return 1.0 - (1.0 - progress) ** 3


def tween(start, end, progress):
    return start + (end - start) * ease_out(progress)


def parked_top(area, bar_height, stack=0):
    """Top of a parked bar on the work area (left, top, width, height): at
    the bottom, clear of the taskbar, the stack-th bar sitting above the
    ones already parked. A monitor above the primary one has a negative top,
    and the arithmetic has to keep it there."""
    left, top, width, height = area
    bottom = top + height - DRAWER_GAP
    return bottom - bar_height - max(0, int(stack)) * (bar_height + DRAWER_STACK_STEP)


def clamp_left(area, left, width):
    """Keep a window of this width on the work area horizontally."""
    a_left, a_top, a_width, a_height = area
    right_most = a_left + max(0.0, a_width - width)
    return max(a_left, min(left, right_most))


def bar_moved(parked_at, now_at, tolerance=3.0):
    return (abs(parked_at[0] - now_at[0]) > tolerance or
            abs(parked_at[1] - now_at[1]) > tolerance)


def reopen_bounds(restore, parked_at, now_at, bar_height, area):
    """Where the window opens to. Untouched bar: exactly where it was. A bar
    carried somewhere else: open upward from where it now sits - the
    window's bottom on the bar's bottom - kept on that screen."""
    left, top, width, height = restore
    if not bar_moved(parked_at, now_at):
        return (left, top, width, height)
    a_left, a_top, a_width, a_height = area
    new_left = clamp_left(area, now_at[0], width)
    new_top = now_at[1] + bar_height - height
    new_top = max(a_top, min(new_top, a_top + max(0.0, a_height - height)))
    return (new_left, new_top, width, height)


def drawer_key_action(key, ctrl, shift, parked, sliding):
    """What a key press does to the drawer: "toggle", "open", "swallow" or
    None (leave it to the window)."""
    if sliding:
        return u"swallow"
    if ctrl and shift and key == u"H":
        return u"toggle"
    if parked:
        if key in (u"Escape", u"Return", u"Enter", u"F11"):
            return u"open"
        return u"swallow"
    return None


# ============================================================
# debug report
# ============================================================

class DebugReport(object):
    """Everything worth knowing about a run, in one text file to send back.
    Written out after every section, so a run that dies still leaves it.
    Off: every call is a no-op."""

    def __init__(self, enabled, folder=None, stamp=None):
        self.enabled = bool(enabled)
        self.lines = []
        stamp = stamp or datetime.datetime.now().strftime(u"%Y%m%d_%H%M%S")
        self.path = os.path.join(folder or appdata_dir(),
                                 u"model_cleanup_debug_report_{0}.txt".format(stamp))
        self.started = datetime.datetime.now()
        self.pending = []
        if self.enabled:
            self.line(u"RevoBIM {0} v{1} - debug report".format(TOOL_NAME, __version__))
            self.line(u"Started {0}".format(self.started.strftime(u"%Y-%m-%d %H:%M:%S")))

    def line(self, text=u""):
        if self.enabled:
            self.lines.append(to_text(text))

    def section(self, title):
        if self.enabled:
            self.lines.extend([u"", u"=" * 70, to_text(title), u"=" * 70])

    def values(self, pairs):
        if not self.enabled:
            return
        pairs = list(pairs)
        width = max([len(to_text(k)) for k, _ in pairs] + [0])
        for key, value in pairs:
            self.lines.append(u"{0}  {1}".format(to_text(key).ljust(width), to_text(value)))

    def table(self, headers, rows, limit=20000):
        if not self.enabled:
            return
        rows = [[to_text(cell).replace(u"\t", u" ") for cell in row] for row in rows]
        self.lines.append(u"\t".join(headers))
        for row in rows[:limit]:
            self.lines.append(u"\t".join(row))
        if len(rows) > limit:
            self.lines.append(u"... {0} more rows".format(len(rows) - limit))

    def take_pending(self):
        """Details gathered before a stage's heading is written, handed over
        so they print under that heading rather than the one before it."""
        items, self.pending = self.pending, []
        return items

    def exception(self, stage, text):
        if self.enabled:
            self.section(u"ERROR in " + to_text(stage))
            self.lines.append(to_text(text))
            self.flush()

    def flush(self):
        if not self.enabled:
            return False
        try:
            with io.open(self.path, u"w", encoding=u"utf-8") as handle:
                handle.write(u"\n".join(self.lines) + u"\n")
            return True
        except Exception:
            return False


# ============================================================
# ids
# ============================================================

def eid_value(element_id):
    """ElementId.IntegerValue was removed in Revit 2026 - .Value first."""
    if element_id is None:
        return 0
    try:
        return int(element_id.Value)
    except Exception:
        pass
    try:
        return int(element_id.IntegerValue)
    except Exception:
        return 0
