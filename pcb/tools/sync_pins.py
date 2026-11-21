"""Synchronize KiCad's schematic pin attributes, including intentional no-connects.

Run this with KiCad's Python interpreter and pass one or more .kicad_pcb paths.
The matching schematic must be beside each board. Existing copper is preserved.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from xml.etree import ElementTree

import pcbnew


def sync(board, schematic):
    cli = os.environ.get("KICAD_CLI") or shutil.which("kicad-cli")
    if not cli:
        raise RuntimeError("Set KICAD_CLI to the kicad-cli executable.")
    with TemporaryDirectory() as tmp:
        exported = Path(tmp)/"matrix.xml"
        subprocess.run([cli, "sch", "export", "netlist", "--format", "kicadxml",
                        "-o", str(exported), str(schematic)], check=True)
        tree = ElementTree.parse(exported)
    nodes = {}
    for net in tree.findall("./nets/net"):
        for node in net.findall("node"):
            nodes[node.get("ref"),node.get("pin")] = (net.get("name"), node)
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            number = pad.GetNumber()
            if number == "MP" and fp.GetReference() in {"J1", "J2"}:
                # Early placements numbered the isolated mechanical hold-downs.
                pad.SetNumber("")
                pad.SetNetCode(0)
                pad.SetPinType("")
                pad.SetPinFunction("")
                continue
            if not number:  # Mechanical pad or NPTH.
                continue
            name, node = nodes[fp.GetReference(), number]
            pin_type = node.get("pintype", "")
            if pin_type.endswith("+no_connect"):
                if pad.GetNetname() not in ("",name):
                    raise ValueError(f"Unexpected existing net on {fp.GetReference()}.{number}")
                net = board.FindNet(name)
                if not net:
                    net = pcbnew.NETINFO_ITEM(board, name)
                    board.Add(net)
                pad.SetNet(net)
            elif pad.GetNetname() != name:
                raise ValueError(f"{fp.GetReference()}.{number}: PCB has {pad.GetNetname()}, schematic has {name}")
            pad.SetPinType(pin_type)
            pad.SetPinFunction(node.get("pinfunction", ""))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("boards", nargs="+", type=Path)
    for board_path in parser.parse_args().boards:
        board = pcbnew.LoadBoard(str(board_path))
        sync(board, board_path.with_suffix(".kicad_sch"))
        if not pcbnew.SaveBoard(str(board_path), board):
            raise RuntimeError(f"Could not save {board_path}")


if __name__ == "__main__":
    main()
