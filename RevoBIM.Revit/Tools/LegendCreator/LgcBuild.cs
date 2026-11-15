using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Windows.Automation;
using System.Windows.Threading;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Events;
using static RevoBIM.Tools.LegendCreator.LgcCore;
using static RevoBIM.Tools.LegendCreator.LgcLogic;

namespace RevoBIM.Tools.LegendCreator
{
    /// <summary>Everything the Family Legend tab hands to the build.</summary>
    public sealed class FamilyOptions
    {
        public string Theme, ThemeMode, Phase, NameParam, TextTypeName, TextCase;
        public bool Debug, Combined;
        public ElementId TextTypeId;
        public int Scale;
        // real view millimetres at the chosen scale
        public double RowSpacing, TextOffset, ColumnSpacing;
    }

    /// <summary>Everything the System Colour Legend tab hands to the build.</summary>
    public sealed class SystemOptions
    {
        public LegendKind Kind;
        public string Theme, ThemeMode, Heading, RegionPrefix, Style, TemplateName, ViewName;
        public string TextTypeName, HeadTypeName;
        public bool Debug, Centreline, Upper;
        public int LineWeight, Scale;
        public ElementId TextTypeId, HeadTypeId;
        public double SwatchW, SwatchH, RowPitch, TextGap, HeadingGap;
        public List<(string Header, List<LegendEntry> Entries)> Groups;
        public List<string> Notes = new List<string>();
    }

    /// <summary>What a run's progress display offers the build.</summary>
    public interface ILegendProgress
    {
        bool Cancelled { get; }
        void Update(int value, int max);
    }

    /// <summary>Deletes warnings so none of them stops to ask.</summary>
    internal sealed class WarningSwallower : IFailuresPreprocessor
    {
        public FailureProcessingResult PreprocessFailures(FailuresAccessor accessor)
        {
            try
            {
                accessor.DeleteAllWarnings();
            }
            catch (Exception err)
            {
                Swallowed(err);
            }
            return FailureProcessingResult.Continue;
        }
    }

    /// <summary>
    /// Legend Creator - writing the legends. Legend views, components, filled
    /// region types, line styles and patterns, swatches and text; the quiet
    /// transactions and dialog suppression around them; opening the result
    /// and finding it in the Project Browser. Port of lgc_build.py.
    /// </summary>
    public sealed class LgcBuild
    {
        private readonly UIApplication uiapp;
        private readonly Document doc;

        // Revit's own dialogs are answered for the duration of a run.
        public readonly List<string> DialogsSeen = new List<string>();
        private bool dialogsHooked;

        public LgcBuild(UIApplication application, Document document)
        {
            uiapp = application;
            doc = document;
        }

        private static string Name(Element element) => LgcModel.ElementName(element);
        private static long Eid(ElementId id) => LgcModel.Eid(id);

        // -----------------------------------------------------------------
        // Dialog suppression
        // -----------------------------------------------------------------
        private void OnDialog(object sender, DialogBoxShowingEventArgs args)
        {
            try
            {
                DialogsSeen.Add(args.DialogId ?? "");
            }
            catch (Exception err)
            {
                Swallowed(err);
            }
            foreach (int result in new[] { 1, 6, 2 }) // OK, Yes, Cancel - first that is taken
            {
                try
                {
                    args.OverrideResult(result);
                    return;
                }
                catch (Exception err)
                {
                    Swallowed(err);
                }
            }
        }

        /// <summary>Answer Revit's dialogs while on; unhook when off.</summary>
        public void SuppressDialogs(bool on)
        {
            try
            {
                if (on && !dialogsHooked)
                {
                    DialogsSeen.Clear();
                    uiapp.DialogBoxShowing += OnDialog;
                    dialogsHooked = true;
                }
                else if (!on && dialogsHooked)
                {
                    uiapp.DialogBoxShowing -= OnDialog;
                    dialogsHooked = false;
                }
            }
            catch (Exception err)
            {
                Swallowed(err);
            }
        }

        private static Transaction Quiet(Transaction trans)
        {
            try
            {
                FailureHandlingOptions options = trans.GetFailureHandlingOptions();
                options.SetFailuresPreprocessor(new WarningSwallower());
                options.SetClearAfterRollback(true);
                trans.SetFailureHandlingOptions(options);
            }
            catch (Exception err)
            {
                Swallowed(err);
            }
            return trans;
        }

