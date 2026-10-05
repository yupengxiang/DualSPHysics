#!/usr/bin/env python3
"""Validate fresh105's disabled runtime contracts without science-payload I/O."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any


PKG = Path(__file__).resolve().parents[1]
CASE = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
COUNTS = {"total": 194427, "fixed": 158559, "moving": 4210, "floating": 0, "fluid": 31658}
HEX = set("0123456789abcdefABCDEF")
SCIENCE_SUFFIXES = {".bi4", ".csv", ".h5", ".hdf5", ".vtk", ".vtu", ".npy", ".npz", ".dat"}
SOURCE_SUFFIXES = {".json", ".py", ".xml", ".md", ".txt", ".log"}
PRODUCER_ONLY = {
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python": "a2f33a6e006989270f4340528eb61f8f97366e00a5d1b602ac8672ea44fc56ae",
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump": "b8ac8cf4aff68ffd089da6cf3ef19dfd0c6473121475f4c198b720a0ddaa8b2e",
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64": "62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load_json(path: Path) -> tuple[dict[str, Any], str]:
    require(path.suffix.lower() == ".json" and path.is_file(), f"JSON metadata missing: {path}")
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value, hashlib.sha256(raw).hexdigest()


def sha_source(path: Path) -> str:
    require(path.suffix.lower() in SOURCE_SUFFIXES, f"source validator refuses payload digest: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_request_input_closure(request: dict[str, Any], label: str) -> dict[str, int]:
    files = request.get("input_files")
    hashes = request.get("input_sha256")
    require(isinstance(files, list) and isinstance(hashes, dict), f"{label}: input closure shape")
    checked = 0
    placeholders = 0
    producer_only = 0
    for raw in files:
        text = str(raw)
        if text.startswith("<root-bind:"):
            placeholders += 1
            require(text in hashes and hashes[text] is None, f"{label}: placeholder hash must remain null: {text}")
            continue
        path = Path(text)
        require(path.suffix.lower() not in SCIENCE_SUFFIXES, f"{label}: science payload listed in source input closure: {path}")
        require(text in hashes, f"{label}: missing input hash: {path}")
        declared = hashes[text]
        if text in PRODUCER_ONLY:
            require(declared == PRODUCER_ONLY[text], f"{label}: producer-only tool hash mismatch: {path}")
            producer_only += 1
            continue
        require(isinstance(declared, str) and len(declared) == 64 and set(declared) <= HEX, f"{label}: invalid input SHA: {path}")
        require(path.is_file(), f"{label}: static input missing: {path}")
        require(path.suffix.lower() in SOURCE_SUFFIXES, f"{label}: non-source input cannot be hashed by validator: {path}")
        require(sha_source(path) == declared, f"{label}: static input SHA mismatch: {path}")
        checked += 1
    return {"static_source_inputs_hashed": checked, "producer_only_tools": producer_only, "root_bind_placeholders": placeholders}


def check_disabled_request(path: Path, expected_kind: str, expected_task: str) -> dict[str, Any]:
    request, request_sha = load_json(path)
    label = path.name
    require(request.get("schema") == "ds02.runner-request.v2", f"{label}: schema")
    require(request.get("kind") == expected_kind and request.get("cpu_task_kind") == expected_task, f"{label}: kind/task")
    for key in ("disabled", "launch", "launch_allowed", "execution_allowed", "solver_allowed"):
        require(request.get(key) is False if key != "disabled" else request.get(key) is True, f"{label}: unsafe {key}")
    require(request.get("source_only") is True and request.get("shared_registry_write_allowed") is False, f"{label}: source/shared boundary")
    require(request.get("case_id") == CASE, f"{label}: case")
    require(request.get("expected_frames") == 51 and request.get("expected_dimension") == 3, f"{label}: frame/dimension")
    for key, count_key in (("expected_particles", "total"), ("expected_fixed_particles", "fixed"), ("expected_moving_particles", "moving"), ("expected_floating_particles", "floating"), ("expected_fluid_particles", "fluid")):
        require(request.get(key) == COUNTS[count_key], f"{label}: {key}")
    future = request.get("future_output_hashes")
    require(isinstance(future, dict) and all(value is None for value in future.values()), f"{label}: future output hash is not null")
    require(request.get("full801_authorized") is False and request.get("q_n_granted") is False, f"{label}: acceptance boundary")
    closure = check_request_input_closure(request, label)
    return {"request_sha256": request_sha, **closure}


def check_actual_native(att_path: Path, candidate: str) -> dict[str, Any]:
    att, att_sha = load_json(att_path)
    require(att.get("schema") == "ds02.f5.c082s1.root455-native-attestation.fresh105.v1", f"{candidate}: attestation schema")
    require(att.get("actual_counts") == {**COUNTS, "dimension": 3}, f"{candidate}: attestation counts")
    receipt_path = Path(att["actual_receipt"]["actual_receipt_path"])
    receipt, receipt_sha = load_json(receipt_path)
    require(receipt_sha == att["actual_receipt"]["actual_receipt_sha256"], f"{candidate}: actual receipt JSON SHA")
    require(receipt.get("status") == "completed" and int(receipt.get("returncode", -1)) == 0, f"{candidate}: actual receipt status")
    req = receipt.get("request")
    require(isinstance(req, dict) and req.get("case_id") == CASE and req.get("expected_frames") == 51 and req.get("expected_dimension") == 3, f"{candidate}: nested actual request")
    require(req.get("actual_counts") == {**COUNTS, "dimension": 3}, f"{candidate}: nested actual counts")
    require(att.get("full801_authorized") is False and att.get("q_n_granted") is False, f"{candidate}: attestation acceptance")
    return {"attestation_sha256": att_sha, "receipt_sha256": receipt_sha, "attempt_id": att["actual_receipt"]["identity"]["attempt_id"] if "identity" in att["actual_receipt"] else req.get("attempt_id")}


def check_worker_sources() -> dict[str, str]:
    paths = {
        "typed_converter": Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_nvme_convert_v1.py"),
        "direct_converter": Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_direct_convert.py"),
        "typed_binder": PKG / "scripts/bind_downstream_products.py",
        "bed_worker": PKG / "workers/bed_audit.py",
        "xmf_worker": PKG / "workers/export_xmf_legacy_aware.py",
    }
    for name, path in paths.items():
        require(path.is_file(), f"missing worker/source: {name} {path}")
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    direct = paths["direct_converter"].read_text(encoding="utf-8")
    nvme = paths["typed_converter"].read_text(encoding="utf-8")
    xmf = paths["xmf_worker"].read_text(encoding="utf-8")
    bed = paths["bed_worker"].read_text(encoding="utf-8")
    for token in ("_physical_condition_scope", "canonical_hash"):
        require(token in direct, f"direct converter missing semantic scope token: {token}")
    require("conversion-report.json" in nvme or "conversion_report" in nvme, "NVME converter report contract missing")
    require("--binding" in xmf and "--output-dir" in xmf and "source_h5_physical_condition_sha256" in xmf, "legacy-aware XMF CLI/legacy scope contract missing")
    for token in ("--binding", "--trajectory-h5", "--xdmf", "--output-dir", "thresholds_are_diagnostic_only", "native_bed_mk"):
        require(token in bed, f"bed worker contract missing: {token}")
    return {name: sha_source(path) for name, path in paths.items()}


def write_manifest() -> None:
    files: dict[str, str] = {}
    for path in sorted(PKG.rglob("*")):
        if not path.is_file() or path.name == "manifest.json":
            continue
        require(path.suffix.lower() not in SCIENCE_SUFFIXES, f"science payload entered fresh105 package: {path}")
        require(path.suffix.lower() in SOURCE_SUFFIXES, f"unexpected non-source package file: {path}")
        files[str(path.relative_to(PKG))] = sha_source(path)
    manifest = {
        "schema": "ds02.f5.c082s1.fresh105-source-manifest.v1",
        "status": "source_only_root455_native_bound_downstream_disabled",
        "package": str(PKG),
        "files": files,
        "candidates": ["A080", "A120"],
        "actual_root455_native_receipts_bound": True,
        "typed_xmf_bed_future_products": None,
        "full801_authorized": False,
        "q_n_granted": False,
        "independent_case_count_increment": 0,
        "science_payloads_read_or_hashed_by_manifest": False,
        "jobs_started": False,
        "shared_state_modified": False,
    }
    (PKG / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    results: dict[str, Any] = {"candidates": {}, "worker_sources": check_worker_sources()}
    for candidate in ("A080", "A120"):
        results["candidates"][candidate] = {
            "native": check_actual_native(PKG / "metadata" / f"{candidate}-root455-native-attestation.json", candidate),
            "typed_request": check_disabled_request(PKG / "requests" / f"{candidate}-typed-nvme-request.json", "cpu", "conversion"),
            "xmf_request": check_disabled_request(PKG / "requests" / f"{candidate}-xmf-request.json", "cpu", "xmf_export"),
            "bed_request": check_disabled_request(PKG / "requests" / f"{candidate}-bed-audit-request.json", "cpu", "audit"),
        }
    report = {
        "schema": "ds02.f5.c082s1.fresh105-source-validator-report.v1",
        "status": "passed_metadata_and_disabled_downstream_contract",
        "candidates": results["candidates"],
        "worker_sources": results["worker_sources"],
        "actual_root455_native_receipts_verified": True,
        "actual_native_counts": {**COUNTS, "dimension": 3},
        "typed_xmf_bed_requests_remain_disabled": True,
        "all_future_product_hashes_null": True,
        "root_must_verify_51_saved_native_frames_before_typed": True,
        "first_state_zero_velocity_qa_pending": True,
        "exact_dp_lattice_threshold": 1e-6,
        "exact_dp_lattice_negative_retained_and_not_relaxed": True,
        "full801_authorized": False,
        "q_n_granted": False,
        "independent_case_count_increment": 0,
        "science_payloads_read_or_hashed_by_validator": False,
        "jobs_started": False,
        "shared_state_modified": False,
        "source_only": True,
    }
    out = PKG / "metadata" / "fresh105-validator-report.json"
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_manifest()
    print(json.dumps({"status": report["status"], "candidates": ["A080", "A120"], "science_payloads_read_or_hashed_by_validator": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
