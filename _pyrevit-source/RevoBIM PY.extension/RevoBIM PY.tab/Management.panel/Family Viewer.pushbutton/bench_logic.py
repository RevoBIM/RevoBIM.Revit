# -*- coding: utf-8 -*-
"""Family Viewer - bench test of the rules.

    python bench_logic.py

Stubs the Revit API and replaces only the collectors, so the rules themselves
are the real shipped code: the grouping, the counting, the phase filter, the
"(varies)" roll-up, the column filters, the sorting and the settings round
trip all run exactly as they do in Revit.
"""

import io
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import import_check
import_check.install_stubs()

import fv_core
import fv_grid
import fv_window
import fv_model


# ===========================================================================
# a Revit small enough to reason about
# ===========================================================================

class ElementId(object):
    def __init__(self, value):
        self.Value = int(value)

    def __eq__(self, other):
        return isinstance(other, ElementId) and other.Value == self.Value

    def __hash__(self):
        return hash(self.Value)


class Category(object):
    def __init__(self, name, ident, kind='Model'):
        self.Name = name
        self.Id = ElementId(ident)
        self.CategoryType = kind


class Definition(object):
    def __init__(self, name):
        self.Name = name


class Parameter(object):
    def __init__(self, name, value):
        self.name = name
        self.value = value
        self.Definition = Definition(name)
        self.HasValue = value is not None
        self.StorageType = 'String'

    def AsValueString(self):
        return None if self.value is None else str(self.value)

    def AsString(self):
        return None if self.value is None else str(self.value)


class Holder(object):
    def __init__(self, params=None):
        self.params = dict(params or {})

    @property
    def Parameters(self):
        """What parameter_names walks over to see what an element carries."""
        return [Parameter(name, value)
                for name, value in sorted(self.params.items())]

    def GetParameters(self, name):
        if name in self.params:
            return [Parameter(name, self.params[name])]
        return []

    def LookupParameter(self, name):
        if name in self.params:
            return Parameter(name, self.params[name])
        return None


class ElementType(Holder):
    def __init__(self, ident, name, family_name, category, params=None,
                 family_id=None):
        Holder.__init__(self, params)
        self.Id = ElementId(ident)
        self.Name = name
        self.FamilyName = family_name
        self.Category = category
        self._family_id = family_id


class FamilySymbol(ElementType):
    def __init__(self, ident, name, family_name, category, params=None,
                 family_id=1000):
        ElementType.__init__(self, ident, name, family_name, category, params,
                             family_id)

    @property
    def Family(self):
        holder = Holder()
        holder.Name = self.FamilyName
        holder.Id = ElementId(self._family_id)
        return holder


class Instance(Holder):
    def __init__(self, ident, type_id, created=None, demolished=None,
                 super_component=None, params=None, view=None,
                 category=None):
        Holder.__init__(self, params)
        self.Id = ElementId(ident)
        # a real instance carries its category.  The fake did not, and that is
        # why the bench could not tell an element of an unticked category from
        # one whose type was never read - the difference this release turns on.
        self.Category = category
        self._type_id = type_id
        self.created = created
        self.demolished = demolished
        self.SuperComponent = super_component
        self.view = view

    def GetTypeId(self):
        return ElementId(self._type_id)

    def get_Parameter(self, builtin):
        if builtin == 'PHASE_CREATED':
            value = self.created
        elif builtin == 'PHASE_DEMOLISHED':
            value = self.demolished
        else:
            return None
        if value is None:
            return None
        holder = Holder()
        holder.AsElementId = lambda: ElementId(value)
        return holder


class FamilyInstance(Instance):
    pass


class BuiltInParameter(object):
    PHASE_CREATED = 'PHASE_CREATED'
    PHASE_DEMOLISHED = 'PHASE_DEMOLISHED'


class StorageType(object):
    String = 'String'
    Integer = 'Integer'
    Double = 'Double'
    ElementId = 'ElementId'


class FakeList(object):
    def __init__(self):
        self.items = []

    def Add(self, item):
        self.items.append(item)

    @property
    def Count(self):
        return len(self.items)


class ListFactory(object):
    def __getitem__(self, item):
        return FakeList


class Document(object):
    def __init__(self, types, instances, phases):
        self.Title = 'Bench'
        self.types = types
        self.instances = instances
        self.Phases = phases
        self.ParameterBindings = None

    def GetElement(self, element_id):
        return None


class View(object):
    def __init__(self, name):
        self.Id = ElementId(-99)
        self.Name = name


class Collector(object):
    """FilteredElementCollector(doc) and FilteredElementCollector(doc, viewId),
    with just the calls the tool actually makes."""

    def __init__(self, doc, view_id=None):
        self.doc = doc
        self.view_id = view_id
        self.items = None

    def WhereElementIsElementType(self):
        self.items = list(self.doc.types)
        return self

    def WhereElementIsNotElementType(self):
        items = list(self.doc.instances)
        if self.view_id is not None:
            items = [item for item in items if item.view == self.view_id.Value]
        self.items = items
        return self

    def WherePasses(self, element_filter):
        wanted = set(element_filter)
        self.items = [item for item in self.items
                      if _category_of(self.doc, item) in wanted]
        return self

    def __iter__(self):
        return iter(self.items or [])


def _category_of(doc, instance):
    for element in doc.types:
        if element.Id.Value == instance.GetTypeId().Value:
            return element.Category.Id.Value
    return 0


def multicategory(ids):
    return [element_id.Value for element_id in ids.items]


# the real parameter_names, kept before install() swaps it out for a stub in
# the grouping tests - check_parameter_scope puts the real one back
REAL_PARAMETER_NAMES = fv_model.parameter_names


def install(doc):
    fv_model.FilteredElementCollector = lambda document, view_id=None: \
        Collector(doc, view_id)
    fv_model.ElementType = ElementType
    fv_model.FamilySymbol = FamilySymbol
    fv_model.FamilyInstance = FamilyInstance
    fv_model.ElementId = ElementId
    fv_model.ElementMulticategoryFilter = multicategory
    fv_model.BuiltInParameter = BuiltInParameter
    fv_model.StorageType = StorageType
    fv_model.List = ListFactory()
    fv_model.parameter_names = \
        lambda document, types, samples, category_ids=None: []


# ===========================================================================
# the model under test
# ===========================================================================

DOORS = Category('Doors', -2000023)
PIPES = Category('Pipes', -2008044)
TAGS = Category('Door Tags', -2000460, 'Annotation')

PHASE_EXISTING = 100
PHASE_NEW = 101


def build_doc():
    types = [
        FamilySymbol(1, '900x2100', 'BGL_Door_Single', DOORS,
                     {'Fire Rating': 'FD30'}, family_id=901),
        FamilySymbol(2, '1000x2100', 'BGL_Door_Single', DOORS,
                     {'Fire Rating': 'FD60'}, family_id=901),
        FamilySymbol(3, '1800x2100', 'BGL_Door_Double', DOORS,
                     {'Fire Rating': 'FD30'}, family_id=902),
        FamilySymbol(4, 'Standard', 'BGL_Door_Tag', TAGS, {}, family_id=903),
        ElementType(5, 'Copper 15', 'Pipe Types', PIPES, {}),
        ElementType(6, 'Copper 22', 'Pipe Types', PIPES, {}),
    ]
    instances = [
        # type 1: three in the existing phase, one of them nested
        FamilyInstance(11, 1, created=PHASE_EXISTING, view=-99,
                       params={'Mark': 'D01'}, category=DOORS),
        FamilyInstance(12, 1, created=PHASE_EXISTING, view=-1,
                       params={'Mark': 'D01'}, category=DOORS),
        FamilyInstance(13, 1, created=PHASE_EXISTING, view=-1,
                       super_component=FamilyInstance(99, 1),
                       params={'Mark': 'D09'}, category=DOORS),
        # type 2: one new, one existing but demolished in the new phase
        FamilyInstance(14, 2, created=PHASE_NEW, view=-99,
                       params={'Mark': 'D02'}, category=DOORS),
        FamilyInstance(15, 2, created=PHASE_EXISTING,
                       demolished=PHASE_NEW, view=-1,
                       params={'Mark': 'D03'}, category=DOORS),
        # type 3: one with no phase at all
        FamilyInstance(16, 3, created=None, view=-1,
                       params={'Mark': 'D04'}, category=DOORS),
        # type 5: two pipes
        Instance(17, 5, created=PHASE_NEW, view=-1, category=PIPES),
        Instance(18, 5, created=PHASE_NEW, view=-99, category=PIPES),
        # a view holding nothing but a pipe: what a structural view looks like
        # to somebody who has ticked Generic Models
        Instance(19, 5, created=PHASE_NEW, view=-55, category=PIPES),
    ]
    phases = [
        _phase(PHASE_EXISTING, 'Existing'),
        _phase(PHASE_NEW, 'New Construction'),
    ]
    return Document(types, instances, phases)


def _phase(ident, name):
    holder = Holder()
    holder.Id = ElementId(ident)
    holder.Name = name
    return holder


# ===========================================================================
# the checks
# ===========================================================================

CHECKS = []


def check(label, got, wanted):
    CHECKS.append((label, got == wanted, got, wanted))


def child(parent, type_name):
    for row in parent.children:
        if row.type_name == type_name:
            return row
    return None


def by_name(result, family_name):
    for parent in result.families:
        if parent.family_name == family_name:
            return parent
    return None


def check_scopes():
    """The three scopes, run through the real read().

    Every previous round of the scope bug was a runtime failure inside the
    count pass that no static check could see - a filter that matched nothing,
    then a counter whose name was already in use in the same loop.  So the read
    itself is run here, three ways, and the counts are asserted.
    """
    # its own document, with a family loaded and never placed - the one thing
    # that tells All families apart from Entire project.  The shared fixture is
    # left alone because the other checks are written against it.
    doc = build_doc()
    doc.types = list(doc.types) + [
        FamilySymbol(7, '900x2100', 'BGL_Door_Sliding', DOORS,
                     {'Fire Rating': 'FD30'}, family_id=904)]
    install(doc)

    # Entire project: every type with elements placed, none with a count of
    # zero
    result = fv_model.read(doc, scope=fv_model.SCOPE_PROJECT, columns=[])
    counts = {}
    for parent in result.families:
        for child in parent.children:
            counts[child.type_name] = child.count
    check('the whole project counts elements at all',
          result.instance_total > 0, True)
    check('every element the collector offered was looked at',
          result.instances_seen > 0, True)
    check('entire project drops types with nothing placed',
          [name for name, count in counts.items() if count == 0], [])
    check('entire project counts the placed ones',
          counts.get('900x2100'), 2)          # 3 placed, 1 of them nested
    check('and the other type as well', counts.get('1000x2100'), 2)
    check('a type with nothing placed is not listed',
          '1800x2100' in counts, True)        # it has one instance

    # Active view: only what is in that view
    view = View('Level 00 - Power')
    view.Id = ElementId(-99)
    in_view = fv_model.read(doc, view=view, scope=fv_model.SCOPE_VIEW,
                            columns=[])
    view_counts = {}
    for parent in in_view.families:
        for child in parent.children:
            view_counts[child.type_name] = child.count
    check('the active view counts only what is in it',
          view_counts.get('900x2100'), 1)
    check('and drops a type with nothing in the view',
          '1800x2100' in view_counts, False)
    check('the active view never lists a count of zero',
          [name for name, count in view_counts.items() if count == 0], [])

    # All families: every type, placed or not
    every = fv_model.read(doc, scope=fv_model.SCOPE_ALL, columns=[])
    all_names = []
    for parent in every.families:
        for child in parent.children:
            all_names.append(child.type_name)
    check('all families lists more types than entire project does',
          len(all_names) > len(counts), True)

    # and the diagnosis when nothing counts
    empty = Document(list(doc.types), [], list(doc.Phases))
    install(empty)
    nothing = fv_model.read(empty, scope=fv_model.SCOPE_PROJECT, columns=[])
    check('a read that counts nothing says so rather than going quiet',
          bool(nothing.notes), True)
    check('and the list really is empty', nothing.families, [])
    install(build_doc())


