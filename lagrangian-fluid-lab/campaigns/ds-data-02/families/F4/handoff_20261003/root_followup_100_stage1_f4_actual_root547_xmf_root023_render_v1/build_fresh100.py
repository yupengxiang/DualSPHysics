#!/usr/bin/env python3
"""Build the F4 Root547 XMF to Root023 fresh100 handoff.

This builder is deliberately metadata-only.  It polls Root533 conversion
JSON, Root547 execution-receipt/manifest/case.xmf metadata, and immutable
fresh099 JSON evidence.  It never opens, copies, or hashes H5/BI4/VTK/CSV/DAT
payloads and never starts a conversion, export, or render.
"""

from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable


WORKTREE = Path("/home/jade/.codex/worktrees/ds-data-02-f4/DualSPHysics").resolve()
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics").resolve()
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02").resolve()
PACKAGE = Path(__file__).resolve().parent

FRESH099 = WORKTREE / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F4/"
    "handoff_20261003/root_followup_099_stage1_f4_actual_typed_xmf_render_v1"
)
ROOT547 = INTEGRATION / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_f4_actualtyped533_full1201_normal_N3_XMF_547"
)
ROOT230 = INTEGRATION / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_native_home_floor_eight_solver_dispatch_230"
)
ROOT134 = INTEGRATION / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_f3_first24_eight_solver_resource_policy_134"
)
ROOT023 = INTEGRATION / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_native_renderer_proxy_lifetime_diagnostic_023"
)
RESOURCE = INTEGRATION / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"
)

RUNTIME = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
STRICT = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py"
RENDERER = ROOT023 / "render.py"
ROOT230_ENTRY = ROOT230 / "launch.py"
ROOT230_HOME = ROOT230 / "root_native_home_floor_inventory_policy.py"
ROOT230_CONTRACT = ROOT230 / "source-policy-contract.json"
ROOT134_GPU = ROOT134 / "ds02_root_all_idle_gpu_policy_v2.py"
PV_PYTHON = Path("/home/jade/ParaView-6.1.1-MPI-Linux-Python3.12-x86_64/bin/pvpython")
ENV = Path("/usr/bin/env")
MESA_JSON = Path("/usr/share/glvnd/egl_vendor.d/50_mesa.json")

SCOPE = "root_followup_100_stage1_f4_actual_root547_xmf_root023_render_v1"
RAW_SUFFIXES = {".bi4", ".h5", ".hdf5", ".csv", ".dat", ".vtk", ".vtu", ".vtp"}
STATIC_SUFFIXES = {"", ".json", ".jsonl", ".xml", ".xmf", ".py", ".md", ".txt", ".log"}
RENDERER_SHA = "5e78f7b92ad7c6f1d15902e3ccacc9099affb04b1b992a42f540eb88241bde66"
STRICT_SHA = "81bdd60e5de4fec362807043ab632864405f1667a0658560fb9349025aab75ec"


