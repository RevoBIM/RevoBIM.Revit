# -*- coding: utf-8 -*-
"""RevoBIM PY - Family Find & Replace : window and wiring.

Modeless, so Revit stays fully navigable while the tool is open. Every read of
and write to the document goes through a single ExternalEvent, which is the
only place the Revit API is in context.
"""

import os
import traceback

import clr

clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('PresentationCore')
clr.AddReference('PresentationFramework')
clr.AddReference('WindowsBase')
clr.AddReference('System.Xaml')
clr.AddReference('System.Xml')
clr.AddReference('mscorlib')

from Autodesk.Revit.UI import ExternalEvent, IExternalEventHandler, TaskDialog
from Autodesk.Revit.UI.Selection import ObjectType

from System import Action, AppDomain
from System.IO import File, MemoryStream
from System.Windows import (
    FontWeights,
    GridLength,
    GridUnitType,
    TextTrimming,
    TextWrapping,
    Thickness,
    Visibility,
)
from System.Windows.Controls import (
    CheckBox,
    ColumnDefinition,
    Grid,
    ListBoxItem,
    Orientation,
    StackPanel,
    TextBlock,
)
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Media.Imaging import BitmapCacheOption, BitmapImage
from System.Windows.Threading import DispatcherPriority

import ffr_core as core
import ffr_drawer

APPDOMAIN_KEY = 'RevoBIM_FamilyFindReplace_Window'

#: Above this many group instances, ask before starting. Taking a group type
#: apart and putting it back is slow, and it is not obvious from the ribbon how
#: many instances one tick is about to touch.
GROUP_PROMPT_THRESHOLD = 5

#: Active view leads and is the default - replacing across a whole project is
#: the wider blast radius of the two, so it is the one you have to ask for.
SCOPE_LABELS = [
    ('Active view', core.SCOPE_VIEW),
    ('Entire project', core.SCOPE_MODEL),
    ('Current selection', core.SCOPE_SELECTION),
]


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------

def read_text(path):
    handle = open(path, 'rb')
    try:
        raw = handle.read()
    finally:
        handle.close()
    try:
        return raw.decode('utf-8')
    except Exception:
        return raw.decode('latin-1')


def load_window(folder, layout_name):
    """Parse the layout, then merge the theme in behind it.

    The layout may only ask for brushes and styles with DynamicResource,
    because the dictionary is not there yet when XamlReader parses it.
    """
    window = XamlReader.Parse(read_text(os.path.join(folder, layout_name)))
    theme = XamlReader.Parse(read_text(os.path.join(folder, 'Theme.xaml')))
    window.Resources.MergedDictionaries.Add(theme)
    return window


def load_icon(path):
    """From bytes, never from a Uri - System.Uri moved assemblies in 2025."""
    try:
        if not os.path.isfile(path):
            return None
        image = BitmapImage()
        image.BeginInit()
        image.StreamSource = MemoryStream(File.ReadAllBytes(path))
        image.CacheOption = BitmapCacheOption.OnLoad
        image.EndInit()
        return image
    except Exception:
        return None


def own_by_revit(window, uiapp):
    try:
        helper = WindowInteropHelper(window)
        helper.Owner = uiapp.MainWindowHandle
    except Exception:
        pass


# ---------------------------------------------------------------------------
# the one place the Revit API is in context
# ---------------------------------------------------------------------------

class JobHandler(IExternalEventHandler):
    """Runs queued closures inside Revit's API context."""

    def __init__(self):
        self.jobs = []
        self.on_error = None
        self.on_finish = None

    def queue(self, job):
        self.jobs.append(job)

    def Execute(self, uiapp):
        while self.jobs:
            job = self.jobs.pop(0)
            try:
                job(uiapp)
            except Exception:
                if self.on_error is not None:
                    try:
                        self.on_error(traceback.format_exc())
                    except Exception:
                        pass
            finally:
                # The window is made hit-test-invisible while a job runs. A job
                # that throws part way through must not leave it that way, or
                # the tool reads as frozen with no way back.
                if self.on_finish is not None:
                    try:
                        self.on_finish()
                    except Exception:
                        pass

    def GetName(self):
        return 'RevoBIM Family Find and Replace'


# ---------------------------------------------------------------------------
# small WPF builders - controls are built in Python rather than data bound,
# which sidesteps the question of whether WPF can see Python attributes
# ---------------------------------------------------------------------------

def make_row(window, text, right_text, tag):
    item = ListBoxItem()
    grid = Grid()
    left = ColumnDefinition()
    left.Width = GridLength(1, GridUnitType.Star)
    right = ColumnDefinition()
    right.Width = GridLength.Auto
    grid.ColumnDefinitions.Add(left)
    grid.ColumnDefinitions.Add(right)

    label = TextBlock()
    label.Text = text
    label.TextTrimming = TextTrimming.CharacterEllipsis
    Grid.SetColumn(label, 0)
    grid.Children.Add(label)

    if right_text:
        note = TextBlock()
        note.Text = right_text
        note.FontSize = 10
        note.Margin = Thickness(8, 0, 0, 0)
        try:
            note.Foreground = window.FindResource('FgMuted')
        except Exception:
            pass
        Grid.SetColumn(note, 1)
        grid.Children.Add(note)

    item.Content = grid
    item.Tag = tag
    return item


def brush(window, key):
    try:
        return window.FindResource(key)
    except Exception:
        return None


def ask(folder, version, headline, body, ok_text='Yes', cancel_text='Cancel',
        owner=None):
    """Themed modal question. Returns True only on a real yes.

    owner is the tool's main window. Given one, the prompt sits over it, and
    shrinking the prompt takes the main window down with it, so neither is
    left standing over Revit.

    Falls back to Revit's own dialog rather than returning a silent no if the
    themed one will not open. A confirm step that answers itself is
    indistinguishable from a button that does nothing, and that has cost this
    extension a release before.
    """
    try:
        window = load_window(folder, 'FamilyFindReplacePrompt.xaml')
        if owner is not None:
            try:
                window.Owner = owner
            except Exception:
                pass
        header = window.FindName('PromptHeaderBar')
        drawer = ffr_drawer.Drawer(window, header, header.Parent,
                                   window.FindName('PromptShrinkBtn'))
        window.FindName('PromptVersion').Text = 'v' + version
        window.FindName('PromptHeadline').Text = headline
        window.FindName('PromptBody').Text = body
        ok_button = window.FindName('PromptOkBtn')
        cancel_button = window.FindName('PromptCancelBtn')
        ok_button.Content = ok_text
        answer = {'value': False}

        def say_yes(sender, args):
            answer['value'] = True
            window.DialogResult = True

        def say_no(sender, args):
            window.DialogResult = False

        ok_button.Click += say_yes
        if cancel_text is None:
            cancel_button.Visibility = Visibility.Collapsed
        else:
            cancel_button.Content = cancel_text
            cancel_button.Click += say_no

        def drag(sender, args):
            if drawer.on_header_down(args):
                return
            try:
                window.DragMove()
            except Exception:
                pass
        header.MouseLeftButtonDown += drag

        window.ShowDialog()
        return bool(answer['value'])
    except Exception:
        pass
    try:
        from Autodesk.Revit.UI import TaskDialog, TaskDialogCommonButtons, \
            TaskDialogResult
        dialog = TaskDialog('RevoBIM Family Find & Replace')
        dialog.MainInstruction = headline
        dialog.MainContent = body
        if cancel_text is None:
            dialog.CommonButtons = TaskDialogCommonButtons.Ok
            dialog.Show()
            return True
        dialog.CommonButtons = (TaskDialogCommonButtons.Yes |
                                TaskDialogCommonButtons.No)
        return dialog.Show() == TaskDialogResult.Yes
    except Exception:
        return False


def tell(folder, version, headline, body, owner=None):
    """Themed modal statement, one button."""
    ask(folder, version, headline, body, ok_text='OK', cancel_text=None,
        owner=owner)


# ---------------------------------------------------------------------------
# the adjust window
# ---------------------------------------------------------------------------

