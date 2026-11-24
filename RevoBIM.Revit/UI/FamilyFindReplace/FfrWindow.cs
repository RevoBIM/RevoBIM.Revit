using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Media;
using System.Windows.Threading;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Selection;
using RevoBIM.Helpers;
using RevoBIM.Tools.FamilyFindReplace;

using Button = System.Windows.Controls.Button;
using CheckBox = System.Windows.Controls.CheckBox;
using ComboBox = System.Windows.Controls.ComboBox;
using Grid = System.Windows.Controls.Grid;
using ListBox = System.Windows.Controls.ListBox;
using Panel = System.Windows.Controls.Panel;
using TextBox = System.Windows.Controls.TextBox;
using Visibility = System.Windows.Visibility;
using TypeRecord = RevoBIM.Tools.FamilyFindReplace.FfrCore.TypeRecord;
using Index = System.Collections.Generic.Dictionary<string, System.Collections.Generic.Dictionary<string, System.Collections.Generic.List<RevoBIM.Tools.FamilyFindReplace.FfrCore.TypeRecord>>>;

namespace RevoBIM.UI.FamilyFindReplace
{
    /// <summary>
    /// The tool's window. Modeless, so Revit stays fully navigable while it is open. Every read of and write to the
    /// document goes through a single ExternalEvent, which is the only place the Revit API is in context.
    /// Port of ffr_ui.py (MainWindow).
    /// </summary>
    internal sealed class FfrWindow
    {
        /// <summary>The window open now, so a second click on the ribbon brings it forward instead of leaving an orphan.</summary>
        private static FfrWindow current;

        /// <summary>Above this many group instances, ask before starting: taking a group type apart and putting it back is slow.</summary>
        private const int GroupPromptThreshold = 5;

        /// <summary>Active view leads and is the default: replacing across a whole project is the wider blast radius.</summary>
        private static readonly KeyValuePair<string, string>[] ScopeLabels =
        {
            new KeyValuePair<string, string>("Active view", FfrCore.ScopeView),
            new KeyValuePair<string, string>("Entire project", FfrCore.ScopeModel),
            new KeyValuePair<string, string>("Current selection", FfrCore.ScopeSelection),
        };

        /// <summary>The report's line colours: text brushes, not the accent fills.</summary>
        private static readonly Dictionary<string, string> ReportText = new Dictionary<string, string>
        {
            { "ok", "FgBody" }, { "warn", "TextWarn" }, { "fail", "TextFail" }, { "good", "TextGood" }, { "muted", "FgMuted" },
        };

        private readonly UIApplication uiapp;
        private readonly FfrJobHandler handler = new FfrJobHandler();
        private readonly ExternalEvent externalEvent;
        private readonly Window window;
        private readonly FfrDrawer drawer;

        // Each side has its own index. In a model view both point at the same one; in a drafting view Find lists
        // import symbols and Replace with lists detail items, which are not the same set at all.
        private Dictionary<string, Index> indexes = new Dictionary<string, Index> { { "Src", new Index() }, { "Tgt", new Index() } };
        private bool drafting;
        private bool lastDrafting;
        private bool lastByCentre;
        private bool closing;
        private EventHandler<Autodesk.Revit.UI.Events.ViewActivatedEventArgs> viewHandler;
        private bool retainCircuits = true;
        private bool busy;
        private int lastPercent = -1;
        private TypeRecord srcRecord;
        private TypeRecord tgtRecord;
        private Dictionary<string, FfrCore.ParamInfo> srcInfos = new Dictionary<string, FfrCore.ParamInfo>();
        private FfrCore.ElecProfile srcElec = new FfrCore.ElecProfile();
        private int srcCircuits;
        private bool srcCircuitsPartial;
        private int srcCount;
        private FfrCore.Probe probe;
        private List<FfrCore.ParamRow> paramRows = new List<FfrCore.ParamRow>();
        private string elecState = FfrCore.ElecNone;
        private List<ElementId> lastNewIds = new List<ElementId>();
        private FfrAdjustWindow adjust;
        private bool muting;

        private FfrWindow(UIApplication uiapp)
        {
            this.uiapp = uiapp;
            handler.OnError = ReportException;
            handler.OnFinish = BusyEnd;
            externalEvent = ExternalEvent.Create(handler);

            window = FfrXaml.LoadWindow("FamilyFindReplace.xaml");
            var header = (Border)Find("HeaderBar");
            // Held where it is while a run is going: the window is not clickable then anyway, and Ctrl+Shift+H must not slide it mid write.
            drawer = new FfrDrawer(window, header, (Panel)header.Parent, (Button)Find("ShrinkBtn"), () => !busy);
            Wire();
            FfrUi.OwnToRevit(window, uiapp);
        }

        /// <summary>Show the window, or bring the one already open back to the front.</summary>
        public static void Launch(UIApplication uiapp)
        {
            if (current != null)
            {
                try
                {
                    if (current.window.IsLoaded)
                    {
                        current.window.Activate();
                        return;
                    }
                }
                catch (Exception)
                {
                }
            }
            var tool = new FfrWindow(uiapp);
            current = tool;
            tool.Show();
        }

        // ---- plumbing ---------------------------------------------------------------------------------

        private FrameworkElement Find(string name) { return (FrameworkElement)window.FindName(name); }
        private TextBlock Text(string name) { return (TextBlock)window.FindName(name); }
        private Button Btn(string name) { return (Button)window.FindName(name); }
        private ComboBox Combo(string name) { return (ComboBox)window.FindName(name); }
        private ListBox List(string name) { return (ListBox)window.FindName(name); }
        private TextBox Box(string name) { return (TextBox)window.FindName(name); }
        private CheckBox Check(string name) { return (CheckBox)window.FindName(name); }
        private bool Ticked(string name) { return Check(name).IsChecked == true; }

        private void Wire()
        {
            var icon = (Image)Find("IconImage");
            FfrXaml.LoadIcon(icon);
            // three slow clicks on the logo open the RevoBIM Arcade; the logo only, never the whole window
            EggHook.Attach(window, () => "dark", icon);
            Text("VersionText").Text = "v" + FfrCore.Version;

            Find("HeaderBar").MouseLeftButtonDown += (s, a) =>
            {
                // a double click on a parked bar opens it; anything else drags
                if (drawer.OnHeaderDown(a)) return;
                try
                {
                    window.DragMove();
                }
                catch (Exception)
                {
                }
            };
            Btn("CloseBtn").Click += (s, a) => window.Close();
            window.Closed += OnClosed;

            Combo("SrcCategoryCombo").SelectionChanged += (s, a) => { if (!muting) FillFamilies("Src"); };
            Box("SrcSearchBox").TextChanged += (s, a) => { if (!muting) FillFamilies("Src"); };
            List("SrcFamilyList").SelectionChanged += (s, a) => { if (!muting) FillTypes("Src"); };
            List("SrcTypeList").SelectionChanged += (s, a) =>
            {
                if (muting) return;
                var item = List("SrcTypeList").SelectedItem as ListBoxItem;
                srcRecord = item == null ? null : item.Tag as TypeRecord;
                RefreshSource();
            };
            Combo("ScopeCombo").SelectionChanged += (s, a) => { if (!muting) RefreshSource(); };

            Combo("TgtCategoryCombo").SelectionChanged += (s, a) => { if (!muting) FillFamilies("Tgt"); };
            Box("TgtSearchBox").TextChanged += (s, a) => { if (!muting) FillFamilies("Tgt"); };
            List("TgtFamilyList").SelectionChanged += (s, a) => { if (!muting) FillTypes("Tgt"); };
            List("TgtTypeList").SelectionChanged += (s, a) =>
            {
                if (muting) return;
                var item = List("TgtTypeList").SelectedItem as ListBoxItem;
                tgtRecord = item == null ? null : item.Tag as TypeRecord;
                RefreshTarget();
            };

            Btn("SrcPickBtn").Click += (s, a) => PickSource();
            Btn("PickTargetBtn").Click += (s, a) => PickTarget();

            Box("ParamSearchBox").TextChanged += (s, a) => FillParamList();
            Btn("ParamAllBtn").Click += (s, a) =>
            {
                foreach (FfrCore.ParamRow row in paramRows) row.Checked = row.OnTarget;
                FillParamList();
            };
            Btn("ParamNoneBtn").Click += (s, a) =>
            {
                foreach (FfrCore.ParamRow row in paramRows) row.Checked = false;
                FillParamList();
            };
            Btn("ParamSharedBtn").Click += (s, a) =>
            {
                foreach (FfrCore.ParamRow row in paramRows) row.Checked = row.OnTarget && row.IsShared;
                FillParamList();
            };

            Btn("ElecBtn").Click += (s, a) => ElecClicked();

            Check("LevelBelowCheck").Checked += (s, a) => LevelModeChanged();
            Check("LevelBelowCheck").Unchecked += (s, a) => LevelModeChanged();

            WireResize();

            Btn("PreviewBtn").Click += (s, a) => Preview();
            Btn("RunBtn").Click += (s, a) => Run();
            Btn("AdjustBtn").Click += (s, a) => { if (lastNewIds.Count > 0) OpenAdjust(); };

            muting = true;
            ComboBox scope = Combo("ScopeCombo");
            foreach (KeyValuePair<string, string> label in ScopeLabels) scope.Items.Add(label.Key);
            scope.SelectedIndex = 0;
            muting = false;
        }

