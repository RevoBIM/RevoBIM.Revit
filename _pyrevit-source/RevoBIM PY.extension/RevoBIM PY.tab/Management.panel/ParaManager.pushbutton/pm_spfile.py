# -*- coding: utf-8 -*-
"""Shared parameter file round trip. No WPF and no Revit.

The file is kept as the lines it came in as. Anything not edited is written back
character for character: comments, unknown lines, unknown columns, order, line
endings and encoding. Only edited rows are rebuilt.
"""
import codecs
import re
import uuid

YES = u'1'
NO = u'0'
TEMPLATE = (u'# This is a Revit shared parameter file.\r\n# Do not edit manually.\r\n'
            u'*META\tVERSION\tMINVERSION\r\nMETA\t2\t1\r\n*GROUP\tID\tNAME\r\n'
            u'*PARAM\tGUID\tNAME\tDATATYPE\tDATACATEGORY\tGROUP\tVISIBLE\tDESCRIPTION'
            u'\tUSERMODIFIABLE\tHIDEWHENNOVALUE\r\n')
OPTIONAL_DEFAULTS = {'USERMODIFIABLE': YES, 'HIDEWHENNOVALUE': NO}

# (file token, label). A token not listed still loads and saves as itself.
SP_TYPES = [
    (u'TEXT', u'Text'), (u'MULTILINETEXT', u'Multiline Text'), (u'INTEGER', u'Integer'),
    (u'NUMBER', u'Number'), (u'LENGTH', u'Length'), (u'AREA', u'Area'),
    (u'VOLUME', u'Volume'), (u'ANGLE', u'Angle'), (u'SLOPE', u'Slope'),
    (u'CURRENCY', u'Currency'), (u'MASS_DENSITY', u'Mass Density'), (u'URL', u'URL'),
    (u'MATERIAL', u'Material'), (u'IMAGE', u'Image'), (u'YESNO', u'Yes/No'),
    (u'FAMILYTYPE', u'Family Type'),
    (u'HVAC_AIR_FLOW', u'Air Flow'), (u'HVAC_DUCT_SIZE', u'Duct Size'),
    (u'HVAC_DENSITY', u'HVAC Density'), (u'HVAC_ENERGY', u'HVAC Energy'),
    (u'HVAC_FRICTION', u'HVAC Friction'), (u'HVAC_POWER', u'HVAC Power'),
    (u'HVAC_PRESSURE', u'HVAC Pressure'), (u'HVAC_TEMPERATURE', u'Temperature'),
    (u'HVAC_VELOCITY', u'HVAC Velocity'), (u'HVAC_CROSS_SECTION', u'Cross Section'),
    (u'HVAC_HEAT_GAIN', u'Heat Gain'), (u'HVAC_ROUGHNESS', u'HVAC Roughness'),
    (u'HVAC_FACTOR', u'HVAC Factor'), (u'HVAC_SLOPE', u'HVAC Slope'),
    (u'ELECTRICAL_CURRENT', u'Current'), (u'ELECTRICAL_POTENTIAL', u'Electrical Potential'),
    (u'ELECTRICAL_FREQUENCY', u'Frequency'), (u'ELECTRICAL_ILLUMINANCE', u'Illuminance'),
    (u'ELECTRICAL_LUMINOUS_FLUX', u'Luminous Flux'),
    (u'ELECTRICAL_LUMINOUS_INTENSITY', u'Luminous Intensity'),
    (u'ELECTRICAL_EFFICACY', u'Efficacy'), (u'ELECTRICAL_WATTAGE', u'Wattage'),
    (u'ELECTRICAL_POWER', u'Electrical Power'),
    (u'ELECTRICAL_APPARENT_POWER', u'Apparent Power'),
    (u'ELECTRICAL_TEMPERATURE', u'Electrical Temperature'),
    (u'CONDUIT_SIZE', u'Conduit Size'), (u'CABLETRAY_SIZE', u'Cable Tray Size'),
    (u'WIRE_SIZE', u'Wire Size'),
    (u'PIPING_FLOW', u'Piping Flow'), (u'PIPING_PRESSURE', u'Piping Pressure'),
    (u'PIPING_TEMPERATURE', u'Piping Temperature'), (u'PIPING_VELOCITY', u'Piping Velocity'),
    (u'PIPING_DENSITY', u'Piping Density'), (u'PIPING_VISCOSITY', u'Piping Viscosity'),
    (u'PIPING_FRICTION', u'Piping Friction'), (u'PIPING_ROUGHNESS', u'Piping Roughness'),
    (u'PIPING_SLOPE', u'Piping Slope'), (u'PIPING_VOLUME', u'Piping Volume'),
    (u'PIPE_SIZE', u'Pipe Size'),
    (u'FORCE', u'Force'), (u'MOMENT', u'Moment'), (u'LINEAR_FORCE', u'Linear Force'),
    (u'AREA_FORCE', u'Area Force'), (u'STRESS', u'Stress'), (u'MASS', u'Mass'),
    (u'BAR_DIAMETER', u'Bar Diameter'), (u'SPEED', u'Speed'), (u'TIME', u'Time'),
]
_LABELS = dict(SP_TYPES)
_TOKENS = dict((label, token) for token, label in SP_TYPES)


