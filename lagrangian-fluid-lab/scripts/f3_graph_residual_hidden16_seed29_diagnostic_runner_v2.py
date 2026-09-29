#!/usr/bin/env python3
"""Receipt-bound residual seed29 runner v2.

The default mode is a read-only dry-run over an already issued admission
receipt.  This revision deliberately has no admitted execution capability:
even ``--diagnostic-execute`` fails before receipt consumption and before
``subprocess.Popen``.  It also has no terminal-receipt producer.  A future
trusted runtime must provide a sealed real Popen/wait witness and an
independent, stable-FD HDF5 validator; declarations or caller callbacks can
never substitute for those proofs.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from typing import Any

try:
    import h5py
except (ImportError, ValueError):  # ABI mismatch is a fail-closed validator absence.
    h5py = None  # type: ignore[assignment]

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.dont_write_bytecode = True

from scripts import f3_graph_residual_hidden16_current_manifest_rollout_launcher_v1 as launcher
from scripts import f3_graph_residual_hidden16_seed29_diagnostic_admission_v1 as admission


LAB_ROOT = Path(__file__).resolve().parents[1]
SEED = admission.SEED
GPU_INDEX = admission.GPU_INDEX
MODEL = admission.MODEL
HIDDEN = admission.HIDDEN
UPDATES = admission.UPDATES
CASE_ID = admission.CASE_ID
SPLIT = admission.SPLIT
TRANSITIONS = admission.TRANSITIONS
FRAMES = admission.FRAMES
SCHEMA = "core.f3.graph_residual.hidden16.seed29.diagnostic_runner.v2"
REPORT_SCHEMA = f"{SCHEMA}.report"
TERMINAL_RECEIPT_SCHEMA = f"{SCHEMA}.terminal_receipt"
REPORT_ID = "f3-graph-residual-hidden16-seed29-diagnostic-runner-v2"
DEFAULT_REPORT = LAB_ROOT / "reports" / "F3-GRAPH-RESIDUAL-HIDDEN16-SEED29-DIAGNOSTIC-RUNNER-V2-2026-09-29.json"
DEFAULT_MARKDOWN = DEFAULT_REPORT.with_suffix(".zh-CN.md")
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_HDF5_BYTES = 2 * 1024 * 1024 * 1024
MAX_SOURCE_BYTES = 64 * 1024 * 1024
EVALUATOR_OUTPUT_NAMES = ("evaluation", "trajectory", "progress", "validator")
GPU_UUID_RE = re.compile(r"^GPU-[0-9A-Fa-f-]{8,}$")
PCI_BUS_RE = re.compile(r"^[0-9A-Fa-f]{4}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}\.[0-7]$")

ZERO_CREDIT: dict[str, Any] = dict(admission.ZERO_CREDIT)

EXECUTION_BLOCKERS = (
    "trusted one-shot receipt consumer is not independently admitted for execution",
    "source/runtime identity closure is diagnostic-only and has no external scheduler attestation",
    "GPU UUID/PCI mapping is a scheduler snapshot, not a trusted runtime proof",
    "sealed real subprocess.Popen/wait witness is not admitted",
    "stable-FD output lifecycle and independent HDF5 validator capability is not admitted",
    "terminal receipt minting is forbidden in this runner",
    "formal/credit promotion is permanently isolated",
)

# A private sentinel is intentionally never initialized.  The module exposes
# no Popen factory and no caller-provided authority object.
_SEALED_EXECUTION_CAPABILITY: object | None = None
_SEALED_POPEN = subprocess.Popen


class RunnerError(ValueError):
    """Malformed, drifting, unsafe, or non-authorizing runner input."""


def _fail(message: str) -> None:
    raise RunnerError(f"fail-closed: {message}")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{name} must be an object")
    return value


def _exact(value: Mapping[str, Any], key: str, expected: Any, name: str) -> None:
    if key not in value:
        _fail(f"{name}.{key} is missing")
    observed = value[key]
    if type(expected) is bool and type(observed) is not bool:
        _fail(f"{name}.{key} must be boolean")
    if type(expected) is int and type(observed) is not int:
        _fail(f"{name}.{key} must be integer")
    if observed != expected:
        _fail(f"{name}.{key} must be {expected!r}; observed {observed!r}")


def _unknown(value: Mapping[str, Any], allowed: set[str] | frozenset[str], name: str) -> None:
    extra = sorted(set(value) - set(allowed))
    if extra:
        _fail(f"{name} contains unknown fields: {extra}")


def _absolute(value: Path | str, name: str) -> Path:
    try:
        candidate = Path(os.fspath(value))
    except TypeError:
        _fail(f"{name} is not a path")
    if not candidate.is_absolute() or any(part in {".", ".."} for part in candidate.parts):
        _fail(f"{name} must be absolute and lexical-alias free")
    if Path(os.path.normpath(str(candidate))) != candidate:
        _fail(f"{name} uses a lexical path alias")
    return candidate


def _under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _reject_symlinks(path: Path, name: str) -> None:
    current = Path(path.anchor or os.sep)
    for part in path.parts[1:] if path.is_absolute() else path.parts:
        current /= part
        try:
            info = os.lstat(current)
        except OSError as error:
            _fail(f"cannot inspect {name}: {error}")
        if stat.S_ISLNK(info.st_mode):
            _fail(f"{name} contains a symlink component")


def _directory_descriptor(path: Path, name: str) -> dict[str, Any]:
    candidate = _absolute(path, name)
    _reject_symlinks(candidate, name)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(candidate, flags)
    except OSError as error:
        _fail(f"cannot open {name} as a stable directory: {error}")
    try:
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_nlink < 2:
            _fail(f"{name} is not a stable directory")
        return {
            "path": str(candidate), "dev": int(info.st_dev), "ino": int(info.st_ino),
            "mode": int(stat.S_IMODE(info.st_mode)), "uid": int(info.st_uid),
            "gid": int(info.st_gid), "nlink": int(info.st_nlink),
            "stable_fd": True, "path_reopened": False,
        }
    finally:
        os.close(fd)


def _stable_artifact(
    path: Path | str,
    root: Path | str,
    name: str,
    *,
    max_bytes: int,
    allow_leaf_symlink: bool = False,
    read_content: bool = True,
) -> tuple[dict[str, Any], bytes]:
    """Bind one regular artifact to a single stable descriptor read.

    The path is checked without following links, opened with O_NOFOLLOW, and
    read/hash-checked through the held descriptor.  No pathname is reopened
    for content, and hard-linked output files are rejected.
    """

    candidate = _absolute(path, f"{name}.path")
    scope = _absolute(root, f"{name}.root")
    if candidate == scope or not _under(candidate, scope):
        _fail(f"{name} escapes its bound root")
    _reject_symlinks(scope, f"{name} root")
    _reject_symlinks(candidate.parent, f"{name} parent")
    try:
        leaf = os.lstat(candidate)
    except OSError as error:
        _fail(f"cannot inspect {name}: {error}")
    leaf_symlink = stat.S_ISLNK(leaf.st_mode)
    if leaf_symlink and not allow_leaf_symlink:
        _fail(f"{name} is a symlink")
    if not leaf_symlink and not stat.S_ISREG(leaf.st_mode):
        _fail(f"{name} must be a regular file")
    if not leaf_symlink and leaf.st_nlink != 1:
        _fail(f"{name} must not be hard-linked")
    if leaf.st_size > max_bytes:
        _fail(f"{name} exceeds its bounded size")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    if getattr(os, "O_NOFOLLOW", 0) == 0:
        _fail("platform lacks O_NOFOLLOW for stable artifact binding")
    try:
        fd = os.open(candidate, flags)
    except OSError as error:
        _fail(f"cannot open {name} without following links: {error}")
    chunks: list[bytes] = []
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            _fail(f"{name} opened descriptor is not a single-link regular file")
        if before.st_size > max_bytes:
            _fail(f"{name} grew beyond its bounded size")
        if read_content:
            remaining = max_bytes + 1
            while remaining > 0:
                block = os.read(fd, min(1024 * 1024, remaining))
                if not block:
                    break
                chunks.append(block)
                remaining -= len(block)
            if remaining == 0:
                _fail(f"{name} exceeded its bounded read")
        after = os.fstat(fd)
        parent_after = os.stat(candidate.parent, follow_symlinks=False)
        if (
            (before.st_dev, before.st_ino, before.st_mode, before.st_nlink, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            != (after.st_dev, after.st_ino, after.st_mode, after.st_nlink, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        ):
            _fail(f"{name} changed during stable descriptor read")
        if stat.S_ISLNK(parent_after.st_mode):
            _fail(f"{name} parent changed to a symlink")
        raw = b"".join(chunks) if read_content else b""
        descriptor = {
            "path": str(candidate),
            "resolved_path": str(candidate.resolve(strict=True)) if leaf_symlink else str(candidate),
            "dev": int(before.st_dev),
            "ino": int(before.st_ino),
            "bytes": int(before.st_size),
            "mode": int(stat.S_IMODE(before.st_mode)),
            "uid": int(before.st_uid),
            "gid": int(before.st_gid),
            "nlink": int(before.st_nlink),
            "mtime_ns": int(before.st_mtime_ns),
            "ctime_ns": int(before.st_ctime_ns),
            "parent_dev": int(parent_after.st_dev),
            "parent_ino": int(parent_after.st_ino),
            "sha256": hashlib.sha256(raw).hexdigest() if read_content else None,
            "leaf_symlink": leaf_symlink,
            "stable_fd": True,
            "fd_identity_stable": True,
            "path_reopened": False,
            "content_opened": bool(read_content),
        }
        return descriptor, raw
    except OSError as error:
        _fail(f"cannot read {name} through stable descriptor: {error}")
    finally:
        os.close(fd)


def _secure_artifact(path: Path | str, root: Path | str, name: str, *, max_bytes: int) -> tuple[dict[str, Any], bytes]:
    return _stable_artifact(path, root, name, max_bytes=max_bytes)


def _inspect_hdf5_snapshot(raw: bytes, *, required_datasets: Sequence[str]) -> dict[str, Any]:
    if h5py is None:
        _fail("independent h5py validator is unavailable")
    if not raw or len(raw) > MAX_HDF5_BYTES:
        _fail("HDF5 snapshot is empty or oversized")
    try:
        with h5py.File(io.BytesIO(raw), "r") as handle:
            links = 0
            for name in handle:
                links += 1
                link = handle.get(name, getlink=True)
                if isinstance(link, (h5py.ExternalLink, h5py.SoftLink)):
                    _fail("HDF5 external/soft links are not admitted")
            missing = [name for name in required_datasets if name not in handle]
            if missing:
                _fail(f"HDF5 required datasets are missing: {missing}")
            for name in required_datasets:
                item = handle[name]
                if not isinstance(item, h5py.Dataset):
                    _fail(f"HDF5 required path is not a dataset: {name}")
                if getattr(item, "is_virtual", False):
                    _fail(f"HDF5 virtual datasets are not admitted: {name}")
            return {
                "passed": True,
                "complete": True,
                "links_checked": links,
                "required_datasets": list(required_datasets),
                "stable_fd": True,
                "path_reopened": False,
                "content_opened": True,
            }
    except (OSError, ValueError, KeyError) as error:
        _fail(f"independent HDF5 validation failed: {error}")


def _descriptor_matches(observed: Mapping[str, Any], expected: Mapping[str, Any], name: str) -> None:
    for key in ("path", "dev", "ino", "bytes", "mode", "uid", "gid", "nlink", "mtime_ns", "ctime_ns", "parent_dev", "parent_ino", "sha256"):
        if observed.get(key) != expected.get(key):
            _fail(f"{name} identity drifted at {key}")
    _exact(expected, "stable_fd", True, name)
    _exact(expected, "fd_identity_stable", True, name)
    _exact(expected, "path_reopened", False, name)


def _runner_source_descriptor(root: Path) -> dict[str, Any]:
    expected = root / "scripts" / Path(__file__).name
    actual = Path(__file__).resolve()
    if expected != actual:
        _fail("runner source path is not the current residual runner module")
    return admission._file_descriptor(actual, "runner source", max_bytes=MAX_SOURCE_BYTES)


def _outputs(*args: Path | str) -> dict[str, Path]:
    if len(args) == 1:
        namespace = Path(args[0])
        root = LAB_ROOT
        nonce = admission._validate_nonce(namespace.name.rsplit("nonce", 1)[-1])
    elif len(args) == 3:
        root = Path(args[0])
        namespace = Path(args[1])
        nonce = admission._validate_nonce(args[2])
    else:
        _fail("_outputs expects namespace or root, namespace, nonce")
    outputs = dict(launcher._output_paths(namespace, root, SEED, nonce))
    # launcher._output_paths only needs the root for the process-proof path;
    # replace that root-bound path with the receipt's actual root below.
    return outputs


@dataclass(frozen=True)
class DiagnosticPlan:
    receipt_path: Path
    receipt: Mapping[str, Any]
    identity: Mapping[str, Any]
    namespace: Path
    command: tuple[str, ...]
    env: Mapping[str, str]
    outputs: Mapping[str, Path]
    input_descriptors: Mapping[str, Mapping[str, Any]]
    executable_descriptor: Mapping[str, Any]
    cwd_descriptor: Mapping[str, Any]
    runner_source_descriptor: Mapping[str, Any]
    binding_sha256: str

    @property
    def root(self) -> Path:
        return Path(self.identity["root"])

    @property
    def manifest_sha256(self) -> str:
        return self.identity["manifest"]["binding"]["canonical_sha256"]

    @property
    def gpu_identity(self) -> Mapping[str, Any]:
        return admission._gpu_identity(self.identity["resource_admission"]["gpu"])

    @property
    def effective_env_sha256(self) -> str:
        return canonical_digest(dict(self.env))

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA, "status": "dry_run_bound", "mode": "dry_run", "launch_allowed": False,
            "seed": SEED, "model_kind": MODEL, "hidden": HIDDEN, "updates": UPDATES,
            "case_id": CASE_ID, "split": SPLIT, "transitions": TRANSITIONS, "frames": FRAMES,
            "receipt_path": str(self.receipt_path), "receipt_sha256": self.receipt["receipt_sha256"],
            "identity_sha256": self.receipt["identity_sha256"], "namespace": str(self.namespace),
            "namespace_nonce": self.identity["nonce"], "command": list(self.command),
            "command_sha256": self.identity["command"]["sha256"], "env_overrides": dict(self.env),
            "gpu_identity": dict(self.gpu_identity), "effective_env_sha256": self.effective_env_sha256,
            "binding_sha256": self.binding_sha256,
            "input_descriptors": {key: dict(value) for key, value in self.input_descriptors.items()},
            "executable_descriptor": dict(self.executable_descriptor), "cwd_descriptor": dict(self.cwd_descriptor),
            "runner_source_descriptor": dict(self.runner_source_descriptor),
            "outputs": {key: str(value) for key, value in self.outputs.items()},
            "diagnostic_execute_allowed": False, "popen_attempted": False, "wait_attempted": False,
            "real_workload_started": 0, **ZERO_CREDIT,
        }


def _validate_identity_contract(receipt: Mapping[str, Any]) -> tuple[Mapping[str, Any], tuple[str, ...], dict[str, str]]:
    core = _mapping(receipt["identity"], "receipt.identity")
    for key, expected in {"seed": SEED, "run_id": admission.RUN_ID, "model_kind": MODEL, "hidden": HIDDEN, "updates": UPDATES, "case_id": CASE_ID, "split": SPLIT, "transitions": TRANSITIONS, "frames": FRAMES}.items():
        _exact(core, key, expected, "receipt.identity")
    command = _mapping(core.get("command"), "receipt.identity.command")
    argv = command.get("argv")
    if not isinstance(argv, list) or not argv or any(not isinstance(item, str) or not item or "\x00" in item for item in argv):
        _fail("receipt.identity.command.argv must be a non-empty string list")
    env = dict(_mapping(command.get("env_overrides"), "receipt.identity.command.env_overrides"))
    expected_env = {"CUDA_VISIBLE_DEVICES": str(GPU_INDEX), "CUDA_DEVICE_ORDER": admission.CUDA_DEVICE_ORDER, "PYTHONDONTWRITEBYTECODE": "1"}
    if env != expected_env:
        _fail("receipt identity environment drifted")
    root = _absolute(core["root"], "receipt.identity.root")
    _exact(command, "cwd", str(root), "receipt.identity.command")
    if command.get("sha256") != canonical_digest({"argv": argv, "cwd": str(root), "env_overrides": env, "seed": SEED, "gpu_index": GPU_INDEX}):
        _fail("receipt identity command digest drifted")
    manifest = _mapping(core.get("manifest"), "receipt.identity.manifest")
    manifest_binding = _mapping(manifest.get("binding"), "receipt.identity.manifest.binding")
    training = _mapping(core.get("training_receipt"), "receipt.identity.training_receipt")
    training_binding = _mapping(training.get("binding"), "receipt.identity.training_receipt.binding")
    checkpoint = _mapping(core.get("checkpoint"), "receipt.identity.checkpoint")
    executable = _mapping(core.get("executable"), "receipt.identity.executable")
    expected_command = launcher._build_command(
        root=root,
        python=Path(executable["path"]),
        manifest=Path(manifest_binding["path"]),
        checkpoint=Path(checkpoint["path"]),
        outputs={
            "evaluation": Path(str(core["namespace"]) + "-evaluation.json"),
            "trajectory": Path(str(core["namespace"]) + "-trajectory.h5"),
            "progress": Path(str(core["namespace"]) + "-evaluation-progress.json"),
        },
    )
    if tuple(argv) != tuple(expected_command):
        _fail("receipt identity command arguments drifted from residual current-manifest contract")
    if manifest_binding.get("path") != str(root / launcher.MANIFEST_RELATIVE):
        _fail("receipt identity manifest path drifted")
    if training_binding.get("path") != str(Path(training["file"]["path"])):
        _fail("receipt identity training path drifted")
    if checkpoint.get("path") != str(checkpoint["file"]["path"]):
        _fail("receipt identity checkpoint path drifted")
    return core, tuple(argv), env


def _environment_digest(environment: Mapping[str, str]) -> str:
    return canonical_digest(dict(environment))


def _binding_digest(plan_values: DiagnosticPlan | Mapping[str, Any]) -> str:
    if isinstance(plan_values, DiagnosticPlan):
        return canonical_digest(
            {
                "schema": SCHEMA,
                "receipt_sha256": plan_values.receipt["receipt_sha256"],
                "identity_sha256": plan_values.receipt["identity_sha256"],
                "root": str(plan_values.root),
                "namespace": str(plan_values.namespace),
                "nonce": plan_values.identity["nonce"],
                "command": list(plan_values.command),
                "env": dict(plan_values.env),
                "gpu_identity": dict(plan_values.gpu_identity),
                "input_descriptors": dict(plan_values.input_descriptors),
                "executable_descriptor": dict(plan_values.executable_descriptor),
                "cwd_descriptor": dict(plan_values.cwd_descriptor),
                "runner_source_descriptor": dict(plan_values.runner_source_descriptor),
                "outputs": {key: str(value) for key, value in plan_values.outputs.items()},
            }
        )
    return canonical_digest(plan_values)


def build_plan(
    receipt_path: Path | str,
    *,
    resource_admission: Mapping[str, Any] | None = None,
) -> DiagnosticPlan:
    """Bind an admission receipt and all stable input identities, without launch."""

    candidate = _absolute(receipt_path, "admission receipt")
    receipt = admission.load_receipt(candidate)
    admission.revalidate_receipt(receipt, resource_admission=resource_admission)
    core, command, env = _validate_identity_contract(receipt)
    root = _absolute(core["root"], "receipt.identity.root")
    namespace = _absolute(core["namespace"], "receipt.identity.namespace")
    if namespace != Path(receipt["namespace"]):
        _fail("receipt namespace drifted")
    _reject_symlinks(namespace, "receipt namespace")
    cwd_descriptor = _directory_descriptor(root, "bound cwd")
    executable_descriptor = dict(core["executable"])
    _descriptor_matches(admission._file_descriptor(Path(executable_descriptor["path"]), "executable", max_bytes=admission.MAX_EXECUTABLE_BYTES), executable_descriptor, "executable")
    input_descriptors: dict[str, Mapping[str, Any]] = {}
    manifest = core["manifest"]
    training = core["training_receipt"]
    checkpoint = core["checkpoint"]
    input_descriptors["manifest"] = manifest["file"]
    input_descriptors["training_receipt"] = training["file"]
    input_descriptors["checkpoint"] = checkpoint["file"]
    for key, descriptor in dict(core["source_files"]).items():
        input_descriptors[f"source.{key}"] = descriptor
    for name, descriptor in input_descriptors.items():
        limit = admission.MAX_CHECKPOINT_BYTES if name == "checkpoint" else (
            admission.MAX_JSON_BYTES if name in {"manifest", "training_receipt"} else admission.MAX_SOURCE_BYTES
        )
        observed = admission._file_descriptor(Path(descriptor["path"]), name, max_bytes=limit)
        admission._descriptor_equal(observed, descriptor, name)
    outputs = dict(launcher._output_paths(namespace, root, SEED, core["nonce"]))
    outputs["terminal_receipt"] = Path(str(namespace) + "-terminal-receipt.json")
    stored_outputs = _mapping(core.get("outputs"), "receipt.identity.outputs")
    for name, path in outputs.items():
        if name != "terminal_receipt" and stored_outputs.get(name) != str(path):
            _fail(f"receipt identity output.{name} drifted")
    for name, path in outputs.items():
        if os.path.lexists(path):
            _fail(f"fresh output {name} already exists")
    runner_source = _runner_source_descriptor(root)
    binding = {
        "schema": SCHEMA, "receipt_sha256": receipt["receipt_sha256"], "identity_sha256": receipt["identity_sha256"],
        "runner_source": runner_source, "cwd": cwd_descriptor, "executable": executable_descriptor,
        "inputs": input_descriptors, "outputs": {key: str(value) for key, value in outputs.items()},
        "argv": list(command), "env": env,
    }
    return DiagnosticPlan(
        receipt_path=candidate,
        receipt=receipt,
        identity=core,
        namespace=namespace,
        command=command,
        env=env,
        outputs=outputs,
        input_descriptors=input_descriptors,
        executable_descriptor=executable_descriptor,
        cwd_descriptor=cwd_descriptor,
        runner_source_descriptor=runner_source,
        binding_sha256=_binding_digest(binding),
    )


@dataclass(frozen=True)
class _OutputReservations:
    plan: DiagnosticPlan
    descriptors: Mapping[str, Mapping[str, Any]]

    @property
    def outputs(self) -> Mapping[str, Path]:
        return {name: Path(self.descriptors[name]["path"]) for name in EVALUATOR_OUTPUT_NAMES}


def _reserve_evaluator_outputs(plan: DiagnosticPlan) -> _OutputReservations:
    """Reserve evaluator paths without granting a pathname-only child access."""

    descriptors: dict[str, Mapping[str, Any]] = {}
    created: list[Path] = []
    try:
        for name in EVALUATOR_OUTPUT_NAMES:
            path = plan.outputs[name]
            _reject_symlinks(path.parent, f"output.{name} parent")
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(path, flags, 0o600)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            created.append(path)
            descriptor, _raw = _stable_artifact(path, path.parent, f"output.{name}", max_bytes=MAX_HDF5_BYTES)
            descriptors[name] = descriptor
        return _OutputReservations(plan=plan, descriptors=descriptors)
    except BaseException:
        for path in created:
            try:
                path.unlink()
            except OSError:
                pass
        raise


def _validate_output_reservations(reservations: _OutputReservations) -> None:
    for name in EVALUATOR_OUTPUT_NAMES:
        expected = reservations.descriptors[name]
        observed, _raw = _stable_artifact(
            Path(expected["path"]),
            Path(expected["path"]).parent,
            f"reserved output.{name}",
            max_bytes=MAX_HDF5_BYTES,
        )
        _descriptor_matches(observed, expected, f"reserved output.{name}")


def _release_output_reservations(reservations: _OutputReservations, *, remove_unpublished: bool) -> None:
    if not remove_unpublished:
        return
    for name in EVALUATOR_OUTPUT_NAMES:
        expected = reservations.descriptors[name]
        path = Path(expected["path"])
        try:
            info = os.lstat(path)
            if int(info.st_dev) == int(expected["dev"]) and int(info.st_ino) == int(expected["ino"]):
                path.unlink()
        except FileNotFoundError:
            continue
        except OSError as error:
            _fail(f"cannot release reserved output.{name}: {error}")


def _require_descriptor_bound_outputs(plan: DiagnosticPlan, reservations: _OutputReservations) -> None:
    del plan, reservations
    _fail("evaluator output publication is pathname-only; descriptor-bound child attestation is absent")


def _parse_nvidia_smi_gpu_rows(stdout: str) -> dict[int, dict[str, Any]]:
    rows: dict[int, dict[str, Any]] = {}
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        fields = [item.strip() for item in line.split(",")]
        if len(fields) != 6:
            _fail("nvidia-smi GPU row has an unexpected shape")
        try:
            index = int(fields[0])
            total_mib, used_mib, free_mib = (int(item) for item in fields[3:6])
        except ValueError as error:
            _fail(f"nvidia-smi GPU row is not numeric: {error}")
        if index in rows or index < 0 or not GPU_UUID_RE.fullmatch(fields[1]) or not PCI_BUS_RE.fullmatch(fields[2]):
            _fail("nvidia-smi GPU row has an invalid or duplicate identity")
        rows[index] = {
            "physical_index": index,
            "uuid": fields[1],
            "pci_bus_id": fields[2],
            "total_mib": total_mib,
            "used_mib": used_mib,
            "free_mib": free_mib,
        }
    if not rows:
        _fail("nvidia-smi returned no GPU rows")
    return rows


def _parse_nvidia_smi_process_rows(stdout: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        fields = [item.strip() for item in line.split(",")]
        if len(fields) != 2 or not fields[0].isdigit() or not GPU_UUID_RE.fullmatch(fields[1]):
            _fail("nvidia-smi process row has an invalid shape")
        result.append({"pid": int(fields[0]), "gpu_uuid": fields[1]})
    return result


def _validate_child_gpu_attestation(
    value: Mapping[str, Any] | DiagnosticPlan,
    *args: Any,
    expected_gpu: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if isinstance(value, DiagnosticPlan):
        if len(args) != 2:
            _fail("child GPU attestation requires payload and child PID")
        payload_value = _mapping(args[0], "child_gpu_attestation")
        pid = args[1]
        if type(pid) is not int or pid <= 0:
            _fail("child GPU attestation PID is invalid")
        expected_gpu = value.gpu_identity
        value = payload_value.get("gpu", payload_value)
    if expected_gpu is None:
        _fail("expected GPU identity is required")
    payload = dict(_mapping(value, "child_gpu_attestation"))
    _unknown(payload, {"producer", "synthetic", "sealed", "gpu_index", "gpu_uuid", "pci_bus_id", "pids"}, "child_gpu_attestation")
    _exact(payload, "producer", "audited_runtime_gpu_attestation", "child_gpu_attestation")
    _exact(payload, "synthetic", False, "child_gpu_attestation")
    _exact(payload, "sealed", True, "child_gpu_attestation")
    _exact(payload, "gpu_index", GPU_INDEX, "child_gpu_attestation")
    _exact(payload, "gpu_uuid", expected_gpu["uuid"], "child_gpu_attestation")
    _exact(payload, "pci_bus_id", expected_gpu["pci_bus_id"], "child_gpu_attestation")
    pids = payload.get("pids")
    if not isinstance(pids, list) or not pids or any(type(item) is not int or item <= 0 for item in pids):
        _fail("child_gpu_attestation.pids must be a non-empty positive integer list")
    return payload


def _run_real_popen_wait(plan: DiagnosticPlan, capability: object) -> Mapping[str, Any]:
    del plan, capability
    if _SEALED_EXECUTION_CAPABILITY is None:
        _fail("sealed real Popen/wait capability is not admitted; Popen was not attempted")
    _fail("unreachable execution capability state")


def execute_diagnostic(plan: DiagnosticPlan, capability: object) -> Mapping[str, Any]:
    """Reject execution before receipt consumption, Popen, or GPU startup."""

    del plan
    if _SEALED_EXECUTION_CAPABILITY is None:
        _fail("diagnostic execute capability is not admitted; no receipt was consumed")
    if capability is not _SEALED_EXECUTION_CAPABILITY:
        _fail("caller-supplied object cannot authorize sealed execution")
    _fail("unreachable execution capability state")


def _artifact_descriptor(value: Any, name: str, expected_path: Path) -> Mapping[str, Any]:
    artifact = dict(_mapping(value, name))
    _unknown(
        artifact,
        {
            "path", "resolved_path", "dev", "ino", "bytes", "mode", "uid", "gid",
            "nlink", "mtime_ns", "ctime_ns", "parent_dev", "parent_ino", "sha256",
            "leaf_symlink", "stable_fd", "fd_identity_stable", "path_reopened",
            "content_opened",
        },
        name,
    )
    _exact(artifact, "path", str(expected_path), name)
    _absolute(artifact.get("resolved_path"), f"{name}.resolved_path")
    for key in ("dev", "ino", "bytes", "mode", "uid", "gid", "nlink", "mtime_ns", "ctime_ns", "parent_dev", "parent_ino"):
        if type(artifact.get(key)) is not int or artifact[key] < 0:
            _fail(f"{name}.{key} must be a non-negative integer")
    admission._sha(artifact.get("sha256"), f"{name}.sha256")
    admission._exact(artifact, "leaf_symlink", False, name)
    admission._int(artifact.get("bytes"), f"{name}.bytes", 1)
    _exact(artifact, "stable_fd", True, name)
    _exact(artifact, "fd_identity_stable", True, name)
    _exact(artifact, "path_reopened", False, name)
    return artifact


def validate_terminal_receipt(plan: DiagnosticPlan, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a future real terminal envelope; never create one."""

    value = dict(_mapping(payload, "terminal_receipt"))
    _unknown(value, {"schema", "status", "synthetic", "receipt_sha256", "identity_sha256", "binding_sha256", "seed", "model_kind", "hidden", "updates", "case_id", "split", "transitions", "frames", "process", "hdf5_validator", "artifacts", *ZERO_CREDIT}, "terminal_receipt")
    _exact(value, "schema", TERMINAL_RECEIPT_SCHEMA, "terminal_receipt")
    _exact(value, "status", "terminal_verified_diagnostic_only", "terminal_receipt")
    _exact(value, "synthetic", False, "terminal_receipt")
    _exact(value, "receipt_sha256", plan.receipt["receipt_sha256"], "terminal_receipt")
    _exact(value, "identity_sha256", plan.receipt["identity_sha256"], "terminal_receipt")
    _exact(value, "binding_sha256", plan.binding_sha256, "terminal_receipt")
    for key, expected in {"seed": SEED, "model_kind": MODEL, "hidden": HIDDEN, "updates": UPDATES, "case_id": CASE_ID, "split": SPLIT, "transitions": TRANSITIONS, "frames": FRAMES}.items():
        _exact(value, key, expected, "terminal_receipt")
    for key, expected in ZERO_CREDIT.items():
        _exact(value, key, expected, "terminal_receipt")
    process = dict(_mapping(value.get("process"), "terminal_receipt.process"))
    _unknown(process, {"producer", "sealed", "synthetic", "popen_called", "wait_observed", "wait_returncode", "natural_exit", "argv", "cwd", "env", "command_sha256", "stable_fd", "pid", "pid_starttime"}, "terminal_receipt.process")
    _exact(process, "producer", "audited_runtime_sealed_witness", "terminal_receipt.process")
    for key, expected in {"sealed": True, "synthetic": False, "popen_called": True, "wait_observed": True, "wait_returncode": 0, "natural_exit": True, "stable_fd": True}.items():
        _exact(process, key, expected, "terminal_receipt.process")
    _exact(process, "argv", list(plan.command), "terminal_receipt.process")
    _exact(process, "cwd", str(plan.root), "terminal_receipt.process")
    _exact(process, "env", dict(plan.env), "terminal_receipt.process")
    _exact(process, "command_sha256", plan.identity["command"]["sha256"], "terminal_receipt.process")
    admission._string(process.get("pid_starttime"), "terminal_receipt.process.pid_starttime")
    hdf5 = dict(_mapping(value.get("hdf5_validator"), "terminal_receipt.hdf5_validator"))
    _unknown(hdf5, {"producer", "independent", "synthetic", "passed", "complete", "hdf5_content_opened", "stable_fd", "path_reopened", "expected_transitions", "frames_executed", "trajectory_transitions", "trajectory_frames", "trajectory_artifact_sha256", "validator_returncode"}, "terminal_receipt.hdf5_validator")
    for key, expected in {"producer": "independent_hdf5_validator", "independent": True, "synthetic": False, "passed": True, "complete": True, "hdf5_content_opened": True, "stable_fd": True, "path_reopened": False, "expected_transitions": TRANSITIONS, "frames_executed": FRAMES, "trajectory_transitions": TRANSITIONS, "trajectory_frames": FRAMES, "validator_returncode": 0}.items():
        _exact(hdf5, key, expected, "terminal_receipt.hdf5_validator")
    artifacts = _mapping(value.get("artifacts"), "terminal_receipt.artifacts")
    _unknown(artifacts, {"evaluation", "trajectory", "progress", "validator"}, "terminal_receipt.artifacts")
    checked: dict[str, Any] = {}
    for name, hdf5_flag in (("evaluation", False), ("trajectory", True), ("progress", False), ("validator", False)):
        descriptor = _artifact_descriptor(artifacts.get(name), f"terminal_receipt.artifacts.{name}", plan.outputs[name])
        actual, raw = _stable_artifact(
            Path(descriptor["path"]),
            Path(descriptor["path"]).parent,
            f"terminal.{name}",
            max_bytes=MAX_HDF5_BYTES if hdf5_flag else MAX_JSON_BYTES,
        )
        _descriptor_matches(actual, descriptor, f"terminal.{name}")
        if hdf5_flag:
            _inspect_hdf5_snapshot(raw, required_datasets=())
        checked[name] = actual
    _exact(hdf5, "trajectory_artifact_sha256", checked["trajectory"]["sha256"], "terminal_receipt.hdf5_validator")
    return {"schema": TERMINAL_RECEIPT_SCHEMA, "status": "terminal_verified_diagnostic_only", "real_popen_wait_proof": True, "stable_fd_artifacts_verified": True, "independent_hdf5_validator": True, "trusted_for_formal_credit": False, "artifacts": checked, **ZERO_CREDIT}


