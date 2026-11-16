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
                if (job == null)
                {
                    err = "No job was queued.";
                }
                else
                {
                    if (!quiet) FhaRevit.CurrentLog = log;
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