        // -----------------------------------------------------------------
        // Legend construction
        // -----------------------------------------------------------------
        /// <summary>
        /// Delete the drafting content a duplicated legend inherited. Deliberately
        /// narrow: never the view, its SketchPlane or anything without a category -
        /// deleting the work plane can crash Revit on the next creation in it.
        /// </summary>
        private void ClearLegend(View view)
        {
            var allowed = LgcModel.CategoryIdSet(ClearableCategories);
            var victims = new List<ElementId>();

            foreach (Element element in new FilteredElementCollector(doc, view.Id).WhereElementIsNotElementType())
            {
                if (element == null || element.Id == view.Id) continue;
                if (element is View || element is SketchPlane) continue;
                try
                {
                    if (!element.ViewSpecific || element.OwnerViewId != view.Id) continue;
                }
                catch (Exception err)
                {
                    Swallowed(err);
                    continue;
                }
                Category category = element.Category;
                if (category == null || !allowed.Contains(Eid(category.Id))) continue;
                victims.Add(element.Id);
            }

            if (victims.Count > 0)
            {
                try
                {
                    doc.Delete(victims);
                }
                catch (Exception err)
                {
                    Swallowed(err);
                }
            }
        }

        private Element CloneComponent(View seedView, Element seedComponent, View targetView)
        {
            var copied = ElementTransformUtils.CopyElements(
                seedView, new List<ElementId> { seedComponent.Id }, targetView,
                Transform.Identity, new CopyPasteOptions());
            foreach (ElementId newId in copied) return doc.GetElement(newId);
            return null;
        }

        /// <summary>Clone a legend component, point it at typeId, centre it on x, y.</summary>
        private Element PlaceComponent(View seedView, Element seedComponent, View view, ElementId typeId,
                                       double x, double y)
        {
            Element component = CloneComponent(seedView, seedComponent, view);
            if (component == null) return null;

            Parameter param = component.get_Parameter(BuiltInParameter.LEGEND_COMPONENT);
            if (param == null || param.IsReadOnly)
            {
                doc.Delete(component.Id);
                return null;
            }
            param.Set(typeId);
            doc.Regenerate();

            BoundingBoxXYZ box = component.get_BoundingBox(view);
            double centreX = 0.0, centreY = 0.0;
            if (box != null)
            {
                centreX = (box.Min.X + box.Max.X) / 2.0;
                centreY = (box.Min.Y + box.Max.Y) / 2.0;
            }

            ElementTransformUtils.MoveElement(doc, component.Id, new XYZ(x - centreX, y - centreY, 0.0));
            return component;
        }

        /// <summary>Duplicate the seed legend, rename it, scale it, and empty it.</summary>
        private View MakeLegendView(View seedView, string name, HashSet<string> taken, int scale)
        {
            const ViewDuplicateOption option = ViewDuplicateOption.Duplicate;
            if (!seedView.CanViewBeDuplicated(option)) return null;

            var view = (View)doc.GetElement(seedView.Duplicate(option));
            try
            {
                view.Name = UniqueViewName(name, taken);
            }
            catch (Exception err)
            {
                Swallowed(err);
            }
            try
            {
                view.Scale = scale;
            }
            catch (Exception err)
            {
                Swallowed(err);
            }

            ClearLegend(view);
            return view;
        }

        private static TextNoteOptions MiddleLeft(ElementId typeId)
        {
            var options = new TextNoteOptions(typeId) { HorizontalAlignment = HorizontalTextAlignment.Left };
            try
            {
                options.VerticalAlignment = VerticalTextAlignment.Middle;
            }
            catch (Exception err)
            {
                Swallowed(err);
            }
            return options;
        }

