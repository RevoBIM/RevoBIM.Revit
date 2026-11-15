# -*- coding: utf-8 -*-
"""RevoBIM PY - Workset Management : the Scope Boxes tab.

Every scope box in a table - Used, how many views and how many levels and
grids use it, and which - with batch rename and multi-delete staged in red
and written by Apply scope box changes.  Every read and write goes through
the main window's ExternalEvent runner.
"""

import wsm_clr  # noqa: F401  (assemblies first)

import wsm_core as core      # noqa: E402
import wsm_revit as revit    # noqa: E402
import wsm_table as table    # noqa: E402
import wsm_ui as ui          # noqa: E402

COLUMNS = [
    ("name", 2.4, 180, "WsNameText", u"Filter names"),
    ("used", 0.6, 70, "WsEditableText", u"Yes / No"),
    ("views", 0.6, 70, "WsCountText", u"e.g. >0"),
    ("datums", 0.8, 96, "WsCountText", u"e.g. =0"),
    ("usedby", 2.6, 200, "WsUsedByText", u"e.g. level 02"),
    ("change", 2.0, 160, "WsChangeText", u"Filter"),
]


def make_spec():
    return table.TableSpec(
        COLUMNS, core.SCOPE_TITLES, core.SCOPE_NUMERIC, core.SCOPE_TICK,
        value=core.scope_value,
        passes=core.scope_passes,
        tick_choices=core.scope_tick_choices,
        sort=core.scope_sort,
        change=core.scope_change_text,
        validate=core.scope_validate,
        tips={"usedby": core.scope_used_full})


