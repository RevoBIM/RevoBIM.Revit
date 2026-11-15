using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Markup;

namespace RevoBIM.UI.ProSheets
{
    public static partial class PsUi
    {
        /// <summary>
        /// A text box with a list under it. Typing narrows the list to the names
        /// containing what is typed; click one, or arrow to it and press Enter, to
        /// pick it. The caret beside the box shows the whole list.
        ///
        /// A themed stand-in for an editable ComboBox, whose template the theme
        /// does not carry and whose typed text and picked item fight each other.
        /// Value is the picked name, or "" while what is typed matches none.
        /// Put Element into the layout.
        /// </summary>
        public class SearchPicker
        {
            /// <summary>The caret glyph (Python CARET; renamed because Caret is the button).</summary>
            public const string CaretXaml =
                "<Path xmlns=\"http://schemas.microsoft.com/winfx/2006/xaml/presentation\" Width=\"8\" Height=\"5\" Stretch=\"Uniform\"" +
                " Fill=\"{DynamicResource MutedBrush}\" Data=\"M 0,0 L 8,0 L 4,5 Z\"/>";

            public List<string> Items;
            public string Value;
            public Action<SearchPicker> OnChange;
            public Func<IEnumerable<string>, string, List<string>> Matcher;
            internal bool Suspend;

            public Grid Element;
            public TextBox Box;
            public Button Caret;
            public ListBox List;
            public Border Shell;
            public Popup Popup;

            public SearchPicker(IEnumerable items = null, string value = "", Action<SearchPicker> onChange = null,
                string hint = "Type to search", Func<IEnumerable<string>, string, List<string>> matcher = null,
                double height = 28)
            {
                Items = ToNames(items);
                Value = "";
                OnChange = onChange;
                Matcher = matcher ?? new Func<IEnumerable<string>, string, List<string>>(WordsMatch);
                Suspend = false;

                Element = new Grid();
                Element.Height = height;
                foreach (double? width in new double?[] { null, 26 })
                {
                    var definition = new ColumnDefinition();
                    if (width != null) definition.Width = new GridLength(width.Value);
                    Element.ColumnDefinitions.Add(definition);
                }
                Box = new TextBox();
                Box.Tag = hint;
                Box.ToolTip = "Type part of the name - the list narrows to " +
                              "the names containing it. Down and Enter, or a click, to pick.";
                Grid.SetColumn(Box, 0);
                Element.Children.Add(Box);
                Caret = new Button();
                Caret.SetResourceReference(FrameworkElement.StyleProperty, "IconButton");
                Caret.Width = 24;
                Caret.ToolTip = "Show the whole list";
                try
                {
                    Caret.Content = XamlReader.Parse(CaretXaml);
                }
                catch (Exception)
                {
                    Caret.Content = "v";
                }
                Grid.SetColumn(Caret, 1);
                Element.Children.Add(Caret);

                List = new ListBox();
                List.MaxHeight = 260;
                List.BorderThickness = new Thickness(0);
                var shell = new Border();
                shell.SetResourceReference(Border.BackgroundProperty, "CardBg");
                shell.SetResourceReference(Border.BorderBrushProperty, "EdgeBrush");
                shell.BorderThickness = new Thickness(1);
                shell.CornerRadius = new CornerRadius(3);
                shell.Padding = new Thickness(1);
                shell.Child = List;
                Shell = shell;
                Popup = new Popup();
                Popup.PlacementTarget = Element;
                Popup.Placement = PlacementMode.Bottom;
                Popup.StaysOpen = false;
                Popup.AllowsTransparency = true;
                Popup.Child = shell;
                // In the picker's own Grid, so the list is in the window's logical
                // tree and its DynamicResource colours resolve.
                Element.Children.Add(Popup);

                Box.TextChanged += Typed;
                Box.PreviewKeyDown += KeyPressed;
                Caret.Click += ShowAll;
                List.PreviewMouseLeftButtonUp += Clicked;
                SetValue(value);
            }

            private static List<string> ToNames(IEnumerable items)
            {
                var names = new List<string>();
                if (items == null) return names;
                foreach (object item in items) names.Add(PyStr(item));
                return names;
            }

            // ------------------------------------------------------------------

            /// <summary>
            /// The names on offer for what is in the box: all of them while it is
            /// empty or still shows the picked name, else those that match.
            /// </summary>
            public static List<string> Shown(IEnumerable<string> items, string text, string value,
                Func<IEnumerable<string>, string, List<string>> matcher = null)
            {
                text = (text ?? "").Trim();
                if (text.Length == 0 || (!string.IsNullOrEmpty(value) && text == value)) return items.ToList();
                return (matcher ?? new Func<IEnumerable<string>, string, List<string>>(WordsMatch))(items, text);
            }

