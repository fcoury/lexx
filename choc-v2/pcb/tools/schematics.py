"""Generate editable KiCad schematics from the pad/net manifests used for routing."""
import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

PCB = Path(__file__).resolve().parents[1]
GRID = 1.27
SHEETS = ("left-finger", "left-thumb", "right-finger", "right-thumb")


def q(text):
    return json.dumps(str(text), ensure_ascii=False)


def coord(x, y):
    return f"{x * GRID:.3f} {y * GRID:.3f}"


def uid(key):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "urn:lexx:expanded-choc-v2:schematic:" + key))


def font(size=1.27, align="", hide=False):
    return (f"(effects (font (size {size} {size}))"
            + (f" (justify {align})" if align else "")
            + (" (hide yes)" if hide else "") + ")")


STROKE = '(stroke (width 0.254) (type default))'
FILL = '(fill (type none))'


def line(*points):
    pts = " ".join(f"(xy {coord(x, y)})" for x, y in points)
    return f"(polyline (pts {pts}) {STROKE} {FILL})"


@dataclass
class Pin:
    num: str
    name: str
    x: int
    y: int
    direction: int
    kind: str = "passive"
    length: int = 2

    def encode(self):
        return (f"(pin {self.kind} line (at {coord(self.x, -self.y)} {self.direction}) "
                f"(length {self.length * GRID}) (name {q(self.name)} {font(1.016)}) "
                f"(number {q(self.num)} {font(1.016)}))")


@dataclass
class Symbol:
    name: str
    ref: str
    pins: list
    graphics: list
    show_names: bool = False
    show_numbers: bool = True
    virtual: bool = False

    def encode(self, embed=False):
        ident = "Lexx:" + self.name if embed else self.name
        parts = [f'(symbol {q(ident)}',
                 '(pin_names (offset 0.762)' + (')' if self.show_names else ' (hide yes))')]
        if not self.show_numbers:
            parts.append('(pin_numbers (hide yes))')
        parts.extend([f'(exclude_from_sim no) (in_bom {"no" if self.virtual else "yes"}) '
                      f'(on_board {"no" if self.virtual else "yes"})',
                      f'(property "Reference" {q(self.ref)} (at 0 5.08 0) {font(hide=self.virtual)})',
                      f'(property "Value" {q(self.name)} (at 0 -5.08 0) {font(hide=self.virtual)})',
                      f'(property "Footprint" "" (at 0 0 0) {font(hide=True)})',
                      f'(property "Datasheet" "" (at 0 0 0) {font(hide=True)})',
                      f'(symbol {q(self.name + "_0_1")} {" ".join(self.graphics)})',
                      f'(symbol {q(self.name + "_1_1")} {" ".join(p.encode() for p in self.pins)})',
                      ')'])
        return "\n".join(parts)


def rect(left, top, right, bottom):
    return f'(rectangle (start {coord(left, -top)}) (end {coord(right, -bottom)}) {STROKE} (fill (type background)))'


def port(number, name, x, y, angle, kind="passive"):
    return Pin(str(number), name, x, y, angle, kind)


