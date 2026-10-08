#!/usr/bin/env python3
"""Prepare an additive F7 half-CFL GenCase handoff and end-time gate.

The consumed F7 half-CFL plan is deliberately left byte-for-byte unchanged.
This forward module materializes a separately hashed definition with
``cflnumber=.1`` and dense ``TimeOut=.01`` from the reviewed source Def.  It
does not run GenCase, a native decoder, a solver, or a GPU.  The request is a
bounded CPU GenCase request; the half solver remains unavailable until the
parent has an actual generated XML/BI4, receipt, and initial typed QA.

The same-CFL end gate reads only the small native ``RunPARTs.csv`` and solver
receipt.  It records observed rows and final time.  The planned 1202 rows and
12.00003209155591 s are never substituted for missing evidence.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from typing import Any, Iterable, Mapping, Sequence


LAB = Path(__file__).resolve().parents[1]
CAMPAIGN = LAB / "campaigns" / "ds-data-02"
CURRENT = CAMPAIGN / "stage2" / "CURRENT336.json"
CASE_ID = "F7_OBSTACLE_QUINTIC_B08_A065"

# These are read-only source inputs.  The new Def is written under this
# worktree's stage2/native-reconstruction namespace and never overwrites the
# source or consumed generated XML.
SOURCE_DEF = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/"
    "F7_TARGET_ANGLE_ENDPOINTS/"
    "root-stage1-f7-target030-065-actual-motion-preparation-074/prepared/"
    "F7_OBSTACLE_QUINTIC_B08_A065/F7_OBSTACLE_QUINTIC_B08_A065_Def.xml"
)
BASELINE_XML = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/"
    "F7_OBSTACLE_QUINTIC_B08_A065/"
    "root-stage1-f7-angle065-genuine-gencase-085/prepared/"
    "F7_OBSTACLE_QUINTIC_B08_A065.xml"
)
BASELINE_GENCASE_RECEIPT = BASELINE_XML.parents[1] / "execution-receipt.json"
MOTION = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/"
    "F7_TARGET_ANGLE_ENDPOINTS/"
    "root-stage1-f7-target030-065-actual-motion-preparation-074/prepared/"
    "F7_OBSTACLE_QUINTIC_B08_A065/motion_obstacle_quintic.dat"
)
SAME_CFL_RECEIPT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/"
    "F7_OBSTACLE_QUINTIC_B08_A065/"
    "root-stage1-f7-a065-full601-native-099/execution-receipt.json"
)
SAME_CFL_RUNPARTS = SAME_CFL_RECEIPT.parent / "solver_output" / "RunPARTs.csv"
GENCASE = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/"
    "vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64"
)

NATIVE_ROOT = CAMPAIGN / "stage2" / "native-reconstruction"
VARIANT_DEF = NATIVE_ROOT / "f7-half-cfl-v1" / "source" / (
    "F7_OBSTACLE_QUINTIC_B08_A065_half_cfl01_Def.xml"
)
OLD_HALF_PLAN = NATIVE_ROOT / "f7-nvme-counterpart-v4" / "f7-s2-half-cfl-nvme-plan-v1-001.json"
RUNTIME_V2 = LAB / "scripts" / "ds_data02_runtime_v2.py"
RUNTIME_V6 = LAB / "scripts" / "ds_data02_runtime_v6.py"
RUNTIME_V8 = LAB / "scripts" / "ds_data02_runtime_v8.py"
STRICT_V8 = LAB / "scripts" / "ds_data02_strict_dispatch_v8.py"
DISPATCH_V8 = LAB / "scripts" / "ds_data02_stage2_dispatch_v8.py"

UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
REQUEST_SCHEMA = "ds02.stage2.f7-half-cfl-gencase-request.v8"
PLAN_SCHEMA = "ds02.stage2.f7-nvme-half-cfl-plan.v2"
GATE_SCHEMA = "ds02.stage2.f7-same-cfl-runparts-end-gate.v1"


class HalfCflError(RuntimeError):
    """Raised when a source-bound handoff cannot be made fail-closed."""


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode()
    ).hexdigest()


def load_json(path: Path | str) -> dict[str, Any]:
    value = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise HalfCflError(f"JSON object required: {path}")
    return value


def _require_file(path: Path, role: str) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise HalfCflError(f"{role} is unavailable: {path}")
    return path


def _source_binding(path: Path, role: str, *, content_scope: str = "source_content") -> dict[str, Any]:
    path = _require_file(path, role)
    stat = path.stat()
    return {
        "path": str(path),
        "role": role,
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "sha256": sha256_file(path),
        "content_scope": content_scope,
    }


def _replace_once(text: str, pattern: str, replacement: str, label: str) -> str:
    result, count = re.subn(pattern, replacement, text, count=1)
    if count != 1:
        raise HalfCflError(f"expected exactly one {label} in source Def; found {count}")
    return result


def _normalized_source_text(text: str) -> str:
    """Remove source-only trailing blanks while preserving XML content."""
    return "\n".join(line.rstrip() for line in text.splitlines()) + "\n"


def derive_definition(source: Path = SOURCE_DEF, output: Path = VARIANT_DEF) -> dict[str, Any]:
    """Create a new independently hashed Def without mutating the source."""
    source = _require_file(source, "reference F7 Def")
    output = output.expanduser().resolve()
    if output.exists():
        raise HalfCflError(f"refusing to overwrite additive Def: {output}")
    text = _normalized_source_text(source.read_text(encoding="utf-8"))
    variant = _replace_once(
        text,
        r'(<cflnumber\s+value=")0\.2("\s*/>)',
        r'\g<1>0.1\g<2>',
        "cflnumber=.2",
    )
    variant = _replace_once(
        variant,
        r'(<parameter\s+key="TimeOut"\s+value=")0\.02("\s+units_comment="seconds"\s*/>)',
        r'\g<1>0.01\g<2>',
        "dense TimeOut=.02",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(variant, encoding="utf-8")
    return validate_definition_pair(source, output)


def _xml_digest(element: ET.Element) -> str:
    # Formatting-only blank lines in the reviewed Def must not turn into a
    # geometry change when the additive source is normalized.
    clone = ET.fromstring(ET.tostring(element, encoding="utf-8"))
    for node in clone.iter():
        if node.text is not None and not node.text.strip():
            node.text = None
        if node.tail is not None and not node.tail.strip():
            node.tail = None
    return hashlib.sha256(ET.tostring(clone, encoding="utf-8")).hexdigest()


def _initial_intent(baseline_xml: Path = BASELINE_XML) -> dict[str, Any]:
    baseline_xml = _require_file(baseline_xml, "baseline generated XML")
    root = ET.parse(baseline_xml).getroot()
    particles = root.find("./execution/particles")
    summary = particles.find("./_summary") if particles is not None else None
    if particles is None or summary is None:
        raise HalfCflError("baseline generated XML lacks particle summary")

    def count(name: str) -> int:
        node = summary.find(f"./{name}")
        if node is None or node.get("count") is None:
            raise HalfCflError(f"baseline generated XML lacks {name} count")
        return int(node.get("count", "-1"))

    constants = root.find("./execution/constants")
    dp = constants.find("./dp") if constants is not None else None
    mass = constants.find("./massfluid") if constants is not None else None
    return {
        "source_generated_xml": _source_binding(
            baseline_xml,
            "consumed baseline GenCase generated XML",
            content_scope="read_only_initial_intent_evidence_no_half_output",
        ),
        "total_particles": int(particles.get("np", "-1")),
        "boundary_particles": int(particles.get("nb", "-1")),
        "fixed_particles": count("fixed"),
        "moving_particles": count("moving"),
        "fluid_particles": count("fluid"),
        "dp_m": float(dp.get("value")) if dp is not None else None,
        "massfluid_kg": float(mass.get("value")) if mass is not None else None,
        "status": "baseline_initial_intent_only; half output not observed",
    }


def validate_definition_pair(source: Path = SOURCE_DEF, variant: Path = VARIANT_DEF) -> dict[str, Any]:
    """Check exact geometry/motion intent while requiring the two numeric edits."""
    source = _require_file(source, "reference F7 Def")
    variant = _require_file(variant, "independent half-CFL Def")
    source_text = _normalized_source_text(source.read_text(encoding="utf-8"))
    variant_text = variant.read_text(encoding="utf-8")
    expected = _replace_once(
        _replace_once(source_text, r'(<cflnumber\s+value=")0\.2("\s*/>)', r'\g<1>0.1\g<2>', "cflnumber=.2"),
        r'(<parameter\s+key="TimeOut"\s+value=")0\.02("\s+units_comment="seconds"\s*/>)',
        r'\g<1>0.01\g<2>',
        "dense TimeOut=.02",
    )
    if variant_text != expected:
        raise HalfCflError("half-CFL Def is not the independently-derived .1/.01 variant")
    source_root = ET.parse(source).getroot()
    variant_root = ET.parse(variant).getroot()
    source_geometry = source_root.find("./casedef/geometry")
    variant_geometry = variant_root.find("./casedef/geometry")
    source_motion = source_root.find("./casedef/motion")
    variant_motion = variant_root.find("./casedef/motion")
    if source_geometry is None or variant_geometry is None or source_motion is None or variant_motion is None:
        raise HalfCflError("Def lacks geometry or motion subtree")
    if _xml_digest(source_geometry) != _xml_digest(variant_geometry):
        raise HalfCflError("half-CFL variant changed geometry")
    if _xml_digest(source_motion) != _xml_digest(variant_motion):
        raise HalfCflError("half-CFL variant changed motion definition")
    cfl_nodes = variant_root.findall(".//cflnumber")
    if not cfl_nodes or any(node.get("value") != "0.1" for node in cfl_nodes):
        raise HalfCflError("half-CFL variant does not bind cflnumber=.1")
    timeout_nodes = variant_root.findall(".//parameter[@key='TimeOut']")
    if len(timeout_nodes) != 1 or timeout_nodes[0].get("value") != "0.01":
        raise HalfCflError("half-CFL variant does not bind dense TimeOut=.01")
    return {
        "reference": _source_binding(source, "reference cfl=.2 Def", content_scope="immutable_provenance"),
        "variant": _source_binding(variant, "independent cfl=.1/.01 Def", content_scope="actionable_gencase_input"),
        "geometry_sha256": _xml_digest(source_geometry),
        "motion_sha256": _xml_digest(source_motion),
        "numeric_edits": {"cflnumber": {"reference": 0.2, "variant": 0.1},
                          "TimeOut_s": {"reference": 0.02, "variant": 0.01}},
        "initial_particle_intent": _initial_intent(),
        "copy_edit_policy": "consumed reference and old plan were not modified; this is a new source artifact",
    }


def _unique_files(paths: Iterable[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for raw in paths:
        path = _require_file(Path(raw), "request input")
        key = str(path)
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


def build_gencase_request(case_id: str = CASE_ID, *, variant: Path = VARIANT_DEF) -> dict[str, Any]:
    if case_id != CASE_ID:
        raise HalfCflError(f"only the registered F7 source case is supported: {case_id}")
    definition = validate_definition_pair(SOURCE_DEF, variant)
    current = load_json(CURRENT)
    rows = current.get("cases")
    if not isinstance(rows, list):
        raise HalfCflError("CURRENT cases list is missing")
    row_index = next((i for i, row in enumerate(rows) if isinstance(row, dict) and row.get("physical_case_id") == case_id), None)
    if row_index is None:
        raise HalfCflError(f"CURRENT case missing: {case_id}")
    row = rows[row_index]
    files = _unique_files([
        CURRENT,
        SOURCE_DEF,
        variant,
        BASELINE_XML,
        BASELINE_GENCASE_RECEIPT,
        MOTION,
        GENCASE,
        Path(__file__),
        RUNTIME_V2,
        RUNTIME_V6,
        RUNTIME_V8,
        STRICT_V8,
        DISPATCH_V8,
    ])
    input_files = [str(path) for path in files]
    input_sha256 = {str(path): sha256_file(path) for path in files}
    attempt_id = "f7-half-cfl-gencase-v8-001"
    command = [str(GENCASE), str(Path(variant).resolve().with_suffix("")),
               "{attempt_root}/prepared/F7_OBSTACLE_QUINTIC_B08_A065_half_cfl01", "-save:all"]
    request: dict[str, Any] = {
        "schema": REQUEST_SCHEMA,
        "runner_schema": "ds02.runner-request.v2",
        "status": "READY_FOR_PARENT_GUARD",
        "role": "DEVELOPMENT",
        "family_id": "F7",
        "case_id": case_id,
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": "gencase",
        "command": command,
        "cwd": str(GENCASE.parent),
        "worktree_root": str(LAB.parent),
        "max_wall_seconds": 1200,
        "cpu_threads": 2,
        "estimated_storage_bytes": 512 * 1024**2,
        "launch_allowed": True,
        "solver_launch_allowed": False,
        "input_files": input_files,
        "input_sha256": input_sha256,
        "input_content_scope": {str(path): "metadata_or_small_source; no HDF5/BI4 input" for path in files},
        "runtime_binding": {
            "dispatch_v8": _source_binding(DISPATCH_V8, "v8 CPU dispatch"),
            "strict_v8": _source_binding(STRICT_V8, "v8 strict digest guard"),
            "runtime_v8": _source_binding(RUNTIME_V8, "v8 CPU runtime"),
            "runtime_v6": _source_binding(RUNTIME_V6, "v6 receipt/accounting dependency"),
            "runtime_v2": _source_binding(RUNTIME_V2, "v2 base runtime dependency"),
        },
        "source_binding": {
            "current": {"path": str(CURRENT), "sha256": sha256_file(CURRENT), "row_index": row_index},
            "reference_definition": definition["reference"],
            "half_definition": definition["variant"],
            "motion": _source_binding(MOTION, "F7 obstacle motion", content_scope="actionable_gencase_input"),
            "baseline_generated_xml": definition["initial_particle_intent"]["source_generated_xml"],
            "baseline_gencase_receipt": _source_binding(BASELINE_GENCASE_RECEIPT, "baseline GenCase receipt", content_scope="initial_intent_evidence"),
        },
        "variant_contract": {
            "reference_cfl": 0.2,
            "target_cfl": 0.1,
            "dense_save_interval_s": 0.01,
            "geometry_sha256": definition["geometry_sha256"],
            "motion_sha256": definition["motion_sha256"],
            "identical_geometry_and_initial_intent": True,
            "independent_source_artifact": True,
        },
        "expected_baseline_initial_intent": definition["initial_particle_intent"],
        "expected_outputs": {
            "generated_xml": "{attempt_root}/prepared/F7_OBSTACLE_QUINTIC_B08_A065_half_cfl01.xml",
            "generated_bi4": "{attempt_root}/prepared/F7_OBSTACLE_QUINTIC_B08_A065_half_cfl01.bi4",
            "execution_receipt": "{attempt_root}/execution-receipt.json",
            "initial_typed_qa": "must be produced from the new generated XML/BI4; no baseline count is substituted",
        },
        "execution_contract": {
            "gencase_only": True,
            "solver_launch_allowed": False,
            "native_decoder_invoked": False,
            "hdf5_opened": False,
            "bi4_opened_by_this_request": False,
            "gpu_started": False,
            "model_invoked": False,
            "cfd_invoked": False,
            "source_overwrite_forbidden": True,
        },
        "qualification": dict(UNKNOWN),
        "scientific_status": "DEVELOPMENT_GENCASE_PREP_ONLY",
        "launch_owner": "root",
        "root_review_required": True,
        "old_half_plan_unchanged": {"path": str(OLD_HALF_PLAN), "sha256": sha256_file(OLD_HALF_PLAN), "launch_allowed": False},
    }
    request["sha256"] = canonical_sha(request)
    return request


def _numeric_rows(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with _require_file(path, "RunPARTs") .open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader((line for line in handle if not line.startswith("#")), delimiter=";"):
            try:
                int(str(row.get("Part", "")))
                float(str(row.get("TimeStep [s]", "")))
            except (TypeError, ValueError):
                continue
            rows.append(row)
    if not rows:
        raise HalfCflError(f"RunPARTs has no numeric rows: {path}")
    return rows


def audit_same_cfl_runparts(runparts: Path = SAME_CFL_RUNPARTS,
                            solver_receipt: Path = SAME_CFL_RECEIPT) -> dict[str, Any]:
    """Derive native end evidence from RunPARTs, never from planning values."""
    runparts = _require_file(runparts, "same-CFL RunPARTs")
    solver_receipt = _require_file(solver_receipt, "same-CFL solver receipt")
    receipt = load_json(solver_receipt)
    rows = _numeric_rows(runparts)

    def number(row: Mapping[str, str], key: str) -> float:
        raw = str(row.get(key, "")).replace(",", "")
        try:
            value = float(raw)
        except ValueError as exc:
            raise HalfCflError(f"RunPARTs field {key} is not numeric") from exc
        return value

    times = [number(row, "TimeStep [s]") for row in rows]
    parts = [int(row["Part"]) for row in rows]
    positive_deltas = [b - a for a, b in zip(times, times[1:]) if b > a]
    observed_interval = (sum(positive_deltas) / len(positive_deltas)) if positive_deltas else None
    completed = receipt.get("status") == "completed" and receipt.get("returncode") == 0
    terminal = completed and bool(rows) and receipt.get("termination_reason") in (None, "")
    dense_rows = len(rows) == 1202
    dense_interval = observed_interval is not None and abs(observed_interval - 0.01) <= 0.00025
    complete_window = terminal and times[-1] >= 12.0
    return {
        "schema": GATE_SCHEMA,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "OBSERVED_REFERENCE_RUNPARTS_ONLY",
        "scope": "historical_same_cfl_runparts; no dense-.01 credit is granted",
        "runparts": _source_binding(runparts, "same-CFL RunPARTs", content_scope="small_native_telemetry"),
        "solver_receipt": _source_binding(solver_receipt, "same-CFL solver receipt", content_scope="terminal_evidence"),
        "receipt_terminal": {
            "status": receipt.get("status"),
            "returncode": receipt.get("returncode"),
            "termination_reason": receipt.get("termination_reason"),
            "terminal": terminal,
        },
        "observed": {
            "numeric_rows": len(rows),
            "first_part": parts[0],
            "last_part": parts[-1],
            "first_time_s": times[0],
            "last_time_s": times[-1],
            "mean_positive_save_interval_s": observed_interval,
        },
        "planning_contract": {
            "expected_rows": 1202,
            "expected_save_interval_s": 0.01,
            "expected_min_final_time_s": 12.0,
            "old_planned_end_time_s": 12.00003209155591,
            "interpretation": "planning-only; observed RunPARTs controls the gate",
        },
        "checks": {
            "terminal_complete_12s": complete_window,
            "dense_rows_1202_observed": dense_rows,
            "dense_interval_0p01_observed": dense_interval,
            "dense_12s_gate": bool(complete_window and dense_rows and dense_interval),
        },
        "scientific_credit": "NONE; this is a source-bound development gate",
        "qualification": dict(UNKNOWN),
    }


def half_solver_readiness(*, generated_xml: Path | None = None,
                          generated_bi4: Path | None = None,
                          gencase_receipt: Path | None = None,
                          initial_typed_qa: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return a fail-closed readiness result without requiring a solver receipt."""
    missing: list[str] = []
    if generated_xml is None or not Path(generated_xml).is_file():
        missing.append("actual half-CFL generated XML")
    if generated_bi4 is None or not Path(generated_bi4).is_file():
        missing.append("actual half-CFL generated BI4")
    receipt = None
    if gencase_receipt is None or not Path(gencase_receipt).is_file():
        missing.append("actual half-CFL GenCase receipt")
    else:
        receipt = load_json(gencase_receipt)
        if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
            missing.append("completed half-CFL GenCase receipt")
    if not isinstance(initial_typed_qa, Mapping):
        missing.append("actual initial typed QA")
    ready = not missing
    return {
        "half_solver_ready": ready,
        "missing": missing,
        "solver_receipt_not_required_for_this_gate": True,
        "solver_receipt_scope": "future native run evidence, after this gate; not a circular prerequisite",
        "gencase_receipt_status": receipt.get("status") if receipt else None,
    }


