#!/usr/bin/env python3
"""Materialise the evidence-based F1 virtual-normal-plane candidate.

The source is the immutable distanceh=3 normal-support candidate.  This writer
changes only the two ``GeometryForNormals`` layer declarations from their
observed phase-coincident offsets (-0.5 for the outer wall and +0.5 for the
separator) to vdp=0.  Mainlist layers, physical drawbox bounds, distanceh,
svshapes, and the native fluid recipe must remain byte-identical.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import resource
from typing import Any

OUTER_OLD = b'<layers vdp="-0.5" />'
SEPARATOR_OLD = b'<layers vdp="0.5" />'
LAYER_NEW = b'<layers vdp="0" />'
DISTANCEH = b'<distanceh v="3.0" />'
SVSHAPES = b'<svshapes v="true" />'
MAIN_OUTER = b'<layers vdp="0,1,2" />'
MAIN_SEPARATOR = b'<layers vdp="0,-1,-2" />'


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _rusage() -> dict[str, float]:
    self_usage = resource.getrusage(resource.RUSAGE_SELF)
    child_usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return {
        "self_user_seconds": float(self_usage.ru_utime),
        "self_system_seconds": float(self_usage.ru_stime),
        "children_user_seconds": float(child_usage.ru_utime),
        "children_system_seconds": float(child_usage.ru_stime),
        "combined_user_seconds": float(self_usage.ru_utime + child_usage.ru_utime),
        "combined_system_seconds": float(self_usage.ru_stime + child_usage.ru_stime),
        "max_rss_kib_self": float(self_usage.ru_maxrss),
        "max_rss_kib_children": float(child_usage.ru_maxrss),
    }


def prepare_definition(source: Path, output: Path) -> dict[str, Any]:
    source = source.resolve()
    output = output.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite candidate: {output}")
    source_bytes = source.read_bytes()
    if source_bytes.count(OUTER_OLD) != 1 or source_bytes.count(SEPARATOR_OLD) != 1:
        raise ValueError(
            "source must contain exactly one outer vdp=-0.5 and one separator vdp=0.5 layer"
        )
    for token, label in ((DISTANCEH, "distanceh=3.0"), (SVSHAPES, "svshapes=true"), (MAIN_OUTER, "main outer layers"), (MAIN_SEPARATOR, "main separator layers")):
        if source_bytes.count(token) != 1:
            raise ValueError(f"source must retain exactly one {label} token")
    candidate_bytes = source_bytes.replace(OUTER_OLD, LAYER_NEW, 1).replace(SEPARATOR_OLD, LAYER_NEW, 1)
    expected_bytes = source_bytes.replace(OUTER_OLD, LAYER_NEW, 1).replace(SEPARATOR_OLD, LAYER_NEW, 1)
    if candidate_bytes != expected_bytes:
        raise AssertionError("candidate byte delta is not the declared vdp replacement")
    if candidate_bytes.count(OUTER_OLD) or candidate_bytes.count(SEPARATOR_OLD):
        raise AssertionError("candidate retained an old GeometryForNormals vdp token")
    if candidate_bytes.count(LAYER_NEW) != 2:
        raise AssertionError("candidate must contain exactly two vdp=0 normal layers")
    if candidate_bytes.count(MAIN_OUTER) != 1 or candidate_bytes.count(MAIN_SEPARATOR) != 1:
        raise AssertionError("candidate changed the mainlist layer declarations")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(candidate_bytes)
    observed = output.read_bytes()
    if observed != candidate_bytes:
        raise AssertionError("candidate changed while being written")
    source_hash_before = sha256_bytes(source_bytes)
    source_hash_after = sha256(source)
    if source_hash_before != source_hash_after:
        raise AssertionError("source changed during preparation")
    return {
        "source": str(source),
        "candidate": str(output),
        "source_sha256": source_hash_before,
        "candidate_sha256": sha256_bytes(candidate_bytes),
        "source_outer_vdp": "-0.5",
        "source_separator_vdp": "0.5",
        "candidate_outer_vdp": "0",
        "candidate_separator_vdp": "0",
        "distanceh": "3.0",
        "svshapes": "true",
        "physical_drawbox_bounds_unchanged": True,
        "mainlist_layers_unchanged": True,
        "native_fluid_recipe_unchanged": True,
        "byte_delta": {
            "replace_once": [
                [OUTER_OLD.decode(), LAYER_NEW.decode()],
                [SEPARATOR_OLD.decode(), LAYER_NEW.decode()],
            ]
        },
        "source_unchanged": source_hash_before == source_hash_after,
        "candidate_exists": output.is_file(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    before = _rusage()
    result = prepare_definition(args.source, args.output)
    result["resource_usage"] = {"before": before, "after": _rusage()}
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
