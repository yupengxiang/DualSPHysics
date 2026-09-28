#!/usr/bin/env python3
"""Independent read-only hardening boundary for the F3 terminal validators.

The current raw/residual validator, bridge, readiness, and production-
capability files remain intentionally untouched.  This module records the
security audit and provides an additive boundary for a future integration:

* artifact bytes are read through a directory-fd walk with ``O_NOFOLLOW``;
  lexical containment, parent symlinks, leaf symlinks, and multi-link files
  are rejected before bytes are returned;
* HDF5 is opened from the already-bound in-memory byte snapshot, never from
  the path a second time.  Every link is required to be a hard link and
  virtual datasets are rejected, preventing external/soft-link escape;
* a process receipt must bind the complete expected command, cwd, environment,
  manifest, training receipt, checkpoint, namespace, and nonce.  A self-
  declared JSON proof is still only a declaration: this module never promotes
  it to a real Popen/wait witness;
* execute requests are rejected by this audit boundary.  No subprocess,
  evaluator, solver, worker, GPU, queue, or production artifact is started or
  opened here.

The hardening functions are deliberately additive and are not imported by the
existing contracts.  Their purpose is to make the P1/P2 findings concrete and
to provide a safe seam for a separately reviewed future integration.
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
import stat
from typing import Any

import h5py


SCHEMA = "core.f3.graph.terminal.validator.security_hardening.v1"
REPORT_SCHEMA = f"{SCHEMA}.report"
PROCESS_PROOF_SCHEMA = f"{SCHEMA}.declared_process_proof"
REPORT_ID = "f3-graph-terminal-validator-security-hardening-v1"

MAX_ARTIFACT_BYTES = 32 * 1024 * 1024
MAX_HDF5_LINKS = 8192
SHA256_HEX_LENGTH = 64

ZERO_CREDIT: dict[str, Any] = {
    "diagnostic_only": True,
    "formal": False,
    "formal_eligible": False,
    "T1_numerical": False,
    "T2_macro": False,
    "T2_path": False,
    "qualification": False,
    "qualification_credit": 0,
    "credit": 0,
}


class SecurityBoundaryError(ValueError):
    """An unsafe, drifting, or authorizing input was rejected."""


def _fail(message: str) -> None:
    raise SecurityBoundaryError(f"fail-closed: {message}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _absolute_normalized(value: Path | str, name: str) -> Path:
    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        _fail(f"{name} must be a non-empty path")
    path = Path(raw)
    if not path.is_absolute():
        _fail(f"{name} must be absolute")
    if any(part in {".", ".."} for part in path.parts):
        _fail(f"{name} contains a lexical path alias")
    if Path(os.path.normpath(raw)) != path:
        _fail(f"{name} is not normalized")
    return path


def _under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _identity(info: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(info.st_mode),
        int(info.st_nlink),
        int(info.st_size),
        int(info.st_mtime_ns),
    )


def _directory_flags() -> int:
    required = getattr(os, "O_DIRECTORY", 0)
    if required == 0:
        _fail("platform does not expose O_DIRECTORY")
    return os.O_RDONLY | required | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)


def _read_flags() -> int:
    return os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)


def _open_directory_chain(path: Path, name: str) -> int:
    """Open every absolute directory component with O_NOFOLLOW.

    Holding the directory descriptors makes a parent-directory rename or
    replacement unable to redirect the later leaf open outside the checked
    directory chain.
    """

    flags = _directory_flags()
    try:
        current = os.open(os.sep, flags)
    except OSError as error:
        _fail(f"cannot open root for {name}: {error}")
    try:
        for component in path.parts[1:]:
            try:
                next_fd = os.open(component, flags, dir_fd=current)
            except OSError as error:
                _fail(f"cannot open {name} directory component {component!r}: {error}")
            os.close(current)
            current = next_fd
        return current
    except BaseException:
        try:
            os.close(current)
        except OSError:
            pass
        raise


def secure_read_regular_file(
    path_value: Path | str,
    *,
    root_value: Path | str,
    max_bytes: int = MAX_ARTIFACT_BYTES,
    expected_bytes: int | None = None,
    expected_sha256: str | None = None,
) -> bytes:
    """Read one bounded, single-link regular file from a checked root.

    The data is read only from the opened descriptor.  A later pathname
    replacement cannot make the reader follow a new symlink or parent tree.
    The final lstat is an additional fail-closed path-consistency check, not
    the source of the bytes.
    """

    root = _absolute_normalized(root_value, "root")
    path = _absolute_normalized(path_value, "artifact")
    if root == path or not _under(path, root):
        _fail("artifact must remain strictly inside root")
    if type(max_bytes) is not int or max_bytes < 1:
        _fail("max_bytes must be a positive integer")
    if expected_bytes is not None and (type(expected_bytes) is not int or expected_bytes < 1):
        _fail("expected_bytes must be a positive integer")
    if expected_sha256 is not None:
        if (
            not isinstance(expected_sha256, str)
            or len(expected_sha256) != SHA256_HEX_LENGTH
            or any(char not in "0123456789abcdef" for char in expected_sha256)
        ):
            _fail("expected_sha256 must be lowercase SHA-256")

    relative = path.relative_to(root)
    if not relative.parts:
        _fail("artifact leaf is missing")

    directory_fds: list[int] = []
    root_fd = _open_directory_chain(root, "root")
    directory_fds.append(root_fd)
    parent_fd = root_fd
    leaf_fd: int | None = None
    before: os.stat_result | None = None
    chunks: list[bytes] = []
    try:
        for component in relative.parts[:-1]:
            try:
                next_fd = os.open(component, _directory_flags(), dir_fd=parent_fd)
            except OSError as error:
                _fail(f"artifact parent component {component!r} is unsafe: {error}")
            directory_fds.append(next_fd)
            parent_fd = next_fd
        try:
            leaf_fd = os.open(relative.parts[-1], _read_flags(), dir_fd=parent_fd)
        except OSError as error:
            _fail(f"cannot open artifact without following links: {error}")

        before = os.fstat(leaf_fd)
        if not stat.S_ISREG(before.st_mode):
            _fail("artifact must be a regular file")
        if before.st_nlink != 1:
            _fail("artifact must have exactly one hard link")
        if before.st_size < 1 or before.st_size > max_bytes:
            _fail(f"artifact exceeds bounded size {max_bytes}")
        if expected_bytes is not None and int(before.st_size) != expected_bytes:
            _fail("artifact bytes disagree with expected identity")
        expected_identity = _identity(before)

        total = 0
        while True:
            block = os.read(leaf_fd, min(1024 * 1024, max_bytes + 1 - total))
            if not block:
                break
            chunks.append(block)
            total += len(block)
            if total > max_bytes:
                _fail(f"artifact exceeds bounded read size {max_bytes}")
        after_fd = os.fstat(leaf_fd)
        if _identity(after_fd) != expected_identity or total != before.st_size:
            _fail("artifact changed during descriptor read")
    except OSError as error:
        _fail(f"cannot read artifact: {error}")
    finally:
        if leaf_fd is not None:
            try:
                os.close(leaf_fd)
            except OSError:
                pass
        for descriptor in reversed(directory_fds):
            try:
                os.close(descriptor)
            except OSError:
                pass

    # The pathname is checked only after the safe descriptor read.  A changed
    # path causes rejection; it can never change which bytes were read.
    try:
        path_info = os.lstat(path)
    except OSError as error:
        _fail(f"artifact path changed after descriptor read: {error}")
    if (
        before is None
        or not stat.S_ISREG(path_info.st_mode)
        or path_info.st_nlink != 1
        or _identity(path_info) != _identity(before)
    ):
        _fail("artifact path identity changed after descriptor read")

    raw = b"".join(chunks)
    if expected_sha256 is not None and hashlib.sha256(raw).hexdigest() != expected_sha256:
        _fail("artifact SHA-256 disagrees with expected identity")
    return raw


def _reject_unsafe_hdf5_links(handle: h5py.File, *, max_links: int) -> int:
    """Reject external/soft links and virtual datasets before dereference."""

    pending: list[h5py.Group] = [handle]
    visited_links = 0
    while pending:
        group = pending.pop()
        for name in group.keys():
            visited_links += 1
            if visited_links > max_links:
                _fail("HDF5 link count exceeds the bounded limit")
            link = group.get(name, getlink=True)
            if not isinstance(link, h5py.HardLink):
                _fail(f"HDF5 contains a non-hard link at {name!r}")
            obj = group.get(name)
            if isinstance(obj, h5py.Group):
                pending.append(obj)
            elif isinstance(obj, h5py.Dataset):
                if bool(getattr(obj, "is_virtual", False)):
                    _fail(f"HDF5 contains a virtual dataset at {name!r}")
            else:
                _fail(f"HDF5 contains an unsupported object at {name!r}")
    return visited_links


def inspect_hdf5_snapshot(
    raw: bytes,
    *,
    required_datasets: Sequence[str] = (),
    max_bytes: int = MAX_ARTIFACT_BYTES,
) -> dict[str, Any]:
    """Inspect HDF5 only from a previously bound byte snapshot."""

    if not isinstance(raw, bytes):
        _fail("HDF5 snapshot must be bytes")
    if not 1 <= len(raw) <= max_bytes:
        _fail("HDF5 snapshot is outside the bounded size")
    names = tuple(required_datasets)
    if any(not isinstance(name, str) or not name or "\x00" in name for name in names):
        _fail("required HDF5 dataset names must be non-empty strings")
    try:
        with h5py.File(io.BytesIO(raw), "r") as handle:
            link_count = _reject_unsafe_hdf5_links(handle, max_links=MAX_HDF5_LINKS)
            for name in names:
                if name not in handle:
                    _fail(f"required HDF5 dataset is missing: {name}")
                link = handle.get(name, getlink=True)
                if not isinstance(link, h5py.HardLink):
                    _fail(f"required HDF5 dataset is not a hard link: {name}")
                dataset = handle[name]
                if not isinstance(dataset, h5py.Dataset) or bool(getattr(dataset, "is_virtual", False)):
                    _fail(f"required HDF5 object is not a physical dataset: {name}")
                # Reading only bounded metadata here avoids turning this seam
                # into a trajectory evaluator.  Future code can read the same
                # in-memory handle under its own shape/finite-value contract.
            return {
                "status": "bounded_hdf5_snapshot_links_validated",
                "passed": True,
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "hard_link_count": link_count,
                "required_datasets": list(names),
                "external_links_rejected": True,
                "soft_links_rejected": True,
                "virtual_datasets_rejected": True,
            }
    except (OSError, ValueError) as error:
        _fail(f"cannot inspect bounded HDF5 snapshot: {error}")


@dataclass(frozen=True)
class ExpectedExecutionIdentity:
    """The complete identity a future process proof must declare."""

    model_kind: str
    seed: int
    nonce: str
    namespace: str
    manifest_sha256: str
    training_receipt_sha256: str
    checkpoint_path: str
    checkpoint_sha256: str
    command: tuple[str, ...]
    cwd: str
    env_overrides: tuple[tuple[str, str], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_kind": self.model_kind,
            "seed": self.seed,
            "nonce": self.nonce,
            "namespace": self.namespace,
            "manifest_sha256": self.manifest_sha256,
            "training_receipt_sha256": self.training_receipt_sha256,
            "checkpoint_path": self.checkpoint_path,
            "checkpoint_sha256": self.checkpoint_sha256,
            "command": list(self.command),
            "cwd": self.cwd,
            "env_overrides": dict(self.env_overrides),
        }

    @property
    def command_sha256(self) -> str:
        return canonical_digest(
            {
                "argv": list(self.command),
                "cwd": self.cwd,
                "env_overrides": dict(self.env_overrides),
            }
        )

    @property
    def identity_sha256(self) -> str:
        return canonical_digest(self.as_dict())


def validate_declared_process_proof(
    value: Mapping[str, Any],
    expected: ExpectedExecutionIdentity,
) -> dict[str, Any]:
    """Check complete declaration binding without treating it as real proof."""

    if not isinstance(value, Mapping):
        _fail("declared process proof must be an object")
    allowed = {
        "schema",
        "status",
        "synthetic_only",
        "real_popen_wait",
        "real_popen_type",
        "wait_observed",
        "evaluator_returncode",
        "wait_returncode",
        "evaluator_pid",
        "model_kind",
        "seed",
        "nonce",
        "namespace",
        "manifest_sha256",
        "training_receipt_sha256",
        "checkpoint_path",
        "checkpoint_sha256",
        "command",
        "command_sha256",
        "cwd",
        "env_overrides",
        "identity_sha256",
        "proof_sha256",
    }
    unknown = sorted(set(value) - allowed)
    if unknown:
        _fail(f"declared process proof contains unknown fields: {unknown}")
    exact = {
        "schema": PROCESS_PROOF_SCHEMA,
        "status": "natural_exit_verified",
        "synthetic_only": False,
        "real_popen_wait": True,
        "real_popen_type": "subprocess.Popen",
        "wait_observed": True,
        "evaluator_returncode": 0,
        "wait_returncode": 0,
        "model_kind": expected.model_kind,
        "seed": expected.seed,
        "nonce": expected.nonce,
        "namespace": expected.namespace,
        "manifest_sha256": expected.manifest_sha256,
        "training_receipt_sha256": expected.training_receipt_sha256,
        "checkpoint_path": expected.checkpoint_path,
        "checkpoint_sha256": expected.checkpoint_sha256,
        "command": list(expected.command),
        "command_sha256": expected.command_sha256,
        "cwd": expected.cwd,
        "env_overrides": dict(expected.env_overrides),
        "identity_sha256": expected.identity_sha256,
    }
    for key, required in exact.items():
        if key not in value or value[key] != required or type(value[key]) is not type(required):
            _fail(f"declared process proof.{key} is not exactly bound to the expected identity")
    if type(value.get("evaluator_pid")) is not int or value["evaluator_pid"] < 1:
        _fail("declared process proof.evaluator_pid must be a positive integer")
    proof_sha = value.get("proof_sha256")
    if (
        not isinstance(proof_sha, str)
        or len(proof_sha) != SHA256_HEX_LENGTH
        or any(char not in "0123456789abcdef" for char in proof_sha)
    ):
        _fail("declared process proof.proof_sha256 must be lowercase SHA-256")
    unsigned = dict(value)
    unsigned.pop("proof_sha256")
    if proof_sha != canonical_digest(unsigned):
        _fail("declared process proof digest does not bind its complete declaration")
    return {
        **dict(value),
        "declaration_consistent": True,
        "real_popen_wait_verified": False,
        "promotion_allowed": False,
        **ZERO_CREDIT,
    }


def reject_execute_request(*, execute_requested: bool, capability_admitted: bool = False) -> dict[str, Any]:
    """Return dry-run state or reject execution; never starts a process."""

    if execute_requested:
        _fail(
            "execution is outside the independent read-only hardening boundary; "
            "no default or explicit execute path is admitted"
        )
    if capability_admitted:
        _fail("a caller cannot self-install production execution capability")
    return {
        "status": "dry_run",
        "execute_requested": False,
        "popen_attempted": False,
        "wait_attempted": False,
        "launch_allowed": False,
        **ZERO_CREDIT,
    }


AUDIT_FINDINGS: tuple[dict[str, Any], ...] = (
    {
        "id": "F3-SA-001",
        "severity": "P1",
        "title": "process proof and command/source identity are self-declared",
        "affected": [
            "scripts/f3_graph_terminal_production_validator_capability_v1.py:471-504",
            "scripts/f3_graph_residual_hidden16_current_manifest_terminal_artifact_identity_v1.py:951-968",
            "scripts/f3_graph_raw_hidden16_current_manifest_terminal_execution_bridge_v1.py:599-652",
        ],
        "evidence": "A receipt can self-hash arbitrary command/booleans/PID; the production capability receipt has no manifest or checkpoint binding and no sealed process witness. The current capability is uninstalled, so no credit is currently promoted.",
        "risk": "A future capability enablement could accept a successful-looking receipt for a different evaluator or source checkpoint.",
        "status": "blocked_by_uninstalled_capability",
        "hardening": "Require the complete expected argv/cwd/environment plus manifest/training/checkpoint identity, and keep declarations non-authorizing without an in-memory real-Popen witness.",
    },
    {
        "id": "F3-SA-002",
        "severity": "P1",
        "title": "path TOCTOU before HDF5/artifact re-open",
        "affected": [
            "scripts/f3_graph_raw_hidden16_current_manifest_terminal_artifact_validator_v1.py:669-675",
            "scripts/f3_graph_raw_hidden16_current_manifest_terminal_execution_bridge_v1.py:278-315",
            "scripts/f3_graph_terminal_production_validator_capability_v1.py:715-738",
            "scripts/f3_full_rollout_receipt_hdf5_validator_v1.py:329-330",
        ],
        "evidence": "The code hashes or bounds a path and later opens that pathname again; a final stat/second digest cannot prevent a swap during the intervening HDF5/JSON read.",
        "risk": "A symlink or parent-directory race can make the validator read a different or out-of-bound artifact while retaining a passing pre/post pathname check.",
        "status": "blocked_by_synthetic_or_uninstalled_boundary",
        "hardening": "Walk directory descriptors with O_NOFOLLOW, read the bytes once, and open HDF5 only from that bound byte snapshot.",
    },
    {
        "id": "F3-SA-003",
        "severity": "P1",
        "title": "residual terminal token and injectable Popen are not a sealed capability",
        "affected": [
            "scripts/f3_graph_residual_hidden16_current_manifest_terminal_artifact_identity_v1.py:772-869",
        ],
        "evidence": "The module-level _TERMINAL_CAPABILITY_TOKEN is import-accessible, execute_plan accepts it, and _run_popen_wait accepts an injected popen_factory while checking only isinstance(process, subprocess.Popen).",
        "risk": "A same-process caller can bypass the stated unadmitted boundary or supply a subclass/fake process path if the token is used.",
        "status": "blocked_in_default_cli_but_latent_programmatic_bypass",
        "hardening": "Do not expose an executable token in a diagnostic module; reject execute requests at this boundary and require an independently sealed runtime witness before any future integration.",
    },
    {
        "id": "F3-SA-004",
        "severity": "P1",
        "title": "HDF5 external/soft links and virtual datasets are not rejected",
        "affected": [
            "scripts/f3_graph_raw_hidden16_current_manifest_terminal_artifact_validator_v1.py:674-755",
            "scripts/f3_graph_terminal_production_validator_capability_v1.py:677-703",
            "scripts/f3_full_rollout_receipt_hdf5_validator_v1.py:329-406",
        ],
        "evidence": "Required datasets are obtained with handle[name] without checking getlink(..., getlink=True) or Dataset.is_virtual.",
        "risk": "A crafted HDF5 can dereference an external/soft/VDS source outside the checked artifact path.",
        "status": "blocked_by_marked_fixture_or_uninstalled_capability",
        "hardening": "Reject every non-HardLink and every virtual dataset before dereference; inspect only the immutable in-memory snapshot.",
    },
    {
        "id": "F3-SA-005",
        "severity": "P2",
        "title": "unknown-field handling is inconsistent at the production payload boundary",
        "affected": [
            "scripts/f3_graph_terminal_production_validator_capability_v1.py:571-644",
        ],
        "evidence": "Evaluation and validator payloads validate selected fields but do not reject all unknown fields, unlike the outer receipt/process/artifact objects.",
        "risk": "Future consumers can accidentally interpret an ignored field as an additional proof or completion signal.",
        "status": "currently_zero_credit_and_non_authorizing",
        "hardening": "Use an explicit versioned allowlist for each payload or preserve unknown fields only under an inert diagnostic namespace.",
    },
)


def build_audit_report() -> dict[str, Any]:
    return {
        "schema": REPORT_SCHEMA,
        "report_id": REPORT_ID,
        "status": "blocked_fail_closed",
        "audit_mode": "independent_read_only_static_and_adversarial_boundary_audit",
        "scope": {
            "raw_terminal_validator": True,
            "residual_terminal_validator": True,
            "raw_execution_bridge": True,
            "residual_execution_bridge": True,
            "evaluator_artifact_readiness": True,
            "production_validator_capability": True,
            "workload_started": False,
            "popen_attempted": False,
            "real_artifact_opened": False,
        },
        "audited_commits": [
            "06d85f50",
            "bfa1f841",
            "8d3c0f65",
            "65e016ef",
            "6eac3b1e",
            "8900e148",
        ],
        "findings": [dict(item) for item in AUDIT_FINDINGS],
        "hardening_contract": {
            "directory_fd_walk_no_follow": True,
            "single_link_regular_file": True,
            "descriptor_snapshot_read": True,
            "hdf5_open_from_bound_bytes": True,
            "external_soft_and_virtual_links_rejected": True,
            "complete_command_manifest_training_checkpoint_binding": True,
            "self_declared_process_receipt_never_promoted": True,
            "default_and_explicit_execute_rejected": True,
        },
        "side_effects": {
            "processes_started": 0,
            "processes_stopped": 0,
            "processes_restarted": 0,
            "popen_attempts": 0,
            "wait_attempts": 0,
            "solver_started": False,
            "worker_started": False,
            "gpu_used_for_execution": False,
            "queue_submissions": 0,
            "production_artifacts_opened": 0,
            "registry_writes": 0,
            "ledger_writes": 0,
            "gate_writes": 0,
            "completion_writes": 0,
            "plan_writes": 0,
        },
        "blocked_reasons": [
            "findings are recorded without modifying the audited contracts",
            "real Popen/wait witness is absent",
            "production validator capability remains uninstalled",
            "all output remains diagnostic-only and zero-credit",
        ],
        **ZERO_CREDIT,
    }


def validate_audit_report(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        expected = build_audit_report()
        if canonical_json(report) != canonical_json(expected):
            _fail("audit report drifted from the independent bounded contract")
        if report["status"] != "blocked_fail_closed":
            _fail("audit report was promoted from blocked status")
        for key, value in ZERO_CREDIT.items():
            if report.get(key) != value:
                _fail(f"audit report.{key} is not zero-credit")
        if report["scope"]["workload_started"] or report["scope"]["popen_attempted"]:
            _fail("audit report claims a workload or Popen attempt")
    except (SecurityBoundaryError, KeyError, TypeError, ValueError) as error:
        errors.append(str(error))
    return errors


def _write_exclusive(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as error:
        _fail(f"refusing to overwrite audit report: {error}")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-output", type=Path, default=None)
    parser.add_argument("--verify-report", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        if args.verify_report is not None:
            payload = json.loads(args.verify_report.read_text(encoding="utf-8"))
            errors = validate_audit_report(payload)
            if errors:
                _fail("; ".join(errors))
            print(canonical_json({"status": "verified", "report": str(args.verify_report)}))
            return 0
        report = build_audit_report()
        if args.report_output is not None:
            _write_exclusive(args.report_output, report)
        print(canonical_json(report))
        return 0
    except (SecurityBoundaryError, OSError, TypeError, ValueError) as error:
        print(canonical_json({"status": "blocked_fail_closed", "error": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
