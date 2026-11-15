# -*- coding: utf-8 -*-
"""Bench check for Place BWIC Horizontal.

Run it with plain Python before shipping. It cannot load the Revit API, so it
checks the things that go wrong silently:

    * script.py parses
    * the XAML is well formed
    * every x:Name in the XAML is used in the script, AND every self.<name>
      the script touches exists in the XAML  -- the second direction is the
      one that matters: an edit that fails to apply leaves the script calling
      a control that was never added, and nothing complains until Revit
    * every Click / MouseLeftButtonDown handler has a matching def
    * every StaticResource key is defined in the same file
    * no f-strings, no print statements, no bare .IntegerValue outside the
      guarded eid_value helper
"""

import ast
import io
import importlib
import os.path as op
import re
import sys
import xml.dom.minidom

HERE = op.dirname(op.abspath(__file__))
SCRIPTS = [op.join(HERE, 'script.py'), op.join(HERE, 'bwic_core.py'),
           op.join(HERE, 'bwic_drawer.py'), op.join(HERE, 'bwic_global.py'),
           op.join(HERE, 'bwic_families.py'), op.join(HERE, 'bwic_prompt.py')]
# each XAML and the class in script.py that loads it
PAIRS = [('ui.xaml', 'BWICWindow'), ('settings.xaml', 'SettingsWindow'),
         ('results.xaml', 'ResultsWindow'), ('prompt.xaml', 'FloatingPrompt'),
         ('family_settings.xaml', 'FamilySettingsWindow')]
# windows the shrink drawer rule does not apply to, and why
DRAWER_EXEMPT = {
    'FloatingPrompt': 'a click-through overlay with no header and nothing '
                  'to click; it closes itself and never covers Revit',
}

# controls the script may reference without them being in the XAML
EXEMPT_ATTRS = set([
    'settings', 'handler', 'ext_event', 'workset_names', 'Topmost',
    'Focusable', 'Resources', 'Content', 'Close', 'Activate', 'DragMove',
    'Show', 'ShowDialog', 'IsEnabled', 'Title', 'Left', 'Top', 'Width',
    'Height', 'MinWidth', 'MinHeight', 'MaxHeight', 'MaxWidth',
    'Owner', 'WindowState', 'Visibility', 'SizeToContent',
    'SourceInitialized', 'ContentRendered', 'PreviewKeyDown',
    'Closed', 'Dispatcher', 'FindResource', 'Hide', 'IsVisible', 'Topmost', 'Focusable',
    'ActualWidth', 'ActualHeight', 'WindowStartupLocation',
])

# names defined inside control templates rather than as real controls
TEMPLATE_NAMES = set(['bd', 'tbd', 'tab', 'body', 'chev', 'hb', 'seg'])

# named purely so the XAML can refer to them; nothing in the
# script needs to touch them
XAML_ONLY = set(['tabs', 'settings_tabs', 'settings_btn'])


def fail(problems, message):
    problems.append(message)


def class_body(source, name):
    """The source of one class, so controls are checked against their window."""
    marker = 'class {}('.format(name)
    if marker not in source:
        return ''
    start = source.index(marker)
    rest = source[start + len(marker):]
    nxt = rest.find('\nclass ')
    return rest if nxt < 0 else rest[:nxt]


