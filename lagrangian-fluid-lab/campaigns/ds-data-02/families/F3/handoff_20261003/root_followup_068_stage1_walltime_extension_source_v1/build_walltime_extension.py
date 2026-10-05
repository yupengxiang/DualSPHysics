#!/usr/bin/env python3
"""Build or check disabled fresh068 wall-time derivatives from Root134 requests.

The source requests are read as JSON metadata only.  No input_files are opened,
no payload hash is recomputed, and no runtime entry point is imported.  Writing
is opt-in via --write; --check is read-only.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
REQUEST_DIR = HERE / "requests"
SOURCE_DIR = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    """lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"""
    """root_stage1_f3_first24_eight_solver_resource_policy_134/requests"""
)
POLICY_PATH = SOURCE_DIR.parent / "resource-policy-check.json"
WINDOW_PATH = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    """lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"""
    """root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"""
)
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3")
CASES = ("0590", "0610", "0670", "0710")
ALLOWED_DERIVED_FIELDS = {
    "attempt_id",
    "max_wall_seconds",
    "launch_allowed",
    "execution_allowed",
    "fresh068_lineage",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path):
    return json.loads(path.read_text())


def dump_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def observe_attempt(case_id: str, attempt_id: str) -> dict:
    """Read only the small execution receipt, if one exists."""
    receipt = DATA_ROOT / case_id / attempt_id / "execution-receipt.json"
    observation = {
        "receipt_path": str(receipt),
        "receipt_present": receipt.is_file(),
        "status": "no_receipt_at_observation",
        "returncode": None,
        "started_at_utc": None,
        "finished_at_utc": None,
        "gpu_seconds": None,
    }
    if receipt.is_file():
        value = load_json(receipt)
        observation.update(
            status=value.get("status"),
            returncode=value.get("returncode"),
            started_at_utc=value.get("started_at_utc"),
            finished_at_utc=value.get("finished_at_utc"),
            gpu_seconds=value.get("gpu_seconds"),
        )
    return observation


def policy_lineage() -> dict:
    policy = load_json(POLICY_PATH)
    window = load_json(WINDOW_PATH)
    return {
        "schema": "ds02.f3.fresh068-walltime-policy-lineage.v1",
        "source_only": True,
        "source_policy": {
            "path": str(POLICY_PATH),
            "sha256": digest(POLICY_PATH),
            "effective_function_sha256": policy["effective_policy"]["effective_function_sha256"],
            "core_file_sha256": policy["effective_policy"]["core_file_sha256"],
            "only_change": policy["effective_policy"]["only_change"],
            "other_source_bytes_identical": policy["effective_policy"]["other_source_bytes_identical"],
            "fixture_only_no_shared_state_mutation": policy["fixture_only_no_shared_state_mutation"],
        },
        "inherited_guards": {
            "solver_concurrency_maximum": 8,
            "conversion_concurrency_maximum": 2,
            "shared_cpu_thread_cap": 64,
            "home_min_free_gib": window["home_min_free_gib"],
            "home_min_free_bytes": window["new_limits"]["home_min_free_bytes"],
            "storage_policy": window["new_limits"]["storage_policy"],
            "parent_gpu_hours": window["gpu_hours"],
            "parent_cpu_core_hours": window["cpu_core_hours"],
            "parent_gpu_seconds": window["new_limits"]["gpu_seconds"],
            "parent_cpu_core_seconds": window["new_limits"]["cpu_core_seconds"],
            "qualification_attempts": window["new_limits"]["qualification_attempts"],
            "production_attempts": window["new_limits"]["production_attempts"],
            "new_storage_bytes": window["new_limits"]["new_storage_bytes"],
            "deadline_utc": window["deadline_utc"],
        },
        "lease_policy": {
            "profile": "root_live_all_idle_uuid_leased_eight_solver_v2",
            "active_leases_protected": True,
            "selection": "Root must select an idle UUID at actual launch; fresh068 pins no UUID and changes no live lease.",
            "foreign_gpu_processes_excluded": True,
        },
        "source_window": {
            "path": str(WINDOW_PATH),
            "sha256": digest(WINDOW_PATH),
            "at_utc": window["at_utc"],
            "deadline_utc": window["deadline_utc"],
        },
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "actual_gpu_started_by_policy_fixture": policy["gpu_started"],
    }


def build_request(source: dict, source_path: Path) -> dict:
    case_id = source["case_id"]
    derived = deepcopy(source)
    source_attempt = source["attempt_id"]
    derived_attempt = source_attempt + "-wall14400"
    derived["attempt_id"] = derived_attempt
    derived["max_wall_seconds"] = 14_400
    # A source handoff must not be accidentally launchable.  Root can rederive
    # an approved live request later after reviewing actual resource state.
    derived["launch_allowed"] = False
    derived["execution_allowed"] = False
    derived["fresh068_lineage"] = {
        "schema": "ds02.f3.fresh068-walltime-lineage.v1",
        "source_request_path": str(source_path),
        "source_request_sha256": digest(source_path),
        "source_attempt_id": source_attempt,
        "source_max_wall_seconds": source["max_wall_seconds"],
        "derived_attempt_id": derived_attempt,
        "derived_max_wall_seconds": 14_400,
        "walltime_extension_only": True,
        "physical_condition_sha256": source["physical_condition_sha256"],
        "solver_command_unchanged": True,
        "solver_cwd_unchanged": True,
        "xml_bi4_forcing_inputs_unchanged": True,
        "tmax_tout_and_saved_frames_unchanged": True,
        "resource_policy_inherited": {
            "root_solver_concurrency_cap": source["root_solver_concurrency_cap"],
            "root_gpu_selection_profile": source["root_gpu_selection_profile"],
            "root_effective_reservation_function_sha256": source["root_effective_reservation_function_sha256"],
            "estimated_storage_bytes": source["estimated_storage_bytes"],
            "cpu_threads": source["cpu_threads"],
            "estimated_peak_gpu_mib": source["estimated_peak_gpu_mib"],
        },
        "active_root134_requests_untouched": True,
        "future_execution_receipt_sha256": None,
        "future_native_receipt_sha256": None,
        "future_visual_decision_sha256": None,
        "actual_consumed_status_observation": observe_attempt(case_id, source_attempt),
    }
    return derived


def validate_pair(source: dict, derived: dict, source_path: Path, derived_path: Path) -> list[str]:
    errors: list[str] = []
    if set(derived) != set(source) | {"fresh068_lineage"}:
        errors.append(f"{derived_path.name}: top-level key set changed beyond fresh068_lineage")
    for key in source:
        if key not in ALLOWED_DERIVED_FIELDS and derived.get(key) != source[key]:
            errors.append(f"{derived_path.name}: unexpected source-field change: {key}")
    if derived.get("attempt_id") != source["attempt_id"] + "-wall14400":
        errors.append(f"{derived_path.name}: attempt identity is not the wall14400 child")
    if derived.get("max_wall_seconds") != 14_400:
        errors.append(f"{derived_path.name}: max_wall_seconds is not 14400")
    if derived.get("launch_allowed") is not False or derived.get("execution_allowed") is not False:
        errors.append(f"{derived_path.name}: derived request is launchable")
    lineage = derived.get("fresh068_lineage", {})
    if lineage.get("source_request_path") != str(source_path):
        errors.append(f"{derived_path.name}: source path lineage mismatch")
    if lineage.get("source_request_sha256") != digest(source_path):
        errors.append(f"{derived_path.name}: source SHA lineage mismatch")
    if lineage.get("future_execution_receipt_sha256") is not None:
        errors.append(f"{derived_path.name}: future execution receipt is fabricated")
    if lineage.get("future_native_receipt_sha256") is not None:
        errors.append(f"{derived_path.name}: future native receipt is fabricated")
    if lineage.get("future_visual_decision_sha256") is not None:
        errors.append(f"{derived_path.name}: future visual decision is fabricated")
    if derived.get("root_solver_concurrency_cap") != 8:
        errors.append(f"{derived_path.name}: Root134 cap8 policy was not inherited")
    if derived.get("root_gpu_selection_profile") != "root_live_all_idle_uuid_leased_eight_solver_v2":
        errors.append(f"{derived_path.name}: live UUID lease policy changed")
    if derived.get("command") != derived.get("actual_solver_command"):
        errors.append(f"{derived_path.name}: command/actual_solver_command diverged")
    if derived.get("max_wall_seconds") == source.get("max_wall_seconds"):
        errors.append(f"{derived_path.name}: no wall-time extension")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="write derived requests and metadata")
    mode.add_argument("--check", action="store_true", help="check existing package without writing")
    args = parser.parse_args()

    if not SOURCE_DIR.is_dir():
        print(f"missing Root134 source directory: {SOURCE_DIR}", file=sys.stderr)
        return 2
    source_rows = []
    errors: list[str] = []
    for ay in CASES:
        name = f"F3_STAGE1_DP006_P1000_AY{ay}.json"
        source_path = SOURCE_DIR / name
        derived_path = REQUEST_DIR / name
        if not source_path.is_file():
            errors.append(f"missing source request: {source_path}")
            continue
        source = load_json(source_path)
        derived = build_request(source, source_path)
        source_rows.append({
            "case_id": source["case_id"],
            "source_attempt_id": source["attempt_id"],
            "derived_attempt_id": derived["attempt_id"],
            "physical_condition_sha256": source["physical_condition_sha256"],
            "source_request_path": str(source_path),
            "source_request_sha256": digest(source_path),
            "source_max_wall_seconds": source["max_wall_seconds"],
            "derived_max_wall_seconds": derived["max_wall_seconds"],
            "actual_consumed_status_observation": derived["fresh068_lineage"]["actual_consumed_status_observation"],
        })
        if args.write:
            dump_json(derived_path, derived)
        elif not derived_path.is_file():
            errors.append(f"missing derived request: {derived_path}")
        else:
            existing = load_json(derived_path)
            errors.extend(validate_pair(source, existing, source_path, derived_path))
    if args.write:
        dump_json(HERE / "source-lineage.json", {
            "schema": "ds02.f3.fresh068-source-lineage.v1",
            "fresh_id": "fresh068",
            "family_id": "F3",
            "source_policy": "Root134 requests are read-only inputs; their bytes are never rewritten.",
            "cases": source_rows,
            "derived_requests_disabled": True,
            "independent_case_count_increment": 0,
            "physical_conditions_changed": False,
            "actual_native_receipts_created": False,
        })
        dump_json(HERE / "policy-lineage.json", policy_lineage())
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"fresh068 {'written' if args.write else 'checked'}: {len(source_rows)} disabled wall-time derivatives")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
