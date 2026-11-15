# -*- coding: utf-8 -*-
"""RevoBIM Match Offset - Revit keyboard shortcuts.

There is no Revit API for keyboard shortcuts. The only route is the file
Revit keeps them in:

    %APPDATA%\\Autodesk\\Revit\\Autodesk Revit <year>\\KeyboardShortcuts.xml

so this module reads that file, finds the ShortcutItem for a ribbon command by
its CommandName, reports anything already holding the key sequence, and writes
the file back. Two things about that file decide the whole design:

* Revit reads it at startup. A shortcut written now takes effect next session.
* Revit rewrites the whole file from memory when the user presses OK in its own
  Keyboard Shortcuts dialog. Opening that dialog and OK-ing it after this tool
  has written, but before restarting, throws the change away.

Both are said plainly in the report rather than hoped about.

Everything here is string and file work, so bench_logic.py exercises the whole
of it under plain CPython with no Revit anywhere.
"""

import mo_clr  # noqa: F401

import os
import re
import datetime

from mo_core import to_text

TAB_NAME = u"RevoBIM PY"
PANEL_NAME = u"Coordination"
PULLDOWN_NAME = u"Match Offset"

# .*? rather than [^>]*?: Revit writes the ribbon path as Paths="a&gt;b",
# but a hand written > inside an attribute would otherwise end the match
# early and the entry would silently not exist as far as this module is
# concerned - which is exactly what it did until the bench caught it.
ITEM_RE = re.compile(r"<ShortcutItem\b.*?/>", re.IGNORECASE | re.DOTALL)
ATTR_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')


# ======================================================================
# where the file lives
# ======================================================================

def shortcuts_path(version_number, override=u""):
    """The KeyboardShortcuts.xml for a Revit release, or an override."""
    override = to_text(override).strip()
    if override:
        return override
    root = os.environ.get('APPDATA') or os.path.expanduser('~')
    year = to_text(version_number).strip() or u"2024"
    return os.path.join(root, 'Autodesk', 'Revit',
                        'Autodesk Revit {0}'.format(year),
                        'KeyboardShortcuts.xml')


def backup_path(path, now=None):
    stamp = (now or datetime.datetime.now()).strftime('%Y%m%d_%H%M%S')
    root = os.environ.get('APPDATA') or os.path.expanduser('~')
    folder = os.path.join(root, 'RevoBIM')
    name = os.path.basename(to_text(path)) or u"KeyboardShortcuts.xml"
    return os.path.join(folder, u"{0}.backup_{1}.xml".format(name, stamp))


# ======================================================================
# keys
# ======================================================================

def normalise_key(text):
    """A key sequence as Revit writes it: upper case, no stray spacing."""
    raw = to_text(text).strip().upper()
    if not raw:
        return u""
    parts = []
    for chunk in raw.replace(u"+", u" ").split():
        chunk = chunk.strip()
        if chunk:
            parts.append(chunk)
    return u" ".join(parts)


def split_keys(text):
    """Revit separates several shortcuts on one command with a semicolon."""
    out = []
    for part in to_text(text).split(u";"):
        key = normalise_key(part)
        if key and key not in out:
            out.append(key)
    return out


def join_keys(keys):
    return u";".join([k for k in keys if k])


def key_is_valid(text):
    """What Revit will accept: one or two tokens of letters or digits.

    Revit itself is looser than this - it takes function keys and modifier
    combinations too - so this only refuses what is certainly wrong rather
    than trying to be the authority on what is right.
    """
    key = normalise_key(text)
    if not key:
        return False
    tokens = key.split(u" ")
    if len(tokens) > 3:
        return False
    for token in tokens:
        if not token:
            return False
        if len(token) > 4:
            return False
        for ch in token:
            if not (ch.isalpha() or ch.isdigit()):
                return False
    return True


# ======================================================================
# reading the file
# ======================================================================

