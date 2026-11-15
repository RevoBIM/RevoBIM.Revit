# -*- coding: utf-8 -*-
"""RevoBIM PY - Wires: the bench's own bench.

A rule nobody has seen fail is a rule that might not work. Each case below
breaks one thing on a scratch copy of this folder and confirms the bench
catches it - RULES against import_check.py, LOGIC against bench_logic.py.

    python selftest.py

Exit code 0 means every deliberate breakage was caught.
"""

from __future__ import print_function

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

# (label, file, exact text, replacement, what the report must say)
RULES = [
 ('layout StaticResource', 'WiresConfirm.xaml', '{DynamicResource BtnGhost}', '{StaticResource BtnGhost}', 'StaticResource BtnGhost in a layout'),
 ('undefined dynamic key', 'WiresShuffle.xaml', 'Content="Arc"\n                    Style="{DynamicResource Segment}"', 'Content="Arc"\n                    Style="{DynamicResource Segmnt}"', 'DynamicResource Segmnt is not defined'),
 ('style type mismatch', 'WiresShuffle.xaml', 'Content="&#x25B2;"\n                          Style="{DynamicResource BtnStep}"/>', 'Content="&#x25B2;"\n                          Style="{DynamicResource Btn}"/>', 'TargetType is Button'),
 ('hex in layout', 'WiresResults.xaml', 'Background="{DynamicResource Field}"', 'Background="#112233"', 'colour #112233 by value in a layout'),
 ('window resources back', 'WiresConfirm.xaml', '<Border x:Name="Chrome"', '<Window.Resources></Window.Resources>\n  <Border x:Name="Chrome"', 'carries its own Window.Resources'),
 ('missing shrink button', 'WiresSettings.xaml', 'x:Name="ShrinkButton"', 'x:Name="ShrinkButtn"', 'no ShrinkButton'),
 ('arrow not green', 'WiresResults.xaml', 'Stroke="{DynamicResource Green}" StrokeThickness="2"', 'Stroke="{DynamicResource Blue}" StrokeThickness="2"', 'not drawn in the palette green'),
 ('static outside BasedOn', 'Theme.xaml', '<Setter Property="Foreground" Value="{DynamicResource Muted}"/>\n    <Setter Property="FontSize" Value="11"/>\n    <Setter Property="Height" Value="22"/>', '<Setter Property="Foreground" Value="{StaticResource Muted}"/>\n    <Setter Property="FontSize" Value="11"/>\n    <Setter Property="Height" Value="22"/>', 'outside a BasedOn'),
 ('BasedOn forward', 'Theme.xaml', 'BasedOn="{StaticResource BtnWin}"', 'BasedOn="{StaticResource Chip}"', 'BasedOn Chip is defined after'),
 ('palette parity', 'wires_theme.py', "        'OnBlue': '#FFFFFF',\n", "", 'carry different keys'),
 ('brush with no palette', 'Theme.xaml', '<SolidColorBrush x:Key="OnBlue"     Color="#0E2233"/>', '<SolidColorBrush x:Key="OnBlue"     Color="#0E2233"/>\n  <SolidColorBrush x:Key="Stray" Color="#0E2233"/>', 'brush Stray is in no palette'),
 ('fallback brush missing', 'Theme.xaml', '<SolidColorBrush x:Key="OnBlue"     Color="#0E2233"/>', '', 'no fallback brush for palette key OnBlue'),
 ('paint unknown key', 'settings_window.py', "ui.paint(card, Border.BackgroundProperty, 'Card')", "ui.paint(card, Border.BackgroundProperty, 'Cardd')", 'paints with Cardd'),
 ('paint either branch', 'settings_window.py', "'Blue' if side == 0 else 'Orange')", "'Blue' if side == 0 else 'Orang')", 'paints with Orang'),
 ('hex in window module', 'shuffle_window.py', "ui.paint(button, Control.ForegroundProperty, 'OnBlue')", "button.Foreground = ui.brush('#FFFFFF')", 'colour #FFFFFF by value'),
 ('window not dressed', 'confirm_window.py', '    ui.dress_header(window, core.__version__)\n', '', 'loads a window but never dresses it'),
 ('no drawer built', 'wires_ui.py', "        drawer = WindowDrawer(window, window.FindName('HeaderBar'),", "        drawer = make_drawer(window, window.FindName('HeaderBar'),", 'builds no WindowDrawer'),
 ('drawer not handed button', 'wires_ui.py', "window.FindName('ShrinkButton'))", "None)", 'not handed ShrinkButton'),
 ('chip unwired', 'wires_ui.py', '            chip.Click += _on_theme_chip\n', '            pass\n', 'Click is never wired'),
 ('theme not merged', 'wires_ui.py', '    _attach_theme(window)\n    return window', '    return window', 'does not merge the theme'),
 ('shrink unwired', 'wires_drawer.py', '                button.Click += self._on_click', '                self.handler = self._on_click', 'never wired to the drawer'),
 ('top never released', 'wires_drawer.py', '            self.window.BeginAnimation(Window.TopProperty, None)\n', '', 'never releases the TopProperty'),
 ('one try', 'wires_drawer.py', "            self.window.BeginAnimation(Window.HeightProperty, None)\n        except Exception:\n            pass\n        try:\n", "            self.window.BeginAnimation(Window.HeightProperty, None)\n", 'share one try'),
 ('no fallback', 'wires_drawer.py', "            # could not animate: go straight there\n            _land()", "            pass", 'no fallback to land'),
 ('minheight not restored', 'wires_drawer.py', "            window.MinHeight = self.saved.get('min_height', 0)", "            pass", 'MinHeight is never put back'),
 ('dead setting', 'wires_core.py', "    ('Circuits', 'The route', 'check', 'two_opt',", "    ('Circuits', 'The route', 'check', 'never_read_anywhere', 'x', 'no', ''),\n    ('Circuits', 'The route', 'check', 'two_opt',", 'never_read_anywhere" is on the Circuits tab but nothing reads it'),
]

