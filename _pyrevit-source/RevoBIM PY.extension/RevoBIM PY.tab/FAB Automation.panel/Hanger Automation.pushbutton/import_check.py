# -*- coding: utf-8 -*-
"""Static bench for Hanger Automation (plain CPython).
    python import_check.py             run every rule
    python import_check.py --selftest  break one thing at a time, confirm the rule fires
"""
import os
import re
import sys
import shutil
import tempfile
import xml.dom.minidom as minidom

HERE = os.path.dirname(os.path.abspath(__file__))
PY = ['script.py', 'fha_clr.py', 'fha_core.py', 'fha_revit.py', 'fha_ui.py', 'fha_window.py',
      'hfam_core.py', 'hfam_revit.py', 'hfam_ui.py', 'hview_ui.py', 'hcirc_core.py', 'hcirc_revit.py']
XAML = ['HangerAutomation.xaml', 'Theme.xaml', 'HangerFamilySettings.xaml', 'HangerRules.xaml',
        'HangerPrompt.xaml', 'HangerDimViews.xaml']
LAYOUTS = ['HangerAutomation.xaml', 'HangerFamilySettings.xaml', 'HangerRules.xaml', 'HangerPrompt.xaml',
           'HangerDimViews.xaml']
NET_MODULES = ['fha_revit.py', 'fha_ui.py', 'fha_window.py', 'hfam_revit.py', 'hfam_ui.py', 'hview_ui.py', 'hcirc_revit.py']
NS_ASSEMBLY = {
    'System': ['mscorlib', 'System'],
    'System.Windows': ['PresentationFramework', 'PresentationCore', 'WindowsBase'],
    'System.Windows.Threading': ['WindowsBase'],
    'System.Windows.Input': ['PresentationCore'],
    'System.Windows.Media.Animation': ['PresentationCore'],
    'System.Windows.Media': ['PresentationCore'],
    'System.Windows.Media.Imaging': ['PresentationCore'],
    'System.Windows.Controls': ['PresentationFramework'],
    'System.Windows.Controls.Primitives': ['PresentationFramework'],
    'System.Windows.Interop': ['PresentationFramework', 'PresentationCore'],
    'System.Windows.Forms': ['System.Windows.Forms'],
    'System.Drawing': ['System.Drawing'],
    'System.Drawing.Imaging': ['System.Drawing'],
    'System.IO': ['mscorlib', 'System'],
    'System.Collections.Generic': ['mscorlib', 'System'],
    'System.Windows.Markup': ['PresentationFramework', 'System.Xaml'],
}


def rd(root, name):
    with open(os.path.join(root, name), 'rb') as f:
        return f.read().decode('utf-8')


def rule_xaml_parses(root):
    bad = []
    for n in XAML:
        try:
            minidom.parseString(rd(root, n).encode('utf-8'))
        except Exception as ex:
            bad.append('%s: %s' % (n, ex))
    return bad


def rule_clr_first(root):
    bad = []
    for n in NET_MODULES:
        src = rd(root, n)
        m = re.search(r'^import fha_clr', src, re.M)
        net = re.search(r'^(from|import) (System|Autodesk)', src, re.M)
        if not m:
            bad.append('%s: fha_clr not imported' % n)
        elif net and net.start() < m.start():
            bad.append('%s: .NET import before fha_clr' % n)
    if re.search(r'^(from|import) (System|Autodesk|clr)', rd(root, 'fha_core.py'), re.M):
        bad.append('fha_core touches .NET')
    return bad


def rule_assemblies_referenced(root):
    ref = rd(root, 'fha_clr.py')
    have = set(re.findall(r"'([A-Za-z.]+)'", ref))
    bad = []
    for n in NET_MODULES:
        for ns in re.findall(r'^from (System[\w.]*) import', rd(root, n), re.M):
            need = NS_ASSEMBLY.get(ns, ['mscorlib'])
            if not any(a in have for a in need):
                bad.append('%s: %s needs one of %s' % (n, ns, need))
    return bad