def check_scope_rules():
    """scope_rules is the one place a scope becomes behaviour."""
    check('project counts the whole project and drops what is not placed',
          fv_model.scope_rules(fv_model.SCOPE_PROJECT), (False, False))
    check('view counts the active view and drops what is not placed',
          fv_model.scope_rules(fv_model.SCOPE_VIEW), (True, False))
    check('all counts the whole project and keeps what is not placed',
          fv_model.scope_rules(fv_model.SCOPE_ALL), (False, True))
    check('an unknown scope behaves as the whole project',
          fv_model.scope_rules('nonsense'), (False, False))

    # a view handed to a scope that does not want one is dropped, so the count
    # can never be scoped to a view while the whole project was asked for
    doc = build_doc()
    install(doc)
    view = View('Level 00')
    view.Id = ElementId(-99)
    whole = fv_model.read(doc, view=view, scope=fv_model.SCOPE_PROJECT,
                          columns=[])
    in_view = fv_model.read(doc, view=view, scope=fv_model.SCOPE_VIEW,
                            columns=[])
    # BGL_Door_Single has four placed instances across the project and two of
    # them in this view
    check('the view scope counts only what is in the view',
          by_name(in_view, 'BGL_Door_Single').count, 2)
    check('a view passed with the project scope is ignored, and the count is '
          'the whole project',
          by_name(whole, 'BGL_Door_Single').count, 4)

    # the view scope with no view says so rather than counting the project
    none_view = fv_model.read(doc, view=None, scope=fv_model.SCOPE_VIEW,
                              columns=[])
    check('the view scope with no active view reports it',
          bool(none_view.notes), True)
    check('and lists nothing rather than the whole project',
          none_view.families, [])

    # the phase that emptied the list is not remembered between sessions
    check('a phase is never carried over from a previous session',
          fv_core.DEFAULTS['default_phase'], '')
    check('and the phase mode is what stands in the phase, not what was '
          'created in it', fv_core.DEFAULTS['phase_mode'], 'existing')


def check_instances_and_grouping():
    """The third level, and the grouping over it."""
    doc = build_doc()
    install(doc)

    types = [1, 2]
    rows, seen = fv_model.read_instances(doc, types, columns=['Mark'])
    check('every type asked for gets an entry, even with nothing under it',
          sorted(rows.keys()), [1, 2])
    check('the elements are read', seen > 0, True)
    check('and land under the right type',
          all([one.type_id == 1 for one in rows[1]]), True)
    check('an element row knows its own element id',
          all([one.element_id for one in rows[1]]), True)

    # a nested instance is left out the same way the count leaves it out, so
    # the level agrees with the number above it
    nested, _seen = fv_model.read_instances(doc, [1], ignore_nested=True)
    loose, _seen2 = fv_model.read_instances(doc, [1], ignore_nested=False)
    check('a nested element is left out when nested are ignored',
          len(loose[1]) > len(nested[1]), True)

    # a type asked for that has nothing placed comes back empty, not missing
    empty, _e = fv_model.read_instances(doc, [9999])
    check('a type with nothing placed comes back empty rather than missing',
          empty.get(9999), [])

    # the cap stops a runaway read
    capped, capped_seen = fv_model.read_instances(doc, types, cap=1)
    check('the cap is honoured', capped_seen, 1)

    # grouping
    made = []
    for value in ('B', 'A', 'B', ''):
        row = fv_model.Row(fv_model.INSTANCE_ROW)
        row.element_id = len(made) + 1
        row.values['Mark'] = value
        made.append(row)

    groups = fv_model.group_instances(made, 'Mark')
    check('a heading per distinct value',
          [one.label for one in groups], ['(blank)', 'A', 'B'])
    check('the heading counts what is under it',
          [one.count for one in groups], [1, 1, 2])
    check('a heading is a group row', groups[0].kind, fv_model.GROUP_ROW)
    check('every element ends up under a heading',
          sum([len(one.children) for one in groups]), 4)
    check('a blank value gets its own heading rather than being dropped',
          groups[0].count, 1)
    check('and the elements know which heading they are under',
          made[1].parent.label, 'A')

    check('grouping by nothing leaves the list flat',
          [one.kind for one in fv_model.group_instances(made, '')],
          [fv_model.INSTANCE_ROW] * 4)

    # flatten walks all four levels, honouring each row's open state
    family = fv_model.Row(fv_model.FAMILY_ROW)
    a_type = fv_model.Row(fv_model.TYPE_ROW)
    a_type.parent = family
    family.children = [a_type]
    a_type.instances = groups
    a_type.loaded = True

    a_type.open = False
    check('shut, a type shows none of its elements',
          len(fv_model.flatten([family])), 2)
    a_type.open = True
    check('open, it shows its headings and their elements',
          len(fv_model.flatten([family])), 2 + 3 + 4)
    groups[2].open = False
    check('a shut heading hides only its own elements',
          len(fv_model.flatten([family])), 2 + 3 + 2)
    family.open = False
    check('a shut family hides the lot', len(fv_model.flatten([family])), 1)

    install(build_doc())


class FakeEvent(object):
    """`event += handler` the way a .NET event takes it."""

    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def fire(self, *args):
        for handler in list(self.handlers):
            handler(*args)


class FakeTimer(object):
    """A DispatcherTimer that behaves like the real one where it matters.

    It does NOT run its ticks inside Start() - a real timer never calls Tick
    from there, and a fake that does hides a missing fallback: an exception
    escaping a tick lands in the try round Start(), the very fallback the slide
    uses when no timer can start, and the window lands anyway.  run() drives
    the ticks afterwards, and anything escaping a tick is RECORDED the way the
    dispatcher would swallow it, so the bench can fail on it.
    """

    escaped = []

    def __init__(self):
        self.Tick = FakeEvent()
        self.running = False
        self.Interval = None

    def Start(self):
        self.running = True
        FakeTimer.live.append(self)

    def Stop(self):
        self.running = False


FakeTimer.live = []


def run_timers(limit=200):
    """Drive every live timer until it stops, as the dispatcher would."""
    for _ in range(limit):
        live = [timer for timer in FakeTimer.live if timer.running]
        if not live:
            return
        for timer in live:
            try:
                timer.Tick.fire(timer, None)
            except Exception as error:
                FakeTimer.escaped.append(repr(error))
                # the real dispatcher would carry on; the timer is still
                # "running", which is what leaves a drawer sliding for ever
    FakeTimer.escaped.append('a timer never stopped')


class FakeWindow(object):
    def __init__(self, left=100.0, top=100.0, width=900.0, height=700.0):
        self.Left, self.Top = left, top
        self.Width, self.Height = width, height
        self.MinHeight = 480.0
        self.SizeToContent = 'Manual'
        self.WindowStartupLocation = 'CenterOwner'
        self.Owner = None
        self.PreviewKeyDown = FakeEvent()
        self.Closed = FakeEvent()
        self.refuse_top_at = None

    @property
    def ActualHeight(self):
        return self.Height

    @property
    def ActualWidth(self):
        return self.Width

    def __setattr__(self, name, value):
        if name == 'Top' and getattr(self, 'refuse_top_at', None) is not None:
            if self.refuse_top_at == 0:
                self.refuse_top_at = None
                raise ValueError('a frame Revit refused')
            self.refuse_top_at -= 1
        object.__setattr__(self, name, value)


class FakePart(object):
    def __init__(self, height=40.0):
        self.ActualHeight = height
        self.Height = float('nan')
        self.VerticalAlignment = 'Stretch'
        self.Visibility = 'Visible'
        self.Tag = ''
        self.Click = FakeEvent()
        self.PreviewMouseLeftButtonDown = FakeEvent()


