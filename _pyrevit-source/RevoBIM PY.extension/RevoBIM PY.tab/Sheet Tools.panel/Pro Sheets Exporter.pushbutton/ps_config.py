# -*- coding: utf-8 -*-
"""Settings and per-project export profiles.

Everything persists as plain ``key=value`` text under ``%APPDATA%\\RevoBIM\\``,
not JSON: no dependency on a module whose availability varies with the
IronPython engine, and the files stay readable and hand-editable.

A missing or damaged file falls back to the defaults **key by key**, and keys
from an older version are ignored rather than breaking the load. That is the
whole reliability story here - a profile written by v1.0.0 must still open in
v1.4.0 and vice versa.

Two stores:

* **settings** - one file, global to the user. Theme, the default printer, how
  the window opens. Things that are a house standard rather than a job.
* **profiles** - the whole export configuration, saved by name **against the
  project**, so each job keeps its own list and they are all still there next
  time the model opens. This is the "template for the session" from the top
  right of the window.
"""

import ps_refs  # noqa: F401  - must be first

import os
import re

from System import Environment


# ==========================================================================
# where things live
# ==========================================================================

def appdata_root():
    """``%APPDATA%\\RevoBIM``, created if it is not there yet."""
    try:
        base = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData)
    except Exception:
        base = os.path.expanduser('~')
    folder = os.path.join(base, 'RevoBIM')
    try:
        if not os.path.isdir(folder):
            os.makedirs(folder)
    except Exception:
        pass
    return folder


def settings_path():
    return os.path.join(appdata_root(), 'pro_sheets_exporter.txt')


def profiles_root():
    folder = os.path.join(appdata_root(), 'pro_sheets_profiles')
    try:
        if not os.path.isdir(folder):
            os.makedirs(folder)
    except Exception:
        pass
    return folder


def error_path():
    folder = os.path.join(appdata_root(), 'logs')
    try:
        if not os.path.isdir(folder):
            os.makedirs(folder)
    except Exception:
        folder = appdata_root()
    return os.path.join(folder, 'pro_sheets_exporter_last_error.txt')


_UNSAFE = re.compile(r'[^A-Za-z0-9 _.\-]+')


def safe_name(text, fallback='unnamed'):
    """A string that is safe as a file or folder name on Windows."""
    cleaned = _UNSAFE.sub('_', str(text or '')).strip().strip('.')
    cleaned = re.sub(r'\s+', ' ', cleaned)
    if not cleaned:
        return fallback
    return cleaned[:96]


def project_key(doc):
    """A folder name identifying this project, so profiles do not mix.

    The model's file name is used where there is one; an unsaved model falls
    back to its title, and something with no title at all lands in a shared
    ``_unsaved`` bucket rather than failing.
    """
    try:
        path = getattr(doc, 'PathName', '') or ''
        if path:
            return safe_name(os.path.splitext(os.path.basename(path))[0], '_unsaved')
    except Exception:
        pass
    try:
        title = getattr(doc, 'Title', '') or ''
        if title:
            return safe_name(title, '_unsaved')
    except Exception:
        pass
    return '_unsaved'


def project_folder(doc):
    folder = os.path.join(profiles_root(), project_key(doc))
    try:
        if not os.path.isdir(folder):
            os.makedirs(folder)
    except Exception:
        pass
    return folder


# ==========================================================================
# the key=value store
# ==========================================================================

def _encode(value):
    text = u'' if value is None else u'{0}'.format(value)
    return text.replace(u'\\', u'\\\\').replace(u'\r', u'').replace(u'\n', u'\\n')


def _decode(text):
    out = []
    index = 0
    length = len(text)
    while index < length:
        ch = text[index]
        if ch == u'\\' and index + 1 < length:
            nxt = text[index + 1]
            if nxt == u'n':
                out.append(u'\n')
                index += 2
                continue
            if nxt == u'\\':
                out.append(u'\\')
                index += 2
                continue
        out.append(ch)
        index += 1
    return u''.join(out)


