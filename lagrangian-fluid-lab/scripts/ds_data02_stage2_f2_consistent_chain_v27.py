#!/usr/bin/env python3
"""Forward v25/v26 into the v15 accounting adapter and v21 supervisor.

The v26 metadata chain proves v14/v20 source closure, but the consumed v14
implementation looked for its terminal predicate on the wrong module.  v27
adds the explicit v15 adapter and keeps the v21 supervisor's 25-second child
cleanup grace.  The bridge graph and all scientific source paths remain the
immutable v25 graph; this command only writes small fresh JSON contracts.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
LAB = SCRIPT_DIR.parents[0]
V26_V14 = LAB / "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v26-supervised-chain/f2-s1-parent-supervised-launch-request-v14-013.json"
V15_PATH = SCRIPT_DIR / "ds_data02_stage2_f2_parent_launcher_v15.py"
V21_PATH = SCRIPT_DIR / "ds_data02_stage2_f2_external_supervisor_v21.py"
OUT_DIR = LAB / "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v27-supervised-chain"
V15_OUT = OUT_DIR / "f2-s1-parent-supervised-launch-request-v15-adapter-014.json"
V21_OUT = OUT_DIR / "f2-s1-external-supervisor-request-v21-014.json"
EXTERNAL = Path("/var/tmp/ds02-stage2/ds-data-02/families/F2/STAGE2_F2_S1_PORTABLE_RAW_TO_LABEL_V5")
SUPERVISOR_ROOT = EXTERNAL / "f2-s1-v27-supervisor-001"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V15 = _load("ds02_parent_launcher_v15_for_v27", V15_PATH)
V21 = _load("ds02_external_supervisor_v21_for_v27", V21_PATH)


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build() -> dict[str, Any]:
    if not V26_V14.is_file():
        raise RuntimeError(f"v26 v14 request is missing: {V26_V14}")
    if V15_OUT.exists() or V21_OUT.exists() or SUPERVISOR_ROOT.exists():
        raise RuntimeError("refusing existing v27 output")
    v15 = V15.build_request(V26_V14, V15_OUT)
    v21 = V21.build_request(V15_OUT, V21_OUT, output_root=SUPERVISOR_ROOT,
                            max_wall_seconds=6000.0)
    return {"v15": v15, "v21": v21}


def main() -> int:
    argparse.ArgumentParser().parse_args()
    value = build()
    print(json.dumps({key: {"path": str(path), "sha256": sha256_file(path),
                            "canonical_sha256": item["sha256"],
                            "status": item.get("status")}
                      for key, path, item in (("v15", V15_OUT, value["v15"]),
                                              ("v21", V21_OUT, value["v21"]))},
                     indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
