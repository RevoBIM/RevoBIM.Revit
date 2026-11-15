# -*- coding: utf-8 -*-
u"""RevoBIM Addin Manager - the favourites grid.

A second view of the panel, behind the yellow star in the header. Favourites
are laid out like apps on a phone: a uniform grid filled from the top left
across and then down, each tile the addin's own icon - a size up from the
list's - on a small raised card with a soft shadow, its name in small text
underneath (switchable). The search box goes away in this view to give the
grid the room.

**Pick a tile up to move it.** Hold it still for a moment, or start dragging,
and it lifts: it grows a little with a small overshoot and its shadow deepens,
so it is plainly off the grid. It then follows the cursor freely. As it
passes over the others they slide out of its way - they are not just
rearranged, they glide to their new places - and letting go settles it into
its slot. A press let go before it lifts is a click and runs the addin. The
order is the settings list itself, so it is remembered, and a new favourite
always goes on the end - the next free spot in reading order.

Adding a favourite from the list takes you straight to the grid, and the new
tile pops in so you can see where it went.

How it is built, because each choice is load bearing:

* The mouse is captured on the **grid**, never on a tile. The lifted tile is
  removed and reinserted as it moves, and an element taken out of the tree
  while it holds the capture loses it mid-drag.
* Tiles move within the WrapPanel's own Children rather than the grid being
  re-rendered, so nothing is rebuilt under the cursor.
* Every movement is a **render transform** (scale and translate), eased by
  `rba_tween` from the render loop. Slots are measured with
  `LayoutInformation.GetLayoutSlot`, which ignores render transforms - read
  through TranslatePoint instead, a sliding tile would report where it is
  drawn rather than where it belongs, and the drop slot would wander.
* Which slot the pointer is over is `rba_core.drop_index` - pure, benched.
"""

import rba_clr  # noqa: F401

from System import Double, Object
from System.Windows import (Thickness, CornerRadius, HorizontalAlignment,
                            VerticalAlignment, TextAlignment, TextTrimming,
                            TextWrapping, Point, Visibility)
from System import TimeSpan
from System.Windows.Controls import (Border, StackPanel, TextBlock, Image, ToolTip,
                                     ContextMenu, MenuItem, Panel)
from System.Windows.Controls.Primitives import LayoutInformation
from System.Windows.Input import Cursors, Mouse, MouseButtonState
from System.Windows.Media import (FontFamily, Stretch, ScaleTransform,
                                  TranslateTransform, TransformGroup)
from System.Windows.Media.Effects import DropShadowEffect
from System.Windows.Threading import DispatcherTimer

import rba_core
import rba_menu
import rba_theme
import rba_tween
import rba_ui

from rba_core import to_text, log, log_exception

TILE_PAD = 26          # a tile is its icon plus this, so names have room
TILE_MIN = 66
CARD_PAD = 6           # the card around the icon

# the shadow at rest and lifted: (blur, depth, opacity dark, opacity light)
SHADOW_REST = (7.0, 1.5, 0.45, 0.30)
SHADOW_LIFT = (18.0, 7.0, 0.60, 0.42)
LIFT_SCALE = 1.14
LIFT_S = 0.17          # seconds: the lift
SLIDE_S = 0.18         # the others getting out of the way
DROP_S = 0.20          # settling into the slot
POP_S = 0.34           # a new favourite arriving


