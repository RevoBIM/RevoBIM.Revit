# -*- coding: utf-8 -*-
"""The Resize runs dialog on the Containment tab. Modal, themed; it only
gathers the sizes - the window runs the job and reports."""
import msm_clr  # noqa: F401  - assemblies first

import msm_core as core
import msm_theme as theme
import msm_ui as ui


class ResizeDialog(object):
    def __init__(self, owner, settings, trays, conduits, runs, sizes_now, whole=None):
        self.settings = settings.copy()
        self.answer = None
        self.window = ui.load_window(u"MsmResize.xaml", settings.get(u"theme", u"auto"))
        w = self.window
        find = w.FindName
        self.find = find
        if owner is not None:
            try:
                w.Owner = owner
            except Exception:
                pass
        find(u"VersionText").Text = u"v{0}".format(core.__version__)
        ui.load_icon(find(u"Logo"))
        ui.Chrome(w, header=find(u"HeaderBar"), close_button=find(u"BtnClose"),
                  resizable=False)
        ui.attach_egg(w, find(u"LogoHost"),
                      lambda: theme.palette(theme.resolve(self.settings.get(u"theme"))))

        parts = []
        if trays:
            parts.append(u"{0} cable tray{1}".format(trays, u"" if trays == 1 else u"s"))
        if conduits:
            parts.append(u"{0} conduit{1}".format(conduits, u"" if conduits == 1 else u"s"))
        text = u"{0} in {1} row{2}.".format(u" and ".join(parts) or u"Nothing", runs,
                                          u"" if runs == 1 else u"s")
        if sizes_now:
            text += u" Sizes now: {0}.".format(u", ".join(sizes_now[:8]) +
                                               (u" ..." if len(sizes_now) > 8 else u""))
        find(u"SelText").Text = text
        find(u"TxtWidth").IsEnabled = bool(trays)
        find(u"TxtHeight").IsEnabled = bool(trays)
        find(u"TxtDiameter").IsEnabled = bool(conduits)
        find(u"ChkWholeRun").IsChecked = core.to_bool(settings.get(u"resize_whole_run", u"1"))
        find(u"ChkFittings").IsChecked = core.to_bool(settings.get(u"resize_fittings", u"1"))
        chosen = 0
        for index, (key, label) in enumerate(core.RESIZE_MODES):
            find(u"CmbMode").Items.Add(label)
            if key == settings.get(u"resize_mode", u"partial"):
                chosen = index
        find(u"CmbMode").SelectedIndex = chosen
        # say exactly how many each choice takes, before anything is resized
        if whole is not None:
            find(u"ChkWholeRun").Content = (
                u"Resize the whole run of each selected row - {0} instead of {1}".format(
                    self.count_text(whole[0], whole[1]), self.count_text(trays, conduits)))
        else:
            find(u"ChkWholeRun").Content = (
                u"Resize the whole run of each selected row (counted when it runs - System "
                u"No is taken from a parameter, so runs are not in the table)")

        find(u"BtnCancel").Click += lambda a, b: w.Close()
        find(u"BtnResize").Click += ui.ui_safe(lambda a, b: self.resize(), u"Resize",
                                               self.show_error)

    @staticmethod
    def count_text(trays, conduits):
        parts = []
        if trays:
            parts.append(u"{0} tray{1}".format(trays, u"" if trays == 1 else u"s"))
        if conduits:
            parts.append(u"{0} conduit{1}".format(conduits, u"" if conduits == 1 else u"s"))
        return u" and ".join(parts) or u"nothing"

    def show_error(self, text):
        self.find(u"ErrorText").Text = text

    def resize(self):
        find = self.find
        values = {}
        for key, box in ((u"width", u"TxtWidth"), (u"height", u"TxtHeight"),
                         (u"diameter", u"TxtDiameter")):
            value, error = core.parse_mm(find(box).Text if find(box).IsEnabled else u"")
            if error:
                self.show_error(u"{0}: {1}.".format(key.capitalize(), error))
                return
            values[key] = value
        if values[u"width"] is None and values[u"height"] is None and values[u"diameter"] is None:
            self.show_error(u"Enter at least one size.")
            return
        values[u"whole_run"] = bool(find(u"ChkWholeRun").IsChecked)
        index = find(u"CmbMode").SelectedIndex
        values[u"mode"] = core.RESIZE_MODES[index][0] if index >= 0 else u"partial"
        self.settings[u"resize_whole_run"] = core.from_bool(values[u"whole_run"])
        self.settings[u"resize_mode"] = values[u"mode"]
        values[u"fittings"] = bool(find(u"ChkFittings").IsChecked)
        self.settings[u"resize_fittings"] = core.from_bool(values[u"fittings"])
        core.save_settings(self.settings)
        self.answer = values
        self.window.Close()

    def show(self):
        self.window.ShowDialog()
        return self.answer
