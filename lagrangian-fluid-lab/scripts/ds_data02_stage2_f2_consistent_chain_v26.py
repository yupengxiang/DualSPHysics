#!/usr/bin/env python3
"""Bind the consumed v25 graph to the real v14/v20 parent chain.

v25 corrected the bridge's hidden v7 graph, but its terminal launcher still
points at the consumed v13 implementation.  This additive builder keeps all
v25 JSON and code immutable, creates a new v14 request with the real nested
strace/PDEATHSIG cleanup entry, then creates the v20 same-parent supervisor
request around that exact v14 request.  It only reads small contracts and
does not copy HDF5/BI4 or launch a worker.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[0]
V25_V13 = (ROOT / "campaigns/ds-data-02/stage2/native-reconstruction/"
           "raw-to-label-v25-consistent/f2-s1-parent-supervised-launch-request-v13-012.json")
V14_PATH = SCRIPT_DIR / "ds_data02_stage2_f2_parent_launcher_v14.py"
V20_PATH = SCRIPT_DIR / "ds_data02_stage2_f2_external_supervisor_v20.py"
OUT_DIR = (ROOT / "campaigns/ds-data-02/stage2/native-reconstruction/"
           "raw-to-label-v26-supervised-chain")
V14_OUT = OUT_DIR / "f2-s1-parent-supervised-launch-request-v14-013.json"
V20_OUT = OUT_DIR / "f2-s1-external-supervisor-request-v20-013.json"
EXTERNAL = Path("/var/tmp/ds02-stage2/ds-data-02/families/F2/STAGE2_F2_S1_PORTABLE_RAW_TO_LABEL_V5")
SUPERVISOR_ROOT = EXTERNAL / "f2-s1-v26-supervisor-001"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V14 = _load("ds02_f2_parent_launcher_v14_for_v26", V14_PATH)
V20 = _load("ds02_f2_external_supervisor_v20_for_v26", V20_PATH)


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build() -> dict[str, Any]:
    if not V25_V13.is_file():
        raise RuntimeError(f"v25 v13 request is missing: {V25_V13}")
    if V14_OUT.exists() or V20_OUT.exists():
        raise RuntimeError("refusing to overwrite v26 requests")
    if SUPERVISOR_ROOT.exists():
        raise RuntimeError(f"refusing existing supervisor namespace: {SUPERVISOR_ROOT}")
    v14 = V14.build_request(V25_V13, V14_OUT, cleanup_grace_seconds=20.0)
    v20 = V20.build_request(V14_OUT, V20_OUT, output_root=SUPERVISOR_ROOT,
                            max_wall_seconds=6000.0)
    return {"v14": v14, "v20": v20}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    value = build()
    print(json.dumps({
        key: {"path": str(path), "sha256": sha256_file(path),
              "canonical_sha256": item["sha256"], "status": item.get("status")}
        for key, path, item in (("v14", V14_OUT, value["v14"]),
                                ("v20", V20_OUT, value["v20"]))},
        sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