def symbols():
    key = Symbol("ChocV2", "SW", [port(1, "1", -4, 0, 0), port(2, "2", 4, 0, 180)],
                 [line((-2, 0), (-2, 0.75)), line((2, 0), (2, 0.75)),
                  line((-2.5, 1.5), (2.5, 1.5)), line((0, 1.5), (0, 2.5))])
    diode = Symbol("D", "D", [port(2, "A", -3, 0, 0), port(1, "K", 3, 0, 180)],
                   [line((-1, -1.1), (-1, 1.1), (1, 0), (-1, -1.1)),
                    line((1, -1.1), (1, 1.1))])
    ffc_pins = [port(i + 1, f"{i + 1}", -5, 2*i-11, 0) for i in range(12)]
    ffc = Symbol("FFC12", "J", ffc_pins, [rect(-3, -14, 4, 14)], True)
    xiao_names = ["3V3_OUT", "GND", "VBUS", "SWDIO", "SWCLK", "EN", "GND", "VBAT",
                  "GND", "NFC1", "NFC2"]
    xiao_types = ["power_out", "power_in", "power_in", "bidirectional", "input", "input",
                  "power_in", "power_in", "power_in", "bidirectional", "bidirectional"]
    mcu = Symbol("XIAO_nRF52840", "U", [
        *[port(i+1, f"D{i}", -12, 3*i-15, 0, "bidirectional") for i in range(11)],
        *[port(i+12, name, 12, 3*i-15, 180, xiao_types[i]) for i, name in enumerate(xiao_names) if i+12 not in (15,16,21,22)]
    ], [rect(-10, -18, 10, 18)], True)
    pwr_sw = Symbol("PowerSwitch", "SW",
                    [port(2, "COM", -4, 0, 0), port(1, "1", 4, -2, 180),
                     port(3, "3", 4, 2, 180)],
                    [line((-2, 0), (2, 1.75))])
    battery = Symbol("Battery", "BT", [port(1, "+", -5, -2, 0), port(2, "−", -5, 2, 0)],
                     [rect(-3, -4, 3, 4)], True)
    flag = Symbol("ExternalPower", "#FLG", [Pin("1", "~", 0, 0, 90, "power_out", 0)],
                  [line((0, 0), (0, 2), (-1.5, 3), (0, 4), (1.5, 3), (0, 2))],
                  False, False, True)
    return {item.name: item for item in (key, diode, ffc, mcu, pwr_sw, battery, flag)}


LIB = symbols()