class AdjustWindow(object):

    def __init__(self, parent, folder, version, uiapp, handler, event, ids,
                 drafting=False, about_centre=False):
        self.parent = parent
        self.uiapp = uiapp
        self.handler = handler
        self.event = event
        self.ids = list(ids)
        self.drafting = bool(drafting)
        self.about_centre = bool(drafting and about_centre)
        self.applied_degrees = 0.0
        self.applied_z = 0.0

        self.window = load_window(folder, 'FamilyFindReplaceAdjust.xaml')
        self.window.Owner = parent
        header = self.find('AdjHeaderBar')
        self.drawer = ffr_drawer.Drawer(self.window, header, header.Parent,
                                        self.find('AdjShrinkBtn'))
        icon = load_icon(os.path.join(folder, 'icon.png'))
        if icon is not None:
            self.find('AdjIconImage').Source = icon
        self.find('AdjVersionText').Text = 'v' + version
        if self.drafting:
            # Detail items in a drafting view: no depth to offset into, and
            # each turns about its own centre so it stays on its import's.
            self.find('AdjHeightCard').Visibility = Visibility.Collapsed
            self.find('AdjCountText').Text = core.fmt(
                '{0} detail item(s). Each one turns about its own {1}, so it '
                'stays exactly where its import symbol was.', len(self.ids),
                'centre' if self.about_centre else 'insertion point')
        else:
            self.find('AdjCountText').Text = core.fmt(
                '{0} replacement(s). Each one turns about its own insertion '
                'point, so a bank of devices keeps its setting out.',
                len(self.ids))

        self.find('AdjHeaderBar').MouseLeftButtonDown += self._drag
        self.find('AdjCloseBtn').Click += self._close
        self.find('AdjApplyBtn').Click += self._apply
        self.find('AdjResetBtn').Click += self._reset
        self.find('AdjSelectBtn').Click += self._select
        for name in ('Rot0', 'Rot90', 'Rot180', 'Rot270', 'RotCustom'):
            self.find(name).Checked += self._mode_changed

    def find(self, name):
        return self.window.FindName(name)

    def show(self):
        self.window.Show()

    def _drag(self, sender, args):
        # A double click on a parked bar opens it; anything else drags.
        if self.drawer.on_header_down(args):
            return
        try:
            self.window.DragMove()
        except Exception:
            pass

    def _close(self, sender, args):
        try:
            self.window.Close()
        except Exception:
            pass

    def _mode_changed(self, sender, args):
        try:
            self.find('RotCustomBox').IsEnabled = bool(
                self.find('RotCustom').IsChecked)
        except Exception:
            pass

    def _target_degrees(self):
        for name, value in (('Rot0', 0.0), ('Rot90', 90.0),
                            ('Rot180', 180.0), ('Rot270', 270.0)):
            if self.find(name).IsChecked:
                return value
        try:
            return float(self.find('RotCustomBox').Text.strip() or '0')
        except Exception:
            return None

    def _target_z(self):
        if self.drafting:
            return 0.0
        try:
            return float(self.find('ZOffsetBox').Text.strip() or '0')
        except Exception:
            return None

    def _status(self, text):
        try:
            self.find('AdjStatusText').Text = text
        except Exception:
            pass

    def _reset(self, sender, args):
        self.find('Rot0').IsChecked = True
        self.find('RotCustomBox').Text = '0'
        self.find('ZOffsetBox').Text = '0'
        self._apply(sender, args)

    def _select(self, sender, args):
        def job(uiapp):
            core.select_elements(uiapp.ActiveUIDocument, self.ids)
            self._status(core.fmt('{0} element(s) selected.', len(self.ids)))
        self.handler.queue(job)
        self.event.Raise()

    def _apply(self, sender, args):
        degrees = self._target_degrees()
        offset = self._target_z()
        if degrees is None:
            self._status('The custom angle is not a number.')
            return
        if offset is None:
            self._status('The Z offset is not a number.')
            return

        delta_degrees = degrees - self.applied_degrees
        delta_z = offset - self.applied_z
        if abs(delta_degrees) < 1.0e-9 and abs(delta_z) < 1.0e-9:
            self._status('Already there - nothing to apply.')
            return

        def job(uiapp):
            doc = uiapp.ActiveUIDocument.Document
            moved, problems = core.adjust_elements(
                doc, self.ids, delta_degrees, delta_z, self.about_centre)
            self.applied_degrees = degrees
            self.applied_z = offset
            if problems:
                self._status(core.fmt(
                    '{0} adjusted at {1} degrees, {2}mm. {3} would not move.',
                    moved, degrees, offset, len(problems)))
            else:
                self._status(core.fmt('{0} adjusted - {1} degrees, {2}mm.',
                                      moved, degrees, offset))
        self.handler.queue(job)
        self.event.Raise()


# ---------------------------------------------------------------------------
# the main window
# ---------------------------------------------------------------------------

