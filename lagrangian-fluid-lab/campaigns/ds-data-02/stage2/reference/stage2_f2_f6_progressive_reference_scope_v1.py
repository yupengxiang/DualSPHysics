#!/usr/bin/env python3
"""Build a finite, source-bound progress index for the F2--F6 sentinels.

This is a bounded metadata audit.  It reads only the committed JSON audits and
request files in the repository; it does not open BI4/H5/native payloads and it
does not start GenCase, a solver, or a GPU.  The result separates completed
source/GenCase evidence from candidate solver requests and records the concrete
field, time, and output observations still needed before QI/QN/QE can change.

The index is intentionally additive.  Existing status, quality, and request
artifacts remain the authorities for their own bytes and are never rewritten.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.f2-f6-progressive-reference-scope.v1"
REPO = Path(__file__).resolve().parents[5]
STAGE2 = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
STATUS_PATH = STAGE2 / "reference/stage2_fourteen_reference_status_v1.json"
QUALITY_PATH = STAGE2 / "reference/stage2_reference_quality_cost_v2.json"
SUPPORT_PATH = STAGE2 / "reference/stage2_f2_f3_f6_source_support_audit_v2.json"
EVENT_PATH = STAGE2 / "reference/stage2_f2_f3_f6_event_registration_v4.json"
F5_PATH = STAGE2 / "reference/stage2_f5_effective_condition_audit_v2.json"
GRID_PATH = STAGE2 / "reference/stage2_f6_f7_three_grid_audit_v1.json"
DEFAULT_OUTPUT = STAGE2 / "reference/stage2_f2_f6_progressive_reference_scope_v1.json"

SENTINELS = (
    "F2-S1", "F2-S2", "F3-S1", "F3-S2", "F4-S1", "F4-S2",
    "F5-S1", "F5-S2", "F6-S1", "F6-S2",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def source_record(path: Path) -> dict[str, Any]:
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)}


def file_ref(value: Any) -> dict[str, Any] | None:
    """Keep an existing report's file identity without touching that file."""
    if not isinstance(value, dict):
        return None
    if isinstance(value.get("file"), dict):
        value = value["file"]
    keys = ("path", "bytes", "mtime_ns", "sha256")
    result = {key: value[key] for key in keys if key in value}
    return result or None


def request_record(path_value: str | Path) -> dict[str, Any]:
    path = Path(path_value).expanduser()
    result: dict[str, Any] = {"path": str(path), "exists": path.is_file()}
    if not path.is_file():
        return result
    result["bytes"] = path.stat().st_size
    result["sha256"] = sha256(path)
    try:
        request = load(path)
    except (OSError, ValueError):
        return result
    for key in (
        "schema", "kind", "cpu_task_kind", "family_id", "sentinel_id", "case_id",
        "attempt_id", "launch_disabled", "execution_allowed", "solver_started",
        "gpu_started", "bi4_read", "hdf5_read", "max_wall_seconds",
        "estimated_storage_bytes", "estimated_native_read_bytes",
        "estimated_hdf5_read_bytes", "qualification_stage",
    ):
        if key in request:
            result[key] = request[key]
    return result


def controls(source: dict[str, Any]) -> dict[str, Any]:
    xml = source.get("source_xml", {})
    if isinstance(xml, dict) and isinstance(xml.get("file"), dict):
        xml = xml["file"]
    params = source.get("source_xml", {}).get("parameters", {}) if isinstance(source.get("source_xml"), dict) else {}
    wanted = (
        "Boundary", "SlipMode", "StepAlgorithm", "Kernel", "ViscoTreatment", "Visco",
        "DensityDT", "DensityDTvalue", "Shifting", "ShiftCoef", "ShiftTFS", "RigidAlgorithm",
        "CoefDtMin", "DtIni", "DtMin", "DtFixed", "DtAllParticles", "TimeMax", "TimeOut",
        "PartsOutMax", "SavePosDouble",
    )
    return {
        "source_xml": file_ref(source.get("source_xml")),
        "parameters": {key: params[key] for key in wanted if key in params},
        "source_motion_refs": source.get("source_xml", {}).get("motion_refs", []) if isinstance(source.get("source_xml"), dict) else [],
        "effective_cfl": source.get("source_cfl"),
        "effective_half_cfl": source.get("half_cfl"),
        "effective_tmax_s": source.get("effective_time_window_s", [None, None])[-1],
        "effective_output_cadence_s": source.get("effective_output_cadence_s"),
        "source_solver_control_status": (source.get("source_solver_controls") or {}).get("status"),
        "source_solver_receipt": file_ref((source.get("source_solver_controls") or {}).get("receipt")),
    }


