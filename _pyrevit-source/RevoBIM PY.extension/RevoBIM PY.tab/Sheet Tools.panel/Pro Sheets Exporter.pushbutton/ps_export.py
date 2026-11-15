# -*- coding: utf-8 -*-
"""The export engine: PDF (Revit's own or a printer) and DWG.

Two things shape everything in here.

**Nothing about the Revit API is assumed to exist.** Between 2024 and 2027 the
export options classes gain properties, lose properties and rename enum
members, and an attribute that is not there throws at the moment it is set -
halfway through configuring an export, with the user watching. So every option
goes through ``set_opt`` and every enum member through ``enum_member``, both of
which skip quietly and record what they skipped. A release that cannot honour
"hide scope boxes" still exports; it just says so in the report.

**A void call is not evidence.** Revit's export and print calls return nothing
useful and do not reliably raise when a file does not appear. Every job is
confirmed by looking for the file on disk afterwards, and the count reported at
the end is the count of files that exist - not the count of calls that did not
throw.
"""

import ps_refs  # noqa: F401  - must be first

import os
import re
import time

from System.Collections.Generic import List

from Autodesk.Revit.DB import (
    ElementId, Transaction, ViewSet,
)

import ps_paths


# ==========================================================================
# defensive access to an API that moves between releases
# ==========================================================================

def set_opt(target, names, value, log=None):
    """Set the first property of ``names`` that exists on ``target``.

    ``names`` may be one name or several spellings of the same idea - the
    print API and the PDF API disagree about capitalisation in a few places
    (``ViewLinksinBlue`` against ``ViewLinksInBlue``) and there is no value in
    finding that out at the user's desk.
    """
    if isinstance(names, str):
        names = [names]
    for name in names:
        if not hasattr(target, name):
            continue
        try:
            setattr(target, name, value)
            return True
        except Exception as err:
            if log is not None:
                log.append(u'could not set {0}: {1}'.format(name, err))
            return False
    if log is not None:
        log.append(u'not available on this release: {0}'.format(names[0]))
    return False


def enum_member(type_name, *members):
    """The first member of a DB enum that exists, or None.

    The enum type itself may be missing on a release, which is why the type is
    looked up by name rather than imported at the top of the module - an
    import of a name that is not there kills the whole module at load.
    """
    try:
        from Autodesk.Revit import DB
    except Exception:
        return None
    enum_type = getattr(DB, type_name, None)
    if enum_type is None:
        return None
    for member in members:
        found = getattr(enum_type, member, None)
        if found is not None:
            return found
    return None


def id_list(element_ids):
    typed = List[ElementId]()
    for element_id in element_ids:
        typed.Add(element_id)
    return typed


# ==========================================================================
# suppressing Revit's own dialogs
#
# Two things have to be handled and they are different: a TaskDialog that
# pops up mid-run, and a failure posted against the transaction. The first
# is answered through DialogBoxShowing, the second deleted by an
# IFailuresPreprocessor.
#
# The handler is hooked ONCE and switched with a flag. Unsubscribing an
# IronPython bound method from a .NET event is not reliable - each attribute
# access makes a fresh delegate, so the -= silently removes nothing and the
# handlers pile up run after run.
# ==========================================================================

SUPPRESS_ON = False
_dialog_hooked = False
_suppressed = []


def _on_dialog_showing(sender, args):
    if not SUPPRESS_ON:
        return
    try:
        shown = u'{0}'.format(args.DialogId)
    except Exception:
        shown = u'?'
    for member in ('Close', 'Cancel', 'Ok', 'OK', 'Yes', 'No'):
        try:
            from Autodesk.Revit.UI import TaskDialogResult
            answer = getattr(TaskDialogResult, member, None)
            if answer is None:
                continue
            args.OverrideResult(int(answer))
            _suppressed.append(shown)
            debug(u'suppressed Revit dialog "{0}" with {1}'.format(shown, member))
            return
        except Exception:
            continue
    try:
        args.OverrideResult(1)
        _suppressed.append(shown)
        debug(u'suppressed Revit dialog "{0}"'.format(shown))
    except Exception:
        pass


def hook_dialogs(uiapp):
    """Hook DialogBoxShowing once for the life of the session."""
    global _dialog_hooked
    if _dialog_hooked:
        return True
    try:
        uiapp.DialogBoxShowing += _on_dialog_showing
        _dialog_hooked = True
        return True
    except Exception:
        return False


def begin_suppression(uiapp):
    global SUPPRESS_ON
    del _suppressed[:]
    hook_dialogs(uiapp)
    SUPPRESS_ON = True
    debug(u'Revit dialog suppression on')


def end_suppression():
    global SUPPRESS_ON
    SUPPRESS_ON = False
    if _suppressed:
        debug(u'suppressed {0} Revit dialog(s): {1}'.format(
            len(_suppressed), u', '.join(_suppressed[:12])))
    debug(u'Revit dialog suppression off')
    return list(_suppressed)


def failure_preprocessor():
    """An IFailuresPreprocessor that deletes warnings, or None."""
    try:
        from Autodesk.Revit.DB import IFailuresPreprocessor, FailureProcessingResult
    except Exception:
        return None

    class _Swallow(IFailuresPreprocessor):
        def PreprocessFailures(self, accessor):
            try:
                for failure in accessor.GetFailureMessages():
                    try:
                        accessor.DeleteWarning(failure)
                    except Exception:
                        continue
            except Exception:
                pass
            return FailureProcessingResult.Continue

    try:
        return _Swallow()
    except Exception:
        return None


def quiet_transaction(transaction):
    """Put the warning-swallowing preprocessor on a transaction."""
    if not SUPPRESS_ON:
        return False
    handler = failure_preprocessor()
    if handler is None:
        return False
    try:
        options = transaction.GetFailureHandlingOptions()
        options.SetFailuresPreprocessor(handler)
        options.SetClearAfterRollback(True)
        transaction.SetFailureHandlingOptions(options)
        return True
    except Exception:
        return False


# ==========================================================================
# results
# ==========================================================================

class Outcome(object):
    """What happened to one row in one format."""

    __slots__ = ('key', 'label', 'fmt', 'path', 'ok', 'message')

    def __init__(self, key, label, fmt, path=u'', ok=False, message=u''):
        self.key = key
        self.label = label
        self.fmt = fmt
        self.path = path
        self.ok = ok
        self.message = message


# ==========================================================================
# the debug log
#
# Off by default. On, it records what was actually asked of Revit and of the
# driver, in order, which is the only way to tell "the driver refused" apart
# from "the driver saved it somewhere else" - both of which look identical
# from outside as a file that is not there.
# ==========================================================================

# Always on. The log is a few kilobytes, it is overwritten every run, and a
# diagnostic that only exists when somebody remembered to ask for it is not
# there on the run that actually went wrong. The tickbox decides how loudly
# the report talks about it, not whether it is written.
DEBUG_ON = True
DEBUG_LINES = []


def debug_reset():
    del DEBUG_LINES[:]


def debug(text):
    if not DEBUG_ON:
        return
    try:
        from System import DateTime
        stamp = DateTime.Now.ToString('HH:mm:ss.fff')
    except Exception:
        stamp = u''
    try:
        DEBUG_LINES.append(u'{0}  {1}'.format(stamp, text))
    except Exception:
        pass


def debug_text():
    return u'\n'.join(DEBUG_LINES)


class Report(object):
    """Everything worth telling the user after a run."""

    def __init__(self):
        self.outcomes = []
        self.notes = []
        self.cancelled = False
        self.seconds = 0.0
        self.debug_path = u''
        # Called with each outcome as it happens, so the window can
        # colour the row. Set here rather than threaded through every
        # exporter's arguments: five of them add outcomes and they
        # would all have needed the same extra parameter.
        self.on_add = None

    def add(self, outcome):
        self.outcomes.append(outcome)
        if self.on_add is None:
            return
        try:
            self.on_add(outcome)
        except Exception:
            # A window that cannot repaint must never stop an export.
            pass

    def note(self, text):
        text = u'{0}'.format(text)
        if text and text not in self.notes:
            self.notes.append(text)

    def written(self):
        return [o for o in self.outcomes if o.ok]

    def failed(self):
        return [o for o in self.outcomes if not o.ok]

    def folders(self):
        seen = []
        for outcome in self.written():
            folder = os.path.dirname(outcome.path)
            if folder and folder not in seen:
                seen.append(folder)
        return seen

    def summary(self):
        ok_count = len(self.written())
        bad_count = len(self.failed())
        if self.cancelled:
            head = u'Cancelled after {0} file{1}'.format(
                ok_count, u'' if ok_count == 1 else u's')
        elif bad_count:
            head = u'{0} written, {1} failed'.format(ok_count, bad_count)
        else:
            head = u'{0} file{1} written'.format(
                ok_count, u'' if ok_count == 1 else u's')
        return u'{0} in {1:.1f}s'.format(head, float(self.seconds))


