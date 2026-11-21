"""Build both hand-wired MX case sizes in Blender. Dimensions in millimeters."""
from pathlib import Path
import json
import math
import sys
import struct
import bpy
import bmesh
from mathutils import Vector, Matrix

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from hinge import build_hinge

PITCH = 19.05
MX_CUT = 14.0
PLATE_Z = 16.5
PLATE_T = 1.5
FLOOR = 2.4
WALL = 2.4


def mesh(name, verts, faces):
    data = bpy.data.meshes.new(name)
    data.from_pydata(verts, [], faces)
    data.update()
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def hull(points):
    def side(seq):
        chain = []
        for p in seq:
            while len(chain) >= 2:
                a, b = chain[-2:]
                if (b-a).cross(p-a) > .0001:
                    break
                chain.pop()
            chain.append(p)
        return chain[:-1]
    pts = [Vector(p) for p in sorted(set(points))]
    return side(pts) + side(reversed(pts))


def round_outline(points, trim=3.2):
    out = []
    for i,b in enumerate(points):
        v, w = points[i-1]-b, points[(i+1)%len(points)]-b
        d = min(trim, v.length*.4, w.length*.4)
        a, c = b+v.normalized()*d, b+w.normalized()*d
        for j in range(7):
            t = j/6
            out.append((1-t)**2*a + 2*(1-t)*t*b + t*t*c)
    return out


def inset(poly, d):
    pts = []
    for i,p in enumerate(poly):
        a = (p-poly[i-1]).normalized()
        b = (poly[(i+1)%len(poly)]-p).normalized()
        n = Vector((-(a.y+b.y), a.x+b.x))
        pts.append(p + n*(d/(1+a.dot(b))))
    return pts


def rings(name, sections):
    n = len(sections[0][0])
    vertices = [(p[0],p[1],z) for poly,z in sections for p in poly]
    faces = [tuple(reversed(range(n)))]
    for row in range(len(sections)-1):
        for i in range(n):
            j=(i+1)%n
            a=row*n
            faces.append((a+i,a+j,a+n+j,a+n+i))
    offset=(len(sections)-1)*n
    faces.append(tuple(range(offset,offset+n)))
    return mesh(name,vertices,faces)


def square(x,y,r):
    return [(x-r,y-r),(x+r,y-r),(x+r,y+r),(x-r,y+r)]


def cylinder(x,y,r,z1,z2):
    p=[(x+r*math.cos(i*math.tau/40),y+r*math.sin(i*math.tau/40)) for i in range(40)]
    return rings('tool', [(p,z1),(p,z2)])


def unite_objects(objs):
    bpy.ops.object.select_all(action='DESELECT')
    for obj in objs:
        obj.select_set(True)
    bpy.context.view_layer.objects.active=objs[0]
    if len(objs)>1:
        bpy.ops.object.join()
    return objs[0]


def boolean(target, cutters, operation):
    tool=unite_objects(cutters)
    mod=target.modifiers.new(operation,'BOOLEAN')
    mod.operation=operation
    mod.object=tool
    mod.solver='EXACT'
    bpy.context.view_layer.objects.active=target
    bpy.ops.object.modifier_apply(modifier=mod.name)
    bpy.data.objects.remove(tool,do_unlink=True)


def box(x,y,rx,ry,z1,z2):
    p=[(x-rx,y-ry),(x+rx,y-ry),(x+rx,y+ry),(x-rx,y+ry)]
    return rings('tool',[(p,z1),(p,z2)])


def paint(obj, mat):
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    obj.color=mat.diffuse_color


def material(name,color):
    mat=bpy.data.materials.new(name)
    mat.diffuse_color=(*color,1)
    return mat


SCALE = PITCH / 16
INDEX_X, INDEX_Y = -17.9, -15.5
DESIGN = {}


def key_xy(dx, dy):
    return INDEX_X + dx*SCALE, INDEX_Y + dy*SCALE


