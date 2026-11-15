# -*- coding: utf-8 -*-
"""Palettes. Dark is Revit's own dark, sampled from its Project Browser."""

REVIT_DARK = {
    'Title': '#222933', 'Window': '#3C4454', 'Field': '#2D3441',
    'Card': '#323C48', 'Hover': '#444E5E', 'Selection': '#3A7392',
    'Edge': '#515C6B', 'Text': '#EEF0F4', 'Muted': '#A4AAB1',
    'Blue': '#5AAEEB', 'Orange': '#F0A040', 'Green': '#3FA75A',
    'GreenHover': '#4EC06D', 'Red': '#F07A76', 'OnAccent': '#FFFFFF',
}

LIGHT = {
    'Title': '#E4E7EB', 'Window': '#F3F4F6', 'Field': '#FFFFFF',
    'Card': '#FFFFFF', 'Hover': '#E1E5EA', 'Selection': '#BBDDF3',
    'Edge': '#C4C9D0', 'Text': '#1E2227', 'Muted': '#5C6570',
    'Blue': '#1B72BE', 'Orange': '#B96A12', 'Green': '#2E8546',
    'GreenHover': '#37995A', 'Red': '#C73A36', 'OnAccent': '#FFFFFF',
}


def palette(name):
    return LIGHT if name == 'light' else REVIT_DARK