        private void OnClosed(object sender, EventArgs args)
        {
            closing = true;
            UnhookViews();
            try
            {
                if (adjust != null) adjust.Window.Close();
            }
            catch (Exception)
            {
            }
            if (ReferenceEquals(current, this)) current = null;
            FfrLog.Write("window: closed");
        }

        private void ReportException(string text)
        {
            Status("Something went wrong - see the report.");
            ReportClear();
            foreach (string line in text.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries))
                if (line.Trim().Length > 0) ReportAdd("fail", line);
        }

        private void Post(Action<UIApplication> job)
        {
            handler.Queue(job);
            externalEvent.Raise();
        }

        public void Show()
        {
            FfrLog.Begin(uiapp.Application.VersionName + " " + uiapp.Application.VersionBuild, SafeTitle());
            window.Show();
            HookViews();
            Post(JobLoadIndex);
        }

        private string SafeTitle()
        {
            try
            {
                return uiapp.ActiveUIDocument.Document.Title;
            }
            catch (Exception)
            {
                return "?";
            }
        }

        // ---- progress ---------------------------------------------------------------------------------

        /// <summary>
        /// Show the bar and stop the window answering the mouse. Pumping the dispatcher to move a progress bar also
        /// pumps input, so the window could be clicked, or closed, part way through a run. Making it
        /// hit-test-invisible for the duration is what stops that.
        /// </summary>
        private void BusyStart(string label)
        {
            busy = true;
            lastPercent = -1;   // -1 rather than 0, so the first call at 0% still paints
            try
            {
                Find("ProgressTrack").Visibility = Visibility.Visible;
                window.IsHitTestVisible = false;
            }
            catch (Exception)
            {
            }
            SetProgress(0, 1, label);
        }

        private void BusyEnd()
        {
            busy = false;
            try
            {
                Find("ProgressTrack").Visibility = Visibility.Collapsed;
                Text("ProgressText").Text = "";
                Text("ProgressLabel").Text = "";
                window.IsHitTestVisible = true;
            }
            catch (Exception)
            {
            }
        }

        /// <summary>Repaint only when the whole percent moves: pumping on every one of several thousand elements costs more than the work being measured.</summary>
        private void SetProgress(int done, int total, string label)
        {
            if (total <= 0) return;
            int percent = (int)(done * 100L / total);
            if (percent > 100) percent = 100;
            if (percent == lastPercent) return;
            lastPercent = percent;
            int left = Math.Max(0, total - done);
            try
            {
                ((ColumnDefinition)window.FindName("ProgressDone")).Width = new GridLength(percent, GridUnitType.Star);
                ((ColumnDefinition)window.FindName("ProgressLeft")).Width = new GridLength(100 - percent, GridUnitType.Star);
                Text("ProgressText").Text = percent + "%";
                // what is left rather than what is done: on a long run the useful question is how much more of it there is
                Text("ProgressLabel").Text = left > 0
                    ? percent + "%   -   " + left + " of " + total + " left   -   " + (string.IsNullOrEmpty(label) ? "working" : label)
                    : percent + "%   -   done";
            }
            catch (Exception)
            {
            }
            if (!string.IsNullOrEmpty(label)) Status(label);
            Pump();
        }

        /// <summary>Let the window repaint. Safe only because the core calls this between transactions, never between a Start and a Commit.</summary>
        private void Pump()
        {
            try
            {
                window.Dispatcher.Invoke(DispatcherPriority.Render, new Action(() => { }));
            }
            catch (Exception)
            {
            }
        }

        // ---- status and report ------------------------------------------------------------------------

        private void Status(string text)
        {
            try
            {
                Text("StatusText").Text = text;
            }
            catch (Exception)
            {
            }
        }

        private void ReportClear()
        {
            List("ReportList").Items.Clear();
            Text("ReportSummary").Text = "";
        }

        private void ReportAdd(string kind, string text)
        {
            var block = new TextBlock { Text = text, TextWrapping = TextWrapping.Wrap };
            string key;
            Brush colour = FfrUi.BrushOf(window, ReportText.TryGetValue(kind, out key) ? key : "FgBody");
            if (colour != null) block.Foreground = colour;
            List("ReportList").Items.Add(block);
        }

        // ---- model index ------------------------------------------------------------------------------

        /// <summary>
        /// Read both lists for the kind of view that is active. Run on opening and again whenever the active view
        /// changes between a drafting view and anything else, because the two modes do not share a single list:
        /// a pick or a type chosen in one means nothing in the other, so both sides are cleared on a switch.
        /// </summary>
        private void JobLoadIndex(UIApplication app)
        {
            UIDocument uidoc = app.ActiveUIDocument;
            Document doc = uidoc.Document;
            drafting = FfrCore.IsDraftingView(uidoc.ActiveView);
            if (drafting)
            {
                indexes = new Dictionary<string, Index> { { "Src", FfrCore.BuildImportIndex(doc) }, { "Tgt", FfrCore.BuildDetailIndex(doc) } };
            }
            else
            {
                Index shared = FfrCore.BuildIndex(doc);
                indexes = new Dictionary<string, Index> { { "Src", shared }, { "Tgt", shared } };
            }

            srcRecord = null;
            tgtRecord = null;
            probe = null;
            srcCount = 0;
            srcInfos = new Dictionary<string, FfrCore.ParamInfo>();
            srcElec = new FfrCore.ElecProfile();
            srcCircuits = 0;

            bool wasMuting = muting;
            muting = true;
            var single = new List<string>();
            try
            {
                foreach (string side in new[] { "Src", "Tgt" })
                {
                    ComboBox combo = Combo(side + "CategoryCombo");
                    combo.Items.Clear();
                    List(side + "FamilyList").Items.Clear();
                    List(side + "TypeList").Items.Clear();
                    List<string> names = indexes[side].Keys.OrderBy(n => n.ToLowerInvariant(), StringComparer.Ordinal).ToList();
                    foreach (string name in names) combo.Items.Add(name);
                    // one category (Detail Items, say) is chosen for you rather than making you open a list with one thing in it
                    if (names.Count == 1)
                    {
                        combo.SelectedIndex = 0;
                        single.Add(side);
                    }
                }
            }
            finally
            {
                muting = wasMuting;
            }
            foreach (string side in single) FillFamilies(side);

            Text("TgtInfoText").Text = "No replacement chosen yet.";
            Text("SrcCountText").Text = drafting ? "Choose an import symbol to find." : "Choose a family to find.";
            ApplyMode();
            RebuildParams();
            UpdateRun();

            if (drafting)
            {
                int imports = indexes["Src"].Values.SelectMany(f => f.Values).SelectMany(r => r).Sum(r => r.Count);
                int details = indexes["Tgt"].Values.Sum(f => f.Count);
                Status("Drafting view: " + imports + " import symbol(s) found in views, " + details + " detail item famil(ies) to replace them with.");
                FfrLog.Write("index: drafting view '" + FfrCore.Name(uidoc.ActiveView) + "', " + imports + " import symbol(s), " + details + " detail item famil(ies)");
            }
            else
            {
                Status(indexes["Src"].Count + " categories read from the model. Choose the family to find, then the family to replace it with.");
                int types = indexes["Src"].Values.SelectMany(f => f.Values).Sum(r => r.Count);
                FfrLog.Write("index: model view '" + FfrCore.Name(uidoc.ActiveView) + "', " + indexes["Src"].Count + " categories, " + types + " type(s)");
            }
        }

