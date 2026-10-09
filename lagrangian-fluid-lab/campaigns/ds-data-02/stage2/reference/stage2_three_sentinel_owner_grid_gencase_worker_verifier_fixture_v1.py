#!/usr/bin/env python3
"""Run a real tiny subprocess chain for the nine-row owner-grid audit.

The subprocess named ``GenCase_linux64`` is a manufactured fixture, not the
production binary. It writes the small generated.xml/Fluid.vtk/Bound.vtk/BI4/
receipt shape consumed by the guarded worker. The fixture then invokes the
actual worker CLI and independent verifier CLI in separate subprocesses.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
from typing import Any

HERE = Path(__file__).resolve().parent
WORKER = HERE / "stage2_three_sentinel_owner_grid_initial_support_audit_v1.py"
VERIFIER = HERE / "stage2_three_sentinel_owner_grid_initial_support_verify_v1.py"
REQUEST_BUILDER = HERE / "stage2_three_sentinel_owner_grid_initial_support_request_v1.py"
TARGETS = ("F2-S2", "F3-S1", "F5-S1")
GRIDS = ("original", "coarse", "fine")


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino),
            "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns),
            "ctime_ns": int(value.st_ctime_ns)}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record(path: Path, *, payload_read_by_builder: bool = True,
            include_sha: bool = True) -> dict[str, Any]:
    value: dict[str, Any] = {"path": str(path.absolute()), "stat": _stat(path),
                             "payload_read_by_builder": payload_read_by_builder}
    if include_sha:
        value["sha256"] = _sha(path)
    return value


def _tiny_vtk(points: list[tuple[float, float, float]], ids: list[int]) -> bytes:
    header = b"# vtk DataFile Version 3.0\ntiny GenCase fixture\nBINARY\nDATASET POLYDATA\n"
    header += f"POINTS {len(points)} float\n".encode("ascii")
    payload = b"".join(struct.pack(">fff", *point) for point in points)
    tail = f"\nPOINT_DATA {len(points)}\nSCALARS Idp unsigned_int 1\nLOOKUP_TABLE default\n".encode("ascii")
    return header + payload + tail + b"".join(struct.pack(">I", value) for value in ids) + b"\n"


def _write_gencase_stub(path: Path) -> None:
    """Create an executable fixture with an actual subprocess boundary."""
    path.write_text(
        """#!/usr/bin/env python3
import argparse, hashlib, json, pathlib, struct

def vtk(points, ids):
    h = b'# vtk DataFile Version 3.0\\ntiny GenCase fixture\\nBINARY\\nDATASET POLYDATA\\n'
    h += ('POINTS %d float\\n' % len(points)).encode('ascii')
    p = b''.join(struct.pack('>fff', *row) for row in points)
    t = ('\\nPOINT_DATA %d\\nSCALARS Idp unsigned_int 1\\nLOOKUP_TABLE default\\n' % len(points)).encode('ascii')
    return h + p + t + b''.join(struct.pack('>I', value) for value in ids) + b'\\n'

p = argparse.ArgumentParser()
p.add_argument('candidate_def')
p.add_argument('output_root')
p.add_argument('--probe', action='store_true')
a = p.parse_args()
source = pathlib.Path(a.candidate_def).read_bytes()
out = pathlib.Path(a.output_root)
out.mkdir(parents=True, exist_ok=True)
(out / 'generated.xml').write_bytes(source)
(out / 'generated_Fluid.vtk').write_bytes(vtk([(0.25,0.25,0.25),(0.75,0.75,0.75)], [0,1]))
(out / 'generated_Bound.vtk').write_bytes(vtk([(0.25,0.25,0.25)], [2]))
bi4 = out / 'generated.bi4'
bi4.write_bytes(b'tiny official GenCase BI4 fixture')
(out / 'execution-receipt.json').write_text(json.dumps({'status':'completed','returncode':0,'producer':'manufactured-GenCase-linux64-fixture'})+'\\n')
if a.probe:
    (out / 'native-header.json').write_text(json.dumps({'schema':'ds02.stage2.native-header-probe.v1','source_path':str(bi4.absolute()),'source_sha256':hashlib.sha256(bi4.read_bytes()).hexdigest(),'massfluid':0.5,'massbound':0.5,'dp':0.1,'time_s':0.0,'role_counts':{'fluid':2,'bound':1},'finite_fields':{'position':True,'ids_unique':True}})+'\\n')
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _xml(dp: str) -> str:
    return (f'<case><casedef><definition dp="{dp}"/><mainlist>'
            '<setmkfluid mk="1"/><drawbox><point x="0" y="0" z="0"/>'
            '<size x="1" y="1" z="1"/></drawbox><setmkbound mk="2"/>'
            '</mainlist></casedef><execution><particles>'
            '<fluid begin="0" count="2" mkfluid="0" mk="1"/>'
            '<bound begin="2" count="1" mkbound="2" mk="2"/>'
            '</particles><constants><massfluid value="0.5"/></constants>'
            '</execution></case>')


