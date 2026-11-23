using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;

namespace RevoBIM.Tools.HangerAutomation
{
    /// <summary>
    /// The per-family settings (the Python dict of FAM_DEFAULTS keys; every value is the text the file holds).
    /// Mode is the one extra key the UI adds with dict(cfg, mode=...): "hang" or "floor", null when absent.
    /// </summary>
    public class FamConfig
    {
        public string Left = "";             // instance length stretching one way from centre
        public string Right = "";            // instance length stretching the other way
        public string Rod = HfamCore.RodDefault;   // drop rod length
        public string Axis = "X";            // the family's width runs along its X (left/right) or Y
        public string Clearance = "0";       // mm added to each half width
        public string Soffit = "level";      // level = base of the level above; structure = ray to structure
        public string Swap = "0";            // 1 = the first width parameter is the family's positive side
        // floor supports (Family Floor Support tab)
        public string FirstBar = HfamCore.FirstBarDefault;           // level -> top of the bottom bar (the service invert)
        public string Height = HfamCore.SupportHeightDefault;        // bottom bar top -> top bar underside (the service depth)
        public string HeightClear = "0";     // mm added to the support height above the service
        // floor support style: rect = Rectangular Floor Based (frame round the service),
        // circ = Circular System Based (a ring round a pipe / round duct on a post)
        public string Style = "rect";
        public string Dia = HfamCore.DiameterDefault;                // circ: ring diameter, set to the service's (insulated) diameter
        public string CircHeight = HfamCore.SupportHeightDefault;    // circ: base -> service centre (the ring centre)
        public string CircAxis = "X";        // circ: the service runs along the family's X or Y

        /// <summary>The extra "mode" key some callers add (dict(cfg, mode=...)); null = not set.</summary>
        public string Mode;

        public FamConfig() { }

        public FamConfig Clone() { return (FamConfig)MemberwiseClone(); }

        /// <summary>The value for a file key (left, right, rod, axis, clearance, soffit, swap, first_bar, height,
        /// height_clear, style, dia, circ_height, circ_axis) or "mode"; null for any other key.</summary>
        public string this[string key]
        {
            get
            {
                switch (key)
                {
                    case "left": return Left;
                    case "right": return Right;
                    case "rod": return Rod;
                    case "axis": return Axis;
                    case "clearance": return Clearance;
                    case "soffit": return Soffit;
                    case "swap": return Swap;
                    case "first_bar": return FirstBar;
                    case "height": return Height;
                    case "height_clear": return HeightClear;
                    case "style": return Style;
                    case "dia": return Dia;
                    case "circ_height": return CircHeight;
                    case "circ_axis": return CircAxis;
                    case "mode": return Mode;
                }
                return null;
            }
            set
            {
                switch (key)
                {
                    case "left": Left = value; break;
                    case "right": Right = value; break;
                    case "rod": Rod = value; break;
                    case "axis": Axis = value; break;
                    case "clearance": Clearance = value; break;
                    case "soffit": Soffit = value; break;
                    case "swap": Swap = value; break;
                    case "first_bar": FirstBar = value; break;
                    case "height": Height = value; break;
                    case "height_clear": HeightClear = value; break;
                    case "style": Style = value; break;
                    case "dia": Dia = value; break;
                    case "circ_height": CircHeight = value; break;
                    case "circ_axis": CircAxis = value; break;
                    case "mode": Mode = value; break;
                }
            }
        }

        /// <summary>cfg.get(key, dflt).</summary>
        public string Get(string key, string dflt)
        {
            string v = this[key];
            return v ?? dflt;
        }
    }

    /// <summary>One type in the family list (the dicts list_family_types builds and filter_types reads).</summary>
    public class FamTypeItem
    {
        public string Key;        // item_key(family, type)
        public string Family;
        public string Type;
        public string Cat;        // BuiltInCategory name, e.g. OST_GenericModel
        public string CatLabel;
        public Autodesk.Revit.DB.ElementId Id;
    }

