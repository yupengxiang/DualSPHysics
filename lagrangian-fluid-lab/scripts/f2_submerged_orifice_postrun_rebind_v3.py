#!/usr/bin/env python3
"""Rebind immutable v3 evidence after a verifier-only source repair.

The v3 CPU/native run is a one-shot artifact.  This utility never invokes a
solver, GenCase, decoder, queue, ledger, registry, or matrix operation.  It
updates only provenance references in the authorization/contract/result JSON
files after a non-scientific verifier change and records the before/after
hashes in a separate append-only sidecar.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


LAB_ROOT = Path(__file__).resolve().parents[1]
BASE = LAB_ROOT / "campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v3"
RECEIPT = BASE / "root-review-receipt-v3.json"
CONTRACT = BASE / "preflight-contract-v3.json"
PREFLIGHT = BASE / "preflight-v3/preflight.json"
REBINDS = BASE / "postrun-verifier-rebind-v1.json"
RUNNER = LAB_ROOT / "scripts/f2_submerged_orifice_preflight_v3.py"
RUNNER_TEST = LAB_ROOT / "tests/test_f2_submerged_orifice_preflight_v3.py"
ROOT_REVIEW = LAB_ROOT / "scripts/f2_submerged_orifice_normal_remediation_root_review_v3.py"
ROOT_TEST = LAB_ROOT / "tests/test_f2_submerged_orifice_normal_remediation_root_review_v3.py"
V3_STATIC_TEST = LAB_ROOT / "tests/test_f2_submerged_orifice_normal_remediation_v3.py"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def dump(path: Path, value: dict[str, Any]) -> None:
    path = Path(path)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    partial.replace(path)


def snapshot(paths: list[Path]) -> dict[str, dict[str, Any]]:
    return {str(Path(path).resolve()): ref(Path(path), "post-run rebind snapshot") for path in paths}


def update_ref(item: dict[str, Any], path: Path) -> None:
    old_role = str(item.get("role", "rebound evidence"))
    item.update(ref(path, old_role))


def rebind() -> dict[str, Any]:
    paths = [RECEIPT, CONTRACT, PREFLIGHT, RUNNER, RUNNER_TEST, ROOT_REVIEW, ROOT_TEST]
    # Preserve the first pre-rebind snapshot across idempotent repairs.
    before = load(REBINDS).get("before") if REBINDS.is_file() else snapshot(paths)

    receipt = load(RECEIPT)
    bindings = receipt["hash_bindings"]
    update_ref(bindings["v3_root_review_adapter"], ROOT_REVIEW)
    update_ref(bindings["v3_root_review_test"], ROOT_TEST)
    update_ref(bindings["v3_contract_test"], V3_STATIC_TEST)
    dump(RECEIPT, receipt)

    contract = load(CONTRACT)
    bindings = contract["input_bindings"]
    update_ref(bindings["v3_root_review_receipt"], RECEIPT)
    update_ref(bindings["runner"], RUNNER)
    update_ref(bindings["v3_preflight_test"], RUNNER_TEST)
    dump(CONTRACT, contract)

    preflight = load(PREFLIGHT)
    for key, path in {
        "root_review": RECEIPT,
        "preflight_contract": CONTRACT,
        "runner": RUNNER,
    }.items():
        if key in preflight:
            update_ref(preflight[key], path)
    preflight["input_hashes"][str(RECEIPT.resolve())] = sha256(RECEIPT)
    preflight["input_hashes"][str(CONTRACT.resolve())] = sha256(CONTRACT)
    preflight["input_hashes"][str(RUNNER.resolve())] = sha256(RUNNER)
    preflight["input_hashes"][str(RUNNER_TEST.resolve())] = sha256(RUNNER_TEST)
    dump(PREFLIGHT, preflight)

    after = snapshot(paths)
    result = {
        "schema": "core.f2.submerged_orifice_transfer.postrun_verifier_rebind.v1",
        "status": "rebound_verifier_only_no_science_change",
        "execution_controls": {
            "solver_invoked": False,
            "gpu_invoked": False,
            "gencase_invoked": False,
            "native_decoder_invoked": False,
            "job_created": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "matrix_submission": False,
        },
        "immutable_result": {
            "preflight_path": str(PREFLIGHT.resolve()),
            "preflight_status": preflight["status"],
            "qualification_claim": preflight["qualification_claim"],
            "matrix_credit": preflight["matrix_credit"],
            "solver_product_present": preflight["solver_product_present"],
        },
        "before": before,
        "after": after,
        "changed_science_fields": [],
        "notes": [
            "Only hash/byte references and verifier test bindings were refreshed.",
            "The preflight hard-gate observations and execution controls were not changed.",
            "The original before hashes remain recorded here; same-input execution remains forbidden.",
        ],
    }
    dump(REBINDS, result)
    return result


def verify(path: Path = REBINDS) -> dict[str, Any]:
    result = load(path)
    if result.get("schema") != "core.f2.submerged_orifice_transfer.postrun_verifier_rebind.v1":
        raise ValueError("postrun rebind schema mismatch")
    if result.get("status") != "rebound_verifier_only_no_science_change":
        raise ValueError("postrun rebind status changed")
    if result.get("changed_science_fields") != []:
        raise ValueError("postrun rebind changed scientific fields")
    controls = result.get("execution_controls", {})
    for key in ("solver_invoked", "gpu_invoked", "gencase_invoked", "native_decoder_invoked", "job_created", "matrix_submission"):
        if controls.get(key) is not False:
            raise ValueError(f"postrun rebind opened {key}")
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation"):
        if controls.get(key) != 0:
            raise ValueError(f"postrun rebind opened {key}")
    immutable = result["immutable_result"]
    if immutable["preflight_status"] != "cpu_native_preflight_failed_hard_audit":
        raise ValueError("immutable preflight status changed")
    if immutable["qualification_claim"] != "none" or immutable["matrix_credit"] != 0:
        raise ValueError("postrun rebind carries credit")
    for section in ("before", "after"):
        for path_text, item in result[section].items():
            if len(item["sha256"]) != 64 or item["bytes"] <= 0:
                raise ValueError(f"invalid {section} snapshot")
            if section == "after":
                path = Path(path_text)
                if not path.is_file() or sha256(path) != item["sha256"] or path.stat().st_size != item["bytes"]:
                    raise ValueError(f"current postrun binding is stale: {path}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("rebind", "verify"))
    parser.add_argument("--output", type=Path, default=REBINDS)
    args = parser.parse_args()
    value = rebind() if args.command == "rebind" else verify(args.output)
    print(json.dumps(value, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
