#!/usr/bin/env python3
"""Materialize M3 request candidates from immutable templates and receipts.

This helper is deliberately a preparation tool.  It never calls the shared
runner, never writes the campaign request directory, and never changes a
template.  It can materialize a postprocess candidate once the selected child
solver receipt is completed.  A comparison candidate is materialized only
when the child postprocess receipt, manifest, and both observation CSVs are
also completed and agree with the mother sources.

The postprocess candidate records every non-hidden regular file currently in
the completed solver attempt.  This keeps the runner's input provenance
complete for the native data that MeasureTool reads, while the comparison
candidate binds only the small metadata and observation sources that its
worker actually reads.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


class FinalizationError(RuntimeError):
    """A source or immutable-template contract is not satisfied."""


class PendingSource(FinalizationError):
    """A source is not present or has not reached completed status yet."""


HERE = Path(__file__).resolve().parent
WORKTREE_ROOT = HERE.parents[6]
ORIGINAL_PROJECT = Path("/home/jade/Projects/DualSPHysics")
OFFICIAL_ROOT = ORIGINAL_PROJECT / "lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4"
OFFICIAL_BIN = OFFICIAL_ROOT / "bin/linux"
UPSTREAM_RUNS = Path("/data/nas/jade/Simulation/DualSPHysics/upstream-first/runs/F1")
M1_F1 = WORKTREE_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/upstream-first/m1/f1"
M3_ROOT = HERE.parent
RUNTIME_V2 = WORKTREE_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
RUNTIME_V6 = WORKTREE_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v6.py"
DSPH_CONFIG = OFFICIAL_BIN / "DsphConfig.xml"
MEASURETOOL = OFFICIAL_BIN / "MeasureTool_linux64"
EXTRACTOR_V2 = M1_F1 / "scripts/extract_reference_observations_v2.sh"
M1_PARSER = M1_F1 / "scripts/compare_spheric_reference_v2.py"
MAPPING = M1_F1 / "reference/spheric-test2-metadata.json"
MOTHER_ACCEPTANCE = M3_ROOT.parent / "fine-mother-acceptance-decision.json"
MOTHER_ACCEPTANCE_SHA256 = "d43d3e85cf804585005a616e2cb0e73a64feead0742d104a8b98d964554a8b77"
MOTHER_CASE = "UF_F1_MDBC_DAMBREAK3D"
MOTHER_SOLVER_ROOT = UPSTREAM_RUNS / MOTHER_CASE / "solver-001"
MOTHER_POST_ROOT = UPSTREAM_RUNS / MOTHER_CASE / "postprocess-001"
MOTHER_SOLVER_RECEIPT = MOTHER_SOLVER_ROOT / "execution-receipt.json"
MOTHER_POST_RECEIPT = MOTHER_POST_ROOT / "execution-receipt.json"
MOTHER_POST_MANIFEST = MOTHER_POST_ROOT / "observations/postprocess-manifest.json"
MOTHER_ELEVATION = MOTHER_POST_ROOT / "observations/measuretool/_elevation_Elevation.csv"
MOTHER_PRESSURE = MOTHER_POST_ROOT / "observations/measuretool/_pressure_Press.csv"


# These hashes protect the prepared templates from accidental edits.  A
# candidate is always a copy of a verified template, never an in-place patch.
TEMPLATE_SHA256 = {
    "H050": {
        "postprocess": "d87fe8bcfb040a49173c09d5330f1bd9ec39484a78f540bab6e7688cb41a32a1",
        "comparison": "883dc11490311773a21d9e573b913030d02e9a75fbb3a6727c56f71251e2cefd",
    },
    "H060": {
        "postprocess": "06ca028944c580ababd4547ba64d191c450dd534e3c190bc6cfc554f0598df7f",
        "comparison": "525eff69c316cfe69ad2b2c88375ffc8a8ee2b2a447efea359a69c9a3ffaafb0",
    },
}


CASE_CONFIG = {
    "H050": {
        "case_id": "UF_F1_MDBC_DP010_H050",
        "depth_m": 0.50,
        "definition": M3_ROOT / "input/UF_F1_MDBC_DP010_H050_Def.xml",
        "case_manifest": M3_ROOT / "manifests/UF_F1_MDBC_DP010_H050.json",
    },
    "H060": {
        "case_id": "UF_F1_MDBC_DP010_H060",
        "depth_m": 0.60,
        "definition": M3_ROOT / "input/UF_F1_MDBC_DP010_H060_Def.xml",
        "case_manifest": M3_ROOT / "manifests/UF_F1_MDBC_DP010_H060.json",
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(path: Path) -> str:
    return str(path.resolve())


def file_binding(path: Path) -> Dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise FinalizationError(f"missing file: {path}")
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)}


def read_json(path: Path, role: str) -> Dict[str, Any]:
    if not path.is_file():
        raise PendingSource(f"{role} is not present: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FinalizationError(f"cannot read {role}: {path}: {error}") from error
    if not isinstance(value, dict):
        raise FinalizationError(f"{role} must be a JSON object: {path}")
    return value


def template_path(case: str, role: str) -> Path:
    return HERE / "requests" / f"UF_F1_MDBC_DP010_{case}-{role}.template.json"


def load_immutable_template(case: str, role: str) -> Tuple[Dict[str, Any], str, Path]:
    path = template_path(case, role)
    expected = TEMPLATE_SHA256[case][role]
    if not path.is_file():
        raise FinalizationError(f"missing {case} {role} template: {path}")
    actual = sha256(path)
    if actual != expected:
        raise FinalizationError(
            f"immutable {case} {role} template changed: expected {expected}, got {actual}"
        )
    value = read_json(path, f"{case} {role} template")
    if value.get("status") != "template_pending_actual_receipts":
        raise FinalizationError(f"{path} is not a pending template")
    if value.get("submission_forbidden") is not True:
        raise FinalizationError(f"{path} no longer forbids direct template submission")
    return value, actual, path


def dedupe(paths: Iterable[Path]) -> List[str]:
    result: List[str] = []
    seen = set()
    for path in paths:
        value = canonical(path)
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


def regular_solver_files(solver_root: Path) -> List[Path]:
    """Return every non-hidden regular file in a completed solver attempt."""
    if not solver_root.is_dir():
        raise PendingSource(f"solver attempt directory is not present: {solver_root}")
    result = []
    for path in sorted(solver_root.rglob("*")):
        relative = path.relative_to(solver_root)
        if any(part.startswith(".") for part in relative.parts):
            continue
        if path.is_file() and not path.is_symlink():
            result.append(path.resolve())
    if not any(path.name.startswith("Part_") and path.suffix == ".bi4" for path in result):
        raise PendingSource(f"completed solver has no native Part_*.bi4 files: {solver_root}")
    return result


def validate_completed_receipt(
    path: Path,
    role: str,
    case_id: str,
    attempt_id: str,
    expected_output_root: Optional[Path] = None,
) -> Dict[str, Any]:
    receipt = read_json(path, role)
    if receipt.get("status") != "completed":
        raise PendingSource(f"{role} is not completed (status={receipt.get('status')!r}): {path}")
    try:
        returncode = int(receipt.get("returncode", receipt.get("exit_code")))
    except (TypeError, ValueError) as error:
        raise FinalizationError(f"{role} has no numeric successful return code: {path}") from error
    if returncode != 0:
        raise FinalizationError(f"{role} has returncode {returncode}: {path}")
    request = receipt.get("request")
    if not isinstance(request, dict):
        raise FinalizationError(f"{role} lacks its bound request: {path}")
    if request.get("case_id") != case_id or request.get("attempt_id") != attempt_id:
        raise FinalizationError(f"{role} identity binding differs: {path}")
    if expected_output_root is not None:
        actual_output = receipt.get("output_root")
        if not isinstance(actual_output, str) or Path(actual_output).resolve() != expected_output_root.resolve():
            raise FinalizationError(f"{role} output_root differs from expected attempt: {path}")
    binding = file_binding(path)
    binding.update(
        {
            "status": receipt.get("status"),
            "returncode": returncode,
            "finished_at_utc": receipt.get("finished_at_utc"),
            "request_sha256": receipt.get("request_sha256"),
        }
    )
    return binding


def validate_postprocess_bundle(
    case_id: str,
    solver_receipt: Dict[str, Any],
    post_root: Path,
    *,
    require_v2_inputs: bool,
) -> Dict[str, Any]:
    post_receipt_path = post_root / "execution-receipt.json"
    manifest_path = post_root / "observations/postprocess-manifest.json"
    elevation_path = post_root / "observations/measuretool/_elevation_Elevation.csv"
    pressure_path = post_root / "observations/measuretool/_pressure_Press.csv"
    post_receipt = validate_completed_receipt(
        post_receipt_path,
        f"{case_id} postprocess receipt",
        case_id,
        "postprocess-001",
        post_root,
    )
    manifest = read_json(manifest_path, f"{case_id} postprocess manifest")
    if manifest.get("case_id") != case_id:
        raise FinalizationError(f"{case_id} manifest case_id differs: {manifest_path}")
    if manifest.get("primary_observation_files") != [canonical(elevation_path)]:
        raise FinalizationError(f"{case_id} manifest does not bind its elevation CSV: {manifest_path}")
    if manifest.get("auxiliary_observation_files") != [canonical(pressure_path)]:
        raise FinalizationError(f"{case_id} manifest does not bind its pressure CSV: {manifest_path}")
    time_policy = manifest.get("time_policy", {})
    if not isinstance(time_policy, dict) or time_policy.get("simulation_window_s") != [0.0, 6.0]:
        raise FinalizationError(f"{case_id} postprocess window is not exactly 0..6 s: {manifest_path}")
    source_hashes = manifest.get("source_hashes", {})
    if not isinstance(source_hashes, dict):
        raise FinalizationError(f"{case_id} manifest source_hashes is not an object: {manifest_path}")
    if source_hashes.get("solver_receipt_sha256") != solver_receipt["sha256"]:
        raise FinalizationError(f"{case_id} manifest solver receipt hash differs: {manifest_path}")
    if require_v2_inputs:
        request = read_json(post_receipt_path, f"{case_id} postprocess receipt")['request']
        listed = {canonical(Path(value)) for value in request.get("input_files", [])}
        for required in (RUNTIME_V2, RUNTIME_V6, DSPH_CONFIG, EXTRACTOR_V2):
            if canonical(required) not in listed:
                raise FinalizationError(
                    f"{case_id} completed postprocess receipt omitted required input {required}"
                )
        command = request.get("command", [])
        if len(command) < 2 or Path(command[1]).resolve() != EXTRACTOR_V2.resolve():
            raise FinalizationError(f"{case_id} completed postprocess did not use extractor v2")
    return {
        "receipt": post_receipt,
        "manifest": file_binding(manifest_path),
        "elevation": file_binding(elevation_path),
        "pressure": file_binding(pressure_path),
        "manifest_source_hashes": source_hashes,
    }


def validate_mother_acceptance() -> Dict[str, Any]:
    decision = read_json(MOTHER_ACCEPTANCE, "mother acceptance decision")
    binding = file_binding(MOTHER_ACCEPTANCE)
    if binding["sha256"] != MOTHER_ACCEPTANCE_SHA256:
        raise FinalizationError(
            f"mother acceptance decision hash changed: expected {MOTHER_ACCEPTANCE_SHA256}, "
            f"got {binding['sha256']}"
        )
    if decision.get("status") != "accepted_for_scoped_internal_numerical_transport_diagnostics":
        raise FinalizationError("mother acceptance decision is not the scoped internal diagnostic acceptance")
    if decision.get("case_id") != MOTHER_CASE or decision.get("frames") != 601:
        raise FinalizationError("mother acceptance decision is not bound to the all-601 mother case")
    if decision.get("fatal_findings") != []:
        raise FinalizationError("mother acceptance decision contains fatal findings")
    binding.update({"status": decision.get("status"), "frames": decision.get("frames")})
    return binding


def static_post_inputs() -> List[Path]:
    return [EXTRACTOR_V2, M1_F1 / "input/elevation.txt", M1_F1 / "input/pressure.txt", MEASURETOOL,
            DSPH_CONFIG, RUNTIME_V2, RUNTIME_V6]


def make_postprocess_candidate(
    case: str,
    config: Mapping[str, Any],
    solver_receipt: Dict[str, Any],
    solver_root: Path,
    template: Mapping[str, Any],
    template_sha: str,
) -> Dict[str, Any]:
    native_files = regular_solver_files(solver_root)
    input_files = dedupe([*static_post_inputs(), solver_root / "execution-receipt.json", *native_files])
    static_bindings = {
        name: file_binding(path)
        for name, path in {
            "extractor_v2": EXTRACTOR_V2,
            "elevation_points": M1_F1 / "input/elevation.txt",
            "pressure_points": M1_F1 / "input/pressure.txt",
            "measuretool": MEASURETOOL,
            "dsph_config": DSPH_CONFIG,
            "runtime_v2": RUNTIME_V2,
            "runtime_v6": RUNTIME_V6,
        }.items()
    }
    candidate = deepcopy(dict(template))
    candidate.update(
        {
            "status": "ready_for_root_review",
            "submission_forbidden": False,
            "candidate_only": True,
            "root_review_required": True,
            "no_launch_performed": True,
            "template_sha256": template_sha,
            "generated_from_solver_finished_at_utc": solver_receipt.get("finished_at_utc"),
            "solver_receipt_sha256": solver_receipt["sha256"],
            "requires_completed_solver_receipt": canonical(solver_root / "execution-receipt.json"),
            "readiness": "completed_child_solver_receipt_and_native_files_bound",
            "launch_authorization": "root-controlled; candidate only; this helper performed no launch",
            "input_files": input_files,
            "input_file_bindings": {
                "static": static_bindings,
                "solver_receipt": solver_receipt,
            },
            "native_solver_files_policy": (
                "all non-hidden regular files below the completed solver attempt, including "
                "data/Part_*.bi4, PartInfo/PartOut/Part_Head, CfgInit_*.vtk, Run*, stdout.log, "
                "and execution-receipt.json"
            ),
            "native_solver_file_count": len(native_files),
            "native_solver_files": [canonical(path) for path in native_files],
            "source_bindings": {
                "solver_receipt": solver_receipt,
                **static_bindings,
            },
            "request_note": (
                "Candidate generated only after a completed child solver receipt. The v2 extractor "
                "writes a new postprocess attempt and does not alter native raw output. Root review "
                "and shared-runner submission remain required."
            ),
        }
    )
    # Keep the candidate's case/depth identity tied to the immutable definition.
    candidate["case_id"] = config["case_id"]
    candidate["physical_axis"]["child_value_m"] = config["depth_m"]
    return candidate


def completed_comparison_sources(case: str, config: Mapping[str, Any], child_solver: Dict[str, Any]) -> Dict[str, Any]:
    child_post_root = UPSTREAM_RUNS / config["case_id"] / "postprocess-001"
    mother_solver = validate_completed_receipt(
        MOTHER_SOLVER_RECEIPT, "mother solver receipt", MOTHER_CASE, "solver-001", MOTHER_SOLVER_ROOT
    )
    mother_acceptance = validate_mother_acceptance()
    mother_bundle = validate_postprocess_bundle(
        MOTHER_CASE, mother_solver, MOTHER_POST_ROOT, require_v2_inputs=False
    )
    child_bundle = validate_postprocess_bundle(
        config["case_id"], child_solver, child_post_root, require_v2_inputs=True
    )
    return {
        "mother_solver_receipt": mother_solver,
        "mother_acceptance": mother_acceptance,
        "mother_postprocess": mother_bundle,
        "child_solver_receipt": child_solver,
        "child_postprocess": child_bundle,
    }


def make_comparison_candidate(
    case: str,
    config: Mapping[str, Any],
    template: Mapping[str, Any],
    template_sha: str,
    sources: Mapping[str, Any],
) -> Dict[str, Any]:
    mother = sources["mother_postprocess"]
    child = sources["child_postprocess"]
    source_paths = [
        MOTHER_SOLVER_RECEIPT,
        MOTHER_POST_RECEIPT,
        MOTHER_POST_MANIFEST,
        MOTHER_ELEVATION,
        MOTHER_PRESSURE,
        UPSTREAM_RUNS / config["case_id"] / "solver-001/execution-receipt.json",
        UPSTREAM_RUNS / config["case_id"] / "postprocess-001/execution-receipt.json",
        UPSTREAM_RUNS / config["case_id"] / "postprocess-001/observations/postprocess-manifest.json",
        UPSTREAM_RUNS / config["case_id"] / "postprocess-001/observations/measuretool/_elevation_Elevation.csv",
        UPSTREAM_RUNS / config["case_id"] / "postprocess-001/observations/measuretool/_pressure_Press.csv",
    ]
    input_files = dedupe([Path(value) for value in template["input_files"]] + source_paths)
    bindings = {path: file_binding(Path(path)) for path in input_files}
    candidate = deepcopy(dict(template))
    candidate.update(
        {
            "status": "ready_for_root_review",
            "submission_forbidden": False,
            "candidate_only": True,
            "root_review_required": True,
            "no_launch_performed": True,
            "template_sha256": template_sha,
            "readiness": "completed_mother_and_child_postprocess_sources_bound",
            "launch_authorization": "root-controlled; candidate only; this helper performed no launch",
            "input_files": input_files,
            "input_file_bindings": bindings,
            "completed_receipt_bindings": {
                "mother_solver": sources["mother_solver_receipt"],
                "mother_postprocess": mother["receipt"],
                "child_solver": sources["child_solver_receipt"],
                "child_postprocess": child["receipt"],
            },
            "mother_acceptance_binding": sources["mother_acceptance"],
            "completed_postprocess_bindings": {
                "mother_manifest": mother["manifest"],
                "mother_elevation_csv": mother["elevation"],
                "mother_pressure_csv": mother["pressure"],
                "child_manifest": child["manifest"],
                "child_elevation_csv": child["elevation"],
                "child_pressure_csv": child["pressure"],
            },
            "solver_receipt_sha256": sources["child_solver_receipt"]["sha256"],
            "child_postprocess_receipt_sha256": child["receipt"]["sha256"],
            "mother_solver_receipt_sha256": sources["mother_solver_receipt"]["sha256"],
            "mother_postprocess_receipt_sha256": mother["receipt"]["sha256"],
            "request_note": (
                "Candidate binds actual completed solver/postprocess receipts, v2 manifests, H/P CSVs, "
                "the all-601 native mother acceptance decision, and immutable definitions. The .50/.60 "
                "fill-height difference is physical; mother .01 s versus child .025 s TimeOut is a "
                "separate sampling difference. Metrics remain diagnostic only: no experimental credit, "
                "no retiming, and no acceptance threshold. Root review and shared-runner submission remain required."
            ),
        }
    )
    return candidate


def write_stable_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise FinalizationError(f"candidate already exists but is not valid JSON: {path}") from error
        if existing != value:
            raise FinalizationError(f"candidate exists with different content; refusing to overwrite: {path}")
        return
    path.write_text(text, encoding="utf-8")


def pending_reason(error: Exception) -> Dict[str, Any]:
    return {"status": "pending_or_blocked", "reason": str(error)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=sorted(CASE_CONFIG), default="H050")
    parser.add_argument(
        "--candidate-dir",
        type=Path,
        default=HERE / "candidates",
        help="directory under this comparison subtree for generated candidates",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    case = args.case
    config = CASE_CONFIG[case]
    case_id = config["case_id"]
    solver_root = UPSTREAM_RUNS / case_id / "solver-001"
    solver_receipt_path = solver_root / "execution-receipt.json"
    post_candidate_path = args.candidate_dir / f"{case_id}-postprocess.ready.json"
    comparison_candidate_path = args.candidate_dir / f"{case_id}-comparison.ready.json"
    report_path = args.candidate_dir / f"{case_id}-finalization-report.json"
    report: Dict[str, Any] = {
        "schema": "ds-data-02.upstream-first.m3.f1-fine-dp010-t025.request-finalization.v1",
        "case_id": case_id,
        "status": "solver_receipt_pending",
        "no_launch_performed": True,
        "candidate_only": True,
        "templates": {},
        "candidates": {},
    }
    try:
        post_template, post_template_sha, post_template_path = load_immutable_template(case, "postprocess")
        comparison_template, comparison_template_sha, comparison_template_path = load_immutable_template(case, "comparison")
        report["templates"] = {
            "postprocess": {"path": canonical(post_template_path), "sha256": post_template_sha},
            "comparison": {"path": canonical(comparison_template_path), "sha256": comparison_template_sha},
        }
    except FinalizationError as error:
        report.update(status="template_contract_failed", error=str(error))
        write_stable_json(report_path, report)
        print(report_path)
        return 2

    try:
        solver_receipt = validate_completed_receipt(
            solver_receipt_path, "child solver receipt", case_id, "solver-001", solver_root
        )
    except PendingSource as error:
        report.update(status="solver_receipt_pending", solver_receipt=pending_reason(error))
        write_stable_json(report_path, report)
        print(report_path)
        return 0
    except FinalizationError as error:
        report.update(status="solver_receipt_invalid", solver_receipt=pending_reason(error))
        write_stable_json(report_path, report)
        print(report_path)
        return 2

    try:
        post_candidate = make_postprocess_candidate(
            case, config, solver_receipt, solver_root, post_template, post_template_sha
        )
        write_stable_json(post_candidate_path, post_candidate)
        report["candidates"]["postprocess"] = {
            "status": "ready_for_root_review",
            "path": canonical(post_candidate_path),
            "solver_receipt_sha256": solver_receipt["sha256"],
            "native_solver_file_count": post_candidate["native_solver_file_count"],
        }
        report["status"] = "postprocess_ready_comparison_pending"
    except FinalizationError as error:
        report.update(status="postprocess_candidate_failed", postprocess=pending_reason(error))
        write_stable_json(report_path, report)
        print(report_path)
        return 2

    try:
        sources = completed_comparison_sources(case, config, solver_receipt)
    except PendingSource as error:
        report["comparison"] = pending_reason(error)
        write_stable_json(report_path, report)
        print(report_path)
        return 0
    except FinalizationError as error:
        report["comparison"] = pending_reason(error)
        report["status"] = "postprocess_ready_comparison_blocked"
        write_stable_json(report_path, report)
        print(report_path)
        return 2

    try:
        comparison_candidate = make_comparison_candidate(
            case, config, comparison_template, comparison_template_sha, sources
        )
        write_stable_json(comparison_candidate_path, comparison_candidate)
    except FinalizationError as error:
        report.update(status="comparison_candidate_failed", comparison=pending_reason(error))
        write_stable_json(report_path, report)
        print(report_path)
        return 2
    report["status"] = "postprocess_and_comparison_ready"
    report["candidates"]["comparison"] = {
        "status": "ready_for_root_review",
        "path": canonical(comparison_candidate_path),
        "child_postprocess_receipt_sha256": sources["child_postprocess"]["receipt"]["sha256"],
        "mother_postprocess_receipt_sha256": sources["mother_postprocess"]["receipt"]["sha256"],
    }
    write_stable_json(report_path, report)
    print(report_path)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FinalizationError as error:
        print(f"request finalization error: {error}", file=sys.stderr)
        raise SystemExit(2)
