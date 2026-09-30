#!/usr/bin/env python3
"""Materialize bounded post-solver F2 evidence requests.

The six V4 qualification requests are GPU requests owned by the primary
process.  This module never launches a solver.  After a solver receipt is
terminal, it creates one CPU request per case for each downstream stage:
native full-state conversion, native finite-surface labels, full Q-I audit,
and an evidence-only preview manifest.  A stage is materialized only when
the preceding stage's actual receipt and output files are present, so the
shared runner never receives placeholder input paths.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


LAB_ROOT = Path(__file__).resolve().parents[4]
WORKTREE_ROOT = LAB_ROOT.parent
FAMILY_ROOT = LAB_ROOT / "campaigns/ds-data-02/families/F2"
SCOPE_ROOT = FAMILY_ROOT / "commensurate_cellcenter_v4"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
DATA_FAMILY_ROOT = DATA_ROOT / "families/F2"
PYTHON = LAB_ROOT / ".venv/bin/python"
PARTVTKOUT = LAB_ROOT / "vendor/official/DualSPHysics_v5.4/bin/linux/PartVTKOut_linux64"
CONVERTER = LAB_ROOT / "scripts/ds_data02_convert.py"
CONVERSION_WRAPPER = FAMILY_ROOT / "f2_commensurate_conversion_wrapper.py"
# The integration worktree owns the reviewed BI4 streaming converter.  It is
# an immutable input to F2 requests; F2 does not edit or copy the generic
# converter into a consumed qualification tree.
DIRECT_CONVERTER = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_direct_convert.py")
DIRECT_DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
TRAJECTORY_IO = LAB_ROOT / "scripts/trajectory_io.py"
INTEGRITY = LAB_ROOT / "scripts/ds_data02_integrity.py"
NATIVE_LABELS = LAB_ROOT / "scripts/f2_native_observations.py"
QI_AUDIT = FAMILY_ROOT / "f2_full_qi_audit.py"
PREVIEW = FAMILY_ROOT / "f2_commensurate_preview.py"
CONVERSION_ADAPTER = FAMILY_ROOT / "f2_commensurate_conversion_adapter.py"
MASS_CORRECTION = SCOPE_ROOT / "mass_semantics_correction.json"
EVENT_DEFINITIONS = FAMILY_ROOT / "event_definitions.json"
QUALITY_CONTRACT = FAMILY_ROOT / "quality_contract.json"
INTEGRATION_SAVE = FAMILY_ROOT / "integration_save_plan.json"

CPU_THREADS = 4
MAX_WALL_SECONDS = 600
STORAGE_BYTES = 8 * 1024**3
STAGE_ORDER = ("conversion", "labels", "qi", "preview")


class PlanError(RuntimeError):
    """Raised when a post-solver stage is not evidence-bound yet."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise PlanError(f"{label} is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise PlanError(f"{label} is not valid JSON: {path}") from error
    if not isinstance(value, dict):
        raise PlanError(f"{label} must be a JSON object: {path}")
    return value


def file_binding(path: Path) -> dict[str, str]:
    path = path.resolve()
    if not path.is_file():
        raise PlanError(f"evidence input is missing: {path}")
    return {"path": str(path), "sha256": sha256(path)}