class FavGrid(object):

    def __init__(self, pane, panel):
        self.pane = pane
        self.panel = panel
        self.press = None          # {item, key, tile, start, grab} while held
        self.lifted = False
        self.fx = {}               # key -> {scale, move, shadow}
        self.tweens = rba_tween.Tweens()
        self.driver = rba_tween.FrameDriver(self.tweens)
        self.hold = DispatcherTimer()
        self.hold.Interval = TimeSpan.FromMilliseconds(rba_core.FAV_HOLD_MS)
        self.hold.Tick += self.on_hold
        panel.PreviewMouseMove += self.on_move
        panel.PreviewMouseLeftButtonUp += self.on_up
        panel.MouseRightButtonUp += self.on_panel_context
        panel.LostMouseCapture += self.on_lost_capture

    # ------------------------------------------------------------ state

    def keys(self):
        return rba_core.as_list(self.pane.settings, u"favourites")

    def labels_shown(self):
        return rba_core.as_bool(self.pane.settings, u"fav_labels")

    def is_favourite(self, item):
        return item.key in self.keys()

    def toggle(self, item):
        keys = self.keys()
        if item.key in keys:
            keys = rba_core.fav_remove(keys, item.key)
            note = u"{0} taken out of favourites".format(item.title)
        else:
            keys = rba_core.fav_add(keys, item.key)
            note = u"{0} added to favourites".format(item.title)
        rba_core.set_list(self.pane.settings, u"favourites", keys)
        added = item.key in keys
        if added:
            # Straight to the grid, so the new favourite can be seen.
            self.pane.settings[u"view"] = u"favourites"
        self.pane.save_settings()
        self.pane.render()
        self.pane.set_status(note)
        if added:
            self.pop(item.key)

    def toggle_labels(self):
        self.pane.settings[u"fav_labels"] = u"0" if self.labels_shown() else u"1"
        self.pane.save_settings()
        self.pane.render()

    # ------------------------------------------------------------ render

    def render(self):
        u"""Rebuild the grid. Returns how many tiles it drew."""
        panel = self.panel
        # Anything mid-flight lands at once: its tiles are about to go.
        self.tweens.finish_all()
        self.cancel_press()
        panel.Children.Clear()
        self.fx = {}
        pane = self.pane
        by_key = {}
        for item in pane.items:
            by_key[item.key] = item
        hide = rba_core.as_bool(pane.settings, u"hide_unloaded")
        items = []
        for key in self.keys():
            item = by_key.get(key)
            # A favourite whose folder has gone is kept in the list, not
            # shown: put the folder back and it returns to its old spot.
            if item is None or (hide and not item.live):
                continue
            items.append(item)

        icon = rba_core.fav_icon_size(pane.icon_size())
        width = max(TILE_MIN, icon + CARD_PAD * 2 + TILE_PAD)
        panel.ItemWidth = width
        if not items:
            panel.ItemWidth = Double.NaN
            panel.Children.Add(self._empty_note())
            return 0
        for item in items:
            panel.Children.Add(self._tile(item, icon, width))
        return len(items)

    def _empty_note(self):
        note = TextBlock()
        note.Text = (u"No favourites yet.\n\nRight click any addin in the list "
                     u"and choose Add to favourites. They fill in here from "
                     u"the top left, and can be dragged into any order.")
        note.TextWrapping = TextWrapping.Wrap
        note.Foreground = self.pane.res(u"FgMuted")
        note.FontFamily = FontFamily(u"Segoe UI")
        note.FontSize = 12
        note.Margin = Thickness(4, 6, 4, 6)
        note.MaxWidth = 300
        return note

    def _tile(self, item, icon, width):
        pane = self.pane
        tile = Border()
        tile.Tag = item.key
        tile.Width = width
        tile.Padding = Thickness(2, 4, 2, 4)
        tile.Margin = Thickness(0, 0, 0, 2)
        tile.CornerRadius = CornerRadius(6)
        tile.Background = pane.res(u"BgWindow")
        tile.Cursor = Cursors.Hand

        # Every movement is a render transform: scaled about the middle, and
        # moved without the grid laying anything out.
        scale = ScaleTransform(1.0, 1.0)
        move = TranslateTransform(0.0, 0.0)
        group = TransformGroup()
        group.Children.Add(scale)
        group.Children.Add(move)
        tile.RenderTransform = group
        tile.RenderTransformOrigin = Point(0.5, 0.5)

        stack = StackPanel()
        stack.HorizontalAlignment = HorizontalAlignment.Center

        # the raised card the icon sits on: a small soft shadow so it reads
        # as something to press
        card = Border()
        card.Background = pane.res(u"BgCard")
        card.CornerRadius = CornerRadius(7)
        card.Padding = Thickness(CARD_PAD)
        card.HorizontalAlignment = HorizontalAlignment.Center
        card.Margin = Thickness(0, 0, 0, 4)
        shadow = None
        try:
            shadow = DropShadowEffect()
            shadow.Color = pane.res(u"ShadowColor")
            shadow.Direction = 270
            self._set_shadow(shadow, 0.0)
            card.Effect = shadow
        except Exception:
            shadow = None
            log_exception(u"fav/shadow")
        self.fx[item.key] = {u"scale": scale, u"move": move, u"shadow": shadow}

        icon_path = item.icon
        if pane.theme_name == u"dark" and item.icon_dark:
            icon_path = item.icon_dark
        source = rba_ui.load_image(icon_path, icon)
        if source is not None:
            picture = Image()
            picture.Source = source
            picture.Width = icon
            picture.Height = icon
            picture.Stretch = Stretch.Uniform
            visual = picture
        else:
            visual = rba_ui.initial_glyph(item.title, icon,
                                          pane.res(u"BgField"), pane.res(u"FgMuted"))
        if not item.live:
            visual.Opacity = 0.45
        card.Child = visual
        stack.Children.Add(card)

        if self.labels_shown():
            name = TextBlock()
            name.Text = item.title
            name.FontFamily = FontFamily(u"Segoe UI")
            name.FontSize = 10.5
            name.Foreground = pane.res(u"FgText" if item.live else u"FgMuted")
            name.TextAlignment = TextAlignment.Center
            name.TextWrapping = TextWrapping.Wrap
            name.TextTrimming = TextTrimming.CharacterEllipsis
            name.MaxHeight = 30          # two lines, then an ellipsis
            name.MaxWidth = width - 4
            name.HorizontalAlignment = HorizontalAlignment.Center
            stack.Children.Add(name)

        tile.Child = stack

        tip = ToolTip()
        lines = [item.title]
        if not item.live:
            lines.append(u"Not loaded - reload pyRevit")
        elif item.tooltip:
            lines.append(item.tooltip)
        tip.Content = u"\n".join(lines)
        tile.ToolTip = tip

        hover = pane.res(u"BgHover")
        rest = pane.res(u"BgWindow")

        def on_enter(sender, args):
            if not self.lifted:
                sender.Background = hover

        def on_leave(sender, args):
            if not self.lifted:
                sender.Background = rest

        def on_down(sender, args, entry=item):
            if self.lifted:
                return
            try:
                self.press = {u"item": entry, u"key": entry.key, u"tile": sender,
                              u"start": args.GetPosition(self.panel),
                              u"grab": args.GetPosition(sender)}
                self.hold.Stop()
                self.hold.Start()
            except Exception:
                self.press = None

        def on_context(sender, args, entry=item):
            try:
                menu = rba_menu.build(self.pane, entry)
                menu.PlacementTarget = sender
                menu.IsOpen = True
                args.Handled = True
            except Exception:
                log_exception(u"fav/context")

        tile.MouseEnter += on_enter
        tile.MouseLeave += on_leave
        tile.PreviewMouseLeftButtonDown += on_down
        tile.MouseRightButtonUp += on_context
        return tile

    # ------------------------------------------------------------ effects

    def _set_shadow(self, shadow, lift):
        u"""Shadow between rest (lift 0) and lifted (lift 1)."""
        if shadow is None:
            return
        dark = self.pane.theme_name == u"dark"
        rest_blur, rest_depth, rest_dark, rest_light = SHADOW_REST
        up_blur, up_depth, up_dark, up_light = SHADOW_LIFT
        rest_opacity = rest_dark if dark else rest_light
        up_opacity = up_dark if dark else up_light
        shadow.BlurRadius = rest_blur + (up_blur - rest_blur) * lift
        shadow.ShadowDepth = rest_depth + (up_depth - rest_depth) * lift
        shadow.Opacity = rest_opacity + (up_opacity - rest_opacity) * lift

    def _scale_to(self, key, end, seconds, ease, done=None):
        fx = self.fx.get(key)
        if fx is None:
            return
        scale = fx[u"scale"]

        def apply(value):
            scale.ScaleX = value
            scale.ScaleY = value

        self.tweens.add(key + u"#scale", scale.ScaleX, end, seconds, apply, ease, done)

    def _lift_to(self, key, end, seconds):
        fx = self.fx.get(key)
        if fx is None or fx[u"shadow"] is None:
            return
        shadow = fx[u"shadow"]
        state = {u"value": 0.0 if end else 1.0}
        existing = self.tweens.active.get(key + u"#lift")
        if existing is not None:
            state[u"value"] = existing[u"value"]

        def apply(value):
            self._set_shadow(shadow, value)

        self.tweens.add(key + u"#lift", state[u"value"], end, seconds, apply)

    def _slide_home(self, key, seconds, ease=None, done=None):
        u"""Glide a tile's offset back to nothing - into its own slot."""
        fx = self.fx.get(key)
        if fx is None:
            return
        move = fx[u"move"]

        def apply_x(value):
            move.X = value

        def apply_y(value):
            move.Y = value

        self.tweens.add(key + u"#x", move.X, 0.0, seconds, apply_x, ease)
        self.tweens.add(key + u"#y", move.Y, 0.0, seconds, apply_y, ease, done)

    def pop(self, key):
        u"""A new favourite arrives: scrolled to, then popped in."""
        fx = self.fx.get(key)
        if fx is None:
            return
        tile = self._tile_for(key)
        try:
            if tile is not None:
                tile.BringIntoView()
        except Exception:
            pass
        fx[u"scale"].ScaleX = fx[u"scale"].ScaleY = 0.4
        self._scale_to(key, 1.0, POP_S, rba_core.ease_out_back)

    # ------------------------------------------------------------ geometry

    def _tile_for(self, key):
        children = self.panel.Children
        for index in range(children.Count):
            if to_text(getattr(children[index], u"Tag", u"") or u"") == key:
                return children[index]
        return None

    def _index_of(self, tile):
        children = self.panel.Children
        for index in range(children.Count):
            if Object.ReferenceEquals(children[index], tile):
                return index
        return -1

    def _slot(self, child):
        u"""Where a tile BELONGS, ignoring any render transform it has."""
        rect = LayoutInformation.GetLayoutSlot(child)
        return (rect.X, rect.Y, rect.Width, rect.Height)

    def _slots(self):
        out = []
        children = self.panel.Children
        for index in range(children.Count):
            try:
                out.append(self._slot(children[index]))
            except Exception:
                out.append((0.0, 0.0, 0.0, 0.0))
        return out

    # ------------------------------------------------------------ pick up

    def cancel_press(self):
        try:
            self.hold.Stop()
        except Exception:
            pass
        if not self.lifted:
            self.press = None

    def on_hold(self, sender, args):
        u"""Held still long enough: lift where it is."""
        self.hold.Stop()
        if self.press is None or self.lifted:
            return
        try:
            if Mouse.LeftButton != MouseButtonState.Pressed:
                self.press = None
                return
        except Exception:
            pass
        self.lift()

    def lift(self):
        press = self.press
        if press is None or self.lifted:
            return
        self.hold.Stop()
        self.lifted = True
        tile = press[u"tile"]
        key = press[u"key"]
        # Captured on the grid, never the tile: the tile is about to be taken
        # out and put back as it moves.
        try:
            self.panel.CaptureMouse()
        except Exception:
            pass
        Panel.SetZIndex(tile, 100)
        tile.Cursor = Cursors.SizeAll
        tile.Background = self.pane.res(u"BgWindow")
        self._scale_to(key, LIFT_SCALE, LIFT_S, rba_core.ease_out_back)
        self._lift_to(key, 1.0, LIFT_S)
        try:
            self.follow(Mouse.GetPosition(self.panel), reorder=False)
        except Exception:
            pass

    def on_move(self, sender, args):
        press = self.press
        if press is None:
            return
        try:
            if args.LeftButton != MouseButtonState.Pressed:
                if self.lifted:
                    self.drop()
                else:
                    self.cancel_press()
                return
            here = args.GetPosition(self.panel)
        except Exception:
            return
        if not self.lifted:
            start = press[u"start"]
            if (abs(here.X - start.X) < rba_core.FAV_DRAG_PX
                    and abs(here.Y - start.Y) < rba_core.FAV_DRAG_PX):
                return
            self.lift()
        self.follow(here)

    def follow(self, here, reorder=True):
        u"""Keep the lifted tile under the cursor; move it to the slot below."""
        press = self.press
        if press is None:
            return
        tile = press[u"tile"]
        key = press[u"key"]
        if reorder:
            source = self._index_of(tile)
            target = rba_core.drop_index(self._slots(), (here.X, here.Y))
            if source >= 0 and target is not None and target != source:
                self._reorder(tile, source, target)
        fx = self.fx.get(key)
        if fx is None:
            return
        # It follows the cursor directly while held - no easing, or it lags.
        self.tweens.stop(key + u"#x")
        self.tweens.stop(key + u"#y")
        slot = self._slot(tile)
        grab = press[u"grab"]
        fx[u"move"].X = here.X - grab.X - slot[0]
        fx[u"move"].Y = here.Y - grab.Y - slot[1]

    def _reorder(self, tile, source, target):
        u"""Move the lifted tile's slot, and glide the others to theirs."""
        children = self.panel.Children
        before = {}
        for index in range(children.Count):
            child = children[index]
            child_key = to_text(getattr(child, u"Tag", u"") or u"")
            if child_key:
                before[child_key] = self._slot(child)
        children.RemoveAt(source)
        children.Insert(min(target, children.Count), tile)
        # Lay out now, so the new slots are there to read - WPF would
        # otherwise wait for its next pass.
        try:
            self.panel.UpdateLayout()
        except Exception:
            pass
        lifted_key = self.press[u"key"]
        for index in range(children.Count):
            child = children[index]
            child_key = to_text(getattr(child, u"Tag", u"") or u"")
            if not child_key or child_key == lifted_key or child_key not in before:
                continue
            old = before[child_key]
            new = self._slot(child)
            dx, dy = old[0] - new[0], old[1] - new[1]
            if abs(dx) < 0.5 and abs(dy) < 0.5:
                continue
            fx = self.fx.get(child_key)
            if fx is None:
                continue
            # Start drawn where it was (plus anything still in flight), then
            # glide home: it slides out of the way instead of jumping.
            fx[u"move"].X += dx
            fx[u"move"].Y += dy
            self._slide_home(child_key, SLIDE_S)

    # ------------------------------------------------------------ let go

    def on_up(self, sender, args):
        press = self.press
        if press is None:
            return
        self.hold.Stop()
        if self.lifted:
            self.drop()
            args.Handled = True
            return
        self.press = None
        # Let go before it lifted: a click.
        self.pane.launch(press[u"item"])

    def on_lost_capture(self, sender, args):
        if self.lifted:
            self.drop()

    def drop(self):
        u"""Settle the tile into its slot, then save the order."""
        press = self.press
        self.press = None
        if not self.lifted:
            return
        self.lifted = False
        self.hold.Stop()
        try:
            self.panel.ReleaseMouseCapture()
        except Exception:
            pass
        if press is None:
            return
        tile = press[u"tile"]
        key = press[u"key"]

        def settled():
            try:
                Panel.SetZIndex(tile, 0)
                tile.Cursor = Cursors.Hand
            except Exception:
                pass

        self._slide_home(key, DROP_S, rba_core.ease_out, settled)
        self._scale_to(key, 1.0, DROP_S, rba_core.ease_out)
        self._lift_to(key, 0.0, DROP_S)

        shown = []
        for index in range(self.panel.Children.Count):
            tag = getattr(self.panel.Children[index], u"Tag", None)
            if tag:
                shown.append(to_text(tag))
        order = merge_order(self.keys(), shown)
        if order != self.keys():
            rba_core.set_list(self.pane.settings, u"favourites", order)
            self.pane.save_settings()
            log(u"favourites reordered")

    # ------------------------------------------------------------ empty space

    def on_panel_context(self, sender, args):
        u"""Right click between the tiles: show or hide the names."""
        if args.Handled:
            return
        try:
            menu = ContextMenu()
            rba_ui.merge_theme(menu)
            rba_theme.apply(menu, self.pane.theme_name)
            entry = MenuItem()
            entry.Header = (u"Hide the names" if self.labels_shown()
                            else u"Show the names")

            def on_click(s, a):
                self.toggle_labels()

            entry.Click += on_click
            menu.Items.Add(entry)
            menu.PlacementTarget = self.panel
            menu.IsOpen = True
            args.Handled = True
        except Exception:
            log_exception(u"fav/panel menu")


def merge_order(saved, shown):
    u"""The saved order, with the shown tiles rearranged in place.

    Favourites that are not on screen - a folder that has gone, an addin
    hidden because it is not loaded - keep their places in the list; only the
    slots the visible tiles occupy take the new order.
    """
    visible = set(shown)
    queue = list(shown)
    out = []
    for key in saved:
        if key in visible:
            out.append(queue.pop(0))
        else:
            out.append(key)
    out.extend(queue)
    return out

