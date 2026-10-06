#!/usr/bin/env python3
"""Small source-package-only tests for fresh141.

These tests intentionally inspect only package JSON/Python/text and never open
any path outside the package. Root's registered audit is the only operation
allowed to read or hash the trajectory H5.
"""
from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
PAYLOAD_SUFFIXES = {".h5", ".hdf5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu", ".npy", ".npz"}


def main() -> int:
    binding = json.loads((HERE / "metadata/ay0270-audit-binding.json").read_text())
    request = json.loads((HERE / "requests/ay0270_full836_scientific_artifact_audit.disabled-request.json").read_text())
    manifest = json.loads((HERE / "manifest.json").read_text())
    assert binding["source_only"] is True and binding["execution_allowed"] is False
    assert request["disabled"] is True and request["launch_allowed"] is False
    assert request["source_conversion_lifecycle"]["returncode"] is None
    assert request["opaque_scientific_inputs"]["source_agent_sha256"] is None
    assert request["root_enablement"]["derive_new_request_before_strict_dispatch"] is True
    assert request["root_enablement"]["source_request_is_intentionally_not_strict_dispatchable"] is True
    h5 = Path(request["opaque_scientific_inputs"]["trajectory_h5"])
    assert h5 in {Path(path) for path in request["input_files"]}
    assert str(h5) not in request["input_sha256"]
    assert manifest["runtime"]["serial_cap"] == 1
    worker = HERE / "scripts/ay0270_full836_scientific_audit_worker.py"
    ast.parse(worker.read_text(), filename=str(worker))
    spec = importlib.util.spec_from_file_location("fresh141_worker_contract", worker)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    assert module._counts_match({0: 111708, 3: 67500}, {0: 111708, 1: 0, 2: 0, 3: 67500})
    assert not module._counts_match({0: 111707, 3: 67500}, {0: 111708, 1: 0, 2: 0, 3: 67500})
    package_files = {path.relative_to(HERE).as_posix() for path in HERE.rglob("*") if path.is_file()}
    assert not any(Path(path).suffix.lower() in PAYLOAD_SUFFIXES for path in package_files)
    assert "trajectory.h5" not in {Path(path).name for path in package_files}
    print(json.dumps({"schema": "ds02.fresh141.source-tests.v1", "status": "PASS", "payload_files": 0}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
