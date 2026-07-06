"""Quick straight-line cutting.

This ports the original GPL-3.0 "Dovetail Key" addon's line-slice math
almost verbatim: two screen-space points unambiguously define a real 3D
plane (the plane containing both view rays), so a straight-line drag needs
none of freeform_cut.py's polygon-closing/prism-boolean machinery - it just
hands the reconstructed plane to plane_cut.bisect_and_split, the same
robust bisect_plane-based path "Custom Plane" mode uses.

Important wrinkle: a mathematical plane is infinite - it extends in every
direction within itself, not just between the two points you dragged over,
and can cross completely unrelated geometry that just happens to also lie
on that plane (e.g. drag a line across an arm, and the plane also passes
through a lock of hair elsewhere on the same character).

THREE approaches were tried and abandoned before landing on the current
one (all found via real debug-logged Blender runs, not guessing - see
/memories/repo/original-addon-analysis.md for the full blow-by-blow):
1. Restrict which faces bisect_plane is even allowed to touch, based on a
   spatial "corridor" around the drawn line (screen-space reprojection,
   then two different 3D single/isotropic-margin variants). Every variant
   either let unrelated geometry sharing part of the corridor's extent
   sneak in (uncappable multi-loop boundary), or clipped part of the
   actual cut ring the intended feature needed (cut silently fails to
   separate anything) - there's no corridor size that's simultaneously
   "big enough to fully wrap the real feature" and "small enough to
   exclude everything else" without actually knowing the real feature's
   shape in advance, which a spatial guess fundamentally can't know.
2. Confirmed against the original GPL addon's own behavior (user tested
   and screenshotted it): it doesn't guess a corridor at all - it traces
   the EXACT topological ring where the plane crosses the surface.

Current approach: let bisect_plane run against the FULL, unrestricted mesh
(so every real crossing is found with zero guessing), then group the
resulting cut edges into disjoint connected loops (one per actual place
the plane crosses the surface) and keep only the loop nearest to the
drawn line - every other loop is left completely alone (not even split,
just an inert edge where the plane crossed it). This can't ever clip part
of the intended ring (the whole thing is always found, being a real
topological trace) and can't ever include an unrelated crossing elsewhere
(different loops are never merged) - see plane_cut.bisect_and_split's
`near_point` parameter for the implementation.
"""

from bpy_extras import view3d_utils

from . import mesh_utils, plane_cut


def plane_from_screen_line(region, rv3d, a, b):
    """a, b: (x, y) region-space 2D points from a straight drag. Returns
    (plane_co, plane_no) in world space, or None if degenerate (e.g. a
    zero-length drag, or a view angle where the two rays are parallel)."""
    o1 = view3d_utils.region_2d_to_origin_3d(region, rv3d, a)
    d1 = view3d_utils.region_2d_to_vector_3d(region, rv3d, a)
    o2 = view3d_utils.region_2d_to_origin_3d(region, rv3d, b)
    d2 = view3d_utils.region_2d_to_vector_3d(region, rv3d, b)

    normal = d1.cross((o2 + d2) - o1)
    if normal.length < 1e-9:
        return None
    normal.normalize()
    return o1, normal


def _segment_midpoint_near_object(obj, region, rv3d, a, b):
    """Approximates where the drawn line crosses `obj`, as the midpoint of
    the two screen-rays' closest points to the object's bounding-sphere
    center - doesn't need to be exact, just close enough to the intended
    crossing to unambiguously be "nearest" to it (vs. some other unrelated
    crossing elsewhere on the mesh)."""
    center, _radius = mesh_utils.bounding_sphere(obj)

    o1 = view3d_utils.region_2d_to_origin_3d(region, rv3d, a)
    d1 = view3d_utils.region_2d_to_vector_3d(region, rv3d, a)
    o2 = view3d_utils.region_2d_to_origin_3d(region, rv3d, b)
    d2 = view3d_utils.region_2d_to_vector_3d(region, rv3d, b)
    if d1.length < 1e-9 or d2.length < 1e-9:
        return center

    p1 = o1 + d1 * (center - o1).dot(d1)
    p2 = o2 + d2 * (center - o2).dot(d2)
    return (p1 + p2) * 0.5


def bisect_and_split_line(context, obj, region, rv3d, a, b):
    """Cut `obj` along the plane defined by a straight screen-space drag
    from a to b, restricted to the local ring nearest the drawn line so it
    doesn't also slice through unrelated geometry elsewhere on the same
    infinite plane. Returns (obj_a, obj_b) or None."""
    plane = plane_from_screen_line(region, rv3d, a, b)
    if plane is None:
        return None
    plane_co, plane_no = plane

    near_point = _segment_midpoint_near_object(obj, region, rv3d, a, b)
    return plane_cut.bisect_and_split(context, obj, plane_co, plane_no, near_point=near_point)

