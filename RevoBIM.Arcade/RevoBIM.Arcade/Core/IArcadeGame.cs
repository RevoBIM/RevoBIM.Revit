namespace RevoBIM.Arcade.Core
{
    /// <summary>
    /// The contract every game implements. A game lives in its own folder under Games\
    /// and is registered with one line in GameRegistry. Games draw on host.Surface, read
    /// input from host.Input, tick from host.Loop and use host.Brush(...) for colours, so
    /// they follow the theme without knowing which one is active.
    /// </summary>
    public interface IArcadeGame
    {
        /// <summary>Lower-case id used on the command line, e.g. "pacman". Letters, digits, '-'.</summary>
        string Key { get; }

        string DisplayName { get; }

        /// <summary>Footer hint, e.g. "Arrows move   P pause   R restart   Esc menu".</summary>
        string Hints => string.Empty;

        /// <summary>
        /// The picker icon: SVG path data drawn in a 24 x 24 box, filled with the theme accent.
        /// Empty means a plain square.
        /// </summary>
        string Icon => string.Empty;

        /// <summary>Build the board and start the loop. Called on the UI thread.</summary>
        void Start(GameHost host);

        /// <summary>Called when the game is left (menu, restart, window closing). Save scores here.</summary>
        void Stop();
    }
}
