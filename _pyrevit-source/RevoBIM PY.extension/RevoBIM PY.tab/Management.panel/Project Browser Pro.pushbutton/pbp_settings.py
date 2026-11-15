# -*- coding: utf-8 -*-
u"""Project Browser Pro - settings and browser organisations.

Plain key=value text under %APPDATA%\\RevoBIM\\, split on the first '=' only.
A missing or damaged file falls back to the defaults key by key; keys from an
older version are ignored rather than breaking the load.

Two files:
  project_browser_pro.txt                     global: theme, zoom, colour, debug
  project_browser_pro_orgs\\<project>.txt     one browser organisation per tab,
                                              saved against the project

Changing a default here does nothing for anyone who already has a file -
bump SETTINGS_VERSION and add the change to MIGRATIONS.
"""
import io
import os

from pbp_compat import to_text, safe_file_part, clamp

SETTINGS_VERSION = 1
SETTINGS_FILE = u'project_browser_pro.txt'
ORGS_FOLDER = u'project_browser_pro_orgs'

DEFAULTS = {
    u'settings_version': u'1',
    u'theme': u'follow',      # follow | dark | light
    u'zoom': u'1.0',
    u'colour': u'colour',     # colour | grey | custom (1.4: '1' / '0')
    u'debug': u'1',           # on while the tool is new - Drew sends the report back
    u'last_tab': u'all',
    u'legend_sub': u'Legends',   # Legends tab: Legends | Drafting Views
    u'fav_sub': u'all',          # Favourites tab: all, or one type (views, sheets...)
    u'start_open': u'0',         # folders start closed (1.7.0); '1': open, as before
    u'bar': u'1',             # title line and tool buttons shown
    u'sync': u'1',            # selecting in the browser selects in Revit
    u'follow': u'1',          # selecting in Revit finds it in the browser
    u'custom_colours': u'',   # colours the user added to the choices (escaped list)
    # highlighted rows, per theme: fill and text, and bold or not
    u'highlight_dark': u'#8A7420',
    u'highlight_dark_text': u'#FFFFFF',
    u'highlight_light': u'#FFF0A0',
    u'highlight_light_text': u'#1E1E22',
    u'highlight_bold': u'1',
}
COLOUR_MODES = (u'colour', u'grey', u'custom')
COLOUR_LABELS = {u'colour': u'Colour', u'grey': u'Greyscale', u'custom': u'Custom'}
HIGHLIGHT_KEYS = (u'highlight_dark', u'highlight_dark_text', u'highlight_light', u'highlight_light_text')


def colour_mode(value):
    u"""colour / grey / custom, from any version's setting (1.4 stored the
    colour button as '1' on, '0' off)."""
    text = to_text(value).strip().lower()
    if text in COLOUR_MODES:
        return text
    if text in (u'0', u'false', u'off', u'no'):
        return u'grey'
    return u'colour'


def next_colour_mode(mode):
    index = COLOUR_MODES.index(colour_mode(mode))
    return COLOUR_MODES[(index + 1) % len(COLOUR_MODES)]

THEME_MODES = (u'follow', u'dark', u'light')

# version -> function(dict) that upgrades a file written by the version before.
MIGRATIONS = {}

TABS = (u'all', u'favourites', u'views', u'legends', u'sheets', u'panels', u'schedules',
        u'families')
ORGANISABLE = (u'views', u'legends', u'sheets', u'panels', u'schedules')
# The Favourites tab organises each type's favourites on its own (1.7.0),
# apart from that type's tab: organisation keys 'fav.views' ... 'fav.families'.
FAV_TYPES = (u'views', u'legends', u'sheets', u'schedules', u'panels', u'families')
FAV_ORGS = tuple(u'fav.' + tab for tab in FAV_TYPES)


def fav_org_key(tab):
    return u'fav.' + tab


def base_tab(key):
    u"""'fav.views' -> 'views'; a tab's own key as it is."""
    return key[4:] if key.startswith(u'fav.') else key


def organisable(key):
    return key in ORGANISABLE or key in FAV_ORGS


