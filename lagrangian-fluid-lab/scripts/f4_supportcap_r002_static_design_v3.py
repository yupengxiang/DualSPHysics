#!/usr/bin/env python3
"""Add filesystem-access guards to the F4 r002 static design receipt.

This v3 carries forward the v2 no-HDF5-hash repair and strengthens its
regression boundary: the builder must not stat, resolve, open, parse, read, or
hash an HDF5/NPZ path.  The r001 trace digest is still inherited from the
attribution JSON; all execution permissions remain false.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts import f4_supportcap_r002_static_design_v2 as predecessor


RECEIPT = Path(
    "campaigns/core-v1/material/candidates/f4-supportcap-affine-query-bound-v3/"
    "r002-static-design-v3/recipe.json"
)
SCHEMA = "core.material.f4.supportcap_r002_static_temporal_alignment_design.v3"


def build_recipe() -> dict:
    recipe = predecessor.build_recipe()
    recipe["schema"] = SCHEMA
    recipe["record_id"] = "f4-supportcap-affine-query-bound-v3-r002-static-design-v3"
    recipe["status"] = "static_temporal_alignment_design_v3_access_guarded_for_independent_review"
    recipe["static_read_boundary"] = {
        "binary_trajectory_access": "forbidden",
        "r001_trace_binding": "inherit path/bytes/sha256 from immutable attribution JSON",
        "text_parent_bindings": "re-hash and verify",
        "forbidden_path_operations_on_hdf5_npz": [
            "stat", "lstat", "resolve", "exists", "is_file", "is_symlink",
            "open", "read_bytes", "read_text", "hash",
        ],
        "hdf5_npz_stat_open_parse_or_hash_performed": False,
        "filesystem_access_regression_guard": "tests wrap pathlib accessors and the source hash helper",
    }
    for binding in recipe["bindings"]:
        if binding["path"] == "scripts/f4_supportcap_r002_static_design_v2.py":
            binding["role"] = "v2 HDF5 hash-inheritance predecessor generator"
        elif binding["path"] == "tests/test_f4_supportcap_r002_static_design_v2.py":
            binding["role"] = "v2 hash-inheritance predecessor regression tests"
    recipe["bindings"].extend([
        predecessor.predecessor._binding(
            Path(__file__).resolve(), "HDF5/NPZ filesystem-access guard v3 generator"
        ),
        predecessor.predecessor._binding(
            Path("tests/test_f4_supportcap_r002_static_design_v3.py"),
            "HDF5/NPZ filesystem-access regression tests",
        ),
    ])
    return recipe


def write_recipe() -> Path:
    path = LAB / RECEIPT
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite static-design receipt: {path}")
    if path.parent.exists() or path.parent.is_symlink():
        raise FileExistsError(f"refusing to reuse static-design receipt directory: {path.parent}")
    path.parent.mkdir(parents=True, exist_ok=False)
    path.write_text(json.dumps(build_recipe(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the v3 static receipt once")
    args = parser.parse_args(argv)
    if args.write:
        print(str(write_recipe().relative_to(LAB)))
    else:
        print(json.dumps(build_recipe(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
