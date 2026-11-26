using System;
using System.IO;
using System.Text;
using Autodesk.Revit.UI;

namespace RevoBIM.Tools.ViewManager
{
    /// <summary>The external event - the only route a modeless window has to the model. Every write goes out through it and nothing ever waits on it.</summary>
    public sealed class VmRunner : IExternalEventHandler
    {
        private readonly ExternalEvent ev;
        public Action<UIApplication> Job;

        public VmRunner()
        {
            ev = ExternalEvent.Create(this);
        }

        public void Raise(Action<UIApplication> job)
        {
            Job = job;
            ev.Raise();
        }

        public void Execute(UIApplication app)
        {
            Action<UIApplication> job = Job;
            Job = null;
            if (job == null) return;
            try
            {
                job(app);
            }
            catch (Exception ex)
            {
                try
                {
                    File.WriteAllText(VmCore.ErrorPath(), "RevoBIM View Manager v" + VmCore.Version + "\n" + VmCore.BuildInfo() + "\n" + ex, new UTF8Encoding(false));
                }
                catch (Exception) { }
            }
        }

        public string GetName() { return "RevoBIM - View Manager"; }
    }
}
