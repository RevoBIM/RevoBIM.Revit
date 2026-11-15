# -*- coding: utf-8 -*-
"""What the step prompt should show, and for how long.

The prompt walks the user through a manual placement: what to pick next,
when to press Finish, then "BWIC placed" for two seconds. The run does not
wait for the prompt -- the next pick starts the moment a BWIC is placed -- so
the next step arrives while "placed" is still showing. This holds it back
until the two seconds are up, and closes the prompt once the run is over.

Plain Python, no WPF: the window asks this what to draw, and the bench drives
it with a stand-in clock.
"""

FLASH_SECONDS = {'placed': 2.0, 'problem': 3.0, 'note': 3.5,
                 # long enough to read what has to be set up first
                 'blocked': 6.0}

# what each state looks like: (accent, eyebrow)
LOOKS = {
    'step': ('blue', None),         # eyebrow comes from the step number
    'placed': ('green', 'DONE'),
    'problem': ('orange', 'NOT PLACED'),
    # a message from the tool when no run is going -- what the status box
    # under the buttons used to say
    'note': ('blue', 'BWIC PENETRATION'),
    # a run refused before it started: Family settings not set up
    'blocked': ('orange', 'NOT STARTED'),
}


class PromptState(object):
    """Decides what is on screen.

    Every method returns what the window should now do: ('show', look) to
    draw something, ('hide', None) to close, or None to leave it as it is.
    A look is a dict: kind, accent, eyebrow, title, detail, ends, number,
    total -- and seconds, for a flash that should time out.
    """

    def __init__(self):
        self.visible = False
        self.flashing = False
        self.pending = None
        self.closing = False
        self.current = None

    # -- the run's events --------------------------------------------------
    def step(self, details):
        look = step_look(details)
        if self.flashing:
            # the run has moved on while "placed" is still up: show the next
            # step when the flash ends rather than cutting it short
            self.pending = look
            self.closing = False
            return None
        return self._show(look)

    def flash(self, kind, details):
        look = flash_look(kind, details)
        self.flashing = True
        self.pending = None
        self.closing = False
        return self._show(look)

    def done(self):
        """The run is over. A flash still showing is allowed to finish."""
        self.pending = None
        if self.flashing:
            self.closing = True
            return None
        return self._hide()

    def flash_over(self):
        """The flash's time is up."""
        if not self.flashing:
            return None
        self.flashing = False
        if self.pending is not None:
            look, self.pending = self.pending, None
            return self._show(look)
        # nothing came after it -- the run ended, or is between steps
        self.closing = False
        return self._hide()

    def reset(self):
        """Forget everything, as when the tool window closes."""
        self.__init__()
        return ('hide', None)

    # -- internals ---------------------------------------------------------
    def _show(self, look):
        self.visible = True
        self.current = look
        return ('show', look)

    def _hide(self):
        was = self.visible
        self.visible = False
        self.current = None
        return ('hide', None) if was else None


def finish_armed(event, details, armed):
    """Whether the tool's Finish Selection button may press Return now.

    Only while the run is at a step that ends with Finish -- Revit waiting on
    a multiple selection. Return anywhere else repeats Revit's last command,
    so every other event disarms it. A note says nothing about the run and
    leaves it as it was.
    """
    if event == 'step':
        return (details or {}).get('ends') == 'finish'
    if event in ('placed', 'problem', 'done'):
        return False
    return armed


def is_finish_label(text):
    """True for the Options Bar's Finish button: "Finish" or "&Finish".

    Not "Finish Edit Mode", "Finished" or anything else that merely starts
    the same way -- pressing the wrong button would do something else.
    """
    if not text:
        return False
    return text.replace('&', '').strip().lower() == 'finish'


def step_look(details):
    number = details.get('number') or 1
    total = details.get('total') or 1
    return {
        'kind': 'step',
        'accent': LOOKS['step'][0],
        'eyebrow': 'STEP {} OF {}'.format(number, total),
        'title': details.get('title') or '',
        'detail': details.get('detail') or '',
        'ends': details.get('ends') or 'click',
        'number': number,
        'total': total,
        'seconds': None,
    }


def flash_look(kind, details):
    accent, eyebrow = LOOKS[kind]
    return {
        'kind': kind,
        'accent': accent,
        'eyebrow': eyebrow,
        'title': details.get('title') or '',
        'detail': details.get('detail') or '',
        'ends': None,
        'number': None,
        'total': None,
        'seconds': FLASH_SECONDS[kind],
    }


def hint_text(look):
    """The line along the bottom: how this step is answered."""
    if look.get('kind') != 'step':
        return ''
    if look.get('ends') == 'finish':
        return 'Finish Selection  ·  Options Bar Finish  ·  Return     ·     Esc to stop'
    return 'Single click     ·     Esc to stop'


def dots(look):
    """Progress through the steps, as filled and open dots."""
    total = look.get('total') or 0
    number = look.get('number') or 0
    if not total:
        return ''
    return u' '.join(u'●' if i < number else u'○'
                     for i in range(total))
