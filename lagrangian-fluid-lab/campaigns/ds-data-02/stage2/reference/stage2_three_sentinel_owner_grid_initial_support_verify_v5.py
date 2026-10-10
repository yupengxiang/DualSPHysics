#!/usr/bin/env python3
"""Independent metadata verifier for the ROOT709-bound support V2 package.

This verifier reads only the bounded manifest, request, ROOT709 proof/report,
and the nine tiny sidecars.  Product XML/VTK/BI4 files are stat'ed and never
opened or hashed.  A successful result means that a parent may perform the
deferred initial-support reads; it grants no native-mass, owner, QI, QN, or
QE credit.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
WORKER_PATH = HERE / "stage2_three_sentinel_owner_grid_initial_support_audit_v2.py"
JSON_CAP = 10 * 1024 * 1024
HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
MANIFEST_SCHEMA = "ds02.stage2.three-sentinel-owner-grid-initial-support-manifest.v2"
REPORT_SCHEMA = "ds02.stage2.native-header-probe.v3"
REPORT_ROW_SCHEMA = "ds02.stage2.native-header-probe.v2"
SIDECAR_SCHEMA = "ds02.stage2.native-header-probe.v3-sidecar.v1"
PROOF_STATUS = "VERIFIED_ACTUAL_NINE_GENCASE_NATIVE_HEADER_DIAGNOSTIC_NO_SCIENTIFIC_Q"
REPORT_STATUS = "COMPLETE_NATIVE_HEADER_PROBE_DIAGNOSTIC"
UNKNOWN_STATUS = "UNKNOWN_NATIVE_HEADER_FIELDS_NOT_EXPOSED_BY_DECODER"
PASS_STATUS = "PASS_NATIVE_HEADER_FIELDS"
TARGETS = ("F2-S2", "F3-S1", "F5-S1")
GRIDS = ("original", "coarse", "fine")
ROW_KEYS = tuple(f"{sid}:{grid}" for sid in TARGETS for grid in GRIDS)
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")


class VerifyFailure(RuntimeError):
    pass


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise VerifyFailure(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


WORKER = _load(WORKER_PATH, "owner_grid_initial_support_v2_for_v5_verify")


def _abs(value: Path | str) -> Path:
    return Path(value).expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    st = path.stat()
    return {"device": int(st.st_dev), "inode": int(st.st_ino), "bytes": int(st.st_size),
            "mtime_ns": int(st.st_mtime_ns), "ctime_ns": int(st.st_ctime_ns)}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(HEX64.fullmatch(value))


def _json(path: Path | str, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _abs(path)
    if path.is_symlink() or not path.is_file():
        raise VerifyFailure(f"{label} is not a regular file: {path}")
    before = _stat(path)
    if before["bytes"] > JSON_CAP:
        raise VerifyFailure(f"{label} exceeds 10 MiB cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise VerifyFailure(f"{label} changed during bounded read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerifyFailure(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise VerifyFailure(f"{label} must be an object")
    return value, {"path": str(path), "sha256": _sha(raw), "bytes": len(raw), "stat": after}


def _record_path(value: Any, label: str) -> Path:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise VerifyFailure(f"{label} lacks path")
    return _abs(value["path"])


def _record_sha(value: Any, actual: str, label: str) -> None:
    if isinstance(value, dict) and value.get("sha256") is not None:
        if value.get("sha256") != actual:
            raise VerifyFailure(f"{label} SHA differs from file bytes")


def _norm_stat(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, int] = {}
    for target, names in {"device": ("device", "dev", "st_dev"),
                          "inode": ("inode", "ino", "st_ino"),
                          "bytes": ("bytes", "size"), "mtime_ns": ("mtime_ns",),
                          "ctime_ns": ("ctime_ns",)}.items():
        for name in names:
            if name in value:
                out[target] = int(value[name]); break
    return out


def _product_stat(record: Any, label: str, waiting: list[str]) -> None:
    if not isinstance(record, dict) or not isinstance(record.get("path"), str):
        raise VerifyFailure(f"{label} lacks product path")
    path = _abs(record["path"])
    if path.is_symlink() or not path.is_file():
        waiting.append(f"{label} is not present")
        return
    actual = _stat(path)
    expected = _norm_stat(record.get("stat"))
    for key, value in expected.items():
        if actual[key] != value:
            raise VerifyFailure(f"{label} {key} differs from deferred stat")


def _source_guard_stats(row: dict[str, Any]) -> tuple[dict[str, int], dict[str, int]]:
    guard = row.get("source_guard")
    if not isinstance(guard, dict):
        raise VerifyFailure(f"{row.get('row_key')} lacks source_guard")
    pre = guard.get("pre") if isinstance(guard.get("pre"), dict) else guard
    post = guard.get("post") if isinstance(guard.get("post"), dict) else guard
    pre_stat = _norm_stat(pre.get("stat_pre") or pre.get("stat") or pre.get("stat_before"))
    post_stat = _norm_stat(post.get("stat_post") or post.get("stat") or post.get("stat_after"))
    if not pre_stat or not post_stat:
        raise VerifyFailure(f"{row.get('row_key')} source_guard lacks complete stats")
    return pre_stat, post_stat


def _verify_header_binding(manifest: dict[str, Any], errors: list[str]) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    binding = manifest.get("header_binding")
    if not isinstance(binding, dict):
        raise VerifyFailure("manifest lacks header_binding")
    if binding.get("actual_header_count") != 9 or binding.get("xml_mass_is_not_native") is not True or binding.get("xml_fallback") is not False:
        raise VerifyFailure("manifest header binding permits incomplete/derived native fields")
    proof_path = _record_path(binding.get("proof"), "ROOT709 proof")
    report_path = _record_path(binding.get("report"), "ROOT709 report")
    proof, proof_record = _json(proof_path, "ROOT709 proof")
    report, report_record = _json(report_path, "ROOT709 report")
    _record_sha(binding.get("proof"), proof_record["sha256"], "ROOT709 proof")
    _record_sha(binding.get("report"), report_record["sha256"], "ROOT709 report")
    if proof.get("status") != PROOF_STATUS or proof.get("report") != str(report_path):
        raise VerifyFailure("ROOT709 proof does not bind exact report")
    if proof.get("report_sha256") != report_record["sha256"]:
        raise VerifyFailure("ROOT709 proof report SHA mismatch")
    if proof.get("scientific_Q_credit") not in (0, 0.0) or proof.get("H5_BI4_read_by_root") is not False:
        raise VerifyFailure("ROOT709 proof carries disallowed credit/payload read")
    request_path = _abs(proof["request"]) if isinstance(proof.get("request"), str) else None
    receipt_path = _abs(proof["receipt"]) if isinstance(proof.get("receipt"), str) else None
    if request_path is None or receipt_path is None:
        raise VerifyFailure("ROOT709 proof lacks exact request/receipt paths")
    producer_request, producer_request_record = _json(request_path, "ROOT709 producer request")
    producer_receipt, producer_receipt_record = _json(receipt_path, "ROOT709 execution receipt")
    if proof.get("request_sha256") != producer_request_record["sha256"] or proof.get("receipt_sha256") != producer_receipt_record["sha256"]:
        raise VerifyFailure("ROOT709 proof request/receipt SHA mismatch")
    if producer_request.get("schema") != "ds02.request.v1":
        raise VerifyFailure("ROOT709 producer request schema mismatch")
    if (producer_receipt.get("schema") != "ds02.execution-receipt.v1" or
            producer_receipt.get("status") != "completed" or producer_receipt.get("returncode") != 0 or
            producer_receipt.get("request") != producer_request or
            producer_receipt.get("request_sha256") != producer_request_record["sha256"]):
        raise VerifyFailure("ROOT709 receipt does not bind completed producer request")
    if report.get("schema") != REPORT_SCHEMA or report.get("status") != REPORT_STATUS or report.get("xml_fallback") not in (False, None):
        raise VerifyFailure("ROOT709 report schema/status/fallback mismatch")
    rows = report.get("cases")
    if not isinstance(rows, list) or len(rows) != 9:
        raise VerifyFailure("ROOT709 report does not contain nine rows")
    by_key: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("schema") != REPORT_ROW_SCHEMA:
            raise VerifyFailure("ROOT709 row schema mismatch")
        key = str(row.get("row_key"))
        if key not in ROW_KEYS or key in by_key:
            raise VerifyFailure(f"invalid/duplicate ROOT709 row {key}")
        if row.get("status") not in (UNKNOWN_STATUS, PASS_STATUS) or row.get("source_xml_mass_is_not_native") is not True:
            raise VerifyFailure(f"unsupported ROOT709 row status/fallback {key}")
        _source_guard_stats(row)
        if not isinstance(row.get("source_path"), str) or not _valid_sha(row.get("source_sha256")):
            raise VerifyFailure(f"ROOT709 row {key} lacks source path/SHA")
        by_key[key] = row
    if set(by_key) != set(ROW_KEYS):
        raise VerifyFailure("ROOT709 row keys incomplete")
    return proof, report, by_key


def verify(manifest_path: Path, request_path: Path, output_path: Path) -> dict[str, Any]:
    manifest, manifest_record = _json(manifest_path, "V2 initial-support manifest")
    request, request_record = _json(request_path, "V2 initial-support request")
    errors: list[str] = []
    waiting: list[str] = []
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "READY_FOR_PARENT_GUARDED_OWNER_GRID_INITIAL_SUPPORT_V2":
        errors.append("manifest schema/status mismatch")
    if request.get("schema") != "ds02.request.v1" or request.get("execution_allowed") is not False or request.get("launch_disabled") is not True:
        errors.append("request is not source-only and launch-disabled")
    if request.get("scientific_credit") != 0 or request.get("solver_launch") is not False or request.get("gencase_launch") is not False:
        errors.append("request carries execution/scientific credit")
    command = request.get("command")
    if not isinstance(command, list) or command[:1] != [str(PYTHON)] or str(WORKER_PATH) not in command:
        errors.append("request does not use the literal V2 venv/worker")
    if "--manifest" not in command or command[command.index("--manifest") + 1] != str(_abs(manifest_path)):
        errors.append("request manifest operand is not the exact static manifest")
    records = request.get("input_records")
    if not isinstance(records, dict) or str(_abs(manifest_path)) not in records:
        errors.append("request input_records does not contain the exact manifest")
    else:
        if records[str(_abs(manifest_path))].get("sha256") != manifest_record["sha256"]:
            errors.append("request manifest record SHA is stale")
    try:
        _, _, header_rows = _verify_header_binding(manifest, errors)
    except VerifyFailure as exc:
        errors.append(str(exc)); header_rows = {}
    rows = manifest.get("cases")
    if not isinstance(rows, list) or len(rows) != 9:
        errors.append("manifest does not contain exactly nine cases")
        rows = []
    by_key = {f"{row.get('sentinel_id')}:{row.get('grid_label')}": row for row in rows if isinstance(row, dict)}
    if set(by_key) != set(ROW_KEYS):
        errors.append("manifest row keys are incomplete")
    for key in ROW_KEYS:
        row = by_key.get(key)
        if row is None:
            continue
        sidecar = row.get("native_header_probe")
        try:
            sidecar_path = _record_path(sidecar, f"{key} sidecar")
            sidecar_value, sidecar_record = _json(sidecar_path, f"{key} sidecar")
            _record_sha(sidecar, sidecar_record["sha256"], f"{key} sidecar")
            report_row = header_rows.get(key)
            if report_row is None or sidecar_value.get("schema") != SIDECAR_SCHEMA:
                raise VerifyFailure(f"{key} sidecar/report row mismatch")
            if sidecar_value.get("status") != report_row.get("status") or sidecar_value.get("source_path") != report_row.get("source_path") or sidecar_value.get("source_sha256") != report_row.get("source_sha256"):
                raise VerifyFailure(f"{key} sidecar does not bind ROOT709 row")
            native_path = _record_path(row.get("native_bi4"), f"{key} native BI4")
            if native_path != _abs(Path(str(report_row["source_path"]))):
                raise VerifyFailure(f"{key} ROOT709 source path differs from manifest native BI4")
            if sidecar_value.get("source_xml_mass_is_not_native") is not True or sidecar_value.get("xml_fallback") is not False:
                raise VerifyFailure(f"{key} sidecar permits XML mass fallback")
            for role in ("generated_xml", "fluid_vtk", "bound_vtk", "native_bi4"):
                _product_stat(row.get(role), f"{key} {role}", waiting)
            native = row.get("native_bi4")
            if isinstance(native, dict) and isinstance(native.get("sha256"), str) and native.get("sha256") != report_row.get("source_sha256"):
                raise VerifyFailure(f"{key} known native product SHA differs from ROOT709")
        except VerifyFailure as exc:
            errors.append(str(exc))
    if errors:
        status = "REJECTED"
    elif waiting:
        status = "WAITING_FOR_PARENT_PRODUCT_SUPPORT_READS"
    else:
        status = "READY_FOR_PARENT_GUARDED_OWNER_GRID_INITIAL_SUPPORT_V2"
    value = {"schema": "ds02.stage2.three-sentinel-owner-grid-initial-support-verifier.v5",
             "status": status, "manifest": manifest_record, "request": request_record,
             "case_count": len(rows), "waiting": waiting, "errors": errors,
             "native_header_rows": {key: {"status": row.get("status"), "massfluid": row.get("massfluid"),
                                           "massbound": row.get("massbound"), "dp": row.get("dp")}
                                     for key, row in header_rows.items()},
             "scientific_scope": {"native_mass": "UNKNOWN", "continuous_owner": "UNKNOWN",
                                  "xml_mass_fallback": False, "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
                                  "scientific_credit": 0}}
    output_path = _abs(output_path)
    if output_path.exists() or output_path.is_symlink():
        raise VerifyFailure(f"refusing to overwrite verifier output: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return value


def _self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="owner-grid-support-v5-verify-") as td:
        root = Path(td)
        base = WORKER.V1._fixture_manifest(root / "base")
        # Reuse the same ROOT709-shaped manufactured lineage as the V2 builder,
        # but run the independent verifier through its public entry point.
        rows = []
        base_value, _ = WORKER._read_json(base, "fixture base")
        for case in base_value["cases"]:
            key = f"{case['sentinel_id']}:{case['grid_label']}"; native = Path(case["native_bi4"]["path"]); stat = _stat(native)
            rows.append({"schema": REPORT_ROW_SCHEMA, "status": UNKNOWN_STATUS, "row_key": key,
                         "source_path": str(native), "source_sha256": _sha(native.read_bytes()),
                         "source_guard": {"pre": {"stat_pre": stat}, "post": {"stat_post": stat}},
                         "massfluid": "UNKNOWN_NOT_EXPOSED_BY_DECODER", "massbound": "UNKNOWN_NOT_EXPOSED_BY_DECODER",
                         "dp": "UNKNOWN_NOT_EXPOSED_BY_DECODER", "time_s": "UNKNOWN_NOT_EXPOSED_BY_DECODER",
                         "role_counts": {"fluid": "UNKNOWN_NOT_EXPOSED_BY_DECODER"},
                         "finite_fields": {"position": "UNKNOWN_NOT_DECODED_BY_HEADER_PROBE", "ids_unique": "UNKNOWN_NOT_DECODED_BY_HEADER_PROBE"},
                         "source_xml_mass_is_not_native": True})
        report = {"schema": REPORT_SCHEMA, "status": REPORT_STATUS, "cases": rows, "xml_fallback": False}
        rp = root / "report.json"; rp.write_text(json.dumps(report, sort_keys=True), encoding="utf-8")
        qp = root / "producer.json"; q = {"schema": "ds02.request.v1", "family_id": "infra", "case_id": "ROOT709_FIXTURE", "attempt_id": "fixture"}; qp.write_text(json.dumps(q, sort_keys=True), encoding="utf-8")
        receipt = {"schema": "ds02.execution-receipt.v1", "status": "completed", "returncode": 0, "request": q, "request_sha256": _sha(qp.read_bytes()), "output_root": str(root)}
        rp2 = root / "receipt.json"; rp2.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")
        proof = {"schema": "ds02.stage2.root-actual-verification.v1", "status": PROOF_STATUS, "report": str(rp), "report_sha256": _sha(rp.read_bytes()), "request": str(qp), "request_sha256": _sha(qp.read_bytes()), "receipt": str(rp2), "receipt_sha256": _sha(rp2.read_bytes()), "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}, "scientific_Q_credit": 0, "H5_BI4_read_by_root": False, "root_native_payload_content_read": False}
        pp = root / "proof.json"; pp.write_text(json.dumps(proof, sort_keys=True), encoding="utf-8")
        built = WORKER.build(base, pp, rp, root / "prepared")
        result = verify(Path(built["manifest"]), Path(built["request"]), root / "verified.json")
        assert result["status"] == "READY_FOR_PARENT_GUARDED_OWNER_GRID_INITIAL_SUPPORT_V2"
        assert result["scientific_scope"]["scientific_credit"] == 0
        sidecar = Path(built["manifest"]).parent / "native-header-sidecars" / "F2-S2__original.json"
        side = json.loads(sidecar.read_text()); side["source_sha256"] = "0" * 64; sidecar.write_text(json.dumps(side))
        bad_result = verify(Path(built["manifest"]), Path(built["request"]), root / "bad.json")
        assert bad_result["status"] == "REJECTED", "tampered sidecar was accepted"
    print("PASS_THREE_SENTINEL_OWNER_GRID_INITIAL_SUPPORT_VERIFY_V5_ROOT709_FIXTURE")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--verify", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            _self_test(); return 0
        if None in (args.manifest, args.request, args.output):
            parser.error("--verify requires --manifest, --request, --output")
        result = verify(args.manifest, args.request, args.output)
        print(json.dumps({"status": result["status"], "output": str(_abs(args.output)),
                          "case_count": result["case_count"], "errors": result["errors"],
                          "waiting_count": len(result["waiting"]), "scientific_credit": 0}, sort_keys=True))
        return 0 if result["status"] != "REJECTED" else 2
    except (VerifyFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_THREE_SENTINEL_OWNER_GRID_INITIAL_SUPPORT_VERIFY_V5: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
