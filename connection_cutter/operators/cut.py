"""Cut-plane operators.

plane_helper.py is the primary way users pose the plane now: "Show Cut
Plane" creates a normal Blender object that the user moves/rotates with
Blender's own built-in gizmos (or G/R, or the N-panel Transform fields) -
these operators just create/reset/remove that helper object and read its
transform back out when committing the actual cut.
"""

import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

from .. import plane_helper
from ..geometry import plane_cut, freeform_cut, line_cut, mesh_utils


class CC_OT_toggle_cut_plane(bpy.types.Operator):
    """Show/hide the cut-plane helper object, remembering every currently
    selected mesh so Cut can act on all of them"""
    bl_idname = "cc.toggle_cut_plane"
    bl_label = "Cut Plane"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.type == 'MESH'

    def execute(self, context):
        cc = context.scene.cc
        if cc.cut_active:
            plane_helper.remove_plane_object()
            plane_helper.restore_object_gizmo_overlay(context)
            cc.cut_active = False
            active = None
            for item in cc.target_objects:
                if item.obj is not None:
                    item.obj.select_set(True)
                    active = item.obj
            if active is not None:
                context.view_layer.objects.active = active
            cc.target_objects.clear()
            return {'FINISHED'}

        targets = [o for o in context.selected_objects if o.type == 'MESH']
        if not targets:
            targets = [context.active_object]
        cc.target_objects.clear()
        for obj in targets:
            cc.target_objects.add().obj = obj

        plane_obj = plane_helper.create_plane_object(context, targets)
        plane_helper.enable_object_gizmo_overlay(context)
        for o in list(context.selected_objects):
            o.select_set(False)
        plane_obj.select_set(True)
        context.view_layer.objects.active = plane_obj
        cc.cut_active = True
        return {'FINISHED'}


class CC_OT_reset_cut_plane(bpy.types.Operator):
    """Reset the cut plane to the target objects' combined bounding-box
    center, facing the current view."""
    bl_idname = "cc.reset_cut_plane"
    bl_label = "Reset Cut Plane"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        cc = context.scene.cc
        return cc.cut_active and len(cc.target_objects) > 0 and plane_helper.get_plane_object() is not None

    def execute(self, context):
        cc = context.scene.cc
        targets = [item.obj for item in cc.target_objects if item.obj is not None]
        plane_helper.reset_plane_transform(context, plane_helper.get_plane_object(), targets)
        return {'FINISHED'}


class CC_OT_apply_cut(bpy.types.Operator):
    """Cut every target object with the current cut plane, splitting each
    one into two objects"""
    bl_idname = "cc.apply_cut"
    bl_label = "Cut"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        cc = context.scene.cc
        return cc.cut_active and len(cc.target_objects) > 0 and plane_helper.get_plane_object() is not None

    def execute(self, context):
        cc = context.scene.cc
        targets = [item.obj for item in cc.target_objects if item.obj is not None]
        plane_obj = plane_helper.get_plane_object()
        plane_co, plane_no = plane_helper.plane_co_no(plane_obj)

        new_selection = []
        skipped = 0
        caveats = []
        for obj in targets:
            caveats.extend(mesh_utils.pre_cut_caveats(obj))
            # near_point anchors the cut to whichever crossing of the
            # (mathematically infinite) plane is nearest to where the user
            # actually posed the helper object - without this, the plane's
            # visible size/position is purely cosmetic and the cut affects
            # EVERY place the infinite plane crosses the mesh, even far
            # away from the posed helper (the same bug Line Cut had before
            # it started using near_point - see plane_cut.bisect_and_split's
            # docstring). Every other crossing is left completely alone.
            result = plane_cut.bisect_and_split(context, obj, plane_co, plane_no, near_point=plane_co)
            if result is None:
                skipped += 1
                continue
            new_selection.extend(result)

        if not new_selection:
            self.report({'WARNING'}, "Cut plane doesn't cross any target object")
            return {'CANCELLED'}

        plane_helper.remove_plane_object()
        plane_helper.restore_object_gizmo_overlay(context)
        for o in list(context.selected_objects):
            o.select_set(False)
        for o in new_selection:
            o.select_set(True)
        context.view_layer.objects.active = new_selection[0]

        if skipped:
            self.report({'WARNING'}, f"Cut plane didn't cross {skipped} of {len(targets)} target object(s)")
        if caveats:
            self.report({'WARNING'}, " | ".join(caveats))

        cc.cut_active = False
        cc.target_objects.clear()
        return {'FINISHED'}


