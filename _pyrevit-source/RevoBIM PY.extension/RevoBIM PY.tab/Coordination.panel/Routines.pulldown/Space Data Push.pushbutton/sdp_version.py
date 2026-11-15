# -*- coding: utf-8 -*-
"""The one place the version and the tool name live. Both are read by the
window, the loader and the bench checks."""

__version__ = u"1.2.1"
TOOL_NAME = u"Space Data Push"

# Live-window parking key. Version-stamped so an upgraded tool never finds an
# orphaned window left behind by the previous version.
PARK_KEY = u"RevoBIM.SpaceDataPush." + __version__
