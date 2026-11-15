# Bulk Rename

## 1.1.0
- Write Sheet names button: splits each sheet's name on the delimiter into three
  parameters. Settings gear top right chooses the parameters and delimiter.

## 1.0.2
- Switching tab widens the window to fit the longest line on that tab.

## 1.0.1
- Fixed the load error "Cannot import name PresentationSource": it lives in
  System.Windows, not System.Windows.Media. New bench rule holds every .NET
  import to its real namespace.

## 1.0.0
- First version. Tools on the left (Find and replace, Add prefix, Add suffix),
  selected Project Browser items on the right with a live preview.
- Sheet Name / Sheet Number tabs when sheets are selected.
- Window sizes itself to the selection. Apply writes; prompt when nothing is
  selected in the Project Browser.