        // ---- drafting mode ----------------------------------------------------------------------------

        /// <summary>Set the window up for a drafting view or a model view.</summary>
        private void ApplyMode()
        {
            Visibility shown = drafting ? Visibility.Visible : Visibility.Collapsed;
            Visibility hidden = drafting ? Visibility.Collapsed : Visibility.Visible;
            try
            {
                Find("ModeChip").Visibility = shown;
                Btn("SrcPickBtn").Content = drafting ? "Select import symbol in the view" : "Select family in the model";
                Btn("PickTargetBtn").Content = drafting ? "Select detail item in the view" : "Select family in the model";

                // greyed as a whole: there is nothing to circuit or wire in a drafting view, and a live-looking control would suggest there is
                FrameworkElement card = Find("ElecCard");
                card.IsEnabled = !drafting;
                card.Opacity = drafting ? 0.45 : 1.0;

                CheckBox groups = Check("GroupsCheck");
                groups.IsEnabled = !drafting;
                if (drafting)
                {
                    groups.IsChecked = false;
                    groups.ToolTip = "Groups are not handled in drafting views.";
                }
                else groups.ToolTip = null;

                Check("LevelBelowCheck").Visibility = hidden;
                Check("MirrorCheck").Visibility = shown;
                Check("CentreAlignCheck").Visibility = shown;
                Text("LevelNote").Text = drafting
                    ? "Each import symbol becomes a detail item whose insertion point sits on the block's AutoCAD base point, turned to the same " +
                      "rotation - the way a family-for-family swap lands. Tick \"line up centres\" to match middles instead."
                    : "A face based family often carries no level, or carries its host's. Untick to keep the original's own level.";
            }
            catch (Exception)
            {
            }
            RefreshElectrical();
        }

        /// <summary>
        /// Follow the active view, so the mode follows it too. The handler is kept as one object so the same one
        /// can be taken off again on close.
        /// </summary>
        private void HookViews()
        {
            viewHandler = ViewActivated;
            try
            {
                uiapp.ViewActivated += viewHandler;
            }
            catch (Exception)
            {
                viewHandler = null;
            }
        }

        private void UnhookViews()
        {
            if (viewHandler == null) return;
            try
            {
                uiapp.ViewActivated -= viewHandler;
            }
            catch (Exception)
            {
            }
            viewHandler = null;
        }

        private void ViewActivated(object sender, Autodesk.Revit.UI.Events.ViewActivatedEventArgs args)
        {
            if (closing || busy) return;
            bool nowDrafting;
            try
            {
                nowDrafting = FfrCore.IsDraftingView(args.CurrentActiveView);
            }
            catch (Exception)
            {
                return;
            }
            if (nowDrafting != drafting)
            {
                Status("The view changed - reading the lists again...");
                Post(JobLoadIndex);
                return;
            }
            // same mode, different view: "Active view" now means a different set
            if (srcRecord != null && ScopeValue() == FfrCore.ScopeView) RefreshSource();
        }

        // ---- scope ------------------------------------------------------------------------------------

        private string ScopeValue()
        {
            int index = Combo("ScopeCombo").SelectedIndex;
            return index < 0 || index >= ScopeLabels.Length ? FfrCore.ScopeModel : ScopeLabels[index].Value;
        }

        private string ScopeLabel()
        {
            int index = Combo("ScopeCombo").SelectedIndex;
            return index < 0 || index >= ScopeLabels.Length ? ScopeLabels[0].Key : ScopeLabels[index].Key;
        }

        // ---- list filling -----------------------------------------------------------------------------

        private void FillFamilies(string side)
        {
            ComboBox combo = Combo(side + "CategoryCombo");
            ListBox familyList = List(side + "FamilyList");
            ListBox typeList = List(side + "TypeList");
            string keyword = (Box(side + "SearchBox").Text ?? "").Trim().ToLowerInvariant();

            bool wasMuting = muting;
            muting = true;
            familyList.Items.Clear();
            typeList.Items.Clear();
            muting = wasMuting;

            string category = combo.SelectedItem as string;
            if (category == null) return;
            Dictionary<string, List<TypeRecord>> families;
            if (!indexes[side].TryGetValue(category, out families)) return;

            int shown = 0;
            foreach (string familyName in families.Keys.OrderBy(n => n.ToLowerInvariant(), StringComparer.Ordinal))
            {
                List<TypeRecord> records = families[familyName];
                if (keyword.Length > 0)
                {
                    bool hit = familyName.ToLowerInvariant().Contains(keyword) || records.Any(r => r.TypeName.ToLowerInvariant().Contains(keyword));
                    if (!hit) continue;
                }
                int placed = records.Sum(r => r.Count);
                familyList.Items.Add(FfrUi.MakeRow(window, familyName, records.Count + " type(s), " + placed + " placed", familyName));
                shown++;
            }
            if (shown == 1) familyList.SelectedIndex = 0;
        }

        private void FillTypes(string side)
        {
            ComboBox combo = Combo(side + "CategoryCombo");
            ListBox familyList = List(side + "FamilyList");
            ListBox typeList = List(side + "TypeList");
            string keyword = (Box(side + "SearchBox").Text ?? "").Trim().ToLowerInvariant();

            bool wasMuting = muting;
            muting = true;
            typeList.Items.Clear();
            muting = wasMuting;

            string category = combo.SelectedItem as string;
            var item = familyList.SelectedItem as ListBoxItem;
            if (category == null || item == null) return;
            string familyName = (string)item.Tag;
            Dictionary<string, List<TypeRecord>> families;
            List<TypeRecord> records;
            if (!indexes[side].TryGetValue(category, out families) || !families.TryGetValue(familyName, out records)) return;

            bool familyHit = keyword.Length > 0 && familyName.ToLowerInvariant().Contains(keyword);
            foreach (TypeRecord record in records)
            {
                if (keyword.Length > 0 && !familyHit && !record.TypeName.ToLowerInvariant().Contains(keyword)) continue;
                typeList.Items.Add(FfrUi.MakeRow(window, record.TypeName, record.Count + " placed", record));
            }
            if (typeList.Items.Count == 1) typeList.SelectedIndex = 0;
        }