def read_store(path):
    """Every key=value pair in a file, as a dictionary. Never raises.

    A line with no ``=`` is a comment or damage and is skipped; the rest of
    the file still loads. That is deliberate - one bad line must not cost the
    user their whole profile.
    """
    found = {}
    try:
        if not os.path.isfile(path):
            return found
        handle = open(path, 'rb')
        try:
            raw = handle.read()
        finally:
            handle.close()
        try:
            text = raw.decode('utf-8')
        except Exception:
            text = raw.decode('latin-1')
        for line in text.replace(u'\r\n', u'\n').split(u'\n'):
            line = line.strip()
            if not line or line.startswith(u'#'):
                continue
            if u'=' not in line:
                continue
            key, _, value = line.partition(u'=')
            found[key.strip()] = _decode(value)
    except Exception:
        pass
    return found


def write_store(path, values, banner=None):
    """Write a dictionary out as key=value text. True when it landed."""
    try:
        folder = os.path.dirname(path)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)
        lines = []
        if banner:
            for line in str(banner).split('\n'):
                lines.append(u'# ' + line)
        for key in sorted(values.keys()):
            lines.append(u'{0}={1}'.format(key, _encode(values[key])))
        body = u'\n'.join(lines) + u'\n'
        handle = open(path, 'wb')
        try:
            handle.write(body.encode('utf-8'))
        finally:
            handle.close()
        return True
    except Exception:
        return False


# ==========================================================================
# typed reads, each falling back on its own
# ==========================================================================

def get_text(store, key, default=u''):
    value = store.get(key)
    if value is None:
        return default
    return value


def get_bool(store, key, default=False):
    value = store.get(key)
    if value is None:
        return default
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def get_int(store, key, default=0):
    value = store.get(key)
    if value is None:
        return default
    try:
        return int(float(str(value).strip()))
    except Exception:
        return default


def get_float(store, key, default=0.0):
    value = store.get(key)
    if value is None:
        return default
    try:
        return float(str(value).strip())
    except Exception:
        return default


def get_list(store, key, default=None):
    """A list written as a tab-separated value. Empty means an empty list."""
    value = store.get(key)
    if value is None:
        return list(default or [])
    text = str(value)
    if not text.strip():
        return []
    return [part for part in text.split(u'\t')]


def put_list(values):
    return u'\t'.join([u'{0}'.format(v) for v in values])


# ==========================================================================
# global settings
# ==========================================================================

def register_path(doc):
    """Where this project's hand-ticked register selection is kept."""
    return os.path.join(appdata_root(), 'prosheets_register',
                        project_key(doc) + '.txt')


def read_register_excluded(doc):
    """The sheet keys left out of the register by hand, or None if never set.

    Kept as the ones left *out*, so a sheet added to the model after the
    list was saved starts included - a register that quietly misses new
    drawings is the failure worth designing against.
    """
    store = read_store(register_path(doc))
    if 'excluded' not in store:
        return None
    return set([key for key in get_list(store, 'excluded') if key])


def write_register_excluded(doc, keys):
    return _write_register_value(doc, 'excluded', sorted(keys))


def read_register_skipped(doc):
    """The disciplines unticked on the register's tab strip, by name."""
    store = read_store(register_path(doc))
    return set([name for name in get_list(store, 'skip_tabs') if name])


def write_register_skipped(doc, names):
    return _write_register_value(doc, 'skip_tabs', sorted(names))


def encode_heading_colours(colours):
    """{heading: '#RRGGBB'} as list entries, 'heading=#RRGGBB'."""
    return [u'{0}={1}'.format(name, colour)
            for name, colour in sorted((colours or {}).items())
            if name and colour]


def decode_heading_colours(entries):
    """The other way. A heading may itself hold '=': the colour is
    whatever follows the last one."""
    found = {}
    for entry in entries or ():
        name, mark, colour = u'{0}'.format(entry).rpartition(u'=')
        if mark and name and colour.startswith(u'#') and len(colour) == 7:
            found[name] = colour.upper()
    return found


def read_heading_colours(doc):
    """The colours picked for the register's headings in this project
    (1.52.0), by heading name."""
    store = read_store(register_path(doc))
    return decode_heading_colours(get_list(store, 'heading_colours'))


def write_heading_colours(doc, colours):
    return _write_register_value(doc, 'heading_colours',
                                 encode_heading_colours(colours))


def _write_register_value(doc, key, values):
    """One list in the project's register file, keeping the others."""
    path = register_path(doc)
    store = read_store(path)
    store[key] = put_list(values)
    return write_store(path, store,
                       'RevoBIM PY - Pro Sheets Exporter\nDocument Register '
                       'choices for this project: sheets left out by hand '
                       '(element ids) and disciplines left out of the Excel '
                       'export.')


