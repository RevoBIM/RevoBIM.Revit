using System;
using System.Runtime.InteropServices;
using System.Windows;
using RevoBIM.Arcade.Core;
using RevoBIM.Arcade.Services;
using RevoBIM.Arcade.UI;

namespace RevoBIM.Arcade
{
    public partial class App : Application
    {
        [DllImport("kernel32.dll")] static extern bool AttachConsole(int processId);

        SingleInstance? _single;

        protected override void OnStartup(StartupEventArgs e)
        {
            base.OnStartup(e);
            var options = LaunchOptions.Parse(e.Args);

            if (options.SelfTest)
            {
                AttachConsole(-1);                       // so a plain console shows the report too
                int code = SelfTest.Run(options, Console.Out);
                Shutdown(code);
                return;
            }

            _single = SingleInstance.Acquire();
            if (!_single.IsFirst)
            {
                // Already running: hand the request over and leave.
                SingleInstance.SendToRunning(options.GameKey);
                _single.Dispose();
                Shutdown(0);
                return;
            }

            ThemeService.Apply(options.Theme);

            var shell = new ShellWindow(options);
            MainWindow = shell;
            shell.Show();

            _single.Listen(key => Dispatcher.BeginInvoke(new Action(() => shell.HandleExternalRequest(key))));
        }

        protected override void OnExit(ExitEventArgs e)
        {
            _single?.Dispose();
            base.OnExit(e);
        }
    }
}
