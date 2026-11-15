# -*- coding: utf-8 -*-
u"""RevoBIM PY - Hide Service Type : the category list.

Everything the list window shows, with no WPF in it, so the bench can drive it.

    This model
        Pipes                         <- a service category
            Vent            142
            Soil             88
        Walls                         <- anything else
            Basic Wall
                100 Blockwork  64
    Linked models
        BGL_MECH.rvt                  <- built the first time it is opened
            Pipes
                Vent        142   (+0 in this model)

Host elements are hidden by id.  Linked elements cannot be - Revit's API will
not hide a linked element by id, temporarily or otherwise - so a ticked linked
row becomes a view filter, named for exactly what it hides, and the reset takes
the filters away again.  A filter cannot tell host from link, so each linked
row carries how many host elements in the view the same filter would also
catch.
"""

import ist_clr  # noqa: F401  - assemblies first, always

from Autodesk.Revit.DB import (
    CategoryType,
    FilteredElementCollector,
    RevitLinkInstance,
)

import ist_core
from ist_core import eid_value, normalise

HOST_LABEL = u"This model"
LINKS_LABEL = u"Linked models"
NO_SERVICE = u"(no service type)"
NO_FAMILY = u"(no family)"
NO_TYPE = u"(no type)"

# Never listed: the box that frames the view, the cameras and the link
# instances themselves (a whole link is hidden from its own row instead).
EXCLUDED = (u"OST_SectionBox", u"OST_Cameras", u"OST_RvtLinks")

# Which parameter a linked service row is filtered on, per discipline.  Revit's
# own built-ins, so a filter made in the host matches a linked model's elements
# whatever language either was authored in.
SERVICE_FILTER_BIP = {
    u"tray": u"RBS_CTC_SERVICE_TYPE",
    u"conduit": u"RBS_CTC_SERVICE_TYPE",
    u"duct": u"RBS_DUCT_SYSTEM_TYPE_PARAM",
    u"pipe": u"RBS_PIPING_SYSTEM_TYPE_PARAM",
}

FAMILY_BIP = u"ALL_MODEL_FAMILY_NAME"
TYPE_BIP = u"ALL_MODEL_TYPE_NAME"

# Characters Revit refuses in a filter name.
_BAD_NAME_CHARS = u'\\:{}[]|;<>?`~'


# ===========================================================================
# the tree
# ===========================================================================

class Node(object):
    u"""One row.  `checked` is True, False, or None for partly ticked."""

    def __init__(self, label, kind, parent=None):
        self.label = label
        self.kind = kind          # root | source | category | service | family | type
        self.parent = parent
        self.children = []
        self._index = {}
        self.ids = []             # host element ids, on the leaves only
        self.count = 0
        self.collateral = 0       # linked rows: host elements the filter would catch
        self.rule = None          # linked rows: what a filter on this row means
        self.checked = False
        self.loaded = True        # a link is False until it is opened
        self.link_id = None       # a link source: the RevitLinkInstance id
        self.note = u""
        self.ui = None            # the window hangs its controls here

    def child(self, key, label, kind):
        node = self._index.get(key)
        if node is None:
            node = Node(label, kind, self)
            self._index[key] = node
            self.children.append(node)
        return node

    def find(self, key):
        return self._index.get(key)

    def walk(self):
        yield self
        for child in self.children:
            for node in child.walk():
                yield node

    def leaves(self):
        if not self.children:
            yield self
            return
        for child in self.children:
            for leaf in child.leaves():
                yield leaf


def _finish(node):
    u"""Counts up the tree, children sorted by label with the blanks last."""
    if node.children:
        total = 0
        for child in node.children:
            total += _finish(child)
        node.children.sort(key=lambda n: (n.label.startswith(u"("),
                                          n.label.lower()))
        if node.kind not in (u"root",):
            node.count = total
        return node.count if node.kind != u"root" else total
    if node.ids:
        node.count = len(node.ids)
    return node.count


# ===========================================================================
# ticking
# ===========================================================================

def set_checked(node, state):
    u"""A click: the row and everything under it, then the rows above it."""
    for each in node.walk():
        each.checked = bool(state)
    parent = node.parent
    while parent is not None:
        parent.checked = aggregate(parent)
        parent = parent.parent


