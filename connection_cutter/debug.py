"""Lightweight debug logging for Connection Cutter.

Enabled automatically when Blender itself is launched with the --debug
command-line flag (bpy.app.debug), or manually via the "Debug Logging"
toggle in the addon preferences - useful for seeing exactly *why* a cut
was rejected (which of several possible checks failed, and with what
numbers) without needing to relaunch Blender each time.

Prints to the console Blender was started from (Window > Toggle System
Console on Windows, if you didn't launch from a terminal).
"""

import bpy


def enabled():
    if bpy.app.debug:
        return True
    addon = bpy.context.preferences.addons.get(__package__)
    return bool(addon and addon.preferences.debug_logging)


def log(*parts):
    if enabled():
        print("[Connection Cutter]", *parts)
