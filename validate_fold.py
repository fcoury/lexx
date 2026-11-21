"""Verify a foldable MX case in Blender 5.2.4 (all scene coordinates in mm).

blender -b case.blend --python-exit-code 1 --python validate_fold.py -- --output clearance.json

The custom property on Controls drives a rigid rotation around ThumbPivot's
world Y axis. Every fixed_* mesh is checked against every thumb_* mesh.
The continuous bound assumes the same rigid, linear-angle rotation between
samples. Distances below are nominal CAD clearances, before print tolerances.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils.bvhtree import BVHTree
import numpy as np


# Larger gaps need no exact distance. All broad-phase pruning also includes
# the local rotational displacement, so a fast-moving corner cannot be missed.
REPORT_LIMIT = 1.0
NUMERIC_MARGIN = 0.0005
BATCH_SIZE = 16384


def dot(a, b):
    return np.einsum("ij,ij->i", a, b)


def ratio(a, b):
    return np.divide(a, b, out=np.zeros_like(a), where=b > 1e-24)


def closest_on_edges(point, triangle):
    """Squared distance from a point to the perimeter of a triangle."""
    best = np.full(len(point), np.inf)
    for i in range(3):
        p = triangle[:, i]
        edge = triangle[:, (i + 1) % 3] - p
        rel = point - p
        t = np.clip(ratio(dot(rel, edge), dot(edge, edge)), 0, 1)
        delta = rel - t[:, None] * edge
        best = np.minimum(best, dot(delta, delta))
    return best


def point_triangle_sq(point, triangle):
    a, b, c = triangle[:, 0], triangle[:, 1], triangle[:, 2]
    ab, ac = b - a, c - a
    normal = np.cross(ab, ac)
    ap = point - a
    n2 = dot(normal, normal)
    s = dot(np.cross(ap, ac), normal)
    t = dot(np.cross(ab, ap), normal)
    inside = (s >= 0) & (t >= 0) & (s + t <= n2) & (n2 > 1e-24)
    distance = ratio(dot(ap, normal) ** 2, n2)
    outside = ~inside
    distance[outside] = closest_on_edges(point[outside], triangle[outside])
    return distance


def triangle_distances(left, right):
    """Exact feature distances for disjoint triangles, in vectorized batches.

    Vertex/face tests include all vertex/edge and vertex/vertex features.
    Interior edge/edge witnesses only require the unconstrained line parameters.
    The independent BVH intersection test covers penetrating triangles.
    """
    best = np.full(len(left), np.inf)
    for i in range(3):
        best = np.minimum(best, point_triangle_sq(left[:, i], right))
        best = np.minimum(best, point_triangle_sq(right[:, i], left))
    for i in range(3):
        a = left[:, i]
        u = left[:, (i + 1) % 3] - a
        for j in range(3):
            b = right[:, j]
            v = right[:, (j + 1) % 3] - b
            normal = np.cross(u, v)
            denom = dot(normal, normal)
            d = b - a
            s = dot(np.cross(d, v), normal)
            t = dot(np.cross(d, u), normal)
            inside = (denom > 1e-24) & (s >= 0) & (s <= denom) & (t >= 0) & (t <= denom)
            best = np.minimum(best, np.where(inside, ratio(dot(d, normal) ** 2, denom), np.inf))
    return np.sqrt(np.maximum(0, best))


def box_gap(lo, hi, other_lo, other_hi):
    return np.maximum(0, np.maximum(lo - other_hi, other_lo - hi))


class Node:
    def __init__(self, mesh, indices):
        self.lo = mesh.lo[indices].min(axis=0)
        self.hi = mesh.hi[indices].max(axis=0)
        self.radius = mesh.radii[indices].max()
        self.children = None
        self.indices = indices
        if len(indices) > 12:
            centers = (mesh.lo[indices] + mesh.hi[indices]) / 2
            axis = np.ptp(centers, axis=0).argmax()
            order = indices[centers[:, axis].argsort()]
            mid = len(indices) // 2
            self.children = (Node(mesh, order[:mid]), Node(mesh, order[mid:]))


class Surface:
    def __init__(self, obj, graph, pivot):
        evaluated = obj.evaluated_get(graph)
        mesh = evaluated.to_mesh()
        try:
            mesh.calc_loop_triangles()
            coords = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
            mesh.vertices.foreach_get("co", coords)
            faces = np.empty(len(mesh.loop_triangles) * 3, dtype=np.int32)
            mesh.loop_triangles.foreach_get("vertices", faces)
            self.faces = faces.reshape(-1, 3)
            self.matrix = np.array(evaluated.matrix_world)
            self.vertices = coords.reshape(-1, 3) @ self.matrix[:3, :3].T + self.matrix[:3, 3]
        finally:
            evaluated.to_mesh_clear()
        self.name = obj.name
        self.tri = self.vertices[self.faces]
        self.lo = self.tri.min(axis=1)
        self.hi = self.tri.max(axis=1)
        radial = self.tri[:, :, [0, 2]] - pivot[[0, 2]]
        self.radii = np.linalg.norm(radial, axis=2).max(axis=1)
        self.root = Node(self, np.arange(len(self.faces)))
        self.bvh = BVHTree.FromPolygons(self.vertices.tolist(), self.faces.tolist(), all_triangles=True)

    @property
    def component_points(self):
        # One boundary point per connected shell is enough for containment
        # testing when surface pairs have already been shown to be disjoint.
        if hasattr(self, "_component_points"):
            return self._component_points
        parent = list(range(len(self.vertices)))

        def root(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for a, b, c in self.faces:
            i = root(a)
            parent[root(b)] = i
            parent[root(c)] = i
        self._component_points = self.vertices[sorted({root(i) for i in np.unique(self.faces)})]
        return self._component_points

    def contains(self, point):
        if np.any(point < self.root.lo) or np.any(point > self.root.hi):
            return False
        # Three oblique rays avoid relying on imported face winding. An odd
        # crossing count on a majority means the point lies in solid material.
        votes = 0
        for direction in ((0.217, 0.423, 0.88), (-0.63, 0.65, 0.42), (0.38, -0.89, 0.23)):
            origin = point
            count = 0
            while True:
                hit, _, _, _ = self.bvh.ray_cast(origin, direction)
                if hit is None:
                    break
                count += 1
                origin = np.array(hit) + np.array(direction) * 0.0001
            votes += count % 2
        return votes >= 2


def nearby_pairs(left, right, travel):
    stack = [(left.root, right.root)]
    groups = []
    while stack:
        a, b = stack.pop()
        threshold = REPORT_LIMIT + travel * b.radius + NUMERIC_MARGIN
        if np.any(box_gap(a.lo, a.hi, b.lo, b.hi) > threshold):
            continue
        if a.children and (not b.children or len(a.indices) >= len(b.indices)):
            stack.extend((child, b) for child in a.children)
        elif b.children:
            stack.extend((a, child) for child in b.children)
        else:
            i, j = a.indices, b.indices
            gaps = box_gap(left.lo[i, None], left.hi[i, None], right.lo[j], right.hi[j])
            cut = REPORT_LIMIT + travel * right.radii[j] + NUMERIC_MARGIN
            x, y = np.where(np.einsum("ijk,ijk->ij", gaps, gaps) <= cut ** 2)
            if len(x):
                groups.append(np.column_stack((i[x], j[y])))
    return np.concatenate(groups) if groups else np.empty((0, 2), dtype=int)


def measure(left, right, travel):
    candidates = nearby_pairs(left, right, travel)
    sample = bound = REPORT_LIMIT
    if len(candidates):
        if left.bvh.overlap(right.bvh):
            return 0., 0., True
        for start in range(0, len(candidates), BATCH_SIZE):
            i, j = candidates[start:start + BATCH_SIZE].T
            d = triangle_distances(left.tri[i], right.tri[j])
            sample = min(sample, d.min())
            # Rotation about world Y preserves the axial coordinate exactly.
            axial = box_gap(left.lo[i, 1], left.hi[i, 1], right.lo[j, 1], right.hi[j, 1])
            lower = np.maximum(axial, d - travel * right.radii[j]) - NUMERIC_MARGIN
            bound = min(bound, lower.min())
    return float(sample), float(bound), False


def inspect_scene(max_step):
    scene = bpy.context.scene
    objects = bpy.data.objects
    control = objects["Controls"]
    pivot_obj = objects["ThumbPivot"]
    fixed_objects = [o for o in scene.objects if o.type == "MESH" and o.name.startswith("fixed_")]
    moving_objects = [o for o in scene.objects if o.type == "MESH" and o.name.startswith("thumb_")]
    assert fixed_objects and moving_objects, "No meshes found for one or both rigid groups"
    # The saved viewport hides the clearance gauges. Bring them into this
    # disposable evaluation context so their driven parent transforms update.
    for obj in fixed_objects + moving_objects:
        obj.hide_viewport = False
        obj.hide_set(False)
    bpy.context.view_layer.update()
    ui = control.id_properties_ui("thumb_fold_deg").as_dict()
    assert ui["min"] == 0 and ui["max"] == 60, ui
    count = math.ceil(60 / max_step)
    step = 60 / count
    # Each sample covers its nearest half-step on either side. A point at
    # radius r moves by at most 2r sin(step/4) over that angular separation.
    travel = 2 * math.sin(math.radians(step / 4))
    results = {}
    collisions = []
    initial = {}
    for index in range(count + 1):
        angle = step * index
        control["thumb_fold_deg"] = angle
        control.update_tag()
        bpy.context.view_layer.update()
        graph = bpy.context.evaluated_depsgraph_get()
        pivot = np.array(pivot_obj.evaluated_get(graph).matrix_world.translation)
        if index == 0:
            origin = pivot
            fixed = [Surface(o, graph, pivot) for o in fixed_objects]
        else:
            assert np.allclose(pivot, origin, atol=0.0001, rtol=0), "Pivot position drifted"
        rad = math.radians(angle)
        cos, sin = math.cos(rad), math.sin(rad)
        rotation = np.array(((cos, 0, sin), (0, 1, 0), (-sin, 0, cos)))
        moving = [Surface(o, graph, origin) for o in moving_objects]
        for part in moving:
            if index == 0:
                initial[part.name] = part.vertices
            expected = (initial[part.name] - origin) @ rotation.T + origin
            assert np.allclose(part.vertices, expected, atol=0.0001, rtol=0), f"Wrong motion: {part.name} at {angle} deg"
        for obj, left in zip(fixed_objects, fixed):
            assert np.allclose(np.array(obj.evaluated_get(graph).matrix_world), left.matrix, rtol=0, atol=1e-5)
            for right in moving:
                sample, bound, intersects = measure(left, right, travel)
                if index == 0 and not intersects and not np.any(box_gap(
                        left.root.lo, left.root.hi, right.root.lo, right.root.hi)):
                    intersects = any(left.contains(p) for p in right.component_points) or any(
                        right.contains(p) for p in left.component_points)
                    if intersects:
                        sample = bound = 0.
                if intersects or sample <= NUMERIC_MARGIN:
                    collisions.append({"fixed": left.name, "moving": right.name, "angle_deg": angle})
                key = (left.name, right.name)
                row = results.setdefault(key, {"fixed": left.name, "moving": right.name,
                    "sample_gap_mm": sample, "at_deg": angle, "continuous_lower_bound_mm": bound})
                if sample < row["sample_gap_mm"]:
                    row.update(sample_gap_mm=sample, at_deg=angle)
                row["continuous_lower_bound_mm"] = min(row["continuous_lower_bound_mm"], bound)
        if index % 10 == 0:
            print(f"Measured {angle:.2f} degrees", flush=True)
    ordered = sorted(results.values(), key=lambda r: r["continuous_lower_bound_mm"])
    worst = ordered[0]["continuous_lower_bound_mm"]
    return {
        "file": Path(bpy.data.filepath).name, "sha256": hashlib.sha256(Path(bpy.data.filepath).read_bytes()).hexdigest(),
        "blender": bpy.app.version_string,
        "range_deg": [0, 60], "samples": count + 1, "step_deg": step,
        "report_limit_mm": REPORT_LIMIT, "numeric_margin_mm": NUMERIC_MARGIN,
        "note": "Values at the report limit mean at least that distance. The continuous bound subtracts each moving triangle's maximum chord travel to its nearest sample, uses the invariant axial separation when larger, and allows for rounding. One half, rigid linear rotation about world Y; same-group pairs excluded.",
        "minimum_sampled_gap_mm": min(r["sample_gap_mm"] for r in ordered),
        "minimum_continuous_lower_bound_mm": worst,
        "collisions": collisions, "pairs": ordered, "pass": not collisions and worst > 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-step", type=float, default=2.0)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    if not 0 < args.max_step <= 60:
        parser.error("--max-step must be in (0, 60]")
    report = inspect_scene(args.max_step)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"{report['file']}: sampled minimum {report['minimum_sampled_gap_mm']:.4f} mm, "
          f"continuous lower bound {report['minimum_continuous_lower_bound_mm']:.4f} mm")
    if not report["pass"]:
        raise RuntimeError("Collision detected or sweep bound inconclusive; inspect report")


if __name__ == "__main__":
    main()