            /// <summary>The name the box holds exactly, any case, or "".</summary>
            public static string Resolve(IEnumerable<string> items, string text)
            {
                text = (text ?? "").Trim().ToLowerInvariant();
                if (text.Length == 0) return "";
                foreach (string item in items)
                {
                    if ((item ?? "None").ToLowerInvariant() == text) return item;
                }
                return "";
            }

            public string Text()
            {
                try
                {
                    return Box.Text ?? "";
                }
                catch (Exception)
                {
                    return "";
                }
            }

            public void SetItems(IEnumerable items, string value = null)
            {
                Items = ToNames(items);
                SetValue(value == null ? Value : value);
            }

            /// <summary>Show a name as picked, without telling OnChange.</summary>
            public void SetValue(string value)
            {
                value = value ?? "";
                Value = Items.Contains(value) ? value : "";
                Suspend = true;
                try
                {
                    Box.Text = Value;
                }
                finally
                {
                    Suspend = false;
                }
            }

            public void SetEnabled(bool enabled)
            {
                foreach (UIElement part in new UIElement[] { Box, Caret })
                {
                    try
                    {
                        part.IsEnabled = enabled;
                    }
                    catch (Exception)
                    {
                    }
                }
                if (!enabled) Close();
            }

            // ------------------------------------------------------------------
            internal void Fill(IEnumerable<string> names)
            {
                List.Items.Clear();
                foreach (string name in names) List.Items.Add(name);
            }

            internal void Open(List<string> names)
            {
                Fill(names);
                try
                {
                    // At least as wide as the box, as a ComboBox's list is.
                    Shell.MinWidth = Element.ActualWidth;
                }
                catch (Exception)
                {
                }
                Popup.IsOpen = names.Count > 0;
            }

            internal void Close()
            {
                try
                {
                    Popup.IsOpen = false;
                }
                catch (Exception)
                {
                }
            }

            internal void Typed(object sender, TextChangedEventArgs args)
            {
                if (Suspend) return;
                string text = Text();
                Value = Resolve(Items, text);
                List<string> names = Shown(Items, text, Value, Matcher);
                if (text.Trim().Length > 0 && string.IsNullOrEmpty(Value)) Open(names);
                else Close();
                Tell();
            }

            internal void ShowAll(object sender, RoutedEventArgs args)
            {
                Open(Items);
                if (Items.Contains(Value)) List.SelectedItem = Value;
                try
                {
                    Box.Focus();
                }
                catch (Exception)
                {
                }
            }

            internal void KeyPressed(object sender, KeyEventArgs args)
            {
                Key key;
                try
                {
                    key = args.Key;
                }
                catch (Exception)
                {
                    return;
                }
                int count = List.Items.Count;
                if (key == Key.Down || key == Key.Up)
                {
                    if (!Popup.IsOpen)
                    {
                        Open(Shown(Items, Text(), Value, Matcher));
                        count = List.Items.Count;
                    }
                    if (count > 0)
                    {
                        int step = key == Key.Down ? 1 : -1;
                        int index = Math.Max(0, Math.Min(count - 1, List.SelectedIndex + step));
                        List.SelectedIndex = index;
                        List.ScrollIntoView(List.SelectedItem);
                    }
                    args.Handled = true;
                }
                else if (key == Key.Enter && Popup.IsOpen)
                {
                    if (List.SelectedItem != null) Pick(List.SelectedItem);
                    else if (count == 1) Pick(List.Items[0]);
                    args.Handled = true;
                }
                else if (key == Key.Escape && Popup.IsOpen)
                {
                    Close();
                    args.Handled = true;
                }
            }

            internal void Clicked(object sender, MouseButtonEventArgs args)
            {
                // Only a press on a name picks it - not one on the scroll bar.
                DependencyObject item;
                try
                {
                    item = ItemsControl.ContainerFromElement(List, args.OriginalSource as DependencyObject);
                }
                catch (Exception)
                {
                    item = null;
                }
                if (item is ListBoxItem && List.SelectedItem != null) Pick(List.SelectedItem);
            }

            public void Pick(object name)
            {
                string text = name == null ? "" : PyStr(name);
                Close();
                SetValue(text);
                try
                {
                    Box.Focus();
                    Box.CaretIndex = Text().Length;
                }
                catch (Exception)
                {
                }
                Tell();
            }

            internal void Tell()
            {
                if (OnChange != null)
                {
                    try
                    {
                        OnChange(this);
                    }
                    catch (Exception)
                    {
                    }
                }
            }
        }
    }
}
