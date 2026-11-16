using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Text;
using Autodesk.Revit.DB;
using static RevoBIM.Tools.ModelCleanup.McuCore;

namespace RevoBIM.Tools.ModelCleanup
{
    /// <summary>
    /// Publish to ACC - the parts that need the network. HTTP through WebRequest, the sign-in callback
    /// through a plain TcpListener on the loopback address (no URL reservation or admin rights needed),
    /// the browser through the shell, and the refresh token encrypted with Windows DPAPI for the current
    /// user (looked up by reflection, so no extra package is shipped). If DPAPI is not available the token
    /// is kept for this run only. The waiting loop polls the socket for 0.2 s at a time and pumps the
    /// window between polls; it never sleeps on Revit's thread. Port of mcu_web.py.
    /// </summary>
    public static class McuWeb
    {
        public sealed class PublishError : Exception
        {
            public PublishError(string message) : base(message) { }
        }

        public sealed class Cancelled : Exception { }

        // the token for this run of the tool
        private static McuAps.Token sessionToken;
        private static string sessionClient = "";

        // ============================================================
        // HTTP
        // ============================================================

        /// <summary>(status, text). Non-2xx answers are returned, not raised.</summary>
        public static (int Status, string Text) Http(string method, string url, string body = null,
            string contentType = null, string token = null, int timeoutMs = 30000)
        {
            try
            {
                ServicePointManager.SecurityProtocol |= SecurityProtocolType.Tls12;
            }
            catch (Exception) { }
            var request = (HttpWebRequest)WebRequest.Create(url);
            request.Method = method;
            request.Timeout = timeoutMs;
            request.Accept = "application/json, application/vnd.api+json";
            if (!string.IsNullOrEmpty(token)) request.Headers.Add("Authorization", "Bearer " + token);
            if (body != null)
            {
                byte[] data = Encoding.UTF8.GetBytes(body);
                request.ContentType = contentType;
                request.ContentLength = data.Length;
                using (Stream stream = request.GetRequestStream()) stream.Write(data, 0, data.Length);
            }
            WebResponse response;
            try
            {
                response = request.GetResponse();
            }
            catch (WebException error)
            {
                response = error.Response;
                if (response == null)
                    throw new PublishError("No answer from Autodesk (" + error.Message + "). Check the internet connection or proxy.");
            }
            int status;
            string text;
            using (response)
            {
                status = (int)((HttpWebResponse)response).StatusCode;
                using (var reader = new StreamReader(response.GetResponseStream(), Encoding.UTF8)) text = reader.ReadToEnd();
            }
            Log("APS " + method + " " + url.Split('?')[0] + " -> " + status);
            return (status, text);
        }

        public static bool Ok(int status) { return status >= 200 && status < 300; }

        // ============================================================
        // token store (DPAPI)
        // ============================================================

        public static string StorePath() { return Path.Combine(AppDataDir(), "model_cleanup_aps.txt"); }

        private static Type ProtectedDataType()
        {
            foreach (string name in new[]
            {
                "System.Security.Cryptography.ProtectedData, System.Security",
                "System.Security.Cryptography.ProtectedData, System.Security.Cryptography.ProtectedData",
            })
            {
                try
                {
                    Type type = Type.GetType(name, false);
                    if (type != null) return type;
                }
                catch (Exception) { }
            }
            return null;
        }

        private static string Dpapi(bool protect, string value)
        {
            try
            {
                Type type = ProtectedDataType();
                if (type == null) return null;
                Type scopeType = type.Assembly.GetType("System.Security.Cryptography.DataProtectionScope");
                object currentUser = Enum.Parse(scopeType, "CurrentUser");
                MethodInfo method = type.GetMethod(protect ? "Protect" : "Unprotect",
                    new[] { typeof(byte[]), typeof(byte[]), scopeType });
                byte[] input = protect ? Encoding.UTF8.GetBytes(value) : Convert.FromBase64String(value);
                byte[] output = (byte[])method.Invoke(null, new object[] { input, null, currentUser });
                return protect ? Convert.ToBase64String(output) : Encoding.UTF8.GetString(output);
            }
            catch (Exception) { return null; }
        }