class ShortcutItem(object):
    def __init__(self, raw, start, end):
        self.raw = raw
        self.start = start
        self.end = end
        self.attrs = {}
        for name, value in ATTR_RE.findall(raw):
            self.attrs[name] = value

    @property
    def command_name(self):
        return to_text(self.attrs.get('CommandName', u""))

    @property
    def command_id(self):
        return to_text(self.attrs.get('CommandId', u""))

    @property
    def paths(self):
        return to_text(self.attrs.get('Paths', u""))

    @property
    def keys(self):
        return split_keys(self.attrs.get('Shortcuts', u""))

    def with_keys(self, keys):
        """This element rewritten with a new Shortcuts attribute.

        Everything else in the element is left byte for byte as it was, which
        is the point of splicing strings rather than reserialising the
        document: Revit's file carries several hundred entries and none of
        them is this tool's business.
        """
        value = join_keys(keys)
        if 'Shortcuts' in self.attrs:
            if value:
                return re.sub(r'Shortcuts\s*=\s*"[^"]*"',
                              'Shortcuts="{0}"'.format(value),
                              self.raw, count=1)
            return re.sub(r'\s*Shortcuts\s*=\s*"[^"]*"', '',
                          self.raw, count=1)
        if not value:
            return self.raw
        return self.raw[:-2].rstrip() + ' Shortcuts="{0}" />'.format(value)


def parse_items(xml_text):
    items = []
    text = to_text(xml_text)
    for match in ITEM_RE.finditer(text):
        items.append(ShortcutItem(match.group(0), match.start(), match.end()))
    return items


def read_file(path):
    handle = open(path, 'rb')
    try:
        raw = handle.read()
    finally:
        handle.close()
    try:
        return raw.decode('utf-8')
    except Exception:
        return raw.decode('latin-1', 'replace')


# ======================================================================
# finding a command
# ======================================================================

def command_id_for(button_name, tab=TAB_NAME, panel=PANEL_NAME,
                   pulldown=PULLDOWN_NAME):
    """The CommandId Revit gives a pyRevit button inside a pulldown."""
    return u"CustomCtrl_%CustomCtrl_%{0}%{1}%{2}%{3}".format(
        tab, panel, pulldown, button_name)


def find_item(items, command_name, command_id=u""):
    """The entry for one of our buttons, by name first and then by id."""
    wanted = to_text(command_name).strip().lower()
    for item in items:
        if item.command_name.strip().lower() == wanted:
            return item
    wanted_id = to_text(command_id).strip().lower()
    if wanted_id:
        for item in items:
            if item.command_id.strip().lower() == wanted_id:
                return item
    return None


def find_conflicts(items, key, keep_command_name=u""):
    """Every other command already holding this key sequence."""
    wanted = normalise_key(key)
    if not wanted:
        return []
    keep = to_text(keep_command_name).strip().lower()
    out = []
    for item in items:
        if item.command_name.strip().lower() == keep:
            continue
        if wanted in item.keys:
            out.append(item)
    return out


def xml_escape(text):
    out = to_text(text)
    out = out.replace(u"&", u"&amp;").replace(u"<", u"&lt;")
    return out.replace(u">", u"&gt;").replace(u'"', u"&quot;")


def new_item_xml(command_name, command_id, key, paths):
    return (u'  <ShortcutItem CommandName="{0}" CommandId="{1}" '
            u'Shortcuts="{2}" Paths="{3}" />'.format(
                xml_escape(command_name), xml_escape(command_id),
                normalise_key(key), xml_escape(paths)))


# ======================================================================
# writing
# ======================================================================

def plan_assignments(xml_text, wanted):
    """Work out what assigning these keys would do, before doing any of it.

    "wanted" is a list of (command_name, key). The plan that comes back is a
    list of dicts, one per assignment, each carrying the conflicts it would
    have to clear and whether the command was found in the file at all.
    """
    items = parse_items(xml_text)
    ours = set([to_text(name).strip().lower() for name, _key in wanted])
    plan = []
    for name, key in wanted:
        key = normalise_key(key)
        entry = {
            u"command": to_text(name),
            u"key": key,
            u"valid": key_is_valid(key),
            u"found": False,
            u"current": [],
            u"already": False,
            u"conflicts": [],
        }
        if not key:
            plan.append(entry)
            continue
        item = find_item(items, name, command_id_for(name))
        if item is not None:
            entry[u"found"] = True
            entry[u"current"] = item.keys
            entry[u"already"] = key in item.keys
        for other in find_conflicts(items, key, name):
            if other.command_name.strip().lower() in ours:
                continue
            entry[u"conflicts"].append({
                u"command": other.command_name,
                u"paths": other.paths,
                u"keys": other.keys,
            })
        plan.append(entry)
    return plan


