#!/usr/bin/env python3
"""Small source-only contract checks for the 062 request successor."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_SCRIPTS = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts"
)
sys.path.insert(0, str(INTEGRATION_SCRIPTS))
import ds_data02_strict_dispatch_v1 as strict  # noqa: E402


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(name: str) -> dict:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def test_requests_validate() -> None:
    gencase = load("requests/f4_drop_gap_gencase_preflight_request.json")
    qa = load("requests/f4_drop_gap_initial_native_qa_request.json")
    assert gencase["cpu_task_kind"] == "gencase"
    assert qa["cpu_task_kind"] == "audit"
    assert gencase["launch"] is False and gencase["launch_allowed"] is False
    assert qa["launch"] is False and qa["launch_allowed"] is False
    assert len(strict.validate_request(gencase)) == len(gencase["input_files"])
    assert len(strict.validate_request(qa)) == len(qa["input_files"])


def test_metadata_matches_definitions() -> None:
    for metadata in sorted((ROOT / "metadata").glob("*.metadata.json")):
        value = json.loads(metadata.read_text(encoding="utf-8"))
        definition = metadata.with_name(f"{value['case_id']}_Def.xml")
        assert definition.is_file()
        assert value["definition_sha256"] == digest(definition)
        assert value["expected_counts_by_source"] == {"drop": 5824, "pool": 53248}
        assert value["source_regions"]["drop"]["low_m"][2] in (0.38, 0.46)


def test_workers_compile() -> None:
    for path in sorted((ROOT / "workers").glob("*.py")):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)


if __name__ == "__main__":
    test_requests_validate()
    test_metadata_matches_definitions()
    test_workers_compile()
    print("request contract: PASS")
