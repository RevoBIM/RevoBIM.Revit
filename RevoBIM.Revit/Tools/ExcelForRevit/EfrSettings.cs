// Port of efr_core.py's settings store (SETTINGS_DIR / SETTINGS_PATH / load_settings / save_settings).
//
// The settings stay a JSON object, in the same place as the pyRevit version keeps them
// (%APPDATA%\RevoBIM PY\excel_for_revit_settings.json), so both versions share them.
// Values are bool / long / double / string / null, plus nested Dictionary<string, object>
// and List<object> if a file ever holds them. Nothing here is ever allowed to interrupt
// the tool: a missing or damaged file reads as empty, a failed write is swallowed.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;

namespace RevoBIM.Tools.ExcelForRevit
{
    public static partial class Efr
    {
        public static readonly string SETTINGS_DIR = Path.Combine(
            Environment.GetEnvironmentVariable("APPDATA")
                ?? Path.GetDirectoryName(typeof(Efr).Assembly.Location) ?? "",
            "RevoBIM PY");

        public static readonly string SETTINGS_PATH = Path.Combine(SETTINGS_DIR, "excel_for_revit_settings.json");

        private static readonly object SettingsLock = new object();

        /// <summary>The settings file as a dictionary. Empty when it is missing or damaged. Never throws.</summary>
        public static Dictionary<string, object> LoadSettings()
        {
            try
            {
                lock (SettingsLock)
                {
                    if (File.Exists(SETTINGS_PATH))
                    {
                        string text = File.ReadAllText(SETTINGS_PATH, Encoding.UTF8);
                        if (text.Trim().Length == 0)
                            return new Dictionary<string, object>(StringComparer.Ordinal);
                        var parsed = new EfrSettingsJson(text).ParseDocument() as Dictionary<string, object>;
                        if (parsed != null)
                            return parsed;
                    }
                }
            }
            catch (Exception)
            {
            }
            return new Dictionary<string, object>(StringComparer.Ordinal);
        }

        /// <summary>Merge and write. Never allowed to interrupt the tool.</summary>
        public static void SaveSettings(IDictionary<string, object> values)
        {
            try
            {
                lock (SettingsLock)
                {
                    if (!Directory.Exists(SETTINGS_DIR))
                        Directory.CreateDirectory(SETTINGS_DIR);
                    var current = LoadSettings();
                    if (values != null)
                    {
                        foreach (var item in values)
                            current[item.Key] = item.Value;
                    }
                    File.WriteAllText(SETTINGS_PATH, EfrSettingsJson.Dump(current), new UTF8Encoding(false));
                }
            }
            catch (Exception)
            {
            }
        }

        /// <summary>Convenience for the common one-key save_settings({key: value}).</summary>
        public static void SaveSetting(string key, object value)
        {
            SaveSettings(new Dictionary<string, object> { { key, value } });
        }

        // ---- typed getters (Python: settings.get(key, default) wrapped in bool() / to_text() / int()) ----

        /// <summary>Python bool(settings.get(key, default)): truthiness of whatever is stored.</summary>
        public static bool GetBool(IDictionary<string, object> settings, string key, bool @default = false)
        {
            object value;
            if (settings == null || !settings.TryGetValue(key, out value))
                return @default;
            return SettingTruthy(value);
        }

        /// <summary>Python to_text(settings.get(key, default)): None reads as "".</summary>
        public static string GetString(IDictionary<string, object> settings, string key, string @default = "")
        {
            object value;
            if (settings == null || !settings.TryGetValue(key, out value))
                return @default;
            return SettingText(value);
        }

        /// <summary>The stored number, or the default when it is missing or not a number.</summary>
        public static int GetInt(IDictionary<string, object> settings, string key, int @default = 0)
        {
            object value;
            if (settings == null || !settings.TryGetValue(key, out value) || value == null)
                return @default;
            try
            {
                if (value is bool)
                    return (bool)value ? 1 : 0;
                if (value is long)
                    return checked((int)(long)value);
                if (value is double)
                    return checked((int)Math.Truncate((double)value));
                if (value is int)
                    return (int)value;
                double parsed;
                if (double.TryParse(Convert.ToString(value, CultureInfo.InvariantCulture),
                                    NumberStyles.Float, CultureInfo.InvariantCulture, out parsed))
                    return checked((int)Math.Truncate(parsed));
            }
            catch (Exception)
            {
            }
            return @default;
        }

