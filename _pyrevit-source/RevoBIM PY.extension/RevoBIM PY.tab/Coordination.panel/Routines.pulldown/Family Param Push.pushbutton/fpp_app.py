# -*- coding: utf-8 -*-
"""Launch, and the ExternalEvent runner every Revit read and write goes
through. Modeless windows must never wait for the event: the job is queued, the
window returns, and the result comes back on the dispatcher."""
import fpp_clr  # noqa: F401  (must stay first)
import traceback
from System import Action, AppDomain, TimeSpan
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Threading import DispatcherPriority, DispatcherTimer
from Autodesk.Revit.UI import ExternalEvent, IExternalEventHandler

import fpp_core
import fpp_dialogs
import fpp_revit
from fpp_main import FamilyParamPush
from fpp_version import __version__

WINDOW_KEY = 'RevoBIM.FamilyParamPush.' + __version__
WATCHDOG_SECONDS = 20


class Job(object):
    def __init__(self, name, work, done, dispatcher):
        self.name = name
        self.work = work
        self.done = done
        self.dispatcher = dispatcher


class Runner(IExternalEventHandler):
    def __init__(self, settings, direct=False):
        self.settings = settings
        self.direct = direct
        self.queue = []
        self.event = None
        self.dog = None
        self.uiapp = None

    def GetName(self):
        return 'Family Param Push'

    def Execute(self, uiapp):
        self.stop_dog()
        jobs = self.queue
        self.queue = []
        for job in jobs:
            self.run(job, uiapp)

    def run(self, job, uiapp):
        result, error = None, None
        fpp_core.log(self.settings, u'job start: ' + job.name)
        try:
            result = job.work(uiapp)
        except Exception:
            error = traceback.format_exc()
            fpp_core.log(None, error)
        def finish():
            job.done(result, error)
        job.dispatcher.BeginInvoke(DispatcherPriority.Background,
                                   Action(finish))

    def submit(self, name, work, done, dispatcher):
        job = Job(name, work, done, dispatcher)
        if self.direct:                 # modal: already in the API context
            self.run(job, self.uiapp)
            return True
        self.queue.append(job)
        status = str(self.event.Raise())
        if status in ('Accepted', 'Pending'):   # Pending: one is already waiting
            self.start_dog(dispatcher)
            return True
        self.queue.remove(job)          # only the refused job, never the queue
        fpp_core.log(self.settings, u'event refused: ' + status)
        return False

    def start_dog(self, dispatcher):
        self.stop_dog()
        self.dog = DispatcherTimer()
        self.dog.Interval = TimeSpan.FromSeconds(WATCHDOG_SECONDS)
        self.dog.Tick += self.on_dog
        self.dog.Start()

    def stop_dog(self):
        if self.dog is not None:
            self.dog.Stop()
            self.dog = None

    def on_dog(self, sender, args):
        """Revit has not run it: a command or dialog is open. The job stays
        queued and runs when Revit is idle; the window is told why."""
        self.stop_dog()
        fpp_core.log(self.settings, u'watchdog: Revit busy')
        if self.on_stuck is not None:
            self.on_stuck()

    on_stuck = None


def replace_open_window():
    domain = AppDomain.CurrentDomain
    old = domain.GetData(WINDOW_KEY)
    if old is None:
        return
    try:
        old.Tag = 'replace'
        old.Close()
    except Exception:
        pass
    domain.SetData(WINDOW_KEY, None)


def stale_engine(settings):
    return fpp_core.engine_note_is_stale(
        fpp_core.read_text(fpp_core.note_path()), __version__)


def launch(uiapp):
    uidoc = uiapp.ActiveUIDocument
    if uidoc is None:
        return None
    doc = uidoc.Document
    settings = fpp_core.load_settings()
    replace_open_window()
    families = fpp_revit.read_model(doc)
    modal = settings.get('modal') == '1'
    runner = Runner(settings, modal)
    runner.uiapp = uiapp
    if not modal:
        runner.event = ExternalEvent.Create(runner)
    tool = FamilyParamPush(uiapp, doc, families, settings, runner)
    def stuck():
        tool.busy = False
        tool.update_buttons()
        tool.set_status(u'Revit is busy (a command or dialog is open). This '
                        u'will run as soon as Revit is idle.', True)
    runner.on_stuck = stuck
    if not modal and stale_engine(settings):
        if fpp_dialogs.ask(tool, u'Family Param Push',
                           u'The last window may not have responded to '
                           u'clicks. Open this one locked to Revit instead? '
                           u'It works the same, but Revit waits until it is '
                           u'closed.', u'Open locked', u'Try normally'):
            settings['modal'] = u'1'
            fpp_core.save_settings(settings)
            runner.direct = True
            modal = True
    helper = WindowInteropHelper(tool.window)
    helper.Owner = uiapp.MainWindowHandle
    AppDomain.CurrentDomain.SetData(WINDOW_KEY, tool.window)
    if modal:
        tool.window.ShowDialog()
        return tool
    fpp_core.write_text(fpp_core.note_path(), __version__)
    tool.armed = True                  # after the build, just before Show
    tool.window.Show()
    return tool
