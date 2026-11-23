using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Windows.Automation;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Selection;

namespace RevoBIM.Tools.HangerAutomation
{
    /// <summary>What the Finish Selection card says while Revit waits on a multiple selection.</summary>
    public sealed class FinishRequest
    {
        public string Eyebrow = "SELECTION";
        public string Title = "";
        public string Detail = "";
        public string Hint = FhaFinish.HintText;
        /// <summary>Revit's main window (UIApplication.MainWindowHandle) - where Finish is pressed.</summary>
        public IntPtr MainWindow = IntPtr.Zero;
    }

    /// <summary>
    /// The Finish Selection button: an alternative to the Finish button on Revit's Options Bar. Port of the BWIC
    /// Penetration tool's press_finish / finish_armed / arm_finish (bwic_core.py, bwic_prompt.py, script.py).
    ///
    /// PickObjects is the one way the tool asks for a multiple selection: it arms the card the window shows, runs
    /// Revit's pick and, whatever the pick ends with (Finish, Esc, an error), disarms it again - the card never stays
    /// on screen after the pick returns. The window registers Listener; Listener(request) arms the card,
    /// Listener(null) disarms it. Press() finishes the selection Revit is waiting on, as its Finish button would:
    ///
    ///   1. as a Windows button among Revit's child windows (BM_CLICK on a visible, enabled one whose text is
    ///      exactly "Finish"),
    ///   2. else through UI Automation (Invoke on a Button named Finish),
    ///   3. else Return is posted straight to the active view's window.
    ///
    /// It runs on its own thread, after the click handler has returned: Revit's window answers UI Automation and
    /// SendMessage on the UI thread, which the click handler would otherwise still be holding. Only ever pressed
    /// while a pick is armed (Return with nothing waiting repeats Revit's last command), and once per pick.
    /// The worker's debug lines are kept in a locked buffer and written to the running job's debug log on the
    /// Revit thread (the log itself is not thread safe).
    /// </summary>
    public static class FhaFinish
    {
        /// <summary>The hint line under the card's description.</summary>
        public const string HintText = "Finish Selection  \u00B7  Options Bar Finish  \u00B7  Return     \u00B7     Esc to stop";

        /// <summary>How every card description ends.</summary>
        public const string Then = "then click Finish on the Options Bar, top left, or press Return, or use Finish Selection below.";

        /// <summary>"Pick the hangers" -> "Pick the hangers, then click Finish on the Options Bar, ...".</summary>
        public static string Detail(string pick)
        {
            return (pick ?? "Pick the elements").TrimEnd(' ', ',', '.') + ", " + Then;
        }

        /// <summary>
        /// The window's callback: Listener(request) shows the card, Listener(null) hides it. Null while no window is
        /// open. It is called on the thread that picks (Revit's), and must guard itself with the window's Dispatcher.
        /// </summary>
        public static Action<FinishRequest> Listener;

        private static volatile FinishRequest current;
        private static volatile bool pressed;
        private static IntPtr lastMain = IntPtr.Zero;
        private static FhaDebugLog armedLog;

        private static readonly object Gate = new object();
        private static readonly List<string> Pending = new List<string>();

        /// <summary>True while a multiple selection is waiting and the button may be pressed.</summary>
        public static bool Armed
        {
            get { return current != null; }
        }

        /// <summary>True once Finish was pressed for the pick now waiting (it is pressed once per pick).</summary>
        public static bool Pressed
        {
            get { return pressed; }
        }

        /// <summary>The request on the card now, or null.</summary>
        public static FinishRequest Current
        {
            get { return current; }
        }

        // ================================================================ the pick
        /// <summary>
        /// uidoc.Selection.PickObjects(Element, filter, prompt) with the Finish Selection card shown for the length
        /// of the pick. Esc still throws OperationCanceledException, as the plain call does; the card is gone either way.
        /// </summary>
        public static IList<Reference> PickObjects(UIDocument uidoc, ISelectionFilter filter, string prompt, string title = null, string detail = null)
        {
            var req = new FinishRequest();
            req.Title = string.IsNullOrEmpty(title) ? "Select the elements" : title;
            req.Detail = string.IsNullOrEmpty(detail) ? Detail("Pick the elements") : detail;
            try
            {
                req.MainWindow = uidoc.Application.MainWindowHandle;
            }
            catch (Exception)
            {
            }
            Arm(req);
            string outcome = "error";
            try
            {
                IList<Reference> refs = uidoc.Selection.PickObjects(ObjectType.Element, filter, prompt);
                outcome = "picked " + (refs == null ? 0 : refs.Count);
                return refs;
            }
            catch (Autodesk.Revit.Exceptions.OperationCanceledException)
            {
                outcome = "cancelled";
                throw;
            }
            finally
            {
                Disarm(outcome);
            }
        }

