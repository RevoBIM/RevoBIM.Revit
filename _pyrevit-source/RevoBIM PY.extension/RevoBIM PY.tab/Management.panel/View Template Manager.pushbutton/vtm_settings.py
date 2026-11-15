# -*- coding: utf-8 -*-
"""RevoBIM PY - View Template Manager: remembered settings.

Plain key=value text at %APPDATA%\\RevoBIM\\view_template_manager.txt, split on
the first '=' only. DEFAULTS is also the whitelist: a key not in it is ignored
on load, so an old file never breaks a new version, and a damaged file falls
back to the defaults key by key.

No .NET here and no Revit: everything below the file handling is a plain
function that bench_logic.py runs under CPython.

Columns are remembered by *token*, not by the key the model hands out, because
a key is only stable for built-in parameters. A project or shared parameter's
id differs from model to model, so it is remembered by its name instead:

    __name__              one of the fixed columns
    b:-1005112            a built-in parameter (stable across every model)
    n:BGL_View Group      anything else, by its name
"""

import io
import os

SETTINGS_VERSION = 1

DEFAULTS = {
    "settings_version": str(SETTINGS_VERSION),
    "theme": "follow",
    "column_order": "",
    "visible_values": "",
    "visible_controlled": "",
    "column_widths": "",
    "width": "1420",
    "height": "820",
}

# version -> keys that version reset to default. Empty until a key changes
# meaning; a new default alone does nothing for an existing file.
MIGRATIONS = {}

FILE_NAME = "view_template_manager.txt"

FIXED_KEYS = ["__name__", "__type__", "__used__", "__default__"]


# --------------------------------------------------------------------------
# the file
# --------------------------------------------------------------------------


def settings_dir():
    root = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(root, "RevoBIM")


def settings_path():
    return os.path.join(settings_dir(), FILE_NAME)


def parse(text):
    """key=value lines into a dict, filled from DEFAULTS first."""
    data = dict(DEFAULTS)
    if not text:
        return data
    for line in text.splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in DEFAULTS:
            data[key] = value
    try:
        found = int(data.get("settings_version", "0"))
    except Exception:
        found = 0
    for version in sorted(MIGRATIONS):
        if found < version:
            for key in MIGRATIONS[version]:
                data[key] = DEFAULTS[key]
    data["settings_version"] = str(SETTINGS_VERSION)
    return data


def render(data):
    lines = ["# RevoBIM PY - View Template Manager"]
    for key in sorted(DEFAULTS):
        value = data.get(key, DEFAULTS[key])
        value = (u"%s" % value).replace("\r", " ").replace("\n", " ")
        lines.append(u"{0}={1}".format(key, value))
    return u"\n".join(lines) + u"\n"


def load():
    try:
        handle = io.open(settings_path(), "r", encoding="utf-8")
        try:
            return parse(handle.read())
        finally:
            handle.close()
    except Exception:
        return dict(DEFAULTS)


def save(data):
    """Best effort. Returns True when the file was written."""
    try:
        folder = settings_dir()
        if not os.path.isdir(folder):
            os.makedirs(folder)
        text = render(data)
        handle = io.open(settings_path(), "w", encoding="utf-8")
        try:
            handle.write(text)
        finally:
            handle.close()
        return True
    except Exception:
        return False


def as_int(data, key, fallback):
    try:
        return int(float(data.get(key, fallback)))
    except Exception:
        return fallback


# --------------------------------------------------------------------------
# column tokens
# --------------------------------------------------------------------------


def _clean(text):
    """A name safe to sit inside a '|' list and a ';' list on one line."""
    text = u"%s" % (text or u"")
    for bad in (u"|", u";", u"=", u"\r", u"\n"):
        text = text.replace(bad, u" ")
    return text.strip()


def key_token(key, label):
    if key in FIXED_KEYS:
        return key
    try:
        number = int(key)
    except Exception:
        number = None
    if number is not None and number < 0:
        return u"b:{0}".format(number)
    return u"n:{0}".format(_clean(label))


