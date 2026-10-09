#!/usr/bin/env python3
"""Build V50 post-terminal metadata from the two real parent records.

The parent-v3 implementation writes its immutable Home receipt before it
charges the same-parent ledger.  The value returned by ``run`` is a second,
small record written by the caller after that charge.  They are deliberately
different records:

* ``--parent-receipt`` is the Home receipt.  It binds request/executor paths,
  the post-reservation execution scope, and the reservation/charge IDs, but
  records ``pending_same_parent_charge`` at the time it is written.
* ``--returned-parent-report`` is the returned terminal summary.  It binds
  the Home receipt path and request SHA, and proves that the charge mutation
  completed, but it does not repeat the request/executor/execution sections.

V1 incorrectly required a synthetic object containing both shapes.  This
additive V2 accepts the two actual immutable inputs and cross-checks them; it
never fabricates or rewrites either record.  It otherwise delegates bounded
worker/artifact/source checks to V1.  It does not open or hash HDF5, BI4, raw,
typed, or result payloads.  The output static attestation is explicitly a
derived sidecar, never an instrumented parent receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
V1_SCRIPT = SCRIPT.parent / "ds_data02_stage2_f2_v50_source_only_postterminal_builder_v1.py"
MAX_METADATA_BYTES = 64 * 1024 * 1024
PARENT_REPORT_SCHEMA = "ds02.stage2.f2-portable-executor-parent-report.v3"
STATIC_SCHEMA = "ds02.stage2.f2-v50-parent-static-content-verification.v1"
STATIC_STATUS = "PASS_PARENT_STATIC_CONTENT_AFTER_RESERVATION"
STATIC_PHASE = "AFTER_ATOMIC_PARENT_RESERVATION"
MANIFEST_SCHEMA = "ds02.stage2.f2-v47-producer-terminal-manifest.v1"
CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


class BuilderV2Error(RuntimeError):
    """A malformed, stale, or inconsistently paired terminal input."""


def _load_v1() -> Any:
    spec = importlib.util.spec_from_file_location(
        "ds02_bound_f2_v50_source_only_postterminal_builder_v1_for_v2", V1_SCRIPT)
    if spec is None or spec.loader is None:
        raise BuilderV2Error(f"cannot load V1 builder: {V1_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V1 = _load_v1()


def canonical_sha(value: Mapping[str, Any]) -> str:
    return V1.canonical_sha(value)


def _json(path: Path | str, role: str) -> tuple[Path, dict[str, Any]]:
    try:
        target, value = V1._json(path, role, max_bytes=MAX_METADATA_BYTES)
    except Exception as error:  # normalize the consumed builder's error type
        raise BuilderV2Error(str(error)) from error
    return target, value


def _sha_file(path: Path | str, role: str) -> str:
    try:
        return V1.sha256_file(path, max_bytes=MAX_METADATA_BYTES, role=role)
    except Exception as error:
        raise BuilderV2Error(str(error)) from error


def _sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise BuilderV2Error(f"{role} must be a lowercase SHA-256")
    return value


def _file(path: Any, role: str) -> Path:
    try:
        return V1._file(path, role, max_bytes=MAX_METADATA_BYTES)
    except Exception as error:
        raise BuilderV2Error(str(error)) from error


def _canonical_request(path: Path, value: Mapping[str, Any], role: str) -> str:
    declared = _sha(value.get("sha256"), f"{role}.sha256")
    if declared != canonical_sha(value):
        raise BuilderV2Error(f"{role} canonical SHA differs")
    return _sha_file(path, role)


def _validate_common_inputs(executor_path: Path, executor: Mapping[str, Any],
                            parent_path: Path, parent: Mapping[str, Any],
                            preflight_path: Path, preflight: Mapping[str, Any]) -> dict[str, Any]:
    if executor.get("schema") != "ds02.stage2.f2-portable-executor-request.v34":
        raise BuilderV2Error("executor schema is not v34")
    if parent.get("schema") != "ds02.stage2.f2-portable-executor-parent-request.v3":
        raise BuilderV2Error("parent schema is not parent-v3")
    executor_sha = _canonical_request(executor_path, executor, "executor request")
    parent_sha = _canonical_request(parent_path, parent, "parent request")
    if preflight.get("schema") != "ds02.stage2.root.v50-metadata-preflight.v1" \
            or preflight.get("status") != "ACTUAL_PARENT_V3_METADATA_VALIDATOR_PASS":
        raise BuilderV2Error("V50 metadata preflight schema/status differs")
    if preflight.get("array_payload_read") is not False \
            or preflight.get("qualification_credit") not in {None, "NONE"}:
        raise BuilderV2Error("V50 metadata preflight claims payload access or qualification credit")
    if preflight.get("content_hash_phase") != "AFTER_ATOMIC_PARENT_RESERVATION":
        raise BuilderV2Error("V50 metadata preflight content phase differs")
    if preflight.get("namespace_absent") is not True:
        raise BuilderV2Error("V50 metadata preflight namespace absence is not explicit")
    # The preflight must bind both request files if it exposes those fields.
    # Missing fields are tolerated for the older V50 preflight, but a present
    # field can never silently point at another case.
    executor_section = preflight.get("executor")
    if isinstance(executor_section, Mapping):
        if executor_section.get("request") not in {None, str(executor_path)}:
            raise BuilderV2Error("V50 preflight executor path differs")
        if executor_section.get("request_sha256") not in {None, executor_sha}:
            raise BuilderV2Error("V50 preflight executor SHA differs")
    parent_section = preflight.get("parent")
    if isinstance(parent_section, Mapping):
        if parent_section.get("parent_request") not in {None, str(parent_path)}:
            raise BuilderV2Error("V50 preflight parent path differs")
        if parent_section.get("parent_physical_sha256") not in {None, parent_sha}:
            raise BuilderV2Error("V50 preflight parent SHA differs")
    return {"executor_sha": executor_sha, "parent_sha": parent_sha}


def _charge_id_from_home(home: Mapping[str, Any]) -> str:
    accounting = home.get("accounting")
    if not isinstance(accounting, Mapping):
        raise BuilderV2Error("Home parent receipt accounting section is missing")
    charge_id = accounting.get("charge_id")
    if not isinstance(charge_id, str) or not charge_id:
        raise BuilderV2Error("Home parent receipt charge_id is missing")
    return charge_id


def _validate_home_receipt(path: Path, *, parent_path: Path, executor_path: Path,
                           parent_sha: str, executor_sha: str) -> tuple[dict[str, Any], dict[str, Any]]:
    _, home = _json(path, "Home parent receipt")
    if home.get("schema") != PARENT_REPORT_SCHEMA:
        raise BuilderV2Error(f"Home parent receipt schema differs: {home.get('schema')!r}")
    if home.get("status") != "COMPLETED_PARENT_EXECUTOR_RAW_TYPED_LABEL_UNKNOWN":
        raise BuilderV2Error(f"Home parent receipt is not completed: {home.get('status')!r}")
    request = home.get("request")
    if not isinstance(request, Mapping) or request.get("path") != str(parent_path) \
            or request.get("sha256") != parent_sha:
        raise BuilderV2Error("Home parent receipt request binding differs")
    executor = home.get("executor")
    if not isinstance(executor, Mapping) or executor.get("path") != str(executor_path) \
            or executor.get("sha256") != executor_sha:
        raise BuilderV2Error("Home parent receipt executor binding differs")
    execution = home.get("execution")
    required_cover = {"metadata/stat preflight", "same-parent reservation",
                      "v34 child copy/hash/worker/evaluator"}
    covered = set(execution.get("hard_wall_covers", [])) if isinstance(execution, Mapping) else set()
    if not required_cover.issubset(covered):
        raise BuilderV2Error("Home parent receipt lacks post-reservation execution scope")
    if home.get("model_invoked") is not False or home.get("cfd_invoked") is not False:
        raise BuilderV2Error("Home parent receipt model/CFD boundary is not closed")
    parent = home.get("parent")
    if not isinstance(parent, Mapping) or parent.get("same_parent_ledger") is not True:
        raise BuilderV2Error("Home parent receipt same-parent ledger binding is missing")
    attempt_id = parent.get("attempt_id")
    if not isinstance(attempt_id, str) or not attempt_id:
        raise BuilderV2Error("Home parent receipt parent attempt_id is missing")
    accounting = home.get("accounting")
    if not isinstance(accounting, Mapping) or accounting.get("reservation_applied") is not True:
        raise BuilderV2Error("Home parent receipt reservation binding is missing")
    if accounting.get("charge_status_at_report_write") != "pending_same_parent_charge":
        raise BuilderV2Error("Home parent receipt is not the pre-charge immutable receipt")
    if accounting.get("same_parent_ledger") not in {None, True}:
        raise BuilderV2Error("Home parent receipt accounting is not same-ledger")
    if accounting.get("attempt_id") not in {None, attempt_id}:
        raise BuilderV2Error("Home parent receipt accounting attempt differs")
    return home, {"attempt_id": attempt_id, "charge_id": _charge_id_from_home(home)}


def _returned_charge(value: Mapping[str, Any]) -> Mapping[str, Any]:
    charge = value.get("charge")
    if not isinstance(charge, Mapping):
        raise BuilderV2Error("returned parent report charge summary is missing")
    if charge.get("ledger_mutated") is not True:
        raise BuilderV2Error("returned parent report does not prove a ledger mutation")
    row = charge.get("charge")
    if not isinstance(row, Mapping):
        raise BuilderV2Error("returned parent report charge row is missing")
    return row


def _validate_returned_report(path: Path, *, home_path: Path, parent_path: Path,
                              parent_sha: str, expected_attempt: str,
                              expected_charge: str, home: Mapping[str, Any]) -> tuple[dict[str, Any], Mapping[str, Any]]:
    _, returned = _json(path, "returned parent report")
    if returned.get("schema") != PARENT_REPORT_SCHEMA:
        raise BuilderV2Error(f"returned parent report schema differs: {returned.get('schema')!r}")
    if returned.get("status") != "COMPLETED_PARENT_EXECUTOR_RAW_TYPED_LABEL_UNKNOWN":
        raise BuilderV2Error(f"returned parent report is not completed: {returned.get('status')!r}")
    if returned.get("report_path") != str(home_path):
        raise BuilderV2Error("returned parent report does not bind the Home receipt path")
    if returned.get("request_sha256") != parent_sha:
        raise BuilderV2Error("returned parent report request SHA differs")
    if returned.get("ledger_mutated") is not True:
        raise BuilderV2Error("returned parent report ledger_mutated is not true")
    if returned.get("model_invoked") is not False or returned.get("cfd_invoked") is not False:
        raise BuilderV2Error("returned parent report model/CFD boundary is not closed")
    row = _returned_charge(returned)
    if row.get("id") != expected_charge:
        raise BuilderV2Error("returned charge ID differs from Home receipt")
    if row.get("parent_attempt_id") != expected_attempt:
        raise BuilderV2Error("returned charge parent attempt differs from Home receipt")
    if row.get("status") != "completed":
        raise BuilderV2Error("returned charge row is not completed")
    # These values are all emitted by parent-v3 after the Home receipt is
    # written.  Comparing them to the immutable receipt catches mixing a
    # receipt and returned summary from different attempts without reading any
    # payload artifact.
    filesystem = home.get("filesystem")
    if isinstance(filesystem, Mapping):
        for returned_key, home_key in (("external_bytes", "external_bytes_before_parent_charge"),
                                       ("trace_bytes", "trace_bytes"),
                                       ("copy_hash_bytes", "copy_hash_bytes")):
            expected = filesystem.get(home_key)
            actual = returned.get(returned_key)
            if isinstance(expected, int) and isinstance(actual, int) and expected != actual:
                raise BuilderV2Error(f"returned {returned_key} differs from Home receipt")
    if isinstance(returned.get("home_bytes"), int) and returned["home_bytes"] != home_path.stat().st_size:
        raise BuilderV2Error("returned home_bytes differs from the immutable Home receipt stat")
    return returned, row


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser()
    if target.exists() or target.is_symlink():
        raise BuilderV2Error(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    return target


def build_terminal_inputs_split(*, executor_request: Path | str, parent_request: Path | str,
                                preflight: Path | str, parent_receipt: Path | str,
                                returned_parent_report: Path | str, worker_report: Path | str,
                                source_contract: Path | str, output_root: Path | str,
                                namespace_root: Path | str, static_output: Path | str,
                                manifest_output: Path | str, pinned_sources: Sequence[str],
                                artifact_bindings: Sequence[str]) -> dict[str, Any]:
    executor_path, executor = _json(executor_request, "executor request")
    parent_path, parent = _json(parent_request, "parent request")
    preflight_path, preflight_value = _json(preflight, "V50 metadata preflight")
    request_sha = _validate_common_inputs(executor_path, executor, parent_path, parent,
                                          preflight_path, preflight_value)
    home_path = _file(parent_receipt, "Home parent receipt")
    home, home_ids = _validate_home_receipt(
        home_path, parent_path=parent_path, executor_path=executor_path,
        parent_sha=request_sha["parent_sha"], executor_sha=request_sha["executor_sha"])
    returned_path = _file(returned_parent_report, "returned parent report")
    returned, charge_row = _validate_returned_report(
        returned_path, home_path=home_path, parent_path=parent_path,
        parent_sha=request_sha["parent_sha"], expected_attempt=home_ids["attempt_id"],
        expected_charge=home_ids["charge_id"], home=home)
    out_root = Path(output_root).expanduser().resolve()
    ns_root = Path(namespace_root).expanduser().resolve()
    if not out_root.is_dir() or not ns_root.is_dir():
        raise BuilderV2Error("fresh output/namespace roots must exist after the producer run")
    worker_path = _file(worker_report, "native worker report")
    try:
        worker, products = V1._worker_report(worker_path, output_root=out_root, namespace_root=ns_root)
    except Exception as error:
        raise BuilderV2Error(str(error)) from error
    explicit: dict[str, dict[str, Any]] = {}
    for raw in artifact_bindings:
        if "=" not in raw:
            raise BuilderV2Error("--artifact must be role=/absolute/path")
        role, raw_path = raw.split("=", 1)
        if not role or role in explicit:
            raise BuilderV2Error(f"malformed/duplicate artifact role: {role}")
        try:
            explicit[role] = V1._small_artifact(raw_path, role, output_root=out_root, namespace_root=ns_root)
        except Exception as error:
            raise BuilderV2Error(str(error)) from error
    required_explicit = {"current_runtime_view", "relocated_v15_request", "engine_report"}
    missing = required_explicit.difference(explicit)
    if missing:
        raise BuilderV2Error(f"terminal manifest needs explicit artifact roles: {sorted(missing)}")
    contract_path = _file(source_contract, "source contract")
    try:
        source_contract_binding = V1._small_artifact(contract_path, "source_contract",
                                                     output_root=out_root, namespace_root=ns_root)
        identity = V1._source_identity(executor_path, contract_path)
        pinned = V1._pinned_code_bindings(pinned_sources)
    except Exception as error:
        raise BuilderV2Error(str(error)) from error
    home_physical = _sha_file(home_path, "Home parent receipt")
    returned_physical = _sha_file(returned_path, "returned parent report")
    preflight_physical = _sha_file(preflight_path, "V50 metadata preflight")
    static: dict[str, Any] = {
        "schema": STATIC_SCHEMA, "status": STATIC_STATUS, "phase": STATIC_PHASE,
        "static_content_verified": True,
        "verification_mode": "DERIVED_FROM_HOME_RECEIPT_AND_RETURNED_PARENT_REPORT",
        "instrumented_receipt": False, "derived_sidecar": True,
        "request": str(parent_path), "executor": str(executor_path),
        "request_file_sha256": request_sha["parent_sha"],
        "executor_file_sha256": request_sha["executor_sha"],
        "same_parent_ledger": True, "parent_attempt_id": home_ids["attempt_id"],
        "charge_id": home_ids["charge_id"],
        "completed_parent_report": {
            "home_receipt": {"path": str(home_path), "sha256": home_physical},
            "returned_report": {"path": str(returned_path), "sha256": returned_physical},
            "home_receipt_status": home.get("status"),
            "returned_report_status": returned.get("status"),
            "returned_charge_status": charge_row.get("status"),
            "returned_ledger_mutated": returned.get("ledger_mutated"),
        },
        "preflight_basis": {"path": str(preflight_path), "sha256": preflight_physical,
                             "schema": "ds02.stage2.root.v50-metadata-preflight.v1"},
        "derivation": {
            "statement": "The Home receipt is the immutable pre-charge parent execution record; the returned parent report proves the subsequent same-ledger charge. They are independently bound and are not merged into an instrumented receipt.",
            "home_receipt_charge_status_at_write": home.get("accounting", {}).get("charge_status_at_report_write"),
            "returned_charge_id": charge_row.get("id"),
            "returned_charge_parent_attempt_id": charge_row.get("parent_attempt_id"),
            "original_instrumented_receipt_present": False,
            "payload_rehashed_by_this_builder": False,
        },
        "verified_source_hashes": {
            **{key: dict(value) for key, value in pinned.items()},
            "executor_request": {"path": str(executor_path), "sha256": request_sha["executor_sha"]},
            "parent_request": {"path": str(parent_path), "sha256": request_sha["parent_sha"]},
            "v50_preflight": {"path": str(preflight_path), "sha256": preflight_physical},
            "home_parent_receipt": {"path": str(home_path), "sha256": home_physical},
            "returned_parent_report": {"path": str(returned_path), "sha256": returned_physical},
            "source_contract": source_contract_binding,
        },
        "qualification": dict(UNKNOWN),
    }
    static["sha256"] = canonical_sha(static)
    static_path = _write_new(static_output, static)
    artifacts = {
        "worker_report": V1._small_artifact(worker_path, "worker_report", output_root=out_root, namespace_root=ns_root),
        "raw_converter_report": products["converter"], "typed_hdf5": products["typed"],
        "v15_result": products["v15"], "v16_result": products["v16"],
        **explicit, "source_contract": source_contract_binding,
    }
    request_bindings = {
        "executor": {"path": str(executor_path), "physical_sha256": request_sha["executor_sha"]},
        "parent": {"path": str(parent_path), "physical_sha256": request_sha["parent_sha"]},
        "root_metadata_verification": {"path": str(preflight_path), "physical_sha256": preflight_physical},
    }
    manifest: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA, "status": "COMPLETED_DEVELOPMENT_UNKNOWN",
        "request_bindings": request_bindings, "source_identity": identity,
        "parent_attempt_id": home_ids["attempt_id"], "charge_id": home_ids["charge_id"],
        "terminal": {
            "parent_guard_completed": True, "reservation_closed": True,
            "charge_closed": True, "ledger_mutated": True,
            "payload_read_after_reservation": True, "model_invoked": False,
            "cfd_invoked": False, "derived_static_attestation": True,
            "instrumented_static_receipt": False,
        },
        "parent_terminal_evidence": {
            "home_receipt": {"path": str(home_path), "sha256": home_physical},
            "returned_report": {"path": str(returned_path), "sha256": returned_physical},
            "returned_charge": {"id": charge_row.get("id"), "status": charge_row.get("status"),
                                "ledger_mutated": returned.get("ledger_mutated")},
        },
        "source_contract": {"path": str(contract_path), "sha256": source_contract_binding["sha256"]},
        "artifacts": artifacts,
        "parent_static_content_verification": {
            "path": str(static_path), "physical_sha256": _sha_file(static_path, "static attestation"),
            "status": STATIC_STATUS, "phase": STATIC_PHASE,
        },
        "limitations": [
            "The static-content result is a derived sidecar from two real parent-v3 records, not an instrumented receipt written by the historical parent.",
            "Payload artifact SHA values are producer-declared and are not rehashed by this source-only builder.",
            "QI/QN/QE remain UNKNOWN; a fresh V10 semantic proof and evaluator guard are still required.",
        ],
        "qualification": dict(UNKNOWN),
    }
    manifest["sha256"] = canonical_sha(manifest)
    manifest_path = _write_new(manifest_output, manifest)
    return {"manifest": str(manifest_path), "manifest_sha256": manifest["sha256"],
            "static_attestation": str(static_path), "static_attestation_sha256": static["sha256"],
            "derived_sidecar": True, "payload_read": False, "qualification": dict(UNKNOWN)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("executor-request", "parent-request", "preflight", "parent-receipt",
                 "returned-parent-report", "worker-report", "source-contract", "output-root",
                 "namespace-root", "static-output", "manifest-output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--pinned-source", action="append", default=[])
    parser.add_argument("--artifact", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        result = build_terminal_inputs_split(
            executor_request=args.executor_request, parent_request=args.parent_request,
            preflight=args.preflight, parent_receipt=args.parent_receipt,
            returned_parent_report=args.returned_parent_report, worker_report=args.worker_report,
            source_contract=args.source_contract, output_root=args.output_root,
            namespace_root=args.namespace_root, static_output=args.static_output,
            manifest_output=args.manifest_output, pinned_sources=args.pinned_source,
            artifact_bindings=args.artifact)
    except (BuilderV2Error, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"V50 split source-only post-terminal builder: {error}", file=__import__("sys").stderr)
        return 2
    print(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
