#!/usr/bin/env python3
"""Prepare receipt-bound M4 additional child requests without launching work.

The frozen M3 native auditors are intentionally reused as request targets.  This
worker only turns completed, case-bound H052/H058 NAS outputs into candidate
JSON; it never starts GenCase, a solver, or an auditor and never writes the
root request queue.  Static M4 manifests and templates remain the source of
the contract.  Every generated receipt, generated XML, cohort hash, solver
file, and native audit report is bound from an actual regular file at the time
the candidate is prepared.

Examples (after the root-owned later-batch admission and actual work exist)::

    python prepare_m4_additional_audits.py solver-ready \
        --case UF_F1_MDBC_DP010_H052
    python prepare_m4_additional_audits.py native-exclusions \
        --case UF_F1_MDBC_DP010_H052
    python prepare_m4_additional_audits.py native-frames \
        --case UF_F1_MDBC_DP010_H052

The default output directory is this M4 subtree's ``prepared/`` directory.
An output path outside this subtree is rejected so a preparation mistake cannot
write a root request or a frozen M3 artifact.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import stat
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable, Mapping


SUBTREE = Path(__file__).resolve().parent
UPSTREAM = SUBTREE.parent
DATA02 = UPSTREAM.parent
LAB_ROOT = UPSTREAM.parents[2]
CONVERSION = UPSTREAM / "m2" / "upstream_conversion"
RUNS = Path("/data/nas/jade/Simulation/DualSPHysics/upstream-first/runs/F1")
MOTHER_CASE = "UF_F1_MDBC_DAMBREAK3D"
MOTHER_DEFINITION = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/"
    "DualSPHysics_v5.4/examples/mdbc/04_Dambreak/CaseDamBreak3D_Def.xml"
)
PARTVTK = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/"
    "DualSPHysics_v5.4/bin/linux/PartVTKOut_linux64"
)
DSPH_CONFIG = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/"
    "DualSPHysics_v5.4/bin/linux/DsphConfig.xml"
)
RUNTIME_V2 = LAB_ROOT / "scripts" / "ds_data02_runtime_v2.py"
RUNTIME_V6 = LAB_ROOT / "scripts" / "ds_data02_runtime_v6.py"
M2_INTEGRITY_AUDITOR = CONVERSION / "native_integrity_audit.py"
M2_INTEGRITY_SCHEMA = CONVERSION / "native-integrity-manifest.schema.json"
M2_FRAME_AUDITOR = CONVERSION / "native_frame_identity_scan.py"
M2_FRAME_SCHEMA = CONVERSION / "native-frame-scan-manifest.schema.json"
BI4_ADAPTER = LAB_ROOT / "scripts" / "ds_data02_f5_bi4.py"
SCRIPTS_INIT = LAB_ROOT / "scripts" / "__init__.py"
BI4_DUMP = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/"
    "l1-resume/artifacts/bi4_dump"
)

CHILD_MANIFEST_SCHEMA = "ds-data-02.upstream-first.m3.f1-fine-dp010-t025.case-manifest.v1"
SEMANTIC_DIFF_SCHEMA = "ds-data-02.upstream-first.m3.f1-fine-dp010-t025.semantic-diff.v1"
INTEGRITY_MANIFEST_SCHEMA = "ds-data-02.upstream-first.native-integrity-manifest.v1"
FRAME_MANIFEST_SCHEMA = "ds-data-02.upstream-first.native-frame-scan-manifest.v1"
INTEGRITY_OUTPUT_SCHEMA = "ds-data-02.upstream-first.f1-native-integrity.v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
EXCLUDED_RE = re.compile(r"Excluded particles\.*:\s*([\d,]+)", re.IGNORECASE)
INITIAL_RE = re.compile(r"Particles of simulation \(initial\):\s*([\d,]+)")

CASES: dict[str, dict[str, Any]] = {
    "UF_F1_MDBC_DP010_H052": {
        "depth_m": 0.52,
        "depth_text": "0.52",
        "grid_index": 52,
        "definition": SUBTREE / "UF_F1_MDBC_DP010_H052_Def.xml",
    },
    "UF_F1_MDBC_DP010_H058": {
        "depth_m": 0.58,
        "depth_text": "0.58",
        "grid_index": 58,
        "definition": SUBTREE / "UF_F1_MDBC_DP010_H058_Def.xml",
    },
}


class PreparationError(ValueError):
    """Raised when actual evidence is missing or violates the child contract."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _regular(path: Path, label: str) -> Path:
    path = Path(path).expanduser()
    if path.is_symlink():
        raise PreparationError(f"{label} is a symbolic link: {path}")
    if not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
        raise PreparationError(f"{label} is not a regular file: {path}")
    return path


