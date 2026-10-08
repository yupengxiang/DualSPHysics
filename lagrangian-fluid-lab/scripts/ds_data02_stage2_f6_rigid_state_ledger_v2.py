#!/usr/bin/env python3
"""Forward F6 rigid-state ledger with an additive manifest adapter.

The consumed v1 worker expects a direct ``conversion_report`` row field,
while the completed v5 producer manifest stores the same immutable report
under ``conversion_contract.report``.  This version consumes an additive
adapter manifest that exposes that field and independently checks the
original producer manifest/output/receipt bindings.  The original v5
manifest, v1 request, v1 failure receipt, output, and source bytes remain
unchanged.

The worker reads only the completed v5 JSON output, receipts, XML/JSON/CSV
provenance and FloatingInfo CSVs.  It never opens trajectory H5 or BI4 and
does not start a solver, decoder, CFD, or model.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

import ds_data02_stage2_f6_rigid_state_ledger_v1 as legacy


SCRIPT = Path(__file__).resolve()
ADAPTER_SCHEMA = "ds02.stage2.f6-rigid-state-ledger-input-manifest.v1"
ADAPTER_STATUS = "PREPARED_F6_RIGID_STATE_LEDGER_INPUT_ADAPTER_V1"
PRODUCER_SCHEMA = "ds02.stage2.f6-static-kabsch-combined-bundle.v5"
PRODUCER_OUTPUT_SCHEMA = "ds02.stage2.f6-static-kabsch-combined.v5"
EXPECTED_CASES = legacy.EXPECTED_CASES


class RigidLedgerV2Error(RuntimeError):
    """Raised when the additive adapter or producer binding is not exact."""


def sha256(value: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(value).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(value: Path | str, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise RigidLedgerV2Error(f"{label} is missing: {path}")
    if path.suffix.lower() in {".h5", ".hdf5", ".obi4", ".bi4"} or (path.name.startswith("Part_") and path.suffix.lower() == ".bi4"):
        raise RigidLedgerV2Error(f"H5/BI4/raw input is forbidden: {path}")
    return path


def read_json(value: Path | str, label: str) -> tuple[Path, dict[str, Any]]:
    path = require_file(value, label)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RigidLedgerV2Error(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise RigidLedgerV2Error(f"{label} is not an object: {path}")
    return path, payload


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path = path.resolve()
    if path.exists():
        raise RigidLedgerV2Error(f"refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
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


def file_binding(path: Path | str, label: str, expected: str | None = None) -> dict[str, Any]:
    path = require_file(path, label)
    digest = sha256(path)
    if expected is not None and digest != expected:
        raise RigidLedgerV2Error(f"{label} digest differs: {path}")
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": digest}


def producer_rows(manifest_path: Path) -> tuple[Path, dict[str, Any], list[dict[str, Any]]]:
    path, manifest = read_json(manifest_path, "completed F6 v5 producer manifest")
    if manifest.get("schema") != PRODUCER_SCHEMA or manifest.get("status") != "PREPARED_COMBINED_V5_H5_SOURCE_BOUND":
        raise RigidLedgerV2Error("producer manifest schema/status differs")
    rows = manifest.get("source_cases")
    if not isinstance(rows, list) or {row.get("physical_case_id") for row in rows} != EXPECTED_CASES:
        raise RigidLedgerV2Error("producer manifest case union differs")
    adapted: list[dict[str, Any]] = []
    for source in rows:
        row = copy.deepcopy(source)
        contract = row.get("conversion_contract")
        report = contract.get("report") if isinstance(contract, dict) else None
        if not isinstance(report, dict) or not report.get("path") or not report.get("sha256"):
            raise RigidLedgerV2Error(f"{row.get('physical_case_id')} lacks conversion_contract.report")
        # Additive schema bridge.  The original row and original manifest are
        # never rewritten; v2's validator consumes this copied row only.
        row["conversion_report"] = copy.deepcopy(report)
        adapted.append(row)
    return path, manifest, adapted


def adapt_manifest(producer_manifest: Path, producer_output: Path, producer_receipt: Path, output: Path) -> dict[str, Any]:
    producer_path, producer, rows = producer_rows(producer_manifest)
    output_path, output_payload = read_json(producer_output, "completed F6 v5 output")
    receipt_path, receipt = read_json(producer_receipt, "completed F6 v5 receipt")
    producer_binding = file_binding(producer_path, "producer manifest")
    output_binding = file_binding(output_path, "producer output")
    receipt_binding = file_binding(receipt_path, "producer receipt")
    if output_payload.get("schema") != PRODUCER_OUTPUT_SCHEMA or output_payload.get("status") != "completed":
        raise RigidLedgerV2Error("producer output schema/status differs")
    if receipt.get("status") != "completed" or int(receipt.get("returncode", -1)) != 0:
        raise RigidLedgerV2Error("producer receipt is not completed code 0")
    if output_payload.get("bundle", {}).get("path") != producer_binding["path"] or output_payload.get("bundle", {}).get("sha256") != producer_binding["sha256"]:
        raise RigidLedgerV2Error("producer output does not bind original manifest")
    h5_metadata = {}
    for row in rows:
        case = str(row["physical_case_id"])
        h5 = row.get("trajectory_h5", {})
        h5_metadata[case] = {"path": str(h5.get("path")), "bytes": int(h5.get("bytes", -1)), "sha256": str(h5.get("sha256")), "registered_as_input": False, "content_opened": False}
    payload = {
        "schema": ADAPTER_SCHEMA,
        "status": ADAPTER_STATUS,
        "producer_manifest": producer_binding,
        "producer_output": output_binding,
        "producer_receipt": receipt_binding,
        "source_cases": rows,
        "selected_case_ids": sorted(EXPECTED_CASES),
        "h5_metadata_not_input": h5_metadata,
        "adapter_contract": {
            "conversion_report_source": "copied from each immutable producer row conversion_contract.report",
            "original_manifest_modified": False,
            "original_output_binding_preserved": True,
            "original_receipt_binding_preserved": True,
            "h5_content_read": False,
            "bi4_content_read": False,
        },
        "claim_boundary": {"physical_COM": "UNKNOWN", "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED"},
    }
    atomic_json(output, payload)
    return {"status": payload["status"], "output": str(output.resolve()), "case_count": len(rows), "h5_opened": False, "producer_manifest_sha256": producer_binding["sha256"]}


def validate_adapter(adapter_path: Path) -> tuple[Path, dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    path, adapter = read_json(adapter_path, "F6 rigid-state adapter manifest")
    if adapter.get("schema") != ADAPTER_SCHEMA or adapter.get("status") != ADAPTER_STATUS:
        raise RigidLedgerV2Error("adapter schema/status differs")
    producer_decl = adapter.get("producer_manifest", {})
    producer_path, producer, producer_rows_value = producer_rows(Path(producer_decl.get("path", "")))
    producer_actual = file_binding(producer_path, "original producer manifest", producer_decl.get("sha256"))
    if producer_actual["bytes"] != producer_decl.get("bytes"):
        raise RigidLedgerV2Error("original producer manifest byte count differs")
    rows = adapter.get("source_cases")
    if not isinstance(rows, list) or {row.get("physical_case_id") for row in rows} != EXPECTED_CASES:
        raise RigidLedgerV2Error("adapter case union differs")
    original_by_case = {row["physical_case_id"]: row for row in producer_rows_value}
    for row in rows:
        case = row["physical_case_id"]
        if row.get("conversion_report") != original_by_case[case].get("conversion_contract", {}).get("report"):
            raise RigidLedgerV2Error(f"{case} conversion report adapter differs")
    if adapter.get("adapter_contract", {}).get("original_manifest_modified") is not False:
        raise RigidLedgerV2Error("adapter does not preserve original manifest")
    return path, adapter, producer, rows


def validate_execution(adapter_path: Path, output_path: Path, receipt_path: Path) -> dict[str, Any]:
    adapter_path, adapter, producer, manifest_rows = validate_adapter(adapter_path)
    output_path, output = read_json(output_path, "completed F6 v5 output")
    receipt_path, receipt = read_json(receipt_path, "completed F6 v5 receipt")
    producer_decl = adapter["producer_manifest"]
    if output.get("schema") != PRODUCER_OUTPUT_SCHEMA or output.get("status") != "completed":
        raise RigidLedgerV2Error("F6 v5 output schema/status differs")
    if output.get("bundle", {}).get("path") != producer_decl["path"] or output.get("bundle", {}).get("sha256") != producer_decl["sha256"]:
        raise RigidLedgerV2Error("F6 v5 output original manifest binding differs")
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed" or int(receipt.get("returncode", -1)) != 0:
        raise RigidLedgerV2Error("F6 v5 receipt is not completed code 0")
    request = receipt.get("request", {})
    if request.get("case_id") != "STAGE2_F6_STATIC_KABSCH_COMBINED_V5" or request.get("attempt_id") != "f6-static-kabsch-combined-v5-primary-001":
        raise RigidLedgerV2Error("F6 v5 receipt request identity differs")
    if output.get("source_policy", {}).get("h5_opened") is not True or output.get("source_policy", {}).get("solver_started") is not False:
        raise RigidLedgerV2Error("F6 v5 output source policy differs")
    declared = request.get("input_sha256", {})
    launch = receipt.get("input_hashes_at_launch", {})
    finish = receipt.get("input_hashes_after_run", {})
    if not launch or launch != finish:
        raise RigidLedgerV2Error("F6 v5 producer input hashes are not stable")
    for row in manifest_rows:
        h5 = row.get("trajectory_h5", {})
        key = str(Path(str(h5.get("path", ""))).expanduser().resolve())
        digest = h5.get("sha256")
        if not isinstance(digest, str) or declared.get(key) != digest or launch.get(key) != digest or finish.get(key) != digest:
            raise RigidLedgerV2Error(f"F6 v5 H5 terminal metadata is not stable: {key}")
    output_rows = {row.get("physical_case_id"): row for row in output.get("cases", [])}
    if set(output_rows) != EXPECTED_CASES:
        raise RigidLedgerV2Error("F6 v5 output case union differs")
    cases = [legacy.validate_case(row, output_rows[row["physical_case_id"]]) for row in sorted(manifest_rows, key=lambda item: item["physical_case_id"])]
    return {
        "schema": "ds02.stage2.f6-rigid-state-ledger.v2",
        "status": "completed",
        "adapter_manifest": file_binding(adapter_path, "adapter manifest"),
        "producer_manifest": {"path": producer_decl["path"], "sha256": producer_decl["sha256"], "bytes": producer_decl["bytes"]},
        "producer": file_binding(output_path, "F6 v5 output"),
        "execution_receipt": file_binding(receipt_path, "F6 v5 receipt"),
        "cases": cases,
        "claim_boundary": {"physical_body_mass": "128 kg", "sampled_support_mass": "256 kg", "physical_COM": "UNKNOWN", "SO3_truth": "UNKNOWN; algebraic Kabsch fit diagnostics only", "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN"},
        "read_policy": {"h5_opened_by_validator": False, "trajectory_content_opened_by_validator": False, "solver_started": False, "decoder_started": False},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    adapt = sub.add_parser("adapt")
    adapt.add_argument("--producer-manifest", type=Path, required=True)
    adapt.add_argument("--producer-output", type=Path, required=True)
    adapt.add_argument("--producer-receipt", type=Path, required=True)
    adapt.add_argument("--output", type=Path, required=True)
    audit = sub.add_parser("audit")
    audit.add_argument("--manifest", type=Path, required=True)
    audit.add_argument("--output", type=Path, required=True)
    audit.add_argument("--receipt", type=Path, required=True)
    audit.add_argument("--sidecar", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == "adapt":
            result = adapt_manifest(args.producer_manifest, args.producer_output, args.producer_receipt, args.output)
        else:
            result = validate_execution(args.manifest, args.output, args.receipt)
            legacy.atomic_json(args.sidecar, result)
            result = {"status": result["status"], "sidecar": str(args.sidecar.resolve()), "case_count": len(result["cases"]), "h5_opened_by_validator": False}
    except (RigidLedgerV2Error, legacy.RigidLedgerError) as exc:
        raise SystemExit(f"RigidLedgerV2Error: {exc}")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
