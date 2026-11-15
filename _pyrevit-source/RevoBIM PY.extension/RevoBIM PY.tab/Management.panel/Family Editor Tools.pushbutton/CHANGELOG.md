# Family Editor Tools - changelog

## 1.6.0

**Flex test** - the last placeholder is built.

- **What to flex**, on the left: every parameter a run can drive, each
  with a minimum and maximum **already filled in** at plus and minus fifty
  per cent of what it currently holds. Tick what matters, set the ends, say
  how many steps to take between them.
- A parameter with a **formula**, a **reporting** parameter and a read only
  one are left out. Setting those is refused by Revit, so offering them
  would fill the report with noise instead of faults.
- **Every type, or just this one.** The round count is shown before you
  press anything, because every type is driven through every value of every
  parameter and that grows faster than it looks. Past 400 rounds the button
  greys out and says so.
- **What happened**, on the right, worst first: *broke* (it would not
  regenerate), *refused* (Revit would not take the value), *not taken* (the
  value was accepted and did not stick), *warned* (it regenerated, with a
  warning Revit would otherwise have swallowed), *ok*. A tick hides
  everything that passed. **Copy the report** puts the lot on the clipboard
  as tab separated text.
- **Nothing is left changed.** The whole run sits inside a
  `TransactionGroup` that is rolled back in a `finally`, and the type the
  family was on is put back. If Revit will not open the group, the run does
  not start - it could not have been undone afterwards. A new bench rule
  enforces all of that, because the one thing worse than a flex run that
  finds no faults is one that leaves the family broken.
- The warnings are **recorded rather than deleted**. A value that
  regenerates with "constraints are not satisfied" is precisely what a flex
  run is looking for.
- 20 bench rules, 128 logic checks, 69 breakages, all caught.

## 1.5.1

- **The family icon settings live in the main Settings window**, as three
  tabs: *Icon appearance*, *Icon options* and *Family naming*, beside
  *General*. That is now the one place they are.
- **The Family icon settings button stays where it was** and opens the same
  window on the *Icon appearance* tab. Two windows for one set of settings
  is two places for them to disagree, so the second one is gone rather than
  kept in step by hand.
- The settings window gained the **Radius** parameter name box, which the
  revolve page drives and the old layout had no room for.
- The window now resizes and remembers nothing it should not: Apply writes
  everything on every tab at once.

## 1.5.0

**Family Icon and Name** - the side rail section is built.

**The icon**

- **Family icon settings**, a window of its own with three tabs.
  *Appearance Settings* carries display style, detail level, view scale and
  view type for 3D and 2D families; *General Settings* carries the
  thumbnail view name and fifteen ticks - export images, lock the 3D
  orientation, gradient background, and hide dimensions, reference points,
  reference lines, reference planes, text notes, invisible lines, flip
  controls, room calculation points, host elements, connector elements,
  void elements and imported elements.
- **Apply image** builds a 3D view named after the setting, points the
  camera at the chosen corner, applies the style, detail and scale, hides
  everything ticked, opens it, and holds it as the view the family will be
  saved with.
- The view is **rebuilt from scratch** each time rather than adjusted: one
  somebody has since tilted or filtered would otherwise produce a thumbnail
  nobody can explain.
- **A void is not a category** - it is a form with `IsSolid` false - and
  neither is an import, so those two are hidden as elements. A category a
  release does not carry is skipped rather than throwing.

**The name**

- Four boxes - **Company, Family type, Discipline, Family name** - built
  into `BGL_PFX_DOM_Waste Connection` and previewed live as you type.
- The three abbreviations are **dropdowns fed from your own standards**,
  kept in the settings window's *Family Naming* tab, one per line as
  `CODE = what it means`. The dropdown shows both; only the code goes into
  the name.
- **Save family** appears, highlighted, once all four are filled. It opens
  an explorer window at the folder you last used, with the built name
  already in it.
- The family is saved with **the thumbnail view as its preview**
  (`SaveAsOptions.PreviewViewId`), which is the only API route to the
  picture Windows and Revit's own load dialog show. Press Save family
  without pressing Apply image first and the view is built for you, because
  saving without one is how a family ends up with a grey box for a preview.
- With *Export Images* ticked, a PNG of the view is written beside the
  family.

- 114 logic checks, 61 breakages, all caught.

