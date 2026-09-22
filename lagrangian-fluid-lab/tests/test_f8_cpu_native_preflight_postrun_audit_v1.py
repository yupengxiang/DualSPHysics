from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from scripts import f8_cpu_native_preflight_postrun_audit_v1 as audit


ROOT = Path(__file__).resolve().parents[1]


def test_postrun_audit_is_read_only_and_retains_the_f8_hard_failure() -> None:
    source = (ROOT / "scripts/f8_cpu_native_preflight_postrun_audit_v1.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {alias.name for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in node.names}
    assert "subprocess" not in imported
    assert "numpy" not in imported
    value = audit.verify_audit()
    assert value["status"] == "retained_hard_failure_no_retry_zero_credit"
    assert value["qualification_claim"] == "none"
    assert value["qualification_credit"] == 0
    closure = value["failure_closure"]
    assert closure["gencase_invocations_confirmed"] == 1
    assert closure["native_decode_invocations_confirmed"] == 1
    assert closure["same_input_retry_forbidden"] is True
    assert all(closure[key] == 0 for key in ("queue_mutation", "registry_mutation", "ledger_mutation", "denominator_mutation", "qualification_credit"))


def test_postrun_audit_hash_binds_all_required_failure_evidence() -> None:
    value = audit.verify_audit()
    evidence = value["evidence"]
    names = {entry["path"].rsplit("/", 1)[-1] for entry in evidence}
    assert {"receipt.json", "one-shot-lock.json", "gencase.stdout.log", "native-decode.stdout.log", "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R001.xml", "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R001.bi4", "native-initial.xml"} <= names
    arrays = value["decoded_array_manifest_recursive"]
    assert {entry["path"].rsplit("/", 1)[-1] for entry in arrays} == {"Idp.bin", "Posd.bin", "Rhop.bin", "Vel.bin"}
    facts = value["retained_failure_facts"]
    assert facts["fixed_boundary_particle_count"] == 0
    assert facts["generated_fixed_group_count"] == 0
    assert facts["decoded_boundary_normal_file"] == "absent: BoundNor.bin"
    assert facts["control_csv_copy_warning"].startswith("WARNING: File 'acceleration/")


def test_postrun_audit_refuses_overwrite() -> None:
    with pytest.raises(FileExistsError, match="immutable F8 postrun audit"):
        audit.write_audit()


def test_stored_audit_is_json_object_without_runtime_side_effects() -> None:
    value = json.loads(audit.OUTPUT.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    assert value["audit_mode"] == "strictly_read_only_against_cpu_native_preflight_v1"
