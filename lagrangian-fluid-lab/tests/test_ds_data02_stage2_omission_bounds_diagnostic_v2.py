import hashlib
import json
from pathlib import Path
import sys

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import ds_data02_stage2_omission_bounds_diagnostic_v2 as diagnostic


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, text, *, binary=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if binary:
        path.write_bytes(text.encode())
    else:
        path.write_text(text)
    return path


def make_fixture(root, *, case_mismatch=False, raw_mutation=False,
                 decoder_digest_mismatch=False, scan_digest_mismatch=False,
                 time_mismatch=False, count_mismatch=False,
                 ambiguous_partout=False, missing_run_out=False,
                 missing_bottom=False):
    root = Path(root)
    scan = write(root / "scan/scientific-scan.json", json.dumps({
        "schema": "ds02.stage2.scientific-scan.v1",
        "scan_status": "SCANNED",
        "failures": [],
        "family_id": "F2",
        "physical_case_id": "TEST_CASE",
        "trajectory": str(root / "trajectory.h5"),
        "time_s": [0.0, 0.1, 0.2],
    }))
    trajectory = write(root / "trajectory.h5", "placeholder")
    scan_receipt = write(scan.parent / "execution-receipt.json", json.dumps({
        "status": "completed", "returncode": 0,
    }))
    xml_body = "" if missing_bottom else """
      <drawbox><boxfill>bottom</boxfill>
        <point x="0" y="0" z="0"/><size x="1" y="1" z="0.1"/>
      </drawbox>
    """
    xml = write(root / "prepared/TEST_CASE.xml", f"""<case>
      <casedef><geometry><definition dp="0.1">
        <pointmin x="-0.1" y="-0.1" z="-0.1"/>
        <pointmax x="1.1" y="1.1" z="1.1"/>
        <commands>{xml_body}</commands>
      </definition></geometry></casedef>
      <execution><parameters>
        <parameter key="RhopOutMin" value="700"/>
        <parameter key="RhopOutMax" value="1300"/>
        <simulationdomain><posmin x="0" y="0" z="0"/>
          <posmax x="1" y="1" z="1"/></simulationdomain>
        <particles np="11" nb="1"><fluid count="10"/></particles>
      </parameters></execution>
      <massfluid value="0.001"/>
    </case>""")
    conversion = write(root / "conversion-report.json", json.dumps({
        "conversion_status": "completed",
        "output_hdf5": str(trajectory),
        "output_sha256": "0" * 64,
    }))
    gencase = write(root / "gencase-receipt.json", json.dumps({
        "status": "completed", "returncode": 0,
    }))
    solver_root = root / "solver"
    run_out = solver_root / "solver_output/Run.out"
    if not missing_run_out:
        write(run_out, """CaseName=\"TEST_CASE\"
MapRealPos(border)=(0,0,0)-(1,1,1)
MapRealPos(final)=(0,0,0)-(1,1,1)
RhopOut=True
RhopOutMin=700
RhopOutMax=1300
""")
    solver_receipt = write(solver_root / "execution-receipt.json", json.dumps({
        "status": "completed", "returncode": 0,
        "output_root": str(solver_root),
        "request": {"physical_case_id": "TEST_CASE"},
    }))
    data_root = solver_root / "solver_output/data"
    raw = write(data_root / "PartOut_000.obi4", "raw-native")
    times = ["0;0.0;0;0;0;0", "1;0.1;1;1;0;0", "2;0.2;0;0;0;0"]
    if time_mismatch:
        times = ["0;0.0;0;0;0;0", "1;0.2;1;1;0;0", "2;0.1;0;0;0;0"]
    if count_mismatch:
        times = times[:2]
    runparts = write(solver_root / "solver_output/RunPARTs.csv",
                     "Part;TimeStep [s];NpOut;NpOutPos;NpOutRho;NpOutMov\n" +
                     "\n".join(times) + "\n")
    partout_rows = ["1.2,0.2,0.2,1,1,9,0,0,0,1000"]
    if ambiguous_partout:
        partout_rows.append("1.2,0.2,0.2,1,1,9,0,0,0,1000")
    partout = write(root / "decoded/PartOut.csv",
                    "Pos.x [m],Pos.y [m],Pos.z [m],PartOut,Motive,Idp,Vel.x [m/s],Vel.y [m/s],Vel.z [m/s],Rhop [kg/m^3],\n" +
                    "\n".join(partout_rows) + "\n")
    resume = write(root / "decoded/resume.csv", "resume\n")
    binary = write(root / "PartVTKOut_linux64", "binary", binary=True)
    decoder_inputs = [scan, scan_receipt, raw, runparts, xml, conversion,
                      solver_receipt, gencase]
    decoder_request = {
        "input_files": [str(path) for path in decoder_inputs],
        "input_sha256": {str(path): digest(path) for path in decoder_inputs},
        "command": [str(binary), "-dirdata", str(data_root),
                    "-savecsv", "{attempt_root}/PartOut.csv",
                    "-saveresume", "{attempt_root}/resume.csv",
                    "-createdirs:1", "-csvsep:1"],
    }
    decoder = {
        "status": "completed", "returncode": 0,
        "output_root": str(root / "decoded"),
        "command": [str(binary), "-dirdata", str(data_root),
                    "-savecsv", str(partout), "-saveresume", str(resume),
                    "-createdirs:1", "-csvsep:1"],
        "binary_sha256": digest(binary),
        "request": decoder_request,
        "input_hashes_at_launch": decoder_request["input_sha256"],
        "input_hashes_after_run": decoder_request["input_sha256"],
    }
    decoder_path = write(root / "decoded/execution-receipt.json", json.dumps(decoder))
    sidecar = {
        "schema": "ds02.stage2.omission-forensics.v2",
        "status": "CAUSES_RECONCILED",
        "family_id": "F2",
        "physical_case_id": "WRONG_CASE" if case_mismatch else "TEST_CASE",
        "scan": {"path": str(scan), "sha256": digest(scan)},
        "scan_completion": {"receipt": {"path": str(scan_receipt),
                                           "sha256": digest(scan_receipt)}},
        "trajectory": {"sha256": "0" * 64,
                        "conversion_report": {"path": str(conversion),
                                               "sha256": digest(conversion)}},
        "source_provenance": {
            "data_root": str(data_root),
            "generated_xml": {"path": str(xml), "sha256": digest(xml)},
            "solver_receipt": {"path": str(solver_receipt),
                                "sha256": digest(solver_receipt)},
            "gencase_receipt": {"path": str(gencase),
                                 "sha256": digest(gencase)},
            "partvtk": {"path": str(binary), "sha256": digest(binary)},
        },
        "native_decode": {
            "receipt": {"path": str(decoder_path), "sha256": digest(decoder_path)},
            "partout": {"path": str(partout), "sha256": digest(partout)},
            "runparts": {"path": str(runparts), "sha256": digest(runparts)},
            "runparts_row_count": len(times),
            "runparts_totals": {"NpOut": 1, "NpOutPos": 1,
                                 "NpOutRho": 0, "NpOutMov": 0},
        },
        "typed_identity": {"missing_fluid_count": 1,
                           "ids": [{"zone": 0, "idp": 9,
                                    "first_missing_frame": 1}]},
        "excluded_particles": [{
            "zone": 0, "idp": 9, "first_missing_frame": 1,
            "first_missing_bracket_s": [0.0, 0.1],
            "first_gap_previous_state": {"frame": 0},
            "last_known_frame": 0, "last_known_time_s": 0.0,
            "last_known_position_m": [0.2, 0.2, 0.2],
            "last_known_velocity_m_s": [0.0, 0.0, 0.0],
            "last_known_density_kg_m3": 1000.0,
            "initial_mass_kg": 0.001,
            "native_motive": "position",
        }],
    }
    sidecar_path = write(root / "sidecar.json", json.dumps(sidecar))
    if raw_mutation:
        raw.write_text("changed-native")
    if decoder_digest_mismatch:
        sidecar["native_decode"]["receipt"]["sha256"] = "0" * 64
        sidecar_path.write_text(json.dumps(sidecar))
    if scan_digest_mismatch:
        sidecar["scan"]["sha256"] = "0" * 64
        sidecar_path.write_text(json.dumps(sidecar))
    return sidecar_path


def test_positive_diagnosis_grants_only_numerical_position_credit(tmp_path):
    result = diagnostic.diagnose(make_fixture(tmp_path))
    assert result["status"] == "BOUNDS_DENSITY_DIAGNOSED"
    assert result["diagnostic"]["numerical_cause_credit_count"] == 1
    assert result["diagnostic"]["particles"][0]["diagnostic_category"] == "position_outside_map_final"
    assert result["physical_fate"] == "UNKNOWN"
    assert result["dynamical_impact"] == "NOT_ASSESSED"


@pytest.mark.parametrize("option", [
    "case_mismatch", "raw_mutation", "decoder_digest_mismatch", "scan_digest_mismatch",
    "time_mismatch", "count_mismatch", "ambiguous_partout", "missing_run_out",
    "missing_bottom",
])
def test_invalid_or_incomplete_evidence_cannot_receive_cause_credit(tmp_path, option):
    path = make_fixture(tmp_path, **{option: True})
    with pytest.raises(diagnostic.EvidenceError):
        diagnostic.diagnose(path)
