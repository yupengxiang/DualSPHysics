from __future__ import annotations

import json
from pathlib import Path

import h5py
import numpy as np

from scripts import l2_f5r_confirmation as f5r


def _write_definition(path: Path, *, symbolic: bool = True) -> None:
    if symbolic:
        posmin = 'x="default - 25%" y="default - 25%" z="default - 25%"'
        posmax = 'x="default + 25%" y="default + 25%" z="default + 75%"'
    else:
        posmin = 'x="-0.3" y="-0.1" z="-0.15"'
        posmax = 'x="1.5" y="0.5" z="1.35"'
    path.write_text(
        f"""<case>
  <casedef><geometry><definition dp="0.0075" />
    <commands><mainlist><drawbox><boxfill>bottom | left | right | front | back</boxfill></drawbox>
      <drawbox><boxfill>top | left | right | front | back</boxfill></drawbox></mainlist></commands>
  </geometry></casedef>
  <execution><parameters>
    <simulationdomain><posmin {posmin} /><posmax {posmax} /></simulationdomain>
  </parameters></execution>
</case>"""
    )


def _write_hdf5(path: Path, *, missing_final: bool = True) -> None:
    valid = np.asarray(
        [[True, True, True], [True, True, True], [True, True, not missing_final]],
        dtype=bool,
    )
    position = np.asarray(
        [
            [[0.1, 0.1, 0.1], [0.2, 0.1, 0.1], [0.3, 0.1, 0.2]],
            [[0.1, 0.1, 0.2], [0.2, 0.1, 0.2], [0.3, 0.1, 1.1]],
            [[0.1, 0.1, 0.3], [0.2, 0.1, 0.3], [np.nan, np.nan, np.nan]],
        ],
        dtype=np.float64,
    )
    if not missing_final:
        position[-1, 2] = [0.3, 0.1, 1.2]
    with h5py.File(path, "w") as handle:
        handle["time"] = np.asarray([0.0, 0.1, 0.2])
        handle["valid"] = valid
        handle["particle_id"] = np.asarray([10, 11, 12], dtype=np.int64)
        handle["position"] = position
        handle["velocity"] = np.zeros((3, 3, 3), dtype=np.float64)
        handle["mass"] = np.ones((3, 3), dtype=np.float64)
        handle.attrs["identity_key"] = "particle_id"


def _write_runparts(path: Path, *, excluded: bool = True) -> None:
    count = "1" if excluded else "0"
    position = count if excluded else "0"
    path.write_text(
        "Part;TimeStep [s];NpOut;NpOutPos;NpOutRho;NpOutMov\n"
        f"0;0.0;0;0;0;0\n"
        f"1;0.1;0;0;0;0\n"
        f"2;0.2;{count};{position};0;0\n"
    )


def _write_partout(path: Path, *, particle_id: int = 12) -> None:
    path.write_text(
        "Idp,PartOut,Motive,Pos.x [m],Pos.y [m],Pos.z [m],"
        "Vel.x [m/s],Vel.y [m/s],Vel.z [m/s],Rhop [kg/m^3]\n"
        f"{particle_id},2,1,0.3,0.1,1.1001,0.0,0.0,1.0,1000\n"
    )


def _write_attempt(path: Path, *, attempt_id: str = "20260919T000000Z-f5r00001", fresh: bool = True) -> None:
    path.mkdir(parents=True)
    payload = {
        "schema_version": 1,
        "case_id": f5r.FRESH_CASE_ID if fresh else f5r.LEGACY_CASE_ID,
        "attempt_id": attempt_id if fresh else f5r.LEGACY_ATTEMPT_ID,
        "status": "completed",
        "returncode": 0,
        "command": ["DualSPHysics5.4_linux64", "-gpu:3", "fresh-prefix", "fresh-output"],
    }
    (path / "attempt.json").write_text(json.dumps(payload))


def test_runtime_domain_repair_is_explicit_and_does_not_change_source(tmp_path: Path):
    source = tmp_path / "source.xml"
    target = tmp_path / "fresh.xml"
    _write_definition(source)
    original = source.read_text()
    result = f5r.configure_runtime_domain(source, target)

    assert source.read_text() == original
    assert result["physical_geometry_unchanged"] is True
    parsed = f5r.read_runtime_domain(target)
    assert parsed["all_faces_explicit"] is True
    assert parsed["domain"] == f5r.F5R_RUNTIME_DOMAIN
    assert "default" not in target.read_text()


