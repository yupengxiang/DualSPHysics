"""Validate required driving assets using the native parser before GPU launch."""

import json, subprocess
import numpy as np
import xml.etree.ElementTree as ET
from scripts.l1r_continuation_evidence import LAB, OUT, write
from scripts import l1r_q2_mdbc_bridge as q2


def check_boundary_mode(record):
    modes={'-mdbc':1,'-mdbc_noslip':2,'-mdbc_freeslip':3}
    mode,_,option=record.get('solver_mode','').partition(':')
    if mode not in modes:return
    root=ET.parse(LAB/(record['generated_prefix']+'.xml')).getroot()
    parameters={n.get('key'):n.get('value') for n in root.findall('.//parameter')}
    if int(parameters.get('Boundary','1'))!=2 or int(parameters.get('SlipMode','1'))!=modes[mode]:
        raise ValueError('CLI boundary mode would override the registered XML mode')
    if option not in ('','0','1'):
        raise ValueError('unregistered no-penetration CLI option')
    cli_nopen=mode!='-mdbc' and option=='1'
    if bool(int(parameters.get('NoPenetration','0'))) != cli_nopen:
        raise ValueError('CLI no-penetration mode would override the registered XML mode')
    if 'expected_no_penetration' in record and record['expected_no_penetration'] != cli_nopen:
        raise ValueError('declared no-penetration mode differs from command')


def check_input(record):
    file = (LAB / record["generated_prefix"]).parent / "CaseSloshingAccData.csv"
    source = (
        LAB
        / "vendor/official/DualSPHysics_v5.4/examples/main/05_SloshingTank/CaseSloshingAccData.csv"
    )
    if not file.is_file() or file.stat().st_size == 0:
        raise ValueError("missing/empty acceleration input; no solver attempt launched")
    check_boundary_mode(record)
    if q2.sha256(file) != q2.sha256(source):
        if record.get('control_definition') != 'F3_CELL3_gravity_preserving_amplitude_v1':
            raise ValueError("driving input differs from declared source")
        amplitude=float(record['drive_amplitude'])
        if not np.isfinite(amplitude) or not 0 <= amplitude <= 1.1:
            raise ValueError('unregistered control amplitude')
        nominal=np.loadtxt(source,delimiter=';',comments='#')
        expected=nominal.copy()
        g=np.array([0.,0.,-9.81])
        expected[:,1:4]=g+amplitude*(nominal[:,1:4]-g)
        expected[:,4:7]=amplitude*nominal[:,4:7]
        actual=np.loadtxt(file,delimiter=';',comments='#')
        if actual.shape != expected.shape or not np.allclose(actual,expected,rtol=0,atol=1e-12):
            raise ValueError('drive is not the registered gravity-preserving transformation')
    if record.get('drive_sha256') and q2.sha256(file) != record['drive_sha256']:
        raise ValueError('driving input changed after registration')
    p = subprocess.run(
        [str(LAB / "campaigns/l1-resume/artifacts/check_acc_input"), str(file)],
        text=True,
        capture_output=True,
    )
    if p.returncode:
        raise ValueError("native acceleration reader rejects input")
    parsed = json.loads(p.stdout)
    if parsed["first_time_s"] > 0 or parsed["last_time_s"] < record["time_max_s"]:
        raise ValueError("driving data does not cover run")
    existing_path = OUT / f"{record['id']}-INPUT-PREFLIGHT.json"
    existing = json.loads(existing_path.read_text()) if existing_path.is_file() else {}
    result = {
        "asset": q2.fingerprint(file),
        "source": q2.fingerprint(source),
        "native_reader": parsed,
        "solver_attempts": 0,
        "status": "passed",
    }
    # Preserve immutable preparation bindings when a preflight is repeated
    # immediately before an authorized launch.
    for key in ("record_id", "record_sha256", "recipe_id", "revision_manifest_sha256"):
        if key in existing:
            result[key] = existing[key]
    write(record["id"] + "-INPUT-PREFLIGHT.json", result)
    return result
