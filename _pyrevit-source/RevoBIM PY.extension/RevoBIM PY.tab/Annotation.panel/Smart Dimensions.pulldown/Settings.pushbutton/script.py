# -*- coding: utf-8 -*-
"""RevoBIM Smart Dimension Settings.

Standalone and modal - nothing here needs picking in the model. Set them,
press Apply, and they are written to
``%APPDATA%\\RevoBIM\\smart_dimensions.txt``; every later run of the command
uses them. A missing or damaged file falls back to the defaults key by key,
and keys from an older version are ignored rather than breaking the load.
"""

__title__ = "RevoBIM\nSmart Dim Settings"
__author__ = "RevoBIM"

import os
import sys
import traceback

_HERE = os.path.dirname(__file__)
_PULLDOWN = os.path.dirname(_HERE)
if _PULLDOWN not in sys.path:
    sys.path.append(_PULLDOWN)

_LOAD_ERROR = None
core = None
try:
    import smart_dimensions_core as core
except Exception:
    _LOAD_ERROR = traceback.format_exc()

from pyrevit import forms

__version__ = getattr(core, "__version__", "1.0.0") if core else "1.0.0"

VIEW_DEFAULT = "<the view's own dimension type>"


def _doc_and_uiapp():
    doc = None
    uiapp = None
    try:
        from pyrevit import HOST_APP

        uiapp = HOST_APP.uiapp
        doc = HOST_APP.doc
    except Exception:
        pass
    if uiapp is None:
        try:
            uiapp = __revit__  # noqa: F821
        except Exception:
            uiapp = None
    if doc is None and uiapp is not None:
        try:
            doc = uiapp.ActiveUIDocument.Document
        except Exception:
            doc = None
    return doc, uiapp


def _load_bitmap(path):
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