def test_preflight_is_separate_from_shared_resume_state(tmp_path: Path):
    source = tmp_path / "source.xml"
    configured = tmp_path / "configured.xml"
    report = tmp_path / "preflight.json"
    _write_definition(source)
    state_path = f5r.RESUME_ROOT / "state.json"
    before = state_path.read_bytes() if state_path.is_file() else None

    result = f5r.build_preflight(
        source_xml=source,
        configured_xml=configured,
        output_report=report,
    )

    assert result["status"] == "preflight_ready"
    assert result["execution_policy"]["solver_invocations"] == 0
    assert result["execution_policy"]["gencase_invocations"] == 0
    assert result["execution_policy"]["shared_resume_state_modified"] is False
    assert json.loads(report.read_text())["provenance"]["execution_origin"] == "fresh_confirmation_not_started"
    assert (state_path.read_bytes() if state_path.is_file() else None) == before


def test_runparts_partout_hdf5_identity_ledger_passes_exact_join(tmp_path: Path):
    runparts_path = tmp_path / "RunPARTs.csv"
    partout_path = tmp_path / "PartOut.csv"
    hdf5_path = tmp_path / "fresh.h5"
    _write_runparts(runparts_path)
    _write_partout(partout_path)
    _write_hdf5(hdf5_path)

    runparts = f5r.parse_runparts(runparts_path)
    partout = f5r.parse_partout_csv(partout_path, runparts)
    hdf5 = f5r.audit_hdf5_identity(hdf5_path)
    ledger = f5r.reconcile_identity_ledger(runparts=runparts, partout=partout, hdf5=hdf5)

    assert runparts["totals"] == {"np_out": 1, "np_out_pos": 1, "np_out_rho": 0, "np_out_mov": 0}
    assert partout["particle_ids"] == [12]
    assert hdf5["missing_particle_ids"] == [12]
    assert hdf5["hard_structural_pass"] is True
    assert ledger["status"] == "pass"
    assert ledger["checks"]["hdf5_missing_ids_equal_partout_ids"] is True
    assert ledger["checks"]["runparts_total_matches_partout_rows"] is True


def test_identity_mismatch_is_blocked_instead_of_inferred(tmp_path: Path):
    runparts_path = tmp_path / "RunPARTs.csv"
    partout_path = tmp_path / "PartOut.csv"
    hdf5_path = tmp_path / "fresh.h5"
    _write_runparts(runparts_path)
    _write_partout(partout_path, particle_id=99)
    _write_hdf5(hdf5_path)

    runparts = f5r.parse_runparts(runparts_path)
    ledger = f5r.reconcile_identity_ledger(
        runparts=runparts,
        partout=f5r.parse_partout_csv(partout_path, runparts),
        hdf5=f5r.audit_hdf5_identity(hdf5_path),
    )

    assert ledger["status"] == "failed"
    assert ledger["missing_ids_not_in_partout"] == [12]
    assert ledger["unknown_partout_ids"] == [99]


def test_historical_attempt_cannot_satisfy_freshness_contract(tmp_path: Path):
    attempt = tmp_path / f"{f5r.LEGACY_ATTEMPT_ID}.complete"
    _write_attempt(attempt, fresh=False)

    result = f5r.inspect_attempt_freshness(attempt)

    assert result["fresh_attempt"] is False
    assert result["historical_execution_reused_as_new"] is True
    assert "case_id_is_fresh_f5r_id" in result["errors"]


def test_full_audit_is_fresh_but_makes_no_qualification_claim(tmp_path: Path):
    attempt_id = "20260919T000000Z-f5r00002"
    attempt = tmp_path / f"{attempt_id}.complete"
    _write_attempt(attempt, attempt_id=attempt_id)
    runparts_path = attempt / "RunPARTs.csv"
    partout_path = tmp_path / "PartOut.csv"
    hdf5_path = tmp_path / "fresh.h5"
    generated_xml = tmp_path / "generated.xml"
    run_log = attempt / "Run.out"
    _write_runparts(runparts_path)
    _write_partout(partout_path)
    _write_hdf5(hdf5_path)
    _write_definition(generated_xml, symbolic=False)
    run_log.write_text(
        "MapRealPos(final)=(-0.3,-0.1,-0.15)-(1.5,0.496875,1.35)\n"
        "Finished execution (code=0)\n"
    )

    report = f5r.build_audit(
        attempt_dir=attempt,
        hdf5_path=hdf5_path,
        partout_csv=partout_path,
        generated_xml=generated_xml,
        output_report=tmp_path / "audit.json",
    )

    assert report["status"] == "complete_with_findings"
    assert report["execution_policy"]["new_solver_execution"] is True
    assert report["execution_policy"]["solver_invocations_by_this_entrypoint"] == 0
    assert report["identity_reconciliation"]["status"] == "pass"
    assert report["hard_checks"]["runtime_domain_contract"] is True
    assert report["execution_policy"]["qualification_claim"] == "none; F5R confirmation audit only"
