#!/usr/bin/env python3
"""Audit the remaining F3 formal/source admission gap without authorizing it.

The v1 capability validator and the strict held-FD verifier already cover the
shape of a future synthetic capability envelope.  This sidecar audits the
repository around those contracts: whether the current manifest and
production reader bind them, whether source measurement has runtime
authority, and whether producer/broker/worker identity and formal release are
actually present.  It deliberately does not implement another envelope
validator.

Only allow-listed JSON and Python source files are read.  No HDF5/FD is
opened, fs-verity is not invoked, no production module is imported, and no
worker, GPU, solver, queue, registry, ledger, manifest, or gate is started or
modified.  A report is diagnostic even when all static markers are present:
``formal_eligible`` is always false and ``qualification_credit`` is always
zero.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping


REPORT_SCHEMA = "core.f3.formal_admission_closure_audit.v2"
AUDIT_VERSION = "v2"

MANIFEST_REL = Path("campaigns/core-v1/f3-dataset-v2.json")
REGISTRY_REL = Path("campaigns/core-v1/registry.json")

BASE_CONTRACT_REL = Path("scripts/f3_formal_reader_capability_contract_v1.py")
BASE_TEST_REL = Path("tests/test_f3_formal_reader_capability_contract_v1.py")
STRICT_CONTRACT_REL = Path("scripts/f3_formal_reader_strict_capability_contract_v1.py")
STRICT_TEST_REL = Path("tests/test_f3_formal_reader_strict_capability_contract_v1.py")
DATASET_REL = Path("scripts/core_dataset.py")
FSVERITY_REL = Path("scripts/core_fsverity.py")
LEARNING_REL = Path("scripts/core_learning.py")
CAMPAIGN_REL = Path("scripts/core_campaign.py")

MANIFEST_CAPABILITY_FIELDS = frozenset({
    "capability_contract", "capability_contract_ref", "formal_reader_capability",
    "formal_reader_capability_ref", "admission_capability", "admission_capability_ref",
    "descriptor_bundle", "source_trust", "source_snapshot", "source_measurement",
    "source_measurement_ref", "producer_identity", "broker_identity", "worker_identity",
    "identities", "session_nonce", "source_snapshot_nonce", "attempt_nonce",
})
CASE_RUNTIME_FIELDS = frozenset({
    "fd_identity", "fd_token", "source_measurement", "measurement", "source_snapshot_nonce",
    "session_nonce", "producer_identity", "broker_identity", "worker_identity",
})

BASE_MARKERS = (
    "def validate_capability_contract",
    '"authorizes_formal": False',
    '"formal_eligible": False',
    '"qualification_credit": 0',
    '"opens_source_fd": False',
)
STRICT_MARKERS = (
    "def validate_strict_capability_contract",
    'bundle.get("access_mode") == "held_fd_only"',
    "attempt_history",
    '"formal_eligible": False',
    '"qualification_credit": 0',
    '"opens_source_fd": False',
)
BASE_TEST_MARKERS = ("test_complete_synthetic_envelope_is_structural_only_and_non_authorizing",)
STRICT_TEST_MARKERS = ("test_complete_strict_envelope_checks_bindings_but_never_authorizes",)
DATASET_MARKERS = (
    "snapshot_fds=None",
    "snapshot_measurements=None",
    "self.formal_eligible = False",
    "caller-provided measurements are",
    "still not authenticated capabilities",
    "producer or prove immutability",
)
FSVERITY_MARKERS = (
    "def verify_fd(",
    "authenticate who produced a file",
    "mint a capability",
)
LEARNING_MARKERS = (
    "def _manifest_formal_release(dataset):",
    "V13 verified-reader capability",
    "formal training requires a V13 verified-reader capability",
    "formal Core evaluation requires a V13 verified-reader capability",
)
CAMPAIGN_MARKERS = (
    "def _reject_nonformal_or_nonroot(payload, label):",
    'receipt.get("formal_eligible") is not True',
    'config.get("manifest_formal_release") is not True',
    '"can_finalize": all(checks.values())',
)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _relative(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _file_record(root: Path, relative: Path, markers: tuple[str, ...] = ()) -> tuple[dict[str, Any], str]:
    path = root / relative
    record: dict[str, Any] = {
        "path": relative.as_posix(),
        "exists": False,
        "bytes": None,
        "sha256": None,
        "marker_checks": {marker: False for marker in markers},
        "all_markers_present": False if markers else False,
    }
    try:
        raw = path.read_bytes()
    except (OSError, ValueError) as error:
        record["read_error"] = type(error).__name__
        return record, ""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        record["read_error"] = type(error).__name__
        return record, ""
    record.update({
        "exists": True,
        "bytes": len(raw),
        "sha256": _sha256(raw),
        "marker_checks": {marker: marker in text for marker in markers},
    })
    record["all_markers_present"] = bool(markers) and all(record["marker_checks"].values())
    return record, text


def _json_record(root: Path, relative: Path) -> tuple[dict[str, Any], Any]:
    record, text = _file_record(root, relative)
    payload: Any = None
    if record["exists"]:
        try:
            payload = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            record["json_error"] = type(error).__name__
    record["json_object"] = isinstance(payload, dict)
    return record, payload


def _function_body(text: str, name: str) -> str:
    match = re.search(rf"^def {re.escape(name)}\b", text, flags=re.MULTILINE)
    if match is None:
        return ""
    next_function = re.search(r"^def \w+\b", text[match.end():], flags=re.MULTILINE)
    end = match.end() + next_function.start() if next_function else len(text)
    return text[match.start():end]


def _manifest_inventory(root: Path) -> tuple[dict[str, Any], Any]:
    record, payload = _json_record(root, MANIFEST_REL)
    inventory: dict[str, Any] = {
        "file": record,
        "valid_json_object": isinstance(payload, dict),
        "top_level_keys": sorted(payload) if isinstance(payload, dict) else [],
        "declared_formal_release": payload.get("formal_release") is True
        if isinstance(payload, dict) else False,
        "case_count": 0,
        "declared_case_count": payload.get("case_count") if isinstance(payload, dict) else None,
        "case_count_matches": False,
        "source_hash_byte_metadata": False,
        "descriptor_metadata": False,
        "runtime_capability_fields": [],
        "case_runtime_field_counts": {},
        "declared_source_manifest_sha256": payload.get("source_manifest_sha256")
        if isinstance(payload, dict) else None,
    }
    if not isinstance(payload, dict):
        return inventory, payload
    cases = payload.get("cases")
    rows = [row for row in cases if isinstance(row, Mapping)] if isinstance(cases, list) else []
    inventory["case_count"] = len(rows)
    inventory["case_count_matches"] = payload.get("case_count") == len(rows) and bool(rows)
    inventory["source_hash_byte_metadata"] = bool(rows) and all(
        isinstance(row.get("hdf5"), str) and bool(row["hdf5"].strip())
        and isinstance(row.get("sha256"), str) and len(row["sha256"]) == 64
        and isinstance(row.get("bytes"), int) and not isinstance(row["bytes"], bool)
        and row["bytes"] > 0 for row in rows
    )
    inventory["descriptor_metadata"] = bool(rows) and all(
        isinstance(row.get("known_inputs_ref"), Mapping)
        and all(
            isinstance(row["known_inputs_ref"].get(role), Mapping)
            and isinstance(row["known_inputs_ref"][role].get("path"), str)
            and isinstance(row["known_inputs_ref"][role].get("sha256"), str)
            and len(row["known_inputs_ref"][role]["sha256"]) == 64
            for role in ("geometry", "control")
        ) for row in rows
    )
    inventory["runtime_capability_fields"] = sorted(
        set(payload).intersection(MANIFEST_CAPABILITY_FIELDS)
    )
    inventory["case_runtime_field_counts"] = {
        field: sum(field in row for row in rows) for field in sorted(CASE_RUNTIME_FIELDS)
    }
    return inventory, payload


def _registry_inventory(root: Path) -> tuple[dict[str, Any], Any]:
    record, payload = _json_record(root, REGISTRY_REL)
    counts: dict[str, int | None] = {}
    if isinstance(payload, dict):
        for key in ("scopes", "scope_studies", "training_runs", "evaluations"):
            value = payload.get(key)
            counts[key] = len(value) if isinstance(value, list) else None
    return {
        "file": record,
        "valid_json_object": isinstance(payload, dict),
        "schema": payload.get("schema") if isinstance(payload, dict) else None,
        "counts": counts,
    }, payload


def _check(
    identifier: str,
    description: str,
    *,
    code_contract_exists: bool,
    synthetic_contract_exists: bool,
    trusted_runtime_evidence_exists: bool,
    status: str,
    evidence: list[str],
) -> dict[str, Any]:
    return {
        "id": identifier,
        "description": description,
        "code_contract_exists": bool(code_contract_exists),
        "synthetic_contract_exists": bool(synthetic_contract_exists),
        "trusted_runtime_evidence_exists": bool(trusted_runtime_evidence_exists),
        "status": status,
        "evidence": evidence,
    }


def audit_repository(lab_root: str | Path) -> dict[str, Any]:
    """Return a deterministic, read-only static closure audit."""
    root = Path(lab_root).resolve()
    manifest, manifest_payload = _manifest_inventory(root)
    registry, registry_payload = _registry_inventory(root)

    files: dict[str, dict[str, Any]] = {}
    texts: dict[str, str] = {}

    file_specs = {
        "base_contract": (BASE_CONTRACT_REL, BASE_MARKERS),
        "base_tests": (BASE_TEST_REL, BASE_TEST_MARKERS),
        "strict_contract": (STRICT_CONTRACT_REL, STRICT_MARKERS),
        "strict_tests": (STRICT_TEST_REL, STRICT_TEST_MARKERS),
        "dataset_reader": (DATASET_REL, DATASET_MARKERS),
        "fsverity_primitives": (FSVERITY_REL, FSVERITY_MARKERS),
        "learning_gate": (LEARNING_REL, LEARNING_MARKERS),
        "campaign_gate": (CAMPAIGN_REL, CAMPAIGN_MARKERS),
    }
    for name, (relative, markers) in file_specs.items():
        record, text = _file_record(root, relative, markers)
        files[name] = record
        texts[name] = text

    blockers: list[dict[str, Any]] = []

    def add_blocker(code: str, message: str, evidence: list[str]) -> None:
        if any(item["code"] == code for item in blockers):
            return
        blockers.append({"code": code, "message": message, "evidence": evidence})

    base_code = files["base_contract"]["all_markers_present"]
    strict_code = files["strict_contract"]["all_markers_present"]
    synthetic_tests = (
        files["base_tests"]["all_markers_present"]
        and files["strict_tests"]["all_markers_present"]
    )
    dataset_code = files["dataset_reader"]["all_markers_present"]
    fsverity_code = files["fsverity_primitives"]["all_markers_present"]
    learning_code = files["learning_gate"]["all_markers_present"]
    campaign_code = files["campaign_gate"]["all_markers_present"]

    release_function = _function_body(texts["learning_gate"], "_manifest_formal_release")
    learning_hard_false = bool(release_function) and "return False" in release_function
    reader_hard_false = "self.formal_eligible = False" in texts["dataset_reader"]
    sidecar_imported_by_production = any(
        marker in texts[name]
        for name in ("dataset_reader", "learning_gate", "campaign_gate")
        for marker in (
            "f3_formal_reader_capability_contract_v1",
            "f3_formal_reader_strict_capability_contract_v1",
            "validate_capability_contract(",
            "validate_strict_capability_contract(",
        )
    )
    production_identity_binding = any(
        marker in texts["dataset_reader"] or marker in texts["learning_gate"]
        for marker in (
            "capability_contract",
            "descriptor_bundle",
            "session_nonce",
            "producer_identity",
            "broker_identity",
            "worker_identity",
        )
    )

    manifest_valid = manifest["valid_json_object"] and manifest["case_count_matches"]
    if not manifest_valid:
        add_blocker(
            "F3_MANIFEST_INVENTORY_INVALID",
            "the current F3 manifest is missing or is not a valid case inventory",
            [MANIFEST_REL.as_posix()],
        )
    if not manifest["declared_formal_release"]:
        add_blocker(
            "F3_MANIFEST_FORMAL_RELEASE_FALSE",
            "the current F3 manifest declares formal_release=false",
            [MANIFEST_REL.as_posix()],
        )
    if not manifest["runtime_capability_fields"]:
        add_blocker(
            "FORMAL_CAPABILITY_RELEASE_UNBOUND",
            "the manifest has no bound capability contract, source authority, identity chain, or release reference",
            [MANIFEST_REL.as_posix()],
        )
    if not manifest["source_hash_byte_metadata"]:
        add_blocker(
            "SOURCE_METADATA_INCOMPLETE",
            "the manifest does not provide complete path/hash/byte metadata for every case",
            [MANIFEST_REL.as_posix()],
        )
    if not dataset_code or not fsverity_code:
        add_blocker(
            "SOURCE_MEASUREMENT_CODE_CONTRACT_MISSING",
            "the local snapshot/fs-verity primitive contract could not be found",
            [DATASET_REL.as_posix(), FSVERITY_REL.as_posix()],
        )
    add_blocker(
        "SOURCE_MEASUREMENT_RUNTIME_AUTHORITY_MISSING",
        "fs-verity and held-FD checks are caller-supplied code primitives; no trusted producer measurement/runtime authority is bound to the current manifest and reader",
        [DATASET_REL.as_posix(), FSVERITY_REL.as_posix(), MANIFEST_REL.as_posix()],
    )
    for role in ("producer", "broker", "worker"):
        add_blocker(
            f"{role.upper()}_IDENTITY_RUNTIME_AUTHORITY_MISSING",
            f"no trusted {role} identity, nonce/session binding, or runtime attestation is integrated into the production F3 admission path",
            [BASE_CONTRACT_REL.as_posix(), STRICT_CONTRACT_REL.as_posix(), DATASET_REL.as_posix(), LEARNING_REL.as_posix()],
        )
    if not (base_code and strict_code and learning_hard_false):
        add_blocker(
            "FORMAL_RELEASE_FAIL_CLOSED_CONTRACT_MISSING",
            "the fail-closed formal release contract is incomplete",
            [BASE_CONTRACT_REL.as_posix(), STRICT_CONTRACT_REL.as_posix(), LEARNING_REL.as_posix()],
        )
    add_blocker(
        "READER_CAPABILITY_INTEGRATION_MISSING",
        "v1/strict validators are isolated sidecars and are not consumed by CoreDataset or the formal learning/evaluation admission path",
        [DATASET_REL.as_posix(), LEARNING_REL.as_posix(), BASE_CONTRACT_REL.as_posix(), STRICT_CONTRACT_REL.as_posix()],
    )
    if not campaign_code or not (learning_hard_false and reader_hard_false):
        add_blocker(
            "CORE_CAMPAIGN_FORMAL_GATE_CONTRACT_MISSING",
            "the campaign gate or its upstream fail-closed reader gate could not be confirmed",
            [CAMPAIGN_REL.as_posix(), LEARNING_REL.as_posix(), DATASET_REL.as_posix()],
        )
    add_blocker(
        "CORE_CAMPAIGN_FORMAL_GATE_UNSATISFIED",
        "core_campaign accepts only formal/root-admitted evidence, while the current F3 path has no formal capability release or trusted runtime evidence",
        [CAMPAIGN_REL.as_posix(), LEARNING_REL.as_posix(), MANIFEST_REL.as_posix(), REGISTRY_REL.as_posix()],
    )

    checks = [
        _check(
            "v1_capability_shape",
            "v1 synthetic source/descriptor/identity envelope shape is implemented and tested",
            code_contract_exists=base_code,
            synthetic_contract_exists=base_code and files["base_tests"]["all_markers_present"],
            trusted_runtime_evidence_exists=False,
            status="contract_only_non_authorizing",
            evidence=[BASE_CONTRACT_REL.as_posix(), BASE_TEST_REL.as_posix()],
        ),
        _check(
            "strict_held_fd_bundle_shape",
            "strict same-bundle/session/attempt/replay binding shape is implemented and tested",
            code_contract_exists=strict_code,
            synthetic_contract_exists=strict_code and files["strict_tests"]["all_markers_present"],
            trusted_runtime_evidence_exists=False,
            status="contract_only_non_authorizing",
            evidence=[STRICT_CONTRACT_REL.as_posix(), STRICT_TEST_REL.as_posix()],
        ),
        _check(
            "manifest_source_metadata",
            "current F3 manifest has content-addressed source and geometry/control metadata",
            code_contract_exists=bool(manifest["source_hash_byte_metadata"] and manifest["descriptor_metadata"]),
            synthetic_contract_exists=bool(manifest["source_hash_byte_metadata"]),
            trusted_runtime_evidence_exists=False,
            status="metadata_only",
            evidence=[MANIFEST_REL.as_posix()],
        ),
        _check(
            "source_measurement_runtime_authority",
            "reader and fs-verity modules contain held-FD measurement primitives, but no trusted runtime authority is present",
            code_contract_exists=bool(dataset_code and fsverity_code),
            synthetic_contract_exists=bool(base_code and strict_code),
            trusted_runtime_evidence_exists=False,
            status="primitive_only_no_authority",
            evidence=[DATASET_REL.as_posix(), FSVERITY_REL.as_posix(), MANIFEST_REL.as_posix()],
        ),
        _check(
            "producer_identity_runtime_authority",
            "producer identity is expressible only in the synthetic v1 envelope",
            code_contract_exists=False,
            synthetic_contract_exists=base_code,
            trusted_runtime_evidence_exists=False,
            status="synthetic_shape_only",
            evidence=[BASE_CONTRACT_REL.as_posix(), MANIFEST_REL.as_posix(), DATASET_REL.as_posix()],
        ),
        _check(
            "broker_identity_runtime_authority",
            "broker identity is expressible only in the synthetic v1 envelope",
            code_contract_exists=False,
            synthetic_contract_exists=base_code,
            trusted_runtime_evidence_exists=False,
            status="synthetic_shape_only",
            evidence=[BASE_CONTRACT_REL.as_posix(), MANIFEST_REL.as_posix(), LEARNING_REL.as_posix()],
        ),
        _check(
            "worker_identity_runtime_authority",
            "worker identity is expressible only in the synthetic v1 envelope",
            code_contract_exists=False,
            synthetic_contract_exists=base_code,
            trusted_runtime_evidence_exists=False,
            status="synthetic_shape_only",
            evidence=[BASE_CONTRACT_REL.as_posix(), MANIFEST_REL.as_posix(), LEARNING_REL.as_posix()],
        ),
        _check(
            "formal_capability_release",
            "formal_release is required by the synthetic contracts and remains fail-closed in core_learning",
            code_contract_exists=bool(base_code and strict_code and learning_hard_false),
            synthetic_contract_exists=bool(base_code and strict_code),
            trusted_runtime_evidence_exists=False,
            status="fail_closed_no_release",
            evidence=[BASE_CONTRACT_REL.as_posix(), STRICT_CONTRACT_REL.as_posix(), LEARNING_REL.as_posix(), MANIFEST_REL.as_posix()],
        ),
        _check(
            "reader_capability_integration",
            "the v1/strict sidecars are not integrated into CoreDataset or formal learning/evaluation admission",
            code_contract_exists=bool(sidecar_imported_by_production),
            synthetic_contract_exists=bool(base_code and strict_code),
            trusted_runtime_evidence_exists=False,
            status="isolated_sidecars_not_consumed",
            evidence=[DATASET_REL.as_posix(), LEARNING_REL.as_posix(), BASE_CONTRACT_REL.as_posix(), STRICT_CONTRACT_REL.as_posix()],
        ),
        _check(
            "core_campaign_formal_gate",
            "core_campaign rejects diagnostic/non-formal evidence and requires formal training/evaluation receipts",
            code_contract_exists=campaign_code,
            synthetic_contract_exists=campaign_code,
            trusted_runtime_evidence_exists=False,
            status="gate_present_but_unsatisfied",
            evidence=[CAMPAIGN_REL.as_posix(), REGISTRY_REL.as_posix(), MANIFEST_REL.as_posix()],
        ),
    ]

    registry_counts = registry["counts"]
    return {
        "schema": REPORT_SCHEMA,
        "audit_version": AUDIT_VERSION,
        "validation_scope": "repository_static_inventory_and_synthetic_contract_closure_only",
        "subject": {
            "family": "F3",
            "manifest": MANIFEST_REL.as_posix(),
            "manifest_sha256": manifest["file"]["sha256"],
            "manifest_declared_formal_release": manifest["declared_formal_release"],
        },
        "contract_layer": {
            "v1_present": bool(base_code),
            "strict_present": bool(strict_code),
            "synthetic_negative_tests_present": bool(synthetic_tests),
            "production_identity_binding_present": bool(production_identity_binding),
            "production_sidecar_integration_present": bool(sidecar_imported_by_production),
            "already_covered_by_v1_strict": [
                "synthetic capability envelope shape",
                "same held-FD bundle/session/attempt/replay shape",
            ],
            "new_v2_scope": [
                "manifest-to-capability binding",
                "production reader/learning integration",
                "trusted source measurement/runtime authority",
                "producer/broker/worker runtime identity authority",
                "formal release consumption and campaign gate compatibility",
            ],
        },
        "runtime_evidence_layer": {
            "trusted_runtime_evidence_exists": False,
            "manifest": manifest,
            "registry": {
                "path": REGISTRY_REL.as_posix(),
                "valid_json_object": registry["valid_json_object"],
                "schema": registry["schema"],
                "counts": registry_counts,
                "formal_training_receipts": registry_counts.get("training_runs"),
                "evaluation_receipts": registry_counts.get("evaluations"),
            },
            "reason": "static JSON/source claims are not authority; no producer/broker/worker runtime attestation or released capability is consumed by the production reader",
        },
        "source_files": files,
        "checks": checks,
        "blockers": blockers,
        "authorizes_formal": False,
        "formal_eligible": False,
        "qualification_credit": 0,
        "execution_constraints": {
            "read_only": True,
            "synthetic_only": True,
            "opens_source_fd": False,
            "reads_hdf5": False,
            "invokes_fsverity": False,
            "imports_production_reader": False,
            "starts_gpu": False,
            "starts_solver": False,
            "starts_worker": False,
            "starts_queue": False,
            "mutates_manifest": False,
            "mutates_reader": False,
            "mutates_registry": False,
            "mutates_ledger": False,
            "mutates_denominator": False,
            "mutates_gate": False,
            "writes_existing_project_state": False,
        },
        "side_effects": {
            "production_files_written": False,
            "new_audit_output_only": True,
            "registry_mutation": False,
            "ledger_mutation": False,
            "qualification_credit_added": 0,
        },
        "internal_consistency": {
            "manifest_payload_loaded": isinstance(manifest_payload, dict),
            "registry_payload_loaded": isinstance(registry_payload, dict),
            "learning_gate_hard_false": learning_hard_false,
            "reader_formal_flag_hard_false": reader_hard_false,
            "campaign_gate_contract_present": campaign_code,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = audit_repository(args.lab_root)
    encoded = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.output is None:
        sys.stdout.write(encoded)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(encoded)
    return 0 if report["formal_eligible"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