def layout(expanded):
    keys = []
    for col, stagger in enumerate([0,2,4,0,-10,-10][:6 if expanded else 5]):
        for row in range(-1 if col in (3,4) else 0, 4 if expanded else 3):
            x,y = key_xy(-16*col, stagger+16*row)
            keys.append((x,y,0,row==3 or col==5))
    return keys


def rotated(points,x,y,yaw):
    a=math.radians(yaw)
    c,s=math.cos(a),math.sin(a)
    return [Vector((x+c*px-s*py,y+s*px+c*py)) for px,py in points]


def ringbox(x,y,yaw,r,z1,z2):
    poly=rotated(square(0,0,r),x,y,yaw)
    return rings('tool',[(poly,z1),(poly,z2)])


def circle(x,y,r):
    return [(x+r*math.cos(i*math.tau/48),y+r*math.sin(i*math.tau/48)) for i in range(48)]


def finger_outline(keys,side):
    # Walk the stepped perimeter, keeping a straight front edge under the inner three columns.
    columns=sorted(set(k[0] for k in keys))
    bottom=[]; top=[]
    for i,x in enumerate(columns):
        ys=[k[1] for k in keys if k[0]==x]
        lo=(INDEX_Y if x>=INDEX_X-2*PITCH-.01 else min(ys))-12.5
        hi=max(ys)+12.0
        left=x-PITCH/2 if i else x-12.5
        right=x+PITCH/2 if i<len(columns)-1 else side
        bottom.extend([(left,lo),(right,lo)])
        top.extend([(left,hi),(right,hi)])
    # Suppress straight-line points before beveling corners.
    pts=[Vector(v) for v in bottom+top[::-1]]
    return [p for i,p in enumerate(pts)
            if abs((p-pts[i-1]).cross(pts[(i+1)%len(pts)]-p))>.001]


def wing_outline(side):
    # Two sampled arcs bound the key fan. The return runs up the seam behind the fan.
    leading=[(-20.7,-43.0),(-15,-42.4),(-9,-42.4),(-3,-42.9),(3,-43.9),
             (9,-45.6),(15,-47.8),(21,-50.6),(27,-54.1),(32,-57.6)]
    trailing=[(15,-23.8),(9,-22.1),(3,-20.8),(-3,-19.9),(-9,-19.3),
              (-15,-19.1),(-24.4,-19.1)]
    front=[key_xy(x,y) for x,y in leading]
    back=[key_xy(x,y) for x,y in trailing if key_xy(x,y)[0]<side-0.1]
    return [Vector(v) for v in front+[key_xy(43.3,-37.0),(key_xy(43.3,0)[0],26.8),
            (side,26.8),(side,key_xy(0,-23.6)[1])]+back]