        /// <summary>Show the card (the Python arm_finish(True) on a step that ends with Finish).</summary>
        public static void Arm(FinishRequest req)
        {
            if (req == null) return;
            FlushLog();   // a late line of the last press goes out before this pick's own
            try
            {
                armedLog = FhaRevit.CurrentLog;
            }
            catch (Exception)
            {
                armedLog = null;
            }
            current = req;
            pressed = false;
            if (req.MainWindow != IntPtr.Zero) lastMain = req.MainWindow;
            Log("Finish Selection: armed for \"" + req.Title + "\"");
            Notify(req);
            StartPrewarm(req);
        }

        // ================================================================ finding the button ahead of the click
        // Searching Revit's whole UI Automation tree takes seconds. The search starts as soon as a pick is armed, on its own
        // thread, while the user is still selecting, so the click only has to Invoke the button already found. The element found
        // is kept: Revit's Options Bar / ribbon Finish (AutomationId ID_FINISH_MULTI_PICK_DBAR) is usually the same element
        // pick after pick, and a stale one fails its first property read and is searched for again.
        private const string FinishId = "ID_FINISH_MULTI_PICK_DBAR";
        private static AutomationElement found;
        private static long foundMs = -1;

        private static void StartPrewarm(FinishRequest req)
        {
            IntPtr hwnd = req.MainWindow != IntPtr.Zero ? req.MainWindow : lastMain;
            if (hwnd == IntPtr.Zero) return;
            try
            {
                var t = new Thread(new ThreadStart(() => Prewarm(req, hwnd)));
                t.IsBackground = true;
                t.Name = "FhaFinishPrewarm";
                t.Start();
            }
            catch (Exception)
            {
            }
        }

        private static void Prewarm(FinishRequest req, IntPtr hwnd)
        {
            try
            {
                if (Usable(found) && Ready(found))
                {
                    Log("Finish Selection: button from the last pick still there");
                    return;
                }
                found = null;
                foundPat = null;
                var sw = System.Diagnostics.Stopwatch.StartNew();
                for (int i = 0; i < 20 && ReferenceEquals(current, req) && !pressed; i++)   // the button appears once the pick has started
                {
                    AutomationElement e = FindFinishFast(hwnd);
                    if (e != null && Ready(e))
                    {
                        found = e;
                        foundMs = sw.ElapsedMilliseconds;
                        Log("Finish Selection: button found ahead of the click in " + foundMs + " ms");
                        return;
                    }
                    Thread.Sleep(250);
                }
                Log("Finish Selection: button not found ahead of the click (" + sw.ElapsedMilliseconds + " ms)");
            }
            catch (Exception ex)
            {
                Log("Finish Selection: search ahead failed: " + ex.Message);
            }
        }

