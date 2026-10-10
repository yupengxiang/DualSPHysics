#!/usr/bin/env python3
"""Exercise the complete tiny ABI chain used by the nine-row owner study.

The production path is split into three guarded parents:

``GenCase producer -> native-header probe -> initial-support/calibration``.

This file supplies a manufactured, six-byte-scale fixture for that path.  It
invokes the primary ``runtime_v8`` command through the literal project venv,
reads the resulting ``execution-receipt.v1`` files, invokes the frozen
native-header probe through its real CLI, and invokes the frozen calibration
worker through three more real runtime-v8 audit parents.  The fixture producer
is intentionally an ``audit`` task: it is not GenCase and grants no scientific
credit.  Production GenCase rows must use ``cpu_task_kind=gencase`` and the
ROOT345 product-map/receipt bridge described in the emitted contract.

The source-only builder in this module records the exact manifest schemas,
CLI argv, literal interpreter, transitive source closure, and parent resource
requirements.  It never opens a production BI4/VTK/Part/HDF5 file and never
starts GenCase, a solver, a GPU lease, or a shared Stage2 ledger.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[5]
PRIMARY_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
if not (PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py").is_file():
    PRIMARY_REPO = REPO
LAB = REPO / "lagrangian-fluid-lab"
VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PYVENV = VENV.parent.parent / "pyvenv.cfg"
RUNTIME_V8 = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
RUNTIME_V6 = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v6.py"
RUNTIME_V2 = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
RUNTIME_BASE = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime.py"
HEADER_PROBE = HERE / "stage2_three_sentinel_owner_grid_native_header_probe_v2.py"
CAL_WORKER = HERE / "stage2_three_sentinel_calibration_worker_v1.py"
CAL_VERIFY = HERE / "stage2_three_sentinel_calibration_verify_v1.py"
FROZEN_SUPPORT = HERE / "stage2_three_sentinel_owner_grid_initial_support_audit_v1.py"
SUPPORT_VERIFY_V1 = HERE / "stage2_three_sentinel_owner_grid_initial_support_verify_v1.py"
SUPPORT_VERIFY_V2 = HERE / "stage2_three_sentinel_owner_grid_initial_support_verify_v2.py"
SUPPORT_VERIFY_V3 = HERE / "stage2_three_sentinel_owner_grid_initial_support_verify_v3.py"
GEOMETRY = HERE / "stage2_four_sentinel_gencase_geometry_support_audit_v1.py"
GENCASE_REQUEST_V1 = HERE / "stage2_three_sentinel_owner_grid_gencase_producer_request_v1.py"
GENCASE_REQUEST_V2 = HERE / "stage2_three_sentinel_owner_grid_gencase_producer_request_v2.py"
EXTERNAL_CANARY = HERE / "stage2_f3_s1_external_solver_canary_v1.py"
EXTERNAL_MATERIALIZER = HERE / "stage2_f3_s1_external_solver_canary_materialize.py"
EXTERNAL_VERIFIER = HERE / "stage2_f3_s1_external_solver_canary_verify_v1.py"
NATIVE_OBSERVER = HERE / "stage2_native_physical_observer_v2.py"
NATIVE_ENFORCER = HERE / "stage2_native_physical_observer_enforcer_v2.py"
SCALES = HERE / "stage2_three_sentinel_calibration_scales_v2.json"
SCHEMA = "ds02.stage2.three-sentinel-owner-grid-abi-chain.v1"
REQUEST_SCHEMA = "ds02.request.v1"
RECEIPT_SCHEMA = "ds02.execution-receipt.v1"
HEADER_MANIFEST_SCHEMA = "ds02.stage2.three-sentinel-owner-grid-native-header-probe-manifest.v2"
CAL_MANIFEST_SCHEMA = "ds02.stage2.three-sentinel-calibration-manifest.v1"
JSON_CAP = 10 * 1024 * 1024
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scientific_credit": 0}
TARGETS = ("F2-S2", "F3-S1", "F5-S1")
GRIDS = ("original", "coarse", "fine")


class ChainFailure(RuntimeError):
    pass


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ChainFailure(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _abs(path: Path | str) -> Path:
    return Path(path).expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino),
            "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns),
            "ctime_ns": int(value.st_ctime_ns)}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _record(path: Path, label: str, *, read: bool = True) -> dict[str, Any]:
    path = _abs(path)
    if path.is_symlink() or not path.is_file():
        raise ChainFailure(f"{label} is not a regular file: {path}")
    before = _stat(path)
    if read and before["bytes"] > JSON_CAP:
        raise ChainFailure(f"{label} exceeds the 10 MiB bounded source cap: {path}")
    raw = path.read_bytes() if read else b""
    after = _stat(path)
    if before != after or (read and len(raw) != before["bytes"]):
        raise ChainFailure(f"{label} changed during bounded source read: {path}")
    return {"path": str(path), "sha256": _sha(raw) if read else None,
            "stat_before": before, "stat_after": after, "bytes": before["bytes"],
            "read_scope": "bounded_source_metadata" if read else "stat_only_deferred",
            "payload_read_by_builder": bool(read), "label": label}


def _json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    path = _abs(path)
    rec = _record(path, label, read=True)
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ChainFailure(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ChainFailure(f"{label} must be a JSON object")
    return value, rec, raw


def _write_once(path: Path, value: Any) -> None:
    path = _abs(path)
    if path.exists() or path.is_symlink():
        raise ChainFailure(f"refusing to overwrite immutable chain artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _tiny_vtk(points: list[tuple[float, float, float]], ids: list[int]) -> bytes:
    import struct
    value = b"# vtk DataFile Version 3.0\ntiny ABI fixture\nBINARY\nDATASET POLYDATA\n"
    value += f"POINTS {len(points)} float\n".encode("ascii")
    value += b"".join(struct.pack(">fff", *point) for point in points)
    value += f"\nPOINT_DATA {len(points)}\nSCALARS Idp unsigned_int 1\nLOOKUP_TABLE default\n".encode("ascii")
    value += b"".join(struct.pack(">I", item) for item in ids) + b"\n"
    return value


def _fixture_xml(dp: str = "0.05") -> str:
    return ("<case><casedef><definition dp=\"" + dp + "\"/><mainlist>"
            "<setmkfluid mk=\"1\"/><drawbox><point x=\"0\" y=\"0\" z=\"0\"/>"
            "<size x=\"1\" y=\"1\" z=\"1\"/></drawbox><setmkbound mk=\"2\"/>"
            "</mainlist></casedef><execution><particles>"
            "<fluid begin=\"0\" count=\"2\" mkfluid=\"0\" mk=\"1\"/>"
            "<bound begin=\"2\" count=\"1\" mkbound=\"2\" mk=\"2\"/>"
            "</particles><constants><massfluid value=\"0.5\"/></constants>"
            "</execution></case>")


def _write_tiny_producer(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
from pathlib import Path
import struct
import sys

out = Path(sys.argv[1])
case = sys.argv[2]
dp = sys.argv[3]
out.mkdir(parents=True, exist_ok=True)
xml = f'''<case><casedef><definition dp="{dp}"/><mainlist>
<setmkfluid mk="1"/><drawbox><point x="0" y="0" z="0"/>
<size x="1" y="1" z="1"/></drawbox><setmkbound mk="2"/>
</mainlist></casedef><execution><particles>
<fluid begin="0" count="2" mkfluid="0" mk="1"/>
<bound begin="2" count="1" mkbound="2" mk="2"/>
</particles><constants><massfluid value="0.5"/></constants>
</execution></case>'''
(out / 'generated.xml').write_text(xml, encoding='utf-8')
header = b'# vtk DataFile Version 3.0\\ntiny ABI fixture\\nBINARY\\nDATASET POLYDATA\\n'
def vtk(points, ids):
    data = header + f'POINTS {len(points)} float\\n'.encode('ascii')
    data += b''.join(struct.pack('>fff', *p) for p in points)
    data += f'\\nPOINT_DATA {len(points)}\\nSCALARS Idp unsigned_int 1\\nLOOKUP_TABLE default\\n'.encode('ascii')
    return data + b''.join(struct.pack('>I', i) for i in ids) + b'\\n'
(out / 'generated_Fluid.vtk').write_bytes(vtk([(0.25,0.25,0.25),(0.75,0.75,0.75)], [0, 1]))
(out / 'generated_Bound.vtk').write_bytes(vtk([(0.25,0.25,0.25)], [2]))
(out / 'generated.bi4').write_bytes(('tiny-bi4-' + case).encode())
print('Total particles: 3\\nFluid....: 2\\nData2D=0')
""",
        encoding="utf-8")
    path.chmod(0o755)


