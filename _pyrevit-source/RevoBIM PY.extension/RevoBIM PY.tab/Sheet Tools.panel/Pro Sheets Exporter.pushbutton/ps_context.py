# -*- coding: utf-8 -*-
""""Print in ProSheets" on Revit's right click menu, from Revit 2025 on.

Right clicking in the Project Browser - or in the canvas - gets a **Print in
ProSheets** entry at the bottom that opens Pro Sheets Exporter. Whatever was
selected arrives isolated and ticked, because that is what the tool already
does with a pre-selection; this only saves the trip to the ribbon.

Four things about this are worth knowing before changing any of it.

**It is a 2025 API.** ``IContextMenuCreator``, ``ContextMenu`` and
``CommandMenuItem`` arrived in the Revit 2025 API. On 2024 and earlier they
do not exist, so **nothing in this module may import them at module level**
- an import that throws at load would take the whole shared ``startup.py``
with it, and a startup.py that throws stops pyRevit loading every tool in
the extension. Every one of those names is imported inside a function,
after the version gate has passed. The bench rule ``context_menu_gate``
fails if one of them ever moves to the top of the file.

**Which object you register on depends on the release, and getting this
wrong is how the feature stayed invisible until 1.19.0.**
``RegisterContextMenu`` is on ``UIApplication`` from 2025, but it was only
added to ``UIControlledApplication`` in **2026**. Versions up to 1.18.1
were handed a ``UIControlledApplication`` and tested ``hasattr`` on it, so
on Revit 2025 - the release this was built for - the gate decided the API
was missing and went dormant. So the host is now chosen by capability
across every candidate the caller can offer, never assumed: see
``pick_host``. pyRevit's ``startup.py`` gets both ``__revit__`` and
``__uicontrolledapplication__``, and which of the two carries the method
varies by pyRevit build as well as by Revit release, which is exactly why
both are passed in and neither is trusted.

**The command is resolved at right click time, not at registration.**
``CommandMenuItem`` wants an ``IExternalCommand`` class name and the
assembly holding it. pyRevit generates that assembly itself and writes a
fresh copy, under a fresh name, every time the extension reloads - so a
path captured once at startup is stale the moment somebody reloads
pyRevit, and the menu item stops doing anything. ``BuildContextMenu`` is
called afresh on every right click, so the lookup happens there instead,
against whatever is loaded right now. That is also why the registration
surviving a reload is harmless: the creator object left behind by the old
module still resolves the new assembly.

**The item is always added, never conditionally.** Autodesk have an open
bug, REVIT-251042, where a creator that adds nothing still leaves an empty
flyout hanging in the Project Browser - it does not happen in the canvas.
So rather than hiding the entry when the selection is not useful, the entry
is always there and the tool says what it found when it opens. An entry
that is occasionally pointless beats a blank sub-menu that looks broken.
"""

import ps_refs  # noqa: F401  - must be first, see its docstring

import os
import re
import traceback

import ps_config


# The Revit release the context menu API arrived in. Below this the whole
# feature is dormant and register() says so rather than throwing.
MIN_VERSION = 2025

# What the entry says. One constant, because it is the only string a user
# ever sees from this module.
ITEM_TEXT = u'Print in ProSheets'

# Passed to RegisterContextMenu as the add-in id. Stable, and namespaced so
# a second RevoBIM tool registering its own menu cannot collide with it.
ADDIN_ID = 'RevoBIM.ProSheetsExporter'

# Survives a pyRevit reload, which a module level flag does not: a reload
# re-imports this module with the flag back at False while the creator
# registered by the previous import is still live. Registering twice gives
# two identical entries on the menu.
GUARD_KEY = 'RevoBIM.ProSheetsExporter.ContextMenu'

# Matched against the generated command type's full name. pyRevit builds
# that name out of the bundle path, and the scheme has changed between
# pyRevit versions, so it is matched on letters and digits alone rather
# than on any particular separator.
TOOL_TOKEN = 'prosheetsexporter'

_registered = False


# ==========================================================================
# diagnostics
#
# This runs at Revit startup inside a bare except, in a file shared with
# every other tool, so it cannot report a problem by throwing and must not
# report one with a dialog either. It writes a line to a log instead.
# ==========================================================================

def log_path():
    try:
        return os.path.join(os.path.dirname(ps_config.error_path()),
                            'pro_sheets_exporter_context_menu.txt')
    except Exception:
        return u''