        /// <summary>Drive the three lists from a type picked in the model. Kept muted throughout so the selection changes do not each kick off their own read of the document.</summary>
        private void SelectInLists(string side, TypeRecord record)
        {
            bool wasMuting = muting;
            muting = true;
            try
            {
                ComboBox combo = Combo(side + "CategoryCombo");
                Box(side + "SearchBox").Text = "";
                for (int i = 0; i < combo.Items.Count; i++)
                {
                    if ((string)combo.Items[i] == record.CategoryName)
                    {
                        combo.SelectedIndex = i;
                        break;
                    }
                }
                FillFamilies(side);

                ListBox familyList = List(side + "FamilyList");
                for (int i = 0; i < familyList.Items.Count; i++)
                {
                    if ((string)((ListBoxItem)familyList.Items[i]).Tag == record.FamilyName)
                    {
                        familyList.SelectedIndex = i;
                        break;
                    }
                }
                FillTypes(side);

                ListBox typeList = List(side + "TypeList");
                for (int i = 0; i < typeList.Items.Count; i++)
                {
                    var tag = ((ListBoxItem)typeList.Items[i]).Tag as TypeRecord;
                    if (tag != null && FfrCore.Eid(tag.SymbolId) == FfrCore.Eid(record.SymbolId))
                    {
                        typeList.SelectedIndex = i;
                        break;
                    }
                }
            }
            finally
            {
                muting = wasMuting;
            }
        }

        // ---- picking ----------------------------------------------------------------------------------

        /// <summary>The type record behind a picked element.</summary>
        private static TypeRecord ReadSymbol(Document doc, Reference reference, int count)
        {
            Element element = doc.GetElement(reference.ElementId);
            if (element == null) return null;
            if (element is ImportInstance) return FfrCore.ImportRecord(doc, element, count);
            var symbol = doc.GetElement(element.GetTypeId()) as FamilySymbol;
            if (symbol == null) return null;
            string category = "";
            try
            {
                category = symbol.Category.Name;
            }
            catch (Exception)
            {
            }
            return new TypeRecord(symbol.Id, FfrCore.Name(symbol), FfrCore.Name(symbol.Family), category, FfrCore.PlacementName(symbol), count);
        }

        /// <summary>
        /// Click one element in the model to set the family to find. A single PickObject, so one click completes
        /// the step: no Finish, no Enter. What it sets is the family and type, not that one element; the scope
        /// decides how many instances of it get replaced.
        /// </summary>
        private void PickSource()
        {
            Post(app =>
            {
                UIDocument uidoc = app.ActiveUIDocument;
                ISelectionFilter filter;
                string prompt;
                if (drafting)
                {
                    filter = new FfrCore.ImportPickFilter();
                    prompt = "Click the import symbol you want to REPLACE";
                }
                else
                {
                    filter = new FfrCore.FamilyInstancePickFilter();
                    prompt = "Click the element whose family you want to REPLACE";
                }
                Status(prompt + ".");
                Reference reference;
                try
                {
                    reference = uidoc.Selection.PickObject(ObjectType.Element, filter, prompt);
                }
                catch (Exception)
                {
                    Status("Picking abandoned - nothing changed.");
                    return;
                }
                TypeRecord record = ReadSymbol(uidoc.Document, reference, 0);
                if (record == null)
                {
                    Status("That element has no family type to read.");
                    return;
                }
                srcRecord = record;
                SelectInLists("Src", record);
                Status("Finding " + record.Label + ". Now choose what to replace it with.");
                FfrLog.Write("pick: find = " + record.Label + " (" + record.Placement + ")");
                RefreshSource();
            });
        }

        /// <summary>Click one element in the model to set the replacement family.</summary>
        private void PickTarget()
        {
            Post(app =>
            {
                UIDocument uidoc = app.ActiveUIDocument;
                ISelectionFilter filter;
                string prompt;
                if (drafting)
                {
                    filter = new FfrCore.DetailItemPickFilter();
                    prompt = "Click a detail item to replace them WITH";
                }
                else
                {
                    filter = new FfrCore.FamilyInstancePickFilter();
                    prompt = "Click an element of the family to replace it WITH";
                }
                Status(prompt + ".");
                Reference reference;
                try
                {
                    reference = uidoc.Selection.PickObject(ObjectType.Element, filter, prompt);
                }
                catch (Exception)
                {
                    Status("Picking abandoned - nothing changed.");
                    return;
                }
                TypeRecord record = ReadSymbol(uidoc.Document, reference, 0);
                if (record == null)
                {
                    Status("That element has no family type to read.");
                    return;
                }
                if (srcRecord != null && FfrCore.Eid(record.SymbolId) == FfrCore.Eid(srcRecord.SymbolId))
                {
                    Status("That is the same type as the one being found.");
                    return;
                }
                tgtRecord = record;
                SelectInLists("Tgt", record);
                FfrLog.Write("pick: replace with = " + record.Label + " (" + record.Placement + ")");
                RefreshTarget();
            });
        }

        // ---- refresh ----------------------------------------------------------------------------------

        private void RefreshSource()
        {
            Post(app =>
            {
                UIDocument uidoc = app.ActiveUIDocument;
                Document doc = uidoc.Document;
                FfrCore.ResetRunCaches();
                List<Element> instances = SourceInstances(doc, uidoc);
                srcCount = instances.Count;
                srcInfos = new Dictionary<string, FfrCore.ParamInfo>();
                srcElec = new FfrCore.ElecProfile();
                srcCircuits = 0;
                // circuits are only counted over the first few hundred so driving the window stays responsive; the run itself handles every one
                srcCircuitsPartial = instances.Count > FfrCore.CircuitScanCap;
                foreach (Element instance in instances.Take(FfrCore.CircuitScanCap))
                {
                    if (srcInfos.Count == 0)
                    {
                        srcInfos = FfrCore.ReadParamInfos(instance);
                        if (!drafting) srcElec = FfrCore.ElectricalProfile(instance);
                    }
                    if (drafting) break;
                    if (FfrCore.ElectricalSystems(instance).Count > 0) srcCircuits++;
                }
                string label = srcRecord != null ? srcRecord.Label : "nothing";
                Text("SrcCountText").Text = srcCount + " " + (drafting ? "import symbol(s)" : "instance(s)") + " of " + label + " in " + ScopeLabel().ToLowerInvariant() + ".";
                FfrLog.Write("refresh: " + srcCount + " of " + label + " in " + ScopeLabel().ToLowerInvariant() + "; " + srcInfos.Count + " writable parameter(s), " +
                             srcCircuits + (srcCircuitsPartial ? "+" : "") + " circuited");
                RebuildParams();
                RefreshElectrical();
                UpdateRun();
            });
        }

        /// <summary>
        /// Every instance of the source type inside the chosen scope. Both ways of choosing the type land here:
        /// from that point on they behave identically, and the scope decides how many get replaced.
        /// </summary>
        private List<Element> SourceInstances(Document doc, UIDocument uidoc)
        {
            if (srcRecord == null) return new List<Element>();
            return drafting
                ? FfrCore.CollectImports(doc, uidoc, srcRecord.SymbolId, ScopeValue())
                : FfrCore.CollectInstances(doc, uidoc, srcRecord.SymbolId, ScopeValue());
        }