class Job(object):
    """One sheet or view, with the name and folder already decided."""

    __slots__ = ('key', 'label', 'element_id', 'base_name', 'folders',
                 'size_info', 'view')

    def __init__(self, key, label, element_id, base_name, folders,
                 size_info=None, view=None):
        self.key = key
        self.label = label
        self.element_id = element_id
        self.base_name = base_name
        self.folders = folders          # {'pdf': path, 'dwg': path}
        self.size_info = size_info
        self.view = view


# ==========================================================================
# what this machine can do
# ==========================================================================

def list_printers():
    """Every printer installed on this machine, PDF writers included."""
    names = []
    try:
        from System.Drawing.Printing import PrinterSettings
        for name in PrinterSettings.InstalledPrinters:
            text = u'{0}'.format(name)
            if text and text not in names:
                names.append(text)
    except Exception:
        pass
    names.sort(key=lambda n: n.lower())
    return names


def default_printer():
    try:
        from System.Drawing.Printing import PrinterSettings
        return u'{0}'.format(PrinterSettings().PrinterName)
    except Exception:
        return u''


# ==========================================================================
# drivers we already know something about
#
# Most installed printers are a mystery to this tool: whether one prompts
# for a file name, and where it writes if it does not, can only be found
# out by running a sheet through it. A few are not a mystery.
#
# "diroots.prosheets" is the one that matters. ProSheets installs its own
# private instance of PDF24 under that name, set up not to ask where to
# save - which is the entire reason their batch export works unattended
# while a hand-rolled one against the main PDF24 printer sits waiting on a
# Save As dialog. If it is on the machine it is the best driver default
# available, so it is picked ahead of whatever Windows calls the default
# printer.
#
# Matched on letters and digits alone, so "DiRoots.ProSheets",
# "diroots prosheets" and a redirected copy carrying a session suffix all
# count as the same printer.
# ==========================================================================

# token, what to tell the user, needs a staging folder
KNOWN_PRINTERS = [
    ('dirootsprosheets',
     u'a private PDF24 instance that ProSheets installs, already set not '
     u'to ask where to save',
     True),
]


def _token(text):
    return re.sub(r'[^a-z0-9]', '', u'{0}'.format(text or u'').lower())


def known_printer(name):
    """(description, needs staging) for a driver we know, or None."""
    token = _token(name)
    if not token:
        return None
    for wanted, description, staging in KNOWN_PRINTERS:
        if wanted in token:
            return description, staging
    return None


def preferred_printer(printers):
    """The best known driver out of a list of installed printers, or ''.

    Order in KNOWN_PRINTERS is preference order, not the order the
    printers happen to be installed in.
    """
    for wanted, _description, _staging in KNOWN_PRINTERS:
        for name in printers or []:
            if wanted in _token(name):
                return u'{0}'.format(name)
    return u''


def native_pdf_available(doc):
    """Whether this Revit has its own PDF exporter (2022 and later)."""
    try:
        from Autodesk.Revit import DB
        return hasattr(DB, 'PDFExportOptions')
    except Exception:
        return False


def list_dwg_setups(doc):
    """Every DWG export setup saved in this model."""
    names = []
    try:
        from Autodesk.Revit.DB import ExportDWGSettings
        for name in ExportDWGSettings.ListNames(doc):
            text = u'{0}'.format(name)
            if text and text not in names:
                names.append(text)
    except Exception:
        pass
    names.sort(key=lambda n: n.lower())
    return names


# ==========================================================================
# paper sizes
# ==========================================================================

def printer_paper_sizes(doc):
    """The paper sizes the currently selected print driver offers."""
    sizes = []
    try:
        for paper in doc.PrintManager.PaperSizes:
            try:
                sizes.append((u'{0}'.format(paper.Name), paper))
            except Exception:
                continue
    except Exception:
        pass
    return sizes


def _normalise(text):
    return u''.join([ch for ch in u'{0}'.format(text).upper()
                     if ch.isalnum()])


def match_paper(sizes, wanted, width_mm=0.0, height_mm=0.0):
    """Find the driver's paper for a sheet size like ``A1``.

    Drivers name the same paper half a dozen ways - ``A1``, ``ISO A1``,
    ``A1 (594 x 841mm)`` - so an exact string match finds nothing on most
    machines. Exact first, then a whole-token match, then the millimetres.
    """
    if not sizes:
        return None
    target = _normalise(wanted)

    if target:
        for name, paper in sizes:
            if _normalise(name) == target:
                return paper
        for name, paper in sizes:
            normalised = _normalise(name)
            if normalised.startswith(target) or normalised.endswith(target):
                return paper
        for name, paper in sizes:
            if target and target in _normalise(name):
                return paper

    if width_mm and height_mm:
        short = int(round(min(width_mm, height_mm)))
        long_edge = int(round(max(width_mm, height_mm)))
        for tolerance in (0, 1, 2, 3, 4, 5):
            for name, paper in sizes:
                normalised = _normalise(name)
                for candidate_short in range(short - tolerance, short + tolerance + 1):
                    for candidate_long in range(long_edge - tolerance,
                                                long_edge + tolerance + 1):
                        pair = u'{0}X{1}'.format(candidate_short, candidate_long)
                        if pair in normalised:
                            return paper
    return None


# ==========================================================================
# shared option mapping
# ==========================================================================

def _raster_quality(name):
    lookup = {
        'low': ('Low',),
        'medium': ('Medium',),
        'high': ('High',),
        'presentation': ('Presentation',),
    }
    return enum_member('RasterQualityType',
                       *lookup.get(name, ('High',)))


def _colour_depth(name):
    lookup = {
        'color': ('Color', 'Colour'),
        'grayscale': ('GrayScale', 'Grayscale'),
        'blackline': ('BlackLine', 'Blackline'),
    }
    return enum_member('ColorDepthType', *lookup.get(name, ('Color',)))


def _zoom_type(name):
    if name == 'fit':
        return enum_member('ZoomType', 'FitToPage', 'Fit')
    return enum_member('ZoomType', 'Zoom')


def _placement(name):
    if name == 'offset':
        return enum_member('PaperPlacementType', 'Margins', 'LowerLeft')
    return enum_member('PaperPlacementType', 'Center', 'Centre')


def _margin(name):
    lookup = {
        'nomargin': ('NoMargin',),
        'printerlimit': ('PrinterLimit',),
        'usermargin': ('UserDefined', 'UserMargin'),
    }
    return enum_member('MarginType', *lookup.get(name, ('NoMargin',)))


def _hidden_line(name):
    if name == 'raster':
        return enum_member('HiddenLineViewsType', 'RasterProcessing')
    return enum_member('HiddenLineViewsType', 'VectorProcessing')


def _orientation(landscape):
    if landscape:
        return enum_member('PageOrientationType', 'Landscape')
    return enum_member('PageOrientationType', 'Portrait')


def _flag(profile, key, default=False):
    value = profile.get(key)
    if value is None:
        return default
    return u'{0}'.format(value).strip().lower() in ('1', 'true', 'yes', 'on')


def _number(profile, key, default=0.0):
    try:
        return float(u'{0}'.format(profile.get(key, default)).strip())
    except Exception:
        return default


def _text(profile, key, default=u''):
    value = profile.get(key)
    if value is None:
        return default
    return u'{0}'.format(value).strip()


# ==========================================================================
# PDF through Revit's own exporter
# ==========================================================================

