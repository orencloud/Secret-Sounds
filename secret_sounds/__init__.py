bl_info = {
    "name": "Secret Sounds",
    "author": "orencloud",
    "version": (1, 0, 1),
    "blender": (4, 5, 0),
    "location": "Edit > Preferences > Add-ons",
    "description": "Customizable editing, selection and viewport sounds",
    "category": "Interface",
}

import bpy

from .preferences import CLASSES, merge_release, preferences
from . import runtime, updater

_classes = (*CLASSES, runtime.SECRET_SOUNDS_OT_observe, *updater.CLASSES)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    prefs = preferences()
    if prefs:
        merge_release(prefs)
    runtime.start()
    updater.start(bl_info["version"])


def unregister():
    updater.stop()
    runtime.stop()
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
