"""Focused tests for the guarded ROOT238 F4 native-evidence worker."""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts/ds_data02_stage2_f4_unlocated_native_evidence_v3.py"
SPEC = importlib.util.spec_from_file_location("f4_unlocated_native_evidence_v3", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
WORKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WORKER)


def _runparts_header() -> list[str]:
    return list(WORKER.RUNPARTS_COLUMNS)


def _runparts_row(*, bad_integer_count: bool = False) -> list[str]:
    values = {column: "0" for column in _runparts_header()}
    values.update(
        {
            "Part": "0",
            "TimeStep [s]": "0.0",
            "Steps": "0",
            "NpSave": "1",
            "NpSim": "1",
            "NpOut": "1",
            "NpAlloc [X]": "1.000307",
            "NctAlloc [X]": "2.000000",
            "NpOutPos": "1",
            "NpAlloc": "1.000307" if bad_integer_count else "1,234",
            "NctAlloc": "0",
        }
    )
    return [values[column] for column in _runparts_header()]


def _write_fixture(tmp_path: Path, *, duplicate_partout: bool = False, bad_integer_count: bool = False) -> Path:
    partout = tmp_path / "PartOut.csv"
    partout.write_text(
        "Pos.x [m],Pos.y [m],Pos.z [m],PartOut,Motive,Idp,Rhop [kg/m^3]\n"
        "0.1,0.2,0.3,0,1,42,998.0\n"
        + ("0.1,0.2,0.3,0,1,42,998.0\n" if duplicate_partout else ""),
        encoding="utf-8",
    )
    runparts = tmp_path / "RunPARTs.csv"
    with runparts.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter=";", lineterminator="\n")
        writer.writerow(_runparts_header())
        writer.writerow(_runparts_row(bad_integer_count=bad_integer_count))
        stream.write("# parser fixture footer\n")
    manifest = tmp_path / "fixture.json"
    manifest.write_text(json.dumps({"fixture": True, "partout": str(partout), "runparts": str(runparts)}), encoding="utf-8")
    return manifest


def test_root232_exact_intersection_and_root235_reuse_are_explicit() -> None:
    current, rows, selected, excluded, root235 = WORKER._validate_metadata(
        WORKER.CURRENT_DEFAULT,
        WORKER.INVENTORY_DEFAULT,
        WORKER.OVERLAY_DEFAULT,
        WORKER.HISTORICAL_DEFAULT,
        WORKER.ROOT232_MANIFEST_DEFAULT,
        WORKER.ROOT235_DEFAULT_PROOF,
    )
    assert current["schema"] == WORKER.CURRENT_SCHEMA
    assert len(rows) == 118
    assert len(selected) == 5
    assert len(excluded) == 3
    assert len(root235) == 3
    root232 = set(WORKER._root232_ids(WORKER._read_json(WORKER.ROOT232_MANIFEST_DEFAULT, "ROOT232")))
    assert set(selected).issubset(root232)
    assert set(selected).isdisjoint(root235)


def test_runparts_accepts_float_allocation_ratios_and_thousands_counts(tmp_path: Path) -> None:
    manifest = _write_fixture(tmp_path)
    runparts = Path(json.loads(manifest.read_text())["runparts"])
    result = WORKER._runparts(runparts, {"timeline": {"time_s": [0.0]}})
    assert result["rows"] == 1
    assert result["totals"]["NpOut"] == 1


def test_runparts_rejects_ratio_in_integer_count_column(tmp_path: Path) -> None:
    manifest = _write_fixture(tmp_path, bad_integer_count=True)
    runparts = Path(json.loads(manifest.read_text())["runparts"])
    with pytest.raises(WORKER.EvidenceError, match="not numeric"):
        WORKER._runparts(runparts, {"timeline": {"time_s": [0.0]}})


