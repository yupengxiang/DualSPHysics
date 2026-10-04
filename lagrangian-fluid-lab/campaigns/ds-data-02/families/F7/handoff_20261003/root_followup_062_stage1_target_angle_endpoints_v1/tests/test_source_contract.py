#!/usr/bin/env python3
"""Source-only checks for the F7 target-angle endpoint handoff."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts"
)
sys.path.insert(0, str(SCRIPTS))
import ds_data02_strict_dispatch_v1 as strict  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_builder():
    path = ROOT / "builders/build_f7_target_angle_sources.py"
    spec = importlib.util.spec_from_file_location("f7_target_angle_builder", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_plan_and_clones() -> None:
    plan = load(ROOT / "endpoint-plan.json")
    assert plan["stage_contract"]["launch_allowed"] is False
    assert [row["amplitude_deg"] for row in plan["endpoints"]] == [30.0, 65.0]
    assert all(row["axis"] == "paddle_amplitude_deg" for row in plan["endpoints"])
    assert all(row["source_definition_clone_sha256"] == plan["mother_binding"]["source_definition_sha256"] for row in plan["endpoints"])
    builder = load_builder()
    for row in plan["endpoints"]:
        source = ROOT / row["source_definition_clone"]
        assert sha256(source) == row["source_definition_clone_sha256"]
        result = builder.validate_source_definition(source, row["source_definition_clone_sha256"], plan)
        assert result["dp_m"] == 0.02
        assert result["time_max_s"] == 12.0
        assert result["time_out_s"] == 0.02


def test_requests_validate_and_are_disabled() -> None:
    for path in sorted((ROOT / "requests").glob("*.json")):
        request = load(path)
        assert request["launch"] is False
        assert request["launch_allowed"] is False
        assert request["cpu_task_kind"] in {"audit", "gencase"}
        actual = strict.validate_request(request)
        assert len(actual) == len(request["input_files"])


def test_no_runtime_outputs() -> None:
    forbidden_suffixes = {".bi4", ".h5", ".csv"}
    assert not any(path.suffix in forbidden_suffixes for path in ROOT.rglob("*"))
    assert not any(path.name == "motion_obstacle_quintic.dat" for path in ROOT.rglob("*"))


if __name__ == "__main__":
    test_plan_and_clones()
    test_requests_validate_and_are_disabled()
    test_no_runtime_outputs()
    print("F7 source contract: PASS")