**Not built:** the per-category appearance overrides from the Appearance
tab. The default appearance applies to the whole family.

## 1.4.3

**Standard planes: a parameter picked for the page is used**

- Pointing a page at one of the family's own parameters now **always**
  places the dimension and labels it with that parameter. The two ticks -
  *Label the dimensions with parameters* and *Create the parameters the
  layout drives* - govern **inventing** a parameter where none was picked;
  they no longer override a choice made on purpose, which is what stopped
  an assigned parameter being used at all.
- The result says which happened: the family's own parameter now driving
  the dimension **and that its value becomes the measured distance**, a
  parameter created because the page had none, or one created because the
  parameter the page was pointed at is no longer in the family.
- The panel says it too, in green under the dropdowns, as soon as anything
  is picked.
- Picking a parameter refreshes the dropdowns, so the note and the
  type/instance suffix stay in step.
- 103 logic checks, 55 breakages, all caught.

## 1.4.2

The trace showed all three routes failing, each for its own reason:

    trying: copied whole
      route 1 copy of the asset element returned nothing
    trying: built from Revit's own GenericSchema asset
      route 2 found 0 library assets for schema 'GenericSchema'
    trying: written into the one the family made
      no asset element from this route

- **Route 2 was matching on the wrong thing.** A library asset's `Name` is
  its own name - *Aluminium - Anodised* - not its schema. The schema is in
  the asset's **`BaseSchema` property**, which is why nothing matched in a
  library of 3104. It now reads `BaseSchema`, and stops after finding a few
  rather than walking all three thousand.
- **Route 3 had nothing to work with.** It duplicated the asset on the
  material - and this material has `AppearanceAssetId: -1`, no asset at
  all. That route is now the last one, and a **new route sits in front of
  it: duplicate an appearance asset element already in the family that is
  built on the same schema.** A family template carries dozens of them -
  this one has 35 - and duplicating one produces an asset of exactly the
  right shape without anything having to cross between documents.
- **Route 1's exception now reaches the trace**, not just the log, so a
  refusal from `CopyElements` is in the report you send rather than a file
  you have to find.
- **Schema properties are out of the comparison.** `AdvancedUIDefinition`,
  `BaseSchema`, `localname`, `category`, `PatternOffset` and the rest
  describe the schema, not the look, and are read only - so a look that
  transferred perfectly still read back as different. They are ignored when
  comparing, and still offered to the write in case a release takes them.
- 100 logic checks, 53 breakages, all caught.

## 1.4.1

The diagnostics named it on the first line of the load:

    existing: BGL_PVC Red - already in this family

**"Already in this family" was skipping the appearance step entirely.**
An earlier run had copied the material across with `AppearanceAssetId: -1` -
no appearance asset at all - and every run after that saw the name, called
it done, and never looked at the asset. Three releases of appearance fixes
were correct and never ran.

- **A material already in the family is checked and repaired like any
  other.** It is reported as already there, and its appearance is still
  brought over.
- **The scan list keeps existing materials tickable**, with the row saying
  *already here - its appearance can still be brought over*. Greying them
  out was what made the problem impossible to put right from the window.
- **A second thing the dump caught: the comparison could never have
  succeeded.** The rendering asset carries `thumbnail`
  (`tmp:?MaterialThumbnails_PID_d398\b33c64e0.png` - a temp path with the
  process id in it), `UIName`, `VersionGUID`, `ExchangeGUID`, `AssetLibID`
  and `revision`. Two copies of the same appearance never agree on any of
  them. They are now left out of both the comparison and the write - a
  perfect copy was reading back as a failure.
- The trace now says, per material, whether the appearance already matched,
  did not match, or was not looked at - which is the line that would have
  shown this straight away.
- 96 logic checks, 51 breakages, all caught.

**What the dump also told us, for the record:** the source asset's schema is
`GenericSchema`, not `Generic`, from `assetlibrary_base.fbx`, and Revit's
library holds 3104 appearance assets - so the library route has something to
match against. The material copy genuinely brings no appearance asset with
it, which is what the three routes exist for.

## 1.4.0

**A Diagnose button, because the material transfer still is not working**

Three releases have guessed at which Revit call is giving way. This one
stops guessing and reports it.

- **Diagnose**, beside Scan on the Materials tab. Tick up to five
  materials, pick the model they come from, and press it. The tool runs the
  **real load**, with everything on the appearance asset path saying what it
  did, and writes a full report.
