# -*- coding: utf-8 -*-
"""First run setup: make this machine able to write a PDF before it tries.

Every setting this asks about is per machine and none of it is in the
model, so a template that works on one desk can fail on the next with
nothing to show for it but "no file appeared". That is what happened on
the first machine this tool was tried on that was not the one it was
built on, and it is what this window exists to stop.

**The default is Revit's own exporter wherever it exists.** 1.9.1 made
the tool pick up a known print driver automatically when it found one,
which is right for a machine already set up for that driver and wrong
for a fresh one: a driver needs its "Driver saves to" folder before a
single file lands, and until then every sheet fails. A driver is now
offered here, with the folder it needs on the same screen, instead of
being chosen quietly on the user's behalf.
"""

import ps_refs  # noqa: F401  - must be first

import os
import shutil

import ps_config
import ps_export
import ps_model
import ps_paths
import ps_ui
import ps_xlsx


REVIT_PDF = u'Revit built-in PDF export'
NO_PARAMETER = u'(this project has none)'
PAPERS = [u'A4 portrait', u'A3 portrait', u'A4 landscape', u'A3 landscape']

# The two logos the register's title band carries:
# slot: (setting, file name in %APPDATA%\RevoBIM, controls prefix, what).
LOGOS = {
    'company': ('reg_logo', u'register_logo', 'SetupRegLogo',
                u'company logo'),
    'client': ('reg_client_logo', u'register_client_logo',
               'SetupRegClientLogo', u'client logo'),
}


def needed(settings):
    """Whether this machine has been through setup."""
    try:
        return not settings.flag('setup_done', False)
    except Exception:
        return False


