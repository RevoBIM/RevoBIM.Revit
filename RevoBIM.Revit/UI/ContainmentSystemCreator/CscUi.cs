using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Media;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Electrical;
using Autodesk.Revit.UI;
using RevoBIM.Helpers;
using RevoBIM.Tools.ContainmentSystemCreator;

using Button = System.Windows.Controls.Button;
using Color = System.Windows.Media.Color;
using Panel = System.Windows.Controls.Panel;
using CheckBox = System.Windows.Controls.CheckBox;
using ComboBox = System.Windows.Controls.ComboBox;
using Control = System.Windows.Controls.Control;
using Orientation = System.Windows.Controls.Orientation;
using TextBox = System.Windows.Controls.TextBox;
using Visibility = System.Windows.Visibility;

namespace RevoBIM.UI.ContainmentSystemCreator
{
    /// <summary>
    /// Base of every window of the tool (the layouts are self-contained and dark only): loads the layout with its handlers
    /// wired by name, puts the icon and version in the header, and gives the window the shrink-to-taskbar drawer.
    /// Esc closes an open window; while parked it brings the window back (pyRevit's own Esc handler is not used).
    /// </summary>
    internal abstract class CscWindowBase
    {
        public static readonly ChromeConfig Config = new ChromeConfig
        {
            IconResource = "RevoBIM.Resources.ContainmentSystemCreator.icon.png",
            Version = CscCore.Version,
            Log = CscLog.Write,
        };

        protected static readonly SolidColorBrush Blue = Brush(79, 163, 227);
        protected static readonly SolidColorBrush Orange = Brush(232, 145, 45);
        protected static readonly SolidColorBrush Grey = Brush(157, 164, 178);
        protected static readonly SolidColorBrush White = Brush(232, 240, 248);
        protected static readonly SolidColorBrush Red = Brush(217, 83, 79);
        protected static readonly SolidColorBrush Green = Brush(78, 192, 109);

        private static SolidColorBrush Brush(byte r, byte g, byte b)
        {
            var brush = new SolidColorBrush(Color.FromRgb(r, g, b));
            brush.Freeze();
            return brush;
        }

        public Window Win;
        public WindowDrawer Drawer;

        protected void Init(string layout, Dictionary<string, Action<object, EventArgs>> handlers, bool egg = false)
        {
            handlers["drag_window"] = (s, a) => HeaderDown((MouseButtonEventArgs)a);
            Win = XamlLoader.Load<Window>("RevoBIM.UI.ContainmentSystemCreator.Layouts." + layout, handlers);
            var header = (FrameworkElement)Win.FindName("header_bar");
            Drawer = new WindowDrawer(Config, Win, header, (FrameworkElement)Win.Content, Win.FindName("shrink_btn") as Button,
                                      (UIElement)Win.FindName("shrink_glyph"), (UIElement)Win.FindName("expand_glyph"), null,
                                      WindowDrawer.ChildrenOf(header.Parent as Panel, header, null));
            var icon = Win.FindName("app_icon") as Image;
            ThemedWindow.LoadIcon(icon, Config.IconResource);
            if (egg) EggHook.Attach(Win, () => "dark", icon);
            var version = Win.FindName("version_text") as TextBlock;
            if (version != null) version.Text = "v" + CscCore.Version;
            Win.PreviewKeyDown += OnKey;
        }

        private void HeaderDown(MouseButtonEventArgs args)
        {
            try
            {
                if (args.ClickCount >= 2)
                {
                    if (Drawer.OnHeaderDoubleClick()) args.Handled = true;
                    return;
                }
                if (Drawer.CanDrag()) Win.DragMove();
            }
            catch (Exception)
            {
            }
        }

        private void OnKey(object sender, KeyEventArgs args)
        {
            try
            {
                Key key = args.Key == Key.System ? args.SystemKey : args.Key;
                if (Drawer.OnKey(key, RevoChrome.CtrlDown(), RevoChrome.ShiftDown()))
                {
                    args.Handled = true;
                    return;
                }
                if (key == Key.Escape)
                {
                    args.Handled = true;
                    Win.Close();
                }
            }
            catch (Exception)
            {
            }
        }

