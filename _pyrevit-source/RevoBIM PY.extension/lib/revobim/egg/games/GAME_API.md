# Writing a game for the RevoBIM easter egg

Drop a `.py` file in this folder. It is found by filename next time the window
opens and appears in the header chip. Nothing else is edited — no registry, no
settings, no list to keep in step.

A game module needs five module-level names and one class.

```python
NAME    = "Pacman"      # what the header and the chip show
KEY     = "pacman"      # the settings key, and the high-score key
TICK_MS = 33            # how often tick() is called
KEYS    = "Arrows move   P pause   R restart   Esc close"   # footer hint

class Game(object):
    def __init__(self, surface, settings): ...
    def width(self):   return 342     # board size in pixels
    def height(self):  return 378
    def start(self):   ...            # build the board
    def tick(self):    ...            # one logic step. NO DRAWING.
    def render(self, alpha): ...      # one frame. NO LOGIC.
    def key(self, name): ...          # "Up" "Down" "Left" "Right"
                                      # "W" "A" "S" "D" "Space" "P"
    def stop(self):    ...            # called when the window closes
    def status(self):  return "Score 0"   # the footer's left hand line
    def is_over(self): return False
    score = 0                         # read for the high score
```

## tick() and render() are separate, and it matters

The shell runs `tick()` on a fixed step of `TICK_MS` and calls `render()` once
for every frame the display actually draws, off `CompositionTarget.Rendering`.
`alpha` is how far between the last two logic steps that frame falls, 0 to 1.

So a game keeps the position it had before the last step and draws between the
two:

```python
def tick(self):
    self.px, self.py = self.x, self.y      # remember
    self.x += self.dir[0] * SPEED          # move

def render(self, alpha):
    x = self.px + (self.x - self.px) * alpha
    self.s.rect("hero", x, self.y, 16, 16, "hero")
```

That is what turns 30 logic steps a second into 60fps motion without touching
the integer grid arithmetic the movement rules depend on. **A game that draws
inside `tick()` paints at the logic rate no matter what the render loop does**,
which looks exactly like the smoothing not working — so there is a bench rule
against it.

Two things to watch:

- **Wrapping.** A mover that has just come through a tunnel is a whole board
  away from where it was, and interpolating that frame flings it back across the
  screen. Check the gap and draw it where it actually is.
- **`render()` must be safe to call twice for one tick, or not at all.** It is
  called on the display's schedule, not the game's, and it must not change any
  game state — only `paint` counters and the like.

Two more rules that are not obvious:

- **`__init__` must not draw.** The shell builds a game once with `surface` set
  to `None` purely to ask `width()` and `height()`, so it knows how big to make
  the window before there is a canvas to draw on.
- **The board is a fixed pixel size and the shell scales it.** A `Viewbox`
  handles resizing and full screen, so a game never asks how big the window is.
- **`R` never reaches `key()`.** Restart is the shell's, and it does it by
  throwing the game away and building a new one. A game needs no restart logic
  of its own.

## The surface

Retained mode. Every shape is created once against a key and afterwards only
moved, refilled or removed — a game does not allocate in its tick loop, and a
few hundred shapes redraw at 30fps without trouble.

| Call | What it does |
| --- | --- |
| `rect(key, x, y, w, h, colour, radius=0)` | rectangle, top-left placed |
| `ellipse(key, cx, cy, r, colour)` | circle, centre placed |
| `wedge(key, cx, cy, r, start_deg, sweep_deg, colour)` | pie slice — this is a mouth |
| `label(key, x, y, text, size, colour, bold)` | text |
| `banner(key, y, width, text, size, colour)` | centred text on a full-width strip |
| `drop_banner(key)` | remove a banner and its strip |
| `move(key, x, y)` / `move_centre(key, cx, cy)` | reposition |
| `fill(key, colour)` / `alpha(key, 0..1)` | recolour, fade |
| `lift(key)` | bring a shape to the front — an overlay over a board built earlier |
| `show(key, visible)` / `remove(key)` / `has(key)` / `clear()` | the rest |

Angles are degrees, zero pointing right, increasing clockwise, because the
canvas y-axis runs downwards.

**`colour` is a palette key, not a hex value** — `"hero"`, `"maze"`, `"pellet"`,
`"power"`, `"ghost_1".."ghost_4"`, `"scared"`, `"eyes"`, plus the house
`"blue"`, `"orange"`, `"green"`, `"red"`, `"text"`, `"muted"`, `"bg"`, `"card"`,
`"field"`, and `"veil"` for a translucent full-board overlay. That is what makes
a game come up in dark or light without knowing which it is in. A literal hex is accepted and will look wrong in one of the two
themes.

No game imports WPF, `System.*` or the Revit API. `pacman.py` and `snake.py`
both import nothing but `random`, which is why they can be exercised on the
bench under plain CPython against a fake surface.
