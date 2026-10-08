from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_s1_native_source_adapter_v1.py"
MANIFEST = (
    ROOT
    / "campaigns/ds-data-02/stage2/requests/f2-s1-native-source-adapter-v1"
    / "f2-s1-native-source-adapter-v1-manifest.json"
)
SPEC = importlib.util.spec_from_file_location("f2_s1_native_source_adapter_v1", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _manifest_copy(tmp_path: Path) -> Path:
    target = tmp_path / "manifest.json"
    target.write_text(MANIFEST.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def test_actual_f2_s1_source_join_closes_three_ids(tmp_path: Path) -> None:
    output = tmp_path / "adapter.json"
    result = MODULE.audit(MANIFEST, output)
    assert result["status"] == "COMPLETED_F2_S1_NATIVE_SOURCE_JOIN_WITH_PHYSICAL_FATE_UNKNOWN"
    assert result["case_identity"]["current_case_index"] == 78
    assert result["native_identity"]["id_count"] == 3
    assert result["native_identity"]["source_mk_counts"] == {"1": 3, "2": 0, "3": 0}
    assert [row["idp"] for row in result["native_identity"]["ids"]] == [397194, 403829, 404024]
    assert result["conversion_join"]["typed_blocks_identical"] is True
    assert result["conversion_join"]["v37_converter_report"]["output_hdf5"]["opened"] is False
    assert result["claim_boundary"]["physical_fate"].startswith("UNKNOWN")
    assert result["claim_boundary"]["typed_only_scientific_credit"] == "NOT_GRANTED"
    assert result["read_policy"]["trajectory_h5_opened"] is False
    assert result["read_policy"]["part_frames_opened"] is False


def test_wrong_case_identity_is_rejected_before_source_join(tmp_path: Path) -> None:
    path = _manifest_copy(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["case"]["identity"]["physical_case_id"] = "F2_WRONG_RUN"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(MODULE.AdapterError, match="source identity differs"):
        MODULE.audit(path, tmp_path / "out.json")


def test_wrong_source_digest_is_rejected(tmp_path: Path) -> None:
    path = _manifest_copy(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["bindings"]["v37_converter_report"]["sha256"] = "0" * 64
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(MODULE.AdapterError, match="V37 converter report digest differs"):
        MODULE.audit(path, tmp_path / "out.json")


def test_trajectory_is_metadata_only_even_when_report_names_hdf5() -> None:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    # The contract may name the producer and V37 HDF5 paths, but neither path
    # is an input binding.  This prevents a future request builder from
    # silently turning metadata provenance into an HDF5 read.
    input_names = [Path(ref["path"]).name for ref in data["bindings"].values()]
    assert "trajectory.h5" not in input_names
    assert all(not (name.startswith("Part_") and name.endswith(".bi4")) for name in input_names)
