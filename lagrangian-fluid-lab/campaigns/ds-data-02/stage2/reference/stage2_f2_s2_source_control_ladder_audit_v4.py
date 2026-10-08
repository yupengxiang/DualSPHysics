#!/usr/bin/env python3
"""Audit the F2-S2 three-grid source contract without launching GenCase.

The existing ``stage2_f2_s2_source_control_ladder_v3.py`` is the request
builder used by the parent guard.  This forward-only audit deliberately does
not import the dispatchers or create requests.  It checks the exact CURRENT
identity, the three candidate Def files, the motion bytes, and the controls
that are intentionally common across the ladder.  ``h`` and ``massfluid``
are generated/derived constants and are therefore recorded separately when
they are absent from a candidate Def; their eventual values, particle counts,
support and mass remain UNKNOWN until the parent runs GenCase.

This is a metadata-only source closure.  It reads small XML, motion, catalog,
review and toolchain metadata only; it never reads BI4, VTK or HDF5 and never
starts GenCase or the solver.  V3 remains immutable and is only loaded as a
source of the already registered paths and identity checks.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.f2-s2.source-control-ladder-audit.v4"
REPO = Path(__file__).resolve().parents[5]
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
V3_PATH = REFERENCE / "stage2_f2_s2_source_control_ladder_v3.py"
DEFAULT_OUTPUT = REFERENCE / "stage2_f2_s2_source_control_ladder_audit_v4.json"


def load_v3():
    spec = importlib.util.spec_from_file_location("stage2_f2_s2_ladder_v3_for_audit", V3_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load immutable V3 builder: {V3_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path, label: str) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} must be a regular file: {path}")
    stat = path.stat()
    return {
        "path": str(path),
        "label": label,
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": sha256(path),
        "scope": "metadata_only_small_input",
    }


def unique_json(value: Any) -> Any:
    """Stable JSON value with duplicate list objects removed."""
    if isinstance(value, dict):
        return {key: unique_json(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        items = [unique_json(item) for item in value]
        result = []
        seen: set[str] = set()
        for item in items:
            marker = json.dumps(item, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            if marker not in seen:
                seen.add(marker)
                result.append(item)
        return result
    return value


def control_projection(facts: dict[str, Any]) -> dict[str, Any]:
    """Return physical/control fields common to source and candidate Defs."""
    return {
        "parameters": unique_json(facts.get("parameters", {})),
        "common_constants": unique_json({
            key: facts.get("constants", {}).get(key)
            for key in ("cflnumber", "rhop0", "gamma")
            if key in facts.get("constants", {})
        }),
        "rotations": unique_json(facts.get("rotations", [])),
        "drawboxes": unique_json(facts.get("drawboxes", [])),
    }


def source_contract() -> dict[str, Any]:
    v3 = load_v3()
    source = v3.load_exact_source()
    # Re-run the exact identity checks through V3, then use only its small
    # source/candidate paths.  This does not require the parent dispatchers.
    source_def = source["source_def"]
    source_motion = source["source_motion"]
    source_facts = source["source_facts"]
    rows = []
    source_projection = control_projection(source_facts)
    source_def_bytes = source_def.read_bytes()
    for grid, spec in v3.GRIDS.items():
        candidate_def, candidate_motion = v3.candidate_paths(grid, v3.repo_root())
        candidate_facts = v3.parse_xml_facts(candidate_def)
        normalized_equal = v3.normalize_definition(source_def_bytes) == v3.normalize_definition(candidate_def.read_bytes())
        motion_equal = source_motion.read_bytes() == candidate_motion.read_bytes()
        candidate_projection = control_projection(candidate_facts)
        rows.append({
            "grid": grid,
            "candidate_dp_m": spec["dp_m"],
            "candidate_def": record(candidate_def, f"F2-S2 {grid} candidate Def"),
            "candidate_motion": record(candidate_motion, f"F2-S2 {grid} candidate motion"),
            "candidate_xml_facts": candidate_facts,
            "source_control_projection": source_projection,
            "candidate_control_projection": candidate_projection,
            "normalized_def_equal_except_dp": normalized_equal,
            "motion_byte_identical": motion_equal,
            "shared_physical_geometry_and_control_status": (
                "PASS_METADATA_ONLY" if normalized_equal and motion_equal and candidate_projection == source_projection
                else "FAIL_METADATA_MISMATCH"
            ),
            "derived_constants": {
                "source_present_but_candidate_absent": sorted(
                    set(source_facts.get("constants", {})) - set(candidate_facts.get("constants", {}))
                ),
                "interpretation": "h/massfluid are generated/derived; do not treat their absence as a control mismatch or infer terminal values",
            },
            "measured_after_parent_gencase": {
                "fluid_counts": "UNKNOWN",
                "sample_mass_kg": "UNKNOWN",
                "support_and_overlap": "UNKNOWN",
                "generated_xml_and_vtk_sha": "UNKNOWN",
            },
        })
    return {
        "schema": SCHEMA,
        "status": "PASS_METADATA_ONLY_SOURCE_CONTROL_CLOSED",
        "sentinel_id": v3.SENTINEL_ID,
        "family_id": "F2",
        "physical_case_id": v3.PHYSICAL_CASE_ID,
        "source_identity": {
            "current_catalog": record(source["current_path"], "CURRENT336 catalog"),
            "review_row_source": record(source["review_path"], "SENTINEL_MATRIX"),
            "generated_xml": record(source["source_xml"], "CURRENT F2-S2 generated XML"),
            "gencase_receipt": record(source["source_receipt"], "CURRENT F2-S2 GenCase receipt"),
            "source_def": record(source_def, "CURRENT F2-S2 Def"),
            "source_motion": record(source_motion, "CURRENT F2-S2 motion"),
            "source_xml_facts": source_facts,
        },
        "toolchain": {
            "generator": "GenCase_linux64",
            "generator_bytes": v3.GENCASE_BYTES,
            "generator_sha256": v3.GENCASE_SHA256,
            "generator_role": "official GenCase input generator; not the solver binary",
            "config": record(v3.GENCASE.parent / v3.GENCASE_CONFIG_NAME, "official DsphConfig.xml"),
            "template": record(v3.repo_root() / "doc/xml_format/GenCase_CaseTemplate.xml", "GenCase case template"),
            "command_contract": "GenCase_linux64 <Def-prefix-without-.xml> <output-prefix> -save:all -threads:1",
        },
        "grids": rows,
        "source_control_scope": {
            "intentional_resolution_parameter": "definition@dp only",
            "continuous_geometry_and_motion_frozen": True,
            "control_projection_checked": ["execution parameters", "common cfl/rhop0/gamma", "rotation axes/duration/file", "all drawboxes"],
            "derived_h_and_massfluid": "not a terminal mass/support result; parent GenCase must measure them",
            "no_mass_rescale": True,
        },
        "parent_execution": {
            "next_action": "parent guarded CPU GenCase individually for coarse/original/fine after reviewing this audit",
            "request_builder": str(V3_PATH),
            "dispatch_owned_by": "root",
            "solver_started": False,
            "gencase_started": False,
            "bi4_read": False,
            "vtk_read": False,
            "hdf5_read": False,
        },
        "scientific_qualification": {
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "reason": "source/control closure does not establish generated counts, mass, support, overlap or observer accuracy",
        },
    }


def json_new(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    temporary = path.with_name(f".{path.name}.{__import__('os').getpid()}.tmp")
    try:
        fd = __import__('os').open(temporary, __import__('os').O_CREAT | __import__('os').O_EXCL | __import__('os').O_WRONLY, 0o644)
        try:
            with __import__('os').fdopen(fd, "wb") as handle:
                fd = -1
                handle.write(payload)
                handle.flush()
                __import__('os').fsync(handle.fileno())
        finally:
            if fd >= 0:
                __import__('os').close(fd)
        __import__('os').replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def self_test() -> dict[str, Any]:
    v3 = load_v3()
    result = source_contract()
    assert result["status"] == "PASS_METADATA_ONLY_SOURCE_CONTROL_CLOSED"
    assert len(result["grids"]) == 3
    assert all(row["shared_physical_geometry_and_control_status"] == "PASS_METADATA_ONLY" for row in result["grids"])
    assert all(row["normalized_def_equal_except_dp"] for row in result["grids"])
    assert all(row["motion_byte_identical"] for row in result["grids"])
    assert result["toolchain"]["generator_bytes"] == 5_809_384
    assert result["toolchain"]["generator_sha256"] == "a1b6414e0f716669363d1a80a05e133085c04995e15716e3c1f0406e0d023226"
    # A source mutation in a physical drawbox must not be classified as a
    # resolution-only change.  This is an in-memory negative test; no file is
    # written and no generated payload is read.
    source_def = result["source_identity"]["source_def"]
    source_bytes = Path(source_def["path"]).read_bytes()
    mutated = source_bytes.replace(b'x="0.05"', b'x="0.051"', 1)
    assert mutated != source_bytes
    assert v3.normalize_definition(source_bytes) != v3.normalize_definition(mutated)
    return {
        "status": "PASS",
        "schema": SCHEMA,
        "sentinel_id": result["sentinel_id"],
        "physical_case_id": result["physical_case_id"],
        "grids": [row["candidate_dp_m"] for row in result["grids"]],
        "source_control_closed": True,
        "negative_physical_drawbox_test": "PASS_REJECTED",
        "solver_or_gencase_started": False,
        "payload_reads": {"bi4": False, "vtk": False, "hdf5": False},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--self-test", action="store_true")
    group.add_argument("--audit", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0
    report = source_contract()
    json_new(args.output, report)
    print(json.dumps({"status": report["status"], "output": str(args.output.resolve()), "grids": len(report["grids"]), "gencase_started": False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
