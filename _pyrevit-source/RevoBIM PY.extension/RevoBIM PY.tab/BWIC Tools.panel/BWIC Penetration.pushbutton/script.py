# -*- coding: utf-8 -*-
"""RevoBIM BWIC Placement.

Two tabs:

    Wall  -- the original tool. Select the services, pick the wall in the
             linked model, and a BWIC is placed, sized and stamped around
             them. Also resizes an existing BWIC from a fresh selection.
    Slab  -- select the services, Finish, click the floor. A generic model
             opening is placed at the centre of the selection, sized in plan,
             with its base and top set off the floor's own level.

Settings sit behind the gear in the header, split the same way, so the two
tools carry their own family, parameter names and clearances.
"""

__title__ = 'BWIC\nPenetration'
__author__ = 'RevoBIM PY'
__doc__ = ('Dark themed BWIC penetration window with Wall and Slab tabs.\n\n'
           'Wall: select the services, pick the linked wall.\n'
           'Slab: select the services, Finish, click the floor.\n'
           'Escape returns to the window, which stays open while you '
           'navigate the model.')

# modeless WPF windows need a persistent engine in pyRevit
__persistentengine__ = True

import math
import os.path as op
import sys
import traceback

from pyrevit import forms, script

logger = script.get_logger()

# --- stage 1: the core module ---------------------------------------------
# a failure here is the classic blank white pyRevit window, so it is caught
# and reported rather than left to die silently at module load
HERE = op.dirname(__file__)
if HERE not in sys.path:
    sys.path.append(HERE)

try:
    import bwic_core as core
except Exception:
    forms.alert('Place BWIC could not load its core module.\n\n{}'.format(
        traceback.format_exc()), title='BWIC Penetration', exitscript=True)

try:
    import bwic_global as gp
except Exception:
    forms.alert('BWIC Penetration could not load its Global Placement '
                'engine.\n\n{}'.format(traceback.format_exc()),
                title='BWIC Penetration', exitscript=True)

try:
    import bwic_families as fam
except Exception:
    forms.alert('BWIC Penetration could not load its family profiles.\n\n{}'
                .format(traceback.format_exc()), title='BWIC Penetration',
                exitscript=True)

try:
    import bwic_prompt as steps
except Exception:
    forms.alert('BWIC Penetration could not load its step prompt.\n\n{}'
                .format(traceback.format_exc()), title='BWIC Penetration',
                exitscript=True)

try:
    import bwic_drawer as drawer
except Exception:
    forms.alert('BWIC Penetration could not load its window drawer.\n\n{}'
                .format(traceback.format_exc()), title='BWIC Penetration',
                exitscript=True)

from pyrevit import UI, DB, HOST_APP
from System.Collections.Generic import List
from System.Windows import SizeToContent, Visibility, \
    WindowStartupLocation, VerticalAlignment
from System.Windows import FontWeights
from System.Windows.Controls import TextBlock
from System.Windows.Input import Key


def dpi_scale(window):
    """Device pixels per WPF unit for the screen this window is on."""
    try:
        from System.Windows import PresentationSource
        source = PresentationSource.FromVisual(window)
        if source is not None:
            scale = source.CompositionTarget.TransformToDevice.M22
            if scale:
                return scale
    except Exception:
        pass
    return 1.0


def working_area(scale):
    """The usable screen area in WPF units."""
    try:
        from System.Windows.Forms import Screen
        area = Screen.PrimaryScreen.WorkingArea
        return (area.Left / scale, area.Top / scale,
                area.Width / scale, area.Height / scale)
    except Exception:
        return (0.0, 0.0, 1920.0, 1040.0)


def bitmap_to_image(bitmap):
    """A System.Drawing bitmap as a frozen WPF image, or None.

    Through a PNG stream rather than an HBITMAP, so there is no GDI handle to
    leak each time a family is picked.
    """
    if bitmap is None:
        return None
    try:
        from System.IO import MemoryStream
        from System.Drawing.Imaging import ImageFormat
        from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption
        stream = MemoryStream()
        bitmap.Save(stream, ImageFormat.Png)
        stream.Position = 0
        image = BitmapImage()
        image.BeginInit()
        image.StreamSource = stream
        image.CacheOption = BitmapCacheOption.OnLoad
        image.EndInit()
        image.Freeze()
        return image
    except Exception as err:
        logger.debug('preview could not be shown: {}'.format(err))
        return None
    finally:
        try:
            bitmap.Dispose()
        except Exception:
            pass


def guarded(method):
    """Report a handler that throws instead of letting it vanish.

    IronPython swallows an exception raised inside a WPF event handler: the
    click simply does nothing, with no traceback and nothing in the log. Every
    handler goes through here so a failure names itself.
    """
    def wrapper(self, sender, args):
        try:
            return method(self, sender, args)
        except Exception as err:
            detail = traceback.format_exc()
            logger.error(detail)
            try:
                core.debug('HANDLER {} FAILED\n{}'.format(
                    method.__name__, detail))
            except Exception:
                pass
            try:
                self.report('{} failed: {}'.format(
                    method.__name__.replace('_', ' '), err))
            except Exception:
                pass
    wrapper.__name__ = method.__name__
    wrapper.__doc__ = method.__doc__
    return wrapper


# ---------------------------------------------------------------------------
# external event -- lets the modeless window drive the Revit API
# ---------------------------------------------------------------------------
class PlacementHandler(UI.IExternalEventHandler):
    def __init__(self, window):
        self.window = window
        self.clearance_mm = core.DEFAULT_CLEARANCE_MM
        self.options = {}
        self.settings = {}
        self.mode = 'place'

    def Execute(self, uiapp):
        if self.mode == 'global':
            self.run_global(uiapp)
            return
        try:
            if self.mode in ('slab', 'slab_resize'):
                core.run_slab_loop(
                    uiapp, self.settings, self.options, self.window.report,
                    'resize' if self.mode == 'slab_resize' else 'place')
            else:
                core.run_placement_loop(uiapp, self.clearance_mm, self.options,
                                        self.window.report, self.mode)
        except Exception as err:
            logger.error(err)
            self.window.report('Error: {}'.format(err))
        finally:
            core.close_output_window()
            self.window.finish()

    def run_global(self, uiapp):
        """Sweep the active view, then show what it did."""
        summary = None
        try:
            # the wall family's own profile decides its parameter names
            gp.configure(core.family_settings(self.settings, 'wall'))
            try:
                core.start_debug(uiapp.ActiveUIDocument.Document,
                                 'GLOBAL PLACEMENT RUN', self.settings,
                                 self.global_settings)
            except Exception:
                pass
            summary = gp.run_global_placement(uiapp, self.global_settings,
                                              self.window.report)
            # the engine keeps its own running notes; they belong in the
            # tool's one debug log with everything else
            for line in (summary or {}).get('log') or []:
                core.debug(line)
            if summary:
                core.debug('placed {placed}, to review {review}, failed '
                           '{failed}, skipped {skipped}, repeats {duplicates}'
                           .format(**dict((k, summary.get(k, 0)) for k in (
                               'placed', 'review', 'failed', 'skipped',
                               'duplicates'))))
        except Exception as err:
            logger.error(err)
            core.debug('GLOBAL RUN EXCEPTION\n{}'.format(
                traceback.format_exc()))
            self.window.report('Error: {}'.format(err))
        finally:
            core.close_output_window()
            self.window.finish()

        if summary:
            self.window.show_results(summary)

    def GetName(self):
        return 'RevoBIM BWIC Penetration'


class SelectionHandler(UI.IExternalEventHandler):
    """Select the flagged BWICs for the modeless results window.

    A modeless window cannot touch the selection itself, so it goes through
    an external event and Revit picks it up when it next has a moment.
    """

    def __init__(self):
        self.ids = []

    def Execute(self, uiapp):
        try:
            uidoc = uiapp.ActiveUIDocument
            if uidoc is None or not self.ids:
                return
            ids = List[DB.ElementId]()
            for eid in self.ids:
                ids.Add(eid)
            uidoc.Selection.SetElementIds(ids)
            try:
                uidoc.ShowElements(ids)
            except Exception:
                pass
        except Exception as err:
            logger.debug('could not select the flagged BWICs: {}'.format(err))

    def GetName(self):
        return 'RevoBIM BWIC select flagged'


# ---------------------------------------------------------------------------
# step prompt
# ---------------------------------------------------------------------------
# extended window styles: clicks pass through, never activated, no taskbar
WS_EX_TRANSPARENT = 0x20
WS_EX_TOOLWINDOW = 0x80
WS_EX_NOACTIVATE = 0x08000000
GWL_EXSTYLE = -20


class PromptParts(object):
    """The controls one prompt card is drawn into. The docked card in the
    tool window and the floating one over Revit have the same parts."""

    def __init__(self, card, accent, eyebrow, dots, icon, title, detail,
                 hint_box, hint):
        self.card = card
        self.accent_bd = accent
        self.eyebrow_tb = eyebrow
        self.dots_tb = dots
        self.icon_tb = icon
        self.title_tb = title
        self.detail_tb = detail
        self.hint_bd = hint_box
        self.hint_tb = hint


def draw_card(parts, find, look):
    """Fill a prompt card from a look (see bwic_prompt)."""
    brush = find({'green': 'Green', 'orange': 'Orange'}.get(
        look.get('accent'), 'Blue'))
    parts.accent_bd.Background = brush
    parts.eyebrow_tb.Foreground = brush
    parts.eyebrow_tb.Text = look.get('eyebrow') or ''
    parts.dots_tb.Text = steps.dots(look)
    parts.title_tb.Text = look.get('title') or ''
    # a note is a sentence, not a heading: no title line
    parts.title_tb.Visibility = Visibility.Visible if look.get('title') \
        else Visibility.Collapsed
    parts.detail_tb.Text = look.get('detail') or ''
    parts.detail_tb.Visibility = Visibility.Visible \
        if look.get('detail') else Visibility.Collapsed
    icon = {'placed': u'\u2713', 'problem': u'!'}.get(look.get('kind'), '')
    parts.icon_tb.Text = icon
    parts.icon_tb.Foreground = brush
    parts.icon_tb.Visibility = Visibility.Visible if icon \
        else Visibility.Collapsed
    hint = steps.hint_text(look)
    parts.hint_tb.Text = hint
    parts.hint_bd.Visibility = Visibility.Visible if hint \
        else Visibility.Collapsed


