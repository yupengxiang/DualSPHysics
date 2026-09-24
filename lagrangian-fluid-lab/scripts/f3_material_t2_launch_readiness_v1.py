#!/usr/bin/env python3
"""Read-only F3 macro-material T2 launch-readiness audit.

This audit is intentionally narrower than a material collector: it reads
versioned JSON evidence and source text only, makes no HDF5 reads, and never
starts a material worker, solver, CUDA process, or queue request.  Its output
separates a reusable *CFD source* from a completed material result and from a
permission to schedule work.  In particular, it cannot grant T2 credit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


SCHEMA = "core.material.f3.t2.launch_readiness.v1"
QUALIFICATION_SCHEMA = "core.qualification.v1"
DEFAULT_OUTPUT = Path(
    "campaigns/core-v1/material/evidence/"
    "f3-material-t2-launch-readiness-v1/receipt.json"
)

INPUTS: dict[str, Path] = {
    "f3_canonical_manifest": Path(
        "campaigns/l2-multifamily/evidence/f3-canonical-manifest.json"
    ),
    "f3_inherited_qualification": Path(
        "campaigns/core-v1/evidence/f3-inherited-qualification.json"
    ),
    "f3_dataset": Path("campaigns/core-v1/f3-dataset-v2.json"),
    "matrix_asset_audit": Path(
        "campaigns/core-v1/material/evidence/"
        "f3-native-volume-mls-f3-matrix-asset-audit-v3-20260919.json"
    ),
    "matrix_gap_audit": Path(
        "campaigns/core-v1/material/evidence/"
        "f3-native-mls-33-matrix-gap-audit-v1.json"
    ),
    "t2_admission_gap_audit": Path(
        "campaigns/core-v1/material/evidence/"
        "f3-t2-admission-acceptance-gap-audit-v3-20260923.json"
    ),
    "t2_source_closure_audit": Path(
        "campaigns/core-v1/material/evidence/"
        "f3-t2-source-closure-audit-v1-20260922.json"
    ),
    "resource_preflight_contract": Path(
        "campaigns/core-v1/material/evidence/"
        "f3-qualification-diagnostic-runtime-spec-2026-09-19.json"
    ),
    "resume_contract": Path(
        "campaigns/core-v1/material/evidence/"
        "f3-native-volume-mls-v1-checkpoint-resume-test-20260919.json"
    ),
    "material_implementation": Path("scripts/core_material.py"),
    "material_acceptance": Path("scripts/core_material_acceptance.py"),
    "native_mls_implementation": Path("scripts/f3_native_volume_mls.py"),
    "native_mls_acceptance_adapter": Path(
        "scripts/f3_native_mls_acceptance_adapter_v1.py"
    ),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve_path(lab_root: str | Path, value: str | Path) -> Path:
    """Resolve both lab-relative and historical repository-relative paths."""
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    root = Path(lab_root).resolve()
    for item in (root / candidate, root.parent / candidate):
        if item.exists():
            return item
    return root / candidate


def display_path(lab_root: str | Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path(lab_root).resolve()))
    except ValueError:
        return str(path.resolve())


def bind_file(lab_root: str | Path, path: Path) -> dict[str, Any]:
    resolved = resolve_path(lab_root, path)
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    return {
        "path": display_path(lab_root, resolved),
        "bytes": resolved.stat().st_size,
        "sha256": sha256_file(resolved),
    }


def load_json(lab_root: str | Path, path: Path) -> dict[str, Any]:
    resolved = resolve_path(lab_root, path)
    value = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {resolved}")
    return value


def _require_qualification_schema(qualification: dict[str, Any]) -> None:
    schema = qualification.get("schema")
    if type(schema) is not str or schema != QUALIFICATION_SCHEMA:
        raise ValueError("F3 qualification schema mismatch")


def _rows(
    value: dict[str, Any], source_name: str, *, key: str = "rows"
) -> dict[int, dict[str, Any]]:
    rows = value.get(key)
    if not isinstance(rows, list):
        raise ValueError(f"{source_name} has no row list")
    result: dict[int, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("matrix_index"), int):
            raise ValueError(f"{source_name} has malformed matrix row")
        result[row["matrix_index"]] = row
    if sorted(result) != list(range(33)):
        raise ValueError(f"{source_name} does not have the canonical 0..32 rows")
    return result


def _closure_failures(source_closure: dict[str, Any]) -> set[int]:
    missing = source_closure.get("missing_root_owned_cfd_sources", {}).get("items", [])
    if not isinstance(missing, list):
        raise ValueError("source closure missing-root list is malformed")
    return {
        item["matrix_row"]
        for item in missing
        if isinstance(item, dict) and isinstance(item.get("matrix_row"), int)
    }


def _evidence_class(
    index: int,
    gap: dict[str, Any],
    asset: dict[str, Any],
    missing_source_rows: set[int],
) -> tuple[str, str, bool]:
    """Return evidence kind, next gap, and whether an exact CFD source is reusable."""
    source_available = asset.get("source_available") is True
    status = str(gap.get("status", ""))
    if index in (29, 31):
        return (
            "terminal_scientific_failure",
            "the bound source-window audit records unknown/CDF gate failures; do not rerun "
            "the identical diagnostic as a substitute for a remedy decision",
            source_available,
        )
    if index in missing_source_rows or status == "blocked_missing_registered_source":
        return (
            "missing_exact_cfd_source",
            "root-owned exact CFD source definition, solve, conversion, and hash receipt are required",
            False,
        )
    if index == 24:
        return (
            "terminal_engineering_evidence_incomplete_for_acceptance",
            "existing native-dense material trace lacks independent CDF/residence-CDF acceptance receipts",
            source_available,
        )
    if index == 25:
        return (
            "terminal_matched_decimation_diagnostic_only",
            "retain the paired native-dense source/result and obtain independent acceptance collection; no interpolation substitution",
            source_available,
        )
    if index == 30:
        return (
            "noncanonical_related_failure_not_a_canonical_result",
            "the retained v3 s2 diagnostic is not canonical s4 and failed the unknown gate; a frozen canonical s4 attempt needs fresh authorization",
            source_available,
        )
    if status == "terminal_diagnostic_observed":
        return (
            "terminal_diagnostic_only",
            "independent per-row acceptance collection is still absent; terminal diagnostics have zero T2 credit",
            source_available,
        )
    if status == "source_available_not_submitted":
        return (
            "reusable_source_not_executed",
            "material execution is possible only after independent root and resource authorization",
            source_available,
        )
    return (
        "static_or_stale_status_not_launch_authorization",
        "the recorded status is historical/static and does not itself authorize a current material launch",
        source_available,
    )


def _plan_diagnostic_role(index: int) -> str | None:
    # PLAN §III.3: 12 center/hard-endpoint resolution/substep configurations,
    # native-dense plus matched-decimation cadence pair, then central 4096 seeds.
    if 0 <= index <= 11:
        return "resolution_substep_12"
    if index in (24, 25):
        return "native_dense_vs_matched_decimation_pair"
    if index == 30:
        return "central_512_vs_4096_seed_quadrature"
    return None


def build_audit(lab_root: str | Path) -> dict[str, Any]:
    root = Path(lab_root).resolve()
    inputs = {name: bind_file(root, path) for name, path in INPUTS.items()}
    canonical = load_json(root, INPUTS["f3_canonical_manifest"])
    qualification = load_json(root, INPUTS["f3_inherited_qualification"])
    _require_qualification_schema(qualification)
    dataset = load_json(root, INPUTS["f3_dataset"])
    assets = load_json(root, INPUTS["matrix_asset_audit"])
    gap = load_json(root, INPUTS["matrix_gap_audit"])
    admission = load_json(root, INPUTS["t2_admission_gap_audit"])
    closure = load_json(root, INPUTS["t2_source_closure_audit"])
    resource = load_json(root, INPUTS["resource_preflight_contract"])
    resume = load_json(root, INPUTS["resume_contract"])

    asset_rows = _rows(assets, "matrix asset audit", key="matrix_rows")
    gap_rows = _rows(gap, "matrix gap audit")
    missing_source_rows = _closure_failures(closure)
    availability: list[dict[str, Any]] = []
    for index in range(33):
        asset = asset_rows[index]
        observed = gap_rows[index]
        evidence_class, next_gap, reusable_source = _evidence_class(
            index, observed, asset, missing_source_rows
        )
        availability.append(
            {
                "matrix_index": index,
                "configuration_id": observed.get("configuration_id"),
                "plan_diagnostic_role": _plan_diagnostic_role(index),
                "matrix_stage": observed.get("matrix_stage"),
                "q": observed.get("q"),
                "q_role": observed.get("q_role"),
                "dp": observed.get("dp"),
                "cadence": observed.get("cadence"),
                "substeps": observed.get("substeps"),
                "seeds": observed.get("seeds"),
                "source_asset_id": asset.get("source_asset_id"),
                "exact_cfd_source_reusable": reusable_source,
                "historical_matrix_status": observed.get("status"),
                "evidence_class": evidence_class,
                "next_gap": next_gap,
                "T2_credit": "none",
            }
        )

    diagnostic_rows = [row for row in availability if row["plan_diagnostic_role"]]
    if len(diagnostic_rows) != 15:
        raise AssertionError("PLAN 15-diagnostic mapping must contain exactly 15 rows")
    classes = Counter(row["evidence_class"] for row in availability)
    source_available_unexecuted = [
        row["matrix_index"]
        for row in availability
        if row["evidence_class"] == "reusable_source_not_executed"
    ]
    next_row = next(row for row in availability if row["matrix_index"] == 30)

    qualification_summary = {
        "T1_numerical": qualification.get("T1_numerical") is True,
        "T2_macro": qualification.get("T2_macro") is True,
        "T2_path": qualification.get("T2_path") is True,
        "scope_id": qualification.get("scope_id"),
        "canonical_material_macro": canonical.get("qualification_axes", {}).get("material_macro"),
        "canonical_material_path": canonical.get("qualification_axes", {}).get("material_path"),
        "dataset_formal_release": dataset.get("formal_release") is True,
        "dataset_material_macro": dataset.get("source_qualification_claims", {}).get("material_macro"),
    }
    if qualification_summary["T1_numerical"] is not True:
        raise AssertionError("F3 inherited numerical qualification changed unexpectedly")
    if qualification_summary["T2_macro"] or qualification_summary["T2_path"]:
        raise AssertionError("this launch-readiness audit must not receive F3 T2 credit")

    return {
        "schema": SCHEMA,
        "scope": {
            "family": "F3",
            "purpose": "read-only launch readiness for the PLAN F3 macro-material T2 15-diagnostic and 33-logical-configuration matrix",
            "hdf5_opened": False,
            "external_binary_invocations": 0,
            "solver_started": False,
            "cuda_started": False,
            "queue_submissions": 0,
            "material_workers_started": 0,
        },
        "input_bindings": inputs,
        "canonical_and_qualification": qualification_summary,
        "material_implementation": {
            "frozen_source_files": [
                "material_implementation",
                "material_acceptance",
                "native_mls_implementation",
                "native_mls_acceptance_adapter",
            ],
            "admission_status": admission.get("status"),
            "admission_T2_macro": admission.get("T2_macro") is True,
            "admission_qualification_credit": admission.get("qualification_credit"),
            "interpretation": "implementation and adapter bindings are static surfaces, not completed material acceptance evidence",
        },
        "resource_and_resume_contracts": {
            "resource_preflight_status": resource.get("status"),
            "resource_scheduler_owned": resource.get("runtime", {}).get("scheduler_owned_resources") is True,
            "resource_cpu_only": resource.get("runtime", {}).get("cpu_only") is True,
            "resource_gpu_forbidden": resource.get("runtime", {}).get("gpu_forbidden") is True,
            "resource_qualification_claim": resource.get("qualification_claim"),
            "resume_contract_status": resume.get("status"),
            "resume_fixture_only": resume.get("scope_limits", {}).get("fixture_is_not_f3_qualification") is True,
            "resume_same_argv_required": resume.get("resume_assertions", {}).get("resume_command") == "same argv plus --resume",
            "interpretation": "the historical contract supports a CPU-only resume protocol but neither it nor its fixture test is an independent authorization for a current matrix launch",
        },
        "plan_15_diagnostics": {
            "required_count": 15,
            "mapped_count": len(diagnostic_rows),
            "rows": diagnostic_rows,
            "availability_counts": dict(Counter(row["evidence_class"] for row in diagnostic_rows)),
        },
        "plan_33_logical_configurations": {
            "required_count": 33,
            "mapped_count": len(availability),
            "rows": availability,
            "availability_counts": dict(classes),
            "missing_exact_source_rows": sorted(missing_source_rows),
            "reusable_source_not_executed_rows": source_available_unexecuted,
        },
        "next_executable_step": {
            "status": "authorization_required_before_execution",
            "candidate_matrix_row": next_row["matrix_index"],
            "candidate_configuration_id": next_row["configuration_id"],
            "candidate_reason": "central 4096-seed s4 quadrature configuration belongs to the PLAN 15-diagnostic set; its production q=0.5 source is registered as reusable, while the retained s2 diagnostic is noncanonical and failed its unknown gate",
            "frozen_inputs_required": [
                "current canonical F3 qualification binding",
                "production q=0.5 exact source hash and source provenance",
                "current native-MLS implementation and acceptance-adapter hashes",
                "fixed 4096-seed, s4, full-window configuration",
                "same-argv checkpoint/resume contract",
            ],
            "required_before_launch": [
                "independent root decision authorizing this exact new diagnostic attempt",
                "fresh scheduler/resource preflight and allocation receipt bound to that decision",
                "one-attempt output namespace and immutable result/acceptance collection contract",
            ],
            "not_authorized_by_this_audit": [
                "solver", "GPU", "queue", "material worker", "registry mutation", "ledger mutation", "T2 credit"
            ],
            "T2_credit": "none",
        },
        "root_and_resource_authorization_gaps": {
            "current_launch_authorization_proven": False,
            "reason": "the bound runtime spec is explicitly scheduler-owned and only ready_for_root_queue; its bound prepared source is not launch-allowed, while no bound independent root/resource receipt authorizes a current frozen matrix attempt",
            "missing_exact_cfd_source_rows_require_root_owned_scope": sorted(missing_source_rows),
            "failed_rows_must_not_be_relabelled_or_counted": [29, 31],
            "formal_matrix_acceptance_receipts": 0,
        },
        "hard_boundaries": {
            "T2_macro": False,
            "T2_path": False,
            "qualification_credit": "none",
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "matrix_mutation": 0,
            "prior_evidence_overwritten": False,
            "F4_files_modified": False,
            "F8_files_modified": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    root = args.lab_root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(build_audit(root), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
