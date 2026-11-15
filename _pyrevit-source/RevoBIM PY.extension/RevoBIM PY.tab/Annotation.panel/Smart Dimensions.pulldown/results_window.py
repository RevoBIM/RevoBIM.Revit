# -*- coding: utf-8 -*-
"""Themed results window for Smart Dimensions.

Results are reported in a RevoBIM window rather than the pyRevit output window.
Everything decorative sits in a try/except so cosmetics can never take the tool
down.
"""

import os

from pyrevit import forms

XAML_NAME = "SmartDimensionsResults.xaml"


def load_bitmap(path):
    """Images from bytes, never from System.Uri - Uri moved assemblies in 2025."""
    try:
        from System.IO import File, MemoryStream
        from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption

        if not os.path.isfile(path):
            return None
        image = BitmapImage()
        image.BeginInit()
        image.StreamSource = MemoryStream(File.ReadAllBytes(path))
        image.CacheOption = BitmapCacheOption.OnLoad
        image.EndInit()
        try:
            image.Freeze()
        except Exception:
            pass
        return image
    except Exception:
        return None


class ResultsWindow(forms.WPFWindow):
    def __init__(self, xaml_path, title, lines, tone, version, icon_path):
        forms.WPFWindow.__init__(self, xaml_path)
        try:
            self.tool_name.Text = title
        except Exception:
            pass
        try:
            self.version_text.Text = "v" + str(version)
        except Exception:
            pass
        try:
            self.body_text.Text = "\n".join(lines)
        except Exception:
            pass
        try:
            if tone == "ok":
                self.section_tick.Background = self._brush("#3FA75A")
                self.section_title.Text = "Done"
                self.status_text.Text = "Nothing needed a second look."
            else:
                self.section_tick.Background = self._brush("#E8912D")
                self.section_title.Text = "Needs a look"
                self.status_text.Text = "Everything else went through."
        except Exception:
            pass
        try:
            bitmap = load_bitmap(icon_path)
            if bitmap is not None:
                self.header_icon.Source = bitmap
        except Exception:
            pass

    @staticmethod
    def _brush(hex_value):
        from System.Windows.Media import BrushConverter

        return BrushConverter().ConvertFrom(hex_value)

    def header_drag(self, sender, args):
        try:
            self.DragMove()
        except Exception:
            pass

    def close_click(self, sender, args):
        try:
            self.Close()
        except Exception:
            pass


def show(title, lines, tone, version, pulldown_folder, icon_path=None):
    xaml_path = os.path.join(pulldown_folder, XAML_NAME)
    if icon_path is None:
        icon_path = os.path.join(pulldown_folder, "icon.png")
    window = ResultsWindow(xaml_path, title, lines, tone, version, icon_path)
    window.ShowDialog()