class CC_OT_freeform_cut(bpy.types.Operator):
    """Draw a curved line across the part(s) to cut along it"""
    bl_idname = "cc.freeform_cut"
    bl_label = "Draw Freeform Cut"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        cc = context.scene.cc
        return (
            context.active_object is not None and context.active_object.type == 'MESH'
            and not cc.cut_active
        )

    def invoke(self, context, event):
        if context.area is None or context.area.type != 'VIEW_3D':
            self.report({'ERROR'}, "Use in the 3D Viewport")
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        self.objs = [o for o in context.selected_objects if o.type == 'MESH']
        if not self.objs:
            self.objs = [context.active_object]
        self.points = []
        self._drawing = False
        self._handle = bpy.types.SpaceView3D.draw_handler_add(
            self.draw_px, (), 'WINDOW', 'POST_PIXEL')
        context.window.cursor_modal_set('KNIFE')
        context.workspace.status_text_set(
            "LMB drag across the part: draw cut line   |   ESC / RMB: cancel")
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if context.area:
            context.area.tag_redraw()

        if event.type == 'MOUSEMOVE' and self._drawing:
            self.points.append((event.mouse_region_x, event.mouse_region_y))

        elif event.type == 'LEFTMOUSE':
            if event.value == 'PRESS':
                self._drawing = True
                self.points = [(event.mouse_region_x, event.mouse_region_y)]
                return {'RUNNING_MODAL'}
            elif event.value == 'RELEASE':
                stroke = self.points[:]
                region, region_data = context.region, context.region_data
                self.finish(context)
                if len(stroke) >= 2:
                    new_selection = []
                    skipped = 0
                    reasons = []
                    caveats = []
                    for obj in self.objs:
                        caveats.extend(mesh_utils.pre_cut_caveats(obj))
                        result, reason = freeform_cut.bisect_and_split_freeform(
                            context, obj, region, region_data, stroke)
                        if result is None:
                            skipped += 1
                            reasons.append(f"{obj.name}: {reason}")
                            continue
                        new_selection.extend(result)

                    if not new_selection:
                        # Surface the REAL reason(s) instead of a generic
                        # message - e.g. shape keys or a boolean solver
                        # failure look nothing like "didn't cross the part"
                        # and used to be indistinguishable from it.
                        self.report({'ERROR'}, "; ".join(reasons) if reasons else
                                    "Stroke must fully cross the part. Try again")
                        return {'CANCELLED'}

                    for o in list(context.selected_objects):
                        o.select_set(False)
                    for o in new_selection:
                        o.select_set(True)
                    context.view_layer.objects.active = new_selection[0]
                    if skipped:
                        self.report(
                            {'WARNING'},
                            f"Skipped {skipped} of {len(self.objs)} part(s) - " + "; ".join(reasons),
                        )
                    if caveats:
                        self.report({'WARNING'}, " | ".join(caveats))
                return {'FINISHED'}

        elif event.type in {'RIGHTMOUSE', 'ESC'}:
            self.finish(context)
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}

    def finish(self, context):
        if self._handle:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
            self._handle = None
        context.window.cursor_modal_restore()
        context.workspace.status_text_set(None)
        if context.area:
            context.area.tag_redraw()

    def draw_px(self):
        if len(self.points) < 2:
            return
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        coords = [(x, y, 0.0) for x, y in self.points] if bpy.app.version >= (4, 0, 0) else self.points
        batch = batch_for_shader(shader, 'LINE_STRIP', {"pos": coords})
        gpu.state.blend_set('ALPHA')
        gpu.state.line_width_set(4.0)
        shader.bind()
        shader.uniform_float("color", (1.0, 0.15, 0.15, 1.0))
        batch.draw(shader)
        gpu.state.line_width_set(1.0)
        gpu.state.blend_set('NONE')


