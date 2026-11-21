"""Generate the clearance footprint and KiCad envelope for Kailh CPG135001S30.

Dimensions in mm, from Kailh KHA-PG1350-005EN. The silhouette bounds the
maximum body and terminal sizes. Its deliberately square shoulders allow
clearance at the moulded transitions and at both solder tails.
"""

import json
import math
from pathlib import Path

PCB = Path(__file__).resolve().parents[1]
# Board viewed from keycaps, Y away from typist. Socket sleeves register
# at (0, 5.95) and (5, 3.75). The body grows 0.15 mm in overall length.
x_mid = 2.50
body_half_length = (9.95 + 0.15) / 2
tail_half_length = (13.15 + 0.15) / 2
body_half_width = (4.65 + 0.10) / 2
tail_half_width = (1.68 + 0.05) / 2
left_y, right_y = 5.95, 3.75
x0, x1 = x_mid - body_half_length, x_mid + body_half_length
t0, t1 = x_mid - tail_half_length, x_mid + tail_half_length
ly0, ly1 = left_y - body_half_width, left_y + body_half_width
ry0, ry1 = right_y - body_half_width, right_y + body_half_width
# Each shoulder occupies at most about 2 mm along X in the drawing.
sl, sr = x_mid - 1.10, x_mid + 1.10
body = [
    (x0, ly0),
    (sl, ly0),
    (sl, ry0),
    (x1, ry0),
    (x1, ry1),
    (sr, ry1),
    (sr, ly1),
    (x0, ly1),
]
tails = [
    [
        (t0, left_y - tail_half_width),
        (x0, left_y - tail_half_width),
        (x0, left_y + tail_half_width),
        (t0, left_y + tail_half_width),
    ],
    [
        (x1, right_y - tail_half_width),
        (t1, right_y - tail_half_width),
        (t1, right_y + tail_half_width),
        (x1, right_y + tail_half_width),
    ],
]
# Follow the left tail clockwise around its exterior before closing at x0.
outline = [
    *body[:4],
    *tails[1],
    *body[4:],
    (x0, left_y + tail_half_width),
    (t0, left_y + tail_half_width),
    (t0, left_y - tail_half_width),
    (x0, left_y - tail_half_width),
]
underside_depth = 1.85 + 0.10


def feature(points, lo, hi, color):
    # WRL +Y points up the drawing of a front footprint. KiCad flips this
    # footprint around X on the underside, restoring 'away' in the built board.
    vertices = [(x / 2.54, -y / 2.54, z / 2.54) for z in (lo, hi) for x, y in points]
    n = len(points)
    faces = [range(n - 1, -1, -1), range(n, 2 * n)]
    faces += [(i, (i + 1) % n, (i + 1) % n + n, i + n) for i in range(n)]
    coords = ",\n      ".join("%.6f %.6f %.6f" % v for v in vertices)
    indices = ",\n      ".join(" ".join(map(str, face)) + " -1" for face in faces)
    return f"""Shape {{
  appearance Appearance {{ material Material {{ diffuseColor {color} }} }}
  geometry IndexedFaceSet {{
    ccw FALSE
    solid TRUE
    convex FALSE
    coord Coordinate {{ point [ {coords} ] }}
    coordIndex [ {indices} ]
  }}
}}
"""


def main():
    profile = {
        "xy": [[round(x, 4), round(y, 4)] for x, y in outline],
        "lowest_from_board_underside_mm": -underside_depth,
        "comment": "Independent maximum-size CPG135001S30 envelope from Kailh KHA-PG1350-005EN. Local keycap-side view at south: +X right, +Y away. Square shoulders and full-depth terminal allowance bound the tapered moulding and solder tails.",
    }
    (PCB / "socket-profile.json").write_text(json.dumps(profile, indent=2) + "\n")
    model = "#VRML V2.0 utf8\n# Independently dimensioned socket envelope. Units are 2.54 mm.\n"
    model += feature(body, 0, underside_depth, "0.18 0.18 0.17")
    for tail in tails:
        model += feature(tail, 0, underside_depth, "0.68 0.63 0.51")
    # The 2.90 mm insulating collars rise through the two 3 mm board drills.
    for cx, cy in [(0, left_y), (5, right_y)]:
        circle = [
            (
                cx + 1.45 * math.cos(i * math.tau / 24),
                cy + 1.45 * math.sin(i * math.tau / 24),
            )
            for i in range(24)
        ]
        model += feature(circle, -1.25, 0, "0.23 0.23 0.22")
    (PCB / "models" / "CPG135001S30.wrl").write_text(model)


if __name__ == "__main__":
    main()
