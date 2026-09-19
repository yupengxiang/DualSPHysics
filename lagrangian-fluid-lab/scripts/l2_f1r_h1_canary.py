#!/usr/bin/env python3
"""Run one bounded F1R-H1 runtime-domain repair canary.

H1 changes one numerical input from the retained F1 canary: the resolved
runtime-domain upper face is materialised explicitly at ``zmax=1.35 m``.
The source recipe, geometry, background, nominal spacing, and solver options
remain unchanged.  This module deliberately has its own case, run, artifact,
and trajectory paths.  It never calls the resume controller, changes the
shared state/ledger, or emits a qualification receipt.

The post-run evidence joins three independent views of particle loss:

* native ``RunPARTs.csv`` exclusion counters,
* native ``PartOut_*.obi4`` identities decoded by ``PartVTKOut``, and
* the normalized HDF5 identity/lifecycle trajectory.

The retained F1 evidence is copied into the report as a read-only ``before``
baseline so the position-exclusion mechanism can be compared directly.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET
from typing import Any

try:
    from scripts import l2_c1_canary as c1
    from scripts import l2_f1r_audit as f1r
    from scripts.campaign_runner import execute_attempt
    from scripts.l2_campaign import inspect_hdf5, repo_relative
    from scripts.trajectory_io import convert_streaming
    from scripts.w02_semantics import partvtk_csv
except ModuleNotFoundError:  # direct invocation from scripts/
    import l2_c1_canary as c1
    import l2_f1r_audit as f1r
    from campaign_runner import execute_attempt
    from l2_campaign import inspect_hdf5, repo_relative
    from trajectory_io import convert_streaming
    from w02_semantics import partvtk_csv


LAB = Path(__file__).resolve().parents[1]
CAMPAIGN = LAB / "campaigns" / "l2-multifamily"
H1_ROOT = CAMPAIGN / "f1r-h1"
CASE_ID = "L2_F1R_H1_runtime_domain_repair"
H1_ARTIFACT_ROOT = H1_ROOT / "artifacts"
H1_INPUT_ROOT = H1_ARTIFACT_ROOT / CASE_ID / "input"
H1_GENERATED_ROOT = H1_ARTIFACT_ROOT / CASE_ID / "generated"
H1_RUN_ROOT = H1_ROOT / "runs"
H1_DATA_ROOT = H1_ROOT / "data"
H1_CSV_ROOT = H1_ARTIFACT_ROOT / CASE_ID / "csv"
H1_DEFINITION = H1_INPUT_ROOT / f"{CASE_ID}_Def.xml"
H1_PREFIX = H1_GENERATED_ROOT / CASE_ID
H1_HDF5 = H1_DATA_ROOT / f"{CASE_ID}.h5"
H1_REPORT = H1_ARTIFACT_ROOT / CASE_ID / "h1-report.json"
H1_ZMAX = 1.35
H1_GPU_DEFAULT = 7

BIN = LAB / "vendor" / "official" / "DualSPHysics_v5.4" / "bin" / "linux"
GENCASE = BIN / "GenCase_linux64"
SOLVER = BIN / "DualSPHysics5.4_linux64"
INVENTORY = LAB / "campaigns" / "v0.1-candidate" / "w00-inventory.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def _rel(path: Path) -> str:
    return repo_relative(path)


def _environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["LD_LIBRARY_PATH"] = f"{BIN}:{environment.get('LD_LIBRARY_PATH', '')}"
    return environment


def _canonical_without_runtime_domain(path: Path) -> bytes:
    """Serialize a definition after removing only simulation-domain nodes."""

    root = ET.parse(path).getroot()
    for parent in root.iter():
        for child in list(parent):
            if child.tag == "simulationdomain":
                parent.remove(child)
    # ``ElementTree.indent`` changes whitespace while materialising the
    # repair.  Whitespace-only text is formatting, not a recipe parameter.
    for node in root.iter():
        if node.text is not None and not node.text.strip():
            node.text = None
        if node.tail is not None and not node.tail.strip():
            node.tail = None
    return ET.tostring(root, encoding="utf-8")


def recipe_contract() -> dict[str, Any]:
    """Prove H1 differs from the retained recipe only in runtime-domain XML."""

    baseline_domain = f1r.resolve_runtime_domain(f1r.F1_GENERATED_XML)
    return {
        "baseline_definition": _rel(f1r.F1_DEFINITION),
        "baseline_definition_sha256": _sha256(f1r.F1_DEFINITION),
        "baseline_generated_xml": _rel(f1r.F1_GENERATED_XML),
        "baseline_generated_xml_sha256": _sha256(f1r.F1_GENERATED_XML),
        "baseline_resolved_zmax_m": None if baseline_domain is None else baseline_domain.get("zmax"),
        "h1_required_zmax_m": H1_ZMAX,
        "non_domain_recipe_sha256": {
            "baseline": hashlib.sha256(_canonical_without_runtime_domain(f1r.F1_DEFINITION)).hexdigest(),
            "h1": hashlib.sha256(_canonical_without_runtime_domain(H1_DEFINITION)).hexdigest()
            if H1_DEFINITION.is_file()
            else None,
        },
        "same_non_domain_recipe": (
            H1_DEFINITION.is_file()
            and _canonical_without_runtime_domain(f1r.F1_DEFINITION)
            == _canonical_without_runtime_domain(H1_DEFINITION)
        ),
        "unchanged_recipe_fields": [
            "geometry/background: center obstacle",
            "dp=0.0075 m",
            "gravity and fluid source",
            "CFL=0.2, DBC, VerletSteps=40",
            "SavePosDouble=2, TimeMax=0.6 s, TimeOut=0.02 s",
        ],
    }


def materialize_definition(destination: Path = H1_DEFINITION) -> Path:
    """Copy the retained F1 recipe and apply only the explicit H1 domain."""

    if not f1r.F1_DEFINITION.is_file():
        raise FileNotFoundError(f"retained F1 definition is missing: {f1r.F1_DEFINITION}")
    f1r.apply_runtime_domain_repair(f1r.F1_DEFINITION, destination, zmax=H1_ZMAX)
    root = ET.parse(destination).getroot()
    domain = root.find(".//execution/parameters/simulationdomain")
    if domain is None or domain.find("posmax") is None:
        raise RuntimeError("H1 definition did not contain an explicit simulation domain")
    actual_zmax = float(domain.find("posmax").attrib["z"])
    if abs(actual_zmax - H1_ZMAX) > 1e-12:
        raise RuntimeError(f"H1 zmax mismatch: {actual_zmax} != {H1_ZMAX}")
    return destination


def generate_case() -> dict[str, Any]:
    """Run GenCase into the isolated H1 artifact directory."""

    if not GENCASE.is_file():
        raise FileNotFoundError(f"official GenCase is missing: {GENCASE}")
    H1_GENERATED_ROOT.mkdir(parents=True, exist_ok=True)
    process = subprocess.run(
        [str(GENCASE), str(H1_DEFINITION.with_suffix("")), str(H1_PREFIX), "-save:all"],
        cwd=H1_INPUT_ROOT,
        env=_environment(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    (H1_GENERATED_ROOT / "gencase.stdout.log").write_text(process.stdout)
    generated_xml = H1_PREFIX.with_suffix(".xml")
    if process.returncode != 0 or not generated_xml.is_file():
        raise RuntimeError(f"GenCase failed for H1: {process.stdout[-1600:]}")
    resolved_domain = f1r.resolve_runtime_domain(generated_xml)
    if resolved_domain is None or abs(float(resolved_domain["zmax"]) - H1_ZMAX) > 1e-8:
        raise RuntimeError(f"generated H1 XML did not resolve to zmax={H1_ZMAX}: {resolved_domain}")
    return {
        "returncode": process.returncode,
        "definition": H1_DEFINITION,
        "definition_sha256": _sha256(H1_DEFINITION),
        "generated_xml": generated_xml,
        "generated_xml_sha256": _sha256(generated_xml),
        "resolved_runtime_domain": resolved_domain,
        "gencase_binary": _rel(GENCASE),
        "gencase_binary_sha256": _sha256(GENCASE),
    }


def gpu_preflight(physical_gpu: int) -> dict[str, Any]:
    """Require an idle, inventory-allowlisted physical GPU for one job."""

    allowed = c1.inventory_allowlist()
    record = c1.require_idle_allowed_gpu(physical_gpu, allowed)
    return {
        "physical_gpu_index": physical_gpu,
        "allowlist_source": _rel(INVENTORY),
        "allowlisted_uuid": record["uuid"],
        "preflight_record": record,
        "cuda_visible_devices": str(physical_gpu),
        "solver_gpu_argument": 0,
        "single_device_namespace": True,
        "policy": "physical GPU is rechecked immediately before launch; solver sees only logical GPU 0",
    }


def run_solver(prepared: dict[str, Any], physical_gpu: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """Launch exactly one isolated solver attempt and return launch evidence."""

    launch_record = gpu_preflight(physical_gpu)
    environment = _environment()
    environment["CUDA_VISIBLE_DEVICES"] = str(physical_gpu)
    result = execute_attempt(
        CASE_ID,
        [str(SOLVER), "-gpu:0", str(H1_PREFIX), "{output}"],
        H1_RUN_ROOT,
        cwd=LAB,
        env=environment,
        evidence_glob="data/Part_*.bi4",
        required_text="Finished execution (code=0)",
        timeout_seconds=3600,
        resource_category="development",
    )
    launch_record.update(
        {
            "launch_record": launch_record["preflight_record"],
            "cuda_visible_devices_at_launch": environment.get("CUDA_VISIBLE_DEVICES"),
            "solver_gpu_argument_at_launch": 0,
            "solver_binary": _rel(SOLVER),
            "solver_binary_sha256": _sha256(SOLVER),
        }
    )
    result.update(
        {
            "gpu_isolation": launch_record,
            "definition_sha256": prepared["definition_sha256"],
            "generated_xml_sha256": prepared["generated_xml_sha256"],
        }
    )
    return result, launch_record


def _aggregate_runparts(runparts: list[dict[str, Any]]) -> dict[str, int]:
    totals: Counter[str] = Counter()
    for row in runparts:
        for reason, count in (row.get("reason_counts") or {}).items():
            totals[str(reason)] += int(count or 0)
    return dict(totals)


def _position_counts(
    *,
    runparts: dict[str, int],
    partout: dict[str, Any],
    identity: dict[str, Any],
) -> dict[str, int | None]:
    reason_counts = identity.get("reason_counts") or {}
    partout_counts = partout.get("reason_counts") or {}
    return {
        "runparts": int(runparts.get("position", 0)),
        "partout": int(partout_counts.get("position", 0)),
        "hdf5_identity_join": int(reason_counts.get("position", 0)),
        "hdf5_missing_initial_identity": int(identity.get("missing_initial_identity_count", 0)),
        "hdf5_native_join": int(identity.get("native_join_count", 0)),
        "runtime_domain_ceiling_classified": int(
            identity.get("runtime_domain_ceiling_classified_count", 0)
        ),
    }


def compare_position_exclusions(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Compare native and HDF5 position-exclusion counts without promotion."""

    before_counts = before["position_exclusion"]
    after_counts = after["position_exclusion"]
    keys = (
        "runparts",
        "partout",
        "hdf5_identity_join",
        "hdf5_missing_initial_identity",
        "hdf5_native_join",
        "runtime_domain_ceiling_classified",
    )
    delta = {key: int(after_counts[key]) - int(before_counts[key]) for key in keys}
    removed = all(int(after_counts[key]) == 0 for key in keys[:4])
    return {
        "before": dict(before_counts),
        "after": dict(after_counts),
        "delta_after_minus_before": delta,
        "position_exclusion_removed": removed,
        "interpretation": (
            "H1 removed the bounded canary's native position-exclusion mechanism"
            if removed
            else "H1 did not remove every bounded position-exclusion signal"
        ),
    }