def build_half_plan(request: Mapping[str, Any], gate: Mapping[str, Any], *,
                    request_path: Path | None = None, gate_path: Path | None = None) -> dict[str, Any]:
    old_sha = sha256_file(OLD_HALF_PLAN)
    plan: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "status": "PENDING_GENCASE_AND_INITIAL_QA",
        "role": "DEVELOPMENT",
        "family_id": "F7",
        "case_id": CASE_ID,
        "current_path": str(CURRENT),
        "current_sha256": sha256_file(CURRENT),
        "target_cfl": 0.1,
        "reference_cfl": 0.2,
        "dense_save_interval_s": 0.01,
        "launch_allowed": False,
        "solver_launch_allowed": False,
        "gencase_request_launch_allowed": True,
        "gencase_request_path": str(request_path.resolve()) if request_path is not None else "f7-s2-half-cfl-gencase-request-v8-001.json",
        "gencase_request_sha256": request["sha256"],
        "independent_definition": {
            "path": str(VARIANT_DEF),
            "sha256": sha256_file(VARIANT_DEF),
            "source_reference_path": str(SOURCE_DEF),
            "source_reference_sha256": sha256_file(SOURCE_DEF),
            "geometry_and_initial_intent_preserved": True,
        },
        "readiness_gate": half_solver_readiness(),
        "required_before_half_solver_request": [
            "actual half-CFL generated XML and BI4",
            "completed half-CFL GenCase receipt bound to the new request",
            "initial typed QA from the new generated artifact",
        ],
        "not_a_prerequisite": [
            "a future half-CFL solver receipt is not required to establish this GenCase readiness gate",
            "the old consumed half-CFL plan remains false and is not overwritten",
        ],
        "same_cfl_end_gate": {
            "path": str(gate_path.resolve()) if gate_path is not None else "f7-s2-same-cfl-runparts-end-gate-v1-001.json",
            "sha256": gate["sha256"],
            "dense_0p01_gate": gate["checks"]["dense_12s_gate"],
            "observed_runparts_controls_end": True,
            "frame_count_1202_and_12p000032_are_planning_only": True,
        },
        "historical_old_plan": {
            "path": str(OLD_HALF_PLAN),
            "sha256": old_sha,
            "launch_allowed": False,
            "bytes_unchanged": True,
        },
        "qualification": dict(UNKNOWN),
        "scientific_credit": "NONE; independent GenCase preparation pending parent guard and initial QA",
        "limitations": [
            "No solver, native decoder, H5, BI4 read, GPU, CFD, or qualification action is performed here.",
            "Initial particle counts are baseline intent evidence only until the new generated output is checked.",
            "The historical RunPARTs has its own observed sampling; it cannot prove a new dense-.01 run.",
        ],
    }
    plan["sha256"] = canonical_sha(plan)
    return plan


