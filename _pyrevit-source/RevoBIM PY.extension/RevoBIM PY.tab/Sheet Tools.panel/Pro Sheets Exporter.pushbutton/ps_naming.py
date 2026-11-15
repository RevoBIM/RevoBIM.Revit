# -*- coding: utf-8 -*-
"""The custom file name engine.

There is no WPF and no Revit in this module. Every rule that decides what a
file ends up called is a plain function taking plain data, so the whole lot
can be run against a table of cases under CPython on the bench. That is the
single most valuable decision in a tool like this: nearly every naming bug is
findable here, and the ones that are not findable here are the ones that reach
the user.

A name is built from an **ordered list of rules**. Each rule is one parameter
plus a prefix, a suffix and a separator:

    prefix + value + suffix   then the separator, before the next segment

The separator belongs to the segment it **follows**, which is how the
reference tool does it and how the preview reads: Sheet Number with separator
``-`` then Sheet Name gives ``Sheet Number-Sheet Name``. The last rule's
separator is dropped, so a trailing ``-`` on the bottom row costs nothing.
"""

import re


# Windows forbids these outright in a file name.
ILLEGAL = u'\\/:*?"<>|'

# ...and reserves these whole names, with or without an extension.
RESERVED = set([
    'CON', 'PRN', 'AUX', 'NUL',
    'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
    'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9',
])

MAX_SEGMENT = 160


class Rule(object):
    """One row of the Custom File Name dialog."""

    __slots__ = ('param', 'prefix', 'suffix', 'separator')

    def __init__(self, param, prefix=u'', suffix=u'', separator=u''):
        self.param = u'{0}'.format(param or u'')
        self.prefix = u'{0}'.format(prefix or u'')
        self.suffix = u'{0}'.format(suffix or u'')
        self.separator = u'{0}'.format(separator or u'')

    def __repr__(self):
        return 'Rule({0!r}, {1!r}, {2!r}, {3!r})'.format(
            self.param, self.prefix, self.suffix, self.separator)

    def __eq__(self, other):
        if not isinstance(other, Rule):
            return False
        return (self.param == other.param and self.prefix == other.prefix
                and self.suffix == other.suffix
                and self.separator == other.separator)

    def __ne__(self, other):
        return not self.__eq__(other)


def rules_from_store(store, prefix_key='name'):
    """Read the ordered rules out of a profile dictionary.

    Rules are numbered from 1. A gap in the numbering is stepped over rather
    than treated as the end, so a hand-edited profile file that deletes rule 2
    still loads rules 1 and 3.
    """
    try:
        count = int(float(store.get(prefix_key + '.rule_count', 0) or 0))
    except Exception:
        count = 0
    if count <= 0:
        # No count written. Probe forward a reasonable distance anyway.
        count = 40
    rules = []
    for index in range(1, count + 1):
        base = u'{0}.rule.{1}.'.format(prefix_key, index)
        param = store.get(base + 'param')
        if param is None or not u'{0}'.format(param).strip():
            continue
        rules.append(Rule(param,
                          store.get(base + 'prefix', u''),
                          store.get(base + 'suffix', u''),
                          store.get(base + 'sep', u'')))
    return rules


def rules_to_store(rules, store, prefix_key='name'):
    """Write the rules back into a profile dictionary, clearing old numbers."""
    stale = [key for key in store.keys()
             if key.startswith(prefix_key + '.rule.')]
    for key in stale:
        try:
            del store[key]
        except Exception:
            pass
    store[prefix_key + '.rule_count'] = u'{0}'.format(len(rules))
    for index, rule in enumerate(rules, 1):
        base = u'{0}.rule.{1}.'.format(prefix_key, index)
        store[base + 'param'] = rule.param
        store[base + 'prefix'] = rule.prefix
        store[base + 'suffix'] = rule.suffix
        store[base + 'sep'] = rule.separator
    return store


def default_rules(mode='sheets'):
    """Sheet Number, a hyphen, Sheet Name - what most registers want.

    Views have no number worth a file name, so Views mode starts from the
    view's own name instead.
    """
    if mode == 'views':
        return [Rule(u'View Name')]
    return [Rule(u'Sheet Number', separator=u'-'), Rule(u'Sheet Name')]


# Sheets keep the original ``name.`` keys so a template written before 1.55.0
# still opens with its naming; views get keys of their own.
MODE_KEYS = {'sheets': 'name', 'views': 'vname'}


def mode_key(mode):
    return MODE_KEYS.get(mode, 'name')


def _has_rules(store, prefix_key):
    marker = prefix_key + '.rule'
    for key in store.keys():
        if u'{0}'.format(key).startswith(marker):
            return True
    return False


