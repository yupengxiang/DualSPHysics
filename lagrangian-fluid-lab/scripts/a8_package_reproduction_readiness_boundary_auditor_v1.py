#!/usr/bin/env python3
"""Audit the A8 package/reproduction readiness projection boundary.

This is a bounded, fail-closed audit of the metadata boundary between the
current ``core.reader_bundle.v2`` reader package and the A8 trusted-root /
external-host / independent-reproduction path.  It reads only small JSON
metadata and historical receipts.  It never opens HDF5, NPZ, checkpoint or
trajectory payloads, and it never starts a solver, worker, GPU or queue.

The audit exists because the current local package bridge is intentionally
diagnostic-only, but two of its projections are weaker than the surrounding
A8 contracts: a ``core.verification.v1`` reader payload is accepted on its
``passed`` bit without a diagnostic/zero-credit boundary check, and the
diagnostic-pair projection accepts self-reported host distinctness without
checking that the host list is present and actually distinct.  These are
projection-boundary findings only; this report never promotes them to trusted
attestation, independent reproduction, formal admission or credit.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

# Keep the standalone CLI importable from the lab root as well as through the
# package test runner, without touching any campaign state.
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import core_product_repro_bridge_v1 as package_bridge
from scripts.core_independent_reproduction_secure_io_v1 import (
    SecureReadError,
    file_identity,
    read_bounded_json_object,
)


SCHEMA = "core.a8.package_reproduction_readiness_boundary_audit.v1"
OBSERVED_AT_UTC = "2026-09-29T04:56:49Z"
MAX_INPUT_BYTES = 256 * 1024
ZERO_MUTATIONS = {
    "registry": 0,
    "ledger": 0,
    "denominator": 0,
    "gate": 0,
    "completion": 0,
    "plan": 0,
}
FALSE_CLAIMS = {
    "readiness_pass": False,
    "independent_reproduction": False,
    "full_product_reproduction": False,
    "formal_admission": False,
    "formal_training": False,
    "credit": 0,
    "qualification_credit": 0,
}
EXECUTION_CONSTRAINTS = {
    "read_only": True,
    "json_metadata_only": True,
    "large_hdf5_opened": False,
    "large_npz_opened": False,
    "checkpoint_opened": False,
    "trajectory_opened": False,
    "trusted_root_authenticated": False,
    "external_host_attested": False,
    "solver_started": False,
    "worker_started": False,
    "gpu_started": False,
    "queue_mutation": 0,
    "registry_mutation": 0,
    "ledger_mutation": 0,
    "denominator_mutation": 0,
    "gate_mutation": 0,
    "completion_mutation": 0,
}

INPUTS = {
    "current_reader_bundle": "campaigns/core-v1/reproduction/a8-full-reproduce-v2/bundle.json",
    "package_manifest": "reports/A8-CORE-PRODUCT-V2-LOCAL-PACKAGE-MANIFEST-2026-09-28.json",
    "package_bridge_report": "reports/A8-CORE-PRODUCT-V2-REPRO-BRIDGE-2026-09-28.json",
    "package_reproduction_receipt": "reports/A8-CORE-PRODUCT-V2-REPRO-RECEIPT-2026-09-28.json",
    "independent_readiness_contract": "reports/A8-INDEPENDENT-REPRODUCTION-READINESS-CONTRACT-V1-2026-09-29.json",
    "trusted_root_external_host_contract": "reports/A8-TRUSTED-ROOT-EXTERNAL-HOST-ATTESTATION-CONTRACT-V1-2026-09-29.json",
    "checkpoint_readiness_audit": "reports/A8-CHECKPOINT-MODEL-REPRODUCTION-READINESS-AUDIT-V1-2026-09-28.json",
    "historical_cross_host_pair": "campaigns/core-v1/reproduction/a8-cross-host-diagnostic-pair-v1.json",
    "historical_independent_receipt": "campaigns/core-v1/reproduction/a8-independent-relocated-v1/independent-reproduction-receipt.json",
    "historical_independent_contract": "campaigns/core-v1/evidence/independent-reproduction-contract-20260920.json",
    "historical_cross_host_contract": "campaigns/core-v1/evidence/cross-host-reproduction-contract-20260920.json",
    "package_bridge_source": "scripts/core_product_repro_bridge_v1.py",
}


class AuditError(ValueError):
    """A bounded A8 audit-input or contract error."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError as error:
        raise AuditError(f"input escaped lab root: {path}") from error


