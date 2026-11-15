# -*- coding: utf-8 -*-
u"""RevoBIM Addin Manager - Revit's KeyboardShortcuts.xml.

Revit keeps its shortcuts in

    %APPDATA%\\Autodesk\\Revit\\Autodesk Revit <version>\\KeyboardShortcuts.xml

and reads the file at start up. There is no API for assigning a shortcut, so
the file is edited directly - the same route this extension already uses - and
the command id comes from the live ribbon item, which is the only place it
exists.

Everything in here is plain string work with no .NET in it, so the parsing,
the conflict rule and the rewrite are all exercised by bench_logic.py under
CPython. **The file is parsed with a regex rather than an XML parser on
purpose**: it is machine written and flat, an XML round trip reorders and
re-quotes attributes across the whole file, and a shortcut file that Revit
then rejects costs the user every shortcut they have.
"""

import rba_clr  # noqa: F401

import os
import re
import shutil

from rba_core import to_text, log, log_exception

ITEM = re.compile(r"<ShortcutItem\b[^>]*/>", re.I)
ATTR = re.compile(r'(\w+)\s*=\s*"([^"]*)"')

# Revit separates several shortcuts on one command with a hash.
SEPARATOR = u"#"


def shortcuts_path(version):
    u"""The file for a given Revit version number, e.g. "2024"."""
    base = os.environ.get(u"APPDATA") or os.path.expanduser(u"~")
    return os.path.join(base, u"Autodesk", u"Revit",
                        u"Autodesk Revit {0}".format(to_text(version)),
                        u"KeyboardShortcuts.xml")


def read_file(path):
    try:
        handle = open(path, u"rb")
        try:
            raw = handle.read()
        finally:
            handle.close()
        try:
            return raw.decode(u"utf-8")
        except Exception:
            return raw.decode(u"latin-1")
    except Exception:
        return u""


def parse(text):
    u"""Every ShortcutItem, as a dict of its attributes plus its raw tag."""
    items = []
    for match in ITEM.finditer(to_text(text)):
        raw = match.group(0)
        attributes = {}
        for name, value in ATTR.findall(raw):
            attributes[name] = value
        attributes[u"_raw"] = raw
        items.append(attributes)
    return items


def keys_of(item):
    value = to_text(item.get(u"Shortcuts", u""))
    return [part.strip() for part in value.split(SEPARATOR) if part.strip()]


def normalise_keys(keys):
    u"""Upper case, and the modifier order Revit writes.

    "ctrl+shift+s" and "Shift+Ctrl+S" are the same shortcut, and a conflict
    check that compares them as written would miss it.
    """
    text = to_text(keys).strip().upper().replace(u" ", u"")
    if u"+" not in text:
        return text
    parts = [part for part in text.split(u"+") if part]
    order = {u"CTRL": 0, u"SHIFT": 1, u"ALT": 2}
    modifiers = sorted([part for part in parts if part in order],
                       key=lambda part: order[part])
    rest = [part for part in parts if part not in order]
    return u"+".join(modifiers + rest)


def find_conflicts(items, keys, command_id=None):
    u"""Every command already holding this shortcut, bar the one being set."""
    wanted = normalise_keys(keys)
    if not wanted:
        return []
    out = []
    for item in items:
        if command_id and item.get(u"CommandId") == command_id:
            continue
        for existing in keys_of(item):
            if normalise_keys(existing) == wanted:
                out.append(item)
                break
    return out


def describe(item):
    name = to_text(item.get(u"CommandName") or item.get(u"Command") or u"")
    paths = to_text(item.get(u"Paths", u"")).replace(u";", u", ")
    if name and paths:
        return u"{0}  ({1})".format(name, paths)
    return name or paths or to_text(item.get(u"CommandId", u"unknown command"))


def find_item(items, command_id):
    for item in items:
        if item.get(u"CommandId") == command_id:
            return item
    return None


def _escape(value):
    return (to_text(value).replace(u"&", u"&amp;").replace(u"<", u"&lt;")
            .replace(u">", u"&gt;").replace(u'"', u"&quot;"))


def build_item(command_id, name, paths, keys):
    return (u'<ShortcutItem CommandName="{0}" CommandId="{1}" Shortcuts="{2}" '
            u'Paths="{3}" />').format(_escape(name), _escape(command_id),
                                      _escape(keys), _escape(paths))


def upsert(text, command_id, name, paths, keys, replace=True):
    u"""Set the shortcut on a command, returning the new file text.

    An existing entry for that command has only its Shortcuts attribute
    rewritten, so whatever else Revit put on that line survives untouched.
    """
    text = to_text(text)
    items = parse(text)
    keys = normalise_keys(keys)
    existing = find_item(items, command_id)
    if existing is not None:
        raw = existing[u"_raw"]
        current = keys_of(existing)
        if replace:
            merged = keys
        else:
            if keys in [normalise_keys(one) for one in current]:
                merged = SEPARATOR.join(current)
            else:
                merged = SEPARATOR.join(current + [keys])
        if u"Shortcuts=" in raw:
            updated = re.sub(r'Shortcuts\s*=\s*"[^"]*"',
                             u'Shortcuts="{0}"'.format(_escape(merged)), raw, count=1)
        else:
            updated = raw[:-2].rstrip() + u' Shortcuts="{0}" />'.format(_escape(merged))
        return text.replace(raw, updated, 1)

    new_item = u"\t" + build_item(command_id, name, paths, keys) + u"\n"
    closing = re.search(r"</Shortcuts>", text, re.I)
    if closing:
        return text[:closing.start()] + new_item + text[closing.start():]
    if text.strip():
        return text.rstrip() + u"\n" + new_item
    return (u'<?xml version="1.0" encoding="utf-8"?>\n<Shortcuts>\n'
            + new_item + u"</Shortcuts>\n")


def remove(text, command_id, keys):
    u"""Take one shortcut off a command, leaving any others it has."""
    text = to_text(text)
    items = parse(text)
    existing = find_item(items, command_id)
    if existing is None:
        return text
    wanted = normalise_keys(keys)
    kept = [one for one in keys_of(existing) if normalise_keys(one) != wanted]
    raw = existing[u"_raw"]
    updated = re.sub(r'Shortcuts\s*=\s*"[^"]*"',
                     u'Shortcuts="{0}"'.format(_escape(SEPARATOR.join(kept))),
                     raw, count=1)
    return text.replace(raw, updated, 1)


def current_keys(text, command_id):
    item = find_item(parse(text), command_id)
    if item is None:
        return []
    return keys_of(item)


def write_file(path, text):
    u"""Write, keeping one backup.

    A shortcut file Revit will not read costs the user every shortcut they
    have, so the last good one is kept beside it before anything is written.
    """
    try:
        if os.path.isfile(path):
            backup = path + u".revobim.bak"
            try:
                shutil.copyfile(path, backup)
            except Exception:
                log_exception(u"shortcuts/backup")
        folder = os.path.dirname(path)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)
        handle = open(path, u"wb")
        try:
            handle.write(to_text(text).encode(u"utf-8"))
        finally:
            handle.close()
        log(u"shortcuts written to {0}".format(path))
        return True
    except Exception:
        log_exception(u"shortcuts/write")
        return False
