# -*- coding: utf-8 -*-
u"""Builds the Family Floor Support panel of HangerAutomation.xaml from the
Family Hangers panel, so the two tabs never drift apart.

Run after changing the Family Hangers panel:   python build_floor_panel.py
import_check.rule_floor_panel_in_sync fails until you do.

The floor panel is the hanger panel with:
  - every x:Name renamed Fam -> Flr (hfam_core.flr_name), FamPanel -> FloorPanel;
  - the Drop rod extender tool and every drop rod tick removed;
  - 'hanger' -> 'support' in visible text, and a few texts rewritten;
  - a floor-only card after the workset row: what the supports stand on
    (the service's level, or a floor / roof / equipment you pick).
Not loaded by Revit (pyRevit only runs script.py); plain CPython or IronPython.
"""
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LAYOUT = 'HangerAutomation.xaml'
START = '        <ScrollViewer x:Name="FamPanel"'
FLOOR_START = '        <!-- ================ Family floor support'
END = '        </ScrollViewer>\n'
CARD = '            <Border Background="{DynamicResource CardBrush}"'
CARD_END = '\n            </Border>\n'
ROD_TICKS = ('ChkFamRodPlace', 'ChkFamRodRealign', 'ChkFamRodAuto')
WS_CARD_END = '\n          </Border>\n'

# floor-only: what the supports stand on (placed after the workset row)
BASE_CARD = u'''          <Border Background="{DynamicResource CardBrush}" BorderBrush="{DynamicResource EdgeBrush}" BorderThickness="1" CornerRadius="5" Padding="12,8" Margin="0,0,0,8">
            <Grid>
              <Grid.ColumnDefinitions>
                <ColumnDefinition Width="Auto"/>
                <ColumnDefinition Width="Auto"/>
                <ColumnDefinition Width="*"/>
              </Grid.ColumnDefinitions>
              <Grid.RowDefinitions>
                <RowDefinition Height="Auto"/>
                <RowDefinition Height="Auto"/>
              </Grid.RowDefinitions>
              <Viewbox Grid.Column="0" Width="20" Height="20" Margin="0,0,8,0" VerticalAlignment="Center">
                <Canvas Width="24" Height="24">
                  <Path Stroke="{DynamicResource GreenBrush}" StrokeThickness="2" StrokeStartLineCap="Round" StrokeEndLineCap="Round" Data="M6,3 L6,17 M18,3 L18,17 M3,9 L21,9"/>
                  <Path Stroke="{DynamicResource OrangeBrush}" StrokeThickness="2.4" StrokeStartLineCap="Round" StrokeEndLineCap="Round" Data="M1,21 L23,17"/>
                </Canvas>
              </Viewbox>
              <TextBlock Grid.Column="1" Text="Supports stand on" VerticalAlignment="Center" Margin="0,0,10,0"/>
              <ComboBox x:Name="CmbFlrBase" Grid.Column="2" ToolTip="The level: the base sits on the service&apos;s level. A picked element: after you start a tool you click a floor, roof or mechanical equipment (here or in a linked model) and each support&apos;s base is lifted onto its top surface, still hosted on the same level."/>
              <CheckBox x:Name="ChkFlrBaseLinked" Grid.Row="1" Grid.Column="2" Content="It is in a linked model" Margin="0,6,0,0" ToolTip="Go straight to picking inside a link. Unticked, clicking a link still works - you are asked to click the element inside it next."/>
            </Grid>
          </Border>
'''

