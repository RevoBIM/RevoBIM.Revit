# -*- coding: utf-8 -*-
"""Extra columns on revisions, kept in the model, and pushed to parameters.

Revit will not take parameters on the Revisions category, so a revision cannot
carry "Revision notes" of its own the way a sheet can. The Revision Manager's
own columns are stored in the model instead, through Extensible Storage, on
one DataStorage element:

- ``columns`` - the column definitions: name, type, choices, and where the
  column is pushed to
- ``values`` - every revision's value in every column, keyed by the
  revision's UniqueId so it survives worksharing and copy-monitoring

One element, not an entity on each revision: Revit locks an issued revision,
and notes are exactly what gets written after an issue.

**Pushing.** The data can go on into real parameters, which is what lets a
title block or a tag show it:

| Push to | Each element takes the value of |
| --- | --- |
| Sheets | the sheet's current revision |
| Revision clouds | the cloud's own revision |

The parameter is a project or shared parameter the office has already added
to that category - Text for text, choice and date columns, Yes/No for yes/no,
Number (or Integer, or Text) for numbers. It is pushed on every Apply, and on
demand, so a sheet whose current revision changes picks up the new value.

Everything above the Revit section is plain Python, bench-tested.
"""

import ps_refs  # noqa: F401  - must be first

import re

from System import Guid, String

from Autodesk.Revit.DB import (BuiltInCategory, FilteredElementCollector,
                               RevisionCloud, Transaction, ViewSheet)

# SpecTypeId, and Definition.GetDataType with it, arrived in Revit 2021.
# On its own and guarded, for the same reason as
# ps_revisions.RevisionNumberingSequence: one missing name in a grouped
# import takes the whole tool down. Without it no parameter's type of data
# can be read, so nothing is offered for mapping.
try:
    from Autodesk.Revit.DB import SpecTypeId
except Exception:
    SpecTypeId = None
from Autodesk.Revit.DB.ExtensibleStorage import (AccessLevel, DataStorage,
                                                 Entity, Schema,
                                                 SchemaBuilder)

import ps_model


SCHEMA_GUID = '6f2c1d84-3a57-4b9e-9c41-52e0a7d3b1f6'
SCHEMA_NAME = 'RevoBIMRevisionData'
# Values are stored as v1; columns from 1.44.0 as v2, which adds the group a
# column belongs to. A v1 column list is read and the Issue Status, Issued
# To and Method columns added to it, once.
FORMAT = u'v1'
COLUMNS_FORMAT = u'v2'

# kind, as the type list words it
KINDS = [('text', u'Text'), ('yesno', u'Yes/No'), ('number', u'Number'),
         ('date', u'Date'), ('choice', u'Choice list')]
KIND_LABELS = dict(KINDS)

# where a column can be pushed, as the mapping list words it
TARGETS = [('', u'Nowhere - kept in the model only'),
           ('sheets', u'Sheets - their current revision\'s value'),
           ('clouds', u'Revision clouds - their own revision\'s value')]
TARGET_LABELS = dict(TARGETS)

# The parameter data each kind can be written into. 'YesNo' is a Yes/No
# parameter - an Integer underneath, but a number written into one is
# nonsense, so it is told apart from a whole-number parameter.
ACCEPTS = {
    'text': ('String',),
    'date': ('String',),
    'choice': ('String',),
    'yesno': ('YesNo', 'Integer', 'String'),
    'number': ('Double', 'Integer', 'String'),
}

DATA_WORDS = {'String': u'Text', 'YesNo': u'Yes/No',
              'Integer': u'Integer', 'Double': u'Number'}

# What a mapping does, for the tooltips that explain it.
MAPPING_HELP = (
    u'Revit takes no parameters on revisions, so these columns are kept in '
    u'the model by this tool. Map one to a parameter to put its values '
    u'where Revit can show them:\n\n'
    u'SHEETS - each sheet takes the value of its current revision. Use it '
    u'for a label in the title block (the parameter must be a shared '
    u'parameter for a label to see it), or in a sheet list schedule.\n\n'
    u'REVISION CLOUDS - each cloud takes the value of its own revision. Use '
    u'it in a revision cloud tag, or to filter and schedule clouds.\n\n'
    u'Only instance parameters bound to that category are offered - a type '
    u'parameter would give every sheet the same value. Text, date and '
    u'choice columns need a Text parameter; Yes/No columns a Yes/No '
    u'parameter; Number columns a Number or Integer parameter.\n\n'
    u'Values are written on every Apply, so a sheet whose current revision '
    u'changes picks up the new value. To add a parameter: Open Project '
    u'Parameters, add it as an instance parameter to Sheets or Revision '
    u'Clouds, then come back here and pick it.')

