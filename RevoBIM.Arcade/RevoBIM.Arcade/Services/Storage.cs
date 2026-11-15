using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;

namespace RevoBIM.Arcade.Services
{
    /// <summary>%APPDATA%\RevoBIM\arcade\ (REVOBIM_ARCADE_DIR overrides it, which the selftest uses).</summary>
    public static class ArcadePaths
    {
        public static string Folder
        {
            get
            {
                var over = Environment.GetEnvironmentVariable("REVOBIM_ARCADE_DIR");
                if (!string.IsNullOrWhiteSpace(over)) return over;
                return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "RevoBIM", "arcade");
            }
        }

        public static string SettingsFile => Path.Combine(Folder, "settings.json");
        public static string ScoresFile(string gameKey) => Path.Combine(Folder, "scores." + gameKey + ".json");
    }

    static class Atomic
    {
        public static void Write(string path, string text)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            var tmp = path + ".tmp";
            File.WriteAllText(tmp, text);
            if (File.Exists(path)) File.Replace(tmp, path, null);
            else File.Move(tmp, path);
        }
    }

    public sealed class ArcadeSettings
    {
        public string? LastGame { get; set; }
        public string PlayerName { get; set; } = Environment.UserName;
    }

    /// <summary>One settings file. Never throws: a missing or damaged file gives defaults.</summary>
    public static class SettingsStore
    {
        static readonly JsonSerializerOptions Json = new JsonSerializerOptions { WriteIndented = true };

        public static ArcadeSettings Load()
        {
            try
            {
                if (File.Exists(ArcadePaths.SettingsFile))
                    return JsonSerializer.Deserialize<ArcadeSettings>(File.ReadAllText(ArcadePaths.SettingsFile)) ?? new ArcadeSettings();
            }
            catch { /* fall through to defaults */ }
            return new ArcadeSettings();
        }

        public static void Save(ArcadeSettings settings)
        {
            try { Atomic.Write(ArcadePaths.SettingsFile, JsonSerializer.Serialize(settings, Json)); }
            catch { /* settings are a convenience; never fail a game over them */ }
        }
    }

    public sealed class ScoreEntry
    {
        public DateTime When { get; set; }
        public string Player { get; set; } = "";
        public int Score { get; set; }
    }

    /// <summary>One scores file per game, best first, capped.</summary>
    public sealed class ScoreStore
    {
        const int Kept = 300;
        static readonly JsonSerializerOptions Json = new JsonSerializerOptions { WriteIndented = true };
        readonly string _key;

        public ScoreStore(string gameKey) { _key = gameKey; }

        public List<ScoreEntry> Ranked(int limit = 10)
        {
            try
            {
                var path = ArcadePaths.ScoresFile(_key);
                if (!File.Exists(path)) return new List<ScoreEntry>();
                var all = JsonSerializer.Deserialize<List<ScoreEntry>>(File.ReadAllText(path)) ?? new List<ScoreEntry>();
                return all.OrderByDescending(e => e.Score).ThenBy(e => e.When).Take(limit).ToList();
            }
            catch { return new List<ScoreEntry>(); }
        }

        public int Best() => Ranked(1).FirstOrDefault()?.Score ?? 0;

        public void Record(int score, string? player = null)
        {
            try
            {
                var all = Ranked(int.MaxValue);
                all.Add(new ScoreEntry { When = DateTime.Now, Player = player ?? SettingsStore.Load().PlayerName, Score = score });
                var kept = all.OrderByDescending(e => e.Score).ThenBy(e => e.When).Take(Kept).ToList();
                Atomic.Write(ArcadePaths.ScoresFile(_key), JsonSerializer.Serialize(kept, Json));
            }
            catch { /* a lost score is not worth a crash */ }
        }
    }
}
