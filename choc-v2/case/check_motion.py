"""Run Choc rigid case, hinge hardware and driven electronics tests independently."""
import argparse
import json
from pathlib import Path
import sys

import bpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0,str(ROOT))
from validate_fold import inspect_scene
from validate_hardware import verify


def main():
    args = argparse.ArgumentParser()
    args.add_argument("test",choices=("case","hardware","electronics"))
    mode = args.parse_args(sys.argv[sys.argv.index("--")+1:]).test
    master = HERE/"Expanded-Choc-V2.blend"
    if mode=="hardware":
        report = verify(master)
        (HERE/"hardware.json").write_text(json.dumps(report,indent=2)+"\n")
    elif mode=="case":
        bpy.ops.wm.open_mainfile(filepath=str(master))
        result = inspect_scene(.5)
        (HERE/"fold.json").write_text(json.dumps(result,indent=2)+"\n")
        assert result["pass"],result["collisions"]
    else:
        sys.path.insert(0,str(HERE))
        from check_electronics import check
        bpy.ops.wm.open_mainfile(filepath=str(master))
        check(master,HERE/"electronics-fold.json")


if __name__=="__main__":
    main()
