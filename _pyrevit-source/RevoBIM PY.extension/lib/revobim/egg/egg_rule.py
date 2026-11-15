# -*- coding: utf-8 -*-
"""A rule to paste into each tool's own import_check.py.

The point of "map the egg on every rebuild" is that it stops being something to
remember. Copy this function into a tool's bench check and add it to that tool's
RULES list, and a rebuild that forgets the egg fails on the bench instead of
shipping without it.

    from egg_rule import rule_easter_egg_wired   # if lib is on sys.path
    RULES.append(rule_easter_egg_wired)

or just paste the function body in - it depends on nothing.
"""

import re


def rule_easter_egg_wired(report, texts, xaml=None):
    """The tool attaches the egg to a named logo element.

    `egg_hook.attach_to_window(window)` is the call to prefer: it finds the logo
    itself, so there is no name to get wrong and nothing here to check beyond
    the call being made at all.

    Where a tool uses the older `attach(element)` form, three things are checked
    rather than one, because any of them alone passes while the egg quietly does
    nothing:

    1. some module calls egg_hook.attach
    2. the element it attaches to is fetched by name
    3. that name exists as an x:Name in a layout file

    `texts` is [(filename, source)] as the other rules take it. `xaml` is
    [(filename, source)] for the layout files; leave it off for a tool whose
    window is built in code and only the first two are checked.
    """
    call = None
    whole_window = False
    for name, text in texts:
        if re.search(r"egg_hook\s*\.\s*attach_to_window\s*\(", text):
            call = (name, text)
            whole_window = True
            break
        if re.search(r"egg_hook\s*\.\s*attach\s*\(", text):
            call = (name, text)
            break
    if call is None:
        raise Exception("no module calls egg_hook.attach_to_window - the "
                        "easter egg is not wired to this tool's logo")

    if whole_window:
        # attach_to_window finds the logo itself, so there is no name to check
        # and nothing for a renamed element to break.
        report.append("easter egg: attach_to_window in {0}".format(call[0]))
        return

    names = re.findall(r'FindName\(\s*["\']([\w]+)["\']\s*\)', call[1])
    if not names:
        raise Exception("{0} calls egg_hook.attach but fetches no element by "
                        "name".format(call[0]))

    if xaml is None:
        report.append("easter egg: attached in {0}".format(call[0]))
        return

    declared = set()
    for name, text in xaml:
        for found in re.finditer(r'x:Name\s*=\s*["\']([\w]+)["\']', text):
            declared.add(found.group(1))

    wired = [item for item in names if item in declared]
    if not wired:
        raise Exception(
            "{0} attaches the egg to {1}, which no layout declares as an "
            "x:Name".format(call[0], ", ".join(sorted(set(names)))))

    report.append("easter egg: attached in {0} to {1}".format(
        call[0], ", ".join(sorted(set(wired)))))
