"""Check the real MX drills, socket pads, plate centers and matrix position on each board.

Run with KiCad 10's Python (pcbnew). Optional arguments are native .kicad_pcb files.
Coordinates here use the keycap view, with the typist toward positive KiCad Y.
"""

import argparse
import json
import math
from pathlib import Path

import pcbnew as k

PCB = Path(__file__).resolve().parents[1]
TOLERANCE = 0.002  # mm, accommodates KiCad coordinate rounding


def xy(vector):
    return k.ToMM(vector.x), k.ToMM(vector.y)


def mx_drills(fp):
    """Return drill circles and the unit vector toward the switch's LED window.

    The CHERRY MX Series PCB layout puts the window opposite both contacts.
    The two locating pegs define the lateral axis, including on angled thumb keys.
    """
    holes = [(xy(p.GetPosition()), k.ToMM(p.GetDrillSizeX()) / 2)
             for p in fp.Pads() if p.GetAttribute() == k.PAD_ATTRIB_NPTH]
    pegs = [p for p, r in holes if math.isclose(2*r, 1.9)]
    contacts = [p for p, r in holes if math.isclose(2*r, 3.0)]
    stems = [p for p, r in holes if math.isclose(2*r, 4.1)]
    if (len(holes), len(pegs), len(contacts), len(stems)) != (5, 2, 2, 1):
        raise ValueError(f"{fp.GetReference()}: unexpected MX drill pattern")
    stem = stems[0]
    dx, dy = pegs[1][0] - pegs[0][0], pegs[1][1] - pegs[0][1]
    span = math.hypot(dx, dy)
    if abs(span - 10.16) > TOLERANCE:
        raise ValueError(f"{fp.GetReference()}: MX locating pegs are {span:.3f} mm apart")
    direction = (-dy/span, dx/span)
    depths = [(p[0]-stem[0])*direction[0] + (p[1]-stem[1])*direction[1] for p in contacts]
    if all(d > 0 for d in depths):
        direction = (-direction[0], -direction[1])
    elif any(d >= 0 for d in depths):
        raise ValueError(f"{fp.GetReference()}: contact holes straddle locating pegs")
    return stem, holes, direction


def verify(board_path, layout):
    hand, deck = board_path.stem.split("-")
    if hand not in ("left", "right") or deck not in ("finger", "thumb"):
        raise ValueError(f"Unknown board name {board_path.stem}")
    sign = 1 if hand == "left" else -1
    keys = layout["fixed" if deck == "finger" else "thumb"]["keys"]
    by_column = sorted({x for x, _, _ in keys}, reverse=True)
    first_ref = 1 if deck == "finger" else 27
    board = k.LoadBoard(str(board_path.resolve()))
    footprints = {f.GetReference(): f for f in board.GetFootprints()}
    expected = {f"SW{i}" for i in range(first_ref, first_ref + len(keys))}
    actual = {ref for ref in footprints if ref.startswith("SW")}
    if actual != expected:
        raise ValueError(f"{board_path.stem}: unexpected switch references {actual ^ expected}")

    failures = []
    for idx, (x, y, yaw) in enumerate(keys):
        num = first_ref + idx
        ref = f"SW{num}"
        fp = footprints[ref]
        if fp.GetFPIDAsString() != "Lexx:MX" or not fp.IsFlipped():
            raise ValueError(f"{board_path.stem} {ref}: expected underside Lexx:MX socket")
        center, holes, led = mx_drills(fp)
        expected_center = (150 + sign*x, 100-y)
        if math.dist(center, expected_center) > TOLERANCE:
            raise ValueError(f"{board_path.stem} {ref}: stem misses the plate center")
        radians = math.radians(sign*yaw)
        towards_typist = math.sin(radians), math.cos(radians)
        if math.dist(led, towards_typist) > 0.0001:
            failures.append(ref)

        # Check the asymmetric contact drills and stamped socket lands against the
        # physical pattern in its measured axes. This also catches a mirrored socket.
        def target(lateral, forward):
            return (center[0] + lateral*led[1] + forward*led[0],
                    center[1] - lateral*led[0] + forward*led[1])

        for lateral, forward, diameter in ((-5.08,0,1.9), (5.08,0,1.9),
                                           (2.54,-5.08,3), (-3.81,-2.54,3)):
            if not any(math.dist(p,target(lateral,forward)) <= TOLERANCE and
                       math.isclose(2*r,diameter) for p, r in holes):
                raise ValueError(f"{board_path.stem} {ref}: mirrored or displaced MX drill")

        column = by_column.index(x) if deck == "finger" else idx
        rows = sorted(sy for sx, sy, _ in keys if sx == x)
        row = rows.index(y) + int(column not in (3,4)) if deck == "finger" else 0
        local_net = f"K{num}"
        for pin, lateral, forward, net in (("1",-7.085,-2.54,f"C{column}"),
                                            ("2",5.842,-5.08,local_net)):
            pad = fp.FindPadByNumber(pin)
            if (not pad or pad.GetAttribute() != k.PAD_ATTRIB_SMD or
                    not pad.IsOnLayer(k.B_Cu) or pad.GetNetname() != net or
                    math.dist(xy(pad.GetPosition()),target(lateral,forward)) > TOLERANCE):
                raise ValueError(f"{board_path.stem} {ref}: socket land {pin} differs from {net}")
        diode = footprints[f"D{num}"]
        if (diode.FindPadByNumber("1").GetNetname() != f"R{row}" or
                diode.FindPadByNumber("2").GetNetname() != local_net):
            raise ValueError(f"{board_path.stem} D{num}: diode pins differ from this key's matrix")
    if failures:
        raise ValueError(f"{board_path.stem}: {len(failures)}/{len(keys)} windows face away "
                         f"from their local south direction: {', '.join(failures)}")
    return len(keys)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("boards", nargs="*", type=Path)
    args = parser.parse_args()
    paths = args.boards or [PCB / name / (name + ".kicad_pcb")
                            for name in ("left-finger","left-thumb","right-finger","right-thumb")]
    layout = json.loads((PCB.parent/"validation/design.json").read_text())["Expanded"]
    failed = False
    for path in paths:
        try:
            count = verify(path, layout)
            print(f"{path.stem}: {count} south-facing MX patterns, plate centers and matrix paths verified.")
        except ValueError as exc:
            print(exc)
            failed = True
    raise SystemExit(int(failed))
