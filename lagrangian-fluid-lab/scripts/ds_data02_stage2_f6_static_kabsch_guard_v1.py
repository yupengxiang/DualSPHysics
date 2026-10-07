#!/usr/bin/env python3
"""Prepare and validate the two-case F6 static-MK/Kabsch join guard.

The static per-MK worker owns the two complete H5 pre/post hashes.  This
guard never opens H5 and never hashes it again.  It binds the static request's
declared H5 paths/digests to the existing F6 sentinel solver receipts and
then, after root runs the separate workers, checks that the static result and
the direct-particle Kabsch result refer to the same two CURRENT cases.  The
Kabsch result must be produced from a JSON particle snapshot and the exact
bound solver receipt; a future snapshot containing an H5 path is rejected.

``prepare`` is metadata-only and creates the source-bound bundle plus a
root-owned validation request.  ``validate`` consumes only completed small
JSON outputs from those workers.  No H5, solver, CFD, or model is opened or
run by this script.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
STATIC_REQUEST_DEFAULT = Path(__file__).resolve().parents[1] / "campaigns/ds-data-02/stage2/requests/static-per-mk-h5-audit-f6-sentinels-v2.json"
RIGID_BINDING_DEFAULT = Path(__file__).resolve().parents[1] / "campaigns/ds-data-02/stage2/requests/f6-rigid-observation-v1/f6-rigid-observation-binding.json"
EXPECTED = {
    "F6-S1": "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S095_DP025",
    "F6-S2": "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S200_DP025",
}
EXPECTED_IDS = tuple(EXPECTED.values())


class GuardError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise GuardError(f"{label} is missing: {path}")
    return path


def read_json(value: str | Path, label: str) -> tuple[Path, dict[str, Any]]:
    path = require_file(value, label)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GuardError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise GuardError(f"{label} is not an object: {path}")
    return path, payload


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _path_digest(path: str, expected: str, label: str) -> dict[str, Any]:
    value = require_file(path, label)
    actual = sha256(value)
    if actual != expected:
        raise GuardError(f"{label} digest differs from binding: {value}")
    return {"path": str(value), "sha256": actual, "bytes": value.stat().st_size}


def _small_binding(binding_row: dict[str, Any], field: str, label: str) -> dict[str, Any]:
    path = str(binding_row.get(field, ""))
    digest = str(binding_row.get(f"{field[:-5]}sha256", "")) if field.endswith("_path") else ""
    # The existing binding uses <name>_path/<name>_sha256 pairs.  Keep the
    # lookup explicit so an accidental alternate run cannot be accepted.
    if field == "floating_csv_path":
        digest = str(binding_row.get("floating_csv_sha256", ""))
    elif field == "floating_report_path":
        digest = str(binding_row.get("floating_report_sha256", ""))
    elif field == "generated_xml_path":
        digest = str(binding_row.get("generated_xml_sha256", ""))
    elif field == "partfloatinfo_path":
        digest = str(binding_row.get("partfloatinfo_sha256", ""))
    elif field == "runout_path":
        digest = str(binding_row.get("runout_sha256", ""))
    elif field == "runparts_path":
        digest = str(binding_row.get("runparts_sha256", ""))
    elif field == "solver_receipt_path":
        digest = str(binding_row.get("solver_receipt_sha256", ""))
    if len(digest) != 64:
        raise GuardError(f"{label} has no 64-hex digest")
    return _path_digest(path, digest, label)


def prepare(static_request_path: Path, rigid_binding_path: Path, output_manifest: Path, output_request: Path) -> dict[str, Any]:
    static_path, static = read_json(static_request_path, "F6 static request")
    binding_path, binding = read_json(rigid_binding_path, "F6 rigid binding")
    if static.get("case_id") != "STAGE2_STATIC_PER_MK_H5_AUDIT_F6_SENTINELS" or static.get("attempt_id") != "static-per-mk-h5-audit-f6-sentinels-v2":
        raise GuardError("static input is not the existing two-sentinel v2 request")
    if binding.get("schema") != "ds02.stage2.f6-rigid-observation-binding.v1":
        raise GuardError("rigid input is not the registered v1 binding")
    sentinels = binding.get("sentinels")
    if not isinstance(sentinels, dict) or set(sentinels) != {"F6-S1", "F6-S2"}:
        raise GuardError("rigid binding must contain exactly F6-S1/F6-S2")
    static_ids = static.get("source_binding", {}).get("case_ids", [])
    if not static_ids:
        command = static.get("command", [])
        static_ids = [str(command[index + 1]) for index, value in enumerate(command[:-1])
                      if value == "--case-id"]
    if tuple(static_ids) != EXPECTED_IDS:
        raise GuardError(f"static request selected IDs {static_ids!r}, expected {EXPECTED_IDS!r}")
    static_digest_map = static.get("input_sha256", {})
    source_cases = []
    for sentinel_id in ("F6-S1", "F6-S2"):
        row = sentinels[sentinel_id]
        if row.get("physical_case_id") != EXPECTED[sentinel_id]:
            raise GuardError(f"{sentinel_id} physical identity differs")
        # All small binding files are verified now.  The H5s are represented
        # only by the existing static request declaration; this preparation
        # deliberately never opens or hashes them.
        small = {
            key: _small_binding(row, key, f"{sentinel_id} {key}")
            for key in ("solver_receipt_path", "generated_xml_path", "runparts_path", "runout_path", "floating_csv_path", "floating_report_path", "partfloatinfo_path")
        }
        receipt_payload = json.loads(Path(small["solver_receipt_path"]["path"]).read_text(encoding="utf-8"))
        if (receipt_payload.get("schema") != "ds02.execution-receipt.v1"
                or receipt_payload.get("status") != "completed"
                or receipt_payload.get("returncode") != 0):
            raise GuardError(f"{sentinel_id} solver receipt is not completed code 0")
        receipt_request = receipt_payload.get("request", {})
        if receipt_request.get("family_id") != "F6" or receipt_request.get("physical_case_id") != EXPECTED[sentinel_id]:
            raise GuardError(f"{sentinel_id} solver receipt physical identity differs")
        trajectory_path = next((str(path) for path in static.get("input_files", []) if str(path).endswith(f"/{EXPECTED[sentinel_id]}/trajectory.h5")), "")
        if not trajectory_path:
            # Existing static request names the file directly; fall back to
            # the selected row in its source identity if a future generator
            # changes the input ordering.
            trajectory_path = next((str(path) for path in static.get("input_files", []) if str(path).lower().endswith("trajectory.h5") and EXPECTED[sentinel_id] in str(path)), "")
        if not trajectory_path:
            raise GuardError(f"{sentinel_id} H5 input is absent from static request")
        trajectory_sha = static_digest_map.get(trajectory_path)
        if not isinstance(trajectory_sha, str) or len(trajectory_sha) != 64:
            raise GuardError(f"{sentinel_id} H5 digest declaration is absent")
        declared_bytes = int(static.get("source_read_cost", {}).get("trajectory_h5_bytes", {}).get(EXPECTED[sentinel_id], -1))
        if declared_bytes <= 0:
            raise GuardError(f"{sentinel_id} H5 byte declaration is absent")
        source_cases.append({
            "sentinel_id": sentinel_id,
            "physical_case_id": EXPECTED[sentinel_id],
            "solver_receipt": small["solver_receipt_path"],
            "small_source_bindings": small,
            "trajectory_h5": {"path": trajectory_path, "sha256": trajectory_sha, "bytes": declared_bytes, "digest_owner": "static-per-mk-h5-audit-f6-sentinels-v2"},
        })
    total_h5 = sum(int(row["trajectory_h5"]["bytes"]) for row in source_cases)
    bundle = {
        "schema": "ds02.stage2.f6-static-kabsch-guard-bundle.v1",
        "status": "PREPARED_SOURCE_BOUND_NO_H5",
        "selected_case_ids": list(EXPECTED_IDS),
        "static_request": {"path": str(static_path), "sha256": sha256(static_path), "attempt_id": static["attempt_id"]},
        "rigid_binding": {"path": str(binding_path), "sha256": sha256(binding_path), "schema": binding["schema"]},
        "source_cases": source_cases,
        "hash_ownership": {
            "h5_hash_owner": static["attempt_id"],
            "parent_pre_hash_bytes": total_h5,
            "parent_post_hash_bytes": total_h5,
            "parent_pre_post_hash_bytes": total_h5 * 2,
            "kabsch_h5_opened": False,
            "kabsch_duplicate_h5_hash_forbidden": True,
            "guard_h5_opened": False,
            "guard_h5_rehash_performed": False,
        },
        "kabsch_contract": {
            "script_schema": "ds02.stage2.f6-rigid-observation.v3",
            "input_snapshot_schema": "ds02.stage2.f6-rigid-particle-snapshots.v1",
            "orientation_source": "direct proper Kabsch from identical (Zone,Idp) positions",
            "snapshot_must_bind_exact_solver_receipt": True,
            "snapshot_must_not_reference_h5": True,
            "so3_tolerances_deg": {"rmse": 2.0, "max": 5.0},
            "body_mass_kg": 128.0,
            "support_sample_mass_kg": 256.0,
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
        },
        "preparation_policy": {"h5_opened": False, "solver_started": False, "kabsch_started": False, "static_worker_started": False},
    }
    atomic_json(output_manifest, bundle)
    manifest_sha = sha256(output_manifest)
    input_files = [SCRIPT, VENV, static_path, binding_path, Path(static["command"][1]), Path("/home/jade/.codex/worktrees/ds-data-02-stage2-forensics/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_stage2_f6_rigid_observation_v3.py")]
    for row in source_cases:
        input_files.extend(Path(item["path"]) for item in row["small_source_bindings"].values())
    unique = list(dict.fromkeys(str(Path(path).expanduser().resolve()) for path in input_files))
    digests = {path: sha256(Path(path)) for path in unique}
    request = {
        "schema": "ds02.request.v1",
        "family_id": "F6",
        "case_id": "STAGE2_F6_STATIC_KABSCH_SOURCE_GUARD_V1",
        "attempt_id": "f6-static-kabsch-source-guard-v1",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 300,
        "estimated_storage_bytes": 16 * 1024 * 1024,
        "cwd": str(SCRIPT.parent),
        "worktree_root": str(SCRIPT.parents[2]),
        "command": [str(VENV), str(SCRIPT), "validate", "--manifest", str(output_manifest.resolve()), "--static-output", "{attempt_root}/static-per-mk-h5-f6-sentinels.json", "--rigid-output", "{attempt_root}/f6-rigid-observation-F6-S1.json", "--rigid-output", "{attempt_root}/f6-rigid-observation-F6-S2.json", "--output", "{attempt_root}/f6-static-kabsch-guard.json"],
        "input_files": sorted(set(unique + [str(output_manifest.resolve())])),
        "input_sha256": {**digests, str(output_manifest.resolve()): manifest_sha},
        "source_policy": {
            "h5_read_by_guard": False,
            "h5_hash_by_guard": False,
            "h5_hash_owner": static["attempt_id"],
            "static_and_kabsch_same_h5_hash": False,
            "kabsch_source": "JSON snapshot only; no H5 path accepted",
        },
        "source_cases": [{"sentinel_id": row["sentinel_id"], "physical_case_id": row["physical_case_id"], "trajectory_h5_path": row["trajectory_h5"]["path"], "trajectory_h5_sha256": row["trajectory_h5"]["sha256"], "trajectory_h5_bytes": row["trajectory_h5"]["bytes"]} for row in source_cases],
        "canonical_ready": True,
        "launch_owner": "root",
        "primary_launch_owner": "root",
        "launch": True,
        "launch_allowed": True,
        "execution_allowed": True,
        "foreign_process_protection_required": True,
        "shared_lease_required": True,
        "physical_fate": "UNKNOWN",
        "dynamical_impact": "UNKNOWN",
        "QN": "NOT_ASSESSED",
        "QE": "NOT_ASSESSED",
        "request_note": "Final small-output join guard only. Existing static request owns the two H5 pre/post hashes; this guard and Kabsch never open or hash H5.",
    }
    atomic_json(output_request, request)
    return {"bundle": str(output_manifest.resolve()), "bundle_sha256": manifest_sha, "request": str(output_request.resolve()), "request_sha256": sha256(output_request), "h5_pre_post_hash_bytes": total_h5 * 2}


def validate(manifest_path: Path, static_output: Path, rigid_outputs: list[Path], output: Path) -> dict[str, Any]:
    manifest_path, bundle = read_json(manifest_path, "F6 static/Kabsch bundle")
    if bundle.get("schema") != "ds02.stage2.f6-static-kabsch-guard-bundle.v1":
        raise GuardError("unexpected bundle schema")
    if bundle.get("hash_ownership", {}).get("kabsch_h5_opened") is not False or bundle.get("hash_ownership", {}).get("kabsch_duplicate_h5_hash_forbidden") is not True:
        raise GuardError("bundle H5 ownership contract is not strict")
    static_path, static = read_json(static_output, "static per-MK output")
    if static.get("schema") != "ds02.stage2.static-per-mk-h5-audit.v2":
        raise GuardError("static output schema differs")
    static_ids = static.get("scope", {}).get("selected_case_ids", [])
    if tuple(static_ids) != EXPECTED_IDS:
        raise GuardError("static output selected IDs differ")
    by_id = {str(row.get("physical_case_id")): row for row in static.get("rows", []) if isinstance(row, dict)}
    if set(by_id) != set(EXPECTED_IDS):
        raise GuardError("static output rows do not cover exactly the two F6 sentinels")
    static_checks = []
    source_by_id = {row["physical_case_id"]: row for row in bundle["source_cases"]}
    for physical_id in EXPECTED_IDS:
        row = by_id[physical_id]
        trajectory = row.get("trajectory", {})
        bound = source_by_id[physical_id]["trajectory_h5"]
        if str(trajectory.get("path")) != str(Path(bound["path"]).resolve()):
            raise GuardError(f"static trajectory path differs for {physical_id}")
        if trajectory.get("declared_sha256") != bound["sha256"] or int(trajectory.get("declared_bytes", -1)) != int(bound["bytes"]):
            raise GuardError(f"static trajectory binding differs for {physical_id}")
        static_checks.append({"physical_case_id": physical_id, "h5_rehash_by_guard": False, "static_output": str(static_path)})
    if len(rigid_outputs) != 2:
        raise GuardError("exactly two rigid Kabsch outputs are required")
    rigid_checks = []
    seen_ids = set()
    for path in rigid_outputs:
        _path, result = read_json(path, "rigid Kabsch output")
        if result.get("schema") != "ds02.stage2.f6-rigid-observation.v3" or result.get("status") != "completed":
            raise GuardError(f"rigid output is not a completed v3 result: {path}")
        physical_id = str(result.get("physical_case_id", ""))
        if physical_id not in EXPECTED_IDS or physical_id in seen_ids:
            raise GuardError(f"rigid output identity is not one unique sentinel: {path}")
        seen_ids.add(physical_id)
        source = result.get("source", {})
        if source.get("solver_receipt", {}).get("sha256") != source_by_id[physical_id]["solver_receipt"]["sha256"]:
            raise GuardError(f"rigid solver receipt binding differs for {physical_id}")
        bound_small = source_by_id[physical_id]["small_source_bindings"]
        floating = source.get("floating_csv", {})
        if floating.get("path") != bound_small["floating_csv_path"]["path"] or floating.get("sha256") != bound_small["floating_csv_path"]["sha256"]:
            raise GuardError(f"rigid FloatingInfo binding differs for {physical_id}")
        snapshot_path = str(source.get("snapshot_json", {}).get("path", ""))
        if snapshot_path.lower().endswith((".h5", ".hdf5")) or not snapshot_path:
            raise GuardError(f"rigid snapshot source is H5 or absent for {physical_id}")
        contract = result.get("frozen_contract", {})
        tolerances = contract.get("so3_error_tolerances_deg", {})
        if float(tolerances.get("rmse", -1)) != 2.0 or float(tolerances.get("max", -1)) != 5.0:
            raise GuardError(f"rigid SO3 tolerance contract differs for {physical_id}")
        if float(contract.get("body_mass_kg", -1)) != 128.0 or float(contract.get("support_sample_mass_kg", -1)) != 256.0:
            raise GuardError(f"rigid body/support mass separation differs for {physical_id}")
        rigid_checks.append({"physical_case_id": physical_id, "output": str(path.resolve()), "h5_opened": False})
    if seen_ids != set(EXPECTED_IDS):
        raise GuardError("rigid outputs do not cover both sentinels")
    result = {
        "schema": "ds02.stage2.f6-static-kabsch-guard.v1",
        "status": "completed",
        "bundle": {"path": str(manifest_path), "sha256": sha256(manifest_path)},
        "static_checks": static_checks,
        "rigid_checks": rigid_checks,
        "hash_ownership": bundle["hash_ownership"],
        "source_policy": {"h5_opened": False, "h5_rehashed": False, "solver_started": False, "cfd_or_model_run": False},
        "qualification": {"physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED"},
    }
    atomic_json(output, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--static-request", type=Path, default=STATIC_REQUEST_DEFAULT)
    prep.add_argument("--rigid-binding", type=Path, default=RIGID_BINDING_DEFAULT)
    prep.add_argument("--output-manifest", type=Path, required=True)
    prep.add_argument("--output-request", type=Path, required=True)
    check = sub.add_parser("validate")
    check.add_argument("--manifest", type=Path, required=True)
    check.add_argument("--static-output", type=Path, required=True)
    check.add_argument("--rigid-output", type=Path, action="append", required=True)
    check.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            result = prepare(args.static_request, args.rigid_binding, args.output_manifest, args.output_request)
        else:
            result = validate(args.manifest, args.static_output, args.rigid_output, args.output)
    except GuardError as exc:
        raise SystemExit(f"GuardError: {exc}")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
