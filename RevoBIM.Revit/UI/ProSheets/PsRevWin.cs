using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Autodesk.Revit.UI;
using RevoBIM.Tools.ProSheets;

namespace RevoBIM.UI.ProSheets
{
    /// <summary>
    /// The Revision Manager window: a view of a PsRevisions.Staging. Port of ps_revwin.py.
    ///
    /// Opened from the Document Register's Revision Manager button (modal: it stages, and on Apply
    /// hands back a plan for the register to write through the external event, then closes), or on
    /// its own from the Revision Manager ribbon button (modeless, see RunStandalone).
    ///
    /// The grid is a DataTable like every other grid in the tool. Each cell's look comes from flags
    /// on its row rather than from anything set on a container: <c>c_&lt;field&gt;</c> is 1 when that
    /// field is staged to change (green), <c>live</c> is 0 when the row is staged to be deleted or
    /// merged (red, struck through). Rows are recycled as they scroll, so anything set on a container
    /// would wander.
    ///
    /// Split across PsRevWin.cs (this file: the module-level constants and helpers, the external
    /// event handler and RunStandalone), PsRevWin.Manager.cs (the window: building, columns, bands,
    /// filters) and PsRevWin.Manager.Edit.cs (the window: the table, editing, the side panel, apply).
    /// </summary>
    public static partial class PsRevWin
    {
        // ps_refs is not ported (nothing to reference in C#).

        public const string Presentation = "http://schemas.microsoft.com/winfx/2006/xaml/presentation";

        // The green + that adds a column, and the pencil on an extra column's heading.
        public const string PlusIcon =
            "<Path xmlns=\"{0}\" Width=\"14\" Height=\"14\" Stretch=\"Uniform\"" +
            " Fill=\"{{DynamicResource GreenBrush}}\"" +
            " Data=\"M 5,0 L 7,0 L 7,5 L 12,5 L 12,7 L 7,7 L 7,12 L 5,12 L 5,7 L 0,7" +
            " L 0,5 L 5,5 Z\"/>";
        public const string PencilIcon =
            "<Path xmlns=\"{0}\" Width=\"10\" Height=\"10\" Stretch=\"Uniform\"" +
            " Fill=\"{{DynamicResource MutedBrush}}\"" +
            " Data=\"M 8,0 L 11,3 L 3.5,10.5 L 0,11 L 0.5,7.5 Z\"/>";

        /// <summary>A column that fits itself to its heading and its widest value.</summary>
        public const int Auto = -1;

        // How narrow an auto column may get - the search box and its list button have to stay
        // usable - and how wide, so one long value cannot push the rest off the right of the window.
        public const int AutoMin = 78;
        public const int AutoMax = 300;

        /// <summary>
        /// (field, heading, width (Auto = fit the text, 0 = take the rest), kind). Sheet series is the
        /// one fixed width: its chips wrap to the column, and a column that fits itself to its content
        /// has no edge for them to wrap at, so it would grow into one long line instead.
        /// </summary>
        public static readonly List<(string Field, string Heading, int Width, string Kind)> Columns =
            new List<(string, string, int, string)>
            {
                ("seq", "Sequence", Auto, "read"),
                ("numbering", "Numbering", Auto, "RevNumberingChoices"),
                ("date", "Date", Auto, "text"),
                ("desc", "Description", 0, "text"),
                ("issued", "Issued", Auto, "check"),
                ("issued_to", "Issued to", Auto, "text"),
                ("issued_by", "Issued by", Auto, "text"),
                ("show", "Show", Auto, "RevShowChoices"),
                ("used", "Used on sheets", Auto, "used"),
                ("series", "Sheet series", 190, "series"),
                // 1.46.0: clouds drawn in views that are on no sheet - why a revision "on 0 sheets"
                // can still say it is in use.
                ("unplaced", "Clouds off sheets", Auto, "unplaced"),
            };

        /// <summary>How many views Find clouds on views opens before asking first.</summary>
        public const int OpenLimit = 12;

