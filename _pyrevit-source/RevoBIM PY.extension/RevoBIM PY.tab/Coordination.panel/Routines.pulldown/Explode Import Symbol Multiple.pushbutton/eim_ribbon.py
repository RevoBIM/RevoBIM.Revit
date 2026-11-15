# -*- coding: utf-8 -*-
"""Finding and pressing Revit's own Partial / Full Explode ribbon command.

The Revit API has no explode call and the command is not a PostableCommand,
so the tool presses the real button:

1. AdWindows - walk ComponentManager.Ribbon for the item whose id carries
   Control_Essentials_ImportPartialExplode / _ImportExplode and run its
   CommandHandler. The split button's children exist in the ribbon model even
   while the flyout is closed, so Full Explode is reachable this way.
2. UI Automation - only if the ribbon model offers nothing. Runs on a
   background thread: an Automation call made from Revit's own UI thread can
   deadlock, and the click has to be processed after the Idling handler
   returns anyway.
"""
import eim_clr  # noqa: F401  (assembly references first)
import eim_core


# ==========================================================================
# AdWindows
# ==========================================================================

def _component_manager():
    try:
        from Autodesk.Windows import ComponentManager
        return ComponentManager
    except Exception:
        return None


def _iter_coll(coll, parent, depth):
    if coll is None or depth > 6:
        return
    try:
        items = list(coll)
    except Exception:
        return
    for item in items:
        if item is None:
            continue
        yield item, parent
        sub = None
        try:
            sub = getattr(item, 'Items', None)
        except Exception:
            sub = None
        if sub is not None:
            for pair in _iter_coll(sub, item, depth + 1):
                yield pair


def iter_ribbon_items():
    """(tab, item, parent) for every ribbon item, visible tabs first."""
    cm = _component_manager()
    if cm is None:
        return
    try:
        tabs = list(cm.Ribbon.Tabs)
    except Exception:
        return

    def tab_rank(tab):
        try:
            return 0 if tab.IsVisible else 1
        except Exception:
            return 1

    for tab in sorted(tabs, key=tab_rank):
        try:
            panels = list(tab.Panels)
        except Exception:
            continue
        for panel in panels:
            try:
                src = panel.Source
            except Exception:
                continue
            for coll_name in ('Items', 'SlideOutPanelItems'):
                try:
                    coll = getattr(src, coll_name, None)
                except Exception:
                    coll = None
                for item, parent in _iter_coll(coll, None, 0):
                    yield tab, item, parent


def _attr(obj, name, default=None):
    try:
        return getattr(obj, name)
    except Exception:
        return default


def find(mode):
    """(status, item, parent): status is 'enabled', 'disabled' or 'missing'."""
    best = None
    for tab, item, parent in iter_ribbon_items():
        if not eim_core.ribbon_item_matches(mode, _attr(item, 'Id', u''), _attr(item, 'Text', u'')):
            continue
        enabled = bool(_attr(item, 'IsEnabled', True))
        if parent is not None and not bool(_attr(parent, 'IsEnabled', True)):
            enabled = False
        visible = bool(_attr(tab, 'IsVisible', False))
        rank = (0 if enabled else 1, 0 if visible else 1)
        if best is None or rank < best[0]:
            best = (rank, item, parent, enabled)
        if enabled and visible:
            break
    if best is None:
        return u'missing', None, None
    return (u'enabled' if best[3] else u'disabled'), best[1], best[2]


def invoke(item, parent, log):
    """Run the item's command. Returns the route used, or None when there was
    no handler to run (the caller then falls back to UI Automation)."""
    candidates = [('item', item), ('parent', parent)]
    cm = _component_manager()
    if cm is not None:
        candidates.append(('ribbon', _attr(cm.Ribbon, 'CommandHandler')))
    for label, target in candidates:
        if target is None:
            continue
        handler = target if label == 'ribbon' else _attr(target, 'CommandHandler')
        if handler is None:
            continue
        try:
            can = handler.CanExecute(item)
        except Exception:
            can = True
        if not can:
            log(u'ribbon: {0} handler says it cannot execute'.format(label))
            continue
        try:
            handler.Execute(item)
            log(u'ribbon: executed via {0} handler, item id {1}'.format(label, _attr(item, 'Id', u'?')))
            return u'ribbon-' + label
        except Exception as ex:
            log(u'ribbon: {0} handler threw {1}'.format(label, ex))
    return None


# ==========================================================================
# UI Automation fallback
# ==========================================================================

UIA_IDS = {
    u'partial': [
        u'Dialog_Essentials_ImportInstanceExplode:Control_Essentials_ImportPartialExplode_RibbonListButton_FlyoutButtonExecute',
        u'Dialog_Essentials_ImportInstanceExplode:Control_Essentials_ImportPartialExplode',
    ],
    u'full': [
        u'Dialog_Essentials_ImportInstanceExplode:Control_Essentials_ImportExplode_RibbonListButton_FlyoutButtonExecute',
        u'Dialog_Essentials_ImportInstanceExplode:Control_Essentials_ImportExplode',
    ],
}
UIA_NAMES = {u'partial': u'Partial Explode', u'full': u'Full Explode'}


def _uia_work(mode, hwnd, log):
    try:
        from System.Windows.Automation import (AutomationElement, PropertyCondition,
                                               TreeScope, InvokePattern,
                                               ExpandCollapsePattern)
        from System.Threading import Thread
        root = AutomationElement.FromHandle(hwnd)

        def by_id(aid):
            return root.FindFirst(TreeScope.Descendants,
                                  PropertyCondition(AutomationElement.AutomationIdProperty, aid))

        def press(el, how):
            pat = el.GetCurrentPattern(InvokePattern.Pattern)
            pat.Invoke()
            log(u'uia: invoked {0}'.format(how))
            return True

        # The FlyoutButtonExecute id names the split's current item, so an
        # exact match is guaranteed to be the mode asked for.
        for aid in UIA_IDS[mode]:
            el = by_id(aid)
            if el is not None:
                return press(el, aid)

        # Otherwise the other mode is current: open the split and pick by name.
        split = root.FindFirst(TreeScope.Descendants,
                               PropertyCondition(AutomationElement.NameProperty, u'Explode'))
        if split is not None:
            try:
                split.GetCurrentPattern(ExpandCollapsePattern.Pattern).Expand()
                Thread.Sleep(300)
            except Exception as ex:
                log(u'uia: could not expand Explode ({0})'.format(ex))
            el = root.FindFirst(TreeScope.Descendants,
                                PropertyCondition(AutomationElement.NameProperty, UIA_NAMES[mode]))
            if el is not None:
                return press(el, UIA_NAMES[mode])
        log(u'uia: no explode control found')
    except Exception as ex:
        log(u'uia: error {0}'.format(ex))
    return False


def invoke_uia_async(mode, hwnd, log):
    try:
        from System.Threading import Thread, ThreadStart
        t = Thread(ThreadStart(lambda: _uia_work(mode, hwnd, log)))
        t.IsBackground = True
        t.Start()
        return True
    except Exception as ex:
        log(u'uia: could not start thread {0}'.format(ex))
        return False