def rule_no_staticresource(root):
    return ['%s uses StaticResource' % n for n in LAYOUTS if 'StaticResource' in rd(root, n)]


def rule_resource_keys(root):
    theme = rd(root, 'Theme.xaml')
    defined = set(re.findall(r'x:Key="(\w+)"', theme))
    used = set(re.findall(r'DynamicResource (\w+)', ''.join(rd(root, n) for n in LAYOUTS) + theme))
    return ['undefined resource key %s' % k for k in sorted(used - defined)]


def rule_palette_matches_theme(root):
    sys.path.insert(0, root)
    import importlib
    core = importlib.import_module('fha_core')
    defined = set(re.findall(r'x:Key="(\w+)Brush"', rd(root, 'Theme.xaml')))
    bad = []
    for mode in core.PALETTES:
        for k in core.PALETTES[mode]:
            if k not in defined:
                bad.append('%s palette key %s has no brush' % (mode, k))
    return bad


def rule_theme_defaults_dark(root):
    u"""Theme.xaml's brush colours are the dark palette (Revit's dark greys), so
    the window's first paint matches before the palette is applied."""
    sys.path.insert(0, root)
    import importlib
    for k in [m for m in list(sys.modules) if m == 'fha_core']:
        del sys.modules[k]
    core = importlib.import_module('fha_core')
    theme = dict(re.findall(r'x:Key="(\w+)Brush" Color="(#[0-9A-Fa-f]{6})"', rd(root, 'Theme.xaml')))
    bad = []
    for k, v in core.PALETTES['dark'].items():
        if theme.get(k, '').upper() != v.upper():
            bad.append('%sBrush is %s in Theme.xaml, %s in the dark palette' % (k, theme.get(k), v))
    return bad


def rule_findname(root):
    names = set(re.findall(r'x:Name="(\w+)"', ''.join(rd(root, n) for n in LAYOUTS)))
    used = set()
    for n in ('fha_window.py', 'fha_ui.py', 'hfam_ui.py', 'hview_ui.py'):
        used |= set(re.findall(r"(?:self\.c|FindName)\('(\w+)'\)", rd(root, n)))
        used |= set(re.findall(r"'((?:Chk|Btn|Txt|Cmb|Lst|Dlg|Fam|Tab|Rules)[A-Z]\w*)'", code_only(rd(root, n))))
    keys = set(re.findall(r'x:Key="(\w+)"', rd(root, 'Theme.xaml')))
    return ['no x:Name for %s' % k for k in sorted(used - names - keys)]


def rule_banned_python(root):
    bad = []
    for n in PY:
        src = rd(root, n)
        if re.search(r'\bf"|\bf\'', src):
            bad.append('%s: f-string' % n)
        if re.search(r'^\s*print\s+[^(\s]', src, re.M):
            bad.append('%s: print statement' % n)
        for m in re.finditer(r'\.IntegerValue', src):
            owner = re.findall(r'^def (\w+)', src[:m.start()], re.M)
            if not owner or owner[-1] not in ('eid_value', 'ws_int'):
                bad.append('%s: .IntegerValue outside eid_value/ws_int' % n)
        if re.search(r'import Uri|System\.Uri', src):
            bad.append('%s: System.Uri' % n)
        if 'nonlocal' in src:
            bad.append('%s: nonlocal' % n)
    return bad


def rule_no_duplicate_defs(root):
    bad = []
    for n in PY:
        seen = {}
        for m in re.finditer(r'^([ \t]*)def (\w+)', rd(root, n), re.M):
            key = (len(m.group(1)), m.group(2))
            if len(m.group(1)) == 0 and key in seen:
                bad.append('%s: %s defined twice' % (n, m.group(2)))
            seen[key] = 1
    return bad


def rule_loader_thin(root):
    src = rd(root, 'script.py')
    bad = []
    if '__persistentengine__ = True' not in src:
        bad.append('script.py: no __persistentengine__')
    if len(src.split('\n')) > 80:
        bad.append('script.py is not thin')
    return bad


