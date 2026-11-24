using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using RevoBIM.Tools.BwicPenetration;

namespace RevoBIM.UI.BwicPenetration
{
    /// <summary>
    /// One family slot in the main window: list, type, preview and summary. The four cards (wall and slab, rectangular and circular)
    /// all behave the same, so they share this rather than four copies of the same handlers.
    /// </summary>
    internal sealed class FamilyCard
    {
        private readonly BwiMainWindow _window;
        public readonly string Slot;
        private readonly ComboBox _familyCb, _typeCb;
        private readonly Image _image;
        private readonly TextBlock _noprev, _summary;
        private List<string> _names = new List<string>();
        private Dictionary<string, List<string>> _types = new Dictionary<string, List<string>>();
        private bool _loading;
        private readonly string _familyKey, _typeKey;

        public FamilyCard(BwiMainWindow window, string slot, ComboBox familyCb, ComboBox typeCb, Image image, TextBlock noprev, TextBlock summary)
        {
            _window = window;
            Slot = slot;
            _familyCb = familyCb;
            _typeCb = typeCb;
            _image = image;
            _noprev = noprev;
            _summary = summary;
            _familyKey = BwicFamilies.SlotFamilyKey(slot);
            _typeKey = BwicFamilies.SlotTypeKey(slot);
            familyCb.SelectionChanged += FamilyChanged;
            typeCb.SelectionChanged += TypeChanged;
            // the list is read again whenever it is opened, so a family loaded into the project while the tool is open turns up
            familyCb.DropDownOpened += (s, e) => _window.ReloadFamilies();
        }

        /// <summary>families: what this slot offers; every: all the project's families (a saved choice of the other shape is kept and labelled).</summary>
        public void Fill(List<GenericFamily> families, List<GenericFamily> every)
        {
            string wanted = BwicFamilies.Get(_window.Settings, _familyKey);
            if (wanted.Length == 0 && Slot == "wall") wanted = BwicCore.FamilyName;
            _loading = true;
            try
            {
                _names = families.Select(f => f.Name).ToList();
                _types = families.ToDictionary(f => f.Name, f => new List<string>(f.Types));
                _familyCb.Items.Clear();
                var loaded = (every ?? families).ToDictionary(f => f.Name, f => new List<string>(f.Types));
                int start;
                if (wanted.Length > 0 && !_names.Contains(wanted))
                {
                    // keep a saved family rather than quietly swap it for another: one not loaded, or one of the other shape
                    _names.Insert(0, wanted);
                    _types[wanted] = loaded.ContainsKey(wanted) ? loaded[wanted] : new List<string>();
                    string other = Slot == "wall" || Slot == "slab_rect" ? "circular" : "rectangular";
                    _familyCb.Items.Add(wanted + "   [" + (loaded.ContainsKey(wanted) ? other : "not loaded") + "]");
                    start = 1;
                }
                else start = 0;
                var profiles = _window.Profiles;
                var rest = BwicFamilies.SetFirst(_names.Skip(start), profiles);
                _names = _names.Take(start).Concat(rest).ToList();
                if (start > 0 && BwicFamilies.IsSet(wanted, profiles)) ColourItem(0, true);
                foreach (string name in _names.Skip(start)) _familyCb.Items.Add(ListItem(name, BwicFamilies.IsSet(name, profiles)));
                if (_names.Count == 0)
                    _familyCb.Items.Add(Slot == "wall_circ" || Slot == "slab_circ" ? "<no circular generic model families>" : "<no rectangular generic model families>");
                _familyCb.SelectedIndex = _names.Contains(wanted) ? _names.IndexOf(wanted) : 0;
                FillTypes();
            }
            finally
            {
                _loading = false;
            }
            Refresh();
        }

        /// <summary>A list entry: green with a tick once the family is set up.</summary>
        private ComboBoxItem ListItem(string label, bool ready)
        {
            var item = new ComboBoxItem { Content = ready ? "✓  " + label : label };
            if (ready)
            {
                item.Foreground = (Brush)_window.Win.FindResource("Green");
                item.FontWeight = FontWeights.SemiBold;
            }
            return item;
        }

        private void ColourItem(int index, bool ready)
        {
            object label = _familyCb.Items[index];
            _familyCb.Items[index] = ListItem(label.ToString(), ready);
        }

        private void FillTypes()
        {
            string family = Family();
            List<string> types;
            if (!_types.TryGetValue(family, out types)) types = new List<string>();
            string wanted = _typeKey.Length > 0 ? BwicFamilies.Get(_window.Settings, _typeKey) : "";
            _typeCb.Items.Clear();
            foreach (string name in types) _typeCb.Items.Add(name);
            if (wanted.Length > 0 && !types.Contains(wanted) && types.Count == 0)
            {
                _typeCb.Items.Add(wanted);
                types = new List<string> { wanted };
            }
            _typeCb.SelectedIndex = types.Contains(wanted) ? types.IndexOf(wanted) : (types.Count > 0 ? 0 : -1);
        }

        public string Family()
        {
            int index = _familyCb.SelectedIndex;
            return index >= 0 && index < _names.Count ? _names[index] : "";
        }

        public string TypeName()
        {
            object chosen = _typeCb.SelectedItem;
            return chosen != null ? chosen.ToString() : "";
        }

        private void FamilyChanged(object sender, SelectionChangedEventArgs args)
        {
            // a change bubbles up from the type list too; only the family list itself counts here
            if (_loading || args.OriginalSource != _familyCb) return;
            _loading = true;
            try { FillTypes(); }
            finally { _loading = false; }
            Store();
        }

        private void TypeChanged(object sender, SelectionChangedEventArgs args)
        {
            if (_loading || args.OriginalSource != _typeCb) return;
            Store();
        }

        /// <summary>Remember the choice at once: it is what the next run uses.</summary>
        private void Store()
        {
            var settings = _window.Settings;
            settings[_familyKey] = Family();
            if (_typeKey.Length > 0) settings[_typeKey] = TypeName();
            try
            {
                BwicCore.WriteSettings(settings);
                BwicCore.ApplySettings(settings);
            }
            catch (Exception err)
            {
                BwicCore.DebugLog("family choice not saved: " + err.Message);
            }
            Refresh();
            _window.FamilyChoiceChanged(Slot);
        }

        public void Refresh()
        {
            string family = Family();
            ImageSource image = _window.Preview(family, TypeName());
            _image.Source = image;
            _noprev.Visibility = image != null ? Visibility.Collapsed : Visibility.Visible;
            Dictionary<string, object> profile = family.Length > 0 ? BwicFamilies.Sub(_window.Profiles, family) : null;
            string text;
            if (profile != null && profile.Count > 0)
            {
                text = BwicFamilies.Summary(Slot, profile);
                _summary.ClearValue(TextBlock.ForegroundProperty);
            }
            else if (family.Length > 0)
            {
                // nothing runs until this is done
                text = "Family settings not set yet – press Family settings…, check the parameters and clearance, then Save. Placing is blocked until then.";
                _summary.Foreground = (Brush)_window.Win.FindResource("Orange");
            }
            else
            {
                text = "Pick a family.";
                _summary.ClearValue(TextBlock.ForegroundProperty);
            }
            _summary.Text = text;
        }
    }
}
