using System.Collections.Generic;

namespace RevoBIM.Tools.BwicPenetration
{
    /// <summary>How a circular run sizes its hole: gap and round-up in mm, and whether insulation counts.</summary>
    public sealed class RoundSpec
    {
        public string Family = "", Through = "", Diameter = "", Type = "";
        public bool Radius;
        public double GapMm = 50.0, RoundMm = 10.0;
        public bool Insulation = true;

        public RoundSpec Copy() { return (RoundSpec)MemberwiseClone(); }
    }

    /// <summary>
    /// The options of one run (the pyRevit tool kept them in a dict): workset, level parameter, comments, pinning, linked services,
    /// and the circular spec. LevelSource is written per placement.
    /// </summary>
    public sealed class BwicOptions
    {
        public string WorksetName = "";
        public string LevelParam = "";
        public string LevelSource = "";
        public bool LogComments, Pin, IncludeLinked, UseWorkset;
        public RoundSpec RoundWall, RoundSpecValue;

        public Dictionary<string, string> ToDebug()
        {
            return new Dictionary<string, string>
            {
                { "workset_name", WorksetName ?? "" }, { "level_param", LevelParam ?? "" }, { "log_comments", LogComments.ToString() },
                { "pin", Pin.ToString() }, { "include_linked", IncludeLinked.ToString() }, { "use_workset", UseWorkset.ToString() },
                { "round_wall", RoundWall == null ? "None" : "gap " + RoundWall.GapMm + " mm, round " + RoundWall.RoundMm + " mm" },
            };
        }
    }
}
