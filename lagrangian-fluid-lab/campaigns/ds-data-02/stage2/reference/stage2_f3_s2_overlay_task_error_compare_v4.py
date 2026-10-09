#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Strict V4 three-way overlay comparison with producer and solver joins.

V2 validates the terminal solver evidence used by a compact summary.  This
additive layer also validates the *observer producer* evidence: producer
request, producer receipt, producer verification proof, and compact summary
must all agree by path and SHA.  The summary must then point to the same
underlying solver request, proof, and receipt that are supplied separately.

The worker reads only bounded JSON metadata and compact summaries.  It never
opens full observer reports, BI4/Part payloads, H5, or RunPARTs payloads.
ROOT177 is bound to ROOT162 and ROOT187 is bound to ROOT173.  ROOT188 is
represented by a pending manifest entry until its actual proof/receipt/summary
exist; a missing terminal evidence set is a hard validation failure, never a
scientific pass.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
V2_PATH = HERE / "stage2_f3_s2_overlay_task_error_compare_v2.py"
SCHEMA = "ds02.stage2.f3-s2.overlay-task-error-compare.v4"
MANIFEST_SCHEMA = "ds02.stage2.f3-s2.overlay-task-error-compare.v4.binding-manifest"
SUMMARY_SCHEMAS = {
    "ds02.stage2.f3-s2.full-native-stream-observer.v4",
    "ds02.stage2.f3-s2.full-native-stream-observer.v5",
}


def _load_v2():
    spec = importlib.util.spec_from_file_location(
        "stage2_f3_s2_overlay_task_error_compare_v4_v2_dependency", V2_PATH
    )
    if spec is None or spec.loader is None:
        raise ImportError(V2_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


V2 = _load_v2()
# V2 is an adapter over the consumed V1 module.  Keep the normalizer and
# contract loader explicitly rooted at that loaded dependency; V2 itself
# exposes terminal-join/compare adapters, not private V1 helpers.
V1 = V2.V1


def _path(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} path is missing")
    return Path(value).expanduser().resolve()


def _same_path(value: Any, expected: Path, label: str) -> None:
    actual = _path(value, label)
    if actual != expected:
        raise ValueError(f"{label} path differs: {actual} != {expected}")


def _same_sha(value: Any, expected: str, label: str) -> None:
    if not isinstance(value, str) or value.lower() != expected.lower():
        raise ValueError(f"{label} SHA differs")


def _returncode(value: dict[str, Any], label: str) -> int:
    execution = value.get("execution")
    nested = execution if isinstance(execution, dict) else {}
    candidates = [
        value.get("returncode"),
        value.get("return_code"),
        nested.get("returncode"),
        nested.get("return_code"),
    ]
    present = [item for item in candidates if item is not None]
    if not present:
        raise ValueError(f"{label} has no terminal returncode")
    try:
        parsed = [int(item) for item in present]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} returncode is not integral") from exc
    if any(item != 0 for item in parsed):
        raise ValueError(f"{label} returncode is not zero")
    return parsed[0]


def _completed(value: dict[str, Any], label: str) -> None:
    status = str(value.get("status", "")).lower()
    if not (
        status.startswith("completed")
        or status.startswith("complete")
        or status in {"success", "completed0"}
    ):
        raise ValueError(f"{label} is not completed: {value.get('status')!r}")
    _returncode(value, label)


def _record(path: Path, label: str, max_bytes: int) -> tuple[dict[str, Any], dict[str, Any]]:
    return V2.V1._json_file(path, label, max_bytes=max_bytes)


