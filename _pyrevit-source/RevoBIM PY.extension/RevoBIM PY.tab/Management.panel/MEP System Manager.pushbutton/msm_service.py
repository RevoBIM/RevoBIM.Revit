# -*- coding: utf-8 -*-
"""The Change service type dialog on the Containment tab. Modal, themed;
it gathers the new name and how far it reaches - the window runs the job."""
import msm_clr  # noqa: F401  - assemblies first

import msm_core as core
import msm_theme as theme
import msm_ui as ui


class ServiceDialog(object):
    """counts: {scope: (trays, conduits)} worked out by the window from the
    table, so the dialog can say exactly what each choice reaches."""

    def __init__(self, owner, settings, services_now, all_services, counts, parameter):
        self.settings = settings.copy()
        self.counts = counts
        self.answer = None
        self.window = ui.load_window(u"MsmService.xaml", settings.get(u"theme", u"auto"))
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

        find(u"SelText").Text = u"Service types now: {0}.".format(
            u", ".join(services_now[:10]) + (u" ..." if len(services_now) > 10 else u"")
            if services_now else u"none")
        self.existing = list(all_services)
        for name in self.existing:
            find(u"CmbExisting").Items.Add(name)
        for _key, label in core.SERVICE_SCOPES:
            find(u"CmbScope").Items.Add(label)
        find(u"CmbScope").SelectedIndex = 1
        find(u"ChkFittings").IsChecked = True
        find(u"WritesText").Text = (
            u"Writes the {0} parameter - the one this tab groups by. A fitting belonging to "
            u"another service marks the edge of a run and is left alone.".format(parameter))
        self.show_count()

        find(u"CmbExisting").SelectionChanged += ui.ui_safe(
            lambda a, b: self.pick_existing(), u"Existing")
        find(u"CmbScope").SelectionChanged += ui.ui_safe(lambda a, b: self.show_count(),
                                                         u"Scope")
        find(u"BtnCancel").Click += lambda a, b: w.Close()
        find(u"BtnChange").Click += ui.ui_safe(lambda a, b: self.change(), u"Change",
                                               self.show_error)

    def scope(self):
        index = self.find(u"CmbScope").SelectedIndex
        if 0 <= index < len(core.SERVICE_SCOPES):
            return core.SERVICE_SCOPES[index][0]
        return u"runs"

    def show_count(self):
        trays, conduits = self.counts.get(self.scope(), (0, 0))
        parts = []
        if trays:
            parts.append(u"{0} tray{1}".format(trays, u"" if trays == 1 else u"s"))
        if conduits:
            parts.append(u"{0} conduit{1}".format(conduits, u"" if conduits == 1 else u"s"))
        self.find(u"ScopeCount").Text = u"Reaches {0}.".format(u" and ".join(parts) or u"nothing")

    def pick_existing(self):
        item = self.find(u"CmbExisting").SelectedItem
        if item is not None:
            self.find(u"TxtService").Text = u"{0}".format(item)

    def show_error(self, text):
        self.find(u"ErrorText").Text = text

    def change(self):
        value = (self.find(u"TxtService").Text or u"").strip()
        if not value:
            self.show_error(u"Type the new service type, or pick one in use.")
            return
        self.answer = {u"value": value, u"scope": self.scope(),
                       u"fittings": bool(self.find(u"ChkFittings").IsChecked)}
        self.window.Close()

    def show(self):
        self.window.ShowDialog()
        return self.answer