    /// <summary>
    /// A service's (or unit's) section as the hanger fitting code sees it (the Python dict: a, b, width, depth, round,
    /// ins, ins_used, bare_width, bare_depth, keys, ext_neg, ext_pos, across, span_height, unit, run_from, length, bottom,
    /// plus set_left / set_right / set_dia / set_height the placing code writes into it).
    /// Nullable members are the keys that may be absent in the dict.
    /// </summary>
    public class Section
    {
        public V3 A, B;
        public double Width, Depth;
        public bool Round;
        public double Ins;
        public bool InsUsed;
        public double? BareWidth, BareDepth;
        public List<long> Keys;
        public double? ExtNeg, ExtPos;
        public V3? Across;
        public double? SpanHeight;
        public bool Unit;
        public string RunFrom;
        public double? Length;
        public double? Bottom;
        public double? SetLeft, SetRight, SetDia, SetHeight;

        /// <summary>dict(sec): a shallow copy (the Keys list is shared, as in Python).</summary>
        public Section Clone() { return (Section)MemberwiseClone(); }
    }

    /// <summary>One service in a grouped hanger (bundle members: key, a, b, width, depth).</summary>
    public class BundleMember
    {
        public long Key;
        public V3 A, B;
        public double Width, Depth;
        public BundleMember() { }
        public BundleMember(long key, V3 a, V3 b, double width, double depth) { Key = key; A = a; B = b; Width = width; Depth = depth; }
    }

    /// <summary>The Hanger rules: (z_tol_ft, gap_tol_ft, angle_deg, centre).</summary>
    public class GroupRules
    {
        public double ZTolFt, GapTolFt, AngleDeg;
        public string Centre = "mean";
        public GroupRules() { }
        public GroupRules(double zTolFt, double gapTolFt, double angleDeg, string centre) { ZTolFt = zTolFt; GapTolFt = gapTolFt; AngleDeg = angleDeg; Centre = centre; }
        /// <summary>(BUNDLE_Z_MM / MM, BUNDLE_GAP_MM / MM, BUNDLE_ANGLE_DEG, 'mean') - what bundle_for uses when no rules are given.</summary>
        public static GroupRules Default()
        {
            return new GroupRules(HfamCore.BundleZMm / FhaCore.MM, HfamCore.BundleGapMm / FhaCore.MM, HfamCore.BundleAngleDeg, "mean");
        }
    }

    /// <summary>The result of HfamCore.Bundle: one hanger round several services.</summary>
    public class HangerBundle
    {
        public List<long> Keys = new List<long>();
        public double Width, ExtNeg, ExtPos;
        public V3 Across;
        public double Bottom, Top;
        public List<string> Notes = new List<string>();
        public V3 Point, A, B;
    }

    /// <summary>A straight to pick_segment: (key, a, b).</summary>
    public class KeySeg
    {
        public long Key;
        public V3 A, B;
        public KeySeg() { }
        public KeySeg(long key, V3 a, V3 b) { Key = key; A = a; B = b; }
    }

    /// <summary>A hanger for group_runs: (key, point, along) - along is the run direction at the hanger.</summary>
    public class RunHanger
    {
        public long Key;
        public V3 P, Along;
        public RunHanger() { }
        public RunHanger(long key, V3 p, V3 along) { Key = key; P = p; Along = along; }
    }

    /// <summary>One straight line of hangers: its direction and the hanger keys sorted along it.</summary>
    public class RunGroup
    {
        public V3 Dir;
        public List<long> Keys = new List<long>();
    }

    /// <summary>A connector of an in-line unit: origin and basisZ.</summary>
    public class InlineConn
    {
        public V3 Origin, Basis;
        public InlineConn() { }
        public InlineConn(V3 origin, V3 basis) { Origin = origin; Basis = basis; }
    }
}
