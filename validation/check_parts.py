"""Inspect the actual exported millimetric STLs. Run: python3 validation/check_parts.py

Requires NumPy. STL float coordinates are lifted to an exact integer grid for
triangle contact tests. Only a shared topological vertex or edge may touch.
"""
import collections
import hashlib
import json
import math
from pathlib import Path
import struct

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
STL_FACE = np.dtype([("normal", "<f4", 3), ("tri", "<f4", (3, 3)), ("attribute", "<u2")])


def sub(a, b):
    return tuple(x-y for x,y in zip(a,b))


def cross(a,b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def dot(a,b):
    return sum(x*y for x,y in zip(a,b))


def orient(a,b,c):
    return (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])


def inside(p, tri):
    s = [orient(tri[i-1],tri[i],p) for i in range(3)]
    return min(s) >= 0 or max(s) <= 0


def coplanar_overlap(a,b,shared):
    # Check inclusive containment of every nonshared corner and proper edge
    # crossings. Together these cover partial collinear overlaps as well.
    if any(inside(p,b) for p in a if p not in shared) or any(inside(p,a) for p in b if p not in shared):
        return True
    for i in range(3):
        p,q = a[i-1],a[i]
        for j in range(3):
            r,s = b[j-1],b[j]
            if orient(p,q,r)*orient(p,q,s)<0 and orient(r,s,p)*orient(r,s,q)<0:
                return True
    return False


def cut_interval(tri, distances, axis):
    # In plane-intersection cases one interval endpoint may be rational.
    points = [(p[axis],1) for p,d in zip(tri,distances) if d == 0]
    for i,x in enumerate(distances):
        y = distances[i-1]
        if x*y < 0:
            n = y*tri[i][axis]-x*tri[i-1][axis]
            d = y-x
            points.append((n,d) if d>0 else (-n,-d))
    if len(points)==1:
        return points[0],points[0]
    a,b = points
    return (a,b) if cmp(a,b)<=0 else (b,a)


def cmp(a,b):
    return a[0]*b[1]-b[0]*a[1]


def invalid_contact(a,b,na,nb,shared):
    da = [dot(sub(p,b[0]),nb) for p in a]
    if min(da)>0 or max(da)<0:
        return False
    if max(da)==min(da)==0:
        drop = max(range(3),key=lambda i: abs(na[i]))
        def uv(p):
            return (p[(drop+1)%3],p[(drop+2)%3])
        return coplanar_overlap(tuple(map(uv,a)),tuple(map(uv,b)),set(map(uv,shared)))
    # Two noncoplanar triangles sharing their common edge meet only there.
    if len(shared)==2:
        return False
    db = [dot(sub(p,a[0]),na) for p in b]
    if min(db)>0 or max(db)<0:
        return False
    line = cross(na,nb)
    axis = max(range(3),key=lambda i: abs(line[i]))
    l,r = cut_interval(a,da,axis)
    m,n = cut_interval(b,db,axis)
    lo = l if cmp(l,m)>0 else m
    hi = r if cmp(r,n)<0 else n
    length = cmp(hi,lo)
    return length>0 or (length==0 and not shared)


def self_intersections(vertices,faces):
    denominators = [float(x).as_integer_ratio()[1] for x in vertices.flat]
    scale = max(denominators)
    grid = [tuple(int(float(x)*scale) for x in v) for v in vertices]
    tri = [tuple(grid[i] for i in f) for f in faces]
    normals = [cross(sub(b,a),sub(c,a)) for a,b,c in tri]
    bounds_lo, bounds_hi = vertices[faces].min(axis=1),vertices[faces].max(axis=1)
    samples = []
    total = 0
    for i,a in enumerate(tri):
        j = i+1
        mask = np.all((bounds_lo[j:]<=bounds_hi[i]) & (bounds_hi[j:]>=bounds_lo[i]),axis=1)
        for k in np.flatnonzero(mask)+j:
            b = tri[k]
            shared = set(a).intersection(b)
            if invalid_contact(a,b,normals[i],normals[k],shared):
                total += 1
                if len(samples)<3:
                    samples.append({"facets":[i,int(k)],"a":vertices[faces[i]].tolist(),"b":vertices[faces[k]].tolist()})
    return total,samples