def test_partout_rejects_duplicate_identity(tmp_path: Path) -> None:
    manifest = _write_fixture(tmp_path, duplicate_partout=True)
    partout = Path(json.loads(manifest.read_text())["partout"])
    with pytest.raises(WORKER.EvidenceError, match="duplicate identity"):
        WORKER._partout_csv(partout)


def test_real_fixture_cli_has_no_scientific_credit(tmp_path: Path) -> None:
    manifest = _write_fixture(tmp_path)
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "fixture", "--manifest", str(manifest)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["status"] == "FIXTURE_PARSER_PASS_NO_SCIENTIFIC_CREDIT"
    assert result["scientific_credit"] is False


def test_real_fixture_cli_rejects_bad_integer_count(tmp_path: Path) -> None:
    manifest = _write_fixture(tmp_path, bad_integer_count=True)
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "fixture", "--manifest", str(manifest)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    assert "not numeric" in completed.stdout


def test_prepare_binds_completed_root232_proof_paths(tmp_path: Path) -> None:
    """V3 must emit the completed ROOT232 paths, never request placeholders."""
    output_root = tmp_path / "root238-v3"
    request_path = tmp_path / "root238-v3-request.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "prepare",
            "--output-root",
            str(output_root),
            "--request-output",
            str(request_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    assert result["launch_allowed"] is True
    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    assert manifest["schema"] == "ds02.stage2.f4-unlocated-native-evidence.v3"
    placeholder = "stage2/requests/typed-lifecycle-batch-v1-f4-root-prepared-232-001/case-manifests"
    for entry in manifest["contracts"]:
        contract = json.loads(Path(entry["path"]).read_text(encoding="utf-8"))
        deferred = contract["root232_deferred"]
        summary = deferred["summary"]
        records = deferred["records"]
        assert placeholder not in summary["path"]
        assert placeholder not in records["path"]
        assert Path(summary["path"]).is_file()
        assert Path(records["path"]).is_file()
        assert summary["sha256"] != "PARENT_GUARD_COMPUTED"
        assert records["sha256"] != "PARENT_GUARD_COMPUTED"
        assert deferred["terminal_proof_case"]["records_stat_only"]["path"] == records["path"]
    request = json.loads(request_path.read_text(encoding="utf-8"))
    deferred_paths = set(request["deferred_input_files"])
    assert any("STAGE2_TYPED_LIFECYCLE_BATCH_F4_ROOT232" in path for path in deferred_paths)
    assert not any(placeholder in path for path in deferred_paths)


def test_v3_deferred_ref_rejects_missing_path(tmp_path: Path) -> None:
    missing = tmp_path / "missing-root232-summary.json"
    with pytest.raises(WORKER.EvidenceError, match="missing"):
        WORKER._deferred_ref(
            missing,
            "ROOT232 proof summary",
            declared_sha="0" * 64,
            allow_missing=False,
        )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_audit_integration_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Build one complete source contract and a subprocess decoder fixture."""
    case_id = "F4_V3_DIRECTORY_AUDIT_FIXTURE"
    data_dir = tmp_path / "native-data"
    data_dir.mkdir()
    partout = data_dir / "PartOut_000.obi4"
    partout.write_bytes(b"OBI4 fixture bytes\n")

    summary = tmp_path / "typed-lifecycle-v4-summary.json"
    summary.write_text(
        json.dumps(
            {
                "physical_case_id": case_id,
                "family_id": "F4",
                "records": {"rows": 1},
                "timeline": {"time_s": [0.0]},
            }
        ),
        encoding="utf-8",
    )
    records = tmp_path / "typed-lifecycle-v4-records.jsonl"
    records.write_text(
        json.dumps({"record_fields": "one row per static (Zone, Idp); saved-frame lifecycle only"})
        + "\n"
        + json.dumps(
            {
                "zone": 0,
                "idp": 42,
                "initial_role": "fluid",
                "initial_mass_kg": 0.001,
                "first_disappeared_frame": 1,
                "first_disappeared_time_s": 0.0,
                "first_disappeared_bracket_s": [0.0, 0.0],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    runparts = tmp_path / "RunPARTs.csv"
    values = {column: "0" for column in WORKER.RUNPARTS_COLUMNS}
    values.update(
        {
            "Part": "0",
            "TimeStep [s]": "0.0",
            "Steps": "0",
            "NpSave": "1",
            "NpSim": "1",
            "NpOut": "1",
            "NpOutPos": "1",
            "NpAlloc [X]": "1.000307",
            "NctAlloc [X]": "2.0",
            "NpAlloc": "1",
            "NctAlloc": "1",
        }
    )
    with runparts.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter=";", lineterminator="\n")
        writer.writerow(WORKER.RUNPARTS_COLUMNS)
        writer.writerow([values[column] for column in WORKER.RUNPARTS_COLUMNS])

    native_report = tmp_path / "native-omission-report.json"
    native_report.write_text(json.dumps({"physical_case_id": case_id, "excluded_particles": []}), encoding="utf-8")

    proof = tmp_path / "root232-proof.json"
    proof.write_text(
        json.dumps(
            {
                "schema": WORKER.ROOT232_PROOF_SCHEMA,
                "case_verifications": [
                    {
                        "physical_case_id": case_id,
                        "family_id": "F4",
                        "status": "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY",
                        "summary": {"path": str(summary), "sha256": _sha256(summary)},
                        "records_stat_only": {"path": str(records), "sha256": _sha256(records)},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    contract = tmp_path / "case-contract.json"
    contract.write_text(
        json.dumps(
            {
                "physical_case_id": case_id,
                "family_id": "F4",
                "claim_boundary": {
                    "native_motive": "NUMERICAL_PARTVTKOUT_MOTIVE_ONLY",
                    "physical_fate": "UNKNOWN",
                    "legal_flux": "UNKNOWN",
                    "dynamics": "UNKNOWN",
                },
                "native_deferred": {
                    "data_dir": {"path": str(data_dir)},
                    "partout_obi4": {"path": str(partout)},
                    "runparts_csv": {"path": str(runparts)},
                    "native_report": {"path": str(native_report), "sha256": _sha256(native_report)},
                },
            }
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": WORKER.MANIFEST_SCHEMA,
                "batch_id": "ROOT238_V3_FIXTURE",
                "family_id": "F4",
                "launch_allowed": True,
                "contracts": [{"physical_case_id": case_id, "path": str(contract)}],
            }
        ),
        encoding="utf-8",
    )

    decoder = tmp_path / "mock-PartVTKOut.py"
    decoder.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib, sys\n"
        "def arg(name): return pathlib.Path(sys.argv[sys.argv.index(name) + 1])\n"
        "csv = arg('-savecsv')\n"
        "resume = arg('-saveresume')\n"
        "csv.parent.mkdir(parents=True, exist_ok=True)\n"
        "csv.write_text('Pos.x [m],Pos.y [m],Pos.z [m],PartOut,Motive,Idp,Rhop [kg/m^3]\\n0.1,0.2,0.3,0,1,42,998.0\\n', encoding='utf-8')\n"
        "resume.write_text('fixture\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )
    decoder.chmod(0o755)
    return manifest, proof, decoder


def test_cli_audit_exercises_directory_decoder_and_exact_join(tmp_path: Path) -> None:
    manifest, proof, decoder = _write_audit_integration_fixture(tmp_path)
    output = tmp_path / "audit-report.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "audit",
            "--manifest",
            str(manifest),
            "--root232-proof",
            str(proof),
            "--output",
            str(output),
            "--partvtkout",
            str(decoder),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    assert result["status"] == "COMPLETED_ALL_CASES"
    assert result["completed"] == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["counts"] == {"completed": 1, "failed": 0, "requested": 1}
    case_result = report["case_results"][0]
    case_report = json.loads(Path(case_result["output"]).read_text(encoding="utf-8"))
    assert case_report["exact_join"]["count"] == 1
    assert case_report["native"]["official_tool"]["path"] == str(decoder.resolve())