def main():
    problems = []
    sources = {}

    for path in SCRIPTS:
        if not op.isfile(path):
            fail(problems, '{} is missing'.format(op.basename(path)))
            continue
        text = io.open(path, encoding='utf-8').read()
        sources[op.basename(path)] = text
        try:
            ast.parse(text)
        except SyntaxError as err:
            print('FAIL  {} does not parse: {}'.format(op.basename(path), err))
            return 1

    script_src = sources.get('script.py', '')
    all_src = '\n'.join(sources.values())

    total_names = total_handlers = total_keys = 0

    for xaml_name, class_name in PAIRS:
        path = op.join(HERE, xaml_name)
        if not op.isfile(path):
            fail(problems, '{} is missing'.format(xaml_name))
            continue
        markup = io.open(path, encoding='utf-8').read()

        try:
            xml.dom.minidom.parseString(markup.encode('utf-8'))
        except Exception as err:
            fail(problems, '{} is not well formed: {}'.format(xaml_name, err))
            continue

        body = class_body(script_src, class_name)
        if not body:
            fail(problems, 'class {} for {} is not in script.py'.format(
                class_name, xaml_name))
            continue

        names = set(re.findall(r'x:Name="(\w+)"', markup)) - TEMPLATE_NAMES
        total_names += len(names)

        # xaml -> script
        for name in sorted(names - XAML_ONLY):
            if 'self.' + name not in body:
                fail(problems, '{}: control "{}" is in the XAML but never '
                               'used in {}'.format(xaml_name, name, class_name))

        # script -> xaml, the direction that catches an edit that did not apply
        used = set(re.findall(r'self\.(\w+)', body))
        defined = set(re.findall(r'self\.(\w+)\s*=', body))
        defined |= set(re.findall(r'def (\w+)\(', body))
        for attr in sorted(used - defined - EXEMPT_ATTRS - names):
            fail(problems, '{}: {} uses self.{} but no control of that name '
                           'is in the XAML'.format(xaml_name, class_name, attr))

        handlers = set(re.findall(
            r'(?<![\w.])(?:Click|MouseLeftButtonDown|MouseDoubleClick|DragDelta)="(\w+)"',
            markup))
        total_handlers += len(handlers)
        for handler in sorted(handlers):
            if 'def {}('.format(handler) not in body:
                fail(problems, '{}: handler "{}" is wired in the XAML but has '
                               'no def in {}'.format(xaml_name, handler,
                                                     class_name))

        keys = set(re.findall(r'x:Key="(\w+)"', markup))
        total_keys += len(keys)
        for key in sorted(set(re.findall(r'StaticResource (\w+)', markup))):
            if key not in keys:
                fail(problems, '{}: StaticResource "{}" is not defined'.format(
                    xaml_name, key))

    # --- names the script reaches for in its own modules -------------------
    # Every module script.py imports under an alias is checked the same way,
    # so a misspelt gp.X or drawer.X fails here rather than in Revit.
    aliases = dict(re.findall(r'^\s*import (bwic_\w+) as (\w+)', script_src,
                              re.M))
    for module, alias in sorted(aliases.items()):
        mod_src = sources.get(module + '.py', '')
        if not mod_src:
            fail(problems, 'script.py imports {} but the bench does not '
                           'read it'.format(module))
            continue
        names = set(re.findall(r'^def (\w+)', mod_src, re.M))
        names |= set(re.findall(r'^class (\w+)', mod_src, re.M))
        names |= set(re.findall(r'^(\w+) *=', mod_src, re.M))
        names.add('__version__')
        for attr in sorted(set(re.findall(r'(?<![\w.])' + alias + r'\.(\w+)',
                                          script_src))):
            if attr not in names:
                fail(problems, 'script.py uses {}.{} which {}.py does not '
                               'define'.format(alias, attr, module))
    core_src = sources.get('bwic_core.py', '')

    # --- names a function reaches for that do not exist -------------------
    # This is the rule that would have caught 'clearance_ft is not defined':
    # an edit removed the lines that assigned it while leaving the uses in
    # place, and nothing complained until the tool ran in Revit.
    import symtable
    for name, text in sorted(sources.items()):
        try:
            table = symtable.symtable(text, name, 'exec')
        except SyntaxError:
            continue
        module_names = set(table.get_identifiers())
        for child in table.get_children():
            if child.get_type() == 'class':
                module_names |= set(child.get_identifiers())
        builtins = set(dir(__builtins__)) if isinstance(__builtins__, type(re)) \
            else set(__builtins__.keys())
        builtins |= set(['True', 'False', 'None', 'self', '__file__',
                         '__name__', 'unicode', 'basestring', 'xrange',
                         'long', 'reduce', 'raw_input'])

        def walk(scope):
            for child in scope.get_children():
                walk(child)
            if scope.get_type() != 'function':
                return
            for symbol in scope.get_symbols():
                if not symbol.is_referenced():
                    continue
                # assigned here, passed in, or captured from an enclosing
                # function -- all fine
                # a function local import assigns the name too, though
                # symtable reports is_assigned() False for it
                imported = getattr(symbol, 'is_imported', None)
                if imported is not None and imported():
                    continue
                if symbol.is_assigned() or symbol.is_parameter() \
                        or symbol.is_free():
                    continue
                label = symbol.get_name()
                # what is left is a plain global lookup, so the module has to
                # define it. get_identifiers() is no use for this: it lists
                # names merely REFERENCED in a scope as well as assigned ones.
                if label in module_names or label in builtins:
                    continue
                fail(problems, '{}: {}() uses "{}" which is never assigned '
                               'anywhere it can see'.format(
                                   name, scope.get_name(), label))

        walk(table)

    # --- a local used before it is assigned --------------------------------
    # The symtable rule above only catches a name assigned NOWHERE. This one
    # catches a name assigned LATER in the same function than it is first
    # read, which Python treats as a local and rejects at run time with
    # "referenced before assignment" -- as happened to 'levels' in the wall
    # loop after a block was copied over from the slab loop.
    NESTED = (ast.FunctionDef, ast.Lambda, ast.ListComp, ast.SetComp,
              ast.DictComp, ast.GeneratorExp)
    if hasattr(ast, 'AsyncFunctionDef'):
        NESTED = NESTED + (ast.AsyncFunctionDef,)

    def own_scope(node):
        """Nodes belonging to this function, not to anything nested in it.

        A comprehension has its own scope and lists its target AFTER the
        expression that reads it, and a nested def has its own parameters --
        both look like use-before-assignment from the outside.
        """
        for field, value in ast.iter_fields(node):
            items = value if isinstance(value, list) else [value]
            for item in items:
                if not isinstance(item, ast.AST):
                    continue
                if isinstance(item, NESTED):
                    continue
                yield item
                for child in own_scope(item):
                    yield child

    for name, text in sorted(sources.items()):
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue

            declared = set()
            for inner in own_scope(node):
                if isinstance(inner, ast.Global):
                    declared |= set(inner.names)
                elif hasattr(ast, 'Nonlocal') and isinstance(inner, ast.Nonlocal):
                    declared |= set(inner.names)

            params = set()
            args = node.args
            for group in ('args', 'posonlyargs', 'kwonlyargs'):
                for arg in getattr(args, group, None) or []:
                    params.add(getattr(arg, 'arg', getattr(arg, 'id', None)))
            for extra in (args.vararg, args.kwarg):
                if extra is not None:
                    params.add(getattr(extra, 'arg', extra))

            first_store, first_load = {}, {}
            for inner in own_scope(node):
                if not isinstance(inner, ast.Name):
                    continue
                table = first_store if isinstance(inner.ctx, ast.Store) \
                    else first_load
                if inner.id not in table or inner.lineno < table[inner.id]:
                    table[inner.id] = inner.lineno

            for label, store_line in sorted(first_store.items()):
                if label in params or label in declared:
                    continue
                load_line = first_load.get(label)
                if load_line is not None and load_line < store_line:
                    fail(problems, '{}: {}() reads "{}" on line {} but only '
                                   'assigns it on line {}'.format(
                                       name, node.name, label,
                                       load_line, store_line))

    # --- a click handler nothing calls ------------------------------------
    # The reverse of the XAML check: a *_click method that no Click= in its
    # window's XAML names, and that the class never wires up in code, is a
    # button that silently does nothing.
    for xaml_name, class_name in PAIRS:
        xaml_text = io.open(op.join(HERE, xaml_name), encoding='utf-8').read()
        body = class_body(script_src, class_name)
        wired = set(re.findall(r'Click="(\w+)"', xaml_text))
        for handler in sorted(set(re.findall(r'def (\w+_click)\(self', body))):
            if handler in wired:
                continue
            if re.search(r'\+= *self\.' + handler + r'\b', body) \
                    or re.search(r'self\.' + handler + r'\(', body):
                continue
            fail(problems, '{}.{} is never wired to a button in {}'.format(
                class_name, handler, xaml_name))

    # --- shrink to the taskbar ---------------------------------------------
    # The RevoBIM standard: every window carries the drawer. These fail if a
    # window is built without one, if a shrink button is drawn but not wired,
    # or if the slide never lets go of Top and Height -- which leaves a window
    # that can never be moved or resized again, with nothing raised to say so.
    script_src = sources.get('script.py', '')
    drawer_src = sources.get('bwic_drawer.py', '')
    for xaml_name, class_name in PAIRS:
        if class_name in DRAWER_EXEMPT:
            continue
        xaml_text = io.open(op.join(HERE, xaml_name), encoding='utf-8').read()
        body = class_body(script_src, class_name)
        if 'drawer.Drawer(' not in body:
            fail(problems, '{} is built without a drawer'.format(class_name))
        if 'x:Name="shrink_btn"' not in xaml_text:
            fail(problems, '{} has no shrink button'.format(xaml_name))
        elif not re.search(r'x:Name="shrink_btn"[^>]*Click="shrink_click"',
                           xaml_text, re.S):
            fail(problems, '{}: the shrink button is drawn but not wired'
                           .format(xaml_name))
        shrink = re.search(r'def shrink_click\(self[^)]*\):(.*?)(?:\n    @|\n    def |\Z)',
                           body, re.S)
        if shrink is None or 'self.drawer.toggle()' not in shrink.group(1):
            fail(problems, '{}.shrink_click does not toggle the drawer'
                           .format(class_name))
        drag = re.search(r'def drag_window\(self[^)]*\):(.*?)(?:\n    @|\n    def |\Z)',
                         body, re.S)
        if drag is None or 'header_down' not in drag.group(1):
            fail(problems, '{}: a double click on the parked bar would not '
                           'reopen it'.format(class_name))
        if 'self.PreviewKeyDown += self.key_down' not in body:
            fail(problems, '{}: Esc and Enter would not reopen a parked window'
                           .format(class_name))
        # the drawer collapses the header's siblings, so the header has to be
        # a direct child of the layout grid
        header = re.search(r'<(\w+)\s+x:Name="header_pnl"', xaml_text)
        if header is None:
            fail(problems, '{} has no header_pnl'.format(xaml_name))
        else:
            before = xaml_text[:header.start()]
            opened = re.findall(r'<(/?)(Grid|Border|StackPanel|DockPanel)\b[^>]*?(/?)>',
                                before)
            stack = []
            for close, tag, selfclose in opened:
                if selfclose:
                    continue
                if close:
                    if stack:
                        stack.pop()
                else:
                    stack.append(tag)
            if not stack or stack[-1] != 'Grid':
                fail(problems, '{}: header_pnl must sit directly in the '
                               'layout Grid'.format(xaml_name))
        if 'Value="shrunk"' not in xaml_text or 'Green' not in xaml_text:
            fail(problems, '{}: the shrink glyph never turns into the green '
                           'up arrow'.format(xaml_name))

    for needle, why in (
            ('BeginAnimation(Window.TopProperty, None)', 'Top is never released'),
            ('BeginAnimation(Window.HeightProperty, None)',
             'Height is never released'),
            ('Tick -= self._tick_handler', 'the timer handler is never removed'),
            ('w.MinHeight = self.saved[\'min_height\']',
             'MinHeight is never put back'),
            ('SizeToContent.Manual', 'SizeToContent would veto the slide'),
            ('_park_grips(True)', 'the grips are not parked with the window')):
        if needle not in drawer_src:
            fail(problems, 'bwic_drawer.py: {}'.format(why))

    # the arithmetic, proved against a table of cases
    try:
        import importlib
        sys.path.insert(0, HERE)
        dr = importlib.import_module('bwic_drawer')
        sys.path.pop(0)
        checks = []
        primary = (0.0, 0.0, 1920.0, 1040.0)
        above = (0.0, -1080.0, 1920.0, 1040.0)   # second monitor ABOVE
        left = (-1920.0, 0.0, 1920.0, 1040.0)
        checks.append(('ease starts at 0', dr.ease_out(0.0) == 0.0))
        checks.append(('ease ends at 1', dr.ease_out(1.0) == 1.0))
        checks.append(('ease clamps past the end', dr.ease_out(1.7) == 1.0))
        checks.append(('ease is front loaded', dr.ease_out(0.5) > 0.5))
        checks.append(('bar is header plus inset twice',
                       dr.bar_height(50.0, 13.0) == 76.0))
        checks.append(('first bar lands 8 above the taskbar',
                       dr.shrunk_top(primary, 76.0, 0) == 1040 - 8 - 76))
        checks.append(('second bar stacks 4 above the first',
                       dr.shrunk_top(primary, 76.0, 1) ==
                       1040 - 8 - 76 - (76 + 4)))
        checks.append(('a monitor above keeps its negative top',
                       dr.shrunk_top(above, 76.0, 0) == -1080 + 1040 - 8 - 76))
        checks.append(('a monitor to the left is untouched in Y',
                       dr.shrunk_top(left, 76.0, 0) == 1040 - 8 - 76))
        checks.append(('stacking never leaves the screen',
                       dr.shrunk_top(primary, 76.0, 50) == 0.0))
        checks.append(('free slot starts at 0', dr.free_slot([]) == 0))
        checks.append(('free slot reuses a gap', dr.free_slot([0, 2]) == 1))
        saved = (100.0, 120.0, 430.0, 700.0)
        landed = (100.0, 956.0)
        l, t, moved = dr.expand_target(saved, landed, landed, 76.0, primary)
        checks.append(('an unmoved bar goes home',
                       (l, t, moved) == (100.0, 120.0, False)))
        l, t, moved = dr.expand_target(saved, landed, (900.0, 900.0), 76.0,
                                       primary)
        checks.append(('a moved bar opens upward from where it sits',
                       moved and l == 900.0 and t == 900.0 + 76.0 - 700.0))
        l, t, moved = dr.expand_target(saved, landed, (900.0, 10.0), 76.0,
                                       primary)
        checks.append(('opening upward is kept on screen', t == 0.0))
        l, t, moved = dr.expand_target(saved, landed, (1800.0, 900.0), 76.0,
                                       primary)
        checks.append(('opening is kept off the right edge',
                       l == 1920.0 - 430.0))
        l, t, moved = dr.expand_target((100.0, -900.0, 430.0, 700.0),
                                       (100.0, -124.0), (100.0, -124.0), 76.0,
                                       above)
        checks.append(('reopening on a monitor above stays on it',
                       t == -900.0))
        for label, ok in checks:
            if not ok:
                fail(problems, 'drawer arithmetic: {}'.format(label))
        drawer_cases = len(checks)
        # and the state machine, against a stand-in window
        sys.path.insert(0, HERE)
        bench = importlib.import_module('drawer_bench')
        sys.path.pop(0)
        for label, passed in bench.run(HERE):
            drawer_cases += 1
            if not passed:
                fail(problems, 'drawer behaviour: {}'.format(label))
    except Exception as err:
        fail(problems, 'bwic_drawer.py could not be proved: {}'.format(err))
        drawer_cases = 0

    # --- step prompts --------------------------------------------------------
    # Every pick in a manual run says what it is waiting for, every loop says
    # when it is over (or the prompt would stay on screen), and every step it
    # names exists -- a misspelt one would show a blank prompt.
    core_src = sources.get('bwic_core.py', '')
    core_tree = ast.parse(core_src)
    tables = {}
    for node in core_tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id in ('FLOWS', 'STEP_TEXT', 'STEP_ENDS'):
            tables[node.targets[0].id] = ast.literal_eval(node.value)
    for table in ('FLOWS', 'STEP_TEXT', 'STEP_ENDS'):
        if table not in tables:
            fail(problems, 'bwic_core.py has no {} table'.format(table))
    flows = tables.get('FLOWS', {})
    texts = tables.get('STEP_TEXT', {})
    for flow, keys in sorted(flows.items()):
        for key in keys:
            if key not in texts:
                fail(problems, 'step "{}" in flow {} has no wording'.format(
                    key, flow))
            if key not in tables.get('STEP_ENDS', {}):
                fail(problems, 'step "{}" does not say how it ends'.format(key))
    in_flows = set(k for keys in flows.values() for k in keys)
    for key in sorted(set(re.findall(r"step_dict\(\s*flow,\s*'(\w+)'",
                                     core_src))):
        if key not in in_flows:
            fail(problems, 'the core announces step "{}", which no flow '
                           'has'.format(key))
    lines = core_src.splitlines()
    for number, line in enumerate(lines):
        if re.search(r'Selection\.PickObjects?\(', line):
            before = '\n'.join(lines[max(0, number - 4):number])
            if "guide('step'" not in before:
                fail(problems, 'bwic_core.py line {}: a pick with no step '
                               'prompt before it'.format(number + 1))
    for loop in ('_wall_loop', 'run_slab_loop'):
        body = re.search(r'\ndef ' + loop + r'\(.*?(?=\ndef |\Z)', core_src,
                         re.S)
        if body is None or "guide('done')" not in body.group(0):
            fail(problems, '{} never says it is done, so the prompt would '
                           'stay up'.format(loop))
    if "core.set_guide(None if mode == 'global' else self.on_guide)" \
            not in script_src:
        fail(problems, 'manual runs are never connected to the prompt')
    if "self.prompt.handle('done', {})" not in script_src:
        fail(problems, 'a run that ends badly could leave the prompt up')

    # --- family profiles ------------------------------------------------------
    # family profiles are applied where they are used: the core for wall and
    # slab runs, the main window for the circular wall run
    if "values = core.family_settings(self.settings, 'wall_circ')" \
            not in script_src:
        fail(problems, 'the circular wall run ignores its family profile')
    if "'round_wall': round_wall," not in script_src:
        fail(problems, 'the circular wall choice never reaches the core')
    round_run = re.search(r'\ndef run_placement_loop\(.*?(?=\ndef |\Z)',
                          core_src, re.S)
    round_text = round_run.group(0) if round_run else ''
    if 'ROUND_WALL = dict(round_wall)' not in round_text \
            or 'finally:' not in round_text \
            or 'ROUND_WALL) = saved' not in round_text:
        fail(problems, 'a circular wall run must swap its family in and put '
                       'the rectangular one back')
    if 'families.round_hole_mm(' not in core_src:
        fail(problems, 'circular wall holes are not sized by round_hole_mm')
    # one card per family slot in the main window, none left in Settings
    for slot in ('wall', 'wall_circ', 'slab_rect', 'slab_circ'):
        if "FamilyCard(self, '{}'".format(slot) not in script_src:
            fail(problems, 'no family card for the {} slot'.format(slot))
    settings_xaml = io.open(op.join(HERE, 'settings.xaml'),
                            encoding='utf-8').read()
    if '_famset_click' in settings_xaml or '_family_cb' in settings_xaml:
        fail(problems, 'family selection is back in Settings')
    if 'job_settings = slab_job_settings(settings, shape, symbol,' \
            not in core_src:
        fail(problems, 'slab openings do not use their own family profile')
    if "values = family_settings(values, 'wall')" not in core_src:
        fail(problems, 'the wall family profile is never applied')
    if "core.family_settings(self.settings, 'wall')" not in script_src:
        fail(problems, 'Global Placement ignores the wall family profile')

    # the prompt's timing and the profiles, against a table of cases
    try:
        sys.path.insert(0, HERE)
        logic = importlib.import_module('logic_bench')
        sys.path.pop(0)
        logic_cases = 0
        for label, passed in logic.run(HERE):
            logic_cases += 1
            if not passed:
                fail(problems, 'logic: {}'.format(label))
    except Exception as err:
        fail(problems, 'logic_bench.py could not run: {}'.format(err))
        logic_cases = 0

    # --- one child where WPF allows only one ----------------------------------
    # Expander, Border, ScrollViewer, Button and the like hold a single
    # element as their content. Two side by side parse as valid XML but fail
    # when Revit loads the window: "'Content' property has already been set".
    import xml.dom.minidom as minidom
    single = ('Expander', 'Border', 'ScrollViewer', 'Button', 'CheckBox',
              'TabItem', 'ToggleButton', 'Window', 'ContentControl', 'Viewbox',
              'Label', 'RadioButton')
    for xaml_name, _ in PAIRS:
        dom = minidom.parse(op.join(HERE, xaml_name))
        for element in dom.getElementsByTagName('*'):
            if element.tagName not in single:
                continue
            children = [k for k in element.childNodes
                        if k.nodeType == k.ELEMENT_NODE and '.' not in k.tagName]
            if len(children) > 1:
                fail(problems, '{}: {} "{}" holds {} elements but can only hold '
                               'one - wrap them in a panel'.format(
                                   xaml_name, element.tagName,
                                   element.getAttribute('x:Name')
                                   or element.getAttribute('Header') or '?',
                               len(children)))

    # --- messages without a status box ---------------------------------------
    # Messages show as a note on the prompt, but not during a run: the prompt
    # holds the next step back while a note shows, so a note at the start of a
    # run would delay step 1. The run must be flagged before its first message
    # and unflagged when it ends, or every later message is swallowed.
    run_body = re.search(r'def start_run\(self, mode\):(.*?)(?:\n    @|\n    def |\Z)',
                         class_body(script_src, 'BWICWindow'), re.S)
    if run_body is None:
        fail(problems, 'start_run is missing')
    else:
        text = run_body.group(1)
        flag = text.find('self.running = True')
        first = text.find('self.report(message)')
        if flag < 0 or first < 0 or flag > first:
            fail(problems, 'a run is flagged after its first message, so a '
                           'note would hold back step 1')
    finish = re.search(r'def finish\(self\):(.*?)(?:\n    @|\n    def |\Z)',
                       class_body(script_src, 'BWICWindow'), re.S)
    if finish is None or 'self.running = False' not in finish.group(1):
        fail(problems, 'finish() never clears the run flag, so every message '
                       'after the first run would be swallowed')
    report = re.search(r'def report\(self, message\):(.*?)(?:\n    @|\n    def |\Z)',
                       class_body(script_src, 'BWICWindow'), re.S)
    if report is None or "getattr(self, 'running', False)" not in report.group(1):
        fail(problems, 'report() shows notes during a run')
    if 'status_tb' in io.open(op.join(HERE, 'ui.xaml'), encoding='utf-8').read():
        fail(problems, 'the status box is back')

    # --- split (X+ / X-) families --------------------------------------------
    # One writer for the whole tool, and it is the one that halves a pair. A
    # size checked or written any other way would skip the split.
    global_src = sources.get('bwic_global.py', '')
    writer = re.search(r'\ndef set_length_param\(.*?(?=\ndef |\Z)', core_src, re.S)
    if writer is None or 'families.split_parts(name)' not in writer.group(0):
        fail(problems, 'the size writer does not split X+ / X- pairs')
    else:
        text = writer.group(0)
        if text.find('.Set(') < text.find('params.append'):
            fail(problems, 'the size writer sets a side before checking both, '
                           'so a pair could be left half sized')
    for name, text in (('bwic_core.py', core_src), ('bwic_global.py', global_src)):
        for pattern in (r'LookupParameter\(pname\)', r'LookupParameter\(n\)'):
            if re.search(pattern, text):
                fail(problems, '{} checks a size parameter directly, which '
                               'misses a split pair'.format(name))
    if 'from bwic_core import set_length_param, has_length_param' \
            not in global_src or re.search(r'\ndef set_length_param\(',
                                           global_src):
        fail(problems, 'Global Placement has its own size writer, which does '
                       'not split pairs')

    # --- resize uses the picked BWIC's own family ----------------------------
    # The tab's family is for placing. A resize sizes the BWIC that was picked,
    # with that family's settings -- otherwise a different family, a round one
    # or an X+ / X- one would be sized with the wrong parameter names.
    if 'swapped = use_wall_family(target, options)' not in core_src \
            or 'restore_wall_family(swapped)' not in core_src:
        fail(problems, 'a wall resize does not use the picked BWIC\'s family')
    if "slot, resize_values = resize_settings(target, 'slab')" not in core_src \
            or 'symbol = target.Symbol' not in core_src:
        fail(problems, 'a slab resize does not keep the picked BWIC\'s family')
    if 'families.settings_for_family(' not in core_src:
        fail(problems, 'resizes do not look up the family settings')
    if "'round_spec': self.round_spec()" not in script_src:
        fail(problems, 'a round BWIC resized from the Rectangular tab has no '
                       'gap to size with')

    # --- Finish Selection never sends Return outside a selection ----------
    # Return in Revit with nothing waiting repeats the last command.
    click = re.search(r'def finish_click\(.*?(?=\n    @|\n    def )',
                      script_src, re.S)
    text = click.group(0) if click else ''
    if 'if not self.finish_ready:' not in text or \
            text.find('self.arm_finish(False)') > text.find('core.press_finish()'):
        fail(problems, 'Finish Selection can send Return when no selection '
                       'is waiting, or twice')
    press = re.search(r'\ndef _press_finish\(.*?(?=\ndef |\Z)', core_src, re.S)
    if press is None or not re.search(
            r'\n    except BaseException as err:\n.*\n    except:\n        pass',
            press.group(0), re.S):
        fail(problems, 'Finish Selection runs on a thread an exception could '
                       'escape, which would end Revit')
    if re.search(r'keybd_event', core_src):
        fail(problems, 'Finish Selection types Return into whatever has the '
                       'keyboard -- the tool window, as it turned out')
    if 'Thread(ThreadStart(' not in core_src:
        fail(problems, 'Finish Selection presses Revit\'s button on the UI '
                       'thread, which the click handler is still holding')
    guide = re.search(r'def on_guide\(.*?(?=\n    @|\n    def )', script_src,
                      re.S)
    if guide is None or 'steps.finish_armed(' not in guide.group(0):
        fail(problems, 'Finish Selection does not follow the run\'s steps')
    done = re.search(r'    def finish\(self\):.*?(?=\n    @|\n    def )',
                     script_src, re.S)
    if done is None or 'self.arm_finish(False)' not in done.group(0):
        fail(problems, 'Finish Selection stays lit after the run ends')

    # --- Family settings before anything runs ------------------------------
    start = re.search(r'    def start_run\(self, mode\):.*?(?=\n    @|\n    def )',
                      script_src, re.S)
    if start is None or not re.search(
            r'def start_run\(self, mode\):\s*\n(\s*#.*\n)*\s*if self\.'
            r'blocked_by_family_settings\(mode\):\s*\n\s*return',
            start.group(0)):
        fail(problems, 'a run can start before its family\'s Family '
                       'settings are saved')
    names = re.search(r'\ndef resize_family_names\(.*?(?=\ndef |\Z)', core_src,
                      re.S)
    if names is None or 'read_settings()' in names.group(0) or \
            'load_profiles()' not in names.group(0):
        fail(problems, 'a resize accepts a BWIC whose family is not set up')
    for box in ('clearance_tb"', 'wc_gap_tb', 'slab_clearance_tb',
                'slab_gap_tb', 'g_clearance_tb'):
        if box in io.open(op.join(HERE, 'ui.xaml'), encoding='utf-8').read():
            fail(problems, 'the main window still has a clearance box ({}) - '
                           'clearance is set per family'.format(box.strip('"')))
    fill = re.search(r'    def fill\(self, families, every=None\):.*?(?=\n    def )',
                     script_src, re.S)
    if fill is None or 'fam.set_first(' not in fill.group(0) or \
            'self.list_item(' not in fill.group(0):
        fail(problems, 'set-up families are not green and first in the lists')

    # --- a clearance per family --------------------------------------------
    # Family settings can give a family its own clearance; every place it is
    # used must ask the family first, or the tab's figure wins silently.
    loop = re.search(r'\ndef _wall_loop\(.*?(?=\ndef |\Z)', core_src, re.S)
    loop_text = loop.group(0) if loop else ''
    if 'clearance_mm = family_clearance_mm(FAMILY_NAME, tab_clearance_mm)' \
            not in loop_text:
        fail(problems, 'a wall run uses the tab\'s clearance, not the '
                       'family\'s')
    if 'mm_to_ft(family_clearance_mm(FAMILY_NAME,' not in loop_text:
        fail(problems, 'a wall resize uses the tab\'s clearance, not the '
                       'picked family\'s')
    if "ROUND_WALL['gap_mm'] = family_clearance_mm(" not in round_text:
        fail(problems, 'a circular wall run uses the tab\'s gap, not the '
                       'family\'s')
    swap = re.search(r'\ndef use_wall_family\(.*?(?=\ndef |\Z)', core_src, re.S)
    if swap is None or "ROUND_WALL['gap_mm'] = family_clearance_mm(" not in \
            swap.group(0):
        fail(problems, 'a round BWIC resize uses the tab\'s gap, not its '
                       'family\'s')
    if 'circular_size(job[0], job_gap_ft,' not in core_src or \
            'doc, job, slab, transform, job_clearance_ft,' not in core_src:
        fail(problems, 'a slab opening uses the tab\'s clearance, not its '
                       'family\'s')
    if "get('family_clearance')" not in global_src:
        fail(problems, 'Global Placement ignores the family\'s clearance')
    if "'clearance_mm': str(self.fs_clearance_tb.Text).strip()" not in \
            class_body(script_src, 'FamilySettingsWindow'):
        fail(problems, 'Family settings does not save the clearance')

    # --- family lists by shape, and the docked step card -------------------
    reload = re.search(r'def reload_families\(.*?(?=\n    def )', script_src,
                       re.S)
    if reload is None or 'fam.families_for_slot(card.slot' not in \
            reload.group(0):
        fail(problems, 'the family lists are not sorted by shape, so a '
                       'circular family shows on a rectangular tab')
    controller = class_body(script_src, 'StepPrompt')
    if 'self.tool.show_docked_prompt(look)' not in controller \
            or 'self.parked()' not in controller:
        fail(problems, 'the step card is not docked under the buttons, or '
                       'does not float while the window is parked')
    if 'self.drawer.on_change = self.drawer_moved' not in script_src:
        fail(problems, 'parking the window mid-step leaves the step card '
                       'where it cannot be seen')
    if "self._heading('parked')" not in sources.get('bwic_drawer.py', ''):
        fail(problems, 'the drawer never says it is parking')

    # --- sizes are measured inside the wall, to the right parameters ------
    # Measured over the whole run, a drainage pipe's fall was added to the
    # height. And a blank size name kept the last run's -- an X+ / X- pair
    # wrote a family since set back to Standard.
    compute = re.search(r'\ndef compute_bwic\(.*?(?=\ndef |\Z)', core_src, re.S)
    if compute is None or 'service_points(service, plane)' not in \
            compute.group(0):
        fail(problems, 'wall openings are measured over the whole run, so a '
                       'pipe\'s fall grows the height')
    if 'families.wall_span(' not in core_src:
        fail(problems, 'service_points never trims a run to the wall')
    for func in ('apply_settings', 'use_wall_family'):
        body = re.search(r'\ndef ' + func + r'\(.*?(?=\ndef |\Z)', core_src,
                         re.S)
        text = body.group(0) if body else ''
        for size in ('P_LENGTH', 'P_WIDTH', 'P_HEIGHT'):
            if not re.search(size + r" = values\.get\('wall_\w+_param'\) or "
                             r"DEFAULT_" + size + r"\b", text):
                fail(problems, '{} can keep the last run\'s {} when a '
                               'family leaves it blank'.format(func, size))

    # --- the family's own workset -----------------------------------------
    # A family can name its workset in Family settings. Every place and resize
    # goes through place_on_workset, which asks the family first; a direct
    # assign_workset in the core would quietly use the Settings workset.
    helper = re.search(r'\ndef place_on_workset\(.*?(?=\ndef |\Z)', core_src,
                       re.S)
    if helper is None or 'families.family_workset(' not in helper.group(0) \
            or 'families.workset_choice(' not in helper.group(0):
        fail(problems, 'placement does not ask the family for its workset')
    else:
        outside = core_src.replace(helper.group(0), '')
        if re.search(r'assign_workset\(instance', outside):
            fail(problems, 'a placement sets the workset directly, skipping '
                           'the family\'s own workset')
        if outside.count('place_on_workset(doc, instance, options, workset, '
                         'notes)') < 2:
            fail(problems, 'the wall and slab placements do not both put the '
                           'BWIC on its family\'s workset')
    if "out['family_workset']" not in sources.get('bwic_families.py', '') \
            or "get('family_workset')" not in global_src:
        fail(problems, 'Global Placement does not follow the family\'s '
                       'workset')
    fs_body = class_body(script_src, 'FamilySettingsWindow')
    if "'worksets': self.gathered_worksets()" not in fs_body:
        fail(problems, 'Family settings does not save the worksets')
    drive_handler = re.search(r'def drive_changed\(.*?(?=\n    @|\n    def )',
                              fs_body, re.S)
    if drive_handler is None or 'self.keep_workset()' not in \
            drive_handler.group(0):
        fail(problems, 'switching sub tab in Family settings loses the '
                       'workset chosen on the other')
    if "out['family_workset'] = profile_workset(profile)" not in \
            sources.get('bwic_families.py', ''):
        fail(problems, 'Global Placement is not given the workset of the '
                       'sub tab the family is set to')

    # --- sub tabs and collapsible groups ------------------------------------
    # SelectionChanged bubbles: a family list inside a sub tab fires the tab's
    # handler too. Every tab handler must check where the event came from.
    ui_xaml = io.open(op.join(HERE, 'ui.xaml'), encoding='utf-8').read()
    main_body = class_body(script_src, 'BWICWindow')
    for xaml_name, class_name in PAIRS:
        window_xaml = io.open(op.join(HERE, xaml_name), encoding='utf-8').read()
        window_body = class_body(script_src, class_name)
        tab_handlers = set(re.findall(
            r'<TabControl\b[^>]*SelectionChanged="(\w+)"', window_xaml, re.S))
        tab_handlers |= set(re.findall(
            r'self\.\w*tabs\.SelectionChanged \+= self\.(\w+)', window_body))
        for handler in sorted(tab_handlers):
            found = re.search(r'def ' + handler +
                              r'\(self[^)]*\):(.*?)(?:\n    @|\n    def |\Z)',
                              window_body, re.S)
            if found is None or 'OriginalSource' not in found.group(1):
                fail(problems, '{}.{} does not check where SelectionChanged '
                               'came from, so a family list would switch '
                               'tabs'.format(class_name, handler))
    # every group remembers whether it was left open or closed
    remembered = set(re.findall(r"\('\w+', self\.(grp_\w+)\)", main_body))
    for group in sorted(set(re.findall(
            r'<Expander x:Name="(grp_\w+)"', ui_xaml))):
        if group not in remembered:
            fail(problems, 'group {} is not in the open/closed memory'.format(
                group))

    # --- the version and the changelog must agree -------------------------
    # They drifted apart for six releases: a version bump chained behind this
    # very check with && never ran when the check failed, and every later bump
    # then searched for a string that had never been written.
    core_src = sources.get('bwic_core.py', '')
    declared = re.search(r"__version__ = '([\d.]+)'", core_src)
    changelog = op.join(HERE, 'CHANGELOG.md')
    if declared is None:
        fail(problems, 'bwic_core.py has no __version__')
    elif not op.isfile(changelog):
        fail(problems, 'CHANGELOG.md is missing')
    else:
        text = io.open(changelog, encoding='utf-8').read()
        headings = re.findall(r'^## ([\d.]+)', text, re.M)
        if not headings:
            fail(problems, 'CHANGELOG.md has no version headings')
        elif headings[0] != declared.group(1):
            fail(problems, '__version__ is {} but the newest CHANGELOG entry '
                           'is {}'.format(declared.group(1), headings[0]))

    # --- IronPython constraints -------------------------------------------
    for name, text in sources.items():
        for index, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if re.search(r'\bf["\']', stripped) and not stripped.startswith('#'):
                fail(problems, '{} line {}: f-string, which IronPython 2.7 '
                               'cannot parse'.format(name, index))
            if re.match(r'^print[ (]', stripped):
                fail(problems, '{} line {}: print statement'.format(name, index))

    if 'def eid_value(' in all_src:
        guarded = all_src[all_src.index('def eid_value('):]
        cut = guarded.index('\ndef ', 5) if '\ndef ' in guarded[5:] else len(guarded)
        outside = all_src.replace(guarded[:cut], '')
        if '.IntegerValue' in outside:
            fail(problems, 'bare .IntegerValue outside eid_value -- removed '
                           'in Revit 2026')

    if problems:
        for problem in problems:
            print('FAIL  {}'.format(problem))
        print('\n{} problem(s).'.format(len(problems)))
        return 1

    print('OK  every window agrees with its XAML.')
    print('    shrink drawer on {} windows, {} drawer checks proved.'.format(
        len(PAIRS) - len(DRAWER_EXEMPT), drawer_cases))
    print('    step prompt and family profiles: {} logic checks proved.'.format(
        logic_cases))
    print('    {} controls, {} handlers, {} resource keys checked across '
          '{} windows.'.format(total_names, total_handlers, total_keys,
                               len(PAIRS)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
