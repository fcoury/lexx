"""Check the manufactured PG1353 drill pattern, assembled matrix and packed ZMK firmware.

Run with KiCad 10's Python. All coordinates are in millimeters. KiCad's board
view looks down on the keycaps, with the typist toward increasing Y.
"""

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import struct
from zipfile import ZipFile

import pcbnew as k

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PCB = ROOT / "pcb"
BOARD_NAMES = ("left-finger", "right-finger", "left-thumb", "right-thumb")
NM_TO_MM = 1e-6
CAD_TOL = 0.002
DRILL_TOL = 0.00072  # 3-decimal millimeter Excellon, rounded in each axis


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def xy(v):
    return (v.x * NM_TO_MM, v.y * NM_TO_MM)


def segment_error(a, b):
    """Compare two unoriented round-ended CNC moves."""
    return min(max(math.dist(a[0], b[i]), math.dist(a[1], b[1 - i])) for i in (0, 1))


def check_switch(fp, key, hand):
    ref = fp.GetReference()
    require(
        fp.GetFPIDAsString() == "Lexx:ChocV2" and fp.IsFlipped(), f"{ref}: expected underside ChocV2"
    )
    sign = 1 if hand == "left" else -1
    center = (150 + sign * float(key["left_x_mm"]), 100 - float(key["y_mm"]))
    angle = math.radians(sign * float(key["left_yaw_deg"]))
    c, s = math.cos(angle), math.sin(angle)

    def place(x, y):
        return (center[0] + x * c + y * s, center[1] - x * s + y * c)

    # Local coordinates below are TOP VIEW, LED toward the typist. They come
    # from the two Kailh drawings, independently of the native footprint's angle.
    # The stamp differs from the switch pin spacing by 0.10 mm. Center it between
    # those pins, splitting the nominal offset by 0.05 mm at each sleeve.
    expected = [
        (5.0, place(0, 0), place(0, 0)),
        (3.0, place(5, -3.75), place(5, -3.75)),
        (3.0, place(0, -5.95), place(0, -5.95)),
        (1.65, place(-5, 4.95), place(-5, 5.35)),
    ]
    holes = []
    for p in fp.Pads():
        if p.GetAttribute() == k.PAD_ATTRIB_NPTH:
            shape = p.GetEffectiveHoleShape()
            holes.append((k.ToMM(shape.GetWidth()), xy(shape.GetStart()), xy(shape.GetEnd())))
    require(len(holes) == 4 and len(list(fp.Pads())) == 6, f"{ref}: wrong hole/pad count")
    for width, start, end in expected:
        require(
            any(
                abs(w - width) < CAD_TOL and segment_error((a, b), (start, end)) < CAD_TOL
                for w, a, b in holes
            ),
            f"{ref}: misplaced or rotated {width:g} mm drill at {start}",
        )
    require(math.dist(xy(fp.GetPosition()), center) < CAD_TOL, f"{ref}: footprint origin misses stem")
    for number, local, net in (
        ("1", (8.245, -3.75), "C" + key["local_column"]),
        ("2", (-3.245, -5.95), "K" + ref[2:]),
    ):
        pad = fp.FindPadByNumber(number)
        require(
            pad is not None
            and pad.GetAttribute() == k.PAD_ATTRIB_SMD
            and pad.GetShape() == k.PAD_SHAPE_RECT
            and all(pad.IsOnLayer(layer) for layer in (k.B_Cu, k.B_Mask, k.B_Paste))
            and not pad.IsOnLayer(k.F_Cu)
            and pad.GetNetname() == net
            and math.dist(xy(pad.GetSize()), (2.6, 2.6)) < CAD_TOL
            and abs(math.remainder(pad.GetOrientationDegrees() - math.degrees(angle), 90)) < 0.01
            and math.dist(xy(pad.GetPosition()), place(*local)) < CAD_TOL,
            f"{ref}: land {number} differs from its signal, layer, shape or location",
        )
    return holes


def excellon(path, name):
    """Read absolute metric NPTH drill hits and G85 routed slots from the fab ZIP."""
    with ZipFile(path) as archive:
        lines = archive.read(name + "-NPTH.drl").decode("ascii").splitlines()
    require(
        "METRIC" in lines and "G90" in lines and any("NonPlated" in line for line in lines),
        f"{name}: expected absolute metric non-plated drill file",
    )
    tools = {}
    features = []
    tool = None
    coord = r"X(-?[0-9.]+)Y(-?[0-9.]+)"
    for line in lines:
        declaration = re.fullmatch(r"(T\d+)C([0-9.]+)", line)
        if declaration:
            tools[declaration[1]] = float(declaration[2])
        elif line in tools:
            tool = tools[line]
        elif line.startswith("X"):
            move = re.fullmatch(coord + "(?:G85" + coord + ")?", line)
            require(move is not None and tool is not None, f"{name}: unknown tool or move {line}")
            start = float(move[1]), -float(move[2])
            end = (float(move[3]), -float(move[4])) if move[3] else start
            features.append((tool, start, end))
    return features