        protected T F<T>(string name) where T : class
        {
            return Win.FindName(name) as T;
        }

        protected static TextBlock TextBlockOf(string text, Brush brush = null, bool bold = false, double size = 12, double left = 0)
        {
            var block = new TextBlock { Text = text, Foreground = brush ?? White, FontSize = size, VerticalAlignment = VerticalAlignment.Center };
            if (bold) block.FontWeight = FontWeights.SemiBold;
            if (left != 0) block.Margin = new Thickness(left, 0, 0, 0);
            return block;
        }

        /// <summary>Parents a child window and links the drawers so the two go down and come back together.</summary>
        public void Adopt(CscWindowBase child)
        {
            try
            {
                child.Win.Owner = Win;
            }
            catch (Exception)
            {
            }
            try
            {
                child.Drawer.SetOwner(Drawer);
            }
            catch (Exception)
            {
            }
        }

        public void ShowDialog()
        {
            Win.ShowDialog();
        }
    }

    internal sealed class CscResultsDialog : CscWindowBase
    {
        public CscResultsDialog(string title, string headline, string body, bool ok = true)
        {
            Init("ResultsDialog.xaml", new Dictionary<string, Action<object, EventArgs>> { { "ok_clicked", (s, a) => Win.Close() } });
            F<TextBlock>("dialog_title").Text = title;
            var head = F<TextBlock>("headline");
            head.Text = headline;
            head.Foreground = ok ? Green : Red;
            F<TextBlock>("body").Text = body;
        }
    }

    /// <summary>Collects the new service definition and previews the result.</summary>
    internal sealed class CscCreateDialog : CscWindowBase
    {
        private readonly Document doc;
        private readonly Type cls;
        private readonly List<SystemTypeInfo> allTypes;
        private readonly int autoDepth;
        private readonly HashSet<string> existingNames;
        private bool loading = true;
        private bool functionTouched, markTouched, fullnameTouched;

        public Plan Plan;
        public bool Created;
        public bool Ok = true;
        public string Summary;
        public bool ShowSummary = true;

        public CscCreateDialog(Document doc, Type cls, string label, List<Kind> kinds, List<SystemTypeInfo> allTypes, int autoDepth)
        {
            this.doc = doc;
            this.cls = cls;
            this.allTypes = allTypes;
            this.autoDepth = autoDepth;
            existingNames = CscModel.ExistingSystemTypeNames(doc, cls);
            Init("CreateSystemDialog.xaml", new Dictionary<string, Action<object, EventArgs>>
            {
                { "kind_changed", (s, a) => ReloadSources() },
                { "source_changed", (s, a) => RefreshPreview() },
                { "source_changed_evt", (s, a) => RefreshPreview() },
                { "name_changed", (s, a) => NameChanged() },
                { "mirror_edited", (s, a) => MirrorEdited(s) },
                { "fullname_edited", (s, a) => FullnameEdited() },
                { "reset_fullname", (s, a) =>
                    {
                        fullnameTouched = false;
                        RefreshPreview();
                    } },
                { "cancel_clicked", (s, a) =>
                    {
                        Created = false;
                        Win.Close();
                    } },
                { "create_clicked", (s, a) => CreateClicked() },
            });
            F<TextBlock>("dialog_title").Text = "New " + label + " System";

            Dictionary<string, int> counts;
            int unassigned;
            List<Kind> present = CscModel.KindsPresent(allTypes, kinds, out counts, out unassigned);
            var cmbKind = F<ComboBox>("cmb_kind");
            foreach (Kind kind in present)
            {
                int c;
                counts.TryGetValue(kind.Label, out c);
                cmbKind.Items.Add(new ComboBoxItem { Content = kind.Label + "   (" + c + ")", Tag = kind });
            }
            cmbKind.Items.Add(new ComboBoxItem
            {
                Content = unassigned > 0 ? CscCore.Unfiltered + "   (" + allTypes.Count + ", " + unassigned + " unmatched)" : CscCore.Unfiltered + "   (" + allTypes.Count + ")",
                Tag = null,
            });
            var cmbFit = F<ComboBox>("cmb_fitname");
            foreach (var scheme in CscCore.FitSchemes) cmbFit.Items.Add(new ComboBoxItem { Content = scheme.Key, Tag = scheme.Value });
            cmbFit.SelectedIndex = 0;
            cmbKind.SelectedIndex = 0;
            loading = false;
            ReloadSources();
        }