DEFAULT_NOTES = u'Revision notes'

# Columns that belong to a group, treated apart from the rest: the
# Document Register's Excel plots the Issued To and Method groups as its
# "Issued to:" rows - an x where a revision is ticked - and the Issue Status
# column as each issue's status. Both groups are Yes/No, always.
ISSUED_TO = 'issued_to'
METHOD = 'method'
STATUS = 'status'
GROUPS = [(ISSUED_TO, u'Issued To'), (METHOD, u'Issued Method')]
GROUP_LABELS = dict(GROUPS + [(STATUS, u'Issue Status'), ('', u'')])
STATUS_ID = u'status'
STATUS_NAME = u'Issue Status'


class Column(object):
    """One extra column."""

    def __init__(self, column_id, name, kind='text', choices=None, target=u'',
                 parameter=u'', group=u''):
        self.id = u'{0}'.format(column_id)
        self.name = u'{0}'.format(name or u'').strip()
        self.kind = kind if kind in KIND_LABELS else 'text'
        self.choices = [u'{0}'.format(one).strip() for one in (choices or [])
                        if u'{0}'.format(one).strip()]
        self.target = target if target in TARGET_LABELS else u''
        self.parameter = u'{0}'.format(parameter or u'').strip()
        self.group = group if group in GROUP_LABELS else u''
        if self.group in (ISSUED_TO, METHOD):
            # Ticked or not, per revision: where the issue went, and how.
            self.kind = 'yesno'
        elif self.group == STATUS:
            self.kind = 'text'

    @property
    def pushed(self):
        return bool(self.target and self.parameter)

    def copy(self):
        return Column(self.id, self.name, self.kind, list(self.choices),
                      self.target, self.parameter, self.group)

    def same(self, other):
        return (self.id, self.name, self.kind, self.choices, self.target,
                self.parameter, self.group) == (
                    other.id, other.name, other.kind, other.choices,
                    other.target, other.parameter, other.group)


def grouped_defaults():
    """The Issue Status column and the Issued To / Method groups a model
    starts with - rename, add to or remove them in the manager."""
    return ([Column(STATUS_ID, STATUS_NAME, 'text', group=STATUS)] +
            [Column(u'it{0}'.format(number),
                    u'Issued To {0}'.format(number), 'yesno',
                    group=ISSUED_TO) for number in (1, 2, 3)] +
            [Column(u'm{0}'.format(number),
                    u'Issued Method {0}'.format(number), 'yesno',
                    group=METHOD) for number in (1, 2)])


def default_columns():
    """What a model with nothing stored starts with."""
    return [Column(u'notes', DEFAULT_NOTES, 'text')] + grouped_defaults()


def with_groups(columns):
    """A column list from before 1.44.0, with the grouped defaults added
    where nothing of theirs is there - a name already taken is skipped."""
    out = list(columns)
    ids = set([column.id for column in out])
    names = set([column.name.lower() for column in out])
    for column in grouped_defaults():
        if column.id in ids or column.name.lower() in names:
            continue
        out.append(column)
    return out


def group_order(columns):
    """The columns as the manager lays them out: the plain ones, then
    Issue Status, then each group with its members side by side."""
    ranks = {u'': 0, STATUS: 1, ISSUED_TO: 2, METHOD: 3}
    indexed = list(enumerate(columns))
    indexed.sort(key=lambda pair: (ranks.get(pair[1].group, 0), pair[0]))
    return [column for _index, column in indexed]


def status_column(columns):
    for column in columns:
        if column.group == STATUS:
            return column
    return None


def issue_rows(columns, values, revisions):
    """The Excel register's "Issued to:" block.

    ``values`` is {revision key: {column id: stored value}} and
    ``revisions`` the revision keys of the worksheet's issue columns, in
    order. Returns [(name, group, [ticked per revision])] - the Issued To
    group first, then Method - leaving out any column no revision on the
    worksheet has ticked."""
    rows = []
    for group, _label in GROUPS:
        for column in [one for one in columns if one.group == group]:
            ticks = [(values.get(key) or {}).get(column.id) == u'1'
                     for key in revisions]
            if True in ticks:
                rows.append((column.name, group, ticks))
    return rows