def staging_key(printer):
    """The settings key holding where a driver saves.

    Per printer, because it is a fact about the driver and not about the
    job. Lives here rather than in a window so the setup dialog and the
    Format tab cannot drift into writing different keys.
    """
    return 'staging.' + safe_name(printer, 'printer')


# The RD9 issue sheet's status legend and recipients.
# The BGL TIDP register's status legend, from 1.44.0: the suitability codes
# the Issue Status row carries.
REG_LEGEND = [u'S0 = WIP', u'S1 = Coordination', u'S2 = Information',
              u'S3 = Review/Comment', u'S4 = Stage Approval',
              u'S5 = Authorisation']
# What they were from 1.24.0 to 1.43.0 (the RD9 sheet's), so the migration
# can tell a default nobody touched from a list somebody typed.
RD9_LEGEND = [u'Pro = Proposal', u'D = Draft', u'P = Preliminary',
              u'PL = Planning', u'T = Tender', u'CN = Contract',
              u'C = Construction', u'AB = As Built', u'SK = Sketch']
RD9_TITLE = u'RD9 - Document Register & Issue Sheet'
# 1.44.0's title. The form went back to the RD9 name in 1.45.0.
TIDP_TITLE = u'TIDP - Task Information Delivery Plan'
REG_TITLE = RD9_TITLE
# Where a sheet's scale comes from in the register: a text parameter on the
# sheet or its title block, or Revit's own viewport scales.
SCALE_PARAMETER = 'parameter'
SCALE_REVIT = 'revit'
REG_ISSUED_TO = [u'Client', u'Architect', u'Principal Designer',
                 u'Project Manager', u'Structural Engineer', u'Fire Engineer',
                 u'Main Contractor']


SETTINGS_DEFAULTS = {
    # 'theme' is the pre-1.10.0 key. The chip used to write the resolved
    # palette into it, so a value there cannot be told apart from a
    # deliberate pin - which is why 1.10.0 reads a new key instead and
    # lets everybody start on follow again.
    'theme': 'follow',          # legacy, no longer written
    'theme_mode': 'follow',     # follow | dark | light
    'default_printer': '',      # blank means Revit's own PDF export
    'window_width': '1240',
    'window_height': '820',
    'last_profile': '',
    'remember_last_profile': '1',
    'open_folder_after_export': '1',
    'report_always': '1',
    'debug': '0',
    'suppress_dialogs': '1',
    'settle_ms': '250',
    'column_widths': '',
    # First run. Until this is set the setup window opens with the tool:
    # every setting it asks about is per machine, and a template that
    # works on one desk fails on the next with nothing to show for it.
    'setup_done': '0',
    'default_root': '',
    # Revit's own exporter is the house default from 1.16.0. A print
    # driver is opt in, per machine, and a template asking for one does
    # not override this - see usable_printer in ps_window for why that
    # is the way round it is.
    'prefer_native_pdf': '1',
    # What this office calls the two parameters the Selection page
    # shows by default and sorts by. Names, not ids, because they are
    # shared parameters and a different client's model calls them
    # something else. Setup asks; blank means "this project has none".
    'param_series': 'BGL_Sheet Series',
    'param_discipline': 'BGL_Sheet Discipline',
    # The Document Register's Excel form. Lists are tab separated, one
    # entry per line in the settings window. The logo is copied into
    # %APPDATA%\RevoBIM when it is chosen, so the form keeps it after the
    # original is moved or the network drive is not there.
    # The defaults are the RD9 issue sheet's own, from 1.24.0.
    'reg_title': REG_TITLE,
    'reg_logo': '',
    'reg_client_logo': '',
    'reg_legend': u'\t'.join(REG_LEGEND),
    'reg_issued_to': u'\t'.join(REG_ISSUED_TO),
    'reg_footer': '',
    'reg_paper': 'A4 portrait',
    # The heading of the register's current revision column - orange, just
    # before the issues from 1.44.0. Blank leaves the column off.
    'reg_snapshot': 'Current Rev',
    # 1.44.0: the sheet parameter each issue's status is filled from (the
    # Revision Manager's Issue Status column), and where the Scale column
    # comes from - a text parameter, read from the sheet then its title
    # block, or Revit's own viewport scales.
    'reg_status_param': 'BGL_Sheet Status',
    'reg_scale_mode': SCALE_PARAMETER,
    'reg_scale_param': 'BGL_Title Block Scale Text',
    # The Revision Manager, opened from its own button, opens again after
    # Apply so the next change can follow straight on.
    'rev_reopen': '1',
    # The order the manager's columns were last dragged into: fields,
    # comma separated. Blank is the first order.
    'rev_column_order': '',
    # 1.34.0: every Sheet series cell opens expanded, listing them all
    'rev_series_open': '1',
    # 1.38.0: the modeless manager follows the selection in Revit - pick a
    # revision cloud in a view and the list goes to its revision.
    'rev_follow_selection': '1',
    # 1.39.0: the Pro Sheets window's size, - and + in its header.
    'ui_scale': '1',
    # The register tab's own state between sessions.
    'reg_add_to_export': '0',
    'reg_last_set': '',
    'reg_show': 'all',
    # Show only the revision columns the drawings on screen carry, and
    # write only those a worksheet's drawings carry. On by default.
    'reg_hide_unused': '1',
    # Bumped when a default changes in a way an existing settings file
    # would otherwise keep overriding. See migrate().
    'settings_version': '6',
}


