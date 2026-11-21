"""Draw the mechanical assembly plan from the left KiCad boards and shell STLs."""

import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import LineString, Polygon, box
from shapely.ops import polygonize

sys.path.insert(0,str(Path(__file__).resolve().parent))
from check_boards import HERE, ROOT, PROFILE, edge_cuts, pose, stl_mesh


def section(tris, axis, value):
    lines = []
    for tri in tris:
        cut = []
        for a,b in zip(tri, np.roll(tri,-1,axis=0)):
            if (a[axis]>value) != (b[axis]>value):
                p = a+(b-a)*((value-a[axis])/(b[axis]-a[axis]))
                cut.append(np.round(np.delete(p,axis),5))
        if len(cut)==2 and not np.array_equal(cut[0],cut[1]):
            lines.append(LineString(cut))
    return max(polygonize(lines),key=lambda poly:poly.area)


def main():
    bg, ink, muted = "#f9f8f4", "#202e33", "#49606a"
    shell, pcb, socket = "#e5ddce", "#c4dfd7", "#789792"
    module, cell, cable, pad = "#6487a2", "#e4c576", "#d46641", "#b5334e"
    image = Image.new("RGB",(2940,1810),bg)
    pen = ImageDraw.Draw(image)
    def font(size, bold=False):
        source = Path("/System/Library/Fonts/Supplemental")/("Arial Bold.ttf" if bold else "Arial.ttf")
        return ImageFont.truetype(str(source),size*2) if source.exists() else ImageFont.load_default(size*2)
    def label(x,y,s,size=17,bold=False,color=ink):
        pen.text((x*2,y*2),s,font=font(size,bold),fill=color,anchor="lt")
    def line(coords, color=muted, width=1):
        pen.line([(x*2,y*2) for x,y in coords],fill=color,width=width*2)
    def draw_poly(poly, transform, fill, outline, hole_color):
        def ring(r, color):
            pts=[tuple(n*2 for n in transform(x,y)) for x,y in r.coords]
            pen.polygon(pts,fill=color,outline=outline,width=2)
        for p in getattr(poly,"geoms",[poly]):
            if p.geom_type != "Polygon": continue
            ring(p.exterior,fill)
            for hole in p.interiors: ring(hole,hole_color)
    plan = lambda x,y: (657+x*4.8,405-y*4.8)
    detail = lambda x,y: (861+x*8,402-y*8)
    label(40,27,"Expanded MX   /   PCB fit",34,True)
    label(40,75,"Left hand, flat. The switch plates are lifted in the plan view.",18,color=muted)
    line([(40,110),(1430,110)],"#aec0ba")
    label(40,132,"Boards and shell supports",21,True)
    label(904,132,"Thumb electronics",21,True)
    boards = {}
    shell_mesh = {}
    parts = {}
    for deck,kind in (("finger","fixed"),("thumb","thumb")):
        folder=ROOT/"pcb"/("left-"+deck)
        boards[deck]=edge_cuts(folder/("left-"+deck+".kicad_pcb"))
        shell_mesh[deck]=stl_mesh(HERE/"print"/"left"/(kind+"_shell.stl"))
        parts[deck]=json.loads((folder/"circuit.json").read_text())
        draw_poly(section(shell_mesh[deck],2,1.5),plan,shell,ink,bg)
        draw_poly(boards[deck],plan,pcb,muted,shell)
    profiles = json.loads((HERE/"component-profiles.json").read_text())
    def draw_parts(deck,transform):
        for part in parts[deck]:
            key=part["footprint"].split(":")[-1]
            if key=="SOD123":continue
            local = Polygon(profiles[key]["xy"]) if key in profiles else PROFILE[key]
            shape=pose(local,*part["xy"],part["angle"])
            draw_poly(shape,transform, socket if key=="MX" else cable if key=="FFC12" else module,
                      muted,pcb)
    def draw_supports(kind,transform):
        for x,y,r in json.loads((HERE/"supports.json").read_text())[kind]:
            cx,cy=transform(x,y)
            dx=abs(transform(x+r,y)[0]-cx)
            pen.ellipse(((cx-dx)*2,(cy-dx)*2,(cx+dx)*2,(cy+dx)*2),fill=pad,outline=bg,width=2)
    for deck,kind in (("finger","fixed"),("thumb","thumb")):
        draw_parts(deck,plan)
        draw_supports(kind,plan)
    # Show the bay at assembly scale and draw the components above the battery.
    crop = box(9,-49,34,27)
    draw_poly(boards["thumb"].intersection(crop),detail,pcb,muted,bg)
    draw_poly(box(12,-33,30,-9),detail,cell,ink,pcb)
    draw_poly(pose(box(-3.25,1,3.25,14),20.25,13.45,-9).intersection(crop),
              detail,"#f6dbc0",muted,pcb)
    for part in parts["thumb"]:
        key=part["footprint"].split(":")[-1]
        if key not in ("XIAO","FFC12","PowerSwitch","Battery"):continue
        shape = (box(11,-8.39,32.05,9.39) if key=="XIAO" else
                 pose(PROFILE[key],*part["xy"],part["angle"]))
        draw_poly(shape.intersection(crop),detail,
                  cable if key=="FFC12" else module,ink,pcb)
        if key=="XIAO":
            draw_poly(box(26.3,-4.0,33.55,5.0),detail,"#bed1dc",ink,pcb)
    def callout(start,x,y,s,sub):
        line([start,(x-12,start[1]),(x-12,y+9),(x-3,y+9)],muted)
        label(x,y,s,17,True)
        label(x,y+27,sub,15,color=muted)
    callout(detail(23.4,15.7),1170,263,"J1 flex","12 contacts, 0.5 mm pitch")
    callout(detail(32.8,.5),1170,382,"USB-C","12.0 × 6.8 mm window")
    callout(detail(30.7,-13.6),1170,494,"Power switch","9.0 × 3.8 mm window")
    callout(detail(27,-26),1170,594,"Protected battery","18 × 24 × 4 mm below PCB")
    callout(detail(23,-43),1170,727,"J2 battery connector","Side-entry JST PH")
    line([(40,843),(1430,843)],"#aec0ba")
    for x,color,text in [(42,pcb,"PCB outline"),(248,shell,"Printed shell"),(466,socket,"MX socket envelope"),
                         (760,pad,"PCB support"),(991,module,"Electronics"),(1220,cable,"Flex connector")]:
        pen.rectangle((x*2,865*2,(x+17)*2,882*2),fill=color,outline=ink,width=1)
        label(x+27,864,text,16,color=ink)
    image.resize((1470,905),Image.Resampling.LANCZOS).save(HERE/"mechanical-fit.png")


if __name__=="__main__":
    main()
