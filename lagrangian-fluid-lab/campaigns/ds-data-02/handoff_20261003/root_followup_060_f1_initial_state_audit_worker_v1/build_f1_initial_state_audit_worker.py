#!/usr/bin/env python3
"""Build disabled, digest-bound F1 ECC/DUAL initial-state audit requests.

This builder only reads JSON provenance and hashes already-existing source
files.  It never launches the worker, PartVTK, GenCase, a solver, or any
other subprocess.  Root enables one request only after reviewing the worker
source and the QA031 reader provenance.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


HERE = Path(__file__).resolve().parent
INFRA_LAB = HERE.parents[3]
INTEGRATION_LAB = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/"
    "DualSPHysics/lagrangian-fluid-lab"
)
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1")
PYTHON = Path("/usr/bin/python3.10")
WORKER = HERE / "worker.py"
READER = INTEGRATION_LAB / (
    "campaigns/ds-data-02/handoff_20261003/"
    "root_native_initial_state_tools_001/qa.py"
)
QA_RECEIPT = DATA_ROOT / (
    "F1_STAGE1_SIX_NEW_HEAD_ACTUAL_INITIAL_QA/"
    "root-stage1-six-new-head-actual-native-initial-qa-031/execution-receipt.json"
)
PARTVTK = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/"
    "DualSPHysics_v5.4/bin/linux/PartVTK_linux64"
)
STRICT_DISPATCH = INTEGRATION_LAB / "scripts/ds_data02_strict_dispatch_v1.py"
RUNTIME = INTEGRATION_LAB / "scripts/ds_data02_runtime_v2.py"

CASES = (
    {
        "variant": "ecc",
        "case_id": "F1_STAGE1_ECC_H130_DP010",
        "input_manifest": HERE.parent / "root_followup_058_f1_ecc_production_bindings_v1/F1_ECC_H130_STRICT_CPU_AUDIT_INPUTS.json",
        "request_name": "F1_ECC_H130_STRICT_CPU_AUDIT_REQUEST.json",
        "attempt_id": "root-stage1-f1-ecc-h130-strict-cpu-audit-060-pending",
        "output_root": DATA_ROOT / "F1_STAGE1_ECC_H130_DP010/root-stage1-ecc-h130-strict-cpu-audit-060",
        "audit_schema": "ds02.stage1.f1.ecc.h130-strict-cpu-audit-result.v1",
    },
    {
        "variant": "dual",
        "case_id": "F1_STAGE1_DUAL_H260_DP020",
        "input_manifest": HERE.parent / "root_followup_059_f1_dual_production_bindings_v1/F1_DUAL_H260_STRICT_CPU_AUDIT_INPUTS.json",
        "request_name": "F1_DUAL_H260_STRICT_CPU_AUDIT_REQUEST.json",
        "attempt_id": "root-stage1-f1-dual-h260-strict-cpu-audit-060-pending",
        "output_root": DATA_ROOT / "F1_STAGE1_DUAL_H260_DP020/root-stage1-dual-h260-strict-cpu-audit-060",
        "audit_schema": "ds02.stage1.f1.dual.h260-strict-cpu-audit-result.v1",
    },
)


class BuildError(ValueError):
    """Raised when a frozen source binding is incomplete or changed."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def binding(path: Path, expected: str | None = None) -> dict[str, str]:
    path = path.resolve()
    if not path.is_file():
        raise BuildError(f"required source file is missing: {path}")
    actual = sha256(path)
    if expected is not None and actual != expected:
        raise BuildError(f"source hash mismatch: {path}")
    return {"path": str(path), "sha256": actual}


def load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise BuildError(f"cannot load JSON source: {path}") from error


