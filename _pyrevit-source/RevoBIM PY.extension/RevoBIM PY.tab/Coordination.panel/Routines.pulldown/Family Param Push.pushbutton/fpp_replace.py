# -*- coding: utf-8 -*-
"""The Family Param - Replace tab. Holds no rules: those are in fpp_core, and
the work is in fpp_family."""
import fpp_clr  # noqa: F401  (must stay first)
from fpp_chrome import Table
import fpp_core
import fpp_dialogs
import fpp_family
import fpp_revit
from fpp_core import to_text


class ReplaceTab(object):
    def __init__(self, tool):
        self.tool = tool
        self.picks = fpp_core.ReplacePicks()
        self.focus = []
        self.shared = []
        self.shared_read = False
        self.source_params = []
        for name in ('combo_rcategory', 'txt_rsearch', 'txt_rcount',
                     'grid_rleft', 'grid_rright', 'grid_rsource',
                     'grid_rtarget', 'grid_rmaps', 'btn_rpush', 'btn_rback',
                     'btn_rmap', 'btn_runmap', 'btn_rreload', 'search_rsource',
                     'search_rtarget', 'txt_rfocus', 'txt_rfile'):
            setattr(self, name, tool.find(name))
        self.build()
        self.wire()

    def build(self):
        tool = self.tool
        tool.columns(self.grid_rleft, [
            tool.tree_column(u'Family', 3),
            tool.text_column(u'Category', 'cat', 1.3),
            tool.text_column(u'Placed', 'count', 0.5, 56)])
        tool.columns(self.grid_rright, [
            tool.tree_column(u'Family', 3),
            tool.text_column(u'Placed', 'count', 0.6, 56),
            tool.text_column(u'Mappings', 'note', 1, 96)])
        tool.columns(self.grid_rsource, [
            tool.text_column(u'Family parameter', 'name', 3, 120),
            tool.text_column(u'Applies to', 'scope', 1, 64),
            tool.text_column(u'Kind', 'kind', 1, 56),
            tool.text_column(u'Driven by', 'sample', 0.9, 60)])
        tool.columns(self.grid_rtarget, [
            tool.text_column(u'Shared parameter', 'name', 3, 120),
            tool.text_column(u'Group', 'scope', 1.4, 64),
            tool.text_column(u'Kind', 'kind', 1, 56)])
        tool.columns(self.grid_rmaps, [
            tool.text_column(u'Replace', 'source', 2, 120),
            tool.text_column(u'With shared parameter', 'target', 2, 120),
            tool.text_column(u'Project values', 'how', 2, 120),
            tool.text_column(u'Families', 'count', 0.6, 60)])
        tree = ['key', 'kind', 'text', 'cat', 'count', 'open', 'picked', 'note']
        param = ['key', 'name', 'scope', 'kind', 'origin', 'sample']
        self.left = Table(self.grid_rleft, tree)
        self.right = Table(self.grid_rright, tree)
        self.source = Table(self.grid_rsource, param, True)
        self.target = Table(self.grid_rtarget, param, True)
        self.maps = Table(self.grid_rmaps,
                          ['key', 'source', 'target', 'how', 'count'])

    def wire(self):
        safe = self.tool.safe
        self.combo_rcategory.SelectionChanged += safe(self.on_category)
        self.txt_rsearch.TextChanged += safe(self.on_search)
        self.search_rsource.TextChanged += safe(self.on_param_search)
        self.search_rtarget.TextChanged += safe(self.on_param_search)
        self.grid_rleft.SelectionChanged += safe(self.on_selection)
        self.grid_rright.SelectionChanged += safe(self.on_right_selection)
        self.grid_rsource.SelectionChanged += safe(self.on_selection)
        self.grid_rtarget.SelectionChanged += safe(self.on_selection)
        self.grid_rmaps.SelectionChanged += safe(self.on_selection)
        self.grid_rleft.MouseDoubleClick += safe(self.on_left_double)
        self.grid_rtarget.MouseDoubleClick += safe(self.on_map)
        self.btn_rpush.Click += safe(self.on_push)
        self.btn_rback.Click += safe(self.on_back)
        self.btn_rmap.Click += safe(self.on_map)
        self.btn_runmap.Click += safe(self.on_unmap)
        self.btn_rreload.Click += safe(self.tool.on_reload)

    # ----- opening -----
    def on_open(self):
        self.load_families()
        if self.shared_read:
            return
        def work(uiapp):
            return fpp_family.read_shared(uiapp.Application)
        def done(result, error):
            if error:
                self.tool.on_error(error)
                return
            self.shared_read = True
            path, self.shared = result
            self.txt_rfile.Text = path or u'No shared parameter file is set'
            if not self.shared:
                self.tool.set_status(
                    u'No shared parameters found. Set the shared parameter '
                    u'file in Revit, then press Reload.', True)
            self.fill_params()
        self.tool.submit(u'shared parameters', work, done)

    def editable(self):
        return [f for f in self.tool.families if f.editable]

    def load_families(self):
        tool = self.tool
        tool.suspend += 1
        chosen = to_text(self.combo_rcategory.SelectedItem)
        options = fpp_core.category_options(self.editable())
        self.combo_rcategory.Items.Clear()
        for name in options:
            self.combo_rcategory.Items.Add(name)
        self.combo_rcategory.SelectedItem = chosen if chosen in options \
            else options[0]
        tool.suspend -= 1
        self.refresh_left()

    def on_families(self):
        """After a reload: everything read from the model is read again."""
        self.shared_read = False
        self.picks.sync(self.tool.families)
        if self.tool.active == 'replace':
            self.on_open()
        self.refresh_right()
        self.after_right()

    # ----- left -----
    def refresh_left(self):
        tool = self.tool
        tool.suspend += 1
        rows = fpp_core.editable_rows(
            self.tool.families, to_text(self.combo_rcategory.SelectedItem),
            self.txt_rsearch.Text, self.picks)
        self.left.fill(rows)
        tool.suspend -= 1
        self.txt_rcount.Text = u'{0} famil{1}'.format(
            len(rows), u'y' if len(rows) == 1 else u'ies')
        self.update_buttons()

    def on_category(self, sender, args):
        if not self.tool.suspend:
            self.refresh_left()

    def on_search(self, sender, args):
        self.refresh_left()

    def on_selection(self, sender, args):
        if not self.tool.suspend:
            self.update_buttons()

    def on_left_double(self, sender, args):
        if self.left.keys():
            self.on_push(sender, args)

    def on_push(self, sender, args):
        lookup = dict([(f.key, f) for f in self.tool.families])
        added = [key[2:] for key in self.left.keys() if key[2:] in lookup]
        for fkey in added:
            self.picks.add(lookup[fkey])
        if not added:
            return
        self.grid_rleft.UnselectAll()
        self.refresh_left()
        self.refresh_right([u'f:' + k for k in added])
        self.after_right()

    def on_back(self, sender, args):
        self.picks.remove([key[2:] for key in self.right.keys()])
        self.grid_rright.UnselectAll()
        self.refresh_left()
        self.refresh_right()
        self.after_right()

    # ----- right -----
    def refresh_right(self, keep=None):
        tool = self.tool
        tool.suspend += 1
        self.right.fill(self.picks.rows(), keep)
        tool.suspend -= 1
        self.update_buttons()

    def on_right_selection(self, sender, args):
        if not self.tool.suspend:
            self.update_buttons()
            self.after_right()

    def after_right(self):
        self.focus = [k[2:] for k in self.right.keys()
                      if k[2:] in self.picks.items]
        names = [self.picks.items[k].fam.name for k in self.focus]
        if not names:
            self.txt_rfocus.Text = u'Select a family above to map its parameters'
        elif len(names) == 1:
            self.txt_rfocus.Text = names[0]
        else:
            self.txt_rfocus.Text = u'{0} families: what they share'.format(
                len(names))
        self.load_params()
        self.refresh_maps()

    def load_params(self):
        missing = [self.picks.items[k] for k in self.focus
                   if self.picks.items[k].params is None]
        if not missing:
            self.refresh_params()
            return
        self.tool.set_status(u'Opening families to read their parameters...')
        def work(uiapp):
            doc = self.tool.live_doc(uiapp)
            return [(p, fpp_family.read_family_params(doc, p)) for p in missing]
        def done(result, error):
            if error:
                self.tool.on_error(error)
                return
            for pick, found in result:
                pick.params = found
            self.tool.set_status(u'Ready.')
            self.refresh_params()
        self.tool.submit(u'family parameters', work, done)

    def refresh_params(self):
        lists = [self.picks.items[k].params for k in self.focus
                 if self.picks.items[k].params is not None]
        complete = len(lists) == len(self.focus)
        self.source_params = fpp_core.merge_params(lists if complete else [])
        self.fill_params()

    def fill_params(self):
        tool = self.tool
        tool.suspend += 1
        self.source.fill(fpp_core.source_rows(self.source_params,
                                              self.search_rsource.Text))
        self.target.fill(fpp_core.shared_rows(self.shared,
                                              self.search_rtarget.Text))
        tool.suspend -= 1
        self.update_buttons()

    def on_param_search(self, sender, args):
        self.fill_params()

    # ----- mappings -----
    def on_map(self, sender, args):
        src = self.tool.param_named(self.source_params, self.source.keys())
        tgt = self.tool.param_named(self.shared, self.target.keys())
        if src is None or tgt is None or not self.focus:
            return
        added, refusal = self.picks.add_mapping(self.focus, src, tgt)
        self.refresh_right(self.right.keys())
        self.refresh_maps()
        self.tool.set_status(
            refusal or u'Mapped {0} to {1}.'.format(src.name, tgt.name),
            bool(refusal))

    def on_unmap(self, sender, args):
        self.picks.remove_mappings(self.focus, self.maps.keys())
        self.refresh_right(self.right.keys())
        self.refresh_maps()

    def refresh_maps(self):
        tool = self.tool
        tool.suspend += 1
        self.maps.fill(self.picks.mapping_rows(self.focus), [])
        tool.suspend -= 1
        self.update_buttons()

    def update_buttons(self):
        self.btn_rpush.IsEnabled = bool(self.left.keys())
        self.btn_rback.IsEnabled = bool(self.right.keys())
        self.btn_rmap.IsEnabled = bool(self.source.keys()) \
            and bool(self.target.keys()) and bool(self.focus)
        self.btn_runmap.IsEnabled = bool(self.maps.keys())
        if self.tool.active == 'replace':
            count = self.picks.mapping_count()
            self.tool.btn_run.IsEnabled = count > 0 and not self.tool.busy
            self.tool.txt_run.Text = u'Replace ({0})'.format(count) if count \
                else u'Replace'

    def on_delete_key(self):
        if self.maps.keys():
            self.on_unmap(None, None)
        elif self.right.keys():
            self.on_back(None, None)

    # ----- run -----
    def on_run(self):
        tool = self.tool
        ready = self.picks.ready()
        if tool.busy or not ready:
            return
        text = (u'This edits {0} famil{1} and loads {2} back into the project. '
                u'Every placed value is kept and written to the new '
                u'parameter.\n\nSchedules, filters and tags that use an old '
                u'parameter will need pointing at the new one.\n\nSync first '
                u'if this is a workshared model.').format(
            len(ready), u'y' if len(ready) == 1 else u'ies',
            u'it' if len(ready) == 1 else u'them')
        if not fpp_dialogs.ask(tool, u'Replace family parameters?', text,
                               u'Replace'):
            return
        tool.start_job()
        picks = self.picks
        def work(uiapp):
            doc = tool.live_doc(uiapp)
            rep = fpp_family.run_replace(doc, uiapp.Application, picks,
                                         tool.on_progress)
            return rep, fpp_revit.read_model(doc)
        tool.submit(u'replace', work, self.on_done)

    def on_done(self, result, error):
        tool = self.tool
        tool.end_job()
        if error:
            tool.on_error(error)
            fpp_dialogs.tell(tool, u'Family Param - Replace', to_text(error),
                             error)
            return
        rep, families = result
        self.picks.remove(rep['done'])
        tool.families = families
        tool.picks.sync(families)
        tool.load_families()
        tool.refresh_left()
        tool.refresh_right()
        self.refresh_left()
        self.refresh_right()
        self.after_right()
        line = fpp_core.replace_status(rep)
        problems = fpp_core.replace_problem_lines(rep)
        fpp_core.log(tool.settings, line)
        for problem in problems:
            fpp_core.log(tool.settings, problem)
        tool.set_status(line, bool(problems))
        if problems:
            text = u'{0}\n\n{1}'.format(line, u'\n'.join(problems))
            fpp_dialogs.tell(tool, u'Needs a look', text, text)
