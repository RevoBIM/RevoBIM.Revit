using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using RevoBIM.Arcade.Games.Hello;
using RevoBIM.Arcade.Games.PacMan;
using RevoBIM.Arcade.Games.Tetris;

namespace RevoBIM.Arcade.Core
{
    /// <summary>
    /// The one list of games. To add a game: create Games\&lt;Name&gt;\ and add one line to
    /// <see cref="Build"/>. Nothing else changes.
    /// </summary>
    public static class GameRegistry
    {
        static readonly Regex KeyPattern = new Regex("^[a-z0-9][a-z0-9-]*$", RegexOptions.Compiled);

        /// <summary>Registration list. One line per game.</summary>
        static IEnumerable<Func<IArcadeGame>> Build()
        {
            yield return () => new PacManGame();
            yield return () => new TetrisGame();
            yield return () => new HelloGame();
        }

        static List<Entry>? _all;

        public sealed class Entry
        {
            public Entry(string key, string name, Func<IArcadeGame> create) { Key = key; DisplayName = name; Create = create; }
            public string Key { get; }
            public string DisplayName { get; }
            public Func<IArcadeGame> Create { get; }
        }

        public static IReadOnlyList<Entry> All => _all ??= Load(Build());

        /// <summary>Builds the entry list from factories. Throws on a bad or duplicate key.</summary>
        public static List<Entry> Load(IEnumerable<Func<IArcadeGame>> factories)
        {
            var list = new List<Entry>();
            foreach (var make in factories)
            {
                var game = make();
                var key = (game.Key ?? string.Empty);
                if (!IsValidKey(key))
                    throw new InvalidOperationException($"Game key '{key}' is not valid (lower-case letters, digits and '-').");
                if (list.Any(e => e.Key == key))
                    throw new InvalidOperationException($"Game key '{key}' is registered twice.");
                list.Add(new Entry(key, game.DisplayName, make));
            }
            return list;
        }

        public static bool IsValidKey(string? key) => !string.IsNullOrEmpty(key) && KeyPattern.IsMatch(key);

        /// <summary>
        /// What to open at start-up. A game named on the command line wins (an unknown name gives no
        /// game and a note, so the picker explains itself); with none named, the saved default game
        /// if there is one; otherwise nothing, which means the picker.
        /// </summary>
        public static (Entry? Entry, string Note) ResolveStart(string? requested, string? defaultKey)
        {
            if (!string.IsNullOrWhiteSpace(requested))
            {
                var named = Find(requested);
                return named != null ? (named, "") : (null, $"There is no game called '{requested.Trim()}'. Pick one below.");
            }
            return (Find(defaultKey), "");
        }

        public static Entry? Find(string? key)
        {
            if (string.IsNullOrWhiteSpace(key)) return null;
            var k = key.Trim().ToLowerInvariant();
            return All.FirstOrDefault(e => e.Key == k);
        }
    }
}
