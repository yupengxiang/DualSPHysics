"""Source-closure tests for the ROOT249 PartVTKOut forward worker.

These tests exercise only bounded metadata and the manufactured parser path.
They do not open a production OBI4/BI4/H5 source or submit a request.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import argparse
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts/ds_data02_stage2_f4_unlocated_native_evidence_v4.py"
SPEC = importlib.util.spec_from_file_location("f4_unlocated_native_evidence_v4", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
WORKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WORKER)


def test_original_partvtkout_is_the_declared_vendor_binary() -> None:
    ref = WORKER._validate_official_partvtkout()
    assert ref["path"] == str(Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTKOut_linux64"))
    assert ref["sha256"] == "62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00"
    assert ref["source_namespace"] == "ORIGINAL_LAB_VENDOR"
    assert ref["native_payload_opened_by_preparer"] is False


def test_prepare_binds_original_tool_and_v4_command(tmp_path: Path) -> None:
    output_root = tmp_path / "root249-v4"
    request_path = tmp_path / "root249-v4-request.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "prepare",
            "--output-root",
            str(output_root),
            "--request-output",
            str(request_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    assert result["launch_allowed"] is True
    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    tool = manifest["source_closure"]["official_partvtkout"]
    assert tool["source_namespace"] == "ORIGINAL_LAB_VENDOR"
    assert tool["sha256"] == WORKER.PARTVTKOUT_SHA256
    assert tool["path"] == str(WORKER.PARTVTKOUT)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    assert request["command"][1] == str(SCRIPT)
    assert request["command"][-1] == "{attempt_root}/f4-unlocated-native-evidence-v4.json"
    tool_path = str(WORKER.PARTVTKOUT)
    assert tool_path in request["input_sha256"]
    assert request["input_sha256"][tool_path] == WORKER.PARTVTKOUT_SHA256
    assert request["source_read_cost"]["h5_content_read"] is False


def test_v4_rejects_a_different_partvtkout_even_when_it_exists(tmp_path: Path) -> None:
    replacement = tmp_path / "PartVTKOut_linux64"
    replacement.write_bytes(Path(WORKER.PARTVTKOUT).read_bytes())
    with pytest.raises(WORKER.EvidenceError, match="unbound PartVTKOut replacement"):
        # This enters the production audit gate before it reads a manifest or
        # native payload, so the rejection is source-binding only.
        WORKER.audit(argparse.Namespace(partvtkout=replacement, manifest=tmp_path / "missing.json", root232_proof=tmp_path / "missing-proof.json", output=tmp_path / "out.json", allow_pending_proof=False))


def test_v4_script_and_vendor_digest_are_reproducible() -> None:
    digest = hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
    assert len(digest) == 64
    assert WORKER._validate_official_partvtkout()["sha256"] == WORKER.PARTVTKOUT_SHA256