def _read_json(root: Path, relative: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = root / relative
    try:
        payload, safe_path, identity = read_bounded_json_object(
            path, label=relative, max_bytes=MAX_INPUT_BYTES
        )
    except SecureReadError as error:
        raise AuditError(f"{relative}: {error.code}: {error}") from error
    return payload, {
        "path": _relative(safe_path, root),
        "bytes": int(identity["bytes"]),
        "sha256": identity["sha256"],
        "schema": payload.get("schema"),
        "read_policy": "strict_bounded_json_only",
    }


def _read_source_identity(root: Path, relative: str) -> dict[str, Any]:
    path = root / relative
    try:
        identity = file_identity(path, label=relative)
    except SecureReadError as error:
        raise AuditError(f"{relative}: source cannot be read: {error}") from error
    return {
        "path": relative,
        "bytes": int(identity["bytes"]),
        "sha256": identity["sha256"],
        "read_policy": "bounded_source_code_hash",
    }


def _input_summary(payload: Mapping[str, Any], ref: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only bounded metadata in the audit report."""
    return {
        "artifact": dict(ref),
        "schema": payload.get("schema"),
    }


def _reader_projection_probe() -> dict[str, Any]:
    """Probe whether the package bridge rejects an authority-shaped reader row."""
    mutated = {
        "schema": "core.verification.v1",
        "passed": True,
        "diagnostic_only": False,
        "formal_training": True,
        "full_product_reproduction": True,
        "qualification_credit": 1,
    }
    projection, blockers = package_bridge._reader_report_projection(
        mutated,
        label="A8 mutation probe reader",
    )
    accepted = projection.get("passed") is True and not blockers
    return {
        "probe": "core.verification.v1_authority_fields_ignored",
        "mutated_input": {
            "schema": mutated["schema"],
            "passed": mutated["passed"],
            "diagnostic_only": mutated["diagnostic_only"],
            "formal_training": mutated["formal_training"],
            "full_product_reproduction": mutated["full_product_reproduction"],
            "qualification_credit": mutated["qualification_credit"],
        },
        "projection": {
            "passed": projection.get("passed"),
            "diagnostic_only": projection.get("diagnostic_only"),
            "qualification_credit": projection.get("qualification_credit"),
        },
        "blockers": list(blockers),
        "accepted_by_current_bridge": accepted,
        "expected_fail_closed": True,
    }


def _pair_projection_probe(pair: Mapping[str, Any]) -> dict[str, Any]:
    """Probe whether host distinctness is independently checked by the bridge."""
    mutated = copy.deepcopy(dict(pair))
    mutated["observed_hosts"] = ["same-physical-host", "same-physical-host"]
    mutated["distinct_host_evidence"] = True
    rollout, score, blockers = package_bridge._diagnostic_pair_projection(
        {"path": "synthetic/a8-cross-host-diagnostic-pair.json", "bytes": 1, "sha256": "0" * 64},
        mutated,
    )
    accepted = rollout.get("passed") is True and score.get("passed") is True and not blockers
    return {
        "probe": "diagnostic_pair_self_reported_host_distinctness",
        "mutated_input": {
            "observed_hosts": list(mutated["observed_hosts"]),
            "distinct_host_evidence": mutated["distinct_host_evidence"],
            "payload_passed": mutated.get("passed"),
        },
        "projection": {
            "rollout_passed": rollout.get("passed"),
            "rollout_observed_hosts": rollout.get("observed_hosts"),
            "rollout_distinct_host_evidence": rollout.get("distinct_host_evidence"),
            "score_passed": score.get("passed"),
        },
        "blockers": list(blockers),
        "accepted_by_current_bridge": accepted,
        "expected_fail_closed": True,
    }


def _history_projection(
    pair: Mapping[str, Any],
    pair_ref: Mapping[str, Any],
    receipt: Mapping[str, Any],
    receipt_ref: Mapping[str, Any],
    independent_contract: Mapping[str, Any],
    independent_contract_ref: Mapping[str, Any],
    cross_host_contract: Mapping[str, Any],
    cross_host_contract_ref: Mapping[str, Any],
) -> dict[str, Any]:
    evidence = pair.get("evidence") if isinstance(pair.get("evidence"), Mapping) else {}
    model = receipt.get("model") if isinstance(receipt.get("model"), Mapping) else {}
    result = receipt.get("result") if isinstance(receipt.get("result"), Mapping) else {}
    relocation = receipt.get("relocation") if isinstance(receipt.get("relocation"), Mapping) else {}
    scope = receipt.get("scope") if isinstance(receipt.get("scope"), Mapping) else {}
    return {
        "cross_host_pair": {
            "artifact": dict(pair_ref),
            "status": pair.get("status"),
            "passed": pair.get("passed"),
            "observed_hosts": list(pair.get("observed_hosts", []))
            if isinstance(pair.get("observed_hosts"), list)
            else None,
            "distinct_host_evidence": pair.get("distinct_host_evidence"),
            "diagnostic_only": evidence.get("diagnostic_only"),
            "formal_training": evidence.get("formal_training"),
            "qualification_credit": evidence.get("qualification_credit"),
        },
        "independent_receipt": {
            "artifact": dict(receipt_ref),
            "status": receipt.get("status"),
            "host": receipt.get("host"),
            "different_data_root": relocation.get("different_data_root"),
            "reused_existing_relocated_root": relocation.get("metadata", {}).get(
                "reused_existing_relocated_root"
            )
            if isinstance(relocation.get("metadata"), Mapping)
            else None,
            "model_passed": model.get("passed"),
            "model_cross_host_reproduction": model.get("cross_host_reproduction"),
            "model_full_product_reproduction": model.get("full_product_reproduction"),
            "result_independent_reproduction_evidence": result.get(
                "independent_reproduction_evidence"
            ),
            "result_core_gate_status": result.get("core_gate_status"),
            "scope_cross_host_claim": scope.get("cross_host_claim"),
            "scope_formal_training_count": scope.get("formal_training_count"),
        },
        "independent_contract": {
            "artifact": dict(independent_contract_ref),
            "passed": independent_contract.get("passed"),
            "cross_host_reproduction": independent_contract.get("cross_host_reproduction"),
            "full_product_reproduction": independent_contract.get("full_product_reproduction"),
            "scope": independent_contract.get("scope"),
        },
        "cross_host_contract": {
            "artifact": dict(cross_host_contract_ref),
            "passed": cross_host_contract.get("passed"),
            "diagnostic_only": cross_host_contract.get("diagnostic_only"),
            "cross_host_reproduction": cross_host_contract.get("cross_host_reproduction"),
            "full_product_reproduction": cross_host_contract.get("full_product_reproduction"),
            "formal_training_count": cross_host_contract.get("formal_training_count"),
            "scope": cross_host_contract.get("scope"),
        },
    }


def _base_report() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "version": "a8-package-reproduction-readiness-boundary-v1",
        "observed_at_utc": OBSERVED_AT_UTC,
        "status": "blocked_audit_input_error",
        "passed": False,
        "conclusion": "fail_closed",
        **FALSE_CLAIMS,
        "diagnostic_only": True,
        "mutations": dict(ZERO_MUTATIONS),
        "execution_constraints": dict(EXECUTION_CONSTRAINTS),
        "scope": [
            "current reader_bundle.v2 metadata",
            "A8 package/reproduction readiness projections",
            "trusted-root and external-host contract reports",
            "historical second-host and independent-reproduction receipts",
        ],
        "inputs": {},
        "findings": [],
        "minimal_progress_unit": None,
        "history": {},
        "errors": [],
        "allowed_write_set": [
            "scripts/a8_package_reproduction_readiness_boundary_auditor_v1.py",
            "tests/test_a8_package_reproduction_readiness_boundary_auditor_v1.py",
            "reports/A8-PACKAGE-REPRODUCTION-READINESS-BOUNDARY-AUDIT-V1-2026-09-29.json",
            "reports/A8-PACKAGE-REPRODUCTION-READINESS-BOUNDARY-AUDIT-V1-2026-09-29.zh-CN.md",
        ],
    }


def build_report(lab_root: str | Path) -> dict[str, Any]:
    """Build a bounded fail-closed report without opening large artifacts."""
    root = Path(lab_root).expanduser().resolve()
    report = _base_report()
    try:
        loaded: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        for name, relative in INPUTS.items():
            if name == "package_bridge_source":
                report["inputs"][name] = _read_source_identity(root, relative)
            else:
                loaded[name] = _read_json(root, relative)
                report["inputs"][name] = loaded[name][1]

        bundle, bundle_ref = loaded["current_reader_bundle"]
        package_manifest, package_manifest_ref = loaded["package_manifest"]
        package_bridge_report, package_bridge_ref = loaded["package_bridge_report"]
        package_receipt, package_receipt_ref = loaded["package_reproduction_receipt"]
        independent_readiness, independent_readiness_ref = loaded[
            "independent_readiness_contract"
        ]
        trusted_contract, trusted_contract_ref = loaded[
            "trusted_root_external_host_contract"
        ]
        checkpoint_audit, checkpoint_audit_ref = loaded["checkpoint_readiness_audit"]
        pair, pair_ref = loaded["historical_cross_host_pair"]
        historical_receipt, historical_receipt_ref = loaded["historical_independent_receipt"]
        independent_contract, independent_contract_ref = loaded[
            "historical_independent_contract"
        ]
        cross_host_contract, cross_host_contract_ref = loaded[
            "historical_cross_host_contract"
        ]

        files = bundle.get("files")
        checkpoint_paths = []
        if isinstance(files, list):
            checkpoint_paths = [
                row.get("path")
                for row in files
                if isinstance(row, Mapping)
                and isinstance(row.get("path"), str)
                and "checkpoint" in row["path"].lower()
            ]
        current_model_ready = bool(
            bundle.get("schema") == "core.reader_bundle.v2"
            and bundle.get("checkpoint_count") == 0
            and bundle.get("model_reproduction_supported") is False
            and not checkpoint_paths
        )
        report["current_reader_bundle"] = {
            "artifact": dict(bundle_ref),
            "schema": bundle.get("schema"),
            "case_count": bundle.get("case_count"),
            "checkpoint_count": bundle.get("checkpoint_count"),
            "model_reproduction_supported": bundle.get("model_reproduction_supported"),
            "checkpoint_paths_declared": checkpoint_paths,
            "reader_only_current_v2": current_model_ready,
            "large_asset_contents_opened": False,
        }

        report["package_readiness"] = {
            "manifest": {
                "artifact": dict(package_manifest_ref),
                "local_package_ready": package_manifest.get("local_package_ready"),
                "coarse_chain_passed": package_manifest.get("coarse_chain_passed"),
                "diagnostic_only": package_manifest.get("diagnostic_only"),
                "formal_admission": package_manifest.get("formal_admission"),
                "full_product_reproduction": package_manifest.get(
                    "claims", {}
                ).get("full_product_reproduction")
                if isinstance(package_manifest.get("claims"), Mapping)
                else None,
                "qualification_credit": package_manifest.get("qualification_credit"),
                "full_artifact_integrity_verified": package_manifest.get("bundle", {}).get(
                    "full_artifact_integrity_verified"
                )
                if isinstance(package_manifest.get("bundle"), Mapping)
                else None,
                "large_asset_hashes_read": package_manifest.get("bundle", {}).get(
                    "large_asset_hashes_read"
                )
                if isinstance(package_manifest.get("bundle"), Mapping)
                else None,
            },
            "bridge_report": _input_summary(package_bridge_report, package_bridge_ref)
            | {
                "status": package_bridge_report.get("status"),
                "local_package_ready": package_bridge_report.get("local_package_ready"),
                "formal_admission": package_bridge_report.get("formal_admission"),
                "full_product_reproduction": package_bridge_report.get(
                    "full_product_reproduction"
                ),
                "qualification_credit": package_bridge_report.get("qualification_credit"),
            },
            "reproduction_receipt": _input_summary(package_receipt, package_receipt_ref)
            | {
                "status": package_receipt.get("status"),
                "local_package_ready": package_receipt.get("local_package_ready"),
                "cross_host_reproduction": package_receipt.get("cross_host_reproduction"),
                "full_product_reproduction": package_receipt.get(
                    "full_product_reproduction"
                ),
                "formal_training_runs_counted": package_receipt.get(
                    "formal_training_runs_counted"
                ),
                "qualification_credit": package_receipt.get("qualification_credit"),
            },
        }

        report["contract_readiness"] = {
            "independent_reproduction": _input_summary(
                independent_readiness, independent_readiness_ref
            )
            | {
                "status": independent_readiness.get("status"),
                "readiness_pass": independent_readiness.get("readiness_pass"),
                "independent_reproduction": independent_readiness.get(
                    "independent_reproduction"
                ),
                "credit": independent_readiness.get("credit"),
                "blockers": independent_readiness.get("blockers", []),
            },
            "trusted_root_external_host": _input_summary(
                trusted_contract, trusted_contract_ref
            )
            | {
                "status": trusted_contract.get("status"),
                "readiness_pass": trusted_contract.get("readiness_pass"),
                "independent_reproduction": trusted_contract.get(
                    "independent_reproduction"
                ),
                "credit": trusted_contract.get("credit"),
                "blockers": trusted_contract.get("blockers", []),
            },
            "checkpoint_current_binding": {
                "artifact": dict(checkpoint_audit_ref),
                "status": checkpoint_audit.get("status"),
                "current_ready_for_trusted_model_package": checkpoint_audit.get(
                    "trusted_checkpoint_binding", {}
                ).get("ready")
                if isinstance(checkpoint_audit.get("trusted_checkpoint_binding"), Mapping)
                else None,
                "current_trusted_checkpoint_binding": checkpoint_audit.get(
                    "trusted_checkpoint_binding", {}
                ).get("ready")
                if isinstance(checkpoint_audit.get("trusted_checkpoint_binding"), Mapping)
                else None,
            },
        }

        reader_probe = _reader_projection_probe()
        pair_probe = _pair_projection_probe(pair)
        report["mutation_probes"] = {
            "reader_projection": reader_probe,
            "diagnostic_pair_projection": pair_probe,
        }
        report["history"] = _history_projection(
            pair,
            pair_ref,
            historical_receipt,
            historical_receipt_ref,
            independent_contract,
            independent_contract_ref,
            cross_host_contract,
            cross_host_contract_ref,
        )

        findings = []
        if reader_probe["accepted_by_current_bridge"]:
            findings.append({
                "id": "A8-PRB-01",
                "severity": "high",
                "status": "open_boundary_gap",
                "component": "core_product_repro_bridge_v1._reader_report_projection",
                "finding": (
                    "A core.verification.v1 reader payload with passed=true and authority-shaped "
                    "non-diagnostic/credit fields is accepted without a blocker."
                ),
                "impact": (
                    "local_package_ready can be reported from a reader receipt whose diagnostic "
                    "boundary was not validated; this does not itself mint formal credit, but it "
                    "is not a fail-closed readiness projection."
                ),
                "required_minimal_fix": (
                    "Require an exact diagnostic-only reader receipt contract with zero credit, or "
                    "reject the receipt when those markers are absent or contradictory."
                ),
            })
        if pair_probe["accepted_by_current_bridge"]:
            findings.append({
                "id": "A8-PRB-02",
                "severity": "high",
                "status": "open_boundary_gap",
                "component": "core_product_repro_bridge_v1._diagnostic_pair_projection",
                "finding": (
                    "A diagnostic pair with identical observed host ids and a self-reported "
                    "distinct_host_evidence=true is accepted as a passed rollout/score projection."
                ),
                "impact": (
                    "the package bridge can carry self-asserted second-host evidence without an "
                    "independent host identity check; this is insufficient for trusted-root or "
                    "independent-reproduction admission."
                ),
                "required_minimal_fix": (
                    "Require a non-empty host list with pairwise-distinct identities and bind it to "
                    "an independently verified second-host receipt before setting the projection passed."
                ),
            })

        findings.append({
            "id": "A8-PRB-03",
            "severity": "confirmed_blocked",
            "status": "fail_closed",
            "component": "current_v2_reader_and_historical_reproduction_lineage",
            "finding": (
                "The current v2 bundle is reader-only with no checkpoint registry/artifact, while "
                "historical independent-reproduction receipts refer to the older v1 bundle and "
                "contain diagnostic/full-product scope contradictions."
            ),
            "impact": (
                "No current trusted model-package or independent-reproduction promotion unit is "
                "available from these metadata receipts."
            ),
            "required_minimal_fix": (
                "Supply a fresh current-v2 checkpoint binding and independently produced root/host "
                "receipts; historical metadata must remain non-authoritative."
            ),
        })
        report["findings"] = findings
        report["minimal_progress_unit"] = {
            "exists": True,
            "kind": "package_bridge_projection_hardening",
            "files": ["scripts/core_product_repro_bridge_v1.py"],
            "requires_external_attestation": False,
            "requires_large_artifact_open": False,
            "requires_solver_worker_gpu_queue": False,
            "steps": [
                "close A8-PRB-01 with exact reader diagnostic/zero-credit validation",
                "close A8-PRB-02 with independent host-list and second-host receipt validation",
                "rerun the bounded package/reproduction readiness projection",
            ],
            "promotion_allowed_by_this_audit": False,
        }
        report.update({
            "status": "blocked_open_package_reproduction_boundary_gaps",
            "passed": False,
            "conclusion": "open_projection_gaps_but_no_authorizing_evidence",
            "input_contracts_read": True,
        })
    except (AuditError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        report["errors"] = [{"type": type(error).__name__, "message": str(error)}]
        report["status"] = "blocked_audit_input_error"
        report["conclusion"] = "fail_closed_input_error"
    return report


def validate_report(report: Mapping[str, Any]) -> list[str]:
    """Validate that the audit report remains non-authorizing and fail-closed."""
    errors: list[str] = []
    if report.get("schema") != SCHEMA:
        errors.append("schema mismatch")
    if report.get("diagnostic_only") is not True:
        errors.append("diagnostic_only must be true")
    if report.get("mutations") != ZERO_MUTATIONS:
        errors.append("mutations must remain zero")
    if report.get("execution_constraints") != EXECUTION_CONSTRAINTS:
        errors.append("execution_constraints drift")
    for key, expected in FALSE_CLAIMS.items():
        if report.get(key) != expected:
            errors.append(f"{key} must remain {expected!r}")
    if report.get("passed") is not False:
        errors.append("passed must remain false")
    if report.get("status") not in {
        "blocked_open_package_reproduction_boundary_gaps",
        "blocked_audit_input_error",
    }:
        errors.append("unsupported status")
    findings = report.get("findings")
    if not isinstance(findings, list) or not findings:
        errors.append("findings must be non-empty")
    if report.get("status") == "blocked_open_package_reproduction_boundary_gaps":
        if not report.get("input_contracts_read") is True:
            errors.append("input_contracts_read must be true")
        probes = report.get("mutation_probes")
        if not isinstance(probes, Mapping):
            errors.append("mutation_probes missing")
        else:
            for name in ("reader_projection", "diagnostic_pair_projection"):
                probe = probes.get(name)
                if not isinstance(probe, Mapping):
                    errors.append(f"mutation probe missing: {name}")
                elif probe.get("expected_fail_closed") is not True:
                    errors.append(f"mutation probe expectation missing: {name}")
        unit = report.get("minimal_progress_unit")
        if not isinstance(unit, Mapping) or unit.get("promotion_allowed_by_this_audit") is not False:
            errors.append("minimal progress unit must remain non-promoting")
    return sorted(set(errors))


def write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise AuditError(f"refusing to overwrite existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    audit = sub.add_parser("audit")
    audit.add_argument("--lab-root", type=Path, required=True)
    audit.add_argument("--output", type=Path, required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--report", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "audit":
        report = build_report(args.lab_root)
        write_json(args.output, report)
        print(json.dumps({"schema": SCHEMA, "status": report["status"], "findings": len(report["findings"])}, sort_keys=True))
        return 0
    try:
        payload, _, _ = read_bounded_json_object(
            args.report, label="A8 package/reproduction boundary report", max_bytes=MAX_INPUT_BYTES
        )
    except SecureReadError as error:
        print(json.dumps({"passed": False, "errors": [f"{error.code}: {error}"]}, sort_keys=True))
        return 1
    errors = validate_report(payload)
    print(json.dumps({"passed": not errors, "errors": errors}, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
