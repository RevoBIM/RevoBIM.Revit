# -*- coding: utf-8 -*-
u"""RevoBIM Addins - the read of the extensions folder.

Pure Python: no WPF, no Revit API.  The whole of it is exercised by
bench_logic.py against a synthetic folder tree under CPython.

pyRevit's ribbon IS the folder tree, so the folder tree is the register.
Nothing is cached to disk - a rescan is a directory walk and takes
milliseconds, which is what lets the tool stay correct when a tool folder is
added or deleted while Revit is open.
"""

import rba_clr  # noqa: F401

import os
import re

from rba_core import to_text, normalise, natural_key, matches_search, KEY_SEP

# Folder suffixes pyRevit uses.  Anything that ends up as a clickable ribbon
# item is LAUNCHABLE; the rest are containers to walk through.
LAUNCHABLE = (
    u".pushbutton",
    u".smartbutton",
    u".invokebutton",
    u".urlbutton",
    u".linkbutton",
    u".contentbutton",
)
CONTAINERS = (
    u".pulldown",
    u".splitbutton",
    u".splitpushbutton",
    u".stack",
    u".stack2",
    u".stack3",
)
ICON_NAMES = (u"icon.png", u"icon.dark.png")

TRIPLE_DOUBLE = u'"' * 3
TRIPLE_SINGLE = u"'" * 3


def _key_sep():
    return KEY_SEP


class Item(object):
    u"""One launchable button."""

    def __init__(self):
        self.title = u""
        self.folder = u""
        self.tooltip = u""
        self.description = u""
        self.icon = u""
        self.icon_dark = u""
        self.extension = u""
        self.tab = u""
        self.panel = u""
        self.parent = u""      # pulldown / stack title, blank at panel level
        self.kind = u""
        self.live = False      # matched to a live ribbon item
        self.command_id = u""

    @property
    def name_text(self):
        u'''What the PRIMARY search looks at: what the addin is called.'''
        return u" ".join([self.title, self.parent])

    @property
    def detail_text(self):
        u'''What the SECONDARY search looks at: what the addin does.

        Deliberately kept apart from name_text rather than pooled into one
        string. Pooled, a word buried in a description drags an addin up
        beside an exact name match and the list stops being ranked at all.
        '''
        return u" ".join([self.tooltip, self.description, self.panel,
                          self.tab, self.extension])

    @property
    def search_text(self):
        return u" ".join([self.name_text, self.detail_text])

    @property
    def key(self):
        # "::" between the parts, never "|": the settings file stores lists
        # of these keys joined with "|", and 1.3.0 - 1.5.0 built keys with "|"
        # inside them - so every saved key came back as four fragments and
        # favourites, pins, the toolbar list and folded groups never stuck.
        return _key_sep().join([normalise(self.extension), normalise(self.tab),
                                normalise(self.panel), normalise(self.title)])


class Group(object):
    u"""A collapsible heading and its items."""

    def __init__(self, key, title, subtitle):
        self.key = key
        self.title = title
        self.subtitle = subtitle
        self.items = []


# ----------------------------------------------------------------------
# bundle.yaml and script.py metadata
# ----------------------------------------------------------------------

def _read_text(path):
    try:
        handle = open(path, u"rb")
        try:
            raw = handle.read()
        finally:
            handle.close()
        try:
            return raw.decode(u"utf-8")
        except Exception:
            try:
                return raw.decode(u"latin-1")
            except Exception:
                return u""
    except Exception:
        return u""


def read_bundle(folder):
    u"""Pull title and tooltip out of bundle.yaml without a YAML parser.

    Deliberately a line reader: importing a YAML module is a dependency on
    something whose availability varies with the IronPython engine pyRevit
    picks, and a bundle.yaml only ever has flat keys worth reading here.
    """
    out = {}
    path = os.path.join(folder, u"bundle.yaml")
    if not os.path.isfile(path):
        return out
    for line in _read_text(path).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(u"#"):
            continue
        if u":" not in stripped:
            continue
        # only top level keys - an indented line belongs to a nested block
        if line[:1] in (u" ", u"\t"):
            continue
        key, value = stripped.split(u":", 1)
        key = key.strip().lower()
        value = value.strip().strip(u'"').strip(u"'")
        if key in (u"title", u"tooltip", u"highlight", u"author") and value:
            out[key] = value
    return out


def read_script_meta(folder):
    u"""__title__ and the first line of __doc__ out of script.py."""
    out = {}
    for name in (u"script.py", u"config.py"):
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        text = _read_text(path)
        for line in text.splitlines()[:80]:
            stripped = line.strip()
            for key, dunder in ((u"title", u"__title__"), (u"tooltip", u"__doc__")):
                if stripped.startswith(dunder) and u"=" in stripped:
                    value = stripped.split(u"=", 1)[1].strip()
                    value = value.strip(u"u").strip(u'"').strip(u"'").strip()
                    if value and key not in out:
                        out[key] = value
        break
    return out


