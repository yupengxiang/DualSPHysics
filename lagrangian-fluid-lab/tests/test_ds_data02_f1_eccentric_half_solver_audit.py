from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.ds_data02_f1_eccentric_half_solver_audit import AuditError, audit_solver


def _fixture(tmp_path: Path) -> dict[str, Path]:
    xml = tmp_path / "case.xml"
    xml.write_text(
        """<case><execution>
          <parameters>
            <parameter key="DtIni" value="0.0005"/>
            <parameter key="DtMin" value="0.0005"/>
            <parameter key="DtFixed" value="0.0005"/>
            <parameter key="TimeMax" value="0.002"/>
            <parameter key="TimeOut" value="0.001"/>
          </parameters>
          <particles np="3" nb="1"><fixed begin="0" count="1" mk="10"/><fluid begin="1" count="2" mk="1"/></particles>
          <constants><data2d value="false"/></constants>
        </execution></case>"""
    )
    run_out = tmp_path / "Run.out"
    run_out.write_text(
        "**3D-Simulation parameters:\nBoundary=\"DBC\"\n"
        "CaseNp=3\nCaseNbound=1\nCaseNfluid=2\n"
        "DtIni=0.0005\nDtMin=0.0005\nFixedDt=0.0005\nTimeMax=0.002\nTimePart=0.001\n"
        "Particle summary:\n  Fixed....: 1  id:(0-0) MKs:1 (10)\n"
        "  Moving...: 0\n  Floating.: 0\n  Fluid....: 2  id:(1-2) MKs:1 (1)\n"
        "Particles of simulation (initial): 3\nDTs adjusted to DtMin............: 0\n"
        "Excluded particles...............: 0\nPART files.......................: 3\n"
        "Maximum number of particles......: 3\nSteps of simulation..............: 4\n"
        "Finished execution (code=0).\n"
    )
    run_csv = tmp_path / "Run.csv"
    run_csv.write_text(
        "#RunName;Np;PhysicalTime;PartFiles;PartsOut;MaxParticles;Nbound;Nfixed;Dp\n"
        "case;3;0.002;3;0;3;1;1;0.01\n"
    )
    run_parts = tmp_path / "RunPARTs.csv"
    header = ";".join(
        [
            "Part", "TimeStep [s]", "Steps", "DTsMin", "PartRuntime [s]", "NpSave", "NpSim", "NpNew", "NpOut",
            "NctSim", "NpAlloc [X]", "NctAlloc [X]", "SimRuntime [s]", "NpbSim", "NpfSim", "NpNormal",
            "NpOutPos", "NpOutRho", "NpOutMov", "DtMin [s]", "DtMax [s]",
        ]
    )
    rows = []
    for index, current in enumerate((0.0, 0.001, 0.002)):
        dt = "0" if index == 0 else "0.0005"
        rows.append(";".join(map(str, [index, current, 2, 0, 0, 3, 3, 0, 0, 1, 1, 1, 0, 1, 2, 3, 0, 0, 0, dt, dt])))
    run_parts.write_text(header + "\n" + "\n".join(rows) + "\n")
    receipt = tmp_path / "execution-receipt.json"
    payload = {
        "status": "completed",
        "returncode": 0,
        "termination_reason": "completed",
        "request": {
            "attempt_id": "fixture-half",
            "numeric_parameters": {"DtIni_s": 0.0005, "DtMin_s": 0.0005, "DtFixed_s": 0.0005, "TimeMax_s": 0.002, "TimeOut_s": 0.001},
            "expected_native": {"saved_frames": 3, "dimension": 3, "fluid_particles_type3": 2, "fixed_particles": 1, "total_particles": 3, "initial_fluid_mass_kg": 0.002, "continuous_initial_mass_kg": 0.002, "expected_solver_excluded_particles": 0},
        },
        "input_hashes_at_launch": {"case.xml": "abc"},
        "input_hashes_after_run": {"case.xml": "abc"},
    }
    receipt.write_text(json.dumps(payload))
    return {"xml": xml, "run_out": run_out, "run_csv": run_csv, "run_parts": run_parts, "receipt": receipt}


def test_audit_reads_native_text_ledger_without_bi4(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    result = audit_solver(
        solver_receipt=paths["receipt"],
        run_out=paths["run_out"],
        run_parts=paths["run_parts"],
        run_csv=paths["run_csv"],
        generated_xml=paths["xml"],
    )
    assert result["actual_solver"]["saved_frames"] == 3
    assert result["actual_solver"]["final_saved_time_s"] == pytest.approx(0.002)
    assert result["typed_counts"]["fluid_type3"] == 2
    assert result["exclusion_ledger"]["closed_native_solver_ledger"] is True
    assert result["q_n_status"] == "not_assessed"


def test_audit_rejects_excluded_particle_in_runparts(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    lines = paths["run_parts"].read_text().splitlines()
    fields = lines[1].split(";")
    fields[8] = "1"  # NpOut
    lines[1] = ";".join(fields)
    paths["run_parts"].write_text("\n".join(lines) + "\n")
    with pytest.raises(AuditError, match="nonzero exclusion field NpOut"):
        audit_solver(
            solver_receipt=paths["receipt"],
            run_out=paths["run_out"],
            run_parts=paths["run_parts"],
            run_csv=paths["run_csv"],
            generated_xml=paths["xml"],
        )
