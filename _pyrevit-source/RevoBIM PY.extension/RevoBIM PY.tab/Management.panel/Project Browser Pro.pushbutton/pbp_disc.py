# -*- coding: utf-8 -*-
u"""Project Browser Pro - MEP disciplines read from names.

One table drives two things:
  * the icon on a folder heading in Views and Sheets (Pipework, Ductwork,
    Electrical Containment, Electrical Power, ...) and that heading's colour
  * the icon on a view, from its view template's name (Power, Security /
    Fire Alarm, Fire Protection, Ductwork, Heating Pipework, Drainage,
    Water Services, ...)

Matching is on words, never on any substring: a phrase has to start a word
("DRAIN" finds DRAINAGE, "VENT" does not find PREVENT, "LV" does not find
SOLVENT). The table is ordered and the first match wins, which is how
HEATING PIPEWORK reads as heating, CHILLED WATER as pipework rather than
water services, and SOIL VENT PIPE as drainage rather than ventilation.

Icons are drawn on the same 12 x 12 grid as the row icons, as geometry, so
they recolour with the theme and cannot come out as empty boxes.

Pure Python: the bench checks every name in a table of cases.
"""
import re

from pbp_compat import to_text

# (key, label, phrases matched at a word start, (dark colour, light colour), icon)
DISCIPLINES = [
    (u'security', u'Security / Fire Alarm',
     (u'SECURITY', u'FIRE ALARM', u'FIREALARM', u'ACCESS CONTROL', u'CCTV',
      u'INTRUDER', u'DETECTION', u'FA'),
     (u'#D45BA8', u'#9C2F76'),
     # a bell
     u'M6,0.8 C3.6,0.8 2.6,2.8 2.6,5 L2.6,7.6 L1.2,9.2 L10.8,9.2 L9.4,7.6 '
     u'L9.4,5 C9.4,2.8 8.4,0.8 6,0.8 Z M4.6,10 A1.4,1.4 0 0 0 7.4,10 Z'),
    (u'fire', u'Fire Protection',
     (u'FIRE PROTECTION', u'SPRINKLER', u'SUPPRESSION', u'DRY RISER',
      u'WET RISER', u'HOSE REEL', u'FIRE FIGHTING', u'FIREFIGHTING', u'MIST'),
     (u'#F2773A', u'#B84B14'),
     # a flame
     u'M6,0.6 C7.4,3 9.8,4.4 9.8,7.4 C9.8,9.8 8,11.4 6,11.4 C4,11.4 2.2,9.8 '
     u'2.2,7.6 C2.2,5.8 3.2,4.8 4,4 C4.2,5.4 4.8,6 5.4,6.2 C5,4.2 5.4,2.2 6,0.6 Z'),
    (u'heating', u'Heating Pipework',
     (u'HEATING', u'LTHW', u'MTHW', u'HTHW', u'RADIATOR', u'UNDERFLOOR', u'UFH'),
     (u'#E5534B', u'#B02A22'),
     # a radiator: three sections and two feet
     u'F0 M1,3 L11,3 L11,10 L1,10 Z M2.4,4.3 L3.8,4.3 L3.8,8.7 L2.4,8.7 Z '
     u'M5.3,4.3 L6.7,4.3 L6.7,8.7 L5.3,8.7 Z M8.2,4.3 L9.6,4.3 L9.6,8.7 L8.2,8.7 Z '
     u'M2,10 L3.2,10 L3.2,11.6 L2,11.6 Z M8.8,10 L10,10 L10,11.6 L8.8,11.6 Z'),
    (u'drainage', u'Drainage',
     (u'DRAINAGE', u'DRAIN', u'SOIL', u'WASTE', u'RAINWATER', u'RWP', u'FOUL',
      u'SANITARY', u'SVP', u'GULLY', u'SYPHONIC'),
     (u'#B08A5A', u'#7A5A30'),
     # a gully: funnel into an outlet
     u'M1,2 L11,2 L7.2,6.5 L7.2,11 L4.8,11 L4.8,6.5 Z'),
    (u'pipework', u'Pipework',
     # cooling and gas first: CHILLED WATER is pipework, not water services
     (u'CHILLED', u'CHW', u'CONDENSER', u'REFRIGERANT', u'COOLING'),
     (u'#3FA75A', u'#2E8546'),
     None),
    (u'water', u'Water Services',
     (u'WATER SERVICES', u'DOMESTIC WATER', u'COLD WATER', u'HOT WATER',
      u'WATER', u'DCW', u'DHW', u'MCWS', u'BCWS', u'BOOSTED', u'POTABLE'),
     (u'#3BB8D9', u'#147FA0'),
     # a tap with a drop
     u'M2,4 L8.5,4 C10.2,4 11,5 11,6.6 L11,7.6 L9.2,7.6 L9.2,6.8 C9.2,6.2 8.9,6 '
     u'8.4,6 L2,6 Z M4.2,1.2 L6.2,1.2 L6.2,4 L4.2,4 Z M2.4,0.8 L8,0.8 L8,1.8 '
     u'L2.4,1.8 Z M10.1,8.6 C10.6,9.4 11,10 11,10.5 A0.9,0.9 0 0 1 9.2,10.5 '
     u'C9.2,10 9.6,9.4 10.1,8.6 Z'),
    (u'ductwork', u'Ductwork',
     (u'DUCTWORK', u'DUCT', u'DUCTS', u'AIR TERMINAL', u'VENTILATION', u'VENT', u'SUPPLY AIR', u'EXTRACT',
      u'EXHAUST', u'MVHR', u'AHU', u'AIR CONDITIONING', u'HVAC'),
     (u'#4FA3E3', u'#1B72BE'),
     # a duct with a flow arrow
     u'F0 M0.5,3 L11.5,3 L11.5,9 L0.5,9 Z M2,4.5 L10,4.5 L10,7.5 L2,7.5 Z '
     u'M3,5.4 L6.5,5.4 L6.5,4.6 L8.6,6 L6.5,7.4 L6.5,6.6 L3,6.6 Z'),
    (u'containment', u'Electrical Containment',
     (u'CONTAINMENT', u'CABLE TRAY', u'CABLE LADDER', u'TRAY', u'LADDER',
      u'TRUNKING', u'BASKET', u'CONDUIT'),
     (u'#E8912D', u'#B96A12'),
     # a cable ladder: two rails and three rungs
     u'M0.5,2.5 L11.5,2.5 L11.5,4 L0.5,4 Z M0.5,8 L11.5,8 L11.5,9.5 L0.5,9.5 Z '
     u'M2,4 L3.2,4 L3.2,8 L2,8 Z M5.4,4 L6.6,4 L6.6,8 L5.4,8 Z M8.8,4 L10,4 L10,8 L8.8,8 Z'),
    (u'lighting', u'Lighting',
     (u'LIGHTING', u'LUMINAIRE', u'LIGHT FITTING', u'EMERGENCY LIGHT'),
     (u'#F0D264', u'#9A7A12'),
     # a light bulb
     u'M6,0.6 C3.3,0.6 1.8,2.6 1.8,4.6 C1.8,6.2 2.8,7.2 3.8,8 L3.8,9.2 L8.2,9.2 L8.2,8 '
     u'C9.2,7.2 10.2,6.2 10.2,4.6 C10.2,2.6 8.7,0.6 6,0.6 Z M4,10 L8,10 L8,11.4 L4,11.4 Z'),
    (u'comms', u'Data & Communications',
     (u'DATA', u'COMMS', u'COMMUNICATION', u'TELECOM', u'STRUCTURED CABLING', u'NURSE CALL',
      u'AUDIO VISUAL', u'AV'),
     (u'#6FD08C', u'#2E8546'),
     # three linked nodes
     u'M6,0.8 A1.7,1.7 0 1 0 6.01,0.8 Z M5.4,3.8 L6.6,3.8 L6.6,6.4 L10,8.2 L9.4,9.2 L6,7.4 '
     u'L2.6,9.2 L2,8.2 L5.4,6.4 Z M2,8.6 A1.6,1.6 0 1 0 2.01,8.6 Z M10,8.6 A1.6,1.6 0 1 0 10.01,8.6 Z'),
    (u'power', u'Electrical Power',
     (u'POWER', u'ELECTRICAL', u'ELEC', u'SUBMAIN', u'SUB MAIN', u'DISTRIBUTION',
      u'LV', u'SMALL POWER'),
     (u'#E8C33A', u'#9A7A12'),
     # a lightning bolt
     u'M7,0.5 L2.2,6.8 L5.4,6.8 L4.4,11.5 L9.8,4.8 L6.6,4.8 Z'),
    (u'pipework', u'Pipework',
     (u'PIPEWORK', u'PIPE', u'PIPES', u'PIPING', u'GAS', u'MECHANICAL PIPE'),
     (u'#3FA75A', u'#2E8546'),
     None),
    # the generic headings last, so anything more specific wins first
    (u'plumbing', u'Plumbing & Public Health',
     (u'PLUMBING', u'PUBLIC HEALTH', u'SANITARYWARE'),
     (u'#B08A5A', u'#7A5A30'),
     # a basin with a tap over it
     u'M1,5.4 L11,5.4 C11,8.6 8.8,10.6 6,10.6 C3.2,10.6 1,8.6 1,5.4 Z '
     u'M5.4,1 L6.6,1 L6.6,4.4 L5.4,4.4 Z M3.6,1 L8.4,1 L8.4,2 L3.6,2 Z'),
    (u'mechanical', u'Mechanical',
     (u'MECHANICAL', u'MECH'),
     (u'#4FA3E3', u'#1B72BE'),
     # a fan: four blades round a hub
     u'M6,6 C5,3.6 5.2,1.2 6.6,0.8 C8,0.6 8.2,3 6,6 Z M6,6 C8.4,5 10.8,5.2 11.2,6.6 '
     u'C11.4,8 9,8.2 6,6 Z M6,6 C7,8.4 6.8,10.8 5.4,11.2 C4,11.4 3.8,9 6,6 Z M6,6 '
     u'C3.6,7 1.2,6.8 0.8,5.4 C0.6,4 3,3.8 6,6 Z'),
]

