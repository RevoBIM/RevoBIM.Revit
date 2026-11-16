using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Security.Cryptography;
using System.Text;

namespace RevoBIM.Tools.ModelCleanup
{
    /// <summary>A small JSON reader and writer - only what the Autodesk Data Management API sends is needed.</summary>
    public static class McuJson
    {
        public sealed class JsonError : Exception
        {
            public JsonError(string message) : base(message) { }
        }

        /// <summary>Objects are Dictionary&lt;string,object&gt;, arrays List&lt;object&gt;, numbers double.</summary>
        public static object Loads(string text)
        {
            int pos = 0;
            object value = ReadValue(text ?? "", ref pos);
            SkipWhite(text, ref pos);
            if (pos != text.Length) throw new JsonError("extra data at character " + pos);
            return value;
        }

        private static void SkipWhite(string text, ref int pos)
        {
            while (pos < text.Length && " \t\r\n".IndexOf(text[pos]) >= 0) pos++;
        }

        private static object ReadValue(string text, ref int pos)
        {
            SkipWhite(text, ref pos);
            if (pos >= text.Length) throw new JsonError("unexpected end");
            char ch = text[pos];
            if (ch == '{') return ReadObject(text, ref pos);
            if (ch == '[') return ReadArray(text, ref pos);
            if (ch == '"') return ReadString(text, ref pos);
            if (string.CompareOrdinal(text, pos, "true", 0, 4) == 0) { pos += 4; return true; }
            if (string.CompareOrdinal(text, pos, "false", 0, 5) == 0) { pos += 5; return false; }
            if (string.CompareOrdinal(text, pos, "null", 0, 4) == 0) { pos += 4; return null; }
            int start = pos;
            while (pos < text.Length && "+-0123456789.eE".IndexOf(text[pos]) >= 0) pos++;
            double number;
            if (pos == start || !double.TryParse(text.Substring(start, pos - start), NumberStyles.Float,
                                                 CultureInfo.InvariantCulture, out number))
                throw new JsonError("unexpected character at " + start);
            return number;
        }

        private static Dictionary<string, object> ReadObject(string text, ref int pos)
        {
            var output = new Dictionary<string, object>();
            pos++;
            SkipWhite(text, ref pos);
            if (pos < text.Length && text[pos] == '}') { pos++; return output; }
            while (true)
            {
                SkipWhite(text, ref pos);
                if (pos >= text.Length || text[pos] != '"') throw new JsonError("expected a key at " + pos);
                string key = ReadString(text, ref pos);
                SkipWhite(text, ref pos);
                if (pos >= text.Length || text[pos] != ':') throw new JsonError("expected ':' at " + pos);
                pos++;
                output[key] = ReadValue(text, ref pos);
                SkipWhite(text, ref pos);
                char ch = pos < text.Length ? text[pos] : '\0';
                pos++;
                if (ch == '}') return output;
                if (ch != ',') throw new JsonError("expected ',' or '}' at " + pos);
            }
        }

        private static List<object> ReadArray(string text, ref int pos)
        {
            var output = new List<object>();
            pos++;
            SkipWhite(text, ref pos);
            if (pos < text.Length && text[pos] == ']') { pos++; return output; }
            while (true)
            {
                output.Add(ReadValue(text, ref pos));
                SkipWhite(text, ref pos);
                char ch = pos < text.Length ? text[pos] : '\0';
                pos++;
                if (ch == ']') return output;
                if (ch != ',') throw new JsonError("expected ',' or ']' at " + pos);
            }
        }

        private static string ReadString(string text, ref int pos)
        {
            pos++;
            var parts = new StringBuilder();
            while (true)
            {
                if (pos >= text.Length) throw new JsonError("unterminated string");
                char ch = text[pos];
                if (ch == '"') { pos++; return parts.ToString(); }
                if (ch == '\\')
                {
                    char code = pos + 1 < text.Length ? text[pos + 1] : '\0';
                    if (code == 'u')
                    {
                        int point;
                        if (pos + 6 > text.Length || !int.TryParse(text.Substring(pos + 2, 4), NumberStyles.HexNumber,
                                                                   CultureInfo.InvariantCulture, out point))
                            throw new JsonError("bad \\u escape");
                        parts.Append((char)point);
                        pos += 6;
                        continue;
                    }
                    switch (code)
                    {
                        case '"': parts.Append('"'); break;
                        case '\\': parts.Append('\\'); break;
                        case '/': parts.Append('/'); break;
                        case 'b': parts.Append('\b'); break;
                        case 'f': parts.Append('\f'); break;
                        case 'n': parts.Append('\n'); break;
                        case 'r': parts.Append('\r'); break;
                        case 't': parts.Append('\t'); break;
                        default: throw new JsonError("bad escape");
                    }
                    pos += 2;
                    continue;
                }
                parts.Append(ch);
                pos++;
            }
        }