        private Kind SelectedKind()
        {
            var item = F<ComboBox>("cmb_kind").SelectedItem as ComboBoxItem;
            return item == null ? null : item.Tag as Kind;
        }

        private string SelectedScheme()
        {
            var item = F<ComboBox>("cmb_fitname").SelectedItem as ComboBoxItem;
            return item == null ? "full" : (string)item.Tag;
        }

        private SystemTypeInfo SelectedSource()
        {
            var item = F<ComboBox>("cmb_source").SelectedItem as ComboBoxItem;
            return item == null ? null : item.Tag as SystemTypeInfo;
        }

        private void ReloadSources()
        {
            if (loading) return;
            loading = true;
            var cmb = F<ComboBox>("cmb_source");
            cmb.Items.Clear();
            List<SystemTypeInfo> matches = CscModel.TypesForKind(allTypes, SelectedKind());
            foreach (SystemTypeInfo info in matches)
            {
                string text = info.FamilyName.Length > 0
                    ? info.Name + "      [" + info.FamilyName + "]   (" + info.Slots.Count + " fittings)"
                    : info.Name + "   (" + info.Slots.Count + " fittings)";
                cmb.Items.Add(new ComboBoxItem { Content = text, Tag = info });
            }
            if (matches.Count > 0) cmb.SelectedIndex = 0;
            loading = false;
            RefreshPreview();
        }

        private void NameChanged()
        {
            if (loading) return;
            string value = F<TextBox>("txt_name").Text;
            // mirror the name into the two parameter boxes until the user edits them
            if (!functionTouched)
            {
                loading = true;
                F<TextBox>("txt_function").Text = value;
                loading = false;
            }
            if (!markTouched)
            {
                loading = true;
                F<TextBox>("txt_mark").Text = value;
                loading = false;
            }
            RefreshPreview();
        }

        private void MirrorEdited(object sender)
        {
            if (loading) return;
            if (ReferenceEquals(sender, F<TextBox>("txt_function"))) functionTouched = true;
            else if (ReferenceEquals(sender, F<TextBox>("txt_mark"))) markTouched = true;
            RefreshPreview();
        }

        private void FullnameEdited()
        {
            if (loading) return;
            fullnameTouched = F<TextBox>("txt_fullname").Text.Trim().Length > 0;
            RefreshPreview();
        }

        private void RefreshPreview()
        {
            if (loading) return;
            SystemTypeInfo source = SelectedSource();
            string over = fullnameTouched ? F<TextBox>("txt_fullname").Text : null;
            Plan plan = CscModel.BuildPlan(doc, cls, source, autoDepth, F<TextBox>("txt_name").Text, F<TextBox>("txt_function").Text,
                                           F<TextBox>("txt_mark").Text, SelectedScheme(), F<CheckBox>("chk_params_on_fittings").IsChecked == true,
                                           existingNames, over);
            Plan = plan;
            if (!fullnameTouched)
            {
                loading = true;
                F<TextBox>("txt_fullname").Text = plan.NewTypeName;
                loading = false;
            }
            if (source == null)
            {
                F<TextBlock>("preview_head").Text = "";
                F<TextBlock>("preview_body").Text = "No source type found for this kind.";
            }
            else
            {
                F<TextBlock>("preview_head").Text = source.Name + "\n   ->  " + (plan.NewTypeName.Length > 0 ? plan.NewTypeName : "...");
                var lines = new List<string>();
                lines.Add("Source family: " + (source.FamilyName.Length > 0 ? source.FamilyName : "(none)"));
                if (source.KindLabel.Length > 0)
                {
                    if (source.NameAlias != null) lines.Add("Kind         : " + source.KindLabel + "   (from the type name)");
                    else lines.Add("Kind         : " + source.KindLabel + "   (from the family naming - check the name above)");
                }
                lines.Add("");
                lines.Add(source.FunctionParamName + " = " + F<TextBox>("txt_function").Text);
                lines.Add(source.MarkParamName + " = " + F<TextBox>("txt_mark").Text);
                lines.Add("");
                lines.Add(plan.Items.Count + " fitting type(s) will be created:");
                foreach (PlanItem item in plan.Items)
                {
                    lines.Add("   " + item.Slot.Name);
                    lines.Add("      " + item.Slot.FamilyName + " : " + item.Slot.TypeName);
                    string arrow = item.Reused ? "      =  " : "      -> ";
                    string suffix = item.Reused ? "   (existing, reused)" : "";
                    lines.Add(arrow + item.Slot.FamilyName + " : " + item.NewTypeName + suffix);
                }
                foreach (string note in plan.Notes)
                {
                    lines.Add("");
                    lines.Add(note);
                }
                F<TextBlock>("preview_body").Text = string.Join("\n", lines);
            }
            if (plan.Errors.Count > 0)
            {
                F<TextBlock>("warn_text").Text = plan.Errors[0];
                F<Button>("btn_create").IsEnabled = false;
            }
            else
            {
                F<TextBlock>("warn_text").Text = "";
                F<Button>("btn_create").IsEnabled = plan.Items.Count > 0;
            }
        }

