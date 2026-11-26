using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using Autodesk.Revit.UI;
using RevoBIM.Tools.FamilyThumbnail;

using Button = System.Windows.Controls.Button;
using CheckBox = System.Windows.Controls.CheckBox;
using ComboBox = System.Windows.Controls.ComboBox;
using Grid = System.Windows.Controls.Grid;
using RadioButton = System.Windows.Controls.RadioButton;
using TextBox = System.Windows.Controls.TextBox;
using Color = System.Windows.Media.Color;
using Point = System.Windows.Point;
using HorizontalAlignment = System.Windows.HorizontalAlignment;

namespace RevoBIM.UI.FamilyThumbnail
{
    /// <summary>The Settings window: appearance by family kind and category, view options, export folder and gradient background. Port of SettingsWindow in ft_ui.py.</summary>
    internal sealed class FtSettingsWindow : FtChromeWindow
    {
        private sealed class CheckBinding
        {
            public string Name;
            public Func<FtSettings, bool> Get;
            public Action<FtSettings, bool> Set;
        }

        private static CheckBinding C(string name, Func<FtSettings, bool> get, Action<FtSettings, bool> set)
        {
            return new CheckBinding { Name = name, Get = get, Set = set };
        }

        private static readonly CheckBinding[] Checkboxes =
        {
            C("cbLock", s => s.LockOrientation, (s, v) => s.LockOrientation = v),
            C("cbHideDim", s => s.HideDimensions, (s, v) => s.HideDimensions = v),
            C("cbHideRefPts", s => s.HideRefPoints, (s, v) => s.HideRefPoints = v),
            C("cbHideRefLines", s => s.HideRefLines, (s, v) => s.HideRefLines = v),
            C("cbHideRefPlanes", s => s.HideRefPlanes, (s, v) => s.HideRefPlanes = v),
            C("cbHideText", s => s.HideTextNotes, (s, v) => s.HideTextNotes = v),
            C("cbHideInvisible", s => s.HideInvisibleLines, (s, v) => s.HideInvisibleLines = v),
            C("cbHideFlip", s => s.HideFlipControls, (s, v) => s.HideFlipControls = v),
            C("cbHideRoomPts", s => s.HideRoomCalcPoints, (s, v) => s.HideRoomCalcPoints = v),
            C("cbHideHost", s => s.HideHost, (s, v) => s.HideHost = v),
            C("cbHideConn", s => s.HideConnectors, (s, v) => s.HideConnectors = v),
            C("cbHideVoid", s => s.HideVoids, (s, v) => s.HideVoids = v),
            C("cbHideImported", s => s.HideImported, (s, v) => s.HideImported = v),
            C("cbExport", s => s.ExportImages, (s, v) => s.ExportImages = v),
            C("cbPrompt", s => s.PromptOpen, (s, v) => s.PromptOpen = v),
            C("cbFillParams", s => s.FillParams, (s, v) => s.FillParams = v),
            C("cbCategoryFolders", s => s.CategoryFolders, (s, v) => s.CategoryFolders = v),
            C("cbLeave", s => s.LeaveOpen, (s, v) => s.LeaveOpen = v),
            C("cbGradient", s => s.Gradient, (s, v) => s.Gradient = v),
        };

        private static readonly string[][] ColourFields =
        {
            new[] { "tbSky", "swSky" }, new[] { "tbHorizon", "swHorizon" }, new[] { "tbGround", "swGround" },
        };

        private static readonly string[] ParamCombos = { "cbParamCreator", "cbParamRevision", "cbParamDate" };
        private static readonly double[] OverrideWidths = { 210, 200, 160, 100, 86 };

        private sealed class OverrideRow
        {
            public Grid Grid;
            public ComboBox Cat, View, Style, Detail, Scale;
        }

        private readonly FtSettings s;
        private string sharedFileValue;
        private List<string> sharedNames = new List<string>();
        private string sharedNote = "";
        private readonly List<string> categories;
        private bool loading = true;
        private bool dirty;
        private bool discardArmed;
        private readonly List<OverrideRow> rows = new List<OverrideRow>();
        private readonly Func<string, KeyValuePair<List<string>, string>> loader; // shared parameter file path -> text parameter names and a note