def aggregate(node):
    if not node.children:
        return node.checked
    states = set(child.checked for child in node.children)
    if states == set([True]):
        return True
    if states == set([False]):
        return False
    return None


def cover(node):
    u"""The fewest rows that say what is ticked: a fully ticked category is
    one filter, not one per service under it."""
    if node.checked is True and node.kind not in (u"root",):
        return [node]
    if node.checked is False and node.kind != u"root":
        return []
    out = []
    for child in node.children:
        out.extend(cover(child))
    return out


def host_ids(nodes):
    out = set()
    for node in nodes:
        for leaf in node.leaves():
            out.update(leaf.ids)
    return out


def summarise(host_root, links_root):
    u"""What the footer says and what the Hide button will do."""
    host_rows = cover(host_root) if host_root is not None else []
    ids = host_ids(host_rows)
    link_rows = cover(links_root) if links_root is not None else []
    whole_links = [n for n in link_rows if n.kind == u"source"]
    filters = [n for n in link_rows if n.kind != u"source"]
    collateral = 0
    for node in filters:
        collateral += node.collateral
    return {
        u"host_ids": ids,
        u"whole_links": whole_links,
        u"filters": filters,
        u"collateral": collateral,
        u"empty": not ids and not whole_links and not filters,
    }


# ===========================================================================
# reading elements
# ===========================================================================

def type_name_of(doc, element, cache):
    u"""(family, type) by type id, cached.  Element.Name on a FamilySymbol is
    unreachable as a plain attribute in IronPython, hence the fallbacks."""
    try:
        type_id = element.GetTypeId()
    except Exception:
        return (u"", u"")
    key = eid_value(type_id)
    if key in cache:
        return cache[key]
    family = u""
    name = u""
    try:
        symbol = doc.GetElement(type_id)
    except Exception:
        symbol = None
    if symbol is not None:
        try:
            family = u"{0}".format(getattr(symbol, u"FamilyName", u"") or u"")
        except Exception:
            family = u""
        try:
            name = u"{0}".format(symbol.Name or u"")
        except Exception:
            try:
                from Autodesk.Revit.DB import Element
                name = u"{0}".format(Element.Name.GetValue(symbol) or u"")
            except Exception:
                name = u""
    cache[key] = (family, name)
    return (family, name)


def _model_category(element, excluded):
    try:
        category = element.Category
    except Exception:
        return None
    if category is None:
        return None
    try:
        if category.CategoryType != CategoryType.Model:
            return None
    except Exception:
        return None
    if eid_value(category.Id) in excluded:
        return None
    return category


def _excluded_ints(values):
    out = set()
    names = list(EXCLUDED)
    if ist_core.is_on(values, u"include_insulation"):
        # Insulation travels with what it wraps, so it is not a row of its own.
        names.extend(ist_core.INSULATION_CATS)
    for name in names:
        member = ist_core.bic(name)
        if member is not None:
            try:
                out.add(int(member))
            except Exception:
                continue
    return out


class Grouper(object):
    u"""Puts an element in its row: service categories by service, everything
    else by family then type."""

    def __init__(self, doc, values):
        self.doc = doc
        self.values = values
        self.case_sensitive = ist_core.is_on(values, u"match_case")
        self.active_cats = {}
        for group in ist_core.GROUP_KEYS:
            self.active_cats[group] = ist_core.cats_of(values, group)
        self.id_to_cat = ist_core.category_ids()
        fallback = ist_core.is_on(values, u"fallback_builtin")
        self.readers = {}
        for group in ist_core.GROUP_KEYS:
            self.readers[group] = ist_core.ValueReader(
                doc, ist_core.param_of(values, group), group, fallback)
        self.type_cache = {}

    def place(self, root, element, category):
        cat_int = eid_value(category.Id)
        cat_node = root.child(cat_int, category.Name, u"category")
        cat_node.rule = {u"cat": cat_int, u"cat_name": category.Name}
        cat_name = self.id_to_cat.get(cat_int)
        groups = ist_core.groups_for_category(cat_name, self.active_cats) \
            if cat_name else []
        if groups:
            group = groups[0]
            value = self.readers[group].value(element)
            key = normalise(value, self.case_sensitive)
            leaf = cat_node.child((u"s", key), value or NO_SERVICE, u"service")
            leaf.rule = {u"cat": cat_int, u"cat_name": category.Name,
                         u"group": group, u"value": value or u""}
            return leaf
        family, type_name = type_name_of(self.doc, element, self.type_cache)
        fam_node = cat_node.child((u"f", family.lower()), family or NO_FAMILY,
                                  u"family")
        fam_node.rule = {u"cat": cat_int, u"cat_name": category.Name,
                         u"family": family}
        leaf = fam_node.child((u"t", type_name.lower()), type_name or NO_TYPE,
                              u"type")
        leaf.rule = {u"cat": cat_int, u"cat_name": category.Name,
                     u"family": family, u"type": type_name}
        return leaf