        private void RefreshTarget()
        {
            if (tgtRecord == null) return;
            TypeRecord record = tgtRecord;
            Text("TgtInfoText").Text = "Reading " + record.Label + "...";
            Post(app =>
            {
                UIDocument uidoc = app.ActiveUIDocument;
                // the active view goes in too: a detail item can only be test-placed in a view
                probe = FfrCore.ProbeSymbol(uidoc.Document, record.SymbolId, uidoc.ActiveView);
                Text("TgtInfoText").Text = record.Label + "\nPlacement: " + probe.Placement + ". " + probe.Note;
                FfrLog.Write("probe: " + record.Label + " placement " + probe.Placement + ", ok " + probe.Ok + ", " + probe.ParamInfos.Count +
                             " writable parameter(s), connector " + probe.Elec.HasConnector + " [" + probe.Note + "]");
                RebuildParams();
                RefreshElectrical();
                UpdateRun();
            });
        }

        // ---- parameters -------------------------------------------------------------------------------

        private void RebuildParams()
        {
            Dictionary<string, FfrCore.ParamInfo> targetInfos = probe != null ? probe.ParamInfos : null;
            if (srcInfos.Count == 0) paramRows = new List<FfrCore.ParamRow>();
            else
            {
                var existing = new Dictionary<string, bool>();
                foreach (FfrCore.ParamRow row in paramRows) existing[row.Name] = row.Checked;
                paramRows = FfrCore.BuildParamRows(srcInfos, targetInfos);
                foreach (FfrCore.ParamRow row in paramRows)
                {
                    bool was;
                    if (existing.TryGetValue(row.Name, out was) && row.OnTarget) row.Checked = was;
                }
            }
            FillParamList();
        }

        private void FillParamList()
        {
            string keyword = (Box("ParamSearchBox").Text ?? "").Trim().ToLowerInvariant();
            ListBox listbox = List("ParamList");
            listbox.Items.Clear();
            // styles, not brushes: each one turns to the body colour on a selected row, where muted, red and blue all fall under 2.5:1
            Style rowNote = FfrUi.StyleOf(window, "RowNote");
            Style rowNoteFail = FfrUi.StyleOf(window, "RowNoteFail");
            Style rowShared = FfrUi.StyleOf(window, "RowShared");

            int shown = 0;
            foreach (FfrCore.ParamRow row in paramRows)
            {
                if (keyword.Length > 0 && !row.Name.ToLowerInvariant().Contains(keyword)) continue;
                var check = new CheckBox { IsChecked = row.Checked, IsEnabled = row.OnTarget, Tag = row };
                check.Checked += ParamToggled;
                check.Unchecked += ParamToggled;

                var panel = new StackPanel { Orientation = Orientation.Vertical };
                var title = new TextBlock { Text = row.Name };
                if (row.IsShared && rowShared != null) title.Style = rowShared;
                panel.Children.Add(title);

                var bits = new List<string> { row.Storage.Replace("StorageType.", "") };
                if (!string.IsNullOrEmpty(row.Sample))
                {
                    string sample = row.Sample;
                    if (sample.Length > 42) sample = sample.Substring(0, 39) + "...";
                    bits.Add(sample);
                }
                if (!string.IsNullOrEmpty(row.Note)) bits.Add(row.Note);
                var subtitle = new TextBlock { Text = string.Join("  -  ", bits), FontSize = 10 };
                Style tone = string.IsNullOrEmpty(row.Note) ? rowNote : rowNoteFail;
                if (tone != null) subtitle.Style = tone;
                panel.Children.Add(subtitle);

                check.Content = panel;
                listbox.Items.Add(check);
                shown++;
            }
            Text("ParamCountText").Text = paramRows.Count(r => r.Checked && r.OnTarget) + " ticked of " + shown + " shown";
        }

        private void ParamToggled(object sender, RoutedEventArgs args)
        {
            var check = (CheckBox)sender;
            var row = check.Tag as FfrCore.ParamRow;
            if (row != null) row.Checked = check.IsChecked == true;
            Text("ParamCountText").Text = paramRows.Count(r => r.Checked && r.OnTarget) + " ticked of " + List("ParamList").Items.Count + " shown";
        }

        private List<string> RetainedNames()
        {
            return paramRows.Where(r => r.Checked && r.OnTarget).Select(r => r.Name).ToList();
        }

        // ---- electrical -------------------------------------------------------------------------------

        /// <summary>
        /// Paint the circuits chip. The chip is a toggle, not a verdict: On means carry the circuits across, Off
        /// means do not. Solid green for On, solid red for Off, because Off on a circuited selection is the
        /// destructive setting and should not look like the safe one. Whether the two families actually agree
        /// goes in the line underneath, where it can be read without turning the chip into a second control.
        /// </summary>
        private void RefreshElectrical()
        {
            Button button = Btn("ElecBtn");
            TextBlock detail = Text("ElecDetail");
            TextBlock countText = Text("ElecCircuitCount");

            if (drafting)
            {
                button.Content = "Circuits retained? : n/a";
                PaintSolid(button, "BgHover");
                Brush muted = FfrUi.BrushOf(window, "FgMuted");
                if (muted != null) button.Foreground = muted;
                detail.Text = "Not used in a drafting view - import symbols and detail items carry no circuits or wires.";
                PaintText(detail, "FgMuted");
                countText.Text = "";
                elecState = FfrCore.ElecNone;
                return;
            }

            bool on = retainCircuits;
            button.Content = "Circuits retained? : " + (on ? "On" : "Off");
            PaintSolid(button, on ? "AccGreen" : "AccRed");

            if (probe == null || srcInfos.Count == 0)
            {
                detail.Text = "Choose both families to check the circuits.";
                PaintText(detail, "FgMuted");
                countText.Text = "";
                elecState = FfrCore.ElecNone;
                return;
            }

            string headline;
            List<string> lines;
            string state = FfrCore.CompareElectrical(srcElec, probe.Elec, srcCircuits, out headline, out lines);
            elecState = state;
            countText.Text = srcCircuits + (srcCircuitsPartial ? "+" : "") + " circuited";

            if (!on)
            {
                if (srcCircuits > 0)
                {
                    detail.Text = srcCircuits + " circuit(s) on the originals will be lost when they are deleted. Turn this back on to carry them across.";
                    PaintText(detail, "TextFail");
                }
                else
                {
                    detail.Text = "Nothing on the selection is circuited.";
                    PaintText(detail, "FgMuted");
                }
                return;
            }

            if (state == FfrCore.ElecRetain || state == FfrCore.ElecNone)
            {
                detail.Text = string.Join(" ", lines);
                PaintText(detail, "FgMuted");
            }
            else
            {
                // on, but the two families disagree: the chip stays green because the setting really is on; the warning belongs here
                detail.Text = headline + ". " + string.Join(" ", lines) + " Circuited elements will be left alone rather than swapped, so no circuit is destroyed.";
                PaintText(detail, "TextFail");
            }
        }

        /// <summary>Fill the chip, not just outline it: On and Off both read at a glance. Dark ink on the fill (white on green is 3.05:1, this is 6.15:1).</summary>
        private void PaintSolid(Button button, string key)
        {
            Brush value = FfrUi.BrushOf(window, key);
            if (value != null)
            {
                button.Background = value;
                button.BorderBrush = value;
            }
            Brush ink = FfrUi.BrushOf(window, "InkOnAccent");
            if (ink != null) button.Foreground = ink;
            button.FontWeight = FontWeights.SemiBold;
        }

        private void PaintText(TextBlock block, string key)
        {
            Brush value = FfrUi.BrushOf(window, key);
            if (value != null) block.Foreground = value;
        }

        /// <summary>The chip is the toggle.</summary>
        private void ElecClicked()
        {
            if (drafting) return;
            retainCircuits = !retainCircuits;
            RefreshElectrical();
            UpdateRun();
            Status("Circuits will " + (retainCircuits ? "now" : "NOT") + " be carried across.");
            FfrLog.Write("option: circuits retained " + retainCircuits);
        }

