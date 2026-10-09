#!/usr/bin/env python3
"""Run the immutable V2 native worker with owned decoder scratch.

The V2 worker remains the scientific converter and is copied into the private
runtime by the portable executor.  This small entry point is an additive
compatibility wrapper: it loads that copied worker, redirects Python's
``tempfile`` module to an attempt-owned directory, and wraps the copied
converter's ``decode_frame`` callback so every frame gets a private directory
which is removed before the next frame starts.  It never changes the V2
converter source or the producer raw-tree contract.

The wrapper is intentionally usable with the V2 command line.  It must be
launched from the copied bundle (the sibling ``runtime/native`` V2 role is the
only worker it imports), so a missing copied role fails closed instead of
falling back to a worktree module.  The wrapper itself does not own the stage2
ledger; its parent guard owns reservation, timeout, and terminal accounting.
"""
from __future__ import annotations

import contextlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any, Iterator, MutableMapping, Sequence


SCHEMA = "ds02.stage2.f2-native-raw-to-typed-label-scratch-wrapper.v3"
WORKER_NAME = "ds_data02_stage2_f2_native_raw_to_typed_label_v2.py"


class OwnedScratchError(RuntimeError):
    """Raised when the private decoder scratch contract cannot be enforced."""


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise OwnedScratchError(f"JSON object required: {path}")
    return value


