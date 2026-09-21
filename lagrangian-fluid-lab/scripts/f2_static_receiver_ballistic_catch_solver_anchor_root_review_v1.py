#!/usr/bin/env python3
"""Authorize one protected GPU solver anchor for the fresh F2 scope.

The review runs only after the fresh CPU/native preflight has passed its hard
input gates.  It writes a hash-bound job specification and a second review
receipt, but does not submit the queue job.  Registry, qualification matrix,
and scientific numerator writes remain closed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.core_runtime import validate_spec  # noqa: E402
from scripts.f2_static_receiver_ballistic_catch_definition_writer_v1 import (  # noqa: E402
    BASE, CASE_ID, DEFAULT_CONTRACT, DEFAULT_DEFINITION, sha256,
)
from scripts.f2_static_receiver_ballistic_catch_preflight_v1 import (  # noqa: E402
    GENERATED_PREFIX, PREFLIGHT_RECEIPT, verify_preflight,
)
from scripts.f2_static_receiver_ballistic_catch_root_review_v1 import (  # noqa: E402
    ROOT_RECEIPT, verify_receipt as verify_cpu_root,
)


ANCHOR_DIR = BASE / "solver-anchor-v1"
REVIEW_OUTPUT = ANCHOR_DIR / "solver-anchor-root-review-v1.json"
JOB_OUTPUT = ANCHOR_DIR / "solver-anchor-job-spec-v1.json"
WORKER = LAB_ROOT / "scripts/f2_static_receiver_ballistic_catch_solver_worker_v1.py"
SOLVER = LAB_ROOT / "vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"
SCHEMA = "core.f2.static_receiver_ballistic_catch.solver_anchor_root_review.v1"
JOB_SCHEMA = "core.runtime.job_spec.v1"
JOB_ID = "f2-static-receiver-ballistic-catch-q05-anchor-v1"


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def check_ref(item: dict[str, Any], label: str) -> Path:
    path = Path(item["path"]).resolve()
    if not path.is_file() or path.stat().st_size != item.get("bytes") or sha256(path) != item.get("sha256"):
        raise ValueError(f"stale binding: {label}")
    return path


def _input_refs() -> list[dict[str, Any]]:
    return [
        ref(DEFAULT_DEFINITION, "fresh literal Definition"),
        ref(DEFAULT_CONTRACT, "Definition contract"),
        ref(PREFLIGHT_RECEIPT, "CPU/native preflight receipt"),
        ref(GENERATED_PREFIX.with_suffix(".xml"), "GenCase generated XML"),
        ref(GENERATED_PREFIX.with_suffix(".bi4"), "GenCase initial native frame"),
        ref(SOLVER, "pinned DualSPHysics solver"),
        ref(WORKER, "protected solver worker"),
    ]


def build_job_spec() -> dict[str, Any]:
    verify_cpu_root(ROOT_RECEIPT)
    preflight = _json(PREFLIGHT_RECEIPT)
    verify_preflight(PREFLIGHT_RECEIPT)
    if preflight.get("status") != "cpu_native_preflight_pass" or preflight.get("qualified") is not False:
        raise ValueError("CPU/native preflight is not a zero-credit hard pass")
    if not WORKER.is_file() or not SOLVER.is_file():
        raise FileNotFoundError("solver worker or binary missing")
    output_root = ANCHOR_DIR / "runtime-output"
    argv = [
        str(LAB_ROOT / ".venv/bin/python"), str(WORKER),
        "--output", "{attempt_dir}/product",
        "--generated-prefix", str(GENERATED_PREFIX),
        "--time-max", "1.5", "--output-interval", "0.005",
    ]
    spec = {
        "schema": JOB_SCHEMA,
        "job_id": JOB_ID,
        "logical_id": JOB_ID,
        "attempt_role": "protected_solver_anchor",
        "category": "solver_f2_static_receiver_anchor",
        "family": "F2",
        "scope_id": "F2_static_receiver_ballistic_catch_x_v1",
        "revision_id": "F2_static_receiver_ballistic_catch_v1",
        "case_id": CASE_ID,
        "host": "ada",
        "cwd": str(LAB_ROOT),
        "source_lab": str(LAB_ROOT),
        "argv": argv,
        "input_files": _input_refs(),
        "required_outputs": ["product/result.json", "product/solver.stdout.log", "product/worker-status.json"],
        "resources": {"cpu_cores": 4, "ram_mib": 16384, "gpu_peak_mib": 8192, "io_weight": 0.5},
        "timeout_seconds": 7200,
        "depends_on": [],
        "qualification_claim": "none; one protected solver anchor only",
        "matrix_credit": 0,
        "registry_mutation": 0,
        "ledger_mutation": 1,
        "queue_mutation": 1,
        "solver_launch": True,
        "gpu_launch": True,
        "worker_contract": "one solver invocation with scheduler-provided CUDA_VISIBLE_DEVICES; raw result only",
        "output_namespace": str(output_root.resolve()),
    }
    return validate_spec(spec)


def write_review() -> dict[str, Any]:
    if REVIEW_OUTPUT.exists() or JOB_OUTPUT.exists():
        raise FileExistsError("solver anchor root-review namespace already exists")
    ANCHOR_DIR.mkdir(parents=True, exist_ok=True)
    spec = build_job_spec()
    JOB_OUTPUT.write_text(json.dumps(spec, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    refs = {item["path"]: item for item in spec["input_files"]}
    receipt = {
        "schema": SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "authorized_one_protected_gpu_solver_anchor_pending_submission",
        "scientific_status": "anchor_only_zero_credit",
        "qualification_claim": "none",
        "matrix_credit": 0,
        "family": "F2",
        "scope_id": "F2_static_receiver_ballistic_catch_x_v1",
        "case_id": CASE_ID,
        "cpu_root_review": ref(ROOT_RECEIPT, "CPU/native root review"),
        "preflight": ref(PREFLIGHT_RECEIPT, "CPU/native hard preflight"),
        "job_spec": ref(JOB_OUTPUT, "protected solver job specification"),
        "input_bindings": list(spec["input_files"]),
        "authorization": {
            "solver_invocations": 1, "gpu_launch": True, "queue_submission": True,
            "ledger_mutation": 1, "registry_mutation": 0, "matrix_submission": 0,
            "model_training": False, "material_training": False,
        },
        "denominator": {"parent_scope_rows": 15, "anchor_credit": 0,
                        "same_input_retry": False, "event_censor_is_failure": True},
        "postconditions": [
            "raw solver output is retained under the attempt archive",
            "Run.out and saved frame inventory are independently audited",
            "native conversion and event audit occur in a separate postrun step",
            "no registry or qualification-matrix mutation",
        ],
        "submission": {"submitted": False, "queue_root": str(LAB_ROOT / "campaigns/core-v1/runtime")},
    }
    REVIEW_OUTPUT.write_text(json.dumps(receipt, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return receipt


def verify_review(path: Path = REVIEW_OUTPUT) -> dict[str, Any]:
    value = _json(path)
    if value.get("schema") != SCHEMA or value.get("status") != "authorized_one_protected_gpu_solver_anchor_pending_submission":
        raise ValueError("solver anchor review schema/status mismatch")
    if value.get("qualification_claim") != "none" or value.get("matrix_credit") != 0:
        raise ValueError("solver anchor review carries scientific credit")
    if value.get("authorization", {}).get("solver_invocations") != 1:
        raise ValueError("solver authorization is not exact-one")
    for key in ("registry_mutation", "matrix_submission", "model_training", "material_training"):
        if value["authorization"].get(key) not in (0, False):
            raise ValueError(f"solver review opened protected path: {key}")
    check_ref(value["cpu_root_review"], "cpu root review")
    check_ref(value["preflight"], "preflight")
    job = check_ref(value["job_spec"], "job spec")
    spec = _json(job)
    validate_spec(spec)
    if spec.get("job_id") != JOB_ID or spec.get("qualification_claim", "").startswith("none") is False:
        raise ValueError("job spec identity/credit mismatch")
    if spec.get("solver_launch") is not True or spec.get("gpu_launch") is not True:
        raise ValueError("job spec does not authorize solver/GPU anchor")
    for item in value.get("input_bindings", []):
        check_ref(item, item.get("role", "input"))
    return {"status": "ok", "job_id": JOB_ID, "submitted": bool(value.get("submission", {}).get("submitted")),
            "qualification_claim": value.get("qualification_claim"), "matrix_credit": value.get("matrix_credit"),
            "solver_invocations": 1, "queue_submission_authorized": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("write")
    p = sub.add_parser("verify"); p.add_argument("--receipt", type=Path, default=REVIEW_OUTPUT)
    p = sub.add_parser("job-spec"); p.add_argument("--output", type=Path, default=JOB_OUTPUT)
    args = parser.parse_args()
    if args.command == "write": result = write_review()
    elif args.command == "verify": result = verify_review(args.receipt)
    else:
        spec = build_job_spec(); args.output.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n"); result = spec
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
