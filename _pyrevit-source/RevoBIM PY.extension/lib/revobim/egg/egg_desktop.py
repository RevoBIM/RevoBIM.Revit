# -*- coding: utf-8 -*-
"""RevoBIM Arcade - the desktop build.

The same games, outside Revit, in their own process. Nothing here imports the
Revit API, WPF or `clr`, and nothing in Revit is running while it plays.

This is only possible because of the surface contract. A game draws through
`rect`, `ellipse`, `wedge`, `label` and friends and knows nothing about what is
underneath, so putting a Tk canvas underneath instead of a WPF one is a second
implementation of ten methods rather than a second set of games. `pacman.py` and
`snake.py` are shared byte for byte, and so are the settings, the scoreboard and
the log - which means **the scoreboard is the same board**: a game won at your
desk sits in the same table as one won inside Revit.

Run it with:

    pythonw "RevoBIM Arcade.pyw"          (standalone\\)
    python -m revobim.egg.egg_desktop     (with lib on sys.path)
"""

import os
import sys
import time

try:
    import tkinter
    from tkinter import font as tkfont
except ImportError:                                   # pragma: no cover
    tkinter = None
    tkfont = None

from revobim.egg import __version__ as EGG_VERSION
from revobim.egg import egg_log, egg_registry, egg_scores, egg_settings
from revobim.egg import egg_theme

PAD = 14
HEADER = 46
FOOTER = 30
BOARD_DELAY = 1.4          # seconds of the game over card before the board


# -- colour ==============================================================

def _rgb(value):
    text = str(value).lstrip("#")
    if len(text) == 8:                     # #AARRGGBB, as the veil is
        alpha = int(text[0:2], 16) / 255.0
        return (int(text[2:4], 16), int(text[4:6], 16), int(text[6:8], 16),
                alpha)
    return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16), 1.0)


def flatten(value, backdrop, extra_alpha=1.0):
    """Tk has no alpha, so anything translucent is mixed down onto its backdrop.

    The palette carries one 8-digit colour - the scoreboard veil - and the
    prompt on the game over card fades. Both have to become a solid colour here,
    which is exactly what the compositor would have produced anyway.
    """
    red, green, blue, alpha = _rgb(value)
    back_r, back_g, back_b, _ = _rgb(backdrop)
    alpha = max(0.0, min(1.0, alpha * extra_alpha))
    return "#{0:02x}{1:02x}{2:02x}".format(
        int(back_r + (red - back_r) * alpha),
        int(back_g + (green - back_g) * alpha),
        int(back_b + (blue - back_b) * alpha))


# -- the surface =========================================================