        private static bool SettingTruthy(object value)
        {
            if (value == null) return false;
            if (value is bool) return (bool)value;
            if (value is string) return ((string)value).Length > 0;
            if (value is long) return (long)value != 0;
            if (value is int) return (int)value != 0;
            if (value is double) return (double)value != 0.0;
            var collection = value as ICollection;
            if (collection != null) return collection.Count > 0;
            return true;
        }

        private static string SettingText(object value)
        {
            if (value == null) return "";
            if (value is string) return (string)value;
            if (value is bool) return (bool)value ? "True" : "False";
            if (value is double) return ((double)value).ToString("R", CultureInfo.InvariantCulture);
            return Convert.ToString(value, CultureInfo.InvariantCulture);
        }
    }

    /// <summary>A small JSON reader and writer, enough for the settings file (no System.Web / Newtonsoft).</summary>
    internal sealed class EfrSettingsJson
    {
        private readonly string _s;
        private int _i;

        public EfrSettingsJson(string text)
        {
            _s = text ?? "";
        }

        // ---------------------------------------------------------------- reading

        public object ParseDocument()
        {
            _i = 0;
            if (_s.Length > 0 && _s[0] == '﻿')
                _i = 1;
            object value = ParseValue();
            SkipSpace();
            if (_i != _s.Length)
                throw new FormatException("trailing data");
            return value;
        }

        private void SkipSpace()
        {
            while (_i < _s.Length && (_s[_i] == ' ' || _s[_i] == '\t' || _s[_i] == '\r' || _s[_i] == '\n'))
                _i++;
        }

        private object ParseValue()
        {
            SkipSpace();
            if (_i >= _s.Length)
                throw new FormatException("unexpected end");
            char c = _s[_i];
            if (c == '{') return ParseObject();
            if (c == '[') return ParseArray();
            if (c == '"') return ParseString();
            if (Literal("true")) return true;
            if (Literal("false")) return false;
            if (Literal("null")) return null;
            if (Literal("NaN")) return double.NaN;
            if (Literal("Infinity")) return double.PositiveInfinity;
            if (Literal("-Infinity")) return double.NegativeInfinity;
            return ParseNumber();
        }

        private bool Literal(string word)
        {
            if (string.CompareOrdinal(_s, _i, word, 0, word.Length) != 0)
                return false;
            _i += word.Length;
            return true;
        }

        private Dictionary<string, object> ParseObject()
        {
            var result = new Dictionary<string, object>(StringComparer.Ordinal);
            _i++; // {
            SkipSpace();
            if (_i < _s.Length && _s[_i] == '}')
            {
                _i++;
                return result;
            }
            while (true)
            {
                SkipSpace();
                if (_i >= _s.Length || _s[_i] != '"')
                    throw new FormatException("key expected");
                string key = ParseString();
                SkipSpace();
                if (_i >= _s.Length || _s[_i] != ':')
                    throw new FormatException("colon expected");
                _i++;
                result[key] = ParseValue();
                SkipSpace();
                if (_i >= _s.Length)
                    throw new FormatException("unexpected end");
                if (_s[_i] == ',')
                {
                    _i++;
                    continue;
                }
                if (_s[_i] == '}')
                {
                    _i++;
                    return result;
                }
                throw new FormatException("comma or brace expected");
            }
        }

        private List<object> ParseArray()
        {
            var result = new List<object>();
            _i++; // [
            SkipSpace();
            if (_i < _s.Length && _s[_i] == ']')
            {
                _i++;
                return result;
            }
            while (true)
            {
                result.Add(ParseValue());
                SkipSpace();
                if (_i >= _s.Length)
                    throw new FormatException("unexpected end");
                if (_s[_i] == ',')
                {
                    _i++;
                    continue;
                }
                if (_s[_i] == ']')
                {
                    _i++;
                    return result;
                }
                throw new FormatException("comma or bracket expected");
            }
        }

        private string ParseString()
        {
            var sb = new StringBuilder();
            _i++; // opening quote
            while (true)
            {
                if (_i >= _s.Length)
                    throw new FormatException("unterminated string");
                char c = _s[_i++];
                if (c == '"')
                    return sb.ToString();
                if (c != '\\')
                {
                    sb.Append(c);
                    continue;
                }
                if (_i >= _s.Length)
                    throw new FormatException("bad escape");
                char e = _s[_i++];
                switch (e)
                {
                    case '"': sb.Append('"'); break;
                    case '\\': sb.Append('\\'); break;
                    case '/': sb.Append('/'); break;
                    case 'b': sb.Append('\b'); break;
                    case 'f': sb.Append('\f'); break;
                    case 'n': sb.Append('\n'); break;
                    case 'r': sb.Append('\r'); break;
                    case 't': sb.Append('\t'); break;
                    case 'u':
                        if (_i + 4 > _s.Length)
                            throw new FormatException("bad unicode escape");
                        sb.Append((char)int.Parse(_s.Substring(_i, 4), NumberStyles.HexNumber, CultureInfo.InvariantCulture));
                        _i += 4;
                        break;
                    default:
                        throw new FormatException("bad escape");
                }
            }
        }

