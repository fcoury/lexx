"""Make two actual-size PG1353 fit sheets from the routed KiCad boards.

Run with ReportLab and --kicad-python pointing to Python with KiCad 10 pcbnew.
"""

import argparse
import json
import math
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def board_geometry():
    import pcbnew as k

    def xy(vector):
        return [k.ToMM(vector.x), k.ToMM(vector.y)]

    def line_or_circle(g):
        if g.GetShape() == k.SHAPE_T_SEGMENT:
            return ["line", xy(g.GetStart()), xy(g.GetEnd())]
        if g.GetShape() == k.SHAPE_T_CIRCLE:
            return ["circle", xy(g.GetCenter()), k.ToMM(g.GetRadius())]
        raise ValueError(f"Unsupported Edge.Cuts primitive: {g.GetShapeStr()}")

    def switch(fp):
        drills = []
        for pad in fp.Pads():
            x, y = xy(pad.GetDrillSize())
            if x <= 0:
                continue
            origin = xy(pad.GetPosition())
            angle = math.radians(pad.GetOrientationDegrees())
            # Drill axes inherit pad rotation. KiCad screen Y increases down.
            axis = (
                [-math.sin(angle), -math.cos(angle)]
                if y > x
                else [math.cos(angle), -math.sin(angle)]
            )
            drills.append(
                dict(center=origin, width=min(x, y), length=max(x, y), axis=axis)
            )
        (stem,) = [d["center"] for d in drills if abs(d["width"] - 5.00) < 0.01]
        contacts = [d["center"] for d in drills if abs(d["width"] - 3.0) < 0.01]
        if len(contacts) != 2 or len(drills) != 4:
            raise ValueError(f"{fp.GetReference()}: incomplete PG1353 pattern")
        # The contact on the switch centerline is closer to the stem than
        # the off-axis contact. The LED window is on the opposite side.
        p = min(contacts, key=lambda c: math.dist(c, stem))
        r = math.dist(p, stem)
        assert 5.8 < r < 6.1
        return dict(
            ref=fp.GetReference(),
            center=stem,
            drills=drills,
            led=[(stem[0] - p[0]) / r, (stem[1] - p[1]) / r],
        )

    hands = {}
    for hand in ("left", "right"):
        boards = []
        for kind, expected in (("finger", 26), ("thumb", 3)):
            folder = ROOT / "pcb" / f"{hand}-{kind}"
            board = k.LoadBoard(str(folder / (folder.name + ".kicad_pcb")))
            edges = [
                line_or_circle(g)
                for g in board.GetDrawings()
                if g.GetLayer() == k.Edge_Cuts
            ]
            keys = [
                switch(fp)
                for fp in board.GetFootprints()
                if fp.GetReference().startswith("SW")
            ]
            assert len(keys) == expected
            boards.append(dict(kind=kind, edges=edges, keys=keys))
        hands[hand] = boards
    return hands


