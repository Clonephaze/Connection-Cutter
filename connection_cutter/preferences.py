"""Add-on preferences for Connection Cutter."""

import bpy


class CCAddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    plane_color: bpy.props.FloatVectorProperty(
        name="Cut Plane Color", subtype='COLOR', size=3,
        default=(0.15, 0.9, 1.0), min=0.0, max=1.0,
    )
    default_clearance: bpy.props.FloatProperty(
        name="Default Socket Clearance",
        description="Default fit-gap fraction applied to socket (female) connectors",
        default=0.02, min=0.0, max=0.5,
    )
    debug_logging: bpy.props.BoolProperty(
        name="Debug Logging",
        description="Print detailed diagnostics for cut/cap operations to the system console "
                    "(Window > Toggle System Console) - also turns on automatically if Blender "
                    "itself was launched with the --debug command-line flag",
        default=False,
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "plane_color")
        layout.prop(self, "default_clearance")
        layout.prop(self, "debug_logging")


def register():
    bpy.utils.register_class(CCAddonPreferences)


def unregister():
    bpy.utils.unregister_class(CCAddonPreferences)