        private FtSettingsWindow(UIApplication uiapp, FtSettings settings, IEnumerable<string> categoryNames,
            Func<string, KeyValuePair<List<string>, string>> sharedLoader)
            : base(uiapp, "SettingsWindow.xaml", settings.ThemeMode, true)
        {
            s = settings;
            loader = sharedLoader;
            sharedFileValue = settings.SharedFile;
            ReadSharedFile();
            categories = categoryNames.Concat(FtCore.FallbackCategories).Distinct().OrderBy(n => n.ToLowerInvariant(), StringComparer.Ordinal).ToList();
            BuildDefaultCombos();
            LoadValues();
            Wire();
            UpdatePreview();
            loading = false;
            SetStatus("", "bMuted");
        }

        // ---- build / load ------------------------------------------------------------------------------

        private void FillCombo(ComboBox combo, IList<string> items, string selected, bool hook)
        {
            combo.Items.Clear();
            foreach (string item in items) combo.Items.Add(item);
            int index = items.IndexOf(selected);
            combo.SelectedIndex = index >= 0 ? index : 0;
            if (hook) combo.SelectionChanged += (s2, a) => MarkDirty();
        }

        /// <summary>Reads the text parameters of the chosen shared parameter file (the built-in one when none is chosen).</summary>
        private void ReadSharedFile()
        {
            var probe = new FtSettings { SharedFile = sharedFileValue };
            bool isDefault;
            string note;
            string path = FtCore.ResolveSharedFile(probe, out isDefault, out note);
            KeyValuePair<List<string>, string> read = loader(path);
            sharedNames = read.Key.OrderBy(n => n.ToLowerInvariant(), StringComparer.Ordinal).ToList();
            sharedNote = (note.Length > 0 ? note + "  " : "") + read.Value;
        }

        private void RefillParamCombos(bool firstTime)
        {
            FtSettings defaults = new FtSettings();
            string[] current = { s.ParamCreator, s.ParamRevision, s.ParamDate };
            string[] defaultNames = { defaults.ParamCreator, defaults.ParamRevision, defaults.ParamDate };
            for (int i = 0; i < ParamCombos.Length; i++)
            {
                var combo = Get<ComboBox>(ParamCombos[i]);
                string chosen = firstTime ? current[i] : ((combo.SelectedItem as string) ?? current[i]);
                var names = new List<string>(sharedNames);
                if (firstTime && !string.IsNullOrEmpty(chosen) && !names.Contains(chosen)) names.Insert(0, chosen); // keep a saved choice this file lacks
                if (!names.Contains(chosen)) chosen = names.Contains(defaultNames[i]) ? defaultNames[i] : (names.Count > 0 ? names[0] : "");
                FillCombo(combo, names, chosen, firstTime);
            }
        }

        private void BuildDefaultCombos()
        {
            List<string> scales = FtCore.Scales.Select(FtLogic.ScaleText).ToList();
            FillCombo(Get<ComboBox>("cbStyle3D"), FtCore.DisplayStyles, s.D3Style, true);
            FillCombo(Get<ComboBox>("cbDetail3D"), FtCore.DetailLevels, s.D3Detail, true);
            FillCombo(Get<ComboBox>("cbScale3D"), scales, FtLogic.ScaleText(s.D3Scale), true);
            FillCombo(Get<ComboBox>("cbView3D"), FtCore.ViewTypes3D, s.D3View, true);
            FillCombo(Get<ComboBox>("cbStyle2D"), FtCore.DisplayStyles, s.D2Style, true);
            FillCombo(Get<ComboBox>("cbDetail2D"), FtCore.DetailLevels, s.D2Detail, true);
            FillCombo(Get<ComboBox>("cbScale2D"), scales, FtLogic.ScaleText(s.D2Scale), true);
            FillCombo(Get<ComboBox>("cbFormat"), FtCore.ImageFormats, s.ImageFormat, true);
            FillCombo(Get<ComboBox>("cbRevisionStep"), FtCore.RevisionSteps, s.RevisionStep, true);
            RefillParamCombos(true);
        }

