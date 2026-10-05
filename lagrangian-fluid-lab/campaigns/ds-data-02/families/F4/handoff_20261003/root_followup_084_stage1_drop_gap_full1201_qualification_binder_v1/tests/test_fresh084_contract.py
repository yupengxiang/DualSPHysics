#!/usr/bin/env python3
"""Static checks for the disabled Root200 qualification bindings."""

from __future__ import annotations

import ast
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
REQUESTS = ROOT / "requests"
BUILDER = ROOT / "workers/build_f4_root200_native_qualification_bindings_v1.py"
INTEGRATION = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/"
    "DualSPHysics/lagrangian-fluid-lab/scripts"
)


def test_requests_remain_disabled_until_root212_passes() -> None:
    index = json.loads((REQUESTS / "index.json").read_text(encoding="utf-8"))
    assert index["case_count"] == 8
    assert index["status"] == "source_only_disabled"
    assert index["native_initial_qa_dependency"]["provider_attempt_id"].endswith("-212")
    paths = [Path(row["path"]) for row in index["requests"]]
    assert len(paths) == 8
    for path in paths:
        request = json.loads(path.read_text(encoding="utf-8"))
        assert request["kind"] == "qualification"
        assert request["status"] == "source_only_disabled"
        assert request["launch"] is False
        assert request["launch_allowed"] is False
        assert request["solver_recipe"]["solver_options"] == ["-tmax:1.2", "-tout:0.001"]
        assert request["gencase_actual_evidence"]["total_particles"] > 0
        assert request["gencase_actual_evidence"]["fluid_particles"] > 0
        assert request["root195_parent_aggregate"]["status"] == "failed"
        assert request["root195_parent_aggregate"]["returncode"] == 0
        assert request["root195_parent_aggregate"]["error"] == "GenCase actual particle count missing"
        assert request["native_initial_qa"]["provider_attempt_id"].endswith("-212")
        assert all(Path(p).suffix.lower() != ".bi4" for p in request["input_files"])
        deferred_bi4 = [p for p in request["deferred_input_files"] if Path(p).suffix.lower() == ".bi4"]
        assert len(deferred_bi4) == 1
        assert all(value is None for p, value in request["deferred_input_sha256"].items() if p.endswith(".bi4"))

    sys.path.insert(0, str(INTEGRATION))
    import ds_data02_strict_dispatch_v1 as strict  # noqa: PLC0415

    for path in paths:
        strict.validate_request(json.loads(path.read_text(encoding="utf-8")))


def test_builder_never_reads_scientific_arrays() -> None:
    source = BUILDER.read_text(encoding="utf-8")
    ast.parse(source, filename=str(BUILDER))
    assert "numpy" not in source
    assert "memmap" not in source
    assert "scan_bi4" not in source
    assert "ROOT212_ATTEMPT" in source


if __name__ == "__main__":
    test_requests_remain_disabled_until_root212_passes()
    test_builder_never_reads_scientific_arrays()
    print("F4 fresh084 source contract: PASS")