class StepPrompt(object):
    """Says what to pick next while a manual placement runs.

    The card is docked at the bottom of the tool window, below the action
    buttons. While the tool window is parked on the taskbar the same card
    floats over Revit instead (FloatingPrompt), so a step is never shown
    somewhere that cannot be seen. Parking or opening the window mid-step
    moves the card across.

    What it shows, and for how long, is decided by bwic_prompt.PromptState,
    so the timing can be proved on the bench. Nothing here takes focus --
    the tool window taking focus is what once stopped Return finishing a
    selection.
    """

    def __init__(self, xaml_file, tool):
        self.xaml_file = xaml_file
        self.tool = tool
        self.state = steps.PromptState()
        self.timer = None
        self._tick_handler = None
        self.floating = None

    # -- events from the run -------------------------------------------------
    def handle(self, event, details):
        if event == 'step':
            self.apply(self.state.step(details))
        elif event in ('placed', 'problem', 'note', 'blocked'):
            self.apply(self.state.flash(event, details))
        elif event == 'done':
            self.apply(self.state.done())

    def apply(self, result):
        if result is None:
            return
        action, look = result
        if action == 'hide':
            self.stop_timer()
            self.hide_all()
            return
        self.show(look)
        if look.get('seconds'):
            self.start_timer(look['seconds'])
        self.flush()

    # -- where it goes -------------------------------------------------------
    def parked(self):
        """True while the tool window is on the taskbar, or on its way."""
        lid = getattr(self.tool, 'drawer', None)
        if lid is not None and lid.heading == 'parked':
            return True
        try:
            return not self.tool.IsVisible
        except Exception:
            return False

    def show(self, look):
        if self.parked():
            self.tool.hide_docked_prompt()
            if self.floating is None:
                self.floating = FloatingPrompt(self.xaml_file, self.tool)
            self.floating.present(look)
        else:
            if self.floating is not None:
                self.floating.conceal()
            self.tool.show_docked_prompt(look)

    def refresh(self):
        """The tool window was parked or opened: move the card across."""
        if self.state.visible and self.state.current is not None:
            self.show(self.state.current)

    def hide_all(self):
        try:
            self.tool.hide_docked_prompt()
        except Exception:
            pass
        if self.floating is not None:
            self.floating.conceal()

    # -- the flash timer ---------------------------------------------------------
    def start_timer(self, seconds):
        from System import TimeSpan
        from System.Windows.Threading import DispatcherTimer
        self.stop_timer()
        self.timer = DispatcherTimer()
        self.timer.Interval = TimeSpan.FromSeconds(seconds)
        # held on the instance so it can be taken off again
        self._tick_handler = self.flash_over
        self.timer.Tick += self._tick_handler
        self.timer.Start()

    def stop_timer(self):
        if self.timer is not None:
            try:
                self.timer.Stop()
                if self._tick_handler is not None:
                    self.timer.Tick -= self._tick_handler
            except Exception:
                pass
        self.timer = None
        self._tick_handler = None

    def flash_over(self, sender, args):
        self.stop_timer()
        self.apply(self.state.flash_over())

    def flush(self):
        """Draw now. The next pick starts straight after this, and the card
        has to be on screen before Revit starts waiting for the click."""
        try:
            from System import Action
            from System.Windows.Threading import DispatcherPriority
            self.tool.Dispatcher.Invoke(Action(lambda: None),
                                        DispatcherPriority.Render)
        except Exception:
            pass

    def shut(self):
        self.stop_timer()
        self.state.reset()
        self.hide_all()
        if self.floating is not None:
            self.floating.shut()
            self.floating = None


class FloatingPrompt(forms.WPFWindow):
    """The step card over Revit, for while the tool window is parked.

    A click-through card at the top of the Revit window. It never takes
    focus and lets every click through to Revit underneath.
    """

    def __init__(self, xaml_file, tool):
        forms.WPFWindow.__init__(self, xaml_file, handle_esc=False)
        self.tool = tool
        self.parts = PromptParts(None, self.accent_bd, self.eyebrow_tb,
                                 self.dots_tb, self.icon_tb, self.title_tb,
                                 self.detail_tb, self.hint_bd, self.hint_tb)
        self.SourceInitialized += self.make_click_through

    def present(self, look):
        draw_card(self.parts, self.FindResource, look)
        self.position()
        try:
            if not self.IsVisible:
                self.Show()
        except Exception:
            pass

    def conceal(self):
        try:
            self.Hide()
        except Exception:
            pass

    def position(self):
        """Top centre of the Revit window, below the ribbon and Options Bar,
        so it sits where the eye already is and clear of Finish."""
        try:
            scale = dpi_scale(self.tool)
            ext = HOST_APP.uiapp.MainWindowExtents
            left = (ext.Left + ext.Right) / 2.0 / scale - self.Width / 2.0
            top = ext.Top / scale + 170.0
        except Exception:
            scale = 1.0
            area = working_area(scale)
            left = area[0] + (area[2] - self.Width) / 2.0
            top = area[1] + 170.0
        area = working_area(scale)
        self.Left = min(max(left, area[0]), area[0] + area[2] - self.Width)
        self.Top = max(top, area[1])

    # -- click-through, never activated ----------------------------------------
    def make_click_through(self, sender, args):
        try:
            import ctypes
            from System.Windows.Interop import WindowInteropHelper
            hwnd = int(str(WindowInteropHelper(self).Handle))
            user32 = ctypes.windll.user32
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                                  style | WS_EX_TRANSPARENT
                                  | WS_EX_TOOLWINDOW
                                  | WS_EX_NOACTIVATE)
        except Exception as err:
            logger.debug('prompt could not be made click-through: {}'
                         .format(err))

    def shut(self):
        try:
            self.Close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Global Placement results
# ---------------------------------------------------------------------------
class ResultsWindow(forms.WPFWindow):
    """What a global run did, and a way to get at anything needing a look."""

    def __init__(self, xaml_file, summary, select_event, select_handler):
        forms.WPFWindow.__init__(self, xaml_file, handle_esc=False)
        self.select_event = select_event
        self.select_handler = select_handler
        try:
            self.version_tb.Text = 'v' + core.__version__
        except Exception:
            pass
        self.review_ids = summary.get('review_ids') or []
        self.drawer = drawer.Drawer(self, self.header_pnl, self.shrink_btn)
        self.PreviewKeyDown += self.key_down

        review = summary.get('review', 0)
        self.placed_val.Text = str(summary.get('placed', 0))
        self.placed_cap.Text = 'BWIC placed'
        self.review_val.Text = str(review)
        self.failed_val.Text = str(summary.get('failed', 0))

        def plural(n, word):
            return '{} {}{}'.format(n, word, '' if n == 1 else 's')

        detail = ['{} across {}'.format(
            plural(summary.get('groups', 0), 'group'),
            plural(summary.get('walls', 0), 'wall'))]
        if summary.get('skipped'):
            detail.append('{} already had a BWIC'.format(summary['skipped']))
        if summary.get('duplicates'):
            detail.append('{} dropped'.format(
                plural(summary['duplicates'], 'repeat opening')))
        if summary.get('unmeasured'):
            detail.append('{} not measurable at the wall'.format(
                plural(summary['unmeasured'], 'service')))
        self.detail_tb.Text = ', '.join(detail) + '.'

        warnings = summary.get('warnings') or []
        if warnings:
            shown = warnings[:3]
            extra = len(warnings) - len(shown)
            self.warn_tb.Text = 'Revit messages dismissed: {}{}'.format(
                '; '.join(shown),
                ' and {} more'.format(extra) if extra > 0 else '')
        else:
            self.warn_tb.Visibility = Visibility.Collapsed

        lines = []
        if summary.get('group_name'):
            lines.append('Overlapping BWICs are boxed in red, grouped as '
                         '"{}".'.format(summary['group_name']))
        elif review:
            lines.append('Overlapping BWICs were found but could not be '
                         'marked in this view -- try a plan or section.')
        else:
            lines.append('No overlapping BWICs in this run.')
        if summary.get('failed_group_name'):
            lines.append('Failures are boxed in amber, grouped as "{}".'
                         .format(summary['failed_group_name']))
        self.note_tb.Text = ' '.join(lines)

        if self.review_ids:
            self.select_btn.Content = 'Select the {} to review'.format(
                len(self.review_ids))
        else:
            self.select_btn.Visibility = Visibility.Collapsed

    @guarded
    def select_click(self, sender, args):
        try:
            self.select_handler.ids = self.review_ids
            self.select_event.Raise()
        except Exception as err:
            logger.debug('could not raise the selection event: {}'.format(err))

    @guarded
    def shrink_click(self, sender, args):
        self.drawer.toggle()

    @guarded
    def key_down(self, sender, args):
        if self.drawer.handle_key(args):
            return
        if args.Key == Key.Escape:
            args.Handled = True
            self.Close()

    @guarded
    def drag_window(self, sender, args):
        if self.drawer.header_down(args):
            return
        try:
            self.DragMove()
        except Exception:
            pass

    @guarded
    def close_click(self, sender, args):
        self.Close()


# ---------------------------------------------------------------------------
# settings window
# ---------------------------------------------------------------------------
RULE_LABELS = [
    ('two_level', 'Two levels (Base Level / Top Level + offsets)'),
    ('single_level', 'Single level (nearest level + height parameters)'),
]

# the slab sub tabs ARE the method: the tab you are on decides the shapes
SLAB_METHODS = ['rectangular', 'circular', 'auto']
WALL_SHAPES = ['rectangular', 'circular']

DATUM_LABELS = [
    ('soffit', 'The floor soffit, downwards'),
    ('top', 'The floor top, upwards'),
    ('level', "The floor's level, plus its depth"),
]