        /// <summary>Fill a legend with one column per CategoryInfo. Returns (placed, skipped).</summary>
        private (int Placed, List<(string Label, string Reason)> Skipped) PopulateLegend(
            View view, List<CategoryInfo> infos, View seedView, Element seedComponent, FamilyOptions opts)
        {
            double spacing = ToInternal(opts.RowSpacing);
            double offset = ToInternal(opts.TextOffset);
            double columnGap = ToInternal(opts.ColumnSpacing);

            var skipped = new List<(string, string)>();
            var columns = new List<(double X, List<(Element Component, double Y, string Text)> Placed)>();

            for (int columnIndex = 0; columnIndex < infos.Count; columnIndex++)
            {
                double columnX = columnGap * columnIndex;
                var placed = new List<(Element, double, string)>();
                int row = 0;
                foreach (ElementId typeId in infos[columnIndex].TypeIds)
                {
                    Element elementType = doc.GetElement(typeId);
                    if (elementType == null) continue;
                    string label = LgcModel.FamilyTypeLabel(elementType);
                    Element component;
                    try
                    {
                        component = PlaceComponent(seedView, seedComponent, view, typeId, columnX, -spacing * row);
                    }
                    catch (Exception err)
                    {
                        skipped.Add((label, ErrText(err)));
                        continue;
                    }
                    if (component == null)
                    {
                        skipped.Add((label, "type cannot be shown as a legend component"));
                        continue;
                    }

                    string text = ApplyCase(LgcModel.ParamText(elementType, opts.NameParam), opts.TextCase);
                    placed.Add((component, -spacing * row, text));
                    row++;
                }
                columns.Add((columnX, placed));
            }

            doc.Regenerate();

            int total = 0;
            foreach (var (columnX, placed) in columns)
            {
                if (placed.Count == 0) continue;
                total += placed.Count;

                // One text column per category, measured off the widest component
                // in that column so the labels line up instead of running ragged.
                double textX = columnX;
                foreach (var (component, _, _) in placed)
                {
                    BoundingBoxXYZ box = component.get_BoundingBox(view);
                    if (box != null) textX = Math.Max(textX, box.Max.X);
                }
                textX += offset;

                foreach (var (_, y, text) in placed)
                    TextNote.Create(doc, view.Id, new XYZ(textX, y, 0.0), text, MiddleLeft(opts.TextTypeId));
            }

            return (total, skipped);
        }

        private ElementId SolidFillPatternId()
        {
            foreach (FillPatternElement pattern in new FilteredElementCollector(doc).OfClass(typeof(FillPatternElement)))
            {
                try
                {
                    if (pattern.GetFillPattern().IsSolidFill) return pattern.Id;
                }
                catch (Exception err)
                {
                    Swallowed(err);
                }
            }
            return null;
        }

        /// <summary>A filled region wants a drafting pattern; a filter may hand back a model one.</summary>
        private ElementId UsablePatternId(ElementId patternId, ElementId fallbackId)
        {
            if (patternId == null) return fallbackId;
            if (!(doc.GetElement(patternId) is FillPatternElement pattern)) return fallbackId;
            try
            {
                if (pattern.GetFillPattern().Target == FillPatternTarget.Drafting) return patternId;
            }
            catch (Exception err)
            {
                Swallowed(err);
            }
            return fallbackId;
        }

        private FilledRegionType FindFilledRegionType(string name)
        {
            return new FilteredElementCollector(doc).OfClass(typeof(FilledRegionType))
                .Cast<FilledRegionType>().FirstOrDefault(t => Name(t) == name);
        }

        private static (int, int, int)? Rgb(Color colour)
        {
            if (colour == null || !colour.IsValid) return null;
            return (colour.Red, colour.Green, colour.Blue);
        }

        private static Color ToColor((int R, int G, int B) c)
        {
            return new Color((byte)Channel(c.R), (byte)Channel(c.G), (byte)Channel(c.B));
        }

        /// <summary>
        /// Write colour, pattern and line weight onto a filled region type -
        /// unconditionally, so a re-run brings an existing type up to date.
        /// The comparison is kept only to say what moved.
        /// </summary>
        private static List<string> ApplyRegionStyle(FilledRegionType regionType, (int R, int G, int B)? colour,
                                                      ElementId patternId, int weight)
        {
            var changed = new List<string>();

            if (colour != null)
            {
                var wanted = (Channel(colour.Value.R), Channel(colour.Value.G), Channel(colour.Value.B));
                try
                {
                    var current = Rgb(regionType.ForegroundPatternColor);
                    regionType.ForegroundPatternColor = ToColor(wanted);
                    if (!current.HasValue || current.Value != wanted) changed.Add("colour");
                }
                catch (Exception err)
                {
                    Swallowed(err);
                }
            }

            if (patternId != null)
            {
                try
                {
                    long was = Eid(regionType.ForegroundPatternId);
                    regionType.ForegroundPatternId = patternId;
                    if (was != Eid(patternId)) changed.Add("pattern");
                }
                catch (Exception err)
                {
                    Swallowed(err);
                }
            }

            try
            {
                int was = regionType.LineWeight;
                regionType.LineWeight = weight;
                if (was != weight) changed.Add("line weight");
            }
            catch (Exception err)
            {
                Swallowed(err);
            }

            try
            {
                if (regionType.IsMasking)
                {
                    regionType.IsMasking = false;
                    changed.Add("masking off");
                }
            }
            catch (Exception err)
            {
                Swallowed(err);
            }

            return changed;
        }