        // ---- resize -----------------------------------------------------------------------------------

        /// <summary>
        /// Drag any edge or corner to resize. A window with WindowStyle=None and AllowsTransparency=True gets no
        /// usable resize border from WPF, so eight thumbs over the edges do the job explicitly.
        /// </summary>
        private void WireResize()
        {
            foreach (string[] grip in new[]
                     {
                         new[] { "GripNW", "NW" }, new[] { "GripN", "N" }, new[] { "GripNE", "NE" }, new[] { "GripW", "W" },
                         new[] { "GripE", "E" }, new[] { "GripSW", "SW" }, new[] { "GripS", "S" }, new[] { "GripSE", "SE" },
                     })
            {
                var thumb = window.FindName(grip[0]) as Thumb;
                if (thumb == null) continue;
                string edge = grip[1];
                thumb.DragDelta += (s, a) =>
                {
                    try
                    {
                        Resize(edge, a.HorizontalChange, a.VerticalChange);
                    }
                    catch (Exception)
                    {
                    }
                };
            }
        }

        private void Resize(string edge, double dx, double dy)
        {
            // the grips are hidden while parked; this is the belt to those braces
            if (!drawer.IsOpen) return;
            double minW = window.MinWidth > 0 ? window.MinWidth : 400;
            double minH = window.MinHeight > 0 ? window.MinHeight : 300;
            double width = window.ActualWidth;
            double height = window.ActualHeight;

            if (edge.Contains("E")) window.Width = Math.Max(minW, width + dx);
            if (edge.Contains("W"))
            {
                // dragging the west edge has to move the window left as it widens, or the right edge walks across the screen
                double wanted = Math.Max(minW, width - dx);
                window.Left = window.Left + (width - wanted);
                window.Width = wanted;
            }
            if (edge.Contains("S")) window.Height = Math.Max(minH, height + dy);
            if (edge.Contains("N"))
            {
                double wanted = Math.Max(minH, height - dy);
                window.Top = window.Top + (height - wanted);
                window.Height = wanted;
            }
        }

        private void LevelModeChanged()
        {
            if (muting) return;
            Text("LevelNote").Text = Ticked("LevelBelowCheck")
                ? "A face based family hosted to a face often carries no level, or carries its host's - a light on Level 1's ceiling reports Level 2. " +
                  "Each replacement is associated with the nearest level at or below its own insertion point instead."
                : "Each replacement keeps whatever level its original was associated with, falling back to the nearest level below where the original " +
                  "has none. Use this where a family is deliberately dimensioned down from the level above on a negative offset.";
            Status("Level rule changed. Preview to see which levels apply.");
            FfrLog.Write("option: level below insertion point " + Ticked("LevelBelowCheck"));
        }

        // ---- run --------------------------------------------------------------------------------------

        private void UpdateRun()
        {
            bool ready = srcCount > 0 && tgtRecord != null;
            Btn("RunBtn").IsEnabled = ready;
            Btn("PreviewBtn").IsEnabled = ready;
            Btn("AdjustBtn").IsEnabled = lastNewIds.Count > 0;
        }

        private static string Pairs(Dictionary<string, int> map)
        {
            return string.Join(", ", map.OrderByDescending(p => p.Value).Select(p => p.Key + " (" + p.Value + ")"));
        }

        private void Preview()
        {
            Post(app =>
            {
                UIDocument uidoc = app.ActiveUIDocument;
                Document doc = uidoc.Document;
                FfrCore.ResetRunCaches();
                List<Element> instances = SourceInstances(doc, uidoc);
                ReportClear();
                if (drafting)
                {
                    PreviewDrafting(doc, instances);
                    return;
                }
                string sourceLabel = srcRecord != null ? srcRecord.Label : "the picked type";
                ReportAdd("ok", instances.Count + " element(s) of " + sourceLabel);
                ReportAdd("ok", "become " + tgtRecord.Label + " (" + (probe != null ? probe.Placement : "unknown placement") + ")");

                int grouped = 0, lineBased = 0, circuited = 0, tagged = 0, wireEnds = 0;
                bool wantTags = Ticked("TagsCheck");
                bool wantWires = Ticked("WiresCheck");
                bool levelBelow = Ticked("LevelBelowCheck");
                var levels = new Dictionary<string, int>();
                int total = instances.Count;
                BusyStart("Checking...");
                int seen = 0;
                foreach (Element instance in instances)
                {
                    seen++;
                    SetProgress(seen, total, "Checking " + seen + " of " + total);
                    try
                    {
                        if (instance.GroupId != null && FfrCore.Eid(instance.GroupId) > 0)
                        {
                            grouped++;
                            continue;
                        }
                    }
                    catch (Exception)
                    {
                    }
                    XYZ point = FfrCore.InstancePoint(instance);
                    if (point == null) lineBased++;
                    else
                    {
                        Level level = FfrCore.ResolveLevel(doc, instance, point, levelBelow);
                        FfrCore.Report.Bump(levels, level != null ? FfrCore.Name(level) : "no level found");
                    }
                    if (FfrCore.ElectricalSystems(instance).Count > 0) circuited++;
                    tagged += FfrCore.TagsOn(doc, instance).Count;
                    wireEnds += FfrCore.WireLinks(doc, instance).Count;
                }

                if (tagged > 0)
                {
                    if (wantTags) ReportAdd("good", tagged + " tag(s) will be moved onto the replacements.");
                    else ReportAdd("warn", tagged + " tag(s) will be deleted with the originals - retain tags is off.");
                }
                if (wireEnds > 0)
                {
                    if (wantWires) ReportAdd("good", wireEnds + " wire end(s) will be reconnected to the replacements.");
                    else ReportAdd("warn", wireEnds + " wire end(s) will be left dangling - reconnect wires is off.");
                }

                List<string> names = RetainedNames();
                if (levels.Count > 0)
                    ReportAdd("muted", "Level " + (levelBelow ? "below the insertion point" : "kept from the original") + ": " + Pairs(levels));
                ReportAdd("muted", names.Count + " parameter(s) kept: " + (names.Count > 0 ? string.Join(", ", names) : "none"));
                if (circuited > 0 && !retainCircuits)
                    ReportAdd("fail", circuited + " circuited element(s) - circuits retained is off, so those circuits will be lost.");
                else if (circuited > 0)
                {
                    if (elecState == FfrCore.ElecRetain)
                        ReportAdd("good", circuited + " circuited element(s) - each replacement joins the circuit before the original is deleted.");
                    else
                        ReportAdd("warn", circuited + " circuited element(s) - the two families disagree, so those elements will be left alone rather than swapped. No circuit is destroyed.");
                }
                if (grouped > 0 && Ticked("GroupsCheck"))
                {
                    FfrCore.ResetRunCaches();
                    List<Element> loose;
                    List<FfrCore.GroupWork> work = FfrCore.SurveyGroups(doc, instances, new HashSet<long> { FfrCore.Eid(srcRecord.SymbolId) }, out loose);
                    ReportAdd("warn", grouped + " element(s) are inside " + work.Count + " group type(s). Every one of the " +
                                      FfrCore.CountGroupInstances(work) + " instance(s) of those types will change, project wide, whatever the scope says.");
                }
                else if (grouped > 0)
                    ReportAdd("warn", grouped + " element(s) sit inside a group and will be left alone.");
                if (lineBased > 0)
                    ReportAdd("warn", lineBased + " element(s) are line based rather than point based and will be left alone.");
                BusyEnd();
                Text("ReportSummary").Text = "preview - nothing written";
                Status("Preview only - nothing has been changed.");
                FfrLog.Write("preview: " + instances.Count + " element(s); grouped " + grouped + ", line based " + lineBased + ", circuited " + circuited +
                             ", tags " + tagged + ", wire ends " + wireEnds + "; levels [" + Pairs(levels) + "]; parameters kept " + names.Count);
            });
        }

