using System;
using System.Collections.Generic;
using System.Linq;

namespace RevoBIM.Tools.BwicPenetration
{
    /// <summary>What the step prompt shows: kind, accent, eyebrow, title, detail, how the step ends, step number and timeout.</summary>
    public sealed class PromptLook
    {
        public string Kind, Accent, Eyebrow, Title, Detail, Ends;
        public int Number, Total;
        public double? Seconds;
    }

    /// <summary>An instruction to the window: "show" a look or "hide".</summary>
    public sealed class PromptAction
    {
        public string Action;
        public PromptLook Look;
        public PromptAction(string action, PromptLook look) { Action = action; Look = look; }
    }

    /// <summary>
    /// What the step prompt should show, and for how long (port of bwic_prompt.py). The run does not wait for the prompt, so the
    /// next step is held back until a "placed" flash has run its time. Every method returns what the window should now do, or null.
    /// </summary>
    public sealed class PromptState
    {
        public bool Visible, Flashing, Closing;
        public PromptLook Pending, Current;

        public static readonly Dictionary<string, double> FlashSeconds = new Dictionary<string, double>
        {
            { "placed", 2.0 }, { "problem", 3.0 }, { "note", 3.5 }, { "blocked", 6.0 },
        };

        // kind -> (accent, eyebrow)
        private static readonly Dictionary<string, string[]> Looks = new Dictionary<string, string[]>
        {
            { "step", new[] { "blue", null } },
            { "placed", new[] { "green", "DONE" } },
            { "problem", new[] { "orange", "NOT PLACED" } },
            { "note", new[] { "blue", "BWIC PENETRATION" } },
            { "blocked", new[] { "orange", "NOT STARTED" } },
        };

        public PromptAction Step(Dictionary<string, object> details)
        {
            PromptLook look = StepLook(details);
            if (Flashing)
            {
                Pending = look;
                Closing = false;
                return null;
            }
            return Show(look);
        }

        public PromptAction Flash(string kind, Dictionary<string, object> details)
        {
            PromptLook look = FlashLook(kind, details);
            Flashing = true;
            Pending = null;
            Closing = false;
            return Show(look);
        }

        public PromptAction Done()
        {
            Pending = null;
            if (Flashing)
            {
                Closing = true;
                return null;
            }
            return Hide();
        }

        public PromptAction FlashOver()
        {
            if (!Flashing) return null;
            Flashing = false;
            if (Pending != null)
            {
                PromptLook look = Pending;
                Pending = null;
                return Show(look);
            }
            Closing = false;
            return Hide();
        }

        public PromptAction Reset()
        {
            Visible = Flashing = Closing = false;
            Pending = Current = null;
            return new PromptAction("hide", null);
        }

        private PromptAction Show(PromptLook look)
        {
            Visible = true;
            Current = look;
            return new PromptAction("show", look);
        }

        private PromptAction Hide()
        {
            bool was = Visible;
            Visible = false;
            Current = null;
            return was ? new PromptAction("hide", null) : null;
        }

        /// <summary>Whether the tool's Finish Selection button may press Return now: only at a step that ends with Finish.</summary>
        public static bool FinishArmed(string evt, Dictionary<string, object> details, bool armed)
        {
            if (evt == "step") return Text(details, "ends") == "finish";
            if (evt == "placed" || evt == "problem" || evt == "done") return false;
            return armed;
        }

        /// <summary>True for the Options Bar's Finish button: "Finish" or "&amp;Finish", nothing that merely starts the same.</summary>
        public static bool IsFinishLabel(string text)
        {
            if (string.IsNullOrEmpty(text)) return false;
            return text.Replace("&", "").Trim().ToLowerInvariant() == "finish";
        }

        public static string Text(Dictionary<string, object> details, string key)
        {
            object v;
            if (details != null && details.TryGetValue(key, out v) && v != null) return Convert.ToString(v);
            return "";
        }

        private static int Int(Dictionary<string, object> details, string key, int fallback)
        {
            object v;
            if (details != null && details.TryGetValue(key, out v) && v != null)
            {
                int n;
                if (int.TryParse(Convert.ToString(v), out n) && n != 0) return n;
            }
            return fallback;
        }

        public static PromptLook StepLook(Dictionary<string, object> details)
        {
            int number = Int(details, "number", 1), total = Int(details, "total", 1);
            string ends = Text(details, "ends");
            return new PromptLook
            {
                Kind = "step", Accent = Looks["step"][0], Eyebrow = "STEP " + number + " OF " + total,
                Title = Text(details, "title"), Detail = Text(details, "detail"), Ends = ends.Length > 0 ? ends : "click",
                Number = number, Total = total, Seconds = null,
            };
        }

        public static PromptLook FlashLook(string kind, Dictionary<string, object> details)
        {
            string[] look = Looks[kind];
            return new PromptLook
            {
                Kind = kind, Accent = look[0], Eyebrow = look[1], Title = Text(details, "title"), Detail = Text(details, "detail"),
                Ends = null, Number = 0, Total = 0, Seconds = FlashSeconds[kind],
            };
        }

        /// <summary>The line along the bottom: how this step is answered.</summary>
        public static string HintText(PromptLook look)
        {
            if (look == null || look.Kind != "step") return "";
            if (look.Ends == "finish") return "Finish Selection  ·  Options Bar Finish  ·  Return     ·     Esc to stop";
            return "Single click     ·     Esc to stop";
        }

        /// <summary>Progress through the steps, as filled and open dots.</summary>
        public static string Dots(PromptLook look)
        {
            if (look == null || look.Total == 0) return "";
            return string.Join(" ", Enumerable.Range(0, look.Total).Select(i => i < look.Number ? "●" : "○"));
        }
    }
}
