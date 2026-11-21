"""Build the expanded PCB case from the committed Blender master. Units are mm."""

from pathlib import Path
import json
import math
import sys

import bpy
import bmesh

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
from build import boolean, box, circle, export, mesh, rings
import electronics


def prism_along_x(x0, x1, yz):
    """Extrude a counterclockwise YZ polygon along positive X."""
    n = len(yz)
    points = [(x, y, z) for x in (x0, x1) for y, z in yz]
    faces = [tuple(reversed(range(n))), tuple(range(n, 2*n))]
    faces.extend((i, (i+1) % n, n+(i+1) % n, n+i) for i in range(n))
    return mesh("Port tool", points, faces)


def side_window(y, width, bottom, top, radius):
    yz = []
    for cy, cz, start in [(y+width/2-radius, bottom+radius, -90),
                          (y+width/2-radius, top-radius, 0),
                          (y-width/2+radius, top-radius, 90),
                          (y-width/2+radius, bottom+radius, 180)]:
        for i in range(7):
            angle = math.radians(start + 15*i)
            yz.append((cy+radius*math.cos(angle), cz+radius*math.sin(angle)))
    return prism_along_x(29, 36, yz)


def flex_slot(shell, center_x, front_y):
    """Follow the actual stepped rear wall and round the two cable-bearing edges."""
    radius = .55
    sill = 4.15
    sections = []
    for step in range(21):
        x = center_x-4+.4*step
        hit, outer, _, _ = shell.ray_cast((x, front_y+8, 13), (0, -1, 0))
        assert hit
        hit, inner, _, _ = shell.ray_cast((x, outer.y-.01, 13), (0, -1, 0))
        assert hit and 2 < outer.y-inner.y < 7
        yz = [(inner.y-2, sill-radius)]
        for cy, first, last in [(inner.y+radius, 180, 90), (outer.y-radius, 90, 0)]:
            for i in range(6):
                angle = math.radians(first + (last-first)*i/5)
                yz.append((cy+radius*math.cos(angle), sill-radius+radius*math.sin(angle)))
        yz.extend([(outer.y+2, sill-radius), (outer.y+2, 18), (inner.y-2, 18)])
        sections.append([(x,y,z) for y,z in yz])
    n = len(sections[0])
    vertices = [pt for section in sections for pt in section]
    faces = [tuple(reversed(range(n))), tuple(range(len(vertices)-n,len(vertices)))]
    for j in range(len(sections)-1):
        for i in range(n):
            a, b = j*n+i, j*n+(i+1)%n
            faces.append((a,b,b+n,a+n))
    return mesh("Cable slot tool", vertices, faces)


def main():
    bpy.ops.wm.open_mainfile(filepath=str(ROOT/"models"/"Expanded.blend"))
    scene = bpy.context.scene
    controls = scene.objects["Controls"]
    controls["thumb_fold_deg"] = 0.0
    controls.update_tag()
    bpy.context.view_layer.update()
    original = json.loads((ROOT/"validation"/"design.json").read_text())["Expanded"]
    for name in ("fixed", "thumb"):
        shell = scene.objects[name+"_shell"]
        center_x = -27 if name == "fixed" else 22.35
        cutters = [flex_slot(shell, center_x, original[name]["loop_port"][1])]
        if name == "thumb":
            # The module PCB shoulders reach x=32.05 on both sides of its USB socket.
            # Recess the interior wall while retaining 1.20 mm of exterior skin.
            cutters.append(box(30.125,.5,2.325,9.30,9.0,11.8))
            boolean(shell, cutters, "DIFFERENCE")
            cutters = [side_window(.5, 12, 5, 11.8, .8),
                       side_window(-14, 9, 8, 11.8, .55)]
        boolean(shell, cutters, "DIFFERENCE")
        # The three floorside lands catch board deflection under switch insertion.
        # A 0.20 mm nominal gap accommodates variation in the switch seating height.
        supports = json.loads((HERE/"supports.json").read_text())[name]
        lands = [rings("Board support", [(circle(x,y,r+.35),2.1),
                                         (circle(x,y,r+.35),2.7),
                                         (circle(x,y,r),3.1),
                                         (circle(x,y,r),11.2)]) for x,y,r in supports]
        boolean(shell, lands, "UNION")
        # Intersecting the staggered rear wall can split a vertex by a few microns.
        # Weld it before triangulation so both sides export the same STL edge.
        bm = bmesh.new()
        bm.from_mesh(shell.data)
        bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=.0001)
        bm.to_mesh(shell.data)
        bm.free()
        for hand in ("left", "right"):
            output = HERE/"print"/hand
            output.mkdir(parents=True, exist_ok=True)
            export(shell, output/(shell.name+".stl"), hand == "right")
    electronics.add()
    bpy.ops.object.select_all(action='DESELECT')
    controls.select_set(True)
    bpy.context.view_layer.objects.active = controls
    bpy.context.preferences.filepaths.save_version = 0
    bpy.data.texts["START HERE"].write("\nExpanded PCB revision. USB and power access are on "
                                     "the outer thumb wall; feed the flex through the two rear slots.\n")
    bpy.data.texts.load(str(Path(__file__).resolve()), internal=True)
    bpy.data.texts.load(str(HERE/"electronics.py"), internal=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(HERE/"Expanded-PCB.blend"))


if __name__ == "__main__":
    main()
