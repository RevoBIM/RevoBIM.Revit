using System;
using System.Windows;
using RevoBIM.Arcade.Core;

namespace RevoBIM.Arcade.Services
{
    /// <summary>
    /// Light and dark are two ResourceDictionaries with the same brush keys. Layouts use
    /// DynamicResource only, so swapping the dictionary restyles everything.
    /// </summary>
    public static class ThemeService
    {
        public static string Current { get; private set; } = ThemeNames.Dark;

        static ResourceDictionary? _active;

        public static void Apply(string? theme)
        {
            if (!ThemeNames.TryNormalise(theme, out var name)) name = ThemeNames.Dark;
            var dict = new ResourceDictionary
            {
                Source = new Uri($"pack://application:,,,/RevoBIM.Arcade;component/Themes/{(name == ThemeNames.Light ? "Light" : "Dark")}.xaml", UriKind.Absolute)
            };
            var merged = Application.Current.Resources.MergedDictionaries;
            if (_active != null) merged.Remove(_active);
            merged.Add(dict);
            _active = dict;
            Current = name;
        }
    }
}