# The version this build's defaults belong to.
SETTINGS_VERSION = 6

# What the register defaults were before 1.24.0, so the migration can tell
# a default nobody touched from a list somebody typed.
OLD_REG_DEFAULTS = {
    'reg_title': u'Document Register & Issue Sheet',
    'reg_legend': u'\t'.join([u'P - Preliminary', u'I - Information',
                               u'T - Tender', u'C - Construction',
                               u'AB - As Built']),
    'reg_issued_to': u'\t'.join([u'Client', u'Architect',
                                  u'Structural Engineer',
                                  u'Main Contractor', u'File']),
    'reg_paper': u'A3',
}


class Settings(object):
    """The global settings, loaded once and saved on change."""

    def __init__(self):
        self.store = dict(SETTINGS_DEFAULTS)
        self.store.update(read_store(settings_path()))
        self.migrated = self.migrate()

    def migrate(self):
        """Bring an older settings file up to this build's defaults.

        A default only applies where the file says nothing, so changing
        one does nothing for anybody who already has the tool - and a
        machine that was pointed at a print driver back when the tool
        chose one for itself would keep going to that driver forever.
        That is the whole reason this exists.

        Returns whether anything changed, so the caller can save.
        """
        try:
            found = int(get_text(self.store, 'settings_version', '1') or '1')
        except Exception:
            found = 1
        if found >= SETTINGS_VERSION:
            return False

        # To 2: Revit's own exporter becomes the default, and a driver
        # chosen automatically by 1.9.1 to 1.13.0 is let go of. Nobody
        # picked those deliberately; the tool picked them, and on every
        # machine they were tried on they wrote nothing.
        if found < 2:
            self.store['default_printer'] = ''
            self.store['prefer_native_pdf'] = '1'

        # To 3: runs are quiet by default. Anybody who had turned this
        # on already keeps it on; the change is for everybody who never
        # touched it and was getting a confirmation every export.
        if found < 3:
            self.store['suppress_dialogs'] = '1'

        # To 4: Revit's own PDF exporter again, for everybody. Setup wrote a
        # driver into default_printer whenever a driver option was clicked
        # - testing PDF24 once was enough - and from then on every run went
        # to it. The driver stays available in Setup; it is just no longer
        # the default anybody is left on by accident. And the register's
        # defaults become the RD9 issue sheet's, where they were never
        # changed: a list somebody typed is kept as typed.
        if found < 4:
            self.store['default_printer'] = ''
            self.store['prefer_native_pdf'] = '1'
            for key, old in OLD_REG_DEFAULTS.items():
                if get_text(self.store, key, old) == old:
                    self.store[key] = SETTINGS_DEFAULTS[key]
            paper = u'{0}'.format(get_text(self.store, 'reg_paper', u'')
                                  ).strip()
            if paper and len(paper.split()) == 1:
                self.store['reg_paper'] = u'{0} portrait'.format(paper)

        # To 5: the register becomes the BGL TIDP form - its title, the S0
        # to S5 legend, and the current revision column called Current Rev.
        # Each only where the RD9 default was never changed.
        if found < 5:
            for key, old, new in (
                    ('reg_title', RD9_TITLE, TIDP_TITLE),
                    ('reg_legend', u'\t'.join(RD9_LEGEND),
                     u'\t'.join(REG_LEGEND)),
                    ('reg_snapshot', u'Asite Snapshot', u'Current Rev')):
                if get_text(self.store, key, old) == old:
                    self.store[key] = new

        # To 6: the title back to the RD9 name, where 1.44.0 set it and
        # nobody has changed it since.
        if found < 6:
            if get_text(self.store, 'reg_title', TIDP_TITLE) == TIDP_TITLE:
                self.store['reg_title'] = RD9_TITLE

        self.store['settings_version'] = u'{0}'.format(SETTINGS_VERSION)
        return True

    def text(self, key, default=None):
        if default is None:
            default = SETTINGS_DEFAULTS.get(key, u'')
        return get_text(self.store, key, default)

    def flag(self, key, default=None):
        if default is None:
            default = get_bool(SETTINGS_DEFAULTS, key, False)
        return get_bool(self.store, key, default)

    def number(self, key, default=None):
        if default is None:
            default = get_int(SETTINGS_DEFAULTS, key, 0)
        return get_int(self.store, key, default)

    def set(self, key, value):
        self.store[key] = u'{0}'.format(value)

    def save(self):
        return write_store(
            settings_path(), self.store,
            'RevoBIM PY - Pro Sheets Exporter\nGlobal settings. Safe to edit by hand.')


