#!/usr/bin/env python3
"""Run the relocated v15 consumer with an actual Python file-access audit.

The v18 runner recursively rewrote the role overlay, but its ``FORBIDDEN``
field was only a declaration.  This entrypoint installs ``sys.addaudithook``
before importing the copied consumer and rejects every Python-level open of a
bound original source path.  Bundle files, this copied runtime, the Python
standard library, and installed dependencies are permitted.  Unexpected data
paths are rejected as well, while the audit receipt keeps the observed open
paths and rejection reason.

The hook observes Python ``open``/``os.open`` audit events.  Native HDF5 C
opens are not guaranteed to emit Python audit events; the strict role overlay,
content hashes, and v15 source validation remain the source-path controls for
those opens.  This runner therefore reports the observation boundary instead
of claiming an OS-level syscall trace.
"""
from __future__ import annotations

import argparse
from collections import Counter
import importlib.util
import json
import os
from pathlib import Path
import sys
import sysconfig
from typing import Any, Iterable, Mapping, Sequence


class ReplayV20BindingError(ValueError):
    """Raised when the relocated full-window consumer cannot be bound."""


class ReplayV20AccessAuditViolation(ReplayV20BindingError):
    """Raised when a consumer attempts to open an original or unknown path."""

    def __init__(self, message: str, audit: "AccessAudit") -> None:
        super().__init__(message)
        self.audit = audit


def _runtime_roots() -> tuple[Path, Path]:
    replay_root = Path(__file__).resolve().parent
    portable_root = replay_root.parent / "portable"
    return replay_root, portable_root


