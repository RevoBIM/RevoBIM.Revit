# -*- coding: utf-8 -*-
"""Model Cleanup logic bench. Plain CPython, no Revit:

    python bench_logic.py              run every check
    python bench_logic.py --selftest   swap in broken versions of the rules
                                       and confirm the checks fail
"""
from __future__ import print_function

import datetime
import io
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import mcu_core as core  # noqa: E402
import mcu_aps as aps  # noqa: E402
import mcu_json as js  # noqa: E402
import mcu_nwc as nwc  # noqa: E402

# The window plumbing - the job queue and the drawer - imports .NET. It is
# loaded here against the same stub API import_check uses, so its logic can
# be driven with stand-in windows, timers and ExternalEvents.
import import_check  # noqa: E402
sys.modules.update(import_check.make_stub_modules())
import mcu_events as events  # noqa: E402
import mcu_ui as ui  # noqa: E402

RESULTS = []


def check(label, condition):
    RESULTS.append((label, bool(condition)))


# ============================================================
# the checks
# ============================================================

def checks_steps():
    s = core.step_states(False, False, False, False)
    check(u"steps: only sync is lit at the start",
          s[core.STEP_SYNC] and not s[core.STEP_SAVE_AS] and not s[core.STEP_CLEANUP])
    s = core.step_states(True, False, False, False)
    check(u"steps: save as lights after sync", s[core.STEP_SAVE_AS])
    check(u"steps: clean up stays dark until saved as", not s[core.STEP_CLEANUP])
    s = core.step_states(False, True, False, False)
    check(u"steps: clean up stays dark if not synced", not s[core.STEP_CLEANUP])
    s = core.step_states(True, True, False, False)
    check(u"steps: clean up lights after sync and save as", s[core.STEP_CLEANUP])
    s = core.step_states(True, True, False, True)
    check(u"steps: nothing is lit while busy",
          not any(s.values()))
    s = core.step_states(True, True, True, False)
    check(u"steps: clean up never runs twice on one copy", not s[core.STEP_CLEANUP])
    s = core.step_states(True, True, False, False, target_alive=False)
    check(u"steps: clean up dark when the copy is closed", not s[core.STEP_CLEANUP])
    check(u"badge: done", core.step_badge(False, True) == u"Done")
    check(u"badge: locked", core.step_badge(False, False) == u"Locked")
    check(u"badge: ready", core.step_badge(True, False) == u"Ready")
    check(u"sync label workshared", core.sync_label(True) == u"Sync Current Model")
    check(u"sync label local", core.sync_label(False) == u"Save Current Model")


def checks_names():
    day = datetime.date(2026, 9, 15)
    template = core.default_template()
    check(u"suffix: on by default", core.active_suffix(template) == u"_Issue")
    template[u"add_suffix"] = u"0"
    check(u"suffix: switched off gives nothing", core.active_suffix(template) == u"")
    check(u"suffix: off keeps the model's own name",
          core.send_file_name(u"45306-MEP.rvt", core.active_suffix(template), False, day)
          == u"45306-MEP.rvt")
    check(u"suffix: off still takes the date",
          core.send_file_name(u"45306-MEP.rvt", core.active_suffix(template), True, day)
          == u"45306-MEP_2026-09-15.rvt")
    template[u"add_suffix"] = u"1"
    template[u"file_suffix"] = u"  _IFC "
    check(u"suffix: trimmed", core.active_suffix(template) == u"_IFC")
    check(u"name: suffix and date",
          core.send_file_name(u"C:\\Jobs\\45306-MEP.rvt", u"_Issue", True, day)
          == u"45306-MEP_Issue_2026-09-15.rvt")
    check(u"name: no date",
          core.send_file_name(u"45306-MEP.rvt", u"_Issue", False, day) == u"45306-MEP_Issue.rvt")
    check(u"name: local user suffix stripped",
          core.send_file_name(u"45306-MEP_jsmith", u"_Issue", False, day, u"jsmith")
          == u"45306-MEP_Issue.rvt")
    check(u"name: cloud path",
          core.send_file_name(u"Autodesk Docs://Job/45306-MEP.rvt", u"", False, day)
          == u"45306-MEP.rvt")
    check(u"name: suffix not doubled",
          core.send_file_name(u"A_Issue.rvt", u"_Issue", False, day) == u"A_Issue.rvt")
    check(u"name: bad characters removed",
          u":" not in core.send_file_name(u"A:B", u"", False, day))
    check(u"name: upper case extension", core.model_stem(u"X.RVT") == u"X")
    check(u"target: empty refused", core.check_target_path(u"", []) is not None)
    check(u"target: not rvt refused", core.check_target_path(u"C:\\a.txt", []) is not None)
    folder = tempfile.mkdtemp()
    try:
        live = os.path.join(folder, u"Live.rvt")
        check(u"target: live model refused",
              core.check_target_path(live, [live]) is not None)
        check(u"target: good path accepted",
              core.check_target_path(os.path.join(folder, u"Copy.rvt"), [live]) is None)
        check(u"target: missing folder refused",
              core.check_target_path(os.path.join(folder, u"nope", u"C.rvt"), []) is not None)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def view(i, name, kind=u"FloorPlan", template=False, parent=0, internal=False):
    return {u"id": i, u"name": name, u"kind": kind, u"template": template,
            u"parent": parent, u"internal": internal}


def checks_views():
    items = [
        view(1, u"L00 Plan"),
        view(2, u"L01 Plan"),
        view(3, u"L01 Plan - Dependent 1", parent=2),
        view(4, u"KEEP coordination"),
        view(5, u"Starting View"),
        view(6, u"Template", template=True),
        view(7, u"Sheet", kind=u"DrawingSheet"),
        view(8, u"Browser", kind=u"ProjectBrowser"),
        view(9, u"Pipe Schedule", kind=u"Schedule"),
        view(10, u"Rev schedule", kind=u"Schedule", internal=True),
        view(11, u"Legend A", kind=u"Legend"),
        view(12, u"Active", kind=u"ThreeD"),
        view(13, u"Section 1", kind=u"Section"),
        view(14, u"Loose 3D", kind=u"ThreeD"),
    ]
    on_sheet = set([1, 3])
    keep = [u"keep"]
    protected = set([12])
    ids, skipped = core.views_to_delete(items, on_sheet, keep, protected)
    check(u"views: placed view kept", 1 not in ids)
    check(u"views: primary of a placed dependent kept", 2 not in ids)
    check(u"views: primary reason recorded", skipped.get(2) == u"a dependent of it is kept")
    check(u"views: keep word honoured (any case)", 4 not in ids)
    check(u"views: templates never deleted", 6 not in ids)
    check(u"views: sheets never deleted", 7 not in ids)
    check(u"views: browser never deleted", 8 not in ids)
    check(u"views: schedules left to their own op", 9 not in ids)
    check(u"views: legends left to their own op", 11 not in ids)
    check(u"views: active view protected", 12 not in ids)
    check(u"views: unplaced section deleted", 13 in ids)
    check(u"views: unplaced 3D deleted", 14 in ids)
    check(u"views: plain unplaced view named Starting kept by keep word",
          5 not in core.views_to_delete(items, on_sheet, [u"Starting"], protected)[0])
    ids2, _ = core.views_to_delete(items, on_sheet, [], set([5]))
    check(u"views: starting view protected", 5 not in ids2)
    sched, _ = core.schedules_to_delete(items, on_sheet, keep, protected)
    check(u"schedules: unplaced schedule deleted", sched == [9])
    check(u"schedules: revision schedule kept", 10 not in sched)
    legends, _ = core.legends_to_delete(items, set(), keep, protected)
    check(u"legends: unplaced legend deleted", legends == [11])
    legends, _ = core.legends_to_delete(items, set([11]), keep, protected)
    check(u"legends: placed legend kept", legends == [])
    chain = [view(20, u"A"), view(21, u"B", parent=20), view(22, u"C", parent=21)]
    ids3, _ = core.views_to_delete(chain, set([22]), [], set())
    check(u"views: whole dependent chain protected", ids3 == [])
    check(u"unused ids: used and defaults kept",
          core.unused_ids([1, 2, 3, 4], set([2]), set([3])) == [1, 4])
    check(u"remaining ids", core.remaining_ids([1, 2, 3], [2]) == [1, 3])


def checks_purge_groups():
    check(u"group: category wins", core.purge_group(u"Pipe Fittings", u"FamilySymbol") == u"Pipe Fittings")
    check(u"group: materials", core.purge_group(u"", u"Material") == u"Materials")
    check(u"group: line patterns", core.purge_group(None, u"LinePatternElement") == u"Line Patterns")
    check(u"group: unknown class split", core.purge_group(u"", u"SomeNewThing") == u"Some New Thing")
    check(u"group: nothing", core.purge_group(u"", u"") == core.OTHER_GROUP)
    entries = [(1, u"A"), (2, u"B"), (3, u"A")]
    check(u"purge selection excludes groups", core.purge_selection(entries, [u"A"]) == [2])
    check(u"purge selection empty exclusion", core.purge_selection(entries, []) == [1, 2, 3])
    rows = core.group_counts(entries, [(9, u"B"), (10, u"C")])
    check(u"group counts", rows == [(u"A", 2, 0), (u"B", 1, 1), (u"C", 0, 1)])
    check(u"visible: used-only hidden when show used off",
          [r[0] for r in core.visible_groups(rows, False, u"")] == [u"A", u"B"])
    check(u"visible: used-only shown when show used on",
          [r[0] for r in core.visible_groups(rows, True, u"")] == [u"A", u"B", u"C"])
    check(u"visible: search", [r[0] for r in core.visible_groups(rows, True, u"c")] == [u"C"])


def checks_delete():
    alive = set(range(1, 121))
    bad = set([7, 55])

    def batch(ids):
        if bad & set(ids):
            return False
        alive.difference_update(ids)
        return True

    def one(value):
        if value in bad:
            return False, u"refused"
        alive.discard(value)
        return True, u""

    fractions = []
    deleted, failures = core.delete_in_chunks(
        list(range(1, 121)), batch, one, lambda v: v in alive, 50, fractions.append)
    check(u"delete: all good ones removed", len(deleted) == 118)
    check(u"delete: bad ones named", set(failures) == bad)
    check(u"delete: progress reaches 1", fractions and abs(fractions[-1] - 1.0) < 1e-9)

    alive2 = set([1, 2, 3])

    def batch_cascade(ids):
        alive2.clear()          # deleting 1 takes 2 and 3 with it
        return True
    deleted, failures = core.delete_in_chunks(
        [1, 2, 3], batch_cascade, one, lambda v: v in alive2, 50)
    check(u"delete: cascade counted once", sorted(deleted) == [1, 2, 3] and not failures)

    alive3 = set([1, 2, 3])
    calls = []

    def batch_fail(ids):
        alive3.discard(1)
        return False

    def one_record(value):
        calls.append(value)
        alive3.discard(value)
        return True, u""
    deleted, failures = core.delete_in_chunks(
        [1, 2, 3], batch_fail, one_record, lambda v: v in alive3, 50)
    check(u"delete: gone element not asked for again on replay", calls == [2, 3])

    def batch_raise(ids):
        raise RuntimeError(u"managed exception")
    alive4 = set([5])
    deleted, failures = core.delete_in_chunks(
        [5], batch_raise, one, lambda v: v in alive4, 50)
    check(u"delete: a throwing batch still replays", deleted == [5])