def rule_changelog_version(root):
    sys.path.insert(0, root)
    import importlib
    core = importlib.import_module('fha_core')
    return [] if ('## %s' % core.__version__) in rd(root, 'CHANGELOG.md') else ['CHANGELOG lacks %s' % core.__version__]


def rule_transparent_window(root):
    bad = []
    for n in LAYOUTS:
        x = rd(root, n)
        if 'AllowsTransparency="True"' in x and 'WindowStyle="None"' not in x:
            bad.append('%s: AllowsTransparency without WindowStyle=None' % n)
        if 'Baseline' in x:
            bad.append('%s: Baseline alignment in layout' % n)
    return bad


def rule_handlers_exist(root):
    src = rd(root, 'fha_window.py')
    bad = []
    for m in re.findall(r'\+= self\.(_\w+)[ \t]*$', src, re.M):
        if not re.search(r'def %s\(' % m, src):
            bad.append('handler %s missing' % m)
    return bad


def rule_enums_late(root):
    src = rd(root, 'fha_revit.py')
    return ['ViewType enum imported at top for use at module level'] if re.search(r'^_\w+\s*=\s*ViewType', src, re.M) else []


def rule_version_top_right(root):
    x = rd(root, XAML[0])
    return [] if 'x:Name="VerTxt"' in x and 'x:Name="ThemeBtn"' in x else ['version or theme chip missing']


def rule_compiles(root):
    bad = []
    for n in PY:
        try:
            compile(rd(root, n), n, 'exec')
        except SyntaxError as ex:
            bad.append('%s: %s' % (n, ex))
    return bad


def code_only(src):
    u"""Source with docstrings blanked (line numbers kept) - rules must match code, not prose."""
    return re.sub(r'(?s)u?(\"\"\"|\'\'\').*?\1', lambda m: '\n' * m.group(0).count('\n'), src)


def rule_no_python_attrs_on_wpf(root):
    u"""IronPython refuses new attributes on .NET objects: `win._full = x` is the
    1.0.0 crash.  Only PascalCase (real WPF properties) may be assigned onto the
    window or a control; Python state belongs on Python objects."""
    bad = []
    pat = re.compile(r"(?:\bwin|self\.win|fw\.win|owner\.win|self\.c\('\w+'\)|\bt|\bbi|\blogo)\.([a-z_]\w*)\s*=(?!=)")
    for n in ('fha_ui.py', 'fha_window.py', 'hfam_ui.py', 'hview_ui.py'):
        for i, line in enumerate(code_only(rd(root, n)).split('\n'), 1):
            if line.strip().startswith('#'):
                continue
            for m in pat.finditer(line):
                bad.append('%s:%d assigns .%s onto a WPF object' % (n, i, m.group(1)))
    return bad


def rule_raise_status_read(root):
    src = rd(root, 'fha_window.py')
    if re.search(r"^\s*_STATE\['evt'\]\.Raise\(\)\s*$", src, re.M):
        return ['ExternalEvent.Raise() result ignored']
    return [] if re.search(r"=\s*str\(_STATE\['evt'\]\.Raise\(\)\)", src) else ['Raise() status not read']


def rule_hosting_by_connector(root):
    u"""CreateHanger / PlaceOnHost take a Connector object, never an index."""
    src = rd(root, 'fha_revit.py')
    bad = []
    if re.search(r'PlaceOnHost\([^)]*,\s*\d+\s*,', src):
        bad.append('PlaceOnHost given a connector index')
    if re.search(r"places\.append\(\(elems\[loc\['id'\]\],\s*loc\['entry'\]", src):
        bad.append('hanger hosted by connector index')
    return bad


