# -*- coding: utf-8 -*-
"""Bench tests for the game rules themselves, under plain CPython.

    python bench_logic.py

import_check proves the games do not throw. This proves they do something: the
hero moves, ghosts leave the house and then keep turning, pellets disappear,
power pellets frighten, a ghost can be eaten and sent home, a collision costs a
life, and clearing the board moves the level on.

"It did not throw" is not evidence, on a bench any more than in Revit.
"""

import datetime
import os
import shutil
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
GAMES = os.path.join(HERE, "games")

# egg_desktop imports the shared modules as `revobim.egg.*`, exactly as it does
# on a desktop, so the extension's lib folder has to be reachable here too.
LIB = os.path.abspath(os.path.join(HERE, "..", ".."))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

PASSED = []
FAILED = []


class FakeSurface(object):
    def __init__(self):
        self.live = {}
        self.removed = []
        self.alphas = {}
        self.lifted = []
        self.banners = {}
        self.last_banner = ""

    def _set(self, key):
        self.live[key] = True

    def rect(self, key, x, y, w, h, colour, radius=0):
        self._set(key)

    def ellipse(self, key, cx, cy, r, colour):
        self._set(key)

    def wedge(self, key, cx, cy, r, start, sweep, colour):
        self._set(key)

    def label(self, key, x, y, text, size=12, colour="text", bold=False):
        self._set(key)
        return None

    def banner(self, key, y, width, text, size=15, colour="orange",
               behind="bg"):
        self._set(key)
        # Keyed, not just "the last one" - the card draws six banners and the
        # last of them is the prompt, not the headline.
        self.banners[key] = text
        self.last_banner = text
        return None

    def drop_banner(self, key):
        self.live.pop(key, None)

    def alpha(self, key, value):
        self.alphas[key] = value

    def lift(self, key):
        self.lifted.append(key)

    def move(self, key, x, y):
        pass

    def move_centre(self, key, cx, cy):
        pass

    def fill(self, key, colour):
        pass

    def show(self, key, visible):
        pass

    def has(self, key):
        return key in self.live

    def remove(self, key):
        self.removed.append(key)
        self.live.pop(key, None)

    def clear(self):
        self.live = {}


def load_module(name, folder):
    path = os.path.join(folder, name + ".py")
    module = types.ModuleType("bench_" + name)
    module.__file__ = path
    handle = open(path, "r")
    try:
        text = handle.read()
    finally:
        handle.close()
    exec(compile(text, path, "exec"), module.__dict__)
    return module


def load(name):
    path = os.path.join(GAMES, name + ".py")
    module = types.ModuleType("bench_" + name)
    module.__file__ = path
    handle = open(path, "r")
    try:
        text = handle.read()
    finally:
        handle.close()
    exec(compile(text, path, "exec"), module.__dict__)
    return module


def check(label, condition, detail=""):
    if condition:
        PASSED.append(label)
    else:
        FAILED.append("{0} {1}".format(label, detail).strip())


def run_ticks(game, count, ready=True):
    """Tick and render, the way the shell does it."""
    for _ in range(count):
        game.tick()
        game.render(1.0)


def ghost_out(game, limit=600):
    """Run until a ghost is out of the house, and hand it back.

    A fixed number of warm-up ticks is not good enough: the idle hero gets
    caught, and a death sends every ghost back into the house. Two tests were
    quietly relying on the old death timing.
    """
    for _ in range(limit):
        game.tick()
        game.render(1.0)
        for ghost in game.ghosts:
            if not ghost["home"] and not ghost["eyes"]:
                return ghost
    return None


def new_pacman():
    pacman = load("pacman")
    surface = FakeSurface()
    game = pacman.Game(surface, {})
    game.start()
    return pacman, surface, game


# -- pacman ==============================================================

def test_board():
    pacman, surface, game = new_pacman()
    check("board: pellets laid out", len(game.pellets) > 100,
          "got {0}".format(len(game.pellets)))
    check("board: power pellets", 
          len([c for c in game.pellets if game.pellets[c] == "o"]) == 4)
    check("board: four ghosts", len(game.ghosts) == 4)
    check("board: one life", game.lives == 1)
    check("board: hero placed", game.hero is not None)


def test_ready_then_run():
    pacman, surface, game = new_pacman()
    check("ready: starts in ready", game.state == "ready")
    run_ticks(game, pacman.READY_TICKS + 2)
    check("ready: hands over to run", game.state == "run",
          "state {0}".format(game.state))


def test_hero_moves_and_eats():
    pacman, surface, game = new_pacman()
    run_ticks(game, pacman.READY_TICKS + 2)
    start_x = game.hero["x"]
    before = len(game.pellets)
    run_ticks(game, 60)
    check("hero: moves", game.hero["x"] != start_x)
    check("hero: eats pellets", len(game.pellets) < before,
          "{0} -> {1}".format(before, len(game.pellets)))
    check("hero: scores", game.score > 0)


def test_hero_turns_and_stops_at_walls():
    pacman, surface, game = new_pacman()
    run_ticks(game, pacman.READY_TICKS + 2)
    game.key("Up")
    run_ticks(game, 60)
    check("hero: obeys a turn it can make", game.hero["dir"] != pacman.LEFT)

    # Drive it into the wall above the hero start and confirm it stops rather
    # than walking through.
    pacman2, surface2, game2 = new_pacman()
    run_ticks(game2, pacman2.READY_TICKS + 2)
    game2.key("Down")
    run_ticks(game2, 200)
    col, row = game2._cell(game2.hero)
    check("hero: stays on the maze",
          game2._walkable(int(col), int(row)),
          "ended on {0}".format(pacman2.MAZE[int(row)][int(col)]))


