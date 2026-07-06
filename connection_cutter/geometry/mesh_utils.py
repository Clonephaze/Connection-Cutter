"""Small bmesh utilities shared across the different cut modes.

component()/extract() were originally private helpers duplicated between
plane_cut.py's bisect split and the (new) loop_cut.py edge-loop split -
pulled out here once a second consumer showed up. bounding_sphere() had the
same story between freeform_cut.py and line_cut.py.
"""

import re
import string

import bmesh
import bpy
from mathutils import Vector
from mathutils.kdtree import KDTree

_COINCIDENT_EPSILON = 1e-5  # local-space distance below which 2 verts are treated as "the same point"

# Matches a trailing split-name suffix - either a single letter ("_B") or a
# "Z_"-prefixed chain from _split_suffixes() overflowing past Z ("_Z_A",
# "_Z_Z_C", ...) - used to strip a PREVIOUS split suffix back to the shared
# root before computing the next one, so repeated cuts of the same lineage
# don't compound ("Part_B_B_B...").
_SPLIT_SUFFIX_RE = re.compile(r'^(.*)_((?:Z_)*[A-Z])$')


def bounding_sphere(obj):
    """World-space (center, radius) bounding sphere from obj's bound_box."""
    bb = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    center = sum(bb, Vector((0.0, 0.0, 0.0))) / 8.0
    radius = max((c - center).length for c in bb)
    return center, max(radius, 1e-6)


def _split_suffixes():
    """Infinite generator of split-name suffixes: B, C, ..., Z (A is
    skipped - reserved/never used, matching the historical "_A" temp/"_B"
    result convention), then once single letters are exhausted, a "Z_"
    prefix marks "carry" and a fresh A-Z cycle continues after it: Z_A,
    Z_B, ..., Z_Z, then Z_Z_A, Z_Z_B, ... - extending indefinitely for the
    pathological case of cutting the same lineage more than 25 times."""
    letters = string.ascii_uppercase
    yield from letters[1:]  # B..Z
    prefix = "Z"
    while True:
        for letter in letters:
            yield f"{prefix}_{letter}"
        prefix += "_Z"


def next_split_name(base_name, existing):
    """Name for the newly-created "other half" of a cut - avoids the
    compounding "_B_B_B..." suffix that resulted from always blindly
    appending "_B" to whatever name the object already had. If `base_name`
    already ends with a split suffix from a PREVIOUS cut (e.g. "Part_B", or
    "Part_Z_A" once past Z - see `_split_suffixes()`), that suffix is
    stripped back to the shared root ("Part") first; then the next suffix
    not already taken (checked against `existing` - e.g. bpy.data.objects
    or bpy.data.meshes, or any other container supporting `in`) is used -
    so repeatedly cutting the same lineage produces Part_B, Part_C, ...,
    Part_Z, Part_Z_A, Part_Z_B, ... instead of compounding OR falling back
    to Blender's own ".001"-style renaming once single letters run out."""
    m = _SPLIT_SUFFIX_RE.match(base_name)
    root = m.group(1) if m else base_name
    for suffix in _split_suffixes():
        candidate = f"{root}_{suffix}"
        if candidate not in existing:
            return candidate
    raise AssertionError("unreachable - _split_suffixes() is an infinite generator")



def copy_modifiers(src_obj, dst_obj):
    """Copy src_obj's modifier stack onto dst_obj (best-effort - each
    modifier's settings are copied property-by-property, skipping any that
    fail to set rather than aborting the whole modifier). Used so a freshly
    split-off "_B" piece keeps behaving like the original object (e.g. a
    Subdivision Surface or Mirror modifier) instead of silently losing its
    whole modifier stack, which only `obj` (the transplanted original)
    would otherwise keep."""
    for src_mod in src_obj.modifiers:
        dst_mod = dst_obj.modifiers.new(name=src_mod.name, type=src_mod.type)
        for prop in src_mod.bl_rna.properties:
            if prop.is_readonly or prop.identifier in ('name', 'type'):
                continue
            try:
                setattr(dst_mod, prop.identifier, getattr(src_mod, prop.identifier))
            except (AttributeError, TypeError, ValueError):
                pass


def has_shape_keys(obj):
    """True if obj's mesh has shape keys - Blender refuses to apply ANY
    modifier (boolean included) to a mesh with shape keys, so Freeform
    (which needs to apply a boolean modifier to do its cut) must check this
    upfront rather than let it fail deep inside modifier_apply with a
    generic-looking error."""
    return obj.data.shape_keys is not None