def trim_candidate(row: dict[str, Any]) -> dict[str, Any]:
    mass = row.get("mass_diagnostic") or {}
    receipt = row.get("receipt_terminal") or {}
    control = row.get("control_terminal") or {}
    if not isinstance(control, dict):
        control = {"solver_candidate_status": control}
    continuous = row.get("continuous_vs_intentional") or {}
    if not isinstance(continuous, dict):
        continuous = {"strict_continuous_equivalence": continuous}
    generated = row.get("generated_xml")
    if isinstance(generated, dict):
        generated = generated.get("path") or generated.get("file", {}).get("path")
    return {
        "label": row.get("label"),
        "case_id": row.get("case_id"),
        "requested_dp_m": row.get("requested_dp_m"),
        "source_dp_m": row.get("source_dp_m"),
        "receipt": {
            "path": row.get("receipt_path"),
            "status": receipt.get("status"),
            "returncode": receipt.get("returncode"),
            "termination_reason": receipt.get("termination_reason"),
            "fluid_particles": receipt.get("fluid_particles"),
            "output_root": receipt.get("output_root"),
            "actual_output_tree_bytes": receipt.get("actual_output_tree_bytes"),
        },
        "generated_xml": generated,
        "initial_sample_mass": {
            "source_kg": mass.get("source_sample_mass_kg"),
            "candidate_kg": mass.get("candidate_sample_mass_kg"),
            "deviation_pct_vs_source": mass.get("deviation_pct_vs_source"),
            "gate": mass.get("gate"),
            "basis": "CURRENT discrete source sample; not continuum truth",
        },
        "geometry_control": {
            "xml_control_match_except_intentional_dp_h": control.get("candidate_xml_control_match_except_intentional_dp_h"),
            "continuous_geometry_control": control.get("continuous_geometry_control"),
            "motion_or_acceleration_changed": continuous.get("motion_or_acceleration_changed", control.get("motion_or_acceleration_changed")),
            "draw_fill_geometry_changed": continuous.get("draw_fill_geometry_changed"),
            "relative_dependencies_byte_identical": continuous.get("relative_dependencies_byte_identical"),
            "intentional_resolution": control.get("intentional_resolution"),
            "solver_candidate_status": control.get("solver_candidate_status"),
        },
        "solver_started": row.get("solver_started", False),
        "scientific_qualification": {key: row.get(key, "UNKNOWN") for key in ("QI", "QN", "QE")},
    }


def pair_request(sentinel_id: str, mode: str) -> dict[str, Any]:
    stem = sentinel_id.lower().replace("-", "_")
    savedt = STAGE2 / "requests/stage2-savedt-cfl-pairs-v1" / f"{stem}_original_savedt_{mode}.json"
    # F4-S1's already reviewed pair uses the original-cfl-pairs-v2 request
    # names; preserve that exact request rather than emitting a nonexistent
    # alias.  Other rows use the SavedDt-v1 names when present.
    fallback = STAGE2 / "requests/stage2-original-cfl-pairs-v2" / f"{stem}_original_{mode}_cfl_dense.json"
    relative = savedt if savedt.is_file() else fallback
    return request_record(relative)


