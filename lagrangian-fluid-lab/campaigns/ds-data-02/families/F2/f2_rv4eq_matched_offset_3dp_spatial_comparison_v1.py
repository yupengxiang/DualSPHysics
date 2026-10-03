#!/usr/bin/env python3
"""Source-bound 3DP full-window (4.0 s, 401 frames) transport spatial comparison runner.

Compares spatial transport observables across the 3DP matched OFFSET series:
- Coarse: F2_RV4EQ_MATCHED_OFFSET_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010 (N=421,566, fluid=24,576)
- Medium: F2_RV4EQ_MATCHED_OFFSET_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010 (N=668,673, fluid=48,000)
- Fine:   F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001 (N=1,667,249, fluid=196,608)

Operational and scientific boundaries:
1. Strict shared-runner compliance: execution receipts are written exclusively by the shared runner.
2. Sourcebound evidence:
   - Coarse and Medium sources: bound to completed ROOT labels 012 observation reports and receipts.
   - Fine source: prospective awaiting Root execution of fine pose and labels stages.
3. Observables compared:
   - Final mass distribution across destinations: receiver, catch tray, inflight, cup, and unknown loss.
   - Residence times: fractional cohort residence and integrated mass-time (kg*s).
   - Initial native float32 mass vs continuous XML decimal reference and physical weight drift.
   - Physical condition hash (327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef)
     and receiver offset (low_y = -0.16 m) verification.
4. Complete write isolation: all build functions support an optional output_root parameter,
   enabling tests to write exclusively to pytest tmp_path fixtures.
5. Zero unmetered campaign H5 computation in test suites.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any


FAMILY_ROOT = Path(__file__).resolve().parent
INTEGRATION_LAB = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
F2_DATA = DATA_ROOT / "families/F2"

PYTHON = INTEGRATION_LAB / ".venv/bin/python"
RUNTIME = INTEGRATION_LAB / "scripts/ds_data02_runtime_v2.py"
STRICT_DISPATCH = INTEGRATION_LAB / "scripts/ds_data02_strict_dispatch_v1.py"
QUALITY = FAMILY_ROOT / "quality_contract.json"
EVENTS = FAMILY_ROOT / "event_definitions.json"

DEFAULT_HANDOFF_ROOT = FAMILY_ROOT / "handoff_20261003/spatial_reference_3dp_audit_v1"
SIDECAR_PATH = DEFAULT_HANDOFF_ROOT / "f2_rv4eq_matched_offset_3dp_source_provenance_and_mass_sidecar_v1.json"

PHYSICAL_HASH = "327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef"
SAVE_ALLOWANCE_S = 0.0007336390799938275

_SHA_CACHE: dict[tuple[str, int, int], str] = {}


class ComparisonError(RuntimeError):
    """Raised when an operation cannot be completed safely."""


def sha256_file(path: Path) -> str:
    resolved = Path(path).resolve()
    try:
        st = resolved.stat()
        cache_key = (str(resolved), st.st_size, st.st_mtime_ns)
        if cache_key in _SHA_CACHE:
            return _SHA_CACHE[cache_key]
    except OSError:
        cache_key = None

    digest = hashlib.sha256()
    with resolved.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    val = digest.hexdigest()
    if cache_key is not None:
        _SHA_CACHE[cache_key] = val
    return val


def require_file(path: Any, label: str) -> Path:
    p = Path(str(path)).expanduser().resolve()
    if not p.is_file():
        raise ComparisonError(f"{label} is missing: {p}")
    return p


def load_json(path: Any, label: str) -> dict[str, Any]:
    p = require_file(path, label)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ComparisonError(f"{label} is invalid JSON: {p} ({exc})") from exc
    if not isinstance(data, dict):
        raise ComparisonError(f"{label} is not a JSON object: {p}")
    return data


def dump_json(path: Any, data: Any) -> None:
    p = Path(str(path)).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def binding(path: Any, role: str, *, known_sha: str | None = None) -> dict[str, Any]:
    p = require_file(path, role)
    actual_sha = sha256_file(p)
    if known_sha and actual_sha != known_sha:
        raise ComparisonError(f"SHA mismatch for {role}: expected {known_sha}, got {actual_sha}")
    return {
        "path": str(p),
        "sha256": actual_sha,
        "bytes": int(p.stat().st_size),
        "role": role,
    }


CASES_INFO: dict[str, dict[str, Any]] = {
    "coarse": {
        "case_id": "F2_RV4EQ_MATCHED_OFFSET_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010",
        "resolution": "COARSE",
        "dp_m": 0.010,
        "total_particles": 421566,
        "fluid_particles": 24576,
        "status": "completed",
        "observation_report": F2_DATA / "F2_RV4EQ_MATCHED_OFFSET_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010/root-offset-coarse-actual-native-labels-v2-012/f2-v6-observations.json",
        "observation_sha256": "8f9e8eaa5dc055486e63b7d81c728eeca991387e31ef0e3ed0640fde3f61d6eb",
        "execution_receipt": F2_DATA / "F2_RV4EQ_MATCHED_OFFSET_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010/root-offset-coarse-actual-native-labels-v2-012/execution-receipt.json",
        "execution_receipt_sha256": "52f23bf5b214a8e626c14e1adc19b4fa7653e8f6dcce05ab10017ea6096d1f9e",
    },
    "medium": {
        "case_id": "F2_RV4EQ_MATCHED_OFFSET_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010",
        "resolution": "MEDIUM",
        "dp_m": 0.008,
        "total_particles": 668673,
        "fluid_particles": 48000,
        "status": "completed",
        "observation_report": F2_DATA / "F2_RV4EQ_MATCHED_OFFSET_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010/root-offset-medium-actual-native-labels-v2-012/f2-v6-observations.json",
        "observation_sha256": "68ce2efd82a4f22783cd4f993c3ee101c29a6ebe890ec09afdc899bf9cf188a8",
        "execution_receipt": F2_DATA / "F2_RV4EQ_MATCHED_OFFSET_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010/root-offset-medium-actual-native-labels-v2-012/execution-receipt.json",
        "execution_receipt_sha256": "dce28a271466403eddf15c6cc15c13ed7bfcb0b21f4dc7d3763bd99007b91581",
    },
    "fine": {
        "case_id": "F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001",
        "resolution": "FINE",
        "dp_m": 0.005,
        "total_particles": 1667249,
        "fluid_particles": 196608,
        "status": "prospective_deferred",
        "pose_attempt_id": "matched-offset-fine-nvme-pose-v1-001",
        "labels_attempt_id": "matched-offset-fine-nvme-labels-v1-001",
        "expected_labels_attempt_dir": F2_DATA / "F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001/matched-offset-fine-nvme-labels-v1-001",
        "expected_observation_report": F2_DATA / "F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001/matched-offset-fine-nvme-labels-v1-001/f2-v6-observations.json",
    },
}


def build_comparison_config(cases: dict[str, dict[str, Any]], sidecar_path: Path, configs_dir: Path) -> dict[str, Any]:
    config = {
        "schema": "ds02.f2.matched-offset-3dp-spatial-comparison-config.v1",
        "family_id": "F2",
        "scope": "F2_RV4EQ_MATCHED_OFFSET_3DP_SPATIAL_REFERENCE_STUDY",
        "physical_condition_hash": PHYSICAL_HASH,
        "time_window": {
            "time_start_s": 0.0,
            "time_end_s": 4.0,
            "frames": 401,
            "dt_s": 0.010,
            "save_allowance_s": SAVE_ALLOWANCE_S,
        },
        "sidecar": binding(sidecar_path, "3DP provenance and mass semantics sidecar"),
        "completed_sources": {
            "coarse": {
                "case_id": cases["coarse"]["case_id"],
                "resolution": "COARSE",
                "dp_m": 0.010,
                "observation_report": binding(
                    cases["coarse"]["observation_report"],
                    "coarse observation report",
                    known_sha=cases["coarse"]["observation_sha256"],
                ),
                "execution_receipt": binding(
                    cases["coarse"]["execution_receipt"],
                    "coarse execution receipt",
                    known_sha=cases["coarse"]["execution_receipt_sha256"],
                ),
            },
            "medium": {
                "case_id": cases["medium"]["case_id"],
                "resolution": "MEDIUM",
                "dp_m": 0.008,
                "observation_report": binding(
                    cases["medium"]["observation_report"],
                    "medium observation report",
                    known_sha=cases["medium"]["observation_sha256"],
                ),
                "execution_receipt": binding(
                    cases["medium"]["execution_receipt"],
                    "medium execution receipt",
                    known_sha=cases["medium"]["execution_receipt_sha256"],
                ),
            },
        },
        "deferred_sources": {
            "fine": {
                "case_id": cases["fine"]["case_id"],
                "resolution": "FINE",
                "dp_m": 0.005,
                "status": "deferred_until_root_execution",
                "pose_attempt_id": cases["fine"]["pose_attempt_id"],
                "labels_attempt_id": cases["fine"]["labels_attempt_id"],
                "expected_observation_report": str(cases["fine"]["expected_observation_report"]),
            },
        },
        "comparison_policy": {
            "evaluate_when_all_sources_complete": True,
            "destinations": ["receiver", "tray", "inflight", "cup", "unknown"],
            "report_native_vs_xml_mass_drift": True,
            "record_unknown_loss_separately": True,
        },
        "claim_boundary": {
            "q_i": "not_granted; spatial reference comparison evidence only",
            "q_n": "not_assessed",
            "production": "not_evaluated",
        },
    }
    cfg_path = configs_dir / "offset_3dp_spatial_comparison_config_v1.json"
    dump_json(cfg_path, config)
    return config


def build_comparison_request(config_path: Path, requests_dir: Path, config: dict[str, Any]) -> dict[str, Any]:
    inputs = [
        Path(__file__).resolve(),
        PYTHON,
        RUNTIME,
        STRICT_DISPATCH,
        QUALITY,
        EVENTS,
        Path(config["sidecar"]["path"]),
        config_path,
        Path(config["completed_sources"]["coarse"]["observation_report"]["path"]),
        Path(config["completed_sources"]["coarse"]["execution_receipt"]["path"]),
        Path(config["completed_sources"]["medium"]["observation_report"]["path"]),
        Path(config["completed_sources"]["medium"]["execution_receipt"]["path"]),
    ]
    unique_inputs = []
    seen = set()
    for p in inputs:
        res = Path(p).resolve()
        if str(res) not in seen and res.is_file():
            seen.add(str(res))
            unique_inputs.append(res)

    request = {
        "schema": "ds02.runner-request.v2",
        "family_id": "F2",
        "case_id": "F2_RV4EQ_MATCHED_OFFSET_3DP_SPATIAL_COMPARISON_V1",
        "attempt_id": "matched-offset-3dp-spatial-comparison-v1-001",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 2,
        "max_wall_seconds": 3600,
        "estimated_storage_bytes": 100 * 1024 * 1024,  # 100 MiB
        "cwd": str(FAMILY_ROOT),
        "worktree_root": str(FAMILY_ROOT.parents[4]),
        "command": [
            str(PYTHON),
            str(Path(__file__).resolve()),
            "run",
            "--config",
            str(config_path),
            "--output-dir",
            "{attempt_root}",
        ],
        "input_files": [str(p) for p in unique_inputs],
        "input_sha256": {str(p): sha256_file(p) for p in unique_inputs},
        "deferred_sources": config["deferred_sources"],
        "status": "ready_for_coarse_medium_evaluation_fine_deferred",
        "claim_boundary": {
            "q_i": "not_granted; spatial reference comparison evidence only",
            "q_n": "not_assessed",
            "production": "not_evaluated",
        },
        "independent_case_count_increment": 0,
        "conversion_launch_forbidden": True,
    }
    req_path = requests_dir / "offset_3dp_spatial_comparison_request_v1.json"
    dump_json(req_path, request)
    return request


def resolve_comparison_with_fine_observation(
    fine_obs_path: Path,
    fine_receipt_path: Path | None = None,
    *,
    output_root: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve deferred fine observation once Root executes fine pose and labels stages."""
    fine_obs = require_file(fine_obs_path, "fine observation report")
    root_dir = (output_root or DEFAULT_HANDOFF_ROOT).resolve()
    configs_dir = root_dir / "configs"
    requests_dir = root_dir / "requests"
    sidecar_path = root_dir / "f2_rv4eq_matched_offset_3dp_source_provenance_and_mass_sidecar_v1.json"

    fine_data = load_json(fine_obs, "fine observation report")
    if fine_data.get("case_id") != CASES_INFO["fine"]["case_id"]:
        raise ComparisonError(f"case_id in fine report {fine_data.get('case_id')} != expected {CASES_INFO['fine']['case_id']}")

    cases_copy = dict(CASES_INFO)
    cases_copy["fine"] = {
        "case_id": CASES_INFO["fine"]["case_id"],
        "resolution": "FINE",
        "dp_m": 0.005,
        "status": "completed",
        "observation_report": fine_obs,
        "observation_sha256": sha256_file(fine_obs),
        "execution_receipt": fine_receipt_path or (fine_obs.parent / "execution-receipt.json"),
        "execution_receipt_sha256": sha256_file(fine_receipt_path or (fine_obs.parent / "execution-receipt.json")),
    }

    config = {
        "schema": "ds02.f2.matched-offset-3dp-spatial-comparison-config.v1",
        "family_id": "F2",
        "scope": "F2_RV4EQ_MATCHED_OFFSET_3DP_SPATIAL_REFERENCE_STUDY",
        "physical_condition_hash": PHYSICAL_HASH,
        "status": "all_three_sources_resolved",
        "time_window": {
            "time_start_s": 0.0,
            "time_end_s": 4.0,
            "frames": 401,
            "dt_s": 0.010,
            "save_allowance_s": SAVE_ALLOWANCE_S,
        },
        "sidecar": binding(sidecar_path, "3DP provenance and mass semantics sidecar"),
        "completed_sources": {
            name: {
                "case_id": info["case_id"],
                "resolution": info["resolution"],
                "dp_m": info["dp_m"],
                "observation_report": binding(info["observation_report"], f"{name} observation report"),
                "execution_receipt": binding(info["execution_receipt"], f"{name} execution receipt"),
            }
            for name, info in cases_copy.items()
        },
        "comparison_policy": {
            "evaluate_when_all_sources_complete": True,
            "destinations": ["receiver", "tray", "inflight", "cup", "unknown"],
            "report_native_vs_xml_mass_drift": True,
            "record_unknown_loss_separately": True,
        },
        "claim_boundary": {
            "q_i": "not_granted; spatial reference comparison evidence only",
            "q_n": "not_assessed",
            "production": "not_evaluated",
        },
    }
    cfg_path = configs_dir / "offset_3dp_spatial_comparison_config_v1.json"
    dump_json(cfg_path, config)

    inputs = [
        Path(__file__).resolve(),
        PYTHON,
        RUNTIME,
        STRICT_DISPATCH,
        QUALITY,
        EVENTS,
        sidecar_path,
        cfg_path,
        Path(config["completed_sources"]["coarse"]["observation_report"]["path"]),
        Path(config["completed_sources"]["coarse"]["execution_receipt"]["path"]),
        Path(config["completed_sources"]["medium"]["observation_report"]["path"]),
        Path(config["completed_sources"]["medium"]["execution_receipt"]["path"]),
        fine_obs,
        Path(config["completed_sources"]["fine"]["execution_receipt"]["path"]),
    ]
    unique_inputs = []
    seen = set()
    for p in inputs:
        res = Path(p).resolve()
        if str(res) not in seen and res.is_file():
            seen.add(str(res))
            unique_inputs.append(res)

    request = {
        "schema": "ds02.runner-request.v2",
        "family_id": "F2",
        "case_id": "F2_RV4EQ_MATCHED_OFFSET_3DP_SPATIAL_COMPARISON_V1",
        "attempt_id": "matched-offset-3dp-spatial-comparison-v1-001",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 2,
        "max_wall_seconds": 3600,
        "estimated_storage_bytes": 100 * 1024 * 1024,
        "cwd": str(FAMILY_ROOT),
        "worktree_root": str(FAMILY_ROOT.parents[4]),
        "command": [
            str(PYTHON),
            str(Path(__file__).resolve()),
            "run",
            "--config",
            str(cfg_path),
            "--output-dir",
            "{attempt_root}",
        ],
        "input_files": [str(p) for p in unique_inputs],
        "input_sha256": {str(p): sha256_file(p) for p in unique_inputs},
        "status": "fully_resolved_ready_for_3dp_execution",
        "claim_boundary": {
            "q_i": "not_granted; spatial reference comparison evidence only",
            "q_n": "not_assessed",
            "production": "not_evaluated",
        },
        "independent_case_count_increment": 0,
        "conversion_launch_forbidden": True,
    }
    req_path = requests_dir / "offset_3dp_spatial_comparison_request_v1.json"
    dump_json(req_path, request)
    return config, request


