#!/usr/bin/env python3
"""Execute the ROOT213 typed-only relocation after a parent reservation.

ROOT213's builder is intentionally metadata-only.  This additive entry point
is the first stage that may consume the declared V16 JSON, and it does so only
after a directly supervised parent has reserved the attempt.  It seals a
fresh target-relative V1 contract, copies the V16 result plus bounded evidence
and runtime roles, creates the existing V2 request overlay, and calls V2's
real V8/V12/typed-scorer worker in a private subprocess.

The executor never copies or opens HDF5, BI4, or raw data.  The frozen V15
view receives sparse stat-only placeholders for those roles; the existing
typed scorer needs their producer-attested stat contract but does not consume
their content.  A result/report is valid only when the copied V16 file's
source and target SHA/stat pre/post records agree.  No ledger is created or
mutated here; the parent owns the reservation and terminal accounting.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
ROOT213_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_root213_portable_typed_parent_v1.py"
V1_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_portable_rebind_v1.py"
V2_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_portable_rebind_v2.py"
NO_MODEL_V2_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_no_model_evaluator_v2.py"


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load dependency: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ROOT213 = _load(ROOT213_SCRIPT, "ds02_root213_for_executor")
V1 = _load(V1_SCRIPT, "ds02_portable_rebind_v1_for_executor")
V2 = _load(V2_SCRIPT, "ds02_portable_rebind_v2_for_executor")


REQUEST_SCHEMA = "ds02.stage2.f2-root213-portable-typed-parent-request.v1"
REPORT_SCHEMA = "ds02.stage2.f2-root213-portable-typed-executor-report.v1"
MAX_METADATA_BYTES = 10 * 1024 * 1024
MAX_RESULT_BYTES = 100 * 1024 * 1024
HEX64 = set("0123456789abcdef")
PROVENANCE_KEYS = {"historical_provenance", "source_provenance", "provenance",
                   "original_roots", "old_absolute_paths"}
PAYLOAD_SUFFIXES = {".h5", ".hdf5", ".bi4", ".obi4", ".out"}


class Root213ExecutorError(RuntimeError):
    """A strict ROOT213 parent, copy, seal, or child-execution failure."""


def _canonical(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def _abs(value: Any, role: str, *, allow_symlink: bool = False) -> Path:
    if not isinstance(value, str) or not value.startswith("/"):
        raise Root213ExecutorError(f"{role} must be an absolute path")
    path = Path(value).expanduser()
    if path.is_symlink() and not allow_symlink:
        raise Root213ExecutorError(f"{role} may not be a symlink: {path}")
    return path


def _full_stat(path: Path, role: str, *, allow_symlink: bool = False) -> dict[str, int]:
    if path.is_symlink() and not allow_symlink:
        raise Root213ExecutorError(f"{role} is a symlink")
    if not path.is_file():
        raise Root213ExecutorError(f"{role} is not a regular file: {path}")
    value = path.stat()
    return {"bytes": int(value.st_size), "mode_bits": int(value.st_mode & 0o7777),
            "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns),
            "st_dev": int(value.st_dev), "st_ino": int(value.st_ino)}


def _sha(path: Path, role: str, *, maximum: int = MAX_METADATA_BYTES) -> str:
    if path.is_symlink():
        path = path.resolve()
    stat = _full_stat(path, role)
    if stat["bytes"] > maximum:
        raise Root213ExecutorError(f"{role} exceeds the bounded hash limit: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha_value(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in HEX64 for c in value):
        raise Root213ExecutorError(f"{role} must be a lowercase SHA-256")
    return value


def _json(path: Path, role: str, *, maximum: int = MAX_METADATA_BYTES) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise Root213ExecutorError(f"{role} must be a regular non-symlink file: {path}")
    if path.stat().st_size > maximum:
        raise Root213ExecutorError(f"{role} exceeds the bounded JSON limit: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise Root213ExecutorError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise Root213ExecutorError(f"{role} must be a JSON object")
    return value


def _safe_relative(value: Any, role: str) -> str:
    if not isinstance(value, str) or not value:
        raise Root213ExecutorError(f"{role} target-relative path is missing")
    path = Path(value)
    if path.is_absolute() or "." in path.parts or ".." in path.parts:
        raise Root213ExecutorError(f"{role} target path is not safely relative: {value}")
    return path.as_posix()


def _under(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def _source_stat(value: Any, role: str, fallback: Path | None = None) -> dict[str, int]:
    if isinstance(value, Mapping):
        result: dict[str, int] = {}
        for key in ("bytes", "mode_bits", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
            if key in value and isinstance(value[key], (int, float)) and not isinstance(value[key], bool):
                result[key] = int(value[key])
        if "bytes" in result and "mode_bits" in result and "mtime_ns" in result:
            return result
    if fallback is not None and (fallback.is_file() or fallback.is_symlink()):
        return _full_stat(fallback.resolve() if fallback.is_symlink() else fallback, role)
    raise Root213ExecutorError(f"{role} lacks a source stat contract")


def _path_sha_from_binding(value: Mapping[str, Any]) -> str | None:
    for key in ("file_sha256", "sha256", "producer_declared_sha256", "source_sha256"):
        candidate = value.get(key)
        if isinstance(candidate, str) and len(candidate) == 64 and not any(c not in HEX64 for c in candidate):
            return candidate
    return None


def _is_provenance(parts: Sequence[str]) -> bool:
    lowered = [str(part).lower() for part in parts]
    return any(item in PROVENANCE_KEYS or "provenance" in item for item in lowered)


def _path_records(value: Any, parts: tuple[str, ...] = ()) -> list[tuple[str, Mapping[str, Any], tuple[str, ...]]]:
    records: list[tuple[str, Mapping[str, Any], tuple[str, ...]]] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            if key_text == "path" and isinstance(child, str) and child.startswith("/"):
                if not _is_provenance(parts):
                    # Directory roots are represented by their containing
                    # request fields and are rebound by V2's synthetic
                    # directory policy.  Only file roles need a contract
                    # artifact here.
                    candidate = Path(child).expanduser()
                    if not candidate.exists() or candidate.is_file():
                        records.append((child, value, parts + (key_text,)))
            else:
                records.extend(_path_records(child, parts + (key_text,)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            records.extend(_path_records(child, parts + (str(index),)))
    return records


class _ArtifactTable:
    def __init__(self, output_root: Path):
        self.output_root = output_root
        self.items: list[dict[str, Any]] = []
        self.by_source: dict[str, dict[str, Any]] = {}
        self.by_target: dict[str, dict[str, Any]] = {}

    def add(self, *, role: str, source: Path, target: str, sha256: str | None,
            stat: Mapping[str, Any] | None, kind: str, deferred: bool,
            placeholder: bool = False, executable_exception: bool = False) -> dict[str, Any]:
        source_key = os.path.abspath(str(source))
        if source_key in self.by_source:
            return self.by_source[source_key]
        target = _safe_relative(target, role)
        if target in self.by_target:
            existing = self.by_target[target]
            if existing.get("source_path_provenance") == str(source):
                self.by_source[source_key] = existing
                return existing
            target = f"closure/{hashlib.sha256(source_key.encode()).hexdigest()[:16]}-{Path(target).name}"
        if sha256 is None:
            if source.is_file() and source.stat().st_size <= MAX_METADATA_BYTES:
                sha256 = _sha(source, role)
            else:
                raise Root213ExecutorError(f"{role} has no declared SHA for an unavailable/large source")
        sha256 = _sha_value(sha256, f"{role}.source_sha256")
        source_stat = _source_stat(stat, role, source)
        item = {
            "logical_role": role, "source_kind": kind,
            "actionable": True, "content_read_by_manifest": not bool(deferred),
            "source_sha256": sha256, "source_sha256_basis": "ROOT213_DECLARED_OR_POSTRESERVATION",
            "source_stat_provenance": dict(source_stat), "source_path_provenance": str(source),
            "target_relative_path": target, "target_stat": None, "target_sha256": None,
            "content_sha_verified": False, "content_verification_phase":
                "PARENT_AFTER_RESERVATION" if deferred else "SEAL_METADATA",
            "deferred_content": bool(deferred), "placeholder_only": bool(placeholder),
            "executable_environment_exception": bool(executable_exception),
            "source_inode_mtime_equivalence": "NOT_CLAIMED",
        }
        self.items.append(item)
        self.by_source[source_key] = item
        self.by_target[target] = item
        return item

    def get(self, source: Path) -> dict[str, Any] | None:
        return self.by_source.get(os.path.abspath(str(source)))


def _add_binding(table: _ArtifactTable, binding: Mapping[str, Any], role: str,
                 target: str, *, kind: str = "bounded_evidence") -> dict[str, Any]:
    source = _abs(binding.get("path"), role)
    return table.add(role=role, source=source, target=target,
                     sha256=_path_sha_from_binding(binding), stat=binding.get("stat"),
                     kind=kind, deferred=False)


def _payload_like(path: Path, value: Mapping[str, Any] | None) -> bool:
    suffix = path.suffix.lower()
    if suffix in PAYLOAD_SUFFIXES:
        return True
    if value is not None and isinstance(value.get("bytes"), int) and int(value["bytes"]) > MAX_METADATA_BYTES:
        return True
    try:
        return path.is_file() and path.stat().st_size > MAX_METADATA_BYTES
    except OSError:
        return False


def _target_for_closure(path: Path, sha256: str | None, *, payload: bool) -> str:
    token = sha256[:16] if isinstance(sha256, str) and len(sha256) >= 16 else hashlib.sha256(str(path).encode()).hexdigest()[:16]
    suffix = path.suffix or ".metadata"
    if payload:
        return f"evidence/deferred/{token}-{path.name}"
    return f"evidence/closure/{token}-{path.name}"


def _make_manifest(request: Mapping[str, Any], root: Path, reservation_started: float) -> tuple[Path, Path, dict[str, Any]]:
    """Build the V1 contract inputs after the parent boundary is active."""
    table = _ArtifactTable(root)
    evidence = request["root200_evidence"]

    table.add(role="root200_inner_request", source=_abs(evidence["inner_request"]["path"], "ROOT200 inner"),
              target="evidence/root200/inner.json", sha256=evidence["inner_request"]["file_sha256"],
              stat=None, kind="bounded_evidence", deferred=False)
    for key, role, target in (
        ("outer_wrapper", "root200_outer_wrapper", "evidence/root200/outer-wrapper.json"),
        ("completed_execution_receipt", "root200_execution_receipt", "evidence/root200/execution-receipt.json"),
        ("actual_verification_checkpoint", "root200_verification_checkpoint", "evidence/root200/checkpoint.json"),
        ("fresh_v12_proof", "root200_fresh_v12_proof", "evidence/root200/fresh-v12-proof.json"),
    ):
        _add_binding(table, evidence[key], role, target)
    nested_meta = evidence["nested_actionable_metadata"]
    _add_binding(table, nested_meta["current_manifest"], "current336_actionable_metadata",
                 "evidence/current/CURRENT336.json")
    _add_binding(table, nested_meta["v12_semantic_sidecar"], "v12_semantic_sidecar",
                 "evidence/v12/semantic-sidecar.json")
    _add_binding(table, nested_meta["producer_nested_report"], "producer_nested_report_v2",
                 "evidence/v12/producer-report.json")

    producer = request["producer_179c_evidence"]
    for key, target in (("request", "evidence/producer-179c/request.json"),
                        ("completed_receipt", "evidence/producer-179c/receipt.json"),
                        ("parent_report", "evidence/producer-179c/parent-report.json"),
                        ("root_proof", "evidence/producer-179c/root-proof.json")):
        _add_binding(table, producer[key], f"producer_179c_{key}", target)

    frozen = request["frozen_v15"]
    frozen_source = _abs(frozen["path"], "frozen V15")
    table.add(role="frozen_v15_request", source=frozen_source,
              target="evidence/frozen-v15/request.json", sha256=frozen["file_sha256"],
              stat=frozen.get("stat"), kind="frozen_source", deferred=False)

    result = request["deferred_products"]["v16_result"]
    result_source = _abs(result["path"], "deferred V16 result")
    table.add(role="root179c_v16_result_deferred", source=result_source,
              target="products/v16-result.json", sha256=result["sha256"],
              stat=result["expected_stat"], kind="deferred_result_json", deferred=True)

    # Runtime roles from ROOT191 are already source-bound.  Normalize only
    # historical role aliases required by the existing V2 loader.
    aliases = {"no_model_evaluator_v3": "typed_scorer_v3",
               "replay_v14_source_contract": "replay_v14",
               "replay_v15_source_contract": "replay_v15"}
    for role in request["runtime_closure"]["roles"]:
        logical = aliases.get(str(role["role"]), str(role["role"]))
        table.add(role=logical, source=_abs(role["source_path"], f"runtime.{logical}"),
                  target=str(role["target_relative_path"]), sha256=role["source_sha256"],
                  stat=role.get("source_stat"), kind="runtime_source", deferred=False)
    interface = request["v2_interface"]
    table.add(role="portable_rebind_v2_entrypoint", source=_abs(interface["v2_script"], "V2 entrypoint"),
              target=f"runtime/{V2_SCRIPT.name}", sha256=interface["v2_script_sha256"],
              stat=None, kind="runtime_source", deferred=False)
    interpreter = _abs(interface["literal_python"], "literal project interpreter", allow_symlink=True)
    interpreter_real = interpreter.resolve()
    table.add(role="literal_project_venv_python", source=interpreter,
              target="environment/python", sha256=_sha(interpreter_real, "literal interpreter"),
              stat=_full_stat(interpreter_real, "literal interpreter"), kind="external_environment",
              deferred=False, executable_exception=True)
    pyvenv = _abs(interface["pyvenv_cfg"], "project pyvenv.cfg")
    table.add(role="pinned_project_pyvenv_cfg", source=pyvenv, target="environment/pyvenv.cfg",
              sha256=_sha(pyvenv, "project pyvenv.cfg"), stat=_full_stat(pyvenv, "project pyvenv.cfg"),
              kind="external_environment", deferred=False)
    # V2's typed scorer imports the V2 evaluator through its V3 sibling.  The
    # ROOT191 closure names V3, while this exact V2 source is an explicit
    # additional code binding rather than an implicit worktree import.
    table.add(role="typed_scorer_v2", source=NO_MODEL_V2_SCRIPT,
              target=f"runtime/{NO_MODEL_V2_SCRIPT.name}", sha256=_sha(NO_MODEL_V2_SCRIPT, "typed scorer V2"),
              stat=_full_stat(NO_MODEL_V2_SCRIPT, "typed scorer V2"), kind="runtime_source", deferred=False)
    # V1 injects this helper when it is absent from a manifest.  Declare it
    # explicitly here so the copy phase actually materializes the same role
    # that the sealed contract and V2 runtime closure will consume.
    table.add(role="typed_only_portable_rebind_v1", source=V1_SCRIPT,
              target=f"runtime/{V1_SCRIPT.name}", sha256=_sha(V1_SCRIPT, "V1 entrypoint"),
              stat=_full_stat(V1_SCRIPT, "V1 entrypoint"), kind="runtime_source", deferred=False)

    # Ensure the source map covers every actionable path inside the copied
    # inner request, sidecar, and frozen V15 JSON.  Small roles are copied;
    # HDF5/raw/BI4/oversized CSV roles get sparse stat-only placeholders.
    json_sources: list[tuple[Path, dict[str, Any]]] = []
    for binding in (evidence["inner_request"], nested_meta["v12_semantic_sidecar"], frozen):
        path = _abs(binding["path"], "metadata source")
        json_sources.append((path, _json(path, "metadata source")))
    for path, value in json_sources:
        for raw_path, parent, _parts in _path_records(value):
            source = _abs(raw_path, "nested source path")
            if table.get(source) is not None:
                continue
            sha = _path_sha_from_binding(parent)
            payload = _payload_like(source, parent)
            if sha is None and source.is_file() and not payload:
                sha = _sha(source, "nested small source")
            if sha is None:
                raise Root213ExecutorError(f"nested source has no declared SHA: {source}")
            target = _target_for_closure(source, sha, payload=payload)
            stat = parent.get("stat") if isinstance(parent, Mapping) else None
            table.add(role=f"closure_{hashlib.sha256(str(source).encode()).hexdigest()[:16]}",
                      source=source, target=target, sha256=sha, stat=stat,
                      kind="deferred_source_placeholder" if payload else "bounded_source",
                      deferred=payload, placeholder=payload)

    # The request itself is regenerated by V2 from this role.  Make the
    # manifest/contract files target-local; they are metadata, not executable
    # source and are never used as an original-path fallback.
    manifest = {
        "schema": V1.MANIFEST_SCHEMA,
        "status": "ROOT213_PARENT_RESERVATION_COPY_MANIFEST",
        "artifacts": table.items,
        "portable_loading_entry": {
            "entrypoint_logical_role": "fresh_v16_proof_consumer_v8",
            "entrypoint_target_relative_path": next(item["target_relative_path"] for item in table.items if item["logical_role"] == "fresh_v16_proof_consumer_v8"),
            "request_target_relative_path": "evidence/root200/inner.json",
            "frozen_v15_target_relative_path": "evidence/frozen-v15/request.json",
            "current_target_relative_path": "evidence/current/CURRENT336.json",
            "result_target_relative_path": "products/v16-result.json",
            "typed_h5_target_relative_path": "evidence/deferred/typed-output.h5",
            "fresh_proof_target_relative_path": "reports/v2-report.json",
            "operator_report_target_relative_path": "reports/v2-report.json",
            "runtime_sibling_directory": "runtime", "source_fallback": "REJECT",
            "no_model": True, "model_invoked": False,
        },
        "path_policy": {"original_absolute_path_fallback": "REJECT"},
        "parent_boundary": {"reservation_asserted_by_direct_parent": True,
                            "reservation_started_monotonic": reservation_started,
                            "content_phase": "AFTER_PARENT_RESERVATION"},
    }
    manifest["sha256"] = _canonical(manifest)
    manifest_path = root / "metadata" / "root213-copy-manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    contract_path = root / "metadata" / "root213-copy-contract.json"
    contract = V1.build_contract(manifest_path=manifest_path, relocated_root=root,
                                 output=contract_path, contract_id=request["attempt_id"])
    return manifest_path, contract_path, {"table": table, "manifest": manifest, "contract": contract}


def _contract_stat(item: Mapping[str, Any], role: str) -> dict[str, int]:
    """Return the declared source stat without touching source content."""
    value = item.get("source_stat_provenance")
    if not isinstance(value, Mapping):
        raise Root213ExecutorError(f"{role} lacks source stat provenance")
    result: dict[str, int] = {}
    for key in ("bytes", "mode_bits", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
        raw = value.get(key)
        if isinstance(raw, bool) or raw is None:
            if key in {"ctime_ns", "st_dev", "st_ino"}:
                # ROOT213 permits an older three-field stat for copied metadata;
                # the target audit records the fields that are actually known.
                continue
            raise Root213ExecutorError(f"{role} source stat lacks {key}")
        result[key] = int(raw)
    return result


def _copy_roles(table: _ArtifactTable, root: Path, *, deadline: float) -> list[dict[str, Any]]:
    audit: list[dict[str, Any]] = []
    for item in table.items:
        if time.monotonic() >= deadline:
            raise Root213ExecutorError("ROOT213 executor exceeded its bounded copy deadline")
        source = Path(item["source_path_provenance"])
        target = root / _safe_relative(item["target_relative_path"], item["logical_role"])
        if target.exists() or target.is_symlink():
            raise Root213ExecutorError(f"refusing existing target role: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        deferred = bool(item.get("deferred_content"))
        placeholder = bool(item.get("placeholder_only"))
        source_exists = source.is_file() and not source.is_symlink()
        # A stat-only placeholder may refer to an unavailable historical H5,
        # BI4, or raw path.  Its declared stat is evidence; attempting
        # ``stat()`` on the old path must not turn a typed-only relocation into
        # an original-source dependency.
        source_pre = (_full_stat(source, item["logical_role"] + ".source", allow_symlink=False)
                      if source_exists else _contract_stat(item, item["logical_role"] + ".source"))
        source_pre_sha: str | None = None
        if not placeholder:
            maximum = MAX_RESULT_BYTES if deferred else MAX_METADATA_BYTES
            source_pre_sha = _sha(source, item["logical_role"] + ".source", maximum=maximum)
            if source_pre_sha != item["source_sha256"]:
                raise Root213ExecutorError(f"source pre-copy SHA differs: {item['logical_role']}")

        if placeholder:
            declared_bytes = int(item.get("source_stat_provenance", {}).get("bytes", 1))
            if source.suffix.lower() not in PAYLOAD_SUFFIXES and declared_bytes > MAX_METADATA_BYTES:
                declared_bytes = 1
            with target.open("wb") as stream:
                stream.truncate(max(1, declared_bytes))
            mode = int(item.get("source_stat_provenance", {}).get("mode_bits", 0o664)) & 0o7777
            os.chmod(target, mode)
            mtime = item.get("source_stat_provenance", {}).get("mtime_ns")
            if isinstance(mtime, int):
                os.utime(target, ns=(mtime, mtime))
        else:
            copy_source = source.resolve() if source.is_symlink() else source
            shutil.copy2(copy_source, target)
            if item.get("executable_environment_exception"):
                target.chmod(target.stat().st_mode | 0o111)

        target_stat = _full_stat(target, item["logical_role"] + ".target")
        target_sha: str | None = None
        if not placeholder:
            maximum = MAX_RESULT_BYTES if deferred else MAX_METADATA_BYTES
            target_sha = _sha(target, item["logical_role"] + ".target", maximum=maximum)
            if not deferred and target_sha != item["source_sha256"]:
                raise Root213ExecutorError(f"target SHA differs: {item['logical_role']}")
            if deferred and target_sha != item["source_sha256"]:
                raise Root213ExecutorError(f"deferred V16 target SHA differs: {item['logical_role']}")
        source_post = (_full_stat(source, item["logical_role"] + ".source_post", allow_symlink=False)
                       if source_exists else _contract_stat(item, item["logical_role"] + ".source_post"))
        source_post_sha: str | None = None
        if not placeholder:
            maximum = MAX_RESULT_BYTES if deferred else MAX_METADATA_BYTES
            source_post_sha = _sha(source, item["logical_role"] + ".source_post", maximum=maximum)
            if source_post_sha != source_pre_sha or source_post_sha != item["source_sha256"]:
                raise Root213ExecutorError(f"source changed during copy: {item['logical_role']}")
        audit.append({
            "logical_role": item["logical_role"], "source_path_provenance": str(source),
            "target_relative_path": item["target_relative_path"],
            "source_pre_stat": source_pre, "source_post_stat": source_post,
            "source_pre_sha256": source_pre_sha or item["source_sha256"],
            "source_post_sha256": source_post_sha or item["source_sha256"],
            "target_post_stat": target_stat, "target_sha256": target_sha,
            "source_path_existed_at_copy": source_exists,
            "content_read_after_parent_reservation": not placeholder,
            "deferred_payload": deferred, "stat_only_placeholder": placeholder,
            "source_inode_mtime_equivalence": "NOT_CLAIMED",
        })
    return audit


def _set_parent_death_signal() -> None:
    try:
        import ctypes
        libc = ctypes.CDLL(None)
        if int(libc.prctl(1, signal.SIGTERM, 0, 0, 0)) != 0:
            raise OSError("prctl(PR_SET_PDEATHSIG) failed")
    except (AttributeError, OSError) as error:
        raise Root213ExecutorError(f"parent-death signal unavailable: {error}") from error


def _run_pinned_v2(*, overlay_path: Path, output_relative: str,
                   parent_pid: int, python_source: Path,
                   max_wall_seconds: float) -> dict[str, Any]:
    """Run V2's real worker with the explicitly pinned project environment.

    The project ``.venv`` is the one allowed environment exception: copying
    its interpreter binary together with ``pyvenv.cfg`` would make CPython
    derive a new prefix and silently lose the pinned NumPy ABI.  The worker
    code and every scientific/source role are still target-relative copied
    files; only argv[0] is the declared, SHA-bound environment path.  This
    small supervisor mirrors V2's guard boundary so that the consumed V2
    module remains byte-frozen.
    """
    if os.getppid() != int(parent_pid):
        raise Root213ExecutorError("pinned V2 guard is not under declared parent")
    checked = V2.validate_request_overlay(overlay_path)
    root = checked["root"]
    output = root / _safe_relative(output_relative, "V2 output")
    if output.exists() or output.is_symlink():
        raise Root213ExecutorError(f"refusing existing V2 output: {output}")
    stdout = root / (str(Path(output_relative).with_suffix(".stdout.log")))
    stderr = root / (str(Path(output_relative).with_suffix(".stderr.log")))
    for path in (stdout, stderr):
        if path.exists() or path.is_symlink():
            raise Root213ExecutorError(f"refusing existing V2 log: {path}")
    if not python_source.is_file():
        raise Root213ExecutorError(f"pinned project interpreter is unavailable: {python_source}")
    if not os.access(python_source, os.X_OK):
        raise Root213ExecutorError("pinned project interpreter is not executable")
    copied_entrypoint = checked["runtime_paths"]["portable_rebind_v2_entrypoint"]
    command = [str(python_source), "-B", "-I", str(copied_entrypoint), "worker",
               "--request", str(checked["request_path"]), "--output", str(output),
               "--parent-pid", str(os.getpid())]
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        environment[key] = "1"
    child = subprocess.Popen(command, cwd=str(root), env=environment,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             start_new_session=True, close_fds=True)
    old_term = signal.getsignal(signal.SIGTERM)
    old_int = signal.getsignal(signal.SIGINT)

    def _cancel(signum: int, _frame: Any) -> None:
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        raise KeyboardInterrupt(f"ROOT213 V2 worker cancelled by signal {signum}")

    signal.signal(signal.SIGTERM, _cancel)
    signal.signal(signal.SIGINT, _cancel)
    try:
        returncode, stream_info = V2._drain_child(
            child, max_wall=float(max_wall_seconds),
            stdout_path=stdout, stderr_path=stderr)
    except KeyboardInterrupt as error:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait(timeout=5.0)
        raise Root213ExecutorError(str(error)) from error
    finally:
        signal.signal(signal.SIGTERM, old_term)
        signal.signal(signal.SIGINT, old_int)
    if stream_info["timed_out"]:
        raise Root213ExecutorError("V2 child exceeded bounded deadline")
    if returncode != 0:
        tail = stderr.read_text(encoding="utf-8", errors="replace") if stderr.exists() else ""
        raise Root213ExecutorError(f"V2 child failed with return code {returncode}: {tail[-1000:]}")
    report = _json(output, "V2 child report")
    if report.get("status") != "PASS_RELOCATED_V8_V12_TYPED_SCORER":
        raise Root213ExecutorError("V2 child report is not a successful V8/V12/scorer result")
    receipt: dict[str, Any] = {
        "schema": "ds02.stage2.f2-typed-only-portable-rebind-guard-receipt.v2",
        "status": "COMPLETE_RELOCATED_TYPED_ONLY_V2",
        "request_file_sha256": _sha(checked["request_path"], "V2 overlay"),
        "report_sha256": _sha(output, "V2 report"),
        "report_target_relative_path": str(output.relative_to(root)),
        "stdout_target_relative_path": str(stdout.relative_to(root)),
        "stderr_target_relative_path": str(stderr.relative_to(root)),
        "stream_accounting": stream_info, "child_returncode": returncode,
        "parent_death_signal": "SIGTERM", "source_fallback": "REJECT",
        "pinned_environment_exception": str(python_source),
        "ledger_mutated": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "portable_cold_replay_credit": "NOT_CLAIMED",
    }
    receipt["sha256"] = _canonical(receipt)
    receipt_path = output.with_suffix(".guard-receipt.json")
    if receipt_path.exists() or receipt_path.is_symlink():
        raise Root213ExecutorError(f"refusing existing V2 receipt: {receipt_path}")
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def run(*, request_path: Path | str, output_root: Path | str, parent_pid: int,
        max_wall_seconds: float) -> dict[str, Any]:
    if os.getppid() != int(parent_pid):
        raise Root213ExecutorError("executor is not directly owned by declared parent")
    if max_wall_seconds <= 0 or max_wall_seconds > 900:
        raise Root213ExecutorError("ROOT213 executor wall bound must be in (0, 900]")
    _set_parent_death_signal()
    started = time.monotonic()
    deadline = started + float(max_wall_seconds)
    request_file = _abs(str(request_path), "ROOT213 request")
    ROOT213.validate_request(request_file)
    request = _json(request_file, "ROOT213 request")
    if request.get("schema") != REQUEST_SCHEMA:
        raise Root213ExecutorError("ROOT213 schema differs")
    root = _abs(str(output_root), "ROOT213 fresh output root")
    if root.exists() or root.is_symlink():
        raise Root213ExecutorError(f"refusing existing ROOT213 target namespace: {root}")
    root.mkdir(parents=True)
    if time.monotonic() >= deadline:
        raise Root213ExecutorError("ROOT213 executor deadline expired during metadata validation")
    manifest_path, contract_path, built = _make_manifest(request, root, started)
    table: _ArtifactTable = built["table"]
    copy_audit = _copy_roles(table, root, deadline=deadline)
    sealed_path = root / "metadata" / "root213-sealed-overlay.json"
    V1.seal_contract(contract_path=contract_path, output=sealed_path, verify_deferred_content=False)
    V1.validate_sealed(sealed_path, verify_deferred_content=False)
    overlay_path = root / "requests" / "root200-v2-rebound-overlay.json"
    V2.build_request_overlay(contract_path=contract_path, request_role="root200_inner_request",
                             output=overlay_path, request_target_relative="requests/rebound-inner.json",
                             request_id=request["attempt_id"])
    checked = V2.validate_request_overlay(overlay_path)
    python_target = root / "environment/python"
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise Root213ExecutorError("ROOT213 executor deadline expired before private V2 child")
    pinned_python = _abs(request["v2_interface"]["literal_python"],
                         "ROOT213 pinned project interpreter", allow_symlink=True)
    guard_receipt = _run_pinned_v2(overlay_path=overlay_path,
                                   output_relative="reports/v2-report.json",
                                   parent_pid=int(parent_pid),
                                   python_source=pinned_python,
                                   max_wall_seconds=remaining)
    v2_report_path = root / "reports/v2-report.json"
    v2_report = _json(v2_report_path, "ROOT213 V2 report")
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA, "status": "COMPLETE_ROOT213_TYPED_ONLY_PORTABLE_EXECUTOR",
        "request": {"path": str(request_file), "file_sha256": _sha(request_file, "ROOT213 request")},
        "attempt_id": request["attempt_id"], "case_id": request["case_id"],
        "parent": {"pid": int(parent_pid), "direct_child_verified": True,
                    "reservation_owned_by_parent": True, "ledger_created_or_mutated": False},
        "copy_contract": {"manifest": {"path": str(manifest_path), "sha256": _sha(manifest_path, "copy manifest")},
                          "contract": {"path": str(contract_path), "sha256": _sha(contract_path, "copy contract")},
                          "sealed_overlay": {"path": str(sealed_path), "sha256": _sha(sealed_path, "sealed overlay")},
                          "role_count": len(copy_audit), "roles": copy_audit,
                          "content_phase": "AFTER_PARENT_RESERVATION"},
        "v2_overlay": {"path": str(overlay_path), "sha256": _sha(overlay_path, "V2 overlay"),
                       "report": {"path": str(v2_report_path), "sha256": _sha(v2_report_path, "V2 report")},
                       "guard_receipt": guard_receipt},
        "execution": {"v8_validator": True, "v12_validator": True, "typed_scorer": True,
                       "model_invoked": False, "cfd_invoked": False, "raw_opened": False,
                       "hdf5_or_bi4_content_read": False,
                       "deferred_v16_content_read_after_reservation": True,
                       "elapsed_wall_seconds": time.monotonic() - started,
                       "bounded_wall_seconds": float(max_wall_seconds),
                       "parent_death_signal": "SIGTERM", "original_path_fallback": "REJECT"},
        "v2_report_status": v2_report.get("status"), "portable_cold_replay_credit": "NOT_CLAIMED",
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "quality": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "ledger_mutated": False, "payload_read_by_builder": False,
    }
    report["sha256"] = _canonical(report)
    report_path = root / "reports/root213-executor-report.json"
    if report_path.exists():
        raise Root213ExecutorError(f"refusing existing executor report: {report_path}")
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"schema": REPORT_SCHEMA, "status": report["status"], "report": str(report_path),
            "report_sha256": _sha(report_path, "ROOT213 executor report"),
            "v2_status": v2_report.get("status"), "result_bytes":
                next((item["target_post_stat"]["bytes"] for item in copy_audit
                      if item["logical_role"] == "root179c_v16_result_deferred"), None),
            "payload_read": True, "hdf5_or_bi4_content_read": False,
            "portable_cold_replay_credit": "NOT_CLAIMED"}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--output-root", type=Path, required=True)
    run_parser.add_argument("--parent-pid", type=int, required=True)
    run_parser.add_argument("--max-wall-seconds", type=float, default=900.0)
    check = sub.add_parser("validate")
    check.add_argument("--request", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "validate":
            value = ROOT213.validate_request(args.request)
        else:
            value = run(request_path=args.request, output_root=args.output_root,
                        parent_pid=args.parent_pid, max_wall_seconds=args.max_wall_seconds)
        print(json.dumps(value, sort_keys=True, ensure_ascii=True, default=str))
        return 0
    except (Root213ExecutorError, ROOT213.Root213Error, V1.PortableRebindError,
            V2.PortableRebindV2Error, OSError, ValueError, KeyError) as error:
        print(f"ROOT213 portable typed executor: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