def checks_purge_loop():
    state = {u"unused": [(1, u"A"), (2, u"B")], u"next": [(3, u"A"), (4, u"A")]}

    def scan():
        return list(state[u"unused"])

    def delete(ids, sub=None):
        if sub is not None:
            sub(0.5)
            sub(1.0)
        state[u"unused"] = [e for e in state[u"unused"] if e[0] not in ids]
        state[u"unused"] += state[u"next"]
        state[u"next"] = []
        return ids, {}

    seen = []
    deleted, failures, ran = core.purge_loop(scan, delete, [u"B"], 3, seen.append)
    check(u"purge: second pass takes what the first freed", sorted(deleted) == [1, 3, 4])
    check(u"purge: excluded group untouched", 2 not in deleted)
    check(u"purge: stops when nothing is left", ran == 2)
    check(u"purge progress: never runs backwards", seen == sorted(seen))
    check(u"purge progress: ends at 100%", seen and seen[-1] == 1.0)
    check(u"purge progress: moves inside a pass", any(0 < v < 1.0 / 3 for v in seen))

    def scan_stuck():
        return [(9, u"A")]

    def delete_refuse(ids, sub=None):
        return [], dict((i, u"no") for i in ids)
    deleted, failures, ran = core.purge_loop(scan_stuck, delete_refuse, [], 5)
    check(u"purge: refused element not retried every pass", ran == 1 and 9 in failures)


def checks_theme():
    check(u"theme: auto dark canvas", core.resolve_theme(u"auto", True) == u"dark")
    check(u"theme: auto light canvas", core.resolve_theme(u"auto", False) == u"light")
    check(u"theme: auto unknown canvas", core.resolve_theme(u"auto", None) == u"dark")
    check(u"theme: fixed light ignores canvas", core.resolve_theme(u"light", True) == u"light")
    check(u"theme: junk means auto", core.normalise_theme_mode(u"purple") == u"auto")
    check(u"theme: cycle", [core.next_theme_mode(m) for m in (u"auto", u"dark", u"light")]
          == [u"dark", u"light", u"auto"])
    check(u"theme: chip label", core.theme_chip_label(u"auto", u"light") == u"Auto Light")
    check(u"theme: white is light", not core.colour_is_dark(255, 255, 255))
    check(u"theme: revit dark grey is dark", core.colour_is_dark(59, 68, 83))


def checks_settings():
    folder = tempfile.mkdtemp()
    old = os.environ.get(u"APPDATA")
    os.environ[u"APPDATA"] = folder
    try:
        names = core.list_templates()
        check(u"templates: seeded on first run",
              names == sorted([n for n, _ in core.SEED_TEMPLATES], key=lambda n: n.lower()))
        keep_links = core.load_template(u"Keep Links")
        check(u"templates: seed override applied", keep_links[u"remove_revit_links"] == u"0")
        values = core.default_template()
        values[u"purge_exclude"] = core.join_list([u"Materials", u"Line Patterns", u"Materials"])
        values[u"keep_view_words"] = u"KEEP;a=b"
        check(u"templates: save", core.save_template(u"My: Job", values))
        loaded = core.load_template(u"My  Job")
        check(u"templates: name sanitised consistently", u"My Job" in core.list_templates())
        check(u"templates: exclusion list round trip",
              core.split_list(loaded[u"purge_exclude"]) == [u"Materials", u"Line Patterns"])
        check(u"templates: value with = round trips", loaded[u"keep_view_words"] == u"KEEP;a=b")
        path = core.template_path(u"Broken")
        with open(path, u"w") as handle:
            handle.write(u"garbage line\npurge=0\nunknown_key=1\npurge_passes=abc\n")
        broken = core.load_template(u"Broken")
        check(u"templates: damaged file falls back key by key",
              broken[u"purge"] == u"0" and broken[u"compact"] == u"1")
        check(u"templates: unknown keys dropped", u"unknown_key" not in broken)
        check(u"templates: unversioned file gets the migrated passes",
              broken[u"purge_passes"] == u"4")
        check(u"templates: bad number clamps to default",
              core.as_int(u"abc", 4, 1, 10) == 4 and core.as_int(u"99", 4, 1, 10) == 10)
        for name in core.list_templates()[:-1]:
            core.delete_template(name)
        ok, reason = core.delete_template(core.list_templates()[0])
        check(u"templates: last one cannot be deleted", not ok and reason)
        check(u"templates: pick falls back", core.pick_template([u"A", u"B"], u"z") == u"A")
        check(u"templates: pick ignores case", core.pick_template([u"A", u"B"], u"b") == u"B")
        settings = core.load_global()
        check(u"global: theme defaults to auto", settings[u"theme_mode"] == u"auto")
        settings[u"theme_mode"] = u"light"
        core.save_global(settings)
        check(u"global: round trip", core.load_global()[u"theme_mode"] == u"light")
        core.MIGRATIONS[99] = [u"theme_mode"]
        try:
            check(u"global: migration resets a changed key",
                  core.load_global()[u"theme_mode"] == u"auto")
        finally:
            del core.MIGRATIONS[99]
        on = core.enabled_ops(core.default_template())
        check(u"ops: default template runs the purge last", on[-1][0] == u"purge")
        check(u"ops: no remove-everything image stage",
              u"remove_images" not in [k for k, _ in core.CLEANUP_OPS])
    finally:
        if old is None:
            del os.environ[u"APPDATA"]
        else:
            os.environ[u"APPDATA"] = old
        shutil.rmtree(folder, ignore_errors=True)


def checks_eid():
    class New(object):
        Value = 12

    class Old(object):
        IntegerValue = 7

        @property
        def Value(self):
            raise AttributeError(u"no Value before 2024")
    check(u"eid: Value first", core.eid_value(New()) == 12)
    check(u"eid: IntegerValue fallback", core.eid_value(Old()) == 7)
    check(u"eid: None", core.eid_value(None) == 0)


class FakeTime(object):
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def checks_progress():
    fake = FakeTime()
    clock = core.ProgressClock(fake)
    clock.start()
    check(u"clock: starts at 0%", clock.percent() == 0)
    check(u"clock: no guess at the start", clock.eta() is None)
    fake.t += 1.0
    clock.update(0.10)
    check(u"clock: no guess before 2 s", clock.eta() is None)
    fake.t += 1.0
    clock.update(0.20)
    eta = clock.eta()
    check(u"clock: steady rate gives the right estimate", eta is not None and abs(eta - 8.0) < 0.5)
    clock.update(0.05)
    check(u"clock: percent never runs backwards", clock.percent() == 20)
    fake.t += 1.0
    clock.update(0.999)
    check(u"clock: 99.9% shows 99 not 100", clock.percent() == 99)
    clock.finish()
    check(u"clock: finish is 100%", clock.percent() == 100 and clock.eta() == 0.0)
    fake.t += 50
    check(u"clock: elapsed stops at finish", abs(clock.elapsed() - 3.0) < 1e-6)
    check(u"clock: done line", core.progress_line(clock) == u"Done in 3 s")

    fake2 = FakeTime()
    slow = core.ProgressClock(fake2)
    slow.start()
    for _ in range(10):
        fake2.t += 1.0
        slow.update(slow.fraction + 0.05)     # 5% a second
    for _ in range(4):
        fake2.t += 1.0
        slow.update(slow.fraction + 0.01)     # slows to 1% a second
    eta = slow.eta()
    check(u"clock: slowdown lengthens the estimate",
          eta is not None and eta > (1 - slow.fraction) / (slow.fraction / slow.elapsed()))
    check(u"clock: running line shows time left and elapsed",
          u"left" in core.progress_line(slow) and u"0:14 elapsed" in core.progress_line(slow))

    check(u"eta text: estimating", core.eta_text(None) == u"Estimating time left...")
    check(u"eta text: under 10", core.eta_text(4) == u"Under 10 s left")
    check(u"eta text: seconds round to 5", core.eta_text(43) == u"About 45 s left")
    check(u"eta text: minutes", core.eta_text(125) == u"About 2 min 05 s left")
    check(u"duration: hours", core.format_duration(3725) == u"1 h 02 min")
    check(u"clock text", core.format_clock(65) == u"1:05" and core.format_clock(3661) == u"1:01:01")

    check(u"repaint: first time", core.should_repaint(None, 5.0, None, 0))
    check(u"repaint: new percent", core.should_repaint(5.0, 5.01, 3, 4))
    check(u"repaint: same percent too soon", not core.should_repaint(5.0, 5.05, 3, 3))
    check(u"repaint: same percent after the interval", core.should_repaint(5.0, 5.2, 3, 3))

    plan = core.stage_plan([u"remove_revit_links", u"purge", u"save"])
    check(u"plan: covers 0 to 1", abs(plan[-1][1] + plan[-1][2] - 1.0) < 1e-9)
    check(u"plan: purge gets more than links", plan[1][2] > plan[0][2])
    check(u"plan: fraction inside a stage",
          abs(core.plan_fraction(plan, u"purge", 0.5) - (plan[1][1] + plan[1][2] / 2)) < 1e-9)
    check(u"plan: unknown stage is 0", core.plan_fraction(plan, u"nope", 0.5) == 0.0)
    check(u"plan: clamps", core.plan_fraction(plan, u"save", 5) == 1.0)

    # delete progress moves during a one-by-one replay
    alive = set(range(1, 11))
    seen = []

    def batch(ids):
        return False

    def one(value):
        alive.discard(value)
        return True, u""
    core.delete_in_chunks(list(range(1, 11)), batch, one, lambda v: v in alive, 25, seen.append)
    check(u"delete progress: reported per replayed element", len(seen) >= 10)
    check(u"delete progress: never runs backwards", seen == sorted(seen))
    check(u"delete progress: ends at 100%", seen[-1] == 1.0)
    empty = []
    core.delete_in_chunks([], batch, one, lambda v: False, 25, empty.append)
    check(u"delete progress: nothing to do still completes", empty == [1.0])


def checks_json():
    data = js.loads(u'{"a": [1, 2.5, -3e2, true, false, null], "b": "x\\"y\\u00e9\\n", "c": {}}')
    check(u"json: numbers", data[u"a"][:3] == [1, 2.5, -300.0])
    check(u"json: literals", data[u"a"][3:] == [True, False, None])
    check(u"json: escapes", data[u"b"] == u'x"y\u00e9\n')
    check(u"json: empty object", data[u"c"] == {})
    check(u"json: surrogate pair", js.loads(u'"\\ud83d\\ude00"') == u"\U0001F600")
    round_trip = {u"k": [u"a\tb", 1, None, {u"z": False}], u"u": u"caf\u00e9"}
    check(u"json: round trip", js.loads(js.dumps(round_trip)) == round_trip)
    check(u"json: output is ASCII", all(ord(c) < 128 for c in js.dumps(round_trip)))
    for bad in (u'{"a" 1}', u"[1,2", u'"open', u"{} x", u""):
        try:
            js.loads(bad)
            check(u"json: rejects " + bad, False)
        except js.JsonError:
            check(u"json: rejects " + bad, True)
    check(u"json: dig", js.dig({u"a": [{u"b": 3}]}, u"a", 0, u"b") == 3)
    check(u"json: dig missing", js.dig({u"a": None}, u"a", u"b") is None)