def build_pdf_options(profile, size_info=None, log=None):
    """A configured ``PDFExportOptions``, or None where the class is absent."""
    try:
        from Autodesk.Revit.DB import PDFExportOptions
    except Exception:
        if log is not None:
            log.append(u'this Revit has no built-in PDF exporter')
        return None

    options = PDFExportOptions()

    set_opt(options, 'ZoomType', _zoom_type(_text(profile, 'pdf.zoom_mode', 'zoom')), log)
    if _text(profile, 'pdf.zoom_mode', 'zoom') == 'zoom':
        try:
            set_opt(options, 'ZoomPercentage',
                    int(_number(profile, 'pdf.zoom', 100.0)), log)
        except Exception:
            pass

    set_opt(options, 'PaperPlacement',
            _placement(_text(profile, 'pdf.placement', 'center')), log)
    if _text(profile, 'pdf.placement', 'center') == 'offset':
        set_opt(options, 'MarginType',
                _margin(_text(profile, 'pdf.margin', 'nomargin')), log)
        set_opt(options, 'OriginOffsetX', _number(profile, 'pdf.offset_x'), log)
        set_opt(options, 'OriginOffsetY', _number(profile, 'pdf.offset_y'), log)

    set_opt(options, 'HiddenLineViews',
            _hidden_line(_text(profile, 'pdf.hidden_line', 'vector')), log)
    # Older releases express the same idea as a bare flag instead.
    set_opt(options, 'AlwaysUseRaster',
            _text(profile, 'pdf.hidden_line', 'vector') == 'raster', None)

    set_opt(options, 'RasterQuality',
            _raster_quality(_text(profile, 'pdf.raster_quality', 'high')), log)
    set_opt(options, 'ColorDepth',
            _colour_depth(_text(profile, 'pdf.colors', 'color')), log)

    set_opt(options, ['ViewLinksInBlue', 'ViewLinksinBlue'],
            _flag(profile, 'pdf.view_links_blue', True), log)
    set_opt(options, ['HideReferencePlane', 'HideReforWorkPlanes'],
            _flag(profile, 'pdf.hide_ref_planes', True), log)
    set_opt(options, 'HideUnreferencedViewTags',
            _flag(profile, 'pdf.hide_unreferenced_tags', True), log)
    set_opt(options, 'HideScopeBoxes',
            _flag(profile, 'pdf.hide_scope_boxes', True), log)
    set_opt(options, 'HideCropBoundaries',
            _flag(profile, 'pdf.hide_crop_boundaries', True), log)
    set_opt(options, 'ReplaceHalftoneWithThinLines',
            _flag(profile, 'pdf.replace_halftone', False), log)
    set_opt(options, 'MaskCoincidentLines',
            _flag(profile, 'pdf.mask_coincident', False), log)
    set_opt(options, 'StopOnError', False, None)

    if size_info is not None and _flag(profile, 'pdf.keep_paper_size', True):
        set_opt(options, 'PaperOrientation',
                _orientation(getattr(size_info, 'landscape', True)), None)
        paper_format = _paper_format_for(getattr(size_info, 'name', u''))
        if paper_format is not None:
            set_opt(options, 'PaperFormat', paper_format, None)

    return options


def _paper_format_for(size_name):
    """Map an A-size onto ``ExportPaperFormat`` where the member exists."""
    name = u'{0}'.format(size_name).strip().upper()
    if name in ('A0', 'A1', 'A2', 'A3', 'A4', 'A5', 'A6'):
        return enum_member('ExportPaperFormat', 'ISO_' + name, name)
    return enum_member('ExportPaperFormat', 'Default')


def export_pdf_native(doc, jobs, profile, progress=None, should_stop=None,
                      report=None):
    """One PDF per job through Revit's own exporter.

    Each job is exported on its own with ``Combine`` on and ``FileName`` set,
    which is the only way to get the exact file name the naming rules asked
    for. Exporting them all in one call is faster but hands the naming back to
    Revit, and the whole point of the first page is that the user owns it.
    """
    report = report or Report()
    log = []
    total = len(jobs)

    for index, job in enumerate(jobs, 1):
        if should_stop is not None and should_stop():
            report.cancelled = True
            break
        if progress is not None:
            progress(index, total, job.label, 'PDF')

        folder = job.folders.get('pdf', u'')
        made, error = ps_paths.ensure(folder)
        if not made:
            report.add(Outcome(job.key, job.label, 'PDF', u'', False,
                               u'folder could not be made: {0}'.format(error)))
            continue

        target = os.path.join(folder, job.base_name + u'.pdf')
        if ps_paths.long_path_risk(target):
            report.note(u'Some paths are close to the 260 character limit; '
                        u'a shorter root folder would be safer.')

        options = build_pdf_options(profile, job.size_info, log)
        if options is None:
            report.add(Outcome(job.key, job.label, 'PDF', target, False,
                               u'no built-in PDF exporter on this Revit'))
            continue

        set_opt(options, 'Combine', True, None)
        set_opt(options, 'FileName', job.base_name, None)

        if _flag(profile, 'out.overwrite', True):
            _remove_if_present(target)
        else:
            target = ps_paths.unique_on_disk(folder, job.base_name, u'.pdf')
            set_opt(options, 'FileName',
                    os.path.splitext(os.path.basename(target))[0], None)

        debug(u'--- {0}'.format(job.label))
        debug(u'native PDF export to {0}'.format(target))
        try:
            doc.Export(folder, id_list([job.element_id]), options)
            debug(u'Document.Export returned with no error')
        except Exception as err:
            debug(u'Document.Export threw: {0}'.format(err))
            report.add(Outcome(job.key, job.label, 'PDF', target, False,
                               u'{0}'.format(err)))
            continue

        landed = _wait_for(target)
        debug(u'file on disk afterwards: {0}'.format(landed))
        report.add(Outcome(
            job.key, job.label, 'PDF', target, landed,
            u'' if landed else u'Revit reported no error but no file appeared'))

    for line in log:
        report.note(line)
    return report


def export_pdf_combined(doc, jobs, profile, out_name, progress=None,
                        report=None):
    """Every job into one PDF, in the order given."""
    report = report or Report()
    if not jobs:
        return report
    log = []
    folder = jobs[0].folders.get('pdf', u'')
    made, error = ps_paths.ensure(folder)
    if not made:
        report.add(Outcome(0, out_name, 'PDF', u'', False,
                           u'folder could not be made: {0}'.format(error)))
        return report

    options = build_pdf_options(profile, jobs[0].size_info, log)
    if options is None:
        report.add(Outcome(0, out_name, 'PDF', u'', False,
                           u'no built-in PDF exporter on this Revit'))
        return report

    set_opt(options, 'Combine', True, None)
    set_opt(options, 'FileName', out_name, None)

    target = os.path.join(folder, out_name + u'.pdf')
    if _flag(profile, 'out.overwrite', True):
        _remove_if_present(target)

    if progress is not None:
        progress(1, 1, out_name, 'PDF')

    try:
        doc.Export(folder, id_list([job.element_id for job in jobs]), options)
    except Exception as err:
        report.add(Outcome(0, out_name, 'PDF', target, False, u'{0}'.format(err)))
        return report

    landed = _wait_for(target)
    report.add(Outcome(
        0, out_name, 'PDF', target, landed,
        u'' if landed else u'Revit reported no error but no file appeared'))
    for line in log:
        report.note(line)
    return report


# ==========================================================================
# PDF through a printer driver
# ==========================================================================

