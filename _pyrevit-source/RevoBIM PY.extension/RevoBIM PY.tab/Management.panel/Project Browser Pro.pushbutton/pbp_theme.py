# -*- coding: utf-8 -*-
u"""Project Browser Pro - dark and light, following Revit's UI theme.

The setting is follow / dark / light, so following is a state rather than
the absence of one. Following reads UIThemeManager (Revit 2024 and later) -
the registry lags the live setting, so it is not used.

Two traps kept out of here, both learned on earlier tools:
  * UITheme.Dark is 0. A read tested with `or` or plain truthiness treats
    Dark as a failed read and falls through to Light. The value is tested
    with `is not None`, and its name decides dark or light.
  * UIThemeManager does not exist before Revit 2024, so it is reached with
    getattr on the namespace, never imported at the top of a module.
"""
import os

import pbp_clr  # noqa: F401
from System.IO import File, MemoryStream
from System.Windows.Markup import XamlReader
from System.Windows.Media import SolidColorBrush, ColorConverter

import pbp_log
from pbp_compat import to_text
from pbp_palette import palette

HERE = os.path.dirname(os.path.abspath(__file__))
MERGED_MARK = u'PBP.ThemeMerged'
MODES = (u'follow', u'dark', u'light')
LABELS = {u'follow': u'Auto', u'dark': u'Dark', u'light': u'Light'}
GLYPHS = {
    u'follow': u'F0 M1,6 A5,5 0 1 0 11,6 A5,5 0 1 0 1,6 Z M6,2.2 A3.8,3.8 0 0 1 6,9.8 Z',
    u'dark': u'M7.5,0.8 A5.4,5.4 0 1 0 11.2,8.2 A4.3,4.3 0 1 1 7.5,0.8 Z',
    u'light': u'M6,3.2 A2.8,2.8 0 1 0 6,8.8 A2.8,2.8 0 1 0 6,3.2 Z '
              u'M5.4,0 L6.6,0 L6.6,1.8 L5.4,1.8 Z M5.4,10.2 L6.6,10.2 L6.6,12 L5.4,12 Z '
              u'M0,5.4 L1.8,5.4 L1.8,6.6 L0,6.6 Z M10.2,5.4 L12,5.4 L12,6.6 L10.2,6.6 Z',
}


def read_revit_theme():
    u"""'dark' or 'light' from Revit's UI theme (its ribbon, toolbars and
    palettes), or None where it cannot be read.

    The UI theme, not the canvas: the browser is a palette beside Revit's own
    Project Browser, which follows the UI theme - a dark UI with a light
    canvas must still give a dark browser (1.4.0; before, it went light).
    The canvas is only read where the UI theme cannot be."""
    try:
        import Autodesk.Revit.UI as revit_ui
    except Exception:
        return None
    manager = getattr(revit_ui, u'UIThemeManager', None)
    if manager is None:
        return None
    for attr in (u'CurrentTheme', u'CurrentCanvasTheme'):
        try:
            value = getattr(manager, attr, None)
        except Exception:
            value = None
        if value is not None:
            return u'dark' if u'dark' in to_text(value).lower() else u'light'
    return None


def resolve(mode):
    u"""Revit 2021-2023 have no dark theme and no UIThemeManager, so Auto
    shows light there - which is what Revit itself looks like."""
    if mode in (u'dark', u'light'):
        return mode
    read = read_revit_theme()
    return read if read is not None else u'light'


def next_mode(mode):
    index = MODES.index(mode) if mode in MODES else 0
    return MODES[(index + 1) % len(MODES)]


def brush(hex_text):
    value = SolidColorBrush(ColorConverter.ConvertFromString(hex_text))
    value.Freeze()
    return value


def theme_dictionary():
    u"""A fresh copy of Theme.xaml for one root, read from bytes."""
    data = File.ReadAllBytes(os.path.join(HERE, u'Theme.xaml'))
    stream = MemoryStream(data)
    try:
        return XamlReader.Load(stream)
    finally:
        stream.Close()


def apply(element, theme_name):
    u"""Merge Theme.xaml once, then write the palette onto the element.

    The palette lives on the element's own Resources, in front of the merged
    dictionary in WPF's lookup order, so writing it again repaints everything
    using DynamicResource without reloading anything.
    """
    try:
        resources = element.Resources
        if not resources.Contains(MERGED_MARK):
            resources.MergedDictionaries.Add(theme_dictionary())
            resources[MERGED_MARK] = True
        for key, value in palette(theme_name).items():
            # ...Color keys are Colors (a DropShadowEffect wants a Color,
            # not a brush); everything else is a frozen brush.
            if key.endswith(u'Color'):
                resources[key] = ColorConverter.ConvertFromString(value)
            else:
                resources[key] = brush(value)
        return True
    except Exception:
        pbp_log.exc(u'theme apply')
        return False
