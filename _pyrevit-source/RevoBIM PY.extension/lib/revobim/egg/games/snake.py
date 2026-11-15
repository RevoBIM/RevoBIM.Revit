# -*- coding: utf-8 -*-
"""Snake.

Here mostly to prove the point: a second game, written against exactly the same
contract as Pacman, in a fifth of the code. Nothing outside this file knows
which game is running.
"""

import random

NAME = "Snake"
KEY = "snake"
TICK_MS = 110
KEYS = "Arrows / WASD turn   P pause   R restart   F11 full screen   Esc close"

CELL = 18
COLS = 19
ROWS = 21

UP = (0, -1)
DOWN = (0, 1)
LEFT = (-1, 0)
RIGHT = (1, 0)

KEY_DIRS = {
    "Up": UP, "W": UP,
    "Down": DOWN, "S": DOWN,
    "Left": LEFT, "A": LEFT,
    "Right": RIGHT, "D": RIGHT,
}

RANKS = (
    (0, "Cable Puller"),
    (60, "Containment Fitter"),
    (150, "Riser Wrangler"),
    (280, "Tray Tsar"),
    (450, "Lord of the Basket"),
)

SIGN_OFFS = (
    "Route rejected by the ceiling void.",
    "Clashed with itself. Again.",
    "That is going to need a transition piece.",
    "Coordination comment: see attached.",
)


class Game(object):

    def __init__(self, surface, settings):
        self.s = surface
        self.settings = settings
        self.score = 0
        self.over = False
        self.state = "run"
        self.body = []
        self.dir = RIGHT
        self.want = RIGHT
        self.food = None
        self.prev_body = []
        self.paint = 0
        self.overlay = False
        self.sign_off = SIGN_OFFS[0]
        self.best_at_start = 0

    def width(self):
        return COLS * CELL

    def height(self):
        return ROWS * CELL

    def start(self):
        self.s.clear()
        self.s.rect("floor", 0, 0, self.width(), self.height(),
                    "field", 4)
        middle = ROWS // 2
        self.body = [(6, middle), (5, middle), (4, middle)]
        self.prev_body = list(self.body)
        self.dir = RIGHT
        self.want = RIGHT
        self.score = 0
        self.over = False
        self.overlay = False
        self.state = "run"
        self.best_at_start = _as_int((self.settings or {}).get(
            "high_" + KEY, 0))
        self._place_food()

    def stop(self):
        pass

    def status(self):
        return "Score {0}    Length {1}".format(self.score, len(self.body))

    def is_over(self):
        return self.over

    def key(self, name):
        if name in ("P", "Space"):
            if self.state == "run":
                self.state = "paused"
                self.s.banner("msg", self.height() / 2.0, self.width(),
                              "PAUSED", 15, "orange")
            elif self.state == "paused":
                self.state = "run"
                self.s.drop_banner("msg")
            return
        wanted = KEY_DIRS.get(name)
        if not wanted or self.over:
            return
        # A snake cannot double back on itself.
        if (wanted[0] + self.dir[0], wanted[1] + self.dir[1]) == (0, 0):
            return
        self.want = wanted

    def tick(self):
        if self.over or self.state != "run":
            return
        self.dir = self.want
        head = self.body[0]
        nxt = (head[0] + self.dir[0], head[1] + self.dir[1])

        if (nxt[0] < 0 or nxt[0] >= COLS or nxt[1] < 0 or nxt[1] >= ROWS
                or nxt in self.body[:-1]):
            self.over = True
            self.sign_off = random.choice(SIGN_OFFS)
            return

        self.prev_body = list(self.body)
        self.body.insert(0, nxt)
        if nxt == self.food:
            self.score += 10
            self._place_food()
        else:
            tail = self.body.pop()
            self.s.remove("s{0}_{1}".format(tail[0], tail[1]))

    # -- internals =======================================================

    def _place_food(self):
        free = []
        for col in range(COLS):
            for row in range(ROWS):
                if (col, row) not in self.body:
                    free.append((col, row))
        if not free:
            self.over = True
            return
        self.food = random.choice(free)
        self.s.ellipse("food",
                       self.food[0] * CELL + CELL / 2.0,
                       self.food[1] * CELL + CELL / 2.0,
                       CELL / 2.0 - 4, "power")

    # -- drawing =========================================================

    def render(self, alpha):
        """Draw one frame, sliding each segment towards where it is going.

        A snake that jumps a whole cell every 110ms reads as a slideshow. Each
        segment is drawn between the cell it was in and the cell it is in, which
        costs nothing and looks like a different game.
        """
        self.paint += 1
        if self.over:
            self._draw_over()
            return
        if self.state == "paused":
            alpha = 1.0

        for index in range(len(self.body)):
            col, row = self.body[index]
            was = self.prev_body[index] if index < len(self.prev_body) \
                else (col, row)
            x = (was[0] + (col - was[0]) * alpha) * CELL + 2
            y = (was[1] + (row - was[1]) * alpha) * CELL + 2
            colour = "green" if index else "hero"
            self.s.rect("s{0}_{1}".format(col, row), x, y,
                        CELL - 4, CELL - 4, colour, 4)

    def _draw_over(self):
        width = self.width()
        beat = self.score > self.best_at_start
        if not self.overlay:
            self.overlay = True
            self.s.rect("veil", 0, 0, width, self.height(), "veil")
            top = self.height() / 2.0 - 60
            self.s.banner("over_title", top + 16, width,
                          "NEW BEST" if beat else "GAME OVER", 24,
                          "green" if beat else "red", "veil")
            self.s.banner("over_score", top + 54, width,
                          "{0} points   -   {1} long".format(
                              self.score, len(self.body)), 14, "hero", "veil")
            self.s.banner("over_rank", top + 82, width, _rank(self.score),
                          14, "blue", "veil")
            self.s.banner("over_note", top + 106, width, self.sign_off, 11,
                          "muted", "veil")
            self.s.banner("over_again", top + 136, width,
                          "press R to play again", 12, "orange", "veil")
            self.s.lift("veil")
            for key in ("over_title", "over_score", "over_rank", "over_note",
                        "over_again"):
                self.s.lift(key + "_bg")
                self.s.lift(key)
        self.s.alpha("over_again", 0.55 + 0.45 * _wave(self.paint))


def _wave(frame):
    span = 70.0
    position = (frame % (span * 2)) / span
    return position if position <= 1.0 else 2.0 - position


def _rank(score):
    title = RANKS[0][1]
    for threshold, name in RANKS:
        if score >= threshold:
            title = name
    return title


def _as_int(value):
    try:
        return int(str(value).strip())
    except Exception:
        return 0
