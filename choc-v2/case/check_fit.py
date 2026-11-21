"""Measure the eight exported parts, every plate cut and every populated PCB in assembly mm."""
from pathlib import Path
import hashlib
import json
import math
import sys

import numpy as np
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PCB = HERE.parent/"pcb"
sys.path.insert(0,str(ROOT/"pcb"/"case"))
from check_case import box_contact, stl_mesh, topology, trace
from check_boards import edge_cuts, pose, projected_surface

PLATE_TOP = 15.2
DESIGN = json.loads((ROOT/"validation"/"design.json").read_text())["Expanded"]
SOCKET = Polygon(json.loads((PCB/"socket-profile.json").read_text())["xy"])
FFC = Polygon(json.loads((ROOT/"pcb"/"case"/"component-profiles.json").read_text())["FFC12"]["xy"])
PADS = unary_union([box(x-1.3,y-1.3,x+1.3,y+1.3) for x,y in ((8.245,3.75),(-3.245,5.95))])
PEGS = unary_union([Point(0,0).buffer(2.4,quad_segs=64),
                    box(-5.75,-6.15,-4.25,-4.15)])
OTHER = {"FFC12":FFC,"SOD123":box(-2.5,-1.18,2.5,1.18),
         "XIAO":box(-.1,-22.6,17.9,0),"PowerSwitch":box(-4.4,-2.45,4.4,3.4),
         "Battery":box(-4.7,-5,4.7,5.2)}


def check_near(observed,nominal,feature):
    if abs(observed-nominal)>.008:
        raise ValueError((feature,observed,nominal))


def first(tri,p,v):
    hits = trace(tri,p,v)
    return hits[0] if len(hits) else math.inf


