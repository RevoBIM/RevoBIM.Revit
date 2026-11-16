using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Animation;

namespace RevoBIM.UI.HangerAutomation
{
    /// <summary>
    /// Tool cards that fold away to their header (icon + name). Port of fha_ui.Collapser.
    ///
    /// Clicking a header slides its body open or shut: the body's Height runs from 0 to the content's measured height
    /// (and back) on a 260 ms ease-in-out curve while it fades, and the chevron turns. When an opening finishes, the
    /// Height animation is cleared and Height set back to Auto (NaN), so the card can still grow and shrink with its
    /// content. All state is on this object; each chevron gets its own RotateTransform made here (never a named
    /// transform in XAML).
    ///
    /// Elements looked up by name (prefix "Fam" or "Flr"): Hdr&lt;prefix&gt;&lt;key&gt; (Border), Body&lt;prefix&gt;&lt;key&gt;
    /// (Border with a Child) and Chv&lt;prefix&gt;&lt;key&gt; (the chevron).
    /// </summary>
    public sealed class Collapser
    {
        public readonly Window Win;
        public readonly string Prefix;                       // HdrFamPlace / BodyFamPlace / ChvFamPlace (Flr on the floor tab)
        public readonly List<string> Keys;
        public readonly Dictionary<string, bool> Open;       // key -> is the tool open
        public readonly Dictionary<string, RotateTransform> Turn = new Dictionary<string, RotateTransform>();
        public Action OnChange;
        public Action<double> OnResize;                      // the window follows a fold: called with the height delta

        public Collapser(Window win, IEnumerable<string> keys, Action onChange = null, Action<double> onResize = null, string prefix = "Fam")
        {
            Win = win;
            Prefix = prefix;
            Keys = keys.ToList();
            Open = new Dictionary<string, bool>();
            foreach (string k in Keys) Open[k] = true;
            OnChange = onChange;
            OnResize = onResize;
            foreach (string k in Keys)
            {
                var rt = new RotateTransform(0.0);
                Turn[k] = rt;
                try
                {
                    ((UIElement)C("Chv" + Prefix + k)).RenderTransform = rt;
                }
                catch (Exception)
                {
                }
                var hdr = (UIElement)C("Hdr" + Prefix + k);
                hdr.MouseLeftButtonUp += Clicker(k);
                hdr.MouseEnter += Hover(k, true);
                hdr.MouseLeave += Hover(k, false);
            }
        }

        public object C(string name)
        {
            return Win.FindName(name);
        }

        private System.Windows.Input.MouseButtonEventHandler Clicker(string key)
        {
            return (sender, e) => Toggle(key);
        }

        private System.Windows.Input.MouseEventHandler Hover(string key, bool on)
        {
            return (sender, e) =>
            {
                try
                {
                    var hdr = (Border)C("Hdr" + Prefix + key);
                    if (on) hdr.SetResourceReference(Border.BackgroundProperty, "HoverBgBrush");
                    else hdr.Background = null;
                }
                catch (Exception)
                {
                }
            };
        }

        // ---- state
        /// <summary>The open tools' keys, lower-cased, comma-joined (what the window saves).</summary>
        public string StateText()
        {
            return string.Join(",", Keys.Where(k => Open[k]).Select(k => k.ToLowerInvariant()));
        }

        /// <summary>Restore from StateText: tools named in <paramref name="text"/> open, the rest folded, no animation.</summary>
        public void Load(string text)
        {
            var want = new HashSet<string>(StringComparer.Ordinal);
            foreach (string w in (text ?? "").Split(','))
            {
                string t = w.Trim().ToLowerInvariant();
                if (t.Length > 0) want.Add(t);
            }
            foreach (string k in Keys) Set(k, want.Contains(k.ToLowerInvariant()), false);
        }

        public bool AllOpen()
        {
            return Keys.All(k => Open[k]);
        }

        // ---- folding
        /// <summary>
        /// A header click. Opening one tool folds whichever others are open (one tool at a time); Expand all still
        /// opens every one.
        /// </summary>
        public void Toggle(string key)
        {
            bool opening = !Open[key];
            if (opening)
            {
                foreach (string k in Keys)
                    if (k != key && Open[k]) Set(k, false, true);
            }
            Set(key, opening, true);
        }

        public void SetAll(bool opened)
        {
            foreach (string k in Keys)
                if (Open[k] != opened) Set(k, opened, true);
        }

        public void Set(string key, bool opened, bool animate = true)
        {
            Open[key] = opened;
            var body = (Border)C("Body" + Prefix + key);
            RotateTransform rt;
            Turn.TryGetValue(key, out rt);
            double angle = opened ? 0.0 : -90.0;
            if (!animate)
            {
                try
                {
                    body.BeginAnimation(FrameworkElement.HeightProperty, null);
                    body.BeginAnimation(UIElement.OpacityProperty, null);
                    body.Height = opened ? double.NaN : 0.0;
                    body.Opacity = opened ? 1.0 : 0.0;
                    if (rt != null)
                    {
                        rt.BeginAnimation(RotateTransform.AngleProperty, null);
                        rt.Angle = angle;
                    }
                }
                catch (Exception)
                {
                }
                Changed();
                return;
            }
            try
            {
                double start = body.ActualHeight;
                double end;
                DoubleAnimation fade;
                if (opened)
                {
                    double width = ((FrameworkElement)C("Hdr" + Prefix + key)).ActualWidth;
                    if (width == 0.0) width = body.ActualWidth;
                    UIElement content = body.Child;
                    content.Measure(new Size(Math.Max(width, 50.0), double.PositiveInfinity));
                    end = content.DesiredSize.Height;
                    fade = FhaUi.Eased(body.Opacity, 1.0, FhaUi.SlideMs);
                }
                else
                {
                    end = 0.0;
                    fade = FhaUi.Eased(body.Opacity, 0.0, FhaUi.SlideMs * 0.8);
                }
                DoubleAnimation slide = FhaUi.Eased(start, end, FhaUi.SlideMs);
                slide.Completed += Finisher(key, opened);
                if (OnResize != null)
                {
                    try
                    {
                        OnResize(end - start);   // the window follows, on the same curve
                    }
                    catch (Exception)
                    {
                    }
                }
                body.BeginAnimation(FrameworkElement.HeightProperty, slide);
                body.BeginAnimation(UIElement.OpacityProperty, fade);
                if (rt != null) rt.BeginAnimation(RotateTransform.AngleProperty, FhaUi.Eased(rt.Angle, angle, FhaUi.SlideMs));
            }
            catch (Exception)
            {
                Set(key, opened, false);
                return;
            }
            Changed();
        }

        private EventHandler Finisher(string key, bool opened)
        {
            return (sender, e) =>
            {
                bool now;
                if (!Open.TryGetValue(key, out now) || now != opened) return;   // clicked again mid-slide: the newer animation owns it
                try
                {
                    var body = (Border)C("Body" + Prefix + key);
                    body.BeginAnimation(FrameworkElement.HeightProperty, null);
                    body.Height = opened ? double.NaN : 0.0;
                    body.BeginAnimation(UIElement.OpacityProperty, null);
                    body.Opacity = opened ? 1.0 : 0.0;
                }
                catch (Exception)
                {
                }
            };
        }

        private void Changed()
        {
            if (OnChange != null)
            {
                try
                {
                    OnChange();
                }
                catch (Exception)
                {
                }
            }
        }
    }
}