def apply_assignments(xml_text, wanted, clear_conflicts=True,
                      tab=TAB_NAME, panel=PANEL_NAME, pulldown=PULLDOWN_NAME):
    """Rewrite the file text with these assignments.

    Returns (new_text, report), where report lists what was given, what was
    taken away and what could not be found. Conflicts are only cleared when
    asked for; with clear_conflicts off, an assignment whose key is held
    elsewhere is refused and said so, because Revit given two commands on one
    key silently honours one of them.
    """
    text = to_text(xml_text)
    plan = plan_assignments(text, wanted)
    report = {u"assigned": [], u"cleared": [], u"refused": [], u"added": []}

    edits = []        # (start, end, replacement)
    additions = []
    items = parse_items(text)

    for entry in plan:
        name = entry[u"command"]
        key = entry[u"key"]
        if not key:
            continue
        if not entry[u"valid"]:
            report[u"refused"].append(
                u"{0}: '{1}' is not a key sequence Revit will take".format(
                    name, key))
            continue
        if entry[u"conflicts"] and not clear_conflicts:
            holders = u", ".join([c[u"command"] for c in entry[u"conflicts"]])
            report[u"refused"].append(
                u"{0}: {1} is already on {2}".format(name, key, holders))
            continue

        for conflict in entry[u"conflicts"]:
            other = find_item(items, conflict[u"command"])
            if other is None:
                continue
            remaining = [k for k in other.keys if k != key]
            edits.append((other.start, other.end, other.with_keys(remaining)))
            report[u"cleared"].append(
                u"{0} lost {1}".format(other.command_name, key))

        item = find_item(items, name, command_id_for(name, tab, panel, pulldown))
        if item is None:
            additions.append(new_item_xml(
                name, command_id_for(name, tab, panel, pulldown), key,
                u"{0}>{1}".format(tab, panel)))
            report[u"added"].append(name)
            report[u"assigned"].append(u"{0} -> {1}".format(name, key))
            continue
        keys = [k for k in item.keys if k != key]
        keys.insert(0, key)
        edits.append((item.start, item.end, item.with_keys(keys)))
        report[u"assigned"].append(u"{0} -> {1}".format(name, key))

    # One element can be touched twice - given a key, and stripped of the same
    # key as somebody else's conflict. Later edits win, and they are applied
    # back to front so the earlier offsets stay valid.
    merged = {}
    for start, end, replacement in edits:
        merged[(start, end)] = replacement
    for (start, end) in sorted(merged.keys(), reverse=True):
        text = text[:start] + merged[(start, end)] + text[end:]

    if additions:
        text = insert_items(text, additions)

    return text, report


def insert_items(xml_text, blocks):
    """Put new ShortcutItem elements in just before the closing tag."""
    text = to_text(xml_text)
    body = u"\n".join(blocks)
    match = re.search(r"</Shortcuts\s*>", text, re.IGNORECASE)
    if match:
        return text[:match.start()] + body + u"\n" + text[match.start():]
    return text.rstrip() + u"\n" + body + u"\n"


def write_file(path, text, make_backup=True):
    """Write the file, keeping a copy of what was there first."""
    backup = u""
    if make_backup and os.path.isfile(path):
        backup = backup_path(path)
        folder = os.path.dirname(backup)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)
        source = open(path, 'rb')
        try:
            data = source.read()
        finally:
            source.close()
        target = open(backup, 'wb')
        try:
            target.write(data)
        finally:
            target.close()
    handle = open(path, 'wb')
    try:
        handle.write(to_text(text).encode('utf-8'))
    finally:
        handle.close()
    return backup


EMPTY_FILE = (u'<?xml version="1.0" encoding="utf-8" standalone="yes"?>\n'
              u'<Shortcuts>\n</Shortcuts>\n')