class TkSurface(object):
    """The same ten methods as the WPF surface, over a Tk canvas.

    Retained mode, for the same reason: a game creates each shape once against a
    key and afterwards only moves, refills or removes it.
    """

    def __init__(self, canvas, palette, scale=1.0):
        self.canvas = canvas
        self.palette = palette
        self.scale = scale
        self._items = {}
        self._kinds = {}
        self._sizes = {}
        self._base = {}

    # -- helpers ---------------------------------------------------------

    def colour(self, value, alpha=1.0):
        raw = self.palette.get(value, value)
        return flatten(raw, self.palette["bg"], alpha)

    def brush(self, value):
        """The name the WPF surface uses. See Surface.colour."""
        return self.colour(value)

    def _s(self, value):
        return value * self.scale

    def set_scale(self, scale):
        """Rescale everything already drawn, and everything drawn after.

        Static shapes - the maze, the pellets - are drawn once at the start and
        would otherwise keep their old size for ever. Text needs its font
        resetting too, since `canvas.scale` moves points and leaves glyphs.
        """
        if not scale or abs(scale - self.scale) < 0.001:
            return
        factor = float(scale) / float(self.scale)
        try:
            self.canvas.scale("all", 0, 0, factor, factor)
        except Exception:
            pass
        self.scale = float(scale)
        for key in list(self._items.keys()):
            if self._kinds.get(key) == "text":
                self._font(key)

    def _font(self, key):
        size = max(1, int(round(self._sizes.get(key, (12, False))[0] *
                                self.scale)))
        bold = self._sizes.get(key, (12, False))[1]
        try:
            self.canvas.itemconfigure(
                self._items[key],
                font=("Segoe UI", size, "bold" if bold else "normal"))
        except Exception:
            pass

    def _drop(self, key):
        item = self._items.pop(key, None)
        if item is not None:
            try:
                self.canvas.delete(item)
            except Exception:
                pass
        self._kinds.pop(key, None)
        self._sizes.pop(key, None)
        self._base.pop(key, None)

    # -- shapes ----------------------------------------------------------

    def rect(self, key, x, y, w, h, colour, radius=0):
        fill = self.colour(colour)
        self._base[key] = colour
        points = self._rounded(x, y, w, h, radius)
        item = self._items.get(key)
        if item is not None and self._kinds.get(key) == "rect":
            self.canvas.coords(item, *points)
            self.canvas.itemconfigure(item, fill=fill)
            return item
        self._drop(key)
        item = self.canvas.create_polygon(points, fill=fill, outline="",
                                          smooth=bool(radius))
        self._items[key] = item
        self._kinds[key] = "rect"
        return item

    def _rounded(self, x, y, w, h, radius):
        """A rounded rectangle as a smoothed polygon.

        Tk has no corner radius, and a square maze next to the WPF one would
        look like a different game. Extra points at the corners plus `smooth`
        gets close enough that nobody asks.
        """
        x0, y0 = self._s(x), self._s(y)
        x1, y1 = self._s(x + w), self._s(y + h)
        if not radius:
            return [x0, y0, x1, y0, x1, y1, x0, y1]
        r = min(self._s(radius), (x1 - x0) / 2.0, (y1 - y0) / 2.0)
        return [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r,
                x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1,
                x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]

    def ellipse(self, key, cx, cy, r, colour):
        fill = self.colour(colour)
        self._base[key] = colour
        box = (self._s(cx - r), self._s(cy - r), self._s(cx + r),
               self._s(cy + r))
        item = self._items.get(key)
        if item is not None and self._kinds.get(key) == "oval":
            self.canvas.coords(item, *box)
            self.canvas.itemconfigure(item, fill=fill)
            return item
        self._drop(key)
        item = self.canvas.create_oval(box, fill=fill, outline="")
        self._items[key] = item
        self._kinds[key] = "oval"
        return item

    def wedge(self, key, cx, cy, r, start_deg, sweep_deg, colour):
        """A pie slice.

        Tk measures angles anticlockwise from east; the games are written for
        WPF, where a positive angle turns clockwise because the y axis points
        down. So both the start and the sweep are negated. Get this wrong and
        Pacman's mouth faces backwards, which is the sort of thing that looks
        like a physics bug.
        """
        fill = self.colour(colour)
        self._base[key] = colour
        sweep = max(0.1, min(359.9, sweep_deg))
        box = (self._s(cx - r), self._s(cy - r), self._s(cx + r),
               self._s(cy + r))
        item = self._items.get(key)
        if item is not None and self._kinds.get(key) == "arc":
            self.canvas.coords(item, *box)
            self.canvas.itemconfigure(item, start=-start_deg, extent=-sweep,
                                      fill=fill)
            return item
        self._drop(key)
        item = self.canvas.create_arc(box, start=-start_deg, extent=-sweep,
                                      style=tkinter.PIESLICE, fill=fill,
                                      outline="")
        self._items[key] = item
        self._kinds[key] = "arc"
        return item

    def label(self, key, x, y, text, size=12, colour="text", bold=False):
        fill = self.colour(colour)
        self._base[key] = colour
        item = self._items.get(key)
        if item is not None and self._kinds.get(key) == "text":
            self.canvas.coords(item, self._s(x), self._s(y))
            self.canvas.itemconfigure(item, text=text, fill=fill)
            self._sizes[key] = (size, bold)
            self._font(key)
            return item
        self._drop(key)
        item = self.canvas.create_text(
            self._s(x), self._s(y), text=text, fill=fill, anchor="nw",
            font=("Segoe UI", max(1, int(round(size * self.scale))),
                  "bold" if bold else "normal"))
        self._items[key] = item
        self._kinds[key] = "text"
        self._sizes[key] = (size, bold)
        return item

    def banner(self, key, y, width, text, size=15, colour="orange",
               behind="bg"):
        self.rect(key + "_bg", 0, y - (size + 6) / 2.0, width, size + 12,
                  behind, 4)
        item = self.label(key, 0, y - (size + 1) / 2.0, text, size, colour,
                          True)
        try:
            self.canvas.itemconfigure(item, width=self._s(width),
                                      justify="center")
            self.canvas.coords(item, self._s(width / 2.0),
                               self._s(y - (size + 1) / 2.0))
            self.canvas.itemconfigure(item, anchor="n")
        except Exception:
            pass
        return item

    def drop_banner(self, key):
        self.remove(key)
        self.remove(key + "_bg")

    # -- updates ---------------------------------------------------------

    def alpha(self, key, value):
        base = self._base.get(key)
        if base is None or key not in self._items:
            return
        # No per-item opacity in Tk, so the fade is mixed down onto the
        # background instead. The eye cannot tell the difference here.
        try:
            self.canvas.itemconfigure(self._items[key],
                                      fill=self.colour(base, value))
        except Exception:
            pass

    def lift(self, key):
        item = self._items.get(key)
        if item is not None:
            try:
                self.canvas.tag_raise(item)
            except Exception:
                pass

    def move(self, key, x, y):
        item = self._items.get(key)
        if item is None:
            return
        try:
            self.canvas.coords(item, self._s(x), self._s(y))
        except Exception:
            pass

    def move_centre(self, key, cx, cy):
        self.move(key, cx, cy)

    def fill(self, key, colour):
        item = self._items.get(key)
        if item is None:
            return
        self._base[key] = colour
        try:
            self.canvas.itemconfigure(item, fill=self.colour(colour))
        except Exception:
            pass

    def show(self, key, visible):
        item = self._items.get(key)
        if item is None:
            return
        try:
            self.canvas.itemconfigure(item,
                                      state="normal" if visible else "hidden")
        except Exception:
            pass

    def has(self, key):
        return key in self._items

    def remove(self, key):
        self._drop(key)

    def clear(self):
        try:
            self.canvas.delete("all")
        except Exception:
            pass
        self._items = {}
        self._kinds = {}
        self._sizes = {}
        self._base = {}