def _report_base(*, execute_requested: bool, receipt_path: Path | None, status: str, blocked: Sequence[str], plan: DiagnosticPlan | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema": REPORT_SCHEMA, "report_id": REPORT_ID, "status": status,
        "mode": "diagnostic_execute" if execute_requested else "dry_run",
        "dry_run": not execute_requested, "execute_requested": bool(execute_requested),
        "source_bound": plan is not None, "admission_receipt_valid": plan is not None,
        "diagnostic_execute_allowed": False, "launch_allowed": False,
        "popen_attempted": False, "wait_attempted": False, "real_workload_started": 0,
        "terminal_receipt_minted": False, "terminal_receipt": None,
        "receipt_path": None if plan is None else str(plan.receipt_path),
        "blocked_reasons": list(dict.fromkeys(str(item) for item in blocked if item)),
        "side_effects": {"processes_started": 0, "processes_stopped": 0, "processes_restarted": 0, "popen_called": False, "wait_observed": False, "validator_started": False, "registry_writes": 0, "ledger_writes": 0, "denominator_writes": 0, "gate_writes": 0, "completion_writes": 0, "plan_writes": 0},
        **ZERO_CREDIT,
    }
    if plan is not None:
        result.update({
            "seed": SEED, "model_kind": MODEL, "hidden": HIDDEN, "updates": UPDATES,
            "case_id": CASE_ID, "split": SPLIT, "transitions": TRANSITIONS, "frames": FRAMES,
            "receipt_sha256": plan.receipt["receipt_sha256"], "identity_sha256": plan.receipt["identity_sha256"],
            "namespace": str(plan.namespace), "namespace_nonce": plan.identity["nonce"],
            "command": list(plan.command), "command_sha256": plan.identity["command"]["sha256"],
            "env_overrides": dict(plan.env), "binding_sha256": plan.binding_sha256,
            "input_descriptors": {key: dict(value) for key, value in plan.input_descriptors.items()},
            "executable_descriptor": dict(plan.executable_descriptor), "cwd_descriptor": dict(plan.cwd_descriptor),
            "runner_source_descriptor": dict(plan.runner_source_descriptor),
            "outputs": {key: str(value) for key, value in plan.outputs.items()},
        })
    return result


