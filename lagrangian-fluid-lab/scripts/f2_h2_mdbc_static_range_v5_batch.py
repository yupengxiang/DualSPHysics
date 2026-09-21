#!/usr/bin/env python3
"""Prepare a root-review-only first batch for the F2 H2-v5 scope.

The v5 matrix has a fixed fifteen-row qualification denominator.  This module
creates an independent admission record and eight *draft* job specifications
for the first eight registered rows.  It never submits a request, calls the
solver, invokes CUDA, or mutates the Core ledger/registry.  A later root review
may consume the immutable inputs and issue a separate executable job set.

The collector is deliberately terminal-evidence aware: missing attempts,
infrastructure failures, hard-integrity failures, and event censoring remain in
the fifteen-row denominator.  A successful first batch therefore cannot claim
T1 or shrink the denominator.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Iterable

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

SCOPE_ID = "F2_H2_mdbc_static_range_qualification_v5"
REVISION_ID = "F2_H2_mdbc_static_range_mdbc_v5_top_layer_lateral_lattice"
CANDIDATE_ID = SCOPE_ID
FAMILY = "F2"
MATRIX_SCHEMA = "core.f2.h2_mdbc.static_range_v5_preparation.v1"
CELL_SCHEMA = "core.f2.h2_mdbc.static_range_v5.cell_prepared.v1"
ADMISSION_SCHEMA = "core.f2.h2_mdbc.static_range_v5.batch_admission.v1"
JOB_SCHEMA = "core.cfd.job.v1"
JOB_MANIFEST_SCHEMA = "core.f2.h2_mdbc.static_range_v5.batch_job_specs.v1"
EVIDENCE_SCHEMA = "core.f2.h2_mdbc.static_range_v5.batch_execution_evidence.v1"
FIXED_DENOMINATOR = 15
# The first batch is fixed by registered row order.  It is not survivor
# selection and it does not imply a 32-row qualification denominator.
FIRST_BATCH_INDICES = tuple(range(8))

DEFAULT_CANDIDATE = LAB_ROOT / "campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-candidate-v5.json"
DEFAULT_MATRIX = LAB_ROOT / (
    "campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-v5/"
    "prepared-20260920-v5-all/matrix-preparation.json"
)
DEFAULT_CANARY = LAB_ROOT / (
    "campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-v5/"
    "runtime-canary-evidence-cell11-v1.json"
)


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    partial.replace(path)


def ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": str(path), "sha256": digest(path), "bytes": path.stat().st_size, "role": role}


def _resolve(lab: Path, value: str | Path) -> Path:
    value = Path(value)
    path = value if value.is_absolute() else Path(lab) / value
    return path.resolve()


def _bool_zero(value: Any) -> bool:
    return value in (False, 0)


def _validate_candidate(candidate_path: Path) -> dict[str, Any]:
    candidate = load(candidate_path)
    if candidate.get("candidate_id") != CANDIDATE_ID or candidate.get("scope_id") != SCOPE_ID:
        raise ValueError("candidate identity does not bind static v5 scope")
    if candidate.get("revision_id") != REVISION_ID:
        raise ValueError("candidate revision does not bind static v5 sampling")
    if candidate.get("qualification_only") is not True or candidate.get("qualified") is not False:
        raise ValueError("candidate must remain qualification-only and unqualified")
    if candidate.get("T1_numerical") is not False:
        raise ValueError("candidate must retain T1_numerical=false")
    for key in ("central_ledger_mutation", "registry_mutation"):
        if not _bool_zero(candidate.get(key)):
            raise ValueError(f"candidate permits {key}")
    cells = candidate.get("qualification_design", {}).get("cells", [])
    if len(cells) != FIXED_DENOMINATOR:
        raise ValueError("candidate qualification design is not fifteen rows")
    denominator = candidate.get("failure_denominator", {})
    if denominator.get("fixed_registered_cell_denominator") != FIXED_DENOMINATOR:
        raise ValueError("candidate failure denominator is not fixed at fifteen")
    return candidate


def _validate_matrix(lab: Path, matrix_path: Path, candidate: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    matrix = load(matrix_path)
    if matrix.get("schema") != MATRIX_SCHEMA or matrix.get("scope_id") != SCOPE_ID:
        raise ValueError("matrix schema/scope mismatch")
    if matrix.get("candidate_id") != candidate.get("candidate_id"):
        raise ValueError("matrix candidate mismatch")
    if matrix.get("registered_cell_count") != FIXED_DENOMINATOR:
        raise ValueError("matrix denominator is not fifteen")
    if matrix.get("qualification_only") is not True or matrix.get("T1_numerical") is not False:
        raise ValueError("matrix qualification controls are open")
    rows = matrix.get("cells", [])
    if len(rows) != FIXED_DENOMINATOR:
        raise ValueError("matrix does not contain fifteen rows")
    indices = {int(row.get("index", -1)) for row in rows}
    if indices != set(range(FIXED_DENOMINATOR)):
        raise ValueError("matrix indices are not the fixed 0..14 denominator")
    for row in rows:
        if row.get("preflight_pass") is not True or row.get("qualification_credit") is not False:
            raise ValueError(f"matrix row {row.get('index')} is not passed zero-credit CPU/native closure")
        prepared = _resolve(lab, row.get("prepared", ""))
        if not prepared.is_file() or row.get("prepared_sha256") != digest(prepared):
            raise ValueError(f"matrix row {row.get('index')} prepared hash mismatch")
        payload = load(prepared)
        if payload.get("schema") != CELL_SCHEMA or payload.get("scope_id") != SCOPE_ID:
            raise ValueError(f"matrix row {row.get('index')} source cell schema mismatch")
        if int(payload.get("index", -1)) != int(row["index"]) or payload.get("case_id") != row.get("case_id"):
            raise ValueError(f"matrix row {row.get('index')} source cell identity mismatch")
        if payload.get("preflight_pass") is not True or payload.get("qualification_only") is not True:
            raise ValueError(f"matrix row {row.get('index')} source cell is not qualification-only preflight")
        for key in ("solver_invoked", "gpu_invoked", "queue_mutated", "ledger_mutated", "registry_mutated"):
            if payload.get(key) is not False:
                raise ValueError(f"matrix row {row.get('index')} opens forbidden control {key}")
    return matrix, sorted(rows, key=lambda row: int(row["index"]))


def _validate_canary(canary_path: Path) -> dict[str, Any]:
    canary = load(canary_path)
    if canary.get("scope_id") != SCOPE_ID or canary.get("schema") != "core.f2.h2_mdbc.static_range_v5.runtime_canary_evidence.v1":
        raise ValueError("cell-11 canary scope/schema mismatch")
    if canary.get("matrix_credit") != 0 or canary.get("qualified") is not False or canary.get("T1_numerical") is not False:
        raise ValueError("cell-11 canary is not explicitly zero-credit")
    if canary.get("qualification_claim") != "none":
        raise ValueError("cell-11 canary qualification claim is not neutral")
    constraints = canary.get("execution_constraints", {})
    if constraints.get("registry_mutation") != 0 or constraints.get("ledger_mutation") != 0:
        raise ValueError("cell-11 canary has forbidden ledger/registry mutation")
    if canary.get("hard_integrity", {}).get("pass") is not True:
        raise ValueError("cell-11 canary is not a positive hard-integrity input")
    return canary


def _validate_optional_root_review(root_review_path: Path | None, *, indices: tuple[int, ...]) -> dict[str, Any]:
    if root_review_path is None:
        return {
            "status": "missing",
            "decision_required": "approved_for_8_cell_canary",
            "authorized_cell_indices": list(indices),
            "solver_launch": "requires explicit root approval",
            "gpu_launch": "requires explicit root approval",
            "job_spec_creation": "requires explicit root approval",
            "queue_mutation": "requires explicit root approval",
            "ledger_mutation": False,
            "registry_mutation": False,
        }
    review = load(root_review_path)
    if review.get("schema") != "core.root_review.v1" or review.get("scope_id") != SCOPE_ID:
        raise ValueError("batch root review schema/scope mismatch")
    if review.get("decision") not in {"approved_for_8_cell_canary", "approved_for_qualification_batch_8"}:
        raise ValueError("root review does not authorize an eight-cell batch")
    if {int(value) for value in review.get("authorized_cell_indices", [])} != set(indices):
        raise ValueError("root review indices do not equal the fixed first batch")
    auth = review.get("authorization", {})
    for key in ("solver_launch", "gpu_launch", "job_spec_creation", "queue_mutation"):
        if auth.get(key) is not True:
            raise ValueError(f"root review does not authorize {key}")
    for key in ("ledger_mutation", "registry_mutation", "material_training", "model_training"):
        if auth.get(key) is not False:
            raise ValueError(f"root review does not prohibit {key}")
    if review.get("qualification_claim") != "none":
        raise ValueError("root review qualification claim is not neutral")
    return {"status": "approved", "review": ref(root_review_path, "eight-cell root review")}


def build_admission(*, lab: Path, candidate_path: Path = DEFAULT_CANDIDATE,
                    matrix_path: Path = DEFAULT_MATRIX, canary_path: Path = DEFAULT_CANARY,
                    root_review_path: Path | None = None) -> dict[str, Any]:
    lab = Path(lab).resolve()
    candidate_path = _resolve(lab, candidate_path)
    matrix_path = _resolve(lab, matrix_path)
    canary_path = _resolve(lab, canary_path)
    candidate = _validate_candidate(candidate_path)
    matrix, rows = _validate_matrix(lab, matrix_path, candidate)
    canary = _validate_canary(canary_path)
    indices = FIRST_BATCH_INDICES
    root_state = _validate_optional_root_review(
        _resolve(lab, root_review_path) if root_review_path is not None else None,
        indices=indices,
    )
    selected = [row for row in rows if int(row["index"]) in indices]
    if len(selected) != len(indices):
        raise ValueError("fixed first batch is not fully represented")
    refs = {
        "candidate": ref(candidate_path, "v5 candidate card"),
        "matrix": ref(matrix_path, "v5 fifteen-row CPU/native matrix"),
        "canary": ref(canary_path, "cell-11 runtime canary, zero credit"),
        "adapter": ref(Path(__file__), "independent batch admission/collector code"),
    }
    return {
        "schema": ADMISSION_SCHEMA,
        "created_at_utc": stamp(),
        "family": FAMILY,
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "candidate_id": CANDIDATE_ID,
        "status": "root_review_ready",
        "decision": "eligible_for_root_review_only",
        "qualification_only": True,
        "qualified": False,
        "T1_numerical": False,
        "fixed_denominator": {
            "registered_cell_denominator": FIXED_DENOMINATOR,
            "all_rows_in_denominator": True,
            "failed_rows_retained": True,
            "unprepared_rows_are_not_successes": True,
            "survivor_renormalization": False,
            "qualification_requires": "15/15 independent rows; first batch cannot claim T1",
        },
        "batch": {
            "stage": "first_8_of_fixed_15",
            "requested_size": len(indices),
            "requested_indices": list(indices),
            "case_ids": [row["case_id"] for row in selected],
            "remaining_scope_indices": [index for index in range(FIXED_DENOMINATOR) if index not in indices],
            "fixed_8_to_32_compatible": False,
            "fixed_8_to_32_note": (
                "the Core 8-to-32 production rule is not this scope's qualification denominator; "
                "v5 remains a fixed fifteen-row qualification scope"
            ),
        },
        "source_closure": refs,
        "cell11_canary": {
            "status": canary.get("status"),
            "hard_integrity_pass": canary.get("hard_integrity", {}).get("pass"),
            "event_window_complete": canary.get("event_window", {}).get("complete"),
            "matrix_credit": canary.get("matrix_credit"),
            "qualification_claim": canary.get("qualification_claim"),
        },
        "root_review": root_state,
        "authorization": {
            "solver_launch": False,
            "gpu_launch": False,
            "job_spec_creation": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "material_training": False,
            "model_training": False,
            "submission_status": "not_submitted",
        },
        "failure_policy": {
            "preflight_failure": "retain row in fixed fifteen-row denominator",
            "infrastructure_failure": "retain receipt and classify separately; never drop row",
            "hard_integrity_failure": "retain audit and prohibit same-input retry",
            "event_censor": "retain row as failure; no horizon extension or threshold relaxation",
            "successful_batch_rows": "zero qualification credit until all fifteen rows pass",
        },
    }


def _job_spec(*, lab: Path, admission_path: Path, admission: dict[str, Any],
              candidate_path: Path, matrix_path: Path, row: dict[str, Any],
              output_dir: Path, ordinal: int) -> dict[str, Any]:
    source = _resolve(lab, row["prepared"])
    job_id = f"f2-h2-v5-qualification-batch8-cell{int(row['index']):02d}"
    runtime = (lab / "scripts/f2_h2_mdbc_static_range_v5_runtime.py").resolve()
    adapter = Path(__file__).resolve()
    # This is a review artifact, intentionally carrying a non-runnable command
    # gate.  Root must issue a new review and regenerate an executable runtime
    # view before any solver or queue action.
    return {
        "schema": JOB_SCHEMA,
        "job_id": job_id,
        "logical_id": job_id,
        "attempt_role": "f2_h2_v5_qualification_batch8_draft",
        "category": "qualification_batch_draft",
        "host": "scheduler-selected",
        "source_lab": str(lab),
        "cwd": str(lab),
        "submission_status": "blocked_pending_root_review",
        "root_review_required": True,
        "argv": [],
        "runtime_prepare_argv_template": [
            str(lab / ".venv/bin/python"), str(runtime), "--lab-root", str(lab),
            "prepare-runtime", "--source-prepared", str(source),
            "--candidate", str(candidate_path), "--matrix", str(matrix_path),
            "--admission", str(admission_path), "--root-review", "<new-eight-cell-root-review>",
            "--output", "{attempt_dir}/runtime", "--cell-index", str(int(row["index"])),
        ],
        "run_argv_template": [
            str(lab / ".venv/bin/python"), str(runtime), "--lab-root", str(lab),
            "run", "--prepared", "{attempt_dir}/runtime/prepared.json",
            "--output", "{attempt_dir}/product",
        ],
        "required_outputs": [
            "product/result.json", "product/trajectory.h5", "product/audit.json",
            "product/prepared.json", "product/worker-status.json",
        ],
        "resources": {"cpu_cores": 2, "ram_mib": 20480, "gpu_peak_mib": 8192, "io_weight": 1},
        "timeout_seconds": 3600,
        "depends_on": [],
        "qualification_claim": "none",
        "qualification_only": True,
        "family": FAMILY,
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "cell_index": int(row["index"]),
        "prepared_case_id": row["case_id"],
        "prepared_source": {"path": str(source), "sha256": row["prepared_sha256"]},
        "registered_denominator": FIXED_DENOMINATOR,
        "batch_index": ordinal,
        "batch_size": len(FIRST_BATCH_INDICES),
        "solver_launch_authorized": False,
        "gpu_launch_authorized": False,
        "job_spec_creation_authorized": False,
        "queue_mutation_authorized": False,
        "ledger_mutation_authorized": False,
        "registry_mutation_authorized": False,
        "qualification_matrix_expanded": False,
        "input_files": [
            ref(admission_path, "batch admission"),
            ref(candidate_path, "v5 candidate card"),
            ref(matrix_path, "v5 fifteen-row matrix"),
            ref(source, "v5 CPU/native prepared cell"),
            ref(runtime, "runtime adapter"),
            ref(adapter, "independent batch adapter"),
        ],
    }


def build_job_specs(*, lab: Path, admission_path: Path, candidate_path: Path = DEFAULT_CANDIDATE,
                    matrix_path: Path = DEFAULT_MATRIX, output_dir: Path) -> dict[str, Any]:
    lab = Path(lab).resolve()
    admission_path = _resolve(lab, admission_path)
    candidate_path = _resolve(lab, candidate_path)
    matrix_path = _resolve(lab, matrix_path)
    admission = load(admission_path)
    if admission.get("schema") != ADMISSION_SCHEMA or admission.get("status") != "root_review_ready":
        raise ValueError("batch admission is not a root-review-ready v5 admission")
    if admission.get("fixed_denominator", {}).get("registered_cell_denominator") != FIXED_DENOMINATOR:
        raise ValueError("admission denominator is not fifteen")
    if admission.get("authorization", {}).get("queue_mutation") != 0:
        raise ValueError("batch admission permits queue mutation")
    candidate = _validate_candidate(candidate_path)
    _, rows = _validate_matrix(lab, matrix_path, candidate)
    selected = [row for row in rows if int(row["index"]) in FIRST_BATCH_INDICES]
    if len(selected) != len(FIRST_BATCH_INDICES):
        raise ValueError("fixed first batch is incomplete")
    output_dir = Path(output_dir).resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"job-spec output is not fresh: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    specs = []
    for ordinal, row in enumerate(selected):
        spec = _job_spec(lab=lab, admission_path=admission_path, admission=admission,
                         candidate_path=candidate_path, matrix_path=matrix_path,
                         row=row, output_dir=output_dir, ordinal=ordinal)
        path = output_dir / f"{spec['job_id']}.json"
        write_json(path, spec)
        specs.append({"job_id": spec["job_id"], "cell_index": spec["cell_index"],
                      "case_id": spec["prepared_case_id"], "path": str(path),
                      "sha256": digest(path), "bytes": path.stat().st_size})
    manifest = {
        "schema": JOB_MANIFEST_SCHEMA,
        "created_at_utc": stamp(),
        "family": FAMILY,
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "admission": ref(admission_path, "batch admission"),
        "registered_denominator": FIXED_DENOMINATOR,
        "batch_size": len(specs),
        "cell_indices": [item["cell_index"] for item in specs],
        "job_specs": specs,
        "status": "root_review_ready_not_submitted",
        "execution_controls": {
            "solver_invoked": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
        },
    }
    write_json(output_dir / "batch-job-specs.json", manifest)
    return manifest


def _find_attempt_product(attempt_dir: Path) -> tuple[Path, Path]:
    attempt_dir = Path(attempt_dir).resolve()
    product = attempt_dir / "product"
    receipt = attempt_dir / "result.json"
    return product, receipt


def _classify_attempt(*, spec: dict[str, Any], attempt_dir: Path) -> dict[str, Any]:
    product, receipt_path = _find_attempt_product(attempt_dir)
    required = [product / "result.json", product / "audit.json", product / "prepared.json",
                product / "trajectory.h5", receipt_path]
    if not all(path.is_file() for path in required):
        missing = [str(path) for path in required if not path.is_file()]
        return {"status": "infrastructure_failed", "attempt_dir": str(attempt_dir),
                "missing_outputs": missing, "pass": False}
    receipt = load(receipt_path)
    result = load(product / "result.json")
    audit = load(product / "audit.json")
    prepared = load(product / "prepared.json")
    if result.get("scope_id") != SCOPE_ID or prepared.get("scope_id") != SCOPE_ID:
        return {"status": "infrastructure_failed", "attempt_dir": str(attempt_dir),
                "reason": "scope binding mismatch", "pass": False}
    if result.get("cell_index") != spec.get("cell_index"):
        return {"status": "infrastructure_failed", "attempt_dir": str(attempt_dir),
                "reason": "cell index mismatch", "pass": False}
    if spec.get("prepared_case_id") != result.get("case_id"):
        return {"status": "infrastructure_failed", "attempt_dir": str(attempt_dir),
                "reason": "case identity mismatch", "pass": False}
    if receipt.get("execution_status") != "succeeded" or receipt.get("returncode") != 0:
        return {"status": "infrastructure_failed", "attempt_dir": str(attempt_dir),
                "reason": "nonzero or incomplete execution receipt", "pass": False,
                "receipt": ref(receipt_path, "execution receipt")}
    if result.get("qualification_claim", "").startswith("none") is False:
        return {"status": "scientific_failed", "attempt_dir": str(attempt_dir),
                "reason": "qualification claim is not neutral", "pass": False}
    if result.get("qualified") is not False or result.get("registry_mutation") not in (0, False):
        return {"status": "scientific_failed", "attempt_dir": str(attempt_dir),
                "reason": "result opens qualification or registry mutation", "pass": False}
    if audit.get("hard_integrity_pass") is not True or audit.get("requested_horizon_reached") is not True:
        return {"status": "scientific_failed", "attempt_dir": str(attempt_dir),
                "reason": "hard integrity or requested horizon failed", "pass": False,
                "audit": ref(product / "audit.json", "hard integrity audit")}
    if audit.get("event_window_complete") is not True:
        return {"status": "event_censored", "attempt_dir": str(attempt_dir),
                "reason": "registered event window is incomplete", "pass": False,
                "audit": ref(product / "audit.json", "hard/event audit")}
    return {
        "status": "passed_zero_credit",
        "attempt_dir": str(attempt_dir),
        "pass": True,
        "result": ref(product / "result.json", "worker result"),
        "audit": ref(product / "audit.json", "hard/event audit"),
        "trajectory": ref(product / "trajectory.h5", "native trajectory"),
        "receipt": ref(receipt_path, "execution receipt"),
    }


def collect_evidence(*, admission_path: Path, jobs_manifest_path: Path,
                     attempt_dirs: dict[str, Path] | None, output: Path) -> dict[str, Any]:
    admission_path = Path(admission_path).resolve()
    jobs_manifest_path = Path(jobs_manifest_path).resolve()
    admission = load(admission_path)
    manifest = load(jobs_manifest_path)
    if admission.get("schema") != ADMISSION_SCHEMA or admission.get("scope_id") != SCOPE_ID:
        raise ValueError("evidence admission scope/schema mismatch")
    if manifest.get("schema") != JOB_MANIFEST_SCHEMA or manifest.get("scope_id") != SCOPE_ID:
        raise ValueError("evidence job manifest scope/schema mismatch")
    if manifest.get("registered_denominator") != FIXED_DENOMINATOR or manifest.get("batch_size") != len(FIRST_BATCH_INDICES):
        raise ValueError("evidence batch denominator mismatch")
    attempt_dirs = {str(key): Path(value).resolve() for key, value in (attempt_dirs or {}).items()}
    batch_by_index: dict[int, dict[str, Any]] = {}
    for item in manifest.get("job_specs", []):
        spec_path = Path(item["path"]).resolve()
        if not spec_path.is_file() or digest(spec_path) != item.get("sha256"):
            raise ValueError(f"job spec hash mismatch: {spec_path}")
        spec = load(spec_path)
        if spec.get("scope_id") != SCOPE_ID or spec.get("qualification_only") is not True:
            raise ValueError("job spec opens scope controls")
        if spec.get("registered_denominator") != FIXED_DENOMINATOR:
            raise ValueError("job spec denominator mismatch")
        idx = int(spec["cell_index"])
        if idx in batch_by_index:
            raise ValueError("duplicate batch cell index")
        if spec.get("ledger_mutation_authorized") is not False or spec.get("registry_mutation_authorized") is not False:
            raise ValueError("job spec permits ledger or registry mutation")
        attempt = attempt_dirs.get(spec["job_id"])
        batch_by_index[idx] = {
            "job_id": spec["job_id"], "case_id": spec["prepared_case_id"],
            "job_spec": ref(spec_path, "batch job spec"),
            "status": "unattempted", "pass": False,
        }
        if attempt is not None:
            batch_by_index[idx].update(_classify_attempt(spec=spec, attempt_dir=attempt))
    rows = []
    for index in range(FIXED_DENOMINATOR):
        item = batch_by_index.get(index)
        if item is None:
            rows.append({"index": index, "batch_member": False, "status": "unattempted",
                         "pass": False, "qualification_credit": False})
        else:
            rows.append({"index": index, "batch_member": True, "job_id": item["job_id"],
                         "case_id": item["case_id"], "status": item["status"],
                         "pass": item.get("pass", False), "qualification_credit": False,
                         **{key: value for key, value in item.items()
                            if key not in {"job_id", "case_id", "status", "pass"}}})
    attempted = [row for row in rows if row["batch_member"] and row["status"] != "unattempted"]
    passed = [row for row in attempted if row["pass"] is True]
    failed = [row for row in attempted if row["pass"] is not True]
    evidence = {
        "schema": EVIDENCE_SCHEMA,
        "created_at_utc": stamp(),
        "family": FAMILY,
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "qualification_only": True,
        "qualified": False,
        "T1_numerical": False,
        "qualification_claim": "none",
        "matrix_credit": 0,
        "admission": ref(admission_path, "batch admission"),
        "job_manifest": ref(jobs_manifest_path, "batch job-spec manifest"),
        "batch": {
            "registered_denominator": FIXED_DENOMINATOR,
            "batch_size": len(FIRST_BATCH_INDICES),
            "batch_indices": list(FIRST_BATCH_INDICES),
            "attempted_count": len(attempted),
            "passed_zero_credit_count": len(passed),
            "failed_or_unresolved_count": len(failed),
            "unattempted_count": FIXED_DENOMINATOR - len(attempted),
        },
        "failure_denominator": {
            "fixed_registered_cell_denominator": FIXED_DENOMINATOR,
            "all_rows_in_denominator": True,
            "failed_rows_are_not_dropped": True,
            "unprepared_rows_are_not_successes": True,
            "survivor_renormalization": False,
            "rows": rows,
        },
        "execution_controls": {
            "solver_invoked_by_collector": False,
            "gpu_invoked_by_collector": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "qualification_matrix_expanded": False,
        },
        "next_gate": (
            "obtain a new root review for exactly the eight indices, then execute only after "
            "the review retains qualification_only and ledger/registry mutation zero; "
            "complete all fifteen rows before any T1 discussion"
        ),
    }
    write_json(Path(output), evidence)
    return evidence


def _parse_attempt_args(values: Iterable[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise ValueError("--attempt values must use JOB_ID=ATTEMPT_DIR")
        job_id, path = value.split("=", 1)
        if not job_id or not path:
            raise ValueError("--attempt values must use JOB_ID=ATTEMPT_DIR")
        result[job_id] = Path(path)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("admit")
    p.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    p.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    p.add_argument("--canary", type=Path, default=DEFAULT_CANARY)
    p.add_argument("--root-review", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("make-jobs")
    p.add_argument("--admission", type=Path, required=True)
    p.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    p.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    p.add_argument("--output-dir", type=Path, required=True)
    p = sub.add_parser("collect")
    p.add_argument("--admission", type=Path, required=True)
    p.add_argument("--job-manifest", type=Path, required=True)
    p.add_argument("--attempt", action="append", default=[])
    p.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    lab = Path(args.lab_root).resolve()
    if args.command == "admit":
        value = build_admission(lab=lab, candidate_path=args.candidate, matrix_path=args.matrix,
                                canary_path=args.canary, root_review_path=args.root_review)
        write_json(_resolve(lab, args.output), value)
        print(json.dumps({"status": value["status"], "decision": value["decision"],
                          "denominator": value["fixed_denominator"]["registered_cell_denominator"],
                          "batch_indices": value["batch"]["requested_indices"]}, indent=2))
    elif args.command == "make-jobs":
        value = build_job_specs(lab=lab, admission_path=args.admission, candidate_path=args.candidate,
                                matrix_path=args.matrix, output_dir=_resolve(lab, args.output_dir))
        print(json.dumps({"status": value["status"], "batch_size": value["batch_size"],
                          "job_specs": value["job_specs"]}, indent=2))
    else:
        value = collect_evidence(admission_path=_resolve(lab, args.admission),
                                 jobs_manifest_path=_resolve(lab, args.job_manifest),
                                 attempt_dirs=_parse_attempt_args(args.attempt), output=_resolve(lab, args.output))
        print(json.dumps({"schema": value["schema"], "matrix_credit": value["matrix_credit"],
                          "batch": value["batch"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
