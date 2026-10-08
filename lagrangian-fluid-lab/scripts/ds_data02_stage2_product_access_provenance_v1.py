#!/usr/bin/env python3
"""Build a small, source-bound dependency/license/access sidecar.

The sidecar joins the completed v28 delivery metadata and v30 task-scope
catalog with the repository and solver license files and the exact Python
environment used by this worker.  It is deliberately a forward provenance
record: it hashes metadata and license files, but does not copy license text,
open scientific payloads, or make a redistribution determination.

The consumer entries point at the existing v28 loader and JSON product fields;
this module does not create a second scientific data framework.  QN/QE/QI,
physical fate, dynamics, and external redistribution remain UNKNOWN.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as metadata
import json
import platform
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
V28_SCHEMA = "ds02.stage2.product-delivery-metadata.v28"
V30_SCHEMA = "ds02.stage2.task-scope-catalog.v30"
SIDEcar_SCHEMA = "ds02.stage2.product-access-provenance.v1"
REQUEST_SCHEMA = "ds02.stage2.product-access-provenance-request.v1"
FORBIDDEN_SUFFIXES = {".h5", ".hdf5", ".bi4", ".bi2", ".bi1"}
PIN_RE = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[[^]]+\])?\s*(==|~=|>=|<=|!=|>|<)?\s*([^;\s]+)?")


class ProvenanceError(RuntimeError):
    """Raised when a source, environment, or access boundary is incomplete."""


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _path(value: Path | str, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_absolute() or not path.is_file():
        raise ProvenanceError(f"{label} is not an existing absolute file: {path}")
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:
        raise ProvenanceError(f"{label} is a forbidden scientific payload: {path}")
    return path


def _json(value: Path | str, label: str) -> tuple[Path, dict[str, Any]]:
    path = _path(value, label)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProvenanceError(f"{label} is invalid JSON: {path}") from error
    if not isinstance(data, dict):
        raise ProvenanceError(f"{label} must be a JSON object: {path}")
    return path, data


def _ref(path: Path, role: str, *, access: str = "workspace_metadata_read_only") -> dict[str, Any]:
    return {
        "role": role,
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "access": access,
    }


def _git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=SCRIPT.parents[2],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def _require_ref(path: Path, declared: Any, label: str) -> None:
    if not isinstance(declared, str) or declared != sha256_file(path):
        raise ProvenanceError(f"{label} digest differs from the bound source")


def _validate_actual_pair(
    *,
    product_path: Path,
    product: dict[str, Any],
    proof_path: Path,
    proof: dict[str, Any],
    receipt_path: Path,
    receipt: dict[str, Any],
    request_path: Path,
    request: dict[str, Any],
    schema: str,
    label: str,
) -> dict[str, Any]:
    if product.get("schema") != schema:
        raise ProvenanceError(f"{label} product schema is not {schema}")
    if not str(product.get("status", "")).startswith("ACTUAL_"):
        raise ProvenanceError(f"{label} product is not actual")
    policy = product.get("read_policy") or {}
    forbidden_keys = (
        "trajectory_h5_opened",
        "original_trajectory_h5_opened_by_this_worker",
        "materialized_label_h5_opened",
        "materialized_label_h5_opened_by_this_worker",
        "part_bi4_opened",
        "part_bi4_opened_by_this_worker",
        "raw_solver_output_opened",
        "raw_solver_output_opened_by_this_worker",
    )
    forbidden = [key for key in forbidden_keys if policy.get(key) is True]
    if forbidden or policy.get("solver_started") is True or policy.get("model_invoked") is True:
        raise ProvenanceError(f"{label} product has an open scientific read policy: {forbidden}")
    if proof.get("schema") != "ds02.stage2.root-actual-verification.v1" or not str(proof.get("status", "")).startswith("PASS_ACTUAL"):
        raise ProvenanceError(f"{label} proof is not actual")
    if proof.get("H5_BI4_read_by_root") is not False:
        raise ProvenanceError(f"{label} proof does not close H5/BI4 reads")
    report_value = proof.get("report") or proof.get("product") or proof.get("output")
    report_path = report_value.get("path") if isinstance(report_value, dict) else report_value
    report_sha = report_value.get("sha256") if isinstance(report_value, dict) else proof.get("report_sha256") or proof.get("product_sha256")
    if report_path != str(product_path) or report_sha != sha256_file(product_path):
        raise ProvenanceError(f"{label} proof does not bind product exactly")
    if proof.get("receipt") != str(receipt_path) or proof.get("receipt_sha256") != sha256_file(receipt_path):
        raise ProvenanceError(f"{label} proof does not bind receipt exactly")
    if proof.get("request") != str(request_path) or proof.get("request_sha256") != sha256_file(request_path):
        raise ProvenanceError(f"{label} proof does not bind request exactly")
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed" or receipt.get("returncode") not in (None, 0):
        raise ProvenanceError(f"{label} receipt is not completed")
    if receipt.get("request_sha256") not in (None, sha256_file(request_path)):
        raise ProvenanceError(f"{label} receipt request digest differs")
    if request.get("status") != "prepared_guard_pending_actual_CPU" or request.get("launch_allowed") is not True:
        # Actual root requests retain the prepared producer status after launch.
        if request.get("status") not in ("prepared_guard_pending_actual_CPU", "completed"):
            raise ProvenanceError(f"{label} request status is unexpected")
    return {
        "product": _ref(product_path, f"{label} actual product"),
        "proof": _ref(proof_path, f"{label} actual independent proof"),
        "receipt": _ref(receipt_path, f"{label} actual execution receipt"),
        "request": _ref(request_path, f"{label} producer request", access="source_hash_bound_guard_only"),
        "status": product.get("status"),
    }


def _parse_requirements(path: Path) -> list[dict[str, str | None]]:
    entries: list[dict[str, str | None]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("--"):
            continue
        match = PIN_RE.match(line)
        if not match:
            raise ProvenanceError(f"unsupported requirement line in {path}: {line}")
        name, operator, version = match.groups()
        entries.append({"name": name, "operator": operator, "version": version})
    return entries


def _environment(requirements: list[Path], python_executable: Path) -> tuple[dict[str, Any], list[Path]]:
    invocation_path = python_executable.expanduser()
    if not invocation_path.is_absolute() or not invocation_path.is_file():
        raise ProvenanceError(f"Python executable is not an absolute file: {invocation_path}")
    executable = invocation_path.resolve()
    actual_executable = Path(sys.executable).resolve()
    if executable != actual_executable:
        raise ProvenanceError(f"worker interpreter differs: requested {executable}, actual {actual_executable}")
    parsed: list[dict[str, str | None]] = []
    for path in requirements:
        parsed.extend(_parse_requirements(path))
    by_name: dict[str, dict[str, str | None]] = {}
    for item in parsed:
        by_name.setdefault(str(item["name"]).lower(), item)
    packages: list[dict[str, Any]] = []
    metadata_files: list[Path] = []
    for key in sorted(by_name):
        item = by_name[key]
        name = str(item["name"])
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError as error:
            raise ProvenanceError(f"required package is not installed: {name}") from error
        version = dist.version
        operator = item.get("operator")
        required = item.get("version")
        if operator == "==" and required != version:
            raise ProvenanceError(f"environment version mismatch for {name}: {version} != {required}")
        metadata_path = Path(dist._path) / "METADATA"
        metadata_path = _path(metadata_path, f"{name} distribution metadata")
        metadata_files.append(metadata_path)
        classifiers = [value for value in dist.metadata.get_all("Classifier", []) if value.startswith("License ::")]
        packages.append({
            "name": name,
            "required": {"operator": operator, "version": required},
            "actual_version": version,
            "distribution_metadata": _ref(metadata_path, f"{name} distribution metadata"),
            "declared_license_classifiers": classifiers,
            "redistribution": "UNKNOWN_NOT_ESTABLISHED_BY_THIS_SIDECAR",
        })
    return {
        "interpreter": {
            "invocation_path": str(invocation_path),
            "resolved_path": str(executable),
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "sys_version": sys.version,
            "platform": platform.platform(),
            "prefix": sys.prefix,
        },
        "requirements": [_ref(path, "pinned Python requirement file") for path in requirements],
        "packages": packages,
        "redistribution": "UNKNOWN_NOT_ESTABLISHED_BY_THIS_SIDECAR",
    }, metadata_files


def build_provenance(
    *,
    v28_product: Path | str,
    v28_proof: Path | str,
    v28_receipt: Path | str,
    v28_request: Path | str,
    v30_product: Path | str,
    v30_manifest: Path | str,
    v30_proof: Path | str,
    v30_receipt: Path | str,
    v30_request: Path | str,
    repo_license: Path | str,
    solver_license: Path | str,
    requirements: Path | str,
    requirements_ml: Path | str,
    python_executable: Path | str,
    output: Path | str,
) -> dict[str, Any]:
    v28_product, v28 = _json(v28_product, "v28 product")
    v28_proof, v28_proof_data = _json(v28_proof, "v28 proof")
    v28_receipt, v28_receipt_data = _json(v28_receipt, "v28 receipt")
    v28_request, v28_request_data = _json(v28_request, "v28 request")
    v30_product, v30 = _json(v30_product, "v30 product")
    v30_manifest, v30_manifest_data = _json(v30_manifest, "v30 manifest")
    v30_proof, v30_proof_data = _json(v30_proof, "v30 proof")
    v30_receipt, v30_receipt_data = _json(v30_receipt, "v30 receipt")
    v30_request, v30_request_data = _json(v30_request, "v30 request")
    v28_refs = _validate_actual_pair(product_path=v28_product, product=v28, proof_path=v28_proof, proof=v28_proof_data, receipt_path=v28_receipt, receipt=v28_receipt_data, request_path=v28_request, request=v28_request_data, schema=V28_SCHEMA, label="v28")
    v30_refs = _validate_actual_pair(product_path=v30_product, product=v30, proof_path=v30_proof, proof=v30_proof_data, receipt_path=v30_receipt, receipt=v30_receipt_data, request_path=v30_request, request=v30_request_data, schema=V30_SCHEMA, label="v30")
    v30_coverage = v30.get("coverage") or {}
    if v30_coverage.get("current_cases") != 336 or v30_coverage.get("native_motive_id_cases") != 118 or v30_coverage.get("all_qn_qe_qi_unknown") is not True:
        raise ProvenanceError("v30 task-scope coverage or UNKNOWN boundary is incomplete")
    if v30_manifest_data.get("product", {}).get("sha256") != sha256_file(v30_product):
        raise ProvenanceError("v30 manifest does not bind the product")
    repo_license = _path(repo_license, "repository license")
    solver_license = _path(solver_license, "solver license")
    requirements = _path(requirements, "Python requirements")
    requirements_ml = _path(requirements_ml, "ML Python requirements")
    python_executable = Path(python_executable).expanduser()
    if not python_executable.is_absolute() or not python_executable.is_file():
        raise ProvenanceError(f"Python executable is not an absolute file: {python_executable}")
    environment, metadata_files = _environment([requirements, requirements_ml], python_executable)
    license_refs = [
        {**_ref(repo_license, "repository LICENSE"), "license_scope": "repository source", "redistribution": "UNKNOWN_NOT_ESTABLISHED"},
        {**_ref(solver_license, "solver LICENSE"), "license_scope": "solver/source subtree", "redistribution": "UNKNOWN_NOT_ESTABLISHED"},
    ]
    result = {
        "schema": SIDEcar_SCHEMA,
        "status": "ACTUAL_V28_V30_METADATA_PROVENANCE_NO_REDISTRIBUTION_DETERMINATION",
        "producer": {"script_path": str(SCRIPT), "script_sha256": sha256_file(SCRIPT), "git_commit": _git_commit()},
        "source_products": {"v28": v28_refs, "v30": {**v30_refs, "manifest": _ref(v30_manifest, "v30 actual manifest")}},
        "license_inventory": license_refs,
        "python_environment": environment,
        "consumer_entrypoints": {
            "v28_loader": {
                "module": v28_proof_data.get("actual_loader_module"),
                "module_sha256": v28_proof_data.get("actual_loader_module_sha256"),
                "entrypoints": ["load_product_json(path)", "get_family_card(product, family_id)", "get_current_case(product, family_id, current_index)", "single_case_reproduction_contract(product, 'F2')"],
                "supported_scope": ["seven family cards", "exact CURRENT inventory", "F2 index-78 source-anchored contract"],
            },
            "v29_catalog": {
                "entrypoint": "json.load(v29_product)['cases']",
                "supported_scope": ["336 CURRENT/audit rows", "118 native motive/ID and source-visible mass scope", "saved-record brackets"],
                "qualification": "QN/QE/QI/physical fate/dynamics UNKNOWN",
            },
            "v30_task_scope": {
                "entrypoint": "json.load(v30_product)['cases']",
                "supported_scope": ["exact current inventory", "finite field/lifecycle diagnostics where exposed", "118 native motive/ID", "118 saved-record bracket diagnostics", "7 strict quality anchor task scope"],
                "qualification": "QN/QE/QI/physical fate/dynamics/effective split UNKNOWN",
            },
        },
        "access_boundary": {
            "internal_workspace_access": "OBSERVED_READ_ONLY_FOR_BOUND_METADATA_AND_LICENSE_PATHS",
            "scientific_payload_access": "FORBIDDEN_H5_BI4_RAW_SOLVER",
            "external_access": "UNKNOWN_NOT_ESTABLISHED",
            "redistribution": "UNKNOWN_NOT_ESTABLISHED; legal review and artifact policy are outside this sidecar",
            "scientific_qualification": "NONE_ADDED",
        },
        "read_policy": {"metadata_json_opened": True, "license_text_hashed_without_copying": True, "distribution_metadata_opened": True, "trajectory_h5_opened": False, "materialized_label_h5_opened": False, "part_bi4_opened": False, "raw_solver_output_opened": False, "solver_started": False, "model_invoked": False},
    }
    output = Path(output).expanduser().resolve()
    if output.exists():
        raise ProvenanceError(f"refusing to overwrite provenance sidecar: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def make_request(**kwargs: Any) -> dict[str, Any]:
    output = Path(kwargs.pop("output")).expanduser().resolve()
    runtime_root = Path(kwargs.pop("runtime_root")).expanduser().resolve()
    worker_root = Path(kwargs.pop("worker_root")).expanduser().resolve()
    attempt_id = kwargs.pop("attempt_id", "product-access-provenance-v1-forward-001")
    python_executable = Path(kwargs["python_executable"]).expanduser()
    if not python_executable.is_absolute() or not python_executable.is_file():
        raise ProvenanceError(f"Python executable is not an absolute file: {python_executable}")
    # Run the full source/environment validation before registering a request.
    temp_probe = output.parent / (output.name + ".preflight.json")
    kwargs["python_executable"] = python_executable
    result = build_provenance(**kwargs, output=temp_probe)
    temp_probe.unlink()
    worker = worker_root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_product_access_provenance_v1.py"
    runtime_files = [runtime_root / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py", runtime_root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py", runtime_root / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"]
    source_paths = [Path(kwargs[name]).expanduser().resolve() for name in ("v28_product", "v28_proof", "v28_receipt", "v28_request", "v30_product", "v30_manifest", "v30_proof", "v30_receipt", "v30_request", "repo_license", "solver_license", "requirements", "requirements_ml")]
    package_paths = [Path(item["distribution_metadata"]["path"]) for item in result["python_environment"]["packages"]]
    inputs: list[Path] = [worker, *runtime_files, *source_paths, *package_paths]
    unique: list[Path] = []
    seen: set[str] = set()
    for path in inputs:
        path = _path(path, "provenance request input")
        if str(path) not in seen:
            seen.add(str(path)); unique.append(path)
    hashes = {str(path): sha256_file(path) for path in unique}
    command = [str(python_executable), str(worker), "build"]
    for name in ("v28-product", "v28-proof", "v28-receipt", "v28-request", "v30-product", "v30-manifest", "v30-proof", "v30-receipt", "v30-request", "repo-license", "solver-license", "requirements", "requirements-ml"):
        command.extend([f"--{name}", str(kwargs[name.replace("-", "_")])])
    command.extend(["--python-executable", str(python_executable), "--output", "{attempt_root}/product-access-provenance-v1.json"])
    request = {
        "schema": "ds02.runner-request.v1", "request_schema": REQUEST_SCHEMA, "attempt_id": attempt_id, "case_id": "DS02_STAGE2_PRODUCT_ACCESS_PROVENANCE_V1", "family_id": "infra", "dataset_families": [f"F{i}" for i in range(1, 8)], "kind": "cpu", "cpu_task_kind": "metadata_license_access_provenance", "cpu_threads": 1, "max_wall_seconds": 600, "estimated_storage_bytes": 8 * 1024 * 1024, "cwd": str(worker.parent), "worktree_root": str(worker_root), "command": command, "input_files": [str(path) for path in unique], "input_sha256": hashes, "launch_allowed": True, "primary_launch_owner": "root", "status": "prepared_guard_pending_actual_CPU", "source_cost": {"small_json_receipt_proof_license_metadata_bytes_read": sum(path.stat().st_size for path in unique if path.suffix.lower() in {".json", ".txt", ""}), "trajectory_h5_bytes_read": 0, "materialized_label_h5_bytes_read": 0, "part_bi4_bytes_read": 0, "raw_solver_output_bytes_read": 0, "solver_started": False, "cfd_or_model_run": False}, "environment_contract": result["python_environment"], "claim_boundary": result["access_boundary"], "read_policy": result["read_policy"],
    }
    if output.exists():
        raise ProvenanceError(f"refusing to overwrite provenance request: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return request


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("build", "make-request"):
        p = sub.add_parser(name)
        for arg in ("v28-product", "v28-proof", "v28-receipt", "v28-request", "v30-product", "v30-manifest", "v30-proof", "v30-receipt", "v30-request", "repo-license", "solver-license", "requirements", "requirements-ml", "python-executable"):
            p.add_argument(f"--{arg}", type=Path, required=True)
        p.add_argument("--output", type=Path, required=True)
        if name == "make-request":
            p.add_argument("--runtime-root", type=Path, required=True)
            p.add_argument("--worker-root", type=Path, required=True)
            p.add_argument("--attempt-id", default="product-access-provenance-v1-forward-001")
    args = parser.parse_args(argv)
    values = vars(args).copy(); command = values.pop("command")
    if command == "build":
        build_provenance(**values)
    else:
        make_request(**values)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