def _request_record(
    value: Any,
    path: Path,
    request_value: dict[str, Any],
    record: dict[str, Any],
    label: str,
) -> None:
    if isinstance(value, dict) and "path" in value:
        _same_path(value.get("path"), path, f"{label} request")
        _same_sha(value.get("sha256"), record["sha256"], f"{label} request")
    elif isinstance(value, dict):
        # Receipts normally embed the executed request object rather than a
        # path record.  Its identity fields still must match exactly.
        if value.get("case_id") is not None and request_value.get("case_id") is not None:
            if value.get("case_id") != request_value.get("case_id"):
                raise ValueError(f"{label} embedded request case differs")
        if value.get("attempt_id") is not None and request_value.get("attempt_id") is not None:
            if value.get("attempt_id") != request_value.get("attempt_id"):
                raise ValueError(f"{label} embedded request attempt differs")
    else:
        raise ValueError(f"{label} receipt request is absent")


def _proof_status(value: dict[str, Any], label: str) -> None:
    schema = value.get("schema")
    if schema not in {
        "ds02.stage2.root-actual-verification.v1",
        "ds02.stage2.root-actual-external-solver-verification.v1",
    }:
        raise ValueError(f"{label} proof schema is not an actual root proof")
    status = str(value.get("status", ""))
    if not ("ACTUAL" in status or status.startswith("VERIFIED") or "PASS" in status):
        raise ValueError(f"{label} proof is not actual: {status!r}")


def _validate_solver_binding(
    *,
    label: str,
    summary: dict[str, Any],
    proof: Path,
    request: Path,
    receipt: Path,
    expected_physical_case: str,
) -> dict[str, Any]:
    """Delegate the underlying solver join to the consumed V2 validator."""

    return V2._validate_terminal_binding(
        label,
        summary,
        proof,
        request,
        receipt,
        expected_physical_case,
    )


