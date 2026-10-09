#!/usr/bin/env python3
"""Build the additive ROOT276 F6 support request.

V5 used ``sentinel_id`` as a fallback physical identity.  That is unsafe for
the two spatial producer receipts whose request omitted ``physical_case_id``.
V6 keeps the six producer cases separate and records the actual request
``case_id``/``attempt_id``/input closure.  A missing physical identity or an
unjoinable generation-input hash makes only that case UNKNOWN; it is never
filled from a label.  The actual V5 worker is called only for cases whose
metadata identity and explicit sentinel/grid/domain mapping are closed.

This builder performs bounded metadata reads and stat-only deferred-input
preparation.  It does not open BI4/VTK payloads or launch a task.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
V5_BUILDER = HERE / "stage2_f6_initial_native_support_audit_request_v5.py"
V5_WORKER = HERE / "stage2_f6_initial_native_support_audit_v5.py"
V6_WORKER = HERE / "stage2_f6_initial_native_support_audit_v6.py"
OWNER_PROOF_DEFAULT = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F6_CONTINUOUS_OWNER_GEOMETRY_AUDIT_V1_ACTUAL_ROOT_VERIFICATION_252.json"
RIGID_PROOF_DEFAULT = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F6_OWNER_RIGID_METADATA_V1_ACTUAL_ROOT_VERIFICATION_244.json"
PRIOR_V5_FAILURE_DEFAULT = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F6_INITIAL_NATIVE_SUPPORT_V5_ACTUAL_PRODUCER_IDENTITY_FAILURE_ROOT_VERIFICATION_272.json"
CONTRACT = HERE / "stage2_f6_initial_native_support_audit_contract_v6.json"

REQUEST_SCHEMA = "ds02.request.v1"
MANIFEST_SCHEMA = "ds02.stage2.f6-initial-native-support-manifest.v6"
VARIANT_SCHEMA = "ds02.stage2.f6-initial-native-support-request.v6"
STATUS = "READY_FOR_PARENT_V8_F6_INITIAL_NATIVE_SUPPORT_ROOT276_V6_PARTIAL_IDENTITY"
MAX_SMALL = 16 * 1024 * 1024
STAT_FIELDS = ("dev", "ino", "bytes", "mtime_ns", "ctime_ns")

MAPPING = {
    ("F6-S1", "source_current"): {
        "domain_label": "F6-S1 current angular release omega=.95 source product",
        "source_authority": "ROOT244 rigid metadata + ROOT252 explicit continuous owner",
    },
    ("F6-S1", "coarse"): {
        "domain_label": "F6-S1 coarse spatial generated product",
        "source_authority": "ROOT244/252 source owner edges; producer physical identity required",
    },
    ("F6-S1", "fine"): {
        "domain_label": "F6-S1 fine spatial generated product",
        "source_authority": "ROOT244/252 source owner edges; producer physical identity required",
    },
    ("F6-S2", "source_current"): {
        "domain_label": "F6-S2 current angular release omega=2.0 source product",
        "source_authority": "ROOT244 rigid metadata + ROOT252 explicit continuous owner",
    },
    ("F6-S2", "coarse"): {
        "domain_label": "F6-S2 coarse spatial generated product",
        "source_authority": "ROOT244/252 source owner edges; producer physical identity required",
    },
    ("F6-S2", "fine"): {
        "domain_label": "F6-S2 fine spatial generated product",
        "source_authority": "ROOT244/252 source owner edges; producer physical identity required",
    },
}


class BuildFailure(RuntimeError):
    pass


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise BuildFailure(f"cannot load source module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"dev": int(value.st_dev), "ino": int(value.st_ino), "bytes": int(value.st_size),
            "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns)}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _record(path: Path, label: str, *, parse_json: bool = False) -> tuple[Any, dict[str, Any]]:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not a regular file: {path}")
    before = _stat(path)
    if before["bytes"] > MAX_SMALL:
        raise BuildFailure(f"{label} exceeds bounded metadata read: {path}")
    digest = hashlib.sha256()
    chunks: list[bytes] = []
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
            chunks.append(block)
    after = _stat(path)
    if before != after:
        raise BuildFailure(f"{label} changed while read: {path}")
    value: Any = None
    if parse_json:
        try:
            value = json.loads(b"".join(chunks).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BuildFailure(f"{label} is not JSON: {path}") from exc
        if not isinstance(value, dict):
            raise BuildFailure(f"{label} JSON must be an object: {path}")
    return value, {"path": str(path), "label": label, "bytes": after["bytes"],
                   "sha256": digest.hexdigest(), "stat": after, "stable_read": True,
                   "payload_read_by_builder": False}


def _canonical(value: dict[str, Any]) -> str:
    body = copy.deepcopy(value)
    body.pop("sha256", None)
    body.pop("request_sha256", None)
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def _actual_identity(receipt: dict[str, Any], case: dict[str, Any], mapping: dict[str, Any]) -> dict[str, Any]:
    request = receipt.get("request") if isinstance(receipt.get("request"), dict) else {}
    actual_case = request.get("case_id")
    actual_attempt = request.get("attempt_id") or request.get("attempt_root") or receipt.get("attempt_id")
    actual_physical = request.get("physical_case_id")
    output_root = receipt.get("output_root")
    xml_path = str((case.get("xml") or {}).get("path", ""))
    input_files = request.get("input_files")
    input_hashes = request.get("input_hashes", request.get("input_sha256"))
    has_case = isinstance(actual_case, str) and bool(actual_case)
    has_attempt = isinstance(actual_attempt, str) and bool(actual_attempt)
    has_output = isinstance(output_root, str) and bool(output_root)
    has_mapping = isinstance(mapping, dict) and bool(mapping.get("domain_label"))
    # A generated XML is a producer output for the spatial receipts.  Its
    # actual path/hash is still retained; absence from an old request's input
    # hash map is an explicit UNKNOWN rather than a guessed closure.
    input_hash_status = "PASS_REQUEST_INPUT_HASH_MAP" if isinstance(input_hashes, dict) and isinstance(input_files, list) else "UNKNOWN_REQUEST_INPUT_HASH_SCHEMA"
    physical_status = "PASS_ACTUAL_PRODUCER_REQUEST" if isinstance(actual_physical, str) and actual_physical else "UNKNOWN_PHYSICAL_CASE_ID_OMITTED"
    identity_status = "PASS" if has_case and has_attempt and has_output and has_mapping and physical_status.startswith("PASS") and input_hash_status.startswith("PASS") else "UNKNOWN"
    return {
        "status": identity_status,
        "physical_case_id": actual_physical if isinstance(actual_physical, str) and actual_physical else None,
        "case_id": actual_case if isinstance(actual_case, str) and actual_case else None,
        "attempt_id": actual_attempt if isinstance(actual_attempt, str) and actual_attempt else None,
        "output_root": output_root if isinstance(output_root, str) else None,
        "source_xml_path": xml_path,
        "request_input_files": input_files if isinstance(input_files, list) else None,
        "request_input_hashes": input_hashes if isinstance(input_hashes, dict) else None,
        "physical_case_status": physical_status,
        "input_hash_status": input_hash_status,
        "required_fields": ["request.case_id", "request.attempt_id or receipt.attempt_id", "receipt.output_root", "request.physical_case_id", "request.input_files", "request.input_hashes", "explicit domain mapping"],
        "missing_fields": [
            name for name, ok in (
                ("request.case_id", has_case),
                ("request.attempt_id", has_attempt),
                ("receipt.output_root", has_output),
                ("request.physical_case_id", physical_status.startswith("PASS")),
                ("request.input_files/input_hashes", input_hash_status.startswith("PASS")),
                ("domain mapping", has_mapping),
            ) if not ok
        ],
    }


def _prepare_v5(args: argparse.Namespace) -> tuple[Any, Any]:
    """Build V5 into a disposable directory, then normalize it additively."""
    v5 = _load_module(V5_BUILDER, "stage2_f6_request_v5_source")
    with tempfile.TemporaryDirectory(prefix="root276-v5-source-") as td:
        root = Path(td)
        ns = argparse.Namespace(
            proof=args.proof,
            owner_proof=args.owner_proof,
            manifest_output=root / "v5-manifest.json",
            output_request=root / "v5-request.json",
            case_id="F6_INITIAL_NATIVE_SUPPORT_AUDIT_ROOT276_V6_SOURCE",
            attempt_id="f6-initial-native-support-audit-root276-v6-source-001",
        )
        v5.build(ns)
        manifest = json.loads(ns.manifest_output.read_text(encoding="utf-8"))
        request = json.loads(ns.output_request.read_text(encoding="utf-8"))
    return manifest, request


def build(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest, request = _prepare_v5(args)
    owner_proof_record = manifest.get("owner_proof")
    rigid_proof_record = manifest.get("proof")
    if not isinstance(owner_proof_record, dict) or not isinstance(rigid_proof_record, dict):
        raise BuildFailure("V5 manifest did not carry ROOT244/ROOT252 proof records")
    cases: list[dict[str, Any]] = []
    identity_index: list[dict[str, Any]] = []
    for original in manifest.get("cases", []):
        case = copy.deepcopy(original)
        sid = str(case.get("sentinel_id")); grid = str(case.get("grid"))
        mapping = copy.deepcopy(MAPPING.get((sid, grid), {"domain_label": "UNKNOWN_UNMAPPED_SENTINEL_GRID", "source_authority": "UNKNOWN"}))
        receipt_path = Path(str(case.get("producer_receipt", {}).get("path", "")))
        receipt, receipt_record = _record(receipt_path, f"{sid}/{grid} actual producer receipt", parse_json=True)
        identity = _actual_identity(receipt, case, mapping)
        # Never retain V5's sentinel fallback as an authority.  The worker
        # only sees an actual physical ID when the receipt request supplied it.
        case["physical_case_id"] = identity["physical_case_id"]
        case["producer_case_id"] = identity["case_id"]
        case["producer_attempt_id"] = identity["attempt_id"]
        case["identity_status"] = identity["status"]
        case["producer_identity_v6"] = identity
        case["domain_mapping_v6"] = {
            "sentinel_id": sid, "grid": grid, **mapping,
            "owner_proof": owner_proof_record,
            "rigid_proof": rigid_proof_record,
            "physical_case_authority": "actual producer request.physical_case_id only; no sentinel fallback",
        }
        case["producer_receipt_v6"] = receipt_record
        identity_index.append({"sentinel_id": sid, "grid": grid, "identity": identity, "mapping": case["domain_mapping_v6"]})
        cases.append(case)
    manifest["schema"] = MANIFEST_SCHEMA
    manifest["status"] = "PREPARED_NOT_RUN_ROOT276_F6_INITIAL_NATIVE_SUPPORT_AUDIT_V6"
    manifest["cases"] = cases
    manifest["identity_index_v6"] = identity_index
    manifest["identity_policy"] = {
        "physical_case_id_fallback": "FORBIDDEN",
        "missing_identity_case": "UNKNOWN_CASE_ONLY",
        "partial_report": True,
        "failed_case_is_not_success": True,
        "source_xml_and_generation_inputs": "actual producer receipt request plus recorded generated XML path/hash",
        "owner_edges": "ROOT244 rigid proof and ROOT252 continuous-owner proof are required sidecar references",
    }
    manifest["source_binding_v6"] = {
        "root244_rigid_proof": rigid_proof_record,
        "root252_owner_proof": owner_proof_record,
        "mapping_sidecar": "sentinel/grid/domain mapping is explicit and cannot infer physical identity",
        "native_field_scope": "POSITION_ONLY_INITIAL_SUPPORT; optional Vel/Rhop/Mass remain UNKNOWN when absent",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0},
    }
    # Keep the actual ROOT272 V5 failure as an immutable predecessor.  The
    # imported V5 manifest still retains the older ROOT267 failure; ROOT276
    # must also explain the new missing-physical-identity boundary.
    prior_v5_record = None
    prior_v5_request_record = None
    if PRIOR_V5_FAILURE_DEFAULT.is_file():
        prior_v5, prior_v5_record = _record(PRIOR_V5_FAILURE_DEFAULT, "ROOT272 V5 failure proof", parse_json=True)
        prior_request_path = prior_v5.get("request")
        if isinstance(prior_request_path, str) and Path(prior_request_path).is_file():
            _, prior_v5_request_record = _record(Path(prior_request_path), "ROOT272 V5 failed request", parse_json=True)
            if prior_v5.get("request_sha256") and prior_v5["request_sha256"] != prior_v5_request_record["sha256"]:
                raise BuildFailure("ROOT272 proof/request SHA join failed")
        manifest["prior_v5_failure_proof"] = prior_v5_record
        manifest["prior_v5_failure_request"] = prior_v5_request_record
    else:
        manifest["prior_v5_failure_proof"] = {"path": str(PRIOR_V5_FAILURE_DEFAULT), "status": "PENDING_PRIMARY_ROOT272_PROOF"}
    manifest["qualification"] = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}
    manifest["builder_v6"] = {"path": str(HERE / Path(__file__).name), "sha256": _sha256(HERE / Path(__file__).name)}

    request = copy.deepcopy(request)
    request["variant_schema"] = VARIANT_SCHEMA
    request["status"] = STATUS
    request["request_id"] = "f6-initial-native-support-audit-root276-v6"
    request["case_id"] = args.case_id
    request["attempt_id"] = args.attempt_id
    request["command"] = [
        str(v5_path(args).get("python", "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")),
        "-B", str(V6_WORKER), "--manifest", "{attempt_root}/inputs/f6_initial_native_support_manifest_v6.json",
        "--attempt-root", "{attempt_root}", "--output", "{attempt_root}/observer/f6_initial_native_support_audit_v6.json",
    ]
    old_manifest_path = str((request.get("manifest") or {}).get("path", ""))
    request["manifest"] = {"schema": MANIFEST_SCHEMA, "status": manifest["status"], "path": "{attempt_root}/inputs/f6_initial_native_support_manifest_v6.json", "sha256": "PARENT_ATTEMPT_MANIFEST_SHA"}
    # V5 was built in a disposable directory.  Its temporary manifest is a
    # build artifact, not a valid runtime input; remove that path before
    # adding the parent-attempt manifest placeholder.
    request["input_files"] = [
        path for path in request.get("input_files", [])
        if str(path) != old_manifest_path
    ]
    request["input_files"] = list(dict.fromkeys(list(request["input_files"]) + [str(HERE / Path(__file__).name), str(V6_WORKER), str(CONTRACT)]))
    request["input_sha256"] = {path: value for path, value in request.get("input_sha256", {}).items()} if isinstance(request.get("input_sha256"), dict) else {}
    request["input_records"] = {
        path: value for path, value in request.get("input_records", {}).items()
        if str(path) != old_manifest_path
    } if isinstance(request.get("input_records"), dict) else {}
    for path in (HERE / Path(__file__).name, V6_WORKER, CONTRACT):
        if path.is_file():
            path_text = str(path)
            request["input_sha256"][path_text] = _sha256(path)
            _, record = _record(path, f"ROOT276 V6 source {path.name}")
            request["input_records"][path_text] = record
    for record in (prior_v5_record, prior_v5_request_record):
        if isinstance(record, dict) and record.get("path"):
            path_text = str(record["path"])
            request["input_files"].append(path_text)
            request["input_sha256"][path_text] = str(record.get("sha256"))
            request["input_records"][path_text] = record
    request["input_files"] = list(dict.fromkeys(request["input_files"]))
    request["deferred_input_records"] = manifest.get("deferred_input_records", [])
    request["identity_index_v6"] = identity_index
    request["prior_v5_failure_proof"] = prior_v5_record or manifest["prior_v5_failure_proof"]
    request["prior_v5_failure_request"] = prior_v5_request_record
    request["partial_report_policy"] = {
        "unknown_case_output": "one per-case UNKNOWN entry with actual missing fields",
        "valid_case_output": "V5 support/VTK/position audit only after V6 identity gate",
        "never": ["fallback physical_case_id", "case-name substitution", "failure->success", "scientific Q credit"],
    }
    request["source_binding"] = manifest["source_binding_v6"]
    request["qualification"] = manifest["qualification"]
    request["launch_disabled"] = True
    request["execution_allowed"] = False
    request["solver_started"] = False
    request["native_payload_read"] = False
    request["hdf5_read"] = False
    request["ledger_mutation"] = False
    request["sha256"] = _canonical(request)
    return manifest, request


def v5_path(args: argparse.Namespace) -> dict[str, str]:
    # Keep the literal venv path in argv[0]; no resolved system Python.
    return {"python": "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"}


def _self_test() -> None:
    base_case = {"xml": {"path": "/tmp/generated.xml"}}
    mapping = MAPPING[("F6-S1", "coarse")]
    completed = {"status": "completed", "returncode": 0, "output_root": "/tmp/attempt",
                 "request": {"case_id": "generated-case", "attempt_id": "attempt-1",
                              "physical_case_id": "physical-case", "input_files": ["x"], "input_hashes": {"x": "a"}}}
    missing_physical = copy.deepcopy(completed)
    del missing_physical["request"]["physical_case_id"]
    good = _actual_identity(completed, base_case, mapping)
    bad = _actual_identity(missing_physical, base_case, mapping)
    assert good["status"] == "PASS" and good["physical_case_id"] == "physical-case"
    assert bad["status"] == "UNKNOWN" and bad["physical_case_id"] is None
    assert "request.physical_case_id" in bad["missing_fields"]
    malformed = copy.deepcopy(completed)
    malformed["request"]["input_hashes"] = ["x"]
    assert _actual_identity(malformed, base_case, mapping)["input_hash_status"].startswith("UNKNOWN")
    print("PASS_F6_INITIAL_NATIVE_SUPPORT_REQUEST_V6_SELFTEST")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--self-test", action="store_true")
    group.add_argument("--build", action="store_true")
    parser.add_argument("--proof", type=Path, default=RIGID_PROOF_DEFAULT)
    parser.add_argument("--owner-proof", type=Path, default=OWNER_PROOF_DEFAULT)
    parser.add_argument("--manifest-output", type=Path)
    parser.add_argument("--output-request", type=Path)
    parser.add_argument("--case-id", default="F6_INITIAL_NATIVE_SUPPORT_AUDIT_ROOT276_V6")
    parser.add_argument("--attempt-id", default="f6-initial-native-support-audit-root276-v6-001")
    args = parser.parse_args()
    if args.self_test:
        _self_test(); return 0
    if args.manifest_output is None or args.output_request is None:
        parser.error("--manifest-output and --output-request are required with --build")
    try:
        manifest, request = build(args)
        for path, value in ((args.manifest_output, manifest), (args.output_request, request)):
            path = path.expanduser().absolute()
            if path.exists() or path.is_symlink():
                raise BuildFailure(f"refusing overwrite: {path}")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        print(json.dumps({"status": request["status"], "manifest": str(args.manifest_output.absolute()), "request": str(args.output_request.absolute()), "sha256": request["sha256"], "payload_read": False}, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"FAILED_F6_INITIAL_NATIVE_SUPPORT_REQUEST_V6: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
