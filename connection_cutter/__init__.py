"""Connection Cutter.

Cut a mesh with a plane (posed using Blender's own move/rotate gizmos on a
helper object) or a hand-drawn freeform stroke, then join the two halves
back together with printable connectors (plug/dowel, dovetail, snap-fit)
placed on the cut seam - either auto-distributed or clicked in by hand.

This is a from-scratch rewrite of the GPL-3.0 "Dovetail Key" addon by
Milad Kambari (3DRedbox Studio); see ../other addon/ for the original. A
handful of proven bmesh utility routines (plane bisect, connected-component
split, hole capping, boolean-apply-with-solver-fallback) are carried over
almost verbatim since they're solid, generic mesh math - the connector
system is a new design.
"""

from . import properties
from . import preferences
from .operators import cut as op_cut
from .operators import edge_loop as op_edge_loop
from .operators import connectors as op_connectors
from . import plane_helper
from .ui import panels

_MODULES = (
    properties,
    preferences,
    op_cut,
    op_edge_loop,
    op_connectors,
    plane_helper,
    panels,
)


def register():
    for module in _MODULES:
        module.register()


def unregister():
    for module in reversed(_MODULES):
        module.unregister()
