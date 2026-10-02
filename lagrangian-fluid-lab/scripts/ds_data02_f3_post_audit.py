#!/usr/bin/env python3
"""Post-audit an already completed F3 native HDF5 artifact.

This is deliberately separate from ``ds_data02_f3_weak.py``.  The latter can
time out after the streaming conversion has completed while it is rendering
the full audit.  This module consumes that immutable output, verifies the
parent timeout and the inner conversion evidence, and then performs a bounded
Q-I audit.  It never invokes a solver, decoder, PartVTK, model, or GPU.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import resource
import sys
import time
from typing import Any, Mapping

import h5py


LAB = Path(__file__).resolve().parents[1]
if str(LAB / "scripts") not in sys.path:
    sys.path.insert(0, str(LAB / "scripts"))

from ds_data02_integrity import audit_hdf5  # noqa: E402


SCHEMA = "ds02.f3.post-audit-rebind.v1"
EXPECTED_FRAMES = 8001
EXPECTED_PARTICLES = 108000


def sha256_file(path: Path, *, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def first_record(value: Any) -> Mapping[str, Any]:
    if isinstance(value, list):
        if len(value) != 1 or not isinstance(value[0], Mapping):
            raise ValueError("expected a single-record JSON list")
        return value[0]
    if not isinstance(value, Mapping):
        raise ValueError("expected a JSON object")
    return value


def resource_snapshot() -> dict[str, Any]:
    def usage(which: int) -> dict[str, Any]:
        value = resource.getrusage(which)
        return {
            "user_cpu_seconds": float(value.ru_utime),
            "system_cpu_seconds": float(value.ru_stime),
            "max_rss_kib": int(value.ru_maxrss),
            "minor_page_faults": int(value.ru_minflt),
            "major_page_faults": int(value.ru_majflt),
            "in_block": int(value.ru_inblock),
            "out_block": int(value.ru_oublock),
            "voluntary_context_switches": int(value.ru_nvcsw),
            "involuntary_context_switches": int(value.ru_nivcsw),
        }

    return {"self": usage(resource.RUSAGE_SELF), "children": usage(resource.RUSAGE_CHILDREN)}


def verify_parent_timeout(parent: Mapping[str, Any], hdf5: Path) -> dict[str, Any]:
    request = parent.get("request")
    command = parent.get("command")
    output_root = Path(str(parent.get("output_root", ""))).resolve()
    expected_root = hdf5.resolve().parent
    # The runner receipt records the qualification state at the receipt level;
    # older F3 requests also carry a human-readable request claim.  Require
    # both forms to remain explicitly unqualified, while accepting the
    # existing request wording ("none; ... remains not assessed").
    request_claim = request.get("qualification_claim") if isinstance(request, Mapping) else None
    request_unqualified = (
        isinstance(request_claim, str)
        and request_claim.lower().startswith("none")
        and (request_claim.strip().lower() == "none" or "not assessed" in request_claim.lower())
    )
    receipt_unqualified = (
        parent.get("numerical_reference_status") == "not_assessed"
        and parent.get("production_product_acceptance") == "not_assessed"
    )
    checks = {
        "status_failed": parent.get("status") == "failed",
        "returncode_sigterm": parent.get("returncode") == -15,
        "wall_timeout": parent.get("termination_reason") == "reserved_wall_time_exceeded",
        "output_root_matches_hdf5": output_root == expected_root,
        "input_hashes_unchanged": parent.get("input_hashes_at_launch") == parent.get("input_hashes_after_run"),
        "request_claim_remains_unqualified": (
            request_unqualified or receipt_unqualified
        ),
    }
    if isinstance(command, list):
        rendered = [str(value) for value in command]
        checks["parent_command_targets_hdf5"] = any(str(expected_root / "trajectory.h5") == value for value in rendered)
    else:
        checks["parent_command_targets_hdf5"] = False
    return {
        "receipt_status": parent.get("status"),
        "termination_reason": parent.get("termination_reason"),
        "elapsed_seconds": parent.get("elapsed_seconds"),
        "receipt_path_output_root": str(output_root),
        "checks": checks,
        "all_checks_pass": all(checks.values()),
        "reuse_semantics": "immutable H5/direct report retained from a parent conversion attempt that timed out during downstream audit; no failed receipt or artifact was patched",
    }


def verify_direct_report(report: Mapping[str, Any], hdf5: Path, actual_sha: str) -> dict[str, Any]:
    provenance = report.get("source_provenance", {})
    raw_tree = provenance.get("raw_tree", {}) if isinstance(provenance, Mapping) else {}
    partvtk = report.get("partvtk_validation", {})
    lifecycle = report.get("lifecycle", {})
    typed = report.get("typed_identity", {})
    checks = {
        "conversion_completed": report.get("conversion_status") == "completed",
        "output_path_matches": Path(str(report.get("output_hdf5", ""))).resolve() == hdf5.resolve(),
        "output_sha256_matches": report.get("output_sha256") == actual_sha,
        "expected_frames": report.get("frames") == EXPECTED_FRAMES,
        "expected_particles": report.get("particles") == EXPECTED_PARTICLES,
        "partvtk_first_middle_final": bool(partvtk.get("all_passed")) and len(partvtk.get("frames", [])) == 3,
        "raw_tree_unchanged": raw_tree.get("unchanged") is True and raw_tree.get("before_tree_sha256") == raw_tree.get("after_tree_sha256"),
        "no_transient_missing": lifecycle.get("transient_missing_frame_count") == 0,
        "q_n_not_assessed": report.get("q_n_status") == "not_assessed",
    }
    return {
        "report_schema": report.get("schema"),
        "frames": report.get("frames"),
        "particles": report.get("particles"),
        "reported_output_sha256": report.get("output_sha256"),
        "raw_tree": {
            "before_tree_sha256": raw_tree.get("before_tree_sha256"),
            "after_tree_sha256": raw_tree.get("after_tree_sha256"),
            "unchanged": raw_tree.get("unchanged"),
            "before_file_count": raw_tree.get("before_file_count"),
            "after_file_count": raw_tree.get("after_file_count"),
        },
        "typed_identity": {
            "key": typed.get("key"),
            "observed_types": typed.get("observed_types"),
            "observed_mks": typed.get("observed_mks"),
            "initial_exclusion_ledger": typed.get("initial_exclusion_ledger"),
        },
        "partvtk_validation": partvtk,
        "checks": checks,
        "all_checks_pass": all(checks.values()),
    }


def verify_native_accounting(accounting: Mapping[str, Any], hdf5: Path) -> dict[str, Any]:
    facts = accounting.get("facts", {})
    with h5py.File(hdf5, "r") as handle:
        frames = int(handle["time"].shape[0])
        particles = int(handle["particle_id"].shape[0])
        first_time = float(handle["time"][0])
        last_time = float(handle["time"][-1])
    csv_summary = facts.get("run_csv_summary", {})
    checks = {
        "frames_match_hdf5": facts.get("saved_frames") == frames == EXPECTED_FRAMES,
        "particles_match_hdf5": facts.get("final_total_particles") == particles == EXPECTED_PARTICLES,
        "first_time_zero": first_time == 0.0,
        "final_time_matches_accounting": abs(last_time - float(facts.get("final_time_s"))) <= 1e-9,
        "run_csv_frames_match": csv_summary.get("part_files") == frames,
        "npout_zero_full_window": facts.get("excluded_interval_sums", {}).get("NpOut") == 0,
        "solver_dimension_3": accounting.get("solver_dimension") == 3,
        "q_n_not_assessed": accounting.get("q_n_status") == "not_assessed",
    }
    return {
        "attempt_id": accounting.get("attempt_id"),
        "facts": {
            "saved_frames": facts.get("saved_frames"),
            "final_time_s": facts.get("final_time_s"),
            "internal_steps": facts.get("internal_steps"),
            "run_out_parameters": facts.get("run_out_parameters"),
            "run_csv_summary": csv_summary,
            "excluded_interval_sums": facts.get("excluded_interval_sums"),
        },
        "checks": checks,
        "all_checks_pass": all(checks.values()),
    }


def verify_label_hdf5(labels: Path, source: Path, source_sha: str) -> dict[str, Any]:
    label_sha = sha256_file(labels)
    with h5py.File(labels, "r") as handle:
        attrs = {str(key): (value.item() if hasattr(value, "item") else value) for key, value in handle.attrs.items()}
        shapes = {name: list(obj.shape) for name, obj in handle.items() if isinstance(obj, h5py.Dataset)}
        required = {
            "time": (EXPECTED_FRAMES,),
            "particle_id": (EXPECTED_PARTICLES,),
            "particle_zone": (EXPECTED_PARTICLES,),
            "destination_time_series": (EXPECTED_FRAMES, EXPECTED_PARTICLES),
            "final_category": (EXPECTED_PARTICLES,),
            "first_passage_interval": (EXPECTED_PARTICLES, 3, 2),
            "residence_time_s": (EXPECTED_PARTICLES, 2),
        }
        checks = {
            "complete": attrs.get("complete") is True,
            "source_hdf5_sha256_matches": attrs.get("source_hdf5_sha256") == source_sha,
            "source_hdf5_path_matches": Path(str(attrs.get("source_hdf5", ""))).resolve() == source.resolve(),
            "q_n_not_assessed": attrs.get("q_n_status") == "not_assessed",
            "required_shapes": all(tuple(shapes.get(name, [])) == shape for name, shape in required.items()),
        }
    return {
        "sha256": label_sha,
        "attrs": {key: attrs.get(key) for key in ("schema", "complete", "source_hdf5_sha256", "initial_fluid_mass_kg", "q_n_status")},
        "shapes": shapes,
        "checks": checks,
        "all_checks_pass": all(checks.values()),
    }


def build_metadata(owner: Mapping[str, Any], direct: Mapping[str, Any]) -> dict[str, Any]:
    binding = owner["physical_binding"]
    return {
        "units": {"time": "s", "position": "m", "velocity": "m/s", "density": "kg/m^3", "mass": "kg", "pressure": "Pa"},
        "coordinate_frame": "DualSPHysics case Cartesian coordinates (x,y,z)",
        "solver_dimension": 3,
        "geometry": binding["geometry"],
        "geometry_source": {
            "path": owner.get("source_definition"),
            "sha256": direct.get("source_provenance", {}).get("generated_xml", {}).get("sha256"),
            "continuous_geometry_reference_sha256": direct.get("source_provenance", {}).get("geometry_reference_sha256"),
        },
        "control": binding["controls"],
        "control_source": {
            "path": owner.get("source_control"),
            "sha256": owner.get("source_control_sha256"),
        },
        "boundary_mode": "open_system",
        "boundary_detail": binding.get("open_inlet"),
        "lifecycle_mode": "fixed_initial_identity_axis_no_births; open-top exit is right-censored in labels",
    }


def post_audit(*, hdf5: Path, direct_report_path: Path, parent_receipt_path: Path,
               accounting_path: Path, labels_path: Path, solver_log: Path,
               owner_path: Path, raw_manifest_path: Path, particle_chunk: int,
               expected_hdf5_sha256: str | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    before = resource_snapshot()
    direct = first_record(load_json(direct_report_path))
    parent = first_record(load_json(parent_receipt_path))
    accounting = first_record(load_json(accounting_path))
    owner = first_record(load_json(owner_path))
    source_sha = sha256_file(hdf5)
    if expected_hdf5_sha256 is not None and source_sha != expected_hdf5_sha256:
        raise ValueError(f"HDF5 SHA-256 mismatch: expected {expected_hdf5_sha256}, observed {source_sha}")
    parent_check = verify_parent_timeout(parent, hdf5)
    direct_check = verify_direct_report(direct, hdf5, source_sha)
    accounting_check = verify_native_accounting(accounting, hdf5)
    label_check = verify_label_hdf5(labels_path, hdf5, source_sha)
    metadata = build_metadata(owner, direct)
    integrity = audit_hdf5(hdf5, solver_log=solver_log, metadata=metadata, particle_chunk=particle_chunk)
    checks = {
        "parent_timeout_rebound": parent_check["all_checks_pass"],
        "direct_report_rebound": direct_check["all_checks_pass"],
        "native_accounting_rebound": accounting_check["all_checks_pass"],
        "full_label_hdf5_rebound": label_check["all_checks_pass"],
        "integrity_not_error": integrity.get("q_i_status") not in {"Q-I-audit-error", "Q-I-structure-fail"},
    }
    after = resource_snapshot()
    return {
        "schema": SCHEMA,
        "audit_claim": "independent post-audit/rebind of a completed native conversion artifact; Q-N and production remain unassessed",
        "source_hdf5": {
            "path": str(hdf5), "sha256": source_sha, "expected_sha256": expected_hdf5_sha256,
            "bytes": hdf5.stat().st_size,
        },
        "parent_conversion_timeout": parent_check,
        "direct_conversion_evidence": direct_check,
        "native_accounting_evidence": accounting_check,
        "full_label_hdf5_evidence": label_check,
        "raw_frame_manifest": {"path": str(raw_manifest_path), "sha256": sha256_file(raw_manifest_path)},
        "integrity_audit": integrity,
        "checks": checks,
        "all_rebind_checks_pass": all(checks.values()),
        "q_i_status": integrity.get("q_i_status", "Q-I-audit-error"),
        "q_n_status": "not_assessed",
        "production_eligibility": "not_evaluated",
        "resource_usage": {"before": before, "after": after},
        "wall_seconds": time.perf_counter() - started,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hdf5", type=Path, required=True)
    parser.add_argument("--direct-report", type=Path, required=True)
    parser.add_argument("--parent-receipt", type=Path, required=True)
    parser.add_argument("--native-accounting", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--solver-log", type=Path, required=True)
    parser.add_argument("--owner-metadata", type=Path, required=True)
    parser.add_argument("--raw-manifest", type=Path, required=True)
    parser.add_argument("--expected-hdf5-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--particle-chunk", type=int, default=65536)
    args = parser.parse_args(argv)
    report = post_audit(
        hdf5=args.hdf5, direct_report_path=args.direct_report, parent_receipt_path=args.parent_receipt,
        accounting_path=args.native_accounting, labels_path=args.labels, solver_log=args.solver_log,
        owner_path=args.owner_metadata, raw_manifest_path=args.raw_manifest, particle_chunk=args.particle_chunk,
        expected_hdf5_sha256=args.expected_hdf5_sha256,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "q_i_status": report["q_i_status"], "all_rebind_checks_pass": report["all_rebind_checks_pass"], "q_n_status": report["q_n_status"]}, sort_keys=True))
    return 0 if report["all_rebind_checks_pass"] and report["q_i_status"] not in {"Q-I-audit-error", "Q-I-structure-fail"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
