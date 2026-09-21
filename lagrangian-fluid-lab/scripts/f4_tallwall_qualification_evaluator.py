#!/usr/bin/env python3
"""Read-only evaluator for the frozen F4 tall-wall 13+2 qualification matrix.

The evaluator consumes a scope-specific manifest.  It keeps the canary reuse
in the 15-cell denominator, verifies the original canary receipt and input
hashes, and leaves the result unqualified until all fourteen scheduled cells
have independently returned valid products.  No solver, queue, or ledger
operation is performed here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.core_runtime import Store
from scripts.core_qualification import aligned_difference, time_step_evidence


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load(path: Path) -> dict:
    return json.loads(Path(path).read_text())


def _verify_binding(binding: dict) -> tuple[bool, str | None]:
    path = Path(binding["path"])
    if not path.is_file():
        return False, f"missing:{path}"
    actual = digest(path)
    if actual != binding["sha256"]:
        return False, f"hash:{path}:{actual}!={binding['sha256']}"
    return True, None


def verify_static_manifest(manifest_path: Path) -> dict:
    """Verify immutable inputs and return a pending, non-qualification result."""
    manifest_path = Path(manifest_path).resolve()
    manifest = load(manifest_path)
    issues: list[str] = []
    if manifest.get("schema") != "core.f4.tallwall120.qualification_evaluator.v1":
        issues.append("schema")
    if manifest.get("family") != "F4":
        issues.append("family")
    if manifest.get("qualification_claim") != "none":
        issues.append("qualification_claim")
    if manifest.get("matrix_denominator") != 15:
        issues.append("matrix_denominator")
    accounting = manifest.get("cell_accounting", {})
    scheduled = set(accounting.get("scheduled_solver_cells", []))
    reused = set(accounting.get("reused_canary_cells", []))
    if scheduled | reused != set(range(15)) or scheduled & reused or reused != {12} or len(scheduled) != 14:
        issues.append("cell_accounting")

    binding_results = {}
    for name, binding in manifest.get("source_bindings", {}).items():
        ok, reason = _verify_binding(binding)
        binding_results[name] = {"pass": ok, "reason": reason, **binding}
        if not ok:
            issues.append(f"binding:{name}")
    for binding in accounting.get("root_scheduled_specs", []):
        ok, reason = _verify_binding(binding)
        name = f"root_scheduled_spec:{binding.get('index')}"
        binding_results[name] = {"pass": ok, "reason": reason, **binding}
        if not ok:
            issues.append(name)

    cell12 = manifest.get("cell12_reuse", {})
    if cell12.get("new_candidate_bi4_executed") is not False:
        issues.append("cell12_new_candidate_bi4_executed")
    if cell12.get("reuse_qualifies_range") is not False:
        issues.append("cell12_reuse_qualifies_range")
    for name, binding in cell12.get("evidence_bindings", {}).items():
        ok, reason = _verify_binding(binding)
        binding_results[f"cell12:{name}"] = {"pass": ok, "reason": reason, **binding}
        if not ok:
            issues.append(f"cell12_binding:{name}")
    for item in cell12.get("original_canary_input_hashes", []):
        ok, reason = _verify_binding(item)
        name = f"cell12:original_input:{item.get('path')}"
        binding_results[name] = {"pass": ok, "reason": reason, **item}
        if not ok:
            issues.append(f"cell12_original_input:{item.get('path')}")

    prepared_cells = manifest.get("cells", [])
    if len(prepared_cells) != 15 or {row.get("index") for row in prepared_cells} != set(range(15)):
        issues.append("cells")
    for row in prepared_cells:
        if row.get("qualification_only") is not True or row.get("qualification_claim") != "none":
            issues.append(f"cell_contract:{row.get('index')}")
        prepared_binding = {"path": row.get("prepared"), "sha256": row.get("prepared_sha256")}
        ok, reason = _verify_binding(prepared_binding)
        binding_results[f"prepared_cell:{row.get('index')}"] = {
            "pass": ok, "reason": reason, **prepared_binding
        }
        if not ok:
            issues.append(f"prepared_cell:{row.get('index')}")

    return {
        "schema": "core.f4.tallwall120.qualification_evaluation.v1",
        "scope_id": manifest.get("scope_id"),
        "revision_id": manifest.get("revision_id"),
        "qualification_claim": "none",
        "static_manifest": str(manifest_path),
        "static_manifest_sha256": digest(manifest_path),
        "static_contract_pass": not issues,
        "static_issues": issues,
        "binding_results": binding_results,
        "cell_count": 15,
        "scheduled_solver_cells": sorted(scheduled),
        "reused_canary_cells": sorted(reused),
        "matrix_complete": False,
        "T1_numerical": False,
        "promotion_status": "blocked_until_14_scheduled_products_and_all_gates",
    }


def _parse_steps_and_dt_min(text: str) -> dict:
    steps = re.search(r"Steps of simulation\.*\s*:\s*([\d,]+)", text)
    minimum = re.search(r"^DtMin=([\d.eE+-]+)", text, re.M)
    return {
        "steps": int(steps.group(1).replace(",", "")) if steps else None,
        "dt_min_s": float(minimum.group(1)) if minimum else None,
    }


def _artifact_hashes(job: dict) -> dict:
    return {
        item["path"]: item["sha256"]
        for item in job.get("result", {}).get("artifact_index", job.get("result", {}).get("outputs", []))
    }


def _archive_job(archive_root: Path, job_id: str) -> dict | None:
    """Adapt a verified archive receipt to the worker-product interface."""
    folder = Path(archive_root) / job_id
    receipt_path = folder / "archive.json"
    if not receipt_path.is_file():
        return None
    receipt = load(receipt_path)
    if receipt.get("execution_status") != "succeeded":
        return None
    return {
        "job_id": job_id,
        "status": "succeeded",
        "attempt_dir": str(folder),
        "result": {"artifact_index": receipt.get("outputs", [])},
        "archive_receipt": {
            "path": str(receipt_path),
            "sha256": digest(receipt_path),
            "schema": receipt.get("schema"),
            "scientific_status": receipt.get("scientific_status"),
        },
    }


def _completed_product(job: dict, expected_case_id: str) -> tuple[dict | None, dict | None, dict]:
    """Read a completed worker product, with hashes checked against its receipt."""
    if job.get("status") != "succeeded":
        return None, None, {"status": job.get("status", "missing")}
    product = Path(job.get("attempt_dir", "")) / "product"
    audit_path, observations_path = product / "audit.json", product / "observations.json"
    if not audit_path.is_file() or not observations_path.is_file():
        return None, None, {"status": "missing_required_outputs", "product": str(product)}
    indexed = _artifact_hashes(job)
    hash_pass = all(
        indexed.get(f"product/{path.name}") == digest(path)
        for path in (audit_path, observations_path)
    )
    audit, observations = load(audit_path), load(observations_path)
    gate_pass = bool(
        hash_pass
        and audit.get("case_id") == expected_case_id
        and audit.get("hard_integrity_pass") is True
        and audit.get("source_mass_gate_pass") is True
        and audit.get("event_window_complete") is True
    )
    return audit, observations, {
        "status": "succeeded",
        "product": str(product),
        "audit_sha256": digest(audit_path),
        "observations_sha256": digest(observations_path),
        "artifact_hash_gate": hash_pass,
        "hard_mass_event_gate": gate_pass,
    }


def evaluate(
    manifest_path: Path,
    runtime_root: Path | None = None,
    archive_root: Path | None = None,
) -> dict:
    """Evaluate available products; missing cells remain explicit and fail closed."""
    result = verify_static_manifest(manifest_path)
    manifest = load(manifest_path)
    if not result["static_contract_pass"]:
        return result

    rows_by_index = {row["index"]: row for row in manifest["cells"]}
    cells: list[dict] = []
    observations: dict[tuple[float, float, str], dict] = {}
    solver_logs: dict[tuple[float, float, str], str] = {}

    # The canary is a read-only reuse row.  It is accepted into the matrix
    # accounting only after the manifest has verified every bound artifact.
    reuse = manifest["cell12_reuse"]
    evidence = reuse["evidence_bindings"]
    canary_result = load(Path(evidence["canary_result"]["path"]))
    canary_audit = load(Path(evidence["canary_audit"]["path"]))
    canary_obs = load(Path(evidence["canary_observations_v2"]["path"]))
    canary_ok = bool(
        canary_result.get("hard_integrity_pass") is True
        and canary_result.get("source_mass_gate_pass") is True
        and canary_result.get("event_window_complete") is True
    )
    c12 = rows_by_index[12]
    if canary_ok:
        observations[(float(c12["q"]), float(c12["dp_m"]), c12["design_cell"])] = canary_obs
    cells.append({
        "index": 12,
        "case_id": c12["case_id"],
        "status": "reused_canary" if canary_ok else "reused_canary_failed",
        "passed": canary_ok,
        "solver_rerun": False,
        "range_qualification_inherited": False,
        "source_receipt": reuse["root_integration"],
        "audit": {"path": evidence["canary_audit"]["path"], "sha256": evidence["canary_audit"]["sha256"]},
        "observations": {"path": evidence["canary_observations_v2"]["path"], "sha256": evidence["canary_observations_v2"]["sha256"]},
    })

    if runtime_root is None and archive_root is None:
        pending = [i for i in sorted(result["scheduled_solver_cells"])]
        result.update({
            "cells": sorted(cells, key=lambda row: row["index"]),
            "missing": [{"index": i, "case_id": rows_by_index[i]["case_id"], "status": "runtime_not_supplied"} for i in pending],
            "failures": [],
            "matrix_complete": False,
            "T1_numerical": False,
        })
        return result

    jobs = {job["job_id"]: job for job in Store(runtime_root).jobs()} if runtime_root is not None else {}
    missing = []
    failures = []
    for index in sorted(result["scheduled_solver_cells"]):
        row = rows_by_index[index]
        job_id = row["job_id"]
        job = jobs.get(job_id)
        if (job is None or job.get("status") != "succeeded") and archive_root is not None:
            archived = _archive_job(archive_root, job_id)
            if archived is not None:
                job = archived
        if job is None:
            missing.append({"index": index, "case_id": row["case_id"], "job_id": job_id, "status": "missing"})
            continue
        audit, obs, status = _completed_product(job, row["case_id"])
        if audit is None or obs is None:
            missing.append({"index": index, "case_id": row["case_id"], "job_id": job_id, **status})
            continue
        passed = bool(status["hard_mass_event_gate"])
        if not passed:
            failures.append({"index": index, "case_id": row["case_id"], "job_id": job_id, **status})
        key = (float(row["q"]), float(row["dp_m"]), row["design_cell"])
        observations[key] = obs
        solver_path = Path(job["attempt_dir"]) / "product/solver/Run.out"
        if solver_path.is_file() and _artifact_hashes(job).get("product/solver/Run.out") == digest(solver_path):
            solver_logs[key] = solver_path.read_text()
        cells.append({
            "index": index,
            "case_id": row["case_id"],
            "job_id": job_id,
            "status": "succeeded",
            "passed": passed,
            "audit": {"path": str(Path(job["attempt_dir"]) / "product/audit.json"), "sha256": status["audit_sha256"]},
            "observations": {"path": str(Path(job["attempt_dir"]) / "product/observations.json"), "sha256": status["observations_sha256"]},
            **{k: status[k] for k in ("artifact_hash_gate", "hard_mass_event_gate")},
        })

    cells.sort(key=lambda row: row["index"])
    gates = manifest["gates"]
    comparisons = []
    spatial_pass = not missing and not failures
    independent_pass = spatial_pass
    temporal_pass = spatial_pass
    for q in (0.0, 0.5, 1.0, 0.25, 0.75):
        middle = observations.get((q, 0.0075, "spatial"))
        fine = observations.get((q, 0.005, "spatial"))
        if middle is None or fine is None:
            spatial_pass = False
            if q in (0.25, 0.75):
                independent_pass = False
            continue
        error = aligned_difference(middle, fine)
        passed = error["maximum"] <= gates["spatial_max_absolute_normalized_difference"]
        record = {"q": q, "kind": "production_fine", "passed": passed, **error}
        if q in (0.0, 0.5, 1.0):
            coarse = observations.get((q, 0.01, "spatial"))
            if coarse is None:
                passed = False
            else:
                cp = aligned_difference(coarse, middle)
                cf = aligned_difference(coarse, fine)
                monotone = error["maximum"] <= cp["maximum"] + 1e-12
                passed &= max(cp["maximum"], cf["maximum"]) <= gates["spatial_max_absolute_normalized_difference"] and monotone
                record.update(coarse_production=cp, coarse_fine=cf, monotone_refinement=monotone)
        record["passed"] = bool(passed)
        comparisons.append(record)
        spatial_pass &= bool(passed)
        if q in (0.25, 0.75):
            independent_pass &= bool(passed)
    baseline = observations.get((0.5, 0.0075, "spatial"))
    for kind in ("internal_time", "native_output"):
        other = observations.get((0.5, 0.0075, kind))
        if baseline is None or other is None:
            temporal_pass = False
            continue
        error = aligned_difference(baseline, other)
        passed = error["maximum"] <= gates["spatial_max_absolute_normalized_difference"] * gates["temporal_fraction_of_spatial_budget"]
        actual = None
        if kind == "internal_time":
            actual = time_step_evidence(
                solver_logs.get((0.5, 0.0075, "spatial"), ""),
                solver_logs.get((0.5, 0.0075, kind), ""),
            )
            passed = bool(passed and actual["passed"])
        temporal_pass &= bool(passed)
        comparisons.append({"q": 0.5, "kind": kind, "passed": passed, "actual_step_evidence": actual, **error})

    checks = {
        "static_contract": result["static_contract_pass"],
        "matrix_complete": len(cells) == 15 and not missing,
        "all_case_hard_mass_event_gates": len(cells) == 15 and not failures and not missing,
        "spatial": bool(spatial_pass),
        "independent_checks": bool(independent_pass),
        "time_and_output": bool(temporal_pass),
        "cell12_reuse_verified": canary_ok,
        "cell12_reuse_does_not_inherit_qualification": True,
    }
    result.update({
        "cells": cells,
        "missing": missing,
        "failures": failures,
        "comparisons": comparisons,
        "checks": checks,
        "matrix_complete": checks["matrix_complete"],
        "T1_numerical": all(checks.values()),
        "promotion_status": "qualified_candidate_pending_root_review" if all(checks.values()) else "blocked_until_all_gates",
    })
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--archive-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(args.manifest, args.runtime_root, args.archive_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({
        "static_contract_pass": result["static_contract_pass"],
        "matrix_complete": result["matrix_complete"],
        "T1_numerical": result["T1_numerical"],
        "qualification_claim": result["qualification_claim"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
