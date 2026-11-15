# -*- coding: utf-8 -*-
u"""Project Browser Pro - the browser tree, with no WPF and no Revit in it.

Leaves are what Revit read (one per view, sheet, schedule, panel schedule or
family type). An organisation turns each leaf into a folder path; the tree is
built from those paths, sorted the natural way, and flattened into the rows
the list shows - honouring which folders are open and what the search box
holds.

Everything here runs under plain CPython on the bench against tables of
cases, which is the point of keeping it free of WPF and the Revit API.
"""
from pbp_compat import to_text, natural_key, matches

UNSET = u'???'
# Panel schedules the user has not put in a group, once any group exists.
UNGROUPED = u'Ungrouped'
# The Legends and Drafting Views tab's two fixed master groups.
LEGENDS = u'Legends'
DRAFTING = u'Drafting Views'
MASTERS = [LEGENDS, DRAFTING]

TAB_ORDER = (u'views', u'legends', u'sheets', u'schedules', u'panels', u'families')
TAB_LABELS = {
    u'all': u'All',
    u'views': u'Views',
    u'legends': u'Legends and Drafting Views',
    u'sheets': u'Sheets',
    u'panels': u'Panel Schedules',
    u'schedules': u'Schedules',
    u'families': u'Families',
    u'favourites': u'Favourites',
}
# Order ticked items open in: views, then sheets, then schedules, then panel
# schedules - each alphabetical. Families never open.
OPEN_ORDER = (u'views', u'legends', u'sheets', u'schedules', u'panels')


class Leaf(object):
    u"""One openable thing in the browser."""

    def __init__(self, key, tab, kind, text, sort_text=u'', number=u'',
                 values=None, folders=None, eid=None, uid=u'',
                 revit_sort=u'', parent=u''):
        self.key = to_text(key)
        self.tab = tab
        self.kind = kind
        self.text = to_text(text)
        self.sort_text = to_text(sort_text) or self.text
        self.revit_sort = to_text(revit_sort) or self.sort_text
        self.number = to_text(number)
        self.values = values if values is not None else {}
        self.folders = list(folders or [])
        self.eid = eid
        self.uid = to_text(uid)
        self.is_open = False
        self.is_active = False
        self.search = (self.text + u' ' + self.number).lower()
        # A dependent view names its primary's key here; build_tab nests it
        # under that leaf (children) when both land in the same folder.
        self.parent = to_text(parent)
        # ...and the read notes its primary's element id (0 for none) to
        # find that leaf by
        self.primary = 0
        self.children = []
        # The view template's name (views only): it picks the view's icon.
        self.template = u''
        # A sheet's placed views, schedules and panel schedules (the same
        # leaf objects the other tabs show), in the order Revit lists them.
        self.placed = []
        # ...and the other way: the sheets a view or schedule is placed on
        self.sheets = []


class Node(object):
    u"""A folder in the tree; the root of each tab is a Node too."""

    def __init__(self, key, label, level, tab, path):
        self.key = key
        self.label = to_text(label)
        self.level = level
        self.tab = tab
        self.path = path
        self.children = []
        self.leaves = []
        self.index = {}
        self.count = 0
        # whose organisation it is grouped by: its tab's, or (on the
        # Favourites tab) that type's favourites' own, 'fav.views'
        self.org_key = tab
        # A flat root (Favourites) lists its leaves without the dependents
        # nested under them: those belong to the Views tab, not to the star.
        self.flat = False


class Row(object):
    u"""One line of the list, flattened from the tree."""

    def __init__(self, key, text, level, heading, expanded=False, count=None,
                 leaf=None, node=None, colour_key=u'', is_root=False, tab=u'',
                 nested=False, is_parent=False, opens=False, on_sheet=None):
        self.key = key
        self.text = text
        self.level = level
        self.heading = heading
        self.expanded = expanded
        self.count = count
        self.leaf = leaf
        self.node = node
        self.colour_key = colour_key
        self.is_root = is_root
        self.tab = tab
        self.nested = nested          # a dependent drawn under its parent
        self.is_parent = is_parent    # a view with dependents under it
        # A sheet with views on it opens like a folder (opens), and each
        # placed view row names the sheet it is drawn under (on_sheet).
        self.opens = opens
        self.on_sheet = on_sheet


def group_key(tab, path):
    return u'g:{0}|{1}'.format(tab, u'\x1f'.join(path))


def root_key(tab):
    return u'r:' + tab


def path_of(leaf, org):
    u"""The folder labels a leaf sits under for this organisation."""
    source = org.get(u'source', u'none')
    if source == u'revit':
        return tuple(to_text(f) or UNSET for f in leaf.folders)
    if source == u'custom':
        return tuple(to_text(leaf.values.get(name, u'')) or UNSET
                     for name in org.get(u'levels', []))
    return ()


