# -*- coding: utf-8 -*-

"""Legend Creator - a run, start to finish."""

import os

from pyrevit import forms, revit, script

from lgc_logic import (CASE_ASIS, CASE_CAMEL, CASE_UPPER, THEME_AUTO,
                       format_mm, grouped_entries)
from lgc_core import (_DEBUG, _TRACE, eid_value, load_settings, log,
                      reset_trace, start_debug)
from lgc_model import (element_name, find_seed_legend, find_seed_legend_view,
                       project_phases, taken_view_names, text_note_types)
from lgc_build import (_DIALOGS, open_view, reveal_in_browser, run_batch,
                       run_system, suppress_dialogs)
from lgc_theme import resolve_theme
from lgc_windows import CategoryPicker, DoneWindow
from lgc_report import show_debug_report

# The active document, bound by lgc_app.bind_document() at the start of every
# run - never captured at import, which pyRevit may cache across runs and
# models.
doc = None


def finish(view, legends, components, skipped, opts, folder):
    """After the run: the summary, its question, then the browser.

    Everything here happens with every transaction closed - the active view
    cannot change inside one - and after the summary has gone, since a modal
    window and a view switch do not mix.
    """
    window = DoneWindow(os.path.join(folder, 'LegendCreatorDone.xaml'),
                        legends, components, skipped, opts['scale'],
                        opts['theme'],
                        element_name(view) if view is not None else '',
                        opts.get('debug'))
    window.show_dialog()
    if view is None:
        return

    if window.open_requested:
        log(u'opened {0}: {1}'.format(
            element_name(view),
            'yes' if open_view(view) else 'no - open it by hand'))
    else:
        log(u'not opened - user chose Not now')
    reveal_in_browser(view)


def report_system(opts, view, placed, skipped, notes, template_notes):
    log('')
    log('=== System Colour Legend - {0} ==='.format(opts['kind']['label']))
    log('scale 1:{0}, text {1}, heading {2}'.format(
        opts['scale'], opts['text_type_name'], opts['head_type_name']))
    log('swatches {0} x {1}mm, pitch {2}mm, text {3}mm clear, '
        'line weight {4}'.format(
            format_mm(opts['swatch_w']), format_mm(opts['swatch_h']),
            format_mm(opts['row_pitch']), format_mm(opts['text_gap']),
            opts['line_weight']))
    if view is not None:
        log('{0} - {1} swatch(es)'.format(element_name(view), placed))
    else:
        log('failed')
    for note in list(notes) + list(template_notes):
        log('   {0}'.format(note))
    for label, reason in skipped:
        log('   skipped {0} - {1}'.format(label, reason))
    if _DIALOGS['seen']:
        log('   Revit dialogs answered: {0}'.format(
            ', '.join(sorted(set(_DIALOGS['seen'])))))


def bind_document(document):
    """Point every module that reads the model at this run's document."""
    import lgc_app, lgc_build, lgc_model, lgc_report
    for module in (lgc_app, lgc_build, lgc_model, lgc_report):
        module.doc = document