def _write_decoder(path: Path) -> None:
    path.write_text(
        """#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
from pathlib import Path
import sys
native = Path(sys.argv[1])
prefix = Path(sys.argv[2])
raw = native.read_bytes()
if not raw.startswith(b'tiny-bi4-'):
    raise SystemExit(17)
prefix.parent.mkdir(parents=True, exist_ok=True)
prefix.with_suffix('.xml').write_text(
    "<data><item name='Header'><item name='MassFluid' value='0.5'/>"
    "<item name='MassBound' value='0.5'/><item name='Dp' value='0.05'/>"
    "<item name='Nfluid' value='2'/><item name='Nbound' value='1'/>"
    "</item></data>", encoding='utf-8')
""",
        encoding="utf-8")
    path.chmod(0o755)


def _fixture_ledger(data_root: Path) -> None:
    (data_root / "runtime").mkdir(parents=True, exist_ok=True)
    from datetime import datetime, timedelta, timezone
    deadline = datetime.now(timezone.utc) + timedelta(hours=1)
    _write_once(data_root / "runtime/resource-ledger.json", {
        "schema": "ds02.runtime.resource-ledger.v1",
        "campaign_id": "tiny-owner-grid-abi-chain-v1",
        "deadline_utc": deadline.isoformat(),
        "limits": {"gpu_seconds": 0.0, "cpu_core_seconds": 5000.0,
                    "new_storage_bytes": 512 * 1024 * 1024,
                    "qualification_attempts": 0, "production_attempts": 0,
                    "storage_policy": "external", "home_min_free_bytes": 0},
        "charges": [], "reservations": [], "attempts": [],
    })


