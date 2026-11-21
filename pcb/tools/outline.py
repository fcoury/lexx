"""Extract the board boundary at switch-PCB height from the released case STL (mm)."""

import struct
from pathlib import Path
from shapely.geometry import LineString, Polygon
from shapely.ops import polygonize

ROOT = Path(__file__).resolve().parents[2]


def cavity(hand, deck, height=12.37):
    shell = "fixed" if deck == "finger" else "thumb"
    path = ROOT / "print" / "expanded" / hand / (shell + "_shell.stl")
    segments = []
    for triangle in struct.iter_unpack("<12fH", path.read_bytes()[84:]):
        vertices = [triangle[i : i + 3] for i in (3, 6, 9)]
        ends = []
        for a, b in zip(vertices, vertices[1:] + vertices[:1]):
            if (a[2] > height) != (b[2] > height):
                f = (height - a[2]) / (b[2] - a[2])
                ends.append(tuple(round(a[i] + f * (b[i] - a[i]), 4) for i in (0, 1)))
        if len(ends) == 2 and ends[0] != ends[1]:
            segments.append(LineString(ends))
    # Interior of the shell is the largest closed region with no smaller nested ring.
    areas = list(polygonize(segments))
    return max(areas, key=lambda p: p.area)


def board(hand, deck):
    return (
        cavity(hand, deck)
        .buffer(-0.45, join_style="round", quad_segs=4)
        .simplify(0.045, preserve_topology=True)
    )
