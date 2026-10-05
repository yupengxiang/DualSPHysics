#!/usr/bin/env python3
"""Static contract checks for the fresh090 F4 post-native handoff.

The preflight reads JSON and hashes declared source inputs only.  It refuses
scientific-array input paths and never opens a BI4/H5/VTK/CSV artifact.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


PACKAGE = Path(__file__).resolve().parents[1]
F4_ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / "AGENTS.md").is_file())
S089 = F4_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F4/handoff_20261003/root_followup_089_stage1_f4_root237_qa_full1201_bind_v1"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
SCIENTIFIC_SUFFIXES = {".bi4", ".h5", ".hdf5", ".vtk", ".csv"}


def sha(path: Path) -> str:
    if path.suffix.lower() in SCIENTIFIC_SUFFIXES:
        raise AssertionError(f"preflight attempted to hash scientific artifact: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text())


def check() -> dict[str, Any]:
    source_binding = load(PACKAGE / "source-binding.json")
    assert source_binding["family_id"] == "F4"
    assert source_binding["native_case_count"] == 6
    assert source_binding["independent_case_count_increment"] == 0
    assert source_binding["arrays_read_by_source"] is False
    assert source_binding["jobs_started_by_source"] is False
    request_paths = sorted((PACKAGE / "requests").glob("*.request.json"))
    assert len(request_paths) == 18
    request_rows = []
    for request_path in request_paths:
        request = load(request_path)
        assert request["schema"] == "ds02.runner-request.v2"
        assert request["family_id"] == "F4"
        assert request["kind"] == "cpu"
        assert request["launch"] is False and request["launch_allowed"] is False
        assert request["launch_owner"] == "root"
        assert request["source_only"] is True
        assert request["status"] == "source_only_disabled"
        assert request["independent_case_count_increment"] == 0
        assert request["worktree_root"] == str(F4_ROOT)
        assert request["cpu_task_kind"] in {"conversion", "audit"}
        assert request["input_files"]
        assert request["scope_id"] == "root_followup_090_stage1_f4_root242_typed_xmf_render_bind_v1"
        for input_name in request["input_files"]:
            path = Path(input_name)
            assert path.is_file(), f"missing input: {path}"
            assert path.suffix.lower() not in SCIENTIFIC_SUFFIXES, f"scientific source input: {path}"
            assert request["input_sha256"][input_name] == sha(path), f"hash mismatch: {path}"
        for deferred_name, declared in request.get("deferred_input_sha256", {}).items():
            if Path(deferred_name).suffix.lower() in SCIENTIFIC_SUFFIXES:
                assert declared is None, f"future scientific digest must remain null: {deferred_name}"
        command = request["command"]
        if request["cpu_task_kind"] == "audit":
            assert "--diagnostic-frames" not in command, "Root023 full renderer cannot be reduced to a diagnostic frame"
            assert "--force-offscreen-rendering" in command
            assert str(PACKAGE / "render" / "n3-vector-spec.json") in request["input_files"]
        if request["cpu_task_kind"] == "conversion":
            assert request["storage_contract"]["concurrency_cap"] == 2 if "storage_contract" in request else True
        output_values = request["expected_outputs"]
        assert output_values.get("all_sha256") is None
        assert request["arrays_read_by_source"] is False
        assert request["jobs_started_by_source"] is False
        request_rows.append({"case_id": request["case_id"], "task": request["cpu_task_kind"], "attempt_id": request["attempt_id"]})

    evidence = load(PACKAGE / "evidence/root242-native-receipts.json")
    assert len(evidence["cases"]) == 6
    for row in evidence["cases"]:
        native = row["native_receipt"]
        receipt_path = Path(native["path"])
        assert receipt_path.is_file()
        assert sha(receipt_path) == native["sha256"]
        receipt = load(receipt_path)
        assert receipt["status"] == "completed" and receipt["returncode"] == 0
        assert native["request_sha256"] == receipt["request_sha256"]
        actual_request = receipt["request"]
        assert actual_request["attempt_id"] == native["attempt_id"]
        assert actual_request["command"][-2:] == ["-tmax:1.2", "-tout:0.001"]
        assert actual_request["solver_recipe"]["native_frame_count"] == 1201
        assert actual_request["solver_recipe"]["dp_m"] == 0.01
        assert actual_request["solver_recipe"]["time_max_s"] == 1.2
        assert actual_request["solver_recipe"]["time_out_s"] == 0.001

    for binding_path in sorted((PACKAGE / "bindings").glob("*.json")):
        binding = load(binding_path)
        assert binding["arrays_read_by_source"] is False
        assert binding["root242_native"]["status"] == "completed"
        assert binding["root242_native"]["returncode"] == 0
        assert binding["root242_native"]["sha256"]
        if "actual_typed_counts" in binding:
            assert binding["actual_typed_counts"] is None

    camera = load(PACKAGE / "render/camera-spec.json")
    assert len(camera["cases"]) == 6
    contacts = load(PACKAGE / "render/contact-page-keys.json")
    assert contacts["frames"] == 1201 and contacts["page_count"] == 51
    assert contacts["all_frames_required"] is True
    vector = load(PACKAGE / "render/n3-vector-spec.json")
    assert vector["semantic_type"] == "N3"
    assert vector["components"] == ["vx", "vy", "vz"]

    return {"request_count": len(request_paths), "native_case_count": len(evidence["cases"]), "arrays_read_by_source": False, "jobs_started_by_source": False}


if __name__ == "__main__":
    print(json.dumps(check(), indent=2, sort_keys=True))
