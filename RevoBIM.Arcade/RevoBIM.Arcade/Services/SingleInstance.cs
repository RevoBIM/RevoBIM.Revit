using System;
using System.IO;
using System.IO.Pipes;
using System.Threading;
using System.Threading.Tasks;

namespace RevoBIM.Arcade.Services
{
    /// <summary>
    /// One arcade per user session. The first launch owns a named mutex and listens on a named
    /// pipe; a later launch sends its game key down the pipe (empty means just bring forward)
    /// and exits.
    /// </summary>
    public sealed class SingleInstance : IDisposable
    {
        const string MutexName = @"Local\RevoBIM.Arcade.SingleInstance";
        const string PipeName = "RevoBIM.Arcade.Pipe";
        const int MaxMessage = 64;

        Mutex? _mutex;
        CancellationTokenSource? _cts;

        public bool IsFirst { get; private set; }

        public static SingleInstance Acquire()
        {
            var s = new SingleInstance();
            s._mutex = new Mutex(true, MutexName, out var created);
            s.IsFirst = created;
            if (!created) { s._mutex.Dispose(); s._mutex = null; }
            return s;
        }

        /// <summary>Tell the running arcade what to open. False if nobody answered in time.</summary>
        public static bool SendToRunning(string? gameKey, int timeoutMs = 3000)
        {
            try
            {
                using var client = new NamedPipeClientStream(".", PipeName, PipeDirection.Out);
                client.Connect(timeoutMs);
                using var w = new StreamWriter(client) { AutoFlush = true };
                w.WriteLine(Clean(gameKey));
                return true;
            }
            catch { return false; }
        }

        /// <summary>Start listening. onMessage runs on a pool thread; marshal to the UI yourself.</summary>
        public void Listen(Action<string> onMessage)
        {
            if (!IsFirst) return;
            _cts = new CancellationTokenSource();
            var token = _cts.Token;
            Task.Run(async () =>
            {
                while (!token.IsCancellationRequested)
                {
                    try
                    {
                        using var server = new NamedPipeServerStream(PipeName, PipeDirection.In, 1,
                            PipeTransmissionMode.Byte, PipeOptions.Asynchronous);
                        await server.WaitForConnectionAsync(token).ConfigureAwait(false);
                        using var r = new StreamReader(server);
                        var line = await r.ReadLineAsync().ConfigureAwait(false);
                        onMessage(Clean(line));
                    }
                    catch (OperationCanceledException) { break; }
                    catch { await Task.Delay(100).ConfigureAwait(false); }
                }
            }, token);
        }

        /// <summary>Whatever arrives is data: trimmed, lower-cased, length-capped.</summary>
        public static string Clean(string? text)
        {
            var t = (text ?? string.Empty).Trim().ToLowerInvariant();
            return t.Length > MaxMessage ? t.Substring(0, MaxMessage) : t;
        }

        public void Dispose()
        {
            try { _cts?.Cancel(); } catch { }
            try { if (IsFirst) _mutex?.ReleaseMutex(); } catch { }
            _mutex?.Dispose();
            _mutex = null;
        }
    }
}