        // A cell's text: green and bold while its field is staged to change, red and struck through
        // while its row is staged to go.
        public const string TextStyle =
            "<TextBlock.Style><Style TargetType=\"TextBlock\">" +
            "<Setter Property=\"VerticalAlignment\" Value=\"Center\"/>" +
            "<Setter Property=\"Padding\" Value=\"3,1\"/>" +
            "<Style.Triggers>" +
            "<DataTrigger Binding=\"{{Binding c_{0}}}\" Value=\"1\">" +
            "<Setter Property=\"Foreground\" Value=\"{{DynamicResource GreenBrush}}\"/>" +
            "<Setter Property=\"FontWeight\" Value=\"Bold\"/>" +
            "<Setter Property=\"Background\" Value=\"{{DynamicResource GreenWashBrush}}\"/>" +
            "</DataTrigger>" +
            "<DataTrigger Binding=\"{{Binding live}}\" Value=\"0\">" +
            "<Setter Property=\"Foreground\" Value=\"{{DynamicResource RedBrush}}\"/>" +
            "<Setter Property=\"TextDecorations\" Value=\"Strikethrough\"/>" +
            "<Setter Property=\"Background\" Value=\"Transparent\"/>" +
            "</DataTrigger>" +
            "</Style.Triggers></Style></TextBlock.Style>";

        public const string ShowTemplate =
            "<DataTemplate xmlns=\"{0}\"><TextBlock Text=\"{{Binding {1}}}\"{2}>" +
            "{3}</TextBlock></DataTemplate>";

        // The editors take the keyboard as they open, so one click on a cell is enough to start
        // typing - as in Revit's own dialog.
        public const string TextEditTemplate =
            "<DataTemplate xmlns=\"{0}\" " +
            "xmlns:x=\"http://schemas.microsoft.com/winfx/2006/xaml\">" +
            "<Grid FocusManager.FocusedElement=\"{{Binding ElementName=Editor}}\">" +
            "<TextBox x:Name=\"Editor\" Text=\"{{Binding {1}, Mode=TwoWay}}\"" +
            " VerticalContentAlignment=\"Center\"/></Grid></DataTemplate>";

        public const string ComboEditTemplate =
            "<DataTemplate xmlns=\"{0}\" " +
            "xmlns:x=\"http://schemas.microsoft.com/winfx/2006/xaml\">" +
            "<Grid FocusManager.FocusedElement=\"{{Binding ElementName=Editor}}\">" +
            "<ComboBox x:Name=\"Editor\" ItemsSource=\"{{DynamicResource {2}}}\"" +
            " SelectedItem=\"{{Binding {1}, Mode=TwoWay, " +
            "UpdateSourceTrigger=PropertyChanged}}\"/></Grid></DataTemplate>";

        public const string CheckTemplate =
            "<DataTemplate xmlns=\"{0}\">" +
            "<Border Padding=\"2,1\" CornerRadius=\"2\"><Border.Style>" +
            "<Style TargetType=\"Border\">" +
            "<Setter Property=\"Background\" Value=\"Transparent\"/>" +
            "<Style.Triggers>" +
            "<DataTrigger Binding=\"{{Binding c_{1}}}\" Value=\"1\">" +
            "<Setter Property=\"Background\" Value=\"{{DynamicResource GreenWashBrush}}\"/>" +
            "<Setter Property=\"BorderBrush\" Value=\"{{DynamicResource GreenBrush}}\"/>" +
            "<Setter Property=\"BorderThickness\" Value=\"1\"/>" +
            "</DataTrigger>" +
            // A row staged to go cannot be issued; the Border's IsEnabled carries down to the tick
            // inside it.
            "<DataTrigger Binding=\"{{Binding live}}\" Value=\"0\">" +
            "<Setter Property=\"IsEnabled\" Value=\"False\"/>" +
            "<Setter Property=\"Opacity\" Value=\"0.5\"/>" +
            "</DataTrigger></Style.Triggers></Style></Border.Style>" +
            "<CheckBox HorizontalAlignment=\"Center\"" +
            " Style=\"{{DynamicResource GridCheckBox}}\"" +
            " IsChecked=\"{{Binding {1}, Mode=TwoWay, " +
            "UpdateSourceTrigger=PropertyChanged}}\"/>" +
            "</Border></DataTemplate>";

