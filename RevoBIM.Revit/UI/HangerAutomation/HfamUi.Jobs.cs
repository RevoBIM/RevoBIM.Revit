using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using RevoBIM.Tools.HangerAutomation;

namespace RevoBIM.UI.HangerAutomation
{
    public sealed partial class FamTab
    {
        // ---- refresh
        private void RefreshClick(object sender, RoutedEventArgs e)
        {
            O.StartQuiet(HfamRevit.ListJob, GotList, "Reading families...");
        }

        private void GotList(object res, string err)
        {
            var list = res as List<FamTypeItem>;
            if (!string.IsNullOrEmpty(err) || list == null)
            {
                O.Status("Could not read the families - see Copy debug");
                return;
            }
            Items = list;
            previews = new Dictionary<string, byte[]>();
            Refill();
            O.Status(Items.Count + " " + Noun + " family types");
        }

        // ---- family settings
        private void SettingsClick(object sender, RoutedEventArgs e)
        {
            FamTypeItem it = Current();
            if (it == null)
            {
                O.Status("Choose a family and type first");
                return;
            }
            if (Params.ContainsKey(it.Family))
            {
                OpenSettings(it);
                return;
            }
            string fam = it.Family;
            Action<object, string> got = (res, err) =>
            {
                List<string> names;
                string source;
                if (!(res != null && string.IsNullOrEmpty(err) && ParamsResult(res, out names, out source)))
                {
                    names = new List<string>();
                    source = "nothing - see Copy debug";
                }
                Params[fam] = new FamParams(new List<string>(names), source);
                OpenSettings(it);
            };
            O.StartQuiet(HfamRevit.ParamsJobFor(it.Id), got, "Reading the family parameters...");
        }