def _caveat_shape_keys(obj):
    if has_shape_keys(obj):
        return (
            f"'{obj.name}' has shape keys - cutting changes the mesh's vertex count/"
            "layout, which can desync or corrupt them. Check the result(s) afterward."
        )
    return None


# Registry of "worth a heads-up, but not fatal" Blender caveats to check for
# BEFORE a cut runs (cutting mutates - or on Freeform's temp duplicates,
# replaces - the object's data, so most of these can't be reliably detected
# from the RESULT afterward; they have to be captured from the original
# object first). Add a new caveat by writing a function of the shape
# `check(obj) -> str | None` and appending it here - nothing else needs to
# change; every cut operator already calls pre_cut_caveats() once per
# target object before cutting and reports whatever comes back.
_CAVEAT_CHECKS = (
    _caveat_shape_keys,
)


def pre_cut_caveats(obj):
    """Runs every registered caveat check (see `_CAVEAT_CHECKS`) against
    `obj` as it is RIGHT NOW (call this before the cut mutates/replaces its
    data) and returns a list of warning strings - empty if there's nothing
    to flag."""
    warnings = []
    for check in _CAVEAT_CHECKS:
        msg = check(obj)
        if msg:
            warnings.append(msg)
    return warnings


def component(seed_face):
    """Flood-fill the set of faces connected to seed_face via shared edges."""
    seen = {seed_face}
    stack = [seed_face]
    while stack:
        f = stack.pop()
        for e in f.edges:
            for lf in e.link_faces:
                if lf not in seen:
                    seen.add(lf)
                    stack.append(lf)
    return seen


def group_connected_edges(edges):
    """Group `edges` into connected components (sharing a vertex). A single
    bisect_plane call against an infinite plane can cross a mesh in more
    than one disjoint place (e.g. an arm AND a lock of hair that happens to
    lie on the same plane) - this splits `geom_cut` into one group per
    actual crossing so callers can pick just the one they care about
    instead of treating every crossing as part of the same cut.

    NOTE: this only follows literal shared-BMVert identity - see
    `merge_coincident_groups()` for why a single real-world continuous
    ring can still come out fragmented into several of these groups, and
    should almost always be passed through that afterward."""
    remaining = set(edges)
    groups = []
    while remaining:
        seed = next(iter(remaining))
        group = {seed}
        remaining.discard(seed)
        stack = [seed]
        while stack:
            e = stack.pop()
            for v in e.verts:
                for e2 in v.link_edges:
                    if e2 in remaining:
                        remaining.discard(e2)
                        group.add(e2)
                        stack.append(e2)
        groups.append(group)
    return groups


