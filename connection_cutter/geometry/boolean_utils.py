import bpy


def set_bool_solver(mod, prefer):
    """Assign a boolean solver name that exists in this Blender build.
    Names changed across versions: old=FAST/EXACT, new=FLOAT/EXACT/MANIFOLD."""
    if prefer == 'EXACT':
        cands = ['EXACT', 'MANIFOLD', 'FLOAT', 'FAST']
    elif prefer == 'MANIFOLD':
        cands = ['MANIFOLD', 'FLOAT', 'FAST', 'EXACT']
    else:
        cands = ['FLOAT', 'FAST', 'MANIFOLD', 'EXACT']
    for c in cands:
        try:
            mod.solver = c
            return c
        except TypeError:
            continue
    return None


def apply_boolean(context, target, cutter, op, solver_pref='FAST'):
    """Add a boolean modifier to `target` against `cutter` and apply it
    immediately. Returns (True, None) on success, or (False, reason) on
    failure (the modifier is left in place in that case, in case the
    caller/user wants to inspect it) - `reason` is the actual exception
    message from Blender (e.g. "Modifier cannot be applied to a mesh with
    shape keys"), not just a generic pass/fail flag, so callers can surface
    a specific, actionable error instead of a vague "cut failed" message.
    """
    mod = target.modifiers.new("CC_Connector", 'BOOLEAN')
    mod.operation = op
    mod.object = cutter
    set_bool_solver(mod, solver_pref)
    prev = context.view_layer.objects.active
    context.view_layer.objects.active = target
    reason = None
    try:
        bpy.ops.object.modifier_apply(modifier=mod.name)
    except Exception as ex:
        reason = str(ex)
        print("Connection Cutter boolean apply error:", ex)
    context.view_layer.objects.active = prev
    return (reason is None), reason
