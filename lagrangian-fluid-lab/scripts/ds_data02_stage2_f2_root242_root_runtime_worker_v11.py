#!/usr/bin/env python3
"""Copied V11 child entrypoint with a runtime OS-open audit.

This file is copied into the parent-owned target root and is invoked with the
literal pinned interpreter.  The audit hook is installed before the copied
V2 entrypoint and its V8/V12/scorer modules are imported.  A path is allowed
only when it is inside the fresh target, the explicitly declared project
environment, or a small system-runtime allowlist.  Original DATA/worktree
paths and unbound absolute paths fail closed.  This worker has no ledger
access and never reads a production payload outside the parent-bound role
copy phase.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import sys
from typing import Any, Mapping, Sequence


POLICY_SCHEMA = "ds02.stage2.f2-runtime-open-policy.v1"
REPORT_STATUS = "PASS_RELOCATED_V8_V12_TYPED_SCORER"


class RuntimeOpenPolicyError(RuntimeError):
    pass


class _OpenPolicy:
    def __init__(self, value: Mapping[str, Any]) -> None:
        if value.get("schema") != POLICY_SCHEMA:
            raise RuntimeOpenPolicyError("runtime open policy schema differs")
        self.root = self._path(value.get("target_root"), "target_root")
        self.allowed = [self._path(item, "allowed_root") for item in value.get("allowed_roots", [])]
        target_values = value.get("target_roots", [value.get("target_root")])
        environment_values = value.get("environment_roots", [])
        if not isinstance(target_values, list) or not isinstance(environment_values, list):
            raise RuntimeOpenPolicyError("runtime open policy root sets are malformed")
        self.target_roots = [self._path(item, "target_root") for item in target_values]
        self.environment_roots = [self._path(item, "environment_root") for item in environment_values]
        if not self.environment_roots:
            self.environment_roots = [item for item in self.allowed if item != self.root]
        self.venv_root = self._path(value.get("venv_root"), "venv_root")
        site_values = value.get("venv_site_packages", [])
        if not isinstance(site_values, list) or any(not isinstance(item, str) for item in site_values):
            raise RuntimeOpenPolicyError("runtime open policy site-packages list is malformed")
        self.venv_site_packages = [self._path(item, "venv_site_packages") for item in site_values]
        if not all(self._under(item, self.venv_root) for item in self.venv_site_packages):
            raise RuntimeOpenPolicyError("runtime site-packages escape pinned venv")
        self.forbidden = [self._path(item, "forbidden_root") for item in value.get("forbidden_roots", [])]
        if not self.allowed or not self.forbidden:
            raise RuntimeOpenPolicyError("runtime open policy lacks allow/deny roots")
        self.allowed_count = 0
        self.open_count = 0
        self.chdir_count = 0
        self.blocked: list[str] = []

    @staticmethod
    def _path(value: Any, role: str) -> Path:
        if not isinstance(value, str) or not value.startswith("/"):
            raise RuntimeOpenPolicyError(f"{role} must be absolute")
        return Path(value).expanduser()

    @staticmethod
    def _under(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    def _candidates(self, value: Any) -> tuple[Path, Path] | None:
        if isinstance(value, int):
            # fd-based opens are already bound by the parent/runtime process;
            # they do not contain an external path to audit.
            return None
        if isinstance(value, bytes):
            try:
                value = os.fsdecode(value)
            except Exception:
                raise RuntimeOpenPolicyError("runtime open path is not decodable")
        if not isinstance(value, (str, os.PathLike)):
            raise RuntimeOpenPolicyError("runtime open path is not path-like")
        text = os.fspath(value)
        if isinstance(text, bytes):
            text = os.fsdecode(text)
        raw = Path(text)
        lexical = raw if raw.is_absolute() else Path.cwd() / raw
        lexical = Path(os.path.abspath(os.path.normpath(str(lexical))))
        # realpath detects a symlink in the copied tree that points back to an
        # original source.  It intentionally does not require the target to
        # exist, so missing paths are checked under the same policy.
        resolved = Path(os.path.realpath(str(lexical)))
        return lexical, resolved

    def check(self, value: Any, event: str) -> None:
        candidates = self._candidates(value)
        if candidates is None:
            return
        lexical, resolved = candidates
        # A resolved source path is rejected even if its symlinked lexical
        # spelling is under the fresh root.  The explicit environment
        # exception is checked before the deny roots for the pinned venv.
        # Both spellings must be inside the same explicit root.  Checking
        # lexical *or* resolved membership lets /proc/self/root/home/... or a
        # copied-tree symlink escape the policy.
        environment_allowed = any(
            self._under(lexical, item) and self._under(resolved, item)
            for item in self.environment_roots
        )
        target_allowed = any(
            self._under(lexical, item) and self._under(resolved, item)
            for item in self.target_roots
        )
        forbidden = any(self._under(lexical, item) or self._under(resolved, item)
                        for item in self.forbidden)
        if forbidden and not environment_allowed and not target_allowed:
            self.blocked.append(str(lexical))
            raise RuntimeOpenPolicyError(
                f"ROOT242 V11 OPEN_POLICY_REJECTED event={event} path={lexical}")
        if not (environment_allowed or target_allowed):
            self.blocked.append(str(lexical))
            raise RuntimeOpenPolicyError(
                f"ROOT242 V11 OPEN_POLICY_REJECTED unbound event={event} path={lexical}")
        self.allowed_count += 1

    def summary(self) -> dict[str, Any]:
        return {
            "schema": POLICY_SCHEMA,
            "hook_installed": True,
            "events_audited": ["open", "os.chdir"],
            "open_events_allowed": self.allowed_count,
            "open_events_observed": self.open_count,
            "chdir_events_observed": self.chdir_count,
            "blocked_events": len(self.blocked),
            "blocked_paths": list(self.blocked[-4:]),
            "original_path_fallback": "REJECT",
            "environment_exception": "EXPLICIT_PINNED_PROJECT_VENV_AND_SYSTEM_RUNTIME",
        }


def _read_policy(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1 * 1024 * 1024:
        raise RuntimeOpenPolicyError("runtime open policy is unavailable or oversized")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeOpenPolicyError("runtime open policy must be an object")
    return value


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeOpenPolicyError(f"cannot load copied runtime module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _set_pdeathsig() -> None:
    libc = ctypes.CDLL(None)
    if int(libc.prctl(1, signal.SIGTERM, 0, 0, 0)) != 0:
        raise RuntimeOpenPolicyError("PR_SET_PDEATHSIG failed")


def run(*, root: Path, policy_path: Path, v2_entrypoint: Path,
        overlay: Path, output: Path, parent_pid: int) -> dict[str, Any]:
    if os.getppid() != int(parent_pid):
        raise RuntimeOpenPolicyError("V11 runtime worker is not directly owned")
    _set_pdeathsig()
    policy = _OpenPolicy(_read_policy(policy_path))

    def audit(event: str, args: tuple[Any, ...]) -> None:
        if event == "open":
            policy.open_count += 1
            if not args:
                raise RuntimeOpenPolicyError("open event lacks a path")
            policy.check(args[0], event)
        elif event == "os.chdir":
            policy.chdir_count += 1
            if not args:
                raise RuntimeOpenPolicyError("chdir event lacks a path")
            policy.check(args[0], event)

    sys.addaudithook(audit)
    root = root.absolute()
    entry = v2_entrypoint.absolute()
    if not entry.is_file() or entry.is_symlink():
        raise RuntimeOpenPolicyError("copied V2 entrypoint is unavailable")
    # The copied V2 explicitly loads V8/V12/scorer files, while those modules
    # import the copied replay siblings by basename.  These are the only
    # non-system sys.path entries; no original worktree path is inherited.
    runtime_dir = root / "runtime"
    system_paths = [
        item for item in sys.path
        if item.startswith(("/usr/", "/lib", "/bin", "/sbin"))
    ]
    # Preserve imports from the exact pinned environment.  The prior worker
    # kept only .venv/bin and system paths, which silently selected the
    # system NumPy/h5py ABI.  Site-packages are policy-bound descendants of
    # the literal interpreter's pyvenv.cfg root.
    sys.path[:] = [str(entry.parent), str(runtime_dir)] + [
        str(item) for item in policy.venv_site_packages
    ] + system_paths
    module = _load(entry, "ds02_root242_v11_copied_v5_entrypoint")
    # The sealed production entrypoint is V5.  V5 patches only the recursive
    # metadata views and dispatches to the copied V2 CLI; it intentionally
    # does not expose V2's private ``_worker_run`` symbol.  Calling its real
    # ``main`` keeps the actual V5 -> V2 -> V8/V12/scorer boundary intact.
    main = getattr(module, "main", None)
    if not callable(main):
        raise RuntimeOpenPolicyError("copied V5 entrypoint lacks main")
    status = int(main([
        "worker", "--request", str(overlay), "--output", str(output),
        "--parent-pid", str(parent_pid),
    ]))
    if status != 0:
        raise RuntimeOpenPolicyError(f"copied V5/V2 worker returned {status}")
    if not output.is_file() or output.is_symlink():
        raise RuntimeOpenPolicyError("copied V2 worker did not write its report")
    report = json.loads(output.read_text(encoding="utf-8"))
    if not isinstance(report, Mapping) or report.get("status") != REPORT_STATUS:
        raise RuntimeOpenPolicyError("copied V2 report is not a successful V8/V12/scorer result")
    # V2 wrote the report before this worker can expose the audit summary.  It
    # is a target-side report, so updating only this additive audit field does
    # not alter any bound source/result bytes.
    if output.is_file() and not output.is_symlink():
        value = json.loads(output.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise RuntimeOpenPolicyError("copied V2 report is not a JSON object")
        value["runtime_open_audit"] = policy.summary()
        canonical = getattr(module, "_canonical", None)
        if callable(canonical):
            value["sha256"] = canonical(value)
        output.write_text(json.dumps(value, indent=2, sort_keys=True,
                                     ensure_ascii=True, allow_nan=False) + "\n",
                          encoding="utf-8")
    return {"status": str(report["status"]), "report_path": str(output),
            "runtime_open_audit": policy.summary()}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    worker = sub.add_parser("worker")
    worker.add_argument("--root", type=Path, required=True)
    worker.add_argument("--policy", type=Path, required=True)
    worker.add_argument("--v2-entrypoint", type=Path, required=True)
    worker.add_argument("--overlay", type=Path, required=True)
    worker.add_argument("--output", type=Path, required=True)
    worker.add_argument("--parent-pid", type=int, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        value = run(root=args.root, policy_path=args.policy,
                    v2_entrypoint=args.v2_entrypoint, overlay=args.overlay,
                    output=args.output, parent_pid=args.parent_pid)
        print(json.dumps(value, sort_keys=True, ensure_ascii=True))
        return 0
    except (RuntimeOpenPolicyError, OSError, ValueError, TypeError,
            json.JSONDecodeError) as error:
        print(f"ROOT242 V11 runtime worker: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