def unique_paths(paths: Iterable[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        path = Path(path).resolve()
        if path in seen:
            continue
        seen.add(path)
        result.append(path)
    return result


def _qualification_paths() -> list[Path]:
    paths = sorted(SCOPE_ROOT.glob("requests/*_qualification_request.json"))
    if len(paths) != 6:
        raise PlanError(f"expected six V4 qualification requests, found {len(paths)}")
    return paths


def load_qualification_requests() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in _qualification_paths():
        request = load_json(path, "qualification request")
        if request.get("kind") != "qualification" or request.get("family_id") != "F2":
            raise PlanError(f"not an F2 qualification request: {path}")
        case_id = request.get("case_id")
        if not isinstance(case_id, str) or case_id in seen:
            raise PlanError(f"duplicate or invalid qualification case id: {path}")
        if not case_id.startswith("F2_COMM4_"):
            raise PlanError(f"post-solver planner only accepts V4 cases: {case_id}")
        seen.add(case_id)
        request_path = path.resolve()
        request["_request_path"] = str(request_path)
        rows.append(request)
    return rows


def _required_solver_output(receipt: Mapping[str, Any]) -> tuple[Path, list[Path]]:
    output_root = Path(str(receipt.get("output_root", ""))).resolve()
    if not output_root.is_dir():
        raise PlanError(f"solver output root is missing: {output_root}")
    solver_output = output_root / "solver_output"
    if not solver_output.is_dir():
        raise PlanError(f"solver_output directory is missing: {solver_output}")
    required = [solver_output / name for name in ("Run.out", "Run.csv", "RunPARTs.csv")]
    missing = [path for path in required if not path.is_file()]
    if missing:
        raise PlanError("solver receipt is terminal but required logs are missing: " + ", ".join(map(str, missing)))
    data = solver_output / "data"
    frame_files = sorted(data.glob("Part_*.bi4")) + sorted(data.glob("PartOut_*.obi4"))
    if not frame_files:
        raise PlanError(f"solver data contains no native Part_*.bi4/PartOut_*.obi4 frames: {data}")
    return solver_output, [*required, frame_files[0]]


def load_solver_receipts(paths: Iterable[Path]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for path in paths:
        receipt_path = Path(path).resolve()
        receipt = load_json(receipt_path, "solver execution receipt")
        request = receipt.get("request")
        if not isinstance(request, Mapping):
            raise PlanError(f"solver receipt has no request binding: {receipt_path}")
        case_id = request.get("case_id")
        if not isinstance(case_id, str) or not case_id.startswith("F2_COMM4_"):
            raise PlanError(f"solver receipt has invalid V4 case id: {receipt_path}")
        if case_id in rows:
            raise PlanError(f"duplicate solver receipt for {case_id}")
        if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
            raise PlanError(f"solver receipt is not completed successfully: {receipt_path}")
        solver_output, log_inputs = _required_solver_output(receipt)
        rows[case_id] = {
            "path": receipt_path,
            "sha256": sha256(receipt_path),
            "receipt": receipt,
            "solver_output": solver_output,
            "solver_log_inputs": log_inputs,
        }
    if set(rows) != {row["case_id"] for row in load_qualification_requests()}:
        raise PlanError("exactly one completed solver receipt is required for every V4 case")
    return rows


def _owner_paths(request: Mapping[str, Any], compatibility: Mapping[str, Any] | None = None) -> dict[str, Path]:
    artifacts = request.get("gencase_artifacts")
    if not isinstance(artifacts, Mapping):
        raise PlanError(f"qualification request lacks gencase artifact bindings: {request.get('case_id')}")
    if compatibility is None:
        metadata_candidates = [Path(value) for value in request.get("input_files", []) if str(value).endswith(".metadata.json")]
        if len(metadata_candidates) != 1:
            raise PlanError(f"expected one V4 owner metadata input: {request.get('case_id')}")
        metadata = metadata_candidates[0].resolve()
        gencase_receipt = Path(str(artifacts.get("receipt", {}).get("path", ""))).resolve()
    else:
        metadata = Path(str(compatibility["adapted_owner_metadata"]["path"])).resolve()
        gencase_receipt = Path(str(compatibility["adapted_gencase_receipt"]["path"])).resolve()
    metadata_obj = load_json(metadata, "V4 owner metadata")
    definition = Path(str(metadata_obj.get("definition", {}).get("path", ""))).resolve()
    motion = Path(str(metadata_obj.get("motion", {}).get("path", ""))).resolve()
    required = {
        "metadata": metadata,
        "definition": definition,
        "motion": motion,
        "gencase_receipt": gencase_receipt,
        "gencase_xml": Path(str(artifacts.get("xml", {}).get("path", ""))).resolve(),
        "gencase_bi4": Path(str(artifacts.get("bi4", {}).get("path", ""))).resolve(),
        "gencase_motion": Path(str(artifacts.get("copied_motion", {}).get("path", ""))).resolve(),
    }
    for label, path in required.items():
        if not path.is_file():
            raise PlanError(f"{label} input is missing for {request.get('case_id')}: {path}")
    return required


def load_compatibility_manifest(path: Path, qualifications: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    """Validate the derived metadata/receipt aliases before a conversion request.

    The aliases are F2-owned provenance files.  They are allowed to satisfy the
    converter's schema gate only when their original owner metadata, GenCase
    receipt, and completed solver receipt still bind exactly to the frozen
    qualification inputs.  This does not rewrite or re-run any consumed
    execution artifact.
    """
    manifest_path = Path(path).resolve()
    manifest = load_json(manifest_path, "converter compatibility manifest")
    if manifest.get("schema") != "ds-data-02.f2.commensurate-converter-compat-manifest.v1":
        raise PlanError(f"unexpected compatibility manifest schema: {manifest_path}")
    if manifest.get("status") != "derived_provenance_aliases_ready" or manifest.get("source_bytes_unchanged") is not True:
        raise PlanError(f"compatibility manifest is not a derived, source-preserving alias set: {manifest_path}")
    rows = manifest.get("cases")
    if not isinstance(rows, list) or len(rows) != 6:
        raise PlanError(f"compatibility manifest must contain six cases: {manifest_path}")
    if qualifications is None:
        qualifications = {row["case_id"]: row for row in load_qualification_requests()}
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise PlanError(f"invalid compatibility case row: {manifest_path}")
        case_id = str(row.get("case_id", ""))
        if case_id in result or case_id not in qualifications:
            raise PlanError(f"compatibility case is not one of the six qualifications: {case_id}")
        qualification = qualifications[case_id]
        source_owner = _owner_paths(qualification)
        bindings = {
            "source_owner_metadata": row.get("source_owner_metadata"),
            "source_gencase_receipt": row.get("source_gencase_receipt"),
            "source_solver_receipt": row.get("source_solver_receipt"),
            "adapted_owner_metadata": row.get("adapted_owner_metadata"),
            "adapted_gencase_receipt": row.get("adapted_gencase_receipt"),
            "adapted_solver_receipt": row.get("adapted_solver_receipt"),
        }
        if any(not isinstance(value, Mapping) for value in bindings.values()):
            raise PlanError(f"compatibility row lacks complete source/derived bindings: {case_id}")
        for label, value in bindings.items():
            bound_path = Path(str(value["path"])).resolve()
            if not bound_path.is_file() or sha256(bound_path) != str(value.get("sha256", "")):
                raise PlanError(f"compatibility {label} hash/path mismatch: {case_id}")
            bindings[label] = {"path": str(bound_path), "sha256": sha256(bound_path)}
        if bindings["source_owner_metadata"] != file_binding(source_owner["metadata"]):
            raise PlanError(f"compatibility source owner metadata differs from qualification: {case_id}")
        if bindings["source_gencase_receipt"] != file_binding(source_owner["gencase_receipt"]):
            raise PlanError(f"compatibility source GenCase receipt differs from qualification: {case_id}")
        raw_output_root = Path(str(qualification.get("raw_output_root", ""))).resolve()
        attempt_id = str(qualification.get("attempt_id", ""))
        expected_solver_candidates = [raw_output_root / case_id / attempt_id / "execution-receipt.json",
                                      raw_output_root / attempt_id / "execution-receipt.json"]
        expected_solver = next((candidate for candidate in expected_solver_candidates if candidate.is_file()), expected_solver_candidates[0])
        if bindings["source_solver_receipt"] != file_binding(expected_solver):
            raise PlanError(f"compatibility source solver receipt differs from qualification: {case_id}")
        adapted_metadata = load_json(Path(bindings["adapted_owner_metadata"]["path"]), "adapted owner metadata")
        if not str(adapted_metadata.get("schema", "")).endswith("generator.v1"):
            raise PlanError(f"adapted owner metadata does not satisfy converter schema gate: {case_id}")
        adapter = adapted_metadata.get("compatibility_adapter")
        if not isinstance(adapter, Mapping) or adapter.get("derived_only") is not True or adapter.get("no_gencase_rerun") is not True or adapter.get("no_physical_field_change") is not True:
            raise PlanError(f"adapted owner metadata lacks strict derived-only marker: {case_id}")
        if adapter.get("source_owner_metadata") != bindings["source_owner_metadata"]:
            raise PlanError(f"adapted owner metadata source binding mismatch: {case_id}")
        adapted_gencase = load_json(Path(bindings["adapted_gencase_receipt"]["path"]), "adapted GenCase receipt")
        if adapted_gencase.get("schema") != "ds02.execution-receipt.v1" or adapted_gencase.get("status") != "completed" or adapted_gencase.get("returncode") != 0:
            raise PlanError(f"adapted GenCase receipt is not a completed derived receipt: {case_id}")
        adapted_gencase_adapter = adapted_gencase.get("compatibility_adapter")
        if not isinstance(adapted_gencase_adapter, Mapping) or adapted_gencase_adapter.get("source_gencase_receipt") != bindings["source_gencase_receipt"]:
            raise PlanError(f"adapted GenCase receipt source binding mismatch: {case_id}")
        adapted_solver = load_json(Path(bindings["adapted_solver_receipt"]["path"]), "adapted solver receipt")
        if adapted_solver.get("schema") != "ds02.execution-receipt.v1" or adapted_solver.get("status") != "completed" or adapted_solver.get("returncode") != 0:
            raise PlanError(f"adapted solver receipt is not a completed derived receipt: {case_id}")
        adapted_solver_request = adapted_solver.get("request")
        if not isinstance(adapted_solver_request, Mapping) or adapted_solver_request.get("case_id") != case_id:
            raise PlanError(f"adapted solver receipt case binding mismatch: {case_id}")
        if Path(str(adapted_solver_request.get("gencase_receipt", ""))).resolve() != Path(bindings["adapted_gencase_receipt"]["path"]).resolve():
            raise PlanError(f"adapted solver receipt does not bind adapted GenCase receipt: {case_id}")
        result[case_id] = {
            **{key: dict(value) for key, value in bindings.items()},
            "manifest": file_binding(manifest_path),
            "derived_only": True,
            "no_gencase_rerun": True,
        }
    if set(result) != set(qualifications):
        raise PlanError("compatibility manifest does not cover exactly the six qualification cases")
    return result


def _request_prefix(request: Mapping[str, Any]) -> str:
    prefix = Path(str(request.get("gencase_input_prefix", ""))).resolve()
    if not prefix.is_file() and not Path(str(prefix) + ".xml").is_file():
        raise PlanError(f"completed GenCase prefix is not bound: {prefix}")
    return str(prefix)


def _case_slug(case_id: str) -> str:
    return case_id.lower().replace("f2_comm4_", "comm4-")


def _stage_attempt(case_id: str, stage: str, *, compatibility: bool = False, conversion_engine: str = "wrapper") -> str:
    slug = _case_slug(case_id)
    if conversion_engine not in {"wrapper", "direct"}:
        raise PlanError(f"unsupported F2 conversion engine: {conversion_engine}")
    conversion_attempt = (
        f"conversion-f2-{slug}-fullstate-compat-direct-v1"
        if compatibility and conversion_engine == "direct"
        else f"conversion-f2-{slug}-fullstate-compat-scratch-v4"
        if compatibility
        else f"conversion-f2-{slug}-fullstate-v1"
    )
    return {
        "conversion": conversion_attempt,
        "labels": f"labels-f2-{slug}-native-v1",
        "qi": f"full-qi-f2-{slug}-v1",
        "preview": f"preview-f2-{slug}-native-v1",
    }[stage]


def _common_cpu_request(*, request: Mapping[str, Any], case_id: str, attempt_id: str,
                        stage: str, command: list[str], input_files: Iterable[Path],
                        note: str) -> dict[str, Any]:
    files = unique_paths(input_files)
    for path in files:
        if not path.is_file():
            raise PlanError(f"request input is missing before materialization: {path}")
    return {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": "F2",
        "case_id": case_id,
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": stage,
        "command": command,
        "cwd": str(LAB_ROOT),
        "max_wall_seconds": MAX_WALL_SECONDS,
        "cpu_threads": CPU_THREADS,
        "estimated_storage_bytes": STORAGE_BYTES,
        "input_files": [str(path) for path in files],
        "worktree_root": str(WORKTREE_ROOT),
        "raw_output_root": str(DATA_FAMILY_ROOT),
        "source_mother": request.get("source_mother"),
        "mechanism_id": request.get("mechanism_id"),
        "physical_condition_hash": request.get("physical_condition_hash"),
        "numerical_recipe_hash": request.get("numerical_recipe_hash"),
        "event_window_s": request.get("event_window_s", 4.0),
        "solver_launch_forbidden": True,
        "gpu_launch": {"family_owner_launch": False, "primary_process_gpu_only": True},
        "request_note": note,
    }


def _source_bindings(paths: Iterable[Path]) -> dict[str, dict[str, str]]:
    return {str(path.resolve()): file_binding(path) for path in unique_paths(paths)}


def _entry_base(request: Mapping[str, Any], solver: Mapping[str, Any], compatibility: Mapping[str, Any] | None = None) -> dict[str, Any]:
    owner = _owner_paths(request, compatibility)
    gencase = {
        key: file_binding(path) for key, path in owner.items()
        if key != "metadata"
    }
    gencase["metadata"] = file_binding(owner["metadata"])
    solver_binding = file_binding(Path(str(solver["path"])))
    if compatibility is not None:
        solver_binding = dict(compatibility["adapted_solver_receipt"])
    entry = {
        "case_id": request["case_id"],
        "background": request.get("source_mother"),
        "resolution": request.get("numerical_recipe_fields", {}).get("resolution"),
        "physical_condition_hash": request.get("physical_condition_hash"),
        "numerical_recipe_hash": request.get("numerical_recipe_hash"),
        "qualification_request": file_binding(Path(str(request["_request_path"]))),
        "solver_receipt": solver_binding,
        "solver_output": str(solver["solver_output"]),
        "gencase": gencase,
        "owner": {key: file_binding(path) for key, path in owner.items() if key in {"metadata", "definition", "motion"}},
        "gencase_prefix": _request_prefix(request),
    }
    if compatibility is not None:
        entry["source_solver_receipt"] = file_binding(Path(str(solver["path"])))
        entry["compatibility"] = dict(compatibility)
    return entry


def build_conversion_request(request: Mapping[str, Any], solver: Mapping[str, Any], compatibility: Mapping[str, Any] | None = None, *, conversion_engine: str = "wrapper") -> tuple[dict[str, Any], dict[str, Any]]:
    if compatibility is None:
        raise PlanError("conversion request requires an F2 compatibility manifest")
    if conversion_engine not in {"wrapper", "direct"}:
        raise PlanError(f"unsupported F2 conversion engine: {conversion_engine}")
    case_id = str(request["case_id"])
    if Path(str(compatibility["source_solver_receipt"]["path"])).resolve() != Path(str(solver["path"])).resolve():
        raise PlanError(f"compatibility source solver receipt differs for {case_id}")
    entry = _entry_base(request, solver, compatibility)
    owner = _owner_paths(request, compatibility)
    attempt_id = _stage_attempt(case_id, "conversion", compatibility=True, conversion_engine=conversion_engine)
    attempt_root = DATA_FAMILY_ROOT / case_id / attempt_id
    adapted_solver = Path(str(compatibility["adapted_solver_receipt"]["path"])).resolve()
    adapted_gencase = Path(str(compatibility["adapted_gencase_receipt"]["path"])).resolve()
    if conversion_engine == "direct":
        command = [
            str(PYTHON), str(DIRECT_CONVERTER),
            "--data-root", str(Path(str(solver["solver_output"])).resolve() / "data"),
            "--generated-xml", str(owner["gencase_xml"]),
            "--output", "{attempt_root}/trajectory.h5",
            "--report", "{attempt_root}/conversion-report.json",
            "--solver-log", str(Path(str(solver["solver_output"])).resolve() / "Run.out"),
            "--solver-receipt", str(adapted_solver),
            "--gencase-receipt", str(adapted_gencase),
            "--owner-metadata", str(owner["metadata"]),
            "--decoder", str(DIRECT_DECODER),
            "--partvtk", str(PARTVTKOUT),
            "--validation-dir", "{attempt_root}/partvtk-validation",
            "--keep-validation-csv",
        ]
        conversion_inputs = [DIRECT_CONVERTER, DIRECT_DECODER, PARTVTKOUT]
        note = "CPU-only streaming BI4 direct conversion. Official PartVTK validates first/middle/last frames; no solver launch or GPU."
    else:
        command = [
            str(PYTHON), str(CONVERSION_WRAPPER),
            "--solver-receipt", str(adapted_solver),
            "--gencase-receipt", str(adapted_gencase),
            "--owner-metadata", str(owner["metadata"]),
            "--output", "{attempt_root}/trajectory.h5",
            "--report", "{attempt_root}/conversion-report.json",
            "--partvtk-threads", "4",
        ]
        conversion_inputs = [CONVERSION_WRAPPER, CONVERTER]
        note = "CPU-only full native BI4 conversion through an F2 wrapper. PartVTK CSV scratch is outside the runner attempt and removed after hashing; trajectory/report stay in the ownattempt. Preserve typed Zone+Idp identity and source/control hashes; no solver launch or GPU."
    input_files = [*conversion_inputs, TRAJECTORY_IO, MASS_CORRECTION, CONVERSION_ADAPTER,
                   Path(str(compatibility["manifest"]["path"])),
                   Path(str(compatibility["source_owner_metadata"]["path"])),
                   Path(str(compatibility["source_gencase_receipt"]["path"])),
                   Path(str(compatibility["source_solver_receipt"]["path"])),
                   Path(str(compatibility["adapted_solver_receipt"]["path"])),
                   *owner.values(), *solver["solver_log_inputs"]]
    cpu = _common_cpu_request(
        request=request, case_id=case_id, attempt_id=attempt_id, stage="conversion",
        command=command, input_files=input_files,
        note=note,
    )
    cpu.update({
        "expected_outputs": {
            "receipt": str(attempt_root / "execution-receipt.json"),
            "trajectory": str(attempt_root / "trajectory.h5"),
            "conversion_report": str(attempt_root / "conversion-report.json"),
        },
        "source_bindings": _source_bindings(input_files),
        "strict_mass_semantics_sidecar": file_binding(MASS_CORRECTION),
        "compatibility_manifest": dict(compatibility["manifest"]),
        "compatibility_source_bindings": {key: dict(compatibility[key]) for key in compatibility if key.endswith("_metadata") or key.endswith("_receipt")},
    })
    entry.update({"stage": "conversion", "attempt_id": attempt_id, "request": str(attempt_root / "request.json"),
                 "expected_outputs": cpu["expected_outputs"]})
    return cpu, entry


def _load_stage_manifest(path: Path, expected_stage: str) -> list[dict[str, Any]]:
    manifest = load_json(path, f"{expected_stage} stage manifest")
    if manifest.get("stage") != expected_stage or manifest.get("status") != "requests_ready_to_schedule":
        raise PlanError(f"{path} is not a materialized {expected_stage} stage manifest")
    entries = manifest.get("cases")
    if not isinstance(entries, list) or len(entries) != 6:
        raise PlanError(f"{path} must contain six {expected_stage} cases")
    return entries


def _completed_artifact(entry: Mapping[str, Any], key: str) -> tuple[Path, Path, dict[str, Any]]:
    output_maps: list[Mapping[str, Any]] = []
    outputs = entry.get("expected_outputs")
    if isinstance(outputs, Mapping):
        output_maps.append(outputs)
    upstream = entry.get("upstream_outputs")
    if isinstance(upstream, Mapping):
        output_maps.extend(value for value in upstream.values() if isinstance(value, Mapping))
    selected: Mapping[str, Any] | None = next((value for value in output_maps if key in value), None)
    if selected is None:
        raise PlanError(f"stage entry {entry.get('case_id')} lacks output {key}")
    artifact = Path(str(selected[key])).resolve()
    if not artifact.is_file():
        raise PlanError(f"required {entry.get('stage')} output is missing: {artifact}")
    receipt_path = Path(str(selected.get("receipt", ""))).resolve()
    receipt = load_json(receipt_path, f"{entry.get('stage')} execution receipt")
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise PlanError(f"{entry.get('stage')} receipt is not successful: {receipt_path}")
    return artifact, receipt_path, receipt


def _compatibility_inputs(entry: Mapping[str, Any]) -> list[Path]:
    compatibility = entry.get("compatibility")
    if not isinstance(compatibility, Mapping):
        raise PlanError(f"post-solver entry lacks converter compatibility provenance: {entry.get('case_id')}")
    paths = [CONVERSION_ADAPTER]
    for key in (
        "manifest", "source_owner_metadata", "source_gencase_receipt", "source_solver_receipt",
        "adapted_owner_metadata", "adapted_gencase_receipt", "adapted_solver_receipt",
    ):
        binding = compatibility.get(key)
        if not isinstance(binding, Mapping):
            raise PlanError(f"post-solver compatibility binding is incomplete: {entry.get('case_id')} {key}")
        paths.append(Path(str(binding["path"])).resolve())
    return paths


def build_labels_request(entry: Mapping[str, Any], qualification: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    trajectory, conversion_receipt_path, conversion_receipt = _completed_artifact(entry, "trajectory")
    conversion_report, _, _ = _completed_artifact(entry, "conversion_report")
    case_id = str(entry["case_id"])
    compatibility = entry.get("compatibility")
    owner = _owner_paths(qualification, compatibility if isinstance(compatibility, Mapping) else None)
    attempt_id = _stage_attempt(case_id, "labels")
    attempt_root = DATA_FAMILY_ROOT / case_id / attempt_id
    command = [
        str(PYTHON), str(NATIVE_LABELS),
        "--trajectory", str(trajectory),
        "--owner-metadata", str(owner["metadata"]),
        "--conversion-report", str(conversion_report),
        "--output", "{attempt_root}/f2-native-labels.h5",
        "--report", "{attempt_root}/f2-native-observations.json",
    ]
    input_files = [NATIVE_LABELS, INTEGRITY, TRAJECTORY_IO, EVENT_DEFINITIONS, QUALITY_CONTRACT,
                   MASS_CORRECTION, owner["metadata"], owner["definition"], owner["motion"],
                   trajectory, conversion_report, conversion_receipt_path, *_compatibility_inputs(entry)]
    cpu = _common_cpu_request(
        request=qualification, case_id=case_id, attempt_id=attempt_id, stage="labels",
        command=command, input_files=input_files,
        note="CPU-only F2 native finite moving cup/receiver/tray transport labels. Read immutable full state and actual rigid pose; retain typed identities and separate numerical unknown from physical spill/tray; no solver launch or GPU.",
    )
    cpu.update({
        "expected_outputs": {
            "receipt": str(attempt_root / "execution-receipt.json"),
            "labels": str(attempt_root / "f2-native-labels.h5"),
            "labels_report": str(attempt_root / "f2-native-observations.json"),
        },
        "source_bindings": _source_bindings(input_files),
        "conversion_receipt": file_binding(conversion_receipt_path),
        "conversion_report": file_binding(conversion_report),
    })
    new_entry = dict(entry)
    new_entry["upstream_outputs"] = {**dict(entry.get("upstream_outputs", {})), "conversion": dict(entry["expected_outputs"])}
    new_entry.update({"stage": "labels", "attempt_id": attempt_id, "request": str(attempt_root / "request.json"),
                      "expected_outputs": cpu["expected_outputs"], "conversion_receipt": str(conversion_receipt_path),
                      "conversion_receipt_sha256": sha256(conversion_receipt_path)})
    return cpu, new_entry


def build_qi_request(entry: Mapping[str, Any], qualification: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    trajectory, conversion_receipt_path, _ = _completed_artifact(entry, "trajectory")
    conversion_report, _, _ = _completed_artifact(entry, "conversion_report")
    labels, labels_receipt_path, _ = _completed_artifact(entry, "labels")
    labels_report, _, _ = _completed_artifact(entry, "labels_report")
    solver_receipt = Path(str(entry["solver_receipt"]["path"])).resolve()
    solver = load_json(solver_receipt, "solver receipt")
    solver_output, solver_logs = _required_solver_output(solver)
    compatibility = entry.get("compatibility")
    owner = _owner_paths(qualification, compatibility if isinstance(compatibility, Mapping) else None)
    case_id = str(entry["case_id"])
    attempt_id = _stage_attempt(case_id, "qi")
    attempt_root = DATA_FAMILY_ROOT / case_id / attempt_id
    command = [
        str(PYTHON), str(QI_AUDIT),
        "--trajectory", str(trajectory),
        "--labels", str(labels),
        "--owner-metadata", str(owner["metadata"]),
        "--conversion-report", str(conversion_report),
        "--solver-output", str(solver_output),
        "--gencase-receipt", str(owner["gencase_receipt"]),
        "--gencase-prefix", str(entry["gencase_prefix"]),
        "--definition", str(owner["definition"]),
        "--motion", str(owner["motion"]),
        "--partvtkout", str(PARTVTKOUT),
        "--output-dir", "{attempt_root}",
    ]
    input_files = [QI_AUDIT, INTEGRITY, EVENT_DEFINITIONS, QUALITY_CONTRACT, INTEGRATION_SAVE,
                   MASS_CORRECTION, owner["metadata"], owner["definition"], owner["motion"],
                   owner["gencase_receipt"], owner["gencase_xml"], owner["gencase_bi4"], owner["gencase_motion"],
                   solver_receipt, *solver_logs, trajectory, conversion_report, conversion_receipt_path,
                   labels, labels_report, labels_receipt_path, PARTVTKOUT, *_compatibility_inputs(entry)]
    cpu = _common_cpu_request(
        request=qualification, case_id=case_id, attempt_id=attempt_id, stage="audit",
        command=command, input_files=input_files,
        note="CPU-only F2 full Q-I audit of native typed lifecycle, PartVTKOut exclusions, actual moving-body pose, finite cup/receiver/tray transport, and source/control bindings. Q-N and production remain unassessed; no solver launch or GPU.",
    )
    cpu["cpu_task_kind"] = "audit"
    cpu.update({
        "expected_outputs": {
            "receipt": str(attempt_root / "execution-receipt.json"),
            "qi_report": str(attempt_root / "full-qi-audit.json"),
        },
        "source_bindings": _source_bindings(input_files),
        "solver_receipt": file_binding(solver_receipt),
        "solver_output": str(solver_output),
        "labels_receipt": file_binding(labels_receipt_path),
        "labels_report": file_binding(labels_report),
        "strict_mass_semantics_sidecar": file_binding(MASS_CORRECTION),
        "qualification_gate_note": "strict continuous mass sidecar is evidence-bound separately; this request cannot grant Q-I/Q-N or production eligibility",
    })
    new_entry = dict(entry)
    new_entry["upstream_outputs"] = {**dict(entry.get("upstream_outputs", {})), "labels": dict(entry["expected_outputs"])}
    new_entry.update({"stage": "qi", "attempt_id": attempt_id, "request": str(attempt_root / "request.json"),
                      "expected_outputs": cpu["expected_outputs"], "labels_receipt": str(labels_receipt_path),
                      "labels_receipt_sha256": sha256(labels_receipt_path)})
    return cpu, new_entry


def build_preview_request(entry: Mapping[str, Any], qualification: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    trajectory, conversion_receipt_path, _ = _completed_artifact(entry, "trajectory")
    conversion_report, _, _ = _completed_artifact(entry, "conversion_report")
    labels, labels_receipt_path, _ = _completed_artifact(entry, "labels")
    labels_report, _, _ = _completed_artifact(entry, "labels_report")
    qi_report, qi_receipt_path, _ = _completed_artifact(entry, "qi_report")
    compatibility = entry.get("compatibility")
    owner = _owner_paths(qualification, compatibility if isinstance(compatibility, Mapping) else None)
    case_id = str(entry["case_id"])
    attempt_id = _stage_attempt(case_id, "preview")
    attempt_root = DATA_FAMILY_ROOT / case_id / attempt_id
    command = [
        str(PYTHON), str(PREVIEW),
        "--trajectory", str(trajectory),
        "--labels", str(labels),
        "--labels-report", str(labels_report),
        "--qi-report", str(qi_report),
        "--owner-metadata", str(owner["metadata"]),
        "--conversion-report", str(conversion_report),
        "--motion", str(owner["motion"]),
        "--event-definitions", str(EVENT_DEFINITIONS),
        "--quality-contract", str(QUALITY_CONTRACT),
        "--output", "{attempt_root}/preview-manifest.json",
    ]
    input_files = [PREVIEW, TRAJECTORY_IO, EVENT_DEFINITIONS, QUALITY_CONTRACT, MASS_CORRECTION,
                   owner["metadata"], owner["definition"], owner["motion"], trajectory, conversion_report,
                   conversion_receipt_path, labels, labels_report, labels_receipt_path,
                   qi_report, qi_receipt_path, *_compatibility_inputs(entry)]
    cpu = _common_cpu_request(
        request=qualification, case_id=case_id, attempt_id=attempt_id, stage="preview",
        command=command, input_files=input_files,
        note="CPU-only evidence preview manifest from immutable native HDF5, actual moving-cup pose, and finite-surface transport labels. It lists real frame references and required event phases; it grants no Q-I, Q-N, or production status.",
    )
    cpu.update({
        "expected_outputs": {
            "receipt": str(attempt_root / "execution-receipt.json"),
            "preview_manifest": str(attempt_root / "preview-manifest.json"),
        },
        "source_bindings": _source_bindings(input_files),
        "qi_report": file_binding(qi_report),
        "labels_report": file_binding(labels_report),
        "strict_mass_semantics_sidecar": file_binding(MASS_CORRECTION),
    })
    new_entry = dict(entry)
    new_entry["upstream_outputs"] = {**dict(entry.get("upstream_outputs", {})), "qi": dict(entry["expected_outputs"])}
    new_entry.update({"stage": "preview", "attempt_id": attempt_id, "request": str(attempt_root / "request.json"),
                      "expected_outputs": cpu["expected_outputs"], "qi_receipt": str(qi_receipt_path),
                      "qi_receipt_sha256": sha256(qi_receipt_path)})
    return cpu, new_entry


def write_stage(*, stage: str, requests: list[tuple[dict[str, Any], dict[str, Any]]], output_dir: Path) -> Path:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    request_dir = output_dir / "requests"
    request_dir.mkdir(exist_ok=True)
    entries: list[dict[str, Any]] = []
    for request, entry in requests:
        path = request_dir / f"{entry['case_id']}_{stage}_request.json"
        if path.exists():
            raise PlanError(f"refusing to overwrite staged request: {path}")
        path.write_text(json.dumps(request, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        entry = dict(entry)
        entry["request"] = str(path.resolve())
        entry["request_sha256"] = sha256(path)
        entries.append(entry)
    manifest = {
        "schema": "ds-data-02.f2.commensurate-postsolver-stage.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "family_id": "F2",
        "scope_id": "F2_SCOPE_COMMENSURATE_CELLCENTER_V4",
        "stage": stage,
        "status": "requests_ready_to_schedule",
        "requests_are_unlaunched": True,
        "solver_launch_forbidden": True,
        "cpu_resources": {"cpu_threads": CPU_THREADS, "max_wall_seconds": MAX_WALL_SECONDS, "estimated_storage_bytes": STORAGE_BYTES},
        "cases": entries,
    }
    manifest_path = output_dir / f"postsolver-{stage}-manifest.json"
    if manifest_path.exists():
        raise PlanError(f"refusing to overwrite stage manifest: {manifest_path}")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def materialize(stage: str, *, solver_receipts: list[Path], prior_manifest: Path | None,
                compatibility_manifest: Path | None, output_dir: Path, conversion_engine: str = "wrapper") -> Path:
    qualifications = {row["case_id"]: row for row in load_qualification_requests()}
    if stage == "conversion":
        solvers = load_solver_receipts(solver_receipts)
        if compatibility_manifest is None:
            raise PlanError("conversion requires --compatibility-manifest")
        compatibility = load_compatibility_manifest(compatibility_manifest, qualifications)
        return write_stage(
            stage=stage,
            requests=[build_conversion_request(qualifications[case_id], solvers[case_id], compatibility[case_id], conversion_engine=conversion_engine) for case_id in sorted(qualifications)],
            output_dir=output_dir,
        )
    if prior_manifest is None:
        raise PlanError(f"--prior-manifest is required for {stage}")
    previous_stage = {"labels": "conversion", "qi": "labels", "preview": "qi"}[stage]
    entries = _load_stage_manifest(prior_manifest.resolve(), previous_stage)
    by_case = {entry["case_id"]: entry for entry in entries}
    if set(by_case) != set(qualifications):
        raise PlanError(f"{previous_stage} manifest does not contain exactly the six V4 cases")
    builders = {"labels": build_labels_request, "qi": build_qi_request, "preview": build_preview_request}
    return write_stage(stage=stage, requests=[builders[stage](by_case[case_id], qualifications[case_id]) for case_id in sorted(qualifications)], output_dir=output_dir)


def write_deferred_plan(path: Path) -> None:
    plan = {
        "schema": "ds-data-02.f2.commensurate-postsolver-plan.v1",
        "family_id": "F2",
        "scope_id": "F2_SCOPE_COMMENSURATE_CELLCENTER_V4",
        "status": "deferred_until_six_solver_receipts_are_terminal",
        "qualification_claim": "none",
        "production_claim": "none",
        "solver_launch_authority": "primary_process_via_shared_runner_only",
        "planner_launches_solver": False,
        "input_policy": "each stage is materialized only after all six actual upstream receipts and required artifacts exist; placeholder input paths are rejected",
        "compatibility_policy": "conversion uses an F2-derived generator-schema alias only after source owner metadata, GenCase receipt, and completed solver receipt hashes are validated; consumed bytes remain unchanged",
        "conversion_engine_policy": {
            "direct": "preferred for fine/native evidence: integration BI4 streaming converter with PartVTK first/middle/last checks",
            "wrapper": "legacy full-frame PartVTK CSV path retained only as bounded diagnostic evidence",
        },
        "resource_plan": {
            "per_request": {"cpu_threads": CPU_THREADS, "max_wall_seconds": MAX_WALL_SECONDS, "estimated_storage_bytes": STORAGE_BYTES},
            "conversion_concurrency": 2,
            "gpu_requests": 0,
            "stages": [
                {"stage": "conversion", "cpu_task_kind": "conversion", "output": "trajectory.h5 + conversion-report.json", "requires": "six completed solver receipts and native solver logs/BI4"},
                {"stage": "labels", "cpu_task_kind": "labels", "output": "f2-native-labels.h5 + f2-native-observations.json", "requires": "six completed conversion receipts and full-state HDF5"},
                {"stage": "qi", "cpu_task_kind": "audit", "output": "full-qi-audit.json + PartVTKOut evidence", "requires": "six completed label and conversion receipts plus solver logs, gencase prefix, XML/BI4/motion"},
                {"stage": "preview", "cpu_task_kind": "preview", "output": "preview-manifest.json with actual frame references", "requires": "six completed Q-I receipts, labels, and full-state HDF5"}
            ]
        },
        "materialize_command": "lagrangian-fluid-lab/.venv/bin/python campaigns/ds-data-02/families/F2/f2_commensurate_postsolver.py materialize --stage STAGE --solver-receipt RECEIPT ... --compatibility-manifest COMPAT_MANIFEST --conversion-engine direct --output-dir OUTPUT_DIR",
        "next_stage_commands": {
            "conversion": "provide all six --solver-receipt arguments, the F2 compatibility manifest, and --conversion-engine direct",
            "labels": "use --prior-manifest postsolver-conversion-manifest.json",
            "qi": "use --prior-manifest postsolver-labels-manifest.json",
            "preview": "use --prior-manifest postsolver-qi-manifest.json"
        },
        "mass_semantics_correction": file_binding(MASS_CORRECTION),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    describe = sub.add_parser("describe")
    describe.add_argument("--output", type=Path, default=SCOPE_ROOT / "postsolver_plan.json")
    materialize_parser = sub.add_parser("materialize")
    materialize_parser.add_argument("--stage", choices=STAGE_ORDER, required=True)
    materialize_parser.add_argument("--solver-receipt", action="append", type=Path, default=[])
    materialize_parser.add_argument("--prior-manifest", type=Path)
    materialize_parser.add_argument("--compatibility-manifest", type=Path)
    materialize_parser.add_argument("--conversion-engine", choices=("wrapper", "direct"), default="wrapper")
    materialize_parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == "describe":
            write_deferred_plan(args.output.resolve())
            print(json.dumps({"status": "written", "path": str(args.output.resolve()), "sha256": sha256(args.output.resolve())}, indent=2))
        else:
            if args.stage == "conversion" and len(args.solver_receipt) != 6:
                raise PlanError("conversion requires exactly six --solver-receipt arguments")
            path = materialize(args.stage, solver_receipts=args.solver_receipt,
                               prior_manifest=args.prior_manifest,
                               compatibility_manifest=args.compatibility_manifest,
                               output_dir=args.output_dir,
                               conversion_engine=args.conversion_engine)
            print(json.dumps({"status": "requests_ready_to_schedule", "stage": args.stage,
                              "manifest": str(path), "sha256": sha256(path)}, indent=2))
    except (PlanError, OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"f2_commensurate_postsolver: {error}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