        public static bool SaveRefresh(string clientId, string refresh)
        {
            string protectedText = string.IsNullOrEmpty(refresh) ? null : Dpapi(true, refresh);
            if (string.IsNullOrEmpty(protectedText))
            {
                Forget();
                return false;
            }
            return WriteKv(StorePath(), new[]
            {
                new KeyValuePair<string, string>("client_id", clientId),
                new KeyValuePair<string, string>("refresh", protectedText),
            }, "RevoBIM ACC sign-in (encrypted for this Windows user)");
        }

        public static string LoadRefresh(string clientId)
        {
            var raw = ReadKv(StorePath());
            if (raw.Get("client_id") != clientId || raw.Get("refresh").Length == 0) return "";
            return Dpapi(false, raw["refresh"]) ?? "";
        }

        public static void Forget()
        {
            sessionToken = null;
            try
            {
                if (File.Exists(StorePath())) File.Delete(StorePath());
            }
            catch (Exception) { }
        }

        public static string SignedInText(string clientId)
        {
            if (sessionToken != null && sessionClient == clientId && sessionToken.Valid()) return "Signed in for this session.";
            if (clientId.Length > 0 && LoadRefresh(clientId).Length > 0) return "Signed in (remembered for this Windows user).";
            return "Not signed in. The first publish opens the browser.";
        }

        // ============================================================
        // sign-in
        // ============================================================

        public static void OpenBrowser(string url)
        {
            Process.Start(new ProcessStartInfo(url) { UseShellExecute = true });
        }

        private static string ReadRequestLine(NetworkStream stream)
        {
            var buffer = new byte[8192];
            int count = stream.Read(buffer, 0, buffer.Length);
            if (count <= 0) return "";
            string text = Encoding.ASCII.GetString(buffer, 0, count);
            return text.Split(new[] { "\r\n" }, StringSplitOptions.None)[0];
        }

        /// <summary>Browser sign-in. tick() is called between socket polls; it pumps the window and throws Cancelled on Escape.</summary>
        public static McuAps.Token SignIn(string clientId, int port, Action tick, double timeout = 240.0)
        {
            string verifier = McuAps.NewVerifier();
            string state = McuAps.NewState();
            var listener = new TcpListener(IPAddress.Loopback, port);
            try
            {
                listener.Start();
            }
            catch (Exception)
            {
                throw new PublishError("Port " + port + " is already in use on this PC. Pick another sign-in port in " +
                                       "Export Settings, and add the matching callback URL to the APS app:\n" + McuAps.CallbackUrl(port));
            }
            string code = null;
            try
            {
                OpenBrowser(McuAps.AuthorizeUrlFor(clientId, port, McuAps.ChallengeFor(verifier), state));
                DateTime started = DateTime.UtcNow;
                while (code == null)
                {
                    if ((DateTime.UtcNow - started).TotalSeconds > timeout)
                        throw new PublishError("No sign-in arrived within " + (int)(timeout / 60) + " minutes.");
                    tick();
                    if (!listener.Server.Poll(200000, SelectMode.SelectRead)) continue;
                    using (TcpClient client = listener.AcceptTcpClient())
                    {
                        client.ReceiveTimeout = 5000;
                        NetworkStream stream = client.GetStream();
                        string line = ReadRequestLine(stream);
                        var (found, error) = McuAps.ParseCallback(line, state);
                        byte[] reply;
                        if (found != null)
                        {
                            code = found;
                            reply = McuAps.CallbackResponse("Signed in. Model Cleanup is publishing.");
                        }
                        else if (error != null)
                        {
                            reply = McuAps.CallbackResponse("Sign-in failed: " + error);
                            stream.Write(reply, 0, reply.Length);
                            throw new PublishError("Sign-in failed: " + error);
                        }
                        else
                        {
                            reply = McuAps.CallbackResponse("Waiting for sign-in.");
                        }
                        stream.Write(reply, 0, reply.Length);
                    }
                }
            }
            finally
            {
                try { listener.Stop(); } catch (Exception) { }
            }
            var (status, body) = Http("POST", McuAps.TokenUrl, McuAps.CodeRequest(clientId, port, code, verifier),
                                      "application/x-www-form-urlencoded");
            if (!Ok(status)) throw new PublishError("Sign-in could not be completed.\n\n" + McuAps.ExplainStatus(status, body));
            return McuAps.TokenFromReply(body);
        }

