// Port of ps_version.py (Pro Sheets Exporter).
namespace RevoBIM.Tools.ProSheets
{
    /// <summary>
    /// The one place the version number lives.
    /// Every window reads it from here and shows it in the top right corner. Bumping
    /// this string is the only edit a release needs; nothing hardcodes it in XAML.
    /// </summary>
    public static partial class PsVersion
    {
        // Python: __version__
        public const string Version = "1.56.1";

        public const string ToolName = "Pro Sheets Exporter";
        public const string ToolKey = "pro_sheets_exporter";
    }
}
