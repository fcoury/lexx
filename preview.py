"""Create preview.png from the two saved model files (Python 3, Pillow, Blender).

Run python3 preview.py from any directory. Blender renders the actual evaluated
mesh at each pose. Image-only transforms rest both case edges on a level desk.
"""
from pathlib import Path
import math
import os
import shutil
import subprocess
import struct
from collections import defaultdict
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
# Finishes are illustrative. The footprint and joint come from the saved CAD.
COLORS = {"shell": "#ddd9c9", "plate": "#e4e0d2", "caps": "#f5f1e1",
          "addition": "#c8c3af", "metal": "#8a8881", "switch": "#323431"}


def render_models(folder):
    import bpy
    import numpy as np
    from mathutils import Matrix, Vector

    def finish(name, color):
        channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [v / 12.92 if v < .04045 else ((v + .055) / 1.055) ** 2.4 for v in channels]
        mat = bpy.data.materials.new("Preview " + name)
        mat.use_nodes = True
        shader = mat.node_tree.nodes.get("Principled BSDF")
        shader.inputs["Base Color"].default_value = (*linear, 1)
        shader.inputs["Metallic"].default_value = .68 if name == "metal" else .03
        shader.inputs["Roughness"].default_value = .43
        return mat

    for edition, angle, shot in [("Standard", 0, "hero"), ("Standard", 60, "pair"),
                                 ("Standard", 0, "standard"), ("Expanded", 0, "expanded"),
                                 ("Standard", 0, "parts")]:
        bpy.ops.wm.open_mainfile(filepath=str(ROOT / "models" / (edition + ".blend")))
        control = bpy.data.objects["Controls"]
        control["thumb_fold_deg"] = float(angle)
        control.update_tag()
        bpy.context.view_layer.update()
        depsgraph = bpy.context.evaluated_depsgraph_get()
        parts = []
        for source in list(bpy.context.scene.objects):
            if source.type != "MESH" or source.hide_render or not source.name.startswith(("fixed_", "thumb_")):
                continue
            if shot == "parts" and not source.name.endswith(("_shell", "_plate", "_pin")):
                continue
            evaluated = source.evaluated_get(depsgraph)
            mesh = bpy.data.meshes.new_from_object(evaluated, depsgraph=depsgraph)
            mesh.transform(evaluated.matrix_world)
            obj = bpy.data.objects.new("Preview " + source.name, mesh)
            xyz = np.array([list(v.co) for v in mesh.vertices])
            parts.append((source.name, obj, xyz))
        scene = bpy.data.scenes.new("Presentation")
        bpy.context.window.scene = scene
        mats = {key: finish(key, val) for key, val in COLORS.items()}
        fixed, thumb = (np.concatenate([p[2] for p in parts if p[0].startswith(t)])
                        for t in ("fixed_shell", "thumb_shell"))

        def min_z(points, phi):
            return np.min(points[:, 2] * math.cos(phi) + points[:, 0] * math.sin(phi))

        # The saved rig holds the main shell still. Tilt the *entire* assembly
        # for the resting display so the two outer edges touch the same plane.
        low, high = 0, math.radians(angle)
        for _ in range(40):
            mid = (low + high) / 2
            if min_z(fixed, mid) > min_z(thumb, mid):
                low = mid
            else:
                high = mid
        rot = Matrix.Rotation(-mid, 4, 'Y')
        drop = min(min_z(fixed, mid), min_z(thumb, mid))
        stand = Matrix.Translation((0, 0, -drop)) @ rot
        points = []
        for name, obj, xyz in parts:
            scene.collection.objects.link(obj)
            offset = Matrix.Translation((0, 0, 55 if shot == "parts" and name.endswith("_plate") else 0))
            obj.data.transform(Matrix.Scale(.01, 4) @ offset @ stand)
            group = ("addition" if "added" in name and shot == "expanded" else
                     "caps" if "caps" in name else "metal" if "pin" in name or "axle" in name else
                     "switch" if "switch" in name or "housing" in name else
                     "plate" if "plate" in name else "shell")
            obj.data.materials.clear()
            obj.data.materials.append(mats[group])

        # Mirror the complete result so each view uses the same right-hand
        # orientation as the comparison photograph. Both halves in the tented
        # view are literal reflections of the saved CAD.
        mirror = Matrix.Diagonal(Vector((-1, 1, 1, 1)))
        objs = [p[1] for p in parts]
        if shot == "pair":
            gap = .31
            inner = max(v.co.x for obj in objs for v in obj.data.vertices)
            translate = Matrix.Translation((-inner - gap / 2, 0, 0))
            for obj in objs:
                obj.data.transform(translate)
                other = bpy.data.objects.new(obj.name + " right", obj.data.copy())
                other.data.transform(mirror)
                other.data.flip_normals()
                scene.collection.objects.link(other)
        else:
            for obj in objs:
                obj.data.transform(mirror)
                obj.data.flip_normals()
        for obj in scene.objects:
            if obj.type == "MESH":
                points.extend([v.co.copy() for v in obj.data.vertices])

        # A transparent film allows consistent page colors across the overview.
        scene.render.engine = 'CYCLES'
        scene.cycles.device = 'CPU'
        scene.cycles.samples = 24
        scene.cycles.use_denoising = True
        scene.render.film_transparent = True
        scene.render.image_settings.color_mode = 'RGBA'
        scene.render.image_settings.file_format = 'PNG'
        scene.view_settings.view_transform = 'AgX'
        scene.view_settings.look = 'AgX - Medium High Contrast'
        scene.world = bpy.data.worlds.new("Studio")
        scene.world.use_nodes = True
        scene.world.node_tree.nodes["Background"].inputs[0].default_value = (.82, .86, .90, 1)
        scene.world.node_tree.nodes["Background"].inputs[1].default_value = .34
        for name, pos, size, power in [("Large softbox", (-2.7, -2.5, 4), 3.4, 380),
                                       ("Edge light", (2.5, 2.5, 4), 2.1, 220)]:
            lamp = bpy.data.lights.new(name, 'AREA')
            lamp.energy, lamp.shape, lamp.size = power, 'DISK', size
            obj = bpy.data.objects.new(name, lamp)
            scene.collection.objects.link(obj)
            obj.location = pos
            obj.rotation_euler = (-Vector(pos)).to_track_quat('-Z', 'Y').to_euler()

        cam_data = bpy.data.cameras.new("Study camera")
        cam = bpy.data.objects.new("Study camera", cam_data)
        scene.collection.objects.link(cam)
        scene.camera = cam
        cam_data.type = 'ORTHO'
        views = {"hero": (.69, -1.2, .94), "pair": (.015, -1.35, .64),
                 "parts": (.60, -1.15, .84)}
        direction = Vector(views.get(shot, (0, -.0001, 1))).normalized()
        rot = Matrix.Identity(3).to_quaternion() if shot in {'standard', 'expanded'} else (-direction).to_track_quat('-Z', 'Y')
        right, up = rot @ Vector((1,0,0)), rot @ Vector((0,1,0))
        us, vs = [p.dot(right) for p in points], [p.dot(up) for p in points]
        # Same mm/pixel across both flat views makes the growth measurable.
        dimensions = {"hero": (1600, 1060), "pair": (1710, 640), "parts": (1610, 1050)}
        w, h = dimensions.get(shot, (1090, 855))
        width = max((max(us) - min(us)) * 1.05, (max(vs) - min(vs)) * w / h * 1.05)
        if shot in {"standard", "expanded"}:
            if width > 2.25:
                raise ValueError("The flat layout no longer fits the shared comparison scale")
            width = 2.25
        center = right * ((min(us)+max(us))/2) + up * ((min(vs)+max(vs))/2)
        cam.location = center + direction * 7
        cam.rotation_euler = rot.to_euler()
        cam_data.ortho_scale = width
        scene.render.resolution_x, scene.render.resolution_y = w, h
        scene.render.resolution_percentage = 100
        scene.render.filepath = str(folder / (shot + ".png"))
        bpy.ops.render.render(write_still=True, scene=scene.name)