class CC_OT_line_cut(bpy.types.Operator):
    """Drag a straight line across the part(s) to cut along it - like the
    original Dovetail Key addon's line slice"""
    bl_idname = "cc.line_cut"
    bl_label = "Draw Line Cut"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.type == 'MESH'

    def invoke(self, context, event):
        if context.area is None or context.area.type != 'VIEW_3D':
            self.report({'ERROR'}, "Use in the 3D Viewport")
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        self.objs = [o for o in context.selected_objects if o.type == 'MESH']
        if not self.objs:
            self.objs = [context.active_object]
        self.start = None
        self.end = None
        self._handle = bpy.types.SpaceView3D.draw_handler_add(
            self.draw_px, (), 'WINDOW', 'POST_PIXEL')
        context.window.cursor_modal_set('KNIFE')
        context.workspace.status_text_set(
            "LMB drag across the part: draw cut line   |   ESC / RMB: cancel")
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if context.area:
            context.area.tag_redraw()

        if event.type == 'MOUSEMOVE':
            self.end = (event.mouse_region_x, event.mouse_region_y)

        elif event.type == 'LEFTMOUSE':
            if event.value == 'PRESS':
                self.start = (event.mouse_region_x, event.mouse_region_y)
                self.end = self.start
                return {'RUNNING_MODAL'}
            elif event.value == 'RELEASE':
                start, end = self.start, self.end
                region, region_data = context.region, context.region_data
                self.finish(context)
                if start and end and (Vector(end) - Vector(start)).length > 2:
                    new_selection = []
                    skipped = 0
                    caveats = []
                    for obj in self.objs:
                        caveats.extend(mesh_utils.pre_cut_caveats(obj))
                        result = line_cut.bisect_and_split_line(
                            context, obj, region, region_data, start, end)
                        if result is None:
                            skipped += 1
                            continue
                        new_selection.extend(result)

                    if not new_selection:
                        self.report(
                            {'WARNING'},
                            "Line must fully cross the part. Try again (enable Debug Logging "
                            "in the panel/preferences and check the System Console for why)",
                        )
                        return {'CANCELLED'}

                    for o in list(context.selected_objects):
                        o.select_set(False)
                    for o in new_selection:
                        o.select_set(True)
                    context.view_layer.objects.active = new_selection[0]
                    if skipped:
                        self.report(
                            {'WARNING'},
                            f"Line didn't cross {skipped} of {len(self.objs)} part(s)",
                        )
                    if caveats:
                        self.report({'WARNING'}, " | ".join(caveats))
                return {'FINISHED'}

        elif event.type in {'RIGHTMOUSE', 'ESC'}:
            self.finish(context)
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}

    def finish(self, context):
        if self._handle:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
            self._handle = None
        context.window.cursor_modal_restore()
        context.workspace.status_text_set(None)
        if context.area:
            context.area.tag_redraw()

    def draw_px(self):
        if not self.start or not self.end:
            return
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        coords = [(self.start[0], self.start[1], 0.0), (self.end[0], self.end[1], 0.0)]
        batch = batch_for_shader(shader, 'LINES', {"pos": coords})
        gpu.state.blend_set('ALPHA')
        gpu.state.line_width_set(4.0)
        shader.bind()
        shader.uniform_float("color", (1.0, 0.6, 0.15, 1.0))
        batch.draw(shader)
        gpu.state.line_width_set(1.0)
        gpu.state.blend_set('NONE')


_CLASSES = (
    CC_OT_toggle_cut_plane, CC_OT_reset_cut_plane, CC_OT_apply_cut,
    CC_OT_freeform_cut, CC_OT_line_cut,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
