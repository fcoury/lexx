"""Generate assembly placements in the committed case's XY coordinate system."""

import json
import math
import uuid
from shapely.affinity import rotate, scale, translate
from shapely.geometry import Point, box
from shapely.ops import unary_union
from outline import ROOT, board

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
# Kailh socket lands in switch-local assembly coordinates before rotation.
MX_COPPER = unary_union([
    box(cx - 1.275, cy - 1.25, cx + 1.275, cy + 1.25)
    for cx, cy in ((7.085, -2.54), (-5.842, -5.08))
])
FINGER_J1_X = -20.0
FINGER_J1_Y = 52.0


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
    screws = data["screws"]
    if finger:
        screws = json.loads((PCB / "case/finger-posts.json").read_text())
        # A common board perimeter fits the asymmetrical solder lands in both hands.
        # Keep the key centers fixed and add laminate only near the constrained edges.
        envelope = SOCKET.buffer(0.10).union(MX_COPPER.buffer(0.60))
        additions = [outline]
        for kx, ky, yaw in data["keys"]:
            for mirrored in (1, -1):
                local = scale(envelope, xfact=mirrored, origin=(0, 0))
                additions.append(pose(local, sign * kx, ky, 180 + sign * yaw))
        # Support the rear flex socket, including its two soldered hold-downs.
        x, y = sign * FINGER_J1_X, FINGER_J1_Y
        additions.append(box(x - 5.7, y - 4.0, x + 5.7, y + 3.9).buffer(0.70))
        # Round narrow internal corners so a board mill can follow the profile.
        outline = unary_union(additions).buffer(0.9).buffer(-0.9).simplify(0.018)
    for x, y in screws:
        outline = outline.difference(Point(sign * x, y).buffer(2.85, quad_segs=12))
    if not finger:
        # Air below the onboard antenna, at the end opposite the USB connector.
        xs = sorted([sign * 9, sign * 15.3])
        ys = sorted([0.5 + sign * (u - 8.89) for u in (2.9, 9.5)])
        outline = outline.difference(box(xs[0], ys[0], xs[1], ys[1]))
    parts = []
    supports = json.loads((PCB / "case/supports.json").read_text())
    support_areas = [Point(sign * x, y).buffer(radius)
                     for x, y, radius in supports["fixed" if finger else "thumb"]]
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
    x, y = (sign * FINGER_J1_X, FINGER_J1_Y) if finger else (sign * 20.25, 13.45)
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
        # With this underside footprint the LED window faces local south at 180°.
        angle = 180 + base * sign
        shape = pose(SOCKET, x, y, angle)
        copper = pose(MX_COPPER, x, y, angle)
        if not outline.covers(copper.buffer(0.50)):
            raise ValueError(f"{name} SW{number} needs more laminate at its lands")
        if any(shape.distance(land) < 0.50 for land in support_areas):
            raise ValueError(f"{name} SW{number} interferes with a printed support")
        if any(shape.intersects(o) for o in obstacles):
            raise ValueError(f"{name} SW{number} conflicts with another component")
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
    obstacles.extend(support_areas)
    diode_area = outline.buffer(-0.50)
    for x, y, number, row, local in pending:
        candidates = []
        for dy in (4.5, -4.5, 6.7, -6.7, 7.7, -7.7, 0):
            for dx in (0, 3, -3, 5.8, -5.8, 7.8, -7.8):
                for angle in (0, 90):
                    shape = pose(DIODE, x + dx, y + dy, angle)
                    if diode_area.covers(shape) and not any(
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