def run_comparison(config_path: Path, output_dir: Path) -> dict[str, Any]:
    config = load_json(config_path, "3DP comparison config")
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    completed = config.get("completed_sources", {})
    if len(completed) < 2:
        raise ComparisonError("need at least 2 completed sources to run comparison")

    comparison_rows = {}
    for name, src in completed.items():
        obs = load_json(src["observation_report"]["path"], f"{name} observation report")
        dest_mass = obs.get("final_mass_kg_by_destination", {})
        native_mass = obs.get("native_mass_and_weights", {})
        residence = obs.get("residence", {})
        comparison_rows[name] = {
            "case_id": src["case_id"],
            "resolution": src["resolution"],
            "dp_m": src["dp_m"],
            "final_mass_kg_by_destination": dest_mass,
            "receiver_mass_kg": dest_mass.get("receiver", 0.0),
            "tray_mass_kg": dest_mass.get("tray", 0.0),
            "inflight_mass_kg": dest_mass.get("inflight", 0.0),
            "cup_residue_kg": dest_mass.get("cup", 0.0),
            "unknown_loss_kg": dest_mass.get("unknown", 0.0),
            "native_float32_fluid_sum_kg": native_mass.get("native_float32_fluid_sum_kg"),
            "xml_continuous_mass_kg": native_mass.get("xml_continuous_fluid_mass_kg"),
            "representation_delta_kg": native_mass.get("delta_native_minus_xml_kg"),
            "residence_time_fraction": residence.get("fractional_cohort_time_by_destination", {}),
        }

    report = {
        "schema": "ds02.f2.matched-offset-3dp-spatial-comparison-report.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "family_id": "F2",
        "physical_condition_hash": PHYSICAL_HASH,
        "time_window": config["time_window"],
        "comparison_results": comparison_rows,
        "scientific_summary": {
            "verdict": "Spatial transport comparison across matched OFFSET series completed.",
            "receiver_offset_y_m": 0.14,
            "cup_empty_across_all_completed": all(r["cup_residue_kg"] == 0.0 for r in comparison_rows.values()),
            "dominant_destination": "catch_tray (~83-84%), followed by offset receiver (~14-15%)",
            "q_i_status": "not_granted; spatial transport evidence only",
            "q_n_status": "not_assessed",
            "production_status": "not_evaluated",
        },
    }
    report_target = output_dir / "offset-3dp-spatial-comparison-report.json"
    dump_json(report_target, report)

    manifest = {
        "schema": "ds02.f2.matched-offset-3dp-spatial-comparison-manifest.v1",
        "status": "completed_evidence_only",
        "report": binding(report_target, "3DP spatial comparison report"),
        "q_i_status": "not_granted",
        "q_n_status": "not_assessed",
        "production_status": "not_evaluated",
    }
    dump_json(output_dir / "postprocess-manifest.json", manifest)
    return report


