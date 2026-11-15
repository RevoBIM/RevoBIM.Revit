# -*- coding: utf-8 -*-
"""RevoBIM PY - Panel Template Mngr: version, settings and helpers.

The version number lives here rather than in either pushbutton, so both buttons
and every window read the same value and bumping it is a one line edit.

Runs on IronPython 2.7 and IronPython 3: no f-strings, no print statements,
`//` for integer division, `.format()` for interpolation.
"""

import os
import re

import pstm_clr                                                  # noqa: F401
import clr

__version__ = "1.9.0"

TOOL_NAME = "Panel Template Mngr"


# ---------------------------------------------------------------------------
# ElementId across releases
# ---------------------------------------------------------------------------

def eid_value(element_id):
    """ElementId.IntegerValue was deprecated in Revit 2024 and removed in 2026.

    Never touch it directly - prefer .Value (Int64) and fall back.
    """
    if element_id is None:
        return 0
    try:
        return int(element_id.Value)
    except Exception:
        pass
    try:
        return int(element_id.IntegerValue)
    except Exception:
        return 0


def same_id(a, b):
    return eid_value(a) == eid_value(b) and eid_value(a) != 0


def as_id(thing):
    """Accept an Element, an ElementId or None and hand back an ElementId.

    Several panel schedule calls are documented only as "retrieves the panel" or
    "retrieves the template" without saying whether that is the element or its
    id, and the answer has not been the same in every release.
    """
    if thing is None:
        return None
    try:
        if thing.GetType().Name == 'ElementId':
            return thing
    except Exception:
        pass
    try:
        return thing.Id
    except Exception:
        return thing


# ---------------------------------------------------------------------------
# Reflection.  Several panel schedule API calls have changed shape between
# releases and are not documented consistently, so the arguments are matched to
# the method's own parameter names at run time rather than being hardcoded.
# ---------------------------------------------------------------------------

def _clr_type(obj):
    try:
        return clr.GetClrType(obj.GetType())
    except Exception:
        pass
    try:
        return obj.GetType()
    except Exception:
        return None


def find_methods(obj, method_name):
    t = _clr_type(obj)
    if t is None:
        return []
    try:
        return [m for m in t.GetMethods() if m.Name == method_name]
    except Exception:
        return []


def _match_value(param, values):
    """Pick the value for one method parameter, by name first then by type."""
    pname = (param.Name or '').lower()
    ptype = ''
    try:
        ptype = param.ParameterType.Name
    except Exception:
        pass

    # Name driven - the reliable route, RevitAPI.dll keeps parameter names.
    # Every matching key is considered and the LONGEST wins, with the name as
    # the tie break so two keys of equal length cannot swap places between runs
    # and bind the wrong value.
    matches = [key for key in values if key in pname]
    if matches:
        matches.sort(key=lambda k: (-len(k), k))
        return True, values[matches[0]]

    # type driven fallback
    if ptype == 'Document' and 'document' in values:
        return True, values['document']
    if ptype == 'String' and 'name' in values:
        return True, values['name']
    if ptype == 'PanelConfiguration' and 'config' in values:
        return True, values['config']
    if ptype == 'PanelScheduleType' and 'scheduletype' in values:
        return True, values['scheduletype']
    if ptype == 'PanelSchedulePhaseLoadType' and 'newtype' in values:
        return True, values['newtype']
    if ptype == 'Int32':
        for key in ('numberofslots', 'slots', 'slot'):
            if key in values:
                return True, values[key]
    if ptype == 'ElementId' and 'template' in values:
        return True, values['template']
    if ptype == 'Boolean':
        return True, False
    return False, None


