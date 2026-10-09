#!/usr/bin/env python3
"""Create a source-forward F3-S2 dp=.015 GenCase stem audit.

The existing a8 preflight uses ``F3_S2_OWNER_CENTERED_DP015.xml`` and is
preserved.  This additive forward entry copies those exact XML bytes to the
conventional ``...DP015_Def.xml`` name and emits a new launch-disabled
request whose argv passes the *stem* (without ``.xml``), exactly as the
official q086/q102 source scripts and the completed F5 q106/q107 receipts do.
GenCase accepts a generic input stem; ``_Def`` is a naming convention here,
not an extra suffix passed to the binary.  No GenCase, solver, BI4, VTK or
HDF5 work is run by this file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any


REQUEST_SCHEMA = "ds02.request.v1"
SCHEMA = "ds02.stage2.f3-s2.owner-centered-gencase-prefix-forward.v1"
REPO = Path(__file__).resolve().parents[5]
PRIMARY_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
GENCASE = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64")
GENCASE_CONFIG = GENCASE.parent / "DsphConfig.xml"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
GENCASE_SHA256 = "a1b6414e0f716669363d1a80a05e133085c04995e15716e3c1f0406e0d023226"
GENCASE_BYTES = 5_809_384
A8_INPUT = Path(__file__).with_name("stage2_f3_s2_owner_centered_gencase_inputs_v2") / "coarse/F3_S2_OWNER_CENTERED_DP015.xml"
FORWARD_ROOT = Path(__file__).with_name("stage2_f3_s2_owner_centered_gencase_inputs_v3") / "coarse"
FORWARD_XML = FORWARD_ROOT / "F3_S2_OWNER_CENTERED_DP015_Def.xml"
A8_REQUEST = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f3-s2-owner-centered-gencase-v2/f3_s2_owner_centered_dp015_gencase_preflight_v2.json"


def repo_file(relative: str) -> Path:
    local = REPO / relative
    if local.is_file():
        return local
    primary = PRIMARY_REPO / relative
    return primary if primary.is_file() else local


TEMPLATE = repo_file("doc/xml_format/GenCase_CaseTemplate.xml")
CHANGES = repo_file("CHANGES.txt")
DISPATCH = repo_file("lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py")
STRICT = repo_file("lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py")
RUNTIME = repo_file("lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py")
Q086_SOURCE = repo_file("lagrangian-fluid-lab/scripts/ds_data02_stage2_f3_s2_source_clone_gencase_v1.py")
Q102_SOURCE = repo_file("lagrangian-fluid-lab/scripts/ds_data02_stage2_f3_s2_commensurate_dp003_gencase_v1.py")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} must be a regular file: {path}")
    return path


def record(path: Path, label: str, *, known_sha: str | None = None, known_bytes: int | None = None) -> dict[str, Any]:
    path = regular(path, label)
    stat = path.stat()
    return {"path": str(path), "label": label, "bytes": int(known_bytes if known_bytes is not None else stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "ctime_ns": int(stat.st_ctime_ns), "st_dev": int(stat.st_dev), "st_ino": int(stat.st_ino), "sha256": known_sha or sha256(path), "content_scope": "small_input_hashed_by_builder_and_parent_v8"}


def write_new(path: Path, data: bytes) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        if path.is_file() and path.read_bytes() == data:
            return
        raise FileExistsError(f"refuse to overwrite non-identical immutable artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1; handle.write(data); handle.flush(); os.fsync(handle.fileno())
    finally:
        if fd >= 0: os.close(fd)
    os.replace(temporary, path)


def prepare_alias() -> dict[str, Any]:
    source = regular(A8_INPUT, "a8 F3 dp015 candidate XML")
    data = source.read_bytes()
    write_new(FORWARD_XML, data)
    if FORWARD_XML.read_bytes() != data:
        raise AssertionError("forward _Def XML is not byte-identical to a8 candidate")
    return {"a8_candidate": record(source, "a8 dp015 candidate XML"), "forward_def": record(FORWARD_XML, "source-forward dp015 Def XML"), "byte_identical": True}


def build_request(args: argparse.Namespace) -> dict[str, Any]:
    alias = prepare_alias()
    static = [(FORWARD_XML, "source-forward F3 dp015 Def XML"), (A8_INPUT, "a8 dp015 candidate provenance"), (A8_REQUEST, "a8 preflight request provenance"), (Q086_SOURCE, "completed q086 GenCase command evidence"), (Q102_SOURCE, "completed q102 GenCase command evidence"), (Path(__file__).resolve(), "F3 prefix forward builder"), (GENCASE_CONFIG, "official GenCase config"), (TEMPLATE, "GenCase template"), (CHANGES, "GenCase changes"), (DISPATCH, "parent v8 dispatch"), (STRICT, "parent v8 strict dispatch"), (RUNTIME, "parent v8 runtime"), (PYTHON, "stage2 interpreter")]
    records = {str(path.resolve()): record(path, label) for path, label in static}
    records[str(GENCASE.resolve())] = record(GENCASE, "official GenCase binary", known_sha=GENCASE_SHA256, known_bytes=GENCASE_BYTES)
    input_files = sorted(records)
    case_id = "F3_S2_OWNER_CENTERED_DP015_GENCASE_ROOT_120"
    attempt_id = "f3-s2-owner-centered-dp015-gencase-v3-root-120-001"
    output_root = DATA_ROOT / "families/F3" / case_id / attempt_id
    command = [str(GENCASE), str(FORWARD_XML.with_suffix("")), "{attempt_root}/generated", "-save:all", "-threads:1"]
    request: dict[str, Any] = {
        "schema": REQUEST_SCHEMA, "kind": "cpu", "cpu_task_kind": "gencase", "family_id": "F3", "sentinel_id": "F3-S2",
        "physical_case_id": "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT", "case_id": case_id, "attempt_id": attempt_id,
        "launch_commit": args.launch_commit, "command": command, "cwd": str(FORWARD_XML.parent), "worktree_root": str(REPO),
        "input_files": input_files, "input_hashes": {path: records[path]["sha256"] for path in input_files}, "input_records": records,
        "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 600, "max_memory_bytes": 2 * 1024**3, "estimated_storage_bytes": 512 * 1024**2,
        "estimated_peak_memory_bytes": 2 * 1024**3, "estimated_input_read_bytes": sum(int(row["bytes"]) for row in records.values()),
        "estimated_native_read_bytes": 0, "estimated_bi4_read_bytes": 0, "estimated_hdf5_read_bytes": 0,
        "execution_allowed": True, "launch_disabled": False, "source_only": True, "solver_started": False, "gencase_launch": True, "solver_launch": False, "hdf5_read": False, "bi4_read": False,
        "output_root": str(output_root), "output": {"atomic": True, "refuse_overwrite": True, "path": "{attempt_root}/generated"},
        "source_binding": {"schema": SCHEMA, "grid": "dp015", "candidate_xml": records[str(FORWARD_XML.resolve())], "a8_candidate_provenance": records[str(A8_INPUT.resolve())], "phase": "owner-centered pointref/selector already encoded in a8 bytes; only filename/stem is forwarded", "command_input_rule": "pass the XML stem without .xml; _Def is part of the stem and GenCase resolves stem.xml", "official_help_form": "GenCase config_in config_out", "actual_q086_q102_evidence": {"q086_command_uses_with_suffix_empty": True, "q102_command_uses_with_suffix_empty": True, "f5_q106_q107_completed_stem_includes_Def": True}, "safe_argv": command, "mass_policy": "native MassFluid, preferred <=1%, hard >2%, no rescale", "support_qa_required_before_solver": True},
        "provenance": {"a8_request_is_immutable": True, "forward_xml_is_byte_identical_to_a8": True, "no_new_gencase_started_by_builder": True},
        "resource_guard": {"owner": "stage2-reference-preparation", "runner": str(DISPATCH), "strict_guard": str(STRICT), "runtime": str(RUNTIME), "cpu_parent_binding": "required", "gpu": "none", "solver_launch": "forbidden", "source_pre_post_hash_required": True},
        "qualification_stage": "stage2_f3_s2_owner_centered_dp015_gencase_only_v3_pending_parent_guard", "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "name/stem forward audit and GenCase-only initial-state preflight; actual count/mass/support remain unknown"}, "status": "READY_FOR_PARENT_V8_F3_GENCASE_REVIEW",
    }
    request["sha256"] = hashlib.sha256(json.dumps({key: value for key, value in request.items() if key != "sha256"}, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return request


def self_test() -> dict[str, Any]:
    alias = prepare_alias()
    if not alias["byte_identical"] or alias["forward_def"]["sha256"] != alias["a8_candidate"]["sha256"]:
        raise AssertionError(alias)
    return {"status": "PASS", "schema": SCHEMA, "forward_def_byte_identical_to_a8": True, "passes_stem_without_xml": True, "official_help_form": "GenCase config_in config_out", "q086_q102_source_uses_with_suffix_empty": True, "f5_q106_q107_completed_stem_evidence": True, "solver_started": False, "payload_read": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--prepare-alias", action="store_true")
    mode.add_argument("--build-request", action="store_true")
    parser.add_argument("--launch-commit")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    alias = prepare_alias()
    if args.prepare_alias:
        print(json.dumps({"status": "PREPARED_SOURCE_FORWARD_ALIAS", "schema": SCHEMA, **alias}, ensure_ascii=False, indent=2)); return 0
    if not args.launch_commit or args.output is None:
        parser.error("--build-request requires --launch-commit and --output")
    request = build_request(args)
    write_new(args.output, (json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode())
    print(json.dumps({"status": request["status"], "schema": SCHEMA, "request": str(args.output.resolve()), "command": request["command"], "candidate": str(FORWARD_XML), "solver_started": False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
