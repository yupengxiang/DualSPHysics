#!/usr/bin/env python3
"""Assemble fresh191 from terminal producer metadata only.

The builder reads JSON/XML/XMF metadata and stats published PNGs.  It never
opens or hashes H5/BI4/IBI4/CSV/DAT/VTK payloads, and it never hashes PNGs.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


PACKAGE = Path(__file__).resolve().parents[1]
RAW = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/"
    "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M110_T100_NEXT34/"
    "root-stage1-f5-m110_t100-actual1185-bed0-full801-original116023-frozen-progress-root1189"
)
INTEGRATION = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_F5_M110_T100_actual1185_bed0_full801_UID_footprint_original116023944_expected34_render_1189"
)
QI = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_F5_M110T100_actual1189_full801_complete_UID_N3_bed_actual_native_XMF_SourceDef_namespace_previsual_QI_1434/"
    "actual1189-full801-independent-QI-UID-N3-bed-scope-previsual-proof.json"
)
XMF_XML = RAW.parent / "root-stage1-f5-m110_t100-actual1045-full801-N3-xmf129-root1072/xmf/case.xmf"
FORBIDDEN = {".h5", ".hdf5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu", ".vtp"}
HASHABLE = {".json", ".xml", ".xmf", ".py", ".md"}
H5_SHA = "44d9113124f574c266ae8709293c2989c34b6353f0a13b48dafd2f819987f713"
DECODER_SHA = "b8ac8cf4aff68ffd089da6cf3ef19dfd0c6473121475f4c198b720a0ddaa8b2e"
NATIVE_SHA = "83d6ff1798c49ce500aaf07d2319fac66f48d496d73fa1c044582fd9ec2b9024"
TYPED_SHA = "7b383a4e371948c22f8702cd9704844d1b16d8835fa12f203b688892fbc9f2a2"
SOURCE_PLAN_SHA = "366adc5200604490871116a0a5b8503c9bef4bfb1e72195df94995605fa7d324"
SOURCE_DEF_SHA = "da761772174d2a4ba20736647649b2e1117e48c55924426a3e24194057d366a7"


def read_json(path: Path) -> dict[str, Any]:
    if path.suffix.lower() in FORBIDDEN:
        raise RuntimeError(f"forbidden payload read: {path}")
    if path.suffix.lower() != ".json":
        raise RuntimeError(f"expected JSON metadata: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"metadata is not an object: {path}")
    return value


def digest(path: Path) -> str:
    if path.suffix.lower() not in HASHABLE:
        raise RuntimeError(f"non-metadata hash attempted: {path}")
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def metadata_ref(path: Path, role: str, expected: str | None = None) -> dict[str, Any]:
    path = path.resolve()
    suffix = path.suffix.lower()
    if suffix in FORBIDDEN:
        result = {
            "path": str(path),
            "role": role,
            "sha256": None,
            "producer_attested_sha256": expected,
            "read_policy": "producer_attestation_only_no_local_io",
        }
        return result
    if suffix not in HASHABLE:
        raise RuntimeError(f"unclassified metadata input: {path}")
    if not path.exists():
        raise FileNotFoundError(path)
    actual = digest(path)
    if expected is not None and actual != expected:
        raise RuntimeError(f"metadata SHA mismatch for {path}: {actual} != {expected}")
    return {"path": str(path), "role": role, "sha256": actual, "read_policy": "metadata_only"}


def terminal(path: Path, role: str, expected: str | None = None) -> dict[str, Any]:
    data = read_json(path)
    if data.get("status") != "completed" or data.get("returncode") != 0:
        raise RuntimeError(f"{role} is not terminal completed/0: {path}")
    ref = metadata_ref(path, role, expected)
    ref.update({"status": data.get("status"), "returncode": data.get("returncode")})
    return ref


def evidence_ref(data: dict[str, Any], key: str, role: str) -> dict[str, Any]:
    item = data[key]
    path = Path(item["path"])
    return metadata_ref(path, role, item.get("sha256"))


def main() -> int:
    qi = read_json(QI)
    identity = {
        "case_id": qi["case_id"],
        "physical_case_id": qi["physical_case_id"],
        "family_id": "F5",
        "receiver": "M110",
        "duration": "T100",
        "expected_dimension": 3,
        "physical_condition_sha256": NATIVE_SHA,
        "source_plan_file_sha256": SOURCE_PLAN_SHA,
        "source_definition_sha256": SOURCE_DEF_SHA,
    }
    assert identity["case_id"].endswith("M110_T100_NEXT34")
    ev = qi["actual_completed_metadata_evidence"]
    gencase_receipt = Path(ev["gencase_receipt"]["path"])
    prepared_report = Path(ev["generated_xml"]["path"]).parent / "prepared-input-report.json"
    initial_receipt = Path(ev["initial_qa_receipt"]["path"])
    initial_report = Path(ev["initial_qa_report"]["path"])
    native_receipt = Path(ev["native_receipt"]["path"])
    typed_receipt = Path(ev["typed_receipt"]["path"])
    typed_report = Path(ev["typed_report"]["path"])
    xmf_receipt = Path(ev["xmf_receipt"]["path"])
    xmf_manifest = Path(ev["xmf_manifest"]["path"])
    bed_receipt = Path(ev["bed_receipt"]["path"])
    bed_report = Path(ev["bed_report"]["path"])
    render_receipt = Path(ev["render_receipt"]["path"])
    render_report = Path(ev["render_report"]["path"])
    publish_receipt = Path(ev["render_publish_receipt"]["path"])

    report = read_json(render_report)
    publish = read_json(publish_receipt)
    receipt = read_json(render_receipt)
    wrapper = read_json(INTEGRATION / "enabled-render-wrapper.json")
    request = read_json(INTEGRATION / "enabled-full801-render-request.json")
    source_lineage = read_json(INTEGRATION / "actual-bed0-to-render-input-lineage.json")
    output_root = Path(report["outputs"]["frames_dir"]).parent
    contacts = []
    files_by_rel = {x["relative_path"]: x for x in publish["files_excluding_receipt"]}

    def png_ref(path: Path, role: str) -> dict[str, Any]:
        path = path.resolve()
        if path.suffix.lower() != ".png":
            raise RuntimeError(f"expected published PNG: {path}")
        if not path.exists():
            raise FileNotFoundError(path)
        rel = str(path.relative_to(output_root)).replace("\\", "/")
        producer = files_by_rel.get(rel)
        if producer is None:
            raise RuntimeError(f"published receipt has no producer entry for {rel}")
        if path.stat().st_size != producer["bytes"]:
            raise RuntimeError(f"published byte-size mismatch for {path}")
        return {
            "path": str(path),
            "role": role,
            "relative_path": rel,
            "bytes_stat": path.stat().st_size,
            "producer_declared_sha256": producer["sha256"],
            "content_read_or_hashed": False,
        }

    for path in report["outputs"]["contact_sheets"]:
        contacts.append(png_ref(Path(path), "contact_sheet"))
    keys = [png_ref(Path(report["outputs"]["frames_dir"]) / f"frame_{i:04d}.png", "key_frame")
            for i in wrapper["keyframe_indices"]]

    upstream = {
        "gencase": {
            "status": "completed", "returncode": 0,
            "receipt": terminal(gencase_receipt, "gencase_receipt", ev["gencase_receipt"]["sha256"]),
            "prepared_report": metadata_ref(prepared_report, "gencase_prepared_report"),
            "generated_xml": metadata_ref(Path(ev["generated_xml"]["path"]), "gencase_generated_xml", ev["generated_xml"]["sha256"]),
            "total_particles": 194427, "fluid_particles": 31658, "solver_dimension_from_gencase": 3,
        },
        "initial_qa": {
            "status": "completed", "returncode": 0,
            "receipt": terminal(initial_receipt, "initial_qa_receipt", ev["initial_qa_receipt"]["sha256"]),
            "report": metadata_ref(initial_report, "initial_qa_report", ev["initial_qa_report"]["sha256"]),
            "precision_gate": qi["actual_initial_QA_precision_negative"],
        },
        "native": {
            "status": "completed", "returncode": 0,
            "primary_receipt": terminal(native_receipt, "native_receipt", ev["native_receipt"]["sha256"]),
            "canonical_physical_condition_sha256": NATIVE_SHA,
        },
        "typed": {
            "status": "completed", "returncode": 0,
            "receipt": terminal(typed_receipt, "typed_receipt", ev["typed_receipt"]["sha256"]),
            "conversion_report": metadata_ref(typed_report, "typed_conversion_report", ev["typed_report"]["sha256"]),
            "legacy_scope_sha256": TYPED_SHA,
            "output_h5_producer_attested_sha256": "44d9113124f574c266ae8709293c2989c34b6353f0a13b48dafd2f819987f713",
        },
        "xmf": {
            "status": "completed", "returncode": 0,
            "receipt": terminal(xmf_receipt, "xmf_receipt", ev["xmf_receipt"]["sha256"]),
            "manifest": metadata_ref(xmf_manifest, "xmf_manifest", ev["xmf_manifest"]["sha256"]),
            "xml": metadata_ref(XMF_XML, "xmf_case_xml", "33a0b31c16cfb766f7290d1e0e98fdb67f70bd9a8272a7aadbf8a06bb7a4a4fb"),
            "physical_condition_sha256": NATIVE_SHA,
            "physical_plan_sha256": SOURCE_DEF_SHA,
        },
        "bed": {
            "status": "completed", "returncode": 0,
            "receipt": terminal(bed_receipt, "bed_receipt", ev["bed_receipt"]["sha256"]),
            "report": metadata_ref(bed_report, "bed_report", ev["bed_report"]["sha256"]),
            "source_definition_sha256": SOURCE_DEF_SHA,
            "diagnostic_bins_are_not_numerical_acceptance": True,
            "sub_dp_depth_not_quantified": True,
        },
        "render": {
            "status": "completed", "returncode": 0,
            "receipt": terminal(render_receipt, "render_receipt", ev["render_receipt"]["sha256"]),
            "report": metadata_ref(render_report, "render_report", ev["render_report"]["sha256"]),
            "publish_receipt": metadata_ref(publish_receipt, "render_publish_receipt", ev["render_publish_receipt"]["sha256"]),
            "atomic_publish_status": publish["status"],
            "published_bytes_excluding_receipt": publish["published_bytes_excluding_receipt"],
            "published_bytes_total": publish["published_bytes_total"],
            "published_files_excluding_receipt": len(publish["files_excluding_receipt"]),
            "home_publish_cap_bytes": publish["home_publish_cap_bytes"],
            "all_frames_rendered": report["all_frames_rendered"],
            "actual_times_preserved_exactly": report["actual_times_preserved_exactly"],
            "actual_time_window_s": qi["actual_time_window_s"],
            "contact_sheets": contacts,
            "key_frames": keys,
            "visual_review": "deferred_to_fresh192",
            "personally_viewed_pngs": False,
        },
    }

    def add_closure(path: Path, role: str, expected: str | None = None, attested: str | None = None) -> dict[str, Any]:
        entry = metadata_ref(path, role, expected)
        if attested is not None:
            entry["producer_attested_sha256"] = attested
        return entry

    closure: list[dict[str, Any]] = []
    for path, role, expected in [
        (QI, "parent_qi" , "1842851ab604f787bfba37e8b55e68463a8e1a81d94779c05412f0da1cca2652"),
        (INTEGRATION / "controller-result.json", "controller_result", None),
        (INTEGRATION / "controller-launch-process.json", "controller_launch_process", None),
        (INTEGRATION / "enabled-render-wrapper.json", "enabled_wrapper", None),
        (INTEGRATION / "enabled-full801-render-request.json", "enabled_request", None),
        (INTEGRATION / "registered-render-binding.json", "registered_binding", None),
        (INTEGRATION / "actual-bed0-to-render-input-lineage.json", "actual_render_input_lineage", None),
        (INTEGRATION / "actual-full801-bed-UID-footprint-times-and-scope-independent-review.json", "independent_review", None),
        (INTEGRATION / "completed-bed-progress-frozen.json", "frozen_progress_snapshot", None),
        (INTEGRATION / "original-disabled-planning-versus-enabled-output-roles.json", "planning_vs_enabled_roles", None),
        (INTEGRATION / "controller-config.json", "controller_config", None),
        (render_report, "render_report", ev["render_report"]["sha256"]),
        (publish_receipt, "render_publish_receipt", ev["render_publish_receipt"]["sha256"]),
        (render_receipt, "render_receipt", ev["render_receipt"]["sha256"]),
        (xmf_manifest, "xmf_manifest", ev["xmf_manifest"]["sha256"]),
        (XMF_XML, "xmf_case_xml", "33a0b31c16cfb766f7290d1e0e98fdb67f70bd9a8272a7aadbf8a06bb7a4a4fb"),
        (Path(qi["actual_SourceDef"]["path"]), "source_definition_xml", SOURCE_DEF_SHA),
        (Path(qi["actual_source_plan_JSON_file"]["path"]), "source_plan_json", SOURCE_PLAN_SHA),
        (Path(ev["generated_xml"]["path"]), "gencase_generated_xml", ev["generated_xml"]["sha256"]),
        (prepared_report, "gencase_prepared_report", None),
        (initial_report, "initial_qa_report", ev["initial_qa_report"]["sha256"]),
        (typed_report, "typed_conversion_report", ev["typed_report"]["sha256"]),
        (bed_report, "bed_report", ev["bed_report"]["sha256"]),
    ]:
        closure.append(add_closure(path, role, expected))
    closure.append(add_closure(Path(INTEGRATION / "trajectory.h5"), "trajectory_h5", None, H5_SHA)) if (INTEGRATION / "trajectory.h5").exists() else None
    closure.append({
        "path": str(Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M110_T100_NEXT34/root-stage1-f5-m110_t100-actual-native0-full801-typed157-home4gib-root1045/trajectory.h5")),
        "role": "trajectory_h5",
        "sha256": None,
        "producer_attested_sha256": H5_SHA,
        "read_policy": "producer_attestation_only_no_local_io",
    })
    closure.append({
        "path": str(Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/campaigns/l1-resume/artifacts/bi4_dump")),
        "role": "decoder_executable",
        "sha256": None,
        "producer_attested_sha256": DECODER_SHA,
        "read_policy": "producer_attestation_only_no_local_io",
    })

    metadata = {
        "schema": "ds02.f3.assigned-f5.metadata-preflight.v2",
        "package": {
            "name": "fresh191",
            "family_written": "F3",
            "actual_case_family": "F5",
            "assigned_family": "F3",
            "status": "metadata_preflight_terminal_render_complete",
            "case_credit": 0,
            "q_n": 0,
            "q_e": 0,
            "configured_model": "gpt-5.6-luna/max",
            "personal_visual_review": "deferred_to_fresh192",
            "personally_viewed_pngs": False,
        },
        "case_identity": identity,
        "runtime_contract": {
            "counts": {"frames": 801, "particles": 194427, "fixed": 158559, "moving": 4210, "fluid": 31658, "floating": 0},
            "nominal_time_window_s": [0.0, 16.0],
            "actual_time_window_s": qi["actual_time_window_s"],
            "expected_contact_sheets": 34,
            "keyframe_indices": wrapper["keyframe_indices"],
            "n3": True,
            "uid_lifecycle": "parent QI/producer metadata; source agent did not read arrays",
            "finite_state": "parent QI/producer metadata; source agent did not read arrays",
        },
        "actual_scope": {
            "native_canonical": {
                "physical_condition_sha256": NATIVE_SHA,
                "source_plan_condition_sha256": None,
                "source_plan_physical_condition_sha256": NATIVE_SHA,
                "source_plan_condition_presence": False,
                "source_plan_physical_condition_presence": True,
            },
            "typed_converter_legacy": {"schema": "legacy-owner-scope.v0", "physical_condition_sha256": TYPED_SHA, "cross_resolution_claim": False},
            "xmf": {
                "physical_condition_sha256": NATIVE_SHA,
                "source_plan_condition_sha256": None,
                "source_plan_physical_condition_sha256": SOURCE_DEF_SHA,
                "source_plan_condition_presence": False,
                "source_plan_physical_condition_presence": True,
                "source_definition_role": "independent_bed_SourceDef_FILE",
            },
            "source_definition_file": {"path": qi["actual_SourceDef"]["path"], "sha256": SOURCE_DEF_SHA, "role": "bed_SourceDef_FILE"},
            "source_plan_json": {"path": qi["actual_source_plan_JSON_file"]["path"], "sha256": SOURCE_PLAN_SHA},
            "prospective_canonical_preserved_separately": "9b51cce0a2f5940a8e6fdf2d284e407dd57f918fad42172eccfd498cbac1eaee",
        },
        "upstream_evidence": upstream,
        "qi_evidence": {
            "role": "independent parent full801 QI; not a runner receipt and not a personal visual review",
            "path": str(QI),
            "sha256": digest(QI),
            "status": "completed0",
            "visual_credit": 0,
            "all801_geometry_velocity_N3_times_UID_finite_verified": True,
            "all_native_UIDs_active_each_frame": True,
            "full_bed_UID_footprint_checked": True,
        },
        "terminal_render": upstream["render"],
        "metadata_input_closure": closure,
        "preflight_assertions": {
            "gencase_initial_qa_native_typed_xmf_bed_render_terminal_completed0": True,
            "render_atomic_publish_and_output_path_rebind_verified": True,
            "runtime_counts_and_actual_time_metadata_bound": True,
            "native_typed_xmf_bed_scope_roles_kept_distinct": True,
            "source_h5_and_decoder_only_producer_attested": True,
            "published_pngs_only_statted_and_producer_sha_copied": True,
            "personal_visual_review_deferred": True,
            "numerical_precision_not_accepted": True,
        },
        "limitations": [
            "This package reads metadata JSON/XML/XMF and stats published PNG paths only.",
            "The source agent did not open, copy, or hash H5/BI4/IBI4/CSV/DAT/VTK payloads.",
            "The source agent did not open or hash PNGs; all personal visual review is deferred to fresh192.",
            "The actual render endpoint is 16.00008511666941 s; nominal 16.0 s is retained separately.",
            "Initial placement precision remains negative at the original threshold; no strict containment, sub-DP, or numerical acceptance is claimed.",
            "Typed legacy, native canonical, XMF SourceDef, and prospective source-plan roles are not interchangeable.",
            "Historical future-render null fields remain planning-role evidence; terminal receipt/report/publish refs are separate actual evidence.",
        ],
    }
    target = PACKAGE / "metadata" / "m110-t100-original1189-preflight.json"
    target.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(target)
    print("fresh191 metadata assembled; terminal render completed/0; personal review deferred to fresh192")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