class FamilyCard(object):
    """One family slot in the main window: list, type, preview and summary.

    The four cards (wall and slab, rectangular and circular) all behave the
    same, so they share this rather than four copies of the same handlers.
    The controls are handed in as self.x references, so the bench can check
    every one exists.
    """

    def __init__(self, window, slot, family_cb, type_cb, image, noprev,
                 summary):
        self.window = window
        self.slot = slot
        self.family_cb = family_cb
        self.type_cb = type_cb
        self.image = image
        self.noprev = noprev
        self.summary = summary
        self.names = []
        self.types = {}
        self.loading = False
        self.family_key = fam.slot_family_key(slot)
        self.type_key = fam.slot_type_key(slot)
        family_cb.SelectionChanged += self.family_changed
        type_cb.SelectionChanged += self.type_changed
        # the list is read again whenever it is opened, so a family loaded
        # into the project while the tool is open turns up without a restart
        family_cb.DropDownOpened += self.dropdown_opened

    # -- the list ------------------------------------------------------------
    def fill(self, families, every=None):
        """families: [(name, [type names], kind, label)] this slot offers.
        every: all the project's families, so a saved choice of the other
        shape is kept and labelled rather than called not loaded."""
        settings = self.window.settings
        wanted = settings.get(self.family_key, '') or (
            core.FAMILY_NAME if self.slot == 'wall' else '')
        self.loading = True
        try:
            self.names = [entry[0] for entry in families]
            self.types = dict((entry[0], list(entry[1])) for entry in families)
            self.family_cb.Items.Clear()
            loaded = dict((entry[0], list(entry[1]))
                          for entry in (every or families))
            if wanted and wanted not in self.names:
                # keep a saved family rather than quietly swap it for another:
                # one that is not loaded, or one of the other shape
                self.names.insert(0, wanted)
                self.types[wanted] = loaded.get(wanted, [])
                other = u'circular' if self.slot in ('wall', 'slab_rect') \
                    else u'rectangular'
                self.family_cb.Items.Add(u'{}   [{}]'.format(
                    wanted, other if wanted in loaded else 'not loaded'))
                start = 1
            else:
                start = 0
            # families with saved Family settings first, in green
            profiles = self.window.profiles
            self.names[start:] = fam.set_first(self.names[start:], profiles)
            if start and fam.is_set(wanted, profiles):
                self.colour_item(0, True)
            for name in self.names[start:]:
                self.family_cb.Items.Add(self.list_item(
                    name, fam.is_set(name, profiles)))
            if not self.names:
                self.family_cb.Items.Add(
                    '<no circular generic model families>'
                    if self.slot in ('wall_circ', 'slab_circ') else
                    '<no rectangular generic model families>')
            self.family_cb.SelectedIndex = self.names.index(wanted) \
                if wanted in self.names else (0 if self.names else 0)
            self.fill_types()
        finally:
            self.loading = False
        self.refresh()

    def list_item(self, label, ready):
        """A list entry: green with a tick once the family is set up."""
        from System.Windows.Controls import ComboBoxItem
        item = ComboBoxItem()
        item.Content = (u'\u2713  ' + label) if ready else label
        if ready:
            item.Foreground = self.window.FindResource('Green')
            item.FontWeight = FontWeights.SemiBold
        return item

    def colour_item(self, index, ready):
        label = self.family_cb.Items[index]
        self.family_cb.Items[index] = self.list_item(str(label), ready)

    def fill_types(self):
        family = self.family()
        types = self.types.get(family, [])
        wanted = self.window.settings.get(self.type_key, '') \
            if self.type_key else ''
        self.type_cb.Items.Clear()
        for name in types:
            self.type_cb.Items.Add(name)
        if wanted and wanted not in types and types == []:
            self.type_cb.Items.Add(wanted)
            types = [wanted]
        self.type_cb.SelectedIndex = types.index(wanted) \
            if wanted in types else (0 if types else -1)

    def family(self):
        index = self.family_cb.SelectedIndex
        return self.names[index] if 0 <= index < len(self.names) else ''

    def type_name(self):
        chosen = self.type_cb.SelectedItem
        return str(chosen) if chosen is not None else ''

    # -- events --------------------------------------------------------------
    def family_changed(self, sender, args):
        # a change bubbles up from the type list too; only the family list
        # itself counts here
        if self.loading or args.OriginalSource is not self.family_cb:
            return
        self.loading = True
        try:
            self.fill_types()
        finally:
            self.loading = False
        self.store()

    def type_changed(self, sender, args):
        if self.loading or args.OriginalSource is not self.type_cb:
            return
        self.store()

    def dropdown_opened(self, sender, args):
        self.window.reload_families()

    def store(self):
        """Remember the choice at once: it is what the next run uses."""
        settings = self.window.settings
        settings[self.family_key] = self.family()
        if self.type_key:
            settings[self.type_key] = self.type_name()
        try:
            core.write_settings(settings)
            core.apply_settings(settings)
        except Exception as err:
            logger.debug('family choice not saved: {}'.format(err))
        self.refresh()
        self.window.family_choice_changed(self.slot)

    # -- what it shows -------------------------------------------------------
    def refresh(self):
        family = self.family()
        image = self.window.preview(family, self.type_name())
        self.image.Source = image
        self.noprev.Visibility = Visibility.Collapsed if image is not None \
            else Visibility.Visible
        profile = self.window.profiles.get(family) if family else None
        if profile:
            text = fam.summary(self.slot, profile)
            self.summary.ClearValue(TextBlock.ForegroundProperty)
        elif family:
            # nothing runs until this is done
            text = (u'Family settings not set yet \u2013 press Family '
                    u'settings\u2026, check the parameters and clearance, '
                    u'then Save. Placing is blocked until then.')
            self.summary.Foreground = self.window.FindResource('Orange')
        else:
            text = 'Pick a family.'
            self.summary.ClearValue(TextBlock.ForegroundProperty)
        self.summary.Text = text


# the roles that size an opening, as against those that position it
SIZE_ROLES = ('through', 'across', 'height', 'diameter', 'plan_x', 'plan_y')
SHAPE_LABELS = {fam.RECT: 'Rectangular', fam.CIRC: 'Round'}