def issue_block(columns):
    """The columns the Document Register shows as rows under its
    revision headings (1.51.0): Issue Status first, then the Issued To
    group, then Issued Method - the Excel's block, every column whether
    ticked anywhere or not, so it can be ticked from the register."""
    block = []
    status = status_column(columns)
    if status is not None:
        block.append(status)
    for group, _label in GROUPS:
        block.extend([column for column in columns if column.group == group])
    return block


def block_edges(block):
    """What divides each row of the block from the next, in order:
    'frame' under Issue Status and between the groups (the Excel's medium
    lines), 'line' between rows of one group, None under the last."""
    edges = []
    for index, column in enumerate(block):
        following = block[index + 1] if index + 1 < len(block) else None
        if following is None:
            edges.append(None)
        elif column.group == STATUS or following.group != column.group:
            edges.append('frame')
        else:
            edges.append('line')
    return edges


def stored_value(column, value):
    """A stored value as the register compares it: a Yes/No left empty
    is a No."""
    text = u'{0}'.format(value if value is not None else u'').strip()
    if column.kind == 'yesno':
        return u'1' if text == u'1' else u'0'
    return text


def apply_changes(columns, values, changes):
    """``values`` ({revision uid: {column id: value}}) with ``changes``
    played over it: [(uid, column id, value)] in order. Returns (values,
    done, problems) - a column no longer in the model, or a value it
    refuses, is a problem and changes nothing."""
    by_id = dict([(column.id, column) for column in columns])
    out = dict([(uid, dict(row)) for uid, row in (values or {}).items()])
    done, problems = 0, []
    for uid, column_id, value in changes:
        column = by_id.get(column_id)
        if column is None:
            problems.append(u'The column {0} is no longer in the model.'
                            .format(column_id))
            continue
        if not uid:
            problems.append(u'{0}: the revision is no longer in the model.'
                            .format(column.name))
            continue
        ok, stored = normalise(column, value)
        if not ok:
            problems.append(stored)
            continue
        out.setdefault(uid, {})[column.id] = stored
        done += 1
    return out, done, problems


# ==========================================================================
# pure decisions - bench-tested
# ==========================================================================

def escape(text):
    return (u'{0}'.format(text if text is not None else u'')
            .replace(u'\\', u'\\\\').replace(u'\t', u'\\t')
            .replace(u'\n', u'\\n').replace(u'\r', u''))


def unescape(text):
    out = []
    index = 0
    text = u'{0}'.format(text or u'')
    while index < len(text):
        char = text[index]
        if char == u'\\' and index + 1 < len(text):
            following = text[index + 1]
            out.append({u't': u'\t', u'n': u'\n'}.get(following, following))
            index += 2
            continue
        out.append(char)
        index += 1
    return u''.join(out)


def _split(line):
    """A line split on tabs that are not escaped."""
    parts = []
    current = []
    index = 0
    while index < len(line):
        char = line[index]
        if char == u'\\' and index + 1 < len(line):
            current.append(line[index:index + 2])
            index += 2
            continue
        if char == u'\t':
            parts.append(u''.join(current))
            current = []
        else:
            current.append(char)
        index += 1
    parts.append(u''.join(current))
    return [unescape(part) for part in parts]


def encode_columns(columns):
    lines = [COLUMNS_FORMAT]
    for column in columns:
        lines.append(u'\t'.join([escape(column.id), escape(column.name),
                                 escape(column.kind),
                                 escape(u'|'.join(column.choices)),
                                 escape(column.target),
                                 escape(column.parameter),
                                 escape(column.group)]))
    return u'\n'.join(lines)


def decode_columns(text):
    """The stored columns, or None when nothing usable is stored. A list
    stored before 1.44.0 (v1) gains the grouped defaults."""
    lines = u'{0}'.format(text or u'').split(u'\n')
    version = lines[0].strip() if lines else u''
    if version not in (FORMAT, COLUMNS_FORMAT):
        return None
    columns = []
    seen = set()
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = _split(line) + [u''] * 7
        column = Column(parts[0], parts[1], parts[2],
                        parts[3].split(u'|') if parts[3] else [],
                        parts[4], parts[5], parts[6])
        if column.id and column.name and column.id not in seen:
            seen.add(column.id)
            columns.append(column)
    if version == FORMAT:
        columns = with_groups(columns)
    return columns


def encode_values(values):
    """{revision uid: {column id: value}} as text; empty values left out."""
    lines = [FORMAT]
    for uid in sorted(values):
        for column_id in sorted(values[uid]):
            value = values[uid][column_id]
            if value in (None, u''):
                continue
            lines.append(u'\t'.join([escape(uid), escape(column_id),
                                     escape(value)]))
    return u'\n'.join(lines)