class SetupWindow(object):
    """Modal. Returns True when settings were saved."""

    def __init__(self, doc, settings, theme_name='dark', owner=None,
                 first_run=True, catalogue=None, focus=None):
        self.doc = doc
        self.focus = focus
        self.logo_paths = {'company': u'', 'client': u''}
        self.settings = settings
        self.theme_name = theme_name
        self.saved = False
        self.sheet_parameters = self._read_parameters(catalogue)
        # The Scale parameter may be the title block's rather than the
        # sheet's, so both are offered for it.
        self.scale_parameters = sorted(
            set(self.sheet_parameters) |
            set(ps_model.title_block_parameter_names(doc)),
            key=lambda one: one.lower())
        self.native = ps_export.native_pdf_available(doc)
        self.printers = ps_export.list_printers()
        self.preferred = ps_export.preferred_printer(self.printers)

        self.window = ps_ui.load_window('ProSheetsSetup.xaml', theme_name)
        self.chrome = ps_ui.Chrome(self.window, on_close=self._skip)
        if owner is not None:
            try:
                self.window.Owner = owner
            except Exception:
                pass

        self.ui = {}
        for name in ('IntroText', 'NativeRadio', 'NativeNote', 'DriverRadio',
                     'DriverNote', 'SetupPreferNative',
                     'SetupPrinterCombo', 'SetupStagingBox',
                     'SetupStagingBrowse', 'SetupStagingFind',
                     'SetupStagingNote',
                     'SetupRootBox', 'SetupRootBrowse', 'FoundText',
                     'SetupSeriesCombo', 'SetupDisciplineCombo',
                     'SetupStatusCombo', 'SetupParamNote',
                     'SetupScaleParamRadio', 'SetupScaleRevitRadio',
                     'SetupScaleCombo',
                     'RegisterSection', 'SetupRegTitle', 'SetupRegLogoBox',
                     'SetupRegLogoBrowse', 'SetupRegLogoClear',
                     'SetupRegLogoPreview', 'SetupRegLogoNote',
                     'SetupRegClientLogoBox', 'SetupRegClientLogoBrowse',
                     'SetupRegClientLogoClear', 'SetupRegClientLogoPreview',
                     'SetupRegClientLogoNote', 'SetupRegSnapshot',
                     'SetupRegLegend', 'SetupRegFooter',
                     'SetupRegPaper', 'RevisionSection', 'SetupRevReopen',
                     'StatusText', 'TestButton', 'SkipButton', 'OkButton'):
            self.ui[name] = ps_ui.find(self.window, name)

        if not first_run:
            ps_ui.set_text(
                self.ui['IntroText'],
                u'Settings kept on this computer, not in the model. '
                u'Changing them here changes what a new template starts '
                u'with; templates already saved keep their own.')

        self._fill()
        self._fill_register()
        self._wire()
        self._say_what_is_here()
        self._mode_changed()
        if self.focus == 'register':
            try:
                self.window.Loaded += self._bring_register_forward
            except Exception:
                pass

    def _bring_register_forward(self, sender=None, args=None):
        """Opened from the register tab: start at the register's section."""
        try:
            self.ui['RegisterSection'].BringIntoView()
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _read_parameters(self, catalogue):
        """Every parameter a sheet in this model actually carries.

        Taken from the window's own catalogue where there is one, so
        the model is not read twice for the same answer, and read here
        only when setup is opened without one.
        """
        pairs = catalogue
        if not pairs:
            try:
                rows = ps_model.read_rows(self.doc, 'sheets')
                pairs = ps_model.parameter_catalogue(self.doc, rows)
            except Exception:
                pairs = []
        names = []
        for pair in pairs or []:
            try:
                name = u'{0}'.format(pair[0])
            except Exception:
                continue
            if name and name not in names:
                names.append(name)
        names.sort(key=lambda one: one.lower())
        return names

    def _fill_parameter_combos(self):
        """Offer the model's parameters, with the saved one selected.

        A saved name this model does not have is still offered rather
        than dropped: the answer to "which parameter is it" should not
        silently become something else because one project has not got
        it.
        """
        missing = []
        for control_name, key, names in (
                ('SetupSeriesCombo', 'param_series', self.sheet_parameters),
                ('SetupDisciplineCombo', 'param_discipline',
                 self.sheet_parameters),
                ('SetupStatusCombo', 'reg_status_param',
                 self.sheet_parameters),
                ('SetupScaleCombo', 'reg_scale_param',
                 self.scale_parameters)):
            wanted = self.settings.text(key, u'')
            offered = [NO_PARAMETER] + list(names)
            if wanted and wanted not in offered:
                offered.insert(1, wanted)
                missing.append(wanted)
            ps_ui.fill_combo(self.ui[control_name], offered,
                             selected=wanted or NO_PARAMETER)
        if missing:
            ps_ui.set_text(
                self.ui['SetupParamNote'],
                u'Not on the sheets in this model: {0}. Left as it is in '
                u'case this is not the project it was meant for - pick '
                u'another, or "{1}", if it is.'
                .format(u', '.join([u'"{0}"'.format(one) for one in missing]),
                        NO_PARAMETER))
        else:
            ps_ui.set_text(self.ui['SetupParamNote'], u'')

    def _chosen_parameter(self, control_name):
        name = ps_ui.combo_text(self.ui[control_name], NO_PARAMETER)
        return u'' if name == NO_PARAMETER else name

    def _fill(self):
        chosen = self.settings.text('default_printer') or u''
        if not chosen:
            chosen = REVIT_PDF if self.native else self.preferred
        ps_ui.fill_combo(self.ui['SetupPrinterCombo'], self.printers,
                         selected=chosen if chosen != REVIT_PDF
                         else (self.preferred or None))

        use_native = bool(self.native) and (not chosen or chosen == REVIT_PDF)
        try:
            self.ui['NativeRadio'].IsChecked = use_native
            self.ui['DriverRadio'].IsChecked = not use_native
            self.ui['NativeRadio'].IsEnabled = bool(self.native)
        except Exception:
            pass
        if not self.native:
            ps_ui.set_text(
                self.ui['NativeNote'],
                u'Not on this Revit. Revit gained its own PDF exporter in '
                u'2022; before that a print driver is the only route.')

        try:
            self.ui['SetupRootBox'].Text = self.settings.text('default_root') \
                or self._suggest_root()
        except Exception:
            pass
        try:
            self.ui['SetupPreferNative'].IsChecked = self.settings.flag(
                'prefer_native_pdf', True)
        except Exception:
            pass
        self._fill_parameter_combos()
        self._recall_staging()

    # ------------------------------------------------------------------
    # the Document Register's form
    # ------------------------------------------------------------------

    def _fill_register(self):
        store = self.settings.store
        try:
            self.ui['SetupRegTitle'].Text = self.settings.text('reg_title')
            self.ui['SetupRegFooter'].Text = self.settings.text('reg_footer')
            self.ui['SetupRegLegend'].Text = u'\n'.join(
                ps_config.get_list(store, 'reg_legend'))
            self.ui['SetupRegSnapshot'].Text = store.get(
                'reg_snapshot', u'') or u''
        except Exception:
            pass
        by_parameter = self.settings.text('reg_scale_mode', u'') != \
            ps_config.SCALE_REVIT
        try:
            self.ui['SetupScaleParamRadio'].IsChecked = by_parameter
            self.ui['SetupScaleRevitRadio'].IsChecked = not by_parameter
        except Exception:
            pass
        paper = self.settings.text('reg_paper', u'') or PAPERS[0]
        ps_ui.fill_combo(self.ui['SetupRegPaper'], PAPERS,
                         selected=paper if paper in PAPERS else PAPERS[0])
        for slot in LOGOS:
            self._show_logo(self.settings.text(LOGOS[slot][0], u''), slot)
        try:
            self.ui['SetupRevReopen'].IsChecked = self.settings.flag(
                'rev_reopen', True)
        except Exception:
            pass

    def _show_logo(self, path, slot='company'):
        """Put a logo in its preview, or say there is none."""
        prefix = LOGOS[slot][2]
        usable = bool(path) and os.path.isfile(path) and \
            ps_xlsx.image_size(path) is not None
        self.logo_paths[slot] = path if usable else u''
        try:
            self.ui[prefix + 'Box'].Text = self.logo_paths[slot]
        except Exception:
            pass
        image = ps_ui.load_bitmap(self.logo_paths[slot]) if usable else None
        try:
            self.ui[prefix + 'Preview'].Source = image
        except Exception:
            pass
        if path and not usable:
            ps_ui.set_text(self.ui[prefix + 'Note'],
                           u'Not found - choose it again')
        else:
            ps_ui.set_text(self.ui[prefix + 'Note'],
                           u'' if usable else u'No logo')

    def _browse_logo(self, sender=None, args=None, slot='company'):
        """Pick a PNG or JPG and keep a copy of it beside the settings.

        A copy, because a logo on a network drive or in somebody's
        Downloads is gone the day the register is next exported, and the
        form would quietly lose its band. Each slot has its own file, so
        choosing the client's never replaces the company's.
        """
        _setting, stem, _prefix, what = LOGOS[slot]
        chosen = _pick_image(u'Choose the {0}'.format(what))
        if not chosen:
            return
        if ps_xlsx.image_size(chosen) is None:
            self._say(u'That is not a PNG or JPG this can read.')
            return
        target = logo_target(ps_config.appdata_root(), stem, chosen)
        try:
            for old in (u'.png', u'.jpg', u'.jpeg'):
                stale = os.path.join(ps_config.appdata_root(), stem + old)
                if os.path.normcase(stale) != os.path.normcase(target) and \
                        os.path.isfile(stale):
                    os.remove(stale)
            if os.path.normcase(chosen) != os.path.normcase(target):
                shutil.copyfile(chosen, target)
        except Exception as err:
            self._say(u'The {0} could not be copied: {1}'.format(what, err))
            return
        self._show_logo(target, slot)
        self._say(u'{0} set. It goes in the register\'s title band.'.format(
            what[:1].upper() + what[1:]))

    def _clear_logo(self, sender=None, args=None, slot='company'):
        self._show_logo(u'', slot)
        self._say(u'No {0} on the register.'.format(LOGOS[slot][3]))

    def _browse_client_logo(self, sender=None, args=None):
        self._browse_logo(sender, args, 'client')

    def _clear_client_logo(self, sender=None, args=None):
        self._clear_logo(sender, args, 'client')

    @staticmethod
    def lines_of(text):
        """A multi-line box as a list, blank lines dropped."""
        return [line.strip() for line in
                u'{0}'.format(text or u'').replace(u'\r', u'').split(u'\n')
                if line.strip()]

    def _suggest_root(self):
        """The folder the model sits in, else Documents."""
        try:
            here = os.path.dirname(self.doc.PathName or u'')
            if here and os.path.isdir(here):
                return here
        except Exception:
            pass
        try:
            return os.path.join(os.path.expanduser('~'), 'Documents')
        except Exception:
            return u''

    def _recall_staging(self):
        printer = ps_ui.combo_text(self.ui['SetupPrinterCombo'])
        try:
            self.ui['SetupStagingBox'].Text = self.settings.text(
                ps_config.staging_key(printer), u'')
        except Exception:
            pass

    def _say_what_is_here(self):
        lines = []
        lines.append(u'Revit\'s own PDF exporter: {0}'.format(
            u'yes' if self.native else u'no, this Revit is older than 2022'))
        lines.append(u'{0} printer(s) installed.'.format(len(self.printers)))
        if self.preferred:
            lines.append(
                u'"{0}" is installed. That is ProSheets\' own instance of '
                u'PDF24, already set not to ask where to save - but like '
                u'any PDF24 it writes to PDF24\'s output folder rather than '
                u'the path Revit asks for, so it still needs "Driver saves '
                u'to" filled in below.'.format(self.preferred))
        ps_ui.set_text(self.ui['FoundText'], u'\n'.join(lines))

    def _wire(self):
        for name, handler in (('OkButton', self._save),
                              ('SkipButton', self._skip),
                              ('TestButton', self._test),
                              ('SetupStagingBrowse', self._browse_staging),
                              ('SetupStagingFind', self._find_staging),
                              ('SetupRootBrowse', self._browse_root),
                              ('SetupRegLogoBrowse', self._browse_logo),
                              ('SetupRegLogoClear', self._clear_logo),
                              ('SetupRegClientLogoBrowse',
                               self._browse_client_logo),
                              ('SetupRegClientLogoClear',
                               self._clear_client_logo)):
            control = self.ui.get(name)
            if control is None:
                continue
            try:
                control.Click += handler
            except Exception:
                continue
        for name in ('NativeRadio', 'DriverRadio'):
            control = self.ui.get(name)
            if control is None:
                continue
            try:
                control.Checked += self._on_mode
            except Exception:
                continue
        combo = self.ui.get('SetupPrinterCombo')
        if combo is not None:
            try:
                combo.SelectionChanged += self._on_printer
            except Exception:
                pass

    # ------------------------------------------------------------------
    def _driver_chosen(self):
        try:
            return bool(self.ui['DriverRadio'].IsChecked)
        except Exception:
            return False

    def _on_mode(self, sender=None, args=None):
        self._mode_changed()

    def _on_printer(self, sender=None, args=None):
        self._recall_staging()
        self._mode_changed()

    def _mode_changed(self):
        driver = self._driver_chosen()
        # The override only means anything while the built-in exporter
        # is the choice; picking a driver is the override.
        try:
            self.ui['SetupPreferNative'].IsEnabled = bool(
                self.native) and not driver
            if driver:
                self.ui['SetupPreferNative'].IsChecked = False
        except Exception:
            pass
        for name in ('SetupPrinterCombo', 'SetupStagingBox',
                     'SetupStagingBrowse', 'SetupStagingFind'):
            control = self.ui.get(name)
            if control is None:
                continue
            try:
                control.IsEnabled = driver
            except Exception:
                continue
        if not driver:
            ps_ui.set_text(self.ui['SetupStagingNote'], u'')
            self._say(u'Revit writes the files itself. Nothing else needed.')
            return

        printer = ps_ui.combo_text(self.ui['SetupPrinterCombo'])
        staging = self._text('SetupStagingBox')
        known = ps_export.known_printer(printer)
        if not staging:
            ps_ui.set_text(
                self.ui['SetupStagingNote'],
                u'Needed, and it has to be the folder the driver itself '
                u'is set to save into - open the driver\'s own preferences '
                u'to find out which that is. Typing where you want the '
                u'PDFs does not work: the tool collects from this folder '
                u'and renames, it cannot move the driver\'s output.')
            self._say(u'"{0}" needs a folder above before it can write '
                      u'anything.'.format(printer or u'That driver'))
        else:
            ps_ui.set_text(
                self.ui['SetupStagingNote'],
                u'Give it a folder of its own. Collecting takes whatever '
                u'new PDF turns up while a run is going, so a folder used '
                u'for other things will pick up somebody else\'s file.')
            if known is None:
                self._say(u'"{0}" must also be set not to ask where to '
                          u'save.'.format(printer))
            else:
                self._say(u'"{0}" is already set not to ask where to save.'
                          .format(printer))

    def _text(self, name):
        try:
            return u'{0}'.format(self.ui[name].Text or u'')
        except Exception:
            return u''

    def _say(self, text):
        ps_ui.set_text(self.ui['StatusText'], text)

    # ------------------------------------------------------------------
    def _browse_root(self, sender=None, args=None):
        chosen = ps_ui.browse_folder(self._text('SetupRootBox'))
        if chosen:
            try:
                self.ui['SetupRootBox'].Text = chosen
            except Exception:
                pass

    def _browse_staging(self, sender=None, args=None):
        chosen = ps_ui.browse_folder(self._text('SetupStagingBox'))
        if chosen:
            try:
                self.ui['SetupStagingBox'].Text = chosen
            except Exception:
                pass
            self._mode_changed()

    def _find_staging(self, sender=None, args=None):
        """Look for where the driver has been writing, and fill it in."""
        self._say(u'Looking for PDFs written in the last few minutes...')
        try:
            found = ps_export.find_recent_pdfs(600)
        except Exception as err:
            self._say(u'The search failed: {0}'.format(err))
            return
        folders = []
        for path in found:
            folder = os.path.dirname(path)
            if folder not in folders:
                folders.append(folder)

        if not folders:
            ps_ui.Prompt(
                title=u'Find the folder',
                headline=u'Nothing has been written recently.',
                message=u'The search looks for PDFs this machine has '
                        u'written in the last ten minutes, so there has to '
                        u'be one to find.',
                detail=u'1.  Open the driver\'s own settings and turn ON '
                       u'automatic saving, with an output folder of its '
                       u'own.\n\n'
                       u'2.  Print anything to that printer once - a '
                       u'Notepad page will do.\n\n'
                       u'3.  Come back and press Find it again.\n\n'
                       u'If the driver is set to ASK where to save, it will '
                       u'never work with this tool. Either turn automatic '
                       u'saving on, or use Revit\'s own exporter, which '
                       u'needs none of this.',
                primary=u'Close', theme_name=self.theme_name,
                owner=self.window).show()
            self._say(u'Nothing found. Print one page to the driver first.')
            return

        if len(folders) == 1:
            try:
                self.ui['SetupStagingBox'].Text = folders[0]
            except Exception:
                pass
            self._mode_changed()
            self._say(u'Found it: {0}'.format(folders[0]))
            return

        # More than one place had a recent PDF, so guessing would be
        # worse than asking. Say which they are and let them pick.
        ps_ui.Prompt(
            title=u'Find the folder',
            headline=u'More than one folder had a recent PDF.',
            message=u'Pick whichever of these is the driver\'s own output '
                    u'folder and type or browse to it. A folder used for '
                    u'anything else is the wrong answer even if the PDF is '
                    u'in it.',
            detail=u'\n'.join(folders[:12]), primary=u'Close',
            theme_name=self.theme_name, owner=self.window).show()
        self._say(u'{0} folders had a recent PDF - pick the driver\'s own.'
                  .format(len(folders)))

    def _test(self, sender=None, args=None):
        """Say what would happen, without writing anything."""
        problems = self.problems()
        if not problems:
            self._say(u'Looks right. Nothing has been written - this only '
                      u'checks the settings.')
            return
        ps_ui.Prompt(
            title=u'Set up this machine',
            headline=u'This would not write a file yet.',
            message=u'Each of these has to be sorted before a run can '
                    u'produce anything.',
            detail=u'\n\n'.join(problems), primary=u'Close',
            theme_name=self.theme_name, owner=self.window).show()

    def problems(self):
        """Everything that would stop a run writing a file, in words."""
        found = []
        if self._driver_chosen():
            printer = ps_ui.combo_text(self.ui['SetupPrinterCombo'])
            if not printer:
                found.append(u'No printer is chosen.')
            if not self._text('SetupStagingBox'):
                found.append(
                    u'"Driver saves to" is empty. A print driver writes to '
                    u'its own output folder, and the tool collects the file '
                    u'from there - with nothing to collect from, every '
                    u'sheet reports "no file appeared". Either fill it in, '
                    u'or use Revit\'s own exporter, which needs no folder.')
        elif not self.native:
            found.append(u'Revit\'s own exporter does not exist before '
                         u'Revit 2022, so a print driver has to be used '
                         u'here.')
        root = self._text('SetupRootBox')
        if root:
            ok, error = ps_paths.writable(root)
            if not ok:
                found.append(u'The export folder cannot be written to: '
                             u'{0}'.format(error))
        return found

    # ------------------------------------------------------------------
    def _save(self, sender=None, args=None):
        printer = u''
        if self._driver_chosen():
            printer = ps_ui.combo_text(self.ui['SetupPrinterCombo'])
            staging = self._text('SetupStagingBox')
            if printer and staging:
                self.settings.set(ps_config.staging_key(printer), staging)
        prefer = True
        try:
            prefer = bool(self.ui['SetupPreferNative'].IsChecked)
        except Exception:
            prefer = True
        # Choosing a driver at all means not preferring the built-in
        # exporter. Saving both would store a setting that the very next
        # template load quietly undoes.
        if printer:
            prefer = False
        self.settings.set('prefer_native_pdf', '1' if prefer else '0')
        self.settings.set('default_printer', printer)
        self.settings.set('default_root', self._text('SetupRootBox'))
        self.settings.set('param_series',
                          self._chosen_parameter('SetupSeriesCombo'))
        self.settings.set('param_discipline',
                          self._chosen_parameter('SetupDisciplineCombo'))
        self.settings.set('reg_title', self._text('SetupRegTitle').strip()
                          or ps_config.SETTINGS_DEFAULTS['reg_title'])
        self.settings.set('reg_footer', self._text('SetupRegFooter').strip())
        self.settings.set('reg_legend', ps_config.put_list(
            self.lines_of(self._text('SetupRegLegend'))))
        self.settings.set('reg_status_param',
                          self._chosen_parameter('SetupStatusCombo'))
        self.settings.set('reg_scale_param',
                          self._chosen_parameter('SetupScaleCombo'))
        try:
            by_revit = bool(self.ui['SetupScaleRevitRadio'].IsChecked)
        except Exception:
            by_revit = False
        self.settings.set('reg_scale_mode', ps_config.SCALE_REVIT
                          if by_revit else ps_config.SCALE_PARAMETER)
        for slot in LOGOS:
            self.settings.set(LOGOS[slot][0], self.logo_paths[slot])
        self.settings.set('reg_snapshot', self._text('SetupRegSnapshot')
                          .strip())
        try:
            self.settings.set('rev_reopen', u'1' if bool(
                self.ui['SetupRevReopen'].IsChecked) else u'0')
        except Exception:
            pass
        self.settings.set('reg_paper', ps_ui.combo_text(
            self.ui['SetupRegPaper'], PAPERS[0]) or PAPERS[0])
        self.settings.set('setup_done', '1')
        self.settings.save()
        self.saved = True
        self._close()

    def _skip(self, sender=None, args=None):
        # Not marked done. Somebody who closes this without answering gets
        # asked again next time, which is the right way round: the cost of
        # asking twice is a click, the cost of not asking is a failed
        # issue.
        self._close()

    def _close(self):
        try:
            self.window.Close()
        except Exception:
            pass

    def show(self):
        try:
            self.window.ShowDialog()
        except Exception:
            pass
        return self.saved


def logo_target(folder, stem, chosen):
    """Where a chosen logo is copied: its slot's own name, its own type."""
    extension = os.path.splitext(u'{0}'.format(chosen))[1].lower()
    return os.path.join(folder, stem + extension)


def _pick_image(title=u'Choose the company logo'):
    """An image file chosen by the user, or an empty string."""
    dialog = None
    try:
        from System.Windows.Forms import DialogResult, OpenFileDialog
        dialog = OpenFileDialog()
        dialog.Title = title
        dialog.Filter = (u'Images (*.png;*.jpg;*.jpeg)|*.png;*.jpg;*.jpeg|'
                         u'All files (*.*)|*.*')
        dialog.Multiselect = False
        if dialog.ShowDialog() == DialogResult.OK:
            return u'{0}'.format(dialog.FileName)
    except Exception:
        pass
    finally:
        if dialog is not None:
            try:
                dialog.Dispose()
            except Exception:
                pass
    return u''


def run(doc, settings, theme_name='dark', owner=None, first_run=True,
        catalogue=None, focus=None):
    """Show the setup window. True when it saved."""
    try:
        return SetupWindow(doc, settings, theme_name, owner, first_run,
                           catalogue, focus).show()
    except Exception:
        return False