# Families keep their fixed grouping but their headings take colours of
# their own (1.7.0): saved with the others, only the colours read back.
FIXED_ORGS = (u'families',)
SAVED_ORGS = ORGANISABLE + FIXED_ORGS + FAV_ORGS


def colourable(key):
    u"""Whether a tab's (or favourites type's) headings can be given colours."""
    return organisable(key) or key in FIXED_ORGS
SOURCES = (u'revit', u'custom', u'none')
MAX_LEVELS = 6
# Folder levels drawn as coloured main headings unless the organisation
# says otherwise (View Group and View Purpose in a typical organisation).
DEFAULT_COLOURS = [1, 2]

DEFAULT_ORGS = {
    u'views': {u'source': u'revit', u'levels': [], u'sort': u'', u'desc': False},
    u'sheets': {u'source': u'revit', u'levels': [], u'sort': u'', u'desc': False},
    u'panels': {u'source': u'none', u'levels': [], u'sort': u'', u'desc': False},
    u'schedules': {u'source': u'none', u'levels': [], u'sort': u'', u'desc': False},
    # Revit shows legends flat, under their own Legends root
    u'legends': {u'source': u'none', u'levels': [], u'sort': u'', u'desc': False},
    # fixed: main group (Tags, Annotations, Architecture...) > category > family
    u'families': {u'source': u'custom', u'levels': [u'Main Group', u'Category', u'Family'],
                  u'sort': u'Type', u'desc': False},
}
# Favourites start as they always were: no grouping, under their type.
for _key in FAV_ORGS:
    DEFAULT_ORGS[_key] = {u'source': u'none', u'levels': [], u'sort': u'', u'desc': False}


# ============================================================
# key=value files
# ============================================================

def read_pairs(path):
    pairs = {}
    if not path or not os.path.isfile(path):
        return pairs
    try:
        handle = io.open(path, 'r', encoding='utf-8')
        try:
            lines = handle.read().splitlines()
        finally:
            handle.close()
    except Exception:
        return pairs
    for line in lines:
        line = to_text(line)
        if not line.strip() or line.lstrip().startswith(u'#'):
            continue
        if u'=' not in line:
            continue
        key, value = line.split(u'=', 1)
        pairs[key.strip()] = value
    return pairs


def write_pairs(path, pairs):
    u"""Write through a temporary file so a crash mid-write keeps the old one.

    os.replace does not exist on IronPython 2.7, so remove then rename.
    """
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    temp = path + u'.tmp'
    handle = io.open(temp, 'w', encoding='utf-8')
    try:
        for key in sorted(pairs):
            handle.write(u'{0}={1}\n'.format(to_text(key), to_text(pairs[key])))
    finally:
        handle.close()
    if os.path.isfile(path):
        os.remove(path)
    os.rename(temp, path)


def settings_path(folder):
    return os.path.join(folder, SETTINGS_FILE)


def load(folder):
    pairs = read_pairs(settings_path(folder))
    try:
        version = int(pairs.get(u'settings_version', u'0') or 0)
    except Exception:
        version = 0
    if pairs and version < SETTINGS_VERSION:
        for step in range(version + 1, SETTINGS_VERSION + 1):
            upgrade = MIGRATIONS.get(step)
            if upgrade is not None:
                try:
                    upgrade(pairs)
                except Exception:
                    pass
    data = dict(DEFAULTS)
    for key in DEFAULTS:
        if key in pairs:
            data[key] = pairs[key]
    data[u'settings_version'] = to_text(SETTINGS_VERSION)
    if data[u'theme'] not in THEME_MODES:
        data[u'theme'] = DEFAULTS[u'theme']
    if data[u'last_tab'] not in TABS:
        data[u'last_tab'] = DEFAULTS[u'last_tab']
    data[u'zoom'] = to_text(clamp(data[u'zoom'], 0.6, 2.0))
    data[u'colour'] = colour_mode(data[u'colour'])
    for key in HIGHLIGHT_KEYS:
        if not hex_colour(data[key]):
            data[key] = DEFAULTS[key]
    return data


def save(folder, data):
    try:
        write_pairs(settings_path(folder), data)
        return True
    except Exception:
        return False