class FamilySettingsWindow(forms.WPFWindow):
    """How one family sizes itself: its shape, and which of its parameters
    the tool writes each size and position to.

    The rows come from bwic_families.ROLES, so the dialog can only offer a
    role the placement code knows how to fill.
    """

    def __init__(self, xaml_file, slot, family, profile, length_names,
                 all_names, placed, preview, lift, on_save, worksets=(),
                 settings_workset=None):
        forms.WPFWindow.__init__(self, xaml_file, handle_esc=False)
        self.slot = slot
        self.family = family
        self.length_names = list(length_names)
        self.all_names = list(all_names)
        self.on_save = on_save
        self.profile = {'shape': profile.get('shape') or fam.default_shape(slot),
                        'radius': bool(profile.get('radius')),
                        'roles': dict(profile.get('roles') or {}),
                        'drive': profile.get('drive') or fam.STANDARD,
                        'split': dict((axis, dict(pair)) for axis, pair in
                                      (profile.get('split') or {}).items())}
        # one workset per sub tab: Standard, and X+ / X- or Y+ / Y-
        self.worksets = fam.profile_worksets(profile)
        self.combos = {}
        self.split_combos = {}

        self.drawer = drawer.Drawer(self, self.header_pnl, self.shrink_btn,
                                    lift=lift)
        self.PreviewKeyDown += self.key_down

        self.fs_slot_tb.Text = dict((k, v) for k, v, _, _ in fam.SLOTS)[slot]
        self.fs_family_tb.Text = family
        note = '' if placed else (' Only its type parameters are visible '
                                  'until it has been placed once in this '
                                  'model -- a saved name it cannot see is '
                                  'kept.')
        self.fs_count_tb.Text = '{} length parameter{} found.{}'.format(
            len(self.length_names),
            '' if len(self.length_names) == 1 else 's', note)
        self.fs_preview_img.Source = preview
        self.fs_noprev_tb.Visibility = Visibility.Collapsed \
            if preview is not None else Visibility.Visible

        shapes = fam.SLOT_SHAPES[slot]
        for shape in shapes:
            self.fs_shape_cb.Items.Add(SHAPE_LABELS[shape])
        self.fs_shape_cb.SelectedIndex = shapes.index(self.profile['shape']) \
            if self.profile['shape'] in shapes else 0
        # a slab slot exists for one shape; only the wall slot can change it
        self.fs_shape_cb.IsEnabled = len(shapes) > 1
        self.fs_holds_cb.Items.Add('Diameter')
        self.fs_holds_cb.Items.Add('Radius')
        self.fs_holds_cb.SelectedIndex = 1 if self.profile['radius'] else 0
        # only slab families have position and level roles
        self.fs_position_pnl.Visibility = Visibility.Visible \
            if slot.startswith('slab') else Visibility.Collapsed

        # Standard or X+ / X- (Y+ / Y- on a round family, whose only pair is
        # its thickness through)
        splittable = slot in fam.SPLIT_AXES
        self.fs_split_tab_tb.Text = fam.SPLIT_LABEL.get(
            slot, 'X+ / X-').replace('-', u'\u2212')
        self.fs_drive_tabs.Visibility = Visibility.Visible if splittable \
            else Visibility.Collapsed
        self.fs_drive_tabs.SelectedIndex = 1 if (
            splittable and self.profile['drive'] == fam.SPLIT) else 0

        # this family's clearance each side; blank follows the tab's
        # 50 mm until changed
        own = fam.clearance_value(profile.get('clearance_mm'))
        self.fs_clearance_tb.Text = '{:g}'.format(
            fam.DEFAULT_CLEARANCE_MM if own is None else own)
        self.fs_clearance_tb_hint.Text = (
            u'mm each side of the pipe' if self.slot in ('wall_circ',
                                                         'slab_circ')
            else u'mm each side of the services')
        self.fs_clearance_tb.TextChanged += self.something_changed

        self.workset_drive = self.selected_drive()
        self.fill_worksets(worksets, settings_workset)
        self.build_rows()
        self.fs_shape_cb.SelectionChanged += self.shape_changed
        self.fs_holds_cb.SelectionChanged += self.something_changed
        self.fs_drive_tabs.SelectionChanged += self.drive_changed

    # -- workset -------------------------------------------------------------
    def fill_worksets(self, worksets, settings_workset):
        """As Settings, the active workset, then every workset in the model.
        A saved workset this model does not have is kept, and says so."""
        follow = fam.FOLLOW_LABEL
        if settings_workset:
            follow = u'{}  ({})'.format(follow, settings_workset)
        self.workset_values = [fam.FOLLOW_SETTINGS, fam.ACTIVE_WORKSET]
        labels = [follow, fam.ACTIVE_LABEL]
        names = list(worksets)
        for name in names:
            self.workset_values.append(name)
            labels.append(name)
        for saved in sorted(set(v for v in self.worksets.values() if v)):
            if saved not in self.workset_values:
                self.workset_values.append(saved)
                labels.append(u'{}  (not in this model)'.format(saved))
        self.fs_workset_cb.Items.Clear()
        for label in labels:
            self.fs_workset_cb.Items.Add(label)
        # a model that is not workshared has nowhere to put it
        self.fs_workset_cb.IsEnabled = bool(names) or \
            any(self.worksets.values())
        self.show_workset(self.workset_drive)

    def show_workset(self, drive):
        """Show the workset of one sub tab."""
        self.workset_drive = drive
        current = self.worksets.get(drive) or fam.FOLLOW_SETTINGS
        self.fs_workset_cb.SelectedIndex = \
            self.workset_values.index(current) \
            if current in self.workset_values else 0
        splittable = self.slot in fam.SPLIT_AXES
        tab = fam.SPLIT_LABEL.get(self.slot, 'X+ / X-').replace(
            '-', u'\u2212') if drive == fam.SPLIT else 'Standard'
        self.fs_workset_head_tb.Text = u'Workset \u2013 {}'.format(tab) \
            if splittable else 'Workset'
        self.fs_workset_tb.Text = (
            u'Used when this family is set to {}. Each sub tab keeps its '
            u'own.'.format(tab)) if splittable else ''

    def keep_workset(self):
        """Store the list's choice against the sub tab it was showing."""
        self.worksets[self.workset_drive] = self.selected_workset()

    def gathered_worksets(self):
        self.keep_workset()
        return dict(self.worksets)

    def selected_workset(self):
        index = self.fs_workset_cb.SelectedIndex
        if 0 <= index < len(self.workset_values):
            return self.workset_values[index]
        return fam.FOLLOW_SETTINGS

    # -- rows ----------------------------------------------------------------
    def selected_shape(self):
        shapes = fam.SLOT_SHAPES[self.slot]
        index = self.fs_shape_cb.SelectedIndex
        return shapes[index] if 0 <= index < len(shapes) else shapes[0]

    def build_rows(self):
        from System.Windows import GridLength, GridUnitType, Thickness, \
            TextWrapping
        from System.Windows.Controls import (ColumnDefinition, ComboBox,
                                             RowDefinition, StackPanel,
                                             TextBlock, Grid)
        shape = self.selected_shape()
        round_shape = shape == fam.CIRC
        self.fs_holds_cb.Visibility = Visibility.Visible if round_shape \
            else Visibility.Collapsed
        self.fs_holds_lbl.Visibility = self.fs_holds_cb.Visibility

        for grid in (self.fs_size_grid, self.fs_position_grid):
            grid.Children.Clear()
            grid.RowDefinitions.Clear()
            grid.ColumnDefinitions.Clear()
            grid.ColumnDefinitions.Add(
                ColumnDefinition(Width=GridLength(165)))
            grid.ColumnDefinitions.Add(
                ColumnDefinition(Width=GridLength(1, GridUnitType.Star)))
        self.combos = {}
        self.role_rows = {}

        label_style = self.FindResource('FieldLabel')
        combo_style = self.FindResource('DarkCombo')
        dim = self.FindResource('TextDim')
        for role in fam.roles_for(self.slot, shape):
            key, label, help_text, _, kind, _, required = role
            grid = self.fs_size_grid if key in SIZE_ROLES \
                else self.fs_position_grid
            row = grid.RowDefinitions.Count
            grid.RowDefinitions.Add(RowDefinition(Height=GridLength.Auto))

            left = StackPanel(Margin=Thickness(0, 0, 10, 8))
            title = TextBlock(Text=label + ('' if not required else '  *'))
            title.Style = label_style
            left.Children.Add(title)
            hint = TextBlock(Text=help_text, FontSize=10.5, Foreground=dim,
                             TextWrapping=TextWrapping.Wrap)
            left.Children.Add(hint)
            Grid.SetRow(left, row)
            Grid.SetColumn(left, 0)
            grid.Children.Add(left)

            combo = ComboBox(Margin=Thickness(0, 0, 0, 8))
            combo.Style = combo_style
            combo.VerticalAlignment = VerticalAlignment.Top
            names = list(self.length_names if kind == 'length'
                         else self.all_names)
            current = self.profile['roles'].get(key, '') or ''
            if current and current not in names:
                names.insert(0, current)
            combo.Items.Add('<none>')
            for name in names:
                combo.Items.Add(name)
            combo.SelectedIndex = names.index(current) + 1 \
                if current in names else 0
            combo.SelectionChanged += self.something_changed
            Grid.SetRow(combo, row)
            Grid.SetColumn(combo, 1)
            grid.Children.Add(combo)
            self.combos[key] = combo
            self.role_rows[key] = (left, combo)
        self.build_split_rows()
        self.show_drive()
        self.check()

    def build_split_rows(self):
        """Three groups -- X = Width, Y = Length, Z = Height -- each with a
        Minus and a Plus parameter."""
        from System.Windows import GridLength, GridUnitType, Thickness, \
            TextWrapping, FontWeights
        from System.Windows.Controls import (ColumnDefinition, ComboBox,
                                             RowDefinition, TextBlock, Grid)
        grid = self.fs_split_grid
        grid.Children.Clear()
        grid.RowDefinitions.Clear()
        grid.ColumnDefinitions.Clear()
        grid.ColumnDefinitions.Add(ColumnDefinition(Width=GridLength(165)))
        grid.ColumnDefinitions.Add(
            ColumnDefinition(Width=GridLength(1, GridUnitType.Star)))
        self.split_combos = {}
        if self.slot not in fam.SPLIT_AXES:
            return
        label_style = self.FindResource('FieldLabel')
        combo_style = self.FindResource('DarkCombo')
        dim = self.FindResource('TextDim')
        main = self.FindResource('TextMain')
        needed = [r[0] for r in fam.roles_for(self.slot, self.selected_shape())
                  if r[6]]
        size_word = {'x': 'width', 'y': 'length', 'z': 'height'}

        def add(element, row, column, span=1):
            Grid.SetRow(element, row)
            Grid.SetColumn(element, column)
            if span > 1:
                Grid.SetColumnSpan(element, span)
            grid.Children.Add(element)

        for axis, label, role in fam.SPLIT_AXES[self.slot]:
            row = grid.RowDefinitions.Count
            grid.RowDefinitions.Add(RowDefinition(Height=GridLength.Auto))
            head = TextBlock(Text=label + ('  *' if role in needed else ''),
                             FontSize=12.5, Foreground=main,
                             Margin=Thickness(0, 4, 0, 1))
            head.FontWeight = FontWeights.SemiBold
            add(head, row, 0, 2)
            row += 1
            grid.RowDefinitions.Add(RowDefinition(Height=GridLength.Auto))
            what = 'the overall {}'.format(size_word[axis])
            if self.slot == 'wall_circ':
                what = 'the thickness through the wall'
            elif self.slot == 'slab_circ':
                what = 'the thickness through the floor'
            hint = TextBlock(
                Text='Each side takes half {}.'.format(what),
                FontSize=10.5, Foreground=dim, TextWrapping=TextWrapping.Wrap,
                Margin=Thickness(0, 0, 0, 5))
            add(hint, row, 0, 2)
            pair = self.profile['split'].get(axis) or {}
            for side, word in (('minus', 'Minus side'), ('plus', 'Plus side')):
                row = grid.RowDefinitions.Count
                grid.RowDefinitions.Add(RowDefinition(Height=GridLength.Auto))
                title = TextBlock(Text='{} {}'.format(axis.upper(), word),
                                  Margin=Thickness(10, 0, 10, 6))
                title.Style = label_style
                add(title, row, 0)
                combo = ComboBox(Margin=Thickness(0, 0, 0, 6))
                combo.Style = combo_style
                names = list(self.length_names)
                current = pair.get(side, '') or ''
                if current and current not in names:
                    names.insert(0, current)
                combo.Items.Add('<none>')
                for name in names:
                    combo.Items.Add(name)
                combo.SelectedIndex = names.index(current) + 1 \
                    if current in names else 0
                combo.SelectionChanged += self.something_changed
                add(combo, row, 1)
                self.split_combos[(axis, side)] = combo

    def selected_drive(self):
        if self.slot in fam.SPLIT_AXES and self.fs_drive_tabs.SelectedIndex == 1:
            return fam.SPLIT
        return fam.STANDARD

    def show_drive(self):
        split = self.selected_drive() == fam.SPLIT
        self.fs_split_pnl.Visibility = Visibility.Visible if split \
            else Visibility.Collapsed
        round_family = fam.SLOT_SHAPES[self.slot] == (fam.CIRC,)
        if round_family:
            # a round family keeps its diameter row either way; only the
            # rows the pairs take over are swapped out
            self.fs_standard_pnl.Visibility = Visibility.Visible
            covered = fam.axis_roles(self.slot)
            for key, parts in self.role_rows.items():
                shown = Visibility.Collapsed if (split and key in covered) \
                    else Visibility.Visible
                for element in parts:
                    element.Visibility = shown
        else:
            self.fs_standard_pnl.Visibility = Visibility.Collapsed if split \
                else Visibility.Visible

    # -- reading it back -------------------------------------------------------
    def gather(self):
        """The profile as the dialog now shows it. Roles belonging to the
        other shape are kept, so switching shape and back loses nothing."""
        roles = dict(self.profile['roles'])
        for key, combo in self.combos.items():
            value = combo.SelectedItem
            roles[key] = '' if value is None or str(value).startswith('<') \
                else str(value)
        split = dict((axis, dict(pair)) for axis, pair in
                     (self.profile.get('split') or {}).items())
        for (axis, side), combo in self.split_combos.items():
            value = combo.SelectedItem
            split.setdefault(axis, {})[side] = '' if value is None or \
                str(value).startswith('<') else str(value)
        return {'shape': self.selected_shape(),
                'radius': self.fs_holds_cb.SelectedIndex == 1,
                'roles': roles,
                'drive': self.selected_drive(),
                'split': split,
                'worksets': self.gathered_worksets(),
                'clearance_mm': str(self.fs_clearance_tb.Text).strip()}

    def check(self):
        found = fam.problems(self.slot, self.gather(), self.length_names)
        if found:
            self.fs_problems_tb.Text = u'\n'.join(u'\u2022 ' + p
                                                  for p in found)
            self.fs_problems_bd.Visibility = Visibility.Visible
        else:
            self.fs_problems_tb.Text = ''
            self.fs_problems_bd.Visibility = Visibility.Collapsed

    # -- events --------------------------------------------------------------
    def shape_changed(self, sender, args):
        self.profile = self.gather()
        self.build_rows()

    def something_changed(self, sender, args):
        self.check()

    def drive_changed(self, sender, args):
        # SelectionChanged bubbles: the lists inside fire it too
        if args is None or args.OriginalSource is not self.fs_drive_tabs:
            return
        # each sub tab has its own workset
        self.keep_workset()
        self.show_workset(self.selected_drive())
        self.show_drive()
        self.check()

    @guarded
    def suggest_click(self, sender, args):
        guess = fam.seed_profile(self.slot, {}, self.length_names,
                                 self.all_names)
        guess['shape'] = self.selected_shape()
        # a guess from names is about sizes: the worksets stay as chosen,
        # and live outside self.profile
        self.profile = guess
        self.fs_holds_cb.SelectedIndex = 1 if guess['radius'] else 0
        # a family whose names are Minus / Plus pairs is suggested as one
        if self.slot in fam.SPLIT_AXES:
            self.fs_drive_tabs.SelectedIndex = 1 \
                if guess.get('drive') == fam.SPLIT else 0
        self.build_rows()

    @guarded
    def save_click(self, sender, args):
        self.on_save(self.slot, self.family, self.gather())
        self.Close()

    @guarded
    def cancel_click(self, sender, args):
        self.Close()

    @guarded
    def shrink_click(self, sender, args):
        self.drawer.toggle()

    @guarded
    def key_down(self, sender, args):
        if self.drawer.handle_key(args):
            return
        if args.Key == Key.Escape:
            args.Handled = True
            self.Close()

    @guarded
    def drag_window(self, sender, args):
        if self.drawer.header_down(args):
            return
        try:
            self.DragMove()
        except Exception:
            pass


