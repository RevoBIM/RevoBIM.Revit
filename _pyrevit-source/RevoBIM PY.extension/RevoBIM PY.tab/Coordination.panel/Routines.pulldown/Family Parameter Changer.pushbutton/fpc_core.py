# -*- coding: utf-8 -*-
"""RevoBIM PY - Family Parameter Changer - core: version, settings, small
Revit-facing helpers that do not touch the WPF side.

Both script.py and the settings gear read __version__ from here, so
bumping this one line is the only edit a release needs.
"""
import fpc_clr  # noqa - assemblies referenced before anything below

import os

__version__ = '1.3.0'

TOOL_NAME = 'Family Parameter Changer'
SETTINGS_PATH = os.path.join(
    os.environ.get('APPDATA', os.path.expanduser('~')),
    'RevoBIM',
    'family_parameter_changer.txt'
)

DEFAULTS = {
    'settings_version': '1',
    'theme': 'dark',
    'window_w': '1180',
    'window_h': '720',
    'confirm_before_apply': 'on',
    'write_log': 'on',
    'bulk_skip_already_bound': 'on',
}

LOG_PATH = os.path.join(
    os.environ.get('APPDATA', os.path.expanduser('~')),
    'RevoBIM',
    'family_parameter_changer.log'
)

# Keys reset to their new default when a settings file older than the
# listed version is loaded - carried across from Smart Dimensions'
# settings pattern. Empty for v1 since there is nothing to migrate yet.
MIGRATIONS = {
    # '2': ['some_key_whose_meaning_changed'],
}


def eid_value(element_id):
    """ElementId.Value (2024+) preferred, ElementId.IntegerValue as the
    2021-2023 fallback. Never touch either directly anywhere else."""
    if element_id is None:
        return 0
    try:
        return element_id.Value
    except Exception:
        pass
    try:
        return element_id.IntegerValue
    except Exception:
        return 0


def load_settings():
    values = dict(DEFAULTS)
    try:
        if os.path.isfile(SETTINGS_PATH):
            f = open(SETTINGS_PATH, 'r')
            try:
                lines = f.readlines()
            finally:
                f.close()
            file_values = {}
            for line in lines:
                line = line.rstrip(u'\r\n')
                if not line or u'=' not in line:
                    continue
                key, _, val = line.partition(u'=')
                file_values[key.strip()] = val
            file_version = file_values.get('settings_version', '0')
            for min_version, keys in MIGRATIONS.items():
                try:
                    stale = int(file_version) < int(min_version)
                except Exception:
                    stale = True
                if stale:
                    for k in keys:
                        file_values.pop(k, None)
            for key in DEFAULTS:
                if key in file_values:
                    values[key] = file_values[key]
    except Exception:
        values = dict(DEFAULTS)
    return values


def save_settings(values):
    try:
        folder = os.path.dirname(SETTINGS_PATH)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        merged = dict(DEFAULTS)
        merged.update(values)
        merged['settings_version'] = DEFAULTS['settings_version']
        f = open(SETTINGS_PATH, 'w')
        try:
            for key in sorted(merged.keys()):
                f.write(u'{0}={1}\n'.format(key, merged[key]))
        finally:
            f.close()
        return True
    except Exception:
        return False


def get_group_label(definition):
    """Best-effort human label for a parameter's group, covering both the
    ForgeTypeId API (2022+) and the older BuiltInParameterGroup enum."""
    try:
        from Autodesk.Revit.DB import LabelUtils
    except Exception:
        LabelUtils = None
    try:
        gtid = definition.GetGroupTypeId()
        if LabelUtils is not None:
            try:
                return LabelUtils.GetLabelForGroup(gtid)
            except Exception:
                pass
        return gtid.TypeId if gtid is not None else u''
    except Exception:
        pass
    try:
        bip_group = definition.ParameterGroup
        if LabelUtils is not None:
            try:
                return LabelUtils.GetLabelFor(bip_group)
            except Exception:
                pass
        return str(bip_group)
    except Exception:
        return u''


def read_shared_parameter_file(app):
    """Returns a list of (group_name, definitions) tuples read from the
    application's currently-set shared parameter file, or an empty list
    with a reason string if none is set / it cannot be opened."""
    try:
        spf = app.OpenSharedParameterFile()
    except Exception:
        return [], u'Could not open the shared parameter file.'
    if spf is None:
        return [], u'No shared parameter file is set for this session.'
    groups = []
    try:
        for g in spf.Groups:
            defs = []
            for d in g.Definitions:
                try:
                    defs.append(d)
                except Exception:
                    continue
            groups.append((g.Name, defs))
    except Exception:
        return [], u'Could not read groups from the shared parameter file.'
    return groups, None


def shared_param_display_name(definition):
    try:
        return definition.Name
    except Exception:
        return u'(unnamed)'


def shared_param_guid(definition):
    try:
        return definition.GUID.ToString()
    except Exception:
        return u''


# ==================== bulk rebind planning ====================

BULK_ALL = u'<All families>'


def parameter_census(families, scope_category=None):
    """{param_name: {'families': n, 'shared': n, 'unshared': n}} across the
    families in scope. Blocked families (in-place, not editable) are left
    out because they cannot be rebound anyway."""
    census = {}
    for fam in families:
        if fam.get('blocked'):
            continue
        if scope_category and scope_category != BULK_ALL and fam['category'] != scope_category:
            continue
        for prow in fam['params']:
            entry = census.get(prow['name'])
            if entry is None:
                entry = {'families': 0, 'shared': 0, 'unshared': 0}
                census[prow['name']] = entry
            entry['families'] += 1
            if prow['is_shared']:
                entry['shared'] += 1
            else:
                entry['unshared'] += 1
    return census


def plan_bulk(families, scope_category, param_name, shared_guid, skip_already_bound=True):
    """Returns (targets, skipped) where targets is a list of family dicts
    that carry `param_name` and should be queued, and skipped is a list of
    (family_name, reason) for the ones left out. Pure, tested on the
    bench. A family already bound to exactly this GUID is skipped when
    asked, since rebinding it would be a no-op with a family-editor cost."""
    targets = []
    skipped = []
    for fam in families:
        if scope_category and scope_category != BULK_ALL and fam['category'] != scope_category:
            continue
        prow = None
        for candidate in fam['params']:
            if candidate['name'] == param_name:
                prow = candidate
                break
        if prow is None:
            continue
        if fam.get('blocked'):
            skipped.append((fam['name'], fam['blocked']))
            continue
        if skip_already_bound and prow['is_shared'] and prow.get('guid') == shared_guid:
            skipped.append((fam['name'], u'already bound to this shared parameter'))
            continue
        targets.append(fam)
    return targets, skipped


# ==================== run log ====================

def append_log(lines, path=None):
    """Appends timestamped lines to the run log. Never raises - a log
    that cannot be written must not cost the run."""
    import datetime
    target = path or LOG_PATH
    try:
        folder = os.path.dirname(target)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        stamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        f = open(target, 'a')
        try:
            for line in lines:
                f.write(u'{0}  {1}\n'.format(stamp, line))
        finally:
            f.close()
        return True
    except Exception:
        return False


def format_result_line(result):
    """One log / clipboard line for a handler result dict."""
    if result.get('info'):
        mark = u'INFO  '
    elif result.get('ok'):
        mark = u'OK    '
    else:
        mark = u'FAILED'
    family = result.get('family', u'')
    param = result.get('param', u'')
    message = result.get('message', u'')
    if param:
        return u'{0}  {1}  .  {2}  -  {3}'.format(mark, family, param, message)
    return u'{0}  {1}  -  {2}'.format(mark, family, message)