def deck(prefix,keys):
    finger=prefix=='fixed'
    outline=(lambda side:finger_outline(keys,side)) if finger else wing_outline
    sign=-1 if finger else 1
    raw=outline(sign*8)
    # Inset the polygon before rounding: short steps remain parallel and do not reverse.
    outer=round_outline(raw,trim=2.6)
    inner=round_outline(inset(raw,WALL),trim=2.2)
    if len(outer)!=len(inner):
        raise ValueError('Outlines need the same vertex count')
    shell=rings(prefix+'_shell',[(round_outline(inset(raw,.9),2.2),0),(outer,.9),
                                  (outer,PLATE_Z),(inner,PLATE_Z),(inner,FLOOR)])
    lid_raw=outline(-1.75 if finger else 3.6)
    rim=round_outline(lid_raw,trim=2.8)
    plate=rings(prefix+'_plate',[(rim,PLATE_Z),(rim,17.5),
            (round_outline(inset(lid_raw,.5),trim=2.6),18)])
    boolean(plate,[ringbox(x,y,yaw,MX_CUT/2,16,19) for x,y,yaw,_ in keys],'DIFFERENCE')
    if finger:
        # Local underside relief over the rotating indexing ear preserves the visible seam.
        boolean(plate,[box(-1.5,14.8,2.25,3.5,16.3,17.2)],'DIFFERENCE')
        columns=sorted(set(k[0] for k in keys))
        screws=[]
        for col in (0,len(columns)-2):
            x=(columns[col]+columns[col+1])/2
            ys=[k[1] for k in keys if k[0]==columns[col]]
            screws.extend([(x,min(ys)+PITCH/2),(x,max(ys)-PITCH/2)])
        screws.append((INDEX_X-2.5*PITCH, INDEX_Y+PITCH*.55))
    else:
        screws=[key_xy(-20.2,-22.9), key_xy(15.5,-44.0), (15,21),(29,18)]
    # Blind pilots in downward posts leave the top faces clean. Screw heads seat from below.
    boolean(plate,[cylinder(x,y,2.45,FLOOR+.05,PLATE_Z+.3) for x,y in screws],'UNION')
    boolean(plate,[cylinder(x,y,1.05,1,16.3) for x,y in screws],'DIFFERENCE')
    countersinks=[rings('tool',[(circle(x,y,2.75),-.2),(circle(x,y,2.55),0),
                  (circle(x,y,1.45),1.1),(circle(x,y,1.45),3.1)]) for x,y in screws]
    boolean(shell,countersinks,'DIFFERENCE')
    loop_port=([INDEX_X,max(k[1] for k in keys if k[0]==INDEX_X)+12] if finger else [22,26.8])
    boolean(shell,[box(*loop_port,3.2,5,4.2,8.6)],'DIFFERENCE')
    rear=None
    if finger:
        x=INDEX_X-2*PITCH
        y=max(k[1] for k in keys if k[0]==x)+12.0
        boolean(shell,[box(x,y,4,5,4,9)],'DIFFERENCE')
        rear=[x,y]
    DESIGN[prefix]={'keys':[list(k[:3]) for k in keys],'screws':screws,'loop_port':loop_port,
                    'rear_port':rear}
    return shell,plate


def cap_proxy(x,y,yaw):
    # A shallow cylindrical dish with a radiused lip. All rings share the same vertex order.
    profile=[(8.85,23.5,0),(9.08,23.82,0),(8.95,24.9,0),(8.15,29.4,.5),
             (7.9,30.4,1.1),(7.55,30.65,1.15),(6.8,30.64,1.15),
             (5.2,30.64,1.15),(3.4,30.64,1.15),(1.6,30.64,1.15),(.2,30.64,1.15)]
    verts=[]; faces=[]
    for r,z,dish in profile:
        pts=round_outline([Vector(v) for v in square(0,0,r)],trim=min(r*.45,2.0))
        offset=len(verts)
        n=len(pts)
        for p,q in zip(pts,rotated(pts,x,y,yaw)):
            verts.append((q.x,q.y,z-dish*(1-(p.x/8.1)**2)))
        if not offset:
            faces.append(tuple(reversed(range(n))))
        else:
            for i in range(n):
                j=(i+1)%n
                faces.append((offset-n+i,offset-n+j,offset+j,offset+i))
    faces.append(tuple(range(len(verts)-n,len(verts))))
    obj=mesh('cap',verts,faces)
    for poly in obj.data.polygons:
        poly.use_smooth=True
    return obj


def fitted(prefix,keys,mats):
    envs=[]; caps={False:[],True:[]}; switches=[]
    for x,y,yaw,added in keys:
        envs.append(ringbox(x,y,yaw,9.1,5.25,35.0))
        cap=cap_proxy(x,y,yaw)
        caps[added].append(cap)
        switches.append(rings('switch',[(rotated(square(0,0,r),x,y,yaw),z)
                        for r,z in [(7.75,18),(7.75,19.9),(6.1,22.8),(3.1,23.65)]]))
    env=unite_objects(envs)
    env.name=prefix+'_envelopes'
    env.hide_set(True)
    env.hide_render=True
    env.display_type='WIRE'
    housing=unite_objects(switches)
    housing.name=prefix+'_switches'
    paint(housing,mats['housing'])
    result=[env,housing]
    for added,items in caps.items():
        if items:
            obj=unite_objects(items)
            obj.name=prefix+('_caps_added' if added else '_caps')
            paint(obj,mats['cap'])
            result.append(obj)
    return result