- The report carries: the Revit version and build, the family and its
  category, whether `Application.GetAssets` works and how many appearance
  assets Revit's own library holds, the **complete property dump of the
  source material's rendering asset** (schema, title, library, every
  property with its type and value, and every connected texture), the
  dependency ids handed to `CopyElements`, what each of the three routes
  returned, every exception with its traceback, how many properties were
  written, and the **same complete dump of the material in the family
  afterwards**.
- It is **copied to the clipboard** as well as saved to
  `%APPDATA%\RevoBIM\fet_diagnostics.txt`, so it can be pasted straight
  into a chat.
- **Settings: "Write a diagnostic trace on every material load"**. With it
  on, the ordinary Load into the family button takes the same path - the
  same code, described as it goes - so a failure that only happens on a
  real run is still captured.
- Long values are cut short and the trace stops at 6000 lines, because a
  report nobody can read is a report nobody sends.
- 92 logic checks, 48 breakages, all caught.

## 1.3.5

**The appearance asset: the property write now always runs**

1.3.4 tried three routes but gated the last one - the only one that does
not depend on an element crossing between documents - on the two assets'
**schema names matching**. `Asset.Name` does not reliably return a schema,
so that guard bailed out on assets that would have written across perfectly
well, and the material kept the default `Generic(n)` Revit had invented for
it.

- **The three routes now only decide which asset element to point the
  material at.** The source's properties are written into it afterwards
  **whichever route produced it** - a route that gave an empty asset of the
  right shape is still a win.
- The routes, in order: copy the source asset element across; **create one
  from Revit's own library asset of the same schema**
  (`Application.GetAssets`), which is the only route that reliably produces
  the right shape; duplicate whatever the family attached.
- **"Nothing in common" is now measured, not guessed.** The write reports
  how many properties it actually matched by name; zero means a different
  schema. Comparing schema names was a guess.
- **The asset is renamed to `<source asset> (<source model>)` whichever
  route ran**, so the family stops filling up with `Generic(4)`,
  `Generic(5)` and there is something readable to check against.
- **Textures are carried.** A connected asset is walked, and where the
  target property has no texture slot at all one is added with
  `AddConnectedAsset` before writing into it.
- A read-only property no longer stops the rest of the asset being written.
- 88 logic checks, 45 breakages, all caught.

## 1.3.4

**The appearance asset, for real this time**

What actually happens is worse than a name clash: handed a material,
**Revit invents a fresh default Generic asset in the family and attaches
that** - `Generic(4)`, RGB 80,80,80 - rather than bringing the source asset
over at all. The material arrives named correctly, it has an appearance
asset, and it renders grey. Every check up to 1.3.3 passed it.

- **Three routes, tried in turn, each proved by reading the properties
  back**:
  1. copy the source asset element across, parking a name clash if there is
     one;
  2. **create a new asset in the family from the source's own rendering
     asset** (`AppearanceAssetElement.Create`);
  3. **write the source's properties into the asset the family made**,
     through an `AppearanceAssetEditScope` - the route that does not depend
     on an element crossing between documents at all.
- Route 3 **duplicates the asset first**, because Revit may have handed the
  same default asset to several materials and editing it in place would
  change all of them.
- Every route to a property value is tried: a colour is four doubles, a
  glossiness is one, a highlight is an enum, and a read-only property
  throws rather than saying so.
- Where the family made a different **schema** of asset from the source -
  Generic against Metal - nothing can be written across, and it says so by
  name instead of half-doing it.
- **The asset's element name is no longer part of the comparison.** The
  same appearance rebuilt under another name is the same appearance;
  including the name made every rebuild read as a failure.
- The transaction bench rule now covers `AppearanceAssetEditScope` too,
  which opens its own transaction exactly as `CopyElements` does.
- 83 logic checks, 41 breakages, all caught.

## 1.3.3

**The appearance asset really comes over now**

- **The name clash was the bug.** `CopyPasteOptions` can only answer a
  duplicate name with `UseDestinationTypes`, so a material copied into a
  family whose template already carries an appearance asset of that name
  quietly ended up pointing at the **family's** asset - same name, none of
  the properties. The copy succeeded, nothing threw, and the material
  rendered wrong. 1.3.2 only checked that an asset was attached, which it
  was.