def rules_by_mode(store):
    """Both naming sets out of a profile, as {'sheets': [...], 'views': [...]}.

    A profile from before 1.55.0 holds one set used for both. Sheets keep it.
    Views keep it too when somebody had changed it from the stock sheet name -
    that was their naming for views as much as sheets - and otherwise start
    from the view name.
    """
    store = store or {}
    sheets = rules_from_store(store, mode_key('sheets')) \
        or default_rules('sheets')
    if _has_rules(store, mode_key('views')):
        views = rules_from_store(store, mode_key('views')) \
            or default_rules('views')
    elif sheets != default_rules('sheets'):
        views = [Rule(rule.param, rule.prefix, rule.suffix, rule.separator)
                 for rule in sheets]
    else:
        views = default_rules('views')
    return {'sheets': sheets, 'views': views}


def store_rules_by_mode(sets, store):
    """Write both naming sets into a profile."""
    for mode in ('sheets', 'views'):
        rules = (sets or {}).get(mode) or default_rules(mode)
        rules_to_store(rules, store, mode_key(mode))
    return store


def build_segments(rules, lookup):
    """Every rule turned into (text, separator), with empties dropped.

    ``lookup`` takes a parameter name and gives back its value as text, or an
    empty string where the parameter is missing or blank on this sheet.

    A rule whose value is empty **and** which carries no prefix or suffix
    contributes nothing at all - not even its separator. Without that, a sheet
    with no revision yet comes out as ``1101--CONTAINMENT`` and the run of
    separators looks like a bug in the tool rather than an empty parameter.
    """
    out = []
    for rule in rules:
        try:
            value = lookup(rule.param)
        except Exception:
            value = u''
        value = u'' if value is None else u'{0}'.format(value).strip()
        if not value and not rule.prefix and not rule.suffix:
            continue
        out.append((rule.prefix + value + rule.suffix, rule.separator))
    return out


def join_segments(segments):
    """Join (text, separator) pairs, dropping the last separator."""
    if not segments:
        return u''
    parts = []
    for index, pair in enumerate(segments):
        text, separator = pair
        parts.append(text)
        if index < len(segments) - 1:
            parts.append(separator)
    return u''.join(parts)


def sanitise(text, fallback=u'unnamed'):
    """A string Windows will accept as one path segment.

    Illegal characters become underscores rather than disappearing, because a
    silently shortened name is harder to spot than an obviously substituted
    one. Trailing dots and spaces go, since Windows drops them anyway and a
    name the tool reports is not the name that ends up on disk.
    """
    value = u'' if text is None else u'{0}'.format(text)
    out = []
    for ch in value:
        if ch in ILLEGAL or ord(ch) < 32:
            out.append(u'_')
        else:
            out.append(ch)
    value = u''.join(out).strip()
    value = value.rstrip(u'. ')
    value = re.sub(u'_{3,}', u'__', value)
    if not value:
        return fallback
    if value.split(u'.')[0].upper() in RESERVED:
        value = u'_' + value
    if len(value) > MAX_SEGMENT:
        value = value[:MAX_SEGMENT].rstrip(u'. ')
    return value or fallback


def build_name(rules, lookup, fallback=u'unnamed'):
    """The finished, sanitised file name for one sheet or view."""
    if not rules:
        return sanitise(lookup(u'Sheet Number') or u'', fallback)
    return sanitise(join_segments(build_segments(rules, lookup)), fallback)


def preview(rules):
    """The Custom Name Preview line, using parameter names as sample values.

    Deliberately unsanitised - this is showing the shape of the name, and
    substituting an underscore for a character the user has just typed reads
    as the tool refusing it rather than warning about it.
    """
    segments = []
    for rule in rules:
        segments.append((rule.prefix + rule.param + rule.suffix, rule.separator))
    text = join_segments(segments)
    return text or u'(nothing chosen)'


def unique_names(pairs):
    """Make every name in a list unique, keeping the first of each clash.

    ``pairs`` is a list of (key, name). Returns a list of (key, name) in the
    same order, where a repeated name gains `` (2)``, `` (3)`` and so on.

    This matters more than it looks: two sheets whose chosen parameters happen
    to match would otherwise export one file and silently overwrite it with
    the other, and the count at the end would still say two.
    """
    seen = {}
    out = []
    for key, name in pairs:
        base = u'{0}'.format(name)
        lowered = base.lower()
        if lowered not in seen:
            seen[lowered] = 1
            out.append((key, base))
            continue
        count = seen[lowered] + 1
        candidate = u'{0} ({1})'.format(base, count)
        while candidate.lower() in seen:
            count += 1
            candidate = u'{0} ({1})'.format(base, count)
        seen[lowered] = count
        seen[candidate.lower()] = 1
        out.append((key, candidate))
    return out


def clashes(pairs):
    """Which names in a list of (key, name) collide, as {name: [keys]}."""
    buckets = {}
    for key, name in pairs:
        buckets.setdefault(u'{0}'.format(name).lower(), []).append(key)
    return dict([(name, keys) for name, keys in buckets.items()
                 if len(keys) > 1])
