# -*- coding: utf-8 -*-
u"""Project Browser Pro - dockable pane registration and Revit's events.

Revit only sets a dockable pane up while it is building its user interface.
RegisterDockablePane called any later - from a button, say - is accepted and
the pane is never created, so GetDockablePane then throws. That is why this
is called from the extension's startup.py (the banded fragment shipped with
the tool) and why the button falls back to a floating window when the panes
are not there.

Everything here is guarded and idempotent: it runs inside the shared
startup.py, where an exception stops pyRevit loading every tool in the
extension, and a second paste of the fragment (or a pyRevit reload) must be
a no-op. The guards live in the AppDomain, which survives a reload; a module
flag would not.
"""
import pbp_clr  # noqa: F401
from System import Guid
from System.Windows.Controls import Border, TextBlock
from System.Windows import TextWrapping, Thickness

import pbp_log
import pbp_store
import pbp_runner
import pbp_revit
from pbp_panes import PANES, MAIN_GUID
from pbp_compat import to_text, eid_value, on_path

HOOKS_KEY = u'RevoBIM.PBP.hooks'
VERSION_KEY = u'RevoBIM.PBP.pane_version'
UIAPP_KEY = u'RevoBIM.PBP.uiapp'
# More changed elements than this in one event (a reload, a sync, a big
# paste) and the next read reads everything instead of looking at each.
INSPECT_LIMIT = 2000

PROVIDERS = []
LAST_DOC = [u'']
IDLE_DONE = [False]


def failure_note(error_text):
    u"""What a pane shows when its browser could not be built - never an
    empty black pane. The error's last line and where the full log is."""
    lines = [line for line in to_text(error_text).strip().splitlines() if line.strip()]
    note = TextBlock()
    note.TextWrapping = TextWrapping.Wrap
    note.Margin = Thickness(14)
    note.Text = (u'Project Browser Pro could not start in this panel.\n\n{0}\n\n'
                 u'Restart Revit. If this stays, send the log: '
                 u'%APPDATA%\\RevoBIM\\project_browser_pro_debug.txt').format(
                     lines[-1] if lines else u'(no error text)')
    try:
        # readable whatever Revit paints behind the pane (black, by default)
        import pbp_theme
        note.Foreground = pbp_theme.brush(u'#E8E8E8')
        note.Background = pbp_theme.brush(u'#3B4453')
        note.Padding = Thickness(14)
        note.Margin = Thickness(0)
    except Exception:
        pass
    return note


def can_register(candidate):
    try:
        return callable(getattr(candidate, u'RegisterDockablePane', None))
    except Exception:
        return False


def register(*candidates):
    u"""Register every pane on the first candidate that can take them.

    pyRevit hands startup.py a UIControlledApplication under one name or
    another depending on its build, so the fragment offers every name it can
    find and this asks each one rather than assuming.
    """
    if pbp_store.panes_registered():
        pbp_log.log(u'panes: already registered this session')
        return True
    host = None
    for candidate in candidates:
        if candidate is not None and can_register(candidate):
            host = candidate
            break
    if host is None:
        pbp_log.log(u'panes: no candidate offered RegisterDockablePane')
        return False
    try:
        from Autodesk.Revit.UI import (IDockablePaneProvider, DockablePaneId,
                                       DockablePaneState, DockPosition,
                                       DockablePanes)
    except Exception:
        pbp_log.exc(u'panes: import')
        return False

    class PaneProvider(IDockablePaneProvider):
        u"""Hands Revit an empty Border; the browser is built the first time
        the pane is shown, so start up stays quick."""

        def __init__(self, fixed_tab):
            self.fixed_tab = fixed_tab
            self.host = Border()
            self.browser = None
            self.host.IsVisibleChanged += self._visible

        def _visible(self, sender, args):
            try:
                if self.host.IsVisible and self.browser is None:
                    # pyRevit has reset sys.path since startup.py ran: put
                    # the tool's folder back before importing the browser
                    if on_path():
                        pbp_log.log(u'pane build: tool folder put back on sys.path')
                    import pbp_browser
                    self.browser = pbp_browser.BrowserControl(u'pane', self.fixed_tab)
                    self.host.Child = self.browser.root
                    pbp_log.log(u'pane built: {0}'.format(self.fixed_tab or u'main'))
            except Exception:
                text = pbp_log.exc(u'pane build')
                self.host.Child = failure_note(text)

        def SetupDockablePane(self, data):
            data.FrameworkElement = self.host
            try:
                state = DockablePaneState()
                if self.fixed_tab is None:
                    state.DockPosition = DockPosition.Tabbed
                    state.TabBehind = DockablePanes.BuiltInDockablePanes.ProjectBrowser
                else:
                    # A single-tab pane opens floating, so it never stacks
                    # under the main pane - stacked panes bring back Revit's
                    # own tab strip along the bottom, which the API cannot
                    # move or restyle. Revit remembers wherever it is then
                    # docked.
                    state.DockPosition = DockPosition.Floating
                data.InitialState = state
            except Exception:
                try:
                    data.InitialState = DockablePaneState()
                    data.InitialState.DockPosition = DockPosition.Floating
                except Exception:
                    pass
            try:
                data.VisibleByDefault = False
            except Exception:
                pass

    registered = 0
    for pane_id, title, fixed_tab, guid in PANES:
        try:
            provider = PaneProvider(fixed_tab)
            PROVIDERS.append(provider)
            host.RegisterDockablePane(DockablePaneId(Guid(guid)), title, provider)
            registered += 1
        except Exception:
            pbp_log.exc(u'panes: register ' + pane_id)
    if registered:
        pbp_store.domain_set(pbp_store.PANES_KEY, u'registered')
        try:
            from pbp_version import __version__ as running
            pbp_store.domain_set(VERSION_KEY, running)
        except Exception:
            pass
    pbp_log.log(u'panes: {0} of {1} registered'.format(registered, len(PANES)))
    hook_events(host)
    return registered > 0


