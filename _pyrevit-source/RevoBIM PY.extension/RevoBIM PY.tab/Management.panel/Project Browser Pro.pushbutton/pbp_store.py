# -*- coding: utf-8 -*-
u"""Project Browser Pro - the latest read, shared by every browser in an engine.

Every pane in the startup engine (the main pane, the tab panes and the
pinned copies) listens to one Store, so a change in the model costs one
read, not one per pane. Reads are coalesced: asking while a read is
running asks for one more read after it, not one per caller.

A read is only as big as the change (1.6.0). Revit's DocumentChanged
event notes, cheaply, what changed:
  * a view, sheet, schedule or family type the browser shows, modified:
    its id goes in the journal, and the next read looks at it alone - and
    tells the panes nothing at all when its row would draw the same
  * something added or deleted: its section's counter moves, and that
    section is read again whole (a new sheet reads the sheets, not the
    2,000 family types)
  * another document, a reload, more than the event can look at: 'all'

What has to cross engines - the dirty counters bumped by Revit's events,
whether the panes registered, the ids the last read saw - is parked in the
AppDomain, which every pyRevit engine shares. Module variables do not cross:
each engine has its own copy of this module.
"""
import pbp_clr  # noqa: F401
from System import AppDomain

import pbp_log
import pbp_settings
import pbp_revit
import pbp_marks
from pbp_compat import to_text, eid_value

DIRTY_KEY = u'RevoBIM.PBP.dirty'
VIEWS_KEY = u'RevoBIM.PBP.views'
PANES_KEY = u'RevoBIM.PBP.panes'
KNOWN_KEY = u'RevoBIM.PBP.known'
DOC_KEY = u'RevoBIM.PBP.doc'
PINS_KEY = u'RevoBIM.PBP.pins'
# Revit's selection as browser keys ('view:e:12|type:e:34'), and a counter
# bumped when it changes - written by the Idling hook, read by browsers.
SELECTION_KEY = u'RevoBIM.PBP.selection'
SELECTION_COUNT_KEY = u'RevoBIM.PBP.selection_count'
# 'RevoBIM.PBP.place.<pane guid>' = 'left,top,width,height': where a pane
# being opened from a browser should go - taken once by that pane.
PLACE_KEY = u'RevoBIM.PBP.place.'
# What a listener is told changed: a full read (False), only which views
# are open (True - changed_ids says which), only the user's marks -
# favourites, colours, panel groups, the sheet set (MARKS) - or some tabs
# after a change (PATCH - changed_tabs says which).
MARKS = u'marks'
PATCH = u'patch'
# 'RevoBIM.PBP.dirty.<section>': a counter per section (pbp_revit.SECTIONS)
SECTION_KEY = u'RevoBIM.PBP.dirty.'
# Modified ids to look at alone: 'seq:id seq:id ...', newest last, each id
# once. Kept to JOURNAL_LIMIT ids; a reader that has fallen further behind
# than that (the floor) reads everything instead.
JOURNAL_KEY = u'RevoBIM.PBP.journal'
JOURNAL_SEQ_KEY = u'RevoBIM.PBP.journal_seq'
JOURNAL_FLOOR_KEY = u'RevoBIM.PBP.journal_floor'
JOURNAL_LIMIT = 400


def domain_get(key, default=None):
    try:
        value = AppDomain.CurrentDomain.GetData(key)
    except Exception:
        value = None
    return default if value is None else value


def domain_set(key, value):
    try:
        AppDomain.CurrentDomain.SetData(key, value)
        return True
    except Exception:
        return False


def _bump(key):
    try:
        value = int(domain_get(key, 0)) + 1
    except Exception:
        value = 1
    domain_set(key, value)
    return value


def bump_dirty(*sections):
    u"""Something the browser shows changed. The sections named are read
    again whole; with none named, everything is (another document, a
    reload)."""
    for name in (sections or (pbp_revit.ALL,)):
        _bump(SECTION_KEY + name)
    return _bump(DIRTY_KEY)


def section_counts():
    out = {}
    for name in pbp_revit.SECTIONS:
        try:
            out[name] = int(domain_get(SECTION_KEY + name, 0))
        except Exception:
            out[name] = 0
    return out


def _int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def journal_seq():
    return _int(domain_get(JOURNAL_SEQ_KEY, 0))


def journal_floor():
    return _int(domain_get(JOURNAL_FLOOR_KEY, 0))


def _journal_entries():
    u"""[(seq, id)] oldest first."""
    out = []
    for entry in to_text(domain_get(JOURNAL_KEY, u'')).split():
        seq, sep, value = entry.partition(u':')
        if sep:
            try:
                out.append((int(seq), int(value)))
            except ValueError:
                continue
    return out


