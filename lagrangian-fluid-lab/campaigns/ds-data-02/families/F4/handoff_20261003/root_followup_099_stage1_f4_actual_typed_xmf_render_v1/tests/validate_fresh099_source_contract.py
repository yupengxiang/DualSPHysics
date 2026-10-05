#!/usr/bin/env python3
"""Static validation for fresh099 generated metadata only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PACKAGE = Path(__file__).resolve().parents[1]
RAW_SUFFIXES = {".bi4", ".h5", ".hdf5", ".csv", ".dat", ".vtk", ".vtu", ".vtp"}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), path
    return value


def assert_no_csv_key(value: Any, where: str = "root") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            assert key.lower() != "csv", f"raw CSV key leaked into compact evidence at {where}.{key}"
            assert_no_csv_key(child, f"{where}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_no_csv_key(child, f"{where}[{index}]")


def check_future_nulls(value: Any, where: str = "root") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"future_output_hashes", "render_outputs_future_hashes", "future_typed_product_hashes", "future_xmf_hashes"}:
                if isinstance(child, dict):
                    assert all(item is None for item in child.values()), f"future hash not null at {where}.{key}"
            if key.endswith("_output_hash") or key.endswith("_output_sha256"):
                assert child is None, f"future output hash not null at {where}.{key}"
            check_future_nulls(child, f"{where}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            check_future_nulls(child, f"{where}[{index}]")


def main() -> None:
    source = load(PACKAGE / "source-binding.json")
    assert source["case_count"] == 24
    assert source["independent_case_count_increment"] == 0
    assert source["arrays_read_by_source"] is False
    assert source["jobs_started_by_source"] is False
    assert source["shared_registry_write_by_source"] is False

    evidence = load(PACKAGE / "evidence/root533-conversion-report-snapshot.json")
    rows = evidence["cases"]
    assert len(rows) == 24
    assert evidence["vector_contract"]["semantic_type"] == "N3"
    assert evidence["arrays_read_by_source"] is False
    assert evidence["jobs_started_by_source"] is False
    for row in rows:
        summary = row.get("report_summary")
        if row["typed_status"] == "completed_reported":
            assert summary is not None
            assert summary["frames"] == 1201
            assert summary["particles"] == 83233
            assert summary["solver_dimension"]["solver_dimension"] == 3
            assert summary["time_evidence"]["strictly_increasing"] is True
            assert summary["partvtk_validation"]["all_passed"] is True
            lifecycle = summary["typed_identity_lifecycle"]
            assert lifecycle["identity_key"] == "(Zone,Idp)"
            assert "first_missing_frame_by_mk" in lifecycle
            assert "first_missing_frame_by_type" in lifecycle
            assert "transient_missing_frame_count" in lifecycle
            assert lifecycle["padding_or_reclassification"]
            assert_no_csv_key(summary, f"typed[{row['case_id']}]")
        check_future_nulls(row, f"typed[{row['case_id']}]")

    xmf = load(PACKAGE / "evidence/fresh098-xmf-result-snapshot.json")
    assert len(xmf["cases"]) == 24
    for row in xmf["cases"]:
        check_future_nulls(row, f"xmf[{row['case_id']}]")

    binding_paths = sorted((PACKAGE / "bindings").glob("*-render-binding.json"))
    request_paths = sorted((PACKAGE / "requests").glob("*-full1201-render-fresh099-disabled.request.json"))
    assert len(binding_paths) == 24
    assert len(request_paths) == 24
    for path in binding_paths:
        binding = load(path)
        assert binding["typed_lifecycle_policy"]["no_padding"] is True
        assert binding["typed_lifecycle_policy"]["no_reclassification"] is True
        assert binding["typed_lifecycle_policy"]["no_mass_rescale"] is True
        assert binding["renderer"]["all_temporal_frames_required"] is True
        assert binding["expected_native_contract"]["vector_semantic_type"] == "N3"
        check_future_nulls(binding, path.name)
    for path in request_paths:
        request = load(path)
        assert request["disabled"] is True
        assert request["execution_allowed"] is False
        assert request["launch"] is False
        assert request["launch_allowed"] is False
        assert request["launch_owner"] == "root"
        assert request["source_only"] is True
        assert request["cpu_task_kind"] == "audit"
        assert request["cpu_threads"] == 2
        assert request["expected_frames"] == 1201
        assert request["vector_semantic_type"] == "N3"
        assert request["future_sha256_values"].startswith("null")
        assert all(Path(name).suffix.lower() not in RAW_SUFFIXES for name in request["input_files"])
        assert all(value is None for value in request["deferred_input_sha256"].values())
        assert set(request["input_files"]) == set(request["input_sha256"])
        check_future_nulls(request, path.name)

    print("fresh099 static contract: PASS")
    print(json.dumps({
        "cases": 24,
        "disabled_render_requests": 24,
        "root533_rows": len(rows),
        "arrays_read_by_source": False,
        "jobs_started_by_source": False,
        "shared_registry_write_by_source": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
