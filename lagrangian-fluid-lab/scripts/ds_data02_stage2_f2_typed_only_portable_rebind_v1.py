#!/usr/bin/env python3
"""Relocate and run the existing F2 typed-only consumer through a strict map.

The dependency manifest is an audit of the original producer graph.  This
forward layer turns that audit into a target-relative binding contract and a
sealed overlay.  It never treats the historical source inode or mtime as a
property of a copied file.  Small code/evidence files are hashed when the
overlay is sealed; the result JSON/HDF5 and trajectory HDF5 remain deferred
to the parent-after-reservation gate and are represented by their attested
source SHA and a fresh target stat only.

``run`` is a bounded subprocess entrypoint for the already existing ROOT191
V4 executable.  It runs with the literal interpreter supplied by the caller,
``-B -I``, a copied sibling directory, and no inherited ``PYTHONPATH``.  The
production ``run`` mode invokes V4's real V8/V12 validation and typed scorer;
``run-v8-fixture`` is only for the small manufactured CLI fixture used by the
tests.  Neither mode creates a ledger entry or grants scientific credit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Any, Iterable, Mapping, Sequence


MANIFEST_SCHEMA = "ds02.stage2.f2-typed-only-portable-dependency-manifest.v1"
CONTRACT_SCHEMA = "ds02.stage2.f2-typed-only-portable-rebind-contract.v1"
SEALED_SCHEMA = "ds02.stage2.f2-typed-only-portable-rebind-overlay.v1"
MAX_METADATA_BYTES = 10 * 1024 * 1024
HEX64 = set("0123456789abcdef")
DEFERRED_KINDS = {
    "deferred_result_json",
    "deferred_typed_h5",
    "source_provenance_deferred_h5",
}
PASS_STATUSES = ("PASS_", "ROOT191_V4_METADATA_VALIDATED")
SCRIPT_PATH = Path(__file__).resolve()


class PortableRebindError(RuntimeError):
    """A strict source/target binding, loader, or child execution error."""


def _canonical(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def _require_sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in HEX64 for ch in value):
        raise PortableRebindError(f"{role} must be a lowercase SHA-256")
    return value


def _stat(path: Path) -> dict[str, int]:
    if path.is_symlink() or not path.is_file():
        raise PortableRebindError(f"target must be a regular non-symlink file: {path}")
    value = path.stat()
    return {
        "bytes": int(value.st_size),
        "mode_bits": int(value.st_mode & 0o7777),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
        "st_dev": int(value.st_dev),
        "st_ino": int(value.st_ino),
    }


def _sha(path: Path, *, max_bytes: int = MAX_METADATA_BYTES) -> str:
    size = path.stat().st_size
    if size > max_bytes:
        raise PortableRebindError(f"content hash exceeds bounded metadata limit: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path, role: str, *, max_bytes: int = MAX_METADATA_BYTES) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise PortableRebindError(f"{role} must be a regular non-symlink file: {path}")
    if path.stat().st_size > max_bytes:
        raise PortableRebindError(f"{role} exceeds bounded metadata limit: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PortableRebindError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise PortableRebindError(f"{role} must be a JSON object")
    return value


def _absolute_without_resolving(path: Path | str) -> Path:
    value = Path(path).expanduser()
    if not value.is_absolute():
        value = Path(os.path.abspath(value))
    return value


def _safe_relative(value: Any, role: str) -> str:
    if not isinstance(value, str) or not value:
        raise PortableRebindError(f"{role} target-relative path is missing")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise PortableRebindError(f"{role} target path is not safely relative: {value}")
    return path.as_posix()


def _under(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def _reject_symlink_components(path: Path, root: Path) -> None:
    relative = path.relative_to(root)
    current = root
    if current.is_symlink():
        raise PortableRebindError(f"relocated root is a symlink: {root}")
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise PortableRebindError(f"relocation target contains a symlink: {current}")


def _target(root: Path, relative: str, *, require_exists: bool) -> Path:
    target = root / _safe_relative(relative, "target")
    # Check the lexical namespace before resolving anything.  Resolving first
    # would turn an escaping symlink into an "outside root" error and obscure
    # the stronger, actionable rejection that the target itself is a symlink.
    try:
        target.relative_to(root)
    except ValueError:
        raise PortableRebindError(f"target escapes relocated root: {target}")
    _reject_symlink_components(target, root)
    if require_exists and not target.is_file():
        raise PortableRebindError(f"required relocated role is missing: {target}")
    return target


def _load_manifest(path: Path) -> dict[str, Any]:
    manifest = _json(path, "portable dependency manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise PortableRebindError("dependency manifest schema differs")
    if manifest.get("sha256") != _canonical(manifest):
        raise PortableRebindError("dependency manifest canonical SHA differs")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise PortableRebindError("dependency manifest has no artifacts")
    loading = manifest.get("portable_loading_entry")
    if not isinstance(loading, Mapping):
        raise PortableRebindError("dependency manifest has no portable loading entry")
    _safe_relative(loading.get("entrypoint_target_relative_path"), "loading.entrypoint")
    _safe_relative(loading.get("request_target_relative_path"), "loading.request")
    if loading.get("source_fallback") != "REJECT":
        raise PortableRebindError("loading entry permits source fallback")
    return manifest


def _source_paths(manifest: Mapping[str, Any]) -> list[Path]:
    paths: list[Path] = []
    for item in manifest.get("artifacts", []):
        if isinstance(item, Mapping) and isinstance(item.get("source_path_provenance"), str):
            paths.append(Path(item["source_path_provenance"]))
    return paths


def _assert_target_namespace(manifest: Mapping[str, Any], root: Path) -> None:
    """Reject using a source directory as the copy target."""
    if root.exists() and root.is_symlink():
        raise PortableRebindError(f"relocated root is a symlink: {root}")
    for source in _source_paths(manifest):
        source_abs = _absolute_without_resolving(source)
        if _under(root, source_abs) or _under(source_abs, root):
            raise PortableRebindError(
                f"relocated namespace overlaps source provenance: {root} / {source_abs}")


def _write_new(path: Path, value: Mapping[str, Any]) -> Path:
    if path.exists() or path.is_symlink():
        raise PortableRebindError(f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True,
                               allow_nan=False) + "\n", encoding="utf-8")
    return path


def build_contract(*, manifest_path: Path | str, relocated_root: Path | str,
                   output: Path | str, contract_id: str) -> dict[str, Any]:
    manifest_path = _absolute_without_resolving(manifest_path)
    manifest = _load_manifest(manifest_path)
    root = _absolute_without_resolving(relocated_root)
    _assert_target_namespace(manifest, root)
    if not isinstance(contract_id, str) or not contract_id or "/" in contract_id:
        raise PortableRebindError("contract_id must be a non-empty path-safe identifier")

    roles: list[dict[str, Any]] = []
    seen_targets: set[str] = set()
    for item in manifest["artifacts"]:
        if not isinstance(item, Mapping) or item.get("actionable") is not True:
            continue
        role = item.get("logical_role")
        if not isinstance(role, str) or not role:
            raise PortableRebindError("actionable artifact has no logical role")
        target_relative = _safe_relative(item.get("target_relative_path"), role)
        if target_relative in seen_targets:
            raise PortableRebindError(f"duplicate target-relative path: {target_relative}")
        seen_targets.add(target_relative)
        source_sha = _require_sha(item.get("source_sha256"), f"{role}.source_sha256")
        source_stat = item.get("source_stat_provenance")
        if not isinstance(source_stat, Mapping):
            raise PortableRebindError(f"{role} has no source stat provenance")
        deferred = item.get("source_kind") in DEFERRED_KINDS or item.get("content_read_by_manifest") is False
        roles.append({
            "logical_role": role,
            "source_kind": item.get("source_kind"),
            "source_sha256": source_sha,
            "source_sha256_basis": item.get("source_sha256_basis"),
            "source_stat_provenance": dict(source_stat),
            "source_path_provenance": str(item.get("source_path_provenance")),
            "target_relative_path": target_relative,
            "target_stat": None,
            "target_sha256": None,
            "content_sha_verified": False,
            "content_verification_phase": "PARENT_AFTER_RESERVATION" if deferred else "SEAL_METADATA",
            "deferred_content": deferred,
            "source_inode_mtime_equivalence": "NOT_CLAIMED",
        })
    if not roles:
        raise PortableRebindError("manifest has no actionable roles")

    # The rebind helper is itself part of the private copied runtime.  Keep it
    # as a distinct logical role so a copied child cannot silently execute the
    # helper from the original worktree.  This additive role does not mutate
    # the consumed dependency manifest.
    helper_role = "typed_only_portable_rebind_v1"
    if helper_role not in {str(role["logical_role"]) for role in roles}:
        roles.append({
            "logical_role": helper_role,
            "source_kind": "portable_rebind_runtime",
            "source_sha256": _sha(SCRIPT_PATH),
            "source_sha256_basis": "manifest_read_bounded",
            "source_stat_provenance": _stat(SCRIPT_PATH),
            "source_path_provenance": str(SCRIPT_PATH),
            "target_relative_path": "runtime/ds_data02_stage2_f2_typed_only_portable_rebind_v1.py",
            "target_stat": None,
            "target_sha256": None,
            "content_sha_verified": False,
            "content_verification_phase": "SEAL_METADATA",
            "deferred_content": False,
            "source_inode_mtime_equivalence": "NOT_CLAIMED",
        })

    loading = manifest["portable_loading_entry"]
    loading_entry = {
        "entrypoint_logical_role": loading["entrypoint_logical_role"],
        "entrypoint_target_relative_path": _safe_relative(loading["entrypoint_target_relative_path"], "loading.entrypoint"),
        "request_target_relative_path": _safe_relative(loading["request_target_relative_path"], "loading.request"),
        "frozen_v15_target_relative_path": _safe_relative(loading["frozen_v15_target_relative_path"], "loading.v15"),
        "current_target_relative_path": _safe_relative(loading["current_target_relative_path"], "loading.current"),
        "result_target_relative_path": _safe_relative(loading["result_target_relative_path"], "loading.result"),
        "typed_h5_target_relative_path": _safe_relative(loading["typed_h5_target_relative_path"], "loading.typed_h5"),
        "fresh_proof_target_relative_path": _safe_relative(loading["fresh_proof_target_relative_path"], "loading.proof"),
        "operator_report_target_relative_path": _safe_relative(loading["operator_report_target_relative_path"], "loading.report"),
        "runtime_sibling_directory": _safe_relative(loading["runtime_sibling_directory"], "loading.runtime"),
        "argv0_policy": loading.get("argv0_policy"),
        "source_fallback": "REJECT",
        "no_model": True,
        "model_invoked": False,
    }
    contract: dict[str, Any] = {
        "schema": CONTRACT_SCHEMA,
        "status": "PENDING_PARENT_RELOCATION_TARGETS",
        "contract_id": contract_id,
        "manifest_binding": {
            "path_provenance": str(manifest_path),
            "sha256": manifest["sha256"],
            "content_read_by_rebind_builder": True,
        },
        "relocated_root": str(root),
        "roles": roles,
        "portable_loading_entry": loading_entry,
        "path_policy": {
            "original_absolute_path_fallback": "REJECT",
            "source_path_provenance_is_not_actionable": True,
            "source_stat_is_not_target_stat": True,
            "source_inode_mtime_equivalence": "NOT_CLAIMED",
            "symlink_targets": "REJECT",
        },
        "parent_gate": {
            "content_sha_and_deferred_payload_read": "AFTER_PARENT_RESERVATION",
            "ledger_mutated_by_this_helper": False,
            "raw_to_typed_credit": "NOT_CLAIMED",
            "portable_cold_replay_credit": "NOT_CLAIMED",
            "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
        },
        "metadata_only": True,
        "payload_read": False,
    }
    contract["sha256"] = _canonical(contract)
    _write_new(_absolute_without_resolving(output), contract)
    return contract


def _load_contract(path: Path | str) -> dict[str, Any]:
    contract_path = _absolute_without_resolving(path)
    contract = _json(contract_path, "rebind contract")
    if contract.get("schema") != CONTRACT_SCHEMA:
        raise PortableRebindError("rebind contract schema differs")
    if contract.get("sha256") != _canonical(contract):
        raise PortableRebindError("rebind contract canonical SHA differs")
    if contract.get("path_policy", {}).get("original_absolute_path_fallback") != "REJECT":
        raise PortableRebindError("rebind contract permits original path fallback")
    return contract


def seal_contract(*, contract_path: Path | str, output: Path | str,
                  verify_deferred_content: bool = False) -> dict[str, Any]:
    contract = _load_contract(contract_path)
    root = _absolute_without_resolving(contract.get("relocated_root"))
    if not root.is_dir() or root.is_symlink():
        raise PortableRebindError(f"relocated root is not a real directory: {root}")
    sealed_roles: list[dict[str, Any]] = []
    for role in contract.get("roles", []):
        if not isinstance(role, Mapping):
            raise PortableRebindError("malformed role in rebind contract")
        target_relative = _safe_relative(role.get("target_relative_path"), "role.target")
        target = _target(root, target_relative, require_exists=True)
        stat = _stat(target)
        deferred = bool(role.get("deferred_content"))
        verified = False
        target_sha: str | None = None
        if not deferred or verify_deferred_content:
            target_sha = _sha(target)
            if target_sha != role.get("source_sha256"):
                raise PortableRebindError(f"relocated content SHA differs for {role.get('logical_role')}")
            verified = True
        sealed_roles.append({
            "logical_role": role["logical_role"],
            "source_kind": role.get("source_kind"),
            "source_sha256": role["source_sha256"],
            "source_sha256_basis": role.get("source_sha256_basis"),
            "source_stat_provenance": dict(role["source_stat_provenance"]),
            "source_path_provenance": role.get("source_path_provenance"),
            "target_relative_path": target_relative,
            "target_stat": stat,
            "target_sha256": target_sha,
            "content_sha_verified": verified,
            "deferred_content": deferred,
            "source_inode_mtime_equivalence": "NOT_CLAIMED",
        })
    sealed: dict[str, Any] = {
        "schema": SEALED_SCHEMA,
        "status": "SEALED_TARGET_RELATIVE_BINDING_READY",
        "contract": {"path_provenance": str(_absolute_without_resolving(contract_path)),
                     "sha256": contract["sha256"]},
        "relocated_root": str(root),
        "roles": sealed_roles,
        "portable_loading_entry": dict(contract["portable_loading_entry"]),
        "path_policy": dict(contract["path_policy"]),
        "parent_gate": dict(contract["parent_gate"]),
        "deferred_content_roles": [r["logical_role"] for r in sealed_roles if r["deferred_content"]],
        "all_target_content_verified": all(r["content_sha_verified"] for r in sealed_roles),
        "payload_read": False,
    }
    sealed["sha256"] = _canonical(sealed)
    _write_new(_absolute_without_resolving(output), sealed)
    return sealed


def _sealed_role(sealed: Mapping[str, Any], logical_role: str) -> Mapping[str, Any]:
    for role in sealed.get("roles", []):
        if isinstance(role, Mapping) and role.get("logical_role") == logical_role:
            return role
    raise PortableRebindError(f"sealed overlay role is missing: {logical_role}")


def validate_sealed(path: Path | str, *, verify_deferred_content: bool = False) -> dict[str, Any]:
    sealed = _json(_absolute_without_resolving(path), "sealed relocation overlay")
    if sealed.get("schema") != SEALED_SCHEMA or sealed.get("sha256") != _canonical(sealed):
        raise PortableRebindError("sealed overlay schema/canonical SHA differs")
    root = _absolute_without_resolving(sealed.get("relocated_root"))
    if not root.is_dir() or root.is_symlink():
        raise PortableRebindError(f"sealed relocated root is unavailable: {root}")
    checked = 0
    for role in sealed.get("roles", []):
        if not isinstance(role, Mapping):
            raise PortableRebindError("malformed sealed role")
        target = _target(root, _safe_relative(role.get("target_relative_path"), "sealed.target"), require_exists=True)
        actual_stat = _stat(target)
        if actual_stat != role.get("target_stat"):
            raise PortableRebindError(f"target stat changed for {role.get('logical_role')}")
        if role.get("content_sha_verified"):
            if _sha(target) != role.get("target_sha256") or role.get("target_sha256") != role.get("source_sha256"):
                raise PortableRebindError(f"sealed target content changed for {role.get('logical_role')}")
        elif verify_deferred_content:
            if _sha(target) != role.get("source_sha256"):
                raise PortableRebindError(f"deferred target content differs for {role.get('logical_role')}")
        checked += 1
    loading = sealed.get("portable_loading_entry")
    if not isinstance(loading, Mapping) or loading.get("source_fallback") != "REJECT":
        raise PortableRebindError("sealed loading entry permits source fallback")
    _sealed_role(sealed, str(loading.get("entrypoint_logical_role")))
    return {"schema": SEALED_SCHEMA, "status": "SEALED_RELOCATION_VALIDATED",
            "overlay": str(_absolute_without_resolving(path)), "role_count": checked,
            "all_target_content_verified": bool(sealed.get("all_target_content_verified")),
            "payload_read": False}


def _read_report(path: Path) -> dict[str, Any]:
    report = _json(path, "child report", max_bytes=MAX_METADATA_BYTES)
    status = str(report.get("status", ""))
    if not status.startswith(PASS_STATUSES):
        raise PortableRebindError(f"child report is not a successful typed-only report: {status}")
    execution = report.get("execution")
    model_invoked = report.get("model_invoked")
    if model_invoked is None and isinstance(execution, Mapping):
        model_invoked = execution.get("model_invoked")
    if model_invoked is not False:
        raise PortableRebindError("child report model invocation is not false")
    return report


def run_child(*, overlay_path: Path | str, request_relative: str,
              output_relative: str, entry_mode: str, python_path: Path | str,
              parent_pid: int, max_wall_seconds: float,
              receipt_relative: str | None = None) -> dict[str, Any]:
    overlay_path = _absolute_without_resolving(overlay_path)
    validate_sealed(overlay_path)
    overlay = _json(overlay_path, "sealed relocation overlay")
    root = _absolute_without_resolving(overlay["relocated_root"])
    request = _target(root, _safe_relative(request_relative, "request"), require_exists=True)
    output = _target(root, _safe_relative(output_relative, "output"), require_exists=False)
    if output.exists() or output.is_symlink():
        raise PortableRebindError(f"refusing existing child output: {output}")
    entry = _sealed_role(overlay, str(overlay["portable_loading_entry"]["entrypoint_logical_role"]))
    entry_path = _target(root, _safe_relative(entry["target_relative_path"], "entrypoint"), require_exists=True)
    if not entry.get("content_sha_verified"):
        raise PortableRebindError("entrypoint content SHA is not sealed")
    interpreter = Path(python_path).expanduser()
    if not interpreter.is_file():
        raise PortableRebindError(f"literal interpreter is unavailable: {interpreter}")
    if entry_mode not in {"run", "run-v8-fixture"}:
        raise PortableRebindError("entry_mode must be run or run-v8-fixture")
    if isinstance(parent_pid, bool) or int(parent_pid) <= 0:
        raise PortableRebindError("parent_pid must be a positive OS PID")
    if os.getppid() != int(parent_pid):
        raise PortableRebindError("portable rebind wrapper is not running under its declared parent guard")
    if max_wall_seconds <= 0:
        raise PortableRebindError("max_wall_seconds must be positive")
    receipt_rel = _safe_relative(receipt_relative or (str(Path(output_relative).with_suffix(".guard-receipt.json"))), "receipt")
    receipt = _target(root, receipt_rel, require_exists=False)
    if receipt.exists() or receipt.is_symlink():
        raise PortableRebindError(f"refusing existing guard receipt: {receipt}")
    stdout = _target(root, str(Path(output_relative).with_suffix(".stdout.log")), require_exists=False)
    stderr = _target(root, str(Path(output_relative).with_suffix(".stderr.log")), require_exists=False)
    for log in (stdout, stderr):
        if log.exists() or log.is_symlink():
            raise PortableRebindError(f"refusing existing child log: {log}")
        log.parent.mkdir(parents=True, exist_ok=True)

    command = [str(interpreter), "-B", "-I", str(entry_path), entry_mode,
               "--request", str(request), "--output", str(output),
               "--parent-pid", str(os.getpid())]
    if entry_mode == "run":
        command.extend(["--max-wall-seconds", str(float(max_wall_seconds))])
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        environment[key] = "1"
    started = time.monotonic()
    with stdout.open("x", encoding="utf-8") as stdout_stream, stderr.open("x", encoding="utf-8") as stderr_stream:
        child = subprocess.Popen(command, cwd=str(root), env=environment,
                                 stdout=stdout_stream, stderr=stderr_stream,
                                 start_new_session=True, close_fds=True)
        timed_out = False
        try:
            returncode = child.wait(timeout=float(max_wall_seconds))
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                child.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait(timeout=5.0)
            returncode = child.returncode
    if timed_out:
        raise PortableRebindError("relocated typed-only child exceeded bounded deadline")
    if returncode != 0:
        raise PortableRebindError(f"relocated typed-only child failed with return code {returncode}")
    report = _read_report(output)
    result = {
        "schema": "ds02.stage2.f2-typed-only-portable-rebind-execution-receipt.v1",
        "status": "COMPLETE_RELOCATED_TYPED_ONLY_CHILD",
        "overlay_sha256": overlay["sha256"],
        "entrypoint_role": entry["logical_role"],
        "entrypoint_target_relative_path": entry["target_relative_path"],
        "request_target_relative_path": _safe_relative(request_relative, "request"),
        "output_target_relative_path": _safe_relative(output_relative, "output"),
        "stdout_target_relative_path": str(stdout.relative_to(root)),
        "stderr_target_relative_path": str(stderr.relative_to(root)),
        "child_returncode": returncode,
        "child_status": report["status"],
        "model_invoked": False,
        "hdf5_or_bi4_content_read": report.get("execution", {}).get("hdf5_or_bi4_content_read", False),
        "raw_opened": report.get("execution", {}).get("raw_opened", False),
        "max_wall_seconds": float(max_wall_seconds),
        "elapsed_wall_seconds": time.monotonic() - started,
        "source_fallback": "REJECT",
        "ledger_mutated": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "portable_cold_replay_credit": "NOT_CLAIMED",
        "report_sha256": _sha(output),
        "report_bytes": output.stat().st_size,
    }
    result["sha256"] = _canonical(result)
    _write_new(receipt, result)
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-contract")
    build.add_argument("--manifest", type=Path, required=True)
    build.add_argument("--relocated-root", type=Path, required=True)
    build.add_argument("--contract-id", required=True)
    build.add_argument("--output", type=Path, required=True)
    seal = sub.add_parser("seal")
    seal.add_argument("--contract", type=Path, required=True)
    seal.add_argument("--output", type=Path, required=True)
    seal.add_argument("--verify-deferred-content", action="store_true")
    validate = sub.add_parser("validate")
    validate.add_argument("--overlay", type=Path, required=True)
    validate.add_argument("--verify-deferred-content", action="store_true")
    run = sub.add_parser("run")
    run.add_argument("--overlay", type=Path, required=True)
    run.add_argument("--request-relative", required=True)
    run.add_argument("--output-relative", required=True)
    run.add_argument("--entry-mode", choices=("run", "run-v8-fixture"), default="run")
    run.add_argument("--python", dest="python_path", type=Path, required=True)
    run.add_argument("--parent-pid", type=int, required=True)
    run.add_argument("--max-wall-seconds", type=float, required=True)
    run.add_argument("--receipt-relative")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "build-contract":
            value = build_contract(manifest_path=args.manifest, relocated_root=args.relocated_root,
                                   output=args.output, contract_id=args.contract_id)
        elif args.command == "seal":
            value = seal_contract(contract_path=args.contract, output=args.output,
                                  verify_deferred_content=args.verify_deferred_content)
        elif args.command == "validate":
            value = validate_sealed(args.overlay, verify_deferred_content=args.verify_deferred_content)
        else:
            value = run_child(overlay_path=args.overlay, request_relative=args.request_relative,
                              output_relative=args.output_relative, entry_mode=args.entry_mode,
                              python_path=args.python_path, parent_pid=args.parent_pid,
                              max_wall_seconds=args.max_wall_seconds,
                              receipt_relative=args.receipt_relative)
    except (PortableRebindError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"typed-only portable rebind: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"schema": value.get("schema"), "status": value.get("status"),
                      "sha256": value.get("sha256"), "role_count": value.get("role_count"),
                      "payload_read": value.get("payload_read", False),
                      "model_invoked": value.get("model_invoked")}, sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