# ==========================================================================
# profiles
# ==========================================================================

PROFILE_DEFAULTS = {
    # what is being exported
    'mode': 'sheets',                 # sheets | views
    'formats': 'pdf',                 # tab separated: pdf dwg nwc ifc
    'selected': '',                   # tab separated sheet numbers / view names

    # PDF
    'pdf.printer': '',                # blank = Revit's own PDF export
    'pdf.staging': '',                # a driver that saves where it likes
    'pdf.placement': 'center',        # center | offset
    'pdf.margin': 'nomargin',         # nomargin | printerlimit | usermargin
    'pdf.offset_x': '0.0',
    'pdf.offset_y': '0.0',
    'pdf.zoom_mode': 'zoom',          # fit | zoom
    'pdf.zoom': '100',
    'pdf.hidden_line': 'vector',      # vector | raster
    'pdf.raster_quality': 'high',     # low | medium | high | presentation
    'pdf.colors': 'color',            # color | grayscale | blackline
    'pdf.view_links_blue': '1',
    'pdf.hide_ref_planes': '1',
    'pdf.hide_unreferenced_tags': '1',
    'pdf.hide_scope_boxes': '1',
    'pdf.hide_crop_boundaries': '1',
    'pdf.replace_halftone': '0',
    'pdf.mask_coincident': '0',
    'pdf.combine': '0',
    'pdf.keep_paper_size': '1',
    'pdf.order': '',                  # tab separated keys, the combine order

    # DWG
    'dwg.setup': '',                  # an export setup saved in the model
    'dwg.external_refs': '0',      # off = links bound into the DWG
    'dwg.shared_coords': '1',
    'dwg.version': 'default',
    'dwg.export_views_on_sheet': '0',

    # NWC. The defaults are Revit's own Navisworks export defaults, which
    # are also what the reference screenshots show.
    'nwc.parts': '0',
    'nwc.element_ids': '1',
    'nwc.parameters': 'all',          # all | elements | none
    'nwc.properties': '0',
    'nwc.linked_files': '0',
    'nwc.room_as_attribute': '1',
    'nwc.urls': '1',
    'nwc.coordinates': 'shared',      # shared | internal
    'nwc.divide_levels': '1',
    'nwc.room_geometry': '1',
    'nwc.find_materials': '1',
    'nwc.linked_cad': '1',
    'nwc.lights': '0',
    'nwc.faceting': '1',

    # IFC
    'ifc.version': 'IFC2x3CV2',
    'ifc.file_type': 'ifc',           # ifc | ifcxml | ifczip | ifcxmlzip
    'ifc.phase': '',                  # blank = the default phase
    # The phase's element id, resolved against this model when the run
    # starts. The name above is what travels in a template; an id from
    # another model would point at whatever happens to share the number.
    'ifc.phase_id': '',
    'ifc.space_boundaries': '0',      # 0 | 1 | 2
    'ifc.origin': 'shared',           # shared | project | internal | survey
    'ifc.split_by_level': '0',
    'ifc.steel': '1',
    'ifc.linked_files': 'none',       # none | separate
    'ifc.export_2d': '0',
    'ifc.visible_only': '1',
    'ifc.rooms_in_3d': '0',
    'ifc.detail': 'low',              # extralow | low | medium | high
    'ifc.revit_psets': '0',
    'ifc.common_psets': '1',
    'ifc.base_quantities': '0',
    'ifc.material_psets': '0',
    'ifc.schedule_psets': '0',
    'ifc.specific_schedules': '0',
    'ifc.user_psets': '0',
    'ifc.type_properties': '0',
    'ifc.user_psets_file': '',
    'ifc.parameter_map': '0',
    'ifc.parameter_map_file': '',
    'ifc.parts_as_elements': '0',
    'ifc.solid_model': '0',
    'ifc.active_view_geometry': '0',
    'ifc.family_type_reference': '0',
    'ifc.room_boundary_2d': '0',
    'ifc.site_elevation': '0',
    'ifc.store_guid': '0',
    'ifc.bounding_box': '0',
    'ifc.triangulation': '0',
    'ifc.type_name_only': '0',
    'ifc.visible_name': '0',

    # naming
    'name.rule_count': '2',
    'name.rule.1.param': 'Sheet Number',
    'name.rule.1.prefix': '',
    'name.rule.1.suffix': '',
    'name.rule.1.sep': '-',
    'name.rule.2.param': 'Sheet Name',
    'name.rule.2.prefix': '',
    'name.rule.2.suffix': '',
    'name.rule.2.sep': '',

    # where it goes
    'out.root': '',
    # The house layout: project, then a stamp for this issue, then the
    # sheet series. A token that resolves to nothing becomes _unset
    # rather than collapsing the level, so a model without
    # BGL_Sheet Series still lands somewhere findable.
    'out.tokens': '{Project Name}\\{Year}-{Month}-{Day}_{Hour}_{Minute}'
                  '\\{BGL_Sheet Series}',
    'out.folder_per_format': '1',
    'out.overwrite': '1',

    # filters
    'filter.sheet_set': '',
    'filter.active_only': '0',
    'filter.search': '',
    'cols': '',                   # the whole Selection column order
    'sort.stack': '',
    'sort.grouped': '1',       # colour and collapse runs of matching values
    'colwidths': '',
    'win.width': '',
    'win.height': '',

    # How the run behaves. Kept in the template as well as globally: the
    # global value is the default when no template is loaded, the template
    # wins once one is.
    # Quiet by default. Export starts on the first press: the
    # confirmation existed because a run used to be hard to undo, and
    # the Create tab now shows every path before anything happens.
    'run.suppress_dialogs': '1',
    'run.open_folder': '1',
    'run.debug': '0',
}