def log(text):
    """Append one line to the context menu log. Never raises."""
    path = log_path()
    if not path:
        return
    try:
        handle = open(path, 'ab')
        try:
            handle.write((u'{0}\n'.format(text)).encode('utf-8'))
        finally:
            handle.close()
    except Exception:
        pass


def log_reset(text):
    try:
        path = log_path()
        if path and os.path.isfile(path):
            os.remove(path)
    except Exception:
        pass
    log(text)


# ==========================================================================
# the version gate
# ==========================================================================

def host_version(uiapp):
    """The running Revit's year as an int, or 0 where it cannot be read."""
    for route in ('ControlledApplication', 'Application'):
        try:
            app = getattr(uiapp, route, None)
            if app is None:
                continue
            digits = re.findall(r'\d{4}', u'{0}'.format(app.VersionNumber))
            if digits:
                return int(digits[0])
        except Exception:
            continue
    return 0


def can_register(candidate):
    """Whether this object is one ``RegisterContextMenu`` can be called on.

    Asked of each candidate rather than assumed from its type, because the
    answer moved between releases: ``UIApplication`` has had the method
    since 2025, ``UIControlledApplication`` only since 2026.
    """
    if candidate is None:
        return False
    try:
        return callable(getattr(candidate, 'RegisterContextMenu', None))
    except Exception:
        return False


def pick_host(candidates):
    """The first candidate that can register, or None. (host, index).

    Order is the caller's: the fragment passes what pyRevit gives it, best
    first. Index is returned only so the log can say which one answered,
    which is the difference between a puzzling dormant feature and a log
    line naming the object that worked.
    """
    index = 0
    for candidate in candidates or ():
        if can_register(candidate):
            return candidate, index
        index += 1
    return None, -1


def api_present():
    """(present, reason) for the three types the menu is built out of."""
    try:
        from Autodesk.Revit.UI import IContextMenuCreator  # noqa: F401
        from Autodesk.Revit.UI import ContextMenu          # noqa: F401
        from Autodesk.Revit.UI import CommandMenuItem      # noqa: F401
    except Exception as err:
        return False, (u'the context menu API is not on this '
                       u'Revit: {0}'.format(err))
    return True, u'the context menu API is present'


def available(*candidates):
    """(usable, host, reason). Reason is for the log, not for a user.

    Takes any number of candidates so the caller can hand over everything
    it has - ``__revit__``, ``__uicontrolledapplication__`` - without
    knowing which one this Revit put the method on.
    """
    live = [item for item in candidates if item is not None]
    if not live:
        return False, None, u'nothing was passed in to register on'

    version = 0
    for candidate in live:
        version = host_version(candidate) or version
    if version and version < MIN_VERSION:
        return False, None, (u'Revit {0} has no context menu API; it '
                             u'arrived in {1}'.format(version, MIN_VERSION))

    present, why = api_present()
    if not present:
        return False, None, why

    host, index = pick_host(live)
    if host is None:
        # Reached on a Revit new enough to have the types but where every
        # candidate is the wrong kind of object - a 2025 handed only a
        # UIControlledApplication, which is the 1.18.1 bug. The deferred
        # route in register() picks it up from here.
        return False, None, (u'none of the {0} candidate(s) passed in has '
                             u'RegisterContextMenu'.format(len(live)))
    return True, host, u'Revit {0}, candidate {1}'.format(
        version or u'?', index + 1)


# ==========================================================================
# finding the command to point the entry at
# ==========================================================================

def _normalise(text):
    return re.sub(r'[^a-z0-9]', '', u'{0}'.format(text or u'').lower())