def flat_plate_sections(path):
    """Read the outlines and apertures directly from the printable STL at mid-height."""
    data = path.read_bytes()
    adj = defaultdict(set)
    # The plates are separately exported with their lower surface at zero.
    triangles = list(struct.iter_unpack("<12fH", data[84:]))
    h = .73  # Plates print face down, with the top sheet at the bed.
    for triangle in triangles:
        vertices = (triangle[3:6], triangle[6:9], triangle[9:12])
        ends = []
        for a, b in zip(vertices, vertices[1:] + vertices[:1]):
            if (a[2] > h) != (b[2] > h):
                t = (h-a[2]) / (b[2]-a[2])
                ends.append((round(a[0]+t*(b[0]-a[0]),3), -round(a[1]+t*(b[1]-a[1]),3)))
        if len(ends) == 2 and ends[0] != ends[1]:
            a, b = ends
            adj[a].add(b)
            adj[b].add(a)
    outlines, apertures = [], []
    while adj:
        point = next(iter(adj))
        loop = [point]
        while adj.get(point):
            other = adj[point].pop()
            if not adj[point]:
                del adj[point]
            adj[other].remove(point)
            if not adj[other]:
                del adj[other]
            if other == loop[0]:
                break
            loop.append(other)
            point = other
        edges = list(zip(loop, loop[1:] + loop[:1]))
        cross = [a[0]*b[1] - b[0]*a[1] for a,b in edges]
        area = sum(cross)/2
        if abs(area) > 500:
            outlines.append(loop)
        elif 185 < abs(area) < 210:
            centroid = tuple(sum((a[i]+b[i])*c for (a,b),c in zip(edges,cross))/(6*area) for i in (0,1))
            apertures.append((loop,centroid))
    return outlines, apertures


