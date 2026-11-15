# -*- coding: utf-8 -*-
"""Building the output folder from project and sheet parameters.

No WPF and no Revit in here either - the token expansion is a plain function
over a lookup, tested on the bench the same way the naming rules are.

The user gives a **root folder** they browse to, plus a **token string**:

    {Project Number}\\{BGL_Sheet Discipline}\\{Sheet Issue Date}

Every ``{...}`` is looked up as a parameter on the sheet, falling back to the
project information, and each resulting segment is sanitised as a folder name.
A token with no value collapses to a placeholder rather than an empty folder
level, because an empty level silently moves every file up a directory and
nobody notices until a hundred PDFs are in the wrong place.
"""

import os
import re

import ps_naming


TOKEN = re.compile(r'\{([^{}]*)\}')

EMPTY_PLACEHOLDER = u'_unset'


# ==========================================================================
# date and time
#
# Two spellings, on purpose.
#
# The named ones - {Year}, {Month}, {Hour} - are what the picker inserts,
# because they cannot be misread. The strftime ones are there for people who
# already know them, and they follow strftime exactly: %m is the MONTH and %M
# is the MINUTE. That trap is the whole reason the named tokens exist and the
# whole reason the picker never offers the percent ones.
# ==========================================================================

NAMED_TIME_TOKENS = [
    (u'Year', '%Y', u'2026'),
    (u'Year Short', '%y', u'26'),
    (u'Month', '%m', u'09'),
    (u'Month Name', '%B', u'September'),
    (u'Month Short', '%b', u'Sep'),
    (u'Day', '%d', u'28'),
    (u'Day Name', '%A', u'Monday'),
    (u'Hour', '%H', u'14'),
    (u'Minute', '%M', u'05'),
    (u'Second', '%S', u'32'),
    (u'Date', '%Y-%m-%d', u'2026-09-28'),
    (u'Time', '%H%M', u'1405'),
    (u'Date Time', '%Y-%m-%d %H%M', u'2026-09-28 1405'),
    (u'Week', '%W', u'39'),
]

# The percent codes accepted in a token string, for anyone who reaches for
# them out of habit. Everything here is plain strftime, with one addition:
# %h is not a strftime code, but people type it meaning "hour", so it is
# accepted as an alias for %H rather than left to pass through as literal
# text and quietly land in a folder name.
STRFTIME_CODES = set(['%Y', '%y', '%m', '%b', '%B', '%d', '%a', '%A',
                      '%H', '%I', '%M', '%S', '%p', '%j', '%W'])
STRFTIME_ALIASES = {'%h': '%H'}

_STRFTIME = re.compile(r'%[A-Za-z%]')


def _now():
    """Plain Python, not System.DateTime.

    Using .NET here made the whole date and time feature impossible to test
    on the bench, which for something with a %m/%M trap in it is exactly
    backwards. ``datetime`` is in IronPython 2.7 and 3 and in CPython, so
    the bench runs the same code the tool runs.
    """
    try:
        import datetime
        return datetime.datetime.now()
    except Exception:
        return None


def _format_now(pattern):
    moment = _now()
    if moment is None or not pattern:
        return u''
    try:
        return u'{0}'.format(moment.strftime(pattern))
    except Exception:
        return u''


def time_token(name):
    """The value for a named date or time token, or None if it is not one."""
    wanted = u'{0}'.format(name or u'').strip().lower()
    for label, pattern, _sample in NAMED_TIME_TOKENS:
        if label.lower() == wanted:
            return _format_now(pattern)
    return None


def expand_strftime(text):
    """Replace %Y, %m, %d, %H, %M, %S and friends before the {tokens} run.

    strftime's own meanings, so **%m is the month and %M is the minute**.
    That is the trap the named tokens exist to avoid, and it is not worth
    inventing a third convention here to soften it.
    """
    body = u'{0}'.format(text or u'')
    if '%' not in body:
        return body

    def swap(match):
        code = match.group(0)
        if code == '%%':
            return u'%'
        code = STRFTIME_ALIASES.get(code, code)
        if code not in STRFTIME_CODES:
            return match.group(0)
        return _format_now(code)

    return _STRFTIME.sub(swap, body)