def checks_aps():
    # RFC 7636 appendix B
    check(u"pkce: RFC 7636 challenge",
          aps.challenge_for(u"dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk")
          == u"E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM")
    verifier = aps.new_verifier()
    check(u"pkce: verifier length 43-128", 43 <= len(verifier) <= 128)
    check(u"pkce: verifier is url-safe", all(c.isalnum() or c in u"-_" for c in verifier))
    check(u"pkce: verifiers differ", aps.new_verifier() != verifier)
    url = aps.authorize_url(u"CID", 8765, u"CH", u"ST")
    check(u"auth url: redirect encoded",
          u"redirect_uri=http%3A%2F%2Flocalhost%3A8765%2Frevobim%2Fcallback" in url)
    check(u"auth url: scopes", u"scope=data%3Aread%20data%3Awrite%20data%3Acreate" in url)
    check(u"auth url: S256", u"code_challenge_method=S256" in url)
    body = aps.code_request(u"CID", 8765, u"a/b+c", u"VER")
    check(u"token request: code escaped", u"code=a%2Fb%2Bc" in body and u"code_verifier=VER" in body)
    check(u"unquote", aps.unquote(u"a%2Fb+c%C3%A9") == u"a/b c\u00e9")
    check(u"unquote: stray percent kept", aps.unquote(u"100%") == u"100%")

    line = u"GET /revobim/callback?code=abc%2F1&state=ST HTTP/1.1"
    check(u"callback: code", aps.parse_callback(line, u"ST") == (u"abc/1", None))
    code, error = aps.parse_callback(line, u"OTHER")
    check(u"callback: wrong state refused", code is None and error)
    code, error = aps.parse_callback(
        u"GET /revobim/callback?error=access_denied&error_description=User%20said%20no HTTP/1.1", u"ST")
    check(u"callback: denial explained", code is None and error == u"User said no")
    check(u"callback: favicon ignored",
          aps.parse_callback(u"GET /favicon.ico HTTP/1.1", u"ST") == (None, None))
    check(u"callback: junk ignored", aps.parse_callback(u"", u"ST") == (None, None))
    reply = aps.callback_response(u"Signed in.")
    check(u"callback page: valid HTTP", reply.startswith(b"HTTP/1.1 200 OK"))
    head, _, page = reply.partition(b"\r\n\r\n")
    check(u"callback page: length right", (u"Content-Length: {0}".format(len(page))).encode(u"ascii") in head)

    token = aps.token_from_reply(u'{"access_token":"A","refresh_token":"R","expires_in":3600}', now=100.0)
    check(u"token: parsed", token.access == u"A" and token.refresh == u"R")
    check(u"token: valid before expiry", token.valid(now=200.0))
    check(u"token: stale near expiry", not token.valid(now=3600.0))
    try:
        aps.token_from_reply(u'{"error":"invalid_grant","error_description":"bad code"}')
        check(u"token: error raised", False)
    except ValueError as error:
        check(u"token: error raised with reason", u"bad code" in u"{0}".format(error))

    check(u"explain: 403 names custom integrations",
          u"Custom Integrations" in aps.explain_status(403, u'{"errors":[{"detail":"no"}]}'))
    check(u"explain: detail carried", u"no" in aps.explain_status(403, u'{"errors":[{"detail":"no"}]}'))
    check(u"explain: unreadable body", u"HTTP 502" in aps.explain_status(502, u"<html>"))

    check(u"project id: prefixed", aps.dm_project_id(u"abc") == u"b.abc")
    check(u"project id: kept", aps.dm_project_id(u"b.abc") == u"b.abc")
    check(u"project id: blank", aps.dm_project_id(u" ") == u"")
    check(u"urn: lineage", aps.is_lineage(u"urn:adsk.wipprod:dm.lineage:X"))
    check(u"urn: EMEA lineage", aps.is_lineage(u"urn:adsk.wipemea:dm.lineage:X"))
    check(u"urn: version", aps.is_version(u"urn:adsk.wipprod:fs.file:vf.X?version=3"))
    check(u"version url encoded",
          aps.version_url(u"p", u"urn:a:fs.file:vf.X?version=3").endswith(
              u"/projects/b.p/versions/urn%3Aa%3Afs.file%3Avf.X%3Fversion%3D3"))
    check(u"item from version",
          aps.item_from_version_reply(
              u'{"data":{"relationships":{"item":{"data":{"id":"urn:L"}}}}}') == u"urn:L")
    folder = (u'{"included":[{"attributes":{"extension":{"data":{"modelGuid":"aaa"}}},'
              u'"relationships":{"item":{"data":{"id":"urn:wrong"}}}},'
              u'{"attributes":{"extension":{"data":{"modelGuid":"BBB-1"}}},'
              u'"relationships":{"item":{"data":{"id":"urn:right"}}}}]}')
    check(u"item from folder by model guid", aps.item_from_folder_reply(folder, u"{bbb-1}") == u"urn:right")
    check(u"item from folder: none", aps.item_from_folder_reply(u"{}", u"x") is None)

    with_links = js.loads(aps.command_body(aps.publish_command(True), u"urn:L"))
    without = js.loads(aps.command_body(aps.publish_command(False), u"urn:L"))
    check(u"payload: with links command",
          js.dig(with_links, u"data", u"attributes", u"extension", u"type")
          == u"commands:autodesk.bim360:C4RModelPublish")
    check(u"payload: without links command",
          js.dig(without, u"data", u"attributes", u"extension", u"type")
          == u"commands:autodesk.bim360:C4RPublishWithoutLinks")
    check(u"payload: schema version", js.dig(without, u"data", u"attributes", u"extension", u"version") == u"1.0.0")
    check(u"payload: item resource",
          js.dig(with_links, u"data", u"relationships", u"resources", u"data", 0)
          == {u"type": u"items", u"id": u"urn:L"})
    check(u"payload: commands type", js.dig(with_links, u"data", u"type") == u"commands")
    check(u"payload: jsonapi", js.dig(with_links, u"jsonapi", u"version") == u"1.0")

    check(u"job: null data means needed", aps.job_state(u'{"data":null}')[0] == aps.JOB_NEEDED)
    check(u"job: processing",
          aps.job_state(u'{"data":{"attributes":{"status":"processing"}}}')[0] == aps.JOB_RUNNING)
    check(u"job: complete",
          aps.job_state(u'{"data":{"attributes":{"status":"complete"}}}')[0] == aps.JOB_DONE)
    check(u"job: failed",
          aps.job_state(u'{"data":{"attributes":{"status":"failed"}}}')[0] == aps.JOB_FAILED)
    check(u"job: odd status kept", aps.job_state(u'{"data":{"attributes":{}}}')[0] == aps.JOB_UNKNOWN)
    check(u"poll: stops when done", aps.poll_should_stop(aps.JOB_DONE, 5))
    check(u"poll: keeps going while running", not aps.poll_should_stop(aps.JOB_RUNNING, 5))
    check(u"poll: gives up after 15 min", aps.poll_should_stop(aps.JOB_RUNNING, 901))
    check(u"links: junk means ask", aps.normalise_links(u"maybe") == aps.LINKS_ASK)
    check(u"links: kept", aps.normalise_links(u"WITHOUT") == aps.LINKS_WITHOUT)

    cloud = {u"cloud": True, u"workshared": True}
    check(u"publish: lit after sync on a cloud model", aps.can_publish(cloud, True) is None)
    check(u"publish: dark before sync", aps.can_publish(cloud, False) is not None)
    check(u"publish: not for local files",
          aps.can_publish({u"cloud": False, u"workshared": True}, True) is not None)
    check(u"publish: not for non-workshared cloud",
          aps.can_publish({u"cloud": True, u"workshared": False}, True) is not None)
    check(u"setup help names the callback",
          u"http://localhost:9000/revobim/callback" in aps.SETUP_HELP.format(
              callback=aps.callback_url(9000)))
    template = core.default_template()
    check(u"template: offer publish on by default", template[u"offer_publish"] == u"1")
    check(u"template: links ask by default", template[u"publish_links"] == u"ask")
    check(u"global: default port", dict(core.GLOBAL_DEFAULTS)[u"aps_port"] == u"8765")


def checks_skip():
    check(u"confirm: exact word", core.confirm_typed(u"CONFIRM"))
    check(u"confirm: spaces forgiven", core.confirm_typed(u"  CONFIRM "))
    for wrong in (u"confirm", u"Confirm", u"CONFIRMED", u"CON FIRM", u"", None, u"yes"):
        check(u"confirm: refuses {0!r}".format(wrong), not core.confirm_typed(wrong))
    check(u"skip: stands in for both steps", core.effective_steps(False, False, True) == (True, True))
    check(u"skip: nothing without it", core.effective_steps(False, False, False) == (False, False))
    synced, saved = core.effective_steps(False, False, True)
    check(u"skip: clean up lights after a confirmed skip",
          core.step_states(synced, saved, False, False)[core.STEP_CLEANUP])
    check(u"skip button: available at the start", core.can_skip(False, False, False, False, False))
    for args in ((True, False, False, False, False), (False, True, False, False, False),
                 (False, False, True, False, False), (False, False, False, True, False),
                 (False, False, False, False, True)):
        check(u"skip button: dark once anything happened {0}".format(args), not core.can_skip(*args))
    check(u"badge: skipped", core.step_badge(False, False, True) == u"Skipped")
    warning = core.skip_warning({u"workshared": False})
    check(u"warning: names central models", u"central model" in warning)
    check(u"warning: asks for the word", u"Type CONFIRM" in warning)
    check(u"warning: says it will not save", u"will not save" in warning)
    check(u"warning: plain model has no connected line", u"still connected" not in warning)
    check(u"warning: connected local called out",
          u"still connected to its central on ACC" in core.skip_warning(
              {u"workshared": True, u"cloud": True, u"central": u"x", u"path": u"y"}))
    check(u"warning: open central called out",
          u"IS the central" in core.skip_warning(
              {u"workshared": True, u"central": u"C:\\a.rvt", u"path": u"c:\\A.rvt"}
              if os.name == u"nt" else
              {u"workshared": True, u"central": u"/a.rvt", u"path": u"/a.rvt"}))


