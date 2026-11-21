"""Import four KiCad laminates and their underside assembly envelopes into Blender."""

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

import bpy
from mathutils import Matrix, Vector
from mathutils.geometry import delaunay_2d_cdt

from build import cylinder, mesh, rings, unite_objects
from electronics import component_meshes

HERE = Path(__file__).resolve().parent
PCB = HERE.parent/"pcb"
ROOT = HERE.parents[1]
NUMBER = r"[-+.\d]+"


def circle(x, y, radius, steps):
    return [(x+radius*math.cos(i*math.tau/steps), y+radius*math.sin(i*math.tau/steps))
            for i in range(steps)]


def xy(block, tag):
    match = re.search(r"\("+tag+r" ("+NUMBER+") ("+NUMBER+r")[ )]",block)
    return float(match[1]),float(match[2])


def capsule(width,height):
    radius = width/2
    straight = (height-width)/2
    return [(radius*math.cos(t),cy+radius*math.sin(t))
            for cy,start in ((straight,0),(-straight,math.pi))
            for i in range(17) for t in [start+i*math.pi/16]]


def boundaries(path):
    """Read Edge.Cuts and mechanical drills from the final placed KiCad board."""
    source = path.read_text()
    segments = defaultdict(list)
    holes = []
    def assembly(p):
        return round(p[0]-150,5),round(100-p[1],5)

    for kind,block in re.findall(r"(?ms)^\t\(gr_(\w+)\s+(.*?)^\t\)",source):
        if '(layer "Edge.Cuts")' not in block:
            continue
        end = assembly(xy(block,"end"))
        if kind=="circle":
            center = assembly(xy(block,"center"))
            holes.append(circle(*center, math.dist(center,end), 48))
        elif kind=="line":
            start = assembly(xy(block,"start"))
            segments[start].append(end)
            segments[end].append(start)
        else:
            raise ValueError(f"Unsupported Edge.Cuts primitive {kind}")
    assert segments and all(len(neighbors)==2 for neighbors in segments.values())
    outer = [min(segments)]
    prev = None
    while True:
        curr = outer[-1]
        following = next(p for p in segments[curr] if p != prev)
        if following == outer[0]:
            break
        outer.append(following)
        prev = curr
    assert len(outer) == len(segments), "Multiple perimeter loops"
    for footprint in re.findall(r"(?ms)^\t\(footprint (.*?)^\t\)",source):
        at = re.search(r"(?m)^\t\t\(at ([^)]*)\)",footprint)[1].split()
        x,y = assembly(tuple(map(float,at[:2])))
        angle = math.radians(float(at[2])) if len(at)>2 else 0
        c,s = math.cos(angle),math.sin(angle)
        for pad in re.findall(r"(?ms)^\t\t\(pad [^\n]*np_thru_hole[^\n]*(.*?)^\t\t\)",footprint):
            dx,dy = xy(pad,"at")
            drill = re.search(r"\(drill ([^)]*)\)",pad)[1].split()
            center = x+dx*c+dy*s, y+dx*s-dy*c
            if drill[0]=="oval":
                width,height = map(float,drill[1:])
                assert width<height, "Expected vertical PG1353 antirotation slot"
                outline = capsule(width,height)
                # Saved KiCad pad angles are absolute even inside rotated footprints.
                fields = re.search(r"\(at ([^)]*)\)",pad)[1].split()
                a = math.radians(float(fields[2])) if len(fields)>2 else 0.
                ca,sa = math.cos(a),math.sin(a)
                holes.append([(center[0]+px*ca-py*sa,center[1]+px*sa+py*ca) for px,py in outline])
            else:
                holes.append(circle(*center,float(drill[0])/2,32))
    return [outer,*holes]


def laminate(path):
    rings = boundaries(path)
    coords = []
    loops = []
    for ring in rings:
        area2 = sum(x*y2-x2*y for (x,y),(x2,y2) in zip(ring,ring[1:]+ring[:1]))
        if area2<0:
            ring = ring[::-1]
        loops.append(tuple(range(len(coords),len(coords)+len(ring))))
        coords.extend(Vector(p) for p in ring)
    points, _, triangles, _, _, faces_from = delaunay_2d_cdt(coords,[],loops,1,.00001,True)
    top = [tuple(face) for face,orig in zip(triangles,faces_from) if orig==[0]]
    uses = Counter((a,b) for face in top for a,b in zip(face,face[1:]+face[:1]))
    n = len(points)
    vertices = [(p.x,p.y,z) for z in (11.4,13.0) for p in points]
    faces = [tri[::-1] for tri in top] + [tuple(i+n for i in tri) for tri in top]
    faces.extend((a,b,n+b,n+a) for a,b in uses if (b,a) not in uses)
    result = mesh(path.stem,vertices,faces)
    result["source"] = "choc-v2/pcb/"+path.stem+"/"+path.name
    result["mechanical_holes"] = len(rings)-1
    result["laminate_thickness_mm"] = 1.6
    return result


def swap_geometry(target, source):
    mat = target.data.materials[0]
    target.data = source.data
    target.data.materials.clear()
    target.data.materials.append(mat)
    bpy.data.objects.remove(source,do_unlink=True)


def switch_assembly(part, profile):
    outline = profile["xy"]
    socket = rings("CPG135001S30",[(outline,11.4+profile["lowest_from_board_underside_mm"]),
                                  (outline,11.4)])
    # The center guide and metal mounting leg project from the upper switch,
    # through their own drilled openings, into the open space below the PCB.
    slot = [(x-5,y-5.15) for x,y in capsule(1.5,2.)]
    peg = cylinder(0,0,2.4,9.7,13.)
    leg = rings("retaining leg",[(slot,9.8),(slot,13.)])
    return [("CPG135001S30 with locating pins",unite_objects([socket,peg,leg]))]


def update_electronics():
    profiles = json.loads((ROOT/"pcb"/"case"/"component-profiles.json").read_text())
    socket = json.loads((PCB/"socket-profile.json").read_text())
    for hand in ("left","right"):
        for deck in ("finger","thumb"):
            name = f"{hand}-{deck}"
            folder = PCB/name
            target = bpy.data.objects[name+" • PCB"]
            board = laminate(folder/(name+".kicad_pcb"))
            for attr in ("source","mechanical_holes","laminate_thickness_mm"):
                target[attr] = board[attr]
            swap_geometry(target,board)
            for part in json.loads((folder/"circuit.json").read_text()):
                prefix = name+" • "+part["ref"]+" "
                existing = [o for o in bpy.data.objects if o.name.startswith(prefix)]
                is_switch = part["ref"].startswith("SW")
                new = switch_assembly(part,socket) if is_switch else component_meshes(part,profiles)
                assert len(existing)==len(new), (prefix,len(existing),len(new))
                for label,body in new:
                    obj = existing[0] if is_switch else bpy.data.objects[prefix+label]
                    swap_geometry(obj,body)
                    obj.name = prefix+label
                    obj.location.x,obj.location.y = part["xy"]
                    obj.rotation_euler.z = math.radians(part["angle"])
                    obj["component"] = part["value"]
    bpy.context.view_layer.update()