def _runtime_request(root: Path, *, family: str, case: str, attempt: str,
                     command: list[str], input_files: list[Path], output_root: Path,
                     manifest: Path | None = None, scales: Path | None = None,
                     deferred: list[dict[str, Any]] | None = None,
                     sentinel_id: str | None = None,
                     cpu_task_kind: str = "audit") -> Path:
    paths = [str(_abs(item)) for item in input_files]
    request: dict[str, Any] = {
        "schema": REQUEST_SCHEMA, "status": "READY_FOR_PARENT_GUARD",
        "request_variant": "three-sentinel-owner-grid-abi-chain-v1",
        "family_id": family, "case_id": case, "attempt_id": attempt,
        "kind": "cpu", "cpu_task_kind": cpu_task_kind, "command": command,
        "cwd": str(_abs(root)), "worktree_root": str(PRIMARY_REPO),
        "max_wall_seconds": 60.0, "cpu_threads": 1,
        "estimated_storage_bytes": 8 * 1024 * 1024,
        "output_root": str(_abs(output_root)), "input_files": paths,
        "input_sha256": {item: _sha(Path(item).read_bytes()) for item in paths},
        "execution_allowed": True, "launch_disabled": False,
        "gencase_launch": False, "solver_launch": False,
        "source_only": False, "production_eligible": False,
        "scientific_qualification": dict(UNKNOWN), "fixture_only": True,
        "deferred_input_records": list(deferred or []),
    }
    if sentinel_id is not None:
        request["sentinel_id"] = sentinel_id
    if manifest is not None:
        request["manifest"] = _record(manifest, "chain manifest")
    if scales is not None:
        request["calibration_scales"] = _record(scales, "calibration scales")
    path = root / "requests" / f"{case}-{attempt}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_once(path, request)
    return path


def _run_runtime(request_path: Path, data_root: Path) -> tuple[dict[str, Any], Path, str]:
    command = [str(VENV), str(RUNTIME_V8), "run", "--request", str(_abs(request_path)),
               "--data-root", str(_abs(data_root))]
    process = subprocess.run(command, cwd=str(PRIMARY_REPO), capture_output=True,
                             text=True, timeout=90, check=False)
    if process.returncode != 0:
        raise ChainFailure(f"runtime-v8 failed rc={process.returncode}: {process.stdout[-1000:]} {process.stderr[-1000:]}")
    request_doc, _, request_raw = _json(request_path, "runtime request")
    output = data_root / "families" / request_doc["family_id"] / request_doc["case_id"] / request_doc["attempt_id"]
    receipt_path = output / "execution-receipt.json"
    receipt, _, _ = _json(receipt_path, "runtime execution receipt")
    if receipt.get("schema") != RECEIPT_SCHEMA or receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ChainFailure(f"runtime receipt is not completed: {receipt.get('status')} rc={receipt.get('returncode')}")
    if receipt.get("request") != request_doc or receipt.get("request_sha256") != _sha(request_raw):
        raise ChainFailure("runtime receipt does not bind exact request file bytes")
    if receipt.get("input_hashes_at_launch") != receipt.get("input_hashes_after_run"):
        raise ChainFailure("runtime static input hashes changed")
    if request_doc.get("cpu_task_kind") == "gencase":
        stdout_path = output / "stdout.log"
        stdout = stdout_path.read_text(encoding="utf-8", errors="replace")
        if len(stdout.encode("utf-8")) > 64 * 1024:
            raise ChainFailure("tiny gencase stdout exceeded bounded parse cap")
        if not re.search(r"Total particles:\s*3", stdout) or not re.search(r"Fluid\.*:\s*2", stdout) or "Data2D=0" not in stdout:
            raise ChainFailure("tiny gencase output did not preserve particle/dimension evidence")
    return receipt, receipt_path, _sha(request_raw)


