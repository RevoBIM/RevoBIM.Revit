using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;

namespace RevoBIM.Tools.HangerAutomation
{
    /// <summary>A 3D point or vector (the Python tuples of three floats).</summary>
    public struct V3
    {
        public double X, Y, Z;
        public V3(double x, double y, double z) { X = x; Y = y; Z = z; }
        public override string ToString() { return "(" + X.ToString("R", CultureInfo.InvariantCulture) + ", " + Y.ToString("R", CultureInfo.InvariantCulture) + ", " + Z.ToString("R", CultureInfo.InvariantCulture) + ")"; }
    }

    /// <summary>One connector of a part in the run graph. To / ToConn are null when nothing is joined; Role is "main" / "branch" on a tee.</summary>
    public class ConnRec
    {
        public long? To;
        public int? ToConn;
        public string Role;
    }

    /// <summary>A part in the run graph (fha_core "parts" values). Kind: straight / inline / bend / tee / tap / other / accessory.</summary>
    public class PartRec
    {
        public string Kind = "other";
        public double Len;
        public bool Horizontal = true;
        public List<ConnRec> Conns = new List<ConnRec>();
    }

    public class ChainItem
    {
        public long Id;
        public string Kind;
        public double Len;
        public int Entry, Exit;
    }

    /// <summary>What finishes one end of a span: bend / accessory / vertical / tee_main / tee_branch / tap / open / other / loop.</summary>
    public class SpanEnd
    {
        public string Type;
        public long? Id;
    }

    public class Span
    {
        public List<ChainItem> Chain = new List<ChainItem>();
        public SpanEnd StartEnd, EndEnd;
    }

    /// <summary>A candidate host straight for nearest_host: connector 0 / connector 1 origins.</summary>
    public class HostSeg
    {
        public long Id;
        public V3 A, B;
        public bool Horizontal = true;
        public object Tag;   // the caller's own record
    }

    public class NearestHostResult
    {
        public HostSeg Host;
        public double Dist, D, T;
    }

    public class Located
    {
        public long Id;
        public int Entry;
        public double Dist, Station;
    }

    /// <summary>One straight's piece of a span: s0 = station of its start, A / B its end points.</summary>
    public class SpanSeg
    {
        public double S0;
        public V3 A, B;
        public long Id;
    }

    /// <summary>A hanger button condition for pick_condition.</summary>
    public class Condition
    {
        public int Index;
        public double Lower, Upper;
        public bool Unrestricted;
        public Condition() { }
        public Condition(int index, double lower, double upper, bool unrestricted) { Index = index; Lower = lower; Upper = upper; Unrestricted = unrestricted; }
    }

    /// <summary>The numbers plan_stations needs, all mm (plan_config).</summary>
    public class PlanConfig
    {
        public double Spacing = 2000, StartOff = 300, EndOff = 300, TakeoffMax = 600, TakeoffClear = 400, MinGap = 500, Edge = 100;
    }

    /// <summary>A hanger's identity for signature_score (all fields may be null).</summary>
    public class HangerSignature
    {
        public string Name, Product, Alias, ItemId, Code;
    }

    /// <summary>A plan / section view a run can be dimensioned in (dim_view_rows).</summary>
    public class ViewRow
    {
        public long Key;
        public Autodesk.Revit.DB.ElementId Id;
        public string Name;
        public string Type;      // ViewType name: FloorPlan, CeilingPlan, EngineeringPlan, AreaPlan, Section, Elevation, Detail ...
        public int Scale;
    }

    /// <summary>A sheet carrying such views (dim_sheet_rows). Views = the view keys.</summary>
    public class SheetRow
    {
        public long Key;
        public Autodesk.Revit.DB.ElementId Id;
        public string Number, Name;
        public List<long> Views = new List<long>();
    }

    /// <summary>The Dimension views picker's answer (null = skip).</summary>
    public class DimChoice
    {
        public List<long> Views = new List<long>();
        public List<long> Sheets = new List<long>();
    }

    /// <summary>
    /// The questions a job asks mid-run; the window hands its implementation to the jobs (the Python
    /// settings["_ui"]). Implemented by UI\HangerAutomation\HviewUi.cs.
    /// </summary>
    public interface IFhaPrompts
    {
        /// <summary>null to skip, else the ticked views and sheets.</summary>
        DimChoice ChooseDimViews(string viewName, List<ViewRow> rows, List<SheetRow> sheets);
        /// <summary>"pick" or "level" (null if closed).</summary>
        string AskBasePick(bool linked);
        /// <summary>"sheets", "views" or null.</summary>
        string AskOpen(int nRuns, List<string> views, List<string> sheets);
    }

    /// <summary>The settings dictionary jobs receive. Python put the prompts object in the dict as "_ui"; here it is Prompts.</summary>
    public class FhaSettings : Dictionary<string, string>
    {
        public IFhaPrompts Prompts;
        public FhaSettings() : base(StringComparer.Ordinal) { }
        public FhaSettings(IDictionary<string, string> from) : base(from, StringComparer.Ordinal)
        {
            FhaSettings f = from as FhaSettings;
            if (f != null) Prompts = f.Prompts;
        }
    }

    /// <summary>What a tool reports (fha_revit.new_result): "Title: done, skipped, failed" and the lines under it.</summary>
    public class JobResult
    {
        public string Title;
        public int Done, Skipped, Failed;
        public List<string> Lines = new List<string>();
        public Dictionary<string, object> Extra = new Dictionary<string, object>();
        public JobResult() { }
        public JobResult(string title) { Title = title; }
    }

    /// <summary>A queued job: runs inside Revit's API context. Returns a JobResult (tools) or any object (quiet reads).</summary>
    public delegate object FhaJob(Autodesk.Revit.UI.UIDocument uidoc, FhaSettings settings, FhaDebugLog log);

    /// <summary>The debug file's lines (core.DebugLog).</summary>
    public sealed class FhaDebugLog
    {
        public bool Enabled;
        public List<string> Lines = new List<string>();
        public FhaDebugLog(bool enabled = true) { Enabled = enabled; }

        public void Add(string msg)
        {
            if (!Enabled) return;
            try { Lines.Add(msg ?? ""); } catch (Exception) { Lines.Add("?"); }
        }

        public string Text() { return string.Join("\n", Lines); }

        public void Write(string path = null)
        {
            if (!Enabled) return;
            try
            {
                string p = path ?? FhaCore.DebugPath();
                string folder = Path.GetDirectoryName(p);
                if (!string.IsNullOrEmpty(folder) && !Directory.Exists(folder)) Directory.CreateDirectory(folder);
                File.WriteAllText(p, Text() + "\n", new UTF8Encoding(false));
            }
            catch (Exception) { }
        }
    }

    /// <summary>The workset combo: labels, selected index and the value behind each label.</summary>
    public class WorksetItems
    {
        public List<string> Labels = new List<string>();
        public List<string> Values = new List<string>();
        public int Index;
    }
}
