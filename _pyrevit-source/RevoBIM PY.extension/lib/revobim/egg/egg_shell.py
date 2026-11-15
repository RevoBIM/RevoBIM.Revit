# -*- coding: utf-8 -*-
"""The window the egg opens in.

Built entirely in code rather than from a XAML file. Two reasons: the whole
blank-white-pyRevit-window class of bug comes from a layout that will not parse
or a StaticResource resolved before Theme.xaml is merged, and neither is
possible where there is no layout; and a game window that had to ship a
Theme.xaml beside every tool would defeat the point of it living in lib once.

Chrome still follows the house style - WindowStyle None, rounded border,
draggable header, RevoBIM in blue with the name in orange, version top right, a
full screen button beside a bare close glyph that turns red on hover, and eight
resize grips because a borderless AllowsTransparency window has no frame WPF can
hit test.
"""

from revobim.egg import egg_clr  # noqa: F401  - assemblies first, always

from System import Action, AppDomain
from System.Diagnostics import Stopwatch
from System.Threading import ApartmentState, Thread, ThreadStart
from System.Windows import (CornerRadius, FontWeights, GridLength,
                            HorizontalAlignment, PresentationSource,
                            ResizeMode, SystemParameters, TextAlignment,
                            Thickness, VerticalAlignment, Visibility, Window,
                            WindowStartupLocation, WindowStyle)
from System.Windows.Controls import (Border, Canvas, ColumnDefinition, Grid,
                                     Orientation, RowDefinition, StackPanel,
                                     StretchDirection, TextBlock, Viewbox)
from System.Windows.Controls.Primitives import Thumb
from System.Windows.Input import Cursors, Key
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Media import (ColorConverter, CompositionTarget,
                                  FontFamily, SolidColorBrush, Stretch)

from revobim.egg import __version__ as EGG_VERSION
from revobim.egg import (egg_launcher, egg_log, egg_registry, egg_scores,
                         egg_settings, egg_theme)
from revobim.egg.egg_surface import Surface

PAD = 14
HEADER = 46
FOOTER = 30
MIN_WIDTH = 560
MIN_HEIGHT = 360
GRIP = 6

TRANSPARENT = "#00FFFFFF"

# Keys the games are told about, under the names they expect.
_KEY_NAMES = {
    Key.Up: "Up", Key.Down: "Down", Key.Left: "Left", Key.Right: "Right",
    Key.W: "W", Key.A: "A", Key.S: "S", Key.D: "D",
    Key.Space: "Space", Key.P: "P", Key.R: "R",
}

THEME_CYCLE = ("auto", "dark", "light")

# How long the game over card gets to itself before the board slides in over it.
BOARD_DELAY_MS = 1400.0

# A frame this long means the window was dragged, the machine stalled, or a
# breakpoint was hit. Catching up thirty logic steps at once would teleport
# every ghost across the board, so the clock is simply told to forget it.
MAX_FRAME_MS = 250.0

# The window is parked here so the persistent engine cannot collect it out from
# under the player, and so a second triple click brings the open one forward
# rather than stacking another on top of it. Also parked in the AppDomain, which
# outlives a pyRevit engine teardown - a modal tool's command returns while the
# game thread is still running, and without this the engine can be disposed out
# from under it.
_OPEN = []
_PARK_KEY = "RevoBIM.egg.windows"


def _park(egg):
    _OPEN.append(egg)
    try:
        AppDomain.CurrentDomain.SetData(_PARK_KEY, _OPEN)
    except Exception:
        pass


def _brush(value):
    try:
        made = SolidColorBrush(ColorConverter.ConvertFromString(value))
        made.Freeze()
        return made
    except Exception:
        return None