        private object ParseNumber()
        {
            int start = _i;
            bool real = false;
            while (_i < _s.Length)
            {
                char c = _s[_i];
                if ((c >= '0' && c <= '9') || c == '-' || c == '+')
                    _i++;
                else if (c == '.' || c == 'e' || c == 'E')
                {
                    real = true;
                    _i++;
                }
                else
                    break;
            }
            string text = _s.Substring(start, _i - start);
            if (text.Length == 0)
                throw new FormatException("value expected");
            if (!real)
            {
                long whole;
                if (long.TryParse(text, NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out whole))
                    return whole;
            }
            return double.Parse(text, NumberStyles.Float, CultureInfo.InvariantCulture);
        }

        // ---------------------------------------------------------------- writing

        /// <summary>json.dumps(value, indent=2): ASCII only, so any reader takes it.</summary>
        public static string Dump(object value)
        {
            var sb = new StringBuilder();
            Write(sb, value, 0);
            return sb.ToString();
        }

        private static void Indent(StringBuilder sb, int level)
        {
            sb.Append('\n');
            sb.Append(' ', level * 2);
        }

        private static void Write(StringBuilder sb, object value, int level)
        {
            if (value == null)
            {
                sb.Append("null");
            }
            else if (value is bool)
            {
                sb.Append((bool)value ? "true" : "false");
            }
            else if (value is string)
            {
                WriteString(sb, (string)value);
            }
            else if (value is double || value is float)
            {
                double d = Convert.ToDouble(value, CultureInfo.InvariantCulture);
                if (double.IsNaN(d)) sb.Append("NaN");
                else if (double.IsPositiveInfinity(d)) sb.Append("Infinity");
                else if (double.IsNegativeInfinity(d)) sb.Append("-Infinity");
                else
                {
                    string text = d.ToString("R", CultureInfo.InvariantCulture);
                    if (text.IndexOf('.') < 0 && text.IndexOf('E') < 0)
                        text += ".0";
                    sb.Append(text);
                }
            }
            else if (value is long || value is int || value is short || value is byte || value is sbyte
                     || value is ushort || value is uint || value is ulong)
            {
                sb.Append(Convert.ToString(value, CultureInfo.InvariantCulture));
            }
            else if (value is IDictionary)
            {
                var map = (IDictionary)value;
                if (map.Count == 0)
                {
                    sb.Append("{}");
                    return;
                }
                sb.Append('{');
                bool first = true;
                foreach (DictionaryEntry item in map)
                {
                    if (!first) sb.Append(',');
                    first = false;
                    Indent(sb, level + 1);
                    WriteString(sb, Convert.ToString(item.Key, CultureInfo.InvariantCulture));
                    sb.Append(": ");
                    Write(sb, item.Value, level + 1);
                }
                Indent(sb, level);
                sb.Append('}');
            }
            else if (value is IEnumerable)
            {
                var items = new List<object>();
                foreach (object item in (IEnumerable)value)
                    items.Add(item);
                if (items.Count == 0)
                {
                    sb.Append("[]");
                    return;
                }
                sb.Append('[');
                for (int k = 0; k < items.Count; k++)
                {
                    if (k > 0) sb.Append(',');
                    Indent(sb, level + 1);
                    Write(sb, items[k], level + 1);
                }
                Indent(sb, level);
                sb.Append(']');
            }
            else
            {
                WriteString(sb, Convert.ToString(value, CultureInfo.InvariantCulture));
            }
        }

        private static void WriteString(StringBuilder sb, string text)
        {
            sb.Append('"');
            foreach (char c in text)
            {
                switch (c)
                {
                    case '"': sb.Append("\\\""); break;
                    case '\\': sb.Append("\\\\"); break;
                    case '\n': sb.Append("\\n"); break;
                    case '\r': sb.Append("\\r"); break;
                    case '\t': sb.Append("\\t"); break;
                    case '\b': sb.Append("\\b"); break;
                    case '\f': sb.Append("\\f"); break;
                    default:
                        if (c < 0x20 || c > 0x7E)
                            sb.Append("\\u").Append(((int)c).ToString("x4", CultureInfo.InvariantCulture));
                        else
                            sb.Append(c);
                        break;
                }
            }
            sb.Append('"');
        }
    }
}