        /// <summary>Find or make LEG_CONT_&lt;name&gt; and bring it up to date.</summary>
        private (FilledRegionType Type, string Outcome) RegionTypeFor(LegendEntry entry, string prefix,
                                                                      ElementId fallbackPatternId, int weight)
        {
            string name = prefix + entry.Label;
            ElementId patternId = UsablePatternId(entry.PatternId, fallbackPatternId);

            FilledRegionType existing = FindFilledRegionType(name);
            if (existing != null)
            {
                var changed = ApplyRegionStyle(existing, entry.Colour, patternId, weight);
                return (existing, changed.Count > 0 ? "overwritten: " + string.Join(", ", changed)
                                                    : "overwritten, nothing differed");
            }

            var seed = new FilteredElementCollector(doc).OfClass(typeof(FilledRegionType)).FirstElement()
                as FilledRegionType;
            if (seed == null) return (null, "this project has no filled region type to copy");
            FilledRegionType created;
            try
            {
                created = (FilledRegionType)seed.Duplicate(name);
            }
            catch (Exception err)
            {
                return (null, "could not create the type: " + ErrText(err));
            }
            ApplyRegionStyle(created, entry.Colour, patternId, weight);
            return (created, "created");
        }

        private (Category Lines, Category Sub) FindLineSubcategory(string name)
        {
            Category lines;
            try
            {
                lines = doc.Settings.Categories.get_Item(BuiltInCategory.OST_Lines);
            }
            catch (Exception err)
            {
                Swallowed(err);
                return (null, null);
            }
            try
            {
                foreach (Category sub in lines.SubCategories)
                    if (sub.Name == name) return (lines, sub);
            }
            catch (Exception err)
            {
                Swallowed(err);
            }
            return (lines, null);
        }

        /// <summary>The dashed centre pattern, created or brought up to date (paper mm, not scaled).</summary>
        private ElementId CentrelinePatternId()
        {
            var segments = CentrelineSegments
                .Select(s => new LinePatternSegment(s.Dash ? LinePatternSegmentType.Dash : LinePatternSegmentType.Space,
                                                    ToInternal(s.Length)))
                .ToList();
            var pattern = new LinePattern(CentrelinePatternName);
            pattern.SetSegments(segments);

            var existing = new FilteredElementCollector(doc).OfClass(typeof(LinePatternElement))
                .Cast<LinePatternElement>().FirstOrDefault(e => Name(e) == CentrelinePatternName);
            if (existing != null)
            {
                try
                {
                    existing.SetLinePattern(pattern);
                }
                catch (Exception err)
                {
                    Swallowed(err); // keep whatever is already there
                }
                return existing.Id;
            }

            try
            {
                return LinePatternElement.Create(doc, pattern).Id;
            }
            catch (Exception err)
            {
                Swallowed(err);
                return null;
            }
        }

        /// <summary>Write colour and line weight onto a line subcategory, always.</summary>
        private static List<string> ApplyLineStyle(Category sub, (int R, int G, int B)? colour, int weight)
        {
            var changed = new List<string>();
            if (colour != null)
            {
                var wanted = (Channel(colour.Value.R), Channel(colour.Value.G), Channel(colour.Value.B));
                try
                {
                    var current = Rgb(sub.LineColor);
                    sub.LineColor = ToColor(wanted);
                    if (!current.HasValue || current.Value != wanted) changed.Add("colour");
                }
                catch (Exception err)
                {
                    Swallowed(err);
                }
            }

            try
            {
                int? was = sub.GetLineWeight(GraphicsStyleType.Projection);
                sub.SetLineWeight(weight, GraphicsStyleType.Projection);
                if (was != weight) changed.Add("line weight");
            }
            catch (Exception err)
            {
                Swallowed(err);
            }
            return changed;
        }

