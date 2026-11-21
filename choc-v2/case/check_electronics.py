"""Evaluate both independent Choc V2 boards and all their driven component envelopes."""
import hashlib
import importlib.util
import json
import math
import numpy as np
from pathlib import Path
import sys
import bpy

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from validate_fold import REPORT_LIMIT

spec = importlib.util.spec_from_file_location("electronics_motion_helpers",ROOT/"pcb"/"case"/"check_motion.py")
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)
AssemblySurface = shared.AssemblySurface
PIVOT, SHAPES = shared.PIVOT, shared.SHAPES
check_pair, cylinder, mesh_arrays, stacked = shared.check_pair, shared.cylinder, shared.mesh_arrays, shared.stacked


def check(master, destination):
    scene = bpy.data.scenes["Split keyboard"]
    bpy.context.window.scene = scene
    ctrl = scene.objects["Controls"]
    ctrl["thumb_fold_deg"] = 0.
    ctrl.update_tag()
    for name in ("fixed_envelopes","thumb_envelopes"):
        scene.objects[name].hide_viewport = False
        scene.objects[name].hide_set(False)
    bpy.context.view_layer.update()
    graph = bpy.context.evaluated_depsgraph_get()
    identity = np.eye(4)
    case = {}
    for role in ("fixed","thumb"):
        case[role] = stacked(mesh_arrays(scene.objects[role+"_"+s],graph,identity) for s in SHAPES)
    axle = stacked([cylinder(0,6,1.5,-27,23),cylinder(0,6,2.75,23,26),cylinder(0,6,3.20,-26,-22)])
    insert = cylinder(-3.5,6+7*math.cos(math.radians(30)),2.,13.3,17.3)
    baseline = {}
    rig = []
    for hand in ("left","right"):
        normalization = identity.copy()
        if hand=="right":
            normalization[0,0] = -1
            normalization[0,3] = scene.objects["Right PCB assembly origin"].location.x
        for deck in ("finger","thumb"):
            objects = [o for o in scene.objects if o.get("pcb_hand")==hand and o.get("pcb_deck")==deck]
            assert objects
            for o in objects:
                rig.append((deck,o,normalization,normalization @ np.array(o.evaluated_get(graph).matrix_world)))
            for kind in ("PCB","parts"):
                selected = [o for o in objects if ("laminate_thickness_mm" in o)==(kind=="PCB")]
                assert selected
                baseline[hand,deck,kind] = stacked(mesh_arrays(o,graph,normalization) for o in selected)
    step = .5
    travel = 2*math.sin(math.radians(step/4))
    # Opposite-side geometry only. The PCB intentionally supports parts on its own side.
    pairs = [(a,b) for a in ("PCB","parts","case","hardware")
             for b in ("PCB","parts","case","hardware")
             if a in ("PCB","parts") or b in ("PCB","parts")]
    records = {}
    endpoint_gaps = {}
    worst_matrix = 0.
    static = {hand:{"case":AssemblySurface(case["fixed"]),"hardware":AssemblySurface(axle),
                    **{k:AssemblySurface(baseline[hand,"finger",k]) for k in ("PCB","parts")}}
              for hand in ("left","right")}
    for index in range(121):
        angle = index*step
        ctrl["thumb_fold_deg"] = angle
        ctrl.update_tag()
        bpy.context.view_layer.update()
        graph = bpy.context.evaluated_depsgraph_get()
        radians = math.radians(angle)
        c,s = math.cos(radians),math.sin(radians)
        rotation = np.array([(c,0,s),(0,1,0),(-s,0,c)])
        transform = identity.copy()
        transform[:3,:3] = rotation
        transform[:3,3] = PIVOT-rotation@PIVOT
        for deck,obj,normalization,flat in rig:
            actual = normalization @ np.array(obj.evaluated_get(graph).matrix_world)
            expected = flat if deck=="finger" else transform@flat
            err = np.abs(actual-expected).max()
            worst_matrix = max(worst_matrix,float(err))
            if err>0.0001:
                raise ValueError(f"{obj.name}: driver disagrees with saved pose at {angle}° by {err}")
        def moving(arrays):
            points,faces = arrays
            return AssemblySurface(((points-PIVOT) @ rotation.T + PIVOT,faces))
        common = {"case":moving(case["thumb"]), "hardware":moving(insert)}
        for hand in ("left","right"):
            fixed = static[hand]
            thumb = dict(common,**{k:moving(baseline[hand,"thumb",k]) for k in ("PCB","parts")})
            for a,b in pairs:
                key = f"{hand} finger {a} / thumb {b}"
                try:
                    gap,bound = check_pair(fixed[a],thumb[b],travel,index==0)
                except ValueError as exc:
                    raise ValueError(f"{key}, {angle} degrees: {exc}") from exc
                records[key] = min(records.get(key,REPORT_LIMIT),bound)
            if index in (0,120):
                t = math.radians(angle-30)
                x,z = 7*math.sin(t),6+7*math.cos(t)
                bolt = AssemblySurface(stacked([cylinder(x,z,1.5,13,23),cylinder(x,z,2.75,23,26)]))
                checks = [check_pair(bolt,d[k],0,True)[0] for d in (fixed,thumb) for k in ("PCB","parts")]
                endpoint_gaps[f"{hand} {angle:g} degrees"] = min(checks)
        if index%20==0:
            print(f"Checked electronics at {angle:g} degrees",flush=True)
    p = master
    report = dict(file=p.name, sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
                  samples_per_hand=121, range_deg=[0,60], step_deg=step, report_limit_mm=REPORT_LIMIT,
                  pcb_electronics_objects=len(rig),max_pose_matrix_error=worst_matrix,
                  clearance_method="Exact triangle distances within report limit; conservative triangle "
                                   "travel bound between poses, with initial containment checks. Rigid parts only.",
                  lowest_continuous_bound_mm=min(records.values()),continuous_bounds_mm=records,
                  index_screw_to_electronics_at_lock_mm=endpoint_gaps)
    destination.write_text(json.dumps(report,indent=2)+"\n")
    print("All electronic assemblies clear",report["lowest_continuous_bound_mm"],flush=True)