# (label, file, exact text, replacement) - bench_logic must fail
LOGIC = [
 ('truthiness', 'wires_theme.py', "    if 'dark' in text:\n        return True", "    if not value:\n        return None\n    if 'dark' in text:\n        return True"),
 ('no canvas -> light', 'wires_theme.py', "    if canvas_dark is False:\n        return LIGHT", "    if not canvas_dark:\n        return LIGHT"),
 ('primary only', 'wires_drawer.py', "    return float(work_top) + float(work_height) - float(bar_height) - margin", "    return float(work_height) - float(bar_height) - margin"),
 ('jump back', 'wires_drawer.py', "        top = float(bar_top_now) + float(bar_height) - float(full_height)", "        top = float(saved_top)"),
 ('no clamp', 'wires_drawer.py', "    return max(top, float(work_top))", "    return top"),
 ('chip cycle', 'wires_theme.py', "MODES = (FOLLOW, DARK, LIGHT)", "MODES = (FOLLOW, LIGHT, DARK)"),
 ('weak tick', 'wires_theme.py', "        'OnBlue': '#0E2233',", "        'OnBlue': '#FFFFFF',"),
 ('no f11', 'wires_drawer.py', "Key.Enter,\n                                       Key.F11):", "Key.Enter):"),
]


def _mutated(name, old, new):
    work = tempfile.mkdtemp()
    copy = os.path.join(work, 'w')
    shutil.copytree(HERE, copy, ignore=shutil.ignore_patterns('__pycache__'))
    path = os.path.join(copy, name)
    with open(path) as handle:
        text = handle.read()
    if text.count(old) != 1:
        shutil.rmtree(work)
        return None, None
    with open(path, 'w') as handle:
        handle.write(text.replace(old, new))
    return work, copy


def _run(copy, script):
    return subprocess.run([sys.executable, script], cwd=copy,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          universal_newlines=True)


def main():
    missed = []
    for label, name, old, new, expect in RULES:
        work, copy = _mutated(name, old, new)
        if work is None:
            missed.append('setup: ' + label)
            continue
        if expect not in _run(copy, 'import_check.py').stdout:
            missed.append('rule: ' + label)
        shutil.rmtree(work)
    for label, name, old, new in LOGIC:
        work, copy = _mutated(name, old, new)
        if work is None:
            missed.append('setup: ' + label)
            continue
        if _run(copy, 'bench_logic.py').returncode == 0:
            missed.append('logic: ' + label)
        shutil.rmtree(work)
    total = len(RULES) + len(LOGIC)
    if missed:
        print('WIRES SELFTEST - {0} of {1} breakages NOT caught:'.format(
            len(missed), total))
        for line in missed:
            print('  ' + line)
        return 1
    print('WIRES SELFTEST - all {0} deliberate breakages caught.'.format(total))
    return 0


if __name__ == '__main__':
    sys.exit(main())
