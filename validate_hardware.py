"""Check purchase-hardware envelopes, lock alignment and service paths in both saved models."""
import hashlib
import json
import math
from pathlib import Path

import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree


ROOT = Path(__file__).resolve().parent
# Separate intentional fastener bearing surfaces by 0.01 mm for the intersection test.
FACE_EPS = 0.01


def solid(section, y1, y2):
    n = len(section)
    vertices = [(x, y, z) for y in (y1, y2) for x, z in section]
    faces = [list(range(n)), list(reversed(range(n, 2 * n)))]
    faces.extend([j, i, i + n, j + n] for i in range(n) for j in [(i + 1) % n])
    return BVHTree.FromPolygons(vertices, faces)


def cylinder(x, z, radius, y1, y2):
    # Circumscribed solid overbounds the circular envelope.
    r = radius / math.cos(math.pi / 64)
    return solid([(x + r * math.cos(i * math.tau / 64), z + r * math.sin(i * math.tau / 64))
                  for i in range(64)], y1, y2)


def object_tree(obj, depsgraph):
    obj = obj.evaluated_get(depsgraph)
    return BVHTree.FromPolygons([obj.matrix_world @ v.co for v in obj.data.vertices],
                                [p.vertices[:] for p in obj.data.polygons])


def check(probe, name, obstacles):
    for other_name, tree in obstacles.items():
        if probe.overlap(tree):
            raise ValueError(f"{name} intersects {other_name}")


def verify(path):
    bpy.ops.wm.open_mainfile(filepath=str(path))
    objects = bpy.context.scene.objects
    controls = objects["Controls"]
    static = ["fixed_shell", "fixed_plate", "fixed_envelopes"]
    moving = ["thumb_shell", "thumb_plate", "thumb_envelopes"]
    for name in static + moving:
        objects[name].hide_viewport = False
        objects[name].hide_set(False)
    bpy.context.view_layer.update()
    pivot = Vector((0, 0, 6))
    sample_start = None
    max_pose_error = 0.0
    # Both bolts start at y=23. Shaft lengths are 50 and 10 mm under the head.
    axle = cylinder(0, 6, 1.5, -27, 23)
    axle_head = cylinder(0, 6, 2.75, 23+FACE_EPS, 26)
    axle_nut = cylinder(0, 6, 3.20, -26, -22-FACE_EPS)
    hardware = {"axle shank": axle, "axle head": axle_head, "axle locknut": axle_nut}
    for angle in range(61):
        controls["thumb_fold_deg"] = float(angle)
        controls.update_tag()
        bpy.context.view_layer.update()
        deps = bpy.context.evaluated_depsgraph_get()
        envelope = objects["thumb_envelopes"].evaluated_get(deps)
        sample = envelope.matrix_world @ envelope.data.vertices[0].co
        if sample_start is None:
            sample_start = sample.copy()
        expected = pivot + Matrix.Rotation(math.radians(angle), 3, "Y") @ (sample_start - pivot)
        pose_error = (expected - sample).length
        max_pose_error = max(max_pose_error, pose_error)
        if pose_error > 0.0001:
            raise ValueError(f"{path.name}: thumb envelope position error at {angle}°: {pose_error} mm")
        case = {n: object_tree(objects[n], deps) for n in static+moving}
        for name, tree in hardware.items():
            check(tree, name, case)
        # The Ø4 mm OD insert occupies its intended heat-set bore. Its center
        # rotates around the fixed axle from the -30° to the +30° position.
        a = math.radians(angle - 30)
        x, z = 7 * math.sin(a), 6 + 7 * math.cos(a)
        insert = cylinder(x, z, 2.0, 13.3, 17.3)
        others = dict(case, **hardware)
        others.pop("thumb_shell")
        check(insert, "seated insert", others)

        if angle == 0:
            # The bare moving shell receives the insert through the +Y face
            # before the two shells are assembled. Measure its as-modeled pilot.
            wing = case["thumb_shell"]
            hit = wing.ray_cast((x, 15, z), (1, 0, 0), 5)[3]
            if hit is None or abs(2 * hit - 3.65) > 0.002:
                raise ValueError(f"{path.name}: expected 3.65 mm pilot, measured radius {hit}")
            check(cylinder(x, z, 2.0, 17.3+FACE_EPS, 150), "insert approach", {"wing":wing})
            check(cylinder(x, z, 10.0, 17.3+FACE_EPS, 150), "straight iron access", {"wing":wing})
            # Assemble the axle flat with the case lifted. Present the nut from
            # below before the axle protrudes into its seat. Hold it as the axle turns.
            seat = [(-3.2,-70),(3.2,-70),(3.2,9.2),(-3.2,9.2)]
            check(solid(seat,-26,-22-FACE_EPS), "axle locknut access", case)
            jaw = [(-4.25,-70),(4.25,-70),(4.25,10.25),(-4.25,10.25)]
            check(solid(jaw,-25.5,-22.5), "slim axle nut holder access", case)
            check(cylinder(0,6,1.5,-27,150), "axle insertion", case)
            check(cylinder(0,6,2.75,23+FACE_EPS,150), "axle head/driver access", case)
        if angle in (0, 60):
            blocked = dict(case, **hardware)
            # The shank and the insert's female threads intentionally engage.
            check(cylinder(x,z,1.5,13,150), "locking screw insertion", blocked)
            check(cylinder(x,z,2.75,23+FACE_EPS,150), "locking screw head/driver access", blocked)
    return {"model":path.name, "sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
            "axle_sampled_poses":61, "index_assembly_angles_deg":[0,60],
            "thumb_envelope_vertex":{"index":0, "at_0_deg_mm":list(sample_start),
                                     "at_60_deg_mm":list(sample),
                                     "max_pose_error_mm":max_pose_error}}


if __name__ == "__main__":
    results = [verify(ROOT/"models"/(s+".blend")) for s in ["Standard","Expanded"]]
    report = {
        "outcome":"PASS", "units":"mm",
        "axle":"M3x50, 5.5 mm head diameter x 3 mm high, 6.4 mm locknut envelope x 4 mm high, no washers",
        "index":"M3x10, socket cap head up to 5.5 mm x 3 mm. M3 heat-set insert 4 mm OD x 4 mm long in 3.65 mm pilot; insert flush at y=17.3. Full 4 mm thread engagement.",
        "method":"Triangle BVH surface intersections on saved models. Fit insert from +Y into detached wing. Assemble axle flat with case lifted; introduce its nut from underneath before protruding the bolt. Insert both screws from +Y. Allow 0.01 mm at intentional bearing faces.",
        "limits":"Ideal rigid dimensions. Axle locknut-holder envelope tested from below at 8.5 mm wide x 3 mm thick. Local insert interference with its plastic bore and screw-thread engagement are intentional. Cable routing, tool-specific shape, print tolerances and wear excluded.",
        "variants":results}
    dest=ROOT/"validation"/"hardware.json"
    dest.parent.mkdir(exist_ok=True)
    dest.write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report))
