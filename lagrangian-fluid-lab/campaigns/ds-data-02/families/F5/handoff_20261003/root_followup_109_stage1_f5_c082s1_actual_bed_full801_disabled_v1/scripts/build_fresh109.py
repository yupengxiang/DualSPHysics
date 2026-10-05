#!/usr/bin/env python3
"""Build the F5 fresh109 source-only promotion pack.

Root506/509 short-window XMF and bed reports are consumed as JSON/XML
metadata.  This script never opens or hashes H5/BI4/CSV/VTK/DAT payloads and
never launches a solver.  It emits disabled 16 s/801-frame native requests
that remain blocked on Root's short-window visual review and live Root230
UUID/lease checks.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any

PKG = Path(__file__).resolve().parents[1]
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5")
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
LAB = INTEGRATION / "lagrangian-fluid-lab"
CASE = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
ROOT230 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_home_floor_eight_solver_dispatch_230"
ROOT230_POLICY = ROOT230 / "root_native_home_floor_inventory_policy.py"
ROOT230_LAUNCH = ROOT230 / "launch.py"
RUNTIME = LAB / "scripts/ds_data02_runtime_v2.py"
STRICT = LAB / "scripts/ds_data02_strict_dispatch_v1.py"
PYTHON = LAB / ".venv/bin/python"
RESOURCE = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"
SOLVER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64")
ROOT349_RECEIPT = DATA / CASE / "root-stage1-f5-c082s1-solid-fluid-recovery-full801-native-qualification-349/execution-receipt.json"
COUNTS = {"total": 194427, "fixed": 158559, "moving": 4210, "floating": 0, "fluid": 31658}
ROOT230_POLICY_SHA = "c9103e306f87bb5af871c5de28d9939aa05f0c95c72e1630778f4bcf50e91ab5"
ROOT230_LAUNCH_SHA = "7f703fb94e17c2e2800873f4fcc021f9cd5f8201076afd8e10e3bc6a2d03396e"
ROOT230_RESERVATION_SHA = "46e62ea197862a833797556d09350126b3632b2e3b1d496d08816ee42f7abecf"
HASHABLE = {".json", ".py", ".xml", ".md", ".txt", ".log"}
SCIENCE = {".bi4", ".csv", ".h5", ".hdf5", ".vtk", ".vtu", ".npy", ".npz", ".dat"}
HEX = set("0123456789abcdefABCDEF")
CANDIDATES = {
    "A080": {
        "physical_id": "F5_COMPACT_RUNUP_RECOVERY_C082S1_A080",
        "condition_id": "F5_RUNUP_DP020_C082S1_MOTION_A080_099",
        "xmf_attempt": "root-stage1-f5-c082s1-A080-short-native-xmf-107-root506",
        "bed_attempt": "root-stage1-f5-c082s1-A080-short-dynamic-bed-audit-107-root508",
        "full_attempt": "root-stage1-f5-c082s1-A080-full801-native-qualification-109",
    },
    "A120": {
        "physical_id": "F5_COMPACT_RUNUP_RECOVERY_C082S1_A120",
        "condition_id": "F5_RUNUP_DP020_C082S1_MOTION_A120_099",
        "xmf_attempt": "root-stage1-f5-c082s1-A120-short-native-xmf-107-root506",
        "bed_attempt": "root-stage1-f5-c082s1-A120-short-dynamic-bed-audit-107-root508",
        "full_attempt": "root-stage1-f5-c082s1-A120-full801-native-qualification-109",
    },
}


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value


def sha(path: Path) -> str:
    require(path.suffix.lower() in HASHABLE, f"payload hash forbidden: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def actual_paths(candidate: str) -> dict[str, Path]:
    spec = CANDIDATES[candidate]
    root = DATA / CASE
    return {
        "xmf_receipt": root / spec["xmf_attempt"] / "execution-receipt.json",
        "xmf_manifest": root / spec["xmf_attempt"] / "xmf/manifest.json",
        "bed_receipt": root / spec["bed_attempt"] / "execution-receipt.json",
        "bed_report": root / spec["bed_attempt"] / "audit-output/c082s1-short-event-bed-footprint-audit.json",
    }


def summary_bed(report: dict[str, Any]) -> dict[str, Any]:
    frames = report.get("frame_reports", [])
    require(report.get("scan", {}).get("frames_scanned") == 51 and len(frames) == 51, "short bed report is not 51 frames")
    one = [int(frame.get("penetration", {}).get("one_dp", {}).get("count", -1)) for frame in frames]
    two = [int(frame.get("penetration", {}).get("two_dp", {}).get("count", -1)) for frame in frames]
    missing = [int(frame.get("uid_tracking", {}).get("missing_initial_uid", {}).get("count", -1)) for frame in frames]
    nonfinite = [int(frame.get("nonfinite_initial_fluid_uid_count", -1)) for frame in frames]
    xout = [int(frame.get("bed_domain", {}).get("x_outside_exact_profile_domain_count", -1)) for frame in frames]
    yout = [int(frame.get("bed_domain", {}).get("y_outside_actual_bed_footprint_with_x_in_domain_count", -1)) for frame in frames]
    require(max(one) == 0 and max(two) == 0 and max(missing) == 0 and max(nonfinite) == 0 and max(xout) == 0 and max(yout) == 0, "actual short bed report has unexpected nonzero diagnostic")
    return {
        "frames": 51,
        "particle_axis": int(report["scan"]["particle_axis_count"]),
        "initial_fluid_uid_count": int(report["scan"]["initial_fluid_uid_count"]),
        "max_one_dp_count": max(one),
        "max_two_dp_count": max(two),
        "max_missing_initial_uid": max(missing),
        "max_nonfinite_initial_uid": max(nonfinite),
        "max_outside_profile_x": max(xout),
        "max_outside_bed_y": max(yout),
        "time_last_s": float(report["scan"]["times_s"]["last"]),
        "profile_and_thresholds_unchanged": True,
        "diagnostic_only": report.get("diagnostic_only") is True,
        "repair_success": report.get("repair_success"),
        "visual_review": "WAIT",
        "full801_authorized": False,
        "q_n_granted": False,
    }


def patch_worker(candidate: str) -> str:
    path = PKG / "workers" / f"bed_audit_{candidate}.py"
    text = path.read_text(encoding="utf-8")
    new = 'BINDING_SCHEMA = "ds02.f5.c082s1.short-dynamic-bed-audit-binding.fresh109.v1"'
    text = text.replace("short-event-bed-audit-binding", "short-dynamic-bed-audit-binding")
    require(new in text, f"{candidate}: worker schema anchor")
    ast.parse(text, filename=str(path))
    path.write_text(text, encoding="utf-8")
    return sha(path)


def update_actual_bindings(candidate: str, bed_worker_sha: str) -> dict[str, Any]:
    paths = actual_paths(candidate)
    xmf_receipt = load(paths["xmf_receipt"])
    xmf_manifest = load(paths["xmf_manifest"])
    bed_receipt = load(paths["bed_receipt"])
    bed_report = load(paths["bed_report"])
    require(xmf_receipt.get("status") == "completed" and int(xmf_receipt.get("returncode", -1)) == 0, f"{candidate}: XMF receipt")
    require(bed_receipt.get("status") == "completed" and int(bed_receipt.get("returncode", -1)) == 0, f"{candidate}: bed receipt")
    require(xmf_manifest.get("frames") == 51 and xmf_manifest.get("particles") == COUNTS["total"], f"{candidate}: XMF shape")
    bed_summary = summary_bed(bed_report)
    xmf_sha = sha(paths["xmf_manifest"])
    bed_report_sha = sha(paths["bed_report"])
    bed_receipt_sha = sha(paths["bed_receipt"])
    xmf_receipt_sha = sha(paths["xmf_receipt"])

    xmf_binding_path = PKG / "bindings" / f"{candidate}-short-xmf-binding.json"
    xmf_binding = load(xmf_binding_path)
    xmf_binding.update({
        "xmf_actual": {
            "attempt_id": CANDIDATES[candidate]["xmf_attempt"],
            "receipt": str(paths["xmf_receipt"]),
            "receipt_sha256": xmf_receipt_sha,
            "manifest": str(paths["xmf_manifest"]),
            "manifest_sha256": xmf_sha,
            "xdmf": xmf_manifest.get("xdmf"),
            "xdmf_sha256": xmf_manifest.get("xdmf_sha256"),
            "completed0": True,
            "frames": 51,
            "particles": COUNTS["total"],
        },
        "short_visual_review": {"status": "WAIT", "report": None, "receipt": None, "full801_gate": "blocked"},
    })
    dump(xmf_binding_path, xmf_binding)

    bed_binding_path = PKG / "bindings" / f"{candidate}-short-bed-audit-binding.json"
    bed_binding = load(bed_binding_path)
    bed_binding.update({
        "schema": "ds02.f5.c082s1.short-dynamic-bed-audit-binding.fresh109.v1",
        "xmf_manifest": str(paths["xmf_manifest"]),
        "xmf_manifest_sha256": xmf_sha,
        "xmf": xmf_manifest.get("xdmf"),
        "xmf_sha256": xmf_manifest.get("xdmf_sha256"),
        "xdmf": xmf_manifest.get("xdmf"),
        "xdmf_sha256": xmf_manifest.get("xdmf_sha256"),
        "short_bed_audit": {
            "attempt_id": CANDIDATES[candidate]["bed_attempt"],
            "receipt": str(paths["bed_receipt"]),
            "receipt_sha256": bed_receipt_sha,
            "report": str(paths["bed_report"]),
            "report_sha256": bed_report_sha,
            "completed0": True,
            "report_schema": bed_report.get("schema"),
            "summary": bed_summary,
        },
        "short_visual_review": {"status": "WAIT", "report": None, "receipt": None, "full801_gate": "blocked"},
        "worker_contract": {**bed_binding.get("worker_contract", {}), "worker_source": f"workers/bed_audit_{candidate}.py", "worker_source_sha256": bed_worker_sha, "binding_schema_matches_worker": True},
        "full801_authorized": False,
        "q_n_granted": False,
        "case_credit": False,
    })
    dump(bed_binding_path, bed_binding)
    return {"paths": paths, "xmf_manifest": xmf_manifest, "xmf_receipt": xmf_receipt, "bed_report": bed_report, "bed_receipt": bed_receipt, "xmf_sha256": xmf_sha, "xmf_receipt_sha256": xmf_receipt_sha, "bed_report_sha256": bed_report_sha, "bed_receipt_sha256": bed_receipt_sha, "bed_summary": bed_summary}


def static_input_closure(candidate: str, actual: dict[str, Any]) -> tuple[list[str], dict[str, str | None], dict[str, str]]:
    bed_binding_path = PKG / "bindings" / f"{candidate}-short-bed-audit-binding.json"
    xmf_binding_path = PKG / "bindings" / f"{candidate}-short-xmf-binding.json"
    physical_path = PKG / "bindings" / f"{candidate}-physical-binding.json"
    owner_path = PKG / "metadata" / f"{candidate}-typed-producer-owner.json"
    native_att = PKG / "metadata" / f"{candidate}-actual-native-typed-attestation.json"
    native = load(PKG / "metadata" / f"{candidate}-actual-native-typed-attestation.json")
    # Use the already-bound actual XML/JSON producer metadata and local source
    # files; never include BI4/H5/CSV/VTK payloads in this closure.
    files = [physical_path, owner_path, xmf_binding_path, bed_binding_path, native_att,
             PKG / "inputs" / f"{candidate}-Definition.xml", PKG / "inputs" / f"{candidate}-owner.json",
             PKG / "workers" / f"bed_audit_{candidate}.py", PKG / "workers/export_xmf_legacy_aware.py",
             RUNTIME, STRICT, ROOT230_POLICY, ROOT230_LAUNCH, RESOURCE,
             actual["paths"]["xmf_receipt"], actual["paths"]["xmf_manifest"], actual["paths"]["bed_receipt"], actual["paths"]["bed_report"],
             Path(str(native["native"]["receipt"])),
             Path(str(load(bed_binding_path)["gencase_receipt"])),
             Path(str(load(bed_binding_path)["gencase_prepared_report"])),
             Path(str(load(bed_binding_path)["canonical_generated_xml"])),
             Path(str(load(bed_binding_path)["initial_qa_receipt"])),
             Path(str(load(bed_binding_path)["initial_qa_report"])),
             RESOURCE,
             ]
    unique: list[Path] = []
    for path in files:
        if path not in unique:
            unique.append(path)
    hashes: dict[str, str | None] = {}
    provenance: dict[str, str] = {}
    for path in unique:
        require(path.is_file(), f"missing static full801 input: {path}")
        suffix = path.suffix.lower()
        require(suffix not in SCIENCE, f"science payload accidentally listed: {path}")
        require(suffix in HASHABLE, f"unsupported nonpayload input: {path}")
        text = str(path)
        hashes[text] = sha(path)
        provenance[text] = "JSON/XML/Python/text metadata hashed by fresh109 source preparation"
    # The full solver must resolve the actual transformed motion asset.  The
    # path and SHA are copied from the completed Root455 native request; the
    # DAT itself is never opened or hashed by this source builder.
    native_request = load(Path(str(native["native"]["request"])))
    motion_path = Path(str(native_request.get("motion_asset_path", "")))
    motion_sha = native_request.get("motion_asset_sha256")
    require(motion_path.suffix.lower() == ".dat" and motion_path.is_file(), f"missing producer motion asset path: {motion_path}")
    require(isinstance(motion_sha, str) and len(motion_sha) == 64, "producer motion SHA missing")
    files.append(str(motion_path))
    hashes[str(motion_path)] = motion_sha
    provenance[str(motion_path)] = "producer-declared motion asset SHA; source agent did not read or hash DAT"
    files.append(str(SOLVER)); hashes[str(SOLVER)] = None; provenance[str(SOLVER)] = "official solver executable; source agent did not open or hash binary"
    return sorted({str(path) for path in files}), hashes, provenance


def full_request(candidate: str, actual: dict[str, Any]) -> None:
    bed = load(PKG / "bindings" / f"{candidate}-short-bed-audit-binding.json")
    physical = load(PKG / "bindings" / f"{candidate}-physical-binding.json")
    native_att = load(PKG / "metadata" / f"{candidate}-actual-native-typed-attestation.json")
    native_request = load(Path(str(native_att["native"]["request"])))
    gencase_receipt = Path(str(bed["gencase_receipt"]))
    generated_xml = Path(str(bed["canonical_generated_xml"]))
    prepared_root = generated_xml.parent
    gencase_prefix = str(generated_xml.with_suffix(""))
    files, hashes, provenance = static_input_closure(candidate, actual)
    attempt = CANDIDATES[candidate]["full_attempt"]
    command = [str(SOLVER), gencase_prefix, "{attempt_root}/solver_output", "-tmax:16.0", "-tout:0.02"]
    request = {
        "schema": "ds02.runner-request.v2",
        "kind": "qualification",
        "cpu_task_kind": "solver",
        "attempt_id": attempt,
        "candidate_id": f"C082S1_MOTION_{candidate}",
        "case_id": CASE,
        "family_id": "F5",
        "condition_id": CANDIDATES[candidate]["condition_id"],
        "physical_case_id": physical["physical_case_id"],
        "physical_binding_path": str(PKG / "bindings" / f"{candidate}-physical-binding.json"),
        "physical_binding_sha256": sha(PKG / "bindings" / f"{candidate}-physical-binding.json"),
        "physical_condition_sha256": physical["physical_condition_sha256"],
        "source_plan_physical_condition_sha256": physical["source_plan_physical_condition_sha256"],
        "depends_on_attempt": CANDIDATES[candidate]["bed_attempt"],
        "depends_on_attempts": [CANDIDATES[candidate]["bed_attempt"]],
        "command": command,
        "cwd": str(prepared_root),
        "gencase_prefix": gencase_prefix,
        "gencase_attempt_id": bed["gencase_attempt_id"],
        "gencase_receipt": bed["gencase_receipt"],
        "gencase_receipt_sha256": bed["gencase_receipt_sha256"],
        "generated_xml": bed["canonical_generated_xml"],
        "generated_xml_sha256": bed["canonical_generated_xml_sha256"],
        "generated_bi4": "<root-bind:generated_bi4>",
        "generated_bi4_sha256": None,
        "motion_source_unchanged": True,
        "motion_asset_path": native_request.get("motion_asset_path"),
        "motion_asset_sha256": native_request.get("motion_asset_sha256"),
        "event_window_s": [0.0, 16.0],
        "tmax_s": 16.0,
        "tout_s": 0.02,
        "save_interval_s": 0.02,
        "disabled": True,
        "launch": False,
        "launch_allowed": False,
        "execution_allowed": False,
        "solver_allowed": False,
        "conversion_allowed": False,
        "source_only": True,
        "shared_registry_write_allowed": False,
        "arrays_allowed": False,
        "array_edit_allowed": False,
        "launch_owner": "root",
        "cpu_threads": 2,
        "omp_threads": 2,
        "max_wall_seconds": 7200,
        "estimated_peak_gpu_mib": 4096,
        "estimated_storage_bytes": 51539607552,
        "expected_frames": 801,
        "expected_dimension": 3,
        "expected_particle_axis": COUNTS["total"],
        "expected_particles": COUNTS["total"],
        "expected_fixed_particles": COUNTS["fixed"],
        "expected_moving_particles": COUNTS["moving"],
        "expected_floating_particles": COUNTS["floating"],
        "expected_fluid_particles": COUNTS["fluid"],
        "actual_counts": {**COUNTS, "dimension": 3},
        "native_bed_mk": 50,
        "source_mkbound": 40,
        "fluid_type_code": 3,
        "short_bed_audit": bed["short_bed_audit"],
        "short_visual_review": {"status": "WAIT", "report": None, "receipt": None, "visual_acceptance": False},
        "full801_gate": "blocked_until_root_short_visual_review_and_live_root230_lease",
        "root_full_launch_approval": None,
        "root_full_launch_approval_sha256": None,
        "root_inventory_policy_source": str(ROOT230_POLICY),
        "root_inventory_policy_source_sha256": ROOT230_POLICY_SHA,
        "root_actual_launch_source": str(ROOT230_LAUNCH),
        "root_actual_launch_source_sha256": ROOT230_LAUNCH_SHA,
        "root_dataset_inventory_profile": "root_home_floor_no_legacy_dataset_walk_native_v1",
        "root_gpu_selection_profile": "root_live_all_idle_uuid_leased_eight_solver_v2",
        "root_solver_concurrency_cap": 8,
        "root_effective_reservation_function_sha256": ROOT230_RESERVATION_SHA,
        "root_live_uuid_inventory": None,
        "root_shared_gpu_lease": None,
        "root_live_uuid_required_before_enable": True,
        "foreign_process_protection_required": True,
        "shared_lease_required": True,
        "resource_window": load(ROOT349_RECEIPT).get("request", {}).get("resource_window", {"gpu_hours": 512, "cpu_core_hours": 3840, "qualification_attempts": 1024, "production_attempts": 720, "home_min_free_bytes": 536870912000, "deadline_utc": "2026-10-14T07:23:48+00:00", "launch_owner": "root"}),
        "input_files": files,
        "input_sha256": hashes,
        "input_sha256_provenance": provenance,
        "future_output_hashes": {"solver_receipt_sha256": None, "solver_stdout_sha256": None, "solver_data_manifest_sha256": None, "solver_part_count": None, "typed_receipt_sha256": None, "xmf_receipt_sha256": None, "bed_audit_receipt_sha256": None},
        "future_candidate_fields_remain_null": True,
        "production_approval": "none",
        "full16_authorized": False,
        "full801_authorized": False,
        "q_n_granted": False,
        "independent_case_count_increment": 0,
        "root_review_required": True,
        "old_attempt_modification_forbidden": True,
        "no_new_case_credit": True,
        "status": "source_template_waiting_short_visual_review",
        "source_agent_did_not_read_science_payloads": True,
    }
    dump(PKG / "requests" / f"{candidate}-full801-native-request.json", request)


def write_attestation(candidate: str, actual: dict[str, Any]) -> None:
    paths = actual["paths"]
    value = {
        "schema": "ds02.f5.c082s1.actual-short-bed-evidence.fresh109.v1",
        "candidate": candidate,
        "case_id": CASE,
        "xmf": {"attempt_id": CANDIDATES[candidate]["xmf_attempt"], "receipt": str(paths["xmf_receipt"]), "receipt_sha256": actual["xmf_receipt_sha256"], "manifest": str(paths["xmf_manifest"]), "manifest_sha256": actual["xmf_sha256"], "completed0": True, "frames": 51, "particles": COUNTS["total"]},
        "bed": {"attempt_id": CANDIDATES[candidate]["bed_attempt"], "receipt": str(paths["bed_receipt"]), "receipt_sha256": actual["bed_receipt_sha256"], "report": str(paths["bed_report"]), "report_sha256": actual["bed_report_sha256"], "completed0": True, **actual["bed_summary"]},
        "visual_review": {"status": "WAIT", "report": None, "receipt": None, "full801_gate": "blocked"},
        "exact_dp_lattice_negative_retained": True,
        "full801_authorized": False,
        "q_n_granted": False,
        "independent_case_count_increment": 0,
        "science_payloads_read_or_hashed_by_source_builder": False,
    }
    dump(PKG / "metadata" / f"{candidate}-actual-short-bed-evidence.json", value)


def write_readme(actuals: dict[str, Any]) -> None:
    lines = [
        "# F5 fresh109: actual short bed evidence and disabled full801 native templates",
        "",
        "Root506 XMF and Root509 dynamic bed audits are actual completed/0 producer evidence. This source-only pack reads only their JSON/XML metadata; it does not read or hash H5/BI4/CSV/VTK/DAT and does not start a solver.",
        "",
        "## Short-window evidence",
        "",
    ]
    for candidate in sorted(actuals):
        s = actuals[candidate]["bed_summary"]
        lines.append(f"- {candidate}: 51 frames, N={COUNTS['total']}, fluid UID denominator={COUNTS['fluid']}, max 1DP={s['max_one_dp_count']}, max 2DP={s['max_two_dp_count']}, max missing UID={s['max_missing_initial_uid']}, max nonfinite UID={s['max_nonfinite_initial_uid']}, x/y outside footprint={s['max_outside_profile_x']}/{s['max_outside_bed_y']}; report remains diagnostic-only and visual review is WAIT.")
    lines.extend([
        "",
        "The bed worker binding schema is exactly `ds02.f5.c082s1.short-dynamic-bed-audit-binding.fresh109.v1`, matching both fresh109 candidate worker constants. The historical actual Root506 request used the runtime CPU `audit` task kind for the XMF producer; fresh109 keeps that allowlisted CPU kind in any disabled short request template.",
        "",
        "`requests/*-full801-native-request.json` are 16 s, tout=.02, 801-frame, 3-D native solver templates with CPU threads=2 and Root230 live UUID/lease/foreign-process protection fields. They remain disabled because short-window visual report/receipt are WAIT/null. No full801, Q-N, or case credit is granted.",
        "",
        "The exact DP lattice 1e-6 negative is retained as an independent numerical diagnostic. Short 0..1 s bed evidence and visual review do not certify the full 16 s runup event.",
    ])
    (PKG / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_plan(actuals: dict[str, Any]) -> None:
    candidates = {}
    for candidate, actual in actuals.items():
        candidates[candidate] = {"short_bed": actual["bed_summary"], "xmf_completed0": True, "bed_completed0": True, "visual_review": "WAIT", "full801_request": CANDIDATES[candidate]["full_attempt"], "full801_authorized": False}
    dump(PKG / "metadata" / "fresh109-source-plan.json", {
        "schema": "ds02.f5.c082s1.fresh109-source-plan.v1",
        "status": "actual_short_bed_bound_full801_disabled",
        "candidates": candidates,
        "native_full_window": {"frames": 801, "tmax_s": 16.0, "tout_s": 0.02, "dimension": 3, "cpu_threads": 2},
        "root230_live_lease_required": True,
        "short_visual_review": "WAIT/null; no full801 enablement",
        "exact_dp_lattice_negative_retained": True,
        "full801_authorized": False,
        "q_n_granted": False,
        "independent_case_count_increment": 0,
        "future_output_hashes": None,
        "science_payloads_read_or_hashed_by_source_builder": False,
        "jobs_started": False,
        "shared_state_modified": False,
    })


def refresh_request_closure(path: Path) -> None:
    """Rebind static source hashes after actual binding mutation.

    The short XMF/bed requests are copied source templates.  Their bindings
    are replaced with Root506/509 producer metadata above, so their local
    JSON/Python/XML inputs must be hashed after that replacement.  Producer
    declared H5/DAT hashes remain opaque and are never recomputed here.
    """
    request = load(path)
    files = request.get("input_files", [])
    hashes = request.get("input_sha256", {})
    provenance = request.get("input_sha256_provenance", {})
    require(isinstance(files, list) and isinstance(hashes, dict) and isinstance(provenance, dict), f"{path}: request closure shape")
    for raw in files:
        text = str(raw)
        if text.startswith("<root-bind:"):
            require(hashes.get(text) is None, f"{path}: placeholder hash must remain null")
            continue
        source = Path(text)
        suffix = source.suffix.lower()
        if suffix in SCIENCE:
            require(suffix in {".h5", ".dat"}, f"{path}: unsupported science input {source}")
            require(isinstance(hashes.get(text), str) and len(str(hashes[text])) == 64, f"{path}: producer payload SHA missing {source}")
            require("producer-declared" in str(provenance.get(text, "")), f"{path}: producer payload provenance missing {source}")
            continue
        if suffix in HASHABLE:
            require(source.is_file(), f"{path}: static input missing {source}")
            hashes[text] = sha(source)
            provenance[text] = "JSON/XML/Python/text metadata hashed by fresh109 source preparation"
            continue
        require(hashes.get(text) is None, f"{path}: executable input must remain un-hashed {source}")
    dump(path, request)


def write_manifest() -> None:
    files = {}
    report = PKG / "metadata" / "fresh109-validator-report.json"
    for path in sorted(PKG.rglob("*")):
        if not path.is_file() or path.name == "manifest.json" or path == report:
            continue
        require(path.suffix.lower() in HASHABLE and path.suffix.lower() not in SCIENCE, f"unsupported package file: {path}")
        files[str(path.relative_to(PKG))] = sha(path)
    dump(PKG / "manifest.json", {"schema": "ds02.f5.c082s1.fresh109-source-manifest.v1", "status": "actual_short_bed_bound_full801_disabled", "package": str(PKG), "files": files, "validator_report_excluded_from_manifest": True, "full801_authorized": False, "q_n_granted": False, "independent_case_count_increment": 0, "science_payloads_read_or_hashed_by_source_builder": False, "jobs_started": False, "shared_state_modified": False})


def main() -> int:
    actuals = {}
    for candidate in CANDIDATES:
        bed_worker_sha = patch_worker(candidate)
        actual = update_actual_bindings(candidate, bed_worker_sha)
        actual["paths"] = actual.pop("paths")
        actuals[candidate] = actual
        write_attestation(candidate, actual)
        full_request(candidate, actual)
    # CPU XMF short request is a source template only; Root506 already ran it.
    for candidate in CANDIDATES:
        p = PKG / "requests" / f"{candidate}-xmf-request.json"
        value = load(p)
        value["cpu_task_kind"] = "audit"
        value["runtime_task_kind_alias"] = "xmf_export_worker_under_allowlisted_audit"
        value["actual_producer_attempt"] = CANDIDATES[candidate]["xmf_attempt"]
        value["actual_producer_completed0"] = True
        dump(p, value)
        # The previous loop rewrote both bindings and the XMF request fields.
        # Refresh both short request closures only after those mutations are
        # complete; this prevents a self-consistent package from carrying the
        # prior binding hashes.
        refresh_request_closure(p)
        refresh_request_closure(PKG / "requests" / f"{candidate}-bed-audit-request.json")
    write_plan(actuals)
    write_readme(actuals)
    write_manifest()
    print(json.dumps({"status": "built", "candidates": sorted(CANDIDATES), "full801_disabled": True}, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