def export_pdf_printer(doc, jobs, profile, printer_name, progress=None,
                       should_stop=None, report=None):
    """One PDF per job through an installed print driver such as PDF24.

    The driver route exists because a house PDF setup (compression, fonts,
    stamps) lives in the driver, not in Revit. What it costs is paper size
    matching: Revit prints onto whatever paper the driver offers, and a sheet
    whose size the driver does not have comes out scaled with no warning. So
    the size is matched per sheet and a sheet that cannot be matched is
    **refused rather than printed wrong**.
    """
    report = report or Report()
    log = []
    total = len(jobs)

    manager = None
    try:
        manager = doc.PrintManager
    except Exception as err:
        report.note(u'no print manager: {0}'.format(err))
        for job in jobs:
            report.add(Outcome(job.key, job.label, 'PDF', u'', False,
                               u'the print manager is not available'))
        return report

    # No transaction around any of this.
    #
    # The paper size lives on PrintParameters, which is a document
    # element, so changing it DOES need one - but SubmitPrint must be
    # called with none open. Revit 2024 and later do not throw when it
    # is: the call returns, immediately and successfully, having printed
    # nothing at all. A whole afternoon went into "SubmitPrint returned
    # with no error" followed by no file, on two machines, before the
    # 178 milliseconds it took to render an A0 sheet gave it away.
    #
    # So the transaction is opened per sheet, around the setup only, and
    # committed before the job is submitted. See _print_setup_ok.
    try:
        debug(u'printer route: selecting driver "{0}"'.format(printer_name))
        try:
            manager.SelectNewPrintDriver(printer_name)
        except Exception as err:
            report.note(u'could not select "{0}": {1}'.format(printer_name, err))
            for job in jobs:
                report.add(Outcome(job.key, job.label, 'PDF', u'', False,
                                   u'printer "{0}" could not be selected'
                                   .format(printer_name)))
            return report

        staging = _text(profile, 'pdf.staging')
        if staging:
            debug(u'staging route: collecting from {0}'.format(staging))
            # The driver is going to save where its own settings say, so
            # asking Revit to redirect the output would only confuse it.
            set_opt(manager, 'PrintToFile', False, log)
        else:
            set_opt(manager, 'PrintToFile', True, log)
        set_opt(manager, 'CombinedFile', False, None)
        range_current = enum_member('PrintRange', 'Current')
        if range_current is not None:
            set_opt(manager, 'PrintRange', range_current, log)

        run_before = folder_snapshot(staging) if staging else {}
        sizes = printer_paper_sizes(doc)
        debug(u'driver offers {0} paper size(s): {1}'.format(
            len(sizes), u', '.join([name for name, _p in sizes[:40]]) or u'none'))
        if not sizes:
            report.note(u'the driver reported no paper sizes; sheets will '
                        u'print on whatever it defaults to')

        written_so_far = 0
        for index, job in enumerate(jobs, 1):
            if should_stop is not None and should_stop():
                report.cancelled = True
                break

            # A driver that produced nothing for the first sheet will
            # produce nothing for the next hundred, each costing ten seconds
            # of waiting. Stop and say so rather than grinding through a
            # whole issue to reach the same conclusion.
            if index > 1 and written_so_far == 0 and report.failed():
                skipped = len(jobs) - index + 1
                report.note(
                    u'Stopped after the first sheet produced no file. The '
                    u'remaining {0} sheet(s) were not attempted, because the '
                    u'same thing would happen to each of them. Fix the '
                    u'driver or the "Driver saves to" folder and run again.'
                    .format(skipped))
                debug(u'stopping early: first sheet produced nothing, '
                      u'{0} skipped'.format(skipped))
                report.cancelled = True
                break

            if progress is not None:
                progress(index, total, job.label, 'PDF')

            folder = job.folders.get('pdf', u'')
            made, error = ps_paths.ensure(folder)
            if not made:
                report.add(Outcome(job.key, job.label, 'PDF', u'', False,
                                   u'folder could not be made: {0}'.format(error)))
                continue

            target = os.path.join(folder, job.base_name + u'.pdf')
            if not _flag(profile, 'out.overwrite', True):
                target = ps_paths.unique_on_disk(folder, job.base_name, u'.pdf')
            else:
                _remove_if_present(target)

            debug(u'--- {0}'.format(job.label))
            debug(u'target path: {0}'.format(target))
            ok, message = _print_setup_ok(doc, manager, profile,
                                          job.size_info, sizes, log)
            debug(u'print setup: {0}'.format(
                u'applied' if ok else u'REFUSED - ' + message))
            if not ok:
                report.add(Outcome(job.key, job.label, 'PDF', target, False,
                                   message))
                continue

            before = {}
            if staging:
                made, error = ps_paths.ensure(staging)
                if not made:
                    report.add(Outcome(job.key, job.label, 'PDF', target, False,
                                       u'the staging folder could not be '
                                       u'made: {0}'.format(error)))
                    continue
                before = folder_snapshot(staging)
                debug(u'{0} PDF(s) already in the staging folder'
                      .format(len(before)))
            else:
                took_path = set_opt(manager, 'PrintToFileName', target, log)
                debug(u'PrintToFileName accepted by the API: {0}'
                      .format(took_path))
            try:
                manager.Apply()
                debug(u'PrintManager.Apply() returned')
            except Exception as err:
                log.append(u'print settings would not apply: {0}'.format(err))
                debug(u'PrintManager.Apply() threw: {0}'.format(err))

            spent = 0.0
            try:
                started = time.time()
                manager.SubmitPrint(job.view)
                spent = time.time() - started
                debug(u'SubmitPrint returned with no error after {0:.2f}s'
                      .format(float(spent)))
                if spent < 0.5:
                    debug(u'   that is too quick to have rendered a sheet. '
                          u'A submit that returns instantly has printed '
                          u'nothing - the usual cause is a transaction '
                          u'still open, which Revit does not complain '
                          u'about.')
            except Exception as err:
                debug(u'SubmitPrint threw: {0}'.format(err))
                report.add(Outcome(job.key, job.label, 'PDF', target, False,
                                   u'{0}'.format(err)))
                continue

            if staging:
                budget = driver_wait_budget(spent)
                debug(u'waiting up to {0:.0f}s for "{1}" to write it'
                      .format(float(budget), printer_name))
                arrived = wait_for_new_pdf(staging, before, seconds=budget,
                                           should_stop=should_stop)
                if not arrived:
                    debug(u'nothing new arrived in the staging folder')
                    waiting, status = queue_state(printer_name)
                    if waiting > 0:
                        debug(u'{0} job(s) still sitting in the Windows '
                              u'print queue for "{1}" (status: {2})'
                              .format(waiting, printer_name,
                                      status or u'unknown'))
                        stuck = (u'{0} job(s) are still sitting in the '
                                 u'Windows print queue for "{1}", so it '
                                 u'took the sheet and has not finished with '
                                 u'it. That is the driver waiting on '
                                 u'something - usually its own Save As or '
                                 u'assistant window, open behind Revit.'
                                 .format(waiting, printer_name))
                    elif waiting == 0:
                        debug(u'the Windows print queue for "{0}" is empty, '
                              u'so the driver finished with the job and '
                              u'wrote it somewhere else - or discarded it'
                              .format(printer_name))
                        stuck = (u'The Windows print queue for "{0}" is '
                                 u'empty, so it finished with the sheet and '
                                 u'either wrote it somewhere other than {1} '
                                 u'or threw it away. Automatic saving is '
                                 u'most likely off.'.format(printer_name,
                                                            staging))
                    else:
                        debug(u'could not read the print queue: {0}'
                              .format(status))
                        stuck = (u'"{0}" is most likely still asking where '
                                 u'to save rather than saving on its own.'
                                 .format(printer_name))
                    report.add(Outcome(
                        job.key, job.label, 'PDF', target, False,
                        u'nothing appeared in {0} within {1:.0f}s. {2}'
                        .format(staging, float(budget), stuck)))
                    continue
                debug(u'driver wrote {0}'.format(arrived))
                moved, detail = move_into_place(
                    arrived, target, _flag(profile, 'out.overwrite', True))
                debug(u'moved into place: {0} ({1})'.format(moved, detail))
                if moved:
                    written_so_far += 1
                report.add(Outcome(
                    job.key, job.label, 'PDF',
                    detail if moved else target, moved,
                    u'' if moved else
                    u'the driver wrote {0} but it could not be moved: {1}'
                    .format(arrived, detail)))
                continue

            landed = _wait_for(target, attempts=40)
            debug(u'waited 10s for the file: {0}'.format(
                u'it arrived' if landed else u'NOTHING ARRIVED'))
            if landed:
                written_so_far += 1
            report.add(Outcome(
                job.key, job.label, 'PDF', target, landed,
                u'' if landed else
                u'no file appeared at {0}'.format(target)))
        # One last look before calling it a failure.
        #
        # A driver slower than the wait means the file lands after the
        # tool has moved on, and the old behaviour was to leave it
        # there and report nothing written - the worst of both, because
        # the PDF exists and nobody is told. Anything that turned up
        # late is claimed here and named.
        if staging and written_so_far == 0 and not report.cancelled:
            late = _late_arrivals(staging, run_before)
            if late:
                debug(u'{0} PDF(s) turned up in the staging folder after '
                      u'the run gave up'.format(len(late)))
                report.note(
                    u'{0} PDF(s) appeared in {1} after the tool had stopped '
                    u'waiting, so "{2}" is simply slower than the wait '
                    u'allowed. They are still there, under the driver\'s own '
                    u'names, and the next run will wait longer.'
                    .format(len(late), staging, printer_name))
    finally:
        for line in log:
            report.note(line)
    return report


def _print_setup_ok(doc, manager, profile, size_info, sizes, log):
    """Apply the print setup inside a transaction, and close it again.

    Committed before returning, always. The caller submits the print job
    straight afterwards and SubmitPrint with a transaction still open
    prints nothing while reporting success - so the transaction not
    outliving this function is the whole point of it existing.
    """
    transaction = None
    try:
        transaction = Transaction(doc, 'RevoBIM Pro Sheets print setup')
        quiet_transaction(transaction)
        transaction.Start()
    except Exception as err:
        log.append(u'could not start the print setup transaction: {0}'
                   .format(err))
        transaction = None

    try:
        return _apply_print_setup(doc, manager, profile, size_info, sizes,
                                  log)
    finally:
        if transaction is not None:
            try:
                transaction.Commit()
            except Exception:
                try:
                    transaction.RollBack()
                except Exception:
                    pass


