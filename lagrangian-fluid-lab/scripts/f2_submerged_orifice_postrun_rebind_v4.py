#!/usr/bin/env python3
"""Rebind F2 v4 evidence after a verifier-only source edit.

The v4 CPU/native preflight is immutable and one-shot.  This utility only
refreshes hash/byte references in its receipt and contract after a source
edit that does not alter the already recorded native audit.  It never calls
GenCase, the native decoder, solver, GPU, queue, ledger, registry, or matrix.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

LAB_ROOT = Path(__file__).resolve().parents[1]
BASE = LAB_ROOT / "campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v4"
RECEIPT = BASE / "root-review-receipt-v4.json"
CONTRACT = BASE / "preflight-contract-v4.json"
PREFLIGHT = BASE / "preflight-v4/preflight.json"
REBIND = BASE / "postrun-verifier-rebind-v1.json"
RUNNER = LAB_ROOT / "scripts/f2_submerged_orifice_preflight_v4.py"
RUNNER_TEST = LAB_ROOT / "tests/test_f2_submerged_orifice_preflight_v4.py"
ROOT_REVIEW = LAB_ROOT / "scripts/f2_submerged_orifice_root_review_v4.py"
ROOT_TEST = LAB_ROOT / "tests/test_f2_submerged_orifice_root_review_v4.py"
STATIC_ADAPTER = LAB_ROOT / "scripts/f2_submerged_orifice_normal_remediation_v4.py"
STATIC_CONTRACT = BASE / "root-review-only-contract-v4.json"
STATIC_TEST = LAB_ROOT / "tests/test_f2_submerged_orifice_normal_remediation_v4.py"


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
    path = Path(path).resolve()
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    partial.replace(path)


def snapshot(paths: list[Path]) -> dict[str, dict[str, Any]]:
    return {str(Path(path).resolve()): ref(path, "post-run rebind snapshot") for path in paths}


def update_ref(item: dict[str, Any], path: Path) -> None:
    role = str(item.get("role", "rebound evidence"))
    item.update(ref(path, role))


def rebind() -> dict[str, Any]:
    required = [RECEIPT, CONTRACT, PREFLIGHT, RUNNER, RUNNER_TEST, ROOT_REVIEW, ROOT_TEST, STATIC_ADAPTER, STATIC_CONTRACT, STATIC_TEST]
    if not all(path.is_file() for path in required):
        raise FileNotFoundError("v4 rebind input is missing")
    before = load(REBIND).get("before") if REBIND.is_file() else snapshot(required)
    receipt = load(RECEIPT)
    # Refresh only test/adapter references.  These are verifier bindings; the
    # root decision, case identity, gates and permissions remain untouched.
    for key, path in (("root_review_adapter", ROOT_REVIEW), ("adapter", STATIC_ADAPTER)):
        item = receipt.get("hash_bindings", {}).get(key)
        if not item or item.get("sha256") != sha256(path) or item.get("bytes") != path.stat().st_size:
            raise ValueError(f"root receipt implementation binding changed: {key}")

    static_contract = load(STATIC_CONTRACT)
    static_contract["hash_bindings"]["v4_contract_test"] = ref(STATIC_TEST, "v4 static contract test")
    dump(STATIC_CONTRACT, static_contract)
    receipt["hash_bindings"]["root_review_test"] = ref(ROOT_TEST, "independent v4 root-review test")
    receipt["hash_bindings"]["contract_test"] = ref(STATIC_TEST, "v4 static contract test")
    receipt["hash_bindings"]["v4_static_contract"] = ref(STATIC_CONTRACT, "v4 runtime-closed static contract")
    dump(RECEIPT, receipt)

    contract = load(CONTRACT)
    bindings = contract["input_bindings"]
    update_ref(bindings["v4_root_review_receipt"], RECEIPT)
    update_ref(bindings["runner"], RUNNER)
    update_ref(bindings["v4_preflight_test"], RUNNER_TEST)
    update_ref(bindings["v4_static_contract"], STATIC_CONTRACT)
    dump(CONTRACT, contract)

    preflight = load(PREFLIGHT)
    if preflight.get("status") != "cpu_native_preflight_failed_hard_audit":
        raise ValueError("v4 preflight is not the recorded hard-gate failure")
    if preflight.get("qualification_claim") != "none" or preflight.get("matrix_credit") != 0:
        raise ValueError("v4 preflight carries credit")
    if preflight.get("native_initial", {}).get("zero_boundnor_count") != 29484:
        raise ValueError("v4 immutable zero-normal observation changed")
    if preflight.get("native_initial", {}).get("zero_normal_size_count") != 29484:
        raise ValueError("v4 immutable NormalSize observation changed")
    for key, path in (("root_review", RECEIPT), ("preflight_contract", CONTRACT), ("runner", RUNNER)):
        update_ref(preflight[key], path)
    preflight["input_hashes"][str(RECEIPT.resolve())] = sha256(RECEIPT)
    preflight["input_hashes"][str(CONTRACT.resolve())] = sha256(CONTRACT)
    preflight["input_hashes"][str(RUNNER.resolve())] = sha256(RUNNER)
    preflight["input_hashes"][str(RUNNER_TEST.resolve())] = sha256(RUNNER_TEST)
    dump(PREFLIGHT, preflight)

    after = snapshot(required)
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
            "zero_boundnor_count": preflight["native_initial"]["zero_boundnor_count"],
            "zero_normal_size_count": preflight["native_initial"]["zero_normal_size_count"],
            "mass_relative_error": preflight["native_initial"]["hard_gates"]["mass"]["relative_error"],
            "qualification_claim": preflight["qualification_claim"],
            "matrix_credit": preflight["matrix_credit"],
            "solver_product_present": preflight["solver_product_present"],
        },
        "before": before,
        "after": after,
        "changed_science_fields": [],
        "notes": [
            "Only verifier hash/byte references were refreshed after the one-shot run.",
            "The native hard-gate observations, artifacts, execution controls, and zero credit were not changed.",
            "The original before hashes remain recorded; same-input execution remains forbidden.",
        ],
    }
    dump(REBIND, result)
    return result


def verify(path: Path = REBIND) -> dict[str, Any]:
    result = load(path)
    if result.get("schema") != "core.f2.submerged_orifice_transfer.postrun_verifier_rebind.v1":
        raise ValueError("v4 postrun rebind schema mismatch")
    if result.get("status") != "rebound_verifier_only_no_science_change" or result.get("changed_science_fields") != []:
        raise ValueError("v4 postrun rebind changed status/science")
    controls = result.get("execution_controls", {})
    for key in ("solver_invoked", "gpu_invoked", "gencase_invoked", "native_decoder_invoked", "job_created", "matrix_submission"):
        if controls.get(key) is not False:
            raise ValueError(f"v4 postrun rebind opened {key}")
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation"):
        if controls.get(key) != 0:
            raise ValueError(f"v4 postrun rebind opened {key}")
    immutable = result["immutable_result"]
    if immutable["preflight_status"] != "cpu_native_preflight_failed_hard_audit":
        raise ValueError("v4 immutable status changed")
    if immutable["zero_boundnor_count"] != 29484 or immutable["zero_normal_size_count"] != 29484:
        raise ValueError("v4 immutable zero-normal result changed")
    if immutable["qualification_claim"] != "none" or immutable["matrix_credit"] != 0:
        raise ValueError("v4 rebind carries credit")
    for path_text, item in result["after"].items():
        path = Path(path_text)
        if not path.is_file() or sha256(path) != item["sha256"] or path.stat().st_size != item["bytes"]:
            raise ValueError(f"current v4 rebind binding is stale: {path}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("rebind", "verify"))
    parser.add_argument("--output", type=Path, default=REBIND)
    args = parser.parse_args()
    value = rebind() if args.command == "rebind" else verify(args.output)
    print(json.dumps(value, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
