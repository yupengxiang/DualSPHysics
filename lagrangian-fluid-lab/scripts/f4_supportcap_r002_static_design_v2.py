#!/usr/bin/env python3
"""Reissue the F4 r002 static design without opening historical HDF5 files.

The v1 design generator accidentally re-hashed the small r001 trace while
checking its inherited evidence bindings.  This version preserves that
receipt and its generator as historical evidence, but carries the trace's
already-recorded byte count and digest forward from the attribution JSON.  It
does not stat, open, parse, or hash any HDF5/NPZ file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts import f4_supportcap_r002_static_design_v1 as predecessor


RECEIPT = Path(
    "campaigns/core-v1/material/candidates/f4-supportcap-affine-query-bound-v3/"
    "r002-static-design-v2/recipe.json"
)
SCHEMA = "core.material.f4.supportcap_r002_static_temporal_alignment_design.v2"
TRACE_PATH = str(predecessor.R001_DIR / "trace.h5")


def parent_bindings(attribution: dict[str, Any]) -> list[dict[str, Any]]:
    """Verify text parents, but inherit the immutable r001 trace binding only."""
    result: list[dict[str, Any]] = []
    inherited_trace_count = 0
    items = attribution.get("bindings", [])
    if not isinstance(items, list):
        raise ValueError("r001 attribution bindings must be a list")

    for item in items:
        if not isinstance(item, dict):
            raise ValueError("r001 attribution binding must be an object")
        path_text = item.get("path")
        role = item.get("role")
        if not isinstance(path_text, str) or not isinstance(role, str):
            raise ValueError("r001 attribution binding lacks path/role")

        if path_text == TRACE_PATH:
            size = item.get("bytes")
            digest = item.get("sha256")
            if (isinstance(size, bool) or not isinstance(size, int) or size <= 0
                    or not isinstance(digest, str) or len(digest) != 64
                    or any(char not in "0123456789abcdef" for char in digest)):
                raise ValueError("r001 trace must have a valid inherited size and SHA256")
            if role != "immutable r001 two-frame trace":
                raise ValueError("r001 trace binding has an unexpected role")
            result.append({
                "path": path_text,
                "role": role,
                "bytes": size,
                "sha256": digest,
            })
            inherited_trace_count += 1
            continue

        path = Path(path_text)
        if path.suffix.lower() in {".h5", ".hdf5", ".npz"}:
            raise ValueError(f"unexpected binary parent is not opened by static design: {path}")
        observed = predecessor._binding(path, role)
        if observed["bytes"] != item.get("bytes") or observed["sha256"] != item.get("sha256"):
            raise ValueError(f"immutable r001 text parent changed: {path}")
        result.append(observed)

    if inherited_trace_count != 1:
        raise ValueError("r001 attribution must contain exactly one inherited trace binding")
    return result


def build_recipe() -> dict[str, Any]:
    """Build the corrected v2 static receipt using only JSON/HDF5 metadata."""
    original_parent_bindings = predecessor._parent_bindings
    predecessor._parent_bindings = parent_bindings
    try:
        recipe = predecessor.build_recipe()
    finally:
        predecessor._parent_bindings = original_parent_bindings

    recipe["schema"] = SCHEMA
    recipe["record_id"] = "f4-supportcap-affine-query-bound-v3-r002-static-design-v2"
    recipe["status"] = "static_temporal_alignment_design_v2_for_independent_review"
    recipe["static_read_boundary"] = {
        "binary_trajectory_access": "forbidden",
        "r001_trace_binding": "inherit path/bytes/sha256 from immutable attribution JSON",
        "text_parent_bindings": "re-hash and verify",
        "hdf5_npz_stat_open_parse_or_hash_performed": False,
    }

    for binding in recipe["bindings"]:
        if binding["path"] == "scripts/f4_supportcap_r002_static_design_v1.py":
            binding["role"] = "historical v1 predecessor generator retained unchanged"
        elif binding["path"] == "tests/test_f4_supportcap_r002_static_design_v1.py":
            binding["role"] = "historical v1 predecessor tests retained unchanged"
    recipe["bindings"].extend([
        predecessor._binding(Path(__file__).resolve(), "HDF5-read-boundary-fix v2 generator"),
        predecessor._binding(
            Path("tests/test_f4_supportcap_r002_static_design_v2.py"),
            "HDF5-read-boundary regression tests",
        ),
    ])
    return recipe


def write_recipe() -> Path:
    path = LAB / RECEIPT
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite static-design receipt: {path}")
    recipe = build_recipe()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(recipe, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the new v2 static receipt once")
    args = parser.parse_args(argv)
    if args.write:
        print(str(write_recipe().relative_to(LAB)))
    else:
        print(json.dumps(build_recipe(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