def _baseline_snapshot() -> dict[str, Any]:
    if not f1r.REPORT.is_file():
        raise FileNotFoundError(f"retained F1 evidence report is missing: {f1r.REPORT}")
    payload = json.loads(f1r.REPORT.read_text())
    evidence = payload.get("native_failure_evidence", {})
    identity = evidence.get("identity_join", {})
    partout = evidence.get("partout", {})
    runparts = _aggregate_runparts(evidence.get("runparts_events", []))
    position = _position_counts(runparts=runparts, partout=partout, identity=identity)
    input_payload = payload.get("input", {})
    attempt_payload = payload.get("attempt", {})
    return {
        "source": "retained F1R evidence audit; read-only",
        "report": _rel(f1r.REPORT),
        "report_sha256": _sha256(f1r.REPORT),
        "attempt_id": attempt_payload.get("attempt_id"),
        "hdf5": input_payload.get("hdf5", _rel(f1r.F1_HDF5)),
        "hdf5_sha256": _sha256(f1r.F1_HDF5),
        "source_definition_sha256": input_payload.get("definition_sha256"),
        "generated_xml_sha256": input_payload.get("generated_xml_sha256"),
        "runparts_reason_counts": runparts,
        "partout_status": partout.get("status"),
        "partout_reason_counts": partout.get("reason_counts", {}),
        "identity_join": {
            key: value
            for key, value in identity.items()
            if key != "rows"
        },
        "position_exclusion": position,
    }


