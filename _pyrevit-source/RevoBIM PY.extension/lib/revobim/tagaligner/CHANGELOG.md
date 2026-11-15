# Tag Aligner — changelog

## 1.0.0 — 2026-10-22

First release. Six small buttons on the RevoBIM PY tab, Annotation panel, in
two stacks:

- **Tag Align Left / Center / Right** — lines the selected tags up on their
  left edge, centre or right edge, to the first tag selected, the average of
  them all, or a tag clicked after pressing the button. Only the
  side-to-side position changes.
- **Tag Untangle Vertical / Horizontal** — spaces the selected tags out
  evenly so none overlap: each tag's measured height (or width) plus a clear
  gap of text height × 0.5, so single line tags sit text height + text
  height / 2 centre to centre. Text height read from the tag families, scaled
  by the view. Fixed pitch available instead.
- **Tag Aligner Settings** — every rule above, leader elbows, pinned tags,
  results window, debug log.

Tags are measured with their leaders switched off (SubTransaction, rolled
back) and in the view's own right/up axes; leader elbows travel with the
head; every move is measured again before commit. Room, space and area tags
work as well as IndependentTag. Revit 2024–2027 from one copy.