        private void CreateClicked()
        {
            RefreshPreview();
            if (Plan == null || Plan.Errors.Count > 0) return;
            List<string> log;
            bool ok = CscModel.ExecutePlan(doc, Plan, out log);
            CscLog.Write("create " + Plan.NewTypeName + " from " + Plan.Source.Name + ": " + (ok ? "ok" : "rolled back") + "; " + Plan.Items.Count + " fitting(s)");
            Created = ok;
            Summary = string.Join("\n", log);
            ShowSummary = F<CheckBox>("chk_select_after").IsChecked == true;
            Ok = ok;
            Win.Close();
        }
    }

    /// <summary>
    /// Edits an existing system's service name and its two parameters, across the system type and every fitting type in its
    /// routing preferences.
    /// </summary>
    internal sealed class CscEditDialog : CscWindowBase
    {
        private readonly Document doc;
        private readonly Type cls;
        private readonly SystemTypeInfo info;
        private readonly int autoDepth;
        private readonly HashSet<string> existingNames;
        private bool loading = true;

        public EditPlan Plan;
        public bool Applied;
        public bool Ok = true;
        public string Summary;

        public CscEditDialog(Document doc, Type cls, SystemTypeInfo info, int autoDepth)
        {
            this.doc = doc;
            this.cls = cls;
            this.info = info;
            this.autoDepth = autoDepth;
            existingNames = CscModel.ExistingSystemTypeNames(doc, cls);
            Init("EditSystemDialog.xaml", new Dictionary<string, Action<object, EventArgs>>
            {
                { "field_changed", (s, a) => RefreshPreview() },
                { "cancel_clicked", (s, a) =>
                    {
                        Applied = false;
                        Win.Close();
                    } },
                { "apply_clicked", (s, a) => ApplyClicked() },
            });
            string prefix, sep;
            CscCore.EditSplit(info.Name, info.NameAlias, autoDepth, out prefix, out sep);
            F<TextBlock>("prefix_text").Text = prefix.Length > 0 ? prefix + sep : "(whole name)";
            F<TextBlock>("subject_name").Text = info.Name;
            var bits = new List<string>();
            if (info.KindLabel.Length > 0) bits.Add(info.KindLabel);
            if (info.FamilyName.Length > 0) bits.Add(info.FamilyName);
            bits.Add(info.Slots.Count + " fitting type(s) in the routing preferences");
            F<TextBlock>("subject_meta").Text = string.Join("   |   ", bits);
            F<TextBox>("txt_token").Text = CscCore.ServiceToken(info.Name, prefix, sep);
            F<TextBox>("txt_function").Text = info.Function;
            F<TextBox>("txt_mark").Text = info.Mark;
            loading = false;
            RefreshPreview();
        }