def trace(tris, start, direction):
    # Möller–Trumbore intersections. Rounding only coalesces the same hit
    # seen by two adjacent triangles, e.g. a ray on a triangulation diagonal.
    d = np.asarray(direction)
    e1 = tris[:,1]-tris[:,0]
    e2 = tris[:,2]-tris[:,0]
    h = np.cross(d,e2)
    det = (h*e1).sum(axis=1)
    inv = np.divide(1.,det,out=np.zeros_like(det),where=abs(det)>1e-12)
    offset = np.asarray(start)-tris[:,0]
    u = (offset*h).sum(axis=1)*inv
    q = np.cross(offset,e1)
    v = (q*d).sum(axis=1)*inv
    t = (q*e2).sum(axis=1)*inv
    ok=(abs(det)>1e-12)&(u>=-1e-9)&(v>=-1e-9)&(u+v<=1+1e-9)&(t>1e-7)
    return np.unique(np.round(t[ok],5))


def obstructs_body(tris, center, yaw):
    """Separating-axis test for an oriented 13.98 mm switch-body gauge below the plate."""
    c, s = math.cos(yaw), math.sin(yaw)
    rotation = np.array(((c, -s, 0.), (s, c, 0.), (0., 0., 1.)))
    low, high = 5.25, 16.49
    tri = (tris - [*center, (low + high)/2]) @ rotation
    half = np.array([6.99, 6.99, (high - low)/2])
    tri = tri[np.all((tri.max(axis=1)>=-half) & (tri.min(axis=1)<=half),axis=1)]
    if not len(tri):
        return False
    edges = np.roll(tri,-1,axis=1) - tri
    axes = [np.cross(edges[:,0],edges[:,1])]
    axes.extend(np.cross(edges[:,i],d) for i in range(3) for d in np.eye(3))
    intersects = np.ones(len(tri),dtype=bool)
    for axis in axes:
        p = np.einsum("nij,nj->ni",tri,axis)
        r = np.abs(axis) @ half
        intersects &= (p.min(axis=1)<=r) & (p.max(axis=1)>=-r)
    return bool(intersects.any())


def check_features(tris,path):
    finger = "fixed_" in path.name
    plate = "_plate" in path.name
    data = json.loads((ROOT/"validation"/"design.json").read_text())
    spec = data[path.parents[1].name.capitalize()]["fixed" if finger else "thumb"]
    centers = spec["keys"]
    screws = spec["screws"]
    # Return the printed orientation to left-hand assembly coordinates.
    tris = tris.copy()
    if path.parent.name == "right":
        tris[:,:,0] *= -1
    if plate:
        tris[:,:,1] *= -1
        tris[:,:,2] = 18.0 - tris[:,:,2]
    issues = []
    def first(start,direction):
        hits=trace(tris,start,direction)
        return hits[0] if len(hits) else math.inf
    def near(actual,want,kind,where,tol=.005):
        if abs(actual-want)>tol:
            issues.append(f"{kind} at {where}: got {actual}, expected {want}")
    for x,y,degrees in centers:
        if obstructs_body(tris, (x,y), math.radians(degrees)):
            issues.append(f"Switch-body gauge hits solid below the plate at {x},{y}")
    if plate:
        for x,y,degrees in centers:
            angle = math.radians(degrees)
            u = np.array([math.cos(angle),math.sin(angle),0.])
            v = np.array([-math.sin(angle),math.cos(angle),0.])
            for z in (16.55,17.25,17.95):
                for direction in (u,-u,v,-v):
                    near(first((x,y,z),direction),7.0,"MX half-width",(x,y,z))
            for dx,dy in ((0,0),(6.95,6.95),(-6.95,6.95),(6.95,-6.95),(-6.95,-6.95)):
                start = np.array([x,y,16.0]) + dx*u + dy*v
                if first(start,(0,0,1)) < 2.1:
                    issues.append(f"Obstructed MX aperture at {start.tolist()}")
    for x,y in screws:
        for z in ((4.0,15.5) if plate else (2.3,)):
            for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
                near(first((x,y,z),(dx,dy,0)),1.05 if plate else 1.45,"Screw bore radius",(x,y,z))
        if plate:
            near(first((x,y,1.0),(0,0,1)),15.3,"Blind post roof at z=16.3",(x,y))
        else:
            if first((x,y,-1.0),(0,0,1))<18:
                issues.append(f"Shell screw hole obstructed at {x},{y}")
            # A countersink widens toward the bed-facing side.
            if first((x,y,.1),(1,0,0)) <= 1.5:
                issues.append(f"Missing countersink at {x},{y}")
    if not plate:
        px,py = spec["loop_port"]
        for dx in (-2.9,0,2.9):
            for z in (4.4,6.4,8.4):
                if first((px+dx,py+4,z),(0,-1,0)) < 10:
                    issues.append(f"Fold cable port obstructed at x={px+dx}, z={z}")
        if first((px,py+4,9.6),(0,-1,0)) >= 10:
            issues.append("Missing adjacent fold cable port wall")
        if finger:
            x,y = spec["rear_port"]
            for dx in (-3.8,0,3.8):
                for z in (4.2,6.5,8.8):
                    if first((x+dx,y+6,z),(0,-1,0))<12:
                        issues.append(f"Rear cable port obstructed at x={x+dx}, z={z}")
            if first((x,y+6,10),(0,-1,0))>=12:
                issues.append("Missing adjacent rear cable port wall")
    return {"switch_body_gauges_checked":len(centers), "mx_openings_probed": len(centers) if plate else 0, "screw_positions_probed":len(screws),
            "cable_ports_probed":0 if plate else 1+int(finger), "issues":issues}