def checks_retain():
    keys = [op for op, _ in core.CLEANUP_OPS]
    check(u"order: NWC export before anything is removed", keys[0] == u"export_nwc")
    check(u"order: sheets first of the removals", keys[1] == u"delete_sheets_not_retained")
    check(u"order: views straight after sheets", keys[2] == u"delete_views_off_sheet")
    check(u"order: schedules and legends before links",
          keys.index(u"delete_legends_off_sheet") < keys.index(u"remove_revit_links"))
    check(u"order: purge last", keys[-1] == u"purge")
    template = core.default_template()
    check(u"purge: 4 passes by default", template[u"purge_passes"] == u"4")
    check(u"sheets: not deleted unless switched on", template[u"delete_sheets_not_retained"] == u"0")
    for name, overrides in core.SEED_TEMPLATES:
        values = core.default_template()
        values.update(overrides)
        check(u"seed {0}: keeps sheets".format(name), values[u"delete_sheets_not_retained"] == u"0")

    folder = tempfile.mkdtemp()
    try:
        path = os.path.join(folder, u"Old.txt")
        with open(path, u"w") as handle:
            handle.write(u"settings_version=1\npurge_passes=3\nremove_cad=0\n")
        old = core.load_template(u"Old", folder)
        check(u"migration: old 3 passes become 4", old[u"purge_passes"] == u"4")
        check(u"migration: other saved keys kept", old[u"remove_cad"] == u"0")
        values = core.default_template()
        values[u"purge_passes"] = u"7"
        core.save_template(u"New", values, folder)
        check(u"migration: a new file keeps its own passes",
              core.load_template(u"New", folder)[u"purge_passes"] == u"7")
        values[u"retain_views"] = core.join_retain(
            [u"FloorPlan::L01 | Power", u"Section::A=B", u"FloorPlan::L01 | Power"])
        values[u"retain_sheets"] = core.join_retain([u"E-110", u"E-101", u"E-99"])
        core.save_template(u"Keep", values, folder)
        loaded = core.load_template(u"Keep", folder)
        check(u"retain: names with | and = survive the file",
              core.split_retain(loaded[u"retain_views"]) == [u"FloorPlan::L01 | Power", u"Section::A=B"])
        check(u"retain: sheets in natural order",
              core.split_retain(loaded[u"retain_sheets"]) == [u"E-99", u"E-101", u"E-110"])
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    check(u"retain: empty text is empty", core.split_retain(u"") == [])
    check(u"view key", core.view_key(u"FloorPlan", u"L01") == u"FloorPlan::L01")

    check(u"natural sort", sorted([u"P-10", u"P-9", u"p-100"], key=core.natural_key)
          == [u"P-9", u"P-10", u"p-100"])
    check(u"folders: org then type",
          core.view_folders([u"MEP", u"Power"], u"FloorPlan") == [u"MEP", u"Power", u"Floor Plans"])
    check(u"folders: blank org value shown as ???",
          core.view_folders([u""], u"Section") == [u"???", u"Sections"])
    check(u"folders: legends at the top", core.view_folders([u"MEP"], u"Legend") == [u"Legends"])
    check(u"folders: schedules at the top",
          core.view_folders([u"MEP"], u"Schedule") == [u"Schedules/Quantities"])
    check(u"folders: sheets without an org", core.sheet_folders([]) == [u"Sheets"])

    items = [
        {u"key": u"a", u"label": u"L10 Power", u"folders": [u"MEP", u"Floor Plans"]},
        {u"key": u"b", u"label": u"L9 Power", u"folders": [u"MEP", u"Floor Plans"]},
        {u"key": u"c", u"label": u"Section 1", u"folders": [u"MEP", u"Sections"]},
        {u"key": u"d", u"label": u"Arch L1", u"folders": [u"Arch", u"Floor Plans"]},
    ]
    rows = core.retain_rows(items, u"", set([u"a", u"b"]))
    labels = [(r[u"kind"], r[u"label"]) for r in rows]
    check(u"rows: browser order with headers", labels == [
        (u"header", u"Arch"), (u"header", u"Floor Plans"), (u"item", u"Arch L1"),
        (u"header", u"MEP"), (u"header", u"Floor Plans"), (u"item", u"L9 Power"),
        (u"item", u"L10 Power"), (u"header", u"Sections"), (u"item", u"Section 1")])
    headers = dict((r[u"path"], r) for r in rows if r[u"kind"] == u"header")
    check(u"rows: fully ticked folder", headers[u"MEP\x1fFloor Plans"][u"state"] == u"all")
    check(u"rows: part ticked folder", headers[u"MEP"][u"state"] == u"some")
    check(u"rows: unticked folder", headers[u"Arch"][u"state"] == u"none")
    check(u"rows: folder lists its items", sorted(headers[u"MEP"][u"children"]) == [u"a", u"b", u"c"])
    check(u"rows: same folder name kept apart by parent",
          headers[u"Arch\x1fFloor Plans"][u"children"] == [u"d"])
    check(u"rows: indent follows depth", [r[u"level"] for r in rows if r[u"kind"] == u"item"] == [2, 2, 2, 2])
    searched = core.retain_rows(items, u"sections", set())
    check(u"search: matches folder names", [r[u"label"] for r in searched if r[u"kind"] == u"item"]
          == [u"Section 1"])
    searched = core.retain_rows(items, u"power l9", set())
    check(u"search: every word must match", [r[u"label"] for r in searched if r[u"kind"] == u"item"]
          == [u"L9 Power"])
    check(u"search: folder tick covers only what is shown",
          [r[u"children"] for r in searched if r[u"kind"] == u"header"][0] == [u"b"])
    folded = core.retain_rows(items, u"", set(), set([u"MEP"]))
    check(u"collapse: hides the folder's items",
          [r[u"label"] for r in folded if r[u"kind"] == u"item"] == [u"Arch L1"])
    check(u"collapse: keeps the header, marked",
          [r[u"collapsed"] for r in folded if r[u"kind"] == u"header" and r[u"label"] == u"MEP"] == [True])
    check(u"collapse: a search opens it again",
          len([r for r in core.retain_rows(items, u"power", set(), set([u"MEP"]))
               if r[u"kind"] == u"item"]) == 2)
    only = core.retain_rows(items, u"", set([u"b", u"d"]), only_retained=True)
    check(u"isolate: only retained items listed",
          [r[u"label"] for r in only if r[u"kind"] == u"item"] == [u"Arch L1", u"L9 Power"])
    check(u"isolate: empty folders dropped",
          u"Sections" not in [r[u"label"] for r in only if r[u"kind"] == u"header"])
    check(u"isolate: folder tick covers only the retained rows",
          [r[u"children"] for r in only if r[u"kind"] == u"header" and r[u"label"] == u"MEP"] == [[u"b"]])
    check(u"isolate: works with a search",
          [r[u"label"] for r in core.retain_rows(items, u"arch", set([u"b", u"d"]), only_retained=True)
           if r[u"kind"] == u"item"] == [u"Arch L1"])
    check(u"isolate: nothing retained shows nothing",
          core.retain_rows(items, u"", set(), only_retained=True) == [])
    check(u"isolate: off by default shows everything",
          len([r for r in core.retain_rows(items, u"", set([u"b"])) if r[u"kind"] == u"item"]) == 4)
    check(u"collapse: all paths", u"MEP\x1fSections" in core.all_folder_paths(items))
    check(u"summary", core.retain_summary(items, set([u"a", u"zz"]), u"views")
          == u"1 of 4 views retained (1 more listed in the template are not in this model)")

    sheets = [{u"id": 1, u"number": u"E-101"}, {u"id": 2, u"number": u"E-102"},
              {u"id": 3, u"number": u"E-103"}]
    ids, skipped = core.sheets_to_delete(sheets, set([u"E-101"]), set([3]))
    check(u"sheets: unretained go", ids == [2])
    check(u"sheets: starting view kept", 3 in skipped)
    check(u"sheets: surviving set",
          core.surviving_sheet_ids(sheets, True, set([u"E-101"]), set([3])) == set([1, 3]))
    check(u"sheets: all survive when the stage is off",
          core.surviving_sheet_ids(sheets, False, set(), set()) == set([1, 2, 3]))

    views = [view(1, u"Kept plan"), view(2, u"Parent"), view(3, u"Dep", parent=2),
             view(4, u"Loose"), view(5, u"Kept legend", kind=u"Legend"),
             view(6, u"Kept sched", kind=u"Schedule")]
    retained = set([u"FloorPlan::Kept plan", u"FloorPlan::Dep", u"Legend::Kept legend",
                    u"Schedule::Kept sched"])
    ids, skipped = core.views_to_delete(views, set(), [], set(), retained)
    check(u"views: retained view kept", 1 not in ids and skipped.get(1) == u"retained in the template")
    check(u"views: parent of a retained dependent kept", 2 not in ids)
    check(u"views: the rest go", ids == [4])
    check(u"views: retain matches the type too",
          4 in core.views_to_delete([view(4, u"Kept plan", kind=u"Section")], set(), [], set(),
                                    retained)[0])
    check(u"legends: retained kept", core.legends_to_delete(views, set(), [], set(), retained)[0] == [])
    check(u"schedules: retained kept",
          core.schedules_to_delete(views, set(), [], set(), retained)[0] == [])
    check(u"views: placed on a surviving sheet kept without being retained",
          core.views_to_delete(views, set([4]), [], set(), retained)[0] == [])


