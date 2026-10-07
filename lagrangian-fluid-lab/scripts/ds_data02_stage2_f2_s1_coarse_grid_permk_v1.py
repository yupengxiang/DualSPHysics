#!/usr/bin/env python3
"""Prepare and audit a bounded F2-S1 coarse GenCase per-MK mass study.

The study has exactly three already prepared source-bound input definitions at
dp=0.0125, 0.0126, and 0.0127 m.  Their spacing is 25, 26, and 27 percent
above the frozen dp=0.01 source, so this is a small lattice-breakpoint probe,
not an unbounded mass search.  The candidate definitions are checked against
the immutable source definition after removing only the declared ``dp`` and
motion-file-name changes.  The motion bytes, geometry, fill, controls, and
initial source remain fixed.

``prepare`` writes new requests only.  ``audit`` consumes one completed
GenCase receipt and its generated XML, and records actual per-mkfluid counts
and masses.  It never launches GenCase, a solver, PartVTKOut, HDF5, CFD, or a
model.  Whole-sample mass is a pre-solver diagnostic gate; per-MK comparisons
are measured against the frozen dp=0.01 generated source and remain
diagnostic.  No particle-mass rescaling or tolerance widening is accepted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Iterable
import xml.etree.ElementTree as ET


SCRIPT = Path(__file__).resolve()
REPO = SCRIPT.parents[2]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
REFERENCE_WORKTREE = Path("/home/jade/.codex/worktrees/ds-data-02-stage2-reference/DualSPHysics")
REQUEST_ROOT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f2-s1-coarse-grid-permk-v1"
MANIFEST_PATH = REQUEST_ROOT / "coarse-grid-permk-v1-manifest.json"

VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
GENCASE = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64")
RUNTIME = REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v4.py"
DISPATCH = REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v4.py"
STRICT = REPO / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v4.py"

PHYSICAL_CASE_ID = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
SOURCE_DEF = DATA_ROOT / (
    "families/F2/F2_FIRST48_REMAINING24_SOURCE_ROOT801/"
    "root-stage1-f2-first48-remaining24-registered-source-generation-root801/"
    "source/source/F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_"
    "DP010_SPATIAL_REFERENCE_SAVE010_Def.xml"
)
SOURCE_MOTION = SOURCE_DEF.with_name(SOURCE_DEF.name.replace("_Def.xml", "_motion.dat"))
SOURCE_RECEIPT = DATA_ROOT / (
    "families/F2/F2_S1_PREFLIGHT_NATIVE_DP010_DENSE_CFL020/"
    "f2_s1_preflight_native_dp010_dense_cfl020-003/execution-receipt.json"
)
SOURCE_GENERATED_XML = DATA_ROOT / (
    "families/F2/F2_S1_PREFLIGHT_NATIVE_DP010_DENSE_CFL020/"
    "f2_s1_preflight_native_dp010_dense_cfl020-003/generated.xml"
)

TARGET_DP_M = 0.01
TARGET_MASS_KG = 21.114
PASS_RELATIVE = 0.01
HARD_UPPER_RELATIVE = 0.02
PER_MK_WHOLE_TARGET_GATE = 0.03
SCHEMA = "ds02.stage2.f2-s1.coarse-grid-permk.v1"
AUDIT_SCHEMA = "ds02.stage2.f2-s1.coarse-grid-permk-audit.v1"
REQUEST_SCHEMA = "ds02.request.v1"

# These are immutable, previously prepared Def/motion bytes.  The new study
# gives each case a new identity/attempt and never edits an old request or
# receipt.  dp=.0125 was prepared in the preflight input set; .0126/.0127
# were prepared in the phase-probe input set.
CANDIDATE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "dp_m": 0.0125,
        "case_id": "F2_S1_COARSE_GRID_PERMK_DP01250",
        "attempt_id": "f2-s1-coarse-grid-permk-dp01250-v1-001",
        "definition": REFERENCE_WORKTREE / (
            "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/"
            "f2_s1_preflight_inputs/coarse_dp0125/F2_S1_PREFLIGHT_COARSE_DP0125_Def.xml"
        ),
        "motion": REFERENCE_WORKTREE / (
            "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/"
            "f2_s1_preflight_inputs/coarse_dp0125/F2_S1_PREFLIGHT_COARSE_DP0125_motion.dat"
        ),
        "legacy_input_identity": "F2_S1_PREFLIGHT_COARSE_DP0125",
    },
    {
        "dp_m": 0.0126,
        "case_id": "F2_S1_COARSE_GRID_PERMK_DP01260",
        "attempt_id": "f2-s1-coarse-grid-permk-dp01260-v1-001",
        "definition": REFERENCE_WORKTREE / (
            "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/"
            "f2_s1_coarse_phase_probe_inputs/dp0p0126/F2_S1_COARSE_PHASE_PROBE_DP01260_Def.xml"
        ),
        "motion": REFERENCE_WORKTREE / (
            "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/"
            "f2_s1_coarse_phase_probe_inputs/dp0p0126/F2_S1_COARSE_PHASE_PROBE_DP01260_motion.dat"
        ),
        "legacy_input_identity": "F2_S1_COARSE_PHASE_PROBE_DP01260",
    },
    {
        "dp_m": 0.0127,
        "case_id": "F2_S1_COARSE_GRID_PERMK_DP01270",
        "attempt_id": "f2-s1-coarse-grid-permk-dp01270-v1-001",
        "definition": REFERENCE_WORKTREE / (
            "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/"
            "f2_s1_coarse_phase_probe_inputs/dp0p0127/F2_S1_COARSE_PHASE_PROBE_DP01270_Def.xml"
        ),
        "motion": REFERENCE_WORKTREE / (
            "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/"
            "f2_s1_coarse_phase_probe_inputs/dp0p0127/F2_S1_COARSE_PHASE_PROBE_DP01270_motion.dat"
        ),
        "legacy_input_identity": "F2_S1_COARSE_PHASE_PROBE_DP01270",
    },
)


class ProbeError(RuntimeError):
    """Raised when a source, request, receipt, or generated XML is unsafe."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise ProbeError(f"{label} is missing: {path}")
    return path


