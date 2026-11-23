using System;
using System.Windows.Threading;
using Autodesk.Revit.UI;
using RevoBIM.Tools.HangerAutomation;

namespace RevoBIM.UI.HangerAutomation
{
    /// <summary>
    /// Runs one queued job inside Revit's API context, then hands the result back to the window on its
    /// dispatcher. DialogBoxShowing is hooked once and switched with a flag (unhooking a bound method is
    /// unreliable). Port of fha_window.FhaHandler.
    /// </summary>
    public sealed class FhaHandler : IExternalEventHandler
    {
        public FhaJob Job;
        public FhaWindow Owner;
        public FhaSettings Settings = new FhaSettings();
        public FhaDebugLog Log;
        public bool Started;
        public bool Suppress;
        public bool Hooked;
        public bool Quiet;

        public string GetName()
        {
            return "Hanger Automation";
        }

        private void OnDialog(object sender, Autodesk.Revit.UI.Events.DialogBoxShowingEventArgs args)
        {
            if (!Suppress) return;
            try
            {
                if (Log != null) Log.Add("dialog suppressed: " + args.DialogId);
                args.OverrideResult(1);
            }
            catch (Exception)
            {
            }
        }

        public void Execute(UIApplication uiapp)
        {
            Started = true;
            FhaJob job = Job;
            FhaWindow owner = Owner;
            bool quiet = Quiet;
            Job = null;
            object res = null;
            string err = null;
            var log = new FhaDebugLog(FhaCore.AsBool(Settings, "debug"));
            if (!quiet) Log = log;
            try
            {
                if (!Hooked)
                {
                    try
                    {
                        uiapp.DialogBoxShowing += OnDialog;
                        Hooked = true;
                    }
                    catch (Exception)
                    {
                    }
                }
                Suppress = true;
                string revit = "?";
                try
                {
                    revit = uiapp.Application.VersionNumber;
                }
                catch (Exception)
                {
                }
                log.Add("Hanger Automation " + FhaCore.Version + ", Revit " + revit + ", egg: " +
                        (owner != null ? owner.EggRoute : "?"));
                log.Add("build: " + FhaCore.BuildInfo());
                if (!string.IsNullOrEmpty(FhaWindow.OpenTiming)) log.Add("window open: " + FhaWindow.OpenTiming);
                if (job == null)
                {
                    err = "No job was queued.";
                }
                else
                {
                    if (!quiet) FhaRevit.CurrentLog = log;
                    string sp;
                    Settings.TryGetValue("svc_param", out sp);
                    FhaRevit.ServiceParamName = sp ?? "";   // where the service type text goes (Service Type Assigner)
                    if (!string.IsNullOrEmpty(sp) && sp != "Comments") log.Add("service type parameter: " + sp);
                    HaCache.Reset();            // per-job caches (levels, sections): never carried over from an earlier job, whichever job this is
                    HaTiming.BeginJob(null);    // timing off and cleared; the jobs that time themselves switch it on
                    res = job(uiapp.ActiveUIDocument, Settings, log);
                }
            }
            catch (Exception ex)
            {
                err = ex.ToString();
                log.Add(err);
            }
            finally
            {
                Suppress = false;
                if (!quiet) FhaRevit.CurrentLog = null;
            }
            if (!quiet) log.Write();
            if (owner != null)
            {
                try
                {
                    object r = res;
                    string e = err;
                    owner.Win.Dispatcher.BeginInvoke(new Action(() => owner.Finished(r, e)));
                }
                catch (Exception)
                {
                    owner.Finished(res, err);
                }
            }
        }
    }
}