def main():
    reset_trace()
    bind_document(revit.doc)
    log(u'start')
    settings = load_settings()
    # Debug follows the saved tick from the very first line, so a failure
    # before the window opens is still written down.
    start_debug(settings.get('debug', '0') == '1')
    theme_name = resolve_theme(settings.get('theme_mode', THEME_AUTO))
    _TRACE['theme'] = theme_name
    log(u'theme mode {0} -> {1}'.format(settings.get('theme_mode'), theme_name))

    if doc is None or doc.IsFamilyDocument:
        log(u'stopped: no project document')
        forms.alert('Open a project document and try again.',
                    title='RevoBIM - Legend Creator', exitscript=True)
    log(u'document: {0}'.format(doc.Title))

    # The family tab needs a legend component to clone; the system tab only
    # needs somewhere to draw, so a bare legend view is enough for it.
    seed_view, seed_component = find_seed_legend()
    any_legend = seed_view or find_seed_legend_view()
    log(u'seed legend with a component: {0}; any legend: {1}'.format(
        element_name(seed_view) if seed_view else u'none',
        element_name(any_legend) if any_legend else u'none'))
    if any_legend is None:
        forms.alert(
            'Legend Creator needs at least one existing legend view.\n\n'
            'The Revit API cannot create a legend view from scratch, so the '
            'tool duplicates one. Make an empty legend view and run it '
            'again.\n\n'
            'The Family Legend tab additionally needs that legend to hold '
            'one legend component, since components cannot be created from '
            'nothing either - drag any family type into it from the Project '
            'Browser.',
            title='RevoBIM - Legend Creator', exitscript=True)

    text_types = text_note_types()
    log(u'text note types: {0}'.format(len(text_types)))
    if not text_types:
        forms.alert('This project has no text note type available.',
                    title='RevoBIM - Legend Creator', exitscript=True)

    folder = os.path.dirname(__file__)
    phases = project_phases()
    log(u'phases: {0}'.format(u', '.join(
        u'{0} (id {1})'.format(n, eid_value(i)) for n, i in phases)))
    log(u'building the window')
    window = CategoryPicker(os.path.join(folder, 'LegendCreatorWindow.xaml'),
                            phases, text_types, settings,
                            family_ready=seed_view is not None)
    log(u'window built, showing it')
    window.show_dialog()
    _TRACE['theme'] = getattr(window, 'theme_name', theme_name)

    debug_now = bool(window.debug_cb.IsChecked)
    start_debug(debug_now)
    if not debug_now:
        _DEBUG['on'] = False

    if not window.result:
        log(u'window closed without creating')
        if debug_now:
            show_debug_report(u'Debug is ticked and the window was closed '
                              u'without creating anything',
                              _TRACE['theme'])
        script.exit()

    opts = window.opts
    log(u'creating: tab {0}, {1} item(s)'.format(window.mode,
                                                len(window.result)))
    taken = taken_view_names()
    suppress_dialogs(True)
    try:
        run_everything(window, opts, taken, folder, seed_view,
                       seed_component, any_legend)
    finally:
        suppress_dialogs(False)

    if debug_now:
        show_debug_report(u'Debug is ticked', _TRACE['theme'])


def run_everything(window, opts, taken, folder, seed_view, seed_component,
                   any_legend):
    if window.mode == 'system':
        opts['groups'] = grouped_entries(window.result, opts['kind'])
        view, placed, skipped, notes = run_system(
            window.result, opts, any_legend, taken)
        report_system(opts, view, placed, skipped, notes, window.sys_notes)
        finish(view, 1 if view is not None else 0, placed,
               len(skipped) + len(window.sys_notes), opts, folder)
        return

    if seed_view is None:
        forms.alert(
            'The Family Legend tab needs an existing legend view holding at '
            'least one legend component, which this project has not got.\n\n'
            'Drag any family type into a legend view from the Project '
            'Browser, then run it again.',
            title='RevoBIM - Legend Creator', exitscript=True)

    results = run_batch(window.result, opts, seed_view, seed_component,
                        taken)

    case_label = {CASE_ASIS: 'as written',
                  CASE_UPPER: 'UPPERCASE',
                  CASE_CAMEL: 'Camel Case'}[opts['text_case']]
    log('')
    log('=== Family Legend ===')
    log('scale 1:{0}, phase {1}, text from {2} ({3}), style {4}'.format(
        opts['scale'], opts['phase'], opts['name_param'], case_label,
        opts['text_type_name']))
    log('rows {0}mm, text {1}mm right, columns {2}mm'.format(
        format_mm(opts['row_spacing']), format_mm(opts['text_offset']),
        format_mm(opts['column_spacing'])))

    for name, view, count, skipped in results:
        if view is None:
            log('{0} - failed'.format(name))
        else:
            log('{0} - {1} component(s)'.format(element_name(view), count))
        for label, reason in skipped:
            log('   skipped {0} - {1}'.format(label, reason))
    if _DIALOGS['seen']:
        log('   Revit dialogs answered: {0}'.format(
            ', '.join(sorted(set(_DIALOGS['seen'])))))

    made = [r for r in results if r[1] is not None]
    finish(made[0][1] if made else None, len(made),
           sum(r[2] for r in made), sum(len(r[3]) for r in results),
           opts, folder)
