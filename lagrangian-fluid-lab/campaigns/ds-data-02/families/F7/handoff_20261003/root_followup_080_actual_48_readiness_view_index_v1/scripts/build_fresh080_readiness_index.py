#!/usr/bin/env python3
"""Build the F7 fresh080 native/typed/XMF/render readiness index.

This is a bounded metadata reader.  It reads JSON receipts/reports/manifests and
the XML-independent paths recorded by those files.  It never opens BI4, H5,
CSV, DAT, image, or other scientific payloads, and it never starts a job.

The output is deliberately a snapshot: an unfinished stage has no completed
output metadata digest.  Re-running this script after Root advances the live
renderer refreshes the snapshot without changing any consumed source package.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable


PACKAGE_ID = "root_followup_080_actual_48_readiness_view_index_v1"
FRESH079_ID = "root_followup_079_actual_xmf_render_schema_closure_v1"
MOTHER_ID = "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_BASE_V1"
CASE_PREFIX = "F7_OBSTACLE_QUINTIC_B08_A"

P5_CASES = {
    f"{CASE_PREFIX}{x}P5"
    for x in ("030", "031", "032", "033", "034", "035", "036", "037", "038", "039",
              "040", "041", "042", "043", "044", "045", "046", "047", "048", "049",
              "050", "054", "059", "064")
}
FIRST24_CASES = {
    f"{CASE_PREFIX}{x}"
    for x in ("031", "032", "033", "034", "036", "037", "038", "039", "041", "042",
              "043", "044", "046", "047", "048", "049")
}
FIRST8_CASES = {f"{CASE_PREFIX}{x}" for x in ("035", "040", "050", "055", "060")}
ENDPOINT_CASES = {f"{CASE_PREFIX}{x}" for x in ("030", "065")}

FORBIDDEN_SUFFIXES = {".bi4", ".h5", ".csv", ".dat", ".png", ".jpg", ".jpeg", ".gif", ".mp4"}
SCIENTIFIC_METADATA_KEY_TOKENS = (
    "bi4", "h5", "csv", "motion_file", "trajectory", "output_hdf5", "scientific_payload",
)


def as_path(value: Any) -> Path | None:
    if isinstance(value, str) and value:
        return Path(value)
    return None


def load_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file() or path.suffix.lower() != ".json":
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def metadata_sha256(path: Path | None) -> str | None:
    """Hash only bounded metadata/source files, never scientific payloads."""
    if path is None or not path.is_file() or path.suffix.lower() in FORBIDDEN_SUFFIXES:
        return None
    try:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
    except OSError:
        return None


def scalar(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return None


def compact_mapping(value: Any, *, max_items: int = 24) -> Any:
    """Keep bounded metadata counts and avoid copying scientific arrays."""
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:max_items]:
            lowered_key = str(key).lower()
            if any(token in lowered_key for token in SCIENTIFIC_METADATA_KEY_TOKENS):
                continue
            if isinstance(item, str) and Path(item).suffix.lower() in FORBIDDEN_SUFFIXES:
                continue
            if isinstance(item, (dict, list)):
                if isinstance(item, list):
                    result[str(key)] = {"kind": "list", "length": len(item)}
                else:
                    result[str(key)] = compact_mapping(item, max_items=max_items)
            else:
                result[str(key)] = scalar(item)
        if len(value) > max_items:
            result["__truncated_keys__"] = len(value) - max_items
        return result
    if isinstance(value, list):
        return {"kind": "list", "length": len(value)}
    return scalar(value)


def list_summary(value: Any) -> dict[str, Any] | None:
    """Summarize a bounded metadata time vector without copying it."""
    if not isinstance(value, list):
        return None
    result: dict[str, Any] = {"count": len(value)}
    if value:
        result["first"] = scalar(value[0])
        result["last"] = scalar(value[-1])
    return result


def dimension(value: Any) -> Any:
    if isinstance(value, int):
        return value
    if isinstance(value, dict):
        for key in ("dimension", "solver_dimension", "value"):
            if isinstance(value.get(key), int):
                return value[key]
    return None


def pick(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def receipt_request_path(receipt: dict[str, Any], explicit: Path | None = None) -> Path | None:
    if explicit is not None:
        return explicit
    request = receipt.get("request")
    if not isinstance(request, dict):
        return None
    for key in ("actual_request", "request_path", "root_reviewed_source_request", "binding"):
        candidate = as_path(request.get(key))
        if candidate is not None and candidate.is_file() and candidate.suffix.lower() == ".json":
            return candidate
    for item in request.get("input_files", []) if isinstance(request.get("input_files"), list) else []:
        candidate = as_path(item)
        if candidate is None or not candidate.is_file() or candidate.suffix.lower() != ".json":
            continue
        lowered = candidate.name.lower()
        if "request" in lowered and "receipt" not in lowered:
            return candidate
    return None


def receipt_summary(path: Path | None, *, explicit_request: Path | None = None) -> dict[str, Any]:
    if path is None:
        return {
            "path": None,
            "exists": False,
            "metadata_sha256": None,
            "schema": None,
            "status": "not_registered",
            "returncode": None,
            "completed_zero": False,
            "request_sha256": None,
            "request_path": None,
            "request_file_sha256": None,
            "started_at_utc": None,
            "finished_at_utc": None,
            "elapsed_seconds": None,
            "request_status": None,
            "expected_frames": None,
            "expected_particles": None,
            "expected_counts": None,
            "physical_window_s": None,
            "physical_condition_sha256": None,
            "canonical_physical_binding_sha256": None,
            "source_plan_condition_sha256": None,
        }

    data = load_json(path)
    if data is None:
        return {
            "path": str(path),
            "exists": path.is_file(),
            "metadata_sha256": metadata_sha256(path),
            "schema": None,
            "status": "invalid_metadata",
            "returncode": None,
            "completed_zero": False,
            "request_sha256": None,
            "request_path": None,
            "request_file_sha256": None,
        }

    request = data.get("request") if isinstance(data.get("request"), dict) else {}
    request_path = receipt_request_path(data, explicit_request)
    status = data.get("status")
    returncode = data.get("returncode")
    completed = status == "completed" and returncode == 0
    window = pick(request, "physical_window_s", "event_window_s", "full_event_window_s")
    return {
        "path": str(path),
        "exists": True,
        "metadata_sha256": metadata_sha256(path),
        "schema": data.get("schema"),
        "status": status,
        "returncode": returncode,
        "completed_zero": completed,
        "request_sha256": data.get("request_sha256"),
        "request_path": str(request_path) if request_path else None,
        "request_file_sha256": metadata_sha256(request_path),
        "started_at_utc": data.get("started_at_utc"),
        "finished_at_utc": data.get("finished_at_utc"),
        "elapsed_seconds": data.get("elapsed_seconds"),
        "request_status": request.get("status"),
        "expected_frames": pick(request, "expected_frames", "expected_native_frames"),
        "expected_particles": pick(request, "expected_particles", "expected_native_particles"),
        "expected_counts": compact_mapping(request.get("expected_counts")),
        "physical_window_s": compact_mapping(window),
        "physical_condition_sha256": pick(request, "physical_condition_sha256", "producer_physical_condition_sha256"),
        "canonical_physical_binding_sha256": request.get("canonical_physical_binding_sha256"),
        "source_plan_condition_sha256": pick(request, "source_plan_condition_sha256", "declared_source_plan_condition_sha256"),
    }


def report_summary(path: Path | None, *, case_id: str | None = None) -> dict[str, Any]:
    if path is None:
        return {"path": None, "exists": False, "metadata_sha256": None}
    data = load_json(path)
    if data is None:
        return {"path": str(path), "exists": path.is_file(), "metadata_sha256": metadata_sha256(path), "schema": None}
    case_entry: dict[str, Any] | None = None
    cases = data.get("cases")
    if case_id and isinstance(cases, list):
        for item in cases:
            if isinstance(item, dict) and item.get("case_id") == case_id:
                case_entry = item
                break
    counts = pick(data, "actual_counts", "generated_xml_particle_counts", "counts")
    frame_value = pick(data, "frames", "expected_frames", "source_frames")
    source_frame_value = data.get("source_frames")
    particle_value = pick(data, "particles", "actual_total_particles", "total_particles", "native_particles")
    times = pick(data, "actual_time_s", "time_s", "times")
    if isinstance(times, dict):
        times = times.get("values")
    output_attested = bool(data.get("output_sha256"))
    return {
        "path": str(path),
        "exists": True,
        "metadata_sha256": metadata_sha256(path),
        "schema": data.get("schema"),
        "case_id": data.get("case_id"),
        "frame_count": frame_value if isinstance(frame_value, (int, float)) else None,
        "source_frame_count": source_frame_value if isinstance(source_frame_value, (int, float)) else None,
        "particle_count": particle_value if isinstance(particle_value, (int, float)) else None,
        "counts": compact_mapping(counts),
        "field_names": list(data.get("fields", {}).keys()) if isinstance(data.get("fields"), dict) else None,
        "solver_dimension": dimension(data.get("solver_dimension")),
        "physical_window_s": compact_mapping(pick(data, "physical_window_s", "event_window_s", "full_event_window_s")),
        "save_interval_s": data.get("save_interval_s"),
        "actual_time_s": list_summary(times),
        "all_cases_passed": data.get("all_cases_passed"),
        "case_entry": compact_mapping(case_entry),
        "producer_attested_scientific_output_hash_present": output_attested,
        "scientific_payload_hash": None,
        "claim_boundary": data.get("claim_boundary"),
    }


def find_one(directory: Path, *needles: str, exclude: Iterable[str] = ()) -> Path | None:
    if not directory.is_dir():
        return None
    excluded = {x.lower() for x in exclude}
    candidates = [
        p for p in directory.iterdir()
        if p.is_dir() and all(n.lower() in p.name.lower() for n in needles)
        and not any(e in p.name.lower() for e in excluded)
    ]
    if not candidates:
        return None
    # Explicitly prefer the largest numeric attempt suffix when several
    # historical records coexist, while retaining deterministic ordering.
    def rank(path: Path) -> tuple[int, str]:
        nums = [int(x) for x in re.findall(r"(?:^|[-_])([0-9]{3,})$", path.name)]
        return (nums[-1] if nums else -1, path.name)
    return sorted(candidates, key=rank)[-1]


def nested_json(directory: Path, filename: str) -> Path | None:
    if not directory.is_dir():
        return None
    matches = sorted(p for p in directory.rglob(filename) if p.is_file())
    return matches[0] if matches else None


def stage_record(
    name: str,
    stage_dir: Path | None,
    *,
    report: Path | None = None,
    manifest: Path | None = None,
    explicit_request: Path | None = None,
    case_id: str | None = None,
    case_entry_report: Path | None = None,
) -> dict[str, Any]:
    if stage_dir is None:
        return {
            "stage": name,
            "registered": False,
            "path": None,
            "receipt": receipt_summary(None),
            "report": report_summary(None),
            "manifest": report_summary(None),
            "completed_output_metadata_sha256": None,
            "scientific_output_sha256": None,
        }
    receipt_path = stage_dir / "execution-receipt.json"
    receipt = receipt_summary(receipt_path if receipt_path.is_file() else None, explicit_request=explicit_request)
    if report is None:
        report = nested_json(stage_dir, "prepared-input-report.json") if name == "gencase" else None
        if name == "initial_qa":
            report = nested_json(stage_dir, "native-initial-qa.json")
        if name == "typed":
            candidate = stage_dir / "conversion-report.json"
            report = candidate if candidate.is_file() else None
        if name == "render":
            report = nested_json(stage_dir, "paraview-full-animation-report.json")
    if manifest is None and name == "xmf":
        manifest = nested_json(stage_dir, "manifest.json")
    report_value = report_summary(report, case_id=case_id)
    if case_entry_report is not None:
        report_value = report_summary(case_entry_report, case_id=case_id)
    manifest_value = report_summary(manifest)
    finished = bool(receipt.get("completed_zero"))
    output_meta: str | None = None
    if finished:
        if name == "xmf" and manifest is not None:
            output_meta = metadata_sha256(manifest)
        elif report is not None:
            output_meta = metadata_sha256(report)
    return {
        "stage": name,
        "registered": True,
        "path": str(stage_dir),
        "receipt": receipt,
        "report": report_value,
        "manifest": manifest_value,
        "completed_output_metadata_sha256": output_meta,
        # The source agent intentionally never reads or hashes BI4/H5/CSV/DAT.
        "scientific_output_sha256": None,
    }


def group_for(case_id: str) -> str:
    if case_id == MOTHER_ID:
        return "historical_mother062"
    if case_id in P5_CASES:
        return "fresh074_next24_p5"
    if case_id in FIRST24_CASES:
        return "fresh070_first24_whole_degree"
    if case_id in FIRST8_CASES:
        return "fresh065_first8_internal"
    if case_id in ENDPOINT_CASES:
        return "fresh064_endpoints"
    return "unclassified"


def source_package(group: str) -> str | None:
    return {
        "historical_mother062": "root_followup_062_stage1_target_angle_endpoints_v1 (read-only mother provenance)",
        "fresh064_endpoints": "root_followup_064_stage1_target_angle_full601_native099_nvme_typed_v1",
        "fresh065_first8_internal": "root_followup_065_stage1_first8_target_angles_v1",
        "fresh070_first24_whole_degree": "root_followup_070_stage1_first24_target_angles_v1",
        "fresh074_next24_p5": "root_followup_074_stage1_next24_target_angles_v1",
    }.get(group)


def build_paths(case_id: str, data_root: Path) -> dict[str, Any]:
    group = group_for(case_id)
    if group == "historical_mother062":
        case_root = data_root / "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_COARSE"
        gencase = find_one(case_root, "actual-gencase-021")
        # The first restored-recipe native attempt (023) failed before the
        # successful restored-motion retry (025).  Select the completed retry
        # and keep the failed receipt in the case's historical alternates.
        native = find_one(case_root, "restored-motion-coarse-full601-native-025")
        typed = find_one(case_root, "typed-026")
        xmf = find_one(case_root, "dynamic-xdmf-005")
        render = find_one(case_root, "native-geometry-animation-028")
        qa = None
        gencase_report = (gencase / "prepared" / "prepared-input-report.json") if gencase else None
    elif group == "fresh064_endpoints":
        case_root = data_root / case_id
        gencase = find_one(case_root, "genuine-gencase-085")
        native = find_one(case_root, "full601-native-099")
        typed = find_one(case_root, "native-typed-nvme-064")
        xmf = find_one(case_root, "normal-dynamic-")
        render = find_one(case_root, "native023-render-")
        qa = data_root / "F7_TARGET_ANGLE_ENDPOINTS" / "root-stage1-f7-two-angles-actual-native-initial-qa-096"
        gencase_report = (gencase / "prepared" / "prepared-input-report.json") if gencase else None
    elif group == "fresh065_first8_internal":
        case_root = data_root / case_id
        first8 = data_root / "F7_STAGE1_FIRST8_TARGET_ANGLES"
        gencase = first8 / "root-stage1-f7-first8-genuine-gencase-065" / "gencase" / case_id
        if not gencase.is_dir():
            gencase = None
        native = find_one(case_root, "full601-native-156")
        typed = find_one(case_root, "native-typed-nvme-221")
        xmf = find_one(case_root, "canonical-typed221-xmf-")
        render = find_one(case_root, "native023-render-")
        qa = find_one(case_root, "native-initial-qa-126")
        gencase_report = (gencase / "prepared-input-report.json") if gencase else None
    elif group == "fresh070_first24_whole_degree":
        case_root = data_root / case_id
        gencase = find_one(case_root, "genuine-gencase-070")
        native = find_one(case_root, "full601-native-071")
        typed = find_one(case_root, "native-typed-nvme-072")
        xmf = find_one(case_root, "normal-dynamic-073")
        render = find_one(case_root, "actual-xmf327-full601-render-329")
        qa = data_root / "F7_STAGE1_FIRST24_TARGET_ANGLES" / "root-stage1-f7-first24-native-initial-qa-071"
        gencase_report = (gencase / "prepared" / "prepared-input-report.json") if gencase else None
    elif group == "fresh074_next24_p5":
        case_root = data_root / case_id
        gencase = find_one(case_root, "genuine-gencase-074")
        native = find_one(case_root, "native-qualification-075")
        typed = find_one(case_root, "typed-nvme-077")
        xmf = find_one(case_root, "normal-xmf-078")
        render = find_one(case_root, "actual-xmf078-full601-render-413")
        qa = data_root / "F7_STAGE1_NEXT24_TARGET_ANGLES" / "root-stage1-f7-next24-native-initial-qa-075"
        gencase_report = (gencase / "prepared" / "prepared-input-report.json") if gencase else None
    else:
        case_root = data_root / case_id
        gencase = native = typed = xmf = render = qa = None
        gencase_report = None

    return {
        "case_root": case_root,
        "gencase": gencase,
        "gencase_report": gencase_report,
        "native": native,
        "typed": typed,
        "xmf": xmf,
        "render": render,
        "qa": qa,
    }


def request_file_for_render(case_id: str, render: Path | None, integration_root: Path) -> Path | None:
    if "P5" in case_id:
        candidate = integration_root / "root_stage1_f7_actual24_XMF411_full601_root023_render_413" / f"{case_id}-render-request.json"
        if candidate.is_file():
            return candidate
    if case_id in FIRST24_CASES:
        candidate = integration_root / "root_stage1_f7_actual_xmf327_sixteen_full601_render_329" / f"{case_id}-render-request.json"
        if candidate.is_file():
            return candidate
    if case_id in FIRST8_CASES:
        candidate = integration_root / "root_followup_069_stage1_actual_native156_full601_typed_xmf_render_v1" / "requests" / "render" / f"{case_id}.full601-native023-render-request.json"
        if candidate.is_file():
            return candidate
    if case_id == f"{CASE_PREFIX}030":
        candidate = integration_root / "root_stage1_f1_f7_actual_full_native_geometry_pipeline_144" / f"{case_id}-render-request.json"
        if candidate.is_file():
            return candidate
    if case_id == f"{CASE_PREFIX}065":
        candidate = integration_root / "root_stage1_f7_a065_actual_complete_native_render_150" / f"{case_id}-render-request.json"
        if candidate.is_file():
            return candidate
    if render is not None:
        receipt = load_json(render / "execution-receipt.json")
        if receipt:
            request = receipt.get("request") if isinstance(receipt.get("request"), dict) else {}
            render_candidates: list[Path] = []
            for item in request.get("input_files", []) if isinstance(request.get("input_files"), list) else []:
                candidate = as_path(item)
                if candidate is None or not candidate.is_file() or candidate.suffix.lower() != ".json":
                    continue
                lowered = str(candidate).lower()
                if "render" in lowered and "request" in lowered:
                    render_candidates.append(candidate)
            if render_candidates:
                return sorted(render_candidates, key=str)[0]
            candidate = receipt_request_path(receipt)
            if candidate is not None:
                return candidate
    return None


def qa_case_report(qa_dir: Path | None, case_id: str) -> tuple[Path | None, dict[str, Any] | None]:
    if qa_dir is None or not qa_dir.is_dir():
        return None, None
    report = nested_json(qa_dir, "native-initial-qa.json")
    if report is None:
        return None, None
    data = load_json(report)
    if not data:
        return report, None
    cases = data.get("cases")
    if isinstance(cases, list):
        for item in cases:
            if isinstance(item, dict) and item.get("case_id") == case_id:
                return report, item
    return report, None


def build_case(case_id: str, data_root: Path, integration_root: Path) -> dict[str, Any]:
    group = group_for(case_id)
    paths = build_paths(case_id, data_root)
    qa_report, qa_entry = qa_case_report(paths["qa"], case_id)
    render_request = request_file_for_render(case_id, paths["render"], integration_root)
    stages = {
        "gencase": stage_record("gencase", paths["gencase"], report=paths["gencase_report"], case_id=case_id),
        "native_initial_qa": stage_record(
            "initial_qa", paths["qa"], report=qa_report, case_id=case_id,
            case_entry_report=qa_report,
        ),
        "native_full601": stage_record("native", paths["native"], case_id=case_id),
        "typed_full601": stage_record("typed", paths["typed"], case_id=case_id),
        "xmf_full601": stage_record("xmf", paths["xmf"], case_id=case_id),
        "render_full601": stage_record(
            "render", paths["render"], case_id=case_id, explicit_request=render_request,
        ),
    }
    result = {
        "case_id": case_id,
        "group": group,
        "source_package": source_package(group),
        "case_directory": str(paths["case_root"]),
        "stages": stages,
        "render_request": {
            "path": str(render_request) if render_request else None,
            "metadata_sha256": metadata_sha256(render_request),
        },
        "case_entry_observation": compact_mapping(qa_entry),
        "visual_review": "pending root inspection; no visual approval or credit from this index",
        "q_n": "not_granted",
        "precision_status": "not_accepted",
        "production_approval": "none",
        "independent_case_increment": 0,
    }
    if group == "fresh065_first8_internal":
        batch_receipt = data_root / "F7_STAGE1_FIRST8_TARGET_ANGLES" / "root-stage1-f7-first8-genuine-gencase-065" / "execution-receipt.json"
        if batch_receipt.is_file():
            # The per-case GenCase receipts are producer metadata without a
            # request_sha256.  Preserve the common batch request separately;
            # do not mislabel it as a per-case request hash.
            result["stages"]["gencase"]["batch_receipt"] = receipt_summary(batch_receipt)
    if group == "historical_mother062":
        # Preserve the failed 023 attempt as historical evidence while using
        # the completed 025 retry as the selected native readiness input.
        alternates = []
        for candidate in sorted(paths["case_root"].glob("*full601-native-*/execution-receipt.json")):
            if paths["native"] is not None and candidate.parent == paths["native"]:
                continue
            alternates.append(receipt_summary(candidate))
        result["historical_alternate_attempts"] = {"native_full601": alternates}
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--integration-root", type=Path, required=True)
    parser.add_argument("--fresh079-audit", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    audit = load_json(args.fresh079_audit)
    if not audit:
        raise SystemExit(f"cannot read bounded fresh079 audit: {args.fresh079_audit}")
    case_ids = list(audit.get("family_unique_physical_case_ids", []))
    if len(case_ids) != 48 or len(set(case_ids)) != 48:
        raise SystemExit(f"fresh079 family audit is not exactly 48 unique IDs: {len(case_ids)}")

    cases = [build_case(case_id, args.data_root, args.integration_root) for case_id in sorted(case_ids)]
    stage_names = ("gencase", "native_initial_qa", "native_full601", "typed_full601", "xmf_full601", "render_full601")
    stage_counts: dict[str, dict[str, int]] = {}
    for name in stage_names:
        counts = {"registered": 0, "completed_zero": 0, "running": 0, "failed_or_other": 0, "not_registered": 0}
        for case in cases:
            stage = case["stages"][name]
            rec = stage["receipt"]
            if not stage["registered"]:
                counts["not_registered"] += 1
            else:
                counts["registered"] += 1
                if rec.get("completed_zero"):
                    counts["completed_zero"] += 1
                elif rec.get("status") == "running":
                    counts["running"] += 1
                else:
                    counts["failed_or_other"] += 1
        stage_counts[name] = counts

    render_handoff = args.integration_root / "root_stage1_f7_actual24_XMF411_full601_root023_render_413"
    controller_handoff = args.integration_root / "root_stage1_f7_all24_render413_guarded_cap2_controller_414"
    render_requests = sorted(render_handoff.glob("F7_OBSTACLE_QUINTIC_B08_A*P5-render-request.json"))
    render_request_records = [
        {"case_id": p.name.removesuffix("-render-request.json"), "path": str(p), "metadata_sha256": metadata_sha256(p)}
        for p in render_requests
    ]

    source_audit_ref = {
        "path": str(args.fresh079_audit),
        "metadata_sha256": metadata_sha256(args.fresh079_audit),
        "family_unique_physical_case_count": audit.get("family_unique_physical_case_count"),
        "source_owner_row_count": audit.get("source_owner_row_count"),
        "source_package_counts": audit.get("source_package_counts"),
        "historical_mother": audit.get("mother_binding"),
        "prospective_candidate_excluded": audit.get("prospective_candidate_excluded_from_family48"),
    }

    index = {
        "schema": "ds02.f7.fresh080.actual-48-readiness-view-index.v1",
        "scope_id": PACKAGE_ID,
        "family_id": "F7",
        "generated_by": "gpt-5.6-luna/max metadata-only source worker",
        "source_only": True,
        "arrays_read": False,
        "scientific_payloads_read_or_hashed": False,
        "jobs_started": False,
        "shared_state_written": False,
        "claim_boundary": (
            "Readiness metadata only. This index records actual receipt status, bounded time/frame/count "
            "metadata, producer-attested JSON metadata digests, and renderer viewing paths. It does not grant "
            "visual acceptance, Q-N, precision, production approval, or independent case credit."
        ),
        "source_coverage": source_audit_ref,
        "family_counts": {
            "unique_physical_cases": 48,
            "source_rows": 47,
            "historical_mother_rows": 1,
            "excluded_prospective_A052P5": True,
            "source_duplicate_ids": audit.get("source_duplicate_ids", []),
        },
        "stage_counts": stage_counts,
        "render_controller": {
            "root413_request_handoff": str(render_handoff),
            "root413_controller_handoff": str(controller_handoff),
            "root413_request_count": len(render_request_records),
            "root413_request_files": render_request_records,
            "root414_controller_source": str(controller_handoff / "batch-render-controller.py"),
            "root414_controller_source_sha256": metadata_sha256(controller_handoff / "batch-render-controller.py"),
            "parent_observed_live_session": "96407 at task handoff; per-case receipts below are authoritative snapshot",
            "viewing_target": {
                "contact_pages_expected": 26,
                "key_frames_expected": [0, 120, 240, 360, 480, 600],
                "key_frame_source": "render report frames_dir; paths are indexed without opening image payloads",
            },
        },
        "cases": cases,
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.output_dir / "family48-readiness-index.json"
    out_path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    viewing = {
        "schema": "ds02.f7.fresh080.actual-render-view-index.v1",
        "scope_id": PACKAGE_ID,
        "source_index": str(out_path),
        "claim_boundary": "Viewing aid only; Root must inspect all listed contact sheets and six key frames and decide acceptance.",
        "contact_pages_expected": 26,
        "key_frames_expected": [0, 120, 240, 360, 480, 600],
        "cases": [],
    }
    for case in cases:
        render = case["stages"]["render_full601"]
        report = render.get("report", {})
        report_data = load_json(Path(report["path"])) if report.get("path") else None
        outputs = report_data.get("outputs", {}) if isinstance(report_data, dict) else {}
        contact = outputs.get("contact_sheets") if isinstance(outputs, dict) else None
        frames_dir = outputs.get("frames_dir") if isinstance(outputs, dict) else None
        key_frames = []
        if isinstance(frames_dir, str):
            for frame in (0, 120, 240, 360, 480, 600):
                path = Path(frames_dir) / f"frame_{frame:04d}.png"
                key_frames.append({"frame": frame, "path": str(path), "exists": path.is_file()})
        viewing["cases"].append({
            "case_id": case["case_id"],
            "render_status": render["receipt"].get("status"),
            "render_returncode": render["receipt"].get("returncode"),
            "render_request_sha256": render["receipt"].get("request_sha256"),
            "report_metadata_sha256": render.get("completed_output_metadata_sha256"),
            "contact_sheets": contact if isinstance(contact, list) else [],
            "contact_sheet_count": len(contact) if isinstance(contact, list) else 0,
            "key_frames": key_frames,
            "visual_review": "pending root inspection",
        })
    (args.output_dir / "render-view-index.json").write_text(json.dumps(viewing, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