        /// <summary>True when the element still answers and can be pressed.</summary>
        private static bool Usable(AutomationElement e)
        {
            if (e == null) return false;
            try
            {
                return e.Current.IsEnabled && !e.Current.IsOffscreen;
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>FindFirst (stops at the first match) for Revit's Finish button by its AutomationId, else by name.</summary>
        private static AutomationElement FindFinishFast(IntPtr hwnd)
        {
            AutomationElement root = AutomationElement.FromHandle(hwnd);
            System.Windows.Automation.Condition byId = new AndCondition(new PropertyCondition(AutomationElement.AutomationIdProperty, FinishId),
                                              new PropertyCondition(AutomationElement.IsInvokePatternAvailableProperty, true));
            AutomationElement e = root.FindFirst(TreeScope.Descendants, byId);
            if (e != null) return e;
            System.Windows.Automation.Condition byName = new AndCondition(new PropertyCondition(AutomationElement.NameProperty, "Finish", PropertyConditionFlags.IgnoreCase),
                                                new PropertyCondition(AutomationElement.IsInvokePatternAvailableProperty, true));
            return root.FindFirst(TreeScope.Descendants, byName);
        }

        /// <summary>The button's Invoke pattern, fetched ahead of the click too: the press is then a single call into Revit.</summary>
        private static volatile InvokePattern foundPat;

        private static bool Ready(AutomationElement e)
        {
            try
            {
                object pat;
                if (!e.TryGetCurrentPattern(InvokePattern.Pattern, out pat)) return false;
                foundPat = (InvokePattern)pat;
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>Invoke the button found ahead of the click: straight through its pattern (no checks first - each check is
        /// another round trip into Revit); if that fails, the slower checked route below.</summary>
        private static bool InvokeFound()
        {
            InvokePattern ip = foundPat;
            if (ip != null)
            {
                var sw = System.Diagnostics.Stopwatch.StartNew();
                try
                {
                    ip.Invoke();
                    Log("Finish Selection: pressed the button found ahead of the click (" + sw.ElapsedMilliseconds + " ms)");
                    return true;
                }
                catch (Exception ex)
                {
                    Log("Finish Selection: the button found ahead is gone (" + ex.Message + ") - searching again");
                    foundPat = null;
                    found = null;
                }
            }
            AutomationElement e = found;
            if (!Usable(e)) return false;
            try
            {
                object pat;
                if (!e.TryGetCurrentPattern(InvokePattern.Pattern, out pat)) return false;
                Log("Finish Selection: invoking the button found ahead of the click");
                ((InvokePattern)pat).Invoke();
                return true;
            }
            catch (Exception ex)
            {
                Log("Finish Selection: the button found ahead failed: " + ex.Message);
                found = null;
                return false;
            }
        }

        /// <summary>Hide the card (the Python arm_finish(False)).</summary>
        public static void Disarm(string why = null)
        {
            bool was = current != null;
            current = null;
            pressed = false;
            if (was) Log("Finish Selection: disarmed" + (string.IsNullOrEmpty(why) ? "" : " (" + why + ")"));
            Notify(null);
            FlushLog();
            armedLog = null;
        }

        private static void Notify(FinishRequest req)
        {
            Action<FinishRequest> l = Listener;
            if (l == null) return;
            try
            {
                l(req);
            }
            catch (Exception ex)
            {
                Log("Finish Selection: the window could not show the card: " + ex.Message);
            }
        }

        // ================================================================ pressing Finish
        /// <summary>
        /// Finish the selection Revit is waiting on, as its Finish button would (press_finish). False if nothing is
        /// armed, it was pressed already, or it could not be started - the caller may then re-enable the button.
        /// </summary>
        public static bool Press()
        {
            try
            {
                if (current == null || pressed)
                {
                    Log("Finish Selection: not pressed (" + (current == null ? "nothing is waiting on it" : "already pressed for this pick") + ")");
                    return false;
                }
                IntPtr hwnd = current.MainWindow != IntPtr.Zero ? current.MainWindow : lastMain;
                if (hwnd == IntPtr.Zero)
                {
                    Log("Finish Selection: no Revit window handle");
                    return false;
                }
                // the click gave the tool window the keyboard: hand it back to Revit so the next pick answers straight away
                FocusRevit(hwnd);
                pressed = true;
                try
                {
                    var worker = new Thread(new ThreadStart(() => PressFinish(hwnd)));
                    worker.IsBackground = true;
                    worker.Name = "FhaFinishSelection";
                    worker.Start();
                    return true;
                }
                catch (Exception ex)
                {
                    pressed = false;
                    Log("Finish Selection could not start: " + ex.Message);
                    return false;
                }
            }
            catch (Exception ex)
            {
                try
                {
                    pressed = false;
                    Log("Finish Selection: " + ex.Message);
                }
                catch (Exception)
                {
                }
                return false;
            }
        }

        /// <summary>The worker. An exception escaping a .NET thread ends Revit: nothing may get out.</summary>
        private static void PressFinish(IntPtr hwnd)
        {
            try
            {
                FinishRequest req = current;
                // each way is tried in turn and checked: if Revit is still waiting on the pick afterwards, the next way runs
                if (InvokeFound() && Landed(req, "button found ahead", 600)) return;
                if (FinishByButton(hwnd) && Landed(req, "Win32 button")) return;
                AutomationElement fast = null;
                try { fast = FindFinishFast(hwnd); }
                catch (Exception) { }
                if (fast != null)
                {
                    found = fast;
                    if (InvokeFound() && Landed(req, "UI Automation (quick search)")) return;
                }
                if (FinishByAutomation(hwnd) && Landed(req, "UI Automation")) return;
                if (FinishByMouse(hwnd) && Landed(req, "mouse click")) return;
                FinishByReturn(hwnd);
                Landed(req, "Return");
            }
            catch (Exception ex)
            {
                try
                {
                    Log("Finish Selection failed: " + ex.Message);
                }
                catch (Exception)
                {
                }
            }
        }

        /// <summary>
        /// Wait (up to ~1.5 s) for the pick to end after a press. The pick ending disarms the card, so a request that is
        /// still current afterwards means Revit did not take the press.
        /// </summary>
        private static bool Landed(FinishRequest req, string how, int maxMs = 1500)
        {
            for (int i = 0; i < maxMs / 50; i++)
            {
                Thread.Sleep(50);
                if (!ReferenceEquals(current, req))
                {
                    Log("Finish Selection: " + how + " finished the pick (" + ((i + 1) * 50) + " ms)");
                    return true;
                }
            }
            Log("Finish Selection: " + how + " had no effect, Revit is still waiting - trying the next way");
            return false;
        }

        // ---- 1. the button as a Windows window
        private sealed class ChildWin
        {
            public IntPtr Handle;
            public string Class, Text;
            public bool Visible, Enabled;
        }

        /// <summary>(handle, class, text, visible, enabled) for every child window.</summary>
        private static List<ChildWin> ChildWindows(IntPtr hwnd)
        {
            var found = new List<ChildWin>();
            Native.EnumProc visit = (child, lp) =>
            {
                try
                {
                    var cls = new StringBuilder(128);
                    Native.GetClassName(child, cls, 128);
                    int length = Native.GetWindowTextLength(child);
                    var text = new StringBuilder(length + 1);
                    Native.GetWindowText(child, text, length + 1);
                    found.Add(new ChildWin
                    {
                        Handle = child, Class = cls.ToString(), Text = text.ToString(),
                        Visible = Native.IsWindowVisible(child), Enabled = Native.IsWindowEnabled(child),
                    });
                }
                catch (Exception)
                {
                }
                return true;
            };
            Native.EnumChildWindows(hwnd, visit, IntPtr.Zero);
            GC.KeepAlive(visit);
            return found;
        }

        private static bool FinishByButton(IntPtr hwnd)
        {
            List<ChildWin> windows = ChildWindows(hwnd);
            foreach (ChildWin w in windows)
            {
                if (w.Visible && w.Enabled && IsFinishLabel(w.Text))
                {
                    Log("Finish Selection: pressing the Options Bar button \"" + w.Text + "\" (" + w.Class + ")");
                    Native.SendMessage(w.Handle, Native.BM_CLICK, IntPtr.Zero, IntPtr.Zero);
                    return true;
                }
            }
            var cand = new StringBuilder();
            foreach (ChildWin w in windows)
            {
                if (w.Text.Length > 0 && w.Visible && w.Text.Length < 30)
                {
                    if (cand.Length > 0) cand.Append(", ");
                    cand.Append('"').Append(w.Text).Append("\" ").Append(w.Class);
                }
            }
            string list = cand.Length > 600 ? cand.ToString(0, 600) : cand.ToString();
            Log("Finish Selection: no Finish window among " + windows.Count + " child windows; candidates: " + (list.Length > 0 ? list : "none"));
            return false;
        }

        // ---- 2. UI Automation
        private static bool FinishByAutomation(IntPtr hwnd)
        {
            List<AutomationElement> found = FindFinishElements(hwnd);
            foreach (AutomationElement element in found)
            {
                try
                {
                    string name = element.Current.Name;
                    if (!element.Current.IsEnabled || element.Current.IsOffscreen) continue;
                    object pat;
                    if (element.TryGetCurrentPattern(InvokePattern.Pattern, out pat))
                    {
                        Log("Finish Selection: invoking \"" + name + "\" through UI Automation");
                        ((InvokePattern)pat).Invoke();
                        return true;
                    }
                    Log("Finish Selection: \"" + name + "\" has no Invoke pattern");
                }
                catch (Exception ex)
                {
                    Log("Finish Selection: UI Automation press failed: " + ex.Message);
                }
            }
            return false;
        }

        /// <summary>Every UI Automation element named Finish (any control type), logged with type, class and state.</summary>
        private static List<AutomationElement> FindFinishElements(IntPtr hwnd)
        {
            var list = new List<AutomationElement>();
            AutomationElement root = AutomationElement.FromHandle(hwnd);
            AutomationElementCollection all = root.FindAll(TreeScope.Descendants,
                new PropertyCondition(AutomationElement.NameProperty, "Finish", PropertyConditionFlags.IgnoreCase));
            for (int index = 0; index < all.Count; index++)
            {
                try
                {
                    AutomationElement e = all[index];
                    list.Add(e);
                    Log("Finish Selection: UIA candidate " + (index + 1) + "/" + all.Count + ": type " + e.Current.ControlType.ProgrammaticName +
                        ", class \"" + e.Current.ClassName + "\", id \"" + e.Current.AutomationId + "\", enabled " + e.Current.IsEnabled +
                        ", offscreen " + e.Current.IsOffscreen + ", rect " + e.Current.BoundingRectangle);
                }
                catch (Exception)
                {
                }
            }
            if (all.Count == 0) Log("Finish Selection: UI Automation found no element named Finish");
            return list;
        }

        // ---- 3. a real mouse click on the button, as the user would
        private static bool FinishByMouse(IntPtr hwnd)
        {
            foreach (AutomationElement e in FindFinishElements(hwnd))
            {
                try
                {
                    if (!e.Current.IsEnabled || e.Current.IsOffscreen) continue;
                    var r = e.Current.BoundingRectangle;
                    if (r.IsEmpty || r.Width < 2 || r.Height < 2) continue;
                    int x = (int)(r.Left + r.Width / 2), y = (int)(r.Top + r.Height / 2);
                    FocusRevit(hwnd);
                    Native.POINT old;
                    Native.GetCursorPos(out old);
                    Log("Finish Selection: clicking at " + x + "," + y);
                    Native.SetCursorPos(x, y);
                    Native.mouse_event(0x0002, 0, 0, 0, IntPtr.Zero);   // left down
                    Native.mouse_event(0x0004, 0, 0, 0, IntPtr.Zero);   // left up
                    Thread.Sleep(50);
                    Native.SetCursorPos(old.X, old.Y);
                    return true;
                }
                catch (Exception ex)
                {
                    Log("Finish Selection: mouse click failed: " + ex.Message);
                }
            }
            return false;
        }

        // ---- 3. Return to the active view
        /// <summary>Post Return to the active view, not the main frame.</summary>
        private static bool FinishByReturn(IntPtr hwnd)
        {
            IntPtr target = IntPtr.Zero;
            foreach (ChildWin w in ChildWindows(hwnd))
            {
                if (w.Class == "MDIClient")
                {
                    target = Native.SendMessage(w.Handle, Native.WM_MDIGETACTIVE, IntPtr.Zero, IntPtr.Zero);
                    break;
                }
            }
            if (target != IntPtr.Zero)
            {
                IntPtr inner = Native.GetWindow(target, Native.GW_CHILD);   // the view itself is the active frame's first child
                if (inner != IntPtr.Zero) target = inner;
            }
            if (target == IntPtr.Zero) target = hwnd;
            Log("Finish Selection: posting Return to window " + target.ToInt64());
            Native.PostMessage(target, Native.WM_KEYDOWN, new IntPtr(Native.VK_RETURN), new IntPtr(0x001C0001L));
            Native.PostMessage(target, Native.WM_KEYUP, new IntPtr(Native.VK_RETURN), new IntPtr(0xC01C0001L));
            return true;
        }

        /// <summary>
        /// True for the Options Bar's Finish button: "Finish" or "&amp;Finish". Not "Finish Edit Mode", "Finished" or
        /// anything else that merely starts the same way - pressing the wrong button would do something else.
        /// </summary>
        public static bool IsFinishLabel(string text)
        {
            if (string.IsNullOrEmpty(text)) return false;
            return text.Replace("&", "").Trim().ToLowerInvariant() == "finish";
        }

        /// <summary>
        /// Put Revit in the foreground with the keyboard actually attached to it. A bare SetForegroundWindow is
        /// refused by Windows when the calling thread does not own the foreground window; attaching the input queues
        /// first makes the call stick, and the attachment is undone straight away.
        /// </summary>
        public static void FocusRevit(IntPtr hwnd)
        {
            try
            {
                IntPtr foreground = Native.GetForegroundWindow();
                if (foreground == hwnd) return;
                uint thisThread = Native.GetWindowThreadProcessId(foreground, IntPtr.Zero);
                uint revitThread = Native.GetWindowThreadProcessId(hwnd, IntPtr.Zero);
                bool attached = false;
                if (thisThread != 0 && revitThread != 0 && thisThread != revitThread)
                    attached = Native.AttachThreadInput(thisThread, revitThread, true);
                try
                {
                    Native.SetForegroundWindow(hwnd);
                    Native.SetFocus(hwnd);
                }
                finally
                {
                    if (attached) Native.AttachThreadInput(thisThread, revitThread, false);
                }
            }
            catch (Exception)
            {
                Log("Finish Selection: could not set focus to the Revit window");
            }
        }

        // ================================================================ the debug lines
        /// <summary>Any thread: the line waits in a locked buffer until the Revit thread writes it to the job's log.</summary>
        private static void Log(string text)
        {
            try
            {
                lock (Gate) Pending.Add(text ?? "");
            }
            catch (Exception)
            {
            }
        }

        /// <summary>Revit thread: the waiting lines go to the log of the job that armed the card.</summary>
        private static void FlushLog()
        {
            try
            {
                string[] lines;
                lock (Gate)
                {
                    lines = Pending.ToArray();
                    Pending.Clear();
                }
                FhaDebugLog log = armedLog ?? FhaRevit.CurrentLog;
                if (log == null) return;
                foreach (string s in lines) log.Add(s);
            }
            catch (Exception)
            {
            }
        }

        // ================================================================ user32
        private static class Native
        {
            public const uint BM_CLICK = 0x00F5;
            public const uint WM_MDIGETACTIVE = 0x0229;
            public const uint WM_KEYDOWN = 0x0100;
            public const uint WM_KEYUP = 0x0101;
            public const uint GW_CHILD = 5;
            public const int VK_RETURN = 0x0D;

            public delegate bool EnumProc(IntPtr hwnd, IntPtr lParam);

            [StructLayout(LayoutKind.Sequential)]
            public struct POINT
            {
                public int X;
                public int Y;
            }

            [DllImport("user32.dll")]
            public static extern bool GetCursorPos(out POINT p);

            [DllImport("user32.dll")]
            public static extern bool SetCursorPos(int x, int y);

            [DllImport("user32.dll")]
            public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, IntPtr extra);

            [DllImport("user32.dll")]
            public static extern bool EnumChildWindows(IntPtr parent, EnumProc proc, IntPtr lParam);

            [DllImport("user32.dll", CharSet = CharSet.Unicode)]
            public static extern int GetClassName(IntPtr hWnd, StringBuilder text, int maxCount);

            [DllImport("user32.dll", CharSet = CharSet.Unicode)]
            public static extern int GetWindowTextLength(IntPtr hWnd);

            [DllImport("user32.dll", CharSet = CharSet.Unicode)]
            public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int maxCount);

            [DllImport("user32.dll")]
            public static extern bool IsWindowVisible(IntPtr hWnd);

            [DllImport("user32.dll")]
            public static extern bool IsWindowEnabled(IntPtr hWnd);

            [DllImport("user32.dll", CharSet = CharSet.Unicode)]
            public static extern IntPtr SendMessage(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);

            [DllImport("user32.dll", CharSet = CharSet.Unicode)]
            public static extern bool PostMessage(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);

            [DllImport("user32.dll")]
            public static extern IntPtr GetWindow(IntPtr hWnd, uint cmd);

            [DllImport("user32.dll")]
            public static extern IntPtr GetForegroundWindow();

            [DllImport("user32.dll")]
            public static extern uint GetWindowThreadProcessId(IntPtr hWnd, IntPtr processId);

            [DllImport("user32.dll")]
            public static extern bool AttachThreadInput(uint idAttach, uint idAttachTo, bool attach);

            [DllImport("user32.dll")]
            public static extern bool SetForegroundWindow(IntPtr hWnd);

            [DllImport("user32.dll")]
            public static extern IntPtr SetFocus(IntPtr hWnd);
        }
    }
}