def _after_snapshot(
    attempt: dict[str, Any],
    hdf5: Path,
    runtime_domain: dict[str, Any],
    native: dict[str, Any],
    runparts: dict[int, dict[str, Any]],
    identity_join: dict[str, Any],
    independent_audit: dict[str, Any],
) -> dict[str, Any]:
    runparts_counts = _aggregate_runparts(list(runparts.values()))
    partout = {key: value for key, value in native.items() if key != "rows"}
    position = _position_counts(runparts=runparts_counts, partout=partout, identity=identity_join["summary"])
    return {
        "source": "fresh bounded H1 canary",
        "attempt_id": attempt.get("attempt_id"),
        "attempt_directory": _rel(Path(attempt["attempt_directory"])),
        "hdf5": _rel(hdf5),
        "hdf5_sha256": _sha256(hdf5),
        "runtime_domain": runtime_domain,
        "runparts": {
            "path": _rel(Path(attempt["attempt_directory"]) / "RunPARTs.csv"),
            "sha256": _sha256(Path(attempt["attempt_directory"]) / "RunPARTs.csv"),
            "reason_counts": runparts_counts,
            "events": list(runparts.values()),
        },
        "partout": {
            **partout,
            "identity_row_count": len(native.get("rows", [])),
            "path": _rel(Path(attempt["attempt_directory"]) / "data" / "PartOut_000.obi4"),
            "sha256": _sha256(Path(attempt["attempt_directory"]) / "data" / "PartOut_000.obi4"),
        },
        "identity_join": identity_join,
        "hdf5_independent_audit": independent_audit,
        "position_exclusion": position,
    }