def _validate_binding(spec: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    label = spec.get("label")
    if not isinstance(label, str) or not label:
        raise ValueError("binding label is missing")
    expected_case = spec.get("expected_physical_case")
    if not isinstance(expected_case, str) or not expected_case:
        raise ValueError(f"{label} expected physical case is missing")
    producer = spec.get("producer")
    solver = spec.get("solver")
    if not isinstance(producer, dict) or not isinstance(solver, dict):
        raise ValueError(f"{label} producer/solver evidence is incomplete")

    summary_path = _path(producer.get("summary"), f"{label} producer summary")
    producer_proof_path = _path(producer.get("proof"), f"{label} producer proof")
    producer_request_path = _path(producer.get("request"), f"{label} producer request")
    producer_receipt_path = _path(producer.get("receipt"), f"{label} producer receipt")
    solver_proof_path = _path(solver.get("proof"), f"{label} solver proof")
    solver_request_path = _path(solver.get("request"), f"{label} solver request")
    solver_receipt_path = _path(solver.get("receipt"), f"{label} solver receipt")

    summary_record, summary_value = _record(
        summary_path, f"{label} producer compact summary", 4 * 1024 * 1024
    )
    if summary_value.get("schema") not in SUMMARY_SCHEMAS:
        raise ValueError(f"{label} compact summary schema is unsupported")
    if not str(summary_value.get("status", "")).startswith("PASS"):
        raise ValueError(f"{label} compact summary is not successful")

    producer_proof_record, producer_proof = _record(
        producer_proof_path, f"{label} producer proof", 32 * 1024 * 1024
    )
    producer_request_record, producer_request = _record(
        producer_request_path, f"{label} producer request", 4 * 1024 * 1024
    )
    producer_receipt_record, producer_receipt = _record(
        producer_receipt_path, f"{label} producer receipt", 32 * 1024 * 1024
    )
    _proof_status(producer_proof, f"{label} producer")
    if producer_request.get("physical_case_id") not in {expected_case, None}:
        raise ValueError(f"{label} producer request physical case differs")
    _same_path(producer_proof.get("request"), producer_request_path, f"{label} producer proof request")
    _same_sha(
        producer_proof.get("request_sha256"),
        producer_request_record["sha256"],
        f"{label} producer proof request",
    )
    _same_path(producer_proof.get("receipt"), producer_receipt_path, f"{label} producer proof receipt")
    _same_sha(
        producer_proof.get("receipt_sha256"),
        producer_receipt_record["sha256"],
        f"{label} producer proof receipt",
    )
    _same_path(producer_proof.get("summary"), summary_path, f"{label} producer proof summary")
    _same_sha(
        producer_proof.get("summary_sha256"),
        summary_record["sha256"],
        f"{label} producer proof summary",
    )
    if producer_proof.get("summary_bytes") not in (None, summary_record["bytes"]):
        raise ValueError(f"{label} producer proof summary byte count differs")
    _same_sha(
        producer_receipt.get("request_sha256"),
        producer_request_record["sha256"],
        f"{label} producer receipt request",
    )
    _request_record(
        producer_receipt.get("request"),
        producer_request_path,
        producer_request,
        producer_request_record,
        label,
    )
    _completed(producer_receipt, f"{label} producer receipt")

    solver_proof_record, solver_proof = _record(
        solver_proof_path, f"{label} solver proof", 32 * 1024 * 1024
    )
    solver_request_record, solver_request = _record(
        solver_request_path, f"{label} solver request", 8 * 1024 * 1024
    )
    solver_receipt_record, solver_receipt = _record(
        solver_receipt_path, f"{label} solver receipt", 32 * 1024 * 1024
    )
    solver_join = _validate_solver_binding(
        label=f"{label}.underlying_solver",
        summary=summary_value,
        proof=solver_proof_path,
        request=solver_request_path,
        receipt=solver_receipt_path,
        expected_physical_case=expected_case,
    )

    case_binding = summary_value.get("case_binding")
    if not isinstance(case_binding, dict):
        raise ValueError(f"{label} compact summary lacks case binding")
    source_binding = summary_value.get("source_binding")
    if not isinstance(source_binding, dict):
        raise ValueError(f"{label} compact summary lacks source binding")
    _same_sha(
        case_binding.get("terminal_request_sha256"),
        solver_request_record["sha256"],
        f"{label} compact summary underlying request",
    )
    _same_sha(
        source_binding.get("terminal_request_sha256"),
        solver_request_record["sha256"],
        f"{label} compact summary source request",
    )
    declared_record = case_binding.get("request_record")
    if not isinstance(declared_record, dict):
        raise ValueError(f"{label} compact summary lacks underlying request record")
    _same_path(declared_record.get("path"), solver_request_path, f"{label} compact summary request record")
    _same_sha(declared_record.get("sha256"), solver_request_record["sha256"], f"{label} compact summary request record")

    # The proof must bind the same solver evidence as the compact summary.  A
    # producer proof from another observer cannot be substituted merely because
    # its fields or physical case are equal.
    producer_case_binding = producer_proof.get("case_binding")
    if isinstance(producer_case_binding, dict):
        _same_sha(
            producer_case_binding.get("terminal_request_sha256"),
            solver_request_record["sha256"],
            f"{label} producer proof underlying request",
        )

    normalized = V1._normalize(label, summary_path, expected_case)
    evidence = {
        "label": label,
        "producer": {
            "request": producer_request_record,
            "receipt": producer_receipt_record,
            "proof": producer_proof_record,
            "summary": summary_record,
        },
        "underlying_solver": {
            "request": solver_request_record,
            "receipt": solver_receipt_record,
            "proof": solver_proof_record,
            "v2_terminal_join": solver_join,
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    return normalized, evidence


def _read_manifest(path: Path) -> dict[str, Any]:
    record, manifest = _record(path, "V4 binding manifest", 4 * 1024 * 1024)
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("unexpected V4 binding manifest schema")
    bindings = manifest.get("bindings")
    if not isinstance(bindings, list) or not bindings:
        raise ValueError("V4 binding manifest has no bindings")
    labels = [item.get("label") for item in bindings if isinstance(item, dict)]
    if len(labels) != len(set(labels)):
        raise ValueError("V4 binding manifest has duplicate labels")
    manifest["_record"] = record
    return manifest


def validate_manifest(path: Path, *, require_three_way: bool = False) -> dict[str, Any]:
    manifest = _read_manifest(path)
    normalized: dict[str, dict[str, Any]] = {}
    evidence: dict[str, dict[str, Any]] = {}
    for spec in manifest["bindings"]:
        if not isinstance(spec, dict):
            raise ValueError("V4 binding entry is not an object")
        value, joined = _validate_binding(spec)
        normalized[spec["label"]] = value
        evidence[spec["label"]] = joined

    required = {"same_cfl_baseline", "half_cfl", "half_output"}
    missing = sorted(required - set(normalized))
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "PRODUCER_AND_SOLVER_BINDINGS_VALIDATED" if not missing else "PARTIAL_PRODUCER_AND_SOLVER_BINDINGS_VALIDATED",
        "manifest": manifest["_record"],
        "bindings": evidence,
        "missing_required_labels": missing,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "full_report_read": False,
        "native_payload_read": False,
        "h5_read": False,
    }
    if missing:
        if require_three_way:
            raise ValueError(f"three-way comparison missing actual bindings: {missing}")
        return result
    contract_path = _path(manifest.get("calibration_contract"), "calibration contract")
    contract = V1._contract(contract_path)
    compared = V2.compare(normalized, contract)
    compared["schema"] = SCHEMA
    compared["producer_solver_binding_policy"] = "strict_observer_proof_receipt_summary_and_underlying_solver_join"
    compared["scientific_qualification"] = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    result["status"] = "THREE_WAY_COMPARISON_READY_WITH_STRICT_PRODUCER_SOLVER_JOINS"
    result["comparison"] = compared
    return result


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _fixture_self_test() -> dict[str, Any]:
    """Exercise wrong producer-proof, receipt, and summary SHA rejection."""

    physical = "fixture-physical-case"
    with tempfile.TemporaryDirectory(prefix="f3-overlay-v4-") as root_text:
        root = Path(root_text)
        solver_request = root / "solver-request.json"
        solver_receipt = root / "solver-receipt.json"
        solver_proof = root / "solver-proof.json"
        producer_request = root / "producer-request.json"
        producer_receipt = root / "producer-receipt.json"
        producer_proof = root / "producer-proof.json"
        summary = root / "summary.json"

        solver_request_value = {"physical_case_id": physical, "case_id": "solver", "attempt_id": "solver-attempt"}
        solver_request.write_text(json.dumps(solver_request_value, sort_keys=True), encoding="utf-8")
        solver_request_record = {"sha256": hashlib.sha256(solver_request.read_bytes()).hexdigest()}
        solver_receipt_value = {"status": "COMPLETED_DEVELOPMENT_UNKNOWN", "returncode": 0, "request": {"path": str(solver_request), "sha256": solver_request_record["sha256"]}, "attempt_id": "solver-attempt"}
        solver_receipt.write_text(json.dumps(solver_receipt_value, sort_keys=True), encoding="utf-8")
        solver_receipt_record = {"sha256": hashlib.sha256(solver_receipt.read_bytes()).hexdigest()}
        solver_proof_value = {"schema": "ds02.stage2.root-actual-verification.v1", "status": "VERIFIED_ACTUAL_FIXTURE", "request": str(solver_request), "request_sha256": solver_request_record["sha256"], "receipt": str(solver_receipt), "receipt_sha256": solver_receipt_record["sha256"]}
        solver_proof.write_text(json.dumps(solver_proof_value, sort_keys=True), encoding="utf-8")

        producer_request_value = {"physical_case_id": physical, "case_id": "producer", "attempt_id": "producer-attempt"}
        producer_request.write_text(json.dumps(producer_request_value, sort_keys=True), encoding="utf-8")
        producer_request_record = {"sha256": hashlib.sha256(producer_request.read_bytes()).hexdigest()}
        producer_receipt_value = {"status": "completed", "returncode": 0, "request_sha256": producer_request_record["sha256"], "request": {"path": str(producer_request), "sha256": producer_request_record["sha256"]}, "attempt_id": "producer-attempt"}
        producer_receipt.write_text(json.dumps(producer_receipt_value, sort_keys=True), encoding="utf-8")
        producer_receipt_record = {"sha256": hashlib.sha256(producer_receipt.read_bytes()).hexdigest()}

        summary_value = {
            "schema": "ds02.stage2.f3-s2.full-native-stream-observer.v5",
            "status": "PASS_FIXTURE",
            "case_binding": {"physical_case_id": physical, "case_id": "solver", "attempt_id": "solver-attempt", "terminal_request_sha256": solver_request_record["sha256"], "request_record": {"path": str(solver_request), "sha256": solver_request_record["sha256"]}},
            "source_binding": {"terminal_request_sha256": solver_request_record["sha256"]},
            "selected_observations": [{"frame": 0, "runparts_time_s": 0.0, "native_header": {"MassFluid": 1.0}, "fields": {"weighted_centroid_m": [0.0, 0.0, 0.0], "weighted_velocity_m_per_s": [0.0, 0.0, 0.0], "kinetic_energy_j": 0.0, "mass_semantics": "native header MassFluid"}}],
            "query_brackets": [{"query_time_s": 0.0, "status": "EXACT_OR_LEFT", "lower_frame": 0, "upper_frame": 0, "lower_time_s": 0.0, "upper_time_s": 0.0}],
        }
        summary.write_text(json.dumps(summary_value, sort_keys=True), encoding="utf-8")
        summary_record = {"sha256": hashlib.sha256(summary.read_bytes()).hexdigest(), "bytes": summary.stat().st_size}
        producer_proof_value = {"schema": "ds02.stage2.root-actual-verification.v1", "status": "VERIFIED_ACTUAL_FIXTURE", "request": str(producer_request), "request_sha256": producer_request_record["sha256"], "receipt": str(producer_receipt), "receipt_sha256": producer_receipt_record["sha256"], "summary": str(summary), "summary_sha256": summary_record["sha256"], "summary_bytes": summary_record["bytes"], "case_binding": {"terminal_request_sha256": solver_request_record["sha256"]}}
        producer_proof.write_text(json.dumps(producer_proof_value, sort_keys=True), encoding="utf-8")
        spec = {"label": "fixture", "expected_physical_case": physical, "producer": {"summary": str(summary), "proof": str(producer_proof), "request": str(producer_request), "receipt": str(producer_receipt)}, "solver": {"proof": str(solver_proof), "request": str(solver_request), "receipt": str(solver_receipt)}}
        _validate_binding(spec)

        negative_counts = {"wrong_producer_proof_sha": False, "wrong_producer_receipt_sha": False, "wrong_producer_summary_sha": False}
        for key, field, replacement in (
            ("wrong_producer_proof_sha", "request_sha256", "0" * 64),
            ("wrong_producer_receipt_sha", "receipt_sha256", "1" * 64),
            ("wrong_producer_summary_sha", "summary_sha256", "2" * 64),
        ):
            bad = root / f"{key}.json"
            value = dict(producer_proof_value)
            value[field] = replacement
            bad.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
            bad_spec = dict(spec)
            bad_spec["producer"] = dict(spec["producer"])
            bad_spec["producer"]["proof"] = str(bad)
            try:
                _validate_binding(bad_spec)
            except ValueError:
                negative_counts[key] = True
        if not all(negative_counts.values()):
            raise AssertionError(negative_counts)
        return {"status": "PASS", "negative_fixtures": negative_counts, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-three-way", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(_fixture_self_test(), indent=2, sort_keys=True))
        return 0
    if args.manifest is None:
        parser.error("--manifest is required unless --self-test is used")
    result = validate_manifest(args.manifest, require_three_way=args.require_three_way)
    if args.output is not None:
        _write(args.output, result)
    print(json.dumps({"status": result["status"], "missing_required_labels": result["missing_required_labels"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