# -- the window ==========================================================

class Arcade(object):

    def __init__(self, game_key=None):
        self.settings = egg_settings.load()
        name = egg_theme.resolve(None, self.settings.get("theme"))
        self.theme_name = name
        self.palette = egg_theme.palette(name)
        self.game_key = game_key or self.settings.get("game", "pacman")
        self.module = egg_registry.pick(self.game_key)
        self.game = None
        self.surface = None
        self.board = None
        self.full = False
        self.recorded = False
        self.dismissed = False
        self.over_at = None
        self.last_entry = None
        self.last_place = 0
        self.owed = 0.0
        self.mark = None
        self.running = False

    def run(self):
        if tkinter is None:
            sys.stderr.write(
                "RevoBIM Arcade needs Python with tkinter, which is included "
                "in the standard python.org installer.\n")
            return 2
        if self.module is None:
            sys.stderr.write("No games found beside this script.\n")
            return 3

        self.step = float(getattr(self.module, "TICK_MS", 33)) / 1000.0
        self.root = tkinter.Tk()
        self.root.title("RevoBIM Arcade")
        self.root.configure(bg=self.palette["bg"])
        self.root.minsize(560, 380)
        self._build()
        self._restart()

        self.root.bind("<Key>", self._on_key)
        self.root.protocol("WM_DELETE_WINDOW", self._quit)
        self.running = True
        self.mark = time.time()
        self._tick()
        egg_log.write("desktop build started, game {0}".format(self.game_key),
                      "arcade")
        self.root.mainloop()
        return 0

    # -- chrome ----------------------------------------------------------

    def _build(self):
        palette = self.palette

        header = tkinter.Frame(self.root, bg=palette["bar"], height=HEADER)
        header.pack(fill="x")
        header.pack_propagate(False)

        tkinter.Label(header, text="RevoBIM", bg=palette["bar"],
                      fg=palette["blue"],
                      font=("Segoe UI", 15, "bold")).pack(side="left",
                                                          padx=(PAD, 6))
        tkinter.Label(header, text=self.module.NAME, bg=palette["bar"],
                      fg=palette["orange"],
                      font=("Segoe UI", 11)).pack(side="left")

        tkinter.Label(header, text="v" + EGG_VERSION, bg=palette["bar"],
                      fg=palette["muted"],
                      font=("Segoe UI", 8)).pack(side="right", padx=(6, PAD))
        self._chip(header, "Scores", self._toggle_board)
        self._chip(header, "Theme", self._cycle_theme)
        self._chip(header, self.module.NAME, self._next_game)

        body = tkinter.Frame(self.root, bg=palette["bg"])
        body.pack(fill="both", expand=True, padx=PAD, pady=(0, 0))
        self.body = body

        self.canvas = tkinter.Canvas(body, bg=palette["card"],
                                     highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", self._on_resize)

        footer = tkinter.Frame(self.root, bg=palette["bar"], height=FOOTER)
        footer.pack(fill="x")
        footer.pack_propagate(False)
        self.status = tkinter.Label(footer, text="", bg=palette["bar"],
                                    fg=palette["text"],
                                    font=("Segoe UI", 9))
        self.status.pack(side="left", padx=PAD)
        tkinter.Label(footer, text=self.module.KEYS + "   Tab scores",
                      bg=palette["bar"], fg=palette["muted"],
                      font=("Segoe UI", 8)).pack(side="right", padx=PAD)

        probe = self.module.Game(None, self.settings)
        self.board_w = probe.width()
        self.board_h = probe.height()
        self.root.geometry("{0}x{1}".format(
            max(self.board_w + PAD * 2 + 10, 560),
            self.board_h + HEADER + FOOTER + 16))

    def _chip(self, parent, text, command):
        chip = tkinter.Label(parent, text=text, bg=self.palette["card"],
                             fg=self.palette["muted"],
                             font=("Segoe UI", 8), padx=8, pady=2,
                             cursor="hand2")
        chip.pack(side="right", padx=3)
        chip.bind("<Button-1>", lambda event: command())
        return chip

    # -- the loop --------------------------------------------------------

    def _restart(self):
        self.surface = TkSurface(self.canvas, self.palette, self._scale())
        self.game = self.module.Game(self.surface, self.settings)
        self.game.start()
        self.recorded = False
        self.dismissed = False
        self.over_at = None
        self.last_entry = None
        self.last_place = 0
        self.owed = 0.0
        self.mark = time.time()
        self._hide_board()

    def _scale(self):
        try:
            width = max(1, self.canvas.winfo_width())
            height = max(1, self.canvas.winfo_height())
        except Exception:
            return 1.0
        if width < 20 or height < 20:
            return 1.0
        return max(0.35, min(float(width) / self.board_w,
                             float(height) / self.board_h))

    def _on_resize(self, event=None):
        if self.surface is not None:
            self.surface.set_scale(self._scale())

    def _tick(self):
        if not self.running:
            return
        try:
            now = time.time()
            elapsed = now - (self.mark or now)
            self.mark = now
            if elapsed > 0.25:
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
                self._watch_for_finish()
        except Exception:
            self.running = False
            egg_log.write("desktop loop stopped: {0}".format(
                sys.exc_info()[1]), "arcade")
            try:
                self.status.configure(text="The game stopped. Esc to close.")
            except Exception:
                pass
            return
        # 16ms is about as often as Tk will usefully repaint, and the fixed
        # logic step above means the game does not care what it actually gets.
        self.root.after(16, self._tick)

    def _update_status(self):
        score = getattr(self.game, "score", 0)
        best = egg_settings.high_score(self.settings, self.game_key)
        if score > best:
            egg_settings.set_high_score(self.settings, self.game_key, score)
            best = score
        self.status.configure(text="{0}    Best {1}".format(
            self.game.status(), best))

    def _watch_for_finish(self):
        if not self.game.is_over():
            return
        if not self.recorded:
            self.recorded = True
            self.over_at = time.time()
            try:
                entry, place, total = egg_scores.record(
                    self.game_key, getattr(self.game, "score", 0),
                    self.settings)
                self.last_entry = entry
                self.last_place = place
            except Exception:
                self.last_entry = None
            return
        if self.board is not None or self.dismissed:
            return
        if str(self.settings.get("scores_on_finish", "on")).lower() != "on":
            return
        if time.time() - self.over_at >= BOARD_DELAY:
            self._show_board()

    # -- the scoreboard --------------------------------------------------

    def _toggle_board(self):
        if self.board is not None:
            self.dismissed = True
            self._hide_board()
        else:
            self._show_board()

    def _hide_board(self):
        if self.board is not None:
            try:
                self.board.destroy()
            except Exception:
                pass
        self.board = None

    def _show_board(self):
        self._hide_board()
        palette = self.palette
        shown = egg_settings.get_int(self.settings, "scores_shown", 15)
        table = egg_scores.ranked(self.game_key, shown)
        me = egg_scores.player_name(self.settings)

        card = tkinter.Frame(self.canvas,
                             bg=flatten(palette["veil"], palette["card"]),
                             padx=22, pady=14)
        card.place(relx=0.5, rely=0.5, anchor="center")
        self.board = card

        head = tkinter.Frame(card, bg=card["bg"])
        head.pack()
        tkinter.Label(head, text="HIGH SCORES", bg=card["bg"],
                      fg=palette["blue"],
                      font=("Segoe UI", 13, "bold")).pack(side="left")
        tkinter.Label(head, text=self.module.NAME, bg=card["bg"],
                      fg=palette["orange"],
                      font=("Segoe UI", 10)).pack(side="left", padx=(8, 0))

        grid = tkinter.Frame(card, bg=card["bg"])
        grid.pack(pady=(10, 0))
        if not table:
            tkinter.Label(grid, text="Nothing on the board yet. Go and lose "
                                     "a game.", bg=card["bg"],
                          fg=palette["muted"],
                          font=("Segoe UI", 9)).pack()
        else:
            self._row(grid, 0, "#", "Player", "Score", "When",
                      palette["muted"], False, 8)
            for index in range(len(table)):
                entry = table[index]
                mine = (self.last_entry is not None
                        and entry["when"] == self.last_entry["when"]
                        and entry["player"] == self.last_entry["player"]
                        and entry["score"] == self.last_entry["score"])
                colour = palette["orange"] if mine else (
                    palette["text"] if entry["player"] == me
                    else palette["muted"])
                self._row(grid, index + 1, str(index + 1), entry["player"],
                          str(entry["score"]),
                          egg_scores.pretty_when(entry["when"]),
                          colour, mine, 9)

        tkinter.Label(card, text="press R to play again    -    Tab to close",
                      bg=card["bg"], fg=palette["muted"],
                      font=("Segoe UI", 8)).pack(pady=(10, 0))
        tkinter.Label(card, text="Now get back to work!", bg=card["bg"],
                      fg=palette["orange"],
                      font=("Segoe UI", 10, "bold")).pack(pady=(8, 0))

    def _row(self, parent, index, place, player, score, when, colour, bold,
             size):
        weight = "bold" if bold else "normal"
        widths = ((place, 4, "w"), (player, 18, "w"), (score, 8, "e"),
                  (when, 14, "e"))
        for column in range(len(widths)):
            text, width, anchor = widths[column]
            tkinter.Label(parent, text=text, bg=parent["bg"], fg=colour,
                          width=width, anchor=anchor,
                          font=("Segoe UI", size, weight)).grid(
                row=index, column=column, sticky="ew")

    # -- input -----------------------------------------------------------

    def _on_key(self, event):
        key = (event.keysym or "").lower()
        if key == "tab":
            self._toggle_board()
            return
        if key == "f11":
            self._toggle_full()
            return
        if key == "escape":
            if self.board is not None:
                self.dismissed = True
                self._hide_board()
            elif self.full:
                self._toggle_full()
            else:
                self._quit()
            return
        if key == "r":
            self._restart()
            return
        if self.board is not None:
            return
        name = {"up": "Up", "down": "Down", "left": "Left", "right": "Right",
                "w": "W", "a": "A", "s": "S", "d": "D", "space": "Space",
                "p": "P"}.get(key)
        if name and self.game is not None:
            try:
                self.game.key(name)
            except Exception:
                pass

    def _toggle_full(self):
        self.full = not self.full
        try:
            self.root.attributes("-fullscreen", self.full)
        except Exception:
            self.full = False
        self.root.after(60, self._on_resize)

    def _next_game(self):
        self.settings["game"] = egg_registry.next_after(self.game_key)
        egg_settings.save(self.settings)
        self.game_key = self.settings["game"]
        self.module = egg_registry.pick(self.game_key)
        self._reload()

    def _cycle_theme(self):
        order = ("auto", "dark", "light")
        current = self.settings.get("theme", "auto")
        if current not in order:
            current = "auto"
        self.settings["theme"] = order[(order.index(current) + 1) % len(order)]
        egg_settings.save(self.settings)
        self._reload()

    def _reload(self):
        """Rebuild the window rather than re-theme it in place.

        The same call the Revit build makes, for the same reason: repainting
        every widget is a lot of code for something used twice a session.
        """
        self.running = False
        try:
            self.root.destroy()
        except Exception:
            pass
        Arcade(self.settings.get("game")).run()

    def _quit(self):
        self.running = False
        try:
            self.root.destroy()
        except Exception:
            pass


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    wanted = argv[0] if argv else None
    return Arcade(wanted).run()


if __name__ == "__main__":                            # pragma: no cover
    # Run straight from the egg folder as well as through the launcher.
    here = os.path.dirname(os.path.abspath(__file__))
    lib = os.path.abspath(os.path.join(here, "..", ".."))
    if lib not in sys.path:
        sys.path.insert(0, lib)
    sys.exit(main())