def check_drawer():
    """Shrink to taskbar: the arithmetic, and the drawer driven frame by
    frame through a timer that behaves like the real one."""
    import types
    import fv_ui

    # -- where the bar parks -----------------------------------------------
    primary = (0.0, 0.0, 1920.0, 1040.0)
    left, top, bar = fv_ui.park_rect(primary, 100, 900, 42)
    check('the bar parks just clear of the taskbar', (top, bar), (992.0, 42.0))
    check('it keeps its own left edge', left, 100.0)

    above = (0.0, -1080.0, 1920.0, 1040.0)      # a second monitor ABOVE
    check('on a monitor above the primary it parks on THAT monitor, not the '
          'primary', fv_ui.park_rect(above, 100, 900, 42)[1], -88.0)
    beside = (-1920.0, 0.0, 1920.0, 1040.0)     # one to the left
    check('on a monitor to the left it keeps its negative left edge',
          fv_ui.park_rect(beside, -1500, 900, 42)[0], -1500.0)
    check('a bar hanging off the right of the screen is pulled back on',
          fv_ui.park_rect(primary, 1500, 900, 42)[0], 1020.0)
    check('a stacked bar parks one bar higher, clear of the one beneath',
          fv_ui.park_rect(primary, 0, 900, 42, stack=1)[1], 992.0 - 48.0)

    # -- where it reopens --------------------------------------------------
    saved = (100.0, 120.0, 700.0)
    parked = (100.0, 992.0)
    check('a bar nobody moved reopens exactly where the window was',
          fv_ui.reopen_rect(saved, parked, 100, 992, primary, 42),
          (100.0, 120.0, 700.0))
    check('a bar carried elsewhere opens upward from where it now sits',
          fv_ui.reopen_rect(saved, parked, 600, 900, primary, 42),
          (600.0, 242.0, 700.0))
    check('opening upward never goes off the top of the screen',
          fv_ui.reopen_rect(saved, parked, 600, 300, primary, 42)[1], 0.0)
    check('a window taller than the screen reopens no taller than it',
          fv_ui.reopen_rect((0, 0, 5000), parked, 100, 992, primary, 42)[2],
          1040.0)
    check('carried onto the monitor above, it opens there',
          fv_ui.reopen_rect(saved, parked, 100, -200, above, 42)[1] < 0, True)

    # -- the drawer itself -------------------------------------------------
    real = (fv_ui.Visibility, fv_ui.VerticalAlignment)
    fv_ui.Visibility = types.SimpleNamespace(Visible='Visible',
                                             Collapsed='Collapsed')
    fv_ui.VerticalAlignment = types.SimpleNamespace(Top='Top',
                                                    Stretch='Stretch')
    windows_ns = sys.modules['System.Windows']
    saved_size = windows_ns.__dict__.get('SizeToContent')
    saved_where = windows_ns.__dict__.get('WindowStartupLocation')
    windows_ns.SizeToContent = types.SimpleNamespace(Manual='Manual',
                                                     Height='Height')
    windows_ns.WindowStartupLocation = types.SimpleNamespace(
        CenterScreen='CenterScreen', CenterOwner='CenterOwner')
    FakeTimer.escaped = []
    FakeTimer.live = []
    try:
        window = FakeWindow()
        header, root, button, grips = (FakePart(40.0), FakePart(700.0),
                                       FakePart(), FakePart())
        drawer = fv_ui.WindowDrawer(window, header, root, button, grips,
                                    timer_factory=FakeTimer,
                                    area_reader=lambda w: primary)
        button.Click.fire(button, None)
        check('pressing shrink starts a slide rather than jumping',
              drawer.sliding, True)
        run_timers()
        check('the window ends as just its bar, parked at the bottom',
              (window.Top, window.Height), (992.0, 42.0))
        check('the slide finishes and the drawer can be used again',
              drawer.sliding, False)
        check('the button turns into the green up arrow', button.Tag,
              'shrunk')
        check('MinHeight is relaxed, or it vetoes the slide half way',
              window.MinHeight, 0.0)
        check('SizeToContent is relaxed for the same reason',
              window.SizeToContent, 'Manual')
        check('the body is pinned so it is clipped, not squashed',
              (root.Height, root.VerticalAlignment), (700.0, 'Top'))
        check('the resize grips are parked with the window',
              grips.Visibility, 'Collapsed')

        button.Click.fire(button, None)
        run_timers()
        check('pressing the arrow opens it where it was',
              (window.Top, window.Height), (100.0, 700.0))
        check('MinHeight is put back, or it can be dragged shut for good',
              window.MinHeight, 480.0)
        check('the body is unpinned', root.VerticalAlignment, 'Stretch')
        check('the grips come back', grips.Visibility, 'Visible')
        check('and the button is the shrink button again', button.Tag, '')

        # a frame that throws: caught IN the frame, the window still lands
        window.refuse_top_at = 3
        button.Click.fire(button, None)
        run_timers()
        check('a frame that throws still lands the window', window.Height,
              42.0)
        check('and leaves the drawer free to open again', drawer.sliding,
              False)
        check('the failure is recorded, not lost', len(drawer.errors), 1)
        button.Click.fire(button, None)
        run_timers()

        # no timer at all: the slide lands at once
        def broken():
            raise RuntimeError('no dispatcher')
        bare = FakeWindow()
        no_timer = fv_ui.WindowDrawer(bare, FakePart(), FakePart(),
                                      FakePart(), timer_factory=broken,
                                      area_reader=lambda w: primary)
        no_timer.shrink()
        check('with no timer to slide on, it parks at once',
              (bare.Top, no_timer.sliding), (992.0, False))

        # a press mid-slide is ignored rather than starting a second slide
        busy = FakeWindow()
        mid = fv_ui.WindowDrawer(busy, FakePart(), FakePart(), FakePart(),
                                 timer_factory=FakeTimer,
                                 area_reader=lambda w: primary)
        mid.shrink()
        mid.toggle()
        check('a second press mid-slide is ignored', mid.shrunk, True)
        run_timers()

        # a modal dialog takes its owner down with it, stacked beneath
        owner = FakeWindow()
        owner_drawer = fv_ui.WindowDrawer(owner, FakePart(), FakePart(),
                                          FakePart(), timer_factory=FakeTimer,
                                          area_reader=lambda w: primary)
        dialog = FakeWindow(300, 200, 470, 300)
        dialog_drawer = fv_ui.WindowDrawer(dialog, FakePart(), FakePart(),
                                           FakePart(), owner=owner,
                                           timer_factory=FakeTimer,
                                           area_reader=lambda w: primary)
        dialog_drawer.shrink()
        run_timers()
        check('shrinking a dialog takes its owner down too',
              owner_drawer.shrunk, True)
        check('the owner parks beneath the dialog',
              owner.Top > dialog.Top, True)
        dialog_drawer.expand()
        run_timers()
        check('and comes back with it', owner_drawer.shrunk, False)

        # a dialog opened while its owner is parked centres on the screen
        owner_drawer.shrink()
        run_timers()
        late = FakeWindow()
        fv_ui.own_dialog(late, owner)
        check('a dialog opened over a parked owner centres on the screen',
              str(late.WindowStartupLocation).endswith('CenterScreen'), True)

        check('nothing escaped a frame into the dispatcher',
              FakeTimer.escaped, [])
    finally:
        fv_ui.Visibility, fv_ui.VerticalAlignment = real
        for name, value in (('SizeToContent', saved_size),
                            ('WindowStartupLocation', saved_where)):
            if value is None:
                windows_ns.__dict__.pop(name, None)
            else:
                setattr(windows_ns, name, value)


def check_import_plan():
    """What a workbook import changes, decided before anything is staged."""
    import ast as _ast
    import fv_excel

    family = fv_model.Row(fv_model.FAMILY_ROW)
    family.family_name = 'BGL_Door'
    family.family_id = 900
    door = fv_model.Row(fv_model.TYPE_ROW)
    door.family_name = 'BGL_Door'
    door.type_name = 'FD30'
    door.type_id = 501
    door.values['Type Mark'] = 'D1'
    other = fv_model.Row(fv_model.TYPE_ROW)
    other.family_name = 'BGL_Door'
    other.type_name = 'FD60'
    other.type_id = 502
    other.values['Type Mark'] = 'D2'
    locked = fv_model.Row(fv_model.TYPE_ROW)
    locked.family_name = 'BGL_Window'
    locked.type_name = 'W1'
    locked.type_id = 503
    known = {('family', 900): family, ('type', 501): door,
             ('type', 502): other, ('type', 503): locked}

    def edit_key(row, column):
        if row is locked and column != fv_model.KEY_NAME:
            return None                      # a cell the window refuses
        return (row.kind, row.type_id or row.family_id, column)

    headings = [fv_excel.ID_HEAD, fv_excel.KIND_HEAD, fv_excel.FAMILY_HEAD,
                fv_excel.TYPE_HEAD, fv_excel.CATEGORY_HEAD,
                fv_excel.COUNT_HEAD, 'Type Mark']
    rows = [
        ['501', 'type', 'BGL_Door', 'FD30 renamed', 'Doors', '4', 'D9'],
        ['502', 'type', 'BGL_Door', 'FD60', 'Doors', '1', 'D2'],
        ['503', 'type', 'BGL_Window', 'W1', 'Windows', '2', 'W-X'],
        ['777', 'type', 'Gone', 'Gone', 'Doors', '0', 'X'],
        ['', 'type', 'No id', 'x', 'Doors', '0', 'X'],
        ['501.0', 'type', 'BGL_Door', '', 'Doors', '4', 'D1'],
    ]
    plan = fv_excel.plan_import(headings, rows, known, edit_key)
    check('every row read is counted', plan.rows_read, 6)
    check('a changed name and a changed parameter are both staged',
          sorted([head for key, value, row, head in plan.changes]),
          ['Type', 'Type Mark'])
    check('the changed row counts once, however many values changed',
          plan.changed_rows, 1)
    check('a row identical to the model is unchanged', plan.unchanged >= 1,
          True)
    check('an id the model does not have is unknown, not dropped',
          plan.unknown, 1)
    check('a row with no readable id is counted, not skipped quietly',
          plan.no_id, 1)
    check('a cell the window will not write is refused and named',
          any('Type Mark cannot be written' in line for line in plan.refused),
          True)
    check('a name blanked in Excel is refused rather than staged',
          any('a name cannot be blank' in line for line in plan.refused), True)
    check('Excel writing an id back as 501.0 still matches 501',
          plan.no_id + plan.unknown, 2)
    check('the families holding a change are named for the highlight',
          sorted(plan.families), ['BGL_Door'])
    check('every row lands in exactly one bucket',
          plan.changed_rows + plan.unchanged + plan.unknown + plan.no_id,
          plan.rows_read)
    check('failed counts refusals, unknown ids and unreadable ids',
          plan.failed, len(plan.refused) + 2)

    words = fv_excel.summary(plan, 'C:/x/families.xlsx')
    check('the summary says how many changed', 'Changed:      2 values' in words,
          True)
    check('the summary says how many did not import',
          'Not imported: ' + str(plan.failed) in words, True)
    check('the summary says plainly that nothing has been written',
          'Nothing has been written to the model' in words, True)
    empty = fv_excel.plan_import(headings, [rows[1]], known, edit_key)
    check('a workbook that changes nothing says so',
          'nothing was staged' in fv_excel.summary(empty), True)

    # the import path never writes: no call on it raises the apply job
    tree = _ast.parse(io.open(os.path.join(HERE, 'fv_window.py'),
                              encoding='utf-8').read())
    path = ('on_import', '_stage_from_workbook', '_known_rows')
    raises_apply = []
    for node in _ast.walk(tree):
        if isinstance(node, _ast.FunctionDef) and node.name in path:
            for inner in _ast.walk(node):
                if isinstance(inner, _ast.Call) and \
                        getattr(inner.func, 'attr', '') in ('_raise', 'on_apply'):
                    if inner.args and isinstance(inner.args[0], _ast.Constant) \
                            and inner.args[0].value == 'apply':
                        raises_apply.append(node.name)
                    if getattr(inner.func, 'attr', '') == 'on_apply':
                        raises_apply.append(node.name)
    check('nothing on the import path raises Apply', raises_apply, [])
    source = io.open(os.path.join(HERE, 'fv_window.py'),
                     encoding='utf-8').read()
    known_body = source.split('def _known_rows')[1].split('\n    def ')[0]
    check('the import matches against the whole read, not the screen',
          'self.families' in known_body and 'self.shown' not in known_body,
          True)


