"""Freeform (curved, hand-drawn) cutting.

Unlike plane_cut.py (a single infinite flat plane, trivially divides all of
3D space in two), a hand-drawn stroke only defines a *curve*, not something
that splits space on its own - it needs to be closed into an actual solid
before we can boolean-split the mesh with it. The approach here:

1. The user draws an open 2D stroke in the viewport (screen space) that
   fully crosses the part, same requirement as a straight-line cut.
2. We turn that into a closed 2D polygon by bridging the two ends with a
   simple trapezoid that bulges away from the object - i.e. a loop that
   follows the drawn curve exactly where it matters and stays outside the
   object's silhouette everywhere else, so it never introduces extra
   unwanted cuts.
3. Each point of that closed polygon is cast into 3D as a *pair* of points
   (near/far along that specific viewing ray), bracketing the object's
   bounding sphere - turning the closed 2D polygon into a closed, watertight
   3D "prism" solid (like a cookie cutter extruded through the object).
4. TWO FRESH DUPLICATES of the target object (never the original) are
   boolean-split against that solid: INTERSECT keeps one side, DIFFERENCE
   keeps the other - both using the Exact solver. Only once both booleans
   are confirmed to have produced a valid, non-empty result do we touch the
   original object at all (swap its mesh data for the INTERSECT result and
   drop the temporary duplicate). If anything goes wrong, the original
   object is left completely untouched and both duplicates are discarded.

This "closed cutter solid -> intersect / difference" step is intentionally
generic - a future surface-following cutter (conforming to the mesh instead
of a straight view-direction extrusion) would only need to change how the
solid is built, not this split step.
"""

import bmesh
import bpy
from bpy_extras import view3d_utils
from mathutils import Vector

from . import boolean_utils, mesh_utils

_DEPTH_MARGIN = 1.5  # multiplier on the object's bounding radius
_CLOSE_LOOP_FACTOR = 4.0  # how far outside the silhouette the closing loop bulges
_MIN_POINT_SPACING = 2.0  # px - drop stroke points closer together than this


def _simplify_stroke(stroke_2d):
    """Drop near-duplicate consecutive points (mouse-move jitter/pauses
    otherwise produce zero-length edges that make the prism non-manifold)."""
    out = [Vector(stroke_2d[0])]
    for p in stroke_2d[1:]:
        p = Vector(p)
        if (p - out[-1]).length >= _MIN_POINT_SPACING:
            out.append(p)
    return out


def _close_stroke_loop(stroke_2d, obj_center_2d):
    """Extend an open 2D stroke into a simple closed polygon: bridge the two
    ends with a trapezoid that bulges away from the object's screen
    position, keeping the closing edges outside the object's silhouette."""
    if len(stroke_2d) < 2:
        return None

    p0, pn = stroke_2d[0], stroke_2d[-1]
    span = (pn - p0).length
    big = max(span, 1.0) * _CLOSE_LOOP_FACTOR

    chord = pn - p0
    perp = Vector((-chord.y, chord.x))
    perp = perp.normalized() if perp.length > 1e-9 else Vector((0.0, 1.0))
    mid = (p0 + pn) * 0.5
    if (obj_center_2d - mid).dot(perp) > 0:
        perp = -perp  # bulge the closing loop away from the object

    far_end = pn + perp * big
    far_start = p0 + perp * big

    return list(stroke_2d) + [far_end, far_start]


def _ray_near_far(region, rv3d, pt2d, sphere_center, sphere_radius):
    origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, pt2d)
    direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, pt2d)
    if direction is None or direction.length < 1e-9:
        return None
    direction = direction.normalized()
    t_center = (sphere_center - origin).dot(direction)
    margin = sphere_radius * _DEPTH_MARGIN
    near_t = max(t_center - margin, 0.0)
    far_t = t_center + margin
    return origin + direction * near_t, origin + direction * far_t


def _build_prism_mesh(name, near_pts, far_pts):
    bm = bmesh.new()
    near_verts = [bm.verts.new(p) for p in near_pts]
    far_verts = [bm.verts.new(p) for p in far_pts]
    bm.verts.index_update()

    try:
        bm.faces.new(near_verts)
    except ValueError:
        pass
    try:
        bm.faces.new(list(reversed(far_verts)))
    except ValueError:
        pass

    n = len(near_verts)
    for i in range(n):
        j = (i + 1) % n
        try:
            bm.faces.new((near_verts[i], near_verts[j], far_verts[j], far_verts[i]))
        except ValueError:
            pass

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return me


def _duplicate(context, obj, name):
    data = obj.data.copy()
    dup = bpy.data.objects.new(name, data)
    dup.matrix_world = obj.matrix_world.copy()
    context.collection.objects.link(dup)
    return dup