        public static McuAps.Token Refresh(string clientId, string refreshToken)
        {
            var (status, body) = Http("POST", McuAps.TokenUrl, McuAps.RefreshRequest(clientId, refreshToken),
                                      "application/x-www-form-urlencoded");
            if (!Ok(status)) return null;
            try { return McuAps.TokenFromReply(body); }
            catch (Exception) { return null; }
        }

        /// <summary>A valid access token: this run's, else a refreshed remembered one, else a browser sign-in (null if not allowed).</summary>
        public static string GetToken(string clientId, int port, Action tick, bool allowBrowser = true)
        {
            McuAps.Token token = sessionToken;
            if (token != null && sessionClient == clientId && token.Valid()) return token.Access;
            token = null;
            string remembered = LoadRefresh(clientId);
            if (remembered.Length > 0)
            {
                token = Refresh(clientId, remembered);
                if (token == null) Forget();
            }
            if (token == null || !token.Valid())
            {
                if (!allowBrowser) return null;
                token = SignIn(clientId, port, tick);
            }
            sessionToken = token;
            sessionClient = clientId;
            if (token.Refresh.Length > 0 && !SaveRefresh(clientId, token.Refresh))
                Log("ACC sign-in kept for this run only - DPAPI is not available");
            return token.Access;
        }

        // ============================================================
        // the model on ACC
        // ============================================================

        private static string CallString(Document doc, string name)
        {
            try
            {
                MethodInfo method = doc.GetType().GetMethod(name, Type.EmptyTypes);
                if (method != null) return Convert.ToString(method.Invoke(doc, null)) ?? "";
                method = doc.GetType().GetMethod(name, new[] { typeof(bool) });
                if (method != null) return Convert.ToString(method.Invoke(doc, new object[] { false })) ?? "";
            }
            catch (Exception) { }
            return "";
        }

        public static string ModelGuid(Document doc)
        {
            try { return doc.GetCloudModelPath().GetModelGUID().ToString(); }
            catch (Exception) { return ""; }
        }

        /// <summary>(project id, item lineage urn) of the open cloud model.</summary>
        public static (string Project, string Item) ResolveItem(Document doc, string token)
        {
            string project = McuAps.DmProjectId(CallString(doc, "GetProjectId"));
            if (project.Length == 0) throw new PublishError("Revit did not report which ACC project this model is in.");
            string urn = CallString(doc, "GetCloudModelUrn");
            if (McuAps.IsLineage(urn)) return (project, urn);
            if (McuAps.IsVersion(urn))
            {
                var (status, body) = Http("GET", McuAps.VersionUrl(project, urn), token: token);
                if (Ok(status))
                {
                    string item = McuAps.ItemFromVersionReply(body);
                    if (!string.IsNullOrEmpty(item)) return (project, item);
                }
            }
            string folder = CallString(doc, "GetCloudFolderId");
            string guid = ModelGuid(doc);
            string url = folder.Length > 0 ? McuAps.FolderUrl(project, folder) : "";
            int pages = 0;
            while (url.Length > 0 && pages < 20)
            {
                var (status, body) = Http("GET", url, token: token);
                if (!Ok(status)) throw new PublishError(McuAps.ExplainStatus(status, body));
                string item = McuAps.ItemFromFolderReply(body, guid);
                if (!string.IsNullOrEmpty(item)) return (project, item);
                url = McuJson.DigText(McuJson.Loads(body), "links", "next", "href");
                pages++;
            }
            throw new PublishError("This model could not be found in its ACC folder.");
        }

        private static (int Status, string Text) Command(string token, string project, string commandType, string item)
        {
            return Http("POST", McuAps.CommandsUrl(project), McuAps.CommandBody(commandType, item), McuAps.JsonApiType, token);
        }

        public static (string State, string Status) JobState(string token, string project, string item)
        {
            var (status, body) = Command(token, project, McuAps.CmdGetJob, item);
            if (!Ok(status)) return (McuAps.JobUnknown, "HTTP " + status);
            try { return McuAps.JobState(body); }
            catch (Exception) { return (McuAps.JobUnknown, "unreadable reply"); }
        }

        public static (bool Sent, int Code) Publish(string token, string project, string item, bool withLinks)
        {
            var (status, body) = Command(token, project, McuAps.PublishCommand(withLinks), item);
            if (status == 401) return (false, 401);
            if (!Ok(status)) throw new PublishError(McuAps.ExplainStatus(status, body));
            return (true, status);
        }
    }
}