        private void RefreshPreview()
        {
            if (loading) return;
            EditPlan plan = CscModel.BuildEditPlan(doc, cls, info, autoDepth, F<TextBox>("txt_token").Text, F<TextBox>("txt_function").Text,
                                                   F<TextBox>("txt_mark").Text, F<CheckBox>("chk_rename_fittings").IsChecked == true,
                                                   F<CheckBox>("chk_params_on_fittings").IsChecked == true, existingNames);
            Plan = plan;
            F<TextBlock>("preview_head").Text = info.Name + "\n   ->  " + (plan.NewFullName.Length > 0 ? plan.NewFullName : "...");
            var lines = new List<string>();
            lines.Add(plan.FunctionParamName + " = " + F<TextBox>("txt_function").Text);
            lines.Add(plan.MarkParamName + " = " + F<TextBox>("txt_mark").Text);
            lines.Add("");
            List<RenameItem> changing = plan.Renaming;
            lines.Add(changing.Count > 0 ? changing.Count + " type name(s) will change:" : "No type names will change.");
            foreach (RenameItem item in plan.Renames)
            {
                lines.Add("   " + item.SlotName);
                lines.Add("      " + item.OldName);
                if (!string.IsNullOrEmpty(item.Note)) lines.Add("      !  " + item.Note);
                else if (item.Changes) lines.Add("      -> " + item.NewName);
                else lines.Add("      =  unchanged");
            }
            lines.Add("");
            lines.Add("Parameters will be written to " + plan.ParamTargets.Count + " element(s).");
            foreach (string note in plan.Notes)
            {
                lines.Add("");
                lines.Add(note);
            }
            F<TextBlock>("preview_body").Text = string.Join("\n", lines);
            if (plan.Errors.Count > 0)
            {
                F<TextBlock>("warn_text").Text = plan.Errors[0];
                F<Button>("btn_apply").IsEnabled = false;
            }
            else
            {
                F<TextBlock>("warn_text").Text = "";
                F<Button>("btn_apply").IsEnabled = true;
            }
        }

        private void ApplyClicked()
        {
            RefreshPreview();
            if (Plan == null || Plan.Errors.Count > 0) return;
            List<string> log;
            bool ok = CscModel.ExecuteEdit(doc, Plan, out log);
            CscLog.Write("edit " + info.Name + " -> " + Plan.NewFullName + ": " + (ok ? "ok" : "rolled back") + "; " + Plan.Renaming.Count + " rename(s)");
            Applied = ok;
            Ok = ok;
            Summary = string.Join("\n", log);
            Win.Close();
        }
    }

    /// <summary>The main window: every containment service type in the model, with the fitting types each one uses.</summary>
    internal sealed class CscWindow : CscWindowBase
    {
        private sealed class Selection
        {
            public SystemTypeInfo Info;
            public Type Cls;
            public int Depth;
        }

        private readonly Document doc;
        private Selection selection;
        private bool syncing;
        private List<Kind> trayKinds, conduitKinds;
        private List<SystemTypeInfo> trayTypes, conduitTypes;
        private int trayDepth, conduitDepth;

        public CscWindow(Document doc, UIApplication uiapp)
        {
            this.doc = doc;
            Init("ContainmentSystemCreator.xaml", new Dictionary<string, Action<object, EventArgs>>
            {
                { "close_window", (s, a) => Win.Close() },
                { "tray_search_changed", (s, a) => TraySearchChanged() },
                { "conduit_search_changed", (s, a) => ConduitSearchChanged() },
                { "refresh_clicked", (s, a) =>
                    {
                        LoadModel();
                        F<TextBlock>("status_text").Foreground = Grey;
                        F<TextBlock>("status_text").Text = "Reloaded from the model.";
                    } },
                { "tray_selected", (s, a) => NoteSelection(F<TreeView>("tray_tree"), F<TreeView>("conduit_tree"), typeof(CableTrayType), trayDepth) },
                { "conduit_selected", (s, a) => NoteSelection(F<TreeView>("conduit_tree"), F<TreeView>("tray_tree"), typeof(ConduitType), conduitDepth) },
                { "edit_selected", (s, a) => EditSelected() },
                { "create_tray_system", (s, a) => RunCreator(typeof(CableTrayType), "Cable Tray", trayKinds, trayTypes, trayDepth) },
                { "create_conduit_system", (s, a) => RunCreator(typeof(ConduitType), "Conduit", conduitKinds, conduitTypes, conduitDepth) },
            }, egg: true);
            try
            {
                new WindowInteropHelper(Win).Owner = uiapp.MainWindowHandle;
            }
            catch (Exception)
            {
            }
            LoadModel();
        }