def invoke_named(obj, method_name, values, arg_orders=None):
    """Call a method, matching arguments to its parameter names.

    `values` maps a lower case fragment of a parameter name to the value to
    pass - e.g. {'slot': 36, 'config': PanelConfiguration.OneColumn}.
    `arg_orders` is an optional list of straight positional argument tuples to
    try if reflection finds nothing, so the call still works if the assembly
    was built without parameter names.

    Returns (ok, result_or_error_text).
    """
    import System

    methods = find_methods(obj, method_name)
    # try the overload with the most parameters we can fill first
    methods.sort(key=lambda m: -len(m.GetParameters()))
    errors = []
    for m in methods:
        params = list(m.GetParameters())
        args = []
        usable = True
        for p in params:
            ok, val = _match_value(p, values)
            if not ok:
                usable = False
                break
            args.append(val)
        if not usable:
            continue
        try:
            arr = System.Array[System.Object](list(args))
            return True, m.Invoke(obj, arr)
        except Exception as ex:
            errors.append(str(ex))

    for order in (arg_orders or []):
        try:
            return True, getattr(obj, method_name)(*order)
        except Exception as ex:
            errors.append(str(ex))

    return False, '; '.join(errors) if errors else 'no usable overload found'


def invoke_static_named(clr_type, method_name, values, arg_orders=None):
    """The same argument matching, for a static factory method.

    PanelScheduleTemplate.Create is documented as taking three arguments and
    actually takes four - "Create() takes exactly 4 arguments (3 given)" is what
    Revit says if you believe the documentation.  Rather than guess which fourth
    argument, the method's own parameter list is read and filled.

    Returns (ok, result_or_error_text).
    """
    import System

    if clr_type is None:
        return False, 'the type is not available on this release'
    try:
        methods = [m for m in clr_type.GetMethods()
                   if m.Name == method_name and m.IsStatic]
    except Exception as ex:
        return False, str(ex)
    methods.sort(key=lambda m: -len(m.GetParameters()))

    errors = []
    for method in methods:
        args = []
        usable = True
        for param in method.GetParameters():
            ok, value = _match_value(param, values)
            if not ok or value is None:
                usable = False
                shape = '{0} {1}'.format(
                    getattr(param.ParameterType, 'Name', '?'), param.Name)
                errors.append('{0}({1}): nothing to pass for {2}'.format(
                    method_name, len(method.GetParameters()), shape))
                break
            args.append(value)
        if not usable:
            continue
        try:
            return True, method.Invoke(None, System.Array[System.Object](list(args)))
        except Exception as ex:
            errors.append('{0}({1}): {2}'.format(
                method_name, len(method.GetParameters()), ex))

    for order in (arg_orders or []):
        try:
            return True, getattr(clr_type, method_name)(*order)
        except Exception as ex:
            errors.append(str(ex))

    return False, '; '.join(errors) if errors else 'no usable overload found'


def method_shapes(clr_type, method_name):
    """What a method's overloads actually look like, for a diagnostic."""
    out = []
    try:
        for method in clr_type.GetMethods():
            if method.Name != method_name:
                continue
            bits = []
            for param in method.GetParameters():
                bits.append('{0} {1}'.format(
                    getattr(param.ParameterType, 'Name', '?'), param.Name))
            out.append('{0}({1})'.format(method_name, ', '.join(bits)))
    except Exception:
        pass
    return out


# ---------------------------------------------------------------------------
# Renaming.  Which route works varies with the IronPython version and neither
# reliably raises on failure, so the name is always read back to confirm.
# ---------------------------------------------------------------------------

def element_name(element):
    try:
        n = element.Name
        if n:
            return n
    except Exception:
        pass
    try:
        from Autodesk.Revit.DB import Element
        return Element.Name.GetValue(element) or ''
    except Exception:
        return ''


def set_element_name(element, new_name):
    """Try both routes and confirm by reading the name back."""
    try:
        element.Name = new_name
    except Exception:
        pass
    if element_name(element) == new_name:
        return True
    try:
        from Autodesk.Revit.DB import Element
        Element.Name.SetValue(element, new_name)
    except Exception:
        pass
    return element_name(element) == new_name