# Which colour gradient each discipline's headings are drawn in.
FAMILY = {
    u'security': u'electrical', u'lighting': u'electrical', u'comms': u'electrical',
    u'power': u'electrical', u'containment': u'electrical',
    u'ductwork': u'mechanical', u'heating': u'mechanical', u'pipework': u'mechanical',
    u'mechanical': u'mechanical',
    u'drainage': u'plumbing', u'water': u'plumbing', u'plumbing': u'plumbing',
    u'fire': u'other',
}

# An elbow of pipe with its two flanges.
PIPEWORK_ICON = (u'M1,3.5 L8.5,3.5 L8.5,11 L5.5,11 L5.5,6.5 L1,6.5 Z '
                 u'M0.5,2.5 L1.8,2.5 L1.8,7.5 L0.5,7.5 Z M4.5,9.7 L9.5,9.7 L9.5,11.5 L4.5,11.5 Z')

_COMPILED = []


def _compile():
    if _COMPILED:
        return _COMPILED
    for key, label, phrases, colours, icon in DISCIPLINES:
        parts = [re.escape(p).replace(u'\\ ', u' ') for p in phrases]
        # start of a word, and for short codes (4 letters or fewer) the end
        # of one too, so FA never finds FAN and LV never finds LVL.
        alternatives = []
        for phrase, part in zip(phrases, parts):
            tail = u'(?![A-Z0-9])' if len(phrase) <= 4 else u''
            alternatives.append(part + tail)
        pattern = re.compile(u'(?<![A-Z0-9])(?:' + u'|'.join(alternatives) + u')')
        _COMPILED.append((key, pattern))
    return _COMPILED


def normalise(text):
    u"""Upper case, every run of non letters/digits one space: BGL_M-Heating
    reads as BGL M HEATING."""
    return u' '.join(re.split(u'[^A-Z0-9]+', to_text(text).upper())).strip()


def match(text):
    u"""The discipline key for a name, or None."""
    clean = normalise(text)
    if not clean:
        return None
    for key, pattern in _compile():
        if pattern.search(clean):
            return key
    return None


def _entry(key):
    for entry in DISCIPLINES:
        if entry[0] == key:
            return entry
    return None


def icon(key):
    entry = _entry(key)
    if entry is None:
        return None
    return entry[4] or PIPEWORK_ICON


def colour(key, theme_name):
    entry = _entry(key)
    if entry is None:
        return None
    return entry[3][1] if theme_name == u'light' else entry[3][0]


def label(key):
    entry = _entry(key)
    return entry[1] if entry else u''


def family(key):
    u"""'electrical', 'mechanical', 'plumbing' or 'other' (also for None)."""
    return FAMILY.get(key, u'other')


def keys():
    seen = []
    for entry in DISCIPLINES:
        if entry[0] not in seen:
            seen.append(entry[0])
    return seen