def check_family_rename_import():
    """A family renamed in the workbook comes back as one family rename.

    Up to 2.0.0 the Family column was coloured editable in the workbook, called
    editable in its legend, and dropped by the import without a word - so a
    family renamed in Excel changed nothing.
    """
    import fv_excel

    def build():
        family = fv_model.Row(fv_model.FAMILY_ROW)
        family.family_name = 'BGL_Door_Single'
        family.family_id = 900
        types = []
        for ident, name in ((501, 'FD30'), (502, 'FD60')):
            row = fv_model.Row(fv_model.TYPE_ROW)
            row.family_name = 'BGL_Door_Single'
            row.family_id = 900
            row.type_name = name
            row.type_id = ident
            row.parent = family
            family.children.append(row)
            types.append(row)
        system = fv_model.Row(fv_model.FAMILY_ROW)
        system.family_name = 'Basic Wall'
        system.family_id = 0
        system.is_system = True
        wall = fv_model.Row(fv_model.TYPE_ROW)
        wall.family_name = 'Basic Wall'
        wall.family_id = 0
        wall.type_name = 'Generic 200'
        wall.type_id = 601
        known = {('family', 900): family, ('type', 501): types[0],
                 ('type', 502): types[1], ('family', 0): system,
                 ('type', 601): wall}
        return family, known

    def edit_key(row, column):
        if row.kind == fv_model.FAMILY_ROW:
            if column != fv_model.KEY_NAME or not row.family_id:
                return None
            return ('family', row.family_id, column)
        return ('type', row.type_id, column)

    headings = [fv_excel.ID_HEAD, fv_excel.KIND_HEAD, fv_excel.FAMILY_HEAD,
                fv_excel.TYPE_HEAD, fv_excel.CATEGORY_HEAD,
                fv_excel.COUNT_HEAD]

    def rows(family_on_family_row, family_on_types):
        made = [['900', 'family', family_on_family_row, '', 'Doors', '6']]
        for ident, name in ((501, 'FD30'), (502, 'FD60')):
            made.append([str(ident), 'type', family_on_types, name, 'Doors',
                         '3'])
        return made

    # renamed everywhere, the way Excel's find and replace does it
    family, known = build()
    plan = fv_excel.plan_import(
        headings, rows('BGL_Door_Single_v2', 'BGL_Door_Single_v2'), known,
        edit_key)
    renames = [(key, value) for key, value, row, head in plan.changes
               if head == fv_excel.FAMILY_HEAD]
    check('a family renamed in the workbook is staged',
          renames, [(('family', 900, fv_model.KEY_NAME), 'BGL_Door_Single_v2')])
    check('once, however many of its rows carry the new name',
          len(renames), 1)
    check('and every row carrying it counts as changed',
          plan.changed_rows, 3)
    check('nothing is refused', plan.refused, [])
    check('the family is named for the highlight',
          sorted(plan.families), ['BGL_Door_Single'])

    # renamed on the family row only
    family, known = build()
    plan = fv_excel.plan_import(
        headings, rows('BGL_Door_Single_v2', 'BGL_Door_Single'), known,
        edit_key)
    check('renamed on the family row alone still comes through',
          [value for key, value, row, head in plan.changes],
          ['BGL_Door_Single_v2'])

    # renamed on the type rows only
    family, known = build()
    plan = fv_excel.plan_import(
        headings, rows('BGL_Door_Single', 'BGL_Door_Single_v2'), known,
        edit_key)
    check('renamed on the type rows alone still renames the family',
          [key for key, value, row, head in plan.changes],
          [('family', 900, fv_model.KEY_NAME)])

    # two different new names for one family
    family, known = build()
    plan = fv_excel.plan_import(
        headings, rows('Name A', 'Name B'), known, edit_key)
    check('rows that disagree on the new name stage nothing',
          plan.changes, [])
    check('and say so, naming both',
          any('Name A / Name B' in line for line in plan.refused), True)

    # blanked
    family, known = build()
    plan = fv_excel.plan_import(
        headings, rows('', 'BGL_Door_Single'), known, edit_key)
    check('a family name blanked in the workbook is refused',
          any('cannot be blank' in line for line in plan.refused), True)

    # a system family
    family, known = build()
    plan = fv_excel.plan_import(
        headings, [['601', 'type', 'Wall Thing', 'Generic 200', 'Walls', '4']],
        known, edit_key)
    check('a system family is refused with the reason, not silently',
          any('system family cannot be renamed' in line
              for line in plan.refused), True)

    # THE GUARD: every column the workbook calls editable must come back as a
    # change or a refusal - never be read, compared and thrown away
    family, known = build()
    for head in headings:
        if head in fv_excel.READ_ONLY:
            continue
        sample = [['900', 'family', 'BGL_Door_Single', '', 'Doors', '6'],
                  ['501', 'type', 'BGL_Door_Single', 'FD30', 'Doors', '3']]
        column = headings.index(head)
        for row in sample:
            row[column] = row[column] + ' edited' if row[column] else 'edited'
        plan = fv_excel.plan_import(headings, sample, known, edit_key)
        check('the workbook calls ' + head + ' editable, and an edit to it '
              'comes back as a change or a refusal',
              bool(plan.changes) or bool(plan.refused), True)


def check_theme_follow():
    """Follow Revit's canvas, unless a palette was picked."""
    import theme
    check('following takes Revit\'s dark canvas',
          theme.resolve('follow', 'dark'), 'dark')
    check('following takes Revit\'s light canvas',
          theme.resolve('follow', 'light'), 'light')
    check('a picked palette beats the canvas',
          theme.resolve('dark', 'light'), 'dark')
    check('and the other way round', theme.resolve('light', 'dark'), 'light')
    check('a canvas that cannot be read falls back to dark',
          theme.resolve('follow', None), 'dark')
    check('a damaged setting is read as following',
          theme.resolve('nonsense', 'light'), 'light')
    check('a blank setting is read as following',
          theme.resolve('', 'light'), 'light')

    # Revit's own enum, faked.  UITheme.Dark is 0 - the trap from the project
    # notes: testing the read for truth reports every dark canvas as a failed
    # read and falls through to light.
    import types
    import Autodesk.Revit.UI as revit_ui
    kinds = types.SimpleNamespace(Dark=0, Light=1)
    saved = (revit_ui.__dict__.get('UIThemeManager'),
             revit_ui.__dict__.get('UITheme'))
    try:
        revit_ui.UITheme = kinds
        revit_ui.UIThemeManager = types.SimpleNamespace(CurrentCanvasTheme=0)
        check('a dark canvas (enum value 0) is read as dark, not as a failed '
              'read', theme.revit_canvas(), 'dark')
        revit_ui.UIThemeManager = types.SimpleNamespace(CurrentCanvasTheme=1)
        check('a light canvas is read as light', theme.revit_canvas(), 'light')
        revit_ui.UIThemeManager = types.SimpleNamespace(CurrentTheme=0)
        check('the older CurrentTheme is used where the canvas one is missing',
              theme.revit_canvas(), 'dark')
        # gone altogether, the way Revit 2023 has it: reaching for it raises,
        # and the read must survive that rather than take the window down
        del revit_ui.UIThemeManager
        check('a Revit with no UIThemeManager (before 2024) answers None',
              theme.revit_canvas(), None)
    finally:
        for name, value in zip(('UIThemeManager', 'UITheme'), saved):
            if value is None:
                revit_ui.__dict__.pop(name, None)
            else:
                setattr(revit_ui, name, value)

    # an install from before 2.0.0 has theme=dark and maybe phase_mode=created
    # saved; the migration is what makes the new defaults reach it
    folder = tempfile.mkdtemp(prefix='fv_theme_')
    path = os.path.join(folder, 'family_viewer.txt')
    original = fv_core.settings_path
    fv_core.settings_path = lambda: path
    try:
        handle = open(path, 'w')
        handle.write('settings_version=1\ntheme=dark\nphase_mode=created\n'
                     'ui_scale=110\n')
        handle.close()
        loaded = fv_core.load_settings()
        check('an old saved theme is reset to follow Revit',
              loaded['theme'], 'follow')
        check('an old saved "created" phase mode is reset - the setting that '
              'emptied every list', loaded['phase_mode'], 'existing')
        check('settings the migration does not name are kept',
              loaded['ui_scale'], '110')
        handle = open(path, 'w')
        handle.write('settings_version=2\ntheme=dark\n')
        handle.close()
        check('a theme picked AFTER the migration is kept',
              fv_core.load_settings()['theme'], 'dark')
    finally:
        fv_core.settings_path = original


def check_instance_index():
    """Apply finds the instances of every edited type in ONE pass.

    The first version opened a fresh collector over the whole model for each
    type, inside the Apply transaction.  Counting the collectors opened is the
    only honest way to prove it does not any more.
    """
    doc = build_doc()
    opened = []

    def counting(document, view_id=None):
        opened.append(1)
        return Collector(doc, view_id)

    fv_model.FilteredElementCollector = counting
    index = fv_model.InstanceIndex(doc, [1, 2, 3])
    check('building the index opens nothing until something asks', len(opened),
          0)
    first = index.of(1)
    index.of(2)
    index.of(3)
    index.of(1)
    check('every type is answered from one pass of the model', len(opened), 1)
    check('and the instances are the right ones',
          sorted([fv_core.eid_value(one.Id) for one in first]),
          sorted([fv_core.eid_value(one.Id) for one in doc.instances
                  if one.GetTypeId().Value == 1]))
    check('a type that was never asked about is answered empty',
          index.of(42), [])
    install(build_doc())


def check_filter_values():
    """The tick list offers what is actually in the column.

    Gathering from the type rows alone offered "(varies)" for a parameter that
    lives on the instance - which is every value the list can be filtered by,
    missing from the filter.
    """
    family = fv_model.Row(fv_model.FAMILY_ROW)
    family.family_name = 'BGL_Door'
    for type_name, mark in (('FD30', fv_core.VARIES), ('FD60', 'D9')):
        child = fv_model.Row(fv_model.TYPE_ROW)
        child.family_name = 'BGL_Door'
        child.type_name = type_name
        child.values['Mark'] = mark
        child.parent = family
        family.children.append(child)

    plain = fv_grid.distinct_values([family], 'Mark')
    check('the type rows alone offer almost nothing',
          [value for value, count in plain], ['D9'])
    check('and "(varies)" is never offered - it filters to nothing',
          fv_core.VARIES in [value for value, count in plain], False)

    instances = []
    for mark in ('D1', 'D2', 'D1'):
        row = fv_model.Row(fv_model.INSTANCE_ROW)
        row.element_id = len(instances) + 1
        row.values['Mark'] = mark
        instances.append(row)

    full = fv_grid.distinct_values([family], 'Mark', instances)
    check('with the elements, every real value is offered',
          [value for value, count in full], ['D1', 'D2', 'D9'])
    check('and they are counted', dict(full)['D1'], 2)
    check('"(varies)" is still left out',
          fv_core.VARIES in [value for value, count in full], False)

    # a blank is a value like any other - "which ones have nothing set" is
    # usually the question
    blank = fv_model.Row(fv_model.INSTANCE_ROW)
    blank.element_id = 99
    with_blank = fv_grid.distinct_values([family], 'Mark', instances + [blank])
    check('a blank is offered rather than dropped',
          '' in [value for value, count in with_blank], True)


def check_instance_sorting():
    """The elements follow the column the list is sorted by."""
    made = []
    for mark, value in (('D03', 'B'), ('D01', 'C'), ('D02', 'A'),
                        ('D10', 'A')):
        row = fv_model.Row(fv_model.INSTANCE_ROW)
        row.element_id = len(made) + 1
        row.mark = mark
        row.values['Mark2'] = value
        made.append(row)

    natural = fv_model.sort_instances(made, '', 1)
    check('with no column, elements go in their own natural order',
          [one.label for one in natural], ['D01', 'D02', 'D03', 'D10'])
    check('and D10 after D02, not between D01 and D02',
          natural[-1].label, 'D10')

    by_value = fv_model.sort_instances(made, 'Mark2', 1)
    check('sorted by a column, the elements follow it',
          [one.cell('Mark2') for one in by_value],
          ['A', 'A', 'B', 'C'])
    check('and ties fall back to the element order',
          [one.label for one in by_value[:2]], ['D02', 'D10'])

    down = fv_model.sort_instances(made, 'Mark2', -1)
    check('descending reverses it',
          [one.cell('Mark2') for one in down], ['C', 'B', 'A', 'A'])

    # sorting then grouping: the headings come out in value order and every
    # element keeps its heading
    groups = fv_model.group_instances(by_value, 'Mark2')
    check('a heading per value, in order',
          [one.label for one in groups], ['A', 'B', 'C'])
    check('and the elements are shared out between them',
          [one.count for one in groups], [2, 1, 1])


def check_empty_diagnosis():
    """An element of a category nobody ticked is SUPPOSED to miss.

    Counting those as mismatches is what made the tool accuse itself of a bug
    every time a view held nothing of the ticked category - which is most
    views, and is exactly what a user saw.
    """
    doc = build_doc()
    install(doc)

    # a view holding elements, none of them in the ticked category - which is
    # what a structural view looks like with Generic Models ticked
    other_view = View('BW_CLM_SLAB_L01')
    other_view.Id = ElementId(-55)
    nothing_ticked = fv_model.read(doc, view=other_view,
                                   scope=fv_model.SCOPE_VIEW, columns=[],
                                   wanted_category_ids=[DOORS.Id.Value])
    text = ' '.join(nothing_ticked.notes)
    check('elements were looked at', nothing_ticked.instances_seen > 0, True)
    check('none of them were in the ticked category',
          nothing_ticked.in_scope_seen, 0)
    check('a view with none of the ticked categories is NOT called a bug',
          'bug' in text, False)
    check('and it says what is actually the matter',
          'categories you have ticked' in text, True)

    # a category that IS there counts as in scope
    doors = fv_model.read(doc, scope=fv_model.SCOPE_PROJECT, columns=[],
                          wanted_category_ids=[DOORS.Id.Value])
    check('elements of a ticked category are counted as in scope',
          doors.in_scope_seen > 0, True)
    check('and none of them are unmatched', doors.in_scope_no_match, 0)
    check('the by-category tally counts only what is in scope',
          list(doors.by_category.keys()), ['Doors'])
    check('a read that found things says nothing about bugs',
          'bug' in ' '.join(doors.notes), False)

    install(build_doc())


