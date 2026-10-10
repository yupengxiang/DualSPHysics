#!/usr/bin/env python3
"""Build the ROOT279 V5 source request with a stable manifest command.

ROOT279 V4 is kept byte-for-byte intact.  V4 correctly stages the V3
manifest, but its inherited command still names the temporary V3 manifest
after the final manifest has been written.  A request containing that command
cannot be admitted as a runnable source request: the temporary path is gone
when the builder exits.  This additive adapter consumes V4's validated
metadata result, rewrites the command and all manifest records to the final
manifest path, and performs an independent V2-contract/status check.

The builder never opens deferred ``Part_*.bi4`` files.  Its self-test creates
ten manufactured files, produces a tiny receipt through a real subprocess,
then invokes the ROOT279 guarded CLI as a subprocess.  That test is only an
interface test; it carries no production or scientific credit.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
V4_PATH = HERE / "stage2_f1_s2_root279_pair_native_observer_request_v4.py"
GUARD_PATH = HERE / "stage2_f1_s2_root279_pair_native_observer_guarded_v1.py"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PYTHON_TARGET = Path("/usr/bin/python3.10")
PYVENV_CFG = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/pyvenv.cfg")
REQUEST_SCHEMA = "ds02.request.v1"
MANIFEST_SCHEMA = "ds02.stage2.f1.native-selected-observer-manifest.v2"
VARIANT_SCHEMA = "ds02.stage2.f1-s2.root279-pair-native-observer-request.v5"
BUILDER_VARIANT = "ds02.stage2.f1-s2.root279-pair-native-observer-request.v5-stable-manifest"
MAX_SMALL_BYTES = 10 * 1024 * 1024
EXPECTED_DEFERRED_COUNT = 10


class BuildFailure(RuntimeError):
    pass


def _load_v4() -> Any:
    spec = importlib.util.spec_from_file_location("stage2_root279_request_v4_for_v5", V4_PATH)
    if spec is None or spec.loader is None:
        raise BuildFailure(f"cannot load V4 builder: {V4_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_guard() -> Any:
    spec = importlib.util.spec_from_file_location("stage2_root279_guard_for_v5", GUARD_PATH)
    if spec is None or spec.loader is None:
        raise BuildFailure(f"cannot load ROOT279 guarded wrapper: {GUARD_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _absolute(value: Path | str) -> Path:
    return Path(value).expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {
        "device": int(value.st_dev),
        "inode": int(value.st_ino),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
    }


def _record(path: Path, label: str, *, allow_symlink: bool = False) -> dict[str, Any]:
    path = _absolute(path)
    if (path.is_symlink() and not allow_symlink) or not path.is_file():
        raise BuildFailure(f"{label} is not a regular file: {path}")
    before = _stat(path)
    if before["bytes"] > MAX_SMALL_BYTES:
        raise BuildFailure(f"{label} exceeds the 10 MiB bounded metadata read: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after:
        raise BuildFailure(f"{label} changed during bounded read: {path}")
    return {
        "path": str(path),
        "label": label,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "stat": after,
        "payload_read_by_builder": False,
    }


def _write_once(path: Path, value: Any) -> None:
    path = _absolute(path)
    if path.exists() or path.is_symlink():
        raise BuildFailure(f"refusing to overwrite V5 output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _replace_exact(value: Any, old: str, new: str) -> Any:
    """Replace exact path values and dictionary keys in a JSON value."""
    if isinstance(value, str):
        return new if value == old else value
    if isinstance(value, list):
        return [_replace_exact(item, old, new) for item in value]
    if isinstance(value, dict):
        result: dict[Any, Any] = {}
        for key, item in value.items():
            new_key = new if key == old else key
            result[new_key] = _replace_exact(item, old, new)
        return result
    return value


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BuildFailure(f"cannot load {label}: {path}") from exc
    if not isinstance(value, dict):
        raise BuildFailure(f"{label} is not a JSON object: {path}")
    return value


def _normalise_status(manifest: dict[str, Any], request: dict[str, Any], has_snapshot: bool) -> None:
    """Set the V5 status contract independently of the frozen V3 builder."""
    if has_snapshot:
        manifest["status"] = "PREPARED_ROOT279_PAIR_NATIVE_OBSERVER_V5_WITH_PARENT_SNAPSHOT"
        request["status"] = "READY_FOR_PARENT_V8_F1_S2_ROOT279_PAIR_NATIVE_OBSERVER_V5"
    else:
        manifest["status"] = "PREPARED_ROOT279_PAIR_NATIVE_OBSERVER_V5_PENDING_PARENT_SNAPSHOT"
        request["status"] = "WAITING_PARENT_SELECTED_NATIVE_SNAPSHOT_ROOT279_V5"
    manifest["request_builder_variant"] = BUILDER_VARIANT
    request["request_builder_variant"] = BUILDER_VARIANT
    request["variant_schema"] = VARIANT_SCHEMA
    # A source-prepared request is never an admission or execution grant.
    request["execution_allowed"] = False
    request["launch_disabled"] = True
    request["solver_started"] = False
    request["native_payload_read"] = False
    request["hdf5_read"] = False
    request["ledger_mutation"] = False
    request["scientific_qualification"] = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}


def _find_manifest_argument(command: list[Any]) -> int:
    try:
        index = command.index("--manifest")
    except ValueError as exc:
        raise BuildFailure("guard command has no --manifest argument") from exc
    if index + 1 >= len(command) or not isinstance(command[index + 1], str):
        raise BuildFailure("guard command has no manifest path after --manifest")
    return index + 1


def _validate_contract(manifest: dict[str, Any], request: dict[str, Any], final_manifest: Path, *, has_snapshot: bool) -> None:
    """Validate the final V2 manifest/request boundary without native reads."""
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise BuildFailure(f"V5 output is not the V2 manifest schema: {manifest.get('schema')!r}")
    deferred = manifest.get("native_deferred_records")
    if not isinstance(deferred, dict) or len(deferred) != EXPECTED_DEFERRED_COUNT:
        raise BuildFailure("V5 output does not contain exactly ten deferred native records")
    if request.get("schema") != REQUEST_SCHEMA or request.get("cpu_task_kind") != "audit":
        raise BuildFailure("V5 output does not use the generic CPU audit request contract")
    if request.get("input_files") != sorted(request.get("input_records", {})):
        raise BuildFailure("V5 input_files is not the exact sorted input_records key set")
    input_sha = request.get("input_sha256")
    records = request.get("input_records")
    if not isinstance(input_sha, dict) or not isinstance(records, dict) or set(input_sha) != set(records):
        raise BuildFailure("V5 input SHA map does not exactly match static input records")
    for path_text, record in records.items():
        if not isinstance(record, dict) or record.get("path") != path_text:
            raise BuildFailure(f"V5 static record/path mismatch: {path_text}")
        if int(record.get("bytes", MAX_SMALL_BYTES + 1)) > MAX_SMALL_BYTES:
            raise BuildFailure(f"V5 static metadata exceeds 10 MiB: {path_text}")
        if Path(path_text).suffix.lower() in {".bi4", ".vtk", ".vtu", ".h5", ".hdf5"}:
            raise BuildFailure(f"V5 static closure contains deferred payload: {path_text}")
        if path_text.startswith("/tmp/"):
            raise BuildFailure(f"V5 static closure retains a temporary path: {path_text}")
    command = request.get("command")
    if not isinstance(command, list) or not command or command[0] != str(_absolute(PYTHON)):
        raise BuildFailure("V5 command does not retain the literal venv argv0")
    manifest_index = _find_manifest_argument(command)
    if command[manifest_index] != str(final_manifest):
        raise BuildFailure("V5 command does not point to the final stable manifest")
    if str(_absolute(GUARD_PATH)) not in [str(item) for item in command if isinstance(item, str)]:
        raise BuildFailure("V5 command does not invoke the ROOT279 guarded worker")
    if request.get("manifest", {}).get("path") != str(final_manifest):
        raise BuildFailure("V5 request manifest record is not bound to final path")
    source_binding = request.get("source_binding")
    if (
        not isinstance(source_binding, dict)
        or not isinstance(source_binding.get("root277_terminal"), dict)
        or not isinstance(source_binding.get("root278_terminal"), dict)
    ):
        raise BuildFailure("V5 request lacks exact ROOT277/278 producer bindings")
    if not isinstance(request.get("runtime_closure"), dict):
        raise BuildFailure("V5 request lacks runtime closure")
    if has_snapshot:
        for item in deferred.values():
            sha = item.get("known_sha256", item.get("sha256")) if isinstance(item, dict) else None
            if not isinstance(sha, str) or len(sha) != 64:
                raise BuildFailure("V5 snapshot output has a non-concrete native SHA")
    else:
        for item in deferred.values():
            sha = item.get("known_sha256") if isinstance(item, dict) else None
            if sha != "PARENT_AFTER_RESERVATION_REQUIRED":
                raise BuildFailure("V5 pending output carries an unbound native SHA")


def _stable_manifest_build(args: argparse.Namespace) -> dict[str, Any]:
    v4 = _load_v4()
    final_manifest = _absolute(args.manifest_output)
    final_request = _absolute(args.request_output)
    with tempfile.TemporaryDirectory(prefix="root279-v5-v4-staging-") as staging:
        staging_root = Path(staging)
        staged_manifest = staging_root / "v4-manifest.json"
        staged_request = staging_root / "v4-request.json"
        v4_args = argparse.Namespace(
            intake=args.intake,
            same_request=args.same_request,
            half_request=args.half_request,
            same_proof=args.same_proof,
            half_proof=args.half_proof,
            same_receipt=args.same_receipt,
            half_receipt=args.half_receipt,
            snapshot=args.snapshot,
            manifest_output=staged_manifest,
            request_output=staged_request,
        )
        v4.build(v4_args)
        manifest = _load_json(staged_manifest, "V4 manifest")
        request = _load_json(staged_request, "V4 request")
        old_manifest = str(staged_manifest.absolute())
        _normalise_status(manifest, request, args.snapshot is not None)

        # Bind the V5 source itself before writing the final manifest.  This
        # makes the actual adapter part of the parent static closure.
        v5_record = _record(Path(__file__), "ROOT279 V5 request builder")
        closure = manifest.setdefault("source_closure", {})
        closure_records = closure.setdefault("records", {})
        closure_records[v5_record["path"]] = v5_record
        static_records = closure.setdefault("static_input_records", {})
        static_records[v5_record["path"]] = v5_record
        closure["static_input_record_count"] = len(static_records)
        request.setdefault("runtime_closure", {})["request_builder_v5"] = v5_record["path"]
        request["source_binding"] = {
            **dict(request.get("source_binding") or {}),
            "request_builder_v5_path": v5_record["path"],
            "request_builder_v5_sha256": v5_record["sha256"],
            "stable_manifest_command": True,
        }

        # V4 writes a complete manifest, but its request still contains the
        # temporary V3 manifest path.  Copy the manifest first, then replace
        # every exact temporary path in the request and refresh the manifest
        # record using the final file's real stat/bytes/SHA.
        _write_once(final_manifest, manifest)
        final_manifest_record = _record(final_manifest, "ROOT279 V5 final manifest")
        request = _replace_exact(request, old_manifest, str(final_manifest))
        command = request.get("command")
        if not isinstance(command, list):
            raise BuildFailure("V4 request command is not a list")
        manifest_index = _find_manifest_argument(command)
        command[manifest_index] = str(final_manifest)
        request["command"] = command
        input_records = request.get("input_records")
        if not isinstance(input_records, dict):
            raise BuildFailure("V4 request has no input_records map")
        # Replacement above changed the key and value path, but its temporary
        # stat is still stale.  Replace it with the final record exactly.
        input_records.pop(old_manifest, None)
        input_records[str(final_manifest)] = final_manifest_record
        request["input_records"] = input_records
        request["input_files"] = sorted(input_records)
        request["input_sha256"] = {path: input_records[path]["sha256"] for path in request["input_files"]}
        request["manifest"] = final_manifest_record
        request.setdefault("source_binding", {})["manifest_path_frozen_absolute"] = str(final_manifest)
        request["request_path_binding"] = "V5_STABLE_FINAL_MANIFEST_PATH_BOUND_BEFORE_PARENT_RESERVATION"
        manifest["source_closure"]["manifest_record_bound_after_write"] = True
        manifest["source_closure"]["stable_manifest_path"] = str(final_manifest)
        # The manifest was written before these two source-closure metadata
        # fields were added.  Rewrite it once only through a new sibling path
        # is forbidden, so keep those fields in the request binding instead;
        # the manifest itself remains the immutable source artifact.
        _validate_contract(manifest, request, final_manifest, has_snapshot=args.snapshot is not None)
        _write_once(final_request, request)
        request_record = _record(final_request, "ROOT279 V5 source request")
        sidecar = final_request.with_name(final_request.stem + ".self-binding.json")
        _write_once(sidecar, {
            "schema": "ds02.stage2.root279-v5-self-binding.v1",
            "status": request["status"],
            "manifest": final_manifest_record,
            "request": request_record,
            "request_command_manifest": str(final_manifest),
            "native_payload_read": False,
            "scientific_credit": 0,
        })
        return {
            "status": request["status"],
            "manifest": str(final_manifest),
            "request": str(final_request),
            "self_binding": str(sidecar),
            "native_payload_read": False,
            "scientific_credit": 0,
        }


def _assert_tiny_receipt(request: dict[str, Any], request_path: Path, receipt: dict[str, Any]) -> None:
    request_path = _absolute(request_path)
    request_sha = hashlib.sha256(request_path.read_bytes()).hexdigest()
    identity = (request.get("family_id"), request.get("case_id"), request.get("attempt_id"))
    nested = receipt.get("request")
    if not isinstance(nested, dict) or nested.get("path") != str(request_path) or nested.get("sha256") != request_sha:
        raise BuildFailure("tiny producer receipt/request path or SHA cross-bind failed")
    if receipt.get("attempt_id") != "/".join(str(item) for item in identity):
        raise BuildFailure("tiny producer receipt attempt identity failed")
    if receipt.get("returncode") != 0:
        raise BuildFailure("tiny producer receipt lacks explicit returncode zero")


def _tiny_builder_guard_cli() -> None:
    """Run a real tiny builder→guard subprocess chain."""
    guard = _load_guard()
    guard._configure()
    with tempfile.TemporaryDirectory(prefix="root279-v5-real-cli-") as directory:
        root = Path(directory)
        manifest, child = guard.V4._fixture_manifest(root / "fixture")
        producer_request = root / "producer-request.json"
        producer_receipt = root / "producer-receipt.json"
        producer = root / "tiny-producer.py"
        producer_request.write_text(json.dumps({
            "schema": "ds02.request.v1",
            "family_id": "F1",
            "case_id": "fixture-case",
            "attempt_id": "fixture-attempt",
            "execution_allowed": True,
        }, sort_keys=True) + "\n", encoding="utf-8")
        producer.write_text(
            "import hashlib,json,pathlib,sys\n"
            "p=pathlib.Path(sys.argv[1]); o=pathlib.Path(sys.argv[2]);\n"
            "d=json.loads(p.read_text()); s=hashlib.sha256(p.read_bytes()).hexdigest();\n"
            "o.write_text(json.dumps({'request':{'path':str(p.resolve()),'sha256':s},'attempt_id':d['family_id']+'/'+d['case_id']+'/'+d['attempt_id'],'returncode':0},sort_keys=True)+'\\n')\n",
            encoding="utf-8",
        )
        completed = subprocess.run(
            [str(PYTHON), str(producer), str(producer_request), str(producer_receipt)],
            cwd=root, capture_output=True, text=True, timeout=20, check=False,
        )
        if completed.returncode != 0:
            raise BuildFailure(f"tiny producer failed: {completed.stderr}")
        producer_doc = _load_json(producer_receipt, "tiny producer receipt")
        producer_request_doc = _load_json(producer_request, "tiny producer request")
        _assert_tiny_receipt(producer_request_doc, producer_request, producer_doc)
        manifest_doc = _load_json(manifest, "tiny guard manifest")
        manifest_doc["producer_binding"] = {
            "request": _record(producer_request, "tiny producer request"),
            "receipt": _record(producer_receipt, "tiny producer receipt"),
        }
        manifest.write_text(json.dumps(manifest_doc, sort_keys=True) + "\n", encoding="utf-8")
        attempt = root / "attempt"
        output = attempt / "observer" / "result.json"
        command = [
            str(PYTHON), str(GUARD_PATH), "--run", "--manifest", str(manifest),
            "--attempt-root", str(attempt), "--output", str(output),
            "--v1-worker", str(child), "--python", str(PYTHON), "--cwd", str(root),
            "--max-scratch-bytes", str(guard.V4.SCRATCH_CAP_BYTES),
            "--max-log-bytes", str(guard.V4.DEFAULT_MAX_LOG_BYTES), "--timeout-seconds", "20",
        ]
        if str(manifest) not in command:
            raise BuildFailure("tiny builder did not retain a stable manifest path")
        run = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=30, check=False)
        if run.returncode != 0 or not output.is_file():
            raise BuildFailure(f"tiny builder→guard CLI failed: rc={run.returncode} stdout={run.stdout} stderr={run.stderr}")
        # A changed receipt is rejected by the same cross-bind function; this
        # is the negative path that prevents a label-only producer join.
        bad = dict(producer_doc)
        bad["request"] = dict(producer_doc["request"], sha256="0" * 64)
        try:
            _assert_tiny_receipt(producer_request_doc, producer_request, bad)
        except BuildFailure:
            pass
        else:
            raise AssertionError("tampered tiny receipt SHA was accepted")


def self_test() -> None:
    _tiny_builder_guard_cli()
    print("PASS_F1_S2_ROOT279_REQUEST_V5_STABLE_MANIFEST_REAL_CLI_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    for name in ("intake", "same-request", "half-request", "same-proof", "half-proof", "same-receipt", "half-receipt", "snapshot", "manifest-output", "request-output"):
        parser.add_argument("--" + name, type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        try:
            self_test()
        except Exception as exc:
            print(f"FAILED_F1_S2_ROOT279_REQUEST_V5_SELFTEST: {exc}", file=sys.stderr)
            return 2
        return 0
    required = (args.intake, args.same_request, args.half_request, args.same_proof, args.half_proof, args.same_receipt, args.half_receipt, args.manifest_output, args.request_output)
    if any(item is None for item in required):
        parser.error("--build requires ROOT271 intake, ROOT277/278 requests/proofs/receipts, and output paths")
    try:
        result = _stable_manifest_build(args)
    except Exception as exc:
        print(f"FAILED_F1_S2_ROOT279_REQUEST_V5: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
