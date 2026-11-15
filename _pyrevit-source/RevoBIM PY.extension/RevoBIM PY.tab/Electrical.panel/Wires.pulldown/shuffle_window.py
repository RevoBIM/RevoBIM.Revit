# -*- coding: utf-8 -*-
"""RevoBIM PY - Wires: the Shuffle prompt.

Small, parked in the bottom right so the run it just drew is visible behind
it, and floating by default so the view can be panned and zoomed while a route
is being judged.

Two paths, chosen by the `modeless_shuffle` setting.

**Modeless** shows the window and returns. Revit is back at idle, so nothing
the window does can touch the document directly - every redraw is handed to an
ExternalEvent, and the command script sets __persistentengine__ so pyRevit does
not tear the engine down and take these handlers with it.

**Modal** blocks Revit behind the window, but a modal window shown from inside
a command is still in the command's own API context, so its buttons open
transactions directly and none of the above is needed. It is the fallback if
the floating window misbehaves.
"""

import clr

for _asm in ('PresentationCore', 'PresentationFramework', 'WindowsBase'):
    try:
        clr.AddReference(_asm)
    except Exception:
        pass

from System.Windows.Controls import Slider, Control
from System.Windows.Input import MouseButtonEventHandler

import wires_core as core
import wires_ui as ui

# Floating windows, kept referenced for as long as they are open. Without this
# nothing holds them and they are collected out from under the user.
_LIVE = []