def resolve_command():
    """(class name, assembly path) for this tool's pyRevit command, or None.

    Every loaded assembly is searched for a concrete ``IExternalCommand``
    whose full name carries this tool's name. That is deliberately not a
    guess at pyRevit's naming scheme, which has changed between releases -
    it is whatever is actually loaded and actually a command.

    Assemblies with no file on disk are skipped: those are generated in
    memory and Revit has nothing to load the class back out of. Where more
    than one matches, the newest file wins, which after a reload is the
    one that is live.
    """
    try:
        import clr
        from System import AppDomain
        from Autodesk.Revit.UI import IExternalCommand
        # IronPython hands back its own wrapper for a .NET interface, and
        # the wrapper has no IsAssignableFrom. GetClrType is what turns it
        # into the System.Type the reflection call needs.
        try:
            command_type = clr.GetClrType(IExternalCommand)
        except Exception:
            command_type = IExternalCommand
    except Exception as err:
        log(u'could not begin the search: {0}'.format(err))
        return None

    found = []
    try:
        assemblies = list(AppDomain.CurrentDomain.GetAssemblies())
    except Exception as err:
        log(u'could not list the loaded assemblies: {0}'.format(err))
        return None

    for assembly in assemblies:
        try:
            location = u'{0}'.format(assembly.Location or u'')
        except Exception:
            continue
        if not location or not os.path.isfile(location):
            continue
        try:
            candidates = list(assembly.GetTypes())
        except Exception:
            # A partially loadable assembly throws here. It is not ours.
            continue
        for candidate in candidates:
            try:
                if candidate.IsAbstract or candidate.IsInterface:
                    continue
                if not command_type.IsAssignableFrom(candidate):
                    continue
                name = u'{0}'.format(candidate.FullName)
                if TOOL_TOKEN not in _normalise(name):
                    continue
            except Exception:
                continue
            try:
                stamp = os.path.getmtime(location)
            except Exception:
                stamp = 0.0
            found.append((stamp, name, location))

    if not found:
        return None
    found.sort()
    _stamp, name, location = found[-1]
    return name, location


# ==========================================================================
# building the menu
# ==========================================================================

def build_menu(menu):
    """Add the entry. Called by Revit on every right click. Never raises."""
    try:
        from Autodesk.Revit.UI import CommandMenuItem
    except Exception as err:
        log(u'no CommandMenuItem: {0}'.format(err))
        return False

    resolved = resolve_command()
    if resolved is None:
        # Nothing to point at. Adding nothing is what leaves the empty
        # flyout behind, but an entry that cannot run is worse, and this
        # only happens where the tool is not installed at all.
        log(u'no command class carrying "{0}" is loaded, so no entry was '
            u'added'.format(TOOL_TOKEN))
        return False

    class_name, assembly = resolved
    try:
        menu.AddItem(CommandMenuItem(ITEM_TEXT, class_name, assembly))
        return True
    except Exception as err:
        log(u'could not add the entry: {0}'.format(err))
        return False


# ==========================================================================
# registering
# ==========================================================================

def already_registered():
    try:
        from System import AppDomain
        return bool(AppDomain.CurrentDomain.GetData(GUARD_KEY))
    except Exception:
        return _registered


def _remember():
    global _registered
    _registered = True
    try:
        from System import AppDomain
        AppDomain.CurrentDomain.SetData(GUARD_KEY, 'registered')
    except Exception:
        pass


def _creator():
    """A fresh IContextMenuCreator, or None.

    The class is declared inside the function on purpose: the base
    interface does not exist before Revit 2025, and a class statement at
    module level would be evaluated at import and take the shared
    startup.py down with it.
    """
    try:
        from Autodesk.Revit.UI import IContextMenuCreator

        class ProSheetsContextMenu(IContextMenuCreator):

            def BuildContextMenu(self, menu):
                build_menu(menu)

        return ProSheetsContextMenu()
    except Exception as err:
        log(u'could not build the creator: {0}'.format(err))
        return None


def _register_on(host):
    """Call RegisterContextMenu on a host that has it. (done, reason)."""
    creator = _creator()
    if creator is None:
        return False, u'no creator'
    try:
        host.RegisterContextMenu(ADDIN_ID, creator)
    except Exception as err:
        log(u'RegisterContextMenu threw: {0}'.format(err))
        log(traceback.format_exc())
        return False, u'{0}'.format(err)
    _remember()
    log(u'"{0}" will appear at the bottom of the right click menu in the '
        u'Project Browser and the canvas.'.format(ITEM_TEXT))
    return True, u'registered'