class EggWindow(object):

    def __init__(self, host_window=None, theme=None, game_key=None,
                 host_handle=None, dispatcher=None, on_reopen=None):
        self.host = host_window
        self.host_handle = host_handle
        self.dispatcher = dispatcher
        self.on_reopen = on_reopen
        self.replacing = False
        self.theme_source = theme
        self.settings = egg_settings.load()
        self.theme_setting = self.settings.get("theme", "auto")
        self.theme_name = egg_theme.resolve(theme, self.theme_setting)
        self.palette = egg_theme.palette(self.theme_name)
        self.game_key = game_key or self.settings.get("game", "pacman")
        self.module = egg_registry.pick(self.game_key)
        self.game = None
        self.window = None
        self.canvas = None
        self.surface = None
        self.status = None
        self.close_glyph = None
        self.pop_chip = None
        self.closing = False
        self.full = False
        self.bounds = None
        self.clock = None
        self.owed = 0.0
        self.step = 33.0
        self._frame = None
        self.board = None
        self.board_host = None
        self.board_chip = None
        self.recorded = False
        self.dismissed = False
        self.since_over = 0.0
        self.last_entry = None
        self.last_place = 0

    # -- building ========================================================

    def build(self):
        if self.module is None:
            return False
        self.game_key = self.module.KEY
        self.step = float(getattr(self.module, "TICK_MS", 33))

        window = Window()
        # WindowStyle.None cannot be written directly - None is a Python
        # keyword, so IronPython will not parse it. Same trap as any .NET member
        # called None, Not or Is.
        window.WindowStyle = getattr(WindowStyle, "None")
        window.AllowsTransparency = True
        window.ResizeMode = ResizeMode.NoResize
        window.Background = _brush(TRANSPARENT)
        window.ShowInTaskbar = False
        window.WindowStartupLocation = WindowStartupLocation.CenterOwner
        window.Title = "RevoBIM"
        try:
            # So the automatic attachment does not hook the game's own logo.
            from revobim.egg import egg_auto
            egg_auto.mark_as_ours(window)
        except Exception:
            pass
        window.FontFamily = FontFamily("Segoe UI")
        window.MinWidth = MIN_WIDTH
        window.MinHeight = MIN_HEIGHT
        self.window = window

        shell = Border()
        shell.CornerRadius = CornerRadius(6)
        shell.BorderThickness = Thickness(1)
        shell.BorderBrush = _brush(self.palette["chrome"])
        shell.Background = _brush(self.palette["bg"])

        root = Grid()
        root.Children.Add(shell)
        root.Children.Add(self._grips())
        window.Content = root

        grid = Grid()
        for height in (HEADER, None, FOOTER):
            row = RowDefinition()
            if height is not None:
                row.Height = GridLength(height)
            grid.RowDefinitions.Add(row)
        shell.Child = grid

        header = self._header()
        Grid.SetRow(header, 0)
        grid.Children.Add(header)

        body = self._body()
        Grid.SetRow(body, 1)
        grid.Children.Add(body)

        footer = self._footer()
        Grid.SetRow(footer, 2)
        grid.Children.Add(footer)

        self._size(window)
        self._own(window)

        window.PreviewKeyDown += self._on_key
        window.Closed += self._on_closed
        return True

    def _header(self):
        bar = Border()
        bar.Background = _brush(self.palette["bar"])
        bar.CornerRadius = CornerRadius(6, 6, 0, 0)
        bar.MouseLeftButtonDown += self._on_drag

        grid = Grid()
        grid.Margin = Thickness(PAD, 0, PAD - 4, 0)
        left = ColumnDefinition()
        right = ColumnDefinition()
        right.Width = GridLength.Auto
        grid.ColumnDefinitions.Add(left)
        grid.ColumnDefinitions.Add(right)
        bar.Child = grid

        name = StackPanel()
        name.Orientation = Orientation.Horizontal
        name.VerticalAlignment = VerticalAlignment.Center
        Grid.SetColumn(name, 0)
        grid.Children.Add(name)
        name.Children.Add(self._text("RevoBIM", 19, "blue", True))
        title = self._text(self.module.NAME, 14, "orange", False)
        title.Margin = Thickness(8, 4, 0, 0)
        name.Children.Add(title)

        tools = StackPanel()
        tools.Orientation = Orientation.Horizontal
        tools.VerticalAlignment = VerticalAlignment.Center
        Grid.SetColumn(tools, 1)
        grid.Children.Add(tools)

        tools.Children.Add(self._chip(self.module.NAME, self._next_game))
        # Only offered where it can actually work. A button that does nothing
        # on half the machines in the office is worse than no button.
        if egg_launcher.available():
            self.pop_chip = self._chip("Pop out", self._pop_out)
            self.pop_chip.ToolTip = ("Hand the game to its own process and "
                                     "give Revit back")
            tools.Children.Add(self.pop_chip)
        self.board_chip = self._chip("Scores", self._toggle_board)
        tools.Children.Add(self.board_chip)
        tools.Children.Add(self._chip(self.theme_setting.capitalize(),
                                      self._cycle_theme))

        version = self._text("v" + EGG_VERSION, 11, "muted", False)
        version.Margin = Thickness(10, 3, 8, 0)
        tools.Children.Add(version)

        # Full screen sits beside close, which is where the eye looks for it.
        tools.Children.Add(self._full_button())

        close = Border()
        close.Background = _brush(TRANSPARENT)
        close.Padding = Thickness(8, 3, 8, 4)
        close.VerticalAlignment = VerticalAlignment.Center
        self.close_glyph = self._text("X", 13, "muted", True)
        close.Child = self.close_glyph
        close.MouseLeftButtonDown += self._on_close_click
        close.MouseEnter += self._on_close_enter
        close.MouseLeave += self._on_close_leave
        tools.Children.Add(close)
        return bar

    def _full_button(self):
        """The maximise glyph, drawn from Borders.

        Not a symbol font: a machine without that font renders the glyph as an
        empty box, and there is no way to notice until somebody reports it.
        """
        hit = Border()
        hit.Background = _brush(TRANSPARENT)
        hit.Padding = Thickness(6, 4, 6, 4)
        hit.VerticalAlignment = VerticalAlignment.Center
        hit.ToolTip = "Full screen (F11)"

        square = Border()
        square.Width = 11
        square.Height = 10
        square.BorderThickness = Thickness(1.4)
        square.BorderBrush = _brush(self.palette["muted"])
        square.CornerRadius = CornerRadius(1.5)
        hit.Child = square

        hit.MouseLeftButtonDown += self._on_full_click
        self.full_glyph = square
        return hit

    def _body(self):
        holder = Border()
        holder.Background = _brush(self.palette["card"])
        holder.Margin = Thickness(PAD, 0, PAD, 0)
        holder.CornerRadius = CornerRadius(4)
        holder.Padding = Thickness(6)

        canvas = Canvas()
        self.canvas = canvas

        # The board is a fixed pixel size, so scaling it is the Viewbox's job
        # rather than every game's. That is also what makes full screen worth
        # having: the same maze, four times the size, no game code involved.
        box = Viewbox()
        box.Stretch = Stretch.Uniform
        box.Child = canvas
        box.HorizontalAlignment = HorizontalAlignment.Center
        box.VerticalAlignment = VerticalAlignment.Center

        stack = Grid()
        stack.Children.Add(box)
        self.board_host = Grid()
        self.board_host.Visibility = Visibility.Collapsed
        stack.Children.Add(self.board_host)
        holder.Child = stack
        return holder

    def _footer(self):
        bar = Border()
        bar.Background = _brush(self.palette["bar"])
        bar.CornerRadius = CornerRadius(0, 0, 6, 6)

        grid = Grid()
        grid.Margin = Thickness(PAD, 0, PAD, 0)
        bar.Child = grid

        self.status = self._text("", 11.5, "text", False)
        self.status.HorizontalAlignment = HorizontalAlignment.Left
        grid.Children.Add(self.status)

        keys = self._text(self.module.KEYS + "   Tab scores", 11, "muted",
                          False)
        keys.HorizontalAlignment = HorizontalAlignment.Right
        grid.Children.Add(keys)
        return bar

    def _grips(self):
        """Eight thumbs round the edge.

        A borderless AllowsTransparency window has nothing hit testable in its
        frame, so WPF's resize border never fires however ResizeMode is set and
        the window is stuck at its start size. The overlay carries no
        Background, so everything underneath stays clickable.
        """
        overlay = Grid()
        edges = (
            ("nw", HorizontalAlignment.Left, VerticalAlignment.Top,
             Cursors.SizeNWSE),
            ("n", HorizontalAlignment.Stretch, VerticalAlignment.Top,
             Cursors.SizeNS),
            ("ne", HorizontalAlignment.Right, VerticalAlignment.Top,
             Cursors.SizeNESW),
            ("e", HorizontalAlignment.Right, VerticalAlignment.Stretch,
             Cursors.SizeWE),
            ("se", HorizontalAlignment.Right, VerticalAlignment.Bottom,
             Cursors.SizeNWSE),
            ("s", HorizontalAlignment.Stretch, VerticalAlignment.Bottom,
             Cursors.SizeNS),
            ("sw", HorizontalAlignment.Left, VerticalAlignment.Bottom,
             Cursors.SizeNESW),
            ("w", HorizontalAlignment.Left, VerticalAlignment.Stretch,
             Cursors.SizeWE),
        )
        for edge, horizontal, vertical, cursor in edges:
            thumb = Thumb()
            thumb.Tag = edge
            thumb.HorizontalAlignment = horizontal
            thumb.VerticalAlignment = vertical
            thumb.Cursor = cursor
            thumb.Opacity = 0.0
            if horizontal != HorizontalAlignment.Stretch:
                thumb.Width = GRIP
            if vertical != VerticalAlignment.Stretch:
                thumb.Height = GRIP
            thumb.DragDelta += self._on_grip
            overlay.Children.Add(thumb)
        return overlay

    def _text(self, value, size, colour, bold):
        block = TextBlock()
        block.Text = value
        block.FontSize = size
        block.Foreground = _brush(self.palette[colour])
        if bold:
            block.FontWeight = FontWeights.Bold
        block.VerticalAlignment = VerticalAlignment.Center
        return block

    def _chip(self, label, handler):
        chip = Border()
        chip.Background = _brush(self.palette["card"])
        chip.BorderBrush = _brush(self.palette["edge"])
        chip.BorderThickness = Thickness(1)
        chip.CornerRadius = CornerRadius(3)
        chip.Padding = Thickness(9, 2, 9, 3)
        chip.Margin = Thickness(0, 0, 6, 0)
        chip.VerticalAlignment = VerticalAlignment.Center
        chip.Child = self._text(label, 11, "muted", False)
        chip.MouseLeftButtonDown += handler
        return chip

    def _chip_label(self, chip, text, colour="muted"):
        try:
            chip.Child.Text = text
            chip.Child.Foreground = _brush(self.palette[colour])
        except Exception:
            pass

    def _size(self, window):
        # A game is asked how big it is before it is given a surface, so its
        # __init__ must not draw. That is in the contract, and it is why the
        # probe below is safe.
        probe = self.module.Game(None, self.settings)
        width = probe.width()
        height = probe.height()
        self.canvas.Width = width
        self.canvas.Height = height
        window.Width = max(width + (PAD * 2) + 14, MIN_WIDTH)
        window.Height = height + HEADER + FOOTER + 22

    def _own(self, window):
        """Own the window, or it slips behind Revit and reads as a crash.

        Owning it to the host tool's window also means it still takes input when
        the host is modal: ShowDialog disables every window in the application
        except those the dialog owns.

        On the game's own thread that route is closed - WPF will not let a
        window on one thread be Owner of a window on another - so ownership goes
        through the raw HWND instead, which is thread agnostic and does the same
        job of keeping it above Revit.
        """
        if self.host_handle is not None:
            try:
                WindowInteropHelper(window).Owner = self.host_handle
                return
            except Exception:
                pass
        if self.host is not None:
            try:
                window.Owner = self.host
                return
            except Exception:
                pass
        try:
            from System.Diagnostics import Process
            handle = Process.GetCurrentProcess().MainWindowHandle
            WindowInteropHelper(window).Owner = handle
        except Exception:
            pass

    # -- running =========================================================

    def show(self):
        if not self.build():
            return False
        self.window.Show()
        self._restart()
        return True

    def _restart(self):
        self._stop_loop()
        self.surface = Surface(self.canvas, self.palette)
        self.game = self.module.Game(self.surface, self.settings)
        self.game.start()
        self.recorded = False
        self.dismissed = False
        self.since_over = 0.0
        self.last_entry = None
        self.last_place = 0
        self._hide_board()
        self._chip_label(self.board_chip, "Scores")
        self.owed = 0.0
        self.clock = Stopwatch()
        self.clock.Start()
        # CompositionTarget.Rendering rather than a DispatcherTimer: it fires
        # once per frame the display actually draws, in step with vsync, which
        # is the difference between a game that glides and one that stutters.
        self._frame = self._on_frame
        CompositionTarget.Rendering += self._frame

    def _stop_loop(self):
        if self._frame is not None:
            try:
                # Rendering is a static event, so a handler left attached would
                # go on firing for the life of the session. The delegate is held
                # in _frame precisely so -= has the same object to remove; the
                # closing flag covers the case where it does not.
                CompositionTarget.Rendering -= self._frame
            except Exception:
                pass
            self._frame = None
        if self.clock is not None:
            try:
                self.clock.Stop()
            except Exception:
                pass
            self.clock = None
        if self.game is not None:
            try:
                self.game.stop()
            except Exception:
                pass

    def _on_frame(self, sender, args):
        if self.closing or self.game is None or self.clock is None:
            return
        try:
            elapsed = self.clock.Elapsed.TotalMilliseconds
            self.clock.Restart()
            if elapsed > MAX_FRAME_MS:
                elapsed = self.step

            self.owed += elapsed
            steps = 0
            while self.owed >= self.step and steps < 5:
                self.game.tick()
                self.owed -= self.step
                steps += 1

            render = getattr(self.game, "render", None)
            if render is not None:
                render(min(1.0, self.owed / self.step))

            if steps:
                self._update_status()
                self._watch_for_finish(elapsed)
        except Exception:
            # An easter egg is not allowed to throw at the user. Raising out of
            # the render loop lands as a Revit crash dialog, so the loop stops
            # and the status line says so instead.
            self._stop_loop()
            try:
                self.status.Text = "The game stopped. Esc to close."
            except Exception:
                pass

    def _watch_for_finish(self, elapsed):
        """Record a finished game once, then show the board.

        The record goes in the moment the game says it is over rather than when
        the window closes - a game abandoned with R or a window shut mid-run is
        not a finished game and does not belong on the board, and waiting for
        the close would put it there.
        """
        if not self.game.is_over():
            return
        if not self.recorded:
            self.recorded = True
            self.since_over = 0.0
            try:
                entry, place, total = egg_scores.record(
                    self.game_key, getattr(self.game, "score", 0),
                    self.settings)
                self.last_entry = entry
                self.last_place = place
                self._chip_label(self.board_chip,
                                 "Scores  #{0}".format(place),
                                 "green" if place == 1 else "orange")
            except Exception:
                self.last_entry = None
            return

        if self.dismissed or self.board is not None:
            return
        if str(self.settings.get("scores_on_finish", "on")).lower() != "on":
            return
        self.since_over += elapsed
        if self.since_over >= BOARD_DELAY_MS:
            self._show_board()

    def _update_status(self):
        score = getattr(self.game, "score", 0)
        best = egg_settings.high_score(self.settings, self.game_key)
        if score > best:
            egg_settings.set_high_score(self.settings, self.game_key, score)
            best = score
        self.status.Text = "{0}    Best {1}".format(self.game.status(), best)

    # -- the scoreboard ==================================================

    def _toggle_board(self, sender=None, args=None):
        if args is not None:
            args.Handled = True
        if self.board is not None:
            self.dismissed = True
            self._hide_board()
        else:
            self._show_board()

    def _show_board(self):
        try:
            self._hide_board()
            self.board = self._build_board()
            self.board_host.Children.Add(self.board)
            self.board_host.Visibility = Visibility.Visible
            self._chip_label(self.board_chip, "Hide scores", "orange")
            # Pause a live game rather than let it play on unwatched behind the
            # board. A finished one has nothing left to pause.
            if self.game is not None and not self.game.is_over():
                try:
                    self.game.key("P")
                except Exception:
                    pass
        except Exception:
            self.board = None

    def _hide_board(self):
        try:
            if self.board_host is not None:
                self.board_host.Children.Clear()
                self.board_host.Visibility = Visibility.Collapsed
        except Exception:
            pass
        self.board = None
        if self.board_chip is not None:
            if self.last_place:
                self._chip_label(self.board_chip,
                                 "Scores  #{0}".format(self.last_place),
                                 "green" if self.last_place == 1 else "orange")
            else:
                self._chip_label(self.board_chip, "Scores")

    def _build_board(self):
        shown = egg_settings.get_int(self.settings, "scores_shown", 15)
        table = egg_scores.ranked(self.game_key, shown)
        me = egg_scores.player_name(self.settings)

        card = Border()
        card.Background = _brush(self.palette["veil"])
        card.CornerRadius = CornerRadius(4)
        card.Padding = Thickness(22, 16, 22, 16)
        card.HorizontalAlignment = HorizontalAlignment.Center
        card.VerticalAlignment = VerticalAlignment.Center

        column = StackPanel()
        column.Orientation = Orientation.Vertical
        card.Child = column

        heading = StackPanel()
        heading.Orientation = Orientation.Horizontal
        heading.HorizontalAlignment = HorizontalAlignment.Center
        heading.Margin = Thickness(0, 0, 0, 12)
        heading.Children.Add(self._text("HIGH SCORES", 17, "blue", True))
        name = self._text(self.module.NAME, 13, "orange", False)
        name.Margin = Thickness(9, 3, 0, 0)
        heading.Children.Add(name)
        column.Children.Add(heading)

        if not table:
            empty = self._text("Nothing on the board yet. Go and lose a game.",
                               12, "muted", False)
            empty.Margin = Thickness(0, 6, 0, 10)
            column.Children.Add(empty)
        else:
            column.Children.Add(self._board_row(
                "#", "Player", "Score", "When", "muted", False, 10.5))
            for index in range(len(table)):
                entry = table[index]
                # The row just played is picked out, so the point of the board
                # is legible without hunting for your own name in it.
                mine = (self.last_entry is not None
                        and entry["when"] == self.last_entry["when"]
                        and entry["player"] == self.last_entry["player"]
                        and entry["score"] == self.last_entry["score"])
                colour = "orange" if mine else (
                    "text" if entry["player"] == me else "muted")
                column.Children.Add(self._board_row(
                    str(index + 1), entry["player"],
                    "{0}".format(entry["score"]),
                    egg_scores.pretty_when(entry["when"]),
                    colour, mine, 12.0))

        note = self._text(
            "press R to play again    -    Tab to close", 11, "muted", False)
        note.HorizontalAlignment = HorizontalAlignment.Center
        note.Margin = Thickness(0, 12, 0, 0)
        column.Children.Add(note)

        back = self._text("Now get back to work!", 13, "orange", True)
        back.HorizontalAlignment = HorizontalAlignment.Center
        back.Margin = Thickness(0, 10, 0, 0)
        column.Children.Add(back)

        # Fifteen rows is taller than the body on a default sized window, so the
        # card shrinks to fit rather than being clipped - and DownOnly means it
        # is never blown up to fill a full screen either, which would leave one
        # short table in enormous text.
        box = Viewbox()
        box.Stretch = Stretch.Uniform
        box.StretchDirection = StretchDirection.DownOnly
        box.Margin = Thickness(4)
        box.Child = card
        box.HorizontalAlignment = HorizontalAlignment.Center
        box.VerticalAlignment = VerticalAlignment.Center
        return box

    def _board_row(self, place, player, score, when, colour, bold, size):
        row = Grid()
        row.Margin = Thickness(0, 0.5, 0, 0.5)
        for width in (34, None, 90, 104):
            definition = ColumnDefinition()
            if width is not None:
                definition.Width = GridLength(width)
            row.ColumnDefinitions.Add(definition)

        cells = ((place, TextAlignment.Left), (player, TextAlignment.Left),
                 (score, TextAlignment.Right), (when, TextAlignment.Right))
        for index in range(len(cells)):
            value, align = cells[index]
            block = self._text(value, size, colour, bold)
            block.TextAlignment = align
            block.Margin = Thickness(0, 0, 10, 0)
            Grid.SetColumn(block, index)
            row.Children.Add(block)
        # The player column is the one that has to give, since a name can be
        # anything and the other three are fixed widths.
        row.ColumnDefinitions[1].MinWidth = 130
        return row

    # -- full screen =====================================================

    def _toggle_full(self):
        """By bounds, not WindowState.Maximized.

        Maximising a borderless AllowsTransparency window the normal way covers
        the task bar and lands on the wrong monitor.
        """
        if self.full:
            if self.bounds:
                left, top, width, height = self.bounds
                self.window.Left = left
                self.window.Top = top
                self.window.Width = width
                self.window.Height = height
            self.full = False
            self._set_full_glyph()
            return

        self.bounds = (self.window.Left, self.window.Top,
                       self.window.Width, self.window.Height)
        area = self._working_area()
        if area is None:
            return
        left, top, width, height = area
        self.window.Left = left
        self.window.Top = top
        self.window.Width = width
        self.window.Height = height
        self.full = True
        self._set_full_glyph()

    def _working_area(self):
        scale_x, scale_y = 1.0, 1.0
        try:
            source = PresentationSource.FromVisual(self.window)
            matrix = source.CompositionTarget.TransformToDevice
            # Without dividing by the DPI scale the window overshoots on a
            # scaled display - and every laptop is a scaled display.
            scale_x = matrix.M11 or 1.0
            scale_y = matrix.M22 or 1.0
        except Exception:
            pass
        try:
            from System.Windows.Forms import Screen
            handle = WindowInteropHelper(self.window).Handle
            area = Screen.FromHandle(handle).WorkingArea
            return (area.Left / scale_x, area.Top / scale_y,
                    area.Width / scale_x, area.Height / scale_y)
        except Exception:
            pass
        try:
            # No WinForms: the primary monitor's work area, already in DIPs.
            return (0.0, 0.0, SystemParameters.WorkArea.Width,
                    SystemParameters.WorkArea.Height)
        except Exception:
            return None

    def _set_full_glyph(self):
        try:
            if self.full:
                self.full_glyph.Width = 9
                self.full_glyph.Height = 8
                self.full_glyph.Margin = Thickness(2, 2, 0, 0)
            else:
                self.full_glyph.Width = 11
                self.full_glyph.Height = 10
                self.full_glyph.Margin = Thickness(0)
        except Exception:
            pass

    # -- interaction =====================================================

    def _on_key(self, sender, args):
        if args.Key == Key.Tab:
            args.Handled = True
            self._toggle_board()
            return
        if args.Key == Key.F11:
            args.Handled = True
            self._toggle_full()
            return
        if args.Key == Key.Escape:
            args.Handled = True
            # Escape unwinds one layer at a time - board, then full screen,
            # then the window - which is what every other application does.
            if self.board is not None:
                self.dismissed = True
                self._hide_board()
            elif self.full:
                self._toggle_full()
            else:
                self.window.Close()
            return
        name = _KEY_NAMES.get(args.Key)
        if name is None:
            return
        # Arrow keys are swallowed by WPF focus navigation unless they are
        # handled here, in the tunnelling pass, before anything else sees them.
        args.Handled = True
        if name == "R":
            self._restart()
            return
        if self.board is not None:
            # With the board up, nothing but R and Tab should reach the game -
            # otherwise a pause keypress unpauses it behind the card.
            return
        if self.game is not None:
            try:
                self.game.key(name)
            except Exception:
                pass

    def _pop_out(self, sender, args):
        """Hand the game to its own process and close this one.

        Same games, same scoreboard file, none of Revit's resources - and Revit
        can be closed underneath it without the game noticing.
        """
        args.Handled = True
        if egg_launcher.spawn(self.game_key):
            self.closing = True
            self._stop_loop()
            try:
                self.window.Close()
            except Exception:
                pass
            return
        try:
            self._chip_label(self.pop_chip, "No Python", "red")
        except Exception:
            pass

    def _next_game(self, sender, args):
        args.Handled = True
        self.settings["game"] = egg_registry.next_after(self.game_key)
        egg_settings.save(self.settings)
        self._reopen(self.settings["game"])

    def _cycle_theme(self, sender, args):
        args.Handled = True
        current = self.theme_setting if self.theme_setting in THEME_CYCLE \
            else "auto"
        nxt = THEME_CYCLE[(THEME_CYCLE.index(current) + 1) % len(THEME_CYCLE)]
        self.settings["theme"] = nxt
        egg_settings.save(self.settings)
        self._reopen(self.game_key)

    def _reopen(self, game_key):
        """Rebuild rather than re-theme in place.

        Re-pointing every brush on a live canvas is a lot of code for something
        used twice a session, and losing a game of Pacman to a theme switch is
        not a real cost.
        """
        source = self.theme_source
        self.closing = True
        self.replacing = True
        self._stop_loop()
        try:
            self.window.Close()
        except Exception:
            pass
        if self.on_reopen is not None:
            # Stay on this thread. Going back through launch() would re-run the
            # mode choice and could hand the game to a whole new process just
            # because somebody changed the theme.
            self.on_reopen(game_key, source)
            return
        launch(host_window=self.host, theme=source, game_key=game_key,
               mode="inline")

    def _on_drag(self, sender, args):
        try:
            if args.ClickCount == 2:
                args.Handled = True
                self._toggle_full()
                return
            if self.full:
                # Dragging the window counts as leaving full screen, the same
                # way it does everywhere else.
                self._toggle_full()
            self.window.DragMove()
        except Exception:
            pass

    def _on_grip(self, sender, args):
        if self.full:
            return
        try:
            edge = str(sender.Tag)
            window = self.window
            if "w" in edge:
                width = window.Width - args.HorizontalChange
                if width >= window.MinWidth:
                    window.Left += args.HorizontalChange
                    window.Width = width
            elif "e" in edge:
                window.Width = max(window.MinWidth,
                                   window.Width + args.HorizontalChange)
            if edge.startswith("n"):
                height = window.Height - args.VerticalChange
                if height >= window.MinHeight:
                    window.Top += args.VerticalChange
                    window.Height = height
            elif edge.startswith("s"):
                window.Height = max(window.MinHeight,
                                    window.Height + args.VerticalChange)
        except Exception:
            pass

    def _on_full_click(self, sender, args):
        args.Handled = True
        self._toggle_full()

    def _on_close_click(self, sender, args):
        args.Handled = True
        self.window.Close()

    def _on_close_enter(self, sender, args):
        self.close_glyph.Foreground = _brush(self.palette["red"])

    def _on_close_leave(self, sender, args):
        self.close_glyph.Foreground = _brush(self.palette["muted"])

    def _on_closed(self, sender, args):
        self.closing = True
        self._stop_loop()
        try:
            _OPEN.remove(self)
        except Exception:
            pass
        # On its own thread the dispatcher has to be told to stop, or the thread
        # sits in Dispatcher.Run() for the life of the Revit session.
        if self.dispatcher is not None and not self.replacing:
            try:
                self.dispatcher.InvokeShutdown()
            except Exception:
                pass