def show(session, headline, title='Auto Wire'):
    """Hold the prompt open.

    Modal: returns True where the route was kept. Modeless: returns None, the
    window lives on, and the session is finished by its own buttons.
    """
    try:
        window = ui.load_window('WiresShuffle.xaml')
    except Exception:
        session.keep()
        return True

    ui.dress_header(window, core.__version__)
    ui.owned_by_revit(window)
    ui.park_bottom_right(window)

    state = {'kept': False, 'busy': False, 'done': False, 'bridge': None}

    def _set_controls():
        try:
            label = window.FindName('ClashText')
            if label is not None:
                if not session.avoiding():
                    label.Text = 'Off - the shortest route wins, whatever it ' \
                                 'crosses.'
                elif session.clashing:
                    label.Text = '{0} span(s) still cross a fitting on ' \
                                 'another circuit. Shuffle may find a route ' \
                                 'that does not.'.format(session.clashing)
                else:
                    label.Text = 'This route crosses nothing.'
        except Exception:
            pass
        try:
            label = window.FindName('VertexCount')
            if label is not None:
                label.Text = str(session.vertices())
        except Exception:
            pass
        try:
            down = window.FindName('VertexDown')
            if down is not None:
                down.IsEnabled = session.vertices() > core.MIN_VERTICES
            up = window.FindName('VertexUp')
            if up is not None:
                up.IsEnabled = session.vertices() < core.MAX_VERTICES
        except Exception:
            pass
        # the segmented arc / chamfer pair: the active one lit blue
        for name, kind in (('ArcButton', 'arc'), ('ChamferButton', 'chamfer')):
            try:
                button = window.FindName(name)
                if button is None:
                    continue
                if session.wiring() == kind:
                    ui.paint(button, Control.BackgroundProperty, 'Blue')
                    ui.paint(button, Control.ForegroundProperty, 'OnBlue')
                else:
                    # back to the Segment style's own field and muted text
                    button.ClearValue(Control.BackgroundProperty)
                    button.ClearValue(Control.ForegroundProperty)
            except Exception:
                pass
        try:
            label = window.FindName('OffsetValue')
            if label is not None:
                if session.sag_mode() == 'paper':
                    label.Text = '{0:g}mm on paper'.format(session.sag())
                else:
                    label.Text = '{0:g}% of the span'.format(session.sag())
        except Exception:
            pass

    def _set_text():
        try:
            label = window.FindName('HeadlineText')
            if label is not None:
                label.Text = headline
        except Exception:
            pass
        try:
            label = window.FindName('RouteText')
            if label is not None:
                label.Text = 'Route {0} of {1}.'.format(
                    (session.variant % max(1, session.alternatives)) + 1,
                    max(1, session.alternatives))
        except Exception:
            pass

    try:
        name = window.FindName('ToolName')
        if name is not None:
            name.Text = title
    except Exception:
        pass
    _set_text()
    try:
        slider = window.FindName('OffsetSlider')
        if slider is not None:
            # the slider drives whichever unit the arc depth is set in
            if session.sag_mode() == 'paper':
                slider.Maximum = 20
                slider.TickFrequency = 0.5
            else:
                slider.Maximum = 45
                slider.TickFrequency = 1
            slider.Value = min(slider.Maximum, session.sag())
    except Exception:
        pass
    _set_controls()

    def _step(sender, move):
        """Redraw at another route, through the same guarded path."""
        _redraw(move)

    def _on_shuffle(sender, args):
        _step(sender, session.shuffle)

    def _on_previous(sender, args):
        _step(sender, session.previous)

    def _redraw(work):
        """Every live control redraws the run, so they all have to be
        re-entrancy guarded - a repeat button auto-repeats faster than a
        transaction commits.

        Modeless, the work is handed to the ExternalEvent and the controls are
        refreshed when it comes back; modal, it runs here and now.
        """
        if state['busy'] or state['done']:
            return
        bridge = state['bridge']
        if bridge is not None:
            state['busy'] = True

            def _after():
                state['busy'] = False
                _set_controls()
                _set_text()

            if not bridge.run(lambda uiapp: work(), _after):
                state['busy'] = False
            return
        state['busy'] = True
        try:
            work()
            _set_controls()
            _set_text()
        except Exception:
            pass
        finally:
            state['busy'] = False

    def _on_vertex_up(sender, args):
        _redraw(lambda: session.set_vertices(session.vertices() + 1))

    def _on_vertex_down(sender, args):
        _redraw(lambda: session.set_vertices(session.vertices() - 1))

    def _on_arc(sender, args):
        if session.wiring() != 'arc':
            _redraw(lambda: session.set_wiring('arc'))

    def _on_chamfer(sender, args):
        if session.wiring() != 'chamfer':
            _redraw(lambda: session.set_wiring('chamfer'))

    def _on_avoid(sender, args):
        try:
            wanted = bool(sender.IsChecked)
        except Exception:
            return
        if wanted == session.avoiding():
            return
        _redraw(lambda: session.set_avoid(wanted))

    def _on_offset(sender, args):
        try:
            value = float(sender.Value)
        except Exception:
            return
        if abs(value - session.sag()) < 1.0e-9:
            return
        _redraw(lambda: session.set_sag(value))

    def _close_with(keep):
        state['kept'] = keep
        bridge = state['bridge']
        if bridge is None:
            try:
                window.Close()
            except Exception:
                pass
            return
        if state['done']:
            return
        state['done'] = True

        def _after():
            try:
                window.Close()
            except Exception:
                pass

        if not bridge.run(lambda uiapp: session.finish(keep), _after):
            state['done'] = False

    def _on_keep(sender, args):
        _close_with(True)

    def _on_cancel(sender, args):
        _close_with(False)

    try:
        back = window.FindName('PreviousButton')
        if back is not None:
            back.IsEnabled = session.has_previous()
    except Exception:
        pass

    try:
        box = window.FindName('AvoidClashBox')
        if box is not None:
            box.IsChecked = session.avoiding()
            box.Click += _on_avoid
    except Exception:
        pass

    for name, handler in (('ShuffleButton', _on_shuffle),
                          ('PreviousButton', _on_previous),
                          ('VertexUp', _on_vertex_up),
                          ('VertexDown', _on_vertex_down),
                          ('ArcButton', _on_arc),
                          ('ChamferButton', _on_chamfer),
                          ('KeepButton', _on_keep),
                          ('CancelButton', _on_cancel)):
        try:
            button = window.FindName(name)
            if button is not None:
                button.Click += handler
        except Exception:
            pass

    # the slider redraws on release rather than on every tick, or a single
    # drag would open a transaction per pixel
    try:
        slider = window.FindName('OffsetSlider')
        if slider is not None:
            slider.AddHandler(Slider.PreviewMouseLeftButtonUpEvent,
                              MouseButtonEventHandler(_on_offset), True)
            slider.KeyUp += _on_offset
    except Exception:
        try:
            slider = window.FindName('OffsetSlider')
            if slider is not None:
                slider.ValueChanged += _on_offset
        except Exception:
            pass

    if not getattr(session, 'modeless', False):
        try:
            window.ShowDialog()
        except Exception:
            state['kept'] = True
        if not state['kept']:
            session.cancel()
        return state['kept']

    # modeless: hand the work to Revit and let the window live
    try:
        from wire_events import EventBridge
        bridge = EventBridge()
    except Exception:
        # no bridge, no safe way to touch the document - fall back to modal
        try:
            window.ShowDialog()
        except Exception:
            state['kept'] = True
        if not state['kept']:
            session.cancel()
        return state['kept']

    state['bridge'] = bridge
    _LIVE.append(window)

    def _closed(sender, args):
        # closing with the X is a cancel, like any other dialog
        if not state['done']:
            state['done'] = True
            bridge.run(lambda uiapp: session.finish(False))
        try:
            _LIVE.remove(window)
        except Exception:
            pass

    try:
        window.Closed += _closed
    except Exception:
        pass

    try:
        window.Show()
    except Exception:
        try:
            _LIVE.remove(window)
        except Exception:
            pass
        session.cancel()
    return None
