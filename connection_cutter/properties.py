"""Scene-level state for Connection Cutter.

Holds a reference to the object being cut plus the list of connectors
staged on the current seam (populated by operators in
operators/connectors.py, consumed by CC_OT_apply_connectors). The cut
plane's actual transform lives on the CC_Cut_Plane helper object itself
(see plane_helper.py) - Blender's native gizmos pose that object directly.
"""

import bpy

CONNECTOR_KIND_ITEMS = (
    ('PLUG', "Plug", "Cylindrical plug / dowel connector"),
    ('DOVETAIL', "Dovetail", "Tapered dovetail key connector"),
    ('SNAP', "Snap-Fit", "Cylindrical connector with a snap-fit retaining groove"),
)


class CC_ConnectorItem(bpy.types.PropertyGroup):
    """A single connector staged on the current cut seam, in the seam's
    local 2D coordinates (u, v) with the seam plane's normal as the axis."""

    kind: bpy.props.EnumProperty(
        name="Type",
        items=CONNECTOR_KIND_ITEMS,
        default='PLUG',
    )
    u: bpy.props.FloatProperty(name="U", default=0.0)
    v: bpy.props.FloatProperty(name="V", default=0.0)
    radius: bpy.props.FloatProperty(name="Radius", default=0.01, min=1e-5)
    depth: bpy.props.FloatProperty(name="Depth", default=0.01, min=1e-5)
    rotation: bpy.props.FloatProperty(name="Rotation", default=0.0, subtype='ANGLE')
    clearance: bpy.props.FloatProperty(name="Clearance", default=0.02, min=0.0, max=0.5)
    flip: bpy.props.BoolProperty(name="Flip", default=False)


class CC_TargetObjectItem(bpy.types.PropertyGroup):
    """Wraps a single Object reference so a plain CollectionProperty can
    hold a *list* of them (bpy.props has no direct "list of pointers")."""
    obj: bpy.props.PointerProperty(type=bpy.types.Object)


class CC_SceneProps(bpy.types.PropertyGroup):
    """Cut-plane + connector staging state, stored on the Scene."""

    def _on_cut_mode_update(self, context):
        # Switching away from Plane mode while the plane helper is up would
        # otherwise leave it orphaned in the scene (and still selected/
        # active) even though its UI section is now hidden - cancel it.
        if self.cut_mode != 'PLANE' and self.cut_active:
            from . import plane_helper
            plane_helper.remove_plane_object()
            plane_helper.restore_object_gizmo_overlay(context)
            self.cut_active = False
            active = None
            for item in self.target_objects:
                if item.obj is not None:
                    item.obj.select_set(True)
                    active = item.obj
            if active is not None:
                context.view_layer.objects.active = active
            self.target_objects.clear()

    cut_mode: bpy.props.EnumProperty(
        name="Cut Mode",
        description="How the cutting surface is defined",
        items=(
            ('LINE', "Line Cut", "Drag a straight line across the part - cuts immediately, like the original Dovetail Key addon"),
            ('FREEFORM', "Freeform", "Hand-drawn curved cut that fully crosses the part"),
            ('PLANE', "Custom Plane", "Flat planar cut, posed with a helper object using Blender's own gizmos"),
            ('EDGE_LOOP', "Edge Loop", "Cut along an inserted or manually-selected edge loop (Edit Mode)"),
        ),
        default='PLANE',
        update=_on_cut_mode_update,
    )
    cut_active: bpy.props.BoolProperty(
        name="Cut Plane Active",
        description="Show the interactive cut-plane helper object on the active object",
        default=False,
    )
    target_objects: bpy.props.CollectionProperty(
        name="Target Objects",
        description="The meshes being cut - remembered while the cut-plane helper is active "
                    "(which selects/shows only itself instead of them) so Cut can act on all "
                    "of them, not just whichever one was last active",
        type=CC_TargetObjectItem,
    )
    cap_strategy: bpy.props.EnumProperty(
        name="Cap Strategy",
        description="How to fill the hole(s) a cut leaves behind - no single approach looks "
                    "right on every hole shape, so pick whichever suits the part you're cutting. "
                    "Auto behaves differently for Edge Loop cuts (can be non-planar) vs Custom "
                    "Plane/Line Cut (always flat, so it can safely fall back to a flat face)",
        items=(
            ('AUTO', "Auto",
             "Grid fill first, then a mode-appropriate fallback: a flat face for Custom "
             "Plane/Line Cut, or even triangulation then a triangle fan for Edge Loop"),
            ('GRID', "Grid Fill",
             "Quad grid fill, falling back to a triangle fan only if that can't fully "
             "close the hole"),
            ('NGON', "Single Face",
             "Cap with one flat n-gon face, no subdivision - only looks right on flat, "
             "convex holes"),
            ('FAN', "Triangle Fan",
             "Always cap with a simple center-point triangle fan - most predictable on "
             "irregular/non-planar holes, even if not the prettiest"),
            ('BEAUTY', "Even Triangulation",
             "Always cap with an even, well-distributed triangulation - no single forced "
             "center point, unlike Triangle Fan"),
        ),
        default='AUTO',
    )

    connectors: bpy.props.CollectionProperty(type=CC_ConnectorItem)
    connector_index: bpy.props.IntProperty(name="Active Connector", default=-1)

    default_kind: bpy.props.EnumProperty(
        name="Default Type", items=CONNECTOR_KIND_ITEMS, default='PLUG',
    )
    default_radius: bpy.props.FloatProperty(name="Default Radius", default=0.01, min=1e-5)
    default_depth: bpy.props.FloatProperty(name="Default Depth", default=0.01, min=1e-5)
    auto_count: bpy.props.IntProperty(
        name="Count", description="Number of connectors to auto-distribute", default=3, min=1, max=64,
    )


_CLASSES = (CC_ConnectorItem, CC_TargetObjectItem, CC_SceneProps)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.cc = bpy.props.PointerProperty(type=CC_SceneProps)


def unregister():
    del bpy.types.Scene.cc
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