        // The Sheet series cell. A button with no chrome of its own, ticked into the row's
        // series_open: closed it shows the first series and "+2", open it shows every series, one
        // coloured chip each, wrapping to the column's width. Rows open expanded unless the user has
        // collapsed them (the Collapse series button, kept as rev_series_open). All of it is in the
        // template - rows are recycled as they scroll, and nothing set on a container from code
        // would stay with its row.
        public const string SeriesTemplate =
            "<DataTemplate xmlns=\"{0}\">" +
            "<ToggleButton Cursor=\"Hand\" Focusable=\"False\"" +
            " ToolTip=\"Click to fold or unfold this revision's sheet series\"" +
            " IsChecked=\"{{Binding series_open, Mode=TwoWay, " +
            "UpdateSourceTrigger=PropertyChanged}}\">" +
            "<ToggleButton.Template><ControlTemplate TargetType=\"ToggleButton\">" +
            "<Border Background=\"Transparent\" Padding=\"0,2\">" +
            "<ContentPresenter/></Border></ControlTemplate>" +
            "</ToggleButton.Template>" +
            // A DockPanel rather than a horizontal StackPanel: the chips get the column's width, so
            // the WrapPanel has an edge to wrap at.
            "<DockPanel LastChildFill=\"True\">" +
            "<TextBlock DockPanel.Dock=\"Right\" Text=\"{{Binding series_more}}\"" +
            " Margin=\"2,0,0,0\" VerticalAlignment=\"Center\" FontWeight=\"Bold\">" +
            "<TextBlock.Style><Style TargetType=\"TextBlock\">" +
            "<Setter Property=\"Foreground\" Value=\"{{DynamicResource BlueBrush}}\"/>" +
            "<Style.Triggers>" +
            "<DataTrigger Binding=\"{{Binding series_open}}\" Value=\"True\">" +
            "<Setter Property=\"Visibility\" Value=\"Collapsed\"/>" +
            "</DataTrigger></Style.Triggers></Style></TextBlock.Style></TextBlock>" +
            "<ItemsControl>" +
            "<ItemsControl.Style><Style TargetType=\"ItemsControl\">" +
            "<Setter Property=\"ItemsSource\" Value=\"{{Binding series_head}}\"/>" +
            "<Style.Triggers>" +
            "<DataTrigger Binding=\"{{Binding series_open}}\" Value=\"True\">" +
            "<Setter Property=\"ItemsSource\" Value=\"{{Binding series_items}}\"/>" +
            "</DataTrigger></Style.Triggers></Style></ItemsControl.Style>" +
            "<ItemsControl.ItemsPanel><ItemsPanelTemplate>" +
            "<WrapPanel Orientation=\"Horizontal\"/>" +
            "</ItemsPanelTemplate></ItemsControl.ItemsPanel>" +
            "<ItemsControl.ItemTemplate><DataTemplate>" +
            "<Border Background=\"{{Binding Item2}}\" BorderBrush=\"{{Binding Item3}}\"" +
            " BorderThickness=\"1\" CornerRadius=\"3\" Padding=\"6,1\" Margin=\"0,1,4,1\">" +
            "<TextBlock Text=\"{{Binding Item1}}\" FontSize=\"11\"" +
            " Foreground=\"{{DynamicResource TextBrush}}\"/></Border>" +
            "</DataTemplate></ItemsControl.ItemTemplate></ItemsControl>" +
            "</DockPanel></ToggleButton></DataTemplate>";