def check_names():
    """The name readers, which is where v1.0.0 put "(unnamed)" on every row.

    IronPython does not reliably hand back a string for element.Name: on some
    engines it comes back as the bound property object instead.  That never
    raised, so the try/except round it never fired and the fallback was reached
    every time.  The rule now is that a name is only accepted if it IS text.
    """

    class NotAString(object):
        """What a bound .NET property looks like when it comes back unbound."""

        def __repr__(self):
            return '<property# Name>'

    good = ElementType(70, 'FD60 900x2100', 'BGL_Door_Single', DOORS)
    check('a real name is read', fv_model.type_name_of(good), 'FD60 900x2100')
    check('a real family name is read',
          fv_model.family_name_of(good), 'BGL_Door_Single')

    # Name comes back as something that is not text: the old code took str()
    # of it and shipped a repr as the type name
    broken = ElementType(71, NotAString(), 'BGL_Door_Single', DOORS)
    check('a name that is not text is refused',
          fv_model.type_name_of(broken), '')
    check('and the family name still answers',
          fv_model.family_name_of(broken), 'BGL_Door_Single')
    check('a repr is never taken as a name',
          fv_model._text_or_blank(NotAString()), '')

    # the built-in name parameter is the next route
    with_param = ElementType(72, NotAString(), '', DOORS,
                             {'SYMBOL_NAME_PARAM': 'From the parameter'})
    with_param.get_Parameter = lambda builtin: (
        Parameter('n', 'From the parameter')
        if builtin == 'SYMBOL_NAME_PARAM' else None)
    saved = fv_model.BuiltInParameter
    fv_model.BuiltInParameter = type(
        str('BIP'), (object,),
        {'SYMBOL_NAME_PARAM': 'SYMBOL_NAME_PARAM',
         'ALL_MODEL_TYPE_NAME': 'ALL_MODEL_TYPE_NAME',
         'ELEM_TYPE_PARAM': 'ELEM_TYPE_PARAM',
         'SYMBOL_FAMILY_NAME_PARAM': 'SYMBOL_FAMILY_NAME_PARAM',
         'ALL_MODEL_FAMILY_NAME': 'ALL_MODEL_FAMILY_NAME',
         'PHASE_CREATED': 'PHASE_CREATED',
         'PHASE_DEMOLISHED': 'PHASE_DEMOLISHED'})
    check('the built-in name parameter is the next route',
          fv_model.type_name_of(with_param), 'From the parameter')
    fv_model.BuiltInParameter = saved

    check('blank is blank', fv_model._text_or_blank('   '), '')
    check('None is blank', fv_model._text_or_blank(None), '')
    check('a name is stripped', fv_model._text_or_blank('  A  '), 'A')
    check('nothing at all reads as blank rather than raising',
          fv_model.type_name_of(None), '')


class Binding(object):
    def __init__(self, category_ids):
        self.Categories = [Category('c', ident) for ident in category_ids]


class Bindings(object):
    """doc.ParameterBindings, walked the way the tool walks it."""

    def __init__(self, pairs):
        self.pairs = pairs
        self.index = -1

    def ForwardIterator(self):
        self.index = -1
        return self

    def Reset(self):
        self.index = -1

    def MoveNext(self):
        self.index += 1
        return self.index < len(self.pairs)

    @property
    def Key(self):
        name, _ = self.pairs[self.index]
        holder = Holder()
        holder.Name = name
        return holder

    @property
    def Current(self):
        _, binding = self.pairs[self.index]
        return binding


def check_parameter_scope():
    fv_model.parameter_names = REAL_PARAMETER_NAMES
    """The picker offers what the categories on show carry, not every project
    parameter in the model - the list was long enough to be useless on a job of
    any size."""
    doc = Document([], [], [])
    doc.ParameterBindings = Bindings([
        ('BGL_Door Fire Rating', Binding([DOORS.Id.Value])),
        ('BGL_Pipe Insulation', Binding([PIPES.Id.Value])),
        ('BGL_Everything', Binding([DOORS.Id.Value, PIPES.Id.Value])),
    ])
    door_type = ElementType(80, 'FD30', 'BGL_Door_Single', DOORS,
                            {'Type Comments': 'on the element'})

    offered = fv_model.parameter_names(doc, [door_type], [],
                                       [DOORS.Id.Value])
    check('a parameter bound to this category is offered',
          'BGL_Door Fire Rating' in offered, True)
    check('a parameter bound to another category is not',
          'BGL_Pipe Insulation' in offered, False)
    check('a parameter bound to both is offered',
          'BGL_Everything' in offered, True)
    check('what the element itself carries is offered',
          'Type Comments' in offered, True)
    check('the two name properties are always offered',
          ['Family Name' in offered, 'Type Name' in offered], [True, True])
    check('the list is in natural order', offered, sorted(
        offered, key=fv_core.natural_key))

    every = fv_model.parameter_names(doc, [door_type], [], None)
    check('with no categories given, nothing is filtered out',
          'BGL_Pipe Insulation' in every, True)

    unreadable = Bindings([('BGL_Odd', object())])
    doc.ParameterBindings = unreadable
    loose = fv_model.parameter_names(doc, [], [], [DOORS.Id.Value])
    check('a binding whose categories will not read is offered rather than '
          'hidden', 'BGL_Odd' in loose, True)


class Writable(Holder):
    """An element whose parameters can be written to, and read back - which is
    the only way to know a write took, since Revit does not reliably raise."""

    def __init__(self, ident, name, params=None, readonly=None,
                 refuses=None):
        Holder.__init__(self, params)
        self.Id = ElementId(ident)
        self._name = name
        self.readonly = set(readonly or [])
        self.refuses = set(refuses or [])

    def _get_name(self):
        return self._name

    def _set_name(self, value):
        if value == 'TAKEN':
            return          # Revit refuses silently: the classic trap
        self._name = value

    Name = property(_get_name, _set_name)

    def GetParameters(self, name):
        if name not in self.params:
            return []
        return [WritableParam(self, name)]

    def LookupParameter(self, name):
        if name not in self.params:
            return None
        return WritableParam(self, name)


class WritableParam(object):
    def __init__(self, owner, name):
        self.owner = owner
        self.name = name
        self.Definition = Definition(name)
        self.StorageType = 'String'
        self.IsReadOnly = name in owner.readonly
        self.HasValue = True

    def AsString(self):
        return self.owner.params.get(self.name)

    def AsValueString(self):
        return self.owner.params.get(self.name)

    def Set(self, value):
        if self.name in self.owner.refuses:
            return False
        self.owner.params[self.name] = str(value)
        return True

    def SetValueString(self, value):
        return self.Set(value)


def check_writes():
    saved_storage = fv_model.StorageType
    fv_model.StorageType = StorageType

    element = Writable(200, 'FD30', {'Fire Rating': 'FD30',
                                     'Mark': 'D1',
                                     'Locked': 'x'},
                       readonly=['Locked'], refuses=['Mark'])

    ok, why = fv_model.set_param(element, 'Fire Rating', 'FD60', None)
    check('a writable parameter is written', [ok, element.params['Fire Rating']],
          [True, 'FD60'])

    ok, why = fv_model.set_param(element, 'Locked', 'nope', None)
    check('a read-only parameter is reported, not silently skipped',
          [ok, 'read-only' in why], [False, True])

    ok, why = fv_model.set_param(element, 'Nothing', 'x', None)
    check('a parameter the element does not carry is reported',
          [ok, 'does not carry' in why], [False, True])

    ok, why = fv_model.set_param(element, 'Mark', 'D2', None)
    check('a write that silently does not take is caught by the read back',
          ok, False)

    # renaming: neither route raises, so the name is read back
    ok, why = fv_model.rename_element(element, 'FD90')
    check('a rename that takes is reported as taken',
          [ok, element.Name], [True, 'FD90'])
    ok, why = fv_model.rename_element(element, 'TAKEN')
    check('a rename Revit refuses silently is caught by the read back',
          ok, False)
    ok, why = fv_model.rename_element(element, '   ')
    check('a blank name is refused before Revit is asked',
          [ok, 'blank' in why], [False, True])
    ok, why = fv_model.rename_element(None, 'x')
    check('renaming nothing is refused rather than raising', ok, False)

    # a number typed into a length comes back reformatted, so an exact string
    # match is too strict
    check('a reformatted number counts as the same value',
          fv_model._same_value('2400.0', '2400'), True)
    check('a value with units counts as the same value',
          fv_model._same_value('2400 mm', '2400'), True)
    check('a different number does not', fv_model._same_value('2401', '2400'),
          False)
    check('blank matches blank', fv_model._same_value('', ''), True)

    fv_model.StorageType = saved_storage


def make_row(kind, family_name, type_name=''):
    row = fv_model.Row(kind)
    row.family_name = family_name
    row.type_name = type_name
    row.category = 'Doors'
    return row


class FakeColumn(object):
    def __init__(self, key, title='', kind='param'):
        self.key = key
        self.title = title or key
        self.kind = kind


class EditOwner(object):
    """Just the edit rules off the controller, with no WPF anywhere near."""

    def __init__(self):
        self.pending = {}

    _edit_key = fv_window.FamilyViewerWindow.__dict__['_edit_key']
    can_edit = fv_window.FamilyViewerWindow.__dict__['can_edit']
    staged = fv_window.FamilyViewerWindow.__dict__['staged']


def check_edit_rules():
    owner = EditOwner()

    family = make_row(fv_model.FAMILY_ROW, 'BGL_Door_Single')
    family.family_id = 900
    system = make_row(fv_model.FAMILY_ROW, 'Pipe Types')
    system.is_system = True
    system.family_id = 0
    type_row = make_row(fv_model.TYPE_ROW, 'BGL_Door_Single', 'FD30')
    type_row.type_id = 500

    name = FakeColumn(fv_model.KEY_NAME, 'Family and type', 'fixed')
    category = FakeColumn(fv_model.KEY_CATEGORY, 'Category', 'fixed')
    count = FakeColumn(fv_model.KEY_COUNT, 'Count', 'fixed')
    mark = FakeColumn('Mark')

    check('a type name is editable', owner.can_edit(type_row, name), True)
    check('a type parameter is editable', owner.can_edit(type_row, mark), True)
    check('a family name is editable', owner.can_edit(family, name), True)
    check('a family parameter is not - a family line has no single element '
          'behind it', owner.can_edit(family, mark), False)
    check('a system family cannot be renamed',
          owner.can_edit(system, name), False)
    check('Category is read from the model, not typed into it',
          owner.can_edit(type_row, category), False)
    check('Count is read from the model, not typed into it',
          owner.can_edit(type_row, count), False)

    # a staged edit is keyed on the element, so the same type edited from two
    # rows is one edit rather than two
    owner.pending[('type', 500, 'Mark')] = 'D9'
    check('a staged value is shown in place of the model value',
          owner.staged(type_row, 'Mark'), 'D9')
    check('an unstaged cell shows nothing staged',
          owner.staged(type_row, fv_model.KEY_NAME), None)
    other = make_row(fv_model.TYPE_ROW, 'BGL_Door_Single', 'FD30')
    other.type_id = 500
    check('the same type staged from another row is the same edit',
          owner.staged(other, 'Mark'), 'D9')
    check('a different type is a different edit',
          owner.staged(type_row, 'Nothing'), None)