def build_host(doc, view, values):
    u"""Every model element drawn in the view, one collector pass."""
    root = Node(HOST_LABEL, u"source")
    excluded = _excluded_ints(values)
    grouper = Grouper(doc, values)
    collector = FilteredElementCollector(doc, view.Id)\
        .WhereElementIsNotElementType()
    for element in collector:
        category = _model_category(element, excluded)
        if category is None:
            continue
        leaf = grouper.place(root, element, category)
        leaf.ids.append(eid_value(element.Id))
    _finish(root)
    return root


def host_lookup(host_root, rule, case_sensitive=False):
    u"""How many host elements in the view a filter for `rule` also catches -
    read off the host tree rather than counted again."""
    if host_root is None or not rule:
        return 0
    cat_node = host_root.find(rule.get(u"cat"))
    if cat_node is None:
        return 0
    if u"group" in rule:
        leaf = cat_node.find((u"s", normalise(rule.get(u"value"),
                                              case_sensitive)))
        return leaf.count if leaf is not None else 0
    if u"type" in rule:
        fam = cat_node.find((u"f", (rule.get(u"family") or u"").lower()))
        if fam is None:
            return 0
        leaf = fam.find((u"t", (rule.get(u"type") or u"").lower()))
        return leaf.count if leaf is not None else 0
    if u"family" in rule:
        fam = cat_node.find((u"f", (rule.get(u"family") or u"").lower()))
        return fam.count if fam is not None else 0
    return cat_node.count


# ===========================================================================
# linked models
# ===========================================================================

def link_instances(doc, view):
    u"""The links drawn in this view, loaded ones only."""
    out = []
    try:
        collector = FilteredElementCollector(doc, view.Id)\
            .OfClass(RevitLinkInstance)
    except Exception:
        return out
    for inst in collector:
        try:
            link_doc = inst.GetLinkDocument()
        except Exception:
            link_doc = None
        if link_doc is None:
            continue
        out.append((inst, link_doc))
    return out


def link_shows_host_filters(view, inst):
    u"""Host filters only reach a link displayed By Host View.  Revit 2024
    added the call to ask; on anything older, or if it throws, assume yes."""
    try:
        settings = view.GetLinkOverrides(inst.Id)
    except Exception:
        return True
    if settings is None:
        return True
    try:
        kind = u"{0}".format(settings.LinkVisibilityType)
    except Exception:
        return True
    return kind in (u"ByHostView", u"0", u"")


def build_links_root(doc, view):
    u"""One unopened row per link.  Opening one reads it."""
    root = Node(LINKS_LABEL, u"root")
    labels = {}
    for inst, link_doc in link_instances(doc, view):
        title = u"{0}".format(link_doc.Title or u"Link")
        labels[title] = labels.get(title, 0) + 1
        label = title if labels[title] == 1 else u"{0} ({1})".format(
            title, labels[title])
        node = root.child(eid_value(inst.Id), label, u"source")
        node.parent = root
        node.link_id = inst.Id
        node.loaded = False
        node.inst = inst
        node.link_doc = link_doc
        if not link_shows_host_filters(view, inst):
            node.note = (u"shown By Linked View or Custom - filters from this "
                         u"view will not reach it; a whole-link tick still "
                         u"hides it")
    return root


def filterable_category_ints():
    try:
        from Autodesk.Revit.DB import ParameterFilterUtilities
        return set(eid_value(i) for i in
                   ParameterFilterUtilities.GetAllFilterableCategories())
    except Exception:
        return None