def _write_report(report: dict[str, Any], path: Path = H1_REPORT) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default) + "\n")
    return path


def run_h1(physical_gpu: int = H1_GPU_DEFAULT) -> dict[str, Any]:
    """Run and audit one H1 canary without touching shared campaign state."""

    preflight = gpu_preflight(physical_gpu)
    before = _baseline_snapshot()
    materialize_definition()
    prepared = generate_case()
    prepared["recipe_contract"] = recipe_contract()
    attempt, launch = run_solver(prepared, physical_gpu)
    report: dict[str, Any] = {
        "schema": "l2r.f1r.h1.canary.v1",
        "stage": "F1R-H1",
        "created_at_utc": _utc_now(),
        "status": "failed" if attempt.get("status") != "completed" else "complete_with_findings",
        "decision": "solver attempt failed; H1 evidence incomplete" if attempt.get("status") != "completed" else None,
        "new_gpu_jobs": 1,
        "qualification_claim": "none",
        "receipt_emitted": False,
        "shared_resume_state_updated": False,
        "preflight": preflight,
        "gpu_isolation": launch,
        "recipe_contract": prepared["recipe_contract"],
        "xml_hashes": {
            "baseline_source_definition_sha256": _sha256(f1r.F1_DEFINITION),
            "baseline_generated_xml_sha256": _sha256(f1r.F1_GENERATED_XML),
            "h1_source_definition_sha256": prepared["definition_sha256"],
            "h1_generated_xml_sha256": prepared["generated_xml_sha256"],
        },
        "attempt": attempt,
        "before": before,
    }
    if attempt.get("status") != "completed":
        report["decision"] = "solver attempt failed; H1 evidence incomplete; no qualification claim"
        _write_report(report)
        return report

    attempt_dir = Path(attempt["attempt_directory"])
    csv_paths = partvtk_csv(attempt_dir / "data", H1_CSV_ROOT, "-all,+fluid")
    record = {
        "id": CASE_ID,
        "family": "F1",
        "mechanism": "resolved-obstacle-collapse-split-return",
        "shifting": 0,
    }
    convert_streaming(record, csv_paths, H1_HDF5)
    config = {
        "case_id": CASE_ID,
        "family": "F1",
        "recipe_id": "L2_F1_C1_obstacle_dbc_native_v1_dp0p0075",
        "physical_case_id": "physical_L2_F1_obstacle_center_nominal_v1",
        "lineage_group_id": "lineage_L2_F1_obstacle_center_nominal_v1",
        "paired_background_id": "paired_L2_F1_obstacle_v1",
        "view_id": "world_fluid_particle_v1",
        "control_semantics": "none; gravity and initial release are fixed inputs",
    }
    semantic_audit = c1.add_semantics(H1_HDF5, config, attempt)
    runtime_domain = prepared["resolved_runtime_domain"]
    independent_audit = inspect_hdf5(
        H1_HDF5,
        full_scan=True,
        wall_spec=f1r.F1_WALL_SPEC,
        runtime_domain=runtime_domain,
    )
    native = f1r.native_partout_evidence(attempt_dir)
    runparts = f1r._runparts_rows(attempt_dir / "RunPARTs.csv")
    identity_join = f1r._missing_identity_join(
        H1_HDF5,
        native.get("rows", []),
        runparts,
        runtime_domain,
    )
    after = _after_snapshot(
        attempt,
        H1_HDF5,
        runtime_domain,
        native,
        runparts,
        identity_join,
        independent_audit,
    )
    after["semantic_audit"] = semantic_audit
    comparison = compare_position_exclusions(before, after)
    removed = comparison["position_exclusion_removed"]
    report.update(
        {
            "decision": (
                "H1 removed bounded native position exclusions; structural canary only, no qualification"
                if removed
                else "H1 did not remove every bounded position-exclusion signal; retain H1 finding, no qualification"
            ),
            "after": after,
            "position_exclusion_comparison": comparison,
            "acceptance": {
                "solver_completed": attempt.get("status") == "completed",
                "generated_zmax_is_1p35_m": abs(float(runtime_domain["zmax"]) - H1_ZMAX) <= 1e-8,
                "same_non_domain_recipe": prepared["recipe_contract"]["same_non_domain_recipe"],
                "runparts_present": bool(runparts),
                "partout_decoded": native.get("status") == "available",
                "hdf5_identity_join_present": "summary" in identity_join,
                "position_exclusion_removed": removed,
                "no_qualification_receipt": True,
                "shared_resume_state_untouched": True,
            },
        }
    )
    _write_report(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gpu", type=int, default=H1_GPU_DEFAULT, help="physical GPU index for one H1 job")
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="check the selected GPU and print the isolation contract without running GenCase/solver",
    )
    args = parser.parse_args()
    try:
        preflight = gpu_preflight(args.gpu)
    except Exception as error:
        print(json.dumps({"status": "blocked_preflight", "error": repr(error)}, ensure_ascii=False, indent=2))
        return 2
    if args.preflight_only:
        print(json.dumps({"status": "preflight_pass", "preflight": preflight}, ensure_ascii=False, indent=2))
        return 0
    try:
        report = run_h1(args.gpu)
    except Exception as error:
        failure = {
            "schema": "l2r.f1r.h1.canary.v1",
            "stage": "F1R-H1",
            "created_at_utc": _utc_now(),
            "status": "failed",
            "decision": f"H1 orchestration failed before complete evidence: {error!r}",
            "new_gpu_jobs": 0,
            "qualification_claim": "none",
            "receipt_emitted": False,
            "shared_resume_state_updated": False,
            "preflight": preflight,
        }
        _write_report(failure)
        print(json.dumps(failure, ensure_ascii=False, indent=2))
        return 2
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "report": _rel(H1_REPORT),
                "gpu": report["gpu_isolation"],
                "position_exclusion_comparison": report.get("position_exclusion_comparison"),
            },
            ensure_ascii=False,
            indent=2,
            default=_json_default,
        )
    )
    return 0 if report["status"] == "complete_with_findings" else 2


if __name__ == "__main__":
    raise SystemExit(main())