def unique_name(base, taken):
    """A name not already in `taken` (a set of lower case names).

    A clash gets "New" on the end, then "New 2" and so on if that clashes too.
    """
    if base.lower() not in taken:
        return base
    candidate = '{0} New'.format(base)
    n = 2
    while candidate.lower() in taken:
        candidate = '{0} New {1}'.format(base, n)
        n += 1
    return candidate


# ---------------------------------------------------------------------------
# Numbers in names
# ---------------------------------------------------------------------------

NUMBER_RE = re.compile(r'\d+')


def numbers_in(text):
    if not text:
        return []
    try:
        return [int(x) for x in NUMBER_RE.findall(str(text))]
    except Exception:
        return []


def extract_template_number(name, rule='largest', keyword='way'):
    """The slot count a template name is advertising.

    'largest'  - the biggest number anywhere in the name (default).  Survives a
                 trailing revision or a year in the name.
    'first'    - the first digit group in the name.
    'keyword'  - only a number immediately followed by the keyword.
    """
    if not name:
        return None
    rule = (rule or 'largest').lower()
    if rule == 'keyword':
        kw = re.escape((keyword or 'way').strip())
        m = re.search(r'(\d+)\s*' + kw, str(name), re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                return None
        return None
    nums = numbers_in(name)
    if not nums:
        return None
    if rule == 'first':
        return nums[0]
    return max(nums)


WAYS_SUFFIX_RE = re.compile(r'[\s_-]*\d+\s*ways?\s*$', re.IGNORECASE)
# not \bmaster\b: an underscore is a word character, so \b never fires in
# "BGL_Master_One Column" - the very shape these templates are named in
MASTER_RE = re.compile(r'(?<![A-Za-z0-9])master(?![A-Za-z0-9])', re.IGNORECASE)
GAP_RE = re.compile(r'\s{2,}')


def drop_master(text):
    """Take the word "Master" out of a name.

    Only the whole word, so "Mastermind" or a panel called "MASTERS" keeps its
    name.  Whatever separators are left over - a doubled space, a trailing
    underscore or dash - are tidied up, because "BGL_Schedule  _ One Column"
    is not a name anybody wanted.
    """
    text = str(text or '')
    out, hits = MASTER_RE.subn('', text)
    if not hits:
        # nothing was taken out, so nothing needs tidying - a name like
        # "Panel - Board" must come back exactly as it went in
        return text
    out = re.sub(r'\(\s*\)|\[\s*\]', '', out)
    out = re.sub(r'[\s_-]*([_-])[\s_-]*', r'\1', out)
    out = GAP_RE.sub(' ', out)
    return out.strip(' _-')


def name_with_ways(base, ways):
    """A duplicate's name: the source's, with "<n> Ways" on the end.

    Replacing the largest number in the name went wrong on a source called
    "BGL_Schedule One Column Master (R2)" - the biggest number there is the
    revision marker, so a 3 way copy came out as "(R3)".  A suffix cannot
    corrupt anything, and an existing ways suffix is replaced rather than
    stacked so duplicating a duplicate does not accumulate them.

    "Master" comes out of the name: the copy is not the master.
    """
    stem = WAYS_SUFFIX_RE.sub('', str(base or '')).rstrip()
    stem = drop_master(stem)
    return '{0} {1} Ways'.format(stem, ways)


# ---------------------------------------------------------------------------
# Renaming a batch of templates
# ---------------------------------------------------------------------------

def rename_find_replace(name, find, replace, match_case=False):
    """Swap one run of text for another inside a name."""
    text = str(name or '')
    if not find:
        return text
    if match_case:
        return text.replace(find, replace or '')
    return re.sub(re.escape(find), lambda m: replace or '', text,
                  flags=re.IGNORECASE)


def rename_affix(name, prefix='', suffix=''):
    """Put something on the front, the back, or both."""
    return '{0}{1}{2}'.format(prefix or '', str(name or ''), suffix or '')


def preview_rename(names, find='', replace='', match_case=False,
                   prefix='', suffix='', strip_master=False):
    """What a rename would do, before anything is written.

    Returns a list of (old, new, note).  A note is set where the result would
    collide with a name already in the list or be empty - both of which Revit
    would refuse, and better said here than found out halfway through a batch.
    """
    out = []
    seen = {}
    for name in names:
        new = str(name or '')
        if strip_master:
            new = drop_master(new)
        if find:
            new = rename_find_replace(new, find, replace, match_case)
        new = rename_affix(new, prefix, suffix).strip()
        note = ''
        if not new:
            note = 'that would leave it with no name'
        elif new.lower() in seen and seen[new.lower()] != name:
            note = 'clashes with "{0}"'.format(seen[new.lower()])
        else:
            seen[new.lower()] = name
        out.append((name, new, note))
    return out


def replace_number_in_name(name, new_number, rule='largest', keyword='way'):
    """Swap the slot number in a template name for a new one.

    If the name carries no number the count is appended instead, so a duplicate
    always ends up named for the number of slots it was given.
    """
    text = str(name or '')
    old = extract_template_number(text, rule, keyword)
    if old is None:
        return '{0} {1} Slot'.format(text.rstrip(), new_number)
    # replace the specific occurrence rather than every digit group
    out = []
    replaced = [False]

    def _sub(match):
        if not replaced[0] and int(match.group(0)) == old:
            replaced[0] = True
            return str(new_number)
        return match.group(0)

    out = NUMBER_RE.sub(_sub, text)
    if not replaced[0]:
        return '{0} {1} Slot'.format(text.rstrip(), new_number)
    return out


# ---------------------------------------------------------------------------
# Auto Assign maths
# ---------------------------------------------------------------------------

def parse_ways(text):
    """The way terms in a value like '12', '8+8' or '8 + 4 ways'."""
    if text is None:
        return []
    return numbers_in(text)


def calc_slots(ways_text, phases):
    """Ways x phases.

    Every term in the ways value is added up first, then multiplied by the
    number of phases: '12 ways' on 3 phases is 12 x 3 = 36 slots, and '8+8 ways'
    on 3 phases is (8 + 8) x 3 = 48.  There is deliberately only one rule.

    Returns (slots, note).  slots is None when it cannot be worked out.
    """
    terms = parse_ways(ways_text)
    if not terms:
        return None, 'no number in the ways parameter'
    try:
        ph = int(phases)
    except Exception:
        return None, 'no number in the phases parameter'
    if ph <= 0:
        return None, 'phases is zero'
    return sum(terms) * ph, ''


SLOTS_PER_WAY = 3


def slots_per_way(single_phase=False):
    """How many slots one way takes up.

    Three on a three phase board, one on a single phase board - a single phase
    way occupies one slot, so a 12 way single phase panel is 12 slots, not 36.
    """
    return 1 if single_phase else SLOTS_PER_WAY


def ways_from_slots(slots, per_way=None):
    """A template's name carries ways, not slots: 36 slots is a 12 way board."""
    step = per_way or SLOTS_PER_WAY
    try:
        return int(slots) // int(step)
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Settings.  Plain key=value text under %APPDATA%\RevoBIM\, not JSON - no
# dependency on a module whose availability varies with the IronPython engine,
# and it stays readable and hand editable.  A missing or damaged file falls back
# to the defaults key by key, and keys from an older version are ignored rather
# than breaking the load.
# ---------------------------------------------------------------------------

DEFAULTS = {
    'theme': 'dark',
    'ways_param': 'BGL_Number of Ways',
    'phases_param': 'BGL_Number of Phases',
    'phases_fallback': '3',
    'name_number_rule': 'largest',
    'name_number_keyword': 'way',
    'default_config': 'OneColumn',
    'default_schedule_type': 'Branch Panel',
    # a pipe separated list, so there can be as many columns as wanted
    'columns': '',
    'slot_step': '3',
    'slot_min': '3',
    'slot_max': '120',
    'match_schedule_type': '1',
    'confirm_apply': '1',
    'rebuild_schedule': '1',
    'window_width': '1280',
    'window_height': '760',
}


def settings_dir():
    base = os.getenv('APPDATA') or os.path.expanduser('~')
    return os.path.join(base, 'RevoBIM')


def settings_path():
    # Deliberately still the old long name.  The tool was renamed to Panel
    # Template Mngr in 1.7.1; renaming this file with it would have quietly
    # thrown away everybody's chosen parameters and column set, because a
    # missing file falls back to the defaults without complaining.  Nobody
    # sees this name, so there is nothing to gain by tidying it.
    return os.path.join(settings_dir(), 'panel_schedule_template_manager.txt')


def load_settings():
    values = dict(DEFAULTS)
    path = settings_path()
    try:
        if os.path.isfile(path):
            handle = open(path, 'r')
            try:
                for line in handle:
                    line = line.strip()
                    if not line or line.startswith('#') or '=' not in line:
                        continue
                    key, val = line.split('=', 1)
                    key = key.strip()
                    # keys from an older version are ignored, not fatal
                    if key in DEFAULTS:
                        values[key] = val.strip()
            finally:
                handle.close()
    except Exception:
        return dict(DEFAULTS)
    return values


def save_settings(values):
    path = settings_path()
    try:
        if not os.path.isdir(settings_dir()):
            os.makedirs(settings_dir())
        handle = open(path, 'w')
        try:
            handle.write('# RevoBIM PY - Panel Template Mngr\n')
            handle.write('# version {0}\n'.format(__version__))
            for key in sorted(DEFAULTS.keys()):
                handle.write('{0}={1}\n'.format(key, values.get(key, DEFAULTS[key])))
        finally:
            handle.close()
        return True
    except Exception:
        return False


def as_int(value, fallback=0):
    try:
        return int(str(value).strip())
    except Exception:
        return fallback


def as_bool(value, fallback=False):
    text = str(value).strip().lower()
    if text in ('1', 'true', 'yes', 'on'):
        return True
    if text in ('0', 'false', 'no', 'off'):
        return False
    return fallback


def initial_columns(settings):
    """The parameter columns the table opens with.

    Blank means "not chosen yet", and the first two then take the ways and
    phases parameters from Settings - the two most worth seeing beside the
    template a panel is on.
    """
    raw = settings.get('columns', '')
    names = raw.split('|') if raw else []
    if not names:
        names = [settings.get('ways_param', ''),
                 settings.get('phases_param', ''), '', '']
    while len(names) < 2:
        names.append('')
    return names


def columns_after_settings(names, settings):
    """Saving Settings repoints the first two columns at ways and phases."""
    names = list(names)
    while len(names) < 2:
        names.append('')
    names[0] = settings.get('ways_param', '') or names[0]
    names[1] = settings.get('phases_param', '') or names[1]
    return names


def slot_options(settings, per_way=None):
    """The list of slot counts the duplicator offers.

    On three phase it is the multiples-of-N from Settings.  On single phase a
    way is one slot, so the list is every whole number - 1, 2, 3, 4 - and it
    starts at 1, not at the Settings minimum.  That minimum is written in slots
    for three phase boards, and applying it here would silently hide every
    single phase board smaller than three ways.
    """
    step = int(per_way) if per_way else max(1, as_int(settings.get('slot_step'), 3))
    step = max(1, step)
    low = as_int(settings.get('slot_min'), 3)
    if step == 1:
        low = 1
    low = max(step, low)
    high = max(low, as_int(settings.get('slot_max'), 120))
    first = ((low + step - 1) // step) * step
    out = []
    n = first
    while n <= high:
        out.append(n)
        n += step
    return out