- **The asset is now compared by content, not by name.** The whole
  rendering asset property tree - including the connected assets that carry
  the textures - is flattened and the source and the arrival compared.
- **Where they differ, the source asset is forced over**: the family's own
  asset is parked under another name for the length of the copy, the
  arrival is renamed to `<asset> (<source model>)`, and the family's asset
  is put back. The material is then pointed at the arrival and **read back
  again** to confirm it matches.
- Anything that still will not match is reported by name saying to check it
  by hand, rather than looking like it worked.
- The transaction bench rule now notices a **commit**, so it can tell a
  transaction that is still open at the copy from one that was properly
  closed first, and it checks the asset copy as well.
- 77 logic checks, 37 breakages, all caught. The duplicate definition rule
  caught a bad edit in this very release, which is what it is for.

## 1.3.2

**A material now brings its assets with it**

- The copy set is no longer the material on its own. Its **appearance,
  thermal and structural assets** and its **fill patterns** - every spelling
  of them across 2024 to 2027 - go to `CopyElements` in the same call, so the
  material cannot land in the family as a flat colour with nothing behind it.
- **A void API call is not evidence.** Every material that arrives is asked
  whether it actually has its appearance asset. One that does not has the
  asset **fetched on its own** and pointed back at it, and the row says so.
- A material whose asset Revit will not hand over at all is reported by name
  with the asset named too, rather than arriving quietly wrong.
- The bench rule about transactions now checks **every** function that
  copies, not just the first one that did it, since the reconnect step
  copies as well.
- 70 logic checks, 33 breakages, all caught.

## 1.3.1

**Loading a material out of a project failed**

- `ElementTransformUtils.CopyElements` between two documents **opens its own
  transaction**, so calling it inside one is answered with "Copying one or
  more elements failed" - a message that says nothing about the real cause.
  1.3.0 wrapped it in a transaction and a sub-transaction. The copy now runs
  outside both, inside a `TransactionGroup` so Revit's undo still sees one
  step.
- The whole ticked batch goes in **one call**; a refused batch is **replayed
  one at a time**, so the one at fault is named and only that one is lost.
- Anything Revit still will not copy is **rebuilt from what was read off it**
  and says so - the colour and class come across, the appearance asset does
  not.
- New bench rule: **the cross document copy runs outside a transaction**,
  proved by putting the transaction back and watching it fail. 19 rules.

**The window is quicker**

- **Parameter group lookups are indexed once.** A linear scan over ~200
  groups, per parameter, per row, was most of the delay.
- **A row's group dropdown fills when it is opened**, not when it is drawn.
  Building 200 items for every row is what made a family with a hundred
  parameters take a visible moment.
- **Standard planes reuses the read it already has** rather than re-reading
  every parameter in the family when the page opens - that was the second's
  hang.
- **The view a page needs is looked up once** and remembered, rather than
  collecting every view in the family on each press of the arrows.
- **What the family already carries is cached per refresh**, not collected
  again on every keystroke.
- **Long lists draw the first 250 rows** and say how many matched, rather
  than quietly building 663 rows of live controls. Narrow the search and the
  rest appear.

## 1.3.0

**The side rail**

- **Standard planes moved out of the tabs and onto the side rail**, beside
  Builder, Flex test and Family icon. Every rail entry and every Builder tab
  now carries an icon, drawn from `Path` geometry rather than a symbol font.

**Standard planes**

- **Each page picks the family parameter it drives.** Width, Depth, Height,
  Clearance and Radius each get a dropdown of the family's own length
  parameters, or *Create '<name>'*. The choice is remembered **per page**, so
  the centred box and the revolve page can drive different parameters.
  Reporting parameters and parameters already driven by a formula are left
  out - a dimension cannot drive those.
- **A new page: Revolve, front elevation.** The axis on the centre, a radius
  plane to sketch the profile against, and the bottom and top it runs
  between.
- **Set out opens the view it needs.** Ref. Level, Front, and the other names
  Revit's own family templates use, then any view of the right kind that
  points the right way. The panel says which view it will open before you
  press it.

**Materials, line styles and annotation styles**

- **Harvest from any open model.** A dropdown at the top of each tab lists
  the RevoBIM presets and every model open in the session; Scan reads it,
  and the list is searchable and tickable as before. Anything the family
  already carries is greyed out and says so.
