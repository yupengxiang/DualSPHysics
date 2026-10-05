#!/usr/bin/env python3
"""Build the fresh070 F3 AY0540 Root140 native-to-NVMe source handoff.

This generator consumes only JSON and small source metadata.  It never opens
or hashes BI4, CSV, H5, HDF5, NPY, or NPZ payloads.  Their registered digests
come from the completed native receipts.  It discovers the completed native
receipt for each requested case, verifies the Root123 source authority and
physical-condition identity, then emits disabled typed-conversion requests.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
INTEGRATION_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
INTEGRATION_LAB = INTEGRATION_ROOT / "lagrangian-fluid-lab"
DATA_F3 = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3")
SCOPE123 = (
    INTEGRATION_LAB
    / "campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_f3_first24_verified_nvme_production_scope_123"
)
INDEX123 = SCOPE123 / "derived-candidate-index.json"
DERIVED_SCOPE = SCOPE123 / "derived-scope-entry.json"
SCOPE_REGISTRATION = SCOPE123 / "actual-scope-registration.json"
TYPED_TEMPLATE = (
    INTEGRATION_LAB
    / "campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_f3_visual_endpoints_full_typed_011/lower-request.json"
)
Genuine_GenCase = DATA_F3 / (
    "F3_CELL3_LONG_DP006_AY0P50_ADAPTIVE_CFL05_COEF005/"
    "root-cell3-dp006-twoaxis-ay0p50-actual-gencase-056/execution-receipt.json"
)
PARENT_INITIAL_QA = DATA_F3 / (
    "F3_TWOAXIS_NOMINAL_THREE_DP_ACTUAL_INITIAL_QA/"
    "root-cell3-twoaxis-nominal-three-dp-official-native-initial-qa-058/"
    "native-initial-qa.json"
)
TARGET_SCOPE = "F3_STAGE1_FIRST24_AY0250_AY0750_VISUAL_V1"
FRESH_ID = "fresh070"
STAGING_ROOT = "/tmp/ds02-nvme-conversion"
STAGING_LIMIT = "25769803776"
RESOURCE_WINDOW = (
    INTEGRATION_LAB
    / "campaigns/ds-data-02/handoff_20261003/"
    "root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"
)
RESOURCE_POLICY = (
    INTEGRATION_LAB
    / "campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_f3_first24_eight_solver_resource_policy_134/resource-policy-check.json"
)
ROOT134_MANIFEST = (
    INTEGRATION_LAB
    / "campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_f3_first24_eight_solver_resource_policy_134/source-enabling-manifest.json"
)
ROOT140_REQUEST = (
    INTEGRATION_LAB
    / "campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_f3_ay0540_after_idle_uuid_retry_140/request.json"
)
ROOT142_POLICY_CHECK = (
    INTEGRATION_LAB
    / "campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_home_floor_inventory_dispatch_142/policy-check.json"
)
ROOT142_CONTRACT = (
    INTEGRATION_LAB
    / "campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_home_floor_inventory_dispatch_142/source-policy-contract.json"
)
ROOT142_LAUNCH = (
    INTEGRATION_LAB
    / "campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_home_floor_inventory_dispatch_142/launch.py"
)
TYPED_IDENTITY_POLICY = {
    "identity_key": "(Zone,Idp)",
    "zone_source": "BI4 Piece",
    "idp_source": "decoder Idp / GenCase particle ranges",
    "preserve_native_zone_id": True,
    "preserve_native_idp": True,
    "no_zone_relabeling": True,
    "source_builder_reads_arrays": False,
    "worker_must_check_zone_piece_stability": True,
    "typed_identity_evidence_status": "future_until_strict_conversion",
}
NATIVE_QUALITY_POLICY = {
    "actual_3d": True,
    "native_particles": 179208,
    "native_fluid_particles": 67500,
    "native_fixed_particles": 111708,
    "continuum_reference_mass_kg": 14.58,
    "native_fluid_mass_kg": 14.580000000000002,
    "mass_policy": "native_massfluid_no_rescaling",
    "mass_rescale": False,
    "particle_count_override": False,
    "native_receipt_authoritative": True,
    "source": "GenCase056 + parent initial QA058 + completed Root140 native request metadata",
}
ARRAY_SUFFIXES = {".bi4", ".csv", ".h5", ".hdf5", ".npy", ".npz"}
OPAQUE_EXECUTABLES = {"python", "bi4_dump", "PartVTK_linux64"}
CASE_IDS = (
    "F3_STAGE1_DP006_P1000_AY0540",
)
FIRST24_CASE_IDS = set(CASE_IDS)


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def resource_guard_snapshot() -> dict[str, Any]:
    """Bind the approved budget/resource guards without changing shared state."""
    window = load(RESOURCE_WINDOW)
    limits = window["new_limits"]
    expected = {
        "gpu_seconds": 1843200,
        "cpu_core_seconds": 13824000,
        "qualification_attempts": 1024,
        "production_attempts": 720,
        "home_min_free_bytes": 536870912000,
    }
    for key, value in expected.items():
        if limits.get(key) != value:
            raise RuntimeError(f"resource window {key} changed: {limits.get(key)!r} != {value!r}")
    if window.get("deadline_utc") != "2026-10-14T07:23:48+00:00":
        raise RuntimeError("resource window deadline changed")
    policy = load(RESOURCE_POLICY)
    manifest = load(ROOT134_MANIFEST)
    if policy.get("all_passed") is not True or policy.get("fixture_only_no_shared_state_mutation") is not True:
        raise RuntimeError("Root134 resource policy fixture is not passing/immutable")
    effective = policy["effective_policy"]
    if effective.get("effective_function_sha256") != "46e62ea197862a833797556d09350126b3632b2e3b1d496d08816ee42f7abecf":
        raise RuntimeError("unexpected Root134 effective resource policy")
    if manifest.get("solver_concurrency_maximum") != 8 or manifest.get("conversion_concurrency_unchanged") != 2:
        raise RuntimeError("unexpected Root134 concurrency policy")
    root142_policy = load(ROOT142_POLICY_CHECK)
    root142_contract = load(ROOT142_CONTRACT)
    if root142_policy.get("all_passed") is not True or root142_policy.get("runtime_source_unchanged") is not True:
        raise RuntimeError("Root142 Home-floor policy fixture is not passing/unchanged")
    if root142_policy.get("actual_checks", {}).get("home_floor_not_weakened") is not True:
        raise RuntimeError("Root142 Home-floor guard was not proven")
    if root142_policy.get("actual_checks", {}).get("cpu_parent_budget_not_weakened") is not True:
        raise RuntimeError("Root142 CPU parent budget guard was not proven")
    if root142_policy.get("actual_checks", {}).get("unreviewed_native_profile_rejected") is not True:
        raise RuntimeError("Root142 native profile rejection guard was not proven")
    if root142_policy.get("no_native_or_array_jobs") is not True:
        raise RuntimeError("Root142 fixture unexpectedly ran native/array jobs")
    if root142_contract.get("profile") != "root_home_floor_no_legacy_dataset_walk_v1" or root142_contract.get("source_enabling_only") is not True:
        raise RuntimeError("unexpected Root142 source-policy contract")
    return {
        "home_min_free_bytes": limits["home_min_free_bytes"],
        "home_min_free_gib": window["home_min_free_gib"],
        "nvme_stage_limit_bytes": int(STAGING_LIMIT),
        "nvme_worker_floor_bytes": 107374182400,
        "shared_cpu_thread_cap": 64,
        "native_solver_concurrency_cap": manifest["solver_concurrency_maximum"],
        "conversion_concurrency_cap": manifest["conversion_concurrency_unchanged"],
        "parent_gpu_seconds": limits["gpu_seconds"],
        "parent_cpu_core_seconds": limits["cpu_core_seconds"],
        "qualification_attempts": limits["qualification_attempts"],
        "production_attempts": limits["production_attempts"],
        "deadline_utc": window["deadline_utc"],
        "charges_reset": window["charges_reset"],
        "reservations_reset": window["reservations_reset"],
        "root134_effective_policy": {
            "core_file_sha256": effective["core_file_sha256"],
            "effective_function_sha256": effective["effective_function_sha256"],
            "other_source_bytes_identical": effective["other_source_bytes_identical"],
            "core_file_modified": effective["core_file_modified"],
        },
        "root142_home_floor_profile": {
            "profile": root142_contract["profile"],
            "root_cpu_only": root142_contract["root_cpu_only"],
            "runtime_core_unchanged": root142_contract["runtime_core_unchanged"],
            "actual_check_count": root142_contract["actual_check_count"],
            "source_enabling_only": root142_contract["source_enabling_only"],
            "source": {
                "policy_check": file_ref(ROOT142_POLICY_CHECK),
                "source_policy_contract": file_ref(ROOT142_CONTRACT),
                "launch_source": file_ref(ROOT142_LAUNCH),
            },
        },
        "source": {
            "resource_window": file_ref(RESOURCE_WINDOW),
            "resource_policy_check": file_ref(RESOURCE_POLICY),
            "root134_enabling_manifest": file_ref(ROOT134_MANIFEST),
            "root140_launch_request": file_ref(ROOT140_REQUEST),
            "root142_policy_check": file_ref(ROOT142_POLICY_CHECK),
            "root142_source_policy_contract": file_ref(ROOT142_CONTRACT),
        },
        "live_conversion_protection": {
            "conversion_slots_reserved_by_existing_live_work": 2,
            "must_not_touch_existing_p01_p03_conversions": True,
            "must_not_touch_root147_ay0590_ay0610_native_launches": True,
        },
    }


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    if path.suffix.lower() in ARRAY_SUFFIXES:
        raise RuntimeError(f"refusing to hash array-bearing payload: {path}")
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def file_ref(path: Path, registered_sha: str | None = None) -> dict[str, str]:
    return {"path": str(path), "sha256": registered_sha or digest(path)}


def add_ref(refs: dict[str, str], path: str | Path, sha256: str) -> None:
    raw = str(path)
    previous = refs.get(raw)
    if previous is not None and previous != sha256:
        raise RuntimeError(f"conflicting registered hashes for {raw}: {previous} != {sha256}")
    refs[raw] = sha256


def find_optional_input_hash(hashes: dict[str, str], path: str | Path) -> str | None:
    return hashes.get(str(path))


def output_ref(path: Path, sha256: str | None) -> dict[str, str | None]:
    value: dict[str, str | None] = {"path": str(path), "sha256": sha256}
    if sha256 is None:
        value["sha256_source"] = "not_registered_in_completed_native_receipt; source package did not read output"
    return value


def find_native_receipt(case_id: str) -> tuple[Path, dict[str, Any]]:
    case_dir = DATA_F3 / case_id
    matches: list[tuple[Path, dict[str, Any]]] = []
    for path in case_dir.rglob("execution-receipt.json"):
        receipt = load(path)
        request = receipt.get("request", {})
        command = receipt.get("command", [])
        if (
            request.get("case_id") == case_id
            and request.get("expected_saved_frames") == 836
            and receipt.get("status") == "completed"
            and receipt.get("returncode") == 0
            and any("DualSPHysics5.4_linux64" in str(item) for item in command)
            and any(str(item).startswith("-gpu:") for item in command)
            and "-mdbc_noslip:1" in command
            and "-tmax:8.35" in command
            and "-tout:0.01" in command
        ):
            matches.append((path, receipt))
    if len(matches) != 1:
        raise RuntimeError(f"{case_id}: expected one completed native full836 receipt, found {len(matches)}")
    return matches[0]


def scope_by_id(index: dict[str, Any], scope_id: str) -> dict[str, Any]:
    for scope in index.get("scopes", []):
        if scope.get("scope_id") == scope_id:
            return scope
    raise RuntimeError(f"scope {scope_id} not found in Root123 derived candidate index")


def canonical_authority(case_id: str, native_request: dict[str, Any]) -> dict[str, Any]:
    """Return read-only Root authority references and verify the condition hash."""
    index = load(INDEX123)
    target_scope = scope_by_id(index, TARGET_SCOPE)
    authority: dict[str, Any] = {
        "root123_candidate_index": file_ref(INDEX123),
        "root123_target_scope_entry": file_ref(DERIVED_SCOPE),
        "root123_scope_registration": file_ref(SCOPE_REGISTRATION),
        "target_scope_id": TARGET_SCOPE,
        "target_scope_status": target_scope.get("status"),
        "target_scope_registered_execution_allowed": target_scope.get("execution_allowed"),
    }
    if case_id in FIRST24_CASE_IDS:
        root_request_path = SCOPE123 / "requests" / f"{case_id}.json"
        root_request = load(root_request_path)
        if root_request.get("physical_condition_sha256") != native_request.get("physical_condition_sha256"):
            raise RuntimeError(
                f"{case_id}: Root123 condition {root_request.get('physical_condition_sha256')} "
                f"does not match completed native {native_request.get('physical_condition_sha256')}"
            )
        if root_request.get("physical_case_id") != native_request.get("physical_case_id"):
            raise RuntimeError(
                f"{case_id}: Root123 physical ID {root_request.get('physical_case_id')} "
                f"does not match completed native {native_request.get('physical_case_id')}"
            )
        authority["canonical_condition_source"] = file_ref(root_request_path)
        authority["canonical_condition_source_kind"] = "Root123 per-case request plus completed native receipt"
        authority["canonical_condition_source_snapshot"] = {
            key: copy.deepcopy(root_request.get(key))
            for key in (
                "case_id",
                "physical_case_id",
                "role",
                "parameter_tuple",
                "physical_condition_sha256",
                "transverse_amplitude_m_s2",
                "nominal_pitch_multiplier",
                "expected_saved_frames",
                "actual_solver_command",
            )
            if key in root_request
        }
    else:
        raise RuntimeError(case_id)
    return authority


def stable_worker_inputs(template: dict[str, Any]) -> tuple[list[str], dict[str, str], dict[str, str]]:
    """Reuse the mature typed NVMe worker and its reviewed runtime inputs."""
    command = template["command"]
    input_hashes = template["input_sha256"]
    stable = [
        command[0],
        "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump",
        "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64",
        command[1],
        "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_direct_convert.py",
        "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_f3_nvme_input_audit_v1.py",
        "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_convert.py",
        "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py",
        "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py",
    ]
    for path in stable:
        if path not in input_hashes:
            raise RuntimeError(f"mature request has no hash for worker input {path}")
    return stable, {path: input_hashes[path] for path in stable}, {
        "python": command[0],
        "nvme_wrapper": command[1],
        "decoder": stable[1],
        "partvtk": stable[2],
    }


def native_snapshot(request: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "case_id",
        "physical_case_id",
        "role",
        "order",
        "scope_id",
        "parameter_tuple",
        "physical_condition_sha256",
        "transverse_amplitude_m_s2",
        "nominal_pitch_multiplier",
        "numerical_recipe",
        "physics",
        "geometry",
        "event_window_s",
        "complete_event_window_s",
        "save_interval_s",
        "expected_saved_frames",
        "actual_solver_command",
        "actual_solver_cwd",
        "qa_semantics",
        "parent_group_id",
        "gencase_receipt",
        "gencase_receipt_sha256",
        "prepared_input",
        "initial_native_reference",
        "source_owner",
        "visual_review_pending",
        "stage1_visual_status",
        "numerical_precision_status",
    )
    return {key: copy.deepcopy(request[key]) for key in keys if key in request}


def case_record(case_id: str, stable_hashes: dict[str, str], stable_paths: list[str], tools: dict[str, str], resource_guards: dict[str, Any]) -> dict[str, Any]:
    receipt_path, receipt = find_native_receipt(case_id)
    native_request = receipt["request"]
    native_receipt_sha = digest(receipt_path)
    authority = canonical_authority(case_id, native_request)
    output_root = Path(receipt["output_root"])
    solver_log = output_root / "solver_output" / "Run.out"
    parts_csv = output_root / "solver_output" / "RunPARTs.csv"
    data_root = output_root / "solver_output" / "data"
    receipt_hashes = receipt.get("input_hashes_after_run", {})
    solver_log_sha = find_optional_input_hash(receipt_hashes, solver_log)
    parts_csv_sha = find_optional_input_hash(receipt_hashes, parts_csv)

    prepared = native_request["prepared_input"]
    report = prepared["report"]
    forcing = prepared["forcing"]
    generated_xml = prepared["generated_xml"]
    initial_bi4 = prepared["initial_bi4"]
    parent_qa = native_request["initial_native_reference"]["parent_initial_qa"]
    gencase = {
        "path": native_request["gencase_receipt"],
        "sha256": native_request["gencase_receipt_sha256"],
    }
    source_owner = native_request["source_owner"]
    if not source_owner or not source_owner.get("path") or not source_owner.get("sha256"):
        raise RuntimeError(f"{case_id}: completed native receipt has no source owner")
    if generated_xml.get("sha256") != "1162322010c42b9a084d76db0e20de571111cb009eb3afb699f2ee4c17d37406":
        raise RuntimeError(f"{case_id}: unexpected generated XML digest")
    if initial_bi4.get("sha256") != "c9c3fb8315dad402f77dd015539be376c3df68f332f3ed6d03e6c174e4c57d80":
        raise RuntimeError(f"{case_id}: unexpected initial BI4 digest")
    if native_request["physical_condition_sha256"] is None:
        raise RuntimeError(f"{case_id}: missing actual physical-condition digest")
    actual_initial = native_request.get("initial_native_reference", {})
    expected_initial = {
        "native_particles": NATIVE_QUALITY_POLICY["native_particles"],
        "native_fluid": NATIVE_QUALITY_POLICY["native_fluid_particles"],
        "native_fixed": NATIVE_QUALITY_POLICY["native_fixed_particles"],
    }
    for key, value in expected_initial.items():
        if actual_initial.get(key) != value:
            raise RuntimeError(f"{case_id}: unexpected actual {key} metadata")
    if actual_initial.get("actual_3d") is not True:
        raise RuntimeError(f"{case_id}: completed native request is not actual 3D")
    if actual_initial.get("mass_normalization") != "none":
        raise RuntimeError(f"{case_id}: native mass normalization is not none")

    owner_path = HERE / "owners" / f"{case_id}.json"
    request_path = HERE / "requests" / f"{case_id}.json"
    native_ref = {
        "receipt": file_ref(receipt_path, native_receipt_sha),
        "status": receipt["status"],
        "returncode": receipt["returncode"],
        "output_root": str(output_root),
        "data_root": str(data_root),
        "solver_log": output_ref(solver_log, solver_log_sha),
        "runparts_csv": output_ref(parts_csv, parts_csv_sha),
        "command": copy.deepcopy(receipt["command"]),
        "expected_saved_frames": native_request["expected_saved_frames"],
        "save_interval_s": native_request.get("save_interval_s"),
        "time_window_s": native_request.get("complete_event_window_s"),
        "request_sha256": receipt.get("request_sha256"),
        "native_scope_id": native_request.get("scope_id"),
    }
    prepared_ref = {
        "report": copy.deepcopy(report),
        "forcing": copy.deepcopy(forcing),
        "generated_xml": copy.deepcopy(generated_xml),
        "initial_bi4": copy.deepcopy(initial_bi4),
        "prepared_prefix": prepared.get("prepared_prefix"),
        "xml_byte_identical_to_baseline": prepared.get("xml_byte_identical_to_baseline"),
        "initial_bi4_byte_identical_to_baseline": prepared.get("initial_bi4_byte_identical_to_baseline"),
        "status": "actual_prepared_input_bound_from_completed_native_receipt",
    }
    initial_qa = copy.deepcopy(parent_qa)
    canonical = {
        "source_authority": copy.deepcopy(authority),
        "completed_native_receipt": native_ref["receipt"],
        "physical_case_id": native_request["physical_case_id"],
        "parameter_tuple": copy.deepcopy(native_request["parameter_tuple"]),
        "physical_condition_sha256": native_request["physical_condition_sha256"],
        "native_request_snapshot": native_snapshot(native_request),
    }

    owner = {
        "schema": "ds02.stage1.f3.first24-typed-nvme-owner.v1",
        "fresh_id": FRESH_ID,
        "status": "disabled_source_only_actual_native_bound_pending_typed_conversion",
        "source_only": True,
        "family_id": "F3",
        "case_id": case_id,
        "physical_case_id": native_request["physical_case_id"],
        "role": native_request.get("role"),
        "target_scope_id": TARGET_SCOPE,
        "native_scope_id": native_request.get("scope_id"),
        "canonical_condition": canonical,
        "source_owner": copy.deepcopy(source_owner),
        "root140_launch_request": file_ref(ROOT140_REQUEST),
        "native_quality_policy": copy.deepcopy(NATIVE_QUALITY_POLICY),
        "typed_identity_policy": copy.deepcopy(TYPED_IDENTITY_POLICY),
        "resource_guards": copy.deepcopy(resource_guards),
        "root142_home_floor_profile": copy.deepcopy(resource_guards["root142_home_floor_profile"]),
        "prepared_input": prepared_ref,
        "genuine_gencase_receipt": gencase,
        "parent_initial_qa": initial_qa,
        "native_full836": native_ref,
        "native_input_bindings": copy.deepcopy(native_request.get("input_bindings", [])),
        "worker": {
            "protocol": "strict_nvme_ds_data02_nvme_convert_v1",
            "command_reused_from": str(TYPED_TEMPLATE),
            "command_reused_from_sha256": digest(TYPED_TEMPLATE),
            "python": tools["python"],
            "nvme_wrapper": tools["nvme_wrapper"],
            "decoder": tools["decoder"],
            "partvtk": tools["partvtk"],
            "staging_root": STAGING_ROOT,
            "staging_limit_bytes": int(STAGING_LIMIT),
            "partvtk_validation": True,
            "particle_chunk": 65536,
        },
        "production_gate": {
            "launch_allowed": False,
            "execution_allowed": False,
            "production_approval": "none",
            "independent_case_count_increment": 0,
            "q_n": "not_granted",
            "q_e": "not_assessed",
            "numerical_precision_status": "not_accepted",
            "launch_owner": "root after explicit fresh070 authorization and CPU/runtime audit",
        },
        "future_typed_outputs": {
            "typed_execution_receipt": {"path": "{attempt_root}/execution-receipt.json", "sha256": None},
            "conversion_report": {"path": "{attempt_root}/conversion-report.json", "sha256": None},
            "trajectory_h5": {"path": "{attempt_root}/trajectory.h5", "sha256": None},
            "partvtk_validation": {"path": "{attempt_root}/partvtk-validation", "sha256": None},
            "visual_decision": None,
            "full_visual_evidence": None,
        },
        "claim_boundary": (
            "The completed native receipt is actual status=completed/returncode=0/full836 evidence. "
            "Typed conversion and visual evidence remain unexecuted and unapproved."
        ),
    }

    # Any original native input binding is reused as metadata; no payload is read.
    # The mature worker/runtime inputs remain part of the strict request closure.
    case_refs: dict[str, str] = dict(stable_hashes)
    for binding in native_request.get("input_bindings", []):
        add_ref(case_refs, binding["path"], binding["sha256"])
    for path, sha256 in (
        (SCOPE123 / "actual-scope-registration.json", digest(SCOPE_REGISTRATION)),
        (SCOPE123 / "derived-scope-entry.json", digest(DERIVED_SCOPE)),
        (INDEX123, digest(INDEX123)),
        (Path(authority["canonical_condition_source"]["path"]),
         authority["canonical_condition_source"].get("sha256")),
        (Path(report["path"]), report["sha256"]),
        (Path(forcing["path"]), forcing["sha256"]),
        (Path(generated_xml["path"]), generated_xml["sha256"]),
        (Path(initial_bi4["path"]), initial_bi4["sha256"]),
        (Path(gencase["path"]), gencase["sha256"]),
        (Path(parent_qa["path"]), parent_qa["sha256"]),
        (ROOT134_MANIFEST, digest(ROOT134_MANIFEST)),
        (ROOT140_REQUEST, digest(ROOT140_REQUEST)),
        (RESOURCE_WINDOW, digest(RESOURCE_WINDOW)),
        (RESOURCE_POLICY, digest(RESOURCE_POLICY)),
        (ROOT142_POLICY_CHECK, digest(ROOT142_POLICY_CHECK)),
        (ROOT142_CONTRACT, digest(ROOT142_CONTRACT)),
        (ROOT142_LAUNCH, digest(ROOT142_LAUNCH)),
        (receipt_path, native_receipt_sha),
        (solver_log, solver_log_sha),
        (parts_csv, parts_csv_sha),
    ):
        if path is not None and sha256 is not None:
            add_ref(case_refs, path, sha256)

    write(owner_path, owner)
    owner_sha = digest(owner_path)

    command = [
        tools["python"],
        tools["nvme_wrapper"],
        "--staging-root",
        STAGING_ROOT,
        "--staging-limit-bytes",
        STAGING_LIMIT,
        "--",
        "--data-root",
        str(data_root),
        "--generated-xml",
        generated_xml["path"],
        "--output",
        "{attempt_root}/trajectory.h5",
        "--report",
        "{attempt_root}/conversion-report.json",
        "--solver-log",
        str(solver_log),
        "--solver-receipt",
        str(receipt_path),
        "--gencase-receipt",
        gencase["path"],
        "--decoder",
        tools["decoder"],
        "--partvtk",
        tools["partvtk"],
        "--validation-dir",
        "{attempt_root}/partvtk-validation",
        "--keep-validation-csv",
        "--owner-metadata",
        str(owner_path),
        "--particle-chunk",
        "65536",
    ]
    input_files = list(stable_paths)
    # The actual native input bindings preserve the reviewed XML/BI4/GenCase/
    # QA/source evidence.  Deduplication is intentional and deterministic.
    for path in case_refs:
        if path not in input_files:
            input_files.append(path)
    add_ref(case_refs, owner_path, owner_sha)
    if str(owner_path) not in input_files:
        input_files.append(str(owner_path))
    request = {
        "schema": "ds02.runner-request.v2",
        "fresh_id": FRESH_ID,
        "family_id": "F3",
        "case_id": case_id,
        "attempt_id": f"root-stage1-f3-{case_id.rsplit('_', 1)[-1].lower()}-full836-typed-nvme-070",
        "kind": "cpu",
        "cpu_task_kind": "conversion",
        "cpu_threads": 2,
        "max_wall_seconds": 5400,
        "estimated_storage_bytes": int(STAGING_LIMIT),
        "cwd": str(INTEGRATION_LAB),
        "worktree_root": str(INTEGRATION_ROOT),
        "scope_id": TARGET_SCOPE,
        "visual_stage_profile": "stage1_visual",
        "target_scope_id": TARGET_SCOPE,
        "native_scope_id": native_request.get("scope_id"),
        "role": native_request.get("role"),
        "physical_case_id": native_request["physical_case_id"],
        "parameter_tuple": copy.deepcopy(native_request["parameter_tuple"]),
        "physical_condition_sha256": native_request["physical_condition_sha256"],
        "canonical_condition": canonical,
        "source_owner": {"path": str(owner_path), "sha256": owner_sha},
        "native_full836_binding": native_ref,
        "root140_launch_request": file_ref(ROOT140_REQUEST),
        "native_quality_policy": copy.deepcopy(NATIVE_QUALITY_POLICY),
        "typed_identity_policy": copy.deepcopy(TYPED_IDENTITY_POLICY),
        "resource_guards": copy.deepcopy(resource_guards),
        "root142_home_floor_profile": copy.deepcopy(resource_guards["root142_home_floor_profile"]),
        "prepared_input_gate": prepared_ref,
        "genuine_gencase_receipt": gencase,
        "parent_initial_qa": initial_qa,
        "native_solver_command": copy.deepcopy(native_request["actual_solver_command"]),
        "command": command,
        "input_files": input_files,
        "input_sha256": case_refs,
        "independent_case_count_increment": 0,
        "production_approval": "none",
        "launch_allowed": False,
        "execution_allowed": False,
        "launch_owner": "root",
        "q_n": "not_granted",
        "q_e": "not_assessed",
        "numerical_precision_status": "not_accepted",
        "visual_review_pending": True,
        "status": "disabled_source_only_actual_native_bound_pending_typed_conversion",
        "future_typed_outputs": copy.deepcopy(owner["future_typed_outputs"]),
        "claim": (
            "Actual native full836 receipt bound exactly. This request is disabled; "
            "typed conversion, PartVTK validation, H5, and visual decision remain future evidence."
        ),
    }
    write(request_path, request)

    return {
        "case_id": case_id,
        "physical_case_id": native_request["physical_case_id"],
        "role": native_request.get("role"),
        "native_scope_id": native_request.get("scope_id"),
        "native_receipt": native_ref,
        "native_physical_condition_sha256": native_request["physical_condition_sha256"],
        "source_authority": authority,
        "owner": file_ref(owner_path, owner_sha),
        "request": file_ref(request_path),
        "canonical_condition_source": authority["canonical_condition_source"],
        "future_typed_receipt_sha256": None,
        "future_h5_sha256": None,
    }


def main() -> None:
    template = load(TYPED_TEMPLATE)
    stable_paths, stable_hashes, tools = stable_worker_inputs(template)
    resource_guards = resource_guard_snapshot()
    for path in stable_paths:
        if not Path(path).exists():
            raise RuntimeError(f"missing mature NVMe worker input: {path}")

    (HERE / "owners").mkdir(parents=True, exist_ok=True)
    (HERE / "requests").mkdir(parents=True, exist_ok=True)
    records = [
        case_record(case_id, stable_hashes, stable_paths, tools, resource_guards)
        for case_id in CASE_IDS
    ]

    binding = {
        "schema": "ds02.stage1.f3.first24-typed-nvme-source-binding.v1",
        "fresh_id": FRESH_ID,
        "family_id": "F3",
        "target_scope_id": TARGET_SCOPE,
        "status": "source_only_disabled_actual_native_bound_pending_typed_conversion",
        "source_only": True,
        "root123_authority": {
            "candidate_index": file_ref(INDEX123),
            "target_scope_entry": file_ref(DERIVED_SCOPE),
            "scope_registration": file_ref(SCOPE_REGISTRATION),
        },
        "root140_launch_request": file_ref(ROOT140_REQUEST),
        "native_quality_policy": copy.deepcopy(NATIVE_QUALITY_POLICY),
        "typed_identity_policy": copy.deepcopy(TYPED_IDENTITY_POLICY),
        "resource_guards": copy.deepcopy(resource_guards),
        "root142_home_floor_profile": copy.deepcopy(resource_guards["root142_home_floor_profile"]),
        "worker": {
            "protocol": "strict_nvme_ds_data02_nvme_convert_v1",
            "template_request": file_ref(TYPED_TEMPLATE),
            "python": tools["python"],
            "nvme_wrapper": tools["nvme_wrapper"],
            "decoder": tools["decoder"],
            "partvtk": tools["partvtk"],
            "staging_root": STAGING_ROOT,
            "staging_limit_bytes": int(STAGING_LIMIT),
            "array_reading_by_source_builder": False,
            "solver_invocation_by_source_builder": False,
        },
        "cases": records,
        "resource_guards": copy.deepcopy(resource_guards),
        "native_quality_policy": copy.deepcopy(NATIVE_QUALITY_POLICY),
        "typed_identity_policy": copy.deepcopy(TYPED_IDENTITY_POLICY),
        "future_hash_policy": {
            "typed_execution_receipt_sha256": None,
            "conversion_report_sha256": None,
            "trajectory_h5_sha256": None,
            "partvtk_validation_sha256": None,
            "visual_decision_sha256": None,
            "source_builder_does_not_fabricate_future_hashes": True,
        },
        "claim_boundary": (
            "Only existing completed native full836 evidence is bound. "
            "The fresh070 CPU conversion request is disabled and do not grant "
            "production, Q-N, precision, or independent case count."
        ),
        "generator": file_ref(HERE / "build_fresh070_typed_requests.py"),
    }
    write(HERE / "source-binding.json", binding)

    manifest = {
        "schema": "ds02.stage1.f3.first24-typed-nvme-source-manifest.v1",
        "fresh_id": FRESH_ID,
        "family_id": "F3",
        "target_scope_id": TARGET_SCOPE,
        "status": "source_only_disabled_actual_native_bound_pending_typed_conversion",
        "source_only": True,
        "case_count": len(records),
        "case_ids": [row["case_id"] for row in records],
        "all_native_full836_completed_zero": all(
            row["native_receipt"]["status"] == "completed"
            and row["native_receipt"]["returncode"] == 0
            and row["native_receipt"]["expected_saved_frames"] == 836
            for row in records
        ),
        "all_typed_requests_disabled": True,
        "production_scope_approval": False,
        "q_n": "not_granted",
        "numerical_precision_status": "not_accepted",
        "independent_case_count_increment": 0,
        "root140_launch_request": file_ref(ROOT140_REQUEST),
        "native_quality_policy": copy.deepcopy(NATIVE_QUALITY_POLICY),
        "typed_identity_policy": copy.deepcopy(TYPED_IDENTITY_POLICY),
        "resource_guards": copy.deepcopy(resource_guards),
        "root142_home_floor_profile": copy.deepcopy(resource_guards["root142_home_floor_profile"]),
        "owner_paths": [row["owner"] for row in records],
        "request_paths": [row["request"] for row in records],
        "future_typed_receipt_sha256": None,
        "future_h5_sha256": None,
        "future_visual_decisions": None,
        "native_cases_excluded_from_this_handoff": [
            "F3_STAGE1_DP006_P1000_AY0590",
            "F3_STAGE1_DP006_P1000_AY0610",
            "F3_STAGE1_DP006_P1000_AY0670",
            "F3_STAGE1_DP006_P1000_AY0710",
        ],
        "raw_data_copied": False,
        "jobs_started": False,
    }
    write(HERE / "manifest.json", manifest)
    print(json.dumps({
        "package": str(HERE),
        "fresh_id": FRESH_ID,
        "cases": [row["case_id"] for row in records],
        "native_receipts": [
            {
                "case_id": row["case_id"],
                "path": row["native_receipt"]["receipt"]["path"],
                "sha256": row["native_receipt"]["receipt"]["sha256"],
                "status": row["native_receipt"]["status"],
                "returncode": row["native_receipt"]["returncode"],
            }
            for row in records
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