def rule_egg_on_logo_only(root):
    u"""The shared attach is attach(logo, host_window=...).  Handing it the window
    first (1.0.1) armed the whole window, so clicks anywhere started PacMan."""
    ui_src = code_only(rd(root, 'fha_ui.py'))
    win_src = code_only(rd(root, 'fha_window.py'))
    bad = []
    if re.search(r'\battach\(\s*win\b', ui_src):
        bad.append('egg attach() given the window as its first argument')
    if not re.search(r'\battach\(\s*logo\b', ui_src):
        bad.append('egg attach() not given the logo first')
    if not re.search(r"attach_egg\(self\.win,\s*self\.c\('Logo'\)", win_src):
        bad.append('window does not hand the Logo element to attach_egg')
    return bad


def rule_tab_buttons_reachable(root):
    u"""1.1.0 shipped with the Auto place button below the bottom of the window.
    Each family tool's button sits at the bottom right of its own folding body,
    every tool has a header that folds it, and both tab bodies scroll."""
    x = rd(root, 'HangerAutomation.xaml')
    bad = []
    for key, name in (('Place', 'BtnFamPlace'), ('Realign', 'BtnFamRealign'), ('Auto', 'BtnFamAuto'), ('Rods', 'BtnFamRods'), ('Dims', 'BtnFamDims')):
        hdr = x.find('x:Name="HdrFam%s"' % key)
        body = x.find('x:Name="BodyFam%s"' % key)
        btn = x.find('<Button x:Name="%s" HorizontalAlignment="Right"' % name)
        nxt = x.find('x:Name="HdrFam', body + 1) if body >= 0 else -1
        if hdr < 0 or body < 0:
            bad.append('%s has no folding header / body' % key)
        elif btn < body or (nxt >= 0 and btn > nxt):
            bad.append('%s is not at the bottom right of its tool body' % name)
    if 'x:Name="BtnFamToggleAll"' not in x:
        bad.append('no collapse / expand all button')
    for panel in ('FabPanel', 'FamPanel', 'FloorPanel'):
        if not re.search(r'<ScrollViewer x:Name="%s"' % panel, x):
            bad.append('%s cannot scroll' % panel)
    if re.search(r'<RotateTransform[^>]*x:Name', x + rd(root, 'Theme.xaml')):
        bad.append('a named RotateTransform in XAML (freezable - breaks loading)')
    return bad


def rule_window_fits_tools(root):
    u"""The window sizes itself to show every tool: on first render and on
    every tab switch."""
    src = code_only(rd(root, 'fha_window.py'))
    bad = []
    if not re.search(r'self\.win\.ContentRendered \+= self\.fit', src):
        bad.append('window does not fit itself when first shown')
    if not re.search(r"def _show_tab\(self, name\):(?:(?!\n    def ).)*self\.fit\(\)", src, re.S):
        bad.append('switching tabs does not refit the window')
    if 'on_resize=self.o.resize_for_fold' not in code_only(rd(root, 'hfam_ui.py')):
        bad.append('folding a tool does not resize the window')
    if 'MAX_SCREEN' not in code_only(rd(root, 'fha_window.py')):
        bad.append('fold resize is not capped to the screen')
    return bad


def rule_shrink_button(root):
    u"""Every window (main and every dialog): a shrink-to-taskbar button in its
    title bar with a shrink glyph and a GREEN up arrow, and the main one wired."""
    bad = []
    for lay in LAYOUTS:
        x = rd(root, lay)
        m = re.search(r'x:Name="(\w*)ShrinkBtn"', x)
        if not m:
            bad.append('%s has no shrink button' % lay)
            continue
        p = m.group(1)
        for n in (p + 'ShrinkIcon', p + 'ExpandIcon'):
            if 'x:Name="%s"' % n not in x:
                bad.append('%s: %s missing' % (lay, n))
        if not re.search(r'x:Name="%sExpandIcon"[^>]*Stroke="\{DynamicResource GreenBrush\}"' % p, x):
            bad.append('%s: the expand arrow is not green' % lay)
    if "self.c('ShrinkBtn').Click += self._shrink_click" not in code_only(rd(root, 'fha_window.py')):
        bad.append('ShrinkBtn is not wired')
    return bad