# ==========================================================================
# template bundles
#
# One file, any number of templates, so a house standard can be handed round
# rather than rebuilt per machine. Same plain key=value text as everything
# else, with a banner line starting each template - readable, diffable, and
# hand-editable, which a zip or a pickle would not be.
# ==========================================================================

BUNDLE_EXTENSION = '.rbtpl'
BUNDLE_MARKER = '@template='
BUNDLE_HEADER = ('RevoBIM PY - Pro Sheets Exporter template bundle\n'
                 'One or more templates. Each begins with a line reading\n'
                 '@template=<name>. Safe to edit by hand.')


def write_bundle(path, templates):
    """Write {name: values} out as one file. True when it landed."""
    try:
        lines = []
        for line in BUNDLE_HEADER.split('\n'):
            lines.append(u'# ' + line)
        for name in sorted(templates.keys(), key=lambda n: n.lower()):
            values = templates[name]
            lines.append(u'')
            lines.append(u'{0}{1}'.format(BUNDLE_MARKER, name))
            for key in sorted(values.keys()):
                lines.append(u'{0}={1}'.format(key, _encode(values[key])))
        body = u'\n'.join(lines) + u'\n'
        handle = open(path, 'wb')
        try:
            handle.write(body.encode('utf-8'))
        finally:
            handle.close()
        return True
    except Exception:
        return False


