# -*- coding: utf-8 -*-
"""RevoBIM Match Offset - the settings window.

Standalone and modal: nothing here needs anything picked in the view, so the
window has no reason to be modeless and so no reason to need a persistent
engine. Nothing is written until Apply.

Three tabs rather than one long column, because the window must fit all of a
section without scrolling and there are now two tools' worth of settings in
it. The tabs are plain buttons swapping Visibility rather than a TabControl:
WPF's stock TabControl would need a full control template of its own to be
themed, and this needs none.
"""

import mo_clr  # noqa: F401

import os

from System.Windows import Thickness, Visibility
from System.Windows.Controls import Button, CheckBox, TextBlock

import mo_shortcuts
import mo_ui
from mo_core import (
    CATEGORY_DEFS, CATEGORY_GROUPS, DEFAULTS, RIBBON_PREFIX, categories_in,
    enabled_categories, format_mm, is_on, is_silent, load_settings, log,
    on_off, parse_number, save_settings, to_text,
)

ROUND_MODE_CHOICES = (
    (u"up", u"up to the next"),
    (u"nearest", u"to the nearest"),
    (u"down", u"down to the last"),
)
ROUND_DATUM_CHOICES = (
    (u"level", u"the offset from its level"),
    (u"project", u"the project elevation"),
)
MEASURE_CHOICES = (
    (u"size", u"the size parameters"),
    (u"box", u"the bounding box"),
)
POINT_MEASURE_CHOICES = (
    (u"solid", u"their real faces"),
    (u"insertion", u"their offset from level"),
    (u"box", u"their bounding box"),
)
FAB_MEASURE_CHOICES = (
    (u"parameters", u"top and bottom of part"),
    (u"solid", u"their real faces"),
    (u"box", u"their bounding box"),
)
HANGER_TOP_CHOICES = (
    (u"bearing", u"the face they bear on"),
    (u"solid", u"the top of their solids"),
    (u"box", u"their bounding box"),
)
FRAMING_CHOICES = (
    (u"top", u"the top face it supports on"),
    (u"solid", u"its real faces"),
    (u"box", u"its bounding box"),
)
SLOPED_CHOICES = (
    (u"skip", u"are reported and left alone"),
    (u"point", u"are matched at the clicked point"),
)
FITTING_CHOICES = (
    (u"skip", u"are left for their pipes to move"),
    (u"move", u"are moved on their own"),
)
SHOW_CHOICES = (
    (u"problems", u"only if something needs a look"),
    (u"always", u"always"),
    (u"never", u"never"),
)
SLOPE_SOURCE_CHOICES = (
    (u"main", u"the main's own fall"),
    (u"fixed", u"a fixed 1 in N"),
)
SLOPE_DIRECTION_CHOICES = (
    (u"towards", u"towards the junction"),
    (u"away", u"away from the junction"),
    (u"keep", u"the way it already falls"),
)
SLOPE_REPEAT_CHOICES = (
    (u"pairs", u"ask for a new main"),
    (u"main", u"keep the same main"),
)
SLOPE_JUNCTION_CHOICES = (
    (u"auto", u"tee or bend to suit"),
    (u"none", u"bring the ends together only"),
)

BUTTON_NAMES = (
    (u"key_bottom", RIBBON_PREFIX + u"Match Offset Bottom"),
    (u"key_middle", RIBBON_PREFIX + u"Match Offset Middle"),
    (u"key_top", RIBBON_PREFIX + u"Match Offset Top"),
    (u"key_slope", RIBBON_PREFIX + u"Match Offset Slope"),
)

KEY_BOXES = (
    (u"key_bottom", 'KeyBottom'),
    (u"key_middle", 'KeyMiddle'),
    (u"key_top", 'KeyTop'),
    (u"key_slope", 'KeySlope'),
)

TABS = (
    ('TabOffset', 'PanelOffset'),
    ('TabSlope', 'PanelSlope'),
    ('TabPicking', 'PanelPicking'),
)


