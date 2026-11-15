# -*- coding: utf-8 -*-
"""Auto RevCloud - the dark and light palettes.

Every key here has a SolidColorBrush of the same name in Theme.xaml, and every
brush in Theme.xaml has a key here; the bench check enforces both directions.
theme.apply (in arc_ui) writes these straight onto window.Resources, which sits
in front of the merged Theme.xaml in WPF's lookup order, so the palette can be
swapped on an open window with no reload.
"""

DARK = {
    u"WindowBg": u"#232326",
    u"CardBg": u"#2B2B2E",
    u"FieldBg": u"#1C1C1F",
    u"BarBg": u"#1C1C1F",
    u"EdgeBrush": u"#3E3E42",
    u"ShellEdge": u"#4A4A50",
    u"TextBrush": u"#E4E4E4",
    u"MutedBrush": u"#9A9A9E",
    u"BlueBrush": u"#4FA3E3",
    u"OrangeBrush": u"#E8912D",
    u"OrangeHoverBrush": u"#F4A64A",
    u"GreenBrush": u"#3FA75A",
    u"GreenHoverBrush": u"#4EC06D",
    u"RedBrush": u"#D9534F",
    u"SelectBrush": u"#2B5473",
    u"HoverBrush": u"#35353A",
    u"ButtonBg": u"#333338",
    u"ButtonHover": u"#3F3F45",
    u"OnAccentBrush": u"#FFFFFF",
    u"ProgressBg": u"#2B2B2E",
}

# Not the dark one inverted: the accents are darkened because the dark
# palette's accents are chosen to sit on near-black and wash out on white.
LIGHT = {
    u"WindowBg": u"#F3F3F5",
    u"CardBg": u"#FFFFFF",
    u"FieldBg": u"#FAFAFC",
    u"BarBg": u"#E6E6EA",
    u"EdgeBrush": u"#C9C9CF",
    u"ShellEdge": u"#B8B8C0",
    u"TextBrush": u"#1E1E22",
    u"MutedBrush": u"#6A6A72",
    u"BlueBrush": u"#1B72BE",
    u"OrangeBrush": u"#B96A12",
    u"OrangeHoverBrush": u"#D17E1F",
    u"GreenBrush": u"#2E8546",
    u"GreenHoverBrush": u"#379B53",
    u"RedBrush": u"#B93B37",
    u"SelectBrush": u"#CFE3F6",
    u"HoverBrush": u"#E9EEF5",
    u"ButtonBg": u"#E9E9EE",
    u"ButtonHover": u"#DCDCE3",
    u"OnAccentBrush": u"#FFFFFF",
    u"ProgressBg": u"#E6E6EA",
}

PALETTES = {u"dark": DARK, u"light": LIGHT}


def palette_for(name):
    return PALETTES.get(name, DARK)