        public const string UsedTemplate =
            "<DataTemplate xmlns=\"{0}\"><TextBlock Text=\"{{Binding used}}\"" +
            " ToolTip=\"{{Binding sheets_tip}}\" FontWeight=\"Bold\"" +
            " VerticalAlignment=\"Center\" Padding=\"3,1\">" +
            "<TextBlock.Style><Style TargetType=\"TextBlock\">" +
            "<Setter Property=\"Foreground\" Value=\"{{DynamicResource BlueBrush}}\"/>" +
            "<Style.Triggers>" +
            "<DataTrigger Binding=\"{{Binding used}}\" Value=\"0\">" +
            "<Setter Property=\"Foreground\" Value=\"{{DynamicResource RedBrush}}\"/>" +
            "</DataTrigger>" +
            "<DataTrigger Binding=\"{{Binding live}}\" Value=\"0\">" +
            "<Setter Property=\"TextDecorations\" Value=\"Strikethrough\"/>" +
            "</DataTrigger>" +
            "</Style.Triggers></Style></TextBlock.Style></TextBlock></DataTemplate>";

        // Clouds off sheets: orange and bold where there are some, blank where there are none; the
        // views they are in, on hover.
        public const string UnplacedTemplate =
            "<DataTemplate xmlns=\"{0}\"><TextBlock Text=\"{{Binding unplaced}}\"" +
            " ToolTip=\"{{Binding unplaced_tip}}\" FontWeight=\"Bold\"" +
            " VerticalAlignment=\"Center\" Padding=\"3,1\">" +
            "<TextBlock.Style><Style TargetType=\"TextBlock\">" +
            "<Setter Property=\"Foreground\" Value=\"{{DynamicResource OrangeBrush}}\"/>" +
            "<Style.Triggers>" +
            "<DataTrigger Binding=\"{{Binding unplaced}}\" Value=\"0\">" +
            "<Setter Property=\"Foreground\" Value=\"{{DynamicResource MutedBrush}}\"/>" +
            "<Setter Property=\"FontWeight\" Value=\"Normal\"/>" +
            "</DataTrigger>" +
            "</Style.Triggers></Style></TextBlock.Style></TextBlock></DataTemplate>";

        /// <summary>A column new since the order was saved goes beside the one it follows, not at
        /// the far end.</summary>
        public static List<string> PlaceAfter(IList<string> fields, IList<string> saved, string field, string after)
        {
            if (saved == null || saved.Count == 0 || saved.Contains(field) || !fields.Contains(field) ||
                !fields.Contains(after))
                return new List<string>(fields);
            var output = fields.Where(one => one != field).ToList();
            output.Insert(output.IndexOf(after) + 1, field);
            return output;
        }

        /// <summary>(views, lines) for Find clouds on views: how many views hold the revisions'
        /// clouds, and one line per revision on where.</summary>
        public static (Dictionary<string, List<string>> Views, List<string> Lines) ViewsReport(
            IEnumerable<PsRevisions.Entry> entries)
        {
            var list = entries.ToList();
            var views = PsRevisions.ViewsToOpen(list);
            var lines = new List<string>();
            foreach (var entry in list)
            {
                int count = entry.CloudViews != null ? entry.CloudViews.Count : 0;
                if (count != 0)
                {
                    string desc = Str(entry.Fields != null && entry.Fields.TryGetValue("desc", out var d) ? d : null);
                    lines.Add(string.Format(Inv, "{0}: {1} cloud{2} in {3} view{4}{5}",
                        desc.Length > 0 ? desc : entry.Key, entry.Clouds,
                        entry.Clouds == 1 ? "" : "s", count,
                        count == 1 ? "" : "s",
                        entry.OffViews != null && entry.OffViews.Count > 0
                            ? string.Format(Inv, ", {0} of them on no sheet", entry.OffViews.Count)
                            : ""));
                }
            }
            return (views, lines);
        }