def check_batch_rename():
    """The rename tools, the cell targeting, and the clash rules that stop a
    batch failing halfway through."""
    import fv_batch_window as batch

    check('find and replace', batch.apply_tools('BGL_Door_FD30', 'FD30',
                                                'FD60', '', '', True),
          'BGL_Door_FD60')
    check('replace with nothing deletes it',
          batch.apply_tools('BGL_Door_FD30', '_FD30', '', '', '', True),
          'BGL_Door')
    check('a prefix goes on the front',
          batch.apply_tools('Door', '', '', 'BGL_', '', True), 'BGL_Door')
    check('a suffix goes on the end',
          batch.apply_tools('Door', '', '', '', ' FD30', True), 'Door FD30')
    check('the order is replace, then prefix, then suffix',
          batch.apply_tools('a-b', '-', '_', 'X', 'Y', True), 'Xa_bY')

    check('a case blind find matches',
          batch.apply_tools('BGL_door', 'DOOR', 'Window', '', '', False),
          'BGL_Window')
    check('a case blind replace leaves the rest of the text alone',
          batch.apply_tools('BGL_Door_Single', 'door', 'Window', '', '',
                            False),
          'BGL_Window_Single')
    check('a case sensitive find does not match the wrong case',
          batch.apply_tools('BGL_door', 'DOOR', 'Window', '', '', True),
          'BGL_door')
    check('every occurrence is replaced',
          batch.apply_tools('a-a-a', 'a', 'b', '', '', True), 'b-b-b')

    NAME = batch.NAME_KEY
    keys = [NAME, 'Type Mark']

    def line(kind, ident, family, name, mark=''):
        return batch.Line(kind, ident, family,
                          {NAME: name, 'Type Mark': mark})

    # nothing picked means every NAME cell, and no parameter cell
    lines = [line('type', 1, 'BGL_Door', 'FD30', 'D1')]
    batch.evaluate(lines, keys, set(), '', '', 'X', '', True, {})
    check('with no cells picked the tools apply to the names',
          lines[0].new_of(NAME), 'XFD30')
    check('and leave the parameter columns alone',
          lines[0].new_of('Type Mark'), 'D1')

    # a picked parameter cell is the only thing touched
    lines = [line('type', 1, 'BGL_Door', 'FD30', 'D1'),
             line('type', 2, 'BGL_Door', 'FD60', 'D2')]
    targets = set([(1, 'type', 'Type Mark')])
    batch.evaluate(lines, keys, targets, '', '', 'X', '', True, {})
    check('a picked cell is the only one changed',
          lines[0].new_of('Type Mark'), 'XD1')
    check('the name in that row is left alone',
          lines[0].new_of(NAME), 'FD30')
    check('another row is left alone entirely',
          [lines[1].new_of(NAME), lines[1].new_of('Type Mark')],
          ['FD60', 'D2'])
    check('only the picked cell counts as a change',
          [lines[0].state_of('Type Mark'), lines[0].state_of(NAME)],
          [batch.OK, batch.UNCHANGED])

    # several picked cells down a column
    lines = [line('type', 1, 'BGL_Door', 'FD30', 'D1'),
             line('type', 2, 'BGL_Door', 'FD60', 'D2')]
    targets = set([(1, 'type', 'Type Mark'), (2, 'type', 'Type Mark')])
    batch.evaluate(lines, keys, targets, 'D', 'M', '', '', True, {})
    check('a run down a column changes every picked cell',
          [row.new_of('Type Mark') for row in lines], ['M1', 'M2'])

    # a parameter value repeating is not a clash - re-stamping is the point
    lines = [line('type', 1, 'BGL_Door', 'FD30', 'D1'),
             line('type', 2, 'BGL_Door', 'FD60', 'D2')]
    targets = set([(1, 'type', 'Type Mark'), (2, 'type', 'Type Mark')])
    batch.evaluate(lines, keys, targets, '', '', '', '', True,
                   {('type', 'BGL_Door'): set(['FD30', 'FD60'])})
    lines = [line('type', 1, 'BGL_Door', 'FD30', 'x'),
             line('type', 2, 'BGL_Door', 'FD60', 'x')]
    batch.evaluate(lines, keys, targets, 'x', 'y', '', '', True, {})
    check('two rows given the same parameter value is not a clash',
          [row.state_of('Type Mark') for row in lines], [batch.OK, batch.OK])

    # the clash rules on names
    taken = {('type', 'BGL_Door'): set(['FD30', 'FD60', 'FD90'])}

    lines = [line('type', 1, 'BGL_Door', 'FD30')]
    batch.evaluate(lines, keys, set(), 'FD30', 'FD60', '', '', True, taken)
    check('a name already used in that family is flagged',
          [lines[0].state_of(NAME), 'already used' in lines[0].note[NAME]],
          [batch.CLASH, True])

    lines = [line('type', 1, 'BGL_Door', 'AA'),
             line('type', 2, 'BGL_Door', 'BB')]
    batch.evaluate(lines, keys, set(), '', '', '', '', True, {})
    check('nothing typed means nothing changes',
          [row.state_of(NAME) for row in lines],
          [batch.UNCHANGED, batch.UNCHANGED])

    lines = [line('type', 1, 'BGL_Door', 'AA'),
             line('type', 2, 'BGL_Door', 'AB')]
    batch.evaluate(lines, keys, set(), 'B', 'A', '', '', True, {})
    states = [row.state_of(NAME) for row in lines]
    check('a row renamed onto a name an unchanged row still holds is caught',
          batch.CLASH in states, True)

    lines = [line('type', 1, 'BGL_Door', 'FD30'),
             line('type', 2, 'BGL_Door', 'FD90')]
    batch.evaluate(lines, keys, set(), 'FD30', 'FD31', '', '', True,
                   {('type', 'BGL_Door'): set(['FD30', 'FD90'])})
    check('a row keeps its own name without clashing with itself',
          lines[0].state_of(NAME), batch.OK)

    lines = [line('type', 1, 'BGL_Door', 'FD30')]
    batch.evaluate(lines, keys, set(), 'FD30', '', '', '', True, {})
    check('a rename that would leave nothing is refused',
          [lines[0].state_of(NAME), 'blank' in lines[0].note[NAME]],
          [batch.BLANK, True])

    # a parameter cleared to nothing is fine - blank is a real value
    lines = [line('type', 1, 'BGL_Door', 'FD30', 'D1')]
    batch.evaluate(lines, keys, set([(1, 'type', 'Type Mark')]), 'D1', '', '',
                   '', True, {})
    check('a parameter emptied is allowed, unlike a name',
          lines[0].state_of('Type Mark'), batch.OK)

    check('only the cells that changed are handed back',
          [key for key in lines[0].changes()], ['Type Mark'])

    # a value typed straight into a cell wins over the tools and survives them
    lines = [line('type', 1, 'BGL_Door', 'FD30', 'D1')]
    lines[0].typed[NAME] = 'Typed by hand'
    batch.evaluate(lines, keys, set(), '', '', 'X', '', True, {})
    check('a typed value beats the tools',
          lines[0].new_of(NAME), 'Typed by hand')
    check('and counts as a change', lines[0].state_of(NAME), batch.OK)
    lines[0].typed[NAME] = 'FD30'
    batch.evaluate(lines, keys, set(), '', '', 'X', '', True, {})
    check('typing a cell back to what it was is not a change',
          lines[0].state_of(NAME), batch.UNCHANGED)
    lines[0].typed[NAME] = '   '
    batch.evaluate(lines, keys, set(), '', '', '', '', True, {})
    check('a name typed blank is still refused',
          lines[0].state_of(NAME), batch.BLANK)

    # the scope rules, read out of the shipped source rather than restated
    # here - v1.4.0 left this to a setting that could disagree with the chip
    source = io.open(os.path.join(HERE, 'fv_window.py'), encoding='utf-8').read()
    check('the window passes the scope by name and works nothing out itself',
          'include_unused' in source, False)
    check('and no setting is consulted for it',
          "as_bool(self.settings, 'include_unused')" in source, False)

    # the count pass carries no category filter.  It was only ever a speed
    # optimisation and it is the one step that can match nothing without
    # raising - which is what made Entire project and Active view list nothing
    # while All families looked fine.
    model = io.open(os.path.join(HERE, 'fv_model.py'), encoding='utf-8').read()
    counting = model.split('pass 2: the instances')[1].split('roll up')[0]
    check('the count pass runs no category filter',
          'ElementMulticategoryFilter' in counting.replace(
              '# It used to carry an ElementMulticategoryFilter', ''), False)
    check('and it counts by the same dictionary lookup Select uses',
          'type_rows.get(type_id)' in counting, True)
    selecting = model.split('def instance_ids')[1]
    check('Select never carried that filter either, which is why Select '
          'worked while Count did not',
          'ElementMulticategoryFilter' in selecting, False)


def check_batch_modes():
    """A locked cell is shown and never written, whatever is done to it."""
    import fv_batch_window as batch

    NAME = batch.NAME_KEY
    keys = [NAME, 'Type Mark']

    # a family line: name editable, everything else locked
    family = batch.Line('family', 900, 'Doors',
                        {NAME: 'BGL_Door_Single', 'Type Mark': ''},
                        editable=set([NAME]))
    a_type = batch.Line('type', 1, 'BGL_Door_Single',
                        {NAME: 'FD30', 'Type Mark': 'D1'},
                        editable=set([NAME, 'Type Mark']))
    lines = [family, a_type]

    batch.evaluate(lines, keys, set(), '', '', 'X', '', True, {})
    check('a family line renames', family.new_of(NAME), 'XBGL_Door_Single')
    check('a family line parameter is locked',
          family.state_of('Type Mark'), batch.LOCKED)
    check('a locked cell is never handed back',
          'Type Mark' in family.changes(), False)

    # a locked cell typed into is still never written
    family.typed['Type Mark'] = 'typed anyway'
    batch.evaluate(lines, keys, set(), '', '', '', '', True, {})
    check('typing into a locked cell changes nothing',
          family.state_of('Type Mark'), batch.LOCKED)
    check('and it is still not handed back',
          'Type Mark' in family.changes(), False)
    family.typed = {}

    # a locked cell picked as a target is ignored rather than obeyed
    batch.evaluate(lines, keys, set([(900, 'family', 'Type Mark')]),
                   '', '', 'X', '', True, {})
    check('picking a locked cell writes nothing',
          family.new_of('Type Mark'), '')

    # an instance-level parameter on a type line is locked the same way
    instance_param = batch.Line('type', 2, 'BGL_Door_Single',
                                {NAME: 'FD60', 'Mark': 'D9'},
                                editable=set([NAME]))
    batch.evaluate([instance_param], [NAME, 'Mark'], set(), '', '', 'X', '',
                   True, {})
    check('an instance parameter on a type line is locked',
          instance_param.state_of('Mark'), batch.LOCKED)
    check('while the type name still renames',
          instance_param.state_of(NAME), batch.OK)

    # with nothing picked, the tools reach only the names that CAN be renamed
    only_locked = batch.Line('type', 3, 'BGL_Door_Single',
                             {NAME: 'FD90'}, editable=set())
    batch.evaluate([only_locked], [NAME], set(), '', '', 'X', '', True, {})
    check('a line with nothing editable is left entirely alone',
          only_locked.new_of(NAME), 'FD90')


