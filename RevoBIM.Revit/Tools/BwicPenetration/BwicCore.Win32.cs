using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Windows.Automation;
using Autodesk.Revit.UI;

namespace RevoBIM.Tools.BwicPenetration
{
    public static partial class BwicCore
    {
        /// <summary>The Revit session the window runs in; set by the window, used to find Revit's main window handle.</summary>
        public static UIApplication CurrentApp;

        private const int BM_CLICK = 0x00F5;
        private const int WM_MDIGETACTIVE = 0x0229;
        private const int WM_KEYDOWN = 0x0100, WM_KEYUP = 0x0101;
        private const int VK_RETURN = 0x0D;

        private delegate bool EnumChildProc(IntPtr hwnd, IntPtr lParam);

        [DllImport("user32.dll")] private static extern bool EnumChildWindows(IntPtr parent, EnumChildProc proc, IntPtr lParam);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetClassName(IntPtr hwnd, StringBuilder text, int max);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetWindowTextLength(IntPtr hwnd);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetWindowText(IntPtr hwnd, StringBuilder text, int max);
        [DllImport("user32.dll")] private static extern bool IsWindowVisible(IntPtr hwnd);
        [DllImport("user32.dll")] private static extern bool IsWindowEnabled(IntPtr hwnd);
        [DllImport("user32.dll")] private static extern IntPtr SendMessage(IntPtr hwnd, int msg, IntPtr wParam, IntPtr lParam);
        [DllImport("user32.dll")] private static extern bool PostMessage(IntPtr hwnd, int msg, IntPtr wParam, IntPtr lParam);
        [DllImport("user32.dll")] private static extern IntPtr GetForegroundWindow();
        [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr hwnd, IntPtr processId);
        [DllImport("user32.dll")] private static extern bool AttachThreadInput(uint idAttach, uint idAttachTo, bool attach);
        [DllImport("user32.dll")] private static extern bool SetForegroundWindow(IntPtr hwnd);
        [DllImport("user32.dll")] private static extern IntPtr SetFocus(IntPtr hwnd);
        [DllImport("user32.dll")] private static extern IntPtr GetWindow(IntPtr hwnd, uint cmd);

        private sealed class ChildWindow
        {
            public IntPtr Handle;
            public string Class, Text;
            public bool Visible, Enabled;
        }

        private static IntPtr RevitHandle()
        {
            try { return CurrentApp == null ? IntPtr.Zero : CurrentApp.MainWindowHandle; }
            catch (Exception) { return IntPtr.Zero; }
        }

        /// <summary>
        /// Finish the selection Revit is waiting on, as its Finish button would. There is no API call for the Options Bar's Finish
        /// button, so the button itself is pressed: as a Windows button among Revit's child windows (BM_CLICK), else through UI
        /// Automation (Invoke), else Return is posted to the active view's window. Runs on its own thread, after the click handler
        /// has returned. Only ever called while a step that ends with Finish is waiting.
        /// </summary>
        public static bool PressFinish()
        {
            IntPtr hwnd = RevitHandle();
            if (hwnd == IntPtr.Zero)
            {
                DebugLog("Finish Selection: no Revit window handle");
                return false;
            }
            FocusRevit();
            try
            {
                var worker = new Thread(() => PressFinishOnThread(hwnd)) { IsBackground = true };
                worker.Start();
                return true;
            }
            catch (Exception err)
            {
                DebugLog("Finish Selection could not start: " + err.Message);
                return false;
            }
        }

        private static void PressFinishOnThread(IntPtr hwnd)
        {
            // an exception escaping a .NET thread ends Revit: nothing may get out
            try
            {
                if (FinishByButton(hwnd)) return;
                if (FinishByAutomation(hwnd)) return;
                FinishByReturn(hwnd);
            }
            catch (Exception err)
            {
                try { DebugLog("Finish Selection failed: " + err.Message); }
                catch (Exception) { }
            }
        }

        private static List<ChildWindow> ChildWindows(IntPtr hwnd)
        {
            var found = new List<ChildWindow>();
            EnumChildProc visit = (child, l) =>
            {
                try
                {
                    var cls = new StringBuilder(128);
                    GetClassName(child, cls, 128);
                    int length = GetWindowTextLength(child);
                    var text = new StringBuilder(length + 1);
                    GetWindowText(child, text, length + 1);
                    found.Add(new ChildWindow { Handle = child, Class = cls.ToString(), Text = text.ToString(), Visible = IsWindowVisible(child), Enabled = IsWindowEnabled(child) });
                }
                catch (Exception) { }
                return true;
            };
            EnumChildWindows(hwnd, visit, IntPtr.Zero);
            GC.KeepAlive(visit);
            return found;
        }