class MainWindow(object):

    def __init__(self, uiapp, folder, version):
        self.uiapp = uiapp
        self.folder = folder
        self.version = version

        self.handler = JobHandler()
        self.handler.on_error = self._report_exception
        self.handler.on_finish = self.busy_end
        self.event = ExternalEvent.Create(self.handler)

        # Each side has its own index. In a model view both point at the same
        # one; in a drafting view Find lists import symbols and Replace with
        # lists detail items, which are not the same set at all.
        self.indexes = {'Src': {}, 'Tgt': {}}
        self.drafting = False
        self.last_drafting = False
        self.last_by_centre = False
        self._closing = False
        self._view_handler = None
        self.retain_circuits = True
        self.busy = False
        self._last_percent = -1
        self.src_record = None
        self.tgt_record = None
        self.src_infos = {}
        self.src_elec = core.ElecProfile()
        self.src_circuits = 0
        self.src_circuits_partial = False
        self.src_count = 0
        self.probe = None
        self.param_rows = []
        self.elec_state = core.ELEC_NONE
        self.last_new_ids = []
        self.adjust = None
        self._muting = False

        self.window = load_window(folder, 'FamilyFindReplace.xaml')
        header = self.find('HeaderBar')
        # Held where it is while a run is going - the window is not clickable
        # then anyway, and Ctrl+Shift+H must not slide it mid write.
        self.drawer = ffr_drawer.Drawer(self.window, header, header.Parent,
                                        self.find('ShrinkBtn'),
                                        can_toggle=lambda: not self.busy)
        self._wire()
        own_by_revit(self.window, uiapp)

    # -- plumbing ----------------------------------------------------------

    def find(self, name):
        return self.window.FindName(name)

    def _wire(self):
        icon = load_icon(os.path.join(self.folder, 'icon.png'))
        if icon is not None:
            self.find('IconImage').Source = icon
        self.find('VersionText').Text = 'v' + self.version

        self.find('HeaderBar').MouseLeftButtonDown += self._drag
        self.find('CloseBtn').Click += self._close_clicked
        self.window.Closed += self._closed


        self.find('SrcCategoryCombo').SelectionChanged += self._src_category_changed
        self.find('SrcSearchBox').TextChanged += self._src_search_changed
        self.find('SrcFamilyList').SelectionChanged += self._src_family_changed
        self.find('SrcTypeList').SelectionChanged += self._src_type_changed
        self.find('ScopeCombo').SelectionChanged += self._scope_changed

        self.find('TgtCategoryCombo').SelectionChanged += self._tgt_category_changed
        self.find('TgtSearchBox').TextChanged += self._tgt_search_changed
        self.find('TgtFamilyList').SelectionChanged += self._tgt_family_changed
        self.find('TgtTypeList').SelectionChanged += self._tgt_type_changed

        self.find('SrcPickBtn').Click += self._pick_source
        self.find('PickTargetBtn').Click += self._pick_target

        self.find('ParamSearchBox').TextChanged += self._param_search_changed
        self.find('ParamAllBtn').Click += self._param_all
        self.find('ParamNoneBtn').Click += self._param_none
        self.find('ParamSharedBtn').Click += self._param_shared

        self.find('ElecBtn').Click += self._elec_clicked

        self.find('LevelBelowCheck').Checked += self._level_mode_changed
        self.find('LevelBelowCheck').Unchecked += self._level_mode_changed

        self._wire_resize()

        self.find('PreviewBtn').Click += self._preview
        self.find('RunBtn').Click += self._run
        self.find('AdjustBtn').Click += self._reopen_adjust

        self._muting = True
        scope = self.find('ScopeCombo')
        for label, _value in SCOPE_LABELS:
            scope.Items.Add(label)
        scope.SelectedIndex = 0
        self._muting = False

    def _drag(self, sender, args):
        # A double click on a parked bar opens it; anything else drags.
        if self.drawer.on_header_down(args):
            return
        try:
            self.window.DragMove()
        except Exception:
            pass

    def _close_clicked(self, sender, args):
        self.window.Close()

    def _closed(self, sender, args):
        self._closing = True
        self._unhook_views()
        try:
            if self.adjust is not None:
                self.adjust.window.Close()
        except Exception:
            pass
        try:
            AppDomain.CurrentDomain.SetData(APPDOMAIN_KEY, None)
        except Exception:
            pass

    def _report_exception(self, text):
        self.status('Something went wrong - see the report.')
        self.report_clear()
        for line in text.splitlines():
            if line.strip():
                self.report_add('fail', line)

    def post(self, job):
        self.handler.queue(job)
        self.event.Raise()

    # -- progress ----------------------------------------------------------

    def busy_start(self, label):
        """Show the bar and stop the window answering the mouse.

        Pumping the dispatcher to move a progress bar also pumps *input*: it
        pushes a message frame that dispatches real mouse and key messages, so
        the window can be clicked - or closed - part way through a run. Making
        it hit-test-invisible for the duration is what stops that, and every
        handler the keyboard can still reach checks self.busy.
        """
        self.busy = True
        # -1 rather than 0, so the first call at 0% still paints and the bar
        # appears filled-none rather than appearing only once work is done.
        self._last_percent = -1
        try:
            self.find('ProgressTrack').Visibility = Visibility.Visible
            self.window.IsHitTestVisible = False
        except Exception:
            pass
        self.set_progress(0, 1, label)

    def busy_end(self):
        self.busy = False
        try:
            self.find('ProgressTrack').Visibility = Visibility.Collapsed
            self.find('ProgressText').Text = ''
            self.find('ProgressLabel').Text = ''
            self.window.IsHitTestVisible = True
        except Exception:
            pass

    def set_progress(self, done, total, label):
        """Repaint only when the whole percent moves.

        Pumping on every one of several thousand elements costs more than the
        work being measured, and the bar cannot show a fraction of a percent
        anyway.
        """
        if total <= 0:
            return
        percent = int(done * 100 // total)
        if percent > 100:
            percent = 100
        if percent == self._last_percent:
            return
        self._last_percent = percent
        left = total - done
        if left < 0:
            left = 0
        try:
            self.find('ProgressDone').Width = GridLength(
                float(percent), GridUnitType.Star)
            self.find('ProgressLeft').Width = GridLength(
                float(100 - percent), GridUnitType.Star)
            self.find('ProgressText').Text = core.fmt('{0}%', percent)
            # What is left rather than what is done: on a long run the useful
            # question is how much more of it there is.
            if left:
                self.find('ProgressLabel').Text = core.fmt(
                    '{0}%   -   {1} of {2} left   -   {3}',
                    percent, left, total, label or 'working')
            else:
                self.find('ProgressLabel').Text = core.fmt(
                    '{0}%   -   done', percent)
        except Exception:
            pass
        if label:
            self.status(label)
        self.pump()

    def pump(self):
        """Let the window repaint.

        Safe only because ffr_core calls this between transactions, never
        between a Start and a Commit.
        """
        try:
            self.window.Dispatcher.Invoke(
                DispatcherPriority.Render, Action(lambda: None))
        except Exception:
            try:
                self.window.Dispatcher.Invoke(
                    Action(lambda: None), DispatcherPriority.Render)
            except Exception:
                pass

    def show(self):
        self.window.Show()
        self._hook_views()
        self.post(self._job_load_index)

    # -- status and report -------------------------------------------------

    def status(self, text):
        try:
            self.find('StatusText').Text = text
        except Exception:
            pass

    def report_clear(self):
        self.find('ReportList').Items.Clear()
        self.find('ReportSummary').Text = ''

    def report_add(self, kind, text):
        block = TextBlock()
        block.Text = text
        block.TextWrapping = TextWrapping.Wrap
        key = {'ok': 'FgBody', 'warn': 'AccOrange', 'fail': 'AccRed',
               'good': 'AccGreen', 'muted': 'FgMuted'}.get(kind, 'FgBody')
        colour = brush(self.window, key)
        if colour is not None:
            block.Foreground = colour
        self.find('ReportList').Items.Add(block)

    # -- model index -------------------------------------------------------

    def _job_load_index(self, uiapp):
        """Read both lists for the kind of view that is active.

        Run on opening and again whenever the active view changes between a
        drafting view and anything else, because the two modes do not share a
        single list: a pick or a type chosen in one means nothing in the other,
        so both sides are cleared on a switch rather than carried across.
        """
        uidoc = uiapp.ActiveUIDocument
        doc = uidoc.Document
        self.drafting = core.is_drafting_view(uidoc.ActiveView)
        if self.drafting:
            self.indexes = {'Src': core.build_import_index(doc),
                            'Tgt': core.build_detail_index(doc)}
        else:
            shared = core.build_index(doc)
            self.indexes = {'Src': shared, 'Tgt': shared}

        self.src_record = None
        self.tgt_record = None
        self.probe = None
        self.src_count = 0
        self.src_infos = {}
        self.src_elec = core.ElecProfile()
        self.src_circuits = 0

        was_muting = self._muting
        self._muting = True
        single = []
        try:
            for side in ('Src', 'Tgt'):
                combo = self.find(side + 'CategoryCombo')
                combo.Items.Clear()
                self.find(side + 'FamilyList').Items.Clear()
                self.find(side + 'TypeList').Items.Clear()
                names = sorted(self.indexes[side].keys(),
                               key=lambda n: n.lower())
                for name in names:
                    combo.Items.Add(name)
                # One category - Detail Items, say - is chosen for you rather
                # than making you open a list with one thing in it.
                if len(names) == 1:
                    combo.SelectedIndex = 0
                    single.append(side)
        finally:
            self._muting = was_muting
        for side in single:
            self._fill_families(side)

        self.find('TgtInfoText').Text = 'No replacement chosen yet.'
        self.find('SrcCountText').Text = (
            'Choose an import symbol to find.' if self.drafting
            else 'Choose a family to find.')
        self._apply_mode()
        self._rebuild_params()
        self._update_run()

        if self.drafting:
            imports = sum([r.count for families in self.indexes['Src'].values()
                           for records in families.values() for r in records])
            details = sum([len(families) for families
                           in self.indexes['Tgt'].values()])
            self.status(core.fmt(
                'Drafting view: {0} import symbol(s) found in views, {1} '
                'detail item famil(ies) to replace them with.',
                imports, details))
        else:
            self.status(core.fmt(
                '{0} categories read from the model. Choose the family to '
                'find, then the family to replace it with.',
                len(self.indexes['Src'])))

    # -- drafting mode -----------------------------------------------------

    def _apply_mode(self):
        """Set the window up for a drafting view or a model view."""
        drafting = self.drafting
        shown = Visibility.Visible if drafting else Visibility.Collapsed
        hidden = Visibility.Collapsed if drafting else Visibility.Visible
        try:
            self.find('ModeChip').Visibility = shown
            self.find('SrcPickBtn').Content = (
                'Select import symbol in the view' if drafting
                else 'Select family in the model')
            self.find('PickTargetBtn').Content = (
                'Select detail item in the view' if drafting
                else 'Select family in the model')

            # Greyed as a whole: there is nothing to circuit or wire in a
            # drafting view, and a live-looking control would suggest there is.
            card = self.find('ElecCard')
            card.IsEnabled = not drafting
            card.Opacity = 0.45 if drafting else 1.0

            groups = self.find('GroupsCheck')
            groups.IsEnabled = not drafting
            if drafting:
                groups.IsChecked = False
                groups.ToolTip = 'Groups are not handled in drafting views.'
            else:
                groups.ToolTip = None

            self.find('LevelBelowCheck').Visibility = hidden
            self.find('MirrorCheck').Visibility = shown
            self.find('CentreAlignCheck').Visibility = shown
            if drafting:
                self.find('LevelNote').Text = (
                    'Each import symbol becomes a detail item whose insertion '
                    'point sits on the block\'s AutoCAD base point, turned to '
                    'the same rotation - the way a family-for-family swap '
                    'lands. Tick "line up centres" to match middles instead.')
            else:
                self.find('LevelNote').Text = (
                    'A face based family often carries no level, or carries '
                    'its host\'s. Untick to keep the original\'s own level.')
        except Exception:
            pass
        self._refresh_electrical()

    def _hook_views(self):
        """Follow the active view, so the mode follows it too.

        The handler is kept as one object so the same one can be taken off
        again on close - a bound method fetched twice is two different
        delegates, and removing the second would leave the first attached.
        """
        self._view_handler = self._view_activated
        try:
            self.uiapp.ViewActivated += self._view_handler
        except Exception:
            self._view_handler = None

    def _unhook_views(self):
        if self._view_handler is None:
            return
        try:
            self.uiapp.ViewActivated -= self._view_handler
        except Exception:
            pass
        self._view_handler = None

    def _view_activated(self, sender, args):
        if self._closing or self.busy:
            return
        try:
            drafting = core.is_drafting_view(args.CurrentActiveView)
        except Exception:
            return
        if drafting != self.drafting:
            self.status('The view changed - reading the lists again...')
            self.post(self._job_load_index)
            return
        # Same mode, different view: "Active view" now means a different set.
        if self.src_record is not None and \
                self.scope_value() == core.SCOPE_VIEW:
            self._refresh_source()

    # -- source side -------------------------------------------------------

    def _src_category_changed(self, sender, args):
        if self._muting:
            return
        self._fill_families('Src')

    def _src_search_changed(self, sender, args):
        if self._muting:
            return
        self._fill_families('Src')

    def _src_family_changed(self, sender, args):
        if self._muting:
            return
        self._fill_types('Src')

    def _src_type_changed(self, sender, args):
        if self._muting:
            return
        item = self.find('SrcTypeList').SelectedItem
        self.src_record = item.Tag if item is not None else None
        self._refresh_source()

    def _scope_changed(self, sender, args):
        if self._muting:
            return
        self._refresh_source()

    def scope_value(self):
        index = self.find('ScopeCombo').SelectedIndex
        if index < 0 or index >= len(SCOPE_LABELS):
            return core.SCOPE_MODEL
        return SCOPE_LABELS[index][1]

    def scope_label(self):
        index = self.find('ScopeCombo').SelectedIndex
        if index < 0 or index >= len(SCOPE_LABELS):
            return SCOPE_LABELS[0][0]
        return SCOPE_LABELS[index][0]

    # -- target side -------------------------------------------------------

    def _tgt_category_changed(self, sender, args):
        if self._muting:
            return
        self._fill_families('Tgt')

    def _tgt_search_changed(self, sender, args):
        if self._muting:
            return
        self._fill_families('Tgt')

    def _tgt_family_changed(self, sender, args):
        if self._muting:
            return
        self._fill_types('Tgt')

    def _tgt_type_changed(self, sender, args):
        if self._muting:
            return
        item = self.find('TgtTypeList').SelectedItem
        self.tgt_record = item.Tag if item is not None else None
        self._refresh_target()

    # -- list filling ------------------------------------------------------

    def _fill_families(self, side):
        combo = self.find(side + 'CategoryCombo')
        family_list = self.find(side + 'FamilyList')
        type_list = self.find(side + 'TypeList')
        keyword = (self.find(side + 'SearchBox').Text or '').strip().lower()

        was_muting = self._muting
        self._muting = True
        family_list.Items.Clear()
        type_list.Items.Clear()
        self._muting = was_muting

        category = combo.SelectedItem
        if category is None:
            return
        families = self.indexes.get(side, {}).get(category, {})

        shown = 0
        for family_name in sorted(families.keys(), key=lambda n: n.lower()):
            records = families[family_name]
            if keyword:
                hit = keyword in family_name.lower()
                if not hit:
                    hit = any(keyword in r.type_name.lower() for r in records)
                if not hit:
                    continue
            placed = sum(r.count for r in records)
            note = core.fmt('{0} type(s), {1} placed', len(records), placed)
            family_list.Items.Add(make_row(self.window, family_name, note,
                                           family_name))
            shown += 1
        if shown == 1:
            family_list.SelectedIndex = 0

    def _fill_types(self, side):
        combo = self.find(side + 'CategoryCombo')
        family_list = self.find(side + 'FamilyList')
        type_list = self.find(side + 'TypeList')
        keyword = (self.find(side + 'SearchBox').Text or '').strip().lower()

        was_muting = self._muting
        self._muting = True
        type_list.Items.Clear()
        self._muting = was_muting

        category = combo.SelectedItem
        item = family_list.SelectedItem
        if category is None or item is None:
            return
        family_name = item.Tag
        records = self.indexes.get(side, {}).get(category, {}).get(
            family_name, [])

        family_hit = keyword and keyword in family_name.lower()
        for record in records:
            if keyword and not family_hit and keyword not in record.type_name.lower():
                continue
            note = core.fmt('{0} placed', record.count)
            type_list.Items.Add(make_row(self.window, record.type_name,
                                         note, record))
        if type_list.Items.Count == 1:
            type_list.SelectedIndex = 0

    def _select_in_lists(self, side, record):
        """Drive the three lists from a type picked in the model.

        Kept muted throughout so the selection changes do not each kick off
        their own read of the document.
        """
        was_muting = self._muting
        self._muting = True
        try:
            combo = self.find(side + 'CategoryCombo')
            self.find(side + 'SearchBox').Text = ''
            for i in range(combo.Items.Count):
                if combo.Items[i] == record.category_name:
                    combo.SelectedIndex = i
                    break
            self._fill_families(side)

            family_list = self.find(side + 'FamilyList')
            for i in range(family_list.Items.Count):
                if family_list.Items[i].Tag == record.family_name:
                    family_list.SelectedIndex = i
                    break
            self._fill_types(side)

            type_list = self.find(side + 'TypeList')
            for i in range(type_list.Items.Count):
                tag = type_list.Items[i].Tag
                if core.eid_value(tag.symbol_id) == \
                        core.eid_value(record.symbol_id):
                    type_list.SelectedIndex = i
                    break
        finally:
            self._muting = was_muting

    # -- picking -----------------------------------------------------------

    def _read_symbol(self, doc, reference, count=0):
        """The type record behind a picked element."""
        element = doc.GetElement(reference.ElementId)
        if element is None:
            return None
        if isinstance(element, core.ImportInstance):
            return core.import_record(doc, element, count)
        symbol = doc.GetElement(element.GetTypeId())
        if symbol is None:
            return None
        try:
            category = symbol.Category.Name
        except Exception:
            category = ''
        return core.TypeRecord(
            symbol.Id, core.elem_name(symbol), core.elem_name(symbol.Family),
            category, core.placement_name(symbol), count)

    def _pick_source(self, sender, args):
        """Click one element in the model to set the family to find.

        A single PickObject, so one click completes the step - no Finish, no
        Enter. What it sets is the family and type, not that one element; the
        scope decides how many instances of it get replaced.
        """
        def job(uiapp):
            uidoc = uiapp.ActiveUIDocument
            if self.drafting:
                pick_filter = core.ImportPickFilter()
                prompt = 'Click the import symbol you want to REPLACE'
            else:
                pick_filter = core.FamilyInstancePickFilter()
                prompt = 'Click the element whose family you want to REPLACE'
            self.status(prompt[0] + prompt[1:].lower() + '.')
            try:
                reference = uidoc.Selection.PickObject(
                    ObjectType.Element, pick_filter, prompt)
            except Exception:
                self.status('Picking abandoned - nothing changed.')
                return
            record = self._read_symbol(uidoc.Document, reference)
            if record is None:
                self.status('That element has no family type to read.')
                return
            self.src_record = record
            self._select_in_lists('Src', record)
            self.status(core.fmt('Finding {0}. Now choose what to replace it '
                                 'with.', record.label))
            self._refresh_source()
        self.post(job)

    def _pick_target(self, sender, args):
        """Click one element in the model to set the replacement family."""
        def job(uiapp):
            uidoc = uiapp.ActiveUIDocument
            if self.drafting:
                pick_filter = core.DetailItemPickFilter()
                prompt = 'Click a detail item to replace them WITH'
            else:
                pick_filter = core.FamilyInstancePickFilter()
                prompt = 'Click an element of the family to replace it WITH'
            self.status(prompt[0] + prompt[1:].lower() + '.')
            try:
                reference = uidoc.Selection.PickObject(
                    ObjectType.Element, pick_filter, prompt)
            except Exception:
                self.status('Picking abandoned - nothing changed.')
                return
            record = self._read_symbol(uidoc.Document, reference)
            if record is None:
                self.status('That element has no family type to read.')
                return
            if self.src_record is not None and \
                    core.eid_value(record.symbol_id) == \
                    core.eid_value(self.src_record.symbol_id):
                self.status('That is the same type as the one being found.')
                return
            self.tgt_record = record
            self._select_in_lists('Tgt', record)
            self._refresh_target()
        self.post(job)

    # -- refresh -----------------------------------------------------------

    def _refresh_source(self):
        def job(uiapp):
            uidoc = uiapp.ActiveUIDocument
            doc = uidoc.Document
            core.reset_run_caches()
            instances = self._source_instances(doc, uidoc)
            self.src_count = len(instances)
            self.src_infos = {}
            self.src_elec = core.ElecProfile()
            self.src_circuits = 0
            # circuits are only counted over the first few hundred so driving
            # the window stays responsive - the run itself handles every one
            self.src_circuits_partial = len(instances) > core.CIRCUIT_SCAN_CAP
            for instance in instances[:core.CIRCUIT_SCAN_CAP]:
                if not self.src_infos:
                    self.src_infos = core.read_param_infos(instance)
                    if not self.drafting:
                        self.src_elec = core.electrical_profile(instance)
                if self.drafting:
                    break
                if core.electrical_systems(instance):
                    self.src_circuits += 1
            label = self.src_record.label if self.src_record else 'nothing'
            scope_label = self.scope_label()
            self.find('SrcCountText').Text = core.fmt(
                '{0} {1} of {2} in {3}.', self.src_count,
                'import symbol(s)' if self.drafting else 'instance(s)',
                label, scope_label.lower())
            self._rebuild_params()
            self._refresh_electrical()
            self._update_run()
        self.post(job)

    def _source_instances(self, doc, uidoc):
        """Every instance of the source type inside the chosen scope.

        Both modes land here. Browse picks the type from the lists, manual
        picks it by clicking one element in the model, and from that point on
        they behave identically - the scope decides how many get replaced.
        """
        if self.src_record is None:
            return []
        if self.drafting:
            return core.collect_imports(doc, uidoc, self.src_record.symbol_id,
                                        self.scope_value())
        return core.collect_instances(doc, uidoc, self.src_record.symbol_id,
                                      self.scope_value())

    def _refresh_target(self):
        if self.tgt_record is None:
            return
        record = self.tgt_record
        self.find('TgtInfoText').Text = core.fmt(
            'Reading {0}...', record.label)

        def job(uiapp):
            uidoc = uiapp.ActiveUIDocument
            # The active view goes in too: a detail item can only be
            # test-placed in a view.
            self.probe = core.probe_symbol(uidoc.Document, record.symbol_id,
                                           uidoc.ActiveView)
            self.find('TgtInfoText').Text = core.fmt(
                '{0}\nPlacement: {1}. {2}', record.label,
                self.probe.placement, self.probe.note)
            self._rebuild_params()
            self._refresh_electrical()
            self._update_run()
        self.post(job)

    # -- parameters --------------------------------------------------------

    def _rebuild_params(self):
        target_infos = self.probe.param_infos if self.probe is not None else None
        if not self.src_infos:
            self.param_rows = []
        else:
            existing = {}
            for row in self.param_rows:
                existing[row.name] = row.checked
            self.param_rows = core.build_param_rows(self.src_infos, target_infos)
            for row in self.param_rows:
                if row.name in existing and row.on_target:
                    row.checked = existing[row.name]
        self._fill_param_list()

    def _fill_param_list(self):
        keyword = (self.find('ParamSearchBox').Text or '').strip().lower()
        listbox = self.find('ParamList')
        listbox.Items.Clear()
        muted = brush(self.window, 'FgMuted')
        red = brush(self.window, 'AccRed')
        blue = brush(self.window, 'AccBlue')

        shown = 0
        for row in self.param_rows:
            if keyword and keyword not in row.name.lower():
                continue
            check = CheckBox()
            check.IsChecked = row.checked
            check.IsEnabled = row.on_target
            check.Tag = row
            check.Checked += self._param_toggled
            check.Unchecked += self._param_toggled

            panel = StackPanel()
            panel.Orientation = Orientation.Vertical

            title = TextBlock()
            title.Text = row.name
            if row.is_shared and blue is not None:
                title.Foreground = blue
            panel.Children.Add(title)

            subtitle = TextBlock()
            bits = [row.storage.replace('StorageType.', '')]
            if row.sample:
                sample = row.sample
                if len(sample) > 42:
                    sample = sample[:39] + '...'
                bits.append(sample)
            if row.note:
                bits.append(row.note)
            subtitle.Text = '  -  '.join(bits)
            subtitle.FontSize = 10
            tone = red if row.note else muted
            if tone is not None:
                subtitle.Foreground = tone
            panel.Children.Add(subtitle)

            check.Content = panel
            listbox.Items.Add(check)
            shown += 1

        ticked = len([r for r in self.param_rows if r.checked and r.on_target])
        self.find('ParamCountText').Text = core.fmt(
            '{0} ticked of {1} shown', ticked, shown)

    def _param_toggled(self, sender, args):
        row = sender.Tag
        if row is not None:
            row.checked = bool(sender.IsChecked)
        ticked = len([r for r in self.param_rows if r.checked and r.on_target])
        self.find('ParamCountText').Text = core.fmt(
            '{0} ticked of {1} shown', ticked, self.find('ParamList').Items.Count)

    def _param_search_changed(self, sender, args):
        self._fill_param_list()

    def _param_all(self, sender, args):
        for row in self.param_rows:
            row.checked = row.on_target
        self._fill_param_list()

    def _param_none(self, sender, args):
        for row in self.param_rows:
            row.checked = False
        self._fill_param_list()

    def _param_shared(self, sender, args):
        for row in self.param_rows:
            row.checked = row.on_target and row.is_shared
        self._fill_param_list()

    def retained_names(self):
        return [r.name for r in self.param_rows if r.checked and r.on_target]

    # -- electrical --------------------------------------------------------

    def _refresh_electrical(self):
        """Paint the circuits chip.

        The chip is a toggle, not a verdict: On means carry the circuits
        across, Off means do not. Solid green for On, solid red for Off,
        because Off on a circuited selection is the destructive setting and
        should not look like the safe one. Whether the two families actually
        agree goes in the line underneath, where it can be read without
        turning the chip into a second control.
        """
        button = self.find('ElecBtn')
        detail = self.find('ElecDetail')
        count_text = self.find('ElecCircuitCount')

        if self.drafting:
            button.Content = 'Circuits retained? : n/a'
            self._paint_solid(button, 'BgHover')
            muted = brush(self.window, 'FgMuted')
            if muted is not None:
                button.Foreground = muted
            detail.Text = ('Not used in a drafting view - import symbols and '
                           'detail items carry no circuits or wires.')
            self._paint_text(detail, 'FgMuted')
            count_text.Text = ''
            self.elec_state = core.ELEC_NONE
            return

        on = bool(self.retain_circuits)
        button.Content = 'Circuits retained? : ' + ('On' if on else 'Off')
        if on:
            self._paint_solid(button, 'AccGreen')
        else:
            self._paint_solid(button, 'AccRed')

        if self.probe is None or not self.src_infos:
            detail.Text = 'Choose both families to check the circuits.'
            self._paint_text(detail, 'FgMuted')
            count_text.Text = ''
            self.elec_state = core.ELEC_NONE
            return

        state, headline, lines = core.compare_electrical(
            self.src_elec, self.probe.elec, self.src_circuits)
        self.elec_state = state
        count_text.Text = core.fmt(
            '{0}{1} circuited', self.src_circuits,
            '+' if self.src_circuits_partial else '')

        if not on:
            if self.src_circuits:
                detail.Text = core.fmt(
                    '{0} circuit(s) on the originals will be lost when they '
                    'are deleted. Turn this back on to carry them across.',
                    self.src_circuits)
                self._paint_text(detail, 'AccRed')
            else:
                detail.Text = 'Nothing on the selection is circuited.'
                self._paint_text(detail, 'FgMuted')
            return

        if state == core.ELEC_RETAIN:
            detail.Text = ' '.join(lines)
            self._paint_text(detail, 'FgMuted')
        elif state == core.ELEC_NONE:
            detail.Text = ' '.join(lines)
            self._paint_text(detail, 'FgMuted')
        else:
            # On, but the two families disagree. The chip stays green because
            # the setting really is on; the warning belongs here.
            detail.Text = core.fmt(
                '{0}. {1} Circuited elements will be left alone rather than '
                'swapped, so no circuit is destroyed.',
                headline, ' '.join(lines))
            self._paint_text(detail, 'AccRed')

    def _paint_solid(self, button, key):
        """Fill the chip, not just outline it - On and Off both read at a glance."""
        value = brush(self.window, key)
        if value is not None:
            button.Background = value
            button.BorderBrush = value
        white = brush(self.window, 'FgOnAccent')
        button.Foreground = white if white is not None else button.Foreground
        button.FontWeight = FontWeights.SemiBold

    def _paint_text(self, block, key):
        value = brush(self.window, key)
        if value is not None:
            block.Foreground = value

    def _elec_clicked(self, sender, args):
        """The chip is the toggle."""
        if self.drafting:
            return
        self.retain_circuits = not self.retain_circuits
        self._refresh_electrical()
        self._update_run()
        self.status('Circuits will {0} be carried across.'.format(
            'now' if self.retain_circuits else 'NOT'))

    def _wire_resize(self):
        """Drag any edge or corner to resize.

        A window with WindowStyle=None and AllowsTransparency=True gets no
        usable resize border from WPF - the grab region is a couple of
        transparent pixels with no cursor. Eight thumbs over the edges do the
        job explicitly, and they work the same on every release.
        """
        # Named in full rather than built from a prefix, so the bench check
        # can still match every FindName to an x:Name in the layout.
        grips = (('GripNW', 'NW'), ('GripN', 'N'), ('GripNE', 'NE'),
                 ('GripW', 'W'), ('GripE', 'E'),
                 ('GripSW', 'SW'), ('GripS', 'S'), ('GripSE', 'SE'))
        for name, edge in grips:
            thumb = self.find(name)
            if thumb is None:
                continue
            thumb.DragDelta += self._make_resizer(edge)

    def _make_resizer(self, edge):
        def handler(sender, args):
            try:
                self._resize(edge, args.HorizontalChange, args.VerticalChange)
            except Exception:
                pass
        return handler

    def _resize(self, edge, dx, dy):
        # The grips are hidden while parked; this is the belt to those braces.
        if not self.drawer.is_open:
            return
        window = self.window
        min_w = window.MinWidth or 400
        min_h = window.MinHeight or 300
        width = window.ActualWidth
        height = window.ActualHeight

        if 'E' in edge:
            window.Width = max(min_w, width + dx)
        if 'W' in edge:
            # Dragging the west edge has to move the window left as it widens,
            # or the right edge walks across the screen. Clamp first, then take
            # the movement actually allowed, so the window does not drift once
            # it has hit its minimum.
            wanted = max(min_w, width - dx)
            window.Left = window.Left + (width - wanted)
            window.Width = wanted
        if 'S' in edge:
            window.Height = max(min_h, height + dy)
        if 'N' in edge:
            wanted = max(min_h, height - dy)
            window.Top = window.Top + (height - wanted)
            window.Height = wanted

    def _level_mode_changed(self, sender, args):
        if self._muting:
            return
        if bool(self.find('LevelBelowCheck').IsChecked):
            self.find('LevelNote').Text = (
                'A face based family hosted to a face often carries no level, '
                'or carries its host\'s - a light on Level 1\'s ceiling reports '
                'Level 2. Each replacement is associated with the nearest level '
                'at or below its own insertion point instead.')
        else:
            self.find('LevelNote').Text = (
                'Each replacement keeps whatever level its original was '
                'associated with, falling back to the nearest level below where '
                'the original has none. Use this where a family is deliberately '
                'dimensioned down from the level above on a negative offset.')
        self.status('Level rule changed. Preview to see which levels apply.')

    # -- run ---------------------------------------------------------------

    def _update_run(self):
        ready = self.src_count > 0 and self.tgt_record is not None
        self.find('RunBtn').IsEnabled = bool(ready)
        self.find('PreviewBtn').IsEnabled = bool(
            self.src_count > 0 and self.tgt_record is not None)
        self.find('AdjustBtn').IsEnabled = bool(self.last_new_ids)

    def _preview(self, sender, args):
        def job(uiapp):
            uidoc = uiapp.ActiveUIDocument
            doc = uidoc.Document
            core.reset_run_caches()
            instances = self._source_instances(doc, uidoc)
            self.report_clear()
            if self.drafting:
                self._preview_drafting(doc, instances)
                return
            source_label = (self.src_record.label if self.src_record
                            else 'the picked type')
            self.report_add('ok', core.fmt(
                '{0} element(s) of {1}', len(instances), source_label))
            self.report_add('ok', core.fmt(
                'become {0} ({1})', self.tgt_record.label,
                self.probe.placement if self.probe else 'unknown placement'))

            grouped = 0
            line_based = 0
            circuited = 0
            tagged = 0
            wire_ends = 0
            want_tags = bool(self.find('TagsCheck').IsChecked)
            want_wires = bool(self.find('WiresCheck').IsChecked)
            level_below = bool(self.find('LevelBelowCheck').IsChecked)
            levels = {}
            total = len(instances)
            self.busy_start('Checking...')
            seen = 0
            for instance in instances:
                seen += 1
                self.set_progress(seen, total,
                                  core.fmt('Checking {0} of {1}', seen, total))
                try:
                    if instance.GroupId is not None and \
                            core.eid_value(instance.GroupId) > 0:
                        grouped += 1
                        continue
                except Exception:
                    pass
                point = core.instance_point(instance)
                if point is None:
                    line_based += 1
                else:
                    level = core.resolve_level(doc, instance, point, level_below)
                    name = core.elem_name(level) if level is not None \
                        else 'no level found'
                    levels[name] = levels.get(name, 0) + 1
                if core.electrical_systems(instance):
                    circuited += 1
                tagged += len(core.tags_on(doc, instance))
                wire_ends += len(core.wire_links(doc, instance))

            if tagged:
                if want_tags:
                    self.report_add('good', core.fmt(
                        '{0} tag(s) will be moved onto the replacements.',
                        tagged))
                else:
                    self.report_add('warn', core.fmt(
                        '{0} tag(s) will be deleted with the originals - '
                        'retain tags is off.', tagged))
            if wire_ends:
                if want_wires:
                    self.report_add('good', core.fmt(
                        '{0} wire end(s) will be reconnected to the '
                        'replacements.', wire_ends))
                else:
                    self.report_add('warn', core.fmt(
                        '{0} wire end(s) will be left dangling - reconnect '
                        'wires is off.', wire_ends))

            names = self.retained_names()
            if levels:
                pairs = sorted(levels.items(), key=lambda item: -item[1])
                summary = ', '.join([core.fmt('{0} ({1})', name, count)
                                     for name, count in pairs])
                self.report_add('muted', core.fmt(
                    'Level {0}: {1}',
                    'below the insertion point' if level_below
                    else 'kept from the original', summary))
            self.report_add('muted', core.fmt(
                '{0} parameter(s) kept: {1}', len(names),
                ', '.join(names) if names else 'none'))
            if circuited and not self.retain_circuits:
                self.report_add('fail', core.fmt(
                    '{0} circuited element(s) - circuits retained is off, so '
                    'those circuits will be lost.', circuited))
            elif circuited:
                if self.elec_state == core.ELEC_RETAIN:
                    self.report_add('good', core.fmt(
                        '{0} circuited element(s) - each replacement joins the '
                        'circuit before the original is deleted.', circuited))
                else:
                    self.report_add('warn', core.fmt(
                        '{0} circuited element(s) - the two families disagree, '
                        'so those elements will be left alone rather than '
                        'swapped. No circuit is destroyed.', circuited))
            if grouped and bool(self.find('GroupsCheck').IsChecked):
                core.reset_run_caches()
                _loose, work = core.survey_groups(
                    doc, instances, core.eid_value(self.src_record.symbol_id))
                total = core.count_group_instances(work)
                self.report_add('warn', core.fmt(
                    '{0} element(s) are inside {1} group type(s). Every one of '
                    'the {2} instance(s) of those types will change, project '
                    'wide, whatever the scope says.',
                    grouped, len(work), total))
            elif grouped:
                self.report_add('warn', core.fmt(
                    '{0} element(s) sit inside a group and will be left alone.',
                    grouped))
            if line_based:
                self.report_add('warn', core.fmt(
                    '{0} element(s) are line based rather than point based and '
                    'will be left alone.', line_based))
            self.busy_end()
            self.find('ReportSummary').Text = 'preview - nothing written'
            self.status('Preview only - nothing has been changed.')
        self.post(job)

    def _preview_drafting(self, doc, instances):
        """What a drafting-view run will do, read without writing anything."""
        total = len(instances)
        views = {}
        routes = {}
        rotated = 0
        mirrored = 0
        grouped = 0
        no_view = 0
        tagged = 0
        want_mirror = bool(self.find('MirrorCheck').IsChecked)
        want_tags = bool(self.find('TagsCheck').IsChecked)
        by_centre = bool(self.find('CentreAlignCheck').IsChecked)
        self.busy_start('Checking...')
        try:
            seen = 0
            for instance in instances:
                seen += 1
                self.set_progress(seen, total, core.fmt(
                    'Checking {0} of {1}', seen, total))
                try:
                    if instance.GroupId is not None and \
                            core.eid_value(instance.GroupId) > 0:
                        grouped += 1
                        continue
                except Exception:
                    pass
                view = core.owner_view(doc, instance)
                if view is None:
                    no_view += 1
                    continue
                views[core.eid_value(view.Id)] = core.elem_name(view)
                # Measuring turns the symbol square for a moment, so it needs a
                # transaction - always rolled back, and closed again before the
                # next repaint of the progress bar.
                frame = None
                reading = core.Transaction(doc, 'RevoBIM read import symbol')
                try:
                    reading.Start()
                    frame = core.read_import_frame(doc, instance, view,
                                                   by_centre)
                finally:
                    try:
                        if reading.HasStarted():
                            reading.RollBack()
                    except Exception:
                        pass
                if frame is None:
                    continue
                route = (frame.route if by_centre else frame.origin_route) \
                    or 'not found'
                routes[route] = routes.get(route, 0) + 1
                if abs(frame.angle) > 1.0e-6:
                    rotated += 1
                if frame.mirrored:
                    mirrored += 1
                tagged += len(core.tags_on(doc, instance))
        finally:
            self.busy_end()

        self.report_add('ok', core.fmt(
            '{0} import symbol(s) of {1}', total,
            self.src_record.label if self.src_record else 'the picked symbol'))
        self.report_add('ok', core.fmt(
            'become {0}, lined up {1}', self.tgt_record.label,
            'middle to middle' if by_centre
            else 'insertion point to insertion point'))
        self._report_views(views)
        if rotated:
            self.report_add('good', core.fmt(
                '{0} are rotated in the drawing - each detail item is turned '
                'to match.', rotated))
        if mirrored:
            if want_mirror:
                self.report_add('good', core.fmt(
                    '{0} are mirrored - each detail item is mirrored to '
                    'match.', mirrored))
            else:
                self.report_add('warn', core.fmt(
                    '{0} are mirrored and will NOT be matched - mirror to '
                    'match is off.', mirrored))
        self._report_centre_routes(routes, by_centre)
        if tagged:
            self.report_add('good' if want_tags else 'warn', core.fmt(
                '{0} tag(s) will be {1}.', tagged,
                'moved onto the detail items' if want_tags
                else 'deleted with the imports - retain tags is off'))
        names = self.retained_names()
        self.report_add('muted', core.fmt(
            '{0} parameter(s) kept: {1}', len(names),
            ', '.join(names) if names else 'none'))
        if grouped:
            self.report_add('warn', core.fmt(
                '{0} import symbol(s) sit inside a detail group and will be '
                'left alone.', grouped))
        if no_view:
            self.report_add('warn', core.fmt(
                '{0} import(s) are not drawn in a view and will be left '
                'alone - a detail item needs a view to go in.', no_view))
        self.find('ReportSummary').Text = 'preview - nothing written'
        self.status('Preview only - nothing has been changed.')

    def _report_views(self, views):
        if not views:
            return
        names = sorted(views.values(), key=lambda n: n.lower())
        shown = ', '.join(names[:5])
        if len(names) > 5:
            shown = core.fmt('{0} and {1} more', shown, len(names) - 5)
        self.report_add('muted', core.fmt('In {0} view(s): {1}',
                                          len(names), shown))

    def _report_centre_routes(self, routes, by_centre=False):
        """How each point was found, and a warning where it was a guess."""
        if not routes:
            return
        pairs = sorted(routes.items(), key=lambda item: -item[1])
        self.report_add('muted', core.fmt(
            '{0}: {1}',
            'Centre measured from' if by_centre
            else 'Insertion point and rotation read from',
            ', '.join([core.fmt('{0} ({1})', name, count)
                       for name, count in pairs])))
        if not by_centre:
            missing = routes.get('not found', 0)
            if missing:
                self.report_add('warn', core.fmt(
                    '{0} symbol(s) gave no placement to read and will be left '
                    'alone.', missing))
            return
        fallback = routes.get('insertion point', 0)
        if fallback:
            self.report_add('warn', core.fmt(
                '{0} symbol(s) had no linework to measure, so their detail '
                'items land on the AutoCAD base point rather than the '
                'middle.', fallback))

    def _report_drafting(self, report):
        self._report_views(report.views)
        if report.rotated:
            self.report_add('good', core.fmt(
                '{0} detail item(s) turned to match the symbol\'s rotation.',
                report.rotated))
        if report.mirrored:
            self.report_add('good', core.fmt(
                '{0} detail item(s) mirrored to match blocks mirrored in '
                'AutoCAD.', report.mirrored))
        if report.mirror_failed:
            self.report_add('warn', core.fmt(
                '{0} mirrored symbol(s) were placed unmirrored - the detail '
                'item would not mirror.', report.mirror_failed))
        if report.centre_shifted:
            self.report_add('muted', core.fmt(
                '{0} detail item(s) are drawn off their own origin, so each '
                'was moved until its middle sat on the symbol\'s middle.',
                report.centre_shifted))
        if report.centre_corrected:
            self.report_add('muted', core.fmt(
                '{0} needed a second move after being checked, and were '
                'checked again.', report.centre_corrected))
        if report.rotation_corrected:
            self.report_add('muted', core.fmt(
                '{0} needed a further turn after being checked.',
                report.rotation_corrected))
        point = 'centre' if report.by_centre else 'insertion point'
        if report.centre_unverified:
            self.report_add('warn', core.fmt(
                '{0} detail item(s) could not be confirmed on their symbol\'s '
                '{1} - each is named below. The debug log has the numbers.',
                report.centre_unverified, point))
        else:
            replaced = sum(report.centre_routes.values())
            if replaced:
                self.report_add('good', core.fmt(
                    'All {0} checked after placing: each sits within 0.5mm of '
                    'its symbol\'s {1}{2}.', replaced, point,
                    '' if report.by_centre else ', at its rotation'))
        self._report_centre_routes(report.centre_routes, report.by_centre)
        path = core.debug_path()
        if path:
            self.report_add('muted', core.fmt('Debug log: {0}', path))

    def _run(self, sender, args):
        self.status('Replacing...')

        def job(uiapp):
            uidoc = uiapp.ActiveUIDocument
            doc = uidoc.Document
            instances = self._source_instances(doc, uidoc)
            if not instances:
                self.status('Nothing to replace.')
                return
            names = self.retained_names()
            level_below = bool(self.find('LevelBelowCheck').IsChecked)
            drafting = self.drafting
            by_centre = drafting and bool(
                self.find('CentreAlignCheck').IsChecked)
            in_groups = bool(self.find('GroupsCheck').IsChecked) and \
                not drafting

            group_work = []
            if in_groups:
                core.reset_run_caches()
                _loose, group_work = core.survey_groups(
                    doc, instances,
                    core.eid_value(self.src_record.symbol_id))
                count = core.count_group_instances(group_work)
                if count > GROUP_PROMPT_THRESHOLD:
                    types = len(group_work)
                    if not ask(
                            self.folder, self.version,
                            core.fmt('This element is within {0} groups.',
                                     count),
                            core.fmt(
                                'Are you sure? This could take some time.\n\n'
                                'Those {0} group instance(s) share {1} group '
                                'type(s). Each type has to be taken apart, '
                                'changed and put back together, and every '
                                'instance of it changes with it - project '
                                'wide, whatever the scope says.',
                                count, types),
                            owner=self.window):
                        self.status('Cancelled - nothing was changed.')
                        return

            self.busy_start('Replacing...')
            try:
                report = core.replace_all(
                    doc, uidoc, instances, self.tgt_record.symbol_id, names,
                    0.0, True, 0.0, level_below, self.retain_circuits,
                    bool(self.find('TagsCheck').IsChecked),
                    bool(self.find('WiresCheck').IsChecked),
                    in_groups, self.set_progress,
                    drafting, bool(self.find('MirrorCheck').IsChecked),
                    by_centre)
            finally:
                self.busy_end()
            self.last_drafting = drafting
            self.last_by_centre = by_centre

            self.report_clear()
            self.report_add('good', core.fmt(
                '{0} of {1} element(s) replaced with {2}.',
                report.replaced, len(instances), self.tgt_record.label))
            if names:
                self.report_add('muted', core.fmt(
                    '{0} parameter(s) carried across: {1}',
                    len(names), ', '.join(names)))
            if report.circuits_kept:
                self.report_add('good', core.fmt(
                    '{0} circuit connection(s) kept.', report.circuits_kept))
            if report.tags_kept:
                self.report_add('good', core.fmt(
                    '{0} tag(s) moved onto the replacements.',
                    report.tags_kept))
            if report.wires_kept:
                self.report_add('good', core.fmt(
                    '{0} wire end(s) reconnected.', report.wires_kept))
            if report.circuits_dropped:
                self.report_add('fail', core.fmt(
                    '{0} circuit(s) dropped - circuits retained was off.',
                    report.circuits_dropped))
            if report.levels_set:
                pairs = sorted(report.levels_set.items(),
                               key=lambda item: -item[1])
                summary = ', '.join([core.fmt('{0} ({1})', name, count)
                                     for name, count in pairs])
                self.report_add(
                    'muted',
                    core.fmt('Associated with {0}: {1}',
                             'the nearest level below' if level_below
                             else 'the original\'s own level', summary))
            if report.routes:
                pairs = sorted(report.routes.items(), key=lambda item: -item[1])
                self.report_add('muted', core.fmt(
                    'Placed by: {0}',
                    ', '.join([core.fmt('{0} ({1})', name, count)
                               for name, count in pairs])))
            if report.pinned:
                self.report_add('muted', core.fmt(
                    '{0} replacement(s) pinned, matching the original. The '
                    'adjust window releases the pin to move them.',
                    report.pinned))
            if drafting:
                self._report_drafting(report)
            for kind, text in report.lines:
                self.report_add(kind, text)

            failures = len([1 for k, _t in report.lines if k == 'fail'])
            self.find('ReportSummary').Text = core.fmt(
                '{0} replaced, {1} left alone', report.replaced, failures)
            self.last_new_ids = report.new_ids
            core.select_elements(uidoc, report.new_ids)
            self.status(core.fmt(
                '{0} replaced. {1}', report.replaced,
                'Fine-tune the rotation in the adjust window.' if drafting
                else 'Set the orientation and height in the adjust window.'))
            self._refresh_source()
            self._update_run()

            # Only after a run that took groups apart. An ordinary run reports
            # in the window and does not make you dismiss anything.
            if in_groups and (report.groups_done or report.groups_failed):
                self._group_summary(report, len(instances), failures)

            if report.new_ids:
                self._open_adjust()
        self.post(job)

    def _group_summary(self, report, attempted, failures):
        done = report.groups_done
        failed = report.groups_failed
        headline = core.fmt('{0} of {1} group instance(s) updated.',
                            done, done + failed)
        body = [core.fmt('{0} of {1} element(s) were replaced in total.',
                         report.replaced, attempted)]
        if failed:
            body.append(core.fmt(
                '{0} group instance(s) were left exactly as they were. Each '
                'one is named in the report with the reason.', failed))
            names = [text for kind, text in report.lines
                     if kind == 'fail' and text.startswith('Group ')]
            if names:
                body.append('')
                body.extend(names[:6])
                if len(names) > 6:
                    body.append(core.fmt('...and {0} more.', len(names) - 6))
        else:
            body.append('None were left behind.')
        if failures and not failed:
            body.append(core.fmt(
                '{0} other element(s) outside groups were left alone - see '
                'the report.', failures))
        tell(self.folder, self.version, headline, '\n'.join(body),
             owner=self.window)

    def _open_adjust(self):
        try:
            if self.adjust is not None:
                self.adjust.window.Close()
        except Exception:
            pass
        self.adjust = AdjustWindow(self.window, self.folder, self.version,
                                   self.uiapp, self.handler, self.event,
                                   self.last_new_ids, self.last_drafting,
                                   self.last_by_centre)
        self.adjust.show()

    def _reopen_adjust(self, sender, args):
        if self.last_new_ids:
            self._open_adjust()


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def launch(uiapp, folder, version):
    """Show the window, or bring the one already open back to the front."""
    try:
        existing = AppDomain.CurrentDomain.GetData(APPDOMAIN_KEY)
    except Exception:
        existing = None
    if existing is not None:
        try:
            if existing.window.IsLoaded:
                existing.window.Activate()
                return
        except Exception:
            pass

    tool = MainWindow(uiapp, folder, version)
    try:
        # parked in the AppDomain so a second click brings this one forward
        # rather than leaving an orphaned window behind
        AppDomain.CurrentDomain.SetData(APPDOMAIN_KEY, tool)
    except Exception:
        pass
    tool.show()


def show_error(title, text):
    try:
        dialog = TaskDialog(title)
        dialog.MainInstruction = title
        dialog.MainContent = text
        dialog.Show()
    except Exception:
        pass
