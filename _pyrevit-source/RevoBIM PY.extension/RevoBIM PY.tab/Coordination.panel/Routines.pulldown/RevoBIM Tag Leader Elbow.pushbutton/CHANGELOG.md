# Tag Leader Elbow - changelog

## 3.2.0

- **The run from the tag to the elbow is now horizontal because the tag itself
  is measured, not its text.** 3.1.0 worked the tag's middle out from a line
  pitch and an assumption about where the head sat, and an assumption that is a
  millimetre out still draws a sloped shoulder. The elbow now goes on the exact
  vertical middle of the tag's own extent.
- **How that extent is read**: the leaders are switched off, the document
  regenerated, every tag's bounding box taken, and the whole thing **rolled
  back in a sub-transaction**. A tag's box normally includes its leader, which
  is the thing being moved; with the leader off it is the tag alone. The
  rollback leaves the model exactly as it was, and it is why this is safe to do
  to somebody's drawing. All the tags go through one sub-transaction and one
  regenerate.
- The same box gives the **exact width on the side the leg goes**, so
  justification and the vertical anchor no longer have to be told to it - they
  are measured. Both settings stay as the fallback for a tag whose box will not
  read, and are labelled as such.
- New setting **Work the tag's extent out by**: measuring the tag itself (the
  default) or measuring its text, which is 3.1.0's behaviour.
- Each results row says which of the two produced it.

## 3.1.0

- **Fixed: the run from the tag to the elbow came out sloped on a multi-line
  tag.** Revit draws that run horizontally only when the elbow is level with
  where the leader meets the tag, which is the **vertical middle of the text
  block**. On a multi-line tag `TagHeadPosition` is on the top line, so an
  elbow left level with the head sat above the text and the shoulder sloped
  down into it. The elbow is now dropped onto the tag's own middle: half a line
  on a two line tag, a whole line on a three line tag.
- The line pitch is measured, not assumed: `FormattedText.Height` for the tag
  type's own font at the tag type's own text size, scaled to the view the same
  way the width is. The estimate falls back to 1.2 of the em, which is a
  setting.
- The drop is along **`View.UpDirection`**, so it is square to the leg rather
  than to the world.
- New setting **Where the tag head sits vertically**: the top line (the
  default), the middle of the text, or the bottom line.
- The results row says how far each elbow was dropped and over how many lines.

## 3.0.0

- **The tag text is no longer assumed to be centred on the head.** 2.0.x
  cleared half the text width whichever way the leg went, which is only right
  for a centred tag. A **left justified** tag has its head at the left hand end
  of the text: going left there is nothing in the way and the leg starts at the
  head, going right the whole width has to be cleared first. Right justified is
  the mirror of it.
- New setting **Where the tag text sits**: left justified (the new default),
  centred on the head, or right justified. The line under it says what that
  means for each direction.
- The results row now reports the text cleared **on that side** as well as the
  tag's full width, so a row can be checked against the drawing.

## 2.0.1

- **Fixed: every run rolled back with "global name \'view\' is not defined".**
  2.0.0 added the tag text measurement, which needs the view, and
  `_do_independent` used `view` without taking it as an argument. Nothing was
  written and nothing was left behind, but nothing worked either.
- Two new rules in `import_check.py`, both of which catch that bug on the
  bench:
  - **every global name a function reaches for exists in its module**
    (`symtable`), which is the rule that sees the missing argument;
  - **every call passes a number of arguments the function takes** (`ast`),
    which is the other half of it - adding an argument and missing a call site
    is a TypeError rather than a name error, so the first rule does not see it.
  Fourteen rules now, all fourteen verified by deliberate breakage.

## 2.0.0

Where the elbow lands has changed, so this is a major.

- **The leg now starts at the end of the tag text, not at the tag head.** The
  head is in the middle of the tag, so a 150mm leg measured from it landed
  inside the text on any tag wider than 300mm. The tag's own text width is
  measured and half of it added, so the elbow always sits clear of the text
  with a 150mm leg beyond it.
- Text width is measured with WPF's `FormattedText` against the tag type's own
  font, text size, width factor, bold and italic, then multiplied by the view
  scale. Revit has no API for the extent of a tag's text, and the tag's own
  bounding box includes the leader, which is the thing being moved. A character
  count estimate stands in where WPF will not measure the string, and the
  report says which of the two was used.
- **A leader running straight up or down now elbows left** rather than being
  skipped. It is the fallback for a leader with no side to take, so it is
  absolute: "reverse" does not flip it. "Skip it and say so" and "elbow to the
  right" are still there.
- New setting **Measure the leg from**: the end of the tag text (default), or
  the tag head, which reproduces 1.0.0.
- Settings version 2. A file written by 1.0.0 has its **straight up or down**
  rule reset to the new default; everything else carries over.

## 1.0.0

First release.

- Two buttons in the **Routines** pulldown on the **Coordination** panel:
  **RevoBIM Tag Leader Elbow** (the command) and **RevoBIM Tag Elbow
  Settings**.
- The command opens no window. It reads the saved settings, takes whatever tags
  are selected, and places an elbow on every leader that is already turned on.
  Nothing selected asks for the tags with `PickObjects`.
- The elbow sits one leg length from the tag head along the **view's own
  horizontal**, on the side the leader already runs. 150mm quoted at 1:50, and
  scaled with the view: 300mm at 1:100, 60mm at 1:20.
- A tag with no leader is skipped and reported, never turned on.
- The tag head is never moved.
- Multi-reference tags get an elbow per leader. Room and space tags are handled
  through `LeaderElbowPosition`.
- One transaction for the whole run, so Revit's undo sees one step.
- Results in a themed window, by default only when something needs a look.
- Dark and light, version top right, settings as plain key=value text.
- Ships `import_check.py` and `bench_logic.py`.
