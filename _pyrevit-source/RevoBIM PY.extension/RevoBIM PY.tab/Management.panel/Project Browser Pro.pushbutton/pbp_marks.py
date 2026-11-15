# -*- coding: utf-8 -*-
u"""Project Browser Pro - what the user has marked, per project.

Favourites (and the colour each is given), panel schedule groups and the
sheet set the Sheets tab is filtered to. All keyed by UniqueId, which
survives renames, renumbering and closing the model - an element id would
too, but a UniqueId is what Revit promises.

One key=value file per project:
    %APPDATA%\\RevoBIM\\project_browser_pro_marks\\<project>.txt

    fav.<uid>=<tab>              a favourite, and which tab it came from
    colour.<uid>=c3              a favourite's colour (a slot, not a hex,
                                 so it follows dark and light)
    group.<uid>=<group name>     a panel schedule's group
    sheet_set=<set name>         blank = all sheets
    favgroup.<n>=<tab>|<labels>  a whole folder made a favourite (1.3.0)
    fold.<where>=+<key>|-<key>   folders opened (+) or closed (-) against
                                 the default, per tab or pinned copy (1.7.0)

Marks for elements that no longer exist are kept rather than pruned: a
sheet deleted and undone keeps its star, and a favourite in a linked or
unloaded state comes back. They simply match nothing while gone.

Pure Python, tested on the bench.
"""
import os

from pbp_compat import to_text, safe_file_part, natural_key
from pbp_settings import read_pairs, write_pairs, escape_list, unescape_list

FOLDER = u'project_browser_pro_marks'
MARKS_VERSION = 1
COLOUR_SLOTS = 10


def marks_path(folder, project_title):
    return os.path.join(folder, FOLDER, safe_file_part(project_title) + u'.txt')


def colour_slot(text):
    u"""'c0'..'c9', or u'' for anything else."""
    text = to_text(text).strip().lower()
    if len(text) >= 2 and text[0] == u'c' and text[1:].isdigit():
        if 0 <= int(text[1:]) < COLOUR_SLOTS:
            return u'c' + to_text(int(text[1:]))
    return u''


def clean_group(name):
    u"""A group name safe to store: no line breaks, no leading/trailing space."""
    return u' '.join(to_text(name).replace(u'\r', u' ').replace(u'\n', u' ').split())


