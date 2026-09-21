#!/usr/bin/env python3
"""Build read-only CPU job proposals for F4 tall-wall material overlays.

The proposal binds one terminal, root-verified 1.2 m tall-wall CFD archive to
the versioned material tracer.  It writes only material evidence/job JSON; it
never submits a job or mutates the central ledger.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import h5py
import numpy as np

# This file is also used as a direct worker-side preparation command.
LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts import f4_tallwall120_material as material


SOURCE_DIR = LAB_ROOT / "campaigns/core-v1/cfd/f4-tallwall120-archives-v2/f4-tallwall120-qualification-cell-04"
SOURCE_H5 = SOURCE_DIR / "product/trajectory.h5"
SOURCE_ARCHIVE = SOURCE_DIR / "archive.json"
SOURCE_RESULT = SOURCE_DIR / "product/result.json"
SOURCE_AUDIT = SOURCE_DIR / "product/audit.json"
SOURCE_OBSERVATIONS = SOURCE_DIR / "product/observations.json"
PREPARED = LAB_ROOT / "campaigns/core-v1/cfd/prepared/F4_tallwall120_qualification_v2/cell-04/prepared.json"
DEF_XML = PREPARED.parent / "F4_TALLWALL120_MDBC_NATIVE_NU1E6_Q0P50000000_DP0P007500000000_SPATIAL_Def.xml"
GENERATED_XML = PREPARED.parent / "generated/F4_TALLWALL120_MDBC_NATIVE_NU1E6_Q0P50000000_DP0P007500000000_SPATIAL.xml"
CELL04_VERIFICATION = LAB_ROOT / "campaigns/core-v1/cfd/f4-tallwall120-cell04-root-verification-v1.json"
T1_COMPLETE = LAB_ROOT / "campaigns/core-v1/cfd/f4-tallwall120-qualification-independent-root-complete-v1.json"
MIGRATION_SPEC = LAB_ROOT / "campaigns/core-v1/material/evidence/f4-resting-pool-migration-spec-2026-09-19.json"
TRACER = LAB_ROOT / "scripts/f4_tallwall120_material.py"
CORE_MATERIAL = LAB_ROOT / "scripts/core_material.py"
NEIGHBOURS = LAB_ROOT / "scripts/f3_material_neighbors.py"
PASSIVE = LAB_ROOT / "scripts/passive_tracers.py"
PROPOSAL_BUILDER = LAB_ROOT / "scripts/f4_tallwall120_material_proposal.py"

SOURCE_H5_SHA256 = "78631cec15acdd5abcd5c43f326c2dd7c215b3248fd99ec544718bca72a74cad"
SOURCE_ARCHIVE_SHA256 = "c08aa95984d3e0f4cf153935c2cc7a710fbaeb8e66a371b72079c25bb9a3d3eb"
FAMILY = "F4"
SOURCE_CASE_ID = "F4_TALLWALL120_MDBC_NATIVE_NU1E6_Q0P50000000_DP0P007500000000_SPATIAL"
Q = 0.5
DP_M = 0.0075
SEEDS = 512
SUBSTEPS = 2
SHORT_STOP_AFTER = 20
FULL_STOP_AFTER = 217
OUTPUT_INTERVAL_S = 0.02
FULL_WINDOW_S = 4.34


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def ref(path: Path, role: str) -> dict:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{role}: {path}")
    return {"path": str(path), "sha256": sha256(path), "role": role}


def _load(path: Path) -> dict:
    return json.loads(Path(path).read_text())


def verify_source() -> dict:
    if sha256(SOURCE_H5) != SOURCE_H5_SHA256:
        raise ValueError("terminal source H5 hash does not match root-verified archive")
    if sha256(SOURCE_ARCHIVE) != SOURCE_ARCHIVE_SHA256:
        raise ValueError("terminal source archive hash does not match root verification")
    archive = _load(SOURCE_ARCHIVE)
    if archive.get("schema") != "core.verified_archive.v1" or archive.get("execution_status") != "succeeded":
        raise ValueError("source archive is not a succeeded verified archive")
    outputs = {row.get("path"): row for row in archive.get("outputs", []) if isinstance(row, dict)}
    if outputs.get("product/trajectory.h5", {}).get("sha256") != SOURCE_H5_SHA256:
        raise ValueError("source archive does not bind trajectory H5")
    prepared = _load(PREPARED)
    cfg = prepared.get("config", {})
    if cfg.get("case_id") != SOURCE_CASE_ID:
        raise ValueError("prepared case does not match terminal source case")
    for key, expected in (("q", Q), ("value", 0.36)):
        actual = cfg.get("parameter", {}).get(key)
        if abs(float(actual) - expected) > 1e-12:
            raise ValueError(f"prepared parameter {key} mismatch: {actual!r}")
    for key, expected in (("dp_m", DP_M), ("output_interval_s", OUTPUT_INTERVAL_S), ("time_max_s", FULL_WINDOW_S)):
        if abs(float(cfg.get(key)) - expected) > 1e-12:
            raise ValueError(f"prepared {key} mismatch: {cfg.get(key)!r}")
    if cfg.get("wall_bounds", {}).get("zmax") != 1.2:
        raise ValueError("prepared source is not the 1.2 m tall-wall case")
    if not _load(SOURCE_AUDIT).get("hard_integrity_pass") or not _load(SOURCE_AUDIT).get("source_mass_gate_pass"):
        raise ValueError("source audit does not pass hard integrity and mass gates")
    with h5py.File(SOURCE_H5, "r") as h5:
        frames = int(h5["time"].shape[0])
        particles = int(h5["position"].shape[1])
        times = np.asarray(h5["time"][:], dtype=np.float64)
        if frames != 218 or particles != 217485:
            raise ValueError(f"unexpected terminal source shape: {frames}x{particles}")
        if not np.isfinite(times).all() or abs(times[0]) > 1e-12 or abs(times[-1] - FULL_WINDOW_S) > 3e-5:
            raise ValueError("source time axis is not the registered 0..4.34 s window")
        interval = np.diff(times)
        cadence_error = float(np.max(np.abs(interval - OUTPUT_INTERVAL_S)))
        if cadence_error > 2e-5:
            raise ValueError(f"source cadence exceeds registered structural tolerance: {cadence_error}")
    return {
        "case_id": SOURCE_CASE_ID,
        "source_h5": ref(SOURCE_H5, "terminal_root_verified_native_trajectory"),
        "archive": ref(SOURCE_ARCHIVE, "terminal_verified_archive"),
        "result": ref(SOURCE_RESULT, "native_source_result"),
        "audit": ref(SOURCE_AUDIT, "native_source_audit"),
        "observations": ref(SOURCE_OBSERVATIONS, "native_source_observations"),
        "prepared": ref(PREPARED, "prepared_source_definition"),
        "def_xml": ref(DEF_XML, "prepared_finite_wall_definition"),
        "generated_xml": ref(GENERATED_XML, "prepared_generated_solver_definition"),
        "cell04_verification": ref(CELL04_VERIFICATION, "root_cell04_output_verification"),
        "t1_complete": ref(T1_COMPLETE, "root_t1_complete_tallwall_matrix"),
        "frame_count": frames,
        "particle_count": particles,
        "native_output_interval_s": OUTPUT_INTERVAL_S,
        "window_s": FULL_WINDOW_S,
        "cadence_tolerance_s": 2e-5,
        "cadence_max_error_s": cadence_error,
    }


def event_contract() -> dict:
    definition = material._tallwall_definition(Q, DP_M)
    return {
        "source_region": definition["source_definition"],
        "destination_region": definition["destination_definition"],
        "wall_bounds_m": definition["wall_bounds_m"],
        "closed_faces": definition["closed_faces"],
        "open_faces": definition["open_faces"],
        "event_definition": definition["event_definition"],
        "source_seed_contract": {
            "generator": "scripts.core_material.seeds_f4",
            "count": SEEDS,
            "q": Q,
            "source_membership": "all seeds must be inside the continuous source box",
            "labels": "all source label 1 from initial continuous membership",
            "identity": "seed-000000..seed-000511; no native particle_id identity",
            "weight": "equal volume quadrature weight; full source mass denominator",
        },
        "provider_contract": definition["provider_contract"],
    }


def input_refs(source: dict) -> list[dict]:
    refs = [source[k] for k in ("source_h5", "archive", "result", "audit", "observations", "prepared", "def_xml", "generated_xml", "cell04_verification", "t1_complete")]
    refs.extend([
        ref(TRACER, "versioned_tallwall120_material_tracer"),
        ref(CORE_MATERIAL, "shared_provider_and_event_primitives"),
        ref(NEIGHBOURS, "visible_support_shepard_backend"),
        ref(PASSIVE, "finite_wall_and_support_helpers"),
        ref(MIGRATION_SPEC, "f4_family_event_precedent"),
        ref(PROPOSAL_BUILDER, "proposal_builder"),
    ])
    return refs


def _argv(stop_after: int | None) -> list[str]:
    argv = [
        str(LAB_ROOT / ".venv/bin/python"),
        str(TRACER),
        "--source", str(SOURCE_H5),
        "--output", "{attempt_dir}/product/tallwall120_material.h5",
        "--q", str(Q), "--dp-m", str(DP_M),
        "--seeds", str(SEEDS), "--substeps", str(SUBSTEPS),
    ]
    if stop_after is not None:
        argv += ["--stop-after", str(stop_after)]
    return argv


def _spec(source: dict, *, short: bool) -> dict:
    job_id = "core-f4-tallwall120-material-canary-s2-v1" if short else "core-f4-tallwall120-material-full434-s2-v1"
    stop_after = SHORT_STOP_AFTER if short else None
    intervals = SHORT_STOP_AFTER if short else FULL_STOP_AFTER
    # The F4 native MLS 151-frame H200 profile is the closest completed CPU
    # basis.  Scale by source bytes and interval count, then add 30% margin.
    basis_wall = 900.0
    basis_cpu = 1050.0
    basis_read = 1320960691
    scale = (SOURCE_H5.stat().st_size / basis_read) * (intervals / 150.0)
    if short:
        wall = max(300, int(np.ceil(basis_wall * scale * 1.30)))
        cpu = max(360, int(np.ceil(basis_cpu * scale * 1.30)))
        read_budget = int(np.ceil(SOURCE_H5.stat().st_size * 1.10 * (intervals + 1) / 218.0))
    else:
        wall = max(2400, int(np.ceil(basis_wall * scale * 1.30)))
        cpu = max(2800, int(np.ceil(basis_cpu * scale * 1.30)))
        read_budget = int(np.ceil(SOURCE_H5.stat().st_size * 1.10))
    return {
        "schema": "core.material.job.v2",
        "job_id": job_id,
        "logical_id": job_id.upper().replace("-", "_"),
        "attempt_role": "initial",
        "category": "material_f4_tallwall120_canary",
        "family": FAMILY,
        "scope_id": material.SCOPE_ID,
        "revision_id": material.REVISION_ID,
        "stage": "qualification_only",
        "qualification_only": True,
        "qualification_claim": "none",
        "material_reliability_status": "uncalibrated",
        "source_t1_status": "root_complete_15_cell_tallwall120; independent material T2 not assessed",
        "source_lineage": "terminal archived cell-04 q=0.5 dp=0.0075; no synthetic or F3 source substitution",
        "host": "ada",
        "cwd": str(LAB_ROOT),
        "argv": _argv(stop_after),
        "env": {
            "OPENBLAS_NUM_THREADS": "1",
            "OMP_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
        },
        "input_files": input_refs(source),
        "source": source,
        "source_definition": event_contract(),
        "backend": {
            "name": material.NEIGHBOUR_BACKEND,
            "version": material.REVISION_ID,
            "neighbours": material.NEIGHBOURS,
            "weighting": "1/(distance_squared+regularization_squared)",
            "regularization_m": material.REGULARIZATION_M,
            "maximum_support_distance_m": material.MAXIMUM_SUPPORT_DISTANCE_M,
            "support_gate": material.GATE,
            "unknown_gate_fraction_max": 0.01,
            "material_reliability_calibrated": False,
        },
        "event_window": {
            "requested_native_intervals": intervals,
            "requested_window_s": float(source["window_s"] if not short else OUTPUT_INTERVAL_S * SHORT_STOP_AFTER),
            "source_native_window_s": source["window_s"],
            "short_canary_is_event_right_censored": short,
            "full_canary_extension_available": False,
            "extension_requires_new_native_source": True,
            "unobserved_event_policy": "NaN/right-censored; retain full source mass denominator",
        },
        "acceptance": {
            "must_preserve_mass_closure": True,
            "must_report_unknown_fraction_per_source": True,
            "must_report_common_reliable_path_coverage": True,
            "must_report_contact_upward_return_cdf": True,
            "must_report_residence_with_right_censoring": True,
            "must_not_report_T2_qualification": True,
            "source_hash_must_match_archive": True,
            "tallwall_zmax_must_be_1p2_m": True,
            "unknown_gate_remains_0p01": True,
        },
        "required_outputs": [
            "product/tallwall120_material.h5",
            "product/tallwall120_material.json",
            "product/tallwall120_material.h5.checkpoint.json",
        ],
        "checkpoint_contract": {
            "schema": material.CHECKPOINT_SCHEMA,
            "policy": "content-addressed generation files; manifest pointer atomic; no generation overwrite",
            "generation_directory": "product/tallwall120_material.h5.checkpoints/",
            "resume_equivalence_required": True,
        },
        "depends_on": [] if short else ["core-f4-tallwall120-material-canary-s2-v1"],
        "resources": {
            "cpu_cores": 2,
            "ram_mib": 8192,
            "gpu_peak_mib": 0,
            "io_weight": 0.25,
        },
        "resource_estimate": {
            "basis": "completed H200 F4 native-MLS 151-frame s2 profile: 900 wall s / 1050 CPU s / 1,320,960,691 input bytes; scaled by terminal cell-04 H5 bytes and interval count with 30% margin",
            "source_bytes": SOURCE_H5.stat().st_size,
            "intervals": intervals,
            "wall_seconds_budget": wall,
            "cpu_user_seconds_budget": cpu,
            "io_read_bytes_budget": read_budget,
            "io_write_bytes_budget": 32 * 1024 * 1024,
            "peak_rss_mib_budget": 8192,
            "estimate_status": "planning estimate; no run started",
        },
        "timeout_seconds": max(3600 if not short else 900, wall + 600),
        "central_ledger_mutation": 0,
        "gpu_started": False,
        "launch_status": "proposal_only_root_review_required",
    }


def build(output_dir: Path) -> dict:
    source = verify_source()
    output_dir = Path(output_dir).resolve()
    evidence_dir = output_dir / "evidence"
    jobs_dir = output_dir / "jobs"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    jobs_dir.mkdir(parents=True, exist_ok=True)
    short = _spec(source, short=True)
    full = _spec(source, short=False)
    manifest = {
        "schema": "core.material.f4.tallwall120.proposal_bundle.v1",
        "created_at_utc": stamp(),
        "family": FAMILY,
        "scope_id": material.SCOPE_ID,
        "revision_id": material.REVISION_ID,
        "qualification_only": True,
        "qualification_claim": "none",
        "source": source,
        "source_definition": event_contract(),
        "code_bindings": [
            ref(TRACER, "versioned_tallwall120_material_tracer"),
            ref(CORE_MATERIAL, "shared_provider_and_event_primitives"),
            ref(NEIGHBOURS, "visible_support_shepard_backend"),
            ref(PASSIVE, "finite_wall_and_support_helpers"),
            ref(PROPOSAL_BUILDER, "proposal_builder"),
        ],
        "jobs": [short["job_id"], full["job_id"]],
        "execution": {
            "gpu_started": False,
            "central_ledger_mutation": 0,
            "submitted": False,
            "source_read_only": True,
        },
        "scientific_boundary": (
            "T1 native tallwall source integrity is root-verified, but this material overlay "
            "remains an uncalibrated diagnostic. A 4.34 s source cannot establish the one-time "
            "8.68 s extension; unresolved events remain right-censored."
        ),
    }
    manifest_path = evidence_dir / "f4-tallwall120-material-proposal-bundle-v1.json"
    short_path = jobs_dir / f"{short['job_id']}.json"
    full_path = jobs_dir / f"{full['job_id']}.json"
    for path, payload in ((manifest_path, manifest), (short_path, short), (full_path, full)):
        temporary = path.with_suffix(path.suffix + ".partial")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
        temporary.replace(path)
    return {
        "manifest": str(manifest_path),
        "manifest_sha256": sha256(manifest_path),
        "short": {"path": str(short_path), "sha256": sha256(short_path), "job_id": short["job_id"]},
        "full": {"path": str(full_path), "sha256": sha256(full_path), "job_id": full["job_id"]},
        "source_h5_sha256": SOURCE_H5_SHA256,
        "tracer_sha256": sha256(TRACER),
        "qualification_only": True,
        "submitted": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=LAB_ROOT / "campaigns/core-v1/material")
    args = parser.parse_args()
    print(json.dumps(build(args.output_root), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
