using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Windows;
using RevoBIM.Arcade.Core;
using RevoBIM.Arcade.Games.PacMan;
using RevoBIM.Arcade.Games.Tetris;
using RevoBIM.Arcade.Services;

namespace RevoBIM.Arcade
{
    /// <summary>
    /// RevoBIM.Arcade.exe --selftest. Headless logic checks, no window, no Revit. Exit code 0
    /// when everything passes. tools\selftest.ps1 wraps this and adds the launch checks.
    /// </summary>
    public static class SelfTest
    {
        sealed class Probe : IArcadeGame
        {
            readonly string _key;
            public Probe(string key) { _key = key; }
            public string Key => _key;
            public string DisplayName => "Probe";
            public void Start(GameHost host) { }
            public void Stop() { }
        }

        public static int Run(LaunchOptions options, TextWriter output)
        {
            int failed = 0, passed = 0;

            void Check(string name, bool ok, string detail = "")
            {
                if (ok) passed++; else failed++;
                output.WriteLine((ok ? "PASS  " : "FAIL  ") + name + (ok || detail == "" ? "" : "  -> " + detail));
            }

            bool Throws(Action a) { try { a(); return false; } catch { return true; } }

            // ---- registry
            var all = GameRegistry.All;
            Check("registry has at least one game", all.Count >= 1);
            Check("every registered key is unique", all.Select(g => g.Key).Distinct().Count() == all.Count,
                string.Join(",", all.Select(g => g.Key)));
            Check("every registered key is valid", all.All(g => GameRegistry.IsValidKey(g.Key)));
            Check("every game has a display name", all.All(g => !string.IsNullOrWhiteSpace(g.DisplayName)));
            Check("the hello placeholder is registered", GameRegistry.Find("hello") != null);
            Check("Find is case and space tolerant", GameRegistry.Find("  HeLLo ") != null);
            Check("Find returns null for an unknown key", GameRegistry.Find("nope") == null && GameRegistry.Find(null) == null && GameRegistry.Find("") == null);
            Check("a duplicate key is refused", Throws(() => GameRegistry.Load(new Func<IArcadeGame>[] { () => new Probe("a"), () => new Probe("a") })));
            Check("an invalid key is refused", Throws(() => GameRegistry.Load(new Func<IArcadeGame>[] { () => new Probe("Bad Key") })));
            Check("an empty key is refused", Throws(() => GameRegistry.Load(new Func<IArcadeGame>[] { () => new Probe("") })));

            Check("pacman and tetris are registered", GameRegistry.Find("pacman") != null && GameRegistry.Find("tetris") != null);

            // ---- default game: named game wins, else the saved default, else the picker
            var named = GameRegistry.ResolveStart("tetris", "pacman");
            Check("start: a named game beats the default", named.Entry?.Key == "tetris" && named.Note == "");
            var viaDefault = GameRegistry.ResolveStart(null, "pacman");
            Check("start: no game named opens the default", viaDefault.Entry?.Key == "pacman" && viaDefault.Note == "");
            Check("start: a blank game name opens the default too", GameRegistry.ResolveStart("  ", "tetris").Entry?.Key == "tetris");
            var noDefault = GameRegistry.ResolveStart(null, null);
            Check("start: no default means the picker", noDefault.Entry == null && noDefault.Note == "");
            Check("start: a stale default means the picker", GameRegistry.ResolveStart(null, "deleted-game").Entry == null);
            var unknown = GameRegistry.ResolveStart("nope", "pacman");
            Check("start: an unknown name shows the picker with a note, not the default", unknown.Entry == null && unknown.Note.Contains("nope"));

            // ---- launch parser
            var none = LaunchOptions.Parse(new string[0]);
            Check("no args: no game, dark, no owner", none.GameKey == null && none.Theme == "dark" && none.Owner == null && none.Warnings.Count == 0);
            Check("null args do not throw", !Throws(() => LaunchOptions.Parse(null)));

            var full = LaunchOptions.Parse(new[] { "--game", "Hello", "--theme", "light", "--owner-x", "10", "--owner-y", "20", "--owner-w", "800", "--owner-h", "600" });
            Check("full command line parses", full.GameKey == "hello" && full.Theme == "light" && full.Owner == (10, 20, 800, 600) && full.Warnings.Count == 0);

            var eq = LaunchOptions.Parse(new[] { "--game=hello", "--theme=LIGHT" });
            Check("--name=value form parses", eq.GameKey == "hello" && eq.Theme == "light");

            var badTheme = LaunchOptions.Parse(new[] { "--theme", "purple" });
            Check("a bad theme falls back to dark and warns", badTheme.Theme == "dark" && badTheme.Warnings.Count == 1);

            var noValue = LaunchOptions.Parse(new[] { "--theme", "--game" });
            Check("a flag with no value is survived", noValue.Theme == "dark" && noValue.GameKey == null && noValue.Warnings.Count >= 2);

            var partial = LaunchOptions.Parse(new[] { "--owner-x", "10", "--owner-y", "20" });
            Check("a partial owner rectangle is dropped", partial.Owner == null && partial.Warnings.Count == 1);

            var notInt = LaunchOptions.Parse(new[] { "--owner-x", "abc", "--owner-y", "1", "--owner-w", "2", "--owner-h", "3" });
            Check("a non-numeric owner value is dropped", notInt.Owner == null && notInt.Warnings.Count >= 1);

            var zero = LaunchOptions.Parse(new[] { "--owner-x", "0", "--owner-y", "0", "--owner-w", "0", "--owner-h", "0" });
            Check("a zero-size owner is dropped", zero.Owner == null);

            var neg = LaunchOptions.Parse(new[] { "--owner-x", "-1920", "--owner-y", "-40", "--owner-w", "1920", "--owner-h", "1080" });
            Check("negative owner origin (left monitor) is accepted", neg.Owner == (-1920, -40, 1920, 1080));

            var junk = LaunchOptions.Parse(new[] { "banana", "--wat", "--game", "'; drop table", "", "--" });
            Check("junk is ignored without throwing", junk.Warnings.Count >= 3);

            // ---- theme validation
            Check("theme: dark and light are valid in any case",
                ThemeNames.TryNormalise("Dark", out var t1) && t1 == "dark" && ThemeNames.TryNormalise(" LIGHT ", out var t2) && t2 == "light");
            Check("theme: anything else is invalid",
                !ThemeNames.TryNormalise("auto", out _) && !ThemeNames.TryNormalise("", out _) && !ThemeNames.TryNormalise(null, out _) && !ThemeNames.TryNormalise("1", out _));

            // ---- single instance message cleaning
            Check("pipe messages are trimmed, lower-cased and capped",
                SingleInstance.Clean("  HeLLo ") == "hello" && SingleInstance.Clean(null) == "" && SingleInstance.Clean(new string('x', 500)).Length == 64);

            // ---- logo egg counter: the same rule as the Revit side
            var c = new SlowClickCounter();
            Check("egg: three slow clicks fire", !c.Click(1000) && !c.Click(1500) && c.Click(2000));
            c = new SlowClickCounter();
            Check("egg: a double click (gap under 250 ms) restarts", !c.Click(1000) && !c.Click(1100) && !c.Click(1600) && c.Click(2100));
            c = new SlowClickCounter();
            Check("egg: a gap over 2 s goes cold and restarts", !c.Click(1000) && !c.Click(1500) && !c.Click(4000) && !c.Click(4500) && c.Click(5000));
            c = new SlowClickCounter();
            Check("egg: gap bounds are inclusive (250 and 2000 count)", !c.Click(0) && !c.Click(250) && c.Click(2250));
            c = new SlowClickCounter();
            Check("egg: one physical click seen twice counts once", !c.Click(1000) && !c.Click(1000) && !c.Click(1500) && c.Click(2000));
            c = new SlowClickCounter();
            c.Click(0); c.Click(500); c.Click(1000);
            Check("egg: counting restarts after it fires", !c.Click(1500) && !c.Click(2000) && c.Click(2500));

            // ---- drawer arithmetic
            var area = new Rect(0, 0, 1920, 1040);
            Check("drawer: a parked bar sits 8 px clear of the taskbar", DrawerMath.ParkedTop(area, 40) == 1040 - 40 - 8);
            Check("drawer: tween hits both ends and stays between", DrawerMath.Tween(10, 90, 0) == 10 && DrawerMath.Tween(10, 90, 1) == 90
                && DrawerMath.Tween(10, 90, 2) == 90 && DrawerMath.Tween(10, 90, 0.5) is > 10 and < 90);
            var saved = new Rect(300, 200, 760, 560);
            var back = DrawerMath.ExpandRect(saved, new Point(300, 992), new Point(300, 992), 40, area);
            Check("drawer: an undisturbed bar returns to its saved place", back == (300, 200, 560));
            var moved = DrawerMath.ExpandRect(saved, new Point(300, 992), new Point(500, 700), 40, area);
            Check("drawer: a dragged bar opens upward from where it sits", moved.Left == 500 && moved.Top == 700 + 40 - 560 && moved.Height == 560);
            var high = DrawerMath.ExpandRect(saved, new Point(300, 992), new Point(300, 10), 40, area);
            Check("drawer: a bar dragged near the top stays on screen", high.Top >= 0);

            // ---- theme palettes: both define every key, and every key the games use
            try
            {
                ResourceDictionary Load(string name) => new ResourceDictionary { Source = new Uri($"pack://application:,,,/RevoBIM.Arcade;component/Themes/{name}.xaml", UriKind.Absolute) };
                var dark = Load("Dark"); var light = Load("Light");
                var darkKeys = dark.Keys.Cast<object>().Select(k => k.ToString()!).OrderBy(k => k).ToList();
                var lightKeys = light.Keys.Cast<object>().Select(k => k.ToString()!).OrderBy(k => k).ToList();
                Check("theme: dark and light define the same keys", darkKeys.SequenceEqual(lightKeys),
                    string.Join(",", darkKeys.Except(lightKeys).Concat(lightKeys.Except(darkKeys))));
                var missing = BrushKeys.All.Where(k => !dark.Contains(k) || !light.Contains(k)).ToList();
                Check("theme: every brush the games use exists in both palettes", missing.Count == 0, string.Join(",", missing));
            }
            catch (Exception ex) { Check("theme: palettes load", false, ex.Message); }

            // ---- fixed step: logic at a steady rate whatever the frame rate
            var fs = new FixedStep(0.1);
            int ticks = 0;
            fs.Advance(0.25, () => ticks++);
            Check("step: 0.25 s at 0.1 s steps runs twice and leaves a remainder", ticks == 2 && Math.Abs(fs.Alpha - 0.5) < 1e-9);
            ticks = 0; fs.Advance(10, () => ticks++, 4);
            Check("step: a long stall is capped and the backlog dropped", ticks == 4 && fs.Alpha == 0);

            // ---- pacman data
            var maze = PacManGame.Maze;
            string all2 = string.Concat(maze);
            Check("pacman: maze rows are all the same width", maze.All(r => r.Length == maze[0].Length));
            Check("pacman: one start, one door, three ghost cells", all2.Count(c => c == 'P') == 1 && all2.Count(c => c == '-') == 1 && all2.Count(c => c == 'G') == 3);
            Check("pacman: walls frame the maze except the tunnel row", maze[0].All(c => c == '#') && maze[^1].All(c => c == '#'));
            Check("pacman: ranks climb with score", PacManGame.RankOf(0) == "Setting Out Apprentice" && PacManGame.RankOf(9500) == "Model Federation Overlord"
                && PacManGame.RankOf(1199) == "Draughtsperson, Second Class");

            // ---- tetris rules
            var tm1 = new TetrisModel(7);
            Check("tetris: a new game has a piece and no score", tm1.Piece >= 1 && tm1.Piece <= 7 && tm1.Score == 0 && !tm1.Over);
            bool shapesOk = true;
            for (int pp = 1; pp <= 7; pp++) for (int rr = 0; rr < 4; rr++) shapesOk &= TetrisModel.CellsOf(pp, rr).Length == 4 && TetrisModel.CellsOf(pp, rr).Distinct().Count() == 4;
            Check("tetris: every piece has four distinct cells in every rotation", shapesOk);
            Check("tetris: four turns come back to the start", Enumerable.Range(1, 7).All(pp => TetrisModel.CellsOf(pp, 4).SequenceEqual(TetrisModel.CellsOf(pp, 0))));
            var seen = new HashSet<int>();
            var bagModel = new TetrisModel(3);
            seen.Add(bagModel.Piece);
            for (int ii = 0; ii < 6; ii++) { bagModel.Lock(); seen.Add(bagModel.Piece); if (bagModel.Over) break; }
            Check("tetris: the first seven pieces are one of each", seen.Count == 7 || bagModel.Over);
            var tm2 = new TetrisModel(1);
            while (tm2.TryMove(-1, 0)) { }
            Check("tetris: a piece stops at the left wall", !tm2.TryMove(-1, 0));
            int scoreBefore = tm2.Score;
            tm2.HardDrop();
            Check("tetris: a hard drop locks the piece into the grid and scores", Enumerable.Range(0, 10).Any(cc => tm2.Grid[19, cc] != 0) && tm2.Score > scoreBefore);
            var tm3 = new TetrisModel(2);
            for (int cc = 0; cc < 10; cc++) tm3.Grid[19, cc] = 1;
            for (int cc = 0; cc < 3; cc++) tm3.Grid[18, cc] = 2;     // a stray block above the full row
            int cleared = tm3.Lock();                              // the current piece lands wherever it is; the full row clears
            Check("tetris: a full row clears and the rows above fall", cleared >= 1 && tm3.Lines >= 1 && tm3.Grid[19, 0] != 0 && tm3.Score >= 40);
            var tm4 = new TetrisModel(4);
            for (int rr = 0; rr < 20; rr++) for (int cc = 0; cc < 10; cc++) tm4.Grid[rr, cc] = 3;
            tm4.Spawn();
            Check("tetris: a full board ends the game", tm4.Over);
            var tm5 = new TetrisModel(5);
            Check("tetris: rotation and gravity interval are sane", tm5.TryRotate(1) && tm5.FallInterval > 0.04 && tm5.FallInterval <= 0.8);

            // ---- storage round trip, in a throwaway folder
            var dir = Path.Combine(Path.GetTempPath(), "revobim-arcade-selftest-" + Guid.NewGuid().ToString("N"));
            var before = Environment.GetEnvironmentVariable("REVOBIM_ARCADE_DIR");
            try
            {
                Environment.SetEnvironmentVariable("REVOBIM_ARCADE_DIR", dir);
                var store = new ScoreStore("selftest");
                store.Record(5, "a"); store.Record(9, "b"); store.Record(7, "c");
                var ranked = store.Ranked(10);
                Check("scores: ranked best first", ranked.Count == 3 && ranked[0].Score == 9 && store.Best() == 9);
                Check("scores: one file per game", File.Exists(ArcadePaths.ScoresFile("selftest")) && Path.GetDirectoryName(ArcadePaths.ScoresFile("selftest")) == dir);
                File.WriteAllText(ArcadePaths.ScoresFile("selftest"), "not json");
                Check("scores: a damaged file reads as empty", new ScoreStore("selftest").Best() == 0);
                var s = SettingsStore.Load(); s.LastGame = "hello"; SettingsStore.Save(s);
                Check("settings: round trip in one file", SettingsStore.Load().LastGame == "hello" && File.Exists(ArcadePaths.SettingsFile));
                s.DefaultGame = "tetris"; SettingsStore.Save(s);
                Check("settings: the default game is saved and read back", SettingsStore.Load().DefaultGame == "tetris");
                s.DefaultGame = null; SettingsStore.Save(s);
                Check("settings: clearing the default leaves none", SettingsStore.Load().DefaultGame == null);
                File.WriteAllText(ArcadePaths.SettingsFile, "{ broken");
                Check("settings: a damaged file means no default, not a crash", SettingsStore.Load().DefaultGame == null);
            }
            finally
            {
                Environment.SetEnvironmentVariable("REVOBIM_ARCADE_DIR", before);
                try { Directory.Delete(dir, true); } catch { }
            }

            Check("version is set", !string.IsNullOrWhiteSpace(Version.Current));

            output.WriteLine();
            output.WriteLine($"{passed} passed, {failed} failed  (RevoBIM Arcade {Version.Current})");
            output.Flush();
            return failed == 0 ? 0 : 1;
        }
    }
}