# whole attribute values rewritten for the floor tab (after hanger -> support)
TEXTS = {
    u'Click on a duct, pipe or cable tray: the support is centred at the invert, on its level, square to it and stretched to its width. Click mechanical equipment or a duct accessory and it goes under the unit&apos;s bottom face, across the unit and stretched to its width. Or select several services first, press Pick and place and click on one of them: one support goes round all of them, centred on them, stretched to the outer edges and at the lowest invert. Esc to finish.':
        u'Click on a duct, pipe or cable tray: the support stands on the service&apos;s level (or the floor, roof or equipment you pick - see Supports stand on), centred under it and square to it, with its first bar at the service invert, its height to the service depth and its width to the service. Click mechanical equipment or a duct accessory and it goes under the unit&apos;s bottom face. Or select several services first, press Pick and place and click on one of them: one support goes round all of them, centred on them, stretched to the outer edges, standing at the lowest invert and as tall as the tallest. Esc to finish.',
    u'Ticked: the support wraps the insulation (width + 2 x thickness, invert lowered by the thickness). Unticked: it fits the bare duct inside the insulation.':
        u'Ticked: the support goes round the insulation (width and height + 2 x thickness, first bar lowered by the thickness). Unticked: it fits the bare duct inside the insulation.',
    u'Width, drop rod and soffit settings for this family':
        u'Width, first bar and support height settings for this family',
    u'Rules for hanging several services together':
        u'Rules for supporting several services together (shared with the Family Hangers tab)',
    u'Pick the service (several to share supports), Finish, then the supports: each slides sideways onto the centreline of the segment it hangs from - never along the run - and its height and width are refitted.':
        u'Pick the service (several to share supports), Finish, then the supports: each slides sideways under the centreline of the segment above it - never along the run - and its first bar, height and width are refitted.',
}


def flr_name(name):
    u"""Same as hfam_core.flr_name (kept here so this script needs no Revit stubs)."""
    if name == u'FamPanel':
        return u'FloorPanel'
    if name == u'LstFamilies':
        return u'LstFlrFamilies'
    return name.replace(u'Fam', u'Flr', 1)


def _support(text):
    for a, b in ((u'Hangers', u'Supports'), (u'hangers', u'supports'), (u'Hanger', u'Support'), (u'hanger', u'support')):
        text = re.sub(r'\b%s\b' % a, b, text)
    return TEXTS.get(text, text)


def fam_panel(xaml):
    a = xaml.index(START)
    b = xaml.index(END, a) + len(END)
    return xaml[a:b]


def floor_panel(fam):
    u"""The floor panel text from the hanger panel text."""
    s = fam
    i = s.index('x:Name="HdrFamRods"')            # drop the rod extender card
    a = s.rindex(CARD, 0, i)
    b = s.index(CARD_END, i) + len(CARD_END)
    s = s[:a] + s[b:]
    s = u''.join(ln for ln in s.splitlines(True) if not any('x:Name="%s"' % t in ln for t in ROD_TICKS))
    s = re.sub(r'x:Name="(\w+)"', lambda m: 'x:Name="%s"' % flr_name(m.group(1)), s)
    s = re.sub(r'\b(Text|Content|ToolTip)="([^"]*)"', lambda m: '%s="%s"' % (m.group(1), _support(m.group(2))), s)
    i = s.index(WS_CARD_END, s.index('x:Name="CmbFlrWorkset"')) + len(WS_CARD_END)
    s = s[:i] + BASE_CARD + s[i:]
    head = (u'        <!-- ================ Family floor support (built from the Family Hangers panel by '
            u'build_floor_panel.py - do not edit by hand) ================ -->\n')
    return head + s


def rebuilt(xaml):
    u"""The whole layout with its floor panel rebuilt."""
    new = floor_panel(fam_panel(xaml))
    a = xaml.index(FLOOR_START)
    b = xaml.index(END, xaml.index('x:Name="FloorPanel"')) + len(END)
    return xaml[:a] + new + xaml[b:]


def main(root=HERE):
    p = os.path.join(root, LAYOUT)
    with io.open(p, encoding='utf-8') as f:
        x = f.read()
    y = rebuilt(x)
    if y != x:
        with io.open(p, 'w', encoding='utf-8') as f:
            f.write(y)
        print('floor panel rebuilt')
    else:
        print('floor panel already up to date')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else HERE))
