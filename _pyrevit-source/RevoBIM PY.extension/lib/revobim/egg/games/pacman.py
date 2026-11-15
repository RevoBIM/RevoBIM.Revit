# -*- coding: utf-8 -*-
"""Pacman.

No Revit API, no WPF, no System.* - everything is drawn through the surface
handed in. That is the whole point of the contract: this file is plain Python
and runs on the bench under CPython as happily as it does in IronPython.

`tick()` is logic only and `render(alpha)` is drawing only. The shell runs the
logic on a fixed step and draws every frame the display gives it, handing in how
far between the last two logic steps that frame falls. Everything that moves is
drawn at that fraction between where it was and where it is, which turns a
30-step-per-second game into 60fps motion without touching the integer grid
arithmetic the whole thing depends on.
"""

import random

NAME = "Pacman"
KEY = "pacman"
TICK_MS = 33
KEYS = "Arrows / WASD move   P pause   R restart   F11 full screen   Esc close"

CELL = 18
HALF = CELL // 2

# '#' wall   '.' pellet   'o' power pellet   '-' ghost house door
# ' ' empty  'P' hero start   'G' ghost start
MAZE = [
    "###################",
    "#........#........#",
    "#o##.###.#.###.##o#",
    "#.................#",
    "#.##.#.#####.#.##.#",
    "#....#...#...#....#",
    "####.###.#.###.####",
    "####.#.......#.####",
    "####.#.##-##.#.####",
    ".....#.#GGG#.#.....",
    "####.#.#####.#.####",
    "####.#.......#.####",
    "####.###.#.###.####",
    "#........#........#",
    "#.##.###.#.###.##.#",
    "#o.#.....P.....#.o#",
    "##.#.#.#####.#.#.##",
    "#....#...#...#....#",
    "#.####.#####.####.#",
    "#.................#",
    "###################",
]

UP = (0, -1)
DOWN = (0, 1)
LEFT = (-1, 0)
RIGHT = (1, 0)
STOP = (0, 0)

DIRS = (UP, DOWN, LEFT, RIGHT)

KEY_DIRS = {
    "Up": UP, "W": UP,
    "Down": DOWN, "S": DOWN,
    "Left": LEFT, "A": LEFT,
    "Right": RIGHT, "D": RIGHT,
}

ANGLES = {UP: 270, DOWN: 90, LEFT: 180, RIGHT: 0, STOP: 0}

HERO_SPEED = 3
GHOST_SPEED = 2
SCARED_SPEED = 1
EYES_SPEED = 6

# One life. Losing is meant to be quick and often - this is a thing somebody
# opens for ninety seconds, and three lives is three times as long before the
# scoreboard, which is the actual point of the game.
LIVES = 1

SCARED_TICKS = 240
READY_TICKS = 45
DEATH_TICKS = 90

GHOSTS = (
    {"name": "blinky", "colour": "ghost_1", "release": 0, "corner": (17, 1)},
    {"name": "pinky", "colour": "ghost_2", "release": 60, "corner": (1, 1)},
    {"name": "inky", "colour": "ghost_3", "release": 150, "corner": (17, 19)},
    {"name": "clyde", "colour": "ghost_4", "release": 260, "corner": (1, 19)},
)

# Score bands, low to high. Losing on 40 points should not read the same as
# losing on 9000.
RANKS = (
    (0, "Setting Out Apprentice"),
    (400, "Draughtsperson, Second Class"),
    (1200, "Junior BIM Coordinator"),
    (2400, "MEP Coordinator"),
    (4000, "Clash Detective"),
    (6500, "Lead Services Engineer"),
    (9500, "Model Federation Overlord"),
)

SIGN_OFFS = (
    "The ghosts have raised an RFI.",
    "Marked up in red and returned.",
    "Rejected at technical review.",
    "Superseded. Try P02.",
    "Clash count: 1. Yours.",
    "That one is going in the issue log.",
    "Please resubmit with a coordinated route.",
)