def bisect_and_split_freeform(context, obj, region, rv3d, stroke_2d, solver='EXACT'):
    """Cut `obj` along a hand-drawn open stroke (list of (x, y) region-space
    2D points) and split it into two separate mesh objects.

    `obj` is never modified unless the cut fully succeeds - both halves are
    built on temporary duplicates first and validated, so a bad/degenerate
    stroke leaves the original mesh exactly as it was (just returns None).

    Returns (obj_a, obj_b) or None if the stroke doesn't validly cross the
    mesh (too few points, degenerate closing loop, or empty boolean result).

    Returns a `(result, reason)` tuple - NOT just `result` - so callers can
    tell an actionable, specific failure (e.g. "has shape keys") apart from
    the generic "stroke didn't cross the part" case instead of guessing:
    - success: `(obj, dup_b), None`
    - failure: `None, <short human-readable reason string>`
    """
    if mesh_utils.has_shape_keys(obj):
        # Fail fast with a specific reason instead of letting this fail deep
        # inside modifier_apply with a message that doesn't explain WHY -
        # Blender refuses to apply ANY modifier (the boolean this whole
        # approach depends on included) to a mesh with shape keys.
        return None, (
            "has shape keys - Blender can't apply a Boolean modifier to a mesh "
            "with shape keys. Remove them (or apply them as the new basis) first."
        )

    stroke_2d = _simplify_stroke(stroke_2d)
    if len(stroke_2d) < 2:
        return None, "stroke has too few points"

    center, radius = mesh_utils.bounding_sphere(obj)
    obj_center_2d = view3d_utils.location_3d_to_region_2d(region, rv3d, center)
    if obj_center_2d is None:
        return None, "couldn't project the object's center into the viewport"

    loop_2d = _close_stroke_loop(stroke_2d, obj_center_2d)
    if loop_2d is None:
        return None, "couldn't close the stroke into a polygon"

    near_pts, far_pts = [], []
    for pt in loop_2d:
        nf = _ray_near_far(region, rv3d, pt, center, radius)
        if nf is None:
            return None, "couldn't cast the stroke into 3D (degenerate view ray)"
        near_pts.append(nf[0])
        far_pts.append(nf[1])

    prism_mesh = _build_prism_mesh("CC_FreeformCutter", near_pts, far_pts)
    prism_obj = bpy.data.objects.new("CC_FreeformCutter", prism_mesh)
    context.collection.objects.link(prism_obj)

    # Never touch the real object until both halves are confirmed good.
    # dup_a is purely temporary (transplanted into `obj` then discarded
    # below, never seen by the user) so its name doesn't need to be smart -
    # only dup_b's, since IT is what becomes the persistent split-off
    # object, and blindly appending "_B" every time compounds into
    # "Part_B_B_B..." on repeated cuts of the same lineage.
    dup_a = _duplicate(context, obj, obj.name + "_A_tmp")
    dup_b = _duplicate(context, obj, mesh_utils.next_split_name(obj.name, bpy.data.objects))

    ok_a, reason_a = boolean_utils.apply_boolean(context, dup_a, prism_obj, 'INTERSECT', solver)
    ok_b, reason_b = boolean_utils.apply_boolean(context, dup_b, prism_obj, 'DIFFERENCE', solver)

    bpy.data.objects.remove(prism_obj, do_unlink=True)
    bpy.data.meshes.remove(prism_mesh)

    valid = (
        ok_a and ok_b
        and len(dup_a.data.polygons) > 0
        and len(dup_b.data.polygons) > 0
    )
    if not valid:
        bpy.data.objects.remove(dup_a, do_unlink=True)
        bpy.data.objects.remove(dup_b, do_unlink=True)
        if not ok_a or not ok_b:
            reason = f"boolean cut failed: {reason_a or reason_b}"
        else:
            reason = "stroke doesn't fully cross the part"
        return None, reason

    # Success - transplant dup_a's result into the original object so it
    # keeps its name/identity (matching plane_cut.bisect_and_split), then
    # discard the now-redundant dup_a wrapper object. dup_b is a brand new
    # object (bpy.data.objects.new) so it doesn't have obj's modifier stack
    # (e.g. Subdivision Surface, Mirror) - copy it over so the split-off
    # piece keeps behaving like the original instead of silently losing it.
    old_mesh = obj.data
    obj.data = dup_a.data
    bpy.data.objects.remove(dup_a, do_unlink=True)
    if old_mesh.users == 0:
        bpy.data.meshes.remove(old_mesh)
    mesh_utils.copy_modifiers(obj, dup_b)

    return (obj, dup_b), None