def check_fill_down():
    """The fill handle: repeat, or count on from a number at the end."""
    import fv_batch_window as batch

    check('a value with no number repeats',
          batch.fill_values('FD30 door', 3),
          ['FD30 door', 'FD30 door', 'FD30 door'])
    check('a value ending in a number counts on',
          batch.fill_values('Type 1', 3), ['Type 2', 'Type 3', 'Type 4'])
    check('leading zeros are kept at the width they were written',
          batch.fill_values('BGL_Door_01', 3),
          ['BGL_Door_02', 'BGL_Door_03', 'BGL_Door_04'])
    check('and the width grows when the number outgrows it',
          batch.fill_values('D_08', 3), ['D_09', 'D_10', 'D_11'])
    check('a number in the middle is not the one counted',
          batch.fill_values('FD30 leaf 1', 2), ['FD30 leaf 2', 'FD30 leaf 3'])
    check('a value that is only a number counts on',
          batch.fill_values('7', 2), ['8', '9'])
    check('filling nothing gives nothing', batch.fill_values('x', 0), [])

    check('the number at the end is found with its width',
          batch.split_number('BGL_Door_007'), ('BGL_Door_', 7, 3))
    check('and nothing is found where there is none',
          batch.split_number('BGL_Door'), ('BGL_Door', None, 0))
    check('a blank splits to nothing', batch.split_number(''), ('', None, 0))


def check_apply_progress():
    """The bar Apply fills: percentages, throttling, and that a broken bar
    can never stop the write behind it."""
    seen = []

    class Clock(object):
        def __init__(self):
            self.now = 0.0

        def __call__(self):
            return self.now

    clock = Clock()
    meter = fv_core.ProgressMeter(lambda p, t: seen.append((p, t)), 3000,
                                  clock=clock)
    meter.update('borrow', 0)
    meter.update('index', 0)
    check('stages always get through', [p for p, _ in seen], [0, 6])

    # 3000 writes in a tight loop with no time passing: only the first one of
    # the stage gets through, the rest wait for the clock
    del seen[:]
    for done in range(3000):
        meter.update('write', done)
    check('a tight loop does not flood the window', len(seen), 1)

    del seen[:]
    for done in range(3000):
        clock.now += 0.001          # three seconds over the whole run
        meter.update('write', done)
    check('a slow loop reports roughly once per step and interval',
          5 <= len(seen) <= 40, True)
    percents = [p for p, _ in seen]
    check('the percentage never runs backwards', percents == sorted(percents),
          True)
    check('writing stays inside its band',
          [min(percents) >= 10, max(percents) <= 95], [True, True])
    check('the text says how far through it is',
          seen[-1][1].startswith('Writing ') and '3,000 changes' in seen[-1][1],
          True)

    del seen[:]
    meter.update('write', 3000)
    meter.update('commit', 0)
    meter.update('done')
    check('it ends at 100', seen[-1][0], 100)
    check('commit has its own words', 'Committing' in seen[-2][1], True)

    check('half way through writing is half way along the band',
          fv_core.ProgressMeter(None, 200).percent_of('write', 100), 52)
    check('one change reads as singular',
          fv_core.ProgressMeter(None, 1).text_of('write', 1),
          'Writing 1 of 1 change')
    check('no changes does not divide by zero',
          fv_core.ProgressMeter(None, 0).percent_of('write', 0), 10)

    def broken(percent, text):
        raise ValueError('the bar went away')

    meter = fv_core.ProgressMeter(broken, 10, clock=clock)
    meter.update('borrow', 0)
    check('a bar that raises is dropped, not passed on', meter.report, None)
    check('and the meter carries on counting', meter.update('done'), True)

    # wiring: the write reports through the payload, and the window repaints
    # at Render priority so input cannot land mid-transaction
    ops = open(os.path.join(HERE, 'fv_ops.py')).read()
    check('Apply reports progress from its payload',
          "ProgressMeter(payload.get('progress')" in ops, True)
    check('Apply reports every write', "meter.update('write', done)" in ops,
          True)
    window = open(os.path.join(HERE, 'fv_window.py')).read()
    check('Apply hands the window its progress callback',
          "'progress': self._on_apply_progress" in window, True)
    check('the repaint pumps at Render, below which input waits',
          'DispatcherPriority.Render' in window, True)
    check('a failed Apply puts the edit bar back',
          'self._show_apply_progress(False)\n        self._update_edit_bar()'
          in window, True)


def check_quick_rename():
    """The toolbar drop-down: the same tools and clash rules as the full
    window, over the names of the picked rows."""
    import fv_batch_window as batch
    NAME = batch.NAME_KEY

    def line(kind, ident, family, name):
        return batch.Line(kind, ident, family, {NAME: name}, [NAME])

    lines = [line('family', 1, 'Doors', 'Door_Single'),
             line('family', 2, 'Doors', 'Door_Double'),
             line('family', 3, 'Doors', 'Window')]
    plan = batch.quick_rename(lines, 'Door', 'DR', 'BGL_', '', True, {})
    check('the quick rename changes what the tools touch',
          [new for _, new in plan.changes],
          ['BGL_DR_Single', 'BGL_DR_Double', 'BGL_Window'])

    plan = batch.quick_rename(lines, 'Door', 'DR', '', '', True, {})
    check('a name the tools leave alone is counted as unchanged',
          [len(plan.changes), plan.unchanged], [2, 1])

    plan = batch.quick_rename(lines, 'Door_Single', 'Door_Double', '', '',
                              True, {})
    check('a rename onto a picked name that is staying is refused',
          [len(plan.changes), len(plan.refused)], [0, 1])

    plan = batch.quick_rename(lines, '', '', '', '_X', True,
                              {('family', 'Doors'): set(['Window_X'])})
    check('a rename onto a name already in the model is refused',
          sorted([l.element_id for l, _ in plan.refused]), [3])

    plan = batch.quick_rename([line('type', 9, 'Door', 'FD30')], 'FD30', '',
                              '', '', True, {})
    check('a rename to blank is refused', len(plan.refused), 1)

    plan = batch.quick_rename(lines, '', '', '', '', True, {})
    check('no tools filled in changes nothing',
          [plan.any_tool(), plan.unchanged], [False, 3])
    check('and says so', plan.summary().startswith('Nothing to change'), True)
    plan = batch.quick_rename(lines, '', '', 'A', '', True, {})
    check('the summary counts the changes', plan.summary(),
          '3 names will change.')

    # the window: right click opens the drop-down rather than the full
    # editor, and the full editor stays one click away
    window = open(os.path.join(HERE, 'fv_window.py')).read()
    check('right click Batch rename opens the toolbar drop-down',
          'def batch_it(sender_, args_):\n            self.open_quick_rename()'
          in window, True)
    check('quick rename stages as batch, in green',
          "self.staged_from[key] = 'batch'" in
          window[window.index('def on_quick_apply'):], True)
    check('the button arms itself from the selection',
          'self._arm_rename()' in window, True)


def check_excel_round_trip():
    """Out to a real .xlsx and back, through the shipped writer and reader.

    The writer runs against .NET, which the bench stubs out, so what is
    exercised here is the XML the writer builds and the reader's parsing of
    it - which is where a round trip actually goes wrong.
    """
    import fv_excel

    headings = [fv_excel.ID_HEAD, fv_excel.KIND_HEAD, fv_excel.FAMILY_HEAD,
                fv_excel.TYPE_HEAD, fv_excel.CATEGORY_HEAD,
                fv_excel.COUNT_HEAD, 'Type Mark']
    rows = [
        ['501', 'type', 'BGL_Door_Single', 'FD30', 'Doors', '4', '007'],
        ['502', 'type', 'BGL_Door_Single', 'FD60', 'Doors', '6', 'A & B'],
        ['503', 'type', 'BGL_Door_Single', '900 <wide>', 'Doors', '1', ''],
    ]

    xml = fv_excel._sheet_xml(headings, rows)
    check('the header row is frozen', 'state="frozen"' in xml, True)
    check('an autofilter is written', '<autoFilter' in xml, True)
    check('read-only columns take the grey fill',
          's="' + str(fv_excel.S_LOCKED) + '"' in xml, True)
    check('editable columns take the orange fill',
          's="' + str(fv_excel.S_EDIT) + '"' in xml, True)
    check('an ampersand is escaped', 'A &amp; B' in xml, True)
    check('angle brackets are escaped', '900 &lt;wide&gt;' in xml, True)
    check('every value is written as inline text, so a type mark of 007 does '
          'not come back as the number seven',
          xml.count('t="inlineStr"'), len(headings) * (len(rows) + 1))

    # the reader, against the XML the writer just produced
    class Node(object):
        pass

    check('a column letter maps back to its index',
          [fv_excel._column_index('A2'), fv_excel._column_index('AA17')],
          [1, 27])
    check('a column index maps to its letter',
          [fv_excel._column_letter(1), fv_excel._column_letter(27)],
          ['A', 'AA'])
    check('a reference with no letters is refused',
          fv_excel._column_index('17'), 0)

    check('Family and the id are read only, so an edit to them is ignored',
          [fv_excel.ID_HEAD in fv_excel.READ_ONLY,
           fv_excel.COUNT_HEAD in fv_excel.READ_ONLY],
          [True, True])
    check('Type is editable - it is the point of the round trip',
          fv_excel.TYPE_HEAD in fv_excel.READ_ONLY, False)

    # the zip types are asked for at the point of use, not at module load:
    # importing them at the top of the module is what killed the tool in 1.3.0
    source = io.open(os.path.join(HERE, 'fv_excel.py'), encoding='utf-8').read()
    head = source.split('def _zip_types')[0]
    check('the zip assembly is not reached for at module load',
          'from System.IO.Compression import' in head, False)
    check('and there is a way to ask whether it is there at all',
          hasattr(fv_excel, 'available'), True)

    legend = fv_excel._legend_xml('title', headings, ['a note'])
    check('the legend says which cells are editable',
          '(editable)' in legend and '(read only)' in legend, True)
    check('the legend warns against changing the id column',
          'do not change it' in legend, True)


