from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f4_typed_native_cause_batch_v1.py"
VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(VENV), str(SCRIPT), *args], text=True, capture_output=True, check=False)


def _write_runparts(path: Path) -> None:
    columns = (
        "Part", "TimeStep [s]", "Steps", "DTsMin", "PartRuntime [s]",
        "NpSave", "NpSim", "NpNew", "NpOut", "NctSim", "NpAlloc [X]",
        "NctAlloc [X]", "SimRuntime [s]", "NpbSim", "NpfSim", "NpNormal",
        "NpOutPos", "NpOutRho", "NpOutMov", "DtMin [s]", "DtMax [s]",
        "MemCPU [MiB]", "MemGPU [MiB]", "MemGPU_Cells [MiB]", "NpAlloc", "NctAlloc",
    )
    integer = {"Part", "Steps", "NpSave", "NpSim", "NpNew", "NpOut", "NctSim", "NpbSim", "NpfSim", "NpNormal", "NpOutPos", "NpOutRho", "NpOutMov", "NpAlloc", "NctAlloc"}
    values = ["0" if name in integer else "0.0" for name in columns]
    values[columns.index("NpAlloc [X]")] = "1.0"
    values[columns.index("NctAlloc [X]")] = "1.0"
    path.write_text(";".join(columns) + "\n" + ";".join(values) + "\n# fixture footer\n", encoding="utf-8")


def _fixture(tmp_path: Path, *, family: str = "F4", empty: bool = False) -> Path:
    summary = tmp_path / "summary.json"
    native = tmp_path / "native.json"
    records = tmp_path / "records.jsonl"
    partout = tmp_path / "PartOut.csv"
    runparts = tmp_path / "RunPARTs.csv"
    source_sha = "0" * 64
    summary.write_text(json.dumps({
        "source": {"trajectory_h5": {"known_sha256": source_sha}},
        "timeline": {"time_s": [0.0]},
    }) + "\n", encoding="utf-8")
    target = [] if empty else [{"zone": 0, "idp": 7, "native_motive_code": 1, "first_missing_frame": 0, "first_missing_bracket_s": [0.0, 0.0]}]
    native.write_text(json.dumps({"excluded_particles": target}) + "\n", encoding="utf-8")
    records.write_text(json.dumps({
        "schema": "ds02.stage2.typed-lifecycle-records.v4",
        "physical_case_id": "fixture-case",
        "family_id": "F4",
        "source_trajectory_sha256": source_sha,
        "record_fields": "one row per static (Zone, Idp); saved-frame lifecycle only",
        "record_population": 1,
    }) + "\n" + json.dumps({
        "zone": 0, "idp": 7, "first_disappeared_frame": 0,
        "first_disappeared_time_s": 0.0, "first_disappeared_bracket_s": [0.0, 0.0],
    }) + "\n", encoding="utf-8")
    partout.write_text("PartOut,Motive,Idp,Pos.x [m],Pos.y [m],Pos.z [m],Rhop [kg/m^3]\n0,1,7,0.0,0.0,0.0,1000.0\n", encoding="utf-8")
    _write_runparts(runparts)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "schema": "ds02.stage2.f4-typed-native-cause-batch.v1",
        "batch_id": "ROOT229_F4_TYPED_NATIVE_CAUSE_V1",
        "fixture": True,
        "contract": {
            "family_id": family,
            "physical_case_id": "fixture-case",
            "summary_path": str(summary),
            "native_path": str(native),
            "records_path": str(records),
            "partout_path": str(partout),
            "runparts_path": str(runparts),
        },
    }) + "\n", encoding="utf-8")
    return manifest


def test_prepare_binds_three_f4_targets_and_excludes_zero_controls(tmp_path: Path) -> None:
    output_root = tmp_path / "prepared"
    request = tmp_path / "request.json"
    result = _run("prepare", "--output-root", str(output_root), "--request-output", str(request), "--checkpoint", str(tmp_path / "checkpoint.json"))
    assert result.returncode == 0, result.stderr + result.stdout
    value = json.loads(result.stdout)
    assert value["case_count"] == 3
    assert value["control_case_count"] == 5
    manifest = json.loads(Path(value["manifest"]).read_text(encoding="utf-8"))
    assert manifest["resource_policy"]["expected_fluid_initial_count"] == 59072
    assert manifest["resource_policy"]["h5_content_read"] is False
    assert all(item["native_decode_requested"] is False for item in manifest["control_cases"])
    assert all(item["historical118_member"] is False for item in manifest["control_cases"])


def test_audit_cli_positive_fixture_uses_real_26_column_parser(tmp_path: Path) -> None:
    manifest = _fixture(tmp_path)
    output = tmp_path / "positive.json"
    result = _run("audit", "--manifest", str(manifest), "--output", str(output), "--allow-test-fixture")
    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "COMPLETED_TYPED_NATIVE_SAVED_FRAME_CROSSCHECK_NO_PHYSICAL_CREDIT"
    assert report["family_id"] == "F4"
    assert report["comparison_counts"]["saved_frame_matches"] == 1
    assert report["native_evidence"]["runparts"]["column_count"] == 26


def test_audit_cli_rejects_empty_target_fixture(tmp_path: Path) -> None:
    manifest = _fixture(tmp_path, empty=True)
    result = _run("audit", "--manifest", str(manifest), "--output", str(tmp_path / "empty.json"), "--allow-test-fixture")
    assert result.returncode != 0
    assert "fixture native target set is empty" in result.stdout


def test_audit_cli_rejects_cross_family_fixture(tmp_path: Path) -> None:
    manifest = _fixture(tmp_path, family="F6")
    result = _run("audit", "--manifest", str(manifest), "--output", str(tmp_path / "wrong-family.json"), "--allow-test-fixture")
    assert result.returncode != 0
    assert "cross-family" in result.stdout
