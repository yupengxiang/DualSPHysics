#!/usr/bin/env python3
"""Independently verify the actual nine-product post-GenCase handoff.

The verifier consumes only bounded JSON metadata and filesystem stat records.
It re-joins each product-map row to the raw producer request, execution
receipt, and terminal proof.  It then checks the V3 package's direct manifest
operands and the row/product identities emitted for the header and support
stages.  Product XML, VTK, and BI4 bytes are never opened or hashed here;
their parent-after-reservation SHA remains a separate gate.

``READY_FOR_PARENT_GUARDED_CHAIN`` means that the metadata edges are closed
and the parent may perform the deferred product/header/support reads.  It is
not a scientific qualification and does not imply that native header or
initial support has passed.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
V3_PATH = HERE / "stage2_three_sentinel_owner_grid_post_gencase_chain_v3.py"
JSON_CAP = 10 * 1024 * 1024
MAP_SCHEMA_PREFIX = "ds02.stage2.three-sentinel.owner-grid-gencase-product-map"
PACKAGE_SCHEMA = "ds02.stage2.three-sentinel.owner-grid-post-gencase-chain-package.v3"
REQUEST_SCHEMA = "ds02.request.v1"
TARGETS = ("F2-S2", "F3-S1", "F5-S1")
GRIDS = ("original", "coarse", "fine")
EXPECTED_KEYS = {f"{sid}:{grid}" for sid in TARGETS for grid in GRIDS}
PRODUCT_ROLES = ("generated_xml", "fluid_vtk", "bound_vtk", "native_bi4")
UNKNOWN = "UNKNOWN"


class VerifyFailure(RuntimeError):
    pass


def _load_v3() -> Any:
    spec = importlib.util.spec_from_file_location("post_gencase_chain_v3_for_verify", V3_PATH)
    if spec is None or spec.loader is None:
        raise VerifyFailure(f"cannot load V3 fixture builder: {V3_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V3 = _load_v3()


def _abs(value: Path | str) -> Path:
    return Path(value).expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino),
            "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns),
            "ctime_ns": int(value.st_ctime_ns)}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json(path: Path | str, label: str) -> tuple[dict[str, Any], str, dict[str, int]]:
    path = _abs(path)
    if path.is_symlink() or not path.is_file():
        raise VerifyFailure(f"{label} is not a regular non-symlink file: {path}")
    before = _stat(path)
    if before["bytes"] > JSON_CAP:
        raise VerifyFailure(f"{label} exceeds the 10 MiB metadata cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after:
        raise VerifyFailure(f"{label} changed during bounded read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerifyFailure(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise VerifyFailure(f"{label} is not an object")
    return value, _sha(raw), after


def _record_path(value: Any, label: str) -> Path:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise VerifyFailure(f"{label} lacks a path record")
    return _abs(value["path"])


def _record_sha(value: Any, label: str) -> str | None:
    if not isinstance(value, dict):
        raise VerifyFailure(f"{label} lacks a record")
    sha = value.get("sha256")
    if sha is None:
        return None
    if not isinstance(sha, str) or len(sha) != 64:
        raise VerifyFailure(f"{label} has a malformed SHA")
    try:
        int(sha, 16)
    except ValueError as exc:
        raise VerifyFailure(f"{label} has a malformed SHA") from exc
    return sha.lower()


def _key(row: dict[str, Any]) -> str:
    return f"{row.get('sentinel_id')}:{row.get('grid_label')}"


def _check_stat_declared(path: Path, declared: Any, label: str, waiting: list[str], errors: list[str]) -> None:
    """Compare stat-only product declarations without opening product bytes."""
    if not path.is_file() or path.is_symlink():
        waiting.append(f"{label} product is absent")
        return
    if not isinstance(declared, dict):
        return
    expected = declared.get("stat")
    if not isinstance(expected, dict):
        return
    actual = _stat(path)
    for target, aliases in {
        "device": ("device", "st_dev"), "inode": ("inode", "st_ino"),
        "bytes": ("bytes", "size"), "mtime_ns": ("mtime_ns",),
        "ctime_ns": ("ctime_ns",),
    }.items():
        known = next((expected[name] for name in aliases if name in expected), None)
        if known is not None and int(known) != actual[target]:
            errors.append(f"{label} stat {target} differs from product map")


def _verify_producer_row(row: dict[str, Any], errors: list[str], waiting: list[str]) -> dict[str, Any]:
    key = _key(row)
    proof_ref = row.get("actual_producer_proof") or row.get("actual_proof") or row.get("producer_proof")
    request_ref = row.get("producer_request")
    receipt_ref = row.get("gencase_receipt") or row.get("actual_producer_receipt") or row.get("producer_receipt")
    if not isinstance(proof_ref, dict) or not isinstance(request_ref, dict):
        errors.append(f"{key} lacks proof/request map edges")
        return {"key": key, "status": "REJECTED"}
    try:
        proof_path = _record_path(proof_ref, f"{key} proof")
        request_path = _record_path(request_ref, f"{key} request")
        proof, proof_sha, _ = _json(proof_path, f"{key} terminal proof")
        request, request_sha, _ = _json(request_path, f"{key} producer request")
        if not isinstance(receipt_ref, dict):
            products = proof.get("products")
            if isinstance(products, dict):
                receipt_ref = products.get("gencase_receipt")
        receipt_path = _record_path(receipt_ref, f"{key} receipt")
        receipt, receipt_sha, _ = _json(receipt_path, f"{key} execution receipt")
    except VerifyFailure as exc:
        errors.append(str(exc))
        return {"key": key, "status": "REJECTED"}
    declared = _record_sha(proof_ref, f"{key} proof")
    if declared is not None and declared != proof_sha.lower():
        errors.append(f"{key} proof SHA differs from map")
    status = str(proof.get("status") or "").upper()
    if "FAIL" in status:
        errors.append(f"{key} terminal proof is failed: {proof.get('status')!r}")
    elif not status.startswith("VERIFIED_ACTUAL") and "COMPLETED" not in status:
        waiting.append(f"{key} terminal proof is not a completed actual proof")
    if proof.get("request") != str(request_path):
        errors.append(f"{key} proof request path differs from map request")
    if proof.get("receipt") != str(receipt_path):
        errors.append(f"{key} proof receipt path differs from map receipt")
    if proof.get("request_sha256") != request_sha:
        errors.append(f"{key} proof request SHA does not bind request bytes")
    if proof.get("receipt_sha256") != receipt_sha:
        errors.append(f"{key} proof receipt SHA does not bind receipt bytes")
    if request.get("schema") != REQUEST_SCHEMA:
        errors.append(f"{key} producer request schema mismatch")
    identity = {
        "family_id": row.get("family_id"), "case_id": row.get("case_id"),
        "attempt_id": row.get("attempt_id"), "physical_case_id": row.get("physical_case_id"),
    }
    for field, expected in identity.items():
        if request.get(field) != expected:
            errors.append(f"{key} request {field} does not bind product-map identity")
    if request.get("sentinel_id") is not None and request.get("sentinel_id") != row.get("sentinel_id"):
        errors.append(f"{key} request sentinel_id mismatch")
    if request.get("grid_label") is not None and request.get("grid_label") != row.get("grid_label"):
        errors.append(f"{key} request grid_label mismatch")
    if receipt.get("schema") != "ds02.execution-receipt.v1":
        errors.append(f"{key} receipt schema mismatch")
    receipt_status = str(receipt.get("status") or "")
    if not (receipt_status == "completed" or receipt_status.upper().startswith("COMPLETED")) or receipt.get("returncode") != 0:
        if receipt.get("status") in (None, "", "running", "pending"):
            waiting.append(f"{key} receipt is not terminal completed")
        else:
            errors.append(f"{key} receipt status/returncode is not completed/0")
    if receipt.get("request") != request:
        errors.append(f"{key} receipt.request differs from raw request document")
    if receipt.get("request_sha256") != request_sha:
        errors.append(f"{key} receipt.request_sha256 does not bind request bytes")
    if receipt.get("output_root") != str(receipt_path.parent):
        errors.append(f"{key} receipt output_root differs from receipt parent")
    # Product paths are stat-only.  A known product SHA is intentionally not
    # recomputed before the parent reservation; the parent owns that deferred
    # post-GenCase content hash.
    package_products = row.get("products") if isinstance(row.get("products"), dict) else {}
    for role in ("generated_xml", "fluid_vtk", "bound_vtk", "native_bi4"):
        record = row.get(role) or package_products.get(role)
        if isinstance(record, dict) and isinstance(record.get("path"), str):
            _check_stat_declared(_abs(record["path"]), record, f"{key} {role}", waiting, errors)
        else:
            waiting.append(f"{key} {role} product record is absent")
    return {"key": key, "status": "PASS" if not errors else "REJECTED",
            "proof_sha256": proof_sha, "request_sha256": request_sha,
            "receipt_sha256": receipt_sha, "identity": identity}


def _verify_stage(package: dict[str, Any], stage: str, errors: list[str], waiting: list[str]) -> None:
    entry = package.get(stage)
    if not isinstance(entry, dict):
        errors.append(f"package lacks {stage} entry")
        return
    manifest_ref = entry.get("manifest")
    request_ref = entry.get("request")
    try:
        manifest_path = _record_path(manifest_ref, f"package {stage} manifest")
        request_path = _record_path(request_ref, f"package {stage} request")
        manifest, manifest_sha, _ = _json(manifest_path, f"{stage} manifest")
        request, request_sha, _ = _json(request_path, f"{stage} request")
    except VerifyFailure as exc:
        errors.append(str(exc)); return
    if _record_sha(manifest_ref, f"package {stage} manifest") not in (None, manifest_sha.lower()):
        errors.append(f"package {stage} manifest SHA is stale")
    if _record_sha(request_ref, f"package {stage} request") not in (None, request_sha.lower()):
        errors.append(f"package {stage} request SHA is stale")
    if request.get("schema") != REQUEST_SCHEMA:
        errors.append(f"{stage} request schema mismatch")
    if request.get("execution_allowed") is not False or request.get("launch_disabled") is not True:
        errors.append(f"{stage} request is not launch-disabled")
    command = request.get("command")
    if not isinstance(command, list) or "--manifest" not in command:
        errors.append(f"{stage} request lacks --manifest command")
    else:
        operand = command[command.index("--manifest") + 1] if command.index("--manifest") + 1 < len(command) else ""
        if not isinstance(operand, str) or operand.startswith("{attempt_root}"):
            errors.append(f"{stage} request still relies on runtime manifest materialization")
        elif operand != str(manifest_path):
            errors.append(f"{stage} command manifest path differs from package manifest")
    if request.get("manifest", {}).get("path") != str(manifest_path):
        errors.append(f"{stage} request manifest record differs from package manifest")
    records = request.get("input_records")
    if not isinstance(records, dict) or str(manifest_path) not in records:
        errors.append(f"{stage} manifest is absent from request input_records")
    elif records[str(manifest_path)].get("sha256") != manifest_sha:
        errors.append(f"{stage} manifest input record SHA is stale")
    if manifest.get("cases") is None or not isinstance(manifest.get("cases"), list) or len(manifest["cases"]) != 9:
        errors.append(f"{stage} manifest does not contain exactly nine cases")
    status = str(manifest.get("status") or "")
    if status.startswith("WAITING") or status.startswith("REJECTED"):
        waiting.append(f"{stage} manifest status is {status or 'missing'}")
    elif not status.startswith("READY"):
        errors.append(f"{stage} manifest has unsupported status {status!r}")


def verify(product_map_path: Path, package_path: Path) -> dict[str, Any]:
    product_map, map_sha, _ = _json(product_map_path, "actual product map")
    package, package_sha, _ = _json(package_path, "post-GenCase V3 package")
    errors: list[str] = []
    waiting: list[str] = []
    if not str(product_map.get("schema", "")).startswith(MAP_SCHEMA_PREFIX):
        errors.append("product-map schema mismatch")
    if package.get("schema") != PACKAGE_SCHEMA:
        errors.append("post-GenCase package schema mismatch")
    if package.get("execution_allowed") is not False or package.get("scientific_credit") != 0:
        errors.append("package is not execution-disabled/zero-credit")
    rows = product_map.get("products", product_map.get("cases"))
    if not isinstance(rows, list):
        errors.append("product map lacks products list")
        rows = []
    keys = [_key(row) for row in rows if isinstance(row, dict)]
    if len(keys) != len(rows) or len(keys) != len(set(keys)) or set(keys) != EXPECTED_KEYS:
        errors.append(f"product map does not contain exact nine rows: {sorted(set(keys))}")
    producer_results = []
    for row in rows:
        if isinstance(row, dict) and _key(row) in EXPECTED_KEYS:
            producer_results.append(_verify_producer_row(row, errors, waiting))
    chain_ref = package.get("chain_manifest")
    try:
        chain_path = _record_path(chain_ref, "package chain manifest")
        chain, chain_sha, _ = _json(chain_path, "chain manifest")
    except VerifyFailure as exc:
        errors.append(str(exc)); chain = {}; chain_sha = ""
    if isinstance(chain_ref, dict) and chain_ref.get("sha256") not in (None, chain_sha):
        errors.append("chain manifest SHA is stale")
    chain_rows = chain.get("rows") if isinstance(chain, dict) else None
    if not isinstance(chain_rows, list) or len(chain_rows) != 9:
        errors.append("chain manifest does not contain exactly nine rows")
    else:
        product_by_key = {str(row.get("row_key")): row for row in chain_rows if isinstance(row, dict)}
        if set(product_by_key) != EXPECTED_KEYS:
            errors.append("chain manifest row key set differs from product map")
        map_by_key = {_key(row): row for row in rows if isinstance(row, dict)}
        for key in EXPECTED_KEYS & set(product_by_key) & set(map_by_key):
            chain_row = product_by_key[key]; map_row = map_by_key[key]
            for field in ("sentinel_id", "grid_label", "family_id", "physical_case_id", "case_id", "attempt_id"):
                if chain_row.get(field) != map_row.get(field):
                    errors.append(f"{key} chain {field} differs from product map")
            if chain_row.get("edge_status") != "VERIFIED_COMPLETED_PRODUCER_EDGE":
                waiting.append(f"{key} chain edge status is {chain_row.get('edge_status')!r}")
    _verify_stage(package, "native_header", errors, waiting)
    _verify_stage(package, "initial_support", errors, waiting)
    calibration = package.get("calibration")
    if not isinstance(calibration, list) or {item.get("sentinel_id") for item in calibration if isinstance(item, dict)} != set(TARGETS):
        errors.append("calibration package does not contain exact three sentinels")
    else:
        for item in calibration:
            if isinstance(item, dict):
                stage_entry = {"manifest": item.get("manifest"), "request": item.get("request")}
                temp = dict(package); temp["calibration_stage"] = stage_entry
                # Reuse the same direct-manifest checks without imposing the
                # nine-case list on each per-sentinel calibration manifest.
                request_ref = item.get("request")
                manifest_ref = item.get("manifest")
                try:
                    mp = _record_path(manifest_ref, f"{item.get('sentinel_id')} calibration manifest")
                    rp = _record_path(request_ref, f"{item.get('sentinel_id')} calibration request")
                    manifest, msha, _ = _json(mp, "calibration manifest")
                    request, rsha, _ = _json(rp, "calibration request")
                    command = request.get("command")
                    if not isinstance(command, list) or "--manifest" not in command or command[command.index("--manifest") + 1] != str(mp):
                        errors.append(f"{item.get('sentinel_id')} calibration command does not bind direct manifest")
                    if request.get("execution_allowed") is not False or request.get("launch_disabled") is not True:
                        errors.append(f"{item.get('sentinel_id')} calibration request is not disabled")
                    if request.get("manifest", {}).get("path") != str(mp) or request.get("manifest", {}).get("sha256") != msha:
                        errors.append(f"{item.get('sentinel_id')} calibration manifest binding is stale")
                    if str(manifest.get("status") or "").startswith("WAITING"):
                        waiting.append(f"{item.get('sentinel_id')} calibration is waiting for upstream reports")
                except VerifyFailure as exc:
                    errors.append(str(exc))
    state = "REJECTED" if errors else ("WAITING" if waiting else "READY_FOR_PARENT_GUARDED_CHAIN")
    return {"schema": "ds02.stage2.three-sentinel.owner-grid-post-gencase-chain-verifier.v1",
            "status": state, "ready": state == "READY_FOR_PARENT_GUARDED_CHAIN",
            "product_map_sha256": map_sha, "package_sha256": package_sha,
            "producer_rows": producer_results, "errors": errors, "waiting": waiting,
            "payload_read": False, "deferred_product_content_hashed": False,
            "scientific_qualification": {"QI": UNKNOWN, "QN": UNKNOWN, "QE": UNKNOWN, "scientific_credit": 0},
            "scope": "metadata_identity_and_runtime_manifest_binding_only"}


def _self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="post-gencase-chain-verifier-") as td:
        root = Path(td)
        product_map = V3.V2._fixture_map(root)
        package = V3.build(product_map, root / "out")["package"]
        result = verify(product_map, Path(package))
        assert result["status"] == "WAITING", result
        assert not result["errors"], result
        # Tampering a proof's raw bytes is a hard identity error, even though
        # all products and stage manifests remain present.
        rows = json.loads(product_map.read_text())
        proof_path = Path(rows["products"][0]["actual_producer_proof"]["path"])
        proof = json.loads(proof_path.read_text()); proof["status"] = "VERIFIED_ACTUAL_TAMPERED"
        proof_path.write_text(json.dumps(proof, sort_keys=True) + "\n")
        bad = verify(product_map, Path(package))
        assert bad["status"] == "REJECTED", bad
        assert any("proof SHA" in item for item in bad["errors"])
    print("PASS_POST_GENCASE_CHAIN_VERIFIER_V1_METADATA_FIXTURE")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--verify", action="store_true")
    parser.add_argument("--product-map", type=Path)
    parser.add_argument("--package", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            _self_test(); return 0
        if args.product_map is None or args.package is None:
            parser.error("--verify requires --product-map and --package")
        result = verify(args.product_map, args.package)
        raw = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.output is not None:
            path = _abs(args.output)
            if path.exists() or path.is_symlink():
                raise VerifyFailure(f"refusing overwrite: {path}")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(raw, encoding="utf-8")
        print(json.dumps({"status": result["status"], "ready": result["ready"],
                          "errors": len(result["errors"]), "waiting": len(result["waiting"]),
                          "scientific_credit": 0, "payload_read": False}, sort_keys=True))
        return 0 if result["status"] != "REJECTED" else 2
    except (VerifyFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"REJECTED_POST_GENCASE_CHAIN_VERIFIER_V1: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
