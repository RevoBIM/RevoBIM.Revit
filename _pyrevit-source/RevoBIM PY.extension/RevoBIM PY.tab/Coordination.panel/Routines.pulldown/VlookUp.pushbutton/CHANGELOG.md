# VlookUp - changelog

## 1.0.1
- Fixed `ImportError: Cannot import name Thickness` on launch.
  `vlookup_window.py` imported WPF types out of `System.Windows` without
  referencing the WPF assemblies itself. A .NET namespace only carries the
  names of assemblies the module has already asked for, and referencing them
  in `vlookup_ui.py` does not help, because the failing import runs before
  that module is reached. Every module that imports a .NET type now carries
  its own `clr.AddReference` block above the imports.
- `vlookup_ui.py` now references `System.Xml`, and `script.py` references
  `RevitAPI` / `RevitAPIUI`, for the same reason.
- `import_check.py` gained a rule for this whole class of bug: each namespace
  a module imports from must be preceded, in that same file, by a
  `clr.AddReference` for the assembly it lives in. Verified by removing the
  block again and confirming the check reported all three imports.

## 1.0.0
First release.

- Reads .xlsx, .xlsm and .csv with no Excel, no COM and no installed package -
  the workbook is unzipped and parsed straight out of its Office Open XML,
  with shared strings, inline strings, cached formula results and date serials
  all resolved. The file is opened shared, so a workbook open in Excel still
  reads.
- Spreadsheet preview in the window: pick the worksheet, say which row holds
  the headers, and click a column header to make it the lookup column.
- Scope by current selection, active view or the whole model, narrowed by
  category, with a keyword search over the category list.
- Match on any readable parameter, instance or type, or on Element ID,
  Unique ID, family name, type name, family and type, or category.
- Column-to-parameter mapping, one row per spreadsheet column, with
  Auto-match for columns whose caption is already a parameter name.
- Type parameters are off by default and warned about before writing, because
  one write lands on every instance of that type in the project.
- Matching options: ignore case, trim spaces, number-aware compare (so 1.0
  matches 1), and what to do with repeated keys.
- Check matches runs the whole thing without touching the model and reports
  what would happen; Apply asks first, then writes in one transaction.
- Values that already agree with the spreadsheet are left alone rather than
  rewritten, so the model does not churn.
- Units are respected on length, flow and other double parameters: a bare
  number is read in the parameter's own display units, and text carrying a
  unit falls back to SetValueString.
- Yes/No parameters take Yes, Y, True, 1 or X.
- Mapping profiles saved by name under
  %APPDATA%\RevoBIM\vlookup_profiles\, last-used settings under
  %APPDATA%\RevoBIM\vlookup.txt, both plain key=value text.
- Results in a themed window, with Copy and Save as text.
- import_check.py ships with the tool.
