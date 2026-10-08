from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "ds_data02_stage2_external_solver_v4.py"
BUILDER = ROOT / "scripts" / "ds_data02_stage2_f7_nvme_counterpart_v4.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = _load(RUNNER, "ds02_external_solver_v4_test")
BUILDER_MODULE = _load(BUILDER, "ds02_f7_counterpart_v4_test")


def test_dense_builder_binds_full_savedt_window_without_actionable_h5() -> None:
    request = BUILDER_MODULE.build_same_cfl()
    assert request["schema"] == "ds02.stage2.external-solver-request.v4"
    assert request["status"] == "READY_FOR_PARENT_GUARD"
    assert request["source_provenance"]["native_save_interval_s"] == 0.01
    assert request["source_provenance"]["frames"] == 1202
    assert request["source_provenance"]["native_time_window_s"] == [0.0, 12.00003209155591]
    assert request["source_provenance"]["dense_predecessor"]["scientific_credit"] == "NONE_CROPPED_TIMEOUT"
    assert not any(str(path).lower().endswith((".h5", ".xmf")) for path in request["input_files"])
    assert {Path(item["path"]).suffix.lower() for item in request["provenance_reference_files"]} == {".h5", ".xmf"}
    assert request["execution"]["reference_hdf5_open_forbidden"] is True
    assert request["execution"]["preflight_cfd_invoked"] is False
    assert request["gpu"]["gpu_uuid"] is None
    assert request["timing_contract"]["entry_time_includes_request_parse"] is True


def test_preflight_is_metadata_only_and_v4_schema_is_accepted(tmp_path: Path) -> None:
    # The v1 storage validator requires the real external filesystem device;
    # only the request JSON is placed in pytest's temporary directory.
    request = BUILDER_MODULE.build_same_cfl()
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request, sort_keys=True) + "\n")
    report = MODULE.run(path, io_slot_approved=False)
    assert report["schema"] == "ds02.stage2.external-solver-report.v4"
    assert report["status"] == "READY_FOR_PARENT_IO_SLOT"
    assert report["hdf5_opened"] is False
    assert report["raw_opened"] is False
    assert report["cfd_invoked"] is False
    assert report["ledger_mutated"] is False


def test_pre_post_input_evidence_catches_same_size_content_change(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"abcd")
    item = {"path": str(source), "sha256": MODULE.sha256_file(source),
            "content_scope": "post_reservation_hash"}
    before = MODULE._input_evidence([item], hash_content=True)
    source.write_bytes(b"wxyz")
    after = MODULE._input_evidence([item], hash_content=True)
    with pytest.raises(MODULE.ExternalSolverV4Error, match="changed during execution"):
        MODULE._compare_input_evidence(before, after)


def test_receipt_uses_runtime_selected_gpu_uuid_and_process_flag() -> None:
    fields = MODULE._selected_gpu_fields(
        {"uuid": "GPU-selected", "index": 2}, "GPU-requested", Path("/tmp/lease.json"))
    assert fields["uuid"] == "GPU-selected"
    assert fields["index"] == 2
    assert fields["requested_uuid"] == "GPU-requested"
    assert fields["uuid"] != fields["requested_uuid"]
    assert MODULE._execution_flags(False) == {"process_started": False, "cfd_invoked": False}
    assert MODULE._execution_flags(True) == {"process_started": True, "cfd_invoked": True}
