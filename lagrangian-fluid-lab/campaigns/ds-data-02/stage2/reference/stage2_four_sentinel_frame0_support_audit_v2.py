#!/usr/bin/env python3
"""Decode one exact native frame zero with position-only BI4 compatibility.

GenCase initial products and solver output use related BI4 containers but do
not have the same array contract.  This additive worker accepts the required
Idp/Idpd plus Pos/Posd arrays and treats Vel, Rhop and Mass as optional
observations.  Missing optional arrays produce explicit UNKNOWN field status;
the worker never fills them with zeros or derives native mass from the XML
constant.  It still performs source XML range assignment, finite checks for
every present array, and a pre/post source stat/SHA guard around the official
``bi4_dump`` call.

The worker does not claim Fluid/Bound geometric support, continuous owner
mass, world-axis qualification, or numerical quality from a frame-zero result.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import tempfile
import subprocess
from typing import Any

import numpy as np


HERE = Path(__file__).resolve().parent
OBSERVER = HERE / "stage2_native_physical_observer_v2.py"
CONTRACT = HERE / "stage2_four_sentinel_frame0_support_audit_contract_v2.json"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
SCHEMA = "ds02.stage2.four-sentinel-frame0-support-audit.v2"
MANIFEST_SCHEMA = "ds02.stage2.four-sentinel-frame0-support-manifest.v2"
CASES = ("F2-S2", "F4-S2", "F5-S2", "F7-S1")
MAX_SMALL_BYTES = 16 * 1024 * 1024
SCRATCH_CAP_BYTES = 256 * 1024 * 1024


class AuditFailure(RuntimeError):
    pass


def _load_observer() -> Any:
    spec = importlib.util.spec_from_file_location("stage2_native_physical_observer_v2_frame0_source", OBSERVER)
    if spec is None or spec.loader is None:
        raise AuditFailure(f"cannot import observer: {OBSERVER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino), "bytes": int(value.st_size),
            "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns)}


def _regular(path: Path, label: str) -> dict[str, int]:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise AuditFailure(f"{label} is not a regular non-symlink file: {path}")
    return _stat(path)


def _sha_stat(path: Path, label: str) -> tuple[str, dict[str, int]]:
    path = path.expanduser().absolute()
    before = _regular(path, label)
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    after = _regular(path, label)
    if before != after or size != before["bytes"]:
        raise AuditFailure(f"{label} changed during SHA pass: {path}")
    return digest.hexdigest(), after


def _small_json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = path.expanduser().absolute()
    stat_before = _regular(path, label)
    if stat_before["bytes"] > MAX_SMALL_BYTES:
        raise AuditFailure(f"{label} exceeds bounded read: {path}")
    raw = path.read_bytes()
    stat_after = _regular(path, label)
    if stat_before != stat_after or len(raw) != stat_before["bytes"]:
        raise AuditFailure(f"{label} changed while read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditFailure(f"{label} is not JSON: {path}") from exc
    if not isinstance(value, dict):
        raise AuditFailure(f"{label} is not an object: {path}")
    return value, {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "stat": stat_after}


def _manifest(path: Path) -> dict[str, Any]:
    value, _ = _small_json(path, "frame-0 support manifest")
    if value.get("schema") != MANIFEST_SCHEMA:
        raise AuditFailure(f"manifest schema mismatch: {value.get('schema')!r}")
    cases = value.get("cases")
    if not isinstance(cases, list) or {str(item.get('sentinel_id')) for item in cases if isinstance(item, dict)} != set(CASES):
        raise AuditFailure("manifest must contain exactly F2-S2/F4-S2/F5-S2/F7-S1")
    return value


def _assert_receipt_identity(case: dict[str, Any], receipt: dict[str, Any], receipt_record: dict[str, Any]) -> None:
    if receipt.get("status") != "completed" or int(receipt.get("returncode", -1)) != 0:
        raise AuditFailure("terminal solver receipt is not completed with returncode 0")
    request = receipt.get("request")
    if not isinstance(request, dict):
        raise AuditFailure("terminal receipt has no nested request")
    missing_receipt_fields: list[str] = []
    expected_identity = case.get("receipt_identity_expected") or {}
    for key in ("family_id", "sentinel_id", "physical_case_id", "case_id", "attempt_id"):
        expected = expected_identity.get(key, case.get(key))
        actual = request.get(key)
        if actual is None:
            # Missing producer identity remains explicitly partial/UNKNOWN;
            # it is never reconstructed from sentinel labels or paths.
            missing_receipt_fields.append(key)
            continue
        if expected is not None and actual != expected:
            raise AuditFailure(f"receipt request {key} does not match manifest")
    declared = case.get("receipt_sha256")
    if declared is not None and declared != receipt_record["sha256"]:
        raise AuditFailure("receipt SHA differs from manifest declaration")
    output_root = case.get("terminal_output_root")
    if not isinstance(output_root, str) or Path(output_root).expanduser().absolute() != Path(str(receipt.get("output_root", ""))).expanduser().absolute():
        raise AuditFailure("receipt output_root does not match manifest")
    if missing_receipt_fields:
        case["receipt_identity_missing_fields"] = missing_receipt_fields


def _expected_stat(record: dict[str, Any]) -> dict[str, int]:
    value = record.get("stat_at_build") or record.get("stat") or {}
    aliases = {"device": ("device", "st_dev", "dev"), "inode": ("inode", "st_ino", "ino"),
               "bytes": ("bytes",), "mtime_ns": ("mtime_ns",), "ctime_ns": ("ctime_ns",)}
    result: dict[str, int] = {}
    for target, names in aliases.items():
        for name in names:
            if name in value:
                result[target] = int(value[name]); break
    return result


def _check_stat(expected: dict[str, int], actual: dict[str, int], label: str) -> None:
    for key, value in expected.items():
        if actual.get(key) != value:
            raise AuditFailure(f"{label} {key} changed: expected {value}, got {actual.get(key)}")


def _read_array(path: Path, dtype: np.dtype[Any], label: str) -> tuple[np.ndarray, dict[str, Any]]:
    """Read one decoder array from a stable byte image and report its digest."""
    before = _regular(path, label)
    raw = path.read_bytes()
    after = _regular(path, label)
    if before != after or len(raw) != before["bytes"]:
        raise AuditFailure(f"{label} changed while reading decoder output")
    itemsize = int(dtype.itemsize)
    if itemsize <= 0 or len(raw) % itemsize:
        raise AuditFailure(f"{label} byte count is not aligned to {dtype}")
    array = np.frombuffer(raw, dtype=dtype).copy()
    return array, {
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "stat_pre": before,
        "stat_post": after,
        "bytes": len(raw),
        "dtype": str(dtype),
        "stable": True,
    }


def _decode_position_aware(frame_path: Path, decoder: Path, scratch_root: Path,
                           frame: int, observer: Any) -> dict[str, Any]:
    """Decode required identity/position and optional dynamic arrays.

    ``stage2_native_physical_observer_v2.decode_frame`` intentionally requires
    Vel/Rhop for dynamic solver frames.  GenCase frame-zero products can be
    position-only, so this worker uses the same official decoder and XML path
    discovery but keeps optional arrays independent and explicit.
    """
    scratch_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"native-frame-{frame:04d}-", dir=scratch_root) as temporary:
        prefix = Path(temporary) / "decoded"
        try:
            subprocess.run(
                [str(decoder), str(frame_path), str(prefix)],
                check=True, capture_output=True, text=True, timeout=300,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            detail = getattr(exc, "stderr", "") or ""
            raise AuditFailure(f"official BI4 decoder failed for frame {frame}: {detail[-1000:]}") from exc
        try:
            decoder_xml, data_root = observer._decoder_particle_paths(prefix)
        except Exception as exc:
            raise AuditFailure(f"official BI4 decoder output schema is unsupported: {exc}") from exc
        names = ("Idp", "Idpd", "Pos", "Posd", "Vel", "Rhop", "Mass")
        paths = {name: data_root / f"{name}.bin" for name in names}
        identity_names = [name for name in ("Idp", "Idpd") if paths[name].is_file()]
        position_names = [name for name in ("Pos", "Posd") if paths[name].is_file()]
        if len(identity_names) != 1:
            raise AuditFailure(f"decoder must expose exactly one identity array, got {identity_names}")
        if len(position_names) != 1:
            raise AuditFailure(f"decoder must expose exactly one position array, got {position_names}")
        identity_name = identity_names[0]
        position_name = position_names[0]
        identity_dtype = np.dtype("<u4") if identity_name == "Idp" else np.dtype("<u8")
        position_dtype = np.dtype("<f4") if position_name == "Pos" else np.dtype("<f8")
        ids, identity_record = _read_array(paths[identity_name], identity_dtype, f"frame {frame} {identity_name}")
        position, position_record = _read_array(paths[position_name], position_dtype, f"frame {frame} {position_name}")
        if ids.size == 0 or np.unique(ids).size != ids.size:
            raise AuditFailure(f"empty or duplicate identity array in frame {frame}")
        count = int(ids.size)
        if position.size != count * 3:
            raise AuditFailure(f"position length does not match identity count in frame {frame}")
        order = np.argsort(ids, kind="mergesort")
        ids = ids[order]
        position = position.reshape(count, 3)[order]
        if not np.isfinite(position).all():
            raise AuditFailure(f"non-finite position in frame {frame}")

        optional: dict[str, tuple[np.ndarray | None, dict[str, Any] | None, np.dtype[Any], int]] = {}
        for name, dtype, width in (("Vel", np.dtype("<f4"), 3), ("Rhop", np.dtype("<f4"), 1), ("Mass", np.dtype("<f4"), 1)):
            if not paths[name].is_file():
                optional[name] = (None, None, dtype, width)
                continue
            array, record = _read_array(paths[name], dtype, f"frame {frame} {name}")
            if array.size != count * width:
                raise AuditFailure(f"{name} length does not match identity count in frame {frame}")
            array = array.reshape(count, width)[order] if width == 3 else array.reshape(count)[order]
            if not np.isfinite(array).all():
                raise AuditFailure(f"non-finite {name} in frame {frame}")
            optional[name] = (array, record, dtype, width)

        info = decoder_xml.get("info", {})
        raw_time = info.get("TimeStep")
        decoded_time = None
        if raw_time is not None:
            try:
                candidate_time = float(raw_time)
                if math.isfinite(candidate_time):
                    decoded_time = candidate_time
            except (TypeError, ValueError):
                decoded_time = None
        field_digest = hashlib.sha256()
        for name, array in ((identity_name, ids), (position_name, position),
                            ("Vel", optional["Vel"][0]), ("Rhop", optional["Rhop"][0]),
                            ("Mass", optional["Mass"][0])):
            if array is None:
                continue
            field_digest.update(name.encode("ascii"))
            field_digest.update(str(array.dtype).encode("ascii"))
            field_digest.update(json.dumps(list(array.shape)).encode("ascii"))
            field_digest.update(np.ascontiguousarray(array).tobytes())
        return {
            "ids": ids,
            "position": position,
            "velocity": optional["Vel"][0],
            "density": optional["Rhop"][0],
            "mass": optional["Mass"][0],
            "array_records": {identity_name: identity_record, position_name: position_record,
                              **{name: item[1] for name, item in optional.items() if item[1] is not None}},
            "field_presence": {identity_name: True, position_name: True,
                               "Vel": optional["Vel"][0] is not None,
                               "Rhop": optional["Rhop"][0] is not None,
                               "Mass": optional["Mass"][0] is not None},
            "decoded_time_s": decoded_time,
            "time_status": "PASS_FINITE_DECODER_TIMESTEP" if decoded_time is not None else "UNKNOWN_MISSING_OR_NONFINITE_TIMESTEP",
            "field_digest_sha256": field_digest.hexdigest(),
            "decoder_xml_sha256": _sha_stat(Path(decoder_xml["xml_path"]), "decoder XML")[0],
            "metadata": decoder_xml.get("metadata", {}),
            "info": info,
            "position_dtype": str(position_dtype),
        }


def _case_run(case: dict[str, Any], attempt_root: Path, observer: Any) -> dict[str, Any]:
    sentinel = str(case["sentinel_id"])
    receipt, receipt_record = _small_json(Path(case["receipt"]["path"]), f"{sentinel} solver receipt")
    _assert_receipt_identity(case, receipt, receipt_record)
    source_xml = Path(case["source_xml"]["path"]).expanduser().absolute()
    xml_stat = _regular(source_xml, f"{sentinel} source XML")
    if case["source_xml"].get("sha256"):
        xml_sha, xml_after = _sha_stat(source_xml, f"{sentinel} source XML")
        if xml_sha != case["source_xml"]["sha256"]:
            raise AuditFailure(f"{sentinel} source XML SHA changed")
        xml_stat = xml_after
    raw = Path(case["frame0"]["path"]).expanduser().absolute()
    expected = _expected_stat(case["frame0"])
    before_sha, before_stat = _sha_stat(raw, f"{sentinel} frame-0 BI4")
    _check_stat(expected, before_stat, f"{sentinel} frame-0 BI4 before decode")
    declared_sha = case["frame0"].get("known_sha256")
    if isinstance(declared_sha, str) and len(declared_sha) == 64 and before_sha != declared_sha:
        raise AuditFailure(f"{sentinel} frame-0 BI4 SHA differs from parent declaration")
    scratch = attempt_root / "scratch" / sentinel.replace("-", "_")
    scratch.mkdir(parents=True, exist_ok=True)
    decoded = _decode_position_aware(raw, Path(case["decoder"]["path"]), scratch, 0, observer)
    after_sha, after_stat = _sha_stat(raw, f"{sentinel} frame-0 BI4 post-decode")
    if before_sha != after_sha or before_stat != after_stat:
        raise AuditFailure(f"{sentinel} frame-0 BI4 changed across decode")
    source = observer.parse_source_xml(source_xml)
    kind, mkfluid, mk_absolute = observer.assign_particle_ranges(decoded["ids"], source["blocks"])
    role_counts: dict[str, int] = {}
    for role in sorted(set(kind.tolist())):
        role_counts[role] = int((kind == role).sum())
    abs_mk_counts: dict[str, int] = {}
    for mk in sorted(set(mk_absolute.tolist())):
        abs_mk_counts[str(int(mk))] = int((mk_absolute == mk).sum())
    fluid_mask = kind == "fluid"
    native_mass = decoded.get("mass")
    native_mass_sum = None if native_mass is None else float(np.sum(native_mass[fluid_mask], dtype=np.float64))
    field_presence = decoded["field_presence"]
    finite_fields = {
        "position": bool(np.isfinite(decoded["position"]).all()),
        "velocity": ("UNKNOWN_MISSING_ARRAY" if decoded["velocity"] is None else bool(np.isfinite(decoded["velocity"]).all())),
        "density": ("UNKNOWN_MISSING_ARRAY" if decoded["density"] is None else bool(np.isfinite(decoded["density"]).all())),
        "mass": ("UNKNOWN_MISSING_ARRAY" if decoded["mass"] is None else bool(np.isfinite(decoded["mass"]).all())),
        "ids_unique": True,
    }
    required_position_status = "PASS_POSITION_IDENTITY_FINITE"
    dynamic_status = "PASS_DYNAMIC_FIELDS_FINITE" if all(field_presence.get(name, False) for name in ("Vel", "Rhop")) else "UNKNOWN_POSITION_ONLY_OR_PARTIAL_FIELDS"
    decoded_time = decoded.get("decoded_time_s")
    return {
        "sentinel_id": sentinel, "status": "PASS_FRAME0_POSITION_IDENTITY_DIAGNOSTIC",
        "source_xml": {"path": str(source_xml), "stat": xml_stat, "sha256": case["source_xml"].get("sha256")},
        "receipt": receipt_record, "receipt_identity": {"status": "PASS_CASE_ATTEMPT_PHYSICAL" if not case.get("receipt_identity_missing_fields") else "PARTIAL_SENTINEL_FIELD_ABSENT", "missing_fields": case.get("receipt_identity_missing_fields", [])},
        "native": {"path": str(raw), "sha256": before_sha, "stat_pre": before_stat, "stat_post": after_stat, "post_equal": True},
        "decoded_time_s": decoded_time, "decoded_time_status": decoded["time_status"],
        "field_digest_sha256": decoded["field_digest_sha256"], "field_presence": field_presence,
        "finite_fields": finite_fields, "position_identity_status": required_position_status,
        "dynamic_field_status": dynamic_status, "decoder_array_records": decoded["array_records"],
        "role_counts": role_counts, "absolute_mk_counts": abs_mk_counts,
        "range_overlap": {"status": "PASS_XML_RANGES_DISJOINT_AND_COVERED", "source": "official source XML Idp ranges"},
        "sample_mass": {"native_mass_array": "PASS" if native_mass is not None else "UNKNOWN_MISSING_MASS_ARRAY",
                        "native_fluid_mass_sum_kg": native_mass_sum,
                        "source_xml_massfluid_kg": source["constants"].get("massfluid"),
                        "source_constant_is_not_native_mass": True,
                        "fluid_count": int(np.count_nonzero(fluid_mask)),
                        "continuous_owner_mass": "UNKNOWN_NOT_DERIVED"},
        "geometric_support": {"status": "UNKNOWN_NO_FLUID_BOUND_VTK_BOUND_IN_SOURCE_CARD", "fluid_inside": "UNKNOWN", "bound_overlap": "UNKNOWN", "contact": "UNKNOWN"},
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0},
    }


def run(manifest_path: Path, attempt_root: Path, output: Path) -> dict[str, Any]:
    manifest = _manifest(manifest_path)
    observer = _load_observer()
    cases: list[dict[str, Any]] = []
    passed = failed = 0
    for case in manifest["cases"]:
        try:
            result = _case_run(case, attempt_root, observer)
            passed += 1
        except Exception as exc:
            result = {"sentinel_id": case.get("sentinel_id"), "status": "FAILED_FRAME0_POSITION_IDENTITY_DIAGNOSTIC", "reason": repr(exc), "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}}
            failed += 1
        cases.append(result)
    status = "COMPLETE_PARTIAL_FRAME0_POSITION_IDENTITY_DIAGNOSTICS" if passed else "FAILED_FRAME0_POSITION_IDENTITY_DIAGNOSTICS"
    value = {"schema": SCHEMA, "status": status, "manifest": str(manifest_path.expanduser().absolute()), "cases": cases,
             "case_counts": {"PASS": passed, "FAILED": failed}, "geometric_support": "UNKNOWN", "continuous_owner_mass": "UNKNOWN",
             "read_scope": {"hdf5_read": False, "solver_launch": False, "full_native_tree_scan": False, "deferred_frame_count": len(cases), "world_axis": "UNKNOWN"},
             "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}}
    output = output.expanduser().absolute(); output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() or output.is_symlink():
        raise AuditFailure(f"refusing overwrite: {output}")
    output.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return value


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="four-sentinel-frame0-") as td:
        path = Path(td) / "x.bi4"; path.write_bytes(b"fixture")
        stat = _stat(path)
        _check_stat(stat, stat, "fixture")
        bad = dict(stat); bad["inode"] += 1
        try:
            _check_stat(bad, stat, "fixture")
        except AuditFailure:
            pass
        else:
            raise AssertionError("inode mutation was accepted")
        receipt = {"status": "completed", "returncode": 0, "output_root": td,
                   "request": {"family_id": "F7", "case_id": "CASE",
                               "attempt_id": "ATTEMPT", "physical_case_id": None}}
        case = {"family_id": "F7", "sentinel_id": "F7-S1",
                "physical_case_id": None, "receipt_identity_expected":
                    {"family_id": "F7", "sentinel_id": "F7-S1",
                     "physical_case_id": "F7-PHYSICAL", "case_id": "CASE",
                     "attempt_id": "ATTEMPT"},
                "receipt_sha256": "receipt-sha", "terminal_output_root": td}
        _assert_receipt_identity(case, receipt, {"sha256": "receipt-sha"})
        assert set(case["receipt_identity_missing_fields"]) == {"sentinel_id", "physical_case_id"}
        bad = dict(receipt)
        bad["request"] = dict(receipt["request"], physical_case_id="WRONG")
        try:
            _assert_receipt_identity(case, bad, {"sha256": "receipt-sha"})
        except AuditFailure:
            pass
        else:
            raise AssertionError("producer physical identity mismatch was accepted")
        ids_path = Path(td) / "Idp.bin"
        ids_path.write_bytes(np.asarray([2, 1], dtype="<u4").tobytes())
        ids, ids_record = _read_array(ids_path, np.dtype("<u4"), "fixture Idp")
        assert ids.tolist() == [2, 1] and ids_record["stable"] is True
        # Position-only is a valid diagnostic shape: optional dynamic arrays
        # are represented by absence/UNKNOWN rather than fabricated zeros.
        assert not (Path(td) / "Vel.bin").exists()
    print("PASS_FOUR_SENTINEL_FRAME0_POSITION_SUPPORT_WORKER_SELFTEST")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True); mode.add_argument("--self-test", action="store_true"); mode.add_argument("--run", action="store_true")
    parser.add_argument("--manifest", type=Path); parser.add_argument("--attempt-root", type=Path); parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.self_test:
        self_test(); return 0
    if args.manifest is None or args.attempt_root is None or args.output is None:
        parser.error("--run requires --manifest, --attempt-root, --output")
    try:
        value = run(args.manifest, args.attempt_root, args.output)
        print(json.dumps({"status": value["status"], "output": str(args.output.absolute()), "case_counts": value["case_counts"]}, sort_keys=True))
        return 0 if value["case_counts"]["FAILED"] == 0 else 2
    except Exception as exc:
        print(f"FAILED_FOUR_SENTINEL_FRAME0_SUPPORT: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