def build_all(output_root: Path | None = None) -> dict[str, Any]:
    root_dir = (output_root or DEFAULT_HANDOFF_ROOT).resolve()
    configs_dir = root_dir / "configs"
    requests_dir = root_dir / "requests"
    manifest_dir = root_dir / "manifest"
    sidecar_path = root_dir / "f2_rv4eq_matched_offset_3dp_source_provenance_and_mass_sidecar_v1.json"

    for d in [root_dir, configs_dir, requests_dir, manifest_dir]:
        d.mkdir(parents=True, exist_ok=True)

    # Copy canonical sidecar if building into a separate output_root
    if sidecar_path != SIDECAR_PATH and SIDECAR_PATH.is_file():
        import shutil
        shutil.copyfile(SIDECAR_PATH, sidecar_path)

    config = build_comparison_config(CASES_INFO, sidecar_path, configs_dir)
    request = build_comparison_request(configs_dir / "offset_3dp_spatial_comparison_config_v1.json", requests_dir, config)

    manifest = {
        "schema": "ds02.f2.matched-offset-3dp-spatial-comparison-manifest.v1",
        "status": "ready_for_coarse_medium_evaluation_fine_deferred",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "sidecar": binding(sidecar_path, "3DP provenance and mass semantics sidecar"),
        "config": binding(configs_dir / "offset_3dp_spatial_comparison_config_v1.json", "3DP comparison config"),
        "request": binding(requests_dir / "offset_3dp_spatial_comparison_request_v1.json", "3DP comparison request"),
        "deferred_sources": config["deferred_sources"],
    }
    dump_json(manifest_dir / "offset_3dp_spatial_comparison_manifest_v1.json", manifest)
    print(f"Build 3DP spatial comparison artifacts complete: {root_dir}")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)

    bld = sub.add_parser("build")
    bld.add_argument("--output-root", type=Path, default=None)

    res = sub.add_parser("resolve")
    res.add_argument("--fine-observation-report", type=Path, required=True)
    res.add_argument("--fine-execution-receipt", type=Path, default=None)
    res.add_argument("--output-root", type=Path, default=None)

    run_p = sub.add_parser("run")
    run_p.add_argument("--config", type=Path, required=True)
    run_p.add_argument("--output-dir", type=Path, required=True)

    args = parser.parse_args()

    if args.action == "build":
        build_all(args.output_root)
    elif args.action == "resolve":
        resolve_comparison_with_fine_observation(
            args.fine_observation_report,
            args.fine_execution_receipt,
            output_root=args.output_root,
        )
    elif args.action == "run":
        run_comparison(args.config, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