def controls():
    ctrl=bpy.data.objects.new('Controls',None)
    bpy.context.scene.collection.objects.link(ctrl)
    ctrl.empty_display_size=2
    ctrl['thumb_fold_deg']=0.0
    ctrl.id_properties_ui('thumb_fold_deg').update(min=0,max=60,soft_min=0,soft_max=60,
            description='Flat at 0 degrees; remove index bolt before moving; reinsert at 60')
    pivot=bpy.data.objects.new('ThumbPivot',None)
    bpy.context.scene.collection.objects.link(pivot)
    pivot.location=(0,0,6)
    pivot.empty_display_size=2
    driver=pivot.driver_add('rotation_euler',1).driver
    var=driver.variables.new()
    var.name='angle'
    var.targets[0].id=ctrl
    var.targets[0].data_path='["thumb_fold_deg"]'
    driver.expression='angle * 0.017453292519943295'
    return ctrl,pivot


def export(obj,dest,mirror):
    # Write millimetric STL on Z=0. Reverse triangle winding on the mirrored hand.
    bm=bmesh.new()
    bm.from_mesh(obj.data)
    bm.transform(obj.matrix_world)
    bm.normal_update()
    if any(not e.is_manifold for e in bm.edges):
        raise ValueError('Open edges in '+obj.name)
    if bm.calc_volume(signed=True)<=0:
        raise ValueError('Bad winding in '+obj.name)
    bmesh.ops.triangulate(bm,faces=list(bm.faces))
    # Omit zero-area triangulation artifacts from coplanar Boolean n-gons.
    triangles=[f for f in bm.faces if f.calc_area()>1e-9]
    if obj.name.endswith('_plate'):
        bm.transform(Matrix.Rotation(math.pi,4,'X'))
    floor=min(v.co.z for v in bm.verts)
    with dest.open('wb') as out:
        out.write(bytes(80)+struct.pack('<I',len(triangles)))
        for f in triangles:
            pts=[Vector((v.co.x*(-1 if mirror else 1),v.co.y,v.co.z-floor)) for v in f.verts]
            if mirror:
                pts.reverse()
            normal=(pts[1]-pts[0]).cross(pts[2]-pts[0]).normalized()
            out.write(struct.pack('<12fH',*normal,*pts[0],*pts[1],*pts[2],0))
    bm.free()


