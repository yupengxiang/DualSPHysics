import json
from pathlib import Path

import pytest

from scripts import ds_data02_f3_raw_manifest as manifest


def _inputs(tmp_path: Path, frame_count: int = 3):
    data = tmp_path / "data"
    data.mkdir()
    (data / "PartInfo.ibi4").write_bytes(b"part-info")
    for index in range(frame_count):
        (data / f"Part_{index:04d}.bi4").write_bytes(f"frame-{index}".encode())
    runparts = tmp_path / "RunPARTs.csv"
    rows = [
        "Part;TimeStep [s];NpOut;Steps;DtMin [s];DtMax [s];NpSim;NpfSim",
    ]
    for index in range(frame_count):
        rows.append(f"{index};{index * 5.0};0;10;0.001;0.002;10;4")
    runparts.write_text("\n".join(rows) + "\n")
    run_csv = tmp_path / "Run.csv"
    run_csv.write_text("Steps;PhysicalTime;PartFiles;Np;Dp;Configuration\n30;10;3;10;0.1;test\n")
    run_out = tmp_path / "Run.out"
    run_out.write_text("** 3D-Simulation parameters\nDtMin=0.001\nTimePart=5\nTimeMax=10\n")
    receipt = tmp_path / "execution-receipt.json"
    receipt.write_text(json.dumps({"status": "completed", "returncode": 0, "request": {"case_id": "F3_TEST", "attempt_id": "a"}}))
    xml = tmp_path / "case.xml"
    xml.write_text('<case><acctimesfile value="control.csv" /></case>')
    (tmp_path / "control.csv").write_text("control\n")
    prepared = tmp_path / "prepared-source-manifest.json"
    prepared.write_text(json.dumps({"status": "completed_actual_read_only_copy"}))
    return data, runparts, run_csv, run_out, receipt, xml, prepared


def test_manifest_enumerates_all_frames_without_raw_rehash(tmp_path):
    args = _inputs(tmp_path)
    output = tmp_path / "manifest.json"
    result = manifest.make_manifest(
        data_root=args[0], runparts=args[1], run_csv=args[2], run_out=args[3],
        solver_receipt=args[4], generated_xml=args[5], prepared_source_manifest=args[6],
        output=output, expected_frames=3,
    )
    assert result["raw_source"]["frame_count"] == 3
    assert len(result["raw_source"]["files"]) == 4
    assert result["raw_source"]["hash_policy"] == "metadata_only_no_full_raw_rehash"
    assert result["native_ledger"]["runparts"]["excluded_interval_sum_NpOut"] == 0
    assert result["q_n_status"] == "not_assessed"


def test_manifest_rejects_missing_frame(tmp_path):
    args = _inputs(tmp_path)
    (args[0] / "Part_0001.bi4").unlink()
    with pytest.raises(manifest.RawManifestError, match="frame indices/count"):
        manifest.make_manifest(
            data_root=args[0], runparts=args[1], run_csv=args[2], run_out=args[3],
            solver_receipt=args[4], generated_xml=args[5], prepared_source_manifest=args[6],
            output=tmp_path / "manifest.json", expected_frames=3,
        )
