#!/usr/bin/env python3
"""Build the additive ROOT279/ROOT310 source closure envelope (V4).

The consumed ROOT279 V3 builder remains the producer of the observer manifest
and request schema.  This wrapper adds the *actual* local Python import
closure, decoder/config records, and an explicit bounded resource envelope to
that request.  It never reads a deferred ``Part_*.bi4`` payload.  A concrete
ROOT310 snapshot is accepted only through the V3 builder's existing
post-reservation records; before that point the request remains pending and
scientific credit is zero.

The wrapper intentionally keeps ``variant_schema`` at the frozen V3 value so
the existing guarded observer and independent verifier can consume the
request.  ``request_builder_variant`` and ``runtime_closure`` identify this
additive envelope.  No production request is overwritten.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable


HERE = Path(__file__).resolve().parent
V3_PATH = HERE / "stage2_f1_s2_root279_pair_native_observer_request_v3.py"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PYTHON_TARGET = Path("/usr/bin/python3.10")
PYVENV_CFG = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/pyvenv.cfg")
MAX_SMALL_BYTES = 16 * 1024 * 1024
MAX_CLOSURE_FILES = 128
MAX_LOG_BYTES = 1 * 1024 * 1024
MAX_SCRATCH_BYTES = 256 * 1024 * 1024
REQUEST_BUILDER_VARIANT = "ds02.stage2.f1-s2.root279-pair-native-observer-request.v4-closure-envelope"


class BuildFailure(RuntimeError):
    pass


def _absolute(path: Path | str) -> Path:
    return Path(path).expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {
        "device": int(value.st_dev),
        "inode": int(value.st_ino),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
    }


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _record(path: Path, label: str) -> dict[str, Any]:
    path = _absolute(path)
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not a regular file: {path}")
    before = _stat(path)
    if before["bytes"] > MAX_SMALL_BYTES:
        raise BuildFailure(f"{label} exceeds bounded source read: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after:
        raise BuildFailure(f"{label} changed during bounded read: {path}")
    return {
        "path": str(path),
        "label": label,
        "bytes": len(raw),
        "sha256": _sha_bytes(raw),
        "stat": after,
        "payload_read_by_builder": False,
    }


def _record_literal_python(path: Path) -> dict[str, Any]:
    """Record the literal venv argv0 plus its resolved executable evidence."""
    path = _absolute(path)
    if not path.is_symlink():
        raise BuildFailure(f"literal venv argv0 is not a symlink: {path}")
    target = path.resolve(strict=True)
    if target.is_symlink() or not target.is_file():
        raise BuildFailure(f"literal venv target is not a regular file: {target}")
    link_before = _stat(path)
    target_record = _record(target, "resolved venv interpreter")
    link_after = _stat(path)
    if link_before != link_after:
        raise BuildFailure("literal venv symlink changed during closure read")
    return {
        **target_record,
        "path": str(path),
        "label": "literal venv argv0",
        "literal_argv0": True,
        "resolved_target": str(target),
        "symlink_stat": link_after,
        "resolved_target_record": target_record,
        "payload_read_by_builder": False,
    }


def _module_name_candidates(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def _resolve_local_imports(path: Path, roots: tuple[Path, ...], seen: set[Path]) -> set[Path]:
    """Resolve only local sibling/module imports; never walk site-packages."""
    path = _absolute(path)
    if path in seen:
        return set()
    seen.add(path)
    try:
        raw = path.read_bytes()
        if len(raw) > MAX_SMALL_BYTES:
            raise BuildFailure(f"Python closure file exceeds bounded read: {path}")
        tree = ast.parse(raw.decode("utf-8"), filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        raise BuildFailure(f"cannot parse local import closure {path}") from exc
    result = {path}
    for module in _module_name_candidates(tree):
        for root in roots:
            candidates = (root / f"{module}.py", root / module / "__init__.py")
            candidate = next((item for item in candidates if item.is_file() and not item.is_symlink()), None)
            if candidate is not None:
                result.update(_resolve_local_imports(candidate, roots, seen))
                break
    if len(result) > MAX_CLOSURE_FILES:
        raise BuildFailure("local import closure exceeds bounded file count")
    return result


def _closure_records(entry_points: Iterable[Path]) -> dict[str, dict[str, Any]]:
    entries = tuple(_absolute(item) for item in entry_points)
    roots = tuple(dict.fromkeys([HERE, *[item.parent for item in entries]]))
    closure: set[Path] = set()
    for entry in entries:
        closure.update(_resolve_local_imports(entry, roots, set()))
    records: dict[str, dict[str, Any]] = {}
    for path in sorted(closure, key=str):
        records[str(path)] = _record(path, f"ROOT279 local import closure: {path.name}")
    return records


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location("stage2_root279_v3_builder_for_v4", V3_PATH)
    if spec is None or spec.loader is None:
        raise BuildFailure(f"cannot import frozen ROOT279 V3 builder: {V3_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _terminal_request_path(proof_path: Path, source_request_path: Path, mode: str) -> Path:
    """Resolve the actual root-forward request named by a terminal proof.

    ROOT277/278 were launched from root-forward external-V5 requests.  The
    source-prepared ROOT271 requests remain useful lineage, but their paths
    are not the request identity in the terminal receipt.  Require the proof
    to name an existing exact request file and verify its bytes before passing
    it to the frozen V3 builder.  This prevents a label or latest-file
    fallback from silently replacing the producer.
    """
    proof_path = _absolute(proof_path)
    source_request_path = _absolute(source_request_path)
    raw = proof_path.read_bytes()
    try:
        proof = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BuildFailure(f"{mode} terminal proof is not JSON") from exc
    actual = proof.get("request")
    actual_sha = proof.get("request_sha256")
    if not isinstance(actual, str) or not isinstance(actual_sha, str) or len(actual_sha) != 64:
        raise BuildFailure(f"{mode} proof lacks exact terminal request path/SHA")
    actual_path = _absolute(actual)
    if not actual_path.is_file() or actual_path.is_symlink():
        raise BuildFailure(f"{mode} proof terminal request is unavailable: {actual_path}")
    actual_raw = actual_path.read_bytes()
    if _sha_bytes(actual_raw) != actual_sha:
        raise BuildFailure(f"{mode} proof terminal request SHA does not match file bytes")
    # A terminal request may differ from the source-prepared request, but the
    # source request must remain present in the actual request's input map or
    # explicit canonical lineage.  Do not accept an unrelated replacement.
    actual_doc = json.loads(actual_raw.decode("utf-8"))
    input_files = actual_doc.get("input_files") if isinstance(actual_doc, dict) else None
    source_path_text = str(source_request_path)
    lineage = actual_doc.get("root_forward_provenance") if isinstance(actual_doc, dict) else None
    lineage_text = json.dumps(lineage, sort_keys=True) if lineage is not None else ""
    if not (isinstance(input_files, list) and source_path_text in input_files) and source_path_text not in lineage_text:
        raise BuildFailure(f"{mode} terminal request does not retain source-prepared request lineage")
    return actual_path


def _write_once(path: Path, value: Any) -> None:
    path = _absolute(path)
    if path.exists() or path.is_symlink():
        raise BuildFailure(f"refusing to overwrite immutable V4 output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _augment_request(request: dict[str, Any], manifest: dict[str, Any], closure: dict[str, dict[str, Any]],
                     manifest_record: dict[str, Any], runtime_records: dict[str, dict[str, Any]],
                     staged_manifest_path: str) -> tuple[dict[str, Any], dict[str, Any]]:
    static = dict(request.get("input_records") or {})
    # V3 built against a temporary manifest.  Do not carry that path into the
    # final request; the final manifest record is inserted below with its
    # actual immutable output SHA/stat.
    static.pop(staged_manifest_path, None)
    static.update(closure)
    static.update(runtime_records)
    static[manifest_record["path"]] = manifest_record
    input_files = sorted(static)
    # Keep the local-import closure and the complete parent static-input
    # closure distinct.  The former proves the Python import graph; the
    # latter is what the guarded command actually needs (decoder, observer,
    # contract, terminal receipts, RunPARTs, and XML/code records).  Earlier
    # V4 drafts exposed only ``records=closure`` and therefore made a valid
    # request look incomplete to a parent admission checker even though all
    # of those records were already in input_records.
    static_runtime_records = {
        path: record for path, record in static.items()
        if path != str(_absolute(staged_manifest_path))
        and path != manifest_record["path"]
    }
    request["request_builder_variant"] = REQUEST_BUILDER_VARIANT
    request["input_files"] = input_files
    request["input_records"] = static
    request["input_sha256"] = {path: static[path]["sha256"] for path in input_files}
    request["runtime_closure"] = {
        "closure_schema": "ds02.stage2.local-python-import-closure.v1",
        "complete_local_import_closure": True,
        "entry_points": [str(_absolute(V3_PATH)), str(_absolute(request.get("command", [])[1]))] if isinstance(request.get("command"), list) and len(request["command"]) > 1 else [str(_absolute(V3_PATH))],
        "records": closure,
        "static_input_records": static_runtime_records,
        "static_input_record_count": len(static_runtime_records),
        "static_input_record_paths": sorted(static_runtime_records),
        "manifest_record_bound_after_write": True,
        "literal_venv": {
            "argv0": str(_absolute(PYTHON)),
            "resolved_target": str(PYTHON.resolve(strict=True)),
            "pyvenv_cfg": str(_absolute(PYVENV_CFG)),
        },
        "deferred_sha_stat_gate": "PARENT_AFTER_RESERVATION_AND_AFTER_CHILD_DECODE",
        "deferred_payloads_read_by_builder": False,
    }
    request["resource_guard"] = {
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 1800,
        "max_memory_bytes": 2 * 1024 * 1024 * 1024,
        "max_scratch_bytes": MAX_SCRATCH_BYTES,
        "max_log_bytes": MAX_LOG_BYTES,
        "estimated_storage_bytes": 128 * 1024 * 1024,
        "estimated_native_read_passes": 4,
        "estimated_native_read_bytes_scope": "ten selected Part files; concrete bytes only after ROOT310 snapshot",
        "full_native_tree_scan": False,
        "gpu": "none",
    }
    request["source_binding"] = {
        **dict(request.get("source_binding") or {}),
        "request_builder_v4_closure_sha": closure[str(_absolute(__file__))]["sha256"],
        "root310_snapshot": "PARENT_AFTER_RESERVATION_REQUIRED_UNTIL_ROOT310_TERMINAL",
        "root279_producer_pair": "ROOT277/ROOT278 exact request/proof/receipt joins retained from V3",
        "native_mass_source": "decoder/header only; XML fallback forbidden",
        "world_axis": "UNKNOWN",
    }
    manifest["request_builder_variant"] = REQUEST_BUILDER_VARIANT
    manifest["source_closure"] = {
        "schema": "ds02.stage2.local-python-import-closure.v1",
        "records": closure,
        "static_input_records": static_runtime_records,
        "static_input_record_count": len(static_runtime_records),
        "complete_local_import_closure": True,
        "deferred_native_payload_read": False,
    }
    manifest["resource_guard"] = request["resource_guard"]
    manifest["scientific_qualification"] = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}
    request["request_path_binding"] = "ROOT_NORMALIZER_MUST_REBIND_ACTUAL_REQUEST_PATH_BEFORE_PARENT_RESERVATION"
    return manifest, request


def build(args: argparse.Namespace) -> dict[str, Any]:
    v3 = _load_module()
    same_actual_request = _terminal_request_path(args.same_proof, args.same_request, "same_cfl")
    half_actual_request = _terminal_request_path(args.half_proof, args.half_request, "half_cfl")
    with tempfile.TemporaryDirectory(prefix="root279-v4-v3-staging-") as staging:
        staging_root = Path(staging)
        v3_manifest = staging_root / "root279-v3-manifest.json"
        v3_request = staging_root / "root279-v3-request.json"
        v3_args = argparse.Namespace(
            intake=args.intake,
            same_request=same_actual_request,
            half_request=half_actual_request,
            same_proof=args.same_proof,
            half_proof=args.half_proof,
            same_receipt=args.same_receipt,
            half_receipt=args.half_receipt,
            snapshot=args.snapshot,
            manifest_output=v3_manifest,
            request_output=v3_request,
        )
        manifest, request = v3.build(v3_args)
        # Preserve the source-prepared ROOT271 request paths as explicit
        # lineage even though the strict terminal joins use root-forward
        # producer requests.
        request["source_prepared_lineage"] = {
            "same_cfl": {"path": str(_absolute(args.same_request)), "sha256": _sha_bytes(_absolute(args.same_request).read_bytes())},
            "half_cfl": {"path": str(_absolute(args.half_request)), "sha256": _sha_bytes(_absolute(args.half_request).read_bytes())},
            "actual_terminal_requests": {"same_cfl": str(same_actual_request), "half_cfl": str(half_actual_request)},
            "join_policy": "terminal proof/receipt use actual root-forward request; source-prepared request must be retained in actual input_files or root_forward_provenance",
        }
        closure_entries = [
            V3_PATH,
            _absolute(__file__),
            Path(str(request.get("command", ["", ""])[1])) if isinstance(request.get("command"), list) and len(request["command"]) > 1 else V3_PATH,
        ]
        closure = _closure_records(closure_entries)
        # The V3 temporary paths are provenance only and are not added to the
        # final static input closure.
        final_manifest = _absolute(args.manifest_output)
        final_request = _absolute(args.request_output)
        # First write the manifest.  It does not contain its own record, so its
        # SHA is stable and can be bound exactly in the request that follows.
        runtime_records = {
            str(_absolute(PYTHON_TARGET)): _record(PYTHON_TARGET, "resolved Python target"),
            str(_absolute(PYVENV_CFG)): _record(PYVENV_CFG, "literal venv configuration"),
            str(_absolute(PYTHON)): _record_literal_python(PYTHON),
        }
        manifest_record_placeholder = {
            "path": str(final_manifest), "label": "ROOT279 V4 manifest output",
            "bytes": 0, "sha256": "PARENT_LOCAL_OUTPUT_SHA_AFTER_WRITE", "stat": {},
            "payload_read_by_builder": False,
        }
        manifest, request = _augment_request(request, manifest, closure, manifest_record_placeholder, runtime_records, str(_absolute(v3_manifest)))
        manifest["source_closure"]["records"].update(runtime_records)
        _write_once(final_manifest, manifest)
        manifest_record = _record(final_manifest, "ROOT279 V4 manifest")
        # Bind the actual manifest record and write the request once.  The
        # request itself is intentionally not part of input_files: including a
        # request's own SHA would create a self-referential impossible digest.
        request["manifest"] = manifest_record
        request["input_records"][manifest_record["path"]] = manifest_record
        request["input_files"] = sorted(request["input_records"])
        request["input_sha256"] = {path: request["input_records"][path]["sha256"] for path in request["input_files"]}
        _write_once(final_request, request)
        request_record = _record(final_request, "ROOT279 V4 request")
        sidecar = final_request.with_name(final_request.stem + ".self-binding.json")
        _write_once(sidecar, {"schema": "ds02.stage2.root279-v4-self-binding.v1", "manifest": manifest_record, "request": request_record, "input_files": request["input_files"], "input_sha256": request["input_sha256"], "status": "SOURCE_PREPARED_PARENT_REBIND_REQUIRED", "request_not_self_bound": True})
        return {"manifest": manifest, "request": request, "manifest_path": str(final_manifest), "request_path": str(final_request), "self_binding_path": str(sidecar)}


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="root279-v4-closure-") as td:
        root = Path(td)
        child = root / "child.py"
        entry = root / "entry.py"
        child.write_text("VALUE = 1\n", encoding="utf-8")
        entry.write_text("import child\n", encoding="utf-8")
        records = _closure_records([entry])
        assert str(entry) in records and str(child) in records
        assert records[str(child)]["sha256"] == hashlib.sha256(child.read_bytes()).hexdigest()
        try:
            _record(root / "missing.py", "missing")
        except BuildFailure:
            pass
        else:
            raise AssertionError("missing closure file was accepted")
    assert MAX_SCRATCH_BYTES == 256 * 1024 * 1024
    assert MAX_LOG_BYTES == 1 * 1024 * 1024
    print("PASS_F1_S2_ROOT279_REQUEST_V4_CLOSURE_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--self-test", action="store_true")
    group.add_argument("--build", action="store_true")
    for name in ("intake", "same-request", "half-request", "same-proof", "half-proof", "same-receipt", "half-receipt", "snapshot", "manifest-output", "request-output"):
        parser.add_argument("--" + name, type=Path, required=False)
    args = parser.parse_args(argv)
    if args.self_test:
        self_test(); return 0
    required = (args.intake, args.same_request, args.half_request, args.same_proof, args.half_proof, args.same_receipt, args.half_receipt, args.manifest_output, args.request_output)
    if any(item is None for item in required):
        parser.error("--build requires intake, both ROOT277/278 requests/proofs/receipts, and manifest/request outputs")
    try:
        result = build(args)
    except Exception as exc:
        print(f"FAILED_F1_S2_ROOT279_REQUEST_V4: {exc}", file=os.sys.stderr)
        return 2
    print(json.dumps({"status": result["request"].get("status"), "manifest": result["manifest_path"], "request": result["request_path"], "self_binding": result["self_binding_path"], "native_payload_read": False, "scientific_credit": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
