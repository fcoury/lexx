"""Build the Choc V2 case in Blender, using the indexed expanded case as its datum."""
import importlib.util
import json
from pathlib import Path
import sys

import bmesh
import bpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT), str(ROOT/"pcb"/"case")]
from build import boolean, box, circle, cylinder, export, ringbox, rings, rotated, square, unite_objects
from choc_boards import update_electronics
from hinge import _circle, _prism

PCB_TOP = 13.
PLATE_TOP = PCB_TOP + 2.2
PLATE_THICKNESS = 1.2
RIM = PLATE_TOP - PLATE_THICKNESS
APERTURE = 14.1
MASTER = HERE/"Expanded-Choc-V2.blend"


def grow_finger_case(scene, design):
    source = ROOT/"pcb"/"case"/"build_case.py"
    spec = importlib.util.spec_from_file_location("indexed_case",source)
    indexed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(indexed)
    indexed.HERE = HERE
    center_x,rear_y = indexed.load_fixed_case(scene,design)
    shell = scene.objects["fixed_shell"]
    boolean(shell,[indexed.flex_slot(shell,center_x,rear_y)],"DIFFERENCE")
    supports = json.loads((HERE/"supports.json").read_text())["fixed"]
    tools = [rings("Support",[(circle(x,y,r+.35),2.1),(circle(x,y,r+.35),2.7),
                              (circle(x,y,r),3.1),(circle(x,y,r),11.2)]) for x,y,r in supports]
    boolean(shell,tools,"UNION")
    # SW1's long stamped terminal approaches the front fixed knuckle on the
    # left hand. Lower only the web crown under that terminal; keep the bore.
    cut_bounds(shell,-11.05,-14.15,-8.03,-11.85,9.12,11.3)
    # The wider Choc perimeter approaches the index cap's rear tool corridor.
    # Mill a round relief that starts beyond the locking ear's bearing face.
    for x in (-3.5,3.5):
        tool = _prism("Driver access",_circle(x,12.0621778,3.10),23.005,90)
        boolean(shell,[tool],"DIFFERENCE")


def cut_bounds(obj, x0, y0, x1, y1, z0, z1):
    boolean(obj, [box((x0+x1)/2, (y0+y1)/2, (x1-x0)/2, (y1-y0)/2,z0,z1)], "DIFFERENCE")


def trim_shell(obj):
    # The two interleaved indexing ears rise above the new switch field.
    # Retain the entire original crown over the rear lock, including its web.
    for x0,y0,x1,y1 in ((-180,-120,-7.05,100),(7.05,-120,100,100),
                         (-7.06,-120,7.06,11.9),(-7.06,23.3,7.06,100)):
        cut_bounds(obj,x0,y0,x1,y1,RIM,30)


def lower_plate(obj, keys):
    # Keep post bottoms and pilots at the original floor seats. Compress the
    # short bevel and move the blind pilot ceiling with the plate underneath.
    for v in obj.data.vertices:
        h = v.co.z
        if h > 16.49:
            v.co.z = RIM + (h-16.5) * (PLATE_THICKNESS/1.5)
        elif h > 15:
            v.co.z = RIM - (16.5-h)
    obj.data.update()
    boolean(obj,[ringbox(x,y,yaw,APERTURE/2,RIM-.2,PLATE_TOP+.2)
                 for x,y,yaw in keys],"DIFFERENCE")
    # A service opening exposes the full pin, lock and iron approach. Its short
    # ends are well away from the switch cutouts and thumb module screw posts.
    cut_bounds(obj,-8.8,11.7,8.8,23.55,RIM-.2,PLATE_TOP+.2)
    cut_bounds(obj,-6.7,23.50,6.7,80,RIM-.2,PLATE_TOP+.2)


def update_switch_bodies(scene, role, keys):
    pieces = []
    for x,y,yaw in keys:
        sections = [(6.975,PCB_TOP),(6.975,PLATE_TOP),(7.5,PLATE_TOP),
                    (7.5,PLATE_TOP+.8),(6.6,PLATE_TOP+.8),(6.05,PLATE_TOP+3.3)]
        pieces.append(rings("PG1353 housing",[(rotated(square(0,0,r),x,y,yaw),z)
                                             for r,z in sections]))
        pieces.append(cylinder(x,y,3.25,PLATE_TOP+3.3,PLATE_TOP+6.4))
    new = unite_objects(pieces)
    old = scene.objects[role+"_switches"]
    mat = old.data.materials[0]
    old.data = new.data
    old.data.materials.append(mat)
    bpy.data.objects.remove(new,do_unlink=True)


