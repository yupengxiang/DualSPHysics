from __future__ import annotations

import ast
from pathlib import Path

import pytest

from scripts import f8_r008_cpu_native_postrun_audit_v1 as audit_module


ROOT = Path(__file__).resolve().parents[1]


def test_r008_postrun_audit_closes_passed_zero_credit_preflight() -> None:
    audit = audit_module.build_audit()
    assert audit["status"] == "cpu_native_preflight_verified_zero_credit_no_solver_authorized"
    assert audit["qualification_credit"] == 0
    assert audit["execution_boundary"]["gencase_invocations_confirmed"] == 1
    assert audit["execution_boundary"]["native_decode_invocations_confirmed"] == 1
    assert audit["execution_boundary"]["solver_invoked"] is False
    assert audit["execution_boundary"]["same_input_retry_forbidden"] is True
    assert audit["verified_result"]["fixed_boundary_particles"] == 4096
    assert audit["verified_result"]["fluid_particles"] == 6656
    assert audit["verified_result"]["total_particles"] == 10752
    assert audit["verified_reference_count"] >= 16


def test_postrun_audit_is_read_only_and_never_loads_heavy_scientific_data() -> None:
    source = (ROOT / "scripts/f8_r008_cpu_native_postrun_audit_v1.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not {"subprocess", "numpy", "h5py"} & imported
    assert audit_module.OUTPUT.exists()
    assert audit_module.verify_audit()["qualification_credit"] == 0


def test_r008_postrun_audit_writer_refuses_overwrite(tmp_path: Path) -> None:
    target = tmp_path / "audit" / "receipt.json"
    audit_module.write_audit(target)
    with pytest.raises(FileExistsError, match="immutable F8 R008 postrun audit"):
        audit_module.write_audit(target)
