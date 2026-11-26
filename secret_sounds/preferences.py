"""The preferences are the add-on's only UI."""

from copy import deepcopy
import json
from pathlib import Path

import bpy
from bpy.props import (
    BoolProperty, CollectionProperty, FloatProperty, IntProperty, StringProperty,
)

from .audio import PACKAGE
from .catalog import DEFAULT_CLIP, GROUPS, LABELS, MOTION
from .theme_updates import freeze, inventory, merge

DEFAULT = json.loads((PACKAGE / "profile.json").read_text(encoding="utf-8"))
EXPANDED = set()


def preferences():
    addon = bpy.context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


def themes_of(prefs):
    if prefs.themes:
        try:
            themes = json.loads(prefs.themes)
            if isinstance(themes, list) and themes:
                return themes
        except ValueError:
            pass
    return deepcopy(DEFAULT["themes"])


def merge_release(prefs):
    if not prefs.update_inventory:
        return
    known = json.loads(prefs.update_inventory)
    current = inventory(DEFAULT["themes"], LABELS, known)
    if current != known:
        prefs.themes = json.dumps(merge(themes_of(prefs), known, DEFAULT["themes"], LABELS, DEFAULT_CLIP))
        prefs.update_inventory = json.dumps(current)


def preserve_before_update(prefs):
    known = json.loads(prefs.update_inventory) if prefs.update_inventory else None
    prefs.themes = json.dumps(freeze(themes_of(prefs), LABELS, DEFAULT_CLIP))
    prefs.update_inventory = json.dumps(inventory(DEFAULT["themes"], LABELS, known))


def active_theme(prefs):
    themes = themes_of(prefs)
    return themes[min(prefs.theme, len(themes) - 1)]


def entry_of(theme, key):
    return theme["operations"].get(key, {"clips": ["@default"], "enabled": True})


def resolve_clip(key, clip):
    if clip == "@default":
        clip = DEFAULT_CLIP[key]
    path = Path(clip)
    return path if path.is_absolute() else PACKAGE / path


def sync(prefs, _context):
    from . import runtime
    runtime.sync(prefs)


class SecretSoundsPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    volume: FloatProperty(name="Master Volume", default=DEFAULT["volume"], min=0, max=1, subtype="FACTOR", update=sync)
    speed_low: FloatProperty(name="Start", default=DEFAULT["speed_low"], min=0, update=sync)
    speed_high: FloatProperty(name="End", default=DEFAULT["speed_high"], min=1, update=sync)
    pitch_low: FloatProperty(name="Start", default=DEFAULT["pitch_low"], update=sync)
    pitch_high: FloatProperty(name="End", default=DEFAULT["pitch_high"], update=sync)
    rate_low: FloatProperty(name="Start", default=DEFAULT["rate_low"], min=0.05, update=sync)
    rate_high: FloatProperty(name="End", default=DEFAULT["rate_high"], min=0.05, update=sync)
    themes: StringProperty(default="", options={"HIDDEN"}, update=sync)
    theme: IntProperty(default=DEFAULT["theme"], min=0, options={"HIDDEN"}, update=sync)
    search: StringProperty(name="Search Sounds", options={"SKIP_SAVE"})
    show_sounds: BoolProperty(name="Sound Themes", default=False)
    theme_name: StringProperty(name="Theme Name", options={"SKIP_SAVE"})
    update_inventory: StringProperty(options={"HIDDEN"})
    auto_check_updates: BoolProperty(name="Automatically Check for Updates", default=True)
    update_interval_days: IntProperty(name="Days Between Checks", default=1, min=1, max=30)
    show_updates: BoolProperty(name="Updates", default=False, options={"SKIP_SAVE"})

    def draw(self, _context):
        from .runtime import AUDIO
        from .updater import draw_updates
        layout = self.layout
        layout.prop(self, "volume", slider=True)
        if AUDIO.error:
            layout.label(text=AUDIO.error, icon="INFO")
        draw_updates(layout, self)
        layout.prop(self, "show_sounds", icon="TRIA_DOWN" if self.show_sounds else "TRIA_RIGHT", emboss=False)
        if not self.show_sounds:
            return

        themes = themes_of(self)
        theme = themes[min(self.theme, len(themes) - 1)]
        row = layout.row(align=True)
        row.operator_menu_enum("secret_sounds.choose_theme", "index", text=theme["name"])
        for action, title in (("NEW", "New"), ("COPY", "Duplicate"), ("RENAME", "Rename"), ("DELETE", "Delete")):
            col = row.row(align=True)
            col.enabled = action != "DELETE" or len(themes) > 1
            col.operator("secret_sounds.edit_theme", text=title).action = action

        table = layout.box()
        headings = table.row()
        headings.label(text="Motion")
        headings.label(text="Start")
        headings.label(text="End")
        for label, low, high in (
            ("Mouse speed (px/s)", "speed_low", "speed_high"),
            ("Pitch (semitones)", "pitch_low", "pitch_high"),
            ("Playback speed", "rate_low", "rate_high"),
        ):
            row = table.row()
            row.label(text=label)
            row.prop(self, low, text="")
            row.prop(self, high, text="")

        layout.prop(self, "search", text="", icon="VIEWZOOM")
        query = self.search.casefold().strip()
        shared = {}
        for key in LABELS:
            for clip in entry_of(theme, key)["clips"]:
                path = resolve_clip(key, clip)
                if path.suffix.lower() == ".mp3":
                    shared.setdefault(path, set()).add(key)
        for group, entries in GROUPS.items():
            matches = [
                (key, label) for key, label in entries.items()
                if query in f"{group} {label}".casefold()
                or any(query in resolve_clip(key, clip).name.casefold() for clip in entry_of(theme, key)["clips"])
            ]
            if not matches:
                continue
            box = layout.box()
            box.label(text=group)
            for key, label in matches:
                entry = entry_of(theme, key)
                row = box.row(align=True)
                button = row.operator("secret_sounds.clip_action", text="", icon="CHECKBOX_HLT" if entry["enabled"] else "CHECKBOX_DEHLT")
                button.key, button.action = key, "TOGGLE"
                button = row.operator("secret_sounds.clip_action", text="", icon="PLAY")
                button.key, button.action = key, "PREVIEW"
                button = row.operator("secret_sounds.pick_clips", text="", icon="ADD")
                button.key = key
                button = row.operator("secret_sounds.clip_action", text=label, emboss=False)
                button.key, button.action = key, "EXPAND"
                if key not in EXPANDED:
                    continue
                for index, clip in enumerate(entry["clips"]):
                    path = resolve_clip(key, clip)
                    row = box.row(align=True)
                    row.separator(factor=1.0)
                    button = row.operator("secret_sounds.clip_action", text="", icon="PLAY")
                    button.key, button.action, button.index = key, "PREVIEW", index
                    button = row.operator("secret_sounds.pick_clips", text="Re-pick")
                    button.key, button.index = key, index
                    button = row.operator("secret_sounds.clip_action", text="", icon="X")
                    button.key, button.action, button.index = key, "REMOVE", index
                    others = shared.get(path, set()) - {key}
                    if others:
                        button = row.operator("secret_sounds.shared_clips", text=str(len(others)))
                        button.labels = "\n".join(sorted(LABELS[item] for item in others))
                    row.label(text=path.name)
                if not entry["clips"]:
                    box.label(text="No clips")


def available_themes(_self, _context):
    prefs = preferences()
    # Blender keeps references to dynamic enum strings.
    global _theme_items
    _theme_items = [(str(i), theme["name"], "") for i, theme in enumerate(themes_of(prefs))] if prefs else []
    return _theme_items


_theme_items = []


class SECRET_SOUNDS_OT_choose_theme(bpy.types.Operator):
    bl_idname = "secret_sounds.choose_theme"
    bl_label = "Choose Sound Theme"

    index: bpy.props.EnumProperty(items=available_themes)

    def execute(self, _context):
        preferences().theme = int(self.index)
        return {"FINISHED"}


class SECRET_SOUNDS_OT_edit_theme(bpy.types.Operator):
    bl_idname = "secret_sounds.edit_theme"
    bl_label = "Edit Sound Theme"

    action: StringProperty(options={"HIDDEN"})
    name: StringProperty(name="Name")

    def invoke(self, context, _event):
        prefs = preferences()
        current = active_theme(prefs)["name"]
        if self.action == "DELETE":
            return context.window_manager.invoke_confirm(self, _event)
        self.name = current if self.action == "RENAME" else current + " Copy" if self.action == "COPY" else "New Theme"
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, _context):
        prefs = preferences()
        themes = themes_of(prefs)
        index = min(prefs.theme, len(themes) - 1)
        if self.action == "DELETE":
            if len(themes) <= 1:
                return {"CANCELLED"}
            del themes[index]
            prefs.themes = json.dumps(themes)
            prefs.theme = min(index, len(themes) - 1)
            return {"FINISHED"}
        name = self.name.strip()
        if not name or any(theme["name"].casefold() == name.casefold() for i, theme in enumerate(themes)
                           if self.action != "RENAME" or i != index):
            self.report({"WARNING"}, "Enter a unique theme name")
            return {"CANCELLED"}
        if self.action == "RENAME":
            themes[index]["name"] = name
        else:
            operations = deepcopy(themes[index]["operations"]) if self.action == "COPY" else {}
            themes.append({"name": name, "operations": operations})
            index = len(themes) - 1
        prefs.themes = json.dumps(themes)
        prefs.theme = index
        return {"FINISHED"}


