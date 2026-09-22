#!/usr/bin/env python3
"""Close F8's one-shot CPU/native preflight failure as read-only evidence.

This verifier never launches a program and never alters the preflight
namespace, Definition, or control table.  Its sole optional write is a new,
immutable audit receipt in a separate versioned directory.  The receipt binds
the retained runtime record and every required native artifact by SHA-256.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


LAB = Path(__file__).resolve().parents[1]
CASE = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001")
PREFLIGHT = CASE / "cpu-native-preflight-v1"
OUTPUT = LAB / CASE / "cpu-native-preflight-postrun-audit-v1/receipt.json"
SCHEMA = "core.cfd.f8.cpu_native_preflight_postrun_audit.v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _relative(path: Path) -> str:
    return str(path.resolve().relative_to(LAB))


def binding(path: Path, role: str) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"required retained F8 evidence is missing: {path}")
    return {"path": _relative(path), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def native_array_manifest() -> list[dict[str, Any]]:
    """Return the complete recursive leaf-file manifest for decoded arrays."""
    array_root = LAB / PREFLIGHT / "native-initial"
    files = sorted(path for path in array_root.rglob("*") if path.is_file())
    _require(files, "decoded native-array tree is empty")
    return [binding(path, "decoded native array") for path in files]


def _find(manifest: list[dict[str, Any]], suffix: str) -> dict[str, Any]:
    matches = [item for item in manifest if item["path"].endswith(suffix)]
    _require(len(matches) == 1, f"expected exactly one retained artifact ending with {suffix}")
    return matches[0]


def _verify_manifest_item(item: dict[str, Any]) -> None:
    path = LAB / str(item["path"])
    _require(path.is_file(), f"bound evidence disappeared: {path}")
    _require(path.stat().st_size == item["bytes"], f"bound evidence size changed: {path}")
    _require(sha256(path) == item["sha256"], f"bound evidence hash changed: {path}")


def build_audit() -> dict[str, Any]:
    """Read and cross-check failure evidence; this function performs no writes."""
    preflight = LAB / PREFLIGHT
    receipt_path = preflight / "receipt.json"
    lock_path = preflight / "one-shot-lock.json"
    gencase_log = preflight / "gencase.stdout.log"
    decode_log = preflight / "native-decode.stdout.log"
    generated_xml = preflight / "generated/F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R001.xml"
    generated_bi4 = preflight / "generated/F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R001.bi4"
    decoded_xml = preflight / "native-initial.xml"

    receipt = load_json(receipt_path)
    lock = load_json(lock_path)
    _require(receipt.get("schema") == "core.cfd.f8.cpu_native_preflight.v1", "preflight receipt schema changed")
    _require(receipt.get("status") == "cpu_native_preflight_failed_hard_audit", "preflight is not the retained hard failure")
    _require(receipt.get("pass") is False, "failed preflight cannot report pass")
    _require(receipt.get("qualification_claim") == "none" and receipt.get("qualification_credit") == 0, "preflight receipt carries qualification credit")
    _require(receipt.get("failure_policy") == "Failure is retained in this namespace and same-input retry is forbidden.", "preflight retry prohibition changed")
    _require(lock.get("schema") == "core.cfd.f8.cpu_native_preflight_lock.v1", "one-shot lock schema changed")
    _require(lock.get("gencase_invocation_budget") == 1 and lock.get("native_decode_invocation_budget") == 1, "one-shot binary budgets changed")
    _require(lock.get("same_input_retry") is False, "same-input retry became allowed")

    controls = receipt.get("execution_controls", {})
    _require(controls.get("cpu_gencase_invoked") is True and controls.get("native_decode_invoked") is True, "both authorized native steps were not consumed")
    _require(controls.get("solver_invoked") is False and controls.get("gpu_invoked") is False and controls.get("training_started") is False, "preflight opened solver, GPU, or training")
    _require(all(controls.get(key) == 0 for key in ("queue_mutation", "registry_mutation", "ledger_mutation", "denominator_mutation", "qualification_credit")), "preflight mutated a forbidden accounting surface")

    gencase_text = gencase_log.read_text(encoding="utf-8")
    decode_text = decode_log.read_text(encoding="utf-8")
    _require(gencase_text.count("GenCase v5.4.354.01 (07-04-2025)") == 1, "GenCase log does not prove exactly one invocation")
    _require(gencase_text.count("Finished execution (code=0).") == 1, "GenCase completion count is not exactly one")
    _require(decode_text.count("PART_0000 Idp ") == 1 and decode_text.count("PART_0000 Rhop ") == 1, "decoder log does not prove one decoded particle block")
    _require("No boundary particles were created in the defined domain." in gencase_text, "missing no-boundary GenCase warning")
    warning = "WARNING: File 'acceleration/F8_OPC_q0p500_acceleration.csv' could not be copied."
    _require(gencase_text.count(warning) == 1 and gencase_text.count("3. File 'acceleration/F8_OPC_q0p500_acceleration.csv' could not be copied.") == 1, "control CSV copy warning is missing or duplicated unexpectedly")

    generated_root = ElementTree.parse(generated_xml).getroot()
    particles = generated_root.find(".//particles")
    _require(particles is not None, "generated XML has no particle summary")
    fixed_nodes = particles.findall("./fixed")
    _require(len(fixed_nodes) == 0 and particles.get("nb") == "0", "generated XML does not retain zero fixed/boundary particles")
    native_root = ElementTree.parse(decoded_xml).getroot()
    item = native_root.find("item")
    native_metadata = {node.get("name"): node.get("v") for node in item if node.tag != "item"} if item is not None else {}
    _require(native_metadata.get("CaseNfixed") == "0", "decoded XML does not retain zero fixed/boundary particles")
    arrays = native_array_manifest()
    _require(not any(entry["path"].endswith("/BoundNor.bin") for entry in arrays), "BoundNor must remain absent for this hard failure")
    _require({entry["path"].rsplit("/", 1)[-1] for entry in arrays} == {"Idp.bin", "Posd.bin", "Rhop.bin", "Vel.bin"}, "decoded array manifest changed")

    evidence = [
        binding(receipt_path, "retained one-shot preflight receipt"),
        binding(lock_path, "pre-execution one-shot lock"),
        binding(gencase_log, "single GenCase stdout log"),
        binding(decode_log, "single native decode stdout log"),
        binding(generated_xml, "GenCase-generated XML"),
        binding(generated_bi4, "GenCase-generated BI4"),
        binding(decoded_xml, "native decoder XML"),
    ]
    for entry in evidence + arrays:
        _verify_manifest_item(entry)
    return {
        "schema": SCHEMA,
        "scope_id": "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R001",
        "status": "retained_hard_failure_no_retry_zero_credit",
        "qualification_claim": "none",
        "qualification_credit": 0,
        "audit_mode": "strictly_read_only_against_cpu_native_preflight_v1",
        "failure_closure": {
            "preflight_status": receipt["status"],
            "same_input_retry_forbidden": True,
            "gencase_invocations_confirmed": 1,
            "native_decode_invocations_confirmed": 1,
            "solver_invoked": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "qualification_credit": 0,
        },
        "retained_failure_facts": {
            "fixed_boundary_particle_count": 0,
            "generated_fixed_group_count": 0,
            "decoded_boundary_normal_file": "absent: BoundNor.bin",
            "control_csv_copy_warning": warning,
            "hard_gate_failures": ["generated_one_boundary_marker", "native_boundary_count_positive", "boundary_normal_count", "boundary_normals_finite", "boundary_normals_nonzero"],
        },
        "evidence": evidence,
        "decoded_array_manifest_recursive": arrays,
    }


def verify_audit(path: Path = OUTPUT) -> dict[str, Any]:
    """Read-only verification of the stored versioned audit receipt."""
    audit = load_json(path)
    _require(audit.get("schema") == SCHEMA, "postrun audit schema changed")
    _require(audit.get("status") == "retained_hard_failure_no_retry_zero_credit", "postrun audit no longer retains failure")
    _require(audit.get("qualification_claim") == "none" and audit.get("qualification_credit") == 0, "postrun audit carries credit")
    expected = build_audit()
    _require(audit == expected, "postrun audit no longer matches read-only evidence")
    return audit


def write_audit(path: Path = OUTPUT) -> dict[str, Any]:
    """Create the one immutable audit receipt without touching retained evidence."""
    target = Path(path).resolve()
    if target.exists():
        raise FileExistsError(f"refusing to overwrite immutable F8 postrun audit: {target}")
    audit = build_audit()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return audit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="read and verify the already-written immutable audit")
    args = parser.parse_args(argv)
    audit = verify_audit() if args.verify else write_audit()
    print(json.dumps({key: audit[key] for key in ("schema", "status", "qualification_credit")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