def token_catalogue(parameter_pairs):
    """Everything the folder picker offers: date and time first, then params.

    Date and time lead because they are the ones nobody can guess the
    spelling of, and because a parameter list is long enough to bury them.
    """
    entries = []
    for label, _pattern, sample in NAMED_TIME_TOKENS:
        entries.append((label, u'Date and time', sample))
    for name, group in (parameter_pairs or []):
        entries.append((name, group, u''))
    return entries


def tokens_in(text):
    """Every token name appearing in a token string, in order, deduplicated."""
    found = []
    for match in TOKEN.finditer(u'{0}'.format(text or u'')):
        name = match.group(1).strip()
        if name and name not in found:
            found.append(name)
    return found


def expand(token_text, lookup, placeholder=EMPTY_PLACEHOLDER):
    """Turn a token string into a relative path, one sanitised segment a level.

    Both ``\\`` and ``/`` count as level separators, since people type
    whichever they are used to. Empty levels are dropped; a level that exists
    but whose token resolved to nothing becomes the placeholder, so the depth
    of the tree never depends on whether a parameter happened to be filled in.
    """
    text = u'{0}'.format(token_text or u'').strip()
    if not text:
        return u''

    text = expand_strftime(text)

    def replace(match):
        name = match.group(1).strip()
        if not name:
            return u''
        stamped = time_token(name)
        if stamped is not None:
            return stamped
        try:
            value = lookup(name)
        except Exception:
            value = u''
        value = u'' if value is None else u'{0}'.format(value).strip()
        return value

    filled = TOKEN.sub(replace, text)
    raw_levels = re.split(r'[\\/]+', filled)
    levels = []
    for level in raw_levels:
        level = level.strip()
        if not level:
            continue
        levels.append(ps_naming.sanitise(level, placeholder))

    # A level that was nothing but an unresolved token comes back empty above
    # and is dropped, which would flatten the tree. Re-walk the original
    # levels so a level that was asked for always exists.
    original_levels = [lvl for lvl in re.split(r'[\\/]+', text) if lvl.strip()]
    if len(levels) < len(original_levels):
        levels = []
        for original in original_levels:
            piece = TOKEN.sub(replace, original).strip()
            levels.append(ps_naming.sanitise(piece, placeholder)
                          if piece else placeholder)
    return os.path.join(*levels) if levels else u''


def full_folder(root, token_text, lookup, format_folder=None):
    """Root + expanded tokens + an optional per-format folder."""
    parts = [u'{0}'.format(root or u'').strip()]
    relative = expand(token_text, lookup)
    if relative:
        parts.append(relative)
    if format_folder:
        parts.append(ps_naming.sanitise(format_folder, u'export'))
    parts = [part for part in parts if part]
    if not parts:
        return u''
    return os.path.normpath(os.path.join(*parts))


def is_series_token(name, series_param):
    """Whether a folder token is the sheet series: the parameter Setup names
    as the series, or anything called Sheet Series when Setup names none."""
    name = u'{0}'.format(name or u'').strip().lower()
    wanted = u'{0}'.format(series_param or u'').strip().lower()
    if wanted:
        return name == wanted
    return u'sheet series' in name


def folder_before(root, token_text, job_folder, series_param):
    """The folder a run's files sit under, cut off above the series level.

    ``{Date}\\{BGL_Sheet Series}\\PDF`` writes into one folder per series
    under the dated one, and the dated one is the issue - the folder
    somebody opening the export wants to land in. Taken from a folder the
    run actually built rather than by expanding the tokens again: a date
    or time token expanded a minute later is a different folder.

    u'' when the folder levels have no series token, or the job's folder
    does not sit under the root - the caller falls back to the folder
    above the formats.
    """
    levels = [level for level in re.split(r'[\\/]+',
                                          u'{0}'.format(token_text or u''))
              if level.strip()]
    cut = None
    for index, level in enumerate(levels):
        if [name for name in tokens_in(level)
                if is_series_token(name, series_param)]:
            cut = index
            break
    if cut is None:
        return u''
    root_parts = [part for part in re.split(r'[\\/]+',
                                            u'{0}'.format(root or u'').strip())
                  if part]
    job_parts = [part for part in re.split(r'[\\/]+',
                                           u'{0}'.format(job_folder or u''))
                 if part]
    if not root_parts or len(job_parts) < len(root_parts) + cut:
        return u''
    if [part.lower() for part in job_parts[:len(root_parts)]] != \
            [part.lower() for part in root_parts]:
        return u''
    text = u'{0}'.format(job_folder)
    separator = u'\\' if u'\\' in text or u'/' not in text else u'/'
    kept = job_parts[:len(root_parts) + cut]
    joined = separator.join(kept)
    if text.startswith(u'\\\\'):
        joined = u'\\\\' + joined          # a UNC share keeps its two
    elif text.startswith(u'/'):
        joined = u'/' + joined
    return joined