def link_elements(doc, view, inst, link_doc):
    u"""What of the link is drawn in this view.  The view-scoped link collector
    arrived in Revit 2024; where it is missing, the whole link is read and the
    row says so."""
    try:
        return list(FilteredElementCollector(doc, view.Id, inst.Id)
                    .WhereElementIsNotElementType()), True
    except Exception:
        pass
    try:
        return list(FilteredElementCollector(link_doc)
                    .WhereElementIsNotElementType()), False
    except Exception:
        return [], False


def load_link(node, doc, view, values, host_root, filterable=None):
    u"""Read one link into its row."""
    if node.loaded:
        return node
    elements, scoped = link_elements(doc, view, node.inst, node.link_doc)
    excluded = _excluded_ints(values)
    grouper = Grouper(node.link_doc, values)
    if filterable is None:
        filterable = filterable_category_ints()
    skipped = set()
    for element in elements:
        category = _model_category(element, excluded)
        if category is None:
            continue
        cat_int = eid_value(category.Id)
        # A project's own categories (positive ids) do not exist in the host,
        # and some built-ins cannot be filtered at all.
        if cat_int > 0 or (filterable is not None and cat_int not in filterable):
            skipped.add(category.Name)
            continue
        leaf = grouper.place(node, element, category)
        leaf.count += 1
    _finish_link(node)
    case_sensitive = ist_core.is_on(values, u"match_case")
    for each in node.walk():
        if each is node:
            continue
        each.collateral = host_lookup(host_root, each.rule, case_sensitive)
    notes = []
    if node.note:
        notes.append(node.note)
    if not scoped:
        notes.append(u"this Revit cannot read a link per view, so the whole "
                     u"link is listed")
    if skipped:
        notes.append(u"not listed, cannot be filtered: {0}".format(
            u", ".join(sorted(skipped))))
    node.note = u"; ".join(notes)
    node.loaded = True
    if node.checked is True:
        for each in node.walk():
            each.checked = True
    return node


def _finish_link(node):
    for child in node.children:
        _finish_link(child)
    if node.children:
        node.count = sum(c.count for c in node.children)
        node.children.sort(key=lambda n: (n.label.startswith(u"("),
                                          n.label.lower()))


# ===========================================================================
# what a filter on a linked row means
# ===========================================================================

def filter_name(rule):
    u"""Named for exactly what it hides, so a second run on the same row finds
    the filter it already made rather than making another."""
    parts = [rule.get(u"cat_name") or u"?"]
    if u"group" in rule:
        parts.append(rule.get(u"value") or u"no service type")
    elif u"type" in rule:
        parts.append(rule.get(u"family") or u"no family")
        parts.append(rule.get(u"type") or u"no type")
    elif u"family" in rule:
        parts.append(rule.get(u"family") or u"no family")
    text = u"{0} - {1}".format(ist_core.TEMP_FILTER_PREFIX, u" - ".join(parts))
    clean = u"".join(u"_" if ch in _BAD_NAME_CHARS else ch for ch in text)
    return clean[:200].strip()


def filter_plan(rule, values, shared_ok=None):
    u"""The rules one filter will carry, as plain data:

        [("bip" | "shared", name, "equals" | "novalue", value), ...]

    An empty list is a category-only filter.  `shared_ok(name)` answers
    whether the configured service parameter is a shared parameter the host
    also has; when it is, the filter uses it, otherwise Revit's built-in.
    """
    if u"group" in rule:
        group = rule[u"group"]
        name = ist_core.param_of(values, group)
        value = rule.get(u"value") or u""
        test = u"equals" if value else u"novalue"
        if shared_ok is not None and shared_ok(name):
            return [(u"shared", name, test, value)]
        return [(u"bip", SERVICE_FILTER_BIP[group], test, value)]
    if u"type" in rule:
        return [(u"bip", FAMILY_BIP, u"equals", rule.get(u"family") or u""),
                (u"bip", TYPE_BIP, u"equals", rule.get(u"type") or u"")]
    if u"family" in rule:
        return [(u"bip", FAMILY_BIP, u"equals", rule.get(u"family") or u"")]
    return []
