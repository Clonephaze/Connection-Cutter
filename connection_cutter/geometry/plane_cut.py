"""Plane bisect + connected-component split + hole capping.

The bisect/split/cap routines are carried over (lightly refactored) from the
GPL-3.0 "Dovetail Key" addon - they're solid, generic bmesh math that doesn't
need to change just because the plane is now posed with a helper object
instead of a 2D screen-space drag. What *is* new: `bisect_and_split` takes
an explicit world-space plane (co, no) instead of reconstructing one from
two mouse rays.
"""

import bmesh
import bpy
from mathutils import Vector

from .. import debug
from . import mesh_utils


def bisect_and_split(context, obj, plane_co, plane_no, face_filter=None, near_point=None):
    """Cut `obj` with the world-space plane (plane_co, plane_no) and split it
    into two separate mesh objects.

    `face_filter`, if given, is called as `face_filter(bm)` (after `bm` is
    built from obj.data) and must return the subset of `bm.faces` the plane
    is actually allowed to affect - everything else is left completely
    untouched, even if it geometrically lies on the same (infinite) plane.
    Currently unused (kept for future use) - superseded by `near_point` for
    Line Cut's "don't affect unrelated geometry" problem, see below.

    `near_point`, if given (world-space), is the more robust fix for that
    same problem: bisect_plane still runs against the FULL, unrestricted
    mesh (so every real crossing of the infinite plane is found exactly,
    with no guessing about corridor size), but a plane can cross unrelated
    geometry more than once (e.g. an arm AND a lock of hair on the same
    plane) - `res['geom_cut']` is grouped into disjoint connected loops
    (mesh_utils.group_connected_edges, then mesh_utils.merge_coincident_
    groups to stitch back together any single ring that got fragmented by
    a UV seam / material boundary) and sorted by distance to `near_point`.

    A single nearest ring ISN'T always enough to actually separate anything
    - e.g. a braid that physically touches the shoulder a little further
    along the same infinite plane bridges the two sides just as much as
    the neck's own ring does, and cutting only the neck ring can never
    fully free the head in that case. So this retries with progressively
    MORE of the nearest rings included (nearest, then nearest+2nd-nearest,
    etc.) until the cut actually separates the mesh or every ring has been
    included (equivalent to the old unrestricted whole-mesh behavior).
    Whichever rings *aren't* included in a given attempt are dissolved back
    to their original topology (see below) rather than left as a stray cut
    line - only the rings that end up part of the winning attempt actually
    get severed. Line Cut uses this (see line_cut.py); Custom Plane leaves
    it None on `face_filter` but still passes `near_point`, so both share
    this same widening-retry behavior.

    TODO: preserve UVs / vertex colors across the new cap faces.

    Returns (obj_a, obj_b) or None if the plane doesn't actually cross the
    (possibly filtered) mesh.
    """
    mw = obj.matrix_world
    mwi = mw.inverted()
    m3t = mw.to_3x3().transposed()

    co_l = mwi @ Vector(plane_co)
    no_l = (m3t @ Vector(plane_no)).normalized()
    near_l = mwi @ Vector(near_point) if near_point is not None else None

    bb = [Vector(c) for c in obj.bound_box]
    diag = (Vector((max(v[i] for v in bb) for i in range(3)))
            - Vector((min(v[i] for v in bb) for i in range(3)))).length

    num_attempts = 1
    attempt = 0
    bm = None
    comp = None
    neighbor_faces = set()
    while attempt < num_attempts:
        attempt += 1

        bm = bmesh.new()
        bm.from_mesh(obj.data)

        if face_filter is not None:
            affected = face_filter(bm)
            geom = set()
            for f in affected:
                geom.update(f.verts)
                geom.update(f.edges)
                geom.add(f)
            geom = list(geom)
            debug.log(f"bisect_and_split({obj.name}): face_filter restricted geom to "
                       f"{len(affected)}/{len(bm.faces)} faces")
        else:
            geom = list(bm.verts) + list(bm.edges) + list(bm.faces)
            debug.log(f"bisect_and_split({obj.name}): no face_filter, using all {len(bm.faces)} faces")

        res = bmesh.ops.bisect_plane(
            bm, geom=geom, dist=1e-5 * max(diag, 1e-6),
            plane_co=co_l, plane_no=no_l,
            clear_inner=False, clear_outer=False,
        )
        cut_edges = [e for e in res['geom_cut'] if isinstance(e, bmesh.types.BMEdge)]
        if not cut_edges:
            debug.log(f"bisect_and_split({obj.name}): REJECTED - bisect_plane produced 0 cut edges "
                       f"(the plane doesn't cross the {'filtered ' if face_filter else ''}geometry)")
            bm.free()
            return None

        if near_point is not None:
            groups = mesh_utils.group_connected_edges(cut_edges)
            raw_group_count = len(groups)
            # A single, real, visually-continuous cut ring can come out
            # fragmented into several "disjoint" groups above purely because
            # of duplicate/coincident vertices at UV seams, material
            # boundaries, or sharp-edge splits - group_connected_edges only
            # follows literal shared-BMVert identity, which those don't share
            # even though they sit at the exact same point.
            groups = mesh_utils.merge_coincident_groups(groups)
            groups.sort(key=lambda g: min((v.co - near_l).length for e in g for v in e.verts))
            num_attempts = len(groups)

            included, excluded = groups[:attempt], groups[attempt:]
            target = [e for g in included for e in g]
            debug.log(f"bisect_and_split({obj.name}): near_point given - plane crossed the mesh in "
                       f"{raw_group_count} raw place(s) ({len(groups)} after merging coincident-vertex "
                       f"fragments) - attempt {attempt}/{num_attempts} includes the {len(included)} "
                       f"nearest ring(s) ({len(target)} cut edges); {len(excluded)} ring(s) still left alone")

            # "Left alone" used to mean "not split/severed" but NOT
            # "untouched" - bisect_plane had already permanently inserted
            # new verts/edges at EVERY crossing (that's how it found them
            # all in the first place), so other, unrelated crossings were
            # left with a stray inert edge loop threaded through them even
            # though nothing there ever got separated - a real, visible
            # mesh defect (e.g. a face on the far side of a character
            # getting a new crack-like edge loop from an arm cut).
            #
            # FIRST ATTEMPT (REVERTED): dissolving all of those verts at
            # once via bmesh.ops.dissolve_verts actually made this much
            # worse on a dense triangulated mesh - it doesn't reliably
            # reconstruct the surrounding n-gon for a whole CHAIN of
            # connected, simultaneously-dissolved verts (each one's
            # neighborhood assumption breaks as its neighbor is also being
            # removed in the same batch), and ended up deleting faces
            # without properly stitching a replacement, i.e. a real hole -
            # visibly worse than the original inert-edge-loop cosmetic
            # issue. Do NOT go back to dissolve_verts here.
            # CURRENT FIX: dissolve the CUT EDGES themselves instead (the
            # new edges lying exactly on the plane, forming a line/loop -
            # the actual chain structure bisect_plane produced) via
            # bmesh.ops.dissolve_edges(..., use_verts=True) - this merges
            # exactly the 2 faces on either side of each such edge back
            # into one (a well-defined, always-safe operation on a proper
            # manifold edge), and use_verts=True also removes the now-
            # unnecessary vertices as a natural side effect of that merge,
            # instead of trying to dissolve a whole vertex batch up front.
            other_edges = [e for g in excluded for e in g]
            if other_edges:
                bmesh.ops.dissolve_edges(bm, edges=other_edges, use_verts=True, use_face_split=False)

            cut_edges = target

        # Identify which faces border the cut on the "kept" (negative)
        # side, and which are candidate seeds on the "split off" (positive)
        # side - BEFORE split_edges disconnects the two sides below, since
        # a cut edge's link_faces only ever reaches both sides up until
        # that point (after the split each side's own copy of the edge
        # only links back to itself, so finding the other side via
        # link_faces afterward silently finds nothing - this was an
        # earlier bug: capping the kept side always no-opped). Deriving
        # both sets directly from cut_edges (rather than scanning bm.faces
        # or res['geom'] broadly) also keeps this correctly scoped down to
        # just the included ring(s) when near_point/face_filter narrowed
        # cut_edges above.
        neighbor_faces = set()
        positive_side_faces = set()
        for e in cut_edges:
            for f in e.link_faces:
                if (f.calc_center_median() - co_l).dot(no_l) <= 0:
                    neighbor_faces.add(f)
                else:
                    positive_side_faces.add(f)

        bmesh.ops.split_edges(bm, edges=cut_edges)

        seed = next(iter(positive_side_faces), None)
        if seed is None:
            debug.log(f"bisect_and_split({obj.name}): REJECTED - no candidate face on the positive "
                       f"side of the plane ({len(cut_edges)} cut edges)")
            bm.free()
            return None

        comp = mesh_utils.component(seed)
        if len(comp) >= len(bm.faces):
            if attempt < num_attempts:
                debug.log(f"bisect_and_split({obj.name}): attempt {attempt}/{num_attempts} still "
                          f"covered the whole mesh ({len(comp)}/{len(bm.faces)} faces) - widening to "
                          f"include one more ring and retrying")
                bm.free()
                continue
            debug.log(f"bisect_and_split({obj.name}): REJECTED - flood-fill from seed covered "
                       f"{len(comp)}/{len(bm.faces)} faces (the whole mesh) - the cut isn't actually "
                       f"separating anything, even after including every ring the plane crosses")
            bm.free()
            return None

        break

    debug.log(f"bisect_and_split({obj.name}): split-off piece has {len(comp)}/{len(bm.faces)} faces")

    mesh_b = mesh_utils.extract_and_cap(
        comp, mesh_utils.next_split_name(obj.data.name, bpy.data.meshes),
        strategy=context.scene.cc.cap_strategy,
    )
    if mesh_b is None:
        debug.log(f"bisect_and_split({obj.name}): REJECTED - capping the split-off piece failed "
                   f"(cap_strategy={context.scene.cc.cap_strategy!r})")
        bm.free()
        return None
    for m in obj.data.materials:
        mesh_b.materials.append(m)

    # neighbor_faces (kept side) and comp (split-off side) are SUPPOSED to
    # be disjoint - but with the widening-retry loop above now able to
    # include more than one ring, a face right at the junction of two
    # rings can get classified as "negative side" via one ring's cut edge
    # (added to neighbor_faces) while still being flood-fill-reachable
    # into comp via some other, non-severed path - i.e. genuinely in both
    # sets. Left alone, that face is deleted below (it's part of comp) but
    # neighbor_faces keeps a now-dangling reference to it, which crashed
    # with "ReferenceError: BMesh data of type BMFace has been removed"
    # the first time this ever came up in practice (2 rings needed for a
    # real cut). comp is the ground truth here (it reflects actual mesh
    # connectivity via the flood-fill, neighbor_faces is only a sign-based
    # pre-classification), so just drop the overlap before it can be used.
    overlap = neighbor_faces & comp
    if overlap:
        debug.log(f"bisect_and_split({obj.name}): {len(overlap)} face(s) were classified as both "
                   f"kept-side and split-off-side (junction between included rings) - dropping them "
                   f"from the kept side's capping boundary, comp wins")
        neighbor_faces -= overlap

    bmesh.ops.delete(bm, geom=list(comp), context='FACES')
    if not mesh_utils.cap_faces_boundary(bm, neighbor_faces, strategy=context.scene.cc.cap_strategy):
        # The "split off" half (mesh_b) already checked out fine above, but
        # the "kept" half's cap failed to fully close - previously this was
        # silently ignored, leaving obj with an open hole on this side while
        # the other object looked fine. Never write back a half-open result.
        debug.log(f"bisect_and_split({obj.name}): REJECTED - capping the kept piece failed "
                   f"({len(neighbor_faces)} neighbor faces, cap_strategy={context.scene.cc.cap_strategy!r})")
        bm.free()
        bpy.data.meshes.remove(mesh_b)
        return None
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()

    obj_b = bpy.data.objects.new(mesh_utils.next_split_name(obj.name, bpy.data.objects), mesh_b)
    obj_b.matrix_world = obj.matrix_world.copy()
    context.collection.objects.link(obj_b)
    # obj_b is a brand new object, so it starts with no modifiers - copy
    # obj's stack (Subdivision Surface, Mirror, etc.) over so the split-off
    # piece keeps behaving like the original instead of silently losing it.
    mesh_utils.copy_modifiers(obj, obj_b)

    return obj, obj_b
