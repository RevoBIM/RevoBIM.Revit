using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Threading;
using RevoBIM.Tools.HangerAutomation;
using ExternalEvent = Autodesk.Revit.UI.ExternalEvent;
using UIApplication = Autodesk.Revit.UI.UIApplication;

namespace RevoBIM.UI.HangerAutomation
{
    public sealed partial class FhaWindow
    {
        // ---- running a job
        private void SetBusy(bool busy, string status)
        {
            Busy = busy;
            foreach (string n in JobButtons) ((UIElement)C(n)).IsEnabled = !busy;
            foreach (FamTab t in FamTabs()) t.SetBusy(busy);
            if (Svc != null) Svc.SetBusy(busy);
            C<TextBlock>("StatusTxt").Text = status;
        }

        private void Start(string kind)
        {
            FhaJob job;
            if (kind == "rehost") job = (u, s, l) => FhaRevit.JobRehost(u, s, l);
            else if (kind == "extend") job = (u, s, l) => FhaRevit.JobExtend(u, s, l);
            else job = (u, s, l) => FhaRevit.JobPlace(u, s, l);
            StartJob(job, JobExtra);
        }

        public void JobExtra(FhaSettings s)
        {
            s.Prompts = DimUi;
        }

        private bool Queue(FhaJob job, FhaSettings settings, bool quiet, string status)
        {
            FhaHandler h = handler;
            h.Owner = this;
            h.Settings = settings;
            h.Job = job;
            h.Quiet = quiet;
            h.Started = false;
            SetBusy(true, status);
            string answer = evt.Raise().ToString();
            if (answer == "Accepted" || answer == "Pending")
            {
                StartTimer();
                return true;
            }
            h.Job = null;
            quietCb = null;
            SetBusy(false, "Revit refused the request (" + answer + ") - try again");
            return false;
        }

        /// <summary>A tool: picks, writes, results box, debug file.</summary>
        public bool StartJob(FhaJob job, Action<FhaSettings> extra = null)
        {
            try
            {
                if (Busy)
                {
                    if (quietCb != null)
                    {
                        pending = new Pending { Job = job, Extra = extra };   // a quick read is in flight: run straight after it
                        Status("Starting as soon as Revit has finished reading...");
                        return true;
                    }
                    Status("Still working on the last request...");
                    return false;
                }
                Save();
                var settings = new FhaSettings(Settings);
                if (extra != null) extra(settings);
                quietCb = null;
                return Queue(job, settings, false, "Working... pick in the model if asked (Esc cancels the pick)");
            }
            catch (Exception ex)
            {
                SetBusy(false, "Could not start - see Copy debug");
                LastDebug = ex.ToString();
                return false;
            }
        }

        /// <summary>A read: the answer goes to callback(result, error). False if busy.</summary>
        public bool StartQuiet(FhaJob job, Action<object, string> callback, string status = "Reading...")
        {
            try
            {
                if (Busy) return false;
                quietCb = callback;
                return Queue(job, new FhaSettings(Settings), true, status);
            }
            catch (Exception)
            {
                quietCb = null;
                SetBusy(false, "Ready");
                return false;
            }
        }

        private void StartTimer()
        {
            StopTimer();
            try
            {
                timer = new DispatcherTimer();
                timer.Interval = TimeSpan.FromSeconds(WatchdogSeconds);
                timer.Tick += Watchdog;
                timer.Start();
            }
            catch (Exception)
            {
                timer = null;
            }
        }

        private void StopTimer()
        {
            try
            {
                if (timer != null) timer.Stop();
            }
            catch (Exception)
            {
            }
            timer = null;
        }

        /// <summary>Frees the window if Revit never started the job (it was busy).</summary>
        private void Watchdog(object sender, EventArgs e)
        {
            StopTimer();
            FhaHandler h = handler;
            if (Busy && h != null && !h.Started)
            {
                h.Job = null;
                quietCb = null;
                pending = null;
                SetBusy(false, "Revit was busy and did not run it - click again");
            }
        }

        /// <summary>The handler's answer, on the window's dispatcher.</summary>
        public void Finished(object res, string err)
        {
            StopTimer();
            if (FhaFinish.Armed) FhaFinish.Disarm("job ended");   // belt and braces: the card never outlives its job
            if (quietCb != null)
            {
                Action<object, string> cb = quietCb;
                quietCb = null;
                SetBusy(false, "Ready");
                try
                {
                    cb(res, err);
                }
                catch (Exception ex)
                {
                    LastDebug = ex.ToString();
                }
                if (pending != null && !Busy)
                {
                    Pending p = pending;
                    pending = null;
                    StartJob(p.Job, p.Extra);
                }
                foreach (FamTab t in FamTabs())   // a tab whose preview read could not start gets its turn now
                {
                    if (!Busy) t.RetryPreview();
                }
                if (!Busy) Svc.RetryScan();
                return;
            }
            FhaHandler h = handler;
            if (h != null && h.Log != null) LastDebug = h.Log.Text();
            var lines = new List<string>();
            string status;
            JobResult jr = res as JobResult;
            if (!string.IsNullOrEmpty(err))
            {
                lines.Add("Something went wrong - press Copy debug and send it over.");
                lines.Add(err);
                status = "Failed - see the results box";
            }
            else if (jr != null)
            {
                lines.Add(jr.Title + ": " + jr.Done + " done, " + jr.Skipped + " skipped, " + jr.Failed + " failed");
                lines.AddRange(jr.Lines);
                status = jr.Title + ": " + jr.Done + " done";
            }
            else
            {
                status = "Ready";
            }
            try
            {
                C<TextBox>("LogBox").Text = string.Join("\n", lines);
                SetBusy(false, status);
                Win.Activate();
            }
            catch (Exception)
            {
            }
            try
            {
                Svc.AfterJob();   // the service type tab reads again after it wrote Comments
            }
            catch (Exception)
            {
            }
        }
    }
}