def journal_add(values):
    u"""Modified elements to look at alone at the next read."""
    values = [_int(value) for value in values]
    values = [value for value in values if value]
    if not values:
        return journal_seq()
    seq = _bump(JOURNAL_SEQ_KEY)
    fresh = set(values)
    entries = [(s, v) for s, v in _journal_entries() if v not in fresh]
    entries.extend((seq, value) for value in sorted(fresh))
    if len(entries) > JOURNAL_LIMIT:
        dropped = entries[:len(entries) - JOURNAL_LIMIT]
        domain_set(JOURNAL_FLOOR_KEY, max([journal_floor()] + [s for s, v in dropped]))
        entries = entries[-JOURNAL_LIMIT:]
    domain_set(JOURNAL_KEY, u' '.join(u'{0}:{1}'.format(s, v) for s, v in entries))
    _bump(DIRTY_KEY)
    return seq


def journal_since(seen):
    u"""(ids modified since journal seq `seen`, whether all are still kept)."""
    ids = set(value for seq, value in _journal_entries() if seq > seen)
    return ids, seen >= journal_floor()


def bump_views():
    return _bump(VIEWS_KEY)


def bump_pins():
    u"""A pin was written: every pinned pane re-reads its own."""
    return _bump(PINS_KEY)


def pins_count():
    try:
        return int(domain_get(PINS_KEY, 0))
    except Exception:
        return 0


def publish_selection(targets):
    text = u'|'.join(u'{0}:{1}'.format(kind, key) for kind, key in targets)
    if text == to_text(domain_get(SELECTION_KEY, u'')):
        return False
    domain_set(SELECTION_KEY, text)
    _bump(SELECTION_COUNT_KEY)
    return True


def selection_count():
    try:
        return int(domain_get(SELECTION_COUNT_KEY, 0))
    except Exception:
        return 0


def read_selection():
    u"""[(kind, key)] as last published."""
    out = []
    for part in to_text(domain_get(SELECTION_KEY, u'')).split(u'|'):
        if u':' in part:
            kind, key = part.split(u':', 1)
            out.append((kind, key))
    return out


SETTINGS_KEY = u'RevoBIM.PBP.settings'


def bump_settings():
    u"""The settings changed in one browser: the others reload them."""
    return _bump(SETTINGS_KEY)


def settings_count():
    try:
        return int(domain_get(SETTINGS_KEY, 0))
    except Exception:
        return 0


def dirty_count():
    try:
        return int(domain_get(DIRTY_KEY, 0))
    except Exception:
        return 0


def views_count():
    try:
        return int(domain_get(VIEWS_KEY, 0))
    except Exception:
        return 0


def panes_registered():
    return to_text(domain_get(PANES_KEY, u'')) == u'registered'


def known_ids():
    u"""{element id: section} as the last read left it (an older copy of
    the tool still running in another engine may have left a set)."""
    value = domain_get(KNOWN_KEY)
    return value if value is not None else {}