def rule_every_window_has_drawer(root):
    u"""A class that loads a window builds its drawer (theme reference: every
    window a tool opens)."""
    bad = []
    for n in ('fha_window.py', 'hfam_ui.py', 'hview_ui.py'):
        src = code_only(rd(root, n))
        for block in re.split(r'\nclass ', src)[1:]:
            name = block.split('(')[0]
            if ('load_xaml_window(' in block or 'load_window(' in block) and \
                    'Drawer(' not in block and 'dialog_drawer(' not in block:
                bad.append('%s: %s opens a window with no drawer' % (n, name))
    return bad


def rule_drawer_releases_animation(root):
    u"""An animation holds its end value over every later assignment: the
    drawer must release Top and Height when it lands, and land without one."""
    src = code_only(rd(root, 'fha_ui.py'))
    d = src[src.index('class Drawer'):]
    bad = []
    for need in ('BeginAnimation(Window.TopProperty, None)', 'BeginAnimation(FrameworkElement.HeightProperty, None)'):
        if need not in d:
            bad.append('the drawer never releases %s' % need.split('(')[1].split(',')[0])
    if not re.search(r'except Exception:\s*\n\s*finish\(\)', d):
        bad.append('no landing when the animation cannot start')
    return bad


def rule_escape_never_closes(root):
    u"""Escape is pressed to leave Revit picks: it must never close the tool."""
    src = code_only(rd(root, 'fha_window.py'))
    body = src[src.index('def _key(self'):]
    body = body[:body.index('\n    def ')]
    return ['_key closes the window'] if 'close(' in body else []


def rule_floor_panel_in_sync(root):
    u"""The Family Floor Support panel is built from the Family Hangers panel by
    build_floor_panel.py - edit the hanger panel, then run it."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('bfp_check', os.path.join(root, 'build_floor_panel.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    x = rd(root, 'HangerAutomation.xaml')
    try:
        if mod.rebuilt(x) != x:
            return ['FloorPanel is out of step with FamPanel - run build_floor_panel.py']
    except Exception as ex:
        return ['build_floor_panel.py failed: %s' % ex]
    return []


def rule_floor_twins(root):
    u"""Every control the family tab code reaches has its Flr twin on the floor
    tab (drop rod controls excepted), since the floor tab runs the same code."""
    names = set(re.findall(r'x:Name="(\w+)"', rd(root, 'HangerAutomation.xaml')))
    src = code_only(rd(root, 'hfam_ui.py'))
    cls = src[src.index('class FamTab'):src.index('class RulesDialog')]
    used = set(re.findall(r"self\.c\('(\w+)'\)", cls))
    used |= set(re.findall(r"'((?:Chk|Btn|Txt|Cmb)Fam\w+)'", src))
    rods = set(re.findall(r"'(\w+)'", src[src.index('ROD_CONTROLS'):src.index('\n', src.index('ROD_CONTROLS'))]))
    bad = []
    for n in sorted(used - rods):
        twin = 'FloorPanel' if n == 'FamPanel' else ('LstFlrFamilies' if n == 'LstFamilies' else n.replace('Fam', 'Flr', 1))
        if n in names and twin not in names:
            bad.append('%s has no floor twin %s' % (n, twin))
    return bad


def rule_circular_separate(root):
    u"""Circular System Based supports are a path of their own: the rectangular
    supports and the hangers (hfam_revit, hfam_core) never reach into it, and
    only the floor tab's dispatch (hfam_ui) chooses it."""
    bad = []
    for name in ('hfam_revit.py', 'hfam_core.py'):
        src = code_only(rd(root, name))
        for word in ('hcirc', 'is_circ', 'circ_', 'set_dia'):
            if word in src.replace("u'circ_height'", '').replace("u'circ_axis'", '').replace("cfg[u'circ_height']", ''):
                bad.append('%s reaches into the circular path (%s)' % (name, word))
    ui_src = code_only(rd(root, 'hfam_ui.py'))
    for job in ('job_place', 'job_realign', 'job_auto'):
        if 'hr.%s, hc.%s' % (job, job) not in ui_src:
            bad.append('hfam_ui.py: %s does not hand circular families to hcirc_revit' % job)
    return bad