def _apply_print_setup(doc, manager, profile, size_info, sizes, log):
    """Point the in-session print setting at the right paper and options."""
    try:
        setup = manager.PrintSetup
    except Exception as err:
        return False, u'no print setup: {0}'.format(err)

    try:
        setup.CurrentPrintSetting = setup.InSession
    except Exception:
        pass

    try:
        parameters = setup.CurrentPrintSetting.PrintParameters
    except Exception as err:
        return False, u'no print parameters: {0}'.format(err)

    if sizes and _flag(profile, 'pdf.keep_paper_size', True):
        wanted = getattr(size_info, 'name', u'') if size_info else u''
        width = getattr(size_info, 'width_mm', 0.0) if size_info else 0.0
        height = getattr(size_info, 'height_mm', 0.0) if size_info else 0.0
        paper = match_paper(sizes, wanted, width, height)
        try:
            described = size_info.describe()
        except Exception:
            described = wanted or u'?'
        debug(u'sheet wants {0}; driver paper matched: {1}'.format(
            described, getattr(paper, 'Name', u'NONE')))
        if size_info is not None and not getattr(size_info, 'exact', True):
            debug(u'   that sheet is not a standard size and was fitted up')
        if paper is None:
            return False, (u'"{0}" is not a paper size this driver offers - '
                           u'add it in the driver, or untick Keep Paper Size'
                           .format(wanted or u'this sheet'))
        set_opt(parameters, 'PaperSize', paper, log)
        set_opt(parameters, 'PageOrientation',
                _orientation(getattr(size_info, 'landscape', True)), None)

    set_opt(parameters, 'PaperPlacement',
            _placement(_text(profile, 'pdf.placement', 'center')), log)
    if _text(profile, 'pdf.placement', 'center') == 'offset':
        set_opt(parameters, 'MarginType',
                _margin(_text(profile, 'pdf.margin', 'nomargin')), log)
        set_opt(parameters, ['OriginOffsetX', 'UserDefinedMarginX'],
                _number(profile, 'pdf.offset_x'), None)
        set_opt(parameters, ['OriginOffsetY', 'UserDefinedMarginY'],
                _number(profile, 'pdf.offset_y'), None)

    zoom_mode = _text(profile, 'pdf.zoom_mode', 'zoom')
    set_opt(parameters, 'ZoomType', _zoom_type(zoom_mode), log)
    if zoom_mode == 'zoom':
        try:
            set_opt(parameters, 'Zoom', int(_number(profile, 'pdf.zoom', 100.0)), log)
        except Exception:
            pass

    set_opt(parameters, 'HiddenLineViews',
            _hidden_line(_text(profile, 'pdf.hidden_line', 'vector')), log)
    set_opt(parameters, 'RasterQuality',
            _raster_quality(_text(profile, 'pdf.raster_quality', 'high')), log)
    set_opt(parameters, 'ColorDepth',
            _colour_depth(_text(profile, 'pdf.colors', 'color')), log)

    set_opt(parameters, ['ViewLinksinBlue', 'ViewLinksInBlue'],
            _flag(profile, 'pdf.view_links_blue', True), log)
    set_opt(parameters, ['HideReforWorkPlanes', 'HideReferencePlane'],
            _flag(profile, 'pdf.hide_ref_planes', True), log)
    set_opt(parameters, 'HideUnreferencedViewTags',
            _flag(profile, 'pdf.hide_unreferenced_tags', True), log)
    set_opt(parameters, 'HideScopeBoxes',
            _flag(profile, 'pdf.hide_scope_boxes', True), log)
    set_opt(parameters, 'HideCropBoundaries',
            _flag(profile, 'pdf.hide_crop_boundaries', True), log)
    set_opt(parameters, 'ReplaceHalftoneWithThinLines',
            _flag(profile, 'pdf.replace_halftone', False), log)
    set_opt(parameters, 'MaskCoincidentLines',
            _flag(profile, 'pdf.mask_coincident', False), log)
    return True, u''


def combined_print_set(doc, manager, views, set_name='RevoBIM Pro Sheets'):
    """Point the print manager at a temporary saved set, for a combined file.

    A combined print needs ``PrintRange.Select`` and a real ``ViewSheetSet``
    element in the model - there is no in-memory route. The set is reused by
    name rather than made fresh each run, so a project does not fill up with
    them.
    """
    try:
        setting = manager.ViewSheetSetting
        view_set = ViewSet()
        for view in views:
            view_set.Insert(view)
        setting.CurrentViewSheetSet.Views = view_set
        try:
            setting.SaveAs(set_name)
        except Exception:
            setting.Save()
        return True, u''
    except Exception as err:
        return False, u'{0}'.format(err)


# ==========================================================================
# DWG
# ==========================================================================

def build_dwg_options(doc, profile, log=None):
    """DWG options from a saved export setup, or sensible defaults."""
    options = None
    setup_name = _text(profile, 'dwg.setup')
    if setup_name:
        try:
            from Autodesk.Revit.DB import ExportDWGSettings
            settings = ExportDWGSettings.FindByName(doc, setup_name)
            if settings is not None:
                options = settings.GetDWGExportOptions()
            elif log is not None:
                log.append(u'DWG export setup "{0}" is not in this model; '
                           u'the default settings were used instead'
                           .format(setup_name))
        except Exception as err:
            if log is not None:
                log.append(u'could not read DWG setup "{0}": {1}'
                           .format(setup_name, err))
    if options is None:
        try:
            from Autodesk.Revit.DB import DWGExportOptions
            options = DWGExportOptions()
        except Exception as err:
            if log is not None:
                log.append(u'no DWG exporter on this Revit: {0}'.format(err))
            return None

    # Revit's own "Export views on sheets and links as external references"
    # is MergedViews inverted: merged means everything bound into one DWG,
    # unmerged means views and links become XREFs. The profile stores the
    # checkbox as the user sees it, so it is flipped here once rather than
    # everywhere it is read.
    as_xrefs = _flag(profile, 'dwg.external_refs', False)
    set_opt(options, 'MergedViews', not as_xrefs, None)
    debug(u'DWG: links and views {0}'.format(
        u'as external references' if as_xrefs else u'bound into the DWG'))
    set_opt(options, 'SharedCoords', _flag(profile, 'dwg.shared_coords', True), None)

    version = _text(profile, 'dwg.version', 'default')
    if version and version != 'default':
        member = enum_member('ACADVersion', version.upper(), version)
        if member is not None:
            set_opt(options, 'FileVersion', member, log)
    return options


def export_dwg(doc, jobs, profile, progress=None, should_stop=None,
               report=None):
    """One DWG per job.

    Exported one view at a time rather than in a batch, for the same reason
    the PDFs are: a batch hands the naming back to Revit, which appends the
    view name to a prefix and ignores the custom naming entirely.
    """
    report = report or Report()
    log = []
    total = len(jobs)

    options = build_dwg_options(doc, profile, log)
    if options is None:
        for job in jobs:
            report.add(Outcome(job.key, job.label, 'DWG', u'', False,
                               u'no DWG exporter available'))
        for line in log:
            report.note(line)
        return report

    for index, job in enumerate(jobs, 1):
        if should_stop is not None and should_stop():
            report.cancelled = True
            break
        if progress is not None:
            progress(index, total, job.label, 'DWG')

        folder = job.folders.get('dwg', u'')
        made, error = ps_paths.ensure(folder)
        if not made:
            report.add(Outcome(job.key, job.label, 'DWG', u'', False,
                               u'folder could not be made: {0}'.format(error)))
            continue

        base = job.base_name
        target = os.path.join(folder, base + u'.dwg')
        if _flag(profile, 'out.overwrite', True):
            _remove_if_present(target)
        else:
            target = ps_paths.unique_on_disk(folder, base, u'.dwg')
            base = os.path.splitext(os.path.basename(target))[0]

        try:
            doc.Export(folder, base, id_list([job.element_id]), options)
        except Exception as err:
            report.add(Outcome(job.key, job.label, 'DWG', target, False,
                               u'{0}'.format(err)))
            continue

        landed = _wait_for(target)
        if not landed:
            # Revit sometimes decorates the name with the view type when it
            # is exporting a view rather than a sheet. Take whichever file it
            # actually made and rename it, rather than reporting a failure
            # for a file that is sitting right there under another name.
            renamed = _claim_stray_dwg(folder, base, target)
            landed = renamed
        report.add(Outcome(
            job.key, job.label, 'DWG', target, landed,
            u'' if landed else u'Revit reported no error but no file appeared'))

    for line in log:
        report.note(line)
    return report


def _claim_stray_dwg(folder, base, target):
    try:
        for entry in os.listdir(folder):
            if not entry.lower().endswith('.dwg'):
                continue
            if entry.lower().startswith(base.lower()) and entry != os.path.basename(target):
                os.rename(os.path.join(folder, entry), target)
                return os.path.isfile(target)
    except Exception:
        pass
    return False


# ==========================================================================
# NWC
#
# One NWC per ticked 3D view. Navisworks export is scoped to a view and
# there is no such thing as exporting a sheet, which is why the tile is
# only live when a 3D view is ticked - see _format_availability in
# ps_window for the other half of that.
#
# NavisworksExportOptions lives in RevitAPI.dll whether or not the
# exporter add-in is installed, so the type being importable proves
# nothing; the export itself is what fails, and it fails per view. The
# first failure stops the run rather than repeating the same message once
# per view.
# ==========================================================================

NWC_PARAMETER_MODES = {
    'all': ('All',),
    'elements': ('Elements',),
    'none': ('None',),
}

NWC_COORDINATE_MODES = {
    'shared': ('Shared',),
    'internal': ('Internal',),
}