def load_json(path: Path) -> dict[str, Any]:
    path = Path(path).resolve()
    if path.suffix.lower() in RAW_SUFFIXES:
        raise RuntimeError(f"scientific payload read refused: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def sha_static(path: Path, known: dict[str, str] | None = None) -> str:
    path = Path(path).resolve()
    if known and str(path) in known:
        return str(known[str(path)])
    if path.suffix.lower() in RAW_SUFFIXES:
        raise RuntimeError(f"scientific payload hash refused: {path}")
    if path.suffix.lower() not in STATIC_SUFFIXES:
        raise RuntimeError(f"non-static input hash refused: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ref(path: Path | None, known: dict[str, str] | None = None) -> dict[str, str] | None:
    if path is None:
        return None
    path = Path(path).resolve()
    if not path.is_file():
        return None
    return {"path": str(path), "sha256": sha_static(path, known)}


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def as_path(value: Any) -> Path | None:
    if isinstance(value, str) and value:
        return Path(value).resolve()
    if isinstance(value, dict) and isinstance(value.get("path"), str):
        return Path(value["path"]).resolve()
    return None


def known_hashes_from_fresh099() -> dict[str, str]:
    known: dict[str, str] = {}
    for path in sorted((FRESH099 / "requests").glob("*-full1201-render-fresh099-disabled.request.json")):
        request = load_json(path)
        for raw_path, digest in (request.get("input_sha256") or {}).items():
            if isinstance(raw_path, str) and isinstance(digest, str):
                known[str(Path(raw_path).resolve())] = digest
    return known


def fresh099_rows() -> tuple[dict[str, dict[str, Any]], Path]:
    evidence_path = FRESH099 / "evidence/root533-conversion-report-snapshot.json"
    evidence = load_json(evidence_path)
    rows: dict[str, dict[str, Any]] = {}
    for row in evidence.get("cases", []):
        if not isinstance(row, dict) or not row.get("case_id"):
            raise RuntimeError("invalid fresh099 conversion row")
        rows[str(row["case_id"])] = row
    if len(rows) != 24:
        raise RuntimeError(f"fresh099 conversion rows expected 24, found {len(rows)}")
    return rows, evidence_path.resolve()


def fresh099_binding(case_id: str) -> tuple[Path, dict[str, Any], Path, dict[str, Any]]:
    binding_path = FRESH099 / "bindings" / f"{case_id}-render-binding.json"
    request_path = FRESH099 / "requests" / f"{case_id}-full1201-render-fresh099-disabled.request.json"
    binding = load_json(binding_path)
    request = load_json(request_path)
    return binding_path.resolve(), binding, request_path.resolve(), request


def json_path_from_row(row: dict[str, Any], key: str) -> Path | None:
    value = row.get(key)
    return as_path(value)


def strip_payload_paths(value: Any) -> Any:
    """Keep physical metadata while removing payload paths and H5 digests."""
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, child in value.items():
            low = str(key).lower()
            if any(token in low for token in ("h5", "hdf", "trajectory", "xdmf")):
                continue
            if low.endswith("payload_hash") or low.endswith("payload_sha256"):
                continue
            if isinstance(child, str) and Path(child).suffix.lower() in RAW_SUFFIXES:
                continue
            cleaned[str(key)] = strip_payload_paths(child)
        return cleaned
    if isinstance(value, list):
        return [strip_payload_paths(child) for child in value]
    return value


def lifecycle_summary(report: dict[str, Any]) -> dict[str, Any]:
    identity = report.get("typed_identity") or {}
    ledger = identity.get("initial_exclusion_ledger") or {}
    lifecycle = report.get("lifecycle") or {}

    def event_count(value: Any) -> int:
        return len(value) if isinstance(value, (list, dict)) else 0

    fluid_blocks = []
    for block in identity.get("blocks", []):
        if isinstance(block, dict) and block.get("tag") == "fluid":
            fluid_blocks.append({
                key: block.get(key)
                for key in ("begin", "count", "mk", "mkfluid", "tag", "type")
                if key in block
            })
    return {
        "contract": lifecycle.get("contract"),
        "identity_key": identity.get("key"),
        "zone_source": identity.get("zone_source"),
        "observed_mks": identity.get("observed_mks"),
        "observed_types": identity.get("observed_types"),
        "mass_semantics": identity.get("mass_semantics"),
        "fluid_blocks": fluid_blocks,
        "initial_exclusion_ledger": {
            "count": ledger.get("count"),
            "mass_kg": ledger.get("mass_kg"),
            "mk_counts": ledger.get("mk_counts"),
            "type_counts": ledger.get("type_counts"),
            "semantics": ledger.get("semantics"),
            "ids_sha256_omitted": True,
        },
        "first_missing_frame_by_mk": lifecycle.get("first_missing_frame_by_mk", {}),
        "first_missing_frame_by_type": lifecycle.get("first_missing_frame_by_type", {}),
        "transient_missing_frame_count": lifecycle.get("transient_missing_frame_count"),
        "transient_missing_by_mk_event_count": event_count(lifecycle.get("transient_missing_by_mk_frame_events")),
        "transient_missing_by_type_event_count": event_count(lifecycle.get("transient_missing_by_type_frame_events")),
        "introduced_id_count": event_count(lifecycle.get("introduced_ids")),
        "missing_semantics": lifecycle.get("missing_semantics"),
        "open_birth_adaptive_multi_piece": lifecycle.get("open_birth_adaptive_multi_piece"),
        "padding_or_reclassification": "forbidden; observed lifecycle retained exactly",
    }


def partvtk_summary(report: dict[str, Any]) -> dict[str, Any]:
    validation = report.get("partvtk_validation") or {}
    frames = validation.get("frames") or []
    samples: list[dict[str, Any]] = []
    if isinstance(frames, list):
        chosen = frames if len(frames) <= 3 else [frames[0], frames[len(frames) // 2], frames[-1]]
        for row in chosen:
            if not isinstance(row, dict):
                continue
            samples.append({
                "frame": row.get("frame"),
                "rows": row.get("rows"),
                "expected_rows": row.get("expected_rows"),
                "passed": row.get("passed"),
                "partvtk_time": row.get("partvtk_time"),
                "type_counts": row.get("type_counts"),
                "identity_type_mk_exact": row.get("identity_type_mk_exact"),
            })
    return {
        "all_passed": validation.get("all_passed"),
        "sample_count": len(samples),
        "samples": samples,
        "csv_paths_omitted": True,
    }


def compact_report(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if report is None:
        return None
    solver = report.get("solver_dimension") or {}
    time = report.get("time_evidence") or {}
    units = report.get("units") or {}
    unsupported = report.get("unsupported_contract") or {}
    return {
        "schema": report.get("schema"),
        "conversion_status": report.get("conversion_status"),
        "frames": report.get("frames"),
        "particles": report.get("particles"),
        "solver_dimension": {
            "solver_dimension": solver.get("solver_dimension"),
            "run_out_dimensions": solver.get("run_out_dimensions"),
            "xml_data2d": solver.get("xml_data2d"),
        },
        "time_evidence": {
            "first_s": time.get("first_s"),
            "last_s": time.get("last_s"),
            "strictly_increasing": time.get("strictly_increasing"),
            "source": time.get("source"),
        },
        "units": {
            key: units.get(key)
            for key in ("density", "mass", "position", "pressure", "time", "velocity")
            if key in units
        },
        "typed_identity_lifecycle": lifecycle_summary(report),
        "partvtk_validation": partvtk_summary(report),
        "conversion_claim": report.get("conversion_claim"),
        "q_i_status": report.get("q_i_status"),
        "q_n_status": report.get("q_n_status"),
        "production_eligibility": report.get("production_eligibility"),
        "unsupported_contract": {
            "dynamic_metadata": unsupported.get("dynamic_metadata"),
            "open_birth_adaptive": unsupported.get("open_birth_adaptive"),
        },
        "raw_payload_rehashed_by_source": False,
        "report_h5_output_digest_copied_by_source": False,
    }


def root533_typed_state(
    case_id: str,
    root547_binding: dict[str, Any],
    fresh_row: dict[str, Any],
    known: dict[str, str],
) -> dict[str, Any]:
    report_path = as_path(root547_binding.get("conversion_report"))
    receipt_path = as_path(root547_binding.get("typed_receipt"))
    if report_path is None:
        report_path = json_path_from_row(fresh_row, "report")
    if receipt_path is None:
        receipt_path = json_path_from_row(fresh_row, "receipt")
    report = load_json(report_path) if report_path and report_path.is_file() else None
    receipt = load_json(receipt_path) if receipt_path and receipt_path.is_file() else None
    typed_attempt = (
        (root547_binding.get("typed_binding") or {}).get("attempt_id")
        or root547_binding.get("typed_attempt_id")
        or fresh_row.get("attempt_id")
    )
    status = receipt.get("status") if receipt else "WAIT"
    returncode = receipt.get("returncode") if receipt else None
    return {
        "case_id": case_id,
        "attempt_id": typed_attempt,
        "request": fresh_row.get("request"),
        "receipt": ref(receipt_path, known),
        "report": ref(report_path, known),
        "receipt_status": status,
        "receipt_returncode": returncode,
        "typed_status": (
            "completed/0_with_report"
            if status == "completed" and returncode == 0 and report is not None
            else "completed/0_missing_report"
            if status == "completed" and returncode == 0
            else status
        ),
        "report_summary": compact_report(report),
        "physical_condition_sha256": root547_binding.get("physical_condition_sha256"),
        "source_owner_physical_condition_sha256": root547_binding.get("source_owner_physical_condition_sha256"),
        "source_plan_condition_sha256": root547_binding.get("source_plan_condition_sha256"),
        "actual_converter_scope": strip_payload_paths(root547_binding.get("actual_converter_scope") or {}),
        "fresh099_source_row": {
            "typed_status_at_fresh099_build": fresh_row.get("typed_status"),
            "snapshot_report": fresh_row.get("report"),
            "snapshot_receipt": fresh_row.get("receipt"),
        },
        "future_typed_product_hashes": {
            "trajectory_h5": None,
            "conversion_report": None,
            "execution_receipt": None,
        },
        "source_did_not_read_or_hash_science_payload": True,
    }


def parse_xmf_metadata(path: Path) -> dict[str, Any]:
    frame_count = 0
    first_time: float | None = None
    last_time: float | None = None
    first_topology: int | None = None
    last_topology: int | None = None
    geometry_types: set[str] = set()
    attributes: dict[str, str | None] = {}
    hdf_reference_count = 0
    for event, element in ET.iterparse(path, events=("start", "end")):
        if event != "start":
            element.clear()
            continue
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "Grid" and element.attrib.get("GridType") == "Uniform":
            frame_count += 1
        elif tag == "Time" and "Value" in element.attrib:
            try:
                value = float(element.attrib["Value"])
            except (TypeError, ValueError):
                value = None
            if value is not None:
                if first_time is None:
                    first_time = value
                last_time = value
        elif tag == "Topology" and "NumberOfElements" in element.attrib:
            try:
                count = int(element.attrib["NumberOfElements"])
            except (TypeError, ValueError):
                count = None
            if count is not None:
                if first_topology is None:
                    first_topology = count
                last_topology = count
        elif tag == "Geometry" and element.attrib.get("GeometryType"):
            geometry_types.add(str(element.attrib["GeometryType"]))
        elif tag == "Attribute" and "Name" in element.attrib:
            attributes[str(element.attrib["Name"])] = element.attrib.get("AttributeType")
        elif tag == "DataItem" and str(element.attrib.get("Format", "")).upper() == "HDF":
            hdf_reference_count += 1
    return {
        "frame_count": frame_count,
        "first_time_s": first_time,
        "last_time_s": last_time,
        "first_topology_elements": first_topology,
        "last_topology_elements": last_topology,
        "geometry_types": sorted(geometry_types),
        "attribute_names": sorted(attributes),
        "attribute_types": {key: attributes[key] for key in sorted(attributes)},
        "velocity_is_n3_vector": attributes.get("velocity") == "Vector",
        "hdf_reference_count": hdf_reference_count,
        "hdf_references_omitted": True,
    }


def root547_state(
    case_id: str,
    fresh099_request_path: Path,
    fresh099_request: dict[str, Any],
    known: dict[str, str],
) -> dict[str, Any]:
    request_path = ROOT547 / f"{case_id}-xmf-request.json"
    binding_path = ROOT547 / "bindings" / f"{case_id}-actual-xmf-binding.json"
    if not request_path.is_file() or not binding_path.is_file():
        return {
            "case_id": case_id,
            "root547_registered": False,
            "status": "WAIT_missing_root547_registration",
            "root547_request": ref(request_path, known),
            "root547_binding": ref(binding_path, known),
            "root547_attempt_id": None,
            "output_root": None,
            "receipt": None,
            "manifest": None,
            "case_xmf": None,
            "receipt_summary": None,
            "manifest_summary": None,
            "xmf_xml_summary": None,
            "actual_hdf5_hashes_omitted": True,
        }
    request = load_json(request_path)
    binding = load_json(binding_path)
    outputs = request.get("expected_outputs") or {}
    manifest_path = as_path(outputs.get("manifest"))
    xmf_path = as_path(outputs.get("xdmf"))
    output_root = manifest_path.parent if manifest_path else xmf_path.parent if xmf_path else None
    receipt_path = output_root / "execution-receipt.json" if output_root else None
    manifest = load_json(manifest_path) if manifest_path and manifest_path.is_file() else None
    receipt = load_json(receipt_path) if receipt_path and receipt_path.is_file() else None
    xmf_summary = parse_xmf_metadata(xmf_path) if xmf_path and xmf_path.is_file() else None
    status = (
        "completed/0_with_manifest_xmf"
        if receipt and receipt.get("status") == "completed" and receipt.get("returncode") == 0 and manifest and xmf_summary
        else "completed/0_missing_xmf_metadata"
        if receipt and receipt.get("status") == "completed" and receipt.get("returncode") == 0
        else str(receipt.get("status"))
        if receipt
        else "WAIT"
    )
    times = manifest.get("actual_time_s") if manifest else None
    if isinstance(times, list):
        time_first = times[0] if times else None
        time_last = times[-1] if times else None
        time_count = len(times)
    else:
        time_first = None
        time_last = None
        time_count = None
    fields = manifest.get("fields") if manifest else []
    if isinstance(fields, dict):
        field_names = list(fields)
        field_shapes = {
            str(name): {
                "shape": item.get("shape"),
                "dtype": item.get("dtype"),
            }
            for name, item in fields.items()
            if isinstance(item, dict)
        }
    elif isinstance(fields, list):
        field_names = [
            item.get("name") if isinstance(item, dict) else item
            for item in fields
        ]
        field_shapes = {}
    else:
        field_names = []
        field_shapes = {}
    manifest_summary = {
        "schema": manifest.get("schema") if manifest else None,
        "case_id": manifest.get("case_id") if manifest else case_id,
        "fresh_id": manifest.get("fresh_id") if manifest else None,
        "frames": manifest.get("frames", manifest.get("frame_count")) if manifest else None,
        "expected_frames": manifest.get("expected_frames") if manifest else None,
        "particles": manifest.get("particles", manifest.get("particle_count")) if manifest else None,
        "expected_particles": manifest.get("expected_particles") if manifest else None,
        "fluid_particles_expected": manifest.get("fluid_particles_expected") if manifest else None,
        "expected_dimension": manifest.get("expected_dimension") if manifest else None,
        "time_count": time_count,
        "time_first_s": time_first,
        "time_last_s": time_last,
        "coordinate_frame": manifest.get("coordinate_frame") if manifest else None,
        "fields": sorted(str(name) for name in field_names if name is not None),
        "field_shapes": field_shapes,
        "physical_condition_sha256": manifest.get("physical_condition_sha256") if manifest else None,
        "source_owner_physical_condition_sha256": manifest.get("source_owner_physical_condition_sha256") if manifest else None,
        "source_plan_condition_sha256": manifest.get("source_plan_condition_sha256") if manifest else None,
        "future_output_hashes": {
            "case_xmf": None,
            "manifest": None,
            "trajectory_h5": None,
            "typed_receipt": None,
            "xmf_receipt": None,
        },
        "h5_hashes_omitted_by_source": True,
    }
    return {
        "case_id": case_id,
        "root547_registered": True,
        "status": status,
        "root547_request": ref(request_path, known),
        "root547_binding": ref(binding_path, known),
        "root547_attempt_id": request.get("attempt_id"),
        "root547_request_status": request.get("status"),
        "output_root": str(output_root) if output_root else None,
        "receipt": ref(receipt_path, known),
        "manifest": ref(manifest_path, known),
        "case_xmf": ref(xmf_path, known),
        "receipt_summary": {
            "schema": receipt.get("schema") if receipt else None,
            "attempt_id": (
                (receipt.get("attempt_id") if receipt else None)
                or request.get("attempt_id")
            ),
            "status": receipt.get("status") if receipt else "WAIT",
            "returncode": receipt.get("returncode") if receipt else None,
            "output_root": receipt.get("output_root") if receipt else str(output_root) if output_root else None,
        },
        "manifest_summary": manifest_summary,
        "xmf_xml_summary": xmf_summary,
        "binding_scope": strip_payload_paths(binding.get("actual_converter_scope") or {}),
        "physical_binding": strip_payload_paths(binding.get("physical_binding") or {}),
        "typed_lifecycle_identity": {
            "identity_and_state": manifest.get("identity_and_state") if manifest else None,
            "type_aliases": strip_payload_paths(manifest.get("type_aliases") or {}) if manifest else {},
            "vector_contract": strip_payload_paths(manifest.get("vector_contract") or {}) if manifest else {},
        },
        "actual_hdf5_hashes_omitted": True,
        "source_did_not_read_or_hash_h5": True,
        "fresh099_request_was_not_reused": True,
        "_request": request,
        "_binding": binding,
        "_fresh099_request": fresh099_request,
        "_fresh099_request_path": fresh099_request_path,
        "_manifest_path": manifest_path,
        "_xmf_path": xmf_path,
        "_receipt_path": receipt_path,
    }


def old_path_audit(fresh099_request: dict[str, Any]) -> dict[str, Any]:
    deferred = [str(item) for item in fresh099_request.get("deferred_input_files", [])]
    old_suffixes = sorted({
        "fresh098" if "fresh098" in path else "fresh099" if "fresh099" in path else "other"
        for path in deferred
        if "fresh098" in path or "fresh099" in path
    })
    old_static_examples = [
        path for path in deferred
        if Path(path).suffix.lower() not in RAW_SUFFIXES
        and ("fresh098" in path or "fresh099" in path)
    ][:4]
    return {
        "fresh099_old_deferred_attempt_suffixes": old_suffixes,
        "fresh099_old_static_deferred_examples": old_static_examples,
        "fresh099_old_raw_deferred_count": sum(
            Path(path).suffix.lower() in RAW_SUFFIXES
            for path in deferred
            if "fresh098" in path or "fresh099" in path
        ),
        "fresh099_old_raw_paths_not_reused": True,
        "fresh099_unchanged": True,
        "path_rebinding_reason": (
            "fresh099 retained immutable prior XMF/render deferred paths. "
            "fresh100 creates an independent disabled Root023 request bound to "
            "the actual Root547 manifest/case.xmf/output root."
        ),
    }


def safe_existing(paths: Iterable[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for raw in paths:
        path = Path(raw).resolve()
        if str(path) in seen or not path.is_file():
            continue
        seen.add(str(path))
        if path.suffix.lower() in RAW_SUFFIXES:
            continue
        if path.suffix.lower() not in STATIC_SUFFIXES:
            continue
        result.append(path)
    return result


def request_static_inputs(
    case_id: str,
    fresh099_binding_path: Path,
    fresh099_request_path: Path,
    fresh_row: dict[str, Any],
    typed: dict[str, Any],
    xmf: dict[str, Any],
    known: dict[str, str],
) -> list[Path]:
    candidates: list[Path] = [
        RUNTIME, STRICT, RESOURCE, ROOT230_ENTRY, ROOT230_HOME, ROOT230_CONTRACT,
        ROOT134_GPU, ROOT023 / "README.md", RENDERER, ENV, MESA_JSON, PV_PYTHON,
        FRESH099 / "source-binding.json",
        FRESH099 / "metadata/typed-lifecycle-contract.json",
        FRESH099 / "evidence/root533-conversion-report-snapshot.json",
        FRESH099 / "evidence/fresh098-xmf-result-snapshot.json",
        fresh099_binding_path, fresh099_request_path,
        ROOT547 / f"{case_id}-xmf-request.json",
        ROOT547 / "bindings" / f"{case_id}-actual-xmf-binding.json",
    ]
    for item in (
        typed.get("request"), typed.get("receipt"), typed.get("report"),
        xmf.get("root547_request"), xmf.get("root547_binding"),
        xmf.get("receipt"), xmf.get("manifest"), xmf.get("case_xmf"),
        fresh_row.get("request"),
    ):
        path = as_path(item)
        if path:
            candidates.append(path)
    # The known map is intentionally passed explicitly so a renderer binary
    # can use an already recorded digest without being opened here.
    _ = known
    return safe_existing(candidates)


def render_request(
    case_id: str,
    xmf: dict[str, Any],
    typed: dict[str, Any],
    binding_path: Path,
    fresh099_request_path: Path,
    fresh099_request: dict[str, Any],
    known: dict[str, str],
) -> dict[str, Any]:
    attempt_id = f"root-stage1-f4-{case_id.lower()}-full1201-render-fresh100"
    output_root = DATA / "families/F4" / case_id / attempt_id
    manifest_path = as_path(xmf.get("manifest"))
    xmf_path = as_path(xmf.get("case_xmf"))
    receipt_path = as_path(xmf.get("receipt"))
    trajectory_path = None
    manifest = load_json(manifest_path) if manifest_path and manifest_path.is_file() else None
    if manifest:
        trajectory_path = as_path(manifest.get("trajectory_h5"))
    static_inputs = request_static_inputs(
        case_id, binding_path, fresh099_request_path,
        {"request": typed.get("request")}, typed, xmf, known,
    )
    command = [
        str(ENV),
        "VTK_SMP_MAX_THREADS=2",
        "LP_NUM_THREADS=2",
        "LIBGL_ALWAYS_SOFTWARE=1",
        "MESA_LOADER_DRIVER_OVERRIDE=llvmpipe",
        "__EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/50_mesa.json",
        "VTK_DEFAULT_OPENGL_WINDOW=vtkEGLRenderWindow",
        "QT_QPA_PLATFORM=offscreen",
        "OMP_NUM_THREADS=2",
        str(PV_PYTHON),
        "--force-offscreen-rendering",
        str(RENDERER),
        "--manifest",
        str(manifest_path) if manifest_path else str(
            DATA / "families/F4" / case_id / "root-stage1-f4-unknown-root547/manifest.json"
        ),
        "--output-dir",
        "{attempt_root}",
    ]
    input_sha = {str(path): sha_static(path, known) for path in static_inputs}
    deferred = [trajectory_path] if trajectory_path else []
    deferred = [path for path in deferred if path is not None]
    request = {
        "schema": "ds02.runner-request.v2",
        "family_id": "F4",
        "case_id": case_id,
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 2,
        "max_wall_seconds": 14400,
        "estimated_storage_bytes": 12 * 1024**3,
        "cwd": str(INTEGRATION / "lagrangian-fluid-lab"),
        "worktree_root": str(WORKTREE),
        "command": command,
        "input_files": [str(path) for path in static_inputs],
        "input_sha256": input_sha,
        "deferred_input_files": [str(path) for path in deferred],
        "deferred_input_sha256": {str(path): None for path in deferred},
        "depends_on_attempts": [
            str(typed.get("attempt_id")) if typed.get("attempt_id") else None,
            str(xmf.get("root547_attempt_id")) if xmf.get("root547_attempt_id") else None,
        ],
        "disabled": True,
        "execution_allowed": False,
        "launch": False,
        "launch_allowed": False,
        "launch_owner": "root",
        "source_only": True,
        "status": "source_only_disabled_root547_bound" if xmf.get("root547_registered") else "source_only_disabled_waiting_root547",
        "disabled_reason": (
            "Root-only continuation. This request renders the actual Root547 "
            "manifest with Root023 software Mesa/CPU settings; it never relaunches "
            "Root533 conversion or Root547 XMF export. Future render artifacts "
            "remain null until Root enables and audits the request."
        ),
        "independent_case_count_increment": 0,
        "root_review_required": True,
        "scope_id": SCOPE,
        "precision_status": "not_accepted",
        "production_approval": "none",
        "q_n_status": "not_assessed",
        "arrays_read_by_source": False,
        "jobs_started_by_source": False,
        "shared_registry_write_by_source": False,
        "expected_frames": 1201,
        "expected_particles": (xmf.get("manifest_summary") or {}).get("expected_particles") or 83233,
        "vector_semantic_type": "N3",
        "renderer": {
            "kind": "Root023",
            "script": str(RENDERER),
            "script_sha256": RENDERER_SHA,
            "software": "Mesa llvmpipe CPU",
            "threads": 2,
            "all_temporal_frames_required": True,
        },
        "root230_policy": {
            "entry": str(ROOT230_ENTRY),
            "home_floor_gib": 500,
            "nvme_floor_gib": 100,
            "stage_cap_gib": 24,
            "foreign_gpu_processes_protected": True,
        },
        "expected_outputs": {
            "output_root": str(output_root),
            "case_pvsm": str(output_root / "case.pvsm"),
            "full_saved_animation_gif": str(output_root / "full_saved_animation.gif"),
            "report": str(output_root / "paraview-full-animation-report.json"),
            "execution_receipt": str(output_root / "execution-receipt.json"),
            "all_sha256": None,
        },
        "future_sha256_values": "null until Root independently enables and completes Root023 render",
        "future_render_hashes": {
            "case_pvsm": None,
            "full_saved_animation_gif": None,
            "report": None,
            "execution_receipt": None,
        },
        "root547_metadata": {
            "status": xmf.get("status"),
            "manifest": xmf.get("manifest"),
            "case_xmf": xmf.get("case_xmf"),
            "receipt": xmf.get("receipt"),
            "actual_hdf5_hashes_omitted": True,
        },
        "fresh099_path_audit": old_path_audit(fresh099_request),
        "source_did_not_read_or_hash_h5": True,
    }
    return request


def main() -> None:
    for directory in (PACKAGE / "bindings", PACKAGE / "requests", PACKAGE / "evidence", PACKAGE / "metadata"):
        directory.mkdir(parents=True, exist_ok=True)
    known = known_hashes_from_fresh099()
    fresh_rows, fresh_evidence_path = fresh099_rows()
    case_ids = sorted(fresh_rows)
    typed_snapshot: list[dict[str, Any]] = []
    xmf_snapshot: list[dict[str, Any]] = []
    binding_rows: list[dict[str, Any]] = []
    request_rows: list[dict[str, Any]] = []
    for case_id in case_ids:
        fresh_binding_path, fresh_binding, fresh_request_path, fresh_request = fresh099_binding(case_id)
        xmf = root547_state(case_id, fresh_request_path, fresh_request, known)
        typed = root533_typed_state(case_id, xmf.get("_binding") or {}, fresh_rows[case_id], known)
        typed_snapshot.append(typed)
        xmf_public = {key: value for key, value in xmf.items() if not key.startswith("_")}
        xmf_snapshot.append(xmf_public)
        render_binding_path = PACKAGE / "bindings" / f"{case_id}-render-fresh100-binding.json"
        render_request_path = PACKAGE / "requests" / f"{case_id}-full1201-render-fresh100-disabled.request.json"
        physical_binding = strip_payload_paths((xmf.get("_binding") or {}).get("physical_binding") or {})
        binding = {
            "schema": "ds02.f4.fresh100.root547-xmf-root023-binding.v1",
            "scope_id": SCOPE,
            "case_id": case_id,
            "physical_case_id": (xmf.get("_binding") or {}).get("physical_case_id", case_id),
            "physical_binding": physical_binding,
            "scope_separation": {
                "actual_converter_scope": strip_payload_paths((xmf.get("_binding") or {}).get("actual_converter_scope") or {}),
                "source_owner_scope_retained": True,
                "source_plan_scope_retained": True,
                "source_owner_sha256_not_reused_as_converter_scope": True,
                "semantic_binding_status": "legacy_incomplete; no cross-resolution physical claim",
            },
            "typed_evidence": {
                "root533": typed,
                "fresh099_snapshot": {
                    "path": str(fresh_evidence_path),
                    "sha256": sha_static(fresh_evidence_path, known),
                    "case_typed_status_at_snapshot": fresh_rows[case_id].get("typed_status"),
                },
                "root533_mk_type_uid_lifecycle": typed.get("report_summary", {}).get("typed_identity_lifecycle")
                if typed.get("report_summary") else None,
            },
            "root547_xmf_evidence": xmf_public,
            "renderer": {
                "kind": "Root023",
                "script": str(RENDERER),
                "script_sha256": RENDERER_SHA,
                "all_temporal_frames_required": True,
                "expected_frames": 1201,
                "vector_semantic_type": "N3",
                "software": "Mesa llvmpipe CPU",
                "cpu_threads": 2,
            },
            "typed_lifecycle_policy": {
                "preserve_mk_type_uid_lifecycle": True,
                "no_padding": True,
                "no_reclassification": True,
                "no_mass_rescale": True,
                "observed_exclusions_are_retained": True,
            },
            "future_render_hashes": {
                "case_pvsm": None,
                "full_saved_animation_gif": None,
                "report": None,
                "execution_receipt": None,
            },
            "arrays_read_by_source": False,
            "jobs_started_by_source": False,
            "shared_registry_write_by_source": False,
            "source_did_not_read_or_hash_h5": True,
        }
        dump(render_binding_path, binding)
        request = render_request(
            case_id, xmf, typed, render_binding_path,
            fresh_request_path, fresh_request, known,
        )
        dump(render_request_path, request)
        binding_rows.append({
            "case_id": case_id,
            "path": str(render_binding_path.resolve()),
            "sha256": sha_static(render_binding_path),
            "root547_status": xmf.get("status"),
            "typed_status": typed.get("typed_status"),
        })
        request_rows.append({
            "case_id": case_id,
            "kind": "root023_render",
            "launch_allowed": False,
            "path": str(render_request_path.resolve()),
            "sha256": sha_static(render_request_path),
            "root547_status": xmf.get("status"),
            "typed_status": typed.get("typed_status"),
        })

    dump(PACKAGE / "evidence/root533-conversion-snapshot.json", {
        "schema": "ds02.f4.fresh100.root533-conversion-json-evidence.v1",
        "source_evidence": str(fresh_evidence_path),
        "source_evidence_sha256": sha_static(fresh_evidence_path, known),
        "claim_boundary": (
            "Each row is bound to the actual Root533 conversion-report.json and "
            "execution-receipt.json referenced by Root547. The report is compacted "
            "to Mk/Type/UID lifecycle metadata; payload arrays and H5 digests are "
            "not read or copied."
        ),
        "cases": typed_snapshot,
        "case_count": len(typed_snapshot),
        "vector_contract": {"semantic_type": "N3", "components": ["vx", "vy", "vz"]},
        "arrays_read_by_source": False,
        "jobs_started_by_source": False,
        "shared_registry_write_by_source": False,
        "h5_hashes_omitted_by_source": True,
    })
    dump(PACKAGE / "evidence/root547-xmf-metadata-snapshot.json", {
        "schema": "ds02.f4.fresh100.root547-xmf-metadata-evidence.v1",
        "claim_boundary": (
            "Root547 receipt/manifest and case.xmf XML metadata were read only "
            "after Root547 publication. XMF HDF references are counted but their "
            "paths and H5 bytes/digests are omitted."
        ),
        "cases": xmf_snapshot,
        "case_count": len(xmf_snapshot),
        "arrays_read_by_source": False,
        "jobs_started_by_source": False,
        "shared_registry_write_by_source": False,
        "h5_hashes_omitted_by_source": True,
    })
    audit_rows = []
    for case_id in case_ids:
        _, _, fresh_request_path, fresh_request = fresh099_binding(case_id)
        xmf = next(row for row in xmf_snapshot if row["case_id"] == case_id)
        audit_rows.append({
            "case_id": case_id,
            "fresh099_request": str(fresh_request_path),
            "fresh099_old_path_audit": old_path_audit(fresh_request),
            "root547_actual_attempt_id": xmf.get("root547_attempt_id"),
            "root547_actual_output_root": xmf.get("output_root"),
            "root547_manifest": xmf.get("manifest"),
            "root547_case_xmf": xmf.get("case_xmf"),
            "root547_receipt": xmf.get("receipt"),
            "new_fresh100_attempt_id": f"root-stage1-f4-{case_id.lower()}-full1201-render-fresh100",
            "new_output_root": str(DATA / "families/F4" / case_id / f"root-stage1-f4-{case_id.lower()}-full1201-render-fresh100"),
            "future_output_hashes": {"case_pvsm": None, "gif": None, "report": None, "receipt": None},
            "fresh099_unchanged": True,
        })
    dump(PACKAGE / "metadata/path-rebinding-audit.json", {
        "schema": "ds02.f4.fresh100.path-rebinding-audit.v1",
        "reason": "fresh099 deferred paths mixed immutable fresh098 XMF/render attempts with Root547 metadata; fresh100 uses a new disabled attempt per case.",
        "cases": audit_rows,
        "old_package_modified_by_source": False,
        "new_render_outputs_are_future_only": True,
        "h5_paths_read_or_hashed_by_source": False,
    })
    dump(PACKAGE / "requests/index.json", {
        "schema": "ds02.f4.fresh100-root023-render-request-index.v1",
        "scope_id": SCOPE,
        "family_id": "F4",
        "case_count": len(case_ids),
        "request_count": len(request_rows),
        "requests": request_rows,
        "future_output_hashes": None,
        "independent_case_count_increment": 0,
        "launch_allowed": False,
        "root547_status_counts": {
            status: sum(row.get("root547_status") == status for row in request_rows)
            for status in sorted({row.get("root547_status") for row in request_rows})
        },
        "typed_status_counts": {
            status: sum(row.get("typed_status") == status for row in request_rows)
            for status in sorted({row.get("typed_status") for row in request_rows})
        },
    })
    dump(PACKAGE / "source-binding.json", {
        "schema": "ds02.f4.fresh100-source-binding.v1",
        "scope_id": SCOPE,
        "family_id": "F4",
        "case_count": len(case_ids),
        "fresh099_unchanged": True,
        "fresh099_old_xmf_attempt_suffix": "fresh098",
        "fresh099_new_render_attempt_suffix": "fresh099",
        "root547_actual_attempt_suffix": "root547",
        "root547_manifest_and_xmf_are_actual_metadata": True,
        "root023_full_temporal_frames": 1201,
        "root023_vector_semantic_type": "N3",
        "root023_cpu_threads": 2,
        "mesa_software_rendering": True,
        "future_output_hashes": None,
        "independent_case_count_increment": 0,
        "arrays_read_by_source": False,
        "jobs_started_by_source": False,
        "shared_registry_write_by_source": False,
        "h5_read_or_hashed_by_source": False,
        "future_requests_disabled": True,
    })


if __name__ == "__main__":
    main()
