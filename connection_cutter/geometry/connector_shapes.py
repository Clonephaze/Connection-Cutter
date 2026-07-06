"""Mesh generators for each connector kind.

Each `make_*_mesh` function returns a bpy.types.Mesh sized in *local* space,
centered on the origin with +Z as the connector's depth axis (i.e. the seam
plane's normal) - callers position/rotate/scale the resulting object to the
connector's (u, v) placement on the seam.

Only the plug shape is implemented for now; dovetail/snap are placeholders
pending the connector-shape design pass.
"""

import bmesh
import bpy


def make_plug_mesh(name, radius, depth, segments=6):
    """Simple cylinder plug/dowel connector with few segments for easy printing.
    TODO: Considering a small taper on the cylinder ends to make it easy to insert."""
    bm = bmesh.new()
    bmesh.ops.create_cone(
        bm, cap_ends=True, cap_tris=False, segments=segments,
        radius1=radius, radius2=radius, depth=depth,
    )
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return me


def make_dovetail_mesh(name, width, taper, height, depth):
    """Tapered dovetail key connector.

    TODO: port + fix up the dovetail box math from the original addon's
    MK_OT_section_dovetail (width/taper/height/depth proportions), or
    redesign. Probably gonna redesign it, since the original was a bit of a hack and
    doesn't properly check geometries for valid space for the dovetail.
    """
    raise NotImplementedError("Dovetail connector shape not implemented yet")


def make_snap_mesh(name, radius, depth, groove_depth=0.0015):
    """Cylindrical connector with a snap-fit retaining groove/bead.

    TODO: design the actual snap geometry.
    """
    raise NotImplementedError("Snap-fit connector shape not implemented yet")


MAKE_MESH_BY_KIND = {
    'PLUG': lambda name, item: make_plug_mesh(name, item.radius, item.depth),
    'DOVETAIL': lambda name, item: make_dovetail_mesh(
        name, item.radius * 2, 0.6, item.depth, item.radius * 2),
    'SNAP': lambda name, item: make_snap_mesh(name, item.radius, item.depth),
}