        public static string Dumps(object value)
        {
            if (value == null) return "null";
            if (value is bool) return (bool)value ? "true" : "false";
            if (value is string) return Quote((string)value);
            if (value is IDictionary<string, object>)
                return "{" + string.Join(",", ((IDictionary<string, object>)value).OrderBy(p => p.Key, StringComparer.Ordinal)
                                                                                   .Select(p => Quote(p.Key) + ":" + Dumps(p.Value))) + "}";
            if (value is System.Collections.IEnumerable)
                return "[" + string.Join(",", ((System.Collections.IEnumerable)value).Cast<object>().Select(Dumps)) + "]";
            return Convert.ToString(value, CultureInfo.InvariantCulture);
        }

        private static string Quote(string value)
        {
            var builder = new StringBuilder("\"");
            foreach (char ch in value)
            {
                if (ch == '"') builder.Append("\\\"");
                else if (ch == '\\') builder.Append("\\\\");
                else if (ch == '\n') builder.Append("\\n");
                else if (ch == '\r') builder.Append("\\r");
                else if (ch == '\t') builder.Append("\\t");
                else if (ch < 0x20 || ch > 0x7E) builder.Append("\\u").Append(((int)ch).ToString("x4", CultureInfo.InvariantCulture));
                else builder.Append(ch);
            }
            return builder.Append('"').ToString();
        }

        /// <summary>data["a"][0]["b"] without the exceptions; null when any step is missing.</summary>
        public static object Dig(object data, params object[] path)
        {
            object current = data;
            foreach (object step in path)
            {
                var map = current as Dictionary<string, object>;
                var list = current as List<object>;
                if (step is string && map != null)
                {
                    object next;
                    if (!map.TryGetValue((string)step, out next)) return null;
                    current = next;
                }
                else if (step is int && list != null && (int)step >= 0 && (int)step < list.Count)
                {
                    current = list[(int)step];
                }
                else
                {
                    return null;
                }
            }
            return current;
        }

        public static string DigText(object data, params object[] path)
        {
            object value = Dig(data, path);
            return value == null ? "" : Convert.ToString(value, CultureInfo.InvariantCulture);
        }
    }

    /// <summary>
    /// Publish to ACC - every rule, no network. Revit has no API to publish a cloud workshared model.
    /// Autodesk's route is the Data Management API command endpoint (C4RModelPublish and friends), with
    /// a user token from a PKCE sign-in in the browser. Port of mcu_aps.py.
    /// </summary>
    public static class McuAps
    {
        public const string ApsHost = "https://developer.api.autodesk.com";
        public const string AuthorizeUrl = ApsHost + "/authentication/v2/authorize";
        public const string TokenUrl = ApsHost + "/authentication/v2/token";
        public const string Scopes = "data:read data:write data:create";
        public const string CallbackPath = "/revobim/callback";
        public const int DefaultPort = 8765;

        public const string CmdPublish = "commands:autodesk.bim360:C4RModelPublish";
        public const string CmdPublishNoLinks = "commands:autodesk.bim360:C4RPublishWithoutLinks";
        public const string CmdGetJob = "commands:autodesk.bim360:C4RModelGetPublishJob";
        public const string JsonApiType = "application/vnd.api+json";

        public const string LinksAsk = "ask", LinksWith = "with", LinksWithout = "without";
        public static readonly string[] LinkChoices = { LinksAsk, LinksWith, LinksWithout };

        public const string SetupHelp =
            "Publishing needs a one-time setup, because Revit has no publish API and the tool has to use " +
            "Autodesk Platform Services instead:\n\n" +
            "1. At aps.autodesk.com, create an app of type 'Desktop, Mobile, Single-Page App' with the Data " +
            "Management API.\n" +
            "2. Add this callback URL to it: {callback}\n" +
            "3. Ask your ACC account admin to add the app's Client ID under Account Admin > Custom Integrations.\n" +
            "4. Paste the Client ID into Model Cleanup > Export Settings.\n\n" +
            "After that, the first publish opens a browser to sign in once.";

        public static string SetupHelpFor(int port) { return SetupHelp.Replace("{callback}", CallbackUrl(port)); }

        // ============================================================
        // PKCE and sign-in
        // ============================================================