class Marks(object):

    def __init__(self, folder=u'', project=u''):
        self.folder = folder
        self.project = to_text(project)
        self.favs = {}      # uid -> tab
        self.colours = {}   # uid -> 'c0'..'c9'
        self.groups = {}    # uid -> group name
        self.sheet_set = u''
        self.fav_groups = []   # [(tab, (folder labels...))]
        # where ('views', 'favourites', 'pin:3') -> (opened keys, closed keys)
        self.folds = {}

    # ---- file ----
    @classmethod
    def load(cls, folder, project):
        marks = cls(folder, project)
        pairs = read_pairs(marks_path(folder, project)) if project else {}
        for key, value in pairs.items():
            value = to_text(value)
            if key.startswith(u'fav.') and value:
                marks.favs[key[4:]] = value
            elif key.startswith(u'colour.'):
                slot = colour_slot(value)
                if slot:
                    marks.colours[key[7:]] = slot
            elif key.startswith(u'group.'):
                name = clean_group(value)
                if name:
                    marks.groups[key[6:]] = name
            elif key == u'sheet_set':
                marks.sheet_set = value.strip()
            elif key.startswith(u'fold.'):
                opened, shut = set(), set()
                for item in unescape_list(value):
                    if item[:1] == u'+':
                        opened.add(item[1:])
                    elif item[:1] == u'-':
                        shut.add(item[1:])
                marks.folds[key[5:]] = (opened, shut)
            elif key.startswith(u'favgroup.'):
                parts = unescape_list(value)
                if len(parts) >= 2:
                    marks.fav_groups.append((key[9:], (parts[0], tuple(parts[1:]))))
        marks.fav_groups = [group for order, group in
                            sorted(marks.fav_groups, key=lambda item: natural_key(item[0]))]
        return marks

    def to_pairs(self):
        pairs = {u'marks_version': to_text(MARKS_VERSION)}
        for uid, tab in self.favs.items():
            pairs[u'fav.' + uid] = tab
        for uid, slot in self.colours.items():
            pairs[u'colour.' + uid] = slot
        for uid, name in self.groups.items():
            pairs[u'group.' + uid] = name
        pairs[u'sheet_set'] = self.sheet_set
        for index, (tab, path) in enumerate(self.fav_groups):
            pairs[u'favgroup.{0}'.format(index)] = escape_list([tab] + list(path))
        for where, (opened, shut) in self.folds.items():
            if opened or shut:
                pairs[u'fold.' + where] = escape_list(
                    [u'+' + key for key in sorted(opened)] + [u'-' + key for key in sorted(shut)])
        return pairs

    def save(self):
        if not self.project:
            return False
        try:
            write_pairs(marks_path(self.folder, self.project), self.to_pairs())
            return True
        except Exception:
            return False

    # ---- folders opened and closed ----
    def folds_of(self, where):
        u"""(opened, closed): the folders opened and closed against the
        default (everything closed) on one tab or pinned copy."""
        opened, shut = self.folds.get(to_text(where), (set(), set()))
        return set(opened), set(shut)

    def set_folds(self, where, opened, shut):
        self.folds[to_text(where)] = (set(opened), set(shut))

    # ---- favourites ----
    def is_fav(self, uid):
        return to_text(uid) in self.favs

    def add_favs(self, leaves):
        added = 0
        for leaf in leaves:
            if leaf.uid and leaf.uid not in self.favs:
                self.favs[leaf.uid] = leaf.tab
                added += 1
        return added

    def remove_favs(self, leaves):
        removed = 0
        for leaf in leaves:
            if self.favs.pop(leaf.uid, None) is not None:
                self.colours.pop(leaf.uid, None)
                removed += 1
        return removed

    def fav_leaves(self, snapshot_tabs):
        u"""{tab: [leaf]} for every favourite still in the model."""
        out = {}
        for tab, leaves in snapshot_tabs.items():
            picked = [leaf for leaf in leaves if leaf.uid in self.favs]
            if picked:
                out[tab] = picked
        return out

    # ---- favourite groups: whole folders ----
    def is_fav_group(self, tab, path):
        return (to_text(tab), tuple(path)) in self.fav_groups

    def add_fav_group(self, tab, path):
        group = (to_text(tab), tuple(to_text(p) for p in path))
        if not group[1] or group in self.fav_groups:
            return False
        self.fav_groups.append(group)
        return True

    def remove_fav_group(self, tab, path):
        group = (to_text(tab), tuple(path))
        if group in self.fav_groups:
            self.fav_groups.remove(group)
            return True
        return False

    def set_colour(self, leaves, slot):
        slot = colour_slot(slot)
        changed = 0
        for leaf in leaves:
            if leaf.uid not in self.favs:
                continue
            if slot:
                self.colours[leaf.uid] = slot
            else:
                self.colours.pop(leaf.uid, None)
            changed += 1
        return changed

    def colour_of(self, uid):
        return self.colours.get(to_text(uid), u'')

    # ---- panel groups ----
    def group_of(self, uid):
        return self.groups.get(to_text(uid), u'')

    def group_names(self):
        return sorted(set(self.groups.values()), key=natural_key)

    def set_group(self, leaves, name):
        name = clean_group(name)
        changed = 0
        for leaf in leaves:
            if not leaf.uid:
                continue
            if name:
                self.groups[leaf.uid] = name
            else:
                self.groups.pop(leaf.uid, None)
            changed += 1
        return changed

    def rename_group(self, old, new):
        old, new = clean_group(old), clean_group(new)
        if not old or not new:
            return 0
        changed = 0
        for uid, name in list(self.groups.items()):
            if name == old:
                self.groups[uid] = new
                changed += 1
        return changed

    def drop_group(self, name):
        name = clean_group(name)
        dropped = [uid for uid, value in self.groups.items() if value == name]
        for uid in dropped:
            del self.groups[uid]
        return len(dropped)
