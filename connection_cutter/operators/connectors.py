"""Connector placement + apply operators.

Connectors are staged in `context.scene.cc.connectors` (see properties.py)
as lightweight data (kind, u/v position on the seam, radius/depth/rotation)
- nothing is boolean-applied to the mesh until CC_OT_apply_connectors runs.

TODO (design pass needed):
- CC_OT_place_connector: modal operator, raycast clicks against the seam/cap
  face(s) to add a connector at the hit point; Ctrl+click add, Alt+click
  remove, drag to reposition. Needs a way to identify "the seam" on an
  already-cut pair of objects (largest coplanar cluster, like the original
  addon's find_section(), or - better - tag the cap faces at cut time so we
  don't have to re-detect them).
- CC_OT_auto_distribute_connectors: evenly space N connectors along the seam
  boundary/area.
- A viewport draw handler to preview staged connectors before Apply.
"""

import bpy

from ..geometry import connector_shapes
from ..geometry import boolean_utils


class CC_OT_auto_distribute_connectors(bpy.types.Operator):
    """Evenly space connectors along the cut seam"""
    bl_idname = "cc.auto_distribute_connectors"
    bl_label = "Auto-Distribute Connectors"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # TODO: find the seam on the selected halves and distribute
        # context.scene.cc.auto_count connectors evenly along it.
        self.report({'WARNING'}, "Auto-distribute not implemented yet")
        return {'CANCELLED'}


class CC_OT_place_connector_modal(bpy.types.Operator):
    """Click on the cut seam to add connectors"""
    bl_idname = "cc.place_connector_modal"
    bl_label = "Place Connectors"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        # TODO: raycast-based modal placement.
        self.report({'WARNING'}, "Manual connector placement not implemented yet")
        return {'CANCELLED'}


class CC_OT_remove_connector(bpy.types.Operator):
    """Remove the active staged connector"""
    bl_idname = "cc.remove_connector"
    bl_label = "Remove Connector"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        cc = context.scene.cc
        return 0 <= cc.connector_index < len(cc.connectors)

    def execute(self, context):
        cc = context.scene.cc
        cc.connectors.remove(cc.connector_index)
        cc.connector_index = min(cc.connector_index, len(cc.connectors) - 1)
        return {'FINISHED'}


class CC_OT_apply_connectors(bpy.types.Operator):
    """Boolean-apply all staged connectors into the two halves"""
    bl_idname = "cc.apply_connectors"
    bl_label = "Apply Connectors"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return len(context.scene.cc.connectors) > 0

    def execute(self, context):
        """
        TODO: for each connector type, build its shape via
        connector_shapes.MAKE_MESH_BY_KIND, position it at (u, v) on the
        seam plane, boolean-union it into the male half and a
        clearance-scaled boolean-difference into the female half via
        boolean_utils.apply_boolean, then clear scene.cc.connectors.
        """
        self.report({'WARNING'}, "Apply connectors not implemented yet")
        return {'CANCELLED'}


_CLASSES = (
    CC_OT_auto_distribute_connectors,
    CC_OT_place_connector_modal,
    CC_OT_remove_connector,
    CC_OT_apply_connectors,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