        public static string B64Url(byte[] data)
        {
            return Convert.ToBase64String(data).Replace('+', '-').Replace('/', '_').TrimEnd('=');
        }

        private static byte[] RandomBytes(int count)
        {
            var bytes = new byte[count];
            using (var rng = RandomNumberGenerator.Create()) rng.GetBytes(bytes);
            return bytes;
        }

        public static string NewVerifier() { return B64Url(RandomBytes(48)); }

        public static string ChallengeFor(string verifier)
        {
            using (var sha = SHA256.Create()) return B64Url(sha.ComputeHash(Encoding.ASCII.GetBytes(verifier)));
        }

        public static string NewState() { return B64Url(RandomBytes(18)); }

        public static string CallbackUrl(int port) { return "http://localhost:" + port + CallbackPath; }

        public static string Quote(string value)
        {
            const string safe = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~";
            var output = new StringBuilder();
            foreach (byte b in Encoding.UTF8.GetBytes(value ?? ""))
            {
                char ch = (char)b;
                if (b < 128 && safe.IndexOf(ch) >= 0) output.Append(ch);
                else output.Append('%').Append(b.ToString("X2", CultureInfo.InvariantCulture));
            }
            return output.ToString();
        }

        public static string Unquote(string value)
        {
            string raw = (value ?? "").Replace('+', ' ');
            var data = new List<byte>();
            int index = 0;
            while (index < raw.Length)
            {
                char ch = raw[index];
                int hex;
                if (ch == '%' && index + 2 < raw.Length + 0 &&
                    int.TryParse(raw.Substring(index + 1, 2), NumberStyles.HexNumber, CultureInfo.InvariantCulture, out hex))
                {
                    data.Add((byte)hex);
                    index += 3;
                    continue;
                }
                data.AddRange(Encoding.UTF8.GetBytes(ch.ToString()));
                index++;
            }
            return Encoding.UTF8.GetString(data.ToArray());
        }

        public static string Form(IEnumerable<(string, string)> pairs)
        {
            return string.Join("&", pairs.Select(p => Quote(p.Item1) + "=" + Quote(p.Item2)));
        }

        public static string AuthorizeUrlFor(string clientId, int port, string challenge, string state)
        {
            return AuthorizeUrl + "?" + Form(new[]
            {
                ("response_type", "code"), ("client_id", clientId), ("redirect_uri", CallbackUrl(port)),
                ("scope", Scopes), ("code_challenge", challenge), ("code_challenge_method", "S256"), ("state", state),
            });
        }

        public static string CodeRequest(string clientId, int port, string code, string verifier)
        {
            return Form(new[]
            {
                ("grant_type", "authorization_code"), ("code", code), ("redirect_uri", CallbackUrl(port)),
                ("client_id", clientId), ("code_verifier", verifier),
            });
        }

        public static string RefreshRequest(string clientId, string refreshToken)
        {
            return Form(new[]
            {
                ("grant_type", "refresh_token"), ("refresh_token", refreshToken), ("client_id", clientId), ("scope", Scopes),
            });
        }

        /// <summary>
        /// The browser's first request line. Exactly one of code and error is set; both null means the request
        /// was not the callback (a favicon, say) and should be ignored.
        /// </summary>
        public static (string Code, string Error) ParseCallback(string requestLine, string expectedState)
        {
            string[] parts = (requestLine ?? "").Split(new[] { ' ', '\t' }, StringSplitOptions.RemoveEmptyEntries);
            if (parts.Length < 2) return (null, null);
            string target = parts[1];
            int mark = target.IndexOf('?');
            string path = mark >= 0 ? target.Substring(0, mark) : target;
            string query = mark >= 0 ? target.Substring(mark + 1) : "";
            if (path != CallbackPath) return (null, null);
            var parameters = new Dictionary<string, string>();
            foreach (string pair in query.Split('&'))
            {
                if (pair.Length == 0) continue;
                int eq = pair.IndexOf('=');
                string key = eq >= 0 ? pair.Substring(0, eq) : pair;
                string value = eq >= 0 ? pair.Substring(eq + 1) : "";
                parameters[Unquote(key)] = Unquote(value);
            }
            if (parameters.ContainsKey("error"))
            {
                string description;
                return (null, parameters.TryGetValue("error_description", out description) && description.Length > 0
                              ? description : parameters["error"]);
            }
            string state;
            if (!parameters.TryGetValue("state", out state) || state != expectedState)
                return (null, "The sign-in reply did not match this request. Try again.");
            string code;
            if (!parameters.TryGetValue("code", out code) || code.Length == 0) return (null, "The sign-in reply carried no code.");
            return (code, null);
        }

