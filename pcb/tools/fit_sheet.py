"""Create both A4 fit templates. Run with ReportLab and pass KiCad's Python path."""
import argparse
import json
import math
from pathlib import Path
import subprocess
import sys

PCB = Path(__file__).resolve().parents[1]


def get_geometry():
    import pcbnew as k

    def xy(v):
        return [k.ToMM(v.x), k.ToMM(v.y)]

    def shape(g):
        start, end = xy(g.GetStart()), xy(g.GetEnd())
        kind = g.GetShape()
        if kind == k.SHAPE_T_SEGMENT:
            return ["path", [start, end]]
        if kind == k.SHAPE_T_CIRCLE:
            return ["circle", xy(g.GetCenter()), k.ToMM(g.GetRadius())]
        if kind == k.SHAPE_T_RECT:
            corners = [xy(p) for p in g.GetRectCorners()]
            return ["path", corners + [corners[0]]]
        if kind == k.SHAPE_T_ARC:
            center = xy(g.GetCenter())
            angle = lambda v: math.atan2(v[1] - center[1], v[0] - center[0])
            a, b, mid = angle(start), angle(end), angle(xy(g.GetArcMid()))
            sweep = (b-a) % math.tau
            if (mid-a) % math.tau > sweep:
                sweep -= math.tau
            radius = math.dist(center,start)
            steps = max(2, math.ceil(abs(sweep)*radius/0.15))
            return ["path", [[center[0] + radius*math.cos(a+sweep*i/steps),
                              center[1] + radius*math.sin(a+sweep*i/steps)] for i in range(steps+1)]]
        raise ValueError(f"Unhandled geometry: {g.GetShapeStr()}")

    result = {}
    for hand in ("left", "right"):
        decks = []
        for deck in ("finger", "thumb"):
            name = f"{hand}-{deck}"
            board = k.LoadBoard(str(PCB/name/(name + ".kicad_pcb")))
            edges = [shape(g) for g in board.GetDrawings() if g.GetLayer() == k.Edge_Cuts]
            switches, connectors = [], []
            for fp in board.GetFootprints():
                ref = fp.GetReference()
                if ref.startswith("SW"):
                    holes = [(xy(p.GetPosition()), k.ToMM(p.GetDrillSizeX())/2) for p in fp.Pads()
                             if p.GetAttribute() == k.PAD_ATTRIB_NPTH]
                    assert len(holes) == 5
                    switches.append([ref, xy(fp.GetPosition()), holes])
                elif ref in ("J1","J2","U1","S1"):
                    body = [shape(g) for g in fp.GraphicalItems() if isinstance(g,k.PCB_SHAPE)
                            and g.GetLayer()==k.B_Fab
                            and (ref != "U1" or g.GetShape()!=k.SHAPE_T_RECT)]
                    pad1 = [xy(p.GetPosition()) for p in fp.Pads() if p.GetNumber()=="1"][0]
                    assert body and fp.IsFlipped()
                    connectors.append([ref,pad1,body])
            decks.append(dict(edges=edges,switches=switches,connectors=connectors))
        result[hand] = decks
    return result


