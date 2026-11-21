"""Verify the actual shell STLs and their interfaces. Requires Python with NumPy."""

import hashlib
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "validation"))
from check_parts import STL_FACE, self_intersections, trace

DESIGN = json.loads((ROOT/"validation"/"design.json").read_text())["Expanded"]


def stl_mesh(path):
    raw = path.read_bytes()
    n = int.from_bytes(raw[80:84], "little")
    assert len(raw) == 84+50*n
    return np.frombuffer(raw[84:], dtype=STL_FACE)["tri"].astype(float)


def topology(tris):
    vertices, inds = np.unique(tris.reshape(-1,3), axis=0, return_inverse=True)
    faces = inds.reshape(-1,3)
    sides = np.concatenate([faces[:,[0,1]], faces[:,[1,2]], faces[:,[2,0]]])
    edges = np.sort(sides, axis=1)
    _, edge_index, count = np.unique(edges, axis=0, return_inverse=True, return_counts=True)
    balance = np.bincount(edge_index, weights=np.where(sides[:,0] < sides[:,1], 1, -1))
    neighbors = defaultdict(set)
    for i,(a,b,c) in enumerate(faces):
        for v in (a,b,c):
            neighbors[v].add(i)
    remaining = set(range(len(faces)))
    components = 0
    while remaining:
        stack = [remaining.pop()]
        components += 1
        while stack:
            for v in faces[stack.pop()]:
                new = remaining.intersection(neighbors[v])
                remaining.difference_update(new)
                stack.extend(new)
    normals = np.cross(tris[:,1]-tris[:,0], tris[:,2]-tris[:,0])
    contacts, _ = self_intersections(vertices, faces)
    result = dict(triangles=len(tris), connected_components=components,
                  bad_edges=int(np.sum((count!=2) | (balance!=0))),
                  zero_area_triangles=int(np.sum(np.linalg.norm(normals,axis=1)==0)),
                  self_intersections=contacts, signed_volume_mm3=round(float((normals*tris[:,0]).sum()/6),2))
    if (components != 1 or result["bad_edges"] or result["zero_area_triangles"]
            or contacts or result["signed_volume_mm3"] <= 0):
        raise ValueError(f"Invalid exported shell: {result}")
    return result


def box_contact(tris, lo, hi):
    """Separating-axis test between the AABB and each potentially touching facet."""
    lo, hi = np.array(lo), np.array(hi)
    half = (hi-lo)/2
    local = tris[np.all((tris.max(axis=1)>=lo) & (tris.min(axis=1)<=hi), axis=1)] - (lo+hi)/2
    edges = np.roll(local,-1,axis=1) - local
    axes = [np.cross(edges[:,0], edges[:,1])]
    axes.extend(np.cross(edges[:,i], axis) for i in range(3) for axis in np.eye(3))
    overlaps = np.ones(len(local), dtype=bool)
    for axis in axes:
        projections = np.einsum("nij,nj->ni",local,axis)
        r = np.abs(axis) @ half
        overlaps &= (projections.min(axis=1)<=r) & (projections.max(axis=1)>=-r)
    return bool(overlaps.any())


def verify_interfaces(hand, name, tris):
    # Return both the shell and the unchanged, bed-oriented switch plate to left assembly space.
    sign = 1 if hand == "left" else -1
    tris = tris * [sign,1,1]
    plate = stl_mesh(ROOT/"print"/"expanded"/hand/(name+"_plate.stl")) * [sign,-1,-1] + [0,0,18]
    geometry = np.concatenate([tris,plate])
    cx = -27 if name == "fixed" else 22.35
    cy = DESIGN[name]["loop_port"][1]
    info = {}

    def first(origin, direction):
        hits = trace(tris,origin,direction)
        return hits[0] if len(hits) else math.inf

    def close(actual, expected, feature):
        if abs(actual-expected) > .015:
            raise ValueError(f"{hand}/{name} {feature}: {actual} mm, expected {expected}")

    for dx in (-3.88,0,3.88):
        for z in (4.20,8.2,11.9,16.4):
            assert first((cx+dx,cy+7,z),(0,-1,0)) > 12.0, "Obstructed cable slot"
    info["flex_open_to_rim_width_mm"] = 8.0
    if name == "thumb":
        for y, width, z0, z1 in ((.5,12,5,11.8),(-14,9,8,11.8)):
            z = (z0+z1)/2
            for direction in (-1,1):
                close(first((33.0,y,z),(0,direction,0)), width/2, "window width")
                close(first((33.0,y,z),(0,0,direction)), (z1-z0)/2, "window height")
        # Boxes are assembled in open space and checked against all shell and post surfaces.
        gauges = {
            "XIAO module laminate": ([11.1,-8.39,9.65], [32.05,9.39,11.32]),
            "USB receptacle nose": ([31.95,-4.00,6.70], [33.55,5.0,10.2]),
            "plug tongue approach": ([33.0,-4.00,6.75], [40,5.0,10.15]),
            "PCM12 actuator approach": ([30.2,-16.4,9.5], [38,-11.6,10.85]),
            "protected battery envelope": ([12,-33,2.9], [30,-9,6.9]),
        }
        for label,(low,high) in gauges.items():
            if box_contact(geometry,low,high):
                raise ValueError(f"{hand}: interference with {label}")
        info["validated_boxes_left_assembly_mm"] = gauges
        close(first((32.6,8.0,10.0),(1,0,0)),33.65406-32.6,"recess skin outer face")
        close(first((32.6,8.0,10.0),(-1,0,0)),32.6-32.45,"recess skin inner face")
        info["xiao_shoulder_skin_mm"] = 1.204
        # A straight ribbon has two parallel edges offset half its width from its centerline.
        direction = np.array([math.sin(math.radians(9)),math.cos(math.radians(9))])
        normal = np.array([direction[1],-direction[0]])
        post_gaps = []
        for post in [(15,21),(29,18)]:
            dist = abs((np.array(post)-[20.25,13.45]) @ normal)
            post_gaps.append(round(float(dist-6.5/2-2.45),3))
        assert min(post_gaps)>0
        info["FFC_to_two_plate_posts_nominal_gap_mm"] = post_gaps
    return info


def main():
    records = []
    for path in sorted((HERE/"print").glob("*/*.stl")):
        hand = path.parent.name
        name = path.stem.split("_")[0]
        tris = stl_mesh(path)
        result = dict(path=str(path.relative_to(HERE)), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                      **topology(tris), **verify_interfaces(hand,name,tris))
        records.append(result)
        print(path.relative_to(HERE), result["triangles"], "triangles; passed", flush=True)
    assert len(records) == 4
    (HERE/"shell-checks.json").write_text(json.dumps(records,indent=2)+"\n")


if __name__ == "__main__":
    main()