        private void LoadModel()
        {
            CscModel.ResetCategories(doc);
            // cable tray kinds are the four the model uses; conduit kinds are whatever the conduit type naming actually contains
            trayKinds = CscCore.TrayKinds();
            trayTypes = CscModel.CollectSystemTypes(doc, typeof(CableTrayType), trayKinds);
            List<SystemTypeInfo> provisional = CscModel.CollectSystemTypes(doc, typeof(ConduitType), new List<Kind>());
            List<string> conduitTokens = CscCore.DetectKinds(provisional.Select(t => t.Name).ToList(), out conduitDepth);
            if (conduitTokens.Count == 0) conduitTokens = new List<string> { "Conduit" };
            conduitKinds = conduitTokens.Select(t => new Kind(t)).ToList();
            conduitTypes = provisional;
            CscModel.TagKinds(conduitTypes, conduitKinds);
            CscCore.DetectKinds(trayTypes.Select(t => t.Name).ToList(), out trayDepth);

            FillTree(F<TreeView>("tray_tree"), trayTypes, F<TextBox>("tray_search").Text);
            FillTree(F<TreeView>("conduit_tree"), conduitTypes, F<TextBox>("conduit_search").Text);
            F<TextBlock>("tray_count").Text = trayTypes.Count + " cable tray type(s), " + trayTypes.Sum(t => t.Slots.Count) + " fitting assignment(s)";
            F<TextBlock>("conduit_count").Text = conduitTypes.Count + " conduit type(s), " + conduitTypes.Sum(t => t.Slots.Count) + " fitting assignment(s)";
            F<Button>("btn_tray_top").IsEnabled = trayTypes.Count > 0;
            F<Button>("btn_tray_bottom").IsEnabled = trayTypes.Count > 0;
            F<Button>("btn_conduit_top").IsEnabled = conduitTypes.Count > 0;
            F<Button>("btn_conduit_bottom").IsEnabled = conduitTypes.Count > 0;
            ClearSelection();
            CscLog.Write("model: " + trayTypes.Count + " cable tray type(s), " + conduitTypes.Count + " conduit type(s); conduit kinds [" +
                         string.Join(", ", conduitKinds.Select(k => k.Label)) + "]");
        }

        private void FillTree(TreeView tree, List<SystemTypeInfo> infos, string filterText)
        {
            tree.Items.Clear();
            string needle = (filterText ?? "").Trim().ToLowerInvariant();
            foreach (SystemTypeInfo info in infos)
            {
                if (needle.Length > 0 && !info.SearchBlob().Contains(needle)) continue;
                var node = new TreeViewItem { Tag = info };
                var head = new StackPanel { Orientation = Orientation.Horizontal };
                head.Children.Add(TextBlockOf(info.Name, White, true, 12));
                if (info.KindLabel.Length > 0) head.Children.Add(TextBlockOf(info.KindLabel, Green, false, 11, 14));
                if (info.FamilyName.Length > 0) head.Children.Add(TextBlockOf("[" + info.FamilyName + "]", Grey, false, 11, 14));
                if (info.Function.Length > 0) head.Children.Add(TextBlockOf(info.FunctionParamName + ": " + info.Function, Blue, false, 11, 14));
                if (info.Mark.Length > 0) head.Children.Add(TextBlockOf(info.MarkParamName + ": " + info.Mark, Orange, false, 11, 14));
                head.Children.Add(TextBlockOf(info.Slots.Count + " fittings", Grey, false, 11, 14));
                node.Header = head;
                foreach (FittingSlot slot in info.Slots)
                {
                    var child = new TreeViewItem { Tag = info };   // picking a fitting selects its system
                    var row = new StackPanel { Orientation = Orientation.Horizontal };
                    var label = TextBlockOf(slot.Name, Grey, false, 11);
                    label.MinWidth = 150;
                    row.Children.Add(label);
                    row.Children.Add(TextBlockOf(slot.Label(), White, false, 11, 8));
                    child.Header = row;
                    node.Items.Add(child);
                }
                tree.Items.Add(node);
            }
        }

