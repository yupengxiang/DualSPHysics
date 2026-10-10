#!/usr/bin/env python3
"""Guarded native-header probe for owner-grid GenCase products.

The frozen initial-support worker accepts a V1 sidecar only when it already
contains finite position/identity fields.  A fresh GenCase product may expose
only position/Idp arrays, and the old worker's optional probe consequently
remains ``NOT_BOUND``.  This additive probe runs the already-bound decoder in
the *same parent guard* as the initial-support audit and extracts only the
decoder-produced outer metadata: ``MassFluid``, optional ``MassBound``,
``Dp``, time, and any role-count fields actually exposed there.  It never
reads the generated solver XML as a mass source and never turns a missing
field into a value.

The native BI4 is hashed before the decoder, the decoder output is read from a
bounded scratch directory, and the BI4 is hashed/stat-checked again after the
parse and cleanup.  The runtime receipt is joined to the exact producer
request file bytes through ``verify_v3``.  This module only consumes a
manufactured fixture in its self-test; production GenCase/BI4/VTK/HDF5 data
must be supplied by a parent reservation.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from typing import Any


HERE = Path(__file__).resolve().parent
VERIFY_V3 = HERE / "stage2_three_sentinel_owner_grid_initial_support_verify_v3.py"
SCHEMA = "ds02.stage2.native-header-probe.v2"
PROBE_STATUS = "PASS_NATIVE_HEADER_FIELDS"
UNKNOWN_STATUS = "UNKNOWN_NATIVE_HEADER_FIELDS_NOT_EXPOSED_BY_DECODER"
JSON_CAP = 10 * 1024 * 1024
SCRATCH_CAP = 256 * 1024 * 1024
LOG_CAP = 64 * 1024
TIMEOUT_S = 300


class ProbeFailure(RuntimeError):
    pass


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ProbeFailure(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V3 = _load(VERIFY_V3, "owner_grid_support_verify_v3_for_native_header_probe")


def _abs(value: Path) -> Path:
    return value.expanduser().absolute()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _stat(path: Path) -> dict[str, int]:
    st = path.stat()
    return {"device": int(st.st_dev), "inode": int(st.st_ino), "bytes": int(st.st_size),
            "mtime_ns": int(st.st_mtime_ns), "ctime_ns": int(st.st_ctime_ns)}


def _regular(path: Path, label: str) -> Path:
    path = _abs(path)
    if path.is_symlink() or not path.is_file():
        raise ProbeFailure(f"{label} is not a regular non-symlink file: {path}")
    return path


def _record(path: Path, label: str) -> dict[str, Any]:
    path = _regular(path, label)
    raw = path.read_bytes()
    return {"path": str(path), "sha256": _sha(raw), "stat": _stat(path)}


def _expected_stat(record: Any) -> dict[str, int]:
    if not isinstance(record, dict):
        return {}
    source = record.get("stat") or record.get("stat_after") or record.get("stat_post") or {}
    aliases = {"device": ("device", "dev", "st_dev"), "inode": ("inode", "ino", "st_ino"),
               "bytes": ("bytes", "size"), "mtime_ns": ("mtime_ns",), "ctime_ns": ("ctime_ns",)}
    result: dict[str, int] = {}
    for target, names in aliases.items():
        for name in names:
            if isinstance(source, dict) and name in source:
                result[target] = int(source[name]); break
    return result


def _guarded_file(path: Path, record: Any, label: str, *, read: bool) -> tuple[bytes | None, dict[str, Any]]:
    path = _regular(path, label)
    before = _stat(path)
    expected = _expected_stat(record)
    for key, value in expected.items():
        if before[key] != value:
            raise ProbeFailure(f"{label} {key} differs before probe")
    declared = record.get("sha256") if isinstance(record, dict) else None
    if declared is not None and (not isinstance(declared, str) or len(declared) != 64):
        raise ProbeFailure(f"{label} has malformed declared SHA")
    raw = path.read_bytes() if read else None
    if read and declared is not None and _sha(raw or b"").lower() != declared.lower():
        raise ProbeFailure(f"{label} SHA differs from declared source record")
    after = _stat(path)
    if before != after or (raw is not None and len(raw) != before["bytes"]):
        raise ProbeFailure(f"{label} changed during guarded read")
    return raw, {"path": str(path), "sha256_pre": _sha(raw) if raw is not None else declared,
                 "sha256_post": _sha(raw) if raw is not None else declared,
                 "stat_pre": before, "stat_post": after, "stable": True,
                 "complete_payload_passes": 1 if raw is not None else 0}


def _scalar(value: str | None) -> Any:
    if value is None:
        return None
    try:
        parsed = float(value)
    except ValueError:
        return value
    return parsed if math.isfinite(parsed) else None


def _decoder_values(root: ET.Element) -> dict[str, Any]:
    """Read values from decoder XML, without assuming a source XML layout."""
    values: dict[str, Any] = {}
    for node in root.iter():
        name = node.attrib.get("name") or node.attrib.get("key") or node.attrib.get("field")
        if not name:
            continue
        raw = node.attrib.get("value")
        if raw is None:
            raw = node.attrib.get("data")
        if raw is None and node.text and not list(node):
            raw = node.text.strip()
        if raw is not None:
            values[str(name)] = _scalar(raw)
    return values


def _lookup(values: dict[str, Any], *names: str) -> Any:
    wanted = {name.lower() for name in names}
    for key, value in values.items():
        if str(key).lower() in wanted:
            return value
    return None


def _find_decoder_xml(prefix: Path) -> Path:
    exact = Path(str(prefix) + ".xml")
    if exact.is_file() and not exact.is_symlink():
        return exact
    candidates = [p for p in prefix.parent.rglob("*.xml") if p.is_file() and not p.is_symlink()]
    if len(candidates) != 1:
        raise ProbeFailure(f"decoder output XML is not uniquely identified under {prefix.parent}")
    return candidates[0]


def _parse_decoder_xml(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    before = _stat(path)
    if before["bytes"] > JSON_CAP:
        raise ProbeFailure(f"decoder XML exceeds bounded metadata cap: {path}")
    raw = path.read_bytes()
    sha_pre = _sha(raw)
    root = ET.fromstring(raw)
    after = _stat(path)
    raw_after = path.read_bytes()
    sha_post = _sha(raw_after)
    if before != after or sha_pre != sha_post:
        raise ProbeFailure(f"decoder XML changed during bounded parse: {path}")
    return _decoder_values(root), {"path": str(path), "sha256_pre": sha_pre,
                                   "sha256_post": sha_post, "stat_pre": before,
                                   "stat_post": after, "stable": True,
                                   "complete_payload_passes": 2}


def _run_decoder(decoder: Path, native: Path, scratch: Path) -> tuple[Path, dict[str, Any]]:
    decoder = _regular(decoder, "official BI4 decoder")
    scratch.mkdir(parents=True, exist_ok=True)
    prefix = scratch / "decoded"
    command = [str(decoder), str(native), str(prefix)]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
        raise ProbeFailure("official BI4 decoder timed out") from exc
    stdout = (stdout or b"")[-LOG_CAP:]
    stderr = (stderr or b"")[-LOG_CAP:]
    if process.returncode != 0:
        raise ProbeFailure(f"official BI4 decoder failed rc={process.returncode}: {stderr.decode(errors='replace')[-1000:]}")
    xml_path = _find_decoder_xml(prefix)
    values, xml_guard = _parse_decoder_xml(xml_path)
    return xml_path, {"command": command, "returncode": process.returncode,
                      "stdout_tail": stdout.decode(errors="replace"),
                      "stderr_tail": stderr.decode(errors="replace"),
                      "xml": xml_guard, "values": values}


def _role_counts(values: dict[str, Any]) -> dict[str, Any]:
    aliases = {
        "fluid": ("Nfluid", "NFluid", "FluidCount", "fluid_count"),
        "bound": ("Nbound", "NBound", "BoundCount", "bound_count"),
        "moving": ("Nmoving", "NMoving", "MovingCount", "moving_count"),
        "floating": ("Nfloating", "NFloating", "FloatingCount", "floating_count"),
        "total": ("Npart", "NPart", "Ntotal", "NTotal", "particle_count"),
    }
    result: dict[str, Any] = {}
    for role, names in aliases.items():
        value = _lookup(values, *names)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            result[role] = "UNKNOWN_NOT_EXPOSED_BY_DECODER"
        else:
            result[role] = int(value) if float(value).is_integer() else float(value)
    return result


def _probe_case(case: dict[str, Any], attempt_root: Path) -> dict[str, Any]:
    key = str(case.get("row_key") or f"{case.get('sentinel_id')}:{case.get('grid_label')}")
    receipt_record = case.get("gencase_receipt")
    receipt_path, _ = V3._path_record(receipt_record, f"{key} GenCase receipt")
    receipt, _, _ = V3._read_json(receipt_path, f"{key} GenCase receipt")
    V3._receipt_identity_v3(receipt_path, case, receipt)
    native_record = case.get("native_bi4")
    if not isinstance(native_record, dict) or not isinstance(native_record.get("path"), str):
        raise ProbeFailure(f"{key} native BI4 record lacks path")
    # A BI4 is deferred payload.  Do not use the metadata helper that hashes
    # every declared record before the worker guard (and imposes the 10 MiB
    # JSON cap); the guarded two-pass read below is its first payload access.
    native_path = _abs(Path(native_record["path"]))
    if native_path.is_symlink() or not native_path.is_file():
        raise ProbeFailure(f"{key} native BI4 is not a regular file")
    _, native_pre = _guarded_file(native_path, native_record, f"{key} native BI4", read=True)
    decoder_path = _abs(Path(str(case.get("decoder", {}).get("path", ""))))
    scratch = _abs(attempt_root) / "scratch" / key.replace(":", "_")
    xml_path, decoder = _run_decoder(decoder_path, native_path, scratch)
    values = decoder["values"]
    # The metadata names are from the decoder output.  No generated/source XML
    # value is consulted here.
    massfluid = _lookup(values, "MassFluid", "massfluid")
    massbound = _lookup(values, "MassBound", "massbound")
    dp = _lookup(values, "Dp", "dp")
    time_s = _lookup(values, "TimeStep", "time_s", "Time")
    finite_numeric = {
        name: (isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)))
        for name, value in (("MassFluid", massfluid), ("MassBound", massbound), ("Dp", dp), ("TimeStep", time_s))
    }
    native_post_raw, native_post = _guarded_file(native_path, native_record, f"{key} native BI4 post-decode", read=True)
    if native_pre["sha256_pre"] != native_post["sha256_post"] or native_pre["stat_pre"] != native_post["stat_post"]:
        raise ProbeFailure(f"{key} native BI4 changed during decoder/parse")
    status = PROBE_STATUS if finite_numeric["MassFluid"] and finite_numeric["Dp"] else UNKNOWN_STATUS
    result = {
        "schema": SCHEMA, "status": status, "row_key": key,
        "source_path": str(native_path), "source_sha256": native_post["sha256_post"],
        "source_guard": {"pre": native_pre, "post": native_post,
                          "full_source_passes": 2, "decoder_read_enclosed": True},
        "decoder_xml": decoder["xml"], "decoder_command": decoder["command"],
        "decoder_returncode": decoder["returncode"], "decoder_values": values,
        "massfluid": massfluid if finite_numeric["MassFluid"] else "UNKNOWN_NOT_EXPOSED_BY_DECODER",
        "massbound": massbound if finite_numeric["MassBound"] else "UNKNOWN_NOT_EXPOSED_BY_DECODER",
        "dp": dp if finite_numeric["Dp"] else "UNKNOWN_NOT_EXPOSED_BY_DECODER",
        "time_s": time_s if finite_numeric["TimeStep"] else "UNKNOWN_NOT_EXPOSED_BY_DECODER",
        "role_counts": _role_counts(values),
        "finite_fields": {
            "position": "UNKNOWN_NOT_DECODED_BY_HEADER_PROBE",
            "ids_unique": "UNKNOWN_NOT_DECODED_BY_HEADER_PROBE",
            "header_numeric_fields": finite_numeric,
        },
        "source_xml_mass_is_not_native": True,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0},
    }
    return result


def _json_load(path: Path) -> dict[str, Any]:
    value, _, _ = V3._read_json(path, "native-header probe manifest")
    if value.get("schema") != "ds02.stage2.three-sentinel-owner-grid-native-header-probe-manifest.v2":
        raise ProbeFailure("native-header probe manifest schema mismatch")
    if value.get("status") != "READY_FOR_PARENT_GUARDED_NATIVE_HEADER_PROBE":
        raise ProbeFailure("native-header probe manifest status is not parent-guarded")
    if not isinstance(value.get("cases"), list) or not value["cases"]:
        raise ProbeFailure("native-header probe manifest has no cases")
    return value


def run(manifest_path: Path, attempt_root: Path, output_path: Path) -> dict[str, Any]:
    manifest = _json_load(_abs(manifest_path))
    rows: list[dict[str, Any]] = []
    for case in manifest["cases"]:
        if not isinstance(case, dict):
            raise ProbeFailure("native-header probe case is malformed")
        rows.append(_probe_case(case, _abs(attempt_root)))
    payload = {
        "schema": SCHEMA, "status": "COMPLETE_NATIVE_HEADER_PROBE_DIAGNOSTIC",
        "manifest": str(_abs(manifest_path)), "cases": rows,
        "native_mass_source": "decoder-produced BI4 metadata only",
        "xml_fallback": False, "solver_launch": False, "gencase_launch": False,
        "hdf5_read": False,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0},
    }
    output_path = _abs(output_path)
    if output_path.exists() or output_path.is_symlink():
        raise ProbeFailure(f"refusing overwrite: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_name(f".{output_path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    tmp.replace(output_path)
    return payload


def _write_fixture_decoder(path: Path, *, include_mass: bool = True) -> None:
    xml = "<data><item name='Header'><item name='MassFluid' value='0.5'/><item name='MassBound' value='1.25'/><item name='Dp' value='0.01'/><item name='Nfluid' value='2'/><item name='Nbound' value='1'/></item></data>" if include_mass else "<data><item name='Header'><item name='Nfluid' value='2'/></item></data>"
    path.write_text("#!/usr/bin/env python3\nimport pathlib,sys\npathlib.Path(sys.argv[2] + '.xml').write_text(" + repr(xml) + ", encoding='utf-8')\n", encoding="utf-8")
    path.chmod(0o755)


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="owner-grid-native-header-v2-") as value:
        root = Path(value)
        decoder = root / "manufactured-decoder.sh"; _write_fixture_decoder(decoder)
        native = root / "generated.bi4"; native.write_bytes(b"manufactured-bi4")
        case_root = root / "F2" / "case" / "attempt"; case_root.mkdir(parents=True)
        receipt_path = case_root / "execution-receipt.json"
        request_path = root / "producer-request.json"
        producer = {"schema": "ds02.request.v1", "family_id": "F2", "case_id": "case",
                    "attempt_id": "attempt", "kind": "cpu", "cpu_task_kind": "gencase",
                    "execution_allowed": True, "gencase_launch": True, "output_root": str(case_root)}
        request_path.write_text(json.dumps(producer, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        receipt = {"schema": "ds02.execution-receipt.v1", "status": "completed", "returncode": 0,
                   "request": producer, "request_sha256": _sha(request_path.read_bytes()),
                   "output_root": str(case_root), "input_hashes_at_launch": {}, "input_hashes_after_run": {}}
        receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        record = lambda p: {"path": str(p), "sha256": _sha(p.read_bytes()), "stat": _stat(p)}
        manifest = {"schema": "ds02.stage2.three-sentinel-owner-grid-native-header-probe-manifest.v2",
                    "status": "READY_FOR_PARENT_GUARDED_NATIVE_HEADER_PROBE",
                    "cases": [{"row_key": "F2-S2:coarse", "sentinel_id": "F2-S2", "grid_label": "coarse",
                               "family_id": "F2", "gencase_receipt": record(receipt_path),
                               "producer_request": record(request_path), "native_bi4": record(native),
                               "decoder": record(decoder)}]}
        manifest_path = root / "manifest.json"; manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        output = root / "probe.json"
        result = run(manifest_path, root / "attempt", output)
        assert result["cases"][0]["status"] == PROBE_STATUS
        assert result["cases"][0]["massfluid"] == 0.5
        assert result["cases"][0]["massbound"] == 1.25
        # Decoder-produced XML without MassFluid/Dp stays UNKNOWN.  It is not
        # replaced by a generated/source XML mass value.
        decoder2 = root / "decoder-missing.sh"; _write_fixture_decoder(decoder2, include_mass=False)
        manifest["cases"][0]["decoder"] = record(decoder2)
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        output2 = root / "probe-missing.json"
        result2 = run(manifest_path, root / "attempt-missing", output2)
        assert result2["cases"][0]["status"] == UNKNOWN_STATUS
        assert result2["cases"][0]["massfluid"] == "UNKNOWN_NOT_EXPOSED_BY_DECODER"
    print("PASS_THREE_SENTINEL_OWNER_GRID_NATIVE_HEADER_PROBE_V2_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--attempt-root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            self_test(); return 0
        if args.manifest is None or args.attempt_root is None or args.output is None:
            parser.error("--run requires --manifest, --attempt-root, and --output")
        run(args.manifest, args.attempt_root, args.output); return 0
    except (ProbeFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_THREE_SENTINEL_OWNER_GRID_NATIVE_HEADER_PROBE_V2: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