        /// <summary>
        /// The quiet params job answers (names, source): read as a Tuple / ValueTuple pair (Item1, Item2) so the job's
        /// exact pair type does not matter here.
        /// </summary>
        private static bool ParamsResult(object res, out List<string> names, out string source)
        {
            names = null;
            source = null;
            var direct = res as HfamRevit.FamParamNames;
            if (direct != null)
            {
                names = direct.Names != null ? direct.Names.ToList() : new List<string>();
                source = direct.Source ?? "";
                return true;
            }
            try
            {
                Type t = res.GetType();
                object a = null, b = null;
                PropertyInfo p1 = t.GetProperty("Item1"), p2 = t.GetProperty("Item2");
                FieldInfo f1 = t.GetField("Item1"), f2 = t.GetField("Item2");
                if (p1 != null && p2 != null)
                {
                    a = p1.GetValue(res, null);
                    b = p2.GetValue(res, null);
                }
                else if (f1 != null && f2 != null)
                {
                    a = f1.GetValue(res);
                    b = f2.GetValue(res);
                }
                else
                {
                    return false;
                }
                var en = a as IEnumerable<string>;
                if (en == null) return false;
                names = en.ToList();
                source = b == null ? "" : b.ToString();
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        public void OpenSettings(FamTypeItem it)
        {
            FamParams p;
            if (!Params.TryGetValue(it.Family, out p)) p = new FamParams(new List<string>(), "");
            try
            {
                var dlg = new FamSettingsDialog(O, it, CfgFor(it), p.Names, p.Source, Mode);
                if (dlg.Show())
                {
                    Fams = HfamCore.LoadFamilies();   // the other tab may have saved since
                    Fams[it.Family] = dlg.Result;
                    HfamCore.SaveFamilies(Fams);
                    O.FamilySettingsSaved(this);
                    O.Status("Settings saved for " + it.Family);
                    Refill();
                }
            }
            catch (Exception ex)
            {
                O.Status("Family settings failed: " + ex.Message);
            }
        }

        // ---- the three tools
        /// <summary>
        /// What a job needs from this tab. The floor tab hands its own flr_ settings over as the fam_ keys the jobs
        /// read, no drop rods, and _mode = "floor" so the jobs fit floor supports. The family and the families table
        /// ride on the settings object (FhaJobExtras: _fam, _fams).
        /// </summary>
        public void JobExtra(FhaSettings s)
        {
            if (Floor)
            {
                foreach (string key in s.Keys.ToList())
                {
                    string fk = FhaCore.FloorKey(key);
                    if (fk != key && s.ContainsKey(fk)) s[key] = s[fk];
                }
                foreach (string key in FhaCore.FloorSkip)
                    if (key.Contains("_rod_")) s[key] = "0";
            }
            s["_mode"] = Mode;
            s.Prompts = O.DimUi;   // asks where dimensions go from a 3D view
            FamTypeItem it = Current();
            HfamRevit.HfamChoice choice = null;
            if (it != null)
            {
                FamConfig cfg = CfgFor(it).Clone();
                cfg.Mode = Mode;
                choice = new HfamRevit.HfamChoice { Id = it.Id, Family = it.Family, Cfg = cfg };
            }
            var all = new Dictionary<string, FamConfig>(StringComparer.Ordinal);
            foreach (string f in Fams.Keys)
            {
                FamConfig c = HfamCore.FamConfigFor(Fams, f);
                c.Mode = Mode;
                all[f] = c;
            }
            HfamRevit.SetFamilies(s, choice, all);   // _fam / _fams
        }

        public void ReloadFamilies()
        {
            Fams = HfamCore.LoadFamilies();
            Refill();   // set-up families are shown in bold green
        }

        /// <summary>
        /// Start a tool. A floor support family saved as Circular System Based runs its own job (HcircRevit);
        /// everything else runs the job given.
        /// </summary>
        private void Run(FhaJob job, FhaJob circJob = null)
        {
            FamTypeItem it = Current();
            if (it == null)
            {
                O.Status("Choose a " + Noun + " family and type first");
                return;
            }
            if (!HfamCore.Configured(Fams, it.Family) && !ignored.Contains(it.Family))
            {
                string ans = AskSetup(it);
                if (ans == "setup")
                {
                    SettingsClick(null, null);
                    return;
                }
                if (ans != "ignore") return;
                ignored.Add(it.Family);   // not asked again this session
            }
            FamConfig cfg = CfgFor(it);
            if (Circular(cfg))
            {
                if (!(cfg.Dia.Length > 0 && (cfg.CircHeight.Length > 0 || !Floor)))
                {
                    O.Status("Set the diameter" + (Floor ? " and support height" : "") + " parameter" + (Floor ? "s" : "") +
                             " in Family settings first");
                    return;
                }
                O.StartJob(circJob, JobExtra);
                return;
            }
            else
            {
                if (!(cfg.Left.Length > 0 && cfg.Right.Length > 0))
                {
                    O.Status("Set the two width parameters in Family settings first");
                    return;
                }
                if (Floor && !(cfg.FirstBar.Length > 0 && cfg.Height.Length > 0))
                {
                    O.Status("Set the first bar and support height parameters in Family settings first");
                    return;
                }
            }
            O.StartJob(job, JobExtra);
        }

        /// <summary>A family never set up: "setup" (open Family settings), "ignore" or null.</summary>
        public string AskSetup(FamTypeItem it)
        {
            string style = Floor ? " - Rectangular Floor Based or Circular System Based -" :
                                   " - Rectangular Hanger System or Circular System Based -";
            return new Prompt(O, "Family settings", "Set up the family first",
                "\"" + it.Family + "\" has not been set up yet. Family settings tells the tool which of its parameters set the " +
                "width, height" + (Floor ? " and first bar" : " and drop rod") + " and the rest" + style +
                ". Ignore carries on with the parameters guessed from their names.",
                new[]
                {
                    new PromptButton("ignore", "Ignore and carry on", false),
                    new PromptButton("setup", "Set up the family", true),
                }).Show();
        }

        /// <summary>
        /// The chosen family is saved as Circular System Based (a floor support or, from 1.14.0, a hanger): it runs
        /// the circular jobs (HcircRevit).
        /// </summary>
        public bool Circular(FamConfig cfg)
        {
            if (cfg == null) cfg = new FamConfig();
            FamConfig c = cfg.Clone();
            c.Mode = Mode;
            return HcircCore.IsCirc(c);
        }

        private void PlaceClick(object sender, RoutedEventArgs e)
        {
            Run(HfamRevit.JobPlace, HcircRevit.JobPlace);
        }

        private void RealignClick(object sender, RoutedEventArgs e)
        {
            Run(HfamRevit.JobRealign, HcircRevit.JobRealign);
        }

        private void AutoClick(object sender, RoutedEventArgs e)
        {
            Run(HfamRevit.JobAuto, HcircRevit.JobAuto);
        }

        /// <summary>
        /// Fab Hanger to Family Swap: the same checks as Pick and place (a family and type chosen, set up, widths
        /// or diameter set); the swap job handles rectangular and circular families itself.
        /// </summary>
        private void SwapClick(object sender, RoutedEventArgs e)
        {
            Run(HfamRevit.JobSwap, HfamRevit.JobSwap);
        }

        /// <summary>The "Rod targets..." window (categories the drop rods can run up to besides floors, framing and roofs).</summary>
        private void RodCatsClick(object sender, RoutedEventArgs e)
        {
            RodCatsDialog.Run(O);
        }

        private void RodsClick(object sender, RoutedEventArgs e)
        {
            O.StartJob(HfamRevit.JobRods, JobExtra);
        }

        private void DimsClick(object sender, RoutedEventArgs e)
        {
            if (!ViewOk)
            {
                O.Status("Open a floor plan first");
                return;
            }
            O.StartJob(HcircRevit.JobDims, JobExtra);   // changes nothing for rectangular families
        }
    }
}
