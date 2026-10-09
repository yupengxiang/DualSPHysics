#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Materialize a reserved F3-S2 solver input tree and run the official solver.

The shared external-solver-v5 runner invokes this executable only after its
parent reservation and source pre-hash.  The runner inserts ``-gpu:0`` after
argv[0]; this wrapper consumes that runner token, copies the terminal ROOT120
XML/BI4 and forcing file into the new attempt's output tree, verifies the
copies against the already-bound SHA values, then invokes DualSPHysics with
the copied prefix.  It never writes into the ROOT120 producer directory.

This is an execution child, not a resource guard.  UUID selection, source
pre/post hashing, reservation, timeout, receipt and charge remain owned by
the parent external-solver-v5 runner.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Sequence


VENV_PYTHON_LITERAL = "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"
MANIFEST_SCHEMA = "ds02.stage2.f3.s2.external-solver-materialization.v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular_source(path: Path, label: str) -> Path:
    # Check the link before resolve() so a producer symlink cannot silently
    # become a new source identity in the child.
    path = path.expanduser()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} must be a regular source file: {path}")
    return path.resolve()


def stat_record(path: Path) -> dict[str, Any]:
    value = path.stat()
    return {
        "path": str(path),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
        "st_dev": int(value.st_dev),
        "st_ino": int(value.st_ino),
    }


def write_new_json(path: Path, value: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refuse to overwrite materialization artifact: {path}")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            fd = -1
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if fd >= 0:
            os.close(fd)
    os.replace(temporary, path)


def copy_checked(source: Path, destination: Path, expected_sha: str, label: str) -> dict[str, Any]:
    source = regular_source(source, label)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"refuse to overwrite destination: {destination}")
    source_before = stat_record(source)
    # copyfile deliberately writes directly to the newly-created destination.
    # If a read fails, the partial file remains inside the charged attempt tree
    # for the parent terminal receipt; it is never deleted or hidden.
    shutil.copyfile(source, destination)
    actual = sha256_file(destination)
    if actual != expected_sha:
        raise ValueError(f"{label} copy SHA differs: expected {expected_sha}, got {actual}")
    return {
        "label": label,
        "source": {**source_before, "expected_sha256": expected_sha},
        "source_after_copy": stat_record(source),
        "destination": {**stat_record(destination), "sha256": actual},
        "copy_sha256_verified": True,
        "source_pre_post_stat_equal": source_before == stat_record(source),
    }


def strip_runner_gpu_token(argv: Sequence[str]) -> list[str]:
    # v5 inserts this token after argv[0] for the leased UUID.  The actual
    # official solver receives its own -gpu:0 below, under the inherited
    # CUDA_VISIBLE_DEVICES UUID environment.
    return [value for value in argv if not value.startswith("-gpu:")]


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--solver", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--generated-xml", type=Path, required=True)
    parser.add_argument("--generated-bi4", type=Path, required=True)
    parser.add_argument("--forcing-csv", type=Path, required=True)
    parser.add_argument("--expected-generated-xml-sha", required=True)
    parser.add_argument("--expected-generated-bi4-sha", required=True)
    parser.add_argument("--expected-forcing-sha", required=True)
    parser.add_argument("--tmax", required=True)
    parser.add_argument("--tout", required=True)
    parser.add_argument("--mdbc-noslip", default="1")
    args = parser.parse_args(strip_runner_gpu_token(list(argv if argv is not None else sys.argv[1:])))

    output_root = args.output_root.expanduser().resolve()
    if not output_root.is_dir() or output_root.is_symlink():
        raise FileNotFoundError(f"parent runner output root is not a regular directory: {output_root}")
    solver = regular_source(args.solver, "official solver")
    generated_xml = regular_source(args.generated_xml, "generated XML")
    generated_bi4 = regular_source(args.generated_bi4, "generated BI4")
    forcing = regular_source(args.forcing_csv, "forcing CSV")
    for label, expected in (("generated XML", args.expected_generated_xml_sha),
                           ("generated BI4", args.expected_generated_bi4_sha),
                           ("forcing CSV", args.expected_forcing_sha)):
        if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
            raise ValueError(f"{label} expected SHA must be lowercase SHA-256")

    input_root = output_root / "solver-inputs"
    input_root.mkdir(mode=0o755, exist_ok=False)
    destination_xml = input_root / "generated.xml"
    destination_bi4 = input_root / "generated.bi4"
    destination_forcing = input_root / "CaseSloshingAccData.csv"
    copies = [
        copy_checked(generated_xml, destination_xml, args.expected_generated_xml_sha, "generated XML"),
        copy_checked(generated_bi4, destination_bi4, args.expected_generated_bi4_sha, "generated BI4"),
        copy_checked(forcing, destination_forcing, args.expected_forcing_sha, "forcing CSV"),
    ]
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "MATERIALIZED_BEFORE_OFFICIAL_SOLVER",
        "venv_argv0_literal": VENV_PYTHON_LITERAL,
        "output_root": str(output_root),
        "solver_input_root": str(input_root),
        "copies": copies,
        "source_integrity_scope": "parent_v5_pre_hash_and_post_hash_plus_child_copy_sha",
        "source_pre_post_hash_owned_by_parent": True,
        "official_solver": str(solver),
        "solver_argv": [str(solver), "-gpu:0", f"-mdbc_noslip:{args.mdbc_noslip}", str(input_root / "generated"), str(output_root / "solver_output"), f"-tmax:{args.tmax}", f"-tout:{args.tout}"],
        "solver_started": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    write_new_json(output_root / "solver_input_manifest.json", manifest)
    command = [
        str(solver), "-gpu:0", f"-mdbc_noslip:{args.mdbc_noslip}",
        str(input_root / "generated"), str(output_root / "solver_output"),
        f"-tmax:{args.tmax}", f"-tout:{args.tout}",
    ]
    manifest["solver_started"] = True
    manifest["status"] = "SOLVER_STARTED"
    # This is a new artifact in the charged attempt tree.  The first manifest
    # is immutable, so retain a second terminal record instead of overwriting.
    write_new_json(output_root / "solver_launch_manifest.json", {**manifest, "solver_argv": command})
    completed = subprocess.run(command, cwd=str(input_root), check=False)
    print(json.dumps({"schema": MANIFEST_SCHEMA, "status": "SOLVER_RETURNED", "returncode": completed.returncode, "output_root": str(output_root), "solver_input_root": str(input_root)}, sort_keys=True))
    return int(completed.returncode)


def self_test() -> dict[str, Any]:
    if VENV_PYTHON_LITERAL != "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python":
        raise AssertionError("literal venv ABI binding changed")
    if strip_runner_gpu_token(["-gpu:0", "--solver", "x", "-gpu:1"]) != ["--solver", "x"]:
        raise AssertionError("runner GPU token filtering failed")
    return {"status": "PASS", "schema": MANIFEST_SCHEMA, "payload_read": False, "solver_started": False, "literal_venv_argv0": VENV_PYTHON_LITERAL}


if __name__ == "__main__":
    if "--self-test" in sys.argv[1:]:
        print(json.dumps(self_test(), indent=2))
        raise SystemExit(0)
    try:
        raise SystemExit(run())
    except (OSError, ValueError, FileNotFoundError) as error:
        print(json.dumps({"schema": MANIFEST_SCHEMA, "status": "MATERIALIZATION_FAILED", "error": f"{type(error).__name__}: {error}"}, sort_keys=True))
        raise SystemExit(2)
