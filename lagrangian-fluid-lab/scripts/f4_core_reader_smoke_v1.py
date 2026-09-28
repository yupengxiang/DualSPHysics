"""Run a bounded, read-only Core reader smoke for an F4 collection.

This command checks the data path only.  It never starts a solver/worker and
never writes a campaign registry, ledger, denominator, or qualification gate.
The reader's ``formal_eligible`` flag is reported verbatim and is never
promoted by this diagnostic.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from scripts.core_cfd_dataset import open_dataset
from scripts.core_contract import contract_hash
from scripts.core_strict_json import read_bounded_raw_json


SCHEMA = "local.f4.core_reader_smoke.v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _check_state(state, *, case_id: str, frame: int, particle_count: int) -> dict:
    position = np.asarray(state.position)
    velocity = np.asarray(state.velocity)
    mass = np.asarray(state.mass)
    valid = np.asarray(state.valid, dtype=bool)
    if position.shape != (particle_count, 3) or velocity.shape != (particle_count, 3):
        raise ValueError(f"{case_id} frame {frame}: state shape does not match particle axis")
    if mass.shape != (particle_count,) or valid.shape != (particle_count,):
        raise ValueError(f"{case_id} frame {frame}: mass/valid shape does not match particle axis")
    finite = {
        "position": bool(np.isfinite(position).all()),
        "velocity": bool(np.isfinite(velocity).all()),
        "mass": bool(np.isfinite(mass).all()),
    }
    if not all(finite.values()):
        raise ValueError(f"{case_id} frame {frame}: non-finite state payload")
    valid_matches_particles = bool(valid.all() and int(valid.sum()) == particle_count)
    if not valid_matches_particles:
        raise ValueError(f"{case_id} frame {frame}: valid mask is not all active particles")
    return {
        "frame": int(frame),
        "time_s": float(state.time_s),
        "particle_count": int(particle_count),
        "finite": finite,
        "valid_true_equals_particle_count": valid_matches_particles,
        "mass_total_kg": float(mass.sum()),
    }


def run_smoke(manifest: str | Path, data_root: str | Path, *, expected_triangles: int = 10) -> dict:
    """Read and validate every case in *manifest* without mutating production data."""
    manifest_path = Path(manifest).expanduser().resolve()
    root = Path(data_root).expanduser().resolve()
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    if not root.is_dir():
        raise NotADirectoryError(root)
    if isinstance(expected_triangles, bool) or not isinstance(expected_triangles, int):
        raise ValueError("expected_triangles must be an integer")
    if expected_triangles < 0:
        raise ValueError("expected_triangles must be non-negative")

    started = time.perf_counter()
    # Use the same bounded raw-byte reader used by the dataset boundary so the
    # manifest digest in this receipt is tied to the bytes that were inspected.
    manifest_raw = read_bounded_raw_json(manifest_path, label="F4 smoke manifest")
    manifest_sha256 = hashlib.sha256(manifest_raw).hexdigest()
    rows = []
    reader_formal_eligible = None
    with open_dataset(manifest_path, root) as dataset:
        reader_formal_eligible = bool(dataset.formal_eligible)
        case_ids = dataset.case_ids()
        source_hashes = dataset.verify_sources(case_ids)
        for case_id in case_ids:
            record = dataset.record(case_id)
            times = np.asarray(dataset.times(case_id), dtype=float)
            if times.ndim != 1 or len(times) < 2 or not np.isfinite(times).all():
                raise ValueError(f"{case_id}: invalid time axis")
            if not np.all(np.diff(times) > 0):
                raise ValueError(f"{case_id}: time axis is not strictly increasing")
            known = dataset.known_inputs(case_id)
            triangles = np.asarray(known.geometry.triangles)
            if triangles.shape != (expected_triangles, 3, 3):
                raise ValueError(
                    f"{case_id}: expected {expected_triangles} geometry triangles, "
                    f"got {triangles.shape}"
                )
            if contract_hash(known) != record["known_inputs_sha256"]:
                raise ValueError(f"{case_id}: known-input contract hash mismatch")
            frames = (0, len(times) // 2, len(times) - 1)
            states = []
            particle_count = None
            for frame in frames:
                state = dataset.read_state(case_id, frame)
                if particle_count is None:
                    particle_count = state.count
                states.append(_check_state(
                    state, case_id=case_id, frame=frame,
                    particle_count=particle_count))
            if any(item["particle_count"] != particle_count for item in states):
                raise ValueError(f"{case_id}: particle count changed across samples")
            source_hash = source_hashes.get(case_id)
            if source_hash != record["sha256"]:
                raise ValueError(f"{case_id}: verified source hash differs from manifest")
            rows.append({
                "case_id": case_id,
                "family": record["family"],
                "split": record["split"],
                "source_sha256": source_hash,
                "known_inputs_sha256": record["known_inputs_sha256"],
                "frames": int(len(times)),
                "transitions": int(len(times) - 1),
                "time_start_s": float(times[0]),
                "time_end_s": float(times[-1]),
                "geometry_triangles": int(triangles.shape[0]),
                "state_samples": states,
            })

    split_counts = {}
    for row in rows:
        split_counts[row["split"]] = split_counts.get(row["split"], 0) + 1
    result = {
        "schema": SCHEMA,
        "manifest": str(manifest_path),
        "manifest_sha256": manifest_sha256,
        "data_root": str(root),
        "case_count": len(rows),
        "source_hashes_verified": len(rows),
        "reader_formal_eligible": reader_formal_eligible,
        "diagnostic_only": True,
        "formal_credit_granted": False,
        "qualification_credit": 0,
        "split_counts": dict(sorted(split_counts.items())),
        "cases": rows,
        "elapsed_seconds": time.perf_counter() - started,
        "side_effects": {
            "solver_started": False,
            "worker_started": False,
            "gpu_started": False,
            "queue_mutation": False,
            "production_artifact_mutation": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "gate_mutation": 0,
        },
    }
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--expected-triangles", type=int, default=10)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    result = run_smoke(args.manifest, args.data_root,
                       expected_triangles=args.expected_triangles)
    encoded = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