def compose(folder):
    from PIL import Image, ImageDraw, ImageFont, ImageFilter

    size = (1700, 1980)
    paper, dark, ink, muted = "#f8f6ef", "#e2dfd3", "#33382f", "#676b5c"
    canvas = Image.new("RGB", size, paper)
    draw = ImageDraw.Draw(canvas)

    def font(n, bold=False, mono=False):
        base = Path("/System/Library/Fonts")
        choices = ([base / "SFNSMono.ttf", "DejaVuSansMono.ttf"] if mono else
                   [base / "Supplemental" / ("Arial Bold.ttf" if bold else "Arial.ttf"),
                    "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"])
        for name in choices:
            try:
                return ImageFont.truetype(str(name), n)
            except OSError:
                pass
        return ImageFont.load_default(size=n)

    def label(x, y, content, n, bold=False, mono=False, fill=ink):
        draw.text((x,y), content, font=font(n,bold,mono), fill=fill, anchor="lt")

    def layer(path, box, shadow=True):
        im = Image.open(folder / path).convert("RGBA")
        im.thumbnail((box[2], box[3]), Image.Resampling.LANCZOS)
        x = box[0] + (box[2] - im.width)//2
        y = box[1] + (box[3] - im.height)//2
        if shadow:
            mask = im.getchannel("A").filter(ImageFilter.GaussianBlur(8)).point(lambda a: round(a*.15))
            canvas.paste("#6d756d", (x+1,y+10,x+1+im.width,y+10+im.height), mask)
        canvas.paste(im, (x,y), im)

    draw.rectangle((0, 0, 1699, 690), fill=dark)
    label(68, 65, "STANDARD   /   MX", 23, mono=True, fill=muted)
    label(62, 151, "Folding", 93, bold=True)
    label(62, 254, "keyboard", 93, bold=True)
    label(69, 461, "Flat right half", 31, bold=True)
    label(69, 513, "Five finger columns", 25, fill=muted)
    label(69, 553, "Three thumb keys", 25, fill=muted)
    layer("hero.png", (503, 22, 1160, 646))

    draw.line((68, 750, 1632, 750), fill="#abae9e", width=2)
    label(68, 785, "Folded pair", 40, bold=True)
    label(1290, 799, "STANDARD   /   60°", 22, mono=True, fill=muted)
    layer("pair.png", (94, 846, 1512, 370))

    draw.line((68, 1268, 1632, 1268), fill="#abae9e", width=2)
    label(68, 1305, "Flat layouts", 40, bold=True)
    label(1178, 1320, "RIGHT HANDS   /   SAME SCALE", 22, mono=True, fill=muted)
    layer("standard.png", (45, 1380, 780, 418))
    layer("expanded.png", (875, 1380, 780, 418))
    label(68, 1830, "Standard", 32, bold=True)
    label(884, 1830, "Expanded", 32, bold=True)
    label(68, 1888, "17 finger keys + 3 thumb keys", 25, fill=muted)
    label(884, 1888, "26 finger keys + 3 thumb keys", 25, fill=muted)
    canvas.save(ROOT / "preview.png", optimize=True)
    canvas = Image.new("RGB", (1700, 1220), paper)
    draw = ImageDraw.Draw(canvas)
    label(68,61,"MX  /  CASE STUDY",23,mono=True,fill=muted)
    label(64,122,"Printable case",73,bold=True)
    label(68,237,"Standard right half",28,fill=muted)
    draw.line((68,306,1632,306),fill="#a8b2ab",width=2)
    layer("parts.png",(45,333,1610,740),shadow=False)
    draw.line((68,1084,1632,1084),fill="#a8b2ab",width=2)
    label(70,1120,"Exploded view",31,bold=True)
    label(420,1124,"Two removable MX plates, two shells and a shared metal axle.",27,fill=muted)
    canvas.save(ROOT / "case-parts.png", optimize=True)

    # Reference measurements from cross-sections of the maker's v1.0.1 top
    # plates in a common hand coordinate system. No source mesh is distributed.
    ref = [(x, y + 16*r) for i,(x,y) in enumerate([(-64,-10),(-48,0),(-32,4),(-16,2),(0,0)])
           for r in range(-1 if i < 2 else 0, 3)]
    ref.extend([(-10.67,-32.605), (8.68,-34.97), (26.89,-41.957)])
    path = ROOT / "print/standard/left"
    main_outline, main_windows = flat_plate_sections(path / "fixed_plate.stl")
    thumb_outline, thumb_windows = flat_plate_sections(path / "thumb_plate.stl")
    if len(main_windows) != 17 or len(thumb_windows) != 3:
        raise ValueError("Unexpected aperture count in standard STLs")
    anchor_x = max(center[0] for _, center in main_windows)
    anchor_y = min(y for _,(x,y) in main_windows if abs(x-anchor_x)<.1)
    targets = [(anchor_x + x*19.05/16, anchor_y + y*19.05/16) for x,y in ref]
    centers = [v[1] for v in main_windows+thumb_windows]
    delta = [min(math.dist(t,c) for c in centers) for t in targets]

    canvas = Image.new("RGB", (1600, 1020), paper)
    draw = ImageDraw.Draw(canvas)
    label(65,62,"STANDARD   /   RIGHT HAND",22,mono=True,fill=muted)
    label(62,119,"Layout registration",66,bold=True)
    label(67,228,"Switch centers, rescaled from 16 mm to 19.05 mm pitch",26,fill=muted)
    draw.line((65,290,1535,290),fill="#abae9e",width=2)
    all_points = [p for poly in main_outline+thumb_outline for p in poly]
    minx,maxx = min(x for x,y in all_points),max(x for x,y in all_points)
    miny,maxy = min(y for x,y in all_points),max(y for x,y in all_points)
    scale = min(920/(maxx-minx),600/(maxy-miny))
    def project(p):
        return (88+(maxx-p[0])*scale, 334+(maxy-p[1])*scale)
    for poly in main_outline+thumb_outline:
        draw.polygon([project(p) for p in poly],fill="#e1dfd3",outline="#868b7c",width=2)
    for poly,(cx,cy) in main_windows+thumb_windows:
        draw.polygon([project(p) for p in poly],fill=paper,outline="#9d9f91",width=2)
        x,y=project((cx,cy))
        draw.ellipse((x-4,y-4,x+4,y+4),fill=ink)
    for p in targets:
        x,y=project(p)
        draw.ellipse((x-9,y-9,x+9,y+9),outline="#7e5542",width=3)
    label(1040,390,"Source center",28,bold=True)
    draw.ellipse((1002,392,1022,412),outline="#7e5542",width=3)
    label(1040,454,"MX aperture center",28,bold=True)
    draw.ellipse((1008,459,1017,468),fill=ink)
    label(1004,580,"Largest center offset",26,fill=muted)
    label(1000,631,"< 0.1 mm" if max(delta) < .1 else f"{max(delta):.1f} mm",61,bold=True)
    label(1004,749,"Aligned at the innermost",24,fill=muted)
    label(1004,790,"front finger key.",24,fill=muted)
    draw.line((65,945,1535,945),fill="#abae9e",width=2)
    label(67,967,"Source: KobitoKey v1.0.1 plate meshes     /     MX geometry: exported standard plates",20,mono=True,fill=muted)
    canvas.save(ROOT / "layout-fit.png", optimize=True)



if __name__ == "__main__":
    if "--render-shots" in sys.argv:
        render_models(Path(sys.argv[-1]))
    else:
        blender = os.environ.get("BLENDER") or shutil.which("blender") or "/Applications/Blender.app/Contents/MacOS/Blender"
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run([blender, "-b", "--factory-startup", "--python-exit-code", "1",
                            "--python", __file__, "--", "--render-shots", tmp], check=True)
            compose(Path(tmp))
