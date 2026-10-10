#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Materialize the reserved F3-S1 canary and invoke the official solver.

The shared external-v5 parent owns the UUID, reservation, source pre/post
hashes, timeout, cancellation, receipt, and fee.  This child only copies the
terminal GenCase products and the exact forcing source into a fresh attempt
tree, checks each copy SHA, writes immutable materialization manifests, and
executes the official solver with the parent's inherited CUDA visibility.
It is never called by the source builder or its tests.
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


VENV_LITERAL = "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"
SCHEMA = "ds02.stage2.f3.s1.external-solver-materialization.v1"


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino),
            "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns),
            "ctime_ns": int(value.st_ctime_ns)}


def _source(path: Path, label: str) -> Path:
    path = path.expanduser()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} must be a regular non-symlink source: {path}")
    return path.absolute()


def _write_once(path: Path, value: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite materialization artifact: {path}")
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temp.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def _copy_checked(source: Path, destination: Path, expected_sha: str, label: str) -> dict[str, Any]:
    source = _source(source, label)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"refusing to overwrite {destination}")
    before = _stat(source)
    shutil.copyfile(source, destination)
    actual = _sha(destination)
    if actual != expected_sha:
        raise ValueError(f"{label} SHA mismatch: expected {expected_sha}, got {actual}")
    after = _stat(source)
    return {"label": label, "source": {**before, "path": str(source)},
            "source_after": after, "destination": {**_stat(destination), "path": str(destination), "sha256": actual},
            "source_pre_post_stat_equal": before == after, "copy_sha256_verified": True}


def _strip_gpu(argv: Sequence[str]) -> list[str]:
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
    parser.add_argument("--tmax", default="8.35")
    parser.add_argument("--tout", default="0.01")
    parser.add_argument("--mdbc-noslip", default="1")
    args = parser.parse_args(_strip_gpu(list(argv if argv is not None else sys.argv[1:])))
    output_root = args.output_root.expanduser().resolve()
    if not output_root.is_dir() or output_root.is_symlink():
        raise FileNotFoundError(f"attempt output root is not a regular directory: {output_root}")
    solver = _source(args.solver, "official solver")
    generated_xml = _source(args.generated_xml, "generated XML")
    generated_bi4 = _source(args.generated_bi4, "generated BI4")
    forcing = _source(args.forcing_csv, "forcing control")
    expected = (args.expected_generated_xml_sha, args.expected_generated_bi4_sha, args.expected_forcing_sha)
    if not all(len(value) == 64 and all(ch in "0123456789abcdef" for ch in value) for value in expected):
        raise ValueError("all materialized source SHA values must be lowercase SHA-256")
    input_root = output_root / "solver-inputs"
    input_root.mkdir(mode=0o755, exist_ok=False)
    copies = [
        _copy_checked(generated_xml, input_root / "generated.xml", args.expected_generated_xml_sha, "generated XML"),
        _copy_checked(generated_bi4, input_root / "generated.bi4", args.expected_generated_bi4_sha, "generated BI4"),
        _copy_checked(forcing, input_root / "CaseSloshingAccData.csv", args.expected_forcing_sha, "F3-S1 forcing control"),
    ]
    command = [str(solver), "-gpu:0", f"-mdbc_noslip:{args.mdbc_noslip}",
               str(input_root / "generated"), str(output_root / "solver_output"),
               f"-tmax:{args.tmax}", f"-tout:{args.tout}"]
    manifest = {
        "schema": SCHEMA, "status": "MATERIALIZED_BEFORE_OFFICIAL_SOLVER",
        "sentinel_id": "F3-S1", "literal_venv_argv0": VENV_LITERAL,
        "output_root": str(output_root), "solver_input_root": str(input_root),
        "copies": copies, "source_pre_post_owned_by_parent": True,
        "official_solver": str(solver), "solver_argv": command,
        "solver_started": False, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    _write_once(output_root / "solver_input_manifest.json", manifest)
    _write_once(output_root / "solver_launch_manifest.json", {**manifest, "status": "SOLVER_STARTED", "solver_started": True})
    completed = subprocess.run(command, cwd=str(input_root), check=False)
    print(json.dumps({"schema": SCHEMA, "status": "SOLVER_RETURNED", "returncode": completed.returncode,
                      "output_root": str(output_root), "sentinel_id": "F3-S1"}, sort_keys=True))
    return int(completed.returncode)


def self_test() -> dict[str, Any]:
    if VENV_LITERAL != "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python":
        raise AssertionError("literal venv path changed")
    if _strip_gpu(["-gpu:0", "x", "-gpu:2"]) != ["x"]:
        raise AssertionError("GPU token filter failed")
    return {"status": "PASS", "schema": SCHEMA, "solver_started": False,
            "payload_read": False, "official_tool": "DualSPHysics5.4_linux64"}


if __name__ == "__main__":
    if "--self-test" in sys.argv[1:]:
        print(json.dumps(self_test(), indent=2, sort_keys=True))
        raise SystemExit(0)
    try:
        raise SystemExit(run())
    except (OSError, ValueError, FileNotFoundError) as exc:
        print(json.dumps({"schema": SCHEMA, "status": "MATERIALIZATION_FAILED", "error": str(exc)}, sort_keys=True))
        raise SystemExit(2)