def decode_values(text):
    lines = u'{0}'.format(text or u'').split(u'\n')
    values = {}
    if not lines or lines[0].strip() != FORMAT:
        return values
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = _split(line)
        if len(parts) < 3 or not parts[0] or not parts[1]:
            continue
        values.setdefault(parts[0], {})[parts[1]] = parts[2]
    return values


_NUMBER = re.compile(r'^\s*[-+]?(\d+(\.\d*)?|\.\d+)\s*$')


def normalise(column, value):
    """(ok, value as stored, or why not) for a value typed into a column."""
    if column.kind == 'yesno':
        if isinstance(value, bool):
            return True, u'1' if value else u'0'
        text = u'{0}'.format(value or u'').strip().lower()
        return True, u'1' if text in (u'1', u'true', u'yes', u'y') else u'0'
    text = u'{0}'.format(value if value is not None else u'').strip()
    if column.kind == 'number':
        if text and not _NUMBER.match(text):
            return False, u'{0} takes a number.'.format(column.name)
        return True, text
    if column.kind == 'choice' and text and column.choices and \
            text not in column.choices:
        return False, u'{0} takes one of: {1}.'.format(
            column.name, u', '.join(column.choices))
    return True, text


def shown(column, value):
    """A stored value as the grid and the searches read it."""
    if column.kind == 'yesno':
        return u'Yes' if value == u'1' else u'No'
    return u'{0}'.format(value or u'')


def column_problem(name, kind, choices, columns, column_id=None):
    """Why a column cannot be added or renamed like that, or u''."""
    name = u'{0}'.format(name or u'').strip()
    if not name:
        return u'A column needs a name.'
    for column in columns:
        if column.id != column_id and column.name.lower() == name.lower():
            return u'There is already a column called "{0}".'.format(
                column.name)
    if kind not in KIND_LABELS:
        return u'Choose a type for the column.'
    if kind == 'choice' and not [one for one in choices or []
                                 if u'{0}'.format(one).strip()]:
        return u'A choice list needs at least one choice.'
    return u''


def new_column_id(columns):
    taken = set([column.id for column in columns])
    number = 1
    while u'c{0}'.format(number) in taken:
        number += 1
    return u'c{0}'.format(number)


def parameter_value(column, storage, value):
    """(ok, value) to write a column's value into a parameter of ``storage``
    ('String', 'Integer' or 'Double'), or (False, why)."""
    value = u'{0}'.format(value if value is not None else u'')
    if storage not in ACCEPTS.get(column.kind, ()):
        return False, u'a {0} parameter cannot hold a {1} column'.format(
            storage, KIND_LABELS.get(column.kind, column.kind))
    if storage == 'YesNo':
        storage = 'Integer'
    if storage == 'String':
        return True, shown(column, value)
    if column.kind == 'yesno':
        return True, 1 if value == u'1' else 0
    if not value.strip():
        return False, u'empty'
    try:
        number = float(value)
    except Exception:
        return False, u'"{0}" is not a number'.format(value)
    if storage == 'Integer':
        return True, int(round(number))
    return True, number


def usable(parameters, target, kind=None):
    """[(name, data)] a column of ``kind`` can be pushed into on ``target``.

    ``parameters`` is what bound_parameters reads: dicts of name,
    categories ('sheets' / 'clouds'), instance and data. Only instance
    parameters bound to the target's category, holding data the column's
    kind can be written as.
    """
    accepted = ACCEPTS.get(kind) if kind else \
        ('String', 'YesNo', 'Integer', 'Double')
    found = {}
    for parameter in parameters or ():
        if not parameter.get('instance'):
            continue
        if target not in parameter.get('categories', ()):
            continue
        if parameter.get('data') not in accepted:
            continue
        found[parameter['name']] = parameter['data']
    return sorted(found.items(), key=lambda item: item[0].lower())


def matching(names, keyword):
    """The names holding every word of ``keyword``, anywhere, any case.
    An empty keyword keeps them all."""
    words = u'{0}'.format(keyword or u'').lower().split()
    if not words:
        return list(names)
    return [name for name in names
            if all([word in u'{0}'.format(name).lower() for word in words])]