def _label_key(label):
    # ??? (no value) and Ungrouped go last, like Revit; everything else in
    # natural order.
    return (1 if label in (UNSET, UNGROUPED) else 0, natural_key(label))


def _leaf_key(leaf, org):
    source = org.get(u'source', u'none')
    sort = org.get(u'sort', u'')
    if source == u'revit':
        primary = leaf.revit_sort
    elif sort:
        primary = to_text(leaf.values.get(sort, u''))
    else:
        primary = leaf.sort_text
    return (natural_key(primary), natural_key(leaf.sort_text), leaf.key)


def _nest(node):
    u"""Move each dependent under its parent when both sit in this folder.

    Done per folder, after grouping, so a dependent follows its parent
    whatever the sort parameter says - sorted on its own it could land
    anywhere in the folder. One whose parent is elsewhere stays loose.
    """
    by_key = dict((leaf.key, leaf) for leaf in node.leaves)
    kept = []
    for leaf in node.leaves:
        parent = by_key.get(leaf.parent) if leaf.parent else None
        if parent is not None and parent is not leaf and not parent.parent:
            parent.children.append(leaf)
        else:
            kept.append(leaf)
    node.leaves = kept
    for leaf in kept:
        leaf.children.sort(key=lambda child: (natural_key(child.text), child.key))


def _ordered_key(label, wanted):
    u"""Labels the caller listed come first, in its order; the rest after,
    sorted as usual."""
    if wanted and label in wanted:
        return (0, wanted.index(label), (0, ()))
    return (1, 0, _label_key(label))


def _finalise(node, org, order=None, nest=True):
    if nest:
        _nest(node)
    wanted = (order or {}).get(node.level + 1)
    node.children.sort(key=lambda child: _ordered_key(child.label, wanted))
    node.leaves.sort(key=lambda leaf: _leaf_key(leaf, org))
    if org.get(u'desc'):
        node.leaves.reverse()
    total = len(node.leaves)
    if nest:
        total += sum(len(leaf.children) for leaf in node.leaves)
    for child in node.children:
        total += _finalise(child, org, order, nest)
    node.count = total
    return total


def build_tab(tab, leaves, org, prefix=None, key=None, order=None, space=None, nest=True):
    u"""Root Node for one tab under one organisation.

    prefix: an optional callable giving extra folder labels to put in front
    of the organisation's own (the panel schedule groups). key: the root's
    key when one tab has two trees (the Sheets tab filtered to a sheet set).
    order: {folder depth: [labels]} for folders that have a set order rather
    than A-Z (the Families tab's main groups).
    space: the organisation key the folders belong to, when not the tab's
    own ('fav.views': the favourite views grouped their own way) - it keys
    the folders apart from the tab's. nest=False leaves the leaves' own
    dependents alone (they belong to the tab's tree) and draws flat.
    """
    space = space or tab
    root = Node(key or root_key(tab), TAB_LABELS.get(tab, tab), 0, tab, ())
    root.org_key = space
    if nest:
        for leaf in leaves:
            del leaf.children[:]   # leaves are reused across rebuilds
    for leaf in leaves:
        path = path_of(leaf, org)
        if prefix is not None:
            path = tuple(prefix(leaf)) + path
        node = root
        for depth in range(len(path)):
            sub = path[:depth + 1]
            key = group_key(space, sub)
            child = node.index.get(key)
            if child is None:
                child = Node(key, path[depth], depth + 1, tab, sub)
                child.org_key = space
                child.flat = not nest
                node.index[key] = child
                node.children.append(child)
            node = child
        node.leaves.append(leaf)
    _finalise(root, org, order, nest)
    return root


def _hits(node, words, labels, hits, leaf_hits, flat=False):
    total = 0
    here = labels + [node.label] if node.level > 0 else labels
    for child in node.children:
        total += _hits(child, words, here, hits, leaf_hits, child.flat)
    context = u' '.join(here).lower()
    for leaf in node.leaves:
        own = matches(leaf.search + u' ' + context, words)
        if own:
            leaf_hits.add(leaf.key)
            total += 1
        for child in ([] if flat else leaf.children):
            if matches(child.search + u' ' + context, words):
                leaf_hits.add(child.key)
                total += 1
                # a matching dependent brings its parent with it, for context
                leaf_hits.add(leaf.key)
    hits[node.key] = total
    return total