def as_bool(value):
    return to_text(value).strip().lower() in (u'1', u'true', u'yes', u'on')


# ============================================================
# browser organisations
# ============================================================

def escape_list(items):
    u"""Join parameter names with '|', escaping '\\' and '|' inside names."""
    out = []
    for item in items:
        text = to_text(item).replace(u'\\', u'\\\\').replace(u'|', u'\\p')
        out.append(text)
    return u'|'.join(out)


def unescape_list(text):
    text = to_text(text)
    if not text:
        return []
    items = []
    current = []
    index = 0
    while index < len(text):
        ch = text[index]
        if ch == u'\\' and index + 1 < len(text):
            nxt = text[index + 1]
            current.append(u'|' if nxt == u'p' else nxt)
            index += 2
            continue
        if ch == u'|':
            items.append(u''.join(current))
            current = []
        else:
            current.append(ch)
        index += 1
    items.append(u''.join(current))
    return [i for i in items if i]


def normalise_org(org, tab):
    base = DEFAULT_ORGS.get(tab, DEFAULT_ORGS[u'schedules'])
    if not isinstance(org, dict):
        org = {}
    source = to_text(org.get(u'source', base[u'source']))
    if source not in SOURCES:
        source = base[u'source']
    levels = []
    for name in org.get(u'levels', base[u'levels']) or []:
        name = to_text(name).strip()
        if name and name not in levels:
            levels.append(name)
    levels = levels[:MAX_LEVELS]
    sort = to_text(org.get(u'sort', base[u'sort'])).strip()
    desc = org.get(u'desc', base[u'desc'])
    if not isinstance(desc, bool):
        desc = as_bool(desc)
    colours = parse_colours(org.get(u'colours', base.get(u'colours', DEFAULT_COLOURS)))
    return {u'source': source, u'levels': levels, u'sort': sort, u'desc': desc,
            u'colours': colours, u'group_colours': parse_group_colours(org.get(u'group_colours'))}


def hex_colour(text):
    u"""'#RRGGBB' upper case, or u'' for anything else."""
    text = to_text(text).strip().upper()
    if len(text) == 7 and text[0] == u'#':
        try:
            int(text[1:], 16)
            return text
        except Exception:
            pass
    return u''


def parse_group_colours(value):
    u"""{folder name: '#RRGGBB'} - colours the user gave group headings,
    from a dict or from the stored list 'name|#RRGGBB|name|#RRGGBB'."""
    if not value:
        return {}
    if isinstance(value, dict):
        pairs = list(value.items())
    else:
        items = unescape_list(to_text(value))
        pairs = list(zip(items[0::2], items[1::2]))
    out = {}
    for name, colour in pairs:
        name, colour = to_text(name), hex_colour(colour)
        if name and colour:
            out[name] = colour
    return out


def group_key(level, name):
    u"""How a colour for one value of one grouping level is stored: the
    level, a section sign, the folder name. (1.3.x stored bare names; those
    still work, for every level.)"""
    return u'{0}\u00a7{1}'.format(int(level), to_text(name))


def custom_colours(settings):
    return [c for c in (hex_colour(v) for v in unescape_list(settings.get(u'custom_colours', u''))) if c]


def set_custom_colours(settings, colours):
    settings[u'custom_colours'] = escape_list([c for c in (hex_colour(v) for v in colours) if c])


def group_colours_text(group_colours):
    items = []
    for name in sorted(group_colours):
        items.extend([name, group_colours[name]])
    return escape_list(items)


def parse_colours(value):
    u"""Coloured folder levels as a sorted list of 1..MAX_LEVELS, from a
    list or from text like '1,2'. Nothing usable: the default."""
    if value is None:
        return list(DEFAULT_COLOURS)
    if isinstance(value, (list, tuple, set)):
        items = value
    else:
        text = to_text(value).strip()
        if text == u'-':
            return []
        items = text.split(u',')
    out = []
    for item in items:
        try:
            level = int(to_text(item).strip())
        except Exception:
            continue
        if 1 <= level <= MAX_LEVELS and level not in out:
            out.append(level)
    if not out and not isinstance(value, (list, tuple, set)):
        return list(DEFAULT_COLOURS)
    return sorted(out)


