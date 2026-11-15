# -*- coding: utf-8 -*-
u"""RevoBIM Addin Manager - Revit's Quick Access Toolbar.

**There is no API for the QAT.** Revit stores it in `UIState.dat`, which is
binary and undocumented; asking for a way to edit it programmatically is a
standing Revit Idea, not a feature. Right-clicking a ribbon button and choosing
*Add to Quick Access Toolbar* is the only supported route.

What *can* be done is the AdWindows one: the ribbon Revit draws is an
`Autodesk.Windows.RibbonControl`, its `QuickAccessToolBar` has an `Items`
collection, and a button put in it behaves like any other. Two things follow,
and both are handled here rather than hoped for:

* **The item has to be a clone.** A WPF element has one parent, so adding the
  live ribbon item itself takes it off the ribbon. A new `RibbonButton` is made
  carrying the original's id, text, icon and `CommandHandler`.
* **It does not persist.** Revit writes `UIState.dat` from its own model of the
  QAT, not from this collection, so the addition is gone at the next start up.
  The tool therefore keeps its own list in settings and **re-applies it every
  time the panel is opened**, which is as close to persistent as this gets, and
  is said plainly in the menu rather than left to be discovered.

Every call verifies by reading the collection back. A void API call is not
evidence.
"""

import rba_clr  # noqa: F401

from rba_core import to_text, log, log_exception


def _qat():
    from Autodesk.Windows import ComponentManager
    ribbon = ComponentManager.Ribbon
    if ribbon is None:
        return None
    return getattr(ribbon, u"QuickAccessToolBar", None)


def available():
    try:
        return _qat() is not None
    except Exception:
        return False


def _ids():
    out = []
    try:
        bar = _qat()
        if bar is None:
            return out
        for item in bar.Items:
            try:
                value = to_text(getattr(item, u"Id", u""))
                if value:
                    out.append(value)
            except Exception:
                continue
    except Exception:
        log_exception(u"qat/ids")
    return out


def holds(command_id):
    command_id = to_text(command_id)
    if not command_id:
        return False
    return command_id in _ids()


def add(ribbon_item, title):
    u"""Put a clone of a ribbon item on the QAT.  Returns (ok, message)."""
    command_id = to_text(getattr(ribbon_item, u"Id", u""))
    if not command_id:
        return False, u"that addin has no command id to put on the toolbar"
    if holds(command_id):
        return True, u""
    try:
        from Autodesk.Windows import RibbonButton, RibbonItemSize
        bar = _qat()
        if bar is None:
            return False, u"Revit did not hand back its Quick Access Toolbar"

        clone = RibbonButton()
        clone.Id = command_id
        clone.Text = to_text(title)
        clone.ShowText = False
        clone.ShowImage = True
        try:
            clone.Size = RibbonItemSize.Standard
        except Exception:
            pass
        for source, target in ((u"Image", u"Image"), (u"LargeImage", u"LargeImage")):
            try:
                value = getattr(ribbon_item, source, None)
                if value is not None:
                    setattr(clone, target, value)
            except Exception:
                pass
        try:
            clone.ToolTip = getattr(ribbon_item, u"ToolTip", None)
        except Exception:
            pass
        # The handler is shared, not copied: the clone is a second button on
        # the same command, which is exactly what the QAT is.
        clone.CommandHandler = getattr(ribbon_item, u"CommandHandler", None)

        bar.Items.Add(clone)
    except Exception:
        log_exception(u"qat/add")
        return False, u"Revit would not take that button on the toolbar"

    if not holds(command_id):
        return False, u"Revit accepted the button and then did not show it"
    log(u"qat: added {0}".format(title))
    return True, u""


def remove(command_id):
    command_id = to_text(command_id)
    try:
        bar = _qat()
        if bar is None:
            return False, u"Revit did not hand back its Quick Access Toolbar"
        doomed = []
        for item in bar.Items:
            try:
                if to_text(getattr(item, u"Id", u"")) == command_id:
                    doomed.append(item)
            except Exception:
                continue
        for item in doomed:
            bar.Items.Remove(item)
    except Exception:
        log_exception(u"qat/remove")
        return False, u"Revit would not take that button off the toolbar"
    if holds(command_id):
        return False, u"Revit removed nothing"
    return True, u""


def reapply(items, wanted_keys):
    u"""Put back everything the settings say belongs on the QAT.

    Called whenever the panel is read, because Revit rebuilds its own toolbar
    from UIState.dat at start up and knows nothing about this list.
    """
    if not wanted_keys:
        return 0
    done = 0
    wanted = {}
    for key in wanted_keys:
        wanted[key] = True
    for item in items:
        if item.key not in wanted or not item.live:
            continue
        ribbon_item = getattr(item, u"_ribbon_item", None)
        if ribbon_item is None:
            continue
        if holds(to_text(getattr(ribbon_item, u"Id", u""))):
            done += 1
            continue
        ok, _ = add(ribbon_item, item.title)
        if ok:
            done += 1
    if done:
        log(u"qat: {0} of {1} pinned buttons in place".format(done, len(wanted_keys)))
    return done