        /// <summary>One grey line style, shared by every swatch that wants a centreline.</summary>
        private GraphicsStyle CentrelineStyle(int weight)
        {
            var (lines, sub) = FindLineSubcategory(CentrelineName);
            if (lines == null) return null;
            if (sub == null)
            {
                try
                {
                    sub = doc.Settings.Categories.NewSubcategory(lines, CentrelineName);
                }
                catch (Exception err)
                {
                    Swallowed(err);
                    return null;
                }
            }
            ApplyLineStyle(sub, CentrelineRgb, weight);
            ElementId patternId = CentrelinePatternId();
            if (patternId != null)
            {
                try
                {
                    sub.SetLinePatternId(patternId, GraphicsStyleType.Projection);
                }
                catch (Exception err)
                {
                    Swallowed(err);
                }
            }
            try
            {
                return sub.GetGraphicsStyle(GraphicsStyleType.Projection);
            }
            catch (Exception err)
            {
                Swallowed(err);
                return null;
            }
        }

        /// <summary>Find or make a line style carrying the system's own colour; overwritten if it exists.</summary>
        private (GraphicsStyle Style, string Outcome) LineStyleFor(LegendEntry entry, string prefix, int weight)
        {
            string name = SafeStyleName(prefix + (string.IsNullOrEmpty(entry.Key) ? entry.Label : entry.Key));
            var (lines, sub) = FindLineSubcategory(name);
            if (lines == null) return (null, "the Lines category is not available");

            bool created = false;
            if (sub == null)
            {
                try
                {
                    sub = doc.Settings.Categories.NewSubcategory(lines, name);
                    created = true;
                }
                catch (Exception err)
                {
                    return (null, "could not create the line style: " + ErrText(err));
                }
            }

            var changed = ApplyLineStyle(sub, entry.Colour, weight);

            GraphicsStyle style = null;
            try
            {
                style = sub.GetGraphicsStyle(GraphicsStyleType.Projection);
            }
            catch (Exception err)
            {
                Swallowed(err);
            }
            if (style == null) return (null, "the line style has no projection graphics style");

            if (created) return (style, "created");
            if (changed.Count > 0) return (style, "overwritten: " + string.Join(", ", changed));
            return (style, "overwritten, nothing differed");
        }

        private void DetailLine(View view, GraphicsStyle style, XYZ a, XYZ b)
        {
            DetailCurve curve = doc.Create.NewDetailCurve(view, Line.CreateBound(a, b));
            if (style == null) return;
            try
            {
                curve.LineStyle = style;
            }
            catch (Exception err)
            {
                Swallowed(err);
            }
        }

        /// <summary>Four detail lines, so the swatch is an outline with no fill.</summary>
        private void DrawOutlineSwatch(View view, GraphicsStyle style, double x0, double y0, double x1, double y1)
        {
            var corners = new[] { new XYZ(x0, y0, 0), new XYZ(x1, y0, 0), new XYZ(x1, y1, 0), new XYZ(x0, y1, 0) };
            for (int i = 0; i < 4; i++) DetailLine(view, style, corners[i], corners[(i + 1) % 4]);
        }

        /// <summary>The grey line through the middle, running past both ends.</summary>
        private void DrawCentreline(View view, GraphicsStyle style, double x0, double x1, double y, double overhang)
        {
            DetailLine(view, style, new XYZ(x0 - overhang, y, 0), new XYZ(x1 + overhang, y, 0));
        }

        private static IList<CurveLoop> RectangleLoop(double x0, double y0, double x1, double y1)
        {
            var points = new[] { new XYZ(x0, y0, 0), new XYZ(x1, y0, 0), new XYZ(x1, y1, 0), new XYZ(x0, y1, 0) };
            var loop = new CurveLoop();
            for (int i = 0; i < 4; i++) loop.Append(Line.CreateBound(points[i], points[(i + 1) % 4]));
            return new List<CurveLoop> { loop };
        }

