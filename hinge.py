"""Two-position fold joint. Coordinates in mm; the shell floor lies at z=0."""

import math

import bpy


AXIS_Z = 6.0
AXLE_RADIUS = 1.5
BORE_RADIUS = 1.75
INDEX_RADIUS = 7.0
INSERT_PILOT_RADIUS = 3.65 / 2
FACETS = 64


def _circle(x, z, radius):
    return [(round(x + radius * math.cos(math.tau * i / FACETS), 7),
             round(z + radius * math.sin(math.tau * i / FACETS), 7)) for i in range(FACETS)]


def _hull(points):
    """Convex section around a barrel, index holes, and wall attachment."""
    def half(values):
        chain = []
        for x, z in values:
            while len(chain) >= 2:
                ax, az = chain[-2]
                bx, bz = chain[-1]
                if (bx - ax) * (z - az) > (bz - az) * (x - ax):
                    break
                chain.pop()
            chain.append((x, z))
        return chain[:-1]

    points = sorted(set(points))
    return half(points) + half(reversed(points))


def _prism(name, section, y1, y2):
    """Extrude a counterclockwise XZ polygon with outward winding."""
    n = len(section)
    vertices = [(x, y, z) for y in (y1, y2) for x, z in section]
    faces = [tuple(range(n)), tuple(reversed(range(n, 2 * n)))]
    for i in range(n):
        j = (i + 1) % n
        faces.append((j, i, n + i, n + j))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _boolean(target, tool, operation):
    bpy.context.view_layer.objects.active = target
    mod = target.modifiers.new("Hinge " + operation.lower(), 'BOOLEAN')
    mod.solver = 'EXACT'
    mod.operation = operation
    mod.object = tool
    bpy.ops.object.modifier_apply(modifier=mod.name)
    mesh = tool.data
    bpy.data.objects.remove(tool, do_unlink=True)
    bpy.data.meshes.remove(mesh)


def _add_knuckle(case, side, y1, y2, index_xs=()):
    z_index = AXIS_Z + INDEX_RADIUS * math.cos(math.pi / 6)
    points = _circle(0, AXIS_Z, 4.9)
    # Fuse the long web into the case wall, leaving the floor undisturbed.
    points.extend([(side * 9.7, 1.12), (side * 9.7, 10.87)])
    holes = [(0, AXIS_Z, BORE_RADIUS)]
    for x in index_xs:
        points.extend(_circle(x, z_index, 3.4))
        holes.append((x, z_index, INSERT_PILOT_RADIUS if side > 0 else BORE_RADIUS))
    knuckle = _prism("Knuckle", _hull(points), y1, y2)
    for x, z, radius in holes:
        drill = _prism("Drill", _circle(x, z, radius), y1 - 1, y2 + 1)
        _boolean(knuckle, drill, 'DIFFERENCE')
    _boolean(case, knuckle, 'UNION')


def build_hinge(fixed, thumb):
    """Fuse knuckles into flat assembled shells, then return a nominal axle mesh.

    The offset hole of the moving ear passes from x=-3.5 to x=+3.5
    during a +60 degree Y rotation. Heat-set a short M3 insert flush to
    its +Y face before assembly. Remove the indexing screw for motion.
    """
    half_span = INDEX_RADIUS / 2
    _add_knuckle(fixed, -1, -22.0, -12.0)
    _add_knuckle(thumb, 1, -11.5, 1.0)
    _add_knuckle(thumb, 1, 12.3, 17.3, (-half_span,))
    _add_knuckle(fixed, -1, 17.8, 23.0, (-half_span, half_span))
    pin = _prism("fixed_pin", _circle(0, AXIS_Z, AXLE_RADIUS), -23.0, 24.0)
    pin["part_type"] = "Purchased hardware; nominal M3 shaft envelope"
    return pin