def render(data, path):
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen.canvas import Canvas

    c = Canvas(str(path), pagesize=A4, pageCompression=1, invariant=1)
    c.setTitle("Lexx Choc V2 | 1:1 switch and PCB fit sheets")
    c.setAuthor("Lexx")
    dark, gray, accent, blue = "#233632", "#50635d", "#a93e15", "#196170"

    def pen(color, width):
        c.setStrokeColor(HexColor(color))
        c.setLineWidth(width)
        c.setLineCap(1)

    def label(x, y, content, size, bold=False, color=dark, align="left"):
        c.setFillColor(HexColor(color))
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        getattr(
            c,
            {
                "left": "drawString",
                "center": "drawCentredString",
                "right": "drawRightString",
            }[align],
        )(x, y, content)

    for hand, boards in data.items():
        c.saveState()
        c.scale(mm, mm)
        label(15, 276, "LEXX   /   CHOC V2", 4, True)
        label(195, 276, "SOUTH-FACING   /   FIT SHEET", 3, True, gray, "right")
        label(15, 257, hand.title() + " hand", 9, True)
        label(
            15,
            247,
            "Print on A4 at 100% or Actual Size. Measure the scale bar before checking a plate.",
            3.1,
        )
        pen(gray, 0.17)
        c.line(15, 240, 195, 240)
        outline = [
            pt
            for board in boards
            for kind, p, q in board["edges"]
            if kind == "line"
            for pt in (p, q)
        ]
        cx = (min(p[0] for p in outline) + max(p[0] for p in outline)) / 2
        cy = (min(p[1] for p in outline) + max(p[1] for p in outline)) / 2

        def pos(point):
            return 105 + point[0] - cx, 159 - point[1] + cy

        for board in boards:
            pen(dark, 0.31)
            for kind, p, q in board["edges"]:
                if kind == "line":
                    c.line(*pos(p), *pos(q))
                else:
                    c.circle(*pos(p), q)
            for key in board["keys"]:
                x, y = pos(key["center"])
                for drill in key["drills"]:
                    xx, yy = pos(drill["center"])
                    short, long = drill["width"], drill["length"]
                    if abs(long - short) < 0.0001:
                        pen(gray, 0.17)
                        c.circle(xx, yy, short / 2)
                    else:
                        # Outline the actual milled slot at its native rotation.
                        ax, ay = drill["axis"]
                        c.saveState()
                        c.translate(xx, yy)
                        c.rotate(math.degrees(math.atan2(-ay, ax)))
                        pen(blue, 0.17)
                        c.roundRect(
                            -long / 2,
                            -short / 2,
                            long,
                            short,
                            short / 2,
                            stroke=1,
                            fill=0,
                        )
                        c.restoreState()
                pen(dark, 0.2)
                c.line(x - 1, y, x + 1, y)
                c.line(x, y - 1, x, y + 1)
                dx, dy = key["led"]
                dy = -dy
                tip = (x + 5.6 * dx, y + 5.6 * dy)
                for sign in (-1, 1):
                    pen(accent, 0.41)
                    c.line(x + 4.1 * dx + sign * dy, y + 4.1 * dy - sign * dx, *tip)
                label(
                    x + 4.9 * dy - 1.4 * dx,
                    y - 4.9 * dx - 1.4 * dy,
                    key["ref"],
                    1.6,
                    False,
                    gray,
                    "center",
                )
        pen(gray, 0.17)
        c.line(15, 77, 195, 77)
        label(15, 69, "Reading the template", 5, True)
        for yy, title, desc, color in (
            (
                60,
                "Black outline",
                "Routed PCB perimeter and screw-post clearances, seen from the keycaps.",
                dark,
            ),
            (
                52,
                "Gray circles",
                "Center post (5 mm) and the two hot-swap socket openings (3 mm).",
                gray,
            ),
            (
                44,
                "Blue slot",
                "Unplated slot for the fourth leg of the PG1353 switch.",
                blue,
            ),
            (
                36,
                "Orange V",
                "LED-window side, toward the typist at the front of each key.",
                accent,
            ),
        ):
            label(15, yy, title, 3.2, True, color)
            label(53, yy, desc, 2.95)
        pen(dark, 0.28)
        c.line(15, 17, 65, 17)
        for xx in (15, 65):
            c.line(xx, 15, xx, 19)
        label(40, 21, "50 mm", 3.4, True, align="center")
        label(195, 16, "A4   /   1:1   /   FLAT POSITION", 3, True, gray, "right")
        c.restoreState()
        c.showPage()
    c.save()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--extract", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--kicad-python", default=sys.executable)
    ap.add_argument("--output", type=Path, default=ROOT / "fit-sheets.pdf")
    args = ap.parse_args()
    if args.extract:
        print(json.dumps(board_geometry()))
    else:
        output = subprocess.check_output([args.kicad_python, __file__, "--extract"])
        render(json.loads(output), args.output)