        private void PlaceHeading(View view, string text, double x, double y, ElementId typeId)
        {
            var options = new TextNoteOptions(typeId) { HorizontalAlignment = HorizontalTextAlignment.Left };
            TextNote note = TextNote.Create(doc, view.Id, new XYZ(x, y, 0.0), text, options);
            // The house heading is underlined - cosmetic, so a failure loses only the underline.
            try
            {
                FormattedText formatted = note.GetFormattedText();
                formatted.SetUnderlineStatus(true);
                note.SetFormattedText(formatted);
            }
            catch (Exception err)
            {
                Swallowed(err);
            }
        }

        /// <summary>Draw the swatches, the labels and a header per group.</summary>
        private (int Placed, List<(string, string)> Skipped, List<string> Notes) BuildSystemLegend(
            View view, SystemOptions opts)
        {
            double width = ToInternal(opts.SwatchW);
            double height = ToInternal(opts.SwatchH);
            double pitch = ToInternal(opts.RowPitch);
            double gap = ToInternal(opts.TextGap);
            double headGap = ToInternal(opts.HeadingGap);

            bool outline = opts.Style == "outline";
            double overhang = height * CentrelineOverhang;

            int weight = ClampWeight(opts.LineWeight);
            ElementId fallbackPattern = outline ? null : SolidFillPatternId();
            GraphicsStyle centreStyle = opts.Centreline ? CentrelineStyle(weight) : null;
            if (opts.Centreline && centreStyle == null)
                opts.Notes.Add("the grey centreline style could not be created - swatches are drawn without it");

            int placed = 0;
            var skipped = new List<(string, string)>();
            var notes = new List<string>(opts.Notes);
            double cursor = 0.0; // runs downward as the legend is built

            foreach (var (header, group) in opts.Groups)
            {
                var drawn = new List<(LegendEntry Entry, GraphicsStyle Style, FilledRegionType Region)>();
                foreach (var entry in group)
                {
                    GraphicsStyle style = null;
                    FilledRegionType regionType = null;
                    string outcome;
                    if (outline)
                    {
                        (style, outcome) = LineStyleFor(entry, opts.RegionPrefix, weight);
                        if (style == null)
                        {
                            skipped.Add((entry.Label, outcome));
                            continue;
                        }
                    }
                    else
                    {
                        (regionType, outcome) = RegionTypeFor(entry, opts.RegionPrefix, fallbackPattern, weight);
                        if (regionType == null)
                        {
                            skipped.Add((entry.Label, outcome));
                            continue;
                        }
                    }
                    notes.Add(opts.RegionPrefix + (string.IsNullOrEmpty(entry.Key) ? entry.Label : entry.Key)
                              + " - " + outcome);
                    drawn.Add((entry, style, regionType));
                }

                if (drawn.Count == 0) continue;

                // the header sits above the first swatch of its own group
                PlaceHeading(view, header, 0.0, cursor, opts.HeadTypeId);
                cursor -= headGap;

                for (int index = 0; index < drawn.Count; index++)
                {
                    var (entry, style, regionType) = drawn[index];
                    double top = cursor - pitch * index;
                    double middle = top - height / 2.0;
                    try
                    {
                        if (outline)
                        {
                            DrawOutlineSwatch(view, style, 0.0, top - height, width, top);
                            if (centreStyle != null) DrawCentreline(view, centreStyle, 0.0, width, middle, overhang);
                        }
                        else
                        {
                            FilledRegion.Create(doc, regionType.Id, view.Id, RectangleLoop(0.0, top - height, width, top));
                        }
                    }
                    catch (Exception err)
                    {
                        skipped.Add((entry.Label, ErrText(err)));
                        continue;
                    }

                    string label = opts.Upper ? entry.Label.ToUpperInvariant() : entry.Label;
                    TextNote.Create(doc, view.Id, new XYZ(width + gap, middle, 0.0), label, MiddleLeft(opts.TextTypeId));
                    placed++;
                }

                cursor -= pitch * drawn.Count;
                cursor -= headGap; // breathing room before the next header
            }

            return (placed, skipped, notes);
        }