def folder_title(folder):
    stem = os.path.basename(to_text(folder))
    if u"." in stem:
        stem = stem.rsplit(u".", 1)[0]
    return stem


def pretty_title(folder):
    u"""bundle.yaml title, then __title__, then the folder name.

    pyRevit names a ribbon item after its folder unless bundle.yaml overrides
    it, so the same order is what puts the same words in this list as on the
    ribbon - which is also what lets the two be matched up later.
    """
    bundle = read_bundle(folder)
    if bundle.get(u"title"):
        return _flatten(bundle[u"title"])
    meta = read_script_meta(folder)
    if meta.get(u"title"):
        return _flatten(meta[u"title"])
    return folder_title(folder)


def _flatten(value):
    return u" ".join(to_text(value).replace(u"\\n", u" ").replace(u"\n", u" ").split())


def _strip_quoting(fragment):
    u'''Quotes, brackets and continuations out; this is a haystack, not a caption.

    Escapes first: a \\n in the source is a line break, and stripping the
    backslash alone left a stray "n" - "tabs. n n Wall:" in the panel.
    '''
    fragment = re.sub(r"\\[nrt]", u" ", fragment)
    for token in (u'__doc__', u'=', u'(', u')', u'[', u']', u'+'):
        fragment = fragment.replace(token, u' ')
    for token in (TRIPLE_DOUBLE, TRIPLE_SINGLE, u'\\'):
        fragment = fragment.replace(token, u' ')
    fragment = fragment.replace(u'"', u' ').replace(u"'", u' ')
    return fragment


def _doc_assignments(text):
    u'''__doc__ = "..." and __doc__ = ("..." "...") alike.'''
    out = []
    index = text.find(u'__doc__')
    while index != -1:
        chunk = text[index:index + 2000]
        stop = chunk.find(u'\n__')
        if stop > 0:
            chunk = chunk[:stop]
        out.append(_strip_quoting(chunk))
        index = text.find(u'__doc__', index + 1)
    return out


def _module_docstring(text):
    u'''The docstring, past the coding line.

    A plain lstrip() finds nothing on a real script, because every script in
    this extension opens with a '# -*- coding: utf-8 -*-' comment and the
    docstring is on the line after it. Leading comments and blank lines are
    stepped over first.
    '''
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped and not stripped.startswith(u'#'):
            break
        index += 1
    body = u'\n'.join(lines[index:]).lstrip()
    for opener in (u'u' + TRIPLE_DOUBLE, TRIPLE_DOUBLE,
                   u'u' + TRIPLE_SINGLE, TRIPLE_SINGLE):
        if body.startswith(opener):
            quote = opener[-3:]
            rest = body[len(opener):]
            end = rest.find(quote)
            if end != -1:
                return rest[:end]
    return u''


def read_description(folder):
    u'''Everything the addin says about itself, for the secondary search.

    Three sources, because the tools in this extension are not consistent
    about which they use: the bundle tooltip, the __doc__ assignment, and
    script.py's own module docstring. Whatever is there is pooled.
    '''
    parts = []
    bundle = read_bundle(folder)
    if bundle.get(u'tooltip'):
        parts.append(bundle[u'tooltip'])
    path = os.path.join(folder, u'script.py')
    if os.path.isfile(path):
        text = _read_text(path)
        parts.extend(_doc_assignments(text))
        parts.append(_module_docstring(text))
    return _flatten(u' '.join([part for part in parts if part]))


def read_tooltip(folder):
    bundle = read_bundle(folder)
    if bundle.get(u"tooltip"):
        return _flatten(bundle[u"tooltip"])
    meta = read_script_meta(folder)
    if meta.get(u"tooltip"):
        return _flatten(meta[u"tooltip"])
    return u""


def find_icon(folder, inherited=u"", inherited_dark=u""):
    light = inherited
    dark = inherited_dark
    try:
        for name in ICON_NAMES:
            path = os.path.join(folder, name)
            if os.path.isfile(path):
                if name == u"icon.dark.png":
                    dark = path
                else:
                    light = path
    except Exception:
        pass
    return light, dark


# ----------------------------------------------------------------------
# the walk
# ----------------------------------------------------------------------

def _subfolders(folder):
    try:
        names = os.listdir(folder)
    except Exception:
        return []
    out = []
    for name in sorted(names, key=natural_key):
        path = os.path.join(folder, name)
        if os.path.isdir(path):
            out.append(path)
    return out


def _suffix(path):
    name = os.path.basename(to_text(path)).lower()
    if u"." in name:
        return u"." + name.rsplit(u".", 1)[1]
    return u""


def scan_panel(panel_folder, extension, tab, panel, icon, icon_dark, parent=u"", depth=0):
    items = []
    if depth > 4:
        return items
    for child in _subfolders(panel_folder):
        suffix = _suffix(child)
        child_icon, child_dark = find_icon(child, icon, icon_dark)
        if suffix in LAUNCHABLE:
            item = Item()
            item.folder = child
            item.title = pretty_title(child)
            item.tooltip = read_tooltip(child)
            item.description = read_description(child)
            item.icon = child_icon
            item.icon_dark = child_dark
            item.extension = extension
            item.tab = tab
            item.panel = panel
            item.parent = parent
            item.kind = suffix.lstrip(u".")
            items.append(item)
        elif suffix in CONTAINERS:
            inner = pretty_title(child)
            items.extend(scan_panel(child, extension, tab, panel,
                                    child_icon, child_dark,
                                    parent=inner, depth=depth + 1))
    return items


