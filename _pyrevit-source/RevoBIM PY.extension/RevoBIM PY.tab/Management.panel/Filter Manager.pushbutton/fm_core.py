# -*- coding: utf-8 -*-
"""RevoBIM PY - Filter Manager : version, settings and cross-version helpers.

Revit 2021 - 2027.
  2021-2024  .NET Framework 4.8   IronPython 2.7
  2025-2027  .NET 8               IronPython 3 / CPython
"""

import fm_clr  # noqa  - must be first

import os
import datetime
import tempfile

VERSION = "v3.31.0"
TOOL_NAME = "Filter Manager"


def eid_value(element_id):
    """ElementId as an integer. .IntegerValue was removed in Revit 2026."""
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


_UIAPP = [None]


def set_uiapp(uiapp):
    """script.py hands us __revit__.

    It is injected into the running script's own globals, not into
    __main__, so a module cannot reach it on its own - which is why the
    error dialog reported "Revit 0".
    """
    _UIAPP[0] = uiapp


def revit_version():
    """The Revit release number, from the UIApplication pyRevit hands us.

    VersionNumber lives on the DB Application, reached through the
    UIApplication - not on the UIApplication itself, which is what made this
    report "Revit 0" in every error dialog.
    """
    app = _UIAPP[0]
    if app is None:
        return 0
    try:
        return int(app.Application.VersionNumber)
    except Exception:
        pass
    try:
        return int(app.ActiveUIDocument.Document.Application.VersionNumber)
    except Exception:
        pass
    try:
        return int(app.VersionNumber)
    except Exception:
        return 0


def open_externally(path):
    """Open a file with its default handler.

    .NET Framework defaults UseShellExecute to True; .NET 8 (Revit 2025+)
    defaults it to False, where Process.Start on a data file throws.
    """
    try:
        from System.Diagnostics import Process, ProcessStartInfo
        psi = ProcessStartInfo(path)
        psi.UseShellExecute = True
        Process.Start(psi)
        return True
    except Exception:
        pass
    try:
        os.startfile(path)
        return True
    except Exception:
        return False


def load_bitmap(path):
    """BitmapImage from bytes.

    Never via BitmapImage.UriSource - `from System import Uri` throws
    ImportError on Revit 2025+ where the type moved assemblies.
    """
    try:
        from System.IO import File, MemoryStream
        from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption
        stream = MemoryStream(File.ReadAllBytes(path))
        bmp = BitmapImage()
        bmp.BeginInit()
        bmp.CacheOption = BitmapCacheOption.OnLoad
        bmp.StreamSource = stream
        bmp.EndInit()
        try:
            bmp.Freeze()
        except Exception:
            pass
        return bmp
    except Exception:
        return None


def apply_icon(image_control, path):
    """Cosmetics can never take a tool down."""
    try:
        if image_control is not None and os.path.isfile(path):
            bmp = load_bitmap(path)
            if bmp is not None:
                image_control.Source = bmp
    except Exception:
        pass


def write_text(path, text):
    """Write text on IronPython 2.7 and IronPython 3 / CPython alike."""
    try:
        import io
        f = io.open(path, "w", encoding="utf-8")
        try:
            if not isinstance(text, type(u"")):
                text = text.decode("utf-8")
            f.write(text)
        finally:
            f.close()
        return True
    except Exception:
        pass
    try:
        f = open(path, "w")
        try:
            f.write(text)
        finally:
            f.close()
        return True
    except Exception:
        return False


def settings_folder():
    base = os.path.join(os.environ.get("APPDATA", tempfile.gettempdir()),
                        "RevoBIM")
    try:
        if not os.path.isdir(base):
            os.makedirs(base)
    except Exception:
        return tempfile.gettempdir()
    return base


BREADCRUMB = "filter_manager_last_run.txt"


def crumb(stage):
    """Write a stage marker to disk and flush it immediately.

    A hard Revit crash raises nothing and leaves no traceback, so the only
    way to find out where it died is to record each step BEFORE taking it.
    After a crash the last line in this file names the stage that killed it.
    """
    try:
        path = os.path.join(settings_folder(), BREADCRUMB)
        f = open(path, "a")
        try:
            f.write("{0}  {1}\n".format(
                datetime.datetime.now().strftime("%H:%M:%S"), stage))
            f.flush()
        finally:
            f.close()
    except Exception:
        pass


