# -*- coding: utf-8 -*-
u"""Project Browser Pro - the dockable panes, as plain data.

One pane with every tab, plus one per tab so each can be docked on its own.
The GUIDs are fixed for ever: Revit remembers where each pane was docked by
its GUID, so changing one loses the user's layout for that pane.

All of them are registered at Revit start up (that is the only time Revit will
accept a dockable pane). A pane builds its browser the first time it is
shown, so these registrations cost Revit's start up almost nothing.
"""

PANES = [
    # (id, title shown on the pane's tab, fixed tab or None, GUID)
    (u'main', u'RevoBIM Project Browser', None, u'6affdb17-3970-4c31-a942-3327bdd36bd9'),
    (u'views', u'RevoBIM Views', u'views', u'a63035b5-3a31-4ad8-ba6f-4f18d4026ceb'),
    (u'sheets', u'RevoBIM Sheets', u'sheets', u'56ff8955-1fb8-4ed5-93d9-e25cf2597455'),
    (u'panels', u'RevoBIM Panel Schedules', u'panels', u'72e05c17-52e0-434c-af19-95e37456df0c'),
    (u'schedules', u'RevoBIM Schedules', u'schedules', u'c4c09698-91a0-442e-9606-1c3727674208'),
    (u'families', u'RevoBIM Families', u'families', u'e0515089-41d7-432b-893d-bd7f02f4218c'),
    # added in 1.1.0 - registers at the first Revit start after updating
    (u'favourites', u'RevoBIM Favourites', u'favourites', u'364c5e3f-2026-42dc-a7b8-3808cfd90a39'),
    # added in 1.2.0
    (u'legends', u'RevoBIM Legends and Drafting Views', u'legends', u'833e1a09-eecb-4db8-819b-7e5e56c4dbb5'),
    # Pinned copies: a heading dragged out of the browser opens in the first
    # of these Revit is not showing. Revit only takes a dockable pane at
    # start up, so the slots are made then, empty, and filled when used.
    # Revit fixes a pane's title when it is registered, so the heading's
    # own name is shown inside the pane instead.
    (u'pin1', u'RevoBIM Pinned 1', u'pin:1', u'9a4717c2-d24f-4ccb-bfae-e7f2ef726a29'),
    (u'pin2', u'RevoBIM Pinned 2', u'pin:2', u'c7e48661-125a-49a7-8830-675734607a60'),
    (u'pin3', u'RevoBIM Pinned 3', u'pin:3', u'699ddf7d-1895-4d6b-8601-3006d90143cd'),
    (u'pin4', u'RevoBIM Pinned 4', u'pin:4', u'65178229-7b60-4407-88ce-4cfbc88a28f2'),
    (u'pin5', u'RevoBIM Pinned 5', u'pin:5', u'7e566194-e482-4c1e-8544-532827df1d87'),
    (u'pin6', u'RevoBIM Pinned 6', u'pin:6', u'c991224b-543e-433c-8fbc-f170a4e49399'),
    (u'pin7', u'RevoBIM Pinned 7', u'pin:7', u'5468e1bd-eede-4527-9a0f-afdf8263984c'),
    (u'pin8', u'RevoBIM Pinned 8', u'pin:8', u'1a0d841f-3d4e-4dee-aa3f-85c616b4cdf3'),
]

MAIN_GUID = PANES[0][3]


def guid_for(tab):
    u"""The pane for a tab; the All tab (or None) is the main pane."""
    for pane_id, title, fixed, guid in PANES:
        if fixed == tab:
            return guid
    return MAIN_GUID


def title_for(tab):
    for pane_id, title, fixed, guid in PANES:
        if fixed == tab:
            return title
    return PANES[0][1]


PIN_SLOTS = [(int(fixed.split(u':')[1]), guid) for pane_id, title, fixed, guid in PANES
             if fixed and fixed.startswith(u'pin:')]


def pin_guids():
    return [guid for slot, guid in PIN_SLOTS]


def pin_slot_for(guid):
    for slot, value in PIN_SLOTS:
        if value == guid:
            return slot
    return None