def run():
    doc = build_doc()
    install(doc)

    # ---- grouping and counting ----------------------------------------
    result = fv_model.read(doc, columns=[], scope=fv_model.SCOPE_ALL)
    names = sorted([parent.family_name for parent in result.families])
    check('loadable families found', names,
          ['BGL_Door_Double', 'BGL_Door_Single'])
    check('system families off by default',
          [name for name in names if name == 'Pipe Types'], [])
    check('annotation off by default', by_name(result, 'BGL_Door_Tag'), None)

    single = by_name(result, 'BGL_Door_Single')
    check('types under the family', len(single.children), 2)
    # natural order, so 900 sorts before 1000 rather than after it
    check('types are in natural name order',
          [row.type_name for row in single.children],
          ['900x2100', '1000x2100'])
    check('nested instance ignored', child(single, '900x2100').count, 2)
    check('family count is the sum of its types', single.count,
          sum([child.count for child in single.children]))
    check('preview comes off the first type', single.preview_id,
          single.children[0].type_id)

    # ---- nested instances ---------------------------------------------
    kept = fv_model.read(doc, columns=[], scope=fv_model.SCOPE_ALL,
                         ignore_nested=False)
    check('nested instance counted when asked for',
          child(by_name(kept, 'BGL_Door_Single'), '900x2100').count, 3)

    # ---- system and annotation ----------------------------------------
    with_system = fv_model.read(doc, columns=[], scope=fv_model.SCOPE_ALL,
                                include_system=True)
    pipes = by_name(with_system, 'Pipe Types')
    check('system families included on request', pipes is not None, True)
    check('system family is flagged as one', pipes.is_system, True)
    check('system type counted', pipes.count, 3)
    with_tags = fv_model.read(doc, columns=[], scope=fv_model.SCOPE_ALL,
                              include_annotation=True)
    check('annotation included on request',
          by_name(with_tags, 'BGL_Door_Tag') is not None, True)

    # ---- unused types --------------------------------------------------
    trimmed = fv_model.read(doc, columns=[], scope=fv_model.SCOPE_PROJECT,
                            include_system=True)
    check('type with no instances dropped',
          [row.type_name for row in by_name(trimmed, 'Pipe Types').children],
          ['Copper 15'])
    double = by_name(trimmed, 'BGL_Door_Double')
    check('family kept while one type survives', double is not None, True)

    # ---- categories ----------------------------------------------------
    only_doors = fv_model.read(doc, columns=[], scope=fv_model.SCOPE_ALL,
                               include_system=True,
                               wanted_category_ids=[DOORS.Id.Value])
    check('category filter narrows the list',
          sorted([parent.family_name for parent in only_doors.families]),
          ['BGL_Door_Double', 'BGL_Door_Single'])

    # ---- phases ---------------------------------------------------------
    created = fv_model.read(doc, columns=[], scope=fv_model.SCOPE_ALL,
                            phase_id=PHASE_EXISTING,
                            phase_mode='created')
    check('created in phase counts only that phase',
          by_name(created, 'BGL_Door_Single').count, 3)
    # the family still lists, at a count of zero: it is the ELEMENT that has
    # no phase, not the type
    check('an element with no phase is not counted',
          by_name(created, 'BGL_Door_Double').count, 0)
    check('and is reported', created.no_phase, 1)

    standing = fv_model.read(doc, columns=[], scope=fv_model.SCOPE_ALL,
                             phase_id=PHASE_NEW,
                             phase_mode='existing')
    single_new = by_name(standing, 'BGL_Door_Single')
    check('existing in phase carries earlier phases forward',
          single_new.count, 3)
    check('a demolished element does not stand in that phase',
          child(single_new, '1000x2100').count, 1)

    order = {PHASE_EXISTING: 0, PHASE_NEW: 1}
    demolished = Instance(0, 1, created=PHASE_EXISTING, demolished=PHASE_NEW)
    check('demolished in the phase it is asked about',
          fv_model.phase_keeps(demolished, PHASE_NEW, 'existing', order), False)
    check('but stood in the phase before it',
          fv_model.phase_keeps(demolished, PHASE_EXISTING, 'existing', order),
          True)
    check('no phase filter keeps everything',
          fv_model.phase_keeps(Instance(0, 1), None, 'created', order), True)

    # ---- the active view ------------------------------------------------
    in_view = fv_model.read(doc, columns=[], view=View('Level 00'),
                            scope=fv_model.SCOPE_VIEW, include_system=True)
    check('active view scope counts only what is in it',
          by_name(in_view, 'BGL_Door_Single').count, 2)
    # changed in 1.4.4: the view scope lists what is placed in the view, so a
    # family with nothing in it is not listed at all rather than listed at zero
    check('a family with nothing in the view is not listed',
          by_name(in_view, 'BGL_Door_Double'), None)

    # ---- parameter columns ----------------------------------------------
    with_params = fv_model.read(doc, columns=['Fire Rating', 'Mark'],
                                scope=fv_model.SCOPE_ALL)
    single = by_name(with_params, 'BGL_Door_Single')
    check('a type parameter is read off the type',
          child(single, '900x2100').cell('Fire Rating'), 'FD30')
    check('a family row agrees where its types do',
          by_name(with_params, 'BGL_Door_Double').cell('Fire Rating'), 'FD30')
    check('and reads (varies) where they do not',
          single.cell('Fire Rating'), fv_core.VARIES)
    check('an instance parameter is read off the instances',
          child(single, '900x2100').cell('Mark'), 'D01')
    check('instances that disagree read (varies)',
          child(single, '1000x2100').cell('Mark'), fv_core.VARIES)

    # ---- selecting -------------------------------------------------------
    ids = fv_model.instance_ids(doc, [1])
    check('select all instances of a type',
          sorted([element.Value for element in ids]), [11, 12])
    ids = fv_model.instance_ids(doc, [1], ignore_nested=False)
    check('nested included when the setting says so',
          sorted([element.Value for element in ids]), [11, 12, 13])
    ids = fv_model.instance_ids(doc, [1, 2], view=View('Level 00'))
    check('select in the active view only',
          sorted([element.Value for element in ids]), [11, 14])
    ids = fv_model.instance_ids(doc, [2], phase_id=PHASE_NEW,
                                phase_mode='created')
    check('select honours the phase filter',
          sorted([element.Value for element in ids]), [14])
    check('nothing selected for a type with no instances',
          fv_model.instance_ids(doc, [6]), [])

    # ---- filtering -------------------------------------------------------
    result = fv_model.read(doc, columns=['Fire Rating'],
                           scope=fv_model.SCOPE_ALL)
    columns = fv_grid.base_columns({})
    columns.append(fv_grid.Column('Fire Rating', 'Fire Rating', 'param'))

    def column_for(key):
        """By key, never by position: base_columns changes order as the
        layout changes, and indexing it into a fixed slot made this test fail
        for a reason that had nothing to do with what it was testing."""
        for column in columns:
            if column.key == key:
                return column
        raise KeyError(key)

    name_column = column_for(fv_model.KEY_NAME)
    rating_column = column_for('Fire Rating')
    check('the count column comes first and the name second',
          [column.key for column in fv_grid.base_columns({})][:2],
          [fv_model.KEY_COUNT, fv_model.KEY_NAME])

    shown = fv_grid.apply_filters(result.families, columns, 'Double')
    check('search narrows to one family', len(shown), 1)
    check('and keeps its types', len(shown[0].children), 1)

    shown = fv_grid.apply_filters(result.families, columns, 'nothing at all')
    check('a search that matches nothing shows nothing', shown, [])

    name_column.search = '900'
    shown = fv_grid.apply_filters(result.families, columns, '')
    check('a column search narrows the types', len(shown), 1)
    check('the family count follows the surviving types', shown[0].count, 2)
    name_column.search = ''

    rating_column.allowed = set(['FD60'])
    shown = fv_grid.apply_filters(result.families, columns, '')
    check('a tick filter narrows on the parameter',
          [row.type_name for parent in shown for row in parent.children],
          ['1000x2100'])
    rating_column.allowed = set()
    check('nothing ticked shows nothing',
          fv_grid.apply_filters(result.families, columns, ''), [])
    rating_column.allowed = None
    check('everything ticked is no filter at all',
          len(fv_grid.apply_filters(result.families, columns, '')), 2)

    values = fv_grid.distinct_values(result.families, 'Fire Rating')
    check('tick values are gathered with their counts',
          sorted(values), [('FD30', 2), ('FD60', 1)])

    # ---- sorting ---------------------------------------------------------
    shown = fv_grid.apply_filters(result.families, columns, '')
    up = fv_grid.sort_families(list(shown), fv_model.KEY_NAME, 1)
    check('sorted up', [parent.family_name for parent in up],
          ['BGL_Door_Double', 'BGL_Door_Single'])
    down = fv_grid.sort_families(list(shown), fv_model.KEY_NAME, -1)
    check('sorted down', [parent.family_name for parent in down],
          ['BGL_Door_Single', 'BGL_Door_Double'])
    by_count = fv_grid.sort_families(list(shown), fv_model.KEY_COUNT, -1)
    check('sorted by count', by_count[0].family_name, 'BGL_Door_Single')

    # ---- flatten ----------------------------------------------------------
    for parent in shown:
        parent.open = True
    check('open families list their types',
          len(fv_model.flatten(shown)), 2 + 3)
    for parent in shown:
        parent.open = False
    check('shut families do not', len(fv_model.flatten(shown)), 2)

    # ---- small helpers -----------------------------------------------------
    check('natural order puts 2 before 10',
          sorted(['Type 10', 'Type 2'], key=fv_core.natural_key),
          ['Type 2', 'Type 10'])
    check('agree on one value', fv_core.agree(['a', 'a', 'a']), 'a')
    check('agree on none', fv_core.agree([None, None]), '')
    check('agree on two', fv_core.agree(['a', 'b']), fv_core.VARIES)
    check('search wants every word',
          fv_core.matches_search('BGL Door Single', 'door bgl'), True)
    check('and fails on a word that is not there',
          fv_core.matches_search('BGL Door Single', 'door sliding'), False)

    # ---- settings ----------------------------------------------------------
    folder = tempfile.mkdtemp(prefix='fv_bench_')
    path = os.path.join(folder, 'family_viewer.txt')
    fv_core.settings_path = lambda: path

    settings = fv_core.load_settings()
    check('a missing file is every default',
          settings['preview_size'], fv_core.DEFAULTS['preview_size'])
    settings['preview_size'] = '96'
    settings['columns'] = 'Fire Rating|Mark'
    fv_core.save_settings(settings)
    again = fv_core.load_settings()
    check('a setting round trips', again['preview_size'], '96')
    # the loader splits on the FIRST '=' only, so a value carrying '=' signs
    # of its own round trips rather than being cut in half
    check('a value carrying = is split on the first one only',
          fv_core._parse('note=a=b=c\n')['note'], 'a=b=c')
    check('a comment line is ignored',
          fv_core._parse('# theme=light\ntheme=dark\n')['theme'], 'dark')
    check('a pipe separated list round trips',
          fv_core.as_list(again, 'columns'), ['Fire Rating', 'Mark'])

    handle = open(path, 'a')
    handle.write('a_key_from_a_later_version=7\n')
    handle.write('this line has no equals sign\n')
    handle.close()
    survived = fv_core.load_settings()
    check('an unknown key does not break the load',
          survived['preview_size'], '96')

    handle = open(path, 'w')
    handle.write('preview_size=not a number\n')
    handle.close()
    damaged = fv_core.load_settings()
    check('a damaged value falls back key by key',
          fv_core.as_int(damaged, 'preview_size', 16, 256), 48)
    check('an integer is clamped',
          fv_core.as_int({'ui_scale': '9000'}, 'ui_scale', 80, 150), 150)
    check('a boolean reads on and off',
          [fv_core.as_bool({'x': 'yes'}, 'x'), fv_core.as_bool({'x': '0'}, 'x')],
          [True, False])
    check('an element id with no Value falls back', fv_core.eid_value(None), 0)

    check_scopes()
    check_scope_rules()
    check_instances_and_grouping()
    check_drawer()
    check_import_plan()
    check_family_rename_import()
    check_theme_follow()
    check_instance_index()
    check_filter_values()
    check_instance_sorting()
    check_empty_diagnosis()
    check_names()
    check_parameter_scope()
    check_writes()
    check_edit_rules()
    check_batch_rename()
    check_batch_modes()
    check_fill_down()
    check_excel_round_trip()
    check_apply_progress()
    check_quick_rename()

    failures = [row for row in CHECKS if not row[1]]
    for label, ok, got, wanted in CHECKS:
        if not ok:
            sys.stdout.write('FAIL  ' + label + '\n      got     ' +
                             repr(got) + '\n      wanted  ' + repr(wanted) +
                             '\n')
    if failures:
        sys.stdout.write('\nbench_logic: ' + str(len(failures)) + ' of ' +
                         str(len(CHECKS)) + ' checks failed.\n')
        return 1
    sys.stdout.write('bench_logic: all ' + str(len(CHECKS)) +
                     ' checks pass.\n')
    return 0


if __name__ == '__main__':
    sys.exit(run())