def why_not(parameters, target, kind, name):
    """Why ``name`` is not offered for this column and target, or u''."""
    if not name:
        return u''
    where = u'Sheets' if target == 'sheets' else u'Revision Clouds'
    matching = [one for one in parameters or () if one.get('name') == name]
    if not matching:
        return (u'"{0}" is not in the project. Add it in Project Parameters '
                u'as an instance parameter on {1}.'.format(name, where))
    if not [one for one in matching if target in one.get('categories', ())]:
        return u'"{0}" is not bound to {1}.'.format(name, where)
    if not [one for one in matching if one.get('instance')]:
        return (u'"{0}" is a type parameter - every {1} would show the same '
                u'value. Make it an instance parameter.'.format(
                    name, u'sheet' if target == 'sheets' else u'cloud'))
    datas = [one.get('data') for one in matching]
    if not [data for data in datas if data in ACCEPTS.get(kind, ())]:
        return (u'"{0}" holds {1}; a {2} column needs {3}.'.format(
            name, DATA_WORDS.get(datas[0], u'another type of data'),
            KIND_LABELS.get(kind, kind), u' or '.join(
                [DATA_WORDS[one] for one in ACCEPTS.get(kind, ())])))
    return u''


def sheet_values(sheets, values, column):
    """{sheet key: value} - each sheet takes its current revision's value.

    ``sheets`` is [(sheet key, current revision key or None)]. A sheet with
    no current revision, or whose revision has no value, gets the empty
    value: a stale note from a superseded revision is worse than none.
    """
    out = {}
    for sheet_key, revision_key in sheets:
        out[sheet_key] = (values.get(revision_key) or {}).get(column.id, u'') \
            if revision_key is not None else u''
    return out


# ==========================================================================
# Revit
# ==========================================================================

def _schema():
    found = Schema.Lookup(Guid(SCHEMA_GUID))
    if found is not None:
        return found
    builder = SchemaBuilder(Guid(SCHEMA_GUID))
    builder.SetReadAccessLevel(AccessLevel.Public)
    builder.SetWriteAccessLevel(AccessLevel.Public)
    builder.SetSchemaName(SCHEMA_NAME)
    builder.SetDocumentation(u'RevoBIM Revision Manager: extra columns on '
                             u'revisions, and their values')
    builder.AddSimpleField('columns', String)
    builder.AddSimpleField('values', String)
    return builder.Finish()


def _store(doc, schema):
    """The DataStorage element holding the data, or None."""
    try:
        for element in FilteredElementCollector(doc).OfClass(DataStorage):
            try:
                if element.GetEntity(schema).IsValid():
                    return element
            except Exception:
                continue
    except Exception:
        pass
    return None


def read(doc):
    """(columns, {revision uid: {column id: value}}). Never raises."""
    try:
        schema = Schema.Lookup(Guid(SCHEMA_GUID))
    except Exception:
        schema = None
    if schema is None:
        return default_columns(), {}
    element = _store(doc, schema)
    if element is None:
        return default_columns(), {}
    try:
        entity = element.GetEntity(schema)
        columns = decode_columns(entity.Get[String]('columns'))
        values = decode_values(entity.Get[String]('values'))
    except Exception:
        return default_columns(), {}
    return (columns if columns is not None else default_columns()), values


def write(doc, columns, values):
    """Store it. Inside a transaction the caller has open."""
    schema = _schema()
    element = _store(doc, schema) or DataStorage.Create(doc)
    entity = Entity(schema)
    entity.Set[String]('columns', encode_columns(columns))
    entity.Set[String]('values', encode_values(values))
    element.SetEntity(entity)


def _storage_name(parameter):
    try:
        return u'{0}'.format(parameter.StorageType)
    except Exception:
        return u''


def _data_of(definition):
    """'String', 'YesNo', 'Integer', 'Double' or u'' for a definition."""
    if SpecTypeId is None:
        return u''
    try:
        spec = definition.GetDataType()
    except Exception:
        return u''
    for name, kind in ((u'String', 'String'), (u'YesNo', 'YesNo'),
                       (u'Integer', 'Integer'), (u'Number', 'Double')):
        try:
            wanted = {u'String': lambda: SpecTypeId.String.Text,
                      u'YesNo': lambda: SpecTypeId.Boolean.YesNo,
                      u'Integer': lambda: SpecTypeId.Int.Integer,
                      u'Number': lambda: SpecTypeId.Number}[name]()
            if spec == wanted or u'{0}'.format(spec.TypeId) == \
                    u'{0}'.format(wanted.TypeId):
                return kind
        except Exception:
            continue
    return u''