class Drawing:
    def __init__(self, board, parts):
        self.board = board
        self.parts = parts
        self.items = []
        self.used = set()
        self.placed = set()
        self.sheet_id = uid(board)
        self.sequence = 0

    def id(self):
        self.sequence += 1
        return uid(f"{self.board}:{self.sequence}")

    def text(self, x, y, text, size=1.6):
        self.items.append(f'(text {q(text)} (exclude_from_sim no) (at {coord(x, y)} 0) '
                          f'{font(size, "left")} (uuid "{self.id()}"))')

    def wire(self, p1, p2):
        if p1 != p2:
            self.items.append(f'(wire (pts (xy {coord(*p1)}) (xy {coord(*p2)})) '
                              f'(stroke (width 0) (type default)) (uuid "{self.id()}"))')

    def junction(self, p):
        self.items.append(f'(junction (at {coord(*p)}) (diameter 0) (color 0 0 0 0) '
                          f'(uuid "{self.id()}"))')

    def label(self, at, net, facing_left=False, size=1.016):
        angle, align = (0, "left") if not facing_left else (180, "right")
        self.items.append(f'(global_label {q(net)} (shape passive) (at {coord(*at)} {angle}) '
                          f'{font(size, align)} (uuid "{self.id()}"))')

    def nc(self, point):
        self.items.append(f'(no_connect (at {coord(*point)}) (uuid "{self.id()}"))')

    def part(self, lib, part, x, y, ref_at, value_at=None):
        self.used.add(lib)
        self.placed.add(part["ref"])
        sym = LIB[lib]
        on_board = "no" if sym.virtual else "yes"
        ref, value, footprint = part["ref"], part["value"], part["footprint"]
        instance_id = str(part["uuid"])
        self.items.append(
            f'(symbol (lib_id "Lexx:{lib}") (at {coord(x,y)} 0) (unit 1) '
            f'(exclude_from_sim no) (in_bom {on_board}) (on_board {on_board}) (dnp no) '
            f'(uuid "{instance_id}") '
            f'(property "Reference" {q(ref)} (at {coord(*ref_at)} 0) {font(hide=sym.virtual)}) '
            f'(property "Value" {q(value)} (at {coord(*(value_at or (x,y)))} 0) '
            f'{font(1.016, hide=value_at is None)}) '
            f'(property "Footprint" {q(footprint)} (at {coord(x,y)} 0) {font(hide=True)}) '
            f'(property "Datasheet" "" (at {coord(x,y)} 0) {font(hide=True)}) '
            f'(instances (project {q(self.board)} (path "/{self.sheet_id}" '
            f'(reference {q(ref)}) (unit 1)))))')

    def draw_matrix(self, pairs, finger):
        self.text(22, 23, "Finger matrix" if finger else "Three-key thumb fan", 2.5)
        self.text(22, 27, "Column drives the Choc V2 socket. The diode band (K, pad 1) faces the row.")
        self.text(22, 30, "Columns count outward from the hinge. R1 is the nearest full finger row.")
        self.text(22, 33, "Each branch uses one Choc V2 hot-swap socket and one 1N4148W diode.", 1.27)
        cols = {}
        rows = {}
        for row, col, sw, diode, col_net, row_net, middle in pairs:
            x = 31 + 39*col
            y = 47 + (4-row)*25 if finger else 47
            bus, end = (x, y), (x+31, y+9)
            self.part("ChocV2", sw, x+7, y, (x+7,y-4))
            self.part("D", diode, x+23, y, (x+23,y-4))
            self.wire(bus, (x+3,y))
            self.wire((x+11,y), (x+14,y))
            self.wire((x+14,y), (x+20,y))
            self.wire((x+14,y), (x+14,y+5))
            self.junction((x+14,y))
            self.label((x+14,y+5), middle)  # below the components, clear of pin numbers
            self.wire((x+26,y), (x+31,y))
            self.wire((x+31,y), end)
            cols.setdefault(col_net, []).append(bus)
            rows.setdefault(row_net, []).append(end)
        for net, points in cols.items():
            pts = sorted(points, key=lambda p: p[1])
            start = (pts[0][0],40)
            self.label(start, net)
            for pt in pts:
                self.wire(start, pt)
                if pt != pts[-1]:
                    self.junction(pt)
                start = pt
        for net, points in rows.items():
            pts = sorted(points)
            start = (21, pts[0][1])
            self.label(start, net, True)
            for pt in pts:
                self.wire(start, pt)
                if pt != pts[-1]:
                    self.junction(pt)
                start = pt

    def terminal_part(self, lib, part, x, y, ref_offset, value_offset, flags=False):
        reference = (x, y+ref_offset)
        self.part(lib, part, x, y, reference, (x, y+value_offset) if value_offset else None)
        pins = part["pins"]
        valid = {p.num for p in LIB[lib].pins}
        unknown = set(pins) - valid
        if unknown:
            raise ValueError(f"{part['ref']} has unknown pins {unknown}")
        flagged = set()
        for pin in LIB[lib].pins:
            origin = (x + pin.x, y + pin.y)
            net = pins.get(pin.num)
            if not net:
                self.nc(origin)
                continue
            dx = -1 if pin.x < 0 else 1
            end = (origin[0] + 7*dx, origin[1])
            self.wire(origin, end)
            self.label(end, net, dx<0)
            if flags and pin.kind == "power_in":
                flagged.add(net)
        for i, net in enumerate(sorted(flagged)):
            # Document the two externally energized supply rails in the power section.
            tip = (232+i*32, 151)
            label_at = (tip[0],tip[1]+2)
            flag_ref = f"#FLG0{i+1:02d}"
            self.part("ExternalPower", {"ref":flag_ref, "value":"External supply",
                      "footprint":"", "uuid":uid(self.board+flag_ref)}, *tip, tip)
            self.wire(tip, label_at)
            self.label(label_at, net)
        if flagged:
            self.text(222, 141, "Supply rails energized by the external cell", 1.27)

    def save(self, directory):
        missing = {p["ref"] for p in self.parts} - self.placed
        if missing:
            raise ValueError(f"{self.board}: missing symbols {missing}")
        heading = self.board.replace("-", " ").title()
        lib = "\n".join(LIB[k].encode(True) for k in sorted(self.used))
        body = "\n".join(self.items)
        path = directory / (self.board + ".kicad_sch")
        path.write_text(f'''(kicad_sch (version 20250114) (generator eeschema)
 (uuid "{self.sheet_id}") (paper "A3")
 (title_block (title "Lexx expanded Choc V2 — {heading}") (rev "A") (company "Lexx")
  (comment 1 "58-key wireless split keyboard • 29 keys per hand"))
 (lib_symbols {lib})
 {body}
 (sheet_instances (path "/" (page "1")))
)\n''')
        project = directory / (self.board + ".kicad_pro")
        if not project.exists():
            project.write_text(json.dumps({"meta": {"filename": project.name, "version": 1}}, indent=2)+"\n")
        (directory/"fp-lib-table").write_text(
            '(fp_lib_table (version 7)\n'
            ' (lib (name "Lexx")(type "KiCad")(uri "${KIPRJMOD}/../Lexx.pretty")(options "")(descr "Lexx expanded Choc V2"))\n)\n')
        (directory/"sym-lib-table").write_text(
            '(sym_lib_table (version 7)\n'
            ' (lib (name "Lexx")(type "KiCad")(uri "${KIPRJMOD}/../Lexx.kicad_sym")(options "")(descr "Lexx switch matrix and interconnect"))\n)\n')