class Store(object):

    def __init__(self):
        self.snapshot = None
        self.listeners = []
        self.reading = False
        self.again = False
        self.read_dirty = -1
        self.runner = None
        self.folder = pbp_log.appdata_folder()
        self.reads = 0
        self.change_reads = 0
        self._marks = None
        # the section counters and journal seq the snapshot is up to date with
        self.seen = {}
        self.journal_seen = 0
        # what the last PATCH and views publish changed
        self.changed_tabs = set()
        self.changed_ids = set()
        self.views_pending = False

    def subscribe(self, listener):
        if listener not in self.listeners:
            self.listeners.append(listener)

    def unsubscribe(self, listener):
        if listener in self.listeners:
            self.listeners.remove(listener)

    def _publish(self, views_only=False):
        for listener in list(self.listeners):
            try:
                listener(self.snapshot, views_only)
            except Exception:
                pbp_log.exc(u'store listener')

    # ---- full read ----
    def load_orgs(self, title):
        return pbp_settings.load_orgs(self.folder, title)

    def request_read(self, runner, reason, dirty=None):
        self.runner = runner
        if self.reading:
            self.again = True
            return True
        target = dirty_count() if dirty is None else dirty
        counts, seq = section_counts(), journal_seq()

        def work(app):
            return pbp_revit.read_snapshot(app, self.load_orgs)
        if runner.queue(u'read (' + to_text(reason) + u')', work, self._read_done):
            self.reading = True
            self.read_dirty = target
            self.seen, self.journal_seen = counts, seq
            return True
        return False

    def plan(self):
        u"""What bringing the snapshot up to date takes:
        ('none' | 'full' | 'changes', sections to read whole, ids alone)."""
        counts = section_counts()
        moved = set(name for name, count in counts.items() if count != self.seen.get(name, 0))
        ids, complete = journal_since(self.journal_seen)
        if self.snapshot is None or pbp_revit.ALL in moved or not complete:
            return u'full', set(), set()
        if not moved and not ids:
            return u'none', set(), set()
        return u'changes', moved, ids

    def refresh(self, runner, reason):
        u"""Read only if the model changed since the last read - and only
        what changed."""
        current = dirty_count()
        if self.snapshot is not None and self.read_dirty == current:
            return True
        if self.reading:
            return True
        kind, sections, ids = self.plan()
        if kind == u'none':
            self.read_dirty = current
            return True
        if kind == u'full':
            return self.request_read(runner, reason, current)
        return self.request_changes(runner, reason, sections, ids, current)

    # the name 1.5 called it by
    ensure_fresh = refresh

    def request_sections(self, runner, sections, reason):
        u"""Read these tabs again whole, now - after an organisation change."""
        self.runner = runner
        if self.snapshot is None or self.reading:
            return self.request_read(runner, reason)
        # whatever else is waiting comes along, so nothing is skipped
        current = dirty_count()
        kind, waiting, ids = self.plan()
        if kind == u'full':
            return self.request_read(runner, reason, current)
        return self.request_changes(runner, reason, set(sections) | waiting, ids, current)

    def request_changes(self, runner, reason, sections, ids, target):
        self.runner = runner
        previous = self.snapshot
        counts, seq = section_counts(), journal_seq()

        def work(app):
            return pbp_revit.read_changes(app, previous, sections, ids, self.load_orgs)
        if runner.queue(u'read changes (' + to_text(reason) + u')', work, self._changes_done):
            self.reading = True
            self.read_dirty = target
            self.seen, self.journal_seen = counts, seq
            return True
        return False

    def _read_done(self, result, error):
        self.reading = False
        if result is not None:
            self._take(result)
        elif error:
            pbp_log.log(u'store: read failed')
        self._again()

    def _take(self, snapshot):
        self.reads += 1
        self.snapshot = snapshot
        self.changed_tabs = set(pbp_revit.READ_TABS)
        domain_set(KNOWN_KEY, snapshot.known_ids)
        domain_set(DOC_KEY, snapshot.key)
        self._publish()

    def _again(self):
        if self.again and self.runner is not None:
            self.again = False
            self.request_read(self.runner, u'again')

    def _changes_done(self, result, error):
        self.reading = False
        if result is None:
            # it failed part way: reading everything puts it right
            pbp_log.log(u'store: reading the changes failed - reading everything')
            if self.runner is not None:
                self.again = False
                self.request_read(self.runner, u'after a failed change read')
            return
        snapshot, tabs = result
        if tabs is None:
            # it read everything after all (another document)
            self._take(snapshot)
        else:
            self.change_reads += 1
            domain_set(KNOWN_KEY, snapshot.known_ids)
            if tabs:
                self.snapshot = snapshot
                self.changed_tabs = set(tabs)
                self._publish(PATCH)
            # nothing any pane draws changed: the panes keep what they have
            # and nobody redraws
        self._again()

    # ---- light read: open views ----
    def request_views(self, runner):
        u"""Which views are open - one look for every pane asking."""
        if self.snapshot is None or self.reading:
            return False
        if self.views_pending:
            return True

        def work(app):
            return pbp_revit.read_open_views(app)
        self.views_pending = runner.queue(u'open views', work, self._views_done)
        return self.views_pending

    def _views_done(self, result, error):
        self.views_pending = False
        if result is None or self.snapshot is None:
            return
        if result[u'key'] != self.snapshot.key:
            if self.runner is not None:
                self.request_read(self.runner, u'document switched')
            return
        snap = self.snapshot
        changed = set(snap.open_ids) ^ set(result[u'open'])
        if snap.active_id != result[u'active']:
            changed |= set([snap.active_id, result[u'active']])
        snap.open_ids = result[u'open']
        snap.active_id = result[u'active']
        if not changed:
            return
        for leaves in snap.tabs.values():
            for leaf in leaves:
                value = eid_value(leaf.eid)
                if value in changed:
                    leaf.is_open = value in snap.open_ids
                    leaf.is_active = value == snap.active_id
        self.changed_ids = changed
        self._publish(views_only=True)

    # ---- marks: favourites, colours, panel groups, sheet set ----
    def marks(self):
        u"""The marks for the project the last read was of - loaded once per
        project and shared by every pane, so a star added in one pane is in
        all of them."""
        title = self.snapshot.title if self.snapshot is not None else u''
        if self._marks is None or self._marks.project != title:
            self._marks = pbp_marks.Marks.load(self.folder, title)
        return self._marks

    def save_marks(self, why):
        marks = self.marks()
        ok = marks.save()
        pbp_log.log(u'marks saved ({0}): {1} - {2} favourite(s), {3} grouped panel(s), '
                    u'sheet set {4!r}'.format(ok, why, len(marks.favs), len(marks.groups),
                                              marks.sheet_set))
        self._publish(MARKS)
        return ok

    def publish_marks_changed(self):
        u"""Something every pane draws changed without a read (a heading's
        colour): each rebuilds its trees."""
        self._publish(MARKS)

    # ---- organisations ----
    def save_org(self, tab, org):
        if self.snapshot is None:
            return False
        orgs = dict(self.snapshot.orgs)
        orgs[tab] = pbp_settings.normalise_org(org, tab)
        self.snapshot.orgs = orgs
        ok = pbp_settings.save_orgs(self.folder, self.snapshot.title, orgs)
        pbp_log.log(u'organisation for {0} saved ({1}): {2}'.format(tab, ok, orgs[tab]))
        return ok


STORE = Store()
