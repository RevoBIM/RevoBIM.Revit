using System;
using System.Collections.Generic;
using System.Windows;
using System.Windows.Interop;
using Autodesk.Revit.UI;

namespace RevoBIM.Tools.FilterManager
{
    /// <summary>Runs whatever the window queued, on Revit's own thread.</summary>
    public class FmActionHandler : IExternalEventHandler
    {
        private readonly Queue<Action<UIApplication>> _queue = new Queue<Action<UIApplication>>();
        public Action<string> OnError;

        public void Enqueue(Action<UIApplication> fn) { _queue.Enqueue(fn); }

        public void Execute(UIApplication app)
        {
            while (_queue.Count > 0)
            {
                Action<UIApplication> fn = _queue.Dequeue();
                try { fn(app); }
                catch (Exception ex)
                {
                    if (OnError != null)
                    {
                        try { OnError(ex.ToString()); }
                        catch (Exception) { }
                    }
                }
            }
        }

        public string GetName() { return "RevoBIM Filter Manager"; }
    }

    /// <summary>
    /// A modeless window cannot start a transaction directly - every write goes out through an ExternalEvent.
    /// Hands a callable to Revit and asks for it to be run. Port of fm_events.Runner.
    /// </summary>
    public class FmRunner
    {
        public readonly FmActionHandler Handler = new FmActionHandler();
        private readonly bool _direct;
        private bool _directNow;
        private readonly ExternalEvent _event;
        public string CreateError;
        public Action<string> OnRefused;

        /// <summary>
        /// Created while the command is still running and Revit is in a valid API context. Creating it later
        /// from a button click is not reliable.
        /// </summary>
        public FmRunner(bool direct = false)
        {
            _direct = direct;
            _directNow = direct;
            if (!direct)
            {
                try { _event = ExternalEvent.Create(Handler); }
                catch (Exception ex)
                {
                    CreateError = ex.ToString();
                    _directNow = true;
                }
            }
        }

        public void SetErrorReporter(Action<string> fn) { Handler.OnError = fn; }

        /// <summary>Hand the work to Revit, and check that Revit took it. A refused request queues nothing and raises nothing.</summary>
        public string Run(Action<UIApplication> fn)
        {
            Handler.Enqueue(fn);
            if (_directNow || _event == null)
            {
                Handler.Execute(null);
                return "Direct";
            }

            ExternalEventRequest request = ExternalEventRequest.Denied;
            bool known = false;
            try { request = _event.Raise(); known = true; }
            catch (Exception) { }

            bool accepted = !known || request == ExternalEventRequest.Accepted || request == ExternalEventRequest.Pending;
            if (accepted) return known ? request.ToString() : "None";

            // Revit would not take it. Rather than lose the work quietly, run it here.
            try { Handler.Execute(null); }
            catch (Exception) { }
            if (OnRefused != null)
            {
                try { OnRefused(request.ToString()); }
                catch (Exception) { }
            }
            return request.ToString();
        }
    }

    /// <summary>Keeps the one open window, and owns it to Revit.</summary>
    public static class FmWindowKeeper
    {
        private static Window _window;

        public static void Park(Window window) { _window = window; }
        public static Window Parked() { return _window; }
        public static void Unpark() { _window = null; }

        /// <summary>An unowned modeless window slips behind Revit and reads as a crash.</summary>
        public static bool OwnToRevit(Window window, UIApplication uiapp)
        {
            try
            {
                new WindowInteropHelper(window).Owner = uiapp.MainWindowHandle;
                return true;
            }
            catch (Exception) { return false; }
        }
    }
}