        // A revision added here and not yet applied: the whole row washed green, edged green, "ready
        // to go on Apply". Parsed, then BasedOn the theme's GridRow in code - a StaticResource cannot
        // resolve outside the window.
        public const string FreshRowStyle =
            "<Style xmlns=\"{0}\" TargetType=\"DataGridRow\">" +
            "<Style.Triggers>" +
            "<DataTrigger Binding=\"{{Binding fresh}}\" Value=\"1\">" +
            "<Setter Property=\"Background\" Value=\"{{DynamicResource GreenWashBrush}}\"/>" +
            "<Setter Property=\"BorderBrush\" Value=\"{{DynamicResource GreenBrush}}\"/>" +
            "<Setter Property=\"BorderThickness\" Value=\"0,1,0,1\"/>" +
            "</DataTrigger>" +
            "</Style.Triggers></Style>";

        /// <summary>How wide each kind of extra column starts: fitted to its text, like the
        /// built-in ones.</summary>
        public static readonly Dictionary<string, int> CustomWidths = new Dictionary<string, int>(StringComparer.Ordinal)
        {
            { "text", Auto }, { "yesno", Auto }, { "number", Auto }, { "date", Auto }, { "choice", Auto },
        };

        /// <summary>Whether a column of this width sizes itself to its text.</summary>
        public static bool Fits(int width)
        {
            return width == Auto;
        }

        /// <summary>
        /// Whether an edit to <paramref name="field"/> goes to every selected revision. Revit's own
        /// fields and the manager's columns do - except the Date, as the issue date of one revision
        /// is never right for several. Read-only columns (Sequence, Used on sheets, Sheet series)
        /// take no edit at all.
        /// </summary>
        public static bool Together(string field, string kind = null)
        {
            if (field.StartsWith("x_", StringComparison.Ordinal))
                return true;
            return PsRevisions.Fields.Contains(field) && !PsRevisions.AllAtOnceRefused.Contains(field);
        }

        /// <summary>
        /// Which revision the list should go to for a selection in Revit. The first selected cloud's
        /// revision that the list actually holds, or null - and null when the list is already sitting
        /// on exactly that row, so a selection that has not moved never yanks the list about.
        /// </summary>
        public static string JumpTarget(IEnumerable<string> keys, IEnumerable<string> order, IEnumerable<string> current)
        {
            var orderList = (order ?? Enumerable.Empty<string>()).ToList();
            foreach (var key in keys ?? Enumerable.Empty<string>())
            {
                if (orderList.Contains(key))
                {
                    var now = (current ?? Enumerable.Empty<string>()).ToList();
                    return now.Count == 1 && now[0] == key ? null : key;
                }
            }
            return null;
        }

        /// <summary><paramref name="fields"/> in the order last saved: the saved ones first, as
        /// dragged, then any not in it (a column added since) where they were.</summary>
        public static List<string> ColumnOrder(IList<string> fields, IEnumerable<string> saved)
        {
            var known = saved.Where(field => fields.Contains(field)).ToList();
            var seen = new HashSet<string>(known, StringComparer.Ordinal);
            return known.Concat(fields.Where(field => !seen.Contains(field))).ToList();
        }

        /// <summary>
        /// The fields with each group's members side by side, where the first of them sits - a
        /// dragged order can split a group, and the band over a group only reads as one if its
        /// columns are together. <paramref name="groupOf"/> gives a field's group, "" for none.
        /// </summary>
        public static List<string> KeepGroups(IList<string> fields, Func<string, string> groupOf)
        {
            var output = new List<string>();
            var placed = new HashSet<string>(StringComparer.Ordinal);
            foreach (var field in fields)
            {
                string group = groupOf(field);
                if (string.IsNullOrEmpty(group))
                {
                    // Only grouped columns are moved. A column listed twice stays listed twice, so
                    // the bench still sees that fault.
                    output.Add(field);
                    continue;
                }
                if (placed.Contains(field))
                    continue;
                foreach (var member in fields)
                {
                    if (!placed.Contains(member) && groupOf(member) == group)
                    {
                        output.Add(member);
                        placed.Add(member);
                    }
                }
            }
            return output;
        }