def token_map(columns):
    """{token: key} for the columns in this model. columns is {key: label}.
    Where two parameters share a name, the first keeps the token."""
    out = {}
    for key in columns:
        token = key_token(key, columns[key])
        if token not in out:
            out[token] = key
    return out


def encode_list(tokens):
    """Tokens are already clean - key_token made them - so this only joins."""
    return u"|".join([t for t in tokens if t])


def decode_list(text):
    if not text:
        return []
    return [t for t in (u"%s" % text).split(u"|") if t]


def tokens_to_keys(tokens, mapping):
    """Saved tokens to this model's keys, dropping any it does not have."""
    out = []
    for token in tokens:
        key = mapping.get(token)
        if key is not None and key not in out:
            out.append(key)
    return out


def keys_to_tokens(keys, columns):
    return [key_token(k, columns.get(k, u"")) for k in keys if k in columns]


def decode_widths(text, mapping):
    out = {}
    if not text:
        return out
    for part in (u"%s" % text).split(u";"):
        if u":" not in part:
            continue
        token, value = part.rsplit(u":", 1)
        key = mapping.get(token)
        if key is None:
            continue
        try:
            number = int(value)
        except Exception:
            continue
        if 30 <= number <= 2000:
            out[key] = number
    return out


# --------------------------------------------------------------------------
# column order
# --------------------------------------------------------------------------


def merge_order(saved, default):
    """The saved order, with anything new slotted in after the column it
    follows in the default order, and anything gone dropped.

    A parameter added to the model since the order was saved lands beside its
    neighbour rather than at the far end where nobody would find it.
    """
    present = set(default)
    out = []
    for key in saved:
        if key in present and key not in out:
            out.append(key)
    for index, key in enumerate(default):
        if key in out:
            continue
        if index == 0:
            out.insert(0, key)
            continue
        before = default[index - 1]
        if before in out:
            out.insert(out.index(before) + 1, key)
        else:
            out.append(key)
    return out


def reorder_full(full, shown):
    """Apply a new order of the shown columns to the full order, leaving the
    hidden columns where they were. `shown` is the shown keys in their new
    left-to-right order."""
    wanted = set(shown)
    slots = [i for i, key in enumerate(full) if key in wanted]
    out = list(full)
    queue = [k for k in shown if k in set(full)]
    for slot, key in zip(slots, queue):
        out[slot] = key
    return out


def leading_frozen(keys, limit=4):
    """How many columns to freeze: the run of identity columns at the left.
    Drag Used to the far right and it stops being frozen."""
    count = 0
    for key in keys:
        if key in FIXED_KEYS and count < limit:
            count += 1
        else:
            break
    return count


def carry_unknown(new, old, known):
    """Keep tokens from the last save that this model does not have, each
    after the token it followed last time. `known` is every token this model
    can produce; anything in `old` outside it belongs to another project."""
    out = list(new)
    for index, token in enumerate(old):
        if token in known or token in out:
            continue
        before = old[index - 1] if index > 0 else None
        if index == 0:
            out.insert(0, token)
        elif before in out:
            out.insert(out.index(before) + 1, token)
        else:
            out.append(token)
    return out


def merge_widths(old_text, widths, columns):
    """The saved widths with this model's columns updated and every other
    project's left alone."""
    merged = {}
    if old_text:
        for part in (u"%s" % old_text).split(u";"):
            if u":" not in part:
                continue
            token, value = part.rsplit(u":", 1)
            try:
                merged[token] = int(value)
            except Exception:
                continue
    for key in widths:
        if key not in columns:
            continue
        try:
            value = int(round(float(widths[key])))
        except Exception:
            continue
        if 30 <= value <= 2000:
            merged[key_token(key, columns[key])] = value
    return u";".join([u"{0}:{1}".format(t, merged[t]) for t in sorted(merged)])


def forget_widths(old_text, known):
    """The saved widths without this model's columns - hidden ones included -
    so a reset sticks, while other projects' widths are left alone."""
    if not old_text:
        return u""
    keep = []
    for part in (u"%s" % old_text).split(u";"):
        if u":" not in part:
            continue
        token = part.rsplit(u":", 1)[0]
        if token not in known:
            keep.append(part)
    return u";".join(keep)
