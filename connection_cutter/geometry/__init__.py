"""Pure geometry / bmesh helpers used by Connection Cutter's operators.

Nothing in this package touches the UI or gizmo state - functions here take
plain values (objects, plane co/normal, sizes) and return plain values
(new objects, meshes, booleans), so they're easy to unit-test in isolation.
"""
