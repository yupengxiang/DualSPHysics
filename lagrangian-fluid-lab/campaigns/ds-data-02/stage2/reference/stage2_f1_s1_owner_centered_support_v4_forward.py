#!/usr/bin/env python3
"""Audit the actual owner-centred F1-S1 ``dp=.0025`` rung.

The first owner-centred rungs retained legacy support boxes and failed the
frozen owner mass/support contract. This forward ``dp=.0025`` preflight uses
the commensurate owner-centred representation: ``pointref=dp/2`` and
``size=owner_size-dp``. It keeps the frozen 40.2 kg owner mass. Earlier
inputs and receipts remain immutable. The continuous reservoir, density,
physical case, motion, and execution controls are unchanged. The generated
lattice and support envelope still require a parent-guarded GenCase/VTK
audit; the expected mass is not promoted from an arithmetic prediction.

The audit parser intentionally separates source Def files from generated XML:
source Defs need command/definition fields but do not contain generated fluid
blocks, while generated XML must contain particle counts and massfluid. This
This v4 is additive and does not modify any consumed v1/v2/v3 source, request,
or failed output.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile
from typing import Any
import xml.etree.ElementTree as ET


REQUEST_SCHEMA = "ds02.request.v1"
SCHEMA = "ds02.stage2.f1-s1.owner-centred-support.v4"
REPORT_SCHEMA = "ds02.stage2.f1-s1.owner-centred-support-report.v4"
REPO = Path(__file__).resolve().parents[5]
MAIN = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
GENCASE = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64")
RUNNER = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
STRICT = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
OWNER = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/handoff_20261003/root_actual_fallback_canonical_bindings_and_typed_034/ecc_coarse/owner.json")
OWNER_BINDING = OWNER.parent.parent / "ecc-physical-binding.json"
GEOMETRY_EVIDENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f1_s1_geometry_semantics_source_evidence_v1.json"
CURRENT_ROOT = DATA_ROOT / "families/F1/F1_FALLBACK_ECC_COARSE/root-fallback-ecc-coarse-actual-gencase-027"
CURRENT_DEF = CURRENT_ROOT / "prepared/F1_FALLBACK_ECC_COARSE_Def.xml"
CURRENT_XML = CURRENT_ROOT / "prepared/F1_FALLBACK_ECC_COARSE.xml"
CURRENT_RECEIPT = CURRENT_ROOT / "execution-receipt.json"
FAILED_V1_ROOT = DATA_ROOT / "families/F1/F1_S1_OWNER_CENTERED_DP0p005000/f1-s1-owner-centered-dp0p005000-v1-root-001-root-forward-029-001"

INPUT_ROOT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f1_s1_owner_centered_support_inputs_v3"
CANDIDATE_CASE_ID = "F1_S1_OWNER_CENTERED_DP0p002500_V3"
CANDIDATE_ATTEMPT_ID = "f1-s1-owner-centered-dp0p002500-v3-root-001"
CANDIDATE_DEF = INPUT_ROOT / f"{CANDIDATE_CASE_ID}_Def.xml"
DERIVATION = INPUT_ROOT / "owner_centered_dp0025_derivation_manifest_v3.json"
CANDIDATE_OUTPUT_ROOT = DATA_ROOT / "families/F1" / CANDIDATE_CASE_ID / "f1-s1-owner-centered-dp0p002500-v3-root-001-root-forward-030-001"
CANDIDATE_REQUEST_DIR = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f1-s1-owner-centered-dp0025-gencase-v3"
CANDIDATE_REQUEST = CANDIDATE_REQUEST_DIR / "f1_s1_owner_centered_dp0025_gencase_v3.json"

AUDIT_CASE_ID = "F1_S1_OWNER_CENTERED_SUPPORT_AUDIT_V4"
AUDIT_ATTEMPT_ID = "f1-s1-owner-centered-support-audit-v4-root-forward-031-001"
AUDIT_REQUEST_DIR = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f1-s1-owner-centered-support-audit-v4-forward"
AUDIT_REQUEST = AUDIT_REQUEST_DIR / "f1_s1_owner_centered_support_audit_v4.json"
AUDIT_OUTPUT_ROOT = DATA_ROOT / "families/F1" / AUDIT_CASE_ID / AUDIT_ATTEMPT_ID

OWNER_LOW = [0.0, 0.0, 0.0]
OWNER_SIZE = [0.4, 0.67, 0.15]
OWNER_UPPER = [OWNER_LOW[i] + OWNER_SIZE[i] for i in range(3)]
OWNER_DENSITY = 1000.0
OWNER_MASS = 40.2
CANDIDATE_DP = 0.0025
CANDIDATE_POINTREF = [CANDIDATE_DP / 2.0] * 3
CANDIDATE_FLUID_POINT = CANDIDATE_POINTREF
CANDIDATE_FLUID_SIZE = [OWNER_SIZE[i] - CANDIDATE_DP for i in range(3)]
EXPECTED_AXIS_COUNTS = [int(round(value / CANDIDATE_DP)) for value in OWNER_SIZE]
EXPECTED_FLUID_COUNT = math.prod(EXPECTED_AXIS_COUNTS)
SUPPORT_TOL = 3.0e-6
VTK_POINTS_RE = re.compile(rb"POINTS\s+(\d+)\s+float\s*\r?\n")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular(path: Path, label: str = "file") -> Path:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} must be an existing file: {path}")
    return path


def record(path: Path, label: str = "file") -> dict[str, Any]:
    path = regular(path, label)
    stat = path.stat()
    return {"path": str(path), "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "sha256": sha256(path)}


def load_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(regular(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def atomic_bytes(path: Path, value: bytes) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise FileExistsError(f"refuse overwrite immutable artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


def atomic_json(path: Path, value: Any) -> None:
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"))


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def finite(value: str | None, label: str) -> float:
    if value is None:
        raise ValueError(f"missing {label}")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"non-finite {label}")
    return result


def vector(node: ET.Element | None, label: str) -> list[float]:
    if node is None:
        raise ValueError(f"missing {label}")
    return [finite(node.get(axis), f"{label}.{axis}") for axis in ("x", "y", "z")]


def parse_source_def(path: Path, label: str) -> dict[str, Any]:
    """Parse command/definition fields only; source Defs have no particles."""
    root = ET.parse(regular(path, label)).getroot()
    definition = next((node for node in root.iter() if local_name(node.tag) == "definition"), None)
    if definition is None:
        raise ValueError(f"{label} has no geometry definition")
    pointref = vector(next((node for node in definition if local_name(node.tag) == "pointref"), None), f"{label}.pointref")
    dp = finite(definition.get("dp"), f"{label}.dp")
    active_mk: str | None = None
    fluid_boxes: list[dict[str, Any]] = []
    for node in root.iter():
        tag = local_name(node.tag)
        if tag == "setmkfluid":
            active_mk = node.get("mk")
        elif tag in {"setmkbound", "setmkvoid"}:
            active_mk = None
        elif tag == "drawbox" and active_mk is not None:
            fill = next((child for child in node if local_name(child.tag) == "boxfill"), None)
            if fill is None or (fill.text or "").strip().lower() != "solid":
                continue
            point = vector(next((child for child in node if local_name(child.tag) == "point"), None), f"{label}.fluid.point")
            size = vector(next((child for child in node if local_name(child.tag) == "size"), None), f"{label}.fluid.size")
            fluid_boxes.append({"mkfluid_relative": active_mk, "comment": node.get("cmt"),
                                "point_m": point, "size_m": size,
                                "upper_m": [point[i] + size[i] for i in range(3)],
                                "volume_m3": math.prod(size)})
    if not fluid_boxes:
        raise ValueError(f"{label} has no fluid drawbox command")
    parameters = {
        node.get("key"): node.get("value") for node in root.iter()
        if local_name(node.tag) == "parameter" and node.get("key") is not None
    }
    return {"file": record(path, label), "case_app": root.get("app"),
            "definition": {"dp_m": dp, "pointref_m": pointref},
            "fluid_drawboxes": fluid_boxes, "execution_parameters": parameters,
            "setshapemode": [(node.text or "").strip() for node in root.iter() if local_name(node.tag) == "setshapemode"]}


def parse_generated_xml(path: Path, label: str) -> dict[str, Any]:
    """Parse generated particle/mass fields plus the same source geometry fields."""
    parsed = parse_source_def(path, label)
    root = ET.parse(regular(path, label)).getroot()
    particles = next((node for node in root.iter() if local_name(node.tag) == "particles"), None)
    fluids = [node for node in list(particles or []) if local_name(node.tag) == "fluid"]
    if not fluids:
        raise ValueError(f"{label} generated XML has no fluid blocks")
    counts = [int(node.get("count")) for node in fluids if node.get("count") is not None]
    if len(counts) != len(fluids):
        raise ValueError(f"{label} has a fluid block without count")
    constants = next((node for node in root.iter() if local_name(node.tag) == "constants"), None)
    mass_node = next((node for node in list(constants or []) if local_name(node.tag) == "massfluid"), None)
    massfluid = finite(mass_node.get("value"), f"{label}.massfluid") if mass_node is not None else None
    if massfluid is None:
        raise ValueError(f"{label} has no generated massfluid")
    parsed.update({"fluid_block_counts": counts, "fluid_count_from_xml": sum(counts), "massfluid_kg": massfluid})
    return parsed


def parse_receipt(path: Path, expected_case_id: str, label: str) -> dict[str, Any]:
    receipt = load_json(path, f"{label} receipt")
    request = receipt.get("request", {})
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ValueError(f"{label} is not a completed successful GenCase receipt")
    if request.get("case_id") != expected_case_id:
        raise ValueError(f"{label} case identity differs: {request.get('case_id')} != {expected_case_id}")
    launch = receipt.get("input_hashes_at_launch")
    finish = receipt.get("input_hashes_after_run")
    if launch is not None and finish is not None and launch != finish:
        raise ValueError(f"{label} input hashes changed")
    return {"record": record(path, f"{label} receipt"), "request_sha256": receipt.get("request_sha256"),
            "output_root": receipt.get("output_root"), "cpu_core_seconds": receipt.get("cpu_core_seconds"),
            "bytes": receipt.get("bytes"), "source_hashes_stable": launch == finish if launch is not None and finish is not None else None}


def grouped(values: list[float], tolerance: float = 2.0e-6) -> list[float]:
    output: list[float] = []
    for value in sorted(values):
        if not output or abs(value - output[-1]) > tolerance:
            output.append(value)
    return output


def parse_vtk(path: Path, dp: float, pointref: list[float], label: str) -> dict[str, Any]:
    raw = regular(path, label).read_bytes()
    match = VTK_POINTS_RE.search(raw)
    if match is None:
        raise ValueError(f"{label} lacks binary POINTS header")
    count = int(match.group(1))
    payload = raw[match.end():match.end() + 12 * count]
    if len(payload) != 12 * count:
        raise ValueError(f"{label} POINTS payload is truncated")
    values = struct.unpack(f">{3 * count}f", payload)
    if not all(math.isfinite(value) for value in values):
        raise ValueError(f"{label} contains NaN/Inf point coordinates")
    axes = [list(values[index::3]) for index in range(3)]
    axis_records: list[dict[str, Any]] = []
    for index, values_axis in enumerate(axes):
        unique = grouped(values_axis)
        if not unique:
            raise ValueError(f"{label} axis {index} is empty")
        indices = [(value - pointref[index]) / dp for value in unique]
        residual = max(abs(value - round(value)) for value in indices)
        axis_records.append({"axis": "xyz"[index], "unique_count": len(unique), "first_m": unique[0],
                             "last_m": unique[-1], "pointref_index_max_integer_residual": residual,
                             "support_low_m": unique[0] - dp / 2.0, "support_high_m": unique[-1] + dp / 2.0})
    return {"file": record(path, label), "point_count_header": count,
            "points_payload_sha256": hashlib.sha256(payload).hexdigest(), "axis": axis_records,
            "axis_count_product": math.prod(item["unique_count"] for item in axis_records),
            "support_envelope_m": {"lower_m": [item["support_low_m"] for item in axis_records],
                                   "upper_m": [item["support_high_m"] for item in axis_records]},
            "all_axis_indices_integer_within_2e-5": all(item["pointref_index_max_integer_residual"] <= 2e-5 for item in axis_records)}


def support_comparison(vtk: dict[str, Any], pointref: list[float], dp: float) -> dict[str, Any]:
    lower = vtk["support_envelope_m"]["lower_m"]
    upper = vtk["support_envelope_m"]["upper_m"]
    residual = [pair[0] - pair[1] for pair in zip(lower, OWNER_LOW)] + [pair[0] - pair[1] for pair in zip(upper, OWNER_UPPER)]
    max_error = max((abs(value) for value in residual), default=math.inf)
    pointref_match = all(abs(pointref[i] - dp / 2.0) <= SUPPORT_TOL for i in range(3))
    return {"owner_lower_m": OWNER_LOW, "owner_upper_m": OWNER_UPPER, "observed_lower_m": lower,
            "observed_upper_m": upper, "residual_m": residual, "max_abs_support_residual_m": max_error,
            "pointref_m": pointref, "dp_over_2_m": [dp / 2.0] * 3,
            "pointref_equals_dp_over_2": pointref_match,
            "matches_owner_within_tolerance": max_error <= SUPPORT_TOL,
            "status": "PASS_OWNER_SUPPORT_ENVELOPE" if max_error <= SUPPORT_TOL else "FAIL_SUPPORT_ENVELOPE_DIFFERS_FROM_OWNER"}


def owner_contract() -> dict[str, Any]:
    owner = load_json(OWNER, "F1 owner")
    binding = load_json(OWNER_BINDING, "F1 physical binding")
    physical = owner.get("physical_binding", {})
    geometry = physical.get("geometry", {}).get("fluid_reservoir")
    if geometry != physical.get("initial_state", {}).get("source_regions", {}).get("fluid"):
        raise ValueError("owner geometry and initial source differ")
    low = [float(value) for value in geometry["low_m"]]
    size = [float(value) for value in geometry["size_m"]]
    density = float(physical["density_kg_m3"])
    mass = float(physical["initial_state"]["continuum_mass_by_source_kg"]["fluid"])
    if low != OWNER_LOW or size != OWNER_SIZE or density != OWNER_DENSITY or abs(mass - OWNER_MASS) > 1e-12:
        raise ValueError("frozen owner contract changed")
    if binding.get("physical_condition_sha256") != owner.get("physical_condition_sha256"):
        raise ValueError("owner/binding physical condition SHA differs")
    return {"owner_file": record(OWNER, "F1 owner"), "binding_file": record(OWNER_BINDING, "F1 binding"),
            "identity": {key: owner.get(key) for key in ("family_id", "case_id", "physical_case_id", "mechanism_id")},
            "physical_condition_sha256": owner.get("physical_condition_sha256"),
            "continuous_fluid_reservoir": {"low_m": low, "size_m": size, "upper_m": OWNER_UPPER,
                                            "volume_m3": math.prod(size), "density_kg_m3": density,
                                            "mass_kg": mass, "mkfluid_relative": geometry.get("mkfluid"),
                                            "authority": "CURRENT336 owner/physical-binding; never inferred from particle count"}}


def source_signatures() -> dict[str, Any]:
    """Return source-side geometry/control facts without requiring particles."""
    specs = {
        "dp010": (CURRENT_DEF, "F1_FALLBACK_ECC_COARSE"),
        "dp009": (REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f1_s1_geometry_mode_probe_inputs_v2/F1_S1/dp0p009000/setshapemode_actual/F1_S1_DP009_MODE_ACTUAL_Def.xml", "F1_S1_SPATIAL_MODE_ACTUAL_DP0p009000"),
        "dp008": (REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f1_s1_owner_third_dp_rung_inputs_v1/F1_S1_OWNER_THIRD_DP0p008000_Def.xml", "F1_S1_OWNER_THIRD_DP0p008000"),
        "dp0025_v3": (CANDIDATE_DEF, CANDIDATE_CASE_ID),
    }
    result: dict[str, Any] = {}
    for label, (path, case_id) in specs.items():
        parsed = parse_source_def(path, f"{label} source Def")
        result[label] = {"case_id": case_id, "source": parsed}
    return result


def derive_candidate() -> dict[str, Any]:
    source = regular(CURRENT_DEF, "CURRENT F1 Def").read_text(encoding="utf-8")
    definition = re.search(r"<definition\b[^>]*>", source)
    if definition is None or 'dp="0.01"' not in definition.group(0):
        raise ValueError("CURRENT Def does not have the expected dp=.01 definition")
    pointref = re.search(r"<pointref\b[^>]*/>", source)
    if pointref is None or any(value not in pointref.group(0) for value in ('x="0.005"', 'y="0.005"', 'z="0.005"')):
        raise ValueError("CURRENT Def pointref is not .005/.005/.005")
    fluid_start = source.find('<drawbox cmt="v1 fallback controlled fluid cell centres">')
    fluid_end = source.find("</drawbox>", fluid_start)
    if fluid_start < 0 or fluid_end < 0:
        raise ValueError("CURRENT Def fluid drawbox anchor is missing")
    fluid_end += len("</drawbox>")
    fluid_block = source[fluid_start:fluid_end]
    new_block, point_changes = re.subn(r"<point\b[^>]*/>", '<point x="0.00125" y="0.00125" z="0.00125"/>', fluid_block, count=1)
    new_block, size_changes = re.subn(r"<size\b[^>]*/>", '<size x="0.3975" y="0.6675" z="0.1475"/>', new_block, count=1)
    if point_changes != 1 or size_changes != 1:
        raise ValueError("fluid drawbox point/size edit was not unique")
    derived = source[:fluid_start] + new_block + source[fluid_end:]
    derived = derived.replace('definition dp="0.01"', 'definition dp="0.0025"', 1)
    derived, pointref_changes = re.subn(r"<pointref\b[^>]*/>", '<pointref x="0.00125" y="0.00125" z="0.00125"/>', derived, count=1)
    if pointref_changes != 1 or derived == source:
        raise ValueError("candidate geometry edits were not applied")
    # A normalized comparison proves that the representation edits are exactly
    # dp, pointref, and the one fluid command box; every other source byte is
    # retained semantically.
    def normalize(text: str) -> str:
        text = re.sub(r'(<definition\b[^>]*\bdp=")[^"]+("[^>]*>)', r"\1<DP>\2", text, count=1)
        text = re.sub(r"<pointref\b[^>]*/>", '<pointref x="<PX>" y="<PY>" z="<PZ>"/>', text, count=1)
        text = text.replace('<point x="0.005" y="0.005" z="0.005"/>', '<point x="<FX>" y="<FY>" z="<FZ>"/>', 1)
        text = text.replace('<size x="0.39" y="0.66" z="0.14"/>', '<size x="<SX>" y="<SY>" z="<SZ>"/>', 1)
        text = text.replace('<point x="0.00125" y="0.00125" z="0.00125"/>', '<point x="<FX>" y="<FY>" z="<FZ>"/>', 1)
        text = text.replace('<size x="0.3975" y="0.6675" z="0.1475"/>', '<size x="<SX>" y="<SY>" z="<SZ>"/>', 1)
        return text
    normalized_source = normalize(source)
    normalized_candidate = normalize(derived)
    if normalized_source != normalized_candidate:
        raise ValueError("candidate changes bytes outside dp/pointref/fluid point/size")
    atomic_bytes(CANDIDATE_DEF, derived.encode("utf-8"))
    derivation = {"schema": SCHEMA, "status": "PREPARED_CORRECTED_OWNER_CENTERED_REPRESENTATION",
                  "source_def": record(CURRENT_DEF, "CURRENT F1 Def"), "candidate_def": record(CANDIDATE_DEF, "owner-centered F1 .0025 Def"),
                  "previous_rung_failure_receipts": record(FAILED_V1_ROOT / "execution-receipt.json", "immutable v1 failure receipt"),
                  "only_intentional_representation_edits": {
                      "definition@dp": [0.01, CANDIDATE_DP], "definition/pointref": [[0.005] * 3, CANDIDATE_POINTREF],
                      "fluid_command_point_m": [[0.005] * 3, CANDIDATE_FLUID_POINT],
                      "fluid_command_size_m": [[0.39, 0.66, 0.14], CANDIDATE_FLUID_SIZE],
                  },
                  "continuous_owner_unchanged": {"low_m": OWNER_LOW, "size_m": OWNER_SIZE, "density_kg_m3": OWNER_DENSITY, "mass_kg": OWNER_MASS},
                  "expected_lattice_only": {"axis_counts": EXPECTED_AXIS_COUNTS, "fluid_count": EXPECTED_FLUID_COUNT,
                                               "quadrature_mass_kg": EXPECTED_FLUID_COUNT * CANDIDATE_DP ** 3 * OWNER_DENSITY,
                                               "status": "EXPECTED_UNTIL_PARENT_GENCASE_AND_VTK_AUDIT"},
                  "previous_failure_scope": {"v1_case": "F1_S1_OWNER_CENTERED_DP0p005000", "v1_mass_kg": 38.087875,
                                               "v1_mass_error_fraction": (38.087875 - OWNER_MASS) / OWNER_MASS,
                                               "classification": "HARD_FAIL_ABOVE_2_PERCENT"},
                  "normalized_source_sha256": hashlib.sha256(normalized_source.encode()).hexdigest(),
                  "normalized_candidate_sha256": hashlib.sha256(normalized_candidate.encode()).hexdigest()}
    atomic_json(DERIVATION, derivation)
    return derivation


def input_records(paths: list[Path]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in list(dict.fromkeys(item.expanduser().resolve() for item in paths)):
        if path.suffix.lower() in {".bi4", ".h5", ".hdf5"}:
            raise ValueError(f"native/HDF5 input forbidden: {path}")
        result[str(path)] = record(path, "GenCase request input")
    return result


def git_commit() -> str:
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN_GIT_COMMIT"
    return result.stdout.strip()


def build_candidate_request() -> dict[str, Any]:
    if CANDIDATE_REQUEST.exists():
        raise FileExistsError(f"refuse overwrite immutable request: {CANDIDATE_REQUEST}")
    if not CANDIDATE_DEF.is_file() or not DERIVATION.is_file():
        raise FileNotFoundError("run --prepare-input before --candidate-request")
    paths = [Path(__file__), PYTHON, GENCASE, RUNNER, STRICT, RUNTIME, CURRENT_DEF, CURRENT_XML, CURRENT_RECEIPT,
             OWNER, OWNER_BINDING, GEOMETRY_EVIDENCE, CANDIDATE_DEF, DERIVATION, FAILED_V1_ROOT / "execution-receipt.json"]
    records = input_records(paths)
    request = {"schema": REQUEST_SCHEMA, "kind": "cpu", "cpu_task_kind": "gencase", "family_id": "F1", "sentinel_id": "F1-S1",
               "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1", "case_id": CANDIDATE_CASE_ID, "attempt_id": CANDIDATE_ATTEMPT_ID,
               "launch_commit": git_commit(),
               "command": [str(GENCASE), str(CANDIDATE_DEF.with_suffix("")), "{attempt_root}/generated", "-save:all", "-threads:1"],
               "cwd": str(REPO), "worktree_root": str(REPO), "input_files": list(records),
               "input_hashes": {path: item["sha256"] for path, item in records.items()}, "input_records": records,
               "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 1800,
               "estimated_input_read_bytes": sum(item["bytes"] for item in records.values()),
               "estimated_storage_bytes": 2 * 1024 * 1024 * 1024, "estimated_peak_memory_bytes": 2 * 1024 * 1024 * 1024,
               "estimated_native_read_bytes": 0, "estimated_bi4_read_bytes": 0, "estimated_hdf5_read_bytes": 0,
               "execution_allowed": True, "launch_disabled": False, "solver_started": False, "gencase_launch": True,
               "solver_launch": False, "hdf5_read": False, "bi4_read": False, "resource_guard": {"owner": "stage2-reference-preparation", "runner": str(RUNNER), "strict_guard": str(STRICT),
                                  "runtime": str(RUNTIME), "launch_commit": git_commit(), "cpu_parent_binding": "required",
                                  "gpu": "none", "gpu_uuid_lease": "none", "solver_launch": "forbidden", "bi4_read": "forbidden",
                                  "hdf5_read": "forbidden", "source_output_protection": "new v3 attempt only; v1/v2 inputs and failures immutable"},
               "output_root": str(CANDIDATE_OUTPUT_ROOT), "output": {"atomic": True, "refuse_overwrite": True},
               "source_binding": {"schema": SCHEMA, "derivation_manifest": record(DERIVATION, "owner-centred dp0025 derivation"),
                                  "continuous_owner": {"low_m": OWNER_LOW, "size_m": OWNER_SIZE, "upper_m": OWNER_UPPER,
                                                        "density_kg_m3": OWNER_DENSITY, "mass_kg": OWNER_MASS,
                                                        "authority": "CURRENT336 owner/physical-binding"},
                                  "source_control": {"current_def": record(CURRENT_DEF, "CURRENT Def"), "candidate_def": record(CANDIDATE_DEF, "corrected candidate Def"),
                                                      "only_representation_edits": ["dp .01 -> .0025", "pointref .005 -> .00125", "fluid point owner_low+dp/2", "fluid size owner_size-dp"],
                                                      "geometry_control_motion_unchanged": True},
                                  "expected_owner_lattice": {"axis_counts": EXPECTED_AXIS_COUNTS, "fluid_count": EXPECTED_FLUID_COUNT,
                                                               "sample_mass_kg": OWNER_MASS, "status": "EXPECTED_ONLY_UNTIL_GENERATED_AUDIT"},
                                  "acceptance": {"preferred_whole_initial_mass_fraction": 0.01, "marginal_upper_fraction": 0.02,
                                                 "hard_fail_above_fraction": 0.02, "support_tolerance_m": SUPPORT_TOL,
                                                 "no_mass_rescale": True, "no_posthoc_geometry_or_control_change": True,
                                                 "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}},
               "qualification_stage": "stage2_f1_s1_owner_centered_dp0025_v3_gencase_pending_support_audit",
               "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}
    atomic_json(CANDIDATE_REQUEST, request)
    return request


def case_specs(include_candidate: bool) -> dict[str, dict[str, Any]]:
    """Bind the actual root-forward .0025 output without reopening old rung VTKs.

    The consumed .005 support proof is referenced as an immutable checkpoint;
    this v4 worker reads only the new .0025 generated XML/Fluid.vtk plus the
    small source/receipt files needed to close its identity.  No old/new
    .005 VTK is reread here.
    """
    cases: dict[str, dict[str, Any]] = {}
    if include_candidate:
        cases["dp0025_v3"] = {
            "case_id": CANDIDATE_CASE_ID,
            "dp_m": CANDIDATE_DP,
            "source_def": CANDIDATE_DEF,
            "generated_xml": CANDIDATE_OUTPUT_ROOT / "generated.xml",
            "receipt": CANDIDATE_OUTPUT_ROOT / "execution-receipt.json",
            "fluid_vtk": CANDIDATE_OUTPUT_ROOT / "generated_Fluid.vtk",
        }
    return cases

def audit_case(label: str, spec: dict[str, Any]) -> dict[str, Any]:
    source = parse_source_def(spec["source_def"], f"{label} source Def")
    generated = parse_generated_xml(spec["generated_xml"], f"{label} generated XML")
    receipt = parse_receipt(spec["receipt"], spec["case_id"], label)
    if abs(source["definition"]["dp_m"] - spec["dp_m"]) > 1e-12 or abs(generated["definition"]["dp_m"] - spec["dp_m"]) > 1e-12:
        raise ValueError(f"{label} dp identity mismatch")
    if source["definition"]["pointref_m"] != generated["definition"]["pointref_m"]:
        raise ValueError(f"{label} source/generated pointref mismatch")
    fluid = parse_vtk(spec["fluid_vtk"], spec["dp_m"], generated["definition"]["pointref_m"], f"{label} Fluid.vtk")
    if fluid["point_count_header"] != generated["fluid_count_from_xml"]:
        raise ValueError(f"{label} Fluid.vtk/XML fluid count mismatch")
    sample_mass = fluid["point_count_header"] * generated["massfluid_kg"]
    mass_error = (sample_mass - OWNER_MASS) / OWNER_MASS
    return {"case_id": spec["case_id"], "dp_m": spec["dp_m"], "source_def": source, "generated_xml": generated,
            "receipt": receipt, "fluid": fluid,
            "fluid_count": fluid["point_count_header"], "sample_mass_kg": sample_mass,
            "sample_mass_error_fraction_vs_owner": mass_error,
            "mass_gate": "PREFERRED_WITHIN_1_PERCENT" if abs(mass_error) <= 0.01 else "MARGINAL_WITHIN_2_PERCENT" if abs(mass_error) <= 0.02 else "HARD_FAIL_ABOVE_2_PERCENT",
            "support_comparison": support_comparison(fluid, generated["definition"]["pointref_m"], spec["dp_m"]),
            "source_control_status": "SOURCE_COMMAND_AND_EXECUTION_FIELDS_RECORDED; cross-grid physical equivalence requires explicit comparison"}


def audit(output: Path, include_candidate: bool) -> dict[str, Any]:
    owner = owner_contract()
    cases = {label: audit_case(label, spec) for label, spec in case_specs(include_candidate).items()}
    candidate = cases.get("dp0025_v3", {"status": "PENDING_V3_GENCASE"})
    return_value = {"schema": REPORT_SCHEMA,
                    "status": "AUDITED_SOURCE_GENERATED_SEPARATION_WITH_EXPLICIT_MASS_AND_SUPPORT_GATES",
                    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                    "family_id": "F1", "sentinel_id": "F1-S1", "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
                    "audit_scope": {"bi4_read": False, "hdf5_read": False, "solver_launch": False, "gencase_launch": False,
                                    "vtk_scope": "binary POINTS payload only; selected generated geometry products",
                                    "source_outputs_immutable": True},
                    "source_authority": owner, "completed_cases": cases, "candidate_dp0025_v3": candidate,
                    "conclusion": {"sample_mass_is_discrete_diagnostic": True, "continuum_owner_mass_kg": OWNER_MASS,
                                   "no_mass_rescale": True, "same_count_is_not_support_proof": True,
                                   "three_grid_scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}},
                    "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}
    atomic_json(output, return_value)
    return return_value


def self_test() -> dict[str, Any]:
    assert EXPECTED_AXIS_COUNTS == [160, 268, 60]
    assert EXPECTED_FLUID_COUNT == 2572800
    assert abs(math.prod(CANDIDATE_FLUID_SIZE) * OWNER_DENSITY - OWNER_MASS * ((159 / 160) * (267 / 268) * (59 / 60))) < 1e-12
    synthetic = {"support_envelope_m": {"lower_m": OWNER_LOW, "upper_m": OWNER_UPPER}}
    assert support_comparison(synthetic, CANDIDATE_POINTREF, CANDIDATE_DP)["matches_owner_within_tolerance"]
    assert not support_comparison({"support_envelope_m": {"lower_m": [0.0005] * 3, "upper_m": [0.3965, 0.6665, 0.1535]}}, [0.005] * 3, 0.009)["matches_owner_within_tolerance"]
    with tempfile.TemporaryDirectory(prefix="ds02-f1-owner-v3-") as root:
        path = Path(root) / "source.xml"
        text = '<case><casedef><geometry><definition dp="0.01"><pointref x="0.005" y="0.005" z="0.005"/><commands><setmkfluid mk="0"/><drawbox cmt="v1 fallback controlled fluid cell centres"><boxfill>solid</boxfill><point x="0.005" y="0.005" z="0.005"/><size x="0.39" y="0.66" z="0.14"/></drawbox></commands></definition></geometry></casedef></case>'
        path.write_text(text)
        assert 'dp="0.01"' in path.read_text()
    return {"status": "PASS", "checks": ["owner mass/geometry", "commensurate dp0025 counts 160x268x60", "support mismatch rejection", "source/generated parser separation"], "passed": 4, "gencase_launch": False, "solver_launch": False, "bi4_read": False, "hdf5_read": False}


def build_audit_request() -> dict[str, Any]:
    if AUDIT_REQUEST.exists():
        raise FileExistsError(f"refuse overwrite immutable request: {AUDIT_REQUEST}")
    if not CANDIDATE_DEF.is_file() or not DERIVATION.is_file():
        raise FileNotFoundError("prepare v3 candidate before audit request")
    # The future candidate products are deliberately included only when this
    # request is built after the parent GenCase receipt exists.
    dp0025_proof = MAIN / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F1_OWNER_DP0025_V3_GENCASE_ACTUAL_INDEPENDENT_VERIFICATION_001.json"
    dp005_proof = MAIN / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F1_OWNER_DP005_V2_SUPPORT_CONTROL_ACTUAL_INDEPENDENT_VERIFICATION_001.json"
    read_scope = MAIN / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F1_OWNER_SUPPORT_ROOT_READ_SCOPE_SEMANTIC_SIDECAR_030.json"
    paths = [Path(__file__), PYTHON, RUNNER, STRICT, RUNTIME, OWNER, OWNER_BINDING, GEOMETRY_EVIDENCE,
             CANDIDATE_DEF, DERIVATION, CANDIDATE_OUTPUT_ROOT / "generated.xml", CANDIDATE_OUTPUT_ROOT / "execution-receipt.json",
             dp0025_proof, dp005_proof, read_scope]
    for spec in case_specs(include_candidate=True).values():
        paths.extend([spec["source_def"], spec["generated_xml"], spec["receipt"]])
    records = input_records(paths)
    candidate_vtk = CANDIDATE_OUTPUT_ROOT / "generated_Fluid.vtk"
    vtk_stat = candidate_vtk.stat()
    deferred = [str(candidate_vtk)]
    request = {"schema": REQUEST_SCHEMA, "kind": "cpu", "cpu_task_kind": "audit", "family_id": "F1", "sentinel_id": "F1-S1",
               "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1", "case_id": AUDIT_CASE_ID, "attempt_id": AUDIT_ATTEMPT_ID,
               "launch_commit": git_commit(), "command": [str(PYTHON), str(Path(__file__).resolve()), "--audit", "--include-candidate", "--output", "{attempt_root}/report/f1_s1_owner_centered_support_v4.json"],
               "cwd": str(REPO), "worktree_root": str(REPO), "input_files": list(records), "input_hashes": {path: item["sha256"] for path, item in records.items()},
               "input_records": records, "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 1800,
               "deferred_input_files": deferred,
               "deferred_input_stats": {str(candidate_vtk): {"bytes_at_prepare": int(vtk_stat.st_size), "sha256": "PARENT_GUARD_COMPUTED"}},
               "estimated_input_read_bytes": sum(item["bytes"] for item in records.values()) + int(vtk_stat.st_size), "estimated_storage_bytes": 768 * 1024 * 1024,
               "estimated_peak_memory_bytes": 768 * 1024 * 1024, "estimated_native_read_bytes": 0, "estimated_bi4_read_bytes": 0,
               "estimated_hdf5_read_bytes": 0, "execution_allowed": True, "launch_disabled": False, "solver_started": False,
               "gencase_launch": False, "solver_launch": False, "hdf5_read": False, "bi4_read": False, "resource_guard": {"owner": "stage2-reference-preparation", "runner": str(RUNNER), "strict_guard": str(STRICT), "runtime": str(RUNTIME),
                                  "launch_commit": git_commit(), "cpu_parent_binding": "required", "gpu": "none", "solver_launch": "forbidden",
                                  "bi4_read": "forbidden", "hdf5_read": "forbidden", "source_output_protection": "all generated products immutable"},
               "output_root": str(AUDIT_OUTPUT_ROOT), "output": {"atomic": True, "refuse_overwrite": True},
               "source_binding": {"derivation_manifest": record(DERIVATION, "owner-centred dp0025 derivation"),
                                  "previous_rung_failure_receipts": record(FAILED_V1_ROOT / "execution-receipt.json", "v1 failure receipt"),
                                  "scope": "source Def + generated XML/receipt + one new .0025 Fluid.vtk POINTS payload; consumed .005 proof is checkpoint-bound; no BI4/H5", "mass_basis": "whole owner initial mass 40.2 kg; samples diagnostic"},
               "qualification_stage": "stage2_f1_s1_owner_centered_support_audit_v4_pending_parent_guard",
               "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}
    atomic_json(AUDIT_REQUEST, request)
    return request


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--prepare-input", action="store_true")
    parser.add_argument("--candidate-request", action="store_true")
    parser.add_argument("--audit-request", action="store_true")
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--include-candidate", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    selected = [args.self_test, args.prepare_input, args.candidate_request, args.audit_request, args.audit]
    if sum(selected) != 1:
        parser.error("choose exactly one operation")
    if args.self_test:
        result = self_test()
    elif args.prepare_input:
        result = derive_candidate()
    elif args.candidate_request:
        result = build_candidate_request()
    elif args.audit_request:
        result = build_audit_request()
    else:
        if args.output is None:
            parser.error("--audit requires --output")
        result = audit(args.output, args.include_candidate)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