        // The Description column's floor, and its ceiling when the window opens; and the room a grid
        // takes beyond its columns - the row headers and the vertical scroll bar.
        public const int DescriptionMin = 240;
        public const int DescriptionMax = 480;
        public const int GridSlack = 24;

        /// <summary>The width Description opens at: its longest text, kept between DescriptionMin
        /// and DescriptionMax.</summary>
        public static int DescriptionWidth(IEnumerable<string> texts, int perChar = 7, int padding = 30)
        {
            int longest = 0;
            foreach (var text in texts ?? Enumerable.Empty<string>())
                longest = Math.Max(longest, (text ?? "").Length);
            return Math.Max(DescriptionMin, Math.Min(DescriptionMax, longest * perChar + padding));
        }

        /// <summary>How wide the window wants to be: every sized column, Description, and the
        /// window's own chrome beside the grid.</summary>
        public static double NeededWidth(double @fixed, double description, double extra)
        {
            return @fixed + description + extra;
        }

        // The coloured strip over the headings: one band per kind of column, merged across every
        // column of that kind that sits together, its name centred.
        public const string Standard = "standard";
        public const string Custom = "custom";

        /// <summary>(key, name, brush, whether its + adds a column of that kind).</summary>
        public static readonly List<(string Key, string Name, string Brush, bool Adds)> Bands =
            new List<(string, string, string, bool)>
            {
                (Standard, "Standard", "SortL4", false),
                (Custom, "Custom", "GreenBrush", true),
                (PsRevData.Status, "Issue Status", "SortL5", false),
                (PsRevData.IssuedTo, "Issued To", "BlueBrush", true),
                (PsRevData.Method, "Issued Method", "OrangeBrush", true),
            };

        public static readonly Dictionary<string, (string Name, string Brush, bool Adds)> BandInfo =
            Bands.ToDictionary(b => b.Key, b => (b.Name, b.Brush, b.Adds), StringComparer.Ordinal);

        /// <summary>
        /// [(band, left, width)] - one run per stretch of side-by-side columns of one band.
        /// <paramref name="columns"/> is [(field, width)] in the order shown; a column with no band
        /// (the + at the end) leaves a gap.
        /// </summary>
        public static List<(string Band, double Left, double Width)> BandRuns(
            IEnumerable<(string Field, double Width)> columns, Func<string, string> bandOf)
        {
            var runs = new List<(string Band, double Left, double Width)>();
            double x = 0.0;
            foreach (var (field, width) in columns)
            {
                string band = bandOf(field);
                if (!string.IsNullOrEmpty(band) && runs.Count > 0 && runs[runs.Count - 1].Band == band &&
                    Math.Abs(runs[runs.Count - 1].Left + runs[runs.Count - 1].Width - x) < 0.5)
                {
                    var last = runs[runs.Count - 1];
                    runs[runs.Count - 1] = (band, last.Left, last.Width + width);
                }
                else if (!string.IsNullOrEmpty(band))
                {
                    runs.Add((band, x, width));
                }
                x += width;
            }
            return runs;
        }

        // ------------------------------------------------------------------ python-ish helpers
        internal static readonly CultureInfo Inv = CultureInfo.InvariantCulture;

        /// <summary>u'{0}'.format(value): null and DBNull as "".</summary>
        internal static string Str(object value)
        {
            if (value == null || value is DBNull) return "";
            if (value is string s) return s;
            if (value is bool b) return b ? "True" : "False";
            if (value is double d) return d.ToString("R", Inv);
            if (value is IFormattable f) return f.ToString(null, Inv);
            return value.ToString();
        }

        /// <summary>A staged sequence as Python formats it: None for none.</summary>
        internal static string Seq(int? sequence)
        {
            return sequence.HasValue ? sequence.Value.ToString(Inv) : "None";
        }

        // ==========================================================================
        // on its own, from the Revision Manager ribbon button
        // ==========================================================================

