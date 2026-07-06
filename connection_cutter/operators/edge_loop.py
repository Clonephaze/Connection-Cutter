"""Edge-loop cutting operators - see geometry/loop_cut.py for the shared
split/cap backend both of these ultimately call.
"""

import bpy

from ..geometry import loop_cut, mesh_utils


class CC_OT_loop_bisect(bpy.types.Macro):
    """Hover to preview a loop around the part (like Ctrl+R) and click to
    cut along it immediately - "bisect", but following the mesh's own
    topology instead of an infinite flat plane, and without a separate
    select-then-cut step.

    This is a Macro (see register() below) chaining Blender's own
    mesh.loopcut_slide straight into CC_OT_split_along_edge_loop, so placing
    the loop *is* the cut - one gesture, not insert-then-confirm-then-cut.
    If the loop placement is cancelled (Esc/right-click), Blender's macro
    system stops there and the split step never runs.
    """
    bl_idname = "cc.loop_bisect"
    bl_label = "Loop Bisect"
    bl_options = {'REGISTER', 'UNDO'}


class CC_OT_start_loop_bisect(bpy.types.Operator):
    """Enter Edit Mode and hand off to the Loop Bisect macro (hover to
    preview a loop around the part, click to cut along it immediately)"""
    bl_idname = "cc.start_loop_bisect"
    bl_label = "Loop Bisect"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.type == 'MESH'

    def invoke(self, context, event):
        if context.mode != 'EDIT_MESH':
            bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='DESELECT')
        return bpy.ops.cc.loop_bisect('INVOKE_DEFAULT')


class CC_OT_insert_edge_loop(bpy.types.Operator):
    """Enter Edit Mode and insert a fresh loop cut (Blender's own interactive
    loop-cut-and-slide) without cutting - leaves the new loop selected, for
    when you want to nudge/adjust it (or select more loops) before manually
    clicking Cut Along Selected Loop"""
    bl_idname = "cc.insert_edge_loop"
    bl_label = "Insert Loop (No Cut)"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.type == 'MESH'

    def invoke(self, context, event):
        if context.mode != 'EDIT_MESH':
            bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='DESELECT')
        return bpy.ops.mesh.loopcut_slide('INVOKE_DEFAULT')


class CC_OT_split_along_edge_loop(bpy.types.Operator):
    """Split the mesh in two along the currently selected edge loop(s)"""
    bl_idname = "cc.split_along_edge_loop"
    bl_label = "Cut Along Selected Loop"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (
            context.mode == 'EDIT_MESH'
            and context.active_object is not None
            and context.active_object.type == 'MESH'
        )

    def execute(self, context):
        obj = context.active_object
        caveats = mesh_utils.pre_cut_caveats(obj)
        result = loop_cut.split_along_selection(context, obj)
        if result is None:
            self.report(
                {'WARNING'},
                "Selected edges must form a closed loop that fully separates its connected "
                "part of the mesh in two (other unrelated islands in the same object are fine)",
            )
            return {'CANCELLED'}

        obj_a, obj_b = result
        for o in list(context.selected_objects):
            o.select_set(False)
        obj_a.select_set(True)
        obj_b.select_set(True)
        context.view_layer.objects.active = obj_a
        if caveats:
            self.report({'WARNING'}, " | ".join(caveats))
        return {'FINISHED'}


_CLASSES = (
    CC_OT_split_along_edge_loop,
    CC_OT_loop_bisect,
    CC_OT_start_loop_bisect,
    CC_OT_insert_edge_loop,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    # Macro steps must be defined after the macro class itself is
    # registered - runs mesh.loopcut_slide interactively, then immediately
    # our own split operator using whatever it left selected.
    CC_OT_loop_bisect.define("MESH_OT_loopcut_slide")
    CC_OT_loop_bisect.define("CC_OT_split_along_edge_loop")


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
