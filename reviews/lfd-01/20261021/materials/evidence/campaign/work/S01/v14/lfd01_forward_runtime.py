#!/usr/bin/env python3
"""LFD-01 forward runtime v14 candidate.

This file is a narrow adapter around the immutable DS-DATA-02 v6/v2 runtime.
It binds requests to the new LFD-01 adoption and baseline, reserves against
the real migrated parent ledger, separates LFD-01 NAS bytes from the legacy
Home-floor check, and adds bounded heavy/light process controls.

The prototype intentionally does not modify the consumed v2/v6 scripts.  It
uses their inventory, UUID selection, atomic receipt writer, GenCase parser,
and process-tree CPU accounting through a short-lived patch context.  The
official v12 solver path is unchanged.  Only an explicitly named
``approved_compiled_binary`` request can use the attested BUILD_004 artifact;
that branch temporarily projects the artifact into the immutable v2.SOLVER
constant after its metadata and parent-settlement checks, then restores it.
Production requests still require a new LFD-01 G2 approval document; the
historical mutable DS-DATA-02 approval index is never consulted.

The ``dispatch`` and ``controller`` actions detach a guardian and worker so a
caller can be killed without losing the job identity.  ``recover`` only
settles an exited LFD-01 reservation once, with a bounded unknown CPU/GPU
segment.  None of these actions is an admission grant: every worker still
revalidates the immutable request, grant, adoption, baseline, and parent
history before the v6 reservation lock.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import csv
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
from pathlib import PurePosixPath
import resource
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
import uuid
from typing import Any, Iterator, Mapping, Sequence


SCRIPT_PATH = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT_PATH.parent
SCHEMA_PATH = (SCRIPT_DIR / "candidate-schema.json").resolve()
# The light worker is deliberately sealed by the bwrap command to a single
# fixed script path.  That path has no repository ancestry, so importing the
# normal ``parents[7]`` layout would fail before argparse can enter the
# trusted light operation.  This exact path/action guard is the only
# alternate root; every controller/dispatch/worker/recover invocation keeps
# the normal repository ancestry check below and fails closed when it is
# absent.  The sandbox root is the mounted /opt/lfd01 directory itself and
# is never used to reach a host parent or the parent ledger.
_SEALED_LIGHT_SCRIPT = Path("/opt/lfd01/lfd01_forward_runtime.py")
_SEALED_LIGHT_WORKER = (
    SCRIPT_PATH == _SEALED_LIGHT_SCRIPT
    and len(sys.argv) > 1
    and sys.argv[1] == "light-worker"
)
if _SEALED_LIGHT_WORKER:
    REPO_ROOT = SCRIPT_DIR
    SCRIPTS_ROOT = SCRIPT_DIR
else:
    try:
        REPO_ROOT = SCRIPT_PATH.parents[7]
    except IndexError as error:
        raise RuntimeError(
            "candidate source path is too shallow outside the sealed light-worker entrypoint"
        ) from error
    SCRIPTS_ROOT = REPO_ROOT / "lagrangian-fluid-lab" / "scripts"
V6_PATH = (SCRIPTS_ROOT / "ds_data02_runtime_v6.py").resolve()
V2_PATH = (SCRIPTS_ROOT / "ds_data02_runtime_v2.py").resolve()

PARENT_DATA_ROOT = Path("/data/nas/jade/Simulation/DualSPHysics-data/ds-data-02").resolve()
NAS_ROOT = Path("/data/nas/jade/Simulation/DualSPHysics/lfd-01").resolve()
# This is the explicit read-only NAS source root for the already-authorized
# upstream-first HDF/UFQ inputs.  It is a single source tree, not a wildcard
# permission over NAS.
UPSTREAM_NAS_ROOT = Path("/data/nas/jade/Simulation/DualSPHysics/upstream-first").resolve()
NAS_RUNS = NAS_ROOT / "runs"
JOB_ROOT = NAS_RUNS / ".lfd01-control" / "jobs"
CONTROLLER_LOCK = NAS_RUNS / ".lfd01-control" / "controller.lock"
ADOPTION_PATH = (REPO_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/lfd-01/control/ADOPTION.json").resolve()
BASELINE_PATH = (REPO_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/lfd-01/control/BASELINE.json").resolve()
HOME_ROOT = Path("/home/jade").resolve()
LEGACY_HOME_DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02").resolve()
LAB_HOME_ROOT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab").resolve()
CONTROL_ROOT = (REPO_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/lfd-01/control").resolve()
POLICY_PATH = (REPO_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/lfd-01/adopted-plan/CAMPAIGN_POLICY.json").resolve()
STATUS_PATH = (CONTROL_ROOT / "STATUS.json").resolve()
M0_ACCEPTANCE_DEFAULT = (CONTROL_ROOT / "M0_ACCEPTANCE.json").resolve()
REGISTERED_VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv").resolve()
REGISTERED_VENV_PYTHON = REGISTERED_VENV / "bin/python"
BOOTSTRAP_PROBE_PATH = (SCRIPT_DIR / "bootstrap_probe.py").resolve()
PRLIMIT_PATH = Path("/usr/bin/prlimit").resolve()
PRLIMIT_SHA256 = "740e7bb73625b7aa99821cd6641015dfd0430de801a86881837a2cb688182d94"

SCHEMA = "lfd01.forward-runtime-candidate.v14"
GRANT_SCHEMA = "lfd01.request-grant.v1"
G2_SCHEMA = "lfd01.g2-approval.v1"
NAMESPACE = "LFD01_"
M0_SCHEMA = "lfd01.m0-acceptance.v1"
POLICY_SCHEMA = "lfd01.campaign-planning-policy.v1"

# The consumed v12 runtime remains the execution/accounting implementation.
# This branch is intentionally opt-in: requests without ``solver_branch`` keep
# the v12 official-solver path byte-for-byte in behavior.  The target below is
# the exact BUILD_004 report path; the earlier preparation candidate's
# ``.../s06-build-v2/bin/DualSPHysics5.4_linux64`` path is rejected.
COMPILED_SOLVER_BRANCH = "approved_compiled_binary"
COMPILED_ATTESTATION_SCHEMA = "lfd01.compiled-binary-attestation.v1"
COMPILED_BUILD_ATTEMPT = "infra/LFD01_S06_BUILD/LFD01_BUILD_004"
COMPILED_BUILD_ROOT = NAS_RUNS / COMPILED_BUILD_ATTEMPT
# Keep the final executable component lexical.  Admission and the launch helper
# must see a symlink as a symlink and reject it; resolving this path at import
# time would erase that identity before O_NOFOLLOW can enforce it.
COMPILED_BINARY_PATH = (
    COMPILED_BUILD_ROOT / "s06-build-v2/bin/linux/DualSPHysics5.4_linux64"
)
COMPILED_BINARY_BYTES = 52_743_392
COMPILED_BINARY_SHA256 = "d9285ea3e5d9fb1b7768a6681b4a60e66200cff2094158ec2dc2fe3def001a0f"
COMPILED_BINARY_STAT = {
    "device": 83,
    "inode": 20_185_002,
    "bytes": COMPILED_BINARY_BYTES,
    "mtime_ns": 1_791_852_734_393_531_912,
    "ctime_ns": 1_791_852_734_394_531_912,
}
COMPILED_PARENT_CHARGE_ID = COMPILED_BUILD_ATTEMPT

# These are bounded metadata artifacts already used by the completed build.
# Every item must be repeated as a normal, full-hashed source binding in the
# future v14 request.  The binary itself is deliberately absent from this
# list: it is a deferred source and is full-hashed only at owned launch and
# after confirmed owned-tree exit.
COMPILED_NORMAL_ARTIFACTS = (
    {
        "role": "build_receipt",
        "path": str(COMPILED_BUILD_ROOT / "execution-receipt.json"),
        "bytes": 332_960,
        "sha256": "180cc8eccc0d2786101f8ae86dc1d51c8650c7a84d63879d2105443d4c58832d",
    },
    {
        "role": "build_result",
        "path": str(COMPILED_BUILD_ROOT / "s06-build-v2/build-result-v2.json"),
        "bytes": 568_264,
        "sha256": "5dd067ac46444b16146ea2ea2f8335a972040f27f03fb97b76b089e47bfe126c",
    },
    {
        "role": "build_request",
        "path": str(CONTROL_ROOT.parent / "requests/S06-accepted-dt-build-v4/request.json"),
        "bytes": 127_282,
        "sha256": "924f90c22713746665176de5e2f78cfacd74b7a114faf51277693dfaed2b687c",
    },
    {
        "role": "build_grant",
        "path": str(CONTROL_ROOT.parent / "requests/S06-accepted-dt-build-v4/grant.json"),
        "bytes": 2_775,
        "sha256": "8c6e46fe618ab4cfb63cedefb3727baeb0b7e639d2efc6b718ae179631b2f5f0",
    },
    {
        "role": "build_manifest",
        "path": str(CONTROL_ROOT.parent / "requests/S06-accepted-dt-build-v4/manifest.json"),
        "bytes": 143_691,
        "sha256": "5145758a35e48bf9ad64cfbcd66b664232dfbf082775090e58464f9121a8ff3f",
    },
    {
        "role": "m0_acceptance",
        "path": str(M0_ACCEPTANCE_DEFAULT),
        "bytes": 1_824,
        "sha256": "d2772b43e8fbfe1620f5c4b884fdcd61bf0961b0a5abf817dc563d7f8219d515",
    },
    {
        "role": "source_closure",
        "path": str(CONTROL_ROOT.parent / "work/S06-build-closure/v1/SOURCE_CLOSURE.candidate-v1.json"),
        "bytes": 704_176,
        "sha256": "e62c47cbd4112f4338f4a0228e3b773d2aeca3ed4d63f2f319933d6873c0a31e",
    },
    {
        "role": "compatibility_patch_v2",
        "path": str(CONTROL_ROOT.parent / "work/S06-cuda13-info-compat/v2/FunctionsCuda_cuda13_info_v2.patch"),
        "bytes": 2_159,
        "sha256": "64ccc63f6bfa64ff34d1e6789e3c3b66d9d1477ddf4fe0b7a288923d13688f19",
    },
    {
        "role": "compatibility_expected_source",
        "path": str(CONTROL_ROOT.parent / "work/S06-cuda13-info-compat/v2/expected-patched-source.candidate.cpp"),
        "bytes": 35_946,
        "sha256": "75209a1f7387584c8d501883ec02b0f8d998689530418315b916550e48e918b7",
    },
    {
        "role": "accepted_step_trace",
        "path": str(CONTROL_ROOT.parent / "work/S06-accepted-step-forward/v2/accepted-dt-instrumentation.patch"),
        "bytes": 2_532,
        "sha256": "da75cc4153e84447144e9362497b8926fb17864060761544a108c4fc9f02782e",
    },
    {
        "role": "actual_non_author_review",
        "path": str(CONTROL_ROOT.parent / "work/S06-build-actual-review/v1/REVIEW.json"),
        "bytes": 19_601,
        "sha256": "5c19e9de8b101c39927d506d528786071d2c606e740f721a325e34ecef1b9761",
    },
    {
        "role": "immutable_v12_runtime",
        "path": str(CONTROL_ROOT.parent / "work/S01/v12/lfd01_forward_runtime.py"),
        "bytes": 202_971,
        "sha256": "b1dd30642885bfef04d74dc7c013ecbf466c34f889f7fcb58ba76459a2cce82e",
    },
    {
        "role": "immutable_v12_schema",
        "path": str(CONTROL_ROOT.parent / "work/S01/v12/candidate-schema.json"),
        "bytes": 19_935,
        "sha256": "5a21444d4927edf9bc15fb7650f95680cfdd43095d4c626450a2cf0389b67d99",
    },
)
COMPILED_ARTIFACT_BY_ROLE = {str(item["role"]): item for item in COMPILED_NORMAL_ARTIFACTS}
BOOTSTRAP_SCENARIOS = frozenset({"B01", "B02", "B03", "B04", "B05", "B06", "B07"})
BOOTSTRAP_OPERATIONS = frozenset({
    "cpu-wait", "fork-tree", "ignore-term-grandchild", "notify-root",
    "hold", "write", "fail",
})
CENTRAL_PURPOSES = frozenset({"repair", "holdout", "replay", "closeout"})
LIGHT_NATIVE_SUFFIXES = frozenset({
    ".bi4", ".hdf", ".h5", ".hdf5", ".vtk", ".vtu", ".bin", ".raw", ".dat",
    ".xmf", ".xmlbin", ".npy", ".npz", ".pt", ".pth", ".onnx",
})

GIB = 1024 ** 3
MIB = 1024 ** 2
LIGHT_MAX_JOBS = 4
LIGHT_MAX_THREADS = 2
LIGHT_MAX_COMBINED_THREADS = 8
LIGHT_MAX_RAM = 4 * GIB
LIGHT_MAX_INPUT = 64 * MIB
LIGHT_MAX_OUTPUT = 256 * MIB
LIGHT_MAX_WALL = 600
NAS_MIN_FREE = 2 * 1024 ** 4
NAS_ACTIVE_PEAK_MAX = 256 * GIB
# The worker must retain a small metadata soft limit while allowing the
# trusted child wrapper to lower its own soft/hard limit to a declared
# scientific output bound.  This is an authorization ceiling, not a request
# to raise the host's existing hard limit.
FSIZE_GLOBAL_HARD = 256 * GIB
HOME_MIN_FREE = 500 * GIB
HOME_SCRATCH_MAX = 20 * GIB
HEAVY_RAM_TIERS = (64 * GIB, 128 * GIB, 256 * GIB)
SMALL_METADATA_MAX = 64 * MIB
AUTHORITY_MAX_BYTES = 16 * MIB
CHECKPOINT_INTERVAL = 0.5
GUARDIAN_POLL_INTERVAL = 0.25
GROUP_GRACE_SECONDS = 2.0
PARENT_PROOF_FILENAME = "owned-parent-proof.json"
PARENT_PROOF_ENV_PATH = "LFD01_PARENT_PROOF_PATH"
PARENT_PROOF_ENV_TOKEN = "LFD01_PARENT_PROOF_TOKEN"
PARENT_PROOF_TIMEOUT_SECONDS = 2.0
PARENT_PROOF_POLL_SECONDS = 0.01
PARENT_PROOF_MAX_BYTES = 64 * 1024
TERMINAL_STATUSES = {"completed", "complete", "accepted", "passed", "verified"}


class LFD01Error(RuntimeError):
    """Fail-closed LFD-01 validation or recovery error."""


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject ambiguous control/data JSON before it reaches policy code."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise LFD01Error(f"non-canonical JSON value: {error}") from error


def _sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    target = Path(path)
    if target.is_symlink() or not target.is_file():
        raise LFD01Error(f"source must be a regular non-symlink file: {target}")
    try:
        with target.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as error:
        raise LFD01Error(f"cannot hash {target}: {error}") from error
    return digest.hexdigest()


def _read_json(path: str | Path, label: str, *, max_bytes: int = AUTHORITY_MAX_BYTES) -> dict[str, Any]:
    target = Path(path).expanduser()
    if target.is_symlink() or not target.is_file():
        raise LFD01Error(f"{label} must be a regular non-symlink file: {target}")
    try:
        size = target.stat().st_size
        if size > max_bytes:
            raise LFD01Error(f"{label} exceeds bounded metadata size: {target}")
        raw = target.read_text(encoding="utf-8")
        value = json.loads(raw, parse_constant=lambda token: (_ for _ in ()).throw(
            ValueError(f"non-finite JSON constant {token}")),
            object_pairs_hook=_reject_duplicate_pairs)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise LFD01Error(f"{label} is invalid JSON: {target}: {error}") from error
    if not isinstance(value, dict):
        raise LFD01Error(f"{label} must be a JSON object")
    return value


def _atomic_json(path: str | Path, value: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Heartbeat, RSS watchdog, guardian, and worker terminal paths can all
    # write small records concurrently.  A pid-only temporary name lets one
    # writer replace another writer's temporary file and turns the loser into
    # a spurious FileNotFoundError.  Every atomic write owns a unique sibling.
    temporary = target.with_name(
        f".{target.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp"
    )
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _import_v6_runtime():
    """Import the immutable v6 module with its canonical source directory bound."""
    import importlib
    scripts_root = str(SCRIPTS_ROOT)
    if scripts_root not in sys.path:
        sys.path.insert(0, scripts_root)
    return importlib.import_module("ds_data02_runtime_v6")


def _sha256_json_payload(value: Mapping[str, Any], field: str) -> str:
    payload = deepcopy(dict(value))
    payload.pop(field, None)
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _require_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise LFD01Error(f"{label} must be a lowercase SHA-256 digest")
    return value


def _finite(value: Any, label: str, *, minimum: float = 0.0, integer: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise LFD01Error(f"{label} must be finite numeric data")
    if float(value) < minimum or (integer and not isinstance(value, int)):
        raise LFD01Error(f"{label} has an invalid range or type")
    return float(value)


def _regular_path(value: Any, label: str, *, must_exist: bool = True) -> Path:
    try:
        value = os.fspath(value)
    except TypeError as error:
        raise LFD01Error(f"{label} must be an absolute path") from error
    if not isinstance(value, str) or not value:
        raise LFD01Error(f"{label} must be an absolute path")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise LFD01Error(f"{label} must be absolute")
    if path.is_symlink():
        raise LFD01Error(f"{label} must not be a symlink")
    path = path.resolve()
    if must_exist and (not path.exists() or not path.is_file()):
        raise LFD01Error(f"{label} must be an existing regular file: {path}")
    return path


def _regular_directory(value: Any, label: str) -> Path:
    try:
        value = os.fspath(value)
    except TypeError as error:
        raise LFD01Error(f"{label} must be an absolute directory") from error
    if not isinstance(value, str) or not value:
        raise LFD01Error(f"{label} must be an absolute directory")
    path = Path(value).expanduser()
    if not path.is_absolute() or path.is_symlink():
        raise LFD01Error(f"{label} must be an existing non-symlink directory")
    path = path.resolve()
    if not path.is_dir():
        raise LFD01Error(f"{label} must be an existing directory: {path}")
    return path


def _safe_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for char in value):
        raise LFD01Error(f"unsafe {label}")
    return value


def _attempt_id(request: Mapping[str, Any]) -> str:
    return f"{request['family_id']}/{request['case_id']}/{request['attempt_id']}"


def _is_lfd_attempt(value: Any) -> bool:
    """Recognize every registered LFD record, including bootstrap settlement.

    Historical parent rows do not consistently carry a ``kind`` field.  The
    campaign/case identity is therefore the durable discriminator and remains
    independent from the request namespace check performed at launch.
    """
    text = str(value)
    if text == "infra/LFD01_BOOTSTRAP_SOURCE_ADOPTION/settlement-001":
        return True
    parts = text.split("/")
    if len(parts) != 3:
        return False
    return parts[1].startswith(NAMESPACE) or parts[2].startswith(NAMESPACE)


def _is_lfd_record(row: Mapping[str, Any]) -> bool:
    if row.get("campaign_id") == "LFD-01":
        return True
    return _is_lfd_attempt(row.get("id"))


def _boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return "UNKNOWN_BOOT"


def _proc_start_ticks(pid: int) -> int | None:
    try:
        raw = (Path("/proc") / str(int(pid)) / "stat").read_text()
        suffix = raw.rsplit(")", 1)[1].split()
        return int(suffix[19])  # field 22, after pid/comm; suffix starts at field 3.
    except (OSError, ValueError, IndexError):
        return None


def _pid_matches(pid: int, start_ticks: int | None, host: str, boot: str) -> bool:
    if host != socket.gethostname() or boot != _boot_id():
        return False
    current = _proc_start_ticks(pid)
    return current is not None and start_ticks is not None and current == start_ticks


def _identity_key(identity: Mapping[str, Any] | None) -> tuple[int, int] | None:
    """Return the PID/start-time key used to reject PID reuse."""
    if not isinstance(identity, Mapping):
        return None
    try:
        pid = int(identity.get("pid", 0) or 0)
        start = identity.get("start_ticks")
        if pid <= 1 or start is None:
            return None
        return pid, int(start)
    except (TypeError, ValueError):
        return None


def _identity_from_stat(stat: Mapping[str, Any], *, boot: str | None = None) -> dict[str, Any]:
    return {
        "pid": int(stat["pid"]),
        "host": socket.gethostname(),
        "boot_id": boot if boot is not None else _boot_id(),
        "start_ticks": int(stat["start_ticks"]),
    }


def _known_group_identities(group: Mapping[str, Any]) -> dict[tuple[int, int], dict[str, Any]]:
    known: dict[tuple[int, int], dict[str, Any]] = {}
    values: list[Any] = [group.get("leader")]
    values.extend(group.get("known_members", []) if isinstance(group.get("known_members"), list) else [])
    values.extend(group.get("verified_members", []) if isinstance(group.get("verified_members"), list) else [])
    for value in values:
        key = _identity_key(value)
        if key is not None and isinstance(value, Mapping):
            known[key] = dict(value)
    return known


def _member_identity_proof(
    stat: Mapping[str, Any], known: Mapping[tuple[int, int], Mapping[str, Any]],
    group: Mapping[str, Any] | None = None,
) -> str | None:
    """Prove a live PGID member is the launched tree or a recorded descendant.

    A numeric PGID is reusable.  Exact PID/start_ticks evidence from launch or
    an earlier heartbeat is accepted; otherwise a bounded current PPID chain
    must reach one of those identities.  A member without either proof is
    retained as an uncertainty and cannot be signalled.
    """
    key = _identity_key(stat)
    if key is None:
        return None
    if key in known:
        return "exact_start_ticks"
    current = dict(stat)
    # A Linux subreaper receives descendants after their direct parent exits.
    # The worker itself is outside the scientific PGID, so it is deliberately
    # not included in ``known``.  Accept its PPID only with all three proofs:
    # the worker identity was captured at launch, PR_SET_CHILD_SUBREAPER was
    # enabled before the target Popen, and the adopted member still belongs to
    # the exact target PGID with a start time no earlier than its leader.  A
    # process in a reused PGID cannot satisfy this parent-chain proof.
    subreaper = group.get("subreaper_identity") if isinstance(group, Mapping) else None
    subreaper_key = _identity_key(subreaper)
    leader_key = _identity_key(group.get("leader")) if isinstance(group, Mapping) else None
    try:
        member_pgid = int(stat.get("pgid", 0) or 0)
        group_pgid = int(group.get("pgid", 0) or 0) if isinstance(group, Mapping) else 0
        member_start = int(stat.get("start_ticks", 0) or 0)
        leader_start = int(leader_key[1]) if leader_key is not None else 0
    except (TypeError, ValueError):
        member_pgid = group_pgid = member_start = leader_start = 0
    subreaper_allowed = bool(
        isinstance(group, Mapping)
        and group.get("subreaper_enabled") is True
        and _identity_key(subreaper) == subreaper_key
        and subreaper_key is not None
        and isinstance(subreaper, Mapping)
        and subreaper.get("host") == group.get("host")
        and subreaper.get("boot_id") == group.get("boot_id")
        and member_pgid == group_pgid > 0
        and leader_start > 0
        and member_start >= leader_start
    )
    seen: set[int] = set()
    for _ in range(64):
        try:
            ppid = int(current.get("ppid", 0) or 0)
        except (TypeError, ValueError):
            return None
        if ppid <= 1 or ppid in seen:
            return None
        seen.add(ppid)
        parent = _proc_stat(ppid)
        if parent is None:
            return None
        parent_key = _identity_key(parent)
        if parent_key in known:
            return "ppid_chain"
        if subreaper_allowed and parent_key == subreaper_key:
            return "subreaper_adopted_ppid_chain"
        current = parent
    return None


def _proc_stat(pid: int) -> dict[str, Any] | None:
    """Read the identity and live counters of one process without /proc globbing assumptions."""
    try:
        raw = (Path("/proc") / str(int(pid)) / "stat").read_text()
        head, tail = raw.rsplit(")", 1)
        fields = tail.split()
        # ``fields`` starts with state (field 3); pgrp is field 5, starttime
        # is field 22, utime/stime are fields 14/15.
        ticks = os.sysconf("SC_CLK_TCK")
        return {
            "pid": int(pid),
            "state": fields[0],
            "ppid": int(fields[1]),
            "pgid": int(fields[2]),
            "start_ticks": int(fields[19]),
            "cpu_seconds": (int(fields[11]) + int(fields[12])) / ticks,
            "rss_bytes": int((Path("/proc") / str(int(pid)) / "statm").read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE"),
        }
    except (OSError, ProcessLookupError, PermissionError, ValueError, IndexError):
        return None


def _parent_proof_required(command: Sequence[Any]) -> bool:
    """Require the handshake for the instrumented orphan bootstrap probe."""
    try:
        probe = Path(str(command[1])).expanduser().resolve()
        operation = str(command[2])
    except (IndexError, OSError, RuntimeError):
        return False
    return probe == BOOTSTRAP_PROBE_PATH and operation == "ignore-term-grandchild"


def _proof_token_sha256(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _valid_parent_proof(
    value: Mapping[str, Any], *, token: str, expected_parent: Mapping[str, Any], expected_pgid: int,
) -> dict[str, Any] | None:
    """Validate a probe-written parent/child identity before trusting adoption."""
    if value.get("schema") != "lfd01.parent-proof.v1" or value.get("token") != token:
        return None
    host = socket.gethostname()
    boot = _boot_id()
    if value.get("host") != host or value.get("boot_id") != boot:
        return None
    parent = value.get("parent_identity")
    child = value.get("child_identity")
    if not isinstance(parent, Mapping) or not isinstance(child, Mapping):
        return None
    expected_parent_key = _identity_key(expected_parent)
    if expected_parent_key is None or _identity_key(parent) != expected_parent_key:
        return None
    if parent.get("host") != host or parent.get("boot_id") != boot:
        return None
    child_key = _identity_key(child)
    if child_key is None or child.get("host") != host or child.get("boot_id") != boot:
        return None
    try:
        child_ppid = int(value.get("child_ppid", 0) or 0)
        child_pgid = int(value.get("child_pgid", 0) or 0)
        parent_pid = int(expected_parent.get("pid", 0) or 0)
        parent_start = int(expected_parent.get("start_ticks", 0) or 0)
        child_start = int(child.get("start_ticks", 0) or 0)
    except (TypeError, ValueError):
        return None
    if child_ppid != parent_pid or child_pgid != int(expected_pgid) or child_start < parent_start:
        return None
    # If the proven child is still live, recheck PID/start/PGID.  It may have
    # been reparented to the worker or PID 1 by the time the file is read, so
    # the historical parent identity is the proof of its original ownership.
    current = _proc_stat(child_key[0])
    if current is not None and (
            int(current.get("start_ticks", -1)) != child_key[1]
            or int(current.get("pgid", -1)) != int(expected_pgid)):
        return None
    return {
        "schema": "lfd01.parent-proof.v1",
        "host": host,
        "boot_id": boot,
        "parent_identity": dict(parent),
        "child_identity": dict(child),
        "child_ppid": child_ppid,
        "child_pgid": child_pgid,
        "token_sha256": _proof_token_sha256(token),
        "verified_at_utc": _now(),
    }


def _await_parent_proof(
    path: Path, *, token: str, expected_parent: Mapping[str, Any], expected_pgid: int,
    timeout: float = PARENT_PROOF_TIMEOUT_SECONDS,
) -> dict[str, Any] | None:
    """Bounded poll for the pre-exit handshake; never trusts an invalid file."""
    deadline = time.monotonic() + max(0.0, float(timeout))
    resolved_parent = path.parent.resolve()
    while True:
        try:
            if (not path.is_symlink() and path.is_file()
                    and path.resolve().parent == resolved_parent
                    and path.stat().st_size <= PARENT_PROOF_MAX_BYTES):
                value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_pairs)
                if isinstance(value, Mapping):
                    proof = _valid_parent_proof(
                        value, token=token, expected_parent=expected_parent, expected_pgid=expected_pgid
                    )
                    if proof is not None:
                        return proof
        except (OSError, ProcessLookupError, PermissionError, ValueError, TypeError, LFD01Error):
            pass
        if time.monotonic() >= deadline:
            return None
        time.sleep(PARENT_PROOF_POLL_SECONDS)


def _owned_group_snapshot(group: Mapping[str, Any]) -> dict[str, Any]:
    """Return a process-group snapshot with explicit PID/start-time proof."""
    pgid = int(group.get("pgid", 0) or 0)
    if pgid <= 0:
        return {"pgid": pgid, "members": [], "exited_members": [],
                "verified_members": [], "identity_unverified_members": [],
                "verified_member_proofs": [],
                "cpu_seconds": 0.0, "rss_bytes": 0}
    current_host = socket.gethostname()
    current_boot = _boot_id()
    if group.get("host") != current_host or group.get("boot_id") != current_boot:
        return {"pgid": pgid, "members": [], "exited_members": [],
                "verified_members": [], "identity_unverified_members": [],
                "verified_member_proofs": [],
                "identity_mismatch": True, "cpu_seconds": 0.0, "rss_bytes": 0,
                "observed_at_utc": _now()}
    known = _known_group_identities(group)
    members: list[dict[str, Any]] = []
    exited_members: list[dict[str, Any]] = []
    verified_members: list[dict[str, Any]] = []
    verified_member_proofs: list[dict[str, Any]] = []
    identity_unverified_members: list[dict[str, Any]] = []
    cpu = 0.0
    rss = 0
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        stat = _proc_stat(int(entry.name))
        if stat is None or stat["pgid"] != pgid:
            continue
        identity = _identity_from_stat(stat, boot=current_boot)
        proof = _member_identity_proof(stat, known, group)
        member = {**identity, "state": stat["state"], "cpu_seconds": stat["cpu_seconds"],
                  "rss_bytes": stat["rss_bytes"], "ppid": stat["ppid"],
                  "identity_proof": proof}
        if proof is not None:
            verified_members.append(identity)
            verified_member_proofs.append({"identity": identity, "proof": proof})
        else:
            identity_unverified_members.append(member)
        # A zombie has already stopped executing and no longer needs a signal.
        # Treat it as an exited member for cleanup confirmation; a live member
        # remains the only process that can contribute sampled CPU/RSS here.
        if stat["state"] in {"Z", "X"}:
            exited_members.append(member)
            continue
        members.append(member)
        if proof is not None:
            cpu += float(stat["cpu_seconds"])
            rss += int(stat["rss_bytes"])
    return {"pgid": pgid, "members": members, "exited_members": exited_members,
            "verified_members": verified_members,
            "identity_unverified_members": identity_unverified_members,
            "verified_member_proofs": verified_member_proofs,
            "cpu_seconds": cpu, "rss_bytes": rss,
            "observed_at_utc": _now()}


def _enable_subreaper() -> bool:
    """Make orphaned grandchildren reparent to the worker for disjoint reaping."""
    try:
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        result = libc.prctl(36, 1, 0, 0, 0)  # PR_SET_CHILD_SUBREAPER
        return result == 0
    except (AttributeError, OSError, ImportError):
        return False


def _reap_owned_descendants(group: Mapping[str, Any]) -> int:
    """Reap only proven members of one owned process group.

    ``waitpid(-1)`` could consume an unrelated helper child and fold its CPU
    into the target worker's RUSAGE_CHILDREN interval.  A member is eligible
    only when the current group snapshot has PID/start/PGID proof; a vanished
    or mismatched identity is left unresolved for the recovery path.
    """
    if not isinstance(group, Mapping):
        return 0
    snapshot = _owned_group_snapshot(group)
    candidates = [
        *snapshot.get("members", []),
        *snapshot.get("exited_members", []),
    ]
    reaped = 0
    seen: set[tuple[int, int]] = set()
    expected_pgid = int(group.get("pgid", 0) or 0)
    for member in candidates:
        if not isinstance(member, Mapping) or member.get("identity_proof") is None:
            continue
        key = _identity_key(member)
        if key is None or key in seen:
            continue
        seen.add(key)
        current = _proc_stat(key[0])
        if (current is None or _identity_key(current) != key
                or int(current.get("pgid", 0) or 0) != expected_pgid):
            continue
        try:
            pid, _status = os.waitpid(key[0], os.WNOHANG)
        except (ChildProcessError, OSError, ProcessLookupError):
            continue
        if pid == key[0]:
            reaped += 1
    return reaped


def _final_reap_owned_descendants(group: Mapping[str, Any], *, timeout: float = GROUP_GRACE_SECONDS) -> dict[str, Any]:
    """Bound the final zombie reap and return the post-reap group snapshot.

    This is deliberately after the SIGTERM/SIGKILL grace path.  RUSAGE_CHILDREN
    is updated by waitpid, so the final reap must complete before v6 takes its
    terminal CPU cutoff and before deferred/G2 proof is written.
    """
    deadline = time.monotonic() + max(0.0, float(timeout))
    reaped = 0
    snapshot: dict[str, Any] = {}
    while True:
        reaped += _reap_owned_descendants(group)
        snapshot = _owned_group_snapshot(group)
        if (not snapshot.get("members") and not snapshot.get("exited_members")
                and not snapshot.get("identity_unverified_members")
                and not snapshot.get("identity_mismatch")):
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(0.02)
    return {"reaped": reaped, "snapshot": snapshot,
            "completed": (not snapshot.get("members")
                          and not snapshot.get("exited_members")
                          and not snapshot.get("identity_unverified_members")
                          and not snapshot.get("identity_mismatch"))}


def _proc_group_cpu_seconds(group: Mapping[str, Any]) -> float:
    return float(_owned_group_snapshot(group).get("cpu_seconds", 0.0))


@contextmanager
def _locked_parent_ledger() -> Iterator[dict[str, Any]]:
    """Read the real parent ledger under its lock without rewriting it."""
    _assert_parent_data_root()
    lock_path = PARENT_DATA_ROOT / "runtime" / "resource-ledger.lock"
    ledger_path = PARENT_DATA_ROOT / "runtime" / "resource-ledger.json"
    with lock_path.open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield _read_json(ledger_path, "real parent resource ledger", max_bytes=32 * MIB)
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _authority() -> tuple[dict[str, Any], dict[str, Any], str, str]:
    adoption = _read_json(ADOPTION_PATH, "LFD-01 adoption")
    baseline = _read_json(BASELINE_PATH, "LFD-01 parent baseline", max_bytes=32 * MIB)
    adoption_sha = _sha256(ADOPTION_PATH)
    baseline_sha = _sha256(BASELINE_PATH)
    if adoption.get("schema") != "lfd01.adoption.v1" or adoption.get("campaign_id") != "LFD-01":
        raise LFD01Error("new LFD-01 adoption schema/campaign binding is invalid")
    if adoption.get("status") != "adopted_active":
        raise LFD01Error("LFD-01 adoption is not active")
    if adoption.get("parent_data_root") != str(PARENT_DATA_ROOT) or adoption.get("nas_root") != str(NAS_ROOT):
        raise LFD01Error("LFD-01 adoption roots do not bind the canonical NAS paths")
    if baseline.get("schema") != "lfd01.parent-baseline.v1" or baseline.get("campaign_id") != "LFD-01":
        raise LFD01Error("LFD-01 parent baseline schema/campaign binding is invalid")
    if baseline.get("source_ledger", {}).get("path") != str(PARENT_DATA_ROOT / "runtime/resource-ledger.json"):
        raise LFD01Error("baseline does not bind the canonical parent ledger")
    caps = adoption.get("effective_caps")
    if not isinstance(caps, dict):
        raise LFD01Error("LFD-01 adoption has no effective caps")
    for key in ("gpu_seconds", "cpu_core_seconds", "new_storage_bytes", "solver_attempts"):
        value = caps.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value <= 0:
            raise LFD01Error(f"LFD-01 effective cap is invalid: {key}")
    return adoption, baseline, adoption_sha, baseline_sha


def _verify_history(ledger: Mapping[str, Any], adoption: Mapping[str, Any], baseline: Mapping[str, Any]) -> None:
    if ledger.get("campaign_id") != "DS-DATA-02":
        raise LFD01Error("real parent ledger campaign identity changed")
    if ledger.get("deadline_utc") != adoption.get("deadline_utc"):
        raise LFD01Error("real parent deadline is not the forward-locked LFD-01 deadline")
    if ledger.get("limits") != baseline.get("limits"):
        raise LFD01Error("real parent limits differ from the immutable LFD-01 baseline")
    charges = ledger.get("charges")
    attempts = ledger.get("attempts")
    reservations = ledger.get("reservations")
    if not isinstance(charges, list) or not isinstance(attempts, list) or not isinstance(reservations, list):
        raise LFD01Error("real parent ledger collections are malformed")
    charge_by_id = {row.get("id"): row for row in charges if isinstance(row, dict) and isinstance(row.get("id"), str)}
    attempt_by_id = {row.get("id"): row for row in attempts if isinstance(row, dict) and isinstance(row.get("id"), str)}
    if len(charge_by_id) != len(charges) or len(attempt_by_id) != len(attempts):
        raise LFD01Error("real parent ledger has duplicate or malformed historical ids")
    for binding in baseline.get("prior_charge_rows", []):
        ident = binding.get("id")
        row = charge_by_id.get(ident)
        if row is None or hashlib.sha256(_canonical(row)).hexdigest() != binding.get("sha256"):
            raise LFD01Error(f"historical parent charge changed: {ident}")
    for binding in baseline.get("prior_attempt_rows", []):
        ident = binding.get("id")
        row = attempt_by_id.get(ident)
        if row is None or hashlib.sha256(_canonical(row)).hexdigest() != binding.get("sha256"):
            raise LFD01Error(f"historical parent attempt changed: {ident}")
    # Old status rows are historical evidence.  A reservation is active only
    # when it is an actual row in the real reservations collection.
    for row in reservations:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise LFD01Error("real parent ledger has a malformed active reservation")


def _source_projection(request: Mapping[str, Any]) -> str:
    bindings = request.get("source_bindings")
    if not isinstance(bindings, list):
        raise LFD01Error("source_bindings are required")
    return hashlib.sha256(_canonical(bindings)).hexdigest()


def _artifact_binding(value: Any, label: str, *, max_bytes: int = SMALL_METADATA_MAX) -> tuple[Path, str, dict[str, Any]]:
    if not isinstance(value, dict):
        raise LFD01Error(f"{label} binding is required")
    path = _regular_path(value.get("path"), f"{label} path")
    expected = _require_sha(value.get("sha256"), f"{label} sha256")
    if path.stat().st_size > max_bytes:
        raise LFD01Error(f"{label} exceeds bounded metadata size")
    if _sha256(path) != expected:
        raise LFD01Error(f"{label} changed or has the wrong hash")
    return path, expected, value


def _review_record(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("status") != "accepted":
        raise LFD01Error(f"{label} is not an accepted review record")
    reviewer = value.get("reviewer") or value.get("reviewer_id")
    if not isinstance(reviewer, str) or not reviewer or reviewer.lower() in {"controller", "root"}:
        raise LFD01Error(f"{label} must name an independent reviewer")
    digest = _require_sha(value.get("sha256"), f"{label} sha256")
    return {"status": "accepted", "reviewer": reviewer, "sha256": digest}


def _validate_g2(request: Mapping[str, Any], *, after_hashes: bool = False) -> dict[str, Any] | None:
    if request.get("kind") != "production":
        return None
    binding = request.get("g2_approval")
    path, expected, _ = _artifact_binding(binding, "G2 approval")
    value = _read_json(path, "G2 approval", max_bytes=SMALL_METADATA_MAX)
    if value.get("schema") != G2_SCHEMA or value.get("campaign_id") != "LFD-01":
        raise LFD01Error("G2 approval is not an LFD-01 artifact")
    if value.get("status") != "accepted" or value.get("g2_for_common_core_task") is not True:
        raise LFD01Error("G2 approval is not accepted for a common core task")
    for field in ("recipe_id", "domain_id", "common_core_task_id"):
        if not isinstance(value.get(field), str) or not value[field]:
            raise LFD01Error(f"G2 approval lacks {field}")
        if request.get(field) != value[field]:
            raise LFD01Error(f"production request {field} differs from G2 approval")
    # A bare accepted boolean is insufficient.  Every production grant binds
    # author, non-author, static, integration, scientific-contract, and actual
    # source evidence as immutable records.
    author = _review_record(value.get("author_review"), "G2 author review")
    non_author = _review_record(value.get("non_author_review"), "G2 non-author review")
    if author["reviewer"] == non_author["reviewer"]:
        raise LFD01Error("G2 author and non-author reviewers must be distinct")
    if value.get("non_author_review_hash") != non_author["sha256"]:
        raise LFD01Error("G2 non-author review hash is not bound exactly")
    static_review = _review_record(value.get("static_review"), "G2 static review")
    launch = value.get("launch_commit")
    if not isinstance(launch, dict) or launch.get("status") != "accepted":
        raise LFD01Error("G2 launch commit binding is missing")
    integration = launch.get("integration_commit") or launch.get("commit")
    if not isinstance(integration, str) or len(integration) < 7 or any(c not in "0123456789abcdef" for c in integration.lower()):
        raise LFD01Error("G2 integration commit is not a hexadecimal identity")
    contract = value.get("scientific_contract")
    if not isinstance(contract, dict) or contract.get("status") != "accepted":
        raise LFD01Error("G2 scientific contract binding is missing")
    contract_sha = _require_sha(contract.get("sha256"), "G2 scientific contract sha256")
    source_proof = value.get("actual_source_proof")
    if not isinstance(source_proof, dict) or source_proof.get("status") != "accepted":
        raise LFD01Error("G2 actual source proof is missing")
    proof_sha = _require_sha(source_proof.get("sha256"), "G2 actual source proof sha256")
    projection = _require_sha(source_proof.get("source_bindings_sha256"), "G2 source bindings sha256")
    requested_projection = _source_projection(request)
    if projection != requested_projection:
        raise LFD01Error("G2 actual source proof does not bind this request source set")
    return {
        "schema": G2_SCHEMA, "path": str(path), "sha256": expected,
        "recipe_id": value["recipe_id"], "domain_id": value["domain_id"],
        "common_core_task_id": value["common_core_task_id"],
        "author_review_sha256": author["sha256"], "non_author_review_sha256": non_author["sha256"],
        "static_review_sha256": static_review["sha256"], "integration_commit": integration,
        "scientific_contract_sha256": contract_sha, "actual_source_proof_sha256": proof_sha,
        "source_bindings_sha256": projection, "verified_after_hashes": bool(after_hashes),
    }


def _validate_m0_artifact(binding: Any) -> dict[str, Any]:
    path, expected, _ = _artifact_binding(binding, "M0 acceptance")
    value = _read_json(path, "M0 acceptance", max_bytes=SMALL_METADATA_MAX)
    if value.get("schema") != M0_SCHEMA or value.get("campaign_id") != "LFD-01" or value.get("status") != "accepted":
        raise LFD01Error("M0 acceptance is not an accepted LFD-01 artifact")
    reviewer = value.get("accepted_by") or value.get("reviewer")
    if not isinstance(reviewer, str) or reviewer.lower() in {"controller", "root"}:
        raise LFD01Error("M0 acceptance must name an independent reviewer")
    if not isinstance(value.get("actual_bootstrap_receipt_sha256"), str):
        raise LFD01Error("M0 acceptance lacks actual bootstrap receipt proof")
    scenarios = value.get("scenario_ids")
    if set(scenarios or ()) != set(BOOTSTRAP_SCENARIOS):
        raise LFD01Error("M0 acceptance does not cover all seven actual bootstrap scenarios")
    return {"schema": M0_SCHEMA, "path": str(path), "sha256": expected,
            "accepted_by": reviewer, "scenario_ids": sorted(BOOTSTRAP_SCENARIOS)}


def _validate_m0_scope(request: Mapping[str, Any], grant: Mapping[str, Any]) -> dict[str, Any] | None:
    bootstrap = request.get("bootstrap") is True
    if grant.get("bootstrap") is not bootstrap:
        raise LFD01Error("grant bootstrap binding differs from request")
    m0 = grant.get("m0_gate")
    if m0 is not None:
        _validate_m0_artifact(m0)
    if bootstrap:
        scenario = request.get("bootstrap_scenario_id")
        if scenario not in BOOTSTRAP_SCENARIOS or request.get("kind") != "cpu" or request.get("cpu_task_kind") != "tests":
            raise LFD01Error("bootstrap scope is restricted to one of seven CPU test scenarios")
        command = request.get("command")
        probe_positions = ([index for index, arg in enumerate(command)
                            if isinstance(arg, str) and Path(arg).name == BOOTSTRAP_PROBE_PATH.name]
                           if isinstance(command, list) else [])
        if len(probe_positions) != 1:
            raise LFD01Error("bootstrap CPU tests must execute the sealed bootstrap probe")
        probe_index = probe_positions[0]
        try:
            probe_path = Path(str(command[probe_index])).expanduser().resolve()
        except (OSError, RuntimeError, ValueError) as error:
            raise LFD01Error("bootstrap probe path cannot be resolved") from error
        if probe_path != BOOTSTRAP_PROBE_PATH or probe_index + 1 >= len(command):
            raise LFD01Error("bootstrap CPU tests must execute the sealed bootstrap probe")
        operation = command[probe_index + 1]
        if operation not in BOOTSTRAP_OPERATIONS:
            raise LFD01Error("bootstrap operation is outside the sealed probe allowlist")
        if (operation == "notify-root") != (scenario == "B07"):
            raise LFD01Error("notify-root is reserved for the B07 caller-exit/wakeup scenario")
        if m0 is not None:
            raise LFD01Error("bootstrap grants do not consume the post-bootstrap M0 gate")
        return None
    if request.get("execution_class") == "heavy" and m0 is None:
        raise LFD01Error("non-bootstrap heavy work is blocked until exact root M0 acceptance")
    if request.get("execution_class") == "light" and request.get("light_operation") not in {"json_collection_counts", "csv_summary"}:
        raise LFD01Error("pre-M0 light work is limited to sealed metadata operations")
    return _validate_m0_artifact(m0) if m0 is not None else None


def _notify_root_command(command: Sequence[str], probe_index: int, request: Mapping[str, Any]) -> dict[str, Any] | None:
    """Validate the fixed one-shot B07 wakeup operation before launch.

    The probe itself runs inside the already admitted worker subtree.  It may
    invoke exactly one root-owned helper, but only with the durable receipt
    belonging to the supplied job id.  The receipt can be created after
    request admission, so its path is checked lexically and against the
    canonical request output here; the helper performs the live
    controller-identity and RUNNING-receipt checks at execution.
    """
    if probe_index + 1 >= len(command) or command[probe_index + 1] != "notify-root":
        return None
    tail = list(command[probe_index + 2:])
    values: dict[str, str] = {}
    allowed = {"--helper", "--job-id", "--event-id", "--receipt"}
    if len(tail) % 2:
        raise LFD01Error("notify-root arguments must be fixed flag/value pairs")
    for index in range(0, len(tail), 2):
        flag, value = tail[index], tail[index + 1]
        if flag not in allowed or flag in values or not value:
            raise LFD01Error("notify-root contains an unknown, repeated, or empty argument")
        values[flag] = value
    required = {"--helper", "--job-id", "--event-id", "--receipt"}
    if set(values) - allowed or not required.issubset(values):
        raise LFD01Error("notify-root requires helper, job id, event id, and receipt bindings")
    helper = _regular_path(values["--helper"], "notify-root helper")
    if helper.parent != CONTROL_ROOT:
        raise LFD01Error("notify-root helper must be a regular file directly in the fixed control root")
    job_id = _safe_id(values["--job-id"], "notify-root job_id")
    if not job_id.startswith(NAMESPACE):
        raise LFD01Error("notify-root job_id must use the LFD01_ namespace")
    event_id = _safe_id(values["--event-id"], "notify-root event_id")
    if not event_id.startswith(NAMESPACE):
        raise LFD01Error("notify-root event_id must use the LFD01_ namespace")
    expected_receipt = (NAS_RUNS / _attempt_id(request) / "execution-receipt.json").resolve()
    paths: dict[str, Path] = {"helper": helper}
    raw = Path(values["--receipt"]).expanduser()
    if not raw.is_absolute() or ".." in raw.parts or raw.is_symlink():
        raise LFD01Error("notify-root receipt path is unsafe")
    receipt = raw.resolve()
    if receipt != expected_receipt:
        raise LFD01Error("notify-root receipt must bind this request's canonical execution receipt")
    paths["receipt"] = receipt
    return {"helper": helper, "job_id": job_id, "event_id": event_id,
            "receipt": paths["receipt"]}


def _allowed_source(path: Path) -> bool:
    allowed = (
        REPO_ROOT,
        Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official").resolve(),
        LAB_HOME_ROOT,
        PARENT_DATA_ROOT,
        LEGACY_HOME_DATA_ROOT,
        NAS_ROOT,
        UPSTREAM_NAS_ROOT,
        Path("/usr/bin").resolve(),
        Path("/usr/lib").resolve(),
        # Existing local CUDA 13.2 toolchain, needed for accepted-dt instrumentation.
        # Read-only source admission only; no install, output, quota, or permission change.
        Path("/usr/local/cuda-13.2").resolve(),
        Path("/lib").resolve(),
        Path("/lib64").resolve(),
    )
    return any(path == root or path.is_relative_to(root) for root in allowed)


def _registered_venv_launcher(value: Any, label: str) -> tuple[Path, Path] | None:
    """Accept the one registered scientific venv launcher with explicit provenance.

    The launcher itself is a symlink by normal venv convention.  Its canonical
    interpreter remains hash-bound and the surrounding request must bind
    ``pyvenv.cfg`` and dependency provenance as normal source records.
    """
    try:
        value = os.fspath(value)
    except TypeError as error:
        raise LFD01Error(f"{label} must be an absolute path") from error
    if not isinstance(value, str) or not value:
        return None
    lexical = Path(value).expanduser()
    if lexical != REGISTERED_VENV_PYTHON:
        return None
    if not lexical.is_symlink():
        raise LFD01Error(f"registered venv launcher must retain its lexical symlink: {label}")
    canonical = lexical.resolve()
    if not canonical.is_file() or canonical.is_symlink():
        raise LFD01Error(f"registered venv interpreter target is not a regular file: {canonical}")
    pyvenv = REGISTERED_VENV / "pyvenv.cfg"
    if pyvenv.is_symlink() or not pyvenv.is_file():
        raise LFD01Error("registered venv pyvenv.cfg is missing or unsafe")
    return lexical, canonical


def _binary_path(value: Any, label: str) -> tuple[Path, Path]:
    launcher = _registered_venv_launcher(value, label)
    if launcher is not None:
        return launcher
    path = _regular_path(value, label)
    return path, path


def _runtime_roots(request: Mapping[str, Any]) -> None:
    for path, label in ((SCRIPT_PATH, "candidate runtime"), (SCHEMA_PATH, "candidate schema"),
                        (V6_PATH, "v6 runtime"), (V2_PATH, "v2 runtime")):
        if not path.is_file() or not _allowed_source(path):
            raise LFD01Error(f"{label} is not a permitted regular source")


def _source_path(value: Any, label: str) -> tuple[Path, Path | None]:
    launcher = _registered_venv_launcher(value, label)
    if launcher is not None:
        lexical, canonical = launcher
        return canonical, lexical
    return _regular_path(value, label), None


def _validate_sources(request: Mapping[str, Any]) -> dict[str, str]:
    bindings = request.get("source_bindings")
    if not isinstance(bindings, list) or not bindings:
        raise LFD01Error("source_bindings must be a non-empty list")
    by_path: dict[str, dict[str, Any]] = {}
    for item in bindings:
        if not isinstance(item, dict):
            raise LFD01Error("source binding must be an object")
        path, launcher = _source_path(item.get("path"), "source binding path")
        if not _allowed_source(path):
            raise LFD01Error(f"source path is outside the LFD-01 whitelist: {path}")
        key = str(path)
        if key in by_path:
            raise LFD01Error(f"duplicate source binding: {path}")
        expected = _require_sha(item.get("sha256"), f"source sha256 {path}")
        deferred = item.get("deferred", False)
        if not isinstance(deferred, bool):
            raise LFD01Error(f"source deferred flag is invalid: {path}")
        size = path.stat().st_size
        declared_bytes = item.get("bytes")
        _finite(declared_bytes, f"source bytes {path}", minimum=0, integer=True)
        if int(declared_bytes) != size:
            raise LFD01Error(f"source byte declaration differs: {path}")
        if not deferred and size > SMALL_METADATA_MAX:
            raise LFD01Error(f"non-deferred source exceeds bounded metadata size: {path}")
        by_path[key] = {"path": key, "sha256": expected, "deferred": deferred, "bytes": size,
                        "role": item.get("role"), "launcher_path": str(launcher) if launcher else None}
    input_files = request.get("input_files")
    if not isinstance(input_files, list) or not input_files:
        raise LFD01Error("input_files must be a non-empty list")
    normal_inputs: set[str] = set()
    for raw in input_files:
        path, _launcher = _source_path(raw, "input file")
        binding = by_path.get(str(path))
        if binding is None:
            raise LFD01Error(f"input file lacks an exact source binding: {path}")
        if binding["deferred"]:
            raise LFD01Error("deferred inputs must be excluded from v6 input_files")
        normal_inputs.add(str(path))
    deferred = [row for row in by_path.values() if row["deferred"]]
    if sum(row["bytes"] for row in by_path.values() if not row["deferred"]) > (LIGHT_MAX_INPUT if request.get("execution_class") == "light" else 2 * SMALL_METADATA_MAX):
        raise LFD01Error("normal metadata inputs exceed the bounded preflight budget")
    for required in (str(SCRIPT_PATH), str(V6_PATH), str(V2_PATH)):
        if required not in normal_inputs:
            raise LFD01Error(f"immutable runtime source is not bound as a normal input: {required}")
    # A scientific request may execute the registered virtualenv interpreter.
    # Its lexical launcher and environment metadata must be explicit inputs;
    # silently substituting /usr/bin/python would change dependency semantics.
    launcher_bindings = [row for row in by_path.values() if row.get("launcher_path")]
    if launcher_bindings:
        pyvenv_key = str(REGISTERED_VENV / "pyvenv.cfg")
        if pyvenv_key not in normal_inputs:
            raise LFD01Error("registered venv launcher requires pyvenv.cfg input binding")
        if not any(row.get("role") == "venv_dependency_provenance" for row in by_path.values()):
            raise LFD01Error("registered venv launcher requires dependency provenance binding")
    if request.get("execution_class") == "light" and deferred:
        raise LFD01Error("light jobs cannot declare deferred or large inputs")
    small_hashes: dict[str, str] = {}
    for path in sorted(normal_inputs):
        actual = _sha256(path)
        expected = by_path[path]["sha256"]
        if actual != expected:
            raise LFD01Error(f"normal source hash mismatch: {path}")
        small_hashes[path] = actual
    return {**small_hashes, "__deferred__": json.dumps(deferred, sort_keys=True)}


def _compiled_normal_artifact_bindings(
    request: Mapping[str, Any], small_hashes: Mapping[str, str],
) -> dict[str, dict[str, Any]]:
    """Require the fixed BUILD_004 evidence set as normal request inputs.

    The request may carry additional scientific inputs, but it cannot replace,
    rename, defer, or silently omit any member of the reviewed build chain.
    ``small_hashes`` is the result of v12's normal-input hashing pass, so this
    check does not open the deferred binary.
    """
    attestation = request.get("compiled_binary_attestation")
    if not isinstance(attestation, dict) or attestation.get("schema") != COMPILED_ATTESTATION_SCHEMA:
        raise LFD01Error("compiled binary branch requires the reviewed attestation schema")
    if attestation.get("status") != "accepted_build_artifact":
        raise LFD01Error("compiled binary attestation is not an accepted BUILD_004 artifact")
    if attestation.get("build_attempt_id") != COMPILED_BUILD_ATTEMPT:
        raise LFD01Error("compiled binary attestation binds a different build attempt")
    deferred_binary = attestation.get("deferred_binary")
    if (not isinstance(deferred_binary, dict)
            or deferred_binary.get("exclude_from_input_files") is not True
            or deferred_binary.get("full_sha256_at") != ["owned_launch", "after_owned_reap"]):
        raise LFD01Error("compiled binary must be deferred and hashed at launch and after owned reap")
    parent = attestation.get("parent_settlement")
    if (not isinstance(parent, dict)
            or parent.get("charge_id") != COMPILED_PARENT_CHARGE_ID
            or parent.get("charge_count") != 1
            or parent.get("reservation_count") != 0
            or parent.get("uuid_lease") != "absent"):
        raise LFD01Error("compiled binary attestation lacks the exact unique parent settlement declaration")

    rows = attestation.get("normal_inputs")
    if not isinstance(rows, list):
        raise LFD01Error("compiled binary attestation normal_inputs must be a list")
    attested_by_role: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("role"), str):
            raise LFD01Error("compiled binary attestation has an invalid normal input row")
        role = str(row["role"])
        if role in attested_by_role:
            raise LFD01Error(f"duplicate compiled binary attestation role: {role}")
        attested_by_role[role] = row

    input_paths: set[str] = set()
    for raw in request.get("input_files", []):
        path, _launcher = _source_path(raw, "compiled branch input file")
        input_paths.add(str(path))
    bound_by_role: dict[str, dict[str, Any]] = {}
    source_bindings = request.get("source_bindings", [])
    for artifact in COMPILED_NORMAL_ARTIFACTS:
        role = str(artifact["role"])
        attested = attested_by_role.get(role)
        if attested is None:
            raise LFD01Error(f"compiled binary attestation omits normal input role: {role}")
        expected_path = Path(str(artifact["path"])).resolve()
        if (attested.get("path") != str(expected_path)
                or attested.get("bytes") != artifact["bytes"]
                or attested.get("sha256") != artifact["sha256"]):
            raise LFD01Error(f"compiled binary attestation row differs for {role}")
        if str(expected_path) not in input_paths:
            raise LFD01Error(f"compiled BUILD_004 evidence must be a normal input: {role}")
        if small_hashes.get(str(expected_path)) != artifact["sha256"]:
            raise LFD01Error(f"compiled BUILD_004 normal input hash is not verified: {role}")
        matched = []
        for raw in source_bindings:
            if not isinstance(raw, dict):
                continue
            candidate, _launcher = _source_path(raw.get("path"), "compiled source binding path")
            if candidate == expected_path:
                matched.append(raw)
        if len(matched) != 1:
            raise LFD01Error(f"compiled BUILD_004 role lacks one exact source binding: {role}")
        binding = matched[0]
        if (binding.get("role") != role or binding.get("deferred") is not False
                or binding.get("bytes") != artifact["bytes"]
                or binding.get("sha256") != artifact["sha256"]):
            raise LFD01Error(f"compiled BUILD_004 source binding differs for {role}")
        bound_by_role[role] = binding
    if set(attested_by_role) != {str(item["role"]) for item in COMPILED_NORMAL_ARTIFACTS}:
        raise LFD01Error("compiled binary attestation contains an unregistered normal input role")
    return bound_by_role


def _compiled_metadata(request: Mapping[str, Any], role: str, *, max_bytes: int = 2 * MIB) -> dict[str, Any]:
    artifact = COMPILED_ARTIFACT_BY_ROLE.get(role)
    attestation = request.get("compiled_binary_attestation")
    rows = attestation.get("normal_inputs") if isinstance(attestation, dict) else None
    row = next((item for item in rows or []
                if isinstance(item, dict) and item.get("role") == role), None)
    if artifact is None or not isinstance(row, dict):
        raise LFD01Error(f"unknown compiled metadata role: {role}")
    path = Path(str(row.get("path"))).resolve()
    if (path != Path(str(artifact["path"])).resolve()
            or row.get("bytes") != artifact["bytes"]
            or row.get("sha256") != artifact["sha256"]):
        raise LFD01Error(f"compiled metadata request binding differs for {role}")
    if path.stat().st_size != int(artifact["bytes"]):
        raise LFD01Error(f"compiled metadata byte count changed: {role}")
    if int(artifact["bytes"]) > max_bytes:
        raise LFD01Error(f"compiled metadata role exceeds bounded reader: {role}")
    return _read_json(path, f"compiled BUILD_004 {role}", max_bytes=max_bytes)


def _validate_build_phase_result(
    value: Any, label: str, *, timeout_required: bool, truncated_required: bool,
) -> None:
    """Validate one bounded BUILD_004 command result without inventing fields.

    The real BUILD_004 make/probe records include ``timed_out: false``.  The
    two patch-helper records are successful ``patch`` results with
    ``returncode``, ``elapsed_seconds``, ``truncated: false`` and ``command``
    but no ``timed_out`` key.  A timeout key is therefore required for the
    timed command phases, optional only for helper results, and rejected when
    present with any value other than ``false``.
    """
    if not isinstance(value, dict):
        raise LFD01Error(f"BUILD_004 {label} result is not an object")
    returncode = value.get("returncode")
    if isinstance(returncode, bool) or returncode != 0:
        raise LFD01Error(f"BUILD_004 {label} did not return zero")
    command = value.get("command")
    if (not isinstance(command, list) or not command
            or any(not isinstance(item, str) or not item for item in command)):
        raise LFD01Error(f"BUILD_004 {label} result lacks its command")
    _finite(value.get("elapsed_seconds"), f"BUILD_004 {label} elapsed_seconds")
    if truncated_required:
        if value.get("truncated") is not False:
            raise LFD01Error(f"BUILD_004 {label} result is missing truncated=false")
    elif "truncated" in value and value.get("truncated") is not False:
        raise LFD01Error(f"BUILD_004 {label} result reported truncation")
    if timeout_required:
        if value.get("timed_out") is not False:
            raise LFD01Error(f"BUILD_004 {label} did not report timed_out=false")
    elif "timed_out" in value and value.get("timed_out") is not False:
        raise LFD01Error(f"BUILD_004 {label} reported a timeout")


def _validate_compiled_build_evidence(
    request: dict[str, Any], small_hashes: Mapping[str, str],
) -> None:
    """Validate BUILD_004 provenance without reading the deferred executable."""
    _compiled_normal_artifact_bindings(request, small_hashes)
    binary = request.get("binary_binding")
    if (not isinstance(binary, dict)
            or binary.get("path") != str(COMPILED_BINARY_PATH)
            or binary.get("bytes") != COMPILED_BINARY_BYTES
            or binary.get("sha256") != COMPILED_BINARY_SHA256
            or binary.get("deferred") is not True):
        raise LFD01Error("compiled binary binding is not the exact deferred BUILD_004 target")
    command = request.get("command")
    if (not isinstance(command, list) or not command
            or Path(str(command[0])).expanduser().resolve() != COMPILED_BINARY_PATH):
        raise LFD01Error("compiled branch command[0] does not equal the exact BUILD_004 target")
    if request.get("kind") not in {"qualification", "production"}:
        raise LFD01Error("compiled binary work must remain qualification or production")
    if request.get("execution_class") != "heavy" or request.get("cpu_task_kind") != "compiled_gpu_solver":
        raise LFD01Error("compiled binary work cannot be relabeled as CPU, tests, or conversion")
    if request.get("bootstrap") is not False or request.get("gpu_required") is not True:
        raise LFD01Error("compiled binary branch requires a non-bootstrap GPU request")
    if any(str(arg).startswith("-cpu") for arg in command[1:]):
        raise LFD01Error("compiled GPU request contains a forbidden -cpu argument")
    _finite(request.get("estimated_peak_gpu_mib"), "compiled estimated_peak_gpu_mib", minimum=1e-9)

    result = _compiled_metadata(request, "build_result")
    receipt = _compiled_metadata(request, "build_receipt")
    build_request = _compiled_metadata(request, "build_request")
    build_grant = _compiled_metadata(request, "build_grant")
    m0 = _compiled_metadata(request, "m0_acceptance")
    closure = _compiled_metadata(request, "source_closure")
    review = _compiled_metadata(request, "actual_non_author_review")

    if (result.get("schema") != "lfd01.s06-build-result.v2"
            or result.get("status") != "completed"
            or result.get("phase") != "completed"
            or result.get("attempt_id") != COMPILED_BUILD_ATTEMPT
            or result.get("attempt_root") != str(COMPILED_BUILD_ROOT)):
        raise LFD01Error("BUILD_004 result is not the exact completed report")
    if result.get("request_sha256") != COMPILED_ARTIFACT_BY_ROLE["build_request"]["sha256"]:
        raise LFD01Error("BUILD_004 result request hash is not the bound request")
    if result.get("grant_sha256") != COMPILED_ARTIFACT_BY_ROLE["build_grant"]["sha256"]:
        raise LFD01Error("BUILD_004 result grant hash is not the bound grant")
    if result.get("manifest_sha256") != COMPILED_ARTIFACT_BY_ROLE["build_manifest"]["sha256"]:
        raise LFD01Error("BUILD_004 result manifest hash is not the bound manifest")
    if result.get("m0_acceptance_sha256") != COMPILED_ARTIFACT_BY_ROLE["m0_acceptance"]["sha256"]:
        raise LFD01Error("BUILD_004 result M0 hash is not the bound M0 artifact")
    binary_report = result.get("binary")
    if (not isinstance(binary_report, dict)
            or binary_report.get("path") != str(COMPILED_BINARY_PATH)
            or binary_report.get("bytes") != COMPILED_BINARY_BYTES
            or binary_report.get("sha256") != COMPILED_BINARY_SHA256):
        raise LFD01Error("BUILD_004 result does not report the exact compiled binary")
    for key in ("device", "inode", "mtime_ns", "ctime_ns"):
        if binary_report.get(key) != COMPILED_BINARY_STAT[key]:
            raise LFD01Error(f"BUILD_004 binary report has a changed {key}")
    phases = result.get("phases")
    if not isinstance(phases, dict):
        raise LFD01Error("BUILD_004 result lacks phase reports")
    for phase_name in ("device_info_compile_probe", "make"):
        phase = phases.get(phase_name)
        _validate_build_phase_result(
            phase, phase_name, timeout_required=True, truncated_required=False,
        )
    compatibility_phase = phases.get("device_info_compatibility_patch")
    if not isinstance(compatibility_phase, dict):
        raise LFD01Error("BUILD_004 result lacks the CUDA13 compatibility phase")
    compatibility_result = compatibility_phase.get("result")
    _validate_build_phase_result(
        compatibility_result, "CUDA13 compatibility patch",
        timeout_required=False, truncated_required=True,
    )
    patch_after = compatibility_phase.get("after")
    if (not isinstance(patch_after, dict)
            or patch_after.get("bytes") != 35_946
            or patch_after.get("sha256") != COMPILED_ARTIFACT_BY_ROLE["compatibility_expected_source"]["sha256"]):
        raise LFD01Error("BUILD_004 CUDA13 expected patched source is not closed")
    trace_phase = phases.get("patch")
    _validate_build_phase_result(
        trace_phase, "accepted-step patch", timeout_required=False, truncated_required=True,
    )
    source_contract = result.get("source_contract")
    if not isinstance(source_contract, dict) or source_contract.get("entry_count") != 339:
        raise LFD01Error("BUILD_004 source closure entry count is not 339")
    _require_sha(result.get("running_receipt_sha256"), "BUILD_004 running receipt sha256")
    if (closure.get("schema") != "lfd01.s06-build-closure.candidate.v1"
            or closure.get("status") != "candidate_source_closure"):
        raise LFD01Error("bound source closure is not the reviewed S06 closure")

    if (receipt.get("schema") != "ds02.execution-receipt.v1"
            or receipt.get("status") != "completed"
            or receipt.get("returncode") != 0
            or receipt.get("request_sha256") != result.get("request_sha256")
            or receipt.get("output_root") != str(COMPILED_BUILD_ROOT)):
        raise LFD01Error("BUILD_004 parent receipt is not completed and request-bound")
    receipt_request = receipt.get("request")
    if not isinstance(receipt_request, dict):
        raise LFD01Error("BUILD_004 parent receipt lacks its request projection")
    runtime = receipt.get("lfd01_runtime")
    deferred_proof = runtime.get("deferred_input_hashes") if isinstance(runtime, dict) else None
    if (not isinstance(runtime, dict)
            or runtime.get("execution_status") != "COMPLETED"
            or runtime.get("child_exit_confirmed") is not True
            or not isinstance(runtime.get("final_reap"), dict)
            or runtime["final_reap"].get("completed") is not True
            or not isinstance(deferred_proof, dict)
            or deferred_proof.get("posthash_status") != "verified"):
        raise LFD01Error("BUILD_004 parent receipt lacks completed owned reap/posthash proof")
    if (build_request.get("schema") != "lfd01.runtime-request.v1"
            or build_request.get("family_id") != "infra"
            or build_request.get("case_id") != "LFD01_S06_BUILD"
            or build_request.get("attempt_id") != "LFD01_BUILD_004"
            or build_request.get("reservation_id") != COMPILED_BUILD_ATTEMPT
            or build_request.get("request_path") is not None):
        raise LFD01Error("bound BUILD_004 request identity is invalid")
    if (build_grant.get("schema") != GRANT_SCHEMA
            or build_grant.get("status") != "granted"
            or build_grant.get("attempt_id") != COMPILED_BUILD_ATTEMPT
            or build_grant.get("request_sha256") != result.get("request_sha256")
            or build_grant.get("request_path") != COMPILED_ARTIFACT_BY_ROLE["build_request"]["path"]):
        raise LFD01Error("bound BUILD_004 grant does not match the completed request")
    for identity_key in ("family_id", "case_id", "attempt_id", "reservation_id"):
        if receipt_request.get(identity_key) != build_request.get(identity_key):
            raise LFD01Error(f"BUILD_004 receipt request differs at {identity_key}")
    if (m0.get("schema") != M0_SCHEMA or m0.get("campaign_id") != "LFD-01"
            or m0.get("status") != "accepted"):
        raise LFD01Error("bound M0 artifact is not accepted")
    if (not isinstance(review, dict)
            or not str(review.get("status", "")).startswith("accepted")
            or review.get("reviewer") in {None, "root", "controller"}
            or review.get("author") in {None, review.get("reviewer")}):
        raise LFD01Error("bound actual BUILD004 non-author review is not accepted")

    target = _regular_path(str(COMPILED_BINARY_PATH), "compiled BUILD_004 binary")
    target_stat = target.stat()
    if not stat.S_ISREG(target_stat.st_mode) or target.is_symlink():
        raise LFD01Error("compiled BUILD_004 target is not a regular non-symlink file")
    for key, actual in (("device", target_stat.st_dev), ("inode", target_stat.st_ino),
                        ("bytes", target_stat.st_size), ("mtime_ns", target_stat.st_mtime_ns),
                        ("ctime_ns", target_stat.st_ctime_ns)):
        if actual != COMPILED_BINARY_STAT[key]:
            raise LFD01Error(f"compiled BUILD_004 target stat differs for {key}")

    with _locked_parent_ledger() as ledger:
        charges = [row for row in ledger.get("charges", [])
                   if isinstance(row, dict) and row.get("id") == COMPILED_PARENT_CHARGE_ID]
        reservations = [row for row in ledger.get("reservations", [])
                        if isinstance(row, dict) and row.get("id") == COMPILED_PARENT_CHARGE_ID]
        attempts = [row for row in ledger.get("attempts", [])
                    if isinstance(row, dict) and row.get("id") == COMPILED_PARENT_CHARGE_ID]
    if len(charges) != 1 or len(reservations) != 0 or len(attempts) != 1:
        raise LFD01Error("BUILD_004 parent fee is absent, duplicated, or still reserved")
    if charges[0].get("status") != "completed" or attempts[0].get("status") != "completed":
        raise LFD01Error("BUILD_004 parent settlement is not completed")
    request["_compiled_attestation_checked"] = {
        "schema": COMPILED_ATTESTATION_SCHEMA,
        "build_attempt_id": COMPILED_BUILD_ATTEMPT,
        "binary_path": str(COMPILED_BINARY_PATH),
        "binary_bytes": COMPILED_BINARY_BYTES,
        "binary_sha256": COMPILED_BINARY_SHA256,
        "parent_charge_id": COMPILED_PARENT_CHARGE_ID,
        "parent_charge_count": 1,
        "parent_reservation_count": 0,
        "binary_stat_verified": True,
        "deferred_hash_scope": ["owned_launch", "after_owned_reap"],
    }


def _is_compiled_binary_request(request: Mapping[str, Any]) -> bool:
    branch = request.get("solver_branch")
    if branch is None:
        return False
    if branch != COMPILED_SOLVER_BRANCH:
        raise LFD01Error("unknown solver branch; official v12 branch is the only default")
    return True


def _parse_cpu_list(value: str, label: str) -> set[int]:
    """Parse a Linux CPU-list file without consulting process affinity."""
    result: set[int] = set()
    text = value.strip()
    if not text:
        raise LFD01Error(f"{label} is empty")
    for token in text.split(","):
        token = token.strip()
        if not token:
            raise LFD01Error(f"{label} contains an empty CPU range")
        if "-" in token:
            pieces = token.split("-")
            if len(pieces) != 2 or any(not piece.isdigit() for piece in pieces):
                raise LFD01Error(f"{label} contains an invalid range: {token}")
            first, last = (int(piece) for piece in pieces)
            if last < first or last - first > 1_000_000:
                raise LFD01Error(f"{label} contains an invalid range: {token}")
            result.update(range(first, last + 1))
        elif token.isdigit():
            result.add(int(token))
        else:
            raise LFD01Error(f"{label} contains an invalid CPU: {token}")
    if not result:
        raise LFD01Error(f"{label} has no CPUs")
    return result


def _cgroup_effective_cpu_file() -> Path:
    """Resolve this process's cpuset file from /proc/self/cgroup."""
    cgroup_file = Path("/proc/self/cgroup")
    try:
        lines = [line.strip() for line in cgroup_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError as error:
        raise LFD01Error(f"cannot read {cgroup_file}: {error}") from error
    v2 = next((line for line in lines if line.startswith("0::")), None)
    if v2 is not None:
        relative = v2.split("::", 1)[1].strip()
        if not relative.startswith("/"):
            raise LFD01Error("cgroup v2 path is malformed")
        mount = Path("/sys/fs/cgroup").resolve()
        target = (mount / relative.lstrip("/")).resolve()
        if target != mount and not target.is_relative_to(mount):
            raise LFD01Error("cgroup v2 path escapes the canonical mount")
        # A cgroup may inherit cpuset from an ancestor without exposing a
        # cpuset file in the leaf (the usual systemd layout).  Walk only this
        # validated cgroup path back to the mount root; never broaden to an
        # unrelated cgroup.
        candidates = []
        cursor = target
        while True:
            candidates.extend((cursor / "cpuset.cpus.effective", cursor / "cpuset.cpus"))
            if cursor == mount:
                break
            cursor = cursor.parent
    else:
        cpuset = None
        for line in lines:
            parts = line.split(":", 2)
            if len(parts) == 3 and "cpuset" in parts[1].split(","):
                cpuset = parts[2].strip()
                break
        if cpuset is None or not cpuset.startswith("/"):
            raise LFD01Error("/proc/self/cgroup has no verifiable cpuset controller")
        mount = Path("/sys/fs/cgroup/cpuset").resolve()
        target = (mount / cpuset.lstrip("/")).resolve()
        if target != mount and not target.is_relative_to(mount):
            raise LFD01Error("cgroup v1 cpuset path escapes the canonical mount")
        candidates = []
        cursor = target
        while True:
            candidates.extend((cursor / "cpuset.cpus.effective", cursor / "cpuset.cpus"))
            if cursor == mount:
                break
            cursor = cursor.parent
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise LFD01Error("no readable effective cpuset file for this process")


def _available_cpus() -> set[int]:
    """Return online CPUs intersected with this cgroup's effective cpuset.

    This deliberately does not use sched_getaffinity(0): the controller or a
    worker may already be pinned to one request's cpuset while global admission
    still needs the real host/container capacity for another request.
    """
    online_file = Path("/sys/devices/system/cpu/online")
    try:
        online = _parse_cpu_list(online_file.read_text(encoding="utf-8"), str(online_file))
        effective_file = _cgroup_effective_cpu_file()
        effective = _parse_cpu_list(effective_file.read_text(encoding="utf-8"), str(effective_file))
    except OSError as error:
        raise LFD01Error(f"cannot read online/effective CPU set: {error}") from error
    available = online & effective
    if not available:
        raise LFD01Error("online CPU set and cgroup effective cpuset do not intersect")
    return available


def _validate_limits(request: Mapping[str, Any]) -> None:
    execution_class = request.get("execution_class")
    if execution_class not in {"heavy", "light"}:
        raise LFD01Error("execution_class must be heavy or light")
    _finite(request.get("max_wall_seconds"), "max_wall_seconds", minimum=1e-9)
    _finite(request.get("cpu_threads"), "cpu_threads", minimum=1, integer=True)
    _finite(request.get("estimated_storage_bytes"), "estimated_storage_bytes", minimum=1, integer=True)
    _finite(request.get("nas_peak_bytes"), "nas_peak_bytes", minimum=1, integer=True)
    _finite(request.get("ram_limit_bytes"), "ram_limit_bytes", minimum=1, integer=True)
    if request.get("output_storage") != "lfd01_nas":
        raise LFD01Error("LFD-01 requests cannot fall back to Home output")
    cpus = request.get("affinity_cpus")
    if not isinstance(cpus, list) or not cpus or any(isinstance(v, bool) or not isinstance(v, int) for v in cpus):
        raise LFD01Error("affinity_cpus must be an explicit integer list")
    if len(cpus) != len(set(cpus)) or not set(cpus).issubset(_available_cpus()):
        raise LFD01Error("affinity_cpus is unavailable or duplicated")
    if len(cpus) != int(request["cpu_threads"]):
        raise LFD01Error("affinity_cpus must contain exactly cpu_threads logical CPUs")
    if request["estimated_storage_bytes"] > FSIZE_GLOBAL_HARD or request["nas_peak_bytes"] > NAS_ACTIVE_PEAK_MAX:
        raise LFD01Error("NAS output/peak exceeds the LFD-01 256 GiB active bound")
    if request["estimated_storage_bytes"] > request["nas_peak_bytes"]:
        raise LFD01Error("estimated output exceeds declared NAS peak")
    if execution_class == "light":
        if request.get("kind") != "cpu" or request.get("cpu_task_kind") not in {"audit", "labels", "evaluator", "preview", "tests"}:
            raise LFD01Error("light jobs must use a bounded CPU metadata task kind")
        if (request["cpu_threads"] > LIGHT_MAX_THREADS or len(cpus) > LIGHT_MAX_THREADS or
                request["ram_limit_bytes"] > LIGHT_MAX_RAM):
            raise LFD01Error("light CPU/RAM limit exceeded")
        if request["max_wall_seconds"] > LIGHT_MAX_WALL:
            raise LFD01Error("light wall limit exceeded")
        if request["estimated_storage_bytes"] > LIGHT_MAX_OUTPUT:
            raise LFD01Error("light output limit exceeded")
    else:
        if request["ram_limit_bytes"] not in HEAVY_RAM_TIERS:
            raise LFD01Error("heavy RAM must use the 64/128/256 GiB tier")
        if request["cpu_threads"] > len(_available_cpus()):
            raise LFD01Error("heavy CPU threads exceed available cpuset")
    if request["kind"] not in {"cpu", "qualification", "production"}:
        raise LFD01Error("invalid legacy request kind")
    if execution_class == "heavy" and request["kind"] == "cpu" and request.get("cpu_task_kind") not in {"conversion", "gencase", "audit", "labels", "evaluator", "preview", "tests"}:
        raise LFD01Error("heavy CPU kind is outside the legacy allowlist")


def _validate_light_inputs(request: Mapping[str, Any]) -> None:
    """Bind every sealed light input to a small, normal source declaration."""
    inputs = request.get("light_inputs")
    bindings = request.get("source_bindings")
    input_files = request.get("input_files")
    if not isinstance(inputs, list) or not inputs:
        raise LFD01Error("light_inputs are required")
    if not isinstance(bindings, list) or not isinstance(input_files, list):
        raise LFD01Error("light source declarations are malformed")
    by_path: dict[str, Mapping[str, Any]] = {}
    for item in bindings:
        if isinstance(item, dict):
            path = _regular_path(item.get("path"), "light source binding path")
            by_path[str(path)] = item
    declared_inputs = {str(_regular_path(path, "light input file")) for path in input_files}
    seen_sandbox: set[str] = set()
    total = 0
    for item in inputs:
        if not isinstance(item, dict):
            raise LFD01Error("light input binding must be an object")
        host = _regular_path(item.get("path"), "light input")
        sandbox = item.get("sandbox_path")
        parts = PurePosixPath(sandbox).parts if isinstance(sandbox, str) else ()
        suffix = host.suffix.lower()
        if (not isinstance(sandbox, str) or parts[:2] != ("/", "input") or
                any(part in {"", ".", ".."} for part in parts[2:]) or
                sandbox in seen_sandbox or sandbox == "/input/request.json"):
            raise LFD01Error("light input sandbox path is unsafe or duplicated")
        if suffix in LIGHT_NATIVE_SUFFIXES:
            raise LFD01Error(f"native/binary input is forbidden for sealed light work: {host}")
        if suffix not in {".json", ".csv", ".txt", ".tsv", ".xml"}:
            raise LFD01Error(f"light input suffix is not an admitted small metadata format: {host}")
        seen_sandbox.add(sandbox)
        if str(host) not in declared_inputs:
            raise LFD01Error("light input must also be declared in input_files")
        binding = by_path.get(str(host))
        if binding is None or binding.get("deferred") is True:
            raise LFD01Error("light input must have a non-deferred source binding")
        size = host.stat().st_size
        total += size
    if total > LIGHT_MAX_INPUT:
        raise LFD01Error("light declared input bytes exceed 64 MiB")


def _light_command(request: Mapping[str, Any], request_path: Path) -> list[str]:
    light = request.get("light_operation")
    if light not in {"json_collection_counts", "csv_summary"}:
        raise LFD01Error("unsupported sealed light operation")
    inputs = request.get("light_inputs")
    if not isinstance(inputs, list) or not inputs:
        raise LFD01Error("light_inputs are required")
    source = _regular_path(request.get("light_executor_path", str(SCRIPT_PATH)), "light executor")
    if source != SCRIPT_PATH:
        raise LFD01Error("light executor must be this sealed candidate source")
    bwrap = _regular_path("/usr/bin/bwrap", "bwrap executable")
    interpreter = _regular_path("/usr/bin/python3.10", "sealed light interpreter")
    command = [str(bwrap), "--die-with-parent", "--unshare-all", "--new-session", "--clearenv"]
    # Bind only canonical, non-symlink system roots.  On this host /bin,
    # /lib, and /lib64 are symlinks into /usr; mounting those lexical paths
    # would make the sandbox depend on bwrap's symlink traversal semantics.
    system_root = _regular_directory("/usr", "sealed light system root")
    command += ["--ro-bind", str(system_root), str(system_root)]
    # The dynamic loader is addressed through the conventional /lib and
    # /lib64 paths even when their host entries are symlinks into /usr.  Mount
    # the resolved regular directories at those exact sandbox destinations so
    # execve can resolve the registered interpreter without exposing any
    # additional host/data tree.
    for lexical in (Path("/lib"), Path("/lib64")):
        if not lexical.exists():
            raise LFD01Error(f"sealed light loader directory is missing: {lexical}")
        resolved = lexical.resolve()
        loader_root = _regular_directory(resolved, f"sealed light loader root {lexical}")
        command += ["--dir", str(lexical), "--ro-bind", str(loader_root), str(lexical)]
    command += ["--dir", "/opt", "--dir", "/opt/lfd01", "--dir", "/input", "--dir", "/out"]
    command += ["--ro-bind", str(SCRIPT_PATH), "/opt/lfd01/lfd01_forward_runtime.py"]
    command += ["--ro-bind", str(request_path), "/input/request.json"]
    seen: set[str] = set()
    for item in sorted(inputs, key=lambda value: str(value.get("sandbox_path", "")) if isinstance(value, dict) else ""):
        if not isinstance(item, dict):
            raise LFD01Error("light input binding must be an object")
        host = _regular_path(item.get("path"), "light input")
        sandbox = item.get("sandbox_path")
        parts = PurePosixPath(sandbox).parts if isinstance(sandbox, str) else ()
        if (not isinstance(sandbox, str) or parts[:2] != ("/", "input") or
                any(part in {"", ".", ".."} for part in parts[2:]) or sandbox in seen or sandbox == "/input/request.json"):
            raise LFD01Error("light input sandbox path is unsafe or duplicated")
        if Path(str(host)).suffix.lower() in LIGHT_NATIVE_SUFFIXES:
            raise LFD01Error("native/binary input cannot be mounted into a light sandbox")
        seen.add(sandbox)
        command += ["--ro-bind", str(host), sandbox]
    command += ["--bind", "{attempt_root}", "/out", "--tmpfs", "/tmp", "--chdir", "/out",
                "--setenv", "PYTHONNOUSERSITE", "1", "--setenv", "HOME", "/tmp",
                "--setenv", "PATH", "/usr/bin:/bin", str(interpreter),
                "/opt/lfd01/lfd01_forward_runtime.py", "light-worker",
                "--request", "/input/request.json", "--output", "/out/light-result.json"]
    return command


def _validate_light_command(request: Mapping[str, Any], request_path: Path) -> None:
    if request.get("command") != _light_command(request, request_path):
        raise LFD01Error("light command differs from the sealed bwrap operation")


def _validate_request_grant(request_path: Path, grant_path: Path, *, actual_job_id: str | None = None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    request = _read_json(request_path, "LFD-01 request")
    grant = _read_json(grant_path, "LFD-01 request grant")
    adoption, baseline, adoption_sha, baseline_sha = _authority()
    if grant.get("schema") != GRANT_SCHEMA or grant.get("status") != "granted" or grant.get("issuer") != "root" or grant.get("immutable") is not True:
        raise LFD01Error("request grant is not an immutable root grant")
    if _sha256_json_payload(grant, "payload_sha256") != _require_sha(grant.get("payload_sha256"), "grant payload_sha256"):
        raise LFD01Error("request grant payload hash mismatch")
    if grant.get("namespace") != NAMESPACE:
        raise LFD01Error("grant namespace is not LFD01_")
    if grant.get("adoption_sha256") != adoption_sha or grant.get("baseline_sha256") != baseline_sha:
        raise LFD01Error("grant does not bind the current adoption and baseline")
    if grant.get("parent_ledger_path") != str(PARENT_DATA_ROOT / "runtime/resource-ledger.json"):
        raise LFD01Error("grant parent ledger path is not canonical")
    expected_request = _regular_path(grant.get("request_path"), "grant request path")
    if expected_request != request_path:
        raise LFD01Error("grant request path differs from the dispatched request")
    if _sha256(request_path) != _require_sha(grant.get("request_sha256"), "grant request_sha256"):
        raise LFD01Error("request changed after root grant")
    _safe_id(request.get("family_id"), "family_id")
    _safe_id(request.get("case_id"), "case_id")
    _safe_id(request.get("attempt_id"), "attempt_id")
    if not request["case_id"].startswith(NAMESPACE) or not request["attempt_id"].startswith(NAMESPACE):
        raise LFD01Error("new request identities must use the LFD01_ namespace")
    if request.get("namespace") != NAMESPACE or _attempt_id(request) != grant.get("attempt_id"):
        raise LFD01Error("request identity differs from grant")
    if grant.get("execution_class") != request.get("execution_class"):
        raise LFD01Error("grant execution class differs from request")
    cwd = _regular_directory(request.get("cwd"), "request cwd")
    if not _allowed_source(cwd / "placeholder"):
        raise LFD01Error("request cwd is outside the registered source/data roots")
    command = request.get("command")
    if (not isinstance(command, list) or not command or
            any(not isinstance(item, str) or not item for item in command)):
        raise LFD01Error("command must be a non-empty argv list of non-empty strings")
    _validate_limits(request)
    m0_state = _validate_m0_scope(request, grant)
    _runtime_roots(request)
    small_hashes = _validate_sources(request)
    notify_binding: dict[str, Any] | None = None
    if request.get("bootstrap") is True:
        probe_positions = [index for index, arg in enumerate(command)
                           if isinstance(arg, str) and Path(arg).name == BOOTSTRAP_PROBE_PATH.name]
        if len(probe_positions) == 1:
            notify_binding = _notify_root_command(command, probe_positions[0], request)
            if notify_binding is not None:
                helper_key = str(notify_binding["helper"])
                if helper_key not in small_hashes:
                    raise LFD01Error("notify-root helper must be a normal full-hashed input")
                if actual_job_id is not None and notify_binding["job_id"] != actual_job_id:
                    raise LFD01Error("notify-root job_id differs from the actual dispatcher job_id")
    if request.get("bootstrap") is True and str(BOOTSTRAP_PROBE_PATH) not in small_hashes:
        raise LFD01Error("bootstrap request must bind the sealed probe as a normal input")
    if grant.get("source_bindings_sha256") != _source_projection(request):
        raise LFD01Error("grant source whitelist differs from request")
    binary = request.get("binary_binding")
    if not isinstance(binary, dict):
        raise LFD01Error("binary_binding is required")
    binary_lexical, binary_path = _binary_path(binary.get("path"), "binary binding path")
    command_lexical = Path(command[0]).expanduser()
    if binary_path != command_lexical.resolve():
        raise LFD01Error("binary binding does not match command executable")
    binary_sha = _require_sha(binary.get("sha256"), "binary binding sha256")
    if not _allowed_source(binary_path):
        raise LFD01Error("command executable is outside the source whitelist")
    source_binding = None
    for item in request.get("source_bindings", []):
        if isinstance(item, dict):
            candidate_path, _launcher = _source_path(item.get("path"), "source binding path")
            if candidate_path == binary_path:
                source_binding = item
                break
    if source_binding is None:
        raise LFD01Error("binary executable lacks an exact source binding")
    if source_binding.get("sha256") != binary_sha:
        raise LFD01Error("binary binding differs from its source binding")
    compiled_branch = _is_compiled_binary_request(request)
    if not compiled_branch and request.get("compiled_binary_attestation") is not None:
        raise LFD01Error("compiled binary attestation is valid only with the explicit v14 branch")
    if compiled_branch:
        if (source_binding.get("role") != "compiled_binary_artifact"
                or source_binding.get("deferred") is not True
                or source_binding.get("bytes") != COMPILED_BINARY_BYTES):
            raise LFD01Error("compiled executable binding must be the deferred exact BUILD_004 artifact row")
        _validate_compiled_build_evidence(request, small_hashes)
    if not source_binding.get("deferred") and _sha256(binary_path) != binary_sha:
        raise LFD01Error("binary executable hash mismatch")
    if request.get("execution_class") == "light":
        _validate_light_inputs(request)
        _validate_light_command(request, request_path)
        required_sandbox_sources = {_regular_path("/usr/bin/bwrap", "bwrap executable"),
                                    _regular_path("/usr/bin/python3.10", "sealed light interpreter")}
        bound_paths = set()
        for item in request.get("source_bindings", []):
            if isinstance(item, dict):
                bound, _launcher = _source_path(item.get("path"), "light source binding path")
                bound_paths.add(bound)
        if not required_sandbox_sources.issubset(bound_paths):
            raise LFD01Error("sealed light command lacks exact bwrap/interpreter source bindings")
        for required in required_sandbox_sources:
            binding = next((item for item in request.get("source_bindings", [])
                            if isinstance(item, dict)
                            and _source_path(item.get("path"), "light source binding path")[0] == required), None)
            if binding is None or binding.get("deferred") is True:
                raise LFD01Error("sealed light executable bindings must be normal full-hashed sources")
            expected = _require_sha(binding.get("sha256"), f"sealed light source sha256 {required}")
            if _sha256(required) != expected:
                raise LFD01Error(f"sealed light source hash mismatch: {required}")
    _validate_g2(request)
    with _locked_parent_ledger() as ledger:
        _verify_history(ledger, adoption, baseline)
        _validate_grant_policy(request, grant, adoption, ledger)
    # Hashes are returned only for provenance; deferred sources have been
    # stat-checked but deliberately not opened before the reservation.
    request["_small_hashes_preflight"] = {key: value for key, value in small_hashes.items() if key != "__deferred__"}
    request["_m0_state"] = m0_state
    if notify_binding is not None:
        request["_notify_root_binding"] = {
            "helper": str(notify_binding["helper"]),
            "job_id": notify_binding["job_id"],
            "event_id": notify_binding["event_id"],
            "receipt": str(notify_binding["receipt"]),
            "helper_sha256": small_hashes[str(notify_binding["helper"])],
            "one_shot": True,
            "failure_policy": "unknown_no_retry",
        }
    return request, grant, adoption, baseline


def _home_free_bytes() -> int:
    stat = os.statvfs(HOME_ROOT)
    return int(stat.f_bavail * stat.f_frsize)


def _nas_free_bytes() -> int:
    if not Path("/data/nas").is_mount():
        raise LFD01Error("/data/nas is not mounted")
    if NAS_ROOT.stat().st_dev == HOME_ROOT.stat().st_dev:
        raise LFD01Error("LFD-01 NAS is not a distinct filesystem")
    stat = os.statvfs(NAS_ROOT)
    return int(stat.f_bavail * stat.f_frsize)


def _assert_parent_data_root() -> None:
    if not Path("/data/nas").is_mount():
        raise LFD01Error("/data/nas is not mounted")
    try:
        if PARENT_DATA_ROOT.stat().st_dev == HOME_ROOT.stat().st_dev:
            raise LFD01Error("parent data root is on the Home filesystem")
    except OSError as error:
        raise LFD01Error(f"parent data root is unavailable: {error}") from error


def _assert_nas_path(path: str | Path) -> None:
    _nas_free_bytes()
    target = Path(path).expanduser().resolve()
    if target != NAS_ROOT and not target.is_relative_to(NAS_ROOT):
        raise LFD01Error(f"path escapes LFD-01 NAS root: {target}")
    probe = target if target.exists() else target.parent
    if probe.exists() and probe.stat().st_dev != NAS_ROOT.stat().st_dev:
        raise LFD01Error("LFD-01 NAS device changed")


def _row_storage_bytes(row: Mapping[str, Any]) -> int:
    value = row.get("new_storage_bytes", 0)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise LFD01Error("ledger storage value is invalid")
    return int(value)


def _row_is_nas_backed(row: Mapping[str, Any]) -> bool:
    ident = str(row.get("id", "")).split("/")
    historical_upstream_id = len(ident) == 3 and ident[1].startswith("UF_")
    return (row.get("output_storage") in {"lfd01_nas", "upstream_nas"} or
            row.get("lfd01_storage_scope") == "nas" or historical_upstream_id)


def _lfd_rows(ledger: Mapping[str, Any], *, reservations_only: bool = False,
              pool: str | None = None, tranche: str | None = None,
              exclude_id: str | None = None) -> list[Mapping[str, Any]]:
    values: list[Mapping[str, Any]] = []
    collections = (ledger.get("reservations", []),) if reservations_only else (ledger.get("charges", []), ledger.get("reservations", []))
    for collection in collections:
        for row in collection:
            if (isinstance(row, Mapping) and _is_lfd_record(row)
                    and (exclude_id is None or row.get("id") != exclude_id)
                    and (pool is None or row.get("pool") == pool)
                    and (tranche is None or row.get("tranche_id") == tranche)):
                values.append(row)
    return values


def _solver_attempt_increment(value: Mapping[str, Any]) -> float:
    """Count only legacy qualification/production solver attempts.

    ``kind='cpu'`` covers bounded CPU/bootstrap metadata work and must not
    acquire a solver-attempt unit merely because it consumes CPU seconds.
    The same predicate is used for historical registered rows and the
    pending request so CPU and solver caps cannot drift apart.
    """
    return 1.0 if value.get("kind") in {"qualification", "production"} else 0.0


def _lfd_usage(ledger: Mapping[str, Any], *, pool: str | None = None,
               tranche: str | None = None, exclude_id: str | None = None) -> dict[str, float]:
    rows = _lfd_rows(ledger, pool=pool, tranche=tranche, exclude_id=exclude_id)
    attempts = [row for row in ledger.get("attempts", [])
                if isinstance(row, dict) and _is_lfd_record(row)
                and (exclude_id is None or row.get("id") != exclude_id)
                and (pool is None or row.get("pool") == pool)
                and (tranche is None or row.get("tranche_id") == tranche)]
    return {
        "gpu_seconds": sum(float(row.get("gpu_seconds", 0) or 0) for row in rows),
        "cpu_core_seconds": sum(float(row.get("cpu_core_seconds", 0) or 0) for row in rows),
        "new_storage_bytes": sum(float(row.get("new_storage_bytes", 0) or 0) for row in rows),
        # Attempt registrations are authoritative, including failed and
        # recovered attempts.  Charges/reservations intentionally carry no
        # Solver attempts come from registered attempt rows, rather than
        # charge rows (legacy charges may omit ``kind``).  CPU/tests/light and
        # the bootstrap settlement remain part of ``registered_attempts`` but
        # do not consume the solver-attempt budget.
        "solver_attempts": sum(_solver_attempt_increment(row) for row in attempts),
        "registered_attempts": float(len(attempts)),
    }


def _active_class(row: Mapping[str, Any]) -> str:
    if row.get("namespace") == NAMESPACE or row.get("lfd01_namespace") == NAMESPACE:
        value = row.get("lfd01_class")
        if value in {"heavy", "light"}:
            return value
    if row.get("kind") in {"qualification", "production"} or row.get("cpu_task_kind") == "conversion":
        return "heavy"
    return "unknown"


def _project_legacy_storage(ledger: Mapping[str, Any], reservation: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    projected = deepcopy(dict(ledger))
    for collection in (projected.get("reservations", []),):
        for row in collection:
            if _row_is_nas_backed(row):
                row["new_storage_bytes"] = 0
    projected_reservation = dict(reservation)
    if projected_reservation.get("output_storage") == "lfd01_nas":
        projected_reservation["new_storage_bytes"] = 0
    return projected, projected_reservation


def _policy_binding() -> tuple[dict[str, Any], str]:
    policy = _read_json(POLICY_PATH, "adopted campaign policy", max_bytes=SMALL_METADATA_MAX)
    if policy.get("schema") != POLICY_SCHEMA or policy.get("campaign_id") != "LFD-01":
        raise LFD01Error("adopted campaign policy binding is invalid")
    return policy, _sha256(POLICY_PATH)


def _grant_allocation(grant: Mapping[str, Any]) -> dict[str, float]:
    allocation = grant.get("allocation")
    if not isinstance(allocation, dict):
        raise LFD01Error("grant must carry an immutable allocation")
    result: dict[str, float] = {}
    for key in ("gpu_seconds", "cpu_core_seconds", "new_storage_bytes", "solver_attempts"):
        value = allocation.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) < 0:
            raise LFD01Error(f"grant allocation is invalid: {key}")
        result[key] = float(value)
    return result


def _validate_grant_policy(request: Mapping[str, Any], grant: Mapping[str, Any], adoption: Mapping[str, Any],
                           ledger: Mapping[str, Any], *, exclude_attempt_id: str | None = None) -> None:
    """Bind each request to a non-resetting work/tranche/central allocation."""
    policy, policy_sha = _policy_binding()
    if grant.get("policy_sha256") != policy_sha:
        raise LFD01Error("grant does not bind the adopted campaign policy")
    pool = grant.get("pool")
    if pool not in {"work", "central"}:
        raise LFD01Error("grant pool must be work or central")
    tranche = grant.get("tranche_id")
    stage = grant.get("stage")
    if not isinstance(tranche, str) or not tranche or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in tranche):
        raise LFD01Error("grant tranche_id is unsafe or missing")
    if not isinstance(stage, str) or not stage:
        raise LFD01Error("grant stage is missing")
    allocation = _grant_allocation(grant)
    pool_caps = adoption.get("work_pool" if pool == "work" else "central_reserve")
    if not isinstance(pool_caps, dict):
        raise LFD01Error(f"adoption has no {pool} pool")
    for key, value in allocation.items():
        cap = float(pool_caps.get(key, 0) or 0)
        if value > cap:
            raise LFD01Error(f"grant allocation exceeds adopted {pool} pool: {key}")
    if pool == "central":
        purpose = grant.get("purpose") or request.get("central_purpose")
        if purpose not in CENTRAL_PURPOSES:
            raise LFD01Error("central reserve is restricted to repair/holdout/replay/closeout")
        if request.get("central_purpose") not in {None, purpose}:
            raise LFD01Error("request central purpose differs from immutable grant")
        evidence = grant.get("central_evidence")
        path, _sha, _ = _artifact_binding(evidence, "central allocation evidence")
        evidence_value = _read_json(path, "central allocation evidence", max_bytes=SMALL_METADATA_MAX)
        if evidence_value.get("status") != "accepted" or evidence_value.get("campaign_id") != "LFD-01":
            raise LFD01Error("central allocation evidence is not accepted")
    if request.get("kind") == "production":
        holdout = grant.get("holdout_protection")
        if not isinstance(holdout, dict) or holdout.get("status") != "protected":
            raise LFD01Error("production requires active holdout protection")
        if int(holdout.get("protected_attempts_min", 0) or 0) < 12 or int(holdout.get("horizon_attempts", 0) or 0) < 26:
            raise LFD01Error("production holdout protection must cover at least 12 attempts in a 26-attempt horizon")
        remaining = holdout.get("remaining_attempts")
        required_remaining = holdout.get("required_remaining_attempts")
        consumed = holdout.get("actual_consumed_attempts")
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0
               for value in (remaining, required_remaining, consumed)):
            raise LFD01Error("production holdout protection must expose non-negative actual remaining/consumed counts")
        if remaining < required_remaining or required_remaining < 12:
            raise LFD01Error("production holdout remaining resource is below the actual protected gap")
        evidence_path, _evidence_sha, _ = _artifact_binding(holdout.get("evidence"), "holdout protection evidence")
        evidence_value = _read_json(evidence_path, "holdout protection evidence", max_bytes=SMALL_METADATA_MAX)
        if (evidence_value.get("status") != "accepted" or evidence_value.get("campaign_id") != "LFD-01"
                or evidence_value.get("actual_consumed_attempts") != consumed
                or evidence_value.get("remaining_attempts") != remaining
                or evidence_value.get("required_remaining_attempts") != required_remaining):
            raise LFD01Error("holdout protection evidence does not bind actual consumed and remaining attempts")
    # Keep three cumulative scopes separate.  Campaign totals never reset when
    # a tranche changes; pool totals do not let central usage consume work
    # capacity (or the reverse); a tranche compares only with its own frozen
    # allocation.  ``exclude_attempt_id`` is used only by terminal rechecks,
    # where the current reservation is already present in the ledger.
    usage = _lfd_usage(ledger, exclude_id=exclude_attempt_id)
    pool_usage = _lfd_usage(ledger, pool=pool, exclude_id=exclude_attempt_id)
    tranche_usage = _lfd_usage(ledger, pool=pool, tranche=tranche, exclude_id=exclude_attempt_id)
    request_cost = {
        "gpu_seconds": float(request.get("max_wall_seconds", 0) or 0) if request.get("kind") in {"qualification", "production"} else 0.0,
        "cpu_core_seconds": float(request.get("cpu_threads", 0) or 0) * float(request.get("max_wall_seconds", 0) or 0),
        "new_storage_bytes": float(request.get("estimated_storage_bytes", 0) or 0),
    }
    request_cost["solver_attempts"] = _solver_attempt_increment(request)
    effective_caps = adoption.get("effective_caps", {})
    pool_caps = adoption.get("work_pool" if pool == "work" else "central_reserve", {})
    for key in ("gpu_seconds", "cpu_core_seconds", "new_storage_bytes", "solver_attempts"):
        if usage[key] + request_cost[key] > float(effective_caps.get(key, 0) or 0):
            raise LFD01Error(f"cumulative LFD-01 campaign cap exceeded: {key}")
        if pool_usage[key] + request_cost[key] > float(pool_caps.get(key, 0) or 0):
            raise LFD01Error(f"cumulative LFD-01 {pool} pool cap exceeded: {key}")
        if tranche_usage[key] + request_cost[key] > allocation[key]:
            raise LFD01Error(f"cumulative LFD-01 tranche allocation exceeded: {key}")