def type_label(token):
    return _LABELS.get(token, token)


def type_token(label):
    return _TOKENS.get(label, label)


def new_guid():
    return u'{0}'.format(uuid.uuid4())


class SpRow(object):
    def __init__(self, guid, name, dtype, dcat, group_id, visible, desc, user, hide,
                 item=None):
        self.guid = guid
        self.name = name
        self.dtype = dtype
        self.dcat = dcat
        self.group_id = group_id
        self.visible = visible
        self.desc = desc
        self.user = user
        self.hide = hide
        self.item = item           # the original line, None for a new row
        self.deleted = False
        self.tick = True
        self.orig = self.values()

    def values(self):
        return (self.guid, self.name, self.dtype, self.dcat, self.group_id, self.visible,
                self.desc, self.user, self.hide)

    def state(self):
        if self.deleted:
            return 'del'
        if self.item is None:
            return 'new'
        return 'mod' if self.values() != self.orig else 'ok'


class SpGroup(object):
    def __init__(self, gid, name, item=None):
        self.gid = gid
        self.name = name
        self.item = item
        self.orig = name


class Item(object):
    """One line. kind: raw, group, param, group_head, param_head."""

    def __init__(self, kind, text, fields=None):
        self.kind = kind
        self.text = text
        self.fields = fields


class SpFile(object):
    def __init__(self):
        self.items = []
        self.cols = []
        self.rows = []
        self.groups = []
        self.encoding = 'utf-16-le'
        self.bom = codecs.BOM_UTF16_LE
        self.newline = u'\r\n'
        self.final_newline = True
        self.path = u''

    def group_name(self, gid):
        for group in self.groups:
            if group.gid == gid:
                return group.name
        return gid

    def group_id(self, name):
        for group in self.groups:
            if group.name == name:
                return group.gid
        return None

    def add_group(self, name):
        highest = 0
        for group in self.groups:
            try:
                highest = max(highest, int(group.gid))
            except Exception:
                pass
        group = SpGroup(u'{0}'.format(highest + 1), name)
        self.groups.append(group)
        return group

    def live_rows(self):
        return [r for r in self.rows if not r.deleted]

    def is_dirty(self):
        if [r for r in self.rows if r.state() != 'ok']:
            return True
        return bool([g for g in self.groups if g.item is None or g.name != g.orig]
                    or len(self.groups) != len([i for i in self.items if i.kind == 'group']))


def decode(data):
    """(text, encoding, bom). Files come in UTF-16 from Revit and UTF-8 or ANSI by hand."""
    if data[:2] == codecs.BOM_UTF16_LE:
        return data[2:].decode('utf-16-le'), 'utf-16-le', codecs.BOM_UTF16_LE
    if data[:2] == codecs.BOM_UTF16_BE:
        return data[2:].decode('utf-16-be'), 'utf-16-be', codecs.BOM_UTF16_BE
    if data[:3] == codecs.BOM_UTF8:
        return data[3:].decode('utf-8'), 'utf-8', codecs.BOM_UTF8
    try:
        return data.decode('utf-8'), 'utf-8', b''
    except Exception:
        return data.decode('cp1252'), 'cp1252', b''


