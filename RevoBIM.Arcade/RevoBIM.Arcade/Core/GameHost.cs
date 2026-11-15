using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Shapes;
using RevoBIM.Arcade.Services;

namespace RevoBIM.Arcade.Core
{
    /// <summary>
    /// Everything a game is given. Games use these shared services and never keep their own
    /// copies of a loop, input handling, score storage or theme lookup.
    /// </summary>
    public sealed class GameHost
    {
        public GameHost(string gameKey, string theme, Canvas surface)
        {
            Theme = theme;
            Surface = surface;
            Scores = new ScoreStore(gameKey);
            Loop = new GameLoop();
            Input = new InputService();
        }

        /// <summary>"dark" or "light". Colours should come from brush keys, not from this.</summary>
        public string Theme { get; }

        /// <summary>The board. Its size is BoardWidth x BoardHeight; the shell scales it to the window.</summary>
        public Canvas Surface { get; }

        public GameLoop Loop { get; }
        public InputService Input { get; }
        public ScoreStore Scores { get; }

        public double BoardWidth { get; private set; } = 640;
        public double BoardHeight { get; private set; } = 400;

        public event Action<string>? StatusChanged;

        public void SetBoardSize(double width, double height)
        {
            BoardWidth = width; BoardHeight = height;
            Surface.Width = width; Surface.Height = height;
        }

        /// <summary>The footer's left-hand line, e.g. "Score 120".</summary>
        public void SetStatus(string text) => StatusChanged?.Invoke(text);

        /// <summary>Bind a shape's fill to a theme brush key (HeroBrush, BlueBrush, ...), so it follows the theme.</summary>
        public void Fill(Shape shape, string brushKey) => shape.SetResourceReference(Shape.FillProperty, brushKey);

        public void Stroke(Shape shape, string brushKey) => shape.SetResourceReference(Shape.StrokeProperty, brushKey);

        public void Text(TextBlock block, string brushKey) => block.SetResourceReference(TextBlock.ForegroundProperty, brushKey);

        /// <summary>Stop the loop and drop every handler. The shell calls this after IArcadeGame.Stop.</summary>
        internal void Shutdown()
        {
            Loop.Stop();
            Input.Reset();
            Surface.Children.Clear();
        }
    }
}
