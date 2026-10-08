from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts/ds_data02_stage2_product_access_provenance_v1.py"
SPEC = importlib.util.spec_from_file_location("stage2_product_access_provenance_v1", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_requirement_parser_keeps_exact_pin_and_skips_index_url(tmp_path: Path) -> None:
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("--index-url https://example.invalid\n# comment\nnumpy==2.2.6\ntorch==2.11.0+cu128\n", encoding="utf-8")
    assert MODULE._parse_requirements(requirements) == [
        {"name": "numpy", "operator": "==", "version": "2.2.6"},
        {"name": "torch", "operator": "==", "version": "2.11.0+cu128"},
    ]


def test_scientific_payload_is_rejected(tmp_path: Path) -> None:
    payload = tmp_path / "trajectory.h5"
    payload.write_bytes(b"fixture")
    with pytest.raises(MODULE.ProvenanceError, match="forbidden scientific payload"):
        MODULE._path(payload, "payload")


def test_environment_contract_records_invocation_and_resolved_paths() -> None:
    executable = Path(__import__("sys").executable)
    requirements = [Path(__file__).parents[1] / "requirements.txt", Path(__file__).parents[1] / "requirements-ml.txt"]
    environment, metadata_files = MODULE._environment(requirements, executable)
    assert environment["interpreter"]["invocation_path"] == str(executable)
    assert environment["interpreter"]["resolved_path"]
    versions = {item["name"]: item["actual_version"] for item in environment["packages"]}
    assert versions["numpy"] == "2.2.6"
    assert versions["h5py"] == "3.16.0"
    assert len(metadata_files) == 10