def encode(text, encoding, bom):
    return bom + text.encode(encoding)


def parse_text(text):
    sp = SpFile()
    sp.newline = u'\r\n' if u'\r\n' in text else u'\n'
    sp.final_newline = text.endswith(u'\n') or not text
    lines = re.split(u'\r\n|\n', text)
    if lines and lines[-1] == u'':
        lines.pop()
    for line in lines:
        fields = line.split(u'\t')
        head = fields[0]
        if head == u'*PARAM':
            sp.cols = fields[1:]
            sp.items.append(Item('param_head', line, fields))
        elif head == u'*GROUP':
            sp.items.append(Item('group_head', line, fields))
        elif head == u'GROUP' and len(fields) >= 3:
            item = Item('group', line, fields)
            sp.items.append(item)
            sp.groups.append(SpGroup(fields[1], fields[2], item))
        elif head == u'PARAM' and sp.cols and len(fields) >= 3:
            item = Item('param', line, fields)
            sp.items.append(item)
            sp.rows.append(_row_from(sp.cols, item))
        else:
            sp.items.append(Item('raw', line))
    return sp


def _row_from(cols, item):
    data = dict(zip(cols, item.fields[1:]))
    get = data.get
    return SpRow(get('GUID', u''), get('NAME', u''), get('DATATYPE', u''),
                 get('DATACATEGORY', u''), get('GROUP', u''), get('VISIBLE', YES),
                 get('DESCRIPTION', u''), get('USERMODIFIABLE', YES),
                 get('HIDEWHENNOVALUE', NO), item)


def parse_bytes(data):
    text, encoding, bom = decode(data)
    sp = parse_text(text)
    sp.encoding = encoding
    sp.bom = bom
    return sp


def blank():
    return parse_text(TEMPLATE)


def _clean(value):
    return re.sub(u'[\t\r\n]+', u' ', value if value is not None else u'')


def _row_line(cols, row):
    values = {'GUID': row.guid, 'NAME': row.name, 'DATATYPE': row.dtype,
              'DATACATEGORY': row.dcat, 'GROUP': row.group_id, 'VISIBLE': row.visible,
              'DESCRIPTION': row.desc, 'USERMODIFIABLE': row.user,
              'HIDEWHENNOVALUE': row.hide}
    old = row.item.fields[1:] if row.item is not None else []
    out = [u'PARAM']
    for index, col in enumerate(cols):
        if col in values:
            out.append(_clean(values[col]))
        else:
            out.append(old[index] if index < len(old) else u'')
    return u'\t'.join(out + old[len(cols):])


def _needed_cols(sp):
    """Older files lack the last two columns. They are added only if a row needs them."""
    cols = list(sp.cols)
    for col, default in (('USERMODIFIABLE', YES), ('HIDEWHENNOVALUE', NO)):
        if col in cols:
            continue
        attr = 'user' if col == 'USERMODIFIABLE' else 'hide'
        if [r for r in sp.live_rows() if getattr(r, attr) != default]:
            cols.append(col)
    return cols


