// Port of efr_core.py's WPF toolkit (lines 1783-2285) and its file/icon helpers (4136-4326):
// the small control builders every dialog uses, the drawer geometry, the palette brushes a
// window built in code needs, and the icon buttons of the main window.
//
// Colours are the Efr.C_* palette fields, read at call time, so a theme switch is picked up
// by whatever is built next. Efr.Brush(hex) gives a cached, frozen brush.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text.RegularExpressions;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Markup;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using RevoBIM.Tools.ExcelForRevit;
using static RevoBIM.Tools.ExcelForRevit.Efr;

namespace RevoBIM.UI.ExcelForRevit
{
    public static partial class EfrUi
    {
        // ================================================================ control builders

        /// <summary>A TextBlock. colour null = the current palette's C_TEXT.</summary>
        public static TextBlock Tb(string text, string colour = null, double size = 12, bool bold = false, bool wrap = false)
        {
            var t = new TextBlock();
            t.Text = text;
            t.Foreground = Brush(colour ?? C_TEXT);
            t.FontSize = size;
            if (bold)
                t.FontWeight = FontWeights.SemiBold;
            if (wrap)
                t.TextWrapping = TextWrapping.Wrap;
            return t;
        }

        private const string BtnTemplateXaml = @"
<ControlTemplate xmlns=""http://schemas.microsoft.com/winfx/2006/xaml/presentation""
                 xmlns:x=""http://schemas.microsoft.com/winfx/2006/xaml"" TargetType=""Button"">
  <Border x:Name=""B"" Background=""{TemplateBinding Background}""
          BorderBrush=""{TemplateBinding BorderBrush}"" BorderThickness=""1""
          CornerRadius=""3"" Padding=""{TemplateBinding Padding}"">
    <ContentPresenter HorizontalAlignment=""Center"" VerticalAlignment=""Center""/>
  </Border>
  <ControlTemplate.Triggers>
    <Trigger Property=""IsMouseOver"" Value=""True"">
      <Setter TargetName=""B"" Property=""Opacity"" Value=""0.82""/>
    </Trigger>
    <Trigger Property=""IsEnabled"" Value=""False"">
      <Setter TargetName=""B"" Property=""Opacity"" Value=""0.40""/>
    </Trigger>
  </ControlTemplate.Triggers>
</ControlTemplate>";

        private static ControlTemplate _btnTemplate;
        private static bool _btnTemplateFailed;

        /// <summary>The shared flat button template, or null if it could not be parsed.</summary>
        public static ControlTemplate BtnTemplate()
        {
            if (_btnTemplate == null && !_btnTemplateFailed)
            {
                try
                {
                    _btnTemplate = (ControlTemplate)XamlReader.Parse(BtnTemplateXaml);
                }
                catch (Exception)
                {
                    _btnTemplateFailed = true;
                }
            }
            return _btnTemplate;
        }

        /// <summary>kind: "ghost" (default), "green", "red" or "orange". width null/0 = auto.</summary>
        public static Button StyledButton(string text, string kind = "ghost", double? width = null)
        {
            var b = new Button();
            try
            {
                ControlTemplate tpl = BtnTemplate();
                if (tpl != null)
                    b.Template = tpl;
            }
            catch (Exception)
            {
            }
            b.Content = text;
            b.Padding = new Thickness(16, 7, 16, 7);
            b.Margin = new Thickness(6, 0, 0, 0);
            b.BorderThickness = new Thickness(1);
            b.FontSize = 12;
            if (width.HasValue && width.Value != 0)
                b.Width = width.Value;
            // palette colours, not literals: these were dark greys written in by hand,
            // so every prompt's buttons stayed dark on a light canvas
            if (kind == "green")
            {
                b.Background = Brush(C_GREEN);
                b.BorderBrush = Brush(C_GREEN);
                b.Foreground = Brush("#FFFFFF");
                b.FontWeight = FontWeights.SemiBold;
            }
            else if (kind == "red")
            {
                b.Background = Brush(C_RED_SOFT);
                b.BorderBrush = Brush(C_RED);
                b.Foreground = Brush(C_RED);
            }
            else if (kind == "orange")
            {
                b.Background = Brush(C_ORANGE_SOFT);
                b.BorderBrush = Brush(C_ORANGE);
                b.Foreground = Brush(C_ORANGE);
            }
            else
            {
                b.Background = Brush(C_BTN_BG);
                b.BorderBrush = Brush(C_BTN_EDGE);
                b.Foreground = Brush(C_TEXT);
            }
            return b;
        }