def build_nwc_options(profile, view_id=None, log=None):
    """Navisworks export options from the profile, or None if unavailable."""
    try:
        from Autodesk.Revit.DB import NavisworksExportOptions
        options = NavisworksExportOptions()
    except Exception as err:
        if log is not None:
            log.append(u'no Navisworks exporter on this Revit: {0}'.format(err))
        return None

    set_opt(options, 'ExportParts', _flag(profile, 'nwc.parts', False), log)
    set_opt(options, 'ExportElementIds',
            _flag(profile, 'nwc.element_ids', True), log)
    set_opt(options, 'ConvertElementProperties',
            _flag(profile, 'nwc.properties', False), log)
    set_opt(options, 'ExportLinks',
            _flag(profile, 'nwc.linked_files', False), log)
    set_opt(options, 'ExportRoomAsAttribute',
            _flag(profile, 'nwc.room_as_attribute', True), log)
    set_opt(options, 'ExportUrls', _flag(profile, 'nwc.urls', True), log)
    set_opt(options, 'DivideFileIntoLevels',
            _flag(profile, 'nwc.divide_levels', True), log)
    set_opt(options, 'ExportRoomGeometry',
            _flag(profile, 'nwc.room_geometry', True), log)
    set_opt(options, 'FindMissingMaterials',
            _flag(profile, 'nwc.find_materials', True), log)
    # 2020 and above. set_opt notes the miss in the log and carries on,
    # which is what a 2019 model should do rather than refuse to export.
    set_opt(options, 'ConvertLinkedCADFormats',
            _flag(profile, 'nwc.linked_cad', True), None)
    set_opt(options, 'ConvertLights', _flag(profile, 'nwc.lights', False), None)

    faceting = _number(profile, 'nwc.faceting', 1.0)
    if faceting > 0:
        set_opt(options, 'FacetingFactor', faceting, None)

    mode = _text(profile, 'nwc.parameters', 'all').lower()
    member = enum_member('NavisworksParameters',
                         *NWC_PARAMETER_MODES.get(mode, ('All',)))
    if member is not None:
        set_opt(options, 'Parameters', member, log)

    coords = _text(profile, 'nwc.coordinates', 'shared').lower()
    member = enum_member('NavisworksCoordinates',
                         *NWC_COORDINATE_MODES.get(coords, ('Shared',)))
    if member is not None:
        set_opt(options, 'Coordinates', member, log)

    scope = enum_member('NavisworksExportScope', 'View')
    if scope is not None and view_id is not None:
        set_opt(options, 'ExportScope', scope, log)
        set_opt(options, 'ViewId', view_id, log)
    return options


def export_nwc(doc, jobs, profile, progress=None, should_stop=None,
               report=None):
    """One NWC per job, each scoped to that job's own 3D view."""
    report = report or Report()
    log = []
    total = len(jobs)
    refused = False

    for index, job in enumerate(jobs, 1):
        if should_stop is not None and should_stop():
            report.cancelled = True
            break
        if progress is not None:
            progress(index, total, job.label, 'NWC')

        if refused:
            report.add(Outcome(job.key, job.label, 'NWC', u'', False,
                               u'skipped: the Navisworks exporter refused '
                               u'the first view'))
            continue

        options = build_nwc_options(profile, job.element_id, log)
        if options is None:
            report.add(Outcome(
                job.key, job.label, 'NWC', u'', False,
                u'the Navisworks exporter is not installed on this machine'))
            refused = True
            continue

        folder = job.folders.get('nwc', u'')
        made, error = ps_paths.ensure(folder)
        if not made:
            report.add(Outcome(job.key, job.label, 'NWC', u'', False,
                               u'folder could not be made: {0}'.format(error)))
            continue

        base = job.base_name
        target = os.path.join(folder, base + u'.nwc')
        if _flag(profile, 'out.overwrite', True):
            _remove_if_present(target)
        else:
            target = ps_paths.unique_on_disk(folder, base, u'.nwc')
            base = os.path.splitext(os.path.basename(target))[0]

        debug(u'NWC: exporting "{0}" to {1}'.format(job.label, target))
        try:
            doc.Export(folder, base, options)
        except Exception as err:
            message = u'{0}'.format(err)
            report.add(Outcome(job.key, job.label, 'NWC', target, False,
                               message))
            debug(u'NWC: export threw - {0}'.format(message))
            # A missing exporter throws identically on every view, so one
            # failure is enough to know the rest will fail the same way.
            if 'exporter' in message.lower() or 'not supported' in message.lower():
                refused = True
                report.note(u'The Navisworks exporter add-in does not appear '
                            u'to be installed for this Revit. It ships with '
                            u'Navisworks Manage and Simulate, not with '
                            u'Revit itself.')
            continue

        landed = _wait_for(target)
        report.add(Outcome(
            job.key, job.label, 'NWC', target, landed,
            u'' if landed else u'Revit reported no error but no file appeared'))

    for line in log:
        report.note(line)
    return report


# ==========================================================================
# IFC
#
# IFCExportOptions carries only five typed properties; everything else the
# Revit IFC dialog offers is a named option read by the open source
# exporter. AddOption with a name the installed exporter does not know is
# ignored rather than throwing, so a newer option name on an older
# exporter costs nothing.
#
# The export itself has to sit inside a transaction. Without one Revit
# 2024 and later raise "Starting a transaction is required", and the
# message names neither IFC nor the view.
# ==========================================================================

IFC_VERSIONS = [
    ('IFC2x3CV2', u'IFC 2x3 Coordination View 2.0',
     ('IFC2x3CV2', 'IFC2x3CoordinationView2')),
    ('IFC2x3', u'IFC 2x3 Coordination View', ('IFC2x3',)),
    ('IFCBCA', u'IFC 2x3 GSA Concept Design BIM 2010', ('IFCBCA',)),
    ('IFC2x3FM', u'IFC 2x3 Basic FM Handover View', ('IFC2x3FM',)),
    ('IFC2x2', u'IFC 2x2 Coordination View', ('IFC2x2',)),
    ('IFC2x3COBIE', u'IFC 2x3 COBie 2.4 Design Deliverable',
     ('IFC2x3COBIE', 'IFCCOBIE')),
    ('IFC4RV', u'IFC 4 Reference View', ('IFC4RV',)),
    ('IFC4DTV', u'IFC 4 Design Transfer View', ('IFC4DTV',)),
    ('IFC4', u'IFC 4', ('IFC4',)),
]

IFC_FILE_TYPES = [
    ('ifc', u'IFC', u'.ifc'),
    ('ifcxml', u'IFC XML', u'.ifcXML'),
    ('ifczip', u'Zipped IFC', u'.ifcZIP'),
    ('ifcxmlzip', u'Zipped IFC XML', u'.ifcZIP'),
]

IFC_DETAIL_LEVELS = [
    ('extralow', u'Extra Low', u'0.0'),
    ('low', u'Low', u'0.2'),
    ('medium', u'Medium', u'0.5'),
    ('high', u'High', u'1.0'),
]

IFC_ORIGINS = [
    ('shared', u'Current Shared Coordinates', u'0'),
    ('survey', u'Site Survey Point', u'1'),
    ('project', u'Project Base Point', u'2'),
    ('internal', u'Internal Coordinates', u'3'),
]


def ifc_extension(profile):
    wanted = _text(profile, 'ifc.file_type', 'ifc').lower()
    for key, _label, suffix in IFC_FILE_TYPES:
        if key == wanted:
            return suffix
    return u'.ifc'


def _ifc_lookup(table, wanted, column, fallback):
    for row in table:
        if row[0] == wanted:
            return row[column]
    return fallback