def merge_coincident_groups(groups, epsilon=_COINCIDENT_EPSILON):
    """Merges groups (from group_connected_edges) whose vertices are
    spatially coincident (within `epsilon`) even though they aren't the
    SAME BMVert - group_connected_edges only follows literal shared-vertex
    identity, but a real mesh very often has multiple distinct vertices
    sitting at the exact same 3D position on purpose (UV seams, material
    boundaries, sharp/custom-split-normal edges - a neckline where skin
    meets a collar is a routine example). If the true, single, visually-
    continuous cut ring happens to cross one of these, it gets incorrectly
    fractured into several "disjoint" groups for a reason that has nothing
    to do with real topology - this was confirmed via real debug logs
    where the SAME conceptual cut reported a different number of "disjoint
    places" (3, 4, 5) on repeated attempts, and the "nearest" one picked
    was sometimes a tiny irrelevant fragment (35 edges / 66 faces) rather
    than the true encircling ring - a strong signal of exactly this
    fragmentation, not genuinely separate crossings.

    Uses a KD-tree + union-find so it stays fast even with many groups/
    vertices, rather than an O(n^2) all-pairs distance check."""
    if len(groups) <= 1:
        return groups

    all_verts = []
    group_of = []
    for gi, g in enumerate(groups):
        for e in g:
            for v in e.verts:
                all_verts.append(v)
                group_of.append(gi)

    kd = KDTree(len(all_verts))
    for i, v in enumerate(all_verts):
        kd.insert(v.co, i)
    kd.balance()

    parent = list(range(len(groups)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i, v in enumerate(all_verts):
        for _co, index, _dist in kd.find_range(v.co, epsilon):
            if group_of[index] != group_of[i]:
                union(group_of[i], group_of[index])

    merged = {}
    for gi, g in enumerate(groups):
        merged.setdefault(find(gi), set()).update(g)
    return list(merged.values())



def nearest_edge_group(groups, point):
    """Pick whichever group (from group_connected_edges) has a vertex
    closest to `point` - same coordinate space as the edges' own .co
    (typically bmesh-local). Returns (group, distance) or (None, None) if
    `groups` is empty."""
    best_group, best_dist = None, None
    for g in groups:
        d = min((v.co - point).length for e in g for v in e.verts)
        if best_dist is None or d < best_dist:
            best_group, best_dist = g, d
    return best_group, best_dist


def extract(faces):
    """Build a standalone bmesh containing only the given faces - used for
    the split-off "_B" piece (plane_cut.py, loop_cut.py). Copies each new
    face's `.smooth` (shade smooth/flat state) and `.material_index` from
    its source face - `.smooth` was silently NOT copied before, meaning the
    split-off piece always came out flat-shaded regardless of how the
    original object was actually shaded (a real bug, not just the "new cap
    faces default to flat" cosmetic issue - see _fill_boundary for that
    one)."""
    nb = bmesh.new()
    vmap = {}
    for f in faces:
        for v in f.verts:
            if v not in vmap:
                vmap[v] = nb.verts.new(v.co)
    nb.verts.index_update()
    for f in faces:
        try:
            nf = nb.faces.new([vmap[v] for v in f.verts])
            nf.material_index = f.material_index
            nf.smooth = f.smooth
        except ValueError:
            pass
    return nb


def all_components(faces):
    """Partition an iterable of BMFaces into connected components.

    Safe to call on any subset of a bmesh's faces, not just the whole mesh -
    component() flood-fills via face.edges/link_faces, which will never
    escape the given subset as long as that subset is already "closed"
    under connectivity (e.g. the whole mesh, or a previously-computed
    component of it - which is exactly how loop_cut.py uses this: it first
    partitions the whole mesh to find the one island a loop selection
    belongs to, then re-partitions *that* island after splitting it, and
    the split can only remove connections, never add new ones outside it).
    """
    remaining = set(faces)
    comps = []
    while remaining:
        seed = next(iter(remaining))
        comp = component(seed)
        comps.append(comp)
        remaining -= comp
    return comps


def cap_holes(bm, strategy='AUTO', is_edge_loop=False):
    """Fill every boundary hole in the whole bmesh. Fine for a standalone/
    freshly-extracted single piece; see cap_faces_boundary() for capping
    just one piece within a bigger bmesh that has other, unrelated faces
    (and possibly their own legitimate pre-existing open boundaries) in it.
    Returns True if every hole ended up fully closed."""
    boundary = [e for e in bm.edges if len(e.link_faces) == 1]
    return _fill_boundary(bm, boundary, strategy, is_edge_loop)


def cap_faces_boundary(bm, faces, strategy='AUTO', is_edge_loop=False):
    """Like cap_holes(), but only considers boundary edges belonging to
    `faces` - use this when `bm` also contains other, unrelated geometry
    that must not be touched."""
    boundary = [e for f in faces for e in f.edges if len(e.link_faces) == 1]
    return _fill_boundary(bm, boundary, strategy, is_edge_loop)


def _fill_boundary(bm, boundary, strategy='AUTO', is_edge_loop=False):
    """Close a boundary loop using one of several strategies - there's no
    single approach that looks right on every hole shape: a flat n-gon
    only works for planar/convex loops; triangle_fill's diagonals and
    poke's spokes don't do any visibility/concavity check, so on a
    sufficiently non-planar or concave loop (routine for edge-loop cuts on
    organic shapes) either can cut straight through the solid instead of
    following its surface. So this is user-selectable (scene.cc.cap_strategy):

    - 'AUTO': grid_fill (best case: clean quads) first, always - then a
      mode-appropriate fallback. Plane/Line cuts are *always* flat, so
      there's no need for anything fancier than a flat n-gon if grid_fill
      doesn't fully close it. Edge-loop cuts can be genuinely non-planar,
      so they keep the fuller grid -> even triangulation -> triangle fan
      chain instead (`is_edge_loop=True`, set by loop_cut.py specifically -
      NOT read from scene.cc.cut_mode, which could be stale/mismatched by
      the time this actually runs).
    - 'GRID': grid_fill -> fill+poke triangle fan (same in every mode).
    - 'NGON': a single flat face, no subdivision, no fallback - matches a
      plain Blender Fill (F) with no beautification.
    - 'FAN': always a fill+poke triangle fan from a center vertex, no
      fallback - the most predictable/least surprising option, since every
      triangle shares one point instead of using potentially-crossing
      diagonals.
    - 'BEAUTY': always an even, well-distributed triangulation
      (bmesh.ops.triangle_fill with use_beauty), no fallback - no single
      forced center point, unlike FAN.

    bmesh.ops.grid_fill also has no way to override its automatic corner
    guess the way bpy.ops.mesh.fill_grid's Span/Offset can (that's a
    higher-level operator, not exposed at this API level) - so it can fail
    outright on a very symmetric/circular loop where there's no obvious
    place to split it; the AUTO/GRID fallbacks exist for exactly that case.

    Returns True if every edge in `boundary` ended up with 2 linked faces
    (fully closed). Capping is mandatory here (no "leave it open" option) -
    an open hole is nowhere for a connector to sit later.
    """
    boundary = [e for e in boundary if e.is_valid and len(e.link_faces) == 1]
    if not boundary:
        return True
    original = list(boundary)

    # New cap faces (grid_fill/triangle_fill/holes_fill/poke) start out
    # flat-shaded (BMFace.smooth defaults to False) regardless of how the
    # rest of the object is shaded - a visible faceted seam right at the
    # cut on an otherwise Shade Smooth (or Auto Smooth) object. Match the
    # boundary's own existing neighbor faces instead of leaving that to
    # chance: majority-vote their `.smooth` state (not "first one found" -
    # a single stray flat/smooth face at the boundary shouldn't flip the
    # whole cap) and apply it to whatever ends up newly created below.
    # Pre-existing faces that just get SUBDIVIDED by the cut (not brand
    # new) already keep their own individual .smooth via the normal bmesh
    # copy - this only matters for genuinely new cap geometry.
    smooth_votes = [f.smooth for e in original for f in e.link_faces]
    smooth = (sum(smooth_votes) * 2 >= len(smooth_votes)) if smooth_votes else False
    pre_existing_faces = set(bm.faces)

    def _still_open():
        return [e for e in original if e.is_valid and len(e.link_faces) == 1]

    def _try_grid():
        try:
            bmesh.ops.grid_fill(bm, edges=_still_open(), mat_nr=0, use_smooth=smooth)
        except Exception:
            pass

    def _try_beauty():
        remaining = _still_open()
        if remaining:
            try:
                bmesh.ops.triangle_fill(bm, use_beauty=True, edges=remaining)
            except Exception:
                pass

    def _try_fill(poke):
        remaining = _still_open()
        if remaining:
            try:
                res = bmesh.ops.holes_fill(bm, edges=remaining, sides=0)
                if poke:
                    new_faces = [f for f in res.get('faces', []) if f.is_valid]
                    if new_faces:
                        bmesh.ops.poke(bm, faces=new_faces)
            except Exception:
                pass

    if strategy == 'AUTO':
        _try_grid()
        if is_edge_loop:
            _try_beauty()
            _try_fill(poke=True)
        else:
            _try_fill(poke=False)
    elif strategy == 'GRID':
        _try_grid()
        _try_fill(poke=True)
    elif strategy == 'BEAUTY':
        _try_beauty()
    elif strategy == 'FAN':
        _try_fill(poke=True)
    elif strategy == 'NGON':
        _try_fill(poke=False)

    # Whatever got created above (regardless of which strategy/fallback
    # tier actually succeeded) should match the boundary's own shading,
    # not bmesh's flat-by-default new-face state.
    for f in bm.faces:
        if f not in pre_existing_faces:
            f.smooth = smooth

    if bm.faces:
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return not any(e.is_valid and len(e.link_faces) == 1 for e in original)


def extract_and_cap(faces, name, strategy='AUTO', is_edge_loop=False):
    """extract() + cap in one step, building a finished bpy.types.Mesh.
    Returns None (and cleans up after itself) if the result has no faces or
    couldn't be fully closed."""
    nb = extract(faces)
    ok = cap_holes(nb, strategy, is_edge_loop)

    me = bpy.data.meshes.new(name)
    nb.to_mesh(me)
    nb.free()

    if not ok or len(me.polygons) == 0:
        bpy.data.meshes.remove(me)
        return None
    return me