        // -----------------------------------------------------------------
        // Entry points
        // -----------------------------------------------------------------
        /// <summary>Build the family legends. One transaction per legend inside a group.</summary>
        public List<(string Name, View View, int Count, List<(string Label, string Reason)> Skipped)> RunBatch(
            List<CategoryInfo> infos, FamilyOptions opts, View seedView, Element seedComponent,
            HashSet<string> taken, ILegendProgress progress)
        {
            var results = new List<(string, View, int, List<(string, string)>)>();
            var jobs = opts.Combined && infos.Count > 1
                ? new List<(string Name, List<CategoryInfo> Members)> { (CombinedName, infos) }
                : infos.Select(i => (ViewPrefix + i.Name, new List<CategoryInfo> { i })).ToList();

            using (var group = new TransactionGroup(doc, "Create WIP legends"))
            {
                group.Start();
                try
                {
                    for (int index = 1; index <= jobs.Count; index++)
                    {
                        if (progress != null && progress.Cancelled) break;
                        var (name, members) = jobs[index - 1];
                        using (Transaction trans = Quiet(new Transaction(doc, name)))
                        {
                            trans.Start();
                            try
                            {
                                View view = MakeLegendView(seedView, name, taken, opts.Scale);
                                if (view == null) throw new InvalidOperationException("the seed legend cannot be duplicated");
                                var (count, skipped) = PopulateLegend(view, members, seedView, seedComponent, opts);
                                trans.Commit();
                                results.Add((name, view, count, skipped));
                            }
                            catch (Exception err)
                            {
                                if (trans.HasStarted() && !trans.HasEnded()) trans.RollBack();
                                results.Add((name, null, 0, new List<(string, string)> { ("-", ErrText(err)) }));
                            }
                        }
                        progress?.Update(index, jobs.Count);
                    }
                    group.Assimilate();
                }
                catch (Exception)
                {
                    if (group.HasStarted() && !group.HasEnded()) group.RollBack();
                    throw;
                }
            }
            return results;
        }

        /// <summary>Build the one system colour legend. Its own transaction.</summary>
        public (View View, int Placed, List<(string Label, string Reason)> Skipped, List<string> Notes) RunSystem(
            SystemOptions opts, View seedView, HashSet<string> taken)
        {
            using (Transaction trans = Quiet(new Transaction(doc, "Create system colour legend")))
            {
                trans.Start();
                try
                {
                    View view = MakeLegendView(seedView, opts.ViewName, taken, opts.Scale);
                    if (view == null) throw new InvalidOperationException("the seed legend cannot be duplicated");
                    var (placed, skipped, notes) = BuildSystemLegend(view, opts);
                    trans.Commit();
                    return (view, placed, skipped, notes);
                }
                catch (Exception err)
                {
                    if (trans.HasStarted() && !trans.HasEnded()) trans.RollBack();
                    return (null, 0, new List<(string, string)> { ("-", ErrText(err)) }, new List<string>());
                }
            }
        }

        /// <summary>
        /// Make the new legend the active view, and prove it took. Called with
        /// every transaction closed, and read back afterwards.
        /// </summary>
        public bool OpenView(View view)
        {
            if (view == null) return false;
            UIDocument uidoc = uiapp.ActiveUIDocument;
            if (uidoc == null) return false;

            for (int attempt = 0; attempt < 2; attempt++)
            {
                try
                {
                    if (attempt == 0) uidoc.ActiveView = view;
                    else uidoc.RequestViewChange(view); // queued - applies when the command returns
                }
                catch (Exception err)
                {
                    Swallowed(err);
                    continue;
                }
                try
                {
                    if (Eid(uidoc.ActiveView.Id) == Eid(view.Id))
                    {
                        try
                        {
                            uidoc.RefreshActiveView();
                        }
                        catch (Exception err)
                        {
                            Swallowed(err);
                        }
                        return true;
                    }
                }
                catch (Exception err)
                {
                    Swallowed(err);
                }
            }
            return false;
        }

        /// <summary>Make sure the Project Browser pane is open.</summary>
        private bool ShowProjectBrowser()
        {
            try
            {
                DockablePane pane = uiapp.GetDockablePane(DockablePanes.BuiltInDockablePanes.ProjectBrowser);
                if (!pane.IsShown()) pane.Show();
                return pane.IsShown();
            }
            catch (Exception err)
            {
                Log("   browser pane: " + ErrText(err));
                return false;
            }
        }

        /// <summary>Select the view as an element, and read the selection back.</summary>
        private bool SelectElement(View view)
        {
            try
            {
                UIDocument uidoc = uiapp.ActiveUIDocument;
                uidoc.Selection.SetElementIds(new List<ElementId> { view.Id });
                long wanted = Eid(view.Id);
                return uidoc.Selection.GetElementIds().Any(i => Eid(i) == wanted);
            }
            catch (Exception err)
            {
                Log("   select view: " + ErrText(err));
                return false;
            }
        }