def issue_cut(root, token_text, folders, series_param):
    """folder_before for the first of a run's folders that gives one."""
    for folder in folders or ():
        found = folder_before(root, token_text, folder, series_param)
        if found:
            return found
    return u''


def project_folder(root, token_text, lookup, series_param):
    """The folder the tokens name without any sheet: the register alone.

    With no sheets ticked there is no sheet to resolve the series or a
    discipline against, but the levels above them - project name, date and
    time - are the issue folder an Export run with sheets would have used.
    Levels are taken from the top down and the walk stops at the series
    level, or at the first level with a token the project cannot fill (a
    sheet parameter), so no ``_unset`` folder is ever made for the
    register to sit in.
    """
    root = u'{0}'.format(root or u'').strip()
    if not root:
        return u''
    kept = []
    for level in re.split(r'[\\/]+', u'{0}'.format(token_text or u'')):
        if not level.strip():
            continue
        names = tokens_in(level)
        if [name for name in names if is_series_token(name, series_param)]:
            break
        resolvable = True
        for name in names:
            if time_token(name) is not None:
                continue
            try:
                value = lookup(name)
            except Exception:
                value = u''
            if not u'{0}'.format(value or u'').strip():
                resolvable = False
                break
        if not resolvable:
            break
        expanded = expand(level, lookup)
        if not expanded:
            break
        kept.append(expanded)
    return os.path.normpath(os.path.join(root, *kept)) if kept else root


def ensure(folder):
    """Create a folder if it is not there. (created, error_text)."""
    if not folder:
        return False, u'no folder given'
    try:
        if os.path.isdir(folder):
            return True, u''
        os.makedirs(folder)
        return True, u''
    except Exception as err:
        return False, u'{0}'.format(err)


def tidy_folder(path):
    """A folder path in a form two of them can be compared in.

    Separators squared up, trailing ones dropped, case folded. Not
    os.path.abspath and not os.path.normcase: both of those answer for
    the platform the check is running on, and the bench runs on Linux
    while the tool runs on Windows - so a comparison built on them
    passes here and fails there, which is the worst of both.
    """
    text = u'{0}'.format(path or u'').strip().replace(u'/', u'\\')
    while len(text) > 3 and text.endswith(u'\\'):
        text = text[:-1]
    return text.lower()


def same_folder(first, second):
    """Whether two paths name the same folder."""
    first = tidy_folder(first)
    return bool(first) and first == tidy_folder(second)


def inside_folder(inner, outer):
    """Whether one folder sits under another, or is the same folder."""
    inner, outer = tidy_folder(inner), tidy_folder(outer)
    if not inner or not outer:
        return False
    return inner == outer or inner.startswith(outer.rstrip(u'\\') + u'\\')


def writable(folder):
    """Whether a file can actually be written here, by trying it.

    Asking the file system about permissions is not the same question as
    asking whether this process can write, and a read-only network share
    answers the first one cheerfully.
    """
    try:
        made, error = ensure(folder)
        if not made:
            return False, error
        probe = os.path.join(folder, '_revobim_write_test.tmp')
        handle = open(probe, 'wb')
        try:
            handle.write(b'x')
        finally:
            handle.close()
        os.remove(probe)
        return True, u''
    except Exception as err:
        return False, u'{0}'.format(err)


def long_path_risk(path):
    """True where the finished path is close enough to 260 to be a problem.

    Revit and the print drivers do not all handle long paths, and the failure
    when they do not is a file that quietly does not appear.
    """
    try:
        return len(u'{0}'.format(path)) >= 240
    except Exception:
        return False


def unique_on_disk(folder, base_name, extension):
    """A path in this folder that nothing is using, adding (2), (3) if needed."""
    candidate = os.path.join(folder, base_name + extension)
    if not os.path.exists(candidate):
        return candidate
    index = 2
    while index < 1000:
        candidate = os.path.join(
            folder, u'{0} ({1}){2}'.format(base_name, index, extension))
        if not os.path.exists(candidate):
            return candidate
        index += 1
    return candidate