def checks_debug():
    sheets = [{u"id": 1, u"number": u"E-101"}, {u"id": 2, u"number": u"E-102"}]
    views = [view(10, u"A"), view(11, u"B"), view(12, u"C"), view(13, u"T", template=True),
             view(14, u"Kept", parent=0), view(15, u"Browser", kind=u"ProjectBrowser")]
    notes = {}
    core.sheets_to_delete(sheets, set([u"E-101"]), set(), notes)
    check(u"decisions: sheet kept reason", notes[1] == u"kept: retained in the template")
    check(u"decisions: sheet deleted", notes[2] == u"DELETE")
    core.views_to_delete(views, set([10]), [], set([11]), set([u"FloorPlan::Kept"]), notes)
    check(u"decisions: placed", notes[10] == u"kept: placed on a sheet that stays")
    check(u"decisions: protected", notes[11] == u"kept: starting or active view")
    check(u"decisions: deleted view", notes[12] == u"DELETE")
    check(u"decisions: template", notes[13] == u"kept: view template")
    check(u"decisions: retained", notes[14] == u"kept: retained in the template")
    check(u"decisions: system view", notes[15] == u"kept: Revit system view")

    views2 = [view(20, u"Leg", kind=u"Legend"), view(21, u"Leg2", kind=u"Legend"),
              view(22, u"DB1", kind=u"PanelSchedule"), view(23, u"PB", kind=u"ProjectBrowser"),
              view(24, u"Rev", kind=u"Schedule", internal=True)]
    notes2 = {20: u"kept: its delete stage is off", 21: u"kept: its delete stage is off"}
    core.views_to_delete(views2, set(), [], set(), set(), notes2)
    core.schedules_to_delete(views2, set(), [], set(), set(), notes2)
    kept = core.kept_summary(views2, notes2)
    check(u"kept summary: stage off", u"2 Legends (their delete stage is off)" in kept)
    check(u"kept summary: panel schedules",
          u"1 Panel Schedules (never deleted by this tool)" in kept)
    check(u"kept summary: browsers not listed", len(kept) == 2)
    check(u"reason: title block schedule explained",
          notes2[24] == u"kept: title block revision or keynote schedule (goes with its sheet)")
    pend = core.DebugReport(False)
    pend.pending = [(u"a", 1)]
    check(u"debug: pending handed over once", pend.take_pending() == [(u"a", 1)] and pend.take_pending() == [])
    check(u"switch: first candidate that stays", core.choose_switch_view([5, 6, 7], set([5]), 9) == 6)
    check(u"switch: never the current view", core.choose_switch_view([9, 6], set(), 9) == 6)
    check(u"switch: skips blanks", core.choose_switch_view([0, None, 4], set(), 9) == 4)
    check(u"switch: nothing qualifies", core.choose_switch_view([5], set([5]), 9) is None)

    template = core.default_template()
    template[u"retain_sheets"] = core.join_retain([u"E-101"])
    template[u"retain_views"] = core.join_retain([u"FloorPlan::A"])
    warnings = core.retention_warnings(template)
    check(u"warning: sheets ticked but stage off", u"sheets" in warnings)
    check(u"warning: placed views stay while sheets stay", u"placed_views" in warnings)
    check(u"warning: message counts the sheets",
          u"1 sheets are ticked" in core.retention_message(template, warnings))
    fixed = core.fix_retention(template, warnings)
    check(u"fix: turns the sheet stage on", fixed[u"delete_sheets_not_retained"] == u"1")
    check(u"fix: nothing left to warn about", core.retention_warnings(fixed) == [])
    check(u"fix: leaves the original alone", template[u"delete_sheets_not_retained"] == u"0")
    views_off = dict(fixed)
    views_off[u"delete_views_off_sheet"] = u"0"
    check(u"warning: views ticked but stage off", core.retention_warnings(views_off) == [u"views"])
    check(u"warning: none without retain lists", core.retention_warnings(core.default_template()) == [])
    check(u"global: debug off by default", dict(core.GLOBAL_DEFAULTS)[u"debug"] == u"0")

    folder = tempfile.mkdtemp()
    try:
        off = core.DebugReport(False, folder, u"x")
        off.section(u"S")
        off.values([(u"a", 1)])
        check(u"debug off: writes nothing", not off.flush() and not os.listdir(folder))
        report = core.DebugReport(True, folder, u"20260915_101500")
        report.section(u"Stage: views")
        report.values([(u"asked", 3), (u"removed", 2)])
        report.table([u"id", u"name"], [(1, u"a\tb"), (2, u"c\u00e9")])
        report.exception(u"views", u"Traceback: boom")
        path = report.path
        check(u"debug: file named with the stamp",
              os.path.basename(path) == u"model_cleanup_debug_report_20260915_101500.txt")
        text = io.open(path, encoding=u"utf-8").read()
        check(u"debug: version on the first line", text.startswith(u"RevoBIM Model Cleanup v" + core.__version__))
        check(u"debug: aligned values", u"asked    3" in text)
        check(u"debug: tabs in cells cannot break columns", u"1\ta b" in text)
        check(u"debug: unicode survives", u"c\u00e9" in text)
        check(u"debug: exception written straight away", u"ERROR in views" in text and u"boom" in text)
        big = core.DebugReport(True, folder, u"big")
        big.table([u"n"], [(i,) for i in range(30)], limit=10)
        big.flush()
        check(u"debug: long tables capped and say so",
              u"... 20 more rows" in io.open(big.path, encoding=u"utf-8").read())
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def checks_images():
    keys = [op for op, _ in core.CLEANUP_OPS]
    check(u"images: stage after sheets and views",
          keys.index(u"delete_unplaced_images") > keys.index(u"delete_legends_off_sheet")
          and keys.index(u"delete_unplaced_images") > keys.index(u"delete_sheets_not_retained"))
    check(u"images: stage before the purge",
          keys.index(u"delete_unplaced_images") < keys.index(u"purge"))
    check(u"images: on by default", core.default_template()[u"delete_unplaced_images"] == u"1")
    check(u"images: the placed-or-not option is gone", u"remove_images" not in core.default_template())
    folder = tempfile.mkdtemp()
    try:
        with io.open(os.path.join(folder, u"Old.txt"), u"w", encoding=u"utf-8") as handle:
            handle.write(u"settings_version=2\nremove_images=1\ndelete_unplaced_images=0\n")
        old = core.load_template(u"Old", folder)
        check(u"images: old remove-all becomes remove-unplaced", old[u"delete_unplaced_images"] == u"1")
        check(u"images: old key not carried forward", u"remove_images" not in old)
        with io.open(os.path.join(folder, u"Off.txt"), u"w", encoding=u"utf-8") as handle:
            handle.write(u"settings_version=2\nremove_images=0\ndelete_unplaced_images=0\n")
        check(u"images: old remove-all off leaves unplaced as set",
              core.load_template(u"Off", folder)[u"delete_unplaced_images"] == u"0")
        exported = os.path.join(folder, u"Exported.txt")
        with io.open(exported, u"w", encoding=u"utf-8") as handle:
            handle.write(u"model_cleanup_template=2\nsettings_version=2\nremove_images=1\n"
                         u"delete_unplaced_images=0\n")
        imported, _, _ = core.import_template(exported)
        check(u"images: an imported file is upgraded too", imported[u"delete_unplaced_images"] == u"1")
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    check(u"images: only what Revit calls unused", core.unplaced_images([1, 2, 3], set([2, 3, 9])) == [2, 3])
    check(u"images: nothing unused", core.unplaced_images([1, 2], set()) == [])
    types = [1, 2, 3, 4]
    placements = [(1, 10), (1, 11), (2, 10), (2, 20), (3, 20)]
    freed = core.images_freed(types, placements, set([10, 11]), set([4]))
    check(u"preview: image only on going views counts", 1 in freed)
    check(u"preview: image also on a kept view does not", 2 not in freed)
    check(u"preview: image only on kept views does not", 3 not in freed)
    check(u"preview: already unused counts", 4 in freed)
    check(u"preview: unplaced but still used elsewhere does not",
          core.images_freed([5], [], set(), set()) == [])


def checks_close():
    fall = [7, 8]
    check(u"open: retained view stays put", core.view_to_open(5, [1], [5], set(), fall) is None)
    check(u"open: retained sheet stays put", core.view_to_open(1, [1], [5], set(), fall) is None)
    check(u"open: not retained moves to a retained sheet", core.view_to_open(9, [1, 2], [5], set(), fall) == 1)
    check(u"open: sheet first even if the view is kept anyway", core.view_to_open(9, [2], [5], set(), fall) == 2)
    check(u"open: skips a retained sheet that is going", core.view_to_open(9, [2, 3], [5], set([2]), fall) == 3)
    check(u"open: retained view when no sheet is retained", core.view_to_open(9, [], [5], set(), fall) == 5)
    check(u"open: nothing retained and not going - stay", core.view_to_open(9, [], [], set(), fall) is None)
    check(u"open: nothing retained but going - fall back", core.view_to_open(9, [], [], set([9]), fall) == 7)
    check(u"open: retained all going, active going - fall back",
          core.view_to_open(9, [2], [], set([2, 9]), fall) == 7)

    check(u"route: never saved", core.save_route({u"path": u""}) == core.SAVE_AS)
    check(u"route: plain file", core.save_route({u"path": u"C:\\a.rvt", u"workshared": False}) == core.SAVE_PLAIN)
    same = u"C:\\x\\M.rvt" if os.name == u"nt" else u"/x/M.rvt"
    check(u"route: its own central syncs",
          core.save_route({u"path": same, u"workshared": True, u"central": same}) == core.SAVE_SYNC)
    check(u"route: detached central without a central path syncs",
          core.save_route({u"path": same, u"workshared": True, u"central": u""}) == core.SAVE_SYNC)
    check(u"route: local of another central asks",
          core.save_route({u"path": u"/l/M_drew.rvt", u"workshared": True,
                           u"central": u"/c/M.rvt"}) == core.SAVE_LOCAL)
    check(u"route: cloud always asks",
          core.save_route({u"path": u"x", u"workshared": True, u"cloud": True,
                           u"central": u"x"}) == core.SAVE_LOCAL)
    message = core.local_save_message({u"central": u"S:\\Job\\M.rvt"})
    check(u"local message names the central", u"S:\\Job\\M.rvt" in message)
    check(u"local message asks for the word", u"CONFIRM" in message)
    check(u"folder of a file", core.folder_of(os.path.join(u"a", u"b.rvt")) == u"a")
    check(u"no folder for a cloud path", core.folder_of(u"Autodesk Docs://Job/M.rvt") == u"")
    check(u"no folder for nothing", core.folder_of(u"") == u"")


def checks_template_files():
    check(u"export name: prefix", core.export_file_name(u"WRX") == u"Model Cleanup Template - WRX.txt")
    check(u"export name: unnamed", core.export_file_name(u" ") == u"Model Cleanup Template.txt")
    check(u"export name: bad characters", u":" not in core.export_file_name(u"A:B"))
    check(u"name from file: prefix stripped",
          core.name_from_file(u"C:\\x\\Model Cleanup Template - WRX Issue.txt") == u"WRX Issue")
    check(u"name from file: any other file", core.name_from_file(u"/x/site notes.txt") == u"site notes")
    check(u"name from file: nothing left", core.name_from_file(u"Model Cleanup Template.txt")
          == core.EXPORT_PREFIX)
    check(u"unique name: free", core.unique_template_name(u"WRX", [u"A"]) == u"WRX")
    check(u"unique name: taken, any case", core.unique_template_name(u"WRX", [u"wrx"]) == u"WRX (2)")
    check(u"unique name: several taken",
          core.unique_template_name(u"WRX", [u"WRX", u"WRX (2)", u"WRX (3)"]) == u"WRX (4)")

    folder = tempfile.mkdtemp()
    old = os.environ.get(u"APPDATA")
    os.environ[u"APPDATA"] = folder
    try:
        values = core.default_template()
        values[u"purge_passes"] = u"7"
        values[u"keep_view_words"] = u"KEEP;a=b"
        values[u"retain_sheets"] = core.join_retain([u"E-101", u"E-102"])
        values[u"nwc_primary"] = u"ACC-ALL"
        path = os.path.join(folder, core.export_file_name(u"WRX"))
        check(u"export: written", core.export_template(values, u"WRX", path))
        back, name, error = core.import_template(path)
        check(u"import: no error", not error)
        check(u"import: name carried in the file", name == u"WRX")
        check(u"import: every setting round trips",
              all(back[k] == values[k] for k, _ in core.TEMPLATE_DEFAULTS
                  if k != u"settings_version"))
        check(u"import: values with = survive", back[u"keep_view_words"] == u"KEEP;a=b")
        check(u"import: retain lists survive",
              core.split_retain(back[u"retain_sheets"]) == [u"E-101", u"E-102"])
        plain = os.path.join(folder, u"Copied From Settings Folder.txt")
        core.save_template(u"Copied From Settings Folder", values, folder)
        back2, name2, error2 = core.import_template(plain)
        check(u"import: a file from the settings folder works too", not error2)
        check(u"import: falls back to the file name", name2 == u"Copied From Settings Folder")
        junk = os.path.join(folder, u"Shopping list.txt")
        with io.open(junk, u"w", encoding=u"utf-8") as handle:
            handle.write(u"milk=2\nbread=1\n")
        _, _, error3 = core.import_template(junk)
        check(u"import: refuses another kind of file", bool(error3))
        _, _, error4 = core.import_template(os.path.join(folder, u"not here.txt"))
        check(u"import: refuses a missing file", bool(error4))
        old_file = os.path.join(folder, u"Old export.txt")
        with io.open(old_file, u"w", encoding=u"utf-8") as handle:
            handle.write(u"model_cleanup_template=1\npurge_passes=3\nremove_cad=0\n")
        back5, _, _ = core.import_template(old_file)
        check(u"import: an older file is migrated", back5[u"purge_passes"] == u"4")
        check(u"import: unknown keys dropped", u"milk" not in (back5 or {}))
    finally:
        if old is None:
            del os.environ[u"APPDATA"]
        else:
            os.environ[u"APPDATA"] = old
        shutil.rmtree(folder, ignore_errors=True)