        private void LoadValues()
        {
            Get<TextBox>("tbViewName").Text = s.ViewName;
            Get<TextBox>("tbFolder").Text = s.ExportFolder;
            Get<TextBox>("tbSize").Text = s.ImageSize.ToString();
            Get<TextBox>("tbCreator").Text = s.CreatorValue;
            ShowSharedFile();
            Get<RadioButton>("rbResize").IsChecked = s.FitMode != "square";
            Get<RadioButton>("rbSquare").IsChecked = s.FitMode == "square";
            foreach (CheckBinding c in Checkboxes) Get<CheckBox>(c.Name).IsChecked = c.Get(s);
            string[] colours = { s.GradSky, s.GradHorizon, s.GradGround };
            for (int i = 0; i < ColourFields.Length; i++)
            {
                Get<TextBox>(ColourFields[i][0]).Text = colours[i];
                Get<Button>(ColourFields[i][1]).Background = FtUi.BrushFromHex(colours[i]);
            }
            foreach (FtOverride item in s.Overrides) AddRow(item);
            var panel = Get<WrapPanel>("presetPanel");
            foreach (string[] preset in FtCore.GradientPresets)
            {
                var button = new Button { Content = preset[0], Margin = new Thickness(0, 0, 8, 8), Tag = preset };
                button.Click += OnPreset;
                panel.Children.Add(button);
            }
        }

        private void ShowSharedFile()
        {
            Get<TextBox>("tbSharedFile").Text = string.IsNullOrEmpty(sharedFileValue) ? "Built-in: BIM_Family_Parameters.txt" : sharedFileValue;
            Get<TextBlock>("tbParamFile").Text = sharedNote;
        }

        private void OnBrowseShared()
        {
            var dialog = new System.Windows.Forms.OpenFileDialog
            {
                Title = "Choose a shared parameter file",
                Filter = "Shared parameter files (*.txt)|*.txt|All files (*.*)|*.*",
            };
            if (!string.IsNullOrEmpty(sharedFileValue) && File.Exists(sharedFileValue)) dialog.FileName = sharedFileValue;
            if (dialog.ShowDialog() == System.Windows.Forms.DialogResult.OK) SetSharedFile(dialog.FileName);
        }

        private void SetSharedFile(string path)
        {
            sharedFileValue = path;
            ReadSharedFile();
            loading = true;
            RefillParamCombos(false);
            loading = false;
            ShowSharedFile();
            MarkDirty();
        }

        private void Wire()
        {
            Get<Button>("btnBrowseShared").Click += (a, b) => OnBrowseShared();
            Get<Button>("btnDefaultShared").Click += (a, b) => SetSharedFile("");
            Get<Button>("btnAddOverride").Click += (a, b) => { AddRow(null); MarkDirty(); };
            Get<Button>("btnBrowse").Click += (a, b) => OnBrowse();
            Get<Button>("btnSave").Click += (a, b) => OnSave();
            Get<Button>("btnClose").Click += (a, b) => RequestClose();
            foreach (string name in new[] { "tbViewName", "tbFolder", "tbSize", "tbCreator" })
                Get<TextBox>(name).TextChanged += (a, b) => MarkDirty();
            foreach (CheckBinding c in Checkboxes)
            {
                var box = Get<CheckBox>(c.Name);
                box.Checked += (a, b) => MarkDirty();
                box.Unchecked += (a, b) => MarkDirty();
            }
            Get<RadioButton>("rbResize").Checked += (a, b) => MarkDirty();
            Get<RadioButton>("rbSquare").Checked += (a, b) => MarkDirty();
            foreach (string[] field in ColourFields)
            {
                string tbName = field[0], swName = field[1];
                Get<TextBox>(tbName).TextChanged += (a, b) =>
                {
                    int r, g, bl;
                    if (FtLogic.ParseHex(Get<TextBox>(tbName).Text, out r, out g, out bl))
                        Get<Button>(swName).Background = FtUi.BrushFromHex(Get<TextBox>(tbName).Text);
                    UpdatePreview();
                    MarkDirty();
                };
                Get<Button>(swName).Click += (a, b) => OnSwatch(tbName);
            }
        }

