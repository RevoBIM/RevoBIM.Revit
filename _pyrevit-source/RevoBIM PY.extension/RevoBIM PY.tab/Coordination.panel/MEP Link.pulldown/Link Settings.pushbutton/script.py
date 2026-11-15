# -*- coding: utf-8 -*-
"""Settings for Riser Link, Corner Link and Centreline Snap.

The one window in the pulldown. Everything else is a windowless command that
reads what is set here, so it can be driven from a keyboard shortcut.
"""

__title__ = "RevoBIM Link Settings"
__author__ = "RevoBIM"

import os

from pyrevit import forms, script

import mep_link_core as core

logger = script.get_logger()
HERE = os.path.dirname(__file__)


class SettingsWindow(forms.WPFWindow):

    def __init__(self, xaml_path):
        forms.WPFWindow.__init__(self, xaml_path)
        self.values = core.load_settings()
        try:
            self.version_tb.Text = "v" + core.VERSION
        except Exception:
            pass
        self.load_icon()
        self.fill()

    # --- setup -------------------------------------------------------------
    def load_icon(self):
        """Icons are decoration, so any failure here is swallowed.

        Loaded from bytes rather than from a Uri: System.Uri moved assemblies
        and importing it throws on Revit 2025+, which would take the whole
        window down over a picture.
        """
        path = os.path.join(HERE, 'icon.png')
        if not os.path.exists(path):
            return
        try:
            from System.IO import MemoryStream, File
            from System.Windows.Media.Imaging import (BitmapImage,
                                                      BitmapCacheOption)
            bitmap = BitmapImage()
            bitmap.BeginInit()
            bitmap.StreamSource = MemoryStream(File.ReadAllBytes(path))
            bitmap.CacheOption = BitmapCacheOption.OnLoad
            bitmap.EndInit()
            self.tool_icon.Source = bitmap
        except Exception as err:
            logger.debug("icon: {0}".format(err))

    def set_angle(self, key, opt_90, opt_45, opt_custom, textbox, fallback):
        angle = core.setting_angle(self.values, key)
        if abs(angle - 90.0) < 0.01:
            opt_90.IsChecked = True
            textbox.Text = "{0:g}".format(fallback)
        elif abs(angle - 45.0) < 0.01:
            opt_45.IsChecked = True
            textbox.Text = "{0:g}".format(fallback)
        else:
            opt_custom.IsChecked = True
            textbox.Text = "{0:g}".format(angle)

    def fill(self):
        self.set_angle('riser_angle', self.rj_90, self.rj_45, self.rj_custom,
                       self.rj_value, 30)
        self.set_angle('corner_angle', self.ct_90, self.ct_45, self.ct_custom,
                       self.ct_value, 45)

        mode = self.values.get('align_mode', 'xy')
        if mode == 'z':
            self.al_z.IsChecked = True
        elif mode == 'both':
            self.al_both.IsChecked = True
        else:
            self.al_xy.IsChecked = True

        report = self.values.get('report', 'problems')
        if report == 'always':
            self.rp_always.IsChecked = True
        elif report == 'never':
            self.rp_never.IsChecked = True
        else:
            self.rp_problems.IsChecked = True

        self.keep_going.IsChecked = self.values.get('keep_going', 'yes') == 'yes'

    # --- reading back ------------------------------------------------------
    def read_angle(self, opt_90, opt_45, textbox, label):
        """The chosen angle, rounded to five degrees, or None if unusable."""
        if opt_90.IsChecked:
            return 90.0
        if opt_45.IsChecked:
            return 45.0
        try:
            value = float(str(textbox.Text).strip().replace(',', '.'))
        except Exception:
            forms.alert("The {0} custom angle needs to be a number, for "
                        "example 30.".format(label), title="RevoBIM")
            return None
        if value <= 0 or value > 90:
            forms.alert("The {0} custom angle must be above 0 and no more than "
                        "90 degrees, measured from horizontal.".format(label),
                        title="RevoBIM")
            return None

        # bends get set out on site, so the angle is held to a multiple of five
        rounded = core.round_angle(value)
        if abs(rounded - value) > 0.01:
            textbox.Text = "{0:g}".format(rounded)
        return rounded

    # --- handlers ----------------------------------------------------------
    def drag_window(self, sender, args):
        try:
            self.DragMove()
        except Exception:
            pass

    def rj_focus(self, sender, args):
        self.rj_custom.IsChecked = True

    def ct_focus(self, sender, args):
        self.ct_custom.IsChecked = True

    def shortcuts_click(self, sender, args):
        forms.alert("In Revit: View > User Interface > Keyboard Shortcuts.\n\n"
                    "Search for \"RevoBIM\" and the three commands in this "
                    "pulldown are listed:\n\n"
                    "    RevoBIM Riser Link\n"
                    "    RevoBIM Corner Link\n"
                    "    RevoBIM Centreline Snap\n\n"
                    "Assign a key to each. They open no window, so the whole "
                    "tool becomes keys, click, click.",
                    title="RevoBIM - Keyboard Shortcuts")

    def apply_click(self, sender, args):
        riser = self.read_angle(self.rj_90, self.rj_45, self.rj_value,
                                "Riser Link")
        if riser is None:
            return
        corner = self.read_angle(self.ct_90, self.ct_45, self.ct_value,
                                 "Corner Link")
        if corner is None:
            return

        if self.al_z.IsChecked:
            mode = 'z'
        elif self.al_both.IsChecked:
            mode = 'both'
        else:
            mode = 'xy'

        if self.rp_always.IsChecked:
            report = 'always'
        elif self.rp_never.IsChecked:
            report = 'never'
        else:
            report = 'problems'

        values = {
            'riser_angle': "{0:g}".format(riser),
            'corner_angle': "{0:g}".format(corner),
            'align_mode': mode,
            'report': report,
            'keep_going': 'yes' if self.keep_going.IsChecked else 'no',
        }

        if not core.save_settings(values):
            forms.alert("The settings could not be written to\n"
                        "{0}".format(core.SETTINGS_PATH), title="RevoBIM")
            return
        self.Close()

    def close_click(self, sender, args):
        self.Close()


xaml = os.path.join(HERE, 'MEPLinkSettings.xaml')
if os.path.exists(xaml):
    SettingsWindow(xaml).ShowDialog()
else:
    forms.alert("MEPLinkSettings.xaml is missing from the button folder.",
                title="RevoBIM")