def crumb_reset():
    try:
        path = os.path.join(settings_folder(), BREADCRUMB)
        previous = ""
        if os.path.isfile(path):
            f = open(path, "r")
            try:
                previous = f.read()
            finally:
                f.close()
        f = open(path, "w")
        try:
            f.write("RevoBIM Filter Manager {0}  {1}\n".format(
                VERSION, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            f.flush()
        finally:
            f.close()
        return previous
    except Exception:
        return ""


def last_stage(previous_text):
    """The final stage of the previous run, or None."""
    try:
        lines = [l.strip() for l in previous_text.splitlines() if l.strip()]
        return lines[-1] if lines else None
    except Exception:
        return None


LAYOUT_FILE = "filter_manager_layout.txt"


def row_visible(name, usage_count, search="", unused_only=False, extra=None):
    """Whether a row survives the search box and the unused tick.

    The search is "contains", and every word has to be found: typing
    "bgl tray" narrows to rows holding both, in any order. That is what
    makes a keyword search useful on names built out of the same handful of
    prefixes.

    `extra` is anything else the row should be searchable by - its
    categories, its parameters - so a word can be found in the name and
    another in a category and the row still counts as a match.
    """
    if unused_only and (usage_count or 0) > 0:
        return False
    return contains_all(search, [name] + list(extra or []))


def view_row_visible(row, hidden_types=None, search="", hide_locked=False,
                     only_ids=None):
    """Whether a row in Target Views survives the view-type dropdown.

    The dropdown works like an Excel filter: every type starts ticked, and
    `hidden_types` holds the ones unticked. Unticking everything shows
    nothing. A type is keyed "family|type", because two families can each
    own a type with the same name.

    `only_ids` is "Show only selected": when given, only those views show,
    still subject to the other filters.
    """
    if only_ids is not None and row.get("idv") not in only_ids:
        return False
    if hide_locked and row.get("locked"):
        return False
    if hidden_types and type_key(row) in hidden_types:
        return False
    return contains_all(search, [row.get("name"), row.get("kind"),
                                 row.get("type"), row.get("template")])


def type_key(row):
    return u"{0}|{1}".format(row.get("kind", ""), row.get("type", ""))


def view_type_entries(rows):
    """[(key, label, count)] for the view-type dropdown, family by family.

    The label is the type name, with its family after it when the two
    differ, so 'Mechanical Plan  (Floor Plan)' and 'Mechanical Plan
    (Ceiling Plan)' can be told apart.
    """
    counts = {}
    labels = {}
    order = {}
    for row in rows:
        key = type_key(row)
        kind = row.get("kind", "")
        tname = row.get("type", "") or kind
        counts[key] = counts.get(key, 0) + 1
        labels[key] = tname if tname == kind else u"{0}  ({1})".format(tname, kind)
        order[key] = (kind.lower(), tname.lower())
    keys = sorted(counts.keys(), key=lambda k: order[k])
    return [(k, labels[k], counts[k]) for k in keys]


def dropdown_caption(total, hidden, noun="view types"):
    """What the closed dropdown says."""
    if not hidden:
        return u"All {0}  ({1})".format(noun, total)
    shown = total - hidden
    if shown <= 0:
        return u"None ticked"
    return u"{0} of {1} {2}".format(shown, total, noun)


def contains_all(search, haystacks):
    """Every word in the search found somewhere in the given text."""
    words = (search or "").lower().split()
    if not words:
        return True
    hay = " ".join((h or "") for h in haystacks).lower()
    for word in words:
        if word not in hay:
            return False
    return True


def uses_match(count, expression):
    """Whether a use count satisfies what was typed in the # box.

    Blank matches everything. A plain number matches exactly. The usual
    comparisons work - >0, >=2, <5, <=1, =3 - and so does a range, 2-5.
    Anything that cannot be read is treated as no filter rather than as
    "match nothing", so a half typed expression does not blank the table.
    """
    text = (expression or "").strip()
    if not text:
        return True

    try:
        value = int(count or 0)
    except Exception:
        value = 0

    text = text.replace(" ", "")

    for prefix, test in ((">=", lambda a, b: a >= b),
                         ("<=", lambda a, b: a <= b),
                         ("<>", lambda a, b: a != b),
                         (">", lambda a, b: a > b),
                         ("<", lambda a, b: a < b),
                         ("=", lambda a, b: a == b)):
        if text.startswith(prefix):
            try:
                return test(value, int(text[len(prefix):]))
            except Exception:
                return True

    if "-" in text[1:]:
        low, _sep, high = text.partition("-")
        try:
            return int(low) <= value <= int(high)
        except Exception:
            return True

    try:
        return value == int(text)
    except Exception:
        return True


def distribute_widths(minimums, weights, available):
    """Share the width of the page out between the table's columns.

    Each column has a width it will not go below and a share of whatever is
    left over. A column with no share keeps its minimum however wide the
    window gets - a tick box or a count does not benefit from being wider -
    and the rest grow in proportion, so the last column ends flush with the
    edge of the page and nothing has to be scrolled sideways.

    Narrower than the minimums will allow, the minimums win and the table
    scrolls, which is the honest answer rather than squashing every column
    until nothing can be read.
    """
    minimums = [float(m) for m in minimums]
    weights = [max(0.0, float(w)) for w in weights]
    floor = sum(minimums)

    try:
        available = float(available)
    except Exception:
        return list(minimums)

    if available <= floor or not minimums:
        return list(minimums)

    total_weight = sum(weights)
    if total_weight <= 0:
        return list(minimums)

    spare = available - floor
    widths = []
    for minimum, weight in zip(minimums, weights):
        widths.append(minimum + spare * (weight / total_weight))

    # rounding leaves a pixel or two over; give it to the widest share so the
    # total is exactly the width of the page
    widths = [round(w, 2) for w in widths]
    drift = round(available - sum(widths), 2)
    if drift:
        biggest = weights.index(max(weights))
        widths[biggest] = round(widths[biggest] + drift, 2)
    return widths


def shrink_to_fit(size, minimum, available, floor=360.0):
    """Fit a window onto a screen that is smaller than it wants to be.

    A minimum larger than the screen is what stops a window going full
    screen: WPF honours the minimum, so the window stays bigger than the
    working area and hangs off the edge. The minimum has to come down with
    the size, not just the size.

    Returns (size, minimum), never below the floor.
    """
    try:
        available = float(available)
        size = float(size)
        minimum = float(minimum)
    except Exception:
        return (size, minimum)

    if available <= 0:
        return (size, minimum)

    limit = max(float(floor), min(available, max(size, minimum)))
    if available < limit:
        limit = available

    new_minimum = min(minimum, max(float(floor), min(minimum, available)))
    new_size = min(size, available)
    if new_size < new_minimum:
        new_size = new_minimum
    return (new_size, new_minimum)


def split_widths(first, second, min_first, min_second, change):
    """Share a fixed pool of width between two columns as one is dragged.

    The pool is whatever the two columns hold between them, so the width a
    drag takes off one is exactly what the other gains and nothing else on
    the row moves. Both minimums are honoured, and a drag that would breach
    either just stops there.
    """
    pool = float(first) + float(second)
    if pool <= 0:
        return (float(first), float(second))

    low = float(min_first)
    high = pool - float(min_second)
    if high < low:
        # the two minimums do not fit; give each its share of what there is
        share = pool * (low / (low + float(min_second))) if (low + float(min_second)) else pool / 2.0
        return (share, pool - share)

    wanted = float(first) + float(change)
    wanted = max(low, min(wanted, high))
    return (wanted, pool - wanted)


def load_settings(name):
    """A plain key=value text file, read key by key.

    Not JSON: no dependency on a module whose availability varies with the
    IronPython engine, and it stays readable and hand editable. A missing or
    damaged file gives back an empty dict rather than raising.
    """
    out = {}
    try:
        path = os.path.join(settings_folder(), name)
        if not os.path.isfile(path):
            return out
        f = open(path, "r")
        try:
            for line in f:
                if "=" not in line:
                    continue
                key, _sep, value = line.partition("=")
                key = key.strip()
                if key and not key.startswith("#"):
                    out[key] = value.strip()
        finally:
            f.close()
    except Exception:
        pass
    return out


def save_settings(name, values):
    rows = ["# RevoBIM Filter Manager {0}".format(VERSION)]
    for key in sorted(values):
        rows.append("{0}={1}".format(key, values[key]))
    return write_text(os.path.join(settings_folder(), name),
                      "\r\n".join(rows) + "\r\n")


def recent_crumbs(count=12):
    """The last few stages of this run, for the debug panel."""
    try:
        path = os.path.join(settings_folder(), BREADCRUMB)
        if not os.path.isfile(path):
            return ["(nothing recorded yet)"]
        f = open(path, "r")
        try:
            lines = [l.rstrip() for l in f if l.strip()]
        finally:
            f.close()
        return lines[-count:] if lines else ["(nothing recorded yet)"]
    except Exception:
        return ["(the breadcrumb file could not be read)"]


def log_folder():
    base = os.path.join(os.path.expanduser("~"), "Documents",
                        "RevoBIM PY", "Logs")
    try:
        if not os.path.isdir(base):
            os.makedirs(base)
        return base
    except Exception:
        return tempfile.gettempdir()


def log_path(prefix):
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(log_folder(), "{0}_{1}.log".format(prefix, stamp))