# ======================================================================
# small helpers
# ======================================================================

def fill_combo(combo, choices, value):
    combo.Items.Clear()
    values = []
    index = 0
    for position, pair in enumerate(choices):
        values.append(pair[0])
        combo.Items.Add(pair[1])
        if pair[0] == to_text(value):
            index = position
    combo.Tag = values
    combo.SelectedIndex = index


def combo_value(combo, fallback):
    try:
        values = combo.Tag
        position = combo.SelectedIndex
        if values is not None and 0 <= position < len(values):
            return values[position]
    except Exception:
        pass
    return fallback


def number_or_default(text, key, floor=None):
    value = parse_number(text, None)
    if value is None or (floor is not None and value < floor):
        value = parse_number(DEFAULTS.get(key), 0.0)
    return format_mm(value, 2)


# ======================================================================
# the window
# ======================================================================


def category_exists(bic_name):
    """Is this category in the running Revit at all?

    MEP ancillary framing arrived in a later Revit than the oldest this tool
    supports. A tick box for a category that does not exist would tick
    nothing, so on a Revit without it the row is not offered.
    """
    try:
        from Autodesk.Revit.DB import BuiltInCategory
    except Exception:
        return True
    try:
        return getattr(BuiltInCategory, bic_name, None) is not None
    except Exception:
        return False

