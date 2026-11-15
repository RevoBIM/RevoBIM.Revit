using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;

namespace RevoBIM.UI.ProSheets
{
    public static partial class PsUi
    {
        /// <summary>
        /// A themed message, question or result window (ProSheetsPrompt.xaml).
        /// Results are reported here, never in an output window.
        ///
        /// Show() returns the button pressed: "primary", "secondary", "extra"
        /// (only seen if the extra handler closes the window), or null when the
        /// window was closed another way.
        /// </summary>
        public class Prompt
        {
            public string Answer;
            public string InputValue;
            public Window Window;
            public Chrome Chrome;
            public bool WantInput;

            public Prompt(string title = "Pro Sheets Exporter", string headline = "", string message = "",
                string detail = "", string primary = "Close", string secondary = null, string extra = null,
                string themeName = "dark", Window owner = null, bool wantInput = false, string inputText = "")
            {
                Answer = null;
                InputValue = inputText;
                Window = LoadWindow("ProSheetsPrompt.xaml", themeName);
                Chrome = new Chrome(Window);
                // No egg here. A message window is something you dismiss, often
                // several in a row, and arming it turned "clicking Close" into a
                // way to start a game.

                Set("SubtitleText", title);
                Set("HeadlineText", headline);
                Set("MessageText", message);
                Set("DetailText", detail);

                if (string.IsNullOrEmpty(detail))
                {
                    if (Find(Window, "DetailScroller") is FrameworkElement scroller)
                    {
                        try
                        {
                            ((UIElement)scroller.Parent).Visibility = Visibility.Collapsed;
                        }
                        catch (Exception)
                        {
                        }
                    }
                }

                Button("PrimaryButton", primary, "primary");
                Button("SecondaryButton", secondary, "secondary");
                Button("ExtraButton", extra, "extra");

                if (Find(Window, "CopyButton") is ButtonBase copyButton)
                {
                    if (!string.IsNullOrEmpty(detail))
                    {
                        try
                        {
                            copyButton.Click += Copy;
                        }
                        catch (Exception)
                        {
                        }
                    }
                    else
                    {
                        try
                        {
                            copyButton.Visibility = Visibility.Collapsed;
                        }
                        catch (Exception)
                        {
                        }
                    }
                }

                WantInput = wantInput;
                if (wantInput) MakeInput(inputText);

                if (owner != null)
                {
                    try
                    {
                        Window.Owner = owner;
                    }
                    catch (Exception)
                    {
                    }
                }
            }

            internal void Set(string name, string text)
            {
                object element = Find(Window, name);
                if (element == null) return;
                try
                {
                    SetTextCore(element, text ?? "");
                }
                catch (Exception)
                {
                }
            }

            internal void Button(string name, string caption, string answer)
            {
                if (!(Find(Window, name) is ButtonBase button)) return;
                if (string.IsNullOrEmpty(caption))
                {
                    try
                    {
                        button.Visibility = Visibility.Collapsed;
                    }
                    catch (Exception)
                    {
                    }
                    return;
                }
                try
                {
                    button.Content = caption;
                    button.Visibility = Visibility.Visible;
                    button.Click += MakeAnswer(answer);
                }
                catch (Exception)
                {
                }
            }

            internal RoutedEventHandler MakeAnswer(string answer)
            {
                return (sender, args) =>
                {
                    Answer = answer;
                    if (WantInput)
                    {
                        if (Find(Window, "PromptInput") is TextBox box)
                        {
                            try
                            {
                                InputValue = box.Text ?? "";
                            }
                            catch (Exception)
                            {
                            }
                        }
                    }
                    if (answer == "extra")
                    {
                        // The extra button acts and leaves the window open.
                        return;
                    }
                    try
                    {
                        Window.DialogResult = answer == "primary";
                    }
                    catch (Exception)
                    {
                    }
                    try
                    {
                        Window.Close();
                    }
                    catch (Exception)
                    {
                    }
                };
            }

            internal void MakeInput(string start)
            {
                if (!(Find(Window, "MessageText") is FrameworkElement host)) return;
                try
                {
                    var box = new TextBox();
                    box.Name = "PromptInput";
                    box.Text = start ?? "";
                    box.Margin = ((FrameworkElement)Window.FindName("MessageText")).Margin;
                    box.MinWidth = 320;
                    box.HorizontalAlignment = HorizontalAlignment.Stretch;
                    var parent = (Panel)host.Parent;
                    parent.Children.Add(box);
                    Window.RegisterName("PromptInput", box);
                    box.Focus();
                    box.SelectAll();
                }
                catch (Exception)
                {
                }
            }

            internal void Copy(object sender, RoutedEventArgs args)
            {
                try
                {
                    if (Find(Window, "DetailText") is TextBlock element)
                        Clipboard.SetText(element.Text ?? "");
                    if (Find(Window, "CopyButton") is ContentControl button)
                        button.Content = "Copied";
                }
                catch (Exception)
                {
                }
            }

            /// <summary>Wire a handler to the extra button (which leaves the window open).</summary>
            public void OnExtra(RoutedEventHandler handler)
            {
                if (Find(Window, "ExtraButton") is ButtonBase button)
                {
                    try
                    {
                        button.Click += handler;
                    }
                    catch (Exception)
                    {
                    }
                }
            }

            public string Show()
            {
                try
                {
                    Window.ShowDialog();
                }
                catch (Exception)
                {
                    try
                    {
                        Window.Show();
                    }
                    catch (Exception)
                    {
                    }
                }
                return Answer;
            }
        }
    }
}
