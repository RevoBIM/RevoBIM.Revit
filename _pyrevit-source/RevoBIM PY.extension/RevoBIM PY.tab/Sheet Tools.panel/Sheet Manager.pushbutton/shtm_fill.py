# -*- coding: utf-8 -*-
"""Fill, series, unique sequences and duplicates - the rules, with no WPF.

Taken from the RevoBIM table reference, which took them from Excel for Revit,
where every one of these was found wrong at least once:

- a hyphen in a tag is not a minus sign: AHU-1 stepped is AHU-2, not AHU0
- do not invent padding: AHU-10 steps to AHU-9, not AHU-09; SD-005 keeps its
  zeros because the seed actually starts with one
- the rightmost number is the counter: L01-P-1 steps to L01-P-3, not L02-P-1
"""

import shtm_clr  # noqa: F401  - references the assemblies first

import re

import shtm_core

_NUMBER = re.compile(r"(?:(?<=^)|(?<=\s))-?\d+|\d+")


def split_number(text):
    """(before, number text, after) for the rightmost number in the text, or
    None. A minus counts as a sign only at the start of the value or after a
    space - anywhere else it is a hyphen and belongs to the text."""
    text = u"{0}".format(text if text is not None else u"")
    last = None
    for match in _NUMBER.finditer(text):
        last = match
    if last is None:
        return None
    return text[:last.start()], last.group(0), text[last.end():]


def series_value(seed, step, count):
    """The seed stepped `count` times by `step`, keeping the seed's own
    padding only when it has some."""
    parts = split_number(seed)
    if parts is None:
        return seed
    before, number, after = parts
    value = int(number) + step * count
    digits = number.lstrip(u"-")
    padded = digits.startswith(u"0") and len(digits) > 1
    if padded:
        body = u"{0:0{1}d}".format(abs(value), len(digits))
    else:
        body = u"{0}".format(abs(value))
    sign = u"-" if value < 0 else u""
    return u"{0}{1}{2}{3}".format(before, sign, body, after)


def infer_step(seeds):
    """The step between several seeds, when they form an even series on the
    same text; None when they do not."""
    if len(seeds) < 2:
        return None
    parsed = [split_number(seed) for seed in seeds]
    if any(part is None for part in parsed):
        return None
    before, _n, after = parsed[0]
    for other in parsed[1:]:
        if other[0] != before or other[2] != after:
            return None
    numbers = [int(part[1]) for part in parsed]
    gaps = [numbers[i + 1] - numbers[i] for i in range(len(numbers) - 1)]
    if len(set(gaps)) != 1:
        return None
    return gaps[0]


def fill_plan(seeds, count, downward=True):
    """What `count` cells get when the selection is filled from `seeds`.

    | seeds                        | result                              |
    | no number in it              | copied                              |
    | a number in it               | stepped, in the direction of the fill |
    | several with an even gap     | that gap is kept                    |
    | several with no series       | repeated as a block                 |
    """
    seeds = [u"{0}".format(s if s is not None else u"") for s in seeds]
    if not seeds or count <= 0:
        return []
    direction = 1 if downward else -1
    if len(seeds) == 1:
        seed = seeds[0]
        if split_number(seed) is None:
            return [seed] * count
        return [series_value(seed, direction, i + 1) for i in range(count)]
    step = infer_step(seeds)
    if step is None:
        return [seeds[i % len(seeds)] for i in range(count)]
    last = seeds[-1] if downward else seeds[0]
    return [series_value(last, step * direction, i + 1) for i in range(count)]


def fill_series(seeds, count, downward=True):
    """Excel's Ctrl+E: like fill_plan but a lone value with no number gets one
    appended and steps from there rather than being copied."""
    seeds = [u"{0}".format(s if s is not None else u"") for s in seeds]
    if len(seeds) == 1 and split_number(seeds[0]) is None:
        seed = seeds[0]
        joiner = u"" if not seed or seed[-1] in u" -_." else u" "
        base = u"{0}{1}1".format(seed, joiner)
        return [series_value(base, 1 if downward else -1, i) for i in range(count)]
    return fill_plan(seeds, count, downward)


