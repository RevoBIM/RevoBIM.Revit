# Space Data Push - changelog

## 1.2.1

- **The thin white line round the window is gone.** What was left after 1.2.0 was
  Windows' own frame: the OS draws a hairline border round every top-level window
  in the system colour - white on a light Windows theme - and `WindowStyle="None"`
  does not remove it, it only removes the caption. Two routes now take it off, both
  tried and both harmless if they fail: a `WindowChrome` with no glass frame, no
  caption and no resize border, so WPF owns the non-client area; and, once the
  window has a handle, the border bits stripped off its window style with
  `DWMWA_BORDER_COLOR` set to none for Windows 11, which draws a border of its own
  on top. Dragging by the header, the eight resize grips and full screen are
  unaffected.
- The bench check refuses either route going missing, and refuses the handle work
  running before `SourceInitialized`, when there is no handle to work on.

## 1.2.0

- **The white border is gone for good.** 1.1.1 guessed at the cause and left the
  window layered. It is now a plain opaque window: `AllowsTransparency` is off, so
  there is no transparent edge for Revit's canvas to show through on a scaled
  display, and the corners are square because an opaque window has square corners
  behind them anyway. The bench check now refuses a layered window and refuses a
  rounded frame on it.
- **No more fidgeting with the dropdowns as the tool opens.** Two causes, both
  fixed: every box rebuilt its item list each time it was filled, and the window
  filled each box several times while it started - the lists are now compared first
  and left alone when nothing has changed; and focus landed inside the first
  dropdown, which put a caret in it and made it look as though the tool was typing
  into itself. Focus now lands on Pick Space, which is also the default button, so
  Enter starts a pick. A box only opens its list when something has actually been
  typed, and the status line only repaints when the words change.
- **Theme rebuilt.** The blue dot that sat inside every editable box (it read as a
  bullet in front of the value) is gone; a keyboard focus ring round the whole
  control says the same thing better. Slimmer 10px scrollbars, an always-present
  scrollbar on the rows so the columns stay lined up with their headings whether
  the list scrolls or not, and a coloured dot on the status line. The activity list
  now has a colour bar down the left of each line, so an outcome reads at a glance.
- Bench: 27 static rules (54 proved breakages) and 168 logic checks (18 proved).

## 1.1.1

- **The white border round the window is gone.** The window was set to paint
  nothing (`Background="Transparent"`) and relied on the content covering every
  pixel of it. Any band the content does not reach - a DPI rounding band on a
  scaled display - was then a hole straight through to Revit's canvas, which on a
  light canvas reads as a white frame. The window now paints the theme's own
  background, so there is no hole to see through, and it is re-pointed at the
  palette whenever the theme is swapped. The bench check refuses a transparent
  window background from now on.
- Corner radii brought back to the house 6px.

## 1.1.0

- **The search is now inside every dropdown.** The separate search boxes are gone:
  click a list, type, and it narrows as you go. A search matching nothing leaves
  the whole list rather than emptying it, and text that was never picked goes back
  to the real value when you leave the box. Esc closes the list and puts it back.
- **Theme refreshed**: rounder cards, a blue and orange rule under the header,
  sunken panels for the held space and the activity log, section ticks in the
  accent colours, focus and hover states on every field, and a wider, calmer
  layout. Same house palette in dark and light.
- **The easter egg now runs only on three slow clicks on the RevoBIM logo.** The
  hook's own attach() is no longer used to wire it, because what it arms varies
  with its version - arming anything besides the logo is how clicking Close three
  times can start the game.
- **Settings are remembered properly**: the rows, the category, the four options,
  the theme and now the **window size**, saved when the window closes and again
  after every pick, so a crash cannot lose the mapping.
- **Picking returns you to the window.** When you press Esc the window comes back
  to the front with Pick Space focused and set as the default button, ready for
  the next space. The status line says how many elements were pushed.
- Bench: 26 static rules (47 proved breakages) and 168 logic checks (18 proved
  breakages).

## 1.0.0

First release. Coordination > Routines.

- Modeless window owned by Revit's main window, so it floats in front of Revit.
- Left: space parameters, any parameter spaces carry, with a keyword search and
  a live preview of the value the held space has. Right: an element category
  (Detail Items by default) and the writable parameters that category carries.
  Rows pair one with the other; add as many as needed.
- Pick Space (or use the space already selected), go to any view - plan,
  drafting, section, 3D - and Pick Elements and Push. Keeps picking until Esc.
- Every value is read back after the commit; a write that did not stick is
  reported as failed. Workshared elements held by someone else are reported by
  owner. One transaction per element, warnings swallowed.
- Text, whole-number and number parameters; a number is only copied straight
  across when the units agree, otherwise it is skipped and says why.
- Dark and light, Auto follows Revit's canvas theme; chip in the header.
- Version top right; three slow clicks on the RevoBIM logo for the easter egg.
- Works on Revit 2024, 2025, 2026 and 2027.