def _write_new(path: Path, value: MutableMapping[str, Any]) -> None:
    if path.exists():
        raise OwnedScratchError(f"refusing to overwrite scratch report: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=True)
        stream.write("\n")


@contextlib.contextmanager
def owned_tempdir(root: Path) -> Iterator[Path]:
    """Make ``tempfile`` resolve only below a fresh attempt directory."""
    root = root.expanduser().resolve()
    if root.exists():
        raise OwnedScratchError(f"attempt scratch already exists: {root}")
    root.mkdir(parents=True, exist_ok=False)
    previous = tempfile.tempdir
    tempfile.tempdir = str(root)
    try:
        yield root
    finally:
        tempfile.tempdir = previous
        if root.exists():
            shutil.rmtree(root)


def install_decoder_scratch(loader: Any, state: MutableMapping[str, Any]) -> Any:
    """Wrap the converter returned for V2's raw-converter role.

    V2 dynamically calls its module-level ``_load_module`` from
    ``_capture_converter``.  Replacing that loader for the converter role
    lets this wrapper install the callback before V2 saves its
    ``original_decode`` reference.  The callback receives the converter's
    shared scratch path, but delegates through a fresh per-frame directory.
    """
    original_loader = loader._load_module

    def load_module(path: Path, name: str) -> Any:
        module = original_loader(path, name)
        if name != "_ds02_bound_converter_v2":
            return module
        original_decode = getattr(module, "decode_frame", None)
        if not callable(original_decode):
            raise OwnedScratchError("bound converter has no decode_frame callback")

        def decode_frame(frame_path: Path, decoder: Path, scratch_root: Path, index: int) -> Any:
            shared = Path(scratch_root).expanduser().resolve()
            if not shared.is_dir():
                raise OwnedScratchError(f"converter scratch is not a directory: {shared}")
            frame_dir = shared / f"owned-frame-{int(index):04d}"
            if frame_dir.exists():
                raise OwnedScratchError(f"decoder frame scratch already exists: {frame_dir}")
            frame_dir.mkdir()
            active = int(state.get("active_frame_directories", 0)) + 1
            state["active_frame_directories"] = active
            state["max_live_frame_directories"] = max(
                int(state.get("max_live_frame_directories", 0)), active
            )
            state["frames_started"] = int(state.get("frames_started", 0)) + 1
            try:
                # The upstream decoder creates ``frame_NNNN`` below the
                # supplied scratch root.  Giving it frame_dir makes all of
                # that output owned by this attempt and this frame.
                return original_decode(frame_path, decoder, frame_dir, int(index))
            finally:
                state["active_frame_directories"] = max(
                    0, int(state.get("active_frame_directories", 1)) - 1
                )
                if frame_dir.exists():
                    shutil.rmtree(frame_dir)
                state["frames_cleaned"] = int(state.get("frames_cleaned", 0)) + 1

        module.decode_frame = decode_frame
        state["converter_wrapper_installed"] = True
        return module

    loader._load_module = load_module
    return original_loader


def _worker_path() -> Path:
    # The wrapper is copied into target_root/sources/...; the immutable V2
    # worker is copied into target_root/runtime/native/....
    target_root = Path(__file__).resolve().parents[1]
    worker = target_root / "runtime" / "native" / WORKER_NAME
    if not worker.is_file():
        raise OwnedScratchError(f"copied V2 worker is missing: {worker}")
    return worker


def _load_worker() -> Any:
    path = _worker_path()
    spec = importlib.util.spec_from_file_location("_ds02_bound_worker_v2_for_v3", path)
    if spec is None or spec.loader is None:
        raise OwnedScratchError(f"cannot load copied V2 worker: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _option(argv: Sequence[str], name: str) -> Path | None:
    try:
        value = argv[list(argv).index(name) + 1]
    except (ValueError, IndexError):
        return None
    return Path(value).expanduser().resolve()


def _scratch_report_path(output_dir: Path | None, scratch_parent: Path) -> Path:
    if output_dir is not None and output_dir.is_dir():
        return output_dir / "owned-decoder-scratch-v3.json"
    return scratch_parent / f"{(output_dir or scratch_parent).name}.owned-decoder-scratch-v3.json"


def run(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    output_dir = _option(args, "--output-dir")
    if output_dir is None:
        raise OwnedScratchError("V2-compatible --output-dir is required")
    scratch_parent = output_dir.parent
    scratch_root = scratch_parent / f".owned-decoder-scratch-v3-{os.getpid()}"
    state: dict[str, Any] = {
        "schema": SCHEMA,
        "wrapper_version": "v3",
        "worker_command_compatibility": "ds_data02_stage2_f2_native_raw_to_typed_label_v2.py",
        "attempt_scratch_path": str(scratch_root),
        "scratch_scope": "parent-approved-attempt-owned",
        "per_frame_directory": True,
        "cleanup_after_each_frame": True,
        "default_tmp_forbidden": True,
        "status": "RUNNING",
        "frames_started": 0,
        "frames_cleaned": 0,
        "active_frame_directories": 0,
        "max_live_frame_directories": 0,
        "module_fallback": "FORBIDDEN",
    }
    worker = _load_worker()
    original_loader = None
    exit_code = 1
    try:
        with owned_tempdir(scratch_root):
            original_loader = install_decoder_scratch(worker, state)
            state["tempfile_gettempdir"] = tempfile.gettempdir()
            value = worker.main(args)
            exit_code = int(value or 0)
            state["status"] = "PASS_WORKER_RETURNED"
    except SystemExit as error:
        exit_code = int(error.code or 0)
        state["status"] = "WORKER_SYSTEM_EXIT" if exit_code == 0 else "FAILED_WORKER_SYSTEM_EXIT"
        state["error_code"] = exit_code
        raise
    except BaseException as error:
        state["status"] = "FAILED_SCRATCH_WRAPPER"
        state["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        if original_loader is not None:
            worker._load_module = original_loader
        state["active_frame_directories"] = 0
        state["attempt_scratch_removed"] = not scratch_root.exists()
        state["status"] = state.get("status", "FAILED")
        report_path = _scratch_report_path(output_dir, scratch_parent)
        try:
            _write_new(report_path, state)
        except Exception:
            # A worker's own failure must remain the primary failure.  The
            # parent can classify missing scratch evidence conservatively.
            pass
    return exit_code


def main(argv: Sequence[str] | None = None) -> int:
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