def checks_nwc():
    template = core.default_template()
    check(u"nwc: off by default", template[u"export_nwc"] == u"0")
    check(u"nwc: every option has a default",
          all(key in template for key, _, _, _ in core.NWC_BOOL_OPTIONS))
    plan = nwc.options_plan(template)
    check(u"nwc plan: view scope", plan[u"ExportScope"] == u"View")
    check(u"nwc plan: shared coordinates", plan[u"Coordinates"] == u"Shared")
    check(u"nwc plan: all parameters", plan[u"Parameters"] == u"All")
    check(u"nwc plan: links off by default", plan[u"ExportLinks"] is False)
    check(u"nwc plan: every option set", len(plan) == 4 + len(core.NWC_BOOL_OPTIONS))
    template[u"nwc_source"] = nwc.SOURCE_DEFAULTS
    check(u"nwc plan: exporter defaults set only the scope",
          nwc.options_plan(template) == {u"ExportScope": u"View"})
    template[u"nwc_source"] = nwc.SOURCE_CUSTOM
    template[u"nwc_coordinates"] = u"internal"
    template[u"nwc_parameters"] = u"NONE"
    template[u"nwc_faceting"] = u"50"
    plan = nwc.options_plan(template)
    check(u"nwc plan: internal coordinates", plan[u"Coordinates"] == u"Internal")
    check(u"nwc plan: none parameters, any case", plan[u"Parameters"] == u"None")
    check(u"nwc plan: faceting clamped", plan[u"FacetingFactor"] == 10.0)
    check(u"nwc: bad faceting falls back", nwc.faceting(u"abc") == 1.0)
    check(u"nwc: junk choice falls back", nwc.choice(u"maybe", nwc.COORDINATES, u"shared") == u"shared")

    check(u"select: primary defaults to the first", nwc.normalise([u"B", u"A 10", u"A 9"], u"")
          == ([u"A 9", u"A 10", u"B"], u"A 9"))
    check(u"select: an unticked primary gets ticked", nwc.normalise([u"B"], u"A") == ([u"A", u"B"], u"A"))
    check(u"select: unticking the primary moves it", nwc.untick([u"A", u"B"], u"A", u"A") == ([u"B"], u"B"))
    check(u"select: unticking the last clears it", nwc.untick([u"A"], u"A", u"A") == ([], u""))
    check(u"select: duplicates and blanks dropped", nwc.normalise([u"A", u"A", u" "], u"A") == ([u"A"], u"A"))
    template[u"nwc_views"] = core.join_retain([u"ACC-ALL", u"3D Coord"])
    template[u"nwc_primary"] = u"ACC-ALL"
    check(u"select: read from the template", nwc.selection(template) == ([u"3D Coord", u"ACC-ALL"], u"ACC-ALL"))

    names = nwc.file_names(u"C:\\x\\WRX-ME-000001.rvt", [u"3D Coord", u"ACC-ALL", u"a/b"], u"ACC-ALL")
    check(u"files: primary named after the model", names[0] == (u"ACC-ALL", u"WRX-ME-000001"))
    check(u"files: secondary gets _view name", (u"3D Coord", u"WRX-ME-000001_3D Coord") in names)
    check(u"files: unsafe characters replaced", (u"a/b", u"WRX-ME-000001_a-b") in names)
    clash = nwc.file_names(u"M", [u"a:b", u"a/b"], u"a:b")
    check(u"files: clashes numbered", [n for _, n in clash] == [u"M", u"M_a-b"]
          and len(set(n.lower() for _, n in nwc.file_names(u"M", [u"x", u"a:b", u"a/b"], u"x"))) == 3)
    check(u"files: nothing ticked", nwc.file_names(u"M", [], u"") == [])
    found, missing = nwc.resolve({u"ACC-ALL": 5}, [(u"ACC-ALL", u"M"), (u"Gone", u"M_Gone")])
    check(u"resolve: found", found == [(5, u"ACC-ALL", u"M")])
    check(u"resolve: missing named", missing == [u"Gone"])

    listed = nwc.rows([u"B", u"A 10", u"A 9", u"C"], u"a", [u"A 9"])
    check(u"rows: natural order and search", listed == [u"A 9", u"A 10"])
    check(u"rows: ticked only", nwc.rows([u"B", u"A"], u"", [u"B"], True) == [u"B"])
    check(u"summary: nothing ticked", u"skipped" in nwc.summary([], u"", u"M"))
    check(u"summary: names the primary and files",
          u"Primary: A" in nwc.summary([u"A", u"B"], u"A", u"M") and u"M_B.nwc" in nwc.summary([u"A", u"B"], u"A", u"M"))
    template[u"export_nwc"] = u"1"
    check(u"problems: none when ready", nwc.problems(template, True) == [])
    check(u"problems: exporter missing", len(nwc.problems(template, False)) == 1)
    template[u"nwc_views"] = u""
    template[u"nwc_primary"] = u""
    check(u"problems: no view ticked", len(nwc.problems(template, True)) == 1)
    template[u"export_nwc"] = u"0"
    check(u"problems: none when off", nwc.problems(template, False) == [])

    cloud = {u"workshared": True, u"cloud": True}
    check(u"save as: ACC saves the open model", core.save_as_route(cloud) == core.ROUTE_SAVE_OPEN)
    check(u"save as: file central opens detached",
          core.save_as_route({u"workshared": True}) == core.ROUTE_DETACHED_OPEN)
    check(u"save as: plain file is copied", core.save_as_route({}) == core.ROUTE_FILE_COPY)
    text = core.save_as_confirmation(cloud, u"C:\\x\\M.rvt", core.DETACH_DISCARD)
    check(u"save as text: says detached copy", u"DETACHED copy" in text and u"is the detached model" in text)
    check(u"save as text: explains ACC", u"cannot detach a cloud model" in text)
    check(u"save as text: discard not possible on ACC", u"not possible" in text)
    check(u"save as text: file central keeps the live model",
          u"is not touched" in core.save_as_confirmation({u"workshared": True}, u"x", u"preserve"))

    folder = tempfile.mkdtemp()
    try:
        with open(os.path.join(folder, u"Old.txt"), u"w") as handle:
            handle.write(u"settings_version=2\nsync_comment=RevoBIM Model Cleanup - synced before issue\n")
        check(u"renamed default: old sync comment refreshed",
              core.load_template(u"Old", folder)[u"sync_comment"] == u"Model Cleanup - synced before issue")
        with open(os.path.join(folder, u"Mine.txt"), u"w") as handle:
            handle.write(u"settings_version=2\nsync_comment=RevoBIM for issue\n")
        check(u"renamed default: own comment kept",
              core.load_template(u"Mine", folder)[u"sync_comment"] == u"RevoBIM for issue")
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    check(u"groups: generic types named", core.purge_group(u"", u"ElementType") == u"Other Types")
    check(u"groups: text styles named",
          core.purge_group(u"", u"LineAndTextAttrSymbol") == u"Line and Text Styles")



# ============================================================
# the job queue (ExternalEvent runner)
# ============================================================

class FakeEvent(object):
    def __init__(self, answers):
        self.answers = list(answers)
        self.raised = 0

    def Raise(self):
        self.raised += 1
        return self.answers.pop(0) if self.answers else u"Accepted"


def make_runner(answers, errors):
    runner = events.ApiRunner(on_error=lambda label, text: errors.append(label))
    runner.event = FakeEvent(answers)
    return runner


def checks_runner():
    check(u"raise: accepted keeps the job", core.raise_kept(u"Accepted"))
    check(u"raise: pending keeps the job", core.raise_kept(u"ExternalEventRequest.Pending"))
    check(u"raise: denied loses it", not core.raise_kept(u"Denied"))
    check(u"raise: timed out loses it", not core.raise_kept(u"TimedOut"))
    check(u"raise: an exception text loses it", not core.raise_kept(u"Raise failed: boom"))
    check(u"waiting: quiet at first", core.waiting_note(3) == u"Waiting for Revit...")
    check(u"waiting: explains after 20 s", u"Esc" in core.waiting_note(25))

    errors, ran = [], []
    runner = make_runner([u"Accepted", u"Pending", u"Denied"], errors)
    kept1, _ = runner.request(u"one", lambda uiapp: ran.append(u"one"))
    kept2, _ = runner.request(u"two", lambda uiapp: ran.append(u"two"))
    kept3, status = runner.request(u"three", lambda uiapp: ran.append(u"three"))
    check(u"runner: accepted and pending both queued", kept1 and kept2)
    check(u"runner: denied refused", not kept3 and status == u"Denied")
    check(u"runner: a refusal drops only its own job", runner.waiting() == [u"one", u"two"])
    runner.Execute(None)
    check(u"runner: jobs run in order", ran == [u"one", u"two"])
    check(u"runner: queue drained", runner.waiting() == [] and runner.running is None)

    errors, ran = [], []
    runner = make_runner([], errors)

    def chain(uiapp):
        ran.append(u"first")
        runner.request(u"second", lambda u: ran.append(u"second"))

    def boom(uiapp):
        raise RuntimeError(u"boom")
    runner.request(u"first", chain)
    runner.request(u"bad", boom)
    runner.request(u"after", lambda uiapp: ran.append(u"after"))
    runner.Execute(None)
    check(u"runner: a failing job is reported", errors == [u"bad"])
    check(u"runner: the queue carries on after a failure", u"after" in ran)
    check(u"runner: a job queued by a job runs in the same pass", u"second" in ran)

    runner = make_runner([], [])
    runner.request(u"keep", lambda uiapp: None)
    runner.request(u"drop", lambda uiapp: None)
    check(u"runner: cancel one label", runner.cancel(u"drop") == 1 and runner.waiting() == [u"keep"])
    check(u"runner: cancel all", runner.cancel() == 1 and runner.waiting() == [])


# ============================================================
# the drawer
# ============================================================

class FakeEventHook(object):
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def fire(self, *args):
        for handler in list(self.handlers):
            handler(*args)


class FakeElement(object):
    def __init__(self, visibility=u"visible"):
        self.Visibility = visibility


class FakePoint(object):
    Y = 1.0


class FakeHeader(FakeElement):
    def __init__(self):
        FakeElement.__init__(self)
        self.ActualHeight = 44.0
        self.CornerRadius = u"top only"

    def TranslatePoint(self, point, relative_to):
        return FakePoint()


class FakeRoot(object):
    def __init__(self, header, siblings):
        self.Children = [header] + siblings
        self.ActualHeight = 758.0
        self.Height = float(u"nan")
        self.VerticalAlignment = u"stretch"


class FakeButton(object):
    def __init__(self):
        self.Click = FakeEventHook()
        self.Tag = None
        self.ToolTip = None


class FakeWindow(object):
    def __init__(self, left=200.0, top=120.0, width=1060.0, height=800.0):
        self.Left, self.Top, self.Width, self.Height = left, top, width, height
        self.ActualHeight = height
        self.MinHeight = 680.0
        self.SizeToContent = u"height"
        self.PreviewKeyDown = FakeEventHook()
        self.Closed = FakeEventHook()
        self.released = []
        self.fail_top_once = False
        self.activated = 0

    def __setattr__(self, name, value):
        if name == u"Top" and getattr(self, u"fail_top_once", False):
            object.__setattr__(self, u"fail_top_once", False)
            raise RuntimeError(u"layout pass refused")
        if name == u"Height":
            object.__setattr__(self, u"ActualHeight", value)
        object.__setattr__(self, name, value)

    def BeginAnimation(self, prop, value):
        self.released.append(value)

    def Activate(self):
        self.activated += 1


class FakeTimer(object):
    """Like a DispatcherTimer: Start() never runs a tick. An exception that
    escapes a tick is recorded, the way the dispatcher would surface it."""
    escaped = []

    def __init__(self, tick):
        self.tick = tick
        self.running = False

    def Start(self):
        self.running = True

    def Stop(self):
        self.running = False

    def fire(self):
        try:
            self.tick()
        except Exception as error:
            FakeTimer.escaped.append(error)


class FakeClock(object):
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


AREA = (0.0, 0.0, 1920.0, 1040.0)


def make_drawer(window=None, siblings=None, timer_factory=None):
    window = window or FakeWindow()
    header = FakeHeader()
    siblings = siblings if siblings is not None else [FakeElement(), FakeElement(u"collapsed")]
    root = FakeRoot(header, siblings)
    button = FakeButton()
    grips = FakeElement()
    clock = FakeClock()
    timers = []

    def factory(tick):
        timer = FakeTimer(tick)
        timers.append(timer)
        return timer
    drawer = ui.WindowDrawer(window, header, root, button, grips,
                             timer_factory=timer_factory or factory, clock=clock,
                             area_of=lambda w: AREA)
    return drawer, window, header, root, button, grips, clock, timers, siblings


