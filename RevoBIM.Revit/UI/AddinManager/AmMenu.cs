using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using Autodesk.Revit.UI;
using RevoBIM.Helpers;
using RevoBIM.Tools.AddinManager;

using Button = System.Windows.Controls.Button;

using ContextMenu = System.Windows.Controls.ContextMenu;
using MenuItem = System.Windows.Controls.MenuItem;

namespace RevoBIM.UI.AddinManager
{
    /// <summary>The right click menu for an addin row or tile, and the keyboard shortcut prompt. Port of rba_menu.py.</summary>
    internal static class AmMenu
    {
        private const int MaxSequence = 5;

        public static ContextMenu Build(AmPane pane, AmItem item)
        {
            var menu = new ContextMenu();
            // a menu opened by PlacementTarget has no logical parent, so it inherits none of the panel's resources
            AmXaml.MergeTheme(menu);
            AmXaml.ApplyMenuTheme(menu, pane.ThemeName);

            bool pinned = pane.PinnedKeys().Contains(item.Key);
            bool onQat = AmCore.AsList(pane.Settings, "qat").Contains(item.Key);
            bool favourite = pane.IsFavourite(item);

            Add(menu, favourite ? "Remove from favourites" : "Add to favourites", () => pane.ToggleFavourite(item),
                true, "Favourites are the grid behind the star at the top");
            Add(menu, pinned ? "Unpin from the top" : "Pin to the top", () => pane.TogglePin(item),
                true, "Keeps it in a Pinned group at the top of this panel");
            Add(menu, onQat ? "Remove from Revit's Quick Access Toolbar" : "Add to Revit's Quick Access Toolbar",
                () => ToggleQat(pane, item), item.Ribbon != null,
                "Revit keeps its own toolbar in a binary file with no API, so this is put back each time the panel opens");

            menu.Items.Add(new Separator());

            List<string> keys = CurrentShortcut(item);
            string label = keys.Count > 0 ? "Change the keyboard shortcut..." : "Assign a keyboard shortcut...";
            if (keys.Count > 0) label += "   [" + string.Join(", ", keys) + "]";
            Add(menu, label, () => AssignShortcut(pane, item), item.CommandId.Length > 0, "");
            Add(menu, "Open Revit's Keyboard Shortcuts", () => OpenRevitShortcuts(pane, item), true, "");

            menu.Items.Add(new Separator());

            Add(menu, "Copy its name", () => CopyText(pane, item.Title), true, "");
            Add(menu, "Copy its command id", () => CopyText(pane, item.CommandId), item.CommandId.Length > 0, "");
            return menu;
        }

        private static void Add(ContextMenu menu, string header, Action action, bool enabled, string tip)
        {
            var entry = new MenuItem { Header = header, IsEnabled = enabled };
            if (tip.Length > 0) entry.ToolTip = tip;
            entry.Click += (s, a) =>
            {
                try { action(); }
                catch (Exception err) { AmCore.LogException("menu/" + header, err); }
            };
            menu.Items.Add(entry);
        }

        // ------------------------------------------------------------------ actions

        private static void ToggleQat(AmPane pane, AmItem item)
        {
            List<string> keys = AmCore.AsList(pane.Settings, "qat");
            string message;
            if (keys.Contains(item.Key))
            {
                bool ok = AmRibbon.QatRemove(item.CommandId, out message);
                keys.RemoveAll(k => k == item.Key);
                AmCore.SetList(pane.Settings, "qat", keys);
                pane.SaveSettings();
                pane.SetStatus(!ok ? message : item.Title + " taken off the Quick Access Toolbar");
                return;
            }
            if (!AmRibbon.QatAdd(item, out message))
            {
                pane.SetStatus(message);
                return;
            }
            keys.Add(item.Key);
            AmCore.SetList(pane.Settings, "qat", keys);
            pane.SaveSettings();
            pane.SetStatus(item.Title + " added to the Quick Access Toolbar");
        }

        private static void CopyText(AmPane pane, string text)
        {
            for (int i = 0; i < 3; i++)
            {
                try
                {
                    Clipboard.SetDataObject(text ?? "", true);
                    pane.SetStatus("Copied: " + text);
                    return;
                }
                catch (Exception)
                {
                    System.Threading.Thread.Sleep(50);
                }
            }
            pane.SetStatus("The clipboard would not take it");
        }