        /// <summary>Runs one queued revision job on Revit's API thread.</summary>
        public class RevisionHandler : IExternalEventHandler
        {
            public Action<UIApplication> Work;

            public void Execute(UIApplication uiapp)
            {
                var work = Work;
                Work = null;
                if (work == null)
                    return;
                try
                {
                    work(uiapp);
                }
                catch (Exception)
                {
                }
            }

            public string GetName()
            {
                return "RevoBIM Revision Manager";
            }
        }

        // Kept at class level for the reason the main window keeps its own: the live window - and the
        // Idling handler subscribed to Revit - must outlive the command that opened it (pyRevit's
        // persistent engine would otherwise collect them; in C# these simply keep them reachable).
        public static RevisionManager Manager;
        public static RevisionHandler Handler;
        public static ExternalEvent Event;

        /// <summary>
        /// The manager on its own, from its ribbon button, <b>modeless</b>: Revit stays fully usable
        /// while it is open. Modeless changes three things, and all three are the usual way a
        /// modeless Revit tool is wrong:
        /// - Apply cannot write where it stands. A modeless window is in no API context, so the plan
        ///   goes out through an ExternalEvent and the window refreshes itself when the write comes
        ///   back. The same rule as the main window's exports.
        /// - The window has to outlive the command. The static references above keep it alive.
        /// - Reading the model needs a valid context too. Following the selection is done in Revit's
        ///   Idling event, which is raised on Revit's main thread inside one.
        /// Must be called from the command (an API context): ExternalEvent.Create is made here.
        /// </summary>
        public static RevisionManager RunStandalone(UIApplication uiapp)
        {
            if (Manager != null)
            {
                // Already open: bring it forward rather than opening a second one over the same
                // model with its own staged changes.
                try
                {
                    Manager.Window.Activate();
                    return Manager;
                }
                catch (Exception)
                {
                    Manager = null;
                }
            }
            if (Handler == null)
                Handler = new RevisionHandler();
            if (Event == null)
                Event = ExternalEvent.Create(Handler);

            var doc = uiapp.ActiveUIDocument.Document;
            PsConfig.Settings settings = null;
            string themeName;
            try
            {
                settings = new PsConfig.Settings();
                themeName = PsTheme.Resolve(PsTheme.Mode(settings.Text("theme_mode")));
            }
            catch (Exception)
            {
                themeName = PsTheme.Resolve("follow");
            }
            string seriesParam = "", statusParam = "";
            bool reopen = true;
            if (settings != null)
            {
                try
                {
                    seriesParam = settings.Text("param_series", "");
                    statusParam = settings.Text("reg_status_param", "");
                    // Modeless, "reopen after Apply" means "stay open, refreshed"; off, the window
                    // closes once the change is in.
                    reopen = settings.Flag("rev_reopen", true);
                }
                catch (Exception)
                {
                }
            }

            Func<IEnumerable<PsRevData.BoundParameter>> reader = () => PsRevData.BoundParameters(doc);

            // Read here, in the command's own API context: the revision of any cloud selected before
            // opening, and the sheet open in Revit.
            var uidoc = uiapp.ActiveUIDocument;
            var focus = PsRevisions.SelectedRevisionKeys(uidoc);
            string currentSheet;
            try
            {
                currentSheet = PsRevisions.SheetNumberOf(uidoc.ActiveView);
            }
            catch (Exception)
            {
                currentSheet = null;
            }
            var manager = new RevisionManager(PsRevisions.Read(doc, seriesParam, statusParam),
                                              themeName, null, reader, "",
                                              uiapp.MainWindowHandle, settings,
                                              modeless: true, focus: focus,
                                              currentSheet: currentSheet);
            // Idling should not take the starting view or selection as a change.
            manager.Token = PsRevisions.SelectionToken(uidoc);
            try
            {
                manager.ViewToken = PsModel.EidValue(uidoc.ActiveView.Id).ToString(Inv);
            }
            catch (Exception)
            {
            }

            // Apply, from the window's thread. Nothing here touches Revit.
            void ApplyPlan(PsRevisions.Plan plan)
            {
                // On Revit's API thread, inside its context.
                void Job(UIApplication eventUiapp)
                {
                    var (done, errors) = PsRevisions.Write(doc, plan);
                    string status = string.Format(Inv, "{0} change{1} applied to the model.",
                                                  done, done == 1 ? "" : "s");
                    if (errors != null && errors.Count > 0)
                        status += string.Format(Inv, " {0} could not be.", errors.Count);
                    string post = manager.PostCommand;
                    PsRevisions.Staging fresh = null;
                    if (reopen && string.IsNullOrEmpty(post))
                    {
                        // Read it back here, still inside the context.
                        try
                        {
                            fresh = PsRevisions.Read(doc, seriesParam, statusParam);
                        }
                        catch (Exception)
                        {
                            fresh = null;
                        }
                    }

                    void Back()
                    {
                        if (!string.IsNullOrEmpty(post) || !reopen)
                            manager.CloseNow();
                        else if (fresh != null)
                            manager.Reload(fresh, status);
                        else
                            manager.Say(status + " Reopen the manager to see the model as it now is.");
                        if (errors != null && errors.Count > 0)
                        {
                            new PsUi.Prompt(
                                title: "Revision Manager",
                                headline: string.Format(Inv, "{0} change{1} Revit would not make.",
                                                        errors.Count, errors.Count == 1 ? "" : "s"),
                                message: "The rest were applied.",
                                detail: string.Join("\n", errors), primary: "Close",
                                themeName: manager.ThemeName).Show();
                        }
                    }

                    manager.OnUi(Back);
                    if (!string.IsNullOrEmpty(post))
                    {
                        // The window has gone; now Revit's own dialog.
                        PostCommand(eventUiapp, post);
                    }
                }

                Handler.Work = Job;
                try
                {
                    Event.Raise();
                }
                catch (Exception err)
                {
                    manager.Say(string.Format("Revit would not take the job: {0}", err.Message));
                }
            }

            manager.OnApply = ApplyPlan;

            // Find clouds on views, from the window's thread: open each view with its clouds
            // isolated - on Revit's thread, through the event.
            void FindClouds(Dictionary<string, List<string>> views)
            {
                void Job(UIApplication eventUiapp)
                {
                    (int Opened, int Isolated, List<string> Errors) result;
                    try
                    {
                        result = PsRevisions.ShowClouds(eventUiapp.ActiveUIDocument, views);
                    }
                    catch (Exception err)
                    {
                        result = (0, 0, new List<string> { err.Message });
                    }
                    manager.OnUi(() => manager.Say(
                        PsRevisions.CloudsReport(result.Opened, result.Isolated, result.Errors)));
                }

                Handler.Work = Job;
                try
                {
                    Event.Raise();
                }
                catch (Exception err)
                {
                    manager.Say(string.Format("Revit would not take the job: {0}", err.Message));
                }
            }

            manager.OnFind = FindClouds;

            void Forget(object sender, EventArgs args)
            {
                Manager = null;
                try
                {
                    if (settings != null)
                    {
                        settings.Set("theme_mode", manager.ThemeName);
                        settings.Save();
                    }
                }
                catch (Exception)
                {
                }
            }

            try
            {
                manager.Window.Closed += Forget;
            }
            catch (Exception)
            {
            }

            Manager = manager;
            manager.WatchSelection(uiapp);
            manager.ShowModeless();
            return manager;
        }

        /// <summary>Ask Revit to run one of its own commands - Project Parameters - as soon as the
        /// tool hands control back. <paramref name="name"/> is a PostableCommand member name.</summary>
        public static bool PostCommand(UIApplication uiapp, string name)
        {
            try
            {
                var command = (PostableCommand)Enum.Parse(typeof(PostableCommand), name);
                uiapp.PostCommand(RevitCommandId.LookupPostableCommandId(command));
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }
    }
}
