# -*- coding: utf-8 -*-
"""RevoBIM PY - Filter Manager : renaming and duplicate naming.

Pure Python - no Revit, no WPF - so every rule here is tested on the bench
rather than in a live model.
"""

import re

PARK_PREFIX = "~RevoBIM rename "


def transform(name, find="", replace="", match_case=False, prefix="", suffix=""):
    """Find and replace, then a prefix and a suffix, in that order."""
    out = name or ""
    find = find or ""
    replace = replace or ""

    if find:
        if match_case:
            out = out.replace(find, replace)
        else:
            pattern = re.compile(re.escape(find), re.IGNORECASE)
            out = pattern.sub(lambda _m: replace, out)

    return "{0}{1}{2}".format(prefix or "", out, suffix or "")


def plan(rows, existing, find="", replace="", match_case=False,
         prefix="", suffix=""):
    """Work out what every selected filter would be renamed to.

    rows      [(key, current name)] for the filters selected
    existing  every filter name in the project, the selected ones included

    Returns [(key, old, new, problem)]. A problem is a sentence, or "" when
    the row is fine. Nothing is written from here - the caller previews the
    whole list first, so a clash is flagged on its own row rather than
    failing halfway through the batch.
    """
    selected = [(key, name) for key, name in rows]
    selected_names = set(name.lower() for _key, name in selected)

    # what will still be called what once the selected ones have moved
    remaining = set()
    for name in existing:
        if name.lower() not in selected_names:
            remaining.add(name.lower())

    # every new name is worked out first, then judged. Doing it row by row
    # missed a collision with a row that was not itself being renamed: that
    # row was marked "unchanged" and skipped the clash test, and two filters
    # ended up with the same name.
    proposed = []
    for key, old in selected:
        proposed.append((key, old,
                         transform(old, find, replace, match_case,
                                   prefix, suffix)))

    tally = {}
    for _key, _old, new in proposed:
        low = new.lower()
        tally[low] = tally.get(low, 0) + 1

    results = []
    for key, old, new in proposed:
        low = new.lower()
        if not new.strip():
            problem = "the name would be empty"
        elif low in remaining:
            problem = "a filter is already called that"
        elif tally.get(low, 0) > 1:
            problem = "two of the selected filters would end up the same"
        elif new == old:
            problem = "unchanged"
        else:
            problem = ""
        results.append((key, old, new, problem))
    return results


def blocking(results):
    """The rows that would actually stop the batch."""
    return [r for r in results if r[3] and r[3] != "unchanged"]


def changing(results):
    """The rows that would really be renamed."""
    return [r for r in results if not r[3]]


def duplicate_name(base, taken):
    """'Name' -> 'Name (1)', then (2), (3) ... until one is free."""
    lower = set(str(t).lower() for t in taken)
    index = 1
    while True:
        candidate = "{0} ({1})".format(base, index)
        if candidate.lower() not in lower:
            return candidate
        index += 1


def parking_names(count, taken):
    """Names nothing else holds, to move through on the way to the real ones.

    A batch rename that swaps two names round, or shuffles a set along by
    one, clashes with itself if it is written in a single pass. Renaming
    everything to a parked name first and then to its real name removes the
    problem entirely.
    """
    lower = set(str(t).lower() for t in taken)
    out = []
    index = 1
    while len(out) < count:
        candidate = "{0}{1}".format(PARK_PREFIX, index)
        if candidate.lower() not in lower:
            out.append(candidate)
            lower.add(candidate.lower())
        index += 1
    return out