def file_record(value: str | Path, label: str = "file") -> dict[str, Any]:
    path = require_file(value, label)
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)}


def read_json(value: str | Path, label: str) -> tuple[Path, dict[str, Any]]:
    path = require_file(value, label)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProbeError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ProbeError(f"{label} is not a JSON object: {path}")
    return path, payload


def atomic_json(path: Path, payload: Any, *, refuse_existing: bool = True) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if refuse_existing and path.exists():
        raise ProbeError(f"refuse to overwrite existing file: {path}")
    encoded = (json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def git_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def local_tag(node: ET.Element) -> str:
    return node.tag.rsplit("}", 1)[-1]


def iter_tag(root: ET.Element, wanted: str) -> Iterable[ET.Element]:
    return (node for node in root.iter() if local_tag(node) == wanted)


def xml_semantic_signature(path: Path) -> list[dict[str, Any]]:
    """Normalize only comments, whitespace, dp, and motion filename.

    The caller separately checks the declared dp and motion filename.  Every
    other element, attribute, and non-whitespace text value must match the
    frozen source definition.
    """
    root = ET.parse(path).getroot()
    result: list[dict[str, Any]] = []

    def walk(node: ET.Element, parent_path: str) -> None:
        tag = local_tag(node)
        current_path = f"{parent_path}/{tag}"
        attrs = dict(node.attrib)
        if tag == "definition":
            attrs.pop("dp", None)
        if tag == "file" and parent_path.endswith("/mvrotfile"):
            attrs.pop("name", None)
        text = (node.text or "").strip()
        result.append({"path": current_path, "attributes": sorted(attrs.items()), "text": text})
        for child in node:
            walk(child, current_path)

    walk(root, "")
    return result


def signature_digest(signature: list[dict[str, Any]]) -> str:
    encoded = json.dumps(signature, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def definition_dp(path: Path) -> float:
    root = ET.parse(path).getroot()
    nodes = [node for node in iter_tag(root, "definition") if "dp" in node.attrib]
    if len(nodes) != 1:
        raise ProbeError(f"{path}: expected one definition dp, found {len(nodes)}")
    try:
        value = float(nodes[0].attrib["dp"])
    except ValueError as exc:
        raise ProbeError(f"{path}: invalid definition dp") from exc
    if not math.isfinite(value) or value <= 0:
        raise ProbeError(f"{path}: non-positive definition dp")
    return value


def motion_file_names(path: Path) -> list[str]:
    root = ET.parse(path).getroot()
    names: list[str] = []

    def walk(node: ET.Element, parent_path: str) -> None:
        tag = local_tag(node)
        current = f"{parent_path}/{tag}"
        if tag == "file" and parent_path.endswith("/mvrotfile"):
            name = node.attrib.get("name")
            if not isinstance(name, str) or not name:
                raise ProbeError(f"{path}: motion file name is missing")
            names.append(name)
        for child in node:
            walk(child, current)

    walk(root, "")
    return names


def validate_candidate_spec(spec: dict[str, Any]) -> dict[str, Any]:
    definition = require_file(spec["definition"], f"candidate Def for {spec['case_id']}")
    motion = require_file(spec["motion"], f"candidate motion for {spec['case_id']}")
    source_def = require_file(SOURCE_DEF, "continuous source Def")
    source_motion = require_file(SOURCE_MOTION, "continuous source motion")
    expected_dp = float(spec["dp_m"])
    actual_dp = definition_dp(definition)
    if not math.isclose(actual_dp, expected_dp, rel_tol=0.0, abs_tol=1e-12):
        raise ProbeError(f"{definition}: dp {actual_dp} differs from registered {expected_dp}")
    if not (0.0125 <= actual_dp <= 0.0127):
        raise ProbeError(f"{definition}: dp is outside bounded .0125-.0127 study")
    if sha256(motion) != sha256(source_motion):
        raise ProbeError(f"{motion}: motion bytes differ from continuous source motion")
    source_names = motion_file_names(source_def)
    candidate_names = motion_file_names(definition)
    if len(source_names) != 1 or len(candidate_names) != 1:
        raise ProbeError("continuous source and candidate must each have one mvrotfile name")
    if Path(source_names[0]).name != source_motion.name:
        raise ProbeError("source Def motion filename is not the registered source motion")
    if Path(candidate_names[0]).name != motion.name:
        raise ProbeError("candidate Def motion filename does not match candidate motion input")
    source_signature = xml_semantic_signature(source_def)
    candidate_signature = xml_semantic_signature(definition)
    if source_signature != candidate_signature:
        raise ProbeError(f"{definition}: geometry/control/motion semantics differ beyond dp/file name")
    return {
        "definition": file_record(definition, "candidate Def"),
        "motion": file_record(motion, "candidate motion"),
        "source_definition": file_record(source_def, "continuous source Def"),
        "source_motion": file_record(source_motion, "continuous source motion"),
        "candidate_motion_filename": candidate_names[0],
        "source_motion_filename": source_names[0],
        "dp_m": expected_dp,
        "semantic_signature_sha256": signature_digest(source_signature),
        "semantic_changes": [
            "casedef/geometry/definition/@dp",
            "casedef/motion/**/mvrotfile/file/@name",
        ],
    }


def parse_generated_xml(path: str | Path) -> dict[str, Any]:
    """Extract actual generated particle counts and uniform mass from XML."""
    xml_path = require_file(path, "generated XML")
    root = ET.parse(xml_path).getroot()
    mass_nodes = [node for node in iter_tag(root, "massfluid") if node.attrib.get("value") is not None]
    if len(mass_nodes) != 1:
        raise ProbeError(f"{xml_path}: expected exactly one generated massfluid value")
    try:
        massfluid = float(mass_nodes[0].attrib["value"])
    except ValueError as exc:
        raise ProbeError(f"{xml_path}: massfluid is not numeric") from exc
    if not math.isfinite(massfluid) or massfluid <= 0:
        raise ProbeError(f"{xml_path}: massfluid must be positive and finite")
    particles_nodes = [node for node in iter_tag(root, "particles")]
    if len(particles_nodes) != 1:
        raise ProbeError(f"{xml_path}: expected exactly one particles node")
    particles = particles_nodes[0]
    blocks: list[dict[str, Any]] = []
    for node in particles:
        if local_tag(node) != "fluid":
            continue
        required = ("mkfluid", "mk", "begin", "count")
        if any(key not in node.attrib for key in required):
            # The generated summary is nested, but a direct malformed fluid
            # block is not silently treated as a summary.
            continue
        try:
            begin = int(node.attrib["begin"])
            count = int(node.attrib["count"])
        except ValueError as exc:
            raise ProbeError(f"{xml_path}: generated fluid begin/count is not integer") from exc
        if begin < 0 or count <= 0:
            raise ProbeError(f"{xml_path}: generated fluid begin/count is invalid")
        blocks.append({"mkfluid": str(node.attrib["mkfluid"]), "mk": str(node.attrib["mk"]), "begin": begin, "count": count})
    if not blocks:
        raise ProbeError(f"{xml_path}: no direct generated fluid blocks")
    if len({block["mkfluid"] for block in blocks}) != len(blocks):
        raise ProbeError(f"{xml_path}: duplicate mkfluid block")
    ordered = sorted(blocks, key=lambda block: block["begin"])
    for previous, current in zip(ordered, ordered[1:]):
        if current["begin"] != previous["begin"] + previous["count"]:
            raise ProbeError(f"{xml_path}: generated fluid blocks are not contiguous")
    by_mk = {
        block["mkfluid"]: {
            "mk": block["mk"],
            "begin": block["begin"],
            "count": block["count"],
            "massfluid_kg": massfluid,
            "sample_mass_kg": block["count"] * massfluid,
        }
        for block in blocks
    }
    dp_values = [node.attrib["dp"] for node in iter_tag(root, "definition") if node.attrib.get("dp") is not None]
    if len(dp_values) != 1:
        raise ProbeError(f"{xml_path}: expected exactly one generated definition dp")
    return {
        "file": file_record(xml_path, "generated XML"),
        "definition_dp_values": dp_values,
        "massfluid_kg": massfluid,
        "fluid_blocks": blocks,
        "total_fluid_particles": sum(block["count"] for block in blocks),
        "initial_fluid_sample_mass_kg": sum(value["sample_mass_kg"] for value in by_mk.values()),
        "by_mkfluid": by_mk,
    }


def mass_gate(actual_mass: float, target_mass: float = TARGET_MASS_KG) -> dict[str, Any]:
    relative = (actual_mass - target_mass) / target_mass
    absolute = abs(relative)
    if absolute <= PASS_RELATIVE:
        status = "WITHIN_WHOLE_TARGET_1PCT_DIAGNOSTIC"
    elif absolute <= HARD_UPPER_RELATIVE:
        status = "MARGINAL_WHOLE_TARGET_1_TO_2PCT_DIAGNOSTIC"
    else:
        status = "HARD_FAIL_WHOLE_TARGET_GT2PCT"
    return {
        "status": status,
        "target_initial_fluid_sample_mass_kg": target_mass,
        "actual_initial_fluid_sample_mass_kg": actual_mass,
        "delta_kg": actual_mass - target_mass,
        "relative_error": relative,
        "error_pct": relative * 100.0,
        "pass_relative_tolerance": PASS_RELATIVE,
        "hard_upper_relative_tolerance": HARD_UPPER_RELATIVE,
        "particle_mass_rescale": False,
        "threshold_widening": False,
        "qualification": "DIAGNOSTIC_ONLY_NO_SOLVER_CREDIT",
    }


def per_mk_diagnostics(baseline: dict[str, Any], actual: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    keys = sorted(set(baseline["by_mkfluid"]) | set(actual["by_mkfluid"]), key=str)
    for key in keys:
        if key not in baseline["by_mkfluid"] or key not in actual["by_mkfluid"]:
            rows.append({"mkfluid": key, "status": "MISSING_MK_BLOCK_DIAGNOSTIC_ONLY"})
            continue
        source = baseline["by_mkfluid"][key]
        candidate = actual["by_mkfluid"][key]
        delta = candidate["sample_mass_kg"] - source["sample_mass_kg"]
        fraction = abs(delta) / TARGET_MASS_KG
        rows.append({
            "mkfluid": key,
            "mk": candidate["mk"],
            "source": source,
            "candidate": candidate,
            "delta_kg": delta,
            "absolute_delta_fraction_of_frozen_whole_target": fraction,
            "absolute_delta_pct_of_frozen_whole_target": fraction * 100.0,
            "frozen_per_mk_gate_3pct_of_whole_target": PER_MK_WHOLE_TARGET_GATE,
            "status": "WITHIN_3PCT_DIAGNOSTIC" if fraction <= PER_MK_WHOLE_TARGET_GATE else "OVER_3PCT_DIAGNOSTIC",
            "qualification": "DIAGNOSTIC_ONLY_NO_PER_MK_RESCALE_OR_ACCEPTANCE",
        })
    return rows


def source_receipt_inputs(source_receipt: dict[str, Any]) -> tuple[Path, Path]:
    request = source_receipt.get("request")
    if not isinstance(request, dict):
        raise ProbeError("source receipt lacks request object")
    files = request.get("input_files")
    if not isinstance(files, list):
        raise ProbeError("source receipt lacks input_files")
    definitions = [Path(value) for value in files if isinstance(value, str) and value.endswith("_Def.xml")]
    motions = [Path(value) for value in files if isinstance(value, str) and value.endswith("_motion.dat")]
    if len(definitions) != 1 or len(motions) != 1:
        raise ProbeError("source receipt must bind exactly one Def and motion input")
    return require_file(definitions[0], "source receipt Def input"), require_file(motions[0], "source receipt motion input")


def validate_source_baseline() -> dict[str, Any]:
    receipt_path, receipt = read_json(SOURCE_RECEIPT, "frozen dp=.01 source receipt")
    generated = require_file(SOURCE_GENERATED_XML, "frozen dp=.01 generated XML")
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ProbeError("frozen dp=.01 source receipt is not completed code 0")
    request = receipt.get("request", {})
    if request.get("family_id") != "F2" or request.get("case_id") != "F2_S1_PREFLIGHT_NATIVE_DP010_DENSE_CFL020":
        raise ProbeError("frozen source receipt identity is not F2-S1 dp=.01")
    scope = request.get("scope", {})
    if scope.get("physical_case_id") != PHYSICAL_CASE_ID or scope.get("dp_m") != TARGET_DP_M:
        raise ProbeError("frozen source receipt physical identity or dp differs")
    if scope.get("gencase_only") is not True or scope.get("solver_started") is not False or scope.get("full_time_hdf5_read") is not False:
        raise ProbeError("frozen source receipt is not GenCase-only")
    declared_root = Path(str(receipt.get("output_root", ""))).expanduser().resolve()
    if not declared_root.is_dir() or generated.resolve() != (declared_root / "generated.xml").resolve():
        raise ProbeError("frozen source generated XML is not receipt output_root/generated.xml")
    source_receipt_def, source_receipt_motion = source_receipt_inputs(receipt)
    request_hashes = request.get("input_hashes", {})
    for path in (source_receipt_def, source_receipt_motion):
        expected = request_hashes.get(str(path)) or request_hashes.get(str(path.resolve()))
        if expected != sha256(path):
            raise ProbeError(f"source receipt input hash does not match {path}")
    if xml_semantic_signature(source_receipt_def) != xml_semantic_signature(SOURCE_DEF):
        raise ProbeError("frozen source receipt Def differs from continuous source semantics")
    if sha256(source_receipt_motion) != sha256(SOURCE_MOTION):
        raise ProbeError("frozen source receipt motion differs from continuous source bytes")
    parsed = parse_generated_xml(generated)
    if not math.isclose(float(parsed["definition_dp_values"][0]), TARGET_DP_M, rel_tol=0.0, abs_tol=1e-12):
        raise ProbeError("frozen source generated XML dp is not .01")
    if not math.isclose(parsed["initial_fluid_sample_mass_kg"], TARGET_MASS_KG, rel_tol=0.0, abs_tol=1e-12):
        raise ProbeError("frozen source generated XML mass no longer equals 21.114 kg")
    return {
        "receipt": file_record(receipt_path, "frozen source receipt"),
        "generated_xml": parsed,
        "source_receipt_def": file_record(source_receipt_def, "source receipt Def"),
        "source_receipt_motion": file_record(source_receipt_motion, "source receipt motion"),
        "source_definition": file_record(SOURCE_DEF, "continuous source Def"),
        "source_motion": file_record(SOURCE_MOTION, "continuous source motion"),
        "request_identity": {"family_id": request["family_id"], "case_id": request["case_id"], "attempt_id": request["attempt_id"]},
    }


def build_manifest() -> dict[str, Any]:
    baseline = validate_source_baseline()
    candidates = []
    for spec in CANDIDATE_SPECS:
        validation = validate_candidate_spec(spec)
        candidates.append({
            "case_id": spec["case_id"],
            "attempt_id": spec["attempt_id"],
            "legacy_input_identity": spec["legacy_input_identity"],
            "physical_case_id": PHYSICAL_CASE_ID,
            "dp_m": spec["dp_m"],
            "spacing_above_dp010_fraction": spec["dp_m"] / TARGET_DP_M - 1.0,
            "definition": validation["definition"],
            "motion": validation["motion"],
            "continuous_source": {"definition": validation["source_definition"], "motion": validation["source_motion"]},
            "candidate_motion_filename": validation["candidate_motion_filename"],
            "semantic_signature_sha256": validation["semantic_signature_sha256"],
            "semantic_changes": validation["semantic_changes"],
            "status": "PREPARED_NEW_ATTEMPT_NOT_RUN",
            "whole_mass_status": "UNKNOWN_UNTIL_COMPLETED_GENCASE_XML",
            "per_mk_status": "UNKNOWN_UNTIL_COMPLETED_GENCASE_XML",
        })
    return {
        "schema": SCHEMA,
        "status": "PREPARED_REQUESTS_NOT_RUN",
        "family_id": "F2",
        "physical_case_id": PHYSICAL_CASE_ID,
        "study_scope": {
            "candidate_count": 3,
            "candidate_dp_m": [0.0125, 0.0126, 0.0127],
            "spacing_separation_from_dp010": "25%, 26%, 27%; all >=10%",
            "selection_rule": "bounded source-lattice breakpoint/count probes; no unbounded mass point search",
            "preserved_prior": "dp=.01258 remains consumed historical evidence and is not relabelled or included",
            "continuous_source_rule": "same source geometry, fill, motion axis/duration, gravity, controls and initial recipe; only candidate dp and Def motion filename differ",
            "particle_mass_rescale": False,
            "threshold_widening": False,
            "solver_or_h5": "forbidden",
        },
        "mass_gate": {
            "target_initial_fluid_sample_mass_kg": TARGET_MASS_KG,
            "pass_relative_tolerance": PASS_RELATIVE,
            "hard_upper_relative_tolerance": HARD_UPPER_RELATIVE,
            "rule": "actual generated fluid count times actual generated massfluid; >2% is a hard failure",
            "per_mk_reference": "actual frozen dp=.01 generated XML blocks",
            "per_mk_gate": "absolute per-MK delta <=3% of frozen whole target is diagnostic only",
            "qualification": "none; GenCase evidence cannot grant QN/QE/dynamics credit",
        },
        "frozen_source": baseline,
        "candidates": candidates,
        "read_policy": {"gencase_started": False, "solver_started": False, "h5_opened": False, "partvtkout_started": False, "cfd_or_model_run": False},
    }


def unique_paths(paths: Iterable[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for value in paths:
        path = require_file(value, f"request input {Path(value).name}")
        if str(path) not in seen:
            result.append(path)
            seen.add(str(path))
    return result


def request_for(candidate: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    spec = next(spec for spec in CANDIDATE_SPECS if spec["case_id"] == candidate["case_id"])
    definition = require_file(spec["definition"], "candidate Def")
    motion = require_file(spec["motion"], "candidate motion")
    source_receipt_def, source_receipt_motion = source_receipt_inputs(read_json(SOURCE_RECEIPT, "source receipt")[1])
    inputs = unique_paths([
        SCRIPT, VENV, GENCASE, RUNTIME, DISPATCH, STRICT, manifest_path,
        SOURCE_DEF, SOURCE_MOTION, SOURCE_RECEIPT, SOURCE_GENERATED_XML,
        source_receipt_def, source_receipt_motion, definition, motion,
    ])
    request = {
        "schema": REQUEST_SCHEMA,
        "family_id": "F2",
        "case_id": candidate["case_id"],
        "physical_case_id": PHYSICAL_CASE_ID,
        "attempt_id": candidate["attempt_id"],
        "kind": "cpu",
        "cpu_task_kind": "gencase",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 300,
        "estimated_storage_bytes": 64 * 1024 * 1024,
        "estimated_peak_memory_bytes": 512 * 1024 * 1024,
        "worktree_root": str(REPO),
        "cwd": str(definition.parent),
        "command": [str(GENCASE), str(definition.with_suffix("")), "{attempt_root}/generated", "-save:all"],
        "input_files": [str(path) for path in inputs],
        "input_hashes": {str(path): sha256(path) for path in inputs},
        "resource_guard": {
            "owner": "root",
            "runner": str(DISPATCH),
            "strict_guard": str(STRICT),
            "runtime": str(RUNTIME),
            "launch_commit": git_head(),
            "cpu_parent_binding": "required",
            "cpu_threads": 1,
            "omp_threads": 1,
            "gpu": "none",
            "gpu_uuid": "none",
            "solver_launch": "forbidden",
            "hdf5_read": "forbidden",
            "estimated_cpu_core_hours": 300 / 3600,
            "estimated_new_storage_bytes": 64 * 1024 * 1024,
        },
        "source_binding": {
            "schema": "ds02.stage2.f2-s1.coarse-grid-permk-binding.v1",
            "manifest": {"path": str(manifest_path.resolve()), "sha256": sha256(manifest_path)},
            "candidate_definition": candidate["definition"],
            "candidate_motion": candidate["motion"],
            "continuous_source": candidate["continuous_source"],
            "semantic_signature_sha256": candidate["semantic_signature_sha256"],
            "frozen_dp010_receipt": file_record(SOURCE_RECEIPT, "frozen source receipt"),
            "frozen_dp010_generated_xml": file_record(SOURCE_GENERATED_XML, "frozen source generated XML"),
            "candidate_dp_m": candidate["dp_m"],
            "spacing_above_dp010_fraction": candidate["spacing_above_dp010_fraction"],
            "physical_case_id": PHYSICAL_CASE_ID,
            "particle_mass_rescale": False,
            "threshold_widening": False,
            "per_mk_reference": "frozen dp=.01 generated XML actual blocks",
        },
        "scope": {
            "physical_case_id": PHYSICAL_CASE_ID,
            "continuous_recipe_source": "frozen F2-S1 source Def/motion semantics",
            "dp_m": candidate["dp_m"],
            "same_initial_geometry_and_motion": True,
            "gencase_only": True,
            "solver_started": False,
            "full_time_hdf5_read": False,
            "gpu_uuid_lease": "none",
            "particle_mass_rescale": False,
            "threshold_widening": False,
        },
        "output_protection": {"refuse_overwrite": True, "attempt_root_must_not_exist_at_dispatch": True},
        "launch": True,
        "launch_allowed": True,
        "execution_allowed": True,
        "launch_owner": "root",
        "shared_lease_required": True,
        "foreign_process_protection_required": True,
        "solver_launch_forbidden": True,
        "hdf5_read_forbidden": True,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN"},
        "request_note": "New CPU1 GenCase-only bounded F2-S1 lattice probes; actual per-MK/whole-mass audit follows a completed receipt. No solver, H5, CFD, model, mass rescale, or widened gate.",
    }
    return request


def prepare(output_dir: Path = REQUEST_ROOT) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest()
    manifest_path = output_dir / "coarse-grid-permk-v1-manifest.json"
    if manifest_path.exists():
        raise ProbeError(f"preserve existing manifest: {manifest_path}")
    atomic_json(manifest_path, manifest)
    requests = []
    for candidate in manifest["candidates"]:
        request_path = output_dir / f"{candidate['case_id'].lower()}.json"
        if request_path.exists():
            raise ProbeError(f"preserve existing request: {request_path}")
        request = request_for(candidate, manifest_path)
        atomic_json(request_path, request)
        requests.append({"path": str(request_path), "sha256": sha256(request_path), "case_id": candidate["case_id"], "attempt_id": candidate["attempt_id"]})
    return {"status": "PREPARED_REQUESTS_NOT_RUN", "manifest": str(manifest_path), "manifest_sha256": sha256(manifest_path), "requests": requests, "candidate_count": len(requests)}


def load_request(request_path: Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    path, request = read_json(request_path, "coarse grid request")
    if request.get("schema") != REQUEST_SCHEMA or request.get("family_id") != "F2":
        raise ProbeError("request schema/family differs")
    manifest_meta = request.get("source_binding", {}).get("manifest", {})
    manifest_path = require_file(manifest_meta.get("path", ""), "request manifest")
    if manifest_meta.get("sha256") != sha256(manifest_path):
        raise ProbeError("request manifest digest changed")
    _, manifest = read_json(manifest_path, "request manifest")
    candidates = {item.get("case_id"): item for item in manifest.get("candidates", [])}
    candidate = candidates.get(request.get("case_id"))
    if not isinstance(candidate, dict):
        raise ProbeError("request case is absent from exact manifest membership")
    if request.get("attempt_id") != candidate.get("attempt_id"):
        raise ProbeError("request attempt differs from manifest membership")
    return path, request, candidate


def validate_request_sources(request_path: Path, request: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    spec = next((value for value in CANDIDATE_SPECS if value["case_id"] == request.get("case_id")), None)
    if spec is None:
        raise ProbeError("request case is not one of the three bounded candidates")
    expected_candidate = validate_candidate_spec(spec)
    if request.get("physical_case_id") != PHYSICAL_CASE_ID or request.get("cpu_threads") != 1 or request.get("omp_threads") != 1:
        raise ProbeError("request identity or CPU1 contract differs")
    if request.get("kind") != "cpu" or request.get("cpu_task_kind") != "gencase":
        raise ProbeError("request is not a CPU GenCase task")
    if request.get("scope", {}).get("gencase_only") is not True or request.get("scope", {}).get("solver_started") is not False:
        raise ProbeError("request does not declare GenCase-only scope")
    if request.get("scope", {}).get("particle_mass_rescale") is not False or request.get("scope", {}).get("threshold_widening") is not False:
        raise ProbeError("request permits mass rescaling or threshold widening")
    if request.get("source_binding", {}).get("candidate_definition", {}).get("sha256") != expected_candidate["definition"]["sha256"]:
        raise ProbeError("request candidate definition binding differs")
    if request.get("source_binding", {}).get("candidate_motion", {}).get("sha256") != expected_candidate["motion"]["sha256"]:
        raise ProbeError("request candidate motion binding differs")
    declared_hashes = request.get("input_hashes", {})
    launch_commit = request.get("resource_guard", {}).get("launch_commit")
    if not isinstance(launch_commit, str) or not launch_commit:
        raise ProbeError("request lacks source launch commit")
    for input_path, expected_hash in declared_hashes.items():
        if sha256(require_file(input_path, "declared request input")) != expected_hash:
            raise ProbeError(f"declared input digest changed: {input_path}")
    command = request.get("command", [])
    if command[:2] != [str(GENCASE), str(Path(expected_candidate["definition"]["path"]).with_suffix(""))] or command[3:] != ["-save:all"]:
        raise ProbeError("request command is not the canonical official GenCase argv")
    if request.get("command", [None, None, None])[2] != "{attempt_root}/generated":
        raise ProbeError("request output is not attempt-root bound")
    return expected_candidate


def receipt_output_root(receipt: dict[str, Any]) -> Path:
    value = receipt.get("output_root")
    if not isinstance(value, str) or not value:
        raise ProbeError("execution receipt lacks output_root")
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise ProbeError(f"receipt output_root is not a directory: {path}")
    return path


def validate_receipt(request_path: Path, request: dict[str, Any], receipt_path: Path, receipt: dict[str, Any], candidate: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ProbeError("execution receipt is not completed code 0")
    if receipt.get("request_sha256") != sha256(request_path):
        raise ProbeError("receipt request digest differs from request bytes")
    receipt_request = receipt.get("request", {})
    for key in ("family_id", "case_id", "attempt_id", "physical_case_id"):
        if receipt_request.get(key) != request.get(key):
            raise ProbeError(f"receipt request {key} differs")
    if receipt.get("input_hashes_at_launch") != request.get("input_hashes"):
        raise ProbeError("receipt launch input hashes differ from request")
    if "input_hashes_after_run" in receipt and receipt.get("input_hashes_after_run") != request.get("input_hashes"):
        raise ProbeError("receipt end input hashes differ from request")
    actual_command = receipt.get("command")
    expected_definition = str(Path(candidate["definition"]["path"]).with_suffix(""))
    if not isinstance(actual_command, list) or len(actual_command) < 4 or actual_command[0] != str(GENCASE) or actual_command[1] != expected_definition:
        raise ProbeError("receipt command does not identify the bound official GenCase and candidate Def")
    if "-save:all" not in actual_command:
        raise ProbeError("receipt command omits canonical -save:all")
    output_root = receipt_output_root(receipt)
    generated = output_root / "generated.xml"
    parsed = parse_generated_xml(generated)
    expected_dp = float(candidate["dp_m"])
    actual_dp = float(parsed["definition_dp_values"][0])
    if not math.isclose(actual_dp, expected_dp, rel_tol=0.0, abs_tol=1e-12):
        raise ProbeError(f"generated XML dp {actual_dp} differs from candidate {expected_dp}")
    candidate_names = motion_file_names(require_file(candidate["definition"]["path"], "candidate Def"))
    generated_names = motion_file_names(generated)
    if not generated_names or any(Path(name).name != Path(candidate_names[0]).name for name in generated_names):
        raise ProbeError("generated XML motion filename differs from bound candidate")
    if receipt.get("fluid_particles") is not None and int(receipt["fluid_particles"]) != parsed["total_fluid_particles"]:
        raise ProbeError("receipt fluid_particles differs from generated XML")
    if receipt.get("total_particles") is not None:
        particles_nodes = [node for node in ET.parse(generated).getroot().iter() if local_tag(node) == "particles"]
        np = particles_nodes[0].attrib.get("np") if particles_nodes else None
        if np is not None and int(receipt["total_particles"]) != int(np):
            raise ProbeError("receipt total_particles differs from generated XML")
    return generated, parsed


def audit(request_path: Path, receipt_path: Path, output: Path) -> dict[str, Any]:
    request_path, request, candidate = load_request(request_path)
    expected_candidate = validate_request_sources(request_path, request, candidate)
    receipt_path, receipt = read_json(receipt_path, "coarse grid execution receipt")
    generated_path, actual = validate_receipt(request_path, request, receipt_path, receipt, expected_candidate)
    baseline = validate_source_baseline()
    baseline_xml = baseline["generated_xml"]
    rows = per_mk_diagnostics(baseline_xml, actual)
    result = {
        "schema": AUDIT_SCHEMA,
        "status": "COMPLETED_GENCASE_PER_MK_DIAGNOSTIC",
        "family_id": "F2",
        "case_id": request["case_id"],
        "attempt_id": request["attempt_id"],
        "physical_case_id": PHYSICAL_CASE_ID,
        "candidate_dp_m": candidate["dp_m"],
        "spacing_above_dp010_fraction": candidate["spacing_above_dp010_fraction"],
        "request": file_record(request_path, "coarse grid request"),
        "receipt": file_record(receipt_path, "coarse grid receipt"),
        "generated_xml": actual,
        "source_binding": {
            "continuous_source": candidate["continuous_source"],
            "semantic_signature_sha256": candidate["semantic_signature_sha256"],
            "frozen_dp010_receipt": baseline["receipt"],
            "frozen_dp010_generated_xml": baseline_xml["file"],
            "frozen_source_per_mk": baseline_xml["by_mkfluid"],
            "request_launch_commit": request["resource_guard"]["launch_commit"],
        },
        "whole_initial_mass_gate": mass_gate(actual["initial_fluid_sample_mass_kg"]),
        "per_mkfluid_diagnostics": rows,
        "interpretation": {
            "actual_generated_count_and_mass": True,
            "per_mk_gate_denominator": "frozen whole dp=.01 source target 21.114 kg",
            "per_mk_gate_is_qualification": False,
            "particle_mass_rescale": False,
            "threshold_widening": False,
            "lattice_breakpoint_probe_only": True,
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
            "QI": "UNKNOWN",
            "QN": "NOT_ASSESSED",
            "QE": "NOT_ASSESSED",
        },
        "read_policy": {"gencase_started": True, "solver_started": False, "h5_opened": False, "partvtkout_started": False, "cfd_or_model_run": False},
    }
    output = output.resolve()
    if output.exists():
        raise ProbeError(f"preserve existing audit sidecar: {output}")
    atomic_json(output, result)
    return {"status": result["status"], "output": str(output), "case_id": result["case_id"], "mass_gate": result["whole_initial_mass_gate"]["status"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--output-dir", type=Path, default=REQUEST_ROOT)
    aud = sub.add_parser("audit")
    aud.add_argument("--request", type=Path, required=True)
    aud.add_argument("--receipt", type=Path, required=True)
    aud.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prepare(args.output_dir) if args.action == "prepare" else audit(args.request, args.receipt, args.output)
    except ProbeError as exc:
        raise SystemExit(f"ProbeError: {exc}")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