def resolve_mode(wanted, have_python):
    """Which of the three ways to run, given the setting and the machine.

    Kept as a plain function of two values so it can be tested without a Revit,
    a Python or a display.

    - **process**  a separate OS process. Nothing to do with Revit at all: it
      keeps playing while a tool holds Revit's thread, and keeps playing if
      Revit is closed. Needs Python 3 with tkinter, which cannot be established
      from a name on PATH - so this is opt in, through the Pop out chip or the
      setting, rather than something auto guesses at.
    - **thread**   this process, but the game's own STA thread with its own
      dispatcher. Immune to Revit's UI thread being blocked, which is the whole
      problem, and needs nothing installed.
    - **inline**   Revit's own UI thread. What every version up to 1.6.0 did,
      and why the game froze whenever a tool was working.
    """
    wanted = (wanted or "auto").strip().lower()
    if wanted == "auto":
        # Thread, not process. A separate process is the stronger answer and it
        # is one chip away, but "a Python is on PATH" is not the same as "that
        # Python is 3 and has tkinter" - and when it is not, the button does
        # nothing and says nothing. The thread needs nothing installed and
        # cannot fail that way, so it is what auto picks.
        return "thread"
    if wanted in ("process", "thread", "inline"):
        return wanted
    return "thread"


def launch(host_window=None, theme=None, game_key=None, mode=None):
    """Open the egg. Returns True if it went.

    Never raises: a broken easter egg must not be able to take a tool down with
    it, so every failure is swallowed and reported as False.
    """
    try:
        if _activate_open():
            return True

        settings = egg_settings.load()
        wanted = resolve_mode(mode or settings.get("run_mode", "auto"),
                              egg_launcher.available())

        # Both resolved here, on the caller's thread, before anything else.
        # A theme callable normally reads the host tool's own state, and
        # touching a WPF object from the game thread throws; a Window cannot be
        # the Owner of a window on another thread either, so the handle is taken
        # while we are still somewhere allowed to ask for it.
        resolved = egg_theme.resolve(theme, settings.get("theme"))
        handle = _handle_of(host_window)

        if wanted == "process":
            if egg_launcher.spawn(game_key or settings.get("game"),
                                  pause=pause):
                return True
            egg_log.write("process mode failed, falling back to a thread",
                          "shell")
            wanted = "thread"

        if wanted == "thread":
            if _launch_threaded(handle, resolved, game_key):
                return True
            egg_log.write("thread mode failed, falling back to inline",
                          "shell")

        return _launch_inline(host_window, resolved, game_key)
    except Exception:
        return False


