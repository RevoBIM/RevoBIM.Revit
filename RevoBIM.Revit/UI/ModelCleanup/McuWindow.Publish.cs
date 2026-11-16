using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;
using RevoBIM.Tools.ModelCleanup;
using static RevoBIM.Tools.ModelCleanup.McuCore;

namespace RevoBIM.UI.ModelCleanup
{
    /// <summary>Publish to ACC (after step 1). Port of the publish half of mcu_window.py.</summary>
    public sealed partial class McuWindow
    {
        private string ClientId() { return settings.Get("aps_client_id").Trim(); }

        private int Port() { return AsInt(settings.Get("aps_port"), McuAps.DefaultPort, 1024, 65535); }

        private void OfferPublishAfterSync()
        {
            if (McuAps.CanPublish(info, synced) != null) return;
            if (!AsBool(template.Get("offer_publish"), true)) return;
            if (ClientId().Length == 0)
            {
                Say("Publish to ACC is ready to use once an APS app is set up (Export Settings > Publish to ACC).");
                return;
            }
            bool? choice = AskLinks(true);
            if (choice != null) RunPublish(choice.Value);
        }

        /// <summary>True with links, False without, null to leave it.</summary>
        private bool? AskLinks(bool offer = false)
        {
            string fixedChoice = McuAps.NormaliseLinks(template.Get("publish_links"));
            string intro = offer ? "The model is synced. Publish the latest version on ACC now?\n\n"
                                 : "Publish the latest synced version on ACC.\n\n";
            object answer;
            if (fixedChoice == McuAps.LinksWith)
            {
                answer = Choose("Publish to ACC", intro + "The template publishes with links.",
                                new McuButton("Not now", null, "BaseButton"), new McuButton("Publish with links", true, "GreenButton"));
            }
            else if (fixedChoice == McuAps.LinksWithout)
            {
                answer = Choose("Publish to ACC", intro + "The template publishes without links.",
                                new McuButton("Not now", null, "BaseButton"), new McuButton("Publish without links", false, "GreenButton"));
            }
            else
            {
                answer = Choose("Publish to ACC",
                    intro + "With links, ACC publishes the model together with the Revit links it carries. Without links is " +
                            "quicker and publishes this model on its own.",
                    new McuButton("Not now", null, "BaseButton"), new McuButton("Publish without links", false, "OrangeButton"),
                    new McuButton("Publish with links", true, "GreenButton"));
            }
            return answer as bool?;
        }

        private void OnPublish(object sender, RoutedEventArgs args)
        {
            string reason = McuAps.CanPublish(info, synced);
            if (reason != null)
            {
                Tell("Publish to ACC", reason);
                return;
            }
            if (ClientId().Length == 0)
            {
                object answer = Choose("Publish to ACC", McuAps.SetupHelpFor(Port()),
                                       new McuButton("Close", false, "BaseButton"), new McuButton("Open Export Settings", true, "OrangeButton"));
                if (answer as bool? == true) OpenSettings();
                return;
            }
            bool? choice = AskLinks();
            if (choice != null) RunPublish(choice.Value);
        }

        private void Tick()
        {
            McuUi.Pump(Window);
            if (cancelRequested) throw new PublishCancelled();
        }

