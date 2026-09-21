#!/usr/bin/env python3
"""Authorize one repaired-infrastructure retry of the F2 solver anchor.

The first anchor exited before loading the solver because the worker omitted
the official shared-library path.  This review accepts exactly one retry for
that infrastructure defect, keeps the scientific Definition/BI4/input hashes
unchanged, and continues to forbid registry and qualification-matrix writes.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
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
ORIGINAL_ATTEMPT = LAB_ROOT / "campaigns/core-v1/runtime/attempts/f2-static-receiver-ballistic-catch-q05-anchor-v1/20260921T111451-a4575f1d2a18"
ORIGINAL_RESULT = ORIGINAL_ATTEMPT / "result.json"
ORIGINAL_PRODUCT_RESULT = ORIGINAL_ATTEMPT / "product/result.json"
ORIGINAL_STDOUT = ORIGINAL_ATTEMPT / "product/solver.stdout.log"
REVIEW_OUTPUT = ANCHOR_DIR / "infra-retry-root-review-v1.json"
JOB_OUTPUT = ANCHOR_DIR / "infra-retry-job-spec-v1.json"
WORKER = LAB_ROOT / "scripts/f2_static_receiver_ballistic_catch_solver_worker_v1.py"
SOLVER = LAB_ROOT / "vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"
JOB_ID = "f2-static-receiver-ballistic-catch-q05-anchor-infra-retry-v1"


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


def check_first_failure() -> dict[str, Any]:
    first = _json(ORIGINAL_RESULT)
    product = _json(ORIGINAL_PRODUCT_RESULT)
    stdout = ORIGINAL_STDOUT.read_text(encoding="utf-8", errors="replace")
    if first.get("execution_status") != "failed" or first.get("returncode") != 1:
        raise ValueError("original runtime attempt is not a failed infrastructure receipt")
    if product.get("execution_status") != "raw_solver_failed" or product.get("returncode") != 127:
        raise ValueError("original worker result is not the expected loader failure")
    if product.get("frame_inventory", {}).get("frame_count") != 0:
        raise ValueError("original failure unexpectedly produced solver frames")
    if "libdsphchrono.so" not in stdout:
        raise ValueError("original failure is not the missing official-library defect")
    return {"runtime": ref(ORIGINAL_RESULT, "first runtime execution receipt"),
            "worker_result": ref(ORIGINAL_PRODUCT_RESULT, "first worker failure result"),
            "solver_stdout": ref(ORIGINAL_STDOUT, "first loader failure log"),
            "returncode": 127, "frame_count": 0, "defect": "missing_official_shared_library_path"}


def input_refs() -> list[dict[str, Any]]:
    return [
        ref(DEFAULT_DEFINITION, "unchanged fresh literal Definition"),
        ref(DEFAULT_CONTRACT, "unchanged Definition contract"),
        ref(PREFLIGHT_RECEIPT, "unchanged CPU/native preflight receipt"),
        ref(GENERATED_PREFIX.with_suffix(".xml"), "unchanged GenCase generated XML"),
        ref(GENERATED_PREFIX.with_suffix(".bi4"), "unchanged GenCase initial native frame"),
        ref(SOLVER, "pinned DualSPHysics solver"),
        ref(WORKER, "repaired solver worker"),
    ]


def build_job_spec() -> dict[str, Any]:
    verify_cpu_root(ROOT_RECEIPT)
    verify_preflight(PREFLIGHT_RECEIPT)
    failure = check_first_failure()
    if not WORKER.is_file() or not SOLVER.is_file():
        raise FileNotFoundError("repaired worker or solver missing")
    argv = [str(LAB_ROOT / ".venv/bin/python"), str(WORKER),
            "--output", "{attempt_dir}/product",
            "--generated-prefix", str(GENERATED_PREFIX),
            "--time-max", "1.5", "--output-interval", "0.005"]
    spec = {
        "schema": "core.runtime.job_spec.v1",
        "job_id": JOB_ID, "logical_id": JOB_ID,
        "attempt_role": "repaired_infrastructure_retry",
        "category": "solver_f2_static_receiver_anchor_infrastructure_retry",
        "family": "F2", "scope_id": "F2_static_receiver_ballistic_catch_x_v1",
        "revision_id": "F2_static_receiver_ballistic_catch_v1", "case_id": CASE_ID,
        "host": "ada", "cwd": str(LAB_ROOT), "source_lab": str(LAB_ROOT), "argv": argv,
        "input_files": input_refs(),
        "required_outputs": ["product/result.json", "product/solver.stdout.log", "product/worker-status.json"],
        "resources": {"cpu_cores": 4, "ram_mib": 16384, "gpu_peak_mib": 8192, "io_weight": 0.5},
        "timeout_seconds": 7200, "depends_on": [],
        "qualification_claim": "none; one repaired-infrastructure retry only",
        "matrix_credit": 0, "registry_mutation": 0, "ledger_mutation": 1, "queue_mutation": 1,
        "solver_launch": True, "gpu_launch": True,
        "retry_policy": {"retry_kind": "infrastructure_only", "scientific_input_changed": False,
                         "same_input_scientific_retry": False, "max_repaired_infrastructure_retries": 1,
                         "retry_index": 1, "first_failure": failure},
        "worker_contract": "official LD_LIBRARY_PATH repair; one solver invocation with scheduler CUDA UUID",
    }
    return validate_spec(spec)


def write_review() -> dict[str, Any]:
    if REVIEW_OUTPUT.exists() or JOB_OUTPUT.exists():
        raise FileExistsError("infrastructure retry review namespace already exists")
    failure = check_first_failure()
    spec = build_job_spec()
    ANCHOR_DIR.mkdir(parents=True, exist_ok=True)
    JOB_OUTPUT.write_text(json.dumps(spec, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    receipt = {
        "schema": "core.f2.static_receiver_ballistic_catch.solver_infra_retry_root_review.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "authorized_one_repaired_infrastructure_solver_retry_pending_submission",
        "qualification_claim": "none", "matrix_credit": 0,
        "family": "F2", "scope_id": "F2_static_receiver_ballistic_catch_x_v1", "case_id": CASE_ID,
        "original_anchor_review": ref(ANCHOR_DIR / "solver-anchor-root-review-v1.json", "original solver anchor review"),
        "first_failure": failure, "job_spec": ref(JOB_OUTPUT, "infrastructure retry job specification"),
        "input_bindings": spec["input_files"],
        "repair": {"changed_field": "worker official LD_LIBRARY_PATH", "scientific_definition_changed": False,
                   "generated_input_changed": False, "threshold_changed": False,
                   "same_input_scientific_retry": False, "retry_index": 1},
        "authorization": {"solver_invocations": 1, "gpu_launch": True, "queue_submission": True,
                          "ledger_mutation": 1, "registry_mutation": 0, "matrix_submission": 0},
        "denominator": {"parent_scope_rows": 15, "first_attempt_credit": 0, "retry_credit": 0,
                        "same_input_scientific_retry": False},
        "submission": {"submitted": False, "queue_root": str(LAB_ROOT / "campaigns/core-v1/runtime")},
    }
    REVIEW_OUTPUT.write_text(json.dumps(receipt, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return receipt


def verify_review(path: Path = REVIEW_OUTPUT) -> dict[str, Any]:
    value = _json(path)
    if value.get("status") != "authorized_one_repaired_infrastructure_solver_retry_pending_submission":
        raise ValueError("retry review status mismatch")
    if value.get("qualification_claim") != "none" or value.get("matrix_credit") != 0:
        raise ValueError("retry review carries credit")
    if value.get("repair", {}).get("scientific_definition_changed") is not False:
        raise ValueError("retry changed scientific Definition")
    check_first_failure()
    check = ref(Path(value["job_spec"]["path"]), "retry job spec")
    if check["sha256"] != value["job_spec"].get("sha256"):
        raise ValueError("retry job hash changed")
    spec = _json(Path(value["job_spec"]["path"]))
    validate_spec(spec)
    if spec.get("job_id") != JOB_ID or spec.get("retry_policy", {}).get("retry_index") != 1:
        raise ValueError("retry job identity/index mismatch")
    return {"status": "ok", "job_id": JOB_ID, "retry_index": 1,
            "scientific_input_changed": False, "qualification_claim": "none", "matrix_credit": 0,
            "submitted": bool(value.get("submission", {}).get("submitted"))}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("write")
    p = sub.add_parser("verify"); p.add_argument("--receipt", type=Path, default=REVIEW_OUTPUT)
    args = parser.parse_args()
    result = write_review() if args.command == "write" else verify_review(args.receipt)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