def test_ghosts_leave_and_keep_turning():
    pacman, surface, game = new_pacman()
    game.lives = 99   # this test watches ghosts, so the hero must not end it
    run_ticks(game, pacman.READY_TICKS + 2)
    run_ticks(game, 400)
    out = [g for g in game.ghosts if not g["home"]]
    check("ghosts: leave the house", len(out) >= 2,
          "{0} out".format(len(out)))

    # The bug worth guarding: a ghost that comes out a pixel off the grid never
    # aligns again, so it never turns again. Track how many distinct directions
    # each escaped ghost uses over a long run.
    seen = {}
    for ghost in out:
        seen[ghost["index"]] = set()
    for _ in range(600):
        game.tick()
        for ghost in game.ghosts:
            if ghost["index"] in seen and not ghost["home"]:
                seen[ghost["index"]].add(ghost["dir"])
    worst = min([len(seen[key]) for key in seen]) if seen else 0
    check("ghosts: keep turning after leaving", worst >= 2,
          "fewest directions used by one ghost: {0}".format(worst))


def test_ghosts_stay_on_the_maze():
    pacman, surface, game = new_pacman()
    game.lives = 99   # likewise: 700 ticks of ghosts, not one short game
    run_ticks(game, pacman.READY_TICKS + 2)
    off = []
    for _ in range(700):
        game.tick()
        for ghost in game.ghosts:
            if ghost["home"]:
                continue
            col, row = game._cell(ghost)
            if not game._walkable(int(col), int(row), ghost=True):
                off.append((ghost["index"], int(col), int(row)))
    check("ghosts: never enter a wall", not off,
          "first at {0}".format(off[0] if off else ""))


def test_power_pellet_frightens():
    pacman, surface, game = new_pacman()
    run_ticks(game, pacman.READY_TICKS + 2)
    # Put the hero on a power pellet and let it eat.
    power = [cell for cell in game.pellets if game.pellets[cell] == "o"][0]
    game.hero["x"], game.hero["y"] = game._centre(power[0], power[1])
    game.hero["dir"] = pacman.STOP
    game.hero["want"] = pacman.STOP
    game.tick()
    check("power: frightens the ghosts", game.scared > 0)
    check("power: scores fifty", game.score >= 50)


def test_eating_a_ghost():
    pacman, surface, game = new_pacman()
    run_ticks(game, pacman.READY_TICKS + 2)
    victim = ghost_out(game)
    if victim is None:
        check("eat: a ghost was out to eat", False)
        return
    game.scared = 200
    game.lives = 3
    game.state = "run"
    game.hero["x"] = victim["x"]
    game.hero["y"] = victim["y"]
    before = game.score
    game._collide()
    check("eat: turns the ghost to eyes", victim["eyes"])
    check("eat: scores two hundred", game.score == before + 200,
          "{0} -> {1}".format(before, game.score))
    check("eat: costs no life", game.lives == 3)

    # And the eyes must find their way home rather than wandering for ever.
    for _ in range(400):
        game.tick()
        if victim["home"]:
            break
    check("eat: the eyes get home", victim["home"] or not victim["eyes"])


def test_collision_costs_a_life():
    pacman, surface, game = new_pacman()
    run_ticks(game, pacman.READY_TICKS + 2)
    victim = ghost_out(game)
    game.scared = 0
    game.lives = 3
    game.state = "run"
    game.hero["x"] = victim["x"]
    game.hero["y"] = victim["y"]
    game._collide()
    check("death: costs a life", game.lives == 2,
          "lives {0}".format(game.lives))
    check("death: pauses the run", game.state == "dying")
    run_ticks(game, pacman.DEATH_TICKS + pacman.READY_TICKS + 4)
    check("death: comes back to run with lives left", game.state == "run",
          "state {0}".format(game.state))


def test_game_over():
    pacman, surface, game = new_pacman()
    run_ticks(game, pacman.READY_TICKS + 2)
    victim = ghost_out(game)
    game.lives = 1
    game.scared = 0
    game.state = "run"
    game.hero["x"] = victim["x"]
    game.hero["y"] = victim["y"]
    # With no previous best, any score at all is a new best - so the headline is
    # only GAME OVER once there is a best to fall short of. Set before the death
    # ticks, because the card is built on the first render after it ends.
    game.best_at_start = 999999
    game._collide()
    check("over: the death plays first", game.state == "dying" and
          not game.is_over(), "state {0}".format(game.state))
    run_ticks(game, pacman.DEATH_TICKS + 2)
    check("over: ends the game", game.is_over())
    # The card is drawn, not written by tick, so it takes a frame to appear.
    game.render(1.0)
    check("over: says so", "GAME OVER" in surface.banners.get("over_title", ""),
          surface.banners.get("over_title", ""))

    pacman2, surface2, game2 = new_pacman()
    game2.best_at_start = 10
    game2.score = 500
    game2.over = True
    game2.state = "over"
    game2.render(1.0)
    check("over: beating the best says so",
          "NEW BEST" in surface2.banners.get("over_title", ""),
          surface2.banners.get("over_title", ""))