class Game(object):

    def __init__(self, surface, settings):
        self.s = surface
        self.settings = settings or {}
        self.cols = len(MAZE[0])
        self.rows = len(MAZE)
        self.hero_cell = self._find("P")
        self.house_cell = self._find("G")
        self.door_cell = self._find("-")
        self.score = 0
        self.lives = LIVES
        self.level = 1
        self.over = False
        self.state = "ready"
        self.wait = READY_TICKS
        self.frame = 0
        self.paint = 0
        self.pellets = {}
        self.hero = None
        self.ghosts = []
        self.scared = 0
        self.chain = 0
        self.eaten_pellets = 0
        self.eaten_ghosts = 0
        self.best_at_start = 0
        self.sign_off = SIGN_OFFS[0]
        self.overlay = False

    # -- what the shell asks for =========================================

    def width(self):
        return self.cols * CELL

    def height(self):
        return self.rows * CELL

    def start(self):
        self.s.clear()
        self.best_at_start = _as_int(self.settings.get("high_" + KEY, 0))
        self._draw_walls()
        self._fill_pellets()
        self._reset_movers()
        self._message("READY")

    def stop(self):
        pass

    def status(self):
        if LIVES > 1:
            lives = "*" * max(0, self.lives)
            return "Score {0}    Level {1}    Lives {2}".format(
                self.score, self.level, lives if lives else "-")
        # One life is not a counter, so the footer says something useful with
        # the room instead.
        return "Score {0}    Level {1}    Pellets {2}".format(
            self.score, self.level, self.eaten_pellets)

    def is_over(self):
        return self.over

    def key(self, name):
        if self.over:
            return
        if name in ("P", "Space"):
            if self.state == "run":
                self.state = "paused"
                self._message("PAUSED")
            elif self.state == "paused":
                self.state = "run"
                self._message(None)
            return
        wanted = KEY_DIRS.get(name)
        if wanted and self.hero:
            self.hero["want"] = wanted

    # -- logic ===========================================================

    def tick(self):
        self.frame += 1

        if self.state in ("paused", "over"):
            return

        if self.state in ("ready", "dying"):
            self.wait -= 1
            if self.wait > 0:
                return
            if self.state == "dying":
                if self.lives <= 0:
                    self._game_over()
                    return
                self._reset_movers()
                self.state = "ready"
                self.wait = READY_TICKS
                self._message("READY")
                return
            self.state = "run"
            self._message(None)
            return

        if self.scared > 0:
            self.scared -= 1
            if self.scared == 0:
                self.chain = 0

        self._remember(self.hero)
        for ghost in self.ghosts:
            self._remember(ghost)

        self._move_hero()
        self._eat()
        for ghost in self.ghosts:
            self._move_ghost(ghost)
        self._collide()

        if not self.pellets:
            self._next_level()

    def _remember(self, mover):
        mover["px"] = mover["x"]
        mover["py"] = mover["y"]

    # -- maze ============================================================

    def _at(self, col, row):
        if row < 0 or row >= self.rows:
            return "#"
        return MAZE[row][col % self.cols]

    def _walkable(self, col, row, ghost=False):
        char = self._at(col, row)
        if char == "#":
            return False
        if char == "-":
            return ghost
        return True

    def _draw_walls(self):
        for row in range(self.rows):
            for col in range(self.cols):
                char = MAZE[row][col]
                if char == "#":
                    self.s.rect("w{0}_{1}".format(col, row),
                                col * CELL + 1, row * CELL + 1,
                                CELL - 2, CELL - 2, "maze", 4)
                elif char == "-":
                    self.s.rect("d{0}_{1}".format(col, row),
                                col * CELL + 1, row * CELL + HALF - 1,
                                CELL - 2, 2, "power")

    def _fill_pellets(self):
        self.pellets = {}
        for row in range(self.rows):
            for col in range(self.cols):
                char = MAZE[row][col]
                if char not in (".", "o"):
                    continue
                self.pellets[(col, row)] = char
                cx = col * CELL + HALF
                cy = row * CELL + HALF
                if char == "o":
                    self.s.ellipse(self._pkey(col, row), cx, cy, 4.5, "power")
                else:
                    self.s.ellipse(self._pkey(col, row), cx, cy, 1.8, "pellet")

    def _pkey(self, col, row):
        return "p{0}_{1}".format(col, row)

    # -- movers ==========================================================

    def _centre(self, col, row):
        return (col * CELL + HALF, row * CELL + HALF)

    def _find(self, char):
        for row in range(len(MAZE)):
            for col in range(len(MAZE[0])):
                if MAZE[row][col] == char:
                    return (col, row)
        return (1, 1)

    def _reset_movers(self):
        col, row = self.hero_cell
        x, y = self._centre(col, row)
        self.hero = {"x": x, "y": y, "px": x, "py": y,
                     "dir": LEFT, "want": LEFT}

        house = self.house_cell
        self.ghosts = []
        for index in range(len(GHOSTS)):
            spec = GHOSTS[index]
            hx, hy = self._centre(house[0] + (index % 3), house[1])
            self.ghosts.append({
                "spec": spec,
                "x": hx, "y": hy, "px": hx, "py": hy, "hy": hy,
                "dir": UP,
                "home": True,
                "released": False,
                "eyes": False,
                "timer": spec["release"],
                "index": index,
            })
        self.scared = 0
        self.chain = 0

    def _cell(self, mover):
        return (((mover["x"] - HALF) // CELL) % self.cols,
                (mover["y"] - HALF) // CELL)

    def _aligned(self, mover):
        return ((mover["x"] - HALF) % CELL == 0 and
                (mover["y"] - HALF) % CELL == 0)

    def _next_align(self, value, step):
        offset = (value - HALF) % CELL
        if step > 0:
            return value + (CELL - offset if offset else CELL)
        return value - (offset if offset else CELL)

    def _advance(self, mover, speed):
        """Move, but never past the next cell centre.

        Without the clamp a mover whose speed changes mid-cell - a ghost turning
        frightened, or turning back into eyes - steps straight over the
        alignment point it makes its decisions on, and from then on it never
        turns again.
        """
        dx, dy = mover["dir"]
        if dx == 0 and dy == 0:
            return
        if dx:
            target = self._next_align(mover["x"], dx)
            moved = mover["x"] + dx * speed
            if (dx > 0 and moved > target) or (dx < 0 and moved < target):
                moved = target
            mover["x"] = moved
        else:
            target = self._next_align(mover["y"], dy)
            moved = mover["y"] + dy * speed
            if (dy > 0 and moved > target) or (dy < 0 and moved < target):
                moved = target
            mover["y"] = moved
        width = self.cols * CELL
        if mover["x"] < 0:
            mover["x"] += width
        elif mover["x"] >= width:
            mover["x"] -= width

    def _move_hero(self):
        hero = self.hero
        if self._aligned(hero):
            col, row = self._cell(hero)
            want = hero["want"]
            if want != STOP and self._walkable(col + want[0], row + want[1]):
                hero["dir"] = want
            forward = hero["dir"]
            if not self._walkable(col + forward[0], row + forward[1]):
                hero["dir"] = STOP
        self._advance(hero, HERO_SPEED)

    def _move_ghost(self, ghost):
        speed = GHOST_SPEED
        if ghost["eyes"]:
            speed = EYES_SPEED
        elif self.scared > 0:
            speed = SCARED_SPEED

        if ghost["home"]:
            ghost["timer"] -= 1
            if ghost["timer"] > 0:
                # Bob on the spot so the house does not look frozen. The offset
                # is thrown away on release: a ghost that comes out of the house
                # a pixel off the grid never aligns again, and so never turns
                # again for the rest of the game.
                ghost["y"] = ghost["hy"] + (2 if (self.frame // 12) % 2 else -2)
                return
            if not ghost["released"]:
                # Once only. Doing this every tick while the ghost is still
                # working its way across the house re-points it upwards into the
                # ceiling on every frame, and it never gets out.
                ghost["y"] = ghost["hy"]
                ghost["dir"] = UP
                ghost["released"] = True
            target = self.door_cell
        elif ghost["eyes"]:
            target = self.house_cell
        else:
            target = self._target(ghost)

        if self._aligned(ghost):
            col, row = self._cell(ghost)
            if ghost["home"] and row <= target[1]:
                ghost["home"] = False
                ghost["dir"] = UP
            if ghost["eyes"] and (col, row) == target:
                ghost["eyes"] = False
                ghost["home"] = True
                ghost["released"] = False
                ghost["timer"] = 45
                return
            ghost["dir"] = self._choose(ghost, col, row, target)
        self._advance(ghost, speed)

    def _target(self, ghost):
        hero_col, hero_row = self._cell(self.hero)
        hero_col = int(hero_col)
        hero_row = int(hero_row)
        dx, dy = self.hero["dir"]
        name = ghost["spec"]["name"]
        if self.scared > 0:
            return ghost["spec"]["corner"]
        if name == "blinky":
            return (hero_col, hero_row)
        if name == "pinky":
            return (hero_col + dx * 4, hero_row + dy * 4)
        if name == "inky":
            return (hero_col + dx * 2, hero_row + dy * 2)
        col, row = self._cell(ghost)
        far = abs(int(col) - hero_col) + abs(int(row) - hero_row)
        if far > 8:
            return (hero_col, hero_row)
        return ghost["spec"]["corner"]

    def _choose(self, ghost, col, row, target):
        col = int(col)
        row = int(row)
        back = (-ghost["dir"][0], -ghost["dir"][1])
        options = []
        for option in DIRS:
            if option == back:
                continue
            if self._walkable(col + option[0], row + option[1],
                              ghost=ghost["eyes"] or ghost["home"]):
                options.append(option)
        if not options:
            return back
        if self.scared > 0 and not ghost["eyes"]:
            return random.choice(options)
        best = None
        best_gap = None
        for option in options:
            gap = ((col + option[0] - target[0]) ** 2 +
                   (row + option[1] - target[1]) ** 2)
            if best_gap is None or gap < best_gap:
                best_gap = gap
                best = option
        return best

    # -- rules ===========================================================

    def _eat(self):
        if not self._aligned(self.hero):
            return
        col, row = self._cell(self.hero)
        cell = (int(col), int(row))
        char = self.pellets.pop(cell, None)
        if char is None:
            return
        self.s.remove(self._pkey(cell[0], cell[1]))
        self.eaten_pellets += 1
        if char == "o":
            self.score += 50
            self.scared = SCARED_TICKS
            self.chain = 0
            for ghost in self.ghosts:
                if not ghost["eyes"] and not ghost["home"]:
                    ghost["dir"] = (-ghost["dir"][0], -ghost["dir"][1])
        else:
            self.score += 10

    def _collide(self):
        for ghost in self.ghosts:
            if ghost["eyes"] or ghost["home"]:
                continue
            gap = (abs(ghost["x"] - self.hero["x"]) +
                   abs(ghost["y"] - self.hero["y"]))
            if gap > CELL * 0.8:
                continue
            if self.scared > 0:
                self.chain += 1
                self.eaten_ghosts += 1
                self.score += 200 * (2 ** (self.chain - 1))
                ghost["eyes"] = True
                return
            # The death animation plays either way. Going straight to the card
            # on the last life means never seeing it, which on one life means
            # never seeing it at all.
            self.lives -= 1
            self.state = "dying"
            self.wait = DEATH_TICKS
            return

    def _game_over(self):
        self.over = True
        self.state = "over"
        self.sign_off = random.choice(SIGN_OFFS)
        self._message(None)

    def _next_level(self):
        self.level += 1
        self.s.clear()
        self._draw_walls()
        self._fill_pellets()
        self._reset_movers()
        self.state = "ready"
        self.wait = READY_TICKS
        self._message("LEVEL {0}".format(self.level))

    # -- drawing =========================================================

    def render(self, alpha):
        """Draw one frame. `alpha` is 0..1 between the last two logic steps."""
        self.paint += 1

        if self.state == "over":
            self._draw_over()
            return

        if self.state == "dying":
            self._draw_death()
            for ghost in self.ghosts:
                index = ghost["index"]
                for key in ("gb{0}", "ge{0}a", "ge{0}b", "gp{0}a", "gp{0}b"):
                    self.s.show(key.format(index), False)
            return

        if self.state in ("ready", "paused"):
            alpha = 1.0

        self._draw_hero(alpha)
        for ghost in self.ghosts:
            self._draw_ghost(ghost, alpha)

    def _lerp(self, mover, alpha):
        """Where to draw a mover this frame.

        A mover that has just come through the tunnel is a whole board width
        away from where it was, so interpolating it would fling it back across
        the screen. That one frame is drawn where it actually is.
        """
        x, y = mover["x"], mover["y"]
        px, py = mover.get("px", x), mover.get("py", y)
        if abs(x - px) > CELL or abs(y - py) > CELL:
            return (x, y)
        return (px + (x - px) * alpha, py + (y - py) * alpha)

    def _draw_hero(self, alpha):
        x, y = self._lerp(self.hero, alpha)
        angle = ANGLES[self.hero["dir"]]
        # The mouth is driven off distance travelled rather than frame count, so
        # it chews at the speed it is moving and holds still when it stops.
        if self.hero["dir"] == STOP:
            mouth = 40
        else:
            mouth = abs(((x + y) * 4) % 140 - 70)
        self.s.wedge("hero", x, y, HALF - 1, angle + mouth / 2.0,
                     360 - mouth, "hero")
        self.s.show("hero", True)

    def _draw_death(self):
        """Open right up and shrink away."""
        gone = float(DEATH_TICKS - self.wait) / DEATH_TICKS
        x, y = self.hero["x"], self.hero["y"]
        angle = ANGLES[self.hero["dir"]]
        mouth = min(358.0, 40 + gone * 340.0)
        radius = max(0.6, (HALF - 1) * (1.0 - gone * 0.9))
        self.s.wedge("hero", x, y, radius, angle + mouth / 2.0,
                     360 - mouth, "hero")
        self.s.show("hero", gone < 0.98)

    def _draw_ghost(self, ghost, alpha):
        index = ghost["index"]
        x, y = self._lerp(ghost, alpha)

        if ghost["eyes"]:
            colour = "maze_fill"
        elif self.scared > 0:
            flashing = self.scared < 60 and (self.frame // 8) % 2 == 0
            colour = "scared_end" if flashing else "scared"
        else:
            colour = ghost["spec"]["colour"]

        size = CELL - 4
        # A slight bob, so a ghost gliding down a corridor is not a sliding
        # brick. Off the paint count, not the logic count, so it is smooth.
        bob = 0.8 if ((self.paint + index * 9) // 16) % 2 else -0.8
        self.s.rect("gb{0}".format(index), x - size / 2.0,
                    y - size / 2.0 + bob, size, size, colour, 6)
        self.s.show("gb{0}".format(index), True)

        dx, dy = ghost["dir"]
        for side, offset in (("a", -3.4), ("b", 3.4)):
            self.s.ellipse("ge{0}{1}".format(index, side),
                           x + offset, y - 2 + bob, 2.5, "eyes")
            self.s.ellipse("gp{0}{1}".format(index, side),
                           x + offset + dx * 1.1, y - 2 + bob + dy * 1.1,
                           1.2, "pupil")
            self.s.show("ge{0}{1}".format(index, side), True)
            self.s.show("gp{0}{1}".format(index, side), True)

    def _message(self, text):
        if text is None:
            self.s.drop_banner("msg")
            return
        self.s.banner("msg", self.height() / 2.0 + CELL * 3,
                      self.width(), text, 15, "orange")

    # -- the game over card ==============================================

    def _draw_over(self):
        width = self.width()
        beat = self.score > self.best_at_start
        if not self.overlay:
            self.overlay = True
            self.s.rect("veil", 0, 0, width, self.height(), "veil")
            top = self.height() / 2.0 - 84
            self.s.banner("over_title", top + 16, width,
                          "NEW BEST" if beat else "GAME OVER", 26,
                          "green" if beat else "red", "veil")
            self.s.banner("over_score", top + 56, width,
                          "{0} points".format(self.score), 17, "hero", "veil")
            self.s.banner("over_stats", top + 84, width,
                          "level {0}   -   {1} pellets   -   {2} ghosts "
                          "eaten".format(self.level, self.eaten_pellets,
                                         self.eaten_ghosts),
                          11, "muted", "veil")
            self.s.banner("over_rank", top + 112, width, _rank(self.score),
                          14, "blue", "veil")
            self.s.banner("over_note", top + 138, width, self.sign_off, 11,
                          "muted", "veil")
            self.s.banner("over_again", top + 170, width,
                          "press R to play again", 12, "orange", "veil")
            # The board was built first, so the card has to be lifted over it.
            self.s.lift("veil")
            for key in ("over_title", "over_score", "over_stats", "over_rank",
                        "over_note", "over_again"):
                self.s.lift(key + "_bg")
                self.s.lift(key)

        # The prompt breathes rather than blinks - a hard blink at 60fps is a
        # strobe, and this window sits in front of somebody's model.
        self.s.alpha("over_again", 0.55 + 0.45 * _wave(self.paint))


def _wave(frame):
    """A cheap 0..1 triangle wave, so nothing here needs the math module."""
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