        public static TextBox DarkTextbox(double width = 220, string text = "")
        {
            var tbx = new TextBox();
            tbx.Width = width;
            tbx.Text = text;
            tbx.Background = Brush(C_FIELD);
            tbx.Foreground = Brush(C_TEXT);
            tbx.BorderBrush = Brush(C_EDGE);
            tbx.BorderThickness = new Thickness(1);
            tbx.Padding = new Thickness(6, 4, 6, 4);
            tbx.CaretBrush = Brush(C_ORANGE);
            return tbx;
        }

        public static CheckBox DarkCheck(string label, bool isChecked = false)
        {
            var c = new CheckBox();
            c.Content = label;
            c.Foreground = Brush(C_TEXT);
            c.IsChecked = isChecked;
            c.Margin = new Thickness(0, 4, 16, 4);
            return c;
        }

        private const string WinBtnTemplateXaml = @"
<ControlTemplate xmlns=""http://schemas.microsoft.com/winfx/2006/xaml/presentation""
                 xmlns:x=""http://schemas.microsoft.com/winfx/2006/xaml"" TargetType=""Button"">
  <Border x:Name=""B"" Background=""Transparent"" CornerRadius=""3"">
    <ContentPresenter HorizontalAlignment=""Center"" VerticalAlignment=""Center""/>
  </Border>
  <ControlTemplate.Triggers>
    <Trigger Property=""IsMouseOver"" Value=""True"">
      <Setter TargetName=""B"" Property=""Background""
              Value=""{Binding Tag, RelativeSource={RelativeSource TemplatedParent}}""/>
    </Trigger>
  </ControlTemplate.Triggers>
</ControlTemplate>";

        private static ControlTemplate _winBtnTemplate;
        private static bool _winBtnTemplateFailed;

        /// <summary>
        /// A header control shaped like the main window's: flat, 44x26, hover grey.
        /// The dialogs build their chrome in code while the main window takes its own
        /// from the layout file, so the same button is written out twice; keeping the
        /// size, the corner and the hover in one place stops the two drifting apart.
        /// The hover colour rides on Tag so it follows the palette rather than being
        /// baked into the shared template.
        /// </summary>
        public static Button WinButton(string glyph, string tip = "")
        {
            var b = new Button();
            if (_winBtnTemplate == null && !_winBtnTemplateFailed)
            {
                try
                {
                    _winBtnTemplate = (ControlTemplate)XamlReader.Parse(WinBtnTemplateXaml);
                }
                catch (Exception)
                {
                    _winBtnTemplateFailed = true;
                }
            }
            if (_winBtnTemplate != null)
            {
                try
                {
                    b.Template = _winBtnTemplate;
                }
                catch (Exception)
                {
                }
            }
            b.Content = glyph;
            b.Width = 44;
            b.Height = 26;
            b.FontSize = 14;
            b.Focusable = false;
            b.Cursor = Cursors.Hand;
            b.Foreground = Brush(C_TEXT);
            b.Background = Brush("#00FFFFFF");
            b.BorderThickness = new Thickness(0);
            b.Tag = Brush(C_BTN_HOVER);
            if (!string.IsNullOrEmpty(tip))
                b.ToolTip = tip;
            return b;
        }

        // ================================================================ shrink to taskbar
        //
        // Every window in this tool can be shrunk to its own title bar and parked at
        // the bottom of the screen, so Revit can be seen without closing anything and
        // losing the pending edits. The motion is a drawer: the window slides down
        // and its body slides out of sight behind the bottom edge, leaving the bar
        // floating just above the taskbar. The button then becomes a green up arrow
        // that pulls the drawer back open.

