"""Measure neutral underside package outlines from the populated KiCad model.

Run with Python, NumPy, Shapely and kicad-cli. The two silhouettes conservatively
fill any internal voids in the package. All coordinates are in assembly mm.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import numpy as np
from shapely.affinity import rotate
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from check_boards import projected_surface


def measured_outline(tris, angle):
    surface = projected_surface(tris, -10, 0)
    neutral = rotate(surface, -angle, origin=(0,0))
    # Cover tessellation noise. Verify that simplifying the silhouette did not
    # move even one point inside the CAD surface it bounds.
    profile = Polygon(neutral.buffer(.014,quad_segs=4).exterior).simplify(.008)
    assert profile.covers(neutral) and profile.is_valid
    return {
        "xy": np.round(orient(profile,1).exterior.coords[:-1],5).tolist(),
        "lowest_from_board_underside_mm": round(float(tris[:,:,2].min()),4),
    }


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--kicad-cli", default="kicad-cli")
    args = cli.parse_args()
    folder = HERE.parent/"left-finger"
    board = folder/(folder.name+".kicad_pcb")
    parts = json.loads((folder/"circuit.json").read_text())
    out = {}
    with tempfile.TemporaryDirectory() as directory:
        for kind, ref in (("MX","SW5"),("FFC12","J1")):
            element = next(p for p in parts if p["ref"]==ref)
            x,y = element["xy"]
            stl = Path(directory)/(ref+".stl")
            subprocess.run([args.kicad_cli,"pcb","export","stl","--no-board-body","--component-filter",
                            ref,"--user-origin",f"{150+x:.5f}x{100-y:.5f}mm","-o",str(stl),str(board)],check=True)
            verts = [list(map(float,s.split())) for s in re.findall(r"vertex ([^\n]*)",stl.read_text())]
            out[kind] = measured_outline(np.array(verts).reshape(-1,3,3),element["angle"])
    (HERE/"component-profiles.json").write_text(json.dumps(out,separators=(",",":"))+"\n")


if __name__ == "__main__":
    main()