def run_slide(drawer, clock, timers, steps=(0.1, 0.2, 0.3)):
    timer = timers[-1]
    for t in steps:
        clock.now = drawer._t0 + t
        if timer.running:
            timer.fire()


class EnumVisibility(object):
    Visible = u"visible"
    Collapsed = u"collapsed"
    Hidden = u"hidden"


class EnumAlignment(object):
    Top = u"top"
    Stretch = u"stretch"


class EnumSizeToContent(object):
    Manual = u"manual"
    Height = u"height"


class EnumDouble(object):
    NaN = float(u"nan")

    @staticmethod
    def IsNaN(value):
        try:
            return value != value
        except Exception:
            return False


def corner(radius):
    return u"corner {0}".format(radius)


DRAWER_ENUMS = {u"Visibility": EnumVisibility, u"VerticalAlignment": EnumAlignment,
                u"SizeToContent": EnumSizeToContent, u"Double": EnumDouble,
                u"CornerRadius": corner}


def checks_drawer():
    saved = dict((name, getattr(ui, name)) for name in DRAWER_ENUMS)
    for name, value in DRAWER_ENUMS.items():
        setattr(ui, name, value)
    try:
        _checks_drawer()
    finally:
        for name, value in saved.items():
            setattr(ui, name, value)


def _checks_drawer():
    FakeTimer.escaped = []
    ui.DRAWERS.clear()
    check(u"ease: ends", core.ease_out(0) == 0.0 and core.ease_out(1) == 1.0)
    check(u"ease: out, not in", core.ease_out(0.5) > 0.5)
    check(u"ease: clamped", core.ease_out(2) == 1.0 and core.ease_out(-1) == 0.0)
    check(u"park: bottom, clear of the taskbar", core.parked_top(AREA, 46) == 1040 - 8 - 46)
    check(u"park: second bar above the first",
          core.parked_top(AREA, 46, 1) == core.parked_top(AREA, 46) - 46 - 4)
    check(u"park: monitor above the primary", core.parked_top((0, -1080, 1920, 1040), 46) < 0)
    check(u"clamp: kept on screen", core.clamp_left(AREA, 1500, 1060) == 860)
    check(u"clamp: left edge", core.clamp_left((-1920, 0, 1920, 1040), -2500, 800) == -1920)
    restore = (200.0, 120.0, 1060.0, 800.0)
    check(u"reopen: untouched bar goes back exactly",
          core.reopen_bounds(restore, (200, 986), (201, 985), 46, AREA) == restore)
    moved = core.reopen_bounds(restore, (200, 986), (600, 900), 46, AREA)
    check(u"reopen: a moved bar opens upward from where it sits",
          moved[0] == 600 and moved[1] == 900 + 46 - 800)
    high = core.reopen_bounds(restore, (200, 986), (600, 100), 46, AREA)
    check(u"reopen: never above the screen", high[1] == 0)
    check(u"keys: ctrl+shift+H toggles", core.drawer_key_action(u"H", True, True, False, False) == u"toggle")
    check(u"keys: escape opens a parked bar", core.drawer_key_action(u"Escape", False, False, True, False) == u"open")
    check(u"keys: enter and F11 open it", core.drawer_key_action(u"Return", False, False, True, False) == u"open"
          and core.drawer_key_action(u"F11", False, False, True, False) == u"open")
    check(u"keys: anything else swallowed while parked",
          core.drawer_key_action(u"A", False, False, True, False) == u"swallow")
    check(u"keys: swallowed mid-slide", core.drawer_key_action(u"H", True, True, False, True) == u"swallow")
    check(u"keys: left alone when open", core.drawer_key_action(u"Escape", False, False, False, False) is None)

    drawer, window, header, root, button, grips, clock, timers, siblings = make_drawer()
    check(u"drawer: registered", ui.drawer_for(window) is drawer)
    check(u"drawer: button wired", len(button.Click.handlers) == 1)
    check(u"drawer: keys wired before the window's own", len(window.PreviewKeyDown.handlers) == 1)
    drawer.shrink()
    check(u"shrink: a timer drives it, nothing ran in Start", timers and window.Top == 120.0)
    check(u"shrink: MinHeight relaxed", window.MinHeight == 0)
    check(u"shrink: SizeToContent relaxed", window.SizeToContent == u"manual")
    check(u"shrink: body pinned", root.Height == 758.0 and root.VerticalAlignment == u"top")
    check(u"shrink: grips parked at once", grips.Visibility == u"collapsed")
    check(u"shrink: second press mid-slide ignored", drawer.toggle() is False)
    clock.now = drawer._t0 + 0.1
    timers[-1].fire()
    check(u"shrink: moving between", 120.0 < window.Top < core.parked_top(AREA, 46))
    run_slide(drawer, clock, timers, (0.2, 0.3))
    bar = 44.0 + 2.0
    check(u"shrink: lands on the bar", window.Top == core.parked_top(AREA, bar) and window.Height == bar)
    check(u"shrink: timer stopped", not timers[-1].running and not drawer.sliding)
    check(u"shrink: siblings collapsed", all(sib.Visibility == u"collapsed" for sib in siblings))
    check(u"shrink: body unpinned once parked",
          root.Height != root.Height and root.VerticalAlignment == u"stretch")
    check(u"shrink: header corners rounded", header.CornerRadius == u"corner 5")
    check(u"shrink: green arrow", button.Tag == u"shrunk")
    check(u"shrink: animations released", None in window.released)

    drawer.expand()
    run_slide(drawer, clock, timers)
    check(u"expand: back where it was",
          (window.Left, window.Top, window.Width, window.Height) == (200.0, 120.0, 1060.0, 800.0))
    check(u"expand: MinHeight put back", window.MinHeight == 680.0)
    check(u"expand: SizeToContent put back", window.SizeToContent == u"height")
    check(u"expand: grips back", grips.Visibility == u"visible")
    check(u"expand: siblings back to what they were",
          siblings[1].Visibility == u"collapsed" and siblings[0].Visibility == u"visible")
    check(u"expand: header corners back", header.CornerRadius == u"top only")
    check(u"expand: body unpinned", root.Height != root.Height and root.VerticalAlignment == u"stretch")
    check(u"expand: down arrow again", button.Tag is None and not drawer.parked)
    check(u"expand: window activated", window.activated >= 1)

    drawer.shrink()
    run_slide(drawer, clock, timers)
    siblings[1].Visibility = u"visible"       # a job showed the progress bar while parked
    drawer.expand()
    run_slide(drawer, clock, timers)
    check(u"expand: something shown while parked stays shown", siblings[1].Visibility == u"visible")
    check(u"expand: the rest restored", siblings[0].Visibility == u"visible")
    siblings[1].Visibility = u"collapsed"

    drawer.shrink()
    run_slide(drawer, clock, timers)
    window.Left, window.Top = 600.0, 900.0
    drawer.expand()
    run_slide(drawer, clock, timers)
    check(u"expand: a moved bar opens upward", window.Left == 600.0 and window.Top == 900.0 + bar - 800.0)

    ui.DRAWERS.clear()
    drawer, window, header, root, button, grips, clock, timers, siblings = make_drawer()
    drawer.shrink()
    clock.now = drawer._t0 + 0.1
    window.fail_top_once = True
    timers[-1].fire()
    check(u"frame failure: lands at the end state", window.Height == bar and drawer.parked)
    check(u"frame failure: not stuck sliding", not drawer.sliding and not timers[-1].running)
    check(u"frame failure: recorded, not escaped", drawer.errors and not FakeTimer.escaped)
    check(u"frame failure: can toggle again", drawer.toggle() is True)

    ui.DRAWERS.clear()

    def no_timer(tick):
        raise RuntimeError(u"no dispatcher")
    drawer, window, header, root, button, grips, clock, timers, siblings = make_drawer(
        timer_factory=no_timer)
    drawer.shrink()
    check(u"no timer: lands at once", drawer.parked and not drawer.sliding and window.Height == bar)

    ui.DRAWERS.clear()
    owner, owner_window = make_drawer()[:2]
    dialog, dialog_window, _, _, _, _, dclock, dtimers, _ = make_drawer(FakeWindow(500, 300, 520, 240))
    dialog.link_owner(owner_window)
    dialog.shrink()
    check(u"owner: shrinking a dialog parks its owner first", owner.parked)
    run_slide(dialog, dclock, dtimers)
    check(u"owner: the dialog's bar stacks above the owner's",
          dialog_window.Top == core.parked_top(AREA, bar, 1))
    dialog.expand()
    check(u"owner: reopening the dialog brings the owner back", not owner.parked)
    run_slide(dialog, dclock, dtimers)
    dialog.shrink()
    run_slide(dialog, dclock, dtimers)
    dialog_window.Closed.fire(None, None)
    check(u"owner: closing a parked dialog brings the owner back", not owner.parked)
    check(u"owner: a closed dialog leaves the register", ui.drawer_for(dialog_window) is None)

    ui.DRAWERS.clear()
    owner, owner_window, _, _, _, _, oclock, otimers, _ = make_drawer()
    owner.shrink()
    run_slide(owner, oclock, otimers)
    dialog, dialog_window, _, _, _, _, dclock, dtimers, _ = make_drawer(FakeWindow(500, 300, 520, 240))
    dialog.link_owner(owner_window)
    dialog.shrink()
    run_slide(dialog, dclock, dtimers)
    dialog.expand()
    run_slide(dialog, dclock, dtimers)
    check(u"owner: one the user parked stays parked when a dialog reopens", owner.parked)
    dialog_window.Closed.fire(None, None)
    check(u"owner: and stays parked when the dialog closes", owner.parked)
    check(u"drawer: nothing escaped any frame", not FakeTimer.escaped)
    ui.DRAWERS.clear()


def checks_cascade():
    check(u"cascade: nothing guarded", core.cascade_hits([1, 2], None) == [])
    check(u"cascade: a kept callout caught", core.cascade_hits([10, 11, 12], set([12, 40])) == [12])
    check(u"cascade: clean delete passes", core.cascade_hits([10, 11], set([12])) == [])
    check(u"guard: keeps what is not doomed", core.view_guard([1, 2, 3, 4], [2, 4]) == set([1, 3]))
    check(u"guard: a view on a sheet Revit refused to delete is kept",
          core.view_guard([1, 2, 3], [2, 3], [3]) == set([1, 3]))
    check(u"cascade reason names the view", u"'Detail A'" in core.cascade_reason([u"Detail A"]))
    check(u"cascade reason caps the list", u"and 2 more" in core.cascade_reason([u"a", u"b", u"c", u"d", u"e"]))
    refused, kept = core.split_refusals({1: u"Revit said no", 2: core.cascade_reason([u"x"])})
    check(u"refusals: guard holds are not failures", list(refused) == [1] and list(kept) == [2])

    # the delete loop with a guard: a chunk that would take a kept callout is
    # undone, replayed one by one, and only the parent at fault stays
    alive = set([1, 2, 3, 4, 50])
    cascades = {3: [50]}         # deleting view 3 takes callout 50 with it
    guard = set([50])

    def batch(ids):
        taken = set(ids)
        for value in ids:
            taken.update(cascades.get(value, []))
        if core.cascade_hits(taken, guard):
            return False
        alive.difference_update(taken)
        return True

    def one(value):
        taken = set([value] + cascades.get(value, []))
        if core.cascade_hits(taken, guard):
            return False, core.cascade_reason([u"Callout 50"])
        alive.difference_update(taken)
        return True, u""
    deleted, failures = core.delete_in_chunks([1, 2, 3, 4], batch, one, lambda v: v in alive, 25)
    check(u"guarded delete: the others go", sorted(deleted) == [1, 2, 4])
    check(u"guarded delete: the parent of a kept callout stays", 3 in alive and 3 in failures)
    check(u"guarded delete: the callout survives", 50 in alive)