def render(sp):
    """The whole file as it came in, with the edits applied."""
    cols = _needed_cols(sp)
    widened = cols != sp.cols
    live_groups = dict((id(g.item), g) for g in sp.groups if g.item is not None)
    by_item = dict((id(r.item), r) for r in sp.rows if r.item is not None)
    out = []
    last_group = last_param = None
    for item in sp.items:
        if item.kind == 'group_head':
            out.append(item.text)
            last_group = len(out)
        elif item.kind == 'group':
            group = live_groups.get(id(item))
            if group is None:
                continue
            if group.name == group.orig:
                out.append(item.text)
            else:
                fields = list(item.fields)
                fields[2] = _clean(group.name)
                out.append(u'\t'.join(fields))
            last_group = len(out)
        elif item.kind == 'param_head':
            out.append(u'\t'.join([u'*PARAM'] + cols) if widened else item.text)
            last_param = len(out)
        elif item.kind == 'param':
            row = by_item[id(item)]
            if not row.deleted:
                out.append(item.text if row.state() == 'ok' and not widened
                           else _row_line(cols, row))
            last_param = len(out)
        else:
            out.append(item.text)
    new_rows = [_row_line(cols, r) for r in sp.rows if r.item is None and not r.deleted]
    if last_param is None:
        out.append(u'\t'.join([u'*PARAM'] + TEMPLATE_COLS))
        last_param = len(out)
    out[last_param:last_param] = new_rows
    new_groups = [u'\t'.join([u'GROUP', g.gid, _clean(g.name)])
                  for g in sp.groups if g.item is None]
    if new_groups:
        if last_group is None:
            first = [i for i, line in enumerate(out) if line.startswith(u'*PARAM')][0]
            out[first:first] = [u'*GROUP\tID\tNAME'] + new_groups
        else:
            out[last_group:last_group] = new_groups
    return sp.newline.join(out) + (sp.newline if sp.final_newline else u'')


TEMPLATE_COLS = [u'GUID', u'NAME', u'DATATYPE', u'DATACATEGORY', u'GROUP', u'VISIBLE',
                 u'DESCRIPTION', u'USERMODIFIABLE', u'HIDEWHENNOVALUE']


def to_bytes(sp):
    return encode(render(sp), sp.encoding, sp.bom)


def validate(sp, name_problem):
    """(errors that stop the save, warnings to confirm)."""
    errors = []
    warnings = []
    rows = sp.live_rows()
    guids = {}
    names = {}
    ids = set(g.gid for g in sp.groups)
    for row in rows:
        guids[row.guid.lower()] = guids.get(row.guid.lower(), 0) + 1
        names[row.name.strip().lower()] = names.get(row.name.strip().lower(), 0) + 1
    for row in rows:
        if row.state() == 'ok':
            continue
        label = row.name or u'(no name)'
        bad = name_problem(row.name)
        if bad:
            errors.append(u'{0}: {1}'.format(label, bad))
        if guids[row.guid.lower()] > 1:
            errors.append(u'{0}: another parameter has the same GUID'.format(label))
        if not re.match(u'^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$', row.guid):
            errors.append(u'{0}: the GUID is not valid'.format(label))
        if row.group_id not in ids:
            errors.append(u'{0}: its group is missing'.format(label))
        if row.dtype == u'FAMILYTYPE' and not row.dcat:
            errors.append(u'{0}: a Family Type needs its category from Revit, '
                          u'create it in Revit\'s own editor'.format(label))
        if names[row.name.strip().lower()] > 1:
            warnings.append(u'{0}: the name is used more than once'.format(label))
    moved = [r for r in rows if r.item is not None and r.guid != r.orig[0]]
    if moved:
        warnings.append(u'{0} parameter(s) have a new GUID. Families and projects already '
                        u'using the old GUID will not match them.'.format(len(moved)))
    gone = [r for r in sp.rows if r.deleted and r.item is not None]
    if gone:
        warnings.append(u'{0} parameter(s) will be removed from the file.'.format(len(gone)))
    return errors, warnings


def group_use(sp, gid):
    return len([r for r in sp.live_rows() if r.group_id == gid])


def duplicate_name(sp, name):
    taken = set(r.name.lower() for r in sp.live_rows())
    candidate = name + u' Copy'
    number = 2
    while candidate.lower() in taken:
        candidate = u'{0} Copy {1}'.format(name, number)
        number += 1
    return candidate


def duplicate(sp, row):
    copy = SpRow(new_guid(), duplicate_name(sp, row.name), row.dtype, row.dcat, row.group_id,
                 row.visible, row.desc, row.user, row.hide)
    copy.tick = False
    sp.rows.append(copy)
    return copy


def add_row(sp, name, group_id):
    row = SpRow(new_guid(), name, u'TEXT', u'', group_id, YES, u'', YES, NO)
    row.tick = False
    sp.rows.append(row)
    return row
