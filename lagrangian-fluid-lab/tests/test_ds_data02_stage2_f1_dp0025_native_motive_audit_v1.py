from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts/ds_data02_stage2_f1_dp0025_native_motive_audit_v1.py"
SPEC = importlib.util.spec_from_file_location("f1_motive_audit_v1", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


TOOL = MODULE.TOOL
CONFIG = MODULE.CONFIG


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _make_fixture(tmp_path: Path, *, count: int = 1, bad_part_frame: bool = False):
    data = tmp_path / "solver-output" / "data"
    data.mkdir(parents=True)
    raw = data / ("Part_0000.bi4" if bad_part_frame else "PartOut_000.obi4")
    raw.write_bytes(b"small native PartOut fixture\n")
    runparts = data.parent / "RunPARTs.csv"
    runparts.write_text(
        "Part;TimeStep [s];NpOut;NpOutPos;NpOutRho;NpOutMov\n"
        "0;0.0;0;0;0;0\n"
        f"1;0.5;{count};{count};0;0\n",
        encoding="utf-8",
    )
    runout = data.parent / "Run.out"
    runout.write_text(
        "Particles of simulation (initial): 100\n"
        f"Excluded particles...............: {count}\n"
        "Excluded particles due to Density: 0\n",
        encoding="utf-8",
    )
    xml = tmp_path / "input.xml"
    xml.write_text("<case/>\n", encoding="utf-8")
    solver_receipt = tmp_path / "solver-receipt.json"
    solver_receipt.write_text("{}\n", encoding="utf-8")
    solver_proof = tmp_path / "solver-proof.json"
    solver_proof.write_text("{}\n", encoding="utf-8")
    prior = tmp_path / "prior.json"
    prior.write_text("{}\n", encoding="utf-8")
    output = tmp_path / "attempt"
    output.mkdir()
    csv_path = output / "PartOut.csv"
    csv_path.write_text(
        "Idp,PartOut,Motive,Pos.x [m],Pos.y [m],Pos.z [m],Rhop [kg/m^3]\n"
        + "42,1,1,1,2,3,1000\n" * count,
        encoding="utf-8",
    )
    resume = output / "resume.csv"
    resume.write_text("ok\n", encoding="utf-8")
    command = [
        "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python",
        str(TOOL),
        "-dirdata", str(data),
        "-savecsv", str(csv_path),
        "-saveresume", str(resume),
        "-createdirs:1", "-csvsep:1",
    ]
    source_paths = {
        "raw_partout": raw,
        "runparts": runparts,
        "run_out": runout,
        "solver_receipt": solver_receipt,
        "solver_proof": solver_proof,
        "generated_xml": xml,
        "partvtk_binary": TOOL,
        "dsph_config": CONFIG,
        "prior_identity_report": prior,
    }
    source = {
        key: {"path": str(path), "sha256": _sha(path), "bytes": path.stat().st_size}
        for key, path in source_paths.items()
    }
    manifest = {
        "schema": MODULE.SCHEMA,
        "family_id": "F1",
        "case": {
            "case_id": "TEST_F1_DP0025",
            "physical_case_id": "TEST_F1_DP0025_HALF_CFL",
            "expected_excluded_count": count,
            "expected_runout_density_excluded": 0,
            "expected_removed_ids": [42],
        },
        "source": source,
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    files = [*source_paths.values()]
    hashes = {str(path): _sha(path) for path in files}
    receipt = {
        "status": "completed",
        "returncode": 0,
        "output_root": str(output),
        "command": command,
        "request": {
            "case_id": "TEST_F1_DP0025",
            "input_files": [str(path) for path in files],
            "input_sha256": hashes,
            "command": [
                command[0], command[1], "-dirdata", str(data), "-savecsv",
                "{attempt_root}/PartOut.csv", "-saveresume", "{attempt_root}/resume.csv",
                "-createdirs:1", "-csvsep:1",
            ],
        },
        "input_hashes_at_launch": hashes,
        "input_hashes_after_run": hashes,
    }
    receipt_path = output / "execution-receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    return manifest_path, receipt_path, output / "report.json"


def test_valid_native_motive_and_saved_time(tmp_path):
    manifest, receipt, report = _make_fixture(tmp_path)
    result = MODULE.audit(manifest, receipt, report)
    assert result["motive_counts"] == {"position": 1, "density": 0, "movement": 0}
    assert result["saved_record_time_brackets_s"]["42"]["saved_time_s"] == 0.5
    assert result["qualification"]["physical_fate"] == "UNKNOWN"


def test_rejects_count_or_identity_mismatch(tmp_path):
    manifest, receipt, report = _make_fixture(tmp_path, count=2)
    with pytest.raises(MODULE.AuditError, match="duplicate Idp"):
        MODULE.audit(manifest, receipt, report)


def test_rejects_trajectory_part_as_source(tmp_path):
    manifest, receipt, report = _make_fixture(tmp_path, bad_part_frame=True)
    with pytest.raises(MODULE.AuditError, match="trajectory Part_"):
        MODULE.audit(manifest, receipt, report)