def build_ifc_options(doc, profile, view_id=None, log=None):
    """IFC export options: five typed properties plus the named options."""
    try:
        from Autodesk.Revit.DB import IFCExportOptions
        options = IFCExportOptions()
    except Exception as err:
        if log is not None:
            log.append(u'no IFC exporter on this Revit: {0}'.format(err))
        return None

    wanted = _text(profile, 'ifc.version', 'IFC2x3CV2')
    names = _ifc_lookup(IFC_VERSIONS, wanted, 2, ('IFC2x3CV2',))
    member = enum_member('IFCVersion', *names)
    if member is not None:
        set_opt(options, 'FileVersion', member, log)
    elif log is not None:
        log.append(u'this Revit does not offer IFC version "{0}"; the '
                   u'exporter default was used'.format(wanted))

    try:
        options.SpaceBoundaryLevel = int(
            _text(profile, 'ifc.space_boundaries', '0') or '0')
    except Exception:
        pass
    set_opt(options, 'ExportBaseQuantities',
            _flag(profile, 'ifc.base_quantities', False), None)
    set_opt(options, 'WallAndColumnSplitting',
            _flag(profile, 'ifc.split_by_level', False), None)

    visible_only = _flag(profile, 'ifc.visible_only', True)
    if visible_only and view_id is not None:
        set_opt(options, 'FilterViewId', view_id, log)

    def option(name, value):
        try:
            options.AddOption(name, u'{0}'.format(value))
        except Exception as err:
            if log is not None:
                log.append(u'IFC option "{0}" was refused: {1}'
                           .format(name, err))

    def switch(name, key, default=False):
        option(name, 'true' if _flag(profile, key, default) else 'false')

    switch('VisibleElementsOfCurrentView', 'ifc.visible_only', True)
    switch('ExportAnnotations', 'ifc.export_2d', False)
    switch('ExportRoomsInView', 'ifc.rooms_in_3d', False)
    switch('IncludeSteelElements', 'ifc.steel', True)
    switch('ExportInternalRevitPropertySets', 'ifc.revit_psets', False)
    switch('ExportIFCCommonPropertySets', 'ifc.common_psets', True)
    switch('ExportMaterialPsets', 'ifc.material_psets', False)
    switch('ExportSchedulesAsPsets', 'ifc.schedule_psets', False)
    switch('ExportSpecificSchedules', 'ifc.specific_schedules', False)
    switch('ExportUserDefinedPsets', 'ifc.user_psets', False)
    switch('UseTypePropertiesInInstacePSets', 'ifc.type_properties', False)
    switch('ExportUserDefinedParameterMapping', 'ifc.parameter_map', False)
    switch('ExportPartsAsBuildingElements', 'ifc.parts_as_elements', False)
    switch('ExportSolidModelRep', 'ifc.solid_model', False)
    switch('UseActiveViewGeometry', 'ifc.active_view_geometry', False)
    switch('UseFamilyAndTypeNameForReference', 'ifc.family_type_reference',
           False)
    switch('Use2DRoomBoundaryForVolume', 'ifc.room_boundary_2d', False)
    switch('IncludeSiteElevation', 'ifc.site_elevation', False)
    switch('StoreIFCGUID', 'ifc.store_guid', False)
    switch('ExportBoundingBox', 'ifc.bounding_box', False)
    switch('UseOnlyTriangulation', 'ifc.triangulation', False)
    switch('UseTypeNameOnlyForIfcType', 'ifc.type_name_only', False)
    switch('UseVisibleRevitNameAsEntityName', 'ifc.visible_name', False)

    # "Linked Files" is a dropdown in Revit's dialog and a boolean in the
    # exporter, so it is mapped here rather than stored as a flag.
    separate = _text(profile, 'ifc.linked_files', 'none').lower() == 'separate'
    option('ExportLinkedFiles', 'true' if separate else 'false')

    option('TessellationLevelOfDetail',
           _ifc_lookup(IFC_DETAIL_LEVELS,
                       _text(profile, 'ifc.detail', 'low').lower(), 2, u'0.2'))
    option('SitePlacement',
           _ifc_lookup(IFC_ORIGINS,
                       _text(profile, 'ifc.origin', 'shared').lower(), 2, u'0'))
    option('SpaceBoundaries', _text(profile, 'ifc.space_boundaries', '0'))

    psets_file = _text(profile, 'ifc.user_psets_file', u'')
    if psets_file:
        option('ExportUserDefinedPsetsFileName', psets_file)
    map_file = _text(profile, 'ifc.parameter_map_file', u'')
    if map_file:
        option('ExportUserDefinedParameterMappingFileName', map_file)

    # The id, not the name: ActivePhaseId wants an element id, and the
    # name is only what travels in a template between models.
    phase = _text(profile, 'ifc.phase_id', u'')
    if phase:
        option('ActivePhaseId', phase)
    return options


def export_ifc(doc, jobs, profile, progress=None, should_stop=None,
               report=None):
    """One IFC per job, inside its own transaction."""
    report = report or Report()
    log = []
    total = len(jobs)
    suffix = ifc_extension(profile)

    for index, job in enumerate(jobs, 1):
        if should_stop is not None and should_stop():
            report.cancelled = True
            break
        if progress is not None:
            progress(index, total, job.label, 'IFC')

        options = build_ifc_options(doc, profile, job.element_id, log)
        if options is None:
            report.add(Outcome(job.key, job.label, 'IFC', u'', False,
                               u'no IFC exporter available on this Revit'))
            break

        folder = job.folders.get('ifc', u'')
        made, error = ps_paths.ensure(folder)
        if not made:
            report.add(Outcome(job.key, job.label, 'IFC', u'', False,
                               u'folder could not be made: {0}'.format(error)))
            continue

        base = job.base_name
        target = os.path.join(folder, base + suffix)
        if _flag(profile, 'out.overwrite', True):
            _remove_if_present(target)
        else:
            target = ps_paths.unique_on_disk(folder, base, suffix)
            base = os.path.splitext(os.path.basename(target))[0]

        debug(u'IFC: exporting "{0}" to {1}'.format(job.label, target))
        try:
            from Autodesk.Revit.DB import Transaction
            transaction = Transaction(doc, 'RevoBIM IFC export')
            quiet_transaction(transaction)
            transaction.Start()
            try:
                doc.Export(folder, base, options)
            finally:
                transaction.Commit()
        except Exception as err:
            message = u'{0}'.format(err)
            report.add(Outcome(job.key, job.label, 'IFC', target, False,
                               message))
            debug(u'IFC: export threw - {0}'.format(message))
            continue

        landed = _wait_for(target)
        if not landed:
            landed = _claim_stray(folder, base, target, suffix)
        report.add(Outcome(
            job.key, job.label, 'IFC', target, landed,
            u'' if landed else u'Revit reported no error but no file appeared'))

    for line in log:
        report.note(line)
    return report


def _claim_stray(folder, base, target, suffix):
    """Take a file the exporter named slightly differently.

    The IFC exporter appends the file type's own casing in places, so a
    request for ``.ifc`` can land as ``.IFC``. That is the same file under
    another name, not a failure.
    """
    try:
        wanted = os.path.basename(target).lower()
        for entry in os.listdir(folder):
            if entry.lower() == wanted and entry != os.path.basename(target):
                os.rename(os.path.join(folder, entry), target)
                return os.path.isfile(target)
            if (entry.lower().startswith(base.lower())
                    and entry.lower().endswith(suffix.lower())
                    and entry != os.path.basename(target)):
                os.rename(os.path.join(folder, entry), target)
                return os.path.isfile(target)
    except Exception:
        pass
    return False


# ==========================================================================
# proving a file landed
# ==========================================================================

def folder_snapshot(folder):
    """Every PDF already in a folder, as {path: size}. Never raises."""
    found = {}
    try:
        for entry in os.listdir(folder):
            if not entry.lower().endswith('.pdf'):
                continue
            full = os.path.join(folder, entry)
            try:
                found[full] = os.path.getsize(full)
            except Exception:
                found[full] = -1
    except Exception:
        pass
    return found


def queue_state(printer_name):
    """(jobs waiting, description) for a printer's Windows queue.

    The one question the tool could not answer before: did the driver
    even get the job? Revit reporting a clean submit says only that
    Revit handed it over. A job still sitting in the queue means the
    driver has it and has not finished - which is a completely
    different problem from a driver that saved somewhere unexpected,
    and the two were indistinguishable from the log.
    """
    try:
        from System.Printing import LocalPrintServer
        server = LocalPrintServer()
        queue = server.GetPrintQueue(printer_name)
        try:
            queue.Refresh()
        except Exception:
            pass
        count = int(queue.NumberOfJobs)
        status = u''
        try:
            status = u'{0}'.format(queue.QueueStatus)
        except Exception:
            status = u''
        return count, status
    except Exception as err:
        return -1, u'{0}'.format(err)


def _late_arrivals(folder, before):
    """PDFs that turned up in a folder since a snapshot was taken."""
    try:
        current = folder_snapshot(folder)
    except Exception:
        return []
    return [path for path in current
            if path not in before and current.get(path, 0) > 0]


def driver_wait_budget(render_seconds, floor=60.0, ceiling=420.0):
    """How long to give a driver to write the file it was just sent.

    A fixed fifteen seconds was the old answer and it was wrong for the
    sheets this tool exists for. Revit took nine seconds to spool one A0
    layout; PDF24 then has to convert that spool file, which on a
    drawing with real geometry in it takes longer than the wait did -
    so the tool declared failure while the driver was still working,
    and the file landed seconds after it had given up and moved on.

    Scaled off the render, because a sheet that was slow to spool is a
    sheet that will be slow to convert, and floored high enough that a
    fast render followed by a slow driver is still caught.
    """
    try:
        scaled = float(render_seconds) * 6.0
    except Exception:
        scaled = 0.0
    return max(floor, min(ceiling, scaled))