        /// <summary>
        /// Find the legend in the Project Browser tree, scroll to it, select it.
        /// UI Automation, because the API has no Project Browser call. Returns
        /// whether the tree item reports itself selected afterwards.
        /// </summary>
        private static bool UiaSelect(IntPtr handle, string name, string legendsLabel)
        {
            AutomationElement root = AutomationElement.FromHandle(handle);
            if (root == null) return false;

            Condition TreeItem(string label) => new AndCondition(
                new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.TreeItem),
                new PropertyCondition(AutomationElement.NameProperty, label));

            AutomationElement scope = root;
            AutomationElement group = root.FindFirst(TreeScope.Descendants, TreeItem(legendsLabel));
            if (group != null)
            {
                // A collapsed node hides its children from UI Automation entirely.
                try
                {
                    var expand = (ExpandCollapsePattern)group.GetCurrentPattern(ExpandCollapsePattern.Pattern);
                    if (expand.Current.ExpandCollapseState != ExpandCollapseState.Expanded) expand.Expand();
                }
                catch (Exception err)
                {
                    Swallowed(err);
                }
                scope = group;
            }

            AutomationElement target = scope.FindFirst(TreeScope.Descendants, TreeItem(name));
            if (target == null && scope != root) target = root.FindFirst(TreeScope.Descendants, TreeItem(name));
            if (target == null) return false;

            try
            {
                ((ScrollItemPattern)target.GetCurrentPattern(ScrollItemPattern.Pattern)).ScrollIntoView();
            }
            catch (Exception err)
            {
                Swallowed(err);
            }
            var selector = (SelectionItemPattern)target.GetCurrentPattern(SelectionItemPattern.Pattern);
            selector.Select();
            return selector.Current.IsSelected;
        }

        public const double BrowserTimeoutS = 4.0;

        /// <summary>
        /// Run the UI Automation search off the UI thread while this thread keeps
        /// Revit's message loop turning; give up after a few seconds rather than
        /// risk a hang. True, false, or null when it timed out.
        /// </summary>
        private bool? SelectInBrowserTree(View view)
        {
            IntPtr handle;
            try
            {
                handle = uiapp.MainWindowHandle;
            }
            catch (Exception err)
            {
                Log("   browser tree: no main window - " + ErrText(err));
                return false;
            }

            Dispatcher dispatcher = Dispatcher.CurrentDispatcher;
            var frame = new DispatcherFrame();
            bool done = false, result = false;
            string error = null;
            string name = Name(view);

            void Stop() => frame.Continue = false;

            var worker = new Thread(() =>
            {
                try
                {
                    result = UiaSelect(handle, name, "Legends");
                }
                catch (Exception err)
                {
                    error = ErrText(err);
                }
                finally
                {
                    done = true;
                    try
                    {
                        dispatcher.BeginInvoke(DispatcherPriority.Normal, (Action)Stop);
                    }
                    catch (Exception err)
                    {
                        Swallowed(err);
                    }
                }
            })
            { IsBackground = true };
            worker.SetApartmentState(ApartmentState.MTA);

            var timer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(BrowserTimeoutS) };
            timer.Tick += (s, e) =>
            {
                timer.Stop();
                Stop();
            };

            worker.Start();
            timer.Start();
            try
            {
                Dispatcher.PushFrame(frame);
            }
            finally
            {
                timer.Stop();
            }

            if (error != null) Log("   browser tree: " + error);
            if (!done)
            {
                Log(string.Format(Inv, "   browser tree: gave up after {0}s", PyFloat(BrowserTimeoutS)));
                return null;
            }
            return result;
        }

        /// <summary>Take the user to a legend in the Project Browser - three steps, each checked and logged.</summary>
        public bool RevealInBrowser(View view)
        {
            if (view == null) return false;
            bool shown = ShowProjectBrowser();
            bool selected = SelectElement(view);
            bool? inTree = SelectInBrowserTree(view);
            Log(string.Format(Inv, "browser: pane shown {0}, view selected {1}, tree item selected {2}",
                              shown ? "True" : "False", selected ? "True" : "False",
                              inTree == null ? "None" : inTree.Value ? "True" : "False"));
            return inTree == true || selected;
        }
    }
}