def _launch_threaded(handle, theme_name, game_key):
    """The game on its own STA thread, with its own dispatcher.

    This is what fixes the freeze. A window belongs to the thread that made it,
    and it repaints and takes input on that thread's dispatcher - so a pyRevit
    tool holding Revit's UI thread for two minutes has no bearing on it. Every
    WPF object therefore has to be built *inside* the thread; building the
    window first and showing it there would put it back on Revit's dispatcher
    and change nothing.
    """
    try:
        def run():
            try:
                dispatcher = Dispatcher.CurrentDispatcher

                def open_one(key, source):
                    egg = EggWindow(theme=source or theme_name, game_key=key,
                                    host_handle=handle, dispatcher=dispatcher,
                                    on_reopen=open_one)
                    if egg.show():
                        _park(egg)
                        return True
                    return False

                if not open_one(game_key, theme_name):
                    egg_log.write("game window would not open on its thread",
                                  "shell")
                    return
                Dispatcher.Run()
            except Exception:
                egg_log.write("game thread stopped: {0}".format(
                    _error()), "shell")

        thread = Thread(ThreadStart(run))
        # STA or WPF will not have it, and background or the thread keeps Revit
        # alive after somebody has asked it to close.
        thread.SetApartmentState(ApartmentState.STA)
        thread.IsBackground = True
        thread.Name = "RevoBIM egg"
        thread.Start()

        # Thread.Start returning only means the thread was created. Prove the
        # window actually opened before saying so, or a thread that dies on its
        # first line - the engine torn down under it, an import that failed - is
        # indistinguishable from a button that does nothing.
        if not _window_appeared():
            egg_log.write(
                "thread started but no window appeared. If this came from a "
                "pushbutton, that script needs __persistentengine__ = True or "
                "pyRevit disposes the engine as it returns.", "shell")
            return False

        egg_log.write("opened on its own thread", "shell")
        return True
    except Exception:
        egg_log.write("could not start the game thread: {0}".format(_error()),
                      "shell")
        return False


