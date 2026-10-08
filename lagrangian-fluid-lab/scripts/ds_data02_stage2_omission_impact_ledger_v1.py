#!/usr/bin/env python3
"""Build an immutable per-case impact ledger from the all-118 native probe.

This consumer separates four evidence scopes that are easy to conflate:

* the native solver motive (position/density/movement),
* conversion metadata and its still-unclosed converter-source provenance,
* source-visible missing mass and censoring brackets, and
* physical fate, legal flux, and dynamics, which remain UNKNOWN.

It consumes the completed small sidecars and the v2 probe report.  It never
opens trajectory HDF5, raw PartOut binaries, or native trajectory data.  A
completed conversion report is checked for output path/SHA metadata only; that
does not grant a converter-source or physical-dynamics claim.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any


SCRIPT = Path(__file__).resolve()
WORKTREE_ROOT = SCRIPT.parents[2]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
SOURCE_REPORT_DEFAULT = DATA_ROOT / (
    "families/infra/STAGE2_OMISSION_MECHANISM_BOUNDS_118_V1/"
    "omission-mechanism-bounds-v2-primary-001-v5/omission-mechanism-bounds-v2.json"
)
PROBE_SCHEMA = "ds02.stage2.omission-mechanism-probe.v2"
PROBE_STATUS = "MECHANISM_PROBE_SOURCE_CLOSED_NO_H5"
OUTPUT_SCHEMA = "ds02.stage2.omission-impact-ledger.v1"
MANIFEST_SCHEMA = "ds02.stage2.omission-impact-ledger-manifest.v1"
SOURCE_SCHEMA = "ds02.stage2.omission-mechanism-bounds.v1"
SOURCE_STATUS = "MECHANISM_BOUNDS_AUDITED_TYPED_NATIVE_SOURCE_CLOSED"
FAMILY_COUNTS = {"F2": 48, "F4": 22, "F6": 48}
MASS_GATE = 0.003
H5_SUFFIXES = {".h5", ".hdf5", ".obi4"}
FAMILY_CONTROLS = {
    "F2": {
        "control_id": "F2_NUMERICAL_DOMAIN_ONLY_PAIRED_CONTROL_V1",
        "factor": "simulation-domain numerical bounds only",
        "preserve": ["CURRENT physical identity", "initial BI4/source set", "mass and dp/CFL", "wetted geometry and motion", "physics and observation window"],
    },
    "F4": {
        "control_id": "F4_DENSITY_GATE_DIAGNOSTIC_CONTROL_V1",
        "factor": "RhopOut gate only, under a separately source-closed sensitivity request",
        "preserve": ["CURRENT physical identity", "initial BI4/source set", "mass and dp/CFL", "MapRealPos/wetted geometry", "motion and physics"],
    },
    "F6": {
        "control_id": "F6_NUMERICAL_DOMAIN_ONLY_WALL_FIXED_CONTROL_V1",
        "factor": "simulation-domain numerical bounds only, wall/body condition fixed",
        "preserve": ["CURRENT physical identity", "initial BI4/source set", "sample/body mass separation", "wetted wall and rigid motion", "mass, dp/CFL and physics"],
    },
}


class LedgerError(RuntimeError):
    """Raised when an impact ledger binding or claim boundary is invalid."""


def sha256(value: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(value).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(value: Path | str, label: str, *, allow_h5: bool = False) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise LedgerError(f"{label} is missing: {path}")
    if not allow_h5 and (path.suffix.lower() in H5_SUFFIXES or (path.name.startswith("Part_") and path.name.endswith(".bi4"))):
        raise LedgerError(f"trajectory/raw PartOut input is forbidden: {path}")
    return path


def read_json(value: Path | str, label: str) -> tuple[Path, dict[str, Any]]:
    path = require_file(value, label)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LedgerError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise LedgerError(f"{label} is not an object: {path}")
    return path, payload


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise LedgerError(f"refuse to overwrite existing output: {path}")
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def binding(value: Path | str, label: str, expected: str | None = None) -> dict[str, Any]:
    path = require_file(value, label)
    digest = sha256(path)
    if expected is not None and digest != expected:
        raise LedgerError(f"{label} digest differs: {path}")
    return {"path": str(path), "sha256": digest, "bytes": path.stat().st_size}


def finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise LedgerError(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise LedgerError(f"{label} is not finite")
    return result


def close(left: Any, right: Any, *, abs_tol: float = 2e-9, rel_tol: float = 2e-12) -> bool:
    try:
        return math.isclose(float(left), float(right), abs_tol=abs_tol, rel_tol=rel_tol)
    except (TypeError, ValueError):
        return False


def source_cases(source_report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if source_report.get("schema") != SOURCE_SCHEMA or source_report.get("status") != SOURCE_STATUS:
        raise LedgerError("source report schema/status is not the completed all-118 ledger")
    cases = source_report.get("cases")
    if not isinstance(cases, list) or len(cases) != 118:
        raise LedgerError("source report does not contain exactly 118 cases")
    by_key = {str(case.get("case_key")): case for case in cases}
    if len(by_key) != len(cases):
        raise LedgerError("source report case keys are not unique")
    counts = Counter(str(case.get("family_id")) for case in cases)
    if dict(sorted(counts.items())) != dict(sorted(FAMILY_COUNTS.items())):
        raise LedgerError(f"source report family membership differs: {dict(sorted(counts.items()))}")
    return by_key


def probe_cases(probe_report: dict[str, Any], source_sha: str) -> dict[str, dict[str, Any]]:
    if probe_report.get("schema") != PROBE_SCHEMA or probe_report.get("status") != PROBE_STATUS:
        raise LedgerError("probe report schema/status is not completed v2 source-closed output")
    policy = probe_report.get("read_policy", {})
    forbidden = ("h5_opened", "trajectory_content_opened", "raw_partout_opened", "decoder_started", "solver_started", "cfd_or_model_run")
    if any(policy.get(name) is not False for name in forbidden):
        raise LedgerError("probe report read policy does not prove no H5/trajectory/solver use")
    report_binding = probe_report.get("source_report", {})
    if report_binding.get("sha256") != source_sha:
        raise LedgerError("probe report is bound to a different all-118 source report")
    cases = probe_report.get("cases")
    if not isinstance(cases, list) or len(cases) != 118:
        raise LedgerError("probe report does not contain exactly 118 cases")
    by_key = {str(case.get("case_key")): case for case in cases}
    if len(by_key) != len(cases):
        raise LedgerError("probe report case keys are not unique")
    return by_key


def positive_motive_counts(value: Any, label: str) -> tuple[str, int]:
    if not isinstance(value, dict):
        raise LedgerError(f"{label} is not an object")
    positive = [(str(name), int(count)) for name, count in value.items() if int(count) > 0]
    if len(positive) != 1 or positive[0][0] not in {"position", "density", "movement"}:
        raise LedgerError(f"{label} is ambiguous")
    return positive[0]


def validate_case(source: dict[str, Any], probe: dict[str, Any], source_report_sha: str) -> dict[str, Any]:
    key = str(source.get("case_key"))
    if probe.get("case_key") != key or probe.get("family_id") != source.get("family_id") or probe.get("physical_case_id") != source.get("physical_case_id"):
        raise LedgerError(f"case identity differs: {key}")
    family = str(source.get("family_id"))
    motive, native_count = positive_motive_counts(source.get("native_cause", {}).get("motive_counts"), f"{key} source motive")
    probe_gate = probe.get("native_gate", {})
    if probe_gate.get("motive") != motive or int(probe_gate.get("native_count", -1)) != native_count:
        raise LedgerError(f"native motive/count differs: {key}")
    if probe_gate.get("cause", {}).get("exit_cause_counts") != source.get("native_cause", {}).get("exit_cause_counts"):
        raise LedgerError(f"native cause differs: {key}")
    particles = source.get("particles", [])
    observations = probe.get("particle_observations", [])
    if not isinstance(particles, list) or not isinstance(observations, list):
        raise LedgerError(f"particle observations are not lists: {key}")
    particle_by_id = {int(row["idp"]): row for row in particles}
    observation_by_id = {int(row["idp"]): row for row in observations}
    if set(particle_by_id) != set(observation_by_id) or len(particle_by_id) != native_count:
        raise LedgerError(f"particle identity/count differs: {key}")
    mass_sum = sum(finite(row.get("initial_mass_kg"), f"{key} particle mass") for row in particles)
    visibility = source.get("mass_visibility", {})
    missing_mass = finite(visibility.get("missing_source_visible_mass_lower_bound_kg"), f"{key} missing mass")
    if not close(mass_sum, missing_mass, abs_tol=2e-8):
        raise LedgerError(f"particle mass does not close source-visible lower bound: {key}")
    if probe.get("mass_visibility") != visibility:
        raise LedgerError(f"probe mass ledger differs from source ledger: {key}")
    source_bindings = source.get("source_bindings", {})
    observed_files = probe.get("source_files", {})
    if not isinstance(observed_files, dict):
        raise LedgerError(f"probe source files are absent: {key}")
    checked_files: dict[str, dict[str, Any]] = {}
    for name, declared in observed_files.items():
        if not isinstance(declared, dict):
            raise LedgerError(f"probe source binding is invalid: {key}/{name}")
        checked_files[name] = binding(declared.get("path", ""), f"{key} {name}", declared.get("sha256"))
    expected_forensic = source_bindings.get("forensic", {})
    if checked_files.get("forensic", {}).get("path") != str(Path(expected_forensic.get("path", "")).resolve()) or checked_files.get("forensic", {}).get("sha256") != expected_forensic.get("sha256"):
        raise LedgerError(f"forensic source binding differs: {key}")
    for binding_name in ("scan", "scan_receipt"):
        expected = source_bindings.get(binding_name, {})
        observed = checked_files.get(binding_name, {})
        if observed.get("path") != str(Path(expected.get("path", "")).resolve()) or observed.get("sha256") != expected.get("sha256"):
            raise LedgerError(f"{binding_name} source binding differs: {key}")
    forensic_path, forensic = read_json(expected_forensic.get("path", ""), f"{key} forensic sidecar")
    if sha256(forensic_path) != expected_forensic.get("sha256"):
        raise LedgerError(f"forensic source digest differs: {key}")
    closure = probe.get("source_closure", {})
    partial = closure.get("status") == "PARTIAL_NATIVE_RECONCILIATION_ONLY"
    if partial:
        if key != "F2/scan-F2-S1-001" or forensic.get("schema") != "ds02.stage2.native-exclusion-reconciliation.v1":
            raise LedgerError(f"partial source status is attached to the wrong case: {key}")
        conversion = {
            "status": "UNKNOWN_SOURCE_MISSING",
            "metadata_path_sha_match": False,
            "converter_source_closure": "UNKNOWN_SOURCE_MISSING",
            "missing_inputs": closure.get("missing_inputs", []),
        }
        repair = {
            "status": "REQUIRED_BEFORE_FULL_SOURCE_CREDIT",
            "path": "Bind the existing immutable F2-S1 native reconciliation to generated XML, GenCase/solver receipts, Run.out, RunPARTs, PartVTKOut CSV/receipt/tool and conversion metadata; retain the 3 IDs and existing hashes.",
        }
    else:
        trajectory = forensic.get("trajectory", {})
        conversion_decl = trajectory.get("conversion_report", {}) if isinstance(trajectory, dict) else {}
        conversion_path, conversion_report = read_json(conversion_decl.get("path", ""), f"{key} conversion report")
        if sha256(conversion_path) != conversion_decl.get("sha256"):
            raise LedgerError(f"conversion report digest differs: {key}")
        if conversion_report.get("conversion_status") != "completed":
            raise LedgerError(f"conversion is not completed: {key}")
        if conversion_report.get("output_hdf5") != trajectory.get("path") or conversion_report.get("output_sha256") != trajectory.get("sha256"):
            raise LedgerError(f"conversion output path/SHA metadata differs: {key}")
        if checked_files.get("conversion_report", {}).get("sha256") != conversion_decl.get("sha256"):
            raise LedgerError(f"probe conversion binding differs: {key}")
        conversion = {
            "status": "COMPLETED_OUTPUT_PATH_SHA_METADATA_MATCHED",
            "conversion_report": binding(conversion_path, f"{key} conversion report", conversion_decl.get("sha256")),
            "trajectory_path": trajectory.get("path"),
            "trajectory_sha256": trajectory.get("sha256"),
            "partvtk_validation_all_passed": conversion_report.get("partvtk_validation", {}).get("all_passed", "UNKNOWN"),
            "native_missing_semantics": conversion_report.get("lifecycle", {}).get("missing_semantics", "UNKNOWN"),
            "converter_source_closure": "UNKNOWN_NOT_BOUND_BY_CONVERSION_RECEIPT",
            "physical_interpretation": "metadata does not prove converter omission absent or physical fate",
        }
        repair = {
            "status": "PLANNED_NOT_EXECUTED",
            "path": FAMILY_CONTROLS[family]["control_id"],
        }
    censoring = source.get("event_censoring", {})
    if not isinstance(censoring, dict):
        raise LedgerError(f"event censoring is absent: {key}")
    mass_fraction = finite(visibility.get("missing_source_visible_fraction_lower_bound"), f"{key} missing fraction")
    source_mk = source.get("source_mk_weight", {})
    record = {
        "case_key": key,
        "family_id": family,
        "physical_case_id": source.get("physical_case_id"),
        "evidence_bindings": {
            "source_report": {"sha256": source_report_sha},
            "forensic": checked_files.get("forensic"),
            "scan": checked_files.get("scan"),
            "scan_receipt": checked_files.get("scan_receipt"),
            "full_probe_sources": checked_files,
        },
        "native_numerical_cause": {
            "motive": motive,
            "native_count": native_count,
            "exit_cause_counts": source.get("native_cause", {}).get("exit_cause_counts", {}),
            "credit_scope": "native solver motive/PartVTKOut-RunPARTs evidence only; endpoint predicates do not prove physical destination",
        },
        "conversion_omission": conversion,
        "mass_impact": {
            "initial_fluid_mass_denominator_kg": visibility.get("initial_fluid_mass_denominator_kg"),
            "source_visible_missing_mass_lower_bound_kg": missing_mass,
            "source_visible_missing_fraction_lower_bound": mass_fraction,
            "screen": visibility.get("screen"),
            "screen_gate_fraction": visibility.get("screen_gate_fraction", MASS_GATE),
            "particle_count": len(particles),
            "particle_mass_sum_kg": mass_sum,
            "source_mk_partition": source_mk,
            "claim_boundary": "source-visible lower bound only; not physical outflow mass, bounded force/impulse, or dynamics error",
        },
        "censoring": {
            "first_missing_window_s": censoring.get("first_missing_window_s"),
            "per_particle_brackets": censoring.get("per_particle_first_missing_windows"),
            "physical_event_time": censoring.get("physical_event_time_s", "UNKNOWN"),
            "post_gap_state": censoring.get("post_gap_state", "UNKNOWN"),
        },
        "source_closure": {
            "status": "PARTIAL_NATIVE_RECONCILIATION_ONLY" if partial else "FULL_PROBE_SOURCE_CLOSED",
            "missing_inputs": closure.get("missing_inputs", []) if partial else [],
        },
        "next_validation_control": {
            **FAMILY_CONTROLS[family],
            "status": repair["status"],
            "repair_or_control": repair["path"],
            "information_gain": "separate numerical gate sensitivity from physical fate; do not infer legal flux from position/density endpoint",
        },
        "physical_fate": "UNKNOWN",
        "legal_outflow_or_spill": "UNKNOWN_NOT_PROVEN",
        "dynamical_impact": "UNKNOWN",
        "QN": "NOT_ASSESSED",
        "QE": "NOT_ASSESSED",
    }
    if family == "F6":
        semantics = source.get("f6_mass_semantics")
        record["rigid_mass_and_com_scope"] = {
            "semantics": semantics if isinstance(semantics, dict) else "UNKNOWN",
            "physical_body_mass_vs_sample_mass": "kept separate; sampled SPH mass cannot be used as rigid body mass",
            "COM_identifiability": "UNKNOWN_PENDING_F6_COMBINED_KABSCH_SIDECAR",
            "SO3_or_rigid_dynamics": "UNKNOWN",
        }
    return record


def build_ledger(source_path: Path, probe_path: Path, output_path: Path) -> dict[str, Any]:
    source_path, source = read_json(source_path, "all-118 source report")
    source_sha = sha256(source_path)
    by_source = source_cases(source)
    probe_path, probe = read_json(probe_path, "all-118 v2 probe report")
    by_probe = probe_cases(probe, source_sha)
    if set(by_source) != set(by_probe):
        raise LedgerError("source/probe case membership differs")
    cases = [validate_case(by_source[key], by_probe[key], source_sha) for key in sorted(by_source)]
    family_counts = Counter(case["family_id"] for case in cases)
    motive_counts = Counter(case["native_numerical_cause"]["motive"] for case in cases)
    cause_counts = Counter()
    for case in cases:
        cause_counts.update(case["native_numerical_cause"]["exit_cause_counts"])
    result = {
        "schema": OUTPUT_SCHEMA,
        "status": "IMPACT_LEDGER_SOURCE_CLOSED_WITH_FATE_AND_DYNAMICS_UNKNOWN",
        "source_report": binding(source_path, "all-118 source report"),
        "probe_report": binding(probe_path, "all-118 v2 probe report"),
        "coverage": {
            "case_count": len(cases),
            "family_counts": dict(sorted(family_counts.items())),
            "native_motive_counts": dict(sorted(motive_counts.items())),
            "native_cause_counts": dict(sorted(cause_counts.items())),
            "partial_source_case_count": sum(case["source_closure"]["status"].startswith("PARTIAL") for case in cases),
            "full_source_case_count": sum(case["source_closure"]["status"] == "FULL_PROBE_SOURCE_CLOSED" for case in cases),
        },
        "claim_boundary": {
            "native_motive": "credited only where v2 source-bound native sidecars agree with CURRENT identity",
            "conversion_omission": "path/SHA metadata is checked; converter implementation/source closure remains UNKNOWN",
            "mass": "source-visible missing lower bound only; per-MK partition remains UNKNOWN where not independently bound",
            "censoring": "first-missing brackets are saved-record windows, not exact physical event times",
            "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN_NOT_PROVEN",
            "dynamical_impact": "UNKNOWN",
            "QN": "NOT_ASSESSED",
            "QE": "NOT_ASSESSED",
        },
        "read_policy": {
            "h5_opened": False,
            "trajectory_content_opened": False,
            "raw_partout_opened": False,
            "decoder_started": False,
            "solver_started": False,
            "cfd_or_model_run": False,
        },
        "cases": cases,
    }
    atomic_json(output_path, result)
    return {"status": result["status"], "output": str(output_path.resolve()), **result["coverage"]}


def prepare(output_dir: Path, probe_path: Path, source_path: Path = SOURCE_REPORT_DEFAULT, variant: str = "v1") -> dict[str, Any]:
    if not re.fullmatch(r"v[0-9]+", variant):
        raise LedgerError(f"invalid request variant: {variant}")
    source_path, source = read_json(source_path, "all-118 source report")
    source_sha = sha256(source_path)
    by_source = source_cases(source)
    probe_path, probe = read_json(probe_path, "all-118 v2 probe report")
    by_probe = probe_cases(probe, source_sha)
    if set(by_source) != set(by_probe):
        raise LedgerError("source/probe case membership differs")
    # Preparation performs the same source closure and writes no result. The
    # actual report is produced by the shared guard through the audit action.
    cases = [validate_case(by_source[key], by_probe[key], source_sha) for key in sorted(by_source)]
    inputs = [
        SCRIPT, source_path, probe_path, VENV,
        SCRIPT.parent / "ds_data02_runtime_v6.py",
        SCRIPT.parent / "ds_data02_stage2_dispatch_v6.py",
        SCRIPT.parent / "ds_data02_strict_dispatch_v6.py",
    ]
    for case in cases:
        for item in case["evidence_bindings"]["full_probe_sources"].values():
            inputs.append(Path(item["path"]))
    unique: list[Path] = []
    seen: set[str] = set()
    for path in inputs:
        path = require_file(path, f"ledger input {Path(path).name}")
        if str(path) not in seen:
            seen.add(str(path)); unique.append(path)
    hashes = {str(path): sha256(path) for path in unique}
    output_dir = output_dir.resolve(); output_dir.mkdir(parents=True, exist_ok=True)
    name = f"omission-impact-ledger-{variant}"
    manifest_path = output_dir / f"{name}-manifest.json"
    request_path = output_dir / f"{name}-request.json"
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "PREPARED_ALL118_IMPACT_LEDGER_NO_H5",
        "source_report": binding(source_path, "all-118 source report", source_sha),
        "probe_report": binding(probe_path, "all-118 v2 probe report", sha256(probe_path)),
        "selected_case_counts": dict(sorted(FAMILY_COUNTS.items())),
        "selected_case_keys": sorted(by_source),
        "input_files": sorted(hashes),
        "input_sha256": dict(sorted(hashes.items())),
        "read_policy": {"h5_opened": False, "trajectory_content_opened": False, "raw_partout_opened": False, "decoder_started": False, "solver_started": False, "cfd_or_model_run": False},
        "claim_boundary": "native cause and source-visible mass only; converter source, physical fate, legal flux and dynamics UNKNOWN",
        "partial_source_cases": [case["case_key"] for case in cases if case["source_closure"]["status"].startswith("PARTIAL")],
    }
    atomic_json(manifest_path, manifest)
    request_hashes = dict(hashes); request_hashes[str(manifest_path)] = sha256(manifest_path)
    request = {
        "schema": "ds02.request.v1",
        "family_id": "infra",
        "case_id": "STAGE2_OMISSION_IMPACT_LEDGER_ALL118_V1",
        "physical_case_id": "F2_F4_F6_ALL118_IMPACT_LEDGER",
        "attempt_id": f"{name}-primary-001",
        "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 1, "omp_threads": 1,
        "max_wall_seconds": 900, "estimated_storage_bytes": 64 * 1024 * 1024,
        "cwd": str(SCRIPT.parent), "worktree_root": str(WORKTREE_ROOT),
        "command": [str(VENV), str(SCRIPT), "audit", "--manifest", str(manifest_path), "--output", f"{{attempt_root}}/{name}.json"],
        "input_files": sorted(request_hashes), "input_sha256": dict(sorted(request_hashes.items())),
        "shared_runtime_version": "v6",
        "runtime_binding": {"path": str((SCRIPT.parent / "ds_data02_runtime_v6.py").resolve()), "sha256": sha256(SCRIPT.parent / "ds_data02_runtime_v6.py")},
        "dispatch_binding": {"path": str((SCRIPT.parent / "ds_data02_stage2_dispatch_v6.py").resolve()), "sha256": sha256(SCRIPT.parent / "ds_data02_stage2_dispatch_v6.py")},
        "strict_dispatch_binding": {"path": str((SCRIPT.parent / "ds_data02_strict_dispatch_v6.py").resolve()), "sha256": sha256(SCRIPT.parent / "ds_data02_strict_dispatch_v6.py")},
        "source_read_cost": {"h5_bytes_read": 0, "trajectory_bytes_read": 0, "raw_partout_bytes_read": 0, "json_csv_xml_binary_bytes_read": sum(path.stat().st_size for path in unique), "runtime_pre_post_hash_bytes": 2 * sum(path.stat().st_size for path in unique), "estimated_output_bytes": 64 * 1024 * 1024},
        "source_scope": {"selected_cases": dict(sorted(FAMILY_COUNTS.items())), "native_cause_and_mass_ledger": True, "h5_content_read": False, "trajectory_content_read": False, "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN_NOT_PROVEN", "dynamical_impact": "UNKNOWN"},
        "canonical_ready": True, "launch": True, "launch_allowed": True, "execution_allowed": True,
        "launch_owner": "root", "primary_launch_owner": "root", "shared_lease_required": True, "foreign_process_protection_required": True,
        "physical_fate": "UNKNOWN", "legal_outflow_or_spill": "UNKNOWN_NOT_PROVEN", "dynamical_impact": "UNKNOWN", "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED",
        "launch_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=WORKTREE_ROOT, check=True, capture_output=True, text=True).stdout.strip(),
        "request_note": "Independent all-118 consumer of completed v2 native probe. Verifies CURRENT identity, native motive/cause, source-visible mass and censoring brackets, conversion output path/SHA metadata, and explicit partial F2-S1 repair scope. No H5, native trajectory, raw PartOut, decoder or solver; converter source closure, physical fate, legal flux and dynamics remain UNKNOWN.",
    }
    atomic_json(request_path, request)
    return {"status": "prepared", "manifest": str(manifest_path), "manifest_sha256": sha256(manifest_path), "request": str(request_path), "request_sha256": sha256(request_path), "selected_case_count": 118, "partial_source_cases": manifest["partial_source_cases"], "h5_opened": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--probe-report", type=Path, required=True)
    prep.add_argument("--source-report", type=Path, default=SOURCE_REPORT_DEFAULT)
    prep.add_argument("--output-dir", type=Path, required=True)
    prep.add_argument("--variant", default="v1")
    audit = sub.add_parser("audit")
    audit.add_argument("--manifest", type=Path, required=True)
    audit.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            result = prepare(args.output_dir, args.probe_report, args.source_report, args.variant)
        else:
            manifest_path, manifest = read_json(args.manifest, "impact ledger manifest")
            if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "PREPARED_ALL118_IMPACT_LEDGER_NO_H5":
                raise LedgerError("impact ledger manifest schema/status differs")
            for path_text, expected in manifest.get("input_sha256", {}).items():
                path = require_file(path_text, "impact ledger input")
                if sha256(path) != expected:
                    raise LedgerError(f"impact ledger input digest differs: {path}")
            result = build_ledger(Path(manifest["source_report"]["path"]), Path(manifest["probe_report"]["path"]), args.output)
    except LedgerError as exc:
        raise SystemExit(f"LedgerError: {exc}")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