def build_report(receipt_path: Path | str | None, *, execute_requested: bool = False) -> dict[str, Any]:
    if receipt_path is None:
        return _report_base(execute_requested=execute_requested, receipt_path=None, status="blocked_fail_closed", blocked=("--admission-receipt is required; no implicit admission is minted", *EXECUTION_BLOCKERS))
    try:
        plan = build_plan(receipt_path)
        return _report_base(execute_requested=execute_requested, receipt_path=plan.receipt_path, status="blocked_fail_closed", blocked=EXECUTION_BLOCKERS, plan=plan)
    except (RunnerError, admission.AdmissionError, OSError, ValueError) as error:
        return _report_base(execute_requested=execute_requested, receipt_path=_absolute(receipt_path, "admission receipt"), status="blocked_fail_closed", blocked=(str(error),))


def validate_report(report: Mapping[str, Any]) -> list[str]:
    try:
        admission._walk_json(report, "report")
        allowed = set(ZERO_CREDIT) | {"schema", "report_id", "status", "mode", "dry_run", "execute_requested", "source_bound", "admission_receipt_valid", "diagnostic_execute_allowed", "launch_allowed", "popen_attempted", "wait_attempted", "real_workload_started", "terminal_receipt_minted", "terminal_receipt", "receipt_path", "blocked_reasons", "side_effects", "seed", "model_kind", "hidden", "updates", "case_id", "split", "transitions", "frames", "receipt_sha256", "identity_sha256", "namespace", "namespace_nonce", "command", "command_sha256", "env_overrides", "binding_sha256", "input_descriptors", "executable_descriptor", "cwd_descriptor", "runner_source_descriptor", "outputs"}
        _unknown(report, allowed, "report")
        _exact(report, "schema", REPORT_SCHEMA, "report")
        _exact(report, "report_id", REPORT_ID, "report")
        _exact(report, "status", "blocked_fail_closed", "report")
        _exact(report, "diagnostic_execute_allowed", False, "report")
        _exact(report, "launch_allowed", False, "report")
        _exact(report, "popen_attempted", False, "report")
        _exact(report, "wait_attempted", False, "report")
        _exact(report, "real_workload_started", 0, "report")
        _exact(report, "terminal_receipt_minted", False, "report")
        _exact(report, "terminal_receipt", None, "report")
        for key, expected in ZERO_CREDIT.items():
            _exact(report, key, expected, "report")
        reasons = report.get("blocked_reasons")
        if not isinstance(reasons, list) or not reasons or any(not isinstance(item, str) for item in reasons):
            _fail("report.blocked_reasons must be a non-empty string list")
        effects = _mapping(report.get("side_effects"), "report.side_effects")
        for key in ("processes_started", "processes_stopped", "processes_restarted", "registry_writes", "ledger_writes", "denominator_writes", "gate_writes", "completion_writes", "plan_writes"):
            if effects.get(key) not in (0, False):
                _fail(f"report.side_effects.{key} must be zero")
        if report.get("source_bound") is True:
            for key in ("receipt_sha256", "identity_sha256", "binding_sha256"):
                admission._sha(report.get(key), f"report.{key}")
        return []
    except (RunnerError, admission.AdmissionError, TypeError, KeyError) as error:
        return [str(error)]


