#!/usr/bin/env python3
"""Bind a real typed317 receipt/report using metadata only.

The binder is intentionally downstream of the actual Root conversion.  It
accepts JSON receipt/report paths, validates their producer-declared fields,
and emits a binding sidecar.  It never opens or hashes H5, BI4, CSV, XMF, or
solver particle data, and it never enables a runner request.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

SCIENCE_SUFFIXES = {".bi4", ".csv", ".h5", ".hdf5", ".xmf", ".xdmf", ".vtk"}


def load_json(path: Path) -> dict[str, Any]:
    if path.suffix.lower() in SCIENCE_SUFFIXES:
        raise ValueError(f"science array/artifact path is forbidden to this metadata-only binder: {path}")
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def identity_from_receipt(receipt: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    request = receipt.get("request") if isinstance(receipt.get("request"), dict) else {}
    attempt = request.get("attempt_id") or receipt.get("attempt_id")
    case_id = request.get("case_id") or receipt.get("case_id")
    output_root = receipt.get("output_root") or request.get("output_root")
    return attempt, case_id, output_root


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", type=Path, required=True)
    parser.add_argument("--typed-receipt", type=Path, required=True)
    parser.add_argument("--conversion-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    owner = load_json(args.owner)
    receipt = load_json(args.typed_receipt)
    report = load_json(args.conversion_report)
    owner_sha = sha256_file(args.owner)
    receipt_sha = sha256_file(args.typed_receipt)
    report_sha = sha256_file(args.conversion_report)
    expected_case = owner["case_id"]
    expected_attempt = owner["typed_conversion_binding"]["attempt_id"]
    expected_counts = owner["actual_counts"]

    require(receipt.get("status") in {"completed", "success"}, "typed receipt is not completed/success")
    attempt, case_id, receipt_output_root = identity_from_receipt(receipt)
    require(attempt == expected_attempt, f"typed receipt attempt mismatch: {attempt!r} != {expected_attempt!r}")
    require(case_id == expected_case, f"typed receipt case mismatch: {case_id!r} != {expected_case!r}")
    return_code = receipt.get("return_code", receipt.get("returncode", receipt.get("exit_code")))
    if return_code is not None:
        require(int(return_code) == 0, f"typed receipt return code is not zero: {return_code!r}")

    require(report.get("conversion_status") == "completed", "conversion report is not completed")
    require(int(report.get("frames", -1)) == 51, f"conversion report frame count is not 51: {report.get('frames')!r}")
    require(int(report.get("particles", -1)) == expected_counts["total_particles"], "conversion particle axis does not match actual GenCase total")
    require(int(report.get("solver_dimension", -1)) == 3, "conversion report is not 3-D")
    require(report.get("coordinate_frame") == "DualSPHysics case Cartesian coordinates (x,y,z)", "unexpected conversion coordinate frame")

    typed_identity = report.get("typed_identity")
    if isinstance(typed_identity, dict):
        observed_types = typed_identity.get("observed_types")
        if observed_types is not None:
            require(set(int(value) for value in observed_types) >= {0, 1, 3}, "typed report omits a required native type")
        observed_mks = typed_identity.get("observed_mks")
        if observed_mks is not None:
            require(50 in {int(value) for value in observed_mks}, "typed report omits native Mk50 bed marker")

    hash_scopes = report.get("hash_scopes")
    require(isinstance(hash_scopes, dict), "conversion report lacks hash_scopes metadata")
    physical_scope = hash_scopes.get("physical_condition")
    legacy_sha = hash_scopes.get("physical_condition_sha256")
    require(isinstance(physical_scope, dict), "conversion report lacks physical condition scope")
    require(physical_scope.get("schema") == "legacy-owner-scope.v0", "conversion did not preserve legacy owner scope")
    require(physical_scope.get("semantic_binding_status") == "legacy_incomplete; no cross-resolution physical claim", "legacy scope status changed")
    require(legacy_sha == owner["legacy_scope_sha256"], "conversion legacy physical scope hash does not match fresh094 owner")
    require(legacy_sha not in {owner["physical_condition_sha256"], owner["source_plan_physical_condition_sha256"]}, "conversion legacy scope was mislabelled as canonical/source-plan")

    provenance = report.get("source_provenance")
    require(isinstance(provenance, dict), "conversion report lacks source provenance")
    owner_provenance = provenance.get("owner_metadata")
    require(isinstance(owner_provenance, dict), "conversion report lacks owner metadata provenance")
    require(owner_provenance.get("sha256") == owner_sha, "conversion report owner metadata hash differs from fresh094 owner")
    generated_xml = provenance.get("generated_xml")
    require(isinstance(generated_xml, dict), "conversion report lacks generated XML provenance")
    require(generated_xml.get("sha256") == owner["generated_xml_sha256"], "conversion XML hash differs from actual GenCase XML")
    gencase = provenance.get("gencase_receipt")
    require(isinstance(gencase, dict), "conversion report lacks GenCase receipt provenance")
    require(gencase.get("sha256") == owner["gencase_receipt_sha256"], "conversion GenCase receipt hash differs from actual GenCase receipt")
    solver = provenance.get("solver_receipt")
    require(isinstance(solver, dict), "conversion report lacks solver receipt provenance")
    require(solver.get("sha256") == owner["short_native"]["receipt_sha256"], "conversion solver receipt hash differs from short316")

    output_hdf5 = report.get("output_hdf5")
    require(isinstance(output_hdf5, str) and output_hdf5, "conversion report lacks output_hdf5 path")
    result = {
        "schema": "ds02.f5.c082s1.post-typed317-metadata-binding.fresh094.v1",
        "status": "completed_metadata_binding",
        "owner_metadata": str(args.owner.resolve()),
        "owner_metadata_sha256": owner_sha,
        "typed_receipt": str(args.typed_receipt.resolve()),
        "typed_receipt_sha256": receipt_sha,
        "conversion_report": str(args.conversion_report.resolve()),
        "conversion_report_sha256": report_sha,
        "typed_attempt_id": expected_attempt,
        "case_id": expected_case,
        "actual_counts": expected_counts,
        "solver_dimension": 3,
        "saved_frames": 51,
        "native_bed_marker_mk": owner["native_bed_marker_mk"],
        "source_mkbound": owner["source_mkbound"],
        "mass_report_without_rescale": True,
        "continuum_fluid_mass_kg": owner["continuum_fluid_mass_kg"],
        "native_fluid_mass_kg": None,
        "physical_condition_semantics": {
            "canonical_owner_sha256": owner["physical_condition_sha256"],
            "source_plan_sha256": owner["source_plan_physical_condition_sha256"],
            "legacy_scope_sha256": legacy_sha,
            "legacy_scope_schema": physical_scope["schema"],
            "legacy_scope_status": physical_scope["semantic_binding_status"],
            "cross_resolution_claim": False
        },
        "trajectory_h5": output_hdf5,
        "trajectory_h5_sha256": None,
        "xmf_manifest": None,
        "xmf_manifest_sha256": None,
        "downstream": {
            "typed_conversion": "actual completed report bound",
            "dynamic_bed_audit": "eligible for separate Root disabled request; requires explicit Root review",
            "xmf": "eligible for separate Root disabled request; requires actual typed binding",
            "render": "eligible for separate Root disabled request; requires actual typed binding",
            "full801": "disabled; no dynamic or visual acceptance inferred"
        },
        "future_hashes": None,
        "root_review_required": True,
        "source_only": True,
        "science_arrays_read_by_binder": False,
        "science_arrays_hashed_by_binder": False,
        "conversion_task_started_by_binder": False
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": result["status"], "legacy_scope_sha256": legacy_sha, "report_sha256": report_sha}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