def wait_for_new_pdf(folder, before, seconds=60.0, pause=0.25,
                     should_stop=None):
    """Wait for a PDF the driver has just written into a folder.

    Matched by "was not there before", not by name, because the whole reason
    this path exists is that the driver names the file itself and we cannot
    predict what it will call it. A file that is there but still growing does
    not count - a driver writes asynchronously and half a PDF is worse than
    none, since it would be moved and reported as a success.
    """
    last_size = {}
    attempts = max(1, int(float(seconds) / max(0.05, pause)))
    for _attempt in range(attempts):
        if should_stop is not None:
            try:
                if should_stop():
                    break
            except Exception:
                pass
        current = folder_snapshot(folder)
        fresh = [path for path in current if path not in before]
        for path in fresh:
            size = current.get(path, 0)
            if size > 0 and last_size.get(path) == size:
                return path
            last_size[path] = size
        time.sleep(pause)
    # One last look, in case it landed complete on the final tick.
    current = folder_snapshot(folder)
    fresh = [path for path in current if path not in before
             and current.get(path, 0) > 0]
    if len(fresh) == 1:
        return fresh[0]
    return u''


def move_into_place(source, target, overwrite=True):
    """Move the driver's file to the name the naming rules asked for."""
    try:
        folder = os.path.dirname(target)
        made, error = ps_paths.ensure(folder)
        if not made:
            return False, error
        if os.path.exists(target):
            if not overwrite:
                target = ps_paths.unique_on_disk(
                    folder, os.path.splitext(os.path.basename(target))[0],
                    u'.pdf')
            else:
                os.remove(target)
        os.rename(source, target)
        return True, target
    except Exception:
        # os.rename will not cross a drive, and the staging folder often is
        # on another one. Fall back to a copy and a delete.
        try:
            import shutil
            shutil.copy2(source, target)
            os.remove(source)
            return True, target
        except Exception as err:
            return False, u'{0}'.format(err)


# ==========================================================================
# finding where a driver actually put the files
#
# A driver that collects the job through its own port saves wherever its own
# settings say, and the user has no particular reason to know where that is.
# Asking them to go and find it is a poor answer when the tool can look.
# ==========================================================================

def _candidate_roots():
    """The folders a PDF driver plausibly writes to, best guesses first."""
    roots = []

    def add(path):
        if not path:
            return
        try:
            full = os.path.normpath(path)
        except Exception:
            return
        if os.path.isdir(full) and full not in roots:
            roots.append(full)

    env = os.environ
    profile = env.get('USERPROFILE', '')
    onedrive = env.get('OneDrive', '') or env.get('OneDriveConsumer', '')
    appdata = env.get('APPDATA', '')
    local = env.get('LOCALAPPDATA', '')
    programdata = env.get('ProgramData', '')

    # The folders a person would pick themselves.
    for base in (profile, onedrive, env.get('OneDriveCommercial', '')):
        for leaf in ('Desktop', 'Documents', 'Downloads'):
            if base:
                add(os.path.join(base, leaf))

    # The folders a PDF tool picks for itself. DiRoots is here because
    # ProSheets installs its own PDF24 instance and points it somewhere of
    # its own - which is exactly the case this scan kept missing.
    for base in (appdata, local, programdata):
        if not base:
            continue
        for vendor in ('PDF24', 'DiRoots', 'DiRoots.ProSheets', 'ProSheets'):
            add(os.path.join(base, vendor))

    add(env.get('TEMP', ''))
    add(env.get('TMP', ''))
    if env.get('PUBLIC'):
        add(os.path.join(env['PUBLIC'], 'Documents'))
    add(profile)
    return roots


# Folders never worth walking: enormous, and no PDF driver writes to them.
SKIP_DIRS = set([
    'windows', 'winsxs', 'program files', 'program files (x86)',
    'programdata\\package cache', '$recycle.bin', 'system volume information',
    'node_modules', '.git', 'packages', 'assembly', 'installer',
    'inetcache', 'webcache', 'code cache', 'gpucache', 'cache2',
    'servicestate', 'crashdumps', 'd3dscache', 'fontcache',
])

MAX_SCAN_DIRS = 5000
MAX_SCAN_SECONDS = 4.0
MAX_SCAN_DEPTH = 6


def _pdfs_newer_than(folder, cutoff, into):
    try:
        for entry in os.listdir(folder):
            if not entry.lower().endswith('.pdf'):
                continue
            full = os.path.join(folder, entry)
            try:
                stamp = os.path.getmtime(full)
            except Exception:
                continue
            if stamp >= cutoff:
                into.append((stamp, full))
    except Exception:
        pass


def find_recent_pdfs(seconds=300):
    """Every PDF written in the last few minutes, newest first.

    Two passes. The quick one looks in the folders a driver is most likely
    to use and usually answers on its own. Only if that finds nothing does
    the slow one walk the user's profile.

    The slow pass descends broadly but **only reads a directory's contents
    when that directory's own timestamp is recent**. Creating a file updates
    the timestamp of the folder holding it and of no other, so this finds a
    PDF six levels down without listing every folder on the machine. It is
    capped by directory count, depth and wall clock, because a diagnostic
    that hangs is worse than one that gives up.
    """
    try:
        cutoff = time.time() - float(seconds)
    except Exception:
        return []

    roots = _candidate_roots()

    quick = []
    for root in roots:
        _pdfs_newer_than(root, cutoff, quick)
        try:
            for entry in os.listdir(root):
                full = os.path.join(root, entry)
                if os.path.isdir(full):
                    _pdfs_newer_than(full, cutoff, quick)
        except Exception:
            continue
    if quick:
        quick.sort(reverse=True)
        debug(u'quick scan found {0} recent PDF(s)'.format(len(quick)))
        return [path for _stamp, path in quick[:40]]

    found = []
    visited = 0
    started = time.time()
    stack = [(root, 0) for root in roots]
    seen = set()
    while stack:
        if visited >= MAX_SCAN_DIRS or (time.time() - started) > MAX_SCAN_SECONDS:
            debug(u'deep scan stopped at {0} folders'.format(visited))
            break
        folder, depth = stack.pop()
        key = os.path.normcase(folder)
        if key in seen:
            continue
        seen.add(key)
        visited += 1

        try:
            if os.path.getmtime(folder) >= cutoff:
                _pdfs_newer_than(folder, cutoff, found)
        except Exception:
            pass

        if depth >= MAX_SCAN_DEPTH:
            continue
        try:
            for entry in os.listdir(folder):
                lowered = entry.lower()
                if lowered in SKIP_DIRS or lowered.startswith('~'):
                    continue
                full = os.path.join(folder, entry)
                try:
                    if os.path.isdir(full):
                        stack.append((full, depth + 1))
                except Exception:
                    continue
        except Exception:
            continue

    found.sort(reverse=True)
    debug(u'deep scan visited {0} folder(s), found {1} recent PDF(s)'
          .format(visited, len(found)))
    return [path for _stamp, path in found[:40]]


def likely_driver_folder(seconds=300):
    """The single folder a driver most likely wrote to, or an empty string.

    Where the recent PDFs are spread over several folders there is no honest
    single answer, so it gives none rather than guessing - but the caller
    still gets the full list to show.
    """
    recent = find_recent_pdfs(seconds)
    folders = []
    for path in recent:
        folder = os.path.dirname(path)
        if folder not in folders:
            folders.append(folder)
    if len(folders) == 1:
        return folders[0]
    return u''


def _remove_if_present(path):
    try:
        if os.path.isfile(path):
            os.remove(path)
            return True
    except Exception:
        pass
    return False


def _wait_for(path, attempts=12, pause=0.25):
    """Wait briefly for a file to appear and stop growing.

    A PDF driver writes asynchronously, so checking immediately after the
    submit call reports a failure for a file that lands a moment later.
    Equally, a file that exists is not necessarily finished - its size is
    checked twice before it counts.
    """
    last_size = -1
    for _attempt in range(attempts):
        try:
            if os.path.isfile(path):
                size = os.path.getsize(path)
                if size > 0 and size == last_size:
                    return True
                last_size = size
        except Exception:
            pass
        time.sleep(pause)
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 0
    except Exception:
        return False


def open_folder(path, select_file=u''):
    """Show a folder in Explorer, with a file picked out where there is one.

    ``/select`` opens the folder the file is actually in and highlights it,
    which lands you at the bottom of the subfolder tree rather than at the
    root wondering which of six date folders the run went into.
    """
    try:
        from System.Diagnostics import Process
        if select_file and os.path.isfile(select_file):
            Process.Start('explorer.exe',
                          u'/select,"{0}"'.format(select_file))
            return True
        if path and os.path.isdir(path):
            Process.Start('explorer.exe', u'"{0}"'.format(path))
            return True
    except Exception:
        pass
    return False


def deepest_written(report):
    """The folder the files actually landed in, and one of the files."""
    written = report.written()
    if not written:
        return (u'', u'')
    # The longest path is the deepest level of the subfolder tree, which is
    # where somebody pressing "Open folder" wants to be.
    best = written[0]
    for outcome in written:
        if len(outcome.path) > len(best.path):
            best = outcome
    return (os.path.dirname(best.path), best.path)