        /// <summary>What a drafting-view run will do, read without writing anything.</summary>
        private void PreviewDrafting(Document doc, List<Element> instances)
        {
            int total = instances.Count;
            var views = new Dictionary<long, string>();
            var routes = new Dictionary<string, int>();
            int rotated = 0, mirrored = 0, grouped = 0, noView = 0, tagged = 0;
            bool wantMirror = Ticked("MirrorCheck");
            bool wantTags = Ticked("TagsCheck");
            bool byCentre = Ticked("CentreAlignCheck");
            BusyStart("Checking...");
            try
            {
                int seen = 0;
                foreach (Element instance in instances)
                {
                    seen++;
                    SetProgress(seen, total, "Checking " + seen + " of " + total);
                    try
                    {
                        if (instance.GroupId != null && FfrCore.Eid(instance.GroupId) > 0)
                        {
                            grouped++;
                            continue;
                        }
                    }
                    catch (Exception)
                    {
                    }
                    View view = FfrCore.OwnerView(doc, instance);
                    if (view == null)
                    {
                        noView++;
                        continue;
                    }
                    views[FfrCore.Eid(view.Id)] = FfrCore.Name(view);
                    // measuring turns the symbol square for a moment, so it needs a transaction: always rolled back, and closed before the next repaint
                    FfrCore.ImportFrame frame = null;
                    var reading = new Transaction(doc, "RevoBIM read import symbol");
                    try
                    {
                        reading.Start();
                        frame = FfrCore.ReadImportFrame(doc, instance, view, byCentre);
                    }
                    finally
                    {
                        try
                        {
                            if (reading.HasStarted()) reading.RollBack();
                        }
                        catch (Exception)
                        {
                        }
                    }
                    if (frame == null) continue;
                    string route = byCentre ? frame.Route : frame.OriginRoute;
                    if (string.IsNullOrEmpty(route)) route = "not found";
                    FfrCore.Report.Bump(routes, route);
                    if (Math.Abs(frame.Angle) > 1.0e-6) rotated++;
                    if (frame.Mirrored) mirrored++;
                    tagged += FfrCore.TagsOn(doc, instance).Count;
                }
            }
            finally
            {
                BusyEnd();
            }

            ReportAdd("ok", total + " import symbol(s) of " + (srcRecord != null ? srcRecord.Label : "the picked symbol"));
            ReportAdd("ok", "become " + tgtRecord.Label + ", lined up " + (byCentre ? "middle to middle" : "insertion point to insertion point"));
            ReportViews(views);
            if (rotated > 0) ReportAdd("good", rotated + " are rotated in the drawing - each detail item is turned to match.");
            if (mirrored > 0)
            {
                if (wantMirror) ReportAdd("good", mirrored + " are mirrored - each detail item is mirrored to match.");
                else ReportAdd("warn", mirrored + " are mirrored and will NOT be matched - mirror to match is off.");
            }
            ReportCentreRoutes(routes, byCentre);
            if (tagged > 0)
                ReportAdd(wantTags ? "good" : "warn", tagged + " tag(s) will be " + (wantTags ? "moved onto the detail items" : "deleted with the imports - retain tags is off") + ".");
            List<string> names = RetainedNames();
            ReportAdd("muted", names.Count + " parameter(s) kept: " + (names.Count > 0 ? string.Join(", ", names) : "none"));
            if (grouped > 0) ReportAdd("warn", grouped + " import symbol(s) sit inside a detail group and will be left alone.");
            if (noView > 0) ReportAdd("warn", noView + " import(s) are not drawn in a view and will be left alone - a detail item needs a view to go in.");
            Text("ReportSummary").Text = "preview - nothing written";
            Status("Preview only - nothing has been changed.");
            FfrLog.Write("preview: drafting, " + total + " import symbol(s); rotated " + rotated + ", mirrored " + mirrored + ", grouped " + grouped +
                         ", no view " + noView + ", tags " + tagged + "; lined up by " + (byCentre ? "centre" : "insertion point") + " [" + Pairs(routes) + "]");
        }

        private void ReportViews(Dictionary<long, string> views)
        {
            if (views.Count == 0) return;
            List<string> names = views.Values.OrderBy(n => n.ToLowerInvariant(), StringComparer.Ordinal).ToList();
            string shown = string.Join(", ", names.Take(5));
            if (names.Count > 5) shown += " and " + (names.Count - 5) + " more";
            ReportAdd("muted", "In " + names.Count + " view(s): " + shown);
        }

        /// <summary>How each point was found, and a warning where it was a guess.</summary>
        private void ReportCentreRoutes(Dictionary<string, int> routes, bool byCentre)
        {
            if (routes.Count == 0) return;
            ReportAdd("muted", (byCentre ? "Centre measured from" : "Insertion point and rotation read from") + ": " + Pairs(routes));
            if (!byCentre)
            {
                int missing;
                if (routes.TryGetValue("not found", out missing) && missing > 0)
                    ReportAdd("warn", missing + " symbol(s) gave no placement to read and will be left alone.");
                return;
            }
            int fallback;
            if (routes.TryGetValue("insertion point", out fallback) && fallback > 0)
                ReportAdd("warn", fallback + " symbol(s) had no linework to measure, so their detail items land on the AutoCAD base point rather than the middle.");
        }

        private void ReportDrafting(FfrCore.Report report)
        {
            ReportViews(report.Views);
            if (report.Rotated > 0) ReportAdd("good", report.Rotated + " detail item(s) turned to match the symbol's rotation.");
            if (report.Mirrored > 0) ReportAdd("good", report.Mirrored + " detail item(s) mirrored to match blocks mirrored in AutoCAD.");
            if (report.MirrorFailed > 0) ReportAdd("warn", report.MirrorFailed + " mirrored symbol(s) were placed unmirrored - the detail item would not mirror.");
            if (report.CentreShifted > 0)
                ReportAdd("muted", report.CentreShifted + " detail item(s) are drawn off their own origin, so each was moved until its middle sat on the symbol's middle.");
            if (report.CentreCorrected > 0) ReportAdd("muted", report.CentreCorrected + " needed a second move after being checked, and were checked again.");
            if (report.RotationCorrected > 0) ReportAdd("muted", report.RotationCorrected + " needed a further turn after being checked.");
            string point = report.ByCentre ? "centre" : "insertion point";
            if (report.CentreUnverified > 0)
                ReportAdd("warn", report.CentreUnverified + " detail item(s) could not be confirmed on their symbol's " + point + " - each is named below. The debug log has the numbers.");
            else
            {
                int replaced = report.CentreRoutes.Values.Sum();
                if (replaced > 0)
                    ReportAdd("good", "All " + replaced + " checked after placing: each sits within 0.5mm of its symbol's " + point + (report.ByCentre ? "" : ", at its rotation") + ".");
            }
            ReportCentreRoutes(report.CentreRoutes, report.ByCentre);
            ReportAdd("muted", "Debug log: " + FfrCore.DebugPath());
        }

