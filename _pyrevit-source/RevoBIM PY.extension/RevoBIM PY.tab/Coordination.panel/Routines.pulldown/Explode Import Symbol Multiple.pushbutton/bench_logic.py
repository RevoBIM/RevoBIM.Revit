# -*- coding: utf-8 -*-
"""Logic bench for Explode Import Symbol Multiple (plain CPython).

    python bench_logic.py             run every check
    python bench_logic.py --selftest  break the logic on purpose, prove each check fires
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import eim_core  # noqa: E402


class _Id(object):
    def __init__(self, value, legacy=False):
        if legacy:
            self.IntegerValue = value
        else:
            self.Value = value


def run_plan(plan, script):
    """script: list of (dt, exists, button). Returns the actions in order."""
    now = 0.0
    actions = []
    for dt, exists, button in script:
        now += dt
        actions.append(plan.tick(now, exists, button)[0])
    return actions


# ==========================================================================
# Checks - each returns a list of failure strings
# ==========================================================================

def check_settings():
    bad = []
    s = eim_core.parse_settings(u'theme=light\nlast_mode=full\ndebug=0\nnonsense\nselect_results=yes\nx=y=z')
    if s[u'theme'] != u'light' or s[u'last_mode'] != u'full' or s[u'debug'] != u'0':
        bad.append('settings: saved values not read back')
    if s[u'select_results'] != u'1':
        bad.append('settings: a damaged flag did not fall back to its default')
    again = eim_core.parse_settings(eim_core.dump_settings(s))
    if again != s:
        bad.append('settings: dump/parse round trip changed values')
    if eim_core.parse_settings(u'')[u'theme'] != u'follow':
        bad.append('settings: theme must follow the canvas by default')
    if eim_core.parse_settings(u'theme=purple')[u'theme'] != u'follow':
        bad.append('settings: unknown theme not reset')
    if eim_core.parse_settings(u'last_mode=a=b')[u'last_mode'] != u'partial':
        bad.append('settings: value with = not split on the first = only')
    return bad


def check_theme():
    bad = []
    r = eim_core.resolve_theme
    if r(u'follow', True) != u'dark' or r(u'follow', False) != u'light':
        bad.append('theme: follow does not track the canvas')
    if r(u'follow', None) != u'dark':
        bad.append('theme: unknown canvas should fall back to dark')
    if r(u'light', True) != u'light' or r(u'dark', False) != u'dark':
        bad.append('theme: a fixed choice is overridden by the canvas')
    seq, cur = [], u'follow'
    for _ in range(3):
        cur = eim_core.next_theme_setting(cur)
        seq.append(cur)
    if seq != [u'dark', u'light', u'follow']:
        bad.append('theme: chip does not cycle Auto > Dark > Light > Auto ({0})'.format(seq))
    if eim_core.theme_chip_label(u'follow') != u'Auto':
        bad.append('theme: follow chip should read Auto')
    return bad


def check_ids():
    bad = []
    if eim_core.eid_value(_Id(5000000001)) != 5000000001:
        bad.append('ids: .Value (Int64, Revit 2026+) not read')
    if eim_core.eid_value(_Id(42, legacy=True)) != 42:
        bad.append('ids: legacy fallback not read')
    if eim_core.eid_value(None) != 0:
        bad.append('ids: None not handled')
    return bad


def check_classify():
    bad = []
    items = [
        {'key': 1, 'is_import': True, 'is_linked': False, 'pinned': False, 'name': u'a.dwg'},
        {'key': 2, 'is_import': True, 'is_linked': True, 'pinned': False, 'name': u'b.dwg'},
        {'key': 3, 'is_import': False},
        {'key': 4, 'is_import': True, 'is_linked': False, 'pinned': True, 'name': u'c.dwg'},
    ]
    c = eim_core.classify(items)
    if c['explode'] != [1, 4]:
        bad.append('classify: explode list wrong {0}'.format(c['explode']))
    if c['linked'] != [2]:
        bad.append('classify: linked CAD must be skipped, never exploded')
    if c['other'] != 1 or c['pinned'] != [4]:
        bad.append('classify: other/pinned counts wrong')
    head, detail = eim_core.summary_lines(c)
    if head != u'2 import symbols selected' or u'linked' not in detail:
        bad.append('classify: summary wrong ({0} / {1})'.format(head, detail))
    head0, _ = eim_core.summary_lines(eim_core.classify([]))
    if head0 != u'No import symbols selected':
        bad.append('classify: empty selection summary wrong')
    return bad


def check_ribbon_match():
    bad = []
    m = eim_core.ribbon_item_matches
    pid = u'Dialog_Essentials_ImportInstanceExplode:Control_Essentials_ImportPartialExplode'
    fid = u'Dialog_Essentials_ImportInstanceExplode:Control_Essentials_ImportExplode'
    flyp = pid + u'_RibbonListButton_FlyoutButtonExecute'
    if not m(u'partial', pid, u'') or not m(u'full', fid, u''):
        bad.append('ribbon: journal ids not matched')
    if m(u'full', pid, u'Full Explode') or m(u'full', flyp, u''):
        bad.append('ribbon: partial explode matched as full - wrong command would run')
    if m(u'partial', fid, u'Partial Explode'):
        bad.append('ribbon: full explode matched as partial')
    if m(u'partial', u'Dialog_Essentials_ImportInstanceExplode', u'Explode'):
        bad.append('ribbon: the split button itself matched')
    if not m(u'full', u'', u'&Full Explode'):
        bad.append('ribbon: label fallback not matched')
    return bad


def check_plan():
    bad = []
    E, D, M = u'enabled', u'disabled', u'missing'

    # normal: select, ribbon appears, press, import disappears
    p = eim_core.ExplodePlan([10, 11])
    acts = run_plan(p, [(0.1, True, M), (0.1, True, E), (0.1, True, M), (0.1, False, M),
                        (0.1, True, M), (0.1, True, E), (0.1, False, M), (0.1, False, M)])
    if acts != [u'select', u'invoke', u'none', u'none', u'select', u'invoke', u'none', u'finished']:
        bad.append('plan: normal run went {0}'.format(acts))
    if p.counts() != (2, 0, 0):
        bad.append('plan: normal run counts {0}'.format(p.counts()))

    # it must never claim success while the import still exists
    p = eim_core.ExplodePlan([10])
    run_plan(p, [(0.1, True, M), (0.1, True, E)] + [(1.0, True, M)] * 30)
    if p.counts()[0] != 0:
        bad.append('plan: counted an import as exploded while it still exists')
    if p.counts()[1] != 1:
        bad.append('plan: refused import not reported as failed')

    # refused once -> reselect and retry before failing
    p = eim_core.ExplodePlan([10])
    acts = run_plan(p, [(0.1, True, M), (0.1, True, E), (0.1, True, M), (7.0, True, M),
                        (0.1, True, E), (0.1, True, M), (0.1, False, M)])
    if acts[3] != u'select' or acts[4] != u'invoke' or p.counts() != (1, 0, 0):
        bad.append('plan: no retry after a refusal ({0})'.format(acts))

    # ribbon greyed out -> fail after the find timeout, never press
    p = eim_core.ExplodePlan([10])
    acts = run_plan(p, [(0.1, True, M)] + [(1.0, True, D)] * 10)
    if u'invoke' in acts or u'invoke_uia' in acts or p.counts()[1] != 1:
        bad.append('plan: pressed or did not fail a greyed-out Explode ({0})'.format(acts))
    if u'greyed' not in p.results[0][2]:
        bad.append('plan: greyed-out failure not explained')

    # ribbon item missing -> one UI Automation attempt
    p = eim_core.ExplodePlan([10])
    acts = run_plan(p, [(0.1, True, M), (1.0, True, M), (2.0, True, M), (0.1, False, M)])
    if acts.count(u'invoke_uia') != 1 or p.counts() != (1, 0, 0):
        bad.append('plan: UI Automation fallback not used once ({0})'.format(acts))

    # already gone before its turn
    p = eim_core.ExplodePlan([10])
    run_plan(p, [(0.1, False, M), (0.1, False, M)])
    if p.counts() != (0, 0, 1):
        bad.append('plan: an import gone before its turn not recorded as gone')

    if eim_core.run_timeout(10) <= 10 * eim_core.FIND_TIMEOUT:
        bad.append('plan: run timeout shorter than the per-import waits')
    return bad


def check_report():
    bad = []
    lines = eim_core.report_lines([(1, u'ok', u'ribbon'), (2, u'failed', u'refused')],
                                  {1: u'a.dwg', 2: u'b.dwg'}, u'full')
    if lines[0] != u'1 of 2 fully exploded.' or u'b.dwg' not in lines[1] or len(lines) != 2:
        bad.append('report: wrong lines {0}'.format(lines))
    return bad


CHECKS = [check_settings, check_theme, check_ids, check_classify, check_ribbon_match,
          check_plan, check_report]


# ==========================================================================
# Selftest - break the logic, every named check must notice
# ==========================================================================

_ORIG_CLASSIFY = eim_core.classify
_ORIG_PLAN = eim_core.ExplodePlan


def _broken_match(mode, item_id, item_text):
    low = (item_id or u'').lower()
    return u'explode' in low and u'instanceexplode' not in low.replace(u':', u'') or \
        eim_core._norm_text(item_text).endswith(u'explode')


class _OptimisticPlan(_ORIG_PLAN):
    def tick(self, now, exists, button=u'missing'):
        if self.state == u'wait' and self.t_wait is not None:
            self._record(u'ok', self.route)          # trusts the click, never checks the model
            return (u'none', None)
        return _ORIG_PLAN.tick(self, now, exists, button)


BREAKAGES = [
    ('resolve_theme', lambda s, c: u'dark', check_theme),
    ('next_theme_setting', lambda c: u'dark', check_theme),
    ('eid_value', lambda e: int(getattr(e, 'IntegerValue', 0)) if e is not None else 0, check_ids),
    ('classify', lambda items: _ORIG_CLASSIFY([dict(i, is_linked=False) for i in items]), check_classify),
    ('ribbon_item_matches', _broken_match, check_ribbon_match),
    ('ExplodePlan', _OptimisticPlan, check_plan),
    ('parse_settings', lambda t: dict(eim_core.DEFAULTS), check_settings),
]


def run_checks():
    out = []
    for c in CHECKS:
        out.extend(c())
    return out


def selftest():
    ok = True
    for name, broken, check in BREAKAGES:
        original = getattr(eim_core, name)
        setattr(eim_core, name, broken)
        try:
            caught = bool(check())
        except Exception as ex:
            caught = False
            sys.stdout.write('SELFTEST FAIL: {0} check raised instead of reporting ({1})\n'.format(name, ex))
        finally:
            setattr(eim_core, name, original)
        if not caught:
            ok = False
            sys.stdout.write('SELFTEST FAIL: breaking {0} went unnoticed\n'.format(name))
    sys.stdout.write('selftest: {0} breakages, {1}\n'.format(len(BREAKAGES), 'all caught' if ok else 'FAILED'))
    return ok


def main():
    if '--selftest' in sys.argv:
        return 0 if selftest() else 1
    failures = run_checks()
    for f in failures:
        sys.stdout.write(f + '\n')
    sys.stdout.write('bench_logic: {0} checks, {1}\n'.format(
        len(CHECKS), 'all pass' if not failures else '{0} failure(s)'.format(len(failures))))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
