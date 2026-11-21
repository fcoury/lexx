"""Generate assembly placements in the committed case's XY coordinate system."""

import json
import math
import uuid
from shapely.affinity import rotate, translate
from shapely.geometry import Point, box
from shapely.ops import unary_union
from outline import ROOT, board, cavity

PCB = ROOT / "pcb"
LAYOUT = json.loads((ROOT / "validation/design.json").read_text())["Expanded"]
FLEX = {
    str(i + 1): v
    for i, v in enumerate(
        [f"R{n}" for n in range(5)] + [f"C{n}" for n in range(6)] + [None]
    )
}
SOCKET = unary_union(
    [
        box(-7.34, -6.45, 8.55, -1.22),
        Point(0, 0).buffer(2.12),
        Point(-5.08, 0).buffer(1.03),
        Point(5.08, 0).buffer(1.03),
    ]
)
DIODE = box(-2.5, -1.18, 2.5, 1.18)


def pose(shape, x, y, a):
    return translate(rotate(shape, a, origin=(0, 0)), x, y)


def outlines(poly):
    return [
        [[round(x, 4), round(y, 4)] for x, y in ring.coords]
        for ring in [poly.exterior, *poly.interiors]
    ]


def plan(hand, deck):
    name = f"{hand}-{deck}"
    finger = deck == "finger"
    sign = 1 if hand == "left" else -1
    data = LAYOUT["fixed" if finger else "thumb"]
    outline = board(hand, deck)
    for x, y in data["screws"]:
        outline = outline.difference(Point(sign * x, y).buffer(2.85, quad_segs=12))
    if finger:
        # SW18 sits in a single-key finger of the outline. Preserve 0.24 mm
        # to the case locally while giving its outer socket land 0.55 mm to the mill.
        px = -89.02 if hand == "left" else 99.18
        py = -52.29825
        land = box(px - 1.25, py - 1.275, px + 1.25, py + 1.275)
        rim = cavity(hand, deck).buffer(-0.24)
        outline = outline.union(land.buffer(0.57, quad_segs=6).intersection(rim))
    if not finger:
        # Air below the onboard antenna, at the end opposite the USB connector.
        xs = sorted([sign * 9, sign * 15.3])
        ys = sorted([0.5 + sign * (u - 8.89) for u in (2.9, 9.5)])
        outline = outline.difference(box(xs[0], ys[0], xs[1], ys[1]))
    parts = []
    obstacles = []

    def add(ref, value, foot, x, y, angle, nets, extra=None):
        uid = str(uuid.uuid5(uuid.NAMESPACE_URL, "lexx/expanded/" + name + "/" + ref))
        parts.append(
            dict(
                ref=ref,
                value=value,
                footprint="Lexx:" + foot,
                pins=nets,
                uuid=uid,
                xy=[round(x, 5), round(y, 5)],
                angle=round(angle % 360, 5),
                side="B",
                **(extra or {}),
            )
        )

    def occupy(shape, x, y, a):
        obstacles.append(pose(shape, x, y, a))

    # Identical bottom-contact ZIFs, with their mating side toward the cable exit.
    x, y = (sign * -27.0, 47.0) if finger else (sign * 20.25, 13.45)
    add("J1", "FH12-12S-0.5SH(55)", "FFC12", x, y, 0 if finger else -9 * sign, FLEX)
    occupy(box(-5.8, -2.65, 5.8, 4.5), x, y, 0 if finger else -9 * sign)
    if not finger:
        # USB edge lies at |X|=33.55, Y=0.5. The two hands use rotated, not reflected, modules.
        ax = sign * 90
        x, y = sign * 11, 0.5 - sign * 8.89
        # Carrier lands use Seeed's numbering. SWD and NFC test lands are omitted.
        nets = {
            "1": "R4",
            "2": "R0",
            "3": "R1",
            "4": "R2",
            "5": "C4",
            "6": "C5",
            "7": "R3",
            "8": "C3",
            "9": "C2",
            "10": "C1",
            "11": "C0",
            "12": None,
            "13": "GND",
            "14": None,
            "17": None,
            "18": "GND",
            "19": "VBAT_SW",
            "20": "GND",
        }
        add("U1", "Seeed XIAO nRF52840", "XIAO", x, y, ax, nets)
        occupy(box(0, -22.55, 17.78, 0), x, y, ax)
        x, y = sign * 28.4, -14
        add(
            "S1",
            "PCM12SMTR",
            "PowerSwitch",
            x,
            y,
            -ax,
            {"1": "BAT_POS", "2": "VBAT_SW", "3": None},
        )
        occupy(box(-4.4, -2.45, 4.4, 3.4), x, y, -ax)
        x, y = sign * 21, -42.5
        add("J2", "S2B-PH-SM4-TB", "Battery", x, y, 0, {"1": "BAT_POS", "2": "GND"})
        occupy(box(-4.7, -5, 4.7, 5.2), x, y, 0)
    centers = data["keys"]
    cols = sorted({k[0] for k in centers}, reverse=True)
    pending = []
    for idx, (sx, y, base) in enumerate(centers, 1):
        x = sign * sx
        col = cols.index(sx) if finger else idx - 1
        row = (
            (
                sorted(k[1] for k in centers if k[0] == sx).index(y)
                + (0 if col in (3, 4) else 1)
            )
            if finger
            else 0
        )
        number = idx if finger else 26 + idx
        local = f"K{number}"
        # Choice of 90-degree multiples preserves the MX cap axis. Select the
        # orientation with most clearance from the wall, posts and connectors.
        candidates = []
        for quarter in [0, 180, 90, 270]:
            angle = base * sign + quarter
            shape = pose(SOCKET, x, y, angle)
            if outline.covers(shape) and not any(
                shape.intersects(o) for o in obstacles
            ):
                score = min(
                    [
                        shape.distance(outline.boundary),
                        *[shape.distance(o) for o in obstacles],
                    ]
                )
                candidates.append((score, angle, shape))
        if not candidates:
            raise RuntimeError(f"No space for {name} SW{number} at {(x, y)}")
        _, angle, shape = max(candidates, key=lambda item: item[0])
        obstacles.append(shape)
        add(
            "SW" + str(number),
            "MX hot-swap",
            "MX",
            x,
            y,
            angle,
            {"1": f"C{col}", "2": local},
            {"row": row, "column": col},
        )
        pending.append((x, y, number, row, local))
    for x, y, number, row, local in pending:
        candidates = []
        for dy in (4.5, -4.5, 6.7, -6.7, 7.7, -7.7, 0):
            for dx in (0, 3, -3, 5.8, -5.8, 7.8, -7.8):
                for angle in (0, 90):
                    shape = pose(DIODE, x + dx, y + dy, angle)
                    if outline.contains(shape) and not any(
                        shape.distance(o) < 0.35 for o in obstacles
                    ):
                        score = math.hypot(dx, dy) + 0.1 * int(angle != 0)
                        candidates.append((score, dx, dy, angle, shape))
        if not candidates:
            raise RuntimeError(f"No space for diode {number}")
        _, dx, dy, angle, shape = min(candidates, key=lambda v: v[0])
        add(
            "D" + str(number),
            "1N4148W",
            "SOD123",
            x + dx,
            y + dy,
            angle,
            {"1": f"R{row}", "2": local},
        )
        obstacles.append(shape)
    folder = PCB / name
    folder.mkdir(exist_ok=True)
    (folder / "circuit.json").write_text(json.dumps(parts, indent=2) + "\n")
    (folder / "outline.json").write_text(
        json.dumps(outlines(outline), separators=(",", ":")) + "\n"
    )


if __name__ == "__main__":
    for hand in ("left", "right"):
        for deck in ("finger", "thumb"):
            plan(hand, deck)
