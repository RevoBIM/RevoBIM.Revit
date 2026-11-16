using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.UI;
using static RevoBIM.Tools.ModelCleanup.McuCore;

namespace RevoBIM.Tools.ModelCleanup
{
    /// <summary>
    /// Revit work from a modeless window, through one ExternalEvent. A modeless window lives on Revit's
    /// thread but outside Revit's API context, so nothing it does can touch the model directly. Every job
    /// goes into a queue here; Revit calls Execute when it is free, in API context, and the queue is drained
    /// there. The ExternalEvent has to be created while a command is running. Port of mcu_events.py.
    /// </summary>
    public sealed class McuApiRunner : IExternalEventHandler
    {
        private readonly List<(string Label, Action<UIApplication> Job)> queue = new List<(string, Action<UIApplication>)>();
        private readonly ExternalEvent externalEvent;
        public string Running;
        public Action<string, string> OnError;

        public McuApiRunner(Action<string, string> onError = null)
        {
            OnError = onError;
            externalEvent = ExternalEvent.Create(this);
        }

        public string GetName() { return "Model Cleanup"; }

        /// <summary>Kept is false only when Revit refused - then this job, and only this one, is taken back off the queue.</summary>
        public (bool Kept, string Status) Request(string label, Action<UIApplication> job)
        {
            var entry = (label, job);
            queue.Add(entry);
            string status;
            try { status = externalEvent.Raise().ToString(); }
            catch (Exception error) { status = "Raise failed: " + error.Message; }
            if (RaiseKept(status))
            {
                Log("queued " + label + " (" + status + ")");
                return (true, status);
            }
            for (int index = queue.Count - 1; index >= 0; index--)
            {
                if (ReferenceEquals(queue[index].Job, job)) { queue.RemoveAt(index); break; }
            }
            Log("Revit refused " + label + " (" + status + ")");
            return (false, status);
        }

        /// <summary>Take waiting jobs back off the queue (those with this label). A job already running cannot be cancelled.</summary>
        public int Cancel(string label)
        {
            int before = queue.Count;
            queue.RemoveAll(e => label == null || e.Label == label);
            return before - queue.Count;
        }

        public void Execute(UIApplication uiapp)
        {
            // A job may queue another (closing the window queues the clean-up of the background copy);
            // it runs in this same pass.
            while (queue.Count > 0)
            {
                var (label, job) = queue[0];
                queue.RemoveAt(0);
                Running = label;
                try
                {
                    job(uiapp);
                }
                catch (Exception error)
                {
                    string text = FormatException(error);
                    WriteError(label, text);
                    try { OnError?.Invoke(label, text); }
                    catch (Exception) { Log("error handler failed for " + label); }
                }
                finally
                {
                    Running = null;
                }
            }
        }
    }
}