def _available_memory_bytes() -> int:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    try:
        return int(os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE"))
    except (AttributeError, OSError, ValueError):
        return 0


def _lfd_check_reservation(
    ledger: dict[str, Any], reservation: dict[str, Any], existing_bytes: int, *,
    request: Mapping[str, Any], grant: Mapping[str, Any], legacy_check,
    expected_adoption_sha256: str | None = None,
    expected_baseline_sha256: str | None = None,
) -> None:
    # v6 invokes this callback while holding the real parent ledger lock.  A
    # second authority read here closes the interval between dispatch
    # validation and reservation admission; it does not acquire the ledger
    # lock recursively.
    _assert_parent_data_root()
    adoption, baseline, adoption_sha256, baseline_sha256 = _authority()
    if (expected_adoption_sha256 is not None and adoption_sha256 != expected_adoption_sha256):
        raise LFD01Error("adoption changed before the locked reservation")
    if (expected_baseline_sha256 is not None and baseline_sha256 != expected_baseline_sha256):
        raise LFD01Error("baseline changed before the locked reservation")
    _verify_history(ledger, adoption, baseline)
    _validate_grant_policy(request, grant, adoption, ledger)
    reservation.update({
        "namespace": NAMESPACE,
        "lfd01_namespace": NAMESPACE,
        "lfd01_class": request["execution_class"],
        "lfd01_ram_limit_bytes": int(request["ram_limit_bytes"]),
        "lfd01_nas_peak_bytes": int(request["nas_peak_bytes"]),
        "lfd01_affinity_cpus": list(request["affinity_cpus"]),
        "lfd01_max_wall_seconds": float(request["max_wall_seconds"]),
        "lfd01_storage_scope": "nas",
        "lfd01_status": "reserved",
        "output_storage": "lfd01_nas",
        "campaign_id": "LFD-01",
        "pool": grant.get("pool"),
        "tranche_id": grant.get("tranche_id"),
        "stage": grant.get("stage"),
        "purpose": grant.get("purpose") or request.get("central_purpose"),
    })
    # Keep the actual v2 check for deadline, parent GPU/CPU budgets, parent
    # attempt caps, duplicate ids, and its other fixed checks.  Only its Home
    # storage input is projected: LFD-01 bytes are guarded separately below.
    projected, projected_reservation = _project_legacy_storage(ledger, reservation)
    legacy_check(
        projected,
        projected_reservation,
        0,
        current_time=datetime.now(timezone.utc),
        available_bytes=_home_free_bytes(),
    )
    if _home_free_bytes() < HOME_MIN_FREE:
        raise LFD01Error("Home free-space floor is below 500 GiB")
    nas_free = _nas_free_bytes()
    if nas_free < NAS_MIN_FREE:
        raise LFD01Error("NAS free-space floor is below 2 TiB")
    active = list(ledger.get("reservations", []))
    foreign = [row for row in active if not _is_lfd_attempt(row.get("id")) and _active_class(row) == "unknown"]
    if foreign:
        raise LFD01Error("unclassified foreign active reservation blocks LFD-01 admission")
    active_heavy = sum(_active_class(row) == "heavy" for row in active)
    active_light = sum(_active_class(row) == "light" for row in active)
    if request["execution_class"] == "heavy" and active_heavy:
        raise LFD01Error("global heavy slot is occupied")
    if request["execution_class"] == "light" and active_light >= LIGHT_MAX_JOBS:
        raise LFD01Error("light queue has four active jobs")
    light_threads = sum(int(row.get("cpu_threads", 0)) for row in active if _active_class(row) == "light")
    if request["execution_class"] == "light" and light_threads + int(request["cpu_threads"]) > LIGHT_MAX_COMBINED_THREADS:
        raise LFD01Error("combined light CPU thread limit exceeded")
    for row in active:
        row_class = _active_class(row)
        if row_class in {"heavy", "light"} and (
                "lfd01_ram_limit_bytes" not in row or "lfd01_nas_peak_bytes" not in row):
            raise LFD01Error("active heavy/light reservation lacks LFD-01 RAM/NAS peak metadata")
    active_ram = sum(int(row.get("lfd01_ram_limit_bytes", 0) or 0) for row in active if _active_class(row) in {"heavy", "light"})
    active_peak = sum(int(row.get("lfd01_nas_peak_bytes", 0) or 0) for row in active if _active_class(row) in {"heavy", "light"})
    active_cpu_threads = sum(int(row.get("cpu_threads", 0) or 0) for row in active if _active_class(row) in {"heavy", "light"})
    if active_cpu_threads + int(request["cpu_threads"]) > len(_available_cpus()):
        raise LFD01Error("global active CPU thread budget exceeded")
    if active_ram + int(request["ram_limit_bytes"]) > NAS_ACTIVE_PEAK_MAX:
        raise LFD01Error("global active RAM bound exceeded")
    if _available_memory_bytes() < active_ram + int(request["ram_limit_bytes"]):
        raise LFD01Error("actual MemAvailable is below active plus requested RAM")
    if active_peak + int(request["nas_peak_bytes"]) > NAS_ACTIVE_PEAK_MAX:
        raise LFD01Error("global active NAS peak bound exceeded")
    limits = adoption.get("effective_caps", {})
    usage = _lfd_usage(ledger)
    cap_map = {
        "gpu_seconds": float(limits.get("gpu_seconds", 0)),
        "cpu_core_seconds": float(limits.get("cpu_core_seconds", 0)),
        "new_storage_bytes": float(limits.get("new_storage_bytes", 0)),
    }
    for key in cap_map:
        if usage[key] + float(reservation.get(key, 0)) > cap_map[key]:
            raise LFD01Error(f"LFD-01 cumulative cap exceeded: {key}")
    solver_cap = int(limits.get("solver_attempts", 0))
    solver_increment = _solver_attempt_increment(request)
    if usage["solver_attempts"] + solver_increment > solver_cap:
        raise LFD01Error("LFD-01 solver-attempt cap exceeded")
    reserved_nas = sum(_row_storage_bytes(row) for row in active if _row_is_nas_backed(row))
    if nas_free - reserved_nas < NAS_MIN_FREE + int(request["estimated_storage_bytes"]):
        raise LFD01Error("NAS reservation would cross the 2 TiB floor")


def _lfd_terminal_guard(
    ledger: Mapping[str, Any], reservation: Mapping[str, Any], *, gpu_seconds: float,
    cpu_core_seconds: float, storage_bytes: int, request: Mapping[str, Any], grant: Mapping[str, Any], legacy_overrun,
    expected_adoption_sha256: str | None = None,
    expected_baseline_sha256: str | None = None,
) -> dict[str, Any] | None:
    adoption, baseline, adoption_sha256, baseline_sha256 = _authority()
    if expected_adoption_sha256 is not None and adoption_sha256 != expected_adoption_sha256:
        raise LFD01Error("adoption changed before terminal settlement")
    if expected_baseline_sha256 is not None and baseline_sha256 != expected_baseline_sha256:
        raise LFD01Error("baseline changed before terminal settlement")
    _verify_history(ledger, adoption, baseline)
    _validate_grant_policy(request, grant, adoption, ledger, exclude_attempt_id=_attempt_id(request))
    overrun = None
    if legacy_overrun is not None:
        overrun = legacy_overrun(
            ledger,
            reservation,
            gpu_seconds=gpu_seconds,
            cpu_core_seconds=cpu_core_seconds,
            storage_bytes=storage_bytes,
        )
    details: dict[str, Any] = {} if overrun is None else {"legacy": overrun}
    usage = _lfd_usage(ledger)
    for key, value in (("gpu_seconds", gpu_seconds), ("cpu_core_seconds", cpu_core_seconds), ("new_storage_bytes", storage_bytes)):
        cap = float(adoption.get("effective_caps", {}).get(key, 0))
        if usage[key] - float(reservation.get(key, 0)) + float(value) > cap:
            details.setdefault("lfd01_caps", {})[key] = {"cap": cap, "measured": value, "used_before": usage[key] - float(reservation.get(key, 0))}
    if storage_bytes > int(request["estimated_storage_bytes"]):
        details.setdefault("output", {})["estimated_storage_bytes"] = {"actual": storage_bytes, "declared": request["estimated_storage_bytes"]}
    return details or None


def _deferred_bindings(request: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [dict(item) for item in request.get("source_bindings", []) if isinstance(item, dict) and item.get("deferred") is True]


_COMPILED_BINARY_STAT_KEYS = ("device", "inode", "bytes", "mtime_ns", "ctime_ns")


def _compiled_binary_stat_record(value: os.stat_result, label: str) -> dict[str, int]:
    if not stat.S_ISREG(value.st_mode):
        raise LFD01Error(f"{label} is not a regular file")
    return {
        "device": int(value.st_dev),
        "inode": int(value.st_ino),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
    }


def _compiled_binary_fd_hash(
    path: Path, *, phase: str, expected_sha256: str,
    expected_stat: Mapping[str, Any], prior: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Hash the compiled executable once through one stable, no-follow FD.

    This helper is intentionally scoped to the already-admitted owned target
    launch and the after-owned-reap proof.  It is never called by request
    preflight, so a deferred executable payload cannot be opened before the
    shared reservation exists.  The before/after FD records and both lexical
    path lstat observations are metadata only; no payload is retained.
    """
    if phase not in {"owned_launch", "after_owned_reap"}:
        raise LFD01Error(f"compiled binary hash phase is not reservation-scoped: {phase}")
    try:
        lexical = Path(os.fspath(path))
    except TypeError as error:
        raise LFD01Error("compiled binary path is not path-like") from error
    if not lexical.is_absolute() or lexical.is_symlink():
        raise LFD01Error("compiled binary lexical path must be absolute and non-symlink")
    if not hasattr(os, "O_NOFOLLOW"):
        raise LFD01Error("compiled binary stable-FD admission requires O_NOFOLLOW")
    flags = os.O_RDONLY | os.O_NOFOLLOW
    flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(os.fspath(lexical), flags)
    except OSError as error:
        raise LFD01Error(f"cannot open compiled binary with O_NOFOLLOW: {lexical}: {error}") from error
    try:
        try:
            path_before = os.stat(lexical, follow_symlinks=False)
        except OSError as error:
            raise LFD01Error(f"compiled binary pre-lstat failed: {lexical}: {error}") from error
        fd_before = _compiled_binary_stat_record(os.fstat(fd), "compiled binary FD before hash")
        path_before_record = _compiled_binary_stat_record(path_before, "compiled binary pre-lstat")
        if path_before_record != fd_before:
            raise LFD01Error("compiled binary path identity differs from the opened FD before hash")
        for key in _COMPILED_BINARY_STAT_KEYS:
            if fd_before.get(key) != expected_stat.get(key):
                raise LFD01Error(f"compiled binary {phase} stat differs for {key}")
        digest = hashlib.sha256()
        total = 0
        while True:
            block = os.read(fd, 1024 * 1024)
            if not block:
                break
            digest.update(block)
            total += len(block)
        fd_after = _compiled_binary_stat_record(os.fstat(fd), "compiled binary FD after hash")
        try:
            path_after = os.stat(lexical, follow_symlinks=False)
        except OSError as error:
            raise LFD01Error(f"compiled binary post-lstat failed: {lexical}: {error}") from error
        path_after_record = _compiled_binary_stat_record(path_after, "compiled binary post-lstat")
        if fd_after != fd_before or path_after_record != fd_after:
            raise LFD01Error("compiled binary changed identity during one stable-FD hash")
        for key in _COMPILED_BINARY_STAT_KEYS:
            if fd_after.get(key) != expected_stat.get(key):
                raise LFD01Error(f"compiled binary {phase} post-stat differs for {key}")
        actual = digest.hexdigest()
        if total != int(expected_stat.get("bytes", -1)):
            raise LFD01Error(f"compiled binary {phase} byte count differs")
        if actual != expected_sha256:
            raise LFD01Error(f"compiled binary {phase} SHA-256 differs from BUILD004")
        if prior is not None:
            prior_after = prior.get("fd_stat_after")
            if not isinstance(prior_after, Mapping) or dict(prior_after) != fd_after:
                raise LFD01Error("compiled binary launch/after FD identity differs")
    finally:
        os.close(fd)
    return {
        "phase": phase,
        "path": str(lexical),
        "sha256": actual,
        "bytes": total,
        "fd_stat_before": fd_before,
        "fd_stat_after": fd_after,
        "path_lstat_before": path_before_record,
        "path_lstat_after": path_after_record,
        "regular": True,
        "observed_at_utc": _now(),
    }


def _hash_deferred(
    bindings: Sequence[Mapping[str, Any]], *, exclude_paths: frozenset[str] = frozenset(),
) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in bindings:
        path = _regular_path(item.get("path"), "deferred source")
        if str(path) in exclude_paths:
            continue
        expected = _require_sha(item.get("sha256"), f"deferred source sha256 {path}")
        if int(item.get("bytes", -1)) != path.stat().st_size:
            raise LFD01Error(f"deferred source size changed: {path}")
        actual = _sha256(path)
        if actual != expected:
            raise LFD01Error(f"deferred source hash mismatch: {path}")
        result[str(path)] = actual
    return result


def _worker_metadata_fsize_limit() -> int:
    """Bound worker metadata writes independently of the scientific output cap.

    The worker must be able to rewrite the real shared parent ledger.  Its
    limit is the current ledger size plus one bounded authority-metadata
    allowance; the scientific child receives the request output limit below.
    """
    ledger_path = PARENT_DATA_ROOT / "runtime" / "resource-ledger.json"
    try:
        ledger_bytes = max(0, int(ledger_path.stat().st_size))
    except OSError:
        # v6 will fail closed if the ledger is unavailable.  Keep enough room
        # for one bounded authority record while that failure is recorded.
        ledger_bytes = AUTHORITY_MAX_BYTES
    return max(2 * AUTHORITY_MAX_BYTES, ledger_bytes + AUTHORITY_MAX_BYTES)


def _child_fsize_limit(request: Mapping[str, Any]) -> int:
    """Return the real declared output ceiling for the launched child."""
    declared = int(request["estimated_storage_bytes"])
    if declared <= 0:
        raise LFD01Error("child output limit must be positive")
    if declared > FSIZE_GLOBAL_HARD:
        raise LFD01Error("child output limit exceeds the authorized 256 GiB hard ceiling")
    if request.get("execution_class") == "light":
        return min(declared, LIGHT_MAX_OUTPUT)
    return declared


def _trusted_prlimit() -> Path:
    helper = PRLIMIT_PATH
    if helper.is_symlink() or not helper.is_file():
        raise LFD01Error("trusted prlimit helper is not a regular file")
    actual = _sha256(helper)
    if actual != PRLIMIT_SHA256:
        raise LFD01Error("trusted prlimit helper changed")
    return helper


def _check_fsize_hard(required: int, scope: str) -> int:
    """Fail closed when the inherited file-size hard limit cannot authorize ``required``."""
    try:
        _soft, inherited_hard = resource.getrlimit(resource.RLIMIT_FSIZE)
    except (AttributeError, OSError, ValueError) as error:
        raise LFD01Error(f"cannot inspect file-size hard limit for {scope}: {error}") from error
    if inherited_hard != resource.RLIM_INFINITY and int(inherited_hard) < int(required):
        raise LFD01Error(
            f"inherited file-size hard limit for {scope} is below {int(required)} bytes: {inherited_hard}"
        )
    return int(required)


def _fsize_limits(request: Mapping[str, Any], *, scope: str) -> tuple[int, int]:
    """Return the soft/hard RLIMIT_FSIZE pair after inherited-hard validation."""
    if scope == "worker":
        soft = _worker_metadata_fsize_limit()
        hard = _check_fsize_hard(FSIZE_GLOBAL_HARD, "worker metadata")
    elif scope == "light":
        soft = _child_fsize_limit(request)
        hard = _check_fsize_hard(soft, "sealed light output")
    else:
        raise LFD01Error(f"unknown process limit scope: {scope}")
    if soft > hard:
        raise LFD01Error(
            f"file-size soft limit for {scope} exceeds its authorized hard limit: {soft}>{hard}"
        )
    return int(soft), int(hard)


def _set_process_limits(request: Mapping[str, Any], *, scope: str) -> tuple[int, int]:
    fsize_soft, fsize_hard = _fsize_limits(request, scope=scope)
    cpuset = set(int(value) for value in request["affinity_cpus"])
    try:
        os.sched_setaffinity(0, cpuset)
    except (AttributeError, OSError) as error:
        raise LFD01Error(f"cannot enforce inherited cpuset: {error}") from error
    limit = int(request["ram_limit_bytes"])
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    try:
        # Metadata keeps its bounded soft limit, while the worker hard limit
        # is the already-authorized global ceiling.  The child wrapper lowers
        # its own soft/hard limit to the request; no privilege escalation is
        # attempted here.
        resource.setrlimit(resource.RLIMIT_FSIZE, (fsize_soft, fsize_hard))
    except (AttributeError, ValueError, OSError) as error:
        raise LFD01Error(f"cannot enforce file-size limit for {scope}: {error}") from error
    return fsize_soft, fsize_hard


class _ObservedProcess:
    """Small Popen proxy that runs the one terminal proof after wait()."""

    def __init__(self, process: subprocess.Popen[str], on_exit) -> None:
        self._process = process
        self._on_exit = on_exit
        self._proof_done = False

    @property
    def pid(self) -> int:
        return self._process.pid

    @property
    def returncode(self) -> int | None:
        return self._process.returncode

    def poll(self):
        return self._process.poll()

    def wait(self, *args, **kwargs):
        result = self._process.wait(*args, **kwargs)
        if not self._proof_done:
            self._proof_done = True
            self._on_exit()
        return result

    def __getattr__(self, name: str):
        return getattr(self._process, name)


def _write_runtime_state(job_dir: Path, state: Mapping[str, Any], lock: threading.Lock) -> None:
    with lock:
        _atomic_json(job_dir / "worker-runtime.json", dict(state))


def _wrap_child_popen(command: list[str], request: Mapping[str, Any], args: tuple[Any, ...],
                      kwargs: Mapping[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any], int]:
    """Apply child RLIMIT_FSIZE through the trusted prlimit executable.

    The request command and its binary binding remain unchanged in v6's
    receipt.  Only the low-level Popen argv is wrapped, so the child and all
    descendants inherit the declared output ceiling without a threaded
    Python preexec_fn.
    """
    helper = _trusted_prlimit()
    limit = _child_fsize_limit(request)
    _check_fsize_hard(limit, "scientific child")
    wrapped = [str(helper), f"--fsize={limit}", "--", *command]
    positional = list(args)
    named = dict(kwargs)
    if "args" in named:
        named["args"] = wrapped
    elif positional:
        positional[0] = wrapped
    else:
        raise LFD01Error("Popen child command is missing")
    return tuple(positional), named, limit


@contextmanager
def _v6_bindings(
    request: Mapping[str, Any], request_path: Path, *, deferred_state: dict[str, Any],
    g2_state: dict[str, Any], runtime_state: dict[str, Any], state_lock: threading.Lock,
    grant: Mapping[str, Any], job_dir: Path,
    expected_adoption_sha256: str, expected_baseline_sha256: str,
) -> Iterator[None]:
    """Bind LFD-01 policy to one in-process v6 call and restore every hook."""
    v6 = _import_v6_runtime()
    base = v6.base
    saved = {
        "upstream_nas": v6.UPSTREAM_NAS,
        "upstream_id": v6._upstream_id,
        "is_nas": v6._is_nas_request,
        "nas_available": v6._nas_available,
        "assert_nas": v6._assert_nas_path_live,
        "output_path": v6._output_path,
        "check_batch": v6._check_upstream_batch,
        "terminal_overrun": v6._terminal_upstream_overrun,
        "apply_terminal_guard": v6._apply_terminal_upstream_guard,
        "base_validate": v6._base_validate,
        "base_check_reservation": v6._base_check_reservation,
        "check_reservation": v6.check_reservation,
        "ledger_locked": v6.ledger_locked,
        "base_atomic_json": v6._base_atomic_json,
        "guarded_receipt": v6._guarded_atomic_json,
        "runtime_path": v6.RUNTIME_PATH,
        "base_runtime_path": v6.BASE_RUNTIME_PATH,
        "popen": base.subprocess.Popen,
        "retain": v6._retain_unresolved_nas_reservation,
        "unresolved_bytes": v6._unresolved_storage_reservation_bytes,
    }
    # Keep the complete consumed v6 callback (finite checks, deadline
    # duration, and its v2 parent budget/attempt checks), rather than calling
    # v2 directly and accidentally dropping the v6 deadline guard.
    legacy_check = saved["check_reservation"]
    reservation_admitted = False
    # The UF-01 batch cap belongs to the old upstream campaign.  LFD-01 has
    # its own effective caps and queue checks below.
    legacy_overrun = None

    def is_nas(request_value: Mapping[str, Any]) -> bool:
        return request_value.get("output_storage") == "lfd01_nas"

    @contextmanager
    def ledger_locked(*args, **kwargs):
        _assert_parent_data_root()
        with saved["ledger_locked"](*args, **kwargs) as ledger:
            yield ledger
            # v6's fixed charge writer intentionally copies only legacy
            # fields.  Add the immutable LFD pool/tranche identity while the
            # same parent lock is still held so later pool accounting cannot
            # confuse a central charge with work-pool usage.
            attempt = _attempt_id(request)
            metadata = {
                "campaign_id": "LFD-01", "namespace": NAMESPACE,
                "lfd01_namespace": NAMESPACE, "pool": grant.get("pool"),
                "tranche_id": grant.get("tranche_id"), "stage": grant.get("stage"),
                "purpose": grant.get("purpose") or request.get("central_purpose"),
            }
            for collection in (ledger.get("reservations", []), ledger.get("charges", []), ledger.get("attempts", [])):
                for row in collection:
                    if isinstance(row, dict) and row.get("id") == attempt:
                        row.update(metadata)
            _assert_parent_data_root()

    def output_path(request_value: Mapping[str, Any], _data_root: Path) -> Path:
        if not is_nas(request_value):
            raise LFD01Error("LFD-01 output must use the new NAS root")
        attempt = _attempt_id(request_value)
        if not _is_lfd_attempt(attempt):
            raise LFD01Error("unsafe LFD-01 attempt path")
        _assert_nas_path(NAS_RUNS)
        return NAS_RUNS / attempt

    def nas_available() -> int:
        return _nas_free_bytes()

    def assert_nas(path: str | Path) -> None:
        _assert_nas_path(path)

    def structural_validate(value: Mapping[str, Any], *, approval_context=None) -> dict[str, str]:
        # v6's structural validator is retained.  Production is projected to
        # qualification for that call so the old mutable approval registry is
        # never imported; LFD-01 G2 was checked above and is rechecked at the
        # terminal receipt hook.
        projected = dict(value)
        if projected.get("kind") == "production":
            projected["kind"] = "qualification"
        actual = saved["base_validate"](projected, approval_context=None)
        expected = {str(Path(item["path"]).resolve()): item["sha256"]
                    for item in value.get("source_bindings", [])
                    if not item.get("deferred")}
        for path, digest in expected.items():
            if actual.get(path) != digest:
                raise LFD01Error(f"v6 normal input hash differs from grant: {path}")
        return actual

    def check_batch(ledger: dict[str, Any], reservation: dict[str, Any], value: Mapping[str, Any]) -> None:
        # Global LFD-01 admission is performed in check_reservation below.
        return None

    def terminal_overrun(ledger: Mapping[str, Any], reservation: Mapping[str, Any], *, gpu_seconds: float, cpu_core_seconds: float, storage_bytes: int) -> dict[str, Any] | None:
        return _lfd_terminal_guard(
            ledger, reservation,
            gpu_seconds=gpu_seconds, cpu_core_seconds=cpu_core_seconds,
            storage_bytes=storage_bytes, request=request, legacy_overrun=legacy_overrun,
            grant=grant,
            expected_adoption_sha256=expected_adoption_sha256,
            expected_baseline_sha256=expected_baseline_sha256,
        )

    def apply_terminal_guard(ledger: Mapping[str, Any], reservation: Mapping[str, Any], receipt: dict[str, Any], measured_cpu: float) -> dict[str, Any] | None:
        storage_bytes = receipt.get("bytes")
        if not isinstance(storage_bytes, int):
            return None
        overrun = terminal_overrun(
            ledger, reservation,
            gpu_seconds=float(receipt.get("gpu_seconds", 0) or 0),
            cpu_core_seconds=float(measured_cpu),
            storage_bytes=storage_bytes,
        )
        if overrun:
            receipt["status"] = "failed"
            # v6's fixed-point loop uses this legacy key as its convergence
            # marker.  The value itself is the LFD-01-only guard result and
            # is mirrored under the namespaced key for downstream readers.
            receipt["upstream_batch_overrun"] = overrun
            receipt["lfd01_terminal_overrun"] = overrun
            if not receipt.get("termination_reason"):
                receipt["termination_reason"] = "lfd01_cap_or_output_limit_exceeded"
        return overrun

    def unresolved_bytes(ledger: Mapping[str, Any], reservation: Mapping[str, Any]) -> int:
        # Retain this request's declared NAS reservation if final storage
        # measurement is unavailable.  Do not borrow the old UF batch cap.
        return max(int(reservation.get("new_storage_bytes", 0)), 0)

    def retain_unresolved(ledger: dict[str, Any], reservation: dict[str, Any], error: BaseException) -> int:
        value = unresolved_bytes(ledger, reservation)
        reservation.update(storage_unresolved=True, storage_unresolved_reason=str(error),
                           storage_unresolved_at_utc=_now(), new_storage_bytes=value)
        for row in ledger.get("reservations", []):
            if row.get("id") == reservation.get("id"):
                row.update(reservation)
        return value

    def attach_runtime_receipt(value: dict[str, Any], *, terminal: bool, deferred_proof: Mapping[str, Any]) -> None:
        """Attach only namespaced forward fields, preserving v6 top-level status."""
        top_status = value.get("status")
        if terminal:
            execution_status = (str(top_status).upper()
                                if top_status in {"completed", "failed"}
                                else "INVALID_TERMINAL")
        else:
            # v6 writes the real top-level ``status='running'`` before the
            # child can be observed by the helper.  RUNNING is emitted only
            # when both facts are true; the original v6 status is untouched.
            execution_status = (
                "RUNNING" if top_status == "running" and runtime_state.get("owned_child") is not None
                else "INVALID_RUNNING"
            )
        value["lfd01_runtime"] = {
            "schema": SCHEMA,
            "namespace": NAMESPACE,
            "execution_status": execution_status,
            "top_level_v6_status": top_status,
            "candidate_path": str(SCRIPT_PATH),
            "candidate_sha256": _sha256(SCRIPT_PATH),
            "schema_path": str(SCHEMA_PATH),
            "schema_sha256": _sha256(SCHEMA_PATH),
            "v6_path": str(V6_PATH),
            "v2_path": str(V2_PATH),
            "execution_class": request["execution_class"],
            "affinity_cpus": list(request["affinity_cpus"]),
            "ram_limit_bytes": int(request["ram_limit_bytes"]),
            "max_wall_seconds": float(request["max_wall_seconds"]),
            "worker_metadata_fsize_limit_bytes": int(runtime_state.get("worker_metadata_fsize_limit_bytes", 0) or 0),
            "worker_metadata_fsize_soft_bytes": int(runtime_state.get("worker_metadata_fsize_soft_bytes", 0) or 0),
            "worker_metadata_fsize_hard_bytes": int(runtime_state.get("worker_metadata_fsize_hard_bytes", 0) or 0),
            "child_fsize_limit_bytes": int(runtime_state.get("child_fsize_limit_bytes", _child_fsize_limit(request)) or 0),
            "child_fsize_soft_bytes": int(runtime_state.get("child_fsize_soft_bytes", 0) or 0),
            "child_fsize_hard_bytes": int(runtime_state.get("child_fsize_hard_bytes", 0) or 0),
            "child_fsize_helper": {"path": str(PRLIMIT_PATH), "sha256": PRLIMIT_SHA256},
            "deferred_input_hashes": dict(deferred_proof),
            "g2": g2_state,
            "owned_child": runtime_state.get("owned_child"),
            "owned_group": runtime_state.get("owned_group"),
            "subreaper_enabled": bool(runtime_state.get("subreaper_enabled", False)),
            "parent_proof": runtime_state.get("parent_proof"),
            "child_exit_confirmed": bool(runtime_state.get("child_exit_confirmed", False)),
            "terminal_settlement_blocked": runtime_state.get("terminal_settlement_blocked"),
            "verified_member_proofs": runtime_state.get("owned_group_snapshot", {}).get("verified_member_proofs", []),
            "final_reap": runtime_state.get("final_reap"),
            "launch_identity_observed": runtime_state.get("launch_identity_observed"),
            "owned_identity_uncertain": bool(runtime_state.get("owned_identity_uncertain", False)),
            "launch_cleanup": runtime_state.get("launch_cleanup"),
            "children_rusage_interval": runtime_state.get("children_rusage_interval"),
            "peak_rss_bytes": runtime_state.get("peak_rss_bytes", 0),
            "unreaped_branch_unknown": bool(runtime_state.get("unreaped_branch_unknown", False)),
            "unreaped_branch_unknown_interval": runtime_state.get("unreaped_branch_unknown_interval"),
            "storage_root": str(NAS_ROOT),
            "solver_branch": request.get("solver_branch", "official_v12"),
            "compiled_binary_attestation": request.get("_compiled_attestation_checked"),
            "compiled_binary_reservation_admitted": bool(runtime_state.get("compiled_binary_reservation_admitted", False)),
            "compiled_binary_observations": runtime_state.get("compiled_binary_observations"),
        }

    def _error_text(error: BaseException) -> str:
        """Return a JSON-safe bounded error description for state records."""
        return f"{type(error).__name__}: {str(error)[:512]}"

    def mark_not_launched(error: BaseException | None = None, *, process_started: bool = False) -> None:
        """Close deferred proof without opening an after-hash on launch failure."""
        status = "failed" if process_started else "not_launched"
        state: dict[str, Any] = {"attempted": True, "status": status}
        if error is not None:
            state["error"] = _error_text(error)
        with state_lock:
            runtime_state["posthash"] = state
        deferred_state["after"] = None
        _write_runtime_state(job_dir, runtime_state, state_lock)

    def post_exit_proof() -> None:
        """Hash deferred sources and revalidate G2 before v6's CPU cutoff.

        ``_ObservedProcess.wait`` invokes this only after the real child wait
        and verified owned-group cleanup.  The v6 terminal writer therefore
        receives serializable proof state and never performs a late hash.
        """
        with state_lock:
            if runtime_state.get("posthash", {}).get("attempted", False):
                return
            runtime_state.setdefault("posthash", {})["attempted"] = True
            runtime_state["posthash"]["status"] = "pending"
            child_exit_confirmed = bool(runtime_state.get("child_exit_confirmed", False))
        if not child_exit_confirmed:
            with state_lock:
                runtime_state["posthash"].update(
                    status="failed", error="owned child/group exit was not confirmed"
                )
            _write_runtime_state(job_dir, runtime_state, state_lock)
            return
        try:
            compiled_branch = _is_compiled_binary_request(request)
            if compiled_branch and not reservation_admitted:
                raise LFD01Error("compiled binary after-hash lacks the live shared reservation proof")
            binary_after = None
            excluded = frozenset()
            if compiled_branch:
                binary_path = Path(str(request["binary_binding"]["path"]))
                launch_observation = None
                with state_lock:
                    observations = runtime_state.get("compiled_binary_observations")
                    if isinstance(observations, dict):
                        launch_observation = observations.get("owned_launch")
                if not isinstance(launch_observation, dict):
                    raise LFD01Error("compiled binary after-hash lacks its owned-launch observation")
                binary_after = _compiled_binary_fd_hash(
                    binary_path, phase="after_owned_reap",
                    expected_sha256=COMPILED_BINARY_SHA256,
                    expected_stat=COMPILED_BINARY_STAT, prior=launch_observation,
                )
                excluded = frozenset({str(binary_path)})
            after = _hash_deferred(_deferred_bindings(request), exclude_paths=excluded)
            if binary_after is not None:
                after[str(binary_after["path"])] = binary_after["sha256"]
                with state_lock:
                    runtime_state.setdefault("compiled_binary_observations", {})["after_owned_reap"] = binary_after
            deferred_state["after"] = after
            with state_lock:
                runtime_state["posthash"]["status"] = "verified"
            if deferred_state.get("launch") != after:
                with state_lock:
                    runtime_state["posthash"].update(
                        status="failed", error="deferred_input_mutated_during_run"
                    )
        except BaseException as error:
            with state_lock:
                runtime_state["posthash"].update(status="failed", error=_error_text(error))
        try:
            g2_value = _validate_g2(request, after_hashes=True)
            g2_state["terminal"] = g2_value or "not_required"
        except BaseException as error:
            if request.get("kind") == "production":
                g2_state["terminal"] = {"status": "failed", "error": _error_text(error)}
        _write_runtime_state(job_dir, runtime_state, state_lock)

    def guarded_receipt(path: Path, value: dict[str, Any]) -> Any:
        if path.name == "execution-receipt.json" and value.get("schema") == "ds02.execution-receipt.v1":
            terminal = "finished_at_utc" in value or value.get("returncode") is not None
            if terminal:
                # The legacy v6 writer removes the reservation immediately
                # after this callback.  Keep that reservation durable until
                # the whole owned tree has been confirmed exited; guardian
                # recovery will settle it after a bounded cleanup/unknown
                # interval.  This prevents a surviving orphan from being
                # charged as a normal terminal run and releasing its lease.
                if (runtime_state.get("owned_child") is not None
                        and not runtime_state.get("child_exit_confirmed", False)):
                    blocked = {
                        "status": "waiting_for_owned_exit",
                        "reason": "terminal_settlement_requires_confirmed_owned_tree_exit",
                        "observed_at_utc": _now(),
                    }
                    with state_lock:
                        runtime_state["terminal_settlement_blocked"] = blocked
                    _write_runtime_state(job_dir, runtime_state, state_lock)
                    raise RuntimeError(
                        "owned child/group exit is unconfirmed; retain reservation for guardian recovery"
                    )
                # Deferred/G2 proof was completed from post_exit before v6's
                # normal post-run hashes and measured_cpu cutoff.  This hook
                # only projects its serializable result into the receipt.
                posthash = runtime_state.get("posthash", {})
                if (not posthash.get("attempted", False)
                        and runtime_state.get("owned_child") is None
                        and deferred_state.get("launch") is None):
                    # v6 can fail during validation/reservation setup before
                    # the request executable is ever launched.  Do not open a
                    # deferred source here merely to populate a terminal
                    # receipt; record the bounded no-launch result instead.
                    posthash = {"attempted": True, "status": "not_launched",
                                "error": "child was never launched"}
                    with state_lock:
                        runtime_state["posthash"] = posthash
                    _write_runtime_state(job_dir, runtime_state, state_lock)
                if posthash.get("status") in {"failed", "not_launched"}:
                    value["status"] = "failed"
                    value.setdefault(
                        "provenance_error",
                        f"deferred_posthash_{posthash.get('status')}: {posthash.get('error', 'unknown')}",
                    )
                g2_terminal = g2_state.get("terminal")
                if (request.get("kind") == "production" and isinstance(g2_terminal, dict)
                        and g2_terminal.get("status") == "failed"):
                    value["status"] = "failed"
                    value.setdefault("provenance_error", "g2_revalidation_failed")
            if terminal and runtime_state.get("descendant_cleanup_required"):
                value["status"] = "failed"
                value.setdefault("provenance_error", "owned_descendants_required_guardian_cleanup")
            if terminal and runtime_state.get("unreaped_branch_unknown"):
                value["status"] = "failed"
                value.setdefault("provenance_error", "linux_subreaper_unavailable_unreaped_branch_unknown")
            if not terminal:
                # RUNNING is launch proof only.  It never forces a deferred
                # multi-gigabyte hash and never embeds a Python tracker.
                deferred_proof = {"launch": deferred_state.get("launch"), "after": None,
                                  "posthash_status": "pending"}
            else:
                deferred_proof = {"launch": deferred_state.get("launch"), "after": deferred_state.get("after"),
                                  "posthash_status": runtime_state.get("posthash", {}).get("status", "pending")}
            attach_runtime_receipt(value, terminal=terminal, deferred_proof=deferred_proof)
        return saved["guarded_receipt"](path, value)

    def running_receipt(path: Path, value: dict[str, Any]) -> Any:
        """Wrap v6's immutable running writer without changing its top status."""
        if path.name == "execution-receipt.json" and value.get("schema") == "ds02.execution-receipt.v1":
            terminal = "finished_at_utc" in value or value.get("returncode") is not None
            if not terminal:
                attach_runtime_receipt(
                    value,
                    terminal=False,
                    deferred_proof={"launch": deferred_state.get("launch"),
                                    "after": None, "posthash_status": "pending"},
                )
        return saved["base_atomic_json"](path, value)

    def launch(*args, **kwargs):
        command = kwargs.get("args")
        if command is None and args:
            command = args[0]
        if not isinstance(command, (list, tuple)):
            raise LFD01Error("v6 child command must be an argv list")
        command = list(command)
        expected_path = Path(request["binary_binding"]["path"]).resolve()
        # v6/v2 use subprocess.run for immutable git/inventory metadata before
        # and during admission.  Only the frozen request executable receives
        # the deferred-hash and identity hook.  Limits were applied to the
        # worker before any heartbeat threads, so children inherit them; a
        # No threaded Python child hook is installed here.
        try:
            command_path = Path(command[0]).expanduser().resolve()
        except (IndexError, OSError):
            command_path = Path("")
        if command_path != expected_path:
            return saved["popen"](*args, **kwargs)
        process = None
        try:
            compiled_branch = _is_compiled_binary_request(request)
            if compiled_branch and not reservation_admitted:
                raise LFD01Error("compiled binary launch hash lacks the live shared reservation proof")
            binary_observation = None
            excluded = frozenset()
            if compiled_branch:
                binary_path = Path(str(request["binary_binding"]["path"]))
                binary_observation = _compiled_binary_fd_hash(
                    binary_path, phase="owned_launch",
                    expected_sha256=COMPILED_BINARY_SHA256,
                    expected_stat=COMPILED_BINARY_STAT,
                )
                excluded = frozenset({str(binary_path)})
                with state_lock:
                    runtime_state["compiled_binary_observations"] = {
                        "owned_launch": binary_observation,
                    }
            deferred_state["launch"] = _hash_deferred(
                _deferred_bindings(request), exclude_paths=excluded
            )
            if binary_observation is not None:
                deferred_state["launch"][str(binary_observation["path"])] = binary_observation["sha256"]
            _atomic_json(job_dir / "deferred-launch.json", {
                "schema": "lfd01.deferred-launch.v1", "attempt_id": _attempt_id(request),
                "observed_at_utc": _now(), "hashes": deferred_state["launch"],
                "compiled_binary_observation": binary_observation,
            })
            child_args, child_kwargs, child_fsize_limit = _wrap_child_popen(command, request, args, kwargs)
            parent_proof_required = _parent_proof_required(command)
            parent_proof_path = job_dir / PARENT_PROOF_FILENAME
            if parent_proof_path.exists():
                raise LFD01Error("parent-proof path already exists; refusing stale ownership evidence")
            parent_proof_token = uuid.uuid4().hex
            child_kwargs = dict(child_kwargs)
            if parent_proof_required:
                child_env = dict(child_kwargs.get("env") or os.environ)
                child_env[PARENT_PROOF_ENV_PATH] = str(parent_proof_path)
                child_env[PARENT_PROOF_ENV_TOKEN] = parent_proof_token
                child_kwargs["env"] = child_env
            with state_lock:
                runtime_state["parent_proof"] = {
                    "schema": "lfd01.parent-proof.v1",
                    "path": str(parent_proof_path),
                    "required": bool(parent_proof_required),
                    "token_sha256": _proof_token_sha256(parent_proof_token),
                    "status": "pending",
                }
            _write_runtime_state(job_dir, runtime_state, state_lock)
            # Capture the raw waited-child counter immediately before this
            # request child is launched.  The interval is diagnostic only:
            # normal charging still uses _cpu_usage/RUSAGE_CHILDREN plus the
            # live owned-group sample without adding this value separately.
            children_before_launch = _children_rusage_snapshot("child.launch_before")
            with state_lock:
                runtime_state["children_rusage_interval"] = {
                    "before_launch": children_before_launch,
                    "scope": "target child Popen through real wait and final owned-tree reap; no posthash",
                    "other_child_processes_expected": False,
                }
            _write_runtime_state(job_dir, runtime_state, state_lock)
            process = saved["popen"](*child_args, **child_kwargs)
            with state_lock:
                runtime_state["child_fsize_limit_bytes"] = child_fsize_limit
                runtime_state["child_fsize_soft_bytes"] = child_fsize_limit
                runtime_state["child_fsize_hard_bytes"] = child_fsize_limit
                runtime_state["child_fsize_helper"] = {"path": str(PRLIMIT_PATH), "sha256": PRLIMIT_SHA256}
            child_identity = _checkpoint_identity(process.pid)
            with state_lock:
                runtime_state["launch_identity_observed"] = dict(child_identity)
            if child_identity.get("start_ticks") is None:
                raise LFD01Error("child start identity unavailable immediately after Popen")
            try:
                pgid = os.getpgid(process.pid)
            except (OSError, ProcessLookupError) as error:
                raise LFD01Error("child process group identity unavailable immediately after Popen") from error
            subreaper_identity = _checkpoint_identity(os.getpid())
            if runtime_state.get("subreaper_enabled", False) and subreaper_identity.get("start_ticks") is None:
                raise LFD01Error("worker subreaper identity was unavailable at child launch")
            group = {"pgid": int(pgid), "leader": child_identity,
                     "known_members": [dict(child_identity)],
                     "host": socket.gethostname(), "boot_id": _boot_id(),
                     "subreaper_enabled": bool(runtime_state.get("subreaper_enabled", False)),
                     "subreaper_identity": subreaper_identity,
                     "parent_proof": None,
                     "identity_uncertain": False}
            with state_lock:
                runtime_state.update(owned_child=child_identity, owned_group=group,
                                     child_launched_at_utc=_now(), child_exit_confirmed=False,
                                     child_exit_at_utc=None)
            _write_runtime_state(job_dir, runtime_state, state_lock)
            # Persist the process/group identity before waiting for the
            # optional handshake.  A caller SIGKILL in this narrow window can
            # therefore still be recovered from the launch record; the proof
            # field is deliberately left pending until the token-validated
            # child record arrives.
            _atomic_json(job_dir / "owned-child-launch.json", {
                "schema": "lfd01.owned-child-launch.v2", "attempt_id": _attempt_id(request),
                "worker_identity": _checkpoint_identity(os.getpid()), "owned_child": child_identity,
                "owned_group": group, "subreaper_enabled": runtime_state.get("subreaper_enabled", False),
                "parent_proof_status": "pending", "launched_at_utc": _now(),
            })
            parent_proof = (
                _await_parent_proof(
                    parent_proof_path,
                    token=parent_proof_token,
                    expected_parent=child_identity,
                    expected_pgid=int(pgid),
                )
                if parent_proof_required else None
            )
            if parent_proof is not None:
                proof_child = dict(parent_proof["child_identity"])
                known = group.setdefault("known_members", [])
                if _identity_key(proof_child) not in {_identity_key(item) for item in known}:
                    known.append(proof_child)
                group["parent_proof"] = parent_proof
            with state_lock:
                if parent_proof is None:
                    runtime_state["parent_proof"].update(
                        status="missing_required" if parent_proof_required else "not_provided",
                    )
                else:
                    runtime_state["parent_proof"].update(status="verified", proof=parent_proof)
                runtime_state["owned_group"] = group
            _write_runtime_state(job_dir, runtime_state, state_lock)
            if parent_proof_required and parent_proof is None:
                raise LFD01Error("instrumented orphan probe did not provide a valid parent-proof handshake")
            _atomic_json(job_dir / "owned-child-launch.json", {
                "schema": "lfd01.owned-child-launch.v2", "attempt_id": _attempt_id(request),
                "worker_identity": _checkpoint_identity(os.getpid()), "owned_child": child_identity,
                "owned_group": group, "subreaper_enabled": runtime_state.get("subreaper_enabled", False),
                "launched_at_utc": _now(),
            })
            # Preserve the worker-entry CPU counter across launch.  This
            # immediate atomic sample closes the interval before the first
            # heartbeat, when an orphaned worker could otherwise lose all
            # preflight/hash CPU from recovery accounting.
            _update_runtime_state(job_dir, runtime_state, state_lock,
                                  float(runtime_state.get("entry_cpu_seconds", 0.0) or 0.0))

            def post_exit() -> None:
                _reap_owned_descendants(group)
                deadline = time.monotonic() + GROUP_GRACE_SECONDS
                while time.monotonic() < deadline:
                    group_snapshot = _owned_group_snapshot(group)
                    if (not group_snapshot.get("members")
                            and not group_snapshot.get("identity_unverified_members")
                            and not group_snapshot.get("identity_mismatch")):
                        break
                    time.sleep(0.05)
                group_snapshot = _owned_group_snapshot(group)
                if (group_snapshot.get("members")
                        or group_snapshot.get("identity_unverified_members")
                        or group_snapshot.get("identity_mismatch")):
                    cleanup = _terminate_verified_owned_group(job_dir, {"runtime_state": runtime_state}, reason="descendant_exit_required")
                    with state_lock:
                        runtime_state["owned_group_cleanup"] = cleanup
                        runtime_state["descendant_cleanup_required"] = True
                final_reap = _final_reap_owned_descendants(group)
                final_snapshot = final_reap["snapshot"]
                children_after_reap = _children_rusage_snapshot("child.after_final_reap")
                with state_lock:
                    before = runtime_state.get("children_rusage_interval", {}).get("before_launch")
                    if isinstance(before, dict):
                        runtime_state["children_rusage_interval"] = _children_rusage_interval(
                            before, children_after_reap
                        )
                    else:
                        runtime_state["children_rusage_interval"] = {
                            "after_final_reap": children_after_reap,
                            "scope": "target child Popen through real wait and final owned-tree reap; no posthash",
                            "other_child_processes_expected": False,
                            "diagnostic_error": "missing prelaunch RUSAGE_CHILDREN sample",
                        }
                    runtime_state["final_reap"] = {
                        "reaped": int(final_reap.get("reaped", 0) or 0),
                        "completed": bool(final_reap.get("completed", False)),
                    }
                    runtime_state["owned_group_snapshot"] = final_snapshot
                    runtime_state["child_exit_at_utc"] = _now()
                    runtime_state["child_exit_confirmed"] = bool(final_reap.get("completed", False))
                    if not runtime_state.get("subreaper_enabled", False):
                        # Without Linux subreaper support, reparented descendants
                        # cannot be waited by this worker.  Keep an explicit,
                        # disjoint uncertainty interval in the receipt/checkpoint
                        # rather than silently treating the tree as fully known.
                        runtime_state["unreaped_branch_unknown"] = True
                        runtime_state["unreaped_branch_unknown_interval"] = {
                            "start_utc": runtime_state.get("last_trusted_at_utc") or runtime_state.get("child_launched_at_utc"),
                            "end_utc": runtime_state.get("child_exit_at_utc"),
                            "reason": "linux_subreaper_unavailable",
                        }
                _write_runtime_state(job_dir, runtime_state, state_lock)
                # This runs synchronously from the real Popen.wait path, before
                # v6 computes its normal post-run hashes and measured CPU.
                post_exit_proof()

            return _ObservedProcess(process, post_exit)
        except BaseException as error:
            if process is not None:
                group = runtime_state.get("owned_group")
                if (isinstance(group, dict) and group.get("identity_uncertain") is False
                        and _identity_key(group.get("leader")) is not None):
                    cleanup = _terminate_verified_owned_group(
                        job_dir, {"runtime_state": deepcopy(runtime_state)},
                        reason="launch_identity_or_persistence_failure",
                    )
                    if not cleanup.get("confirmed_exit"):
                        cleanup["direct_process_cleanup"] = _terminate_spawned_process(
                            process, reason="launch_identity_or_persistence_failure"
                        )
                    else:
                        try:
                            process.wait(timeout=GROUP_GRACE_SECONDS)
                        except (subprocess.TimeoutExpired, OSError, ProcessLookupError):
                            cleanup["direct_process_cleanup"] = _terminate_spawned_process(
                                process, reason="launch_identity_or_persistence_failure"
                            )
                else:
                    cleanup = _terminate_spawned_process(
                        process, reason="launch_identity_or_persistence_failure"
                    )
                with state_lock:
                    runtime_state["owned_identity_uncertain"] = True
                    runtime_state["launch_cleanup"] = cleanup
                try:
                    _write_runtime_state(job_dir, runtime_state, state_lock)
                except (OSError, LFD01Error, ValueError):
                    # Preserve the primary launch failure.  The process-handle
                    # cleanup above remains the only signal sent on this path.
                    pass
            mark_not_launched(error, process_started=process is not None)
            raise

    def checked(ledger: dict[str, Any], reservation: dict[str, Any], existing_bytes: int, **kwargs) -> None:
        nonlocal reservation_admitted
        _lfd_check_reservation(
            ledger, reservation, existing_bytes, request=request,
            grant=grant,
            legacy_check=legacy_check,
            expected_adoption_sha256=expected_adoption_sha256,
            expected_baseline_sha256=expected_baseline_sha256,
        )
        reservation_admitted = True
        if request.get("solver_branch") == COMPILED_SOLVER_BRANCH:
            with state_lock:
                runtime_state["compiled_binary_reservation_admitted"] = True

    v6.UPSTREAM_NAS = NAS_ROOT
    v6._upstream_id = _is_lfd_attempt
    v6._is_nas_request = is_nas
    v6._nas_available = nas_available
    v6._assert_nas_path_live = assert_nas
    v6._output_path = output_path
    v6._check_upstream_batch = check_batch
    v6._terminal_upstream_overrun = terminal_overrun
    v6._apply_terminal_upstream_guard = apply_terminal_guard
    v6._base_validate = structural_validate
    v6.check_reservation = checked
    v6.ledger_locked = ledger_locked
    v6._retain_unresolved_nas_reservation = retain_unresolved
    v6._unresolved_storage_reservation_bytes = unresolved_bytes
    v6.RUNTIME_PATH = str(SCRIPT_PATH)
    v6.BASE_RUNTIME_PATH = str(V2_PATH)
    v6._base_atomic_json = running_receipt
    # v6's terminal path calls its module-level _guarded_atomic_json.  Bind
    # the LFD projection explicitly; saving/restoring it prevents recursion
    # and leaves the immutable legacy module unchanged after this call.
    v6._guarded_atomic_json = guarded_receipt
    base.subprocess.Popen = launch
    try:
        yield
    finally:
        v6.UPSTREAM_NAS = saved["upstream_nas"]
        v6._upstream_id = saved["upstream_id"]
        v6._is_nas_request = saved["is_nas"]
        v6._nas_available = saved["nas_available"]
        v6._assert_nas_path_live = saved["assert_nas"]
        v6._output_path = saved["output_path"]
        v6._check_upstream_batch = saved["check_batch"]
        v6._terminal_upstream_overrun = saved["terminal_overrun"]
        v6._apply_terminal_upstream_guard = saved["apply_terminal_guard"]
        v6._base_validate = saved["base_validate"]
        v6.ledger_locked = saved["ledger_locked"]
        v6._base_atomic_json = saved["base_atomic_json"]
        v6._guarded_atomic_json = saved["guarded_receipt"]
        v6.RUNTIME_PATH = saved["runtime_path"]
        v6.BASE_RUNTIME_PATH = saved["base_runtime_path"]
        v6._retain_unresolved_nas_reservation = saved["retain"]
        v6._unresolved_storage_reservation_bytes = saved["unresolved_bytes"]
        v6.check_reservation = saved["check_reservation"]
        base.subprocess.Popen = saved["popen"]


def _checkpoint_identity(pid: int) -> dict[str, Any]:
    return {"pid": int(pid), "host": socket.gethostname(), "boot_id": _boot_id(), "start_ticks": _proc_start_ticks(pid)}


def _self_rusage_snapshot(scope: str) -> dict[str, Any]:
    """Record only this process's CPU; children are deliberately excluded."""
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return {
        "scope": scope,
        "source": "resource.RUSAGE_SELF",
        "children_excluded": True,
        "identity": _checkpoint_identity(os.getpid()),
        "utime_seconds": float(usage.ru_utime),
        "stime_seconds": float(usage.ru_stime),
        "cpu_seconds": float(usage.ru_utime + usage.ru_stime),
        "max_rss": int(usage.ru_maxrss),
        "observed_at_utc": _now(),
    }


def _children_rusage_snapshot(scope: str) -> dict[str, Any]:
    """Capture the raw waited-child counter without adding it to accounting."""
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return {
        "scope": scope,
        "source": "resource.RUSAGE_CHILDREN",
        "utime_seconds": float(usage.ru_utime),
        "stime_seconds": float(usage.ru_stime),
        "cpu_seconds": float(usage.ru_utime + usage.ru_stime),
        "observed_at_utc": _now(),
    }


def _children_rusage_interval(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    """Return raw before/after totals and their disjoint waited-child delta."""
    delta = {
        key: float(after.get(key, 0.0) or 0.0) - float(before.get(key, 0.0) or 0.0)
        for key in ("utime_seconds", "stime_seconds", "cpu_seconds")
    }
    return {
        "before_launch": dict(before),
        "after_final_reap": dict(after),
        "delta": delta,
        "scope": "target child Popen through real wait and final owned-tree reap; no posthash",
        "other_child_processes_expected": False,
    }


def _job_path(job_id: str) -> Path:
    _safe_id(job_id, "job_id")
    if not job_id.startswith(NAMESPACE):
        raise LFD01Error("job_id must use LFD01_ namespace")
    _assert_nas_path(JOB_ROOT)
    return JOB_ROOT / job_id


def _job_checkpoint(job_dir: Path) -> Path:
    return job_dir / "checkpoint.json"


def _job_guardian_state(job_dir: Path) -> Path:
    return job_dir / "guardian-state.json"


def _job_worker_event(job_dir: Path) -> Path:
    return job_dir / "worker-event.json"


def _job_infrastructure(job_dir: Path) -> Path:
    return job_dir / "infrastructure-ownership.json"


def _job_infrastructure_lock(job_dir: Path) -> Path:
    return job_dir / "infrastructure-ownership.lock"


def _update_infrastructure(job_dir: Path, updates: Mapping[str, Any]) -> dict[str, Any]:
    """Merge one infrastructure record while serializing guardian/controller writers."""
    lock_path = _job_infrastructure_lock(job_dir)
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            current = (_read_json(_job_infrastructure(job_dir), "infrastructure ownership", max_bytes=256 * 1024)
                       if _job_infrastructure(job_dir).exists() else {})
            if not isinstance(current, dict):
                raise LFD01Error("infrastructure ownership record is not an object")
            value = {**current, **dict(updates)}
            _atomic_json(_job_infrastructure(job_dir), value)
            return value
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _owned_group_source(job_dir: Path, runtime_state: Mapping[str, Any] | None = None) -> dict[str, Any]:
    source: dict[str, Any] = {}
    runtime_record: Mapping[str, Any] = {}
    launch = job_dir / "owned-child-launch.json"
    if launch.exists():
        try:
            source.update(_read_json(launch, "owned child launch", max_bytes=256 * 1024))
        except LFD01Error:
            pass
    # A crash can occur after Popen and the first worker-runtime atomic write
    # but before owned-child-launch.json.  Recover that durable state as a
    # second source; never infer ownership from a live numeric PID/PGID alone.
    runtime_path = job_dir / "worker-runtime.json"
    if runtime_path.exists():
        try:
            value = _read_json(runtime_path, "worker runtime", max_bytes=2 * MIB)
            runtime_record = value if isinstance(value, Mapping) else {}
            if isinstance(runtime_record, Mapping):
                if source.get("owned_child") is None and runtime_record.get("owned_child") is not None:
                    source["owned_child"] = runtime_record.get("owned_child")
                if source.get("owned_group") is None and runtime_record.get("owned_group") is not None:
                    source["owned_group"] = runtime_record.get("owned_group")
        except LFD01Error:
            pass
    if isinstance(runtime_state, Mapping):
        if runtime_state.get("owned_child") is not None:
            source["owned_child"] = runtime_state.get("owned_child")
        if runtime_state.get("owned_group") is not None:
            source["owned_group"] = runtime_state.get("owned_group")
    group = source.get("owned_group")
    proof_meta = runtime_state.get("parent_proof") if isinstance(runtime_state, Mapping) else None
    if not isinstance(proof_meta, Mapping):
        proof_meta = runtime_record.get("parent_proof") if isinstance(runtime_record, Mapping) else None
    if isinstance(group, Mapping) and group.get("parent_proof") is None and isinstance(proof_meta, Mapping):
        proof_path = job_dir / PARENT_PROOF_FILENAME
        try:
            if (not proof_path.is_symlink() and proof_path.is_file()
                    and proof_path.stat().st_size <= PARENT_PROOF_MAX_BYTES):
                value = json.loads(proof_path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_pairs)
                token = value.get("token") if isinstance(value, Mapping) else None
                token_sha = proof_meta.get("token_sha256")
                if isinstance(token, str) and isinstance(token_sha, str) and _proof_token_sha256(token) == token_sha:
                    proof = _valid_parent_proof(
                        value, token=token, expected_parent=group.get("leader", {}),
                        expected_pgid=int(group.get("pgid", 0) or 0),
                    ) if isinstance(value, Mapping) else None
                    if proof is not None:
                        copied = deepcopy(dict(group))
                        known = list(copied.get("known_members", [])) if isinstance(copied.get("known_members"), list) else []
                        if _identity_key(proof["child_identity"]) not in {_identity_key(item) for item in known}:
                            known.append(dict(proof["child_identity"]))
                        copied["known_members"] = known
                        copied["parent_proof"] = proof
                        source["owned_group"] = copied
        except (OSError, PermissionError, ValueError, TypeError, LFD01Error):
            pass
    return source


def _terminate_spawned_process(process: subprocess.Popen[str], *, reason: str) -> dict[str, Any]:
    """Synchronously stop one just-launched Popen when ownership is unproven.

    A process handle is the only safe cleanup primitive before the durable
    group identity has been persisted.  This path deliberately does not call
    killpg: a numeric PGID without a durable PID/start_ticks proof could now
    name an unrelated process group.
    """
    result: dict[str, Any] = {
        "status": "direct_process_cleanup",
        "reason": reason,
        "pid": int(process.pid),
        "identity_uncertain": True,
        "confirmed_exit": False,
    }
    try:
        if process.poll() is None:
            process.terminate()
    except (OSError, ProcessLookupError):
        pass
    try:
        process.wait(timeout=GROUP_GRACE_SECONDS)
        result.update(status="terminated", confirmed_exit=True, forced_kill=False,
                      returncode=process.returncode)
        return result
    except subprocess.TimeoutExpired:
        pass
    except (OSError, ProcessLookupError):
        if process.poll() is not None:
            result.update(status="terminated", confirmed_exit=True, forced_kill=False,
                          returncode=process.returncode)
            return result
    try:
        process.kill()
    except (OSError, ProcessLookupError):
        pass
    try:
        process.wait(timeout=GROUP_GRACE_SECONDS)
        result.update(status="terminated", confirmed_exit=True, forced_kill=True,
                      returncode=process.returncode)
    except (subprocess.TimeoutExpired, OSError, ProcessLookupError):
        result.update(status="direct_process_exit_unconfirmed", forced_kill=True)
    return result


def _terminate_verified_owned_group(job_dir: Path, checkpoint: Mapping[str, Any] | None = None, *, reason: str = "guardian_cleanup") -> dict[str, Any]:
    runtime_state = checkpoint.get("runtime_state", {}) if isinstance(checkpoint, Mapping) else {}
    source = _owned_group_source(job_dir, runtime_state)
    group = source.get("owned_group")
    if not isinstance(group, dict):
        return {"status": "no_owned_group", "reason": reason, "confirmed_exit": True, "confirmed_exit_at_utc": _now()}
    if group.get("host") != socket.gethostname() or group.get("boot_id") != _boot_id():
        return {"status": "identity_mismatch", "reason": reason, "confirmed_exit": False}
    pgid = int(group.get("pgid", 0) or 0)
    if pgid <= 0:
        return {"status": "invalid_pgid", "reason": reason, "confirmed_exit": False}
    snapshot = _owned_group_snapshot(group)
    if snapshot.get("identity_mismatch") or snapshot.get("identity_unverified_members"):
        return {"status": "identity_unverified", "pgid": pgid, "reason": reason,
                "confirmed_exit": False,
                "unverified_members": snapshot.get("identity_unverified_members", [])}
    if not snapshot.get("members") and not snapshot.get("exited_members"):
        return {"status": "already_exited", "pgid": pgid, "reason": reason,
                "confirmed_exit": True, "confirmed_exit_at_utc": _now()}
    try:
        os.killpg(pgid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        pass
    deadline = time.monotonic() + GROUP_GRACE_SECONDS
    while time.monotonic() < deadline:
        current = _owned_group_snapshot(group)
        if current.get("identity_mismatch") or current.get("identity_unverified_members"):
            return {"status": "identity_unverified", "pgid": pgid, "reason": reason,
                    "confirmed_exit": False,
                    "unverified_members": current.get("identity_unverified_members", [])}
        if not current.get("members") and not current.get("exited_members"):
            return {"status": "terminated", "pgid": pgid, "reason": reason,
                    "confirmed_exit": True, "confirmed_exit_at_utc": _now(), "forced_kill": False}
        time.sleep(0.05)
    # Revalidate the live leader/member start identities immediately before a
    # forced group kill; a reused PGID is never an ownership proof.
    current = _owned_group_snapshot(group)
    if current.get("identity_mismatch") or current.get("identity_unverified_members"):
        return {"status": "identity_unverified", "pgid": pgid, "reason": reason,
                "confirmed_exit": False,
                "unverified_members": current.get("identity_unverified_members", [])}
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass
    deadline = time.monotonic() + GROUP_GRACE_SECONDS
    while time.monotonic() < deadline:
        current = _owned_group_snapshot(group)
        if current.get("identity_mismatch") or current.get("identity_unverified_members"):
            return {"status": "identity_unverified", "pgid": pgid, "reason": reason,
                    "confirmed_exit": False,
                    "unverified_members": current.get("identity_unverified_members", [])}
        if not current.get("members") and not current.get("exited_members"):
            return {"status": "terminated", "pgid": pgid, "reason": reason,
                    "confirmed_exit": True, "confirmed_exit_at_utc": _now(), "forced_kill": True}
        time.sleep(0.05)
    return {"status": "owned_group_exit_unconfirmed", "pgid": pgid, "reason": reason,
            "confirmed_exit": False, "forced_kill": True}


def _update_runtime_state(job_dir: Path, runtime_state: dict[str, Any], state_lock: threading.Lock,
                          entry_cpu: float, *, worker_alive: bool = True) -> dict[str, Any]:
    with state_lock:
        group = runtime_state.get("owned_group")
        snapshot = (_owned_group_snapshot(group) if isinstance(group, dict)
                    else {"members": [], "exited_members": [], "verified_members": [],
                          "identity_unverified_members": [], "verified_member_proofs": [],
                          "cpu_seconds": 0.0, "rss_bytes": 0})
        if isinstance(group, dict):
            known = list(group.get("known_members", [])) if isinstance(group.get("known_members"), list) else []
            known_keys = {_identity_key(value) for value in known}
            for member in snapshot.get("verified_members", []):
                key = _identity_key(member)
                if key is not None and key not in known_keys:
                    known.append(dict(member))
                    known_keys.add(key)
            group["known_members"] = known
            snapshot["known_members_count"] = len(known)
        worker_stat = _proc_stat(os.getpid()) or {}
        worker_rss = int(worker_stat.get("rss_bytes", 0) or 0)
        snapshot["worker_rss_bytes"] = worker_rss
        base_cpu = max(0.0, _cpu_usage() - entry_cpu)
        # RUSAGE_CHILDREN covers every reaped descendant. Add /proc CPU only
        # while the group is live, when descendants cannot yet be in rusage.
        trusted = base_cpu + (float(snapshot.get("cpu_seconds", 0.0)) if snapshot.get("members") else 0.0)
        runtime_state["last_trusted_cpu_seconds"] = max(float(runtime_state.get("last_trusted_cpu_seconds", 0.0) or 0.0), trusted)
        runtime_state["last_trusted_at_utc"] = _now()
        runtime_state["owned_group_snapshot"] = snapshot
        aggregate_rss = worker_rss + int(snapshot.get("rss_bytes", 0) or 0)
        runtime_state["worker_rss_bytes"] = worker_rss
        runtime_state["peak_rss_bytes"] = max(int(runtime_state.get("peak_rss_bytes", 0) or 0), aggregate_rss)
        if (runtime_state.get("owned_child") is not None and not snapshot.get("members")
                and not snapshot.get("identity_unverified_members")
                and not snapshot.get("identity_mismatch")):
            runtime_state["child_exit_confirmed"] = True
            runtime_state.setdefault("child_exit_at_utc", _now())
        # Return an independent snapshot.  Nested group/identity lists must
        # not be mutated by the next heartbeat while this snapshot is copied
        # into worker-runtime.json and checkpoint.json under the state lock.
        value = deepcopy(runtime_state)
        # Keep serialization and replacement inside the same state lock as the
        # snapshot mutation.  The RSS watchdog and heartbeat therefore cannot
        # read/modify/write this record concurrently.
        _atomic_json(job_dir / "worker-runtime.json", value)
        checkpoint = _job_checkpoint(job_dir)
        if checkpoint.exists():
            current = _read_json(checkpoint, "job checkpoint", max_bytes=2 * MIB)
            current.update({
                "schema": "lfd01.job-checkpoint.v2",
                "updated_at_utc": _now(),
                "worker_cpu_seconds": float(value.get("last_trusted_cpu_seconds", 0.0) or 0.0),
                "last_trusted_cpu_seconds": float(value.get("last_trusted_cpu_seconds", 0.0) or 0.0),
                "last_trusted_at_utc": value.get("last_trusted_at_utc"),
                "children_rusage_interval": value.get("children_rusage_interval"),
                "runtime_state": value,
                "worker_alive": bool(worker_alive),
                "worker_identity": _checkpoint_identity(os.getpid()),
            })
            _atomic_json(checkpoint, current)
    return value


def _heartbeat(job_dir: Path, request: Mapping[str, Any], stop: threading.Event, entry_cpu: float,
               runtime_state: dict[str, Any], state_lock: threading.Lock) -> None:
    while not stop.wait(CHECKPOINT_INTERVAL):
        try:
            _update_runtime_state(job_dir, runtime_state, state_lock, entry_cpu)
        except (OSError, LFD01Error, ValueError):
            continue


def _cpu_usage() -> float:
    own = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    return own.ru_utime + own.ru_stime + children.ru_utime + children.ru_stime


def _watchdog(max_wall: float, done: threading.Event, job_dir: Path, runtime_state: dict[str, Any], state_lock: threading.Lock) -> threading.Thread:
    def kill_group() -> None:
        if done.is_set():
            return
        try:
            _update_runtime_state(job_dir, runtime_state, state_lock, float(runtime_state.get("entry_cpu_seconds", 0.0) or 0.0))
            cleanup = _terminate_verified_owned_group(job_dir, {"runtime_state": runtime_state}, reason="worker_hard_deadline")
            # The guardian is the sole writer of guardian-state.json.  Keep a
            # worker-local event beside it so a watchdog cannot race the
            # guardian's read/modify/write evidence record.
            _atomic_json(_job_worker_event(job_dir), {
                "schema": "lfd01.worker-event.v1", "event": "hard_deadline_cleanup",
                "observed_at_utc": _now(), "owned_group_cleanup": cleanup,
            })
        except (OSError, LFD01Error, ValueError):
            pass
        # The worker may have completed while cleanup was running.  Never
        # deliver a late self/group signal after normal terminal finalization.
        if done.is_set():
            return
        try:
            if os.getpgid(0) == os.getpid():
                os.killpg(os.getpid(), signal.SIGTERM)
            else:
                os.kill(os.getpid(), signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass
    thread = threading.Timer(float(max_wall), kill_group)
    thread.daemon = True
    thread.start()
    return thread


def _storage_watchdog(done: threading.Event) -> threading.Thread:
    """Stop the owned worker if either device loses its admission floor."""
    def check() -> None:
        while not done.wait(5.0):
            try:
                _assert_parent_data_root()
                if _home_free_bytes() < HOME_MIN_FREE or _nas_free_bytes() < NAS_MIN_FREE:
                    if done.is_set():
                        return
                    os.kill(os.getpid(), signal.SIGTERM)
                    return
            except (OSError, LFD01Error):
                if done.is_set():
                    return
                os.kill(os.getpid(), signal.SIGTERM)
                return
    thread = threading.Thread(target=check, name="lfd01-storage-watchdog", daemon=True)
    thread.start()
    return thread


def _rss_watchdog(done: threading.Event, request: Mapping[str, Any], job_dir: Path,
                  runtime_state: dict[str, Any], state_lock: threading.Lock) -> threading.Thread:
    """Enforce the aggregate owned-tree RSS budget independently of RLIMIT_AS."""
    def check() -> None:
        while not done.wait(0.2):
            try:
                state = _update_runtime_state(job_dir, runtime_state, state_lock,
                                              float(runtime_state.get("entry_cpu_seconds", 0.0) or 0.0))
                if int(state.get("peak_rss_bytes", 0) or 0) > int(request["ram_limit_bytes"]):
                    # Merge the flag and cleanup result into the live shared
                    # state under the same lock as the fresh snapshot.  Do
                    # not write the shallow copy returned before heartbeat or
                    # another watchdog can update the record.
                    with state_lock:
                        cleanup_source = deepcopy(runtime_state)
                        runtime_state["rss_limit_exceeded"] = True
                    cleanup = _terminate_verified_owned_group(
                        job_dir, {"runtime_state": cleanup_source}, reason="owned_tree_rss_limit"
                    )
                    with state_lock:
                        runtime_state["rss_limit_exceeded"] = True
                        runtime_state["owned_group_cleanup"] = cleanup
                        _atomic_json(job_dir / "worker-runtime.json", dict(runtime_state))
                    if done.is_set():
                        return
                    os.kill(os.getpid(), signal.SIGTERM)
                    return
            except (OSError, LFD01Error, ValueError):
                if done.is_set():
                    return
                os.kill(os.getpid(), signal.SIGTERM)
                return
    thread = threading.Thread(target=check, name="lfd01-rss-watchdog", daemon=True)
    thread.start()
    return thread


@contextmanager
def _temporary_compiled_solver_constant(request: Mapping[str, Any]) -> Iterator[None]:
    """Temporarily project one attested executable into immutable v2.SOLVER.

    v2's positive GenCase/3-D, GPU-peak, and ``-cpu`` checks are deliberately
    retained by changing only the in-process constant during the one v6 call.
    No source file, official binary, request, or receipt is edited.  The old
    constant is restored even when validation, reservation, launch, or the
    target exits with an error.
    """
    if not _is_compiled_binary_request(request):
        yield
        return
    if not isinstance(request.get("_compiled_attestation_checked"), dict):
        raise LFD01Error("compiled solver constant cannot be projected before attestation")
    v6 = _import_v6_runtime()
    base = v6.base
    saved_solver = base.SOLVER
    approved = COMPILED_BINARY_PATH
    try:
        base.SOLVER = approved
        yield
    finally:
        base.SOLVER = saved_solver


def _run_v6(
    request_path: Path, request: Mapping[str, Any], grant: Mapping[str, Any], *, data_root: Path, job_dir: Path,
    adoption_sha256: str, baseline_sha256: str, subreaper_enabled: bool,
) -> dict[str, Any]:
    v6 = _import_v6_runtime()
    deferred_state: dict[str, Any] = {"launch": None, "after": None}
    g2_state: dict[str, Any] = {"launch": request.get("g2_approval") if request.get("kind") == "production" else None,
                                "terminal": "not_required"}
    runtime_state: dict[str, Any] = {
        "schema": "lfd01.worker-runtime.v2", "owned_child": None, "owned_group": None,
        "owned_group_snapshot": {"members": [], "exited_members": [], "verified_members": [],
                                  "identity_unverified_members": [], "verified_member_proofs": [],
                                  "cpu_seconds": 0.0, "rss_bytes": 0},
        "last_trusted_cpu_seconds": 0.0, "last_trusted_at_utc": None,
        "child_exit_at_utc": None, "child_exit_confirmed": False, "peak_rss_bytes": 0,
        "children_rusage_interval": None,
        "posthash": {"attempted": False, "status": "pending"},
        "compiled_binary_reservation_admitted": False,
        "compiled_binary_observations": None,
        "unreaped_branch_unknown": False, "unreaped_branch_unknown_interval": None,
        "subreaper_enabled": bool(subreaper_enabled),
        "parent_proof": None,
        "terminal_settlement_blocked": None,
        "worker_metadata_fsize_soft_bytes": 0, "worker_metadata_fsize_hard_bytes": 0,
        "child_fsize_soft_bytes": 0, "child_fsize_hard_bytes": 0,
    }
    if not subreaper_enabled:
        # The worker calls PR_SET_CHILD_SUBREAPER before entering this
        # function.  Fail closed before starting the v6 child hook, so no
        # target Popen can run without disjoint adopted-descendant accounting.
        raise LFD01Error("Linux child subreaper could not be enabled before target Popen")
    state_lock = threading.Lock()
    done = threading.Event()
    entry_cpu = _cpu_usage()
    runtime_state["entry_cpu_seconds"] = entry_cpu
    # Apply worker metadata limits before any heartbeat/storage/RSS threads
    # exist.  The scientific child receives its own output limit at launch.
    worker_fsize_soft, worker_fsize_hard = _set_process_limits(request, scope="worker")
    runtime_state["worker_metadata_fsize_limit_bytes"] = worker_fsize_soft
    runtime_state["worker_metadata_fsize_soft_bytes"] = worker_fsize_soft
    runtime_state["worker_metadata_fsize_hard_bytes"] = worker_fsize_hard
    runtime_state["child_fsize_limit_bytes"] = _child_fsize_limit(request)
    runtime_state["child_fsize_soft_bytes"] = 0
    runtime_state["child_fsize_hard_bytes"] = 0
    _write_runtime_state(job_dir, runtime_state, state_lock)
    heartbeat = threading.Thread(target=_heartbeat, args=(job_dir, request, done, entry_cpu, runtime_state, state_lock), daemon=True)
    heartbeat.start()
    watchdog = _watchdog(float(request["max_wall_seconds"]), done, job_dir, runtime_state, state_lock)
    storage_watchdog = _storage_watchdog(done)
    rss_watchdog = _rss_watchdog(done, request, job_dir, runtime_state, state_lock)
    try:
        with _temporary_compiled_solver_constant(request):
            with _v6_bindings(
                request, request_path, deferred_state=deferred_state, g2_state=g2_state,
                runtime_state=runtime_state, state_lock=state_lock, grant=grant,
                job_dir=job_dir, expected_adoption_sha256=adoption_sha256,
                expected_baseline_sha256=baseline_sha256,
            ):
                result = v6.run_request(request_path, data_root=data_root)
        return result
    finally:
        done.set()
        watchdog.cancel()
        # Cancellation only prevents a not-yet-started Timer callback.  Join
        # every watcher so no heartbeat/RSS/storage write or late signal can
        # occur after the terminal CPU/state update.
        watchdog.join()
        heartbeat.join()
        storage_watchdog.join()
        rss_watchdog.join()
        _update_runtime_state(job_dir, runtime_state, state_lock, entry_cpu, worker_alive=False)


def worker(request_path: Path, grant_path: Path, *, job_id: str) -> dict[str, Any]:
    # This must precede every possible target Popen in the worker, including
    # any subprocess created by the consumed v6 runtime during the request.
    subreaper_enabled = _enable_subreaper()
    request_path = _regular_path(request_path, "worker request")
    grant_path = _regular_path(grant_path, "worker grant")
    request, grant, adoption, baseline = _validate_request_grant(
        request_path, grant_path, actual_job_id=job_id
    )
    job_dir = _job_path(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    _atomic_json(_job_checkpoint(job_dir), {
        "schema": "lfd01.job-checkpoint.v2",
        "job_id": job_id,
        "attempt_id": _attempt_id(request),
        "request_path": str(request_path),
        "grant_path": str(grant_path),
        "grant_sha256": _sha256(grant_path),
        "parent_data_root": str(PARENT_DATA_ROOT),
        "adoption_sha256": _sha256(ADOPTION_PATH),
        "baseline_sha256": _sha256(BASELINE_PATH),
        "worker_identity": _checkpoint_identity(os.getpid()),
        "subreaper_enabled_before_worker_popen": bool(subreaper_enabled),
        "worker_started_at_utc": _now(),
        "worker_cpu_seconds": 0.0,
        "cpu_threads": int(request["cpu_threads"]),
        "max_wall_seconds": float(request["max_wall_seconds"]),
        "reservation_id": _attempt_id(request),
        "state": "starting",
        "guardian_state_path": str(_job_guardian_state(job_dir)),
        "owned_child_launch_path": str(job_dir / "owned-child-launch.json"),
    })
    try:
        result = _run_v6(
            request_path, request, grant, data_root=PARENT_DATA_ROOT, job_dir=job_dir,
            adoption_sha256=_sha256(ADOPTION_PATH),
            baseline_sha256=_sha256(BASELINE_PATH),
            subreaper_enabled=subreaper_enabled,
        )
        state = "completed" if result.get("status") == "completed" else "failed"
        current = _read_json(_job_checkpoint(job_dir), "worker checkpoint", max_bytes=2 * MIB)
        _atomic_json(_job_checkpoint(job_dir), {
            **current,
            "state": state,
            "worker_alive": False,
            "finished_at_utc": _now(),
            "result": result,
        })
        return result
    except BaseException as error:
        current = _read_json(_job_checkpoint(job_dir), "worker checkpoint", max_bytes=2 * MIB) if _job_checkpoint(job_dir).exists() else {}
        _atomic_json(_job_checkpoint(job_dir), {
            **current, "state": "worker_exception", "worker_alive": False,
            "finished_at_utc": _now(), "error": f"{type(error).__name__}: {error}",
        })
        raise


def _settle_orphan(job_dir: Path, checkpoint: Mapping[str, Any]) -> dict[str, Any]:
    attempt = checkpoint.get("reservation_id")
    if not _is_lfd_attempt(attempt):
        raise LFD01Error("recovery checkpoint has no LFD-01 reservation identity")
    deadline_hint: str | None = None
    try:
        started_hint = datetime.fromisoformat(str(checkpoint.get("worker_started_at_utc")))
        if started_hint.tzinfo is None:
            started_hint = started_hint.replace(tzinfo=timezone.utc)
        deadline_hint = (started_hint + timedelta(
            seconds=max(0.0, float(checkpoint.get("max_wall_seconds", 0) or 0))
        )).isoformat()
    except (TypeError, ValueError, OverflowError):
        deadline_hint = None
    # guardian has already waited the worker before entering recovery.  If the
    # worker's subreaper descendants were adopted by guardian, reap only this
    # process's exited children before/after the verified group cleanup; a
    # separate root recover process has no waitable relationship and therefore
    # cannot accidentally reap another job.
    owned_source = _owned_group_source(
        job_dir,
        checkpoint.get("runtime_state", {}) if isinstance(checkpoint.get("runtime_state"), Mapping) else {},
    )
    owned_group = owned_source.get("owned_group")
    pre_reaped = _reap_owned_descendants(owned_group) if isinstance(owned_group, Mapping) else 0
    cleanup = _terminate_verified_owned_group(job_dir, checkpoint, reason="orphan_recovery")
    post_reaped = _reap_owned_descendants(owned_group) if isinstance(owned_group, Mapping) else 0
    final_reap = (_final_reap_owned_descendants(owned_group, timeout=0.0)
                  if isinstance(owned_group, Mapping) else {"reaped": 0, "completed": False})
    if pre_reaped or post_reaped:
        cleanup = {**cleanup, "guardian_reaped_before": pre_reaped, "guardian_reaped_after": post_reaped}
    if isinstance(owned_group, Mapping):
        cleanup = {**cleanup, "final_reap": {
            "reaped": int(final_reap.get("reaped", 0) or 0),
            "completed": bool(final_reap.get("completed", False)),
            "snapshot": final_reap.get("snapshot"),
        }}
        if not final_reap.get("completed"):
            # A prior group snapshot may have looked empty, but proof-only
            # final reap is the settlement boundary.  A zombie, unverified
            # member, or transient reap failure always revokes confirmation.
            cleanup.update(status="owned_group_reap_unconfirmed", confirmed_exit=False)
        elif not cleanup.get("confirmed_exit"):
            cleanup.update(status="reaped_after_group_cleanup", confirmed_exit=True,
                           confirmed_exit_at_utc=_now())
    if cleanup.get("status") == "no_owned_group" and owned_source.get("owned_child") is not None:
        # Popen was durably observed but its group identity was never
        # persisted.  Treat that as an unresolved ownership boundary instead
        # of releasing the reservation on a false "no group" conclusion.
        cleanup = {
            "status": "owned_group_identity_unavailable",
            "reason": "orphan_recovery",
            "confirmed_exit": False,
        }
    _assert_parent_data_root()
    adoption, baseline, adoption_sha256, baseline_sha256 = _authority()
    if checkpoint.get("adoption_sha256") != adoption_sha256 or checkpoint.get("baseline_sha256") != baseline_sha256:
        raise LFD01Error("recovery checkpoint authority no longer matches active LFD-01 adoption")
    with _import_v6_runtime().ledger_locked(PARENT_DATA_ROOT) as ledger:
        _verify_history(ledger, adoption, baseline)
        rows = [row for row in ledger.get("reservations", []) if row.get("id") == attempt]
        if not rows:
            prior_charges = [row for row in ledger.get("charges", []) if row.get("id") == attempt]
            if prior_charges:
                # A prior terminal writer already consumed this attempt.  Do
                # not report ``not_registered`` or append a second charge;
                # v11 blocks this path while an owned tree is unconfirmed,
                # while this branch remains an explicit audit result for old
                # candidate receipts and controller retries.
                return {"status": "already_settled", "attempt_id": attempt,
                        "reservation_found": False, "charge_found": True,
                        "prior_charge": dict(prior_charges[-1]),
                        "charge_written": False, "duplicate_charge": True}
            # A reservation append can fail before the locked parent ledger
            # rewrite (for example RLIMIT_FSIZE).  This is not evidence of a
            # prior charge or successful settlement.
            return {"status": "not_registered", "attempt_id": attempt,
                    "reservation_found": False, "charge_written": False,
                    "duplicate_charge": False}
        reservation = dict(rows[0])
        def parse_time(value: Any) -> datetime | None:
            try:
                parsed = datetime.fromisoformat(str(value))
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                return None

        reserved_at = parse_time(reservation.get("reserved_at_utc")) or parse_time(checkpoint.get("worker_started_at_utc")) or datetime.now(timezone.utc)
        max_wall = float(reservation.get("lfd01_max_wall_seconds", checkpoint.get("max_wall_seconds", 0)) or 0)
        hard_deadline = reserved_at.timestamp() + max(0.0, max_wall)
        guardian_state: Mapping[str, Any] = {}
        if _job_guardian_state(job_dir).exists():
            try:
                guardian_state = _read_json(_job_guardian_state(job_dir), "guardian state", max_bytes=2 * MIB)
            except LFD01Error:
                guardian_state = {}
        runtime = checkpoint.get("runtime_state", {}) if isinstance(checkpoint.get("runtime_state"), dict) else {}
        trusted_at = parse_time(checkpoint.get("last_trusted_at_utc") or runtime.get("last_trusted_at_utc"))
        trusted_cpu = min(float(reservation.get("cpu_core_seconds", 0) or 0),
                          max(0.0, float(checkpoint.get("last_trusted_cpu_seconds", runtime.get("last_trusted_cpu_seconds", 0)) or 0)))
        # ``child_exit_at_utc`` is written even when final_reap reports an
        # unresolved member.  It is a process-wait observation, not a safe
        # settlement boundary; use it only with the explicit confirmation
        # flag, otherwise end the unknown interval at verified cleanup or the
        # hard deadline.
        runtime_exit_confirmed = bool(
            runtime.get("child_exit_confirmed", checkpoint.get("child_exit_confirmed", False))
        )
        confirmed_candidates: list[Any] = []
        if cleanup.get("confirmed_exit"):
            confirmed_candidates.append(cleanup.get("confirmed_exit_at_utc"))
            if runtime_exit_confirmed:
                confirmed_candidates.extend([checkpoint.get("child_exit_at_utc"), runtime.get("child_exit_at_utc")])
            confirmed_candidates.append(guardian_state.get("confirmed_exit_at_utc"))
        confirmed_at = next((parsed for parsed in (parse_time(item) for item in confirmed_candidates) if parsed is not None), None)
        now_dt = datetime.now(timezone.utc)
        if not cleanup.get("confirmed_exit"):
            if now_dt.timestamp() < hard_deadline:
                return {"status": "recovery_waiting_for_owned_exit", "attempt_id": attempt,
                        "owned_group_cleanup": cleanup, "hard_deadline_utc": datetime.fromtimestamp(hard_deadline, timezone.utc).isoformat(),
                        "duplicate_charge": False}
            interval_start = trusted_at or reserved_at
            deadline_at = datetime.fromtimestamp(hard_deadline, timezone.utc)
            unknown_seconds_upper = max(0.0, hard_deadline - interval_start.timestamp())
            threads = int(reservation.get("cpu_threads", checkpoint.get("cpu_threads", 1)) or 1)
            reserved_cpu = float(reservation.get("cpu_core_seconds", 0) or 0)
            unknown_cpu_upper = min(max(0.0, reserved_cpu - trusted_cpu), threads * unknown_seconds_upper)
            result = {
                "status": "recovery_waiting_for_owned_exit",
                "attempt_id": attempt,
                "owned_group_cleanup": cleanup,
                "hard_deadline_utc": deadline_at.isoformat(),
                "hard_deadline_reached": True,
                "failure_status": "failed_recovered_unknown",
                "unknown_cpu_upper_seconds": unknown_cpu_upper,
                "trusted_cpu_seconds": trusted_cpu,
                "unknown_interval_start_utc": interval_start.isoformat(),
                "unknown_interval_end_utc": deadline_at.isoformat(),
                "unknown_interval_seconds": unknown_seconds_upper,
                "bounded_by_reserved_cpu_core_seconds": reservation.get("cpu_core_seconds", 0),
                "reservation_retained": True,
                "lease_retained": True,
                "slot_retained": True,
                "duplicate_charge": False,
            }
            _atomic_json(job_dir / "recovery-settlement.json", {
                "schema": "lfd01.recovery-settlement.v2",
                "attempt_id": attempt,
                "status": "failed_recovered_unknown",
                "settlement_deferred_until_owned_exit_confirmation": True,
                "failure": result,
                "observed_at_utc": _now(),
            })
            return result
        if confirmed_at is None and now_dt.timestamp() < hard_deadline:
            return {"status": "recovery_waiting_for_owned_exit", "attempt_id": attempt,
                    "owned_group_cleanup": cleanup, "hard_deadline_utc": datetime.fromtimestamp(hard_deadline, timezone.utc).isoformat(),
                    "duplicate_charge": False}
        interval_start = trusted_at or reserved_at
        interval_end = confirmed_at or datetime.fromtimestamp(hard_deadline, timezone.utc)
        if interval_end.timestamp() > hard_deadline:
            interval_end = datetime.fromtimestamp(hard_deadline, timezone.utc)
        unknown_seconds = max(0.0, interval_end.timestamp() - interval_start.timestamp())
        threads = int(reservation.get("cpu_threads", checkpoint.get("cpu_threads", 1)) or 1)
        reserved_cpu = float(reservation.get("cpu_core_seconds", 0) or 0)
        unknown_cpu = min(max(0.0, reserved_cpu - trusted_cpu), threads * unknown_seconds)
        charged_cpu = min(float(reservation.get("cpu_core_seconds", 0)), trusted_cpu + unknown_cpu)
        charged_gpu = min(float(reservation.get("gpu_seconds", 0) or 0), max(0.0, interval_end.timestamp() - reserved_at.timestamp()))
        output = NAS_RUNS / attempt
        storage = int(reservation.get("new_storage_bytes", 0) or 0)
        if output.exists():
            try:
                storage = max(storage, int(_import_v6_runtime().base.tree_bytes(output)))
            except (OSError, RuntimeError):
                storage = int(reservation.get("new_storage_bytes", 0) or 0)
        finished = _now()
        ledger["reservations"] = [row for row in ledger.get("reservations", []) if row.get("id") != attempt]
        ledger.setdefault("charges", []).append({
            "id": attempt,
            "campaign_id": "LFD-01",
            "namespace": NAMESPACE,
            "lfd01_namespace": NAMESPACE,
            "pool": reservation.get("pool"),
            "tranche_id": reservation.get("tranche_id"),
            "stage": reservation.get("stage"),
            "purpose": reservation.get("purpose"),
            "kind": reservation.get("kind", checkpoint.get("kind", "cpu")),
            "gpu_seconds": charged_gpu,
            "cpu_core_seconds": charged_cpu,
            "new_storage_bytes": storage,
            "output_storage": "lfd01_nas",
            "status": "failed_recovered_unknown",
            "finished_at_utc": finished,
            "recovery": {
                "schema": "lfd01.recovery-settlement.v1",
                "unknown_cpu_seconds": unknown_cpu,
                "trusted_cpu_seconds": trusted_cpu,
                "unknown_interval_start_utc": interval_start.isoformat(),
                "unknown_interval_end_utc": interval_end.isoformat(),
                "unknown_interval_seconds": unknown_seconds,
                "hard_deadline_utc": datetime.fromtimestamp(hard_deadline, timezone.utc).isoformat(),
                "bounded_by_reserved_cpu_core_seconds": reservation.get("cpu_core_seconds", 0),
                "owned_group_cleanup": cleanup,
                "worker_exit_observed_without_terminal_receipt": True,
            },
        })
        for row in ledger.get("attempts", []):
            if row.get("id") == attempt:
                row.update(status="failed_recovered_unknown", finished_at_utc=finished,
                           recovery_unknown_segment=True)
        leases = PARENT_DATA_ROOT / "leases"
        for path in leases.glob("*.json"):
            try:
                value = _read_json(path, "lease", max_bytes=64 * 1024)
                if value.get("attempt_id") == attempt:
                    path.unlink(missing_ok=True)
            except (OSError, LFD01Error):
                continue
        result = {"status": "settled_unknown", "attempt_id": attempt,
                  "charged_cpu_core_seconds": charged_cpu, "unknown_cpu_seconds": unknown_cpu,
                  "charged_gpu_seconds": charged_gpu, "storage_bytes": storage,
                  "unknown_interval_start_utc": interval_start.isoformat(),
                  "unknown_interval_end_utc": interval_end.isoformat(),
                  "hard_deadline_utc": datetime.fromtimestamp(hard_deadline, timezone.utc).isoformat(),
                  "owned_group_cleanup": cleanup, "duplicate_charge": False}
    _atomic_json(job_dir / "recovery-settlement.json", result)
    return result


def recover(job_id: str) -> dict[str, Any]:
    job_dir = _job_path(job_id)
    checkpoint_path = _job_checkpoint(job_dir)
    if not checkpoint_path.exists():
        raise LFD01Error("job checkpoint does not exist")
    checkpoint = _read_json(checkpoint_path, "job checkpoint", max_bytes=2 * MIB)
    guardian_state = {}
    if _job_guardian_state(job_dir).exists():
        try:
            guardian_state = _read_json(_job_guardian_state(job_dir), "guardian state", max_bytes=2 * MIB)
        except LFD01Error:
            guardian_state = {}
    identity = checkpoint.get("worker_identity", {})
    pid = int(identity.get("pid", 0) or 0)
    if pid and _pid_matches(pid, identity.get("start_ticks"), identity.get("host", ""), identity.get("boot_id", "")):
        return {"status": "reattached_alive", "job_id": job_id, "pid": pid, "duplicate_charge": False}
    merged = dict(checkpoint)
    if guardian_state:
        merged["guardian_state"] = guardian_state
    result = _settle_orphan(job_dir, merged)
    if result.get("status") != "recovery_waiting_for_owned_exit":
        _atomic_json(checkpoint_path, {**checkpoint, "state": result["status"], "worker_alive": False, "recovery": result})
    return {"job_id": job_id, **result}


def _spawn_worker(job_dir: Path, dispatch: Mapping[str, Any]) -> subprocess.Popen[str]:
    command = [sys.executable, str(SCRIPT_PATH), "worker", "--request", str(dispatch["request_path"]),
               "--grant", str(dispatch["grant_path"]), "--job-id", str(dispatch["job_id"])]
    log = (job_dir / "worker.log").open("a", encoding="utf-8")
    try:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True, close_fds=True, text=True)
    finally:
        log.close()
    return process


def guardian(job_id: str) -> dict[str, Any]:
    job_dir = _job_path(job_id)
    dispatch_path = job_dir / "dispatch.json"
    dispatch = _read_json(dispatch_path, "dispatch record", max_bytes=2 * MIB)
    if dispatch.get("job_id") != job_id:
        raise LFD01Error("dispatch record identity differs from guardian job")
    request = _read_json(dispatch.get("request_path"), "guardian request")
    guardian_started = time.monotonic()
    guardian_identity = _checkpoint_identity(os.getpid())
    guardian_children_before = _children_rusage_snapshot("guardian.before_worker_popen")
    # The guardian itself owns the worker Popen.  Enable subreaper before that
    # first Popen as well, so a worker that dies during startup cannot leave a
    # descendant outside a durable adoption boundary.
    guardian_subreaper_enabled = _enable_subreaper()
    if not guardian_subreaper_enabled:
        guardian_finished_at = _now()
        guardian_rusage = _self_rusage_snapshot("guardian.subreaper_unavailable")
        _atomic_json(_job_guardian_state(job_dir), {
            "schema": "lfd01.guardian-state.v2", "job_id": job_id,
            "guardian_identity": guardian_identity, "worker_identity": None,
            "guardian_subreaper_enabled": False,
            "guardian_started_at_utc": guardian_finished_at,
            "guardian_finished_at_utc": guardian_finished_at,
            "guardian_alive": False, "state": "guardian_subreaper_unavailable",
            "guardian_self_rusage": guardian_rusage,
        })
        _update_infrastructure(job_dir, {
            "schema": "lfd01.infrastructure-ownership.v1", "job_id": job_id,
            "guardian_identity": guardian_identity, "worker_identity": None,
            "guardian_subreaper_enabled": False, "guardian_alive": False,
            "guardian_finished_at_utc": guardian_finished_at,
            "guardian_self_rusage": guardian_rusage, "updated_at_utc": _now(),
        })
        return {"status": "guardian_subreaper_unavailable", "job_id": job_id,
                "guardian_self_rusage": guardian_rusage}
    worker_process = _spawn_worker(job_dir, dispatch)
    worker_identity = _checkpoint_identity(worker_process.pid)
    _update_infrastructure(job_dir, {
        "schema": "lfd01.infrastructure-ownership.v1",
        "job_id": job_id,
        "guardian_identity": guardian_identity,
        "worker_identity": worker_identity,
        "guardian_subreaper_enabled": True,
        "worker_charge_scope": "worker self plus RUSAGE_CHILDREN and live verified owned child group",
        "excluded_from_worker_charge": ["controller", "guardian", "root_supervisor_watcher"],
        "infra_cpu_settlement": "root supervisor records controller/guardian/watcher SELF and owned codex-cli children once",
        "updated_at_utc": _now(),
    })
    _atomic_json(_job_guardian_state(job_dir), {
        "schema": "lfd01.guardian-state.v2", "job_id": job_id,
        "guardian_identity": guardian_identity,
        "worker_identity": worker_identity, "state": "worker_running",
        "guardian_subreaper_enabled": True,
        "guardian_started_at_utc": _now(), "hard_wall_seconds": float(request.get("max_wall_seconds", 0) or 0),
    })
    deadline_cleanup: dict[str, Any] | None = None
    hard_deadline_triggered = False
    while True:
        code = worker_process.poll()
        if code is not None:
            break
        if (not hard_deadline_triggered and float(request.get("max_wall_seconds", 0) or 0) > 0 and
                time.monotonic() - guardian_started >= float(request["max_wall_seconds"])):
            hard_deadline_triggered = True
            checkpoint = {}
            if _job_checkpoint(job_dir).exists():
                try:
                    checkpoint = _read_json(_job_checkpoint(job_dir), "worker checkpoint", max_bytes=2 * MIB)
                except LFD01Error:
                    checkpoint = {}
            deadline_cleanup = _terminate_verified_owned_group(job_dir, checkpoint, reason="guardian_hard_deadline")
            if _pid_matches(worker_process.pid, worker_identity.get("start_ticks"), worker_identity.get("host", ""), worker_identity.get("boot_id", "")):
                try:
                    os.killpg(worker_process.pid, signal.SIGTERM)
                except (OSError, ProcessLookupError):
                    pass
            _atomic_json(_job_guardian_state(job_dir), {
                "schema": "lfd01.guardian-state.v2", "job_id": job_id,
                "guardian_identity": guardian_identity, "worker_identity": worker_identity,
                "state": "hard_deadline_cleanup", "observed_at_utc": _now(),
                "owned_group_cleanup": deadline_cleanup,
            })
        time.sleep(GUARDIAN_POLL_INTERVAL)
    worker_process.wait()
    recovery = None
    recovery_attempts = 0
    recovery_waiting = False
    if worker_process.returncode != 0:
        recovery_deadline = guardian_started + float(request.get("max_wall_seconds", 0) or 0)
        while True:
            recovery_attempts += 1
            try:
                recovery = recover(job_id)
            except LFD01Error as error:
                recovery = {"status": "recovery_unavailable", "error": f"{type(error).__name__}: {error}"}
            recovery_waiting = isinstance(recovery, dict) and recovery.get("status") == "recovery_waiting_for_owned_exit"
            if not recovery_waiting:
                break
            _atomic_json(_job_guardian_state(job_dir), {
                "schema": "lfd01.guardian-state.v2", "job_id": job_id,
                "guardian_identity": guardian_identity, "worker_identity": worker_identity,
                "guardian_subreaper_enabled": True, "state": "recovery_waiting_for_owned_exit",
                "guardian_alive": True, "recovery_attempts": recovery_attempts,
                "recovery_deadline_utc": recovery.get("hard_deadline_utc"),
                "recovery_after_worker_exit": recovery, "observed_at_utc": _now(),
            })
            if float(request.get("max_wall_seconds", 0) or 0) <= 0 or time.monotonic() >= recovery_deadline:
                break
            time.sleep(min(GUARDIAN_POLL_INTERVAL, max(0.01, recovery_deadline - time.monotonic())))
    # Diagnostic only: this is guardian SELF's raw waited-child counter for
    # the worker plus any descendants adopted/reaped by guardian.  Root can
    # reconcile max(0, this delta - the worker's already settled charge) once;
    # it is never added to LFD-01 worker charging here.
    guardian_children_after = _children_rusage_snapshot("guardian.after_worker_tree_reap")
    guardian_children_interval = _children_rusage_interval(guardian_children_before, guardian_children_after)
    guardian_finished_at = _now()
    guardian_rusage = _self_rusage_snapshot("guardian.terminal")
    _atomic_json(_job_guardian_state(job_dir), {
        "schema": "lfd01.guardian-state.v2", "job_id": job_id,
        "guardian_identity": guardian_identity, "worker_identity": worker_identity,
        "guardian_exit_code": worker_process.returncode, "guardian_finished_at_utc": guardian_finished_at,
        "guardian_alive": False,
        "guardian_subreaper_enabled": True,
        "state": ("recovery_waiting_for_owned_exit" if recovery_waiting else
                  ("recovery_unavailable" if isinstance(recovery, dict) and recovery.get("status") == "recovery_unavailable"
                   else "completed")),
        "hard_deadline_cleanup": deadline_cleanup,
        "recovery_attempts": recovery_attempts,
        "recovery_after_worker_exit": recovery,
        "guardian_children_rusage_interval": guardian_children_interval,
        "confirmed_exit_at_utc": (recovery or {}).get("owned_group_cleanup", {}).get("confirmed_exit_at_utc") if isinstance(recovery, dict) else None,
        "guardian_self_rusage": guardian_rusage,
    })
    _update_infrastructure(job_dir, {
        "schema": "lfd01.infrastructure-ownership.v1", "job_id": job_id,
        "guardian_finished_at_utc": guardian_finished_at, "guardian_exit_code": worker_process.returncode,
        "guardian_alive": False, "guardian_self_rusage": guardian_rusage,
        "guardian_children_rusage_interval": guardian_children_interval,
        "updated_at_utc": _now(),
    })
    return {"status": ("guardian_recovery_waiting" if recovery_waiting else "guardian_completed"), "job_id": job_id,
            "worker_returncode": worker_process.returncode, "recovery": recovery}


def _dispatch_locked(request_path: Path, grant_path: Path, *, job_id: str | None = None) -> dict[str, Any]:
    request_path = _regular_path(request_path, "dispatch request")
    grant_path = _regular_path(grant_path, "dispatch grant")
    job_id = job_id or (NAMESPACE + "job_" + uuid.uuid4().hex)
    _safe_id(job_id, "job_id")
    request, grant, adoption, baseline = _validate_request_grant(
        request_path, grant_path, actual_job_id=job_id
    )
    job_dir = _job_path(job_id)
    if job_dir.exists():
        raise LFD01Error("job directory already exists")
    job_dir.mkdir(parents=True, exist_ok=False)
    controller_identity = _checkpoint_identity(os.getpid())
    record = {
        "schema": "lfd01.dispatch.v1",
        "job_id": job_id,
        "attempt_id": _attempt_id(request),
        "request_path": str(request_path),
        "grant_path": str(grant_path),
        "adoption_sha256": _sha256(ADOPTION_PATH),
        "baseline_sha256": _sha256(BASELINE_PATH),
        "parent_ledger_path": str(PARENT_DATA_ROOT / "runtime/resource-ledger.json"),
        "controller_lock_path": str(CONTROLLER_LOCK),
        "supervisor_hook": {"guardian_state_path": str(_job_guardian_state(job_dir)),
                             "checkpoint_path": str(_job_checkpoint(job_dir)),
                             "worker_event_path": str(_job_worker_event(job_dir)),
                             "infrastructure_ownership_path": str(_job_infrastructure(job_dir)),
                             "recovery_action": "recover", "requires_permissioned_root_supervisor": True},
        "controller_identity": controller_identity,
        "infrastructure_cpu_scope": {
            "worker_charge_excludes": ["controller", "guardian", "root_supervisor_watcher"],
            "controller_settlement": "root supervisor records controller SELF once",
            "guardian_settlement": "root supervisor records guardian SELF and owned codex-cli children once",
            "worker_charge_scope": "worker SELF plus RUSAGE_CHILDREN and live verified owned child group",
        },
        "created_at_utc": _now(),
        "state": "guardian_pending",
    }
    _atomic_json(job_dir / "dispatch.json", record)
    _update_infrastructure(job_dir, {
        "schema": "lfd01.infrastructure-ownership.v1", "job_id": job_id,
        "controller_identity": controller_identity, "guardian_identity": None, "worker_identity": None,
        "worker_charge_scope": "worker self plus RUSAGE_CHILDREN and live verified owned child group",
        "excluded_from_worker_charge": ["controller", "guardian", "root_supervisor_watcher"],
        "infra_cpu_settlement": "root supervisor records controller/guardian/watcher SELF and owned codex-cli children once",
        "state": "guardian_pending", "updated_at_utc": _now(),
    })
    command = [sys.executable, str(SCRIPT_PATH), "guardian", "--job-id", job_id]
    log = (job_dir / "guardian.log").open("a", encoding="utf-8")
    try:
        guardian_process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                             start_new_session=True, close_fds=True, text=True)
    except BaseException as error:
        controller_rusage = _self_rusage_snapshot("controller.guardian_spawn_failed")
        _atomic_json(job_dir / "dispatch.json", {
            **record, "controller_self_rusage": controller_rusage, "state": "guardian_spawn_failed",
            "spawn_error": f"{type(error).__name__}: {error}", "failed_at_utc": _now(),
        })
        _update_infrastructure(job_dir, {
            "controller_self_rusage": controller_rusage,
            "state": "guardian_spawn_failed", "updated_at_utc": _now(),
            "spawn_error": f"{type(error).__name__}: {error}",
        })
        raise
    finally:
        log.close()
    controller_rusage = _self_rusage_snapshot("controller.dispatch")
    _update_infrastructure(job_dir, {"controller_self_rusage": controller_rusage,
                                     "updated_at_utc": _now()})
    _atomic_json(job_dir / "dispatch.json", {
        **record, "controller_self_rusage": controller_rusage,
        "guardian_identity": _checkpoint_identity(guardian_process.pid), "state": "guardian_running",
    })
    return {"status": "dispatched", "job_id": job_id, "guardian_pid": guardian_process.pid, "job_dir": str(job_dir)}


def dispatch(request_path: Path, grant_path: Path, *, job_id: str | None = None) -> dict[str, Any]:
    """Issue one durable dispatch while holding the NAS singleton lock."""
    with _controller_singleton():
        request_path = _regular_path(request_path, "dispatch request")
        request = _read_json(request_path, "LFD-01 request")
        attempt = _attempt_id(request)
        JOB_ROOT.mkdir(parents=True, exist_ok=True)
        for child in JOB_ROOT.iterdir():
            if not child.is_dir() or child.is_symlink():
                continue
            marker = child / "dispatch.json"
            if not marker.is_file() or marker.is_symlink():
                continue
            try:
                existing = _read_json(marker, "dispatch record", max_bytes=2 * MIB)
            except LFD01Error:
                continue
            if existing.get("attempt_id") == attempt:
                raise LFD01Error("attempt already has a durable dispatch record")
        return _dispatch_locked(request_path, grant_path, job_id=job_id)


@contextmanager
def _controller_singleton() -> Iterator[None]:
    _assert_nas_path(CONTROLLER_LOCK)
    CONTROLLER_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with CONTROLLER_LOCK.open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise LFD01Error("another LFD-01 controller is active") from error
        yield
        fcntl.flock(handle, fcntl.LOCK_UN)


def controller(request_path: Path, grant_path: Path, *, job_id: str | None = None) -> dict[str, Any]:
    # The controller owns only the singleton dispatch decision.  The detached
    # guardian/worker own execution and remain alive after this process exits.
    result = dispatch(request_path, grant_path, job_id=job_id)
    result["controller_exited_after_dispatch"] = True
    return result


def _json_collection_counts(input_paths: list[Path]) -> dict[str, Any]:
    counts: list[dict[str, Any]] = []
    for path in input_paths:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(
                handle,
                parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
                object_pairs_hook=_reject_duplicate_pairs,
            )
        if isinstance(value, dict):
            shape = "object"
            keys = sorted(str(key) for key in value)
            counts.append({"path": str(path), "top_level": shape, "key_count": len(keys), "keys": keys[:1024]})
        elif isinstance(value, list):
            counts.append({"path": str(path), "top_level": "array", "item_count": len(value)})
        else:
            counts.append({"path": str(path), "top_level": type(value).__name__})
    return {"schema": "lfd01.light.json-collection-counts.v1", "files": counts}


def _csv_summary(input_paths: list[Path]) -> dict[str, Any]:
    summaries: list[dict[str, Any]] = []
    for path in input_paths:
        rows = 0
        columns = 0
        header: list[str] | None = None
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.reader(handle):
                if rows == 0:
                    header = list(row)
                    columns = len(row)
                rows += 1
                if len(row) != columns:
                    raise LFD01Error(f"CSV row width differs in {path} at row {rows}")
        summaries.append({"path": str(path), "row_count_including_header": rows,
                          "column_count": columns, "header": header or []})
    return {"schema": "lfd01.light.csv-summary.v1", "files": summaries}


def light_worker(request_path: Path, output_path: Path) -> dict[str, Any]:
    if Path(request_path) != Path("/input/request.json") or Path(output_path) != Path("/out/light-result.json"):
        raise LFD01Error("sealed light worker must run at the fixed bwrap paths")
    request = _read_json(request_path, "sandboxed light request", max_bytes=LIGHT_MAX_INPUT)
    if request.get("execution_class") != "light":
        raise LFD01Error("sealed light worker received a non-light request")
    # Dispatch already applies these limits to bwrap; repeat the memory,
    # output, and inherited cpuset binding in the sealed entrypoint so a
    # manually invoked light worker cannot silently run without them.
    _set_process_limits(request, scope="light")
    inputs = request.get("light_inputs")
    if not isinstance(inputs, list) or not inputs:
        raise LFD01Error("sealed light request has no declared inputs")
    paths: list[Path] = []
    for item in inputs:
        sandbox = item.get("sandbox_path") if isinstance(item, dict) else None
        parts = PurePosixPath(sandbox).parts if isinstance(sandbox, str) else ()
        if (not isinstance(sandbox, str) or parts[:2] != ("/", "input") or
                any(part in {"", ".", ".."} for part in parts[2:]) or sandbox == "/input/request.json"):
            raise LFD01Error("sealed light sandbox path is unsafe")
        if Path(sandbox).suffix.lower() in LIGHT_NATIVE_SUFFIXES:
            raise LFD01Error("sealed light worker refuses native/binary input")
        paths.append(Path(sandbox))
    operation = request.get("light_operation")
    if operation == "json_collection_counts":
        result = _json_collection_counts(paths)
    elif operation == "csv_summary":
        result = _csv_summary(paths)
    else:
        raise LFD01Error("sealed light operation is not allowed")
    payload = (json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    if len(payload) > LIGHT_MAX_OUTPUT:
        raise LFD01Error("sealed light result exceeds 256 MiB")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(output_path.name + f".{os.getpid()}.tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, output_path)
    return result


def status() -> dict[str, Any]:
    adoption, baseline, adoption_sha, baseline_sha = _authority()
    with _locked_parent_ledger() as ledger:
        _verify_history(ledger, adoption, baseline)
        reservations = [row for row in ledger.get("reservations", []) if _is_lfd_attempt(row.get("id"))]
        return {
            "schema": SCHEMA,
            "campaign_id": "LFD-01",
            "adoption_sha256": adoption_sha,
            "baseline_sha256": baseline_sha,
            "parent_ledger": str(PARENT_DATA_ROOT / "runtime/resource-ledger.json"),
            "deadline_utc": ledger.get("deadline_utc"),
            "home_free_bytes": _home_free_bytes(),
            "nas_free_bytes": _nas_free_bytes(),
            "active_lfd_reservations": reservations,
            "lfd01_usage": _lfd_usage(ledger),
            "foreign_gpu_process_protection": "caller-owned processes are never stopped",
        }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("dispatch", "controller"):
        item = sub.add_parser(name)
        item.add_argument("--request", type=Path, required=True)
        item.add_argument("--grant", type=Path, required=True)
        item.add_argument("--job-id")
    guardian_parser = sub.add_parser("guardian")
    guardian_parser.add_argument("--job-id", required=True)
    worker_parser = sub.add_parser("worker")
    worker_parser.add_argument("--request", type=Path, required=True)
    worker_parser.add_argument("--grant", type=Path, required=True)
    worker_parser.add_argument("--job-id", required=True)
    recover_parser = sub.add_parser("recover")
    recover_parser.add_argument("--job-id", required=True)
    light_parser = sub.add_parser("light-worker")
    light_parser.add_argument("--request", type=Path, required=True)
    light_parser.add_argument("--output", type=Path, required=True)
    sub.add_parser("status")
    args = parser.parse_args(argv)
    if args.action == "dispatch":
        result = dispatch(args.request, args.grant, job_id=args.job_id)
    elif args.action == "controller":
        result = controller(args.request, args.grant, job_id=args.job_id)
    elif args.action == "guardian":
        result = guardian(args.job_id)
    elif args.action == "worker":
        result = worker(args.request, args.grant, job_id=args.job_id)
    elif args.action == "recover":
        result = recover(args.job_id)
    elif args.action == "light-worker":
        result = light_worker(args.request, args.output)
    else:
        result = status()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if args.action in {"worker", "guardian"} and result.get("status") not in {"completed", "guardian_completed"}:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
