"""Route a placed board with FreeRouting, run KiCad DRC and export a bare PCB.

Run this with the KiCad 10 Python interpreter (pcbnew module). FREEROUTING_JAR
may point to the FreeRouting 2.5.0 distribution JAR. Alternatively, set
FREEROUTING_CLI to a working CLI launcher. KICAD_CLI overrides kicad-cli.
Omit --route to check and plot the finished design.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile

import pcbnew


LAYERS = "F.Cu,B.Cu,F.Mask,B.Mask,F.Silkscreen,B.Silkscreen,F.Paste,B.Paste,Edge.Cuts"


def command(name, env):
    path = os.environ.get(env) or shutil.which(name)
    if not path:
        raise SystemExit(f"Set {env} to the path of {name}.")
    return path


def route(board_path, work):
    board = pcbnew.LoadBoard(str(board_path))
    if next(iter(board.GetTracks()), None) is not None:
        raise SystemExit("Routing requires a freshly placed board. Omit --route to plot the existing copper.")
    # The router approximates rotated, closely spaced rectangular connector
    # pads as enlarged octagons. Align the FFC with its grid for the interchange
    # only. The original component positions and perimeter stay untouched.
    connector = board.FindFootprintByReference("J1")
    angle = -(connector.GetOrientationDegrees() % 90) if connector else 0
    origin = connector.GetPosition() if connector else pcbnew.VECTOR2I(0, 0)
    def rotation(deg):
        return pcbnew.EDA_ANGLE(deg, pcbnew.DEGREES_T)
    if angle:
        for item in [*board.GetFootprints(), *board.GetDrawings(), *board.GetTracks(), *board.Zones()]:
            item.Rotate(origin, rotation(angle))
    dsn = work / "design.dsn"
    ses = work / "routed.ses"
    if not pcbnew.ExportSpecctraDSN(board, str(dsn)):
        raise RuntimeError("KiCad failed to export DSN")
    # KiCad exports internal milled openings as generic Specctra keepouts.
    # Contract the temporary routing boundary so these cuts also preserve the
    # half-millimetre copper setback. Keep the real fabrication edges intact.
    area = pcbnew.SHAPE_POLY_SET()
    if not board.GetBoardPolygonOutlines(area, False):
        raise RuntimeError("Board has an open outline")
    cutouts = area.HoleCount(0)
    area.Inflate(pcbnew.FromMM(-0.55), pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS, pcbnew.FromMM(0.02))
    if area.OutlineCount() != 1:
        raise RuntimeError("Board needs a single continuous routing region")
    def coordinates(ring):
        points = [ring.CPoint(i) for i in range(ring.PointCount())]
        return " ".join(f"{p.x / 1000:.2f} {-p.y / 1000:.2f}" for p in [*points, points[0]])
    region = "    (boundary (path pcb 0 " + coordinates(area.COutline(0)) + "))\n"
    for hole in range(area.HoleCount(0)):
        region += '    (keepout "" (polygon signal 0 ' + coordinates(area.CHole(0, hole)) + '))\n'
    raw = dsn.read_text()
    # This replaces the board boundary and its cutouts only. Footprint hole
    # keepouts are in the library/images section after the structure block.
    polygon_points = r"[-+\d.eE\s]+"
    routing_edges = (rf"    \(boundary\s+\(path pcb 0 {polygon_points}\)\s*\)\s*"
                     + rf'(?:\(keepout "" \(polygon signal 0 {polygon_points}\)\)\s*)' + f"{{{cutouts}}}")
    raw, count = re.subn(routing_edges, lambda _: region, raw, count=1)
    if count != 1 or "(unit um)" not in raw:
        raise RuntimeError("Unexpected KiCad DSN units or boundary")
    # KiCad's Specctra interchange describes a milled oblong NPTH as a
    # copper pin. Reserve its full cutter clearance on both layers instead.
    # The guard circle encloses the 2.05 mm slot and a 0.55 mm offset.
    retention = r"\(pin Oval\[A\]Pad_1650\.0+x2050\.0+_um @\d+ ([-.\d]+) ([-.\d]+)\)"
    raw = re.sub(retention, lambda m: " ".join(
        f'(keepout "" (circle {layer} 3150 {m[1]} {m[2]}))' for layer in ("F.Cu", "B.Cu")
    ), raw)
    dsn.write_text(raw)
    jvm_home = f"-Duser.home={work}"
    if os.environ.get("FREEROUTING_JAR"):
        launcher = [command("java", "JAVA"), "-Xmx2g", "-Djava.awt.headless=true",
                    jvm_home, "-cp", os.environ["FREEROUTING_JAR"], "app.freerouting.cli.FreeroutingCli"]
    else:
        launcher = [command("freerouting-cli", "FREEROUTING_CLI"), jvm_home]
    subprocess.run(
        [*launcher, "-da", "-de", str(dsn), "-do", str(ses), "--router.autorouter.max_passes=35",
         "--router.optimizer.enabled=false", "--router.fanout.enabled=false",
         "--router.automatic_neckdown=false", "--router.neck_width_um=0"],
        check=True,
    )
    if not ses.exists() or not pcbnew.ImportSpecctraSES(board, str(ses)):
        raise RuntimeError("KiCad failed to import routed session")
    if angle:
        original = pcbnew.LoadBoard(str(board_path))
        for track in board.GetTracks():
            copied = track.Duplicate()
            copied.Rotate(origin, rotation(-angle))
            copied.SetNet(original.FindNet(track.GetNetname()))
            original.Add(copied)
        board = original
    if not pcbnew.SaveBoard(str(board_path), board):
        raise RuntimeError("KiCad failed to save imported tracks")


def plot(board_path, out, work):
    cli = command("kicad-cli", "KICAD_CLI")
    report = out / (board_path.stem + "-drc.json")
    parity = ["--schematic-parity"] if board_path.with_suffix(".kicad_sch").exists() else []
    subprocess.run([cli, "pcb", "drc", "--format", "json", "--severity-all",
                    *parity, "-o", str(report), str(board_path)], check=True)
    drc = json.loads(report.read_text())
    issues = drc["violations"]
    open_nets = drc["unconnected_items"]
    mismatches = drc["schematic_parity"]
    if issues or open_nets or mismatches:
        raise SystemExit(f"DRC for {board_path.name}: {len(issues)} design-rule violations, {len(open_nets)} open connections, "
                         f"{len(mismatches)} schematic mismatches. See {report}.")
    layers = work / "layers"
    layers.mkdir()
    subprocess.run([cli, "pcb", "export", "gerbers", "--layers", LAYERS,
                    "-o", str(layers), str(board_path)], check=True)
    subprocess.run([cli, "pcb", "export", "drill", "--format", "excellon",
                    "--excellon-separate-th", "-o", str(layers), str(board_path)], check=True)
    # KiCad silently skips disabled layers. Catch missing copper or masks before
    # packaging, even if a hand-edited board lacked an enabled layer.
    required = {".gtl", ".gbl", ".gts", ".gbs", ".gtp", ".gbp", ".gto", ".gbo", ".gm1", ".drl"}
    missing = required - {layer.suffix for layer in layers.iterdir()}
    if missing:
        raise SystemExit(f"Missing fabrication layers for {board_path.name}: {sorted(missing)}")
    subprocess.run([cli, "pcb", "export", "pos", "--format", "csv", "--units", "mm",
                    "--exclude-dnp", "-o", str(out / (board_path.stem + "-positions.csv")),
                    str(board_path)], check=True)
    with ZipFile(out / (board_path.stem + "-fabrication.zip"), "w", ZIP_DEFLATED) as archive:
        for layer in sorted(layers.iterdir()):
            archive.write(layer, layer.name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("board", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--route", action="store_true", help="Route a freshly placed board in place.")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        if args.route:
            route(args.board.resolve(), work)
        plot(args.board.resolve(), args.output.resolve(), work)


if __name__ == "__main__":
    main()