class SettingsWindow(forms.WPFWindow):
    def __init__(self, xaml_file, settings, on_apply, lift=None):
        # Escape is handled here rather than by pyRevit, so that while the
        # window is shrunk it reopens it instead of closing it
        forms.WPFWindow.__init__(self, xaml_file, handle_esc=False)
        self.settings = dict(settings)
        self.on_apply = on_apply
        self.families = []
        # a dialog lifts its owner: shrinking Settings parks the tool window
        # too, so the whole tool gets out of the way of the model
        self.drawer = drawer.Drawer(self, self.header_pnl, self.shrink_btn,
                                    lift=lift)
        self.PreviewKeyDown += self.key_down
        self.load()

    @guarded
    def shrink_click(self, sender, args):
        self.drawer.toggle()

    @guarded
    def key_down(self, sender, args):
        if self.drawer.handle_key(args):
            return
        if args.Key == Key.Escape:
            args.Handled = True
            self.Close()

    def load(self):
        get = self.settings.get
        # -- wall ----------------------------------------------------------
        self.w_round_tb.Text = get('round_up',
                                   '{:.0f}'.format(core.ROUND_UP_MM))
        self.w_blk_tb.Text = get('wall_type_blockwork', 'BWIC - Blockwork')
        self.w_fr_tb.Text = get('wall_type_firerated', 'BWIC - Fire Rated Wall')

        # -- slab ----------------------------------------------------------

        self.s_round_tb.Text = get('slab_round_up', '5')
        self.s_heightextra_tb.Text = get('slab_height_extra', '0')
        self.s_diaround_tb.Text = get('slab_circular_round', '10')
        self.s_group_tb.Text = get('slab_group_gap', '100')
        self.s_pipegap_tb.Text = get('slab_pipe_tray_gap', '150')
        self.s_groupangle_tb.Text = get('slab_group_angle', '15')
        self.s_topheightextra_tb.Text = get('slab_top_height_extra', '0')


        self.s_rule_cb.Items.Clear()
        for _, label in RULE_LABELS:
            self.s_rule_cb.Items.Add(label)
        wanted_rule = get('slab_rule', 'two_level')
        self.s_rule_cb.SelectedIndex = \
            next((i for i, (key, _) in enumerate(RULE_LABELS)
                  if key == wanted_rule), 0)
        self.s_rule_cb.SelectionChanged += self.rule_changed

        self.load_worksets()
        self.rule_changed(None, None)

    def place_beside(self, owner):
        """Open to the left of the tool window, so neither covers the other.

        Falls back to the right hand side when there is no room on the left.
        """
        try:
            scale = dpi_scale(owner)
            area_left, area_top, area_w, area_h = working_area(scale)
            width = self.Width if self.Width == self.Width else 470.0
            height = self.Height if self.Height == self.Height else 620.0

            left = owner.Left - width - 12
            if left < area_left:
                left = owner.Left + owner.ActualWidth + 12
            left = min(max(left, area_left), area_left + area_w - width)

            top = owner.Top
            top = min(max(top, area_top), area_top + area_h - height)

            self.WindowStartupLocation = WindowStartupLocation.Manual
            self.Left = left
            self.Top = top
        except Exception:
            logger.debug('could not position the settings window')

    def load_worksets(self):
        self.workset_names = []
        try:
            self.workset_names = [w.Name
                                  for w in core.list_worksets(HOST_APP.doc)]
        except Exception:
            logger.debug('could not read the worksets')

        self.s_workset_cb.Items.Clear()
        self.s_workset_cb.Items.Add('<active workset>')
        for name in self.workset_names:
            self.s_workset_cb.Items.Add(name)
        self.s_workset_cb.IsEnabled = bool(self.workset_names)

        if not self.workset_names:
            self.s_workset_cb.SelectedIndex = 0
            return

        remembered = self.settings.get('workset')
        chosen = remembered if remembered in self.workset_names else \
            next((n for n in self.workset_names
                  if core.WORKSET_KEYWORD.upper() in n.upper()), None)
        self.s_workset_cb.SelectedIndex = \
            self.workset_names.index(chosen) + 1 if chosen else 0

    def selected_workset(self):
        value = self.s_workset_cb.SelectedItem
        if value is None or str(value).startswith('<'):
            return ''
        return str(value)

    def report(self, message):
        """The settings window has no status line, so it says it out loud."""
        logger.error(message)
        try:
            forms.alert(message, title='BWIC Penetration Settings')
        except Exception:
            pass

    # -- family cards ---------------------------------------------------------
    def picked(self, combo):
        value = combo.SelectedItem
        if value is None or str(value).startswith('<'):
            return ''
        return str(value)

    # -- events ------------------------------------------------------------
    def rule_changed(self, sender, args):
        single = self.selected_rule() == 'single_level'
        self.s_single_panel.Visibility = \
            Visibility.Visible if single else Visibility.Collapsed
        self.s_two_panel.Visibility = \
            Visibility.Collapsed if single else Visibility.Visible

    def selected_rule(self):
        index = self.s_rule_cb.SelectedIndex
        return RULE_LABELS[index][0] if index >= 0 else 'two_level'

    @guarded
    def drag_window(self, sender, args):
        if self.drawer.header_down(args):
            return
        try:
            self.DragMove()
        except Exception:
            pass

    @guarded
    def cancel_click(self, sender, args):
        self.Close()

    @guarded
    def apply_click(self, sender, args):
        values = dict(self.settings)
        values['round_up'] = str(self.w_round_tb.Text).strip()
        values['wall_type_blockwork'] = str(self.w_blk_tb.Text).strip()
        values['wall_type_firerated'] = str(self.w_fr_tb.Text).strip()

        values['slab_rule'] = self.selected_rule()
        values['slab_round_up'] = str(self.s_round_tb.Text).strip()
        values['slab_height_extra'] = str(self.s_heightextra_tb.Text).strip()
        values['slab_circular_round'] = str(self.s_diaround_tb.Text).strip()
        values['slab_group_gap'] = str(self.s_group_tb.Text).strip()
        values['slab_pipe_tray_gap'] = str(self.s_pipegap_tb.Text).strip()
        values['slab_group_angle'] = str(self.s_groupangle_tb.Text).strip()
        values['workset'] = self.selected_workset()
        values['slab_top_height_extra'] = \
            str(self.s_topheightextra_tb.Text).strip()

        core.write_settings(values)
        core.apply_settings(values)
        self.on_apply(values)
        self.Close()


# ---------------------------------------------------------------------------
# main window
# ---------------------------------------------------------------------------
# the order of the tabs in ui.xaml, as remembered in settings
TAB_NAMES = ['wall', 'slab', 'global']