def _make_fixture(root: Path) -> tuple[Path, Path]:
    source_dir = root / "source"
    source_dir.mkdir(parents=True)
    source_text = _xml("0.1")
    source_xml = source_dir / "source.xml"
    source_xml.write_text(source_text, encoding="utf-8")
    source_def = source_dir / "source_Def.xml"
    source_def.write_text(source_text, encoding="utf-8")
    source_receipt = source_dir / "source-receipt.json"
    source_receipt.write_text('{"status":"completed","returncode":0}\n', encoding="utf-8")
    stub = root / "GenCase_linux64"
    _write_gencase_stub(stub)
    products: list[dict[str, Any]] = []
    for sentinel in TARGETS:
        for grid, dp in (("original", "0.1"), ("coarse", "0.05"), ("fine", "0.025")):
            candidate = source_dir / f"{sentinel.replace('-', '_')}_{grid}_Def.xml"
            candidate.write_text(_xml(dp), encoding="utf-8")
            product_root = root / "products" / sentinel / grid
            command = [str(stub), str(candidate), str(product_root)]
            if sentinel == "F2-S2" and grid == "original":
                command.append("--probe")
            completed = subprocess.run(command, cwd=root, check=False,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if completed.returncode != 0:
                raise RuntimeError(f"tiny GenCase subprocess failed: {completed.stderr}")
            products.append({
                "sentinel_id": sentinel, "grid_label": grid,
                "generated_xml": _record(product_root / "generated.xml"),
                "gencase_receipt": _record(product_root / "execution-receipt.json"),
                "fluid_vtk": _record(product_root / "generated_Fluid.vtk", payload_read_by_builder=False, include_sha=False),
                "bound_vtk": _record(product_root / "generated_Bound.vtk", payload_read_by_builder=False, include_sha=False),
                "native_bi4": _record(product_root / "generated.bi4", payload_read_by_builder=False, include_sha=False),
            })
            probe = product_root / "native-header.json"
            if probe.exists():
                products[-1]["native_header_probe"] = _record(probe)
    owner_cases = []
    source_bindings = {"source_xml": _record(source_xml), "source_def": _record(source_def),
                       "source_receipt": _record(source_receipt)}
    for sentinel in TARGETS:
        source_requests = []
        for grid, dp in (("original", "0.1"), ("coarse", "0.05"), ("fine", "0.025")):
            candidate = source_dir / f"{sentinel.replace('-', '_')}_{grid}_Def.xml"
            source_requests.append({"grid_label": grid,
                                    "source_inputs": {"candidate_def": _record(candidate),
                                                       "motion_or_forcing": None}})
        owner_cases.append({"sentinel_id": sentinel, "family_id": sentinel[:2],
                            "physical_case_id": f"fixture-{sentinel}",
                            "source_bindings": source_bindings,
                            "owner_spec": {"source_region_predicate": {"status": "UNKNOWN_CONTINUOUS_OWNER"},
                                           "owner_mass_kg": None},
                            "source_requests": source_requests})
    owner = {"schema": "ds02.stage2.three-sentinel.owner-grid-source-audit.v3",
             "status": "COMPLETE_SOURCE_OWNER_GRID_AUDIT_V3_NO_SCIENTIFIC_Q", "cases": owner_cases}
    owner_path = root / "owner-grid-source-audit-v3.json"
    owner_path.write_text(json.dumps(owner, indent=2), encoding="utf-8")
    product_path = root / "nine-product-map.json"
    product_path.write_text(json.dumps({"products": products}, indent=2), encoding="utf-8")
    manifest_dir = root / "prepared"
    manifest_dir.mkdir()
    completed = subprocess.run(
        [sys.executable, str(REQUEST_BUILDER), "--owner-report", str(owner_path),
         "--product-map", str(product_path), "--output-dir", str(manifest_dir)],
        cwd=root, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"request builder subprocess failed: {completed.stdout}\n{completed.stderr}")
    return (manifest_dir / "owner-grid-initial-support-manifest-v1.json",
            manifest_dir / "owner-grid-initial-support-request-v1.json")


def run_fixture() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="three-sentinel-gencase-chain-") as directory:
        root = Path(directory)
        manifest, request = _make_fixture(root)
        report = root / "attempt" / "report.json"
        worker = subprocess.run(
            [sys.executable, str(WORKER), "--run", "--manifest", str(manifest),
             "--attempt-root", str(root / "attempt"), "--output", str(report)],
            cwd=root, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        if worker.returncode != 0:
            raise RuntimeError(f"worker subprocess failed: {worker.stdout}\n{worker.stderr}")
        verification_output = root / "attempt" / "verification.json"
        verifier = subprocess.run(
            [sys.executable, str(VERIFIER), "--verify", "--manifest", str(manifest),
             "--output", str(report), "--verification-output", str(verification_output)],
            cwd=root, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        if verifier.returncode != 0:
            raise RuntimeError(f"verifier subprocess failed: {verifier.stdout}\n{verifier.stderr}")
        result = json.loads(verification_output.read_text(encoding="utf-8"))
        if result.get("status") != "VERIFIED_THREE_SENTINEL_OWNER_GRID_INITIAL_SUPPORT_V1":
            raise RuntimeError("verifier did not produce independent success status")
        tampered = root / "attempt" / "tampered-report.json"
        report_value = json.loads(report.read_text(encoding="utf-8"))
        report_value["scientific_scope"]["scientific_credit"] = 1
        tampered.write_text(json.dumps(report_value), encoding="utf-8")
        negative = subprocess.run(
            [sys.executable, str(VERIFIER), "--verify", "--manifest", str(manifest), "--output", str(tampered)],
            cwd=root, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        if negative.returncode == 0:
            raise RuntimeError("verifier accepted a scientific-credit mutation")
        return {"status": "PASS_THREE_SENTINEL_GENCASE_SUBPROCESS_WORKER_VERIFIER_CHAIN",
                "gencase_subprocess": True, "worker_subprocess": True,
                "verifier_subprocess": True, "case_count": result.get("case_counts"),
                "negative_report_mutation_rejected": True, "production_payload_read": False,
                "solver_launch": False, "request": str(request)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if not args.self_test:
        parser.error("only --self-test is supported; this fixture never consumes production inputs")
    try:
        result = run_fixture()
    except Exception as exc:
        print(f"FAILED_THREE_SENTINEL_GENCASE_SUBPROCESS_WORKER_VERIFIER_CHAIN: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