def draw_file(data):
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen.canvas import Canvas

    output = PCB/"expanded-mx-fit-sheets.pdf"
    c = Canvas(str(output), pagesize=A4, pageCompression=1, invariant=1)
    c.setTitle("Lexx expanded MX | Full-scale PCB fit sheets")
    c.setAuthor("Lexx")
    ink, grey, connector, post = "#183036", "#62757A", "#9B4A26", "#126678"
    full = json.loads((PCB.parent/"validation/design.json").read_text())["Expanded"]
    supports = json.loads((PCB/"case/supports.json").read_text())

    def pen(color=ink, width=.25, dash=()):
        c.setStrokeColor(HexColor(color))
        c.setLineWidth(width)
        c.setDash(dash)

    def txt(x, y, s, size=3, bold=False, color=ink, align="left"):
        c.setFillColor(HexColor(color))
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        method = {"left": c.drawString, "center": c.drawCentredString, "right": c.drawRightString}[align]
        method(x,y,s)

    def plus(x,y,r):
        c.line(x-r,y,x+r,y)
        c.line(x,y-r,x,y+r)

    for page, (hand, decks) in enumerate(data.items(),1):
        c.saveState()
        c.scale(mm,mm)
        txt(15,278,"LEXX  /  EXPANDED MX",3.3,True)
        txt(195,278,f"FIT SHEET   {page} / 2",3,align="right")
        txt(15,263,f"{hand.title()} hand",9,True)
        txt(15,254,"Flat position, viewed from the keycaps. Both boards share their assembled position.",3.5)
        txt(15,247,"Print on A4 at 100% or Actual Size. Measure the scale line before matching the case.",3.1)
        pen(grey,.15)
        c.line(15,240,195,240)
        pts = [p for deck in decks for e in deck["edges"] if e[0]=="path" for p in e[1]]
        dx = 105-(min(p[0] for p in pts) + max(p[0] for p in pts))/2
        dy = 158+(min(p[1] for p in pts) + max(p[1] for p in pts))/2

        def pos(p):
            return (p[0]+dx,dy-p[1])

        def geom(s):
            if s[0]=="circle":
                c.circle(*pos(s[1]),s[2],stroke=1,fill=0)
            else:
                p=c.beginPath()
                p.moveTo(*pos(s[1][0]))
                for v in s[1][1:]:
                    p.lineTo(*pos(v))
                c.drawPath(p,stroke=1,fill=0)

        for deck in decks:
            pen(ink,.32)
            for edge in deck["edges"]:
                geom(edge)
            for ref,pt,holes in deck["switches"]:
                x,y=pos(pt)
                pen(grey,.13)
                for p,r in holes:
                    c.circle(*pos(p),r,stroke=1,fill=0)
                pen(ink,.19)
                plus(x,y,1.25)
                txt(x,y-7.9,ref,1.8,color=grey,align="center")
            for ref, pad1, body in deck["connectors"]:
                pen(connector,.22)
                for line in body:
                    geom(line)
                pts = [pos(p) for s in body if s[0]=="path" for p in s[1]]
                if ref in ("J1","J2"):
                    c.setFillColor(HexColor(connector))
                    c.circle(*pos(pad1),.48,stroke=0,fill=1)
                x = (min(p[0] for p in pts)+max(p[0] for p in pts))/2
                y = (min(p[1] for p in pts)+max(p[1] for p in pts))/2
                if ref == "S1":  # Slender body, label alongside toward center of thumb board.
                    x += -6 if hand=="left" else 6
                txt(x,y-.65,ref,1.8,True,connector,align="center")
        sign=1 if hand=="left" else -1
        for zone in ("fixed","thumb"):
            for x,y in full[zone]["screws"]:
                x,y=pos((150+sign*x,100-y))
                pen(post,.2)
                plus(x,y,1.35)
            for x,y,r in supports[zone]:
                x,y=pos((150+sign*x,100-y))
                pen(post,.22,(.7,.5))
                c.circle(x,y,r,stroke=1,fill=0)
        pen(grey,.15)
        c.line(15,76,195,76)
        txt(15,68,"Reading the template",4.8,True)
        txt(15,60,"Dark outline",3,True)
        txt(54,60,"Finished PCB edges, including notches and post clearances.",3)
        txt(15,54,"Gray circles",3,True,grey)
        txt(54,54,"MX stem, locating pegs and socket holes. The cross marks each switch center.",3)
        txt(15,48,"Teal marks",3,True,post)
        txt(54,48,"Crosses mark screw-post centers. Dashed circles show the tips of PCB supports.",3)
        txt(15,42,"Copper-colored outlines",3,True,connector)
        txt(54,42,"Underside parts. Dots identify pin 1 on J1 (ribbon) and J2 (battery).",3)
        txt(54,36,"U1 is the XIAO with USB-C. S1 is the power switch.",3)
        pen(ink,.28)
        c.line(15,17,65,17)
        for x in (15,65):
            c.line(x,14.8,x,19.2)
        txt(40,21,"50 mm",3.5,True,align="center")
        txt(195,16,"A4   /   1:1   /   TOP VIEW",3.1,True,align="right")
        c.restoreState()
        c.showPage()
    c.save()
    print(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extract",action="store_true",help=argparse.SUPPRESS)
    parser.add_argument("--kicad-python",default=sys.executable,help="Python with the pcbnew module")
    args = parser.parse_args()
    if args.extract:
        print(json.dumps(get_geometry()))
    else:
        data = subprocess.check_output([args.kicad_python, __file__, "--extract"])
        draw_file(json.loads(data))