def inspect(path):
    raw = path.read_bytes()
    count, = struct.unpack_from("<I",raw,80)
    assert len(raw)==84+count*50
    data=np.frombuffer(raw[84:],dtype=STL_FACE)
    tri=data["tri"].astype(np.float64)
    vertices,faces=np.unique(tri.reshape(-1,3),axis=0,return_inverse=True)
    faces=faces.reshape(-1,3)
    links=collections.defaultdict(list)
    vertex_faces=collections.defaultdict(set)
    for f, ids in enumerate(faces):
        for i,a in enumerate(ids):
            b=ids[(i+1)%3]
            links[tuple(sorted((a,b)))].append((f,a,b))
            vertex_faces[a].add(f)
    adj=collections.defaultdict(set)
    bad_edges=0
    for items in links.values():
        if len(items)!=2:
            bad_edges+=1
            continue
        (f,a,b),(g,c,d)=items
        bad_edges += (a,b)!=(d,c)
        adj[f].add(g)
        adj[g].add(f)
    def components(faces):
        rest=set(faces)
        n=0
        while rest:
            stack=[rest.pop()]
            n+=1
            while stack:
                found=adj[stack.pop()]&rest
                rest-=found
                stack.extend(found)
        return n
    nonmanifold_verts=sum(components(items)!=1 for items in vertex_faces.values())
    n=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0])
    norms=np.linalg.norm(n,axis=1)
    contact_count,examples=self_intersections(vertices,faces)
    metrics={"file":str(path.relative_to(ROOT)),"sha256":hashlib.sha256(raw).hexdigest(),"triangles":count,"connected_components":components(range(count)),
             "inconsistent_edges":bad_edges,"nonmanifold_vertices":nonmanifold_verts,
             "zero_area_faces":int(np.sum(norms==0)),"duplicate_faces":count-len({tuple(sorted(f)) for f in faces}),
             "outward_volume_mm3":round(float((tri[:,0]*n).sum()/6),3),
             "self_contacts":contact_count, "contact_examples":examples,**check_features(tri,path)}
    metrics["pass"] = (metrics["connected_components"]==1 and metrics["outward_volume_mm3"]>0
                       and not any(metrics[k] for k in ["inconsistent_edges","nonmanifold_vertices",
                           "zero_area_faces","duplicate_faces","self_contacts","issues"]))
    print(path.relative_to(ROOT),metrics["pass"],"contacts",contact_count,metrics["issues"][:2],flush=True)
    return metrics


if __name__=="__main__":
    from concurrent.futures import ProcessPoolExecutor
    with ProcessPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(inspect,sorted((ROOT/"print").glob("*/*/*.stl"))))
    (ROOT/"validation"/"parts.json").write_text(json.dumps(results,indent=2)+"\n")
    if not results or not all(r["pass"] for r in results):
        raise SystemExit(1)
