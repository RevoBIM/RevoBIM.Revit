# -*- coding: utf-8 -*-
"""The door other RevoBIM tools use to run Tag Tidy on tags they have just
placed - Tag All, after a Family Tags run.

A caller adds the Tag Tidy.pulldown folder to sys.path, imports this module,
checks HOOK_VERSION, and calls tidy_tags() from inside its own API context
(an ExternalEvent or a command) and its own TransactionGroup, so Tag All and
Tag Tidy come out as one undo step.  No window opens and nothing is picked:
the saved Tag Tidy settings are used, with whatever the caller overrides.

This module is the whole contract.  Everything behind it can change; what is
here only grows, and HOOK_VERSION goes up when it changes in a way a caller
would need to know about.
"""

import tidy_clr  # noqa: F401  assemblies first

import traceback

import tidy_core as core
import tidy_ops as ops

HOOK_VERSION = 1
TOOL_VERSION = core.__version__

# What a caller may override for one call.  Anything else is ignored, so a
# caller can never switch the preview window back on from inside its run.
OVERRIDABLE = ("side", "leg_angle", "no_leader", "pinned", "leader_end", "keep_single",
               "second_column", "include_spatial_tags", "debug")


def settings(overrides=None):
    """The saved Tag Tidy settings with a caller's overrides on top."""
    cfg = core.load_settings()
    for key, value in (overrides or {}).items():
        if key in OVERRIDABLE and key in core.DEFAULTS:
            choices = core.CHOICES.get(key)
            if choices is None or value in choices:
                cfg[key] = value
    cfg["preview"] = "never"
    cfg["prompt_when_empty"] = "0"
    return cfg


def tidy_tags(doc, tag_ids, overrides=None):
    """Tidy the given tags, view by view, with no window.

    Returns a dict, never raises:
      ok       - False only when the tidy itself failed
      summary  - one line, as Tag Tidy's own preview would head it
      moved, kept, columns, look - counts (look: rows that need a look)
      rows     - [(kind, label, note)], kind done | clash | skip | fail
      error    - the reason when ok is False
    """
    answer = {"ok": True, "summary": u"", "moved": 0, "kept": 0, "columns": 0, "look": 0,
              "rows": [], "error": u""}
    try:
        tags = []
        for tag_id in tag_ids or []:
            element = doc.GetElement(tag_id)
            if element is not None:
                tags.append(element)
        if not tags:
            answer["summary"] = u"nothing to tidy"
            return answer
        result = ops.tidy_headless(doc, tags, settings(overrides))
        answer.update({"summary": result.summary, "moved": result.moved, "kept": result.kept,
                       "columns": result.columns, "look": result.look, "rows": list(result.rows)})
    except Exception as error:
        answer["ok"] = False
        answer["error"] = u"{0}".format(error)
        try:
            core.write_debug(core.load_settings(), [u"tidy_tags failed:", traceback.format_exc()])
        except Exception:
            pass
    return answer