def build(variant):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene=bpy.context.scene
    scene.unit_settings.system='METRIC'
    scene.unit_settings.scale_length=.001
    scene.unit_settings.length_unit='MILLIMETERS'
    mats={name:material(name,color) for name,color in {
        'graphite':(.64,.61,.52),'plate':(.72,.69,.60),'cap':(.85,.82,.73),'housing':(.065,.074,.065),
        'teal':(.035,.36,.34),'added':(.78,.38,.085),'steel':(.34,.38,.40)}.items()}
    keys=layout(variant=='Expanded')
    thumbs=[(*key_xy(dx,dy),yaw,False) for dx,dy,yaw in
            [(-10.67,-32.61,0),(8.68,-34.97,-14),(26.89,-41.96,-28)]]
    main,plate=deck('fixed',keys)
    wing,wing_plate=deck('thumb',thumbs)
    axle=build_hinge(main,wing)
    for obj,color in [(main,'graphite'),(wing,'graphite'),(plate,'plate'),
                      (wing_plate,'plate'),(axle,'steel')]:
        paint(obj,mats[color])
    fitted('fixed',keys,mats)
    thumb_parts=fitted('thumb',thumbs,mats)
    ctrl,pivot=controls()
    for obj in [wing,wing_plate,*thumb_parts]:
        obj.parent=pivot
        obj.matrix_parent_inverse=Matrix.Translation((0,0,-6))
    bpy.context.view_layer.update()
    for group,objs in [('01   |   Printed case',[main,plate,wing,wing_plate]),
            ('02   |   Fold control',[ctrl,pivot]),('03   |   Purchased parts and fit gauges',
            [o for o in scene.objects if any(k in o.name for k in ('caps','envelopes','switches'))]+[axle])]:
        coll=bpy.data.collections.new(group)
        scene.collection.children.link(coll)
        for obj in objs:
            for old in list(obj.users_collection):
                old.objects.unlink(obj)
            coll.objects.link(obj)
    for obj in scene.objects:
        if 'envelopes' in obj.name:
            obj.hide_set(True)
    bpy.ops.object.select_all(action='DESELECT')
    ctrl.select_set(True)
    bpy.context.view_layer.objects.active=ctrl
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type=='VIEW_3D':
                s=area.spaces.active
                s.region_3d.view_rotation=Vector((-.25,-.83,.98)).to_track_quat('Z','Y')
                s.region_3d.view_distance=265
                s.region_3d.view_location=(-36,-8,13)
                s.region_3d.view_perspective='ORTHO'
                s.clip_end=5000
                s.overlay.show_overlays=False
                s.shading.color_type='MATERIAL'
                s.shading.show_cavity=True
            if area.type=='PROPERTIES':
                area.spaces.active.context='OBJECT'
    text=bpy.data.texts.new('START HERE')
    text.write('Select Controls > Object Properties > Custom Properties > thumb_fold_deg.\n'
               'The left hand is shown relative to its fixed finger deck. Set 0 or 60 degrees to lock.\n'
               'Set the tent on the outer edges of both shells in folded use.\n'
               'Toggle the purchased-parts collection to inspect plates. Units are millimeters.\n'
               'See the accompanying README for printing, fit and hardware.\n')
    # Linked assemblies in the second scene stay in sync with the editable left rig.
    assembly=bpy.data.collections.new('Complete left-hand assembly')
    for group in list(scene.collection.children):
        assembly.children.link(group)
        scene.collection.children.unlink(group)
    scene.collection.children.link(assembly)
    scene.name='Edit left hand'
    pair=bpy.data.scenes.new('Split keyboard')
    pair.unit_settings.system='METRIC'
    pair.unit_settings.scale_length=.001
    pair.unit_settings.length_unit='MILLIMETERS'
    pair.collection.children.link(assembly)
    other=bpy.data.objects.new('Right hand (linked mirror)',None)
    other.instance_type='COLLECTION'
    other.instance_collection=assembly
    other.scale.x=-1
    other.location.x=98
    pair.collection.objects.link(other)
    scene.collection['Usage']='Edit the left hand here. Switch Scene to Split keyboard and press Home to frame the pair.'
    # Reference envelopes remain hidden in every view layer and in the mirrored instance.
    for obj in scene.objects:
        if 'envelopes' in obj.name:
            obj.hide_viewport=True
    for source in ('build.py','hinge.py'):
        bpy.data.texts.load(str(ROOT/source),internal=True)
    (ROOT/'models').mkdir(exist_ok=True)
    bpy.context.preferences.filepaths.save_version=0
    bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'models'/(variant+'.blend')))
    (ROOT/'validation').mkdir(exist_ok=True)
    spec_path=ROOT/'validation'/'design.json'
    specs=json.loads(spec_path.read_text()) if spec_path.exists() else {}
    specs[variant]=DESIGN
    spec_path.write_text(json.dumps(specs,indent=2)+'\n')
    for hand in ['left','right']:
        path=ROOT/'print'/variant.lower()/hand
        path.mkdir(parents=True,exist_ok=True)
        for obj in [main,plate,wing,wing_plate]:
            export(obj,path/(obj.name+'.stl'),hand=='right')


if __name__=='__main__':
    for variant in ('Standard','Expanded'):
        build(variant)