class SettingsWindow(object):

    def __init__(self, uiapp):
        self.uiapp = uiapp
        self.settings = load_settings()
        self.window = mo_ui.load_window(
            'MatchOffsetSettings.xaml', self.settings.get(u"theme", u"auto"))
        self.find = self.window.FindName
        self.category_boxes = {}
        self.category_headings = {}
        self._build()

    # ------------------------------------------------------------------
    def _build(self):
        settings = self.settings
        mo_ui.wire_header(self.window, settings, self._theme_changed)

        self.find('RoundStep').Text = to_text(
            settings.get(u"round_step_mm", u"0"))
        self.find('SlopeTol').Text = to_text(
            settings.get(u"slope_tol_deg", u"0.5"))
        self.find('SlopeFixedN').Text = to_text(
            settings.get(u"slope_fixed_n", u"80"))
        self.find('SlopeSteep').Text = to_text(
            settings.get(u"slope_steep_deg", u"46"))
        self.find('SlopeLimit').Text = to_text(
            settings.get(u"slope_limit", u"400"))
        self.find('SlopeStub').Text = to_text(
            settings.get(u"slope_stub_mm", u"0"))
        self.find('SlopeLateral').Text = to_text(
            settings.get(u"slope_inline_offset_mm", u"50"))

        fill_combo(self.find('RoundMode'), ROUND_MODE_CHOICES,
                   settings.get(u"round_mode"))
        fill_combo(self.find('RoundDatum'), ROUND_DATUM_CHOICES,
                   settings.get(u"round_datum"))
        fill_combo(self.find('MeasureMode'), MEASURE_CHOICES,
                   settings.get(u"measure"))
        fill_combo(self.find('PointMeasure'), POINT_MEASURE_CHOICES,
                   settings.get(u"point_measure"))
        fill_combo(self.find('FabMeasure'), FAB_MEASURE_CHOICES,
                   settings.get(u"fab_measure"))
        fill_combo(self.find('HangerTop'), HANGER_TOP_CHOICES,
                   settings.get(u"fab_hanger_top"))
        fill_combo(self.find('FramingMeasure'), FRAMING_CHOICES,
                   settings.get(u"framing_measure"))
        fill_combo(self.find('SlopedMode'), SLOPED_CHOICES,
                   settings.get(u"sloped"))
        fill_combo(self.find('FittingMode'), FITTING_CHOICES,
                   settings.get(u"connected_fittings"))
        fill_combo(self.find('ShowResults'), SHOW_CHOICES,
                   settings.get(u"show_results"))
        fill_combo(self.find('SlopeSource'), SLOPE_SOURCE_CHOICES,
                   settings.get(u"slope_source"))
        fill_combo(self.find('SlopeDirection'), SLOPE_DIRECTION_CHOICES,
                   settings.get(u"slope_direction"))
        fill_combo(self.find('SlopeFitting'), SLOPE_JUNCTION_CHOICES,
                   settings.get(u"slope_fitting"))
        fill_combo(self.find('SlopeRepeat'), SLOPE_REPEAT_CHOICES,
                   settings.get(u"slope_repeat"))

        for name, key in (('MoveSourceCheck', u"move_source_on_round"),
                          ('InsulationCheck', u"include_insulation"),
                          ('PreselectCheck', u"use_preselection"),
                          ('RememberCheck', u"remember_datum"),
                          ('SlopeMatchCheck', u"slope_match_slope"),
                          ('SlopeTrimCheck', u"slope_trim"),
                          ('SlopeApparentCheck', u"slope_apparent"),
                          ('SlopeExtendCheck', u"slope_extend_main"),
                          ('SlopeHandCheck', u"slope_hand_fitting"),
                          ('SlopeSquareCheck', u"slope_square_branch"),
                          ('SlopeInLineCheck', u"slope_in_line"),
                          ('HangerRodsCheck', u"fab_hanger_rods"),
                          ('DebugCheck', u"debug_report"),
                          ('SilentCheck', u"silent")):
            self.find(name).IsChecked = is_on(settings, key)

        for key, name in KEY_BOXES:
            self.find(name).Text = to_text(settings.get(key))

        self._build_categories()

        # Handlers are bound here with += rather than wired in the XAML.
        # A XAML-wired handler that silently fails to bind leaves a window
        # that looks right and does nothing, with no traceback to read.
        self.find('CategoryAll').Click += self._all_categories
        self.find('CategoryNone').Click += self._no_categories
        self.find('CategorySearch').TextChanged += self._filter_categories
        self.find('ApplyShortcuts').Click += self._apply_shortcuts
        self.find('OpenShortcuts').Click += self._open_shortcuts
        self.find('ApplyButton').Click += self._apply
        self.find('CloseFooter').Click += self._close
        for tab, _panel in TABS:
            self.find(tab).Click += self._tab_handler(tab)

        self._show_tab('TabOffset')
        self._say(u"")

    # ------------------------------------------------------------------
    def _tab_handler(self, tab):
        def handler(sender, args):
            self._show_tab(tab)
        return handler

    def _show_tab(self, wanted):
        for tab, panel in TABS:
            active = (tab == wanted)
            self.find(panel).Visibility = (Visibility.Visible if active
                                           else Visibility.Collapsed)
            chip = self.find(tab)
            chip.SetResourceReference(
                Button.ForegroundProperty,
                'BlueBrush' if active else 'MutedBrush')

    def _theme_changed(self, mode):
        # The palette is swapped on the open window, so the tab that is
        # lit has to be pointed at the new brush rather than the old one.
        for tab, panel in TABS:
            if self.find(panel).Visibility == Visibility.Visible:
                self._show_tab(tab)
                return

    # ------------------------------------------------------------------
    def _build_categories(self):
        """The category list, under its own headings.

        Forty-six ticks in one column is a list nobody reads; the headings
        cost six lines and make it scannable. They are plain TextBlocks
        rather than anything clever, and the keyword filter hides a heading
        whose whole group has been filtered away, so a search never leaves a
        heading standing over nothing.
        """
        panel = self.find('CategoryPanel')
        panel.Children.Clear()
        self.category_boxes = {}
        self.category_headings = {}
        chosen = set(enabled_categories(self.settings))
        first = True
        for group in CATEGORY_GROUPS:
            rows = [r for r in categories_in(group) if category_exists(r[2])]
            if not rows:
                continue
            heading = TextBlock()
            heading.Text = group
            heading.Margin = Thickness(0, 0 if first else 10, 0, 5)
            heading.SetResourceReference(TextBlock.ForegroundProperty,
                                         'OrangeBrush')
            panel.Children.Add(heading)
            self.category_headings[group] = heading
            first = False
            for key, label, bic, _group, _on in rows:
                if not category_exists(bic):
                    continue
                box = CheckBox()
                box.Content = label
                box.Margin = Thickness(10, 0, 0, 6)
                box.IsChecked = key in chosen
                box.Tag = key
                panel.Children.Add(box)
                self.category_boxes[key] = box

    def _all_categories(self, sender, args):
        for box in self.category_boxes.values():
            if box.Visibility == Visibility.Visible:
                box.IsChecked = True

    def _no_categories(self, sender, args):
        for box in self.category_boxes.values():
            if box.Visibility == Visibility.Visible:
                box.IsChecked = False

    def _filter_categories(self, sender, args):
        term = to_text(self.find('CategorySearch').Text).strip().lower()
        showing = {}
        for group in CATEGORY_GROUPS:
            showing[group] = False
        for key, label, _bic, group, _on in CATEGORY_DEFS:
            box = self.category_boxes.get(key)
            if box is None:
                continue
            text = to_text(label).lower()
            hit = (not term) or all([w in text for w in term.split()]) \
                or (term in to_text(group).lower())
            box.Visibility = Visibility.Visible if hit else Visibility.Collapsed
            if hit:
                showing[group] = True
        for group, heading in self.category_headings.items():
            heading.Visibility = (Visibility.Visible if showing.get(group)
                                  else Visibility.Collapsed)

    def _chosen_categories(self):
        keys = []
        for key, _label, _bic, _group, _on in CATEGORY_DEFS:
            box = self.category_boxes.get(key)
            if box is not None and box.IsChecked:
                keys.append(key)
        return keys

    # ------------------------------------------------------------------
    def _say(self, text):
        try:
            self.find('StatusText').Text = to_text(text)
        except Exception:
            pass

    def _say_shortcuts(self, text):
        try:
            self.find('ShortcutStatus').Text = to_text(text)
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _collect(self):
        settings = dict(self.settings)

        settings[u"round_step_mm"] = number_or_default(
            self.find('RoundStep').Text, u"round_step_mm", 0.0)
        settings[u"slope_tol_deg"] = number_or_default(
            self.find('SlopeTol').Text, u"slope_tol_deg", 0.0)
        settings[u"slope_fixed_n"] = number_or_default(
            self.find('SlopeFixedN').Text, u"slope_fixed_n", 1.0)
        settings[u"slope_steep_deg"] = number_or_default(
            self.find('SlopeSteep').Text, u"slope_steep_deg", 1.0)
        settings[u"slope_limit"] = number_or_default(
            self.find('SlopeLimit').Text, u"slope_limit", 1.0)
        settings[u"slope_stub_mm"] = number_or_default(
            self.find('SlopeStub').Text, u"slope_stub_mm", 0.0)
        settings[u"slope_inline_offset_mm"] = number_or_default(
            self.find('SlopeLateral').Text, u"slope_inline_offset_mm", 0.0)

        settings[u"round_mode"] = combo_value(self.find('RoundMode'), u"up")
        settings[u"round_datum"] = combo_value(self.find('RoundDatum'),
                                               u"level")
        settings[u"measure"] = combo_value(self.find('MeasureMode'), u"size")
        settings[u"point_measure"] = combo_value(self.find('PointMeasure'),
                                                 u"solid")
        settings[u"fab_measure"] = combo_value(self.find('FabMeasure'),
                                               u"parameters")
        settings[u"fab_hanger_top"] = combo_value(self.find('HangerTop'),
                                                  u"bearing")
        settings[u"framing_measure"] = combo_value(
            self.find('FramingMeasure'), u"top")
        settings[u"sloped"] = combo_value(self.find('SlopedMode'), u"skip")
        settings[u"connected_fittings"] = combo_value(
            self.find('FittingMode'), u"skip")
        settings[u"show_results"] = combo_value(self.find('ShowResults'),
                                                u"problems")
        settings[u"slope_source"] = combo_value(self.find('SlopeSource'),
                                                u"main")
        settings[u"slope_direction"] = combo_value(
            self.find('SlopeDirection'), u"towards")
        settings[u"slope_fitting"] = combo_value(self.find('SlopeFitting'),
                                                 u"auto")
        settings[u"slope_repeat"] = combo_value(self.find('SlopeRepeat'),
                                                u"pairs")

        for name, key in (('MoveSourceCheck', u"move_source_on_round"),
                          ('InsulationCheck', u"include_insulation"),
                          ('PreselectCheck', u"use_preselection"),
                          ('RememberCheck', u"remember_datum"),
                          ('SlopeMatchCheck', u"slope_match_slope"),
                          ('SlopeTrimCheck', u"slope_trim"),
                          ('SlopeApparentCheck', u"slope_apparent"),
                          ('SlopeExtendCheck', u"slope_extend_main"),
                          ('SlopeHandCheck', u"slope_hand_fitting"),
                          ('SlopeSquareCheck', u"slope_square_branch"),
                          ('SlopeInLineCheck', u"slope_in_line"),
                          ('HangerRodsCheck', u"fab_hanger_rods"),
                          ('DebugCheck', u"debug_report"),
                          ('SilentCheck', u"silent")):
            settings[key] = on_off(self.find(name).IsChecked)

        for key, name in KEY_BOXES:
            settings[key] = mo_shortcuts.normalise_key(self.find(name).Text)

        keys = self._chosen_categories()
        if not keys:
            # Leaving the tool with nothing to pick is not a state worth
            # saving, so Pipes comes straight back on and the footer says so.
            keys = [u"pipes"]
            self.category_boxes[u"pipes"].IsChecked = True
        settings[u"categories"] = u"|".join(keys)
        return settings

    def _apply(self, sender, args):
        settings = self._collect()
        if not save_settings(settings):
            self._say(u"Could not write the settings file.")
            return
        self.settings = settings
        step = parse_number(settings.get(u"round_step_mm"), 0.0)
        parts = []
        if step:
            parts.append(u"offsets round to {0} mm and the first element "
                         u"clicked {1}".format(
                             format_mm(step),
                             u"moves onto the rounded value too"
                             if is_on(settings, u"move_source_on_round")
                             else u"stays where it is"))
        if not is_on(settings, u"slope_trim"):
            parts.append(u"the slope tool matches the fall and the height "
                         u"but does not trim or fit")
        elif is_on(settings, u"slope_match_slope"):
            parts.append(u"the slope tool matches the fall and fits the "
                         u"junction")
        else:
            parts.append(u"the slope tool matches the height only, keeping "
                         u"each branch's own fall")
        if is_silent(settings):
            parts.append(u"nothing is put on screen at the end of a run, "
                         u"though the debug report is still written to disk")
        elif is_on(settings, u"debug_report"):
            parts.append(u"a debug report opens after every run")
        self._say(u"Saved. " + u"; ".join(parts) + u".")

    def _close(self, sender, args):
        self.window.Close()

    # ------------------------------------------------------------------
    def _shortcuts_file(self):
        version = u"2024"
        try:
            version = to_text(self.uiapp.Application.VersionNumber)
        except Exception:
            pass
        return mo_shortcuts.shortcuts_path(
            version, self.settings.get(u"shortcuts_path", u""))

    def _open_shortcuts(self, sender, args):
        try:
            from Autodesk.Revit.UI import RevitCommandId, PostableCommand
            command = RevitCommandId.LookupPostableCommandId(
                PostableCommand.KeyboardShortcuts)
            self.uiapp.PostCommand(command)
            self._say_shortcuts(u"Revit's Keyboard Shortcuts dialog will open "
                                u"when this window closes.")
            self.window.Close()
        except Exception as err:
            self._say_shortcuts(
                u"Revit would not open its shortcuts dialog: {0}. It is under "
                u"View > User Interface > Keyboard Shortcuts.".format(
                    to_text(err)))

    def _apply_shortcuts(self, sender, args):
        settings = self._collect()
        save_settings(settings)
        self.settings = settings

        path = self._shortcuts_file()
        if not os.path.isfile(path):
            self._say_shortcuts(
                u"Revit has not written a shortcuts file yet, so there is "
                u"nothing to edit. Open Revit's Keyboard Shortcuts dialog "
                u"once and press OK - that writes the file with every "
                u"command in it, these buttons included - then come back.")
            return

        wanted = []
        for key_name, command_name in BUTTON_NAMES:
            key = to_text(settings.get(key_name, u"")).strip()
            if key:
                wanted.append((command_name, key))
        if not wanted:
            self._say_shortcuts(u"No key sequences are filled in.")
            return

        try:
            text = mo_shortcuts.read_file(path)
        except Exception as err:
            self._say_shortcuts(u"Could not read {0}: {1}".format(
                path, to_text(err)))
            return

        plan = mo_shortcuts.plan_assignments(text, wanted)
        clashes = []
        missing = []
        for entry in plan:
            if not entry[u"valid"]:
                self._say_shortcuts(
                    u"'{0}' is not a key sequence Revit will take.".format(
                        entry[u"key"]))
                return
            if not entry[u"found"]:
                missing.append(entry[u"command"])
            for conflict in entry[u"conflicts"]:
                clashes.append(u"{0}  is on  {1}{2}".format(
                    entry[u"key"], conflict[u"command"],
                    u"  ({0})".format(conflict[u"paths"])
                    if conflict[u"paths"] else u""))

        clear = True
        if clashes:
            body = (u"These key sequences are already in use:\n\n  " +
                    u"\n  ".join(clashes) +
                    u"\n\nTake them off those commands and give them to "
                    u"Match Offset?")
            answer = mo_ui.message(
                u"Shortcuts already in use", body,
                self.settings.get(u"theme", u"auto"), self.window,
                u"Remap to Match Offset", u"Leave them alone", u"Cancel")
            if answer is None:
                self._say_shortcuts(u"Nothing was changed.")
                return
            clear = bool(answer)

        new_text, report = mo_shortcuts.apply_assignments(text, wanted, clear)
        try:
            backup = mo_shortcuts.write_file(path, new_text)
        except Exception as err:
            self._say_shortcuts(u"Could not write {0}: {1}".format(
                path, to_text(err)))
            return

        lines = []
        if report[u"assigned"]:
            lines.append(u"Assigned: " + u"; ".join(report[u"assigned"]))
        if report[u"cleared"]:
            lines.append(u"Cleared: " + u"; ".join(report[u"cleared"]))
        if report[u"refused"]:
            lines.append(u"Refused: " + u"; ".join(report[u"refused"]))
        if missing:
            lines.append(
                u"Revit had no entry for " + u", ".join(missing) +
                u", so one was written from the ribbon path. If the shortcut "
                u"does not work after a restart, open Revit's shortcuts "
                u"dialog, press OK, and apply again.")
        lines.append(u"Restart Revit for these to take effect.")
        if backup:
            lines.append(u"The old file is at " + backup)
        self._say_shortcuts(u"  ".join(lines))
        log(u"shortcuts written to {0}".format(path))

    # ------------------------------------------------------------------
    def show(self):
        # wire_header has already armed the logo; arming it twice would put
        # two click watchers on the same element.
        self.window.ShowDialog()


def show(uiapp):
    window = SettingsWindow(uiapp)
    window.show()
    return window.settings
