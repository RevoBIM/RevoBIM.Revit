# -*- coding: utf-8 -*-
"""Auto RevCloud - the settings dialog.  Modal, owned by the main window;
nothing here touches the model."""
import arc_clr  # noqa: F401
import arc_core
import arc_ui

from System.Windows.Controls import ComboBoxItem, TextBlock

THEMES = [(u"auto", u"Follow Revit's canvas"), (u"dark", u"Dark"), (u"light", u"Light")]
RESULTS = [(u"needed", u"Only if something needs a look"), (u"always", u"Always"), (u"never", u"Never")]
# Revit decides which side a cloud's arcs bulge from the direction the outline
# is drawn. There is nothing to read back, so this is the escape hatch if the
# convention differs on a release.
ARC_SIDES = [(u"out", u"Outwards"), (u"in", u"Inwards")]
METHODS = [(u"id", u"By element id"), (u"spatial", u"Spatially")]
GUID_MODES = [(u"off", u"Off"), (u"flag", u"Flag - skip identical"),
              (u"trust", u"Trust - cloud any difference")]
REMOVALS = [(u"near", u"Cloud if near an element"),
            (u"always", u"Always cloud"),
            (u"never", u"Never cloud")]

NUMBER_BOXES = [
    (u"MoveTolBox", u"move_tol_mm", 0, 10000),
    (u"SizeTolBox", u"size_tol_mm", 0, 10000),
    (u"RotateTolBox", u"rotate_tol_deg", 0, 180),
    (u"SpatialTolBox", u"spatial_tol_mm", 0, 10000),
    (u"SpatialSearchBox", u"spatial_search_mm", 0, 1000000),
    (u"VisibleTolBox", u"visible_tol_mm", 0, 100),
    (u"MergeBox", u"merge_mm", 0, 500),
    (u"OffsetBox", u"offset_mm", 0, 200),
    (u"MaxCloudsBox", u"max_clouds", 1, 2000),
    (u"ArcLengthBox", u"cloud_arc_mm", 0, 100),
    (u"CommentItemsBox", u"comment_items", 1, 20),
]

CHECKS = [
    (u"MatchEidCheck", u"match_by_eid"),
    (u"CheckTypeCheck", u"check_type"),
    (u"CheckParamsCheck", u"check_params"),
    (u"OnlyVisibleCheck", u"only_visible"),
    (u"CloudRemovedCheck", u"cloud_removed"),
    (u"WriteCommentsCheck", u"write_comments"),
]


def _fill_combo(combo, options, current):
    combo.Items.Clear()
    picked = 0
    for index, (key, label) in enumerate(options):
        item = ComboBoxItem()
        item.Content = label
        item.Tag = key
        combo.Items.Add(item)
        if key == current:
            picked = index
    combo.SelectedIndex = picked


def _combo_value(combo, options):
    try:
        item = combo.SelectedItem
        if item is not None and item.Tag:
            return arc_core.unicode_str(item.Tag)
    except Exception:
        pass
    return options[0][0]


