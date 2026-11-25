using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Windows.Threading;
using Autodesk.Revit.UI;

namespace RevoBIM.Tools.WorksetManagement
{
    /// <summary>
    /// The ExternalEvent queue. The window is modeless so Revit stays usable, which means nothing in it may touch the
    /// model directly: every read and write is a job handed to Revit through one ExternalEvent and run when Revit is
    /// ready. Never wait for the event from the window that raised it (Revit runs it on the same thread: deadlock):
    /// queue, return, hand the result back on the window's dispatcher. Accepted and Pending both mean Revit will call
    /// us, so the job simply waits its turn; Denied or TimedOut drops this job only. A watchdog frees a window whose
    /// request Revit never picked up. Port of wsm_runner.py.
    /// </summary>
    public class WsmRunner : IExternalEventHandler
    {
        public const double WatchdogSeconds = 30.0;

        private class Job
        {
            public string Label;
            public Func<UIApplication, object> Work;
            public Action<object, Exception> Done;
            public readonly Stopwatch Age = Stopwatch.StartNew();
        }

        private readonly List<Job> _jobs = new List<Job>();
        private ExternalEvent _event;
        private bool _direct, _running;
        private UIApplication _uiapp;
        private Dispatcher _dispatcher;
        public readonly List<string> Log = new List<string>();

        public bool Direct { get { return _direct; } }

        /// <summary>Call from the command, in API context: ExternalEvent.Create must run there.</summary>
        public void Setup(UIApplication uiapp, Dispatcher dispatcher, bool direct = false)
        {
            _uiapp = uiapp; _dispatcher = dispatcher; _direct = direct;
            if (!_direct) _event = ExternalEvent.Create(this);
        }

        public string GetName() { return "RevoBIM - Workset Management"; }

        public bool Busy() { return _jobs.Count > 0 || _running; }

        public bool Queued(string label) { return _jobs.Any(j => j.Label == label); }

        /// <summary>-> (true, "") when the job will run, (false, why) when it will not.</summary>
        public bool Submit(string label, Func<UIApplication, object> work, Action<object, Exception> done, out string why)
        {
            why = "";
            var job = new Job { Label = label, Work = work, Done = done };
            if (_direct) { RunJob(job, _uiapp); return true; }
            _jobs.Add(job);
            string status;
            try { status = _event.Raise().ToString(); } catch (Exception err) { status = "failed: " + err.Message; }
            Log.Add(label + ": Raise -> " + status + " (" + _jobs.Count + " queued)");
            if (status == "Accepted" || status == "Pending") return true;
            _jobs.Remove(job);
            why = "Revit would not take the request (" + status + ") - finish what you are doing in Revit, then try again.";
            return false;
        }

        /// <summary>Labels of jobs dropped because Revit never picked them up.</summary>
        public List<string> Watchdog()
        {
            if (_running || _jobs.Count == 0) return new List<string>();
            double oldest = _jobs.Max(j => j.Age.Elapsed.TotalSeconds);
            if (oldest < WatchdogSeconds) return new List<string>();
            var dropped = _jobs.Select(j => j.Label).ToList();
            _jobs.Clear();
            Log.Add("watchdog dropped: " + string.Join(", ", dropped));
            return dropped;
        }

        /// <summary>Revit calls this when it is ready. Every queued job runs, in order; nothing may escape.</summary>
        public void Execute(UIApplication uiapp)
        {
            _running = true;
            try
            {
                while (_jobs.Count > 0)
                {
                    Job job = _jobs[0];
                    _jobs.RemoveAt(0);
                    RunJob(job, uiapp);
                }
            }
            finally { _running = false; }
        }

        private void RunJob(Job job, UIApplication uiapp)
        {
            object result = null;
            Exception error = null;
            try { result = job.Work(uiapp); }
            catch (Exception err)
            {
                error = err;
                Log.Add(job.Label + " failed:\n" + err);
            }
            HandBack(job, result, error);
        }

        private void HandBack(Job job, object result, Exception error)
        {
            Action callback = () =>
            {
                try { job.Done(result, error); }
                catch (Exception err) { Log.Add(job.Label + " callback failed:\n" + err); }
            };
            if (_dispatcher == null) { callback(); return; }
            try { _dispatcher.BeginInvoke(callback); }
            catch (Exception) { callback(); }
        }
    }
}