        public const int DRAWER_MS = 240;               // one slide, each way
        public const int DRAWER_GAP_PX = 10;            // air between the parked bar and the taskbar
        public const string DRAWER_DOWN = "⤓";     // downwards arrow to bar, for "put it away"
        public const string DRAWER_UP = "⤒";       // upwards arrow to bar, for "bring it back"
        public const double DRAWER_MOVED_PX = 3.0;      // slack when deciding whether the bar was dragged
        public const string DRAWER_TIP_DOWN = "Shrink to the taskbar so Revit can be seen (Ctrl+Shift+H)";
        public const string DRAWER_TIP_UP = "Expand the window again (Ctrl+Shift+H)";

        /// <summary>
        /// The working area of the screen `window` is on, in WPF units.
        /// SystemParameters.WorkArea is the *primary* screen, so on a second monitor a
        /// maximise, a stretch or a parked drawer threw the window back onto the first
        /// one. The screen is found from the window handle, and its pixels are divided
        /// by the DPI scale or it overshoots on a scaled display.
        /// </summary>
        public static (double Left, double Top, double Width, double Height) ScreenWorkArea(Window window)
        {
            try
            {
                IntPtr handle = new WindowInteropHelper(window).Handle;
                System.Drawing.Rectangle area = System.Windows.Forms.Screen.FromHandle(handle).WorkingArea;
                double sx = 1.0, sy = 1.0;
                try
                {
                    PresentationSource source = PresentationSource.FromVisual(window);
                    if (source != null)
                    {
                        Matrix matrix = source.CompositionTarget.TransformToDevice;
                        sx = matrix.M11 != 0.0 ? matrix.M11 : 1.0;
                        sy = matrix.M22 != 0.0 ? matrix.M22 : 1.0;
                    }
                }
                catch (Exception)
                {
                }
                return (area.Left / sx, area.Top / sy, area.Width / sx, area.Height / sy);
            }
            catch (Exception)
            {
                Rect a = SystemParameters.WorkArea;
                return (a.Left, a.Top, a.Width, a.Height);
            }
        }

        /// <summary>
        /// Where the parked bar sits: just clear of the bottom of the screen. Clamped to
        /// the top of the work area, because a screen shorter than the bar would
        /// otherwise park it below the desktop and out of reach.
        /// </summary>
        public static double DrawerParkTop(double areaTop, double areaHeight, double bar)
        {
            double target = areaTop + areaHeight - bar - DRAWER_GAP_PX;
            return target < areaTop ? areaTop : target;
        }

        /// <summary>
        /// Did the user carry the bar away from where the drawer parked it? A few pixels
        /// of slack, so the window manager nudging a docked window by a pixel does not
        /// count as the user having moved it.
        /// </summary>
        public static bool DrawerMoved(double left, double top, (double Left, double Top)? docked)
        {
            if (docked == null)
                return false;
            return Math.Abs(left - docked.Value.Left) > DRAWER_MOVED_PX
                || Math.Abs(top - docked.Value.Top) > DRAWER_MOVED_PX;
        }

        /// <summary>
        /// Where the window goes when the drawer opens again. Left where it was parked,
        /// it returns to exactly where it came from. Carried somewhere else, it opens
        /// upward from the bar instead: jumping back to a position the user has already
        /// moved on from reads as a bug.
        /// </summary>
        public static double DrawerOpenTop(double barTop, double bar, double height, double areaTop, double savedTop, bool moved)
        {
            if (!moved)
                return savedTop;
            double target = barTop + bar - height;
            return target < areaTop ? areaTop : target;
        }

        // ================================================================ palette for windows built in code

