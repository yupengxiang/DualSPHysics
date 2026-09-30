#!/usr/bin/env python3
"""Compare an old fluid-only F3 HDF5 view with a new full typed HDF5.

The historical plain artifacts deliberately contain only their 34,560 fluid
IDs.  The direct DS-DATA-02 artifact retains the complete 108,000-particle
typed axis.  This comparator aligns the common fluid identities by
``(Zone,Idp)`` and reports all shared fields without pretending that the old
fluid-only representation contains boundary state.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import resource
import time
from typing import Any, Mapping, Sequence

import h5py
import numpy as np


SCHEMA = "ds02.f3.legacy-fluid-subset-compare.v1"
NUMERIC_TOLERANCES = {
    "position": 1.0e-6,
    "velocity": 1.0e-6,
    "density": 1.0e-3,
    "mass": 1.0e-7,
    "pressure": 5.0e-2,
}
SHARED_FIELDS = ("valid", "position", "velocity", "density", "mass", "pressure", "type", "mk")


class LegacyCompareError(RuntimeError):
    """Raised when the historical view cannot be aligned safely."""


def _json_default(value: Any) -> Any:
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def _usage() -> dict[str, float]:
    result: dict[str, float] = {}
    for who, label in ((resource.RUSAGE_SELF, "self"), (resource.RUSAGE_CHILDREN, "children")):
        current = resource.getrusage(who)
        result[f"{label}_user_seconds"] = float(current.ru_utime)
        result[f"{label}_system_seconds"] = float(current.ru_stime)
        result[f"{label}_max_rss_kib"] = float(current.ru_maxrss)
    return result


def _usage_delta(before: Mapping[str, float], after: Mapping[str, float]) -> dict[str, float]:
    return {key: float(after[key] - before.get(key, 0.0)) for key in after}


def compare_subset(
    *,
    direct_path: Path,
    reference_path: Path,
    output_path: Path,
    particle_chunk: int = 65536,
) -> dict[str, Any]:
    if particle_chunk < 1:
        raise ValueError("particle_chunk must be positive")
    started = time.monotonic()
    usage_before = _usage()
    with h5py.File(direct_path, "r") as direct, h5py.File(reference_path, "r") as reference:
        for name in ("time", "particle_id", "particle_zone", *SHARED_FIELDS):
            if name not in direct or name not in reference:
                raise LegacyCompareError(f"shared comparison field is missing: {name}")
        direct_particles = int(direct["particle_id"].shape[0])
        reference_particles = int(reference["particle_id"].shape[0])
        direct_frames = int(direct["time"].shape[0])
        reference_frames = int(reference["time"].shape[0])
        if direct_frames != reference_frames:
            raise LegacyCompareError(f"frame count differs: direct={direct_frames}, reference={reference_frames}")
        direct_keys = list(zip(direct["particle_zone"][:].astype(np.int64), direct["particle_id"][:].astype(np.int64)))
        reference_keys = list(zip(reference["particle_zone"][:].astype(np.int64), reference["particle_id"][:].astype(np.int64)))
        direct_index = {key: index for index, key in enumerate(direct_keys)}
        if len(direct_index) != direct_particles:
            raise LegacyCompareError("direct typed identity axis is not unique")
        if len(set(reference_keys)) != reference_particles:
            raise LegacyCompareError("reference fluid identity axis is not unique")
        missing = [key for key in reference_keys if key not in direct_index]
        if missing:
            raise LegacyCompareError(f"reference identities are absent from direct axis: {missing[:8]}")
        indices = np.asarray([direct_index[key] for key in reference_keys], dtype=np.int64)
        direct_initial_type = direct["type"][0, indices]
        if np.any(direct_initial_type != 3):
            raise LegacyCompareError("reference IDs do not map exclusively to direct initial type=3")
        time_max_error = float(np.max(np.abs(direct["time"][:] - reference["time"][:])))
        time_equal = bool(np.array_equal(direct["time"][:], reference["time"][:], equal_nan=True))
        equal = {name: True for name in ("particle_id", "particle_zone", "valid", "type", "mk")}
        equal["particle_id"] = bool(np.array_equal(direct["particle_id"][indices], reference["particle_id"][:]))
        equal["particle_zone"] = bool(np.array_equal(direct["particle_zone"][indices], reference["particle_zone"][:]))
        numeric_max = {name: 0.0 for name in NUMERIC_TOLERANCES}
        numeric_finite_mismatch = {name: False for name in NUMERIC_TOLERANCES}
        for frame in range(direct_frames):
            for start in range(0, reference_particles, particle_chunk):
                stop = min(reference_particles, start + particle_chunk)
                direct_slice = indices[start:stop]
                for name in ("valid", "type", "mk"):
                    a = direct[name][frame, direct_slice]
                    b = reference[name][frame, start:stop]
                    equal[name] = equal[name] and bool(np.array_equal(a, b))
                for name in NUMERIC_TOLERANCES:
                    a = direct[name][frame, direct_slice].astype(np.float64)
                    b = reference[name][frame, start:stop].astype(np.float64)
                    finite = np.isfinite(a) & np.isfinite(b)
                    if np.any(finite):
                        numeric_max[name] = max(numeric_max[name], float(np.max(np.abs(a[finite] - b[finite]))))
                    if np.any(np.isfinite(a) != np.isfinite(b)):
                        numeric_finite_mismatch[name] = True
        numeric_within = {
            name: not numeric_finite_mismatch[name] and numeric_max[name] <= tolerance
            for name, tolerance in NUMERIC_TOLERANCES.items()
        }
        structural_equal = all(equal.values())
        passed = bool(time_equal and structural_equal and all(numeric_within.values()))
        report = {
            "schema": SCHEMA,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "comparison_status": "completed_actual_read_only_fluid_subset",
            "comparison_claim": "representation consistency for common historical fluid IDs; boundary state absent from reference and remains unvalidated there",
            "direct": {"path": str(direct_path), "frames": direct_frames, "particles": direct_particles, "typed_axis": "complete"},
            "reference": {"path": str(reference_path), "frames": reference_frames, "particles": reference_particles, "typed_axis": "fluid_only"},
            "alignment": {
                "identity_key": "(Zone,Idp)",
                "reference_ids_in_direct": int(len(indices)),
                "direct_reference_indices_contiguous": bool(
                    len(indices) < 2 or np.all(np.diff(indices) == 1)
                ),
                "direct_reference_index_min": int(indices.min()) if len(indices) else None,
                "direct_reference_index_max": int(indices.max()) if len(indices) else None,
                "direct_initial_type_all_fluid": True,
            },
            "time": {"exact_equal": time_equal, "max_abs_error_s": time_max_error},
            "exact_dataset_equality": equal,
            "numeric_max_abs_error": numeric_max,
            "numeric_tolerances": NUMERIC_TOLERANCES,
            "numeric_finite_mismatch": numeric_finite_mismatch,
            "numeric_within_tolerance": numeric_within,
            "passed": passed,
            "resource": {"wall_seconds": float(time.monotonic() - started), "usage": _usage_delta(usage_before, _usage())},
            "q_n_status": "not_assessed",
            "production_eligibility": "not_evaluated",
        }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True, default=_json_default) + "\n")
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--direct", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--particle-chunk", type=int, default=65536)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = compare_subset(
            direct_path=args.direct,
            reference_path=args.reference,
            output_path=args.output,
            particle_chunk=args.particle_chunk,
        )
    except (OSError, ValueError, LegacyCompareError) as exc:
        print(f"F3 legacy fluid subset comparison failed: {exc}")
        return 2
    print(json.dumps({
        "output": str(args.output),
        "passed": report["passed"],
        "frames": report["direct"]["frames"],
        "time_max_abs_error_s": report["time"]["max_abs_error_s"],
    }, sort_keys=True))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