class BWICWindow(forms.WPFWindow):
    def __init__(self, xaml_file):
        forms.WPFWindow.__init__(self, xaml_file, handle_esc=False)
        self.xaml_folder = op.dirname(xaml_file)
        try:
            self.version_tb.Text = 'v' + core.__version__
        except Exception:
            pass
        self.load_logo(op.join(self.xaml_folder, 'icon.png'))

        self.settings = core.read_settings()
        core.apply_settings(self.settings)

        self.load_level_params()
        self.load_datum()

        # the family cards: one per sub tab, all run the same way
        self.profiles = core.load_profiles()
        self.previews = {}
        self.param_cache = {}
        self.cards = {
            'wall': FamilyCard(self, 'wall', self.wr_family_cb,
                               self.wr_type_cb, self.wr_preview_img,
                               self.wr_noprev_tb, self.wr_famsum_tb),
            'wall_circ': FamilyCard(self, 'wall_circ', self.wc_family_cb,
                                    self.wc_type_cb, self.wc_preview_img,
                                    self.wc_noprev_tb, self.wc_famsum_tb),
            'slab_rect': FamilyCard(self, 'slab_rect', self.sr_family_cb,
                                    self.sr_type_cb, self.sr_preview_img,
                                    self.sr_noprev_tb, self.sr_famsum_tb),
            'slab_circ': FamilyCard(self, 'slab_circ', self.sc_family_cb,
                                    self.sc_type_cb, self.sc_preview_img,
                                    self.sc_noprev_tb, self.sc_famsum_tb),
        }
        self.reload_families()

        # every section folds away, and stays as it was left
        self.groups = [
            ('wr_family', self.grp_wr_family),
            ('wc_family', self.grp_wc_family), ('wc_size', self.grp_wc_size),
            ('wall_options', self.grp_wall_options),
            ('wall_help', self.grp_wall_help),
            ('sr_family', self.grp_sr_family),
            ('sc_family', self.grp_sc_family), ('sc_size', self.grp_sc_size),
            ('sa_families', self.grp_sa_families),
            ('sa_rules', self.grp_sa_rules),
            ('slab_setout', self.grp_slab_setout),
            ('slab_options', self.grp_slab_options),
            ('g_link', self.grp_g_link), ('g_sizes', self.grp_g_sizes),
            ('g_options', self.grp_g_options), ('g_help', self.grp_g_help),
        ]
        for key, expander in self.groups:
            saved = self.settings.get('group_' + key)
            if saved in ('open', 'closed'):
                expander.IsExpanded = (saved == 'open')

        self.load_shapes()
        self.restore_settings()
        self.show_slab_family()

        self.debug_cb.IsChecked = (self.settings.get('debug') == 'yes')
        self.debug_changed(None, None)

        # open on whichever tab was last used
        self.tabs.SelectedIndex = TAB_NAMES.index(
            self.settings.get('active_tab')) \
            if self.settings.get('active_tab') in TAB_NAMES else 0
        self.show_actions()
        self.tabs.SelectionChanged += self.tab_changed

        # the presentation source does not exist until the window is shown,
        # so the cap is applied once it is
        try:
            self.SourceInitialized += self.window_shown
        except Exception:
            self.cap_height()

        self.handler = PlacementHandler(self)
        self.ext_event = UI.ExternalEvent.Create(self.handler)

        self.drawer = drawer.Drawer(self, self.header_pnl, self.shrink_btn,
                                    grips=self.grips_grid)
        # parking the window mid-step moves the step card over Revit, and
        # opening it brings the card back under the buttons
        self.drawer.on_change = self.drawer_moved
        self.PreviewKeyDown += self.key_down
        self.dock_parts = PromptParts(
            self.pr_bd, self.pr_accent_bd, self.pr_eyebrow_tb, self.pr_dots_tb,
            self.pr_icon_tb, self.pr_title_tb, self.pr_detail_tb,
            self.pr_hint_bd, self.pr_hint_tb)

        # Global Placement: both external events are created here, on the UI
        # thread, as the Revit API requires
        self.prompt = None
        self.finish_ready = False
        # while a run is going, messages are logged rather than shown: the
        # step prompt is already saying what is happening
        self.running = False
        self.Closed += self.window_closed

        self.links = []
        self.results = None
        self.select_handler = SelectionHandler()
        self.select_event = UI.ExternalEvent.Create(self.select_handler)
        self.load_links()
        self.restore_global()


    # -- helpers -----------------------------------------------------------
    def window_shown(self, sender, args):
        self.cap_height()

    def cap_height(self):
        """Keep the auto sized window inside the screen it opens on."""
        try:
            from System.Windows.Forms import Screen
            area = Screen.PrimaryScreen.WorkingArea
            from System.Windows import PresentationSource
            scale = 1.0
            source = PresentationSource.FromVisual(self)
            if source is not None:
                scale = source.CompositionTarget.TransformToDevice.M22 or 1.0
            # leave the taskbar and a margin clear; past this the tab
            # contents scroll rather than running off the screen
            self.MaxHeight = max(360.0, (area.Height / scale) - 60.0)
        except Exception:
            logger.debug('could not read the screen size')

    def load_logo(self, image_path):
        for method in ('set_image_source_file', 'set_image_source'):
            try:
                getattr(self, method)(self.logo_img, image_path)
                return
            except Exception:
                continue
        # System.Uri moved assemblies in Revit 2025, so load from bytes
        try:
            from System.IO import File, MemoryStream
            from System.Windows.Media.Imaging import BitmapImage, \
                BitmapCacheOption
            image = BitmapImage()
            image.BeginInit()
            image.StreamSource = MemoryStream(File.ReadAllBytes(image_path))
            image.CacheOption = BitmapCacheOption.OnLoad
            image.EndInit()
            self.logo_img.Source = image
        except Exception:
            logger.debug('could not load the window icon')

    def load_level_params(self):
        names = []
        try:
            doc = HOST_APP.doc
            names = core.collect_parameter_names(doc,
                                                 core.find_family_symbol(doc))
        except Exception:
            logger.debug('could not read the family parameters')
            names = [core.LEVEL_PARAM_NAME]

        self.level_param_cb.Items.Clear()
        self.level_param_cb.Items.Add('<do not write a level code>')
        for name in names:
            self.level_param_cb.Items.Add(name)
        preferred = core.default_level_param(names)
        self.level_param_cb.SelectedIndex = \
            names.index(preferred) + 1 if preferred else 0

    def load_datum(self):
        self.slab_datum_cb.Items.Clear()
        for _, label in DATUM_LABELS:
            self.slab_datum_cb.Items.Add(label)
        wanted = self.settings.get('slab_datum', 'soffit')
        self.slab_datum_cb.SelectedIndex = \
            next((i for i, (key, _) in enumerate(DATUM_LABELS)
                  if key == wanted), 0)
        self.slab_datum_cb.SelectionChanged += self.datum_changed
        self.datum_changed(None, None)

    def selected_datum(self):
        index = self.slab_datum_cb.SelectedIndex
        return DATUM_LABELS[index][0] if index >= 0 else 'soffit'

    @guarded
    def datum_changed(self, sender, args):
        labels = {'soffit': 'soffit -', 'top': 'top +',
                  'level': 'level + depth +'}
        self.slab_base_lbl.Text = labels.get(self.selected_datum(), 'soffit -')

    def restore_settings(self):
        get = self.settings.get
        if get('wall_circ_round'):
            self.wc_round_tb.Text = get('wall_circ_round')
        self.wc_insul_cb.IsChecked = \
            (get('wall_circ_insulation', 'yes') != 'no')
        self.wall_round_changed(None, None)
        self.update_place_label()
        if get('slab_circular_round'):
            self.slab_gapround_tb.Text = get('slab_circular_round')
        self.slab_insul_cb.IsChecked = \
            (get('slab_circular_insulation', 'yes') != 'no')
        if get('slab_base_extra'):
            self.slab_base_tb.Text = get('slab_base_extra')
        if get('slab_top_extra'):
            self.slab_top_tb.Text = get('slab_top_extra')

        param = get('level_param')
        if param:
            for index in range(self.level_param_cb.Items.Count):
                if str(self.level_param_cb.Items[index]) == param:
                    self.level_param_cb.SelectedIndex = index
                    break
        if get('include_linked') == 'yes':
            self.linked_cb.IsChecked = True

    def show_slab_family(self):
        """Say how the Automatic tab splits services."""
        self.slab_shape_tb.Text = (
            'Pipes and conduit on their own get a round hole each. Trays and '
            'ducts within {} mm of each other, and pointing the same way, '
            'share one rectangular opening, and a pipe within {} mm of one '
            'joins it.'.format(self.settings.get('slab_group_gap', '100'),
                               self.settings.get('slab_pipe_tray_gap', '150')))
        self.slab_size_changed(None, None)

        rule = self.settings.get('slab_rule', 'two_level')
        if rule == 'single_level':
            height = self.settings.get('slab_height_param') or 'not set'
            self.slab_rule_tb.Text = (
                'Single level rule - placed on the nearest level, vertical '
                'height "{}" set to the floor thickness.'.format(height))
        else:
            self.slab_rule_tb.Text = (
                'Two levels rule - Base Level and Top Level with offsets.')

    def load_shapes(self):
        """Open each tab on the shape it was last used with."""
        wall = self.settings.get('wall_shape', 'rectangular')
        self.wall_shape_tabs.SelectedIndex = WALL_SHAPES.index(wall) \
            if wall in WALL_SHAPES else 0
        method = self.settings.get('slab_method', 'rectangular')
        self.slab_shape_tabs.SelectedIndex = SLAB_METHODS.index(method) \
            if method in SLAB_METHODS else 0

    def selected_method(self):
        index = self.slab_shape_tabs.SelectedIndex
        return SLAB_METHODS[index] if 0 <= index < len(SLAB_METHODS) \
            else 'rectangular'

    def selected_wall_shape(self):
        index = self.wall_shape_tabs.SelectedIndex
        return WALL_SHAPES[index] if 0 <= index < len(WALL_SHAPES) \
            else 'rectangular'

    @guarded
    def slab_shape_changed(self, sender, args):
        # wired in the XAML, so it fires while the window is still loading,
        # before there are any settings to write to
        if getattr(self, 'cards', None) is None:
            return
        # SelectionChanged bubbles: a family list inside the tab fires it too
        if args is None or args.OriginalSource is not self.slab_shape_tabs:
            return
        self.settings['slab_method'] = self.selected_method()
        core.write_settings(self.settings)
        self.show_slab_family()

    @guarded
    def wall_shape_changed(self, sender, args):
        # wired in the XAML, so it fires while the window is still loading,
        # before there are any settings to write to
        if getattr(self, 'cards', None) is None:
            return
        # SelectionChanged bubbles: a family list inside the tab fires it too
        if args is None or args.OriginalSource is not self.wall_shape_tabs:
            return
        self.settings['wall_shape'] = self.selected_wall_shape()
        core.write_settings(self.settings)
        self.update_place_label()

    def update_place_label(self):
        round_wall = self.selected_wall_shape() == 'circular'
        self.place_btn.Content = 'Place Circular BWIC' if round_wall \
            else 'Place BWIC'

    # -- families --------------------------------------------------------------
    def reload_families(self):
        """Read the project's generic model families into every card."""
        try:
            families = core.generic_model_families(HOST_APP.doc, None)
        except Exception:
            logger.debug('could not read the generic model families')
            families = []
        # rectangular lists offer rectangular families only, circular lists
        # circular ones: a Diameter or Radius parameter makes a family round
        try:
            shapes = core.family_shapes(HOST_APP.doc)
        except Exception:
            logger.debug('could not sort the families by shape')
            shapes = {}
        for card in self.cards.values():
            card.fill(fam.families_for_slot(card.slot, families, shapes),
                      families)
        self.show_auto_families()

    def preview(self, family, type_name):
        if not family:
            return None
        key = (family, type_name or None)
        if key not in self.previews:
            try:
                self.previews[key] = bitmap_to_image(core.family_preview(
                    HOST_APP.doc, family, type_name or None))
            except Exception:
                self.previews[key] = None
        return self.previews[key]

    def family_params(self, family):
        """(length names, all names, placed?) for a family, read once."""
        if family not in self.param_cache:
            doc = HOST_APP.doc
            try:
                lengths = core.family_parameter_names(doc, family)
                every = core.family_parameter_names(doc, family,
                                                    lengths_only=False)
                placed = core.family_is_placed(doc, family)
            except Exception:
                lengths, every, placed = [], [], False
            self.param_cache[family] = (lengths, every, placed)
        return self.param_cache[family]

    def family_choice_changed(self, slot):
        if slot in ('slab_rect', 'slab_circ'):
            self.show_auto_families()
            self.show_slab_family()

    def show_auto_families(self):
        """The Automatic tab names both families it will use."""
        for slot, image_box, text in (
                ('slab_rect', self.sa_rect_img, self.sa_rect_tb),
                ('slab_circ', self.sa_circ_img, self.sa_circ_tb)):
            card = self.cards[slot]
            family = card.family()
            image_box.Source = self.preview(family, card.type_name())
            text.Text = '{}{}'.format(
                family, ' : ' + card.type_name() if card.type_name() else '') \
                if family else 'None chosen - pick one on its tab'

    def open_family_settings(self, slot):
        card = self.cards[slot]
        family = card.family()
        if not family:
            self.report('Pick a family first.')
            return
        lengths, every, placed = self.family_params(family)
        profile = self.profiles.get(family) or fam.seed_profile(
            slot, self.settings, lengths, every)
        dialog = FamilySettingsWindow(
            op.join(self.xaml_folder, 'family_settings.xaml'),
            slot, family, profile, lengths, every, placed,
            self.preview(family, card.type_name()), self.drawer,
            self.profile_saved, self.model_worksets(),
            self.workset_name())
        dialog.Owner = self
        dialog.WindowStartupLocation = WindowStartupLocation.CenterOwner
        dialog.ShowDialog()

    # -- Family settings first -------------------------------------------------
    def slots_for(self, mode):
        """The family slots a run needs set up before it may start. A resize
        sizes the BWIC picked by its own family, so it needs at least one
        family set up; the pick only accepts those."""
        if mode == 'place':
            return ['wall_circ'] if self.selected_wall_shape() == 'circular' \
                else ['wall']
        if mode == 'slab':
            method = self.selected_method()
            return {'rectangular': ['slab_rect'], 'circular': ['slab_circ'],
                    'auto': ['slab_rect', 'slab_circ']}.get(method,
                                                            ['slab_rect'])
        if mode == 'global':
            return ['wall']
        return []

    def blocked_by_family_settings(self, mode):
        self.profiles = core.load_profiles()
        if mode in ('resize', 'slab_resize'):
            if self.profiles:
                return False
            self.block_prompt(
                'No family has its Family settings saved yet. Set up the '
                'family of the BWIC to resize: Family settings… on its '
                'family card, then Save.')
            return True
        missing = [(slot, self.cards[slot].family())
                   for slot in self.slots_for(mode)
                   if not fam.is_set(self.cards[slot].family(), self.profiles)]
        if not missing:
            return False
        labels = {'wall': 'Wall - Rectangular', 'wall_circ': 'Wall - Circular',
                  'slab_rect': 'Slab - Rectangular',
                  'slab_circ': 'Slab - Circular'}
        names = '; '.join(
            u'"{}" on {}'.format(family, labels[slot]) if family
            else u'no family chosen on {}'.format(labels[slot])
            for slot, family in missing)
        self.block_prompt(
            u'Set up Family settings first: {}. Press Family settings… on '
            u'the family card, check the parameters and clearance, then '
            u'Save.'.format(names))
        return True

    def block_prompt(self, detail):
        core.debug('run blocked: ' + detail)
        self.on_guide('blocked', {'title': 'Family settings needed',
                                  'detail': detail})

    def model_worksets(self):
        """Workset names for the Family settings list; none if the model
        is not workshared."""
        try:
            return [w.Name for w in core.list_worksets(HOST_APP.doc)]
        except Exception:
            logger.debug('could not read the worksets')
            return []

    def profile_saved(self, slot, family, profile):
        self.profiles[family] = profile
        try:
            fam.save(core.PROFILES_PATH, self.profiles)
        except Exception as err:
            self.report('Family settings could not be saved: {}'.format(err))
            return
        # set-up families go green and to the top of the lists
        self.reload_families()
        try:
            core.apply_settings(self.settings)
        except Exception:
            pass
        self.report('Family settings saved for "{}".'.format(family))

    @guarded
    def wr_famset_click(self, sender, args):
        self.open_family_settings('wall')

    @guarded
    def wc_famset_click(self, sender, args):
        self.open_family_settings('wall_circ')

    @guarded
    def sr_famset_click(self, sender, args):
        self.open_family_settings('slab_rect')

    @guarded
    def sc_famset_click(self, sender, args):
        self.open_family_settings('slab_circ')

    # -- circular wall -----------------------------------------------------------
    @guarded
    def wall_round_changed(self, sender, args):
        """Spell out the round hole the numbers give, as the slab tab does."""
        if getattr(self, 'cards', None) is None:
            return
        # the circular family's own clearance, 50 until it is set
        gap = fam.clearance_for(getattr(self, 'settings', {}).get(
                                    'wall_circ_family'),
                                getattr(self, 'profiles', {}))
        try:
            step = float(str(self.wc_round_tb.Text).strip() or 0)
        except ValueError:
            self.wc_example_tb.Text = 'Round up to must be a number, in mm.'
            return
        pipe = fam.round_hole_mm(114.3, 0, 0, gap, step)
        group = fam.round_hole_mm(None, 300, 100, gap, step)
        self.wc_example_tb.Text = (
            'DN100 steel (114.3 mm outside) gets a {:.0f} mm hole. A 300 x '
            '100 tray gets {:.0f} mm, the circle around its corners plus the '
            'clearance ({:g} mm, from Family settings).'.format(pipe, group,
                                                               gap))

    def round_spec(self):
        """The Circular tab's gap and round-up, without complaining: used only
        when a resize turns out to have picked a round BWIC."""
        def number(box, default):
            try:
                return float(str(box.Text).strip())
            except ValueError:
                return default
        return {'gap_mm': fam.DEFAULT_CLEARANCE_MM,
                'round_mm': number(self.wc_round_tb, 10.0),
                'insulation': bool(self.wc_insul_cb.IsChecked)}

    def round_wall_options(self):
        """What a circular wall run needs, from the circular family's own
        settings, or None with a reason when it cannot run."""
        values = core.family_settings(self.settings, 'wall_circ')
        family = values.get('wall_circ_family') or ''
        if not family:
            return None, 'Pick a circular family on the Wall tab first.'
        # the gap is the family's own clearance: the core asks the family
        gap = fam.DEFAULT_CLEARANCE_MM
        step = self.read_number(self.wc_round_tb, 'Round up to')
        if step is None:
            return None, None
        return {'family': family,
                'type': values.get('wall_circ_type') or '',
                'through': values.get('wall_circ_length_param') or '',
                'diameter': values.get('wall_circ_diameter_param') or '',
                'radius': values.get('wall_circ_radius') == 'yes',
                'gap_mm': gap, 'round_mm': step,
                'insulation': bool(self.wc_insul_cb.IsChecked)}, None

    def workset_name(self):
        """The workset chosen in Settings, or None for the active one."""
        return self.settings.get('workset') or None

    def selected_level_param(self):
        value = self.level_param_cb.SelectedItem
        if value is None or str(value).startswith('<'):
            return None
        return str(value)

    def save_settings(self):
        self.settings['wall_shape'] = self.selected_wall_shape()
        self.settings['wall_circ_round'] = str(self.wc_round_tb.Text).strip()
        self.settings['wall_circ_insulation'] = \
            'yes' if self.wc_insul_cb.IsChecked else 'no'
        for key, expander in self.groups:
            self.settings['group_' + key] = \
                'open' if expander.IsExpanded else 'closed'
        self.settings['level_param'] = self.selected_level_param() or ''
        self.settings['include_linked'] = \
            'yes' if self.linked_cb.IsChecked else 'no'
        self.settings['slab_base_extra'] = str(self.slab_base_tb.Text).strip()
        self.settings['slab_top_extra'] = str(self.slab_top_tb.Text).strip()
        self.settings['slab_datum'] = self.selected_datum()
        self.settings['slab_method'] = self.selected_method()
        self.settings['slab_circular_round'] = \
            str(self.slab_gapround_tb.Text).strip()
        self.settings['slab_circular_insulation'] = \
            'yes' if self.slab_insul_cb.IsChecked else 'no'
        self.settings['global_gap_pipes'] = \
            str(self.g_gap_pipes_tb.Text).strip()
        self.settings['global_gap_trays'] = \
            str(self.g_gap_trays_tb.Text).strip()
        self.settings['global_comments'] = \
            'yes' if self.g_comments_cb.IsChecked else 'no'
        self.settings['global_workset'] = \
            'yes' if self.g_workset_cb.IsChecked else 'no'
        link = self.selected_link()
        if link is not None:
            self.settings['global_link'] = link[1]
        core.write_settings(self.settings)

    def report(self, message):
        """Say something to the user. There is no status box any more: while
        a run is going the step prompt already says what is happening, so the
        message is logged; otherwise it shows briefly as a note on the prompt.
        """
        logger.debug(message)
        try:
            core.debug('status: {}'.format(message))
        except Exception:
            pass
        if getattr(self, 'running', False) or not message:
            return
        try:
            self.on_guide('note', {'detail': message})
        except Exception:
            pass

    def on_guide(self, event, details):
        """Where a manual run has got to, from the core, for the prompt."""
        self.arm_finish(steps.finish_armed(event, details,
                                           self.finish_ready))
        if self.prompt is None:
            self.prompt = StepPrompt(op.join(self.xaml_folder, 'prompt.xaml'),
                                     self)
        self.prompt.handle(event, details)

    # -- Finish Selection ------------------------------------------------------
    def arm_finish(self, ready):
        self.finish_ready = bool(ready)
        self.finish_btn.IsEnabled = self.finish_ready
        self.finish_btn.Tag = 'ready' if self.finish_ready else ''

    @guarded
    def finish_click(self, sender, args):
        # pressed once per step: Return a second time would repeat Revit's
        # last command once the selection has finished
        if not self.finish_ready:
            return
        self.arm_finish(False)
        if not core.press_finish():
            self.arm_finish(True)

    # -- the step card under the buttons -------------------------------------
    def show_docked_prompt(self, look):
        draw_card(self.dock_parts, self.FindResource, look)
        self.pr_bd.Visibility = Visibility.Visible

    def hide_docked_prompt(self):
        self.pr_bd.Visibility = Visibility.Collapsed

    def drawer_moved(self, heading):
        if self.prompt is not None:
            self.prompt.refresh()

    def window_closed(self, sender, args):
        core.set_guide(None)
        if self.prompt is not None:
            self.prompt.shut()
            self.prompt = None

    def finish(self):
        self.running = False
        self.arm_finish(False)
        # a run that ended any way at all -- Esc, an error, a closed document
        # -- must not leave the prompt on screen
        if self.prompt is not None:
            self.prompt.handle('done', {})
        for button in (self.place_btn, self.resize_btn, self.slab_place_btn,
                       self.slab_resize_btn, self.g_run_btn):
            button.IsEnabled = True
        self.Focusable = True
        try:
            self.Activate()
        except Exception:
            pass

    def read_number(self, textbox, label):
        try:
            value = float(str(textbox.Text).strip())
        except ValueError:
            self.report('{} must be a number, in mm.'.format(label))
            return None
        if value < 0:
            self.report('{} cannot be negative.'.format(label))
            return None
        return value

    # -- events ------------------------------------------------------------
    @guarded
    def place_click(self, sender, args):
        self.start_run('place')

    @guarded
    def resize_click(self, sender, args):
        self.start_run('resize')

    @guarded
    def slab_place_click(self, sender, args):
        self.start_run('slab')

    @guarded
    def slab_resize_click(self, sender, args):
        self.start_run('slab_resize')

    def start_run(self, mode):
        # nothing runs on a family whose Family settings have not been saved
        if self.blocked_by_family_settings(mode):
            return
        if mode in ('slab', 'slab_resize'):
            # which family is needed depends on the method, so checking the
            # rectangular one alone turned the button into a dead button for
            # anyone using only a circular family
            method = self.selected_method()
            rect = self.settings.get('slab_family')
            circ = self.settings.get('slab_circ_family')
            if method == 'circular' and not circ and not rect:
                self.report('Choose a circular family in Settings first.')
                return
            if method == 'rectangular' and not rect:
                self.report('Choose a rectangular family in Settings first.')
                return
            if method == 'auto' and not rect and not circ:
                self.report('Choose a family in Settings first - the '
                            'rectangular one for trays and ducts, the '
                            'circular one for pipes.')
                return
            if method == 'auto' and not circ:
                self.report('No circular family set, so pipes on their own '
                            'will be skipped. Set one in Settings.')
            checks = [(self.slab_base_tb, 'Base offset'),
                      (self.slab_top_tb, 'Top offset')]
            if self.selected_method() in ('auto', 'circular'):
                checks += [(self.slab_gapround_tb, 'Round up')]
            for textbox, label in checks:
                if self.read_number(textbox, label) is None:
                    return
            self.handler.options = {
                'log_comments': bool(self.slab_comments_cb.IsChecked),
                'workset_name': self.workset_name(),
                'include_linked': bool(self.slab_linked_cb.IsChecked),
                'pin': bool(self.slab_pin_cb.IsChecked),
                'level_param': self.selected_level_param()}
            settings = dict(self.settings)
            settings['slab_base_extra'] = str(self.slab_base_tb.Text).strip()
            settings['slab_top_extra'] = str(self.slab_top_tb.Text).strip()
            settings['slab_datum'] = self.selected_datum()
            settings['slab_method'] = self.selected_method()
            settings['slab_circular_round'] = \
                str(self.slab_gapround_tb.Text).strip()
            settings['slab_circular_insulation'] = \
                'yes' if self.slab_insul_cb.IsChecked else 'no'
            self.handler.settings = settings
            if mode == 'slab_resize':
                message = ('Working in Revit - pick the opening, then the '
                           'services and press Return, then the floor. '
                           'Esc returns here.')
            else:
                message = ('Working in Revit - select the services and press '
                           'Return, then click the floor. Esc returns here.')
        elif mode == 'global':
            numbers = []
            for textbox, label in ((self.g_gap_pipes_tb,
                                    'Pipe grouping distance'),
                                   (self.g_gap_trays_tb,
                                    'Tray grouping distance')):
                value = self.read_number(textbox, label)
                if value is None:
                    return
                numbers.append(value)
            link = self.selected_link()
            if link is None:
                self.report('There is no loaded link to read the walls from.')
                return
            self.handler.global_settings = {
                'link_id': link[0].Id,
                # the wall family's own clearance, from Family settings
                'clearance_mm': fam.DEFAULT_CLEARANCE_MM,
                'gap_pipes_mm': numbers[0],
                'gap_trays_mm': numbers[1],
                'log_comments': bool(self.g_comments_cb.IsChecked),
                'use_workset': bool(self.g_workset_cb.IsChecked),
                'level_param': self.selected_level_param()}
            self.handler.settings = dict(self.settings)
            message = ('Working through the active view - the window will '
                       'not redraw until the sweep finishes.')
        else:
            # the family's own clearance, from Family settings
            clearance = fam.DEFAULT_CLEARANCE_MM
            round_wall = None
            if self.selected_wall_shape() == 'circular':
                round_wall, problem = self.round_wall_options()
                if round_wall is None:
                    if problem:
                        self.report(problem)
                    return
            # the family and type chosen on the tab take effect now
            core.apply_settings(self.settings)
            self.handler.clearance_mm = clearance
            self.handler.options = {
                'log_comments': bool(self.comments_cb.IsChecked),
                'workset_name': self.workset_name(),
                'include_linked': bool(self.linked_cb.IsChecked),
                'pin': bool(self.pin_cb.IsChecked),
                'level_param': self.selected_level_param(),
                'round_wall': round_wall,
                # a resize can pick a round BWIC from either tab, so the round
                # figures always go along
                'round_spec': self.round_spec()}
            if mode == 'resize':
                message = ('Working in Revit - pick the BWIC, then the '
                           'services and press Return, then the wall. '
                           'Esc returns here.')
            else:
                message = ('Working in Revit - select the services and press '
                           'Return, then pick the wall. Esc returns here.')

        self.save_settings()
        self.handler.mode = mode
        for button in (self.place_btn, self.resize_btn, self.slab_place_btn,
                       self.slab_resize_btn, self.g_run_btn):
            button.IsEnabled = False
        self.running = True
        self.report(message)
        # stop the window taking keyboard focus while Revit is picking, so
        # Return reaches Revit and finishes the selection
        self.Focusable = False
        # manual runs walk the user through each pick; the global sweep has
        # nothing to pick, so it gets no prompt
        core.set_guide(None if mode == 'global' else self.on_guide)
        self.ext_event.Raise()
        core.focus_revit()

    @guarded
    def settings_click(self, sender, args):
        # opening Settings beside a parked bar would put it in the wrong place
        self.drawer.restore_now()
        try:
            window = SettingsWindow(op.join(self.xaml_folder, 'settings.xaml'),
                                    self.settings, self.settings_applied,
                                    lift=self.drawer)
            window.place_beside(self)
            window.ShowDialog()
        except Exception as err:
            logger.error(err)
            self.report('Could not open Settings: {}'.format(err))

    def settings_applied(self, values):
        self.settings = values
        self.load_level_params()
        self.restore_settings()
        self.show_slab_family()
        self.report('Settings saved.')

    @guarded
    def drag_window(self, sender, args):
        if self.drawer.header_down(args):
            return
        try:
            self.DragMove()
        except Exception:
            pass

    @guarded
    def shrink_click(self, sender, args):
        self.drawer.toggle()

    @guarded
    def key_down(self, sender, args):
        self.drawer.handle_key(args)

    # -- resize grips ------------------------------------------------------
    # A borderless AllowsTransparency window has nothing hit testable in its
    # frame, so WPF cannot resize it however ResizeMode is set. These handlers
    # are the frame. Each clamps at the minimum rather than letting the window
    # turn inside out.
    def _widen(self, change, from_left):
        if from_left:
            new = self.Width - change
            if new < self.MinWidth:
                return
            self.Left += change
            self.Width = new
        else:
            new = self.Width + change
            if new >= self.MinWidth:
                self.Width = new

    def _heighten(self, change, from_top):
        # the window sizes itself to its content until the user takes over
        try:
            if self.SizeToContent != SizeToContent.Manual:
                self.SizeToContent = SizeToContent.Manual
        except Exception:
            pass
        if from_top:
            new = self.Height - change
            if new < self.MinHeight:
                return
            self.Top += change
            self.Height = new
        else:
            new = self.Height + change
            if new >= self.MinHeight:
                self.Height = new

    @guarded
    def grip_n_drag(self, sender, args):
        self._heighten(args.VerticalChange, True)

    @guarded
    def grip_s_drag(self, sender, args):
        self._heighten(args.VerticalChange, False)

    @guarded
    def grip_w_drag(self, sender, args):
        self._widen(args.HorizontalChange, True)

    @guarded
    def grip_e_drag(self, sender, args):
        self._widen(args.HorizontalChange, False)

    @guarded
    def grip_nw_drag(self, sender, args):
        self._widen(args.HorizontalChange, True)
        self._heighten(args.VerticalChange, True)

    @guarded
    def grip_ne_drag(self, sender, args):
        self._widen(args.HorizontalChange, False)
        self._heighten(args.VerticalChange, True)

    @guarded
    def grip_sw_drag(self, sender, args):
        self._widen(args.HorizontalChange, True)
        self._heighten(args.VerticalChange, False)

    @guarded
    def grip_se_drag(self, sender, args):
        self._widen(args.HorizontalChange, False)
        self._heighten(args.VerticalChange, False)

    @guarded
    def debug_changed(self, sender, args):
        # one tick box per tab, all the same setting: the one clicked decides
        boxes = (self.debug_cb, self.slab_debug_cb, self.g_debug_cb)
        on = bool(sender.IsChecked) if sender in boxes \
            else bool(self.debug_cb.IsChecked)
        for box in boxes:
            box.IsChecked = on
        core.set_debug(on)
        self.settings['debug'] = 'yes' if on else 'no'
        if sender is not None:
            core.write_settings(self.settings)
            self.report('Debug logging {}. Log: {}'.format(
                'on' if on else 'off', core.DEBUG_PATH) if on
                else 'Debug logging off.')

    @guarded
    def debug_open_click(self, sender, args):
        import os
        path = core.DEBUG_PATH
        if not op.isfile(path):
            self.report('Nothing logged yet - run the tool with Debug ticked.')
            return
        try:
            os.startfile(path)
        except Exception:
            self.report('Log is at {}'.format(path))

    @guarded
    def debug_clear_click(self, sender, args):
        core.clear_debug()
        self.report('Debug log cleared.')

    @guarded
    def slab_size_changed(self, sender, args):
        """Spell out what the numbers will actually do.

        The gap is a clearance all round, so the hole comes out twice the gap
        bigger than the service -- worth showing rather than leaving to be
        discovered.
        """
        # TextChanged fires while the XAML is still loading
        if not hasattr(self, 'slab_gap_example'):
            return
        # the circular family's own clearance, 50 until it is set
        gap = fam.clearance_for(getattr(self, 'settings', {}).get(
                                    'slab_circ_family'),
                                getattr(self, 'profiles', {}))
        try:
            step = float(str(self.slab_gapround_tb.Text).strip() or 0)
        except ValueError:
            self.slab_gap_example.Text = 'Round up to must be a number, in mm.'
            return
        # a DN100 steel pipe, because its nominal size and its outside
        # diameter differ -- which is the whole point
        example = 114.3
        raw = example + 2 * gap
        if step > 0:
            raw = math.ceil(raw / step - 1e-9) * step
        self.slab_gap_example.Text = (
            'DN100 steel is 114.3 mm outside, so it gets a {:.0f} mm hole '
            '(114.3 + 2 x {:.0f}, rounded up). Its nominal size of 100 would '
            'have given a smaller one.'.format(raw, gap))

    # -- Global Placement ----------------------------------------------------
    def load_links(self):
        """Fill the link list: the remembered one, then the hinted, then any."""
        self.g_link_cb.Items.Clear()
        self.links = []
        selected = None
        try:
            uidoc = HOST_APP.uidoc
            self.links = gp.loaded_links(uidoc.Document)
            selected = gp.preselected_link(uidoc)
        except Exception:
            logger.debug('could not read the links in this model')

        if not self.links:
            self.g_link_cb.Items.Add('<no loaded links in this model>')
            self.g_link_cb.SelectedIndex = 0
            self.g_link_cb.IsEnabled = False
            return

        remembered = self.settings.get('global_link')
        picks = {'selected': None, 'remembered': None, 'hint': None}
        for position, pair in enumerate(self.links):
            self.g_link_cb.Items.Add(pair[1])
            if selected is not None and pair[0].Id == selected.Id \
                    and picks['selected'] is None:
                picks['selected'] = position
            if remembered and pair[1] == remembered \
                    and picks['remembered'] is None:
                picks['remembered'] = position
            if gp.LINK_NAME_HINT.lower() in pair[1].lower() \
                    and picks['hint'] is None:
                picks['hint'] = position
        # a link picked in the model wins, then last time's, then the hint
        index = next((picks[k] for k in ('selected', 'remembered', 'hint')
                      if picks[k] is not None), 0)
        self.g_link_cb.IsEnabled = True
        self.g_link_cb.SelectedIndex = index

    def selected_link(self):
        """(link instance, name) chosen in the list, or None."""
        position = self.g_link_cb.SelectedIndex
        if not self.links or position < 0 or position >= len(self.links):
            return None
        return self.links[position]

    def restore_global(self):
        get = self.settings.get
        self.g_gap_pipes_tb.Text = get('global_gap_pipes') or \
            '{:.0f}'.format(gp.DEFAULT_GAP_PIPES_MM)
        self.g_gap_trays_tb.Text = get('global_gap_trays') or \
            '{:.0f}'.format(gp.DEFAULT_GAP_TRAYS_MM)
        self.g_comments_cb.IsChecked = (get('global_comments', 'yes') != 'no')
        self.g_workset_cb.IsChecked = (get('global_workset', 'yes') != 'no')

    def show_results(self, summary):
        """The results window: modeless, and only ever one of it."""
        try:
            if self.results is not None:
                try:
                    self.results.Close()
                except Exception:
                    pass
            # held on this window so it is not collected while open
            self.results = ResultsWindow(
                op.join(self.xaml_folder, 'results.xaml'), summary,
                self.select_event, self.select_handler)
            self.results.show(modal=False)
        except Exception as err:
            logger.error('results window failed: {}'.format(err))
            core.debug('results window failed\n{}'.format(
                traceback.format_exc()))

    @guarded
    def global_run_click(self, sender, args):
        self.start_run('global')

    @guarded
    def global_refresh_click(self, sender, args):
        self.load_links()
        self.report('Links re-read from the model.')

    def tab_changed(self, sender, args):
        # every list and sub tab inside a tab bubbles its SelectionChanged up
        # to here; only the main tabs themselves count
        if args is not None and args.OriginalSource is not self.tabs:
            return
        try:
            self.show_actions()
            index = self.tabs.SelectedIndex
            self.settings['active_tab'] = TAB_NAMES[index] \
                if 0 <= index < len(TAB_NAMES) else 'wall'
            core.write_settings(self.settings)
        except Exception:
            pass

    def show_actions(self):
        """Only the current tab's buttons are shown.

        They sit below the tab control rather than inside it, so however long
        a tab's contents grow they can never push the buttons off the bottom.
        """
        index = self.tabs.SelectedIndex
        for position, panel in enumerate((self.wall_actions,
                                          self.slab_actions,
                                          self.global_actions)):
            panel.Visibility = Visibility.Visible if position == index \
                else Visibility.Collapsed
        # Global Placement has nothing to select
        self.finish_btn.Visibility = Visibility.Collapsed if index == 2 \
            else Visibility.Visible

    @guarded
    def topmost_changed(self, sender, args):
        self.Topmost = bool(self.topmost_cb.IsChecked)

    @guarded
    def close_click(self, sender, args):
        self.Close()


BWICWindow(op.join(HERE, 'ui.xaml')).show(modal=False)