def _load_portable() -> Any:
    _, portable_root = _runtime_roots()
    sys.path.insert(0, str(portable_root))
    path = portable_root / "ds_data02_stage2_f2_portable_v20.py"
    spec = importlib.util.spec_from_file_location("ds_data02_stage2_f2_portable_v20_runtime", path)
    if spec is None or spec.loader is None:
        raise ReplayV20BindingError(f"portable v20 worker is unavailable: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_replay() -> Any:
    replay_root, _ = _runtime_roots()
    sys.path.insert(0, str(replay_root))
    try:
        import ds_data02_stage2_f2_replay_v15 as replay  # type: ignore
    except ImportError as error:
        raise ReplayV20BindingError("copied v15 replay module is unavailable") from error
    return replay


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ReplayV20BindingError(f"cannot read JSON: {path}: {error}") from error
    if not isinstance(value, dict):
        raise ReplayV20BindingError(f"JSON object required: {path}")
    return value


def _path_map(path: Path) -> dict[str, str]:
    value = _load_json(path)
    if isinstance(value.get("path_map"), Mapping):
        value = value["path_map"]
    if not isinstance(value, Mapping):
        raise ReplayV20BindingError("path map must be an object or a receipt containing path_map")
    result = {str(key): str(item) for key, item in value.items()}
    if any(not key or not item for key, item in result.items()):
        raise ReplayV20BindingError("path map contains an empty role or path")
    return result


def _overlay_receipt(path: Path) -> Mapping[str, Any]:
    """Load the complete overlay receipt, including verified content SHA."""
    return _load_json(path)


def _path_from_audit_args(event: str, args: tuple[Any, ...]) -> str | None:
    if event not in {"open", "os.open"} or not args:
        return None
    candidate = args[0]
    if isinstance(candidate, bytes):
        return os.fsdecode(candidate)
    if isinstance(candidate, (str, os.PathLike)):
        return os.fsdecode(candidate)
    # Integer file descriptors are already-open handles and do not identify a
    # source path that this hook can safely classify.
    return None


def _resolve_path(value: str) -> Path:
    # ``strict=False`` is deliberate: a stale original path must still be
    # rejected when the source has already disappeared.
    return Path(value).expanduser().resolve(strict=False)


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _common_bundle_root(path_map: Mapping[str, str]) -> Path | None:
    values: list[str] = []
    for value in path_map.values():
        try:
            values.append(str(_resolve_path(value).parent))
        except (OSError, RuntimeError, TypeError):
            continue
    if not values:
        return None
    try:
        return _resolve_path(os.path.commonpath(values))
    except (OSError, RuntimeError, ValueError):
        return None


def _absolute_strings(value: Any) -> Iterable[str]:
    """Yield absolute local paths embedded in source/profile/request JSON."""
    if isinstance(value, Mapping):
        for item in value.values():
            yield from _absolute_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _absolute_strings(item)
    elif isinstance(value, str) and value.startswith("/"):
        # URI provenance is not an openable local path.  Keep local absolute
        # paths only, including stale paths that no longer exist.
        if "://" not in value:
            yield value


def _installed_roots() -> set[Path]:
    roots: set[Path] = set()
    for value in (sys.prefix, sys.base_prefix, sys.executable, os.__file__):
        if not value:
            continue
        try:
            path = _resolve_path(str(value))
        except (OSError, RuntimeError):
            continue
        roots.add(path if path.is_dir() else path.parent)
    for value in sysconfig.get_paths().values():
        try:
            roots.add(_resolve_path(str(value)))
        except (OSError, RuntimeError):
            pass
    # Extension loading can open system libraries before Python exposes a
    # module path.  These are runtime dependencies, not data inputs.
    for value in ("/lib", "/lib64", "/usr/lib", "/usr/lib64", "/usr/local/lib"):
        path = Path(value)
        if path.exists():
            roots.add(path.resolve())
    return roots


class AccessAudit:
    """Fail-closed Python file-open audit for one relocated replay."""

    def __init__(self, profile: Mapping[str, Any], request: Mapping[str, Any],
                 path_map: Mapping[str, str], allowed_paths: Sequence[str] = ()) -> None:
        self.profile = profile
        self.request = request
        self.path_map = path_map
        self.records: list[dict[str, Any]] = []
        self._record_limit = 4096
        self._truncated = False
        self.installed = False
        self.active = False
        self.forbidden_paths = {
            str(_resolve_path(value))
            for value in set(_absolute_strings(profile)) | set(_absolute_strings(request))
        }
        roots: set[Path] = set()
        bundle = _common_bundle_root(path_map)
        if bundle is not None:
            roots.add(bundle)
        replay_root, portable_root = _runtime_roots()
        roots.update({replay_root, portable_root, replay_root.parent})
        roots.update(_installed_roots())
        for value in allowed_paths:
            try:
                path = _resolve_path(value)
            except (OSError, RuntimeError):
                continue
            roots.add(path if path.is_dir() else path.parent)
        self.allowed_roots = tuple(sorted(roots, key=str))

    def install(self) -> None:
        if self.installed:
            return
        self.installed = True
        self.active = True
        sys.addaudithook(self._hook)

    def deactivate(self) -> None:
        self.active = False

    def _classify(self, path: Path) -> tuple[bool, str]:
        resolved = str(path)
        if resolved in self.forbidden_paths:
            return False, "FORBIDDEN_ORIGINAL_SOURCE_PATH"
        if any(_is_under(path, root) for root in self.allowed_roots):
            return True, "ALLOWED_BUNDLE_RUNTIME_OR_DEPENDENCY"
        if resolved == os.devnull or resolved.startswith("/proc/") or resolved.startswith("/sys/"):
            return True, "ALLOWED_RUNTIME_VIRTUAL_PATH"
        return False, "UNEXPECTED_DATA_PATH"

    def _hook(self, event: str, *args: Any) -> None:
        # CPython calls an audit hook as ``hook(event, args_tuple)``.  Keeping
        # support for the flattened form makes the callback directly
        # testable without changing the production callback contract.
        audit_args = args[0] if len(args) == 1 and isinstance(args[0], tuple) else args
        raw_path = _path_from_audit_args(event, audit_args)
        if raw_path is None:
            return
        # The hook is permanently registered by CPython.  Deactivation makes
        # later calls in the same process inert without leaving a prior
        # replay's roots active for a second run.
        if not self.active:
            return
        try:
            path = _resolve_path(raw_path)
        except (OSError, RuntimeError) as error:
            allowed, reason = False, f"UNRESOLVABLE_PATH:{type(error).__name__}"
            resolved = raw_path
        else:
            allowed, reason = self._classify(path)
            resolved = str(path)
        record = {
            "event": event,
            "path": resolved,
            "mode_or_flags": repr(audit_args[1:3]),
            "allowed": allowed,
            "reason": reason,
        }
        if len(self.records) < self._record_limit:
            self.records.append(record)
        else:
            self._truncated = True
        if not allowed:
            raise ReplayV20AccessAuditViolation(
                f"file access audit rejected {event} path {resolved}: {reason}", self
            )

    def summary(self) -> dict[str, Any]:
        counts = Counter(record["reason"] for record in self.records)
        events = Counter(record["event"] for record in self.records)
        opened = sorted({record["path"] for record in self.records if record["allowed"]})
        rejected = sorted({record["path"] for record in self.records if not record["allowed"]})
        return {
            "schema": "ds02.stage2.f2-s1-python-open-audit.v20",
            "installed": self.installed,
            "active_at_summary": self.active,
            "audit_events": ["open", "os.open"],
            "observation_scope": "python_audit_hook_only; native_HDF5_C_open_not_guaranteed_visible",
            "allowed_roots": [str(root) for root in self.allowed_roots],
            "forbidden_original_path_count": len(self.forbidden_paths),
            "observed_open_file_count": len(opened),
            "observed_open_files": opened,
            "rejected_open_file_count": len(rejected),
            "rejected_open_files": rejected,
            "event_counts": dict(sorted(events.items())),
            "reason_counts": dict(sorted(counts.items())),
            "records": list(self.records),
            "records_truncated": self._truncated,
        }


def _failure_receipt(error: Exception, audit: AccessAudit | None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "ds02.stage2.f2-s1-replay-runner-report.v20",
        "status": "ACCESS_AUDIT_FAILED" if isinstance(error, ReplayV20AccessAuditViolation)
                  else "REPLAY_BINDING_FAILED",
        "error_type": type(error).__name__,
        "error": str(error),
        "trajectory_read": False,
        "model_invoked": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    if audit is not None:
        payload["access_audit"] = audit.summary()
    return payload


def run(profile: Mapping[str, Any], request: Mapping[str, Any], path_map: Mapping[str, str], *,
        io_slot_approved: bool = False, initial_frame_only: bool = False,
        audit_allowed_paths: Sequence[str] = (),
        overlay_receipt: Mapping[str, Any] | None = None) -> dict[str, Any]:
    # Metadata/profile/path-map reads happen before the hook.  Every consumer
    # import and every subsequent Python-level source open is audited.
    audit = AccessAudit(profile, request, path_map, audit_allowed_paths)
    audit.install()
    try:
        portable = _load_portable()
        try:
            portable.verify_relocated_profile(profile, path_map, full_replay=io_slot_approved)
            bound_request = portable.relocate_request_for_consumer(
                request, profile, path_map, overlay_receipt=overlay_receipt,
                io_slot_approved=io_slot_approved)
        except (OSError, portable.PortableV20BindingError) as error:
            raise ReplayV20BindingError(str(error)) from error
        replay = _load_replay()
        try:
            bound = replay.validate_request_v15(bound_request, verify_sources=True, verify_hdf5_stat=True)
        except ReplayV20AccessAuditViolation:
            raise
        except Exception as error:  # v15 has its own binding exception class
            raise ReplayV20BindingError(f"v15 preflight rejected relocated request: {error}") from error
        if io_slot_approved:
            try:
                result = (replay.read_hdf5_initial_frame_v15(bound_request, io_slot_approved=True)
                          if initial_frame_only else replay.read_hdf5_window_v15(bound_request, io_slot_approved=True))
            except ReplayV20AccessAuditViolation:
                raise
            except Exception as error:  # preserve the v15 operator's detailed failure
                raise ReplayV20BindingError(f"v15 relocated replay failed: {error}") from error
            result["runner_status"] = "COMPLETE_PROVISIONAL_H5_READ"
            result["trajectory_read"] = True
            result["source_validation"] = "V20_RECURSIVE_ROLE_OVERLAY_AND_STRICT_HASH_STAT_BEFORE_READ"
            result["original_path_fallback"] = "FORBIDDEN"
        else:
            result = {
                "schema": "ds02.stage2.f2-s1-replay-runner-report.v20",
                "status": "VALIDATED_PENDING_IO_SLOT",
                "request_id": bound_request.get("request_id"),
                "request_schema": bound_request.get("schema"),
                "source_validation": "V20_RECURSIVE_ROLE_OVERLAY_STRICT_HASH_STAT_NO_HDF5_CONTENT_READ",
                "verified_source_count": len(bound.get("_verified_sources", [])),
                "hdf5_content_sha256": bound.get("_verified_hdf5", {}).get("content_sha256"),
                "trajectory_read": False,
                "io_slot_approved": False,
                "original_path_fallback": "FORBIDDEN",
                "relocation": bound_request.get("relocation"),
                "model_invoked": False,
                "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
            }
        result.setdefault("model_invoked", False)
        result.setdefault("qualification", {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"})
        result["access_audit"] = audit.summary()
        result["typed_replay_scope"] = {
            "status": "DEVELOPMENT_ONLY",
            "raw_to_typed_reconstruction_invoked": False,
            "raw_to_label_complete": False,
            "qualification": "UNKNOWN",
        }
        return result
    except ReplayV20AccessAuditViolation:
        raise
    except ReplayV20BindingError as error:
        # Preserve the Python-open log when metadata binding itself fails; a
        # failed preflight is still useful evidence about which copied files
        # were reached before the rejection.
        error.audit = audit  # type: ignore[attr-defined]
        raise
    finally:
        audit.deactivate()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--path-map", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--io-slot-approved", action="store_true")
    parser.add_argument("--initial-frame-only", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"refusing to overwrite existing replay output: {args.output}")
    profile = _load_json(args.profile)
    request = _load_json(args.request)
    overlay_receipt = _overlay_receipt(args.path_map)
    path_map = _path_map(args.path_map)
    try:
        result = run(profile, request, path_map,
                     io_slot_approved=args.io_slot_approved,
                     initial_frame_only=args.initial_frame_only,
                     overlay_receipt=overlay_receipt,
                     audit_allowed_paths=(str(args.output), str(args.profile),
                                          str(args.request), str(args.path_map)))
    except (OSError, ReplayV20BindingError) as error:
        # Keep an immutable failure receipt for audit violations.  It is a new
        # destination and does not replace any prior v18/v20 result.
        audit = getattr(error, "audit", None)
        if audit is not None:
            failure = _failure_receipt(error, audit)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as stream:
                json.dump(failure, stream, indent=2, sort_keys=True, ensure_ascii=False)
                stream.write("\n")
            print(json.dumps({"status": failure["status"], "schema": failure["schema"]}, sort_keys=True),
                  file=sys.stderr)
            return 2
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  default=lambda value: value.tolist() if hasattr(value, "tolist") else str(value))
        stream.write("\n")
    print(json.dumps({"status": result["status"], "schema": result["schema"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