        private static bool FinishByButton(IntPtr hwnd)
        {
            List<ChildWindow> windows = ChildWindows(hwnd);
            foreach (ChildWindow w in windows)
            {
                if (w.Visible && w.Enabled && PromptState.IsFinishLabel(w.Text))
                {
                    DebugLog("Finish Selection: pressing the Options Bar button \"" + w.Text + "\" (" + w.Class + ")");
                    SendMessage(w.Handle, BM_CLICK, IntPtr.Zero, IntPtr.Zero);
                    return true;
                }
            }
            var candidates = new List<string>();
            foreach (ChildWindow w in windows)
                if (w.Text.Length > 0 && w.Visible && w.Text.Length < 30) candidates.Add("\"" + w.Text + "\" " + w.Class);
            string list = string.Join(", ", candidates);
            DebugLog("Finish Selection: no Finish window among " + windows.Count + " child windows; candidates: "
                     + (list.Length == 0 ? "none" : list.Substring(0, Math.Min(600, list.Length))));
            return false;
        }

        private static bool FinishByAutomation(IntPtr hwnd)
        {
            AutomationElement root = AutomationElement.FromHandle(hwnd);
            AutomationElementCollection buttons = root.FindAll(TreeScope.Descendants,
                new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.Button));
            int count = 0;
            for (int i = 0; i < buttons.Count; i++)
            {
                AutomationElement element = buttons[i];
                try
                {
                    string name = element.Current.Name;
                    count++;
                    if (!PromptState.IsFinishLabel(name) || !element.Current.IsEnabled || element.Current.IsOffscreen) continue;
                    var pattern = (InvokePattern)element.GetCurrentPattern(InvokePattern.Pattern);
                    DebugLog("Finish Selection: invoking \"" + name + "\" through UI Automation");
                    pattern.Invoke();
                    return true;
                }
                catch (Exception) { }
            }
            DebugLog("Finish Selection: UI Automation found no Finish button among " + count + " buttons");
            return false;
        }

        /// <summary>Post Return to the active view, not the main frame.</summary>
        private static bool FinishByReturn(IntPtr hwnd)
        {
            IntPtr target = IntPtr.Zero;
            foreach (ChildWindow w in ChildWindows(hwnd))
            {
                if (w.Class == "MDIClient")
                {
                    target = SendMessage(w.Handle, WM_MDIGETACTIVE, IntPtr.Zero, IntPtr.Zero);
                    break;
                }
            }
            if (target != IntPtr.Zero)
            {
                IntPtr inner = GetWindow(target, 5);   // GW_CHILD
                if (inner != IntPtr.Zero) target = inner;
            }
            if (target == IntPtr.Zero) target = hwnd;
            DebugLog("Finish Selection: posting Return to window " + target);
            PostMessage(target, WM_KEYDOWN, (IntPtr)VK_RETURN, (IntPtr)0x001C0001);
            PostMessage(target, WM_KEYUP, (IntPtr)VK_RETURN, unchecked((IntPtr)(int)0xC01C0001));
            return true;
        }

        /// <summary>Put Revit in the foreground with the keyboard attached to it (attach the input queues first, then undo it).</summary>
        public static void FocusRevit()
        {
            try
            {
                IntPtr hwnd = RevitHandle();
                if (hwnd == IntPtr.Zero) return;
                IntPtr foreground = GetForegroundWindow();
                if (foreground == hwnd) return;
                uint thisThread = GetWindowThreadProcessId(foreground, IntPtr.Zero);
                uint revitThread = GetWindowThreadProcessId(hwnd, IntPtr.Zero);
                bool attached = false;
                if (thisThread != 0 && revitThread != 0 && thisThread != revitThread)
                    attached = AttachThreadInput(thisThread, revitThread, true);
                try
                {
                    SetForegroundWindow(hwnd);
                    SetFocus(hwnd);
                }
                finally
                {
                    if (attached) AttachThreadInput(thisThread, revitThread, false);
                }
            }
            catch (Exception)
            {
            }
        }
    }
}
