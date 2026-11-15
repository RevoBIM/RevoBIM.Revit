# -*- coding: utf-8 -*-
u"""RevoBIM PY - Hide Service Type : hide selection templates.

A template says WHAT to hide, never which element ids - so one template works
on every view and every project:

    {"source": "host",      "kind": "service", "cat": -2008044,
     "cat_name": "Pipes",   "group": "pipe",   "value": "Vent"}
    {"source": "BGL_MECH",  "kind": "category", "cat": -2000011,
     "cat_name": "Walls"}
    {"source": "BGL_ARCH",  "kind": "source"}          <- the whole link

Rows are the list's cover - the fewest rows that say what was ticked - so a
fully ticked category is one row, not one per service under it.  A linked row
names its link by title; every instance of that link in the view takes it.

Stored per user in %APPDATA%\\RevoBIM\\hide_templates.json with the name of the
last one used, which Hide Service Type applies when run with nothing selected.
"""

import ist_clr  # noqa: F401  - assemblies first, always

import io
import json
import os
import re
import time

import ist_browse
import ist_core

TEMPLATES_PATH = os.path.join(ist_core.SETTINGS_DIR, u"hide_templates.json")

_COPY = re.compile(u" \\(\\d+\\)$")


# ===========================================================================
# the store
# ===========================================================================

def load():
    try:
        if os.path.isfile(TEMPLATES_PATH):
            handle = io.open(TEMPLATES_PATH, u"r", encoding=u"utf-8")
            try:
                data = json.loads(handle.read())
            finally:
                handle.close()
            if isinstance(data, dict) and isinstance(
                    data.get(u"templates"), dict):
                data.setdefault(u"last", None)
                return data
    except Exception:
        pass
    return {u"last": None, u"templates": {}}


def save(data):
    try:
        folder = os.path.dirname(TEMPLATES_PATH)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)
        text = json.dumps(data, indent=1, sort_keys=True)
        if not isinstance(text, type(u"")):
            text = text.decode(u"utf-8")
        handle = io.open(TEMPLATES_PATH, u"w", encoding=u"utf-8")
        try:
            handle.write(text)
        finally:
            handle.close()
        return True
    except Exception:
        return False


def names():
    return sorted(load()[u"templates"].keys(), key=lambda n: n.lower())


def get(name):
    if not name:
        return None
    return load()[u"templates"].get(name)


def put(name, rows):
    name = (name or u"").strip()
    if not name:
        return False
    data = load()
    data[u"templates"][name] = {u"rows": rows, u"saved": time.time()}
    return save(data)


def remove(name):
    data = load()
    if name in data[u"templates"]:
        del data[u"templates"][name]
        if data.get(u"last") == name:
            data[u"last"] = None
        return save(data)
    return False


def last_name():
    data = load()
    name = data.get(u"last")
    if name and name in data[u"templates"]:
        return name
    return None


def set_last(name):
    data = load()
    data[u"last"] = name if name in data[u"templates"] else None
    save(data)


# ===========================================================================
# rows <-> the list
# ===========================================================================

def link_title(node):
    u"""The link's own title, without the " (2)" the list adds to repeats."""
    return _COPY.sub(u"", node.label or u"")


def _source_of(node):
    while node is not None and node.kind not in (u"source", u"root"):
        node = node.parent
    return node


def row_of(node):
    u"""What a ticked row means, in words that survive into another view."""
    source = _source_of(node)
    is_host = source is not None and source.link_id is None and \
        source.kind == u"source"
    where = u"host" if is_host else link_title(source) if source else u"?"
    if node.kind == u"source":
        return {u"source": where, u"kind": u"source"}
    rule = dict(node.rule or {})
    row = {u"source": where, u"kind": node.kind,
           u"cat": rule.get(u"cat"), u"cat_name": rule.get(u"cat_name")}
    for key in (u"group", u"value", u"family", u"type"):
        if key in rule:
            row[key] = rule[key]
    return row


def rows_from(host_root, links_root):
    rows = []
    for root in (host_root, links_root):
        if root is None:
            continue
        for node in ist_browse.cover(root):
            rows.append(row_of(node))
    return rows


def _find(source, row, case_sensitive):
    if row.get(u"kind") == u"source":
        return source
    cat = source.find(row.get(u"cat"))
    if cat is None or row.get(u"kind") == u"category":
        return cat
    if row.get(u"kind") == u"service":
        return cat.find((u"s", ist_core.normalise(row.get(u"value"),
                                                  case_sensitive)))
    family = cat.find((u"f", (row.get(u"family") or u"").lower()))
    if family is None or row.get(u"kind") == u"family":
        return family
    return family.find((u"t", (row.get(u"type") or u"").lower()))


def apply_rows(host_root, links_root, rows, values, loader=None):
    u"""Tick what a template names.  `loader(node)` reads a link the template
    reaches into before it has been opened.  Returns (ticked, missing) where
    missing is the rows this view has nothing for - a template made in another
    view can name a service that is not drawn here."""
    case_sensitive = ist_core.is_on(values, u"match_case")
    for root in (host_root, links_root):
        if root is None:
            continue
        for node in root.walk():
            node.checked = False
    ticked = 0
    missing = []
    for row in rows or ():
        if row.get(u"source") == u"host":
            sources = [host_root] if host_root is not None else []
        else:
            sources = [n for n in (links_root.children if links_root else [])
                       if link_title(n) == row.get(u"source")]
        hit = False
        for source in sources:
            if row.get(u"kind") != u"source" and not source.loaded and \
                    loader is not None:
                loader(source)
            node = _find(source, row, case_sensitive)
            if node is not None:
                ist_browse.set_checked(node, True)
                hit = True
        if hit:
            ticked += 1
        else:
            missing.append(row)
    return ticked, missing


def describe_row(row):
    parts = [u"this model" if row.get(u"source") == u"host"
             else row.get(u"source") or u"?"]
    if row.get(u"kind") != u"source":
        parts.append(row.get(u"cat_name") or u"?")
    for key in (u"value", u"family", u"type"):
        if row.get(key):
            parts.append(row[key])
    return u" > ".join(parts)


def plan_from_template(doc, view, values, name):
    u"""Everything Hide needs to hide a template in `view` without showing
    the list.  Returns (summary, missing, error)."""
    template = get(name)
    if template is None:
        return None, [], u"There is no template called {0}.".format(name)
    host_root = ist_browse.build_host(doc, view, values)
    links_root = ist_browse.build_links_root(doc, view)
    filterable = ist_browse.filterable_category_ints()

    def loader(node):
        ist_browse.load_link(node, doc, view, values, host_root, filterable)

    _, missing = apply_rows(host_root, links_root, template.get(u"rows"),
                            values, loader)
    summary = ist_browse.summarise(host_root, links_root)
    summary[u"template"] = name
    return summary, missing, None