def read_bundle(path):
    """Read a bundle back as {name: values}. Never raises.

    A file with no @template line at all is treated as a single template
    named after the file, so a plain profile saved from
    %APPDATA% can be handed to somebody and still load.
    """
    found = {}
    try:
        if not os.path.isfile(path):
            return found
        handle = open(path, 'rb')
        try:
            raw = handle.read()
        finally:
            handle.close()
        try:
            text = raw.decode('utf-8')
        except Exception:
            text = raw.decode('latin-1')

        current = None
        loose = {}
        for line in text.replace(u'\r\n', u'\n').split(u'\n'):
            line = line.strip()
            if not line or line.startswith(u'#'):
                continue
            if line.startswith(BUNDLE_MARKER):
                current = line[len(BUNDLE_MARKER):].strip() or u'Unnamed'
                found.setdefault(current, {})
                continue
            if u'=' not in line:
                continue
            key, _, value = line.partition(u'=')
            target = found[current] if current is not None else loose
            target[key.strip()] = _decode(value)

        if not found and loose:
            name = safe_name(os.path.splitext(os.path.basename(path))[0],
                             'Imported')
            found[name] = loose
    except Exception:
        pass
    return found


def unique_template_name(taken, name):
    """A name nothing else is using, adding (1), (2) and so on.

    Merging is the common case and a clash is not an error - somebody has
    two versions of "Standard issue" and wants both, or they would have
    chosen to replace.
    """
    lowered = set([u'{0}'.format(n).lower() for n in taken])
    base = u'{0}'.format(name).strip() or u'Unnamed'
    if base.lower() not in lowered:
        return base
    index = 1
    while index < 500:
        candidate = u'{0} ({1})'.format(base, index)
        if candidate.lower() not in lowered:
            return candidate
        index += 1
    return base


def profile_names(doc):
    """Every profile saved against this project, alphabetically."""
    names = []
    try:
        folder = project_folder(doc)
        for entry in os.listdir(folder):
            if entry.lower().endswith('.txt'):
                names.append(os.path.splitext(entry)[0])
    except Exception:
        pass
    names.sort(key=lambda n: n.lower())
    return names


def profile_path(doc, name):
    return os.path.join(project_folder(doc), safe_name(name, 'profile') + '.txt')


def load_profile(doc, name):
    """A profile merged over the defaults, so missing keys never bite."""
    values = dict(PROFILE_DEFAULTS)
    if name:
        values.update(read_store(profile_path(doc, name)))
    return values


def save_profile(doc, name, values):
    banner = ('RevoBIM PY - Pro Sheets Exporter\n'
              'Export profile "{0}" for project "{1}".\n'
              'Safe to edit by hand. Unknown keys are ignored on load.'
              .format(name, project_key(doc)))
    return write_store(profile_path(doc, name), values, banner)


# ==========================================================================
# IFC setups
#
# Kept apart from the templates and not per project. An IFC setup is a
# house standard - the same one is wanted on every job - whereas a
# template is about one project's folders and sheet list.
# ==========================================================================

IFC_SETUP_EXTENSION = '.rbifc'


def ifc_setups_root():
    folder = os.path.join(appdata_root(), 'ifc_setups')
    try:
        if not os.path.isdir(folder):
            os.makedirs(folder)
    except Exception:
        pass
    return folder


def ifc_setup_names():
    names = []
    try:
        for entry in os.listdir(ifc_setups_root()):
            if entry.lower().endswith(IFC_SETUP_EXTENSION):
                names.append(os.path.splitext(entry)[0])
    except Exception:
        pass
    names.sort(key=lambda n: n.lower())
    return names


def ifc_setup_path(name):
    return os.path.join(ifc_setups_root(),
                        safe_name(name, 'setup') + IFC_SETUP_EXTENSION)


def read_ifc_setup(path):
    """The ifc.* keys held in a setup file, merged over the defaults."""
    values = {}
    for key, value in read_store(path).items():
        if u'{0}'.format(key).startswith('ifc.'):
            values[key] = value
    return values


def write_ifc_setup(path, values):
    keep = dict([(key, value) for key, value in values.items()
                 if u'{0}'.format(key).startswith('ifc.')])
    banner = ('RevoBIM PY - Pro Sheets Exporter\n'
              'IFC export setup. Safe to edit by hand.\n'
              'Unknown keys are ignored on load.')
    return write_store(path, keep, banner)


def delete_profile(doc, name):
    try:
        path = profile_path(doc, name)
        if os.path.isfile(path):
            os.remove(path)
            return True
    except Exception:
        pass
    return False


def defaults():
    """A fresh profile dictionary, untouched by anything on disk."""
    return dict(PROFILE_DEFAULTS)