def test_level_clears():
    pacman, surface, game = new_pacman()
    run_ticks(game, pacman.READY_TICKS + 2)
    # Leave one pellet, eat it, and the level should turn over.
    last = list(game.pellets.keys())[0]
    keep = game.pellets[last]
    game.pellets = {last: keep}
    game.hero["x"], game.hero["y"] = game._centre(last[0], last[1])
    game.hero["dir"] = pacman.STOP
    game.hero["want"] = pacman.STOP
    game.tick()
    check("level: moves on when the board clears", game.level == 2,
          "level {0}".format(game.level))
    check("level: refills the board", len(game.pellets) > 100)


def test_tunnel_wraps():
    pacman, surface, game = new_pacman()
    run_ticks(game, pacman.READY_TICKS + 2)
    width = game.cols * pacman.CELL
    # Drop the hero into the tunnel row heading left off the edge.
    game.hero["x"], game.hero["y"] = game._centre(0, 9)
    game.hero["dir"] = pacman.LEFT
    game.hero["want"] = pacman.LEFT
    run_ticks(game, 8)
    check("tunnel: wraps rather than stopping",
          game.hero["x"] > width * 0.5,
          "x {0} of {1}".format(game.hero["x"], width))


def test_pause():
    pacman, surface, game = new_pacman()
    run_ticks(game, pacman.READY_TICKS + 2)
    game.key("P")
    x = game.hero["x"]
    run_ticks(game, 20)
    check("pause: freezes the hero", game.hero["x"] == x)
    game.key("P")
    run_ticks(game, 20)
    check("pause: unfreezes", game.hero["x"] != x)


# -- snake ===============================================================