# ============================================================
# events
# ============================================================

def _element(doc, eid):
    try:
        return doc.GetElement(eid)
    except Exception:
        return None


def note_changes(doc, added, modified, deleted, known):
    u"""(sections to read again whole, ids to look at again alone).

    Only an element's class is looked at, so this is cheap enough to run on
    every change in the model: drawing pipework, tagging or dimensioning
    costs a look at each element's class and nothing more.

      * deleted: the section the last read saw it in (a view's tab,
        'placed' for a viewport, 'sets' for a sheet set) - unknown ids
        were never shown
      * added: its section (a new sheet reads the sheets again)
      * modified view, sheet, schedule or family type the browser shows,
        or a view template: looked at alone (a template only matters if
        its name changed - it names views' icons)
      * a family, a sheet set or a view type: its section; Revit's browser
        organisation: everything
      * a viewport moved on its sheet: nothing
    """
    sections = set()
    ids = []
    if not isinstance(known, dict):
        known = dict((value, pbp_revit.ALL) for value in (known or ()))
    for eid in deleted:
        section = known.get(eid_value(eid))
        if section:
            sections.add(section)
    looked = 0
    for eid in added:
        looked += 1
        if looked > INSPECT_LIMIT:
            sections.add(pbp_revit.ALL)
            return sections, ids
        kind = pbp_revit.change_kind(_element(doc, eid))
        if kind in pbp_revit.SECTIONS:
            sections.add(kind)
        elif kind == pbp_revit.FAMILY:
            sections.add(u'families')
    for eid in modified:
        looked += 1
        if looked > INSPECT_LIMIT:
            sections.add(pbp_revit.ALL)
            return sections, ids
        kind = pbp_revit.change_kind(_element(doc, eid))
        if kind is None or kind == pbp_revit.PLACED:
            continue
        value = eid_value(eid)
        if kind in pbp_revit.READ_TABS:
            if value in known:
                ids.append(value)
        elif kind == pbp_revit.TEMPLATE:
            ids.append(value)
        elif kind == pbp_revit.FAMILY:
            sections.add(u'families')
        elif kind == pbp_revit.VIEW_TYPE:
            sections.add(u'views')
        elif kind in (pbp_revit.SETS, pbp_revit.ALL):
            sections.add(kind)
    return sections, ids


def on_document_changed(sender, args):
    u"""Note what changed for the next read - never read here.

    The counters and journal this writes are all the browsers look at; the
    read itself waits for the browsers' clock, so a burst of changes costs
    one read, and a change the browser does not show costs none."""
    try:
        doc = args.GetDocument()
        sections, ids = note_changes(doc, args.GetAddedElementIds(),
                                     args.GetModifiedElementIds(),
                                     args.GetDeletedElementIds(),
                                     pbp_store.known_ids())
        if sections:
            pbp_store.bump_dirty(*sorted(sections))
        if ids:
            pbp_store.journal_add(ids)
    except Exception:
        pbp_log.exc(u'DocumentChanged')