class SettingsWindow(object):
    """Returns the new settings dict from show(), or None on cancel."""

    def __init__(self, owner, settings, palette, on_theme_change=None):
        self.settings = dict(settings)
        self.result = None
        self.palette = palette
        self.on_theme_change = on_theme_change
        self.window = arc_ui.load_window(u"ArcSettings.xaml")
        arc_ui.apply_palette(self.window, palette)
        self.find = self.window.FindName
        if owner is not None:
            try:
                self.window.Owner = owner
            except Exception:
                pass
        arc_ui.Chrome(self.window, escape_closes=True)
        self.find(u"ApplyButton").Click += self.on_apply
        self.find(u"CancelButton").Click += self.on_cancel
        self.find(u"DefaultsButton").Click += self.on_defaults
        self.find(u"CategoriesResetButton").Click += self.on_categories_reset
        self.find(u"ThemeCombo").SelectionChanged += self.on_theme_pick
        self.load(self.settings)

    def load(self, settings):
        for box_name, key, _lo, _hi in NUMBER_BOXES:
            self.find(box_name).Text = arc_core.unicode_str(settings.get(key, arc_core.DEFAULT_MAP[key]))
        for check_name, key in CHECKS:
            self.find(check_name).IsChecked = arc_core.as_bool(settings, key)
        _fill_combo(self.find(u"ThemeCombo"), THEMES, settings.get(u"theme"))
        _fill_combo(self.find(u"ResultsCombo"), RESULTS, settings.get(u"show_results"))
        _fill_combo(self.find(u"ArcSideCombo"), ARC_SIDES, settings.get(u"cloud_arc_side"))
        _fill_combo(self.find(u"MethodCombo"), METHODS, settings.get(u"match_method"))
        _fill_combo(self.find(u"GuidModeCombo"), GUID_MODES, settings.get(u"guid_mode"))
        # One per line in the window, pipes in the file.
        self.find(u"CategoriesBox").Text = u"\r\n".join(
            arc_core.parse_categories(settings.get(u"compare_categories", u"")))
        self.find(u"CompareParamsBox").Text = u"\r\n".join(
            arc_core.parse_categories(settings.get(u"compare_params", u"")))

    def read(self):
        """Returns (settings, problems)."""
        out = dict(self.settings)
        problems = []
        for box_name, key, lo, hi in NUMBER_BOXES:
            text = self.find(box_name).Text.strip()
            try:
                value = float(text)
            except Exception:
                problems.append(u"{0}: '{1}' is not a number".format(key, text))
                continue
            if value < lo or value > hi:
                problems.append(u"{0}: {1} is outside {2} - {3}".format(key, text, lo, hi))
                continue
            if value == int(value) and key not in (u"pixel_ink", u"cell_mm"):
                out[key] = arc_core.unicode_str(int(value))
            else:
                out[key] = arc_core.unicode_str(value)
        for check_name, key in CHECKS:
            out[key] = u"1" if self.find(check_name).IsChecked else u"0"
        out[u"theme"] = _combo_value(self.find(u"ThemeCombo"), THEMES)
        out[u"show_results"] = _combo_value(self.find(u"ResultsCombo"), RESULTS)
        out[u"cloud_arc_side"] = _combo_value(self.find(u"ArcSideCombo"), ARC_SIDES)
        out[u"match_method"] = _combo_value(self.find(u"MethodCombo"), METHODS)
        out[u"guid_mode"] = _combo_value(self.find(u"GuidModeCombo"), GUID_MODES)
        names = arc_core.parse_categories(self.find(u"CategoriesBox").Text)
        if names:
            out[u"compare_categories"] = arc_core.format_categories(names)
        fields = arc_core.parse_categories(self.find(u"CompareParamsBox").Text)
        out[u"compare_params"] = arc_core.format_categories(fields)
        return out, problems

    def on_theme_pick(self, sender, args):
        if self.on_theme_change is None:
            return
        try:
            key = _combo_value(self.find(u"ThemeCombo"), THEMES)
            self.on_theme_change(key)
        except Exception:
            pass

    def on_apply(self, sender, args):
        out, problems = self.read()
        if problems:
            self.find(u"StatusText").Text = u"; ".join(problems)
            self.find(u"StatusText").SetResourceReference(TextBlock.ForegroundProperty, u"RedBrush")
            return
        try:
            arc_core.save_settings(out)
        except Exception as exc:
            self.find(u"StatusText").Text = u"could not save: {0}".format(exc)
            return
        self.result = out
        self.window.Close()

    def on_cancel(self, sender, args):
        self.result = None
        self.window.Close()

    def on_categories_reset(self, sender, args):
        """Put the MEP list back without resetting everything else."""
        try:
            self.find(u"CategoriesBox").Text = u"\r\n".join(arc_core.DEFAULT_CATEGORIES)
        except Exception:
            pass

    def on_defaults(self, sender, args):
        self.load(dict(arc_core.DEFAULT_MAP))

    def show(self):
        try:
            self.window.ShowDialog()
        except Exception:
            return None
        return self.result