        private void TraySearchChanged()
        {
            F<TextBlock>("tray_search_hint").Visibility = F<TextBox>("tray_search").Text.Length == 0 ? Visibility.Visible : Visibility.Collapsed;
            FillTree(F<TreeView>("tray_tree"), trayTypes, F<TextBox>("tray_search").Text);
        }

        private void ConduitSearchChanged()
        {
            F<TextBlock>("conduit_search_hint").Visibility = F<TextBox>("conduit_search").Text.Length == 0 ? Visibility.Visible : Visibility.Collapsed;
            FillTree(F<TreeView>("conduit_tree"), conduitTypes, F<TextBox>("conduit_search").Text);
        }

        private void ClearSelection()
        {
            selection = null;
            F<Button>("btn_edit").IsEnabled = false;
            F<Button>("btn_edit").Content = "Edit System Parameters";
        }

        private void NoteSelection(TreeView tree, TreeView other, Type cls, int depth)
        {
            if (syncing) return;
            var item = tree.SelectedItem as TreeViewItem;
            var info = item == null ? null : item.Tag as SystemTypeInfo;
            if (info == null) return;
            // only one of the two trees holds the selection at a time
            syncing = true;
            try
            {
                var stale = other.SelectedItem as TreeViewItem;
                if (stale != null)
                {
                    try
                    {
                        stale.IsSelected = false;
                    }
                    catch (Exception)
                    {
                    }
                }
            }
            finally
            {
                syncing = false;
            }
            selection = new Selection { Info = info, Cls = cls, Depth = depth };
            F<Button>("btn_edit").IsEnabled = true;
            F<Button>("btn_edit").Content = "Edit System Parameters";
            F<TextBlock>("status_text").Foreground = Grey;
            F<TextBlock>("status_text").Text = "Selected \"" + info.Name + "\"";
        }

        private void EditSelected()
        {
            if (selection == null) return;
            var dialog = new CscEditDialog(doc, selection.Cls, selection.Info, selection.Depth);
            Adopt(dialog);
            dialog.ShowDialog();
            if (!dialog.Applied)
            {
                if (!string.IsNullOrEmpty(dialog.Summary) && !dialog.Ok)
                {
                    var failed = new CscResultsDialog("Nothing Changed", "The system could not be updated.", dialog.Summary, false);
                    Adopt(failed);
                    failed.ShowDialog();
                }
                return;
            }
            string name = dialog.Plan.NewFullName;
            LoadModel();
            F<TextBlock>("status_text").Foreground = Green;
            F<TextBlock>("status_text").Text = "Updated \"" + name + "\".";
            var result = new CscResultsDialog("System Updated", "\"" + name + "\" and its fittings are up to date.", dialog.Summary ?? "", true);
            Adopt(result);
            result.ShowDialog();
        }

        private void RunCreator(Type cls, string label, List<Kind> kinds, List<SystemTypeInfo> allTypes, int autoDepth)
        {
            if (allTypes.Count == 0)
            {
                F<TextBlock>("status_text").Text = "No '" + label + " with Fittings' types found in this model.";
                F<TextBlock>("status_text").Foreground = Red;
                return;
            }
            var dialog = new CscCreateDialog(doc, cls, label, kinds, allTypes, autoDepth);
            Adopt(dialog);
            dialog.ShowDialog();
            if (!dialog.Created)
            {
                if (!string.IsNullOrEmpty(dialog.Summary) && !dialog.Ok)
                {
                    var failed = new CscResultsDialog("System Not Created", "The system could not be created.", dialog.Summary, false);
                    Adopt(failed);
                    failed.ShowDialog();
                }
                return;
            }
            string name = dialog.Plan.NewTypeName;
            LoadModel();
            F<TextBlock>("status_text").Text = "Created \"" + name + "\".";
            F<TextBlock>("status_text").Foreground = Green;
            if (dialog.ShowSummary)
            {
                var result = new CscResultsDialog("System Created", "\"" + name + "\" is ready to use.", dialog.Summary ?? "", true);
                Adopt(result);
                result.ShowDialog();
            }
        }
    }
}