def on_view_activated(sender, args):
    try:
        doc = args.Document
        key = to_text(doc.PathName) or to_text(doc.Title)
        if key != LAST_DOC[0]:
            LAST_DOC[0] = key
            pbp_store.bump_dirty()
        pbp_store.bump_views()
    except Exception:
        pbp_log.exc(u'ViewActivated')


def on_document_switched(sender, args):
    try:
        pbp_store.bump_dirty()
    except Exception:
        pass


SELECTION_EVERY = 0.35   # seconds between looks at Revit's selection
LAST_SELECTION = [0.0, u'']


def watch_selection(uiapp, now=None):
    u"""Publish Revit's selection for the browsers to find - a view picked
    in Revit's own browser (Find in Project Browser included), a viewport
    or schedule on a sheet, a family type. Read at most every 0.35 s, and
    only the ids compared until they change."""
    import time
    now = time.time() if now is None else now
    if now - LAST_SELECTION[0] < SELECTION_EVERY:
        return False
    LAST_SELECTION[0] = now
    try:
        uidoc = uiapp.ActiveUIDocument
        if uidoc is None:
            return False
        ids = list(uidoc.Selection.GetElementIds())
        signature = u','.join(to_text(eid_value(eid)) for eid in ids[:200])
        if signature == LAST_SELECTION[1]:
            return False
        LAST_SELECTION[1] = signature
        return pbp_store.publish_selection(pbp_revit.selection_targets(uidoc.Document, ids))
    except Exception:
        pbp_log.exc(u'watch selection')
        return False


def on_idling(sender, args):
    u"""First: park the UIApplication and create the panes' ExternalEvent
    (Idling runs in API context, which ExternalEvent.Create needs). Then on
    every pass, cheaply, watch Revit's selection.
    """
    if IDLE_DONE[0]:
        watch_selection(sender)
        return
    try:
        # the first moment after start up: sys.path has been reset by now
        on_path()
        pbp_store.domain_set(UIAPP_KEY, sender)
        if pbp_runner.get().ensure_event():
            IDLE_DONE[0] = True
    except Exception:
        IDLE_DONE[0] = True
        pbp_log.exc(u'Idling')


def hook_events(app_like):
    u"""Subscribe once per Revit session, from startup.py or from the command.

    Hooked once and never unhooked: unsubscribing an IronPython bound method
    from a .NET event is not reliable, because each access makes a fresh
    delegate.
    """
    if pbp_store.domain_get(HOOKS_KEY):
        return False
    controlled = getattr(app_like, u'ControlledApplication', None)
    if controlled is None:
        controlled = getattr(app_like, u'Application', None)
    hooked = []
    try:
        controlled.DocumentChanged += on_document_changed
        hooked.append(u'DocumentChanged')
    except Exception:
        pbp_log.exc(u'hook DocumentChanged')
    for name in (u'DocumentOpened', u'DocumentClosed'):
        try:
            event = getattr(controlled, name)
            event += on_document_switched
            hooked.append(name)
        except Exception:
            pbp_log.exc(u'hook ' + name)
    try:
        app_like.ViewActivated += on_view_activated
        hooked.append(u'ViewActivated')
    except Exception:
        pbp_log.exc(u'hook ViewActivated')
    try:
        app_like.Idling += on_idling
        hooked.append(u'Idling')
    except Exception:
        pbp_log.exc(u'hook Idling')
    pbp_store.domain_set(HOOKS_KEY, u','.join(hooked))
    pbp_log.log(u'events hooked: ' + u', '.join(hooked))
    return True


def stale_note(installed):
    u"""A one-line note when the panes run an older copy than is installed.

    The panes are built from the code startup.py loaded when Revit started.
    Unzipping a new version, or a pyRevit reload, does not replace it -
    only a Revit restart does - so after an update the panes keep showing
    the old version until then."""
    running = to_text(pbp_store.domain_get(VERSION_KEY, u''))
    if not running or running == to_text(installed):
        return u''
    return (u'Project Browser Pro v{0} is installed, but the docked panels are still running '
            u'v{1} from when Revit started. Close Revit and open it again to load v{0}.').format(
                installed, running)


def show_main(uiapp):
    u"""For the button: show the main pane. Returns False when it is not there."""
    return show(uiapp, MAIN_GUID)


def show(uiapp, guid_text):
    try:
        from Autodesk.Revit.UI import DockablePane, DockablePaneId
        pane_id = DockablePaneId(Guid(guid_text))
        try:
            if not DockablePane.PaneIsRegistered(pane_id):
                return False
        except Exception:
            pass
        uiapp.GetDockablePane(pane_id).Show()
        return True
    except Exception:
        pbp_log.exc(u'show pane')
        return False
