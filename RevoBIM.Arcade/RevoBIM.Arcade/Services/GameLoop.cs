using System;
using System.Diagnostics;
using System.Windows.Media;

namespace RevoBIM.Arcade.Services
{
    /// <summary>
    /// The shared game-loop timer, driven by the display's own frame callback. Games get
    /// the seconds since the last frame, clamped so a stall never flings anything across
    /// the board. Paused means no ticks, and the clock does not run on.
    /// </summary>
    public sealed class GameLoop
    {
        public const double MaxFrameSeconds = 0.25;

        readonly Stopwatch _clock = new Stopwatch();
        TimeSpan _lastRender = TimeSpan.MinValue;
        bool _hooked;

        public bool Running { get; private set; }
        public bool Paused { get; private set; }

        /// <summary>Called every frame with the elapsed seconds.</summary>
        public event Action<double>? Tick;

        public void Start()
        {
            if (Running) return;
            Running = true;
            _clock.Restart();
            _lastRender = TimeSpan.MinValue;
            if (!_hooked) { CompositionTarget.Rendering += OnRendering; _hooked = true; }
        }

        public void Stop()
        {
            Running = false;
            Paused = false;
            if (_hooked) { CompositionTarget.Rendering -= OnRendering; _hooked = false; }
            _clock.Stop();
        }

        public void SetPaused(bool paused)
        {
            Paused = paused;
            _lastRender = TimeSpan.MinValue;   // no catch-up jump on resume
        }

        public void TogglePause() => SetPaused(!Paused);

        void OnRendering(object? sender, EventArgs e)
        {
            if (!Running) return;
            var now = _clock.Elapsed;
            if (_lastRender == TimeSpan.MinValue) { _lastRender = now; return; }
            var dt = (now - _lastRender).TotalSeconds;
            _lastRender = now;
            if (Paused) return;
            Tick?.Invoke(Math.Min(dt, MaxFrameSeconds));
        }
    }
}