ALL = [checks_runner, checks_drawer, checks_cascade, checks_template_files, checks_nwc, checks_images, checks_close, checks_debug, checks_retain, checks_skip, checks_json, checks_aps, checks_progress, checks_steps, checks_names, checks_views, checks_purge_groups,
       checks_delete, checks_purge_loop, checks_theme, checks_settings, checks_eid]


def run_all():
    del RESULTS[:]
    for block in ALL:
        try:
            block()
        except Exception as error:
            RESULTS.append((u"{0} raised {1}".format(block.__name__, error), False))
    return [label for label, ok in RESULTS if not ok]


# ============================================================
# selftest - each breakage must turn at least one check red
# ============================================================

def _broken_steps(synced, saved_as, cleaned, busy, target_alive=True):
    return {core.STEP_SYNC: True, core.STEP_SAVE_AS: True, core.STEP_CLEANUP: bool(synced)}


def _broken_views(items, on_sheet, keep_words, protected):
    return ([i[u"id"] for i in items if i[u"id"] not in on_sheet
             and not i.get(u"template")], {})


def _broken_chunks(ids, delete_batch, delete_one, still_there, size=50, progress=None):
    ok = delete_batch(list(ids))
    return (list(ids), {}) if ok else ([], dict((i, u"x") for i in ids))


def _broken_loop(scan, delete, excluded, passes, progress=None):
    deleted, failures = delete([e[0] for e in scan()], None)
    return deleted, failures, 1


class _BackwardsClock(core.ProgressClock):
    def update(self, fraction):
        self.fraction = max(0.0, min(1.0, float(fraction)))
        return self.fraction


class _NaiveEtaClock(core.ProgressClock):
    def eta(self):
        if self.fraction >= 1.0:
            return 0.0
        if self.fraction <= 0:
            return None
        return (1.0 - self.fraction) / (self.fraction / max(self.elapsed(), 1e-9))


def _broken_repaint(last_paint, now, last_percent, percent, interval=0.15):
    return True


def _broken_plan(keys):
    size = 1.0 / max(1, len(keys))
    return [(key, index * size, size) for index, key in enumerate(keys)]


def _broken_resolve(mode, canvas_dark):
    return core.THEME_DARK


def _broken_merge(raw, defaults):
    out = dict(defaults)
    out.update(raw)
    return out


def _broken_send_name(source, suffix, add_date, today=None, user_name=None):
    return core.model_stem(source) + u".rvt"


def _broken_confirm(text):
    return core.to_text(text).strip().upper() == u"CONFIRM"


def _broken_can_skip(synced, saved_as, skipped, cleaned, busy):
    return not busy


def _broken_warning(info):
    return u"Type CONFIRM. The tool will not save."


def _broken_switch(candidates, doomed, current):
    return candidates[0] if candidates else None


def _broken_view_to_open(active_id, sheets, views, doomed, fallbacks):
    return core.choose_switch_view(fallbacks, doomed, active_id) if active_id in doomed else None


def _broken_route(info):
    return core.SAVE_SYNC if info.get(u"workshared") else core.SAVE_PLAIN


def _broken_raise_kept(status):
    return core.to_text(status).split(u".")[-1] == u"Accepted"


def _broken_parked_top(area, bar_height, stack=0):
    left, top, width, height = area
    return height - bar_height - core.DRAWER_GAP


def _broken_cascade(deleted_ids, guard):
    return []


def _broken_view_guard(all_view_ids, doomed_ids, placed_ids=()):
    doomed = set(doomed_ids or [])
    return set(value for value in all_view_ids if value not in doomed)


def _broken_tick(self):
    progress = (self.clock() - self._t0) / core.DRAWER_SECONDS
    if progress >= 1.0:
        self.timer.Stop()
        self._land(self._end, self._done)
        return
    self._apply(tuple(core.tween(a, b, progress) for a, b in zip(self._start, self._end)))


def _broken_landed_open(self):
    self.root.Height = core.to_text(u"auto")
    self.parked = False
    self._dress()


def _broken_request(self, label, job):
    entry = (label, job)
    self.queue.append(entry)
    status = core.to_text(self.event.Raise())
    if core.raise_kept(status):
        return True, status
    self.queue = []
    return False, status


def _broken_import(path):
    raw = core.read_kv(path)
    return core.merge_defaults(raw, core.TEMPLATE_DEFAULTS), core.name_from_file(path), u""


def _broken_export_name(template_name):
    return core.sanitize_name(template_name) + u".txt"


def _broken_file_names(model_stem, views, primary):
    return [(v, u"{0}_{1}".format(core.model_stem(model_stem), v)) for v in views]


def _broken_untick(views, primary, name):
    return [v for v in views if v != name], primary


def _broken_save_as_route(info):
    return core.ROUTE_DETACHED_OPEN if info.get(u"workshared") else core.ROUTE_FILE_COPY


def _broken_unplaced(image_type_ids, unused_ids):
    return list(image_type_ids)


def _broken_active_suffix(template):
    return core.to_text(template.get(u"file_suffix")).strip()


def _broken_kept(views, decisions):
    return []


def _broken_warnings(template):
    return []


def _broken_ops_order():
    return list(reversed(core.CLEANUP_OPS))


def _broken_rows(items, search, retained, collapsed=None, only_retained=False):
    rows = []
    for item in sorted(items, key=lambda i: i[u"label"]):
        rows.append({u"kind": u"item", u"level": 0, u"key": item[u"key"],
                     u"label": item[u"label"], u"checked": item[u"key"] in (retained or [])})
    return rows


def _broken_sheets(sheets, retained_numbers, protected):
    return [s[u"id"] for s in sheets if s[u"number"] not in (retained_numbers or [])], {}


def _broken_candidates(items, on_sheet, keep_words, protected, kinds=None,
                       exclude_kinds=None, retained=None):
    return _REAL_CANDIDATES(items, on_sheet, keep_words, protected, kinds, exclude_kinds, None)


_REAL_CANDIDATES = core.off_sheet_candidates


def _broken_command(with_links):
    return aps.CMD_PUBLISH


def _broken_callback(request_line, expected_state):
    parts = request_line.split()
    if len(parts) < 2 or u"code=" not in parts[1]:
        return None, None
    return parts[1].split(u"code=")[1].split(u"&")[0], None


def _broken_can_publish(info, synced):
    return None if info.get(u"cloud") else u"no"


def _broken_job_state(body):
    return aps.JOB_DONE, u"complete"


def _broken_quote_string(value):
    return u'"' + value + u'"'


BREAKS = [
    (u"clean up lights after sync only", u"step_states", _broken_steps),
    (u"primary views not protected", u"views_to_delete", _broken_views),
    (u"all-or-nothing delete", u"delete_in_chunks", _broken_chunks),
    (u"single-pass purge ignoring exclusions", u"purge_loop", _broken_loop),
    (u"theme ignores the canvas", u"resolve_theme", _broken_resolve),
    (u"settings keep unknown keys", u"merge_defaults", _broken_merge),
    (u"send name ignores suffix", u"send_file_name", _broken_send_name),
    (u"percent runs backwards", u"ProgressClock", _BackwardsClock),
    (u"estimate guesses from the first tick and ignores slowdowns", u"ProgressClock", _NaiveEtaClock),
    (u"repaint on every report", u"should_repaint", _broken_repaint),
    (u"every stage weighted equally", u"stage_plan", _broken_plan),
    (u"only moves off views that are going", u"view_to_open", _broken_view_to_open),
    (u"every workshared file is synced", u"save_route", _broken_route),
    (u"a Pending raise drops the job", u"raise_kept", _broken_raise_kept),
    (u"a refused raise clears the whole queue", u"events.ApiRunner.request", _broken_request),
    (u"bar parks on the wrong monitor", u"parked_top", _broken_parked_top),
    (u"drawer frame failure escapes the timer", u"ui.WindowDrawer._tick", _broken_tick),
    (u"reopening forgets MinHeight and the grips", u"ui.WindowDrawer._landed_open", _broken_landed_open),
    (u"cascades into kept views not caught", u"cascade_hits", _broken_cascade),
    (u"views on a refused sheet left unguarded", u"view_guard", _broken_view_guard),
    (u"any text file imported as a template", u"import_template", _broken_import),
    (u"export file name loses the prefix", u"export_file_name", _broken_export_name),
    (u"primary NWC not named after the model", u"nwc.file_names", _broken_file_names),
    (u"unticked primary stays primary", u"nwc.untick", _broken_untick),
    (u"ACC tries the detach that fails", u"save_as_route", _broken_save_as_route),
    (u"placed images deleted too", u"unplaced_images", _broken_unplaced),
    (u"suffix tick ignored", u"active_suffix", _broken_active_suffix),
    (u"confirmation hides what stays", u"kept_summary", _broken_kept),
    (u"switch picks a view that is going", u"choose_switch_view", _broken_switch),
    (u"no warning when retain lists do nothing", u"retention_warnings", _broken_warnings),
    (u"purge before sheets and views", u"CLEANUP_OPS", _broken_ops_order()),
    (u"no browser grouping", u"retain_rows", _broken_rows),
    (u"starting sheet not protected", u"sheets_to_delete", _broken_sheets),
    (u"retained views ignored", u"off_sheet_candidates", _broken_candidates),
    (u"old templates keep 3 passes", u"MIGRATIONS", {}),
    (u"confirm accepts any case", u"confirm_typed", _broken_confirm),
    (u"skip offered after sync", u"can_skip", _broken_can_skip),
    (u"warning forgets central models", u"skip_warning", _broken_warning),
    (u"without links sends the with-links command", u"aps.publish_command", _broken_command),
    (u"sign-in ignores the state check", u"aps.parse_callback", _broken_callback),
    (u"publish lights before the sync", u"aps.can_publish", _broken_can_publish),
    (u"every job reads as done", u"aps.job_state", _broken_job_state),
    (u"json strings not escaped", u"js._quote", _broken_quote_string),
]


def selftest():
    baseline = run_all()
    if baseline:
        print(u"bench is red before breaking anything: " + u", ".join(baseline))
        return 1
    bad = 0
    modules = {u"aps": aps, u"js": js, u"nwc": nwc, u"ui": ui, u"events": events}
    for label, name, broken in BREAKS:
        owner = core
        if u"." in name:
            parts = name.split(u".")
            owner = modules[parts[0]]
            for part in parts[1:-1]:
                owner = getattr(owner, part)
            name = parts[-1]
        original = getattr(owner, name)
        setattr(owner, name, broken)
        try:
            failures = run_all()
        finally:
            setattr(owner, name, original)
        print(u"{0:7} {1} ({2} check(s) went red)".format(
            u"caught" if failures else u"MISSED", label, len(failures)))
        if not failures:
            bad += 1
    return bad


if __name__ == u"__main__":
    if u"--selftest" in sys.argv:
        result = selftest()
        print(u"selftest: {0}".format(u"every breakage caught" if not result
                                      else u"{0} missed".format(result)))
        sys.exit(1 if result else 0)
    failures = run_all()
    for label, ok in RESULTS:
        if not ok:
            print(u"FAIL  " + label)
    print(u"{0} of {1} checks passed".format(len(RESULTS) - len(failures), len(RESULTS)))
    sys.exit(1 if failures else 0)