def update_keys(scene, role):
    for kind in ("caps","caps_added","envelopes"):
        obj = scene.objects.get(role+"_"+kind)
        if not obj:
            continue
        for vertex in obj.data.vertices:
            h = vertex.co.z
            if kind.startswith("caps"):
                vertex.co.z = 19.2+(h-23.5)*.73
            else:
                vertex.co.z = 9.4 if h<20 else 26.
        obj.data.update()


def weld(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=.000075)
    bm.to_mesh(obj.data)
    bm.free()


def main():
    bpy.ops.wm.open_mainfile(filepath=str(ROOT/"pcb"/"case"/"Expanded-PCB.blend"))
    scene = bpy.context.scene
    controls = scene.objects["Controls"]
    controls["thumb_fold_deg"] = 0.
    controls.update_tag()
    bpy.context.view_layer.update()
    design = json.loads((ROOT/"validation"/"design.json").read_text())["Expanded"]
    grow_finger_case(scene,design["fixed"])
    for role in ("fixed","thumb"):
        shell,plate = (scene.objects[role+"_"+what] for what in ("shell","plate"))
        if role=="thumb":
            # Remove the inherited land down to the floor surface before planting
            # its replacement clear of the through-board SW27 retaining leg.
            boolean(shell,[cylinder(-37,-59,2.66,2.4,11.5)],"DIFFERENCE")
            x,y,r = json.loads((HERE/"supports.json").read_text())["thumb"][0]
            land = rings("Thumb support",[(circle(x,y,r+.35),2.1),(circle(x,y,r+.35),2.7),
                                          (circle(x,y,r),3.1),(circle(x,y,r),11.2)])
            boolean(shell,[land],"UNION")
        trim_shell(shell)
        lower_plate(plate, design[role]["keys"])
        for obj in (shell,plate):
            weld(obj)
            for hand in ("left","right"):
                out = HERE/"print"/hand
                out.mkdir(parents=True,exist_ok=True)
                export(obj,out/(obj.name+".stl"),hand=="right")
        update_switch_bodies(scene,role,design[role]["keys"])
        update_keys(scene,role)

    coupon = box(0,0,11.,11.,0,PLATE_THICKNESS)
    boolean(coupon,[ringbox(0,0,0,APERTURE/2,-1,2)],"DIFFERENCE")
    export(coupon,HERE/"choc-fit-coupon.stl",False)
    bpy.data.objects.remove(coupon,do_unlink=True)
    prep = "--case-only" in sys.argv
    if not prep:
        update_electronics()
    bpy.ops.object.select_all(action='DESELECT')
    controls.select_set(True)
    bpy.context.view_layer.objects.active = controls
    for doc in list(bpy.data.texts):
        bpy.data.texts.remove(doc)
    doc = bpy.data.texts.new("START HERE")
    doc.write("Expanded Choc V2 • 58 PG1353 switches and CPG135001S30 sockets\n\n"
              "Select Controls and adjust thumb_fold_deg from 0 to 60 degrees. "
              "Remove the M3 index screw before folding a physical assembly.\n"
              "Edit left hand opens the mechanical assembly. Split keyboard shows both hands. "
              "PCB workbench shows each board and its assigned components.\n"
              "Switch plate top 15.20 mm, PCB top 13.00 mm, center spacing 19.05 mm. "
              "Shown low-profile caps are fit proxies. See case/README.md for tested limits.\n")
    for path in (Path(__file__),HERE/"choc_boards.py"):
        bpy.data.texts.load(str(path.resolve()),internal=True)
    bpy.context.preferences.filepaths.save_version = 0
    out = Path("/tmp/lexx-choc-case-only.blend") if prep else MASTER
    bpy.ops.wm.save_as_mainfile(filepath=str(out),compress=True)


if __name__=="__main__":
    main()
