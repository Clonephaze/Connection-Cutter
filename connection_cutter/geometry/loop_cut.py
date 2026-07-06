"""Edge-loop cutting: split a mesh along a closed loop of edges instead of a
plane or a freeform stroke.

This backs BOTH of the edge-loop workflows in operators/edge_loop.py:
- "Insert Loop Cut" (like Blender's own Ctrl+R) inserts a fresh loop, then
  leaves it selected.
- "Cut Along Selected Loop" works on an existing loop you selected yourself
  in Edit Mode (Alt+Click, or any other selection method).

Both end up calling `split_along_selection()` below - the only difference
between the two workflows is *how the edges got selected*, not what happens
next, so there's only one thing to implement and get right.

Same non-destructive discipline as freeform_cut.py: this reads the current
Edit Mode selection (a read-only look at the live edit-bmesh, never mutated
directly), then does all the actual splitting/capping work on a throwaway
bmesh copy of the mesh. `obj` is only touched after both resulting shells
are confirmed valid.
"""

import bmesh
import bpy

from . import mesh_utils


def _selected_edge_indices(obj):
    """Read the current Edit Mode edge selection without touching it."""
    bm = bmesh.from_edit_mesh(obj.data)
    return [e.index for e in bm.edges if e.select]


def split_along_selection(context, obj):
    """Split `obj` (currently in Edit Mode) into two objects along its
    selected edges. Leaves Object Mode active either way.

    Only the pre-existing connected "island" the selection actually belongs
    to is affected - a mesh object routinely bundles several already-
    disconnected islands together (a character body plus both eyeballs,
    teeth, etc.), and those must be left alone rather than counted as
    unexpected extra pieces. So this checks that the selection's *own*
    island splits into exactly two - not that the whole object does.

    Returns (obj_a, obj_b) or None if the selection isn't a closed loop (or
    set of loops) that fully separates its island into two pieces - `obj`
    is left completely untouched in that case (still in Edit Mode, with its
    selection intact, so the user can adjust and try again).
    """
    edge_indices = _selected_edge_indices(obj)
    if not edge_indices:
        return None

    bpy.ops.object.mode_set(mode='OBJECT')

    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.edges.ensure_lookup_table()
    sel_edges = [bm.edges[i] for i in edge_indices]

    seed_face = next((f for e in sel_edges for f in e.link_faces), None)
    if seed_face is None:
        bm.free()
        bpy.ops.object.mode_set(mode='EDIT')
        return None

    # Which pre-existing island (of possibly several in this one object)
    # does the selection belong to? Only that island's split is validated -
    # everything else in the mesh is left exactly as it was.
    target_island = mesh_utils.component(seed_face)

    bmesh.ops.split_edges(bm, edges=sel_edges)

    sub_parts = mesh_utils.all_components(target_island)
    if len(sub_parts) != 2:
        bm.free()
        bpy.ops.object.mode_set(mode='EDIT')
        return None

    # The larger (by surface area) piece keeps the object's identity and
    # keeps any other untouched islands attached to it; the smaller piece
    # becomes the new "_B" object - e.g. cutting an iris off a head keeps
    # the head (plus the other eye, teeth, etc.) as the original object and
    # splits off just the small iris disc.
    comp_keep, comp_split_off = sub_parts
    if sum(f.calc_area() for f in comp_keep) < sum(f.calc_area() for f in comp_split_off):
        comp_keep, comp_split_off = comp_split_off, comp_keep

    mesh_b = mesh_utils.extract_and_cap(
        comp_split_off, mesh_utils.next_split_name(obj.data.name, bpy.data.meshes),
        strategy=context.scene.cc.cap_strategy, is_edge_loop=True,
    )
    if mesh_b is None:
        bm.free()
        bpy.ops.object.mode_set(mode='EDIT')
        return None

    bmesh.ops.delete(bm, geom=list(comp_split_off), context='FACES')
    # Scoped to comp_keep specifically - `bm` still holds every other
    # untouched island in this object too, and those must not have any of
    # their own (possibly pre-existing, unrelated) open boundaries touched.
    if not mesh_utils.cap_faces_boundary(
        bm, comp_keep, strategy=context.scene.cc.cap_strategy, is_edge_loop=True,
    ):
        # mesh_b checked out fine above, but the "kept" side failed to
        # fully close - abort rather than silently leaving obj half-open.
        bm.free()
        bpy.data.meshes.remove(mesh_b)
        bpy.ops.object.mode_set(mode='EDIT')
        return None
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()

    for m in obj.data.materials:
        mesh_b.materials.append(m)

    obj_b = bpy.data.objects.new(mesh_utils.next_split_name(obj.name, bpy.data.objects), mesh_b)
    obj_b.matrix_world = obj.matrix_world.copy()
    context.collection.objects.link(obj_b)
    # obj_b is a brand new object, so it starts with no modifiers - copy
    # obj's stack (Subdivision Surface, Mirror, etc.) over so the split-off
    # piece keeps behaving like the original instead of silently losing it.
    mesh_utils.copy_modifiers(obj, obj_b)

    return obj, obj_b

