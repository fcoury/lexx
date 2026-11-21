"""Trace the manufactured keyboard's logical wiring through the firmware and four schematics."""

import os
import json
from pathlib import Path
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware" / "config"
SHIELD = FIRMWARE / "boards" / "shields" / "lexx"


def schematic_pins(board, directory):
    output = directory / (board + ".xml")
    subprocess.run(
        [
            os.environ.get("KICAD_CLI", "kicad-cli"),
            "sch",
            "export",
            "netlist",
            "--format",
            "kicadxml",
            "-o",
            str(output),
            str(ROOT / board / (board + ".kicad_sch")),
        ],
        check=True,
    )
    return {
        (p.get("ref"), p.get("pin")): net.get("name")
        for net in ET.parse(output).findall("./nets/net")
        for p in net.findall("node")
    }


def require(condition, detail):
    if not condition:
        raise ValueError(detail)


def main():
    overlay = (SHIELD / "lexx.dtsi").read_text()
    require(
        'diode-direction = "col2row"' in overlay,
        "Firmware scan direction differs from diode direction",
    )
    transform = [
        tuple(map(int, pair)) for pair in re.findall(r"RC\((\d+),\s*(\d+)\)", overlay)
    ]
    layout = json.loads((ROOT.parent / "validation/design.json").read_text())["Expanded"]
    scanned = set()
    physical = []
    with tempfile.TemporaryDirectory() as tmp:
        for hand in ("left", "right"):
            thumb = schematic_pins(hand + "-thumb", Path(tmp))
            finger = schematic_pins(hand + "-finger", Path(tmp))
            right_offset = re.search(
                r"col-offset\s*=\s*<(\d+)>",
                (SHIELD / f"lexx_{hand}.overlay").read_text(),
            )
            offset = int(right_offset.group(1)) if right_offset else 0
            for direction, prefix in (("row", "R"), ("col", "C")):
                group = re.search(direction + r"-gpios\s*=\s*([^;]+);", overlay).group(
                    1
                )
                for idx, gpio in enumerate(re.findall(r"&xiao_d\s+(\d+)", group)):
                    # The Seeed carrier numbers D0 as pad 1 and D10 as pad 11.
                    net = thumb["U1", str(int(gpio) + 1)]
                    require(net == f"{prefix}{idx}", f"{hand} XIAO D{gpio}: {net}")
            for pin in range(1, 12):
                pair = ("J1", str(pin))
                require(finger[pair] == thumb[pair], f"{hand} flex pin {pin} mismatch")
            for num in range(1, 30):
                pins = finger if num <= 26 else thumb
                sw, diode = f"SW{num}", f"D{num}"
                require(
                    pins[sw, "2"] == pins[diode, "2"],
                    f"{hand} {sw} diode anode mismatch",
                )
                row, col = pins[diode, "1"], pins[sw, "1"]
                require(
                    row.startswith("R") and col.startswith("C"),
                    f"{hand} {sw} matrix polarity",
                )
                matrix_key = (int(row[1:]), offset + int(col[1:]))
                require(
                    matrix_key not in scanned,
                    f"{hand} {sw} duplicate position {matrix_key}",
                )
                scanned.add(matrix_key)
                key = (layout["fixed"]["keys"][num-1] if num <= 26
                       else layout["thumb"]["keys"][num-27])
                x = key[0] if hand == "left" else -key[0]
                # The keymap reads each row from the far-left finger to the far-right
                # finger. The last row includes the two forward finger positions.
                physical.append((-matrix_key[0], hand, x, matrix_key))
    require(
        len(transform) == 58 and set(transform) == scanned,
        "Key transform differs from populated matrix",
    )
    require(
        transform == [key for _, _, _, key in sorted(physical)],
        "Firmware transform order differs from the mounted keys in the two halves",
    )
    layers = re.findall(
        r"bindings\s*=\s*<([^>]+)>", (FIRMWARE / "lexx.keymap").read_text()
    )
    for entries in layers:
        require(entries.count("&") == len(transform), "Wrong number of key bindings")
    print(
        f"Verified {len(scanned)} switch/diode paths, both 11-line flex links and {len(layers)} firmware layers."
    )


if __name__ == "__main__":
    main()
