#!/usr/bin/env python3
"""Metadata-only contract validator for fresh143."""
from __future__ import annotations
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASE = "F3_STAGE1_DP006_P1000_AY0270"
RAW_SUFFIXES = {".h5", ".hdf5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu", ".pvtu", ".pvd"}
ADAPTER = ROOT / "scripts/ay0270_artifact_audit_xmf_adapter.py"
BINDING = ROOT / "metadata/ay0270-artifact-audit-xmf-binding.json"
REQUEST = ROOT / "requests/ay0270_artifact_audit_full836_xmf.disabled-request.json"

def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def j(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))

def main() -> None:
    binding = j(BINDING)
    request = j(REQUEST)
    roles = j(ROOT / "metadata/receipt-role-closure.json")
    comparison = j(ROOT / "metadata/xmf-adapter-comparison.json")
    assert binding["schema"] == "ds02.f3.artifact-audit-aware-xmf-request.v1"
    assert binding["case_id"] == CASE
    assert binding["disabled"] and binding["source_only"]
    assert not binding["launch_allowed"] and not binding["execution_allowed"]
    assert binding["cpu_threads"] == 2 and binding["serial_cap"] == 1
    assert binding["case_credit"] == 0
    assert all(value is None for value in binding["future_outputs"].values())
    assert "typed_receipt" not in binding
    assert binding["physical_condition_sha256"] == binding["canonical_source_physical_condition_sha256"]
    assert binding["actual_converter_scope_sha256"] == binding["converter_physical_condition_sha256"]
    assert binding["source_plan_scope_sha256"] is None
    assert binding["source_agent_read_scientific_payloads"] is False
    assert binding["source_agent_hashed_scientific_payloads"] is False
    assert binding["metadata_input_sha256"][str(ADAPTER)] == sha(ADAPTER)
    assert binding["upstream_export_xmf"]["sha256"] == comparison["upstream_worker"]["sha256"]
    assert binding["adapter_source"]["sha256"] == sha(ADAPTER)
    assert comparison["adapter_worker"]["sha256"] == sha(ADAPTER)
    assert comparison["comparison_basis"]["scientific_logic_changed"] is False
    assert comparison["comparison_basis"]["receipt_semantics_changed"] is True
    assert request["binding_sha256"] == sha(BINDING)
    assert request["disabled"] and request["future_input_hashes_null"]
    assert request["case_credit"] == 0
    assert request["expected_h5_sha256_from_audit_attestation"] == binding["expected_h5_sha256"]

    for role_name, role in roles["roles"].items():
        path = Path(role["path"])
        assert path.is_file(), (role_name, path)
        assert path.suffix.lower() not in RAW_SUFFIXES
        assert sha(path) == role["sha256"], (role_name, path)
    old = j(Path(roles["roles"]["original_conversion_receipt"]["path"]))
    audit = j(Path(roles["roles"]["artifact_audit_receipt"]["path"]))
    native = j(Path(roles["roles"]["native_receipt"]["path"]))
    assert old["status"] == "running" and "returncode" not in old
    assert audit["status"] == "completed" and audit["returncode"] == 0
    assert native["status"] == "completed" and native["returncode"] == 0
    assert roles["future_outputs"]["xmf_receipt_sha256"] is None
    assert roles["audit_facts"]["case_credit"] == 0

    # The actual adapter preflight reads only the JSON/code closure above.
    result = subprocess.run(
        [sys.executable, str(ADAPTER), "--binding", str(BINDING), "--metadata-preflight"],
        check=False, text=True, capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["status"] == "metadata_preflight_pass"
    assert output["scientific_payload_opened"] is False

    integrity = j(ROOT / "metadata/package-integrity.json")
    listed = {entry["path"]: entry for entry in integrity["files"]}
    actual = {
        str(path.relative_to(ROOT)): path
        for path in ROOT.rglob("*")
        if path.is_file() and path.name != "package-integrity.json"
    }
    assert set(listed) == set(actual)
    for rel, entry in listed.items():
        assert entry["bytes"] == actual[rel].stat().st_size
        assert entry["sha256"] == sha(actual[rel]), rel
    for path in ROOT.rglob("*"):
        if path.is_file():
            assert path.suffix.lower() not in RAW_SUFFIXES, path
    print("fresh143 validation PASS: receipt roles separated; metadata preflight PASS; no payload files")

if __name__ == "__main__":
    main()