def gerber_pads(archive_path, board, suffix):
    """Extract pad flash centers attributed to switches in KiCad's X2 output."""
    with ZipFile(archive_path) as archive:
        lines = archive.read(board + suffix).decode("ascii").splitlines()
    require(
        "%FSLAX46Y46*%" in lines and "%MOMM*%" in lines,
        f"{board}: unsupported Gerber coordinate format in {suffix}",
    )
    ref = ""
    pad = ""
    flashes = {}
    for line in lines:
        if line.startswith("%TO.C,") or line.startswith("%TO.P,"):
            fields = line[6:-2].split(",")
            ref = fields[0]
            pad = fields[1] if len(fields) > 1 else ""
        elif line == "%TD*%":
            ref = ""
        elif ref.startswith("SW") and line.endswith("D03*"):
            point = re.fullmatch(r"X(-?\d+)Y(-?\d+)D03\*", line)
            require(point, f"{board}: unsupported pad flash {line}")
            pos = (int(point[1]) * 1e-6, -int(point[2]) * 1e-6)
            flashes.setdefault((ref, pad), []).append(pos)
    return flashes


def check_plotted_lands(archive, name, keys, parts):
    copper = gerber_pads(archive, name, "-B_Cu.gbl")
    paste = gerber_pads(archive, name, "-B_Paste.gbp")
    count = 0
    for key in keys:
        ref = key["reference"]
        expected = [xy(parts[ref].FindPadByNumber(n).GetPosition()) for n in ("1", "2")]
        for i, pos in enumerate(expected, 1):
            hits = copper.get((ref, str(i)), [])
            require(
                len(hits) == 1 and math.dist(hits[0], pos) < CAD_TOL,
                f"{name}: incorrect solder land for {ref} pad {i}",
            )
        hits = paste.get((ref, ""), [])
        require(
            len(hits) == 2 and segment_error(expected, hits) < CAD_TOL,
            f"{name}: incorrect paste positions for {ref}",
        )
        count += 2
    return count


