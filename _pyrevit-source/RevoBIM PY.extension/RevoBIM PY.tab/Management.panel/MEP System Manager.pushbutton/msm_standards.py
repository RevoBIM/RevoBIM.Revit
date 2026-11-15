# -*- coding: utf-8 -*-
"""The Checks and Standards window, opened from the header chip.

Left: which checks flag a row. Right: for each service, the pipe types it is
allowed to be built from. Modal, themed, nothing saved until Apply.
"""
import msm_clr  # noqa: F401  - assemblies first

from System.Windows import Thickness, Visibility
from System.Windows.Controls import CheckBox

import msm_core as core
import msm_theme as theme
import msm_ui as ui

CHECK_BOXES = ((u"standards", u"ChkStandards"), (u"sizes", u"ChkSizes"),
               (u"open_ends", u"ChkOpenEnds"), (u"mismatch", u"ChkMismatch"),
               (u"no_system", u"ChkNoSystem"))

GROUP_NAMES = {u"system_type": u"System Type", u"classification": u"System Classification",
               u"param": u"the grouping parameter"}
CONT_GROUP_NAMES = {u"system_type": u"the Service Type parameter",
                    u"param": u"the custom service parameter"}


class StandardsDialog(object):
    def __init__(self, owner, settings, services, pipe_types):
        self.settings = settings.copy()
        self.domain = getattr(settings, u"domain", u"pipe")
        info = core.domain_info(self.domain)
        self.saved = False
        self.standards = core.decode_standards(settings.get(u"standards"))
        self.services = core.group_order(sorted(set(list(services) +
                                                    list(self.standards.keys()))))
        self.services = [s for s in self.services if s != core.UNASSIGNED]
        self.model_types = list(pipe_types)
        self.current = None
        self.type_boxes = []

        mode = settings.get(u"theme", u"auto")
        self.window = ui.load_window(u"MsmStandards.xaml", mode)
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

        find(u"SubTitle").Text = u"{0} Checks and Standards".format(info[u"tab"])
        labels = core.check_labels(self.domain)
        wording = {u"standards": u"{0} not allowed for its service".format(info[u"type_word"]),
                   u"sizes": u"Size not offered - routing preferences or duct sizes",
                   u"open_ends": u"Open ends - an end joined to nothing",
                   u"mismatch": labels[u"mismatch"],
                   u"no_system": labels[u"no_system"]}
        allowed = core.checks_for(self.domain)
        for name, box in CHECK_BOXES:
            find(box).IsChecked = core.to_bool(settings.get(u"check_" + name, u"1"))
            find(box).Content = wording[name]
            find(box).Visibility = Visibility.Visible if name in allowed else Visibility.Collapsed
        find(u"TypesTitle").Text = u"Allowed {0}s".format(info[u"type_word"].lower())

        names = CONT_GROUP_NAMES if self.domain == u"cont" else GROUP_NAMES
        grouping = names.get(settings.get(u"group_by"), u"System Type")
        find(u"MatchNote").Text = (
            u"Standards are kept against the service names as they are grouped now, "
            u"by {0}. Change the grouping in Settings and a service keeps its standard "
            u"only where its name is the same.".format(grouping))

        combo = find(u"CmbService")
        for service in self.services:
            combo.Items.Add(self.service_label(service))
        combo.SelectionChanged += ui.ui_safe(lambda a, b: self.on_service(), u"Service")
        find(u"TxtTypeSearch").TextChanged += ui.ui_safe(
            lambda a, b: self.search_types(), u"Type search")
        find(u"BtnTypesAll").Click += ui.ui_safe(lambda a, b: self.tick_shown(True), u"All")
        find(u"BtnTypesNone").Click += ui.ui_safe(lambda a, b: self.tick_shown(False), u"None")
        find(u"BtnCancel").Click += lambda a, b: w.Close()
        find(u"BtnApply").Click += ui.ui_safe(lambda a, b: self.apply(), u"Apply",
                                              self.set_status)

        if self.services:
            combo.SelectedIndex = 0
        else:
            combo.IsEnabled = False
            self.set_status(u"No services in the model yet - nothing to set a standard for.")

    # ---------------- helpers ----------------

    def set_status(self, text):
        try:
            self.find(u"StatusText").Text = text
        except Exception:
            pass

    def service_label(self, service):
        count = len(self.standards.get(service) or [])
        if not count:
            return u"{0}   (no standard)".format(service)
        return u"{0}   ({1} allowed)".format(service, count)

    def relabel(self, index):
        combo = self.find(u"CmbService")
        try:
            keep = combo.SelectedIndex
            combo.Items[index] = self.service_label(self.services[index])
            combo.SelectedIndex = keep
        except Exception:
            pass

    # ---------------- the type list ----------------

    def keep_current(self):
        """Write the ticks for the service on screen back into the working
        copy. Nothing ticked means no standard, not 'nothing allowed'."""
        if self.current is None:
            return
        ticked = [b.Tag for b in self.type_boxes if b.IsChecked]
        if ticked:
            self.standards[self.current] = ticked
        else:
            self.standards.pop(self.current, None)
        if self.current in self.services:
            self.relabel(self.services.index(self.current))

    def on_service(self):
        index = self.find(u"CmbService").SelectedIndex
        if index < 0 or index >= len(self.services):
            return
        service = self.services[index]
        if service == self.current:
            return
        self.keep_current()
        self.current = service
        allowed = set(core.allowed_types(self.standards, service))
        names = sorted(set(self.model_types) | allowed, key=core.natural_key)
        host = self.find(u"TypeHost")
        host.Children.Clear()
        self.type_boxes = []
        for name in names:
            box = CheckBox()
            box.Content = name if name in self.model_types else \
                u"{0}   (not in this model)".format(name)
            box.Tag = name
            box.Margin = Thickness(0, 3, 0, 3)
            box.IsChecked = name in allowed
            box.Checked += ui.ui_safe(lambda a, b: self.count_types(), u"Type")
            box.Unchecked += ui.ui_safe(lambda a, b: self.count_types(), u"Type")
            host.Children.Add(box)
            self.type_boxes.append(box)
        self.search_types()
        self.count_types()

    def search_types(self):
        text = self.find(u"TxtTypeSearch").Text
        for box in self.type_boxes:
            match = core.keyword_match(box.Tag, text)
            box.Visibility = Visibility.Visible if match else Visibility.Collapsed

    def tick_shown(self, state):
        for box in self.type_boxes:
            if box.Visibility == Visibility.Visible:
                box.IsChecked = state
        self.count_types()

    def count_types(self):
        ticked = len([b for b in self.type_boxes if b.IsChecked])
        self.find(u"TypeCount").Text = (u"none ticked - no standard" if not ticked else
                                        u"{0} of {1} allowed".format(ticked,
                                                                     len(self.type_boxes)))

    # ---------------- apply ----------------

    def apply(self):
        self.keep_current()
        s = self.settings
        for name, box in CHECK_BOXES:
            s[u"check_" + name] = core.from_bool(self.find(box).IsChecked)
        s[u"standards"] = core.encode_standards(self.standards)
        if not core.save_settings(s):
            self.set_status(u"Could not write the settings file - nothing saved.")
            return
        self.saved = True
        self.window.Close()

    def show(self):
        self.window.ShowDialog()
        return self.saved