def _bind(path: Path, label: str) -> dict[str, Any]:
    path = _regular(path, label)
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": _sha256(path)}


def _json(path: Path, label: str) -> dict[str, Any]:
    path = _regular(path, label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PreparationError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise PreparationError(f"{label} must be a JSON object: {path}")
    return value


def _json_text(value: Mapping[str, Any]) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _write_new(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise PreparationError(f"refusing to overwrite prepared output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(_json_text(value))


def _json_binding(path: Path, value: Mapping[str, Any]) -> dict[str, Any]:
    """Bind a JSON file before it is written, using the exact writer bytes."""
    encoded = _json_text(value).encode("utf-8")
    return {"path": str(path), "bytes": len(encoded), "sha256": hashlib.sha256(encoded).hexdigest()}


def _case(case: str) -> dict[str, Any]:
    try:
        return CASES[case]
    except KeyError as exc:
        raise PreparationError(f"unsupported M4 additional case: {case}") from exc


def _case_root(case: str) -> Path:
    return RUNS / case


def _gencase_paths(case: str) -> dict[str, Path]:
    root = _case_root(case) / "gencase-001"
    prefix = root / case
    return {
        "root": root,
        "prefix": prefix,
        "receipt": root / "execution-receipt.json",
        "xml": prefix.with_suffix(".xml"),
        "bi4": prefix.with_suffix(".bi4"),
    }


def _solver_paths(case: str) -> dict[str, Path]:
    root = _case_root(case) / "solver-001"
    return {
        "root": root,
        "receipt": root / "execution-receipt.json",
        "run_out": root / "Run.out",
        "runparts": root / "RunPARTs.csv",
        "data": root / "data",
        "part_out": root / "data" / "PartOut_000.obi4",
        "part_info": root / "data" / "PartInfo.ibi4",
    }


def _require_receipt(path: Path, case: str, attempt: str, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    receipt = _json(path, label)
    if receipt.get("schema") != "ds02.execution-receipt.v1":
        raise PreparationError(f"{label} schema is not ds02.execution-receipt.v1")
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise PreparationError(f"{label} is not completed with returncode 0: {path}")
    request = receipt.get("request")
    if not isinstance(request, Mapping):
        raise PreparationError(f"{label} lacks its bound request")
    if request.get("case_id") != case or request.get("attempt_id") != attempt:
        raise PreparationError(f"{label} request is not bound to {case}/{attempt}")
    return receipt, dict(request)


def _number(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise PreparationError(f"{label} is not numeric: {value!r}") from exc
    if not math.isfinite(number):
        raise PreparationError(f"{label} is not finite: {value!r}")
    return number


def _xml_evidence(case: str) -> dict[str, Any]:
    cfg = _case(case)
    paths = _gencase_paths(case)
    try:
        root = ET.parse(_regular(paths["xml"], "generated XML")).getroot()
    except ET.ParseError as exc:
        raise PreparationError(f"generated XML is not parseable: {paths['xml']}") from exc

    data2d = root.find(".//constants/data2d")
    if data2d is None or data2d.get("value") is None:
        raise PreparationError("generated XML lacks explicit constants/data2d dimension")
    if data2d.get("value", "").lower() in {"1", "true", "yes"}:
        raise PreparationError("generated XML is two-dimensional")

    particles = root.find(".//execution/particles")
    if particles is None or particles.get("np") is None:
        raise PreparationError("generated XML lacks execution particle count")
    try:
        nparticles = int(particles.get("np", ""))
    except ValueError as exc:
        raise PreparationError("generated XML particle count is not an integer") from exc
    if nparticles <= 0:
        raise PreparationError("generated XML particle count is not positive")

    blocks: list[dict[str, Any]] = []
    fluid_blocks: list[dict[str, Any]] = []
    seen: list[tuple[int, int]] = []
    for child in particles:
        if child.tag == "_summary":
            continue
        if child.tag not in {"fixed", "moving", "floating", "fluid"}:
            raise PreparationError(f"generated XML has unsupported particle block <{child.tag}>")
        try:
            begin = int(child.attrib["begin"])
            count = int(child.attrib["count"])
            mk = int(child.attrib["mk"])
        except (KeyError, ValueError) as exc:
            raise PreparationError("generated XML typed block lacks integer begin/count/mk") from exc
        if begin < 0 or count <= 0 or begin + count > nparticles:
            raise PreparationError("generated XML typed block is outside the particle axis")
        if any(begin < old_end and old_begin < begin + count for old_begin, old_end in seen):
            raise PreparationError("generated XML typed blocks overlap")
        seen.append((begin, begin + count))
        block = {
            "tag": child.tag,
            "begin": begin,
            "count": count,
            "mk": mk,
            "mkfluid": None if child.get("mkfluid") is None else int(child.get("mkfluid", "0")),
        }
        blocks.append(block)
        if child.tag == "fluid":
            fluid_blocks.append(block)
    if not blocks or sorted(seen) != [(0, nparticles)] and sum(end - begin for begin, end in seen) != nparticles:
        raise PreparationError("generated XML typed blocks do not cover the complete particle axis")
    if not fluid_blocks:
        raise PreparationError("generated XML has no fluid particle block")

    fillbox = root.find(".//geometry/commands/mainlist/fillbox")
    size = None if fillbox is None else fillbox.find("size")
    if size is None or size.get("z") is None:
        raise PreparationError("generated XML lacks fillbox size z")
    depth = _number(size.get("z"), "generated XML fillbox depth")
    if not math.isclose(depth, cfg["depth_m"], abs_tol=1.0e-9, rel_tol=0.0):
        raise PreparationError(f"generated XML depth {depth} differs from expected {cfg['depth_m']}")

    parameters = {
        node.get("key"): node.get("value")
        for node in root.findall(".//execution/parameters/parameter")
        if node.get("key")
    }
    if not math.isclose(_number(parameters.get("TimeMax"), "generated TimeMax"), 6.0, abs_tol=1e-9, rel_tol=0.0):
        raise PreparationError("generated XML TimeMax is not 6 s")
    if not math.isclose(_number(parameters.get("TimeOut"), "generated TimeOut"), 0.025, abs_tol=1e-9, rel_tol=0.0):
        raise PreparationError("generated XML TimeOut is not .025 s")

    fluid_particles = sum(block["count"] for block in fluid_blocks)
    payload = {
        "schema": "ds-data-02.upstream-first.m4.generated-fluid-cohort.v1",
        "case_id": case,
        "dp_m": 0.01,
        "depth_m": cfg["depth_m"],
        "grid_index_at_dp_0.01": cfg["grid_index"],
        "particle_axis_count": nparticles,
        "fluid_particle_count": fluid_particles,
        "fluid_blocks": sorted(fluid_blocks, key=lambda item: item["begin"]),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    cohort_hash = hashlib.sha256(encoded).hexdigest()
    return {
        "root": root,
        "xml": paths["xml"],
        "bi4": paths["bi4"],
        "particle_axis_count": nparticles,
        "fluid_particle_count": fluid_particles,
        "blocks": sorted(blocks, key=lambda item: item["begin"]),
        "fluid_blocks": sorted(fluid_blocks, key=lambda item: item["begin"]),
        "fillbox_depth_m": depth,
        "parameters": {"TimeMax": 6.0, "TimeOut": 0.025},
        "cohort_hash": cohort_hash,
        "cohort_hash_payload": payload,
    }


def _gencase_evidence(case: str) -> dict[str, Any]:
    cfg = _case(case)
    paths = _gencase_paths(case)
    receipt, request = _require_receipt(paths["receipt"], case, "gencase-001", "GenCase execution receipt")
    if receipt.get("solver_dimension_from_gencase") != 3:
        raise PreparationError("GenCase receipt does not bind a 3D generated case")
    xml = _xml_evidence(case)
    if receipt.get("total_particles") != xml["particle_axis_count"]:
        raise PreparationError("GenCase receipt total_particles differs from generated XML")
    if receipt.get("fluid_particles") != xml["fluid_particle_count"]:
        raise PreparationError("GenCase receipt fluid_particles differs from generated XML")
    if not math.isclose(_number(request.get("time_max_s"), "GenCase request TimeMax"), 6.0, abs_tol=1e-9, rel_tol=0.0):
        raise PreparationError("GenCase request TimeMax is not 6 s")
    if not math.isclose(_number(request.get("time_out_s"), "GenCase request TimeOut"), 0.025, abs_tol=1e-9, rel_tol=0.0):
        raise PreparationError("GenCase request TimeOut is not .025 s")
    if not math.isclose(_number(request.get("dp_m"), "GenCase request dp"), 0.01, abs_tol=1e-12, rel_tol=0.0):
        raise PreparationError("GenCase request dp is not .01 m")
    if request.get("definition_copy") != str(cfg["definition"]):
        raise PreparationError("GenCase receipt request does not bind the M4 child definition")
    if request.get("definition_copy_sha256") != _sha256(cfg["definition"]):
        raise PreparationError("GenCase receipt request definition hash differs from M4 definition")
    return {
        "receipt": receipt,
        "request": request,
        "receipt_binding": _bind(paths["receipt"], "GenCase execution receipt"),
        "xml_binding": _bind(paths["xml"], "generated XML"),
        "bi4_binding": _bind(paths["bi4"], "generated BI4"),
        "generated_root": paths["root"],
        "xml": xml,
    }


def _all_regular_files(root: Path, label: str) -> list[Path]:
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise PreparationError(f"{label} is not a regular directory: {root}")
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise PreparationError(f"{label} contains a symbolic link: {path}")
        if path.is_file():
            if not stat.S_ISREG(path.stat().st_mode):
                raise PreparationError(f"{label} contains a non-regular file: {path}")
            files.append(path)
    return files


def _solver_evidence(case: str, gencase: Mapping[str, Any]) -> dict[str, Any]:
    paths = _solver_paths(case)
    receipt, request = _require_receipt(paths["receipt"], case, "solver-001", "solver execution receipt")
    gencase_sha = gencase["receipt_binding"]["sha256"]
    bound_gencase_sha = request.get("gencase_receipt_sha256")
    if bound_gencase_sha is not None and bound_gencase_sha != gencase_sha:
        raise PreparationError("solver receipt request gencase receipt SHA differs from actual receipt")
    if request.get("gencase_receipt") not in {None, str(_gencase_paths(case)["receipt"])}:
        raise PreparationError("solver receipt request gencase receipt path is not child-bound")
    if not math.isclose(_number(request.get("time_max_s"), "solver request TimeMax"), 6.0, abs_tol=1e-9, rel_tol=0.0):
        raise PreparationError("solver request TimeMax is not 6 s")
    if not math.isclose(_number(request.get("time_out_s"), "solver request TimeOut"), 0.025, abs_tol=1e-9, rel_tol=0.0):
        raise PreparationError("solver request TimeOut is not .025 s")
    if not math.isclose(_number(request.get("dp_m"), "solver request dp"), 0.01, abs_tol=1e-12, rel_tol=0.0):
        raise PreparationError("solver request dp is not .01 m")

    all_files = _all_regular_files(paths["root"], "completed solver attempt")
    required = [paths["receipt"], paths["run_out"], paths["runparts"], paths["part_out"], paths["part_info"]]
    missing = [path for path in required if path not in all_files]
    if missing:
        raise PreparationError("completed solver attempt lacks required native files: " + ", ".join(map(str, missing)))
    run_text = paths["run_out"].read_text(encoding="utf-8", errors="replace")
    excluded_matches = EXCLUDED_RE.findall(run_text)
    initial_matches = INITIAL_RE.findall(run_text)
    if len(excluded_matches) != 1 or len(initial_matches) != 1:
        raise PreparationError("Run.out must contain exactly one initial and one excluded-particle ledger")
    excluded = int(excluded_matches[0].replace(",", ""))
    initial = int(initial_matches[0].replace(",", ""))
    if initial != gencase["xml"]["particle_axis_count"]:
        raise PreparationError("Run.out initial particles differ from generated XML")
    if excluded < 0 or excluded > initial:
        raise PreparationError("Run.out excluded particle count is outside the initial axis")

    bindings = [_bind(path, "completed solver regular file") for path in all_files]
    by_name = {path.name: path for path in all_files}
    return {
        "receipt": receipt,
        "request": request,
        "receipt_binding": _bind(paths["receipt"], "solver execution receipt"),
        "root": paths["root"],
        "data": paths["data"],
        "run_out": paths["run_out"],
        "runparts": paths["runparts"],
        "part_out": paths["part_out"],
        "part_info": paths["part_info"],
        "initial_particles": initial,
        "excluded_particles": excluded,
        "regular_files": all_files,
        "regular_bindings": bindings,
        "frame_files": [path for path in all_files if re.fullmatch(r"Part_\d{4,}\.bi4", path.name)],
        "named": by_name,
    }


def _validate_static_artifacts(case: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    cfg = _case(case)
    manifest_path = SUBTREE / "manifests" / f"{case}.json"
    semantic_path = SUBTREE / "semantic-diff.json"
    template_path = SUBTREE / "requests" / f"{case}-solver.template.json"
    manifest = _json(manifest_path, "M4 child manifest")
    semantic = _json(semantic_path, "M4 semantic diff")
    template = _json(template_path, "M4 solver template")
    if manifest.get("schema") != CHILD_MANIFEST_SCHEMA:
        raise PreparationError("M4 child manifest does not retain the frozen M3 child schema")
    if manifest.get("case_id") != case or manifest.get("m4_additional") is not True or manifest.get("m3_completion_claim") is not False:
        raise PreparationError("M4 child manifest lacks explicit M4 additional/no-M3-claim labels")
    definition = cfg["definition"]
    definition_sha = _sha256(definition)
    if manifest.get("definition", {}).get("path") != str(definition) or manifest.get("definition", {}).get("sha256") != definition_sha:
        raise PreparationError("M4 child manifest definition binding is stale")
    if semantic.get("schema") != SEMANTIC_DIFF_SCHEMA or semantic.get("m4_additional") is not True or semantic.get("m3_completion_claim") is not False:
        raise PreparationError("M4 semantic diff lacks frozen schema or M4/no-M3 labels")
    comparison = next((item for item in semantic.get("comparisons", []) if item.get("case_id") == case), None)
    if not isinstance(comparison, Mapping) or comparison.get("candidate_sha256") != definition_sha:
        raise PreparationError("M4 semantic diff lacks the actual child definition hash")
    if manifest.get("semantic_diff", {}).get("sha256") != _sha256(semantic_path):
        raise PreparationError("M4 child manifest semantic-diff hash is stale")
    if template.get("case_id") != case or template.get("template_only") is not True:
        raise PreparationError("M4 solver template is not the expected immutable template")
    reservation = template.get("solver_reservation", {})
    if reservation.get("bytes") != 9663676416 or reservation.get("gib") != 9 or reservation.get("exact") is not True:
        raise PreparationError("M4 solver template reservation is not the exact 9 GiB contract")
    required_static = {str(RUNTIME_V2), str(RUNTIME_V6), str(DSPH_CONFIG)}
    if not required_static.issubset(set(template.get("input_files", []))):
        raise PreparationError("M4 solver template omits runtime v2/v6 or DsphConfig input")
    return manifest, semantic, template


def _cohort_binding(case: str, gencase: Mapping[str, Any]) -> dict[str, Any]:
    xml = gencase["xml"]
    return {
        "algorithm": "sha256(canonical-json(fluid typed particle ranges from actual generated XML))",
        "schema": gencase["xml"]["cohort_hash_payload"]["schema"],
        "value": gencase["xml"]["cohort_hash"],
        "status": "verified_from_actual_completed_gencase_xml",
        "source": gencase["xml_binding"],
        "case_id": case,
        "dp_m": 0.01,
        "depth_m": _case(case)["depth_m"],
        "grid_index_at_dp_0.01": _case(case)["grid_index"],
        "grid_alignment": {
            "definition_alignment_verified": True,
            "actual_generated_fillbox_depth_m": gencase["xml"]["fillbox_depth_m"],
            "actual_generated_typed_fluid_ranges": gencase["xml"]["fluid_blocks"],
            "actual_generated_fluid_particle_count": gencase["xml"]["fluid_particle_count"],
        },
        "definition_sha256_is_not_a_cohort_hash": True,
        "no_receipt_fiction": True,
    }


def prepare_solver_ready(case: str, output_dir: Path) -> Path:
    _validate_output_dir(output_dir)
    _, semantic, template = _validate_static_artifacts(case)
    gencase = _gencase_evidence(case)
    cfg = _case(case)
    candidate = copy.deepcopy(template)
    output = output_dir / "solver-ready" / f"{case}-solver.ready.json"
    candidate["status"] = "m4_additional_candidate_actual_gencase_bound_pending_root_admission"
    candidate["template_only"] = False
    candidate["candidate_only"] = True
    candidate["submission_forbidden"] = True
    candidate["root_may_submit_initially"] = False
    candidate["solver_launch_forbidden"] = True
    candidate["m4_additional"] = True
    candidate["m3_completion_claim"] = False
    candidate["credit_status"] = "not_credited"
    candidate["semantic_diff_sha256"] = _sha256(SUBTREE / "semantic-diff.json")
    candidate["gencase_receipt"] = gencase["receipt_binding"]["path"]
    candidate["gencase_receipt_sha256"] = gencase["receipt_binding"]["sha256"]
    candidate["generated_prefix"] = str(gencase["generated_root"] / case)
    cohort = _cohort_binding(case, gencase)
    candidate["grid_aligned_actual_cohort_hash"] = cohort
    candidate["actual_gencase_binding"] = {
        "status": "completed_case_bound",
        "receipt": gencase["receipt_binding"],
        "generated_xml": gencase["xml_binding"],
        "generated_bi4": gencase["bi4_binding"],
        "cohort": cohort,
    }
    candidate["generated_case_binding"] = {
        **candidate.get("generated_case_binding", {}),
        "generated_prefix": str(gencase["generated_root"] / case),
        "generated_xml": gencase["xml_binding"]["path"],
        "generated_bi4": gencase["bi4_binding"]["path"],
        "gencase_receipt": gencase["receipt_binding"]["path"],
        "gencase_receipt_sha256": gencase["receipt_binding"]["sha256"],
        "status": "actual_completed",
        "actual_fluid_cohort_hash_sha256": cohort["value"],
        "actual_fluid_cohort_hash_status": cohort["status"],
        "grid_alignment_proof": cohort["grid_alignment"],
    }
    actual_files = [
        gencase["receipt_binding"]["path"],
        gencase["xml_binding"]["path"],
        gencase["bi4_binding"]["path"],
        str(SUBTREE / "semantic-diff.json"),
    ]
    candidate["input_files"] = list(dict.fromkeys(list(candidate.get("input_files", [])) + actual_files))
    bindings: dict[str, Any] = {}
    for path_value in candidate["input_files"]:
        path = Path(path_value)
        bindings[path_value] = _bind(path, "solver-ready input")
    candidate["input_bindings"] = bindings
    candidate["actual_input_bindings"] = {
        item["path"]: item for item in [gencase["receipt_binding"], gencase["xml_binding"], gencase["bi4_binding"]]
    }
    candidate["actual_receipt_policy"] = {
        "gencase_receipt_sha256": gencase["receipt_binding"]["sha256"],
        "generated_fluid_cohort_hash_sha256": cohort["value"],
        "solver_receipt_sha256": None,
        "native_audit_receipts": None,
        "null_values_mean_future_evidence_not_claimed": True,
    }
    candidate["request_note"] = (
        str(candidate.get("request_note", "")).rstrip() +
        " Actual GenCase receipt, generated XML/BI4, and generated fluid-cohort hash are bound by this preparation candidate. "
        "Later-batch admission and root review remain required; this file cannot be submitted or launch a solver."
    )
    candidate["launch_authorization"] = "root-controlled; M4 additional candidate only; no solver launch implied"
    candidate["actual_binding_source"] = str(SUBTREE)
    _write_new(output, candidate)
    return output


def _replace_frozen(value: Any, case: str) -> Any:
    if isinstance(value, str):
        return value.replace(MOTHER_CASE, case).replace("CaseDamBreak3D.xml", f"{case}.xml")
    if isinstance(value, list):
        return [_replace_frozen(item, case) for item in value]
    if isinstance(value, dict):
        return {key: _replace_frozen(item, case) for key, item in value.items()}
    return value


def _actual_native_sources(case: str, gencase: Mapping[str, Any], solver: Mapping[str, Any], integrity: Path | None) -> dict[str, Path]:
    cfg = _case(case)
    sources = {
        "dsph_config": DSPH_CONFIG,
        "gencase_receipt": Path(gencase["receipt_binding"]["path"]),
        "generated_xml": Path(gencase["xml_binding"]["path"]),
        "generated_bi4": Path(gencase["bi4_binding"]["path"]),
        "solver_receipt": Path(solver["receipt_binding"]["path"]),
        "source_definition": cfg["definition"],
        "runparts": solver["runparts"],
        "run_out": solver["run_out"],
        "raw_partout": solver["part_out"],
        "part_info": solver["part_info"],
        "partvtk": PARTVTK,
    }
    if integrity is not None:
        sources["native_integrity"] = integrity
    return sources


def _rebind_manifest_sources(manifest: dict[str, Any], sources: Mapping[str, Path], key: str) -> None:
    old = manifest.get(key)
    if not isinstance(old, Mapping):
        raise PreparationError(f"frozen native manifest lacks {key} sources")
    rebound: dict[str, Any] = {}
    for source_name in old:
        if source_name not in sources:
            raise PreparationError(f"frozen native manifest source is not understood: {source_name}")
        rebound[source_name] = _bind(sources[source_name], f"native source {source_name}")
    manifest[key] = rebound


def _native_output_paths(case: str, mode: str, output_dir: Path) -> tuple[Path, Path, str]:
    suffix = "native-integrity-001" if mode == "exclusions" else "native-frame-scan-001"
    branch = "native-exclusions" if mode == "exclusions" else "native-frames"
    folder = output_dir / branch
    return (
        folder / f"{case}-{suffix}-manifest.json",
        folder / f"{case}-{suffix}-request.json",
        suffix,
    )


def _native_request_inputs(
    request: dict[str, Any],
    case: str,
    mode: str,
    manifest_path: Path,
    source_paths: Mapping[str, Path],
    solver: Mapping[str, Any],
) -> list[str]:
    old_definition = str(MOTHER_DEFINITION)
    inputs: list[str] = []
    for item in request.get("input_files", []):
        if not isinstance(item, str):
            raise PreparationError("frozen native request has a non-string input file")
        value = _replace_frozen(item, case)
        if value == old_definition:
            value = str(source_paths["source_definition"])
        if "/manifests/" in value and (
            "native-integrity-001.json" in value
            or "native-frame-scan-001.json" in value
        ):
            value = str(manifest_path)
        inputs.append(value)
    inputs.append(str(manifest_path))
    # The auditor request must keep Part_####.bi4 deferred.  Every other
    # regular solver file is a receipt-bound input, including native logs and
    # ancillary data files that a later postprocess may need.
    for path in solver["regular_files"]:
        if path in solver["frame_files"]:
            continue
        inputs.append(str(path))
    for path in source_paths.values():
        inputs.append(str(path))
    return list(dict.fromkeys(inputs))


def _validate_inputs(inputs: Iterable[str], manifest_path: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    bindings: dict[str, Any] = {}
    manifest_text = _json_text(manifest)
    for value in dict.fromkeys(inputs):
        path = Path(value)
        if path == manifest_path:
            encoded = manifest_text.encode("utf-8")
            bindings[value] = {
                "path": value,
                "bytes": len(encoded),
                "sha256": hashlib.sha256(encoded).hexdigest(),
            }
        else:
            bindings[value] = _bind(path, "native request input")
    return bindings


def prepare_native(case: str, mode: str, output_dir: Path) -> tuple[Path, Path]:
    if mode not in {"exclusions", "frames"}:
        raise PreparationError(f"unsupported native preparation mode: {mode}")
    _validate_output_dir(output_dir)
    _, semantic, _ = _validate_static_artifacts(case)
    gencase = _gencase_evidence(case)
    solver = _solver_evidence(case, gencase)
    integrity_path: Path | None = None
    integrity_payload: dict[str, Any] | None = None
    if mode == "frames":
        integrity_path = _case_root(case) / "native-integrity-001" / "integrity.json"
        integrity_payload = _json(integrity_path, "completed child native-integrity receipt")
        if integrity_payload.get("schema") != INTEGRITY_OUTPUT_SCHEMA or integrity_payload.get("status") != "verified":
            raise PreparationError("full-frame preparation requires a verified actual native-integrity receipt")
        if integrity_payload.get("case_id") != case or integrity_payload.get("solver_root") != str(solver["root"]):
            raise PreparationError("native-integrity receipt is not bound to this child solver")

    manifest_path, request_path, suffix = _native_output_paths(case, mode, output_dir)
    if manifest_path.exists() or manifest_path.is_symlink() or request_path.exists() or request_path.is_symlink():
        raise PreparationError(f"refusing existing native preparation outputs for {case}/{mode}")

    frozen_manifest = _json(CONVERSION / "manifests" / f"{MOTHER_CASE}-{suffix}.json", "frozen native manifest")
    frozen_request = _json(CONVERSION / "requests" / f"{MOTHER_CASE}-{suffix}.json", "frozen native request")
    manifest = _replace_frozen(frozen_manifest, case)
    request = _replace_frozen(frozen_request, case)
    cfg = _case(case)
    sources = _actual_native_sources(case, gencase, solver, integrity_path)
    source_key = "source" if mode == "exclusions" else "sources"
    _rebind_manifest_sources(manifest, sources, source_key)
    manifest["schema"] = INTEGRITY_MANIFEST_SCHEMA if mode == "exclusions" else FRAME_MANIFEST_SCHEMA
    manifest["case_id"] = case
    manifest["solver_root"] = str(solver["root"])
    manifest["reference_role"] = "primary_3d"
    manifest["condition_role"] = "m4_additional_physical_depth_candidate_3d"
    manifest["m4_additional"] = True
    manifest["m3_completion_claim"] = False
    manifest["physical_depth_m"] = cfg["depth_m"]
    manifest["grid_index_at_dp_0.01"] = cfg["grid_index"]
    manifest["actual_gencase_binding"] = {
        "receipt": gencase["receipt_binding"],
        "generated_xml": gencase["xml_binding"],
        "generated_bi4": gencase["bi4_binding"],
        "fluid_cohort_hash_sha256": gencase["xml"]["cohort_hash"],
    }
    manifest["actual_solver_binding"] = {
        "receipt": solver["receipt_binding"],
        "initial_particles": solver["initial_particles"],
        "excluded_particles": solver["excluded_particles"],
        "regular_native_solver_files": solver["regular_bindings"],
    }
    manifest["generated_fluid_cohort_hash"] = _cohort_binding(case, gencase)
    manifest["credit_status"] = "not_credited"
    manifest["acceptance_threshold"] = None
    manifest["physical_difference_label"] = "initial physical fill depth; no physical-condition credit"
    manifest["sampling_difference_label"] = "TimeOut=.025 versus mother .01; no retiming"
    expected = manifest.get("expected")
    if not isinstance(expected, dict):
        raise PreparationError("frozen native manifest expected section is not an object")
    expected.update(
        initial_particles=solver["initial_particles"],
        excluded_particles=solver["excluded_particles"],
        minimum_time_end_s=6.0,
    )
    if mode == "frames":
        expected["frame_count"] = 241
        manifest["data_root"] = str(solver["data"])
        manifest["source_native_integrity"] = _bind(integrity_path, "native-integrity receipt")
    else:
        manifest.pop("data_root", None)

    # Bind the child manifest into the cloned frozen request while retaining
    # the auditor's deferred-frame policy.
    request["case_id"] = case
    request["reference_role"] = "primary_3d"
    request["condition_role"] = "m4_additional_physical_depth_candidate_3d"
    request["m4_additional"] = True
    request["m3_completion_claim"] = False
    request["status"] = "m4_additional_ready_native_integrity_after_actual_solver" if mode == "exclusions" else "m4_additional_ready_native_frame_scan_after_actual_solver"
    request["submission_forbidden"] = True
    request["solver_launch_forbidden"] = True
    request["native_audit_launch_forbidden"] = True
    request["launch_authorization"] = "root-controlled; prepared request candidate only; no auditor launch implied"
    request["actual_gencase_receipt_sha256"] = gencase["receipt_binding"]["sha256"]
    request["actual_fluid_cohort_hash_sha256"] = gencase["xml"]["cohort_hash"]
    request["actual_solver_receipt_sha256"] = solver["receipt_binding"]["sha256"]
    request["actual_solver_binding"] = {
        "receipt": solver["receipt_binding"],
        "regular_native_solver_files": solver["regular_bindings"],
        "frame_files_deferred_from_input_files": [str(path) for path in solver["frame_files"]],
    }
    request["physical_difference_label"] = "initial physical fill depth; no physical-condition credit"
    request["sampling_difference_label"] = "TimeOut=.025 versus mother .01; no retiming"
    request["credit_status"] = "not_credited"
    request["acceptance_threshold"] = None
    request["semantic_diff_sha256"] = _sha256(SUBTREE / "semantic-diff.json")
    request["command"] = list(request.get("command", []))
    try:
        manifest_arg = request["command"].index("--manifest") + 1
    except (KeyError, ValueError) as exc:
        raise PreparationError("frozen native request command lacks --manifest") from exc
    request["command"][manifest_arg] = str(manifest_path)
    request["input_files"] = _native_request_inputs(request, case, mode, manifest_path, sources, solver)
    request["input_bindings"] = _validate_inputs(request["input_files"], manifest_path, manifest)
    if mode == "exclusions":
        request["estimated_storage_bytes"] = 67108864
        request["estimated_deferred_read_bytes"] = 0
        request["native_integrity"] = {
            **dict(request.get("native_integrity", {})),
            "expected_initial_particles": solver["initial_particles"],
            "expected_excluded_particles": solver["excluded_particles"],
            "manifest": str(manifest_path),
        }
    else:
        request["estimated_storage_bytes"] = 671088640
        request["estimated_peak_storage_bytes"] = 671088640
        request["estimated_deferred_read_bytes"] = sum(path.stat().st_size for path in solver["frame_files"])
        request["scan_contract"] = {
            **dict(request.get("scan_contract", {})),
            "frame_count": 241,
            "spatial_scope": "all native saved Part_0000.bi4 through Part_0240.bi4 frames",
        }
        request["source_native_integrity"] = str(integrity_path)

    # The manifest binding in request.input_bindings is based on the exact
    # bytes that _write_new will use.  All other source bindings were hashed
    # from their actual regular files above.
    _write_new(manifest_path, manifest)
    actual_manifest_sha = _sha256(manifest_path)
    expected_manifest_binding = request["input_bindings"][str(manifest_path)]
    if expected_manifest_binding["sha256"] != actual_manifest_sha or expected_manifest_binding["bytes"] != manifest_path.stat().st_size:
        raise PreparationError("prepared native manifest bytes changed between binding and write")
    _write_new(request_path, request)
    return manifest_path, request_path


def _validate_output_dir(output_dir: Path) -> None:
    output_dir = Path(output_dir).expanduser().resolve()
    subtree = SUBTREE.resolve()
    try:
        output_dir.relative_to(subtree)
    except ValueError as exc:
        raise PreparationError(f"output directory must remain inside M4 additional subtree: {output_dir}") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="stage", required=True)
    for stage in ("solver-ready", "native-exclusions", "native-frames"):
        command = sub.add_parser(stage)
        command.add_argument("--case", required=True, choices=sorted(CASES))
        command.add_argument("--output-dir", type=Path, default=SUBTREE / "prepared")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.stage == "solver-ready":
            print(prepare_solver_ready(args.case, args.output_dir))
        else:
            mode = "exclusions" if args.stage == "native-exclusions" else "frames"
            manifest, request = prepare_native(args.case, mode, args.output_dir)
            print(manifest)
            print(request)
    except (OSError, PreparationError, KeyError, TypeError, ValueError) as exc:
        print(f"M4 additional preparation refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