def fw_check():
    cfg = ROOT / "firmware/config"
    shield = cfg / "boards/shields/lexx"
    overlay = (shield / "lexx.dtsi").read_text()
    require('diode-direction = "col2row"' in overlay, "Wrong firmware scan direction")
    gpio = {}
    for direction in ("row", "col"):
        block = re.search(direction + r"-gpios\s*=\s*([^;]+);", overlay)[1]
        gpio[direction] = [int(v) for v in re.findall(r"&xiao_d\s+(\d+)", block)]
    require(len(gpio["row"]) == 5 and len(gpio["col"]) == 6, "Expected 5 row and 6 column GPIOs")
    offsets = {}
    names = (shield / "Kconfig.defconfig").read_text()
    require('default "Lexx Choc V2"' in names, "Unexpected Bluetooth device name")
    binaries = {}
    for hand in ("left", "right"):
        hand_overlay = (shield / f"lexx_{hand}.overlay").read_text()
        matches = re.findall(r"col-offset\s*=\s*<(\d+)>", hand_overlay)
        offsets[hand] = int(matches[0]) if matches else 0
        image = ROOT / "firmware/bin" / f"lexx_{hand}.uf2"
        raw = image.read_bytes()
        pages = len(raw) // 512
        require(len(raw) == pages * 512 and pages > 0, f"{hand}: invalid UF2 length")
        payload = bytearray()
        for i in range(pages):
            base = i * 512
            magic1, magic2, flags, addr, size, seq, count, family = struct.unpack_from("<8I", raw, base)
            require(
                (magic1, magic2, seq, count, family) == (0x0A324655, 0x9E5D5157, i, pages, 0xADA52840)
                and flags & 0x2000
                and 0 < size <= 476
                and raw[base + 508 : base + 512] == bytes.fromhex("306fb10a"),
                f"{hand}: invalid UF2 header or magic in block {i}",
            )
            payload.extend(raw[base + 32 : base + 32 + size])
        require(b"Lexx Choc V2\x00" in payload, f"{hand}: missing Choc firmware identity")
        binaries[hand] = sha256(image)
    require(offsets == {"left": 0, "right": 6}, "Incorrect split column offsets")
    require(binaries["left"] != binaries["right"], "Both firmware images are identical")
    transform = [tuple(map(int, p)) for p in re.findall(r"RC\((\d+),\s*(\d+)\)", overlay)]
    layers = re.findall(r"bindings\s*=\s*<([^>]+)>", (cfg / "lexx.keymap").read_text())
    require(len(layers) > 0 and all(l.count("&") == 58 for l in layers), "Wrong firmware layer size")
    return gpio, offsets, transform, len(layers), binaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--native-only", action="store_true", help="Skip fabrication ZIP checks before plotting"
    )
    parser.add_argument("--report", type=Path, help="Save the measured results as JSON")
    args = parser.parse_args()
    with (HERE / "key-centers.csv").open() as f:
        keys = list(csv.DictReader(f))
    gpio, offsets, transform, layers, binaries = fw_check()
    physical = []
    results = {}
    for name in BOARD_NAMES:
        hand, deck = name.split("-")
        path = PCB / name / (name + ".kicad_pcb")
        board = k.LoadBoard(str(path))
        require(
            board.GetCopperLayerCount() == 2
            and abs(k.ToMM(board.GetDesignSettings().GetBoardThickness()) - 1.6) < CAD_TOL,
            f"{name}: wrong layer count or thickness",
        )
        parts = {fp.GetReference(): fp for fp in board.GetFootprints()}
        these_keys = [key for key in keys if key["deck"] == deck]
        require(
            {r for r in parts if r.startswith("SW")} == {key["reference"] for key in these_keys},
            f"{name}: switch reference set differs from plate",
        )
        drills = []
        for key in these_keys:
            ref = key["reference"]
            fp = parts[ref]
            drills.extend(check_switch(fp, key, hand))
            diode = parts["D" + ref[2:]]
            row = int(key["local_row"])
            col = int(key["local_column"])
            require(
                diode.FindPadByNumber("1").GetNetname() == f"R{row}"
                and diode.FindPadByNumber("2").GetNetname() == "K" + ref[2:],
                f"{name} {ref}: disconnected diode path",
            )
            physical.append((-row, hand, xy(fp.GetPosition())[0], (row, col + offsets[hand])))
        for i, signal in enumerate([f"R{i}" for i in range(5)] + [f"C{i}" for i in range(6)], 1):
            require(parts["J1"].FindPadByNumber(str(i)).GetNetname() == signal, f"{name} J1 pin {i}")
        if deck == "thumb":
            for group, prefix in (("row", "R"), ("col", "C")):
                for index, gpio_num in enumerate(gpio[group]):
                    pin = parts["U1"].FindPadByNumber(str(gpio_num + 1))
                    require(pin.GetNetname() == f"{prefix}{index}", f"{name}: D{gpio_num} scan mismatch")
        result = dict(switches=len(these_keys), native_sha256=sha256(path))
        if not args.native_only:
            zip_path = PCB / "fabrication" / (name + "-fabrication.zip")
            exported = excellon(zip_path, name)
            worst = 0.0
            for width, a, b in drills:
                eligible = [
                    (segment_error((a, b), (p, q)), j)
                    for j, (w, p, q) in enumerate(exported)
                    if abs(w - width) < 0.0001
                ]
                require(eligible, f"{name}: no tool of width {width:g} for {a}")
                err, matched = min(eligible)
                require(err <= DRILL_TOL, f"{name}: fabrication drill {a} {b} differs by {err:.4f} mm")
                exported.pop(matched)
                worst = max(worst, err)
            result.update(
                archive_sha256=sha256(zip_path),
                fab_switch_features=len(drills),
                bottom_copper_and_paste_lands=check_plotted_lands(zip_path, name, these_keys, parts),
                worst_drill_endpoint_error_mm=round(worst, 7),
            )
        results[name] = result
        print(name, result["switches"], "south-facing patterns", flush=True)
    order = [key for _, _, _, key in sorted(physical)]
    require(order == transform and len(set(order)) == 58, "Mounted key order differs from ZMK transform")
    report = dict(
        boards=results, switch_positions=len(order), keymap_layers=layers, firmware_sha256=binaries
    )
    if args.report:
        args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(
        f"{len(order)} switch/diode paths, both flex cables, XIAO GPIOs and {layers} ZMK layers passed."
    )


if __name__ == "__main__":
    main()