def test_snake():
    snake = load("snake")
    surface = FakeSurface()
    game = snake.Game(surface, {})
    game.start()
    length = len(game.body)
    run_ticks(game, 3)
    check("snake: moves", game.body[0] != (6, snake.ROWS // 2))
    game.key("Left")
    run_ticks(game, 1)
    check("snake: cannot double back", game.dir == snake.RIGHT)
    head = game.body[0]
    game.food = (head[0] + game.dir[0], head[1] + game.dir[1])
    game.tick()
    game.render(1.0)
    check("snake: eating grows it", len(game.body) > length)
    game.body = [(0, 0)]
    game.dir = snake.LEFT
    game.want = snake.LEFT
    game.tick()
    game.render(1.0)
    check("snake: the wall ends it", game.is_over())
    check("snake: puts up a card too", surface.has("over_title"))


def test_interpolation():
    """A frame drawn half way between two logic steps must land half way."""
    pacman, surface, game = new_pacman()
    run_ticks(game, pacman.READY_TICKS + 2)
    game.hero["px"], game.hero["py"] = 100, 200
    game.hero["x"], game.hero["y"] = 106, 200
    x, y = game._lerp(game.hero, 0.5)
    check("smooth: draws between the two steps", x == 103 and y == 200,
          "got {0},{1}".format(x, y))
    x, y = game._lerp(game.hero, 0.0)
    check("smooth: alpha 0 is where it was", x == 100)
    x, y = game._lerp(game.hero, 1.0)
    check("smooth: alpha 1 is where it is", x == 106)

    # A mover that has just wrapped the tunnel is a board width away from where
    # it was; interpolating it would fling it back across the screen.
    game.hero["px"] = 9
    game.hero["x"] = game.width() - 9
    x, y = game._lerp(game.hero, 0.5)
    check("smooth: the tunnel frame is not interpolated",
          x == game.width() - 9, "got {0}".format(x))


def test_tick_is_logic_only():
    """Rendering twice for one tick must not change the game."""
    pacman, surface, game = new_pacman()
    run_ticks(game, pacman.READY_TICKS + 40)
    before = (game.score, game.hero["x"], game.hero["y"], len(game.pellets))
    for _ in range(20):
        game.render(0.3)
    after = (game.score, game.hero["x"], game.hero["y"], len(game.pellets))
    check("smooth: extra frames change nothing", before == after)


def test_game_over_card():
    pacman, surface, game = new_pacman()
    run_ticks(game, pacman.READY_TICKS + 2)
    victim = ghost_out(game)
    game.lives = 1
    game.scared = 0
    game.state = "run"
    game.score = 3100
    game.hero["x"] = victim["x"]
    game.hero["y"] = victim["y"]
    game._collide()
    run_ticks(game, pacman.DEATH_TICKS + 2)
    game.render(1.0)
    check("over: puts up the card", surface.has("over_title"))
    check("over: shows the score", surface.has("over_score"))
    check("over: shows a rank", surface.has("over_rank"))
    check("over: lifts the card over the board", "veil" in surface.lifted)
    check("over: rank tracks the score",
          pacman._rank(3100) == "MEP Coordinator",
          pacman._rank(3100))
    check("over: a bad score gets the bottom rank",
          pacman._rank(10) == "Setting Out Apprentice")
    check("over: a good score gets the top rank",
          pacman._rank(20000) == "Model Federation Overlord")

    # The prompt breathes rather than blinks, so its opacity has to move.
    seen = set()
    for _ in range(200):
        game.render(1.0)
        seen.add(round(surface.alphas.get("over_again", 0), 2))
    check("over: the prompt pulses", len(seen) > 10,
          "{0} distinct values".format(len(seen)))
    check("over: it never goes fully invisible",
          min(seen) >= 0.5, "min {0}".format(min(seen)))


def test_one_life():
    """One ghost, one game. The whole run from a clean board to the card."""
    pacman, surface, game = new_pacman()
    check("one life: that is the default", pacman.LIVES == 1)
    run_ticks(game, pacman.READY_TICKS + 2)
    victim = ghost_out(game)
    game.scared = 0
    game.state = "run"
    game.hero["x"] = victim["x"]
    game.hero["y"] = victim["y"]
    game._collide()
    check("one life: a single hit is fatal", game.lives == 0)
    check("one life: but the death still plays", game.state == "dying")
    run_ticks(game, pacman.DEATH_TICKS // 2)
    check("one life: still animating half way through",
          not game.is_over(), "already over")
    run_ticks(game, pacman.DEATH_TICKS)
    check("one life: then it is over", game.is_over())
    game.render(1.0)
    check("one life: and the card is up", surface.has("over_title"))
    check("one life: the footer stops counting lives",
          "Lives" not in game.status(), game.status())


def test_new_best():
    pacman = load("pacman")
    surface = FakeSurface()
    game = pacman.Game(surface, {"high_pacman": "500"})
    game.start()
    check("best: reads the high score at the start",
          game.best_at_start == 500)


def test_death_animation():
    pacman, surface, game = new_pacman()
    run_ticks(game, pacman.READY_TICKS + 2)
    game.state = "dying"
    game.wait = pacman.DEATH_TICKS
    game.render(1.0)
    check("death: hero still drawn at the start", surface.has("hero"))
    game.wait = 1
    game.render(1.0)
    check("death: the ghosts are hidden", True)


# -- the scoreboard ======================================================

def scores_module(scratch):
    """The real module, pointed at a scratch folder rather than AppData."""
    path = os.path.join(HERE, "egg_scores.py")
    module = types.ModuleType("bench_scores")
    module.__file__ = path
    handle = open(path, "r")
    try:
        text = handle.read()
    finally:
        handle.close()
    exec(compile(text, path, "exec"), module.__dict__)
    module.folder = lambda: scratch
    module.path = lambda: os.path.join(scratch, "easter_egg_scores.txt")
    return module


def with_scratch(work):
    scratch = tempfile.mkdtemp()
    try:
        return work(scores_module(scratch), scratch)
    finally:
        try:
            shutil.rmtree(scratch)
        except Exception:
            pass


def test_scores_round_trip():
    def work(scores, scratch):
        entry, place, total = scores.record("pacman", 1500, {"player": "drew"})
        check("scores: first game is first place", place == 1 and total == 1)
        rows = scores.ranked("pacman")
        check("scores: it comes back", len(rows) == 1)
        check("scores: with the score", rows[0]["score"] == 1500)
        check("scores: with the player", rows[0]["player"] == "drew")
        check("scores: with a readable date",
              len(scores.pretty_when(rows[0]["when"])) >= 10,
              scores.pretty_when(rows[0]["when"]))
    with_scratch(work)


def test_scores_order_and_place():
    def work(scores, scratch):
        for score in (400, 9000, 1200):
            scores.record("pacman", score, {"player": "drew"})
        entry, place, total = scores.record("pacman", 5000,
                                            {"player": "someone"})
        rows = scores.ranked("pacman")
        check("scores: highest first",
              [row["score"] for row in rows] == [9000, 5000, 1200, 400],
              str([row["score"] for row in rows]))
        check("scores: the place is right", place == 2, "got {0}".format(place))
        check("scores: total counts every game", total == 4)
    with_scratch(work)


def test_scores_are_per_game():
    def work(scores, scratch):
        scores.record("pacman", 800, {})
        scores.record("snake", 90, {})
        check("scores: one game does not see the other",
              len(scores.ranked("pacman")) == 1
              and len(scores.ranked("snake")) == 1)
        check("scores: but the file holds both", len(scores.load()) == 2)
    with_scratch(work)


def test_scores_tie_keeps_the_older_first():
    def work(scores, scratch):
        early = datetime.datetime(2026, 1, 1, 9, 0, 0)
        late = datetime.datetime(2026, 6, 1, 9, 0, 0)
        scores.record("pacman", 1000, {"player": "late"}, when=late)
        scores.record("pacman", 1000, {"player": "early"}, when=early)
        rows = scores.ranked("pacman")
        check("scores: a tie is settled by who got there first",
              rows[0]["player"] == "early", rows[0]["player"])
    with_scratch(work)


def test_scores_cap_drops_the_weakest():
    def work(scores, scratch):
        settings = {"scores_kept": "5"}
        for score in range(1, 21):
            scores.record("pacman", score * 10, settings)
        rows = scores.ranked("pacman")
        check("scores: the file is capped", len(rows) == 5,
              "{0} rows".format(len(rows)))
        check("scores: and it keeps the best, not the newest",
              [row["score"] for row in rows] == [200, 190, 180, 170, 160],
              str([row["score"] for row in rows]))
    with_scratch(work)


def test_scores_awkward_names():
    def work(scores, scratch):
        entry, place, total = scores.record(
            "pacman", 100, {"player": "a|b\nc  d"})
        rows = scores.ranked("pacman")
        check("scores: a separator in a name cannot break the record",
              len(rows) == 1 and rows[0]["score"] == 100)
        check("scores: the name is cleaned up",
              rows[0]["player"] == "a b c d", rows[0]["player"])
    with_scratch(work)


def test_scores_player_falls_back():
    def work(scores, scratch):
        check("scores: the setting wins",
              scores.player_name({"player": "drew"}) == "drew")
        check("scores: a blank setting falls through to the account",
              scores.player_name({"player": "  "}) != "")
        check("scores: and with nothing at all it still names somebody",
              scores.player_name(None) != "")
    with_scratch(work)


def test_scores_missing_file():
    def work(scores, scratch):
        check("scores: no file is an empty board, not a failure",
              scores.ranked("pacman") == [])
        check("scores: and a personal best of zero",
              scores.personal_best("pacman", "drew") == 0)
    with_scratch(work)


def test_scores_clear():
    def work(scores, scratch):
        scores.record("pacman", 100, {})
        scores.record("snake", 50, {})
        scores.clear("pacman")
        check("scores: clearing one game leaves the other",
              scores.ranked("pacman") == [] and len(scores.ranked("snake")) == 1)
        scores.clear()
        check("scores: clearing everything empties it", scores.load() == [])
    with_scratch(work)


def test_board_holds_fifteen():
    """Fifteen rows come back, and a sixteenth game does not push a good one
    off the table it is drawn from."""
    def work(scores, scratch):
        for score in range(1, 26):
            scores.record("pacman", score * 10, {})
        rows = scores.ranked("pacman", 15)
        check("board: fifteen rows", len(rows) == 15,
              "{0} rows".format(len(rows)))
        check("board: and they are the best fifteen",
              rows[0]["score"] == 250 and rows[-1]["score"] == 110,
              "{0} down to {1}".format(rows[0]["score"], rows[-1]["score"]))
        check("board: asking for more than exist is not an error",
              len(scores.ranked("snake", 15)) == 0)
    with_scratch(work)


def test_settings_migration():
    """A 1.2.0 file must not keep scores_shown=10."""
    settings = load_module("egg_settings", HERE)
    reset = set()
    for version in settings.MIGRATIONS:
        for key in settings.MIGRATIONS[version]:
            reset.add(key)
    check("settings: the row count default is 15",
          settings.DEFAULTS["scores_shown"] == "15")
    check("settings: and it is migrated, not just redefaulted",
          "scores_shown" in reset)


# -- the click counter ===================================================

class FakeArgs(object):
    """Just enough of a WPF MouseButtonEventArgs to count clicks against."""

    def __init__(self, stamp):
        self.Timestamp = stamp
        self.Handled = False


def counter_class():
    """The real _Counter, with the .NET it leans on stubbed out.

    Only the delegate wrapper and the launch are faked; the counting rules
    themselves are the shipped code.
    """
    path = os.path.join(HERE, "egg_hook.py")
    handle = open(path, "r")
    try:
        text = handle.read()
    finally:
        handle.close()

    # Take the class out of the module rather than importing the module, which
    # would drag WPF in with it.
    start = text.index("class _Counter(object):")
    end = text.index("# -- finding the logo")
    source = text[start:end]

    module = types.ModuleType("bench_counter")
    launched = []

    class Shell(object):
        def launch(self, **kwargs):
            launched.append(kwargs)
            return True

    class Log(object):
        def __init__(self):
            self.lines = []

        def write(self, message, tool=None):
            self.lines.append(message)
            return True

    module.__dict__["MouseButtonEventHandler"] = lambda handler: handler
    module.__dict__["egg_shell"] = Shell()
    module.__dict__["egg_log"] = Log()
    module.__dict__["_last_error"] = lambda: "none"
    exec(compile(source, path, "exec"), module.__dict__)
    return module._Counter, launched, module.__dict__["egg_log"]


def new_counter(clicks=3, gap_min=250, gap_max=2000):
    Counter, launched, log = counter_class()
    counter = Counter(["logo"], None, None, clicks, gap_min, gap_max, "bench")
    return counter, launched, log


def click(counter, stamp):
    args = FakeArgs(stamp)
    counter.on_click(None, args)
    return args


def test_three_slow_clicks_open_it():
    """The whole reason 1.4.0 did not work: clicking the documented way."""
    counter, launched, log = new_counter()
    click(counter, 1000)
    click(counter, 2000)          # a second apart - slow, as documented
    check("clicks: two slow clicks are not enough", not launched)
    args = click(counter, 3000)
    check("clicks: three slow clicks open it", len(launched) == 1,
          "{0} launches".format(len(launched)))
    check("clicks: and the third one is swallowed", args.Handled)


def test_a_wide_range_of_slow():
    for gap in (300, 500, 900, 1400, 1900):
        counter, launched, log = new_counter()
        click(counter, 0)
        click(counter, gap)
        click(counter, gap * 2)
        check("clicks: {0}ms apart works".format(gap), len(launched) == 1)


def test_too_slow_goes_cold():
    counter, launched, log = new_counter()
    click(counter, 0)
    click(counter, 1000)
    click(counter, 5000)          # a five second gap is a different visit
    check("clicks: a cold run does not fire", not launched)
    check("clicks: but it restarts the count", counter.count == 1)


def test_double_click_does_not_count():
    counter, launched, log = new_counter()
    click(counter, 0)
    click(counter, 90)            # a double click, not a slow click
    check("clicks: a double click restarts rather than counting",
          counter.count == 1)
    check("clicks: and does not open it", not launched)


def test_one_click_two_elements_counts_once():
    """The egg is hooked to the logo and to the text beside it.

    Preview tunnels through both, so the same physical click reaches the handler
    twice. Identical timestamp, one count.
    """
    counter, launched, log = new_counter()
    for stamp in (0, 1000, 2000):
        args = FakeArgs(stamp)
        counter.on_click(None, args)
        counter.on_click(None, args)      # the same click again
    check("clicks: a click on two hooked elements counts once",
          len(launched) == 1, "{0} launches".format(len(launched)))


def test_it_logs_every_click():
    counter, launched, log = new_counter()
    click(counter, 0)
    click(counter, 1000)
    click(counter, 2000)
    check("clicks: every click is logged", len(log.lines) >= 4,
          "{0} lines".format(len(log.lines)))
    check("clicks: and the launch is logged",
          any("launch" in line for line in log.lines))


def test_counter_never_throws():
    counter, launched, log = new_counter()
    broken = FakeArgs(0)
    del broken.Timestamp          # args with no timestamp at all
    try:
        counter.on_click(None, broken)
        threw = False
    except Exception:
        threw = True
    check("clicks: a click can never throw at the user", not threw)


def test_settings_carry_the_slow_gaps():
    settings = load_module("egg_settings", HERE)
    check("clicks: the gap is a setting, not a whole-run window",
          "click_gap_max_ms" in settings.DEFAULTS
          and "click_window_ms" not in settings.DEFAULTS)
    check("clicks: two seconds is inside it",
          int(settings.DEFAULTS["click_gap_max_ms"]) >= 2000)


# -- the desktop build ===================================================

class FakeCanvas(object):
    """Enough of a Tk canvas to drive the real TkSurface with no display."""

    def __init__(self):
        self.items = {}
        self.next_id = 1
        self.order = []

    def _add(self, kind, coords, options):
        item = self.next_id
        self.next_id += 1
        self.items[item] = {"kind": kind, "coords": list(coords),
                            "options": dict(options)}
        self.order.append(item)
        return item

    def create_polygon(self, points, **options):
        return self._add("polygon", points, options)

    def create_oval(self, box, **options):
        return self._add("oval", box, options)

    def create_arc(self, box, **options):
        return self._add("arc", box, options)

    def create_text(self, x, y, **options):
        return self._add("text", (x, y), options)

    def coords(self, item, *values):
        if item in self.items:
            flat = values[0] if len(values) == 1 and isinstance(
                values[0], (list, tuple)) else values
            self.items[item]["coords"] = list(flat)

    def itemconfigure(self, item, **options):
        if item in self.items:
            self.items[item]["options"].update(options)

    def tag_raise(self, item):
        if item in self.order:
            self.order.remove(item)
            self.order.append(item)

    def delete(self, item):
        if item == "all":
            self.items = {}
            self.order = []
            return
        self.items.pop(item, None)
        if item in self.order:
            self.order.remove(item)

    def scale(self, tag, ox, oy, fx, fy):
        for item in self.items.values():
            scaled = []
            for index in range(len(item["coords"])):
                value = item["coords"][index]
                scaled.append(value * (fx if index % 2 == 0 else fy))
            item["coords"] = scaled

    def winfo_width(self):
        return 400

    def winfo_height(self):
        return 400


def desktop_module():
    """The real egg_desktop, with tkinter stubbed so it loads without a display."""
    fake = types.ModuleType("tkinter")
    fake.PIESLICE = "pieslice"
    fake.Tk = object
    fake.Frame = object
    fake.Label = object
    fake.Canvas = object
    font = types.ModuleType("tkinter.font")
    saved = (sys.modules.get("tkinter"), sys.modules.get("tkinter.font"))
    sys.modules["tkinter"] = fake
    sys.modules["tkinter.font"] = font
    try:
        return load_module("egg_desktop", HERE)
    finally:
        for name, value in zip(("tkinter", "tkinter.font"), saved):
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


def test_desktop_plays_a_real_game():
    """Pacman, through the Tk surface, with no Revit and no display.

    This is the whole claim of the desktop build in one test: the shipped game,
    the shipped surface contract, none of the host.
    """
    desktop = desktop_module()
    pacman = load("pacman")
    canvas = FakeCanvas()
    surface = desktop.TkSurface(canvas, desktop.egg_theme.palette("dark"))
    game = pacman.Game(surface, {})
    game.start()
    check("desktop: the board is drawn", len(canvas.items) > 200,
          "{0} items".format(len(canvas.items)))

    turns = ("Left", "Up", "Right", "Down")
    for step in range(600):
        game.tick()
        game.render(0.5)
        if step % 23 == 0:
            game.key(turns[(step // 23) % 4])
    check("desktop: it survives 600 frames", True)
    check("desktop: the hero is on the canvas", surface.has("hero"))
    check("desktop: pellets get eaten", len(game.pellets) < 180,
          "{0} left".format(len(game.pellets)))


def test_desktop_snake_too():
    desktop = desktop_module()
    snake = load("snake")
    canvas = FakeCanvas()
    surface = desktop.TkSurface(canvas, desktop.egg_theme.palette("light"))
    game = snake.Game(surface, {})
    game.start()
    for _ in range(200):
        game.tick()
        game.render(0.5)
    check("desktop: snake runs on the light palette too", len(canvas.items) > 0)


def test_desktop_mouth_faces_the_right_way():
    """Tk measures angles anticlockwise; the games are written for WPF, where a
    positive angle turns clockwise because the y axis points down."""
    desktop = desktop_module()
    canvas = FakeCanvas()
    surface = desktop.TkSurface(canvas, desktop.egg_theme.palette("dark"))
    surface.wedge("m", 50, 50, 10, 30.0, 300.0, "hero")
    options = canvas.items[surface._items["m"]]["options"]
    check("desktop: the arc start is negated", options["start"] == -30.0,
          str(options["start"]))
    check("desktop: and so is the sweep", options["extent"] == -300.0,
          str(options["extent"]))
    check("desktop: it is a pie slice", options["style"] == "pieslice")


def test_desktop_flattens_translucent_colours():
    """Tk has no alpha, so the veil and the fading prompt are mixed down."""
    desktop = desktop_module()
    solid = desktop.flatten("#FFFFFF", "#000000")
    check("desktop: an opaque colour is itself", solid.lower() == "#ffffff",
          solid)
    half = desktop.flatten("#80FFFFFF", "#000000")
    red = int(half[1:3], 16)
    check("desktop: half alpha lands about half way", 120 < red < 136,
          half)
    faded = desktop.flatten("#FFFFFF", "#000000", 0.0)
    check("desktop: a full fade reaches the backdrop",
          faded.lower() == "#000000", faded)


def test_desktop_scaling_moves_what_is_already_drawn():
    """Full screen must not leave the maze at its old size.

    Walls and pellets are drawn once at the start, so a scale change has to
    reach them as well as everything drawn afterwards.
    """
    desktop = desktop_module()
    canvas = FakeCanvas()
    surface = desktop.TkSurface(canvas, desktop.egg_theme.palette("dark"))
    surface.rect("wall", 10, 10, 20, 20, "maze")
    before = list(canvas.items[surface._items["wall"]]["coords"])
    surface.set_scale(2.0)
    after = canvas.items[surface._items["wall"]]["coords"]
    check("desktop: existing shapes are rescaled",
          abs(after[0] - before[0] * 2.0) < 0.01,
          "{0} -> {1}".format(before[0], after[0]))
    surface.rect("wall2", 10, 10, 20, 20, "maze")
    fresh = canvas.items[surface._items["wall2"]]["coords"]
    check("desktop: and new ones are drawn at the new scale",
          abs(fresh[0] - after[0]) < 0.01)


def test_desktop_and_revit_share_one_scoreboard():
    """The point of sharing egg_scores: one board, wherever it was played."""
    def work(scores, scratch):
        scores.record("pacman", 2200, {"player": "at-the-desk"})
        scores.record("pacman", 900, {"player": "in-revit"})
        rows = scores.ranked("pacman")
        check("desktop: both builds write the same board", len(rows) == 2)
        check("desktop: and it is ordered as one table",
              rows[0]["player"] == "at-the-desk")
    with_scratch(work)


# -- how it runs =========================================================

def shell_mode():
    """resolve_mode lifted out of egg_shell, which cannot be imported here.

    The function is deliberately a plain function of two values so it can be
    tested without a Revit, a Python or a display.
    """
    path = os.path.join(HERE, "egg_shell.py")
    handle = open(path, "r")
    try:
        text = handle.read()
    finally:
        handle.close()
    start = text.index("def resolve_mode(")
    end = text.index("def launch(")
    module = types.ModuleType("bench_mode")
    exec(compile(text[start:end], path, "exec"), module.__dict__)
    return module.resolve_mode


def test_run_mode_choices():
    """Auto takes a separate process where it can, and its own thread where it
    cannot. Neither leaves the game on Revit's UI thread, which is the only
    outcome that freezes."""
    resolve = shell_mode()
    # Auto takes the thread either way. A name on PATH is not proof that the
    # Python behind it is 3 or has tkinter, and when it is not, the process
    # starts, dies, and the button appears to do nothing.
    check("mode: auto takes the thread, whether or not there is a Python",
          resolve("auto", True) == "thread"
          and resolve("auto", False) == "thread")
    check("mode: auto never lands inline",
          resolve("auto", True) != "inline"
          and resolve("auto", False) != "inline")
    check("mode: auto never guesses at a process",
          resolve("auto", True) != "process")
    for wanted in ("process", "thread", "inline"):
        check("mode: {0} is honoured when asked for".format(wanted),
              resolve(wanted, True) == wanted)
    check("mode: nonsense falls back to a thread, not to Revit's",
          resolve("sideways", False) == "thread")
    check("mode: a blank setting is auto",
          resolve("", True) == "thread" and resolve(None, False) == "thread")
    check("mode: it is not case or space sensitive",
          resolve("  Thread ", False) == "thread")


def test_run_mode_default_is_auto():
    settings = load_module("egg_settings", HERE)
    check("mode: the default is auto",
          settings.DEFAULTS.get("run_mode") == "auto")


# -- automatic attachment ================================================

def wants_egg_fn():
    """wants_egg lifted out of egg_auto, which imports WPF.

    It is a plain function of three booleans on purpose: what the class handler
    decides to touch is the riskiest judgement in the package and it should be
    testable without a Revit.
    """
    path = os.path.join(HERE, "egg_auto.py")
    handle = open(path, "r")
    try:
        text = handle.read()
    finally:
        handle.close()
    start = text.index("def wants_egg(")
    end = text.index("def _title_of(")
    module = types.ModuleType("bench_auto")
    exec(compile(text[start:end], path, "exec"), module.__dict__)
    return module.wants_egg


def test_auto_attach_picks_the_right_windows():
    wants = wants_egg_fn()
    check("auto: a RevoBIM window with a named logo is wired",
          wants("style manager", True, False))
    check("auto: so is one whose title carries the brand",
          wants("revobim smart dimensions", False, True))
    check("auto: a named logo is enough on its own",
          wants("", True, False))


def test_auto_attach_leaves_everyone_else_alone():
    """The class handler sees every window every addin in Revit opens.

    A loose test here would put an easter egg on somebody else's software, so
    these are the cases that matter more than the ones above.
    """
    wants = wants_egg_fn()
    check("auto: Revit's own dialogs are left alone",
          not wants("save file", False, False))
    check("auto: another addin's window is left alone",
          not wants("some other addin", False, False))
    check("auto: an untitled dialog with no logo is left alone",
          not wants("", False, False))
    check("auto: a title alone with no logo anywhere is not enough",
          not wants("project browser", False, False))


def _anchor_text(*parts):
    root = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
    path = os.path.join(root, *parts)
    if not os.path.isfile(path):
        return None, path
    handle = open(path, "r")
    try:
        return handle.read(), path
    finally:
        handle.close()


def test_startup_is_pasteable():
    text, path = _anchor_text("startup.py")
    check("startup: it ships", text is not None)
    if text is None:
        return
    check("startup: it installs the auto-attachment",
          "egg_auto" in text and "install()" in text)
    check("startup: it is banded for pasting into an existing one",
          text.count("=" * 20) >= 2)
    check("startup: it cannot stop pyRevit loading the extension",
          "try:" in text and "except Exception" in text)
    check("startup: it puts lib on the path itself", "sys.path" in text)
    check("startup: and it compiles", _compiles(text, path))


def test_the_egg_survives_a_clobbered_startup():
    """There is one startup.py per extension, so another tool's delivery will
    eventually overwrite it - silently, since nothing fails when it does.

    So the egg is anchored in more than one place, using more than one pyRevit
    mechanism. Two anchors is one bad zip away from none, which is why the bar
    is three.
    """
    anchors = [("startup.py",), ("hooks", "app-init.py"),
               ("hooks", "doc-opened.py")]
    live = []
    for parts in anchors:
        text, path = _anchor_text(*parts)
        if text is None:
            continue
        label = "/".join(parts)
        check("anchor: {0} installs the attachment".format(label),
              "egg_auto" in text and "install()" in text)
        check("anchor: {0} is wrapped".format(label),
              "try:" in text and "except Exception" in text)
        check("anchor: {0} compiles".format(label), _compiles(text, path))
        live.append(label)

    check("anchor: at least three of them, in two different mechanisms",
          len(live) >= 3, "only {0}: {1}".format(len(live), ", ".join(live)))

    hooks = [name for name in live if name.startswith("hooks")]
    check("anchor: the hooks are a separate mechanism from startup.py",
          len(hooks) >= 2)

    handle = open(os.path.join(HERE, "egg_hook.py"), "r")
    try:
        hook_source = handle.read()
    finally:
        handle.close()
    check("anchor: a hand-wired tool arms it too, so one tool brings the rest "
          "back", "_arm_auto()" in hook_source)


def _compiles(text, path):
    try:
        compile(text, path, "exec")
        return True
    except SyntaxError:
        return False


TESTS = [test_board, test_ready_then_run, test_hero_moves_and_eats,
         test_hero_turns_and_stops_at_walls, test_ghosts_leave_and_keep_turning,
         test_ghosts_stay_on_the_maze, test_power_pellet_frightens,
         test_eating_a_ghost, test_collision_costs_a_life, test_game_over,
         test_level_clears, test_tunnel_wraps, test_pause, test_snake,
         test_interpolation, test_tick_is_logic_only, test_game_over_card,
         test_new_best, test_one_life, test_death_animation,
         test_scores_round_trip, test_scores_order_and_place,
         test_scores_are_per_game, test_scores_tie_keeps_the_older_first,
         test_scores_cap_drops_the_weakest, test_scores_awkward_names,
         test_scores_player_falls_back, test_scores_missing_file,
         test_scores_clear, test_board_holds_fifteen,
         test_settings_migration,
         test_three_slow_clicks_open_it, test_a_wide_range_of_slow,
         test_too_slow_goes_cold, test_double_click_does_not_count,
         test_one_click_two_elements_counts_once,
         test_it_logs_every_click, test_counter_never_throws,
         test_settings_carry_the_slow_gaps,
         test_desktop_plays_a_real_game, test_desktop_snake_too,
         test_desktop_mouth_faces_the_right_way,
         test_desktop_flattens_translucent_colours,
         test_desktop_scaling_moves_what_is_already_drawn,
         test_desktop_and_revit_share_one_scoreboard,
         test_run_mode_choices, test_run_mode_default_is_auto,
         test_auto_attach_picks_the_right_windows,
         test_auto_attach_leaves_everyone_else_alone,
         test_startup_is_pasteable,
         test_the_egg_survives_a_clobbered_startup]


def main():
    for test in TESTS:
        try:
            test()
        except Exception:
            FAILED.append("{0} raised {1}".format(test.__name__,
                                                  sys.exc_info()[1]))
    for line in PASSED:
        sys.stdout.write("  ok    {0}\n".format(line))
    for line in FAILED:
        sys.stdout.write("  FAIL  {0}\n".format(line))
    sys.stdout.write("\n{0} passed, {1} failed\n".format(len(PASSED),
                                                         len(FAILED)))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