        /// <summary>Posts Revit's own Keyboard Shortcuts dialog with the name on the clipboard to paste into its search box.</summary>
        private static void OpenRevitShortcuts(AmPane pane, AmItem item)
        {
            try { Clipboard.SetDataObject(item.Title, true); } catch (Exception) { }
            UIApplication uiapp = AmRibbon.UiApp;
            try
            {
                RevitCommandId command = RevitCommandId.LookupPostableCommandId(PostableCommand.KeyboardShortcuts);
                if (uiapp != null && command != null)
                {
                    uiapp.PostCommand(command);
                    pane.SetStatus("'" + item.Title + "' copied - paste it into the search box");
                    return;
                }
            }
            catch (Exception err)
            {
                AmCore.LogException("menu/postable", err);
            }
            pane.SetStatus("View > User Interface > Keyboard Shortcuts - '" + item.Title + "' is on the clipboard");
        }

        private static List<string> CurrentShortcut(AmItem item)
        {
            try
            {
                string path = AmShortcuts.PathFor(AmUi.RevitVersion());
                if (!System.IO.File.Exists(path)) return new List<string>();
                return AmShortcuts.CurrentKeys(AmShortcuts.ReadFile(path), item.CommandId);
            }
            catch (Exception err)
            {
                AmCore.LogException("menu/current_shortcut", err);
                return new List<string>();
            }
        }

        private static void AssignShortcut(AmPane pane, AmItem item)
        {
            string path = AmShortcuts.PathFor(AmUi.RevitVersion());
            string text = AmShortcuts.ReadFile(path);
            if (text.Length == 0)
            {
                pane.SetStatus("Revit's shortcut file is not at " + path);
                return;
            }
            string commandId = item.CommandId;
            if (commandId.Length == 0)
            {
                pane.SetStatus(item.Title + " has no command id, so Revit cannot bind a key to it");
                return;
            }

            ShortcutResult result = Prompt(pane, item, text, commandId);
            if (result == null) return;
            if (result.OpenRevit)
            {
                OpenRevitShortcuts(pane, item);
                return;
            }

            string paths = item.Tab + " > " + item.Panel;
            string message;
            if (result.Clear)
            {
                foreach (string one in AmShortcuts.CurrentKeys(text, commandId)) text = AmShortcuts.Remove(text, commandId, one);
                message = "Shortcut removed from " + item.Title;
            }
            else
            {
                text = AmShortcuts.Upsert(text, commandId, item.Title, paths, result.Keys);
                message = result.Keys + " assigned to " + item.Title;
            }
            pane.SetStatus(AmShortcuts.WriteFile(path, text)
                ? message + " - restart Revit for it to take effect"
                : "Revit's shortcut file would not be written - see the debug log");
        }

        // ------------------------------------------------------------------ the prompt

        private sealed class ShortcutResult
        {
            public string Keys = "";
            public bool Clear;
            public bool OpenRevit;
        }

        /// <summary>One key as Revit writes it, or "" when it is not one a shortcut can use.</summary>
        private static string KeyToken(Key key)
        {
            string name = key.ToString();
            if (name.Length == 1) return name.ToUpperInvariant();
            Match m = Regex.Match(name, @"^D(\d)$");
            if (m.Success) return m.Groups[1].Value;
            m = Regex.Match(name, @"^NumPad(\d)$");
            if (m.Success) return m.Groups[1].Value;
            if (Regex.IsMatch(name, @"^F\d{1,2}$")) return name.ToUpperInvariant();
            return "";
        }