        public static byte[] CallbackResponse(string message)
        {
            string page = "<html><head><title>RevoBIM</title></head><body style=\"font-family:Segoe UI;" +
                          "background:#232326;color:#E4E4E4;padding:40px\"><h2 style=\"color:#4FA3E3\">RevoBIM</h2><p>" +
                          message + "</p><p style=\"color:#9A9A9E\">You can close this tab and go back to Revit.</p></body></html>";
            byte[] body = Encoding.UTF8.GetBytes(page);
            string head = "HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: " + body.Length +
                          "\r\nConnection: close\r\n\r\n";
            return Encoding.ASCII.GetBytes(head).Concat(body).ToArray();
        }

        // ============================================================
        // tokens
        // ============================================================

        public sealed class Token
        {
            public string Access = "";
            public string Refresh = "";
            public double ExpiresAt;

            public bool Valid(double? now = null, double margin = 120.0)
            {
                double at = now ?? Now();
                return Access.Length > 0 && at < ExpiresAt - margin;
            }
        }

        public static double Now() { return (DateTime.UtcNow - new DateTime(1970, 1, 1)).TotalSeconds; }

        public static Token TokenFromReply(string body, double? now = null)
        {
            var data = McuJson.Loads(body);
            string access = McuJson.DigText(data, "access_token");
            if (access.Length == 0) throw new InvalidOperationException("Autodesk returned no access token: " + DescribeError(data));
            double seconds;
            double.TryParse(McuJson.DigText(data, "expires_in"), NumberStyles.Float, CultureInfo.InvariantCulture, out seconds);
            return new Token { Access = access, Refresh = McuJson.DigText(data, "refresh_token"), ExpiresAt = (now ?? Now()) + seconds };
        }

        public static string DescribeError(object data)
        {
            var map = data as Dictionary<string, object>;
            if (map == null)
            {
                string text = Convert.ToString(data, CultureInfo.InvariantCulture) ?? "";
                return text.Length > 300 ? text.Substring(0, 300) : text;
            }
            foreach (string key in new[] { "developerMessage", "error_description", "errorDescription", "message", "error" })
            {
                string value = McuJson.DigText(map, key);
                if (value.Length > 0) return value;
            }
            var errors = McuJson.Dig(map, "errors") as List<object>;
            if (errors != null && errors.Count > 0)
            {
                var first = errors[0] as Dictionary<string, object>;
                if (first != null)
                {
                    string detail = McuJson.DigText(first, "detail");
                    if (detail.Length == 0) detail = McuJson.DigText(first, "title");
                    if (detail.Length > 0) return detail;
                }
                return Convert.ToString(errors[0], CultureInfo.InvariantCulture) ?? "";
            }
            string dump = McuJson.Dumps(map);
            return dump.Length > 300 ? dump.Substring(0, 300) : dump;
        }

        /// <summary>A sentence for a failed call, naming the usual cause.</summary>
        public static string ExplainStatus(int status, string body)
        {
            string detail;
            try { detail = DescribeError(McuJson.Loads(body)); }
            catch (Exception) { detail = (body ?? "").Length > 300 ? body.Substring(0, 300) : body ?? ""; }
            string head;
            switch (status)
            {
                case 400: head = "Autodesk did not accept the request."; break;
                case 401: head = "The sign-in has expired. Sign in again."; break;
                case 403:
                    head = "Autodesk refused. Usually the APS app has not been added under ACC Account Admin > " +
                           "Custom Integrations, or you lack edit rights on this model's folder.";
                    break;
                case 404: head = "Autodesk could not find this model or project."; break;
                case 409: head = "A publish is already running for this model."; break;
                case 429: head = "Autodesk is rate limiting. Wait a minute and try again."; break;
                default: head = "Autodesk returned HTTP " + status + "."; break;
            }
            return head + (detail.Length > 0 ? "\n\n" + detail : "");
        }

        // ============================================================
        // ids
        // ============================================================

        /// <summary>ACC / BIM 360 project ids in the Data Management API carry 'b.'.</summary>
        public static string DmProjectId(string projectId)
        {
            string value = (projectId ?? "").Trim();
            if (value.Length == 0) return "";
            return value.StartsWith("b.") ? value : "b." + value;
        }

        public static bool IsLineage(string urn)
        {
            urn = urn ?? "";
            return urn.StartsWith("urn:adsk.wipprod:dm.lineage:") || urn.StartsWith("urn:adsk.wipemea:dm.lineage:");
        }

        public static bool IsVersion(string urn) { return (urn ?? "").Contains(":fs.file:"); }