        private void RunPublish(bool withLinks)
        {
            string label = withLinks ? "with links" : "without links";
            cancelRequested = false;
            BeginBusy("Publishing to ACC " + label);
            string project, item;
            int code;
            try
            {
                progress.Update(0.05, "Signing in to Autodesk (a browser opens the first time - press Escape to cancel)");
                string token = McuWeb.GetToken(ClientId(), Port(), Tick);
                McuUi.BringToFront(Window);
                progress.Update(0.35, "Finding this model on ACC");
                (project, item) = McuWeb.ResolveItem(doc, token);
                progress.Update(0.55, "Checking whether a publish is already running");
                var (state, status) = McuWeb.JobState(token, project, item);
                if (state == McuAps.JobRunning)
                {
                    Say("ACC is already publishing this model (" + status + ").");
                    EndBusy("ACC is already publishing this model", "warn");
                    StartPublishPoll(project, item);
                    return;
                }
                progress.Update(0.75, "Asking ACC to publish " + label);
                var (sent, httpCode) = McuWeb.Publish(token, project, item, withLinks);
                code = httpCode;
                if (!sent && httpCode == 401)
                {
                    McuWeb.Forget();
                    progress.Update(0.8, "Sign-in expired - signing in again");
                    token = McuWeb.GetToken(ClientId(), Port(), Tick);
                    (sent, httpCode) = McuWeb.Publish(token, project, item, withLinks);
                    code = httpCode;
                    if (!sent) throw new McuWeb.PublishError(McuAps.ExplainStatus(401, ""));
                }
            }
            catch (PublishCancelled)
            {
                Say("Publish cancelled.");
                EndBusy("Publish cancelled", "warn");
                return;
            }
            catch (McuWeb.PublishError error)
            {
                string message = error.Message;
                DebugStep("Publish failed", new System.Collections.Generic.List<(string, object)> { ("links", label), ("message", message) });
                Say("Publish failed: " + message.Split('\n')[0]);
                EndBusy("Publish to ACC failed", "fail");
                Tell("Publish to ACC", message);
                return;
            }
            catch (Exception)
            {
                EndBusy("Publish to ACC failed", "fail");
                throw;
            }
            Say("ACC accepted the publish request (" + label + ", HTTP " + code + ").");
            DebugStep("Publish", new System.Collections.Generic.List<(string, object)>
                { ("links", label), ("http", code), ("project", project), ("item", item) });
            EndBusy("Publish requested on ACC " + label);
            StartPublishPoll(project, item);
        }

        private void StartPublishPoll(string project, string item)
        {
            StopPublishPoll();
            publishTarget = (project, item);
            publishStarted = DateTime.Now;
            find.Text("PublishStatusText").Text = "Waiting for ACC...";
            var timer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(10) };
            timer.Tick += McuUi.SafeTick(Window, OnPublishPoll, theme, "publish status");
            publishTimer = timer;
            timer.Start();
        }

        private void StopPublishPoll()
        {
            if (publishTimer != null)
            {
                try { publishTimer.Stop(); } catch (Exception) { }
            }
            publishTimer = null;
        }

        /// <summary>ACC publishes in the cloud and reports no percentage, only a status. The window stays usable while this checks every 10 s.</summary>
        private void OnPublishPoll()
        {
            if (busy || publishTarget == null) return;
            double elapsed = (DateTime.Now - publishStarted).TotalSeconds;
            TextBlock block = find.Text("PublishStatusText");
            string state, status;
            try
            {
                string token = McuWeb.GetToken(ClientId(), Port(), Tick, false);
                if (token == null)
                {
                    block.Text = "Sign-in expired - check the publish on ACC.";
                    StopPublishPoll();
                    return;
                }
                (state, status) = McuWeb.JobState(token, publishTarget.Value.Project, publishTarget.Value.Item);
            }
            catch (Exception error)
            {
                // a dropped connection must stop the timer, not stack a dialog every ten seconds
                StopPublishPoll();
                block.Text = "Stopped watching the publish: " + error.Message.Split('\n')[0];
                block.SetResourceReference(TextBlock.ForegroundProperty, "OrangeBrush");
                Say("Publish status check failed: " + error.Message);
                return;
            }
            block.Text = McuAps.JobLine(state, status, FormatClock(elapsed));
            string brush = state == McuAps.JobDone ? "GreenBrush" : state == McuAps.JobFailed ? "RedBrush" : "OrangeBrush";
            block.SetResourceReference(TextBlock.ForegroundProperty, brush);
            if (McuAps.PollShouldStop(state, elapsed))
            {
                StopPublishPoll();
                if (state == McuAps.JobDone) Say("ACC finished publishing after " + FormatDuration(elapsed) + ".");
                else if (state == McuAps.JobFailed) Say("ACC reports the publish failed - check the model on ACC.");
                else Say("Stopped watching the publish after 15 minutes; ACC is still working on it.");
            }
        }
    }
}