- Materials and annotation types are **copied** out of the source model, so
  their appearance assets, patterns and arrowheads come with them. A line
  style is **rebuilt** from what was read off it, because a subcategory is
  not an element `CopyElements` will take.

**Parameters**

- **Remove selected** takes staged parameters back off the list.
- **The swap is now a selection, not a dropdown.** Click a new parameter on
  the left and every family parameter it could replace lights up on the
  right, tinted and outlined in that data type's colour. Pick one and a
  **Swap parameters** button appears. Pressing it shows the pending swap on
  the right - *old will become new* in violet - and **writes nothing** until
  **Apply changes**, which now applies the swaps and the table edits
  together.
- A swapped parameter still **takes the type or instance setting and the
  group of the parameter it replaces**.

**Bench**

- 64 logic checks (up from 54), 30 deliberate breakages, all caught.

## 1.2.0

- **The parameter loader has its own tab.** Builder now opens on
  **Parameters**, with the shared parameter staging list on the left and
  **every parameter in the open family** on the right.
- **Every staged parameter carries its own settings.** Type or instance and
  the parameter group are now per row, not one choice for the whole
  selection, and a template saves exactly what was set.
- **New or replace, per row.** A staged parameter can be added as new, or
  set to **replace** a named parameter already in the family, through
  `FamilyManager.ReplaceParameter` - so the formulas, labels and values that
  pointed at the old one survive the swap. **A replacing parameter takes the
  binding and group of the parameter it replaces**, and its two dropdowns
  grey out to say so.
- **The family parameter table is editable.** Name, type/instance, group and
  formula, with the current value on the tooltip. Nothing is written until
  **Apply**, and Apply lists what it is about to do. Built-in parameters are
  marked and left alone.
- **Renames go through a parked name** where any wanted name is held by
  something else in the same batch, so swapping two names round does not
  fail on a clash with itself. A clash with a name nobody is moving is
  reported before anything is written.
- **A colour per data type**, the same key on a staged parameter and on the
  family parameter it would replace, with a legend under the tab. Twelve
  kinds, and both spellings - the file's `LENGTH` and Revit's `Length` -
  land on the same one.
- **Filters over the family's parameters**: a keyword box and a data type
  dropdown that only offers the types actually present.
- Bench: 54 logic checks (up from 38), 25 deliberate breakages, all caught.
  Three of them were caught only after being retargeted, which is the point
  of running the selftest: a breakage that makes both halves of an equality
  fail identically proves nothing.

## 1.1.0

- **Side rail down the left of the window**, with three sections: **Builder**
  (everything 1.0.0 did), **Flex test** and **Family icon**. The section is
  remembered between runs.
- Flex test and Family icon are **placeholders** - each says plainly that it is
  not built yet and what it will do, with its action button greyed out, rather
  than being an empty tab.
- The side tabs are `RadioButton`s with a template trigger, so which section is
  open is a state WPF holds rather than something the code keeps in step.
- Bench: a new rule, **no identity comparison on a handler sender**. `is`
  compares Python object identity, not .NET object identity, so a handler that
  compares its sender that way never fires and nothing about it looks wrong.
  The section switch was written that way first and the rule now forbids it.
  18 rules, all proved by deliberate breakage.

## 1.0.0

First release.

- Single button on the **RevoBIM PY** tab, **Management** panel, with a
  single line title so Revit's Keyboard Shortcuts dialog can bind keys to it.
- Refuses politely outside the family editor rather than opening onto nothing.
- **Shared parameters** down the left: open any shared parameter file in its
  own window, search it, tick as many parameters as you like, choose type or
  instance and the parameter group, and stage them. A ticked selection saves
  as a named template and comes back on the next family.
- **Materials**, **Line styles** and **Annotation styles** tabs: editable
  preset lists that load into the open family in one press, seeded with a
  house set and able to harvest what the current family already carries.
- **Standard planes** tab: seven setting-out layouts, a live preview drawn
  from the same positions the model gets, and arrows to cycle through them.
  Creates the reference planes, names them, sets their Is Reference value,
  equalises them about the centre and labels the driving dimensions with
  family parameters.
- Dark and light, switched from the chip in the header and following Revit's
  own theme by default.
- The RevoBIM logo takes three slow clicks.
- Bench checks: `import_check.py` (16 rules) and `bench_logic.py`, both with
  a `--selftest` that proves every rule catches its own deliberate breakage.