def bound_parameters(doc):
    """Every project and shared parameter bound to Sheets or Revision
    Clouds: [{'name', 'categories', 'instance', 'data'}]. Never raises."""
    targets = {}
    try:
        targets[int(BuiltInCategory.OST_Sheets)] = 'sheets'
        targets[int(BuiltInCategory.OST_RevisionClouds)] = 'clouds'
    except Exception:
        return []
    found = []
    try:
        iterator = doc.ParameterBindings.ForwardIterator()
        iterator.Reset()
    except Exception:
        return found
    while True:
        try:
            if not iterator.MoveNext():
                break
            definition = iterator.Key
            binding = iterator.Current
        except Exception:
            break
        categories = set()
        try:
            for category in binding.Categories:
                key = targets.get(ps_model.eid_value(category.Id))
                if key:
                    categories.add(key)
        except Exception:
            pass
        if not categories:
            continue
        try:
            instance = binding.GetType().Name == 'InstanceBinding'
        except Exception:
            instance = False
        found.append({'name': ps_model.to_text(definition.Name),
                      'categories': categories, 'instance': instance,
                      'data': _data_of(definition)})
    return found


def parameter_names(doc, target, kind=None):
    """[(name, data)] the column dialog offers for a target."""
    return usable(bound_parameters(doc), target, kind)


def _set(element, column, value):
    """(written, problem) for one element."""
    parameter = element.LookupParameter(column.parameter)
    if parameter is None:
        return False, u'missing'
    if parameter.IsReadOnly:
        return False, u'read-only'
    ok, converted = parameter_value(column, _storage_name(parameter), value)
    if not ok:
        return False, converted
    parameter.Set(converted)
    return True, u''


def write_changes(doc, changes, keys_by_uid):
    """The Document Register's staged issue data, written (1.51.0).

    ``changes`` is [(revision uid, column id, value)] in the order staged;
    ``keys_by_uid`` every revision's element key by uid, for the push.
    Reads what is stored now, plays the changes over it, stores it and
    pushes the mapped columns - one transaction. (done, problems)."""
    transaction = Transaction(doc, u'RevoBIM - Document Register issue data')
    try:
        transaction.Start()
    except Exception as err:
        return 0, [u'The transaction would not start: {0}'.format(err)]
    try:
        columns, values = read(doc)
        values, done, problems = apply_changes(columns, values, changes)
        write(doc, columns, values)
        by_key = dict([(key, values.get(uid) or {})
                       for uid, key in keys_by_uid.items()])
        _count, pushed = push(doc, columns, by_key)
        problems.extend(pushed)
    except Exception as err:
        try:
            transaction.RollBack()
        except Exception:
            pass
        return 0, [u'Nothing was changed: {0}'.format(err)]
    try:
        transaction.Commit()
    except Exception as err:
        return 0, [u'Revit would not keep the changes: {0}'.format(err)]
    return done, problems


def push(doc, columns, values_by_key):
    """Write every pushed column into its parameters. (count, problems).

    ``values_by_key`` is keyed by revision element key. Inside a
    transaction the caller has open.
    """
    count = 0
    problems = []
    pushed = [column for column in columns if column.pushed]
    if not pushed:
        return count, problems
    sheets = []
    clouds = []
    if [column for column in pushed if column.target == 'sheets']:
        for sheet in FilteredElementCollector(doc).OfClass(ViewSheet):
            try:
                current = sheet.GetCurrentRevision()
                key = ps_model.eid_value(current) if current is not None \
                    and ps_model.eid_value(current) > 0 else None
            except Exception:
                key = None
            sheets.append((sheet, key))
    if [column for column in pushed if column.target == 'clouds']:
        for cloud in FilteredElementCollector(doc).OfClass(RevisionCloud):
            try:
                clouds.append((cloud, ps_model.eid_value(cloud.RevisionId)))
            except Exception:
                continue
    for column in pushed:
        targets = sheets if column.target == 'sheets' else clouds
        tally = {}
        for element, revision_key in targets:
            value = (values_by_key.get(revision_key) or {}).get(column.id, u'') \
                if revision_key is not None else u''
            try:
                written, problem = _set(element, column, value)
            except Exception as err:
                written, problem = False, u'{0}'.format(err)
            if written:
                count += 1
            elif problem != u'empty':
                tally[problem] = tally.get(problem, 0) + 1
        noun = u'sheet' if column.target == 'sheets' else u'cloud'
        for problem, times in sorted(tally.items()):
            problems.append(u'{0} -> "{1}": {2} {3}{4} not written - {5}'
                            .format(column.name, column.parameter, times,
                                    noun, u'' if times == 1 else u's',
                                    problem))
    return count, problems