class SettingsWindow(forms.WPFWindow):
    def __init__(self, xaml_path, doc, uiapp):
        forms.WPFWindow.__init__(self, xaml_path)
        self.doc = doc
        self.uiapp = uiapp
        self.values = core.load_settings()

        try:
            self.version_text.Text = "v" + str(__version__)
        except Exception:
            pass
        try:
            bitmap = _load_bitmap(os.path.join(_HERE, "icon.png"))
            if bitmap is None:
                bitmap = _load_bitmap(os.path.join(_PULLDOWN, "icon.png"))
            if bitmap is not None:
                self.header_icon.Source = bitmap
        except Exception:
            pass

        self._fill_dimension_types()
        self._to_ui()
        self._update_stack_hint()

    # -- dimension types ----------------------------------------------------

    def _fill_dimension_types(self):
        names = [VIEW_DEFAULT]
        if self.doc is not None:
            try:
                names.extend(core.linear_dimension_type_names(self.doc))
            except Exception:
                pass
        try:
            self.cmb_dim_type.ItemsSource = names
        except Exception:
            pass
        wanted = self.values.get("dim_type", "")
        try:
            if wanted and wanted in names:
                self.cmb_dim_type.SelectedItem = wanted
            else:
                self.cmb_dim_type.SelectedIndex = 0
                if wanted:
                    self.status_text.Text = (
                        "Saved dimension type '{0}' is not in this project - "
                        "the view's own type will be used".format(wanted)
                    )
        except Exception:
            pass

    # -- settings <-> controls ---------------------------------------------

    def _pair(self, key, centre_control, edges_control):
        if self.values.get(key) == "edges":
            edges_control.IsChecked = True
        else:
            centre_control.IsChecked = True

    def _to_ui(self):
        self._pair("pipe_mode", self.pipe_centre, self.pipe_edges)
        self._pair("conduit_mode", self.conduit_centre, self.conduit_edges)
        self._pair("round_duct_mode", self.rduct_centre, self.rduct_edges)
        self._pair("rect_duct_mode", self.xduct_centre, self.xduct_edges)
        self._pair("tray_mode", self.tray_centre, self.tray_edges)

        generic = self.values.get("generic_mode", "auto")
        if generic == "centre":
            self.generic_centre.IsChecked = True
        elif generic == "edges":
            self.generic_edges.IsChecked = True
        else:
            self.generic_auto.IsChecked = True

        self.chk_link_step.IsChecked = self.values.get("link_step") == "on"
        if self.values.get("link_multi") == "on":
            self.link_many.IsChecked = True
        else:
            self.link_single.IsChecked = True
        if self.values.get("link_ref") == "centre":
            self.link_centre.IsChecked = True
        else:
            self.link_face.IsChecked = True

        self.txt_margin.Text = str(self.values.get("line_margin_mm", "150"))
        self.chk_repeat.IsChecked = self.values.get("repeat") == "on"

        self.chk_pull_out.IsChecked = self.values.get("pull_out") == "on"
        self.txt_pull_table.Text = str(self.values.get("pull_threshold_table", ""))
        self.txt_pull_base.Text = str(self.values.get("pull_threshold_base", "150"))
        if self.values.get("pull_layout") == "row":
            self.pull_row.IsChecked = True
        else:
            self.pull_stacked.IsChecked = True
        if self.values.get("pull_side") == "end":
            self.pull_end.IsChecked = True
        else:
            self.pull_start.IsChecked = True
        if self.values.get("pull_datum") == "dim_line":
            self.pull_from_line.IsChecked = True
        else:
            self.pull_from_mep.IsChecked = True
        self.txt_pull_offset.Text = str(self.values.get("pull_offset_mm", "6"))
        self.txt_pull_gap.Text = str(self.values.get("pull_gap_mm", "9"))
        self.txt_pull_clear.Text = str(self.values.get("pull_clear_mm", "6"))

        results = self.values.get("results", "issues")
        if results == "never":
            self.res_never.IsChecked = True
        elif results == "always":
            self.res_always.IsChecked = True
        else:
            self.res_issues.IsChecked = True

    def _number(self, box, key):
        """Read a number out of a text box, putting the default back on junk."""
        text = str(box.Text).strip()
        try:
            float(text)
        except Exception:
            text = core.DEFAULTS[key]
            box.Text = text
        return text

    def _from_ui(self):
        values = {}
        values["pipe_mode"] = "edges" if self.pipe_edges.IsChecked else "centre"
        values["conduit_mode"] = "edges" if self.conduit_edges.IsChecked else "centre"
        values["round_duct_mode"] = "edges" if self.rduct_edges.IsChecked else "centre"
        values["rect_duct_mode"] = "edges" if self.xduct_edges.IsChecked else "centre"
        values["tray_mode"] = "edges" if self.tray_edges.IsChecked else "centre"

        if self.generic_centre.IsChecked:
            values["generic_mode"] = "centre"
        elif self.generic_edges.IsChecked:
            values["generic_mode"] = "edges"
        else:
            values["generic_mode"] = "auto"

        values["link_step"] = "on" if self.chk_link_step.IsChecked else "off"
        values["link_multi"] = "on" if self.link_many.IsChecked else "off"
        values["link_ref"] = "centre" if self.link_centre.IsChecked else "closest_face"

        chosen = None
        try:
            chosen = self.cmb_dim_type.SelectedItem
        except Exception:
            chosen = None
        values["dim_type"] = "" if (not chosen or chosen == VIEW_DEFAULT) else str(chosen)

        values["line_margin_mm"] = self._number(self.txt_margin, "line_margin_mm")
        values["min_gap_mm"] = self.values.get("min_gap_mm", core.DEFAULTS["min_gap_mm"])

        values["repeat"] = "on" if self.chk_repeat.IsChecked else "off"

        values["pull_out"] = "on" if self.chk_pull_out.IsChecked else "off"
        values["pull_layout"] = "row" if self.pull_row.IsChecked else "stacked"
        values["pull_side"] = "end" if self.pull_end.IsChecked else "start"
        values["pull_datum"] = "dim_line" if self.pull_from_line.IsChecked else "mep_edge"
        values["pull_threshold_base"] = self._number(self.txt_pull_base, "pull_threshold_base")
        values["pull_offset_mm"] = self._number(self.txt_pull_offset, "pull_offset_mm")
        values["pull_gap_mm"] = self._number(self.txt_pull_gap, "pull_gap_mm")
        values["pull_clear_mm"] = self._number(self.txt_pull_clear, "pull_clear_mm")

        # the table is rewritten from what parsed, so a typo shows up straight
        # away rather than silently doing nothing on the next run
        table = core.parse_threshold_table(self.txt_pull_table.Text)
        if table:
            scales = list(table.keys())
            scales.sort()
            tidy = "; ".join(
                ["{0}={1:g}".format(scale, table[scale]) for scale in scales]
            )
        else:
            tidy = ""
            if str(self.txt_pull_table.Text).strip():
                self.status_text.Text = (
                    "Nothing in the threshold table parsed - use scale=mm, e.g. 50=200; 100=250"
                )
        values["pull_threshold_table"] = tidy
        self.txt_pull_table.Text = tidy

        values["settings_version"] = core.SETTINGS_VERSION
        self._update_stack_hint()

        if self.res_never.IsChecked:
            values["results"] = "never"
        elif self.res_always.IsChecked:
            values["results"] = "always"
        else:
            values["results"] = "issues"
        return values

    # -- events -------------------------------------------------------------

    def _update_stack_hint(self):
        """Spell the stack out as the run of numbers it will actually produce."""
        try:
            out_mm = float(str(self.txt_pull_offset.Text).strip())
            gap_mm = float(str(self.txt_pull_gap.Text).strip())
        except Exception:
            try:
                self.stack_hint.Text = ""
            except Exception:
                pass
            return

        datum = (
            "the outermost service edge"
            if self.pull_from_mep.IsChecked
            else "the dimension line"
        )
        run = ", ".join(["{0:g}mm".format(out_mm + gap_mm * i) for i in range(3)])
        try:
            self.stack_hint.Text = (
                "Beyond {0}, square to the string:  {1}, ...  - model distances, the "
                "same at every scale".format(datum, run)
            )
        except Exception:
            pass

    def stack_changed(self, sender, args):
        self._update_stack_hint()

    def header_drag(self, sender, args):
        try:
            self.DragMove()
        except Exception:
            pass

    def apply_click(self, sender, args):
        try:
            self.values = self._from_ui()
            if core.save_settings(self.values):
                self.status_text.Text = "Saved to {0}".format(core.SETTINGS_PATH)
            else:
                self.status_text.Text = "Could not write {0}".format(core.SETTINGS_PATH)
        except Exception as err:
            try:
                self.status_text.Text = "Not saved: {0}".format(err)
            except Exception:
                pass

    def shortcuts_click(self, sender, args):
        """Open Revit's own Keyboard Shortcuts dialog."""
        opened = False
        try:
            from Autodesk.Revit.UI import RevitCommandId, PostableCommand

            command_id = RevitCommandId.LookupPostableCommandId(
                PostableCommand.KeyboardShortcuts
            )
            if command_id is not None and self.uiapp is not None:
                self.uiapp.PostCommand(command_id)
                opened = True
        except Exception:
            opened = False
        try:
            if opened:
                self.status_text.Text = (
                    "Search for \"RevoBIM Smart Dimensions\" and assign your keys"
                )
                self.Close()
            else:
                self.status_text.Text = (
                    "Open View > User Interface > Keyboard Shortcuts and search "
                    "\"RevoBIM Smart Dimensions\""
                )
        except Exception:
            pass

    def close_click(self, sender, args):
        try:
            self.Close()
        except Exception:
            pass


def main():
    if _LOAD_ERROR is not None:
        try:
            from Autodesk.Revit.UI import TaskDialog

            TaskDialog.Show(
                "RevoBIM Smart Dimensions",
                "The shared module smart_dimensions_core.py failed to load.\n\n"
                + _LOAD_ERROR,
            )
        except Exception:
            pass
        return

    doc, uiapp = _doc_and_uiapp()
    xaml_path = os.path.join(_PULLDOWN, "SmartDimensionsSettings.xaml")
    SettingsWindow(xaml_path, doc, uiapp).ShowDialog()


main()
