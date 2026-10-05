#!/usr/bin/env python3
"""Validate fresh100 source metadata without touching scientific payloads."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PACKAGE = Path(__file__).resolve().parents[1]
RAW_SUFFIXES = {".bi4", ".h5", ".hdf5", ".csv", ".dat", ".vtk", ".vtu", ".vtp"}
HEX64 = set("0123456789abcdef")


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), path
    return value


def check_future_nulls(value: Any, where: str = "root") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            low = str(key).lower()
            if low in {
                "future_output_hashes",
                "future_render_hashes",
                "future_sha256_values",
                "future_typed_product_hashes",
                "future_xmf_hashes",
            }:
                if isinstance(child, dict):
                    assert all(item is None for item in child.values()), f"future hash at {where}.{key}"
                elif low != "future_sha256_values":
                    assert child is None, f"future hash at {where}.{key}"
            if low.endswith("_output_hash") or low.endswith("_output_sha256"):
                assert child is None, f"future output hash at {where}.{key}"
            check_future_nulls(child, f"{where}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            check_future_nulls(child, f"{where}[{index}]")


def assert_no_h5_digest(value: Any, where: str = "root") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            low = str(key).lower()
            if "h5" in low or "hdf" in low:
                if "omit" in low or low.endswith("_by_source"):
                    pass
                elif low.endswith("sha256") or low.endswith("_hash"):
                    raise AssertionError(f"H5 digest leaked at {where}.{key}")
            assert_no_h5_digest(child, f"{where}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_no_h5_digest(child, f"{where}[{index}]")


def main() -> None:
    source = load(PACKAGE / "source-binding.json")
    assert source["scope_id"].endswith("root547_xmf_root023_render_v1")
    assert source["case_count"] == 24
    assert source["independent_case_count_increment"] == 0
    assert source["arrays_read_by_source"] is False
    assert source["jobs_started_by_source"] is False
    assert source["shared_registry_write_by_source"] is False
    assert source["future_requests_disabled"] is True

    typed = load(PACKAGE / "evidence/root533-conversion-snapshot.json")
    assert len(typed["cases"]) == 24
    assert typed["vector_contract"]["semantic_type"] == "N3"
    for row in typed["cases"]:
        summary = row.get("report_summary")
        if row["typed_status"] == "completed/0_with_report":
            assert summary is not None
            assert summary["frames"] == 1201
            assert summary["particles"] == 83233
            assert summary["solver_dimension"]["solver_dimension"] == 3
            assert summary["typed_identity_lifecycle"]["identity_key"] == "(Zone,Idp)"
            assert summary["typed_identity_lifecycle"]["padding_or_reclassification"]
        check_future_nulls(row, f"typed[{row['case_id']}]")
        assert_no_h5_digest(row, f"typed[{row['case_id']}]")

    xmf = load(PACKAGE / "evidence/root547-xmf-metadata-snapshot.json")
    assert len(xmf["cases"]) == 24
    for row in xmf["cases"]:
        assert row["actual_hdf5_hashes_omitted"] is True
        if row["status"] == "completed/0_with_manifest_xmf":
            assert row["root547_attempt_id"].endswith("-root547")
            assert "-root547/" in str(row["output_root"]) + "/"
            manifest = row["manifest_summary"]
            xml = row["xmf_xml_summary"]
            assert manifest["frames"] == 1201
            assert manifest["particles"] == 83233
            assert manifest["expected_dimension"] == 3
            assert xml["frame_count"] == 1201
            assert xml["first_topology_elements"] == 83233
            assert xml["last_topology_elements"] == 83233
            assert xml["geometry_types"] == ["XYZ"]
            assert xml["velocity_is_n3_vector"] is True
            assert xml["hdf_references_omitted"] is True
        check_future_nulls(row, f"xmf[{row['case_id']}]")
        assert_no_h5_digest(row, f"xmf[{row['case_id']}]")

    bindings = sorted((PACKAGE / "bindings").glob("*-render-fresh100-binding.json"))
    requests = sorted((PACKAGE / "requests").glob("*-full1201-render-fresh100-disabled.request.json"))
    assert len(bindings) == 24
    assert len(requests) == 24
    binding_cases = set()
    for path in bindings:
        value = load(path)
        binding_cases.add(value["case_id"])
        assert value["typed_lifecycle_policy"]["no_padding"] is True
        assert value["typed_lifecycle_policy"]["no_reclassification"] is True
        assert value["typed_lifecycle_policy"]["no_mass_rescale"] is True
        assert value["renderer"]["all_temporal_frames_required"] is True
        assert value["renderer"]["vector_semantic_type"] == "N3"
        check_future_nulls(value, path.name)
        assert_no_h5_digest(value, path.name)
    request_cases = set()
    for path in requests:
        value = load(path)
        request_cases.add(value["case_id"])
        assert value["disabled"] is True
        assert value["execution_allowed"] is False
        assert value["launch"] is False
        assert value["launch_allowed"] is False
        assert value["launch_owner"] == "root"
        assert value["source_only"] is True
        assert value["cpu_task_kind"] == "audit"
        assert value["cpu_threads"] == 2
        assert value["expected_frames"] == 1201
        assert value["vector_semantic_type"] == "N3"
        assert value["future_sha256_values"].startswith("null")
        assert "-root547/" in " ".join(value["command"])
        assert all(Path(name).suffix.lower() not in RAW_SUFFIXES for name in value["input_files"])
        assert set(value["input_files"]) == set(value["input_sha256"])
        assert all(item is None for item in value["deferred_input_sha256"].values())
        check_future_nulls(value, path.name)
        assert_no_h5_digest(value, path.name)
        # A deferred H5 path is allowed as a future renderer input, but it
        # must never have a source-side digest.
        for name in value["deferred_input_files"]:
            if Path(name).suffix.lower() in RAW_SUFFIXES:
                assert value["deferred_input_sha256"][name] is None
    assert binding_cases == request_cases

    audit = load(PACKAGE / "metadata/path-rebinding-audit.json")
    assert len(audit["cases"]) == 24
    assert audit["old_package_modified_by_source"] is False
    for row in audit["cases"]:
        assert row["fresh099_unchanged"] is True
        assert row["root547_actual_attempt_id"].endswith("-root547")
        assert "-root547/" in str(row["root547_actual_output_root"]) + "/"
        assert row["new_output_root"].endswith("-render-fresh100")

    print("fresh100 static contract: PASS")
    print(json.dumps({
        "cases": 24,
        "disabled_root023_requests": 24,
        "root547_metadata_rows": len(xmf["cases"]),
        "root533_rows": len(typed["cases"]),
        "arrays_read_by_source": False,
        "jobs_started_by_source": False,
        "shared_registry_write_by_source": False,
        "h5_read_or_hashed_by_source": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