def circuit(board, parts):
    """Identify each series path from pad nets rather than switch numbering."""
    drawing = Drawing(board, parts)
    finger = board.endswith("finger")
    remaining = []
    keys, diodes = [], {}
    for part in parts:
        name = part["footprint"].split(":")[-1]
        if name == "ChocV2":
            keys.append(part)
        elif name == "SOD123":
            diodes[part["pins"]["2"]] = part
        else:
            remaining.append(part)
    pairs = []
    for sw in keys:
        col_net, middle = sw["pins"]["1"], sw["pins"]["2"]
        diode = diodes.pop(middle)
        row_net = diode["pins"]["1"]
        col, row = (int(re.search(r"\d+$", net).group()) for net in (col_net,row_net))
        pairs.append((row,col,sw,diode,col_net,row_net,middle))
    assert not diodes
    drawing.draw_matrix(pairs, finger)
    drawing.text(22, 13, f"LEXX   /   EXPANDED CHOC V2   /   {board.replace('-', ' ').upper()}", 3.5)
    drawing.text(22, 18, "Passive finger board" if finger else "Wireless controller and moving thumb board", 1.8)
    if finger:
        drawing.text(273, 24, "Hinge cable", 2.5)
        drawing.text(273, 29, "Contact 1 mates with contact 1.", 1.27)
    else:
        drawing.text(32, 78, "Hinge cable", 2.5)
        drawing.text(118, 78, "XIAO nRF52840", 2.5)
        drawing.text(222, 78, "Battery and switch", 2.5)
    for part in remaining:
        footprint = part["footprint"].split(":")[-1]
        if footprint == "FFC12":
            x,y = (294,67) if finger else (47,115)
            drawing.terminal_part("FFC12", part, x,y, -18,21)
        elif footprint == "XIAO":
            drawing.terminal_part("XIAO_nRF52840", part,147,115,-23,-20,flags=True)
        elif footprint == "PowerSwitch":
            drawing.terminal_part("PowerSwitch", part,249,124,-6,7)
        elif footprint == "Battery":
            drawing.terminal_part("Battery", part,249,101,-7,7)
        else:
            raise ValueError((part["ref"], footprint))
    return drawing


def main():
    (PCB/"Lexx.kicad_sym").write_text('(kicad_symbol_lib (version 20241209) (generator kicad_symbol_editor)\n'
                                     + '\n'.join(s.encode() for s in LIB.values())+'\n)\n')
    for board in SHEETS:
        directory = PCB/board
        parts = json.loads((directory/"circuit.json").read_text())
        if isinstance(parts, dict):
            parts = parts["components"]
        circuit(board,parts).save(directory)


if __name__ == "__main__":
    main()
