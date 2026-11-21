"""Derive the common finger enclosure from both handed PCB uploads, in assembly mm.

Both hands use a mirrored print. Union their PCB and component keepouts before
drawing the rim, so socket mounting pads can differ without changing any key.
"""
from pathlib import Path
import json
import sys
import numpy as np
from shapely.affinity import scale
from shapely.geometry import LineString, Polygon, box
from shapely.geometry.polygon import orient
from shapely.ops import polygonize, unary_union

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT/"pcb"/"case"))
from check_case import stl_mesh


def outline_at_height(triangles, z):
    segments = []
    for tri in triangles:
        points = []
        for p, q in zip(tri, np.roll(tri, -1, axis=0)):
            if (p[2] > z) != (q[2] > z):
                xy = p[:2] + (q[:2]-p[:2]) * ((z-p[2])/(q[2]-p[2]))
                points.append(tuple(np.round(xy, 5)))
        if len(points) == 2 and points[0] != points[1]:
            segments.append(LineString(points))
    return max(polygonize(segments), key=lambda s: Polygon(s.exterior).area)


def smooth_corners(shape, radius):
    # Close short inside corners, then round convex corners. Extra clearance in
    # the input leaves room for the small milling/contour approximation.
    return (shape.buffer(radius, quad_segs=8).buffer(-2*radius, quad_segs=8)
            .buffer(radius, quad_segs=8).simplify(.025, preserve_topology=True))


def offset_same_vertices(shape, distance):
    """Offset the rounded plan perimeter while retaining corresponding bevel vertices."""
    points = np.asarray(orient(shape, 1).exterior.coords[:-1])
    incoming = points-np.roll(points, 1, axis=0)
    outgoing = np.roll(points, -1, axis=0)-points
    incoming /= np.linalg.norm(incoming, axis=1)[:, None]
    outgoing /= np.linalg.norm(outgoing, axis=1)[:, None]
    normal_sum = incoming+outgoing
    left = np.column_stack((-normal_sum[:, 1], normal_sum[:, 0]))
    shifted = points+distance*left/(1+np.sum(incoming*outgoing, axis=1))[:, None]
    assert Polygon(shifted).is_valid, "Chamfer radius too large for this perimeter"
    return np.round(shifted, 5).tolist()


def main():
    parts = ROOT/"print"/"expanded"/"left"
    shell = outline_at_height(stl_mesh(parts/"fixed_shell.stl"), 16.41)
    baseline = Polygon(shell.exterior)
    assert len(shell.interiors) == 1
    cavity = Polygon(shell.interiors[0])
    plate = outline_at_height(stl_mesh(parts/"fixed_plate.stl")*[1,-1,-1]+[0,0,18], 17.25)
    keepouts = []
    connectors = []
    for hand, sign in (("left", 1), ("right", -1)):
        name = hand+"-finger"
        folder = HERE.parent/"pcb"/name
        # The perimeter sits 0.45 mm from the plastic. The underside needs
        # extra space only at the FFC mouth beyond the laminate edge.
        rings = json.loads((folder/"outline.json").read_text())
        pcb = Polygon(rings[0])
        keepouts.append(scale(Polygon(pcb.exterior), xfact=sign, yfact=1, origin=(0,0)).buffer(.47))
        components = json.loads((folder/"circuit.json").read_text())
        j1 = next(p for p in components if p["ref"] == "J1")
        x, y = j1["xy"]; x *= sign
        assert j1["angle"] == 0
        connectors.append((x, y))
        keepouts.append(box(x-5.85, y-2.7, x+5.85, y+4.55).buffer(.45))
    assert connectors[0] == connectors[1]
    inside = unary_union([cavity, *keepouts]).buffer(1.55).buffer(-1.55).simplify(.018)
    outside = smooth_corners(baseline.union(inside.buffer(1.34)), .85)
    cover = smooth_corners(Polygon(plate.exterior).union(outside), .85)
    assert outside.contains(inside) and min(outside.exterior.distance(k) for k in keepouts) >= 1.19
    profile = {
        "connector_xy_mm": connectors[0],
        "floor_bevel": offset_same_vertices(outside, .45),
        "outer": offset_same_vertices(outside, 0),
        "inner": offset_same_vertices(inside, 0),
        "plate": offset_same_vertices(cover, 0),
        "plate_bevel": offset_same_vertices(cover, .32),
    }
    (HERE/"finger-profiles.json").write_text(json.dumps(profile, separators=(",", ":"))+"\n")


if __name__ == "__main__":
    main()