        public static string ItemFromVersionReply(string body)
        {
            return McuJson.DigText(McuJson.Loads(body), "data", "relationships", "item", "data", "id");
        }

        /// <summary>Folder contents -> the item whose version carries this model GUID.</summary>
        public static string ItemFromFolderReply(string body, string modelGuid)
        {
            var data = McuJson.Loads(body);
            string wanted = (modelGuid ?? "").ToLowerInvariant().Trim('{', '}');
            var included = McuJson.Dig(data, "included") as List<object>;
            if (included == null) return null;
            foreach (object version in included)
            {
                string guid = McuJson.DigText(version, "attributes", "extension", "data", "modelGuid");
                if (guid.Length > 0 && guid.ToLowerInvariant().Trim('{', '}') == wanted)
                {
                    string item = McuJson.DigText(version, "relationships", "item", "data", "id");
                    if (item.Length > 0) return item;
                }
            }
            return null;
        }

        public static string CommandsUrl(string projectId) { return ApsHost + "/data/v1/projects/" + DmProjectId(projectId) + "/commands"; }

        public static string VersionUrl(string projectId, string versionUrn)
        {
            return ApsHost + "/data/v1/projects/" + DmProjectId(projectId) + "/versions/" + Quote(versionUrn);
        }

        public static string FolderUrl(string projectId, string folderUrn)
        {
            return ApsHost + "/data/v1/projects/" + DmProjectId(projectId) + "/folders/" + Quote(folderUrn) + "/contents";
        }

        public static string CommandBody(string commandType, string itemUrn)
        {
            var resource = new Dictionary<string, object> { { "type", "items" }, { "id", itemUrn } };
            return McuJson.Dumps(new Dictionary<string, object>
            {
                { "jsonapi", new Dictionary<string, object> { { "version", "1.0" } } },
                { "data", new Dictionary<string, object>
                    {
                        { "type", "commands" },
                        { "attributes", new Dictionary<string, object>
                            { { "extension", new Dictionary<string, object> { { "type", commandType }, { "version", "1.0.0" } } } } },
                        { "relationships", new Dictionary<string, object>
                            { { "resources", new Dictionary<string, object> { { "data", new List<object> { resource } } } } } },
                    } },
            });
        }

        public static string PublishCommand(bool withLinks) { return withLinks ? CmdPublish : CmdPublishNoLinks; }

        // ============================================================
        // the publish job
        // ============================================================

        public const string JobNeeded = "needed", JobRunning = "running", JobDone = "done", JobFailed = "failed", JobUnknown = "unknown";

        /// <summary>data null means the latest sync is not published yet; otherwise the job's status.</summary>
        public static (string State, string Status) JobState(string body)
        {
            var data = McuJson.Loads(body);
            if (McuJson.Dig(data, "data") == null) return (JobNeeded, "not published since the last sync");
            string status = McuJson.DigText(data, "data", "attributes", "status").ToLowerInvariant();
            if (new[] { "processing", "queued", "pending", "inprogress", "in_progress" }.Contains(status)) return (JobRunning, status);
            if (new[] { "complete", "completed", "success", "succeeded" }.Contains(status)) return (JobDone, status);
            if (new[] { "failed", "failure", "error", "cancelled" }.Contains(status)) return (JobFailed, status);
            return (JobUnknown, status.Length > 0 ? status : "no status");
        }

        public static string JobLine(string state, string status, string elapsedText)
        {
            string words;
            switch (state)
            {
                case JobNeeded: words = "Waiting for ACC to pick it up"; break;
                case JobRunning: words = "Publishing on ACC"; break;
                case JobDone: words = "Published on ACC"; break;
                case JobFailed: words = "ACC reports the publish failed"; break;
                case JobUnknown: words = "ACC status"; break;
                default: words = "ACC"; break;
            }
            return words + " (" + status + ") - " + elapsedText;
        }

        public static bool PollShouldStop(string state, double elapsed, double limit = 900.0)
        {
            return state == JobDone || state == JobFailed || elapsed >= limit;
        }

        public static string NormaliseLinks(string value)
        {
            value = (value ?? "").Trim().ToLowerInvariant();
            return LinkChoices.Contains(value) ? value : LinksAsk;
        }

        /// <summary>Null when the Publish button may light, else why not.</summary>
        public static string CanPublish(McuModelInfo info, bool synced)
        {
            if (!info.Cloud) return "Only cloud models on ACC can be published.";
            if (!info.Workshared) return "Only workshared cloud models are published.";
            if (!synced) return "Sync first - ACC publishes the latest synced version.";
            return null;
        }
    }
}