def scan_tab(tab_folder, extension, tab):
    items = []
    for panel_folder in _subfolders(tab_folder):
        if _suffix(panel_folder) != u".panel":
            continue
        panel = pretty_title(panel_folder)
        icon, icon_dark = find_icon(panel_folder)
        items.extend(scan_panel(panel_folder, extension, tab, panel, icon, icon_dark))
    return items


def scan_extension(ext_folder):
    extension = folder_title(ext_folder)
    items = []
    for tab_folder in _subfolders(ext_folder):
        if _suffix(tab_folder) != u".tab":
            continue
        items.extend(scan_tab(tab_folder, extension, pretty_title(tab_folder)))
    return items


def scan_root(root):
    u"""Accepts an extensions directory, a single .extension, or a .tab."""
    items = []
    if not root or not os.path.isdir(root):
        return items
    suffix = _suffix(root)
    if suffix == u".extension":
        return scan_extension(root)
    if suffix == u".tab":
        return scan_tab(root, folder_title(os.path.dirname(root)), pretty_title(root))
    for child in _subfolders(root):
        child_suffix = _suffix(child)
        if child_suffix == u".extension":
            items.extend(scan_extension(child))
        elif child_suffix == u".tab":
            items.extend(scan_tab(child, folder_title(root), pretty_title(child)))
    return items


def scan(roots, name_filter=u""):
    seen = {}
    items = []
    for root in roots:
        for item in scan_root(root):
            if item.key in seen:
                continue
            if name_filter and normalise(name_filter) not in normalise(item.extension):
                continue
            seen[item.key] = True
            items.append(item)
    return items


def default_roots():
    u"""Where pyRevit keeps extensions when nothing is nominated in settings.

    %APPDATA%\\pyRevit\\Extensions is the normal one; the folder this tool is
    installed into is added too, so the tool finds its own siblings even on a
    machine with the extensions folder somewhere unusual.
    """
    out = []
    base = os.environ.get(u"APPDATA")
    if base:
        candidate = os.path.join(base, u"pyRevit", u"Extensions")
        if os.path.isdir(candidate):
            out.append(candidate)
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        parts = here.split(os.sep)
        for index in range(len(parts) - 1, -1, -1):
            if parts[index].lower().endswith(u".extension"):
                parent = os.sep.join(parts[:index])
                if parent and os.path.isdir(parent) and parent not in out:
                    out.append(parent)
                break
    except Exception:
        pass
    return out


def resolve_roots(folders_setting):
    roots = [part.strip() for part in to_text(folders_setting).split(u"|") if part.strip()]
    roots = [root for root in roots if os.path.isdir(root)]
    if roots:
        return roots
    return default_roots()


# ----------------------------------------------------------------------
# grouping
# ----------------------------------------------------------------------

def search_split(items, search=u"", hide_unloaded=False):
    u'''Returns (primary, secondary).

    Primary is a match on the NAME. Secondary is everything that does not
    match the name but does match what the addin says it does, so searching
    "penetration" still surfaces a tool whose name never says it, without
    letting that push a real name match down the page.
    '''
    terms = [term for term in normalise(search).split(u" ") if term]
    visible = [item for item in items if item.live or not hide_unloaded]
    if not terms:
        return visible, []
    primary = []
    secondary = []
    for item in visible:
        if matches_search(item.name_text, terms):
            primary.append(item)
        elif matches_search(item.detail_text, terms):
            secondary.append(item)
    secondary.sort(key=lambda entry: natural_key(entry.title))
    return primary, secondary


def group_items(items, group_by=u"panel", search=u"", hide_unloaded=False):
    terms = [term for term in normalise(search).split(u" ") if term]
    groups = []
    index = {}
    for item in items:
        if hide_unloaded and not item.live:
            continue
        if not matches_search(item.search_text, terms):
            continue
        if group_by == u"extension":
            key = normalise(item.extension)
            title, subtitle = item.extension, u""
        elif group_by == u"tab":
            key = _key_sep().join([normalise(item.extension), normalise(item.tab)])
            title, subtitle = item.tab, item.extension
        else:
            key = _key_sep().join([normalise(item.extension), normalise(item.tab),
                                   normalise(item.panel)])
            title, subtitle = item.panel, item.tab
        if key not in index:
            group = Group(key, title, subtitle)
            index[key] = group
            groups.append(group)
        index[key].items.append(item)
    for group in groups:
        group.items.sort(key=lambda entry: natural_key(entry.title))
    groups.sort(key=lambda entry: (natural_key(entry.subtitle), natural_key(entry.title)))
    return groups