        /// <summary>
        /// (resource key, colour) for every brush the layouts look up by name. One list
        /// for every window: the main window rewrites these on a theme switch, and each
        /// dialog writes them into its own resources when it is built. Read at call
        /// time, so it always reflects the current theme.
        /// </summary>
        public static (string Key, string Colour)[] PaletteBrushes()
        {
            return new[]
            {
                ("BgWindow", C_WINDOW), ("BgCard", C_CARD), ("BgField", C_FIELD),
                ("BgBar", C_BAR), ("Edge", C_EDGE), ("EdgeSoft", C_EDGE_SOFT),
                ("TextBody", C_TEXT), ("TextMute", C_MUTED), ("Blue", C_BLUE),
                ("Orange", C_ORANGE), ("Green", C_GREEN), ("GreenHi", C_GREEN_HI),
                ("Red", C_RED), ("Sel", C_SEL), ("SelFg", C_SEL_FG),
                ("HeaderBg", C_HEADER_BG), ("BtnBg", C_BTN_BG), ("BtnEdge", C_BTN_EDGE),
                ("BtnHover", C_BTN_HOVER), ("BtnOff", C_BTN_OFF),
                ("TextOff", C_TEXT_OFF),
                ("ScrollBg", C_SCROLL_BG), ("ScrollTh", C_SCROLL_THUMB),
                ("GridLine", C_GRIDLINE), ("OrangeSoft", C_ORANGE_SOFT),
                ("OrangeSoftHi", C_ORANGE_SOFT_HI), ("GreenOff", C_GREEN_OFF),
                ("GreenOffFg", C_GREEN_OFF_FG), ("RowHover", C_ROW_HOVER),
            };
        }

        // The control styles a window built in code does not get. The main window takes
        // its styles from ExcelForRevit.xaml; a ThemedDialog has no layout file, so every
        // list, scrollbar, text box and tick box in it fell back to Windows' own light
        // chrome: grey scrollbars with arrows, a pale selected row, a blue focus border,
        // white tick boxes. Every brush here is a DynamicResource that the dialog writes
        // into its own resources from PaletteBrushes(), so the styles follow the theme
        // without being rebuilt.
        private const string DialogThemeXaml = @"<ResourceDictionary xmlns=""http://schemas.microsoft.com/winfx/2006/xaml/presentation""
                    xmlns:x=""http://schemas.microsoft.com/winfx/2006/xaml"">

  <Style x:Key=""SbThumb"" TargetType=""Thumb"">
    <Setter Property=""MinHeight"" Value=""26""/>
    <Setter Property=""MinWidth"" Value=""26""/>
    <Setter Property=""Template"">
      <Setter.Value>
        <ControlTemplate TargetType=""Thumb"">
          <Border x:Name=""T"" Background=""{DynamicResource ScrollTh}"" CornerRadius=""4"" Margin=""2""/>
          <ControlTemplate.Triggers>
            <Trigger Property=""IsMouseOver"" Value=""True"">
              <Setter TargetName=""T"" Property=""Background"" Value=""{DynamicResource TextMute}""/>
            </Trigger>
            <Trigger Property=""IsDragging"" Value=""True"">
              <Setter TargetName=""T"" Property=""Background"" Value=""{DynamicResource Blue}""/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>

  <Style x:Key=""SbLine"" TargetType=""RepeatButton"">
    <Setter Property=""Focusable"" Value=""False""/>
    <Setter Property=""Template"">
      <Setter.Value>
        <ControlTemplate TargetType=""RepeatButton""><Border Background=""Transparent""/></ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>

  <Style TargetType=""ScrollBar"">
    <Setter Property=""Background"" Value=""{DynamicResource ScrollBg}""/>
    <Setter Property=""Width"" Value=""14""/>
    <Setter Property=""MinWidth"" Value=""14""/>
    <Setter Property=""Template"">
      <Setter.Value>
        <ControlTemplate TargetType=""ScrollBar"">
          <Grid Background=""{DynamicResource ScrollBg}"">
            <Track x:Name=""PART_Track"" IsDirectionReversed=""True""
                   ViewportSize=""{TemplateBinding ViewportSize}""
                   Minimum=""{TemplateBinding Minimum}""
                   Maximum=""{TemplateBinding Maximum}""
                   Value=""{TemplateBinding Value}"">
              <Track.DecreaseRepeatButton>
                <RepeatButton Style=""{DynamicResource SbLine}"" Command=""ScrollBar.PageUpCommand""/>
              </Track.DecreaseRepeatButton>
              <Track.Thumb><Thumb Style=""{DynamicResource SbThumb}""/></Track.Thumb>
              <Track.IncreaseRepeatButton>
                <RepeatButton Style=""{DynamicResource SbLine}"" Command=""ScrollBar.PageDownCommand""/>
              </Track.IncreaseRepeatButton>
            </Track>
          </Grid>
          <ControlTemplate.Triggers>
            <Trigger Property=""Orientation"" Value=""Horizontal"">
              <Setter TargetName=""PART_Track"" Property=""IsDirectionReversed"" Value=""False""/>
              <Setter Property=""Height"" Value=""14""/>
              <Setter Property=""MinHeight"" Value=""14""/>
              <Setter Property=""Width"" Value=""Auto""/>
              <Setter Property=""MinWidth"" Value=""0""/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>