        // ---- status / dirty ----------------------------------------------------------------------------

        private void SetStatus(string text, string brushKey)
        {
            var status = Get<TextBlock>("tbStatus");
            status.Text = text;
            status.SetResourceReference(TextBlock.ForegroundProperty, brushKey);
        }

        private void MarkDirty()
        {
            if (loading) return;
            dirty = true;
            discardArmed = false;
            SetStatus("Unsaved changes", "bOrange");
        }

        // ---- overrides ---------------------------------------------------------------------------------

        private void AddRow(FtOverride item)
        {
            if (item == null)
            {
                var used = new HashSet<string>(rows.Select(r => r.Cat.SelectedItem as string));
                string free = categories.FirstOrDefault(c => !used.Contains(c)) ?? categories[0];
                item = new FtOverride { Category = free, ViewType = s.D3View, Style = s.D3Style, Detail = s.D3Detail, Scale = s.D3Scale };
            }
            var cats = new List<string>(categories);
            if (!cats.Contains(item.Category)) cats.Insert(0, item.Category);
            var grid = new Grid { Margin = new Thickness(0, 0, 0, 6) };
            foreach (double width in OverrideWidths) grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(width) });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

            List<string> scales = FtCore.Scales.Select(FtLogic.ScaleText).ToList();
            var row = new OverrideRow { Grid = grid };
            var combos = new List<ComboBox>();
            var specs = new[]
            {
                new { Items = (IList<string>)cats, Selected = item.Category },
                new { Items = (IList<string>)FtCore.ViewTypes3D, Selected = item.ViewType },
                new { Items = (IList<string>)FtCore.DisplayStyles, Selected = item.Style },
                new { Items = (IList<string>)FtCore.DetailLevels, Selected = item.Detail },
                new { Items = (IList<string>)scales, Selected = FtLogic.ScaleText(item.Scale) },
            };
            for (int i = 0; i < specs.Length; i++)
            {
                var combo = new ComboBox { Margin = new Thickness(0, 0, 8, 0) };
                Grid.SetColumn(combo, i);
                FillCombo(combo, specs[i].Items, specs[i].Selected, true);
                grid.Children.Add(combo);
                combos.Add(combo);
            }
            row.Cat = combos[0];
            row.View = combos[1];
            row.Style = combos[2];
            row.Detail = combos[3];
            row.Scale = combos[4];