def _defer(candidate):
    """Register at ApplicationInitialized instead. (deferred, reason).

    The last resort, for a Revit that has the context menu types but whose
    startup object does not carry the method - a 2025 where the caller only
    had a ``UIControlledApplication`` to offer. ``ApplicationInitialized``
    is the first moment a ``UIApplication`` can be built, and that does
    have the method on 2025.

    Only ``+=`` is used, never ``-=``: detaching a .NET event handler from
    IronPython does not reliably find the same handler again, and the
    handler is harmless after it has run because ``already_registered``
    stops the second pass.
    """
    try:
        controlled = getattr(candidate, 'ControlledApplication', None)
        if controlled is None or not hasattr(controlled,
                                            'ApplicationInitialized'):
            return False, u'nothing to defer to'

        def _on_initialised(sender, args):
            try:
                if already_registered():
                    return
                from Autodesk.Revit.UI import UIApplication
                done, why = _register_on(UIApplication(sender))
                if done:
                    log(u'registered late, at ApplicationInitialized')
                else:
                    log(u'the late registration failed too: '
                        u'{0}'.format(why))
            except Exception as err:
                log(u'the late registration threw: {0}'.format(err))
                log(traceback.format_exc())

        controlled.ApplicationInitialized += _on_initialised
        log(u'deferred to ApplicationInitialized, where a UIApplication '
            u'can be built')
        return True, u'deferred to ApplicationInitialized'
    except Exception as err:
        log(u'could not defer: {0}'.format(err))
        return False, u'{0}'.format(err)


def register(*candidates):
    """Put "Print in ProSheets" on the right click menu. (done, reason).

    Pass everything the caller has and let this work out which object the
    running Revit put ``RegisterContextMenu`` on - best candidate first.
    From ``startup.py`` that is ``register(__revit__,
    __uicontrolledapplication__)``; a single argument still works, which is
    what the pre-1.19.0 fragment does, and on Revit 2025 that lands on the
    deferred route rather than going dormant.

    Safe to call more than once and safe to call on any Revit: two pasted
    startup fragments, or a startup fragment and a hook, both calling this
    is a no-op the second time. Never raises - the caller is a shared
    ``startup.py`` and an exception there stops pyRevit loading every tool
    in the extension, not just this one.
    """
    try:
        if already_registered():
            return False, u'already registered in this session'

        log_reset(u'RevoBIM Pro Sheets Exporter - context menu')
        usable, host, reason = available(*candidates)
        if usable:
            done, why = _register_on(host)
            if done:
                log(u'registered on {0}'.format(reason))
                return True, reason
            log(u'registration failed on {0}: {1}'.format(reason, why))
            return False, why

        # The types are here but no candidate carries the method: a 2025
        # given only a UIControlledApplication. Worth one more try rather
        # than a dormant feature on the release this was asked for.
        present, _why = api_present()
        if present:
            log(u'{0}; trying the deferred route'.format(reason))
            for candidate in candidates:
                deferred, detail = _defer(candidate)
                if deferred:
                    return False, detail

        log(u'dormant: {0}'.format(reason))
        return False, reason
    except Exception as err:
        log(u'registration failed: {0}'.format(err))
        log(traceback.format_exc())
        return False, u'{0}'.format(err)


# ==========================================================================
# the second anchor
#
# The shared files rule says a feature must not hang off one shared file,
# because two anchors is one bad zip away from none. This feature can only
# have one, and it is worth writing down why, because the obvious second
# anchors have all been tried and none of them hold.
#
# A pushbutton script is the tempting one: every pyRevit command gets
# __revit__, and from 2025 a UIApplication does have RegisterContextMenu,
# so the tool could register itself the first time it is opened and nobody
# would ever have to edit startup.py. It does not work. The call is
# accepted and the entry can even appear, but BuildContextMenu is not
# called back, so the item does nothing - reported on the pyRevit forum and
# the reason this module does not try it. Registering has to happen while
# Revit is still building its UI.
#
# A hook is the other one, and app-init hooks are reported as not working
# for this either. ApplicationInitialized is used by _defer above, but only
# as a fallback reached from startup.py, not as an independent anchor.
#
# So the second anchor is not a second place to register from. It is the
# tool noticing, every time it opens, that the first anchor has gone -
# which is the failure the rule exists to catch. An overwritten startup.py
# leaves a line in the log rather than a feature that quietly stopped
# existing and nobody spots for a month.
# ==========================================================================

def audit(uiapp):
    """Leave a trace when the tool opens and the entry is not there."""
    try:
        if already_registered():
            return True
        version = host_version(uiapp)
        if version and version < MIN_VERSION:
            return True                    # dormant by design, not missing
        log(u'The tool opened on Revit {0} and "{1}" is not registered. '
            u'Either the block from startup_fragment.py was never pasted '
            u'into the extension\'s startup.py, or a later delivery '
            u'overwrote that file. Paste it and restart Revit - the entry '
            u'cannot be added once Revit has finished '
            u'starting.'.format(version or u'?', ITEM_TEXT))
        return False
    except Exception:
        return False