class ScopeTab(object):

    def __init__(self, main):
        self.main = main
        self.window = main.window
        self.w = main.w
        self.loaded = False
        self.records = []
        self.table = table.GridTable(main, self.w("ScopeGrid"), make_spec(), self.refreshed)
        self.rename = table.RenamePanel(main, "Sc", self.table, u"scope box", self.staged)
        self.w("ScDeleteButton").Click += self.on_delete
        self.w("ScRevertButton").Click += self.on_revert_selected
        self.w("ScRevertAllButton").Click += self.on_revert_all
        self.w("ScClearFiltersButton").Click += self.on_clear_filters
        self.w("ScRefreshButton").Click += self.on_refresh
        self.w("ScApplyButton").Click += self.on_apply
        self.rename.update()

    # ---------------------------------------------------------- reading

    def ensure_loaded(self):
        if not self.loaded:
            self.request_read()

    def request_read(self, then=None):
        document = self.main.doc

        def work(uiapp):
            return revit.read_scope_boxes(document)

        def done(records):
            self.apply_read(records)
            if then is not None:
                then()
        self.main.run_job(u"read scope boxes", work, done, u"Reading scope boxes...")

    def apply_read(self, records):
        """Take a read in, keeping what is staged: renames and deletes by
        element id, for scope boxes still in the model."""
        old = dict((row.eid, row) for row in self.table.rows)
        rows = []
        for record in records:
            row = core.ScopeRow(record.eid, record.name, record.views, record.datums,
                                record.workset)
            before = old.get(record.eid)
            if before is not None:
                if before.renamed() and before.name != row.orig:
                    row.name = before.name
                if before.delete_to is not None:
                    row.delete_to = before.delete_to
            rows.append(row)
        self.records = records
        self.loaded = True
        self.table.set_rows(rows)
        self.rename.update()

    # ---------------------------------------------------------- state

    def plan(self):
        return core.scope_plan(self.table.rows)

    def staged_count(self):
        return core.scope_plan_count(self.plan()) + self.table.problems

    def refreshed(self):
        count = core.scope_plan_count(self.plan())
        self.w("ScApplyLabel").Text = (u"Apply scope box changes ({0})".format(count)
                                       if count else u"Apply scope box changes")
        self.w("ScApplyButton").IsEnabled = bool(count or self.table.problems)
        self.w("ScRevertAllButton").IsEnabled = any(row.staged() for row in self.table.rows)
        self.update_status()

    def update_status(self):
        if self.main.tab != "scope":
            return
        rows = self.table.rows
        if not self.loaded:
            self.main.status(u"Reading scope boxes...")
            return
        if not rows:
            self.main.status(u"This model has no scope boxes.")
            return
        unused = len([row for row in rows if not row.used()])
        shown = len(self.table.shown_keys())
        staged = len([row for row in rows if row.staged()])
        parts = [u"{0} scope boxes".format(len(rows)), u"{0} not used".format(unused)]
        if shown != len(rows):
            parts.append(u"{0} shown".format(shown))
        if staged:
            parts.append(u"{0} change{1} staged in red".format(staged, u"" if staged == 1 else u"s"))
        if self.table.problems:
            parts.append(u"{0} need a look".format(self.table.problems))
        self.main.status(u"   \u00B7   ".join(parts))

    def staged(self, count):
        self.main.status(u"{0} rename{1} staged in red - press Apply scope box changes to "
                         u"write them.".format(count, u"" if count == 1 else u"s"))

    # ---------------------------------------------------------- actions

    def on_delete(self, sender, args):
        self.table.commit_edits()
        keys = self.table.selected_keys()
        if not keys:
            self.main.status(u"Select the scope boxes to delete - Ctrl or Shift click for several.")
            return
        core.scope_stage_delete(self.table.rows, keys)
        self.table.refresh_states()
        used = [self.table.by_key[key] for key in keys if self.table.by_key[key].used()]
        note = u""
        if used:
            note = u" {0} of them are in use - those views and datums lose their scope box.".format(
                len(used))
        self.main.status(u"{0} scope box(es) staged for deletion in red.{1}".format(len(keys), note))

    def on_revert_selected(self, sender, args):
        self.table.commit_edits()
        keys = self.table.selected_keys()
        if not keys:
            self.main.status(u"Select the rows to revert - or use Revert all.")
            return
        self.table.set_rows(core.revert(self.table.rows, set(keys)))

    def on_revert_all(self, sender, args):
        self.table.commit_edits()
        self.table.set_rows(core.revert(self.table.rows))
        self.main.status(u"Every staged scope box change reverted.")

    def on_clear_filters(self, sender, args):
        self.table.clear_filters()

    def on_refresh(self, sender, args):
        self.request_read(then=lambda: self.main.status(
            u"Read the scope boxes again - staged changes kept."))

    def on_apply(self, sender, args):
        self.table.commit_edits()
        self.table.refresh_states()
        if self.table.problems:
            ui.message(self.window, u"Apply scope box changes",
                       [u"{0} row(s) need a look first - marked \u26A0 in the Change "
                        u"column:".format(self.table.problems), u""] +
                       [u"   {0}  -  {1}".format(row.name or row.orig, row.problem)
                        for row in self.table.rows if row.problem], 600, 360)
            return
        plan = self.plan()
        count = core.scope_plan_count(plan)
        if not count:
            self.main.status(u"Nothing staged.")
            return
        text = u"This writes the changes below to the model as one undo step."
        in_use = [item for item in plan["deletes"] if item["views"] or item["datums"]]
        if in_use:
            text += (u" {0} of the scope boxes being deleted are in use: those views, levels "
                     u"and grids go back to no scope box.".format(len(in_use)))
        if self.main.auto_editable():
            text += u" Anything that needs it is borrowed first."
        if not ui.confirm(self.window, u"Apply scope box changes", text,
                          core.scope_plan_lines(plan),
                          u"Apply {0} change{1}".format(count, u"" if count == 1 else u"s"),
                          u"Cancel", "WsRedButton" if plan["deletes"] else "WsGreenButton"):
            return
        document = self.main.doc
        auto = self.main.auto_editable()

        def work(uiapp):
            log = self.main.new_log()
            result = revit.apply_scope(document, plan, auto, log)
            log.write(header=u"Apply scope box changes")
            return result, revit.read_scope_boxes(document)

        def done(payload):
            result, records = payload
            self.apply_read(records)
            self.report(result)
        self.main.run_job(u"apply scope boxes", work, done, u"Writing the scope box changes...")

    def report(self, result):
        lines = [u"Deleted   {0}".format(name) for name in result["deleted"]]
        lines += [u"Renamed   {0}  ->  {1}".format(old, new) for old, new in result["renamed"]]
        if result["refused"] or result["error"]:
            lines.append(u"")
            lines.append(u"Not done - still staged in the table:")
            lines += [u"   {0}  -  {1}".format(what, why) for what, why in result["refused"]]
            if result["error"]:
                lines.append(u"   " + result["error"])
        show = core.to_text(self.main.settings.get("show_results"))
        if show == "always" or (show != "never" and (result["refused"] or result["error"])):
            ui.message(self.window, u"Scope box changes", lines or [u"Nothing changed."])
        done = len(result["deleted"]) + len(result["renamed"])
        self.main.status(u"{0} scope box change(s) written{1}.".format(
            done, u", {0} refused - still in red".format(len(result["refused"]))
            if result["refused"] else u""))
