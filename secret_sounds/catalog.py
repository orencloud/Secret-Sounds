"""Operation names and defaults shared by the add-on and the profile packer."""

GROUPS = {
    "Modes": {
        "enterModeling": "Enter Edit Mode", "exitModeling": "Exit Edit Mode",
        "enterSculpt": "Enter Sculpt Mode", "exitSculpt": "Exit Sculpt Mode",
        "enterTexture": "Enter Texture Paint", "exitTexture": "Exit Texture Paint",
        "vertexMode": "Vertex Selection", "edgeMode": "Edge Selection",
        "faceMode": "Face Selection", "uvMode": "UV Editor",
    },
    "Transform": {
        "moveStart": "Move Start", "move": "Move", "moveSnap": "Move Snap",
        "rotateStart": "Rotate Start", "rotate": "Rotate", "rotateSnap": "Rotate Snap",
        "scaleStart": "Scale Start", "scale": "Scale", "scaleSnap": "Scale Snap",
        "lockAxis": "Lock Axis or Plane", "unlockAxis": "Unlock Axis or Plane",
        "coordinates": "Transform Orientation", "resetTransform": "Reset Transform",
        "snapSurface": "Snap to Surface", "teleport": "Snap Selection to Cursor",
        "togglePrecision": "Precision", "toggleSnap": "Increment Snap",
        "toggleSurfaceSnap": "Surface Snap Toggle", "toggleGeometrySlide": "Slide Mode",
        "individualOrigins": "Individual Origins", "reanchorPivot": "3D Cursor Pivot",
        "correctFaceAttributes": "Correct Face Attributes", "confirm": "Modal Confirm",
        "cancel": "Modal Cancel",
    },
    "Mesh": {
        "loopCut": "Loop Cut Start", "loopCutTarget": "Loop Cut Target",
        "loopCutCount": "Loop Cut Count", "loopCutSlide": "Loop Cut Slide",
        "loopCutMidpoint": "Loop Cut Midpoint", "extrude": "Extrude Start",
        "extrudeMotion": "Extrude Motion", "inset": "Inset Start",
        "insetMotion": "Inset Motion", "insetIndividual": "Individual Inset",
        "bevel": "Bevel Start", "bevelMotion": "Bevel Motion",
        "bevelSegments": "Bevel Segment Count", "cutter": "Knife",
        "merge": "Merge", "dissolve": "Dissolve", "fill": "Fill",
        "separate": "Separate", "join": "Join", "createPrimitive": "Create Primitive",
        "subdivide": "Subdivide", "unsubdivide": "Unsubdivide", "normals": "Edit Normals",
        "remesh": "Remesh", "uvProjection": "UV Unwrap or Projection",
    },
    "Selection": {
        "select": "Select", "selectAll": "Select All", "deselectAll": "Deselect",
        "boxSelect": "Box Drag", "lassoSelect": "Lasso Drag", "sphereSelect": "Circle Select",
        "loopSelection": "Loop Selection",
    },
    "Viewport": {"zoom": "Zoom", "pan": "Pan", "orbit": "Orbit", "xRay": "X-Ray"},
    "Modifiers": {
        "modifierAdd": "Add Modifier", "modifierRemove": "Remove Modifier",
        "modifierApply": "Apply Modifier", "modifierCount": "Array Count",
        "modifierSpacing": "Array Spacing", "modifierValue": "Other Values or Edit Primitive",
        "arrayModal": "Interactive Array", "mirrorModal": "Mirror",
    },
    "Brushes": {
        "sculptBrushStart": "Sculpt Brush Start", "sculptBrushStroke": "Sculpt Stroke",
        "textureBrushStart": "Texture Brush Start", "textureBrushStroke": "Texture Stroke",
    },
    "Project and Edit": {
        "saveProject": "Save", "renderStart": "Render Start", "duplicate": "Duplicate",
        "delete": "Delete", "undo": "Undo", "redo": "Redo",
    },
}
LABELS = {key: label for operations in GROUPS.values() for key, label in operations.items()}
MOTION = frozenset({
    "move", "rotate", "scale", "pan", "orbit", "boxSelect", "lassoSelect",
    "loopCutSlide", "extrudeMotion", "insetMotion", "bevelMotion", "modifierSpacing",
    "sculptBrushStroke", "textureBrushStroke",
})
SECONDARY = frozenset({
    "togglePrecision", "toggleSnap", "toggleSurfaceSnap", "toggleGeometrySlide",
    "individualOrigins", "loopCutMidpoint", "reanchorPivot",
})
DEFAULT_CLIP = {
    key: "sounds/" + ("DefaultLoop.wav" if key in MOTION else
                     "SecondaryTransform.mp3" if key in SECONDARY else "Default.wav")
    for key in LABELS
}

# The bundled theme uses the recorded bevel cues from the Unreal profile.
DEFAULT_CLIP.update({
    "bevel": "sounds/2026-11-22 12-25-17_9.mp3",
    "bevelMotion": "sounds/sd_8.mp3",
    "bevelSegments": "sounds/2026-11-22 12-25-17_6.mp3",
})