def flatten(roots, collapsed, search_words, show_roots, open_sheets=None):
    u"""The rows to show, top to bottom.

    State is the set of folders the user has CLOSED, so everything starts
    open and a folder that appears later (a refresh, a new organisation)
    is open too. With search words every folder holding a match is shown
    open whatever `collapsed` says, and folder counts are the number of
    matches in them. Folders come before loose items at each level, as in
    Revit. A sheet whose key is in open_sheets is followed by the views,
    schedules and panel schedules placed on it (all sheets start shut, as
    in Revit).
    """
    open_sheets = open_sheets or set()
    rows = []
    searching = bool(search_words)
    for root in roots:
        hits = {}
        leaf_hits = set()
        if searching:
            _hits(root, search_words, [], hits, leaf_hits, root.flat)
            if not hits.get(root.key):
                continue
        count = hits.get(root.key, 0) if searching else root.count
        if show_roots:
            is_open = searching or root.key not in collapsed
            rows.append(Row(root.key, root.label, 0, True, is_open, count,
                            node=root, is_root=True, tab=root.tab))
            if not is_open:
                continue
            base = 1
        else:
            base = 0
        _walk(root, base, collapsed, searching, hits, leaf_hits, rows, u'', root.flat, open_sheets)
    return rows


def placed_key(sheet, leaf):
    return u'p:{0}>{1}'.format(sheet.key, leaf.key)


def _walk(node, level, collapsed, searching, hits, leaf_hits, rows, colour_key, flat=False,
          open_sheets=frozenset()):
    for child in node.children:
        if searching and not hits.get(child.key):
            continue
        is_open = searching or child.key not in collapsed
        count = hits.get(child.key, 0) if searching else child.count
        rows.append(Row(child.key, child.label, level, True, is_open, count,
                        node=child, colour_key=child.key, tab=child.tab))
        if is_open:
            # flat is the root's own: a favourite group under a flat root
            # nests its dependents as the Views tab does
            _walk(child, level + 1, collapsed, searching, hits, leaf_hits,
                  rows, child.key, child.flat, open_sheets)
    for leaf in node.leaves:
        if searching and leaf.key not in leaf_hits:
            continue
        opens = bool(leaf.placed)
        is_open = opens and leaf.key in open_sheets
        rows.append(Row(leaf.key, leaf.text, level, False, expanded=is_open, leaf=leaf,
                        colour_key=colour_key, tab=leaf.tab,
                        is_parent=bool(leaf.children) and not flat, opens=opens))
        if is_open:
            for placed in leaf.placed:
                rows.append(Row(placed_key(leaf, placed), placed.text, level, False, leaf=placed,
                                colour_key=colour_key, tab=placed.tab, nested=True,
                                on_sheet=leaf))
        if flat:
            continue
        for child in leaf.children:
            if searching and child.key not in leaf_hits:
                continue
            rows.append(Row(child.key, child.text, level, False, leaf=child,
                            colour_key=colour_key, tab=child.tab, nested=True))


def all_group_keys(roots):
    keys = set()

    def visit(node):
        keys.add(node.key)
        for child in node.children:
            visit(child)
    for root in roots:
        visit(root)
    return keys


def default_collapsed():
    u"""Nothing closed. (Since 1.7.0 the browser starts every tab as
    Collapse all leaves it, and remembers what is opened - see
    BrowserControl._collapsed_for.)"""
    return set()


def collapse_all_state(roots, show_roots):
    u"""Every folder closed - except the type roots on the All tab, which
    stay open so Collapse all still shows Views / Sheets / ... headings.

    Flat roots (Favourites) have nothing under them but leaves, so there
    Collapse all closes the type roots themselves."""
    keys = all_group_keys(roots)
    if show_roots:
        keys -= set(root.key for root in roots if not root.flat)
    return keys


def is_collapsed(collapsed, roots, show_roots):
    u"""True when every folder Collapse all would close is closed - the
    button then offers Expand all."""
    wanted = collapse_all_state(roots, show_roots)
    return bool(wanted) and wanted <= set(collapsed)


def toggle(collapsed, key):
    result = set(collapsed)
    if key in result:
        result.discard(key)
    else:
        result.add(key)
    return result


def open_order(leaves):
    u"""Views A-Z, then sheets A-Z, then schedules, then panel schedules."""
    ordered = []
    for tab in OPEN_ORDER:
        group = [leaf for leaf in leaves if leaf.tab == tab]
        group.sort(key=lambda leaf: (natural_key(leaf.number + u' ' + leaf.text)
                                     if tab == u'sheets' else natural_key(leaf.text)))
        ordered.extend(group)
    return ordered


def sheet_leaves(leaves):
    return [leaf for leaf in leaves if leaf.tab == u'sheets']


def unique_leaves(rows):
    u"""Leaves of the given rows, each once, in row order."""
    seen = set()
    out = []
    for row in rows:
        leaf = row.leaf
        if leaf is None or leaf.key in seen:
            continue
        seen.add(leaf.key)
        out.append(leaf)
    return out