def colours_text(colours):
    return u','.join(to_text(level) for level in colours) if colours else u'-'


# ============================================================
# pinned copies - headings dragged out into panes of their own
# ============================================================
PINS_FILE = u'project_browser_pro_pins.txt'


def pins_path(folder):
    return os.path.join(folder, PINS_FILE)


def load_pins(folder):
    u"""{slot: (tab, (folder labels...))} for every pinned pane slot."""
    pins = {}
    for key, value in read_pairs(pins_path(folder)).items():
        if not key.startswith(u'pin.'):
            continue
        try:
            slot = int(key[4:])
        except Exception:
            continue
        parts = unescape_list(value)
        if len(parts) >= 2 and parts[0] in TABS:
            pins[slot] = (parts[0], tuple(parts[1:]))
    return pins


def save_pin(folder, slot, tab, path):
    pairs = read_pairs(pins_path(folder))
    pairs[u'pin.{0}'.format(int(slot))] = escape_list([tab] + list(path))
    try:
        write_pairs(pins_path(folder), pairs)
        return True
    except Exception:
        return False


def default_orgs():
    return dict((tab, normalise_org(DEFAULT_ORGS[tab], tab)) for tab in DEFAULT_ORGS)


def orgs_path(folder, project_title):
    return os.path.join(folder, ORGS_FOLDER, safe_file_part(project_title) + u'.txt')


def orgs_from_pairs(pairs):
    orgs = default_orgs()
    for tab in SAVED_ORGS:
        prefix = tab + u'.'
        if (prefix + u'source') not in pairs:
            continue
        if tab in FIXED_ORGS:
            # the grouping is the tool's; the colours - which levels, and
            # each group's own - are the user's
            fixed = dict(DEFAULT_ORGS[tab])
            fixed[u'group_colours'] = pairs.get(prefix + u'group_colours')
            fixed[u'colours'] = pairs.get(prefix + u'colours')
            orgs[tab] = normalise_org(fixed, tab)
            continue
        orgs[tab] = normalise_org({
            u'source': pairs.get(prefix + u'source'),
            u'levels': unescape_list(pairs.get(prefix + u'levels', u'')),
            u'sort': pairs.get(prefix + u'sort', u''),
            u'desc': pairs.get(prefix + u'desc', u'0'),
            u'colours': pairs.get(prefix + u'colours'),
            u'group_colours': pairs.get(prefix + u'group_colours'),
        }, tab)
    return orgs


def orgs_to_pairs(orgs):
    pairs = {u'settings_version': to_text(SETTINGS_VERSION)}
    for tab in SAVED_ORGS:
        org = normalise_org(orgs.get(tab), tab)
        prefix = tab + u'.'
        pairs[prefix + u'source'] = org[u'source']
        pairs[prefix + u'levels'] = escape_list(org[u'levels'])
        pairs[prefix + u'sort'] = org[u'sort']
        pairs[prefix + u'desc'] = u'1' if org[u'desc'] else u'0'
        pairs[prefix + u'colours'] = colours_text(org[u'colours'])
        pairs[prefix + u'group_colours'] = group_colours_text(org[u'group_colours'])
    return pairs


def load_orgs(folder, project_title):
    return orgs_from_pairs(read_pairs(orgs_path(folder, project_title)))


def save_orgs(folder, project_title, orgs):
    try:
        write_pairs(orgs_path(folder, project_title), orgs_to_pairs(orgs))
        return True
    except Exception:
        return False


def describe_org(org, revit_name=u''):
    u"""One line for the status bar and the organisation dialog preview."""
    if org[u'source'] == u'revit':
        name = revit_name or u'current'
        return u"Revit's browser organisation ({0})".format(name)
    parts = []
    if org[u'source'] == u'custom' and org[u'levels']:
        parts.append(u' \u203a '.join(org[u'levels']))
    else:
        parts.append(u'No grouping')
    sort = org[u'sort'] or u'Name'
    parts.append(u'sorted by {0} {1}'.format(sort, u'\u2193' if org[u'desc'] else u'\u2191'))
    return u', '.join(parts)
