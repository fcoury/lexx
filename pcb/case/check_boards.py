"""Check each KiCad board perimeter and its support locations in the printed case.

Run with Python, NumPy and Shapely 2. Dimensions are millimetres in assembly space.
"""

import json
import math
import re
import sys
from pathlib import Path

import numpy as np
from shapely.geometry import LineString, MultiPoint, Point, box
from shapely.ops import polygonize, unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_case import HERE, ROOT, stl_mesh, trace

sys.path.insert(0, str(ROOT/"pcb"/"tools"))
from plan import DIODE, SOCKET, pose

PROFILE = {"MX":SOCKET, "SOD123":DIODE, "FFC12":box(-5.9,-2.8,5.9,4.6),
           "XIAO":box(-.1,-22.6,17.9,0), "PowerSwitch":box(-4.4,-2.45,4.4,3.4),
           "Battery":box(-4.7,-5,4.7,5.2)}


def edge_cuts(path):
    source = path.read_text()
    assert re.search(r"\(general\s+\(thickness 1\.6\)", source)
    lines, holes = [], []
    for kind, block in re.findall(r"(?ms)^\t\(gr_(\w+)\s+(.*?)^\t\)",source):
        if '(layer "Edge.Cuts")' not in block:
            continue
        def xy(tag):
            p = re.search(r"\("+tag+r" ([-.\d]+) ([-.\d]+)\)",block)
            return float(p[1])-150, 100-float(p[2])
        if kind == "line":
            lines.append(LineString([xy("start"),xy("end")]))
        elif kind == "circle":
            center = xy("center")
            holes.append(Point(*center).buffer(math.dist(center,xy("end")),quad_segs=72))
        else:
            raise ValueError(f"Unsupported KiCad outline primitive: {kind}")
    outer, = polygonize(lines)
    board = outer.difference(unary_union(holes))
    assert board.is_valid and not board.is_empty
    return board


def projected_surface(tris, z_min, z_max):
    """Find the XY projection of every triangular facet inside a closed Z slab."""
    shapes = []
    for tri in tris[(tris[:,:,2].min(axis=1)<=z_max) & (tris[:,:,2].max(axis=1)>=z_min)]:
        points = [p[:2] for p in tri if z_min <= p[2] <= z_max]
        for p,q in zip(tri, np.roll(tri,-1,axis=0)):
            for z in (z_min,z_max):
                if min(p[2],q[2]) < z < max(p[2],q[2]):
                    points.append(p[:2]+(q-p)[:2]*((z-p[2])/(q[2]-p[2])))
        if points:
            shapes.append(MultiPoint(points).convex_hull)
    return unary_union(shapes)


def verify(hand, deck):
    name = hand+"-"+deck
    folder = ROOT/"pcb"/name
    pcb = folder/(name+".kicad_pcb")
    board = edge_cuts(pcb)
    # Socket and other underside envelope polygons follow the handed placement data.
    parts = json.loads((folder/"circuit.json").read_text())
    parts_area = unary_union([pose(PROFILE[p["footprint"].split(":")[-1]],*p["xy"],p["angle"]) for p in parts])
    kind = "fixed" if deck=="finger" else "thumb"
    shell = stl_mesh(HERE/"print"/hand/(kind+"_shell.stl"))
    plate = stl_mesh(ROOT/"print"/"expanded"/hand/(kind+"_plate.stl"))*[1,-1,-1]+[0,0,18]
    case_gap = board.distance(projected_surface(shell,11.4,13.0))
    post_gap = board.distance(projected_surface(plate,11.4,13.0))
    assert min(case_gap,post_gap)>0, (name,case_gap,post_gap)
    supports = json.loads((HERE/"supports.json").read_text())[kind]
    gaps = []
    for x,y,radius in supports:
        x = x if hand=="left" else -x
        top = Point(x,y).buffer(radius,quad_segs=48)
        assert board.contains(top)
        gap = top.distance(parts_area)
        assert gap > 0
        highest = trace(shell,[x,y,14],[0,0,-1])[0]
        assert abs(14-highest-11.2)<.002, (name,x,y,highest)
        gaps.append(round(gap,3))
    return {"board":name, "edge_cuts_area_mm2":round(board.area,3),
            "shell_gap_mm":round(case_gap,3), "plate_post_gap_mm":round(post_gap,3),
            "support_z_gap_mm":.20, "support_to_component_xy_gaps_mm":gaps}


if __name__ == "__main__":
    results = [verify(hand,deck) for hand in ("left","right") for deck in ("finger","thumb")]
    print(json.dumps(results,indent=2))
    (HERE/"board-fit.json").write_text(json.dumps(results,indent=2)+"\n")