def next_actions(sentinel_id: str, status_item: dict[str, Any]) -> dict[str, Any]:
    actions: list[dict[str, Any]] = [
        {"purpose": "actual SaveDt same-CFL run; root dispatch only", "request": pair_request(sentinel_id, "same_cfl")},
        {"purpose": "actual SaveDt half-CFL run; root dispatch only", "request": pair_request(sentinel_id, "half_cfl")},
    ]
    special = status_item.get("special_prepared_or_actual") or {}
    for key, value in special.items():
        if key.endswith("request") and isinstance(value, dict) and value.get("path"):
            actions.append({"purpose": f"existing special {key}; root decides dispatch", "request": request_record(value["path"])})
    if sentinel_id.startswith("F6-"):
        actions.append({
            "purpose": "physical rigid-body source/geometry audit before any F6 field credit",
            "request": request_record(STAGE2 / "requests/stage2-f6-rigid-body-geometry-audit-v4/f6_rigid_body_geometry_audit_v4.json"),
        })
    return {"root_dispatch_required": True, "requests": actions}


def unresolved(sentinel_id: str) -> list[str]:
    family = sentinel_id.split("-", 1)[0]
    common = [
        "QI/QN/QE remain UNKNOWN until source-bound physical field comparison.",
        "RunPARTs saved-window summaries are not a full per-step dt/clamp trace; SaveDt overlay is required for integration claims.",
        "Output sampling/interpolation error must be calibrated from actual saved rows; neighboring-grid differences are not truth.",
        "Frozen gates remain position 2% L, velocity/KE 5% nonzero scale, regional mass 3 percentage points of whole initial fluid mass, and time/output each one quarter of their task tolerance.",
    ]
    family_specific = {
        "F2": [
            "Continuous owner volume mass and discrete source sample mass are separate (F2 owner 18.876 kg versus source sample 21.114 kg); no rescale or silent substitution.",
            "Per-native-MK mass/phase and finite-aperture crossing fields are still needed; structural typed brackets are not physical observables.",
        ],
        "F3": [
            "Cell-center drawbox extent versus continuous owner extent remains a geometry-support question; the frozen velocity scale .9077664898 is retained and owner depth .09 m is diagnostic only.",
            "The finite x/y aperture, +z crossing direction, native-MK mapping, and event bracket need actual fields.",
        ],
        "F4": [
            "Coarse/same/half/fine actual windows still need macro observer comparison at common saved times; the F4 gravity anchor is conditional on a continuous no-contact proof.",
            "The 1.2 s endpoint must use actual saved/bracketed time; no extrapolation from the canary shortfall.",
        ],
        "F5": [
            "The effective CLI window is 0--16 s while XML TimeMax is 26 s; motion ends at 14.4 s (S1) or 12.8 s (S2), so post-motion fields need explicit observation.",
            "The two motion controls are separate physical cases; shared geometry does not grant shared event or observer credit.",
        ],
        "F6": [
            "Floating sample mass is 256 kg at the source spacing while physical rigid massbody is 128 kg; rigid massbody/inertia/COM must be compared separately.",
            "The physical COM [2.4,1.2,1.08] and corner-derived speed scale remain authoritative; sample-particle sums cannot replace rigid dynamics.",
        ],
    }
    return common + family_specific[family]