def _producer_rows(root: Path, data_root: Path, producer: Path, decoder: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sid in TARGETS:
        family = sid[:2]
        for grid in GRIDS:
            safe = f"{sid.replace('-', '_')}_{grid}"
            case = f"tiny_{safe}"
            attempt = f"attempt_{safe}"
            output = data_root / "families" / family / case / attempt
            dp = {"original": "0.05", "coarse": "0.025", "fine": "0.0125"}[grid]
            input_files = [RUNTIME_V8, RUNTIME_V6, RUNTIME_V2, RUNTIME_BASE,
                           producer, decoder, HERE / Path(__file__).name]
            request = _runtime_request(root, family=family, case=case, attempt=attempt,
                                       command=[str(VENV), str(producer), "{attempt_root}", case, dp],
                                       input_files=input_files, output_root=output,
                                       cpu_task_kind="gencase")
            receipt, receipt_path, request_sha = _run_runtime(request, data_root)
            role_names = {"generated_xml": "generated.xml", "fluid_vtk": "generated_Fluid.vtk",
                          "bound_vtk": "generated_Bound.vtk", "native_bi4": "generated.bi4",
                          "gencase_receipt": "execution-receipt.json"}
            products = {role: _record(output / name, f"{safe} {role}", read=True)
                        for role, name in role_names.items()}
            row = {"row_key": f"{sid}:{grid}", "sentinel_id": sid, "grid_label": grid,
                   "family_id": family, "physical_case_id": f"tiny-{safe}",
                   "producer_request": _record(request, f"{safe} producer request"),
                   "gencase_receipt": _record(receipt_path, f"{safe} runtime receipt"),
                   "products": products, "decoder": _record(decoder, "fixture decoder"),
                   "request_sha256": request_sha, "receipt": receipt,
                   "status": "COMPLETED_FIXTURE_ONLY", "scientific_qualification": dict(UNKNOWN)}
            rows.append(row)
    return rows


def _header_manifest(root: Path, rows: list[dict[str, Any]]) -> Path:
    cases = []
    for row in rows:
        cases.append({"row_key": row["row_key"], "sentinel_id": row["sentinel_id"],
                      "grid_label": row["grid_label"], "family_id": row["family_id"],
                      "gencase_receipt": row["gencase_receipt"],
                      "producer_request": row["producer_request"],
                      "native_bi4": row["products"]["native_bi4"], "decoder": row["decoder"]})
    path = root / "header-manifest.json"
    _write_once(path, {"schema": HEADER_MANIFEST_SCHEMA,
                       "status": "READY_FOR_PARENT_GUARDED_NATIVE_HEADER_PROBE",
                       "cases": cases, "scientific_qualification": dict(UNKNOWN),
                       "fixture_only": True})
    return path


def _run_header_probe(root: Path, manifest: Path) -> tuple[dict[str, Any], Path]:
    output = root / "header-probe.json"
    attempt = root / "header-attempt"
    command = [str(VENV), str(HEADER_PROBE), "--run", "--manifest", str(manifest),
               "--attempt-root", str(attempt), "--output", str(output)]
    process = subprocess.run(command, cwd=str(PRIMARY_REPO), capture_output=True,
                             text=True, timeout=90, check=False)
    if process.returncode != 0 or not output.is_file():
        raise ChainFailure(f"native-header CLI failed rc={process.returncode}: {process.stdout[-1000:]} {process.stderr[-1000:]}")
    value, _, _ = _json(output, "native-header report")
    if value.get("schema") != "ds02.stage2.native-header-probe.v2" or len(value.get("cases", [])) != 9:
        raise ChainFailure("native-header report did not contain nine exact cases")
    if not all(case.get("scientific_qualification", {}).get("QI") == "UNKNOWN" for case in value["cases"]):
        raise ChainFailure("native-header fixture promoted scientific qualification")
    return value, output


def _sidecars(root: Path, rows: list[dict[str, Any]], header: dict[str, Any]) -> dict[str, Path]:
    by_key = {str(row.get("row_key")): row for row in header.get("cases", [])}
    result: dict[str, Path] = {}
    for row in rows:
        key = row["row_key"]
        source = by_key[key]
        sidecar = {"schema": "ds02.stage2.native-header-probe.v1",
                   "status": source.get("status"), "source_path": source.get("source_path"),
                   "source_sha256": source.get("source_sha256"),
                   "massfluid": source.get("massfluid"), "massbound": source.get("massbound"),
                   "dp": source.get("dp"), "time_s": source.get("time_s", 0.0),
                   "role_counts": source.get("role_counts", {}),
                   "finite_fields": source.get("finite_fields", {}),
                   "source_xml_mass_is_not_native": True,
                   "fixture_only": True, "scientific_qualification": dict(UNKNOWN)}
        path = root / "header-sidecars" / (key.replace(":", "_") + ".json")
        _write_once(path, sidecar)
        result[key] = path
    return result


def _calibration_manifest(root: Path, sid: str, rows: list[dict[str, Any]], sidecars: dict[str, Path], scales: Path) -> Path:
    selected = []
    for row in rows:
        if row["sentinel_id"] != sid:
            continue
        key = row["row_key"]
        source_xml = root / "sources" / f"{sid.replace('-', '_')}_source.xml"
        source_def = root / "sources" / f"{sid.replace('-', '_')}_source_Def.xml"
        candidate = root / "sources" / f"{sid.replace('-', '_')}_{row['grid_label']}_Def.xml"
        source_xml_record = _record(source_xml, f"{key} source XML")
        source_def_record = _record(source_def, f"{key} source Def")
        candidate_record = _record(candidate, f"{key} candidate Def")
        selected.append({"row_key": key, "sentinel_id": sid, "grid_label": row["grid_label"],
                         "family_id": row["family_id"], "physical_case_id": row["physical_case_id"],
                         "source_xml": source_xml_record, "source_def": source_def_record,
                         "candidate_def": candidate_record,
                         "generated_xml": row["products"]["generated_xml"],
                         "gencase_receipt": row["gencase_receipt"],
                         "fluid_vtk": {**row["products"]["fluid_vtk"], "payload_read_by_builder": False},
                         "bound_vtk": {**row["products"]["bound_vtk"], "payload_read_by_builder": False},
                         "native_bi4": {**row["products"]["native_bi4"], "payload_read_by_builder": False},
                         "native_header_probe": _record(sidecars[key], f"{key} native header sidecar"),
                         "owner_predicate": {"status": "UNKNOWN_CONTINUOUS_OWNER",
                                             "mass_rescale": False,
                                             "predicate": "manufactured ABI fixture only"}})
    path = root / "calibration-manifests" / f"{sid.replace('-', '_')}.json"
    _write_once(path, {"schema": CAL_MANIFEST_SCHEMA,
                       "status": "READY_FOR_PARENT_GUARDED_THREE_SENTINEL_CALIBRATION",
                       "sentinel_id": sid, "cases": selected,
                       "calibration_scales": _record(scales, "calibration scales"),
                       "scientific_scope": {"neighbor_grid_truth": False, "interpolation": False,
                                            "scientific_credit": 0}, "fixture_only": True})
    return path


def _calibration_request(root: Path, sid: str, manifest: Path, scales: Path,
                         rows: list[dict[str, Any]], sidecars: dict[str, Path],
                         data_root: Path) -> Path:
    selected = [row for row in rows if row["sentinel_id"] == sid]
    static = [RUNTIME_V8, RUNTIME_V6, RUNTIME_V2, RUNTIME_BASE, CAL_WORKER, CAL_VERIFY,
              FROZEN_SUPPORT, GEOMETRY, SCALES, HERE / Path(__file__).name, manifest]
    static += [root / "sources" / f"{sid.replace('-', '_')}_source.xml",
               root / "sources" / f"{sid.replace('-', '_')}_source_Def.xml"]
    static += [root / "sources" / f"{sid.replace('-', '_')}_{grid}_Def.xml" for grid in GRIDS]
    static += [sidecars[row["row_key"]] for row in selected]
    static = list(dict.fromkeys(_abs(item) for item in static))
    deferred = []
    for row in selected:
        for role in ("generated_xml", "fluid_vtk", "bound_vtk", "native_bi4"):
            rec = row["products"][role]
            deferred.append({"row_key": row["row_key"], "role": role, "path": rec["path"],
                             "sha256": rec["sha256"], "stat": rec["stat_after"],
                             "hash_status": "PARENT_AFTER_RESERVATION_REQUIRED",
                             "payload_read_by_builder": False})
    output = data_root / "families" / sid[:2] / f"tiny_calibration_{sid.replace('-', '_')}" / "attempt"
    command = [str(VENV), str(CAL_WORKER), "--run", "--manifest", str(manifest),
               "--attempt-root", "{attempt_root}", "--output", "{attempt_root}/calibration-report.json"]
    return _runtime_request(root, family=sid[:2], case=f"tiny_calibration_{sid.replace('-', '_')}",
                            attempt="attempt", command=command, input_files=static,
                            output_root=output, manifest=manifest, scales=scales,
                            deferred=deferred, sentinel_id=sid)


def _run_calibration(root: Path, sid: str, request: Path, data_root: Path, manifest: Path) -> dict[str, Any]:
    receipt, receipt_path, request_sha = _run_runtime(request, data_root)
    report = Path(receipt["output_root"]) / "calibration-report.json"
    command = [str(VENV), str(CAL_VERIFY), "--verify", "--manifest", str(manifest),
               "--request", str(request), "--receipt", str(receipt_path), "--report", str(report)]
    process = subprocess.run(command, cwd=str(PRIMARY_REPO), capture_output=True, text=True, timeout=90, check=False)
    if process.returncode != 0:
        raise ChainFailure(f"calibration verifier failed for {sid}: {process.stdout[-1000:]} {process.stderr[-1000:]}")
    value = json.loads(process.stdout) if process.stdout.strip().startswith("{") else {
        "status": "VERIFIED_CALIBRATION_DIAGNOSTIC_NO_Q"}
    return {"sentinel_id": sid, "request": str(request), "receipt": str(receipt_path),
            "receipt_request_sha256": request_sha, "report": str(report),
            "verifier_status": value.get("status"), "scientific_qualification": dict(UNKNOWN)}


def _prepare_sources(root: Path) -> Path:
    sources = root / "sources"
    sources.mkdir(parents=True, exist_ok=True)
    source = _fixture_xml("0.05")
    (sources / "F2_S2_source.xml").write_text(source, encoding="utf-8")
    (sources / "F3_S1_source.xml").write_text(source, encoding="utf-8")
    (sources / "F5_S1_source.xml").write_text(source, encoding="utf-8")
    for sid in TARGETS:
        base = (sources / f"{sid.replace('-', '_')}_source.xml").read_text()
        (sources / f"{sid.replace('-', '_')}_source_Def.xml").write_text(base, encoding="utf-8")
        for grid, dp in (("original", "0.05"), ("coarse", "0.025"), ("fine", "0.0125")):
            (sources / f"{sid.replace('-', '_')}_{grid}_Def.xml").write_text(_fixture_xml(dp), encoding="utf-8")
    scales = root / "calibration-scales-v2.json"
    shutil.copyfile(SCALES, scales)
    return scales


def build_source_contract(output: Path, *, product_map: Path | None = None,
                          initial_manifest: Path | None = None) -> dict[str, Any]:
    """Emit a source-hashed, launch-disabled ABI contract for parent review.

    ``product_map`` and ``initial_manifest`` are metadata only.  Their product
    paths are recorded as deferred parent inputs; this builder never reads the
    referenced binary products.
    """
    source_files = [RUNTIME_V8, RUNTIME_V6, RUNTIME_V2, RUNTIME_BASE, HEADER_PROBE,
                    SUPPORT_VERIFY_V3, SUPPORT_VERIFY_V2, SUPPORT_VERIFY_V1,
                    CAL_WORKER, CAL_VERIFY, FROZEN_SUPPORT, GEOMETRY, GENCASE_REQUEST_V1,
                    GENCASE_REQUEST_V2, EXTERNAL_CANARY, EXTERNAL_MATERIALIZER,
                    EXTERNAL_VERIFIER, NATIVE_OBSERVER, NATIVE_ENFORCER, SCALES,
                    HERE / Path(__file__).name]
    closure = [_record(path, f"ABI source {path.name}") for path in source_files]
    if not VENV.is_file():
        raise ChainFailure(f"literal venv interpreter missing: {VENV}")
    if not PYVENV.is_file():
        raise ChainFailure(f"pyvenv.cfg missing: {PYVENV}")
    closure.append(_record(PYVENV, "literal venv pyvenv.cfg"))
    optional = {}
    for label, path in (("ROOT345 product map", product_map), ("initial-support manifest", initial_manifest)):
        if path is not None:
            optional[label] = _record(path, label)
    contract = {
        "schema": SCHEMA, "status": "SOURCE_PREPARED_NO_PRODUCTION_CREDIT",
        "source_closure": closure, "optional_metadata": optional,
        "literal_venv": {"argv0": str(VENV), "pyvenv_cfg": _record(PYVENV, "pyvenv.cfg"),
                          "resolved_interpreter_stat_only": _record(VENV.resolve(), "resolved literal interpreter", read=False)},
        "runtime_abi": {
            "request_schema": REQUEST_SCHEMA, "receipt_schema": RECEIPT_SCHEMA,
            "family_ids": ["infra", "F1", "F2", "F3", "F4", "F5", "F6", "F7"],
            "audit_cpu_task_kind": "audit", "production_gencase_cpu_task_kind": "gencase",
            "fixture_gencase_task_kind": "gencase",
            "fixture_gencase_is_not_official_binary": True,
            "runtime_cli": [str(VENV), str(RUNTIME_V8), "run", "--request", "<request.json>", "--data-root", "<data-root>", "--parent-pid", "<optional-parent-pid>"],
            "request_sha256_basis": "exact_request_file_bytes",
            "reservation_before_input_content_hash": True,
            "static_input_posthash_required": True,
        },
        "gencase_producer_abi": {
            "source_request_builder": _record(GENCASE_REQUEST_V2, "GenCase producer request builder"),
            "manifest_schema": "ds02.stage2.three-sentinel.owner-grid-gencase-producer-manifest.v2",
            "request_schema": REQUEST_SCHEMA,
            "production_cpu_task_kind": "gencase",
            "official_command": ["<GenCase_linux64>", "<candidate_Def_stem_without_.xml>", "{attempt_root}/generated", "-save:all", "-threads:1"],
            "candidate_stem_rule": "candidate *_Def.xml -> path.with_suffix(''), preserve _Def",
            "products": ["generated.xml", "generated_Fluid.vtk", "generated_Bound.vtk", "generated.bi4", "execution-receipt.json"],
            "receipt_gate": {"schema": RECEIPT_SCHEMA, "status": "completed", "returncode": 0,
                             "request_sha256": "raw producer request file bytes",
                             "input_hashes_at_launch_after_run": "equal"},
            "fixture_chain_note": "V1 ABI fixture uses a Python producer with gencase task kind; it is not official GenCase and has zero production credit",
        },
        "native_header_worker": {
            "manifest_schema": HEADER_MANIFEST_SCHEMA,
            "cli": [str(VENV), str(HEADER_PROBE), "--run", "--manifest", "<manifest>", "--attempt-root", "<attempt-root>", "--output", "<output>"],
            "xml_mass_fallback": False, "source_mass_basis": "decoder-produced-header-only",
            "payload_scope": "parent-guarded-BI4-only", "scientific_qualification": dict(UNKNOWN),
        },
        "initial_support_calibration": {
            "manifest_schema": CAL_MANIFEST_SCHEMA,
            "worker_cli": [str(VENV), str(CAL_WORKER), "--run", "--manifest", "<manifest>", "--attempt-root", "{attempt_root}", "--output", "{attempt_root}/calibration-report.json"],
            "verifier_cli": [str(VENV), str(CAL_VERIFY), "--verify", "--manifest", "<manifest>", "--request", "<request>", "--receipt", "<receipt>", "--report", "<report>"],
            "payloads": "deferred;worker guarded pre/decode/post",
            "spatial_truth": False, "interpolation": False, "scientific_qualification": dict(UNKNOWN),
        },
        "f3_s1_external_v5_parent_inputs": {
            "request_status": "READY_FOR_PARENT_GUARD",
            "command_entrypoint": str(EXTERNAL_MATERIALIZER),
            "builder_source": _record(EXTERNAL_CANARY, "F3-S1 external-v5 builder"),
            "materializer_source": _record(EXTERNAL_MATERIALIZER, "F3-S1 external-v5 materializer"),
            "verifier_source": _record(EXTERNAL_VERIFIER, "F3-S1 external-v5 verifier"),
            "observer_source": _record(NATIVE_OBSERVER, "native observer implementation"),
            "observer_enforcer_source": _record(NATIVE_ENFORCER, "native observer enforcer"),
            "materializer_cli": ["--solver", "<DualSPHysics5.4_linux64>", "--output-root", "<attempt-root>", "--generated-xml", "<generated.xml>", "--generated-bi4", "<generated.bi4>", "--forcing-csv", "<forcing.csv>", "--expected-generated-xml-sha", "<sha>", "--expected-generated-bi4-sha", "<sha>", "--expected-forcing-sha", "<sha>", "--tmax", "8.35", "--tout", "0.01", "--mdbc-noslip", "1"],
            "solver_argv_after_materialization": ["<solver>", "-gpu:0", "-mdbc_noslip:1", "<input_root>/generated", "<attempt-root>/solver_output", "-tmax:8.35", "-tout:0.01"],
            "parent_required": {"gpu_uuid": "PARENT_AFTER_INVENTORY", "gpu_seconds": ">0", "cpu_seconds": ">0", "max_memory_bytes": ">=4GiB", "cancellation": True, "fee_close": True, "source_pre_post_hash": True},
            "adapter_authority": {"bi4_dump_is_project_adapter": True, "official_jbinarydata_source": True, "official_tool_claim": False},
            "scientific_qualification": dict(UNKNOWN),
        },
        "production_credit": 0, "payload_read_by_builder": False,
    }
    _write_once(output, contract)
    return contract


def self_test() -> None:
    if not all(path.is_file() for path in (RUNTIME_V8, RUNTIME_V6, RUNTIME_V2, RUNTIME_BASE)):
        raise ChainFailure("primary runtime-v8/v6/v2/base source closure is unavailable")
    with tempfile.TemporaryDirectory(prefix="three-sentinel-abi-chain-v1-") as td:
        root = Path(td)
        data_root = root / "runtime-data"
        _fixture_ledger(data_root)
        producer = root / "tiny-gencase-fixture.py"
        _write_tiny_producer(producer)
        decoder = root / "bi4_dump_fixture"
        _write_decoder(decoder)
        scales = _prepare_sources(root)
        rows = _producer_rows(root, data_root, producer, decoder)
        if len(rows) != 9:
            raise ChainFailure("fixture producer did not make nine rows")
        header_manifest = _header_manifest(root, rows)
        header, header_path = _run_header_probe(root, header_manifest)
        sidecars = _sidecars(root, rows, header)
        calibration_results = []
        for sid in TARGETS:
            manifest = _calibration_manifest(root, sid, rows, sidecars, scales)
            request = _calibration_request(root, sid, manifest, scales, rows, sidecars, data_root)
            calibration_results.append(_run_calibration(root, sid, request, data_root, manifest))
        contract_path = root / "abi-chain-contract.json"
        contract = build_source_contract(contract_path)
        if len(contract["source_closure"]) < 8:
            raise ChainFailure("ABI source closure is incomplete")
        # The chain must fail closed for a custom task kind and for a changed
        # producer request SHA.  These checks exercise the actual runtime CLI,
        # not a handwritten receipt or a direct helper return value.
        bad = json.loads((root / "requests" / "tiny_F2_S2_original-attempt_F2_S2_original.json").read_text())
        bad["cpu_task_kind"] = "initial_support_native_header_probe"
        bad_path = root / "bad-task-kind.json"; bad_path.write_text(json.dumps(bad, indent=2) + "\n")
        process = subprocess.run([str(VENV), str(RUNTIME_V8), "run", "--request", str(bad_path), "--data-root", str(data_root)],
                                 cwd=str(PRIMARY_REPO), capture_output=True, text=True, timeout=30, check=False)
        if process.returncode == 0:
            raise ChainFailure("runtime-v8 accepted unsupported custom CPU task kind")
        result = {"schema": SCHEMA, "status": "PASS_MANUFACTURED_REAL_RUNTIME_V8_HEADER_INITIAL_SUPPORT_CALIBRATION_CHAIN",
                  "producer_rows": 9, "header_report": str(header_path),
                  "calibration_results": calibration_results, "source_contract": str(contract_path),
                  "literal_venv": str(VENV), "runtime_source": str(RUNTIME_V8),
                  "production_credit": 0, "scientific_qualification": dict(UNKNOWN),
                  "payload_scope": {"production_bi4": False, "production_vtk": False, "production_hdf5": False,
                                    "solver_launch": False, "gencase_launch": False},
                  "negative_custom_cpu_task_rejected": True}
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build-contract", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--product-map", type=Path)
    parser.add_argument("--initial-manifest", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            self_test()
            return 0
        if args.output is None:
            parser.error("--build-contract requires --output")
        build_source_contract(args.output, product_map=args.product_map,
                              initial_manifest=args.initial_manifest)
        print(json.dumps({"schema": SCHEMA, "status": "SOURCE_PREPARED_NO_PRODUCTION_CREDIT",
                          "output": str(_abs(args.output)), "production_credit": 0}, sort_keys=True))
        return 0
    except (ChainFailure, OSError, ValueError, json.JSONDecodeError, AssertionError) as exc:
        print(f"FAILED_THREE_SENTINEL_OWNER_GRID_ABI_CHAIN_V1: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