        private static ShortcutResult Prompt(AmPane pane, AmItem item, string text, string commandId)
        {
            Window window = AmXaml.Load<Window>("RbaShortcut.xaml", pane.ThemeName);
            AmUi.Own(window, pane.HostWindow);
            Find f = new Find(window);

            f.Get<TextBlock>("VersionText").Text = "v" + AmCore.Version;
            // Ctrl+Shift+H is a perfectly good shortcut to assign, so there is no shrink drawer here
            f.Get<Button>("ShrinkBtn").Visibility = Visibility.Collapsed;

            List<Dictionary<string, string>> items = AmShortcuts.Parse(text);
            List<string> existing = AmShortcuts.CurrentKeys(text, commandId);
            f.Get<TextBlock>("SubTitle").Text = "Keyboard shortcut";
            f.Get<TextBlock>("TargetText").Text = item.Title;
            if (existing.Count > 0) f.Get<TextBlock>("CurrentText").Text = "Currently: " + string.Join(", ", existing);
            else
            {
                f.Get<TextBlock>("CurrentText").Text = "No shortcut on it at the moment";
                f.Get<Button>("ClearBtn").IsEnabled = false;
            }

            var tokens = new List<string>();
            ShortcutResult result = null;
            TextBlock keysText = f.Get<TextBlock>("KeysText");
            FrameworkElement clashPanel = f.Get<FrameworkElement>("ClashPanel");
            Button apply = f.Get<Button>("ApplyBtn");

            Func<string> shown = () => string.Concat(tokens);
            Action refresh = () =>
            {
                string value = shown();
                keysText.Text = value.Length > 0 ? value : "waiting...";
                var conflicts = value.Length > 0 ? AmShortcuts.FindConflicts(items, value, commandId) : new List<Dictionary<string, string>>();
                if (conflicts.Count > 0)
                {
                    clashPanel.Visibility = Visibility.Visible;
                    f.Get<TextBlock>("ClashTitle").Text = value + " is already taken";
                    f.Get<TextBlock>("ClashDetail").Text = string.Join("; ", conflicts.Take(3).Select(AmShortcuts.Describe));
                    apply.Content = "Assign anyway";
                }
                else
                {
                    clashPanel.Visibility = Visibility.Collapsed;
                    apply.Content = "Assign";
                }
                apply.IsEnabled = value.Length > 0;
            };

            window.PreviewKeyDown += (s, args) =>
            {
                try
                {
                    if (args.Handled) return;
                    // held with Alt, WPF reports every key as Key.System and puts the real one in SystemKey
                    Key key = args.Key == Key.System ? args.SystemKey : args.Key;
                    if (key == Key.LeftCtrl || key == Key.RightCtrl || key == Key.LeftShift || key == Key.RightShift ||
                        key == Key.LeftAlt || key == Key.RightAlt || key == Key.System || key == Key.LWin || key == Key.RWin) return;
                    args.Handled = true;
                    if (key == Key.Escape) { window.Close(); return; }
                    if (key == Key.Back) { tokens.Clear(); refresh(); return; }
                    if (key == Key.Enter && shown().Length > 0)
                    {
                        result = new ShortcutResult { Keys = shown() };
                        window.Close();
                        return;
                    }
                    string token = KeyToken(key);
                    if (token.Length == 0) return;
                    var modifiers = new List<string>();
                    ModifierKeys live = Keyboard.Modifiers;
                    if ((live & ModifierKeys.Control) != 0) modifiers.Add("Ctrl");
                    if ((live & ModifierKeys.Shift) != 0) modifiers.Add("Shift");
                    if ((live & ModifierKeys.Alt) != 0) modifiers.Add("Alt");
                    if (modifiers.Count > 0)
                    {
                        // a combination replaces the sequence: Revit will not take "VG" and "Ctrl+S" as one shortcut
                        tokens.Clear();
                        modifiers.Add(token);
                        tokens.Add(string.Join("+", modifiers));
                    }
                    else
                    {
                        if (tokens.Count > 0 && tokens[0].Contains("+")) tokens.Clear();
                        if (tokens.Count < MaxSequence) tokens.Add(token);
                    }
                    refresh();
                }
                catch (Exception err) { AmCore.LogException("prompt/key", err); }
            };
            apply.Click += (s, a) =>
            {
                if (shown().Length > 0)
                {
                    result = new ShortcutResult { Keys = shown() };
                    window.Close();
                }
            };
            f.Get<Button>("ClearBtn").Click += (s, a) => { result = new ShortcutResult { Clear = true }; window.Close(); };
            f.Get<Button>("RevitBtn").Click += (s, a) => { result = new ShortcutResult { OpenRevit = true }; window.Close(); };
            f.Get<Button>("CancelBtn").Click += (s, a) => window.Close();
            f.Get<Button>("CloseBtn").Click += (s, a) => window.Close();
            f.Get<FrameworkElement>("HeaderBar").MouseLeftButtonDown += (s, a) => { try { window.DragMove(); } catch (Exception) { } };

            refresh();
            window.ShowDialog();
            AmCore.Log("shortcut prompt returned " + (result == null ? "nothing" : result.Clear ? "clear" : result.OpenRevit ? "revit" : result.Keys));
            return result;
        }

        private sealed class Find
        {
            private readonly FrameworkElement root;
            public Find(FrameworkElement root) { this.root = root; }
            public T Get<T>(string name) where T : class { return root.FindName(name) as T; }
        }
    }
}
