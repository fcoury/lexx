"""Import four KiCad laminates and their underside assembly envelopes into Blender."""

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

import bpy
from mathutils import Matrix, Vector
from mathutils.geometry import delaunay_2d_cdt

from build import material, mesh, rings

PCB = Path(__file__).resolve().parents[1]
NUMBER = r"[-+.\d]+"


def circle(x, y, radius, steps):
    return [(x+radius*math.cos(i*math.tau/steps), y+radius*math.sin(i*math.tau/steps))
            for i in range(steps)]


def xy(block, tag):
    match = re.search(r"\("+tag+r" ("+NUMBER+") ("+NUMBER+r")[ )]",block)
    return float(match[1]),float(match[2])


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
            diameter = float(re.search(r"\(drill ("+NUMBER+r")\)",pad)[1])
            holes.append(circle(x+dx*c+dy*s, y+dx*s-dy*c, diameter/2, 20))
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
    result["source"] = "pcb/"+path.stem+"/"+path.name
    result["mechanical_holes"] = len(rings)-1
    result["laminate_thickness_mm"] = 1.6
    return result


def bounding_box(label, low, high):
    x0,y0,z0 = low
    x1,y1,z1 = high
    corners = [(x0,y0),(x1,y0),(x1,y1),(x0,y1)]
    xyz = [(x,y,z) for z in (z0,z1) for x,y in corners]
    faces = [(3,2,1,0),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]
    return mesh(label,xyz,faces)


def component_meshes(part, profiles):
    kind = part["footprint"].split(":")[-1]
    if kind in profiles:
        profile = profiles[kind]
        outline = profile["xy"]
        return [(kind, rings(kind, [(outline, 11.4+profile["lowest_from_board_underside_mm"]),
                                    (outline, 11.4)]))]
    return [(label, bounding_box(label,low,high)) for label,low,high in part_boxes(part)]


def part_boxes(part):
    """Conservative component bodies, based on the footprints and assembled Z stack."""
    key = part["footprint"].split(":")[-1]
    if key=="XIAO":
        return [("module", (0,-21.04,9.65), (17.78,-.08,11.32)),
                ("USB-C", (4.39,-22.55,6.68), (13.40,-15.1,9.65))]
    if key=="PowerSwitch":
        return [("switch",(-3.35,-1.0,9.9),(3.35,1.6,11.4)),
                ("slider travel",(-1.4,1.6,9.9),(1.4,3.15,11.2))]
    bounds = {
        "SOD123": ((-2.5,-1.18,9.95),(2.5,1.18,11.4)),
        "Battery": ((-4.0,-4.5,7.65),(4.0,4.5,11.4)),
    }
    return [(key,*bounds[key])]


def add():
    profiles = json.loads((Path(__file__).parent/"component-profiles.json").read_text())
    scene = bpy.context.scene
    pair = bpy.data.scenes["Split keyboard"]
    pivot = scene.objects["ThumbPivot"]
    right_base = bpy.data.objects.new("Right PCB assembly origin",None)
    pair.collection.objects.link(right_base)
    right_base.location = pair.objects["Right hand (linked mirror)"].location
    right_pivot = bpy.data.objects.new("Right PCB thumb pivot",None)
    pair.collection.objects.link(right_pivot)
    right_pivot.parent = right_base
    right_pivot.location.z = 6
    drive = right_pivot.driver_add("rotation_euler",1).driver
    variable = drive.variables.new()
    variable.name = "angle"
    variable.targets[0].id = scene.objects["Controls"]
    variable.targets[0].data_path = '["thumb_fold_deg"]'
    drive.expression = "-angle*0.017453292519943295"
    # Cyan board, neutral housings and saturated cable connectors are readable through a hidden plate.
    colors = {"PCB":(.04,.33,.28), "MX":(.10,.11,.12),"SOD123":(.12,.13,.15),
              "FFC12":(.90,.60,.27),"Battery":(.83,.84,.82),"module":(.07,.24,.31),
              "USB-C":(.62,.66,.68),"switch":(.25,.28,.27),"slider travel":(.10,.10,.10),
              "cell":(.81,.63,.24)}
    mats = {k:material("PCB fit • "+k,v) for k,v in colors.items()}
    inspection = bpy.data.scenes.new("PCB workbench")
    inspection.unit_settings.system = "METRIC"
    inspection.unit_settings.scale_length = .001
    inspection.unit_settings.length_unit = "MILLIMETERS"
    for control_obj in (scene.objects["Controls"],pivot,right_base,right_pivot):
        inspection.collection.objects.link(control_obj)
    for hand in ("left","right"):
        for deck in ("finger","thumb"):
            board = hand+"-"+deck
            folder = PCB/board
            collection = bpy.data.collections.new(board+" • electronics")
            for host in ([scene,pair,inspection] if hand=="left" else [pair,inspection]):
                host.collection.children.link(collection)
            def register(obj, ref, color):
                obj.name = board+" • "+ref
                obj.data.materials.append(mats[color])
                obj["pcb_hand"],obj["pcb_deck"] = hand,deck
                for old in list(obj.users_collection): old.objects.unlink(obj)
                collection.objects.link(obj)
                if deck=="thumb":
                    obj.parent = pivot if hand=="left" else right_pivot
                    obj.matrix_parent_inverse = Matrix.Translation((0,0,-6))
                elif hand=="right":
                    obj.parent = right_base
                return obj
            register(laminate(folder/(board+".kicad_pcb")), "PCB", "PCB")
            for part in json.loads((folder/"circuit.json").read_text()):
                for label,mesh_object in component_meshes(part, profiles):
                    obj = register(mesh_object,part["ref"]+" "+label,label)
                    obj.location.x,obj.location.y = part["xy"]
                    obj.rotation_euler.z = math.radians(part["angle"])
                    obj["component"] = part["value"]
            if deck=="thumb":
                cx = 21 if hand=="left" else -21
                register(bounding_box("cell",(cx-9,-33,2.9),(cx+9,-9,6.9)),
                         "protected cell envelope","cell")
    bpy.context.view_layer.update()
