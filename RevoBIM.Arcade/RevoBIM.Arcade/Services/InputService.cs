using System;
using System.Collections.Generic;
using System.Windows.Input;

namespace RevoBIM.Arcade.Services
{
    /// <summary>
    /// Keyboard state for games. The shell feeds it; games poll IsDown or listen for Pressed.
    /// P (pause), R (restart), Esc (back to the menu) and F-keys belong to the shell and are
    /// never delivered here.
    /// </summary>
    public sealed class InputService
    {
        readonly HashSet<Key> _down = new HashSet<Key>();

        public event Action<Key>? Pressed;

        public bool IsDown(Key key) => _down.Contains(key);

        public bool Left => IsDown(Key.Left) || IsDown(Key.A);
        public bool Right => IsDown(Key.Right) || IsDown(Key.D);
        public bool Up => IsDown(Key.Up) || IsDown(Key.W);
        public bool Down => IsDown(Key.Down) || IsDown(Key.S);

        internal void KeyDown(Key key, bool isRepeat)
        {
            if (_down.Add(key) && !isRepeat) Pressed?.Invoke(key);
        }

        internal void KeyUp(Key key) => _down.Remove(key);

        internal void Reset() => _down.Clear();
    }
}
