# -*- coding: utf-8 -*-
u"""RevoBIM Addins - matching scanned folders to live ribbon items, and firing
them.

There is no API that runs a pyRevit script by its folder path.  What there is
is the live ribbon: every loaded button is an Autodesk.Windows.RibbonItem with
an Id that RevitCommandId.LookupCommandId understands.  So the folder walk
gives the LIST and the ribbon gives the WAY TO RUN IT, and an item present in
one but not the other is exactly the interesting case - a tool added to the
folder since the last pyRevit reload.  That row is shown greyed and says so,
rather than being hidden or failing silently when clicked.

Reading the live command Id out of the AdWindows ComponentManager is the same
route the extension already uses to write Revit's KeyboardShortcuts.xml.
"""

import rba_clr  # noqa: F401

from rba_core import normalise, to_text, log, log_exception

# The UIApplication, captured once.  A dockable pane outlives the command that
# opened it, so it cannot rely on __revit__ being in scope: script.py parks it
# here when the button is pressed, and the startup fragment parks it from the
# first Idling event so the pane also works when it is re-opened from Revit's
# own View > User Interface menu.
UIAPP = [None]


def set_uiapp(uiapp):
    if uiapp is not None:
        UIAPP[0] = uiapp


def get_uiapp():
    return UIAPP[0]


def _ribbon():
    from Autodesk.Windows import ComponentManager
    return ComponentManager.Ribbon


def _item_text(item):
    for attribute in (u"AutomationName", u"Text", u"Name", u"Id"):
        try:
            value = getattr(item, attribute, None)
            if value:
                return to_text(value)
        except Exception:
            continue
    return u""


def _walk_items(items, out):
    for item in items:
        try:
            out.append(item)
        except Exception:
            continue
        for attribute in (u"Items",):
            try:
                children = getattr(item, attribute, None)
            except Exception:
                children = None
            if children:
                try:
                    _walk_items(children, out)
                except Exception:
                    pass


def build_index():
    u"""(tab, panel, title) -> RibbonItem, plus looser keys as fallbacks.

    Three keys per item because a pulldown child reports the pulldown's panel
    but not always its own caption the same way the folder does.
    """
    exact = {}
    by_tab = {}
    by_title = {}
    try:
        ribbon = _ribbon()
    except Exception:
        log_exception(u"build_index/ribbon")
        return exact, by_tab, by_title
    if ribbon is None:
        return exact, by_tab, by_title
    try:
        tabs = list(ribbon.Tabs)
    except Exception:
        tabs = []
    for tab in tabs:
        tab_name = normalise(getattr(tab, u"Title", u"") or getattr(tab, u"Name", u""))
        try:
            panels = list(tab.Panels)
        except Exception:
            panels = []
        for panel in panels:
            panel_name = u""
            try:
                panel_name = normalise(panel.Source.Title)
            except Exception:
                panel_name = u""
            items = []
            try:
                _walk_items(list(panel.Source.Items), items)
            except Exception:
                pass
            for item in items:
                title = normalise(_item_text(item))
                if not title:
                    continue
                exact.setdefault(u"{0}|{1}|{2}".format(tab_name, panel_name, title), item)
                by_tab.setdefault(u"{0}|{1}".format(tab_name, title), item)
                by_title.setdefault(title, item)
    return exact, by_tab, by_title


def attach_live(items):
    u"""Mark every scanned item that has a live ribbon command behind it."""
    exact, by_tab, by_title = build_index()
    found = 0
    for item in items:
        ribbon_item = None
        title = normalise(item.title)
        keys = [
            u"{0}|{1}|{2}".format(normalise(item.tab), normalise(item.panel), title),
        ]
        for key in keys:
            ribbon_item = exact.get(key)
            if ribbon_item is not None:
                break
        if ribbon_item is None:
            ribbon_item = by_tab.get(u"{0}|{1}".format(normalise(item.tab), title))
        if ribbon_item is None:
            ribbon_item = by_title.get(title)
        if ribbon_item is None:
            item.live = False
            item.command_id = u""
            continue
        item.live = True
        try:
            item.command_id = to_text(getattr(ribbon_item, u"Id", u""))
        except Exception:
            item.command_id = u""
        item._ribbon_item = ribbon_item
        found += 1
    log(u"attach_live: {0} of {1} scanned items are on the live ribbon".format(
        found, len(items)))
    return found


def launch(item):
    u"""Run a scanned item.  Returns (ok, message).

    PostCommand first: it queues the command so Revit runs it in its own valid
    API context, which is what a real ribbon click does.  Executing the ribbon
    item's own CommandHandler runs it on this thread instead and is kept as a
    fallback for items LookupCommandId will not resolve.
    """
    ribbon_item = getattr(item, u"_ribbon_item", None)
    if ribbon_item is None:
        return False, u"{0} is not on the ribbon - reload pyRevit to pick it up".format(item.title)

    command_id = to_text(getattr(item, u"command_id", u""))
    uiapp = get_uiapp()
    if command_id and uiapp is not None:
        try:
            from Autodesk.Revit.UI import RevitCommandId
            revit_id = RevitCommandId.LookupCommandId(command_id)
            if revit_id is not None:
                uiapp.PostCommand(revit_id)
                log(u"launch: posted {0}".format(command_id))
                return True, u""
        except Exception:
            log_exception(u"launch/PostCommand")

    try:
        handler = getattr(ribbon_item, u"CommandHandler", None)
        if handler is not None:
            parameter = getattr(ribbon_item, u"CommandParameter", None)
            if parameter is None:
                parameter = ribbon_item
            if handler.CanExecute(parameter):
                handler.Execute(parameter)
                log(u"launch: executed handler for {0}".format(item.title))
                return True, u""
    except Exception:
        log_exception(u"launch/CommandHandler")

    return False, u"Revit would not run {0}".format(item.title)