def save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _unique_paths(paths: list[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.resolve()
        if resolved not in seen:
            result.append(resolved)
            seen.add(resolved)
    return result


def _reader_context() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    reader_binding = binding(READER)
    qa_receipt_binding = binding(QA_RECEIPT)
    partvtk_binding = binding(PARTVTK)
    receipt = load(QA_RECEIPT)
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise BuildError("QA031 execution receipt is not completed")
    request = receipt.get("request")
    if not isinstance(request, Mapping) or request.get("cpu_task_kind") != "audit":
        raise BuildError("QA031 receipt is not an audit request")
    command = request.get("command")
    if not isinstance(command, list) or len(command) < 2 or Path(str(command[1])).resolve() != READER.resolve():
        raise BuildError("QA031 receipt does not bind the expected Root preflight reader")
    receipt_hashes = request.get("input_sha256")
    if not isinstance(receipt_hashes, Mapping) or receipt_hashes.get(str(PARTVTK.resolve())) != partvtk_binding["sha256"]:
        raise BuildError("QA031 receipt does not bind the expected PartVTK binary")
    return reader_binding, qa_receipt_binding, partvtk_binding


def build_request(
    case: Mapping[str, Any],
    reader_binding: Mapping[str, str],
    qa_receipt_binding: Mapping[str, str],
    partvtk_binding: Mapping[str, str],
) -> dict[str, Any]:
    manifest_path = Path(str(case["input_manifest"])).resolve()
    manifest = load(manifest_path)
    if manifest.get("case_id") != case["case_id"] or manifest.get("execution_allowed") is not False:
        raise BuildError(f"strict input manifest is not the disabled {case['case_id']} source")
    raw_inputs = manifest.get("inputs")
    if not isinstance(raw_inputs, list) or not raw_inputs:
        raise BuildError(f"strict input manifest has no inputs: {case['case_id']}")
    source_paths = [Path(str(row["path"])).resolve() for row in raw_inputs if isinstance(row, Mapping) and isinstance(row.get("path"), str)]
    paths = _unique_paths([
        PYTHON,
        WORKER,
        READER,
        QA_RECEIPT,
        PARTVTK,
        STRICT_DISPATCH,
        RUNTIME,
        manifest_path,
        *source_paths,
    ])
    input_bindings = {str(path): binding(path)["sha256"] for path in paths}
    command = [
        str(PYTHON.resolve()),
        str(WORKER.resolve()),
        "--input-manifest",
        str(manifest_path),
        "--reader-source",
        str(READER.resolve()),
        "--reader-sha256",
        reader_binding["sha256"],
        "--output",
        "{attempt_root}/strict-cpu-audit.json",
    ]
    return {
        "schema": "ds02.runner.request.v2",
        "family_id": "F1",
        "case_id": case["case_id"],
        "attempt_id": case["attempt_id"],
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "model_profile": "gpt-5.6-luna/max",
        "cpu_threads": 2,
        "max_wall_seconds": 900,
        "estimated_storage_bytes": 134217728,
        "cwd": str(INFRA_LAB),
        "worktree_root": str(INFRA_LAB.parent),
        "command": command,
        "input_files": paths and [str(path) for path in paths],
        "input_sha256": input_bindings,
        "input_hashes": dict(input_bindings),
        "source_only": True,
        "execution_allowed": False,
        "launch_allowed": False,
        "source_immutability": True,
        "launch_owner": "Root only after reviewing fresh060 worker and enabling this audit request",
        "production_approval": "none",
        "q_n": "not_granted",
        "q_e": "not_assessed",
        "numerical_precision_status": "not_accepted",
        "request_status": "disabled_pending_root_review",
        "source_input_manifest": binding(manifest_path),
        "root_preflight_reader": dict(reader_binding),
        "qa031_execution_receipt": dict(qa_receipt_binding),
        "partvtk_binary": dict(partvtk_binding),
        "strict_dispatch": binding(STRICT_DISPATCH),
        "runtime": binding(RUNTIME),
        "expected_identity": manifest.get("expected_identity"),
        "required_output_contract": {
            "schema": case["audit_schema"],
            "status": "completed",
            "returncode": 0,
            "sidecars": list(
                (
                    "initial_mass_discrepancy_report",
                    "physics_evidence",
                    "geometry_evidence",
                    "motion_evidence",
                    "no_overlap_finite_state_evidence",
                )
            ),
            "raw_arrays_written": False,
        },
        "worker_mode": "read_existing_QA031_official_CSV_streaming_no_subprocess",
        "scope": "Actual read-only initial mass/finite-state audit from genuine GenCase027 and QA031 sources; no solver, GenCase, PartVTK, raw-array output, conversion, ParaView, or Q-N claim.",
        "output_root_contract": str(case["output_root"]),
    }


def build_source_package(out: Path = HERE) -> dict[str, Any]:
    out = out.resolve()
    reader_binding, qa_receipt_binding, partvtk_binding = _reader_context()
    request_bindings: list[dict[str, Any]] = []
    for case in CASES:
        request = build_request(case, reader_binding, qa_receipt_binding, partvtk_binding)
        request_path = out / "requests" / str(case["request_name"])
        save(request_path, request)
        request_bindings.append(
            {
                "variant": case["variant"],
                "case_id": case["case_id"],
                "audit_schema": case["audit_schema"],
                "input_manifest": binding(Path(str(case["input_manifest"]))),
                "request": binding(request_path),
                "output_root_contract": str(case["output_root"]),
                "expected_identity": request["expected_identity"],
            }
        )
    package = {
        "schema": "ds02.stage1.f1.initial-state-audit-worker-source.v1",
        "status": "source_only_disabled_requests",
        "source_only": True,
        "execution_allowed": False,
        "family_id": "F1",
        "worker": binding(WORKER),
        "builder": binding(HERE / "build_f1_initial_state_audit_worker.py"),
        "root_preflight_reader": reader_binding,
        "qa031_execution_receipt": qa_receipt_binding,
        "partvtk_binary": partvtk_binding,
        "strict_dispatch": binding(STRICT_DISPATCH),
        "runtime": binding(RUNTIME),
        "worker_contract": {
            "cpu_task_kind": "audit",
            "launch_allowed": False,
            "reads_existing_qa031_official_csv": True,
            "writes_raw_arrays": False,
            "launches_subprocess": False,
            "computes_mass_from_actual_rows": True,
            "required_sidecars": [
                "initial_mass_discrepancy_report",
                "physics_evidence",
                "geometry_evidence",
                "motion_evidence",
                "no_overlap_finite_state_evidence",
            ],
        },
        "cases": request_bindings,
    }
    package_path = out / "F1_INITIAL_STATE_AUDIT_WORKER_SOURCE_BINDINGS.json"
    save(package_path, package)
    return {
        "output": str(out),
        "worker": str(WORKER),
        "source_bindings": str(package_path),
        "requests": [row["request"]["path"] for row in request_bindings],
    }


def main() -> int:
    print(json.dumps(build_source_package(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
