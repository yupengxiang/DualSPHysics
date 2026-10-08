from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_v6_materialization_copies_two_files_to_one_fresh_parent_and_rejects_escape(tmp_path: Path):
    runner = _load("external_solver_v6_materialization", ROOT / "scripts/ds_data02_stage2_external_solver_v6.py")
    source_a = tmp_path / "a.xml"
    source_b = tmp_path / "b.bi4"
    source_a.write_text("xml")
    source_b.write_bytes(b"bi4")
    output = tmp_path / "attempt"
    output.mkdir()
    request = {
        "solver_input_materialization": {
            "files": [
                {"role": "xml", "source": str(source_a), "target": "case.xml", "sha256": runner.sha256_file(source_a)},
                {"role": "bi4", "source": str(source_b), "target": "case.bi4", "sha256": runner.sha256_file(source_b)},
            ]
        }
    }
    evidence = runner._materialize_solver_inputs(request, output)
    assert len(evidence["files"]) == 2
    assert (output / "solver_input" / "case.xml").read_text() == "xml"
    assert (output / "solver_input" / "case.bi4").read_bytes() == b"bi4"
    bad = tmp_path / "bad"
    bad.mkdir()
    bad_request = {"solver_input_materialization": {"files": [
        {"role": "bad", "source": str(source_a), "target": "../escape", "sha256": runner.sha256_file(source_a)}
    ]}}
    with pytest.raises(runner.ExternalSolverV4Error, match="escapes"):
        runner._materialize_solver_inputs(bad_request, bad)


def test_v6_charge_preserves_one_gpu_cutoff_value(tmp_path: Path):
    runner = _load("external_solver_v6_charge", ROOT / "scripts/ds_data02_stage2_external_solver_v6.py")
    ledger = {
        "charges": [], "reservations": [{"id": "F7/a/001", "gpu_seconds": 10.0,
                                           "cpu_core_seconds": 10.0, "new_storage_bytes": 0}],
        "attempts": [{"id": "F7/a/001", "kind": "qualification"}],
    }

    class Runtime:
        class Lock:
            def __enter__(self):
                return ledger
            def __exit__(self, *args):
                return False

        @staticmethod
        def ledger_locked(_root):
            return Runtime.Lock()

    cutoff = 12.345678
    result = runner._charge(Runtime(), tmp_path, "F7/a/001", {"external_filesystem": "/var/tmp"},
                             external_bytes=4, home_bytes=2, cpu_seconds=1.25,
                             gpu_seconds=cutoff, status="FAILED_EXTERNAL_SOLVER")
    assert result["charge"]["gpu_seconds"] == cutoff
    assert ledger["charges"][0]["gpu_seconds"] == cutoff
    assert ledger["charges"][0]["cpu_core_seconds"] == 1.25
