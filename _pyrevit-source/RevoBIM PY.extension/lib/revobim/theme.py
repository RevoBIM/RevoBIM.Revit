# -*- coding: utf-8 -*-
"""
theme.py - shared RevoBIM PY palette and cross-version icon loading.

Colours match claude/RevoBIM theme reference.md so every tool in the suite
reads the same. Kept as plain constants (not a XAML resource dictionary)
because template-scoped resources have proven unreliable under IronPython
2.7 in this extension - each tool's XAML embeds these hex values directly,
sourced from here so a palette change is a one-place edit to check against.
"""

WINDOW_BG = "#232326"
CARD_BG = "#2B2B2E"
FIELD_BG = "#1C1C1F"
BAR_BG = "#1C1C1F"
BORDER = "#3E3E42"
TEXT = "#E4E4E4"
TEXT_MUTED = "#9A9A9E"
BLUE = "#4FA3E3"
ORANGE = "#E8912D"
GREEN = "#3FA75A"
GREEN_HOVER = "#4EC06D"
RED = "#D9534F"
SELECTION = "#2B5473"


def load_bitmap(path):
    """Loads a PNG into a WPF BitmapImage from bytes rather than from
    BitmapImage.UriSource - `from System import Uri` throws ImportError on
    Revit 2025+, so this route is used everywhere in the suite."""
    import clr
    clr.AddReference("PresentationCore")
    clr.AddReference("WindowsBase")
    from System.IO import MemoryStream, File
    from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption

    try:
        data = File.ReadAllBytes(path)
        stream = MemoryStream(data)
        bitmap = BitmapImage()
        bitmap.BeginInit()
        bitmap.CacheOption = BitmapCacheOption.OnLoad
        bitmap.StreamSource = stream
        bitmap.EndInit()
        bitmap.Freeze()
        return bitmap
    except Exception:
        return None