def unique_sequence(values, taken):
    """Renumber `values` so none clashes with `taken` or with each other,
    counting on the rightmost number and keeping the padding. A value with no
    number gets one appended rather than being left clashing; a value already
    unique is left alone.

    Returns a list of (old, new) in the input order."""
    used = set([u"{0}".format(t).strip().lower() for t in taken])
    out = []
    for value in values:
        value = u"{0}".format(value if value is not None else u"")
        key = value.strip().lower()
        if key and key not in used:
            used.add(key)
            out.append((value, value))
            continue
        if split_number(value) is None:
            joiner = u"" if not value or value[-1] in u" -_." else u" "
            candidate = u"{0}{1}1".format(value, joiner)
        else:
            candidate = series_value(value, 1, 1)
        guard = 0
        while candidate.strip().lower() in used and guard < 100000:
            candidate = series_value(candidate, 1, 1)
            guard += 1
        used.add(candidate.strip().lower())
        out.append((value, candidate))
    return out


def duplicate_groups(values):
    """The values that appear more than once, each with the indexes it
    appears at. Blanks are not duplicates - an empty cell repeated forty times
    drowns the real clashes. Case-insensitive, whitespace trimmed."""
    seen = {}
    order = []
    for index, value in enumerate(values):
        key = u"{0}".format(value if value is not None else u"").strip().lower()
        if not key:
            continue
        if key not in seen:
            seen[key] = []
            order.append(key)
        seen[key].append(index)
    return [(key, seen[key]) for key in order if len(seen[key]) > 1]


def parse_block(text):
    """Tab-separated lines, as Excel puts them on the clipboard, into rows."""
    text = u"{0}".format(text if text is not None else u"")
    text = text.replace(u"\r\n", u"\n").replace(u"\r", u"\n")
    if text.endswith(u"\n"):
        text = text[:-1]
    if not text:
        return []
    return [line.split(u"\t") for line in text.split(u"\n")]


def to_block(rows):
    return u"\r\n".join([u"\t".join([u"{0}".format(c if c is not None else u"")
                                     for c in row]) for row in rows])


def paste_plan(block, targets, columns, data_rows=None):
    """Where a pasted block lands.

    `targets` is the list of (sheet, column) the user has selected, in table
    order; `columns` the table's column order; `data_rows` the sheets in table
    order with the group headings already left out.

    One value goes into every selected cell. A block goes from the top-left
    selected cell across and down over the data rows that follow it - the
    whole block, however big the selection, as Excel does it. Decoration rows
    are not in `data_rows`, so a heading cannot eat a value.

    Returns a list of (sheet, column, value).
    """
    if not block or not targets:
        return []
    if len(block) == 1 and len(block[0]) == 1:
        value = block[0][0]
        return [(sheet, column, value) for sheet, column in targets]
    anchor_sheet, anchor_column = targets[0]
    if data_rows is None:
        data_rows = []
        for sheet, _column in targets:
            if not data_rows or data_rows[-1] is not sheet:
                data_rows.append(sheet)
    try:
        start_row = [i for i, sheet in enumerate(data_rows)
                     if sheet is anchor_sheet][0]
    except IndexError:
        return []
    start_column = columns.index(anchor_column) if anchor_column in columns else 0
    out = []
    for row_offset, line in enumerate(block):
        row_index = start_row + row_offset
        if row_index >= len(data_rows):
            break
        sheet = data_rows[row_index]
        for offset, value in enumerate(line):
            column_index = start_column + offset
            if column_index >= len(columns):
                break
            out.append((sheet, columns[column_index], value))
    return out


def natural_sorted(values):
    return sorted(values, key=shtm_core.natural_key)