            var remove = new Button { ToolTip = "Remove this override", HorizontalAlignment = HorizontalAlignment.Left };
            Style removeStyle = Win.TryFindResource("RemoveButton") as Style;
            if (removeStyle != null) remove.Style = removeStyle;
            Grid.SetColumn(remove, 5);
            remove.Click += (a, b) =>
            {
                Get<StackPanel>("OverrideList").Children.Remove(grid);
                rows.RemoveAll(r => r.Grid == grid);
                MarkDirty();
            };
            grid.Children.Add(remove);
            Get<StackPanel>("OverrideList").Children.Add(grid);
            rows.Add(row);
        }

        // ---- gradient ----------------------------------------------------------------------------------

        private void OnSwatch(string tbName)
        {
            int r, g, b;
            if (!FtLogic.ParseHex(Get<TextBox>(tbName).Text, out r, out g, out b)) { r = g = b = 255; }
            var dialog = new System.Windows.Forms.ColorDialog { FullOpen = true, Color = System.Drawing.Color.FromArgb(r, g, b) };
            if (dialog.ShowDialog() == System.Windows.Forms.DialogResult.OK)
                Get<TextBox>(tbName).Text = FtLogic.ToHex(dialog.Color.R, dialog.Color.G, dialog.Color.B);
        }

        private void OnPreset(object sender, RoutedEventArgs args)
        {
            var preset = (string[])((Button)sender).Tag;
            Get<TextBox>("tbSky").Text = preset[1];
            Get<TextBox>("tbHorizon").Text = preset[2];
            Get<TextBox>("tbGround").Text = preset[3];
            Get<CheckBox>("cbGradient").IsChecked = true;
        }

        private static LinearGradientBrush Vertical(params KeyValuePair<Color, double>[] stops)
        {
            var brush = new LinearGradientBrush { StartPoint = new Point(0, 0), EndPoint = new Point(0, 1) };
            foreach (KeyValuePair<Color, double> stop in stops) brush.GradientStops.Add(new GradientStop(stop.Key, stop.Value));
            return brush;
        }

        private void UpdatePreview()
        {
            Color sky = FtUi.ColorFromHex(Get<TextBox>("tbSky").Text);
            Color horizon = FtUi.ColorFromHex(Get<TextBox>("tbHorizon").Text);
            Color ground = FtUi.ColorFromHex(Get<TextBox>("tbGround").Text);
            Get<Border>("prevDown").Background = Vertical(
                new KeyValuePair<Color, double>(horizon, 0.0), new KeyValuePair<Color, double>(ground, 1.0));
            Get<Border>("prevElev").Background = Vertical(
                new KeyValuePair<Color, double>(sky, 0.0), new KeyValuePair<Color, double>(horizon, 0.6),
                new KeyValuePair<Color, double>(ground, 0.6), new KeyValuePair<Color, double>(ground, 1.0));
        }

        // ---- browse / save / close ---------------------------------------------------------------------

        private void OnBrowse()
        {
            var dialog = new System.Windows.Forms.FolderBrowserDialog { Description = "Choose the folder the thumbnails are saved to" };
            string current = Get<TextBox>("tbFolder").Text.Trim();
            dialog.SelectedPath = Directory.Exists(current) ? current : FtCore.DefaultExportFolder();
            if (dialog.ShowDialog() == System.Windows.Forms.DialogResult.OK) Get<TextBox>("tbFolder").Text = dialog.SelectedPath;
        }

        /// <summary>Reads every control back into a settings object. Returns the settings and the problems found.</summary>
        private FtSettings Collect(List<string> problems)
        {
            FtSettings result = FtSettings.Load(); // start from what is on disk so keys this window does not own survive
            string name = Get<TextBox>("tbViewName").Text.Trim();
            if (name.Length == 0) problems.Add("Thumbnail View Name cannot be empty");
            else result.ViewName = name;
            result.ExportFolder = Get<TextBox>("tbFolder").Text.Trim();
            int size;
            if (int.TryParse(Get<TextBox>("tbSize").Text.Trim(), out size) && size >= 128 && size <= 4096) result.ImageSize = size;
            else problems.Add("Size must be a whole number from 128 to 4096");
            result.FitMode = Get<RadioButton>("rbSquare").IsChecked == true ? "square" : "resize";
            result.ImageFormat = Get<ComboBox>("cbFormat").SelectedItem as string ?? result.ImageFormat;
            foreach (CheckBinding c in Checkboxes) c.Set(result, Get<CheckBox>(c.Name).IsChecked == true);
            string[] hex = new string[3];
            for (int i = 0; i < ColourFields.Length; i++)
            {
                string text = Get<TextBox>(ColourFields[i][0]).Text;
                int r, g, b;
                if (!FtLogic.ParseHex(text, out r, out g, out b))
                {
                    problems.Add((text.Trim().Length == 0 ? "(blank)" : text.Trim()) + " is not a colour (use #RRGGBB)");
                    hex[i] = null;
                }
                else hex[i] = FtLogic.ToHex(r, g, b);
            }
            if (hex[0] != null) result.GradSky = hex[0];
            if (hex[1] != null) result.GradHorizon = hex[1];
            if (hex[2] != null) result.GradGround = hex[2];
            result.CreatorValue = Get<TextBox>("tbCreator").Text.Trim();
            result.SharedFile = sharedFileValue ?? "";
            result.RevisionStep = Get<ComboBox>("cbRevisionStep").SelectedItem as string ?? result.RevisionStep;
            string picked = Get<ComboBox>("cbParamCreator").SelectedItem as string;
            if (!string.IsNullOrEmpty(picked)) result.ParamCreator = picked;
            picked = Get<ComboBox>("cbParamRevision").SelectedItem as string;
            if (!string.IsNullOrEmpty(picked)) result.ParamRevision = picked;
            picked = Get<ComboBox>("cbParamDate").SelectedItem as string;
            if (!string.IsNullOrEmpty(picked)) result.ParamDate = picked;
            if (result.FillParams && (result.ParamCreator.Length == 0 || result.ParamRevision.Length == 0 || result.ParamDate.Length == 0))
                problems.Add("Choose the three family parameters, or untick Fill Parameters On Update");
            result.D3Style = Get<ComboBox>("cbStyle3D").SelectedItem as string ?? result.D3Style;
            result.D3Detail = Get<ComboBox>("cbDetail3D").SelectedItem as string ?? result.D3Detail;
            result.D3Scale = FtLogic.ParseScaleText(Get<ComboBox>("cbScale3D").SelectedItem as string, result.D3Scale);
            result.D3View = Get<ComboBox>("cbView3D").SelectedItem as string ?? result.D3View;
            result.D2Style = Get<ComboBox>("cbStyle2D").SelectedItem as string ?? result.D2Style;
            result.D2Detail = Get<ComboBox>("cbDetail2D").SelectedItem as string ?? result.D2Detail;
            result.D2Scale = FtLogic.ParseScaleText(Get<ComboBox>("cbScale2D").SelectedItem as string, result.D2Scale);
            result.Overrides = new List<FtOverride>();
            var seen = new HashSet<string>();
            foreach (OverrideRow row in rows)
            {
                string category = row.Cat.SelectedItem as string;
                if (category == null || !seen.Add(category)) continue; // first override for a category wins
                result.Overrides.Add(new FtOverride
                {
                    Category = category,
                    ViewType = row.View.SelectedItem as string ?? "",
                    Style = row.Style.SelectedItem as string ?? "",
                    Detail = row.Detail.SelectedItem as string ?? "",
                    Scale = FtLogic.ParseScaleText(row.Scale.SelectedItem as string, 1),
                });
            }
            result.ThemeMode = Mode;
            return result;
        }

        private void OnSave()
        {
            var problems = new List<string>();
            FtSettings result = Collect(problems);
            if (problems.Count > 0)
            {
                SetStatus(string.Join("; ", problems), "bRed");
                return;
            }
            try
            {
                result.Save();
            }
            catch (Exception err)
            {
                FtCore.Swallowed("settings.save", err);
                FtCore.Log("settings save failed: " + err);
                SetStatus("Could not save: " + err.Message, "bRed");
                return;
            }
            FtCore.Log("settings saved: size=" + result.ImageSize + " " + result.ImageFormat + " fit=" + result.FitMode + " fill_params=" + result.FillParams
                       + " overrides=" + result.Overrides.Count + " folder=" + FtCore.ExportFolder(result));
            FtCore.FlushLog();
            dirty = false;
            discardArmed = false;
            Win.Close(); // saved: nothing left to discard, so the window goes
        }

        public override void RequestClose()
        {
            if (dirty && !discardArmed)
            {
                discardArmed = true;
                SetStatus("Unsaved changes - press Close again to discard them", "bRed");
                return;
            }
            Win.Close();
        }

        /// <summary>Opens Settings. sharedLoader reads the text parameters of a shared parameter file: names, and a one-line note.</summary>
        public static void Open(UIApplication uiapp, IEnumerable<string> categories,
            Func<string, KeyValuePair<List<string>, string>> sharedLoader, Window owner)
        {
            new FtSettingsWindow(uiapp, FtSettings.Load(), categories, sharedLoader).Show(owner);
        }
    }
}