def leaves_under(node, flat=False):
    out = []
    for leaf in node.leaves:
        out.append(leaf)
        if not flat:
            out.extend(leaf.children)
    for child in node.children:
        out.extend(leaves_under(child, flat))
    return out


def find_node(root, path):
    u"""The folder at these labels under a root, or None."""
    node = root
    for label in path:
        found = None
        for child in node.children:
            if child.label == label:
                found = child
                break
        if found is None:
            return None
        node = found
    return node


def build_favourites(fav_by_tab, groups_by_tab=None, orgs=None):
    u"""One flat root per type for the Favourites tab, in the browser's
    type order: Views, Sheets, Schedules, Panel Schedules, Families.

    The leaves are the same objects the other tabs show, so a favourite is
    open / active / renamed exactly as it is there. Nothing here touches a
    leaf's children (the Views tab owns those); the roots are flat instead.
    Sheets sort by number, everything else by name.

    groups_by_tab: {tab: [Node]} - whole folders made favourites. They are
    the tab's own folder nodes, listed under the type root as they are, so
    they keep their keys (and with them their colours). A group inside
    another favourite group, and a single favourite inside a favourite
    group, are shown once - inside the group.
    orgs: {tab: organisation} - how each type's favourites are grouped
    (1.7.0), apart from the type's own tab. 'none' (the default) lists them
    loose, as before; otherwise they sit in folders of their own, keyed
    'fav.<tab>' so they never clash with the tab's folders, flat (a view's
    dependents stay on the Views tab), and the root notes them as
    `organised` for the colours. Whole folders made favourites follow them.
    """
    groups_by_tab = groups_by_tab or {}
    orgs = orgs or {}
    roots = []
    for tab in TAB_ORDER:
        groups = _outermost(groups_by_tab.get(tab, []))
        inside = set()
        for group in groups:
            inside.update(leaf.key for leaf in leaves_under(group))
        leaves = [leaf for leaf in fav_by_tab.get(tab, []) if leaf.key not in inside]
        if not leaves and not groups:
            continue
        org = orgs.get(tab) or {}
        groups = sorted(groups, key=lambda node: [natural_key(p) for p in node.path])
        if org.get(u'source', u'none') != u'none' and leaves:
            root = build_tab(tab, leaves, org, key=u'f:' + tab, space=u'fav.' + tab, nest=False)
            root.organised = list(root.children)
            root.children = root.children + groups
            root.count = root.count + sum(group.count for group in groups)
        else:
            root = Node(u'f:' + tab, TAB_LABELS.get(tab, tab), 0, tab, ())
            root.org_key = u'fav.' + tab
            root.organised = []
            if tab == u'sheets':
                leaves.sort(key=lambda leaf: (natural_key(leaf.number), natural_key(leaf.text), leaf.key))
            else:
                leaves.sort(key=lambda leaf: (natural_key(leaf.text), leaf.key))
            root.leaves = leaves
            root.children = groups
            root.count = len(leaves) + sum(group.count for group in root.children)
        root.flat = True
        roots.append(root)
    return roots


def _outermost(nodes):
    u"""Drop any folder that sits inside another one in the list."""
    paths = [tuple(node.path) for node in nodes]
    kept = []
    for node in nodes:
        path = tuple(node.path)
        if any(other != path and path[:len(other)] == other for other in paths):
            continue
        if node not in kept:
            kept.append(node)
    return kept


def inside_keys(node):
    u"""Every folder key below a node (not the node itself)."""
    keys = set()

    def visit(current):
        for child in current.children:
            keys.add(child.key)
            visit(child)
    visit(node)
    return keys


def panel_prefix(group_of, any_groups):
    u"""The prefix callable build_tab takes for panel schedules: the group a
    panel is in, Ungrouped for the rest - or nothing at all until the user
    makes a first group, so the tab looks as it did."""
    if not any_groups:
        return None

    def prefix(leaf):
        return (group_of(leaf.uid) or UNGROUPED,)
    return prefix


def locate(roots, keys):
    u"""{leaf key: [folder keys above it, the root included]} for each of
    these keys found in these trees - what must be opened to show them."""
    wanted = set(keys)
    found = {}

    def visit(node, above):
        here = above + [node.key]
        for leaf in node.leaves:
            if leaf.key in wanted and leaf.key not in found:
                found[leaf.key] = list(here)
            for child in leaf.children:
                if child.key in wanted and child.key not in found:
                    found[child.key] = list(here)
        for child in node.children:
            visit(child, here)
    for root in roots:
        visit(root, [])
    return found