def build() -> dict[str, Any]:
    status = load(STATUS_PATH)
    quality = load(QUALITY_PATH)
    support = load(SUPPORT_PATH)
    events = load(EVENT_PATH)
    f5 = load(F5_PATH)
    grid = load(GRID_PATH)
    source_rows = {row["sentinel_id"]: row for row in quality["sources"]}
    candidate_rows: dict[str, list[dict[str, Any]]] = {sid: [] for sid in SENTINELS}
    for row in quality["candidate_quality_and_controls"]:
        if row.get("sentinel_id") in candidate_rows:
            candidate_rows[row["sentinel_id"]].append(trim_candidate(row))
    status_rows = {row["sentinel_id"]: row for row in status["sentinels"]}
    output_rows: list[dict[str, Any]] = []
    for sid in SENTINELS:
        src = source_rows[sid]
        st = status_rows[sid]
        candidates = candidate_rows[sid]
        completed_gencase = [row for row in candidates if row["receipt"]["status"] == "completed" and row["receipt"]["returncode"] == 0]
        gates = {row["initial_sample_mass"]["gate"] for row in completed_gencase}
        output_rows.append({
            "sentinel_id": sid,
            "family_id": src.get("family_id"),
            "physical_case_id": src.get("physical_case_id"),
            "source_and_controls": {
                "source_xml": file_ref(src.get("source_xml")),
                "source_dp_m": src.get("source_dp_m"),
                "h_m": (src.get("source_xml") or {}).get("h_m"),
                "sample_fluid_particles": src.get("source_fluid_particles"),
                "sample_mass_kg": src.get("source_sample_mass_kg"),
                "effective_window_s": src.get("effective_time_window_s"),
                "controls": controls(src),
            },
            "finite_evidence": {
                "current_source_solver": {
                    "status": (src.get("source_solver_controls") or {}).get("status"),
                    "receipt": file_ref((src.get("source_solver_controls") or {}).get("receipt")),
                    "tmax_s": (src.get("source_solver_controls") or {}).get("tmax_s"),
                    "tout_s": (src.get("source_solver_controls") or {}).get("tout_s"),
                    "solver_bytes": (src.get("source_solver_controls") or {}).get("bytes"),
                    "meaning": "existing CURRENT source run evidence; no new field qualification",
                },
                "completed_gencase_candidate_count": len(completed_gencase),
                "candidate_gate_set": sorted(gates),
                "candidate_preflights": candidates,
                "special_existing_evidence": st.get("special_prepared_or_actual"),
            },
            "next_executable": next_actions(sid, st),
            "observations_required_before_qualification": unresolved(sid),
            "qualification": {key: st.get("qualification", {}).get(key, "UNKNOWN") for key in ("QI", "QN", "QE")},
        })
    return {
        "schema": SCHEMA,
        "status": "FINITE_SOURCE_AND_GENCASE_EVIDENCE_WITH_ROOT_DISPATCH_NEXT_STEPS",
        "read_policy": {
            "reads_repository_json_only": True,
            "bi4_read": False,
            "hdf5_read": False,
            "native_payload_read": False,
            "solver_launch": False,
            "gpu_launch": False,
            "qualification_granted": False,
        },
        "frozen_scientific_policy": {
            "mass_gate": "whole initial discrete source sample diagnostic: preferred <=1%, marginal <=2%, hard >2%; no post-hoc rescale",
            "physical_owner": "continuous owner geometry/control remains authoritative where available; source sample mass is not continuum truth",
            "time_and_output": "same-CFL and half-CFL full sentinel windows remain separate root-dispatched studies; output downsampling is a derived observer task",
            "unknown_policy": "unknown field/time/output/event observations are explicit and never filled by adjacent-grid differences",
        },
        "source_inputs": [source_record(path) for path in (STATUS_PATH, QUALITY_PATH, SUPPORT_PATH, EVENT_PATH, F5_PATH, GRID_PATH)],
        "support_and_event_audits": {
            "source_support_audit": {"path": str(SUPPORT_PATH), "schema": support.get("schema"), "status": support.get("status")},
            "event_registration": {"path": str(EVENT_PATH), "schema": events.get("schema"), "status": events.get("status")},
            "f5_effective_controls": {"path": str(F5_PATH), "schema": f5.get("schema"), "status": f5.get("status")},
            "f6_grid_audit": {"path": str(GRID_PATH), "schema": grid.get("schema"), "status": grid.get("status")},
        },
        "sentinels": output_rows,
        "global_constraints": [
            "All pair requests are launch-disabled in this artifact and require parent v4/v8 guard, fresh CPU/GPU ledger, and exact current source bindings.",
            "A completed GenCase receipt is an initial geometry/control preflight only; it is not QI/QN/QE.",
            "Existing source solver receipts are retained as finite source evidence, not cross-grid truth.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.self_test == args.build:
        parser.error("choose exactly one of --self-test or --build")
    report = build()
    if args.self_test:
        assert report["schema"] == SCHEMA
        assert len(report["sentinels"]) == len(SENTINELS)
        assert all(item["read_policy"]["solver_launch"] is False for item in [report])
        assert all(item["qualification"]["QI"] == "UNKNOWN" for item in report["sentinels"])
        print(json.dumps({"status": "PASS", "sentinels": len(report["sentinels"]), "solver_launch": False, "native_payload_read": False}, indent=2))
        return 0
    if args.output.exists():
        raise FileExistsError(f"refuse overwrite immutable artifact: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": "WRITTEN", "path": str(args.output), "sentinels": len(report["sentinels"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