        private void Run()
        {
            Status("Replacing...");
            Post(app =>
            {
                UIDocument uidoc = app.ActiveUIDocument;
                Document doc = uidoc.Document;
                List<Element> instances = SourceInstances(doc, uidoc);
                if (instances.Count == 0)
                {
                    Status("Nothing to replace.");
                    return;
                }
                List<string> names = RetainedNames();
                bool levelBelow = Ticked("LevelBelowCheck");
                bool isDrafting = drafting;
                bool byCentre = isDrafting && Ticked("CentreAlignCheck");
                bool inGroups = Ticked("GroupsCheck") && !isDrafting;

                if (inGroups)
                {
                    FfrCore.ResetRunCaches();
                    List<Element> loose;
                    List<FfrCore.GroupWork> groupWork = FfrCore.SurveyGroups(doc, instances, new HashSet<long> { FfrCore.Eid(srcRecord.SymbolId) }, out loose);
                    int count = FfrCore.CountGroupInstances(groupWork);
                    if (count > GroupPromptThreshold)
                    {
                        bool yes = FfrUi.Ask("This element is within " + count + " groups.",
                                             "Are you sure? This could take some time.\n\nThose " + count + " group instance(s) share " + groupWork.Count +
                                             " group type(s). Each type has to be taken apart, changed and put back together, and every instance of it " +
                                             "changes with it - project wide, whatever the scope says.",
                                             "Yes", "Cancel", window);
                        if (!yes)
                        {
                            Status("Cancelled - nothing was changed.");
                            FfrLog.Write("run: cancelled at the group prompt (" + count + " group instance(s))");
                            return;
                        }
                    }
                }

                var options = new RunOptions
                {
                    RetainNames = names,
                    ZOffsetFt = 0.0,
                    MatchOrientation = true,
                    ExtraRadians = 0.0,
                    LevelBelowPoint = levelBelow,
                    RetainCircuits = retainCircuits,
                    RetainTags = Ticked("TagsCheck"),
                    RetainWires = Ticked("WiresCheck"),
                    ReplaceInGroups = inGroups,
                    Drafting = isDrafting,
                    MatchMirror = Ticked("MirrorCheck"),
                    ByCentre = byCentre,
                };
                FfrLog.Write("run: " + instances.Count + " of " + srcRecord.Label + " -> " + tgtRecord.Label + " (" + (probe != null ? probe.Placement : "?") +
                             "); scope " + ScopeLabel() + "; drafting " + isDrafting + ", by centre " + byCentre + ", level below " + levelBelow +
                             ", circuits " + retainCircuits + ", tags " + options.RetainTags + ", wires " + options.RetainWires + ", groups " + inGroups +
                             ", mirror " + options.MatchMirror + "; parameters [" + string.Join(", ", names) + "]");

                FfrCore.Report report;
                var timer = System.Diagnostics.Stopwatch.StartNew();
                BusyStart("Replacing...");
                try
                {
                    report = FfrCore.ReplaceAll(doc, uidoc, instances, tgtRecord.SymbolId, options, SetProgress);
                }
                finally
                {
                    BusyEnd();
                }
                timer.Stop();
                lastDrafting = isDrafting;
                lastByCentre = byCentre;

                ReportClear();
                ReportAdd("good", report.Replaced + " of " + instances.Count + " element(s) replaced with " + tgtRecord.Label + ".");
                if (names.Count > 0) ReportAdd("muted", names.Count + " parameter(s) carried across: " + string.Join(", ", names));
                if (report.CircuitsKept > 0) ReportAdd("good", report.CircuitsKept + " circuit connection(s) kept.");
                if (report.TagsKept > 0) ReportAdd("good", report.TagsKept + " tag(s) moved onto the replacements.");
                if (report.WiresKept > 0) ReportAdd("good", report.WiresKept + " wire end(s) reconnected.");
                if (report.CircuitsDropped > 0) ReportAdd("fail", report.CircuitsDropped + " circuit(s) dropped - circuits retained was off.");
                if (report.LevelsSet.Count > 0)
                    ReportAdd("muted", "Associated with " + (levelBelow ? "the nearest level below" : "the original's own level") + ": " + Pairs(report.LevelsSet));
                if (report.Routes.Count > 0) ReportAdd("muted", "Placed by: " + Pairs(report.Routes));
                if (report.Pinned > 0)
                    ReportAdd("muted", report.Pinned + " replacement(s) pinned, matching the original. The adjust window releases the pin to move them.");
                if (isDrafting) ReportDrafting(report);
                foreach (KeyValuePair<string, string> line in report.Lines) ReportAdd(line.Key, line.Value);

                int failures = report.Lines.Count(l => l.Key == "fail");
                Text("ReportSummary").Text = report.Replaced + " replaced, " + failures + " left alone";
                lastNewIds = report.NewIds;
                FfrCore.SelectElements(uidoc, report.NewIds);
                Status(report.Replaced + " replaced. " + (isDrafting ? "Fine-tune the rotation in the adjust window." : "Set the orientation and height in the adjust window."));

                // the run's own lines for the log: every warning and failure by kind, then the drafting detail
                FfrLog.Write("result: replaced " + report.Replaced + " of " + instances.Count + " in " + (timer.ElapsedMilliseconds / 1000.0).ToString("0.0", CultureInfo.InvariantCulture) +
                             "s; circuits kept " + report.CircuitsKept + ", dropped " + report.CircuitsDropped + ", tags " + report.TagsKept + ", wires " + report.WiresKept +
                             ", pinned " + report.Pinned + ", groups done " + report.GroupsDone + "/failed " + report.GroupsFailed + "; placed by [" + Pairs(report.Routes) +
                             "]; levels [" + Pairs(report.LevelsSet) + "]");
                foreach (KeyValuePair<string, string> line in report.Lines) FfrLog.Write("report " + line.Key + ": " + line.Value);
                if (report.Debug.Count > 0)
                {
                    FfrLog.Write("drafting: " + instances.Count + " import symbol(s) to " + tgtRecord.Label + ", lined up by " + (byCentre ? "centre" : "insertion point") +
                                 "; moved after checking " + report.CentreCorrected + ", turned after checking " + report.RotationCorrected + ", unverified " + report.CentreUnverified);
                    FfrLog.WriteLines(report.Debug);
                }

                RefreshSource();
                UpdateRun();

                // only after a run that took groups apart: an ordinary run reports in the window and does not make you dismiss anything
                if (inGroups && (report.GroupsDone > 0 || report.GroupsFailed > 0)) GroupSummary(report, instances.Count, failures);

                if (report.NewIds.Count > 0) OpenAdjust();
            });
        }

        private void GroupSummary(FfrCore.Report report, int attempted, int failures)
        {
            int done = report.GroupsDone, failed = report.GroupsFailed;
            string headline = done + " of " + (done + failed) + " group instance(s) updated.";
            var body = new List<string> { report.Replaced + " of " + attempted + " element(s) were replaced in total." };
            if (failed > 0)
            {
                body.Add(failed + " group instance(s) were left exactly as they were. Each one is named in the report with the reason.");
                List<string> names = report.Lines.Where(l => l.Key == "fail" && l.Value.StartsWith("Group ", StringComparison.Ordinal)).Select(l => l.Value).ToList();
                if (names.Count > 0)
                {
                    body.Add("");
                    body.AddRange(names.Take(6));
                    if (names.Count > 6) body.Add("...and " + (names.Count - 6) + " more.");
                }
            }
            else body.Add("None were left behind.");
            if (failures > 0 && failed == 0) body.Add(failures + " other element(s) outside groups were left alone - see the report.");
            FfrUi.Tell(headline, string.Join("\n", body), window);
        }

        private void OpenAdjust()
        {
            try
            {
                if (adjust != null) adjust.Window.Close();
            }
            catch (Exception)
            {
            }
            adjust = new FfrAdjustWindow(window, handler, externalEvent, lastNewIds, lastDrafting, lastByCentre);
            adjust.Show();
        }
    }
}