RULES = [rule_compiles, rule_xaml_parses, rule_theme_defaults_dark, rule_clr_first, rule_assemblies_referenced,
         rule_no_staticresource, rule_resource_keys, rule_palette_matches_theme,
         rule_findname, rule_banned_python, rule_no_duplicate_defs, rule_loader_thin,
         rule_changelog_version, rule_transparent_window, rule_handlers_exist,
         rule_enums_late, rule_version_top_right, rule_no_python_attrs_on_wpf,
         rule_raise_status_read, rule_hosting_by_connector, rule_egg_on_logo_only,
         rule_tab_buttons_reachable, rule_window_fits_tools, rule_floor_panel_in_sync, rule_floor_twins,
         rule_shrink_button, rule_every_window_has_drawer, rule_drawer_releases_animation,
         rule_escape_never_closes, rule_circular_separate]


def run(root, quiet=False):
    total = 0
    for r in RULES:
        for k in [m for m in list(sys.modules) if m.startswith('fha_')]:
            del sys.modules[k]
        bad = r(root)
        total += len(bad)
        if not quiet:
            print('%-30s %s' % (r.__name__, 'ok' if not bad else 'FAIL'))
            for b in bad:
                print('    ' + b)
    return total


def selftest():
    def edit(name, fn):
        def go(root):
            p = os.path.join(root, name)
            with open(p, 'rb') as f:
                s = f.read().decode('utf-8')
            with open(p, 'wb') as f:
                f.write(fn(s).encode('utf-8'))
        return go
    breaks = [
        ('syntax error', edit('fha_revit.py', lambda s: s + '\ndef (:\n'), 'rule_compiles'),
        ('xaml comment --', edit('HangerAutomation.xaml', lambda s: s.replace('<Grid x:Name="GripLayer"/>', '<!-- a -- b --><Grid x:Name="GripLayer"/>')), 'rule_xaml_parses'),
        ('import order', edit('fha_ui.py', lambda s: s.replace('import fha_clr  # noqa: F401  (must be first)\n', '', 1).replace('import os\n', 'from System.IO import File\nimport os\nimport fha_clr\n', 1)), 'rule_clr_first'),
        ('missing assembly', edit('fha_clr.py', lambda s: s.replace("'PresentationFramework', ", '').replace("'PresentationCore', ", '').replace("'WindowsBase'", '')), 'rule_assemblies_referenced'),
        ('StaticResource', edit('HangerAutomation.xaml', lambda s: s.replace('DynamicResource Chip', 'StaticResource Chip', 1)), 'rule_no_staticresource'),
        ('missing key', edit('HangerAutomation.xaml', lambda s: s.replace('DynamicResource Chip', 'DynamicResource Nope', 1)), 'rule_resource_keys'),
        ('palette key', edit('Theme.xaml', lambda s: s.replace('x:Key="SelBrush"', 'x:Key="SelXBrush"')), 'rule_palette_matches_theme'),
        ('findname', edit('fha_window.py', lambda s: s.replace("self.c('LogBox')", "self.c('NoSuchBox')", 1)), 'rule_findname'),
        ('f-string', edit('fha_core.py', lambda s: s + '\nx = f"{1}"\n'), 'rule_banned_python'),
        ('duplicate def', edit('fha_core.py', lambda s: s + '\ndef plural(n):\n    return 1\n'), 'rule_no_duplicate_defs'),
        ('fat loader', edit('script.py', lambda s: s + '\n' * 90), 'rule_loader_thin'),
        ('changelog', edit('CHANGELOG.md', lambda s: s.replace('## ' + __import__('re').search(r"__version__ = u'([\d.]+)'", open(os.path.join(HERE, 'fha_core.py')).read()).group(1), '## 0.0.0')), 'rule_changelog_version'),
        ('transparent', edit('HangerAutomation.xaml', lambda s: s.replace('WindowStyle="None" ', '')), 'rule_transparent_window'),
        ('handler missing', edit('fha_window.py', lambda s: s.replace('def _cycle_theme', 'def _cycle_theme_x')), 'rule_handlers_exist'),
        ('no version', edit('HangerAutomation.xaml', lambda s: s.replace('x:Name="VerTxt"', 'x:Name="VerX"')), 'rule_version_top_right'),
        ('1.0.0 crash', edit('fha_window.py', lambda s: s.replace('        self.chrome = ui.Chrome(self.win)\n', '        self.chrome = ui.Chrome(self.win)\n        self.win._full = False\n', 1)), 'rule_no_python_attrs_on_wpf'),
        ('chrome attr', edit('fha_ui.py', lambda s: s.replace('            t.Opacity = 0.0\n', '            t.Opacity = 0.0\n            t.side = sx\n', 1)), 'rule_no_python_attrs_on_wpf'),
        ('raise ignored', edit('fha_window.py', lambda s: s.replace("answer = str(_STATE['evt'].Raise())", "_STATE['evt'].Raise()\n            answer = 'Accepted'")), 'rule_raise_status_read'),
        ('index hosting', edit('fha_revit.py', lambda s: s.replace("places.append((elems[loc['id']], rec['cobj'][loc['entry']]", "places.append((elems[loc['id']], loc['entry']")), 'rule_hosting_by_connector'),
        ('egg on window', edit('fha_ui.py', lambda s: s.replace('attach(logo, **_kwargs(attach, offered))', 'attach(win, logo)')), 'rule_egg_on_logo_only'),
        ('egg no logo', edit('fha_window.py', lambda s: s.replace("ui.attach_egg(self.win, self.c('Logo'),", "ui.attach_egg(self.win, None,")), 'rule_egg_on_logo_only'),
        ('missing checkbox', edit('HangerAutomation.xaml', lambda s: s.replace('x:Name="ChkReplace"', 'x:Name="ChkReplaceX"')), 'rule_findname'),
        ('auto button buried', edit('HangerAutomation.xaml', lambda s: s.replace('<Button x:Name="BtnFamAuto" HorizontalAlignment="Right"', '<Button x:Name="BtnFamAuto"')), 'rule_tab_buttons_reachable'),
        ('tool cannot fold', edit('HangerAutomation.xaml', lambda s: s.replace('x:Name="BodyFamDims"', 'x:Name="BodyDims"')), 'rule_tab_buttons_reachable'),
        ('named chevron transform', edit('HangerAutomation.xaml', lambda s: s.replace('Data="M0,0 L6,6 L12,0"/>', 'Data="M0,0 L6,6 L12,0"><Path.RenderTransform><RotateTransform x:Name="Spin"/></Path.RenderTransform></Path>', 1)), 'rule_tab_buttons_reachable'),
        ('family tab cannot scroll', edit('HangerAutomation.xaml', lambda s: s.replace('<ScrollViewer x:Name="FamPanel"', '<ScrollViewer x:Name="FamPanelX"')), 'rule_tab_buttons_reachable'),
        ('no fit on open', edit('fha_window.py', lambda s: s.replace('        self.win.ContentRendered += self.fit\n', '')), 'rule_window_fits_tools'),
        ('no fit on tab switch', edit('fha_window.py', lambda s: s.replace("        self._apply_tab()\n        self.fit()", "        self._apply_tab()")), 'rule_window_fits_tools'),
        ('fold leaves window', edit('hfam_ui.py', lambda s: s.replace('on_resize=self.o.resize_for_fold', 'on_resize=None')), 'rule_window_fits_tools'),
        ('fold resize uncapped', edit('fha_window.py', lambda s: s.replace('float(wa_h) * ui.MAX_SCREEN', 'float(wa_h)')), 'rule_window_fits_tools'),
        ('floor panel edited by hand', edit('HangerAutomation.xaml', lambda s: s.replace('Text="Place support on service"', 'Text="Place a support"')), 'rule_floor_panel_in_sync'),
        ('hanger panel changed, floor not rebuilt', edit('HangerAutomation.xaml', lambda s: s.replace('Text="Place hanger on service"', 'Text="Place a hanger"')), 'rule_floor_panel_in_sync'),
        ('floor twin missing', edit('HangerAutomation.xaml', lambda s: s.replace('x:Name="ChkFlrLockAuto"', 'x:Name="ChkFlrLockAutoX"')), 'rule_floor_twins'),
        ('shrink button not wired', edit('fha_window.py', lambda s: s.replace("        self.c('ShrinkBtn').Click += self._shrink_click\n", "")), 'rule_shrink_button'),
        ('expand arrow not green', edit('HangerAutomation.xaml', lambda s: s.replace('Visibility="Collapsed" Stroke="{DynamicResource GreenBrush}"', 'Visibility="Collapsed" Stroke="{DynamicResource MutedBrush}"')), 'rule_shrink_button'),
        ('Theme.xaml default not the dark palette', edit('Theme.xaml', lambda s: s.replace('x:Key="WinBgBrush" Color="#3C4454"', 'x:Key="WinBgBrush" Color="#232326"')), 'rule_theme_defaults_dark'),
        ('dialog with no drawer', edit('hview_ui.py', lambda s: s.replace("        self.drawer = ui.dialog_drawer(self, owner, self.c('PromptHeader')", "        self.drawer = None and (self, owner, self.c('PromptHeader')")), 'rule_every_window_has_drawer'),
        ('dialog with no shrink button', edit('HangerPrompt.xaml', lambda s: s.replace('x:Name="PromptShrinkBtn"', 'x:Name="PromptShrinkB"')), 'rule_shrink_button'),
        ('drawer holds the animation', edit('fha_ui.py', lambda s: s.replace("                win.BeginAnimation(Window.TopProperty, None)\n", "")), 'rule_drawer_releases_animation'),
        ('drawer stuck with no animation', edit('fha_ui.py', lambda s: s.replace("            finish()   # no animation: land at once", "            pass")), 'rule_drawer_releases_animation'),
        ('Escape closes the tool', edit('fha_window.py', lambda s: s.replace("            # Escape never closes the tool: it is pressed to leave Revit picks", "            if k == 'Escape':\n                self.close()")), 'rule_escape_never_closes'),
        ('circ in rect path', edit('hfam_revit.py', lambda s: s.replace('def fit_to_duct(', 'import hcirc_core\n\n\ndef fit_to_duct(', 1)), 'rule_circular_separate'),
        ('circ not dispatched', edit('hfam_ui.py', lambda s: s.replace('self._run(hr.job_auto, hc.job_auto)', 'self._run(hr.job_auto)')), 'rule_circular_separate'),
        ('IntegerValue', edit('fha_revit.py', lambda s: s + '\ndef x(e):\n    return e.Id.IntegerValue\n'), 'rule_banned_python'),
    ]
    missed = 0
    for name, brk, rule in breaks:
        tmp = tempfile.mkdtemp()
        try:
            for n in PY + XAML + ['CHANGELOG.md']:
                shutil.copy(os.path.join(HERE, n), tmp)
            brk(tmp)
            fn = [r for r in RULES if r.__name__ == rule][0]
            for k in [m for m in list(sys.modules) if m.startswith('fha_')]:
                del sys.modules[k]
            sys.path[:] = [p for p in sys.path if p != tmp]
            hit = len(fn(tmp)) > 0
        except Exception as ex:
            hit = True
        finally:
            shutil.rmtree(tmp, True)
        print('%-18s %-30s %s' % (name, rule, 'caught' if hit else 'MISSED'))
        if not hit:
            missed += 1
    return missed


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(1 if selftest() else 0)
    sys.exit(1 if run(HERE) else 0)