  <Style TargetType=""TextBox"">
    <Setter Property=""Background"" Value=""{DynamicResource BgField}""/>
    <Setter Property=""Foreground"" Value=""{DynamicResource TextBody}""/>
    <Setter Property=""CaretBrush"" Value=""{DynamicResource Orange}""/>
    <Setter Property=""BorderBrush"" Value=""{DynamicResource Edge}""/>
    <Setter Property=""BorderThickness"" Value=""1""/>
    <Setter Property=""Padding"" Value=""6,4""/>
    <Setter Property=""SelectionBrush"" Value=""{DynamicResource Sel}""/>
    <Setter Property=""Template"">
      <Setter.Value>
        <ControlTemplate TargetType=""TextBox"">
          <Border x:Name=""B"" Background=""{TemplateBinding Background}""
                  BorderBrush=""{TemplateBinding BorderBrush}""
                  BorderThickness=""{TemplateBinding BorderThickness}"" CornerRadius=""3"">
            <Grid>
              <TextBlock x:Name=""Hint"" Foreground=""{DynamicResource TextMute}""
                         Text=""{Binding Tag, RelativeSource={RelativeSource TemplatedParent}}""
                         Margin=""{TemplateBinding Padding}"" Padding=""2,0,0,0""
                         VerticalAlignment=""Center"" IsHitTestVisible=""False""
                         Visibility=""Collapsed""/>
              <ScrollViewer x:Name=""PART_ContentHost"" Margin=""{TemplateBinding Padding}""
                            VerticalAlignment=""Center""/>
            </Grid>
          </Border>
          <ControlTemplate.Triggers>
            <Trigger Property=""Text"" Value="""">
              <Setter TargetName=""Hint"" Property=""Visibility"" Value=""Visible""/>
            </Trigger>
            <Trigger Property=""IsMouseOver"" Value=""True"">
              <Setter TargetName=""B"" Property=""BorderBrush"" Value=""{DynamicResource EdgeSoft}""/>
            </Trigger>
            <Trigger Property=""IsKeyboardFocused"" Value=""True"">
              <Setter TargetName=""B"" Property=""BorderBrush"" Value=""{DynamicResource Orange}""/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>

  <Style TargetType=""ListBox"">
    <Setter Property=""Background"" Value=""{DynamicResource BgField}""/>
    <Setter Property=""Foreground"" Value=""{DynamicResource TextBody}""/>
    <Setter Property=""BorderBrush"" Value=""{DynamicResource Edge}""/>
    <Setter Property=""BorderThickness"" Value=""1""/>
    <!-- no sideways scrolling: where two scrollbars meet, WPF fills the corner
         with a system-grey square that no style reaches -->
    <Setter Property=""ScrollViewer.HorizontalScrollBarVisibility"" Value=""Disabled""/>
  </Style>

  <Style TargetType=""ListBoxItem"">
    <Setter Property=""Foreground"" Value=""{DynamicResource TextBody}""/>
    <Setter Property=""Padding"" Value=""8,4""/>
    <Setter Property=""FocusVisualStyle"" Value=""{x:Null}""/>
    <Setter Property=""Template"">
      <Setter.Value>
        <ControlTemplate TargetType=""ListBoxItem"">
          <Border x:Name=""B"" Background=""Transparent"" Padding=""{TemplateBinding Padding}"">
            <ContentPresenter VerticalAlignment=""Center""/>
          </Border>
          <ControlTemplate.Triggers>
            <Trigger Property=""IsMouseOver"" Value=""True"">
              <Setter TargetName=""B"" Property=""Background"" Value=""{DynamicResource RowHover}""/>
            </Trigger>
            <Trigger Property=""IsSelected"" Value=""True"">
              <Setter TargetName=""B"" Property=""Background"" Value=""{DynamicResource Sel}""/>
              <Setter Property=""Foreground"" Value=""{DynamicResource SelFg}""/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>

  <Style TargetType=""CheckBox"">
    <Setter Property=""Foreground"" Value=""{DynamicResource TextBody}""/>
    <Setter Property=""Cursor"" Value=""Hand""/>
    <Setter Property=""FocusVisualStyle"" Value=""{x:Null}""/>
    <Setter Property=""Template"">
      <Setter.Value>
        <ControlTemplate TargetType=""CheckBox"">
          <StackPanel Orientation=""Horizontal"" Background=""Transparent"">
            <Border x:Name=""Box"" Width=""15"" Height=""15"" CornerRadius=""3""
                    Background=""{DynamicResource BgField}""
                    BorderBrush=""{DynamicResource EdgeSoft}"" BorderThickness=""1""
                    VerticalAlignment=""Center"">
              <Path x:Name=""Tick"" Data=""M 2.5,7 L 5.5,10 L 11,3.5""
                    Stroke=""{DynamicResource Orange}"" StrokeThickness=""2""
                    Visibility=""Collapsed""/>
            </Border>
            <ContentPresenter Margin=""7,0,0,0"" VerticalAlignment=""Center""/>
          </StackPanel>
          <ControlTemplate.Triggers>
            <Trigger Property=""IsChecked"" Value=""True"">
              <Setter TargetName=""Tick"" Property=""Visibility"" Value=""Visible""/>
              <Setter TargetName=""Box"" Property=""BorderBrush"" Value=""{DynamicResource Orange}""/>
            </Trigger>
            <Trigger Property=""IsMouseOver"" Value=""True"">
              <Setter TargetName=""Box"" Property=""BorderBrush"" Value=""{DynamicResource Orange}""/>
            </Trigger>
            <Trigger Property=""IsEnabled"" Value=""False"">
              <Setter Property=""Opacity"" Value=""0.45""/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>

  <Style TargetType=""RadioButton"">
    <Setter Property=""Foreground"" Value=""{DynamicResource TextBody}""/>
    <Setter Property=""Cursor"" Value=""Hand""/>
    <Setter Property=""FocusVisualStyle"" Value=""{x:Null}""/>
    <Setter Property=""Template"">
      <Setter.Value>
        <ControlTemplate TargetType=""RadioButton"">
          <StackPanel Orientation=""Horizontal"" Background=""Transparent"">
            <Grid Width=""15"" Height=""15"" VerticalAlignment=""Center"">
              <Ellipse x:Name=""Ring"" Fill=""{DynamicResource BgField}""
                       Stroke=""{DynamicResource EdgeSoft}"" StrokeThickness=""1""/>
              <Ellipse x:Name=""Dot"" Width=""7"" Height=""7""
                       Fill=""{DynamicResource Orange}"" Visibility=""Collapsed""/>
            </Grid>
            <ContentPresenter Margin=""7,0,0,0"" VerticalAlignment=""Center""/>
          </StackPanel>
          <ControlTemplate.Triggers>
            <Trigger Property=""IsChecked"" Value=""True"">
              <Setter TargetName=""Dot"" Property=""Visibility"" Value=""Visible""/>
              <Setter TargetName=""Ring"" Property=""Stroke"" Value=""{DynamicResource Orange}""/>
            </Trigger>
            <Trigger Property=""IsMouseOver"" Value=""True"">
              <Setter TargetName=""Ring"" Property=""Stroke"" Value=""{DynamicResource Orange}""/>
            </Trigger>
            <Trigger Property=""IsEnabled"" Value=""False"">
              <Setter Property=""Opacity"" Value=""0.45""/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>

</ResourceDictionary>";

        private static ResourceDictionary _dialogTheme;
        private static bool _dialogThemeFailed;

        /// <summary>
        /// Give a window built in code what the main window gets from its layout: the
        /// palette's brushes by name, and the control styles that use them.
        /// </summary>
        public static void ThemeWindow(Window window)
        {
            ResourceDictionary res = window.Resources;
            foreach (var item in PaletteBrushes())
            {
                try
                {
                    res[item.Key] = Brush(item.Colour);
                }
                catch (Exception)
                {
                }
            }
            if (_dialogTheme == null && !_dialogThemeFailed)
            {
                try
                {
                    _dialogTheme = (ResourceDictionary)XamlReader.Parse(DialogThemeXaml);
                }
                catch (Exception)
                {
                    _dialogThemeFailed = true;   // unthemed beats a dialog that will not open
                }
            }
            if (_dialogTheme != null)
            {
                try
                {
                    res.MergedDictionaries.Add(_dialogTheme);
                }
                catch (Exception)
                {
                }
            }
        }

        // ================================================================ files

        /// <summary>Where the last export or import went. Falls back to Documents.</summary>
        public static string RememberedFolder()
        {
            string folder = GetString(LoadSettings(), "excel_folder", "");
            if (!string.IsNullOrEmpty(folder) && Directory.Exists(folder))
                return folder;
            try
            {
                string docs = Path.Combine(Environment.GetEnvironmentVariable("USERPROFILE") ?? "", "Documents");
                if (Directory.Exists(docs))
                    return docs;
            }
            catch (Exception)
            {
            }
            return "";
        }

        public static void RememberFolder(string path)
        {
            try
            {
                string folder = Path.GetDirectoryName(path);
                if (!string.IsNullOrEmpty(folder))
                    SaveSetting("excel_folder", folder);
            }
            catch (Exception)
            {
            }
        }

        /// <summary>Windows Save As, opening where the last one went. Null when cancelled.</summary>
        public static string AskSavePath(string suggestedName)
        {
            try
            {
                var dialog = new System.Windows.Forms.SaveFileDialog();
                dialog.Title = "Export to Excel";
                dialog.Filter = "Excel workbook (*.xlsx)|*.xlsx";
                dialog.DefaultExt = "xlsx";
                dialog.AddExtension = true;
                dialog.OverwritePrompt = true;
                dialog.FileName = SafeFilename(suggestedName);
                string folder = RememberedFolder();
                if (!string.IsNullOrEmpty(folder))
                    dialog.InitialDirectory = folder;
                if (dialog.ShowDialog() != System.Windows.Forms.DialogResult.OK)
                    return null;
                return dialog.FileName;
            }
            catch (Exception)
            {
                return null;
            }
        }

        /// <summary>Windows Open, opening where the last one went. Null when cancelled.</summary>
        public static string AskOpenPath()
        {
            try
            {
                var dialog = new System.Windows.Forms.OpenFileDialog();
                dialog.Title = "Import from Excel";
                dialog.Filter = "Excel workbook (*.xlsx)|*.xlsx";
                dialog.Multiselect = false;
                string folder = RememberedFolder();
                if (!string.IsNullOrEmpty(folder))
                    dialog.InitialDirectory = folder;
                if (dialog.ShowDialog() != System.Windows.Forms.DialogResult.OK)
                    return null;
                return dialog.FileName;
            }
            catch (Exception)
            {
                return null;
            }
        }

        private static readonly Regex UnsafeFileChars = new Regex(@"[<>:""/\\|?*]");

        /// <summary>The name made safe for a file, trimmed to 120 characters, with ".xlsx" added.</summary>
        public static string SafeFilename(string name)
        {
            string text = UnsafeFileChars.Replace(name ?? "", "-").Trim();
            string output = text.Length > 0 ? text : "Schedule";
            if (output.Length > 120)
                output = output.Substring(0, 120);
            return output + ".xlsx";
        }

        /// <summary>Open the containing folder with the file selected. False when nothing could be opened.</summary>
        public static bool RevealInExplorer(string path)
        {
            try
            {
                var info = new ProcessStartInfo("explorer.exe", "/select,\"" + path + "\"");
                info.UseShellExecute = true;
                Process.Start(info);
                return true;
            }
            catch (Exception)
            {
            }
            try
            {
                var info = new ProcessStartInfo(Path.GetDirectoryName(path));
                info.UseShellExecute = true;
                Process.Start(info);
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        // ================================================================ icons

        private const string IconsPrefix = "RevoBIM.Resources.ExcelForRevit.icons.";
        private static readonly Dictionary<string, BitmapImage> ImageCache = new Dictionary<string, BitmapImage>(StringComparer.Ordinal);

        /// <summary>
        /// A frozen BitmapImage from an embedded resource (full manifest name), or null
        /// when there is no such resource. Cached by resource name, misses included.
        /// </summary>
        public static BitmapImage LoadResourceImage(string resourceName)
        {
            BitmapImage img;
            if (ImageCache.TryGetValue(resourceName, out img))
                return img;
            img = null;
            try
            {
                using (Stream stream = typeof(EfrUi).Assembly.GetManifestResourceStream(resourceName))
                {
                    if (stream != null)
                    {
                        var bytes = new MemoryStream();
                        stream.CopyTo(bytes);
                        bytes.Position = 0;
                        var bi = new BitmapImage();
                        bi.BeginInit();
                        bi.StreamSource = bytes;
                        bi.CacheOption = BitmapCacheOption.OnLoad;
                        bi.EndInit();
                        try
                        {
                            bi.Freeze();
                        }
                        catch (Exception)
                        {
                        }
                        img = bi;
                    }
                }
            }
            catch (Exception)
            {
                img = null;
            }
            ImageCache[resourceName] = img;
            return img;
        }

        /// <summary>The tool's logo for the window header (Python ICON_PATH, icon.png).</summary>
        public static BitmapImage LogoImage()
        {
            return LoadResourceImage("RevoBIM.Resources.ExcelForRevit.icon.png");
        }

        /// <summary>Themed 24px glyph. icons.&lt;name&gt;.png on dark, icons.&lt;name&gt;.light.png on light. Null if missing.</summary>
        public static BitmapImage ToolbarIcon(string name)
        {
            string suffix = ThemeName == "light" ? ".light.png" : ".png";
            return LoadResourceImage(IconsPrefix + name + suffix);
        }

        /// <summary>
        /// What BuildWideButton / BuildToolButton leave in button.Tag, so the theme switch can
        /// repaint the icon: <c>var (iconName, image, text) = EfrUi.IconTag(btn);</c>.
        /// </summary>
        public static (string IconName, Image Image, TextBlock Text) IconTag(Button button)
        {
            return ((string, Image, TextBlock))button.Tag;
        }

        /// <summary>Icon beside the label, for the footer, where a stacked one is too tall.</summary>
        public static Button BuildWideButton(Button button, string iconName, string label, string tooltip = null)
        {
            var stack = new StackPanel();
            stack.Orientation = Orientation.Horizontal;
            stack.HorizontalAlignment = HorizontalAlignment.Center;
            var image = new Image();
            image.Width = 26;
            image.Height = 26;
            image.Margin = new Thickness(0, 0, 8, 0);
            image.VerticalAlignment = VerticalAlignment.Center;
            try
            {
                image.Source = ToolbarIcon(iconName);
            }
            catch (Exception)
            {
            }
            stack.Children.Add(image);
            TextBlock text = Tb(label, C_TEXT, 12.5, true);
            text.VerticalAlignment = VerticalAlignment.Center;
            stack.Children.Add(text);
            button.Content = stack;
            if (!string.IsNullOrEmpty(tooltip))
                button.ToolTip = tooltip;
            button.Tag = (iconName, image, text);
            return button;
        }

        /// <summary>Icon above text, so the strip reads as a ribbon rather than a word soup.</summary>
        public static Button BuildToolButton(Button button, string iconName, string label, string tooltip)
        {
            var stack = new StackPanel();
            stack.Orientation = Orientation.Vertical;
            stack.HorizontalAlignment = HorizontalAlignment.Center;
            var image = new Image();
            image.Width = 22;
            image.Height = 22;
            image.Margin = new Thickness(0, 0, 0, 3);
            image.HorizontalAlignment = HorizontalAlignment.Center;
            try
            {
                image.Source = ToolbarIcon(iconName);
            }
            catch (Exception)
            {
            }
            stack.Children.Add(image);
            TextBlock text = Tb(label, C_TEXT, 10.5);
            text.HorizontalAlignment = HorizontalAlignment.Center;
            stack.Children.Add(text);
            button.Content = stack;
            button.Padding = new Thickness(8, 5, 8, 4);
            button.MinWidth = 58;
            button.Margin = new Thickness(1, 0, 1, 0);
            if (!string.IsNullOrEmpty(tooltip))
                button.ToolTip = tooltip;
            button.Tag = (iconName, image, text);
            return button;
        }
    }
}
