#!/usr/bin/env python3
"""Run one F2 native conversion with bounded external PartVTK scratch.

The shared runner accounts the attempt directory against its 8 GiB output
reservation while ``ds_data02_convert.py`` is streaming all saved BI4 frames.
PartVTK's intermediate CSV frames are temporary by design and can exceed that
reservation before the converter removes them.  This F2-owned wrapper places
only that temporary tree under a private system temporary directory.  The
trajectory, conversion report, receipt, source hashes, and all scientific
outputs remain in the runner-owned attempt directory.  The public converter
is invoked unchanged and no solver is launched.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


LAB_ROOT = Path(__file__).resolve().parents[4]
CONVERTER = LAB_ROOT / "scripts/ds_data02_convert.py"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--solver-receipt", type=Path, required=True)
    parser.add_argument("--gencase-receipt", type=Path, required=True)
    parser.add_argument("--owner-metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--partvtk-threads", type=int, default=4)
    args = parser.parse_args()

    output = args.output.resolve()
    report = args.report.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix=f"ds-data-02-f2-{output.parent.name}-", dir="/tmp"))
    command = [
        sys.executable,
        str(CONVERTER),
        "--solver-receipt", str(args.solver_receipt.resolve()),
        "--gencase-receipt", str(args.gencase_receipt.resolve()),
        "--owner-metadata", str(args.owner_metadata.resolve()),
        "--output", str(output),
        "--work-dir", str(scratch),
        "--report", str(report),
        "--partvtk-threads", str(args.partvtk_threads),
    ]
    try:
        completed = subprocess.run(command, cwd=LAB_ROOT, check=False)
        # Keep the small PartVTK launcher log beside the report.  The frame
        # CSVs remain temporary; their hashes and frame count are in the
        # immutable conversion report.
        partvtk_log = scratch / "partvtk.stdout.log"
        if partvtk_log.is_file():
            shutil.copy2(partvtk_log, output.parent / "partvtk.stdout.log")
        return int(completed.returncode)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
