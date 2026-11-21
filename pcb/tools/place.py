"""Create an unrouted KiCad 10 board from a case-space assembly placement."""

import json
import sys
from pathlib import Path
import pcbnew as k
from sync_pins import sync

PCB = Path(__file__).resolve().parents[1]


def position(x, y):
    return k.VECTOR2I(k.FromMM(150 + x), k.FromMM(100 - y))


def make(name):
    folder = PCB / name
    parts = json.loads((folder / "circuit.json").read_text())
    board = k.BOARD()
    title = k.TITLE_BLOCK()
    title.SetTitle(f"Lexx Expanded MX — {name}")
    title.SetRevision("B")
    board.SetTitleBlock(title)
    board.SetCopperLayerCount(2)
    board.GetDesignSettings().SetBoardThickness(k.FromMM(1.6))
    nets = {}
    for label in sorted({v for p in parts for v in p["pins"].values() if v}):
        net = k.NETINFO_ITEM(board, label)
        board.Add(net)
        nets[label] = net
    rings = json.loads((folder / "outline.json").read_text())
    for idx, ring in enumerate(rings):
        if idx:
            # Isolated mounting bores are circles. Edge notches are in the exterior path.
            x = sum(p[0] for p in ring[:-1]) / (len(ring) - 1)
            y = sum(p[1] for p in ring[:-1]) / (len(ring) - 1)
            shape = k.PCB_SHAPE()
            shape.SetShape(k.SHAPE_T_CIRCLE)
            shape.SetCenter(position(x, y))
            shape.SetEnd(position(x + 2.85, y))
            shape.SetWidth(k.FromMM(0.05))
            shape.SetLayer(k.Edge_Cuts)
            board.Add(shape)
            continue
        for a, b in zip(ring, ring[1:]):
            shape = k.PCB_SHAPE()
            shape.SetShape(k.SHAPE_T_SEGMENT)
            shape.SetStart(position(*a))
            shape.SetEnd(position(*b))
            shape.SetWidth(k.FromMM(0.05))
            shape.SetLayer(k.Edge_Cuts)
            board.Add(shape)
    for part in parts:
        ref = part["ref"]
        fp = k.FootprintLoad(str(PCB / "Lexx.pretty"), part["footprint"].split(":")[1])
        board.Add(fp)
        fp.SetFPIDAsString(part["footprint"])
        path = k.KIID_PATH()
        path.append(k.KIID(part["uuid"]))
        fp.SetPath(path)
        fp.SetReference(ref)
        fp.SetValue(part["value"])
        fp.SetPosition(position(*part["xy"]))
        if part["side"] == "B":
            fp.Flip(fp.GetPosition(), k.FLIP_DIRECTION_TOP_BOTTOM)
        fp.SetOrientationDegrees(part["angle"])
        # Dense socket backs leave space on the other side for the assembly references.
        fp.Reference().SetVisible(False)
        if not ref.startswith("SW"):
            fp.SetAttributes(fp.GetAttributes() | k.FP_SMD)
        for pad in fp.Pads():
            net = part["pins"].get(pad.GetNumber())
            if net:
                pad.SetNet(nets[net])
        # Top-layer identifiers remain visible during socket/diode assembly.
        if ref.startswith("D") or ref in ("J1", "J2", "S1", "U1"):
            labels = ref
            x, y = part["xy"]
            if ref == "J1":
                y -= 3.0
            if ref == "J2":
                labels = "J2  1+  2-"
            if ref == "U1":
                x = 21 if name.startswith("left") else -21
            t = k.PCB_TEXT(board)
            t.SetText(labels)
            t.SetPosition(position(x, y))
            t.SetTextSize(k.VECTOR2I(k.FromMM(0.85), k.FromMM(0.85)))
            t.SetTextThickness(k.FromMM(0.15))
            t.SetLayer(k.F_SilkS)
            board.Add(t)
    hand, deck = name.split("-")
    x, y = (-49, 37) if deck == "finger" else (21, -24)
    label = k.PCB_TEXT(board)
    label.SetText(f"LX-{hand[0].upper()}{deck[0].upper()}-B")
    label.SetPosition(position(x if hand == "left" else -x, y))
    label.SetTextSize(k.VECTOR2I(k.FromMM(1.02), k.FromMM(1.02)))
    label.SetTextThickness(k.FromMM(0.16))
    label.SetLayer(k.F_SilkS)
    board.Add(label)
    path = folder / (name + ".kicad_pcb")
    if path.exists():
        raise SystemExit(
            f"{path} exists; move the previous PCB before regenerating placement."
        )
    sync(board, path.with_suffix(".kicad_sch"))
    if not k.SaveBoard(str(path), board):
        raise RuntimeError(path)


if __name__ == "__main__":
    for name in sys.argv[1:]:
        make(name)