def render_markdown(report: Mapping[str, Any]) -> str:
    return "\n".join([
        "# F3 graph_residual hidden16 seed29 diagnostic runner v2",
        "",
        f"- status: `{report.get('status')}`",
        f"- mode: `{report.get('mode')}`",
        f"- source bound: `{report.get('source_bound')}`",
        f"- admission receipt: `{report.get('receipt_path')}`",
        "- exact contract: graph_residual / hidden16 / seed29 / test / 835 transitions / 836 frames",
        "- default: dry-run; explicit diagnostic execute remains fail-closed",
        f"- Popen/wait attempted: `{report.get('popen_attempted')}/{report.get('wait_attempted')}`",
        "- terminal receipt: producer is absent; declarations cannot be promoted",
        "- formal/registry/ledger/denominator/gate/completion/PLAN writes: `0`; credit: `0`",
        "",
        "## Blockers",
        "",
        *[f"- {item}" for item in report.get("blocked_reasons", []) if isinstance(item, str)],
        "",
    ])


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admission-receipt", type=Path, default=None)
    parser.add_argument("--report-output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--verify-report", type=Path, default=None)
    parser.add_argument("--diagnostic-execute", action="store_true")
    return parser.parse_args(argv)


def _read_report(path: Path) -> dict[str, Any]:
    _raw, _descriptor, payload = admission._read_bound(path, "report", max_bytes=MAX_JSON_BYTES, parse_json=True)
    assert payload is not None
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.verify_report is not None:
            report = _read_report(_absolute(args.verify_report, "report"))
            errors = validate_report(report)
            print(canonical_json({"schema": REPORT_SCHEMA, "valid": not errors, "errors": errors}))
            return 0 if not errors else 1
        report = build_report(args.admission_receipt, execute_requested=args.diagnostic_execute)
        admission._write_exclusive(args.report_output, (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"), mode=0o640)
        admission._write_exclusive(args.report_output.with_suffix(".zh-CN.md"), render_markdown(report).encode("utf-8"), mode=0o640)
        print(canonical_json(report))
        return 2
    except (RunnerError, admission.AdmissionError, OSError, ValueError) as error:
        print(canonical_json({"status": "blocked_fail_closed", "error": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
