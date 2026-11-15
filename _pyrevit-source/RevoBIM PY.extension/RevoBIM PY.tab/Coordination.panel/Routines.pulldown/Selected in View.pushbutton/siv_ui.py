# -*- coding: utf-8 -*-
"""Selected in View - XAML loading, palette, icon, owner, easter egg."""
import io
import os

import siv_clr  # noqa: F401  (assemblies first)

from System.IO import File, MemoryStream
from System.Windows.Markup import XamlReader
from System.Windows.Media import SolidColorBrush, ColorConverter, Geometry
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption
from System.Windows.Interop import WindowInteropHelper

import siv_core as core

LAYOUT = 'SelectedInView.xaml'
THEME = 'Theme.xaml'


def _read(path):
    with io.open(path, 'r', encoding='utf-8') as fh:
        return fh.read()


def load_window(folder):
    win = XamlReader.Parse(_read(os.path.join(folder, LAYOUT)))
    theme = XamlReader.Parse(_read(os.path.join(folder, THEME)))
    win.Resources.MergedDictionaries.Add(theme)
    return win


def brush(hex_text):
    b = SolidColorBrush(ColorConverter.ConvertFromString(hex_text))
    try:
        b.Freeze()
    except Exception:
        pass
    return b


def apply_palette(win, mode):
    """Written onto window.Resources, which wins over the merged Theme.xaml,
    so an open window re-themes in place."""
    palette = core.PALETTES.get(mode) or core.PALETTES['dark']
    for key, hex_text in palette.items():
        win.Resources[key] = brush(hex_text)


def geometry(data):
    return Geometry.Parse(data)


def load_image(path):
    """From bytes, never BitmapImage.UriSource (System.Uri moved in 2025)."""
    try:
        if not os.path.exists(path):
            return None
        img = BitmapImage()
        img.BeginInit()
        img.StreamSource = MemoryStream(File.ReadAllBytes(path))
        img.CacheOption = BitmapCacheOption.OnLoad
        img.EndInit()
        img.Freeze()
        return img
    except Exception:
        return None


def set_owner(win, uiapp):
    try:
        WindowInteropHelper(win).Owner = uiapp.MainWindowHandle
        return True
    except Exception:
        return False


def attach_egg(win):
    """Hand the logo to the shared easter egg. Returns True when the shared
    hook took it; otherwise the caller counts slow clicks itself."""
    try:
        from revobim.egg import egg_hook
    except Exception:
        return False
    for name in ('attach_to_window', 'attach'):
        fn = getattr(egg_hook, name, None)
        if fn is None:
            continue
        try:
            fn(win)
            return True
        except Exception:
            continue
    return False


def launch_egg(win, mode):
    try:
        from revobim.egg import egg_hook
        egg_hook.launch(win, mode, None)
        return True
    except Exception:
        return False
