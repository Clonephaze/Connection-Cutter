"""Sidebar (N-panel) UI for Connection Cutter."""

import bpy


class CC_PT_main_panel(bpy.types.Panel):
    bl_label = "Connection Cutter"
    bl_idname = "CC_PT_main_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Connection Cutter"

    def draw(self, context):
        layout = self.layout
        cc = context.scene.cc

        addon_prefs = context.preferences.addons[
            __package__.rsplit(".", 1)[0]
        ].preferences
        row = layout.row()
        row.prop(
            addon_prefs,
            "debug_logging",
            text="Debug Logging (see System Console)",
            icon="CONSOLE",
        )

        col = layout.column(align=True)
        col.label(text="Cap Strategy")
        col.prop(cc, "cap_strategy", text="")

        layout.separator()
        col = layout.column(align=True)
        col.label(text="1) Cut")

        if context.mode == "EDIT_MESH":
            col.operator(
                "cc.split_along_edge_loop",
                text="Cut Along Selected Loop",
                icon="MOD_BOOLEAN",
            )
            col.operator(
                "cc.insert_edge_loop", text="Insert Loop (No Cut)", icon="EDGESEL"
            )
            col.label(text="Alt+Click a loop, or insert one, then Cut")
        else:
            col.prop(cc, "cut_mode", expand=True)

            if cc.cut_mode == "PLANE":
                col.operator(
                    "cc.toggle_cut_plane",
                    text="Hide Cut Plane" if cc.cut_active else "Show Cut Plane",
                    icon="MESH_PLANE",
                    depress=cc.cut_active,
                )
                if cc.cut_active:
                    col.label(text="Move/Rotate the plane (G / R), then click Cut")
                    col.operator(
                        "cc.reset_cut_plane", text="Reset Plane", icon="LOOP_BACK"
                    )
                    col.operator("cc.apply_cut", text="Cut", icon="MOD_BOOLEAN")
            elif cc.cut_mode == "LINE":
                col.operator("cc.line_cut", text="Draw Line Cut", icon="GREASEPENCIL")
                col.label(text="Drag a straight line fully across the part")
            elif cc.cut_mode == "FREEFORM":
                col.operator(
                    "cc.freeform_cut", text="Draw Freeform Cut", icon="GREASEPENCIL"
                )
                col.label(text="Drag a curved line fully across the part")
            else:
                col.operator(
                    "cc.start_loop_bisect", text="Loop Bisect", icon="MOD_EDGESPLIT"
                )
                col.label(text="Hover to preview a loop, click to cut immediately")

        layout.separator()
        col = layout.column(align=True)
        col.label(text="2) Connectors")
        col.label(text="(TODO: Will be added to the workflow next)")
        # row = col.row(align=True)
        # row.prop(cc, "default_kind", text="")
        # col.prop(cc, "default_radius")
        # col.prop(cc, "default_depth")
        # row = col.row(align=True)
        # row.prop(cc, "auto_count")
        # col.operator("cc.auto_distribute_connectors", text="Auto-Distribute", icon='MOD_ARRAY')
        # col.operator("cc.place_connector_modal", text="Click to Place", icon='RESTRICT_SELECT_OFF')

        # if cc.connectors:
        #     layout.template_list(
        #         "UI_UL_list", "cc_connectors", cc, "connectors", cc, "connector_index", rows=3,
        #     )
        #     col.operator("cc.remove_connector", text="Remove Selected", icon='X')

        # layout.separator()
        # col = layout.column(align=True)
        # col.label(text="3) Apply")
        # col.operator("cc.apply_connectors", text="Apply Connectors", icon='CHECKMARK')


_CLASSES = (CC_PT_main_panel,)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