def pause(milliseconds):
    """Wait on Revit's own thread without wedging it.

    `Thread.Sleep` on an STA thread does not pump messages, and IronPython says
    so out loud - which is a warning written to stderr, which is what makes
    pyRevit throw up its white output window behind the game. `Join` with a
    timeout on the current thread is the documented way to wait on an STA
    thread and it pumps, so nothing is blocked and nothing is printed.
    """
    try:
        Thread.CurrentThread.Join(int(milliseconds))
        return True
    except Exception:
        pass
    try:
        Thread.Sleep(int(milliseconds))
        return True
    except Exception:
        return False


def _window_appeared(seconds=1.2):
    """Wait briefly for the game thread to park a window.

    Polled on the caller's thread. It costs nothing in the normal case, since
    the window is usually up inside a tenth of a second, and the whole wait only
    ever elapses when something is already wrong.
    """
    waited = 0.0
    while waited < seconds:
        if _OPEN:
            return True
        if not pause(50):
            return True
        waited += 0.05
    return bool(_OPEN)


def _launch_inline(host_window, theme_name, game_key):
    """On Revit's own UI thread. The last resort, and the one that freezes."""
    try:
        egg = EggWindow(host_window=host_window, theme=theme_name,
                        game_key=game_key)
        if egg.show():
            _park(egg)
            egg_log.write("opened inline on Revit's UI thread", "shell")
            return True
        return False
    except Exception:
        return False


def _activate_open():
    """Bring an already open game forward, from whichever thread asks.

    Activate() has to happen on the window's own thread, so it goes through that
    window's dispatcher rather than being called directly.
    """
    for egg in list(_OPEN):
        try:
            window = egg.window
            window.Dispatcher.BeginInvoke(Action(window.Activate))
            return True
        except Exception:
            try:
                _OPEN.remove(egg)
            except Exception:
                pass
    return False


def _handle_of(window):
    if window is None:
        return None
    try:
        handle = WindowInteropHelper(window).Handle
        return handle if handle else None
    except Exception:
        return None


def _error():
    try:
        import traceback
        return traceback.format_exc().replace("\n", " | ")
    except Exception:
        return "unknown"