def checks(hand,role,plate,shell):
    sign = 1 if hand=="left" else -1
    # floor-up STL shell, face-down plate rotated about X in its export.
    plate = plate*[1,-1,-1]+[0,0,PLATE_TOP]
    name = hand+"-"+("finger" if role=="fixed" else "thumb")
    directory = PCB/name
    board = edge_cuts(directory/(name+".kicad_pcb"))
    parts = json.loads((directory/"circuit.json").read_text())
    projected = [projected_surface(model,lo,hi) for model,lo,hi in (
        (shell,11.4,13),(plate,11.4,13),(shell,9.44,11.41),(plate,9.44,11.41),
        (shell,11.37,11.41),(plate,11.37,11.41))]
    shell_edge,post_edge,shell_low,post_low,shell_copper,post_copper = projected
    gaps = {}
    def keep(test,value,item):
        if value < gaps.get(test,[math.inf])[0]:
            gaps[test] = [float(value),item]
        if value<.008:
            raise ValueError((name,test,value,item))
    keep("PCB_to_shell",board.distance(shell_edge),name)
    keep("PCB_to_posts",board.distance(post_edge),name)
    other = {p["ref"]:pose(OTHER[p["footprint"].split(":")[-1]],*p["xy"],p["angle"])
             for p in parts if not p["ref"].startswith("SW")}
    components = list(other.values())
    keys = DESIGN[role]["keys"]
    switches = [p for p in parts if p["ref"].startswith("SW")]
    assert len(switches)==len(keys)
    for p,(canonical_x,y,yaw) in zip(switches,keys):
        ref = p["ref"]
        angle = sign*yaw
        x = sign*canonical_x
        assert math.dist([x,y],p["xy"])<.001
        assert abs((p["angle"]-angle+180)%360-180)<.001
        rad = math.radians(angle)
        for i in range(4):
            a = rad+i*math.pi/2
            v = math.cos(a),math.sin(a),0
            check_near(first(plate,[x,y,14.6],v),7.05,ref+" aperture")
        # Probe the actual mounting lip on the inner edge of one web.
        v = math.cos(rad),math.sin(rad)
        thickness_ray = trace(plate,[x+v[0]*7.30,y+v[1]*7.30,19],[0,0,-1])
        check_near(19-thickness_ray[0],PLATE_TOP,ref+" plate top")
        check_near(thickness_ray[1]-thickness_ray[0],1.20,ref+" plate thickness")
        body,pads,pins = (pose(g,x,y,p["angle"]) for g in (SOCKET,PADS,PEGS))
        for label,shape,a,b in (("socket",body,shell_low,post_low),
                                 ("pads",pads,shell_copper,post_copper),
                                 ("pegs",pins,shell_low,post_low)):
            keep(label+"_to_shell",shape.distance(a),ref)
            keep(label+"_to_posts",shape.distance(b),ref)
        assert board.covers(pads) and board.covers(pins), ref
        keep("pads_to_milled_edge",pads.distance(board.boundary),ref)
        assembly = body.union(pads).union(pins)
        components.append(assembly)
        for ref2,shape in other.items():
            keep("switch_to_neighbor",assembly.distance(shape),ref+"/"+ref2)
    for i,(x,y,r) in enumerate(json.loads((HERE/"supports.json").read_text())[role]):
        x *= sign
        land = Point(x,y).buffer(r,quad_segs=80)
        assert board.contains(land)
        keep("lands_to_components_XY",land.distance(unary_union(components)),str(i+1))
        check_near(14-first(shell,[x,y,14],[0,0,-1]),11.2,"land height")
    posts = (json.loads((HERE/"finger-posts.json").read_text()) if role=="fixed"
             else DESIGN["thumb"]["screws"])
    for x,y in posts:
        x *= sign
        check_near(first(shell,[x,y,1.5],[1,0,0]),1.45,"floor seat")
        check_near(first(plate,[x,y,10],[1,0,0]),1.05,"post pilot")
        check_near(first(plate,[x+3,y,10],[-1,0,0]),.55,"post wall")
    # Normalize to left to probe both handed external ports identically.
    normal_shell,normal_plate = shell*[sign,1,1],plate*[sign,1,1]
    cx,cy = (-20,53.75) if role=="fixed" else (22.35,26.8)
    for dx in (-3.88,0,3.88):
        for z in (4.2,8.2,11.9,13.9):
            assert first(normal_shell,(cx+dx,cy+7,z),(0,-1,0))>12.
    if role=="thumb":
        for y,width,z0,z1 in ((.5,12,5,11.8),(-14,9,8,11.8)):
            for d in (-1,1):
                check_near(first(normal_shell,(33,y,(z0+z1)/2),(0,d,0)),width/2,"window width")
                check_near(first(normal_shell,(33,y,(z0+z1)/2),(0,0,d)),(z1-z0)/2,"window height")
        geometry = np.concatenate((normal_shell,normal_plate))
        for lo,hi in [([11.1,-8.39,9.65],[32.05,9.39,11.32]),
                      ([31.95,-4,6.7],[33.55,5,10.2]),([33,-4,6.75],[40,5,10.15]),
                      ([30.2,-16.4,9.5],[38,-11.6,10.85]),([12,-33,2.9],[30,-9,6.9])]:
            assert not box_contact(geometry,lo,hi), (name,lo,hi)
    return {"board":name,"switch_centers_probed":len(keys),"mounts_probed":len(posts),
            "verified_aperture_mm":14.10,"plate_thickness_mm":1.20,"plate_top_mm":PLATE_TOP,
            "measured_minima":{k:{"mm":round(v,3),"at":r} for k,(v,r) in gaps.items()}}


def main():
    paths = sorted((HERE/"print").glob("*/*.stl"))+[HERE/"choc-fit-coupon.stl"]
    assert len(paths)==9
    checksums = [{"part":str(p.relative_to(HERE)),"sha256":hashlib.sha256(p.read_bytes()).hexdigest(),
                  **topology(stl_mesh(p))} for p in paths]
    coupon = stl_mesh(paths[-1])
    check_near(first(coupon,(0,0,.60),(1,0,0)),7.05,"coupon opening")
    check_near(coupon[:,:,2].max(),1.2,"coupon thickness")
    (HERE/"shell-checks.json").write_text(json.dumps(checksums,indent=2)+"\n")
    result = []
    for hand in ("left","right"):
        base = HERE/"print"/hand
        for role in ("fixed","thumb"):
            result.append(checks(hand,role,stl_mesh(base/(role+"_plate.stl")),
                                 stl_mesh(base/(role+"_shell.stl"))))
            print(result[-1],flush=True)
    (HERE/"board-fit.json").write_text(json.dumps(result,indent=2)+"\n")


if __name__=="__main__":
    main()