def _write_new(path: Path, value: Mapping[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise HalfCflError(f"refusing to overwrite artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def prepare(output_dir: Path) -> dict[str, Any]:
    """Write request/plan/gate artifacts into a fresh namespace."""
    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise HalfCflError(f"output namespace is not empty: {output_dir}")
    definition = validate_definition_pair(SOURCE_DEF, VARIANT_DEF)
    request = build_gencase_request(variant=VARIANT_DEF)
    gate = audit_same_cfl_runparts()
    gate["sha256"] = canonical_sha(gate)
    gate_path = output_dir / "f7-s2-same-cfl-runparts-end-gate-v1-001.json"
    request_path = output_dir / "f7-s2-half-cfl-gencase-request-v8-001.json"
    plan_path = output_dir / "f7-s2-half-cfl-plan-v2-001.json"
    _write_new(gate_path, gate)
    _write_new(request_path, request)
    plan = build_half_plan(request, gate, request_path=request_path, gate_path=gate_path)
    _write_new(plan_path, plan)
    return {
        "definition_sha256": definition["variant"]["sha256"],
        "request": {"path": str(request_path), "sha256": request["sha256"]},
        "plan": {"path": str(plan_path), "sha256": plan["sha256"]},
        "runparts_gate": {"path": str(gate_path), "sha256": gate["sha256"]},
        "half_solver_ready": False,
        "launch_allowed": {"gencase": True, "half_solver": False},
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("materialize-def", "prepare"))
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    if args.action == "materialize-def":
        print(json.dumps(derive_definition(), sort_keys=True))
        return 0
    if args.output_dir is None:
        parser.error("--output-dir is required for prepare")
    print(json.dumps(prepare(args.output_dir), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