def edit_entry(key, edit):
    prefs = preferences()
    themes = themes_of(prefs)
    theme = themes[min(prefs.theme, len(themes) - 1)]
    entry = theme["operations"].setdefault(key, entry_of(theme, key))
    edit(entry)
    prefs.themes = json.dumps(themes)


class SECRET_SOUNDS_OT_clip_action(bpy.types.Operator):
    bl_idname = "secret_sounds.clip_action"
    bl_label = "Sound Clip"

    key: StringProperty()
    action: StringProperty()
    index: IntProperty(default=-1)

    def execute(self, context):
        from . import runtime
        if self.key not in LABELS:
            return {"CANCELLED"}
        prefs = preferences()
        if self.action == "EXPAND":
            if self.key in EXPANDED:
                EXPANDED.remove(self.key)
            else:
                EXPANDED.add(self.key)
        elif self.action == "TOGGLE":
            edit_entry(self.key, lambda entry: entry.update(enabled=not entry["enabled"]))
        elif self.action == "REMOVE":
            def remove(entry):
                if 0 <= self.index < len(entry["clips"]):
                    entry["clips"].pop(self.index)
            edit_entry(self.key, remove)
        elif self.action == "PREVIEW":
            paths = entry_of(active_theme(prefs), self.key)["clips"]
            if paths:
                from random import choice
                clip = paths[self.index] if 0 <= self.index < len(paths) else choice(paths)
                runtime.preview(prefs, self.key, resolve_clip(self.key, clip))
        if context.area:
            context.area.tag_redraw()
        return {"FINISHED"}


class SECRET_SOUNDS_OT_pick_clips(bpy.types.Operator):
    bl_idname = "secret_sounds.pick_clips"
    bl_label = "Choose MP3 or WAV"

    key: StringProperty()
    index: IntProperty(default=-1)
    filepath: StringProperty(subtype="FILE_PATH")
    directory: StringProperty(subtype="DIR_PATH")
    files: CollectionProperty(type=bpy.types.OperatorFileListElement)
    filter_glob: StringProperty(default="*.mp3;*.wav;*.ogg;*.flac", options={"HIDDEN"})

    def invoke(self, context, _event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, _context):
        if self.key not in LABELS:
            return {"CANCELLED"}
        files = [Path(self.directory) / file.name for file in self.files]
        if not files and self.filepath:
            files = [Path(self.filepath)]
        paths = [str(path.resolve()) for path in files if path.is_file() and path.suffix.lower() in {".mp3", ".wav", ".ogg", ".flac"}]
        if not paths:
            return {"CANCELLED"}
        def add(entry):
            clips = entry["clips"]
            if 0 <= self.index < len(clips):
                clips[self.index:self.index + 1] = paths
            else:
                clips.extend(paths)
            entry["clips"] = list(dict.fromkeys(clips))
        edit_entry(self.key, add)
        EXPANDED.add(self.key)
        return {"FINISHED"}


class SECRET_SOUNDS_OT_shared_clips(bpy.types.Operator):
    bl_idname = "secret_sounds.shared_clips"
    bl_label = "Also Used By"

    labels: StringProperty()

    def invoke(self, context, _event):
        return context.window_manager.invoke_popup(self, width=230)

    def draw(self, _context):
        for label in self.labels.splitlines():
            self.layout.label(text=label)

    def execute(self, _context):
        return {"FINISHED"}


CLASSES = (
    SecretSoundsPreferences, SECRET_SOUNDS_OT_choose_theme, SECRET_SOUNDS_OT_edit_theme,
    SECRET_SOUNDS_OT_clip_action, SECRET_SOUNDS_OT_pick_clips, SECRET_SOUNDS_OT_shared_clips,
)
