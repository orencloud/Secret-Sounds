"""Observe native Blender actions without replacing keymaps or consuming input."""

from dataclasses import dataclass, field
from itertools import islice
from time import perf_counter

import bpy
import bmesh
from bpy.app.handlers import persistent
from bpy.props import IntProperty

from .audio import Audio
from .catalog import LABELS
from .loopcut import RingPicker
from .preferences import active_theme, entry_of, preferences, resolve_clip

AUDIO = Audio()
WINDOWS = {}
SETTINGS = None
ENABLED = False
NEXT_OBSERVER = 0

MODAL = {
    "TRANSFORM_OT_translate": ("moveStart", "move"),
    "TRANSFORM_OT_rotate": ("rotateStart", "rotate"),
    "TRANSFORM_OT_trackball": ("rotateStart", "rotate"),
    "TRANSFORM_OT_resize": ("scaleStart", "scale"),
    "TRANSFORM_OT_shrink_fatten": ("scaleStart", "scale"),
    "TRANSFORM_OT_edge_slide": ("toggleGeometrySlide", "move"),
    "TRANSFORM_OT_vert_slide": ("toggleGeometrySlide", "move"),
    "TRANSFORM_OT_mirror": ("mirrorModal", "scale"),
    "MESH_OT_loopcut_slide": ("loopCut", None),
    "MESH_OT_loopcut": ("loopCut", None),
    "MESH_OT_extrude_region_move": ("extrude", "extrudeMotion"),
    "MESH_OT_extrude_faces_move": ("extrude", "extrudeMotion"),
    "MESH_OT_extrude_edges_move": ("extrude", "extrudeMotion"),
    "MESH_OT_extrude_vertices_move": ("extrude", "extrudeMotion"),
    "MESH_OT_extrude_manifold": ("extrude", "extrudeMotion"),
    "MESH_OT_extrude_region_shrink_fatten": ("extrude", "extrudeMotion"),
    "MESH_OT_extrude_individual_move": ("extrude", "extrudeMotion"),
    "MESH_OT_inset": ("inset", "insetMotion"),
    "MESH_OT_bevel": ("bevel", "bevelMotion"),
    "MESH_OT_knife_tool": ("cutter", None),
    "VIEW3D_OT_rotate": (None, "orbit"),
    "VIEW3D_OT_move": (None, "pan"),
    "VIEW3D_OT_zoom": (None, None),
    "VIEW3D_OT_select_box": (None, "boxSelect"),
    "VIEW3D_OT_select_lasso": (None, "lassoSelect"),
    "VIEW3D_OT_select_circle": ("sphereSelect", None),
    "UV_OT_select_box": (None, "boxSelect"),
    "UV_OT_select_lasso": (None, "lassoSelect"),
    "UV_OT_select_circle": ("sphereSelect", None),
    "SCULPT_OT_brush_stroke": ("sculptBrushStart", "sculptBrushStroke"),
    "PAINT_OT_image_paint": ("textureBrushStart", "textureBrushStroke"),
}
BRUSH_STROKES = {"SCULPT_OT_brush_stroke", "PAINT_OT_image_paint"}
LOOP_CUTS = {"MESH_OT_loopcut", "MESH_OT_loopcut_slide"}
WHEEL = {"WHEELUPMOUSE", "WHEELDOWNMOUSE", "WHEELINMOUSE", "WHEELOUTMOUSE"}
MOUSE_MOTION = {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"}
CTRL_KEYS = {"LEFT_CTRL", "RIGHT_CTRL"}
SNAP_ELEMENTS = {"INCREMENT", "GRID"}
SNAP_CUES = {"move": "moveSnap", "rotate": "rotateSnap", "scale": "scaleSnap"}
MODE_SOUNDS = {"EDIT": ("enterModeling", "exitModeling"), "SCULPT": ("enterSculpt", "exitSculpt"),
               "TEXTURE_PAINT": ("enterTexture", "exitTexture")}
SELECTION_GESTURES = {key for key in MODAL if "_OT_select_" in key}
SHOT = {
    "OBJECT_OT_duplicate": "duplicate", "OBJECT_OT_duplicate_move": "duplicate",
    "OBJECT_OT_duplicate_move_linked": "duplicate", "MESH_OT_duplicate": "duplicate",
    "MESH_OT_duplicate_move": "duplicate", "OBJECT_OT_delete": "delete", "MESH_OT_delete": "delete",
    "MESH_OT_delete_edgeloop": "delete", "MESH_OT_merge": "merge",
    "MESH_OT_remove_doubles": "merge", "MESH_OT_edge_face_add": "fill",
    "MESH_OT_fill": "fill", "MESH_OT_fill_grid": "fill", "MESH_OT_separate": "separate",
    "OBJECT_OT_join": "join", "MESH_OT_subdivide": "subdivide", "MESH_OT_unsubdivide": "unsubdivide",
    "MESH_OT_flip_normals": "normals", "MESH_OT_normals_make_consistent": "normals",
    "OBJECT_OT_voxel_remesh": "remesh", "OBJECT_OT_quadriflow_remesh": "remesh",
    "MESH_OT_loop_select": "loopSelection", "MESH_OT_edgering_select": "loopSelection",
    "VIEW3D_OT_snap_selected_to_cursor": "teleport", "VIEW3D_OT_snap_selected_to_active": "teleport",
    "TRANSFORM_OT_snap_selected_to_surface": "snapSurface",
    "OBJECT_OT_location_clear": "resetTransform", "OBJECT_OT_rotation_clear": "resetTransform",
    "OBJECT_OT_scale_clear": "resetTransform",
    "OBJECT_OT_modifier_remove": "modifierRemove", "OBJECT_OT_modifier_apply": "modifierApply",
}
PRIMITIVE_PREFIXES = ("MESH_OT_primitive_", "CURVE_OT_primitive_", "SURFACE_OT_primitive_")


@dataclass
class WindowState:
    serial: int = 0
    native: tuple = ()
    history: tuple = ()
    xy: tuple = (0, 0)
    mode: str = ""
    next_mode_check: float = 0.0
    vertex_mode: tuple = ()
    uv: bool = False
    view_state: tuple = ()
    snap: tuple = ()
    xray: bool | None = None
    view_area: int = 0
    finish: str = ""
    axis: tuple = ()
    transform_kind: str = ""
    ctrl: bool = False
    mouse_motion: bool = False
    snap_value: tuple = ()
    snap_vertex_indices: tuple | None = None
    brush: str = ""
    box: str = ""
    select_subtract: bool = False
    select_check: tuple = ()
    select_check_until: float = 0.0
    drag_start: tuple = (0, 0)
    did_drag: bool = False
    previous_axis_key: str = ""
    loop_stage: str = ""
    ring: object = None
    ring_key: object = None
    last_ring_xy: tuple = ()
    modifier_active: bool = False
    modifier_until: float = 0.0
    modifier_values: dict = field(default_factory=dict)
    modifier_delta: tuple = (0, 0)
    primitive_stamp: tuple = ()


def sync(prefs):
    global ENABLED, SETTINGS
    theme = active_theme(prefs)
    paths = {
        key: tuple(resolve_clip(key, clip) for clip in entry["clips"])
        for key in LABELS
        if (entry := entry_of(theme, key))["enabled"] and entry["clips"]
    }
    bounds = (prefs.speed_low, prefs.speed_high, prefs.pitch_low, prefs.pitch_high, prefs.rate_low, prefs.rate_high)
    enabled = prefs.volume > 0
    settings = (paths, bounds)
    if enabled != ENABLED or settings != SETTINGS:
        AUDIO.configure(paths, bounds, prefs.volume)
        if not enabled:
            WINDOWS.clear()
    else:
        AUDIO.volume = prefs.volume
    SETTINGS, ENABLED = settings, enabled
    if ENABLED:
        ensure_tick()


def preview(prefs, key, path):
    AUDIO.volume = prefs.volume
    AUDIO.play(key, preview=path)
    ensure_tick()


def bottom_area(window, x, y):
    if window.screen:
        for area in window.screen.areas:
            if area.x <= x < area.x + area.width and area.y <= y < area.y + area.height:
                return area
    return None


def window_region(area, x, y):
    if area and area.type in {"VIEW_3D", "IMAGE_EDITOR", "PROPERTIES"}:
        for region in area.regions:
            if region.type == "WINDOW" and region.x <= x < region.x + region.width and region.y <= y < region.y + region.height:
                return region
    return None


def pointed_region(window, state):
    area = bottom_area(window, *state.xy)
    return area, window_region(area, *state.xy)


def modal_handlers(window, serial):
    native = None
    watching = False
    for op in window.modal_operators:
        key = op.bl_idname
        if key == "SECRET_SOUNDS_OT_observe" and getattr(op.properties, "serial", None) == serial:
            watching = True
        elif native is None and key in MODAL:
            native = op
    return native, watching


def modes(window, state):
    scene = window.scene
    obj = window.view_layer.objects.active
    mode = obj.mode if obj else "OBJECT"
    if state.mode and mode != state.mode:
        if state.mode in MODE_SOUNDS:
            AUDIO.play(MODE_SOUNDS[state.mode][1])
        if mode in MODE_SOUNDS:
            AUDIO.play(MODE_SOUNDS[mode][0])
    state.mode = mode
    tool = scene.tool_settings
    selection = tuple(tool.mesh_select_mode) if mode == "EDIT" and obj.type == "MESH" else ()
    if state.vertex_mode and selection != state.vertex_mode:
        for key, old, new in zip(("vertexMode", "edgeMode", "faceMode"), state.vertex_mode, selection):
            if new and not old:
                AUDIO.play(key)
    state.vertex_mode = selection
    orientation = scene.transform_orientation_slots[0].type
    pivot = tool.transform_pivot_point
    attrs = getattr(tool, "use_transform_correct_face_attributes", False)
    view = (orientation, pivot, attrs)
    if state.view_state:
        old_orientation, old_pivot, old_attrs = state.view_state
        if orientation != old_orientation:
            AUDIO.play("coordinates")
        if pivot != old_pivot and pivot in {"INDIVIDUAL_ORIGINS", "CURSOR"}:
            AUDIO.play("individualOrigins" if pivot == "INDIVIDUAL_ORIGINS" else "reanchorPivot")
        if attrs != old_attrs:
            AUDIO.play("correctFaceAttributes")
    state.view_state = view
    snap = (tool.use_snap, frozenset(tool.snap_elements))
    if state.snap and snap != state.snap:
        AUDIO.play("toggleSnap" if snap[1] & {"INCREMENT", "GRID"} else "toggleSurfaceSnap")
    state.snap = snap
    area, region = pointed_region(window, state)
    if area and region:
        uv = area.type == "IMAGE_EDITOR" and area.ui_type == "UV"
        if uv and not state.uv:
            AUDIO.play("uvMode")
        state.uv = uv
        if area.type == "VIEW_3D":
            shading = area.spaces.active.shading
            xray = shading.show_xray if shading.type == "SOLID" else shading.show_xray_wireframe
            if state.xray is not None and state.xray != xray and state.view_area == area.as_pointer():
                AUDIO.play("xRay")
            state.xray, state.view_area = xray, area.as_pointer()
    return obj


def selection_stamp(window, obj, area=None):
    if obj and obj.type == "MESH" and obj.mode == "EDIT":
        data = obj.data
        counts = data.total_vert_sel, data.total_edge_sel, data.total_face_sel
        active = None
        if any(counts):
            mesh = bmesh.from_edit_mesh(data)
            active = mesh.select_history.active
            if active is None and mesh.faces.active and mesh.faces.active.select:
                active = mesh.faces.active
        return obj.as_pointer(), counts, hash(active) if active is not None else None
    if area is None:
        area = next((area for area in window.screen.areas if area.type == "VIEW_3D"), None)
    with bpy.context.temp_override(window=window, area=area):
        selected = bpy.context.selected_objects
        count = len(selected) if selected is not None else sum(item.select_get() for item in window.view_layer.objects)
    return obj.as_pointer() if obj else 0, (count,), None


def finish_click(window, state, now, obj=None):
    if not state.select_check or state.did_drag:
        return
    if now > state.select_check_until:
        state.select_check = ()
        return
    current = selection_stamp(window, obj or window.view_layer.objects.active)
    if current != state.select_check:
        AUDIO.play("deselectAll" if state.select_subtract or not any(current[1]) else "select")
        state.select_check = ()


def transform_value(obj, key, state):
    if key not in SNAP_CUES or not obj:
        return ()
    if obj.mode == "EDIT" and obj.type == "MESH":
        # Blender invalidates Python BMesh elements during edit-mode redraw.
        # Re-read the active element or look up the same selected vertices.
        mesh = bmesh.from_edit_mesh(obj.data)
        active = mesh.select_history.active
        if active is None and mesh.faces.active and mesh.faces.active.select:
            active = mesh.faces.active
        if isinstance(active, bmesh.types.BMVert):
            vertices = (active,)
        elif active is not None:
            vertices = islice(active.verts, 4)
        else:
            indices = state.snap_vertex_indices
            if indices is None:
                if not obj.data.total_vert_sel:
                    return ()
                selected = tuple(islice(((i, v) for i, v in enumerate(mesh.verts) if v.select), 4))
                state.snap_vertex_indices = tuple(i for i, _ in selected)
                vertices = (v for _, v in selected)
            elif not indices:
                return ()
            elif indices[-1] < 64:
                vertices = (v for i, v in enumerate(islice(mesh.verts, indices[-1] + 1)) if i in indices)
            else:
                mesh.verts.ensure_lookup_table()
                vertices = (mesh.verts[i] for i in indices)
        return tuple(round(value, 5) for vertex in vertices for value in vertex.co)
    if key == "move":
        return tuple(round(value, 5) for value in obj.location)
    if key == "scale":
        return tuple(round(value, 6) for value in obj.scale)
    rotation = {"QUATERNION": "rotation_quaternion", "AXIS_ANGLE": "rotation_axis_angle"}.get(obj.rotation_mode, "rotation_euler")
    return tuple(round(value, 6) for value in getattr(obj, rotation))


def incremental(state):
    return bool(state.snap and state.snap[1] & SNAP_ELEMENTS and state.snap[0] != state.ctrl)


def check_snap(obj, state, key):
    if not state.mouse_motion:
        return
    state.mouse_motion = False
    try:
        value = transform_value(obj, key, state)
    except (ReferenceError, RuntimeError):
        state.snap_vertex_indices = None
        state.snap_value = ()
        return
    if value and state.snap_value and value != state.snap_value:
        AUDIO.play(SNAP_CUES[key])
    state.snap_value = value


def start_modal(window, state, op):
    key = op.bl_idname
    action, motion = MODAL[key]
    if action and (key not in BRUSH_STROKES or state.brush != motion):
        AUDIO.play(action)
    state.finish = ""
    state.axis = ()
    state.previous_axis_key = ""
    state.transform_kind = motion if motion in {"move", "rotate", "scale"} else ""
    state.ctrl = False
    if state.transform_kind:
        tool = window.scene.tool_settings
        state.snap = tool.use_snap, frozenset(tool.snap_elements)
    state.snap_value = ()
    state.snap_vertex_indices = None
    state.loop_stage = "TARGET" if key in LOOP_CUTS else ""
    state.ring = None
    state.ring_key = None
    state.last_ring_xy = ()


def end_modal(state, key):
    AUDIO.stop_motion()
    if key in SELECTION_GESTURES:
        if state.finish != "cancel":
            AUDIO.play("deselectAll" if state.select_subtract else "select")
    elif key not in BRUSH_STROKES and not key.startswith("VIEW3D_OT_"):
        AUDIO.play(state.finish or "confirm")
    state.finish = ""
    state.ring = None
    state.loop_stage = ""
    state.mouse_motion = False


def mouse_button(event):
    return event.type in {"LEFTMOUSE", "RIGHTMOUSE", "MIDDLEMOUSE"}


def handle_modal(window, state, event, now):
    key = state.native[0]
    _, motion = MODAL[key]
    if state.transform_kind:
        motion = state.transform_kind
    pressed = event.value == "PRESS" and not event.is_repeat
    moving = event.type in MOUSE_MOTION
    if motion in SNAP_CUES:
        ctrl = event.value == "PRESS" if event.type in CTRL_KEYS and pressed else event.ctrl
        if event.type in CTRL_KEYS:
            tool = window.scene.tool_settings
            state.snap = tool.use_snap, frozenset(tool.snap_elements)
        if state.mouse_motion:
            check_snap(window.view_layer.objects.active, state, motion)
        if ctrl != state.ctrl:
            state.ctrl = ctrl
            state.snap_value = ()
            if incremental(state):
                AUDIO.stop_motion(now)
        if moving and incremental(state):
            if AUDIO.paths.get(SNAP_CUES[motion]):
                if not state.snap_value:
                    try:
                        state.snap_value = transform_value(window.view_layer.objects.active, motion, state)
                    except (ReferenceError, RuntimeError):
                        state.snap_vertex_indices = None
                state.mouse_motion = True
            return
    if moving:
        if key in LOOP_CUTS and state.loop_stage == "SLIDE":
            motion = "loopCutSlide"
        if motion:
            AUDIO.motion(motion, event.mouse_x - event.mouse_prev_x, event.mouse_y - event.mouse_prev_y, now)
        return
    if event.type in WHEEL:
        if key in LOOP_CUTS and state.loop_stage == "TARGET":
            AUDIO.play("loopCutCount", wheel=True)
        elif key == "MESH_OT_bevel":
            AUDIO.play("bevelSegments", wheel=True)
        return
    if key in SELECTION_GESTURES:
        if mouse_button(event) and (pressed or event.value == "RELEASE"):
            if event.type == "MIDDLEMOUSE" or event.shift or event.ctrl:
                state.select_subtract = True
        if pressed and event.type in {"ESC", "RIGHTMOUSE"}:
            state.finish = "cancel"
        return
    if key in LOOP_CUTS and pressed:
        if state.loop_stage == "TARGET":
            if event.type == "LEFTMOUSE":
                state.loop_stage = "SLIDE"
                state.ring = None
            elif event.type in {"ESC", "RIGHTMOUSE"}:
                state.finish = "cancel"
        elif event.type == "RIGHTMOUSE":
            state.finish = "confirm"
            AUDIO.play("loopCutMidpoint")
        elif event.type == "ESC":
            state.finish = "cancel"
        return
    if key in BRUSH_STROKES:
        return
    if not pressed:
        if state.axis and event.type in {"LEFT_SHIFT", "RIGHT_SHIFT"} and event.value == "RELEASE":
            state.previous_axis_key = ""
        return
    if event.type in {"ESC", "RIGHTMOUSE"}:
        state.finish = "cancel"
    elif event.type in {"RET", "NUMPAD_ENTER", "LEFTMOUSE", "SPACE"}:
        state.finish = "confirm"
    if state.transform_kind and key != "TRANSFORM_OT_mirror":
        gesture = {"G": "move", "R": "rotate", "S": "scale"}.get(event.type)
        if gesture and not (event.ctrl or event.shift or event.alt):
            if gesture != state.transform_kind:
                state.transform_kind = motion = gesture
                state.axis = ()
                state.previous_axis_key = ""
                state.snap_value = ()
                AUDIO.stop_motion(now)
                AUDIO.play(gesture + "Start")
            elif gesture == "move" and state.mode == "EDIT":
                AUDIO.play("toggleGeometrySlide")
    if motion in {"move", "rotate", "scale"}:
        if event.type == "C" and state.axis:
            state.axis = ()
            state.previous_axis_key = ""
            AUDIO.play("unlockAxis")
        if event.type in {"X", "Y", "Z"} and event.type != state.previous_axis_key:
            state.axis = (event.type, event.shift, 1)
            AUDIO.play("lockAxis")
        elif event.type in {"X", "Y", "Z"}:
            axis, plane, presses = state.axis or (event.type, event.shift, 0)
            presses = (presses + 1) % 3
            state.axis = (axis, plane, presses)
            AUDIO.play("lockAxis" if presses else "unlockAxis")
        if event.type in {"X", "Y", "Z"}:
            state.previous_axis_key = event.type
    if event.type in {"LEFT_SHIFT", "RIGHT_SHIFT"} and motion:
        AUDIO.play("togglePrecision")
    if event.type in {"LEFT_CTRL", "RIGHT_CTRL"} and motion:
        AUDIO.stop_motion(now)
        AUDIO.play("toggleSnap" if state.snap and state.snap[1] & SNAP_ELEMENTS else "toggleSurfaceSnap")
    if key == "MESH_OT_inset" and event.type == "I":
        AUDIO.play("insetIndividual")


def modifier_values(obj):
    values = {}
    if obj:
        for mod in obj.modifiers:
            if mod.type == "ARRAY":
                values[mod.as_pointer()] = (mod.count, tuple(mod.relative_offset_displace), tuple(mod.constant_offset_displace))
            elif mod.type == "NODES" and mod.node_group and "array" in mod.node_group.name.casefold():
                inputs = {}
                for item in mod.node_group.interface.items_tree:
                    if item.item_type != "SOCKET" or item.in_out != "INPUT":
                        continue
                    default = getattr(item, "default_value", None)
                    value = mod.get(item.identifier, default)
                    if isinstance(value, (int, float)):
                        inputs[item.name] = value
                    elif value is not None and hasattr(value, "__len__") and not isinstance(value, str):
                        inputs[item.name] = tuple(value)
                count = next((value for name, value in inputs.items() if "count" in name.casefold() and isinstance(value, int)), 0)
                values[mod.as_pointer()] = count, tuple((name, value) for name, value in inputs.items() if "count" not in name.casefold())
            else:
                # Read only common numeric controls, and only during a
                # Properties gesture. Never walk every RNA property each tick.
                numeric = tuple(getattr(mod, name, None) for name in
                                ("width", "thickness", "strength", "factor", "levels", "segments", "angle", "ratio", "iterations"))
                values[mod.as_pointer()] = (0, None, numeric)
    return values


def sample_modifiers(state, obj, now):
    previous = state.modifier_values
    current = modifier_values(obj)
    delta = state.modifier_delta
    if previous:
        added = current.keys() - previous.keys()
        if added:
            AUDIO.play("modifierAdd", len(added))
        for ptr in previous.keys() & current.keys():
            old, new = previous[ptr], current[ptr]
            if old[0] != new[0]:
                AUDIO.play("modifierCount", abs(new[0] - old[0]))
            if old[1] != new[1]:
                AUDIO.motion("modifierSpacing", *delta, now)
            if len(old) > 2 and len(new) > 2 and old[2] != new[2]:
                AUDIO.play("modifierValue")
    state.modifier_values = current
    state.modifier_delta = (0, 0)


def handle_input(window, state, event, now):
    event_type = event.type
    position = event.mouse_x, event.mouse_y
    state.xy = position
    if event_type == "WINDOW_DEACTIVATE":
        state.brush = state.box = ""
        state.modifier_active = False
        state.select_check = ()
        state.ctrl = state.mouse_motion = False
        state.snap_value = ()
        AUDIO.stop_motion(now)
        return
    if event_type not in MOUSE_MOTION:
        refresh_native(window, state, modal_handlers(window, state.serial)[0])
    if state.native:
        handle_modal(window, state, event, now)
        return
    if event_type in MOUSE_MOTION:
        dx, dy = event.mouse_x - event.mouse_prev_x, event.mouse_y - event.mouse_prev_y
        if state.brush:
            AUDIO.motion(state.brush, dx, dy, now)
        elif state.box:
            x, y = state.drag_start
            if (position[0] - x) ** 2 + (position[1] - y) ** 2 > 25:
                state.did_drag = True
                AUDIO.motion(state.box, dx, dy, now)
        elif state.modifier_active:
            state.modifier_delta = (state.modifier_delta[0] + dx, state.modifier_delta[1] + dy)
        return

    if event_type == "NONE":
        return
    if event_type == "LEFTMOUSE" and event.value == "RELEASE":
        if state.brush or state.box:
            AUDIO.stop_motion(now)
        if state.box and state.did_drag:
            AUDIO.play("deselectAll" if state.select_subtract else "select")
            state.select_check = ()
        state.brush = state.box = ""
        finish_click(window, state, now)
        if state.modifier_active:
            state.modifier_until = now + 0.08
            state.modifier_active = False
    if event_type not in WHEEL and event_type not in {
        "LEFTMOUSE", "TRACKPADZOOM", "TRACKPADPAN", "MOUSEROTATE", "RET", "NUMPAD_ENTER"
    }:
        return
    area, region = pointed_region(window, state)
    if not area or not region:
        return
    if area.type == "PROPERTIES" and area.spaces.active.context == "MODIFIER":
        if event_type == "LEFTMOUSE" and event.value == "PRESS":
            state.modifier_active = True
            state.modifier_delta = (0, 0)
            state.modifier_values = modifier_values(window.view_layer.objects.active)
        elif event_type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE", "RET", "NUMPAD_ENTER"}:
            if not state.modifier_active:
                state.modifier_values = modifier_values(window.view_layer.objects.active)
                state.modifier_until = now + 0.08
        return
    if area.type not in {"VIEW_3D", "IMAGE_EDITOR"}:
        return
    if event_type in WHEEL or event_type == "TRACKPADZOOM":
        if not event.shift and not event.ctrl and not event.alt:
            AUDIO.play("zoom", wheel=event_type in WHEEL)
        return
    if event_type in {"TRACKPADPAN", "MOUSEROTATE"}:
        AUDIO.motion("pan" if event.shift or area.type == "IMAGE_EDITOR" else "orbit",
                     event.mouse_x - event.mouse_prev_x, event.mouse_y - event.mouse_prev_y, now)
        return
    if event_type != "LEFTMOUSE" or event.value != "PRESS":
        return
    obj = window.view_layer.objects.active
    if area.type == "VIEW_3D" and obj and obj.mode in {"SCULPT", "TEXTURE_PAINT"} and not event.alt:
        prefix = "sculpt" if obj.mode == "SCULPT" else "texture"
        AUDIO.play(prefix + "BrushStart")
        state.brush = prefix + "BrushStroke"
        return
    finish_click(window, state, now, obj)
    state.did_drag = False
    state.select_check = selection_stamp(window, obj, area)
    state.select_check_until = now + 0.14
    state.select_subtract = event.ctrl
    if area.type == "VIEW_3D":
        tool = window.workspace.tools.from_space_view3d_mode(bpy.context.mode)
        tool_name = tool.idname if tool else ""
        if tool_name in {"builtin.select_box", "builtin.select_lasso"}:
            state.box = "boxSelect" if tool_name.endswith("box") else "lassoSelect"
            state.drag_start = position
            state.did_drag = False


def history(state, wm):
    if len(wm.operators) == 0:
        return False
    op = wm.operators[-1]
    key = op.bl_idname
    signature = key, op.as_pointer()
    primitive = key.startswith(PRIMITIVE_PREFIXES)
    if primitive and state.history == signature:
        keys = ("vertices", "segments", "ring_count", "subdivisions", "radius", "radius1", "radius2",
                "depth", "size", "major_radius", "minor_radius", "end_fill_type", "calc_uvs", "align")
        stamp = tuple(getattr(op.properties, name, None) for name in keys)
        if state.primitive_stamp and stamp != state.primitive_stamp:
            AUDIO.play("modifierValue")
        state.primitive_stamp = stamp
    if state.history == signature:
        return False
    previous = state.history
    state.history = signature
    state.primitive_stamp = ()
    if not previous:
        return False
    if key.startswith("MESH_OT_dissolve_"):
        AUDIO.play("dissolve")
    elif key.endswith("_select_all"):
        action = getattr(op.properties, "action", "TOGGLE")
        AUDIO.play("deselectAll" if action == "DESELECT" else "selectAll")
        return True
    elif key in {"MESH_OT_select_linked", "MESH_OT_select_linked_pick", "UV_OT_select_linked", "UV_OT_select_linked_pick"}:
        AUDIO.play("deselectAll" if getattr(op.properties, "deselect", False) else "select")
        return True
    elif key.startswith(("UV_OT_unwrap", "UV_OT_smart_project", "UV_OT_cube_project", "UV_OT_project_from_view", "UV_OT_lightmap_pack")):
        AUDIO.play("uvProjection")
    elif key in {"OBJECT_OT_modifier_add", "OBJECT_OT_modifier_add_node_group"}:
        is_array = getattr(op.properties, "type", "") == "ARRAY" or "array" in getattr(op.properties, "relative_asset_identifier", "").casefold()
        AUDIO.play("arrayModal" if is_array else "modifierAdd")
    elif primitive:
        AUDIO.play("createPrimitive")
    elif key in SHOT:
        AUDIO.play(SHOT[key])
        return key in {"MESH_OT_loop_select", "MESH_OT_edgering_select"}
    return False


def update_ring(state, obj, window):
    if not AUDIO.paths.get("loopCutTarget") or not obj or obj.type != "MESH" or obj.mode != "EDIT" or state.last_ring_xy == state.xy:
        return
    area, region = pointed_region(window, state)
    if not area or not region or area.type != "VIEW_3D":
        return
    state.last_ring_xy = state.xy
    try:
        if state.ring is None:
            state.ring = RingPicker(obj)
        result = state.ring.pick(area, region, state.xy)
    except (ReferenceError, RuntimeError, ValueError, IndexError):
        state.ring = None
        return
    if result is not None:
        if state.ring_key is None or result != state.ring_key:
            AUDIO.play("loopCutTarget")
        state.ring_key = result


def refresh_native(window, state, op):
    native = (op.bl_idname, op.as_pointer()) if op else ()
    before = state.native
    if before and before[0] in LOOP_CUTS and state.loop_stage == "SLIDE" and native and native[0] == "TRANSFORM_OT_edge_slide":
        native = before[0], native[1]
    if native != before:
        previous_loop_slide = before and before[0] in LOOP_CUTS and state.loop_stage == "SLIDE"
        new_slide = native and native[0] in LOOP_CUTS
        if before and not (previous_loop_slide and new_slide):
            end_modal(state, before[0])
        state.native = native
        if native:
            if previous_loop_slide and new_slide:
                state.native = (before[0], native[1])
                state.loop_stage = "SLIDE"
            else:
                start_modal(window, state, op)
                if native[0] in SELECTION_GESTURES:
                    state.select_subtract = getattr(op.properties, "mode", "") in {"SUB", "AND"} or (
                        state.select_subtract and bool(state.select_check))
            state.brush = state.box = ""
            state.select_check = ()

def update_window(wm, window, state, now, active):
    if now >= state.next_mode_check:
        obj = modes(window, state)
        state.next_mode_check = now + 0.12
    else:
        obj = window.view_layer.objects.active
    op, watching = modal_handlers(window, state.serial)
    refresh_native(window, state, op)
    if not watching:
        global NEXT_OBSERVER
        NEXT_OBSERVER += 1
        state.serial = NEXT_OBSERVER
        try:
            with bpy.context.temp_override(window=window):
                bpy.ops.secret_sounds.observe("INVOKE_DEFAULT", serial=state.serial)
        except RuntimeError:
            state.serial = 0

    if state.native:
        kind = state.native[0]
        if kind in LOOP_CUTS and state.loop_stage == "TARGET":
            update_ring(state, obj, window)
        elif state.transform_kind:
            check_snap(obj, state, state.transform_kind)
    else:
        sounded = history(state, wm) if active else False
        if state.select_check and not state.box:
            if sounded:
                state.select_check = ()
            else:
                finish_click(window, state, now, obj)
    if state.modifier_active or now < state.modifier_until:
        sample_modifiers(state, obj, now)


class SECRET_SOUNDS_OT_observe(bpy.types.Operator):
    bl_idname = "secret_sounds.observe"
    bl_label = "Secret Sounds Input Observer"
    bl_options = {"INTERNAL", "MODAL_PRIORITY"}

    serial: IntProperty(options={"HIDDEN", "SKIP_SAVE"})

    def invoke(self, context, _event):
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if not ENABLED or not context.window:
            return {"FINISHED", "PASS_THROUGH"}
        state = WINDOWS.get(context.window.as_pointer())
        if state is None:
            return {"FINISHED", "PASS_THROUGH"}
        if self.serial != state.serial:
            return {"FINISHED", "PASS_THROUGH"}
        event_type = event.type
        if event_type.startswith("TIMER"):
            return {"PASS_THROUGH"}
        if event_type in MOUSE_MOTION and not (state.native or state.brush or state.box or state.modifier_active):
            state.xy = event.mouse_x, event.mouse_y
            return {"PASS_THROUGH"}
        handle_input(context.window, state, event, perf_counter())
        return {"PASS_THROUGH"}


def tick():
    now = perf_counter()
    if ENABLED:
        try:
            wm = bpy.context.window_manager
            if wm and not bpy.app.background:
                current = set()
                active = bpy.context.window or (wm.windows[0] if len(wm.windows) else None)
                for window in wm.windows:
                    if not window.scene or not window.screen or window.screen.is_temporary:
                        continue
                    pointer = window.as_pointer()
                    current.add(pointer)
                    state = WINDOWS.get(pointer)
                    if state is None:
                        state = WINDOWS[pointer] = WindowState()
                    update_window(wm, window, state, now, window == active)
                for stale in WINDOWS.keys() - current:
                    del WINDOWS[stale]
        except (ReferenceError, RuntimeError, AttributeError, ValueError) as exc:
            AUDIO.error = f"Could not observe Blender action ({exc})"
        if AUDIO.warming:
            AUDIO.warm()
    if AUDIO.jobs or AUDIO.pending or AUDIO.wheel or AUDIO.shots or AUDIO.tails or AUDIO.gesture:
        AUDIO.tick(now)
    busy = AUDIO.gesture or AUDIO.pending or AUDIO.wheel or AUDIO.tails or any(
        state.native or state.brush or state.box or state.modifier_active for state in WINDOWS.values())
    if busy or AUDIO.shots or AUDIO.jobs:
        return 0.012 if busy else 0.04
    return 0.04 if ENABLED else None


@persistent
def on_load_pre(*_args):
    WINDOWS.clear()
    AUDIO.clear()


@persistent
def on_load_post(*_args):
    prefs = preferences()
    if prefs:
        sync(prefs)


def handler(cue):
    @persistent
    def play(*_args):
        if ENABLED:
            AUDIO.play(cue)
    return play


HANDLERS = (
    (bpy.app.handlers.load_pre, on_load_pre), (bpy.app.handlers.load_post, on_load_post),
    (bpy.app.handlers.save_post, handler("saveProject")), (bpy.app.handlers.render_init, handler("renderStart")),
    (bpy.app.handlers.undo_post, handler("undo")), (bpy.app.handlers.redo_post, handler("redo")),
)


def ensure_tick():
    if not bpy.app.timers.is_registered(tick):
        bpy.app.timers.register(tick, first_interval=0.0, persistent=True)


def start():
    for hooks, callback in HANDLERS:
        hooks.append(callback)
    prefs = preferences()
    if prefs:
        sync(prefs)


def stop():
    global ENABLED, SETTINGS
    ENABLED, SETTINGS = False, None
    if bpy.app.timers.is_registered(tick):
        bpy.app.timers.unregister(tick)
    for hooks, callback in HANDLERS:
        if callback in hooks:
            hooks.remove(callback)
    WINDOWS.clear()
    AUDIO.close()
