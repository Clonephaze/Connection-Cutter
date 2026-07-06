"""Cut-plane helper object.

Earlier versions of this addon drove the cut plane with a hand-rolled
GizmoGroup (custom arrow + dial widgets). That turned out to be the wrong
call: Blender already ships robust, well-tested move/rotate/scale gizmos
for any object, with snapping, numeric input (typing a value, or opening the
N-panel Transform fields), and axis constraints (X/Y/Z, Shift to exclude an
axis) all for free. So instead, "posing the cut plane" is just posing a
normal Blender object - a flat plane mesh named CC_Cut_Plane - with the
regular Move/Rotate tools, G/R shortcuts, or the Transform panel. No custom
gizmo code needed at all.

The object's local +Z axis is the cut normal, and its origin is the cut
point - CC_OT_apply_cut reads matrix_world off of it directly.

This module also enables the viewport's "Object Gizmos" overlay (Move /
Rotate / Scale) while the plane is up, restoring whatever the user had
before, since those overlays being off is the most common reason the
move/rotate handles don't show up on the plane object.
"""

import bmesh
import bpy
from mathutils import Vector

PLANE_OBJECT_NAME = "CC_Cut_Plane"

_saved_gizmo_overlay = None


def get_plane_object():
    return bpy.data.objects.get(PLANE_OBJECT_NAME)


def enable_object_gizmo_overlay(context):
    """Force on the viewport's Move/Rotate/Scale object gizmos, remembering
    whatever they were set to so they can be restored later."""
    global _saved_gizmo_overlay
    space = context.space_data
    if space is None or space.type != 'VIEW_3D':
        return
    if _saved_gizmo_overlay is None:
        _saved_gizmo_overlay = {
            'show_gizmo': space.show_gizmo,
            'show_gizmo_object_translate': space.show_gizmo_object_translate,
            'show_gizmo_object_rotate': space.show_gizmo_object_rotate,
            'show_gizmo_object_scale': space.show_gizmo_object_scale,
        }
    space.show_gizmo = True
    space.show_gizmo_object_translate = True
    space.show_gizmo_object_rotate = True
    space.show_gizmo_object_scale = True


def restore_object_gizmo_overlay(context):
    """Undo enable_object_gizmo_overlay(), restoring the user's prior
    overlay settings. Safe to call even if nothing was saved."""
    global _saved_gizmo_overlay
    if _saved_gizmo_overlay is None:
        return
    space = context.space_data
    if space is not None and space.type == 'VIEW_3D':
        for key, value in _saved_gizmo_overlay.items():
            setattr(space, key, value)
    _saved_gizmo_overlay = None


def _object_bounds_center_and_radius(objs):
    """Combined bounding-sphere center/radius across one or more objects."""
    corners = [obj.matrix_world @ Vector(c) for obj in objs for c in obj.bound_box]
    center = sum(corners, Vector((0.0, 0.0, 0.0))) / max(len(corners), 1)
    radius = max((c - center).length for c in corners) if corners else 1.0
    return center, max(radius, 1e-4)


def _make_plane_mesh(name, size):
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=size)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return me


def _plane_material(context):
    prefs = context.preferences.addons[__package__].preferences
    mat = bpy.data.materials.get("CC_Cut_Plane_Mat")
    if mat is None:
        mat = bpy.data.materials.new("CC_Cut_Plane_Mat")
        mat.blend_method = 'BLEND'
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf is not None:
            bsdf.inputs["Alpha"].default_value = 0.25
    if mat.use_nodes:
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf is not None:
            bsdf.inputs["Base Color"].default_value = (*prefs.plane_color, 1.0)
    return mat


def create_plane_object(context, target_objs):
    """Create (or recreate) the cut-plane helper object, positioned at the
    combined bounding-sphere center of `target_objs` and facing the
    current view. `target_objs` may be a single Object or a list of them."""
    remove_plane_object()
    if not hasattr(target_objs, '__iter__'):
        target_objs = [target_objs]

    center, radius = _object_bounds_center_and_radius(target_objs)

    mesh = _make_plane_mesh(PLANE_OBJECT_NAME, radius * 0.75)
    plane_obj = bpy.data.objects.new(PLANE_OBJECT_NAME, mesh)
    plane_obj.location = center

    rv3d = context.region_data
    if rv3d is not None:
        plane_obj.rotation_euler = rv3d.view_rotation.to_euler()

    plane_obj.display_type = 'SOLID'
    plane_obj.data.materials.append(_plane_material(context))

    context.collection.objects.link(plane_obj)
    return plane_obj


def reset_plane_transform(context, plane_obj, target_objs):
    if not hasattr(target_objs, '__iter__'):
        target_objs = [target_objs]
    center, radius = _object_bounds_center_and_radius(target_objs)
    plane_obj.location = center
    rv3d = context.region_data
    if rv3d is not None:
        plane_obj.rotation_euler = rv3d.view_rotation.to_euler()
    else:
        plane_obj.rotation_euler = (0.0, 0.0, 0.0)
    plane_obj.scale = (1.0, 1.0, 1.0)

    old_mesh = plane_obj.data
    plane_obj.data = _make_plane_mesh(old_mesh.name, radius * 0.75)
    plane_obj.data.materials.append(_plane_material(context))
    if old_mesh.users == 0:
        bpy.data.meshes.remove(old_mesh)


def remove_plane_object():
    obj = get_plane_object()
    if obj is None:
        return
    mesh = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if mesh is not None and mesh.users == 0:
        bpy.data.meshes.remove(mesh)


def plane_co_no(plane_obj):
    """World-space (point, normal) for the current plane transform.
    Scale is intentionally ignored - only translation/rotation matter for an
    (effectively infinite) cutting plane."""
    mw = plane_obj.matrix_world
    co = mw.translation
    no = (mw.to_3x3() @ Vector((0.0, 0.0, 1.0))).normalized()
    return co, no


def register():
    pass


def unregister():
    remove_plane_object()

